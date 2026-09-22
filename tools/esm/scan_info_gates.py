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
    # ★ 第 106 轮（operator 全量产品化）：op 改读 **u32** —— 与 analyze_ctda.py 同款位域
    #   解析（运算符 = op >> 5、flags = op & 0x1F；第 86 轮反汇编实证见 docs/08 4.3）。
    #   旧实现只读 b[0]（低字节）：实测数据恰好都 < 0x100 所以没出错，但不严谨。
    return {
        "op": struct.unpack_from("<I", b, 0)[0],
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
    # ★ 第 106 轮（operator 全量产品化）：全量 CTDA 的 operator/flags 盘点 ——
    #   ① op_hist：全部条件按 (运算符, flags) 分布；
    #   ② prog_hist：进度类形态（三函数 + Run On=Subject + cmp∈{0,1}）条件分布；
    #   ③ pending：**外键进度类、但旧判据不收**（op != 0 —— 带运算符/flags）的清单
    #     —— 这就是「还能收多少」的答案。本轮只统计，不改提取行为。
    op_hist = Counter()
    prog_hist = Counter()
    pending = []
    n_drop_group = 0   # 被放弃的 OR 组数（累计 —— 注意别放进 INFO 循环里重置）
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
                    op_hist[(c["op"] >> 5, c["op"] & 0x1F)] += 1
            elif s == b"VMAD":
                has_vmad = True
        if has_vmad:
            n_vmad += 1
        if not conds:
            continue
        n_ctda += 1

        # ★ 第 106 轮（operator 全量产品化）：判据拆两层 ——
        #   · is_progress = 「进度类形态」（三函数 + Run On=Subject + cmp∈{0,1}），
        #     **不含 op/flags 要求**：用于对话分类（入口/推进/中性）。
        #     旧实现要求 op==0 ⇒ 带 OR 位的自引用条件看不见 ⇒ 分类会偏。
        #   · is_gateable = 「可作为门槛条件」：进度类 + **运算符 == 且 flags 只允许
        #     OR 位**（与记录级 analyze_ctda.py 的 cond_to_gate 同判据，见 docs/08 4.3）。
        def is_progress(c):
            return (c["runOn"] == 0 and c["cmp"] in (0.0, 1.0)
                    and c["func"] in GATE_FUNCS)

        def is_gateable(c):
            t = c["op"]
            return (t >> 5) == 0 and (t & ~0x01) == 0 and is_progress(c)

        self_want1 = any(is_progress(c) and c["p1"] == quest and c["cmp"] == 1.0 for c in conds)
        self_want0 = any(is_progress(c) and c["p1"] == quest and c["cmp"] == 0.0 for c in conds)
        if self_want1:
            kind = "推进"   # 任务已在某阶段/已完成 ⇒ 进行中的对话
        elif self_want0:
            kind = "入口"   # 任务还没开始 ⇒ 可能是接取/触发对话
        else:
            kind = "中性"

        def resolve_pre(p1: int):
            """把 p1 解析成 (master 名, 记录号, EDID)；解析不了 ⇒ None。

            ★★ 第 78 轮：① 命中本文件自己的任务集 ⇒ 本 DLC（DLC 里自己的记录是
              0x01xxxxxx）；② 高字节 0 且低 24 位是基础游戏的任务 ⇒ Starfield.esm；
              ③ 其余（别的 master / 非任务）⇒ None（保守，不猜）。
            """
            if p1 in quests:
                return a.self_master, p1 & 0xFFFFFF, quest_edid.get(p1, "")
            if (p1 >> 24) == 0 and (p1 & 0xFFFFFF) in base_locals:
                return "Starfield.esm", p1 & 0xFFFFFF, base_edid.get(p1 & 0xFFFFFF, "")
            return None

        # 全量统计（每条条件恰好一次）
        for c in conds:
            func_hist[c["func"]] += 1
            if c["func"] in GATE_FUNCS and c["runOn"] == 0 and c["cmp"] in (0.0, 1.0):
                prog_hist[(c["op"] >> 5, c["op"] & 0x1F)] += 1

        def note_pending(c, reason):
            """「进度类 + 外键」但**不能作为门槛** ⇒ 记入仍放行清单（监控/文档用）。"""
            p1 = c["p1"]
            if not (is_progress(c) and p1 not in (0, quest)):
                return
            rp = resolve_pre(p1)
            pending.append({
                "info": info_id, "quest": quest,
                "questEDID": quest_edid.get(quest, ""),
                "func": GATE_FUNCS[c["func"]],
                "op": c["op"] >> 5, "flags": c["op"] & 0x1F,
                "cmp": c["cmp"], "reason": reason,
                "pre": rp[1] if rp else (p1 & 0xFFFFFF),
                "preMaster": rp[0] if rp else "",
                "preEDID": rp[2] if rp else "",
                "want": 1 if c["cmp"] == 1.0 else 0,
                "stage": (c["p2"] & 0xFFFF) if c["func"] == 0x003B else 0,
                "resolved": bool(rp),
            })

        # ★ 第 106 轮：按 **OR 组语义**提取「外键进度类」条件（与记录级 build_gates 同款）——
        #   组 = 从带 OR 位的条件起，到**第一条不带 OR 位的条件（含）**或列表末尾；
        #   组里只要有一条「不能作为门槛」（非进度类 / 自引用 / 含其它 flags /
        #   引用解析不了）⇒ **整组放弃**（不倒半组 —— 那样会把 OR 语义算错）。
        others = []
        i, ncond = 0, len(conds)
        while i < ncond:
            c = conds[i]
            if not (c["op"] & 0x01):
                if is_gateable(c) and c["p1"] not in (0, quest):
                    rp = resolve_pre(c["p1"])
                    if rp:
                        others.append((c, *rp))
                    else:
                        note_pending(c, "引用解析不了")
                elif is_progress(c):
                    note_pending(c, "运算符/flags 不在门槛子集")
                i += 1
                continue
            j = i
            while j < ncond and (conds[j]["op"] & 0x01):
                j += 1
            if j < ncond:
                j += 1   # 含关闭组的那个条件
            group = conds[i:j]
            tmp = []
            ok = True
            for gc in group:
                if not is_gateable(gc):
                    ok = False
                    break
                if gc["p1"] in (0, quest):
                    ok = False
                    break
                rp = resolve_pre(gc["p1"])
                if not rp:
                    ok = False
                    break
                tmp.append((gc, *rp))
            if ok and tmp:
                others.extend(tmp)
            else:
                n_drop_group += 1
                for gc in group:
                    note_pending(gc, "OR 组放弃")
            i = j

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
                    # ★ 第 106 轮：OR 位（组语义与记录级一致，运行时见 SAQ_QuestCond.cpp）
                    "orBit": 1 if (c["op"] & 0x01) else 0,
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
                        "orBit": 1 if (c["op"] & 0x01) else 0,
                        "stage": (c["p2"] & 0xFFFF) if c["func"] == 0x003B else 0}
                       for (c, pre_master, pre_local, pre_edid) in others],
        })

    print(f"├─ 带 CTDA 的 INFO：{n_ctda}")
    print(f"├─ 带 VMAD 的 INFO：{n_vmad}")
    print(f"├─ 引用「别的任务」的进度条件：{len(gates)} 条")
    print(f"└─ 涉及任务：{len(per_quest)} 条（其中前置去重 {len({(g['pre']) for g in gates})} 个）")

    # ★ 第 106 轮（operator 全量产品化）：operator/flags 盘点 —— 见文件头部/统计变量注释。
    OPS = {0: "==", 1: "!=", 2: ">", 3: ">=", 4: "<", 5: "<="}
    print(f"\n--- ★ operator/flags 盘点（第 106 轮） ---")
    print(f"全部 CTDA {sum(op_hist.values())} 条，按 (运算符, flags) 分布：")
    for (op, fl), n in sorted(op_hist.items()):
        print(f"  {OPS.get(op, f'op{op}'):<2} flags=0x{fl:02X}: {n}")
    print(f"进度类形态（三函数 + Subject + cmp∈{{0,1}}）{sum(prog_hist.values())} 条：")
    for (op, fl), n in sorted(prog_hist.items()):
        print(f"  {OPS.get(op, f'op{op}'):<2} flags=0x{fl:02X}: {n}")
    print(f"OR 组放弃 {n_drop_group} 组（组内有不可门槛/自引用/解析不了的条件）")
    print(f"外键进度类、但仍放行（不可门槛）{len(pending)} 条：")
    for g in pending[:80]:
        extra = f" stage {g['stage']}" if g["func"] == "GetStageDone" else ""
        pre = (f"{g['preEDID']}(0x{g['pre']:06X})" if g["resolved"]
               else f"0x{g['pre']:06X}?")
        print(f"  {g['questEDID']:<38} {g['func']}({pre}{extra}) cmp={g['cmp']} "
              f"op={OPS.get(g['op'], g['op'])} flags=0x{g['flags']:02X} "
              f"reason={g['reason']} [info 0x{g['info']:06X}]")
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

    # ★ 第 106 轮：operator 盘点产物（待产品化候选清单 + 分布）—— 供后续分析与 verify。
    #   文件名由 --out 派生（多 master 各扫一份，不能互相覆盖）：
    #   info_gates.json → info_gates_pending.json /
    #   info_gates_sfbgs00d.json → info_gates_pending_sfbgs00d.json …
    pending_path = REF / Path(a.out).name.replace("info_gates", "info_gates_pending", 1)
    pending_path.write_text(json.dumps({
        "selfMaster": a.self_master,
        "dropGroups": n_drop_group,
        "opHist": {f"{k[0]}/{k[1]}": v for k, v in sorted(op_hist.items())},
        "progHist": {f"{k[0]}/{k[1]}": v for k, v in sorted(prog_hist.items())},
        "pending": pending,
    }, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"wrote {pending_path}（operator 盘点：待产品化 {len(pending)} 条）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
