#!/usr/bin/env python3
"""esmrec.py - minimal raw Bethesda plugin reader: list top level records and
dump one record's subrecords (signature + payload hex/ascii) by FormID.

Why: build_sas.pas produces a tiny .esm; when something does not work in game
(e.g. the quest's VMAD script never runs) the fastest way to check is to look at
the raw bytes instead of opening xEdit.

Usage:
    python tools/re/esmrec.py <plugin>                     # record list
    python tools/re/esmrec.py <plugin> --formid 0x04000806  # dump that record
    python tools/re/esmrec.py <plugin> --edid-alike VMAD    # find subrecords with that sig
"""
from __future__ import annotations

import argparse
import struct
import sys
from pathlib import Path


def parse_header(buf: bytes):
    """Returns (records, masters). records = list of dict(sig, size, flags, formid,
    offset_of_payload). Only top level GRUP walking; entries inside GRUPs are
    included (nested GRUPs are walked too)."""
    if len(buf) < 24:
        raise ValueError("too small to be a plugin")
    sig = buf[0:4]
    if sig != b"TES4":
        raise ValueError(f"not a plugin (first sig = {sig!r})")
    head_size = struct.unpack_from("<I", buf, 4)[0]

    masters = []
    pos = 24
    end = 24 + head_size
    while pos + 6 <= end:
        rsig = buf[pos:pos + 4]
        rsize = struct.unpack_from("<H", buf, pos + 4)[0]
        payload = buf[pos + 6:pos + 6 + rsize]
        if rsig == b"MAST":
            masters.append(payload.split(b"\x00")[0].decode("latin1"))
        pos += 6 + rsize

    records = []
    pos = end
    while pos + 24 <= len(buf):
        if buf[pos:pos + 4] != b"GRUP":
            break
        gsize = struct.unpack_from("<I", buf, pos + 4)[0]
        glabel = buf[pos + 8:pos + 12]
        gtype = struct.unpack_from("<i", buf, pos + 12)[0]
        if gsize < 24:
            break
        inner = pos + 24
        gend = pos + gsize
        # only walk leaf groups (type 0); nested groups are handled by recursing
        p = inner
        while p + 24 <= gend:
            sig4 = buf[p:p + 4]
            if sig4 == b"GRUP":
                sub = struct.unpack_from("<I", buf, p + 4)[0]
                if sub < 24:
                    break
                p += sub
                continue
            rsize = struct.unpack_from("<I", buf, p + 4)[0]
            flags = struct.unpack_from("<I", buf, p + 8)[0]
            formid = struct.unpack_from("<I", buf, p + 12)[0]
            records.append({
                "sig": sig4.decode("latin1"),
                "size": rsize,
                "flags": flags,
                "formid": formid,
                "payload": p + 24,
                "group_of": glabel.decode("latin1", "replace"),
            })
            p += 24 + rsize
        pos += gsize
    return records, masters


def dump_record(buf: bytes, rec: dict, out):
    p = rec["payload"]
    end = p + rec["size"]
    out.write(f'--- {rec["sig"]} {rec["formid"]:08X}  size={rec["size"]}  '
              f'flags=0x{rec["flags"]:08X}  group={rec["group_of"]}\n')
    while p + 6 <= end:
        ssig = buf[p:p + 4]
        ssize = struct.unpack_from("<H", buf, p + 4)[0]
        if p + 6 + ssize > end:
            out.write(f"  {ssig!r} truncated (size={ssize})\n")
            break
        payload = buf[p + 6:p + 6 + ssize]
        txt = "".join(chr(b) if 32 <= b < 127 else "." for b in payload)
        out.write(f"  {ssig.decode('latin1')} len={ssize:<5} hex={payload[:48].hex(' ')}"
                  f"{' ...' if ssize > 48 else ''}\n")
        if ssize <= 96:
            out.write(f"      ascii: {txt}\n")
        p += 6 + ssize
    if p != end:
        out.write(f"  (stopped at +0x{p - rec['payload']:X} of {rec['size']})\n")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("plugin")
    ap.add_argument("--formid", type=lambda s: int(s, 0), default=None)
    ap.add_argument("--grep", default=None)
    ap.add_argument("--no-list", action="store_true", help="do not print the record list (huge for Starfield.esm)")
    a = ap.parse_args()

    path = Path(a.plugin)
    buf = path.read_bytes()
    records, masters = parse_header(buf)

    print(f"file    : {path}  ({len(buf)} B)")
    print(f"masters : {masters}")
    print(f"records : {len(records)}")
    for r in ([] if a.no_list else records):
        edid = ""
        p = r["payload"]
        end = p + r["size"]
        while p + 6 <= end:
            ssig = buf[p:p + 4]
            ssize = struct.unpack_from("<H", buf, p + 4)[0]
            if ssig == b"EDID":
                edid = buf[p + 6:p + 6 + ssize].split(b"\x00")[0].decode("latin1")
                break
            p += 6 + ssize
        print(f'  {r["sig"]}  {r["formid"]:08X}  size={r["size"]:<5}  EDID={edid}')

    if a.formid is not None:
        for r in records:
            if r["formid"] == a.formid:
                print()
                dump_record(buf, r, sys.stdout)
    return 0


if __name__ == "__main__":
    sys.exit(main())
