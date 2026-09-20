#!/usr/bin/env python3
"""event_sink_probe.py - 判断某个 `MissionMenu_*` / `DataMenu_*` 之类的 AS3→C++ UI 事件
在引擎里**到底有没有被处理**（有没有 C++ sink）。

为什么需要它（第 37 轮的教训）：
    第 36 轮把「设定航线（R）」照抄原版实现 —— AS3 `BSUIDataManager.dispatchEvent(
    new CustomEvent("MissionMenu_PlotToLocation", {questID, objectiveID}))`。
    实机测试：日志里能看到 AS3 侧确实发了请求（`星图:已请求(代理任务 0x…)`），
    但引擎**毫无反应**（星图没打开）。用本工具离线复核才定案：
    `BSTGlobalEvent::EventSource<MissionMenu_PlotToLocation>` 这个事件源单例在
    整个 exe 里只有它**自己的静态初始化函数**引用它 —— 也就是说**没有任何 sink
    注册**，dispatch 出去的事件没人处理。同族的 MissionMenu_ShowItemLocation /
    MissionMenu_ToggleTrackingQuest / DataMenu_PlotToLocation 三个事件同样如此。
    ⇒ 「照抄原版 AS3 的那一行」在这类事件上不成立，必须自己调引擎的原生能力。

它是怎么工作的（全部静态可复现）：
    1) 按名字找到事件名字符串（.rdata）；
    2) 找 RIP 相对引用它的那条 `lea` —— 那是该事件的**静态初始化函数**
       （函数里会：构造 BSFixedString（名字）→ 取事件源单例地址 → 注册进全局事件表）；
    3) 从初始化函数里抓出**事件源单例**（.data 段里的那个 `lea` 目标）；
    4) 对单例做全量 RIP 相对引用扫描：
         * 只有初始化函数自己那几处引用 ⇒ **没有 sink**（事件是死的）；
         * 出现别的函数（尤其带 `RegisterSink` 形状的）⇒ 那个函数就是注册处，
           顺着它就能找到 ProcessEvent 的实现。

用法：
    python tools/re/event_sink_probe.py MissionMenu_PlotToLocation MissionMenu_ShowItemLocation
    python tools/re/event_sink_probe.py DataMenu_PlotToLocation MissionMenu_ToggleTrackingQuest
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from findrefs import scan  # noqa: E402
from func import EXE, Img  # noqa: E402
from capstone import CS_ARCH_X86, CS_MODE_64, Cs  # noqa: E402

# 事件源单例所在段（.data）—— 初始化函数里 `lea reg, [rip+…]` 指向它的那一处
SINGLETON_SECTION = ".data"


def probe(img: Img, md: "Cs", name: str) -> None:
    print(f"\n######## {name}")
    off = img.data.find(name.encode("ascii"))
    if off < 0:
        print("  字符串没找到（名字拼错了？）")
        return
    s_rva = img.off_to_rva(off)
    print(f"  字符串 RVA 0x{s_rva:X}")

    init_fn = None
    for rva, kind, fn, text in scan(img, s_rva):
        init_fn = fn
        print(f"  引用: {kind} 0x{rva:X} (func 0x{fn:X})   {text}")
    if init_fn is None:
        print("  没有任何代码引用 —— 可能是被运行时注册的字符串表")
        return

    # 初始化函数前 0x80 字节里，指向 .data 的 lea 目标 = 事件源单例
    blob = img.data[img.rva_to_off(init_fn):img.rva_to_off(init_fn) + 0x80]
    for insn in md.disasm(blob, init_fn):
        if insn.mnemonic != "lea" or "[rip" not in insn.op_str:
            continue
        for op in insn.operands:
            if op.type == 3 and op.mem.base == 41:  # X86_OP_MEM / X86_REG_RIP
                tgt = insn.address + insn.size + op.mem.disp
                if img.section_of(tgt) != SINGLETON_SECTION:
                    continue
                print(f"  事件源单例: 0x{tgt:X}")
                hits = scan(img, tgt)
                for rva, kind, fn, text in hits:
                    print(f"      {kind} 0x{rva:X} (func 0x{fn:X}, +0x{rva - fn:X})  {text}")
                # ★ 判据（踩过一次假阳性）：注册 sink 一定是**读**单例地址
                #   （`lea rcx, [单例]` / `mov rcx, [单例]` 之后 call RegisterSink）；
                #   而**写**单例的是引擎自己的静态构造（把共享 vtable 0x4B03D20 装进
                #   每个事件源单例的小函数，见 0x39A4CE0 一带）—— 那不是 sink。
                readers = [h for h in hits if h[1].strip() == "read" and h[2] != init_fn]
                if not readers:
                    # 注意：控制台是 GBK，别用「=>」以外的符号（⇒ 会 UnicodeEncodeError）
                    print("      => **除初始化之外没有任何「读」= 没有 C++ sink，"
                          "dispatch 这个事件不会有任何效果**")
                else:
                    print(f"      => 有 {len(readers)} 处「读」来自别的函数 —— 去那里找注册/处理逻辑：")
                    for rva, kind, fn, text in readers:
                        print(f"        0x{rva:X} (func 0x{fn:X}, +0x{rva - fn:X})  {text}")
                return


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 1
    img = Img(EXE)
    md = Cs(CS_ARCH_X86, CS_MODE_64)
    md.detail = True
    for name in sys.argv[1:]:
        probe(img, md, name)
    return 0


if __name__ == "__main__":
    sys.exit(main())
