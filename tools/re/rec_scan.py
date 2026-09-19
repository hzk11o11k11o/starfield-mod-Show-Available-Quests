# -*- coding: utf-8 -*-
"""按签名扫描插件里的记录，输出「子记录签名序列」，用于与其它插件/原版做结构对比。

用法:
    python rec_scan.py <plugin> --sig PERK [--edid <子串>] [--sub EPF2] [--limit 40]
    python rec_scan.py <plugin> --sig PERK --sigsum          # 只统计子记录签名组合

输出:
    formID / formVersion / EDID / 子记录序列（sig 列表，带 size）
"""
import struct
import sys
import zlib

REC_HDR = 24
GRP_HDR = 24
FLAG_COMPRESSED = 0x00040000


def subrecords(payload):
    """返回 [(sig, size, raw)]，顺序即磁盘顺序"""
    out = []
    off = 0
    n = len(payload)
    while off + 6 <= n:
        sig = payload[off:off + 4].decode('ascii', errors='replace')
        size = struct.unpack('<H', payload[off + 4:off + 6])[0]
        if off + 6 + size > n:
            break
        out.append((sig, size, payload[off + 6:off + 6 + size]))
        off += 6 + size
    return out


def walk(data):
    """yield (sig, formID, flags, fver, payload)"""
    if data[0:4] != b'TES4':
        raise ValueError('not a plugin')
    hdr_size = struct.unpack('<I', data[4:8])[0]
    pos = REC_HDR + hdr_size

    def walk_group(gstart, gend):
        p = gstart
        while p < gend:
            if data[p:p + 4] == b'GRUP':
                gsize = struct.unpack('<I', data[p + 4:p + 8])[0]
                if gsize < GRP_HDR or p + gsize > gend:
                    return
                yield from walk_group(p + GRP_HDR, p + gsize)
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
                        payload = zlib.decompress(payload[4:])
                    except Exception:
                        payload = b''
                yield sig, fid, flags, fver, payload
                p = dstart + dsize
                if dsize == 0 and sig.strip() == '':
                    return

    yield from walk_group(pos, len(data))


def get_edid(payload):
    for sig, size, raw in subrecords(payload):
        if sig == 'EDID':
            return raw.split(b'\x00')[0].decode('utf-8', errors='replace')
        if sig in ('VMAD',):
            break
    return ''


def main():
    args = sys.argv[1:]
    if not args:
        print(__doc__)
        return
    path = args[0]
    want_sig = None
    edid_sub = None
    sub_filter = None
    limit = 40
    sigsum = False
    i = 1
    while i < len(args):
        a = args[i]
        if a == '--sig':
            want_sig = args[i + 1]
            i += 2
        elif a == '--edid':
            edid_sub = args[i + 1]
            i += 2
        elif a == '--sub':
            sub_filter = args[i + 1]
            i += 2
        elif a == '--limit':
            limit = int(args[i + 1])
            i += 2
        elif a == '--sigsum':
            sigsum = True
            i += 1
        else:
            i += 1

    with open(path, 'rb') as f:
        data = f.read()

    shown = 0
    combos = {}
    total = 0
    for sig, fid, flags, fver, payload in walk(data):
        if want_sig and sig != want_sig:
            continue
        total += 1
        subs = subrecords(payload)
        sigs = tuple(s[0] for s in subs)
        combos[sigs] = combos.get(sigs, 0) + 1
        if sigsum:
            continue
        if sub_filter and sub_filter not in sigs:
            continue
        edid = get_edid(payload)
        if edid_sub and edid_sub.lower() not in edid.lower():
            continue
        if shown < limit:
            desc = ' '.join(f'{s}({sz})' if sz else s for s, sz, _ in subs)
            print(f'{sig} {fid:08X} fver={fver} flags={flags:08X} EDID={edid}')
            print(f'    {desc}')
            shown += 1

    print(f'--- {want_sig or "ALL"}: total={total} shown={shown}')
    if sigsum:
        print('子记录签名组合（按出现次数）:')
        for combo, cnt in sorted(combos.items(), key=lambda kv: -kv[1])[:30]:
            print(f'  x{cnt:<5} {" ".join(combo)}')


if __name__ == '__main__':
    main()
