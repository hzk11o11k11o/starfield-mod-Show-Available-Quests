#!/usr/bin/env python3
r"""create_board_markers.py - 给任务板入口新建**常驻 XMarker 引用**（第 30 轮，任意位置精确导航）。

## 背景：第 29 轮的 override 路线已被实机 + 数据双重否定

第 29 轮把 11 条非常驻任务板引用 `override` + 移进 `CellPersistent` 组 + flags 0x400，
希望「常驻化」。实机结果（2026-09-20 12:45 会话，游戏已加载该 ESM）：

    运行时状态：… 入口=12(可导航 2) 入口不可导航: 任务板 · 新亚特兰蒂斯城[0x0021001E] …（10 条）

`tools/esm/check_persist_precedent.py --self` 进一步证明：

* 官方 SFBGS003.esm / SFBGS008.esm 的 70 条「override + 常驻组」记录，**原记录本来就是常驻**
  （66/66 + 4/4）—— 官方从没把「非常驻」引用 override 成常驻；
* 我们的 11 条 **原记录都在 CellTemporary 组、flags 0x000000**。

⇒ 结论：**override 只替换记录数据，不改变引用的加载分类**（分类在记录第一次被加载时确定）。
「非常驻 → 常驻」在本机零先例、引擎不认。

## 本工具的做法（有先例可循：mod 给 cell 添加新物件）

在 `esm/SAQ_ShowAvailableQuests.esm` 里**新建** 11 条引用（记录号 0x900..0x90A，属于本插件
自己的空间），每条：

* base = **XMarker**（Starfield.esm 的 `0x0000003B`；无模型、无脚本、纯位置标记）；
* DATA = **照抄原任务板的 24 字节**（位置 + 旋转完全一致 ⇒ 蓝点精确落在板上）；
* flags = 0x400（常驻）、EDID = `SAQ_BoardMarker_<记录号>`；
* 放在**原 cell 的 `CellPersistent` 组**里：
  `Top 'CELL' > InteriorBlock > InteriorSubBlock > CellChildren > CellPersistent`
  —— 组头（时间戳等 16..23 字节）从 Starfield.esm 里**该 cell 的真实常驻引用所在组**照抄。

新记录从第一次被引擎加载就归入常驻组 ⇒ 引擎按常驻引用处理（这正是第 29 轮想做但做不到的）。
常驻引用的语义（BGS 三代一致）：**cell 未加载时依然存在**，脚本 `Game.GetForm` / DLL
`LookupByID` 在任何位置都取得到 —— 这就是「原生常驻」的阿基拉城板（0x0014D497）能在
赛多尼亚被导航、而其余 11 条不能的原因。

## ★ 第 33 轮：再加一条 **CELL 记录**（官方的「空壳」写法，只留 EDID）

第 30 轮这套「新建常驻 marker」实机判据是 `marker 0`（11 条引擎里一条都取不到）。第 33 轮复查
找到关键对照（docs/99 一·补十八第 4 节，工具 `tools/esm/dump_cell_group.py` +
`scan_override_persistent.py`）：

* 官方插件在动**基础游戏 cell 里的引用**时，**一定同时写一条该 cell 的 CELL 记录**
  （SFBGS003 的 4/4 个 override 引用所在 cell、SFBGS008 的 2/2 都有）；
* 本机全部插件里**只有我们**往基础游戏 cell 新增引用，而且**没有 CELL 记录** ⇒ 引擎很可能
  因此不把我们的 `CellChildren` 组并进那个 cell。

★ 写法照抄官方**对同一条 cell** 的做法（`dump_cell_group.py --plugin SFBGS003.esm` 实测，
对象正是任务板所在的霓虹城 cell 0x00071D5A）：

```
GRUP Interior Cell Sub-Block 6
  CELL 0x00071D5A flags=0x004000 size=19 子记录=[EDID]      ← 空壳：只留 EDID，不写任何数据字段
  GRUP Cell Children of CityNeonCore [CELL:00071D5A]
    GRUP Cell Persistent Children …
      REFR 0xFD000F13 flags=0x000400                        ← 官方自己新增的常驻引用
```

也就是说：

* CELL 记录**只写 EDID**（+ flags 0x4000，官方同款）—— **不覆盖 cell 的任何数据**，
  也不碰本地化名称（保留 string ID 的问题是：本插件非本地化，引擎会把 4 字节 string ID
  当成内联乱码；写空壳就完全没有这个问题）；
* 组结构：CELL 记录是**子块组的第 0 个子项**，紧接着才是它的 `CellChildren` 组：
  `Top 'CELL' > InteriorBlock > InteriorSubBlock > { CELL 记录, CellChildren > CellPersistent > REFR }`；
* 因此**没有 cell 级冲突面**（引用层面的新增当然还是互不冲突的）。

## 幂等 / 运行顺序

* 每次运行先删掉文件里已有的顶部 `CELL` 组（旧的无效 override + 旧 marker 一并清掉），
  再按 `ref/entry_targets.json` 重建 —— 无论从什么状态开始都能收敛到正确结果；
* ★ 必须在 `patch_saq_esm.py` **之后**（后者是线性重建，不认识嵌套组；已加防呆）；
* 产出 `ref/board_markers.json`（入口 refLocal -> marker 记录号），供 `gen_entry_table.py` 使用。

用法：
    python tools/esm/create_board_markers.py            # 幂等重建（需要时会读 Starfield.esm）
    python tools/esm/create_board_markers.py --check    # 只解析打印当前状态
    python tools/esm/create_board_markers.py --clean    # 只移除 CELL 组（含第 29 轮 override）
"""
from __future__ import annotations

import argparse
import json
import struct
import sys
import zlib
from collections import OrderedDict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from gen_entry_table import ENTRIES as BOARD_WHITELIST  # 白名单（唯一数据源，12 条任务板）  # noqa: E402
from persist_entry_refs import (  # noqa: E402
    PERSISTENT_FLAG, count_records_and_mast, describe, make_grup,
    split_top_groups, write_hedr_num_records,
)

ROOT = Path(__file__).resolve().parents[2]
TARGET_ESM = ROOT / "esm" / "SAQ_ShowAvailableQuests.esm"
ENTRY_JSON = ROOT / "ref" / "entry_targets.json"
OUT_JSON = ROOT / "ref" / "board_markers.json"
STARFIELD = Path(r"D:\SteamLibrary\steamapps\common\Starfield\Data\Starfield.esm")

MARKER_FIRST_ID = 0x900            # marker 记录号从这里开始（0x800~0x805 已被 QUST/GLOB 占用）
MARKER_EDID_PREFIX = "SAQ_BoardMarker_"
XMARKER_BASE = 0x0000003B          # Starfield.esm 的 XMarker（无模型、无脚本）
# ★ 第 33 轮：CELL 记录用官方的「空壳」写法（只留 EDID + 这个 flag —— SFBGS003/00D/050 同款）
CELL_STUB_FLAG = 0x00004000

REF_SIGS = (b"REFR", b"ACHR", b"PGRE", b"PMIS", b"PARW", b"PBAR", b"PHZD")


def sub(sig: bytes, data: bytes) -> bytes:
    if len(data) > 0xFFFF:
        raise SystemExit(f"子记录过长（需要 XXXX 扩展，本项目用不到）：{sig}")
    return sig + struct.pack("<H", len(data)) + data


def count_masters(head: bytes) -> int:
    """TES4 头里的 MAST 数量 —— **本文件自身记录的空间索引 = MAST 数量**
    （★ 实机踩过：本 ESM 的 MAST = [Starfield.esm, BlueprintShips-Starfield.esm] ⇒ 自身 = 2；
     写死 1 会让新记录落进 BlueprintShips 的 master 空间 = 非法覆盖）。"""
    size = struct.unpack_from("<I", head, 4)[0]
    p, end, n = 24, 24 + size, 0
    while p + 6 <= end:
        sig = head[p:p + 4]
        ln = struct.unpack_from("<H", head, p + 4)[0]
        if sig == b"MAST":
            n += 1
        p += 6 + ln
    return n


def build_marker_record(hdr_tmpl: bytes, local_id: int, edid: str, data24: bytes,
                        self_index: int) -> bytes:
    """用原任务板记录头作模板（时间戳/版本字段照抄），只改 size/flags/formid。"""
    payload = (sub(b"EDID", edid.encode("latin1") + b"\x00") +
               sub(b"NAME", struct.pack("<I", XMARKER_BASE)) +
               sub(b"DATA", data24))
    hdr = bytearray(hdr_tmpl[:24])
    struct.pack_into("<I", hdr, 4, len(payload))
    struct.pack_into("<I", hdr, 8, PERSISTENT_FLAG)
    struct.pack_into("<I", hdr, 12, (self_index << 24) | local_id)
    return bytes(hdr) + payload


def record_edid_of(raw: bytes) -> str:
    """从一条（可能压缩的）记录里取 EDID —— Starfield.esm 的 CELL 记录都是压缩的。"""
    size = struct.unpack_from("<I", raw, 4)[0]
    flags = struct.unpack_from("<I", raw, 8)[0]
    payload = raw[24:24 + size]
    if flags & 0x00040000 and len(payload) >= 4:
        try:
            payload = zlib.decompress(payload[4:])
        except zlib.error:
            return ""
    q = 0
    while q + 6 <= len(payload):
        sig = payload[q:q + 4]
        n = struct.unpack_from("<H", payload, q + 4)[0]
        if sig == b"EDID":
            return payload[q + 6:q + 6 + n].split(b"\x00")[0].decode("latin1")
        q += 6 + n
    return ""


def build_cell_stub(hdr_tmpl: bytes, edid: str, cell_fid: int) -> bytes:
    """★ 第 33 轮：CELL 记录的**官方空壳写法**（只留 EDID，flags=0x4000）。

    照抄对象：SFBGS003.esm 对自己新增引用的 *同一批* cell（霓虹城 0x00071D5A / 赛多尼亚
    0x002B3DA2）就是这么写的（dump_cell_group.py 实测：`CELL flags=0x004000 size=19 [EDID]`，
    紧跟 `CellChildren > CellPersistent > REFR 0xFD000F13`）。

    为什么不是整条照抄 Starfield.esm：
      ① 整条照抄会把 cell 的**全部字段**都变成"本插件版本" —— 别的 mod 改过同一 cell 时会被覆盖；
      ② 基础游戏的 CELL 名（FULL）是**本地化 string ID**（4 字节），而本插件非本地化 ——
         引擎/xEdit 会把那 4 字节当内联字符串（xEdit 重存后就显示成乱码），空壳写法完全不碰它。
    """
    payload = sub(b"EDID", edid.encode("latin1") + b"\x00")
    hdr = bytearray(hdr_tmpl[:24])          # 记录头照抄基础游戏（版本字段等一致）
    struct.pack_into("<I", hdr, 4, len(payload))
    struct.pack_into("<I", hdr, 8, CELL_STUB_FLAG)
    struct.pack_into("<I", hdr, 12, cell_fid)   # 保持 master 空间 FormID = override
    return bytes(hdr) + payload


def scan_starfield(want_refs: set[int]) -> dict:
    """读 Starfield.esm，返回：
      boards[refLocal]  = {"raw": 记录字节, "data24": DATA 子记录, "chain": 组链}
      pers_hdr[cellFid] = 该 cell 的真实 CellPersistent 组链头模板（block/sub/cc/persistent 四层）
      cells[cellFid]    = ★ 第 33 轮：该 cell 的 CELL 记录原始字节（照抄成 override）

    ★ CELL 记录怎么顺手拿到：文件里每条 cell 的结构固定是
      `[CELL 记录][CellChildren 组]`（dump_cell_group.py 实测），所以**走进任何 cell 的子树时，
      最近见过的那条 CELL 记录就是它自己的** —— 记一个 last_cell 即可，不需要第二遍扫描。
    """
    buf = STARFIELD.read_bytes()
    boards: dict[int, dict] = {}
    pers_hdr: dict[int, list] = {}
    cells: dict[int, dict] = {}
    last_cell: list = [None]      # [cellFid, raw]（闭包内可变）

    def rec(p: int, end: int, chain: list) -> None:
        while p + 24 <= end:
            if buf[p:p + 4] == b"GRUP":
                sub_size = struct.unpack_from("<I", buf, p + 4)[0]
                if sub_size < 24:
                    return
                label = bytes(buf[p + 8:p + 12])
                gtype = struct.unpack_from("<i", buf, p + 12)[0]
                rec(p + 24, p + sub_size, chain + [(gtype, label, bytes(buf[p:p + 24]))])
                p += sub_size
                continue
            size = struct.unpack_from("<I", buf, p + 4)[0]
            flags = struct.unpack_from("<I", buf, p + 8)[0]
            formid = struct.unpack_from("<I", buf, p + 12)[0]
            sig = bytes(buf[p:p + 4])
            low = formid & 0xFFFFFF
            if sig == b"CELL" and (formid >> 24) == 0:
                last_cell[0] = (low, bytes(buf[p:p + 24 + size]))
            if sig in REF_SIGS and (formid >> 24) == 0 and low in want_refs:
                payload = bytes(buf[p + 24:p + 24 + size])
                data24 = None
                q = 0
                while q + 6 <= len(payload):
                    sig2 = payload[q:q + 4]
                    n = struct.unpack_from("<H", payload, q + 4)[0]
                    if sig2 == b"DATA":
                        data24 = payload[q + 6:q + 6 + n]
                    q += 6 + n
                boards[low] = {"raw": bytes(buf[p:p + 24 + size]), "data24": data24,
                               "chain": list(chain), "flags": flags}
                # ★ 第 33 轮：任务板所在 cell 的 CELL 记录（就是我们当前子树里最近见到的那条）
                lc = last_cell[0]
                cell_fid = None
                for g, lab, _h in chain:
                    if g == 6:
                        cell_fid = struct.unpack_from("<i", lab)[0]
                if lc is not None and cell_fid is not None and lc[0] == cell_fid \
                        and cell_fid not in cells:
                    cells[cell_fid] = {"raw": lc[1], "edid": record_edid_of(lc[1]),
                                       "chain": [t for t, _, _ in chain[:3]]}
            # 顺便收集「该 cell 的真实常驻组链头」（任一常驻引用都行，取第一条）。
            # ★ 存**完整链**（Top 'CELL' 开头）：build_cell_group 既取 chain[-4:] 当
            #   blk/sub/cc/pers 模板，也取 chain[0] 当 Top 组头模板。
            if chain and chain[-1][0] == 8 and len(chain) >= 4:
                cell_fid = struct.unpack_from("<i", chain[-2][1])[0]
                if cell_fid and cell_fid not in pers_hdr:
                    pers_hdr[cell_fid] = list(chain)
            p += 24 + size

    head_size = struct.unpack_from("<I", buf, 4)[0]
    pos = 24 + head_size
    while pos + 24 <= len(buf):
        if buf[pos:pos + 4] != b"GRUP":
            break
        gsize = struct.unpack_from("<I", buf, pos + 4)[0]
        rec(pos + 24, pos + gsize,
            [(struct.unpack_from("<i", buf, pos + 12)[0], bytes(buf[pos + 8:pos + 12]),
              bytes(buf[pos:pos + 24]))])
        pos += gsize
    return {"boards": boards, "pers_hdr": pers_hdr, "cells": cells}


def build_cell_group(items: list[tuple[list, bytes]], cell_records: dict[int, bytes]) -> bytes:
    """items = [(组链模板, raw 新记录)] + cell_records{cellFid: CELL 记录字节}
    → 一棵 `Top 'CELL' > … > { CELL 记录, CellChildren > CellPersistent > REFR }` 组树。

    ★ 第 33 轮：CELL 记录必须是子块组的**第 0 个子项**（官方结构与 Starfield.esm 一致，
    见 tools/esm/dump_cell_group.py 的 dump）—— 引擎只把「本插件也写过该 CELL 记录」的
    CellChildren 组并进那个 cell（官方插件 6/6 都写了，我们第 30 轮没写 ⇒ 实机 `marker 0`）。
    """
    blocks: OrderedDict = OrderedDict()
    top_tmpl = None
    for chain, raw in items:
        gtypes = [g for g, _, _ in chain]
        if len(chain) < 4 or chain[-1][0] != 8:
            raise SystemExit(f"组链模板不符合预期（需要尾部 CellPersistent）：{gtypes}")
        blk, sub_g, cc, pers = chain[-4], chain[-3], chain[-2], chain[-1]
        if not (blk[0] == 2 and sub_g[0] == 3 and cc[0] == 6):
            raise SystemExit(f"组链模板不符合预期（内部 cell 的 block/subblock/cellchildren）：{gtypes}")
        top_tmpl = top_tmpl or chain[0][2]
        cell_label = struct.unpack_from("<i", cc[1])[0]
        b = blocks.setdefault((blk[1], sub_g[1]), {"blk": blk[2], "sub": sub_g[2], "cells": OrderedDict()})
        c = b["cells"].setdefault(cell_label, {"cc": cc[2], "pers": pers[2], "refs": []})
        c["refs"].append(raw)

    top_children = bytearray()
    for (blk_label, sub_label), b in blocks.items():
        sub_children = bytearray()
        for cell_label, c in b["cells"].items():
            pers_grup = make_grup(cell_label, 8, c["pers"], b"".join(c["refs"]))
            cc_grup = make_grup(cell_label, 6, c["cc"], pers_grup)
            # ★ 第 33 轮：CELL 记录（整条照抄基础游戏）排在它自己的 CellChildren 组**前面**
            if cell_label in cell_records:
                sub_children += cell_records[cell_label]
            sub_children += cc_grup
        sub_grup = make_grup(sub_label, 3, b["sub"], bytes(sub_children))
        blk_grup = make_grup(blk_label, 2, b["blk"], sub_grup)
        top_children += blk_grup
    return make_grup(b"CELL", 0, top_tmpl, bytes(top_children))


def collect_records(buf: bytes) -> tuple[dict[int, dict], dict[int, dict]]:
    """把文件里的 SAQ_BoardMarker_* 与 CELL 记录收集起来（formid 低 24 位 -> 信息）。"""
    seen: dict[int, dict] = {}
    cells: dict[int, dict] = {}

    def rec(p: int, end: int, chain: list) -> None:
        while p + 24 <= end:
            if buf[p:p + 4] == b"GRUP":
                sub_size = struct.unpack_from("<I", buf, p + 4)[0]
                if sub_size < 24:
                    return
                rec(p + 24, p + sub_size,
                    chain + [(struct.unpack_from("<i", buf, p + 12)[0], bytes(buf[p + 8:p + 12]))])
                p += sub_size
                continue
            size = struct.unpack_from("<I", buf, p + 4)[0]
            flags = struct.unpack_from("<I", buf, p + 8)[0]
            formid = struct.unpack_from("<I", buf, p + 12)[0]
            sig4 = bytes(buf[p:p + 4])
            payload = bytes(buf[p + 24:p + 24 + size])
            edid = None
            data24 = None
            subs: list[str] = []
            if not (flags & 0x00040000):   # 压缩记录不解析子记录（空壳 CELL 是非压缩的）
                q = 0
                while q + 6 <= len(payload):
                    sig = payload[q:q + 4]
                    n = struct.unpack_from("<H", payload, q + 4)[0]
                    subs.append(sig.decode("latin1"))
                    if sig == b"EDID":
                        edid = payload[q + 6:q + 6 + n].split(b"\x00")[0].decode("latin1")
                    if sig == b"DATA":
                        data24 = payload[q + 6:q + 6 + n]
                    q += 6 + n
            if sig4 == b"CELL":
                cells[formid & 0xFFFFFF] = {"formid": formid, "flags": flags, "subs": subs,
                                            "edid": edid or "", "raw": bytes(buf[p:p + 24 + size]),
                                            "chain": list(chain)}
            elif edid and edid.startswith(MARKER_EDID_PREFIX):
                seen[formid & 0xFFFFFF] = {"flags": flags, "chain": list(chain),
                                           "edid": edid, "data": data24, "formid": formid}
            p += 24 + size

    head_size = struct.unpack_from("<I", buf, 4)[0]
    pos = 24 + head_size
    while pos + 24 <= len(buf):
        if buf[pos:pos + 4] != b"GRUP":
            break
        gsize = struct.unpack_from("<I", buf, pos + 4)[0]
        rec(pos + 24, pos + gsize,
            [(struct.unpack_from("<i", buf, pos + 12)[0], bytes(buf[pos + 8:pos + 12]))])
        pos += gsize
    return seen, cells


def verify(buf: bytes, expect: list[dict], check_data: bool, self_index: int = -1) -> list[str]:
    problems: list[str] = []
    seen, cells = collect_records(buf)
    want_cells: dict[int, str] = {}   # cell FormID -> 期望的 cell EDID（'' = 无来源，只查结构）
    for e in expect:
        got = seen.get(e["markerLocal"])
        if got is None:
            problems.append(f"{e['nameZh']}（marker 0x{e['markerLocal']:X}）没有记录")
            continue
        if got["edid"] != e["edid"]:
            problems.append(f"{e['nameZh']} EDID={got['edid']!r} 期望 {e['edid']!r}")
        if self_index >= 0 and (got["formid"] >> 24) != self_index:
            problems.append(f"{e['nameZh']} FormID 空间索引={got['formid'] >> 24} 期望 {self_index}"
                            f"（本文件 MAST 数量；错了就落进别的 master 空间）")
        if not (got["flags"] & PERSISTENT_FLAG):
            problems.append(f"{e['nameZh']} flags=0x{got['flags']:X} 缺 0x400")
        chain_types = [g for g, _ in got["chain"]]
        if chain_types[-4:] != [2, 3, 6, 8]:
            problems.append(f"{e['nameZh']} 组链尾部不是 [2,3,6,8]（实际 {chain_types}）")
        else:
            # ★ 第 33 轮：marker 所在 CellChildren 组的 label = 它所属 cell 的 FormID；
            #   expect 里的 "cell" 就是该 cell 的 EDID（重建路径已与 Starfield.esm 核对过）
            want_cells[struct.unpack_from("<i", got["chain"][-2][1])[0] & 0xFFFFFF] = \
                e.get("cell", "")
        if check_data and e.get("data24") is not None and got["data"] != e["data24"]:
            problems.append(f"{e['nameZh']} DATA 与任务板不一致")

    # ★ 第 33 轮：每个有 marker 的 cell 必须同时有「官方空壳 CELL 记录」（引擎据此并进
    #   CellChildren 组）—— 空壳 = 只留 EDID、flags 0x4000、非压缩、不写任何数据字段。
    for low in sorted(want_cells):
        c = cells.get(low)
        want_edid = want_cells[low]
        if c is None:
            problems.append(f"cell 0x{low:06X} 没有 CELL 记录（第 33 轮：官方对同一条 cell 也写了；"
                            f"缺它 = 引擎不会并入我们的 CellChildren 组）")
            continue
        why = []
        if (c["formid"] >> 24) != 0:
            why.append(f"不是 override（空间索引={c['formid'] >> 24}，应为主 master 0）")
        if [g for g, _ in c["chain"]][-2:] != [2, 3]:
            why.append(f"组链={[g for g, _ in c['chain']]}")
        if not (c["flags"] & CELL_STUB_FLAG):
            why.append(f"flags=0x{c['flags']:X} 缺 0x{CELL_STUB_FLAG:X}（官方空壳标记）")
        if c["flags"] & 0x00040000:
            why.append("是压缩记录（空壳应非压缩）")
        if c["subs"] != ["EDID"]:
            why.append(f"子记录={c['subs']} ≠ ['EDID']（空壳不许写数据字段，否则会覆盖 cell 数据）")
        if want_edid and c["edid"] != want_edid:
            why.append(f"EDID={c['edid']!r}≠{want_edid!r}")
        if not c["edid"]:
            why.append("EDID 为空")
        if why:
            problems.append(f"cell 0x{low:06X} 的 CELL 空壳：" + "；".join(why))
    return problems


def write_json(expect: list[dict]) -> None:
    out = []
    for e in expect:
        d = dict(e)
        if isinstance(d.get("data24"), (bytes, bytearray)):
            d["data24"] = bytes(d["data24"]).hex(" ")   # 仅供人工核对，gen_entry_table 不读它
        out.append(d)
    OUT_JSON.write_text(json.dumps({"markers": out}, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"已写出 {OUT_JSON}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--esm", default=str(TARGET_ESM))
    ap.add_argument("--check", action="store_true", help="只解析打印当前状态")
    ap.add_argument("--clean", action="store_true", help="只移除 CELL 组（含第 29 轮 override）")
    a = ap.parse_args()
    target = Path(a.esm)
    if not target.exists():
        print(f"没有 {target}（先跑 tools/run-esm-build.ps1 + patch_saq_esm.py）")
        return 1
    if a.check:
        return describe(target)

    # 需要建档的条目（非常驻的任务板）：
    #   ① 首选 ref/entry_targets.json 的 persistent 字段（快，与静态表一致）；
    #   ② 不存在（首次构建）⇒ 用 gen_entry_table 的白名单，读 Starfield.esm 按 flags 判断。
    need: list[dict] = []
    if ENTRY_JSON.exists():
        entries = json.loads(ENTRY_JSON.read_text(encoding="utf-8"))
        need = [{"refLocal": e["refLocal"], "refHex": e["refHex"], "nameZh": e["nameZh"],
                 "cell": e["cell"]} for e in entries if not e["persistent"]]
        need.sort(key=lambda e: e["refLocal"])
    pending_scan = not need   # True ⇒ 需要读 Starfield.esm 才知道哪些要建档

    buf = target.read_bytes()
    head, groups = split_top_groups(buf)
    head_size = struct.unpack_from("<I", buf, 4)[0]
    self_index = count_masters(head)     # 自身记录的空间索引（= MAST 数量；实测本文件 = 2）
    n_old_cell = sum(1 for lb, _, _ in groups if lb == b"CELL")
    rest = [(lb, gt, raw) for lb, gt, raw in groups if lb != b"CELL"]

    if a.clean:
        out = bytearray(head)
        for _lb, _gt, raw in rest:
            out += raw
        n_rec, n_mast = count_records_and_mast(bytes(out[:24 + head_size]), rest)
        old = write_hedr_num_records(out, n_rec + n_mast)
        target.write_bytes(bytes(out))
        print(f"移除 CELL 组 {n_old_cell} 个（numRecords {old} -> {n_rec + n_mast}，{len(out)} B）")
        return 0

    def make_expect(items: list[dict]) -> list[dict]:
        return [{
            "refLocal": e["refLocal"], "refHex": e["refHex"], "nameZh": e["nameZh"],
            "cell": e["cell"], "markerLocal": MARKER_FIRST_ID + i,
            "edid": f"{MARKER_EDID_PREFIX}{e['refLocal']:06X}",
        } for i, e in enumerate(items)]

    expect = make_expect(need)

    # 快速路径：文件里已有结构正确的 CELL 组 + 条目集合来自缓存 ⇒ 不必读 1.4 GB 的 Starfield.esm
    # （DATA 与任务板的一致性校验需要 Starfield 的原始字节，只在重建路径做。）
    if not pending_scan and n_old_cell == 1 and not verify(buf, expect, check_data=False,
                                                           self_index=self_index):
        print(f"CELL 组已是最新（{len(expect)} 条常驻 marker）—— 跳过重建")
        write_json(expect)
        return 0

    print(f"移除旧 CELL 组 {n_old_cell} 个（含第 29 轮的无效 override）")
    print(f"读 {STARFIELD.name}（约 1~2 分钟）…")
    want = {r for r, *_ in BOARD_WHITELIST} if pending_scan else {e["refLocal"] for e in need}
    sc = scan_starfield(want)
    if pending_scan:
        need = []
        for refr, cell_edid, _en, zh in BOARD_WHITELIST:
            b = sc["boards"].get(refr)
            if b is None:
                raise SystemExit(f"白名单 REFR 0x{refr:06X} 在 Starfield.esm 里没找到")
            if not (b["flags"] & PERSISTENT_FLAG):
                need.append({"refLocal": refr, "refHex": f"0x{refr:06X}", "nameZh": zh, "cell": cell_edid})
        need.sort(key=lambda e: e["refLocal"])
        expect = make_expect(need)
        print(f"（首次路径：按 Starfield.esm 的 flags 判断）需要建档 {len(need)} / 白名单 {len(BOARD_WHITELIST)} 条")
        if not need:
            print("白名单里的任务板都已经是原生常驻 —— 没有要建档的")
            return 0
    missing = [e for e in need if e["refLocal"] not in sc["boards"]]
    if missing:
        raise SystemExit("Starfield.esm 里没找到：" + ", ".join(e["refHex"] for e in missing))

    items: list[tuple[list, bytes]] = []
    cell_records: dict[int, bytes] = {}
    for e, ex in zip(need, expect):
        b = sc["boards"][e["refLocal"]]
        if not b["data24"] or len(b["data24"]) < 12:
            raise SystemExit(f"{e['nameZh']} 的 DATA 子记录异常（{b['data24']!r}）")
        cell_fid = None
        for g, lab, _h in b["chain"]:
            if g == 6:
                cell_fid = struct.unpack_from("<i", lab)[0]
        tmpl_chain = sc["pers_hdr"].get(cell_fid)
        if tmpl_chain is None:
            raise SystemExit(f"{e['nameZh']} 的 cell 0x{cell_fid:08X} 里没找到常驻引用（无法照抄组头）")
        # ★ 第 33 轮：该 cell 的 CELL 记录（官方空壳写法 —— 引擎并入 CellChildren 组的前提）
        cell_info = sc["cells"].get(cell_fid)
        if cell_info is None or not cell_info["edid"]:
            raise SystemExit(f"{e['nameZh']} 的 cell 0x{cell_fid:08X} 没拿到 CELL 记录/EDID（第 33 轮必需）")
        if cell_info["edid"] != e["cell"]:
            raise SystemExit(f"{e['nameZh']}：Starfield.esm 的 cell EDID={cell_info['edid']!r} "
                             f"与 entry_targets.json 的 {e['cell']!r} 不一致（数据源过期？）")
        ex["cellFid"] = cell_fid
        cell_records[cell_fid] = build_cell_stub(cell_info["raw"], cell_info["edid"], cell_fid)
        ex["data24"] = b["data24"]
        rec = build_marker_record(b["raw"], ex["markerLocal"], ex["edid"], b["data24"], self_index)
        items.append((tmpl_chain, rec))
        print(f"  {e['nameZh']:<22s} marker=0x{ex['markerLocal']:03X} cell={e['cell']:<32s} "
              f"0x{cell_fid:08X} CELL 空壳={len(cell_records[cell_fid])} B "
              f"pos={struct.unpack_from('<fff', b['data24'], 0)}")

    cell_group = build_cell_group(items, cell_records)
    print(f"新建 CELL 组：{len(cell_group)} B / {len(items)} 条常驻 marker"
          f" + {len(cell_records)} 条 CELL 空壳记录（只留 EDID + flags 0x4000，官方写法）")

    out = bytearray(head)
    for _lb, _gt, raw in rest:
        out += raw
    out += cell_group
    n_rec, n_mast = count_records_and_mast(bytes(out[:24 + head_size]), rest + [(b"CELL", 0, cell_group)])
    old = write_hedr_num_records(out, n_rec + n_mast)
    print(f"numRecords {old} -> {n_rec + n_mast}")

    result = bytes(out)
    problems = verify(result, expect, check_data=True, self_index=self_index)
    if problems:
        print("\n!! 自校验失败：")
        for p in problems:
            print("   -", p)
        return 1

    target.write_bytes(result)
    write_json(expect)
    print(f"已写回 {target}（{len(result)} B）\n")
    print("--- 自校验通过（重新解析） ---")
    describe(target)
    return 0


if __name__ == "__main__":
    sys.exit(main())
