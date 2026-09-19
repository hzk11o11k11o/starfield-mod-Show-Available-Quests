#!/usr/bin/env python3
"""esmflst.py - dump 某个 FLST 记录里所有成员的「master 归属」分布。

Why: 构建出来的插件如果意外依赖了别的 master（比如 BlueprintShips-Starfield.esm），
在游戏里可能直接加载失败。最容易被怀疑的就是「离线打包进去的表单列表」——
这个脚本直接读插件字节，把每个 LNAM（FormID）的高 8 位（master 索引）统计出来，
再对照 TES4 头里的 MAST 列表，就能确认「列表里到底是谁家的记录」。

用法:
    python tools/re/esmflst.py <plugin.esm> 0x0800080B
"""
from __future__ import annotations

import struct
import sys
from collections import Counter
from pathlib import Path


def read_masters(b: bytes) -> list[str]:
    size = struct.unpack_from("<I", b, 4)[0]
    pos, end = 24, 24 + size
    out: list[str] = []
    while pos + 6 <= end:
        sig = b[pos:pos + 4]
        sz = struct.unpack_from("<H", b, pos + 4)[0]
        if sig == b"MAST":
            out.append(b[pos + 6:pos + 6 + sz].split(b"\x00")[0].decode("latin1"))
        pos += 6 + sz
    return out


def main() -> int:
    if len(sys.argv) < 3:
        print(__doc__)
        return 1
    path = Path(sys.argv[1])
    want = int(sys.argv[2], 0)
    b = path.read_bytes()
    masters = read_masters(b)
    print(f"file    : {path}")
    print(f"masters : {masters}")

    pos = 24 + struct.unpack_from("<I", b, 4)[0]
    rec = None
    while pos + 24 <= len(b) and b[pos:pos + 4] == b"GRUP":
        gsize = struct.unpack_from("<I", b, pos + 4)[0]
        q, gend = pos + 24, pos + gsize
        while q + 24 <= gend:
            sig = b[q:q + 4]
            if sig == b"GRUP":
                q += struct.unpack_from("<I", b, q + 4)[0]
                continue
            dsize, _flags, formid = struct.unpack_from("<III", b, q + 4)
            # 文件里本插件记录的 formid 前缀 = 自己的 master 数（不一定等于调用者给的前缀），
            # 所以按低 24 位匹配。
            if (formid & 0xFFFFFF) == (want & 0xFFFFFF):
                rec = (sig.decode("latin1"), q + 24, dsize)
            q += 24 + dsize
        pos += gsize

    if rec is None:
        print(f"record {want:08X} not found")
        return 1
    sig, off, size = rec
    payload = b[off:off + size]
    print(f"record  : {sig} {want:08X} size={size}")

    subs: Counter[str] = Counter()
    by_master: Counter[int] = Counter()
    p = 0
    while p + 6 <= size:
        s = payload[p:p + 4]
        sz = struct.unpack_from("<H", payload, p + 4)[0]
        data = payload[p + 6:p + 6 + sz]
        subs[s.decode("latin1")] += 1
        if s == b"LNAM" and sz >= 4:
            for k in range(0, sz - 3, 4):
                fid = struct.unpack_from("<I", data, k)[0]
                by_master[fid >> 24] += 1
        p += 6 + sz

    print(f"subrecords: {dict(subs)}")
    print("member master-index histogram:")
    for idx, n in sorted(by_master.items()):
        name = masters[idx] if idx < len(masters) else f"<out of range {idx}>"
        print(f"  [{idx}] {name}: {n}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
