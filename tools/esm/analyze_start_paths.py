#!/usr/bin/env python3
"""analyze_start_paths.py - 「玩家能不能接到」的全量起点审计（第 69 轮；★★ 第 78 轮扩口径）。

背景：第 67 轮的链式门槛只收「同前缀 + 编号 +1 + 来自 stage fragment」的启动边，
起因是 CF02/CF06 这类**编号任务链的后续环节**误入「可接任务」列表。但同类形态不止一种：
`City_ER_Dead → City_ER_Ghost → City_ER_Exorcism → City_ER_Peace`（无编号）、
`City_GG_Mark ↔ City_GG_Connections`（互启）等等。

本工具把「表内 261 条任务」的**全部起点调用**按调用方分类，找出：
  * 只有「另一个任务的 stage fragment 启动」、没有任何「玩家可触发起点」
    （对话 INFO / 终端 / Perk）的任务 —— 这些就是「同类问题」的候选；
  * 已有链式数据覆盖的（quest_chain.json + 扩展边 + 同伴「后续」门槛）单列。

★★ 第 78 轮（龙神线收口后复查「其他任务是不是也有类似现象」）：三处扩口径 ——
  ① **目标集从「基础游戏」扩到表内全部 master**：DLC 的 fragment 源码就在
     `Data\\Scripts\\Source\\Base\\{SFBGS00D,SFBGS003,DLC03}\\Fragments\\*`；
     旧版只把 `Starfield.esm` 的任务当目标 ⇒ **DLC 的起点调用全被丢掉**（假收敛）；
  ② **「故事事件」形态也算起点**：`<目标EDID>_QuestStartKeyword.SendStoryEvent()` /
     `…SendStoryEventAndWait()`（第 77 轮龙神线那种写法；旧 CALL 正则看不见它）；
  ③ 每条候选附**门槛状态**（chain / cond / info 计数 + 同伴固定显示 / 势力开头固定显示）
     —— `[暴露]`（三类门槛都是 0、又不固定显示）就是玩家报的那一类最高危条目。

调用方分类（按脚本所在目录，见 Base\\Fragments\\* 与 Base\\<DLC>\\Fragments\\*）：
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
# ★★ 第 78 轮：故事事件形态（`RIR03_QuestStartKeyword.SendStoryEvent()`）——
#   与 Start/SetStage 同为「启动边」，只是经故事管理器落地。
STORY = re.compile(
    r"\b([A-Za-z_]\w*)_QuestStartKeyword\s*\.\s*(SendStoryEvent(?:AndWait)?)\s*\(")
# ★ 注意：下面这些正则是拿 **path.stem**（已去掉 .psc）去 match 的 —— 别加 `\.psc$`
#   （第 78 轮踩过：加了之后宿主全部解析不出来，报告里全是「(未解析 QF_…)」）。
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
    # ★★ 第 78 轮：目标集 = **表内全部 master**（含 DLC）—— quest_table_debug.json 里
    #   每条表行都有 edid / local(低 24 位) / 三类门槛计数，比只读基础游戏准。
    tbl = json.loads((REF / "quest_table_debug.json").read_text(encoding="utf-8"))
    table_by_edid: dict[str, dict] = {}
    table_by_local: dict[int, dict] = {}
    for t in tbl:
        if t.get("edid"):
            table_by_edid.setdefault(t["edid"], t)
        table_by_local[int(t["local"]) & 0xFFFFFF] = t

    chain_path = REF / "quest_chain.json"
    chain = json.loads(chain_path.read_text(encoding="utf-8")) if chain_path.exists() else []
    # ★ 第 71 轮：覆盖集要把**扩展边**也算上（此前只读编号链 ⇒ 第 69 轮加过的扩展边
    #   目标被误标成「☆未覆盖」，审计时得人工再过滤一遍）。
    chain_extra_path = REF / "quest_chain_extra.json"
    chain_extra = (json.loads(chain_extra_path.read_text(encoding="utf-8"))
                   if chain_extra_path.exists() else [])
    # ★★ 第 78 轮：同伴「后续」任务的启动边（第 74 轮）也进覆盖集。
    companion_path = REF / "companion_quests.json"
    comp_followup: list[dict] = []
    if companion_path.exists():
        for g in json.loads(companion_path.read_text(encoding="utf-8")):
            for q in g.get("quests", []):
                fg = q.get("followUpGate")
                if fg:
                    comp_followup.append({
                        "formid": int(q["formid"]),
                        "edges": [{
                            "host_local": int(fg["hostLocal"]),
                            "host_master": fg.get("hostMaster", "Starfield.esm"),
                            "host_stage": int(fg["hostStage"]),
                        }],
                    })

    all_chain = list(chain) + list(chain_extra) + comp_followup
    covered_tgt: dict[int, set[tuple[int, int]]] = defaultdict(set)
    for c in all_chain:
        t = int(c["formid"]) & 0xFFFFFF
        for e in c.get("edges", []):
            covered_tgt[t].add((int(e["host_local"]) & 0xFFFFFF, int(e["host_stage"])))

    edid2q: dict[str, dict] = {}
    for q in quests:
        if q.get("edid"):
            edid2q.setdefault(q["edid"], q)
    # ★★ 第 78 轮：文件名里的 EDID 可能是**旧名/大小写不同**（如 CF01 的 QF 文件叫
    #   `QF_BF01_00009136.psc`；`Com_Companion_Barrett` 文件里写成大写开头）——
    #   补两层兜底：① EDID 大小写不敏感；② 文件名末尾 8 位记录号（低 24 位）查表。
    edid2q_ci = {k.lower(): v for k, v in edid2q.items()}
    by_local_any: dict[int, dict] = {}
    for q in quests:
        by_local_any.setdefault(int(q.get("local", q["formid"])) & 0xFFFFFF, q)
    fname_fid = re.compile(r"^[A-Za-z]+_[A-Za-z0-9_]+_([0-9A-Fa-f]{8})$")

    lines: list[str] = []

    def out(s: str = "") -> None:
        lines.append(s)
        print(s)

    # ---- 扫全部脚本，收集「指向表内任务的起点调用」 ----
    edges: list[dict] = []
    story_unresolved: dict[str, int] = defaultdict(int)
    src = Path(a.src)
    files = sorted(src.rglob("*.psc"))
    for f in files:
        txt = f.read_text(encoding="utf-8", errors="replace")
        kind, host_edid = kind_of(f)
        host_q = None
        if host_edid:
            host_q = edid2q.get(host_edid) or edid2q_ci.get(host_edid.lower())
        if host_q is None:
            # 文件名里的记录号兜底（EDID 改过名 / 大小写不一致时）
            m2 = fname_fid.match(f.stem)
            if m2:
                host_q = by_local_any.get(int(m2.group(1), 16) & 0xFFFFFF)
        host_local = (int(host_q["local"]) & 0xFFFFFF) if host_q else None
        if host_q and host_q.get("edid"):
            host_edid = host_q["edid"]  # 报告里用真实 EDID（而不是文件名里的旧名）
        hits: list[tuple[int, str, str, int]] = []
        for m in CALL.finditer(txt):
            prop, op, arg = m.group(1), m.group(2), m.group(3)
            n = int(arg) if arg else 0
            if op == "SetStage" and n == 0:
                continue  # 重置/回退，不是启动
            hits.append((m.start(), prop, op, n))
        for m in STORY.finditer(txt):
            prop, op = m.group(1), m.group(2)
            if prop not in table_by_edid:
                story_unresolved[prop] += 1
                continue
            hits.append((m.start(), prop, op, 0))
        for (pos, prop, op, n) in hits:
            tgt = table_by_edid.get(prop)
            if tgt is None:
                continue
            tgt_local = int(tgt["local"]) & 0xFFFFFF
            if host_local == tgt_local:
                continue  # 自己推自己
            head = txt[:pos]
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
                "target": tgt_local, "op": op, "arg": n,
                "src": f.name, "line": head.count("\n") + 1, "func": fn,
                "kind": eff_kind, "host_edid": host_edid, "host_local": host_local,
                "stage": stage,
            })

    out(f"扫描脚本：{len(files)} 个 .psc（含 DLC 源码目录）")
    out(f"指向表内任务的起点调用（Start / SetStage>0 / CompleteQuest / SendStoryEvent，"
        f"排除自调用）：{len(edges)}")
    if story_unresolved:
        top = sorted(story_unresolved.items(), key=lambda kv: -kv[1])
        out(f"故事事件关键词（前缀不是表内任务 EDID，未计入）：{len(top)} 种 —— "
            + ", ".join(f"{k}×{v}" for k, v in top[:12]) + (" …" if len(top) > 12 else ""))

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
        cand.append((local, es, sorted(kinds)))

    def gate_state(local: int) -> tuple[str, bool]:
        """门槛状态标签 + 是否「暴露」（三类门槛全 0 且不固定显示）。"""
        t = table_by_local.get(local)
        if t is None:
            return "（不在表内）", False
        ch = int(t.get("chain_count", 0))
        cd = int(t.get("cond_count", 0))
        ig = int(t.get("info_group_count", 0))
        comp = int(t.get("companion", -1))
        pin = int(t.get("companion_pin", 0) or 0)
        fe = int(t.get("faction_entry", -1))
        tags = []
        if ch:
            tags.append("链式门槛")
        if cd:
            tags.append("进度门槛")
        if ig:
            tags.append("INFO门槛")
        if comp >= 0:
            tags.append("同伴入口(固定)" if pin else "同伴后续")
        if fe >= 0:
            tags.append("势力开头(固定)")
        exposed = not (ch or cd or ig or pin or fe >= 0)
        return ("+".join(tags) if tags else "（无门槛）"), exposed

    exposed_n = sum(1 for (local, _es, _k) in cand if gate_state(local)[1])
    covered_n = sum(1 for (local, _es, _k) in cand if local in covered_tgt)
    cand.sort(key=lambda x: (0 if gate_state(x[0])[1] else 1, x[0] in covered_tgt, x[0]))
    out(f"\n候选（只有任务脚本侧起点、无对话/终端/Perk 起点）：{len(cand)} 条"
        f"（覆盖 {covered_n} 条；★ **[暴露]** = 三类门槛全 0 且不固定显示：{exposed_n} 条）")
    out("=" * 100)

    for local, es, kinds in cand:
        covered = local in covered_tgt
        if covered and not a.all:
            continue
        gt = table_by_local.get(local, {})
        tag = "★已有链式数据" if covered else "☆未覆盖"
        gate, exposed = gate_state(local)
        flag = int(gt.get("dnam_flags", 0))
        sge = "（StartGameEnabled）" if flag & 1 else ""
        exp = " [暴露]" if exposed else ""
        name = gt.get("name_zh") or gt.get("name_en") or "?"
        out(f"\n● {name:<24} 0x{local:06X} edid={gt.get('edid', '?'):<34}"
            f" master={gt.get('master', '?')} [{tag}]{exp} 门槛={gate} {sge}kinds={','.join(kinds)}")
        # 这条候选的起点调用里，有多少条**已记进链式数据**
        #   ★ 只标「已记入」；「已覆盖但一条都没对上」才值得人工复查（曾用来抓
        #     文件名 EDID 改名/大小写导致的**假警报** —— 第 78 轮已修）。
        known = covered_tgt.get(local, set())
        n_match = 0
        for e in sorted(es, key=lambda x: (x["src"], x["line"])):
            host = e["host_edid"] or f"(未解析 {e['src']})"
            st = f"stage {e['stage']}" if e["stage"] is not None else f"func {e['func']}"
            mark = ""
            if e["kind"] in ("qstage", "qfrag-other", "qfunc") and e["stage"] is not None \
                    and e["host_local"] is not None:
                if (e["host_local"], e["stage"]) in known:
                    mark = "  ←已记入链式数据"
                    n_match += 1
            out(f"    <= {host:<30} {st:<20} {e['op']}({e['arg']})   [{e['src']}:{e['line']}]{mark}")
        if covered and n_match == 0:
            out(f"    ★ 注意：已记录 {len(known)} 条边，但源码里一条对应调用都没找到"
                f"（复查该任务的数据）")

    if a.out:
        Path(a.out).write_text("\n".join(lines), encoding="utf-8")
        print(f"\nwrote {a.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
