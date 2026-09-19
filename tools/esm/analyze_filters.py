#!/usr/bin/env python3
"""analyze_filters.py - 分析静态表里的「垃圾条目」，为过滤规则找信号。

背景：485 条静态表里混着大量内部任务（"研究指示器"、"Kill the target on the
location"、"Landmark Quest" 等）。本脚本把 quests.json 的原始字段与显示名交叉
统计，找出「能把这些条目分出来的结构化信号」。

用法：
    python tools/esm/analyze_filters.py
"""
from __future__ import annotations

import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

QTYPE = {
    0x000475F8: "Activities",
    0x000475FA: "MainQuest",
    0x000475FD: "Factions",
    0x00047600: "SideQuest",
    0x001E2D30: "Mission",
}

ALIAS_RE = re.compile(r"<Alias=([^>]+)>")

# 可疑模式（名字/EDID）
NAME_PATTERNS = {
    "pointer": re.compile(r"pointer|指示器", re.I),
    "landmark": re.compile(r"landmark|地标", re.I),
    "alias_placeholder": ALIAS_RE,
    "be_prefix": re.compile(r"^\[BE\s*-|^\[BE]", re.I),
    "oe_prefix": re.compile(r"^OE_", re.I),
    "tutorial": re.compile(r"tutorial|教程", re.I),
    "debug": re.compile(r"debug|测试", re.I),
    "handler": re.compile(r"handler|处理程序", re.I),
    "template": re.compile(r"template|模板", re.I),
    "companion": re.compile(r"^Companion\b|同伴", re.I),
    "misc_dot": re.compile(r"^Misc\.", re.I),
}


def load_rows():
    table = json.loads((ROOT / "ref" / "quest_table_debug.json").read_text(encoding="utf-8"))
    quests = {q["formid"]: q for q in json.loads((ROOT / "ref" / "quests.json").read_text(encoding="utf-8"))}
    return table, quests


def main() -> int:
    table, quests = load_rows()
    print(f"静态表条目: {len(table)}")

    # ---- 1. EDID 前缀统计 ----
    prefix = Counter()
    for row in table:
        edid = row.get("edid") or ""
        head = edid.split("_")[0]
        prefix[head] += 1
    print("\n== EDID 首段统计（前 30）==")
    for k, v in prefix.most_common(30):
        print(f"  {k:24s} {v}")

    # ---- 2. 名字模式命中 ----
    print("\n== 名字/EDID 模式命中 ==")
    hits = defaultdict(list)
    for row in table:
        raw_name = row["name_en"] or ""
        for key, pat in NAME_PATTERNS.items():
            if pat.search(raw_name) or pat.search(row.get("edid") or ""):
                hits[key].append(row)
    for key in NAME_PATTERNS:
        rows = hits.get(key, [])
        print(f"  {key:18s} {len(rows)}")

    # ---- 3. 别名占位符（生成任务的强信号）----
    alias_rows = []
    for row in table:
        q = quests.get(row["formid"])
        if not q:
            continue
        # FULL 原始字符串在 quests.json 里只有 ID；用 xedit 的名字（row 里已替换过）
        # 这里改用 edid 与 QUEST 结构：产生任务一般 alias 多且 stage 少
        pass

    # ---- 4. 结构字段分布 ----
    print("\n== 结构字段分布（在静态表内）==")
    dist = defaultdict(Counter)
    for row in table:
        q = quests.get(row["formid"])
        if not q:
            continue
        aliases = q.get("aliases") or {}
        alias_n = aliases.get("ALID", 0) if isinstance(aliases, dict) else 0
        # 有些记录的计数可能直接是 int（xEdit 只导了计数）
        if not isinstance(alias_n, int):
            alias_n = len(alias_n)
        dist["ctda"][min(len(q.get("ctda", [])), 5)] += 1
        dist["aliases"][min(alias_n, 6)] += 1
        dist["stages"][min(len(q.get("stages", [])), 6)] += 1
        dist["objectives"][min(len(q.get("objectives", [])), 6)] += 1
        dist["rec_flags"][q.get("rec_flags", 0)] += 1
        dnam = q.get("dnam", "")
        # DNAM flags = 前 4 字节（小端）
        if len(dnam) >= 8:
            flags = int.from_bytes(bytes.fromhex(dnam[:8]), "little")
            dist["dnam_flags"][flags & 0xFF] += 1
        dist["vmad"][1 if q.get("vmad_size", 0) > 0 else 0] += 1
    for field, counter in dist.items():
        print(f"  {field}: {dict(counter.most_common(8))}")

    # ---- 5. 打印可疑条目样例（人工核对） ----
    print("\n== 可疑条目样例 ==")
    for key in ("pointer", "landmark", "be_prefix", "oe_prefix", "handler", "companion"):
        rows = hits.get(key, [])
        for row in rows[:6]:
            q = quests.get(row["formid"]) or {}
            aliases = q.get("aliases") or {}
            alias_n = aliases.get("ALID", 0) if isinstance(aliases, dict) else 0
            if not isinstance(alias_n, int):
                alias_n = len(alias_n)
            print(f"  [{key}] 0x{row['formid']:08X} {(row.get('edid') or '')[:40]:40s} "
                  f"zh={row['name_zh'][:28]:28s} ctda={len(q.get('ctda', []))} "
                  f"al={alias_n} st={len(q.get('stages', []))}")
        if len(rows) > 6:
            print(f"       ... 共 {len(rows)} 条")

    # ---- 6. 全量清单（人工审阅用）----
    out = ROOT / "ref" / "table_review.txt"
    lines = []
    for row in table:
        q = quests.get(row["formid"]) or {}
        lines.append(
            f"0x{row['formid']:08X}\t{row.get('edid','')}\t{row['name_zh']}\t{row['name_en']}\t"
            f"type={row['itype']}\tqtype={row.get('qtype','')}\tctda={len(q.get('ctda', []))}\t"
            f"vmad={q.get('vmad_size',0)}"
        )
    out.write_text("\n".join(lines), encoding="utf-8")
    print(f"\n全量清单 -> {out}（{len(lines)} 行）")

    return 0


if __name__ == "__main__":
    sys.exit(main())
