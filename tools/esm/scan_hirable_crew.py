#!/usr/bin/env python3
r"""scan_hirable_crew.py - 「可招募的有名字船员」能不能跟踪？（第 154 轮研究工具）

背景（玩家提问）：可以被招募为船员的有名字 NPC（酒吧/城市里遇到的精英船员）
能不能像任务板 / 可重复 NPC 入口那样做成「可接任务」条目并跟踪（蓝点 + 扫描线）？

本工具做**只读探查**，产出一份可复核的数据快照：

1. 自动枚举可招募船员：NPC_ 里 EDID 前缀 `Crew_Elite_`（排除 OtherPlayer* 模板与
   BalanceData 模板）⇒ 实测 24 位（与官方 FLST `CREW_imGui_2a_Actors_Elite` 0x00133A67
   的 24 名成员互为印证；另有两位辅助核对对象，见 --extra）；
2. 找每位 NPC 的**放置引用**（ACHR/REFR…）：cell / world / 常驻位 / 常驻组 / 坐标 / XESP；
3. 对每个放置所在 cell（内景）统计**同 cell 常驻引用**、外景统计 **world 级常驻引用**
   —— 即「引导兜底链」在不新建 marker 的前提下有没有现成候选；
4. 收集 `CREW_*Recruit*` 招募任务（QUST）与 NPC_ 上的 crew faction 三件套
   （AvailableCrew / CurrentCrew / PotentialCrew）—— 供「显示/隐藏时机」研究；
5. 打印摘要 + 输出 ref/hirable_crew_scan.json（只读证据，不入库）。

复现（约 1 分钟）：
    python tools/esm/scan_hirable_crew.py
"""
from __future__ import annotations

import json
import struct
import sys
import zlib
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from esm_probe import (  # noqa: E402
    DEFAULT_ESM, REF_SIGS, read_records, record_edid, subrecords,
)
from strings_probe import load_strings  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]

# 名字不在「可招募清单」里的模板/杂项（EDID 排除判据）
EXCLUDE_RE = ("OtherPlayer", "BalanceData", "VascoSarahMisc")

# 两位「有 Crew_Elite 前缀 + 招募任务、但不在 FLST 精英名单里」的补充核对对象
EDID_PREFIX = "Crew_Elite_"


def record_base_form(payload: bytes) -> int:
    """取 REFR/ACHR 的 NAME 子记录（指向 base object）。"""
    for sig, sp in subrecords(payload):
        if sig == b"NAME" and len(sp) >= 4:
            return struct.unpack_from("<I", sp, 0)[0]
    return 0


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


def discover_elite_bases(buf: bytes) -> list[tuple[int, str, int | None]]:
    """第一遍：NPC_ 顶层组里按 EDID 前缀找可招募船员（含 FULL 字符串 id）。"""
    out = []
    for formid, _flags, payload in read_records(buf, "NPC_"):
        edid = ""
        full = None
        for s, sp in subrecords(payload):
            if s == b"EDID":
                edid = sp.split(b"\x00")[0].decode("latin1", "replace")
            elif s == b"FULL" and len(sp) >= 4:
                full = struct.unpack_from("<I", sp, 0)[0]
        if edid.startswith(EDID_PREFIX) and not any(x in edid for x in EXCLUDE_RE):
            out.append((formid, edid, full))
    return out


def main() -> int:
    buf = Path(DEFAULT_ESM).read_bytes()
    print(f"读 {DEFAULT_ESM}（{len(buf)} B）…")

    # 第一遍：枚举可招募船员（EDID 前缀判据）
    elite = discover_elite_bases(buf)
    elite_set = {b for b, _e, _f in elite}
    print(f"按 EDID 前缀 `{EDID_PREFIX}`（排除模板）发现 {len(elite)} 位可招募船员")
    for b, e, _f in elite:
        print(f"    {e}  (0x{b:06X})")

    # 第二遍：全量 —— 放置引用 + 常驻兜底候选 + 各类 EDID + 招募任务
    npc_info: dict[int, dict] = {}
    cell_edid: dict[int, str] = {}
    world_edid: dict[int, str] = {}
    fact_edid: dict[int, str] = {}
    placements: dict[int, list] = defaultdict(list)
    pers_by_cell: dict[int, list] = defaultdict(list)
    pers_by_world: dict[int, list] = defaultdict(list)
    recruit_quests: list[dict] = []

    def cb(sig, formid, flags, chain, cell, world, payload):
        if sig == b"NPC_":
            if formid in elite_set:
                edid = ""
                snams = []
                for s, sp in subrecords(payload):
                    if s == b"EDID":
                        edid = sp.split(b"\x00")[0].decode("latin1", "replace")
                    elif s == b"SNAM" and len(sp) >= 5:
                        snams.append((struct.unpack_from("<I", sp, 0)[0], sp[4]))
                npc_info[formid] = {"edid": edid, "snams": snams}
            return
        if sig == b"FACT":
            fact_edid[formid] = record_edid(payload)
            return
        if sig == b"CELL":
            cell_edid[formid] = record_edid(payload)
            return
        if sig == b"WRLD":
            world_edid[formid] = record_edid(payload)
            return
        if sig == b"QUST":
            # ★ 实测（第 154 轮）：`QUST` 顶层组里混装 QUST 2077 条 + INFO/DIAL/SCEN…
            #   ⇒ 必须按 sig 分类；招募载体任务 = `CREW_EliteCrew_<姓名>` 形式的 QUST
            #   （对话/分支/场景分别挂 INFO / DLBR / SCEN，各自带名字后缀）。
            edid = record_edid(payload)
            if edid.startswith("CREW_EliteCrew_"):
                recruit_quests.append({"formid": formid, "hex": f"0x{formid:08X}", "edid": edid})
            return
        if sig in REF_SIGS:
            types = [g for g, _ in chain]
            base = record_base_form(payload)
            pos = refr_position(payload)
            if base in elite_set:
                placements[base].append({
                    "ref": formid, "flags": flags,
                    "persistent": bool(flags & 0x400),
                    "persistentGroup": bool(types and types[-1] == 8),
                    "cell": cell, "world": world,
                    "interior": bool(chain and chain[0][1] == b"CELL"),
                    "pos": pos,
                    "xesp": refr_xesp(payload),
                })
                return
            # 常驻引用候选（同 cell / world 兜底用）
            if types and types[-1] == 8 and pos:
                if cell and chain and chain[0][1] == b"CELL":
                    pers_by_cell[cell].append((base, pos, formid))
                elif world and types[0] == 0:
                    pers_by_world[world].append((base, pos, formid))

    walk(buf, cb)

    en_map = load_strings(ROOT / "ref/strings/strings/starfield_en.strings")
    zh_map = load_strings(ROOT / "ref/strings/strings/starfield_zhhans.strings")

    out = []
    for base, edid, sid in elite:
        name_en = en_map.get(sid, "") if sid is not None else ""
        name_zh = zh_map.get(sid, "") if sid is not None else ""
        info = npc_info.get(base, {})
        snams = info.get("snams", [])
        pls = placements.get(base, [])
        print()
        print(f"=== {edid}  (0x{base:06X})  名字={name_zh} / {name_en}  放置={len(pls)} ===")
        if snams:
            facs = ", ".join(f"0x{f:08X}:{fact_edid.get(f, '?')[:24]}(r{r})" for f, r in snams)
            print(f"    factions: {facs}")
        for pl in sorted(pls, key=lambda x: (x["cell"], x["ref"])):
            cand = pers_by_cell.get(pl["cell"], []) if pl["interior"] else pers_by_world.get(pl["world"], [])
            near = 0
            if pl["pos"]:
                near = sum(1 for _b, p2, _f in cand
                           if (p2[0] - pl["pos"][0]) ** 2 + (p2[1] - pl["pos"][1]) ** 2
                           + (p2[2] - pl["pos"][2]) ** 2 <= 25.0 ** 2)
            xesp = pl.get("xesp")
            xesp_txt = (f" XESP=0x{xesp[0]:08X}(f{xesp[1]})" if xesp else "")
            print(f"    REF 0x{pl['ref']:08X} cell=0x{pl['cell']:08X}:{cell_edid.get(pl['cell'], '?')[:26]:<26} "
                  f"world=0x{pl['world']:08X}:{world_edid.get(pl['world'], '?')[:12]:<12} "
                  f"常驻位={'Y' if pl['persistent'] else 'n'} 常驻组={'Y' if pl['persistentGroup'] else 'n'} "
                  f"（{'内景' if pl['interior'] else '外景'}）pos={pl['pos']} "
                  f"兜底(≤25m)={'同cell:' if pl['interior'] else 'world级:'}{near}/{len(cand)}{xesp_txt}")
        out.append({
            "base": base, "baseHex": f"0x{base:06X}", "edid": edid,
            "nameZh": name_zh, "nameEn": name_en,
            "factions": [{"fid": f, "hex": f"0x{f:08X}", "edid": fact_edid.get(f, ""), "rank": r}
                         for f, r in snams],
            "placements": [
                {
                    "ref": pl["ref"], "refHex": f"0x{pl['ref']:08X}",
                    "cellFid": pl["cell"], "cellHex": f"0x{pl['cell']:08X}", "cell": cell_edid.get(pl["cell"], ""),
                    "worldFid": pl["world"], "worldHex": f"0x{pl['world']:08X}", "world": world_edid.get(pl["world"], ""),
                    "persistent": pl["persistent"], "persistentGroup": pl["persistentGroup"],
                    "interior": pl["interior"],
                    "pos": [round(v, 2) for v in pl["pos"]] if pl["pos"] else None,
                    "xesp": ({"parentHex": f"0x{pl['xesp'][0]:08X}", "flags": pl["xesp"][1]}
                             if pl.get("xesp") else None),
                } for pl in pls
            ],
        })

    payload_out = {
        "note": "第 154 轮研究快照：可招募船员的放置引用 / 常驻兜底候选 / faction / 招募任务",
        "npcs": out,
        "recruitQuests": sorted(recruit_quests, key=lambda r: r["edid"]),
    }
    (ROOT / "ref/hirable_crew_scan.json").write_text(
        json.dumps(payload_out, ensure_ascii=False, indent=1), encoding="utf-8")
    print()
    print(f"已写出 ref/hirable_crew_scan.json（{len(out)} 位 NPC / {len(recruit_quests)} 条招募任务）")

    # 汇总：放置数 / 常驻比例 / 兜底可用性
    all_pl = [pl for r in out for pl in r["placements"]]
    print(f"总放置数 = {len(all_pl)}；"
          f"常驻位 = {sum(1 for p in all_pl if p['persistent'])}；"
          f"常驻组 = {sum(1 for p in all_pl if p['persistentGroup'])}；"
          f"内景 = {sum(1 for p in all_pl if p['interior'])}；"
          f"外景 = {sum(1 for p in all_pl if not p['interior'])}；"
          f"XESP = {sum(1 for p in all_pl if p['xesp'])}")
    cells_used = sorted({p["cellFid"] for r in out for p in r["placements"] if p["interior"]})
    worlds_used = sorted({p["worldFid"] for r in out for p in r["placements"] if not p["interior"]})
    withcand = [c for c in cells_used if pers_by_cell.get(c)]
    withwcand = [w for w in worlds_used if pers_by_world.get(w)]
    print(f"内景 cell 数 = {len(cells_used)}（有同 cell 常驻候选 = {len(withcand)}）")
    print(f"外景 world 数 = {len(worlds_used)}（有 world 级常驻候选 = {len(withwcand)}；"
          f"world 级常驻引用总数 = {sum(len(v) for v in pers_by_world.values())}）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
