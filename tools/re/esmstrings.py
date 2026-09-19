#!/usr/bin/env python3
"""在 .esm/.esp/.esl 里搜 ASCII 子串，并把命中处周围的字符串一起打出来。

为什么需要：Bethesda 的插件格式是把 EDID（编辑器 ID）以**明文 ASCII** 存在文件里，
所以「游戏里有没有一个叫 GuideEffect / Guide 的形态」这种问题，不用开 xEdit，
直接在二进制里搜字符串最快（1.4 GB 也就几秒）。

用法：
    python tools/re/esmstrings.py GuideEffect
    python tools/re/esmstrings.py Guide --limit 40 --context 120
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

DEFAULT_ESM = Path(r"D:\SteamLibrary\steamapps\common\Starfield\Data\Starfield.esm")

PRINTABLE = re.compile(rb"[\x20-\x7E]{4,}")


def chunks(path: Path, size: int = 8 << 20):
    with open(path, "rb") as f:
        while True:
            b = f.read(size)
            if not b:
                return
            yield b


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("needle")
    ap.add_argument("--esm", default=str(DEFAULT_ESM))
    ap.add_argument("--limit", type=int, default=40)
    ap.add_argument("--context", type=int, default=64, help="命中处向前/后看多少字节")
    a = ap.parse_args()

    needle = a.needle.encode()
    hits = 0
    seen: set[str] = set()
    offset = 0
    for blob in chunks(Path(a.esm)):
        k = blob.find(needle)
        while k != -1:
            lo = max(0, k - a.context)
            hi = min(len(blob), k + len(needle) + a.context)
            for m in PRINTABLE.finditer(blob[lo:hi]):
                s = m.group().decode("latin1")
                if needle.decode() not in s or s in seen:
                    continue
                seen.add(s)
                print(f"  0x{offset + lo + m.start():08X}  {s}")
                hits += 1
            if hits >= a.limit:
                print(f"[stopped] limit {a.limit} reached")
                return 0
            k = blob.find(needle, k + 1)
        offset += len(blob)

    print(f"[done] {hits} unique string(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
