#!/usr/bin/env python3
r"""dump_cell_group.py - 打印「任务板所在 cell」的组结构（第 33 轮）。

## 为什么需要它

第 30 轮往基础游戏 cell 里**新建**了 11 条常驻 XMarker 引用，实机 `marker 0`（引擎里一条都取不到）。
第 33 轮复查发现两条对照事实（见 docs/99 一·补十八）：

* 官方 SFBGS003 / SFBGS008 在动基础游戏 cell 里的引用时，**同时覆盖了 CELL 记录**（6/6 个 cell）；
* 本机全部插件里**只有我们**往基础游戏 cell 新增引用，而且**没有 CELL 记录**。

⇒ 怀疑的落点是：**引擎只把「本插件也覆盖了该 CELL 记录」的 CellChildren 组并进那个 cell**。
本工具把三件事摊开，供实现（create_board_markers.py）与验证（xEdit）照抄：

1. Starfield.esm 里该 cell 的 `InteriorSubBlock` 组**直接子项顺序**（CELL 记录在前还是 CellChildren 在前）；
2. 官方 override 插件里同一 cell 的写法（组链、CELL 记录 flags/size/是否字节一致）；
3. 顶层组的排列顺序（官方把 CELL 组放在文件哪个位置）。

用法：
    python tools/esm/dump_cell_group.py                       # Starfield.esm 里的 11 个目标 cell
    python tools/esm/dump_cell_group.py --plugin SFBGS003.esm # 某插件里这些 cell 的 override
    python tools/esm/dump_cell_group.py --plugin <path> --all # 该插件的全部 CELL 记录（去掉目标过滤）
"""
from __future__ import annotations

import argparse
import json
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from esm_probe import DEFAULT_ESM, record_edid  # noqa: E402
from scan_entry_persistent import walk  # noqa: E402   （带 zlib 解压的记录遍历）

ROOT = Path(__file__).resolve().parents[2]
DATA = Path(r"D:\SteamLibrary\steamapps\common\Starfield\Data")
MODS = Path(r"D:\Mod Organizer 2\starfield_mods\mods")
GROUP_NAMES = {0: "Top", 1: "WorldChildren", 2: "InteriorBlock", 3: "InteriorSubBlock",
               4: "ExteriorBlock", 5: "ExteriorSubBlock", 6: "CellChildren",
               7: "TopicChildren", 8: "CellPersistent", 9: "CellTemporary"}


def target_cells() -> dict[str, str]:
    """entry_targets.json 里 12 条任务板所在 cell：cell EDID -> 任务板中文名（后者只用于打印）。"""
    entries = json.loads((ROOT / "ref" / "entry_targets.json").read_text(encoding="utf-8"))
    return {e["cell"]: e["nameZh"] for e in entries}


def resolve_cell_formids(edids: set[str]) -> dict[int, str]:
    """扫一遍 Starfield.esm 的 CELL 记录，把 EDID 换成 FormID（EDID 子记录，压缩记录交给 walk 解压）。"""
    buf = Path(DEFAULT_ESM).read_bytes()
    out: dict[int, str] = {}

    def cb(sig, formid, flags, chain, cell, world, payload):
        if sig == b"CELL" and (formid >> 24) == 0:
            edid = record_edid(payload)
            if edid in edids:
                out[formid] = edid

    walk(buf, cb)
    return out


def describe_children(buf: bytes, p: int, end: int, indent: str, max_depth: int = 99, depth: int = 0) -> None:
    """按顺序打印一个组的直接子项（组 + 记录）；max_depth 用来限制展开层级（--brief）。"""
    i = 0
    while p + 24 <= end:
        if buf[p:p + 4] == b"GRUP":
            gsize = struct.unpack_from("<I", buf, p + 4)[0]
            if gsize < 24:
                return
            label = bytes(buf[p + 8:p + 12])
            gtype = struct.unpack_from("<i", buf, p + 12)[0]
            lab = label.decode("latin1", "replace") if gtype == 0 else f"0x{struct.unpack('<i', label)[0]:08X}"
            print(f"{indent}{i}) GRUP type={gtype}({GROUP_NAMES.get(gtype, '?')}) label={lab} size={gsize}")
            if depth + 1 < max_depth:
                describe_children(buf, p + 24, p + gsize, indent + "      ", max_depth, depth + 1)
            p += gsize
        else:
            size = struct.unpack_from("<I", buf, p + 4)[0]
            flags = struct.unpack_from("<I", buf, p + 8)[0]
            formid = struct.unpack_from("<I", buf, p + 12)[0]
            sig = bytes(buf[p:p + 4]).decode("latin1")
            mark = "  ← 目标 CELL 记录" if sig == "CELL" and (formid & 0xFFFFFF) in WANT else ""
            print(f"{indent}{i}) {sig:<4s} 0x{formid:08X} flags=0x{flags:06X} size={size}{mark}")
            p += 24 + size
        i += 1


WANT: set[int] = set()
BRIEF = False


def scan(buf: bytes, want: set[int], only_first_subblock: bool) -> None:
    """找出每个目标 cell 的 CELL 记录，打印它的组链 + 父组直接子项。"""
    hit: dict[int, dict] = {}

    def rec(p: int, end: int, chain: list) -> None:
        while p + 24 <= end:
            if buf[p:p + 4] == b"GRUP":
                sub = struct.unpack_from("<I", buf, p + 4)[0]
                if sub < 24:
                    return
                label = bytes(buf[p + 8:p + 12])
                gtype = struct.unpack_from("<i", buf, p + 12)[0]
                rec(p + 24, p + sub, chain + [(gtype, label)])
                p += sub
                continue
            size = struct.unpack_from("<I", buf, p + 4)[0]
            flags = struct.unpack_from("<I", buf, p + 8)[0]
            formid = struct.unpack_from("<I", buf, p + 12)[0]
            if buf[p:p + 4] == b"CELL" and (formid & 0xFFFFFF) in want:
                hit.setdefault(formid, {"chain": [g for g, _ in chain], "flags": flags,
                                        "size": size, "raw": bytes(buf[p:p + 24 + size]),
                                        "parent": (p, end)})
            p += 24 + size

    head = struct.unpack_from("<I", buf, 4)[0]
    pos = 24 + head
    top_groups = []
    while pos + 24 <= len(buf):
        if buf[pos:pos + 4] != b"GRUP":
            break
        gsize = struct.unpack_from("<I", buf, pos + 4)[0]
        top_groups.append((bytes(buf[pos + 8:pos + 12]).decode("latin1", "replace"),
                           struct.unpack_from("<i", buf, pos + 12)[0], gsize))
        rec(pos + 24, pos + gsize, [(struct.unpack_from("<i", buf, pos + 12)[0], bytes(buf[pos + 8:pos + 12]))])
        pos += gsize

    print(f"顶层组（{len(top_groups)} 个，顺序即文件顺序）：")
    print("   " + " | ".join(f"{lb}({gt},{sz}B)" for lb, gt, sz in top_groups[:14])
          + (" …" if len(top_groups) > 14 else ""))
    for formid, info in sorted(hit.items(), key=lambda kv: kv[0] & 0xFFFFFF):
        print(f"\n=== CELL 0x{formid:08X}（{CELL_NAMES.get(formid, '?')}） ===")
        print(f"  组链: {' > '.join(str(g) for g in info['chain'])}"
              f"（{GROUP_NAMES.get(info['chain'][-1], '?')} 是记录所在组的类型）")
        print(f"  记录: flags=0x{info['flags']:06X} size={info['size']} 头 24 B={info['raw'][:24].hex(' ')}")
        pp, pend = info["parent"]
        print("  父组（记录所在组）直接子项顺序：")
        describe_children(buf, pp, pend, "    ", 1 if BRIEF else 99)


CELL_NAMES: dict[int, str] = {}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--plugin", default=str(DEFAULT_ESM))
    ap.add_argument("--all", action="store_true", help="不做目标过滤：打印该插件里全部 CELL 记录")
    ap.add_argument("--cell", action="append", default=[],
                    help="额外的 cell FormID（可重复，如 --cell 0x0001251C）—— 用来对照官方 override")
    ap.add_argument("--brief", action="store_true", help="只列父组的直接子项（不展开 CellChildren 子树）")
    a = ap.parse_args()
    global BRIEF
    BRIEF = a.brief
    path = Path(a.plugin)
    if not path.exists():
        for root in (MODS, DATA):
            cand = list(root.rglob(path.name))
            if cand:
                path = cand[0]
                break
    if not path.exists():
        print(f"找不到插件 {a.plugin}")
        return 1

    by_edid = target_cells()
    fids = resolve_cell_formids(set(by_edid))
    CELL_NAMES.update({fid: by_edid[edid] for fid, edid in fids.items()})
    WANT.update(fids)
    for c in a.cell:
        fid = int(c, 16)
        WANT.add(fid)
        CELL_NAMES.setdefault(fid, "（--cell 指定）")
    if a.all:
        WANT.update(range(0xFFFFFF))   # 全部
    print(f"插件: {path}")
    print(f"目标 cell {len(fids)} 个: " +
          ", ".join(f"0x{f:08X}={CELL_NAMES[f]}" for f in sorted(fids)))
    print()
    scan(path.read_bytes(), WANT, only_first_subblock=False)
    return 0


if __name__ == "__main__":
    sys.exit(main())
