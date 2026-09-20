#!/usr/bin/env python3
"""gen_entry_table.py - 生成「无限任务入口」（任务板）条目表。

背景（AGENTS.md 需求）：无限生成任务本身不显示，但「接取入口」（任务板）可以作为
一条数据出现在可接任务列表里 —— 玩家点了就引导到那块任务板的具体位置。

数据来源：Starfield.esm 的世界数据（REFR）+ 本文件里的**白名单**（人工挑的代表性
任务板，每个城市/据点一块）。任务板在数据里是 ACTIVATOR `MissionBoardConsole*`：
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
#   ① 新建的**常驻 XMarker**（tools/esm/create_board_markers.py：记录号 0x900~0x90A，
#      位置 = 任务板坐标）—— 常驻引用在任何位置都取得到 ⇒ 精确落点、首选；
#   ② 任务板引用自身 —— 原生常驻的（阿基拉城）总是可用；非常驻的只有 cell 加载时可用；
#   ③ 同 cell 里离板最近的**原生常驻引用**（表里的 fallback1/2）—— 位置差 1~20 m，兜底。
#
#   运行期由 DLL 依次 `LookupByID` 取第一个命中的（见 SAQ.cpp::AppendEntryRows）。
#
# ★ 为什么要「新建」而不是 override（第 29 轮的教训）：override 只替换记录数据、
#   **不改变引用的加载分类**（官方 SFBGS003/008 的同类 override 70/70 条原记录本来就是
#   常驻 = 零先例）。新建记录从第一次加载就归入 CellPersistent 组 ⇒ 引擎按常驻处理。
BOARD_MARKERS_JSON = Path("ref/board_markers.json")
ENTRY_SCAN_JSON = Path("ref/entry_persistent_scan.json")
XMARKER_BASES = {0x3B, 0x34}      # XMarker / XMarkerHeading（纯位置标记，位置最稳定）
FALLBACK_MAX_DIST = 25.0          # 兜底候选的最大距离（同房间级；再远就不是「这块板」了）


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
            "nameEn": en,
            "nameZh": zh,
        })

    if problems:
        print("!! 白名单校验失败：")
        for p in problems:
            print("   -", p)
        return 1

    n_pers = sum(1 for r in rows if r["persistent"])
    n_marker = sum(1 for r in rows if r["markerLocal"])
    n_fb = sum(1 for r in rows if r["fallback1"])
    print(f"入口条目：{len(rows)} 条（原生常驻 {n_pers} / 非常驻 {len(rows) - n_pers}；"
          f"新建 marker {n_marker} 条；常驻兜底 {n_fb} 条）")
    for r in rows:
        flag = "P" if r["persistent"] else "-"
        mk = f"marker=0x{r['markerLocal']:03X}" if r["markerLocal"] else "marker=--- "
        fb = (f"兜底=0x{r['fallback1']:06X}/0x{r['fallback2']:06X}" if r["fallback1"]
              else "兜底=---")
        print(f"  [{flag}] {r['refHex']} {mk} {fb} {r['cell']:<32s} {r['nameZh']}")

    # ---- 头文件 ----
    lines = []
    lines.append("#pragma once")
    lines.append("// 本文件由 tools/esm/gen_entry_table.py 自动生成，请勿手改。")
    lines.append("//")
    lines.append("// 「无限任务入口」条目（任务板）：AGENTS.md 需求 —— 无限生成任务本身不显示，")
    lines.append("// 但「接取入口」（任务板）作为一条数据显示在列表里，点了就引导到它的位置。")
    lines.append("//")
    lines.append("//")
    lines.append("// 字段说明（★ 第 30 轮起，引导目标是**候选链**：DLL 依次 LookupByID 取第一个命中的）——")
    lines.append("//   refLocal   任务板 ACTIVATOR 的放置引用记录号 —— 同时是界面条目的 uID（运行期 FormID）。")
    lines.append("//   master     所属 master 下标（kQuestMasters[]；目前全部在 Starfield.esm）。")
    lines.append("//   persistent 任务板引用自身是否**原生常驻**（12 条里只有阿基拉城是）。")
    lines.append("//   markerLocal ① 本插件（ESM 记录号 0x900+i）新建的**常驻 XMarker**，位置 = 任务板坐标：")
    lines.append("//              常驻引用在 cell 未加载时依然存在 ⇒ 任何位置都取得到 ⇒ 首选引导目标。")
    lines.append("//              运行期 FormID = (本插件加载序号 << 24) | markerLocal —— 前缀取")
    lines.append("//              Guide 通道的 ch.prefix（SAQ_Guide.cpp 已认领的值）。")
    lines.append("//   fallback1/2 ③ 同 cell 里离板最近的**原生常驻引用**（XMarker 系优先、≤25 m）——")
    lines.append("//              位置差 1~20 m，作为「新建 marker 万一不被引擎接受」的兜底。")
    lines.append("//   nameZh/En  列表里显示的名字（中英都推，AS3 按游戏语言挑）。")
    lines.append("//")
    lines.append("// 实机排查看 DLL 日志的「入口目标来源：marker N / 原板 N / 兜底 N / 不可用 N」与")
    lines.append("// 「入口候选诊断：…」（SAQ.cpp::AppendEntryRows）。")
    lines.append("")
    lines.append("#include <cstdint>")
    lines.append("")
    lines.append("namespace SAQ")
    lines.append("{")
    lines.append("\tstruct StaticEntryInfo")
    lines.append("\t{")
    lines.append("\t\tstd::uint32_t refLocal;")
    lines.append("\t\tstd::uint8_t  master;")
    lines.append("\t\tbool          persistent;")
    lines.append("\t\tstd::uint32_t markerLocal;   // ① 新建常驻 XMarker（0 = 没有）")
    lines.append("\t\tstd::uint32_t fallback1;     // ③ 同 cell 原生常驻引用（0 = 没有）")
    lines.append("\t\tstd::uint32_t fallback2;")
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
            f'"{c_escape(r["nameEn"])}", "{c_escape(r["nameZh"])}" }},'
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
