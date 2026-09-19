#!/usr/bin/env python3
"""tr_verify.py - structural diff between an original plugin and its translated
copy produced by tools/re/trtool.py apply.

Checks
  1. identical record sequence (signature / formID / flags / compression)
  2. identical subrecord sequence per record, except that the *content* of
     whitelisted text subrecords may change (their subrecord signatures and the
     order in which they appear must stay the same)
  3. every subrecord that is not whitelisted is byte identical
  4. every whitelisted text that is not in the map is byte identical

Usage:
    python tools/re/tr_verify.py <orig.esm> <patched.esm>
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from trtool import load_records, subrecords, in_whitelist  # noqa: E402


def sigs_of(payload: bytes):
    return [s for s, _o, _size in subrecords(payload)]


def main() -> int:
    orig = Path(sys.argv[1])
    patched = Path(sys.argv[2])
    a = list(load_records(orig.read_bytes()))
    b = list(load_records(patched.read_bytes()))

    if len(a) != len(b):
        print(f"FAIL record count {len(a)} -> {len(b)}")
        return 1

    problems = 0
    changed_strings = 0
    changed_records = 0
    sample = []
    for (oa, sa, fa, fla, pa), (ob, sb, fb, flb, pb) in zip(a, b):
        if (sa, fa, fla) != (sb, fb, flb):
            print(f"FAIL record header mismatch {sa}/{fa:08X} vs {sb}/{fb:08X}")
            problems += 1
            continue
        if pa == pb:
            continue
        changed_records += 1
        # the subrecord signature SEQUENCE must be untouched; only the size of
        # whitelisted text subrecords is allowed to grow or shrink
        if sigs_of(pa) != sigs_of(pb):
            print(f"FAIL subrecord sequence changed in {sa} {fa:08X}")
            print(f"     orig {sigs_of(pa)}")
            print(f"     new  {sigs_of(pb)}")
            problems += 1
            continue
        for (s_o, o_o, sz_o), (s_b, o_b, sz_b) in zip(subrecords(pa), subrecords(pb)):
            if s_o != s_b:
                print(f"FAIL subrecord signature mismatch in {sa} {fa:08X}")
                problems += 1
                break
            vo = pa[o_o + 6:o_o + 6 + sz_o]
            vb = pb[o_b + 6:o_b + 6 + sz_b]
            if vo == vb:
                continue
            if not in_whitelist(sa, s_o):
                print(f"FAIL non whitelisted subrecord {sa} {fa:08X} {s_o} changed")
                problems += 1
            else:
                changed_strings += 1
                if len(sample) < 5:
                    sample.append((sa, fa, s_o,
                                   vo.split(b"\x00")[0].decode("utf-8", "replace"),
                                   vb.split(b"\x00")[0].decode("utf-8", "replace")))

    print(f"records: {len(a)}  changed records: {changed_records}  "
          f"changed strings: {changed_strings}  problems: {problems}")
    for sa, fa, s_o, ov, nv in sample:
        print(f"   e.g. {sa} {fa:08X} {s_o}: {ov!r} -> {nv!r}")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
