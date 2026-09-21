#!/usr/bin/env python3
r"""gen_repeatable_givers.py - 生成「提供无限任务的 NPC」条目数据（第 80 轮）。

背景（AGENTS.md 需求）：无限生成任务不显示，但「接取入口」可以作为一条数据显示 ——
任务板已在第 27 轮做过（gen_entry_table.py）；本轮补上 **NPC 形式**的入口：
* RAD03「长途运输」：向 Trade Authority（贸易管理局）商人询问工作 ⇒ 指向最近的任务板
  （可重复活动；见 starfieldwiki.net/wiki/Starfield:The_Long_Haul，4 位商人）。
* RAD04「死亡通缉令」：向 Trackers Alliance（追踪者联盟）探员询问 ⇒ 指向任务板
  （可重复活动；见 starfieldwiki.net/wiki/Starfield:Activities 的 Repeatable activity）。
数据链交叉验证：官方 Papyrus 源码里 QF_DialogueCydonia / QF_DialogueFCAkilaCity /
QF_DialogueFCNeon / QF_DialogueUCNewAtlantis 有 `RAD03.Start()`、
QF_DialogueTrackersAllianceA 有 `RAD04.Start()`（4 城对话 ⟺ wiki 的 Given by 名单）。

本工具做三件事：
1. 全表扫 Starfield.esm 的 REFR，找这 8 位 NPC 的**放置引用**（第 80 轮实测：8/8 非常驻，
   与任务板当年一样需要「引导兜底链」）；
2. 给每条找**兜底候选**（与任务板同一套判据：XMarker 系优先、然后按距离、取 2 个）：
   * 内景 cell ⇒ 同 cell 的原生常驻引用（照抄任务板的做法）；
   * 外景 cell（阿基拉城广场）⇒ 该 worldspace 的**世界级常驻引用**
     （`WRLD > WorldChildren > CellChildren > CellPersistent`；实测外景 cell 里官方
     不放 per-cell 常驻引用，常驻引用都在 world 层级，离探员 3.1 m）；
3. 校验官方名（strings 表）并输出 ref/repeatable_givers.json（供 gen_entry_table.py 合并）。

复现（约 1~2 分钟）：
    python tools/esm/gen_repeatable_givers.py
"""
from __future__ import annotations

import json
import math
import struct
import sys
import zlib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from esm_probe import (  # noqa: E402
    DEFAULT_ESM, REF_SIGS, record_base_form, record_edid,
)
from strings_probe import load_strings  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]

GROUP_NAMES = {
    0: "Top", 1: "WorldChildren", 2: "InteriorBlock", 3: "InteriorSubBlock",
    4: "ExteriorBlock", 5: "ExteriorSubBlock", 6: "CellChildren",
    7: "TopicChildren", 8: "CellPersistent", 9: "CellTemporary", 10: "CellVisibleDistant",
}

# ★ 8 位「提供无限任务的 NPC」（NPC_ 基础对象 FormID → 官方名 / 组织 / 地点 / 名字后缀）。
#   名字来源：官方 strings 的 FULL 子记录（本工具会校验）。
#   * trade   = RAD03（贸易管理局，4 位独立名字的商人）；
#   * tracker = RAD04（追踪者联盟探员，4 城同名 ⇒ 名字必须带地点后缀区分）。
GIVERS = [
    # base,        EDID,                              kind,      orgZh/organization,              官方名（en/zh）,        地点(zh/en)
    (0x0022484D, "FC_AC_DuncanLynch",              "trade",   "贸易管理局", "Duncan Lynch",    "邓肯·林奇",     "阿基拉城", "Akila City"),
    (0x0026FDDC, "FC_Neon_KolmanLang",             "trade",   "贸易管理局", "Kolman Lang",     "科尔曼·朗",     "霓虹城", "Neon"),
    (0x0001291F, "UC_NA_ZoeKaminski",              "trade",   "贸易管理局", "Zoe Kaminski",    "卓伊·卡明斯基", "新亚特兰蒂斯城", "New Atlantis"),
    (0x00262CC5, "CF_SaoirseBowden",               "trade",   "贸易管理局", "Saoirse Bowden",  "希尔莎·包登",   "赛多尼亚", "Cydonia"),
    (0x00216D35, "FC_AC_TrackersAllianceAgent",    "tracker", "追踪者联盟", "Trackers Alliance Agent", "追踪者联盟探员", "阿基拉城", "Akila City"),
    (0x001D8BDF, "UC_CY_TrackersAllianceAgent",    "tracker", "追踪者联盟", "Trackers Alliance Agent", "追踪者联盟探员", "赛多尼亚", "Cydonia"),
    (0x001D8BE1, "FC_Neon_TrackersAllianceAgent",  "tracker", "追踪者联盟", "Trackers Alliance Agent", "追踪者联盟探员", "霓虹城", "Neon"),
    (0x001D8BE0, "UC_NA_TrackersAllianceAgent",    "tracker", "追踪者联盟", "Trackers Alliance Agent", "追踪者联盟探员", "新亚特兰蒂斯城", "New Atlantis"),
]
GIVER_BASES = {g[0] for g in GIVERS}

XMARKER_BASES = {0x3B, 0x34}      # XMarker / XMarkerHeading（与 gen_entry_table.py 同判据）
FALLBACK_MAX_DIST = 25.0          # 兜底候选最大距离（同房间/同广场级）


def subrecords(payload: bytes):
    p = 0
    end = len(payload)
    while p + 6 <= end:
        sig = payload[p:p + 4]
        size = struct.unpack_from("<H", payload, p + 4)[0]
        sp = payload[p + 6:p + 6 + size]
        if len(sp) != size:
            return
        yield sig, sp
        p += 6 + size


def refr_position(payload: bytes):
    for sig, sp in subrecords(payload):
        if sig == b"DATA" and len(sp) >= 12:
            return struct.unpack_from("<fff", sp, 0)
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


def chain_types(chain):
    return [g for g, _ in chain]


def main() -> int:
    # 名字数据（NPC 显示名 = 「（可重复）<组织> · <名字>（地点后缀，仅同名探员）」）。
    def display_names(g) -> tuple[str, str]:
        _base, _edid, _kind, orgZh, en, zh, where_zh, where_en = g
        if _kind == "tracker":
            # 4 城同名 ⇒ 带地点后缀区分（贸易管理局的 4 位有独立名字，不需要）
            return (f"（可重复）{zh} · {where_zh}", f"(Repeatable) {en} - {where_en}")
        return (f"（可重复）{orgZh} · {zh}", f"(Repeatable) Trade Authority - {en}")

    buf = Path(DEFAULT_ESM).read_bytes()
    print(f"读 {DEFAULT_ESM}（{len(buf)} B）…")

    cell_edid: dict[int, str] = {}
    world_edid: dict[int, str] = {}
    cells_needed: dict[str, int] = {}    # 目标 cell EDID -> 第一次见到时的临时标记
    hits: dict[int, dict] = {b: None for b in GIVER_BASES}
    # 目标 cell（内景）常驻引用 + akilacity 世界级常驻引用（外景兜底用）
    pers_by_cell: dict[int, list] = {}
    pers_by_world: dict[int, list] = {}
    world_of_cell: dict[int, int] = {}
    target_cell_fids: set[int] = set()
    exterior_worlds: set[int] = set()   # 外景 NPC 的 worldspace（第一遍后才知道）

    def cb(sig, formid, flags, chain, cell, world, payload):
        if sig == b"CELL":
            cell_edid[formid] = record_edid(payload)
            world_of_cell[formid] = world
            return
        if sig == b"WRLD":
            world_edid[formid] = record_edid(payload)
            return
        if sig not in REF_SIGS:
            return

        types = chain_types(chain)
        base = record_base_form(payload)
        pos = refr_position(payload)

        if base in GIVER_BASES and hits.get(base) is None:
            hits[base] = {
                "refLocal": formid, "flags": flags,
                "persistent": bool(flags & 0x400),
                "persistentGroup": bool(types and types[-1] == 8),
                "cellFid": cell, "cell": cell_edid.get(cell, ""),
                "world": world, "worldEdid": world_edid.get(world, ""),
                # 内景 = 顶层组是 `Top 'CELL'`；外景 = `Top 'WRLD'`（星空的阿基拉城广场属外景）
                "interior": bool(chain and chain[0][1] == b"CELL"),
                "pos": pos,
            }
            return

        # 目标 cell（内景）的常驻引用 —— 兜底候选
        if types and types[-1] == 8 and cell in target_cell_fids and pos:
            pers_by_cell.setdefault(cell, []).append((base, pos, formid))
            return
        # 外景 NPC 的 worldspace 级常驻引用（`WRLD > WorldChildren > CellChildren > CellPersistent`）
        if types and types[-1] == 8 and world in exterior_worlds and types[0] == 0 and pos:
            pers_by_world.setdefault(world, []).append((base, pos, formid))

    # 第一遍：只拿 8 位 NPC 的 REFR（cell 还不知道 EDID，第二遍再解兜底）
    walk(buf, cb)

    missing = [g[1] for g in GIVERS if hits.get(g[0]) is None]
    if missing:
        print("!! 这些 NPC 没找到 REFR：" + ", ".join(missing))
        return 1

    # 目标 cell FormID（内景兜底范围）与外景 worldspace
    target_cell_fids.update(h["cellFid"] for h in hits.values() if h["interior"])
    exterior_worlds.update(h["world"] for h in hits.values() if not h["interior"])

    # 第二遍：把兜底候选收集齐（第一遍时 target_cell_fids / exterior_worlds 还没确定）
    pers_by_cell.clear()
    pers_by_world.clear()
    walk(buf, cb)

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

    out = []
    problems = []
    for g in GIVERS:
        base, edid, kind, _orgZh, en, zh, where_zh, where_en = g
        h = hits[base]
        nameZh, nameEn = display_names(g)
        print(f"=== {edid} (NPC_ 0x{base:08X}) {nameZh} ===")
        print(f"    REFR 0x{h['refLocal']:08X} cell={h['cell']} "
              f"常驻位={'Y' if h['persistent'] else 'n'} 常驻组={'Y' if h['persistentGroup'] else 'n'} "
              f"（{'内景' if h['interior'] else '外景'}）pos={h['pos']}")

        if h["interior"]:
            cands = pers_by_cell.get(h["cellFid"], [])
            fb = pick_fallbacks(cands, h["pos"], "同 cell 常驻兜底")
            fb_kind = "cell"
        else:
            cands = pers_by_world.get(h["world"], [])
            fb = pick_fallbacks(
                cands, h["pos"],
                f"同世界级常驻兜底（外景 {h['worldEdid'] or hex(h['world'])}：WRLD > WorldChildren > "
                f"CellChildren > CellPersistent）")
            fb_kind = "world"
        if not fb:
            problems.append(f"{edid} 没有兜底候选（引导链只剩「引用自身」，远处不可导航）")

        out.append({
            "base": base, "baseHex": f"0x{base:08X}", "edid": edid,
            "kind": kind, "whereZh": where_zh, "whereEn": where_en,
            "nameZh": nameZh, "nameEn": nameEn,
            "refLocal": h["refLocal"], "refHex": f"0x{h['refLocal']:08X}",
            "cell": h["cell"], "worldHex": f"0x{h['world']:08X}",
            "interior": h["interior"], "persistent": h["persistent"],
            "pos": [round(v, 3) for v in h["pos"]] if h["pos"] else None,
            "fallbackKind": fb_kind,
            "fallback1": fb[0] if len(fb) > 0 else 0,
            "fallback2": fb[1] if len(fb) > 1 else 0,
        })

    # 官方名校验（strings 表：NPC_ FULL == 官方英文名；中文名来自 zhhans）
    en_map = load_strings(ROOT / "ref/strings/strings/starfield_en.strings")
    zh_map = load_strings(ROOT / "ref/strings/strings/starfield_zhhans.strings")
    # NPC_ 的 FULL 字符串 ID（esm_probe list 输出抄录；工具只作交叉校验）
    full_ids = {
        "FC_AC_DuncanLynch": 0xE616, "FC_Neon_KolmanLang": 0xDDA9,
        "UC_NA_ZoeKaminski": 0xE362, "CF_SaoirseBowden": 0x2E382,
        "FC_AC_TrackersAllianceAgent": 0xE09F, "UC_CY_TrackersAllianceAgent": 0xEF09,
        "FC_Neon_TrackersAllianceAgent": 0xE67B, "UC_NA_TrackersAllianceAgent": 0xE139,
    }
    for g in GIVERS:
        base, edid, _kind, _o, en, zh, _wz, _we = g
        sid = full_ids.get(edid)
        if sid is None:
            continue
        off_en, off_zh = en_map.get(sid), zh_map.get(sid)
        if off_en != en or off_zh != zh:
            problems.append(f"{edid} 名字与官方 strings 不一致：strings={off_en!r}/{off_zh!r} 工具={en!r}/{zh!r}")

    (ROOT / "ref/repeatable_givers.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print()
    print(f"已写出 ref/repeatable_givers.json（{len(out)} 位 NPC；"
          f"内景 {sum(1 for r in out if r['interior'])} / 外景 {sum(1 for r in out if not r['interior'])}）")
    if problems:
        print("!! 问题：")
        for p in problems:
            print("   -", p)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
