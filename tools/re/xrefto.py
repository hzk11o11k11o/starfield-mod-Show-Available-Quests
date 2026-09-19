#!/usr/bin/env python3
"""xrefto.py - 在 Starfield.exe 的 .text 里找「RIP 相对寻址某个目标 RVA」的指令。

用途：给定一个已知的 RVA（通常是虚表地址 / 全局变量地址），找出引用它的代码，
例如「谁写了 GFx::AS3::MovieRoot 的虚表」= MovieRoot 的构造函数。

做法：字节模式扫描（mod=00, rm=101 的 modrm 表示 RIP 相对）：
    48 8D /r   lea  reg, [rip+disp32]
    48 8B /r   mov  reg, [rip+disp32]
    48 8D 05 / 0D / 15 / 1D / 25 / 2D / 35 / 3D 等

用法：
    python tools/re/xrefto.py <exe> <target_rva_hex> [--offset <delta_hex>]
    # --offset：目标 = rva + delta（想找「虚表 - 8 处的 COL 引用」时用得上）

输出：命中点所在的 RVA（相对模块基址），可用 tools/re/disasm.py 反汇编确认。
"""
from __future__ import annotations

import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from disasm import PEFile  # noqa: E402

MODRM_RIP = {0x05, 0x0D, 0x15, 0x1D, 0x25, 0x2D, 0x35, 0x3D}


def scan(text: bytes, text_rva: int, target: int) -> list[tuple[int, int]]:
    hits: list[tuple[int, int]] = []
    n = len(text)
    i = 0
    while i + 7 <= n:
        if text[i] == 0x48 and text[i + 1] in (0x8D, 0x8B) and text[i + 2] in MODRM_RIP:
            disp = struct.unpack_from("<i", text, i + 3)[0]
            here = text_rva + i
            if here + 7 + disp == target:
                hits.append((here, text[i + 1]))
            i += 3
            continue
        i += 1
    return hits


def scan_calls(text: bytes, text_rva: int, target: int) -> list[int]:
    """E8 rel32 直接调用目标地址的位置。"""
    hits: list[int] = []
    n = len(text)
    i = 0
    while i + 5 <= n:
        if text[i] == 0xE8:
            disp = struct.unpack_from("<i", text, i + 1)[0]
            here = text_rva + i
            if here + 5 + disp == target:
                hits.append(here)
            i += 5
            continue
        i += 1
    return hits


def main() -> int:
    exe = sys.argv[1]
    target = int(sys.argv[2], 16)
    delta = 0
    if "--offset" in sys.argv:
        delta = int(sys.argv[sys.argv.index("--offset") + 1], 16)
    target += delta
    calls = "--call" in sys.argv

    pe = PEFile(exe)
    for name, vaddr, vsize, rawptr, rawsize in pe.sections():
        if name != ".text":
            continue
        data = pe.buf[rawptr:rawptr + rawsize]
        if calls:
            hit_list = scan_calls(data, vaddr, target)
            print(f"目标函数 RVA 0x{target:X}  被 call 命中 {len(hit_list)} 处：")
            for rva in hit_list:
                print(f"  0x{rva:X}  call")
        else:
            hits = scan(data, vaddr, target)
            print(f"目标 RVA 0x{target:X}  在 .text 里命中 {len(hits)} 处：")
            for rva, op in hits:
                kind = "lea" if op == 0x8D else "mov"
                print(f"  0x{rva:X}  {kind}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
