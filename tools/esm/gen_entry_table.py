#!/usr/bin/env python3
"""gen_entry_table.py - 生成「无限任务入口」条目表（任务板 + 提供无限任务的 NPC + 可招募船员）。

背景（AGENTS.md 需求）：无限生成任务本身不显示，但「接取入口」可以作为一条数据出现在
可接任务列表里 —— 玩家点了就引导到那块任务板 / 那位 NPC 的具体位置。三类入口：

* **任务板**（第 27 轮起）：白名单在下面（每个城市/据点一块，14 个基础对象里挑）；
* **提供无限任务的 NPC**（第 80 轮新增）：数据来自 ref/repeatable_givers.json
  （tools/esm/gen_repeatable_givers.py）—— RAD03「长途运输」的 4 位贸易管理局商人 +
  RAD04「死亡通缉令」的 4 城追踪者联盟探员；名字自带「（可重复）」前缀（任务板不加）；
* **可招募船员**（★★★ 第 156 轮新增）：数据来自 ref/hirable_crew.json
  （tools/esm/gen_hirable_crew.py）—— 24 位精英船员（EDID 前缀 `Crew_Elite_*`）；
  名字自带「（可招募）」前缀；3 位位置不适合导航（别名暂存格 / 运行时生成内景）⇒ 不配
  兜底候选（引导链只剩引用自身 ⇒ 平时不可导航，界面照第 91 轮显示「（不可导航）」）。

任务板在数据里是 ACTIVATOR `MissionBoardConsole*`：
    python tools/esm/esm_probe.py list ACTI --grep board     # 可复现（14 条基础对象）
    python tools/esm/explore_boards.py                        # 所有放置引用的清单
挑选规则：
  * 每个城市/据点留**一块**（新亚特兰蒂斯井区、阿基拉城磐石区、霓虹城核心……）；
    「本地补给/悬赏/剧情未激活」的实例（MissionBoardConsoleLocal / _Inactive / _TESTING）
    不收录 —— 它们要么在随机前哨站、要么是剧情道具。
  * ★ `persistent` 列**必须看**：非常驻引用在所在 cell 未加载时脚本 `Game.GetForm`
    取不到（引导会报状态 2）—— 实测哪块板能引导全靠这一列（见 docs/99 第 27 轮）。

输出：
    plugin/src/SAQ_EntryTable.h     C++ 静态数组（DLL 内嵌）
    ref/entry_targets.json          同样的数据（人工核对 / 排查用）

复现：
    python tools/esm/gen_entry_table.py     # 约 1~2 分钟（全表扫一遍 Starfield.esm）
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from esm_probe import (  # noqa: E402
    DEFAULT_ESM, REF_SIGS, iter_records_with_context, record_base_form, record_edid,
)

# ★★ 第 30 轮：入口的引导目标改成**候选链**（背景见 docs/05 第九节 / docs/99 第 30 轮）——
#
#   ① 新建的**常驻 XMarker**（tools/esm/create_board_markers.py：任务板 0x900~0x90A、
#      第 80 轮 NPC 追加 0x90B~0x911，位置 = 条目坐标）—— 常驻引用在任何位置都取得到
#      ⇒ 精确落点、首选；
#   ② 条目引用自身 —— 原生常驻的（阿基拉城板）总是可用；非常驻的（全部 NPC、11 块板）
#      只有 cell 加载时可用；
#   ③ 兜底候选（表里的 fallback1/2）—— 位置差 1~7 m：
#      * 内景条目 ⇒ 同 cell 里最近的原生常驻引用；
#      * 外景条目（阿基拉城广场的探员）⇒ 该 worldspace 的**世界级常驻引用**
#        （`WRLD > WorldChildren > CellChildren > CellPersistent`；外景 cell 里官方
#        不放 per-cell 常驻引用 —— 见 gen_repeatable_givers.py）。
#
#   运行期由 DLL 依次 `LookupByID` 取第一个命中的（见 SAQ.cpp::AppendEntryRows）。
#
# ★ 为什么要「新建」而不是 override（第 29 轮的教训）：override 只替换记录数据、
#   **不改变引用的加载分类**（官方 SFBGS003/008 的同类 override 70/70 条原记录本来就是
#   常驻 = 零先例）。新建记录从第一次加载就归入 CellPersistent 组 ⇒ 引擎按常驻处理。
BOARD_MARKERS_JSON = Path("ref/board_markers.json")
ENTRY_SCAN_JSON = Path("ref/entry_persistent_scan.json")
GIVERS_JSON = Path("ref/repeatable_givers.json")   # ★ 第 80 轮：NPC 入口数据（上游工具产物）
CREW_JSON = Path("ref/hirable_crew.json")          # ★★★ 第 156 轮：可招募船员数据（gen_hirable_crew.py）
XMARKER_BASES = {0x3B, 0x34}      # XMarker / XMarkerHeading（纯位置标记，位置最稳定）
FALLBACK_MAX_DIST = 25.0          # 兜底候选的最大距离（同房间级；再远就不是「这块板」了）

# ★ 第 80 轮：入口条目的 kind（与 C++ 的 StaticEntryInfo::kind / AS3 的载荷 type 对应）。
KIND_BOARD = 0        # 任务板（AS3 type 100：子项「前往任务板」）
KIND_REPEAT_NPC = 1   # 提供无限任务的 NPC（AS3 type 101：子项「找他接活」；名字带「（可重复）」）
KIND_CREW = 2         # ★★★ 第 156 轮：可招募船员（AS3 type 102；名字带「（可招募）」）

# ★★★ 第 156 轮：段序 = 界面顺序（DLL 按表追加 + 组内稳定排序，见 main 的布局硬校验）。
#   新增入口类别时**插在最后**（同类相邻；中间插花会直接构建失败）。
SEGMENT_ORDER = (KIND_BOARD, KIND_REPEAT_NPC, KIND_CREW)


def load_markers() -> dict[int, int]:
    """refLocal -> markerLocal（0x900+i；文件缺失时返回空 = 没有 ①）。"""
    if not BOARD_MARKERS_JSON.exists():
        print(f"!! 缺少 {BOARD_MARKERS_JSON}（先跑 tools/esm/create_board_markers.py）"
              f"—— 入口引导将退化为「板自身 + 常驻兜底」")
        return {}
    data = json.loads(BOARD_MARKERS_JSON.read_text(encoding="utf-8"))
    return {m["refLocal"]: m["markerLocal"] for m in data.get("markers", [])}


def load_fallbacks() -> dict[str, list[int]]:
    """cell EDID -> [最近的常驻引用（≤2 个，XMarker 系优先、距离近优先）]。"""
    if not ENTRY_SCAN_JSON.exists():
        print(f"!! 缺少 {ENTRY_SCAN_JSON}（先跑 tools/esm/scan_entry_persistent.py）—— 没有③兜底候选")
        return {}
    data = json.loads(ENTRY_SCAN_JSON.read_text(encoding="utf-8"))
    out: dict[str, list[int]] = {}
    for cell in data.get("cells", {}).values():
        cands = []
        for t in cell.get("nearest", []):
            if not t.get("formid") or t.get("dist", 999.0) > FALLBACK_MAX_DIST:
                continue
            cands.append((0 if t.get("base") in XMARKER_BASES else 1, t["dist"], t["formid"]))
        cands.sort()
        out[cell.get("edid", "")] = [c[2] for c in cands[:2]]
    return out


def load_givers() -> list[dict]:
    """★ 第 80 轮：「提供无限任务的 NPC」入口数据（上游 tools/esm/gen_repeatable_givers.py）。"""
    if not GIVERS_JSON.exists():
        print(f"!! 缺少 {GIVERS_JSON}（先跑 tools/esm/gen_repeatable_givers.py）"
              f"—— NPC 入口条目将缺失")
        return []
    return json.loads(GIVERS_JSON.read_text(encoding="utf-8"))


def load_crew() -> list[dict]:
    """★★★ 第 156 轮：「可招募船员」入口数据（上游 tools/esm/gen_hirable_crew.py）。

    口径（docs/16 第 154/155 轮研究结论）：
      * 每位 1 处放置引用（= 引导链的「精确目标」，同时是界面 uID）；
      * 兜底候选（同 cell / world 级常驻）已经备齐 —— **不新建 marker**（第 154 轮结论：
        不新建也能配出「精确引用 → 常驻兜底」候选链）；
      * 3 位位置不适合导航（别名暂存格 / 运行时生成内景）⇒ **丢弃兜底**：引导链只剩
        引用自身（平时取不到）⇒ 条目平时不可导航 —— 界面照第 91 轮加「（不可导航）」
        前缀 + 点击提示（不是 bug，是设计）。
    """
    if not CREW_JSON.exists():
        print(f"!! 缺少 {CREW_JSON}（先跑 tools/esm/gen_hirable_crew.py）—— 船员入口条目将缺失")
        return []
    data = json.loads(CREW_JSON.read_text(encoding="utf-8"))
    return data.get("npcs", [])

# 任务板的 14 个基础对象（esm_probe list ACTI --grep board 的结果）；
# 白名单只收录其中「激活的、每个地点一块」的实例，这里仍然全列出来做 base 校验。
BOARD_BASES = {
    0x00129871: "TESTING",
    0x00137579: "Constellation",
    0x0013F737: "RI",
    0x0014E95B: "FC",
    0x001626A8: "Stroud",
    0x001A6C49: "ALL",
    0x001B39B9: "CF",
    0x001DBCAC: "Bounty",
    0x001E2672: "Plain",
    0x002DF8BF: "Supply",
    0x0033039C: "UC",
    0x003514B4: "Local",
    0x000CC9F7: "LC088_Key_Inactive_CF",
    0x0012F4A6: "LC088_Ops_Inactive_UC",
}

# (REFR FormID, 期望的 cell EDID, 英文名, 中文名)
#
# 名字规矩：中文「任务板 · <地点>」/ 英文 "Mission Board - <Place>"
#   —— 与任务条目的命名区分开（玩家一眼看出这是「入口」而不是一条任务）。
#
# ★★ 中文名必须用**游戏官方译名**（第 28 轮踩坑：曾把 The Lodge 写成「星座小屋」，
#     玩家在列表里按「陋室」找不到）。核对方法（用项目内的 strings 表直接查）：
#       python -c "import sys;sys.path.insert(0,'tools/esm');from pathlib import Path;
#                  from strings_probe import load_strings as L;
#                  en=L(Path('ref/strings/strings/starfield_en.strings'));
#                  zh=L(Path('ref/strings/strings/starfield_zhhans.strings'));
#                  print([(v,zh.get(k)) for k,v in en.items() if isinstance(v,str) and 'The Lodge'==v])"
#     已核对的官方译名：The Lodge=陋室 / Cydonia=赛多尼亚 / Ryujin Industries=龙神集团 /
#     Deimos Staryards=火卫二造船厂 / Trident Staryard=海神叉造船厂 /
#     Stroud-Eklund Staryards=斯特劳艾克伦集团造船厂 / The Key=星钥站 /
#     Hopetown=霍普镇 / New Homestead=新家园 / New Atlantis=新亚特兰蒂斯城。
ENTRIES = [
    (0x0021001E, "CityNewAtlantisWell", "Mission Board - New Atlantis", "任务板 · 新亚特兰蒂斯城"),
    (0x0014D497, "CityAkilaCityTheRock", "Mission Board - Akila City", "任务板 · 阿基拉城"),
    (0x00148C93, "CityNeonCore", "Mission Board - Neon", "任务板 · 霓虹城"),
    (0x001DF853, "CityCydoniaMainLevel", "Mission Board - Cydonia", "任务板 · 赛多尼亚"),
    (0x001DED95, "SettleHopeTownPitStop", "Mission Board - Hopetown", "任务板 · 霍普镇"),
    (0x001DF5BD, "SettleNewHomestead01", "Mission Board - New Homestead", "任务板 · 新家园"),
    (0x00137573, "CityNewAtlantisLodgeInt", "Mission Board - The Lodge", "任务板 · 陋室"),
    (0x0013F738, "LC044RyujinIndustriesHQ", "Mission Board - Ryujin Industries", "任务板 · 龙神集团"),
    (0x000C2D64, "ssSettleDeimosStaryard", "Mission Board - Deimos Staryards", "任务板 · 火卫二造船厂"),
    (0x0016265F, "ssSettleTridentStaryard", "Mission Board - Trident Staryard", "任务板 · 海神叉造船厂"),
    (0x00167872, "ssSettleStroudEklundStaryard", "Mission Board - Stroud-Eklund Staryards", "任务板 · 斯特劳艾克伦集团造船厂"),
    (0x00197D22, "StationTheKeyInterior", "Mission Board - The Key", "任务板 · 星钥站"),
]

# ★★★ 第 110 轮（追踪者联盟 · SFBGS003，medium 档）：**手工条目** —— 数据不在 Starfield.esm 里，
#   不走上面的扫描白名单，直接写死（每条都对照 ESM 实录核实）：
#
#   条目 = 追踪者联盟总部的「悬赏信息台」（任务板 `SFBGS003_MissionBoardConsole_TA_REF`）——
#   玩家从总部展示柜取通缉海报接大任务、在任务板上接精英赏金（都是无限生成玩法 ⇒ 只显示入口）。
#   候选链沿用 C++ 的三槽位语义（精确优先 + 常驻兜底）：
#     ② 任务板自身（非常驻 —— 玩家在总部时精确指向它）
#     ③ fallback1 = 展示柜 `SFBGS003_BountyBoard01_`（**常驻**、同 cell —— 远处点引导就落这里）
#     ③ fallback2 = 总部外 marker `SFBGS003_MiscPointer_InevitableTAHQExtMarkerREF`（**常驻**，阿基拉城）
#
#   local 一律写**文件内 FormID 的低位**（medium = 16 位）；运行期由
#   `Masters::MakeFormID(kQuestMasters 下标, local)` 拼出（SFBGS003 是 medium 档，
#   前缀 0xFD | idx<<16 —— 探测见 SAQ_Masters.cpp 的 Tier::Medium）。
#
# ★★★ 第 150 轮：这些条目**追加在任务板段末尾**（12 条 ENTRIES 之后、可重复 NPC 段之前）
#   —— 界面里与其它「任务板 · <地点>」连成一片（本表行顺序 = 列表顺序，见 main 的布局校验）。
EXTRA_ENTRIES: list[dict] = [
    {
        "master": "SFBGS003.esm",
        "refLocal": 0xFD0024AD,          # SFBGS003_MissionBoardConsole_TA_REF
        "persistent": False,
        "base": "SFBGS003_MissionBoardConsole_Activator",
        "cell": "SFBGS003TrackersAllianceHQ",
        "markerLocal": 0,                # 不新建 marker（常驻展示柜兜底已够）
        "fallback1": 0xFD00F9CE,         # 展示柜 SFBGS003_BountyBoard01_（常驻）
        "fallback2": 0xFD000033,         # 总部外 marker（常驻，阿基拉城）
        "kind": KIND_BOARD,
        "nameEn": "Mission Board - Trackers Alliance HQ",
        "nameZh": "任务板 · 追踪者联盟总部",
    },
]


def master_index_map() -> dict[str, int]:
    """kQuestMasters[] 的顺序（与 gen_quest_table.py 一致：Starfield.esm 固定 0，其余按名字排序）。

    ★ 第 110 轮：EXTRA_ENTRIES 要写 master 下标（SFBGS003 = 1）；从任务表产物读，
    避免两处各维护一份顺序。
    """
    qpath = Path("ref/quest_table_debug.json")
    if not qpath.exists():
        print(f"!! 缺少 {qpath} —— EXTRA_ENTRIES 的 master 下标算不出来（先跑 gen_quest_table.py）")
        return {"Starfield.esm": 0}
    rows = json.loads(qpath.read_text(encoding="utf-8"))
    masters = sorted({r.get("master", "Starfield.esm") for r in rows},
                     key=lambda m: (m.lower() != "starfield.esm", m.lower()))
    return {m: i for i, m in enumerate(masters)}


def c_escape(s: str) -> str:
    return s.replace("\\", "\\\\").replace('"', '\\"')


def main() -> int:
    print("读 Starfield.esm（约 1~2 分钟）…")
    buf = Path(DEFAULT_ESM).read_bytes()

    want = set(REF_SIGS)
    want.add(b"CELL")
    cells: dict[int, str] = {}
    found: dict[int, tuple[int, int, int, int]] = {}
    for sig, formid, flags, cell, world, payload in iter_records_with_context(buf, want):
        if sig == b"CELL":
            cells[formid] = record_edid(payload)
            continue
        base = record_base_form(payload)
        if base in BOARD_BASES:
            found[formid] = (base, flags, cell, world)

    markers = load_markers()
    fallbacks = load_fallbacks()
    givers = load_givers()
    crew = load_crew()

    rows = []
    problems = []
    for refr, cell_edid, en, zh in ENTRIES:
        info = found.get(refr)
        if info is None:
            problems.append(f"白名单里的 REFR {refr:08X} 没找到（数据变了？）")
            continue
        base, flags, cell, _world = info
        actual_cell = cells.get(cell, "")
        if actual_cell != cell_edid:
            problems.append(f"REFR {refr:08X} 所在 cell 是 {actual_cell!r}，白名单写的是 {cell_edid!r}")
        fb = fallbacks.get(actual_cell, [])
        rows.append({
            "refLocal": refr,
            "refHex": f"0x{refr:08X}",
            "master": 0,                      # Starfield.esm（kQuestMasters[0]）
            "persistent": bool(flags & 0x400),
            "base": BOARD_BASES[base],
            "cell": actual_cell,
            "markerLocal": markers.get(refr, 0),          # ① 新建常驻 XMarker（首选）
            "fallback1": fb[0] if len(fb) > 0 else 0,     # ③ 同 cell 原生常驻引用（兜底）
            "fallback2": fb[1] if len(fb) > 1 else 0,
            "kind": KIND_BOARD,
            "nameEn": en,
            "nameZh": zh,
        })

    if problems:
        print("!! 白名单校验失败：")
        for p in problems:
            print("   -", p)
        return 1

    # ★★★ 第 150 轮（玩家反馈：「追踪者联盟的任务板没有和其他任务板排序在一起」）：
    #   手工条目（追踪者联盟悬赏信息台）**追加在任务板段末尾** —— 紧接 ENTRIES 的 12 条
    #   任务板之后、可重复 NPC 段之前。列表顺序 = 本表顺序（DLL 先追加、后按组稳定排序
    #   ⇒ 组内保持表顺序，见 SAQ.cpp::CollectAvailableQuests 的第 96 轮注释）——
    #   第 110 轮曾把它追加在**表末尾** ⇒ 界面里落在一串「（可重复）…」入口与可重复
    #   任务之间，看起来不像任务板（玩家截图：MISSION BOARD - TRACKERS ALLIANCE HQ
    #   夹在 4 条「TRACKERS ALLIANCE AGENT」与「（可重复）ONE RIOT…」之间）。
    #   master 下标从任务表产物解析（SFBGS003 = 1，见 master_index_map）。
    master_idx = master_index_map()
    for extra in EXTRA_ENTRIES:
        m = extra["master"]
        if m not in master_idx:
            problems.append(f"EXTRA_ENTRIES：{m} 不在 kQuestMasters 里（先把它的任务加进表）")
            continue
        if not extra.get("fallback1"):
            problems.append(f"EXTRA_ENTRIES：{extra['nameZh']} 没有兜底候选（远处将不可导航）")
        rows.append({
            **extra,
            "master": master_idx[m],
            "refHex": f"0x{extra['refLocal']:08X}",
        })

    # ★ 第 80 轮：「提供无限任务的 NPC」条目（ref/repeatable_givers.json —— 上游已把
    #   「REFR / 常驻性 / 兜底候选 / 官方名」全部核验过，这里只做合并与少量交叉校验）。
    for g in givers:
        if g.get("persistent"):
            problems.append(f"{g['edid']} 在 repeatable_givers.json 里是常驻 —— "
                            f"预期非常驻（常驻性判定变了？重跑 gen_repeatable_givers.py）")
            continue
        if not g.get("fallback1"):
            problems.append(f"{g['edid']} 没有兜底候选（远处将不可导航）")
        rows.append({
            "refLocal": g["refLocal"],
            "refHex": g["refHex"],
            "master": 0,
            "persistent": False,
            "base": g["edid"],                            # NPC_ EDID（人工核对用）
            "cell": g["cell"],
            "markerLocal": markers.get(g["refLocal"], 0), # 内景 NPC 有；外景（阿基拉城探员）没有
            "fallback1": g.get("fallback1") or 0,
            "fallback2": g.get("fallback2") or 0,
            "kind": KIND_REPEAT_NPC,
            "nameEn": g["nameEn"],
            "nameZh": g["nameZh"],
        })

    # ★★★ 第 156 轮：「可招募船员」条目（ref/hirable_crew.json —— 上游 gen_hirable_crew.py
    #   已把「放置引用 / 常驻性 / 两档兜底候选 / 招募任务 / 不可导航」全部核验过，
    #   这里只做合并与交叉校验）。
    #   不新建 marker（第 154 轮结论：兜底候选已就位）；3 位不可导航的**丢弃兜底** ——
    #   引导链只剩引用自身 ⇒ 平时不可导航，界面显示「（不可导航）」前缀（第 91 轮口径）。
    for c in crew:
        no_nav = bool(c.get("noNav"))
        if not c.get("refLocal"):
            problems.append(f"{c.get('edid', '?')} 没有放置引用（RefLocal=0）")
            continue
        if not no_nav and not c.get("fallback1"):
            problems.append(f"{c['edid']} 没有兜底候选（远处将不可导航）—— "
                            f"重跑 gen_hirable_crew.py 或检查 noNav 口径")
        if no_nav and not c.get("noNavReason"):
            problems.append(f"{c['edid']} 标了 noNav 但没有理由（口径要能解释给玩家看）")
        rows.append({
            "refLocal": c["refLocal"],
            "refHex": c["refHex"],
            "master": 0,                                   # 全在 Starfield.esm（kQuestMasters[0]）
            "persistent": bool(c.get("persistent")),
            "base": c["edid"],                             # NPC_ EDID（人工核对用）
            "cell": c.get("cell", ""),
            "markerLocal": 0,                              # 不新建 marker（兜底候选已就位）
            # 不可导航 ⇒ 丢弃兜底（否则远处会落到「玩家到不了的 cell 里」的常驻引用上）
            "fallback1": 0 if no_nav else (c.get("fallback1") or 0),
            "fallback2": 0 if no_nav else (c.get("fallback2") or 0),
            "kind": KIND_CREW,
            "nameEn": c["displayEn"],
            "nameZh": c["displayZh"],
        })

    # ★★★ 第 150/156 轮：**布局硬校验** —— 同类入口必须连成一段，且段序 = SEGMENT_ORDER
    #   （任务板段 → 可重复 NPC 段 → 可招募船员段）。第 110 轮的手工条目曾被追加在表末尾
    #   （落在 NPC 段之后）⇒ 界面里那块任务板混进「（可重复）…」堆里（第 150 轮玩家反馈的
    #   直接原因：表顺序 = 列表顺序，DLL 先按表追加、再按组稳定排序 ⇒ 组内保持表顺序）。
    #   把「顺序即布局」钉在这里：以后新增条目插花会直接构建失败，而不是静默错位。
    #   实现 = 段序下标必须**单调不减**（等价于「同类相邻」）。
    seg_index = {k: i for i, k in enumerate(SEGMENT_ORDER)}
    max_seen = -1
    for r in rows:
        idx = seg_index.get(r["kind"])
        if idx is None:
            problems.append(f"入口顺序：{r['nameZh']} 的 kind={r['kind']} 不在 SEGMENT_ORDER 里")
            continue
        if idx < max_seen:
            problems.append(
                f"入口顺序：{r['nameZh']}（kind={r['kind']}）插在了后面的段落里 —— "
                f"同类入口必须相邻（段序 = 任务板 → 可重复 NPC → 可招募船员，见第 150/156 轮）")
        max_seen = max(max_seen, idx)

    if problems:
        print("!! 入口数据校验失败：")
        for p in problems:
            print("   -", p)
        return 1

    n_board = sum(1 for r in rows if r["kind"] == KIND_BOARD)
    n_npc = sum(1 for r in rows if r["kind"] == KIND_REPEAT_NPC)
    n_crew = sum(1 for r in rows if r["kind"] == KIND_CREW)
    n_crew_nav = sum(1 for r in rows if r["kind"] == KIND_CREW and r["fallback1"])
    n_pers = sum(1 for r in rows if r["persistent"])
    n_marker = sum(1 for r in rows if r["markerLocal"])
    n_fb = sum(1 for r in rows if r["fallback1"])
    print(f"入口条目：{len(rows)} 条（任务板 {n_board} / 可重复 NPC {n_npc} / "
          f"可招募船员 {n_crew}（其中可兜底导航 {n_crew_nav}）；"
          f"原生常驻 {n_pers}；新建 marker {n_marker} 条；兜底候选 {n_fb} 条）")
    kind_tag = {KIND_BOARD: "板", KIND_REPEAT_NPC: "NPC", KIND_CREW: "船员"}
    for r in rows:
        flag = "P" if r["persistent"] else "-"
        mk = f"marker=0x{r['markerLocal']:03X}" if r["markerLocal"] else "marker=--- "
        fb = (f"兜底=0x{r['fallback1']:06X}/0x{r['fallback2']:06X}" if r["fallback1"]
              else "兜底=---")
        kind = kind_tag.get(r["kind"], "?")
        print(f"  [{flag}][{kind}] {r['refHex']} {mk} {fb} {r['cell']:<32s} {r['nameZh']}")

    # ---- 头文件 ----
    lines = []
    lines.append("#pragma once")
    lines.append("// 本文件由 tools/esm/gen_entry_table.py 自动生成，请勿手改。")
    lines.append("//")
    lines.append("// 「无限任务入口」条目（AGENTS.md 需求 —— 无限生成任务本身不显示，但「接取入口」")
    lines.append("// 作为一条数据显示在列表里，点了就引导到它的位置）。三类：")
    lines.append("//   kind=0（任务板，13 条）：ACTIVATOR `MissionBoardConsole*`，名字「任务板 · <地点>」；")
    lines.append("//     ★★ 第 110 轮 +1：追踪者联盟总部（SFBGS003.esm · medium 档手工条目，见 EXTRA_ENTRIES）")
    lines.append("//        —— ★★★ 第 150 轮：它追加在**任务板段末尾**、与 12 条基础任务板连成一段")
    lines.append("//        （界面里紧挨其它「任务板 · <地点>」；此前排在表末尾 ⇒ 混进了「（可重复）…」堆）；")
    lines.append("//   kind=1（可重复 NPC，8 条）：贸易管理局商人 / 追踪者联盟探员（第 80 轮），")
    lines.append("//     名字自带「（可重复）」前缀 —— 数据 ref/repeatable_givers.json；")
    lines.append("//   kind=2（可招募船员，24 条）：精英船员（`Crew_Elite_*`，第 156 轮），")
    lines.append("//     名字自带「（可招募）」前缀 —— 数据 ref/hirable_crew.json；")
    lines.append("//     3 位位置不适合导航（别名暂存格 / 运行时生成内景）⇒ 不配兜底（平时不可导航，")
    lines.append("//     界面照第 91 轮显示「（不可导航）」前缀）；")
    lines.append("//     ★★★ 第 150/156 轮：本表**行顺序 = 界面列表顺序**（DLL 按表追加 + 组内稳定排序）")
    lines.append("//       —— 段序固定为「任务板段 → 可重复 NPC 段 → 可招募船员段」（main 有布局硬校验）。")
    lines.append("//")
    lines.append("// 字段说明（★ 第 30 轮起，引导目标是**候选链**：DLL 依次 LookupByID 取第一个命中的）——")
    lines.append("//   refLocal   条目引用的记录号（任务板 ACTIVATOR / NPC 的 ACHR）—— 同时是界面条目的")
    lines.append("//              uID（运行期 FormID）。")
    lines.append("//   master     所属 master 下标（kQuestMasters[]；第 110 轮起含 SFBGS003.esm=medium）。")
    lines.append("//   persistent 条目引用自身是否**原生常驻**（45 条里只有阿基拉城任务板与船员瓦斯科是）。")
    lines.append("//   markerLocal ① 本插件（ESM 记录号：任务板 0x900~0x90A、NPC 0x90B~0x911）新建的")
    lines.append("//              **常驻 XMarker**，位置 = 条目坐标：常驻引用在 cell 未加载时依然存在")
    lines.append("//              ⇒ 任何位置都取得到 ⇒ 引导目标。外景条目（阿基拉城广场的探员）不建")
    lines.append("//              marker（外景 cell 无 per-cell 常驻引用可挂），= 0。")
    lines.append("//              运行期 FormID = (本插件加载序号 << 24) | markerLocal —— 前缀取")
    lines.append("//              Guide 通道的 ch.prefix（SAQ_Guide.cpp 已认领的值）。")
    lines.append("//   fallback1/2 ③ 兜底候选（XMarker 系优先、≤25 m）—— 位置差 1~7 m：")
    lines.append("//              内景条目 = 同 cell 的原生常驻引用；外景条目 = 该 worldspace 的**世界级")
    lines.append("//              常驻引用**（`WRLD > WorldChildren > CellChildren > CellPersistent`）。")
    lines.append("//   kind       0 = 任务板（AS3 type 100，子项「前往任务板」）；")
    lines.append("//              1 = 可重复 NPC（AS3 type 101，子项「找他接活」+ 名字带「（可重复）」）；")
    lines.append("//              2 = 可招募船员（AS3 type 102，子项「招募他作为船员」+ 名字带「（可招募）」。")
    lines.append("//                  ★ 第 156 轮起：DLL 对 kind=2 做 P/A 判据过滤 —— 引用可读时")
    lines.append("//                  「P=1 且 A=0」才显示（P=0 未解锁 / A=1 已招募 都隐藏；")
    lines.append("//                  引用未加载读不到 ⇒ 保守显示，见 SAQ.cpp::AppendEntryRows）。")
    lines.append("//   nameZh/En  列表里显示的名字（中英都推，AS3 按游戏语言挑）。")
    lines.append("//")
    lines.append("// 实机排查看 DLL 日志的「入口=…(可导航 N｜marker a 原板 b 兜底 c 不可用 d)」与")
    lines.append("// 「入口候选诊断：…」（SAQ.cpp::AppendEntryRows）。")
    lines.append("")
    lines.append("#include <cstdint>")
    lines.append("")
    lines.append("namespace SAQ")
    lines.append("{")
    lines.append("\t// ★ 第 80 轮：与 AS3 载荷 type / gen_entry_table.py 的 KIND_* 对应。")
    lines.append("\tenum EntryKind : std::uint8_t")
    lines.append("\t{")
    lines.append("\t\tkEntryKindBoard = 0,        // 任务板（AS3 type 100）")
    lines.append("\t\tkEntryKindRepeatNpc = 1,    // 提供无限任务的 NPC（AS3 type 101）")
    lines.append("\t\tkEntryKindCrew = 2,         // ★ 第 156 轮：可招募船员（AS3 type 102）")
    lines.append("\t};")
    lines.append("")
    lines.append("\tstruct StaticEntryInfo")
    lines.append("\t{")
    lines.append("\t\tstd::uint32_t refLocal;")
    lines.append("\t\tstd::uint8_t  master;")
    lines.append("\t\tbool          persistent;")
    lines.append("\t\tstd::uint32_t markerLocal;   // ① 新建常驻 XMarker（0 = 没有）")
    lines.append("\t\tstd::uint32_t fallback1;     // ③ 兜底候选（内景 = 同 cell；外景 = 同 world 世界级）")
    lines.append("\t\tstd::uint32_t fallback2;")
    lines.append("\t\tstd::uint8_t  kind;          // ★ 第 80 轮：EntryKind")
    lines.append("\t\tconst char*   nameEn;")
    lines.append("\t\tconst char*   nameZh;")
    lines.append("\t};")
    lines.append("")
    lines.append("\tinline constexpr StaticEntryInfo kEntryTable[] = {")
    for r in rows:
        p = "true " if r["persistent"] else "false"
        lines.append(
            f'\t\t{{ {r["refLocal"]:#010x}u, {r["master"]}u, {p}, '
            f'{r["markerLocal"]:#010x}u, {r["fallback1"]:#010x}u, {r["fallback2"]:#010x}u, '
            f'{r["kind"]}u, "{c_escape(r["nameEn"])}", "{c_escape(r["nameZh"])}" }},'
        )
    lines.append("\t};")
    lines.append(f"\tinline constexpr std::size_t kEntryTableSize = {len(rows)};")
    lines.append("}")
    lines.append("")

    out_header = Path("plugin/src/SAQ_EntryTable.h")
    out_header.write_text("\n".join(lines), encoding="utf-8")
    print(f"已写出 {out_header}（{out_header.stat().st_size} B）")

    out_json = Path("ref/entry_targets.json")
    out_json.write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"已写出 {out_json}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
