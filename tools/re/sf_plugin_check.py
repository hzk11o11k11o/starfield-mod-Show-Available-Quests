# -*- coding: utf-8 -*-
"""Starfield 插件(ESM/ESP)兼容性检查。

用法:
    python sf_plugin_check.py <plugin> [<plugin2> ...]

输出:
    - 头部关键字段: flags(是否 ESM/本地化)、formVersion、HEDR version
    - 头部子记录明细(含 MAST 列表)
    - 顶层 GRUP / 记录统计、各记录 formVersion 分布
    - 与同目录/原版参考插件的 formVersion 对照提示
"""
import struct
import sys
import collections
import os

REC_HDR = 24
GRP_HDR = 24
FLAG_MASTER = 0x00000001
FLAG_LOCALIZED = 0x00000080
FLAG_COMPRESSED = 0x00040000


def parse_header(data, verbose=False):
    if data[0:4] != b'TES4':
        raise ValueError('not a Bethesda plugin (no TES4 signature)')
    data_size = struct.unpack('<I', data[4:8])[0]
    flags = struct.unpack('<I', data[8:12])[0]
    form_id = struct.unpack('<I', data[12:16])[0]
    vc = struct.unpack('<I', data[16:20])[0]
    form_ver = struct.unpack('<H', data[20:22])[0]
    unknown = struct.unpack('<H', data[22:24])[0]

    info = {
        'dataSize': data_size,
        'flags': flags,
        'formID': form_id,
        'vcInfo': vc,
        'formVersion': form_ver,
        'unknown': unknown,
        'masters': [],
        'hedr': None,
        'snam': None,
        'cnam': None,
    }

    off = REC_HDR
    end = REC_HDR + data_size
    while off + 6 <= end:
        rsig = data[off:off + 4].decode('ascii', errors='replace')
        rsize = struct.unpack('<H', data[off + 4:off + 6])[0]
        payload = data[off + 6:off + 6 + rsize]
        if rsig == 'HEDR' and len(payload) >= 12:
            info['hedr'] = (
                struct.unpack('<f', payload[0:4])[0],
                struct.unpack('<I', payload[4:8])[0],
                struct.unpack('<I', payload[8:12])[0],
            )
        elif rsig == 'MAST':
            info['masters'].append(payload.split(b'\x00')[0].decode('utf-8', errors='replace'))
        elif rsig == 'SNAM':
            info['snam'] = payload
        elif rsig == 'CNAM':
            info['cnam'] = payload
        if verbose:
            print(f"  @{off:6d} {rsig} size={rsize} ascii={payload[:48]!r}")
        off += 6 + rsize
    return info


def walk_records(data):
    """返回 (grups, records)。records: (sig, formID, flags, formVersion, EDID)"""
    data_size = struct.unpack('<I', data[4:8])[0]
    pos = REC_HDR + data_size
    grups = []
    records = []

    def parse_edid(payload):
        o = 0
        n = len(payload)
        while o + 6 <= n:
            sig = payload[o:o + 4]
            size = struct.unpack('<H', payload[o + 4:o + 6])[0]
            if sig == b'EDID':
                return payload[o + 6:o + 6 + size].split(b'\x00')[0].decode('utf-8', errors='replace')
            if o + 6 + size > n:
                break
            o += 6 + size
        return ''

    def walk_group(gstart, gend, depth):
        p = gstart
        while p < gend:
            if data[p:p + 4] == b'GRUP':
                gsize = struct.unpack('<I', data[p + 4:p + 8])[0]
                if gsize < GRP_HDR or p + gsize > gend:
                    return
                label = struct.unpack('<I', data[p + 8:p + 12])[0]
                gtype = struct.unpack('<I', data[p + 12:p + 16])[0]
                grups.append((depth, label, gtype))
                walk_group(p + GRP_HDR, p + gsize, depth + 1)
                p += gsize
            else:
                sig = data[p:p + 4].decode('ascii', errors='replace')
                dsize = struct.unpack('<I', data[p + 4:p + 8])[0]
                flags = struct.unpack('<I', data[p + 8:p + 12])[0]
                fid = struct.unpack('<I', data[p + 12:p + 16])[0]
                fver = struct.unpack('<H', data[p + 20:p + 22])[0]
                payload = data[p + REC_HDR:p + REC_HDR + dsize]
                if flags & FLAG_COMPRESSED and len(payload) >= 4:
                    import zlib
                    try:
                        payload = zlib.decompress(payload[4:])
                    except Exception:
                        payload = b''
                records.append((sig, fid, flags, fver, parse_edid(payload)))
                p += REC_HDR + dsize

    walk_group(pos, len(data), 0)
    return grups, records


def report(path):
    with open(path, 'rb') as f:
        data = f.read()
    print('=' * 78)
    print(f'File: {path}')
    print(f'Size: {len(data)} bytes')
    info = parse_header(data, verbose=False)
    fl = info['flags']
    print(f"Signature: TES4")
    print(f"flags: 0x{fl:08X}  -> {'ESM(master)' if fl & FLAG_MASTER else 'ESP(plugin)'}"
          f"{' + localized' if fl & FLAG_LOCALIZED else ''}")
    print(f"header formVersion: {info['formVersion']}  (offset20 u16)")
    if info['hedr']:
        hv, num, nid = info['hedr']
        print(f"HEDR: version={hv:.4f} numRecords={num} nextObjectID=0x{nid:08X}")
    if info['cnam'] is not None:
        author = info['cnam'].split(b'\x00')[0].decode('utf-8', errors='replace')
        print(f"CNAM(author): {author}")
    if info['masters']:
        print('MAST (masters):')
        for m in info['masters']:
            print(f'   - {m}')
    else:
        print('MAST (masters): <none>  !! plugin 无 master，可能非法')
    if info['snam']:
        desc = info['snam'].split(b'\x00')[0].decode('utf-8', errors='replace')
        print(f"SNAM(desc): {desc[:200]}")

    grups, records = walk_records(data)
    print(f'Top GRUP count: {len(grups)}  Records: {len(records)}')
    cnt = collections.Counter(r[0] for r in records)
    print('records by signature:')
    for k in sorted(cnt, key=lambda x: -cnt[x]):
        print(f'   {k}: {cnt[k]}')
    fv = collections.Counter(r[3] for r in records)
    print(f'record formVersion dist: {dict(sorted(fv.items()))}')
    print('sample records (first 40):')
    for r in records[:40]:
        print(f'   {r[0]} formID={r[1]:08X} flags={r[2]:08X} fver={r[3]} EDID={r[4]}')


def main():
    for p in sys.argv[1:]:
        if not os.path.exists(p):
            print(f'MISSING: {p}')
            continue
        try:
            report(p)
        except Exception as ex:
            print(f'ERROR parsing {p}: {ex}')


if __name__ == '__main__':
    main()
