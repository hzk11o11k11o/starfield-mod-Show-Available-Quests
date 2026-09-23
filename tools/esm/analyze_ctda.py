#!/usr/bin/env python3
"""analyze_ctda.py - 第 35 轮：「进度没到不显示」——解析 QUST 记录级条件（CTDA）。

数据来源：
  ref/quests.json         quest_dump.py 产物（原始 CTDA 字节 hex，按文件顺序）
  ref/quests_parsed.json  parse_xedit_dump.py 产物（xEdit 解码后的字段名/函数名）
  ref/quest_table_debug.json  候选表（261 条）

做法：
  1. 原始 32 字节 CTDA 按实测布局解析（Skyrim 风格，已用 FFConstantZ06 对照验证）：
       0   u8   operator/flag（0x00=等于 …；0x01 位用途见 docs/08）
       4   f32  comparison value
       8   u16  function index
       10  u16  （xEdit "Unused"，f9 44 常见）
       12  u32  parameter #1
       16  u32  parameter #2
       20  u32  run on（0=Subject）
       24  u32  reference
       28  i32  parameter #3（多为 -1，GetStageDone 里是 stage 名索引？）
  2. 与 xEdit 解码的「记录级条件」按顺序配对 ⇒（函数索引 ↔ 函数名）对照表。
  3. 统计候选任务的条件「可求值性」（保守子集见下）。

保守求值子集（DLL 侧准备实现）：
    GetQuestCompleted / GetQuestRunning / GetStageDone / GetStage /
    GetGlobalValue / GetInFaction
  其余函数（LocationHasKeyword / BiomeSupportsCreature / IsTrueForConditionForm /
  GetIsID / GetIsVoiceType / GetBodySurveyPercent / GetRandomPercent …）依赖
  运行时上下文（event data / body / 当前地点），本阶段**不求值 ⇒ 放行**。

★ 第 35 轮定案：真正拿来做「进度没到不显示」的判据叫 **gate（进度门槛）**，
  比「可有条件」更窄、更安全（--gates 输出 ref/ctda_gates.json）：
    * ★★ 第 87 轮（第 86 轮反汇编实证，见 docs/08 4.3）：type 按位域解析 ——
      flags = type & 0x1F **只允许 OR 位（0x01）**，其余（别名 / GLOB / Pack Data /
      交换主客体）一律放行；OR 位条件按**引擎的 OR 组语义**成组处理（build_gates：
      组内 OR、组间 AND；组里有一条不能当门槛 ⇒ 整组放弃）；
    * ★★★ 第 128 轮（**operator 二期**）：运算符（type >> 5）全解 —— `!=` / `>` /
      `>=` / `<` / `<=` 在 cmp∈{0,1} 下交给 `ctda_ops.fold_operator` 精确折叠
      （want / 恒真 / 恒假），组级处置见 `build_gates` 与 `tools/esm/ctda_ops.py`
      头注释（真值表 + 有自检）。折叠不改动运行时（`want` 本来就是生成期字段）。
    * ★★★★ 第 145 轮（**operator 三期**）：cmp 不再限定 {0,1}（任意数值常量可精确折叠）；
      type 解析改回**低字节**（+0 的 4 字节里只有低字节是 type —— 见 parse_ctda）；
      仍放行的只剩 flags 非 OR（别名 / GLOB / Pack Data / 交换主客体）。
    * Run On == Subject
    * 函数是 GetQuestRunning / GetQuestCompleted / GetStageDone 之一
    * 比较值 ∈ {0.0, 1.0}
    * **引用的是「别的任务」**（p1 != 自己）——
      对 self 的条件（GetQuestRunning(自己)==0 之类）是引擎启动流程的防重入守卫，
      **不是**进度门槛（第 11 轮的教训：RAD05「全数到期」引擎提前 started、
      条件为假，但玩家仍能接到 ⇒ 用 self 条件过滤会误伤）
  任务的全部 gate 都为真 ⇒ 显示；任一为假 ⇒ 隐藏（进度没到）；
  没有 gate ⇒ 不做条件过滤。

用法：
    python tools/esm/analyze_ctda.py                 # 统计 + 写 ref/ctda_parsed.json
    python tools/esm/analyze_ctda.py --task FFConstantZ06
    python tools/esm/analyze_ctda.py --funcs         # 只打函数索引↔名字对照
"""
from __future__ import annotations

import argparse
import json
import re
import struct
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import ctda_ops  # noqa: E402  （第 128 轮 · operator 二期：运算符折叠内核）

ROOT = Path(__file__).resolve().parents[2]
REF = ROOT / "ref"

# Windows 控制台默认 GBK：输出里有 \u2194 之类的字符会 UnicodeEncodeError
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# 保守求值子集（DLL 侧可安全求值）
SUPPORTED = {
    "GetQuestCompleted",
    "GetQuestRunning",
    "GetStageDone",
    "GetStage",
    "GetGlobalValue",
    "GetInFaction",
}

# gate（进度门槛）支持的函数 → DLL 侧枚举值
GATE_FUNCS = {
    "GetQuestRunning": 0,
    "GetQuestCompleted": 1,
    "GetStageDone": 2,
}

FORMID_RE = re.compile(r"\[(?:QUST|NPC_|KYWD|GLOB|FACT|CNDF|LCRT|FLST)?:?([0-9A-F]{8})\]")


def cond_to_gate(c: dict, self_formid: int) -> dict | None:
    """一条 CTDA 能否作为「进度门槛」以及它的**折叠结果**。不能则返回 None。

    ★★ 第 87 轮：type 按位域解析（第 86 轮反汇编实证，见 docs/08 4.3）——
      运算符 = type >> 5、flags = type & 0x1F；flags **只允许 OR 位（0x01）**，
      其余（别名 / GLOB / Pack Data / 交换主客体）仍一律放行。
    ★★★ 第 128 轮（operator 二期）：运算符不再限定 `==` —— 交给折叠内核
      `ctda_ops.fold_operator`（真值表 + 组语义见该文件；`!=` / `>` / `>=` / `<` / `<=`
      在 cmp∈{0,1} 下都能精确折叠）。返回 dict 的 `fold` ∈
      `("want", 0|1)` / `("const", True|False)`；常量的组级处置见 `build_gates`。
    ★★★★ 第 145 轮（operator 三期）：**cmp 不再限定 {0,1}** —— 任意数值常量都交内核
      精确折叠（`== 1510` 之类 ⇒ 恒假 ⇒ 保守处置；见 docs/08 4.8）。唯一例外 =
      flags bit2（GLOB 比较值：cmp 字段是 FormID，需运行期读 `TESGlobal::value`）——
      表内外当前 0 条外键形态 ⇒ 不实现（放行 + tripwire 盯着）。
    """
    t = c.get("op", 0)
    op, flags = t >> 5, t & 0x1F
    if flags & 0x04:                        # ★ 第 145 轮：GLOB 比较值（cmp 是 FormID）放行
        return None
    if flags & ~0x01:                       # 其余 flags（别名 / Pack Data / 交换主客体）放行
        return None
    if c.get("runOn") != 0:                 # Run On 必须是 Subject
        return None
    name = c.get("name")
    if name not in GATE_FUNCS:
        return None
    # ★ 第 145 轮：cmp 由内核判定（任意数值常量可折叠；NaN ⇒ None）
    cmpv = c.get("cmp")
    p1 = c.get("p1", 0)
    if p1 == self_formid:                   # 自引用 = 启动守卫，不是进度门槛
        return None
    if (p1 >> 24) != 0:                     # 只支持 base 游戏空间（Starfield.esm）的引用
        return None
    # ★ 第 145 轮：cmp∉{0,1}（任意数值常量）也交给内核折叠（NaN ⇒ 内核返回 None）
    folded = ctda_ops.fold_operator(op, cmpv)
    if folded is None:                      # 运算符越界 / cmp 是 NaN（理论上不出现）
        return None
    return {
        "fold": folded,                     # ("want", 0|1) / ("const", True|False)
        "name": name,
        "quest_master": 0,                  # 目前全部是 Starfield.esm（kQuestMasters[0]）
        "quest_local": p1 & 0xFFFFFF,
        "stage": (c.get("p2", 0) & 0xFFFF) if name == "GetStageDone" else 0,
        "or_bit": 1 if (flags & 0x01) else 0,   # ★ 第 87 轮：OR 位（组语义见 build_gates）
    }


def build_gates(conds: list, self_formid: int) -> list:
    """把一条任务的**全部条件**转成门槛列表（按引擎的 OR 组语义 + 折叠规则）。

    ★★ 第 87 轮（引擎算法见 docs/08 4.3）：OR 位标记「**开始一个 OR 组**」——
      组 = 从带 OR 位的那条起，直到**第一条不带 OR 位的条件**（含）或列表末尾；
      组内条件相互 OR、组作为整体 AND；无 OR 位的独立条件各自 AND。

    ★★★ 第 128 轮：组语义与**常量 / 不可折叠的处置**统一由 `ctda_ops.assemble_gates`
      给出（一条真相源，有自检）—— 概览：
        * 独立条件：不可门槛 ⇒ 丢弃（放行）；恒真 ⇒ 丢弃（无约束）；恒假 ⇒ 丢弃（放行）；
        * OR 组：任一成员不可门槛 / 恒假 ⇒ 整组放弃；任一成员恒真 ⇒ 整组丢弃；
          全部是 `want` ⇒ 整组保留（顺序与 OR 位不动）。
      保守底线与旧实现一致：**绝不引入误藏**。
    """
    raw = [cond_to_gate(c, self_formid) for c in conds]
    or_bits = [bool(c.get("op", 0) & 0x01) for c in conds]
    folds = [r["fold"] if r else None for r in raw]
    gates: list = []
    for idx, want in ctda_ops.assemble_gates(folds, or_bits):
        r = raw[idx]
        gates.append({
            "func": GATE_FUNCS[r["name"]],
            "name": r["name"],
            "want": want,                   # 1 = 「应为真」，0 = 「应为假」（折叠结果）
            "quest_master": r["quest_master"],
            "quest_local": r["quest_local"],
            "stage": r["stage"],
            "or_bit": r["or_bit"],
        })
    return gates


def parse_ctda(raw_hex: str) -> dict:
    b = bytes.fromhex(raw_hex)
    if len(b) < 32:
        return {"raw": raw_hex, "len": len(b)}
    # ★★★ 第 145 轮（operator 三期）：type 只取 **低字节** —— 数据侧取证（docs/08 4.8）：
    #   CTDA 的 +0 是 4 字节 = 低字节 type（运算符 = type >> 5、flags = type & 0x1F）
    #   + 高 3 字节 unused；stage / log entry 条件的 unused 非零（实测 300 条，如 55 4C 4C），
    #   第 87 轮起的「读 u32」把它们算成越界运算符（方向保守，但统计失真、且漏收）。
    #   低字节读法与第 86 轮反汇编一致（`and byte [rcx+0x38], 0x1f` —— type 是字节）。
    op = struct.unpack_from("<I", b, 0)[0] & 0xFF
    cmp_val = struct.unpack_from("<f", b, 4)[0]
    func = struct.unpack_from("<H", b, 8)[0]
    p1 = struct.unpack_from("<I", b, 12)[0]
    p2 = struct.unpack_from("<I", b, 16)[0]
    runon = struct.unpack_from("<I", b, 20)[0]
    ref = struct.unpack_from("<I", b, 24)[0]
    p3 = struct.unpack_from("<i", b, 28)[0]
    return {
        "op": op,
        "cmp": round(cmp_val, 6),
        "func": func,
        "p1": p1,
        "p2": p2,
        "runOn": runon,
        "ref": ref,
        "p3": p3,
        "len": len(b),
    }


def formid_of(xedit_param: str) -> int | None:
    m = FORMID_RE.search(xedit_param)
    if m:
        return int(m.group(1), 16)
    return None


def load():
    quests = json.loads((REF / "quests.json").read_text(encoding="utf-8"))
    parsed = json.loads((REF / "quests_parsed.json").read_text(encoding="utf-8"))
    return quests, parsed


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--task", default=None, help="只看某任务的解析结果（EDID 子串）")
    ap.add_argument("--funcs", action="store_true", help="只打函数索引↔名字对照")
    ap.add_argument("--json", default=str(REF / "ctda_parsed.json"))
    a = ap.parse_args()

    # ★ 独立于表生成物：以 quests_parsed.json（xEdit 解码）为准、quests.json（原始字节）配对。
    #   （早期版本用 quest_table_debug.json 限定候选 —— 那会造成「生成器 ↔ 分析器」循环依赖。）
    quests, parsed = load()
    raw_by_fid = {q["formid"]: q for q in quests}

    func_names: dict[int, Counter] = defaultdict(Counter)   # index -> {name: n}
    op_counter = Counter()
    runon_counter = Counter()
    out = []

    for p in parsed:
        fid = int(p["formid"], 16)
        r = raw_by_fid.get(fid)
        if not r:
            continue
        rc = p.get("record_conditions") or []
        raws = r.get("ctda") or []
        conds = []
        for i, xc in enumerate(rc):
            if i >= len(raws):
                break
            pr = parse_ctda(raws[i])
            name = xc.get("Function", "?")
            pr["name"] = name
            pr["x_type"] = xc.get("Type")
            pr["x_runon"] = xc.get("Run On")
            func_names[pr.get("func", -1)][name] += 1
            op_counter[pr.get("op")] += 1
            runon_counter[xc.get("Run On")] += 1
            # 与 xEdit 的 Parameter #1 FormID 对照（校验解析正确性）
            xp1 = formid_of(xc.get("Parameter #1", ""))
            if xp1 is not None and xp1 != pr.get("p1"):
                pr["p1_mismatch"] = f"xedit=0x{xp1:08X}"
            conds.append(pr)
        if conds:
            supported = all(cc["name"] in SUPPORTED for cc in conds)
            gates = build_gates(conds, fid)     # ★ 第 87 轮：OR 组语义成组纳入
            out.append({
                "edid": p.get("edid"),
                "formid": fid,
                "master": r.get("master", "Starfield.esm"),
                "qtype": (p.get("qtyp") or "").split('"')[1] if '"' in (p.get("qtyp") or "") else p.get("qtyp"),
                "supported": supported,
                "gates": gates,
                "conditions": conds,
            })

    if a.funcs:
        for idx in sorted(func_names):
            names = ", ".join(f"{n}×{k}" for n, k in func_names[idx].most_common())
            print(f"  0x{idx:04X} ({idx:5d})  {names}")
        return 0

    if a.task:
        needle = a.task.lower()
        for t in out:
            if needle in t["edid"].lower():
                print(json.dumps(t, ensure_ascii=False, indent=1))
        return 0

    (REF / "ctda_parsed.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")

    # ★ 进度门槛（gate）：真正用来「进度没到不显示」的数据（gen_quest_table.py 读它）
    gates_out = [{"edid": t["edid"], "formid": t["formid"], "master": t["master"],
                  "gates": t["gates"]} for t in out if t["gates"]]
    (REF / "ctda_gates.json").write_text(
        json.dumps(gates_out, ensure_ascii=False, indent=1), encoding="utf-8")

    print(f"候选 261 条：带记录级条件 {len(out)} 条")
    sup = [t for t in out if t["supported"]]
    unsup = [t for t in out if not t["supported"]]
    print(f"  ├─ 条件全部在保守子集内（可求值）：{len(sup)} 条")
    print(f"  └─ 含不支持函数（放行）：{len(unsup)} 条")
    print("\n--- 可求值的任务（进度没到即隐藏的候选） ---")
    for t in sup:
        fns = [f"{c['name']}" for c in t["conditions"]]
        print(f"  {t['edid']:<34} {t['qtype']:<10} {' ; '.join(fns)}")
    print("\n--- 不支持 → 放行 ---")
    for t in unsup:
        fns = sorted({c["name"] for c in t["conditions"]})
        print(f"  {t['edid']:<34} {' ; '.join(fns)}")

    print(f"\n=== 进度门槛（gate）：{len(gates_out)} 条任务 ===")
    for t in gates_out:
        gs = []
        for g in t["gates"]:
            q = f"{g['name']}(0x{g['quest_local']:06X}"
            if g["name"] == "GetStageDone":
                q += f", stage {g['stage']}"
            q += f") == {g['want']}"
            if g.get("or_bit"):
                q += " [OR组开始]"
            gs.append(q)
        print(f"  {t['edid']:<34} {' AND '.join(gs)}")

    print("\n--- operator 字节分布 ---")
    for k, v in op_counter.most_common():
        print(f"  0x{k:02X}: {v}")
    print("\n--- Run On 分布 ---")
    for k, v in runon_counter.most_common():
        print(f"  {k}: {v}")
    print("\n--- 函数索引 ↔ 名字（出现过的） ---")
    for idx in sorted(func_names):
        names = ", ".join(f"{n}×{k}" for n, k in func_names[idx].most_common())
        print(f"  0x{idx:04X} ({idx:5d})  {names}")

    mism = [(t["edid"], cc.get("p1_mismatch"))
            for t in out for cc in t["conditions"] if cc.get("p1_mismatch")]
    if mism:
        print(f"\n⚠ p1 对照不一致 {len(mism)} 处（检查解析布局）：")
        for e, m in mism[:20]:
            print(f"  {e}: {m}")
    else:
        print("\np1 与 xEdit 对照：全部一致（布局解析正确）")
    print(f"\nwrote {a.json}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
