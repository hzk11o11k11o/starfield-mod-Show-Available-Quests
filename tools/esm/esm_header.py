#!/usr/bin/env python3
"""esm_header.py - 打印 ESM/ESP 的 TES4 头（master 列表 / 作者 / 描述 / 标志）+ 顶层组记录数。

为什么要它：做 DLC / 多 master 支持时，第一件要知道的事是
「这个 esm 依赖谁、它自己是不是 light(ESL)、它里面有多少条 QUST」。

用法：
    python tools/esm/esm_header.py D:\\...\\Data\\ShatteredSpace.esm
    python tools/esm/esm_header.py --data "D:\\SteamLibrary\\steamapps\\common\\Starfield\\Data"   # 扫全部 esm
"""
from __future__ import annotations

import argparse
import struct
import sys
from pathlib import Path

from esm_probe import subrecords, walk_group  # 复用解析器（同一目录）


def read_header(buf: bytes) -> dict:
    """TES4 记录：sig(4) size(4) flags(4) formid(4) vcs(4) version(2) unk(2) | 子记录…"""
    assert buf[:4] == b"TES4", "不是 ESM/ESP 文件（头 4 字节不是 TES4）"
    size = struct.unpack_from("<I", buf, 4)[0]
    flags = struct.unpack_from("<I", buf, 8)[0]
    ver = struct.unpack_from("<H", buf, 20)[0]
    masters: list[str] = []
    author = desc = ""

    def z(b: bytes) -> str:
        return b.split(b"\x00")[0].decode("utf-8", errors="replace")

    for sig, sp in subrecords(buf[24:24 + size]):
        if sig == b"MAST":
            masters.append(z(sp))
        elif sig == b"CNAM":
            author = z(sp)
        elif sig == b"SNAM":
            desc = z(sp)
    return {"size": size, "flags": flags, "version": ver, "masters": masters,
            "author": author, "desc": desc, "num_masters": len(masters)}


def top_groups(buf: bytes) -> dict[str, int]:
    """顶层 GRUP 的记录数（每个组名 -> 记录条数，含嵌套）。"""
    head = struct.unpack_from("<I", buf, 4)[0]
    pos = 24 + head
    out: dict[str, int] = {}
    while pos + 24 <= len(buf):
        if buf[pos:pos + 4] != b"GRUP":
            break
        gsize = struct.unpack_from("<I", buf, pos + 4)[0]
        glabel = buf[pos + 8:pos + 12].decode("latin1").strip("\x00") or "?"
        if gsize < 24:
            break
        n = 0
        for _ in walk_group(buf, pos + 24, pos + gsize):
            n += 1
        out[glabel] = out.get(glabel, 0) + n
        pos += gsize
    return out


def raw_tes4(buf: bytes) -> list[tuple[str, bytes]]:
    """TES4 记录的全部子记录（按出现顺序）——排查「作者/描述怎么读成这样」。"""
    size = struct.unpack_from("<I", buf, 4)[0]
    return [(sig.decode("latin1"), sp) for sig, sp in subrecords(buf[24:24 + size])]


def group_tree(buf: bytes, want: str, max_depth: int = 3) -> list[str]:
    """打印某个顶层组内部的嵌套组结构（Starfield 的组里还能套组，别漏读）。"""
    out: list[str] = []

    def walk(p: int, end: int, depth: int, prefix: str) -> int:
        records = 0
        while p + 24 <= end:
            if buf[p:p + 4] == b"GRUP":
                sub = struct.unpack_from("<I", buf, p + 4)[0]
                if sub < 24:
                    return records
                label = buf[p + 8:p + 12]
                gtype = struct.unpack_from("<i", buf, p + 12)[0]
                inner = walk(p + 24, p + sub, depth + 1, prefix)
                if depth <= max_depth:
                    lb = label.decode("latin1").strip("\x00") or "-"
                    tail = f" → 含 {n} 条记录（含子组）" if depth == max_depth else ""
                    out.append(f"{'  ' * depth}{prefix}GRUP[{gtype}] {lb}" + tail)
                records += inner
                p += sub
                continue
            size = struct.unpack_from("<I", buf, p + 4)[0]
            records += 1
            p += 24 + size
        return records

    head = struct.unpack_from("<I", buf, 4)[0]
    pos = 24 + head
    while pos + 24 <= len(buf):
        if buf[pos:pos + 4] != b"GRUP":
            break
        gsize = struct.unpack_from("<I", buf, pos + 4)[0]
        if gsize < 24:
            break
        if buf[pos + 8:pos + 12] == want.encode("latin1"):
            # 顶层：先列直接记录，再逐个打印嵌套组
            p = pos + 24
            end = pos + gsize
            direct = 0
            while p + 24 <= end:
                if buf[p:p + 4] == b"GRUP":
                    sub = struct.unpack_from("<I", buf, p + 4)[0]
                    if sub < 24:
                        break
                    n = walk(p + 24, p + sub, 1, "")
                    lbl = buf[p + 8:p + 12].decode("latin1").strip("\x00") or "-"
                    gt = struct.unpack_from("<i", buf, p + 12)[0]
                    out.append(f"  GRUP[{gt}] {lbl} → {n} 条记录（含子组）")
                    p += sub
                    continue
                size = struct.unpack_from("<I", buf, p + 4)[0]
                direct += 1
                p += 24 + size
            out.insert(0, f"{want} 顶层组：直接记录 {direct} 条 + 嵌套组如下")
            return out
        pos += gsize
    out.append(f"没有顶层组 {want}")
    return out


def describe(path: Path) -> dict:
    buf = path.read_bytes()
    h = read_header(buf)
    h["groups"] = top_groups(buf)
    h["path"] = str(path)
    h["file"] = path.name
    return h


def print_one(h: dict, show_groups: bool) -> None:
    light = "（light/ESL 标志在 TES4 flags 里，见下）"
    print(f"=== {h['file']}  {h['path']}")
    print(f"  版本={h['version']}  TES4 flags=0x{h['flags']:08X}  master 数={h['num_masters']} {light}")
    print(f"  作者={h['author']!r}")
    print(f"  描述={h['desc']!r}")
    for i, m in enumerate(h["masters"]):
        print(f"    master[{i}] = {m}")
    q = h["groups"].get("QUST", 0)
    print(f"  顶层组记录数：QUST={q} CELL={h['groups'].get('CELL', 0)} WRLD={h['groups'].get('WRLD', 0)}"
          f" LCTN={h['groups'].get('LCTN', 0)} NPC_={h['groups'].get('NPC_', 0)}")
    if show_groups:
        print("  全部顶层组：" + " ".join(f"{k}:{v}" for k, v in sorted(h["groups"].items())))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("esm", nargs="*", help="一个或多个 esm 路径")
    ap.add_argument("--data", default="", help="扫这个目录下所有 *.esm")
    ap.add_argument("--groups", action="store_true", help="打印全部顶层组")
    ap.add_argument("--qusts-only", action="store_true", help="只有 QUST>0 的文件才打印")
    ap.add_argument("--tree", default="", help="打印某顶层组内部的嵌套组结构（如 QUST）")
    ap.add_argument("--raw", action="store_true", help="打印 TES4 头里的全部子记录")
    a = ap.parse_args()

    targets: list[Path] = []
    if a.esm:
        targets += [Path(p) for p in a.esm]
    if a.data:
        targets += sorted(Path(a.data).glob("*.esm")) + sorted(Path(a.data).glob("*.esp"))
    if not targets:
        print("用法：esm_header.py <esm 路径> 或 --data <Data 目录>")
        return 2

    for p in targets:
        try:
            h = describe(p)
        except Exception as e:  # noqa: BLE001
            print(f"=== {p.name}：读取失败（{e}）")
            continue
        if a.qusts_only and h["groups"].get("QUST", 0) == 0:
            continue
        print_one(h, a.groups)
        if a.raw or a.tree:
            buf = p.read_bytes()
            if a.raw:
                print("  TES4 子记录：")
                for sig, sp in raw_tes4(buf):
                    shown = sp[:40].hex(" ") if len(sp) <= 16 else f"{sp[:40].hex(' ')} ... txt={sp.split(b'\\x00')[0].decode('utf-8', 'replace')!r}"
                    print(f"    {sig} len={len(sp):5d} {shown}")
            if a.tree:
                for line in group_tree(buf, a.tree):
                    print("  " + line)
    return 0


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).parent))
    sys.exit(main())
