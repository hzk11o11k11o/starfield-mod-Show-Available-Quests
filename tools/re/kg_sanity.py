#!/usr/bin/env python3
"""kg_sanity.py - verify the generated kinggath _zhhans string pack.

Checks, for all three kinds:
  * the id set is identical to the shipped English pack (so no record loses text)
  * every non-identical entry decodes as UTF-8 Chinese (no mojibake)
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import tr_locpack as L  # noqa: E402

EN = Path("tr/loc/kg/STRINGS")
ZH = Path("tr/build/kg")
NAME = "kinggathcreations_spaceship"

ok = True
for kind in ("strings", "dlstrings", "ilstrings"):
    a = L.parse_raw(EN / f"{NAME}_en.{kind}")
    b = L.parse_raw(ZH / f"{NAME}_zhhans.{kind}")
    same = set(a) == set(b)
    changed = [k for k in a if a.get(k) != b.get(k)]
    bad = []
    for k in changed:
        try:
            t = b[k].decode("utf-8")
        except UnicodeDecodeError:
            bad.append(k)
            continue
        if not any(("\u4e00" <= c <= "\u9fff") or ("\u3000" <= c <= "\u303f")
                   or ("\uff00" <= c <= "\uffef") for c in t):
            bad.append(k)
    print(f"{kind}: ids_equal={same} total={len(a)} changed={len(changed)} "
          f"not_chinese={len(bad)}")
    if not same or bad:
        ok = False
        for k in bad[:10]:
            print(f"   suspicious {k:08X}: {b[k]!r}")
print("RESULT:", "OK" if ok else "PROBLEM")
