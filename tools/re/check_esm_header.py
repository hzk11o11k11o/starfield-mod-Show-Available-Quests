# -*- coding: utf-8 -*-
"""读取并打印 Bethesda 插件(ESM/ESP)头部信息：版本、master 列表、记录统计等"""
import struct
import sys
import collections

def read_cstr(buf, off):
    end = buf.index(b'\x00', off)
    return buf[off:end].decode('utf-8', errors='replace'), end + 1

def main(path):
    with open(path, 'rb') as f:
        data = f.read()

    print(f"File: {path}")
    print(f"Size: {len(data)} bytes")

    sig = data[0:4].decode('ascii', errors='replace')
    data_size = struct.unpack('<I', data[4:8])[0]
    flags = struct.unpack('<I', data[8:12])[0]
    form_id = struct.unpack('<I', data[12:16])[0]
    vc = struct.unpack('<I', data[16:20])[0]
    form_ver = struct.unpack('<H', data[20:22])[0]
    version = struct.unpack('<H', data[22:24])[0]
    print(f"Signature: {sig}")
    print(f"dataSize: {data_size}, flags: 0x{flags:08X}, formID: 0x{form_id:08X}")
    print(f"VC info: 0x{vc:08X}, formVersion: {form_ver}, version: {version}")

    # 解析 HEDR 等子记录(在 header 区，通常无压缩)
    off = 24
    end = 24 + data_size
    masters = []
    while off + 6 <= end:
        rsig = data[off:off+4].decode('ascii', errors='replace')
        rsize = struct.unpack('<H', data[off+4:off+6])[0]
        payload = data[off+6:off+6+rsize]
        if rsig == 'HEDR':
            hver = struct.unpack('<f', payload[0:4])[0]
            num = struct.unpack('<I', payload[4:8])[0]
            nid = struct.unpack('<I', payload[8:12])[0]
            print(f"HEDR: version={hver}, numRecords={num}, nextObjectID=0x{nid:08X}")
        elif rsig == 'MAST':
            name, _ = read_cstr(payload, 0)
            masters.append(name)
        elif rsig == 'CNAM':
            ovc = payload[0:4]
        elif rsig == 'SNAM':
            print(f"SNAM: {payload.hex()}")
        elif rsig == 'DNAM':
            print(f"DNAM: {payload.decode('utf-8', errors='replace')}")
        off += 6 + rsize

    print("Masters:")
    for m in masters:
        print(f"  - {m}")

    # 统计顶层记录(仅顶层 GRUP/记录签名扫描，粗略)
    counts = collections.Counter()
    o = 24 + data_size
    while o + 4 <= len(data):
        s = data[o:o+4]
        try:
            txt = s.decode('ascii')
        except Exception:
            break
        if txt == 'GRUP':
            if o + 24 <= len(data):
                gsize = struct.unpack('<I', data[o+4:o+8])[0]
                glabel = data[o+8:o+12].decode('ascii', errors='replace')
                gtype = struct.unpack('<I', data[o+12:o+16])[0]
                counts[f"GRUP:{glabel}(type{gtype})"] += 1
                o += gsize
            else:
                break
        elif txt.isalpha():
            break
        else:
            break
    print("Top-level groups:")
    for k, v in counts.items():
        print(f"  {k}: {v}")

if __name__ == '__main__':
    main(sys.argv[1])
