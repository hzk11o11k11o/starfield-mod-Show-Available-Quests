#!/usr/bin/env python3
"""Starfield.exe 交叉引用（xref）工具。

三种引用形式各自独立，缺一不可：
  1. `--rip`    RIP 相对寻址（x64 上访问全局变量的**主流**方式）：
                `lea rax,[rip+disp32]` / `mov rcx,[rip+disp32]` —— 反汇编里叫 `rip + 0x...`。
                这是**唯一**能找到「谁用了这个 vtable / 这个全局对象」的办法
                （versionlib.py 的 refs 只找 8 字节绝对指针，在 x64 上几乎找不到东西）。
  2. `--abs`    8 字节绝对指针（vtable 槽、全局函数指针表）。
  3. `--call`   E8/E9 rel32 直接调用。

用法：
    python tools/re/xref.py --rip 0x4B2FA50            # 谁引用了这个 vtable
    python tools/re/xref.py --rip 0x4B2FA50 --context  # 附带反汇编上下文
    python tools/re/xref.py --call 0x653400            # 谁调用了这个函数
    python tools/re/xref.py --all 0x4B2FA50

RIP 相对的正确算法：disp32 是**相对指令末尾**的偏移，而 disp 就是指令最后一个字段，
所以「disp 字段所在 RVA + 4 + disp32 == 目标 RVA」即可，不需要先知道指令长度。
"""
from __future__ import annotations

import argparse
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
        sections.append((s.Name.rstrip(b"\x00").decode("ascii", "replace"),
                         s.VirtualAddress, s.SizeOfRawData, s.PointerToRawData,
                         max(s.Misc_VirtualSize, s.SizeOfRawData),
                         bool(s.Characteristics & 0x20000000)))
    return data, base, sections


def off_to_rva(sections, off):
    for _, va, raw, ptr, vsize, _x in sections:
        if ptr <= off < ptr + raw:
            return va + (off - ptr)
    return None


def rva_to_off(sections, rva):
    for _, va, raw, ptr, vsize, _x in sections:
        if va <= rva < va + vsize:
            return ptr + (rva - va)
    return None


def scan_rip(data, sections, target_rva, limit):
    """扫所有「disp32 字段」位置，p_rva + 4 + disp == target。

    ★ 必须做形状校验：随便 4 个字节都可能碰巧等于所需的 disp32
    （实测会产出假命中，例如把 `mov rcx,[rax+0x48]` 的后半截当成 RIP 引用）。
    校验办法：从 p-3 ~ p-10 逐个候选起点反汇编，要求**恰好一条指令**结束在 p+4，
    且操作数里有一个 RIP 相对的 mem。
    """
    from capstone import CS_ARCH_X86, CS_MODE_64, Cs
    from capstone.x86 import X86_OP_MEM, X86_REG_RIP

    md = Cs(CS_ARCH_X86, CS_MODE_64)
    md.detail = True
    out = []
    for _name, va, raw, ptr, vsize, exec_ in sections:
        if not exec_:
            continue
        blob = data[ptr: ptr + raw]
        n = len(blob)
        i = 0
        while i < n - 4:
            disp = struct.unpack_from("<i", blob, i)[0]
            if va + i + 4 + disp != target_rva:
                i += 1
                continue
            start = i
            for back in range(3, 11):
                if i - back < 0:
                    break
                blob2 = blob[i - back: i + 4]
                insns = list(md.disasm(blob2, va + i - back))
                if not insns:
                    continue
                ins = insns[0]
                if len(ins.bytes) != back + 4 or len(insns) > 1:
                    continue
                rip_ok = any(
                    o.type == X86_OP_MEM and o.mem.base == X86_REG_RIP
                    and o.mem.disp == disp
                    for o in ins.operands
                )
                if rip_ok:
                    start = i - back
                    break
            else:
                # 没找到合法起点 → 判为误报，跳过
                i += 1
                continue
            obj = (va + start, va + i, ins)
            out.append(obj)
            if len(out) >= limit:
                return out
            i += 4
    return out


def scan_abs(data, sections, target_value, limit):
    out = []
    needle = struct.pack("<Q", target_value)
    k = data.find(needle)
    while k != -1:
        rva = off_to_rva(sections, k)
        if rva is not None:
            out.append(rva)
        if len(out) >= limit:
            break
        k = data.find(needle, k + 1)
    return out


def scan_call(data, sections, target_rva, limit):
    out = []
    for name, va, raw, ptr, vsize, exec_ in sections:
        if not exec_:
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


def disasm_at(data, sections, base, rva, before=16, count=6):
    from capstone import CS_ARCH_X86, CS_MODE_64, Cs

    off = rva_to_off(sections, rva)
    if off is None:
        return
    md = Cs(CS_ARCH_X86, CS_MODE_64)
    start = max(0, off - 24)
    lines = []
    for ins in md.disasm(data[start: off + 24], base + rva - (off - start)):
        mark = " >> " if base + rva - 4 <= ins.address <= base + rva + 8 else "    "
        b = " ".join(f"{x:02X}" for x in ins.bytes)
        lines.append(f"    {mark}{ins.address:012X}  {b:<28} {ins.mnemonic:<8} {ins.op_str}")
    for l in lines[-before:]:
        print(l)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--exe", default=str(EXE))
    ap.add_argument("--rip", default=None, help="目标 RVA（十六进制），找 RIP 相对引用")
    ap.add_argument("--abs", default=None, help="目标 RVA，找 8 字节绝对引用")
    ap.add_argument("--call", default=None, help="目标 RVA，找直接 call/jmp")
    ap.add_argument("--all", default=None, help="目标 RVA，上面三种都找")
    ap.add_argument("--context", action="store_true", help="打印引用点附近的指令")
    ap.add_argument("--max", type=int, default=60)
    a = ap.parse_args()

    data, base, sections = load(Path(a.exe))
    print(f"imageBase = 0x{base:X}")

    jobs = []
    for kind, val in (("rip", a.rip), ("abs", a.abs), ("call", a.call), ("all", a.all)):
        if val is None:
            continue
        r = int(val, 16)
        if kind in ("all", "rip"):
            jobs.append(("RIP 相对", r, lambda r=r: scan_rip(data, sections, r, a.max)))
        if kind in ("all", "abs"):
            jobs.append(("8 字节绝对", r, lambda r=r: scan_abs(data, sections, base + r, a.max)))
        if kind in ("all", "call"):
            jobs.append(("直接 call/jmp", r, lambda r=r: scan_call(data, sections, r, a.max)))
        if kind == "all":
            break

    for label, target, fn in jobs:
        hits = fn()
        print(f"\n===== {label}: 目标 RVA 0x{target:X} -> {len(hits)} 处 =====")
        for h in hits:
            if isinstance(h, tuple):
                start, disp_off, ins = h
                b = " ".join(f"{x:02X}" for x in ins.bytes)
                print(f"  0x{start:X}  {b:<28} {ins.mnemonic:<8} {ins.op_str}")
                if a.context:
                    disasm_at(data, sections, base, max(0, start), before=5)
            else:
                print(f"  0x{h:X}")
                if a.context:
                    disasm_at(data, sections, base, max(0, h), before=5)
    return 0


if __name__ == "__main__":
    sys.exit(main())
