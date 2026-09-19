#!/usr/bin/env python3
"""临时工具：在官方对照表里按中文译文子串查找条目。"""
import sys
from pathlib import Path

rows = []
for line in Path("tr/loc/starfield_en_zh.tsv").read_text(encoding="utf-8").splitlines():
    if not line or line.startswith("#"):
        continue
    p = line.split("\t")
    if len(p) >= 2 and p[0] and p[1]:
        rows.append((p[0], p[1]))

for t in sys.argv[1:]:
    print(f"=== {t}")
    n = 0
    for en, zh in rows:
        if t in zh:
            print(f"   {en!r}\t=>\t{zh!r}")
            n += 1
            if n >= 60:
                print("   ...")
                break
