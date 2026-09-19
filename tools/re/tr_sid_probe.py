#!/usr/bin/env python3
"""临时工具：按字符串 ID 在官方 en/zh strings 里取值。

用法: python tools/re/_sid_probe.py 0x2D8D4
"""
import struct
import sys
from pathlib import Path

LOC = Path("tr/loc/strings")


def parse(path):
    buf = Path(path).read_bytes()
    count, _ = struct.unpack_from("<II", buf, 0)
    base = 8 + count * 8
    out = {}
    for i in range(count):
        sid, off = struct.unpack_from("<II", buf, 8 + i * 8)
        p = base + off
        if str(path).endswith((".dlstrings", ".ilstrings")):
            ln = struct.unpack_from("<I", buf, p)[0]
            raw = buf[p + 4:p + 4 + ln]
        else:
            raw = buf[p:buf.index(b"\x00", p)]
        out[sid] = raw.decode("utf-8", "replace")
    return out


want = [int(a, 0) for a in sys.argv[1:]]
for kind in ("strings", "dlstrings", "ilstrings"):
    en = parse(LOC / f"starfield_en.{kind}")
    zh = parse(LOC / f"starfield_zhhans.{kind}")
    for sid in want:
        if sid in en:
            print(f"{kind} {sid:08X}: {en[sid]!r} => {zh.get(sid)!r}")
