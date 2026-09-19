#!/usr/bin/env python3
"""tokstat.py - split a todo list into first token / rest so that combinatorial
content (Dark Universe generates thousands of NPC names such as
"Bandit Dock Lead" = faction + role) can be translated from two small tables
instead of thousands of whole strings.

Usage:
    python tools/re/tokstat.py <todo.tsv> [--sub SIG/SUB] [--min N]
"""
from __future__ import annotations

import argparse
import collections
import sys
from pathlib import Path


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("todo")
    ap.add_argument("--sub", default=None, help="filter by sig/sub, e.g. NPC_/FULL")
    ap.add_argument("--min", type=int, default=1)
    ap.add_argument("--show", choices=["first", "rest", "all"], default="all")
    a = ap.parse_args()

    first = collections.Counter()
    rest = collections.Counter()
    words = collections.Counter()
    for line in Path(a.todo).read_text(encoding="utf-8").splitlines():
        if not line or line.startswith("#"):
            continue
        p = line.split("\t")
        if len(p) < 4:
            continue
        sub = p[2]
        if a.sub and sub != a.sub:
            continue
        text = p[3]
        parts = text.split(" ", 1)
        first[parts[0]] += 1
        if len(parts) > 1:
            rest[parts[1]] += 1
        for w in text.split():
            words[w] += 1

    def show(counter, label):
        print(f"--- {label} ({len(counter)} distinct) ---")
        for k, v in counter.most_common():
            if v < a.min:
                continue
            print(f"  {v:>4}  {k}")

    if a.show in ("first", "all"):
        show(first, "first token")
    if a.show in ("rest", "all"):
        show(rest, "rest")
    if a.show == "all":
        show(words, "all words")
    return 0


if __name__ == "__main__":
    sys.exit(main())
