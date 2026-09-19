# -*- coding: utf-8 -*-
"""快速扫描一批 Starfield 插件（.esm/.esp），输出头部 flags / formVersion /
记录数 / 是否含「覆盖原版记录」(FormID 高字节 = 00)。

用法:
    python sf_flags_scan.py <dir_or_file> [<dir_or_file> ...]

用途（本项目的场景）:
    - 判断 flags 0x100（Starfield "Light" 位）在能正常工作的插件里是否存在
    - 判断「Light 插件不允许覆盖原版记录」这一 Skyrim/FO4 规则在 Starfield 是否成立
"""
import struct
import sys
import os
import glob

REC_HDR = 24
GRP_HDR = 24
FLAG_COMPRESSED = 0x00040000


def scan(path):
    with open(path, 'rb') as f:
        data = f.read()
    if data[0:4] != b'TES4':
        return None
    flags = struct.unpack_from('<I', data, 8)[0]
    hdr_fver = struct.unpack_from('<H', data, 20)[0]
    masters = []
    hdr_size = struct.unpack_from('<I', data, 4)[0]
    off = REC_HDR
    end = REC_HDR + hdr_size
    while off + 6 <= end:
        rsig = data[off:off + 4]
        rsize = struct.unpack_from('<H', data, off + 4)[0]
        if rsig == b'MAST':
            masters.append(data[off + 6:off + 6 + rsize].split(b'\x00')[0].decode('utf-8', 'replace'))
        off += 6 + rsize

    stats = {'rec': 0, 'override': 0, 'fver': set()}
    pos = REC_HDR + hdr_size

    def walk(gstart, gend):
        p = gstart
        while p < gend:
            if data[p:p + 4] == b'GRUP':
                gsize = struct.unpack_from('<I', data, p + 4)[0]
                if gsize < GRP_HDR or p + gsize > gend:
                    return
                walk(p + GRP_HDR, p + gsize)
                p += gsize
            else:
                dsize = struct.unpack_from('<I', data, p + 4)[0]
                fid = struct.unpack_from('<I', data, p + 12)[0]
                fver = struct.unpack_from('<H', data, p + 20)[0]
                stats['rec'] += 1
                stats['fver'].add(fver)
                if (fid >> 24) == 0:
                    stats['override'] += 1
                p += REC_HDR + dsize
                if dsize == 0 and data[p - 24:p - 20].strip() == b'':
                    return

    try:
        walk(pos, len(data))
    except Exception:
        pass
    return flags, hdr_fver, masters, stats


def main():
    paths = []
    for a in sys.argv[1:]:
        if os.path.isdir(a):
            paths += sorted(glob.glob(os.path.join(a, '**', '*.esm'), recursive=True))
            paths += sorted(glob.glob(os.path.join(a, '**', '*.esp'), recursive=True))
            paths += sorted(glob.glob(os.path.join(a, '**', '*.esl'), recursive=True))
        else:
            paths.append(a)
    print(f'{"flags":>10}  {"hfver":>5}  {"rec":>6}  {"ovr":>5}  fver(dist)      masters / file')
    for p in paths:
        try:
            r = scan(p)
        except Exception as ex:
            print(f'  ERR {p}: {ex}')
            continue
        if not r:
            print(f'  SKIP (not TES4) {p}')
            continue
        flags, hfver, masters, stats = r
        fv = ','.join(str(x) for x in sorted(stats['fver'])[:4])
        fl = f'0x{flags:08X}'
        tag = ''
        if flags & 0x01:
            tag += 'ESM '
        if flags & 0x80:
            tag += 'Loc '
        if flags & 0x100:
            tag += 'LIGHT '
        m = ','.join(masters[:2]) + ('...' if len(masters) > 2 else '')
        print(f'{fl:>10}  {hfver:>5}  {stats["rec"]:>6}  {stats["override"]:>5}  {fv:<14}  {m} / {os.path.basename(p)}  [{tag.strip()}]')


if __name__ == '__main__':
    main()
