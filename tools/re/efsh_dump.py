#!/usr/bin/env python3
"""efsh_dump.py - dump EffectShader (EFSH) DNAM payloads straight from a plugin file.

Why this exists
---------------
We need to know *which* bytes of the Starfield EFSH DNAM payload actually hold a
colourable value.  xEdit's SF1 definition is a guess ("subrecords checked against
Starfield.esm") and it types the payload as

    float, ByteColors, float x11, SoundRef, Unknown(5)      -> 52 + 40 + 5 bytes

which may not match what the engine reads.  Reading the raw bytes lets us decide
from the data itself: a *colour* slot carries arbitrary 4-byte patterns that vary
per record, while a *float* slot carries sane IEEE-754 values and stays constant
across records that were authored by different people.

Method (no record parser needed)
--------------------------------
Every EFSH payload ends with the same trailing shape, so we pattern-search for it
and then walk backwards a fixed number of bytes to reach the interesting slots:

    idx0  float        +0
    idx1  ByteColors   +4      <- the one xEdit names "Color"
    idx2..idx9 floats  +8 ..+36
    idx10 float        +40
    idx11 float        +44     <- v36 wrongly assumed "Edge Effect - Color"
    idx12 float        +48
    sound ref          +52..+91 (40 bytes)
    unknown            +92..+96 (5 bytes)

The signature we search for is the tail of the *float* fields and it is stable
across the whole vanilla set (idx10=10.0, idx11=255.0, idx12=0.0 for almost every
shader), so each match lands us at +40 and everything else is a simple offset.

Usage
-----
    python tools/re/efsh_dump.py <plugin>                  # summary table
    python tools/re/efsh_dump.py <plugin> --full            # + every slot as hex
    python tools/re/efsh_dump.py <plugin> --edid ReconTargetingFXS
"""

import argparse
import os
import struct
import sys

# idx10=10.0 (0x41200000), idx11=255.0 (0x437F0000), idx12=0.0
SIG = struct.pack('<f', 10.0) + struct.pack('<f', 255.0) + struct.pack('<f', 0.0)
COLOR_OFF = -36           # idx1 sits 36 bytes before idx10
PAYLOAD_END = 4 + 4 * 12  # idx0 .. idx12


def find_edid(buf, pos, back=4096):
    """Best-effort EDID lookup: walk backwards for a printable run near the record."""
    lo = max(0, pos - back)
    window = buf[lo:pos]
    best = ''
    i = 0
    n = len(window)
    while i < n:
        if 32 <= window[i] < 127:
            j = i
            while j < n and 32 <= window[j] < 127 and (j - i) < 64:
                j += 1
            cand = window[i:j].decode('ascii', 'replace')
            if len(cand) >= 4 and any(c.isalpha() for c in cand):
                best = cand
            i = j
        else:
            i += 1
    return best


def fmt_float(b):
    v = struct.unpack('<f', b)[0]
    return '%.3f' % v


def fmt_color(b):
    return '(%d,%d,%d,%d)' % (b[0], b[1], b[2], b[3])


def scan(path, want_edid=None, full=False):
    size = os.path.getsize(path)
    with open(path, 'rb') as f:
        buf = f.read()

    print('file      : %s (%.1f MB)' % (path, size / 1048576.0))
    print('signature : idx10=10.0 idx11=255.0 idx12=0.0')
    print()

    hits = []
    start = 0
    while True:
        p = buf.find(SIG, start)
        if p < 0:
            break
        start = p + 1
        if p + 4 > len(buf):
            continue
        hits.append(p)

    print('signature hits: %d' % len(hits))
    print()

    header = ('#  %-40s %-18s %-18s %-18s %-18s' %
              ('edid(guess)', 'idx1 Color', 'idx2', 'idx11 (+44)', 'idx12 (+48)'))
    rows = []
    for k, p in enumerate(hits):
        edid = find_edid(buf, p)
        if want_edid and want_edid.lower() not in edid.lower():
            continue
        color = buf[p + COLOR_OFF:p + COLOR_OFF + 4]
        if len(color) < 4:
            continue
        rows.append((
            k,
            edid,
            fmt_color(color),
            fmt_float(buf[p - 32:p - 28]),
            fmt_float(buf[p:p + 4]),
            fmt_float(buf[p + 4:p + 8]),
            buf[p + COLOR_OFF:p + COLOR_OFF + 16].hex(' '),
        ))

    print('%-5s %-40s %-18s %-10s %-12s %-12s' %
          ('idx', 'edid(guess)', 'idx1 Color', 'idx2', 'idx11 (+44)', 'idx12 (+48)'))
    print('-' * 100)
    for r in rows:
        print('%-5d %-40s %-18s %-10s %-12s %-12s' %
              (r[0], r[1][:40], r[2], r[3], r[4], r[5]))

    if full:
        print()
        print('--- raw idx0..idx7 (hex) per hit ---')
        for k, p in enumerate(hits):
            edid = find_edid(buf, p)
            if want_edid and want_edid.lower() not in edid.lower():
                continue
            raw = buf[p - 40:p + 4]
            print('%-5d %-40s %s' % (k, edid[:40], raw.hex(' ')))
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('plugin')
    ap.add_argument('--edid', default=None)
    ap.add_argument('--full', action='store_true')
    args = ap.parse_args()
    if not os.path.isfile(args.plugin):
        print('not found: %s' % args.plugin, file=sys.stderr)
        return 2
    scan(args.plugin, args.edid, args.full)
    return 0


if __name__ == '__main__':
    sys.exit(main())
