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
import mmap
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


class open_ba2:
    """with open_ba2(path) as (buf, files): —— mmap 打开（其它脚本也能复用）。

    ★ 为什么要 mmap：DLC 的 ba2 有 2~4 GB（ShatteredSpace - Main01.ba2 = 4.2 GB），
      整体读进内存既慢又危险。列表只需要头部 + 名字区；解包时才碰 payload。
    """

    def __init__(self, path):
        self.path = Path(path)
        self._fh = None
        self._buf = None
        self.files: list[dict] = []
        self.version = self.arc_type = None

    def __enter__(self):
        self._fh = open(self.path, "rb")
        self._buf = mmap.mmap(self._fh.fileno(), 0, access=mmap.ACCESS_READ)
        self.version, self.arc_type, self.files = parse(self._buf)
        return self

    def __exit__(self, *exc):
        if self._buf is not None:
            self._buf.close()
        if self._fh is not None:
            self._fh.close()
        return False

    def find(self, name: str) -> dict | None:
        low = name.lower()
        for f in self.files:
            if f["name"].lower() == low:
                return f
        return None

    def read(self, entry: dict) -> bytes:
        data = bytes(self._buf[entry["offset"]:entry["offset"] + (entry["packed"] or entry["unpacked"])])
        if entry["packed"] and entry["packed"] != entry["unpacked"]:
            import zlib
            data = zlib.decompress(data)
        return data

    def extract(self, entry: dict, dest_dir) -> Path:
        dest = Path(dest_dir) / entry["name"]
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(self.read(entry))
        return dest


def extract_entry(archive: "open_ba2", name: str, dest) -> int | None:
    """按路径名解出一个文件（例：strings/shatteredspace_en.strings）。返回字节数，找不到给 None。"""
    entry = archive.find(name)
    if entry is None:
        return None
    data = archive.read(entry)
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(data)
    return len(data)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("archive")
    ap.add_argument("--grep", default=None)
    ap.add_argument("--extract", default=None)
    a = ap.parse_args()

    p = Path(a.archive)
    with open_ba2(p) as arc:
        total = sum(f["unpacked"] for f in arc.files)
        print(f"{p.name}: BTDX v{arc.version} {arc.arc_type} files={len(arc.files)} unpacked={total}")
        shown = 0
        for f in arc.files:
            if a.grep and a.grep.lower() not in f["name"].lower():
                continue
            print(f"  {f['unpacked']:>10}  {f['name']}")
            shown += 1
            if a.extract:
                arc.extract(f, a.extract)
    print(f"shown: {shown}")
    print("extensions:", dict(Counter(Path(f['name']).suffix.lower() for f in arc.files).most_common()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
