#!/usr/bin/env python3
"""analyze_quests.py - 对 quest_dump.py 生成的 JSON 做深度分析，服务于"可接任务"规则设计。

用法：
    python tools/esm/analyze_quests.py ref/quests.json --list-sidequests
    python tools/esm/analyze_quests.py ref/quests.json --dump-record <formid-hex>
    python tools/esm/analyze_quests.py ref/quests.json --summary
"""
from __future__ import annotations

import argparse
import json
import struct
import sys
from collections import Counter
from pathlib import Path

QTYPE_NAMES = {
    0x000475F8: "Activities",
    0x001E2D30: "Mission",
    0x00047600: "SideQuest",
    0x000475FD: "Factions",
    0x000475FA: "MainQuest",
}

ESM = r"D:\SteamLibrary\steamapps\common\Starfield\Data\Starfield.esm"


def load(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def parse_ctda(hexstr: str):
    b = bytes.fromhex(hexstr)
    if len(b) < 32:
        return {"raw": hexstr, "len": len(b)}
    # 尝试 Skyrim 风格：u8 op + u8[3] + f32 cmp + u32 func + u32 p1 + u32 p2 + u32 runon + u32 ref + i32 p3
    op = b[0]
    cmp_val = struct.unpack_from("<f", b, 4)[0]
    func = struct.unpack_from("<I", b, 8)[0]
    p1 = struct.unpack_from("<I", b, 12)[0]
    p2 = struct.unpack_from("<I", b, 16)[0]
    runon = struct.unpack_from("<I", b, 20)[0]
    ref = struct.unpack_from("<I", b, 24)[0]
    p3 = struct.unpack_from("<i", b, 28)[0]
    out = {
        "len": len(b), "op": op, "cmp": round(cmp_val, 4), "func": func,
        "p1": f"0x{p1:08X}", "p2": f"0x{p2:08X}", "runOn": runon,
        "ref": f"0x{ref:08X}", "p3": p3,
    }
    if len(b) > 32:
        out["extra"] = b[32:].hex()
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("json")
    ap.add_argument("--summary", action="store_true")
    ap.add_argument("--list-sidequests", action="store_true")
    ap.add_argument("--by-edid", default=None, help="find quests whose EDID contains this")
    ap.add_argument("--dump-record", default=None, help="dump raw subrecords of a formid (hex)")
    a = ap.parse_args()

    quests = load(a.json)

    if a.dump_record:
        fid = int(a.dump_record, 16)
        buf = Path(ESM).read_bytes()
        sys.path.insert(0, str(Path(__file__).parent))
        from quest_dump import walk_quests, iter_subrecords
        for formid, flags, payload in walk_quests(buf):
            if formid == fid:
                print(f"=== QUST {formid:08X} ===")
                for ssig, sp in iter_subrecords(payload, 0, len(payload)):
                    txt = "".join(chr(c) if 32 <= c < 127 else "." for c in sp)
                    print(f"  {ssig.decode('latin1')} len={len(sp):<6} {sp[:40].hex(' ')}{' ...' if len(sp) > 40 else ''}")
                    if len(sp) <= 80:
                        print(f"      ascii: {txt}")
                break
        return 0

    if a.by_edid:
        needle = a.by_edid.lower()
        for q in quests:
            if q["edid"] and needle in q["edid"].lower():
                print(f"{q['formid']:08X} {q['edid']:<40} type={QTYPE_NAMES.get(q['qtyp'], '-'):<11} "
                      f"ctda={len(q['ctda'])} stages={len(q['stages'])} aliases={sum(q['aliases'].values())}")
        return 0

    if a.list_sidequests:
        for q in quests:
            if q["qtyp"] == 0x00047600:
                aliases = sum(q["aliases"].values())
                stages = len(q["stages"])
                print(f"{q['formid']:08X} {q['edid']:<36} ctda={len(q['ctda']):<3} stages={stages:<3} "
                      f"alias={aliases:<3} vmad={'Y' if q['vmad_size'] else 'n'} "
                      f"qobj={q['subs'].get('QOBJ', 0)} qsta={q['subs'].get('QSTA', 0)}")
        return 0

    if a.summary:
        print(f"total={len(quests)}")
        print("\n--- 按类型统计（QTYP）---")
        for k, v in Counter(q["qtyp"] for q in quests).most_common():
            print(f"  {QTYPE_NAMES.get(k, 'None' if k is None else hex(k))}: {v}")

        print("\n--- 有 QTYP 的任务里 CTDA 分布 ---")
        typed = [q for q in quests if q["qtyp"] is not None]
        print(f"  typed={len(typed)}, with_ctda={sum(1 for q in typed if q['ctda'])}, "
              f"with_vmad={sum(1 for q in typed if q['vmad_size'])}, "
              f"with_alias={sum(1 for q in typed if q['aliases'])}")

        print("\n--- CTDA 长度分布 ---")
        lens = Counter()
        for q in quests:
            for c in q["ctda"]:
                lens[len(c) // 2] += 1
        print(f"  {lens.most_common(20)}")

        print("\n--- 各类型任务示例 ---")
        seen = {}
        for q in quests:
            t = q["qtyp"]
            if t and t not in seen:
                seen[t] = q
        for t, q in seen.items():
            print(f"  {QTYPE_NAMES.get(t, hex(t))}: {q['edid']} ({q['formid']:08X}) "
                  f"stages={len(q['stages'])} ctda={len(q['ctda'])}")

        print("\n--- 未分类（无 QTYP）任务示例 ---")
        n = 0
        for q in quests:
            if q["qtyp"] is None:
                print(f"  {q['formid']:08X} {q['edid']}")
                n += 1
                if n >= 40:
                    break
        return 0

    ap.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
