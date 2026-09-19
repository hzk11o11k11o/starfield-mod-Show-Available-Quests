#!/usr/bin/env python3
"""split_names.py - split "<prefix> <lastword>" at the last space so that a big
list of generated NPC names can be translated from two small tables.

"Erin Cho"        -> ("Erin", "Cho")
"Ghost Crew Mixer"-> ("Ghost Crew", "Mixer")
'Zuri "Vector" Msuya' -> ('Zuri "Vector"', 'Msuya')

Usage:
    python tools/re/split_names.py <todo.tsv> <sub> [--side pre|last]
"""
from __future__ import annotations

import argparse
import collections
import sys
from pathlib import Path


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("todo")
    ap.add_argument("sub")
    ap.add_argument("--side", choices=["pre", "last"], default="last")
    ap.add_argument("--min", type=int, default=1)
    a = ap.parse_args()

    pre = collections.Counter()
    last = collections.Counter()
    for line in Path(a.todo).read_text(encoding="utf-8").splitlines():
        if not line or line.startswith("#"):
            continue
        p = line.split("\t")
        if len(p) < 4 or p[2] != a.sub:
            continue
        text = p[3]
        i = text.rfind(" ")
        if i < 0:
            last[text] += 1
            continue
        pre[text[:i]] += 1
        last[text[i + 1:]] += 1

    counter = pre if a.side == "pre" else last
    print(f"--- {a.side} ({len(counter)} distinct) ---")
    for k, v in counter.most_common():
        if v >= a.min:
            print(f"{v}\t{k}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
