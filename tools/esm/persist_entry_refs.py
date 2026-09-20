#!/usr/bin/env python3
r"""persist_entry_refs.py - 【第 30 轮起已停用：override 路线被实机否定】

★ 停用说明：本工具把 11 条非常驻任务板引用 **override** 进 `CellPersistent` 组 + flags 0x400，
  想让它们「常驻化」。2026-09-20 12:45 会话实机证明**无效**（`入口=12(可导航 2)`，10 条取不到）；
  数据侧也证明「非常驻 → 常驻」的 override 在本机**零先例**（官方 SFBGS003/008 的 70 条
  同类 override，原记录本来就全是常驻）。⇒ 现由 `tools/esm/create_board_markers.py`
  （**新建**常驻 XMarker）取代；本文件保留作历史记录 + `--clean` 备用（build-saq.ps1 已不再调用）。
  完整复盘见 docs/99 一·补十五。

（下面是第 29 轮的原始说明，保留供追溯。）

persist_entry_refs.py - 把「非常驻」的任务板入口引用 override 成**常驻引用**（第 29 轮）。

## 要解决的问题

第 27/28 轮：12 条任务板入口里 11 条是**非常驻引用**（位于 cell 的 CellTemporary 组），
玩家离得远、cell 未加载时，脚本 `Game.GetForm` / DLL `LookupByID` 都取不到
（实测 `脚本状态=2`，蓝点不动）。玩家反馈：

> 「我现在就是亚特兰蒂斯城，但却还是无法导航，而且也不应该存在所谓『太远就无法导航』。」

⇒ 治本 = 让这 11 条引用**常驻**（persistent 引用在任何位置都被引擎加载）。

## 怎么修（写法抄官方 Creation，不是自创）

在 `esm/SAQ_ShowAvailableQuests.esm` 里写这 11 条 REFR 的 **override**：

* 记录字节**照抄** `Starfield.esm`（位置等字段一律不动），只把 record flags |= 0x400；
* 放进与 master 相同的组路径：
  `GRUP Top 'CELL' > InteriorBlock > InteriorSubBlock > CellChildren > CellPersistent`
  （组头的时间戳等字段同样照抄原文件，只改 size/label/type）；
* HEDR 的 numRecords 按「MAST 数 + 记录总数」重算。

**先例（本机可复现）**：`tools/esm/scan_override_persistent.py` 扫出官方 Creation
`SFBGS003.esm` 有 66 条同款记录（override 基础游戏引用 + CellPersistent 组 + flags 0x400），
`SFBGS008.esm` 4 条 —— 官方插件确实用这个写法把基础游戏引用改成常驻。

## 幂等 / 运行顺序

* 每次运行先删掉文件里已有的顶部 `CELL` 组，再按 `ref/entry_targets.json` 重建；
  只处理 `persistent=false` 的条目（阿基拉城本来就是常驻，不需要也不去动它）。
* ★ 必须在 `patch_saq_esm.py` **之后**运行：那个工具用「线性重建」处理顶层组，
  不认识嵌套组（CELL 组是嵌套结构，先跑它会破坏结构）。`build-saq.ps1` 里顺序已固定。

用法：
    python tools/esm/persist_entry_refs.py            # 幂等重建
    python tools/esm/persist_entry_refs.py --check    # 只解析打印当前状态
    python tools/esm/persist_entry_refs.py --clean    # 只移除 CELL override 组
"""
from __future__ import annotations

import argparse
import json
import struct
import sys
from collections import OrderedDict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from esm_probe import DEFAULT_ESM  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
TARGET_ESM = ROOT / "esm" / "SAQ_ShowAvailableQuests.esm"
ENTRY_JSON = ROOT / "ref" / "entry_targets.json"

REF_SIGS = (b"REFR", b"ACHR", b"PGRE", b"PMIS", b"PARW", b"PBAR", b"PHZD")
PERSISTENT_FLAG = 0x400

GROUP_NAMES = {0: "Top", 2: "InteriorBlock", 3: "InteriorSubBlock", 4: "ExteriorBlock",
               5: "ExteriorSubBlock", 6: "CellChildren", 8: "CellPersistent", 9: "CellTemporary"}


# ---------------------------------------------------------------------------
#  读 Starfield.esm：目标 REFR 的原始字节 + 组头模板
# ---------------------------------------------------------------------------
def scan_starfield(buf: bytes, want: set[int]) -> dict[int, dict]:
    """返回 {记录号低24位: {"raw": 记录字节(含头), "chain": [(gtype,label,hdr), …]}}。"""
    found: dict[int, dict] = {}

    def rec(p: int, end: int, chain: list, cell: int, world: int) -> None:
        while p + 24 <= end:
            if buf[p:p + 4] == b"GRUP":
                sub = struct.unpack_from("<I", buf, p + 4)[0]
                if sub < 24:
                    return
                label = bytes(buf[p + 8:p + 12])
                gtype = struct.unpack_from("<i", buf, p + 12)[0]
                hdr = bytes(buf[p:p + 24])
                rec(p + 24, p + sub, chain + [(gtype, label, hdr)], cell, world)
                p += sub
                continue
            size = struct.unpack_from("<I", buf, p + 4)[0]
            formid = struct.unpack_from("<I", buf, p + 12)[0]
            sig = bytes(buf[p:p + 4])
            if sig in REF_SIGS and (formid >> 24) == 0 and (formid & 0xFFFFFF) in want:
                found[formid & 0xFFFFFF] = {"raw": bytes(buf[p:p + 24 + size]), "chain": list(chain)}
            p += 24 + size

    head_size = struct.unpack_from("<I", buf, 4)[0]
    pos = 24 + head_size
    while pos + 24 <= len(buf):
        if buf[pos:pos + 4] != b"GRUP":
            break
        gsize = struct.unpack_from("<I", buf, pos + 4)[0]
        label = bytes(buf[pos + 8:pos + 12])
        gtype = struct.unpack_from("<i", buf, pos + 12)[0]
        rec(pos + 24, pos + gsize, [(gtype, label, bytes(buf[pos:pos + 24]))], 0, 0)
        pos += gsize
    return found


# ---------------------------------------------------------------------------
#  构造 override 组树
# ---------------------------------------------------------------------------
def make_grup(label, gtype: int, tmpl: bytes, children: bytes) -> bytes:
    """用原组头作模板（时间戳等照抄），只改 sig/size/label/type。label: bytes(4) 或 int。"""
    hdr = bytearray(tmpl)
    hdr[0:4] = b"GRUP"
    hdr[4:8] = struct.pack("<I", 24 + len(children))
    hdr[8:12] = label if isinstance(label, bytes) else struct.pack("<i", label)
    hdr[12:16] = struct.pack("<i", gtype)
    return bytes(hdr) + children


def build_cell_override_group(items: list[tuple[list, bytes]]) -> bytes:
    """items = [(chain, raw_refr)] → 一棵 `Top 'CELL' > … > CellPersistent > REFR` 组树。"""
    blocks: OrderedDict = OrderedDict()
    top_tmpl = None
    for chain, raw in items:
        gtypes = [g for g, _, _ in chain]
        if len(chain) < 5 or chain[-1][0] not in (8, 9):
            raise SystemExit(f"组链不符合预期（需要 …CellChildren > CellPersistent/Temporary）：{gtypes}")
        blk, sub, cellchild, children = chain[-4], chain[-3], chain[-2], chain[-1]
        if not (blk[0] == 2 and sub[0] == 3 and cellchild[0] == 6):
            raise SystemExit(f"组链不符合预期（内部 cell 的 block/subblock/cellchildren）：{gtypes}")
        top_tmpl = top_tmpl or chain[0][2]
        cell_label = struct.unpack_from("<i", cellchild[1])[0]
        b = blocks.setdefault((blk[1], sub[1]), {"blk": blk[2], "sub": sub[2], "cells": OrderedDict()})
        c = b["cells"].setdefault(cell_label, {"cc": cellchild[2], "ch": children[2], "refs": []})
        rec = bytearray(raw)
        flags = struct.unpack_from("<I", rec, 8)[0]
        struct.pack_into("<I", rec, 8, flags | PERSISTENT_FLAG)
        c["refs"].append(bytes(rec))

    top_children = bytearray()
    for (blk_label, sub_label), b in blocks.items():
        sub_children = bytearray()
        for cell_label, c in b["cells"].items():
            persist_grup = make_grup(cell_label, 8, c["ch"], b"".join(c["refs"]))
            cc_grup = make_grup(cell_label, 6, c["cc"], persist_grup)
            sub_children += cc_grup
        sub_grup = make_grup(sub_label, 3, b["sub"], bytes(sub_children))
        blk_grup = make_grup(blk_label, 2, b["blk"], sub_grup)
        top_children += blk_grup
    return make_grup(b"CELL", 0, top_tmpl, bytes(top_children))


# ---------------------------------------------------------------------------
#  目标 ESM：顶层组拆分 / 记录计数 / HEDR
# ---------------------------------------------------------------------------
def split_top_groups(buf: bytes):
    head_size = struct.unpack_from("<I", buf, 4)[0]
    head = bytes(buf[:24 + head_size])
    groups = []
    pos = 24 + head_size
    while pos + 24 <= len(buf):
        if buf[pos:pos + 4] != b"GRUP":
            raise SystemExit(f"顶层不是 GRUP @0x{pos:X} —— 文件坏了")
        gsize = struct.unpack_from("<I", buf, pos + 4)[0]
        label = bytes(buf[pos + 8:pos + 12])
        gtype = struct.unpack_from("<i", buf, pos + 12)[0]
        groups.append((label, gtype, bytes(buf[pos:pos + gsize])))
        pos += gsize
    return head, groups


def count_records_and_mast(head: bytes, groups: list) -> tuple[int, int]:
    def count_in(p: int, end: int, buf: bytes) -> int:
        n = 0
        while p + 24 <= end:
            if buf[p:p + 4] == b"GRUP":
                sub = struct.unpack_from("<I", buf, p + 4)[0]
                if sub < 24:
                    break
                n += count_in(p + 24, p + sub, buf)
                p += sub
                continue
            size = struct.unpack_from("<I", buf, p + 4)[0]
            n += 1
            p += 24 + size
        return n

    total = 0
    for _label, _gtype, raw in groups:
        total += count_in(24, len(raw), raw)
    n_mast = 0
    size = struct.unpack_from("<I", head, 4)[0]
    p = 24
    end = 24 + size
    while p + 6 <= end:
        sig = head[p:p + 4]
        n = struct.unpack_from("<H", head, p + 4)[0]
        if sig == b"MAST":
            n_mast += 1
        p += 6 + n
    return total, n_mast


def write_hedr_num_records(head: bytearray, num: int) -> int:
    size = struct.unpack_from("<I", head, 4)[0]
    p = 24
    end = 24 + size
    while p + 6 <= end:
        sig = bytes(head[p:p + 4])
        n = struct.unpack_from("<H", head, p + 4)[0]
        if sig == b"HEDR" and n >= 12:
            old = struct.unpack_from("<I", head, p + 6 + 4)[0]
            struct.pack_into("<I", head, p + 6 + 4, num)
            return old
        p += 6 + n
    raise SystemExit("TES4 里没有 HEDR")


# ---------------------------------------------------------------------------
#  校验
# ---------------------------------------------------------------------------
def verify(buf: bytes, expect: dict[int, dict]) -> list[str]:
    """检查 override 记录：存在、flags、组链。返回问题列表（空 = 通过）。"""
    problems: list[str] = []
    seen: dict[int, dict] = {}

    def rec(p: int, end: int, chain: list) -> None:
        while p + 24 <= end:
            if buf[p:p + 4] == b"GRUP":
                sub = struct.unpack_from("<I", buf, p + 4)[0]
                if sub < 24 or p + sub > end:
                    problems.append(f"GRUP @0x{p:X} size={sub} 越界")
                    return
                label = bytes(buf[p + 8:p + 12])
                gtype = struct.unpack_from("<i", buf, p + 12)[0]
                rec(p + 24, p + sub, chain + [(gtype, label)])
                p += sub
                continue
            size = struct.unpack_from("<I", buf, p + 4)[0]
            flags = struct.unpack_from("<I", buf, p + 8)[0]
            formid = struct.unpack_from("<I", buf, p + 12)[0]
            if bytes(buf[p:p + 4]) in REF_SIGS and (formid & 0xFFFFFF) in expect:
                seen[formid & 0xFFFFFF] = {"flags": flags, "chain": list(chain)}
            p += 24 + size

    head_size = struct.unpack_from("<I", buf, 4)[0]
    pos = 24 + head_size
    while pos + 24 <= len(buf):
        if buf[pos:pos + 4] != b"GRUP":
            problems.append(f"顶层 @0x{pos:X} 不是 GRUP")
            break
        gsize = struct.unpack_from("<I", buf, pos + 4)[0]
        if pos + gsize > len(buf):
            problems.append(f"顶层 GRUP @0x{pos:X} size 越界")
            break
        rec(pos + 24, pos + gsize, [(struct.unpack_from("<i", buf, pos + 12)[0], bytes(buf[pos + 8:pos + 12]))])
        pos += gsize

    for low, meta in expect.items():
        got = seen.get(low)
        if got is None:
            problems.append(f"{meta['nameZh']}（0x{low:06X}）没有 override 记录")
            continue
        if not (got["flags"] & PERSISTENT_FLAG):
            problems.append(f"{meta['nameZh']}（0x{low:06X}）flags=0x{got['flags']:X} 缺 0x400")
        chain = got["chain"]
        want_tail = [2, 3, 6, 8]
        if [g for g, _ in chain][-4:] != want_tail:
            problems.append(f"{meta['nameZh']}（0x{low:06X}）组链尾部不是 "
                            f"{want_tail}（实际 {[g for g, _ in chain]}）")
    return problems


def describe(path: Path) -> int:
    buf = path.read_bytes()
    head, groups = split_top_groups(buf)
    n_rec, n_mast = count_records_and_mast(head, groups)
    print(f"{path}（{len(buf)} B）记录 {n_rec} + MAST {n_mast}")
    for label, gtype, raw in groups:
        gsize = struct.unpack_from("<I", raw, 4)[0]
        tag = label.decode("latin1", "replace")
        print(f"  GRUP {tag:<6s} type={gtype:<3d} size={gsize}")
        if tag == "CELL":
            def dump(p: int, end: int, depth: int) -> None:
                while p + 24 <= end:
                    if raw[p:p + 4] == b"GRUP":
                        sub = struct.unpack_from("<I", raw, p + 4)[0]
                        gl = bytes(raw[p + 8:p + 12])
                        gt = struct.unpack_from("<i", raw, p + 12)[0]
                        gl_s = gl.decode("latin1", "replace") if gt == 0 else str(struct.unpack("<i", gl)[0])
                        print("    " * (depth + 1) + f"{GROUP_NAMES.get(gt, gt)}({gl_s}) size={sub}")
                        dump(p + 24, p + sub, depth + 1)
                        p += sub
                        continue
                    size = struct.unpack_from("<I", raw, p + 4)[0]
                    flags = struct.unpack_from("<I", raw, p + 8)[0]
                    formid = struct.unpack_from("<I", raw, p + 12)[0]
                    sig = bytes(raw[p:p + 4]).decode("latin1")
                    print("    " * (depth + 1) + f"{sig} 0x{formid:08X} flags=0x{flags:06X} size={size}")
                    p += 24 + size
            dump(24, len(raw), 0)
    return 0


# ---------------------------------------------------------------------------
def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--esm", default=str(TARGET_ESM))
    ap.add_argument("--check", action="store_true", help="只解析打印当前状态")
    ap.add_argument("--clean", action="store_true", help="只把 CELL override 组删掉")
    a = ap.parse_args()
    target = Path(a.esm)
    if not target.exists():
        print(f"没有 {target}（先跑 tools/run-esm-build.ps1 + patch_saq_esm.py）")
        return 1
    if a.check:
        return describe(target)

    entries = json.loads(ENTRY_JSON.read_text(encoding="utf-8"))
    to_persist = {e["refLocal"]: e for e in entries if not e["persistent"]}
    names = {e["refLocal"]: e["nameZh"] for e in entries}

    buf = target.read_bytes()
    head, groups = split_top_groups(buf)

    # MAST[0] 必须是 Starfield.esm（override 记录的 FormID 高位 = 0）
    masters = []
    size = struct.unpack_from("<I", head, 4)[0]
    p = 24
    while p + 6 <= 24 + size:
        sig = head[p:p + 4]
        n = struct.unpack_from("<H", head, p + 4)[0]
        if sig == b"MAST":
            masters.append(head[p + 6:p + 6 + n].split(b"\x00")[0].decode("latin1"))
        p += 6 + n
    if not masters or masters[0].lower() != b"starfield.esm".decode("latin1"):
        raise SystemExit(f"MAST[0] 不是 Starfield.esm（实际 {masters}）—— override 前提不成立")

    n_old_cell = sum(1 for lb, _, _ in groups if lb == b"CELL")
    rest = [(lb, gt, raw) for lb, gt, raw in groups if lb != b"CELL"]

    if a.clean:
        out = bytearray(head)
        for _lb, _gt, raw in rest:
            out += raw
        n_rec, n_mast = count_records_and_mast(bytes(out[:24 + size]), rest)
        old = write_hedr_num_records(out, n_rec + n_mast)
        target.write_bytes(bytes(out))
        print(f"移除 CELL 组 {n_old_cell} 个（numRecords {old} -> {n_rec + n_mast}，{len(out)} B）")
        return 0

    if not to_persist:
        print("entry_targets.json 里没有需要常驻化的条目（都已经是 persistent）")
        return 0

    # 快速路径：文件里已有**正确**的 CELL override 组 ⇒ 不必再读 1.4 GB 的 Starfield.esm
    if n_old_cell == 1 and not verify(buf, to_persist):
        print(f"常驻化 override 已是最新（{len(to_persist)} 条，CellPersistent + 0x400）—— 跳过重建")
        return 0

    print(f"移除旧 CELL 组 {n_old_cell} 个")
    groups = rest
    print(f"读 {Path(DEFAULT_ESM).name}（约 1~2 分钟）…")
    src = Path(DEFAULT_ESM).read_bytes()
    found = scan_starfield(src, set(to_persist))
    missing = [low for low in to_persist if low not in found]
    if missing:
        raise SystemExit("Starfield.esm 里没找到：" + ", ".join(f"0x{m:06X}" for m in missing))

    items = [(found[low]["chain"], found[low]["raw"]) for low in to_persist]
    cell_group = build_cell_override_group(items)
    print(f"新建 CELL override 组：{len(cell_group)} B / {len(items)} 条记录")
    for low in to_persist:
        ch = [GROUP_NAMES.get(g, g) for g, _, _ in found[low]["chain"]]
        print(f"  {to_persist[low]['nameZh']:<22s} 0x{low:06X} 原组链={' > '.join(map(str, ch))}")

    out = bytearray(head)
    for _lb, _gt, raw in groups:
        out += raw
    out += cell_group

    n_rec, n_mast = count_records_and_mast(bytes(out[:24 + size]), groups + [(b"CELL", 0, cell_group)])
    old = write_hedr_num_records(out, n_rec + n_mast)
    print(f"numRecords {old} -> {n_rec + n_mast}")

    result = bytes(out)
    problems = verify(result, to_persist)
    if problems:
        print("\n!! 自校验失败：")
        for p in problems:
            print("   -", p)
        return 1

    target.write_bytes(result)
    print(f"已写回 {target}（{len(result)} B）\n")
    print("--- 自校验通过（重新解析） ---")
    describe(target)
    return 0


if __name__ == "__main__":
    sys.exit(main())
