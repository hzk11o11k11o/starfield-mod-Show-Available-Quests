#!/usr/bin/env python3
r"""probe_override_sample.py - 找官方 ESM 里「override 基础游戏 cell 引用」的样本，抄它的组结构。

背景（第 29 轮）：要让 11 条非常驻任务板引用变成常驻（任何位置都能导航），需要在
`SAQ_ShowAvailableQuests.esm` 里写这些 REFR 的 override（flags |= 0x400）并放进
`CELL > InteriorBlock > InteriorSubBlock > CellChildren > CellPersistent` 组。

问题：**override 文件里的组结构到底怎么写**（是否要连 CELL 记录一起覆盖？
block/subblock 的 label 用原编号？GRUP 的 stamp/version 字段填什么？）。
答案不用猜 —— 官方 DLC（ShatteredSpace / SFBGS050）本身就 override 了基础游戏的
cell 内容，把它们当样本抄。

用法：
    python tools/esm/probe_override_sample.py <某个.esm> [<再来一个>…]
    python tools/esm/probe_override_sample.py            # 默认扫两个官方 DLC
"""
from __future__ import annotations

import struct
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from scan_entry_persistent import GROUP_NAMES, walk  # noqa: E402

DATA = Path(r"D:\SteamLibrary\steamapps\common\Starfield\Data")
DEFAULT = [DATA / "ShatteredSpace.esm", DATA / "SFBGS050.esm"]


def label_repr(gtype: int, label: bytes):
    if gtype == 0:
        return label.decode("latin1", "replace")
    return f"{GROUP_NAMES.get(gtype, gtype)}({struct.unpack('<i', label)[0]})"


def scan(path: Path) -> None:
    if not path.exists():
        print(f"!! 缺文件 {path}")
        return
    buf = path.read_bytes()
    print(f"\n=== {path.name}（{len(buf)} B）===")

    stats: Counter = Counter()
    samples: dict = {}

    def cb(sig, formid, flags, chain, cell, world, payload):
        types = tuple(g for g, _ in chain)
        if 6 in types or 8 in types or 9 in types:  # 只看挂在 cell children 下的记录
            key = (sig.decode("latin1"), types)
            stats[key] += 1
            if key not in samples:
                samples[key] = (formid, flags, chain, len(payload))

    walk(buf, cb)

    for key, n in stats.most_common(12):
        sig, types = key
        formid, flags, chain, plen = samples[key]
        tstr = " > ".join(label_repr(g, lb) for g, lb in chain)
        print(f"  {n:6d} 条  {sig}  formid=0x{formid:08X} flags=0x{flags:06X} payload={plen}B")
        print(f"          组链: {tstr}")


def main() -> int:
    paths = [Path(p) for p in sys.argv[1:]] or DEFAULT
    for p in paths:
        scan(p)
    return 0


if __name__ == "__main__":
    sys.exit(main())
