# -*- coding: utf-8 -*-
"""打印某插件里指定签名/FormID 记录的原始子记录，用于人工核对某个字段是不是 FormID
用法: python dump_one_record.py <plugin> <SIG> [formID_hex] [limit]
"""
import struct
import sys
import zlib


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
    path, want = sys.argv[1], sys.argv[2].encode()
    fid_want = int(sys.argv[3], 16) if len(sys.argv) > 3 else None
    limit = int(sys.argv[4]) if len(sys.argv) > 4 else 3
    d = open(path, 'rb').read()
    shown = 0
    for sig, fid, pl in iter_records(d):
        if sig != want:
            continue
        if fid_want is not None and fid != fid_want:
            continue
        print(f"=== {sig.decode()} {fid:08X}  payload={len(pl)}")
        o = 0
        while o + 6 <= len(pl):
            ss = pl[o:o + 4].decode('latin1')
            n = struct.unpack('<H', pl[o + 4:o + 6])[0]
            if o + 6 + n > len(pl):
                print(f"    [desync at 0x{o:X}]")
                break
            v = pl[o + 6:o + 6 + n]
            txt = ''.join(chr(c) if 32 <= c < 127 else '.' for c in v[:48])
            print(f"    {ss} size={n} {v[:24].hex(' ')} | {txt}")
            o += 6 + n
        shown += 1
        if shown >= limit:
            break


if __name__ == '__main__':
    main()
