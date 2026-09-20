#!/usr/bin/env python3
r"""find_added_persistent_refs.py - 找「往基础游戏 cell 添加**新增常驻引用**」的真实 mod 样本（第 30 轮）。

## 为什么

第 29 轮把 11 条任务板 REFR `override` + `CellPersistent` 组 + flags 0x400 常驻化，
实机无效（12:45 会话 `入口=12(可导航 2)`，10 条取不到）。
`check_persist_precedent.py` 证明：官方 SFBGS003/008 的 70 条同类 override，
**原记录本来就是常驻** —— 「非常驻 → 常驻」没有任何先例，引擎不认（override 只换数据、不换分类）。

⇒ 正确路线是**新增常驻引用**（记录从第一次加载就归入 CellPersistent 组）。
本脚本在本机 mod 里找这种写法（任何 mod 给城市 cell 加常驻物件/NPC 都算），
确认：① 引擎接受这种结构（有先例）；② 记录 payload / 组结构的确切形状（照抄）。

用法：
    python tools/esm/find_added_persistent_refs.py            # 扫 MO2 mods + Data 第三方
    python tools/esm/find_added_persistent_refs.py always     # 只看名字含 always 的插件
"""
from __future__ import annotations

import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from esm_probe import REF_SIGS, record_base_form, record_edid, subrecords  # noqa: E402
from scan_entry_persistent import walk  # noqa: E402

DATA = Path(r"D:\SteamLibrary\steamapps\common\Starfield\Data")
MODS = Path(r"D:\Mod Organizer 2\starfield_mods\mods")

OFFICIAL = {"Starfield.esm", "ShatteredSpace.esm", "SFBGS050.esm", "SFBGS00D.esm",
            "BlueprintShips-Starfield.esm", "Constellation.esm", "SFBGS003.esm",
            "SFBGS004.esm", "SFBGS006.esm", "SFBGS007.esm", "SFBGS008.esm"}


def refr_position(payload: bytes):
    for sig, sp in subrecords(payload):
        if sig == b"DATA" and len(sp) >= 12:
            return struct.unpack_from("<fff", sp, 0)
    return None


def scan(path: Path) -> dict:
    buf = path.read_bytes()
    r = {"name": path.name, "n_added": 0, "n_added_pers": 0,
         "n_in_basegame_cell": 0, "samples": []}

    def cb(sig, formid, flags, chain, cell, world, payload):
        if sig not in REF_SIGS or (formid >> 24) == 0:
            return
        r["n_added"] += 1
        types = [g for g, _ in chain]
        if not types or types[-1] != 8:      # 尾部必须是 CellPersistent
            return
        r["n_added_pers"] += 1
        # cell 归属：最后一个 CellChildren(6) 组的 label（完整 FormID）
        cell_label = None
        for g, lab in chain:
            if g == 6:
                cell_label = struct.unpack_from("<i", lab)[0] & 0xFFFFFFFF
        in_base = cell_label is not None and (cell_label >> 24) == 0 and cell_label != 0
        if in_base:
            r["n_in_basegame_cell"] += 1
        if len(r["samples"]) < 6 and (in_base or r["n_added_pers"] <= 2):
            r["samples"].append({
                "sig": sig.decode("latin1"), "formid": formid, "flags": flags,
                "chain": types, "cellLabel": cell_label, "base": record_base_form(payload),
                "edid": record_edid(payload), "pos": refr_position(payload),
                "subs": [s.decode("latin1") for s, _ in subrecords(payload)],
                "size": len(payload),
            })

    walk(buf, cb)
    return r


def main() -> int:
    filt = sys.argv[1].lower() if len(sys.argv) > 1 else ""
    paths: list[Path] = []
    for root in (MODS, DATA):
        if root.exists():
            paths += [p for p in root.rglob("*.es*") if p.suffix.lower() in (".esm", ".esp", ".esl")]
    paths = [p for p in paths if p.name not in OFFICIAL and p.stat().st_size < 300_000_000]
    if filt:
        paths = [p for p in paths if filt in p.name.lower()]
    if not paths:
        print("没找到可扫的插件")
        return 0

    total_base = 0
    for p in sorted(paths):
        try:
            r = scan(p)
        except Exception as e:  # noqa: BLE001
            print(f"{r['name'] if 'r' in dir() else p.name}: 扫描失败 {e}")
            continue
        if r["n_added_pers"] == 0:
            continue
        total_base += r["n_in_basegame_cell"]
        print(f"\n=== {r['name']} ===")
        print(f"  新增引用 {r['n_added']} 条；其中常驻组(新增) {r['n_added_pers']} 条；"
              f"落在**基础游戏 cell** 的 {r['n_in_basegame_cell']} 条")
        for s in r["samples"]:
            print(f"    {s['sig']} 0x{s['formid']:08X} flags=0x{s['flags']:06X} "
                  f"base=0x{s['base']:08X} edid={s['edid']!r} size={s['size']}")
            print(f"        组链={s['chain']} cellLabel=0x{s['cellLabel']:08X} pos={s['pos']}")
            print(f"        子记录={s['subs']}")

    print(f"\n总结：落在基础游戏 cell 的新增常驻引用共 {total_base} 条")
    return 0


if __name__ == "__main__":
    sys.exit(main())
