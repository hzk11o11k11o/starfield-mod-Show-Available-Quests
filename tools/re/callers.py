"""callers.py - 找 Starfield.exe 里 call 到指定 RVA 的所有位置（call rel32）。

用途：RE 时问「这个函数被谁调用」（第 86 轮用它找到条件列表遍历器 —— IsTrue 的上层）。

用法：python tools/re/callers.py 0xE46D70 [0xE48980 ...]
"""
from __future__ import annotations

import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from disasm import PEFile  # noqa: E402

EXE = r"D:\SteamLibrary\steamapps\common\Starfield\Starfield.exe"

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def main() -> int:
    pe = PEFile(EXE)
    sections = pe.sections()
    text = None
    for name, vaddr, vsize, rawptr, rawsize in sections:
        if name == ".text":
            text = (vaddr, vsize, rawptr, rawsize)
    vaddr, vsize, rawptr, rawsize = text
    buf = pe.buf[rawptr:rawptr + rawsize]
    for arg in sys.argv[1:]:
        target = int(arg, 16)
        hits = []
        i = 0
        while True:
            j = buf.find(b"\xe8", i)
            if j < 0:
                break
            if j + 5 <= len(buf):
                rel = struct.unpack_from("<i", buf, j + 1)[0]
                here = vaddr + j
                if here + 5 + rel == target:
                    hits.append(here)
            i = j + 1
        print(f"call 0x{target:X} 的调用点：{len(hits)} 处")
        for h in hits[:40]:
            print(f"  0x{h:X}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
