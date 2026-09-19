#!/usr/bin/env python3
"""cmp_ui_text.py - 对比 translate_*.txt 里若干 key 的中英文文本。

用法：python tools/esm/cmp_ui_text.py "ref/ui_translate/interface" $ALL $Main $Activity
"""
import io
import sys
from pathlib import Path

base = Path(sys.argv[1])
keys = sys.argv[2:]

tables = {}
for lang in ("zhhans", "en"):
    p = base / f"translate_{lang}.txt"
    if not p.exists():
        continue
    d = {}
    # 注意：translate_*.txt 是 UTF-16LE（带 BOM）+ TAB 分隔
    for line in io.open(p, encoding="utf-16", errors="replace"):
        line = line.rstrip("\n")
        if not line:
            continue
        parts = line.split("\t", 1)
        d[parts[0]] = parts[1] if len(parts) > 1 else ""
    tables[lang] = d

for k in keys:
    row = [f"{k}"]
    for lang in ("zhhans", "en"):
        row.append(f"{lang}={tables.get(lang, {}).get(k, '<missing>')}")
    print("  ".join(row))
