#!/usr/bin/env python3
"""按 RTTI 类名找回 vtable + 虚函数地址（MSVC x64）。

背景：
    commonlibsf 的 `IDs.h` 只覆盖了作者手动挖过的类。像 `HighlightManager`
    这种类**只有 RTTI 名字**，没有 REL::ID。要调它的方法，必须自己找回 vtable。

MSVC x64 的 RTTI 布局（都是**镜像内 RVA/VA**，不是文件偏移）：
    TypeDescriptor        { void* vftable; void* spare; char name[]; }   ← name 就是 " .?AVFoo@@"
    CompleteObjectLocator { u32 signature; u32 offset; u32 cdOffset;
                            u32 pTypeDescriptor(RVA); u32 pClassDescriptor(RVA); u32 self(RVA); }
    vtable                [ -8 ] = &CompleteObjectLocator (8 字节 VA)
                          [  0 ] = 第一个虚函数 (8 字节 VA)
                          ...

所以定位链是：
    名字字符串 → TypeDescriptor → (找 4 字节 == TypeDescriptor RVA) → COL
    → (找 8 字节 == COL 的 VA) → vtable[-1] → vtable 本体

用法：
    python tools/re/rtti_vtable.py HighlightManager
    python tools/re/rtti_vtable.py HighlightManager --slots 40
    python tools/re/rtti_vtable.py HighlightManager --dis 3        # 反汇编第 3 个虚函数
    python tools/re/rtti_vtable.py HighlightManager --callers      # 谁调用了这些虚函数
"""
from __future__ import annotations

import argparse
import re
import struct
import sys
from pathlib import Path

EXE = Path(r"D:\SteamLibrary\steamapps\common\Starfield\Starfield.exe")


def load(exe: Path):
    import pefile

    data = exe.read_bytes()
    pe = pefile.PE(str(exe), fast_load=True)
    e_lfanew = struct.unpack_from("<I", data, 0x3C)[0]
    base = struct.unpack_from("<Q", data, e_lfanew + 0x30)[0]
    sections = []
    for s in pe.sections:
        sections.append(
            (s.Name.rstrip(b"\x00").decode("ascii", "replace"), s.VirtualAddress,
             s.SizeOfRawData, s.PointerToRawData,
             max(s.Misc_VirtualSize, s.SizeOfRawData))
        )
    return data, base, sections


def off_to_rva(sections, off: int) -> int | None:
    for _, va, raw, ptr, vsize in sections:
        if ptr <= off < ptr + raw:
            return va + (off - ptr)
    return None


def rva_to_off(sections, rva: int) -> int | None:
    for _, va, raw, ptr, vsize in sections:
        if va <= rva < va + vsize:
            return ptr + (rva - va)
    return None


def find_all(data: bytes, needle: bytes, limit: int = 64):
    out = []
    k = data.find(needle)
    while k != -1:
        out.append(k)
        if len(out) >= limit:
            break
        k = data.find(needle, k + 1)
    return out


def class_of_vtable(data, base, sections, vt_rva: int) -> str | None:
    """vtable 的 [-8] 槽指向 CompleteObjectLocator，顺着它能拿到类名。

    已知 vtable 地址（比如从「某个函数的地址被谁当 8 字节指针引用」反查出来的）想知道
    它是哪个类时用这个 —— 这是 rtti_vtable 的逆运算。
    """
    off = rva_to_off(sections, vt_rva - 8)
    if off is None:
        return None
    col_va = struct.unpack_from("<Q", data, off)[0]
    # 本游戏里实测两种写法都存在：vtable[-8] 有的存 COL 的 **VA**，有的（多继承
    # 的次级 vtable 区）存的是 **RVA**。两种都试。
    if base <= col_va < base + 0x20000000:
        col_rva = col_va - base
    elif 0 < col_va < 0x10000000:
        col_rva = col_va
    else:
        return None
    o = rva_to_off(sections, col_rva)
    if o is None:
        return None
    sig, coff, cd, ptd_rva, pcd_rva = struct.unpack_from("<IIIII", data, o)
    o2 = rva_to_off(sections, ptd_rva)
    if o2 is None:
        return None
    name = data[o2 + 0x10: o2 + 0x10 + 160].split(b"\x00", 1)[0].decode("ascii", "replace")
    return f"COL 0x{col_rva:X} vtable[-8] -> TD 0x{ptd_rva:X} name={name}"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("cls", nargs="?", help="类名，如 HighlightManager")
    ap.add_argument("--vtable", default=None, help="已知 vtable RVA（hex），反查它属于哪个类")
    ap.add_argument("--exe", default=str(EXE))
    ap.add_argument("--slots", type=int, default=24, help="dump vtable 前多少个槽")
    ap.add_argument("--dis", type=int, default=None, help="反汇编 vtable 第 N 个槽")
    ap.add_argument("--dis-count", type=int, default=60)
    ap.add_argument("--callers", action="store_true", help="列出直接 call 各虚函数的位置")
    a = ap.parse_args()

    data, base, sections = load(Path(a.exe))
    print(f"imageBase = 0x{base:X}")

    if a.vtable:
        vt = int(a.vtable, 16)
        info = class_of_vtable(data, base, sections, vt)
        print(info or "无法解析该 vtable 的 RTTI")
        print(f"\n===== vtable RVA 0x{vt:X} =====")
        for k in range(a.slots):
            o = rva_to_off(sections, vt + k * 8)
            if o is None or o + 8 > len(data):
                break
            q = struct.unpack_from("<Q", data, o)[0]
            if not (base <= q < base + 0x20000000):
                break
            print(f"  [+{k * 8:03X}] RVA 0x{q - base:X}")
        return 0

    if not a.cls:
        print("需要给类名，或用 --vtable")
        return 2

    # --- 1. TypeDescriptor ---
    # TypeDescriptor = { void* vftable; void* spare; char name[]; }，
    # 所以字符串本身在 TD + 0x10。逐个候选做形状校验，避免命中别处的同名文本。
    # ★ MSVC 的类/结构体前缀不同：class = `?AV`、struct = `?AU`、enum = `?AW`。
    #   GroundPathPathingNodeGenerator 这类是 struct（`?AU`），只试 `?AV` 会漏掉，
    #   所以三种前缀都试一遍（各自的命中合并）。
    hits = []
    for prefix in (".?AV", ".?AU", ".?AW"):
        hits.extend(find_all(data, (prefix + a.cls + "@@").encode(), 16))
    if not hits:
        print(f"找不到 RTTI 名 .?AV/?AU/?AW {a.cls!r}")
        return 2
    td_off = None
    for h in hits:
        cand = h - 0x10
        if cand < 0:
            continue
        vt, spare = struct.unpack_from("<QQ", data, cand)
        if base <= vt < base + 0x20000000 and spare == 0:
            td_off = cand
            break
    if td_off is None:
        # 退化：不校验，直接用第一个
        td_off = hits[0] - 0x10
        print("WARN: 未通过 TypeDescriptor 形状校验，退化为第一个命中")
    td_rva = off_to_rva(sections, td_off)
    print(f"TypeDescriptor: file 0x{td_off:X}  RVA 0x{td_rva:X}  VA 0x{base + td_rva:X}  "
          f"(name @ 0x{base + td_rva + 0x10:X})")

    # --- 2. CompleteObjectLocator：找 4 字节 == td_rva ---
    # x64 的 COL：signature 实测为 1（x86 才是 0），offset/cdOffset 一般很小。
    needle = struct.pack("<I", td_rva)
    cols = []
    for off in find_all(data, needle, 400):
        col_off = off - 12  # pTypeDescriptor 在 COL + 12
        if col_off < 0:
            continue
        sig, coff, cd, ptd = struct.unpack_from("<IIII", data, col_off)
        if ptd != td_rva:
            continue
        if sig not in (0, 1):
            continue
        if coff > 0x1000000 or cd > 0x1000000:
            continue
        cols.append(col_off)
    if not cols:
        print("找不到 CompleteObjectLocator")
        return 2
    col_off = cols[0]
    col_rva = off_to_rva(sections, col_off)
    print(f"COL:            file 0x{col_off:X}  RVA 0x{col_rva:X}  VA 0x{base + col_rva:X}")

    # --- 3. vtable：vtable[-8] 指向 COL ---
    # x64 MSVC 里这个槽通常是 8 字节 VA；个别版本写成 4 字节 RVA + 4 字节 0，两种都试。
    vt_slots = find_all(data, struct.pack("<Q", base + col_rva), 32)
    if not vt_slots:
        vt_slots = find_all(data, struct.pack("<Q", col_rva), 32)
        if vt_slots:
            print("NOTE: vtable 用的是 4 字节 RVA 形式的 COL 引用")
    if not vt_slots:
        print("找不到 vtable（没有引用 COL 的槽）")
        return 2

    for i, slot_off in enumerate(vt_slots):
        vt_rva = off_to_rva(sections, slot_off) + 8
        sec = next((s[0] for s in sections if s[1] <= vt_rva < s[1] + s[4]), "?")
        print(f"\n===== vtable #{i}  RVA 0x{vt_rva:X}  (section {sec}) =====")
        entries = []
        for k in range(a.slots):
            o = rva_to_off(sections, vt_rva + k * 8)
            if o is None or o + 8 > len(data):
                break
            q = struct.unpack_from("<Q", data, o)[0]
            if not (base <= q < base + 0x20000000):
                break
            entries.append(q - base)
            print(f"  [+{k * 8:03X}] RVA 0x{entries[-1]:X}")
        if a.dis is not None and 0 <= a.dis < len(entries):
            print(f"\n  --- 反汇编 [+{a.dis * 8:03X}] RVA 0x{entries[a.dis]:X} ---")
            disasm(data, sections, base, entries[a.dis], a.dis_count)
        if a.callers:
            print("\n  --- 直接调用者 ---")
            for k, rva in enumerate(entries):
                callers = find_callers(data, sections, rva, limit=12)
                print(f"  [+{k * 8:03X}] RVA 0x{rva:X}: {len(callers)} 处")
                for c in callers:
                    print(f"       <- RVA 0x{c:X}")
    return 0


def disasm(data, sections, base, rva, count):
    from capstone import CS_ARCH_X86, CS_MODE_64, Cs

    off = rva_to_off(sections, rva)
    if off is None:
        print("  <不在任何 section 内>")
        return
    md = Cs(CS_ARCH_X86, CS_MODE_64)
    n = 0
    for ins in md.disasm(data[off: off + 0x1000], base + rva):
        b = " ".join(f"{x:02X}" for x in ins.bytes)
        print(f"  {ins.address:012X}  {b:<28} {ins.mnemonic:<8} {ins.op_str}")
        n += 1
        if n >= count:
            break


def find_callers(data, sections, target_rva, limit=64):
    """找所有 E8/E9 rel32 直接跳转到 target 的位置。"""
    out = []
    for _, va, raw, ptr, vsize in sections:
        if va == 0:
            continue
        blob = data[ptr: ptr + raw]
        for opc in (0xE8, 0xE9):
            k = blob.find(bytes([opc]))
            while k != -1:
                if k + 5 <= len(blob):
                    rel = struct.unpack_from("<i", blob, k + 1)[0]
                    if va + k + 5 + rel == target_rva:
                        out.append(va + k)
                        if len(out) >= limit:
                            return out
                k = blob.find(bytes([opc]), k + 1)
    return out


if __name__ == "__main__":
    sys.exit(main())
