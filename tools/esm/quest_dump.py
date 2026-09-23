#!/usr/bin/env python3
"""quest_dump.py - 全量导出 Starfield.esm 的 QUST 记录，用于"可接任务"判定分析。

用法：
    python tools/esm/quest_dump.py <Starfield.esm> --json ref/quests.json
    python tools/esm/quest_dump.py <Starfield.esm> --stats

子记录解析基于实测（Starfield 1.16.x）：
    EDID  = 编辑器 ID（ASCII）
    FULL  = u32 字符串表 ID（显示名）
    DNAM  = 12 字节：u16 flags / u16 priority / u32 unk / u32 unk
    QTYP  = u32 FormID -> KYWD QuestType*  （任务类型：Activities/MainQuest/Factions/SideQuest/Mission）
    FTYP  = u32 FormID -> KYWD FactionType*（派系）
    VMAD  = Papyrus 脚本绑定
    CTDA  = 条件（数量）
    ALST/ALED/ALID/ALFG/VTCK/ALLS = alias 定义
    INDX/QSDT/NAM2/QSRD = stage 定义
    QOBJ/QSTA = objective / objective target
"""
from __future__ import annotations

import argparse
import json
import struct
import sys
import zlib
from collections import Counter, defaultdict
from pathlib import Path


def iter_subrecords(buf: bytes, start: int, size: int):
    """遍历一条记录的顶层子记录，yield (sig, payload_bytes)。"""
    p = start
    end = start + size
    while p + 6 <= end:
        ssig = buf[p:p + 4]
        ssize = struct.unpack_from("<H", buf, p + 4)[0]
        if p + 6 + ssize > end:
            break
        yield ssig, buf[p + 6:p + 6 + ssize]
        p += 6 + ssize


def get_record_payload(buf: bytes, rec_off: int):
    """读取记录头后面的 payload，处理压缩标志。返回 payload 字节或 None。"""
    size = struct.unpack_from("<I", buf, rec_off + 4)[0]
    flags = struct.unpack_from("<I", buf, rec_off + 8)[0]
    payload_off = rec_off + 24
    if flags & 0x00040000:  # compressed
        if size < 4:
            return None
        raw = buf[payload_off + 4:payload_off + size]
        try:
            return zlib.decompress(raw)
        except zlib.error:
            return None
    return buf[payload_off:payload_off + size]


def read_tes4(buf: bytes) -> dict:
    """TES4 头：master 列表 / flags / 文件名（用来算「本插件自己的记录前缀」）。

    ★ 多 master 支持的基础（第 17 轮）：插件里记录的 FormID 前缀 = **本插件在它自己的
      master 列表里的序号**（不是运行期加载序号）。例：
        Starfield.esm      masters=[]                      → 自己的记录前缀 0x00
        ShatteredSpace.esm masters=[starfield.esm]         → 0x01
        SFBGS050.esm       masters=[starfield.esm, sfbgs00d.esm] → 0x02
      运行期再把「序号」换成「加载序号」（DLL 侧按 master 名字查 TESDataHandler.files）。

    另：flags 位含义见 commonlibsf `TESFile::Flags`：
        0x01=kMaster 0x04=kEnabled 0x80=kLocalized 0x100=kSmall 0x200=? 0x400=kMedium 0x800=kBlueprint
      kSmall（light）插件的 FormID 是 12 位局部号 + 前缀 0xFE，读表时要按位宽区分。

    ★★ 第 110 轮（medium 档 · SFBGS003 / 追踪者联盟）：
      kMedium（0x400）插件的**记录在文件里就写 0xFD 前缀**：
          FormID = 0xFD000000 | (mediumIndex << 16) | local(16 位)
      文件内 mediumIndex = 0（占位），运行期由引擎按加载顺序分配（8 位、最多 256 个）。
      实测证据（SFBGS003.esm）：自己的记录 0xFD00004A / 0xFD00492D（local < 0x10000）、
      cross-ref 0xFD000EF5（FTYP 引用自己空间的关键字）；而**override 记录仍写 0x00 前缀**
      （改 starfield.esm 的记录，共 9 条）—— 所以 dump 时必须过滤「不是自己的」记录，
      否则 override 会以本插件的身份进表（运行期解析成错误 FormID）。
      同理 light（0xFE 前缀）也按「前缀 == 0xFE」判自己（此前靠 self_index 判，
      对 light/medium 都不成立 —— 本机第 110 轮才第一次有这两种样本）。
    """
    if buf[0:4] != b"TES4":
        raise ValueError("not a plugin")
    head_size = struct.unpack_from("<I", buf, 4)[0]
    flags = struct.unpack_from("<I", buf, 8)[0]
    masters: list[str] = []
    for sig, sp in iter_subrecords(buf, 24, head_size):
        if sig == b"MAST":
            masters.append(sp.split(b"\x00")[0].decode("latin1"))
    return {
        "flags": flags,
        "masters": masters,
        "self_index": len(masters),          # full 插件：自己的记录用的前缀
        "small": bool(flags & 0x100),        # light（ESL 类）—— 前缀 0xFE
        "medium": bool(flags & 0x400),       # ★★ 第 110 轮：medium（ESH 类）—— 前缀 0xFD
        "localized": bool(flags & 0x80),
    }


def is_own_record(formid: int, meta: dict) -> bool:
    """★★ 第 110 轮：这条记录是不是**本插件自己的**（而不是对 master 的 override）。

    full：前缀 == self_index（文件内序号）；medium：0xFD；light：0xFE。
    override 的前缀指向被覆盖记录的宿主 master（通常 0x00 = starfield.esm）⇒ False。
    """
    prefix = (formid >> 24) & 0xFF
    if meta.get("medium"):
        return prefix == 0xFD
    if meta.get("small"):
        return prefix == 0xFE
    return prefix == meta.get("self_index", 0)


def walk_quests(buf: bytes):
    """遍历所有 GRUP(QUST) 里的记录，yield (formid, flags, payload)。

    只取 QUST 顶层组里的**直接记录**；嵌套组（type 7/10，即任务的对话/信息子记录）
    整段跳过 —— 那是 INFO/DIAL，不是任务记录。
    """
    head_size = struct.unpack_from("<I", buf, 4)[0]
    pos = 24 + head_size
    while pos + 24 <= len(buf):
        if buf[pos:pos + 4] != b"GRUP":
            break
        gsize = struct.unpack_from("<I", buf, pos + 4)[0]
        glabel = buf[pos + 8:pos + 12]
        if gsize < 24:
            break
        if glabel == b"QUST":
            p = pos + 24
            gend = pos + gsize
            while p + 24 <= gend:
                if buf[p:p + 4] == b"GRUP":
                    sub = struct.unpack_from("<I", buf, p + 4)[0]
                    if sub < 24:
                        break
                    p += sub
                    continue
                formid = struct.unpack_from("<I", buf, p + 12)[0]
                flags = struct.unpack_from("<I", buf, p + 8)[0]
                payload = get_record_payload(buf, p)
                if payload is not None:
                    yield formid, flags, payload
                rsize = struct.unpack_from("<I", buf, p + 4)[0]
                p += 24 + rsize
            return
        pos += gsize


def parse_quest(formid: int, flags: int, payload: bytes, meta: dict | None = None) -> dict:
    """meta = read_tes4() 的结果（master 名 / 自己的前缀 / 是否 small）。

    ★ 第 17 轮（多 master）：表里同时记
        master    记录来自哪个插件（DLL 按名字查加载序号）
        local     记录号（已经去掉文件内的 master 前缀）——运行期 FormID = (序号<<24)|local
        small     是否是 light 插件（前缀 0xFE + 12 位局部号）
      老字段 formid 保留（= 文件里的原始 FormID），便于和 xEdit/日志对照。

    ★★ 第 110 轮：再加 medium（0xFD 前缀 + 16 位局部号）——
        medium ⇒ local = formid & 0xFFFF；运行期 = 0xFD000000 | (mediumIndex<<16) | local。
    """
    meta = meta or {"self_index": 0, "small": False, "medium": False, "file": ""}
    if meta.get("medium"):
        mask = 0xFFFF
    elif meta.get("small"):
        mask = 0xFFF
    else:
        mask = 0xFFFFFF
    rec = {
        "formid": formid,
        "master": meta.get("file", "Starfield.esm"),
        "self_index": meta.get("self_index", 0),
        "small": bool(meta.get("small")),
        "medium": bool(meta.get("medium")),
        "local": formid & mask,
        "rec_flags": flags,
        "edid": None,
        "full": None,
        "dnam": None,
        "qtyp": None,
        "ftyp": None,
        "subs": {},      # sig -> count
        "ctda": [],
        "aliases": {},
        "stages": [],
        "objectives": [],
        "vmad_size": 0,
    }
    for ssig, sp in iter_subrecords(payload, 0, len(payload)):
        s = ssig.decode("latin1")
        rec["subs"][s] = rec["subs"].get(s, 0) + 1
        if ssig == b"EDID":
            rec["edid"] = sp.split(b"\x00")[0].decode("latin1")
        elif ssig == b"FULL":
            rec["full"] = struct.unpack_from("<I", sp, 0)[0]
        elif ssig == b"DNAM":
            rec["dnam"] = sp.hex()
        elif ssig == b"QTYP":
            rec["qtyp"] = struct.unpack_from("<I", sp, 0)[0]
        elif ssig == b"FTYP":
            rec["ftyp"] = struct.unpack_from("<I", sp, 0)[0]
        elif ssig == b"VMAD":
            rec["vmad_size"] = len(sp)
        elif ssig == b"CTDA":
            rec["ctda"].append(sp.hex())
        elif s in ("ALST", "ALED", "ALID", "ALFG", "VTCK", "ALLS", "ALCS", "ALD2", "ALFI"):
            rec["aliases"][s] = rec["aliases"].get(s, 0) + 1
        elif ssig in (b"INDX", b"QSDT", b"NAM2", b"QSRD"):
            if ssig == b"INDX" and len(sp) >= 4:
                rec["stages"].append({"id": struct.unpack_from("<I", sp, 0)[0]})
            elif ssig == b"QSDT" and len(sp) >= 1 and rec["stages"]:
                rec["stages"][-1]["flags"] = sp[0]
        elif ssig in (b"QOBJ", b"QSTA", b"FNAM", b"QNOD", b"QNPC"):
            pass
    return rec


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("esm", nargs="+", help="一个或多个 ESM（如 Starfield.esm ShatteredSpace.esm SFBGS050.esm）")
    ap.add_argument("--json", default=None, help="dump all quests as JSON")
    ap.add_argument("--stats", action="store_true", help="print statistics")
    a = ap.parse_args()

    quests = []
    for esm in a.esm:
        path = Path(esm)
        buf = path.read_bytes()
        meta = read_tes4(buf)
        meta["file"] = path.name
        n0 = len(quests)
        skipped = 0
        for formid, flags, payload in walk_quests(buf):
            # ★★ 第 110 轮：只收「本插件自己的」记录 —— override（改某个 master 的记录）
            #   在文件里写的是**被覆盖 master 的前缀**，以本插件身份进表会在运行期解析错。
            if not is_own_record(formid, meta):
                skipped += 1
                continue
            quests.append(parse_quest(formid, flags, payload, meta))
        extra = ""
        if meta["flags"] & 0x100:
            extra += " light(kSmall)"
        if meta["flags"] & 0x400:
            extra += " kMedium"
        if meta["flags"] & 0x800:
            extra += " kBlueprint"
        skip_txt = f"（跳过 override {skipped} 条）" if skipped else ""
        print(f"{path.name}: QUST {len(quests) - n0} 条{skip_txt}；"
              f"master={meta['masters']}；自己的记录前缀=0x{meta['self_index']:02X}{extra}")

    print(f"QUST records: {len(quests)}")

    if a.stats:
        by_master = Counter(q["master"] for q in quests)
        print("\n--- 按 master ---")
        for k, v in by_master.most_common():
            print(f"  {k}: {v}")

    if a.stats:
        types = Counter(q["qtyp"] for q in quests)
        print("\n--- QTYP distribution ---")
        for k, v in types.most_common(20):
            print(f"  0x{k:08X}: {v}" if k is not None else f"  None: {v}")

        print("\n--- FTYP distribution (top 20) ---")
        for k, v in Counter(q["ftyp"] for q in quests).most_common(20):
            print(f"  0x{k:08X}: {v}" if k is not None else f"  None: {v}")

        print("\n--- 有 CTDA 的 quest ---")
        with_ctda = [q for q in quests if q["ctda"]]
        print(f"  {len(with_ctda)} / {len(quests)}")
        print(f"  CTDA 条数分布: {Counter(len(q['ctda']) for q in with_ctda).most_common(10)}")

        print("\n--- DNAM flags 分布（前 2 字节）---")
        dnam_flags = Counter()
        for q in quests:
            if q["dnam"]:
                b = bytes.fromhex(q["dnam"])
                dnam_flags[struct.unpack_from("<H", b, 0)[0]] += 1
        for k, v in dnam_flags.most_common(15):
            print(f"  0x{k:04X}: {v}")

        print("\n--- alias 子记录分布 ---")
        al_keys = Counter()
        for q in quests:
            for k in q["aliases"]:
                al_keys[k] += 1
        print(f"  {dict(al_keys.most_common())}")

        print("\n--- stage 数分布 ---")
        print(f"  {Counter(len(q['stages']) for q in quests).most_common(10)}")

        print("\n--- VMAD 有无 ---")
        print(f"  有 VMAD: {sum(1 for q in quests if q['vmad_size'])}")

        print("\n--- 子记录签名总体分布（有多少 quest 含该签名）---")
        sigs = Counter()
        for q in quests:
            for s in q["subs"]:
                sigs[s] += 1
        for k, v in sigs.most_common(60):
            print(f"  {k}: {v}")

    if a.json:
        out = Path(a.json)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(quests, indent=1), encoding="utf-8")
        print(f"wrote {out} ({out.stat().st_size} B)")

    return 0


if __name__ == "__main__":
    sys.exit(main())
