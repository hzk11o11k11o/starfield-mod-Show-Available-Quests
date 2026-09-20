#!/usr/bin/env python3
r"""check_persist_precedent.py - 验证「override 成常驻」是否有真先例（第 30 轮）。

## 背景

第 29 轮把 11 条任务板 REFR 用 override + `CellPersistent` 组 + flags 0x400 的方式
「常驻化」（写法参考 SFBGS003.esm 里 66 条同款记录）。实机结果（12:45/12:47 会话）：

    入口=12(可导航 2) 入口不可导航: 任务板 · 新亚特兰蒂斯城[0x0021001E] …（10 条）

⇒ override **没有**让引擎在 cell 未加载时暴露这些引用。

## 本脚本要回答的问题

SFBGS003 / SFBGS008 里那些「override 引用 + 常驻组」的记录，**在 Starfield.esm 里
原本是什么状态**？

* 如果原本就是「常驻组 + 0x400」⇒ 官方只是改了别的字段、保持常驻，
  **「把非常驻改成常驻」在本机没有任何先例** ⇒ 第 29 轮方案的前提不成立。
* 如果原记录在临时组（非常驻）⇒ 官方真做过这个转换，那问题在别处（组结构细节）。

用法：
    python tools/esm/check_persist_precedent.py            # 扫 SFBGS003 / SFBGS008 + Starfield
    python tools/esm/check_persist_precedent.py --self     # 额外检查我们自己的 ESM
"""
from __future__ import annotations

import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from esm_probe import DEFAULT_ESM, REF_SIGS  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
DATA = Path(r"D:\SteamLibrary\steamapps\common\Starfield\Data")

GROUP_NAMES = {0: "Top", 1: "WorldChildren", 2: "InteriorBlock", 3: "InteriorSubBlock",
               4: "ExteriorBlock", 5: "ExteriorSubBlock", 6: "CellChildren",
               7: "TopicChildren", 8: "CellPersistent", 9: "CellTemporary",
               10: "CellVisibleDistant"}


def walk_raw(buf: bytes, cb):
    """不解压 payload 的极简遍历（只为 sig/flags/formid/组链），比 scan_entry_persistent.walk 快。"""
    head = struct.unpack_from("<I", buf, 4)[0]
    pos = 24 + head
    while pos + 24 <= len(buf):
        if buf[pos:pos + 4] != b"GRUP":
            break
        gsize = struct.unpack_from("<I", buf, pos + 4)[0]
        if gsize < 24:
            break
        label = bytes(buf[pos + 8:pos + 12])
        gtype = struct.unpack_from("<i", buf, pos + 12)[0]
        _rec(buf, pos + 24, pos + gsize, [(gtype, label)], cb)
        pos += gsize


def _rec(buf, p, end, chain, cb):
    while p + 24 <= end:
        if buf[p:p + 4] == b"GRUP":
            sub = struct.unpack_from("<I", buf, p + 4)[0]
            if sub < 24:
                return
            label = bytes(buf[p + 8:p + 12])
            gtype = struct.unpack_from("<i", buf, p + 12)[0]
            _rec(buf, p + 24, p + sub, chain + [(gtype, label)], cb)
            p += sub
            continue
        size = struct.unpack_from("<I", buf, p + 4)[0]
        flags = struct.unpack_from("<I", buf, p + 8)[0]
        formid = struct.unpack_from("<I", buf, p + 12)[0]
        sig = bytes(buf[p:p + 4])
        cb(sig, formid, flags, chain)
        p += 24 + size


def collect_plugin(path: Path) -> list[tuple[int, int, list[int]]]:
    """返回 [(formid, flags, chain_types)]，只看「override 基础游戏 + 常驻组」的引用。"""
    buf = path.read_bytes()
    out: list[tuple[int, int, list[int]]] = []

    def cb(sig, formid, flags, chain):
        if sig not in REF_SIGS or (formid >> 24) != 0:
            return
        types = [g for g, _ in chain]
        if types and types[-1] == 8:
            out.append((formid, flags, types))

    walk_raw(buf, cb)
    return out


def lookup_in_starfield(buf: bytes, want: set[int]) -> dict[int, tuple[int, list[int]]]:
    """在 Starfield.esm 里查这些 formid 的原始 flags / 组链（一次遍历）。"""
    found: dict[int, tuple[int, list[int]]] = {}

    def cb(sig, formid, flags, chain):
        if sig in REF_SIGS and (formid >> 24) == 0 and (formid & 0xFFFFFF) in want:
            found[formid & 0xFFFFFF] = (flags, [g for g, _ in chain])

    walk_raw(buf, cb)
    return found


def chain_name(types: list[int]) -> str:
    return " > ".join(GROUP_NAMES.get(t, f"?{t}") for t in types)


def main() -> int:
    targets = ["SFBGS003.esm", "SFBGS008.esm"]
    if "--self" in sys.argv:
        targets.append(str(ROOT / "esm" / "SAQ_ShowAvailableQuests.esm"))

    collected: dict[str, list] = {}
    for t in targets:
        p = Path(t) if Path(t).is_absolute() else DATA / t
        if not p.exists():
            print(f"!! 找不到 {p}")
            continue
        lst = collect_plugin(p)
        collected[p.name] = lst
        print(f"{p.name}: override+常驻组的引用 = {len(lst)} 条")

    want: set[int] = set()
    for lst in collected.values():
        want |= {fid & 0xFFFFFF for fid, _, _ in lst}
    if not want:
        return 0

    print(f"\n读 {DEFAULT_ESM} 查原记录（{len(want)} 个 FormID）…")
    sf = Path(DEFAULT_ESM).read_bytes()
    orig = lookup_in_starfield(sf, want)
    print(f"Starfield.esm 里找到原记录 {len(orig)}/{len(want)} 条\n")

    for name, lst in collected.items():
        if not lst:
            continue
        print(f"=== {name} ===")
        n_was_pers = n_was_temp = n_missing = 0
        shown = 0
        for fid, flags, types in lst:
            low = fid & 0xFFFFFF
            o = orig.get(low)
            if o is None:
                n_missing += 1
                kind = "None(新记录?)"
                oflags, otypes = 0, []
            else:
                oflags, otypes = o
                o_pers = bool(oflags & 0x400) and otypes and otypes[-1] == 8
                if o_pers:
                    n_was_pers += 1
                    kind = "原=常驻"
                else:
                    n_was_temp += 1
                    kind = "原=非常驻"
            if shown < 12:
                shown += 1
                print(f"  0x{fid:08X} 覆盖后 flags=0x{flags:06X} 组={chain_name(types)}")
                print(f"      原记录 flags=0x{oflags:06X} 组={chain_name(otypes) or '-'}  ⇒ {kind}")
        print(f"  统计：原记录本来就是常驻 {n_was_pers} 条 / 原来是<非常驻> {n_was_temp} 条 / "
              f"Starfield 里找不到 {n_missing} 条\n")

    return 0


if __name__ == "__main__":
    sys.exit(main())
