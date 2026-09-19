#!/usr/bin/env python3
"""tr_slice.py - pick one (recsig, subsig) class out of a trtool extract file.

The extract file produced by ``trtool.py extract`` is a flat list of every
translatable string of a plugin::

    #recsig fid  subsig occ kind text

Translating the long text classes (MESG DESC / BOOK DESC / QUST CNAM) is done
one class at a time, and the hand written spec files feed ``tr_mkbatch.py``
which needs the *raw line number* inside the extract file.  This tool is the
bridge: it filters the extract file down to a single class and keeps that line
number next to the text, so nobody has to copy/paste 500 character paragraphs.

Usage
-----
    python tools/re/tr_slice.py <extract.tsv> --sig MESG --sub DESC [-o out.tsv]
                               [--min-chars N] [--max-chars N]
                               [--limit N] [--sort chars|line] [--all]
                               [--dict dict.tsv]

Output columns:  #line  chars  hits  recsig/subsig  text

``line`` is the 1 based raw line number inside <extract.tsv> (header line = 1),
i.e. exactly what ``tr_mkbatch.py``'s spec file expects.  Duplicate strings are
collapsed and their hit count reported; the line number kept is the first one.

``--dict`` drops every string the dictionary already covers (same exact / strip /
case-folded fallbacks as ``tr_pipeline.py``), so the output is the *remaining work
list* of one class, still carrying the raw line numbers.
"""
from __future__ import annotations

import argparse
from pathlib import Path


def load_lookup(path):
    lookup = {}
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        if not line or line.startswith("#"):
            continue
        p = line.split("\t")
        if len(p) < 2 or not p[0]:
            continue
        k, v = p[0], p[1]
        lookup.setdefault(k, v)
        lookup.setdefault(k.strip(), v)
        lookup.setdefault(k.lower(), v)
        lookup.setdefault(k.strip().lower(), v)
    return lookup


def translated(lookup, t):
    return (lookup.get(t) or lookup.get(t.strip()) or lookup.get(t.lower())
            or lookup.get(t.strip().lower())) is not None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("extract")
    ap.add_argument("--sig", required=True, help="record signature, e.g. MESG")
    ap.add_argument("--sub", required=True, help="subrecord signature, e.g. DESC")
    ap.add_argument("-o", "--out")
    ap.add_argument("--min-chars", type=int, default=0)
    ap.add_argument("--max-chars", type=int, default=0)
    ap.add_argument("--limit", type=int, default=0, help="keep only the first N (after sort)")
    ap.add_argument("--sort", choices=["chars", "line"], default="chars")
    ap.add_argument("--all", action="store_true",
                    help="keep duplicate strings as separate rows (default: unique)")
    ap.add_argument("--dict", default=None,
                    help="drop strings already covered by this dictionary (remaining work list)")
    a = ap.parse_args()

    lookup = load_lookup(a.dict) if a.dict else None
    skipped = 0
    rows = []          # (line_no, text)
    for i, line in enumerate(Path(a.extract).read_text(encoding="utf-8").splitlines(), start=1):
        if not line or line.startswith("#"):
            continue
        p = line.split("\t")
        if len(p) < 6:
            continue
        if p[0] != a.sig or p[2] != a.sub:
            continue
        if len(p[5]) < a.min_chars:
            continue
        if a.max_chars and len(p[5]) > a.max_chars:
            continue
        if lookup is not None and translated(lookup, p[5]):
            skipped += 1
            continue
        rows.append((i, p[5]))

    if not a.all:
        first = {}
        hits = {}
        for ln, t in rows:
            first.setdefault(t, ln)
            hits[t] = hits.get(t, 0) + 1
        rows = [(first[t], t) for t in first]
    else:
        hits = {t: 1 for _, t in rows}

    if a.sort == "chars":
        rows.sort(key=lambda r: (len(r[1]), r[0]))
    else:
        rows.sort(key=lambda r: r[0])
    if a.limit:
        rows = rows[:a.limit]

    head = "#line\tchars\thits\t" + f"{a.sig}/{a.sub}\ttext"
    lines = [head]
    for ln, t in rows:
        lines.append(f"{ln}\t{len(t)}\t{hits[t]}\t{a.sig}/{a.sub}\t{t}")
    body = "\n".join(lines) + "\n"

    if a.out:
        Path(a.out).parent.mkdir(parents=True, exist_ok=True)
        Path(a.out).write_text(body, encoding="utf-8", newline="\n")
        total_chars = sum(len(t) for _, t in rows)
        print(f"slice: {a.sig}/{a.sub} rows={len(rows)} chars={total_chars} -> {a.out}")
    else:
        print(body, end="")
    extra = f" skipped_translated={skipped}" if a.dict else ""
    print(f"slice {a.sig}/{a.sub}: rows={len(rows)} chars={sum(len(t) for _, t in rows)}{extra}",
          flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
