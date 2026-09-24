#!/usr/bin/env python3
r"""gen_hirable_crew.py - 生成「可招募船员」入口数据（第 155 轮）。

背景（AGENTS.md 需求 + 玩家提问）：可以被招募为船员的有名字 NPC（精英船员）
能不能像任务板 / 可重复任务 NPC 那样做成「可接任务」条目并跟踪？
第 154 轮研究（`docs/16`、只读工具 `scan_hirable_crew.py`）结论：**能** ——
24 位可招募船员，每人 1 处固定放置引用 + 1 条招募载体任务，两档常驻兜底
（同 cell 11/11 · world 级 5/5）100% 就位。

本工具把研究结论转成**可复现的入口数据**（仿 `gen_repeatable_givers.py`）：

1. 枚举：NPC_ 里 EDID 前缀 `Crew_Elite_*`，排除 `OtherPlayer*` / `BalanceData*` /
   `VascoSarahMisc` 模板 ⇒ 实测 **24 位**（官方 FLST `CREW_imGui_2a_Actors_Elite`
   会漏 `MathisCastillo` / `AdoringFan`，EDID 判据更准 —— 见 docs/16）；
2. 每位找**放置引用**（ACHR：cell / world / 常驻位 / 坐标 / XESP）——
   决定引导候选链的「精确目标」；
3. 每位找**兜底候选**（与任务板 / 可重复 NPC 同一套判据：XMarker 系优先、≤25 m、取 2）：
   * 内景 ⇒ 同 cell 的原生常驻引用；
   * 外景 ⇒ 该 worldspace 的**世界级常驻引用**（`WRLD > WorldChildren > CellChildren
     > CellPersistent`）；
4. 标记**不适合导航**的位置（照第 91 轮「（不可导航）」口径）：
   * `MQHoldingCell` 之类别名暂存格（玩家到不了）；
   * `*CreatedInterior*` 运行时生成内景（货船 / 太空遭遇船——位置不固定）；
5. 记录 crew faction 三件套（`AvailableCrewFaction` 0x00014314 /
   `CurrentCrewFaction` 0x00014312 / `PotentialCrewFaction` 0x000143A2）的挂载情况
   —— 「已招募 ⇒ 隐藏」判据的候选来源（**待实机探针**：harness `crew.probe`）；
6. 每位匹配**招募载体任务** `CREW_EliteCrew_<名字>`（大小写不敏感 —— 官方数据里
   `ErickVonPrice`(NPC) ↔ `ErickvonPrice`(任务) 拼写不同，见 docs/16 16.1）。

产物：
    ref/hirable_crew.json                入口数据（人工核对 / 未来并入 entry table）
    plugin/src/SAQ_TestCrewProbe.h       harness 只读探针 `crew.probe` 的数据表
                                         （仅 SAQ_Test.cpp include，发布构建不含）

复现（约 1~2 分钟；读 Starfield.esm 两遍）：
    python tools/esm/gen_hirable_crew.py
"""
from __future__ import annotations

import json
import math
import re
import struct
import sys
import zlib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from esm_probe import (  # noqa: E402
    DEFAULT_ESM, REF_SIGS, read_records, record_base_form, record_edid, subrecords,
)
from strings_probe import load_strings  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]

# ---- 枚举判据（第 154 轮实测口径，见 docs/16 16.1）----
EDID_PREFIX = "Crew_Elite_"
EXCLUDE_RE = ("OtherPlayer", "BalanceData", "VascoSarahMisc")

# ---- crew faction 三件套（Starfield.esm FormID，docs/16 16.3）----
CREW_FACTIONS = {
    "available": 0x00014314,   # AvailableCrewFaction
    "current": 0x00014312,     # CurrentCrewFaction
    "potential": 0x000143A2,   # PotentialCrewFaction
}

# ---- 不适合导航的位置（照第 91 轮「（不可导航）」口径 + 第 154 轮研究结论）----
#   别名暂存格：玩家永远到不了（判据与 gen_guide_targets.py 的 BAD_CELL_RE 同源）
BAD_CELL_RE = re.compile(r"(aliascell|alias cell|do\s*not\s*delete|holdingcell|holding cell|_hold\b)", re.I)
#   运行时生成的内景：位置不固定（货船 / 太空遭遇船）
CREATED_INTERIOR_RE = re.compile(r"CreatedInterior", re.I)

XMARKER_BASES = {0x3B, 0x34}      # XMarker / XMarkerHeading（与 gen_entry_table.py 同判据）
FALLBACK_MAX_DIST = 25.0          # 兜底候选最大距离（同房间级）


def refr_position(payload: bytes):
    for sig, sp in subrecords(payload):
        if sig == b"DATA" and len(sp) >= 12:
            return struct.unpack_from("<fff", sp, 0)
    return None


def refr_xesp(payload: bytes):
    """XESP = Enable Parent（引用按条件出现）。返回 (parent, flags) 或 None。"""
    for sig, sp in subrecords(payload):
        if sig == b"XESP" and len(sp) >= 4:
            parent = struct.unpack_from("<I", sp, 0)[0]
            flags = sp[4] if len(sp) >= 5 else 0
            return parent, flags
    return None


def walk(buf, cb):
    head = struct.unpack_from("<I", buf, 4)[0]
    pos = 24 + head
    while pos + 24 <= len(buf):
        if buf[pos:pos + 4] != b"GRUP":
            break
        gsize = struct.unpack_from("<I", buf, pos + 4)[0]
        if gsize < 24:
            break
        label = bytes(buf[pos + 8:pos + 12])
        gtype = struct.unpack_from("<i", buf, pos + 12)[0]
        _rec(buf, pos + 24, pos + gsize, [(gtype, label)], 0, 0, cb)
        pos += gsize


def _rec(buf, p, end, chain, cell, world, cb):
    while p + 24 <= end:
        if buf[p:p + 4] == b"GRUP":
            sub = struct.unpack_from("<I", buf, p + 4)[0]
            if sub < 24:
                return
            label = bytes(buf[p + 8:p + 12])
            gtype = struct.unpack_from("<i", buf, p + 12)[0]
            _rec(buf, p + 24, p + sub, chain + [(gtype, label)], cell, world, cb)
            p += sub
            continue
        size = struct.unpack_from("<I", buf, p + 4)[0]
        flags = struct.unpack_from("<I", buf, p + 8)[0]
        formid = struct.unpack_from("<I", buf, p + 12)[0]
        sig = bytes(buf[p:p + 4])
        payload = None
        if flags & 0x00040000:
            if size >= 4:
                try:
                    payload = zlib.decompress(buf[p + 28:p + 24 + size])
                except zlib.error:
                    payload = None
        else:
            payload = buf[p + 24:p + 24 + size]
        p += 24 + size
        if payload is None:
            continue
        ncell, nworld = cell, world
        if sig == b"CELL":
            ncell = formid
        elif sig == b"WRLD":
            nworld = formid
        cb(sig, formid, flags, chain, cell, world, payload)
        cell, world = ncell, nworld


def discover_elite_bases(buf: bytes) -> list[dict]:
    """第一遍：NPC_ 顶层组里按 EDID 前缀找可招募船员（含 FULL 字符串 id + faction 列表）。"""
    out = []
    for formid, _flags, payload in read_records(buf, "NPC_"):
        edid = ""
        full = None
        snams = []
        for s, sp in subrecords(payload):
            if s == b"EDID":
                edid = sp.split(b"\x00")[0].decode("latin1", "replace")
            elif s == b"FULL" and len(sp) >= 4:
                full = struct.unpack_from("<I", sp, 0)[0]
            elif s == b"SNAM" and len(sp) >= 5:
                snams.append((struct.unpack_from("<I", sp, 0)[0], sp[4]))
        if edid.startswith(EDID_PREFIX) and not any(x in edid for x in EXCLUDE_RE):
            out.append({"base": formid, "edid": edid, "full": full, "snams": snams})
    return out


def nav_reason(cell_edid: str) -> str:
    if BAD_CELL_RE.search(cell_edid):
        return "别名暂存格（玩家到不了）"
    if CREATED_INTERIOR_RE.search(cell_edid):
        return "运行时生成的内景（位置不固定）"
    return ""


def c_escape(s: str) -> str:
    return s.replace("\\", "\\\\").replace('"', '\\"')


def main() -> int:
    buf = Path(DEFAULT_ESM).read_bytes()
    print(f"读 {DEFAULT_ESM}（{len(buf)} B）…")

    # ---- 第一遍：枚举 24 位 + 放置引用 + 兜底池（第二遍）+ 招募任务 ----
    elite = discover_elite_bases(buf)
    elite_set = {e["base"] for e in elite}
    print(f"按 EDID 前缀 `{EDID_PREFIX}`（排除模板）发现 {len(elite)} 位可招募船员")

    cell_edid: dict[int, str] = {}
    world_edid: dict[int, str] = {}
    fact_edid: dict[int, str] = {}
    placements: dict[int, list] = {e["base"]: [] for e in elite}
    recruit_quests: dict[str, int] = {}      # EDID.lower() -> formid

    def cb_pass1(sig, formid, flags, chain, cell, world, payload):
        if sig == b"CELL":
            cell_edid[formid] = record_edid(payload)
            return
        if sig == b"WRLD":
            world_edid[formid] = record_edid(payload)
            return
        if sig == b"FACT":
            fact_edid[formid] = record_edid(payload)
            return
        if sig == b"QUST":
            # ★ 口径教训（第 154 轮）：`QUST` 顶层组里**混装** QUST（2077 条）+ INFO/DIAL/
            #   SCEN 20 万+ 条 ⇒ 必须按记录签名分类，否则会把同名 INFO/DIAL 认成任务。
            edid = record_edid(payload)
            if edid.startswith("CREW_EliteCrew_"):
                recruit_quests[edid.lower()] = formid
            return
        if sig not in REF_SIGS:
            return
        base = record_base_form(payload)
        if base not in elite_set:
            return
        types = [g for g, _ in chain]
        placements[base].append({
            "ref": formid, "flags": flags,
            "persistent": bool(flags & 0x400),
            "persistentGroup": bool(types and types[-1] == 8),
            "cell": cell, "world": world,
            "interior": bool(chain and chain[0][1] == b"CELL"),
            "pos": refr_position(payload),
            "xesp": refr_xesp(payload),
        })

    walk(buf, cb_pass1)

    missing = [e["edid"] for e in elite if not placements[e["base"]]]
    if missing:
        print("!! 这些 NPC 没找到 REFR：" + ", ".join(missing))
        return 1

    # 目标 cell（内景兜底范围）与外景 worldspace
    target_cells = {pl["cell"] for e in elite for pl in placements[e["base"]] if pl["interior"]}
    exterior_worlds = {pl["world"] for e in elite for pl in placements[e["base"]] if not pl["interior"]}

    # ---- 第二遍：收集兜底候选（目标 cell 的同 cell 常驻 / 目标 world 的 world 级常驻）----
    pers_by_cell: dict[int, list] = {}
    pers_by_world: dict[int, list] = {}

    def cb_pass2(sig, formid, flags, chain, cell, world, payload):
        if sig not in REF_SIGS:
            return
        types = [g for g, _ in chain]
        if not types or types[-1] != 8:      # 只要「CellPersistent」组里的常驻引用
            return
        pos = refr_position(payload)
        if not pos:
            return
        base = record_base_form(payload)
        if cell in target_cells and chain and chain[0][1] == b"CELL":
            pers_by_cell.setdefault(cell, []).append((base, pos, formid))
        elif world in exterior_worlds and types[0] == 0:
            pers_by_world.setdefault(world, []).append((base, pos, formid))

    walk(buf, cb_pass2)

    def pick_fallbacks(cands, pos, tag):
        scored = []
        for base, cpos, fid in cands:
            d = math.dist(cpos, pos)
            if d > FALLBACK_MAX_DIST:
                continue
            scored.append((0 if base in XMARKER_BASES else 1, d, fid, base))
        scored.sort()
        out = scored[:2]
        txt = ", ".join(f"0x{f:08X}({d:.1f}m{'/XMarker' if k == 0 else ''})" for k, d, f, _b in out)
        print(f"      {tag}: {txt or '无候选'}")
        return [f for _k, _d, f, _b in out]

    en_map = load_strings(ROOT / "ref/strings/strings/starfield_en.strings")
    zh_map = load_strings(ROOT / "ref/strings/strings/starfield_zhhans.strings")

    out = []
    problems = []
    for e in sorted(elite, key=lambda x: x["edid"]):
        base = e["base"]
        edid = e["edid"]
        sid = e["full"]
        name_en = en_map.get(sid, "") if sid is not None else ""
        name_zh = zh_map.get(sid, "") if sid is not None else ""
        if not name_zh or not name_en:
            problems.append(f"{edid} 名字取不到（FULL 字符串 id = {sid!r}）")
        pls = placements[base]
        if len(pls) != 1:
            problems.append(f"{edid} 有 {len(pls)} 处放置引用（第 154 轮口径 = 每人 1 处）")
        pl = pls[0]
        cell_name = cell_edid.get(pl["cell"], "")
        world_name = world_edid.get(pl["world"], "")

        reason = nav_reason(cell_name) if pl["interior"] else ""
        no_nav = bool(reason)

        # 兜底候选：内景 = 同 cell；外景 = world 级
        if pl["interior"]:
            cands = pers_by_cell.get(pl["cell"], [])
            fb = pick_fallbacks(cands, pl["pos"] or (0, 0, 0), "同 cell 常驻兜底")
            fb_kind = "cell"
        else:
            cands = pers_by_world.get(pl["world"], [])
            fb = pick_fallbacks(cands, pl["pos"] or (0, 0, 0),
                                f"world 级常驻兜底（{world_name or hex(pl['world'])}）")
            fb_kind = "world"
        if not no_nav and not fb:
            problems.append(f"{edid} 没有兜底候选（引导链只剩「引用自身」，远处不可导航）")

        # crew faction 三件套（挂载情况；rank 来自 NPC_ 的 SNAM）
        snam_map = dict(e["snams"])
        crew_factions = {}
        for key, fid in CREW_FACTIONS.items():
            attached = fid in snam_map
            crew_factions[key] = {
                "attached": attached,
                "rank": snam_map.get(fid) if attached else None,
                "hex": f"0x{fid:08X}",
                "edid": fact_edid.get(fid, ""),
            }
        # Lin 例外：三个都没挂（主线剧情加入 —— docs/16 16.1）；其余 23 位应全挂
        n_attached = sum(1 for v in crew_factions.values() if v["attached"])
        if n_attached not in (0, 3):
            problems.append(f"{edid} 的 crew faction 只挂了 {n_attached}/3（口径变了？）")

        # 招募载体任务：`CREW_EliteCrew_<名字>`（大小写不敏感）
        suffix = edid[len(EDID_PREFIX):]
        want_q = ("crew_elitecrew_" + suffix).lower()
        q_fid = recruit_quests.get(want_q)
        if q_fid is None:
            problems.append(f"{edid} 找不到招募任务 CREW_EliteCrew_{suffix}（大小写不敏感匹配失败）")

        display_zh = f"（可招募）{name_zh}"
        display_en = f"(Recruitable) {name_en}"
        print(f"=== {edid} (0x{base:06X}) {display_zh} / {display_en} "
              f"{'【不可导航：' + reason + '】' if no_nav else ''} ===")
        print(f"    REFR 0x{pl['ref']:08X} cell={cell_name} world={world_name} "
              f"常驻={'Y' if pl['persistent'] else 'n'} "
              f"（{'内景' if pl['interior'] else '外景'}）pos={pl['pos']}")
        print(f"    crew faction: " +
              ", ".join(f"{k}={'Y' if v['attached'] else 'n'}(r{v['rank']})"
                        for k, v in crew_factions.items()) +
              f"｜招募任务 {'0x%08X' % q_fid if q_fid else '（缺）'}")

        out.append({
            "base": base, "baseHex": f"0x{base:06X}", "edid": edid,
            "nameZh": name_zh, "nameEn": name_en,
            "displayZh": display_zh, "displayEn": display_en,
            "refLocal": pl["ref"], "refHex": f"0x{pl['ref']:08X}",
            "cell": cell_name, "cellHex": f"0x{pl['cell']:08X}",
            "world": world_name, "worldHex": f"0x{pl['world']:08X}",
            "interior": pl["interior"], "persistent": pl["persistent"],
            "pos": [round(v, 2) for v in pl["pos"]] if pl["pos"] else None,
            "xesp": ({"parentHex": f"0x{pl['xesp'][0]:08X}", "flags": pl["xesp"][1]}
                     if pl.get("xesp") else None),
            "noNav": no_nav, "noNavReason": reason,
            "fallbackKind": fb_kind,
            "fallback1": fb[0] if len(fb) > 0 else 0,
            "fallback2": fb[1] if len(fb) > 1 else 0,
            "crewFactions": crew_factions,
            "recruitQuest": ({"local": q_fid, "hex": f"0x{q_fid:08X}",
                              "edid": f"CREW_EliteCrew_{suffix}"} if q_fid else None),
        })

    payload_out = {
        "note": "第 155 轮：可招募船员入口数据（放置引用 / 兜底候选 / crew faction / 招募任务）",
        "npcs": out,
    }
    (ROOT / "ref/hirable_crew.json").write_text(
        json.dumps(payload_out, ensure_ascii=False, indent=1), encoding="utf-8")
    print()
    print(f"已写出 ref/hirable_crew.json（{len(out)} 位 NPC）")

    # ---- harness 探针数据头（仅开发构建引用；见 SAQ_TestCrewProbe.h 头注释）----
    lines = []
    lines.append("#pragma once")
    lines.append("// 本文件由 tools/esm/gen_hirable_crew.py 自动生成，请勿手改。")
    lines.append("//")
    lines.append("// ★★ 第 155 轮（可招募船员跟踪 · 研究）：harness 只读探针 `crew.probe` 的数据表")
    lines.append("//   —— 24 位可招募船员的 { 放置引用, 招募载体任务, 名字 }。")
    lines.append("//   为什么需要：探针要在实机上把每位船员的「crew faction 三件套成员状态」")
    lines.append("//   （Papyrus `Actor.IsInFaction`，需引用已加载）与「招募任务运行时状态」")
    lines.append("//   （DLL 直读）配对读出来 —— 用于验证「已招募 ⇒ 隐藏」的判据（docs/16 16.3）。")
    lines.append("//   本文件只被 SAQ_Test.cpp include（`#if SAQ_WITH_HARNESS` 内）—— 发布构建不含。")
    lines.append("//   数据来源 = ref/hirable_crew.json（同一次扫描产出）。")
    lines.append("#if SAQ_WITH_HARNESS")
    lines.append("")
    lines.append("#include <cstdint>")
    lines.append("")
    lines.append("namespace SAQ::Test")
    lines.append("{")
    lines.append("\tstruct CrewProbeInfo")
    lines.append("\t{")
    lines.append("\t\tstd::uint32_t refForm;     // ACHR 放置引用（Starfield.esm，运行期 FormID 同值）")
    lines.append("\t\tstd::uint32_t questForm;   // 招募载体任务 CREW_EliteCrew_*（同上）")
    lines.append("\t\tbool          noNav;       // 位置不适合导航（暂存格 / 运行时生成内景）")
    lines.append("\t\tconst char*   nameZh;")
    lines.append("\t\tconst char*   nameEn;")
    lines.append("\t};")
    lines.append("")
    lines.append("\tinline constexpr CrewProbeInfo kCrewProbeTable[] = {")
    for r in out:
        q = r["recruitQuest"]["local"] if r["recruitQuest"] else 0
        nn = "true " if r["noNav"] else "false"
        lines.append(
            f'\t\t{{ {r["refLocal"]:#010x}u, {q:#010x}u, {nn}, '
            f'"{c_escape(r["nameZh"])}", "{c_escape(r["nameEn"])}" }},'
        )
    lines.append("\t};")
    lines.append("\tinline constexpr std::size_t kCrewProbeCount = "
                 "sizeof(kCrewProbeTable) / sizeof(kCrewProbeTable[0]);")
    lines.append("}")
    lines.append("")
    lines.append("#endif  // SAQ_WITH_HARNESS")
    lines.append("")
    out_header = ROOT / "plugin/src/SAQ_TestCrewProbe.h"
    out_header.write_text("\n".join(lines), encoding="utf-8")
    print(f"已写出 {out_header.relative_to(ROOT)}（{out_header.stat().st_size} B）")

    # ---- 汇总 ----
    print()
    print(f"汇总：{len(out)} 位；内景 {sum(1 for r in out if r['interior'])} / "
          f"外景 {sum(1 for r in out if not r['interior'])}；"
          f"常驻 {sum(1 for r in out if r['persistent'])}；"
          f"XESP {sum(1 for r in out if r['xesp'])}")
    print(f"      不适合导航 {sum(1 for r in out if r['noNav'])} 位：" +
          ", ".join(r["nameZh"] for r in out if r["noNav"]))
    print(f"      招募任务齐全 {sum(1 for r in out if r['recruitQuest'])}/{len(out)}；"
          f"crew faction 三件套全挂 "
          f"{sum(1 for r in out if sum(1 for v in r['crewFactions'].values() if v['attached']) == 3)}"
          f"/{len(out)}（Lin 无 —— 剧情加入）")

    if problems:
        print("!! 问题：")
        for p in problems:
            print("   -", p)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
