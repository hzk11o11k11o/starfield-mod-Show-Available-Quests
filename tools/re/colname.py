#!/usr/bin/env python3
"""把 MSVC 的 CompleteObjectLocator（COL）RVA 解成类名。

用法： python tools/re/colname.py 0x4FBDC30 0x4FBDC80 ...
"""
import struct
import sys
from pathlib import Path

EXE = Path(r"D:\SteamLibrary\steamapps\common\Starfield\Starfield.exe")


def main() -> int:
    data = EXE.read_bytes()
    e = struct.unpack_from("<I", data, 0x3C)[0]
    base = struct.unpack_from("<Q", data, e + 0x30)[0]
    import pefile

    pe = pefile.PE(str(EXE), fast_load=True)

    def r2o(rva):
        for s in pe.sections:
            if s.VirtualAddress <= rva < s.VirtualAddress + max(s.Misc_VirtualSize, s.SizeOfRawData):
                return s.PointerToRawData + (rva - s.VirtualAddress)
        return None

    for tok in sys.argv[1:]:
        col_rva = int(tok, 0)
        o = r2o(col_rva)
        if o is None:
            print(f"{tok}: 不在 section 内")
            continue
        sig, coff, cd, ptd, pcd = struct.unpack_from("<IIIII", data, o)
        o2 = r2o(ptd)
        name = data[o2 + 0x10:o2 + 0x10 + 200].split(b"\x00", 1)[0].decode("ascii", "replace")
        print(f"COL 0x{col_rva:X}  sig={sig} offset={coff} cd={cd}  TD 0x{ptd:X}  name={name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
