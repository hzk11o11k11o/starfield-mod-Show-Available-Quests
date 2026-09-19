#!/usr/bin/env python3
"""gen_guide_targets.py - 给每条「可接任务」找一个**引导目标**（世界里的一个 REFR）。

需求背景（第 10 轮）：AGENTS.md 里的「可以选中跟踪，能调用游戏的任务引导系统正常
引导到接取任务的地点（任务目标蓝点，扫描仪任务路径线）」。

引擎只会给「正在运行 + 目标已显示 + 目标是某个引用」的任务画标记；未接取的任务
引擎不管，所以本 MOD 用**代理任务**（ESM 里的 SAQ_MainQuest，带一个可强制填充的
Reference Alias + 一个目标指向该别名的 Objective）把玩家导向下面选出来的引用。

## 引导目标怎么选（按优先级）

| 优先级 | 来源 | 覆盖（202 条候选实测） | 说明 |
| --- | --- | --- | --- |
| 1 | **ALUA「Unique Actor」别名 → NPC 的放置引用（ACHR）** | 见运行输出 | 任务发布者常常就是「去哪里接」的答案；标记会跟着人走 |
| 2 | **ALFR「Forced Reference」别名 → 直接是 REFR** | ~45% | 任务自己的落脚点（XMarker/EnableRef 之类） |
| 3 | QUST `LNAM` / ALFL「Specific Location」→ LCTN `MNAM` | ~7% | 任务地点的**地图标记引用**（只有少部分地点有） |

排除项：落在「别名暂存格」（EDID 里有 AliasCell / DO NOT DELETE / Holding 等）里的
引用一律不用 —— 那种格子玩家进不去，标记会指向空气。

## 数据证据

* `QUST.LNAM` = Location；`LCTN.MNAM` = 该地点的地图标记 REFR。
  实测：CityNewAtlantisLodgeLocation(LCTN 0027C8ED).MNAM = 000F93F1
  = `NewAtlantisMapMarkerLodge`（XMRK 地图标记 + FULL 名字）。
* NPC 放置：全表遍历 CELL/WRLD 组，取 `NAME == NPC_` 的 ACHR。
  实测：FC_Neon_HuongLe(NPC_ 0005797C) → ACHR 0005797D `Neon_HuongRef`
  （cell 00294F32 / world 0027CF9E NeonCity）。

输出：
  ref/guide_targets.json   {任务 FormID: {kind, refr, nameEn, nameZh, whereEn, whereZh, src}}
  （SAQ_QuestTable.h 的 guide* 字段由 gen_quest_table.py 读这个 JSON 生成）

用法：
    python tools/esm/gen_guide_targets.py                  # 全量（含 1~2 分钟 ESM 遍历）
    python tools/esm/gen_guide_targets.py --no-esm         # 跳过 ACHR/地点（只出 ALFR，秒级）
    python tools/esm/gen_guide_targets.py --show 0x000158E0  # 打印单条任务的候选明细
"""
from __future__ import annotations

import argparse
import io
import json
import mmap
import re
import struct
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from esm_probe import iter_records_with_context, subrecords, ascii_z  # noqa: E402
from strings_probe import load_strings  # noqa: E402

DEFAULT_ESM = r"D:\SteamLibrary\steamapps\common\Starfield\Data\Starfield.esm"

# 「别名暂存格」特征（玩家到不了，别把标记指过去）
BAD_CELL_RE = re.compile(r"(aliascell|alias cell|do\s*not\s*delete|holdingcell|holding cell|_hold\b)", re.I)
# 通用/杂兵名（做发布者时优先级降低）
GENERIC_NAME_RE = re.compile(r"(guard|soldier|settler|citizen|worker|technician|scientist|merchant|vendor|"
                             r"security|pirate|spacer|crew|colonist|miner|civilian)", re.I)

ALIAS_HEAD_RE = re.compile(r"^\s+(Reference Alias|Location Alias) \[(ALST|ALLS)\]")
ALID_RE = re.compile(r"ALID - Alias Name = (.+)$")
ALUA_RE = re.compile(r"ALUA - Unique Actor = (.+?)\s*\[NPC_:([0-9A-F]{8})\]")
# 注意布局：父行是 "Forced Reference [ALFR] (1)"，值在子行 "ALFR - Forced Reference = ..."
ALFR_RE = re.compile(r"ALFR - Forced Reference = (.*)$")
LOC_RE = re.compile(r"\[LCTN:([0-9A-F]{8})\]")
REF_RE = re.compile(r"\[(REFR|ACHR):([0-9A-F]{8})\]")
# ALFR 行里 xEdit 会把宿主也写出来：... in <WRLD EDID> "名字" [WRLD:xxxxxxxx]
WRLD_IN_LINE_RE = re.compile(r"\(in ([^)\[]*?)\s*\[WRLD:([0-9A-F]{8})\]")
CELL_EDID_RE = re.compile(r"(?:Children of|in)\s*\[CELL:[0-9A-F]{8}\]")


def quoted(s: str) -> str:
    m = re.search(r"\"([^\"]+)\"", s)
    return m.group(1) if m else s


def parse_dump(dump: Path, kept: set[int]) -> dict[int, dict]:
    """从 xEdit 导出里取每个任务的「发布者候选」与「强制引用候选」。"""
    out: dict[int, dict] = {}
    if not dump.exists():
        return out
    text = io.open(dump, encoding="utf-8-sig", errors="replace").read()
    for block in re.split(r"\r?\n=== ", text)[1:]:
        m = re.match(r"([0-9A-F]{8})\s+(\S+)", block)
        if not m:
            continue
        fid = int(m.group(1), 16)
        if fid not in kept:
            continue
        cur_alias = ""
        actors: list[dict] = []
        refs: list[dict] = []
        lcts: list[int] = []
        for line in block.splitlines():
            if ALIAS_HEAD_RE.match(line):
                cur_alias = ""
                continue
            am = ALID_RE.search(line)
            if am:
                cur_alias = am.group(1).strip()
                continue
            ua = ALUA_RE.search(line)
            if ua:
                actors.append({
                    "alias": cur_alias,
                    "npc": int(ua.group(2), 16),
                    "desc": ua.group(1).strip(),
                })
                continue
            fr = ALFR_RE.search(line)
            if fr:
                rm = REF_RE.search(line)
                if rm:
                    refs.append({
                        "alias": cur_alias,
                        "refr": int(rm.group(2), 16),
                        "desc": fr.group(1).strip(),
                        "line": line.strip(),
                    })
                continue
            if "ALFL - Specific Location" in line:
                lm = LOC_RE.search(line)
                if lm:
                    lcts.append(int(lm.group(1), 16))
        if actors or refs or lcts:
            out[fid] = {"actors": actors, "refs": refs, "locs": lcts}
    return out


def scan_esm(esm: Path, wanted_npc: set[int], wanted_refr: set[int]):
    """一次遍历拿：QUST.LNAM / LCTN / NPC_ 名字 / CELL|WRLD 名字 / 引用信息。

    wanted_refr 里的引用会记录「是否常驻（persistent 记录标志 0x400）」「宿主格」——
    常驻引用在格子没加载时也存在（Game.GetForm 拿得到、ForceRefTo 能成），
    临时引用要等格子加载，所以选引导目标时优先常驻（见 pick_* 的排序）。
    """
    quest_lctn: dict[int, int] = {}
    locs: dict[int, dict] = {}
    npc_names: dict[int, int] = {}
    cells: dict[int, dict] = {}
    world_names: dict[int, int] = {}
    placements: dict[int, list] = {}
    refr_info: dict[int, dict] = {}
    with esm.open("rb") as f:
        mm = mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ)
        try:
            for sig, formid, flags, cell, world, payload in iter_records_with_context(mm):
                if sig == b"QUST":
                    for s, sp in subrecords(payload):
                        if s == b"LNAM" and len(sp) >= 4:
                            quest_lctn[formid] = struct.unpack_from("<I", sp, 0)[0]
                            break
                elif sig == b"LCTN":
                    info = {"edid": "", "full": 0, "marker": 0, "parent": 0}
                    for s, sp in subrecords(payload):
                        if s == b"EDID":
                            info["edid"] = ascii_z(sp)
                        elif s == b"FULL" and len(sp) >= 4:
                            info["full"] = struct.unpack_from("<I", sp, 0)[0]
                        elif s == b"MNAM" and len(sp) >= 4:
                            info["marker"] = struct.unpack_from("<I", sp, 0)[0]
                        elif s == b"PNAM" and len(sp) >= 4:
                            info["parent"] = struct.unpack_from("<I", sp, 0)[0]
                    locs[formid] = info
                    if info["marker"]:
                        wanted_refr.add(info["marker"])
                elif sig == b"NPC_":
                    if formid in wanted_npc:
                        for s, sp in subrecords(payload):
                            if s == b"FULL" and len(sp) >= 4:
                                npc_names[formid] = struct.unpack_from("<I", sp, 0)[0]
                                break
                elif sig == b"CELL":
                    info = {"edid": "", "full": 0}
                    for s, sp in subrecords(payload):
                        if s == b"EDID":
                            info["edid"] = ascii_z(sp)
                        elif s == b"FULL" and len(sp) >= 4:
                            info["full"] = struct.unpack_from("<I", sp, 0)[0]
                    cells[formid] = info
                elif sig == b"WRLD":
                    for s, sp in subrecords(payload):
                        if s == b"FULL" and len(sp) >= 4:
                            world_names[formid] = struct.unpack_from("<I", sp, 0)[0]
                            break
                        if s == b"EDID":
                            break
                elif sig in (b"ACHR", b"REFR"):
                    base = 0
                    edid = ""
                    for s, sp in subrecords(payload):
                        if s == b"NAME" and len(sp) >= 4:
                            base = struct.unpack_from("<I", sp, 0)[0]
                        elif s == b"EDID":
                            edid = ascii_z(sp)
                    info = {
                        "refr": formid,
                        "cell": cell,
                        "world": world,
                        "persistent": bool(flags & 0x400),
                        "edid": edid,
                    }
                    if base in wanted_npc:
                        placements.setdefault(base, []).append(info)
                    if formid in wanted_refr:
                        refr_info[formid] = info
        finally:
            mm.close()
    return quest_lctn, locs, npc_names, cells, world_names, placements, refr_info


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--esm", default=DEFAULT_ESM)
    ap.add_argument("--table", default="ref/quest_table_debug.json")
    ap.add_argument("--dump", default="ref/xedit/quests_typed.txt")
    ap.add_argument("--strings-dir", default="ref/strings/strings")
    ap.add_argument("--out", default="ref/guide_targets.json")
    ap.add_argument("--no-esm", action="store_true", help="跳过 ESM 遍历（只出 ALFR 候选）")
    ap.add_argument("--show", default="", help="打印某条任务的候选明细（十六进制 FormID）")
    a = ap.parse_args()

    rows = json.loads(Path(a.table).read_text(encoding="utf-8"))
    kept = [(r["formid"] if isinstance(r["formid"], int) else int(r["formid"], 16)) for r in rows]
    kept_set = set(kept)
    print(f"候选任务 {len(kept)} 条")

    print("读 xEdit 导出的别名（ALUA / ALFR / ALFL）...")
    dump = parse_dump(Path(a.dump), kept_set)
    n_actors = sum(1 for v in dump.values() if v["actors"])
    n_refs = sum(1 for v in dump.values() if v["refs"])
    n_locs = sum(1 for v in dump.values() if v.get("locs"))
    print(f"  有发布者候选(ALUA) {n_actors} 条；有强制引用候选(ALFR) {n_refs} 条；有具体地点(ALFL) {n_locs} 条")

    wanted_npc: set[int] = set()
    for v in dump.values():
        for act in v["actors"]:
            if act["npc"] not in (0, 0x07):  # 排除 Player
                wanted_npc.add(act["npc"])
    # ALFR 的引用也要查「是否常驻」+ 宿主格（判断是不是别名暂存格）
    wanted_refr: set[int] = {c["refr"] for v in dump.values() for c in v["refs"]}
    print(f"  需要定位的 NPC {len(wanted_npc)} 个；要查标志的引用 {len(wanted_refr)} 个")

    quest_lctn: dict[int, int] = {}
    locs: dict[int, dict] = {}
    npc_names: dict[int, int] = {}
    cells: dict[int, dict] = {}
    world_names: dict[int, int] = {}
    placements: dict[int, list] = {}
    refr_info: dict[int, dict] = {}
    if not a.no_esm:
        print("遍历 Starfield.esm（QUST/LCTN/NPC_/CELL/WRLD/ACHR，约 1-2 分钟）...")
        quest_lctn, locs, npc_names, cells, world_names, placements, refr_info = scan_esm(
            Path(a.esm), wanted_npc, set(wanted_refr))
        print(f"  QUST 有 LNAM {len(quest_lctn)}；LCTN {len(locs)}；CELL {len(cells)}；"
              f"有放置的 NPC {len(placements)}/{len(wanted_npc)}；"
              f"查到的引用 {len(refr_info)}/{len(wanted_refr)}")

    en = load_strings(Path(a.strings_dir) / "starfield_en.strings")
    zh = load_strings(Path(a.strings_dir) / "starfield_zhhans.strings")

    def named(str_id: int) -> tuple[str, str]:
        return en.get(str_id, ""), zh.get(str_id, "")

    def bad_cell(cell_id: int) -> bool:
        """别名暂存格 / 隐藏格（玩家到不了）——标记指过去就是空气。"""
        return bool(BAD_CELL_RE.search(cells.get(cell_id, {}).get("edid", "")))

    def cell_desc(cell_id: int, world_id: int) -> tuple[str, str]:
        """(英文, 中文) 位置描述：优先世界名（城市/星球），否则格子名。"""
        if world_id and world_id in world_names:
            return named(world_names[world_id])
        if cell_id and cell_id in cells and cells[cell_id]["full"]:
            return named(cells[cell_id]["full"])
        return "", ""

    # ------------------------------------------------------------------
    #  候选生成 + 排序
    #
    #  排序键（先硬后软）：
    #    ① 引用必须**常驻**（persistent）：格子没加载时 Game.GetForm 也能拿到、
    #       ForceRefTo 也能成 —— 临时引用要等格子加载，玩家在远方时引导就是空谈；
    #    ② 来源：任务发布者(ALUA) / 任务自己的落脚点(ALFR) > 地点地图标记(LCTN.MNAM)；
    #    ③ 发布者不是杂兵（Guard/Settler/Scientist…）；
    #    ④ 出现顺序。
    # ------------------------------------------------------------------
    def collect_candidates(fid: int) -> list[dict]:
        cands: list[dict] = []
        info = dump.get(fid, {})

        # ① ALFR「Forced Reference」：任务自己写在记录里的落脚引用
        for order, c in enumerate(info.get("refs", [])):
            line = c["line"]
            if BAD_CELL_RE.search(line):
                continue  # 落在别名暂存格里：玩家到不了
            ri = refr_info.get(c["refr"], {})
            where_en = where_zh = ""
            wm = WRLD_IN_LINE_RE.search(line)
            if wm:
                where_en = where_zh = wm.group(1).strip()
            name_en = re.sub(r"^\[REFR:[0-9A-F]{8}\]\s*", "", c["desc"].split("(")[0].strip())
            if name_en.lower() in ("", "xmarker", "xmarkerheading", "mapmarker"):
                name_en = where_en or name_en
            cands.append({
                "kind": "ref", "refr": c["refr"],
                "persistent": ri.get("persistent", False),
                "nameEn": name_en, "nameZh": name_en,
                "whereEn": where_en, "whereZh": where_zh,
                "src": f"ALFR {c['alias']}", "tier": 1, "generic": 0, "order": order,
            })

        # ② ALUA「Unique Actor」：任务发布者（最常见，也最贴「去哪里接」）
        for order, act in enumerate(info.get("actors", [])):
            name_en, name_zh = named(npc_names.get(act["npc"], 0))
            if not name_en:
                name_en = quoted(act["desc"])
            if not name_zh:
                name_zh = name_en
            generic = 1 if GENERIC_NAME_RE.search(name_en or act["desc"]) else 0
            for pl in placements.get(act["npc"], []):
                if bad_cell(pl["cell"]):
                    continue
                where_en, where_zh = cell_desc(pl["cell"], pl["world"])
                cands.append({
                    "kind": "actor", "refr": pl["refr"],
                    "persistent": pl["persistent"],
                    "nameEn": name_en, "nameZh": name_zh,
                    "whereEn": where_en, "whereZh": where_zh,
                    "src": f"ALUA {act['alias']}", "tier": 0, "generic": generic, "order": order,
                })

        # ③ 任务地点的地图标记引用（只有少部分地点有，但指向最准）
        lctn = quest_lctn.get(fid, 0)
        lsrc = "LNAM"
        if not lctn:
            alias_locs = info.get("locs") or []
            lctn = alias_locs[0] if alias_locs else 0
            lsrc = "ALFL"
        if lctn:
            marker = locs.get(lctn, {}).get("marker", 0)
            if marker:
                def name_of(lid: int, depth: int = 0) -> tuple[str, str]:
                    li = locs.get(lid)
                    if not li:
                        return "", ""
                    if li["full"]:
                        return named(li["full"])
                    if li["parent"] and depth < 3:
                        return name_of(li["parent"], depth + 1)
                    return "", ""
                n_en, n_zh = name_of(lctn)
                cands.append({
                    "kind": "loc", "refr": marker,
                    "persistent": refr_info.get(marker, {}).get("persistent", False),
                    "nameEn": n_en, "nameZh": n_zh, "whereEn": n_en, "whereZh": n_zh,
                    "src": lsrc, "tier": 2, "generic": 0, "order": 0,
                })
        return cands

    out: dict[str, dict] = {}
    stats = Counter()
    samples: list[str] = []
    for fid in kept:
        try:
            cands = collect_candidates(fid)
        except Exception as exc:  # noqa: BLE001
            print(f"  候选生成失败 0x{fid:08X}: {exc}")
            cands = []
        if not cands:
            stats["无目标"] += 1
            continue
        cands.sort(key=lambda c: (0 if c["persistent"] else 1, c["tier"], c["generic"], c["order"]))
        got = cands[0]
        got.pop("tier", None)
        got.pop("generic", None)
        got.pop("order", None)
        out[str(fid)] = got
        stats[got["kind"]] += 1
        stats["常驻" if got["persistent"] else "非常驻"] += 1
        if len(samples) < 10:
            samples.append(
                f"0x{fid:08X} [{got['kind']:5s}{'持久' if got['persistent'] else '临时'}] "
                f"refr=0x{got['refr']:08X} 目标={got['nameZh'] or got['nameEn']} "
                f"位置={got['whereZh'] or got['whereEn']} ({got['src']})")

    Path(a.out).write_text(json.dumps(out, ensure_ascii=False, indent=1, sort_keys=True), encoding="utf-8")
    total = len(kept)
    have = len(out)
    print(f"\n有引导目标 {have}/{total}（{have * 100 // max(total, 1)}%）")
    for k, v in stats.most_common():
        print(f"  {k}: {v}")
    print("样本：")
    for s in samples:
        print("  " + s)
    miss = [f"0x{f:08X}" for f in kept if str(f) not in out][:12]
    print("无目标样本：" + " ".join(miss))
    print(f"wrote {a.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
