#!/usr/bin/env python3
"""vmad.py - parse the VMAD subrecord of a record inside a plugin.

Why: SAS_Bridge.psc declares 11 properties; if one of them is missing from the
VMAD (or is bound to the wrong form), Papyrus sees None at runtime and our code
silently returns early (that is exactly how GuideMarkers stays at -2).

Usage:
    python tools/re/vmad.py <plugin> 0x806
    python tools/re/vmad.py <plugin> 0x806 --hex
"""
from __future__ import annotations

import argparse
import struct
import sys
from pathlib import Path

TYPES = {
    0x00: "None",
    0x01: "Object",
    0x02: "String",
    0x03: "Int",
    0x04: "Float",
    0x05: "Bool",
    0x06: "[object]",
    0x0B: "Struct",
    0x0C: "ObjectArray",
    0x0D: "StringArray",
    0x0E: "IntArray",
    0x0F: "FloatArray",
    0x10: "BoolArray",
    0x11: "Array(pair)",
}


def rd_u16(b, p):
    return struct.unpack_from("<H", b, p)[0], p + 2


def rd_str(b, p):
    n, p = rd_u16(b, p)
    s = b[p:p + n].split(b"\x00")[0].decode("latin1")
    return s, p + n


def find_vmad(b, low24):
    pos = 24 + struct.unpack_from("<I", b, 4)[0]
    while pos + 24 <= len(b) and b[pos:pos + 4] == b"GRUP":
        gsize = struct.unpack_from("<I", b, pos + 4)[0]
        q, gend = pos + 24, pos + gsize
        while q + 24 <= gend:
            sig = b[q:q + 4]
            if sig == b"GRUP":
                q += struct.unpack_from("<I", b, q + 4)[0]
                continue
            dsize, _f, fid = struct.unpack_from("<III", b, q + 4)
            if (fid & 0xFFFFFF) == low24:
                payload = b[q + 24:q + 24 + dsize]
                p = 0
                while p + 6 <= dsize:
                    s = payload[p:p + 4]
                    sz = struct.unpack_from("<H", payload, p + 4)[0]
                    if s == b"VMAD":
                        return payload[p + 6:p + 6 + sz]
                    p += 6 + sz
            q += 24 + dsize
        pos += gsize
    return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("plugin")
    ap.add_argument("formid", type=lambda s: int(s, 0))
    ap.add_argument("--hex", action="store_true")
    a = ap.parse_args()

    v = find_vmad(Path(a.plugin).read_bytes(), a.formid & 0xFFFFFF)
    if v is None:
        print("VMAD not found")
        return 1
    if a.hex:
        print(v.hex(" "))
    p = 0
    ver, p = rd_u16(v, p)
    objfmt, p = rd_u16(v, p)
    nscript, p = rd_u16(v, p)
    print(f"version={ver} objFormat={objfmt} scripts={nscript}")
    for _ in range(nscript):
        name, p = rd_str(v, p)
        flags = v[p]
        p += 1
        nprop, p = rd_u16(v, p)
        print(f"script '{name}' flags=0x{flags:02X} properties={nprop}")
        for _ in range(nprop):
            pname, p = rd_str(v, p)
            ptype = v[p]
            pstatus = v[p + 1]
            p += 2
            extra = ""
            if ptype in (0x01, 0x06):
                if ptype == 0x01:
                    # alias(-1) + reserved + object index/flags; just show raw 8 bytes
                    raw = v[p:p + 8]
                    p += 8
                    extra = "raw=" + raw.hex(" ")
                else:
                    cnt, p2 = rd_u16(v, p)
                    p = p2
                    extra = f"count={cnt}"
            tn = TYPES.get(ptype, f"0x{ptype:02X}")
            print(f"  {pname:<16} type={tn:<14} status=0x{pstatus:02X} {extra}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
