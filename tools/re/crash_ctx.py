"""读 minidump 的 **ExceptionStream 里的异常现场 context**（真正的故障寄存器）+ 栈回溯。

与 minidump.py 的区别：minidump.py 打印的是线程列表里 dump 时刻的 context
（异常分发后，寄存器已被 ntdll 改写）；本工具读 ExceptionStream 自带的
ThreadContext —— 那才是「访问违例发生那一瞬」的 RIP/RSP/RCX。

用法：
    python crash_ctx.py <a.dmp> [b.dmp ...]
"""
from __future__ import annotations

import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from minidump import Dump, module_of  # noqa: E402


def analyze(path: str) -> None:
    print("=" * 100)
    print(f"文件：{path}")
    d = Dump(path)
    mods = d.modules()

    # ★ 自己解析 ExceptionStream：
    #   stream+0  ThreadId
    #   stream+8  MINIDUMP_EXCEPTION（152 字节）：Code(4) Flags(4) Record(8) Address(8)
    #             NumberParameters(4) pad(4) Information[15](120)
    #   stream+160 ThreadContext（MINIDUMP_LOCATION_DESCRIPTOR：DataSize(4) Rva(4)）
    #   （minidump.py 的 exception() 用错了偏移，这里显式重算。）
    rva = d.streams[6][1]
    u32 = lambda o: struct.unpack_from("<I", d.buf, o)[0]
    u64 = lambda o: struct.unpack_from("<Q", d.buf, o)[0]
    tid = u32(rva)
    erec = rva + 8
    code = u32(erec)
    addr = u64(erec + 16)
    nparam = u32(erec + 24)
    params = [u64(erec + 32 + 8 * i) for i in range(min(nparam, 15))]
    ctx_size = u32(erec + 152)
    ctx_rva = u32(erec + 156)
    print(f"  异常 tid={tid} code=0x{code:08X} addr=0x{addr:016X} "
          f"params={[hex(p) for p in params]}  ctx(size=0x{ctx_size:X} @0x{ctx_rva:X})")

    ctx = d.read_mem_ctx(ctx_rva)
    regs = Dump.ctx_regs(ctx) if ctx else {}
    if not regs:
        print("  (没有异常 context)")
        return

    for k, v in regs.items():
        m, b = module_of(v, mods)
        extra = f"   -> {m}+0x{v - b:X}" if m else ""
        print(f"    {k}=0x{v:016X}{extra}")

    rsp = regs["Rsp"]
    blob = d.read_mem(rsp, 0x1800)
    print("  ---- 异常现场栈上的模块返回地址候选 ----")
    if blob is None:
        print("    (栈内存不在转储里)")
        return
    for i in range(0, len(blob) - 8, 8):
        v = struct.unpack_from("<Q", blob, i)[0]
        m, b = module_of(v, mods)
        if m and ("Starfield" in m or "SFSE" in m or "SAQ" in m):
            print(f"    [RSP+0x{i:03X}] 0x{v:016X}  {m}+0x{v - b:X}")


def main() -> int:
    for p in sys.argv[1:]:
        try:
            analyze(p)
        except Exception as e:  # noqa: BLE001
            print(f"  !! {p}: {type(e).__name__}: {e}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
