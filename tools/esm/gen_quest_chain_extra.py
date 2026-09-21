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

## ★★ 第 71 轮：跨系列交接 / 命名链路 / 城市线 / 引入任务 / 同伴里程碑

起因（玩家实测）：存档里**深红舰队线根本没开始**，但列表里能看到「深藏不露」（CF01）、
「宝藏号的结局」（CF08_SysDef）、「夺回曾经」（FFKeyZ01）。复查确认它们与 CF02/CF06
是同一问题类别，只是**启动边的写法 / 位置**落在前两轮规则的覆盖面之外：

  * 跨系列交接：`UC02@860 → CF01`（先锋队线自动接取；编号链规则只扫「同前缀 +1」）；
  * 终局选边：`LC088_Space@200 → CF08_SysDef`（跳上警戒号选 SysDef 路线）、
    `LC088_Space@100 → CF08_Fleet`（跳到星钥站选舰队路线）；
  * 星钥站支线：`CF08_SysDef@10 → FFKeyZ01 / FFKeyZ02`、`DialogueCFTheKey@850 → FFKeyZ02`、
    `CF01@310 → CFSD01`（fragment 注释原文 Kick Off CFSD01）；
  * 城市线三连收尾：`City_CY_RedTape01@10000 → 02 → 03`、`City_NA_Viewport01@2000 → 02 → 03`；
  * 帮派线收尾：`City_Neon_Gang03@1100 / @1200 → FFNeonZ10`；
  * 「引入任务 → 正式任务」：`MS05Intro@1000 → MS05`、`MS06Intro@200 → MS06`；
  * 同伴关系里程碑：`COM_Companion_Barrett@900 → 承诺：巴雷特`、
    `COM_Companion_SamCoe@650 → 哈特家事`；
  * 线内支线：`FC_EncryptedSlateQuest@1000 → FC08`（注释 Start FC08）。

★ 同轮做了**全量入边审计**（`tools/esm/analyze_start_paths.py`）——除收进本表的边外，
其余候选全部按类别记录在下方「有意不覆盖」清单里（A~H），避免以后重复排查。

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
    # ---- ★★ 第 71 轮：全量入边审计后的扩展 ----（起因：玩家实测存档里深红舰队线
    #      没开始，却能看到「深藏不露 / 宝藏号的结局 / 夺回曾经」。全部 261 条表内任务
    #      的入边做了一次全量审计 —— tools/esm/analyze_start_paths.py，逐条人工核实。
    #      ★ 已排除的同类候选见下方「有意不覆盖」清单，勿重复排查。）
    # -- 深红舰队线入口（联殖先锋队 UC02@860 自动接取 —— 玩家报告的「深藏不露」）--
    ("CF01", "UC02", 860, "SetStage", 205,
     "深藏不露：先锋队线 UC02@860 的 fragment 原文 CF01.SetStage(205)（自动接取）"),
    # -- 深红舰队终局「选边」（跳上警戒号 = SysDef 路线 / 跳到星钥站 = 舰队路线）--
    ("CF08_SysDef", "LC088_Space", 200, "SetStage", 10,
     "宝藏号的结局：跳上警戒号选 SysDef 路线（注释 commits to the SD path ⇒ CF07@1000 + CF08_SysDef@10）"),
    ("CF08_Fleet", "LC088_Space", 100, "SetStage", 10,
     "遗产的结局：跳到星钥站选舰队路线（注释 commits to the CF path ⇒ CF07@1500 + CF08_Fleet@10）"),
    # -- 星钥站支线（只在剧情推进到相应节点后才被带出）--
    ("FFKeyZ01", "CF08_SysDef", 10, "SetStage", 66,
     "夺回曾经：终章简报开始（CF08_SysDef@10）才启动 —— 第 69 轮「有意不覆盖」的复查收口"),
    ("FFKeyZ02", "CF08_SysDef", 10, "SetStage", 66,
     "博士的命令：终章简报开始才启动（与下一条互为「或」）"),
    ("FFKeyZ02", "DialogueCFTheKey", 850, "SetStage", 100,
     "博士的命令：星钥站对话 @850（星钥站是剧情锁地点 ⇒ 此对话同样受剧情门控）"),
    ("CFSD01", "CF01", 310, "SetStage", 5,
     "罪证的负担：CF01@310 的 fragment 注释 Kick Off CFSD01（加入舰队后才可接）"),
    # -- 自由星系线（FC08 由加密石板任务收尾启动；另一处 CREW_EliteCrew_AutumnMacM@0
    #    是「set stage and stop just to be safe」的强制关闭 ⇒ 不收）--
    ("FC08", "FC_EncryptedSlateQuest", 1000, "Start", 0,
     "奋勇当先：加密石板任务 @1000 的 fragment 注释 Start FC08 + Stop()"),
    # -- 霓虹城帮派线收尾带出的后续（两个分支各一条，互为「或」）--
    ("FFNeonZ10", "City_Neon_Gang03", 1100, "Start", 0,
     "不可告人的秘密：帮派线收尾（CompleteAllObjectives + FFNeonZ10.Start()）"),
    ("FFNeonZ10", "City_Neon_Gang03", 1200, "Start", 0,
     "不可告人的秘密：帮派线收尾（另一分支，同样 Start）"),
    # -- 火星城官僚线（三连「收尾 → 启动下一个」）--
    ("City_CY_RedTape02", "City_CY_RedTape01", 10000, "Start", 0,
     "官僚习气搪塞：RedTape01@10000 收尾（fragment 只做 RedTape02.Start()）"),
    ("City_CY_RedTape03", "City_CY_RedTape02", 10000, "Start", 0,
     "官僚习气纠正：RedTape02@10000 收尾（同上形态）"),
    # -- 新亚特兰蒂斯酒吧线（三连；01 的起点未确证 ⇒ 只收 02/03）--
    ("City_NA_Viewport02", "City_NA_Viewport01", 2000, "Start", 0,
     "流动资产：Viewport01@2000 注释 conditions met for Quest 02 to run + Start + Stop"),
    ("City_NA_Viewport03", "City_NA_Viewport02", 1000, "Start", 0,
     "老板请酒：Viewport02@1000 收尾（CompleteAllObjectives + Start + Stop）"),
    # -- 官方「引入任务 → 正式任务」（Intro 卡片完成后才启动正式任务）--
    ("MS05", "MS05Intro", 1000, "Start", 0,
     "过度设计：MS05Intro@1000 的 fragment 启动正式任务 MS05"),
    ("MS06", "MS06Intro", 200, "Start", 0,
     "第一次接触：MS06Intro@200 的 fragment 启动正式任务 MS06"),
    # -- 同伴关系里程碑（好感事件触发个人任务 / 承诺任务；`或` 语义同其它边）--
    ("COM_Quest_Barrett_Commitment", "Com_Companion_Barrett", 900, "SetStage", 50,
     "承诺：巴雷特：好感里程碑 @900（注释 Begin Quest ⇒ SetStage(50)；注意 EDID 首字母小写）"),
    ("COM_Quest_SamCoe_Q01", "COM_Companion_SamCoe", 650, "SetStage", 100,
     "哈特家事：好感里程碑 @650（fragment：清 798 目标 + 个人任务 SetStage(100)）"),
]

# ============================================================================
#  ★ 有意**不覆盖**的候选 —— ★★ 第 71 轮做了**全量入边审计**（工具
#    tools/esm/analyze_start_paths.py：5033 个脚本 / 737 条指向表内任务的启动调用 /
#    114 个「无对话·终端·Perk 起点」的任务），逐条人工核实后按下述类别排除。
#    以后复查到新候选，先看它属于哪一类；**不要再重复排查**：
#
#  [A] 对话管理器（Dialogue*）驱动 —— 玩家在对应城市/地点对话即可接（可触发）：
#      DialogueFCNeon → FFNeonZ01~09/12、DialogueFCAkilaCity → City_AkilaLife*、
#      DialogueCydonia → City_CY_* / FFCydoniaZ*、DialogueParadiso → FFParadisoZ*、
#      DialogueECSConstant → FFConstantZ04/05、DialogueNewHomestead / DialogueHopeTown /
#      DialogueGagarin_UC_GG / DialogueUCTheDen / DialogueTrackersAllianceA / DialogueUCNewAtlantis
#      等同形态。★ 例外：星钥站（剧情锁地点）的 DialogueCFTheKey@850 → FFKeyZ02 **已收**
#      （见 EDGES；它与城市对话不同 —— 星钥站在剧情推进前不可进入）。
#
#  [B] stage 0 的「收尾 / 关闭 / 初始化」形态（不是启动）：
#      City_NA_Botany03@0（把 Botany01 置 200 = 系列收尾）、City_NA_Well02@0（Well01 收尾）、
#      City_NA_Viewport03@0（同步调用）、MQ204@10（注释 shut down any Lodge quests ⇒ FFLodge01）、
#      FFNewAtlantis06@0（陌生人的善意：语义未确证 ⇒ 连同 TheKin@0 / TheBoot 一起搁置 ——
#      stage 0 的 fragment 是否在 SetStage 高 stage 时执行，可用 harness 实验定论）。
#
#  [C] Quickstart / 调试 / 存档迁移（不是正常接取路径）：
#      DialogueCydonia@5 / @8（注释 Completes the prerequisite quest ⇒ RedTape03）、
#      LC082@10（注释 Set by: Startup ⇒ CF01@2）、LC088_Space@24（注释 CF Initial Briefing
#      Quickstart）、CREW_EliteCrew_AutumnMacM@0（注释 set stage and stop just to be safe ⇒ FC08）、
#      Patch_Update02/03/07b/09 / Patch_Hotfix。
#
#  [D] 引擎 / 故事管理器 / 随机任务管理器驱动（离线无法证明「接不到」）：
#      BE_KT01~06 → SE_KT01~06（登舰遭遇；且是 Activities 无引导目标）、
#      MS01SpaceEncounter01~03 → MS01、RI_Support → RIR01~07 与 RI03（龙神职位管理器；
#      RIR 疑似 Radiant —— **若确证，正确处理是「从表里剔除」而不是加边**，留专项）、
#      LandyScript.RestartRAD05、City_AkilaLife05（场景触发）、
#      RI01_JobAdRadio@100（靠近电台 20 米即可触发 —— 玩家可达，不加边）。
#
#  [E] 同伴关系里程碑的存疑项（语义未确证，暂不覆盖）：
#      COM_Companion_Barrett@69 → COM_Quest_Barrett_Q01（SetStage(7401) + 尾声计时器）、
#      COM_Companion_Andreja@750 → COM_Quest_Andreja_Q01（SetStage(1000) 语义存疑）。
#      （已收的两条是形态干净的：Barrett@900「Begin Quest」、SamCoe@650 SetStage(100)。）
#
#  [F] 主线流程 / 不在本 MOD 关注范围：MQ_TempleQuest_01 / MQ304b（彼方之力 / 无限的尽头）、
#      MQ401/MQ402 的推进边（主线任务本身不显示）。
#
#  [G] 跨线「推进 / 回写」调用（不是启动 —— 目标早已运行）：典型如 CF08_SysDef@1000 → RAD02
#      （把 RAD02 推到 600）、UC04@1000 → RAD02、RedTape03@850/@860 → Psych01（SetStage(121)）、
#      CF06@0~8 → CFSD01（补维护）等。
#
#  [H] 已由其它判据覆盖：FFNewAtlantis01（记录级 CTDA「FFNewAtlantis03@100 + UC04 未运行」）。
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
        #    ★★ 第 71 轮：同一个调用可能在同一脚本里出现多次（如 `CF08_SysDef.SetStage(10)`
        #    在 LC088_Space 的 stage 24 / 25 / 200 三处都有）⇒ 要**逐条匹配行**、按
        #    「该行所属的 stage fragment」找 stage 相符的那一条，不能取第一条就断案
        #    （否则正常数据会被误判成「stage 不符」）。
        arg_pat = "" if (op == "Start" and arg == 0) else rf"{arg}\s*"
        call_pat = re.compile(
            rf"\b{re.escape(tgt_edid)}\s*\.\s*{op}\s*\(\s*{arg_pat}\)")

        def frag_stage_of(line_no: int) -> tuple[str | None, int | None, int | None]:
            """从 line_no 往上找最近的 Fragment_Stage_<n>_Item_* 函数定义。

            返回 (函数名, stage, 函数行号)；找不到 ⇒ (None, None, None)。
            """
            for i in range(line_no - 1, 0, -1):
                m = FRAG_FN.search(lines[i - 1])
                if m:
                    return m.group(1), int(m.group(2)), i
            return None, None, None

        hit_lines = [i for i, ln in enumerate(lines, 1) if call_pat.search(ln)]
        if not hit_lines:
            problems.append(f"{tgt_edid}：{host_file.name} 里找不到 `{tgt_edid}.{op}({arg})`")
            continue
        hit_line = None
        fn_name = None
        fn_line = None
        for i in hit_lines:
            fn_name_i, fs_stage_i, fn_line_i = frag_stage_of(i)
            if fs_stage_i == stage:
                hit_line, fn_name, fn_line = i, fn_name_i, fn_line_i
                break
        if hit_line is None:
            fn0, st0, _ = frag_stage_of(hit_lines[0])
            problems.append(
                f"{tgt_edid}：{host_file.name} 里 `{tgt_edid}.{op}({arg})` 出现在 "
                f"{len(hit_lines)} 处，但都不在 Fragment_Stage_{stage} 里"
                f"（第一处在 {fn0 or '?'}，stage {st0}）")
            continue

        # 2) 调用必须落在 Fragment_Stage_<stage>_Item_* 里（上一步已按 stage 匹配）
        if fn_name is None:
            problems.append(f"{tgt_edid}：{host_file.name}:{hit_line} 不在任何 stage fragment 里")
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
