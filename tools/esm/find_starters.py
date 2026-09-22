#!/usr/bin/env python3
"""find_starters.py - 「谁启动了这个任务」（官方 Papyrus 源码全扫；第 106 轮转正工具）。

用途（覆盖面复盘 / 链式边取证）：给一个或多个 QUST 的 EDID，列出全部启动调用 ——
`<目标>.Start()` / `.SetStage(N)` / `.CompleteQuest()` / `<目标>_QuestStartKeyword.SendStoryEvent()`，
带文件名 + 行号 + 代码原文。用于：
  * audit_coverage.py 筛出「无 QTYP 真任务」候选后，判断它们**玩家能不能接到**
    （有对话管理器 / 终端 / 守卫脚本 / 前一任务收尾 fragment 的调用 = 可接）；
  * 给 gen_quest_chain_extra.py 加新边时确定**精确 stage 号**（哪个 fragment 里调用）。

用法：
    python tools/esm/find_starters.py COM_Quest_Barrett_Q02 City_Akila_Ashta01 ...
    python tools/esm/find_starters.py --src "<Papyrus 源码目录>" <EDID> ...

★ 与 analyze_start_paths.py 的分工：那个工具只审计**表内任务**的入边（并按调用方
  分类）；本工具是「任意 EDID 的单点查询」，覆盖面复盘用。
"""
from __future__ import annotations
import re
import sys
from pathlib import Path

DEFAULT_SRC = Path(r"D:\SteamLibrary\steamapps\common\Starfield\Data\Scripts\Source\Base")
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

argv = sys.argv[1:]
src = DEFAULT_SRC
if "--src" in argv:
    i = argv.index("--src")
    src = Path(argv[i + 1])
    del argv[i:i + 2]

targets = argv
if not targets:
    print("用法：find_starters.py [--src <源码目录>] <EDID> [EDID...]")
    sys.exit(1)

pats = {t: re.compile(r"\b" + re.escape(t) + r"\s*(?:\.\s*(Start|SetStage|CompleteQuest)\s*\(\s*(\d+)?|"
                      r"_QuestStartKeyword\s*\.\s*(SendStoryEvent\w*)\s*\()") for t in targets}

hits = 0
for p in sorted(src.rglob("*.psc")):
    try:
        text = p.read_text(encoding="utf-8", errors="replace")
    except OSError:
        continue
    for i, line in enumerate(text.splitlines(), 1):
        for t, pat in pats.items():
            if pat.search(line):
                hits += 1
                print(f"[{t}] {p.relative_to(src)}:{i}")
                print(f"      {line.strip()[:150]}")
print(f"\n共 {hits} 处命中（源：{src}）")
