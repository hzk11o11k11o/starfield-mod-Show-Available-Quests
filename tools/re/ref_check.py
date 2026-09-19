# -*- coding: utf-8 -*-
"""引用完整性校验：
1) 用 mmap 单遍扫描 master(Starfield.esm)，建立 index=0 的 formID -> 记录签名 映射表
2) 逐条扫描目标插件的记录数据(自动解压)，把所有指向 index=0 的 4 字节候选 FormID 提取出来，
   报告“在 Starfield.esm 中找不到”的候选值及其所在子记录签名，便于人工判断
用法: python ref_check.py <master.esm> <plugin.esm> [out.txt]
"""
import struct
import sys
import mmap
import zlib
import collections
import os

REC_HDR = 24
GRP_HDR = 24
FLAG_COMPRESSED = 0x00040000
MAX_ID = 0x01000000


def sig_text(raw):
    try:
        t = raw.decode('ascii')
        if all(32 <= ord(c) < 127 for c in t):
            return t
        return '0x' + raw.hex()
    except Exception:
        return '0x' + raw.hex()


def build_master_map(path):
    """返回 (sig_map: bytearray 每项 int16, sig_names, count)"""
    sig_names = []
    sig_index = {}
    sig_map = bytearray(b'\xff' * (MAX_ID * 2))  # -1 表示不存在
    count = 0

    with open(path, 'rb') as f:
        mm = mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ)
        total = len(mm)
        hdr_size = struct.unpack('<I', mm[4:8])[0]

        def walk(gstart, gend, depth):
            nonlocal count
            if depth > 12:
                return
            p = gstart
            while p + 4 <= gend:
                if mm[p:p + 4] == b'GRUP':
                    gsize = struct.unpack('<I', mm[p + 4:p + 8])[0]
                    if gsize < GRP_HDR:
                        return
                    walk(p + GRP_HDR, min(p + gsize, gend), depth + 1)
                    p += gsize
                    continue
                if p + REC_HDR > gend:
                    return
                dsize = struct.unpack('<I', mm[p + 4:p + 8])[0]
                fid = struct.unpack('<I', mm[p + 12:p + 16])[0]
                if fid < MAX_ID:
                    raw = bytes(mm[p:p + 4])
                    si = sig_index.get(raw)
                    if si is None:
                        si = len(sig_names)
                        sig_index[raw] = si
                        sig_names.append(sig_text(raw))
                    if si < 32767:
                        struct.pack_into('<h', sig_map, fid * 2, si)
                    count += 1
                p += REC_HDR + dsize

        # 顶层
        pos = REC_HDR + hdr_size
        while pos + 4 <= total:
            if mm[pos:pos + 4] != b'GRUP':
                break
            gsize = struct.unpack('<I', mm[pos + 4:pos + 8])[0]
            if gsize < GRP_HDR:
                break
            walk(pos + GRP_HDR, min(pos + gsize, total), 0)
            pos += gsize
        mm.close()
    return sig_map, sig_names, count


def iter_records(data):
    """遍历插件里所有记录，yield (sig, formID, payload(已解压))"""
    hdr_size = struct.unpack('<I', data[4:8])[0]
    start = REC_HDR + hdr_size

    def walk(gstart, gend):
        p = gstart
        while p < gend:
            if data[p:p + 4] == b'GRUP':
                gsize = struct.unpack('<I', data[p + 4:p + 8])[0]
                if gsize < GRP_HDR:
                    return
                yield from walk(p + GRP_HDR, min(p + gsize, gend))
                p += gsize
            else:
                sig = sig_text(data[p:p + 4])
                dsize = struct.unpack('<I', data[p + 4:p + 8])[0]
                flags = struct.unpack('<I', data[p + 8:p + 12])[0]
                fid = struct.unpack('<I', data[p + 12:p + 16])[0]
                payload = data[p + REC_HDR:p + REC_HDR + dsize]
                if flags & FLAG_COMPRESSED and payload:
                    try:
                        payload = zlib.decompress(payload[4:])
                    except Exception:
                        payload = b''
                yield sig, fid, payload
                p += REC_HDR + dsize

    yield from walk(start, len(data))


def split_subrecords(payload):
    """按子记录切分，yield (subsig, subdata)"""
    off = 0
    n = len(payload)
    while off + 6 <= n:
        ssig = sig_text(payload[off:off + 4])
        ssize = struct.unpack('<H', payload[off + 4:off + 6])[0]
        sstart = off + 6
        if ssize == 0 and off + 10 <= n:
            ext = struct.unpack('<I', payload[off + 6:off + 10])[0]
            if payload[off + 4:off + 8] == b'\x00\x00\x00\x00' and ext > 0:
                ssize = 0  # 扩展长度记录，跳过按普通长度处理
        if sstart + ssize > n:
            break
        yield ssig, payload[sstart:sstart + ssize]
        off = sstart + ssize


def main():
    master, plugin = sys.argv[1], sys.argv[2]
    out_path = sys.argv[3] if len(sys.argv) > 3 else None
    print(f"[1/2] building formID index of {os.path.basename(master)} ...")
    sig_map, sig_names, count = build_master_map(master)
    print(f"      records={count} signatures={len(sig_names)}")

    print(f"[2/2] scanning references of {os.path.basename(plugin)} ...")
    with open(plugin, 'rb') as f:
        data = f.read()

    unresolved = collections.Counter()
    examples = {}
    n_rec = 0
    n_ref = 0
    for sig, fid, payload in iter_records(data):
        n_rec += 1
        if not payload:
            continue
        for ssig, sdata in split_subrecords(payload):
            if len(sdata) < 4:
                continue
            for i in range(0, len(sdata) - 3, 4):
                v = struct.unpack_from('<I', sdata, i)[0]
                if v < 0x00001000 or v >= MAX_ID:
                    continue
                # 排除纯 ASCII 文本（脚本名/文件路径等）
                raw = sdata[i:i + 4]
                if all(0x20 <= b <= 0x7E for b in raw):
                    continue
                n_ref += 1
                if struct.unpack_from('<h', sig_map, v * 2)[0] < 0:
                    key = (ssig, v)
                    unresolved[key] += 1
                    if key not in examples:
                        ctx = sdata[max(0, i - 12):i + 16]
                        examples[key] = f"{sig} {fid:08X} ctx={ctx.hex(' ')}"
    lines = [f"records={n_rec} non_text_candidate_refs={n_ref} unresolved_kinds={len(unresolved)}"]
    for (ssig, v), c in sorted(unresolved.items(), key=lambda kv: -kv[1]):
        lines.append(f"unresolved {ssig} -> {v:08X}  x{c}  (e.g. {examples[(ssig, v)]})")
    text = '\n'.join(lines)
    shown = '\n'.join(lines[:50]) if len(lines) > 50 else text
    sys.stdout.buffer.write((shown + (f"\n... total {len(lines)} lines" if len(lines) > 50 else "") + "\n").encode('utf-8', errors='replace'))
    if out_path:
        with open(out_path, 'w', encoding='utf-8') as f:
            f.write(text)
        print(f"written: {out_path}")


if __name__ == '__main__':
    main()
