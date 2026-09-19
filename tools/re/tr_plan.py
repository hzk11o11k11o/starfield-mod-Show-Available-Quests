#!/usr/bin/env python3
"""tr_plan.py - split a tr_slice.py output into translation batches by size.

The long text classes (MESG DESC / BOOK DESC / QUST CNAM) are translated in
batches of roughly N characters so that a single hand written spec file stays
manageable.  ``tr_slice.py`` already sorts the rows by character count (short
first), so cutting the list into consecutive runs gives short-first batches and
no batch is dominated by one giant paragraph.

Usage
-----
    python tools/re/tr_plan.py <slice.tsv> [--target 16000] [-o plan.tsv]

``slice.tsv`` is the output of ``tr_slice.py`` (columns: #line chars hits class text).
The plan file has one row per batch::

    #batch  rows  chars  first_line  last_line  row_from  row_to

``row_from`` / ``row_to`` are the 1 based data row indexes (header excluded) of
``slice.tsv``, i.e. exactly what you feed to ``read_file(offset=..., limit=...)``
to look at one batch.
"""
from __future__ import annotations

import argparse
from pathlib import Path


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("slice")
    ap.add_argument("--target", type=int, default=16000)
    ap.add_argument("-o", "--out")
    a = ap.parse_args()

    rows = []
    for line in Path(a.slice).read_text(encoding="utf-8").splitlines()[1:]:
        p = line.split("\t")
        if len(p) >= 5:
            rows.append((int(p[0]), int(p[1])))

    batches = []
    cur = []
    cc = 0
    for r in rows:
        cur.append(r)
        cc += r[1]
        if cc >= a.target:
            batches.append((cur, cc))
            cur = []
            cc = 0
    if cur:
        batches.append((cur, cc))

    lines = ["#batch\trows\tchars\tfirst_line\tlast_line\trow_from\trow_to"]
    idx = 0
    for i, (b, cc) in enumerate(batches, 1):
        lines.append(f"{i}\t{len(b)}\t{cc}\t{b[0][0]}\t{b[-1][0]}\t"
                     f"{idx + 1}\t{idx + len(b)}")
        idx += len(b)
    body = "\n".join(lines) + "\n"
    if a.out:
        Path(a.out).write_text(body, encoding="utf-8", newline="\n")
        print(f"plan: batches={len(batches)} rows={len(rows)} "
              f"chars={sum(r[1] for r in rows)} -> {a.out}")
    else:
        print(body, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
