#!/usr/bin/env python3
"""explore_boards.py - 找「任务板」入口候选（B1 探索用，一次性脚本）。

任务板 = ACTI `MissionBoardConsole*`（esm_probe list ACTI --grep board 找到的 14 条）。
本脚本一次遍历 Starfield.esm 里所有世界引用 + CELL，收集：
    REFR / 是否 persistent / CELL / WRLD / 位置(DATA) / 所属 CELL 的 EDID
输出按 base ACTI 分组，人工挑选「每个地点的代表任务板」。
"""
from __future__ import annotations

import struct
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from esm_probe import DEFAULT_ESM, iter_records_with_context, record_base_form, record_edid, subrecords  # noqa: E402

# esm_probe: list ACTI --grep board 的结果（跳过 TESTING / Inactive 的剧情道具）
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


def refr_position(payload: bytes):
    """REFR 的 DATA：Starfield 里为 24 字节（x,y,z float + 旋转 12 字节）。"""
    for sig, sp in subrecords(payload):
        if sig == b"DATA" and len(sp) >= 12:
            return struct.unpack_from("<fff", sp, 0)
    return None


def main() -> int:
    buf = Path(DEFAULT_ESM).read_bytes()
    want = set()
    from esm_probe import REF_SIGS
    want |= set(REF_SIGS)
    want.add(b"CELL")

    cells: dict[int, str] = {}
    rows: list[tuple] = []
    for sig, formid, flags, cell, world, payload in iter_records_with_context(buf, want):
        if sig == b"CELL":
            cells[formid] = record_edid(payload)
            continue
        base = record_base_form(payload)
        if base in BOARD_BASES:
            pos = refr_position(payload)
            rows.append((formid, base, flags, cell, world, pos))

    by_base = defaultdict(list)
    for formid, base, flags, cell, world, pos in rows:
        by_base[base].append((formid, flags, cell, world, pos))

    for base, name in sorted(BOARD_BASES.items(), key=lambda kv: kv[1]):
        items = by_base.get(base, [])
        print(f"\n=== {name} ({base:08X})：{len(items)} 个引用")
        for formid, flags, cell, world, pos in items:
            pers = "P" if flags & 0x400 else "-"
            cell_edid = cells.get(cell, "")
            p = f"({pos[0]:.0f},{pos[1]:.0f},{pos[2]:.0f})" if pos else ""
            print(f"  REFR {formid:08X} [{pers}] cell={cell:08X} {cell_edid:<40s} world={world:08X} {p}")

    print(f"\n共 {len(rows)} 个引用，涉及 {len(cells)} 个 CELL")
    return 0


if __name__ == "__main__":
    sys.exit(main())
