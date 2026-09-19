#!/usr/bin/env python3
"""esm_probe.py - 按记录类型/FormID 直接翻 Starfield.esm（离线排查用）。

为什么要它：xEdit 一次头部加载要 ~5 分钟，但很多问题（"这条记录里到底有哪几个
子记录？某个字段是不是我要的引用？"）用 Python 直接扫一遍几秒就有答案。
本工具只做**只读探测**，不产出正式数据（正式数据走 xEdit 导出 / 专用脚本）。

用法：
    # 列出某类记录（FormID + EDID + 可打印的 FULL 文本前 60 字）
    python tools/esm/esm_probe.py list LCTN --limit 20
    python tools/esm/esm_probe.py list LCTN --grep NewAtlantis

    # 打印一条记录的所有子记录（sig / 长度 / 十六进制 + 可打印文本）
    python tools/esm/esm_probe.py rec LCTN 0027C8ED

    # 只看某条记录里出现的子记录签名统计（先搞清布局）
    python tools/esm/esm_probe.py sigs LCTN --limit 50

    # 扫某类记录里，哪个子记录出现过「像 FormID 的引用」（按签名聚合样本）
    python tools/esm/esm_probe.py refs LCTN

    # 全表扫：某类记录里含某签名的记录数与样本
    python tools/esm/esm_probe.py find LCTN MNAM --limit 5

注意：Starfield.esm 约 1.4 GB，本工具会整体读进内存（约 3-5 秒）。
"""
from __future__ import annotations

import argparse
import re
import struct
import sys
import zlib
from collections import Counter
from pathlib import Path

DEFAULT_ESM = r"D:\SteamLibrary\steamapps\common\Starfield\Data\Starfield.esm"


def read_records(buf: bytes, group_sig: str):
    """yield (formid, flags, payload) —— 遍历顶层 GRUP(group_sig) 下的记录。

    会自动跳过嵌套 GRUP（WRLD/CELL 这类有四层嵌套的也能走通）。
    """
    head = struct.unpack_from("<I", buf, 4)[0]
    pos = 24 + head
    while pos + 24 <= len(buf):
        if buf[pos:pos + 4] != b"GRUP":
            return
        gsize = struct.unpack_from("<I", buf, pos + 4)[0]
        glabel = buf[pos + 8:pos + 12]
        if gsize < 24:
            return
        if glabel == group_sig.encode("latin1"):
            yield from walk_group(buf, pos + 24, pos + gsize)
            return
        pos += gsize


def walk_group(buf: bytes, p: int, end: int):
    while p + 24 <= end:
        if buf[p:p + 4] == b"GRUP":
            sub = struct.unpack_from("<I", buf, p + 4)[0]
            if sub < 24:
                return
            yield from walk_group(buf, p + 24, p + sub)
            p += sub
            continue
        size = struct.unpack_from("<I", buf, p + 4)[0]
        flags = struct.unpack_from("<I", buf, p + 8)[0]
        formid = struct.unpack_from("<I", buf, p + 12)[0]
        payload = None
        if flags & 0x00040000:  # compressed
            if size >= 4:
                try:
                    payload = zlib.decompress(buf[p + 28:p + 24 + size])
                except zlib.error:
                    payload = None
        else:
            payload = buf[p + 24:p + 24 + size]
        if payload is not None:
            yield formid, flags, payload
        p += 24 + size


def subrecords(payload: bytes):
    """遍历子记录。**必须处理 XXXX 扩展长度**（BGS 三代通用）：

        XXXX(4) size(2)=4 actualSize(4)  |  下一个子记录：sig(4) size(2) data(actualSize)

    不处理它就会把长数据的记录解错（实测：CELL 记录里一旦出现 XXXX，后面的字节
    会被当成一堆 4 个零字节的「签名」——本文件里能看到 8 万多个 `\\x00\\x00\\x00\\x00`，
    那就是没处理 XXXX 的痕迹）。
    """
    p = 0
    while p + 6 <= len(payload):
        sig = payload[p:p + 4]
        size = struct.unpack_from("<H", payload, p + 4)[0]
        if sig == b"XXXX":
            if p + 10 > len(payload):
                return
            actual = struct.unpack_from("<I", payload, p + 6)[0]
            q = p + 10
            if q + 6 > len(payload) or q + 6 + actual > len(payload):
                return
            yield payload[q:q + 4], payload[q + 6:q + 6 + actual]
            p = q + 6 + actual
            continue
        if p + 6 + size > len(payload):
            return
        yield sig, payload[p + 6:p + 6 + size]
        p += 6 + size


def printable(b: bytes) -> str:
    out = []
    for ch in b:
        if 32 <= ch < 127 or ch >= 0x80:
            out.append(chr(ch))
        else:
            out.append(".")
    return "".join(out)


def ascii_z(b: bytes) -> str:
    return b.split(b"\x00")[0].decode("latin1", errors="replace")


def cmd_list(buf, a) -> int:
    n = 0
    for formid, _flags, payload in read_records(buf, a.sig):
        edid = full = ""
        for sig, sp in subrecords(payload):
            if sig == b"EDID":
                edid = ascii_z(sp)
            elif sig == b"FULL":
                if len(sp) >= 4:
                    full = f"<str {struct.unpack_from('<I', sp, 0)[0]:#x}>"
                else:
                    full = ascii_z(sp)
        line = f"{formid:08X}  {edid}"
        if full:
            line += f"  FULL={full}"
        if a.grep and a.grep.lower() not in line.lower():
            continue
        print(line)
        n += 1
        if a.limit and n >= a.limit:
            break
    print(f"--- 共列出 {n} 条")
    return 0


def cmd_rec(buf, a) -> int:
    want = int(a.formid, 16)
    for formid, flags, payload in read_records(buf, a.sig):
        if formid != want:
            continue
        print(f"record {formid:08X} flags={flags:#010x} payload={len(payload)} B")
        for i, (sig, sp) in enumerate(subrecords(payload)):
            head = f"[{i:3d}] {sig.decode('latin1')} len={len(sp):5d}"
            if len(sp) <= 24:
                print(f"{head}  hex={sp.hex(' ')}")
            else:
                print(f"{head}  hex={sp[:24].hex(' ')} ...  txt={printable(sp[:60])!r}")
        return 0
    print(f"没找到 {a.sig}:{a.formid}")
    return 1


def cmd_sigs(buf, a) -> int:
    sigs = Counter()
    recs = 0
    for _formid, _flags, payload in read_records(buf, a.sig):
        recs += 1
        for sig, sp in subrecords(payload):
            sigs[sig] += 1
            if a.vex:
                pass
        if a.limit and recs >= a.limit:
            break
    print(f"{a.sig} 扫描 {recs} 条记录，子记录统计：")
    for sig, n in sigs.most_common(80):
        print(f"  {sig.decode('latin1'):6s} {n}")
    return 0


def cmd_find(buf, a) -> int:
    """列出含某子记录签名的记录（可带 formid 过滤）。"""
    hits = 0
    for formid, _flags, payload in read_records(buf, a.sig):
        found = None
        for rsig, sp in subrecords(payload):
            if rsig.decode("latin1") == a.sub:
                found = sp
                break
        if found is None:
            continue
        hits += 1
        if hits <= (a.limit or 5):
            print(f"{formid:08X}  {a.sub} len={len(found)} hex={found[:16].hex(' ')}")
    print(f"--- {a.sig} 中含 {a.sub} 的记录数: {hits}")
    return 0


def walk_all(buf: bytes):
    """遍历所有顶层 GRUP（含嵌套），yield (topsig, formid, flags, payload)。"""
    head = struct.unpack_from("<I", buf, 4)[0]
    pos = 24 + head
    while pos + 24 <= len(buf):
        if buf[pos:pos + 4] != b"GRUP":
            return
        gsize = struct.unpack_from("<I", buf, pos + 4)[0]
        glabel = buf[pos + 8:pos + 12]
        if gsize < 24:
            return
        for formid, flags, payload in walk_group(buf, pos + 24, pos + gsize):
            yield glabel, formid, flags, payload
        pos += gsize


# ---------------------------------------------------------------------------
#  带上下文的遍历：世界里的引用（REFR/ACHR/...）属于哪个 CELL / WRLD
#
#  组类型常量（BGS 三代通用）：
#    0=Top 1=World Children 2/3=Interior Cell Block/SubBlock
#    4/5=Exterior Cell Block/SubBlock 6=Cell Children
#    8=Cell Persistent Children 9=Cell Temporary Children 10=Cell Visible Distant
#  记录出现顺序保证了：CELL 记录先出现，随后才是它的 children 组 —— 所以
#  「最近一次见到的 CELL」就是后续引用的宿主（递归时按层拷贝，不会串台）。
# ---------------------------------------------------------------------------
REF_SIGS = (b"REFR", b"ACHR", b"PGRE", b"PMIS", b"PARW", b"PBAR", b"PHZD")


def _walk_ctx(buf, p, end, cell, world, out, want_sigs):
    while p + 24 <= end:
        if buf[p:p + 4] == b"GRUP":
            sub = struct.unpack_from("<I", buf, p + 4)[0]
            if sub < 24:
                return
            _walk_ctx(buf, p + 24, p + sub, cell, world, out, want_sigs)
            p += sub
            continue
        size = struct.unpack_from("<I", buf, p + 4)[0]
        flags = struct.unpack_from("<I", buf, p + 8)[0]
        formid = struct.unpack_from("<I", buf, p + 12)[0]
        sig = buf[p:p + 4]
        payload = None
        if flags & 0x00040000:
            if size >= 4:
                try:
                    payload = zlib.decompress(buf[p + 28:p + 24 + size])
                except zlib.error:
                    payload = None
        else:
            payload = buf[p + 24:p + 24 + size]
        if payload is not None:
            if sig == b"CELL":
                cell = formid
            elif sig == b"WRLD":
                world = formid
            if want_sigs is None or sig in want_sigs:
                out.append((sig, formid, flags, cell, world, payload))
        p += 24 + size


def iter_records_with_context(buf, want_sigs=None):
    """yield (sig, formid, flags, cell_formid, world_formid, payload)。

    want_sigs=None 表示要全部记录（一次遍历能拿到任意类型，包括 CELL/WRLD/REFR/QUST…）。
    全表 1.4 GB 约 1-2 分钟；适合「一次收集很多信息」的场景。
    """
    out: list = []
    head = struct.unpack_from("<I", buf, 4)[0]
    pos = 24 + head
    while pos + 24 <= len(buf):
        if buf[pos:pos + 4] != b"GRUP":
            break
        gsize = struct.unpack_from("<I", buf, pos + 4)[0]
        if gsize < 24:
            break
        _walk_ctx(buf, pos + 24, pos + gsize, 0, 0, out, want_sigs)
        for item in out:
            yield item
        out.clear()
        pos += gsize


def iter_refs_with_context(buf):
    """yield (refr_formid, flags, cell_formid, world_formid, payload) —— 只遍历世界里的引用。"""
    for _sig, formid, flags, cell, world, payload in iter_records_with_context(buf, set(REF_SIGS)):
        yield formid, flags, cell, world, payload


def record_base_form(payload: bytes) -> int:
    """REFR/ACHR 的 NAME = 基础对象（STAT/NPC_/CONT…）的 FormID。"""
    for sig, sp in subrecords(payload):
        if sig == b"NAME" and len(sp) >= 4:
            return struct.unpack_from("<I", sp, 0)[0]
    return 0


def record_edid(payload: bytes) -> str:
    for sig, sp in subrecords(payload):
        if sig == b"EDID":
            return ascii_z(sp)
    return ""


def cmd_place(buf, a) -> int:
    """找某个基础对象（NPC_/STAT/...）在世界里的所有放置引用。"""
    want = int(a.formid, 16)
    n = 0
    for refr, flags, cell, world, payload in iter_refs_with_context(buf):
        if record_base_form(payload) != want:
            continue
        n += 1
        if n > (a.limit or 20):
            continue
        print(f"REFR {refr:08X} persistent={'Y' if flags & 0x400 else 'n'} cell={cell:08X} world={world:08X} edid={record_edid(payload)}")
    print(f"--- 基础对象 {a.formid} 的放置引用共 {n} 个")
    return 0


def cmd_byid(buf, a) -> int:
    """全表按 FormID 找记录（不知道它在哪个组时用）。"""
    recs = []
    want = int(a.formid, 16)
    for topsig, formid, flags, payload in walk_all(buf):
        if formid != want:
            continue
        recs.append((topsig, formid, flags, payload))
    if not recs:
        print(f"全表没找到 FormID {a.formid}")
        return 1
    print(f"命中 {len(recs)} 条（同一 FormID 可能在多个组里出现，例如 REFR 属于 CELL/WRLD）")
    for topsig, formid, flags, payload in recs[: a.limit or 4]:
        print(f"\n--- 顶层组 {topsig.decode('latin1')}  record {formid:08X} flags={flags:#010x} payload={len(payload)} B")
        for i, (sig, sp) in enumerate(subrecords(payload)):
            head = f"[{i:3d}] {sig.decode('latin1')} len={len(sp):5d}"
            if len(sp) <= 24:
                print(f"{head}  hex={sp.hex(' ')}")
            else:
                print(f"{head}  hex={sp[:24].hex(' ')} ...  txt={printable(sp[:60])!r}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=["list", "rec", "sigs", "find", "byid", "place"])
    ap.add_argument("sig", help="记录类型（如 LCTN / QUST / REFR / NPC_）；byid/place 模式填任意占位")
    ap.add_argument("formid", nargs="?", default="", help="rec/byid/place 模式的 FormID（十六进制）")
    ap.add_argument("sub", nargs="?", default="", help="find 模式的子记录签名")
    ap.add_argument("--esm", default=DEFAULT_ESM)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--grep", default="")
    ap.add_argument("--vex", action="store_true")
    a = ap.parse_args()
    if a.mode not in ("byid", "place") and not re.fullmatch(r"[A-Z0-9_]{4}", a.sig):
        print(f"记录类型应为 4 字符签名：{a.sig}")
        return 2
    buf = Path(a.esm).read_bytes()
    if a.mode == "list":
        return cmd_list(buf, a)
    if a.mode == "rec":
        return cmd_rec(buf, a)
    if a.mode == "sigs":
        return cmd_sigs(buf, a)
    if a.mode == "byid":
        return cmd_byid(buf, a)
    if a.mode == "place":
        return cmd_place(buf, a)
    return cmd_find(buf, a)


if __name__ == "__main__":
    sys.exit(main())
