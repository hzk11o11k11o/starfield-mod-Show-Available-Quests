#!/usr/bin/env python3
"""gen_faction_entry_quests.py - 第 75 轮：**四大势力开头任务表**（固定显示 + 固定排前四）。

起因（玩家要求，2026-09-21）：
  「把四大势力开头任务：联合殖民地（Supra et Ultra）/ 自由星游骑兵（Job Gone Wrong）/
    龙神工业（Back to the Grind）/ 深红舰队（Deep Cover）—— **固定显示**，并固定排在
    可接任务列表的前四个；除了深红舰队，其他都能正常引导（你可以二次确认）；深红舰队
    只保留简要说明，显示在左边说明里即可。」

四条任务 = 每条势力线的**第一环**（官方数据里就是各线的 01 号任务）：

| 势力（UI 枚举） | EDID  | 英文名            | 官方中文名 | 引导 |
| --- | --- | --- | --- | --- |
| 联合殖民地 UC Vanguard（1） | UC01 | Supra et Ultra     | 超越极限   | ✅ 图阿拉指挥官（MAST 大楼）+ 常驻 marker 兜底 |
| 自由星游骑兵（4）           | FC01 | Job Gone Wrong     | 枝节横生   | ✅ 盖尔银行（阿基拉城）的常驻 NPC 等 6 个候选 |
| 龙神工业（2）               | RI01 | Back to the Grind  | 重返职场   | ✅ 龙神集团总部（伊莫金·萨尔佐）+ 招聘亭常驻 marker |
| 深红舰队（5）               | CF01 | Deep Cover         | 深藏不露   | ❌ **故意不给引导**（见下） |

★ 请用**英文名 / EDID** 认任务：玩家给的对照表里 FC01 / RI01 的中文名是社区译名
  （出错的差事 / 重回正轨），游戏里显示的是官方本地化名（枝节横生 / 重返职场）——
  本工具从官方 strings 表取名字，不写死。

## 为什么「深红舰队」只给说明、不给引导
玩家原话：「深红舰队只保留简要说明，显示在左边说明里即可」。数据侧也支持这个决定：
CF01「深藏不露」的**唯一启动边**是 `UC02@860`（`QF_UC02_002B1808.psc:706`
里 `CF01.SetStage(205)` —— 先锋队线第二个任务收尾时图阿拉把你派去卧底）⇒ 玩家没做到
那里时，**没有任何可以「走进去接取」的地点**（它的候选是 CF 线中途才出现的 NPC）。
所以：`guide=false` ⇒ gen_quest_table.py 会**清空它的引导候选** ⇒ 界面侧走
「不可导航」通路（点击给提示 + 描述里写明原因），不会把玩家引到错误的地方。

## 产出 `ref/faction_entry_quests.json`（gen_quest_table.py 消费）

    [
      {
        "key": "UC01",
        "faction": 1,                       # 原版 UI 阵营枚举（FactionUtils 顺序）
        "nameZh": "联合殖民地先锋队", "nameEn": "UC Vanguard",
        "quest": {"edid": "UC01", "formid": 2905089, "local": 2905089,
                  "master": "Starfield.esm", "nameZh": "超越极限", "nameEn": "Supra et Ultra"},
        "guide": true,                      # 玩家要求：除深红舰队外都能正常引导
        "incoming": [],                     # 入边（空 = 这条就是该势力线的第一环）
        "noteZh": "加入联合殖民地先锋队：…",   # 「简要说明」（界面描述里显示）
        "noteEn": "Join the UC Vanguard: ...",
        "evidence": "…（启动边 / 引导候选的原始证据）"
      }, …
    ]

## 构建期核验（任一不符 ⇒ 不写产物、退出码 1）
① 四条任务都在 `ref/quests_all.json`（Starfield.esm）里，且**官方英文名与玩家给的
   对照表逐字一致**（拿 EDID 认任务，避免把中文社区译名当官方名）；
② 「第一环」结构性证据：UC01 / FC01 / RI01 在链式门槛数据（编号链 + 扩展边）里
   **没有任何入边**（不是任何任务的后续）；CF01 的入边恰好是 `UC02@860`
   （与「需先加入 UC 先锋队并完成其前两个任务」一致）；
③ `guide=true` 的三条在 `ref/guide_targets.json` 里**有引导候选**（并把首选候选
   名字打出来供人工二次确认 —— 玩家说「你可以二次确认」）；
④ 阵营枚举与静态表（`ref/quest_table_debug.json`）里的 faction 列一致；
⑤ 说明文本非空、无 Tab / 换行（会破坏载荷的列结构）、长度 ≤ 200 字符。

依赖缺失时（quests_all.json / chain / guide_targets 不在）：保留现有产物、跳过核验
（与 gen_quest_chain_extra.py / gen_companion_quests.py 同一约定）。

用法：
    python tools/esm/gen_faction_entry_quests.py          # 核验 + 写 ref/faction_entry_quests.json
    python tools/esm/gen_faction_entry_quests.py --list   # 只看当前产物
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
REF = ROOT / "ref"

# 四条（顺序 = 列表里的固定顺序；玩家要求「固定排在可接任务列表的前四个」）。
# expectedEn = 玩家对照表里的英文名（核验用：EDID ↔ 名字必须对上）。
ENTRIES: list[dict] = [
    {
        "key": "UC01",
        "faction": 1,                        # FactionUtils：1 = UnitedColonies
        "nameZh": "联合殖民地先锋队",
        "nameEn": "UC Vanguard",
        "expectedEn": "Supra et Ultra",
        "guide": True,
        "noteZh": "加入联合殖民地先锋队：前往新亚特兰蒂斯城的 MAST 大楼，"
                  "与图阿拉指挥官对话，完成入伍协议并通过飞行模拟考试即可加入。",
        "noteEn": "Join the UC Vanguard: go to the MAST building in New Atlantis and "
                  "speak with Commander Tuala; sign the enlistment agreement and pass "
                  "the flight simulator exam.",
    },
    {
        "key": "FC01",
        "faction": 4,                        # 4 = Freestar
        "nameZh": "自由星游骑兵",
        "nameEn": "Freestar Rangers",
        "expectedEn": "Job Gone Wrong",
        "guide": True,
        "noteZh": "加入自由星游骑兵：在阿基拉城遇到银行劫案时自动触发，"
                  "协助丹尼尔·布雷克治安官解决事件后，即可开启加入游骑兵的流程。",
        "noteEn": "Join the Freestar Rangers: this starts automatically when you run into "
                  "the bank robbery in Akila City - help Marshal Daniel Blake resolve it "
                  "to begin the process.",
    },
    {
        "key": "RI01",
        "faction": 2,                        # 2 = RyujinIndustries
        "nameZh": "龙神工业",
        "nameEn": "Ryujin Industries",
        "expectedEn": "Back to the Grind",
        "guide": True,
        "noteZh": "加入龙神工业：在新亚特兰蒂斯城或霓虹城找到龙神工业的招聘亭，"
                  "提交求职申请后即可开始。",
        "noteEn": "Join Ryujin Industries: find a Ryujin Industries recruitment kiosk in "
                  "New Atlantis or Neon and submit a job application.",
    },
    {
        "key": "CF01",
        "faction": 5,                        # 5 = BlackFleet
        "nameZh": "深红舰队",
        "nameEn": "Crimson Fleet",
        "expectedEn": "Deep Cover",
        "guide": False,                      # ★ 只保留简要说明（玩家要求）
        "noteZh": "加入深红舰队：需先加入 UC 先锋队并完成其前两个任务，"
                  "之后图阿拉指挥官会派你作为卧底潜入深红舰队。",
        "noteEn": "Join the Crimson Fleet: first join the UC Vanguard and finish its first "
                  "two quests, then Commander Tuala will send you undercover into the "
                  "Crimson Fleet.",
    },
]

NOTE_MAX = 200

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def load_names(strings_dir: Path) -> tuple[dict[int, str], dict[int, str]]:
    """官方本地化名（en / zhhans）—— quests_all.json 里没有名字，只有字符串 ID。

    ★ 与 gen_companion_quests.py 同一约定：名字从**官方 strings 表**取，不写死；
      玩家给的对照表只用来核验「EDID ↔ 英文名」没有对错行。
    """
    sys.path.insert(0, str(Path(__file__).parent))
    from strings_probe import load_strings
    return (load_strings(strings_dir / "starfield_en.strings"),
            load_strings(strings_dir / "starfield_zhhans.strings"))


def find_quest(quests: list[dict], edid: str) -> dict | None:
    """按 EDID 找 Starfield.esm 的记录（DLC 可能 override 同名 EDID ⇒ 只认基础游戏）。"""
    for q in quests:
        if (q.get("edid") or "") == edid and (q.get("master") or "Starfield.esm") == "Starfield.esm":
            return q
    for q in quests:
        if (q.get("edid") or "").lower() == edid.lower():
            return q
    return None


def incoming_edges(chain_files: list[Path], local: int) -> list[dict]:
    """收集「以这条任务为目标」的启动边（编号链 + 扩展边）。"""
    out: list[dict] = []
    for f in chain_files:
        if not f.exists():
            continue
        for t in load_json(f):
            if int(t["formid"]) != local:
                continue
            for e in t.get("edges", []):
                out.append({"host_edid": e.get("host_edid", "?"),
                            "host_local": int(e["host_local"]),
                            "host_stage": int(e["host_stage"]),
                            "src": e.get("src", ""),
                            "line": e.get("line", 0),
                            "note": e.get("note", ""),
                            "file": f.name})
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--quests", default=str(REF / "quests_all.json"))
    ap.add_argument("--chain", default=str(REF / "quest_chain.json"))
    ap.add_argument("--chain-extra", default=str(REF / "quest_chain_extra.json"))
    ap.add_argument("--guide-targets", default=str(REF / "guide_targets.json"))
    ap.add_argument("--table-json", default=str(REF / "quest_table_debug.json"))
    ap.add_argument("--strings-dir", default=str(REF / "strings" / "strings"))
    ap.add_argument("--out", default=str(REF / "faction_entry_quests.json"))
    ap.add_argument("--list", action="store_true")
    a = ap.parse_args()

    if a.list:
        p = Path(a.out)
        if not p.exists():
            print(f"（还没有 {p}）")
            return 0
        for g in json.loads(p.read_text(encoding="utf-8")):
            q = g["quest"]
            tag = "可引导" if g["guide"] else "只给说明（不可引导）"
            print(f"  {g['key']:<6} {q['nameZh']} / {q['nameEn']}"
                  f"（{g['nameZh']}，阵营 {g['faction']}）[{tag}] 0x{q['local']:06X}")
            print(f"      说明：{g['noteZh']}")
            print(f"      入边：{g['incoming'] or '（无 = 势力线第一环）'}")
            print(f"      证据：{g['evidence']}")
        return 0

    qpath = Path(a.quests)
    if not qpath.exists():
        print(f"（没有 {qpath} —— 保留现有 {a.out}，跳过核验）")
        return 0
    quests = load_json(qpath)
    strings_dir = Path(a.strings_dir)
    if not (strings_dir / "starfield_en.strings").exists():
        print(f"（没有官方 strings 表 {strings_dir} —— 保留现有 {a.out}，跳过核验）")
        return 0
    str_en, str_zh = load_names(strings_dir)
    gpath = Path(a.guide_targets)
    guides = load_json(gpath) if gpath.exists() else {}
    tpath = Path(a.table_json)
    table_rows = load_json(tpath) if tpath.exists() else []
    table_by_local = {int(r["local"]): r for r in table_rows}

    problems: list[str] = []
    out: list[dict] = []
    for ent in ENTRIES:
        edid = ent["key"]
        q = find_quest(quests, edid)
        if q is None:
            problems.append(f"{edid}：quests_all.json 里找不到这条任务")
            continue
        full = q.get("full")
        name_en = (str_en.get(int(full), "") if full else "").strip()
        name_zh = (str_zh.get(int(full), "") if full else "").strip()
        if name_en.lower() != ent["expectedEn"].lower():
            problems.append(f"{edid}：英文名不符（官方 strings {name_en!r} ≠ 对照表 "
                            f"{ent['expectedEn']!r}） —— 别用错 EDID")
            continue
        if not name_zh:
            problems.append(f"{edid}：官方中文名取不到（strings 表里没有 full={full}）")
            continue
        local = int(q["local"]) & 0xFFFFFF

        # ② 第一环 / 入边
        inc = incoming_edges([Path(a.chain), Path(a.chain_extra)], int(q["formid"]))
        if ent["guide"]:
            if inc:
                problems.append(f"{edid}：期望「势力线第一环」（没有入边），实际有 {len(inc)} 条入边"
                                f"：{inc}")
                continue
        else:
            if not inc:
                problems.append(f"{edid}：期望有入边（它就是靠前置任务启动的），实际没有")
                continue

        # ③ 引导候选（可引导的三条必须有；不可引导的那条记录候选数 = 会被清掉的量）
        g = guides.get(str(int(q["formid"]))) or {}
        cands = g.get("cands") or ([g] if g.get("refr") else [])
        cand_desc = ""
        if cands:
            first = cands[0]
            cand_desc = (f"首选候选「{first.get('nameZh') or first.get('nameEn')}」"
                         f"（{first.get('kind')}，常驻={bool(first.get('persistent'))}）"
                         f"，共 {len(cands)} 个候选")
        if ent["guide"] and not cands:
            problems.append(f"{edid}：玩家要求「能正常引导」，但 ref/guide_targets.json 里没有候选"
                            f"（先跑 tools/esm/gen_guide_targets.py）")
            continue

        # ④ 阵营枚举与静态表一致（工具只做交叉核对，不写死）
        fac_note = ""
        row = table_by_local.get(local)
        if row is not None:
            if int(row.get("faction", -1)) != ent["faction"]:
                problems.append(f"{edid}：静态表里的阵营 {row.get('faction')} ≠ 本表 {ent['faction']}"
                                f"（FactionUtils 枚举）")
                continue
            fac_note = f"，静态表阵营={row.get('faction')}"
        else:
            fac_note = "（注意：静态表里还没有这条 —— 它可能被内部任务过滤挡掉了）"
            problems.append(f"{edid}：静态表（quest_table_debug.json）里没有这条任务"
                            f" —— 固定显示无从谈起，先检查 filter_reason")
            continue

        # ⑤ 说明文本（载荷列的安全边界）
        for lang, note in (("zh", ent["noteZh"]), ("en", ent["noteEn"])):
            if not note.strip():
                problems.append(f"{edid}：{lang} 说明为空")
            if any(c in note for c in "\t\r\n"):
                problems.append(f"{edid}：{lang} 说明里有 Tab / 换行（会破坏载荷列结构）")
            if len(note) > NOTE_MAX:
                problems.append(f"{edid}：{lang} 说明超长（{len(note)} > {NOTE_MAX} 字符）")

        if ent["guide"]:
            evidence = cand_desc + fac_note
        else:
            evidence = "故意不引导（玩家要求：只保留简要说明）"
            if cands:
                evidence += f"；数据里有 {len(cands)} 个候选，构建期会被清空"
            evidence += fac_note

        out.append({
            "key": edid,
            "faction": ent["faction"],
            "nameZh": ent["nameZh"],
            "nameEn": ent["nameEn"],
            "quest": {
                "edid": q.get("edid", edid),
                "formid": int(q["formid"]),
                "local": local,
                "master": q.get("master", "Starfield.esm"),
                "nameZh": name_zh,
                "nameEn": name_en,
            },
            "guide": bool(ent["guide"]),
            "incoming": inc,
            "noteZh": ent["noteZh"],
            "noteEn": ent["noteEn"],
            "evidence": evidence,
        })

    if problems:
        print("核验失败（不写产物）：")
        for p in problems:
            print("  !! " + p)
        return 1

    Path(a.out).write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"wrote {a.out}")
    print(f"四大势力开头任务：{len(out)} 条（固定显示 + 固定排前四）")
    for g in out:
        q = g["quest"]
        tag = "可引导" if g["guide"] else "只给说明（不可引导）"
        print(f"  {g['key']:<6} {q['nameZh']} / {q['nameEn']}（{g['nameZh']} / {g['nameEn']}）"
              f" 0x{q['local']:06X} [{tag}]")
        print(f"      入边：{g['incoming'] or '（无 = 势力线第一环）'}")
        print(f"      证据：{g['evidence']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
