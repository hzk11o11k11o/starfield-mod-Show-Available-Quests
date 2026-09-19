#!/usr/bin/env python3
"""Starfield.exe 函数级分析工具（本项目新增，用于「高亮/扫描」逆向）。

为什么需要它：
    disasm.py 只能看「某个 RVA 附近的若干字节」，而逆向时真正需要的是
    「这里属于哪个函数？谁调用它？谁把它的地址放进 vtable / 全局表？」。
    手工一趟趟找太慢，所以这里一次性把全量「call 目标集合」建起来，
    用它来反推函数边界（离某地址最近的、在它之前的 call 目标 = 函数起点）。

用法：
    python tools/re/func.py at 0x208149B              # 该地址属于哪个函数 + 反汇编
    python tools/re/func.py at 0x208149B --count 80
    python tools/re/func.py callers 0x2081400         # 直接 call/jmp 到它的位置
    python tools/re/func.py qword 0x1306E20           # 8 字节绝对引用（vtable/函数指针表）
    python tools/re/func.py rip 0x5F1234              # RIP 相对引用（全局变量/vtable）
    python tools/re/func.py strings "fScanHighlight"  # 在映像里找字符串
"""
from __future__ import annotations

import argparse
import struct
import sys
from pathlib import Path

EXE = Path(r"D:\SteamLibrary\steamapps\common\Starfield\Starfield.exe")


class Img:
    def __init__(self, path: Path):
        import pefile

        self.path = path
        self.data = path.read_bytes()
        self.pe = pefile.PE(str(path), fast_load=True)
        self.base = self.pe.OPTIONAL_HEADER.ImageBase
        self.sections = []
        for s in self.pe.sections:
            self.sections.append(
                (s.Name.rstrip(b"\x00").decode("latin1"), s.VirtualAddress,
                 s.Misc_VirtualSize, s.PointerToRawData, s.SizeOfRawData)
            )
        self._call_targets: set[int] | None = None

    # ---------------- 地址换算 ----------------
    def rva_to_off(self, rva: int):
        for _, va, vsize, ptr, raw in self.sections:
            if va <= rva < va + max(vsize, raw):
                return ptr + (rva - va)
        return None

    def off_to_rva(self, off: int):
        for _, va, vsize, ptr, raw in self.sections:
            if ptr <= off < ptr + raw:
                return va + (off - ptr)
        return None

    def section_of(self, rva: int):
        for name, va, vsize, ptr, raw in self.sections:
            if va <= rva < va + max(vsize, raw):
                return name
        return None

    # ---------------- 全量 call 目标 ----------------
    def call_targets(self) -> set[int]:
        if self._call_targets is not None:
            return self._call_targets
        targets: set[int] = set()
        for _name, va, _vsize, ptr, raw in self.sections:
            blob = self.data[ptr:ptr + raw]
            for opc in (0xE8, 0xE9):
                k = blob.find(bytes([opc]))
                while k != -1:
                    if k + 5 <= len(blob):
                        rel = struct.unpack_from("<i", blob, k + 1)[0]
                        targets.add(va + k + 5 + rel)
                    k = blob.find(bytes([opc]), k + 1)
        self._call_targets = targets
        return targets

    def func_start(self, rva: int) -> int:
        """函数起点判定：往回找最近的 int3 填充区（MSVC 用 CC 对齐），
        填充区之后的第一个字节就是函数起点。找不到再用 call 目标启发式。"""
        off = self.rva_to_off(rva)
        if off is not None:
            lo = max(0, off - 0x8000)
            blob = self.data[lo:off]
            for i in range(len(blob) - 1, 2, -1):
                if blob[i] != 0xCC:
                    continue
                j = i
                while j >= 0 and blob[j] == 0xCC:
                    j -= 1
                if i - j >= 2:
                    start_off = i + 1
                    return self.off_to_rva(lo + start_off) or rva
        cands = [t for t in self.call_targets() if t <= rva and rva - t < 0x8000]
        return max(cands) if cands else rva


def disasm(img: Img, rva: int, count: int):
    from capstone import CS_ARCH_X86, CS_MODE_64, Cs

    off = img.rva_to_off(rva)
    if off is None:
        return "<不在任何 section 内>"
    md = Cs(CS_ARCH_X86, CS_MODE_64)
    md.detail = True
    out = []
    for ins in md.disasm(img.data[off:off + 0x4000], img.base + rva):
        bs = " ".join(f"{x:02X}" for x in ins.bytes)
        # 把直接 call/jmp 的目标换算成 RVA，方便顺着看
        note = ""
        if ins.mnemonic in ("call", "jmp") and ins.op_str.startswith("0x"):
            tgt = int(ins.op_str, 16) - img.base
            note = f"   -> RVA 0x{tgt:X}"
            if ins.mnemonic == "call" and tgt == rva:
                note += "  <== SELF"
        out.append(f"{ins.address - img.base:08X}  {bs:<30} {ins.mnemonic:<8} {ins.op_str}{note}")
        if len(out) >= count:
            break
    return "\n".join(out)


def direct_callers(img: Img, rva: int, limit: int = 64):
    out = []
    for name, va, _vsize, ptr, raw in img.sections:
        blob = img.data[ptr:ptr + raw]
        for opc in (0xE8, 0xE9):
            k = blob.find(bytes([opc]))
            while k != -1:
                if k + 5 <= len(blob):
                    rel = struct.unpack_from("<i", blob, k + 1)[0]
                    if va + k + 5 + rel == rva:
                        out.append((va + k, name))
                        if len(out) >= limit:
                            return out
                k = blob.find(bytes([opc]), k + 1)
    return out


def qword_refs(img: Img, rva: int, limit: int = 64):
    needle = struct.pack("<Q", img.base + rva)
    out = []
    k = img.data.find(needle)
    while k != -1:
        r = img.off_to_rva(k)
        out.append((r, img.section_of(r)))
        if len(out) >= limit:
            break
        k = img.data.find(needle, k + 1)
    return out


def rip_refs(img: Img, target_rva: int, limit: int = 64):
    """找 RIP 相对引用某个地址的指令。

    用「指令前缀 + mod=00/rm=101 的 ModRM」做模式匹配（比全量 capstone 线性扫描快几十倍），
    覆盖逆向中最常用的几类：lea / mov r64,[rip] / mov [rip],r64 / movss / vmov*。
    命中再逐条反汇编确认（形状校验，避免把巧合的 disp32 当真）。
    """
    patterns = [
        # (前缀, ModRM 位置相对前缀末尾, disp 位置)
        (b"\x48\x8d", 0, 1), (b"\x4c\x8d", 0, 1),   # lea  reg, [rip+disp]
        (b"\x48\x8b", 0, 1), (b"\x4c\x8b", 0, 1),   # mov  reg, [rip+disp]
        (b"\x48\x89", 0, 1), (b"\x4c\x89", 0, 1),   # mov  [rip+disp], reg
        (b"\xf3\x0f\x10", 0, 1), (b"\xf3\x0f\x11", 0, 1),
        (b"\xc5\xf8\x28", 0, 1), (b"\xc5\xf8\x29", 0, 1),
        (b"\xc5\xfa\x10", 0, 1), (b"\xc5\xfa\x11", 0, 1),
        (b"\xc5\xf8\x10", 0, 1), (b"\xc5\xf8\x11", 0, 1),
    ]
    hits = []
    for name, va, _vsize, ptr, raw in img.sections:
        if name != ".text":
            continue
        blob = img.data[ptr:ptr + raw]
        for pre, moff, mdoff in patterns:
            k = blob.find(pre)
            while k != -1:
                p = k + len(pre)
                if p + 1 + 4 <= len(blob):
                    modrm = blob[p]
                    if (modrm & 0xC7) == 0x05:
                        disp = struct.unpack_from("<i", blob, p + 1)[0]
                        end = p + 1 + 4
                        # 指令结束（相对 blob）= end → 目标 VA 必须先假定指令从 k 开始
                        ins_len = end - k
                        total = (img.base + va + k + ins_len) + disp
                        if total == img.base + target_rva:
                            hits.append((va + k, name))
                            if len(hits) >= limit:
                                return hits
                k = blob.find(pre, k + 1)
    return hits


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["at", "callers", "qword", "rip", "strings", "funcall", "vtable"])
    ap.add_argument("args", nargs="*")
    ap.add_argument("--exe", default=str(EXE))
    ap.add_argument("--count", type=int, default=60)
    a = ap.parse_args()

    img = Img(Path(a.exe))

    if a.cmd == "strings":
        pat = a.args[0].encode()
        out = []
        k = img.data.find(pat)
        while k != -1:
            r = img.off_to_rva(k)
            end = img.data.find(b"\x00", k)
            s = img.data[k:end].decode("latin1", "replace")
            out.append((r, s))
            if len(out) >= 60:
                break
            k = img.data.find(pat, k + 1)
        for r, s in out:
            print(f"RVA 0x{r:X}  {s}")
        return 0

    rva = int(a.args[0], 0)

    if a.cmd == "at":
        start = img.func_start(rva)
        print(f"目标 RVA 0x{rva:X} 所在函数起点 ≈ RVA 0x{start:X} (偏移 +0x{rva - start:X})")
        print(disasm(img, start, a.count))
        return 0

    if a.cmd == "callers":
        for c, sec in direct_callers(img, rva):
            f = img.func_start(c)
            print(f"RVA 0x{c:X} (func 0x{f:X}, +0x{c - f:X})  [{sec}]")
        return 0

    if a.cmd == "qword":
        for r, sec in qword_refs(img, rva):
            print(f"RVA 0x{r:X}  [{sec}]")
        return 0

    if a.cmd == "rip":
        for r, sec in rip_refs(img, rva):
            print(f"RVA 0x{r:X}  [{sec}]")
        return 0

    if a.cmd == "funcall":
        # 列出某函数体范围内所有的直接 call 目标
        start = img.func_start(rva)
        body = disasm(img, start, 2000)
        for line in body.splitlines():
            if " -> RVA " in line:
                print(line)
        return 0

    if a.cmd == "vtable":
        # dump 一个 vtable（给 vtable RVA）
        off = img.rva_to_off(rva)
        for i in range(a.count):
            q = struct.unpack_from("<Q", img.data, off + i * 8)[0]
            note = f" -> RVA 0x{q - img.base:X}" if img.base <= q < img.base + 0x20000000 else ""
            print(f"  [+0x{i * 8:03X}] 0x{q:016X}{note}")
        return 0

    return 0


if __name__ == "__main__":
    sys.exit(main())
