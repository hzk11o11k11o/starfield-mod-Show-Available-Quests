#!/usr/bin/env python3
r"""dump_refr.py - dump 一条放置引用（REFR/ACHR…）的完整字节结构与子记录（第 30 轮）。

## 用途

「新建常驻引用」（把 XMarker 放到任务板坐标上）需要照抄**同类引用的字节形状**：
* 模板：base = XMarker(0x3B) / XMarkerHeading(0x34) 的普通引用 → 看子记录有哪些；
* 坐标来源：12 条任务板的 DATA（pos/rot）。

用法：
    python tools/esm/dump_refr.py 0014D497                 # 按 FormID（Starfield.esm）
    python tools/esm/dump_refr.py 0014D497 0008C56D 002C14F
    python tools/esm/dump_refr.py --base 0x3b --limit 3    # 找几条 base=XMarker 的样本
"""
from __future__ import annotations

import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from esm_probe import DEFAULT_ESM, ascii_z, record_base_form, record_edid, subrecords  # noqa: E402
from scan_entry_persistent import GROUP_NAMES, walk  # noqa: E402


def show(formid_want: int, buf: bytes) -> None:
    hit = {}

    def cb(sig, formid, flags, chain, cell, world, payload):
        if formid == formid_want:
            hit["sig"] = sig
            hit["flags"] = flags
            hit["chain"] = chain
            hit["cell"] = cell
            hit["world"] = world
            hit["payload"] = payload
            hit["raw_size"] = len(payload)

    walk(buf, cb)
    if not hit:
        print(f"!! 没找到 REFR 0x{formid_want:08X}")
        return
    chain = " > ".join(
        (lab.decode("latin1", "replace") if g in (0,) else GROUP_NAMES.get(g, f"?{g}"))
        for g, lab in hit["chain"])
    print(f"=== REFR 0x{formid_want:08X} {hit['sig'].decode('latin1')} flags=0x{hit['flags']:06X} "
          f"cell=0x{hit['cell']:08X} world=0x{hit['world']:08X} 组链={chain}")
    print(f"    EDID={record_edid(hit['payload'])!r} base=0x{record_base_form(hit['payload']):08X} "
          f"payload={hit['raw_size']} B")
    for s, sp in subrecords(hit["payload"]):
        hexs = sp[:48].hex(" ")
        tail = " …" if len(sp) > 48 else ""
        print(f"    {s.decode('latin1')} len={len(sp):<3d} {hexs}{tail}")


def scan_base(base: int, buf: bytes, limit: int) -> None:
    n = 0

    def cb(sig, formid, flags, chain, cell, world, payload):
        nonlocal n
        if record_base_form(payload) != base:
            return
        n += 1
        if n <= limit:
            chain_s = " > ".join(GROUP_NAMES.get(g, str(g)) for g, _ in chain)
            subs = [s.decode("latin1") for s, _ in subrecords(payload)]
            print(f"  {sig.decode('latin1')} 0x{formid:08X} flags=0x{flags:06X} edid={record_edid(payload)!r} "
                  f"cell=0x{cell:08X} 组链={chain_s}")
            print(f"      子记录={subs}")

    walk(buf, cb)
    print(f"  （base=0x{base:X} 的引用共 {n} 条）")


def main() -> int:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if "--base" in sys.argv:
        i = sys.argv.index("--base")
        base = int(sys.argv[i + 1], 16)
        limit = 3
        if "--limit" in sys.argv:
            limit = int(sys.argv[sys.argv.index("--limit") + 1])
        print(f"读 {DEFAULT_ESM} …")
        buf = Path(DEFAULT_ESM).read_bytes()
        scan_base(base, buf, limit)
        return 0
    if not args:
        print(__doc__)
        return 1
    wants = [int(a, 16) & 0xFFFFFF for a in args]
    print(f"读 {DEFAULT_ESM} …")
    buf = Path(DEFAULT_ESM).read_bytes()
    for w in wants:
        show(w, buf)
    return 0


if __name__ == "__main__":
    sys.exit(main())
