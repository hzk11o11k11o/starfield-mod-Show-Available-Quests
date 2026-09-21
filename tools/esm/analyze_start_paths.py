#!/usr/bin/env python3
"""analyze_start_paths.py - 第 69 轮：**「玩家能不能接到」的全量起点审计**。

背景：第 67 轮的链式门槛只收「同前缀 + 编号 +1 + 来自 stage fragment」的启动边，
起因是 CF02/CF06 这类**编号任务链的后续环节**误入「可接任务」列表。但同类形态不止一种：
`City_ER_Dead → City_ER_Ghost → City_ER_Exorcism → City_ER_Peace`（无编号）、
`City_GG_Mark ↔ City_GG_Connections`（互启）等等。

本工具把「表内 261 条任务」的**全部起点调用**按调用方分类，找出：
  * 只有「另一个任务的 stage fragment 启动」、没有任何「玩家可触发起点」
    （对话 INFO / 终端 / Perk）的任务 —— 这些就是「同类问题」的候选；
  * 已有链式数据覆盖的（quest_chain.json）单列，便于确认收敛情况。

调用方分类（按脚本所在目录，见 Base\Fragments\*）：
  * `Fragments\\Quests\\QF_<任务>_<formid>.psc` —— 任务自己的脚本；函数名
    `Fragment_Stage_NNNN_Item_MM` = **stage fragment**（任务进度推动 ⇒ 玩家没接前一个任务时
    这个调用永远不会发生）；其它函数另算。
  * `Fragments\\TopicInfos\\TIF_*` —— 对话 INFO 片段（玩家在对话里选择 ⇒ 可触发）。
  * `Fragments\\Terminals\\TERM_*` —— 终端菜单片段（玩家操作终端 ⇒ 可触发）。
  * `Fragments\\Scenes\\SF_*` —— 场景片段（可能由对话、也可能由任务进度触发 ⇒ 不计入可触发）。
  * `Fragments\\Packages\\PF_*` —— 包片段（NPC 行为触发 ⇒ 不计入）。
  * `Fragments\\Perks\\PRK_*`（如存在）—— Perk 片段（玩家点技能解锁 ⇒ 可触发）。
  * 根目录 / 其它 —— 系统脚本（Patch_Update* / 别名脚本等），单独归类。

用法：
    python tools/esm/analyze_start_paths.py                # 摘要 + 候选清单
    python tools/esm/analyze_start_paths.py --all          # 连「已有链式数据」的也展开
    python tools/esm/analyze_start_paths.py --out ref/start_paths_report.txt
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
REF = ROOT / "ref"
DEFAULT_SRC = Path(r"D:\SteamLibrary\steamapps\common\Starfield\Data\Scripts\Source\Base")

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

CALL = re.compile(r"\b([A-Za-z_]\w*)\s*\.\s*(Start|SetStage|CompleteQuest)\s*\(\s*(\d+)?\s*\)")
QF_NAME = re.compile(r"^QF_([A-Za-z0-9_]+)_([0-9A-Fa-f]{8})$")
TIF_NAME = re.compile(r"^TIF_([A-Za-z0-9_]+)_([0-9A-Fa-f]{8})$")
SF_NAME = re.compile(r"^SF_([A-Za-z0-9_]+)_([0-9A-Fa-f]{8})$")
TERM_NAME = re.compile(r"^TERM_([A-Za-z0-9_]+)_([0-9A-Fa-f]{8})$")
PF_NAME = re.compile(r"^PF_([A-Za-z0-9_]+)_([0-9A-Fa-f]{8})$")
PRK_NAME = re.compile(r"^PRK_([A-Za-z0-9_]+)_([0-9A-Fa-f]{8})$")
FRAG_STAGE = re.compile(r"Fragment_Stage_(\d+)_Item_(\d+)")
FUNCDEF = re.compile(r"Function\s+(\w+)\s*\(")

# 玩家可触发的起点类别（保守：对话 / 终端 / Perk）
PLAYER_KINDS = {"dialogue", "terminal", "perk"}


def kind_of(path: Path) -> tuple[str, str | None]:
    """返回 (类别, 宿主 EDID 猜测)。按所在目录 + 文件名判定。"""
    stem = path.stem
    parts = {p.lower() for p in path.parts}
    if "fragments" in parts:
        if "quests" in parts:
            m = QF_NAME.match(stem)
            return "qscript", (m.group(1) if m else None)
        if "topicinfos" in parts:
            m = TIF_NAME.match(stem)
            return "dialogue", (m.group(1) if m else None)
        if "terminals" in parts:
            m = TERM_NAME.match(stem)
            return "terminal", (m.group(1) if m else None)
        if "scenes" in parts:
            m = SF_NAME.match(stem)
            return "scene", (m.group(1) if m else None)
        if "packages" in parts:
            m = PF_NAME.match(stem)
            return "package", (m.group(1) if m else None)
        if "perks" in parts:
            m = PRK_NAME.match(stem)
            return "perk", (m.group(1) if m else None)
        return "frag-other", None
    return "script", None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", default=str(DEFAULT_SRC))
    ap.add_argument("--all", action="store_true", help="连已有链式数据覆盖的候选也展开")
    ap.add_argument("--out", default="")
    a = ap.parse_args()

    quests = json.loads((REF / "quests_all.json").read_text(encoding="utf-8"))
    table = json.loads((REF / "quest_table_debug.json").read_text(encoding="utf-8"))
    chain_path = REF / "quest_chain.json"
    chain = json.loads(chain_path.read_text(encoding="utf-8")) if chain_path.exists() else []

    base = [q for q in quests if (q.get("master") or "Starfield.esm") == "Starfield.esm" and q.get("edid")]
    edid2q: dict[str, dict] = {}
    for q in base:
        edid2q.setdefault(q["edid"], q)
    by_local = {q["local"]: q for q in base}

    table_locals = {t["local"] for t in table}
    table_name = {t["local"]: (t.get("name_zh") or t.get("edid") or "?") for t in table}
    table_flags = {t["local"]: int(t.get("dnam_flags", 0)) for t in table}
    covered_tgt = {c["formid"] for c in chain}

    lines: list[str] = []

    def out(s: str = "") -> None:
        lines.append(s)
        print(s)

    # ---- 扫全部脚本，收集「指向表内任务的起点调用」 ----
    edges: list[dict] = []
    src = Path(a.src)
    for f in sorted(src.rglob("*.psc")):
        txt = f.read_text(encoding="utf-8", errors="replace")
        kind, host_edid = kind_of(f)
        host_q = edid2q.get(host_edid) if host_edid else None
        host_local = host_q["local"] if host_q else None
        for m in CALL.finditer(txt):
            prop, op, arg = m.group(1), m.group(2), m.group(3)
            n = int(arg) if arg else 0
            if op == "SetStage" and n == 0:
                continue  # 重置/回退，不是启动
            tgt = edid2q.get(prop)
            if tgt is None or tgt["local"] not in table_locals:
                continue
            if host_local == tgt["local"]:
                continue  # 自己推自己
            head = txt[: m.start()]
            fdef = list(FUNCDEF.finditer(head))
            fn = fdef[-1].group(1) if fdef else "?"
            fs = FRAG_STAGE.match(fn)
            stage = int(fs.group(1)) if fs else None
            eff_kind = kind
            if kind == "qscript":
                if stage is not None:
                    eff_kind = "qstage"
                elif fn.startswith("Fragment_"):
                    eff_kind = "qfrag-other"
                else:
                    eff_kind = "qfunc"
            edges.append({
                "target": tgt["local"], "op": op, "arg": n,
                "src": f.name, "line": head.count("\n") + 1, "func": fn,
                "kind": eff_kind, "host_edid": host_edid, "host_local": host_local,
                "stage": stage,
            })

    out(f"扫描脚本：{len(list(src.rglob('*.psc')))} 个 .psc")
    out(f"指向表内任务的起点调用（Start / SetStage>0 / CompleteQuest，排除自调用）：{len(edges)}")

    # ---- 按目标聚合 ----
    per: dict[int, list[dict]] = defaultdict(list)
    for e in edges:
        per[e["target"]].append(e)

    cand: list[tuple[int, list[dict], list[str]]] = []
    for local, es in per.items():
        kinds = {e["kind"] for e in es}
        if not (kinds & {"qstage", "qfrag-other", "qfunc"}):
            continue
        if kinds & PLAYER_KINDS:
            continue
        # 「根目录系统脚本」（Patch_Update* / 别名脚本等）也算一种非玩家路径 —— 单独标
        cand.append((local, es, sorted(kinds)))
    cand.sort(key=lambda x: (x[0] in covered_tgt, x[0]))

    covered_n = sum(1 for c in cand if c[0] in covered_tgt)
    out(f"\n候选（只有任务脚本侧起点、无对话/终端/Perk 起点）：{len(cand)} 条"
        f"（其中 {covered_n} 条已被第 67 轮链式数据覆盖）")
    out("=" * 100)

    for local, es, kinds in cand:
        if local in covered_tgt and not a.all:
            continue
        tag = "★已有链式数据" if local in covered_tgt else "☆未覆盖"
        flag = table_flags.get(local, 0)
        sge = "（StartGameEnabled）" if flag & 1 else ""
        out(f"\n● {table_name.get(local, '?'):<24} 0x{local:06X} edid={by_local[local].get('edid'):<34}"
            f" [{tag}] {sge}kinds={','.join(kinds)}")
        for e in sorted(es, key=lambda x: (x["src"], x["line"])):
            host = e["host_edid"] or f"(未解析 {e['src']})"
            st = f"stage {e['stage']}" if e["stage"] is not None else f"func {e['func']}"
            out(f"    <= {host:<30} {st:<20} {e['op']}({e['arg']})   [{e['src']}:{e['line']}]")

    if a.out:
        Path(a.out).write_text("\n".join(lines), encoding="utf-8")
        print(f"\nwrote {a.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
