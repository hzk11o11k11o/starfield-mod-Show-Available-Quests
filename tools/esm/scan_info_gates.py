#!/usr/bin/env python3
"""scan_info_gates.py - 大项 D：扫 Starfield.esm 里「任务对话（DIAL/INFO）」的条件。

背景：Starfield 的对话挂在 QUST 的 children 组下（GRUP type=10, label=quest FormID）
—— **INFO → 所属任务** 从组链直接可得（不像 Skyrim 要过 DIAL 的 QNAM）。

本工具做三件事（只读探测 + 产出一份原始数据）：
  1. 统计 INFO 规模（总数 / 带 CTDA / 带 VMAD）；
  2. 提取「引用**别的任务**」的进度类条件（GetQuestRunning/GetStageDone/GetQuestCompleted 的
     等于比较）—— 这是「接取前置」在对话侧的表达，作为大项 D 的候选门槛；
  3. 输出 ref/info_gates.json 供后续分析（另附函数索引分布，方便以后扩子集）。

用法：
    python tools/esm/scan_info_gates.py            # 全表扫描 + 写 json
    python tools/esm/scan_info_gates.py --top 30   # 多打几条样例
"""
from __future__ import annotations

import argparse
import json
import struct
import sys
import zlib
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from esm_probe import DEFAULT_ESM, subrecords  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
REF = ROOT / "ref"

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# 任务侧 CTDA 对照表里已确认的进度类函数（见 analyze_ctda.py --funcs）
GATE_FUNCS = {
    0x0038: "GetQuestRunning",
    0x003B: "GetStageDone",
    0x021F: "GetQuestCompleted",
}


def parse_ctda_raw(b: bytes) -> dict | None:
    if len(b) < 32:
        return None
    return {
        "op": b[0],
        "cmp": round(struct.unpack_from("<f", b, 4)[0], 6),
        "func": struct.unpack_from("<H", b, 8)[0],
        "p1": struct.unpack_from("<I", b, 12)[0],
        "p2": struct.unpack_from("<I", b, 16)[0],
        "runOn": struct.unpack_from("<I", b, 20)[0],
        "ref": struct.unpack_from("<I", b, 24)[0],
        "p3": struct.unpack_from("<i", b, 28)[0],
    }


def payload_of(buf: bytes, p: int) -> tuple[int, bytes] | None:
    size = struct.unpack_from("<I", buf, p + 4)[0]
    flags = struct.unpack_from("<I", buf, p + 8)[0]
    formid = struct.unpack_from("<I", buf, p + 12)[0]
    if flags & 0x00040000:
        if size < 4:
            return None
        try:
            return formid, zlib.decompress(buf[p + 28:p + 24 + size])
        except zlib.error:
            return None
    return formid, buf[p + 24:p + 24 + size]


def scan_info(buf: bytes, start: int, end: int, quest: int, out: list) -> None:
    """递归一个 quest children 组，收集 INFO 记录。"""
    p = start
    while p + 24 <= end:
        sig = buf[p:p + 4]
        size = struct.unpack_from("<I", buf, p + 4)[0]
        if size < 24:
            return
        if sig == b"GRUP":
            scan_info(buf, p + 24, p + size, quest, out)
            p += size
            continue
        if sig == b"INFO":
            got = payload_of(buf, p)
            if got:
                out.append((quest, got[0], got[1]))
        p += 24 + size


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--top", type=int, default=20)
    ap.add_argument("--esm", default=DEFAULT_ESM)
    # ★★ 第 78 轮（DLC 的 INFO 门槛）：多 master 扫描 ——
    #   每个 master 各扫一次、各写一份 info_gates*.json，由 analyze_info_gates.py 合并。
    #   `--self-master` = 被扫文件对应的 master 名（默认 Starfield.esm）。
    #   ★ 文件内的 FormID 形态：**该 DLC 自己的记录引用写 0x01xxxxxx**（它自己的
    #   「本文件内 master 序号」= 1；Starfield.esm 的引用写 0x00xxxxxx）——
    #   探针见本轮 docs；所以判「引用是不是本文件的任务」用原始 p1 直接查本文件任务集。
    ap.add_argument("--out", default="ref/info_gates.json")
    ap.add_argument("--self-master", default="Starfield.esm")
    a = ap.parse_args()

    # 基础游戏（Starfield.esm）的任务记录号集合 —— DLC 文件里引用 0x00xxxxxx 时用它判别。
    base_locals: set[int] = set()
    base_edid: dict[int, str] = {}
    if (REF / "quests_all.json").exists():
        for q in json.loads((REF / "quests_all.json").read_text(encoding="utf-8")):
            if (q.get("master") or "Starfield.esm") == "Starfield.esm":
                base_locals.add(int(q["local"]) & 0xFFFFFF)
                if q.get("edid"):
                    base_edid[int(q["local"]) & 0xFFFFFF] = q["edid"]

    print(f"读 {a.esm} …（self-master={a.self_master}）")
    buf = Path(a.esm).read_bytes()
    head = struct.unpack_from("<I", buf, 4)[0]
    pos = 24 + head

    infos: list[tuple[int, int, bytes]] = []
    quests: set[int] = set()
    quest_edid: dict[int, str] = {}

    while pos + 24 <= len(buf):
        if buf[pos:pos + 4] != b"GRUP":
            break
        gsize = struct.unpack_from("<I", buf, pos + 4)[0]
        if gsize < 24:
            break
        if buf[pos + 8:pos + 12] == b"QUST":
            p = pos + 24
            cur = 0
            while p + 24 <= pos + gsize:
                sig = buf[p:p + 4]
                size = struct.unpack_from("<I", buf, p + 4)[0]
                if size < 24:
                    break
                if sig == b"GRUP":
                    scan_info(buf, p + 24, p + size, cur, infos)
                    p += size
                    continue
                if sig == b"QUST":
                    got = payload_of(buf, p)
                    if got:
                        cur = got[0]
                        quests.add(cur)
                        for s, sp in subrecords(got[1]):
                            if s == b"EDID":
                                quest_edid[cur] = sp.split(b"\x00")[0].decode("latin1", "replace")
                p += 24 + size
            break
        pos += gsize

    print(f"QUST 记录 {len(quests)} 条；INFO 记录 {len(infos)} 条")

    func_hist = Counter()
    n_ctda = 0
    n_vmad = 0
    gates = []
    per_quest = defaultdict(set)
    # ★ 大项 D：用「自引用条件」（任务自己未开始 / 已在某阶段）给 INFO 分类 ——
    #   入口类（未开始）/ 推进类（进行中）/ 中性。只有入口类里的「引用别的任务」
    #   条件才可能是**接取门槛**（推进类的是回报/分支对话，不能拿来判定接取）。
    kind_hist = Counter()
    info_records = []

    for quest, info_id, payload in infos:
        conds = []
        has_vmad = False
        for s, sp in subrecords(payload):
            if s == b"CTDA":
                c = parse_ctda_raw(sp)
                if c:
                    conds.append(c)
            elif s == b"VMAD":
                has_vmad = True
        if has_vmad:
            n_vmad += 1
        if not conds:
            continue
        n_ctda += 1

        def is_progress(c):  # 保守子集形态（op/cmp/runOn）
            return (c["op"] == 0x00 and c["cmp"] in (0.0, 1.0)
                    and c["runOn"] == 0 and c["func"] in GATE_FUNCS)

        self_want1 = any(is_progress(c) and c["p1"] == quest and c["cmp"] == 1.0 for c in conds)
        self_want0 = any(is_progress(c) and c["p1"] == quest and c["cmp"] == 0.0 for c in conds)
        if self_want1:
            kind = "推进"   # 任务已在某阶段/已完成 ⇒ 进行中的对话
        elif self_want0:
            kind = "入口"   # 任务还没开始 ⇒ 可能是接取/触发对话
        else:
            kind = "中性"

        others = []
        for c in conds:
            func_hist[c["func"]] += 1
            if not is_progress(c):
                continue
            p1 = c["p1"]
            if p1 == 0 or p1 == quest:
                continue
            # ★★ 第 78 轮：把引用解析成「(master 名, 记录号)」——
            #   ① 命中本文件自己的任务集 ⇒ 本 DLC（DLC 里自己的记录是 0x01xxxxxx）；
            #   ② 高字节 0 且低 24 位是基础游戏的任务 ⇒ Starfield.esm；
            #   ③ 其余（别的 master / 非任务）⇒ 跳过（保守，不猜）。
            if p1 in quests:
                pre_master = a.self_master
                pre_local = p1 & 0xFFFFFF
                pre_edid = quest_edid.get(p1, "")
            elif (p1 >> 24) == 0 and (p1 & 0xFFFFFF) in base_locals:
                pre_master = "Starfield.esm"
                pre_local = p1 & 0xFFFFFF
                pre_edid = base_edid.get(p1 & 0xFFFFFF, "")
            else:
                continue
            others.append((c, pre_master, pre_local, pre_edid))

        if others:
            kind_hist[kind] += 1
            for (c, pre_master, pre_local, pre_edid) in others:
                g = {
                    "info": info_id,
                    "quest": quest,
                    "questEDID": quest_edid.get(quest, ""),
                    "kind": kind,
                    "func": GATE_FUNCS[c["func"]],
                    "pre": pre_local,
                    "preMaster": pre_master,
                    "preEDID": pre_edid,
                    "want": 1 if c["cmp"] == 1.0 else 0,
                    "stage": (c["p2"] & 0xFFFF) if c["func"] == 0x003B else 0,
                }
                gates.append(g)
                per_quest[quest].add((g["pre"], g["func"], g["want"], g["stage"]))
        info_records.append({
            "info": info_id,
            "quest": quest,
            "edid": quest_edid.get(quest, ""),
            "kind": kind,
            "others": [{"func": GATE_FUNCS[c["func"]], "pre": pre_local,
                        "preMaster": pre_master,
                        "preEDID": pre_edid,
                        "want": 1 if c["cmp"] == 1.0 else 0,
                        "stage": (c["p2"] & 0xFFFF) if c["func"] == 0x003B else 0}
                       for (c, pre_master, pre_local, pre_edid) in others],
        })

    print(f"├─ 带 CTDA 的 INFO：{n_ctda}")
    print(f"├─ 带 VMAD 的 INFO：{n_vmad}")
    print(f"├─ 引用「别的任务」的进度条件：{len(gates)} 条")
    print(f"└─ 涉及任务：{len(per_quest)} 条（其中前置去重 {len({(g['pre']) for g in gates})} 个）")
    print(f"\n--- 带前置条件的 INFO 按「自引用」分类 ---")
    for k, n in kind_hist.most_common():
        print(f"  {k}: {n} 条 INFO")

    # 只打「入口」类的样例（大项 D 真正要用的那一档）
    entry_gates = [g for g in gates if g["kind"] == "入口"]
    print(f"\n--- 「入口」类样例外 {a.top} 条（{len(entry_gates)} 条总数）---")
    for g in entry_gates[:a.top]:
        pre = f"{g['preEDID']}(0x{g['pre']:06X})"
        extra = f" stage {g['stage']}" if g["func"] == "GetStageDone" else ""
        print(f"  {g['questEDID']:<38} 需要 {g['func']}({pre}{extra}) == {g['want']}   [info 0x{g['info']:06X}]")

    print("\n--- INFO 侧函数索引分布（前 30） ---")
    for idx, n in func_hist.most_common(30):
        known = GATE_FUNCS.get(idx, "")
        print(f"  0x{idx:04X} ({idx:5d}) ×{n:<6} {known}")

    # 按任务聚合输出（供后续策略分析）
    by_quest = []
    for quest, keys in sorted(per_quest.items(), key=lambda kv: -len(kv[1])):
        by_quest.append({
            "quest": quest,
            "edid": quest_edid.get(quest, ""),
            "conds": sorted(keys),
        })

    out_path = REF / Path(a.out).name
    out_path.write_text(json.dumps({
        "selfMaster": a.self_master,
        "infoTotal": len(infos),
        "infoWithCtda": n_ctda,
        "infoWithVmad": n_vmad,
        "gateCount": len(gates),
        "kindHist": dict(kind_hist),
        "gates": gates,
        "byQuest": by_quest,
        "infoRecords": info_records,
    }, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\nwrote {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
