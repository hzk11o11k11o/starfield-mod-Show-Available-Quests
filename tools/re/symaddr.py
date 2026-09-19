"""用 dbghelp 把 SHF_Highlight.dll 的 RVA 解析成「函数+偏移」。

用法：
    python symaddr.py 0x2F98A 0x1F710 0x8E758 ...
    python symaddr.py --from-dump            # 自动从最新的崩溃转储里提取 SHF_Highlight 的地址并解析

依赖：同级（或 --dll 指定）的 SHF_Highlight.dll + SHF_Highlight.pdb。
"""
from __future__ import annotations

import argparse
import ctypes
import glob
import os
import sys
from ctypes import wintypes

DEFAULT_DLL = (
    r"D:\Mod Organizer 2\starfield_mods\mods\Starfield Highlight Items (SFSE)"
    r"\SFSE\Plugins\SHF_Highlight.dll"
)

# 假基址：把模块加载到任意一个不冲突的地址，之后用 base+rva 查询即可
FAKE_BASE = 0x10000000


class SYMBOL_INFO(ctypes.Structure):
    _fields_ = [
        ("SizeOfStruct", wintypes.ULONG),
        ("TypeIndex", wintypes.ULONG),
        ("Reserved", ctypes.c_ulonglong * 2),
        ("Index", wintypes.ULONG),
        ("Size", wintypes.ULONG),
        ("ModBase", ctypes.c_ulonglong),
        ("Flags", wintypes.ULONG),
        ("Value", ctypes.c_ulonglong),
        ("Address", ctypes.c_ulonglong),
        ("Register", ctypes.c_ulonglong),
        ("Scope", wintypes.ULONG),
        ("Tag", wintypes.ULONG),
        ("NameLen", wintypes.ULONG),
        ("MaxNameLen", wintypes.ULONG),
        ("Name", ctypes.c_char * 512),
    ]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("addrs", nargs="*", help="RVA（0x 开头）")
    ap.add_argument("--dll", default=DEFAULT_DLL)
    ap.add_argument("--from-dump", action="store_true")
    a = ap.parse_args()

    dll = a.dll
    if not os.path.exists(dll):
        print(f"找不到 DLL：{dll}")
        return 1
    pdb = os.path.splitext(dll)[0] + ".pdb"
    print(f"DLL : {dll}  ({os.path.getsize(dll)} B)")
    print(f"PDB : {pdb}  ({'存在' if os.path.exists(pdb) else '!! 缺失'})\n")

    addrs = [int(x, 0) for x in a.addrs]
    if a.from_dump or not addrs:
        addrs = extract_from_dumps() or addrs

    dbg = ctypes.WinDLL("dbghelp")
    # SYMOPT_UNDNAME(0x02) | SYMOPT_DEFERRED_LOADS(0x04) | SYMOPT_LOAD_LINES(0x10)
    dbg.SymSetOptions(0x02 | 0x04 | 0x10)
    hproc = ctypes.windll.kernel32.GetCurrentProcess()
    dbg.SymInitialize.argtypes = [wintypes.HANDLE, ctypes.c_char_p, wintypes.BOOL]
    if not dbg.SymInitialize(hproc, os.path.dirname(dll).encode(), False):
        print(f"SymInitialize 失败，err={ctypes.GetLastError()}")
        return 1

    dbg.SymLoadModuleEx.argtypes = [
        wintypes.HANDLE, wintypes.HANDLE, ctypes.c_char_p, ctypes.c_char_p,
        ctypes.c_ulonglong, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD,
    ]
    dbg.SymLoadModuleEx.restype = ctypes.c_ulonglong
    base = dbg.SymLoadModuleEx(
        hproc, None, dll.encode(), None, FAKE_BASE, os.path.getsize(dll), None, 0
    )
    if not base:
        print(f"SymLoadModuleEx 失败，err={ctypes.GetLastError()}")
        return 1
    print(f"已加载模块，base=0x{base:X}\n")

    # 【实测】SymFromAddr 在这个 PDB 上返回成功但 NameLen=0（只能拿到相对偏移），
    #   所以改用 SymEnumSymbols 把符号全枚举出来，再自己按地址区间查找。
    syms: list[tuple[int, int, str]] = []
    CALLBACK = ctypes.WINFUNCTYPE(
        wintypes.BOOL, ctypes.POINTER(SYMBOL_INFO), wintypes.ULONG, ctypes.c_void_p
    )

    def _cb(pinfo, size, _ctx):
        try:
            s = pinfo.contents
            name = s.Name.decode("utf-8", "replace")
            if name:
                syms.append((s.Address - base, int(size), name))
        except Exception:
            pass
        return True

    dbg.SymEnumSymbols.argtypes = [
        wintypes.HANDLE, ctypes.c_ulonglong, ctypes.c_char_p, CALLBACK, ctypes.c_void_p,
    ]
    dbg.SymEnumSymbols.restype = wintypes.BOOL
    ok_enum = dbg.SymEnumSymbols(hproc, base, b"*", CALLBACK(_cb), None)
    print(f"SymEnumSymbols -> {ok_enum}, 共 {len(syms)} 个符号\n")
    if not syms:
        print("!! 没枚举到任何符号 —— PDB 可能没被加载（检查目录 / _NT_SYMBOL_PATH）")
        return 1

    syms.sort()

    def lookup(rva: int) -> str:
        import bisect as _b
        keys = [s[0] for s in syms]
        i = _b.bisect_right(keys, rva) - 1
        if i < 0:
            return "<超出符号范围>"
        off, size, name = syms[i]
        if size and rva >= off + size:
            return f"{name} +0x{rva - off:X}  (..>{size}B, 跃出符号)"
        return f"{name}  +0x{rva - off:X}"

    for rva in addrs:
        print(f"  0x{rva:<7X}  {lookup(rva)}")

    dbg.SymCleanup(hproc)
    return 0


def _unused_symfromaddr(dbg, hproc, base, addrs):  # noqa: ANN001
    dbg.SymFromAddr.argtypes = [
        wintypes.HANDLE, ctypes.c_ulonglong, ctypes.POINTER(ctypes.c_ulonglong),
        ctypes.POINTER(SYMBOL_INFO),
    ]
    dbg.SymFromAddr.restype = wintypes.BOOL

    for rva in addrs:
        sym = SYMBOL_INFO()
        sym.SizeOfStruct = 88
        sym.MaxNameLen = 511
        disp = ctypes.c_ulonglong(0)
        ok = dbg.SymFromAddr(hproc, base + rva, ctypes.byref(disp), ctypes.byref(sym))
        if ok:
            print(f"  0x{rva:<7X}  {sym.Name.decode(errors='replace')}  +0x{disp.value:X}")
        else:
            print(f"  0x{rva:<7X}  <未找到符号>")

    dbg.SymCleanup(hproc)
    return 0


DUMP_DIRS = (
    "CrashDumps",                      # WER LocalDumps
    r"Wand\dumps\crash",               # WeMod/Wand 自己抓的（v31 实测：真正的崩溃在这里）
    r"Temp\Dumps",
)


def find_newest_dump() -> str | None:
    """在所有已知的转储目录里找最新的一份。

    【v32 教训】2026-09-15 20:17 那次崩溃**没有**落进 `%LOCALAPPDATA%\\CrashDumps\\`
    —— 它在 WeMod(Wand) 自己的目录里：`%LOCALAPPDATA%\\Wand\\dumps\\crash\\`。
    只盯 CrashDumps 会得出「这次没崩」的错误结论。
    """
    base = os.environ.get("LOCALAPPDATA", "")
    files: list[str] = []
    for sub in DUMP_DIRS:
        files += glob.glob(os.path.join(base, sub, "*.dmp"))
    if not files:
        return None
    files.sort(key=os.path.getmtime, reverse=True)
    # 同一次崩溃常常落两份（WeMod 自己的 139MB 全量版 + 1.2MB 精简版）→
    # 取信息最全（最大）的那份，否则连栈都没得扫。
    newest = os.path.getmtime(files[0])
    burst = [f for f in files if newest - os.path.getmtime(f) <= 60]
    return max(burst, key=os.path.getsize)


def check_dump_matches_dll(path: str, mods) -> None:  # noqa: ANN001
    """确认「转储里的 SHF_Highlight.dll」和本地这份 DLL/PDB 是同一个版本。

    【v31 踩过的坑】用旧转储 + 新 PDB 解析，会得到 `IDDB::load_v2` 这类**看似有效
    其实错位**的函数名（浪费了一整轮定位）。这里用 PE 头的 `TimeDateStamp` 比对：
    RVA 只有在两个版本一致时才有意义。
    """
    try:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        from minidump import Dump, MODULE_SIZE, ST_MODULE_LIST
    except Exception:
        return
    dump_ts = None
    dump_size = None
    try:
        import struct as _s
        d = Dump(path)
        if ST_MODULE_LIST not in d.streams:
            return
        _, rva = d.streams[ST_MODULE_LIST]
        n = _s.unpack_from("<I", d.buf, rva)[0]
        for i in range(n):
            o = rva + 4 + i * MODULE_SIZE
            base = _s.unpack_from("<Q", d.buf, o)[0]
            size = _s.unpack_from("<I", d.buf, o + 8)[0]
            ts = _s.unpack_from("<I", d.buf, o + 16)[0]
            name_rva = _s.unpack_from("<I", d.buf, o + 20)[0]
            if "SHF_Highlight" in d._string(name_rva):
                dump_ts, dump_size = ts, size
                break
    except Exception:
        return
    if dump_ts is None:
        return
    try:
        import pefile
        pe = pefile.PE(DEFAULT_DLL)
        local_ts = pe.FILE_HEADER.TimeDateStamp
        local_size = pe.OPTIONAL_HEADER.SizeOfImage
    except Exception:
        return
    tag = "OK" if (dump_ts == local_ts and dump_size == local_size) else "!! 版本不一致"
    print(
        f"版本比对：转储 ts=0x{dump_ts:08X} image={dump_size}  "
        f"本地 ts=0x{local_ts:08X} image={local_size}  -> {tag}"
    )
    if tag != "OK":
        print(
            "  [!] 函数名会错位！请把【当次】的 SHF_Highlight.dll/.pdb 找出来，"
            "再用 --dll 指向它（旧版本可能在回收站 D:\\$RECYCLE.BIN 里）。"
        )


def extract_from_dumps() -> list[int]:
    """从最新的崩溃转储里，抓出所有落在 SHF_Highlight.dll 内的地址（转成 RVA）。"""
    try:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        from minidump import Dump, module_of
    except Exception as e:
        print(f"（导入 minidump 失败：{e}）")
        return []

    path = find_newest_dump()
    if not path:
        print("（没找到崩溃转储）")
        return []
    print(f"从转储提取：{path}")
    dump = Dump(path)
    mods = dump.modules()
    exc = dump.exception()
    check_dump_matches_dll(path, mods)
    out: list[int] = []
    if exc:
        m, b = module_of(exc["addr"], mods)
        if m and "SHF_Highlight" in m:
            out.append(exc["addr"] - b)
    ths = dump.threads()
    if exc:
        t = next((x for x in ths if x["tid"] == exc["tid"]), None)
        if t:
            raw = dump.read_mem_ctx(t["ctx_rva"])
            if raw:
                regs = dump.ctx_regs(raw)
                # 小体积转储（WeMod 的 1.2MB 那份）不含线程上下文/内存 → 跳过栈扫描
                blob = dump.read_mem(regs["Rsp"], 0x800) if regs.get("Rsp") else None
                if blob:
                    import struct as _s
                    for i in range(0, len(blob) - 8, 8):
                        v = _s.unpack_from("<Q", blob, i)[0]
                        m, b = module_of(v, mods)
                        if m and "SHF_Highlight" in m:
                            out.append(v - b)
    return out


if __name__ == "__main__":
    sys.exit(main())
