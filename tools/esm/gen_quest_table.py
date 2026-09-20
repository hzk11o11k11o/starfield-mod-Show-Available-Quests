#!/usr/bin/env python3
"""gen_quest_table.py - 生成插件内嵌的静态任务表（master + 记录号 -> 中/英文名 + 类型）。

输入：
    ref/quests_all.json                     quest_dump.py 的多 master 导出（Starfield.esm + 各 DLC）
    ref/strings/strings/<master>_en.strings        每个 master 一份字符串表（名字里带 FULL 的字符串 ID）
    ref/strings/strings/<master>_zhhans.strings    master 名小写去掉扩展名，与游戏内 strings 文件同名
输出：
    plugin/src/SAQ_QuestTable.h             C++ 静态数组（多 master）
    ref/quest_table_debug.json              同样的数据（便于人工核对）

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


def filter_reason(row: dict, raw_en: str, raw_zh: str) -> str | None:
    """判断一条任务是不是「内部任务」（不该出现在可接列表里）。

    返回 None = 保留；否则返回被排除的原因标签（统计/日志用）。
    所有判据都是**离线可验证**的显示层信号；运行时状态过滤（已接/条件）在 C++/AS3 侧。
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
    if "pointer" in edid_l or "pointer" in en_l or "指示器" in zh or "指示器" in en:
        return "指示器"               # Misc pointer 系统
    if "landmark" in edid_l or "地标任务" in zh or "地标任务" in en:
        return "地标"                 # 地球地标探索（走近即完成，无从「接」）
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


def build_payload(rows: list[dict], title_zh: str = "可接任务", title_en: str = "Available") -> str:
    """与 C++ 侧 BuildPayloadUtf8 完全同格式的载荷（AS3 内嵌回退用）。

    ★ 第 23 轮：最后一列是「有没有引导目标」（1/0）——界面据此决定这条条目能不能导航。
    """
    lines = ["SAQ1", f"T\t{title_zh}\t{title_en}"]
    for r in rows:
        fid = r["formid"] if isinstance(r["formid"], int) else int(r["formid"], 16)
        has_target = "1" if int(r.get("guide_ref", 0)) else "0"
        lines.append(
            f'Q\t{fid}\t{r["itype"]}\t{sanitize_name(r["name_zh"])}\t{sanitize_name(r["name_en"])}\t{has_target}'
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
        mask = 0xFFF if q.get("small") else 0xFFFFFF
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

    rows = []
    skipped_no_type = 0
    skipped_main = 0
    skipped_reasons: dict[str, int] = {}
    skipped_samples: dict[str, list[str]] = {}

    for q in quests:
        qtyp = q.get("qtyp")
        if qtyp is None:
            skipped_no_type += 1
            continue
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
            "edid": edid,
            "itype": itype,
            "qtype": QTYPE_NAMES.get(qtyp, ""),
            "name_en": name_en,
            "name_zh": name_zh,
            "dnam": q.get("dnam", ""),
            "dnam_flags": dnam_flags(q.get("dnam", "")),
        }
        if not a.keep_internal:
            reason = filter_reason(row, raw_en, raw_zh)
            if reason:
                skipped_reasons[reason] = skipped_reasons.get(reason, 0) + 1
                samples = skipped_samples.setdefault(reason, [])
                if len(samples) < 3:
                    samples.append(f"0x{q['formid']:08X} {edid}")
                continue
        rows.append(row)

    # 排序：master 下标升序（基础游戏在前 —— 列表里同名的以基础游戏为准），再按记录号
    rows.sort(key=lambda r: (master_idx[r["master"]], r["local"]))

    # 引导目标（第 10 轮；第 17 轮加 master）：每条任务在世界里的一个「去哪里接」引用。
    # 没有引导目标的任务照样进表（列表照常显示，只是不能引导）。
    guides = load_guide_targets(Path(a.guide_targets))
    master_by_lower = {m.lower(): i for i, m in enumerate(masters)}
    n_guide = 0
    unknown_guide_master: set[str] = set()
    for r in rows:
        g = guides.get(r["formid"])
        gm = (g or {}).get("refrMaster") or r["master"]
        if g and g.get("refr") and gm.lower() not in master_by_lower:
            unknown_guide_master.add(gm)
            g = None
        if g and g.get("refr"):
            r["guide_ref"] = int(g["refr"]) & (0xFFF if g.get("refrSmall") else 0xFFFFFF)
            r["guide_master"] = master_by_lower[gm.lower()]
            r["guide_kind"] = g.get("kind", "")
            r["guide_where_en"] = (g.get("whereEn") or "").strip()
            r["guide_where_zh"] = (g.get("whereZh") or "").strip()
            n_guide += 1
        else:
            r["guide_ref"] = 0
            r["guide_master"] = 0
            r["guide_kind"] = ""
            r["guide_where_en"] = ""
            r["guide_where_zh"] = ""
    if unknown_guide_master:
        print(f"  !! 引导目标引用了表里没有的 master（先加进任务表）：{sorted(unknown_guide_master)}")

    print(f"table rows: {len(rows)}（无类型 {skipped_no_type}，主线 {skipped_main}）；"
          f"其中带引导目标 {n_guide} 条（{n_guide * 100 // max(len(rows), 1)}%）")

    # ★ 第 35 轮：进度门槛（「游戏进度还不能让玩家接到 ⇒ 不显示」）
    #   数据链：xEdit 条件 dump → analyze_ctda.py（提取外部引用门槛）→ 这里平铺进表。
    gates_by_fid = load_gates(Path(a.gates))
    cond_flat: list[tuple[int, int, int, int, int]] = []
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
                              int(g["func"]), int(g["want"]), int(g.get("stage", 0)) & 0xFFFF))
    print(f"进度门槛：{n_gate_tasks} 条任务 / {len(cond_flat)} 条条件")
    for r in rows:
        if r["cond_count"]:
            desc = []
            for g in r["cond_gates"]:
                name = ("Running", "Completed", "StageDone")[int(g["func"])]
                if int(g["func"]) == 2:
                    desc.append(f"{name}(0x{int(g['quest_local']):06X},{g['stage']})=={g['want']}")
                else:
                    desc.append(f"{name}(0x{int(g['quest_local']):06X})=={g['want']}")
            print(f"  {r['edid']:<34} {' AND '.join(desc)}")

    per_master = Counter(r["master"] for r in rows)
    print("按 master：" + " ".join(f"{m}={per_master[m]}" for m in masters))
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
    lines.append("\t\t// 引导目标（第 10 轮）：这条任务「去哪里接」——世界里的一个引用")
    lines.append("\t\t// （任务发布者 NPC 的放置引用 / 任务自己的落脚点 / 地点地图标记）。")
    lines.append("\t\t// 0 = 这条任务没有可用的引导目标（列表照常显示，只是引导不可用）。")
    lines.append("\t\t// 生成器：tools/esm/gen_guide_targets.py（来源与排序规则见该文件头注释）。")
    lines.append("\t\t// ★ 引用也可能属于别的 master（DLC 任务引用基础游戏的 NPC），所以带下标。")
    lines.append("\t\tstd::uint32_t guideRefLocal;")
    lines.append("\t\tstd::uint8_t  guideRefMaster;")
    lines.append("\t\t// ★ 第 35 轮：进度门槛切片（见下方 kQuestConds 与 docs/08）——")
    lines.append("\t\t//   condCount > 0 时：全部门槛为真 ⇒ 显示；任一为假 = 「进度没到」⇒ 隐藏。")
    lines.append("\t\t//   condCount == 0 ⇒ 这条任务不做条件过滤（无门槛 / 门槛不可求值）。")
    lines.append("\t\tstd::uint32_t condBegin;")
    lines.append("\t\tstd::uint8_t  condCount;")
    lines.append("\t\tconst char*   whereEn;  // 目标所在地（城市/飞船），日志与 UI 提示用")
    lines.append("\t\tconst char*   whereZh;")
    lines.append("\t\tconst char*   nameEn;")
    lines.append("\t\tconst char*   nameZh;")
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
    lines.append("\t};")
    lines.append("\tinline constexpr StaticCondGate kQuestConds[] = {")
    if cond_flat:
        for (ql, qm, chk, want, stage) in cond_flat:
            lines.append(f"\t\t{{ 0x{ql:08X}u, {qm}u, {chk}u, {want}u, {stage}u }},")
    else:
        lines.append("\t\t{ 0u, 0u, 0u, 0u, 0u },  // 占位（表为空时 MSVC 不允许零长数组）")
    lines.append("\t};")
    lines.append(f"\tinline constexpr std::size_t kQuestCondCount = {len(cond_flat)};")
    lines.append("")
    lines.append(f"\tinline constexpr StaticQuestInfo kQuestTable[] = {{")
    for r in rows:
        flags = int(r.get("dnam_flags", 0))
        lines.append(
            f'\t\t{{ 0x{int(r["local"]):08X}u, {master_idx[r["master"]]}u, {r["itype"]}u,'
            f' 0x{flags:08X}u, 0x{int(r["guide_ref"]):08X}u, {int(r["guide_master"])}u,'
            f' {int(r.get("cond_begin", 0))}u, {int(r.get("cond_count", 0))}u,'
            f' "{c_escape(r["guide_where_en"])}", "{c_escape(r["guide_where_zh"])}",'
            f' "{c_escape(r["name_en"])}", "{c_escape(r["name_zh"])}" }},'
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
