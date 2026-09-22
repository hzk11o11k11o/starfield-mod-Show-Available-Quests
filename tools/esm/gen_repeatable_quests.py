#!/usr/bin/env python3
r"""gen_repeatable_quests.py - 第 89 轮：**可重复任务表**（做完一次后仍显示 + 描述标注）。

起因（玩家反馈 + 全量盘点，见 `docs/11-可重复任务盘点（第89轮）.md`）：
  * 玩家反馈「赛多尼亚的 Denis Averin 也给重复任务，为什么列表里没有他」；
  * 全量盘点（`tools/esm/survey_repeatable.py`，5033 个官方 Papyrus 脚本特征扫描
    + ESM/3DM/游侠网三源交叉）⇒ 表内可重复任务 = 15 条（本清单）。

需求（第 89 轮决定，方案「②」）：
  这些任务**还在表里**（未完成时正常显示），但**完成一次后**会被本 mod 的
  「只挡已完成」过滤隐藏 —— 而它们设计上**还能再接**（下次接取后恢复 running）。
  ⇒ 对「可重复任务」**豁免「已完成」过滤**（列表里继续显示）+ 描述里标注「（可重复）」
  （写清「完成一次后还能再次接取 —— 去找谁 / 在哪」）。

    实现链（四处）：
      ① 本工具 → ref/repeatable_quests.json（`gen_quest_table.py` 消费）；
      ② 静态表 `StaticQuestInfo.repeatable` 列 + `kRepeatableNotesZh/En` 数组；
      ③ `Decision::DecideRuntimeFilter(flags, vtableKnown, repeatable)` —— 豁免判据（有单测）；
      ④ AS3 `FilterKnownQuests`：可重复 + 玩家日志里 bComplete == true ⇒ **保留**
         （否则「已接/已完成」会被 AS3 侧再丢一次，C++ 豁免就白做了）；
         载荷第 11 列 = 可重复标记（bSaqRepeatable）。

## 清单（15 条；证据 = 官方 Papyrus 特征 + 社区资料交叉，逐条见 `evidence`）

| EDID | 任务 | 提供者 | 地点 | 可重复证据 |
| --- | --- | --- | --- | --- |
| FFCydoniaR02 | 翻新商品 | 丹尼斯·阿维宁 | 赛多尼亚 · 联合殖民地交易所 | 计数 + 故事事件 |
| FFCydoniaR03 | 介质海绵 | 米奇·本杰明 | 赛多尼亚 ① | 故事事件 |
| FFNewHomesteadR02 | 游客都回家吧 | 古丽雅娜·拉科塔 | 新家园 · 药店 | 计数 + 冷却 + 故事事件 |
| FFNewHomesteadR04 | 限电 | 乔伊斯·奥萨卡 | 新家园 | 计数 + 冷却 + 故事事件 |
| FFNewHomesteadR05 | 特制酱汁 | 卢瑟·亚特兰大 | 新家园 | 计数 + 冷却 + 故事事件 |
| FFConstantR02 | 家人重聚 | 阿贝·莱维茨 | 恒常号（ECS Constant） | 计数 + 上限 + 故事事件 |
| FFRedMileR01 | 红里赛跑 | 「梅」（Mei） | 红里（Red Mile） | 故事事件 + 计数 |
| UCR01 | 先锋队：猎虫行动 | 指挥官图拉 | 新亚特兰蒂斯 · MAST | 计数 + Start |
| UCR03 | 先锋队：更安全的太空 | 指挥官图拉 | 新亚特兰蒂斯 · MAST | 计数 + Start |
| UCR04 | 顶级掠食者 | 珀西瓦尔·瓦尔克 | 红魔总部（火星） | 计数 + Start |
| UCR05 | 防范措施 | 瓦埃·维克提斯 | 新亚特兰蒂斯 · MAST | 计数 + Start |
| FCR01 | 游骑兵之乱 | （任务板连锁） | 自由星游骑兵 | 计数 + Start（每 3 个任务触发） |
| RAD05 | 全数到期 | 兰德里·霍尔费尔德 | 新亚特兰蒂斯 · 盖尔银行 | 计数 + Reset + Start |
| RIR06 | 处理特工 | Masako | 龙神大厦 | 计数 + 故事事件（radiant 调度） |
| RIR07 | 口舌之力 | Masako | 龙神大厦 | 计数 + 故事事件（radiant 调度） |

① 米奇·本杰明在赛多尼亚的摊位（官方数据 UC_CY_MitchBenjamin，别名 Vendor / BookMarker）。

**不收**（本轮盘点里「可重复性未确证」的三条，待实机验证后再补）：
  Rad01_LIST 独立盟之巅 / City_Neon_Chem03 供应线路 /
  City_NewAtlantis_Z_SpreadingTheNews 传播新闻。
**DLC**（SFFL 家族：职业杀手 / 备用零件 / 回收行动 ……）单独立项，本轮不收。

## 构建期核验（任一不符 ⇒ 不写产物、退出码 1）

① 每条在 `ref/quests_all.json`（记 master + local）；英文名与 `expectedEn` 逐字一致；
② 每条在 `ref/quest_table_debug.json`（**必须在静态表内** —— 否则「豁免过滤」无意义）；
③ 每条在 `ref/guide_targets.json` 里有引导候选（cand_count > 0，名单供人工二次确认）；
④ note 文本非空、无 Tab / 换行（会破坏载荷的列结构）、长度 ≤ 220 字符；
⑤ `evidence` 非空（人工复核轨迹）。

依赖缺失时（quests_all.json / quest_table_debug.json / guide_targets.json 不在）：
保留现有产物、跳过核验（与 gen_companion_quests.py / gen_faction_entry_quests.py 同一约定）。

用法：
    python tools/esm/gen_repeatable_quests.py          # 核验 + 写 ref/repeatable_quests.json
    python tools/esm/gen_repeatable_quests.py --list   # 只看当前产物
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
REF = ROOT / "ref"

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# ---------------------------------------------------------------------------
# 清单（顺序 = 生成顺序；与 survey_repeatable.py 的盘点结果一致）。
# expectedEn = 核验用的官方英文名（EDID ↔ 名字必须对上，避免社区译名对错）。
# noteZh/noteEn 留空 ⇒ 用默认模板生成（「完成一次后还能再次接取 —— 去找谁 / 在哪」）；
# 个别任务（触发方式特殊）单独写。
# ---------------------------------------------------------------------------
ENTRIES: list[dict] = [
    {
        "key": "FFCydoniaR02", "expectedEn": "Refurbished Goods",
        "giverZh": "丹尼斯·艾文林", "giverEn": "Denis Averin",
        "whereZh": "赛多尼亚 · 联合殖民地交易所", "whereEn": "Cydonia - the UC Exchange",
        "evidence": "计数 FFCydoniaR02_NumTimesCompleted.Mod(1) + 故事事件 "
                    "FFCydoniaR02QuestStartKeyword.SendStoryEvent()（6 个赛多尼亚对话片段）",
    },
    {
        "key": "FFCydoniaR03", "expectedEn": "Media Sponge",
        "giverZh": "米契·本杰明", "giverEn": "Mitch Benjamin",
        "whereZh": "赛多尼亚", "whereEn": "Cydonia",
        "evidence": "故事事件 FFCydoniaR03QuestStartKeyword.SendStoryEvent()（3 个对话片段）"
                    "+ 3DM「可重复」标注",
    },
    {
        "key": "FFNewHomesteadR02", "expectedEn": "Tourists Go Home",
        "giverZh": "朱莉安娜·拉科塔", "giverEn": "Giuliana Lakota",
        "whereZh": "新家园 · 药店", "whereEn": "New Homestead - the clinic",
        "evidence": "计数 FFNewHomesteadR02_NumTimesCompleted.Mod(1) + SetCooldown + 故事事件",
    },
    {
        "key": "FFNewHomesteadR04", "expectedEn": "Brownout",
        "giverZh": "乔伊斯·大阪", "giverEn": "Joyce Osaka",
        "whereZh": "新家园", "whereEn": "New Homestead",
        "evidence": "计数 FFNewHomesteadR04_NumTimesCompleted.Mod(1) + SetCooldown + 故事事件",
    },
    {
        "key": "FFNewHomesteadR05", "expectedEn": "Special Sauce",
        "giverZh": "卢瑟·亚特兰大", "giverEn": "Luther Atlanta",
        "whereZh": "新家园", "whereEn": "New Homestead",
        "evidence": "计数 FFNewHomesteadR05_NumTimesCompleted.Mod(1) + SetCooldown + 故事事件",
    },
    {
        "key": "FFConstantR02", "expectedEn": "Family Reunion",
        "giverZh": "亚伯·列维兹", "giverEn": "Abe Levitz",
        "whereZh": "恒常号（ECS Constant）", "whereEn": "the ECS Constant",
        "evidence": "计数 FFConstantR02_NumTimesCompleted + 次数上限 FFConstantR02_CompletedLimit "
                    "+ 故事事件（wiki「repeatable side quest」）",
        "noteZh": "（可重复）完成一次后还能再次接取 —— 去恒常号（ECS Constant）"
                  "找亚伯·列维兹即可（有接取次数上限）。",
        "noteEn": "(Repeatable) You can take this quest again after finishing it - talk to "
                  "Abe Levitz aboard the ECS Constant (there is a completion limit).",
    },
    {
        "key": "FFRedMileR01", "expectedEn": "Run the Red Mile",
        "giverZh": "梅·迪瓦恩", "giverEn": "Mei Devine",
        "whereZh": "红里（Red Mile）", "whereEn": "the Red Mile",
        "evidence": "故事事件 FFRedMileR01QuestStartKeyword + 完成计数 PlayerCompletedRedMile"
                    "（RedMileHandlerQuestScript）+ 游侠网「重复任务」",
    },
    {
        "key": "UCR01", "expectedEn": "Vanguard: Bug Hunt",
        "giverZh": "约翰·图阿拉指挥官", "giverEn": "Commander Tuala",
        "whereZh": "新亚特兰蒂斯 · MAST 大楼（中心区）", "whereEn": "New Atlantis - the MAST building",
        "evidence": "计数 UCR01_TimesCompleted + Stop();Reset() + Start()（UC 阵营 radiant）+ 3DM",
    },
    {
        "key": "UCR03", "expectedEn": "Vanguard: Safer Skies",
        "giverZh": "约翰·图阿拉指挥官", "giverEn": "Commander Tuala",
        "whereZh": "新亚特兰蒂斯 · MAST 大楼（中心区）", "whereEn": "New Atlantis - the MAST building",
        "evidence": "计数 UCR03_TimesCompleted + Start()（UC 阵营 radiant）+ 3DM",
    },
    {
        "key": "UCR04", "expectedEn": "Apex Predator",
        "giverZh": "珀西瓦里·沃克", "giverEn": "Percival Walker",
        "whereZh": "红魔总部（火星）／骇变兽管理总局", "whereEn": "Mars - the Red Devils HQ",
        "evidence": "计数 UCR04_TimesCompleted + Start()（UC 阵营 radiant）+ 3DM「可重复」",
    },
    {
        "key": "UCR05", "expectedEn": "Preventive Action",
        "giverZh": "瓦维刻提斯", "giverEn": "Vae Victis",
        "whereZh": "新亚特兰蒂斯 · MAST 大楼（中心区）", "whereEn": "New Atlantis - the MAST building",
        "evidence": "计数 UCR05_TimesCompleted + Start()（UC 阵营 radiant）+ 3DM「可重复」",
    },
    {
        "key": "FCR01", "expectedEn": "One Riot, One Ranger",
        "giverZh": "自由星游骑兵的差事", "giverEn": "Freestar Rangers jobs",
        "whereZh": "阿基拉城一带（游骑兵）", "whereEn": "Akila City (Freestar Rangers)",
        "evidence": "计数 FCR01TimesCompleted + FCRQuestScript.FCRMissionComplete()："
                    "每完成 3 个游骑兵任务板任务（FCR02~FCR05）触发一次",
        "noteZh": "（可重复）每完成 3 个自由星游骑兵的差事（任务板），这个悬赏就会再次开启。",
        "noteEn": "(Repeatable) Every 3 Freestar Rangers jobs (mission board) completed, "
                  "this bounty becomes available again.",
    },
    {
        "key": "RAD05", "expectedEn": "Due in Full",
        "giverZh": "兰德里·霍利菲尔德", "giverEn": "Landry Hollifeld",
        "whereZh": "新亚特兰蒂斯 · 商业区 · 盖尔银行（GalBank）",
        "whereEn": "New Atlantis - GalBank (Commercial District)",
        "evidence": "计数 RAD05_NumTimesCompleted + LandyScript.RestartRAD05()（Reset;Stop;Reset;Start）"
                    "+ mapgenie「repeatable」",
        "noteZh": "（可重复）完成一次后还能再次接取 —— 去新亚特兰蒂斯商业区的盖尔银行"
                  "（GalBank）找前台兰德里·霍利菲尔德即可。",
        "noteEn": "(Repeatable) You can take this quest again after finishing it - talk to "
                  "Landry Hollifeld at the GalBank front desk in New Atlantis.",
    },
    {
        "key": "RIR06", "expectedEn": "Managing Assets",
        "giverZh": "今田雅子（Masako）", "giverEn": "Masako Imada",
        "whereZh": "龙神大厦（霓虹城）", "whereEn": "the Ryujin Tower (Neon)",
        "evidence": "计数 RIR06_RadiantCount + 故事事件 RIR06_QuestStartKeyword"
                    "（RI_Support 调度）+ 第 77 轮 Wiki 定性「可重复 radiant」",
    },
    {
        "key": "RIR07", "expectedEn": "The Power of Persuasion",
        "giverZh": "今田雅子（Masako）", "giverEn": "Masako Imada",
        "whereZh": "龙神大厦（霓虹城）", "whereEn": "the Ryujin Tower (Neon)",
        "evidence": "计数 RIR07_RadiantCount + 故事事件 RIR07_QuestStartKeyword"
                    "（RI_Support 调度）+ 第 77 轮定性",
    },
]

DEFAULT_NOTE_ZH = "（可重复）完成一次后还能再次接取 —— 去找{giverZh}（{whereZh}）即可。"
DEFAULT_NOTE_EN = ("(Repeatable) You can take this quest again after finishing it - "
                   "talk to {giverEn} ({whereEn}).")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--quests", default="ref/quests_all.json")
    ap.add_argument("--table", default="ref/quest_table_debug.json")
    ap.add_argument("--guide", default="ref/guide_targets.json")
    ap.add_argument("--out", default="ref/repeatable_quests.json")
    ap.add_argument("--list", action="store_true")
    a = ap.parse_args()

    out_path = ROOT / a.out
    if a.list:
        if out_path.exists():
            for r in json.loads(out_path.read_text(encoding="utf-8")):
                print(f"{r['edid']:18s} {r['nameZh']:14s} | {r['giverZh']} | {r['whereZh']}")
        else:
            print("（还没有产物）")
        return 0

    qpath, tpath, gpath = ROOT / a.quests, ROOT / a.table, ROOT / a.guide
    if not qpath.exists() or not tpath.exists() or not gpath.exists():
        print(f"!! 缺依赖（{qpath.name} / {tpath.name} / {gpath.name}）—— 保留现有产物、跳过")
        return 0

    quests = {q["edid"]: q for q in json.loads(qpath.read_text(encoding="utf-8")) if q.get("edid")}
    table = {r["edid"]: r for r in json.loads(tpath.read_text(encoding="utf-8"))}
    guides = json.loads(gpath.read_text(encoding="utf-8"))
    guide_by_local = {int(k): v for k, v in guides.items()}

    problems: list[str] = []
    rows: list[dict] = []

    for e in ENTRIES:
        key = e["key"]
        q = quests.get(key)
        if q is None:
            problems.append(f"{key}: quests_all.json 里没有")
            continue
        local = int(q["formid"]) & 0xFFFFFF
        tab = table.get(key)
        if tab is None:
            problems.append(f"{key}: 不在静态表（quest_table_debug.json）里 —— 豁免无意义")
            continue
        name_en = tab.get("name_en", "")
        if e.get("expectedEn") and name_en != e["expectedEn"]:
            problems.append(f"{key}: 英文名不符：表={name_en!r} ≠ expected={e['expectedEn']!r}")
        g = guide_by_local.get(local) or {}
        cand_n = int(tab.get("cand_count", 0))
        first = ""
        if g.get("cands"):
            first = f"{g['cands'][0].get('nameZh') or g['cands'][0].get('nameEn')}" \
                    f"@{g['cands'][0].get('refr')}"
        if cand_n <= 0:
            problems.append(f"{key}: 无引导候选（cand_count=0）")
        note_zh = e.get("noteZh") or DEFAULT_NOTE_ZH.format(**e)
        note_en = e.get("noteEn") or DEFAULT_NOTE_EN.format(**e)
        for label, txt in (("noteZh", note_zh), ("noteEn", note_en)):
            if not txt:
                problems.append(f"{key}: {label} 为空")
            if "\t" in txt or "\n" in txt:
                problems.append(f"{key}: {label} 含 Tab/换行")
            if len(txt) > 220:
                problems.append(f"{key}: {label} 超长（{len(txt)} > 220）")
        if not e.get("evidence"):
            problems.append(f"{key}: evidence 为空")
        rows.append({
            "key": key,
            "edid": key,
            "local": local,
            "master": q.get("master", "Starfield.esm"),
            "nameZh": tab.get("name_zh", ""),
            "nameEn": name_en,
            "giverZh": e["giverZh"], "giverEn": e["giverEn"],
            "whereZh": e["whereZh"], "whereEn": e["whereEn"],
            "candCount": cand_n,
            "firstCand": first,
            "evidence": e["evidence"],
            "noteZh": note_zh,
            "noteEn": note_en,
        })

    if problems:
        print("!! 核验失败：")
        for p in problems:
            print("   -", p)
        return 1

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"已写出 {out_path.relative_to(ROOT)}（{len(rows)} 条）")
    for r in rows:
        print(f"  {r['edid']:18s} {r['nameZh']:14s} | {r['giverZh']} | {r['whereZh']:24s} "
              f"| 首选候选 {r['firstCand']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
