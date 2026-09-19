#!/usr/bin/env python3
"""ststrings.py - parse Bethesda .strings / .dlstrings / .ilstrings files.

Format:
    u32 count
    u32 dataSize
    count * (u32 id, u32 offset)      offset is relative to the start of data
    data ...
        .strings   : NUL terminated utf-8 text
        .dlstrings : u32 byte length, then text, then NUL
        .ilstrings : u32 byte length, then text, then NUL

Subcommands
-----------
  dump   <file> [--limit N] [--grep STR]     print "id<TAB>text"
  dict   <en.strings> <zh.strings> ...       build an EN -> ZH dictionary
         -o dict.tsv
       Accepts any number of "lang file" pairs: en then zh of the same kind.
       All three kinds should be passed so that every id resolves.
"""
from __future__ import annotations

import argparse
import struct
import sys
from pathlib import Path


def parse(path: Path):
    buf = path.read_bytes()
    count, data_size = struct.unpack_from("<II", buf, 0)
    base = 8 + count * 8
    out = {}
    suffix = path.suffix.lower()
    for i in range(count):
        sid, off = struct.unpack_from("<II", buf, 8 + i * 8)
        p = base + off
        if suffix in (".dlstrings", ".ilstrings"):
            ln = struct.unpack_from("<I", buf, p)[0]
            raw = buf[p + 4:p + 4 + ln]
        else:
            end = buf.index(b"\x00", p)
            raw = buf[p:end]
        raw = raw.rstrip(b"\x00")
        out[sid] = raw.decode("utf-8", "replace")
    return out


def cmd_dump(a):
    d = parse(Path(a.file))
    n = 0
    for sid in sorted(d):
        if a.grep and a.grep.lower() not in d[sid].lower():
            continue
        print(f"{sid:08X}\t{d[sid]}")
        n += 1
        if a.limit and n >= a.limit:
            break
    print(f"# total ids={len(d)}", file=sys.stderr)


def cmd_dict(a):
    files = a.files
    if len(files) % 2:
        print("need pairs of en/zh files", file=sys.stderr)
        return 2
    en, zh = {}, {}
    for i in range(0, len(files), 2):
        en.update(parse(Path(files[i])))
        zh.update(parse(Path(files[i + 1])))
    rows = []
    for sid, e in en.items():
        z = zh.get(sid)
        if z and z != e:
            rows.append((e, z))
    with open(a.out, "w", encoding="utf-8", newline="\n") as f:
        f.write("#en\tzh\n")
        for e, z in rows:
            f.write(e.replace("\t", " ").replace("\n", "\\n") + "\t" +
                    z.replace("\t", " ").replace("\n", "\\n") + "\n")
    print(f"built dictionary: {len(rows)} pairs -> {a.out}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("dump")
    p.add_argument("file")
    p.add_argument("--limit", type=int, default=0)
    p.add_argument("--grep", default=None)
    p.set_defaults(func=cmd_dump)

    p = sub.add_parser("dict")
    p.add_argument("files", nargs="+")
    p.add_argument("-o", "--out", required=True)
    p.set_defaults(func=cmd_dict)

    a = ap.parse_args()
    return a.func(a) or 0


if __name__ == "__main__":
    sys.exit(main())
