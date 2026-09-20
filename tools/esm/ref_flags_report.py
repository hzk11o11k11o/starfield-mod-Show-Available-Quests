#!/usr/bin/env python3
"""ref_flags_report.py - 统计引导目标里「常驻引用（persistent）」的占比。

为什么关心：脚本用 `Game.GetForm(FormID)` 取目标引用 —— **非 persistent 引用在
所在 cell 未加载时取不到**（脚本会报状态 2「取不到引用」）。所以：
  * 引导目标尽量选 persistent 的（gen_guide_targets.py 的排序规则已优先常驻）；
  * 「无限任务入口」（任务板）里非持久的那些，引导能不能生效**只能靠实测**
    （见 docs/99 第 27 轮）。

数据源：ref/guide_targets.json（生成时已带 persistent 字段）+ ref/entry_targets.json。
本脚本不扫 ESM（秒出）；引用的离线属性在生成那两个文件时已经解析过。

用法：
    python tools/esm/ref_flags_report.py                 # 全量统计
    python tools/esm/ref_flags_report.py --ids 001B6140 002AD366   # 查特定目标引用
"""
from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ids", nargs="*", default=[], help="按目标引用（refr）查这些 FormID（十六进制）")
    a = ap.parse_args()

    gt = Path("ref/guide_targets.json")
    data = json.loads(gt.read_text(encoding="utf-8"))

    by_ref: dict[int, dict] = {}
    stat = Counter()
    nonpersistent: list[tuple[int, str, str]] = []
    for qid, v in data.items():
        refr = int(v.get("refr") or 0)
        p = bool(v.get("persistent"))
        kind = v.get("kind") or "?"
        stat[(kind, p)] += 1
        if refr:
            by_ref[refr] = {"persistent": p, "kind": kind,
                            "where": v.get("whereZh") or v.get("nameZh") or "",
                            "quest": int(qid)}
        if not p:
            nonpersistent.append((int(qid), kind, v.get("whereZh") or v.get("nameZh") or ""))

    total = sum(stat.values())
    pers = sum(n for (k, p), n in stat.items() if p)
    print(f"引导目标（guide_targets.json）：共 {total} 条，常驻 {pers} / 非常驻 {total - pers}")
    for kind in ("actor", "ref", "marker", "?"):
        p = stat.get((kind, True), 0)
        np = stat.get((kind, False), 0)
        if p + np:
            print(f"  kind={kind:7s} 常驻 {p:3d} / 非常驻 {np:3d}")

    et = Path("ref/entry_targets.json")
    if et.exists():
        rows = json.loads(et.read_text(encoding="utf-8"))
        n_p = sum(1 for r in rows if r["persistent"])
        print(f"\n任务板入口（entry_targets.json）：共 {len(rows)} 条，常驻 {n_p} / 非常驻 {len(rows) - n_p}")
        for r in rows:
            mark = "P " if r["persistent"] else "--"
            print(f"  [{mark}] {r['refHex']} {r['nameZh']}  ({r['cell']})")
            by_ref[int(r["refLocal"])] = {"persistent": r["persistent"], "kind": "entry",
                                          "where": r["nameZh"], "quest": 0}

    if a.ids:
        print("\n指定 FormID（按目标引用查）：")
        for x in a.ids:
            fid = int(x, 16)
            v = by_ref.get(fid)
            if v is None:
                print(f"  {fid:08X} — 不在 guide/entry 表里")
            else:
                print(f"  {fid:08X} persistent={v['persistent']} kind={v['kind']} where={v['where']}")

    if nonpersistent:
        print(f"\n非常驻引用名单（前 20 / 共 {len(nonpersistent)}）：")
        for qid, kind, where in nonpersistent[:20]:
            print(f"  {qid:08X} {kind:7s} {where}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
