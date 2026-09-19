# -*- coding: utf-8 -*-
"""统计整个插件的 form version 分布（每个顶层分组采样前 N 条，快速且具代表性）
用法: python fv_hist.py <plugin> [per_group=40]
"""
import struct
import sys
import mmap
import collections
import os

REC_HDR = 24
GRP_HDR = 24


def main():
    path = sys.argv[1]
    per_group = int(sys.argv[2]) if len(sys.argv) > 2 else 40
    fv = collections.Counter()
    total = 0
    with open(path, 'rb') as f:
        mm = mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ)
        size = len(mm)
        hdr = struct.unpack('<I', mm[4:8])[0]
        p = REC_HDR + hdr
        ngroups = 0
        while p + 4 <= size:
            if mm[p:p + 4] != b'GRUP':
                break
            gsize = struct.unpack('<I', mm[p + 4:p + 8])[0]
            if gsize < GRP_HDR:
                break
            gend = min(p + gsize, size)
            q = p + GRP_HDR
            n = 0
            while q + REC_HDR <= gend and n < per_group:
                if mm[q:q + 4] == b'GRUP':
                    sz = struct.unpack('<I', mm[q + 4:q + 8])[0]
                    if sz < GRP_HDR:
                        break
                    q += sz
                    continue
                dsize = struct.unpack('<I', mm[q + 4:q + 8])[0]
                v = struct.unpack('<H', mm[q + 20:q + 22])[0]
                fv[v] += 1
                total += 1
                n += 1
                q += REC_HDR + dsize
            ngroups += 1
            p = gend
        mm.close()
    print(f"{os.path.basename(path)}: groups={ngroups} sampled={total}")
    for k in sorted(fv):
        print(f"   formVersion {k}: {fv[k]}")


if __name__ == '__main__':
    main()
