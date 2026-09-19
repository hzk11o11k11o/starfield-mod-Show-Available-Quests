#!/usr/bin/env python3
"""enc_probe.py - decide whether a plugin's inline strings are UTF-8 or a
single byte codepage (Latin-1 / Windows-1252).

The answer matters a lot: if the engine reads plugin strings as Windows-1252
then writing Chinese (which has no 1252 representation) is pointless, while if
it reads UTF-8 then writing UTF-8 is mandatory.

Prints, for every text subrecord containing bytes >= 0x80, whether those bytes
form a valid UTF-8 sequence.
"""
from __future__ import annotations

import glob
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from trtool import load_records, subrecords  # noqa: E402

TEXT_SUBS = {"FULL", "DESC", "ITXT", "ENAM"}
PRINTABLE = set(range(0x20, 0x7F))


def mostly_ascii(body: bytes) -> bool:
    if not body:
        return False
    ok = sum(1 for b in body if b in PRINTABLE)
    return ok / len(body) >= 0.8


def main() -> int:
    for p in glob.glob(sys.argv[1]):
        data = Path(p).read_bytes()
        utf8_ok = 0
        latin = 0
        samples = []
        for _off, sig, fid, _flags, pl in load_records(data):
            for ss, o, sz in subrecords(pl):
                if ss not in TEXT_SUBS:
                    continue
                v = pl[o + 6:o + 6 + sz]
                if not any(b >= 0x80 for b in v):
                    continue
                body = v.split(b"\x00")[0]
                if not mostly_ascii(body):
                    continue
                try:
                    body.decode("utf-8")
                    utf8_ok += 1
                    if len(samples) < 4:
                        samples.append(("utf8", sig, ss, body[:60]))
                except UnicodeDecodeError:
                    latin += 1
                    if len(samples) < 8:
                        samples.append(("lat1", sig, ss, body[:60]))
        print(f"{Path(p).name}: high-byte text subrecords: valid-utf8={utf8_ok} "
              f"invalid-utf8={latin}")
        for kind, sig, ss, body in samples:
            if kind == "lat1":
                print(f"    {kind} {sig}/{ss}: {body.decode('latin1')!r}")
            else:
                print(f"    {kind} {sig}/{ss}: {body.decode('utf-8')!r}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
