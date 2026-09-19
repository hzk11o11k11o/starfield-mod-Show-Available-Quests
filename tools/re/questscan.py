#!/usr/bin/env python3
"""questscan.py - 直接在 Starfield.esm 里统计 QUST 记录的子记录构成。

Why: 面包屑引导路径依赖 Papyrus 的 `Quest.GetCurrentStageTargets()`。
如果 Starfield 的任务数据里根本没有 stage target 子记录（QSTA），那这个
API 永远返回空数组 —— 必须先离线确认，别在游戏里瞎猜。

用法:
    python tools/re/questscan.py                 # QUST 子记录统计 + 样例
    python tools/re/questscan.py --samples 3
    python tools/re/questscan.py --formid 0x00227BA5   # 查某个记录（如 CELL）的 EDID
    python tools/re/questscan.py --edid MQ101          # 查某个 EDID 所属记录的签名/FormID
"""
from __future__ import annotations

import argparse
import mmap
import struct
import zlib
from collections import Counter
from pathlib import Path

DEFAULT_ESM = Path(r"D:\SteamLibrary\steamapps\common\Starfield\Data\Starfield.esm")
HDR = 24
COMPRESSED = 0x00040000


def walk_records(mm, start: int, end: int):
    """按 GRUP 结构遍历，产出 (sig, formid, flags, payload_off, data_size)。"""
    stack = [(start, end)]
    while stack:
        pos, stop = stack.pop()
        while pos + 4 <= stop:
            sig = mm[pos:pos + 4]
            if sig == b"GRUP":
                gsize = struct.unpack_from("<I", mm, pos + 4)[0]
                if gsize < 24 or pos + gsize > stop:
                    break
                stack.append((pos + 24, pos + gsize))
                pos += gsize
            else:
                if pos + HDR > stop:
                    break
                dsize, flags, formid = struct.unpack_from("<III", mm, pos + 4)
                if pos + HDR + dsize > stop:
                    break
                yield sig.decode("latin1"), formid, flags, pos + HDR, dsize
                pos += HDR + dsize


def parse_subs(mm, off: int, size: int, flags: int, decompress: bool = True):
    """返回子记录 [(sig, size)]；压缩记录先解压再解析。失败返回 None。"""
    if flags & COMPRESSED:
        if not decompress:
            return None
        raw = bytes(mm[off:off + size])
        if len(raw) < 4:
            return None
        # 前 4 字节是解压后长度
        try:
            out = zlib.decompress(raw[4:])
        except zlib.error:
            return None
        return _parse_subs_buf(out)
    return _parse_subs_buf(mm[off:off + size])


def _parse_subs_buf(buf) -> list[tuple[str, int]] | None:
    subs: list[tuple[str, int]] = []
    p = 0
    n = len(buf)
    while p + 6 <= n:
        sig = bytes(buf[p:p + 4])
        if not all((65 <= c <= 90) or (48 <= c <= 57) for c in sig):
            return None if subs == [] else subs
        sz = struct.unpack_from("<H", buf, p + 4)[0]
        if sig == b"XXXX":  # 大跨度子记录：u32 长度 + 真实 sig
            if p + 10 > n:
                return subs
            sz2 = struct.unpack_from("<I", buf, p + 6)[0]
            real = bytes(buf[p + 10:p + 14])
            subs.append((real.decode("latin1", "replace"), sz2))
            p += 10 + sz2
        else:
            if p + 6 + sz > n:
                return subs
            subs.append((sig.decode("latin1", "replace"), sz))
            p += 6 + sz
    return subs


def get_edid(mm, off: int, size: int, flags: int) -> str:
    subs = parse_subs(mm, off, size, flags)
    if not subs:
        return ""
    if flags & COMPRESSED:
        raw = bytes(mm[off:off + size])
        out = zlib.decompress(raw[4:])
        buf = out
    else:
        buf = mm[off:off + size]
    p = 0
    n = len(buf)
    while p + 6 <= n:
        sig = bytes(buf[p:p + 4])
        sz = struct.unpack_from("<H", buf, p + 4)[0]
        if sig == b"EDID":
            return bytes(buf[p + 6:p + 6 + sz]).split(b"\x00")[0].decode("latin1", "replace")
        if sig == b"XXXX":
            sz = struct.unpack_from("<I", buf, p + 6)[0]
            p += 4
        p += 6 + sz
    return ""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--esm", type=Path, default=DEFAULT_ESM)
    ap.add_argument("--samples", type=int, default=3, help="打印几个含 QSTA 的样例")
    ap.add_argument("--formid", default=None, help="查这个 FormID 的记录签名/EDID")
    ap.add_argument("--edid", default=None, help="按 EDID 反查记录")
    ap.add_argument("--grep", default=None, help="列出 EDID 含该子串的 QUST：FormID / QSTA 数 / EDID")
    args = ap.parse_args()

    with open(args.esm, "rb") as f:
        mm = mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ)

        if args.formid is not None:
            want = int(args.formid, 0)
            for sig, formid, flags, off, dsize in walk_records(mm, 0, len(mm)):
                if formid == want:
                    print(f"{sig} {formid:08X} size={dsize} flags={flags:08X} EDID='{get_edid(mm, off, dsize, flags)}'")
            return 0

        if args.edid is not None:
            needle = args.edid.encode("latin1")
            for sig, formid, flags, off, dsize in walk_records(mm, 0, len(mm)):
                if sig == "GRUP":
                    continue
                if (flags & COMPRESSED):
                    continue
                blob = mm[off:off + dsize]
                if needle in blob:
                    # 粗筛：EDID 就是它
                    print(f"{sig} {formid:08X} size={dsize} (blob 含 {args.edid})")
            return 0

        if args.grep is not None:
            needle = args.grep.lower()
            for sig, formid, flags, off, dsize in walk_records(mm, 0, len(mm)):
                if sig != "QUST":
                    continue
                edid = get_edid(mm, off, dsize, flags)
                if needle not in edid.lower():
                    continue
                subs = parse_subs(mm, off, dsize, flags) or []
                n_qsta = sum(1 for s, _ in subs if s == "QSTA")
                n_qobj = sum(1 for s, _ in subs if s == "QOBJ")
                print(f"QUST {formid:08X} QSTA={n_qsta} QOBJ={n_qobj} EDID='{edid}'")
            return 0

        # ---- QUST 统计 ----
        qst_total = 0
        qst_compressed = 0
        hist: Counter[str] = Counter()
        qst_with: Counter[str] = Counter()
        samples: list[tuple[int, str, list[str]]] = []
        record_count: Counter[str] = Counter()

        for sig, formid, flags, off, dsize in walk_records(mm, 0, len(mm)):
            record_count[sig] += 1
            if sig != "QUST":
                continue
            qst_total += 1
            if flags & COMPRESSED:
                qst_compressed += 1
            subs = parse_subs(mm, off, dsize, flags)
            if subs is None:
                continue
            sigs = [s for s, _ in subs]
            for s in set(sigs):
                hist[s] += 1
            for key in ("QSTA", "QOBJ", "ALST", "ALED", "ANAM", "INAM", "QSDT", "CTDA", "VMAD"):
                if key in sigs:
                    qst_with[key] += 1
            if "QSTA" in sigs and len(samples) < args.samples:
                edid = get_edid(mm, off, dsize, flags)
                samples.append((formid, edid, sigs))

        print(f"QUST 记录总数 = {qst_total}（压缩 {qst_compressed}）")
        print("--- 含这些子记录的 QUST 数量 ---")
        for key, cnt in qst_with.most_common():
            print(f"  {key}: {cnt}")
        print("--- QUST 子记录签名直方图（有多少个 QUST 含该签名）---")
        for s, cnt in hist.most_common(40):
            print(f"  {s}: {cnt}")
        print("--- 含 QSTA 的样例 ---")
        for formid, edid, sigs in samples:
            print(f"  QUST {formid:08X} '{edid}'")
            print(f"    {sigs}")
        print("--- 全库记录数（前 20）---")
        for s, cnt in record_count.most_common(20):
            print(f"  {s}: {cnt}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
