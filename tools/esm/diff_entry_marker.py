#!/usr/bin/env python3
r"""diff_entry_marker.py - 对比「新建常驻 marker」与 Starfield.esm 里**同 cell 的真实记录 / 组头**。

第 31 轮实机反馈：任务板的蓝点偏在板子旁边（引导目标走了「兜底」引用），
DLL 日志里 11 条新建 marker **全部 `marker[未命中]`**：

    入口=12(可导航 12｜marker 0 原板 2 兜底 10 不可用 0)

也就是说「本插件新建的常驻 XMarker（记录号 0x900~0x90A）」在引擎里根本取不到，
于是引导只能落到「同 cell 里离板最近的原生常驻引用」（1~8 m 外）⇒ 蓝点偏移。

本工具回答「为什么取不到」这个问题里**数据侧能回答的部分**：

1. 我们的 marker 记录所在组链（`CELL > InteriorBlock > InteriorSubBlock > CellChildren >
   CellPersistent`）—— 组头的 **label 原始 4 字节**与 Starfield.esm 里同一 cell 的真实
   组头是否一致？（label 写错 ⇒ 引擎根本不把这些组当「该 cell 的常驻子组」）
2. 组链里的 `InteriorBlock/InteriorSubBlock` 编号是否与真实一致？
3. 记录本身：flags / base / DATA 长度与子记录构成，跟 Starfield.esm 里的原生常驻引用比，
   有没有缺东西？

用法：
    python tools/esm/diff_entry_marker.py              # 全部 11 条（1~2 分钟）
    python tools/esm/diff_entry_marker.py --only 137573
"""
from __future__ import annotations

import argparse
import json
import struct
import sys
import zlib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from esm_probe import DEFAULT_ESM, subrecords  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
OUR_ESM = ROOT / "esm" / "SAQ_ShowAvailableQuests.esm"
TARGETS = ROOT / "ref" / "entry_targets.json"
MARKERS = ROOT / "ref" / "board_markers.json"
SCAN = ROOT / "ref" / "entry_persistent_scan.json"

REF_SIGS = (b"REFR", b"ACHR", b"PGRE", b"PMIS", b"PARW", b"PBAR", b"PHZD")


def label_of(hdr: bytes) -> str:
    val = struct.unpack_from("<i", hdr, 8)[0]
    return f"{val} (0x{val & 0xFFFFFFFF:08X})"


def walk_cell_group(buf: bytes, want_cells: set[int], on_group, on_ref) -> None:
    """只遍历顶层 `CELL` 组，且只回调 cell FormID 在 want_cells 里的组与引用。"""
    head_size = struct.unpack_from("<I", buf, 4)[0]
    pos = 24 + head_size
    while pos + 24 <= len(buf):
        if buf[pos:pos + 4] != b"GRUP":
            return
        gsize = struct.unpack_from("<I", buf, pos + 4)[0]
        if gsize < 24 or pos + gsize > len(buf):
            return
        if bytes(buf[pos + 8:pos + 12]) == b"CELL":
            _rec(buf, pos + 24, pos + gsize, [(0, bytes(buf[pos:pos + 24]))],
                 0, want_cells, on_group, on_ref)
            return
        pos += gsize


def _rec(buf, p, end, chain, cell, want_cells, on_group, on_ref) -> None:
    while p + 24 <= end:
        if buf[p:p + 4] == b"GRUP":
            sub = struct.unpack_from("<I", buf, p + 4)[0]
            if sub < 24 or p + sub > end:
                return
            gtype = struct.unpack_from("<i", buf, p + 12)[0]
            hdr = bytes(buf[p:p + 24])
            ncell = cell
            if gtype == 6:                       # CellChildren：label = cell FormID
                ncell = struct.unpack_from("<i", hdr, 8)[0]
                if ncell not in want_cells:      # 不关心的 cell：整棵子树跳过
                    p += sub
                    continue
            if ncell and ncell in want_cells and gtype in (6, 8, 9, 10):
                on_group(ncell, chain + [(gtype, hdr)])
            _rec(buf, p + 24, p + sub, chain + [(gtype, hdr)], ncell, want_cells, on_group, on_ref)
            p += sub
            continue
        size = struct.unpack_from("<I", buf, p + 4)[0]
        if size > 0x1000000:                      # 明显异常，避免越界乱走
            return
        flags = struct.unpack_from("<I", buf, p + 8)[0]
        formid = struct.unpack_from("<I", buf, p + 12)[0]
        sig = bytes(buf[p:p + 4])
        if cell and cell in want_cells and sig in REF_SIGS:
            payload = None
            if flags & 0x00040000:
                if size >= 4:
                    try:
                        payload = zlib.decompress(buf[p + 28:p + 24 + size])
                    except zlib.error:
                        payload = None
            else:
                payload = bytes(buf[p + 24:p + 24 + size])
            if payload is not None:
                on_ref(cell, sig, formid, flags, payload)
        p += 24 + size


def collect(buf: bytes, want_cells: set[int], ref_limit: int) -> dict:
    """{cell: {"groups": [(gtype, 组链, 组头)], "refs": [样本]}}"""
    out: dict[int, dict] = {}

    def on_group(cell, chain):
        out.setdefault(cell, {"groups": [], "refs": []})["groups"].append(chain)

    def on_ref(cell, sig, formid, flags, payload):
        g = out.setdefault(cell, {"groups": [], "refs": []})
        if len(g["refs"]) >= ref_limit:
            return
        subs = [(s.decode("latin1"), len(d)) for s, d in subrecords(payload)]
        base, pos = 0, None
        for s, d in subrecords(payload):
            if s == b"NAME" and len(d) >= 4:
                base = struct.unpack_from("<I", d, 0)[0]
            if s == b"DATA" and len(d) >= 12:
                pos = struct.unpack_from("<fff", d, 0)
        g["refs"].append({"sig": sig.decode("latin1"), "formid": formid, "flags": flags,
                          "base": base, "subs": subs, "pos": pos})

    walk_cell_group(buf, want_cells, on_group, on_ref)
    return out


def key_of(chain) -> tuple:
    return tuple(g for g, _ in chain)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default="", help="只看某个任务板记录号（十六进制，可省 0x）")
    ap.add_argument("--ref-limit", type=int, default=2, help="每个 cell 打印多少条参考引用")
    a = ap.parse_args()

    entries = json.loads(TARGETS.read_text(encoding="utf-8"))
    markers = {m["refLocal"]: m for m in json.loads(MARKERS.read_text(encoding="utf-8"))["markers"]}
    scan = json.loads(SCAN.read_text(encoding="utf-8"))
    cell_of_board = {int(info["board"], 16): int(cell_hex, 16)
                     for cell_hex, info in scan["cells"].items()}

    only = int(a.only, 16) if a.only else None
    want_cells = {cell_of_board[e["refLocal"]] for e in entries
                  if e["refLocal"] in cell_of_board and (only is None or e["refLocal"] == only)}
    print(f"要对比的 cell：{len(want_cells)} 个")

    print(f"读 {Path(DEFAULT_ESM).name}（约 1~2 分钟）…")
    real = collect(Path(DEFAULT_ESM).read_bytes(), want_cells, a.ref_limit)
    ours = collect(OUR_ESM.read_bytes(), want_cells, 3)

    bad = 0
    for e in entries:
        if only is not None and e["refLocal"] != only:
            continue
        cell = cell_of_board.get(e["refLocal"])
        if cell is None:
            continue
        r, o = real.get(cell), ours.get(cell)
        print(f"\n=== {e['nameZh']}（板 0x{e['refLocal']:06X}，cell 0x{cell:08X} {e['cell']}）===")
        if not o:
            print("  !! 我们的 ESM 里这个 cell 没有组/记录")
            bad += 1
            continue
        rchains = {key_of(c): c for c in (r["groups"] if r else [])}
        ochains = {key_of(c): c for c in o["groups"]}
        for key in sorted(set(ochains) | set(rchains), key=lambda t: (len(t), t)):
            rc, oc = rchains.get(key), ochains.get(key)
            real_label = label_of(rc[-1][1]) if rc else "（无）"
            our_label = label_of(oc[-1][1]) if oc else "（无）"
            same = real_label == our_label
            flag = "" if same else "   ← label 不一致"
            print(f"  chain{list(key)} 末尾组 label: 真实={real_label} 我们={our_label}{flag}")
            if rc and oc and not same:
                bad += 1
        print("  我们新建的记录：")
        for info in o["refs"]:
            print(f"    {info['sig']} 0x{info['formid']:08X} flags=0x{info['flags']:06X} "
                  f"base=0x{info['base']:08X} pos={info['pos']}")
            print(f"      子记录: {info['subs']}")
        if r:
            print("  同 cell 的原生常驻引用样本：")
            for info in r["refs"]:
                print(f"    {info['sig']} 0x{info['formid']:08X} flags=0x{info['flags']:06X} "
                      f"base=0x{info['base']:08X} pos={info['pos']}")
                print(f"      子记录: {info['subs']}")
    print(f"\n结论：{'组头 label 存在不一致（见 ← 标记）' if bad else '组头 label 与真实文件一致'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
