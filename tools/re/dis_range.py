#!/usr/bin/env python3
"""dis_range.py - 反汇编一段代码，并**自动标注每个 RIP 相对操作数指向哪里**
（.rdata 里的字符串 / .text 里的函数 / .data 里的全局），调用目标也一并标出来。

为什么需要它（第 37 轮的经验）：
    `tools/re/disasm.py` 只能看裸反汇编；逆向时真正想知道的是
    「这条 `lea rdx, [rip+…]` 指向的是哪个字符串 / 哪个全局」——
    没有这一步，就只能一个个地址手算，容易算错（本轮把 0x15DF112 + 0x0495291E
    手算错一位，白追了一轮）。

用法：
    python tools/re/dis_range.py 0x1368A80 0x1368BB0        # 一段
    python tools/re/dis_range.py 0x2010210 0x2010300        # Papyrus 原生函数体

输出形态：
    02010298  mov   rdi, qword ptr [rip + 0x41cdb21]   ; -> .data 0x5FDDDC0  [0x…]
    020102D1  call  0xc83790                            ; call -> 0xC83790
"""
from __future__ import annotations

import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from func import EXE, Img  # noqa: E402

DATA_SECTIONS = (".rdata", "_RDATA", ".data")


def annotate(img: Img, tgt_rva: int) -> str:
    sec = img.section_of(tgt_rva)
    if sec is None:
        return f"   ; -> ??? 0x{tgt_rva:X}"
    out = f"   ; -> {sec} 0x{tgt_rva:X}"
    if sec not in DATA_SECTIONS:
        return out
    off = img.rva_to_off(tgt_rva)
    if off is None or off + 8 > len(img.data):
        return out + "  (不在文件映射内)"
    raw = img.data[off:off + 64]
    # 像 ASCII 字符串就打印出来
    s = raw.split(b"\x00")[0]
    if len(s) >= 3 and all(0x20 <= b < 0x7F for b in s):
        return out + f'  "{s.decode("latin1")}"'
    # 否则当指针看一眼（vtable / 函数表 / 结构体首字段）
    q = struct.unpack_from("<Q", img.data, off)[0]
    if img.section_of(q - img.base) is not None:
        out += f"  [0x{q - img.base:X}]"
    return out


def main() -> int:
    if len(sys.argv) < 3:
        print(__doc__)
        return 1
    img = Img(EXE)
    lo, hi = int(sys.argv[1], 0), int(sys.argv[2], 0)

    from capstone import CS_ARCH_X86, CS_MODE_64, Cs

    md = Cs(CS_ARCH_X86, CS_MODE_64)
    md.detail = True
    off = img.rva_to_off(lo)
    for insn in md.disasm(img.data[off:off + (hi - lo)], lo):
        note = ""
        for op in insn.operands:
            if op.type == 3 and op.mem.base == 41:  # X86_OP_MEM / RIP 相对
                note = annotate(img, insn.address + insn.size + op.mem.disp)
                break
            if op.type == 2 and insn.mnemonic == "call":  # X86_OP_IMM
                if img.section_of(op.imm) is not None:
                    note = f"   ; call -> 0x{op.imm:X}"
                break
        print(f"{insn.address:08X}  {insn.mnemonic:<8} {insn.op_str}{note}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
