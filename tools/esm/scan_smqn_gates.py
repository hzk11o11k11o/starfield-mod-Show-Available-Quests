#!/usr/bin/env python3
"""scan_smqn_gates.py - 第 98 轮：扫 **Story Manager（SMQN）** 节点里的「跨任务进度门槛」。

背景：本项目「进度没到不显示」的三个数据源里，前两个是
  * 记录级 CTDA（`tools/esm/analyze_ctda.py` → `ref/ctda_gates.json`）；
  * 对话 INFO 条件（`tools/esm/scan_info_gates.py` → `ref/info_gates_final.json`）；
第三个（任务链启动边）是第 67 轮加的（Papyrus 源码 / 第 98 轮起 DLC 用反编译）。
但**任务还可能由 Story Manager 节点启动**（SMQN）——那里同样挂着 CTDA 条件，
如果条件引用的是**别的任务**，那它就是一条真实门槛（本项目此前没扫过这个来源）。

本轮实测（三个官方 DLC）：101 个 SMQN / 180 条 CTDA，其中**只有 1 条**是跨任务门槛
（`SFTER_MS01_IntroSE`：`GetQuestCompleted(SFTER_MQ01) == 1` —— 地球舰队「失踪的地球人」
要求先做完「失踪的华庭号」）；其余全是 `GetQuestRunning / GetStageDone /
GetQuestCompleted(自己)` 的**引擎启动守卫**（自引用不算门槛，见 `docs/08` 4.2）。

CTDA 布局（Starfield fver 582，同 FO4 的 32 字节）：
    +0x00 u8 operator   +0x04 f32 比较值   +0x08 u16 函数号
    +0x0C u32 param1（多数 = 目标 form id）   +0x14 u32 Run On   …
函数号 ↔ 名字的对照由 `analyze_ctda.py --funcs` 建立（同一份引擎函数表，全局通用：
实测 0x0038=GetQuestRunning / 0x003A=GetStage / 0x003B=GetStageDone /
0x021F=GetQuestCompleted）。

用法：
    python tools/esm/scan_smqn_gates.py <esm> [<esm> …] [--json out.json]
    python tools/esm/scan_smqn_gates.py "D:\\...\\Data\\SFBGS050.esm" --json ref/smqn_gates.json
"""
from __future__ import annotations

import argparse
import json
import struct
import sys
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

REC_HDR, GRP_HDR, FLAG_COMPRESSED = 24, 24, 0x00040000
MASK = 0xFFFFFF
FUNC_NAMES = {0x0038: "GetQuestRunning", 0x003A: "GetStage",
              0x003B: "GetStageDone", 0x021F: "GetQuestCompleted"}


def subrecords(payload: bytes):
    out, off, n = [], 0, len(payload)
    while off + 6 <= n:
        sig = payload[off:off + 4].decode("ascii", "replace")
        size = struct.unpack_from("<H", payload, off + 4)[0]
        if off + 6 + size > n:
            break
        out.append((sig, payload[off + 6:off + 6 + size]))
        off += 6 + size
    return out


def walk(data: bytes, want: str):
    """★ GRP 的 size 含 24 字节组头、子项紧跟其后（与 tools/re/rec_scan.py 同法）。"""
    pos = REC_HDR + struct.unpack_from("<I", data, 4)[0]

    def walk_group(gstart: int, gend: int):
        p = gstart
        while p < gend:
            if data[p:p + 4] == b"GRUP":
                gsize = struct.unpack_from("<I", data, p + 4)[0]
                if gsize < GRP_HDR or p + gsize > gend:
                    return
                yield from walk_group(p + GRP_HDR, p + gsize)
                p += gsize
            else:
                sig = data[p:p + 4].decode("ascii", "replace")
                dsize = struct.unpack_from("<I", data, p + 4)[0]
                flags = struct.unpack_from("<I", data, p + 8)[0]
                fid = struct.unpack_from("<I", data, p + 12)[0]
                payload = data[p + REC_HDR: p + REC_HDR + dsize]
                if flags & FLAG_COMPRESSED:
                    try:
                        payload = zlib.decompress(payload[4:])
                    except Exception:
                        payload = b""
                if sig == want:
                    yield fid, payload
                p = p + REC_HDR + dsize

    yield from walk_group(pos, len(data))


def func_name(idx: int) -> str:
    return FUNC_NAMES.get(idx, f"fn_0x{idx:04X}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("esm", nargs="+")
    ap.add_argument("--json", default="")
    a = ap.parse_args()

    tbl = json.loads((ROOT / "ref" / "quest_table_debug.json").read_text(encoding="utf-8"))
    by_local: dict[int, dict] = {}
    for t in tbl:
        by_local.setdefault(int(t["local"]) & MASK, t)

    out_rows = []
    for arg in a.esm:
        esm = Path(arg)
        n_nodes = n_ctda = n_cross = 0
        rows = []
        for fid, body in walk(esm.read_bytes(), "SMQN"):
            n_nodes += 1
            subs = subrecords(body)
            edid = next((s for sig, s in subs if sig == "EDID"), b"")
            edid_s = edid.decode("ascii", "replace")
            starts = [struct.unpack_from("<I", s, 0)[0] for sig, s in subs
                      if sig == "NNAM" and len(s) >= 4]
            for sig, s in subs:
                if sig != "CTDA" or len(s) < 0x20:
                    continue
                n_ctda += 1
                fn = struct.unpack_from("<H", s, 0x08)[0]
                p1 = struct.unpack_from("<I", s, 0x0C)[0]
                selfref = (p1 & MASK) == (fid & MASK) or (p1 & MASK) in [q & MASK for q in starts]
                tgt = by_local.get(p1 & MASK)
                if tgt is None or selfref:
                    continue
                n_cross += 1
                rows.append({
                    "esm": esm.name, "node": f"0x{fid & MASK:06X}", "edid": edid_s,
                    "func": func_name(fn), "func_index": fn,
                    "op": s[0], "cmp": struct.unpack_from("<f", s, 0x04)[0],
                    "quest_master": tgt["master"], "quest_local": tgt["local"] & MASK,
                    "quest_edid": tgt["edid"],
                    "starts": [by_local.get(q & MASK, {}).get("edid", f"0x{q & MASK:06X}")
                               for q in starts],
                    # ★ 关键判据：这个节点的「被启动任务」里有没有**我们表里的**任务 ——
                    #   只有这种条件才对「可接任务」列表有影响（其余节点的目标是内部任务）。
                    "starts_in_table": [by_local[q & MASK]["edid"] for q in starts
                                        if (q & MASK) in by_local],
                })
        # 表内任务受影响的排前面（肉眼可判读）
        rows.sort(key=lambda r: (not r["starts_in_table"], r["edid"]))
        n_table = sum(1 for r in rows if r["starts_in_table"])
        print(f"{esm.name}: SMQN={n_nodes} CTDA={n_ctda} **跨任务条件={n_cross}"
              f"（其中影响表内任务 {n_table}）**")
        for r in rows:
            star = "★ " if r["starts_in_table"] else "  "
            print(f"{star}{r['edid']:<32} {r['func']}({r['quest_edid']}) op=0x{r['op']:02X} "
                  f"cmp={r['cmp']:g}  starts={','.join(r['starts'])}")
        out_rows.extend(rows)

    if a.json:
        Path(a.json).write_text(json.dumps(out_rows, ensure_ascii=False, indent=1),
                                encoding="utf-8")
        print(f"wrote {a.json}（{len(out_rows)} 条）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
