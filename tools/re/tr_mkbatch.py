#!/usr/bin/env python3
"""临时工具：按「抽取文件行号 -> 译文」生成词典批次，避免手抄长英文串出错。

用法: python tools/re/_mkbatch.py <extract.tsv> <spec.txt> <out_batch.tsv>

spec.txt 每行: <行号>\t<中文>
行号 = 抽取文件的行号（带 # 的表头行算第 1 行，空行/注释行不参与）。
"""
import sys
from pathlib import Path

src, spec, out = sys.argv[1], sys.argv[2], sys.argv[3]
en = {}
for i, l in enumerate(Path(src).read_text(encoding="utf-8").splitlines(), start=1):
    if not l or l.startswith("#") or l.count("\t") < 5:
        continue
    en[i] = l.split("\t")[5]

lines = []
seen = set()
used = set()
for l in Path(spec).read_text(encoding="utf-8").splitlines():
    if not l or l.startswith("#"):
        continue
    n, zh = l.split("\t", 1)
    n = int(n)
    if n not in en:
        raise SystemExit(f"spec 行号 {n} 在 {src} 里没有对应数据行（{l!r}）")
    used.add(n)
    key = en[n]
    if key in seen:
        continue
    seen.add(key)
    lines.append(key + "\t" + zh)

Path(out).write_text("#en\tzh\n" + "\n".join(lines) + "\n", encoding="utf-8")
print(f"{len(lines)} entries -> {out}")
print(f"spec lines used={len(used)}")
