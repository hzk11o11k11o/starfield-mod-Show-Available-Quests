#!/usr/bin/env python3
"""quest_api_scan.py - 从 Starfield.exe 里挖 Papyrus 原生函数绑定（用于拿 TESQuest 运行时状态）。

动机：需求里有两条运行时过滤 ——
  * 「已经接了的不显示」
  * 「进度没到不显示」
commonlibsf 的 TESQuest 只有 IsStageDone（而且 REL::ID = 0，不可用），
所以运行时状态得自己 RE。

**思路**：Papyrus 的原生函数名（"IsRunning" / "IsStageDone" / "SetStage" ...）在 exe 里
是唯一字符串，绑定表里就在名字旁边放函数指针 —— 找到那个指针，就找到了
「读 TESQuest 运行时状态」的现成函数（引擎自己用的，语义不用猜）。

用法：
    python tools/re/quest_api_scan.py strings           # 只列出候选名字串地址
    python tools/re/quest_api_scan.py refs IsRunning     # 列出引用该字符串的结构体，dump 上下文
    python tools/re/quest_api_scan.py id 0x1234567       # RVA -> Address Library ID（插件要用）
"""
from __future__ import annotations

import argparse
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

EXE = Path(r"D:\SteamLibrary\steamapps\common\Starfield\Starfield.exe")
LIB = Path(
    r"D:\Mod Organizer 2\starfield_mods\mods\(1.16.244.0) SFSE Address Library"
    r"\SFSE\Plugins\versionlib-1-16-244-0.bin"
)
IMAGE_BASE = 0x140000000

# Papyrus 里和「任务能不能接 / 有没有开始」相关的原生函数名（都是 Quest 脚本的方法）
QUEST_NAMES = [
    "IsRunning", "IsCompleted", "IsStageDone", "GetStageDone", "SetStage",
    "GetStage", "Start", "Stop", "IsActive", "IsStarting", "IsStopping",
    "GetCurrentStageID", "GetNumStages", "GetNumQuestItems", "GetStageDone",
    "CompleteAllObjectives", "IsObjectiveCompleted", "GetQuestAlias",
]


def load_exe() -> bytes:
    return EXE.read_bytes()


def sections(d: bytes):
    e = struct.unpack_from("<I", d, 0x3C)[0]
    nsec = struct.unpack_from("<H", d, e + 6)[0]
    opt = struct.unpack_from("<H", d, e + 20)[0]
    sec = e + 24 + opt
    out = []
    for i in range(nsec):
        s = sec + 40 * i
        name = d[s:s + 8].rstrip(b"\x00").decode("ascii", "replace")
        vs, va, rs, ro = struct.unpack_from("<IIII", d, s + 8)
        out.append((name, va, vs, ro, rs))
    return out


def off_to_rva(secs, off: int):
    for name, va, vs, ro, rs in secs:
        if ro <= off < ro + rs:
            return name, va + (off - ro)
    return None, None


def rva_to_off(secs, rva: int):
    for name, va, vs, ro, rs in secs:
        if va <= rva < va + vs:
            return ro + (rva - va)
    return None


def find_qword(d: bytes, value: int, limit: int = 0):
    b = struct.pack("<Q", value)
    out, i = [], 0
    while True:
        j = d.find(b, i)
        if j < 0:
            return out
        out.append(j)
        i = j + 1
        if limit and len(out) >= limit:
            return out


def cmd_strings(d: bytes, secs) -> int:
    print(f"{EXE}  {len(d):,} 字节")
    for nm in QUEST_NAMES:
        pat = nm.encode() + b"\x00"
        hits, i = [], 0
        while True:
            j = d.find(pat, i)
            if j < 0:
                break
            hits.append(j)
            i = j + 1
        info = []
        for h in hits:
            sname, rva = off_to_rva(secs, h)
            info.append(f"{sname} rva={rva:#x}" if rva else f"file={h:#x}")
        print(f"  {nm:22s} {len(hits)} 处  {'; '.join(info[:4])}")
    return 0


def cmd_refs(d: bytes, secs, name: str, context: int) -> int:
    pat = name.encode() + b"\x00"
    hits = []
    i = 0
    while True:
        j = d.find(pat, i)
        if j < 0:
            break
        hits.append(j)
        i = j + 1
    if not hits:
        print(f"没找到字符串 {name}")
        return 1
    for h in hits:
        sname, rva = off_to_rva(secs, h)
        if rva is None:
            continue
        va = IMAGE_BASE + rva
        print(f"=== {name} 字符串 file={h:#x} rva={rva:#x} va={va:#x} (段 {sname})")
        refs = find_qword(d, va)
        print(f"    被引用的位置：{len(refs)} 个")
        for r in refs[:8]:
            rn, rr = off_to_rva(secs, r)
            print(f"    ---- file={r:#x} rva={rr:#x} 段={rn}")
            start = max(0, r - context)
            for k in range(0, (2 * context) + 8, 8):
                off = start + k
                if off + 8 > len(d):
                    break
                v = struct.unpack_from("<Q", d, off)[0]
                mark = "  <== 字符串" if off == r else ""
                tag = ""
                # 指针落在 .text 里 ⇒ 大概率是函数指针
                if v >> 40 == 0 and v < 0x100000000:
                    tname, trva = off_to_rva(secs, v)
                    if tname == ".text":
                        tag = f"  → text rva={trva:#x}"
                print(f"      +{off - r:+#5x} {v:#018x}{mark}{tag}")
    return 0


def cmd_code(d: bytes, secs, rva: int, length: int) -> int:
    """反汇编 [rva, rva+length)，只打印 rip 相对寻址/调用，并把目标翻译成「段 + 字符串」。

    用途：看某个注册/派发区域里，名字字符串旁边放的是哪个函数指针。
    """
    import capstone  # type: ignore

    off = rva_to_off(secs, rva)
    if off is None:
        print(f"RVA {rva:#x} 不在任何段里")
        return 1
    data = d[off:off + length]
    md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_64)
    md.detail = True
    for insn in md.disasm(data, rva):
        tgt = None
        for op in insn.operands:
            if op.type == capstone.x86.X86_OP_MEM and op.mem.base == capstone.x86.X86_REG_RIP:
                tgt = insn.address + insn.size + op.mem.disp
                break
        sname = ""
        extra = ""
        if tgt is not None:
            sn, _ = off_to_rva_sec(secs, tgt)
            sname = sn or "?"
            extra = describe_rdata(d, secs, tgt)
        line = f"{insn.address:08X}  {insn.mnemonic:8s} {insn.op_str}"
        if tgt is not None:
            line += f"    ; -> {sname} {tgt:#x}{extra}"
        print(line)
    return 0


def cstr_at(d: bytes, secs, rva: int) -> str | None:
    """目标 RVA 上若是一段 ASCII 字符串，返回它。"""
    off = None
    for name, va, vs, ro, rs in secs:
        if va <= rva < va + max(vs, rs):
            off = ro + (rva - va)
            break
    if off is None:
        return None
    raw = d[off:off + 64]
    if not raw or raw[0] == 0 or not all(32 <= c < 127 for c in raw[:6]):
        return None
    return raw.split(b"\x00", 1)[0].decode("ascii", "replace")


def cmd_regs(d: bytes, secs, rva: int, length: int) -> int:
    """把「脚本类型原生函数注册区」翻译成表：函数名 → 实现函数 RVA。

    注册代码的形状（本 exe 实测）：
        mov rsi, [vtable + 0xF0]        ; 注册方法（虚）
        mov ecx, 0x58                   ; NativeFunction 大小
        call operator new
        lea r9, [rip+X]                 ; X = 实现函数（.text，小函数）
        lea rdx, [rip+Y]                ; Y = 名字字符串（.rdata）
        mov rcx, rax
        call ctor                       ; 0x20CEDE0 / 0x20CF020（两种重载）
        ...
        call rsi                        ; 注册
    所以：对每个「指向 .rdata 里 ASCII 字符串」的 lea，往前找最近的
    「指向 .text 的 lea（r9）」= 该函数的实现。
    """
    import capstone  # type: ignore

    off = rva_to_off(secs, rva)
    if off is None:
        print(f"RVA {rva:#x} 不在任何段里")
        return 1
    data = d[off:off + length]
    md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_64)
    md.detail = True

    pending_text_lea: tuple[int, int] | None = None  # (insn 地址, 目标 RVA)
    n = 0
    for insn in md.disasm(data, rva):
        tgt = None
        for op in insn.operands:
            if op.type == capstone.x86.X86_OP_MEM and op.mem.base == capstone.x86.X86_REG_RIP:
                tgt = insn.address + insn.size + op.mem.disp
                break
        if tgt is None:
            continue
        sn, _ = off_to_rva_sec(secs, tgt)
        if sn == ".text":
            pending_text_lea = (insn.address, tgt)
            continue
        s = cstr_at(d, secs, tgt)
        if s:
            impl = ""
            if pending_text_lea and insn.address - pending_text_lea[0] < 0x40:
                impl = f"impl={pending_text_lea[1]:#x} (距 {insn.address - pending_text_lea[0]:#x})"
                pending_text_lea = None
            print(f"{insn.address:08X}  {s:34s} {impl}")
            n += 1
    print(f"共 {n} 条")
    return 0


def off_to_rva_sec(secs, rva: int):
    for name, va, vs, ro, rs in secs:
        if va <= rva < va + max(vs, rs):
            return name, rva
    return None, None


def describe_rdata(d: bytes, secs, rva: int) -> str:
    """若目标落在 .rdata/.data，尝试把内容当「C 字符串 / 指针」解读，方便肉眼判断。"""
    off = None
    for name, va, vs, ro, rs in secs:
        if va <= rva < va + max(vs, rs):
            off = ro + (rva - va)
            sect = name
            break
    if off is None or off + 8 > len(d):
        return ""
    raw = d[off:off + 64]
    if raw[:1].isascii() and raw[:1] not in (b"\x00",) and all(32 <= c < 127 for c in raw[:12]):
        s = raw.split(b"\x00", 1)[0][:48].decode("ascii", "replace")
        return f'  ("{s}")'
    v = struct.unpack_from("<Q", raw, 0)[0]
    if v >> 40 == 0 and v < 0x100000000:
        sn, _ = off_to_rva_sec(secs, v)
        if sn == ".text":
            return f"  (ptr -> .text {v:#x})"
    return ""


def cmd_id(d: bytes, secs, rva: int) -> int:
    sys.path.insert(0, str(Path(__file__).parent))
    from versionlib import read_versionlib  # type: ignore

    _hdr, table = read_versionlib(LIB)
    best = [(i, o) for i, o in table.items() if o == rva]
    print(f"RVA {rva:#x} 直接命中的 ID：{best}")
    if not best:
        near = sorted(((abs(o - rva), i, o) for i, o in table.items()))[:5]
        print("最近的 5 个条目（距离, ID, RVA）：")
        for dist, i, o in near:
            print(f"  {dist:#x}  ID={i}  RVA={o:#x}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["strings", "refs", "id", "code", "regs"])
    ap.add_argument("arg", nargs="?")
    ap.add_argument("--context", type=int, default=0x20)
    ap.add_argument("--len", type=lambda s: int(s, 0), default=0x400)
    a = ap.parse_args()

    d = load_exe()
    secs = sections(d)
    if a.cmd == "strings":
        return cmd_strings(d, secs)
    if a.cmd == "refs":
        return cmd_refs(d, secs, a.arg or "IsRunning", a.context)
    if a.cmd == "code":
        return cmd_code(d, secs, int(a.arg, 16), a.len)
    if a.cmd == "regs":
        return cmd_regs(d, secs, int(a.arg, 16), a.len)
    return cmd_id(d, secs, int(a.arg, 16))


if __name__ == "__main__":
    raise SystemExit(main())
