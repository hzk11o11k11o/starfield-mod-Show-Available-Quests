#!/usr/bin/env python3
"""gen_faction_types.py - 生成「任务阵营」映射表：QUST 的 FTYP 关键字 -> 原版 UI 阵营枚举。

背景（第 65 轮「任务专属图标」）：
    原版任务菜单里每条任务左侧有一个图标（活动 / 杂项 / 任务 / 各势力专属徽记）——
    由 SWF 里的 MissionsListEntry.SetFactionIcon 用 (iFaction, iType) 决定
    （Shared.QuestUtils.GetQuestIconLabel）：

        iType == ACTIVITY(0)          -> "Activities" 帧
        iFaction != FACTION_NONE(-1)  -> 阵营帧（FactionUtils.GetFactionIconLabel）
        iType == MISC(3) / MISSION(4) -> "Misc" / "Missions"
        否则                          -> "None"

    iType 已有（QUST 的 QTYP，见 gen_quest_table.py）；本脚本补 **iFaction**：
    QUST 记录的 FTYP 子记录 = 一个 KYWD「FactionType*」关键字，与 UI 枚举一一对应。

    ★ 枚举值来源：ui/missionmenu/src/Shared/FactionUtils.as（EnumHelper 自增）——
        -1=None  0=Paradiso  1=UnitedColonies  2=RyujinIndustries  3=HouseVaruun
         4=Freestar  5=BlackFleet  6=Constellation  7=TrackersAlliance
         8=TerranArmada  9=Creations
      （Icons_mc sprite 实测 13 帧：Activities/Misc/Missions/None + 9 个阵营帧；
        帧名见 FactionUtils.GetFactionIconLabel —— 如 CrimsonFleet 用 "BlackFleet" 帧。）

    ★ 关键字所在文件不一定是任务所在文件（DLC 常引用基础游戏的 0x546xx），且
      **同一记录在不同文件里的 FormID 前缀不同**（前缀 = 该文件 master 列表里的序号）：
        文件 X 里某 FormID 的高字节 i 表示「X 的 master 列表第 i 项」（i == len 时是自己）。
      所以查表要按「文件内编码 → (所属文件, 记录号)」逐层还原（见 resolve_ftyp）。

输出：
    ref/faction_types.json
        { "<master 文件名>": { "<FTYP 文件内十六进制(8位)>": {"edid": "...", "faction": N} } }
      —— 键与 ref/quests_all.json 每条记录的 (master, ftyp) 完全对应，
         gen_quest_table.py 直接按 (q['master'], f"{q['ftyp']:08X}") 查用。

用法：
    python tools/esm/gen_faction_types.py [--quests ref/quests_all.json]
                                          [--data-dir <Starfield Data 目录>]
                                          [--out ref/faction_types.json]
"""
from __future__ import annotations

import argparse
import json
import struct
from pathlib import Path

# EDID -> UI 阵营枚举（FactionUtils.as 的顺序）。
# ★ 数据里当前存在的：Paradiso / UnitedColonies / RyujinIndustries / HouseVaruun /
#   FreestarCollective / CrimsonFleet / Constellation / TerranArmada（SFBGS050）。
#   TrackersAlliance / Creations 暂无对应关键字（保留映射以备将来；
#   Creations 的自定义图标走 strFactionIconName 动态加载，本 MOD 不需要）。
FACTION_BY_EDID: dict[str, int] = {
    "FactionTypeParadiso": 0,
    "FactionTypeUnitedColonies": 1,
    "FactionTypeRyujinIndustries": 2,
    "FactionTypeHouseVaruun": 3,
    "FactionTypeFreestarCollective": 4,
    "FactionTypeCrimsonFleet": 5,
    "FactionTypeConstellation": 6,
    "FactionTypeTrackersAlliance": 7,
    "FactionTypeTerranArmada": 8,
    "FactionTypeCreations": 9,
}


def iter_subrecords(buf: bytes, start: int, size: int):
    """遍历一条记录的顶层子记录，yield (sig, payload_bytes)。（与 quest_dump.py 相同）"""
    p = start
    end = start + size
    while p + 6 <= end:
        ssig = buf[p:p + 4]
        ssize = struct.unpack_from("<H", buf, p + 4)[0]
        if p + 6 + ssize > end:
            break
        yield ssig, buf[p + 6:p + 6 + ssize]
        p += 6 + ssize


def read_tes4(buf: bytes) -> dict:
    """TES4 头：master 列表 / flags（与 quest_dump.py 相同）。"""
    if buf[0:4] != b"TES4":
        raise ValueError("not a plugin")
    head_size = struct.unpack_from("<I", buf, 4)[0]
    flags = struct.unpack_from("<I", buf, 8)[0]
    masters: list[str] = []
    for sig, sp in iter_subrecords(buf, 24, head_size):
        if sig == b"MAST":
            masters.append(sp.split(b"\x00")[0].decode("latin1"))
    return {
        "flags": flags,
        "masters": masters,
        "self_index": len(masters),
        "small": bool(flags & 0x100),
    }


def iter_groups(buf: bytes):
    """遍历顶层 GRUP，yield (pos, gsize, glabel, gtype)。"""
    head_size = struct.unpack_from("<I", buf, 4)[0]
    pos = 24 + head_size
    while pos + 24 <= len(buf):
        if buf[pos:pos + 4] != b"GRUP":
            break
        gsize = struct.unpack_from("<I", buf, pos + 4)[0]
        glabel = buf[pos + 8:pos + 12]
        gtype = struct.unpack_from("<I", buf, pos + 12)[0]
        if gsize < 24:
            break
        yield pos, gsize, glabel, gtype
        pos += gsize


def parse_kydd_local_names(path: Path) -> dict[int, str]:
    """该文件 KYWD 组里 **自己的** 记录：{记录号(local): EDID}。

    只保留 EDID 以 "FactionType" 开头的关键字（FactionTypeLIST 这类内部关键字
    也一起收，由 FACTION_BY_EDID 决定用不用）。前缀 != 自身序号的（override 别人
    的记录）不收 —— 我们要的是「这个文件自己定义的关键字」。
    """
    buf = path.read_bytes()
    meta = read_tes4(buf)
    mask = 0xFFF if meta["small"] else 0xFFFFFF
    own_prefix = meta["self_index"]
    out: dict[int, str] = {}
    for pos, gsize, glabel, gtype in iter_groups(buf):
        if glabel != b"KYWD":
            continue
        p = pos + 24
        end = pos + gsize
        while p + 24 <= end:
            if buf[p:p + 4] == b"GRUP":
                sub = struct.unpack_from("<I", buf, p + 4)[0]
                if sub < 24:
                    break
                p += sub
                continue
            formid = struct.unpack_from("<I", buf, p + 12)[0]
            prefix = (formid >> 24) & 0xFF
            size = struct.unpack_from("<I", buf, p + 4)[0]
            payload = buf[p + 24:p + 24 + size]
            edid = None
            for q in range(0, len(payload) - 6):
                if payload[q:q + 4] == b"EDID":
                    slen = struct.unpack_from("<H", payload, q + 4)[0]
                    edid = payload[q + 6:q + 6 + slen].split(b"\x00")[0].decode("latin1")
                    break
            if edid and edid.startswith("FactionType") and prefix == own_prefix:
                out[formid & mask] = edid
            p += 24 + size
        break
    return out


class PluginIndex:
    """按需加载各 master 文件的 masters 列表与自己的 KYWD 表。"""

    def __init__(self, data_dir: Path):
        self.data_dir = data_dir
        self.masters: dict[str, list[str]] = {}
        self.kydd: dict[str, dict[int, str]] = {}

    def ensure(self, fname: str) -> bool:
        if fname in self.masters:
            return True
        path = self.data_dir / fname
        if not path.exists():
            print(f"  !! 找不到 {path} —— {fname} 的 FTYP 无法解析")
            return False
        buf = path.read_bytes()
        self.masters[fname] = read_tes4(buf)["masters"]
        self.kydd[fname] = parse_kydd_local_names(path)
        return True

    def resolve_ftyp(self, src_file: str, ftyp: int) -> tuple[str, int] | None:
        """文件内 FTYP -> (关键字所属文件, 记录号)。解析失败返回 None。"""
        if not self.ensure(src_file):
            return None
        masters = self.masters[src_file]
        idx = (ftyp >> 24) & 0xFF
        local = ftyp & 0xFFFFFF
        if idx == len(masters):
            target = src_file
        elif idx < len(masters):
            target = masters[idx]
        else:
            return None
        if not self.ensure(target):
            return None
        return target, local

    def lookup(self, fname: str, local: int) -> str | None:
        return self.kydd.get(fname, {}).get(local)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--quests", default="ref/quests_all.json",
                    help="quest_dump.py 的多 master 导出（只用来收集实际用到的 FTYP）")
    ap.add_argument("--data-dir", default=r"D:\SteamLibrary\steamapps\common\Starfield\Data",
                    help="Starfield 的 Data 目录（读 KYWD 关键字需要原始 ESM）")
    ap.add_argument("--out", default="ref/faction_types.json")
    a = ap.parse_args()

    quests = json.loads(Path(a.quests).read_text(encoding="utf-8"))
    index = PluginIndex(Path(a.data_dir))

    # 每个 master 里实际用到的 FTYP（文件内 FormID 原值）
    need: dict[str, set[int]] = {}
    for q in quests:
        ft = q.get("ftyp")
        if ft is None:
            continue
        need.setdefault(q["master"], set()).add(int(ft))

    out: dict[str, dict] = {}
    unresolved: list[str] = []
    for master in sorted(need):
        rows: dict[str, dict] = {}
        for ft in sorted(need[master]):
            resolved = index.resolve_ftyp(master, ft)
            if resolved is None:
                unresolved.append(f"{master} 0x{ft:08X}（前缀越界 / 文件缺失）")
                continue
            target, local = resolved
            edid = index.lookup(target, local)
            if not edid:
                unresolved.append(f"{master} 0x{ft:08X}（{target} 里找不到 local 0x{local:06X}）")
                continue
            faction = FACTION_BY_EDID.get(edid, -1)
            rows[f"{ft:08X}"] = {"edid": edid, "faction": faction}
        if rows:
            out[master] = rows

    # 统计打印（人工核对用）
    print("=== FTYP -> 阵营枚举 ===")
    for master in sorted(out):
        for key in sorted(out[master]):
            r = out[master][key]
            n = sum(1 for q in quests
                    if q["master"] == master and q.get("ftyp") is not None
                    and f"{int(q['ftyp']):08X}" == key)
            note = "" if r["faction"] >= 0 else "  ← 不在 UI 枚举里（按无阵营显示）"
            print(f"  {master:<20} 0x{key}  faction={r['faction']:>2}  "
                  f"{r['edid']}（{n} 条任务）{note}")
    if unresolved:
        print("\n!! 未能解析的 FTYP：")
        for u in unresolved:
            print(f"  {u}")

    out_path = Path(a.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "_note": "QUST FTYP 关键字 -> 原版 UI 阵营枚举（gen_faction_types.py 生成；"
                 "-1/缺省 = 无阵营）。枚举值见 ui/missionmenu/src/Shared/FactionUtils.as。",
        **out,
    }
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=1) + "\n",
                        encoding="utf-8")
    print(f"\nwrote {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
