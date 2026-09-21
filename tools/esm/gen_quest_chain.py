#!/usr/bin/env python3
"""gen_quest_chain.py - 第 67 轮：**任务链门槛**数据生成。

起因（玩家实测）：存档里「深红舰队」任务线根本没开始，但「可接任务」列表里却出现了
CF02「菜鸟觐见」、CF06「风驰电掣」——它们是**后续任务**，只能由前一个任务的收尾阶段
自动启动（`CF01` 的 stage 1000 fragment 里 `CF02.SetStage(10)`），玩家根本没法主动去接。
现有两类门槛（记录级 CTDA / INFO 对话）都拦不住它们（它们没有"前置任务完成"这类条件）。

做法：从**官方 Papyrus 源码**（CK 的 `Data\\Scripts\\Source\\Base`）里把"任务链启动边"
挖出来 —— 谁在什么阶段把另一个任务 SetStage/Start 起来：

  * 边的两侧都必须是「编号链路」任务：EDID 形如 `<字母前缀><编号>`（CF01 / UC02 / …），
    且 **调用方 A 的 EDID 是纯编号形式**（`CF01`，不是 `CF01_xxx`），
    **被调用方 B 的编号 = A 的编号 + 1**，字母前缀相同。
  * 调用必须发生在 **A 的 stage fragment** 里（`Fragment_Stage_XXXX_Item_NN`），
    这样 `A 的 stage XXXX 完成` 就是这条边的触发条件。
  * 于是判据：**B 的全部链边都还没触发 ⇒ B 是"后续任务" ⇒ 隐藏**（见 SAQ_Decision::DecideChainGates）。

为什么不用"所有跨任务调用"而要卡「前缀 + 编号 +1」：
  * CF01 也有大量跨任务入边（被监狱/犯罪/UC02 等特殊路径调用），但它们**不是启动边**
    （CF01 是可接的链头）⇒ 用编号相邻把这类噪声挡掉；
  * CF05/CF06 会**回写**对方的 stage（CF06 的 stage 0~8 里 `CF05.SetStage(2200)`）——
    编号方向（+1）天然排除回写。

用法：
    python tools/esm/gen_quest_chain.py                 # 写 ref/quest_chain.json
    python tools/esm/gen_quest_chain.py --stats         # 只统计
    python tools/esm/gen_quest_chain.py --quests ref/quest_table_debug.json
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
REF = ROOT / "ref"
DEFAULT_SRC = Path(r"D:\SteamLibrary\steamapps\common\Starfield\Data\Scripts\Source\Base")

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

CALL = re.compile(r"\b([A-Za-z_]\w*)\s*\.\s*(Start|SetStage)\s*\(\s*(\d+)?\s*\)")
QF_NAME = re.compile(r"^QF_([A-Za-z0-9_]+)_([0-9A-Fa-f]{8})$")
FRAG_FN = re.compile(r"Fragment_Stage_(\d+)_Item_(\d+)")
FUNCDEF = re.compile(r"Function\s+(\w+)\s*\(")
PLAIN_NUM = re.compile(r"^([A-Za-z]+)(\d+)$")          # 纯编号（A 侧要求）


def key_of(edid: str):
    """EDID -> (字母前缀, 编号)。纯编号 或 编号+后缀 都返回；无编号返回 None。"""
    m = re.match(r"^([A-Za-z]+)(\d+)", edid or "")
    if not m:
        return None
    return (m.group(1), int(m.group(2)))


def is_plain(edid: str) -> bool:
    return bool(PLAIN_NUM.match(edid or ""))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", default=str(DEFAULT_SRC))
    ap.add_argument("--quests", default=str(REF / "quests_all.json"))
    ap.add_argument("--out", default=str(REF / "quest_chain.json"))
    ap.add_argument("--stats", action="store_true")
    a = ap.parse_args()

    src = Path(a.src)
    if not src.is_dir():
        # 源码目录不存在（CK 没装到默认位置）⇒ **不失败、也不覆盖旧产物**：
        # 静态表继续用上一份 ref\quest_chain.json（构建脚本据此保持幂等）。
        print(f"（没有 Papyrus 源码目录：{src} —— 保留现有 {a.out}，跳过链边提取）")
        return 0

    quests = json.loads(Path(a.quests).read_text(encoding="utf-8"))
    edid2q: dict[str, dict] = {}
    for q in quests:
        if q.get("edid") and (q.get("master") or "Starfield.esm") == "Starfield.esm":
            edid2q.setdefault(q["edid"], q)
    by_local = {q["local"]: q for q in edid2q.values()}
    edids_by_len = sorted(edid2q, key=len, reverse=True)

    def host_of_stem(stem: str):
        """脚本名 -> 宿主任务 local（QF_ 名字直接给 FormID；否则最长 EDID 前缀）。"""
        m = QF_NAME.match(stem)
        if m:
            return int(m.group(2), 16), m.group(1)
        for e in edids_by_len:
            if stem == e or stem.startswith(e):
                return edid2q[e]["local"], e
        return None, None

    edges = []          # 全部候选边（未过滤）
    for f in sorted(src.rglob("*.psc")):
        txt = f.read_text(encoding="utf-8", errors="replace")
        host_local, host_edid = host_of_stem(f.stem)
        for m in CALL.finditer(txt):
            prop, op, arg = m.group(1), m.group(2), m.group(3)
            tgt = edid2q.get(prop)
            if tgt is None:
                continue
            head = txt[: m.start()]
            fdef = list(FUNCDEF.finditer(head))
            fn = fdef[-1].group(1) if fdef else "?"
            fs = FRAG_FN.match(fn)
            stage = int(fs.group(1)) if fs else None
            edges.append({
                "target_local": tgt["local"],
                "target_edid": prop,
                "op": op,
                "arg": int(arg) if arg else 0,
                "src": f.name,
                "line": head.count("\n") + 1,
                "func": fn,
                "host_local": host_local,
                "host_edid": host_edid,
                "host_stage": stage,
            })

    # ---- 链边过滤（见文件头注释）----
    chain: dict[int, list[dict]] = defaultdict(list)
    for e in edges:
        tgt = by_local.get(e["target_local"])
        host = by_local.get(e["host_local"]) if e["host_local"] else None
        if tgt is None or host is None or host["local"] == tgt["local"]:
            continue
        if e["host_stage"] is None:                 # 必须是某任务的 stage fragment 触发
            continue
        if e["op"] == "SetStage" and e["arg"] == 0:  # SetStage(0) 是重置/回退，不是启动
            continue
        ha, hb = host.get("edid"), tgt.get("edid")
        if not is_plain(ha):                         # A 必须是纯编号（CF01，不是 CF01_xxx）
            continue
        ka, kb = key_of(ha), key_of(hb)
        if not ka or not kb:
            continue
        if ka[0] != kb[0] or kb[1] != ka[1] + 1:     # 同前缀 + 编号 +1
            continue
        chain[tgt["local"]].append({
            "host_local": host["local"],
            "host_master": host.get("master", "Starfield.esm"),
            "host_edid": ha,
            "host_stage": e["host_stage"],
            "op": e["op"],
            "arg": e["arg"],
            "src": e["src"],
            "line": e["line"],
        })

    # 同一 (host, stage) 可能有多条调用（同一 fragment 里 SetStage 多次）——去重
    out = []
    for local in sorted(chain):
        seen = set()
        items = []
        for e in chain[local]:
            k = (e["host_local"], e["host_stage"])
            if k in seen:
                continue
            seen.add(k)
            items.append(e)
        q = by_local[local]
        out.append({
            "formid": local,
            "edid": q.get("edid"),
            "edges": items,
        })

    if not a.stats:
        Path(a.out).write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"wrote {a.out}")

    print(f"候选边（全部跨任务调用，含噪声）：{len(edges)}")
    print(f"链边（前缀+编号+1 且来自纯编号任务的 stage fragment）：{len(out)} 条任务")
    for t in out:
        chain_str = " | ".join(f"{e['host_edid']}@{e['host_stage']}→{e['op']}({e['arg']})" for e in t["edges"])
        print(f"  {t['edid']:<32} 0x{t['formid']:06X}  <=  {chain_str}")
    pfx = defaultdict(list)
    for t in out:
        k = key_of(t["edid"])
        if k:
            pfx[k[0]].append(k[1])
    print("\n涉及前缀：", {k: sorted(v) for k, v in sorted(pfx.items())})

    # 只统计表内任务
    kept_path = REF / "quest_table_debug.json"
    if kept_path.exists():
        kept = {q["formid"] for q in json.loads(kept_path.read_text(encoding="utf-8"))}
        in_table = [t for t in out if t["formid"] in kept]
        print(f"\n其中在「可接任务」表内：{len(in_table)} 条")
        for t in in_table:
            print(f"  {t['edid']:<32} 0x{t['formid']:06X}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
