#!/usr/bin/env python3
"""survey_gate_coverage.py - 「进度没到不显示」的门槛覆盖盘点（第 109 轮 · 大项 B；
★★★ 第 128 轮随 **operator 二期**升级；★★★★ 第 145 轮随 **operator 三期**升级）。

背景（docs/99「下一步大项候选」第 ③ 项 / docs/08 4.3~4.8）：
  第 86 轮把 CTDA 的 operator 语义全解（运算符 = type >> 5、flags = type & 0x1F）；
  第 87/106 轮产品化到「`==` + OR 位」；第 128 轮把余下运算符（`!=` / `>` /
  `>=` / `<` / `<=`）折叠产品化；**第 145 轮把 cmp∉{0,1} 也折叠产品化**并使
  type 解析改回低字节（+0 的 4 字节里只有低字节是 type）——
  折叠后**只剩 flags 非 OR（GLOB / 别名 / Pack Data / 交换主客体）管不到**
  （表内外外键形态当前实测 0 条，见 docs/08 4.8）。

本工具回答：「数据侧还剩多少条能收？」并按 (原因 / 前置 / 表内/表外 / 运算符·flags) 摊开。
第 145 轮的两类判据（`--check` 的报红条件）：
  * **应已被折叠收进门槛却仍 pending**（进度类 + 外键 + 前置已解析 + flags 无 GLOB/别名/
    Pack/交换 + 折叠结果 = `want`）⇒ 说明**扫描没重跑 / 折叠逻辑退化**（数据管线问题）；
    ★ 折叠成常量（恒真/恒假）的条件被保守处置丢弃 —— pending 留痕是设计，不报红；
  * **折叠管不到的形态在表内**（flags 非 OR：GLOB 比较值 / 别名 / Pack / 交换）⇒
    「后续阶段」的对象（GLOB 需运行期读 TESGlobal；别名需解析别名表）。

结论（第 109 轮盘点 + 第 128 轮落地 + 第 145 轮普查的实测）：
  * 表内 12 条「OR 组放弃」的阻断项**不是运算符** —— 是同一组里混着
    **自引用条件**或**非进度类条件**（脚本/终端检查等）⇒ 整组放弃（三轮都一致）；
  * 运算符 / cmp∉{0,1} 形态全在**非表内**任务上 ⇒ 折叠收进门槛后对「可接任务列表」
    零影响（表内对象 = 0）；唯一表内样本 = SFTA00 的 `== 1510`（自引用 ⇒ 不算门槛）；
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
sys.path.insert(0, str(Path(__file__).parent))
import ctda_ops  # noqa: E402  （第 145 轮：tripwire 用折叠结果判「应收未收」）
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

#: ★ 第 145 轮：flags 非 OR 的四类（折叠管不到）—— 用于细分诊断文案
FLAG_NAMES = [(0x04, "GLOB 比较值"), (0x02, "别名位"), (0x08, "Pack Data"), (0x10, "交换主客体")]


def flags_reason(fl: int) -> str:
    names = [n for bit, n in FLAG_NAMES if fl & bit]
    return " / ".join(names) if names else f"flags=0x{fl:02X}"

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

    ★★★★ 第 145 轮（operator 三期）的两档判据（均只对**表内**报红，见 main）：
      * `foldCovered`：「应已被折叠收进门槛」形态 —— 进度类 + 外键 + 前置已解析 +
        flags 只允许 OR + 折叠结果 = `want`。这些**本应已折叠收进门槛**；还出现在
        pending 里 ⇒ 数据管线退化（扫描没重跑 / 折叠逻辑坏了）。
        （折叠成常量（恒真/恒假）的条件被保守处置丢弃 —— pending 留痕是设计，不报红。）
      * `uncovered`：「折叠管不到」形态 —— flags 非 OR（GLOB 比较值 / 别名 /
        Pack Data / 交换主客体）：属后续阶段的对象（GLOB 需运行期读 TESGlobal）。
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
            # ★★★★ 第 145 轮（operator 三期）：用折叠内核判「应收未收」——
            #   flags 非 OR ⇒ 折叠管不到（细分原因）；否则看折叠结果：
            #   want ⇒ 本应收进门槛（仍 pending = 管线退化）；常量 ⇒ 保守丢弃（设计）。
            #   ★ 组级阻断（reason 以「OR 组」开头：组内混着自引用 / 非进度类 ⇒ 整组
            #     放弃）是第 106/128 轮的设计行为（不倒半组）——不报红。
            if resolved and (fl & ~0x01) != 0:
                uncovered.append(f"{row} [{flags_reason(fl)}]"
                                 + ("  ← 表内！后续阶段对象" if it else ""))
            elif resolved and not str(g.get("reason", "")).startswith("OR 组"):
                fold = ctda_ops.fold_operator(op, cmpv)
                if fold and fold[0] == ctda_ops.WANT:
                    fold_covered.append(row + ("  ← 表内！数据管线疑似退化" if it else ""))
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
    后者是「后续阶段（GLOB / 别名）」的对象，表内出现就该有人看一眼。
    ★★★★ 第 145 轮（operator 三期）：
      * type 改读**低字节**（+0 的 4 字节里只有低字节是 type —— stage 条件的 unused 非零）；
      * masters 补 **SFBGS003**（第 110 轮新 master，此前记录级扫描漏了它）；
      * `gateableShapes` 改按「**折叠内核能折叠**」（cmp 任意数值常量 ✅）；
      * `uncoveredShapes` 按 flags 四类**细分**（GLOB / 别名 / Pack / 交换），实测表内 0 条。
    """
    import mmap
    import struct
    sys.path.insert(0, str(Path(__file__).parent))
    from esm_probe import subrecords  # noqa: E402

    data = Path(r"D:\SteamLibrary\steamapps\common\Starfield\Data")
    masters = ["Starfield.esm", "ShatteredSpace.esm", "SFBGS00D.esm", "SFBGS050.esm",
               "SFBGS003.esm"]  # ★ 第 145 轮补：第 110 轮新 master
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
                                    t = struct.unpack_from("<I", sp, 0)[0] & 0xFF
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
                                # ★ 第 145 轮：可收形态 = flags 无 GLOB/别名/Pack/交换
                                #   且折叠内核能吃下（cmp 任意数值常量 ✅ / NaN ❌）
                                foldable = ((fl & ~0x01) == 0
                                            and ctda_ops.fold_operator(op, cmpv) is not None)
                                if foldable:
                                    hist[f"{OPS.get(op, op)}/flags=0x{fl:02X}"] += 1
                                    if (m, local) in in_table and len(samples) < 20:
                                        samples.append(
                                            f"{edid}(0x{local:06X}) {gate_funcs[func]} "
                                            f"pre=0x{p1 & 0xFFFFFF:06X} cmp={cmpv} {shape}")
                                else:
                                    # ★ 第 145 轮：折叠管不到 —— 按 flags 四类细分
                                    why = (flags_reason(fl) if (fl & ~0x01)
                                           else "不可折叠（cmp 异常）")
                                    uncov[f"{shape} [{why}]"] += 1
                                    if (m, local) in in_table and len(uncov_samples) < 20:
                                        uncov_samples.append(
                                            f"{edid}(0x{local:06X}) {gate_funcs[func]} "
                                            f"pre=0x{p1 & 0xFFFFFF:06X} {shape} [{why}]")
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
    out(f"应已被折叠收进门槛的形态 {len(pend['foldCovered'])} 条（**独立条件**：运算符全解 +"
        f" cmp 任意数值常量 + 前置已解析 —— 第 145 轮起应已被收进门槛；标「表内」= "
        f"数据管线疑似退化；组级阻断（OR 组放弃）是设计行为、不计入）：")
    for s in pend["foldCovered"]:
        out("  · " + s)
    out("")
    out(f"折叠管不到的形态 {len(pend['uncovered'])} 条（flags 非 OR：GLOB / 别名 / Pack / 交换 —— "
        f"属后续阶段；标「表内」= 后续阶段对象）：")
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
        "conclusion": ("第 145 轮（operator 三期）把 cmp∉{0,1} 折叠产品化、并把 type 解析改回"
                       "低字节后，表内任务上仍无可收对象：pending 的阻断项全部是「同组含自引用/"
                       "非进度类条件」（与运算符 / cmp 无关）；运算符与 cmp 形态都在非表内任务上"
                       "（表内零变化）；记录级表内 11 条已全是 `==`，唯一特殊样本 = SFTA00 的"
                       "`== 1510`（自引用 ⇒ 不算门槛）。"),
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
        # ★★★★ 第 145 轮：报红条件三类（见文件头注释）——
        #   ① 应已被折叠收进门槛却仍 pending（表内）⇒ 扫描没重跑 / 折叠退化；
        #   ② 折叠管不到的形态在表内（flags 非 OR：GLOB / 别名 / Pack / 交换）⇒
        #     后续阶段对象；
        #   ③ 记录级记录文件（`*_record.json`，`--record-scan` 产物）里的表内 uncovered
        #     样本（若有）—— 记录级只有结构扫描能看见，靠定期重跑维护该文件。
        stale = [s for s in pend["foldCovered"] if "表内" in s]
        uncovered = [s for s in pend["uncovered"] if "表内" in s]
        rec_uncovered: list[str] = []
        rec_path = Path(a.out).with_name(Path(a.out).stem + "_record.json")
        if rec_path.exists():
            try:
                rec = json.loads(rec_path.read_text(encoding="utf-8"))
                for mname, d in rec.items():
                    for s in d.get("inTableUncoveredSamples", []):
                        rec_uncovered.append(f"{mname} {s}")
            except (ValueError, OSError):
                pass
        if stale:
            print(f"[tripwire] 表内出现 {len(stale)} 条「应已被折叠收进门槛」形态 ⇒ "
                  f"数据管线疑似退化：重跑 scan_info_gates.py；折叠规则见 docs/08 4.8：")
            for s in stale:
                print("  " + s)
            return 1
        if uncovered:
            print(f"[tripwire] 表内出现 {len(uncovered)} 条「折叠管不到」形态（flags 非 OR）⇒ "
                  f"后续阶段对象（GLOB / 别名 / Pack / 交换）：")
            for s in uncovered:
                print("  " + s)
            return 1
        if rec_uncovered:
            print(f"[tripwire] 记录级出现 {len(rec_uncovered)} 条「折叠管不到」形态（flags 非 OR）⇒ "
                  f"后续阶段对象（重跑 --record-scan 核对）：")
            for s in rec_uncovered:
                print("  " + s)
            return 1
        print("[tripwire] OK：表内任务没有漏收的进度类外键条件"
              "（折叠已覆盖；flags 非 OR 形态在表内也是 0 条）")
        return 0

    Path(a.out).write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    txt = Path(a.out).with_suffix(".txt")
    txt.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"\nwrote {a.out} / {txt}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
