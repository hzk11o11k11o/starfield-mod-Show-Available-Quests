#!/usr/bin/env python3
"""analyze_info_gates.py - 对话侧「进度门槛」的正式数据生成（★★ 第 78 轮：扩到 DLC）。

数据来源（scan_info_gates.py 逐 master 扫描的产物）：
    ref/info_gates.json                 基础游戏（Starfield.esm）
    ref/info_gates_sfbgs003.json        SFBGS003.esm（追踪者联盟 · ★ 第 110 轮）
    ref/info_gates_sfbgs00d.json        SFBGS00D.esm（自由航道更新）
    ref/info_gates_sfbgs050.json        SFBGS050.esm（地球舰队）
    ref/info_gates_shatteredspace.json  ShatteredSpace.esm（破碎空间）
（缺哪个就跳过哪个；第 78 轮之前只做基础游戏 —— DLC 的对话条件没扫 ⇒ DLC 任务
 一条 INFO 门槛都没有 ⇒ 后续环节照常冒出来。）

判据（保守，误藏最小化 —— 设计依据见 docs/08 与 docs/05 第二十二节）：
  * 任务的对话挂在它自己的 QUST children 组下；「任务运行中」的对话不能用来
    判定「能不能接到」 ⇒ **排除「推进类」**（条件组里含「自引用」（折叠后）want=1
    的 INFO —— ★ 第 128 轮起方向按**运算符折叠结果**读，见 scan_info_gates.py）。
  * 参与判定的 INFO = **入口类**（含「自引用」want=0：任务还没开始时才出现的对话）
    + **中性类**（无自引用）。两档都只取「引用别的任务」的进度条件（want 0/1，
    ★ 第 128 轮起 want = 折叠结果 —— `!=` / `>=` 等运算符同样收）。
  * **任务的每条参与判定 INFO 都必须有非空条件集**，否则整条任务不进表（保守）。
  * 运行时判据（DLL）：**全部参与判定的 INFO 都至少有「一条已知为假」的条件 ⇒ 隐藏**
    （任一 INFO 的条件全为真/不可判定 ⇒ 可能可用 ⇒ 显示）。
    「成对条件」（如 X==0 / X==1 各有一条 INFO）会自动豁免 —— 验证例：
    Com_Companion_Barrett（不隐藏）、大器晚成 / 亲爱的姐妹（与记录级 gate 一致）。
  * 前置任务的 master 用**表里的 master 顺序**（kQuestMasters：Starfield.esm 永远排 0，
    其余按名字排序）——与 gen_quest_table.py 的 master_idx 完全一致。

用法：
    python tools/esm/analyze_info_gates.py          # 写 ref/info_gates_final.json
"""
from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
REF = ROOT / "ref"

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ALLOWED_KINDS = ("入口", "中性")
FUNC_TO_CHECK = {"GetQuestRunning": 0, "GetQuestCompleted": 1, "GetStageDone": 2}

# ★★ 第 78 轮：四个 master 的扫描产物（缺文件 ⇒ 跳过）
# ★★★ 第 110 轮：+ 追踪者联盟（SFBGS003.esm，medium 档）
SCAN_FILES = (
    "info_gates.json",
    "info_gates_sfbgs003.json",
    "info_gates_sfbgs00d.json",
    "info_gates_sfbgs050.json",
    "info_gates_shatteredspace.json",
)


def main() -> int:
    table = json.loads((REF / "quest_table_debug.json").read_text(encoding="utf-8"))

    # master 顺序与 gen_quest_table.py 一致：Starfield.esm 永远排 0，其余按名字排序
    masters = sorted({(q.get("master") or "Starfield.esm") for q in table},
                     key=lambda m: (m.lower() != "starfield.esm", m.lower()))
    master_idx = {m.lower(): i for i, m in enumerate(masters)}
    print(f"master 顺序：{masters}")

    # (master 小写, 记录号) -> {info -> [条件]}   —— 目标任务是本 DLC 自己的记录
    per_quest: dict[tuple[str, int], dict[int, list]] = defaultdict(dict)
    n_gate_raw = 0
    for fn in SCAN_FILES:
        p = REF / fn
        if not p.exists():
            print(f"  （没有 {fn} —— 跳过）")
            continue
        raw = json.loads(p.read_text(encoding="utf-8"))
        self_master = (raw.get("selfMaster") or "Starfield.esm").lower()
        n_used = 0
        for g in raw["gates"]:
            if g["kind"] not in ALLOWED_KINDS:
                continue
            if g["want"] not in (0, 1):
                continue
            if g["func"] not in FUNC_TO_CHECK:
                continue
            key = (self_master, int(g["quest"]) & 0xFFFFFF)
            per_quest[key].setdefault(g["info"], []).append(g)
            n_used += 1
        n_gate_raw += n_used
        print(f"  {fn}: 参与判定的条件 {n_used} 条 / 任务 {len({k for k in per_quest})} 条（累计）")

    out = []
    n_skipped_empty = 0
    for q in table:
        master = (q.get("master") or "Starfield.esm").lower()
        infos = per_quest.get((master, int(q["local"]) & 0xFFFFFF))
        if not infos:
            continue
        if not all(v for v in infos.values()):
            n_skipped_empty += 1
            continue
        ser = []
        for info_id, conds in sorted(infos.items()):
            # ★ 第 106 轮（operator 全量产品化）：条件可以带 OR 位（scan_info_gates.py
            #   已按引擎 OR 组语义提取 —— 组内相互 OR、组作为整体 AND，见 docs/08 4.3）。
            #   这里按同样的组结构转写；再做一次「前置 master 能否解析」的保险：
            #   **组里任一条解析不了 ⇒ 整组不参与判定**（半组会把 OR 语义算错）。
            def make_cond(c):
                pre_master = (c.get("preMaster") or "Starfield.esm").lower()
                if pre_master not in master_idx:
                    return None  # 前置在表里没有 master（无法解析）
                return {
                    "func": FUNC_TO_CHECK[c["func"]],
                    "quest_master": master_idx[pre_master],
                    "quest_local": int(c["pre"]) & 0xFFFFFF,
                    "want": int(c["want"]),
                    "stage": int(c.get("stage", 0)) & 0xFFFF,
                    "or_bit": int(c.get("orBit", 0)),
                }

            cs = []
            i, n = 0, len(conds)
            while i < n:
                if not conds[i].get("orBit"):
                    ci = make_cond(conds[i])
                    if ci:
                        cs.append(ci)
                    i += 1
                    continue
                j = i
                while j < n and conds[j].get("orBit"):
                    j += 1
                if j < n:
                    j += 1   # 含关闭组的那个条件（第一条无 OR 位）
                grp = [make_cond(x) for x in conds[i:j]]
                if all(grp):
                    cs.extend(grp)
                i = j
            if not cs:
                continue
            ser.append({"info": info_id, "conds": cs})
        if not ser:
            continue
        out.append({
            "formid": q["formid"],
            "master": q.get("master") or "Starfield.esm",
            "edid": q["edid"],
            "nameZh": q.get("name_zh"),
            "infos": ser,
        })

    total_conds = sum(len(i["conds"]) for t in out for i in t["infos"])
    per_master_n = defaultdict(int)
    for t in out:
        per_master_n[t["master"]] += 1
    print(f"\nINFO 门槛：{len(out)} 条任务 / "
          f"{sum(len(t['infos']) for t in out)} 条参与判定的对话 / {total_conds} 条条件")
    print("按 master：" + " ".join(f"{m}={n}" for m, n in sorted(per_master_n.items())))
    print(f"（另有 {n_skipped_empty} 条任务因「存在无条件的参与对话」被保守跳过）")
    for t in out:
        print(f"  {t['nameZh'] or t['edid']:<24} [{t['edid']:<34} "
              f"0x{t['formid']:06X}] {len(t['infos'])} 条对话")

    path = REF / "info_gates_final.json"
    path.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\nwrote {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
