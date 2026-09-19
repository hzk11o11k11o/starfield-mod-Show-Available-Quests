# -*- coding: utf-8 -*-
"""统计某类记录里某个 4 字节子记录的取值分布（判断它到底是不是 FormID）
用法: python field_stats.py <plugin> <SIG> <SUBSIG> [records_limit]
      python field_stats.py <plugin> <SIG> <SUBSIG> --master <master.esm>   # 额外标注是否存在于 master
"""
import struct
import sys
import zlib
import collections


def iter_records(d):
    hdr = struct.unpack('<I', d[4:8])[0]
    stack = [(24 + hdr, len(d))]
    while stack:
        a, b = stack.pop()
        p = a
        while p + 4 <= b:
            if d[p:p + 4] == b'GRUP':
                sz = struct.unpack('<I', d[p + 4:p + 8])[0]
                stack.append((p + 24, min(p + sz, b)))
                p += sz
                continue
            if p + 24 > b:
                break
            sig = d[p:p + 4]
            ds = struct.unpack('<I', d[p + 4:p + 8])[0]
            fl = struct.unpack('<I', d[p + 8:p + 12])[0]
            fid = struct.unpack('<I', d[p + 12:p + 16])[0]
            pl = d[p + 24:p + 24 + ds]
            if fl & 0x00040000 and pl:
                try:
                    pl = zlib.decompress(pl[4:])
                except Exception:
                    pl = b''
            yield sig, fid, pl
            p += 24 + ds


def main():
    path, sig, subsig = sys.argv[1], sys.argv[2].encode(), sys.argv[3].encode()
    master = None
    if '--master' in sys.argv:
        master = sys.argv[sys.argv.index('--master') + 1]

    idset = None
    if master:
        md = open(master, 'rb').read()
        idset = set()
        for s, fid, pl in iter_records(md):
            if fid < 0x01000000:
                idset.add(fid)
        print(f"master records(index0)={len(idset)}")

    d = open(path, 'rb').read()
    vals = collections.Counter()
    nrec = 0
    for s, fid, pl in iter_records(d):
        if s != sig:
            continue
        nrec += 1
        o = 0
        while o + 6 <= len(pl):
            ss = pl[o:o + 4]
            n = struct.unpack('<H', pl[o + 4:o + 6])[0]
            if o + 6 + n > len(pl):
                break
            if ss == subsig and n >= 4:
                for i in range(0, n - 3, 4):
                    vals[struct.unpack_from('<I', pl, o + 6 + i)[0]] += 1
            o += 6 + n
    print(f"{sig.decode()} records={nrec}, distinct {subsig.decode()} values={len(vals)}")
    for v, c in sorted(vals.items(), key=lambda kv: -kv[1])[:40]:
        mark = ''
        if idset is not None and v != 0:
            mark = ' EXISTS-in-master' if v in idset else ' NOT-in-master'
        print(f"  {v:08X} x{c}{mark}")


if __name__ == '__main__':
    main()
