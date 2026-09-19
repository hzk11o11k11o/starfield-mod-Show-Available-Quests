"""极简 minidump 解析器（无依赖），用于定位 Starfield 崩溃现场。

用法：
    python minidump.py <a.dmp> [b.dmp ...]
    python minidump.py --all          # 自动分析 %LOCALAPPDATA%\\CrashDumps 下最新的几个

输出：
  · 异常码 / 异常地址，以及该地址落在哪个模块（关键：是不是 SHF_Highlight.dll）
  · 故障线程的寄存器（RIP / RSP / RBP）与栈回溯（在栈上找落在已知模块内的返回地址）
  · 所有线程的概览（看是不是渲染线程/主线程）
"""
from __future__ import annotations

import glob
import os
import struct
import sys

# --------------------------------------------------------------------------
# minidump 结构（全部按 little-endian 手工解析，不需要 dbghelp）
# --------------------------------------------------------------------------
MDMP_MAGIC = 0x504D444D  # 'MDMP'

ST_THREAD_LIST = 3
ST_MODULE_LIST = 4
ST_MEMORY_LIST = 5
ST_EXCEPTION = 6
ST_SYSTEM_INFO = 7
ST_MEMORY64_LIST = 9
ST_THREAD_INFO_LIST = 16

EXC_NAMES = {
    0xC0000005: "ACCESS_VIOLATION",
    0xC000001D: "ILLEGAL_INSTRUCTION",
    0xC0000025: "NONCONTINUABLE_EXCEPTION",
    0xC000008C: "ARRAY_BOUNDS_EXCEEDED",
    0xC0000094: "INTEGER_DIVIDE_BY_ZERO",
    0xC0000096: "PRIV_INSTRUCTION",
    0xC00000FD: "STACK_OVERFLOW",
    0xC0000374: "HEAP_CORRUPTION",
    0xC0000409: "STACK_BUFFER_OVERRUN / FAIL_FAST",
    0x80000003: "BREAKPOINT",
}

MODULE_SIZE = 108  # sizeof(MINIDUMP_MODULE)


class Dump:
    def __init__(self, path: str):
        with open(path, "rb") as f:
            self.buf = f.read()
        self.path = path
        self.streams: dict[int, tuple[int, int]] = {}
        self._parse_header()

    def _u32(self, off: int) -> int:
        return struct.unpack_from("<I", self.buf, off)[0]

    def _u64(self, off: int) -> int:
        return struct.unpack_from("<Q", self.buf, off)[0]

    def _parse_header(self) -> None:
        sig = self._u32(0)
        if sig != MDMP_MAGIC:
            raise ValueError(f"{self.path}: 不是 minidump（magic=0x{sig:08X}）")
        self.n_streams = self._u32(8)
        dir_rva = self._u32(12)
        self.timestamp = self._u32(20)
        for i in range(self.n_streams):
            o = dir_rva + i * 12
            stype = self._u32(o)
            size = self._u32(o + 4)
            rva = self._u32(o + 8)
            self.streams[stype] = (size, rva)

    def _string(self, rva: int) -> str:
        n = self._u32(rva)
        raw = self.buf[rva + 4 : rva + 4 + n]
        try:
            return raw.decode("utf-16-le", "replace")
        except Exception:
            return "<bad string>"

    # ---------------------------------------------------------------- modules
    def modules(self) -> list[tuple[int, int, str]]:
        out = []
        if ST_MODULE_LIST not in self.streams:
            return out
        _, rva = self.streams[ST_MODULE_LIST]
        n = self._u32(rva)
        for i in range(n):
            o = rva + 4 + i * MODULE_SIZE
            base = self._u64(o)          # BaseOfImage
            size = self._u32(o + 8)      # SizeOfImage
            # o+12 CheckSum / o+16 TimeDateStamp / o+20 ModuleNameRva
            name_rva = self._u32(o + 20)
            out.append((base, size, self._string(name_rva)))
        return out

    # -------------------------------------------------------------- exception
    def exception(self):
        if ST_EXCEPTION not in self.streams:
            return None
        _, rva = self.streams[ST_EXCEPTION]
        tid = self._u32(rva)
        code = self._u32(rva + 8)
        addr = self._u64(rva + 24)
        nparam = self._u32(rva + 32)
        params = [self._u64(rva + 40 + i * 8) for i in range(min(nparam, 15))]
        ctx = self._u32(rva + 4 + 8 + 32 + 8 * nparam)  # ThreadContext.Rva
        return {"tid": tid, "code": code, "addr": addr, "params": params, "ctx_rva": ctx}

    # ----------------------------------------------------------------- memory
    def memory_ranges(self) -> list[tuple[int, int, int]]:
        """返回 [(start, size, file_off)]，file_off 指向文件里该段内存的原始字节。"""
        out = []
        if ST_MEMORY64_LIST in self.streams:
            _, rva = self.streams[ST_MEMORY64_LIST]
            n = self._u64(rva)
            base_off = self._u64(rva + 8)
            o = rva + 16
            for i in range(n):
                start = self._u64(o)
                size = self._u64(o + 8)
                out.append((start, size, base_off))
                base_off += size
                o += 16
        elif ST_MEMORY_LIST in self.streams:
            _, rva = self.streams[ST_MEMORY_LIST]
            n = self._u32(rva)
            for i in range(n):
                o = rva + 4 + i * 16
                start = self._u64(o)
                size = self._u32(o + 8)
                off = self._u32(o + 12)
                out.append((start, size, off))
        return out

    def read_mem(self, addr: int, n: int) -> bytes | None:
        for start, size, off in self.memory_ranges():
            if start <= addr and addr + n <= start + size:
                fo = off + (addr - start)
                return self.buf[fo : fo + n]
        return None

    # ---------------------------------------------------------------- threads
    def threads(self) -> list[dict]:
        out = []
        if ST_THREAD_LIST not in self.streams:
            return out
        _, rva = self.streams[ST_THREAD_LIST]
        n = self._u32(rva)
        for i in range(n):
            # MINIDUMP_THREAD (48 bytes):
            #   0 ThreadId / 4 SuspendCount / 8 PriorityClass / 12 Priority / 16 Teb(8)
            #   24 Stack{ Start(8) Size(4) Rva(4) } / 40 ThreadContext{ DataSize(4) Rva(4) }
            o = rva + 4 + i * 48
            tid = self._u32(o)
            stack_start = self._u64(o + 24)
            stack_size = self._u32(o + 32)
            ctx_rva = self._u32(o + 44)  # ★ LocationDescriptor 的 Rva 在 +4
            out.append({"tid": tid, "stack": (stack_start, stack_size), "ctx_rva": ctx_rva})
        return out

    @staticmethod
    def ctx_regs(data: bytes) -> dict:
        if len(data) < 0x100:
            return {}
        g = lambda off: struct.unpack_from("<Q", data, off)[0]
        return {
            "Rax": g(0x78), "Rcx": g(0x80), "Rdx": g(0x88), "Rbx": g(0x90),
            "Rsp": g(0x98), "Rbp": g(0xA0), "Rsi": g(0xA8), "Rdi": g(0xB0),
            "R8": g(0xB8), "R9": g(0xC0), "R10": g(0xC8), "R11": g(0xD0),
            "R12": g(0xD8), "R13": g(0xE0), "R14": g(0xE8), "R15": g(0xF0),
            "Rip": g(0xF8),
        }


def module_of(addr: int, mods: list[tuple[int, int, str]]):
    for base, size, name in mods:
        if base <= addr < base + size:
            return name, base
    return None, None


def analyze(path: str) -> None:
    print("=" * 100)
    print(f"文件：{path}")
    try:
        d = Dump(path)
    except Exception as e:
        print(f"  !! 解析失败：{e}")
        return

    mods = d.modules()
    print(f"  streams={sorted(d.streams.keys())}  模块数={len(mods)}")

    exc = d.exception()
    if exc is None:
        print("  (没有 ExceptionStream —— 可能是手动 dump 或非崩溃转储)")
    else:
        name = EXC_NAMES.get(exc["code"], f"0x{exc['code']:08X}")
        mname, mbase = module_of(exc["addr"], mods)
        print(f"  ★ 异常：{name}")
        print(f"    ThreadId = {exc['tid']}")
        print(f"    Address  = 0x{exc['addr']:016X}   <- 落在 {mname or '<未知模块>'} "
              f"{'(+0x%X)' % (exc['addr'] - mbase) if mbase else ''}")
        if exc["params"]:
            print(f"    Params   = " + ", ".join(f"0x{p:X}" for p in exc["params"]))

    # 各线程概览 + 故障线程的栈回溯
    ths = d.threads()
    print(f"  线程数 = {len(ths)}")
    for t in ths:
        ctx_raw = d.read_mem_ctx(t["ctx_rva"])
        regs = d.ctx_regs(ctx_raw) if ctx_raw else {}
        if not regs:
            continue
        rip_mod, rip_base = module_of(regs["Rip"], mods)
        mark = " ★崩溃线程" if exc and t["tid"] == exc["tid"] else ""
        print(f"    tid={t['tid']:<7} RIP=0x{regs['Rip']:016X} "
              f"[{rip_mod or '?'}{' +0x%X' % (regs['Rip'] - rip_base) if rip_base else ''}]"
              f"  RSP=0x{regs['Rsp']:016X}{mark}")

    if exc is None:
        return

    target = next((t for t in ths if t["tid"] == exc["tid"]), None)
    if target is None:
        print("  (找不到故障线程)")
        return

    ctx_raw = d.read_mem_ctx(target["ctx_rva"])
    regs = d.ctx_regs(ctx_raw) if ctx_raw else {}
    if not regs:
        print("  (没有故障线程上下文)")
        return

    print("\n  ---- 故障线程寄存器 ----")
    print("    " + "  ".join(f"{k}=0x{v:016X}" for k, v in regs.items() if k != "Rip"))
    for k in ("Rcx", "Rdx", "R8", "R9"):
        v = regs[k]
        m, b = module_of(v, mods)
        if m:
            print(f"      （{k} 指向 {m}+0x{v - b:X}）")

    # 栈回溯：RSP 往上扫，找落在已知模块内的 8 字节值（宽松启发式，够用来定性）
    print("\n  ---- 栈上的返回地址候选（RSP 向上 0x800）----")
    base_rsp = regs["Rsp"]
    blob = d.read_mem(base_rsp, 0x800)
    if blob is None:
        print("    (栈内存不在转储里)")
        return
    for i in range(0, len(blob) - 8, 8):
        v = struct.unpack_from("<Q", blob, i)[0]
        m, b = module_of(v, mods)
        if m:
            print(f"    [RSP+0x{i:03X}] 0x{v:016X}  {m}+0x{v - b:X}")


# MINIDUMP_LOCATION_DESCRIPTOR 里的 ThreadContext 指向文件偏移（不是内存地址）
def _read_mem_ctx(self, rva: int) -> bytes | None:
    if not rva or rva + 0x100 > len(self.buf):
        return None
    return self.buf[rva : rva + 0x500]


Dump.read_mem_ctx = _read_mem_ctx


def main() -> int:
    args = sys.argv[1:]
    if not args or args[0] == "--all":
        # 【v32 教训】2026-09-15 20:17 那次崩溃**没有**进 CrashDumps —— 它在
        # WeMod(Wand) 的目录里。三个目录都要看，否则会得出「这次没崩」的错误结论。
        base = os.environ.get("LOCALAPPDATA", "")
        files: list[str] = []
        for sub in ("CrashDumps", r"Wand\dumps\crash", r"Temp\Dumps"):
            files += glob.glob(os.path.join(base, sub, "*.dmp"))
        files.sort(key=os.path.getmtime, reverse=True)
        if not files:
            print(f"没找到转储（看了 {base} 下的 CrashDumps / Wand\\dumps\\crash / Temp\\Dumps）")
            return 1
        args = files[: int(os.environ.get("N", "3"))]
        print(f"分析最新的 {len(args)} 个转储：\n  " + "\n  ".join(args) + "\n")
    for p in args:
        try:
            analyze(p)
        except Exception as e:
            print(f"  !! {p}: {type(e).__name__}: {e}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
