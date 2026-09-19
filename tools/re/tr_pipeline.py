#!/usr/bin/env python3
"""tr_pipeline.py - dictionary driven translation pipeline for Starfield mods.

The five Dark Universe plugins carry ~1.6M characters of text.  Translating per
record would duplicate work and wreck terminology consistency, so everything
goes through ONE dictionary keyed by the English source string:

    tr/lang/dict.tsv     en <TAB> zh          (hand written + official matches)

Flow
----
  1. tools/re/trtool.py extract <plugin> -o tr/out/<mod>.tsv
  2. tr_pipeline.py seed        -> seed dict.tsv from the official game strings
  3. tr_pipeline.py todo        -> the still untranslated unique strings
     (translate them, append to dict.tsv)
  4. tr_pipeline.py map <mod>   -> tr/out/<mod>.map.tsv  (recsig fid subsig occ zh)
  5. tools/re/trtool.py apply <plugin> --map tr/out/<mod>.map.tsv -o out/<mod>.esm

Subcommands
-----------
  seed   --official EN_ZH.tsv --mods a.tsv b.tsv ... -o dict.tsv [--merge]
  todo   --mods ... --dict dict.tsv [--max-chars N] [--min-chars N] [-o todo.tsv]
  map    <mod.tsv> --dict dict.tsv -o map.tsv [--coverage]
  status --mods ... --dict dict.tsv
"""
from __future__ import annotations

import argparse
import collections
import sys
from pathlib import Path


def load_dict(path: Path):
    d = {}
    if not Path(path).exists():
        return d
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        if not line or line.startswith("#"):
            continue
        p = line.split("\t")
        if len(p) >= 2 and p[0]:
            d[p[0]] = p[1]
    return d


def build_lookup(d):
    """Exact match first, then stripped / case folded, then stripped+folded.

    Mod strings frequently carry a stray leading or trailing space that is
    invisible in the todo file, so the loose fallbacks are not optional.
    """
    lookup = {}
    for k, v in d.items():
        lookup.setdefault(k, v)
        lookup.setdefault(k.strip(), v)
        lookup.setdefault(k.lower(), v)
        lookup.setdefault(k.strip().lower(), v)
    return lookup


def translate(lookup, t):
    return (lookup.get(t) or lookup.get(t.strip()) or lookup.get(t.lower())
            or lookup.get(t.strip().lower()))


def load_rows(path):
    rows = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        if not line or line.startswith("#"):
            continue
        p = line.split("\t")
        if len(p) >= 6:
            rows.append(p)
    return rows


def cmd_seed(a):
    official = {}
    for line in Path(a.official).read_text(encoding="utf-8").splitlines():
        if not line or line.startswith("#"):
            continue
        p = line.split("\t")
        if len(p) >= 2:
            official.setdefault(p[0], p[1])
    low = {k.lower(): v for k, v in official.items()}

    seed = {}
    for f in a.mods:
        for r in load_rows(f):
            t = r[5]
            if t in official:
                seed.setdefault(t, official[t])
            elif t.lower() in low:
                seed.setdefault(t, low[t.lower()])

    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    existing = load_dict(out) if a.merge else {}
    lines = ["#en\tzh"]
    merged = dict(existing)
    for k, v in seed.items():
        merged.setdefault(k, v)
    for k, v in merged.items():
        lines.append(k + "\t" + v)
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"seed: official matches={len(seed)} dict now={len(merged)} -> {out}")


def cmd_todo(a):
    d = load_dict(Path(a.dict))
    lookup = build_lookup(d)
    prefix_dict = load_dict(Path(a.prefix)) if getattr(a, "prefix", None) else {}
    suffix_dict = load_dict(Path(a.suffix)) if getattr(a, "suffix", None) else {}
    seen = {}
    for f in a.mods:
        for r in load_rows(f):
            t = r[5]
            if translate(lookup, t) is not None:
                continue
            if (prefix_dict or suffix_dict) and compose(prefix_dict, suffix_dict, t) is not None:
                continue
            if len(t) < a.min_chars or (a.max_chars and len(t) > a.max_chars):
                continue
            seen.setdefault(t, [0, r[0], r[2]])
            seen[t][0] += 1
    items = sorted(seen.items(), key=lambda kv: (len(kv[0]), kv[0]))
    if a.out:
        with open(a.out, "w", encoding="utf-8", newline="\n") as f:
            f.write("#chars\thits\tsig/sub\ttext\n")
            for t, (n, sig, sub) in items:
                f.write(f"{len(t)}\t{n}\t{sig}/{sub}\t{t}\n")
        print(f"todo: {len(items)} unique strings -> {a.out}")
    else:
        for t, (n, sig, sub) in items:
            print(f"{len(t):>5} {n:>4} {sig}/{sub:<4} {t[:110]}")
    print(f"todo total={len(items)}", file=sys.stderr)


def cmd_merge(a):
    """Merge any number of en<TAB>zh files into one dictionary. Earlier files
    win, so put the hand written batches before the auto seed if you want the
    hand written wording to take precedence."""
    merged = {}
    for f in a.inputs:
        for line in Path(f).read_text(encoding="utf-8").splitlines():
            if not line or line.startswith("#"):
                continue
            p = line.split("\t")
            if len(p) >= 2 and p[0]:
                merged.setdefault(p[0], p[1])
    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    lines = ["#en\tzh"]
    for k, v in merged.items():
        lines.append(k + "\t" + v)
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"merge: {len(merged)} entries -> {out}")


import re

CODE_RE = re.compile(r"^[A-Z0-9]+(-[A-Z0-9]+)*$")


def has_digit(s):
    return any(ch.isdigit() for ch in s)


def compose(prefix_dict, suffix_dict, text):
    """Dark Universe builds thousands of names as "<faction> <role>", so a small
    prefix table plus a small role table covers the whole set.  Returns None when
    the string does not follow that pattern."""
    if " " not in text:
        return None
    first, rest = text.split(" ", 1)
    pre = prefix_dict.get(first)
    if pre is None:
        return None
    suf = suffix_dict.get(rest)
    if suf is not None:
        return pre + suf
    # "<faction> <designation code>", e.g. "Forge GZ-366"
    if CODE_RE.match(rest) and has_digit(rest):
        return pre + " " + rest
    # "<faction> <code> <tail>", e.g. "Den CR-014 Key"
    m = re.match(r"^([A-Z0-9]+(?:-[A-Z0-9]+)*) (.+)$", rest)
    if m and has_digit(m.group(1)):
        tail = suffix_dict.get(m.group(2))
        if tail is not None:
            return pre + " " + m.group(1) + " " + tail
    return None


def cmd_map(a):
    d = load_dict(Path(a.dict))
    lookup = build_lookup(d)
    prefix_dict = load_dict(Path(a.prefix)) if getattr(a, "prefix", None) else {}
    suffix_dict = load_dict(Path(a.suffix)) if getattr(a, "suffix", None) else {}
    rows = load_rows(a.mod)
    out = []
    miss = 0
    composed = 0
    for r in rows:
        t = r[5]
        zh = translate(lookup, t)
        if zh is None and (prefix_dict or suffix_dict):
            zh = compose(prefix_dict, suffix_dict, t)
            if zh is not None:
                composed += 1
        if zh is None:
            miss += 1
            continue
        out.append((r[0], r[1], r[2], r[3], zh))
    with open(a.out, "w", encoding="utf-8", newline="\n") as f:
        f.write("#recsig\tfid\tsubsig\tocc\ttext\n")
        for r in out:
            f.write("\t".join(r) + "\n")
    total = len(rows)
    print(f"map: {Path(a.mod).name} rows={total} translated={len(out)} "
          f"(composed={composed}) missing={miss} "
          f"({100.0*len(out)/max(total,1):.1f}%) -> {a.out}")


def cmd_status(a):
    d = load_dict(Path(a.dict))
    lookup = build_lookup(d)
    grand = [0, 0]
    print(f"{'mod':<18}{'rows':>8}{'translated':>12}{'unique':>9}{'uniq done':>11}{'chars left':>12}")
    for f in a.mods:
        rows = load_rows(f)
        tot = len(rows)
        done = sum(1 for r in rows if translate(lookup, r[5]) is not None)
        uniq = set(r[5] for r in rows)
        udone = sum(1 for t in uniq if translate(lookup, t) is not None)
        left = sum(len(t) for t in uniq if translate(lookup, t) is None)
        grand[0] += tot
        grand[1] += done
        print(f"{Path(f).stem:<18}{tot:>8}{done:>12}{len(uniq):>9}{udone:>11}{left:>12}")
    print(f"{'TOTAL':<18}{grand[0]:>8}{grand[1]:>12}")


def main() -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("seed")
    p.add_argument("--official", required=True)
    p.add_argument("--mods", nargs="+", required=True)
    p.add_argument("-o", "--out", required=True)
    p.add_argument("--merge", action="store_true")
    p.set_defaults(func=cmd_seed)

    p = sub.add_parser("todo")
    p.add_argument("--mods", nargs="+", required=True)
    p.add_argument("--dict", required=True)
    p.add_argument("--prefix", default=None)
    p.add_argument("--suffix", default=None)
    p.add_argument("--max-chars", type=int, default=0)
    p.add_argument("--min-chars", type=int, default=1)
    p.add_argument("-o", "--out")
    p.set_defaults(func=cmd_todo)

    p = sub.add_parser("merge")
    p.add_argument("inputs", nargs="+")
    p.add_argument("-o", "--out", required=True)
    p.set_defaults(func=cmd_merge)

    p = sub.add_parser("map")
    p.add_argument("mod")
    p.add_argument("--dict", required=True)
    p.add_argument("--prefix", default=None, help="faction/gang token table")
    p.add_argument("--suffix", default=None, help="role token table")
    p.add_argument("-o", "--out", required=True)
    p.set_defaults(func=cmd_map)

    p = sub.add_parser("status")
    p.add_argument("--mods", nargs="+", required=True)
    p.add_argument("--dict", required=True)
    p.set_defaults(func=cmd_status)

    a = ap.parse_args()
    return a.func(a) or 0


if __name__ == "__main__":
    sys.exit(main())
