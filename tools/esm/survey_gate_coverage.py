#!/usr/bin/env python3
"""survey_gate_coverage.py - 「进度没到不显示」的门槛覆盖盘点（第 109 轮 · 大项 B；
★★★ 第 128 轮随 **operator 二期**升级）。

背景（docs/99「下一步大项候选」第 ③ 项 / docs/08 4.3~4.6 / 4.7）：
  第 86 轮把 CTDA 的 operator 语义全解（运算符 = type >> 5、flags = type & 0x1F）；
  第 87/106 轮产品化到「`==` + OR 位」；**第 128 轮把余下的运算符（`!=` / `>` /
  `>=` / `<` / `<=`）也折叠产品化**（`tools/esm/ctda_ops.py`，真值表 + 组语义）——
  折叠后**只剩 flags（别名 / GLOB / Pack Data / 交换主客体）与 cmp∉{0,1} 管不到**。

本工具回答：「数据侧还剩多少条能收？」并按 (原因 / 前置 / 表内/表外 / 运算符·flags) 摊开。
第 128 轮的两类判据（`--check` 的报红条件）：
  * **折叠已覆盖却仍 pending**（进度类 + 外键 + 前置已解析 + flags 只允许 OR +
    cmp∈{0,1} + 运算符 ∈ 1..5）⇒ 说明**扫描没重跑 / 折叠逻辑退化**（数据管线问题）；
  * **折叠管不到的形态在表内**（flags 非 OR / cmp∉{0,1}）⇒ 需要「后续阶段」产品化
    （GLOB 比较值 / 别名解析 —— 与运算符无关）。

结论（第 109 轮盘点 + 第 128 轮落地的实测）：
  * 表内 12 条「OR 组放弃」的阻断项**不是运算符** —— 是同一组里混着
    **自引用条件**或**非进度类条件**（脚本/终端检查等）⇒ 整组放弃（两轮都一致）；
  * 7 条运算符形态全在**非表内**任务（对话容器 / 人群闲聊 / DLC 对话任务）上
    ⇒ 折叠收进门槛后对「可接任务列表」零影响（表内对象 = 0）；
  * 记录级（QUST CTDA）：表内 11 条全是 `==`（结构扫描实测）⇒ 折叠后表内 0 变化。

用法：
    python tools/esm/survey_gate_coverage.py            # 盘点 + 写 ref/gate_coverage.json
    python tools/esm/survey_gate_coverage.py --check    # tripwire（退出码 1 = 上面两类形态出现）
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
    # ★★ 第 110 轮：追踪者联盟（SFBGS003.esm，medium 档）—— 第 128 轮补进盘点
    ("info_gates_pending_sfbgs003.json", "SFBGS003.esm"),
    ("info_gates_pending_shatteredspace.json", "ShatteredSpace.esm"),
    ("info_gates_pending_sfbgs00d.json", "SFBGS00D.esm"),
    ("info_gates_pending_sfbgs050.json", "SFBGS050.esm"),
]


def load_table() -> tuple[set[tuple[str, int]], int]:
    rows = json.loads((REF / "quest_table_debug.json").read_text(encoding="utf-8"))
    keys = {(r.get("master", "Starfield.esm"), int(r["local"]) & 0xFFFFFF) for r in rows}
    return keys, len(rows)


def scan_pending(in_table: set[tuple[str, int]]) -> dict:
    """按 (master, 原因, 前置是否解析, 表内/表外, 运算符/flags) 分类。

    ★★★ 第 128 轮（operator 二期）新增两档判据（均只对**表内**报红，见 main）：
      * `foldCovered`：「折叠已覆盖」形态 —— 进度类 + 外键 + 前置已解析 +
        flags 只允许 OR + cmp∈{0,1} + 运算符 ∈ 1..5。这些**本应已折叠收进门槛**；
        还出现在 pending 里 ⇒ 数据管线退化（扫描没重跑 / 折叠逻辑坏了）。
      * `uncovered`：「折叠管不到」形态 —— flags 非 OR（别名 / GLOB / Pack Data /
        交换主客体）或 cmp∉{0,1}：与运算符无关，属后续阶段（GLOB/别名）的对象。
    """
    per_class: collections.Counter = collections.Counter()
    per_master: dict[str, dict] = {}
    fold_covered: list[str] = []
    uncovered: list[str] = []
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
            cmpv = g["cmp"]
            shape = f"{OPS.get(op, op)}/flags=0x{fl:02X}/cmp={cmpv}"
            cls = (g["reason"], "前置已解析" if g.get("resolved") else "前置未解析",
                   "表内" if it else "表外")
            hist[cls] += 1
            per_class[cls] += 1
            row = (f"{g['questEDID']}({sm}) {g['func']} "
                   f"pre={g.get('preEDID') or hex(g.get('pre', 0))} "
                   f"{shape} reason={g['reason']}")
            if it:
                in_table_rows.append(row)
            resolved = bool(g.get("resolved"))
            if resolved and (fl & ~0x01) == 0 and cmpv in (0.0, 1.0) and op in (1, 2, 3, 4, 5):
                fold_covered.append(row + ("  ← 表内！数据管线疑似退化" if it else ""))
            elif resolved and ((fl & ~0x01) != 0 or cmpv not in (0.0, 1.0)):
                uncovered.append(row + ("  ← 表内！后续阶段对象" if it else ""))
        per_master[sm] = {"file": fn, "total": len(d["pending"]),
                          "classes": {"/".join(k): v for k, v in hist.items()}}
    # ★ perClass 用**元组键**（打印时按下标取列）；写 JSON 时再 join（见 main）。
    return {"perMaster": per_master, "perClass": dict(per_class),
            "inTableRows": in_table_rows, "foldCovered": fold_covered,
            "uncovered": uncovered}


def record_scan() -> dict:
    """记录级（QUST CTDA）结构扫描：表内任务的「进度类外键」条件形态。

    复用 `_tmp_r109_rec_ctda_scan.py` 的定位规则（记录级条件 = 第一条 INDX/ALST 之前的
    CTDA 段）—— 实测 FFConstantZ06 四次条件逐条与文档一致（4 条）。这里只统计。

    ★★★ 第 128 轮：除「可门槛形态」（`gateableShapes`：flags⊆OR + cmp∈{0,1}）外，
    另记「**折叠管不到**」的形态（`uncoveredShapes`：flags 非 OR / cmp∉{0,1}）——
    后者是「后续阶段（GLOB / 别名）」的对象，表内出现就该有人看一眼（本轮实测 0 条）。
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
        uncov: collections.Counter = collections.Counter()
        uncov_samples: list[str] = []
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
                                cmptxt = "cmp∈{0,1}" if cmpv in (0.0, 1.0) else f"cmp={cmpv}"
                                shape = f"{OPS.get(op, op)}/flags=0x{fl:02X} {cmptxt}"
                                gateable = (fl & ~0x01) == 0 and cmpv in (0.0, 1.0)
                                if gateable:
                                    hist[f"{OPS.get(op, op)}/flags=0x{fl:02X}"] += 1
                                    if (m, local) in in_table and len(samples) < 20:
                                        samples.append(
                                            f"{edid}(0x{local:06X}) {gate_funcs[func]} "
                                            f"pre=0x{p1 & 0xFFFFFF:06X} cmp={cmpv} {shape}")
                                else:
                                    # ★ 第 128 轮：折叠管不到的形态（flags / cmp）——
                                    #   记录级里若有，就是「后续阶段」的对象。
                                    uncov[shape] += 1
                                    if (m, local) in in_table and len(uncov_samples) < 20:
                                        uncov_samples.append(
                                            f"{edid}(0x{local:06X}) {gate_funcs[func]} "
                                            f"pre=0x{p1 & 0xFFFFFF:06X} {shape}")
                        p += 24 + size
                    break
            finally:
                mm.close()
        out[m] = {"questsWithRecordCond": n_quest, "progressConds": n_ctda,
                  "gateableShapes": dict(hist), "inTableSamples": samples,
                  "uncoveredShapes": dict(uncov),
                  "inTableUncoveredSamples": uncov_samples}
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true",
                    help="tripwire：折叠已覆盖仍 pending / 折叠管不到的形态在表内 ⇒ 退出码 1")
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
    out("=== INFO 侧「进度类外键、不可门槛」按 (原因 / 前置 / 表内) 分类"
        "（5 个 master：Starfield + 4 个 DLC）===")
    for k, v in sorted(pend["perClass"].items(), key=lambda kv: (-kv[1], kv[0])):
        out(f"  {k[0]:<26} {k[1]:<8} {k[2]:<6} {v}")
    out("")
    out(f"表内条目 {len(pend['inTableRows'])} 条（明细）：")
    for s in pend["inTableRows"]:
        out("  · " + s)
    out("")
    out(f"折叠已覆盖形态 {len(pend['foldCovered'])} 条（`!=`/`>`/`>=`/`<`/`<=` + cmp∈{{0,1}}"
        f" + 前置已解析 —— 第 128 轮起应已被折叠收进门槛；标「表内」= 数据管线疑似退化）：")
    for s in pend["foldCovered"]:
        out("  · " + s)
    out("")
    out(f"折叠管不到的形态 {len(pend['uncovered'])} 条（flags 非 OR / cmp∉{{0,1}} —— "
        f"与运算符无关，属后续阶段；标「表内」= 后续阶段对象）：")
    for s in pend["uncovered"]:
        out("  · " + s)

    report = {
        "_why": ("第 109 轮（大项 B）+ 第 128 轮（operator 二期）：门槛覆盖盘点 —— "
                 "折叠落地后还有多少可收（结论：表内 0 条）"),
        "tableRows": n_rows,
        "infoGates": {"tasks": n_info_tasks, "groups": n_info_groups, "conds": n_info_conds},
        "recordGates": {"fileTasks": n_ctda_tasks, "fileConds": n_ctda_conds,
                        "inTableTasks": in_table_gate_tasks,
                        "inTableConds": in_table_gate_conds},
        "infoPending": {**pend,
                        "perClass": {"/".join(k): v for k, v in pend["perClass"].items()}},
        "conclusion": ("第 128 轮把 `!=`/`>`/`>=`/`<`/`<=` 折叠产品化（tools/esm/ctda_ops.py）"
                       "后，表内任务上仍无可收对象：12 条 pending 全部因「同组含自引用/"
                       "非进度类条件」放弃（与运算符无关）；7 条运算符形态都在非表内任务上"
                       "（折叠已收，表内零变化）；记录级表内 11 条已全是 `==`。"),
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
            out(f"      折叠管不到的形态 {d['uncoveredShapes']} / "
                f"表内样本 {len(d['inTableUncoveredSamples'])} 条")
            for s in d["inTableUncoveredSamples"]:
                out("      ! " + s)
        out(f"（记录级明细另存 {rec_path}）")

    if a.check:
        # tripwire 只读：不写报告（避免把完整报告覆盖成精简版）。
        # ★★★ 第 128 轮：报红条件换成两类（见文件头注释）——
        #   ① 折叠已覆盖却仍 pending（表内）⇒ 扫描没重跑 / 折叠退化；
        #   ② 折叠管不到的形态在表内 ⇒ 后续阶段（GLOB / 别名）的对象。
        stale = [s for s in pend["foldCovered"] if "表内" in s]
        uncovered = [s for s in pend["uncovered"] if "表内" in s]
        if stale:
            print(f"[tripwire] 表内出现 {len(stale)} 条「折叠已覆盖」形态（应已被收进门槛）⇒ "
                  f"数据管线疑似退化：重跑 scan_info_gates.py；折叠规则见 docs/08 4.7：")
            for s in stale:
                print("  " + s)
            return 1
        if uncovered:
            print(f"[tripwire] 表内出现 {len(uncovered)} 条「折叠管不到」形态（flags/cmp）⇒ "
                  f"后续阶段对象（GLOB / 别名 解析）：")
            for s in uncovered:
                print("  " + s)
            return 1
        print("[tripwire] OK：表内任务没有漏收的进度类外键条件"
              "（折叠已覆盖；flags/cmp 形态在表内也是 0 条）")
        return 0

    Path(a.out).write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    txt = Path(a.out).with_suffix(".txt")
    txt.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"\nwrote {a.out} / {txt}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
