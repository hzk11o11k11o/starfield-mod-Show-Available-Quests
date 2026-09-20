#!/usr/bin/env python3
r"""scan_entry_persistent.py - 侦查「任务板入口」12 条 REFR 的组结构，并找同 cell 的常驻引用候选。

要回答的两个问题（第 29 轮，实机反馈「我就是亚特兰蒂斯城也不能导航」）：

1. 这 12 条 REFR 各自**在组结构的什么位置**（Persistent 组 / Temporary 组）？
   —— 决定 override 时要把记录写进哪个组（第 28 轮结论：11 条非常驻，
       cell 未加载时 `Game.GetForm` / `LookupByID` 取不到 ⇒ 蓝点不动）。
2. 每个任务板所在 cell 里**已经有哪些 persistent 引用**、离任务板多远？
   —— 如果附近就有常驻引用，可以不改 ESM，直接把引导目标换成它（备选方案）。

输出：
    ref/entry_persistent_scan.json    机器可读（供后续生成 override / 换目标用）
    标准输出                           人类可读摘要

复现（全表扫一遍 Starfield.esm，约 1~2 分钟）：
    python tools/esm/scan_entry_persistent.py
"""
from __future__ import annotations

import json
import struct
import sys
import zlib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from esm_probe import (  # noqa: E402
    DEFAULT_ESM, REF_SIGS, ascii_z, record_base_form, record_edid, subrecords,
)

ROOT = Path(__file__).resolve().parents[2]

# 组类型（BGS 三代通用，见 esm_probe.py 注释）
GROUP_NAMES = {
    0: "Top", 1: "WorldChildren", 2: "InteriorBlock", 3: "InteriorSubBlock",
    4: "ExteriorBlock", 5: "ExteriorSubBlock", 6: "CellChildren",
    7: "TopicChildren", 8: "CellPersistent", 9: "CellTemporary", 10: "CellVisibleDistant",
}


def refr_position(payload: bytes):
    for sig, sp in subrecords(payload):
        if sig == b"DATA" and len(sp) >= 12:
            return struct.unpack_from("<fff", sp, 0)
    return None


def walk(buf, cb):
    """带「组链」的全表遍历：cb(sig, formid, flags, chain, cell, world, payload)。

    GRUP 头（24 B）：0-3 'GRUP' | 4-7 size | 8-11 label | 12-15 type | 16-19 stamp …
    """
    head = struct.unpack_from("<I", buf, 4)[0]
    pos = 24 + head
    while pos + 24 <= len(buf):
        if buf[pos:pos + 4] != b"GRUP":
            break
        gsize = struct.unpack_from("<I", buf, pos + 4)[0]
        if gsize < 24:
            break
        label = bytes(buf[pos + 8:pos + 12])
        gtype = struct.unpack_from("<i", buf, pos + 12)[0]
        _rec(buf, pos + 24, pos + gsize, [(gtype, label)], 0, 0, cb)
        pos += gsize


def _rec(buf, p, end, chain, cell, world, cb):
    while p + 24 <= end:
        if buf[p:p + 4] == b"GRUP":
            sub = struct.unpack_from("<I", buf, p + 4)[0]
            if sub < 24:
                return
            label = bytes(buf[p + 8:p + 12])
            gtype = struct.unpack_from("<i", buf, p + 12)[0]
            _rec(buf, p + 24, p + sub, chain + [(gtype, label)], cell, world, cb)
            p += sub
            continue
        size = struct.unpack_from("<I", buf, p + 4)[0]
        flags = struct.unpack_from("<I", buf, p + 8)[0]
        formid = struct.unpack_from("<I", buf, p + 12)[0]
        sig = bytes(buf[p:p + 4])
        payload = None
        if flags & 0x00040000:
            if size >= 4:
                try:
                    payload = zlib.decompress(buf[p + 28:p + 24 + size])
                except zlib.error:
                    payload = None
        else:
            payload = buf[p + 24:p + 24 + size]
        p += 24 + size
        if payload is None:
            continue
        ncell, nworld = cell, world
        if sig == b"CELL":
            ncell = formid
        elif sig == b"WRLD":
            nworld = formid
        cb(sig, formid, flags, chain, cell, world, payload)
        cell, world = ncell, nworld


def chain_str(chain) -> str:
    parts = []
    for gtype, label in chain:
        name = GROUP_NAMES.get(gtype, f"?{gtype}")
        if gtype == 0:
            parts.append(label.decode("latin1", "replace"))
        else:
            parts.append(name)
    return " > ".join(parts)


def dist(a, b):
    return sum((x - y) ** 2 for x, y in zip(a, b)) ** 0.5


def main() -> int:
    entries = json.loads((ROOT / "ref" / "entry_targets.json").read_text(encoding="utf-8"))
    want_refs = {e["refLocal"] for e in entries}
    want_cell_edids = {e["cell"] for e in entries}
    name_of = {e["refLocal"]: e["nameZh"] for e in entries}

    buf = Path(DEFAULT_ESM).read_bytes()
    print(f"读 {DEFAULT_ESM}（{len(buf)} B）…")

    info: dict[int, dict] = {}          # 目标 REFR -> 侦查结果
    cell_info: dict[int, dict] = {}     # cell formid -> {edid, flags, world}
    cell_of_edid: dict[str, int] = {}
    target_cells: set[int] = set()
    cand: dict[int, list] = {}          # cell formid -> [persistent 引用候选]

    def cb(sig, formid, flags, chain, cell, world, payload):
        if sig == b"CELL":
            edid = record_edid(payload)
            cell_info[formid] = {"edid": edid, "flags": flags, "world": world}
            if edid in want_cell_edids:
                target_cells.add(formid)
                cell_of_edid[edid] = formid
            return
        if formid in want_refs:
            info[formid] = {
                "flags": flags,
                "chain": chain_str(chain),
                "chain_types": [g for g, _ in chain],
                "cell": cell,
                "world": world,
                "pos": refr_position(payload),
                "base": record_base_form(payload),
                "edid": record_edid(payload),
            }
            return
        if sig in REF_SIGS and cell in target_cells and chain and chain[-1][0] == 8:
            cand.setdefault(cell, []).append({
                "sig": sig.decode("latin1"),
                "formid": formid,
                "base": record_base_form(payload),
                "edid": record_edid(payload),
                "pos": refr_position(payload),
            })

    walk(buf, cb)

    out = {"entries": [], "cells": {}}
    print("\n=== 1. 12 条入口 REFR 的组结构 ===")
    for e in entries:
        fid = e["refLocal"]
        i = info.get(fid)
        if i is None:
            print(f"!! {e['nameZh']} ({fid:08X}) 没扫到")
            continue
        pers_flag = bool(i["flags"] & 0x400)
        in_pers_group = bool(i["chain_types"] and i["chain_types"][-1] == 8)
        cell_e = cell_info.get(i["cell"], {})
        row = {
            "nameZh": e["nameZh"], "refHex": f"0x{fid:08X}", "flags": i["flags"],
            "persistentFlag": pers_flag, "persistentGroup": in_pers_group,
            "chain": i["chain"], "cell": cell_e.get("edid", ""), "world": i["world"],
            "pos": i["pos"], "base": f"0x{i['base']:08X}",
        }
        out["entries"].append(row)
        print(f"{e['nameZh']:<22s} {fid:08X} flags=0x{i['flags']:06X} "
              f"P位={'Y' if pers_flag else 'n'} 常驻组={'Y' if in_pers_group else 'n'}")
        print(f"    组链: {i['chain']}")
        print(f"    cell: {cell_e.get('edid','?')} (0x{i['cell']:08X}) "
              f"world=0x{i['world']:08X} pos={i['pos']}")

    # 距离：入口 REFR 与同 cell 常驻候选
    print("\n=== 2. 每个任务板 cell 里的常驻引用（离任务板最近的 5 条） ===")
    for e in entries:
        fid = e["refLocal"]
        i = info.get(fid)
        if i is None or not i["pos"]:
            continue
        cell = i["cell"]
        cell_e = cell_info.get(cell, {})
        lst = cand.get(cell, [])
        scored = []
        for c in lst:
            if c["formid"] == fid or not c["pos"]:
                continue
            scored.append((dist(i["pos"], c["pos"]), c))
        scored.sort(key=lambda t: t[0])
        top = [{"dist": round(d, 2), **c} for d, c in scored[:5]]
        out["cells"][f"0x{cell:08X}"] = {
            "edid": cell_e.get("edid", ""), "persistentRefs": len(lst),
            "board": f"0x{fid:08X}", "nearest": top,
        }
        print(f"\n{e['nameZh']}  常驻引用共 {len(lst)} 条")
        for t in top:
            print(f"    {t['dist']:8.2f} m  {t['sig']} 0x{t['formid']:08X} "
                  f"base=0x{t['base']:08X} edid={t['edid']!r}")

    outp = ROOT / "ref" / "entry_persistent_scan.json"
    outp.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\n已写出 {outp}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
