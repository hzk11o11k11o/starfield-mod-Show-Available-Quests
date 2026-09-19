#!/usr/bin/env python3
"""tr_lookup.py - precise terminology lookup in the official EN->ZH table.

Usage:  python tools/re/tr_lookup.py "Maddox" "Colton" "Arbiter" ...
        python tools/re/tr_lookup.py --exact "Quinn"

Only *short* official entries are printed (a headword, not a whole sentence),
so the output stays readable when several terms are queried at once.
"""
from __future__ import annotations

import sys
from pathlib import Path

TABLE = "tr/loc/starfield_en_zh.tsv"


def load():
    off = {}
    for line in Path(TABLE).read_text(encoding="utf-8").splitlines():
        if not line or line.startswith("#"):
            continue
        p = line.split("\t")
        if len(p) >= 2 and p[0] and p[1]:
            off.setdefault(p[0].rstrip("\x00"), p[1].rstrip("\x00"))
    return off


def main():
    args = sys.argv[1:]
    exact = False
    if args and args[0] == "--exact":
        exact = True
        args = args[1:]
    maxlen = 60
    off = load()
    for t in args:
        tl = t.lower()
        print(f"=== {t}")
        n = 0
        for k, v in off.items():
            if exact:
                if k.lower() != tl:
                    continue
            else:
                if not (k.lower() == tl or k.lower().startswith(tl + " ")
                        or k.lower().startswith(tl + "'s")):
                    continue
            if len(k) > maxlen:
                continue
            print(f"   {k!r}\t=>\t{v!r}")
            n += 1
            if n >= 40:
                print("   ...")
                break
        if n == 0:
            print("   (none)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
