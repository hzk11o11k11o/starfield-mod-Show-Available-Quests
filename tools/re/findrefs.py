#!/usr/bin/env python3
"""按「数据地址」查全部 RIP 相对引用（func.py 自带 rip 的完整版）。

用途：逆向时经常要问「这个全局变量 / 数据表被谁读写过」。
func.py 的 `rip` 只覆盖少数指令前缀形状（`mov reg,[rip+d]` 等），别的寄存器形式会漏。

做法（两个坑都踩过，所以这里是有意这么写的）：
  1) 不能只用字节模式匹配 —— 会在指令中间误命中（同一地址被 4 字节 / 8 字节各命中一次）；
  2) 不能对 60MB 的 .text 做整段线性反汇编 —— 一旦失同步就静默漏掉后面全部命中。
  ⇒ 枚举「disp 字段（4 字节）在 blob 内的位置」，每个位置对应**唯一**的合法 disp 值：
        disp = target_rva − (va + pos + 4)
    用 `bytes.find` 直接定位该 4 字节（C 速度），再反推指令起点交给 capstone 校验：
    **要求解码长度正好让指令结尾压在 disp 字段上** —— 同时排掉假命中与失同步。
  3) 命中后按操作数位置分读 / 写：目的操作数（op[0]）= 写，源操作数 = 读。

用法：
    python tools/re/findrefs.py 0x61EEA28            # 全部引用
    python tools/re/findrefs.py 0x61EEA28 --writers  # 只看写入点
"""
from __future__ import annotations

import argparse
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from func import Img, EXE  # noqa: E402


def scan(img: Img, target_rva: int, writers_only: bool = False):
    """返回 [(ins_rva, "WRITE"/"read ", func_start_rva, "mnemonic op_str"), ...]。"""
    from capstone import CS_ARCH_X86, CS_MODE_64, Cs
    from capstone.x86 import X86_OP_MEM, X86_REG_RIP

    md = Cs(CS_ARCH_X86, CS_MODE_64)
    md.detail = True
    out = []
    seen: set[int] = set()

    def consider(ins_rva: int, ins_blob_pos: int, disp_pos: int) -> None:
        """ins_rva / ins_blob_pos = 指令起点；disp_pos = disp 字段的 blob 位置。"""
        if ins_rva in seen:
            return
        seen.add(ins_rva)
        off = img.rva_to_off(ins_rva)
        if off is None:
            return
        ins = next(md.disasm(img.data[off:off + 15], ins_rva), None)
        ins_len = disp_pos + 4 - ins_blob_pos
        if ins is None or ins.size != ins_len:
            return
        for i, op in enumerate(ins.operands):
            if op.type != X86_OP_MEM or op.mem.base != X86_REG_RIP:
                continue
            if ins.address + ins.size + op.mem.disp != target_rva:
                continue
            is_write = (i == 0)
            if writers_only and not is_write:
                return
            f = img.func_start(ins_rva)
            out.append((ins_rva, "WRITE" if is_write else "read ", f,
                        f"{ins.mnemonic} {ins.op_str}"))
            return

    for name, va, _vsize, ptr, raw in img.sections:
        if name != ".text":
            continue
        blob = img.data[ptr:ptr + raw]
        # 只能出现这几个「disp 字段距指令起点」的偏移：
        #   REX.W + opcode + ModRM       = 3（如 48 8b 0d …）
        #   …+ SIB                       = 4
        #   …+ REX/多字节 opcode         = 5/6
        # 对每个 disp 字段位置 pos，合法 disp 值唯一：
        #     disp = target_rva − (va + pos + 4)
        # 所以「低字节相等」的快速筛选就能把绝大多数 pos 一秒排除。
        # 注意 disp 是**无符号按位**比较：目标地址与 pos 的差可能在 32 位外，
        # 这里按 4 字节的字节序逐位比（等价于比较 (disp & 0xFFFFFFFF)）。
        end = len(blob) - 4
        for pos in range(0, end):
            need = (target_rva - (va + pos + 4)) & 0xFFFFFFFF
            if blob[pos] != (need & 0xFF):
                continue
            if blob[pos + 1] != ((need >> 8) & 0xFF):
                continue
            if blob[pos + 2] != ((need >> 16) & 0xFF):
                continue
            if blob[pos + 3] != ((need >> 24) & 0xFF):
                continue
            for l_disp in range(3, 7):
                s = pos - l_disp
                if s >= 0:
                    consider(va + s, s, pos)
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("rva", help="数据地址（RVA），如 0x61EEA28")
    ap.add_argument("--exe", default=str(EXE))
    ap.add_argument("--writers", action="store_true", help="只看写入点")
    a = ap.parse_args()

    img = Img(Path(a.exe))
    rva = int(a.rva, 0)
    hits = scan(img, rva, a.writers)
    print(f"# 目标 RVA 0x{rva:X}（VA 0x{img.base + rva:X}）命中 {len(hits)} 处")
    for r, kind, f, text in hits:
        print(f"{kind} 0x{r:X} (func 0x{f:X}, +0x{r - f:X})   {text}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
