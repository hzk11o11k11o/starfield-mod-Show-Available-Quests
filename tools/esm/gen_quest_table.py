#!/usr/bin/env python3
"""gen_quest_table.py - 生成插件内嵌的静态任务表（FormID -> 中/英文名 + 类型）。

输入：
    ref/quests.json                         quest_dump.py 的全量导出（含 FULL 字符串 ID）
    ref/strings/strings/starfield_en.strings
    ref/strings/strings/starfield_zhhans.strings
输出：
    plugin/src/SAQ_QuestTable.h             C++ 静态数组
    ref/quest_table_debug.json              同样的数据（便于人工核对）

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
    if edid_l.startswith("com_companion"):
        return "同伴系统"             # 同伴管理主任务（玩家不会「接」）
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
    """与 C++ 侧 BuildPayloadUtf8 完全同格式的载荷（AS3 内嵌回退用）。"""
    lines = ["SAQ1", f"T\t{title_zh}\t{title_en}"]
    for r in rows:
        fid = r["formid"] if isinstance(r["formid"], int) else int(r["formid"], 16)
        lines.append(
            f'Q\t{fid}\t{r["itype"]}\t{sanitize_name(r["name_zh"])}\t{sanitize_name(r["name_en"])}'
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


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--quests", default="ref/quests.json")
    ap.add_argument("--strings-dir", default="ref/strings/strings")
    ap.add_argument("--guide-targets", default="ref/guide_targets.json")
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
    en = load_strings(base / "starfield_en.strings")
    zh = load_strings(base / "starfield_zhhans.strings")

    quests = json.loads(Path(a.quests).read_text(encoding="utf-8"))
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
            "formid": q["formid"],
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

    rows.sort(key=lambda r: r["formid"])

    # 引导目标（第 10 轮）：每条任务在世界里的一个「去哪里接」引用。
    # 没有引导目标的任务照样进表（列表照常显示，只是不能引导）。
    guides = load_guide_targets(Path(a.guide_targets))
    n_guide = 0
    for r in rows:
        g = guides.get(r["formid"])
        if g and g.get("refr"):
            r["guide_ref"] = int(g["refr"])
            r["guide_kind"] = g.get("kind", "")
            r["guide_where_en"] = (g.get("whereEn") or "").strip()
            r["guide_where_zh"] = (g.get("whereZh") or "").strip()
            n_guide += 1
        else:
            r["guide_ref"] = 0
            r["guide_kind"] = ""
            r["guide_where_en"] = ""
            r["guide_where_zh"] = ""

    print(f"table rows: {len(rows)}（无类型 {skipped_no_type}，主线 {skipped_main}）；"
          f"其中带引导目标 {n_guide} 条（{n_guide * 100 // max(len(rows), 1)}%）")
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
    lines.append("// 数据来源：Starfield.esm 的 QUST 记录 + starfield_en/zhhans.strings")
    lines.append("//")
    lines.append("// itype 与 AS3 侧 Shared.QuestUtils 的枚举一致：")
    lines.append("//   0=Activities 1=Main 2=Factions 3=Misc 4=Mission")
    lines.append("")
    lines.append("#include <cstdint>")
    lines.append("")
    lines.append("namespace SAQ")
    lines.append("{")
    lines.append("\tstruct StaticQuestInfo")
    lines.append("\t{")
    lines.append("\t\tstd::uint32_t formID;")
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
    lines.append("\t\tstd::uint32_t guideRef;")
    lines.append("\t\tconst char*   whereEn;  // 目标所在地（城市/飞船），日志与 UI 提示用")
    lines.append("\t\tconst char*   whereZh;")
    lines.append("\t\tconst char*   nameEn;")
    lines.append("\t\tconst char*   nameZh;")
    lines.append("\t};")
    lines.append("")
    lines.append(f"\tinline constexpr StaticQuestInfo kQuestTable[] = {{")
    for r in rows:
        fid = r["formid"] if isinstance(r["formid"], int) else int(r["formid"], 16)
        flags = int(r.get("dnam_flags", 0))
        lines.append(
            f'\t\t{{ 0x{fid:08X}u, {r["itype"]}u, 0x{flags:08X}u, 0x{int(r["guide_ref"]):08X}u,'
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
    as3_path = Path(a.out_as3)
    n = write_as3_fragment(rows, as3_path)
    print(f"wrote {as3_path}（载荷 {n} 字符 / {as3_path.stat().st_size} B）")

    # 抽样打印
    print("\n样本：")
    for r in rows[:5]:
        print(f"  0x{r['formid']} [{r['qtype']}] zh={r['name_zh']} / en={r['name_en']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
