#!/usr/bin/env python3
r"""golden_snapshot.py - 数据管线「黄金快照」（第 64 轮 · 大项 K）

用途：把**数据管线产物**的规范化内容钉成快照 ——
  · 谁改了生成脚本（tools/esm/*.py）或手改了产物，只要结果变了，这里就红；
  · 改动**是有意的** ⇒ `--update` 更新快照（快照文件进 git，diff 里能看到摘要变化，
    例如「候选 931 → 935」，便于审查）。

与其它测试的分工：
  · 本脚本（数据管线黄金快照）：产物**内容**稳定性（秒级、零游戏）；
  · plugin/tests（离线层单测）：决策**逻辑**（毫秒级、零游戏，见 run-decision-tests.ps1）；
  · tools/ui/verify_saq_build.py：产物**特征**（版本串 / 结构 / 部署一致性）；
  · harness（docs/09）：引擎**时序**（要开游戏）。
  管线真实重跑（fetch/gen 全链，3~6 分钟）不是本脚本的事 —— 先跑构建再跑这里即可：
  `& .\tools\build-saq.ps1` → `python tools\test\golden_snapshot.py`。

用法：
    python tools/test/golden_snapshot.py           # 校验（有变化 → 退出码 1）
    python tools/test/golden_snapshot.py --update  # 更新快照
    python tools/test/golden_snapshot.py --list    # 只看摘要（不校验）

规范化（对「内容」敏感、对「格式 / 注释」钝感）：
    · JSON   → 解析后 sort_keys + 紧凑分隔符再哈希（改缩进 / 键顺序不算变化）；
    · .h     → 去块注释与行注释、逐行 strip、去空行 再哈希（改注释不算变化）；
    · 其它   → 直接哈希原始字节（如 ESM）。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
SNAP = ROOT / "tools" / "test" / "golden" / "snapshots.json"

# 快照清单：(相对路径, 说明)。
# 产物由 tools/esm/ 的管线生成（见 docs/01；生成的表被 DLL 直接编译进去）。
ITEMS: list[tuple[str, str]] = [
    ("ref/ctda_gates.json", "进度门槛数据（analyze_ctda.py）"),
    ("ref/info_gates_final.json", "INFO 门槛数据（analyze_info_gates.py）"),
    ("ref/guide_targets.json", "引导目标候选池（gen_guide_targets.py）"),
    ("ref/entry_targets.json", "任务板入口表（gen_entry_table.py）"),
    ("ref/board_markers.json", "新建常驻 marker（create_board_markers.py）"),
    # ★★ 第 74 轮：同伴好感度任务（入口固定显示 + 后续启动边；gen_companion_quests.py）
    ("ref/companion_quests.json", "同伴好感度任务（gen_companion_quests.py）"),
    ("plugin/src/SAQ_QuestTable.h", "静态任务表（gen_quest_table.py，DLL 编译进去）"),
    ("plugin/src/SAQ_EntryTable.h", "入口条目表（gen_entry_table.py，DLL 编译进去）"),
    ("esm/SAQ_ShowAvailableQuests.esm", "代理任务 ESM（patch_saq_esm.py 等，幂等补丁）"),
]


def sha256_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def canonical_bytes(path: pathlib.Path) -> bytes:
    """把文件折算成「规范化字节」—— 见模块头注释。"""
    data = path.read_bytes()
    suf = path.suffix.lower()
    if suf == ".json":
        obj = json.loads(data.decode("utf-8-sig"))
        text = json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
        return text.encode("utf-8")
    if suf == ".h":
        text = data.decode("utf-8-sig")
        text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)   # 块注释
        text = re.sub(r"//[^\n]*", "", text)                # 行注释
        lines = [ln.strip() for ln in text.splitlines()]
        return "\n".join(ln for ln in lines if ln).encode("utf-8")
    return data


def summarize(rel: str, path: pathlib.Path) -> str:
    """给快照报告用的一行可读摘要（尽量从产物里取「实打实的数字」）。"""
    try:
        if not path.exists():
            return "（文件不存在）"
        if rel.endswith(".json"):
            obj = json.loads(path.read_text(encoding="utf-8-sig"))
            if rel.endswith("ctda_gates.json") and isinstance(obj, list):
                conds = sum(len(q.get("gates", [])) for q in obj)
                return f"任务 {len(obj)} / 条件 {conds}"
            if rel.endswith("info_gates_final.json") and isinstance(obj, list):
                infos = sum(len(q.get("infos", [])) for q in obj)
                conds = sum(len(i.get("conds", []))
                            for q in obj for i in q.get("infos", []))
                return f"任务 {len(obj)} / 对话 {infos} / 条件 {conds}"
            if rel.endswith("guide_targets.json") and isinstance(obj, dict):
                cands = sum(len(v.get("cands", [])) for v in obj.values())
                return f"任务 {len(obj)} / 候选 {cands}"
            if rel.endswith("entry_targets.json") and isinstance(obj, list):
                return f"条目 {len(obj)}"
            if rel.endswith("board_markers.json") and isinstance(obj, dict) and "markers" in obj:
                return f"marker {len(obj['markers'])}"
            if rel.endswith("companion_quests.json") and isinstance(obj, list):
                # ★★ 第 74 轮：同伴 / 任务数 + 入口（固定显示）与后续（链式门槛）的条数
                qs = [q for g in obj for q in g.get("quests", [])]
                n_pin = sum(1 for q in qs if q.get("pin"))
                return f"同伴 {len(obj)} / 任务 {len(qs)}（入口 {n_pin}）"
            return f"键 {len(obj)}" if isinstance(obj, dict) else f"条目 {len(obj)}"
        if path.suffix.lower() == ".h":
            text = path.read_text(encoding="utf-8-sig")
            names = {
                "kQuestTableSize": "任务",
                "kGuideCandidateCount": "候选",
                "kQuestCondCount": "进度门槛",
                "kInfoGroupCount": "INFO对话",
                "kInfoCondCount": "INFO条件",
                "kChainGateCount": "链式边",     # ★ 第 67 轮：任务链门槛
                "kEntryTableSize": "入口",
            }
            parts = []
            for nm, label in names.items():
                m = re.search(rf"{nm}\s*=\s*(\d+)", text)
                if m:
                    parts.append(f"{label} {m.group(1)}")
            if parts:
                return " / ".join(parts)
            return f"{len(text.splitlines())} 行"
        return f"{path.stat().st_size} B"
    except Exception as e:  # noqa: BLE001
        return f"（摘要失败：{e}）"


def build_current() -> dict:
    cur: dict = {}
    for rel, desc in ITEMS:
        p = ROOT / rel
        if not p.exists():
            cur[rel] = {"missing": True, "desc": desc}
            continue
        cur[rel] = {
            "desc": desc,
            "sha256": sha256_bytes(canonical_bytes(p)),
            "summary": summarize(rel, p),
        }
    return cur


def load_snap() -> dict:
    if not SNAP.exists():
        return {}
    return json.loads(SNAP.read_text(encoding="utf-8-sig"))


def save_snap(cur: dict) -> None:
    SNAP.parent.mkdir(parents=True, exist_ok=True)
    out = {
        "note": "数据管线黄金快照（tools/test/golden_snapshot.py 生成；有意的变更请 --update 并审查 diff）",
        "items": cur,
    }
    SNAP.write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    try:
        # 管道 / 重定向下也输出 UTF-8（调用方脚本按 UTF-8 解码；见 run-all-tests.ps1）
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        pass

    ap = argparse.ArgumentParser()
    ap.add_argument("--update", action="store_true", help="把当前产物写回快照")
    ap.add_argument("--list", action="store_true", help="只列摘要，不校验")
    a = ap.parse_args()

    cur = build_current()
    old = load_snap().get("items", {})

    if a.list:
        print("=== 数据管线黄金快照（当前产物摘要）===")
        for rel, _ in ITEMS:
            it = cur.get(rel, {})
            mark = "??" if it.get("missing") else "OK"
            print(f"  [{mark}] {rel:<40} {it.get('summary', '')}")
        return 0

    if a.update:
        save_snap(cur)
        print(f"快照已更新：{SNAP}")
        print("=== 摘要 ===")
        for rel, _ in ITEMS:
            it = cur.get(rel, {})
            before = old.get(rel, {}).get("summary", "（新）")
            print(f"  {rel:<40} {before}  →  {it.get('summary', '')}")
        return 0

    # 校验
    print("=== 数据管线黄金快照校验 ===")
    bad = 0
    for rel, desc in ITEMS:
        it = cur.get(rel, {})
        if it.get("missing"):
            print(f"  [SKIP] {rel}（文件不存在 —— 先跑构建生成产物）")
            bad += 1
            continue
        o = old.get(rel)
        if not o:
            print(f"  [NEW ] {rel} —— 快照里没有这一项（--update 收录）｜{it.get('summary', '')}")
            bad += 1
            continue
        if o.get("sha256") == it.get("sha256"):
            print(f"  [ OK ] {rel}｜{it.get('summary', '')}")
        else:
            print(f"  [DIFF] {rel} —— 内容变了！")
            print(f"         快照：{o.get('summary', '?')}")
            print(f"         现在：{it.get('summary', '?')}")
            print(f"         （若是有意改动：python tools/test/golden_snapshot.py --update，"
                  f"并在 git diff 里审查摘要变化）")
            bad += 1

    print()
    if bad == 0:
        print("全部一致。")
        return 0
    print(f"有 {bad} 项与快照不一致（或缺失）。")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
