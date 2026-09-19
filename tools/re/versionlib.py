"""SFSE Address Library (versionlib-*.bin) 解析器 + Starfield.exe 反汇编工具。

用法示例：
    python versionlib.py info
    python versionlib.py id 83006 83007 83008 83009 83010
    python versionlib.py dis 83007
    python versionlib.py range 83000 83030
"""
from __future__ import annotations

import argparse
import struct
import sys
from pathlib import Path

# --------------------------------------------------------------------------
# 路径
# --------------------------------------------------------------------------
EXE = Path(r"D:\SteamLibrary\steamapps\common\Starfield\Starfield.exe")
LIB = Path(
    r"D:\Mod Organizer 2\starfield_mods\mods\(1.16.244.0) SFSE Address Library"
    r"\SFSE\Plugins\versionlib-1-16-244-0.bin"
)


# Starfield 的 SFSE Address Library 实测格式（versionlib-1-16-244-0.bin, format=5）：
#
#   0x00  u32   format          = 5
#   0x04  u32x4 version         = 1.16.244.0
#   0x14  char  name[0x40]      = "Starfield.exe\0"（固定 0x40 字节，右侧补 0）
#   0x54  u32   pointerSize     = 8
#   0x58  u32   <pad>           = 0
#   0x5C  u32   addressCount    = 0x137458
#   0x60  u32[] offsets         ← 条目就是「纯 4 字节 RVA」，**ID 即下标 +1**
#
# 即 offset(id) = u32 @ (0x60 + 4*(id-1))。已用 IDs.h 里连续 ID 反查验证：
#   83006 -> 0x1306D50, 83007 -> 0x1306E20, 83008 -> 0x1306E80（相邻函数，间隔合理）
#   937585(GameVM::Singleton) -> 0x5FD9B88（.data 段，合理）
HEADER_SIZE = 0x60
ENTRY_SIZE = 4


def read_versionlib(path: Path):
    """返回 (header_dict, {id: offset})。Starfield format=5。"""
    data = path.read_bytes()

    (fmt,) = struct.unpack_from("<I", data, 0)
    version = struct.unpack_from("<4I", data, 4)
    name = data[0x14:0x54].split(b"\x00", 1)[0].decode("ascii", "replace")
    (pointer_size,) = struct.unpack_from("<I", data, 0x54)
    (count,) = struct.unpack_from("<I", data, 0x5C)

    if fmt != 5:
        raise ValueError(f"本解析器只支持实测过的 format=5，实际 {fmt}")

    table: dict[int, int] = {}
    off = HEADER_SIZE
    for i in range(count):
        if off + ENTRY_SIZE > len(data):
            break
        (rva,) = struct.unpack_from("<I", data, off)
        off += ENTRY_SIZE
        if rva:
            table[i + 1] = rva  # ID 从 1 开始

    header = {
        "format": fmt,
        "version": version,
        "name": name,
        "pointer_size": pointer_size,
        "count": count,
        "data_offset": HEADER_SIZE,
        "parsed_bytes": off,
    }
    return header, table


# --------------------------------------------------------------------------
# PE / 反汇编
# --------------------------------------------------------------------------
def load_pe_image(path: Path):
    import pefile

    pe = pefile.PE(str(path), fast_load=True)
    pe.parse_data_directories()
    return pe


def rva_to_off(pe, rva: int) -> int | None:
    for s in pe.sections:
        base = s.VirtualAddress
        if base <= rva < base + max(s.Misc_VirtualSize, s.SizeOfRawData):
            return s.PointerToRawData + (rva - base)
    return None


def module_base(image: bytes) -> int:
    """从 PE 头读 ImageBase。"""
    e_lfanew = struct.unpack_from("<I", image, 0x3C)[0]
    return struct.unpack_from("<Q", image, e_lfanew + 0x30)[0]


def fmt_bytes(b: bytes) -> str:
    return " ".join(f"{x:02X}" for x in b)


def disasm(pe, image: bytes, rva: int, base: int, count: int = 60):
    from capstone import CS_ARCH_X86, CS_MODE_64, Cs

    md = Cs(CS_ARCH_X86, CS_MODE_64)
    off = rva_to_off(pe, rva)
    if off is None:
        return "<rva 不在任何 section 内>"
    va = base + rva
    out = []
    for ins in md.disasm(image[off : off + 0x800], va):
        out.append(f"{ins.address:012X}  {fmt_bytes(ins.bytes):<30} {ins.mnemonic:<8} {ins.op_str}")
        if len(out) >= count:
            break
    return "\n".join(out)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["info", "id", "dis", "range", "xref", "hex", "refs"])
    ap.add_argument("args", nargs="*")
    ap.add_argument("--count", type=int, default=60)
    a = ap.parse_args()

    header, table = read_versionlib(LIB)

    if a.cmd == "info":
        print("header:", header)
        ids = sorted(table)
        print(f"ids: {len(ids)}  min={ids[0]}  max={ids[-1]}")
        return 0

    if a.cmd == "id":
        for s in a.args:
            i = int(s, 0)
            print(f"ID {i} -> RVA 0x{table.get(i, -1):X}" if i in table else f"ID {i} -> <missing>")
        return 0

    if a.cmd == "range":
        lo, hi = (int(x, 0) for x in a.args[:2])
        for i in range(lo, hi + 1):
            if i in table:
                print(f"ID {i} -> RVA 0x{table[i]:X}")
        return 0

    image = EXE.read_bytes()
    base = module_base(image)
    pe = load_pe_image(EXE)

    if a.cmd == "dis":
        for s in a.args:
            # 纯数字 = REL::ID；0x... = 直接给 RVA（用于反汇编 xref 找到的调用点）
            if s.startswith("0x"):
                rva, label = int(s, 0), f"RVA {s}"
            else:
                rva = table.get(int(s, 0))
                label = f"ID {s}"
            if rva is None:
                print(f"{label} -> <missing>")
                continue
            print(f"===== {label}  RVA 0x{rva:X}  VA 0x{base + rva:X} =====")
            print(disasm(pe, image, rva, base, a.count))
            print()
        return 0

    if a.cmd == "xref":
        # 找出所有「直接 call/jmp 到目标 RVA」的位置（E8/E9 + rel32）。
        # 用 bytes.find 而不是逐字节 Python 循环 —— 40MB 的 .text 上后者要跑几分钟。
        targets = {int(s, 0) for s in a.args}
        hits: list[tuple[int, int]] = []
        for s in pe.sections:
            if not (s.Characteristics & 0x20000000):  # IMAGE_SCN_MEM_EXECUTE
                continue
            rva0 = s.VirtualAddress
            blob = image[s.PointerToRawData : s.PointerToRawData + s.SizeOfRawData]
            for opc in (0xE8, 0xE9):
                needle = bytes([opc])
                k = blob.find(needle)
                while k != -1:
                    if k + 5 <= len(blob):
                        rel = struct.unpack_from("<i", blob, k + 1)[0]
                        callee = rva0 + k + 5 + rel
                        if callee in targets:
                            hits.append((rva0 + k, callee))
                    k = blob.find(needle, k + 1)
        for h, t in hits:
            print(f"RVA 0x{t:X}  <- called from RVA 0x{h:X} (VA 0x{base + h:X})")
        if not hits:
            print("no direct call/jmp xref found")
        return 0

    if a.cmd in ("hex", "refs"):
        # hex  : 把某个 ID / RVA 处的内容 dump 出来（vtable 就是一串 u64 函数指针）
        # refs : 在整个映像里找「值等于某地址」的 8 字节（找 vtable/函数指针表里的成员）
        if a.cmd == "hex":
            for tok in a.args:
                rva = int(tok, 0) if tok.startswith("0x") else table.get(int(tok, 0))
                if rva is None:
                    print(f"{tok} -> <missing>")
                    continue
                off = rva_to_off(pe, rva)
                if off is None:
                    print(f"{tok} (RVA 0x{rva:X}) -> 不在任何 section 内")
                    continue
                print(f"===== {tok}  RVA 0x{rva:X} =====")
                for i in range(a.count):
                    o = off + i * 8
                    if o + 8 > len(image):
                        break
                    q = struct.unpack_from("<Q", image, o)[0]
                    note = ""
                    if base <= q < base + 0x8000000:
                        note = f"  -> RVA 0x{q - base:X}"
                    print(f"  +0x{i * 8:03X}  0x{q:016X}{note}")
                print()
            return 0

        if a.cmd == "refs":
            vals = [int(t, 0) for t in a.args]
            for v in vals:
                needle = struct.pack("<Q", base + v)
                print(f"===== 找引用 VA 0x{base + v:X} (RVA 0x{v:X}) 的 8 字节 =====")
                found = 0
                k = image.find(needle)
                while k != -1:
                    sec = next(
                        (s for s in pe.sections
                         if s.PointerToRawData <= k < s.PointerToRawData + s.SizeOfRawData),
                        None,
                    )
                    rva = (k - sec.PointerToRawData + sec.VirtualAddress) if sec else -1
                    print(f"  文件偏移 0x{k:X}  RVA 0x{rva:X}  section={sec.Name.decode(errors='replace') if sec else '?'}")
                    found += 1
                    if found >= 40:
                        print("  ...(超过 40 处，截断)")
                        break
                    k = image.find(needle, k + 1)
                if not found:
                    print("  (无)")
                print()
            return 0

    return 0


if __name__ == "__main__":
    sys.exit(main())
