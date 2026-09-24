#!/usr/bin/env python3
r"""find_papyrus_native.py —— Papyrus native 函数「名 → 注册点 → 实现 → 虚槽」链条解析。

为什么需要它（第 157 轮的一手教训）：
    commonlibsf 的 Actor.h 把 `Actor::IsInFaction` 标在 vtable 槽 **0x175**，
    而 1.16.244 实际在 **0x174**（commonlibsf 整体错位 1 槽）—— 直接调
    `a_actor->IsInFaction()` 会编到错误槽位（实测恒 false，把一个「按 1 字节
    索引查表」的函数当成成员查询用；实机代价 = 4 位真「可招募」船员被错藏）。
    验证槽位的**权威途径** = 看游戏自己怎么调：
    Papyrus native 的注册实现里就是一条 `call qword ptr [rax+0xBA0]`
    ⇒ 槽 = 0xBA0 / 8 = 0x174。

本工具把这条链条自动化（换游戏版本后重跑即可重验；SAQ_Crew 的函数头指纹
就是用它的输出来钉的）：
    1. 在 Starfield.exe 镜像里搜 native 名字符串（如 "IsInFaction"）；
    2. 找引用该字符串的代码（RIP 相对 lea）—— native 注册处；
    3. 在注册函数里找 `lea rXX, [rip+d]` + `mov [reg+0x50], rXX`
       （= 注册结构的实现函数指针；IsInFaction 实测 0x50）；
    4. 反汇编实现函数：
       * 找第一条 `call qword ptr [reg+disp32]`（若有）= 虚调用 ⇒ 输出槽号
         （disp32 / 8）—— 这就是 commonlibsf 该标的槽；
       * 打印实现函数头 32 字节（SAQ_Crew.cpp 的 kIsInFactionSig 指纹来源）。

用法：
    python tools/re/find_papyrus_native.py IsInFaction
    python tools/re/find_papyrus_native.py IsInFaction --class Actor
        （--class：顺带定位 `.?AV<class>@@` 的 primary vtable，打印该槽指向的
          函数头 32 字节 —— 这就是 SAQ_Crew.cpp 的 kIsInFactionSig 指纹来源）
    python tools/re/find_papyrus_native.py AddToAvailableCrew --dump 0x80
"""
from __future__ import annotations

import argparse
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from rtti_slots import load, rva_to_off  # noqa: E402

EXE = Path(r"D:\SteamLibrary\steamapps\common\Starfield\Starfield.exe")
MODRM_RIP = {0x05, 0x0D, 0x15, 0x1D, 0x25, 0x2D, 0x35, 0x3D}
REGNAME = ("rax", "rcx", "rdx", "rbx", "rsp", "rbp", "rsi", "rdi",
           "r8", "r9", "r10", "r11", "r12", "r13", "r14", "r15")


def find_string(data, sections, needle: str):
    """在 .rdata/.data 里找 ASCII 字符串，返回 RVA 列表。"""
    blob = needle.encode("ascii")
    hits = []
    for name, vaddr, vsize, rawptr in sections:
        if name not in (".rdata", ".data"):
            continue
        seg = data[rawptr:rawptr + max(vsize, 1)]
        start = 0
        while True:
            k = seg.find(blob, start)
            if k < 0:
                break
            hits.append(vaddr + k)
            start = k + 1
    return hits


def find_xrefs(text, text_rva, target: int):
    """在 .text 里找 `lea/mov reg, [rip+disp32]` 且目标 == target 的位置。"""
    hits = []
    n = len(text)
    i = 0
    while i + 7 <= n:
        if text[i] == 0x48 and text[i + 1] in (0x8D, 0x8B) and text[i + 2] in MODRM_RIP:
            disp = struct.unpack_from("<i", text, i + 3)[0]
            if text_rva + i + 7 + disp == target:
                hits.append(text_rva + i)
                i += 3
                continue
        i += 1
    return hits


def disasm_insns(data, sections, start_rva: int, size: int):
    import capstone
    md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_64)
    md.detail = True
    fo = rva_to_off(sections, start_rva)
    if fo is None:
        return None, []
    return md, list(md.disasm(data[fo:fo + size], start_rva))


def next_insn_target(insn) -> int:
    """`lea rXX, [rip+d]` 的目标地址。"""
    return insn.address + insn.size + insn.disp


def class_primary_slot(data, base, sections, class_name: str, slot: int, dump: int) -> bool:
    """定位 `.?AV<class>@@` 的 primary vtable（COL offset=0 且 self 自洽），
    打印槽 [slot] 指向函数的 RVA 与头 dump 字节（指纹）。"""
    from rtti_slots import find_name
    tds = find_name(sections, data, base, class_name + "@@")
    if not tds:
        print(f"  （找不到类 {class_name} 的 TypeDescriptor）")
        return False
    td = tds[0]
    o = rva_to_off(sections, td)
    name = data[o + 0x10:].split(b"\x00", 1)[0].decode("latin1", "replace")
    rlo = next(s for s in sections if s[0] == ".rdata")[1]
    rhi = rlo + next(s for s in sections if s[0] == ".rdata")[2]
    tlo = next(s for s in sections if s[0] == ".text")[1]
    thi = tlo + next(s for s in sections if s[0] == ".text")[2]

    # 找 primary COL（offset == 0 且 self 自洽）
    col = None
    for cand in range(rlo, rhi - 0x18, 4):
        co = rva_to_off(sections, cand)
        if co is None:
            continue
        try:
            sig, c_off, cd, ptd, pcd, selfr = struct.unpack_from("<IIIIII", data, co)
        except Exception:
            continue
        if sig == 1 and selfr == cand and c_off == 0 and ptd == td:
            col = cand
            break
    if col is None:
        print(f"  （{name}：找不到 primary COL/offset=0）")
        return False

    # 找 vtable（vtable-8 处 == &COL，且首槽在 .text）
    need = struct.pack("<Q", base + col)
    vo = None
    for cand in range(rlo, rhi - 8, 8):
        off2 = rva_to_off(sections, cand)
        if off2 is None or data[off2:off2 + 8] != need:
            continue
        vt = cand + 8
        fo = rva_to_off(sections, vt)
        if fo is None:
            continue
        fn0 = struct.unpack_from("<Q", data, fo)[0] - base
        if tlo <= fn0 < thi:
            vo = vt
            break
    if vo is None:
        print(f"  （{name}：找不到 vtable）")
        return False

    fo = rva_to_off(sections, vo + slot * 8)
    fn = struct.unpack_from("<Q", data, fo)[0] - base
    print(f"  [{class_name} primary vtable] RVA 0x{vo:X}  槽 0x{slot:X} → 函数 RVA 0x{fn:X}")
    ffo = rva_to_off(sections, fn)
    head = data[ffo:ffo + dump]
    print("  [槽函数头 " + str(dump) + " 字节] " + " ".join(f"{b:02X}" for b in head))
    return True


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("name", help="Papyrus native 名（如 IsInFaction）")
    ap.add_argument("--class", dest="cls", default=None,
                    help="顺带定位 `.?AV<class>@@` 的 primary vtable 并打印该槽函数头")
    ap.add_argument("--dump", type=lambda s: int(s, 0), default=0x40,
                    help="实现函数头打印字节数（默认 0x40）")
    a = ap.parse_args()

    data, base, sections, _ = load(EXE)
    text = next(s for s in sections if s[0] == ".text")
    text_rva, text_size = text[1], text[2]
    text_bytes = data[text[3]:text[3] + max(text_size, 1)]

    # 1) 字符串（大小写两种都试）
    str_hits = find_string(data, sections, a.name) or find_string(data, sections, a.name.lower())
    if not str_hits:
        print(f"找不到字符串 {a.name!r} —— 名字拼写？或该函数不是 native 注册形式")
        return 1
    print(f"字符串 {a.name!r}：{len(str_hits)} 处 → {[hex(x) for x in str_hits]}")

    for s_rva in str_hits:
        # 2) 引用点（注册代码）
        refs = find_xrefs(text_bytes, text_rva, s_rva)
        if not refs:
            print(f"  RVA 0x{s_rva:X}：无代码引用（可能是别名 / 数据）")
            continue
        for ref in refs:
            print(f"\n=== 注册点 RVA 0x{ref:X}（引用字符串 0x{s_rva:X}）===")
            _, insns = disasm_insns(data, sections, ref - 0x20, 0x80)
            for ins in insns:
                mark = "  <== 引用点" if ins.address <= ref < ins.address + ins.size else ""
                print(f"  {ins.address:08X}  {ins.mnemonic:<8} {ins.op_str}{mark}")

            # 3) 在注册点之后找 impl（lea rXX, [rip+d] + mov [reg+0x50], rXX）
            _, insns = disasm_insns(data, sections, ref, 0x400)
            impl = None
            for i, ins in enumerate(insns):
                if ins.mnemonic == "lea" and "[rip" in ins.op_str and ins.disp != 0:
                    if i + 1 < len(insns):
                        nxt = insns[i + 1]
                        if nxt.mnemonic == "mov" and "[rip" not in nxt.op_str \
                                and "+ 0x50]" in nxt.op_str:
                            impl = next_insn_target(ins)
                            print(f"\n  [impl] `{ins.mnemonic} {ins.op_str}` + "
                                  f"`{nxt.mnemonic} {nxt.op_str}` ⇒ RVA 0x{impl:X}")
                            break
            if impl is None:
                print("\n  （注册点后 0x400 字节内没找到 [+0x50] 实现指针 —— 人工看上面的反汇编）")
                continue

            # 4) 反汇编 impl：第一条内存 call = 虚调用（⇒ 槽号）；打印函数头字节
            _, impl_insns = disasm_insns(data, sections, impl, 0x300)
            slot = None
            for ins in impl_insns or []:
                if ins.mnemonic == "call" and "ptr [" in ins.op_str and "[rip" not in ins.op_str:
                    reg = ins.op_str.split("[")[1].split(" ")[0].split("+")[0].strip()
                    disp = ins.disp
                    if reg in REGNAME and disp and disp % 8 == 0:
                        slot = disp // 8
                        print(f"  [虚调用] `{ins.mnemonic} {ins.op_str}`"
                              f" ⇒ 基址寄存器 {reg} + disp 0x{disp:X}"
                              f" ⇒ **槽 0x{slot:X}**（disp/8）")
                    break

            fo = rva_to_off(sections, impl)
            head = data[fo:fo + a.dump]
            print(f"  [函数头 {a.dump} 字节] " +
                  " ".join(f"{b:02X}" for b in head))
            if slot is None:
                print("  （impl 里没有内存 call —— 该 native 直接实现，无虚槽）")
            elif a.cls:
                print(f"\n  --- 顺带取证：{a.cls} 的 primary vtable 槽 0x{slot:X} ---")
                class_primary_slot(data, base, sections, a.cls, slot, 0x20)
    return 0


if __name__ == "__main__":
    sys.exit(main())
