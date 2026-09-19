#!/usr/bin/env python3
"""tr_locpack.py - work with Starfield localized plugins' <plugin>_<lang>.{strings,dlstrings,ilstrings}.

For plugins with the Localized flag (0x80 in the TES4 header) the player visible
text lives *outside* the .esm, in three parallel files.  This tool batches the
common operations needed to translate them.

Subcommands
-----------
  dump  <dir> <basename> --loc en -o out.tsv
        Parse <dir>/<basename>_<loc>.{strings,dlstrings,ilstrings} and write a
        single TSV:  kind <TAB> id(hex) <TAB> text   (text is \\n/\\t/\\\\ escaped)

  stats <tsv>
        Report how many strings are "real" vs placeholder/format-only.

  apply <dir> <basename> --loc zhhans --map map.tsv -o outdir
        map.tsv is  kind <TAB> id(hex) <TAB> translated   (only translated rows
        needed).  Writes a complete new set of the three files into outdir,
        copying any id that is absent from the map verbatim from <loc>'s files
        (or from --fallback, default: the same dir/loc).

Escaping
--------
Text round trips through TSV with \\n \\r \\t \\\\ so that a multi line string
occupies exactly one row.
"""
from __future__ import annotations

import argparse
import io
import struct
import sys
from pathlib import Path

KINDS = ("strings", "dlstrings", "ilstrings")


def parse_raw(path: Path) -> dict:
    """{id: raw bytes} - the exact payload, NUL padding stripped."""
    buf = path.read_bytes()
    count, _data_size = struct.unpack_from("<II", buf, 0)
    base = 8 + count * 8
    suffix = path.suffix.lower()
    out = {}
    for i in range(count):
        sid, off = struct.unpack_from("<II", buf, 8 + i * 8)
        p = base + off
        if suffix in (".dlstrings", ".ilstrings"):
            ln = struct.unpack_from("<I", buf, p)[0]
            raw = buf[p + 4:p + 4 + ln]
        else:
            end = buf.index(b"\x00", p)
            raw = buf[p:end]
        out[sid] = raw.rstrip(b"\x00")
    return out


def parse(path: Path) -> dict:
    return {k: v.decode("utf-8", "replace") for k, v in parse_raw(path).items()}


def build_raw(path: Path, data: dict) -> None:
    """Write a .strings/.dlstrings/.ilstrings file from {id: raw bytes}."""
    suffix = path.suffix.lower()
    ids = sorted(data)
    body = bytearray()
    index = bytearray()
    off = 0
    for sid in ids:
        raw = data[sid]
        if suffix in (".dlstrings", ".ilstrings"):
            blob = struct.pack("<I", len(raw) + 1) + raw + b"\x00"
        else:
            blob = raw + b"\x00"
        index += struct.pack("<II", sid, off)
        body += blob
        off += len(blob)
    head = struct.pack("<II", len(ids), len(body))
    path.write_bytes(head + bytes(index) + bytes(body))


def build(path: Path, data: dict) -> None:
    """Write from {id: text}. Only used for brand new files."""
    build_raw(path, {k: v.encode("utf-8") for k, v in data.items()})


def esc(s: str) -> str:
    return s.replace("\\", "\\\\").replace("\t", "\\t").replace("\r", "\\r").replace("\n", "\\n")


def unesc(s: str) -> str:
    out = []
    i = 0
    while i < len(s):
        c = s[i]
        if c == "\\" and i + 1 < len(s):
            n = s[i + 1]
            if n == "n":
                out.append("\n")
            elif n == "r":
                out.append("\r")
            elif n == "t":
                out.append("\t")
            elif n == "\\":
                out.append("\\")
            else:
                out.append(c)
                out.append(n)
            i += 2
        else:
            out.append(c)
            i += 1
    return "".join(out)


def files_for(base: Path, name: str, loc: str):
    for kind in KINDS:
        yield kind, base / f"{name}_{loc}.{kind}"


def cmd_dump(a):
    base = Path(a.dir)
    rows = []
    for kind, p in files_for(base, a.basename, a.loc):
        if not p.exists():
            continue
        d = parse(p)
        for sid in sorted(d):
            rows.append((kind, sid, d[sid]))
    with io.open(a.out, "w", encoding="utf-8", newline="\n") as f:
        f.write("#kind\tid\ttext\n")
        for kind, sid, text in rows:
            f.write(f"{kind}\t{sid:08X}\t{esc(text)}\n")
    print(f"dumped {len(rows)} strings -> {a.out}")
    for kind in KINDS:
        n = sum(1 for r in rows if r[0] == kind)
        print(f"  {kind:10s} {n}")
    return 0


def cmd_stats(a):
    kinds = {}
    trivial = 0
    total = 0
    chars = 0
    for line in io.open(a.tsv, encoding="utf-8"):
        if not line.strip() or line.startswith("#"):
            continue
        kind, sid, text = line.rstrip("\n").split("\t")
        t = unesc(text)
        total += 1
        chars += len(t)
        kinds[kind] = kinds.get(kind, 0) + 1
        s = t.replace("\\n", "").replace("\\t", "")
        if s.strip() == "" or all(not ch.isalpha() for ch in s):
            trivial += 1
    print(f"total={total} chars={chars} real={total - trivial} trivial={trivial}")
    for k, v in sorted(kinds.items()):
        print(f"  {k:10s} {v}")
    return 0


def cmd_apply(a):
    base = Path(a.dir)
    outdir = Path(a.out)
    outdir.mkdir(parents=True, exist_ok=True)
    tmap = {}
    for line in io.open(a.map, encoding="utf-8"):
        if not line.strip() or line.startswith("#"):
            continue
        parts = line.rstrip("\n").split("\t")
        kind, sid, text = parts[0], parts[1], "\t".join(parts[2:])
        tmap[(kind, int(sid, 16))] = unesc(text)
    applied = {}
    missing = {}
    for kind in KINDS:
        p = base / f"{a.basename}_{a.loc}.{kind}"
        fallback = base / f"{a.basename}_{a.fallback}.{kind}"
        src = p if p.exists() else fallback
        if not src.exists():
            continue
        d = dict(parse_raw(src))
        for sid in list(d):
            if (kind, sid) in tmap:
                d[sid] = tmap[(kind, sid)].encode("utf-8")
                applied[kind] = applied.get(kind, 0) + 1
        for (k, sid) in tmap:
            if k == kind and sid not in d:
                missing[kind] = missing.get(kind, 0) + 1
        outp = outdir / f"{a.basename}_{a.loc}.{kind}"
        build_raw(outp, d)
        print(f"wrote {outp} ({len(d)} strings)")
    print(f"applied={sum(applied.values())} {applied}")
    if missing:
        print(f"!! map ids not present in file: {missing}")
    return 0


def cmd_toextract(a):
    """dump format -> trtool/tr_pipeline "extract" format so the shared
    dictionary / official-seed tooling can be reused verbatim.

        recsig = kind.upper()[:4]   (STRI / DLST / ILST)
        recsig column keeps the kind, so (recsig, fid) is still a unique key.
    """
    TAG = {"strings": "STRI", "dlstrings": "DLST", "ilstrings": "ILST"}
    n = 0
    with io.open(a.tsv, encoding="utf-8") as fin, \
            io.open(a.out, "w", encoding="utf-8", newline="\n") as fout:
        fout.write("#recsig\tfid\tsubsig\tocc\tkind\ttext\n")
        for line in fin:
            if not line.strip() or line.startswith("#"):
                continue
            kind, sid, text = line.rstrip("\n").split("\t")
            fout.write(f"{TAG[kind]}\t{int(sid, 16):08X}\tTEXT\t0\tz\t{text}\n")
            n += 1
    print(f"toextract: {n} rows -> {a.out}")
    return 0


def cmd_tomap(a):
    """tr_pipeline "map" output -> tr_locpack "apply" map."""
    TAG = {"STRI": "strings", "DLST": "dlstrings", "ILST": "ilstrings"}
    n = 0
    with io.open(a.tsv, encoding="utf-8") as fin, \
            io.open(a.out, "w", encoding="utf-8", newline="\n") as fout:
        fout.write("#kind\tid\ttext\n")
        for line in fin:
            if not line.strip() or line.startswith("#"):
                continue
            p = line.rstrip("\n").split("\t")
            recsig, fid, _sub, _occ, text = p[0], p[1], p[2], p[3], p[4]
            fout.write(f"{TAG.get(recsig, recsig.lower())}\t{fid}\t{text}\n")
            n += 1
    print(f"tomap: {n} rows -> {a.out}")
    return 0


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("dump")
    p.add_argument("dir")
    p.add_argument("basename")
    p.add_argument("--loc", required=True)
    p.add_argument("-o", "--out", required=True)
    p.set_defaults(func=cmd_dump)

    p = sub.add_parser("stats")
    p.add_argument("tsv")
    p.set_defaults(func=cmd_stats)

    p = sub.add_parser("toextract")
    p.add_argument("tsv")
    p.add_argument("-o", "--out", required=True)
    p.set_defaults(func=cmd_toextract)

    p = sub.add_parser("tomap")
    p.add_argument("tsv")
    p.add_argument("-o", "--out", required=True)
    p.set_defaults(func=cmd_tomap)

    p = sub.add_parser("apply")
    p.add_argument("dir")
    p.add_argument("basename")
    p.add_argument("--loc", required=True)
    p.add_argument("--fallback", default="en")
    p.add_argument("--map", required=True)
    p.add_argument("-o", "--out", required=True)
    p.set_defaults(func=cmd_apply)

    a = ap.parse_args()
    return a.func(a) or 0


if __name__ == "__main__":
    sys.exit(main())
