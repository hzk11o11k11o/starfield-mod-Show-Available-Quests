#!/usr/bin/env python3
"""临时工具：在官方英中对照表里按子串查找术语（用于名词统一）。"""
import sys
from pathlib import Path

off = {}
for line in Path("tr/loc/starfield_en_zh.tsv").read_text(encoding="utf-8").splitlines():
    if not line or line.startswith("#"):
        continue
    p = line.split("\t")
    if len(p) >= 2 and p[0] and p[1]:
        off.setdefault(p[0], p[1])

terms = sys.argv[1:]
for t in terms:
    tl = t.lower()
    print(f"=== {t}")
    n = 0
    for k, v in off.items():
        if tl in k.lower():
            print(f"   {k!r}\t=>\t{v!r}")
            n += 1
            if n >= 200:
                print("   ...")
                break
