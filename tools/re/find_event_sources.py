# -*- coding: utf-8 -*-
"""（v4.13 新增，可复用）：把 exe 里 `BSTEventSource<X>` 的 **vtable / 静态全局对象** 找出来。

动机（v4.13）：
    v4.12 已证明「往 UI 的菜单事件源挂 sink」这条路通，但**搜刮界面根本不是菜单**
    （实测：投影出现那一刻没有任何 ContainerMenu 事件，IsMenuOpen 快照里只有 HUD/HUDMessages）。
    ⇒ 换「引擎自己发的事件」。commonlibsf 里这些事件源的 `GetEventSource` 的 REL::ID 全是 0，
    注释里的 ID 也对不上（本轮实测：那些 ID 指向别的函数）⇒ 用 **RTTI 名字** 反查：

        名字串(.rdata) → TypeDescriptor（TD = 名字 - 0x10）
        → 找 4 字节 == TD RVA 的位置 ⇒ pTypeDescriptor 字段 ⇒ **COL = 该位置 - 12**
        → 找 8 字节 == IB + COL RVA 的位置 ⇒ vtable[-8] ⇒ **vtable = 该位置 + 8**
        → 找 8 字节 == IB + vtable RVA 的位置 ⇒ **静态对象**（.data 里的那个 slot）

    ★ 校准样本（已知答案）：`BSTEventSource<MenuOpenCloseEvent>` 的
      vtable = 0x4D7E3D8（v4.12 用 UI 构造函数实证），COL = 0x52FF550。

用法：
    python out/find_event_sources.py                 # 全部
    python out/find_event_sources.py Container Mode  # 只打名字里含这些子串的
"""
import struct
import sys
from pathlib import Path

import pefile

EXE = Path(r"D:\SteamLibrary\steamapps\common\Starfield\Starfield.exe")
image = EXE.read_bytes()
pe = pefile.PE(str(EXE), fast_load=True)
IB = pe.OPTIONAL_HEADER.ImageBase
SEC = [(s.Name.rstrip(b"\x00").decode("ascii", "replace"), s.VirtualAddress,
        s.SizeOfRawData, s.PointerToRawData, max(s.Misc_VirtualSize, s.SizeOfRawData))
       for s in pe.sections]


def o2r(off):
    for nm, va, raw, ptr, vs in SEC:
        if ptr <= off < ptr + raw:
            return va + (off - ptr), nm
    return None, None


def r2o(rva):
    for nm, va, raw, ptr, vs in SEC:
        if va <= rva < va + vs:
            return ptr + (rva - va)
    return None


def sec_of(rva):
    for nm, va, raw, ptr, vs in SEC:
        if va <= rva < va + vs:
            return nm
    return None


def q(rva):
    o = r2o(rva)
    return struct.unpack_from("<Q", image, o)[0] if o is not None else None


def find_u32(val, limit=200):
    pat = struct.pack("<I", val)
    out, p = [], 0
    while True:
        p = image.find(pat, p)
        if p < 0:
            return out
        out.append(p)
        p += 1
        if len(out) >= limit:
            return out


def find_u64(val, limit=200):
    pat = struct.pack("<Q", val)
    out, p = [], 0
    while True:
        p = image.find(pat, p)
        if p < 0:
            return out
        out.append(p)
        p += 1
        if len(out) >= limit:
            return out


def resolve(hit_off: int):
    """hit_off = 名字里 `?$BSTEventSource@` 的文件偏移。返回 (full_name, td_rva, cols, vts, objs)。"""
    out = []
    p = hit_off
    while p >= 0:
        name_off = image.rfind(b"\x00", 0, p) + 1   # 名字串起点（上一个 NUL 之后）
        td_off = name_off - 0x10
        if td_off < 0:
            break
        vft, spare = struct.unpack_from("<QQ", image, td_off)
        td_rva, _ = o2r(td_off)
        name = image[name_off:name_off + 300].split(b"\x00", 1)[0].decode("ascii", "replace")
        if td_rva is None or spare != 0 or not (IB <= vft < IB + 0x40000000) or "?$BSTEventSource@" not in name:
            break

        cols = []
        for off in find_u32(td_rva):
            col_off = off - 12
            if col_off < 0:
                continue
            sig, coff, cd, ptd = struct.unpack_from("<IIII", image, col_off)
            if sig not in (0, 1) or coff > 0x1000000 or cd > 0x1000000 or ptd != td_rva:
                continue
            # x64 的 COL 还有第 6 个字段 self（= 自己的 RVA）——用得上时校验
            self_rva = struct.unpack_from("<I", image, col_off + 20)[0]
            col_rva, _ = o2r(col_off)
            ok_self = (self_rva == col_rva)
            cols.append((col_rva, ok_self))

        vts = []
        for col_rva, ok_self in cols:
            for off in find_u64(IB + col_rva):
                vt_rva, _ = o2r(off)
                if vt_rva is None:
                    continue
                vt_rva += 8
                f0 = q(vt_rva)
                if f0 and IB <= f0 < IB + 0x8000000 and sec_of(f0 - IB) == ".text":
                    vts.append((vt_rva, col_rva, ok_self))
        objs = []
        for vt_rva, col_rva, _ in vts:
            for off in find_u64(IB + vt_rva):
                rr, nm = o2r(off)
                if rr is not None:
                    objs.append((rr, nm))
        out.append((name, td_rva, cols, vts, objs))
        break
    return out


def main():
    subs = [s.lower() for s in sys.argv[1:]]
    needle = b"?$BSTEventSource@"
    hits, p = [], 0
    while True:
        p = image.find(needle, p)
        if p < 0:
            break
        hits.append(p)
        p += 1
    print(f"RTTI 名字里含 \"{needle.decode()}\" 的字符串：{len(hits)} 处\n")

    # 同一名字可能在 .rdata/.data 里有多份（TD 不同）⇒ 全都要看
    rows = []
    seen_name = set()
    for h in hits:
        for r in resolve(h):
            if r[0] in seen_name:
                continue
            seen_name.add(r[0])
            rows.append(r)

    print(f"解析出 {len(rows)} 条\n")
    for name, td, cols, vts, objs in rows:
        if subs and not any(s in name.lower() for s in subs):
            continue
        print(name)
        print(f"    TD=0x{td:X}")
        for col_rva, ok_self in cols:
            print(f"    COL=0x{col_rva:X} (self 字段自洽={ok_self})")
        for vt_rva, col_rva, ok_self in vts:
            print(f"    vtable=0x{vt_rva:X}  (COL=0x{col_rva:X})  vtable[0]=0x{(q(vt_rva) or 0):X}")
        if not objs:
            print("    (没有 .data 全局对象引用该 vtable —— 可能内嵌在单例里)")
        seen = set()
        for rr, nm in objs:
            if rr in seen:
                continue
            seen.add(rr)
            o = r2o(rr)
            vals = [struct.unpack_from("<Q", image, o + i * 8)[0] for i in range(4)]
            print(f"    对象@RVA 0x{rr:X} (sec={nm}) 前 4 qword = " + ", ".join(f"0x{v:X}" for v in vals))
        print()


if __name__ == "__main__":
    main()
