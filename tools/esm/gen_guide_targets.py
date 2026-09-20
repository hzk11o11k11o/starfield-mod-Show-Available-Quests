#!/usr/bin/env python3
"""gen_guide_targets.py - 给每条「可接任务」找一个**引导目标**（世界里的一个 REFR）。

需求背景（第 10 轮）：AGENTS.md 里的「可以选中跟踪，能调用游戏的任务引导系统正常
引导到接取任务的地点（任务目标蓝点，扫描仪任务路径线）」。

引擎只会给「正在运行 + 目标已显示 + 目标是某个引用」的任务画标记；未接取的任务
引擎不管，所以本 MOD 用**代理任务**（ESM 里的 SAQ_MainQuest，带一个可强制填充的
Reference Alias + 一个目标指向该别名的 Objective）把玩家导向下面选出来的引用。

## 引导目标怎么选（按优先级）

| 优先级 | 来源 | 说明 |
| --- | --- | --- |
| 1 | **ALUA「Unique Actor」别名 → NPC 的放置引用（ACHR）** | 任务发布者常常就是「去哪里接」的答案；标记会跟着人走 |
| 2 | **ALFR「Forced Reference」别名 → 直接是 REFR** | 任务自己的落脚点（XMarker/EnableRef 之类） |
| 3 | QUST `LNAM` / ALFL「Specific Location」→ LCTN `MNAM` | 任务地点的**地图标记引用**（只有少部分地点有） |

排除项：落在「别名暂存格」（EDID 里有 AliasCell / DO NOT DELETE / Holding 等）里的
引用一律不用 —— 那种格子玩家进不去，标记会指向空气。

## ★ 多 master（第 17 轮，DLC 支持）

* 别名数据**改成直接读 ESM**（原来读 xEdit 的树状导出 `ref/xedit/quests_typed.txt`）：
  DLC 的导出要另外跑 xEdit（每个 ESM 几分钟），而 QUST 的别名子记录
  （`ALST/ALID/ALUA/ALFR/ALFL`）本来就在记录里，直接解析又快又不用等。
* 一条 DLC 任务引用的 NPC / 地点**可能属于基础游戏**（Starfield.esm），反之亦然；
  所以每个 master 都要扫一遍世界数据，并且每条引用都记下**它属于哪个插件**
  （由 FormID 前缀决定：前缀 < master 数 ⇒ 前缀指向的那份 master；== 自己 ⇒ 自己）。
* 输出里的 `refr` 是**记录号（local）**，配 `refrMaster` 一起用；
  DLL 运行期再按加载顺序拼出真正的 FormID（见 plugin/src/SAQ.cpp）。

输出：
  ref/guide_targets.json   {任务的原始 FormID: {kind, refr, refrMaster, refrSmall,
                                               persistent, nameEn, nameZh, whereEn, whereZh, src}}
  （SAQ_QuestTable.h 的 guide* 字段由 gen_quest_table.py 读这个 JSON 生成）

用法：
    python tools/esm/gen_guide_targets.py                 # 全部 master（约 3-6 分钟）
    python tools/esm/gen_guide_targets.py --no-world      # 跳过世界数据（只出 ALFR，秒级）
    python tools/esm/gen_guide_targets.py --show 0x010158E0   # 打印单条任务的候选明细
"""
from __future__ import annotations

import argparse
import json
import mmap
import re
import struct
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from esm_probe import iter_records_with_context, subrecords, ascii_z  # noqa: E402
from quest_dump import read_tes4  # noqa: E402
from strings_probe import load_strings  # noqa: E402

DEFAULT_DATA = r"D:\SteamLibrary\steamapps\common\Starfield\Data"

# 「别名暂存格」特征（玩家到不了，别把标记指过去）
BAD_CELL_RE = re.compile(r"(aliascell|alias cell|do\s*not\s*delete|holdingcell|holding cell|_hold\b)", re.I)
# 通用/杂兵名（做发布者时优先级降低）
GENERIC_NAME_RE = re.compile(r"(guard|soldier|settler|citizen|worker|technician|scientist|merchant|vendor|"
                             r"security|pirate|spacer|crew|colonist|miner|civilian)", re.I)


def u32(b: bytes) -> int:
    return struct.unpack_from("<I", b, 0)[0]


def load_meta(path: Path) -> dict:
    """读 TES4 头（master 列表 / 自己记录的前缀 / 是否 light）—— 只读头，不加载整个文件。"""
    with path.open("rb") as f:
        head = f.read(24)
        size = u32(head[4:8])
        body = f.read(size)
    meta = read_tes4(head + body)
    meta["file"] = path.name
    meta["path"] = str(path)
    return meta


def owner_of(formid: int, meta: dict) -> str:
    """记录属于哪个插件：FormID 前缀 = 该插件自己的 master 列表下标；== self_index 就是它自己。"""
    prefix = (formid >> 24) & 0xFF
    masters = meta["masters"]
    if prefix < len(masters):
        return masters[prefix]
    if prefix == meta["self_index"]:
        return meta["file"]
    return ""


# ---------------------------------------------------------------------------
#  第一遍：任务的别名（ALUA / ALFR / ALFL）与地点（LCTN）
# ---------------------------------------------------------------------------
def scan_quests(mm: mmap.mmap, meta: dict, want: set[int]):
    """QUST 别名 + LCTN。返回 (aliases, lctns)。

    aliases[in-file formid] = {actors: [(别名名, NPC FormID)], refs: [(别名名, REFR FormID)],
                               locs: [LCTN FormID]}
    """
    aliases: dict[int, dict] = {}
    lctns: dict[int, dict] = {}
    for sig, formid, _flags, _cell, _world, payload in iter_records_with_context(mm):
        if sig == b"QUST":
            if formid not in want:
                continue
            info: dict = {"actors": [], "refs": [], "locs": [], "lctn": 0}
            alias_name = ""
            for s, sp in subrecords(payload):
                if s == b"LNAM" and len(sp) >= 4:
                    info["lctn"] = u32(sp)
                elif s == b"ALST" and len(sp) >= 4:
                    alias_name = ""          # 新别名块开始
                elif s == b"ALID":
                    alias_name = ascii_z(sp)
                elif s == b"ALUA" and len(sp) >= 4:
                    info["actors"].append((alias_name, u32(sp)))
                elif s == b"ALFR" and len(sp) >= 4:
                    info["refs"].append((alias_name, u32(sp)))
                elif s == b"ALFL" and len(sp) >= 4:
                    info["locs"].append(u32(sp))
            aliases[formid] = info
        elif sig == b"LCTN":
            info = {"edid": "", "full": 0, "marker": 0, "parent": 0, "owner": owner_of(formid, meta)}
            for s, sp in subrecords(payload):
                if s == b"EDID":
                    info["edid"] = ascii_z(sp)
                elif s == b"FULL" and len(sp) >= 4:
                    info["full"] = u32(sp)
                elif s == b"MNAM" and len(sp) >= 4:
                    info["marker"] = u32(sp)
                elif s == b"PNAM" and len(sp) >= 4:
                    info["parent"] = u32(sp)
            lctns[formid] = info
    return aliases, lctns


# ---------------------------------------------------------------------------
#  第二遍：世界数据（CELL/WRLD 名字、NPC 名字、放置引用、引用的常驻标志）
# ---------------------------------------------------------------------------
def scan_world(mm: mmap.mmap, meta: dict, wanted_npc: set[int], wanted_refr: set[int], acc: dict):
    """把世界数据累积进 acc（多 master 共用；后扫的覆盖同 FormID 的条目）。"""
    for sig, formid, flags, cell, world, payload in iter_records_with_context(mm):
        if sig == b"NPC_":
            if formid in wanted_npc:
                for s, sp in subrecords(payload):
                    if s == b"FULL" and len(sp) >= 4:
                        acc["npc_names"][formid] = u32(sp)
                        break
        elif sig == b"CELL":
            info = {"edid": "", "full": 0}
            for s, sp in subrecords(payload):
                if s == b"EDID":
                    info["edid"] = ascii_z(sp)
                elif s == b"FULL" and len(sp) >= 4:
                    info["full"] = u32(sp)
            acc["cells"][formid] = info
        elif sig == b"WRLD":
            for s, sp in subrecords(payload):
                if s == b"FULL" and len(sp) >= 4:
                    acc["world_names"][formid] = u32(sp)
                    break
                if s == b"EDID":
                    break
        elif sig in (b"ACHR", b"REFR"):
            base = 0
            edid = ""
            for s, sp in subrecords(payload):
                if s == b"NAME" and len(sp) >= 4:
                    base = u32(sp)
                elif s == b"EDID":
                    edid = ascii_z(sp)
            if base not in wanted_npc and formid not in wanted_refr:
                continue
            info = {
                "refr": formid,
                "cell": cell,
                "world": world,
                "persistent": bool(flags & 0x400),
                "edid": edid,
                "owner": owner_of(formid, meta),
            }
            if base in wanted_npc:
                acc["placements"].setdefault(base, []).append(info)
            if formid in wanted_refr:
                acc["refr_info"][formid] = info


def collect_candidates(fid: int, info: dict, acc: dict, quest_lctn: dict, meta: dict,
                       meta_by_lower: dict, named) -> list[dict]:
    """把一条任务的别名候选整理成候选列表（与第 10 轮的规则一致，只是数据来源换了）。"""
    cands: list[dict] = []

    def owner_fields(refr_id: int, fallback_meta: dict) -> tuple[str, bool]:
        owner = owner_of(refr_id, fallback_meta) or fallback_meta["file"]
        om = meta_by_lower.get(owner.lower(), fallback_meta)
        local = refr_id & (0xFFF if om.get("small") else 0xFFFFFF)
        return om["file"], local, bool(om.get("small"))

    def bad_cell(cell_id: int) -> bool:
        return bool(BAD_CELL_RE.search(acc["cells"].get(cell_id, {}).get("edid", "")))

    def cell_desc(cell_id: int, world_id: int) -> tuple[str, str]:
        if world_id and world_id in acc["world_names"]:
            return named(acc["world_names"][world_id])
        if cell_id and cell_id in acc["cells"] and acc["cells"][cell_id]["full"]:
            return named(acc["cells"][cell_id]["full"])
        return "", ""

    # ① ALFR「Forced Reference」：任务自己写在记录里的落脚引用
    for order, (alias, refr) in enumerate(info.get("refs", [])):
        ri = acc["refr_info"].get(refr, {})
        if bad_cell(ri.get("cell", 0)) or BAD_CELL_RE.search(ri.get("edid", "")):
            continue  # 落在别名暂存格里：玩家到不了
        where_en, where_zh = cell_desc(ri.get("cell", 0), ri.get("world", 0))
        name = ri.get("edid", "") or where_en
        if name.lower() in ("", "xmarker", "xmarkerheading", "mapmarker"):
            name = where_en or name
        owner, local, small = owner_fields(refr, meta)
        cands.append({
            "kind": "ref", "refr": local, "refrMaster": owner, "refrSmall": small,
            "persistent": ri.get("persistent", False),
            "nameEn": name, "nameZh": name,
            "whereEn": where_en, "whereZh": where_zh,
            "src": f"ALFR {alias}", "tier": 1, "generic": 0, "order": order,
        })

    # ② ALUA「Unique Actor」：任务发布者（最常见，也最贴「去哪里接」）
    for order, (alias, npc) in enumerate(info.get("actors", [])):
        if npc in (0, 0x07, 0x14):  # Player / PlayerRef
            continue
        name_en, name_zh = named(acc["npc_names"].get(npc, 0))
        if not name_en:
            continue
        generic = 1 if GENERIC_NAME_RE.search(name_en) else 0
        for pl in acc["placements"].get(npc, []):
            if bad_cell(pl["cell"]):
                continue
            where_en, where_zh = cell_desc(pl["cell"], pl["world"])
            owner, local, small = owner_fields(pl["refr"], meta)
            cands.append({
                "kind": "actor", "refr": local, "refrMaster": owner, "refrSmall": small,
                "persistent": pl["persistent"],
                "nameEn": name_en, "nameZh": name_zh,
                "whereEn": where_en, "whereZh": where_zh,
                "src": f"ALUA {alias}", "tier": 0, "generic": generic, "order": order,
            })

    # ③ 任务地点的地图标记引用（只有少部分地点有，但指向最准）
    lctn = quest_lctn.get(fid, 0)
    lsrc = "LNAM"
    if not lctn and info.get("locs"):
        lctn = info["locs"][0]
        lsrc = "ALFL"
    if lctn:
        marker = acc["lctns"].get(lctn, {}).get("marker", 0)
        if marker:
            def name_of(lid: int, depth: int = 0) -> tuple[str, str]:
                li = acc["lctns"].get(lid)
                if not li:
                    return "", ""
                if li["full"]:
                    return named(li["full"])
                if li["parent"] and depth < 3:
                    return name_of(li["parent"], depth + 1)
                return "", ""
            n_en, n_zh = name_of(lctn)
            owner, local, small = owner_fields(marker, meta)
            cands.append({
                "kind": "loc", "refr": local, "refrMaster": owner, "refrSmall": small,
                "persistent": acc["refr_info"].get(marker, {}).get("persistent", False),
                "nameEn": n_en, "nameZh": n_zh, "whereEn": n_en, "whereZh": n_zh,
                "src": lsrc, "tier": 2, "generic": 0, "order": 0,
            })
    return cands


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default=DEFAULT_DATA)
    ap.add_argument("--esm", action="append", default=[],
                    help="额外/覆盖的 master 路径（可多次；默认按 --data + master 名找）")
    ap.add_argument("--table", default="ref/quest_table_debug.json")
    ap.add_argument("--strings-dir", default="ref/strings/strings")
    ap.add_argument("--out", default="ref/guide_targets.json")
    ap.add_argument("--no-world", action="store_true", help="跳过世界数据遍历（只出 ALFR + 名字）")
    ap.add_argument("--show", default="", help="打印某条任务的候选明细（十六进制原始 FormID）")
    a = ap.parse_args()

    rows = json.loads(Path(a.table).read_text(encoding="utf-8"))
    wanted_by_master: dict[str, set[int]] = {}
    for r in rows:
        fid = r["formid"] if isinstance(r["formid"], int) else int(r["formid"], 16)
        wanted_by_master.setdefault(r.get("master", "Starfield.esm"), set()).add(fid)
    print(f"候选任务 {len(rows)} 条，来自 {len(wanted_by_master)} 个 master："
          + " ".join(f"{m}={len(v)}" for m, v in wanted_by_master.items()))

    meta_by_lower: dict[str, dict] = {}
    for m in list(wanted_by_master):
        path = Path(a.data) / m
        meta = load_meta(path)
        meta_by_lower[m.lower()] = meta
    for p in a.esm:
        meta = load_meta(Path(p))
        meta_by_lower[meta["file"].lower()] = meta

    # ---- 第一遍：别名 + LCTN ----
    aliases: dict[int, dict] = {}
    quest_lctn: dict[int, int] = {}
    acc: dict = {"cells": {}, "world_names": {}, "npc_names": {}, "placements": {}, "refr_info": {},
                 "lctns": {}}
    for m, wanted in wanted_by_master.items():
        meta = meta_by_lower[m.lower()]
        with Path(meta["path"]).open("rb") as f:
            mm = mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ)
            try:
                al, lc = scan_quests(mm, meta, wanted)
            finally:
                mm.close()
        aliases.update(al)
        acc["lctns"].update(lc)  # 地图标记（MNAM）在下面统一收集成 wanted_refr
        for fid, info in al.items():
            if info["lctn"]:
                quest_lctn[fid] = info["lctn"]
        print(f"  {m}: 别名 {len(al)}/{len(wanted)} 条；LCTN {len(lc)} 条")

    wanted_npc = {npc for info in aliases.values() for _al, npc in info["actors"] if npc not in (0, 0x07, 0x14)}
    wanted_refr = {refr for info in aliases.values() for _al, refr in info["refs"]}
    wanted_refr |= {info["marker"] for info in acc["lctns"].values() if info["marker"]}
    print(f"  需要定位的 NPC {len(wanted_npc)} 个；要查标志的引用 {len(wanted_refr)} 个")

    # ---- 第二遍：世界数据 ----
    if not a.no_world:
        for m in wanted_by_master:
            meta = meta_by_lower[m.lower()]
            print(f"  遍历 {m} 的世界数据...")
            with Path(meta["path"]).open("rb") as f:
                mm = mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ)
                try:
                    scan_world(mm, meta, wanted_npc, wanted_refr, acc)
                finally:
                    mm.close()
        print(f"  放置引用 {len(acc['placements'])}/{len(wanted_npc)} 个 NPC；"
              f"引用标志 {len(acc['refr_info'])}/{len(wanted_refr)} 个")

    # ---- 名字表（每个 master 一份）----
    strings: dict[str, tuple[dict, dict]] = {}
    for m in wanted_by_master:
        key = Path(m).stem.lower()
        en_f = Path(a.strings_dir) / f"{key}_en.strings"
        zh_f = Path(a.strings_dir) / f"{key}_zhhans.strings"
        if en_f.exists() and zh_f.exists():
            strings[m] = (load_strings(en_f), load_strings(zh_f))
        else:
            print(f"  !! 缺 {key}_*.strings（{m} 的名字会取不到）")
            strings[m] = ({}, {})

    def make_named(meta: dict):
        en, zh = strings.get(meta["file"], ({}, {}))
        return lambda sid: (en.get(sid, ""), zh.get(sid, "")) if sid else ("", "")

    out: dict[str, dict] = {}
    stats = Counter()
    samples: list[str] = []
    for m, wanted in wanted_by_master.items():
        meta = meta_by_lower[m.lower()]
        named = make_named(meta)
        for fid in wanted:
            info = aliases.get(fid, {"actors": [], "refs": [], "locs": [], "lctn": 0})
            try:
                cands = collect_candidates(fid, info, acc, quest_lctn, meta, meta_by_lower, named)
            except Exception as exc:  # noqa: BLE001
                print(f"  候选生成失败 {m} 0x{fid:08X}: {exc}")
                cands = []
            if a.show and fid == int(a.show, 16):
                print(f"\n--- 0x{fid:08X}（{m}）候选 {len(cands)} 条：")
                for c in cands:
                    print(f"    {c}")
            if not cands:
                stats[f"无目标({m})"] += 1
                continue
            cands.sort(key=lambda c: (0 if c["persistent"] else 1, c["tier"], c["generic"], c["order"]))
            got = cands[0]
            got.pop("tier", None)
            got.pop("generic", None)
            got.pop("order", None)
            out[str(fid)] = got
            stats[got["kind"]] += 1
            stats["常驻" if got["persistent"] else "非常驻"] += 1
            if len(samples) < 12:
                samples.append(
                    f"{m} 0x{fid:08X} [{got['kind']:5s}{'持久' if got['persistent'] else '临时'}] "
                    f"{got['refrMaster']}:0x{got['refr']:06X} 目标={got['nameZh'] or got['nameEn']} "
                    f"位置={got['whereZh'] or got['whereEn']} ({got['src']})")

    Path(a.out).write_text(json.dumps(out, ensure_ascii=False, indent=1, sort_keys=True), encoding="utf-8")
    total = len(rows)
    have = len(out)
    print(f"\n有引导目标 {have}/{total}（{have * 100 // max(total, 1)}%）")
    for k, v in stats.most_common():
        print(f"  {k}: {v}")
    print("样本：")
    for s in samples:
        print("  " + s)
    print(f"wrote {a.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
