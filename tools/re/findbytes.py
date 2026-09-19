#!/usr/bin/env python3
"""在 .text 里按字节模式查找（带简单反汇编上下文）。

用法：
    python tools/re/findbytes.py "c7 4? 04 ff ff ff ff"        # ? = 通配一个字节
    python tools/re/findbytes.py "c7 4? 04 ff ff ff ff" --lo 0x650000 --hi 0x660000
    python tools/re/findbytes.py "..." --ctx 6                  # 多打印几条指令上下文

为什么要它：逆向「谁把哈希槽标记为空 / 谁做了移除」这类问题时，
按指令字节（而不是按符号）搜索是最直接的办法。
"""
from __future__ import annotations

import argparse
import struct
import sys
from pathlib import Path

EXE = Path(r"D:\SteamLibrary\steamapps\common\Starfield\Starfield.exe")


def load_pe(path: Path):
    import pefile

    data = path.read_bytes()
    pe = pefile.PE(str(path), fast_load=True)
    base = pe.OPTIONAL_HEADER.ImageBase
    secs = []
    for s in pe.sections:
        secs.append((s.Name.rstrip(b"\x00").decode("latin1"), s.VirtualAddress,
                     s.Misc_VirtualSize, s.PointerToRawData, s.SizeOfRawData))
    return data, base, secs


def parse_pat(text: str):
    """每个 token 返回 (value, mask)；'?' / '??' 为全通配，'4?' 为高半字节固定。"""
    toks = text.split()
    out = []
    for t in toks:
        if t in ("?", "??"):
            out.append((0x00, 0x00))
            continue
        val = 0
        mask = 0
        for ch in t:
            val <<= 4
            mask <<= 4
            if ch in "?*":
                continue
            val |= int(ch, 16)
            mask |= 0xF
        out.append((val, mask))
    return out


def rva_to_off(secs, rva):
    for _, va, vsize, ptr, raw in secs:
        if va <= rva < va + max(vsize, raw):
            return ptr + (rva - va)
    return None


def off_to_rva(secs, off):
    for _, va, vsize, ptr, raw in secs:
        if ptr <= off < ptr + raw:
            return va + (off - ptr)
    return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("pattern")
    ap.add_argument("--exe", default=str(EXE))
    ap.add_argument("--lo", type=lambda s: int(s, 0), default=0)
    ap.add_argument("--hi", type=lambda s: int(s, 0), default=0x80000000)
    ap.add_argument("--ctx", type=int, default=3)
    ap.add_argument("--limit", type=int, default=40)
    ap.add_argument("--section", default=".text")
    a = ap.parse_args()

    data, base, secs = load_pe(Path(a.exe))
    pat = parse_pat(a.pattern)

    for name, va, vsize, ptr, raw in secs:
        if name != a.section:
            continue
        blob = data[ptr:ptr + raw]
        n = 0
        for i in range(0, len(blob) - len(pat)):
            rva = va + i
            if rva < a.lo or rva >= a.hi:
                continue
            ok = True
            for j, (val, mask) in enumerate(pat):
                if (blob[i + j] & mask) != (val & mask):
                    ok = False
                    break
            if not ok:
                continue
            n += 1
            print(f"--- hit RVA 0x{rva:X}")
            if a.ctx:
                from capstone import CS_ARCH_X86, CS_MODE_64, Cs
                md = Cs(CS_ARCH_X86, CS_MODE_64)
                start = max(0, i - a.ctx * 8)
                for ins in list(md.disasm(blob[start:i + len(pat) + 4], va + start))[-(a.ctx * 2 + 2):]:
                    mark = " <== HIT" if rva <= ins.address < rva + len(pat) else ""
                    print(f"    {ins.address:08X}  {ins.mnemonic:<8} {ins.op_str}{mark}")
            if n >= a.limit:
                break
        print(f"[{name}] hits: {n}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
