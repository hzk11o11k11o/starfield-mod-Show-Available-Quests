#!/usr/bin/env python3
"""gen_quest_chain_extra.py - 第 69 轮：**链式门槛的扩展边**（同类问题的收口）。

起因（复查第 67/68 轮的产物时发现）：链式门槛当时只收「同前缀 + 编号 +1」的编号链路
（CF01→CF02、FC01→FC02 这种），但**同形态的「收尾→启动下一个」边不止编号链**：

  * Eleos 静修地线：`City_ER_Dead@1000 → City_ER_Ghost.Start()` → `Ghost@1000 →
    Exorcism.Start()` → `Exorcism@1000 → Peace.Start()`
    （完全停止 → 幽灵狩猎 → 驱魔 → 调停者；都是「CompleteAllObjectives + Stop + 启动下一个」）；
  * 霓虹城帮派线：`City_Neon_Gang01@500`（注释 "Start up the follow up quest"）→
    `City_Neon_Gang02@700`（注释 "Start up the next quest in the line"）→ 决战；
  * `RAD02@50 → City_NewAtlantis_Z_PrimarySources.Start()`（注释 "Start Primary Sources Z Quest"）；
  * `FFNewAtlantis03@1 → OliveBranch.Start()` / `PartingGift.Start()`（城市支线预启动）。

这些任务同样**玩家接不到**（只能由前一个任务的收尾/流程带出来），与 CF02「菜鸟觐见」
是同一个问题类别 —— 存档没做到前一步时，它们不该出现在「可接任务」里。

## 为什么是「人工核实 + 工具核验」而不是全自动扫描

宽口径扫描（`ref/_probe3.py` 那类）会捞出 100+ 条候选，里面大量是**误报**：
  * 对话管理任务（`Dialogue*`）的 stage fragment —— 那是**对话**驱动的（玩家能接）；
  * 补丁任务（`Patch_Update*`）的 stage 0 —— 存档迁移，不是接取；
  * stage 0 的「close out previous quests in the series」（如 `City_NA_Botany03@0`
    把 `Botany01` 置到 200 = **收尾**，不是启动）；
  * 引擎/故事管理器驱动的任务（空间遭遇 `SE_KT*`、`MS01SpaceEncounter*`、`BE_*` 等，
    Papyrus 里看不到真正的启动路径）；
  * 随机/悬赏任务管理器（`RI_Support`、`FCRQuestScript` 等）。

所以本表**逐条人工核实**（读 fragment 上下文 + 注释 + 全部引用），再由工具在**构建期**
对着官方 Papyrus 源码核验每条边仍然存在（任务/宿主/边三者任一不符 ⇒ 直接报错退出，
不会静默写一份错数据）。新增候选的排查工具：`tools/esm/analyze_start_paths.py`。

判据与第 67 轮完全一致（`SAQ_Decision::DecideChainGates`）：
**全部边都还没触发 ⇒ 隐藏；任一条已触发/求值不了 ⇒ 放行**。

用法：
    python tools/esm/gen_quest_chain_extra.py            # 核验 + 写 ref/quest_chain_extra.json
    python tools/esm/gen_quest_chain_extra.py --list     # 只看当前表（不核验）
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
REF = ROOT / "ref"
DEFAULT_SRC = Path(r"D:\SteamLibrary\steamapps\common\Starfield\Data\Scripts\Source\Base")
QF_FILE = re.compile(r"^QF_([A-Za-z0-9_]+)_([0-9A-Fa-f]{8})\.psc$")
FRAG_FN = re.compile(r"Function\s+(Fragment_Stage_(\d+)_Item_\d+)\s*\(")

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# ============================================================================
#  人工核实过的扩展边： (目标 EDID, 宿主 EDID, 宿主 stage, op, arg, 一行理由)
#
#  ★ 加新条目之前先读宿主 fragment 的上下文（注释/是否 CompleteAllObjectives+Stop），
#    并确认目标**没有**对话/终端/Perk 等其它起点（否则不该藏）。
# ============================================================================
EDGES: list[tuple[str, str, int, str, int, str]] = [
    # ---- Eleos 静修地线（完全停止 → 幽灵狩猎 → 驱魔 → 调停者）----
    ("City_ER_Ghost", "City_ER_Dead", 1000, "Start", 0,
     "完全停止@1000：CompleteAllObjectives + Stop + City_ER_Ghost.Start()"),
    ("City_ER_Exorcism", "City_ER_Ghost", 1000, "Start", 0,
     "幽灵狩猎@1000：CompleteAllObjectives + Stop + City_ER_Exorcism.Start()"),
    ("City_ER_Peace", "City_ER_Exorcism", 1000, "Start", 0,
     "驱魔@1000：CompleteAllObjectives + Stop + City_ER_Peace.Start()"),
    # ---- 霓虹城帮派线（面试 → 展示力量 → 决战）----
    ("City_Neon_Gang02", "City_Neon_Gang01", 500, "SetStage", 100,
     "面试@500 注释「Start up the follow up quest」+ SetActive"),
    ("City_Neon_Gang03", "City_Neon_Gang02", 700, "SetStage", 100,
     "展示力量@700 注释「Start up the next quest in the line」+ SetActive"),
    # ---- 城市支线（预启动形态）----
    ("City_NewAtlantis_Z_PrimarySources", "RAD02", 50, "Start", 0,
     "黑暗中的光芒@50 注释「Start Primary Sources Z Quest」"),
    ("City_NewAtlantis_Z_OliveBranch", "FFNewAtlantis03", 1, "Start", 0,
     "新亚特兰蒂斯城介绍@1：与 PartingGift/FFNewAtlantis01TopLevels 一起预启动"),
    ("City_NewAtlantis_Z_PartingGift", "FFNewAtlantis03", 1, "Start", 0,
     "同上（该任务在全部 Papyrus 里只有这一条起点）"),
]

# ============================================================================
#  ★ 有意**不覆盖**的候选（复查结论，避免以后重复排查）：
#    SE_KT01~06（求救信号 / 派对舰 / …）—— 宿主 BE_KT* 是引擎驱动的「登舰遭遇」，
#      真正的起点不在 Papyrus 里；且这些是 Activities 且无引导目标（列表里只显示不导航）。
#    City_AkilaLife05（轰炸区域）—— 场景（SF_AkilaCity_Tate_Greeting）触发。
#    City_NewAtlantis_Z_TheBoot / TheKindnessOfStrangers（靴子 / 陌生人的善意）——
#      互相启动 + TheKin@0 与 FFNewAtlantis06@0（SetStage 100/200）的语义无法确证
#      （stage 0 的 fragment 是否在 SetStage 高 stage 时执行，游戏内无法离线验证）。
#    City_GG_Mark / City_GG_Connections（错失目标 / 错过的接驳点）—— 互启，且
#      Mark@1/@2 是 quickstart（AddPerk + MoveTo(DebugMarker)），正常流程的起点不在 Papyrus。
#    FFKeyZ01/FFKeyZ02（夺回曾经 / 博士的命令）—— FFKeyZ02 有对话管理任务的边（玩家路径）；
#      FFKeyZ01 的宿主 CF08_SysDef@10 是「深红舰队终章开始」，早于它的可用性无法确认。
#    RIR01/03/04/07、RI03（领先一步 / 通行是关键 / …）—— 疑似 Ryujin 随机职位任务
#      （RI_Support 管理器 + PRKF_RI_BountyTrackingPerk 都提到它们），宿主多为内部管理任务。
#    MQ_TempleQuest_01 / MQ304b（彼方之力 / 无限的尽头）—— 主线流程驱动，宿主不在表内，
#      且主线任务不在本 MOD 的关注范围（AGENTS：只关注非主线任务）。
# ============================================================================


def resolve_host_file(src: Path, host_edid: str, host_local: int) -> Path | None:
    """按记录号找宿主的 QF 脚本（文件名里的 EDID 可能被截断，如 TheKin 前缀）。"""
    for f in (src / "Fragments" / "Quests").glob("QF_*_*.psc"):
        m = QF_FILE.match(f.name)
        if m and int(m.group(2), 16) == host_local:
            return f
    return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", default=str(DEFAULT_SRC))
    ap.add_argument("--quests", default=str(REF / "quests_all.json"))
    ap.add_argument("--table", default=str(REF / "quest_table_debug.json"))
    ap.add_argument("--out", default=str(REF / "quest_chain_extra.json"))
    ap.add_argument("--list", action="store_true")
    a = ap.parse_args()

    quests = json.loads(Path(a.quests).read_text(encoding="utf-8"))
    table = json.loads(Path(a.table).read_text(encoding="utf-8"))

    edid2q: dict[str, dict] = {}
    for q in quests:
        if q.get("edid") and (q.get("master") or "Starfield.esm") == "Starfield.esm":
            edid2q.setdefault(q["edid"], q)
    by_local = {q["local"]: q for q in edid2q.values()}
    table_locals = {t["local"] for t in table}

    if a.list:
        for (tgt, host, stage, op, arg, note) in EDGES:
            print(f"  {tgt:<40} <= {host}@{stage} {op}({arg})  —— {note}")
        print(f"合计：{len(EDGES)} 条边 / {len({e[0] for e in EDGES})} 条任务")
        return 0

    src = Path(a.src)
    if not src.is_dir():
        print(f"（没有 Papyrus 源码目录：{src} —— 保留现有 {a.out}，跳过核验）")
        return 0

    problems: list[str] = []
    out_by_target: dict[str, dict] = {}
    for (tgt_edid, host_edid, stage, op, arg, note) in EDGES:
        tgt = edid2q.get(tgt_edid)
        host = edid2q.get(host_edid)
        if tgt is None:
            problems.append(f"目标任务不存在：{tgt_edid}")
            continue
        if host is None:
            problems.append(f"宿主任务不存在：{host_edid}")
            continue
        if tgt["local"] not in table_locals:
            problems.append(f"目标不在「可接任务」表里（加了也没用）：{tgt_edid}")
            continue

        host_file = resolve_host_file(src, host_edid, host["local"])
        if host_file is None:
            problems.append(f"{host_edid}：找不到 QF 脚本（记录号 0x{host['local']:06X}）")
            continue
        txt = host_file.read_text(encoding="utf-8", errors="replace")
        lines = txt.splitlines()

        # 1) 调用本体必须在（属性名 = 目标 EDID，操作/参数一致）
        #    ★ Papyrus 源码里 `Start()` 是不带参数的（arg=0），而 `SetStage(100)` 带参数。
        arg_pat = "" if (op == "Start" and arg == 0) else rf"{arg}\s*"
        call_pat = re.compile(
            rf"\b{re.escape(tgt_edid)}\s*\.\s*{op}\s*\(\s*{arg_pat}\)")
        hit_line = None
        for i, ln in enumerate(lines, 1):
            if call_pat.search(ln):
                hit_line = i
                break
        if hit_line is None:
            problems.append(f"{tgt_edid}：{host_file.name} 里找不到 `{tgt_edid}.{op}({arg})`")
            continue

        # 2) 调用必须落在 Fragment_Stage_<stage>_Item_* 里
        fn_line = None
        fn_name = None
        for i in range(hit_line - 1, 0, -1):
            m = FRAG_FN.search(lines[i - 1])
            if m:
                fn_line, fn_name = i, m.group(1)
                break
        if fn_name is None:
            problems.append(f"{tgt_edid}：{host_file.name}:{hit_line} 不在任何 stage fragment 里")
            continue
        fs = FRAG_FN.search(lines[fn_line - 1])
        if int(fs.group(2)) != stage:
            problems.append(
                f"{tgt_edid}：边写在 {fn_name}（stage {fs.group(2)}）里，与表内 stage {stage} 不符")
            continue

        entry = out_by_target.setdefault(tgt_edid, {
            "formid": tgt["local"],
            "edid": tgt_edid,
            "edges": [],
        })
        entry["edges"].append({
            "host_local": host["local"],
            "host_master": host.get("master", "Starfield.esm"),
            "host_edid": host_edid,
            "host_stage": stage,
            "op": op,
            "arg": arg,
            "src": host_file.name,
            "line": hit_line,
            "note": note,
        })

    if problems:
        print("核验失败（不写产物）：")
        for p in problems:
            print("  !! " + p)
        return 1

    out = [out_by_target[k] for k in sorted(out_by_target, key=lambda e: out_by_target[e]["formid"])]
    Path(a.out).write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"wrote {a.out}")
    n_edges = sum(len(t["edges"]) for t in out)
    print(f"扩展链式门槛：{len(out)} 条任务 / {n_edges} 条启动边（全部经官方 Papyrus 源码核验）")
    for t in out:
        for e in t["edges"]:
            print(f"  {t['edid']:<40} <= {e['host_edid']}@{e['host_stage']} "
                  f"{e['op']}({e['arg']})  [{e['src']}:{e['line']}]")
    return 0


if __name__ == "__main__":
    sys.exit(main())
