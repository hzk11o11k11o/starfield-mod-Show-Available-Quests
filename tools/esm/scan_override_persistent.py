#!/usr/bin/env python3
r"""scan_override_persistent.py - 扫第三方 ESM：有没有「override 基础游戏引用、并放进常驻组」的先例。

用途（第 29 轮）：本项目要把 11 条非常驻任务板引用 override 成常驻（任何位置可导航）。
先在本机所有第三方 mod 里找同款操作的样本 —— 有先例 = 这个写法被社区验证过。

输出：每个文件一行统计 + 命中样本（formid/flags/组链）。
"""
from __future__ import annotations

import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from esm_probe import REF_SIGS  # noqa: E402
from scan_entry_persistent import walk, GROUP_NAMES  # noqa: E402

DATA = Path(r"D:\SteamLibrary\steamapps\common\Starfield\Data")
MODS = Path(r"D:\Mod Organizer 2\starfield_mods\mods")


def scan(path: Path) -> None:
    buf = path.read_bytes()
    n_ref = n_override = n_ov_pers = n_ov_temp = 0
    samples: list = []
    # 只覆盖「引用」的插件：对应 cell 有没有同时被 CELL 记录覆盖？→ 决定我们是否需要写 CELL override
    cell_override_fids: set[int] = set()
    cell_used_by_ov_pers: set[int] = set()

    def cb(sig, formid, flags, chain, cell, world, payload):
        nonlocal n_ref, n_override, n_ov_pers, n_ov_temp
        if sig == b"CELL" and (formid >> 24) == 0:
            cell_override_fids.add(formid & 0xFFFFFF)
            return
        if sig not in REF_SIGS:
            return
        n_ref += 1
        if (formid >> 24) != 0:
            return  # 文件自己的新记录
        n_override += 1
        last = chain[-1][0] if chain else -1
        if last == 8:
            n_ov_pers += 1
            if len(chain) >= 2 and chain[-2][0] == 6:
                cell_used_by_ov_pers.add(struct.unpack_from("<i", chain[-2][1])[0] & 0xFFFFFF)
            if len(samples) < 4:
                samples.append((sig.decode("latin1"), formid, flags, [GROUP_NAMES.get(g, g) for g, _ in chain]))
        elif last == 9:
            n_ov_temp += 1

    walk(buf, cb)
    name = path.name
    hit = sum(1 for s in samples if s[2] & 0x400)
    print(f"{name:<38s} 引用={n_ref:<7d} override={n_override:<7d} "
          f"override+常驻组={n_ov_pers:<6d} override+临时组={n_ov_temp:<7d} flags&0x400 命中={hit}")
    for sig, formid, flags, ch in samples:
        print(f"    样本 {sig} 0x{formid:08X} flags=0x{flags:06X} 组链={' > '.join(ch)}")
    if cell_used_by_ov_pers:
        with_cell = cell_used_by_ov_pers & cell_override_fids
        print(f"    ★ 这些 override 引用所在 cell（{len(cell_used_by_ov_pers)} 个）里，"
              f"同时被 CELL 记录覆盖的有 {len(with_cell)} 个"
              f"（= 有 {len(cell_used_by_ov_pers) - len(with_cell)} 个 cell「只覆盖引用、不覆盖 CELL」）")


def main() -> int:
    filt = sys.argv[1].lower() if len(sys.argv) > 1 else ""
    paths: list[Path] = []
    for root in (MODS, DATA):
        if root.exists():
            paths += [p for p in root.rglob("*.es*") if p.suffix.lower() in (".esm", ".esp", ".esl")]
    paths = [p for p in paths
             if p.name not in ("Starfield.esm", "ShatteredSpace.esm", "SFBGS050.esm", "SFBGS00D.esm",
                               "BlueprintShips-Starfield.esm", "Constellation.esm")
             and p.stat().st_size < 300_000_000]
    if filt:
        paths = [p for p in paths if filt in p.name.lower()]
    if not paths:
        print("没找到可扫的插件")
        return 0
    for p in sorted(paths):
        try:
            scan(p)
        except Exception as e:  # noqa: BLE001
            print(f"{p.name}: 扫描失败 {e}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
