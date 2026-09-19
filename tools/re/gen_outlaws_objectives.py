#!/usr/bin/env python3
"""gen_outlaws_objectives.py - build the Dark Universe: Outlaws quest objective
strings (QUST NNAM) from templates, reusing the already translated book and
person names.

Templates seen in the data:
    Read the <book> from <person>          -> 从<person>处阅读<book>
    Recover the <book> from the <ship>     -> 从<ship>处找回<book>
    Locate the <target> At <place>         -> 在<place>找到<target>
    Destroy the <target> At <dungeon>      -> 在<dungeon>摧毁<target>
    Recover the <target> At <dungeon>      -> 在<dungeon>找回<target>
    Make A Choice                          -> 做出选择

Usage:
    python tools/re/gen_outlaws_objectives.py --mod tr/out/du_outlaws_01.tsv \\
        --dict tr/lang/dict.tsv --places tr/lang/tokens_out_places.tsv \\
        -o tr/lang/batches/b32_outlaws_obj.tsv --miss tr/lang/todo/outlaws/miss_obj.txt
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from tr_pipeline import build_lookup, load_dict, load_rows, translate  # noqa: E402

TEMPLATES = [
    (re.compile(r"^Read the (.+) from (.+)$"), lambda a, b: f"从{b}处阅读{a}"),
    (re.compile(r"^Recover the (.+) from the (.+) cargo hold$"), lambda a, b: f"从{b}的货舱找回{a}"),
    (re.compile(r"^Recover the (.+) from the (.+)$"), lambda a, b: f"从{b}处找回{a}"),
    (re.compile(r"^Locate the (.+) At (.+)$"), lambda a, b: f"在{b}找到{a}"),
    (re.compile(r"^Destroy the (.+) At (.+)$"), lambda a, b: f"在{b}摧毁{a}"),
    (re.compile(r"^Recover the (.+) At (.+)$"), lambda a, b: f"在{b}找回{a}"),
    (re.compile(r"^Defeat (.+) At (.+)$"), lambda a, b: f"在{b}击败{a}"),
]

CODE_RE = re.compile(r"^[A-Z]{2,3}-\d+$")


def ship_name(words, text):
    """Translate "<CODE> <Name>" / "<Name> <CODE>" using the ship word table,
    keeping the designation code untouched.  Returns None when a word is
    unknown."""
    parts = text.split(" ")
    out = []
    for p in parts:
        if CODE_RE.match(p) or p.isdigit():
            out.append(p)
            continue
        z = translate(words, p)
        if z is None:
            return None
        out.append(z)
    return " ".join(out)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mod", required=True)
    ap.add_argument("--dict", required=True)
    ap.add_argument("--places", required=True)
    ap.add_argument("--ships", required=True)
    ap.add_argument("-o", "--out", required=True)
    ap.add_argument("--miss", default=None)
    a = ap.parse_args()

    d = load_dict(Path(a.dict))
    lookup = build_lookup(d)
    places = load_dict(Path(a.places))
    plookup = build_lookup(places)

    ships = load_dict(Path(a.ships))
    slookup = build_lookup(ships)

    def res(t):
        # alias placeholders must be preserved verbatim
        if t.startswith("<Alias=") and t.endswith(">"):
            return t
        if CODE_RE.match(t):
            return t
        return (translate(lookup, t) or translate(plookup, t)
                or ship_name(slookup, t))

    out = {}
    miss = []
    for r in load_rows(a.mod):
        if r[2] != "NNAM":
            continue
        text = r[5]
        if text == "Make A Choice":
            out[text] = "做出选择"
            continue
        done = False
        for rx, build in TEMPLATES:
            m = rx.match(text)
            if not m:
                continue
            x, y = m.group(1), m.group(2)
            zx, zy = res(x), res(y)
            if zx is None or zy is None:
                continue
            out[text] = build(zx, zy)
            done = True
            break
        if not done:
            miss.append(text)

    Path(a.out).write_text(
        "#en\tzh\n# Dark Universe: Outlaws —— 由模板组合的任务目标\n"
        + "\n".join(f"{k}\t{v}" for k, v in sorted(out.items())) + "\n",
        encoding="utf-8")
    print(f"objectives: composed={len(out)} unresolved={len(miss)} -> {a.out}")
    if a.miss:
        Path(a.miss).write_text("\n".join(miss) + "\n", encoding="utf-8")
        print(f"  unresolved list -> {a.miss}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
