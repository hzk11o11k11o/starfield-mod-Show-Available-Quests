#!/usr/bin/env python3
"""survey_gate_coverage.py - 「进度没到不显示」的门槛覆盖盘点（第 109 轮 · 大项 B）。

背景（docs/99「下一步大项候选」第 ③ 项 / docs/08 4.3~4.5）：
  第 86 轮把 CTDA 的 operator 语义全解（运算符 = type >> 5、flags = type & 0x1F），
  第 87/106 轮把它产品化到「`==` + OR 位」这一子集。剩下的 `!=` / `>` / `>=` / `<` / `<=`
  与别名 / GLOB 等 flags **当时一律放行**（保守）。本工具回答：
  「数据侧还剩多少条能收？」——按 master、按表内/表外、按阻断原因摊开。

结论（第 109 轮实测，4 个 master 全量）：
  * INFO 侧 pending 共 87 条：`OR 组放弃` 77（表内 12）+ `运算符/flags` 7（表内 0）
    + `引用解析不了` 3（表内 0）；
  * 表内 12 条「OR 组放弃」的阻断项**不是运算符** —— 是同一组里混着
    **自引用条件**或**非进度类条件**（脚本/终端检查等）；这两类都不能安全求值 ⇒ 无空间；
  * 7 条运算符形态（`!=` / `>=`）全在**非表内**任务（对话容器 / 人群闲聊）上 ⇒ 对
    「可接任务列表」没有影响；
  * 记录级（QUST CTDA）：表内可收 11 条（= 现有 kQuestConds 全量）、DLC 表内 0 条
    （结构扫描实测）⇒ **记录级已无空间**。
  ⇒ 结论：operator 二期**没有可产品化的对象**；本工具因此只做盘点 + 反向监视
    （tripwire）—— 万一以后表扩充（补收 / 待定任务 / 新 DLC）出现「可折叠」形态，
    `--check` 会报红，那时再实现折叠（规则见 docs/08 4.6）。

用法：
    python tools/esm/survey_gate_coverage.py            # 盘点 + 写 ref/gate_coverage.json
    python tools/esm/survey_gate_coverage.py --check    # tripwire（退出码 1 = 出现可折叠形态）
    python tools/esm/survey_gate_coverage.py --record-scan  # 追加记录级结构扫描（约 1 分钟）
"""
from __future__ import annotations

import argparse
import collections
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
REF = ROOT / "ref"
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

OPS = {0: "==", 1: "!=", 2: ">", 3: ">=", 4: "<", 5: "<="}
PENDING_FILES = [
    ("info_gates_pending.json", "Starfield.esm"),
    ("info_gates_pending_shatteredspace.json", "ShatteredSpace.esm"),
    ("info_gates_pending_sfbgs00d.json", "SFBGS00D.esm"),
    ("info_gates_pending_sfbgs050.json", "SFBGS050.esm"),
]


def load_table() -> tuple[set[tuple[str, int]], int]:
    rows = json.loads((REF / "quest_table_debug.json").read_text(encoding="utf-8"))
    keys = {(r.get("master", "Starfield.esm"), int(r["local"]) & 0xFFFFFF) for r in rows}
    return keys, len(rows)


def scan_pending(in_table: set[tuple[str, int]]) -> dict:
    """按 (master, 原因, 前置是否解析, 表内/表外, 运算符/flags) 分类。"""
    per_class: collections.Counter = collections.Counter()
    per_master: dict[str, dict] = {}
    foldable: list[str] = []
    in_table_rows: list[str] = []
    for fn, self_master in PENDING_FILES:
        p = REF / fn
        if not p.exists():
            continue
        d = json.loads(p.read_text(encoding="utf-8"))
        sm = d.get("selfMaster", self_master)
        hist: collections.Counter = collections.Counter()
        for g in d["pending"]:
            key = (sm, int(g["quest"]) & 0xFFFFFF)
            it = key in in_table
            op = int(g["op"])
            fl = int(g["flags"])
            shape = f"{OPS.get(op, op)}/flags=0x{fl:02X}"
            cls = (g["reason"], "前置已解析" if g.get("resolved") else "前置未解析",
                   "表内" if it else "表外")
            hist[cls] += 1
            per_class[cls] += 1
            row = (f"{g['questEDID']}({sm}) {g['func']} "
                   f"pre={g.get('preEDID') or hex(g.get('pre', 0))} "
                   f"cmp={g['cmp']} {shape} reason={g['reason']}")
            if it:
                in_table_rows.append(row)
            # 「可折叠」= 运算符形态 + flags 只允许 OR + cmp ∈ {0,1} + 前置已解析。
            # 这是**唯一**还没产品化、且产品化后语义安全（三函数都返回 0/1 布尔）的形态。
            if (op in (1, 2, 3, 4, 5) and (fl & ~0x01) == 0 and g["cmp"] in (0.0, 1.0)
                    and g.get("resolved")):
                foldable.append(row + ("  ← 表内！需要产品化" if it else ""))
        per_master[sm] = {"file": fn, "total": len(d["pending"]),
                          "classes": {"/".join(k): v for k, v in hist.items()}}
    # ★ perClass 用**元组键**（打印时按下标取列）；写 JSON 时再 join（见 main）。
    return {"perMaster": per_master, "perClass": dict(per_class),
            "inTableRows": in_table_rows, "foldable": foldable}


def record_scan() -> dict:
    """记录级（QUST CTDA）结构扫描：表内任务的「进度类外键」条件形态。

    复用 `_tmp_r109_rec_ctda_scan.py` 的定位规则（记录级条件 = 第一条 INDX/ALST 之前的
    CTDA 段）—— 实测 FFConstantZ06 四次条件逐条与文档一致（4 条）。这里只统计。
    """
    import mmap
    import struct
    sys.path.insert(0, str(Path(__file__).parent))
    from esm_probe import subrecords  # noqa: E402

    data = Path(r"D:\SteamLibrary\steamapps\common\Starfield\Data")
    masters = ["Starfield.esm", "ShatteredSpace.esm", "SFBGS00D.esm", "SFBGS050.esm"]
    gate_funcs = {0x0038: "Running", 0x003B: "StageDone", 0x021F: "Completed"}
    sections = {b"INDX", b"ALST", b"ALED", b"QOBJ", b"QSTA", b"FNAM", b"QNOD", b"QNPC",
                b"QMDP", b"QSRD", b"SCEN", b"ANAM"}
    in_table, _n = load_table()
    out: dict[str, dict] = {}
    for m in masters:
        path = data / m
        if not path.exists():
            continue
        hist: collections.Counter = collections.Counter()
        samples: list[str] = []
        n_quest = n_ctda = 0
        with path.open("rb") as f:
            mm = mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ)
            try:
                head = struct.unpack_from("<I", mm, 4)[0]
                pos = 24 + head
                while pos + 24 <= len(mm):
                    if mm[pos:pos + 4] != b"GRUP":
                        break
                    gsize = struct.unpack_from("<I", mm, pos + 4)[0]
                    if gsize < 24:
                        break
                    if mm[pos + 8:pos + 12] != b"QUST":
                        pos += gsize
                        continue
                    p, end = pos + 24, pos + gsize
                    while p + 24 <= end:
                        sig = mm[p:p + 4]
                        size = struct.unpack_from("<I", mm, p + 4)[0]
                        if size < 24:
                            break
                        if sig == b"GRUP":
                            p += size
                            continue
                        if sig == b"QUST":
                            fid = struct.unpack_from("<I", mm, p + 12)[0]
                            local = fid & 0xFFFFFF
                            flags = struct.unpack_from("<I", mm, p + 8)[0]
                            payload = mm[p + 24:p + 24 + size]
                            if flags & 0x00040000:
                                import zlib
                                try:
                                    payload = zlib.decompress(mm[p + 28:p + 24 + size])
                                except zlib.error:
                                    payload = b""
                            section, conds, edid = "RECORD", [], ""
                            for s, sp in subrecords(payload):
                                if s == b"EDID":
                                    from esm_probe import ascii_z
                                    edid = ascii_z(sp)
                                if s in sections:
                                    section = "OTHER"
                                if s == b"CTDA" and section == "RECORD" and len(sp) >= 32:
                                    t = struct.unpack_from("<I", sp, 0)[0]
                                    conds.append((t >> 5, t & 0x1F,
                                                  struct.unpack_from("<f", sp, 4)[0],
                                                  struct.unpack_from("<H", sp, 8)[0],
                                                  struct.unpack_from("<I", sp, 12)[0],
                                                  struct.unpack_from("<I", sp, 20)[0]))
                            if conds:
                                n_quest += 1
                            for op, fl, cmpv, func, p1, runon in conds:
                                if func not in gate_funcs or runon != 0:
                                    continue
                                n_ctda += 1
                                if p1 in (0, local):
                                    continue
                                if fl & ~0x01:
                                    continue
                                if cmpv not in (0.0, 1.0):
                                    continue
                                hist[f"{OPS.get(op, op)}/flags=0x{fl:02X}"] += 1
                                if (m, local) in in_table and len(samples) < 20:
                                    samples.append(
                                        f"{edid}(0x{local:06X}) {gate_funcs[func]} "
                                        f"pre=0x{p1 & 0xFFFFFF:06X} cmp={cmpv} "
                                        f"{OPS.get(op, op)}/flags=0x{fl:02X}")
                        p += 24 + size
                    break
            finally:
                mm.close()
        out[m] = {"questsWithRecordCond": n_quest, "progressConds": n_ctda,
                  "gateableShapes": dict(hist), "inTableSamples": samples}
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="tripwire：出现可折叠形态 ⇒ 退出码 1")
    ap.add_argument("--record-scan", action="store_true", help="追加记录级结构扫描（约 1 分钟）")
    ap.add_argument("--out", default="ref/gate_coverage.json")
    a = ap.parse_args()

    in_table, n_rows = load_table()
    pend = scan_pending(in_table)
    info_final = json.loads((REF / "info_gates_final.json").read_text(encoding="utf-8"))
    n_info_tasks = len(info_final)
    n_info_groups = sum(len(t.get("infos", [])) for t in info_final)
    n_info_conds = sum(len(i.get("conds", [])) for t in info_final for i in t.get("infos", []))
    ctda = json.loads((REF / "ctda_gates.json").read_text(encoding="utf-8"))
    n_ctda_tasks = len(ctda)
    n_ctda_conds = sum(len(t.get("gates", [])) for t in ctda)
    in_table_gate_tasks = sum(1 for t in ctda
                              if ("Starfield.esm", int(t["formid"]) & 0xFFFFFF) in in_table)
    in_table_gate_conds = sum(len(t.get("gates", [])) for t in ctda
                              if ("Starfield.esm", int(t["formid"]) & 0xFFFFFF) in in_table)

    lines: list[str] = []

    def out(s: str = "") -> None:
        """控制台 + 报告文本双写（★ PowerShell 管道对中文有编码坑 ⇒ 同时落一份 txt）。"""
        print(s)
        lines.append(s)

    out(f"静态表 {n_rows} 条")
    out(f"INFO 门槛 {n_info_tasks} 条任务 / {n_info_groups} 条对话 / {n_info_conds} 条条件")
    out(f"记录级门槛文件 {n_ctda_tasks} 条任务 / {n_ctda_conds} 条条件"
        f"（其中进静态表的 {in_table_gate_tasks} 条任务 / {in_table_gate_conds} 条条件）")
    out("")
    out("=== INFO 侧「进度类外键、不可门槛」按 (原因 / 前置 / 表内) 分类（4 个 master）===")
    for k, v in sorted(pend["perClass"].items(), key=lambda kv: (-kv[1], kv[0])):
        out(f"  {k[0]:<26} {k[1]:<8} {k[2]:<6} {v}")
    out("")
    out(f"表内条目 {len(pend['inTableRows'])} 条（明细）：")
    for s in pend["inTableRows"]:
        out("  · " + s)
    out("")
    out(f"可折叠形态 {len(pend['foldable'])} 条（`!=`/`>`/`>=`/`<`/`<=` + cmp∈{{0,1}}"
        f" + 前置已解析；标「表内」的才是真对象）：")
    for s in pend["foldable"]:
        out("  · " + s)

    report = {
        "_why": "第 109 轮（大项 B）：门槛覆盖盘点 —— operator 二期还有多少可收（结论：表内 0 条）",
        "tableRows": n_rows,
        "infoGates": {"tasks": n_info_tasks, "groups": n_info_groups, "conds": n_info_conds},
        "recordGates": {"fileTasks": n_ctda_tasks, "fileConds": n_ctda_conds,
                        "inTableTasks": in_table_gate_tasks,
                        "inTableConds": in_table_gate_conds},
        "infoPending": {**pend,
                        "perClass": {"/".join(k): v for k, v in pend["perClass"].items()}},
        "conclusion": ("表内任务上没有可产品化的 operator 形态：12 条 pending 全部因"
                       "「同组含自引用/非进度类条件」放弃（与运算符无关）；"
                       "7 条运算符形态都在非表内任务上；记录级表内 11 条已全是 `==`。"),
    }
    if a.record_scan:
        # ★ 记录级扫描写**单独文件**（约 1 分钟；主报告要能进黄金快照 ⇒ 必须只含
        #   JSON 侧分析、随时可重建 —— 见 docs/10）。
        rec = record_scan()
        rec_path = Path(a.out).with_name(Path(a.out).stem + "_record.json")
        rec_path.write_text(json.dumps(rec, ensure_ascii=False, indent=1), encoding="utf-8")
        out("")
        out("=== 记录级结构扫描（结构定位：第一条 INDX/ALST 之前的 CTDA；表内 = 命中静态表）===")
        for m, d in rec.items():
            out(f"  {m}: 带记录级条件 {d['questsWithRecordCond']} 条 / "
                f"进度类条件 {d['progressConds']} 条 / 可收形态 {d['gateableShapes']} / "
                f"表内样本 {len(d['inTableSamples'])} 条")
            for s in d["inTableSamples"]:
                out("      " + s)
        out(f"（记录级明细另存 {rec_path}）")

    foldable_in_table = [s for s in pend["foldable"] if "表内" in s]
    if a.check:
        # tripwire 只读：不写报告（避免把完整报告覆盖成精简版）
        if foldable_in_table:
            print(f"[tripwire] 表内任务出现 {len(foldable_in_table)} 条可折叠形态 ⇒ "
                  f"需要产品化（折叠规则见 docs/08 4.6）：")
            for s in foldable_in_table:
                print("  " + s)
            return 1
        print("[tripwire] OK：表内任务没有可折叠形态（operator 二期仍无对象）")
        return 0

    Path(a.out).write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    txt = Path(a.out).with_suffix(".txt")
    txt.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"\nwrote {a.out} / {txt}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
