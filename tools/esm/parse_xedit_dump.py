#!/usr/bin/env python3
"""parse_xedit_dump.py - 解析 dump_quests.pas 导出的任务树，产出结构化数据。

输入：ref/xedit/quests_typed.txt（缩进树）
输出：
  ref/quests_parsed.json  每个任务的结构化信息
  控制台统计

结构要点（实测）：
  * 记录级条件出现在 "Stages" 之前（与 DNAM/QTYP 同级或更浅）
  * stage/objective/alias 各自有自己的 Conditions 子树
  * CTDA 节点的子项：Type / Comparison Value / Function / Parameter #N / Run On
"""
from __future__ import annotations

import argparse
import io
import json
import re
import sys
from collections import Counter
from pathlib import Path

HEAD_RE = re.compile(r"^(\S+)\s+\"(.*)\"\s+\[QUST:([0-9A-F]{8})\]")
KV_RE = re.compile(r"^(.*?)\s=\s(.*)$")


def indent_of(line: str) -> int:
    return len(line) - len(line.lstrip(" "))


def parse_conditions(lines, i, indent):
    """从 lines[i] 开始（一个 Conditions 节点）收集所有 CTDA。返回 (conds, next_i)。"""
    conds = []
    while i < len(lines):
        line = lines[i]
        if not line.strip():
            i += 1
            continue
        ind = indent_of(line)
        if ind <= indent:
            break
        text = line.strip()
        if text.startswith("CTDA - CTDA"):
            cur = {}
            i += 1
            while i < len(lines):
                sub = lines[i]
                if not sub.strip():
                    i += 1
                    continue
                if indent_of(sub) <= ind:
                    break
                m = KV_RE.match(sub.strip())
                if m:
                    cur[m.group(1).strip()] = m.group(2).strip()
                i += 1
            conds.append(cur)
            continue
        i += 1
    return conds, i


def parse_quest(block: str):
    lines = [ln for ln in block.splitlines()]
    if not lines:
        return None
    # block 第一行是 "00002C1C  MB_xxx ==="，第二行才是记录头
    first = lines[0].strip()
    formid_hint = first.split()[0] if first.split() else ""
    head_idx = 1 if len(lines) > 1 and HEAD_RE.match(lines[1].strip()) else 0
    m = HEAD_RE.match(lines[head_idx].strip())
    if not m:
        return None
    edid, name, formid = m.group(1), m.group(2), m.group(3)
    lines = lines[head_idx:]
    out = {
        "formid": formid,
        "edid": edid,
        "name": name,
        "dnam_flags": "",
        "dnam_priority": "",
        "qtyp": "",
        "record_conditions": [],
        "aliases": [],
        "has_objs": False,
        "stages": 0,
        "conditions_all": [],
    }

    i = 1
    stage_started = False
    while i < len(lines):
        line = lines[i]
        if not line.strip():
            i += 1
            continue
        ind = indent_of(line)
        text = line.strip()

        # 顶层元素（indent == 2）
        if ind == 2:
            if text.startswith("Stages"):
                stage_started = True
            if text.startswith("Objectives"):
                out["has_objs"] = True

        if text.startswith("QTYP"):
            mm = KV_RE.match(text)
            if mm:
                out["qtyp"] = mm.group(2)
        elif text.startswith("Priority"):
            mm = KV_RE.match(text)
            if mm:
                out["dnam_priority"] = mm.group(2)
        elif text.startswith("Conditions") and not stage_started:
            conds, i = parse_conditions(lines, i + 1, ind)
            out["record_conditions"].extend(conds)
            continue
        elif text.startswith("Conditions"):
            conds, i = parse_conditions(lines, i + 1, ind)
            out["conditions_all"].extend(conds)
            continue
        elif text.startswith("[QUST]") is False and re.match(r"^\S+\s\[(ALLS|ALST|ALCS|ALFI|ALAM|ALCO)\]\s\(", text):
            out["aliases"].append(text)
        elif text.startswith("Stage [INDX]"):
            out["stages"] += 1
        elif text.startswith("Flags []") and not stage_started:
            # DNAM\Flags 下的 flag 行
            pass
        i += 1

    # DNAM flags：在 DNAM 块里找 "Unknown NN = 1" 或已知 flag 名
    dnam_pos = None
    for idx, ln in enumerate(lines):
        if ln.strip().startswith("DNAM - General"):
            dnam_pos = idx
            break
    if dnam_pos is not None:
        flags = []
        j = dnam_pos + 1
        while j < len(lines):
            t = lines[j].strip()
            if indent_of(lines[j]) <= 2:
                break
            if t.startswith("Flags []"):
                k = j + 1
                while k < len(lines) and indent_of(lines[k]) > indent_of(lines[j]):
                    if " = 1" in lines[k]:
                        flags.append(lines[k].strip().split(" = ")[0])
                    k += 1
                break
            j += 1
        out["dnam_flags"] = ";".join(flags)
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("dump")
    ap.add_argument("--json", default="ref/quests_parsed.json")
    ap.add_argument("--stats", action="store_true")
    a = ap.parse_args()

    txt = io.open(a.dump, encoding="utf-8-sig", errors="replace").read()
    blocks = re.split(r"\r?\n=== ", txt)
    quests = []
    for b in blocks[1:]:
        q = parse_quest(b)
        if q:
            quests.append(q)

    Path(a.json).write_text(json.dumps(quests, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"parsed {len(quests)} quests -> {a.json}")

    if a.stats:
        print("\n--- 类型分布 ---")
        for k, v in Counter(q["qtyp"].split(" [")[0] for q in quests).most_common():
            print(f"  {k}: {v}")

        print("\n--- 记录级条件数量分布（非主线任务） ---")
        nonmain = [q for q in quests if "MainQuest" not in q["qtyp"]]
        print(f"  非主线任务数: {len(nonmain)}")
        dist = Counter(len(q["record_conditions"]) for q in nonmain)
        for k in sorted(dist):
            print(f"  记录级条件 {k} 条: {dist[k]} 个任务")

        print("\n--- 记录级条件的 Function 词频（非主线，前 30） ---")
        fns = Counter()
        for q in nonmain:
            for c in q["record_conditions"]:
                fns[c.get("Function", "?")] += 1
        for k, v in fns.most_common(30):
            print(f"  {k}: {v}")

        print("\n--- DNAM flags 词频（非主线，前 20） ---")
        fl = Counter()
        for q in nonmain:
            if q["dnam_flags"]:
                for f in q["dnam_flags"].split(";"):
                    fl[f] += 1
        for k, v in fl.most_common(20):
            print(f"  {k}: {v}")

        print("\n--- 有 Objectives 的比例 ---")
        print(f"  {sum(1 for q in nonmain if q['has_objs'])} / {len(nonmain)}")

        print("\n--- alias 数量分布（非主线，前 12） ---")
        dist2 = Counter(len(q["aliases"]) for q in nonmain)
        for k in sorted(dist2)[:12]:
            print(f"  {k} 个 alias: {dist2[k]} 个任务")
    return 0


if __name__ == "__main__":
    sys.exit(main())
