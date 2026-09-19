# -*- coding: utf-8 -*-
"""（v4.13 新增，可复用）：把一个 .data 地址区间里的「对象（首字段=vtable）」全 dump 出来，
并把每个 vtable 的 RTTI 类名（宽松解析：解析不出来就原样打 RVA）列出来。

用途：事件源对象在 .data 里是**按类型成组排列**的，肉眼扫一遍就能找到
「我们的扫描因为类名解析失败而漏掉的那些」（例如 ClearQuickContainerEvent）。

用法：python out/dump_ev_range.py 0x5977800 0x5978C00
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


lo = int(sys.argv[1], 0)
hi = int(sys.argv[2], 0)
for rva in range(lo, hi, 8):
    o = r2o(rva)
    if o is None:
        continue
    vt = struct.unpack_from("<Q", image, o)[0]
    if not (IB <= vt < IB + 0x8000000):
        continue
    vt_rva = vt - IB
    if sec_of(vt_rva) != ".rdata":
        continue
    nm, col = class_of_vtable(vt_rva)
    size, cap, data = struct.unpack_from("<IIQ", image, o + 8)
    print(f"0x{rva:X}  vtable=0x{vt_rva:X} COL=0x{col if col else 0:X}  "
          f"sinks(size={size},cap={cap},data=0x{data:X})  {nm or '<名字解析失败>'}")
