#!/usr/bin/env python3
"""analyze_dnam.py - 分析 QUST 记录 DNAM 的字节布局，找「自动开始」之类的标志位。

背景：需求里「进度没到不显示」需要一个**每任务的静态信号**。
最合适的是 QUST DNAM 里的 flags（引擎里对应 RE::QUEST_DATA::flags，见
commonlibsf RE/T/TESQuest.h：float questDelayTime@0, uint16 flags@4,
int8 priority@6, uint8 questType@7）。

用法：
    python tools/esm/analyze_dnam.py            # 全表 2077 条
    python tools/esm/analyze_dnam.py --kept     # 只统计当前保留的 202 条（ref/quest_table_debug.json）

输出：
  * 每个字节位的取值分布
  * 每位与「任务类型 / 有无条件(CTDA) / 是否有目标」的交叉统计
  * 几个已知任务的原始 DNAM（人工比对用）
"""
from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path


def hexbytes(s: str) -> bytes | None:
    s = (s or "").strip()
    if len(s) < 8 or len(s) % 2:
        return None
    try:
        return bytes.fromhex(s)
    except ValueError:
        return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--quests", default="ref/quests.json")
    ap.add_argument("--kept", default="ref/quest_table_debug.json")
    ap.add_argument("--only-kept", action="store_true")
    a = ap.parse_args()

    quests = json.loads(Path(a.quests).read_text(encoding="utf-8"))
    kept_ids = None
    if a.only_kept:
        kept = json.loads(Path(a.kept).read_text(encoding="utf-8"))
        kept_ids = {int(r["formid"]) for r in kept}
        quests = [q for q in quests if q["formid"] in kept_ids]
        print(f"只统计保留表中的 {len(quests)} 条")
    else:
        kept = json.loads(Path(a.kept).read_text(encoding="utf-8"))
        kept_ids = {int(r["formid"]) for r in kept}

    rows = []
    bytelen = Counter()
    for q in quests:
        b = hexbytes(q.get("dnam"))
        if b is None:
            bytelen["无/异常"] += 1
            continue
        bytelen[len(b)] += 1
        rows.append((q, b))
    print(f"有 DNAM 的：{len(rows)} / {len(quests)}；长度分布：{dict(bytelen)}")
    if not rows:
        return 0

    n = max(len(b) for _, b in rows)
    print("\n== 每字节取值分布（前 8 字节）==")
    for i in range(min(n, 8)):
        c = Counter(b[i] for _, b in rows)
        top = ", ".join(f"{v:02X}×{k}" for v, k in c.most_common(8))
        print(f"  byte[{i}]: {top}")

    print("\n== 第 4..5 字节当 uint16 flags 看：高频值 ==")
    flagc = Counter(int.from_bytes(b[4:6], "little") if len(b) >= 6 else -1 for _, b in rows)
    for v, k in flagc.most_common(12):
        print(f"  0x{v:04X} × {k}")

    print("\n== flags 值与「任务类型 / 有 CTDA / 有目标 / 在保留表中」的交叉 ==")
    cross: dict[int, dict[str, Counter]] = defaultdict(lambda: defaultdict(Counter))

    def bump(flag: int, key: str, val: str) -> None:
        cross[flag][key][val] += 1

    for q, b in rows:
        if len(b) < 6:
            continue
        flag = int.from_bytes(b[4:6], "little")
        fid = int(q["formid"])
        bump(flag, "类型", str(q.get("qtyp")))
        bump(flag, "有CTDA", "是" if q.get("ctda") else "否")
        bump(flag, "有目标", "是" if q.get("objectives") else "否")
        bump(flag, "有阶段", "是" if q.get("stages") else "否")
        bump(flag, "在保留表", "是" if fid in kept_ids else "否")
        bump(flag, "DNAM[8:]零", "是" if all(x == 0 for x in b[8:]) else "否")

    for flag, _k in flagc.most_common(10):
        d = cross[flag]
        parts = []
        for key in ("在保留表", "有CTDA", "有目标", "有阶段"):
            c = d[key]
            tot = sum(c.values())
            parts.append(f"{key}: " + "/".join(f"{v}={c[v] * 100 // max(tot, 1)}%" for v in sorted(c)))
        print(f"  0x{flag:04X} (n={flagc[flag]}): " + " | ".join(parts))

    print("\n== 已知任务样本（人工比对）==")
    want = ["MQ101", "MQ102", "FFNeonZ09", "COM_Companion_SarahMorgan", "MB_Bounty01Far", "City_Neon_Chem03Misc"]
    allq = {q["edid"]: q for q in json.loads(Path(a.quests).read_text(encoding="utf-8")) if q.get("edid")}
    for edid in want:
        q = allq.get(edid)
        if q:
            b = hexbytes(q.get("dnam"))
            print(f"  {edid:32s} dnam={q.get('dnam')}  flags(4..5)="
                  f"{int.from_bytes(b[4:6], 'little'):#06x} ctda={len(q.get('ctda') or [])} "
                  f"objectives={len(q.get('objectives') or [])} 保留表={'是' if int(q['formid']) in kept_ids else '否'}")

    print("\n== 前 8 字节相同组合的高频前缀（看有没有「模板值」）==")
    pref = Counter(b[:8].hex() for _, b in rows)
    for v, k in pref.most_common(10):
        print(f"  {v.upper()} × {k}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
