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
ENTRIES = [
    (0x0021001E, "CityNewAtlantisWell", "Mission Board - New Atlantis", "任务板 · 新亚特兰蒂斯"),
    (0x0014D497, "CityAkilaCityTheRock", "Mission Board - Akila City", "任务板 · 阿基拉城"),
    (0x00148C93, "CityNeonCore", "Mission Board - Neon", "任务板 · 霓虹城"),
    (0x001DF853, "CityCydoniaMainLevel", "Mission Board - Cydonia", "任务板 · 塞多尼亚"),
    (0x001DED95, "SettleHopeTownPitStop", "Mission Board - Hopetown", "任务板 · 霍普镇"),
    (0x001DF5BD, "SettleNewHomestead01", "Mission Board - New Homestead", "任务板 · 新家园"),
    (0x00137573, "CityNewAtlantisLodgeInt", "Mission Board - The Lodge", "任务板 · 星座小屋"),
    (0x0013F738, "LC044RyujinIndustriesHQ", "Mission Board - Ryujin Industries", "任务板 · 龙神工业"),
    (0x000C2D64, "ssSettleDeimosStaryard", "Mission Board - Deimos Staryard", "任务板 · 狄摩斯星船厂"),
    (0x0016265F, "ssSettleTridentStaryard", "Mission Board - Trident Staryard", "任务板 · 三叉戟星船厂"),
    (0x00167872, "ssSettleStroudEklundStaryard", "Mission Board - Stroud-Eklund Staryard", "任务板 · 斯特劳德-埃克伦德星船厂"),
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
        rows.append({
            "refLocal": refr,
            "refHex": f"0x{refr:08X}",
            "master": 0,                      # Starfield.esm（kQuestMasters[0]）
            "persistent": bool(flags & 0x400),
            "base": BOARD_BASES[base],
            "cell": actual_cell,
            "nameEn": en,
            "nameZh": zh,
        })

    if problems:
        print("!! 白名单校验失败：")
        for p in problems:
            print("   -", p)
        return 1

    n_pers = sum(1 for r in rows if r["persistent"])
    print(f"入口条目：{len(rows)} 条（常驻引用 {n_pers} / 非常驻 {len(rows) - n_pers}）")
    for r in rows:
        flag = "P" if r["persistent"] else "-"
        print(f"  [{flag}] {r['refHex']} {r['cell']:<32s} {r['nameZh']}")

    # ---- 头文件 ----
    lines = []
    lines.append("#pragma once")
    lines.append("// 本文件由 tools/esm/gen_entry_table.py 自动生成，请勿手改。")
    lines.append("//")
    lines.append("// 「无限任务入口」条目（任务板）：AGENTS.md 需求 —— 无限生成任务本身不显示，")
    lines.append("// 但「接取入口」（任务板）作为一条数据显示在列表里，点了就引导到它的位置。")
    lines.append("//")
    lines.append("// 字段说明：")
    lines.append("//   refLocal   任务板 ACTIVATOR（MissionBoardConsole*）在世界里的放置引用（REFR）记录号。")
    lines.append("//              ★ 它同时是界面条目的 uID（运行期 FormID）：与任务的 FormID 空间不冲突，")
    lines.append("//                且「引导目标 = 它自己」（DLL 收到该 uID 的引导请求时直接写这个引用）。")
    lines.append("//   master     所属 master 下标（kQuestMasters[]；目前全部在 Starfield.esm）。")
    lines.append("//   persistent REFR 是否常驻引用 —— **引导能不能生效的关键**：")
    lines.append("//              非常驻引用在所在 cell 未加载时脚本 Game.GetForm 取不到（状态 2）。")
    lines.append("//              实机验证哪块板能引导就看这一列（见 docs/99 第 27 轮）。")
    lines.append("//   nameZh/En  列表里显示的名字（中英都推，AS3 按游戏语言挑）。")
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
    lines.append("\t\tconst char*   nameEn;")
    lines.append("\t\tconst char*   nameZh;")
    lines.append("\t};")
    lines.append("")
    lines.append("\tinline constexpr StaticEntryInfo kEntryTable[] = {")
    for r in rows:
        p = "true " if r["persistent"] else "false"
        lines.append(
            f'\t\t{{ {r["refLocal"]:#010x}u, {r["master"]}u, {p}, '
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
