#!/usr/bin/env python3
r"""scan_landmark_book_refs.py - 扫描「地标书」（Landmark_*Book / OliverTwist）在世界里的放置引用。

背景（第 81 轮）：「地球地标」系列任务（Landmark_*）此前被过滤规则排除（docs/03 第 7 轮
的判断「走近即完成、无从接」）。复查发现：它们**可以接** —— 拾取/阅读对应书籍时，
书上的 `defaultrefoncontainerchangedto` 脚本把任务 SetStage(100)（数据见
`ref/xedit/landmark_books.txt`）。所以要显示它们的话，**引导目标 = 书的位置**。

本工具回答：每本书在世界里有没有放置引用（REFR）、在哪（cell/world）、是不是常驻。

输出：
    ref/landmark_book_refs.json    每条书引用（含 cell EDID / world / pos / flags）
    标准输出                       人类可读摘要（按书分组）

用法：
    python tools/esm/scan_landmark_book_refs.py
"""
from __future__ import annotations

import json
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from esm_probe import DEFAULT_ESM, REF_SIGS, record_base_form, record_edid  # noqa: E402
from scan_entry_persistent import GROUP_NAMES, refr_position, walk  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]

# 书 base 记录（Starfield.esm，local 号）-> (EDID, 对应任务)
BOOKS = {
    0x9A33: ("Landmark_LosAngelesBook_NOCLUTTER", "Landmark_LosAngeles"),
    0x9A37: ("Landmark_DubaiBook_NOCLUTTER", "Landmark_Dubai"),
    0x9A3D: ("Landmark_CairoBook_NOCLUTTER", "Landmark_Cairo"),
    0x18641E: ("EAW_CD_Book_OliverTwist_m", "Landmark_London"),
    0x26EA8: ("Landmark_HongKongBook_NOCLUTTER", "Landmark_HongKong"),
    0x26EAE: ("Landmark_OsakaBook_NOCLUTTER", "Landmark_Osaka"),
    0x26EAF: ("Landmark_ApolloBook_NOCLUTTER", "Landmark_Apollo"),
    0x28F10: ("Landmark_NewYorkBook_NOCLUTTER", "Landmark_NewYork"),
    0x28F11: ("Landmark_ShanghaiBook_NOCLUTTER", "Landmark_Shanghai"),
    0x28F12: ("Landmark_StLouisBook_NOCLUTTER", "Landmark_StLouis"),
}


def main() -> int:
    buf = Path(DEFAULT_ESM).read_bytes()
    print(f"读 {DEFAULT_ESM}（{len(buf)} B）…")

    cell_edid: dict[int, str] = {}
    world_edid: dict[int, str] = {}
    hits: dict[int, list] = {b: [] for b in BOOKS}

    def cb(sig, formid, flags, chain, cell, world, payload):
        if sig == b"CELL":
            cell_edid[formid] = record_edid(payload)
            return
        if sig == b"WRLD":
            world_edid[formid] = record_edid(payload)
            return
        if sig not in REF_SIGS:
            return
        base = record_base_form(payload)
        if base in BOOKS:
            key = f"0x{cell:08X}"
            hits[base].append({
                "sig": sig.decode("latin1"),
                "formid": formid,
                "flags": flags,
                "persistentFlag": bool(flags & 0x400),
                "persistentGroup": bool(chain and chain[-1][0] == 8),
                "cell": cell,
                "cellEdid": cell_edid.get(cell, ""),
                "world": world,
                "worldEdid": world_edid.get(world, ""),
                "pos": refr_position(payload),
                "edid": record_edid(payload),
                "chain": " > ".join(
                    (lab.decode("latin1", "replace") if g == 0 else GROUP_NAMES.get(g, f"?{g}"))
                    for g, lab in chain),
            })

    walk(buf, cb)

    out = {"books": []}
    for base, (edid, quest) in sorted(BOOKS.items(), key=lambda kv: kv[1][1]):
        rows = hits[base]
        out["books"].append({
            "base": f"0x{base:08X}", "baseEdid": edid, "quest": quest,
            "refs": rows,
        })
        print(f"\n=== {quest}  {edid} (0x{base:06X})  找到 {len(rows)} 条引用 ===")
        for r in rows:
            pos = r["pos"]
            pos_s = ("(%.1f, %.1f, %.1f)" % pos) if pos else "?"
            cell_s = r["cellEdid"] or f"0x{r['cell']:08X}"
            print(f"  {r['sig']} 0x{r['formid']:08X} P位={'Y' if r['persistentFlag'] else 'n'} "
                  f"常驻组={'Y' if r['persistentGroup'] else 'n'} cell={cell_s} "
                  f"world={r['worldEdid'] or ''} pos={pos_s}")
            print(f"      edid={r['edid']!r} 组链={r['chain']}")

    outp = ROOT / "ref" / "landmark_book_refs.json"
    outp.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\n已写出 {outp}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
