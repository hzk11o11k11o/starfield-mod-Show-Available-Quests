#!/usr/bin/env python3
"""find_ctda_table.py - 找 Starfield 的「条件函数表」（CTDA function table）。

背景（第 35 轮，「进度没到不显示」）：
  Papyrus `Quest.IsStageDone` 的包装（0x20CB530）会 `call 0xD0DBD0` 做真正的
  「stage 是否完成」查询。`xrefto --call` 显示 0xD0DBD0 只有 3 个调用者，其中
  两个（0xBE6A30 / 0xC2E630 附近）是 **CTDA 条件函数**的标准形态：
      void func(ctx /*rcx*/, param1 /*rdx*/, param2 /*r8*/, float* out /*r9*/)
  把 *out 写成 1.0f / 0.0f。条件函数在引擎里应有一张「索引 → 函数指针」表
  （CTDA 原始字节 offset 8 的 u16 = 函数索引，如 GetStageDone=0x3B）。

本工具：
  1) 搜「8 字节绝对地址（首选基址 + RVA）」——函数指针被写入哪里；
  2) 若命中落在 8 字节对齐的数据区，假定它是表项，按给定 index 反推表基址；
  3) 打印表基址附近一段（每项翻译成 RVA），供肉眼确认「密集的函数指针数组」；
  4) 抽查已知索引与名字。

用法：
    python tools/re/find_ctda_table.py 0xBE6A30 --index 59
    python tools/re/find_ctda_table.py 0xBE6A30 --index 59 --probe 0x38,0x3B,0x4A,0x21F
"""
from __future__ import annotations

import argparse
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from disasm import PEFile  # noqa: E402

EXE = r"D:\SteamLibrary\steamapps\common\Starfield\Starfield.exe"
IMAGE_BASE = 0x140000000

KNOWN = {
    0x38: "GetQuestRunning",
    0x3B: "GetStageDone",
    0x47: "GetInFaction",
    0x48: "GetIsID",
    0x4A: "GetGlobalValue",
    0x136: "GetInWorldspace",
    0x1AA: "GetIsVoiceType",
    0x21F: "GetQuestCompleted",
    0x232: "LocationHasKeyword",
    0x233: "LocationHasRefType",
    0x345: "IsTrueForConditionForm",
    0x35A: "BodyHasKeyword",
    0x35C: "SystemHasKeyword",
    0x368: "GetBodySurveyPercent",
    0x394: "BiomeSupportsCreature",
}


def rva_of_off(pe: PEFile, off: int):
    for name, vaddr, vsize, rawptr, rawsize in pe.sections():
        if rawptr <= off < rawptr + rawsize:
            return name, vaddr + (off - rawptr)
    return None, None


def off_of_rva(pe: PEFile, rva: int):
    for name, vaddr, vsize, rawptr, rawsize in pe.sections():
        if vaddr <= rva < vaddr + max(vsize, rawsize):
            return name, rawptr + (rva - vaddr)
    return None, None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("rva")
    ap.add_argument("--index", type=lambda s: int(s, 0), required=True)
    ap.add_argument("--probe", default="")
    ap.add_argument("--span", type=int, default=24, help="打印表基址前后多少项")
    a = ap.parse_args()

    pe = PEFile(EXE)
    target = int(a.rva, 16)
    v = IMAGE_BASE + target
    pat = struct.pack("<Q", v)
    print(f"搜索绝对地址 0x{v:X}（RVA 0x{target:X}）…")
    hits = []
    i = 0
    while True:
        j = pe.buf.find(pat, i)
        if j < 0:
            break
        hits.append(j)
        i = j + 1
    print(f"命中 {len(hits)} 处：")
    for h in hits:
        name, rva = rva_of_off(pe, h)
        aligned = " (8 对齐)" if h % 8 == 0 else ""
        print(f"  file={h:#x} rva={rva if rva is None else hex(rva)} 段={name}{aligned}")

    if not hits:
        return 1

    # 对每个命中，试用 --index 反推表基址并打印周围
    for h in hits:
        base_off = h - a.index * 8
        if base_off < 0:
            continue
        print(f"\n=== 假定表项 file={h:#x} 是 index={a.index}，表基址 file={base_off:#x} ===")
        sname, s_rva = rva_of_off(pe, base_off)
        print(f"表基址 RVA = {s_rva if s_rva is None else hex(s_rva)}（段 {sname}）")
        lo = max(0, a.index - a.span)
        hi = a.index + a.span
        text_lo, text_hi = None, None
        for name, vaddr, vsize, rawptr, rawsize in pe.sections():
            if name == ".text":
                text_lo, text_hi = vaddr, vaddr + vsize
        good = 0
        for idx in range(lo, hi):
            off = base_off + idx * 8
            if off + 8 > len(pe.buf):
                break
            val = struct.unpack_from("<Q", pe.buf, off)[0]
            rv = val - IMAGE_BASE
            mark = ""
            if text_lo is not None and text_lo <= rv < text_hi:
                mark = "-> .text"
                good += 1
            name_hint = KNOWN.get(idx, "")
            if name_hint:
                mark += f"  ★{name_hint}"
            if idx % 1 == 0 and (mark or abs(idx - a.index) < 6):
                print(f"  [{idx:5d} 0x{idx:X}]  0x{rv:08X}  {mark}")
        print(f"（{lo}~{hi} 间落在 .text 的项：{good}）")
        break  # 只处理第一个命中

    if a.probe:
        idxs = [int(x, 0) for x in a.probe.split(",") if x.strip()]
        h = hits[0]
        base_off = h - a.index * 8
        print("\n=== 抽查 ===")
        for idx in idxs:
            off = base_off + idx * 8
            val = struct.unpack_from("<Q", pe.buf, off)[0]
            rv = val - IMAGE_BASE
            print(f"  idx 0x{idx:X} ({idx}) -> RVA 0x{rv:08X}  {KNOWN.get(idx, '')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
