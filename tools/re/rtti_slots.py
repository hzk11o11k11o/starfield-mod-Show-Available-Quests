#!/usr/bin/env python3
"""rtti_slots.py —— 从 RTTI TypeDescriptor 找回 vtable 并把槽位列出来（MSVC x64）。

为什么需要它：commonlibsf 里 `SF_RTTI_VTABLE(X)` 用的 REL::ID 指向的是
**TypeDescriptor**（不是 vtable）。要确认「某个虚函数到底在第几槽」时，
得自己走一遍：TD → COL → vtable。

MSVC x64 布局（镜像内 RVA/VA）：
    TypeDescriptor        { void* vftable; void* spare; char name[]; }      name 在 +0x10
    CompleteObjectLocator { u32 signature; u32 offset; u32 cdOffset;
                            u32 pTypeDescriptor(RVA); u32 pClassDescriptor(RVA);
                            u32 self(RVA); }                                 +0x0C 是 TD 的 RVA
    vtable[-8] = &COL（8 字节 VA）；vtable[0] 起是虚函数

用法：
    python tools/re/rtti_slots.py --td 0x59A53C0 --slots 64
    python tools/re/rtti_slots.py --td 0x59A53C0 --dis 0x39 --count 40
    python tools/re/rtti_slots.py --name "MovieRoot@AS3@GFx@Scaleform@@" --slots 8
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
    base = pe.OPTIONAL_HEADER.ImageBase
    sections = [
        (s.Name.rstrip(b"\x00").decode("latin1"), s.VirtualAddress,
         max(s.Misc_VirtualSize, s.SizeOfRawData), s.PointerToRawData)
        for s in pe.sections
    ]
    image_size = pe.OPTIONAL_HEADER.SizeOfImage
    return data, base, sections, image_size


def rva_to_off(sections, rva):
    for _, vaddr, vsize, rawptr in sections:
        if vaddr <= rva < vaddr + vsize:
            return rawptr + (rva - vaddr)
    return None


def find_name(sections, data, base, needle: str) -> list[int]:
    """在镜像里找 ".?AV<needle>"（needle 要写全，例如 MovieRoot@AS3@GFx@Scaleform@@）。"""
    target = (".?AV" + needle).encode("ascii")
    hits = []
    for _, vaddr, vsize, rawptr in sections:
        blob = data[rawptr:rawptr + vsize]
        start = 0
        while True:
            k = blob.find(target, start)
            if k < 0:
                break
            # 命中位置往前退 0x10（TD 的名字在 +0x10）
            hits.append(vaddr + k - 0x10)
            start = k + 1
    return hits


def find_4byte(sections, data, value: int) -> list[int]:
    needle = struct.pack("<I", value)
    out = []
    for _, vaddr, vsize, rawptr in sections:
        blob = data[rawptr:rawptr + vsize]
        start = 0
        while True:
            k = blob.find(needle, start)
            if k < 0:
                break
            out.append(vaddr + k)
            start = k + 1
    return out


def find_8byte(sections, data, value: int) -> list[int]:
    needle = struct.pack("<Q", value)
    out = []
    for _, vaddr, vsize, rawptr in sections:
        blob = data[rawptr:rawptr + vsize]
        start = 0
        while True:
            k = blob.find(needle, start)
            if k < 0:
                break
            out.append(vaddr + k)
            start = k + 1
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--td", help="TypeDescriptor 的 RVA（十六进制）")
    ap.add_argument("--name", help="修饰名中 .?AV 之后的部分")
    ap.add_argument("--slots", type=int, default=16)
    ap.add_argument("--dis", help="反汇编某个槽（槽号，如 0x39）")
    ap.add_argument("--count", type=int, default=40)
    a = ap.parse_args()

    data, base, sections, _ = load(EXE)
    print(f"imageBase = 0x{base:X}")

    tds = []
    if a.td:
        tds = [int(a.td, 0)]
    elif a.name:
        tds = find_name(sections, data, base, a.name)
        print(f"名字命中 {len(tds)} 处 TypeDescriptor: {[hex(t) for t in tds[:6]]}")
    if not tds:
        print("没有 TD，退出")
        return 1

    for td in tds:
        off = rva_to_off(sections, td)
        if off is None:
            continue
        name = data[off + 0x10:].split(b"\x00", 1)[0].decode("latin1", "replace")
        print(f"\n=== TD RVA 0x{td:X}  name={name} ===")

        # COL：镜像里有一处 4 字节 == TD 的 RVA，就在 COL+0x0C
        cols = []
        for hit in find_4byte(sections, data, td):
            col = hit - 0x0C
            o = rva_to_off(sections, col)
            if o is None:
                continue
            sig, offset, cd, ptd, pcd, self_rva = struct.unpack_from("<IIIIII", data, o)
            if ptd != td:
                continue
            cols.append(col)
            print(f"  COL RVA 0x{col:X}  sig=0x{sig:X} offset=0x{offset:X} cd=0x{cd:X} self=0x{self_rva:X}"
                  + ("  (self 自洽)" if self_rva == col else "  (self 不一致)"))
        if not cols:
            print("  没找到 COL")
            continue

        for col in cols:
            vt_refs = find_8byte(sections, data, base + col)
            for ref in vt_refs:
                vtable = ref + 8
                o = rva_to_off(sections, vtable)
                if o is None:
                    continue
                print(f"  vtable RVA 0x{vtable:X}（COL 引用在 0x{ref:X}）")
                for i in range(a.slots):
                    fn = struct.unpack_from("<Q", data, o + i * 8)[0]
                    if not (base <= fn < base + 0x8000000):
                        print(f"    [{i:02X}] 0x{fn:X}  <不在模块里>")
                        continue
                    print(f"    [{i:02X}] RVA 0x{fn - base:X}")

                if a.dis:
                    slot = int(a.dis, 0)
                    fn = struct.unpack_from("<Q", data, o + slot * 8)[0]
                    rva = fn - base
                    print(f"\n  --- 槽 [{slot:02X}] = RVA 0x{rva:X} 反汇编 ---")
                    try:
                        import capstone
                    except ImportError:
                        print("  (没装 capstone)")
                        continue
                    fo = rva_to_off(sections, rva)
                    md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_64)
                    code = data[fo:fo + 0x400]
                    n = 0
                    for ins in md.disasm(code, rva):
                        print(f"  {ins.address:08X}  {ins.mnemonic:<8} {ins.op_str}")
                        n += 1
                        if n >= a.count:
                            break
    return 0


if __name__ == "__main__":
    sys.exit(main())
