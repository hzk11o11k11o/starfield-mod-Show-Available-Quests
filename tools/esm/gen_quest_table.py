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


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--quests", default="ref/quests.json")
    ap.add_argument("--strings-dir", default="ref/strings/strings")
    ap.add_argument("--out-header", default="plugin/src/SAQ_QuestTable.h")
    ap.add_argument("--out-json", default="ref/quest_table_debug.json")
    ap.add_argument("--out-as3", default="ui/missionmenu/saqdata/SaqEmbeddedPayload.inc")
    ap.add_argument("--include-main", action="store_true")
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
        name_en = clean_name(en.get(full, "") if full else "", False)
        name_zh = clean_name(zh.get(full, "") if full else "", True)
        edid = q.get("edid") or ""
        if not name_en:
            name_en = edid
        if not name_zh:
            name_zh = name_en
        rows.append({
            "formid": q["formid"],
            "edid": edid,
            "itype": itype,
            "qtype": QTYPE_NAMES.get(qtyp, ""),
            "name_en": name_en,
            "name_zh": name_zh,
            "dnam": q.get("dnam", ""),
        })

    rows.sort(key=lambda r: r["formid"])
    print(f"table rows: {len(rows)}（跳过无类型 {skipped_no_type}，跳过主线 {skipped_main}）")

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
    lines.append("\t\tconst char*   nameEn;")
    lines.append("\t\tconst char*   nameZh;")
    lines.append("\t};")
    lines.append("")
    lines.append(f"\tinline constexpr StaticQuestInfo kQuestTable[] = {{")
    for r in rows:
        fid = r["formid"] if isinstance(r["formid"], int) else int(r["formid"], 16)
        lines.append(
            f'\t\t{{ 0x{fid:08X}u, {r["itype"]}u, "{c_escape(r["name_en"])}", "{c_escape(r["name_zh"])}" }},'
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
