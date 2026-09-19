#!/usr/bin/env python3
"""ba2list.py - list / extract files from a Starfield (BTDX v2) BA2 archive.

BSArch 0.9c refuses Starfield archives ("Unknown archive format"), so we parse
the container ourselves.

Layout reverse engineered from real archives:

   0x00  'BTDX'
   0x04  u32 version      (2 = Starfield)
   0x08  'GNRL' | 'DX10'
   0x0C  u32 numFiles
   0x10  u64 namesOffset               (length prefixed file names, then dirs)
   0x18  u32 version2 (=1)
   0x1C  u32 0
   0x20  file record 0
         record = 32 bytes, followed by a 4 byte 0xBAADF00D marker, so the
         stride is 36 bytes:
             +0x00 u32 nameHash
             +0x04 4cc extension   ("nif\0", "il s"? -> 4 chars, NUL padded)
             +0x08 u32 dirHash
             +0x0C u32 flags
             +0x10 u64 offset
             +0x18 u32 packedSize
             +0x1C u32 unpackedSize
         (packedSize == 0 means the payload is stored uncompressed)

Usage:
    python tools/re/ba2list.py <archive.ba2> [--grep STR] [--extract DIR]
"""
from __future__ import annotations

import argparse
import struct
import sys
from collections import Counter
from pathlib import Path


def read_name(buf: bytes, off: int):
    n = struct.unpack_from("<H", buf, off)[0]
    off += 2
    return buf[off:off + n].decode("utf-8", "replace"), off + n


def parse(buf: bytes):
    if buf[0:4] != b"BTDX":
        raise ValueError(f"not a BA2 (sig={buf[0:4]!r})")
    version = struct.unpack_from("<I", buf, 4)[0]
    arc_type = buf[8:12].decode("ascii", "replace")
    num_files = struct.unpack_from("<I", buf, 12)[0]
    names_off = struct.unpack_from("<Q", buf, 16)[0]

    if version != 2:
        raise ValueError(f"only Starfield BTDX v2 is supported (got v{version})")

    rec_start = 0x20
    stride = 36
    files = []
    for i in range(num_files):
        p = rec_start + i * stride
        name_hash = struct.unpack_from("<I", buf, p)[0]
        ext = buf[p + 4:p + 8].rstrip(b"\x00").decode("ascii", "replace")
        dir_hash = struct.unpack_from("<I", buf, p + 8)[0]
        flags = struct.unpack_from("<I", buf, p + 12)[0]
        offset = struct.unpack_from("<Q", buf, p + 16)[0]
        packed = struct.unpack_from("<I", buf, p + 24)[0]
        unpacked = struct.unpack_from("<I", buf, p + 28)[0]
        files.append(dict(hash=name_hash, ext=ext, dir_hash=dir_hash, flags=flags,
                          offset=offset, packed=packed, unpacked=unpacked))

    pos = names_off
    for f in files:
        f["name"], pos = read_name(buf, pos)
    return version, arc_type, files


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("archive")
    ap.add_argument("--grep", default=None)
    ap.add_argument("--extract", default=None)
    a = ap.parse_args()

    p = Path(a.archive)
    buf = p.read_bytes()
    version, arc_type, files = parse(buf)
    total = sum(f["unpacked"] for f in files)
    print(f"{p.name}: BTDX v{version} {arc_type} files={len(files)} unpacked={total}")

    shown = 0
    for f in files:
        if a.grep and a.grep.lower() not in f["name"].lower():
            continue
        print(f"  {f['unpacked']:>10}  {f['name']}")
        shown += 1
        if a.extract:
            data = buf[f["offset"]:f["offset"] + (f["packed"] or f["unpacked"])]
            if f["packed"] and f["packed"] != f["unpacked"]:
                import zlib
                data = zlib.decompress(data)
            dest = Path(a.extract) / f["name"]
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(data)
    print(f"shown: {shown}")
    print("extensions:", dict(Counter(Path(f['name']).suffix.lower() for f in files).most_common()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
