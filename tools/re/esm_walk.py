# -*- coding: utf-8 -*-
"""遍历 Bethesda 插件(尤其 Starfield)所有记录，输出 TSV：
sig, formID, flags, formVersion, EDID(可能为空)
支持 zlib 压缩记录；GRUP 递归。
用法: python esm_walk.py <plugin> <out.tsv> [--index-map master1=0,master2=1,...]
"""
import struct
import sys
import zlib
import os

REC_HDR = 24
GRP_HDR = 24
FLAG_COMPRESSED = 0x00040000


def parse_edid(data):
    """从记录数据里取第一个 EDID 子记录"""
    off = 0
    n = len(data)
    while off + 6 <= n:
        sig = data[off:off + 4]
        size = struct.unpack('<H', data[off + 4:off + 6])[0]
        if sig == b'EDID':
            raw = data[off + 6:off + 6 + size]
            return raw.split(b'\x00')[0].decode('utf-8', errors='replace')
        if off + 6 + size > n:
            break
        off += 6 + size
    return ''


def walk(data, out_lines, stats):
    pos = 0
    size = len(data)
    # 头部 TES4
    if data[0:4] != b'TES4':
        raise ValueError('not a plugin (no TES4)')
    hdr_size = struct.unpack('<I', data[4:8])[0]
    pos = REC_HDR + hdr_size

    def walk_group(gstart, gend, depth):
        p = gstart
        while p < gend:
            if data[p:p + 4] == b'GRUP':
                gsize = struct.unpack('<I', data[p + 4:p + 8])[0]
                if gsize < GRP_HDR or p + gsize > gend:
                    return
                walk_group(p + GRP_HDR, p + gsize, depth + 1)
                p += gsize
            else:
                sig = data[p:p + 4].decode('ascii', errors='replace')
                dsize = struct.unpack('<I', data[p + 4:p + 8])[0]
                flags = struct.unpack('<I', data[p + 8:p + 12])[0]
                fid = struct.unpack('<I', data[p + 12:p + 16])[0]
                fver = struct.unpack('<H', data[p + 20:p + 22])[0]
                dstart = p + REC_HDR
                payload = data[dstart:dstart + dsize]
                if flags & FLAG_COMPRESSED:
                    try:
                        usize = struct.unpack('<I', payload[0:4])[0]
                        payload = zlib.decompress(payload[4:])
                        if len(payload) != usize:
                            pass
                    except Exception:
                        payload = b''
                edid = parse_edid(payload)
                out_lines.append(f"{sig}\t{fid:08X}\t{flags:08X}\t{fver}\t{edid}")
                stats[sig] = stats.get(sig, 0) + 1
                p = dstart + dsize
                if dsize == 0 and sig.strip() == '':
                    return

    walk_group(pos, size, 0)


def main():
    path = sys.argv[1]
    out_path = sys.argv[2] if len(sys.argv) > 2 else None
    with open(path, 'rb') as f:
        data = f.read()
    lines = []
    stats = {}
    walk(data, lines, stats)
    print(f"records: {len(lines)}")
    print("by signature:")
    for k in sorted(stats):
        print(f"  {k}: {stats[k]}")
    # form version 分布
    fv = {}
    for ln in lines:
        v = ln.split('\t')[3]
        fv[v] = fv.get(v, 0) + 1
    print("form versions:", dict(sorted(fv.items(), key=lambda kv: int(kv[0]))))
    if out_path:
        with open(out_path, 'w', encoding='utf-8') as f:
            f.write("sig\tformID\tflags\tformVersion\tEDID\n")
            f.write('\n'.join(lines))
        print(f"written: {out_path}")


if __name__ == '__main__':
    main()
