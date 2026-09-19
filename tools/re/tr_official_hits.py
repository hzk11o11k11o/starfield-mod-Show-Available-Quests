#!/usr/bin/env python3
"""临时工具：查 mod 字符串在官方英中对照表里的命中项（含带尾部 NUL 的变体）。"""
import sys
from pathlib import Path

off = {}
for line in Path("tr/loc/starfield_en_zh.tsv").read_text(encoding="utf-8").splitlines():
    if not line or line.startswith("#"):
        continue
    p = line.split("\t")
    if len(p) >= 2 and p[0] and p[1]:
        off.setdefault(p[0], p[1])
low = {}
for k, v in off.items():
    low.setdefault(k.strip("\x00").lower(), v)


def find(t):
    for k in (t, t + "\x00", t.strip(), t.strip() + "\x00"):
        if k in off:
            return off[k]
    return low.get(t.strip("\x00").lower())


uniq = []
for f in sys.argv[1:]:
    for line in Path(f).read_text(encoding="utf-8").splitlines():
        if not line or line.startswith("#"):
            continue
        p = line.split("\t")
        if len(p) >= 6:
            uniq.append(p[5])

seen = set()
n = 0
for t in uniq:
    if t in seen:
        continue
    seen.add(t)
    v = find(t)
    if v:
        n += 1
        print(f"{t!r}\t=>\t{v!r}")
print(f"--- official hits: {n} / {len(seen)} unique", file=sys.stderr)
