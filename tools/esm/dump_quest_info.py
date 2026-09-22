#!/usr/bin/env python3
"""dump_quest_info.py - dump 指定 QUST 的全部 INFO 原始 CTDA（第 106 轮转正工具）。

用途（INFO 门槛核对 / 覆盖面复盘）：把一条任务的每个对话（INFO）的**原始条件**打出来 ——
op 位域（运算符 + flags）、函数、参数、比较值、Run On、是否自引用 —— 并同时给出
**旧 / 新两版「入口 / 中性 / 推进」分类**（旧版 = op==0 判据；新版 = 不看 op/flags，
见 docs/08 4.5）。

判读「INFO 门槛数据对不对」时用（第 106 轮做过：OR 组纳入 + kind 判据升级的
逐任务核实）。

用法：
    python tools/esm/dump_quest_info.py 035E1B                     # 基础游戏（local 即 formid）
    python tools/esm/dump_quest_info.py --esm "<ShatteredSpace.esm>" 01035E1B
    （DLC 的 formid 要带文件内前缀 0x01 —— 用 quests_all.json 里的 formid 字段）
"""
from __future__ import annotations
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from esm_probe import DEFAULT_ESM, subrecords  # noqa: E402

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

GATE_FUNCS = {0x0038: "Run", 0x003B: "StageDone", 0x021F: "Completed"}
OPS = {0: "==", 1: "!=", 2: ">", 3: ">=", 4: "<", 5: "<="}


def parse_ctda(b: bytes) -> dict | None:
    if len(b) < 32:
        return None
    return {
        "op": struct.unpack_from("<I", b, 0)[0],
        "cmp": round(struct.unpack_from("<f", b, 4)[0], 6),
        "func": struct.unpack_from("<H", b, 8)[0],
        "p1": struct.unpack_from("<I", b, 12)[0],
        "p2": struct.unpack_from("<I", b, 16)[0],
        "runOn": struct.unpack_from("<I", b, 20)[0],
    }


def payload_of(buf: bytes, p: int):
    size = struct.unpack_from("<I", buf, p + 4)[0]
    flags = struct.unpack_from("<I", buf, p + 8)[0]
    formid = struct.unpack_from("<I", buf, p + 12)[0]
    if flags & 0x00040000:
        import zlib
        if size < 4:
            return None
        try:
            return formid, zlib.decompress(buf[p + 28:p + 24 + size])
        except zlib.error:
            return None
    return formid, buf[p + 24:p + 24 + size]


def scan_info(buf, start, end, quest, out):
    p = start
    while p + 24 <= end:
        sig = buf[p:p + 4]
        size = struct.unpack_from("<I", buf, p + 4)[0]
        if size < 24:
            return
        if sig == b"GRUP":
            scan_info(buf, p + 24, p + size, quest, out)
            p += size
            continue
        if sig == b"INFO":
            got = payload_of(buf, p)
            if got:
                out.append((quest, got[0], got[1]))
        p += 24 + size


def is_progress(c, *, old: bool):
    ok = c["runOn"] == 0 and c["cmp"] in (0.0, 1.0) and c["func"] in GATE_FUNCS
    if old:
        ok = ok and c["op"] == 0x00
    return ok


def kind_of(conds, quest, *, old: bool):
    w1 = any(is_progress(c, old=old) and c["p1"] == quest and c["cmp"] == 1.0 for c in conds)
    w0 = any(is_progress(c, old=old) and c["p1"] == quest and c["cmp"] == 0.0 for c in conds)
    return "推进" if w1 else ("入口" if w0 else "中性")


def main() -> int:
    argv = sys.argv[1:]
    esm = DEFAULT_ESM
    if "--esm" in argv:
        i = argv.index("--esm")
        esm = argv[i + 1]
        del argv[i:i + 2]
    targets = {int(x, 16) for x in argv} or {0x035E1B}
    buf = Path(esm).read_bytes()
    infos = []
    pos = 24 + struct.unpack_from("<I", buf, 4)[0]
    while pos + 24 <= len(buf):
        if buf[pos:pos + 4] != b"GRUP":
            break
        gsize = struct.unpack_from("<I", buf, pos + 4)[0]
        if buf[pos + 8:pos + 12] == b"QUST":
            p = pos + 24
            cur = 0
            while p + 24 <= pos + gsize:
                sig = buf[p:p + 4]
                size = struct.unpack_from("<I", buf, p + 4)[0]
                if size < 24:
                    break
                if sig == b"GRUP":
                    if cur in targets:
                        scan_info(buf, p + 24, p + size, cur, infos)
                    p += size
                    continue
                if sig == b"QUST":
                    got = payload_of(buf, p)
                    if got:
                        cur = got[0]
                p += 24 + size
            break
        pos += gsize

    for quest in sorted(targets):
        mine = [x for x in infos if x[0] == quest]
        print(f"\n===== QUST 0x{quest:06X}：{len(mine)} 条 INFO =====")
        for q, iid, payload in mine:
            conds = []
            for s, sp in subrecords(payload):
                if s == b"CTDA":
                    c = parse_ctda(sp)
                    if c:
                        conds.append(c)
            if not conds:
                continue
            k_old = kind_of(conds, quest, old=True)
            k_new = kind_of(conds, quest, old=False)
            mark = "" if k_old == k_new else f"   <<< 分类变化 {k_old} → {k_new}"
            print(f"\nINFO 0x{iid:06X}  [{len(conds)} 条件] kind: 旧={k_old} 新={k_new}{mark}")
            for c in conds:
                t = c["op"]
                fn = GATE_FUNCS.get(c["func"], f"func{c['func']}")
                selfref = " 自引用" if c["p1"] == quest else ""
                stag = f",{c['p2'] & 0xFFFF}" if c["func"] == 0x003B else ""
                print(f"    {OPS.get(t >> 5, t >> 5):<2} flags=0x{t & 0x1F:02X}  "
                      f"{fn}(0x{c['p1']:06X}{stag})  cmp={c['cmp']}  runOn={c['runOn']}{selfref}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
