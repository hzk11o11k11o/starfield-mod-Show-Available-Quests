#!/usr/bin/env python3
"""gen_dlc_chain.py - 第 98 轮：**DLC 的链式门槛取证**（反编译 .pex → 启动边）。

背景（docs/06 六节留下的缺口）：
  * 基础游戏的「任务链门槛」（`ref/quest_chain.json` / `quest_chain_extra.json`）是从
    **官方 Papyrus 源码**（`Data\\Scripts\\Source\\Base\\*.psc`）里挖出来的；
  * **DLC 不发 .psc**（只有 `.pex` 字节码）⇒ 第 78 轮只能「抽字符串表」，而
    `MQ_Shell` / `DialogueHV*` 与各 MQ **双向引用** ⇒ **定不出方向**；
  * 于是破碎空间主线后续（MQ02~MQ06）只能按 INFO 门槛「保守放行」——玩家进度没到
    也会看到它们（这是「进度没到不显示」在 DLC 上的唯一缺口）。

本工具把这一环补上（**零猜测**，全部来自官方字节码）：
  1. **抽**：从 DLC 的 BA2 里解出 `.pex`（`ShatteredSpace - Main01.ba2` 363 个 /
     `SFBGS050 - Main.ba2` 311 个 …）→ `ref/pex_dlc/<key>/`；
  2. **反编译**：用 Champollion（Orvid 分支，支持 Starfield 的 pex 3.12 / gameId 4）
     → `tmp/psc_dlc/<key>/`（与反编译前的目录结构一致）；
     Champollion 下载：https://github.com/Orvid/Champollion/releases （1.3.2 实测可用）
     —— 放 `tools/champollion/Champollion.exe`（已 gitignore：第三方二进制不入库）；
  3. **抽边**：把每个脚本里的「Quest 属性 + `.Start()` / `.SetStage(N)`」调用连同
     **包含它的 fragment 函数**（`Fragment_Stage_XXXX_Item_NN`）一起抽出来 ⇒
     「宿主任务 @ stage ⇒ 目标任务被启动」= 一条候选启动边；
     排除：`SetStage(0)`（重置）、自调用、目标不在「可接任务表」里的。
     非 stage fragment 的形态（`QuestCompleted` 等）也记下来（`need_stage` 标记，
     需要人工翻成「宿主完成 stage」）；
  4. **定稿**：`CURATED` 里的边逐条对候选核验（找不到 ⇒ 直接失败，防手写漂移），
     输出 `ref/quest_chain_dlc.json`（与 `quest_chain_extra.json` 同格式，
     可直接被 `gen_quest_table.py --chain-extra` 一类的合并逻辑消费）。

用法：
    python tools/esm/gen_dlc_chain.py                 # 全流程（抽 + 反编译 + 候选 + 定稿）
    python tools/esm/gen_dlc_chain.py --stats         # 只统计候选（不写产物）
    python tools/esm/gen_dlc_chain.py --force         # 强制重抽 / 重反编译
    python tools/esm/gen_dlc_chain.py --list          # 打印全部候选边
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools" / "re"))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

GAME_DATA = Path(r"D:\SteamLibrary\steamapps\common\Starfield\Data")
# (master, 装 .pex 的 ba2, 缓存键)
SOURCES = [
    ("ShatteredSpace.esm", "ShatteredSpace - Main01.ba2", "shatteredspace"),
    ("SFBGS050.esm", "SFBGS050 - Main.ba2", "sfbgs050"),
    ("SFBGS00D.esm", "SFBGS00D - Main.ba2", "sfbgs00d"),
]
CHAMPOLLION = ROOT / "tools" / "champollion" / "Champollion.exe"
PEX_ROOT = ROOT / "ref" / "pex_dlc"
PSC_ROOT = ROOT / "tmp" / "psc_dlc"
CAND_JSON = ROOT / "ref" / "dlc_chain_candidates.json"
OUT_JSON = ROOT / "ref" / "quest_chain_dlc.json"

RE_PROP = re.compile(r"^\s*Quest(?:\[\])?\s+Property\s+([A-Za-z0-9_]+)", re.I | re.M)
RE_FUNC = re.compile(r"^\s*(?:Function|Event)\s+([A-Za-z0-9_]+)", re.I | re.M)
RE_FRAG = re.compile(r"Fragment_Stage_(\d+)_Item_(\d+)", re.I)
RE_CALL = re.compile(
    r"([A-Za-z0-9_]+)\s*\.\s*(Start|SetStage|SetStageNoWait|SendStoryEvent[A-Za-z]*)\s*\(([^)]*)\)")
RE_QF = re.compile(r"^qf_([a-z0-9_]+?)_([0-9a-f]{8})(?:_\d+)?$", re.I)

# ---------------------------------------------------------------------------
# 定稿表（★ 人工核实；每条边都必须能在候选里找到 —— 构建期核验防手写漂移）
#
# 破碎空间主线（第 98 轮取证，证据全在官方 .pex 的 stage fragment 里）：
#   MQ01「残留之物」@10000 → MQ02.SetStage(100)
#   MQ02「虚妄的得诺者」@2000 → MQ_Shell.SetStage(100)
#   MQ_Shell「家族的调和」@100 → MQ03 / MQ04 / MQ05 各 SetStage(100)（三条议会任务一起开）
#   MQ_Shell@1100（终局）→ MQ06.SetStage(100)
# 语义（与基础游戏链式门槛完全一致）：**全部入边都没触发 ⇒ 隐藏**（进度没到）。
# ---------------------------------------------------------------------------
CURATED = [
    ("SFBGS001_MQ02", "SFBGS001_MQ01", 10000,
     "残留之物@10000（收尾 fragment）里 SFBGS001_MQ02.SetStage(100) —— 虚妄的得诺者"),
    ("SFBGS001_MQ_Shell", "SFBGS001_MQ02", 2000,
     "虚妄的得诺者@2000（收尾）里 SFBGS001_MQ_Shell.SetStage(100) —— 家族的调和"),
    ("SFBGS001_MQ03", "SFBGS001_MQ_Shell", 100,
     "家族的调和@100 里 MQ03/MQ04/MQ05 三条议会任务一起 SetStage(100)"),
    ("SFBGS001_MQ04", "SFBGS001_MQ_Shell", 100,
     "家族的调和@100 里 MQ03/MQ04/MQ05 三条议会任务一起 SetStage(100)"),
    ("SFBGS001_MQ05", "SFBGS001_MQ_Shell", 100,
     "家族的调和@100 里 MQ03/MQ04/MQ05 三条议会任务一起 SetStage(100)"),
    ("SFBGS001_MQ06", "SFBGS001_MQ_Shell", 1100,
     "家族的调和@1100（终局）里 SFBGS001_MQ06.SetStage(100) —— 栉比堡垒"),
]


# ---------------------------------------------------------------------------
#  1. 从 BA2 抽 .pex
# ---------------------------------------------------------------------------
def extract_pex(force: bool) -> None:
    from ba2list import open_ba2  # tools/re/ba2list.py

    for master, ba2_name, key in SOURCES:
        dest = PEX_ROOT / key
        ba2 = GAME_DATA / ba2_name
        if not ba2.exists():
            print(f"（没有 {ba2} —— 跳过 {master}）")
            continue
        have = sum(1 for _ in dest.rglob("*.pex")) if dest.exists() else 0
        if have and not force:
            print(f"{master}: 已有 {have} 个 .pex（--force 可重抽）")
            continue
        n = 0
        with open_ba2(ba2) as arc:
            for entry in arc.files:
                if not entry["name"].lower().endswith(".pex"):
                    continue
                arc.extract(entry, dest)
                n += 1
        print(f"{master}: 从 {ba2_name} 抽出 {n} 个 .pex → {dest.relative_to(ROOT)}")


# ---------------------------------------------------------------------------
#  2. 反编译（Champollion）
# ---------------------------------------------------------------------------
def decompile(force: bool) -> None:
    if not CHAMPOLLION.exists():
        print(f"!! 缺 Champollion：{CHAMPOLLION}\n"
              f"   下载 https://github.com/Orvid/Champollion/releases （v1.3.2）解压到 "
              f"tools/champollion/ 即可（第三次运行起可离线复现）。")
        return
    for master, _ba2, key in SOURCES:
        src = PEX_ROOT / key
        if not src.exists():
            continue
        out = PSC_ROOT / key
        pex = sorted(src.rglob("*.pex"))
        if not pex:
            continue
        out.mkdir(parents=True, exist_ok=True)
        have = {p.stem.lower() for p in out.rglob("*.psc")}
        if force or not have:
            # ① 递归批处理（快）；★ 注意 Champollion 的 -r 会漏掉「与递归根同级目录里的文件」
            subprocess.run([str(CHAMPOLLION), "-r", "-t", "-p", str(out), str(src)],
                           capture_output=True)
            have = {p.stem.lower() for p in out.rglob("*.psc")}
        # ② 补齐漏掉的（显式传文件；按批避免命令行过长）
        missing = [p for p in pex if p.stem.lower() not in have]
        for i in range(0, len(missing), 40):
            subprocess.run([str(CHAMPOLLION), "-p", str(out)] +
                           [str(p) for p in missing[i:i + 40]], capture_output=True)
        have = {p.stem.lower() for p in out.rglob("*.psc")}
        left = [p.name for p in pex if p.stem.lower() not in have]
        print(f"{master}: .pex {len(pex)} 个 → .psc {len(have)} 个"
              + (f"（仍未成功 {len(left)}：{left[:3]}…）" if left else "（全部反编译成功）"))


# ---------------------------------------------------------------------------
#  3. 抽候选启动边
# ---------------------------------------------------------------------------
def realpath_of(master: str) -> str:
    return master


def build_candidates() -> list[dict]:
    tbl = json.loads((ROOT / "ref" / "quest_table_debug.json").read_text(encoding="utf-8"))
    by_edid = {t["edid"]: t for t in tbl if t.get("edid")}
    by_local = {int(t["local"]) & 0xFFFFFF: t for t in tbl}

    allq = json.loads((ROOT / "ref" / "quests_all.json").read_text(encoding="utf-8"))
    host_by_local: dict[int, dict] = {}
    for q in allq:
        if q.get("edid"):
            host_by_local.setdefault(int(q["local"]) & 0xFFFFFF, q)
    host_edids = sorted({q["edid"] for q in allq if q.get("edid")}, key=len, reverse=True)
    by_edid_all = {q["edid"]: q for q in allq if q.get("edid")}

    def host_of(stem: str):
        m = RE_QF.match(stem)
        if m:
            local = int(m.group(2), 16) & 0xFFFFFF
            q = host_by_local.get(local)
            return (local, q["edid"], q["master"]) if q else (None, None, None)
        low = stem.lower()
        for e in host_edids:
            if low.startswith(e.lower()):
                q = by_edid_all[e]
                return int(q["local"]) & 0xFFFFFF, q["edid"], q["master"]
        return None, None, None

    def func_of(text: str, pos: int) -> str:
        name = "?"
        for m in RE_FUNC.finditer(text):
            if m.end() <= pos:
                name = m.group(1)
            else:
                break
        return name

    cand: dict[int, list[dict]] = defaultdict(list)
    stats: dict[str, int] = defaultdict(int)
    for f in sorted(PSC_ROOT.rglob("*.psc")):
        txt = f.read_text(encoding="utf-8", errors="replace")
        props = set(RE_PROP.findall(txt))
        host_local, host_edid, host_master = host_of(f.stem)
        if host_local is None:
            stats["宿主任务认不出"] += 1
            continue
        for m in RE_CALL.finditer(txt):
            prop, op, arg = m.group(1), m.group(2), m.group(3).strip()
            if prop not in props:
                continue
            tgt = by_edid.get(prop)
            if tgt is None:
                stats["目标不在表内"] += 1
                continue
            tgt_local = int(tgt["local"]) & 0xFFFFFF
            if tgt_local == host_local:
                stats["自调用"] += 1
                continue
            fn = func_of(txt, m.start())
            fs = RE_FRAG.match(fn)
            stage = int(fs.group(1)) if fs else None
            if stage is not None and op == "SetStage" and arg.isdigit() and int(arg) == 0:
                stats["SetStage(0)（重置）"] += 1
                continue
            if stage is None:
                stats[f"非 stage fragment（{fn}）"] += 1
            cand[tgt_local].append({
                "host_local": host_local,
                "host_master": host_master,
                "host_edid": host_edid,
                "host_stage": stage,
                "op": op,
                "arg": int(arg) if arg.isdigit() else arg,
                "src": f.name,
                "line": txt.count("\n", 0, m.start()) + 1,
                "func": fn,
                **({"need_stage": True} if stage is None else {}),
            })

    out = []
    for local in sorted(cand):
        q = by_local[local]
        seen, items = set(), []
        for e in sorted(cand[local], key=lambda x: (x["host_local"],
                                                     -1 if x["host_stage"] is None else x["host_stage"])):
            k = (e["host_local"], e["host_stage"], e["op"], str(e["arg"]))
            if k in seen:
                continue
            seen.add(k)
            items.append(e)
        # ★ formid 口径 = **文件里的原始 FormID**（带该文件自己的 master 前缀，如
        #   ShatteredSpace 的 0x01xxxxxx）—— 与 quest_chain.json / info_gates 等所有
        #   ref/*.json 一致，也是 gen_quest_table 里 `r["formid"]` 的样子；
        #   记录号（local）只用在 host_local / kChainGates 的 host 侧。
        out.append({"formid": int(q["formid"]), "edid": q["edid"], "master": q["master"],
                    "edges": items})
    return out, dict(stats)


# ---------------------------------------------------------------------------
#  4. 定稿（核验 + 写 ref/quest_chain_dlc.json）
# ---------------------------------------------------------------------------
def curate(cands: list[dict]) -> int:
    idx: dict[tuple, dict] = {}
    meta: dict[str, dict] = {}
    for t in cands:
        meta[t["edid"]] = t
        for e in t["edges"]:
            idx[(t["edid"], e["host_edid"], e["host_stage"], e["op"])] = e

    out: dict[str, dict] = {}
    bad = []
    for tgt_edid, host_edid, host_stage, note in CURATED:
        e = idx.get((tgt_edid, host_edid, host_stage, "SetStage"))
        if e is None:
            bad.append(f"{tgt_edid} <= {host_edid}@{host_stage}（候选里找不到）")
            continue
        t = meta[tgt_edid]
        # 宿主 master / local 从候选边抄（含 DLC 的 master 名）
        out.setdefault(tgt_edid, {"formid": t["formid"], "edid": tgt_edid, "edges": []})
        out[tgt_edid]["edges"].append({
            "host_local": e["host_local"],
            "host_master": e["host_master"],
            "host_edid": host_edid,
            "host_stage": host_stage,
            "op": e["op"],
            "arg": e["arg"],
            "src": e["src"],
            "line": e["line"],
            "note": note,
        })

    if bad:
        print("!! 定稿核验失败（手写边在候选里找不到）：")
        for b in bad:
            print("   " + b)
        return 1

    payload = [out[k] for k in sorted(out)]
    OUT_JSON.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    n_edges = sum(len(t["edges"]) for t in payload)
    print(f"wrote {OUT_JSON}：{len(payload)} 条任务 / {n_edges} 条边（全部对候选核验通过）")
    for t in payload:
        for e in t["edges"]:
            print(f"  {t['edid']:<22} <= {e['host_edid']}@{e['host_stage']}"
                  f"  {e['op']}({e['arg']})  {e['src']}:{e['line']}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true", help="强制重抽 .pex / 重反编译")
    ap.add_argument("--stats", action="store_true", help="只统计候选（不写定稿）")
    ap.add_argument("--list", action="store_true", help="打印全部候选边")
    ap.add_argument("--skip-extract", action="store_true")
    ap.add_argument("--skip-decompile", action="store_true")
    ap.add_argument("--strict", action="store_true",
                    help="缺 Champollion / 缺反编译缓存时**失败**（默认：保留现有产物、退出 0"
                         "—— 与 gen_quest_chain.py 的「源码目录没有就沿用旧产物」同款宽容）")
    a = ap.parse_args()

    if not a.skip_extract:
        extract_pex(a.force)
    if not a.skip_decompile:
        decompile(a.force)
    if not PSC_ROOT.exists():
        msg = (f"没有反编译产物 {PSC_ROOT} —— 先跑（或补 Champollion：见本文件头）：\n"
               f"    python tools\\esm\\gen_dlc_chain.py")
        if a.strict:
            print("!! " + msg)
            return 2
        print(f"（{msg}\n  ⇒ 保留现有 {OUT_JSON.relative_to(ROOT)}，跳过 DLC 链边提取）")
        return 0

    cands, stats = build_candidates()
    CAND_JSON.write_text(json.dumps(cands, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"wrote {CAND_JSON}：{len(cands)} 条表内任务有候选入边，"
          f"共 {sum(len(t['edges']) for t in cands)} 条边")
    print("跳过统计：", stats)
    if a.list:
        for t in cands:
            print(f"{t['edid']:<26} [{t['master']}]")
            for e in t["edges"]:
                stage = "?" if e["host_stage"] is None else e["host_stage"]
                flag = " ★需定 stage" if e.get("need_stage") else ""
                print(f"    <= {e['host_edid']:<26}@{stage:<6} {e['op']}({e['arg']})"
                      f"  {e['src']}:{e['line']}  @{e['func']}{flag}")
    if a.stats:
        return 0
    return curate(cands)


if __name__ == "__main__":
    sys.exit(main())
