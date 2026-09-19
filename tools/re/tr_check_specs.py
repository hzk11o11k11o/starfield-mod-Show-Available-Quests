#!/usr/bin/env python3
"""tr_check_specs.py - defensive check for spec files before tr_mkbatch.py.

``tr_mkbatch.py`` looks the English up by raw extract line number only, so a
typo in a line number silently maps a translation onto a *different* string
(this is exactly the bug that cost a full rebuild on the BOOK DESC batches).

This tool walks the spec files and asserts that every referenced line really is
the expected ``(recsig, subsig)`` class.

Usage
-----
    python tools/re/tr_check_specs.py <extract.tsv> <SIG> <SUB> spec1.txt [spec2.txt ...]

Exit code is non zero if any line is wrong, so it can gate a build step.
"""
from __future__ import annotations

import sys
from pathlib import Path


def main() -> int:
    src, sig, sub = sys.argv[1], sys.argv[2], sys.argv[3]
    specs = sys.argv[4:]

    rows = {}
    for i, line in enumerate(Path(src).read_text(encoding="utf-8").splitlines(), start=1):
        if not line or line.startswith("#"):
            continue
        p = line.split("\t")
        if len(p) >= 6:
            rows[i] = (p[0], p[2])

    bad = []
    seen = {}
    total = 0
    for f in specs:
        for ln, line in enumerate(Path(f).read_text(encoding="utf-8").splitlines(), start=1):
            if not line or line.startswith("#"):
                continue
            p = line.split("\t", 1)
            if len(p) < 2 or not p[0].strip().isdigit():
                bad.append((f, ln, "malformed", line[:60]))
                continue
            n = int(p[0])
            total += 1
            if n not in rows:
                bad.append((f, ln, "no such line", n))
                continue
            if rows[n] != (sig, sub):
                bad.append((f, ln, f"class={rows[n][0]}/{rows[n][1]}", n))
            if n in seen:
                bad.append((f, ln, f"duplicate of {seen[n]}", n))
            else:
                seen[n] = f

    for f, ln, why, what in bad:
        print(f"BAD  {f}:{ln}  {why}  {what}")
    print(f"checked lines={total} unique={len(seen)} bad={len(bad)}")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
