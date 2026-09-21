#!/usr/bin/env python3
"""pex_strings.py - 从编译后的 Papyrus `.pex` 里抽「字符串表」证据（第 78 轮）。

用途：DLC（ShatteredSpace / SFBGS050 / SFBGS00D）**没有 .psc 源码**（官方只发 .pex），
但 .pex 里有：
  * 字符串表 —— 脚本里用到的标识符（**属性名**/函数名/方法名…）；
  * 函数名 —— `Fragment_Stage_NNNN_Item_MM`（这个脚本实现了哪些 stage fragment ⇒
    该任务有哪些 stage）；
  * 方法名 —— `Start` / `SetStage` / `CompleteQuest` / `SendStoryEvent` …

⇒ 对「QF_<EDID>_<formid>.pex」：抽出的字符串里若出现**别的表内任务 EDID**，
  说明这个任务的脚本**引用了**那个任务（Papyrus 属性名 = 目标任务的 EDID，
  与基础游戏的 .psc 写法一致）—— 结合社区任务表（谁是谁的后续）即可作为
  「启动边」的旁证（第 78 轮用它给 DLC 主线的后续加链式门槛）。

用法：
    python tools/re/pex_strings.py <目录或 .pex 文件> [--grep 关键词] [--json 输出.json]
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
REF = ROOT / "ref"

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

STR = re.compile(rb"[\x20-\x7E]{4,}")
QF = re.compile(r"^QF_([A-Za-z0-9_]+)_([0-9A-Fa-f]{8})(?:_\d+)?$", re.I)
FRAG = re.compile(r"Fragment_Stage_(\d+)_Item_\d+")


def strings_of(p: Path) -> list[str]:
    out = []
    for m in STR.finditer(p.read_bytes()):
        out.append(m.group(0).decode("ascii", "replace"))
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("target", help="目录或 .pex 文件")
    ap.add_argument("--grep", default="")
    ap.add_argument("--json", default="")
    ap.add_argument("--limit", type=int, default=40)
    a = ap.parse_args()

    # 表内任务 EDID（全部 master）
    tbl = json.loads((REF / "quest_table_debug.json").read_text(encoding="utf-8"))
    edids = {t["edid"] for t in tbl if t.get("edid")}
    local2edid = {(int(t["master_idx"]) if "master_idx" in t else 0, int(t["local"]) & 0xFFFFFF): t["edid"]
                  for t in tbl}
    by_local = {int(t["local"]) & 0xFFFFFF: t["edid"] for t in tbl}

    root = Path(a.target)
    files = sorted(root.rglob("*.pex")) if root.is_dir() else [root]
    rows = []
    for f in files:
        ss = strings_of(f)
        sset = set(ss)
        own = None
        m = QF.match(f.stem)
        if m:
            own = m.group(1)
            low = int(m.group(2), 16) & 0xFFFFFF
            if own.lower().startswith("qf_"):
                own = own[3:]
            own = by_local.get(low, own)
        refs = sorted({s for s in sset if s in edids and s != own})
        stages = sorted({int(x) for s in sset for x in FRAG.findall(s)})
        calls = sorted({k for k in ("Start", "SetStage", "SetStageNoWait", "CompleteQuest",
                                    "SendStoryEvent", "SendStoryEventAndWait", "Stop")
                        if k in sset})
        rows.append({"file": f.name, "own": own, "refs": refs, "stages": stages, "calls": calls})

    if a.json:
        Path(a.json).write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"wrote {a.json}")

    shown = 0
    for r in rows:
        if not r["refs"] and not a.grep:
            continue
        line = (f"{r['file']:<58} own={str(r['own']):<28} refs={','.join(r['refs'])[:90]:<90}"
                f" stages={r['stages'][:6]} calls={','.join(r['calls'])}")
        if a.grep and a.grep.lower() not in line.lower():
            continue
        print(line)
        shown += 1
        if shown >= a.limit:
            print(f"…（还有更多，--limit 调大 / 用 --json）")
            break
    print(f"\n共 {len(rows)} 个 .pex，其中带表内引用 {sum(1 for r in rows if r['refs'])} 个")
    return 0


if __name__ == "__main__":
    sys.exit(main())
