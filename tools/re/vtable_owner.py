#!/usr/bin/env python3
"""vtable ↔ 对象偏移 的**离线硬核对**（本项目 v4.12 就是靠它定案的）。

背景（v4.12 那轮踩的坑）：
    把「某个事件源的 vtable RVA」算错，是很容易发生的 —— commonlibsf 的
    `RE/IDs_RTTI.h` 里给的是 **RTTI（TypeDescriptor，类型描述符）的 ID**，
    `versionlib.py id <ID>` 查出来的也就是 TypeDescriptor 的地址，**不是 vtable**。
    直接拿它去和运行时的 `*(void**)obj` 比对，必然不等（v4.11 的「不注册」WARN 就是这个）。

正确姿势（本工具做的事）：
    1) **找构造函数**：谁把 `base + vtable_RVA` 这个地址写进了对象（`lea rax,[rip+X]`
       + `mov [reg+off], rax`）—— 那条 `mov` 的 `off` 就是**这个 vtable 在对象里的偏移**；
    2) 同一个函数里往往把**一整组**基类 vtable 都写了 ⇒ 一次性拿到「偏移 → vtable」映射表，
       拿去和 commonlibsf 头文件里的基类偏移逐条对照即可判定谁对谁错；
    3) 顺便用 COL 链把每个 vtable 的**类名**解出来（MSVC 的 vtable[-8] → COL → TD → 名字）；
       注意多重继承里同一类的多个 vtable 的 COL 会指向**同一个** TypeDescriptor，
       所以类名相同不代表偏移相同 —— 偏移才是判据。

用法：
    python tools/re/vtable_owner.py 0x4D7E3D8          # vtable → 偏移（+ 同组的整张表）
    python tools/re/vtable_owner.py 0x4D7E3D8 --all    # 也打印普通 RIP 引用点
    python tools/re/vtable_owner.py --what 0x5CCADD0   # 判断一个 RVA 是代码 / TD / COL / vtable
"""
from __future__ import annotations

import argparse
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from func import EXE, Img  # noqa: E402


def td_name(img: Img, td_rva: int):
    """TypeDescriptor 的类名（名字在 TD+0x10）。返回 None 表示形状不像 TD。"""
    o = img.rva_to_off(td_rva)
    if o is None or o + 0x20 > len(img.data):
        return None
    # TD 形状：{ void* vftable; void* spare(==0); char name[] }
    vft, spare = struct.unpack_from("<QQ", img.data, o)
    if not (img.base <= vft < img.base + 0x20000000) or spare != 0:
        return None
    nm = img.data[o + 0x10: o + 0x10 + 200].split(b"\x00", 1)[0].decode("ascii", "replace")
    return nm if nm.startswith(".?") else None


def col_name(img: Img, col_rva: int):
    """CompleteObjectLocator → (类名, TD RVA)。"""
    o = img.rva_to_off(col_rva)
    if o is None or o + 0x14 > len(img.data):
        return None
    sig, coff, cd, ptd, pcd = struct.unpack_from("<IIIII", img.data, o)
    if sig not in (0, 1) or coff > 0x1000000 or cd > 0x1000000:
        return None
    nm = td_name(img, ptd)
    return (nm, ptd) if nm else None


def vtable_class(img: Img, vt_rva: int):
    """vtable → (类名, COL RVA)；靠 vtable[-8] 的 COL 引用（VA 或 RVA 两种写法都试）。"""
    o = img.rva_to_off(vt_rva - 8)
    if o is None:
        return None
    col_v = struct.unpack_from("<Q", img.data, o)[0]
    if img.base <= col_v < img.base + 0x20000000:
        col_rva = col_v - img.base
    elif 0 < col_v < 0x10000000:
        col_rva = col_v
    else:
        return None
    info = col_name(img, col_rva)
    return (info[0], col_rva) if info else None


def is_code_ptr(img: Img, rva: int) -> bool:
    o = img.rva_to_off(rva)
    if o is None or o + 4 > len(img.data):
        return False
    q = struct.unpack_from("<Q", img.data, o)[0]
    return img.section_of(q - img.base) == ".text" if img.base <= q < img.base + 0x20000000 else False


def what_is(img: Img, rva: int):
    """判断一个 RVA 是什么。"""
    sec = img.section_of(rva)
    out = [f"RVA 0x{rva:X}（段 {sec}）"]
    nm = td_name(img, rva)
    if nm:
        out.append(f"  = **TypeDescriptor（RTTI 类型描述符）**：{nm}")
        out.append("  ★ 这不是 vtable！要 vtable 得走 COL 链或找构造函数里的写入。")
        return "\n".join(out)
    info = col_name(img, rva)
    if info:
        out.append(f"  = CompleteObjectLocator（RTTI 定位器）→ 类 {info[0]}（TD 0x{info[1]:X}）")
        return "\n".join(out)
    info = vtable_class(img, rva)
    if info:
        slots = []
        for k in range(6):
            o = img.rva_to_off(rva + k * 8)
            if o is None:
                break
            q = struct.unpack_from("<Q", img.data, o)[0]
            if not (img.base <= q < img.base + 0x20000000):
                break
            slots.append(f"0x{q - img.base:X}")
        out.append(f"  = vtable（vtable[-8] → COL 0x{info[1]:X} → 类 {info[0]}）")
        out.append(f"  前几槽: {', '.join(slots)}")
        return "\n".join(out)
    if sec == ".text":
        out.append(f"  = 代码（函数起点 ≈ RVA 0x{img.func_start(rva):X}）")
        return "\n".join(out)
    out.append("  = 没匹配到已知形状（既不是 TD / COL / vtable，也不是 .text 代码）")
    return "\n".join(out)


def find_ctor_stores(img: Img, vt_rva: int):
    """找「把 base+vtable 写进对象」的指令 ⇒ [(函数起点, 偏移, 写入点 RVA)]。"""
    from capstone import CS_ARCH_X86, CS_MODE_64, Cs
    from capstone.x86 import X86_OP_IMM, X86_OP_MEM, X86_OP_REG, X86_REG_RAX, X86_REG_RIP

    md = Cs(CS_ARCH_X86, CS_MODE_64)
    md.detail = True
    want = img.base + vt_rva

    # 先找所有 RIP 相对引用（`lea rax,[rip+X]` 会在其中）
    refs = []
    for name, va, vsize, ptr, raw in img.sections:
        if name != ".text":
            continue
        blob = img.data[ptr:ptr + raw]
        k = blob.find(b"\x48\x8D")  # lea
        while k != -1:
            ins = next(md.disasm(blob[k:k + 16], img.base + va + k), None)
            if ins and ins.mnemonic == "lea" and len(ins.operands) == 2:
                op = ins.operands[1]
                if op.type == X86_OP_MEM and op.mem.base == X86_REG_RIP:
                    tgt = ins.address + ins.size + op.mem.disp
                    if tgt == want:
                        refs.append(va + k)
            k = blob.find(b"\x48\x8D", k + 1)

    out = []
    for ref_rva in refs:
        off = img.rva_to_off(ref_rva)
        start = img.rva_to_off(max(img.func_start(ref_rva), ref_rva - 0x400))
        insns = list(md.disasm(img.data[start:off + 0x30], img.base + (img.off_to_rva(start) or 0)))
        # 找这条 lea 之后最近的 `mov [reg+off], rax`
        seen_lea = False
        for ins in insns:
            if ins.address - img.base == ref_rva:
                seen_lea = True
                continue
            if not seen_lea:
                continue
            if ins.mnemonic != "mov" or len(ins.operands) != 2:
                continue
            dst, src = ins.operands
            if src.type == X86_OP_REG and src.reg == X86_REG_RAX and dst.type == X86_OP_MEM:
                out.append((img.func_start(ref_rva), dst.mem.disp, ref_rva))
                break
            if ins.mnemonic.startswith("jmp") or ins.mnemonic.startswith("ret"):
                break
    return refs, out


def dump_group_table(img: Img, ctor_rva: int):
    """把构造函数里「一组 vtable → 偏移」全列出来（本轮就是靠这张表定案的）。"""
    from capstone import CS_ARCH_X86, CS_MODE_64, Cs
    from capstone.x86 import X86_OP_MEM, X86_OP_REG, X86_REG_RAX, X86_REG_RIP

    md = Cs(CS_ARCH_X86, CS_MODE_64)
    md.detail = True
    off = img.rva_to_off(ctor_rva)
    if off is None:
        return
    end = min(off + 0x400, len(img.data))
    rows = []
    pending = None
    for ins in md.disasm(img.data[off:end], img.base + ctor_rva):
        if ins.mnemonic == "lea" and len(ins.operands) == 2:
            op = ins.operands[1]
            if op.type == X86_OP_MEM and op.mem.base == X86_REG_RIP:
                pending = ins.address + ins.size + op.mem.disp - img.base
                continue
        if ins.mnemonic == "mov" and len(ins.operands) == 2 and pending is not None:
            dst, src = ins.operands
            if src.type == X86_OP_REG and src.reg == X86_REG_RAX and dst.type == X86_OP_MEM:
                rows.append((dst.mem.disp, pending))
                pending = None
                continue
        if ins.mnemonic in ("ret",):
            break
        if ins.mnemonic == "call":
            pending = None
    if not rows:
        return
    print(f"\n  === 构造函数 0x{ctor_rva:X} 里写进对象的 vtable（偏移 → vtable RVA → 类名）===")
    for disp, vt in rows:
        info = vtable_class(img, vt)
        cls = info[0] if info else "?"
        print(f"    [obj+0x{disp:03X}] <- 0x{vt:X}   {cls}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("rva", nargs="?", help="vtable 的 RVA（hex），如 0x4D7E3D8")
    ap.add_argument("--what", default=None, help="判断这个 RVA 是什么（hex）")
    ap.add_argument("--all", action="store_true", help="打印全部 RIP 引用点（不只是构造函数写入）")
    a = ap.parse_args()

    img = Img(EXE)
    print(f"imageBase = 0x{img.base:X}  （{EXE.name}）")

    if a.what:
        print(what_is(img, int(a.what, 16)))
        return 0
    if not a.rva:
        print("需要给 vtable RVA，或用 --what")
        return 2

    vt = int(a.rva, 16)
    info = vtable_class(img, vt)
    print(f"\nvtable 0x{vt:X}: " + (f"COL → 类 {info[0]}" if info else "（vtable[-8] 没能解析出 COL）"))
    refs, stores = find_ctor_stores(img, vt)
    print(f"RIP 引用点 {len(refs)} 个：{[hex(r) for r in refs]}")
    if a.all:
        for r in refs:
            print(f"   引用 @ 0x{r:X}（函数 0x{img.func_start(r):X}）")
    if stores:
        print("\n写入对象的指令（这就是 vtable 与 对象偏移 的直接证据）：")
        for func, disp, at in stores:
            print(f"   [obj+0x{disp:03X}] <- 0x{vt:X}   写于 0x{at:X}（函数 0x{func:X}）")
        for func in sorted({s[0] for s in stores}):
            dump_group_table(img, func)
    else:
        print("没找到 `mov [reg+off], rax` 形状的写入 —— 该 vtable 可能只被别的 vtable/表引用")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
