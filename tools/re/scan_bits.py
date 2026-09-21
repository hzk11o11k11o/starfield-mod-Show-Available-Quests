"""scan_bits.py - 扫描一段代码里的位提取 / 浮点比较 / 间接调用（RE 用）。

用途：第 86 轮定位 operator 位处理时，从 IsTrue 函数体里一把捞出所有
`shr/test/and/cmov/bt/jmp qword/call qword/vcomiss` 指令，再按地址定位语义。
默认范围 = TESConditionItem::IsTrue（0xE46D70~0xE47C40，1.16.244）。

用法：python tools/re/scan_bits.py [startRVA] [endRVA]
"""
from __future__ import annotations

import sys
from pathlib import Path

import capstone

sys.path.insert(0, str(Path(__file__).parent))
from disasm import PEFile  # noqa: E402

EXE = r"D:\SteamLibrary\steamapps\common\Starfield\Starfield.exe"
START = 0xE46D70
END = 0xE47C40

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def main() -> int:
    start = int(sys.argv[1], 16) if len(sys.argv) > 1 else START
    end = int(sys.argv[2], 16) if len(sys.argv) > 2 else END
    pe = PEFile(EXE)
    off = pe.rva_to_off(start)
    data = pe.buf[off:off + (end - start)]
    md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_64)
    md.detail = False
    pats = ("shr", "test", "and", "vcomiss", "ucomiss", "comiss", "cmov",
            "jmp qword", "call qword", "bt ", "movsx", "movzx")
    for insn in md.disasm(data, start):
        m = insn.mnemonic
        if any(m == p or m.startswith(p) for p in pats):
            print(f"{insn.address:08X}  {insn.bytes.hex():<20} {m} {insn.op_str}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
