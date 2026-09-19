#!/usr/bin/env python3
"""strings_probe.py - 读取 Starfield 的 .strings/.dlstrings/.ilstrings 本地化文件。

格式（Bethesda）：
    u32 count
    count * (u32 id, u32 offset)     ; offset 相对数据区起点（即 count 表之后）
    data area: NUL 结尾的字符串（dlstrings/ilstrings 前置 u32 长度，含 NUL）

用法：
    python tools/esm/strings_probe.py ref/strings/starfield_en.strings 0x2D33B
    python tools/esm/strings_probe.py ref/strings/starfield_zhhans.strings --batch ids.txt --out names.csv
    python tools/esm/strings_probe.py ref/strings/starfield_en.strings --grep "One Small Step"
"""
from __future__ import annotations

import argparse
import struct
import sys
from pathlib import Path


def load_strings(path: Path) -> dict[int, str]:
    buf = path.read_bytes()
    count, _data_size = struct.unpack_from("<II", buf, 0)
    entries = []
    for i in range(count):
        sid, off = struct.unpack_from("<II", buf, 8 + i * 8)
        entries.append((sid, off))
    data_start = 8 + count * 8
    is_len_prefixed = path.suffix.lower() in (".dlstrings", ".ilstrings")
    out = {}
    for sid, off in entries:
        p = data_start + off
        if is_len_prefixed:
            n = struct.unpack_from("<I", buf, p)[0]
            raw = buf[p + 4:p + 4 + max(0, n - 1)]
        else:
            end = buf.index(b"\x00", p)
            raw = buf[p:end]
        out[sid] = raw.decode("utf-8", "replace")
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("file")
    ap.add_argument("ids", nargs="*", help="string ids, hex (0x...) or decimal")
    ap.add_argument("--grep", default=None)
    ap.add_argument("--limit", type=int, default=40)
    a = ap.parse_args()

    table = load_strings(Path(a.file))
    print(f"{a.file}: {len(table)} strings", file=sys.stderr)

    if a.grep:
        n = 0
        for sid, s in sorted(table.items()):
            if a.grep.lower() in s.lower():
                print(f"0x{sid:08X}  {s}")
                n += 1
                if n >= a.limit:
                    break
        return 0

    for tok in a.ids:
        sid = int(tok, 0)
        print(f"0x{sid:08X}  {table.get(sid, '<not found>')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
