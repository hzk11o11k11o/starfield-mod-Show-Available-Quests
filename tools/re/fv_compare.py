# -*- coding: utf-8 -*-
"""批量采样多个插件的 form version，用于判断“mod 的记录 form version 是否落后于游戏”"""
import struct
import sys
import os
import collections

GRP_HDR = 24
REC_HDR = 24


def sample(path, limit=400):
    if not os.path.isfile(path):
        return None
    with open(path, 'rb') as f:
        data = f.read(64 * 1024 * 1024)
    if data[0:4] != b'TES4':
        return None
    hdr = struct.unpack('<I', data[4:8])[0]
    hdr_fv = struct.unpack('<H', data[20:22])[0]
    fv = collections.Counter()
    n = 0
    p = REC_HDR + hdr
    while p < len(data) and n < limit:
        if data[p:p + 4] == b'GRUP':
            gsize = struct.unpack('<I', data[p + 4:p + 8])[0]
            if gsize < GRP_HDR:
                break
            q, gend = p + GRP_HDR, p + gsize
            while q < gend and n < limit and q + REC_HDR <= len(data):
                if data[q:q + 4] == b'GRUP':
                    sz = struct.unpack('<I', data[q + 4:q + 8])[0]
                    if sz < GRP_HDR:
                        break
                    q += sz
                    continue
                dsize = struct.unpack('<I', data[q + 4:q + 8])[0]
                v = struct.unpack('<H', data[q + 20:q + 22])[0]
                fv[v] += 1
                n += 1
                q += REC_HDR + dsize
            p += gsize
        else:
            break
    return hdr_fv, fv, n


for path in sys.argv[1:]:
    r = sample(path)
    name = os.path.basename(path)
    if not r:
        print(f"{name}: (读取失败/非插件)")
        continue
    hdr_fv, fv, n = r
    dist = ', '.join(f"{k}x{v}" for k, v in sorted(fv.items()))
    print(f"{name}: headerFormVersion={hdr_fv} | 采样{n}条记录: {dist}")
