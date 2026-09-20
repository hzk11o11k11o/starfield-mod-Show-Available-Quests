#!/usr/bin/env python3
"""analyze_info_gates.py - 大项 D：对话侧「进度门槛」的正式数据生成。

数据来源：ref/info_gates.json（scan_info_gates.py 全表扫描产物）。

判据（保守，误藏最小化 —— 设计依据见 docs/08 与 docs/05 第二十二节）：
  * 任务的对话挂在它自己的 QUST children 组下；「任务运行中」的对话不能用来
    判定「能不能接到」 ⇒ **排除「推进类」**（条件组里含「自引用 == 1」的 INFO）。
  * 参与判定的 INFO = **入口类**（含「自引用 == 0」：任务还没开始时才出现的对话）
    + **中性类**（无自引用）。两档都只取「引用别的任务」的进度条件（want 0/1）。
  * **任务的每条参与判定 INFO 都必须有非空条件集**，否则整条任务不进表（保守）。
  * 运行时判据（DLL）：**全部参与判定的 INFO 都至少有「一条已知为假」的条件 ⇒ 隐藏**
    （任一 INFO 的条件全为真/不可判定 ⇒ 可能可用 ⇒ 显示）。
    「成对条件」（如 X==0 / X==1 各有一条 INFO）会自动豁免 —— 验证例：
    Com_Companion_Barrett（不隐藏）、大器晚成 / 亲爱的姐妹（与记录级 gate 一致）。

用法：
    python tools/esm/analyze_info_gates.py          # 写 ref/info_gates_final.json
"""
from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
REF = ROOT / "ref"

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ALLOWED_KINDS = ("入口", "中性")
FUNC_TO_CHECK = {"GetQuestRunning": 0, "GetQuestCompleted": 1, "GetStageDone": 2}


def main() -> int:
    raw = json.loads((REF / "info_gates.json").read_text(encoding="utf-8"))
    table = json.loads((REF / "quest_table_debug.json").read_text(encoding="utf-8"))
    master_idx = {}
    for q in table:
        master_idx.setdefault(q.get("master") or "Starfield.esm", len(master_idx))

    # quest -> info -> [条件]
    per_quest: dict[int, dict[int, list]] = defaultdict(dict)
    for g in raw["gates"]:
        if g["kind"] not in ALLOWED_KINDS:
            continue
        if g["want"] not in (0, 1):
            continue
        if g["func"] not in FUNC_TO_CHECK:
            continue
        # 前置任务必须也在表里（master 可解析）—— 引用别的 master 的序列化在下面做
        per_quest[g["quest"]].setdefault(g["info"], []).append(g)

    out = []
    n_skipped_empty = 0
    for q in table:
        master = q.get("master") or "Starfield.esm"
        if master != "Starfield.esm":
            continue  # 本轮只做基础游戏（DLC 的 INFO 待后续扩展；保守：不判定）
        infos = per_quest.get(q["formid"])
        if not infos:
            continue
        if not all(v for v in infos.values()):
            n_skipped_empty += 1
            continue
        ser = []
        for info_id, conds in sorted(infos.items()):
            cs = []
            for c in conds:
                cs.append({
                    "func": FUNC_TO_CHECK[c["func"]],
                    "quest_master": 0,          # 前置任务目前全在 Starfield.esm
                    "quest_local": int(c["pre"]) & 0xFFFFFF,
                    "want": int(c["want"]),
                    "stage": int(c.get("stage", 0)) & 0xFFFF,
                })
            ser.append({"info": info_id, "conds": cs})
        out.append({
            "formid": q["formid"],
            "master": master,
            "edid": q["edid"],
            "nameZh": q.get("name_zh"),
            "infos": ser,
        })

    total_conds = sum(len(i["conds"]) for t in out for i in t["infos"])
    print(f"INFO 门槛（大项 D）：{len(out)} 条任务 / "
          f"{sum(len(t['infos']) for t in out)} 条参与判定的对话 / {total_conds} 条条件")
    print(f"（另有 {n_skipped_empty} 条任务因「存在无条件的参与对话」被保守跳过）")
    for t in out:
        print(f"  {t['nameZh'] or t['edid']:<24} [{t['edid']:<34} 0x{t['formid']:06X}] {len(t['infos'])} 条对话")

    path = REF / "info_gates_final.json"
    path.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\nwrote {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
