"""Disassemble a chunk of Starfield.exe at a given RVA (crash site analysis)."""
import struct
import sys

import capstone


class PEFile:
    def __init__(self, path):
        with open(path, 'rb') as f:
            self.f = f
            self.buf = f.read()

    def sections(self):
        b = self.buf
        e_lfanew = struct.unpack_from('<I', b, 0x3C)[0]
        assert b[e_lfanew:e_lfanew + 4] == b'PE\0\0'
        coff = e_lfanew + 4
        nsec, = struct.unpack_from('<H', b, coff + 2)
        opt_size, = struct.unpack_from('<H', b, coff + 16)
        opt = coff + 20
        sec = opt + opt_size
        out = []
        for i in range(nsec):
            o = sec + i * 40
            name = b[o:o + 8].rstrip(b'\0').decode('latin1')
            vsize, vaddr, rawsize, rawptr = struct.unpack_from('<IIII', b, o + 8)
            out.append((name, vaddr, vsize, rawptr, rawsize))
        return out

    def rva_to_off(self, rva):
        for _, vaddr, vsize, rawptr, rawsize in self.sections():
            if vaddr <= rva < vaddr + max(vsize, rawsize):
                return rawptr + (rva - vaddr)
        return None


def main(exe, rva, before=0x60, after=0x60):
    pe = PEFile(exe)
    off = pe.rva_to_off(rva - before)
    data = pe.buf[off:off + before + after]
    md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_64)
    md.detail = True
    base = rva - before
    for insn in md.disasm(data, base):
        mark = '  <== CRASH' if insn.address <= rva < insn.address + insn.size else ''
        print('%08X  %-24s %s %s%s' % (insn.address, insn.bytes.hex(), insn.mnemonic, insn.op_str, mark))


if __name__ == '__main__':
    main(sys.argv[1], int(sys.argv[2], 16),
         int(sys.argv[3], 16) if len(sys.argv) > 3 else 0x60,
         int(sys.argv[4], 16) if len(sys.argv) > 4 else 0x60)
