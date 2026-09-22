#!/usr/bin/env python3
r"""survey_repeatable.py - 「可重复任务」全量盘点（第 89 轮）。

背景：玩家反馈「赛多尼亚的 Denis Averin 也给重复任务，为什么列表里没有他」。
调查（第 88 轮）发现「翻新商品」（FFCydoniaR02）是**可重复任务**
（`FFCydoniaR02_NumTimesCompleted` 计数器 + 故事事件启动），而第 80 轮的
「（可重复）NPC」条目只覆盖 RAD03/RAD04 两个**活动**的给定者 ⇒ 需要全量盘点
「游戏里所有可重复任务 + 它们的提供者」，再决定补法。

本工具（只读）：
  1. 扫官方 Papyrus 源码（Data/Scripts/Source，5000+ .psc），找「可重复」特征：
     * 完成次数计数器 GLOB（`*NumTimesCompleted` / `*TimesCompleted` / `*TimesDone`
       / `*TimesPlayed` / `*CompletedLimit` / `PlayerCompleted*` …）；
     * 任务重启（`*.Reset()`）；
     * 冷却（`SetCooldown` / `*Cooldown*`）；
  2. 扫「启动图」：`<Quest>.Start()` / `<Keyword>.SendStoryEvent()` 的调用点
     —— 用来找每个可重复任务的**提供者**（谁在哪个脚本里启动它）；
  3. 与 ESM 交叉（ref/quests_all.json + ref/quest_table_debug.json）：
     EDID / FormID / 类型 / 是否在当前任务表 / 引导候选数；
  4. 输出 ref/repeatable_survey.json（结构化）+ ref/repeatable_survey.txt（报告）。

用法：
    python tools/esm/survey_repeatable.py            # 扫描 + 报告
    python tools/esm/survey_repeatable.py --top 60   # 启动图多打几条
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
REF = ROOT / "ref"
SRC = Path(r"D:\SteamLibrary\steamapps\common\Starfield\Data\Scripts\Source")

# ---------------------------------------------------------------- 特征正则
COUNTER_RE = re.compile(
    r"\b([A-Za-z0-9_]*(?:NumTimesCompleted|TimesCompleted|NumTimesDone|TimesDone"
    r"|NumTimesPlayed|TimesPlayed|CompletedLimit|CompletionLimit"
    r"|PlayerCompleted[A-Za-z0-9_]*)[A-Za-z0-9_]*)\b")
START_RE = re.compile(r"\b([A-Za-z0-9_]+)\.Start\(\)")
STORY_RE = re.compile(r"\b([A-Za-z0-9_]+)\.SendStoryEvent\b")
COOLDOWN_RE = re.compile(r"\bSetCooldown\b")
RESET_RE = re.compile(r"\b([A-Za-z0-9_]+)\.Reset\(\)")

COUNTER_SUFFIXES = [
    "_NumTimesCompleted", "NumTimesCompleted", "_TimesCompleted", "TimesCompleted",
    "_NumTimesDone", "NumTimesDone", "_TimesDone", "TimesDone",
    "_NumTimesPlayed", "NumTimesPlayed", "_TimesPlayed", "TimesPlayed",
    "_CompletedLimit", "CompletedLimit", "_CompletionLimit", "CompletionLimit",
    "PlayerCompleted",
]
STORY_SUFFIXES = ["QuestStartKeyword", "StartQuestKeyword", "QuestKeyword", "StartKeyword", "Keyword"]

# 已知的「不是任务」的 Start()/Reset() 目标（场景/对话/别名/通用对象）——
# 名字对不上 ESM 任务的会自动过滤，这里只挡明显噪音。
NOISE_START = {"Scene", "SceneObject", "Fade", "Game", "Debug", "Utility"}


def strip_suffix(name: str, suffixes) -> str:
    for s in suffixes:
        if name.endswith(s) and len(name) > len(s):
            return name[: -len(s)].rstrip("_")
    return name


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--top", type=int, default=40)
    ap.add_argument("--src", default=str(SRC))
    a = ap.parse_args()
    src = Path(a.src)
    if not src.exists():
        print(f"!! Papyrus 源码目录不存在：{src}")
        return 1

    files = sorted(src.rglob("*.psc"))
    print(f"scan {src} ({len(files)} .psc) ...")

    counters: dict[str, set] = defaultdict(set)
    story_starts: dict[str, set] = defaultdict(set)   # keyword -> 发送者文件
    direct_starts: dict[str, set] = defaultdict(set)  # quest->  启动者文件
    cooldown_files: set[str] = set()
    resets: dict[str, set] = defaultdict(set)

    for p in files:
        try:
            txt = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        rel = str(p.relative_to(src)).replace("\\", "/")
        for m in COUNTER_RE.finditer(txt):
            counters[m.group(1)].add(rel)
        for m in STORY_RE.finditer(txt):
            story_starts[m.group(1)].add(rel)
        for m in START_RE.finditer(txt):
            t = m.group(1)
            if t not in NOISE_START:
                direct_starts[t].add(rel)
        if COOLDOWN_RE.search(txt):
            cooldown_files.add(rel)
        for m in RESET_RE.finditer(txt):
            resets[m.group(1)].add(rel)

    # ------------------------------------------------------------ ESM 交叉
    quest_by_edid: dict[str, dict] = {}
    if (REF / "quests_all.json").exists():
        for q in json.loads((REF / "quests_all.json").read_text(encoding="utf-8")):
            if q.get("edid"):
                quest_by_edid[q["edid"].lower()] = q
    in_table: dict[int, dict] = {}
    if (REF / "quest_table_debug.json").exists():
        for r in json.loads((REF / "quest_table_debug.json").read_text(encoding="utf-8")):
            in_table[r["formid"]] = r

    def match_quest(name: str) -> dict | None:
        n = name.lower()
        if n in quest_by_edid:
            return quest_by_edid[n]
        # 前缀/后缀关系（如 FFConstantR02Misc vs FFConstantR02）：只在唯一候选时接受
        cands = [e for e in quest_by_edid if e.startswith(n) or n.startswith(e)]
        if len(cands) == 1:
            return quest_by_edid[cands[0]]
        n2 = re.sub(r"[_-]?\d{1,2}$", "", n)
        if n2 and n2 != n and n2 in quest_by_edid:
            return quest_by_edid[n2]
        return None

    # ------------------------------------------------------------ 任务聚合
    def is_quest_name(name: str) -> bool:
        return match_quest(name) is not None

    tasks: dict[str, dict] = {}

    def slot(base: str) -> dict:
        if base not in tasks:
            tasks[base] = {"base": base, "counters": set(), "story": set(),
                           "directStartIn": set(), "resetIn": set(),
                           "cooldown": False, "files": set(), "quest": None}
        return tasks[base]

    for glb, fl in counters.items():
        base = strip_suffix(glb, COUNTER_SUFFIXES)
        # 只接受能对上 ESM 任务的 base（其余是噪音）
        if not is_quest_name(base):
            # 再试：把「计数器 GLOB 的完整名」当任务名的变体查一次
            if is_quest_name(glb):
                base = glb
            else:
                continue
        t = slot(base)
        t["counters"].add(glb)
        t["files"] |= fl

    for kw, fl in story_starts.items():
        base = strip_suffix(kw, STORY_SUFFIXES)
        if not is_quest_name(base):
            continue
        t = slot(base)
        t["story"].add(kw)
        t["files"] |= fl

    # 直接启动（`<Quest>.Start()`）：目标名必须能对上 ESM 任务
    for q, fl in direct_starts.items():
        if not is_quest_name(q):
            continue
        t = slot(q)
        t["directStartIn"] |= fl
        t["files"] |= fl

    for q, fl in resets.items():
        if not is_quest_name(q):
            continue
        t = slot(q)
        t["resetIn"] |= fl
        t["files"] |= fl

    for base, t in tasks.items():
        if t["files"] & cooldown_files:
            t["cooldown"] = True

    rows = []
    for base, t in sorted(tasks.items()):
        q = match_quest(base)
        t["quest"] = q
        row = {
            "base": base,
            "edid": q.get("edid") if q else "",
            "formid": q.get("local") if q else None,
            "master": q.get("master") if q else "",
            "counters": sorted(t["counters"]),
            "storyKeywords": sorted(t["story"]),
            "directStartIn": sorted(t["directStartIn"]),
            "resetIn": sorted(t["resetIn"]),
            "cooldown": t["cooldown"],
            "files": sorted(t["files"]),
            "inTable": None,
            "nameZh": "",
            "nameEn": "",
            "qtype": "",
            "candCount": None,
        }
        if q and q.get("local") is not None:
            tab = in_table.get(int(q["local"]) & 0xFFFFFF)
            if tab:
                row["inTable"] = True
                row["nameZh"] = tab.get("name_zh", "")
                row["nameEn"] = tab.get("name_en", "")
                row["qtype"] = tab.get("qtype", "")
                row["candCount"] = tab.get("cand_count", 0)
            else:
                row["inTable"] = False
        rows.append(row)

    # ------------------------------------------------------------ 报告
    lines: list[str] = []
    lines.append(f"PScript 文件 {len(files)}；计数特征 {len(counters)}；"
                 f"故事事件调用 {len(story_starts)}；直接 Start 调用 {len(direct_starts)}；"
                 f"有 SetCooldown 的文件 {len(cooldown_files)}")
    lines.append("")
    lines.append("=== A. 可重复任务（有计数器 / 冷却 / Reset / 故事事件）===")
    rep = [r for r in rows if (r["counters"] or r["cooldown"] or r["resetIn"]
                               or r["storyKeywords"]) and r["edid"]]
    rep.sort(key=lambda r: (not bool(r["counters"]), r["edid"]))
    for r in rep:
        ev = []
        if r["counters"]:
            ev.append("计数:" + "/".join(r["counters"]))
        if r["storyKeywords"]:
            ev.append("故事事件:" + "/".join(r["storyKeywords"]))
        if r["directStartIn"]:
            ev.append(f"直接Start×{len(r['directStartIn'])}")
        if r["resetIn"]:
            ev.append(f"Reset×{len(r['resetIn'])}")
        if r["cooldown"]:
            ev.append("冷却")
        tab = "表内" if r["inTable"] else ("表外" if r["inTable"] is not None else "?")
        lines.append(f"[{tab}] {r['edid']:32s} {r['nameZh'] or r['nameEn']:16s} "
                     f"{r['qtype']:10s} cand={str(r['candCount']):4s} | " + " ".join(ev))

    lines.append("")
    lines.append("=== B. 启动图（对话/场景/脚本 → 启动的任务）—— 「提供者」线索 ===")
    lines.append("（只列被启动任务能对上 ESM 的调用；TIF_* = 对话，SF_* = 场景）")
    starter_rows = []
    for base, t in sorted(tasks.items()):
        if not (t["directStartIn"] or t["story"]):
            continue
        q = t["quest"]
        if not q:
            continue
        starter_rows.append((q.get("edid") or base, sorted(t["files"])))
    for edid, fl in starter_rows:
        tifs = [f.split("/")[-1] for f in fl if "/TopicInfos/" in f]
        sfx = [f.split("/")[-1] for f in fl if "/Scenes/" in f]
        qfs = [f.split("/")[-1] for f in fl if "/Quests/" in f]
        others = [f for f in fl if "/TopicInfos/" not in f and "/Scenes/" not in f and "/Quests/" not in f]
        parts = []
        if tifs:
            parts.append(f"TIF×{len(tifs)}: " + ", ".join(tifs[:4]))
        if sfx:
            parts.append(f"SF×{len(sfx)}: " + ", ".join(sfx[:3]))
        if qfs:
            parts.append(f"QF×{len(qfs)}: " + ", ".join(qfs[:3]))
        if others:
            parts.append("其它: " + ", ".join(others[:3]))
        lines.append(f"{edid:32s} | " + " | ".join(parts))

    lines.append("")
    lines.append(f"=== C. 计数特征全名单（{len(counters)}，含未对上任务的）===")
    for glb, fl in sorted(counters.items()):
        lines.append(f"  {glb:52s} {len(fl)} file(s): " + ", ".join(sorted(fl)[:3]))

    (REF / "repeatable_survey.txt").write_text("\n".join(lines), encoding="utf-8")
    (REF / "repeatable_survey.json").write_text(
        json.dumps({"tasks": rows,
                    "stats": {"psc": len(files), "counters": len(counters),
                              "storyCalls": len(story_starts),
                              "startCalls": len(direct_starts),
                              "cooldownFiles": len(cooldown_files)}},
                   ensure_ascii=False, indent=1), encoding="utf-8")
    print("wrote ref/repeatable_survey.txt + .json")
    print(f"repeatable tasks: {len(rep)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
