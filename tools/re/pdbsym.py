"""Resolve an address (module base + RVA) to a symbol + source line using a PDB."""
import ctypes
import ctypes.wintypes as w
import sys

SYMOPT_LOAD_LINES = 0x00000010
SYMOPT_UNDNAME = 0x00000002

UNDNAME_COMPLETE = 0x0000


class SYMBOL_INFO(ctypes.Structure):
    _fields_ = [
        ('SizeOfStruct', w.ULONG),
        ('TypeIndex', w.ULONG),
        ('Reserved', ctypes.c_ulonglong * 2),
        ('Index', w.ULONG),
        ('Size', w.ULONG),
        ('ModBase', ctypes.c_ulonglong),
        ('Flags', w.ULONG),
        ('Value', ctypes.c_ulonglong),
        ('Address', ctypes.c_ulonglong),
        ('Register', w.ULONG),
        ('Scope', w.ULONG),
        ('Tag', w.ULONG),
        ('NameLen', w.ULONG),
        ('MaxNameLen', w.ULONG),
        ('Name', ctypes.c_char * 2048),
    ]


class IMAGEHLP_LINE64(ctypes.Structure):
    _fields_ = [
        ('SizeOfStruct', w.DWORD),
        ('Key', ctypes.c_void_p),
        ('LineNumber', w.DWORD),
        ('FileName', ctypes.c_char_p),
        ('Address', ctypes.c_ulonglong),
    ]


def main(dll_path, base, rva):
    dbghelp = ctypes.WinDLL('dbghelp')
    h = ctypes.c_void_p(0x1234ABCD)
    dbghelp.SymSetOptions(SYMOPT_LOAD_LINES | SYMOPT_UNDNAME)
    dbghelp.SymInitialize(h, None, False)

    mod = dbghelp.SymLoadModuleEx(h, None, dll_path.encode(), None,
                                  ctypes.c_ulonglong(base), 0x8F000, None, 0)
    print('SymLoadModuleEx ->', hex(mod or 0))
    if not mod:
        print('last error:', ctypes.get_last_error())
        return

    addr = base + rva
    disp = ctypes.c_ulonglong(0)
    sym = SYMBOL_INFO()
    sym.SizeOfStruct = ctypes.sizeof(SYMBOL_INFO)
    sym.MaxNameLen = 2000
    ok = dbghelp.SymFromAddr(h, ctypes.c_ulonglong(addr), ctypes.byref(disp), ctypes.byref(sym))
    if ok:
        print('SYMBOL : %s + 0x%X' % (sym.Name.decode('utf-8', 'replace'), disp.value))
        try:
            print('MANGLED: %s' % dbghelp.UnDecorateSymbolName(
                sym.Name, ctypes.create_string_buffer(2048), 2048, UNDNAME_COMPLETE) and
                ctypes.create_string_buffer(2048).value.decode('utf-8', 'replace'))
        except Exception:
            pass
    else:
        print('SymFromAddr failed err=%d' % ctypes.get_last_error())

    line = IMAGEHLP_LINE64()
    line.SizeOfStruct = ctypes.sizeof(IMAGEHLP_LINE64)
    d2 = ctypes.c_ulonglong(0)
    if dbghelp.SymGetLineFromAddr64(h, ctypes.c_ulonglong(addr), ctypes.byref(d2), ctypes.byref(line)):
        print('SOURCE : %s : %d  (+0x%X)' % (line.FileName.decode('utf-8', 'replace'),
                                             line.LineNumber, d2.value))
    else:
        print('no line info')


if __name__ == '__main__':
    main(sys.argv[1], int(sys.argv[2], 16), int(sys.argv[3], 16))
