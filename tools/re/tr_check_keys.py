#!/usr/bin/env python3
"""tr_check_keys.py - validate a hand written dictionary batch against an extract file.

Every key in a batch must appear *verbatim* in the extract file's text column,
otherwise tr_pipeline.map will silently skip it and the string stays English.
This is the cheap defence against the "typed the English by hand" mistake.

Usage:
    python tools/re/tr_check_keys.py <extract.tsv> <batch.tsv> [batch2.tsv ...]
"""
from __future__ import annotations

import sys
from pathlib import Path


def load_extract(path):
    texts = set()
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        if not line or line.startswith("#"):
            continue
        p = line.split("\t")
        if len(p) >= 6:
            texts.add(p[5])
    return texts


def main():
    extract = Path(sys.argv[1])
    texts = load_extract(extract)
    print(f"extract {extract.name}: {len(texts)} unique texts")
    bad_total = 0
    for b in sys.argv[2:]:
        bad = []
        n = 0
        for line in Path(b).read_text(encoding="utf-8").splitlines():
            if not line or line.startswith("#"):
                continue
            k = line.split("\t")[0]
            n += 1
            if k not in texts:
                bad.append(k)
        print(f"{Path(b).name}: keys={n} not-found={len(bad)}")
        for k in bad[:40]:
            print(f"   MISS {k[:120]!r}")
        bad_total += len(bad)
    print(f"TOTAL not-found = {bad_total}")
    return 1 if bad_total else 0


if __name__ == "__main__":
    sys.exit(main())
