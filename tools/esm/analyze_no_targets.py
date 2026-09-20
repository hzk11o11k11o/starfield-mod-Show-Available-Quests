#!/usr/bin/env python3
"""analyze_no_targets.py - 分析「没有引导目标」的任务**为什么**没有目标。

需求背景（玩家）：先把原因分析清楚，再决定要不要补导航，**不要为了导航而硬凑**
（以免指向错误地点、误解游戏本来的接取方式）。

gen_guide_targets.py 的引导目标只有三类来源：
  ① ALUA（Unique Actor，任务发布者 NPC）→ 该 NPC 的放置引用（ACHR，且不在暂存格）
  ② ALFR（Forced Reference，任务落脚引用）→ 引用本身（不在暂存格）
  ③ LCTN/ALFL（任务地点）→ 地点的地图标记（MNAM）

两步分析：
  第一步（快，只扫 QUST）：这些任务的记录里到底有没有 ALUA/ALFR/ALFL；
  第二步（--world，约 3-6 分钟）：有候选类别名的，逐个查世界数据 ——
    NPC 有没有放置引用？是不是落在暂存格？地点有没有地图标记？

用法：
    python tools/esm/analyze_no_targets.py               # 第一步（秒级）
    python tools/esm/analyze_no_targets.py --world       # 两步都做
"""
from __future__ import annotations

import argparse
import json
import mmap
import re
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from esm_probe import iter_records_with_context, subrecords, ascii_z  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
DATA = Path(r"D:\SteamLibrary\steamapps\common\Starfield\Data")

ALIAS_SUBS = (b"ALUA", b"ALFR", b"ALFL", b"ALCS", b"ALCO", b"ALFA", b"ALRT",
              b"ALPC", b"ALPS", b"ALSP", b"ALFC", b"ALEQ", b"ALNA", b"ALCM",
              b"ALCC", b"ALUB", b"ALKF", b"ALSY", b"ALFI", b"ALFE")


def load_table() -> list[dict]:
    """从 SAQ_QuestTable.h 抄回「master + 记录号 + 有无目标 + 名字」（表是 C++ 头，用正则抠）。

    ★ 匹配 ESM 里的记录要用**文件内原始 FormID**（DLC 记录的高字节是它引用的 master 前缀，
    不等于记录号）—— 那个值在 ref/quest_table_debug.json 里（.h 只存运行期用的记录号）。
    """
    text = (ROOT / "plugin/src/SAQ_QuestTable.h").read_text(encoding="utf-8")
    row_re = re.compile(
        r'\{\s*(0x[0-9A-Fa-f]+)u,\s*(\d+)u,\s*(\d+)u,\s*0x[0-9A-Fa-f]+u,\s*(0x[0-9A-Fa-f]+)u,'
        r'\s*\d+u,\s*"([^"]*)",\s*"([^"]*)",\s*"([^"]*)",\s*"([^"]*)"\s*\}')
    masters = re.findall(r'^\s*"([^"]+\.esm)",', text, re.M)
    dbg = {(d["master"], int(d["local"])): int(d["formid"])
           for d in json.loads((ROOT / "ref/quest_table_debug.json").read_text(encoding="utf-8"))}
    rows = []
    for m in row_re.finditer(text):
        master = masters[int(m.group(2))]
        local = int(m.group(1), 16)
        rows.append({
            "local": local,
            "formid": dbg.get((master, local), local),
            "master": master,
            "itype": int(m.group(3)),
            "has_target": int(m.group(4), 16) != 0,
            "name_en": m.group(7),
            "name_zh": m.group(8),
        })
    return rows


def scan_quest_alias_detail(master: str, want: set[int]) -> dict[int, dict]:
    """扫一个 master 的 QUST：{formid: {aliases:[(name,[subsig,...])], lnam}}。"""
    out: dict[int, dict] = {}
    with (DATA / master).open("rb") as f:
        mm = mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ)
        try:
            for sig, formid, _flags, _cell, _world, payload in iter_records_with_context(mm):
                if sig != b"QUST" or formid not in want:
                    continue
                info: dict = {"aliases": [], "lnam": 0}
                alias_name, subs = "", []
                for s, sp in subrecords(payload):
                    if s == b"ALST":
                        if alias_name or subs:
                            info["aliases"].append((alias_name, subs))
                        alias_name, subs = "", []
                    elif s == b"ALID":
                        alias_name = ascii_z(sp)
                    elif s == b"LNAM" and len(sp) >= 4:
                        info["lnam"] = int.from_bytes(sp[:4], "little")
                    elif s in ALIAS_SUBS:
                        subs.append(s.decode("latin1"))
                if alias_name or subs:
                    info["aliases"].append((alias_name, subs))
                out[formid] = info
        finally:
            mm.close()
    return out


def classify(info: dict | None) -> str:
    if info is None:
        return "找不到记录"
    actors = any("ALUA" in subs for _n, subs in info["aliases"])
    refs = any("ALFR" in subs for _n, subs in info["aliases"])
    locs = any("ALFL" in subs for _n, subs in info["aliases"])
    if actors or refs or locs or info["lnam"]:
        return "有候选类别名但没算出"
    return "无发布者/无落脚点"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--world", action="store_true",
                    help="第二步：扫世界数据，查每条的具体失败原因（约 3-6 分钟）")
    a = ap.parse_args()

    rows = load_table()
    missing = [r for r in rows if not r["has_target"]]
    print(f"表内 {len(rows)} 条，无引导目标 {len(missing)} 条\n")

    by_master: dict[str, set[int]] = {}
    for r in missing:
        by_master.setdefault(r["master"], set()).add(r["formid"])

    detail: dict[tuple[str, int], dict] = {}
    for m, want in by_master.items():
        got = scan_quest_alias_detail(m, want)
        print(f"  {m}: 扫到 {len(got)}/{len(want)} 条 QUST")
        for formid, info in got.items():
            detail[(m, formid)] = info

    stats = Counter()
    out_rows = []
    for r in missing:
        info = detail.get((r["master"], r["formid"]))
        tag = classify(info)
        stats[tag] += 1
        aliases = info["aliases"] if info else []
        out_rows.append({
            "master": r["master"], "local": r["local"], "formid": r["formid"],
            "itype": r["itype"], "name": r["name_zh"] or r["name_en"], "tag": tag,
            "alias_count": len(aliases),
            "sub_sigs": sorted({s for _n, subs in aliases for s in subs}),
            "reasons": "",
        })

    print("\n=== 第一步分类统计（QUST 层面）===")
    for k, v in stats.most_common():
        print(f"  {k}: {v}")

    # ------------------------------------------------------------------
    # 第二步：世界数据诊断（复用 gen_guide_targets.py 的扫描器）
    # ------------------------------------------------------------------
    if a.world:
        import gen_guide_targets as ggt
        print("\n=== 第二步：世界数据诊断 ===")
        metas = {m: ggt.load_meta(DATA / m) for m in by_master}
        aliases: dict[int, dict] = {}
        acc: dict = {"cells": {}, "world_names": {}, "npc_names": {}, "placements": {},
                     "refr_info": {}, "lctns": {}}
        quest_lctn: dict[int, int] = {}
        for m, want in by_master.items():
            with (DATA / m).open("rb") as f:
                mm = mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ)
                try:
                    al, lc = ggt.scan_quests(mm, metas[m], want)
                finally:
                    mm.close()
            aliases.update(al)
            acc["lctns"].update(lc)
            for fid, info in al.items():
                if info["lctn"]:
                    quest_lctn[fid] = info["lctn"]
        wanted_npc = {npc for info in aliases.values() for _al, npc in info["actors"]
                      if npc not in (0, 0x07, 0x14)}
        wanted_refr = {refr for info in aliases.values() for _al, refr in info["refs"]}
        wanted_refr |= {i["marker"] for i in acc["lctns"].values() if i["marker"]}
        print(f"  需要定位的 NPC {len(wanted_npc)}；引用 {len(wanted_refr)}；开始扫世界数据…")
        for m in by_master:
            with (DATA / m).open("rb") as f:
                mm = mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ)
                try:
                    ggt.scan_world(mm, metas[m], wanted_npc, wanted_refr, acc)
                finally:
                    mm.close()
        print(f"  放置引用 {len(acc['placements'])} 个 NPC；引用信息 {len(acc['refr_info'])} 条")

        def bad_cell(cell_id: int) -> bool:
            return bool(ggt.BAD_CELL_RE.search(acc["cells"].get(cell_id, {}).get("edid", "")))

        reason_stats = Counter()
        for r in out_rows:
            if r["tag"] != "有候选类别名但没算出":
                continue
            info = aliases.get(r["formid"], {"actors": [], "refs": [], "locs": [], "lctn": 0})
            reasons: list[str] = []
            for alias, npc in info.get("actors", []):
                if npc in (0, 0x07, 0x14):
                    reasons.append(f"ALUA[{alias}]=Player")
                    continue
                pls = acc["placements"].get(npc, [])
                if not acc["npc_names"].get(npc, 0):
                    reasons.append(f"ALUA[{alias}] NPC 无名字")
                if not pls:
                    reasons.append(f"ALUA[{alias}] NPC 0x{npc:08X} 没有放置引用")
                elif all(bad_cell(p["cell"]) for p in pls):
                    reasons.append(f"ALUA[{alias}] 放置引用全在暂存格（{len(pls)} 个）")
            for alias, refr in info.get("refs", []):
                ri = acc["refr_info"].get(refr)
                if not ri:
                    reasons.append(f"ALFR[{alias}] 引用不在世界数据里")
                elif bad_cell(ri.get("cell", 0)):
                    reasons.append(f"ALFR[{alias}] 落在暂存格")
            lctn = quest_lctn.get(r["formid"], 0) or (info["locs"][0] if info.get("locs") else 0)
            if lctn and not acc["lctns"].get(lctn, {}).get("marker", 0):
                reasons.append(f"地点 0x{lctn:08X} 没有地图标记(MNAM)")
            r["reasons"] = "; ".join(reasons) or "未识别的过滤（看 gen_guide_targets 的排除条件）"
            key = r["reasons"].split(";")[0].split("0x")[0].strip()
            reason_stats[key] += 1
        print("\n=== 第二步原因统计 ===")
        for k, v in reason_stats.most_common():
            print(f"  {k}: {v}")

    out_path = ROOT / "ref/no_targets_analysis.json"
    out_path.write_text(json.dumps(out_rows, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\nwrote {out_path}")

    print("\n=== 全部明细 ===")
    for r in out_rows:
        sigs = ",".join(r["sub_sigs"]) or "-"
        extra = f"  原因: {r['reasons']}" if r["reasons"] else ""
        print(f"  [{r['tag']}] {r['name']}（0x{r['local']:06X} {r['master']} 别名×{r['alias_count']}"
              f" {sigs}）{extra}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
