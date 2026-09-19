# -*- coding: utf-8 -*-
"""（v4.13 新增，可复用）：扫描镜像里的 **静态 BSTEventSource 对象**（按「首字段是 vtable」找），
并用 vtable[-8] → COL → TypeDescriptor 把类名解出来。

为什么不用 RTTI 名字反查（上一版 find_event_sources.py）：部分事件源找不到 vtable
（COL 的 self 字段不自洽 / 对象内嵌），本方式反过来从「对象」出发，命中率更高。

用法：
    python out/scan_event_sources.py                 # 全部
    python out/scan_event_sources.py Container Mode  # 只打名字里含这些子串的
"""
import struct
import sys
from pathlib import Path

import pefile

EXE = Path(r"D:\SteamLibrary\steamapps\common\Starfield\Starfield.exe")
image = EXE.read_bytes()
pe = pefile.PE(str(EXE), fast_load=True)
IB = pe.OPTIONAL_HEADER.ImageBase
SEC = [(s.Name.rstrip(b"\x00").decode("ascii", "replace"), s.VirtualAddress,
        s.SizeOfRawData, s.PointerToRawData, max(s.Misc_VirtualSize, s.SizeOfRawData))
       for s in pe.sections]


def o2r(off):
    for nm, va, raw, ptr, vs in SEC:
        if ptr <= off < ptr + raw:
            return va + (off - ptr), nm
    return None, None


def r2o(rva):
    for nm, va, raw, ptr, vs in SEC:
        if va <= rva < va + vs:
            return ptr + (rva - va)
    return None


def sec_of(rva):
    for nm, va, raw, ptr, vs in SEC:
        if va <= rva < va + vs:
            return nm
    return None


def td_name(td_rva):
    o = r2o(td_rva)
    if o is None or o + 0x20 > len(image):
        return None
    vft, spare = struct.unpack_from("<QQ", image, o)
    if not (IB <= vft < IB + 0x20000000) or spare != 0:
        return None
    nm = image[o + 0x10:o + 0x10 + 220].split(b"\x00", 1)[0].decode("ascii", "replace")
    return nm if nm.startswith(".?") else None


def class_of_vtable(vt_rva):
    o = r2o(vt_rva - 8)
    if o is None:
        return None
    col_va = struct.unpack_from("<Q", image, o)[0]
    for col_rva in (col_va - IB, col_va):
        if not (0 < col_rva < 0x10000000):
            continue
        oc = r2o(col_rva)
        if oc is None or oc + 0x18 > len(image):
            continue
        sig, coff, cd, ptd = struct.unpack_from("<IIII", image, oc)
        if sig not in (0, 1) or ptd > 0x10000000:
            continue
        nm = td_name(ptd)
        if nm:
            return nm, col_rva
    return None, None


def main():
    subs = [s.lower() for s in sys.argv[1:]]
    rows = []
    # 扫 .data / .rdata / .bss 里的「对象首字段 = vtable」
    for nm, va, raw, ptr, vs in SEC:
        if nm not in (".data", ".rdata"):
            continue
        blob = image[ptr:ptr + raw]
        step = 8
        for k in range(0, len(blob) - 8, step):
            vt = struct.unpack_from("<Q", blob, k)[0]
            if not (IB <= vt < IB + 0x8000000):
                continue
            vt_rva = vt - IB
            if sec_of(vt_rva) not in (".rdata",):
                continue
            nm2, col = class_of_vtable(vt_rva)
            if not nm2 or "BSTEventSource" not in nm2:
                continue
            obj_rva = va + k
            rows.append((obj_rva, vt_rva, nm2, col))

    print(f"扫到疑似事件源对象 {len(rows)} 个\n")
    for obj_rva, vt_rva, name, col in rows:
        if subs and not any(s in name.lower() for s in subs):
            continue
        o = r2o(obj_rva)
        size, cap = struct.unpack_from("<II", image, o + 8)
        data = struct.unpack_from("<Q", image, o + 0x10)[0]
        print(f"{name}")
        print(f"    对象@RVA 0x{obj_rva:X} (sec={sec_of(obj_rva)})  vtable=0x{vt_rva:X}  COL=0x{col:X}")
        print(f"    sinks: size={size} cap={cap} data=0x{data:X}")
        print()


if __name__ == "__main__":
    main()
