#!/usr/bin/env python3
"""gen_quest_table.py - 生成插件内嵌的静态任务表（master + 记录号 -> 中/英文名 + 类型 + 阵营）。

输入：
    ref/quests_all.json                     quest_dump.py 的多 master 导出（Starfield.esm + 各 DLC）
    ref/strings/strings/<master>_en.strings        每个 master 一份字符串表（名字里带 FULL 的字符串 ID）
    ref/strings/strings/<master>_zhhans.strings    master 名小写去掉扩展名，与游戏内 strings 文件同名
    ref/faction_types.json                  ★ 第 65 轮：QUST 的 FTYP 关键字 -> 原版 UI 阵营枚举
                                            （gen_faction_types.py 生成；缺失 ⇒ 全部按无阵营）
    ref/companion_quests.json               ★★ 第 74 轮：同伴好感度任务（gen_companion_quests.py
                                            生成；缺失 ⇒ 不标记 —— 这类任务就不会固定显示）
    ref/faction_entry_quests.json           ★★ 第 75 轮：四大势力开头任务（gen_faction_entry_quests.py
                                            生成；缺失 ⇒ 不标记 —— 也不会固定排前四）
    ref/repeatable_quests.json              ★★ 第 89 轮：可重复任务（gen_repeatable_quests.py 生成；
                                            缺失 ⇒ 这 15 条照旧「做完一次就消失」）
输出：
    plugin/src/SAQ_QuestTable.h             C++ 静态数组（多 master）
    ref/quest_table_debug.json              同样的数据（便于人工核对）
    ui/missionmenu/saqdata/SaqEmbeddedPayload.inc   SWF 内嵌回退载荷（列序与 C++ 完全一致）

★ 多 master（第 17 轮，DLC 支持）：
    每条任务记 **master 名 + 记录号（local）**，不记运行期 FormID —— 运行期 FormID 的
    高字节是「加载顺序」（MO2/其它插件都会影响），只有 DLL 运行时才知道：
        FormID = (master 的加载序号 << 24) | local         （普通插件）
        FormID = 0xFE000000 | (small 序号 << 12) | local   （light/ESL 插件，local 只有 12 位）
    DLC 的字符串表是**各自一份**（shatteredspace_en.strings / sfbgs050_en.strings），
    所以取名字要按记录所属的 master 选表 —— 这是 DLC 支持里最容易搞错的一步。

规则：
  * 只保留带 QTYP 的任务（玩家可见任务）
  * 排除主线（QuestTypeMainQuest）—— MOD 需求：只关注非主线
  * 排除「内部任务」：无本地化名 / 名称带 [] / 指示器 / 地标 / 教学 / 同伴系统 /
    任务板(MB_) / 别名生成模板 / 对话容器 / 系统管理任务等（见 filter_reason，
    分析过程在 ref/table_review.txt 与 ref/filter_preview_kept.txt）
  * 名称里的 <Alias=xxx> 占位符替换为通用词（引擎运行时会替换，静态表不能）
  * 没有名称的任务用 EDID 兜底
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path

ALIAS_RE = re.compile(r"<Alias=([^>]+)>")

QTYPE_TO_ITYPE = {
    0x000475F8: 0,  # Activities
    0x000475FA: 1,  # MainQuest
    0x000475FD: 2,  # Factions
    0x00047600: 3,  # SideQuest (-> Misc)
    0x001E2D30: 4,  # Mission
}
QTYPE_NAMES = {
    0x000475F8: "Activities",
    0x000475FA: "MainQuest",
    0x000475FD: "Factions",
    0x00047600: "SideQuest",
    0x001E2D30: "Mission",
}

# 占位符 -> 通用词（按关键字匹配）
PLACE_KEYS = ("location", "planet", "system", "place", "site", "biome", "body", "orbital", "world")


def alias_to_text(token: str, zh: bool) -> str:
    low = token.lower()
    if any(k in low for k in PLACE_KEYS):
        return "地点" if zh else "the location"
    if "ship" in low:
        return "飞船" if zh else "the ship"
    return "目标" if zh else "the target"


def clean_name(raw: str, zh: bool) -> str:
    if not raw:
        return ""
    out = ALIAS_RE.sub(lambda m: alias_to_text(m.group(1), zh), raw)
    out = out.replace("  ", " ").strip()
    return out


def filter_reason(row: dict, raw_en: str, raw_zh: str, is_landmark: bool = False) -> str | None:
    """判断一条任务是不是「内部任务」（不该出现在可接列表里）。

    返回 None = 保留；否则返回被排除的原因标签（统计/日志用）。
    所有判据都是**离线可验证**的显示层信号；运行时状态过滤（已接/条件）在 C++/AS3 侧。

    ★★ 第 81 轮（地球地标任务）：新增 is_landmark —— 在
    ref/landmark_quests.json 里的任务**豁免「地标」规则**（第 7 轮的判断
    「走近即完成、无从『接』」已被复查否定：它们是「拾取对应书籍 ⇒ SetStage(100)」
    的正常 Activities，见 gen_landmark_quests.py 头注释）。
    """
    edid = row.get("edid") or ""
    edid_l = edid.lower()
    en = row["name_en"] or ""
    zh = row["name_zh"] or ""
    en_l = en.lower()

    if en == edid or zh == edid:
        return "无本地化名"           # B 社没给正式名字 = 内部任务
    if "[" in en or "]" in en or "[" in zh or "]" in zh:
        return "方括号"               # [BE - xxx] / [杂项目标提示] 等开发标记
    if edid.startswith("MB_"):
        return "任务板生成"           # 任务板上的无限生成任务（入口另行处理）
    # ★★ 第 110 轮（追踪者联盟）：BountyScannerQuest 是 Story Manager 交替 spin up 的
    #   「城市赏金」——5 条同名同结构（主条 SFBGS003_BountyScannerQuest + 副本 00~03），
    #   任务本身是无限生成（无固定接取点）。只保留**主条**（作可重复 + noPickup 展示，
    #   见 ref/repeatable_quests.json），副本排除（否则列表里会出现 5 条「赏金狩猎」）。
    if edid_l.startswith("sfbgs003_bountyscannerquest0"):
        return "无限生成副本"
    if "pointer" in edid_l or "pointer" in en_l or "指示器" in zh or "指示器" in en:
        return "指示器"               # Misc pointer 系统
    if not is_landmark and ("landmark" in edid_l or "地标任务" in zh or "地标任务" in en):
        return "地标"                 # ★ 第 81 轮：地标任务表里的 10 条豁免（见上）
    if "tutorial" in edid_l or "tutorial" in en_l:
        return "教学"
    # 测试内容（第 17 轮，DLC 实测）：`SFBGS00D_CruiseMode_TestSupport`「巡航模式测试支援」。
    # 用「_test」而不是「test」：后者会误伤 contest 这类正常词。
    if "_test" in edid_l or edid_l.startswith("test_") or "测试" in zh or "测试" in en:
        return "测试内容"
    if edid_l.startswith("com_companion") or edid_l.endswith("_companions"):
        return "同伴系统"             # 同伴管理主任务（玩家不会「接」）
        # （第 17 轮补 `_companions`：DLC 的 SFTER_Companions「同伴任务处理」是同一类系统任务）
    if "<Alias=" in raw_en or "<Alias=" in raw_zh:
        return "别名模板"             # 名字靠运行时目标拼出来 = 生成任务
    if "dialogue" in edid_l:
        return "对话容器"
    if ("handler" in edid_l or "处理程序" in zh or "的生成和场景任务" in zh
            or "杂项任务" in zh or zh.endswith("- 处理") or zh.endswith(" - 处理")):
        return "内部管理"
    if "各种系统" in zh or "various systems" in en_l:
        return "系统任务"
    if zh.endswith("：") or zh.endswith(":") or en.endswith(":"):
        return "空标题"
    return None


def dnam_flags(dnam_hex: str) -> int:
    """QUST 记录 DNAM 的头 4 字节 = 任务标志位（uint32，小端）。

    ★ 布局是这一版实测出来的（与 commonlibsf 的 QUEST_DATA 声明**不一致**）：
      DNAM = uint32 flags @0 | uint8 priority @4 | 3 字节未用 @5 | uint8 type @8 | 3 字节未用
    验证：MQ101 dnam=0005010050… ⇒ flags=0x00010500、priority=byte[4]=0x50=80
          —— 与 xEdit 树状导出（Flags: Run Once/Warn/Unknown16, Priority = 80）逐字相符。

    目前**只写进表里做诊断**（运行时会打印几个候选位的计数），还没有哪一位被证实是
    「引擎自动启动」；要看的是「引擎已开始的那几条任务的 DNAM 位」长什么样。
    """
    try:
        b = bytes.fromhex(dnam_hex or "")
    except ValueError:
        return 0
    return int.from_bytes(b[:4], "little") if len(b) >= 4 else 0


def as3_escape(s: str) -> str:
    out = []
    for ch in s:
        if ch == "\\":
            out.append("\\\\")
        elif ch == '"':
            out.append('\\"')
        elif ch == "\n":
            out.append("\\n")
        elif ch == "\t":
            out.append("\\t")
        elif ch == "\r":
            out.append("\\r")
        elif ord(ch) < 0x20:
            out.append(" ")
        else:
            out.append(ch)
    return "".join(out)


def sanitize_name(s: str) -> str:
    """名字里不能有 Tab/换行（会破坏载荷的行/列结构）。"""
    return s.replace("\t", " ").replace("\r", " ").replace("\n", " ").strip()


def payload_order(rows: list[dict]) -> list[dict]:
    """★★ 第 74/75/96 轮：内嵌回退载荷的条目顺序 —— 与 C++ 侧**逐条对齐**。

    C++（SAQ.cpp 的 CollectAvailableQuests）收集完成后按 Decision::PinnedOrderKey 排序
    （stable_sort ⇒ 组内保持表顺序）：
      ① ★★ 第 75 轮：四大势力开头任务（faction_entry ≥ 0）—— 玩家要求
         「固定排在可接任务列表的**前四个**」，组内按 faction_entry 下标（= 固定顺序）；
      ② ★ 第 74 轮：同伴任务（按同伴分组、同一位同伴的「入口」在「后续」之前）；
      ③ 其余任务；
      ④ ★★ 第 96 轮：可重复任务（repeatable ≥ 0）—— 玩家要求「一样把它们排列在一起
         （像图里的（可重复）NPC 入口）」⇒ 整组排到列表**末尾**（C++ 侧 = group 3）。
         ★ 注意：内嵌载荷里没有「入口」条目（任务板 / 可重复 NPC 由 DLL 追加）——
         C++ 运行时它们落在「其余」组的末尾（先追加、后稳定排序）⇒ 可重复组正好接在
         「（可重复）NPC」入口之后；回退载荷里可重复组之后同样**没有别的行**（末尾）。
    内嵌载荷必须同序 —— 否则「C++ 推送失败 → 内嵌回退」的窗口里列表顺序会跳变
    （第 65 轮踩过列不对齐的坑，顺序同理；★ 第 74 轮的 `order=` 探针会直接把顺序报出来，
    第 96 轮起还报 `|tail=` 末尾两行 —— 两个来源都在它的覆盖下）。
    """
    factions = [r for r in rows if int(r.get("faction_entry", -1)) >= 0]
    companions = [r for r in rows if int(r.get("faction_entry", -1)) < 0
                  and int(r.get("companion", -1)) >= 0]
    # ★★ 第 96 轮：可重复任务单独一组、排在最后（判据与 C++ 的组序一致：
    #   势力 > 同伴 > 其余 > 可重复；输入顺序 = 表顺序，列表推导天然稳定）。
    repeatables = [r for r in rows if int(r.get("faction_entry", -1)) < 0
                   and int(r.get("companion", -1)) < 0
                   and int(r.get("repeatable", -1)) >= 0]
    others = [r for r in rows if int(r.get("faction_entry", -1)) < 0
              and int(r.get("companion", -1)) < 0
              and int(r.get("repeatable", -1)) < 0]
    factions.sort(key=lambda r: int(r["faction_entry"]))
    companions.sort(key=lambda r: (int(r["companion"]),
                                   0 if int(r.get("companion_pin", 0)) else 1))
    return factions + companions + others + repeatables


def build_payload(rows: list[dict], title_zh: str = "可接任务", title_en: str = "Available") -> str:
    """与 C++ 侧 BuildPayloadUtf8 **完全同格式**的载荷（AS3 内嵌回退用）。

    列序 = C++ 的 Q 行，**必须逐列对齐**（AS3 解析按列号取值，错一列后果严重）：
        formid / itype / 中文名 / 英文名 / 有无引导目标 / 是否需要靠近 / 阵营枚举 / 同伴好感度任务

    ★ 第 23 轮：倒数第四列是「有没有引导目标」（1/0）——界面据此决定能不能导航。
    ★ 第 46 轮：倒数第三列 = 「全部候选都非常驻」（需要靠近才加载目标）。
      第 65 轮补上 —— 此前内嵌回退载荷缺这列，AS3 会把阵营列误读成它。
    ★ 第 65 轮（任务专属图标）：倒数第四列 = 原版 UI 阵营枚举（-1 = 无阵营），
      界面据此显示主线/势力专属图标。
    ★★ 第 74 轮（同伴好感度任务）：倒数第三列 = 「同伴任务」（1/0）—— 界面在描述里
      提示「需要一定好感度才能接取」；旧载荷缺列 ⇒ false（不提这回事）。
    ★★ 第 75 轮（四大势力开头任务）：最后两列 = 「简要说明」（中 / 英）——
      界面把它写在描述里（固定显示的那四条：加入方式 / 前置条件）；
      其余任务是空串。旧载荷缺列 ⇒ 空串（走原来的「这条任务当前可以接取」文案）。
      ★★ 第 89 轮（可重复任务）：说明的来源多一类（kRepeatableNotes*，「（可重复）…」）；
      **追加第 11 列** = 可重复标记（"1"/"0"）—— AS3 侧 FilterKnownQuests 据此豁免
      「在玩家日志里」的丢弃（已完成 + 可重复 ⇒ 保留；进行中照旧隐藏）。
    """
    lines = ["SAQ1", f"T\t{title_zh}\t{title_en}"]
    # ★★ 第 74/75/96 轮：顺序与 C++ 对齐（势力开头任务 → 同伴任务 → 其余 →
    #   可重复任务；见 payload_order —— C++ 侧是 Decision::PinnedOrderKey 的四个组）。
    for r in payload_order(rows):
        fid = r["formid"] if isinstance(r["formid"], int) else int(r["formid"], 16)
        has_target = "1" if int(r.get("cand_count", 0)) else "0"
        approach = "1" if r.get("needs_approach") else "0"
        faction = int(r.get("faction", -1))
        companion = "1" if int(r.get("companion", -1)) >= 0 else "0"
        # ★★ 第 81 轮：说明文本的来源有两类 —— 势力开头任务（kFactionEntryNotes*）与
        #   地球地标任务（kLandmarkNotes*）；其余任务空串。
        #   ★★ 第 89 轮（可重复任务）：第三类来源 kRepeatableNotes*（「（可重复）…」）。
        has_note = (int(r.get("faction_entry", -1)) >= 0 or int(r.get("landmark", -1)) >= 0
                    or int(r.get("repeatable", -1)) >= 0)
        note_zh = sanitize_name(r.get("noteZh", "")) if has_note else ""
        note_en = sanitize_name(r.get("noteEn", "")) if has_note else ""
        # ★★ 第 89 轮：第 11 列 = 可重复任务标记（"1"/"0"）—— 追加在最后
        #   （旧载荷 / 旧内嵌数据缺这列 ⇒ AS3 按 false 处理）。
        repeat = "1" if int(r.get("repeatable", -1)) >= 0 else "0"
        lines.append(
            f'Q\t{fid}\t{r["itype"]}\t{sanitize_name(r["name_zh"])}'
            f'\t{sanitize_name(r["name_en"])}\t{has_target}\t{approach}\t{faction}'
            f'\t{companion}\t{note_zh}\t{note_en}\t{repeat}'
        )
    return "\n".join(lines) + "\n"


def write_as3_fragment(rows: list[dict], out_path: Path, chunk_chars: int = 6000) -> int:
    """把载荷切成若干段 AS3 字符串字面量，供 build-saq.ps1 拼进 MissionMenu.as。

    切片只是为了避免单个字符串字面量过大（运行时 join("") 还原，切片位置无所谓，
    但尽量落在换行处，便于人工看）。
    """
    payload = build_payload(rows)
    chunks: list[str] = []
    rest = payload
    while rest:
        take = min(len(rest), chunk_chars)
        if take < len(rest):
            cut = rest.rfind("\n", 0, take)
            if cut < chunk_chars // 2:
                cut = take
            take = cut
        chunks.append(rest[:take])
        rest = rest[take:]

    body = ",\r\n".join(f'\t\t"{as3_escape(c)}"' for c in chunks)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(body.encode("utf-8"))
    return len(payload)


def c_escape(s: str) -> str:
    out = []
    for ch in s:
        if ch == "\\":
            out.append("\\\\")
        elif ch == '"':
            out.append('\\"')
        elif ch == "\n":
            out.append("\\n")
        elif ch == "\t":
            out.append("\\t")
        else:
            out.append(ch)
    return "".join(out)


def load_guide_targets(path: Path) -> dict[int, dict]:
    """引导目标表（tools/esm/gen_guide_targets.py 生成；没有也不影响构建）。"""
    if not path.exists():
        print(f"（没有 {path} —— 引导目标为空，先跑 tools/esm/gen_guide_targets.py）")
        return {}
    raw = json.loads(path.read_text(encoding="utf-8"))
    return {int(k): v for k, v in raw.items()}


def load_companions(path: Path) -> list[dict]:
    """★★ 第 74 轮：同伴好感度任务（tools/esm/gen_companion_quests.py 生成）。

    这些任务（COM_Quest_<同伴>_Q01 / _Commitment）只能由同伴主任务
    COM_Companion_<同伴> 的**好感度里程碑**带出来 ⇒ 运行时「固定显示」
    （不做三类门槛过滤）+ 名字前缀同伴名 + 界面描述里提示好感度要求。
    缺失 ⇒ 全部按「非同伴任务」处理（功能退化为普通任务，不会写错数据）。
    """
    if not path.exists():
        print(f"（没有 {path} —— 同伴好感度任务不会被固定显示，"
              f"先跑 tools/esm/gen_companion_quests.py）")
        return []
    return json.loads(path.read_text(encoding="utf-8"))


def load_faction_entries(path: Path) -> list[dict]:
    """★★ 第 75 轮：四大势力开头任务（tools/esm/gen_faction_entry_quests.py 生成）。

    这四条（UC01 超越极限 / FC01 枝节横生 / RI01 重返职场 / CF01 深藏不露）是各自
    势力线的**第一环** ⇒ 运行时「固定显示」（跳过三类门槛）+ **固定排在列表前四个**
    （玩家要求）+ 描述里写「简要说明」（加入方式 / 前置条件，载荷最后两列）。
    `guide=false` 的那条（深红舰队）另有处置：**清空引导候选**（见下面的候选循环）。
    缺失 ⇒ 不标记（功能退化：这四条按普通任务处理，不会写错数据）。
    """
    if not path.exists():
        print(f"（没有 {path} —— 四大势力开头任务不会被固定显示，"
              f"先跑 tools/esm/gen_faction_entry_quests.py）")
        return []
    return json.loads(path.read_text(encoding="utf-8"))


def load_landmark_quests(path: Path) -> list[dict]:
    """★★ 第 81 轮（地球地标任务）：「雪景球」收集线（tools/esm/gen_landmark_quests.py 生成）。

    这 10 条（阿波罗 / 开罗 / 迪拜 / 香港 / 伦敦 / 洛杉矶 / 纽约 / 大阪 / 上海 / 圣路易斯）
    在数据里是「**拾取对应书籍 ⇒ 任务 SetStage(100)**」的 Activities（书上挂着官方脚本
    `defaultrefoncontainerchangedto`）⇒ 符合 MOD 的收录标准。本表提供三件事：

      ① **过滤豁免**：filter_reason 的「地标」规则跳过它们（见 is_landmark 参数）；
      ② **引导候选**：书的世界放置引用（精确）+ 同 cell / world 级常驻兜底
         （Cairo 的书在商店库存里 ⇒ 用书商 AhnjongSinclair 的引用；London 无固定
         接取点 ⇒ guide=false，候选在生成期被清空，只给说明）；
      ③ **说明文本**（载荷最后两列）：去哪拿哪本书（书被拾取后任务即已接取，
         运行时「已接取 ⇒ 隐藏」照常生效）。

    缺失 ⇒ 这 10 条继续被「地标」规则排除（功能退化，不会写错数据）。
    """
    if not path.exists():
        print(f"（没有 {path} —— 地球地标任务不会被豁免过滤，"
              f"先跑 tools/esm/gen_landmark_quests.py）")
        return []
    return json.loads(path.read_text(encoding="utf-8"))


def load_repeatable_quests(path: Path) -> list[dict]:
    """★★ 第 89 轮（可重复任务）：**做完一次还能再接**的 15 条（gen_repeatable_quests.py 生成）。

    玩家反馈「赛多尼亚的 Denis Averin 也给重复任务，列表里却没有他」→ 全量盘点
    （tools/esm/survey_repeatable.py，5033 个官方 Papyrus 脚本特征扫描 + ESM/3DM/
    游侠网三源交叉）⇒ 表内可重复任务 15 条。它们设计上**能被反复完成**（完成后引擎
    标记 completed，但下次接取会恢复 running），而本 MOD 原来的「只挡已完成」过滤
    会把它们做完一次后就藏起来 ⇒ 本轮做三件事：

      ① **豁免「已完成」过滤**（C++ 侧：Decision::DecideRuntimeFilter 的 repeatable 参数）
         —— 完成后继续留在列表里；
      ② **描述标注**（载荷最后两列，kRepeatableNotes*）：「（可重复）完成一次后还能
         再次接取 —— 去找谁 / 在哪」；
      ③ **载荷第 11 列** = 可重复标记 —— AS3 侧 FilterKnownQuests 据此豁免
         「在玩家日志里」的丢弃（否则 C++ 豁免会被 AS3 再丢一次，见 MissionMenu.as）。

    缺失 ⇒ 不标记（功能退化：这 15 条照旧「做完一次就消失」，不会写错数据）。
    """
    if not path.exists():
        print(f"（没有 {path} —— 可重复任务不会被豁免「已完成」过滤，"
              f"先跑 tools/esm/gen_repeatable_quests.py）")
        return []
    return json.loads(path.read_text(encoding="utf-8"))


def companion_display_name(name: str, comp: str, sep_out: str) -> str:
    """★ 第 74 轮：把同伴名放到任务名最前面。

    两种形态（都要覆盖）：
      · 承诺任务：官方名本来就是「承诺：巴雷特」/「Commitment: Barrett」
        ⇒ 换位成「巴雷特：承诺」/「Barrett: Commitment」（同伴名已经在名里，不能重复加）；
      · 个人任务：官方名是「违约」/「Breach of Contract」⇒ 直接加前缀。
    sep_out = 输出用冒号（中文「：」/ 英文「: 」）。
    """
    for sep in ("：", ": ", ":"):
        if sep in name:
            head, _, tail = name.rpartition(sep)
            tail = tail.strip()
            if tail == comp and head.strip():
                return f"{comp}{sep_out}{head.strip()}"
    return f"{comp}{sep_out}{name}"


def load_faction_types(path: Path) -> dict[str, dict[str, int]]:
    """阵营映射（tools/esm/gen_faction_types.py 生成；没有 ⇒ 全部按无阵营）。

    ★ 第 65 轮（任务专属图标）：键 = (master 文件名, FTYP 的文件内十六进制)。
    C++ 载荷与内嵌载荷的阵营列都来自这里（见 faction_of）。
    """
    if not path.exists():
        print(f"（没有 {path} —— 任务阵营为空，先跑 tools/esm/gen_faction_types.py）")
        return {}
    raw = json.loads(path.read_text(encoding="utf-8"))
    out: dict[str, dict[str, int]] = {}
    for master, rows in raw.items():
        if master.startswith("_"):
            continue
        out[master] = {k: int(v["faction"]) for k, v in rows.items()}
    return out


def faction_of(q: dict, fac_map: dict[str, dict[str, int]]) -> int:
    """QUST 的 FTYP（文件内 FormID）-> 原版 UI 阵营枚举；无 FTYP / 查不到 ⇒ -1。

    枚举顺序见 ui/missionmenu/src/Shared/FactionUtils.as（0=Paradiso … 6=Constellation …）。
    """
    ft = q.get("ftyp")
    if ft is None:
        return -1
    return fac_map.get(q["master"], {}).get(f"{int(ft):08X}", -1)


def load_gates(path: Path) -> dict[int, list[dict]]:
    """进度门槛表（tools/esm/analyze_ctda.py 生成；没有 ⇒ 不做条件过滤）。

    ★ 第 35 轮：「游戏进度还不能让玩家接到 ⇒ 不显示」的离线判据。
    只有「引用别的任务」的 GetQuestRunning/GetQuestCompleted/GetStageDone（等于比较）
    才算门槛（自引用是引擎启动守卫，不算 —— 见 analyze_ctda.py 头注释）。
    """
    if not path.exists():
        print(f"（没有 {path} —— 进度门槛为空，先跑 tools/esm/analyze_ctda.py）")
        return {}
    raw = json.loads(path.read_text(encoding="utf-8"))
    return {int(t["formid"]): t.get("gates", []) for t in raw}


def load_info_gates(path: Path) -> dict[int, list[dict]]:
    """INFO 门槛表（tools/esm/analyze_info_gates.py 生成；没有 ⇒ 不做 INFO 过滤）。

    ★★ 大项 D（第 48 轮）：任务自己的对话（INFO）里「引用别的任务」的进度条件 ——
    任务运行中的对话（推进类）与没有任何事件条件的对话都不算；判定语义见
    analyze_info_gates.py 头注释（全部参与对话都「有已知为假的条件」⇒ 隐藏）。
    """
    if not path.exists():
        print(f"（没有 {path} —— INFO 门槛为空，先跑 tools/esm/analyze_info_gates.py）")
        return {}
    raw = json.loads(path.read_text(encoding="utf-8"))
    return {int(t["formid"]): t.get("infos", []) for t in raw}


def load_extra_quests(path: Path) -> list[dict]:
    """★★★ 第 106 轮（覆盖面全量复盘）：「无 QTYP 但完整」的补收任务。

    起因：全量审计（tools/esm/audit_coverage.py）发现 —— 现行规则「只保留带 QTYP
    的任务」把一批**有任务目标（QOBJ>0）的正式剧情任务**整体排除了。它们的
    QTYP 子记录缺失（不进原版任务菜单的类型分类），但内容完整：有对话（TIF）、
    有任务目标（QOBJ / QTGL）、有 stage 文本（NAM2）与脚本逻辑，而且都有**玩家可达
    的启动路径**（同伴里程碑 / 前一个任务的收尾 fragment / 城市对话管理器 /
    守卫犯罪对话）—— 是本 MOD「可接任务」应当覆盖的对象。

    本名单是**逐条人工核验**的（每条 note 带证据）；gen 侧只做一件事：对名单里的
    任务**豁免「无 QTYP」短路**（用名单给的 itype 继续走正常流程 —— 名字 / 过滤 /
    门槛 / 引导候选都照常）。

    为什么不用「QOBJ>0 自动收录」：无 QTYP + QOBJ>0 的还有十几条**不该收**的
    （CUT_ 删减内容 / MB_*_OLD 废弃 / StarbornTempleQuest 主线环节 / 特质任务 /
    SFFL_MS01 主线等）—— 自动规则会误收，必须逐条核验（清单见 docs/12）。

    文件格式：{"_why": "...", "entries": [{"master","local"(hex 字符串或整数),
    "edid","itype","note"}, ...]}。缺失 ⇒ 空名单（这些任务照旧不收）。
    """
    if not path.exists():
        print(f"（没有 {path} —— 补收名单为空：无 QTYP 的漏收任务不会进表）")
        return []
    raw = json.loads(path.read_text(encoding="utf-8"))
    entries = raw.get("entries", []) if isinstance(raw, dict) else raw
    out = []
    for e in entries:
        loc = e["local"]
        out.append({
            "master": e.get("master", "Starfield.esm"),
            "local": int(loc, 16) if isinstance(loc, str) else int(loc),
            "edid": e["edid"],
            "itype": int(e.get("itype", 3)),
            "note": e.get("note", ""),
        })
    return out


def load_chain(path: Path) -> dict[int, list[dict]]:
    """★ 第 67 轮：任务链门槛表（tools/esm/gen_quest_chain.py 生成；没有 ⇒ 不做链式过滤）。

    每条边 = 「上一个任务的某个 stage fragment 启动了这个任务」（从官方 Papyrus 源码
    里挖出来的，例如 CF01 的 stage 1000 fragment 里 `CF02.SetStage(10)`）。
    运行时判据：**全部链边都还没触发 ⇒ 隐藏**（详见 SAQ_QuestTable.h 的 kChainGates）。
    """
    if not path.exists():
        print(f"（没有 {path} —— 链式门槛为空，先跑 tools/esm/gen_quest_chain.py）")
        return {}
    raw = json.loads(path.read_text(encoding="utf-8"))
    return {int(t["formid"]): t.get("edges", []) for t in raw}


def merge_chain(base: dict[int, list[dict]], extra: dict[int, list[dict]]) -> dict[int, list[dict]]:
    """★★ 第 69 轮：把「扩展链式边」并进编号链路边 —— 按 (宿主记录号, 宿主 stage) 去重。

    两个数据源语义相同（收尾 stage 启动下一个任务），运行时共用 kChainGates 一套判据；
    扩展边的生成与核验见 tools/esm/gen_quest_chain_extra.py。
    """
    out: dict[int, list[dict]] = {k: list(v) for k, v in base.items()}
    for local, edges in extra.items():
        have = {(int(e["host_local"]), int(e["host_stage"])) for e in out.get(local, [])}
        for e in edges:
            key = (int(e["host_local"]), int(e["host_stage"]))
            if key in have:
                continue
            have.add(key)
            out.setdefault(local, []).append(e)
    return out


def master_strings_key(master: str) -> str:
    """master 名 -> 字符串表前缀：ShatteredSpace.esm -> shatteredspace（与游戏内文件名一致）。"""
    return Path(master).stem.lower()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--quests", default="ref/quests_all.json",
                    help="quest_dump.py 的多 master 导出（老的单文件导出也能用）")
    ap.add_argument("--strings-dir", default="ref/strings/strings")
    ap.add_argument("--guide-targets", default="ref/guide_targets.json")
    ap.add_argument("--gates", default="ref/ctda_gates.json",
                    help="进度门槛（analyze_ctda.py 产物；决定「进度没到不显示」）")
    ap.add_argument("--info-gates", default="ref/info_gates_final.json",
                    help="★ 大项 D：对话侧 INFO 门槛（analyze_info_gates.py 产物）")
    ap.add_argument("--factions", default="ref/faction_types.json",
                    help="★ 第 65 轮：任务阵营（gen_faction_types.py 产物；缺失 ⇒ 全无阵营）")
    ap.add_argument("--chain", default="ref/quest_chain.json",
                    help="★ 第 67 轮：任务链门槛（gen_quest_chain.py 产物；缺失 ⇒ 不做链式过滤）")
    ap.add_argument("--chain-extra", default="ref/quest_chain_extra.json",
                    help="★★ 第 69 轮：链式门槛的扩展边（gen_quest_chain_extra.py 产物；"
                         "人工核实 + 构建期源码核验；缺失 ⇒ 只做编号链）")
    ap.add_argument("--chain-dlc", default="ref/quest_chain_dlc.json",
                    help="★★★ 第 98 轮：DLC 的链式启动边（gen_dlc_chain.py 产物 —— "
                         "官方 .pex 反编译取证；缺失 ⇒ DLC 主线后续照旧只按 INFO 门槛）")
    ap.add_argument("--companions", default="ref/companion_quests.json",
                    help="★★ 第 74 轮：同伴好感度任务（gen_companion_quests.py 产物；"
                         "缺失 ⇒ 不标记，这类任务不会固定显示）")
    ap.add_argument("--faction-entries", default="ref/faction_entry_quests.json",
                    help="★★ 第 75 轮：四大势力开头任务（gen_faction_entry_quests.py 产物；"
                         "缺失 ⇒ 不标记，这四条不会固定排前四）")
    ap.add_argument("--landmarks", default="ref/landmark_quests.json",
                    help="★★ 第 81 轮：地球地标任务（gen_landmark_quests.py 产物；"
                         "缺失 ⇒ 这 10 条继续被「地标」规则排除）")
    ap.add_argument("--repeatables", default="ref/repeatable_quests.json",
                    help="★★ 第 89 轮：可重复任务（gen_repeatable_quests.py 产物；"
                         "缺失 ⇒ 这 15 条照旧「做完一次就消失」）")
    ap.add_argument("--extra-quests", default="ref/extra_quests.json",
                    help="★★★ 第 106 轮：补收名单（无 QTYP 但完整的漏收任务；"
                         "逐条人工核验，见 load_extra_quests；缺失 ⇒ 不补收）")
    ap.add_argument("--out-header", default="plugin/src/SAQ_QuestTable.h")
    ap.add_argument("--out-json", default="ref/quest_table_debug.json")
    ap.add_argument("--out-as3", default="ui/missionmenu/saqdata/SaqEmbeddedPayload.inc")
    ap.add_argument("--include-main", action="store_true")
    ap.add_argument("--keep-internal", action="store_true",
                    help="不过滤内部任务（调试用；正常构建不要加）")
    a = ap.parse_args()

    sys.path.insert(0, str(Path(__file__).parent))
    from strings_probe import load_strings

    base = Path(a.strings_dir)

    quests = json.loads(Path(a.quests).read_text(encoding="utf-8"))
    # 老格式（没有 master 字段）当成全是 Starfield.esm —— 兼容第 17 轮以前的 quests.json
    for q in quests:
        q.setdefault("master", "Starfield.esm")
        # ★★ 第 110 轮：位宽按档位分三种 —— full 24 位 / medium 16 位（0xFD）/ light 12 位（0xFE）
        if q.get("medium"):
            mask = 0xFFFF
        elif q.get("small"):
            mask = 0xFFF
        else:
            mask = 0xFFFFFF
        q["local"] = int(q.get("local", q["formid"])) & mask

    # master 列表：Starfield.esm 永远排 0（表里 master 下标越小越基础），其余按名字排序
    masters = sorted({q["master"] for q in quests},
                     key=lambda m: (m.lower() != "starfield.esm", m.lower()))
    master_idx = {m: i for i, m in enumerate(masters)}
    print(f"master 列表：{masters}")

    # 每个 master 一份字符串表（★ DLC 的名字就在它自己那份里）
    strings: dict[str, tuple[dict, dict]] = {}
    for m in masters:
        key = master_strings_key(m)
        en_file = base / f"{key}_en.strings"
        zh_file = base / f"{key}_zhhans.strings"
        if not en_file.exists() or not zh_file.exists():
            print(f"  !! {m}: 缺 {en_file.name} / {zh_file.name} —— 这个 master 的任务会"
                  f"因「取不到名字」被当成内部任务全部过滤掉")
            print(f"     （用 python tools\\re\\ba2list.py \"<DLC - Main.ba2>\" "
                  f"--grep {key}_en.strings --extract ref\\strings 抽取）")
            strings[m] = ({}, {})
            continue
        strings[m] = (load_strings(en_file), load_strings(zh_file))
        print(f"  {m}: 字符串表 {key}_*.strings（en {len(strings[m][0])} / zh {len(strings[m][1])} 条）")

    # ★ 第 65 轮（任务专属图标）：阵营映射（FTYP 关键字 -> UI 枚举）
    fac_map = load_faction_types(Path(a.factions))

    # ★★ 第 81 轮（地球地标任务）：「雪景球」收集线 —— ① 豁免「地标」过滤；
    #   ② 引导候选来自该书目表；③ 说明文本写进载荷最后两列。见 load_landmark_quests。
    landmarks = load_landmark_quests(Path(a.landmarks))
    lm_by_local = {int(g["quest"]["local"]): i for i, g in enumerate(landmarks)}

    # ★★ 第 89 轮（可重复任务）：做完一次后仍显示（豁免「已完成」过滤）+ 描述标注。
    #   见 load_repeatable_quests / docs/11-可重复任务盘点（第89轮）.md。
    repeatables = load_repeatable_quests(Path(a.repeatables))
    rp_by_local = {int(g["local"]): i for i, g in enumerate(repeatables)}

    # ★★★ 第 106 轮（覆盖面全量复盘）：补收名单（无 QTYP 但完整的漏收任务）——
    #   豁免「无 QTYP」短路；链式边走 quest_chain_extra.json（见 load_extra_quests）。
    extra_quests = load_extra_quests(Path(a.extra_quests))
    extra_by = {((e["master"] or "").lower(), int(e["local"]) & 0xFFFFFF): e
                for e in extra_quests}
    n_extra_used = 0
    if extra_quests:
        print(f"补收名单（无 QTYP 人工核验）：{len(extra_quests)} 条")

    rows = []
    skipped_no_type = 0
    skipped_main = 0
    skipped_reasons: dict[str, int] = {}
    skipped_samples: dict[str, list[str]] = {}

    for q in quests:
        qtyp = q.get("qtyp")
        itype = None
        if qtyp is None:
            # ★★★ 第 106 轮：补收名单里的任务豁免「无 QTYP」短路（逐条人工核验）。
            ex = extra_by.get(((q.get("master") or "").lower(), int(q["local"]) & 0xFFFFFF))
            if ex is None:
                skipped_no_type += 1
                continue
            itype = int(ex["itype"])
            n_extra_used += 1
        else:
            itype = QTYPE_TO_ITYPE.get(qtyp)
            if itype is None:
                continue
        if itype == 1 and not a.include_main:
            skipped_main += 1
            continue
        en, zh = strings.get(q["master"], ({}, {}))
        full = q.get("full")
        raw_en = en.get(full, "") if full else ""
        raw_zh = zh.get(full, "") if full else ""
        name_en = clean_name(raw_en, False)
        name_zh = clean_name(raw_zh, True)
        edid = q.get("edid") or ""
        if not name_en:
            name_en = edid
        if not name_zh:
            name_zh = name_en
        row = {
            "formid": q["formid"],      # 文件里的原始 FormID（带该文件自己的 master 前缀）
            "master": q["master"],      # 记录来自哪个插件
            "local": q["local"],        # 记录号（运行期 = (加载序号 << 24) | local）
            "small": bool(q.get("small")),
            "medium": bool(q.get("medium")),  # ★★ 第 110 轮：medium 档（0xFD | idx<<16 | local）
            "edid": edid,
            "itype": itype,
            "qtype": QTYPE_NAMES.get(qtyp, ""),
            "name_en": name_en,
            "name_zh": name_zh,
            "dnam": q.get("dnam", ""),
            "dnam_flags": dnam_flags(q.get("dnam", "")),
            # ★ 第 65 轮（任务专属图标）：QUST 的 FTYP 关键字 -> 原版 UI 阵营枚举。
            #   -1 = 无阵营（界面按 iType 选 Activities/Misc/Missions 图标）。
            "faction": faction_of(q, fac_map),
            # ★★ 第 74 轮（同伴好感度任务）：-1 = 不是；≥0 = kCompanionNames 下标。
            #   真正的标记与名字前缀在下面 apply_companions 里统一做（要两遍）。
            "companion": -1,
            # ★★ 第 75 轮（四大势力开头任务）：-1 = 不是；≥0 = kFactionEntry* 下标
            #   （同时是**固定顺序**：0 = 联合殖民地 … 3 = 深红舰队）。同样在两遍里做。
            "faction_entry": -1,
            # ★★ 第 81 轮（地球地标任务）：-1 = 不是；≥0 = kLandmarkNotes* 下标
            #   （同时是说明文本的下标）。豁免「地标」过滤的判据也是它。
            "landmark": -1,
            # ★★ 第 89 轮（可重复任务）：-1 = 不是；≥0 = kRepeatableNotes* 下标
            #   （同时是说明文本的下标）。豁免「已完成」过滤的判据也是它。
            "repeatable": -1,
        }
        row_is_landmark = int(row["local"]) in lm_by_local
        if row_is_landmark:
            row["landmark"] = lm_by_local[int(row["local"])]
        if int(row["local"]) in rp_by_local:
            row["repeatable"] = rp_by_local[int(row["local"])]
        if not a.keep_internal:
            reason = filter_reason(row, raw_en, raw_zh, is_landmark=row_is_landmark)
            if reason:
                skipped_reasons[reason] = skipped_reasons.get(reason, 0) + 1
                samples = skipped_samples.setdefault(reason, [])
                if len(samples) < 3:
                    samples.append(f"0x{q['formid']:08X} {edid}")
                continue
        rows.append(row)

    # 排序：master 下标升序（基础游戏在前 —— 列表里同名的以基础游戏为准），再按记录号
    rows.sort(key=lambda r: (master_idx[r["master"]], r["local"]))

    # ★★ 第 74 轮（同伴好感度任务）：入口固定显示 + 名字前缀同伴名；后续（承诺任务）
    #   补一条**启动边**（并入链式门槛 ⇒ 「前置没到就不显示」，见下方 chain_by_fid）。
    #   数据 = ref/companion_quests.json（gen_companion_quests.py；对官方 Papyrus 源码
    #   核验过「只能由好感度里程碑启动」）。名字前缀在这里做（**静态表 + 内嵌回退载荷
    #   一起生效**，C++ 载荷直接取表里的名字）。
    companions = load_companions(Path(a.companions))
    comp_by_formid: dict[int, int] = {}
    comp_pin_by_formid: dict[int, int] = {}
    comp_followup: dict[int, list[dict]] = {}
    for idx, g in enumerate(companions):
        for cq in g["quests"]:
            fid = int(cq["formid"])
            comp_by_formid[fid] = idx
            comp_pin_by_formid[fid] = 1 if cq.get("pin") else 0
            fg = cq.get("followUpGate")
            if fg:
                comp_followup.setdefault(fid, []).append({
                    "host_local": int(fg["hostLocal"]),
                    "host_master": fg.get("hostMaster", "Starfield.esm"),
                    "host_edid": fg["hostEdid"],
                    "host_stage": int(fg["hostStage"]),
                })
    n_companion_quests = 0
    for r in rows:
        idx = comp_by_formid.get(int(r["formid"]))
        if idx is None:
            continue
        g = companions[idx]
        r["companion"] = idx
        r["companion_pin"] = comp_pin_by_formid[int(r["formid"])]
        r["name_zh"] = companion_display_name(r["name_zh"], g["nameZh"], "：")
        r["name_en"] = companion_display_name(r["name_en"], g["nameEn"], ": ")
        n_companion_quests += 1
    unmarked = [f"0x{int(r['formid']):08X} {r['edid']}" for r in rows
                if (r.get("edid") or "").startswith("COM_Quest_")
                and int(r["formid"]) not in comp_by_formid]
    if unmarked:
        print(f"  !! 表里有 COM_Quest_ 前缀、但不在同伴表里的任务（不会固定显示）：{unmarked}")
    n_pin = sum(1 for r in rows if int(r.get("companion_pin", 0)))
    print(f"同伴好感度任务：{len(companions)} 位同伴 / {n_companion_quests} 条标记"
          f"（入口 {n_pin} 条固定显示 + 后续 {n_companion_quests - n_pin} 条走链式门槛）")
    for g in companions:
        entries = [r["name_zh"] for r in rows if r.get("companion", -1) >= 0
                   and companions[r["companion"]]["key"] == g["key"]
                   and int(r.get("companion_pin", 0))]
        follows = [r["name_zh"] for r in rows if r.get("companion", -1) >= 0
                   and companions[r["companion"]]["key"] == g["key"]
                   and not int(r.get("companion_pin", 0))]
        print(f"  {g['nameZh']:<10}（{g['nameEn']}）：入口 {'、'.join(entries)}"
              f"｜后续 {'、'.join(follows)}")

    # ★★ 第 75 轮（四大势力开头任务）：固定显示 + 固定排前四 + 描述里的「简要说明」。
    #   数据 = ref/faction_entry_quests.json（gen_faction_entry_quests.py；核验过
    #   「是势力线第一环」+ 引导候选 / 阵营枚举 / 说明文本）；缺失 ⇒ 不标记。
    #   ★ guide=false 的那条（深红舰队「深藏不露」）另有处置：下面的候选循环会
    #     **清空它的引导候选**（玩家要求「只保留简要说明」—— 它的接取点在先锋队线
    #     两个任务之后才出现，给引导只会把玩家引到错的地方）。
    faction_entries = load_faction_entries(Path(a.faction_entries))
    fac_by_formid = {int(g["quest"]["formid"]): i for i, g in enumerate(faction_entries)}
    fac_guide = {i: bool(g["guide"]) for i, g in enumerate(faction_entries)}
    n_faction_entries = 0
    for r in rows:
        idx = fac_by_formid.get(int(r["formid"]))
        if idx is None:
            continue
        r["faction_entry"] = idx
        # 说明文本只给这四条（载荷最后两列）—— 其余任务保持空串
        r["noteZh"] = faction_entries[idx]["noteZh"]
        r["noteEn"] = faction_entries[idx]["noteEn"]
        n_faction_entries += 1
    rows_formids = {int(r["formid"]) for r in rows}
    missing_fac = [g["key"] for g in faction_entries
                   if int(g["quest"]["formid"]) not in rows_formids]
    if missing_fac:
        print(f"  !! 势力开头任务表里有、但静态表里没有的任务（不会固定显示）：{missing_fac}")
    if faction_entries:
        print(f"四大势力开头任务：{n_faction_entries}/{len(faction_entries)} 条标记"
              f"（固定显示 + 固定排前四；说明写进载荷最后两列）")
        for i, g in enumerate(faction_entries):
            if int(g["quest"]["formid"]) in rows_formids:
                print(f"  {i}. {g['quest']['nameZh']} / {g['quest']['nameEn']}"
                      f"（{g['nameZh']} / {g['nameEn']}）"
                      f"{'可引导' if g['guide'] else '只给说明（候选会被清空）'}")

    # ★★ 第 81 轮（地球地标任务）：说明文本（载荷最后两列）—— 与势力开头的说明同一通路，
    #   只是数据源换成 kLandmarkNotes*（下标 = landmark 列）。
    n_landmark = 0
    for r in rows:
        idx = int(r.get("landmark", -1))
        if idx < 0:
            continue
        g = landmarks[idx]
        r["noteZh"] = g["noteZh"]
        r["noteEn"] = g["noteEn"]
        n_landmark += 1
    missing_lm = [f"{g['key']}(0x{g['quest']['formid']:06X})" for g in landmarks
                  if int(g["quest"]["formid"]) not in rows_formids]
    if missing_lm:
        print(f"  !! 地标任务表里有、但静态表里没有的任务（不会显示）：{missing_lm}")
    if landmarks:
        print(f"地球地标任务：{n_landmark}/{len(landmarks)} 条进表"
              f"（豁免「地标」过滤；说明写进载荷最后两列）")
        for i, g in enumerate(landmarks):
            if int(g["quest"]["formid"]) in rows_formids:
                tag = (f"候选 {len(g['cands'])}（{g['cands'][0]['src']} 起）"
                       if g["guide"] else "只给说明（候选在生成期清空）")
                print(f"  {i}. {g['quest']['nameZh']} / {g['quest']['nameEn']}"
                      f"（书：{g['book']['nameZh']}）[{tag}]")

    # ★★ 第 89 轮（可重复任务）：说明文本（载荷最后两列）—— 与上面两个说明同一通路，
    #   数据源换成 kRepeatableNotes*（下标 = repeatable 列）。判据（豁免「已完成」过滤）
    #   在 C++ 侧由 Decision::DecideRuntimeFilter 的 repeatable 参数消费。
    n_repeatable = 0
    for r in rows:
        idx = int(r.get("repeatable", -1))
        if idx < 0:
            continue
        g = repeatables[idx]
        r["noteZh"] = g["noteZh"]
        r["noteEn"] = g["noteEn"]
        n_repeatable += 1
    rows_locals = {int(r["local"]) for r in rows}
    missing_rp = [f"{g['key']}(0x{g['local']:06X})" for g in repeatables
                  if int(g["local"]) not in rows_locals]
    if missing_rp:
        print(f"  !! 可重复任务表里有、但静态表里没有的任务（豁免无从生效）：{missing_rp}")
    if repeatables:
        print(f"可重复任务：{n_repeatable}/{len(repeatables)} 条进表"
              f"（豁免「已完成」过滤；说明 + 第 11 列标记写进载荷）")

    # 引导目标（第 10 轮；★ 第 45 轮升级为「候选池」）：每条任务在世界里的
    # 「去哪里接」引用序列（gen_guide_targets.py 按质量排序 —— 有名字的 NPC >
    # 可读名落脚点 > 通用名 NPC > 内部名落脚点；同级内常驻优先）。
    # 运行时 DLL 取「此刻引擎里取得到」的第一个候选；脚本报取不到时还会换下一个。
    # 没有引导目标的任务照样进表（列表照常显示，只是不能引导）。
    guides = load_guide_targets(Path(a.guide_targets))
    master_by_lower = {m.lower(): i for i, m in enumerate(masters)}
    n_guide = 0
    unknown_guide_master: set[str] = set()
    cand_flat: list[tuple[int, int, int, str]] = []   # (refrLocal, refrMaster, persistent, 展示名)
    for r in rows:
        lm_idx = int(r.get("landmark", -1))
        if lm_idx >= 0:
            # ★★ 第 81 轮（地球地标任务）：候选来自 ref/landmark_quests.json ——
            #   首选 = 书（或书商）的引用，随后是同 cell / world 级常驻兜底；
            #   guide=false 的那条（伦敦）候选为空 ⇒ 界面走「不可导航」通路（只给说明）。
            cands = landmarks[lm_idx].get("cands", [])
        else:
            g = guides.get(r["formid"])
            cands = (g or {}).get("cands") or ([g] if g and g.get("refr") else [])
        ok_cands: list[dict] = []
        for c in cands:
            cm = c.get("refrMaster") or r["master"]
            if not c.get("refr"):
                continue
            if cm.lower() not in master_by_lower:
                unknown_guide_master.add(cm)
                continue
            ok_cands.append(c)
        # ★★ 第 75 轮（四大势力开头任务）：明确「只给说明」的那条（深红舰队「深藏不露」）
        #   ⇒ **清空引导候选** —— 界面侧因此走「不可导航」通路（点击给提示 + 描述里写明
        #   原因），不会把玩家引到 CF 线中途才存在的 NPC 那里去。判据来自
        #   ref/faction_entry_quests.json 的 guide=false（玩家要求「只保留简要说明」）。
        if int(r.get("faction_entry", -1)) >= 0 and not fac_guide.get(int(r["faction_entry"]), True):
            if ok_cands:
                print(f"  · {r['name_zh']}：按势力入口表清空 {len(ok_cands)} 个引导候选"
                      f"（只保留说明）")
            ok_cands = []
        r["cand_begin"] = len(cand_flat)
        r["cand_count"] = len(ok_cands)
        # ★ 第 65 轮：内嵌回退载荷要跟 C++ 的 Q 行**逐列对齐** —— 这里补算
        #   「全部候选都非常驻」（判据与 C++ 的 AllCandidatesNonPersistent 相同）。
        r["needs_approach"] = bool(ok_cands) and all(not c.get("persistent") for c in ok_cands)
        r["guide_kind"] = ok_cands[0].get("kind", "") if ok_cands else ""
        r["guide_where_en"] = (ok_cands[0].get("whereEn") or "").strip() if ok_cands else ""
        r["guide_where_zh"] = (ok_cands[0].get("whereZh") or "").strip() if ok_cands else ""
        if ok_cands:
            n_guide += 1
        for c in ok_cands:
            cm = c.get("refrMaster") or r["master"]
            # ★★ 第 110 轮：候选引用同样按档位取位宽（medium 也来了）
            if c.get("refrMedium"):
                cand_mask = 0xFFFF
            elif c.get("refrSmall"):
                cand_mask = 0xFFF
            else:
                cand_mask = 0xFFFFFF
            local = int(c["refr"]) & cand_mask
            cand_name = (c.get("nameZh") or c.get("nameEn") or "").strip()
            cand_flat.append((local, master_by_lower[cm.lower()], 1 if c.get("persistent") else 0, cand_name))
    if unknown_guide_master:
        print(f"  !! 引导目标引用了表里没有的 master（先加进任务表）：{sorted(unknown_guide_master)}")
    print(f"引导候选池：{len(cand_flat)} 条候选 / {n_guide} 条任务"
          f"（平均 {len(cand_flat) / max(n_guide, 1):.1f} 个/任务）")

    print(f"table rows: {len(rows)}（无类型 {skipped_no_type}，主线 {skipped_main}"
          + (f"，补收 {n_extra_used}/{len(extra_quests)}" if extra_quests else "")
          + f"）；其中带引导目标 {n_guide} 条（{n_guide * 100 // max(len(rows), 1)}%）")

    # ★ 第 35 轮：进度门槛（「游戏进度还不能让玩家接到 ⇒ 不显示」）
    #   数据链：xEdit 条件 dump → analyze_ctda.py（提取外部引用门槛）→ 这里平铺进表。
    gates_by_fid = load_gates(Path(a.gates))
    # ★★ 第 87 轮：第 6 元 = or_bit（type bit0；OR 组语义见 docs/08 4.3）
    cond_flat: list[tuple[int, int, int, int, int, int]] = []
    n_gate_tasks = 0
    for r in rows:
        gs = gates_by_fid.get(r["formid"], [])
        gs = [g for g in gs if 0 <= int(g.get("quest_master", 0)) < len(masters)]
        r["cond_begin"] = len(cond_flat)
        r["cond_count"] = len(gs)
        r["cond_gates"] = gs
        if gs:
            n_gate_tasks += 1
        for g in gs:
            cond_flat.append((int(g["quest_local"]) & 0xFFFFFF, int(g["quest_master"]),
                              int(g["func"]), int(g["want"]), int(g.get("stage", 0)) & 0xFFFF,
                              int(g.get("or_bit", 0)) & 1))
    print(f"进度门槛：{n_gate_tasks} 条任务 / {len(cond_flat)} 条条件"
          f"（其中 OR 组条件 {sum(c[5] for c in cond_flat)} 条）")
    for r in rows:
        if r["cond_count"]:
            desc = []
            for g in r["cond_gates"]:
                name = ("Running", "Completed", "StageDone")[int(g["func"])]
                if int(g["func"]) == 2:
                    d = f"{name}(0x{int(g['quest_local']):06X},{g['stage']})=={g['want']}"
                else:
                    d = f"{name}(0x{int(g['quest_local']):06X})=={g['want']}"
                if int(g.get("or_bit", 0)):
                    d += "[OR]"
                desc.append(d)
            print(f"  {r['edid']:<34} {' AND '.join(desc)}")

    # ★★ 大项 D（第 48 轮）：INFO 门槛（对话侧条件）—— 每条任务一组「参与判定的对话」，
    #   每条对话又是一组条件（切片）。运行时：全部对话都「有已知为假的条件」⇒ 隐藏。
    #   ★ 第 106 轮（operator 全量产品化）：条件带 OR 位（第 6 元不再恒 0）——
    #   一条对话内：无 OR 位的条件相互 AND、OR 组（含关闭组的第一条无 OR 位条件）
    #   组内相互 OR；组作为整体参与 AND（引擎语义，见 docs/08 4.3）。
    info_by_fid = load_info_gates(Path(a.info_gates))
    info_cond_flat: list[tuple[int, int, int, int, int, int]] = []
    info_group_flat: list[tuple[int, int]] = []
    n_info_tasks = 0
    for r in rows:
        infos = info_by_fid.get(r["formid"], [])
        r["info_group_begin"] = len(info_group_flat)
        r["info_group_count"] = len(infos)
        if infos:
            n_info_tasks += 1
        for inf in infos:
            conds = inf.get("conds", [])
            info_group_flat.append((len(info_cond_flat), len(conds)))
            for c in conds:
                # ★ 第 106 轮：第 6 元 = OR 位（or_bit，来自 scan_info_gates.py 的 OR 组
                #   提取）；旧数据 / 旧 INFO 门槛缺这列 ⇒ 0（与旧行为一致）。
                info_cond_flat.append((int(c["quest_local"]) & 0xFFFFFF, int(c["quest_master"]),
                                       int(c["func"]), int(c["want"]), int(c.get("stage", 0)) & 0xFFFF,
                                       int(c.get("or_bit", 0))))
    print(f"INFO 门槛：{n_info_tasks} 条任务 / {len(info_group_flat)} 条对话 / "
          f"{len(info_cond_flat)} 条条件")

    # ★ 第 67 轮：任务链门槛 —— 「上一个任务的收尾 stage 启动下一个任务」的启动边
    #   （gen_quest_chain.py 从官方 Papyrus 源码里挖出来的）。运行时判据：
    #   **全部链边都还没触发 ⇒ 隐藏**（详见 SAQ_QuestTable.h 的 kChainGates）。
    #   ★★ 第 69 轮：并入「扩展边」（gen_quest_chain_extra.py：非编号链路里同样形态的
    #   「收尾/流程启动下一个」—— Eleos 线、霓虹城帮派线等，见该工具头注释）。
    #   ★★ 第 74 轮：再并入「同伴后续任务（承诺任务）的启动边」—— 与链式门槛共用同一套
    #   判据（全部边都没触发 ⇒ 隐藏）：这是玩家要求的「链式关系的后续任务不要显示，
    #   只显示入口任务」在同伴线上的落点（入口 = 个人任务，见上面的 companion_pin）。
    chain_by_fid = merge_chain(
        merge_chain(
            merge_chain(load_chain(Path(a.chain)), load_chain(Path(a.chain_extra))),
            # ★★★ 第 98 轮：DLC 的启动边（官方 .pex 反编译取证 —— 破碎空间主线
            #   MQ02/MQ_Shell/MQ03/MQ04/MQ05/MQ06 六条；host 是 DLC 自己的任务，
            #   运行时按 kChainGates 的 hostMaster 解析，跨 master 已支持）。
            load_chain(Path(a.chain_dlc))),
        comp_followup)
    dlc_chain = load_chain(Path(a.chain_dlc))
    if dlc_chain:
        n_dlc_edges = sum(len(v) for v in dlc_chain.values())
        print(f"DLC 链式启动边：{len(dlc_chain)} 条任务 / {n_dlc_edges} 条边"
              f"（并入链式门槛 —— 官方 .pex 反编译取证，见 docs/06 八节）")
    if comp_followup:
        n_fu = sum(len(v) for v in comp_followup.values())
        print(f"同伴后续任务启动边：{len(comp_followup)} 条任务 / {n_fu} 条边"
              f"（并入链式门槛 —— 前置没到就不显示）")
    q_master_by_local: dict[int, str] = {}
    for q in quests:
        q_master_by_local.setdefault(int(q["local"]), q["master"])
    chain_flat: list[tuple[int, int, int]] = []   # (hostLocal, hostMaster, hostStage)
    n_chain_tasks = 0
    for r in rows:
        edges = chain_by_fid.get(r["formid"], [])
        ok_edges = []
        for e in edges:
            hm = e.get("host_master", "Starfield.esm")
            hl = int(e["host_local"]) & 0xFFFFFF
            if hm not in master_idx:
                print(f"  !! 链式门槛引用了表里没有的 master（跳过这条边）：{hm}")
                continue
            ok_edges.append((hl, master_idx[hm], int(e["host_stage"]) & 0xFFFF,
                             e.get("host_edid", "")))
        r["chain_begin"] = len(chain_flat)
        r["chain_count"] = len(ok_edges)
        r["chain_edges"] = ok_edges
        if ok_edges:
            n_chain_tasks += 1
        for (hl, hm, hs, _edid) in ok_edges:
            chain_flat.append((hl, hm, hs))
    print(f"链式门槛：{n_chain_tasks} 条任务 / {len(chain_flat)} 条启动边")
    for r in rows:
        if r["chain_count"]:
            desc = " | ".join(f"{e[3]}@{e[2]}" for e in r["chain_edges"])
            print(f"  {r['edid']:<34} 需要其一已触发：{desc}")

    per_master = Counter(r["master"] for r in rows)
    print("按 master：" + " ".join(f"{m}={per_master[m]}" for m in masters))

    # ★ 第 65 轮（任务专属图标）：阵营分布（人工核对「势力任务有没有拿到图标」）
    fac_names = {0: "Paradiso", 1: "UnitedColonies", 2: "RyujinIndustries", 3: "HouseVaruun",
                 4: "Freestar", 5: "BlackFleet", 6: "Constellation", 7: "TrackersAlliance",
                 8: "TerranArmada", 9: "Creations"}
    fac_count = Counter(r["faction"] for r in rows)
    print("任务阵营：" + " ".join(
        f"{fac_names.get(k, ('无阵营' if k < 0 else f'未知{k}'))}={v}"
        for k, v in sorted(fac_count.items())))
    kind_count: dict[str, int] = {}
    for r in rows:
        if r["guide_kind"]:
            kind_count[r["guide_kind"]] = kind_count.get(r["guide_kind"], 0) + 1
    if kind_count:
        print("引导目标来源：" + " ".join(f"{k}={v}" for k, v in sorted(kind_count.items())))
    if skipped_reasons:
        print("过滤内部任务:")
        for reason, n in sorted(skipped_reasons.items(), key=lambda kv: -kv[1]):
            print(f"  {reason:10s} {n:4d}  例: {', '.join(skipped_samples[reason])}")

    # C++ 头文件
    lines = []
    lines.append("#pragma once")
    lines.append("")
    lines.append("// 本文件由 tools/esm/gen_quest_table.py 自动生成，请勿手改。")
    lines.append("// 数据来源：Starfield.esm + 各官方 DLC 的 QUST 记录 + 每个 master 自己的 strings 表")
    lines.append("//   " + "、".join(f"{m}（{per_master[m]} 条）" for m in masters))
    lines.append("//")
    lines.append("// itype 与 AS3 侧 Shared.QuestUtils 的枚举一致：")
    lines.append("//   0=Activities 1=Main 2=Factions 3=Misc 4=Mission")
    lines.append("// ★ 第 65 轮（任务专属图标）：每行尾部的 faction = 原版 UI 阵营枚举")
    lines.append("//   （-1 = 无阵营；顺序见 Shared/FactionUtils.as，说明见 StaticQuestInfo 里的注释）——")
    lines.append("//   界面据此显示主线/各势力专属图标，和原版任务菜单一致。")
    lines.append("// ★★ 第 74 轮（同伴好感度任务）：行尾两列 = companion（同伴下标，-1 = 不是）")
    lines.append("//   + companionPin（1 = 「入口」同伴任务 ⇒ 固定显示 + 名字带同伴前缀）。")
    lines.append("//   「后续」同伴任务（承诺任务，pin=0）照旧走链式门槛（前置没到不显示）。")
    lines.append("// ★★ 第 75 轮（四大势力开头任务）：最后一列 = factionEntry（-1 = 不是；")
    lines.append("//   0..3 = kFactionEntryNames* 下标）—— 这四条**固定显示**（跳过三类门槛）+")
    lines.append("//   **固定排在列表前四个**（按本列升序）+ 描述里写「简要说明」")
    lines.append("//   （载荷最后两列，来自 kFactionEntryNotesZh/En）。")
    lines.append("//")
    lines.append("// ★ 多 master（DLC）：表里存的是「master 下标 + 记录号(local)」，不是运行期 FormID ——")
    lines.append("//   高字节是加载顺序，只有运行时才知道（见 SAQ.cpp 的 MasterResolver）。")
    lines.append("")
    lines.append("#include <cstdint>")
    lines.append("")
    lines.append("namespace SAQ")
    lines.append("{")
    lines.append("\t// 数据源插件名（DLL 按名字在 TESDataHandler.files 里查加载序号）")
    lines.append("\tinline constexpr const char* kQuestMasters[] = {")
    for m in masters:
        lines.append(f'\t\t"{c_escape(m)}",')
    lines.append("\t};")
    lines.append(f"\tinline constexpr std::size_t kQuestMasterCount = {len(masters)};")
    lines.append("")
    lines.append("\tstruct StaticQuestInfo")
    lines.append("\t{")
    lines.append("\t\tstd::uint32_t localFormID;  // 记录号（已去掉文件内的 master 前缀）")
    lines.append("\t\tstd::uint8_t  master;       // kQuestMasters[] 下标（记录来自哪个插件）")
    lines.append("\t\tstd::uint8_t  type;")
    lines.append("\t\t// QUST DNAM 头 4 字节（uint32，小端）—— 目前**只用于运行时诊断日志**：")
    lines.append("\t\t// 拿它和「引擎已开始的那几条」对一下，看哪一位才是「引擎自动启动」。")
    lines.append("\t\t// ★ 第 10 轮已从 xEdit 导出里读到 flag 名：位0 = Start Game Enabled。")
    lines.append("\t\t// 布局证据见 tools/esm/gen_quest_table.py::dnam_flags。")
    lines.append("\t\tstd::uint32_t staticFlags;")
    lines.append("\t\t// 引导目标（第 10 轮；★ 第 45 轮升级为**候选池**）：这条任务「去哪里接」——")
    lines.append("\t\t// 一个按质量排序的引用候选列表（见下方 kGuideCandidates）。运行时 DLL 取")
    lines.append("\t\t// 「此刻引擎里取得到」的第一个候选（= 质量最优的可用目标）；脚本报取不到时")
    lines.append("\t\t// 还会换下一个。candCount == 0 = 没有可用引导目标（照常显示，只是引导不可用）。")
    lines.append("\t\t// 生成器：tools/esm/gen_guide_targets.py（候选排序规则见该文件头注释）。")
    lines.append("\t\tstd::uint32_t candBegin;  // 候选切片起点（kGuideCandidates 下标）")
    lines.append("\t\tstd::uint8_t  candCount;  // 候选数（0 = 没有可用引导目标）")
    lines.append("\t\t// ★ 第 35 轮：进度门槛切片（见下方 kQuestConds 与 docs/08）——")
    lines.append("\t\t//   condCount > 0 时：全部门槛为真 ⇒ 显示；任一为假 = 「进度没到」⇒ 隐藏。")
    lines.append("\t\t//   condCount == 0 ⇒ 这条任务不做条件过滤（无门槛 / 门槛不可求值）。")
    lines.append("\t\tstd::uint32_t condBegin;")
    lines.append("\t\tstd::uint8_t  condCount;")
    lines.append("\t\t// ★ 大项 D（第 48 轮）：INFO 门槛切片（见下方 kInfoGroups / kInfoConds）——")
    lines.append("\t\t//   infoGroupCount > 0 时：**全部参与判定的对话**都至少有「一条已知为假」的")
    lines.append("\t\t//   条件 ⇒ 隐藏（进度没到）；任一对话的条件全为真/不可判定 ⇒ 显示。")
    lines.append("\t\t//   infoGroupCount == 0 ⇒ 这条任务不做 INFO 过滤。")
    lines.append("\t\tstd::uint32_t infoGroupBegin;")
    lines.append("\t\tstd::uint8_t  infoGroupCount;")
    lines.append("\t\t// ★★ 第 67 轮：任务链门槛切片（见下方 kChainGates）——")
    lines.append("\t\t//   本任务是「编号任务链」里的后续环节（数据来源 = 官方 Papyrus 源码里的")
    lines.append("\t\t//   启动边，如 `CF01` 的 stage 1000 fragment 里 `CF02.SetStage(10)`）。")
    lines.append("\t\t//   判据：chainCount > 0 时，**全部链边都还没触发 ⇒ 隐藏**（进度没到 ——")
    lines.append("\t\t//   玩家还没做完前一个任务，这个后续任务根本接不到，比如深红舰队线的")
    lines.append("\t\t//   CF02「菜鸟觐见」在 CF01 没做之前不该出现在「可接任务」里）；")
    lines.append("\t\t//   任一条边已触发（或求值不了）⇒ 放行（保守）。")
    lines.append("\t\t//   chainCount == 0 ⇒ 这条任务不做链式过滤。")
    lines.append("\t\tstd::uint32_t chainBegin;")
    lines.append("\t\tstd::uint8_t  chainCount;")
    lines.append("\t\tconst char*   whereEn;  // 目标所在地（城市/飞船），日志与 UI 提示用")
    lines.append("\t\tconst char*   whereZh;")
    lines.append("\t\tconst char*   nameEn;")
    lines.append("\t\tconst char*   nameZh;")
    lines.append("\t\t// ★ 第 65 轮（任务专属图标）：原版 UI 的阵营枚举（iFaction）——")
    lines.append("\t\t//   由 QUST 的 FTYP 关键字（FactionType*）映射而来，-1 = 无阵营。")
    lines.append("\t\t//   界面用它 + type 决定列表图标（Shared.QuestUtils.GetQuestIconLabel）：")
    lines.append("\t\t//     type=活动 → \"Activities\"；有阵营 → 阵营徽记；")
    lines.append("\t\t//     type=杂项/任务 → \"Misc\" / \"Missions\"；其余 → \"None\"。")
    lines.append("\t\t//   枚举顺序 = ui/missionmenu/src/Shared/FactionUtils.as：")
    lines.append("\t\t//     0=Paradiso 1=UnitedColonies 2=RyujinIndustries 3=HouseVaruun 4=Freestar")
    lines.append("\t\t//     5=BlackFleet 6=Constellation 7=TrackersAlliance 8=TerranArmada 9=Creations")
    lines.append("\t\t//   数据源：ref/faction_types.json（tools/esm/gen_faction_types.py）。")
    lines.append("\t\tstd::int8_t   faction;")
    lines.append("\t\t// ★★ 第 74 轮（同伴好感度任务）：这条属于哪位同伴。")
    lines.append("\t\t//   -1 = 不是同伴任务；>= 0 = kCompanionNamesZh/En 的下标（任务名前缀就是它）。")
    lines.append("\t\t//   数据源：ref/companion_quests.json（tools/esm/gen_companion_quests.py；")
    lines.append("\t\t//   名字从官方承诺任务名解析、启动路径对着官方 Papyrus 源码核验）。")
    lines.append("\t\tstd::int8_t   companion;")
    lines.append("\t\t// ★★ 第 74 轮：「**入口**同伴任务」= 个人任务（COM_Quest_<同伴>_Q01）—— 它是")
    lines.append("\t\t//   这条线的第一环（由好感度里程碑直接启动）⇒ **固定显示**（不做进度 / INFO /")
    lines.append("\t\t//   链式门槛过滤），界面按载荷第 8 列在描述里提示「需要一定好感度才能接取」。")
    lines.append("\t\t//   1 = 是；0 = 否（不是同伴任务，或同伴线的**后续**任务 —— 承诺任务照旧走")
    lines.append("\t\t//   链式门槛：前置好感度里程碑没到就不显示，见 kChainGates 里的同伴边）。")
    lines.append("\t\t//   玩家要求：「把所有达到一定好感度才能接到的同伴任务固定在可接任务列表里」")
    lines.append("\t\t//   + 「链式关系的后续任务还是不要显示，只显示入口任务」。")
    lines.append("\t\tstd::uint8_t  companionPin;")
    lines.append("\t\t// ★★ 第 75 轮（四大势力开头任务）：这条是不是「四大势力开头任务」——")
    lines.append("\t\t//   -1 = 不是；>= 0 = kFactionEntryNamesZh/En 的下标（**同时是固定顺序**：")
    lines.append("\t\t//   0 = 联合殖民地先锋队 / 1 = 自由星游骑兵 / 2 = 龙神工业 / 3 = 深红舰队）。")
    lines.append("\t\t//   语义（玩家 2026-09-21 要求「固定显示，并固定排在可接任务列表的前四个；")
    lines.append("\t\t//   除了深红舰队，其他都能正常引导；深红舰队只保留简要说明」）：")
    lines.append("\t\t//     * **固定显示**：跳过进度 / INFO / 链式三类门槛（同同伴「入口」任务）；")
    lines.append("\t\t//     * **固定排前四**：列表排序时这一组最靠前（按本列升序），")
    lines.append("\t\t//       载荷（C++ 推送 + 内嵌回退）与界面顺序逐条对齐；")
    lines.append("\t\t//     * **简要说明**：kFactionEntryNotesZh/En 的同一下标 —— C++ 写进载荷最后")
    lines.append("\t\t//       两列，界面把它当描述的第一句（「加入方式 / 前置条件」）；")
    lines.append("\t\t//     * 「深红舰队」那条（guide=false 的数据）在生成期就被**清空引导候选**")
    lines.append("\t\t//       （candCount == 0）⇒ 界面按「不可导航」处理（点击给提示、描述写明原因）。")
    lines.append("\t\t//   数据源：ref/faction_entry_quests.json（tools/esm/gen_faction_entry_quests.py；")
    lines.append("\t\t//   核验「势力线第一环」+ 引导候选 + 阵营枚举 + 说明文本）。")
    lines.append("\t\tstd::int8_t   factionEntry;")
    lines.append("\t\t// ★★ 第 81 轮（地球地标任务）：「雪景球」收集线的 10 条 ——")
    lines.append("\t\t//   -1 = 不是；>= 0 = kLandmarkNotesZh/En 的下标（**描述里的说明文本**，")
    lines.append("\t\t//   载荷最后两列）。这 10 条（阿波罗 / 开罗 / … / 圣路易斯）在数据里是")
    lines.append("\t\t//   「拾取对应书籍 ⇒ 任务 SetStage(100)」的 Activities（书上挂着官方脚本")
    lines.append("\t\t//   defaultrefoncontainerchangedto）⇒ 进「可接任务」列表（豁免 filter_reason")
    lines.append("\t\t//   的「地标」规则），引导目标 = 书（或书商）的引用 + 同 cell / world 级常驻兜底。")
    lines.append("\t\t//   伦敦那条没有固定接取点（书在各书店/书堆）⇒ 候选为空，只给说明。")
    lines.append("\t\t//   数据源：ref/landmark_quests.json（tools/esm/gen_landmark_quests.py；")
    lines.append("\t\t//   核验「书的 VMAD 属性 QuestToSetOrCheck/StageToSet」+ 世界引用 + 兜底常驻）。")
    lines.append("\t\tstd::int8_t   landmark;")
    lines.append("\t\t// ★★ 第 89 轮（可重复任务）：这条任务「做完一次还能再接」——")
    lines.append("\t\t//   -1 = 不是；>= 0 = kRepeatableNotesZh/En 的下标（描述里写「（可重复）…」）。")
    lines.append("\t\t//   语义（玩家 2026-09-22 反馈「Denis Averin 也给重复任务，列表里却没有他」）：")
    lines.append("\t\t//     * **豁免「已完成」过滤**：这类任务完成一次后**继续留在列表里**")
    lines.append("\t\t//       （它们设计上还能再接 —— 判据见 Decision::DecideRuntimeFilter 的 repeatable 参数）；")
    lines.append("\t\t//     * **描述标注**：说明写进载荷最后两列（同势力开头 / 地标任务的通路）；")
    lines.append("\t\t//     * **载荷第 11 列** = 可重复标记（\"1\"/\"0\"）—— AS3 侧 FilterKnownQuests 据此")
    lines.append("\t\t//       豁免「在玩家日志里」的丢弃（已完成 + 可重复 ⇒ 保留；进行中照旧隐藏）。")
    lines.append("\t\t//   数据源：ref/repeatable_quests.json（tools/esm/gen_repeatable_quests.py；")
    lines.append("\t\t//   人工清单 + 构建期核验 —— 证据见 docs/11-可重复任务盘点（第89轮）.md）。")
    lines.append("\t\tstd::int8_t   repeatable;")
    lines.append("\t};")
    lines.append("")
    lines.append("\t// 进度门槛（第 35 轮，「游戏进度还不能让玩家接到 ⇒ 不显示」）：")
    lines.append("\t//   任务记录级条件（CTDA）里「引用别的任务」的进度检查，")
    lines.append("\t//   只收 GetQuestRunning / GetQuestCompleted / GetStageDone（等于比较、Run On=Subject）。")
    lines.append("\t//   自引用条件（GetQuestRunning(自己)==0 之类）是引擎启动流程的防重入守卫，")
    lines.append("\t//   **不算门槛**（第 11 轮教训：RAD05 引擎提前 started、条件为假但玩家仍能接到）。")
    lines.append("\t//   数据链：xEdit dump → tools/esm/analyze_ctda.py（ctda_gates.json）→ 本表。")
    lines.append("\tenum CondCheck : std::uint8_t")
    lines.append("\t{")
    lines.append("\t\tkCondRunning   = 0,  // 目标任务的 IsRunning")
    lines.append("\t\tkCondCompleted = 1,  // 目标任务的 IsCompleted")
    lines.append("\t\tkCondStageDone = 2,  // 目标任务的 stage 已完成（引擎 IsStageDone）")
    lines.append("\t};")
    lines.append("\tstruct StaticCondGate")
    lines.append("\t{")
    lines.append("\t\tstd::uint32_t questLocal;   // 被检查的任务（记录号）")
    lines.append("\t\tstd::uint8_t  questMaster;  // kQuestMasters[] 下标")
    lines.append("\t\tstd::uint8_t  check;        // CondCheck")
    lines.append("\t\tstd::uint8_t  want;         // 期望值：函数结果 == want ⇒ 本条通过")
    lines.append("\t\tstd::uint16_t stage;        // 仅 kCondStageDone 用")
    lines.append("\t\t// ★★ 第 87 轮：CTDA type 的 bit0（OR，引擎语义见 docs/08 4.3）——")
    lines.append("\t\t//   1 = 本条**开始一个 OR 组**（组 = 从本条起直到第一条不带 OR 位的条件（含）")
    lines.append("\t\t//   或列表末尾；组内相互 OR、组作为整体 AND）。运行时组合见")
    lines.append("\t\t//   Decision::DecideProgressGates（有单测）。")
    lines.append("\t\tstd::uint8_t  orBit;")
    lines.append("\t};")
    lines.append("\tinline constexpr StaticCondGate kQuestConds[] = {")
    if cond_flat:
        for (ql, qm, chk, want, stage, orb) in cond_flat:
            lines.append(f"\t\t{{ 0x{ql:08X}u, {qm}u, {chk}u, {want}u, {stage}u, {orb}u }},")
    else:
        lines.append("\t\t{ 0u, 0u, 0u, 0u, 0u, 0u },  // 占位（表为空时 MSVC 不允许零长数组）")
    lines.append("\t};")
    lines.append(f"\tinline constexpr std::size_t kQuestCondCount = {len(cond_flat)};")
    lines.append("")
    lines.append("\t// ★★ 大项 D（第 48 轮）：INFO 门槛（对话侧进度条件）——")
    lines.append("\t//   任务自己的对话（INFO）里「任务还没开始时才出现」的入口类 + 中性类对话，")
    lines.append("\t//   其条件「引用别的任务」的进度检查（形态同 StaticCondGate，")
    lines.append("\t//   ★ 第 106 轮起带 OR 位 —— 一条对话内：无 OR 位的条件相互 AND、")
    lines.append("\t//   OR 组（自带 OR 位那条起、含关闭组的第一条无 OR 位条件）组内相互 OR）。")
    lines.append("\t//   运行时判据（见 SAQ_QuestCond.cpp::EvaluateInfoGates）：")
    lines.append("\t//     每一条对话 = 一组条件（AND）；**全部对话都至少有「一条已知为假」"
               "的条件** ⇒ 隐藏。")
    lines.append("\t//   任何一条对话的条件「全为真 / 不可判定」 ⇒ 可能可用 ⇒ 显示（保守）。")
    lines.append("\t//   数据链：scan_info_gates.py → analyze_info_gates.py → 本表；设计见 docs/08。")
    lines.append("\tstruct StaticInfoGroup")
    lines.append("\t{")
    lines.append("\t\tstd::uint16_t condBegin;  // 本条对话的条件切片起点（kInfoConds 下标）")
    lines.append("\t\tstd::uint16_t condCount;")
    lines.append("\t};")
    lines.append("\tinline constexpr StaticInfoGroup kInfoGroups[] = {")
    if info_group_flat:
        for (cb, cc) in info_group_flat:
            lines.append(f"\t\t{{ {cb}u, {cc}u }},")
    else:
        lines.append("\t\t{ 0u, 0u },  // 占位（表为空时 MSVC 不允许零长数组）")
    lines.append("\t};")
    lines.append(f"\tinline constexpr std::size_t kInfoGroupCount = {len(info_group_flat)};")
    lines.append("\tinline constexpr StaticCondGate kInfoConds[] = {")
    if info_cond_flat:
        for (ql, qm, chk, want, stage, orb) in info_cond_flat:
            lines.append(f"\t\t{{ 0x{ql:08X}u, {qm}u, {chk}u, {want}u, {stage}u, {orb}u }},")
    else:
        lines.append("\t\t{ 0u, 0u, 0u, 0u, 0u, 0u },  // 占位（表为空时 MSVC 不允许零长数组）")
    lines.append("\t};")
    lines.append(f"\tinline constexpr std::size_t kInfoCondCount = {len(info_cond_flat)};")
    lines.append("")
    lines.append("\t// ★★ 第 67 轮：任务链门槛（「上一个任务的收尾 stage 启动下一个任务」）——")
    lines.append("\t//   数据来源：官方 Papyrus 源码（CK 的 Data\\Scripts\\Source\\Base）里的跨任务")
    lines.append("\t//   启动调用；提取规则见 tools/esm/gen_quest_chain.py 头注释（只认「编号链路」：")
    lines.append("\t//   前缀相同、编号 +1、调用方是纯编号任务、调用发生在 stage fragment 里）。")
    lines.append("\t//   ★★ 第 69 轮：并入**扩展边**（gen_quest_chain_extra.py；同一形态的非编号链路 ——")
    lines.append("\t//   Eleos 静修地线 / 霓虹城帮派线 / 城市支线预启动；每条都人工核实 + 构建期对着")
    lines.append("\t//   官方 Papyrus 源码核验；判据与语义完全一致，运行时共用本数组）。")
    lines.append("\t//   每条边 = (前置任务, 触发 stage)：后者做完 ⇒ 这条启动边才可能发生。")
    lines.append("\t//   运行时判据（SAQ_QuestCond.cpp::EvaluateChainGates → Decision::DecideChainGates）：")
    lines.append("\t//     * 切片越界 ⇒ 放行（kUnknown）；")
    lines.append("\t//     * 任一条边的 stage 已完成 ⇒ 放行（kPass，保守）；")
    lines.append("\t//     * 全部边都未完成 ⇒ 隐藏（kFail）—— 这是本 MOD「进度没到不显示」的第三判据。")
    lines.append("\tstruct StaticChainGate")
    lines.append("\t{")
    lines.append("\t\tstd::uint32_t hostLocal;   // 前置任务（记录号）")
    lines.append("\t\tstd::uint8_t  hostMaster;  // kQuestMasters[] 下标")
    lines.append("\t\tstd::uint16_t hostStage;   // 该任务的哪个 stage 触发（已完成 ⇒ 边已触发）")
    lines.append("\t};")
    lines.append("\tinline constexpr StaticChainGate kChainGates[] = {")
    if chain_flat:
        for (hl, hm, hs) in chain_flat:
            lines.append(f"\t\t{{ 0x{hl:08X}u, {hm}u, {hs}u }},")
    else:
        lines.append("\t\t{ 0u, 0u, 0u },  // 占位（表为空时 MSVC 不允许零长数组）")
    lines.append("\t};")
    lines.append(f"\tinline constexpr std::size_t kChainGateCount = {len(chain_flat)};")
    lines.append("")
    lines.append("\t// ★ 第 45 轮：引导目标候选池（按质量排序；每条任务用 candBegin/candCount 切片）。")
    lines.append("\t//   flags bit0 = persistent（常驻引用 —— 脚本任何时候都取得到，是「玩家在远处」的备胎）。")
    lines.append("\t//   生成：gen_guide_targets.py 的 cands 数组（排序规则见那个文件头注释）。")
    lines.append("\tstruct StaticGuideCandidate")
    lines.append("\t{")
    lines.append("\t\tstd::uint32_t refrLocal;   // 记录号（已按 refrSmall 去掉文件内前缀）")
    lines.append("\t\tstd::uint8_t  refrMaster;  // kQuestMasters[] 下标（引用可能属于别的 master）")
    lines.append("\t\tstd::uint8_t  flags;       // bit0 = persistent")
    lines.append("\t\tstd::uint16_t _reserved;   // 对齐占位")
    lines.append("\t\tconst char*   nameZh;      // 候选展示名（NPC 名 / 地点名 / 内部名）—— 只用于日志")
    lines.append("\t};")
    lines.append("\tinline constexpr StaticGuideCandidate kGuideCandidates[] = {")
    if cand_flat:
        for (local, cm, cp, cname) in cand_flat:
            lines.append(f'\t\t{{ 0x{local:06X}u, {cm}u, 0x{cp:02X}u, 0u, "{c_escape(cname)}" }},')
    else:
        lines.append('\t\t{ 0u, 0u, 0u, 0u, "" },  // 占位（表为空时 MSVC 不允许零长数组）')
    lines.append("\t};")
    lines.append(f"\tinline constexpr std::size_t kGuideCandidateCount = {len(cand_flat)};")
    lines.append("")
    lines.append("\t// ★★ 第 74 轮（同伴好感度任务）：同伴显示名（下标 = StaticQuestInfo::companion）——")
    lines.append("\t//   中英各一份（界面按游戏语言选；静态表的名字已经带了这个前缀）。")
    lines.append("\t//   数据源：ref/companion_quests.json（从官方「承诺：<同伴>」/「Commitment: <同伴>」")
    lines.append("\t//   里解析而来 —— 不写死名字）。")
    lines.append("\tinline constexpr const char* kCompanionNamesZh[] = {")
    for g in companions:
        lines.append(f'\t\t"{c_escape(g["nameZh"])}",')
    if not companions:
        lines.append('\t\t"",  // 占位（表为空时 MSVC 不允许零长数组）')
    lines.append("\t};")
    lines.append("\tinline constexpr const char* kCompanionNamesEn[] = {")
    for g in companions:
        lines.append(f'\t\t"{c_escape(g["nameEn"])}",')
    if not companions:
        lines.append('\t\t"",  // 占位（表为空时 MSVC 不允许零长数组）')
    lines.append("\t};")
    lines.append(f"\tinline constexpr std::size_t kCompanionCount = {len(companions)};")
    lines.append("")
    lines.append("\t// ★★ 第 75 轮（四大势力开头任务）：显示名 / 「简要说明」（下标 = StaticQuestInfo::")
    lines.append("\t//   factionEntry；**顺序就是固定顺序** —— 联合殖民地 → 自由星 → 龙神 → 深红舰队）。")
    lines.append("\t//   说明由 C++ 写进载荷最后两列（界面描述里的第一句）；")
    lines.append("\t//   数据源：ref/faction_entry_quests.json（gen_faction_entry_quests.py）。")
    lines.append("\tinline constexpr const char* kFactionEntryNamesZh[] = {")
    for g in faction_entries:
        lines.append(f'\t\t"{c_escape(g["nameZh"])}",')
    if not faction_entries:
        lines.append('\t\t"",  // 占位（表为空时 MSVC 不允许零长数组）')
    lines.append("\t};")
    lines.append("\tinline constexpr const char* kFactionEntryNamesEn[] = {")
    for g in faction_entries:
        lines.append(f'\t\t"{c_escape(g["nameEn"])}",')
    if not faction_entries:
        lines.append('\t\t"",  // 占位（表为空时 MSVC 不允许零长数组）')
    lines.append("\t};")
    lines.append("\tinline constexpr const char* kFactionEntryNotesZh[] = {")
    for g in faction_entries:
        lines.append(f'\t\t"{c_escape(g["noteZh"])}",')
    if not faction_entries:
        lines.append('\t\t"",  // 占位（表为空时 MSVC 不允许零长数组）')
    lines.append("\t};")
    lines.append("\tinline constexpr const char* kFactionEntryNotesEn[] = {")
    for g in faction_entries:
        lines.append(f'\t\t"{c_escape(g["noteEn"])}",')
    if not faction_entries:
        lines.append('\t\t"",  // 占位（表为空时 MSVC 不允许零长数组）')
    lines.append("\t};")
    lines.append(f"\tinline constexpr std::size_t kFactionEntryCount = {len(faction_entries)};")
    lines.append("")
    lines.append("\t// ★★ 第 81 轮（地球地标任务）：「去哪拿哪本书」（下标 = StaticQuestInfo::landmark）——")
    lines.append("\t//   与势力开头的说明同一个通路（载荷最后两列，界面把它当描述第一句）。")
    lines.append("\t//   数据源：ref/landmark_quests.json（gen_landmark_quests.py）。")
    lines.append("\tinline constexpr const char* kLandmarkNotesZh[] = {")
    for g in landmarks:
        lines.append(f'\t\t"{c_escape(g["noteZh"])}",')
    if not landmarks:
        lines.append('\t\t"",  // 占位（表为空时 MSVC 不允许零长数组）')
    lines.append("\t};")
    lines.append("\tinline constexpr const char* kLandmarkNotesEn[] = {")
    for g in landmarks:
        lines.append(f'\t\t"{c_escape(g["noteEn"])}",')
    if not landmarks:
        lines.append('\t\t"",  // 占位（表为空时 MSVC 不允许零长数组）')
    lines.append("\t};")
    lines.append(f"\tinline constexpr std::size_t kLandmarkCount = {len(landmarks)};")
    lines.append("")
    lines.append("\t// ★★ 第 89 轮（可重复任务）：「（可重复）…」（下标 = StaticQuestInfo::repeatable）——")
    lines.append("\t//   与前面两个说明同一通路（载荷最后两列，界面把它当描述第一句）。")
    lines.append("\t//   数据源：ref/repeatable_quests.json（gen_repeatable_quests.py）。")
    lines.append("\tinline constexpr const char* kRepeatableNotesZh[] = {")
    for g in repeatables:
        lines.append(f'\t\t"{c_escape(g["noteZh"])}",')
    if not repeatables:
        lines.append('\t\t"",  // 占位（表为空时 MSVC 不允许零长数组）')
    lines.append("\t};")
    lines.append("\tinline constexpr const char* kRepeatableNotesEn[] = {")
    for g in repeatables:
        lines.append(f'\t\t"{c_escape(g["noteEn"])}",')
    if not repeatables:
        lines.append('\t\t"",  // 占位（表为空时 MSVC 不允许零长数组）')
    lines.append("\t};")
    lines.append(f"\tinline constexpr std::size_t kRepeatableCount = {len(repeatables)};")
    lines.append("")
    lines.append(f"\tinline constexpr StaticQuestInfo kQuestTable[] = {{")
    for r in rows:
        flags = int(r.get("dnam_flags", 0))
        lines.append(
            f'\t\t{{ 0x{int(r["local"]):08X}u, {master_idx[r["master"]]}u, {r["itype"]}u,'
            f' 0x{flags:08X}u, {int(r["cand_begin"])}u, {int(r["cand_count"])}u,'
            f' {int(r.get("cond_begin", 0))}u, {int(r.get("cond_count", 0))}u,'
            f' {int(r.get("info_group_begin", 0))}u, {int(r.get("info_group_count", 0))}u,'
            f' {int(r.get("chain_begin", 0))}u, {int(r.get("chain_count", 0))}u,'
            f' "{c_escape(r["guide_where_en"])}", "{c_escape(r["guide_where_zh"])}",'
            f' "{c_escape(r["name_en"])}", "{c_escape(r["name_zh"])}",'
            f' {int(r.get("faction", -1))}, {int(r.get("companion", -1))},'
            f' {int(r.get("companion_pin", 0))}u, {int(r.get("faction_entry", -1))},'
            f' {int(r.get("landmark", -1))}, {int(r.get("repeatable", -1))} }},'
        )
    lines.append("\t};")
    lines.append(f"\tinline constexpr std::size_t kQuestTableSize = {len(rows)};")
    lines.append("}")
    lines.append("")

    out = Path(a.out_header)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines), encoding="utf-8")
    print(f"wrote {out} ({out.stat().st_size} B)")

    Path(a.out_json).write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"wrote {a.out_json}")

    # AS3 内嵌回退数据（C++ 推送失败时 SWF 自己也能显示列表）
    #
    # ★ 只放基础游戏的条目：内嵌载荷要写**运行期 FormID**，而 DLC 的 FormID 高字节
    #   取决于加载顺序（离线算不出来）。放进来的话「点一下它去引导」会拿错 FormID。
    #   代价只是：C++ 推送失败的那 0.3~0.8 秒里列表里看不到 DLC 条目（可接受的降级）。
    as3_path = Path(a.out_as3)
    base_rows = [r for r in rows if r["master"] == "Starfield.esm"]
    n = write_as3_fragment(base_rows, as3_path)
    print(f"wrote {as3_path}（内嵌回退只含 Starfield.esm 的 {len(base_rows)} 条；"
          f"载荷 {n} 字符 / {as3_path.stat().st_size} B）")

    # 抽样打印（每个 master 各来几条，便于人工核对 DLC 的名字对不对）
    print("\n样本：")
    for m in masters:
        ms = [r for r in rows if r["master"] == m]
        for r in ms[:4]:
            print(f"  {m} 0x{r['local']:06X} [{r['qtype']:10s}] zh={r['name_zh']} / en={r['name_en']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
