#!/usr/bin/env python3
"""trtool.py - extract / inject player visible strings in Starfield plugins.

This is a pure python alternative to an xEdit round trip: the xEdit headless
run has to build the whole 3.8M record reference cache of Starfield.esm first,
which is far too slow to be used as an interactive step.

Subcommands
-----------
  scan <plugin>
      print every (record signature, subrecord signature) pair that looks like
      text, with counts and samples                    (see str_scan.py)
  extract <plugin> -o out.tsv
      dump every translatable string as
          recsig  fid  subsig  occ  kind  text
      "occ" is the 0 based occurrence of that subrecord inside the record.
  apply <plugin> --map map.tsv -o patched.esm
      rewrite the plugin, replacing the strings found by --map
          recsig  fid  subsig  occ  newtext
  dump <plugin> <SIG> [fid] [n]
      dump raw subrecords of matching records (debugging)

Escaping in TSV: backslash, tab, cr, lf are escaped as \\ \\t \\r \\n so the file
stays one record per line.
"""
from __future__ import annotations

import argparse
import collections
import struct
import sys
import zlib
from pathlib import Path

REC_HDR = 24
GRP_HDR = 24
FLAG_COMPRESSED = 0x00040000

PRINTABLE = set(range(0x20, 0x7F)) | {0x09, 0x0A, 0x0D}

# ---------------------------------------------------------------------------
# Which (record signature, subrecord signature) pairs carry text a player sees.
# Established by tools/re/str_scan.py over the five Dark Universe plugins; every
# entry was checked against a real record dump (see tr/out/scan_*.txt).
# FULL is the display name everywhere, so it is allowed for every record type.
# ---------------------------------------------------------------------------
WHITELIST: dict[str, set[str]] = {
    "*": {"FULL"},
    # NOTE: BOOK ENAM was dropped on purpose. In du_overtime it holds readable
    # text ("[Data Slate #A-471 | Secure Playback]") but in du_outlaws_01 it
    # holds 8 hex digit ids, i.e. translating it would rewrite a real
    # identifier. Flagged as "do not touch" rather than risking data loss.
    "BOOK": {"DESC"},
    # PERK: DESC is the perk description; EPF2 is the "Button Label" of an
    # "Add Activate Choice" perk entry point (the text shown in the activation
    # menu). Both are plain inline strings in non-localized plugins.
    # (Added for Simple Immersive Looting: buttons "Strip" / "Transfer".)
    "PERK": {"DESC", "EPF2"},
    "MESG": {"DESC", "ITXT"},
    "COBJ": {"DESC"},
    "ARMO": {"DESC"},
    "QUST": {"CNAM", "NAM1", "NAM2", "NNAM", "QMDP", "QMDT", "QMSU"},
    "FACT": {"MNAM", "FNAM"},
    "NPC_": set(),
}

# Subrecords that are never text even if the bytes happen to look printable.
# The whitelist above is explicit per (record, subrecord) pair, so this list is
# only a safety net for the wildcard FULL entry.
BLACKLIST_SUBSIGS: set[str] = set()


def in_whitelist(recsig: str, subsig: str) -> bool:
    if subsig in WHITELIST.get(recsig, set()):
        return True
    if subsig in WHITELIST.get("*", set()) and subsig not in BLACKLIST_SUBSIGS:
        return True
    return False


# ---------------------------------------------------------------------------
# text codec
# ---------------------------------------------------------------------------
def decode_text(payload: bytes):
    """Return (text, kind) or None.  kind is 'l' (u32 length prefixed) or 'z'."""
    if len(payload) < 2:
        return None
    if len(payload) >= 5:
        ln = struct.unpack_from("<I", payload, 0)[0]
        if ln == len(payload) - 5 and payload[-1] == 0:
            body = payload[4:-1]
            if body and all(b in PRINTABLE for b in body):
                return body.decode("utf-8", "replace"), "l"
    if payload[-1:] == b"\x00":
        parts = payload[:-1].split(b"\x00")
        if parts and all(parts) and all(all(b in PRINTABLE for b in p) for p in parts):
            return "\x00".join(p.decode("utf-8", "replace") for p in parts), "z"
    return None


def encode_text(text: str, kind: str) -> bytes:
    body = text.encode("utf-8")
    if kind == "l":
        return struct.pack("<I", len(body) + 1) + body + b"\x00"
    return body + b"\x00"


def esc(s: str) -> str:
    s = s.replace("\\", "\\\\")
    s = s.replace("\t", "\\t").replace("\r", "\\r").replace("\n", "\\n")
    return s


def unesc(s: str) -> str:
    out = []
    i = 0
    while i < len(s):
        c = s[i]
        if c == "\\" and i + 1 < len(s):
            n = s[i + 1]
            if n == "\\":
                out.append("\\")
            elif n == "t":
                out.append("\t")
            elif n == "r":
                out.append("\r")
            elif n == "n":
                out.append("\n")
            else:
                out.append(n)
            i += 2
            continue
        out.append(c)
        i += 1
    return "".join(out)


# ---------------------------------------------------------------------------
# plugin walking
# ---------------------------------------------------------------------------
def iter_groups(data: bytes):
    """Yield (group_offset, group_size) for every group, depth first, plus the
    record ranges.  Used only by the injector, which needs byte offsets."""
    hdr_size = struct.unpack_from("<I", data, 4)[0]
    yield from _walk_groups(data, REC_HDR + hdr_size, len(data))


def _walk_groups(data: bytes, start: int, end: int):
    p = start
    while p + 4 <= end:
        if data[p:p + 4] == b"GRUP":
            if p + GRP_HDR > end:
                return
            sz = struct.unpack_from("<I", data, p + 4)[0]
            if sz < GRP_HDR:
                return
            child_start = p + GRP_HDR
            child_end = min(p + sz, end)
            yield ("grp", p, sz)
            yield from _walk_groups(data, child_start, child_end)
            p += sz
            continue
        if p + REC_HDR > end:
            return
        ds = struct.unpack_from("<I", data, p + 4)[0]
        yield ("rec", p, ds)
        p += REC_HDR + ds


def subrecords(payload: bytes):
    """Yield (subsig, offset_in_payload, size) for each subrecord."""
    o = 0
    n = len(payload)
    while o + 6 <= n:
        subsig = payload[o:o + 4].decode("latin1")
        size = struct.unpack_from("<H", payload, o + 4)[0]
        if o + 6 + size > n:
            return
        yield subsig, o, size
        o += 6 + size


def load_records(data: bytes):
    """Yield (rec_offset, recsig, fid, flags, raw_payload) for every record."""
    for kind, off, ds in iter_groups(data):
        if kind != "rec":
            continue
        sig = data[off:off + 4].decode("latin1")
        flags = struct.unpack_from("<I", data, off + 8)[0]
        fid = struct.unpack_from("<I", data, off + 12)[0]
        payload = data[off + REC_HDR:off + REC_HDR + ds]
        if flags & FLAG_COMPRESSED and payload:
            try:
                payload = zlib.decompress(payload[4:])
            except Exception:
                payload = b""
        yield off, sig, fid, flags, payload


# ---------------------------------------------------------------------------
# subcommands
# ---------------------------------------------------------------------------
def cmd_extract(a):
    data = Path(a.plugin).read_bytes()
    rows = []
    for off, recsig, fid, flags, payload in load_records(data):
        occ = collections.Counter()
        for subsig, o, size in subrecords(payload):
            if not in_whitelist(recsig, subsig):
                continue
            t = decode_text(payload[o + 6:o + 6 + size])
            if t is None:
                continue
            text, kind = t
            if not text.strip():
                occ[subsig] += 1
                continue
            rows.append((recsig, fid, subsig, occ[subsig], kind, text))
            occ[subsig] += 1
    with open(a.out, "w", encoding="utf-8", newline="\n") as f:
        f.write("#recsig\tfid\tsubsig\tocc\tkind\ttext\n")
        for r in rows:
            f.write(f"{r[0]}\t{r[1]:08X}\t{r[2]}\t{r[3]}\t{r[4]}\t{esc(r[5])}\n")
    print(f"{Path(a.plugin).name}: extracted {len(rows)} strings -> {a.out}")

    if a.stats:
        chars = sum(len(r[5]) for r in rows)
        uniq = {}
        for r in rows:
            uniq.setdefault(r[5], 0)
            uniq[r[5]] += 1
        print(f"  total chars={chars}  unique={len(uniq)}  unique chars={sum(len(k) for k in uniq)}")
        by = collections.defaultdict(lambda: [0, 0])
        for r in rows:
            e = by[(r[0], r[2])]
            e[0] += 1
            e[1] += len(r[5])
        for k in sorted(by, key=lambda k: -by[k][1]):
            print(f"    {k[0]:<6}{k[1]:<6}{by[k][0]:>7}{by[k][1]:>9}")


def cmd_apply(a):
    src = Path(a.plugin)
    data = bytearray(src.read_bytes())

    repl = collections.defaultdict(dict)  # (recsig,fid,subsig,occ) -> text
    with open(a.map, encoding="utf-8") as f:
        for line in f:
            line = line.rstrip("\n")
            if not line or line.startswith("#"):
                continue
            parts = line.split("\t")
            if len(parts) < 5:
                continue
            recsig, fid, subsig, occ, text = parts[0], int(parts[1], 16), parts[2], int(parts[3]), parts[4]
            repl[(recsig, fid, subsig, occ)] = unesc(text)

    if not a.out:
        print("dry run only; pass -o to write")
        return

    # Rebuilding is easier than in-place editing: re-serialize every record and
    # every group from scratch, keeping everything byte identical except the
    # whitelisted string subrecords.
    out = bytearray()
    # header untouched
    hdr_size = struct.unpack_from("<I", data, 4)[0]
    out += data[:REC_HDR + hdr_size]

    def rebuild(p, end):
        """Rebuild the byte range [p,end) of groups/records, return new bytes."""
        res = bytearray()
        while p < end:
            if data[p:p + 4] == b"GRUP":
                sz = struct.unpack_from("<I", data, p + 4)[0]
                inner = rebuild(p + GRP_HDR, min(p + sz, end))
                res += b"GRUP"
                res += struct.pack("<I", GRP_HDR + len(inner))
                res += data[p + 8:p + GRP_HDR]
                res += inner
                p += sz
                continue
            ds = struct.unpack_from("<I", data, p + 4)[0]
            flags = struct.unpack_from("<I", data, p + 8)[0]
            payload = data[p + REC_HDR:p + REC_HDR + ds]
            if flags & FLAG_COMPRESSED and payload:
                raw = zlib.decompress(payload[4:])
            else:
                raw = payload
            fid = struct.unpack_from("<I", data, p + 12)[0]
            recsig = data[p:p + 4].decode("latin1")
            newraw = patch_payload(recsig, fid, raw)
            hdr = bytearray(data[p:p + REC_HDR])
            if not (flags & FLAG_COMPRESSED):
                struct.pack_into("<I", hdr, 4, len(newraw))
                res += bytes(hdr) + newraw
            else:
                comp = zlib.compress(newraw, 9)
                body = struct.pack("<I", len(newraw)) + comp
                struct.pack_into("<I", hdr, 4, len(body))
                res += bytes(hdr) + body
            p += REC_HDR + ds
        return bytes(res)

    def patch_payload(recsig, fid, raw):
        occ = collections.Counter()
        chunks = []
        last = 0
        for subsig, o, size in subrecords(raw):
            if not in_whitelist(recsig, subsig):
                continue
            t = decode_text(raw[o + 6:o + 6 + size])
            if t is None:
                continue
            text, kind = t
            key = (recsig, fid, subsig, occ[subsig])
            occ[subsig] += 1
            if not text.strip():
                continue
            if key in repl:
                new = encode_text(repl[key], kind)
                if len(new) > 0xFFFF:
                    raise ValueError(f"subrecord too large: {recsig} {fid:08X} "
                                     f"{subsig} {len(new)} bytes")
                # copy everything up to the subrecord header, then rebuild the
                # header so the 2 byte size follows the new payload length
                chunks.append(raw[last:o])
                chunks.append(raw[o:o + 4])
                chunks.append(struct.pack("<H", len(new)))
                chunks.append(new)
                last = o + 6 + size
                nonlocal_applied.append(key)
        chunks.append(raw[last:])
        return b"".join(chunks)

    nonlocal_applied: list = []
    out += rebuild(REC_HDR + struct.unpack_from("<I", data, 4)[0], len(data))

    missing = set(repl) - set(nonlocal_applied)
    Path(a.out).write_bytes(bytes(out))
    print(f"{src.name}: replaced {len(nonlocal_applied)} strings -> {a.out}")
    print(f"  map entries={len(repl)} not applied={len(missing)}")
    if missing and a.verbose:
        for m in list(missing)[:20]:
            print("   MISS", m)


def cmd_scan(a):
    import importlib.util
    spec = importlib.util.spec_from_file_location("str_scan", Path(__file__).with_name("str_scan.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    sys.argv = ["str_scan", a.plugin, "--sample", str(a.sample)]
    return mod.main()


def cmd_dump(a):
    from dump_one_record import iter_records
    data = Path(a.plugin).read_bytes()
    n = 0
    for rs, fid, pl in iter_records(data):
        if rs != a.sig:
            continue
        if a.fid is not None and fid != a.fid:
            continue
        print(f"=== {rs} {fid:08X} len={len(pl)}")
        for subsig, o, size in subrecords(pl):
            v = pl[o + 6:o + 6 + size]
            t = "".join(chr(c) if 32 <= c < 127 else "." for c in v[:70])
            print(f"   {subsig} sz={size:<5} {t}")
        n += 1
        if n >= a.limit:
            break


def main() -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("extract")
    p.add_argument("plugin")
    p.add_argument("-o", "--out", required=True)
    p.add_argument("--stats", action="store_true")
    p.set_defaults(func=cmd_extract)

    p = sub.add_parser("apply")
    p.add_argument("plugin")
    p.add_argument("--map", required=True)
    p.add_argument("-o", "--out")
    p.add_argument("--verbose", action="store_true")
    p.set_defaults(func=cmd_apply)

    p = sub.add_parser("scan")
    p.add_argument("plugin")
    p.add_argument("--sample", type=int, default=2)
    p.set_defaults(func=cmd_scan)

    p = sub.add_parser("dump")
    p.add_argument("plugin")
    p.add_argument("sig")
    p.add_argument("fid", nargs="?", type=lambda s: int(s, 16))
    p.add_argument("limit", nargs="?", type=int, default=1)
    p.set_defaults(func=cmd_dump)

    a = ap.parse_args()
    return a.func(a) or 0


if __name__ == "__main__":
    sys.exit(main())
