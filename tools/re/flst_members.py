#!/usr/bin/env python3
"""flst_members.py - dump (or query) the members of a FLST by its low-24 FormID.

Why: SAS_DoorBases must contain every DOOR base of the master -- if a door the
player is standing next to is missing from it, the Papyrus side can never find
it.  This reads the raw LNAM list so membership can be checked without xEdit.

Usage:
    python tools/re/flst_members.py <plugin> 0x80B                # list all
    python tools/re/flst_members.py <plugin> 0x80B --has 0x13E58C # membership
"""
from __future__ import annotations

import argparse
import struct
import sys
from pathlib import Path


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("plugin")
    ap.add_argument("formid", type=lambda s: int(s, 0))
    ap.add_argument("--has", type=lambda s: int(s, 0), default=None)
    ap.add_argument("--limit", type=int, default=40)
    a = ap.parse_args()

    b = Path(a.plugin).read_bytes()
    pos = 24 + struct.unpack_from("<I", b, 4)[0]
    ids: list[int] = []
    while pos + 24 <= len(b) and b[pos:pos + 4] == b"GRUP":
        gsize = struct.unpack_from("<I", b, pos + 4)[0]
        q, gend = pos + 24, pos + gsize
        while q + 24 <= gend:
            sig = b[q:q + 4]
            if sig == b"GRUP":
                q += struct.unpack_from("<I", b, q + 4)[0]
                continue
            dsize, _f, fid = struct.unpack_from("<III", b, q + 4)
            if (fid & 0xFFFFFF) == (a.formid & 0xFFFFFF):
                payload = b[q + 24:q + 24 + dsize]
                p = 0
                while p + 6 <= dsize:
                    s = payload[p:p + 4]
                    sz = struct.unpack_from("<H", payload, p + 4)[0]
                    if s == b"LNAM" and sz >= 4:
                        for k in range(0, sz - 3, 4):
                            ids.append(struct.unpack_from("<I", payload, p + 6 + k)[0])
                    p += 6 + sz
            q += 24 + dsize
        pos += gsize

    print(f"members = {len(ids)}")
    if a.has is not None:
        print(f"has 0x{a.has:06X}: {a.has in ids}")
    print("first:", [f"0x{x:06X}" for x in ids[:a.limit]])
    if ids:
        print(f"low24 range: 0x{min(x & 0xFFFFFF for x in ids):06X} .. "
              f"0x{max(x & 0xFFFFFF for x in ids):06X}")
        print(f"master idx set: {sorted(set(x >> 24 for x in ids))}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
