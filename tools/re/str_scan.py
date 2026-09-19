#!/usr/bin/env python3
"""str_scan.py - survey every subrecord of a Bethesda plugin and report which
(record signature, subrecord signature) pairs carry human readable text.

Why: we need a precise, evidence based whitelist of "display text" subrecords
before we can translate a plugin without an xEdit round trip (the xEdit headless
run over Starfield.esm takes far too long to be usable as an interactive step).

Heuristics for "this payload is text":
  - zstring:      all bytes printable (0x20..0x7E plus tab/lf/cr), NUL terminated
  - lstring:      u32 length prefix, then that many bytes, then NUL
  - zstring list: payload splits on NUL into one or more printable chunks

Usage:
    python tools/re/str_scan.py <plugin> [--min-chars N] [--sample 2]
"""
from __future__ import annotations

import argparse
import collections
import struct
import sys
import zlib
from pathlib import Path

REC_HDR = 24
FLAG_COMPRESSED = 0x00040000

PRINTABLE = set(range(0x20, 0x7F)) | {0x09, 0x0A, 0x0D}


def iter_records(data: bytes):
    """Yield (recsig, formid, payload) for every record, decompressing as needed."""
    hdr_size = struct.unpack_from("<I", data, 4)[0]
    stack = [(REC_HDR + hdr_size, len(data))]
    while stack:
        a, b = stack.pop()
        p = a
        while p + 4 <= b:
            if data[p:p + 4] == b"GRUP":
                if p + REC_HDR > b:
                    break
                sz = struct.unpack_from("<I", data, p + 4)[0]
                if sz < REC_HDR:
                    break
                stack.append((p + REC_HDR, min(p + sz, b)))
                p += sz
                continue
            if p + REC_HDR > b:
                break
            sig = data[p:p + 4]
            ds = struct.unpack_from("<I", data, p + 4)[0]
            fl = struct.unpack_from("<I", data, p + 8)[0]
            fid = struct.unpack_from("<I", data, p + 12)[0]
            pl = data[p + REC_HDR:p + REC_HDR + ds]
            if fl & FLAG_COMPRESSED and pl:
                try:
                    pl = zlib.decompress(pl[4:])
                except Exception:
                    pl = b""
            yield sig.decode("latin1"), fid, pl
            p += REC_HDR + ds


def iter_subrecords(payload: bytes):
    o = 0
    n = len(payload)
    while o + 6 <= n:
        sig = payload[o:o + 4]
        size = struct.unpack_from("<H", payload, o + 4)[0]
        if o + 6 + size > n:
            return
        yield sig.decode("latin1"), payload[o + 6:o + 6 + size]
        o += 6 + size


def classify(payload: bytes):
    """Return the decoded text if the payload looks like human readable text."""
    if len(payload) < 2:
        return None
    if len(payload) >= 5:
        ln = struct.unpack_from("<I", payload, 0)[0]
        if ln == len(payload) - 5 and payload[-1] == 0:
            body = payload[4:-1]
            if body and all(b in PRINTABLE for b in body):
                return body.decode("utf-8", "replace")
    if payload[-1:] == b"\x00":
        parts = payload[:-1].split(b"\x00")
        if parts and all(parts) and all(all(b in PRINTABLE for b in p) for p in parts):
            return "\x00".join(p.decode("utf-8", "replace") for p in parts)
    return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("plugin")
    ap.add_argument("--sample", type=int, default=2)
    ap.add_argument("--min-chars", type=int, default=1)
    a = ap.parse_args()

    path = Path(a.plugin)
    data = path.read_bytes()

    stats = collections.defaultdict(lambda: [0, 0, []])
    total = 0
    for recsig, fid, payload in iter_records(data):
        total += 1
        for subsig, sub in iter_subrecords(payload):
            t = classify(sub)
            if t is None or len(t) < a.min_chars:
                continue
            key = (recsig, subsig)
            e = stats[key]
            e[0] += 1
            e[1] += len(t)
            if len(e[2]) < a.sample:
                e[2].append(t[:70].replace("\x00", "|").replace("\n", "\\n"))

    print(f"{path.name}: records={total} text-bearing (rec,sig) pairs={len(stats)}")
    print(f"{'rec':<6}{'sub':<6}{'count':>8}{'chars':>10}  samples")
    for (r, s) in sorted(stats, key=lambda k: (k[0], k[1])):
        c, ch, samples = stats[(r, s)]
        print(f"{r:<6}{s:<6}{c:>8}{ch:>10}  " + " || ".join(samples))
    return 0


if __name__ == "__main__":
    sys.exit(main())
