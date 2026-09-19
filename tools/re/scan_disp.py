#!/usr/bin/env python3
"""按「成员偏移」反查引擎代码：找出所有访问 [reg+disp] 且 disp == 目标偏移的指令。

用途（本项目 v35 的动机）：
    验证 `Actor::boolBits @0x208` / kDead(0x800) 这类「按头文件偏移直接读内存」的
    假设到底对不对 —— 直接在主程序里找「读 [reg+0x208] 并且带 0x800 立即数」的指令：
    有命中 = 引擎自己也在这么读；一个都没命中 = 偏移或位序错了。

用法：
    python tools/re/scan_disp.py 0x208                  # 所有访问 [reg+0x208] 的指令
    python tools/re/scan_disp.py 0x208 --imm 0x800      # 只列立即数为 0x800 的
    python tools/re/scan_disp.py 0x208 --opcode 81      # 只列该 opcode 开头的（81 = 立即数组）
    python tools/re/scan_disp.py 0x208 --max 40

实现：先在 .text 里按小端字节扫 disp32（毫秒级），再对命中点用 capstone 反汇编
前后一小段窗口，确认「确实是一条访问 [reg+disp] 的指令」——
避免全局线性反汇编（100MB 主程序）的耗时。
"""
import argparse
import struct
import sys

try:
    import pefile
    from capstone import Cs, CS_ARCH_X86, CS_MODE_64
    from capstone.x86 import X86_OP_IMM, X86_OP_MEM
except ImportError as e:  # pragma: no cover
    print(f"需要 pefile + capstone: pip install pefile capstone ({e})")
    sys.exit(2)

DEFAULT_EXE = r"D:\SteamLibrary\steamapps\common\Starfield\Starfield.exe"


def parse_int(s):
    return int(s, 16)


def load_text(exe):
    pe = pefile.PE(exe, fast_load=True)
    for sec in pe.sections:
        if sec.Name.rstrip(b"\x00") == b".text":
            return sec.get_data(), sec.VirtualAddress, pe.OPTIONAL_HEADER.ImageBase
    raise SystemExit("找不到 .text 段")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("disp", type=parse_int, help="目标偏移，如 0x208")
    ap.add_argument("--exe", default=DEFAULT_EXE)
    ap.add_argument("--imm", type=parse_int, default=None, help="只列包含该立即数的指令，如 0x800")
    ap.add_argument("--opcode", default=None, help="只列该 opcode 前缀（十六进制），如 81 / f7")
    ap.add_argument("--max", type=int, default=60)
    ap.add_argument("--window", type=int, default=14, help="命中点前多少字节开始反汇编")
    args = ap.parse_args()

    want_op = bytes.fromhex(args.opcode) if args.opcode else None

    text, text_rva, image_base = load_text(args.exe)
    pattern = struct.pack("<I", args.disp)
    print(f".text size={len(text):#x} rva={text_rva:#x} imageBase={image_base:#x}")
    print(f"扫描 disp32 = {args.disp:#x} ...")

    md = Cs(CS_ARCH_X86, CS_MODE_64)
    md.detail = True

    hits = []
    pos = 0
    while len(hits) < args.max:
        pos = text.find(pattern, pos)
        if pos < 0:
            break
        pos += 1
        w0 = max(0, pos - args.window)
        for ins in md.disasm(text[w0 : pos + 8], text_rva + w0):
            if ins.address > text_rva + pos:
                break
            mems = [o for o in ins.operands if o.type == X86_OP_MEM]
            if not mems or any(m.mem.disp != args.disp for m in mems):
                continue
            if args.imm is not None:
                imms = [o for o in ins.operands if o.type == X86_OP_IMM]
                if not any((o.imm & 0xFFFFFFFF) == args.imm for o in imms):
                    continue
            if want_op is not None and not ins.bytes.startswith(want_op):
                continue
            hits.append((ins.address, ins))
            break

    print(f"命中 {len(hits)} 条（上限 {args.max}）")
    for addr, ins in hits:
        print(f"  {addr:#x} (rva {addr - image_base:#x}): {ins.mnemonic}\t{ins.op_str}    [{ins.bytes.hex()}]")


if __name__ == "__main__":
    main()
