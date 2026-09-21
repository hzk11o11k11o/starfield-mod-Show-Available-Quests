#!/usr/bin/env python3
r"""scan_landmark_fallbacks.py - 「地标书」的深挖侦查（第 81 轮）。

两件事：
1. 每本「地标书」**所在 cell 里的常驻引用**（离书最近的 N 条）—— 书本身是
   非常驻引用（CellTemporary），远处 `LookupByID` 取不到 ⇒ 需要「同 cell 常驻兜底」
   （与第 45/47 轮引导候选同一套机制）。
2. **容器里的书**（CONT 的 CNTO 物品列表）—— 找 Cairo 那种「没有世界引用」的书
   （疑在商店货架/容器里）。
   ★ 顺带把定位到的容器引用也扫出来（如果容器本身有放置引用）。

输入：ref/landmark_book_refs.json（scan_landmark_book_refs.py 的产物）
输出：ref/landmark_book_fallbacks.json + 标准输出摘要

用法：
    python tools/esm/scan_landmark_fallbacks.py
"""
from __future__ import annotations

import json
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from esm_probe import DEFAULT_ESM, REF_SIGS, record_base_form, record_edid, subrecords  # noqa: E402
from scan_entry_persistent import GROUP_NAMES, refr_position, walk  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]

BOOK_LOCALS = [0x9A33, 0x9A37, 0x9A3D, 0x18641E, 0x26EA8, 0x26EAE, 0x26EAF,
               0x28F10, 0x28F11, 0x28F12]
MAX_NEAR = 8


def dist(a, b):
    return sum((x - y) ** 2 for x, y in zip(a, b)) ** 0.5


def main() -> int:
    books = json.loads((ROOT / "ref" / "landmark_book_refs.json").read_text(encoding="utf-8"))
    target_cells: dict[int, dict] = {}   # cell formid -> {edid, book rows}
    for b in books["books"]:
        for r in b["refs"]:
            cell = r["cell"]
            target_cells.setdefault(cell, {"edid": r["cellEdid"], "books": []})
            target_cells[cell]["books"].append({"quest": b["quest"], "pos": r["pos"],
                                                "ref": r["formid"]})

    buf = Path(DEFAULT_ESM).read_bytes()
    print(f"读 {DEFAULT_ESM} … 目标 cell {len(target_cells)} 个")

    persistent: dict[int, list] = {}
    cell_edid: dict[int, str] = {}
    cont_books: dict[int, list] = {}      # cont formid -> [book local]
    cont_edid: dict[int, str] = {}
    cont_refs: dict[int, list] = {}       # cont formid -> [refr rows]

    def cb(sig, formid, flags, chain, cell, world, payload):
        if sig == b"CELL":
            cell_edid[formid] = record_edid(payload)
            return
        if sig == b"CONT":
            items = []
            for s, sp in subrecords(payload):
                if s == b"CNTO" and len(sp) >= 8:
                    items.append(struct.unpack_from("<II", sp, 0)[0] & 0xFFFFFF)
            hit = [i for i in items if i in BOOK_LOCALS]
            if hit:
                cont_books[formid] = hit
                cont_edid[formid] = record_edid(payload)
            return
        if sig not in REF_SIGS:
            return
        base = record_base_form(payload)
        if base in cont_books:
            cont_refs.setdefault(base, []).append({
                "sig": sig.decode("latin1"), "formid": formid, "flags": flags,
                "cell": cell, "cellEdid": cell_edid.get(cell, ""), "world": world,
                "pos": refr_position(payload), "edid": record_edid(payload),
                "persistent": bool(chain and chain[-1][0] == 8),
            })
        if cell in target_cells and chain and chain[-1][0] == 8:
            persistent.setdefault(cell, []).append({
                "sig": sig.decode("latin1"), "formid": formid, "flags": flags,
                "base": base, "edid": record_edid(payload), "pos": refr_position(payload),
            })

    walk(buf, cb)

    out = {"cells": {}, "containers": {}}
    print("\n=== 1. 每本书所在 cell 的常驻引用（最近 8 条） ===")
    for cell, info in target_cells.items():
        lst = persistent.get(cell, [])
        rows = []
        for bk in info["books"]:
            ps = bk["pos"]
            scored = []
            if ps:
                for c in lst:
                    if not c["pos"]:
                        continue
                    scored.append((dist(ps, c["pos"]), c))
                scored.sort(key=lambda t: t[0])
            rows.append({"quest": bk["quest"], "bookRef": bk["ref"],
                         "nearest": [{"dist": round(d, 2), **c} for d, c in scored[:MAX_NEAR]]})
        out["cells"][f"0x{cell:08X}"] = {"edid": info["edid"], "persistentCount": len(lst),
                                         "books": rows}
        print(f"\ncell {info['edid']} (0x{cell:08X}) 常驻引用 {len(lst)} 条")
        for r in rows:
            print(f"  {r['quest']}: 最近 {len(r['nearest'])} 候选")
            for n in r["nearest"][:5]:
                print(f"      {n['dist']:8.2f} m {n['sig']} 0x{n['formid']:08X} "
                      f"base=0x{n['base']:08X} edid={n['edid']!r}")

    print("\n=== 2. 容器里的书（CONT 的 CNTO） ===")
    for cont, bl in cont_books.items():
        refs = cont_refs.get(cont, [])
        edid = cont_edid.get(cont, "")
        out["containers"][f"0x{cont:08X}"] = {
            "edid": edid, "books": [f"0x{b:06X}" for b in bl],
            "refs": refs,
        }
        print(f"CONT 0x{cont:08X} {edid} 含书 {[hex(b) for b in bl]} 放置引用 {len(refs)} 条")
        for r in refs:
            pos = r["pos"]
            pos_s = ("(%.1f, %.1f, %.1f)" % pos) if pos else "?"
            print(f"    {r['sig']} 0x{r['formid']:08X} cell={r['cellEdid']} "
                  f"常驻={'Y' if r['persistent'] else 'n'} edid={r['edid']!r} pos={pos_s}")

    outp = ROOT / "ref" / "landmark_book_fallbacks.json"
    outp.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\n已写出 {outp}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
