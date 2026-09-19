"""Minimal minidump reader: module list, exception record, stack scan from RSP."""
import struct
import sys

STREAM_THREAD_LIST = 3
STREAM_MODULE_LIST = 4
STREAM_MEMORY_LIST = 5
STREAM_EXCEPTION = 6
STREAM_MEMORY64_LIST = 9


class Dump:
    def __init__(self, path):
        with open(path, 'rb') as f:
            self.buf = f.read()
        self.streams = {}
        sig, ver, n, dir_rva, chk, ts, flags = struct.unpack_from('<IIIIIIQ', self.buf, 0)
        assert sig == 0x504D444D, 'not a minidump'
        self.timestamp = ts
        for i in range(n):
            st, size, rva = struct.unpack_from('<III', self.buf, dir_rva + i * 12)
            self.streams[st] = (rva, size)

    def modules(self):
        rva, _ = self.streams[STREAM_MODULE_LIST]
        cnt = struct.unpack_from('<I', self.buf, rva)[0]
        out = []
        off = rva + 4
        for _ in range(cnt):
            base, size, chk, tds, name_rva = struct.unpack_from('<QIIII', self.buf, off)
            namelen = struct.unpack_from('<I', self.buf, name_rva)[0]
            raw = self.buf[name_rva + 4:name_rva + 4 + namelen]
            out.append((base, size, raw.decode('utf-16-le', 'replace'), tds))
            off += 108
        return out

    def exception(self):
        rva, _ = self.streams[STREAM_EXCEPTION]
        tid = struct.unpack_from('<I', self.buf, rva)[0]
        er = rva + 8
        code, eflags, erec, addr, nparam = struct.unpack_from('<IIQQI', self.buf, er)
        params = struct.unpack_from('<15Q', self.buf, er + 32)
        ctx_size, ctx_rva = struct.unpack_from('<II', self.buf, er + 152)
        return dict(tid=tid, code=code, addr=addr, nparam=nparam, params=params,
                    ctx_rva=ctx_rva, ctx_size=ctx_size)

    def threads(self):
        rva, _ = self.streams[STREAM_THREAD_LIST]
        cnt = struct.unpack_from('<I', self.buf, rva)[0]
        out = []
        off = rva + 4
        for _ in range(cnt):
            tid = struct.unpack_from('<I', self.buf, off)[0]
            stack_start = struct.unpack_from('<Q', self.buf, off + 24)[0]
            stack_size, stack_rva = struct.unpack_from('<II', self.buf, off + 32)
            ctx_size, ctx_rva = struct.unpack_from('<II', self.buf, off + 40)
            out.append(dict(tid=tid, stack_start=stack_start, stack_size=stack_size,
                            stack_rva=stack_rva, ctx_size=ctx_size, ctx_rva=ctx_rva))
            off += 48
        return out

    def ctx_regs(self, ctx_rva, ctx_size):
        b = self.buf
        if ctx_size < 0x120 or ctx_rva + 0x120 > len(b):
            return None
        regs = {
            'rax': 0x78, 'rcx': 0x80, 'rdx': 0x88, 'rbx': 0x90,
            'rsp': 0x98, 'rbp': 0xA0, 'rsi': 0xA8, 'rdi': 0xB0,
            'r8': 0xB8, 'r9': 0xC0, 'r10': 0xC8, 'r11': 0xD0,
            'r12': 0xD8, 'r13': 0xE0, 'r14': 0xE8, 'r15': 0xF0,
            'rip': 0xF8,
        }
        return {k: struct.unpack_from('<Q', b, ctx_rva + v)[0] for k, v in regs.items()}


CODE_NAMES = {
    0xC0000005: 'ACCESS_VIOLATION',
    0xC0000374: 'HEAP_CORRUPTION',
    0xC0000409: 'STACK_BUFFER_OVERRUN',
    0xC00000FD: 'STACK_OVERFLOW',
    0x80000003: 'BREAKPOINT',
    0xE06D7363: 'C++ EXCEPTION',
}


def main(path):
    d = Dump(path)
    mods = d.modules()
    ranges = sorted((m[0], m[0] + m[1], m[2]) for m in mods)

    def owner(addr):
        for lo, hi, name in ranges:
            if lo <= addr < hi:
                short = name.split('\\')[-1]
                return f'{short}+0x{addr - lo:X}'
        return None

    print('=' * 78)
    print('FILE    :', path)
    print('MODULES :', len(mods))
    for base, size, name, _ in sorted(mods, key=lambda m: m[0]):
        if 'sas_' in name.lower() or 'starfield.exe' in name.lower() or 'sfse' in name.lower() \
           or 'usvfs' in name.lower() or 'trainer' in name.lower() or 'wand' in name.lower() \
           or 'obs' in name.lower() or 'highlight' in name.lower():
            print(f'  {base:016X} {size:>9X}  {name}')

    ex = d.exception()
    regs = d.ctx_regs(ex['ctx_rva'], ex['ctx_size'])
    print('-' * 78)
    print('EXCEPTION tid=%X  code=%08X (%s)' % (ex['tid'], ex['code'],
                                               CODE_NAMES.get(ex['code'], '?')))
    print('EXCEPTION addr = %016X -> %s' % (ex['addr'], owner(ex['addr'])))
    print('EXCEPTION params =', [hex(p) for p in ex['params'][:ex['nparam']]])
    for p in ex['params'][:ex['nparam']]:
        o = owner(p)
        if o:
            print('    param -> ', o)
    if regs:
        print('REGS: ' + '  '.join('%s=%016X' % (k.upper(), v) for k, v in regs.items()))
        for k in ('rcx', 'rdx', 'rax', 'r8', 'r9', 'rbx', 'rsi', 'rdi'):
            o = owner(regs[k])
            if o:
                print('    %s -> %s' % (k.upper(), o))
    else:
        print('REGS: <context unavailable, size=%X>' % ex['ctx_size'])

    th = next((t for t in d.threads() if t['tid'] == ex['tid']), None)
    if not th or not regs:
        return
    print('-' * 78)
    print('STACK walk (faulting thread, captured %d KB, base %016X)' %
          (th['stack_size'] // 1024, th['stack_start']))
    rsp = regs['rsp']
    if not (th['stack_start'] <= rsp <= th['stack_start'] + th['stack_size']):
        print('  RSP %016X outside captured stack; scanning whole region' % rsp)
        start = 0
    else:
        start = (rsp - th['stack_start']) & ~7
    end = min(th['stack_size'], start + 0x4000)
    for i in range(start // 8, end // 8):
        v = struct.unpack_from('<Q', d.buf, th['stack_rva'] + i * 8)[0]
        o = owner(v)
        if o:
            print('  rsp+%05X  %016X  %s' % (i * 8 - start, v, o))


if __name__ == '__main__':
    main(sys.argv[1])
