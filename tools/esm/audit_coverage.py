#!/usr/bin/env python3
"""audit_coverage.py - 覆盖面全量复盘（第 106 轮 · 大项 D）。

目的：把「全部官方任务」与「表内收录」的差集逐类铺开，找**可能漏收**的任务
（= 玩家能接、应该出现在「可接任务」列表里，但当前被过滤规则排除的）。

判据分层（逐层收窄，最后人工复查）：
  ① 全量 2568 条 vs 收录 271 条（307 = 主线 37 + 被规则排除 270 待分类）；
  ② 未收录里「**有正式本地化名**」的（名字非空）—— 「给玩家看的名字」是
     「玩家可能接到」的最直接信号：内部任务通常没有本地化名（FULL 为空）。
  ③ 按排除原因分组铺开（无 QTYP / QTYP 不在映射 / filter_reason 各条 / 主线）。

输出：
  ref/coverage_audit.json    （全部未收录清单：master/local/edid/名字/类型/原因）
  stdout 摘要（各类计数 + 「有名字」的明细，供人工复查）

用法：
    python tools/esm/audit_coverage.py               # 摘要
    python tools/esm/audit_coverage.py --named 200   # 多打「有名字」的明细
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
REF = ROOT / "ref"
sys.path.insert(0, str(Path(__file__).parent))

from strings_probe import load_strings      # noqa: E402
import gen_quest_table as gqt               # noqa: E402

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--named", type=int, default=60,
                    help="打印多少条「有名字」的明细（0 = 全打）")
    ap.add_argument("--out", default=str(REF / "coverage_audit.json"))
    a = ap.parse_args()

    table = json.loads((REF / "quest_table_debug.json").read_text(encoding="utf-8"))
    in_table = {((q.get("master") or "Starfield.esm").lower(), int(q["local"]) & 0xFFFFFF)
                for q in table}
    quests = json.loads((REF / "quests_all.json").read_text(encoding="utf-8"))

    base = REF / "strings" / "strings"
    strs: dict[str, tuple] = {}
    for m in sorted({(q.get("master") or "Starfield.esm") for q in quests}):
        k = Path(m).stem.lower()
        en, zh = base / f"{k}_en.strings", base / f"{k}_zhhans.strings"
        strs[m] = (load_strings(en), load_strings(zh)) if (en.exists() and zh.exists()) else ({}, {})

    stats = Counter()
    by_reason: dict[str, list] = {}
    named: list[dict] = []
    for q in quests:
        m = q.get("master") or "Starfield.esm"
        loc = int(q["local"]) & 0xFFFFFF
        if (m.lower(), loc) in in_table:
            stats["已收录"] += 1
            continue
        stats["未收录"] += 1
        en_t, zh_t = strs[m]
        full = q.get("full")
        raw_en = en_t.get(full, "") if full else ""
        raw_zh = zh_t.get(full, "") if full else ""
        name_en = gqt.clean_name(raw_en, False)
        name_zh = gqt.clean_name(raw_zh, True)
        edid = q.get("edid") or ""
        qtyp = q.get("qtyp")
        itype = gqt.QTYPE_TO_ITYPE.get(qtyp) if qtyp is not None else None

        if qtyp is None:
            reason = "无 QTYP（内部记录）"
        elif itype == 1:
            reason = "主线（有意不收）"
        elif itype is None:
            reason = "QTYP 不在映射"
        else:
            row = {"edid": edid,
                   "name_en": name_en or edid,
                   "name_zh": name_zh or name_en or edid}
            reason = gqt.filter_reason(row, raw_en, raw_zh) or "（未被 filter 排除？！）"

        rec = {"master": m, "local": loc, "edid": edid,
               "nameZh": name_zh, "nameEn": name_en,
               "qtyp": ("0x%08X" % qtyp) if qtyp else None,
               "itype": itype, "reason": reason}
        by_reason.setdefault(reason, []).append(rec)
        stats[f"未收录·{reason}"] += 1
        if name_zh or name_en:
            named.append(rec)

    print(f"全量 {len(quests)} 条：已收录 {stats['已收录']} / 未收录 {stats['未收录']}")
    print("\n--- 未收录按原因 ---")
    for reason, lst in sorted(by_reason.items(), key=lambda kv: -len(kv[1])):
        print(f"  {reason:<28} {len(lst):5d}")

    # 「有名字」= 玩家可见的最直接信号
    print(f"\n--- ★ 「有名字」的未收录任务：{len(named)} 条 ---")
    c_pref = Counter((r["edid"] or "").split("_")[0] for r in named)
    print("  按 EDID 前缀：" + " ".join(f"{k}={v}" for k, v in c_pref.most_common(18)))
    c_r = Counter(r["reason"] for r in named)
    print("  按原因：" + " ".join(f"{k}={v}" for k, v in c_r.most_common()))
    c_m = Counter(r["master"] for r in named)
    print("  按 master：" + " ".join(f"{k}={v}" for k, v in c_m.most_common()))
    show = named if a.named == 0 else named[:a.named]
    print(f"\n  明细（前 {len(show)} 条；- 号 = 无中文名）：")
    for r in show:
        nm = r["nameZh"] or ("-" + (r["nameEn"] or ""))
        print(f"    {r['master']:<18} 0x{r['local']:06X} {r['edid']:<38} "
              f"{nm:<26} itype={r['itype']} 原因={r['reason']}")

    Path(a.out).write_text(json.dumps({
        "total": len(quests),
        "inTable": stats["已收录"],
        "byReason": {k: len(v) for k, v in sorted(by_reason.items(), key=lambda kv: -len(kv[1]))},
        "namedCount": len(named),
        "named": named,
        "all": [r for lst in by_reason.values() for r in lst],
    }, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\nwrote {a.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
