#!/usr/bin/env python3
"""gen_companion_quests.py - 第 74 轮：**同伴好感度任务表**（入口固定显示 + 后续仍走链式门槛）。

起因（玩家要求）：
  「把所有达到一定好感度才能接到的同伴任务固定在可接任务列表里，任务名称前面写上
    同伴的名字，并在提示里提示到达一定好感度才能接取」
  「注意，链式关系的后续任务还是不要显示，只显示入口任务」

哪些是「同伴好感度任务」？—— 官方数据里就是 `COM_Quest_<同伴>_*` 这一组（表内 8 条）：
  * **入口**（个人任务）`COM_Quest_<同伴>_Q01`：违约 / 难侍二主 / 哈特家事 / 难忘逝者
    —— 由同伴主任务 `COM_Companion_<同伴>` 的**好感度里程碑**直接启动，是这条线的
    第一环 ⇒ **固定显示**（不做三类门槛过滤）+ 名字前缀同伴名 + 描述里提示好感度要求；
  * **后续**（承诺/恋爱 → 结婚）`COM_Quest_<同伴>_Commitment`：承诺：巴雷特 等 4 条
    —— 只能在个人任务做完、好感度继续推进之后才启动 ⇒ **不固定显示**，照旧由
    「链式门槛」判（全部启动边都没触发 ⇒ 隐藏；这正是玩家要求的「后续任务不要显示」）。
    ★ 本轮顺带把 4 条承诺任务的启动边补全（此前只有巴雷特那条）：
      · 巴雷特：宿主 `Com_Companion_Barrett@900`（fragment 里 SetStage(50)，第 71 轮已有）；
      · 安德列娅：宿主 `COM_Companion_Andreja@2000`（fragment 里 StartCommitmentQuest()）；
      · 萨姆·科尔：宿主 `COM_Companion_SamCoe@825`（同上）；
      · 莎拉·摩根：里程碑是**场景 fragment**（`SF_COM_SarahMorgan_Story_SG0_0027B5AA`
        的 phase 06 end 调 StartCommitmentQuest）—— 没有宿主 stage 可用 ⇒ 退一步用
        **个人任务完成**当边（`COM_Quest_SarahMorgan_Q01@1000`：两个 item fragment 在
        这个 stage 里调 `FinishedPersonalQuest()`，把好感度推到第 2 级；承诺任务是
        第 3 级的事 ⇒ 这条前置是**必要条件**，略保守地放行，注释见 evidence）。

## 产出 `ref/companion_quests.json`（gen_quest_table.py 消费）

    [
      {
        "key": "Barrett",                 # EDID: COM_Quest_<key>_<rest>
        "host": "Com_Companion_Barrett",  # 好感度宿主任务（EDID 大小写按原始记录）
        "nameZh": "巴雷特", "nameEn": "Barrett",
        "quests": [
          {"edid": "COM_Quest_Barrett_Q01", "formid": 223659, "local": 223659,
           "master": "Starfield.esm", "kind": "personal", "pin": true,
           "evidence": "QF_COM_Companion_Barrett_001C7187.psc:73 ...", "followUpGate": null},
          {"edid": "COM_Quest_Barrett_Commitment", ..., "kind": "commitment", "pin": false,
           "evidence": "...", "followUpGate": {"hostEdid": "Com_Companion_Barrett",
             "hostLocal": 1864071, "hostStage": 900, "source": "milestone",
             "evidence": "QF_COM_Companion_Barrett_001C7187.psc:473 ..."}}
        ]
      }, ...
    ]

## 名字从哪来（不写死）
同伴显示名 = **承诺任务官方本地化名里冒号后半段**：
    「承诺：巴雷特」 / 「Commitment: Barrett」 ⇒ 巴雷特 / Barrett
（名字来自官方 strings 表；解析失败 ⇒ 直接报错退出，不静默写错数据。）

## 构建期核验（对着官方 Papyrus 源码 `Data\\Scripts\\Source\\Base`）
每个同伴 key 必须满足（任一不符 ⇒ 不写产物、退出码 1）：
  ① 宿主任务 `COM_Companion_<key>` 存在（**EDID 大小写不敏感** —— 巴雷特那条的
     真实 EDID 是 `Com_Companion_Barrett`）；
  ② 入口（个人任务）：宿主侧文件（文件名含 key）里有 `<Q01 EDID>.Start(` / `.SetStage(`
     调用（好感度里程碑 stage fragment 启动它）；
  ③ 后续（承诺任务）：必须找到一条**启动边**（`followUpGate`）——
     直接调用 / `StartCommitmentQuest()`（在某个 stage fragment 里）/ 个人任务完成；
  ④ 全局好感度机制在：`COM_CompanionQuestScript.psc` 必须有 `StartPersonalQuest` /
     `StartCommitmentQuest` 与 `COM_AffinityLevel_1_Friendship` / `_3_Commitment`。

源码目录不在时：保留现有产物、跳过核验（与 gen_quest_chain_extra.py 同一约定）。

用法：
    python tools/esm/gen_companion_quests.py             # 核验 + 写 ref/companion_quests.json
    python tools/esm/gen_companion_quests.py --list      # 只看当前产物
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
REF = ROOT / "ref"
DEFAULT_SRC = Path(r"D:\SteamLibrary\steamapps\common\Starfield\Data\Scripts\Source\Base")

QUID = re.compile(r"^COM_Quest_([A-Za-z]+)_(.+)$")
Q01_NAME = re.compile(r"^COM_Quest_(.+)_Q01$")
FRAG_FN = re.compile(r"Function\s+Fragment_Stage_(\d+)_Item_\d+\s*\(")

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def name_from_localized(name: str, seps: tuple[str, ...]) -> str | None:
    """从「承诺：<名>」/「Commitment: <名>」里取出同伴名（冒号后半段）。"""
    for sep in seps:
        if sep in name:
            tail = name.rsplit(sep, 1)[1].strip()
            if 0 < len(tail) <= 24:
                return tail
    return None


def kind_of(edid: str) -> str:
    if edid.endswith("_Commitment"):
        return "commitment"
    if edid.endswith("_Q01"):
        return "personal"
    return "other"


def load_table(path: Path) -> list[dict]:
    rows = json.loads(path.read_text(encoding="utf-8"))
    return [r for r in rows if (r.get("edid") or "").startswith("COM_Quest_")]


def load_official_strings(strings_dir: Path) -> tuple[dict[int, str], dict[int, str]]:
    """基础游戏的官方本地化名（en / zhhans）。

    ★ 为什么名字要从**strings 表**取、而不是从静态表（quest_table_debug.json）取：
      静态表的任务名会被 gen_quest_table.py 按本工具的输出**加同伴名前缀**
      （「承诺：巴雷特」→「巴雷特：承诺」）⇒ 本工具重跑时如果读静态表，
      解析出的「同伴名」会变成「承诺」（踩过一次）—— 必须读原始官方名。
    """
    sys.path.insert(0, str(Path(__file__).parent))
    from strings_probe import load_strings
    return (load_strings(strings_dir / "starfield_en.strings"),
            load_strings(strings_dir / "starfield_zhhans.strings"))


def scan_host_files(src: Path, key: str) -> list[tuple[Path, list[str]]]:
    """读「文件名含 key」的官方脚本（宿主 QF / 同同伴的场景 fragment / 对话 fragment）。"""
    out: list[tuple[Path, list[str]]] = []
    for f in src.rglob("*.psc"):
        if key.lower() not in f.name.lower():
            continue
        try:
            out.append((f, f.read_text(encoding="utf-8", errors="replace").splitlines()))
        except OSError:
            continue
    return out


def enclosing_stage(lines: list[str], line_no: int) -> int | None:
    """从 line_no 往上找最近的 `Fragment_Stage_<n>_Item_*`（场景 fragment 没有 ⇒ None）。"""
    for i in range(line_no - 1, 0, -1):
        m = FRAG_FN.search(lines[i - 1])
        if m:
            return int(m.group(1))
    return None


def find_direct_call(files: list[tuple[Path, list[str]]], edid: str) -> str | None:
    """在宿主侧文件里找 `<EDID>.Start(` / `<EDID>.SetStage(`（返回 一行证据）。"""
    pat = re.compile(rf"\b{re.escape(edid)}\s*\.\s*(?:Start|SetStage)\s*\(")
    for f, lines in files:
        for i, ln in enumerate(lines, 1):
            if pat.search(ln):
                return f"{f.name}:{i} {ln.strip()}"
    return None


def find_direct_stage(files: list[tuple[Path, list[str]]], edid: str) -> tuple[int, str] | None:
    """`<EDID>.Start/.SetStage(` 所在 stage fragment ⇒ (stage, 证据)。"""
    pat = re.compile(rf"\b{re.escape(edid)}\s*\.\s*(?:Start|SetStage)\s*\(")
    for f, lines in files:
        for i, ln in enumerate(lines, 1):
            if pat.search(ln):
                st = enclosing_stage(lines, i)
                if st is not None:
                    return st, f"{f.name}:{i} {ln.strip()}"
    return None


def find_commitment_start_stage(files: list[tuple[Path, list[str]]]) -> tuple[int, str] | None:
    """宿主 fragment 里 `StartCommitmentQuest()` 所在的 stage（承诺任务的启动边）。"""
    pat = re.compile(r"\bStartCommitmentQuest\s*\(")
    for f, lines in files:
        for i, ln in enumerate(lines, 1):
            if pat.search(ln):
                st = enclosing_stage(lines, i)
                if st is not None:
                    return st, f"{f.name}:{i} {ln.strip()}"
    return None


def find_personal_finish_stage(src: Path, q01_local: int) -> tuple[Path, int, str] | None:
    """个人任务的「完成」stage：`FinishedPersonalQuest()` 所在 fragment（莎拉的兜底边）。

    为什么需要它：莎拉·摩根的承诺任务由**场景 fragment**启动（没有宿主 stage 可引用），
    退一步用「个人任务完成」当启动边 —— 承诺是个人任务之后的事，这是必要条件。
    """
    pat = re.compile(r"\bFinishedPersonalQuest\s*\(")
    for f in src.rglob("*.psc"):
        m = re.search(r"_([0-9A-Fa-f]{8})\.psc$", f.name)
        if not m or int(m.group(1), 16) != q01_local:
            continue
        try:
            lines = f.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        for i, ln in enumerate(lines, 1):
            if pat.search(ln):
                st = enclosing_stage(lines, i)
                if st is not None:
                    return f, st, f"{f.name}:{i} {ln.strip()}"
    return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--quests", default=str(REF / "quests_all.json"))
    ap.add_argument("--table", default=str(REF / "quest_table_debug.json"))
    ap.add_argument("--strings-dir", default=str(REF / "strings" / "strings"),
                    help="官方 strings 表（同伴名从这里解析 —— 不读静态表，见 load_official_strings）")
    ap.add_argument("--src", default=str(DEFAULT_SRC))
    ap.add_argument("--out", default=str(REF / "companion_quests.json"))
    ap.add_argument("--list", action="store_true")
    a = ap.parse_args()

    if a.list:
        p = Path(a.out)
        if not p.exists():
            print(f"（还没有 {p}）")
            return 0
        for g in json.loads(p.read_text(encoding="utf-8")):
            print(f"  {g['key']:<12} {g['nameZh']} / {g['nameEn']}"
                  f"（宿主 {g['host']}）：")
            for q in g["quests"]:
                tag = "入口（固定显示）" if q["pin"] else "后续（走链式门槛）"
                print(f"      {q['edid']:<40} 0x{q['local']:06X} [{tag}] {q['evidence']}")
                if q.get("followUpGate"):
                    fg = q["followUpGate"]
                    print(f"          启动边：{fg['hostEdid']}@{fg['hostStage']}"
                          f"（{fg['source']}）｜{fg['evidence']}")
        return 0

    table = load_table(Path(a.table))
    quests = json.loads(Path(a.quests).read_text(encoding="utf-8"))
    # ★ 宿主任务可能被 DLC **override**（如 SFBGS050.esm 里也有一条 COM_Companion_Andreja）
    #   ⇒ 取 **Starfield.esm** 那条（基础游戏记录；与 gen_quest_chain_extra.py 同一约定，
    #   否则链式边会落到 DLC 的 master 空间上）。
    edid_lower: dict[str, dict] = {}
    for q in quests:
        e = (q.get("edid") or "").lower()
        if not e:
            continue
        if e in edid_lower and (q.get("master") or "Starfield.esm") != "Starfield.esm":
            continue
        edid_lower[e] = q

    # ★ 同伴名从官方 strings 表解析（不读静态表，见 load_official_strings 的注释）
    strings_dir = Path(a.strings_dir)
    if not (strings_dir / "starfield_en.strings").exists():
        print(f"核验失败（不写产物）：缺官方 strings 表 {strings_dir}")
        return 1
    str_en, str_zh = load_official_strings(strings_dir)

    # 按 key 分组（表内任务）
    groups: dict[str, list[dict]] = {}
    for r in table:
        m = QUID.match(r["edid"])
        if m:
            groups.setdefault(m.group(1), []).append(r)

    problems: list[str] = []
    out: list[dict] = []
    for key in sorted(groups):
        rows = sorted(groups[key], key=lambda r: r["local"])
        by_edid = {r["edid"]: r for r in rows}
        commit_edid = f"COM_Quest_{key}_Commitment"
        commit = by_edid.get(commit_edid)
        if commit is None:
            problems.append(f"{key}：组里没有承诺任务 {commit_edid}（同伴名解析不了 ——"
                            f"该组的任务不会被标记为同伴好感度任务）")
            continue
        # ★ 名字从**官方 strings 表**解析（不读静态表 —— 表名已被加了前缀，见该函数注释）
        commit_rec = next((q for q in quests if (q.get("edid") or "") == commit_edid
                           and (q.get("master") or "Starfield.esm") == "Starfield.esm"), None)
        raw_zh = raw_en = ""
        if commit_rec is not None and commit_rec.get("full") is not None:
            sid = int(commit_rec["full"])
            raw_zh = str_zh.get(sid, "")
            raw_en = str_en.get(sid, "")
        name_zh = name_from_localized(raw_zh, ("：", ":"))
        name_en = name_from_localized(raw_en, (": ", ":", "："))
        if not name_zh or not name_en:
            problems.append(f"{commit_edid}：官方名解析不出同伴名"
                            f"（zh={raw_zh!r} en={raw_en!r}）")
            continue

        host_edid = f"COM_Companion_{key}"
        host = edid_lower.get(host_edid.lower())
        if host is None:
            problems.append(f"{key}：找不到宿主任务 {host_edid}（好感度里程碑的载体）")
            continue
        host_edid_real = host["edid"]

        group = {
            "key": key,
            "host": host_edid_real,
            "hostLocal": int(host["local"]),
            "hostMaster": host.get("master", "Starfield.esm"),
            "nameZh": name_zh,
            "nameEn": name_en,
            # quests 在核验完证据后填充（见下方 for r in rows）
            "quests": [],
        }

        src = Path(a.src)
        if not src.is_dir():
            print(f"（没有 Papyrus 源码目录：{src} —— 保留现有 {a.out}，跳过核验）")
            return 0

        host_files = scan_host_files(src, key)
        if not host_files:
            problems.append(f"{key}：源码里没有任何文件名含 {key} 的脚本"
                            f"（宿主侧证据找不到）")
            continue

        q01 = next((r for r in rows if r["edid"].endswith("_Q01")), None)
        if q01 is None:
            problems.append(f"{key}：组里没有个人任务（*_Q01）")
            continue
        ev_q01 = find_direct_call(host_files, q01["edid"])
        if not ev_q01:
            problems.append(f"{key}：{q01['edid']} 在宿主侧脚本里没有 .Start/.SetStage 调用")
            continue

        # 承诺任务的启动边（第 74 轮：4 条都要有 —— 否则「后续任务」会一直显示）
        fg_stage = find_direct_stage(host_files, commit_edid)
        fg_source = "milestone-direct"
        fg_evidence = fg_stage[1] if fg_stage else None
        if fg_stage is None:
            fg_stage = find_commitment_start_stage(host_files)
            fg_source = "milestone-StartCommitmentQuest"
            fg_evidence = fg_stage[1] if fg_stage else None
        follow_up_gate: dict | None = None
        if fg_stage is not None:
            follow_up_gate = {
                "hostEdid": host_edid_real,
                "hostLocal": int(host["local"]),
                "hostMaster": host.get("master", "Starfield.esm"),
                "hostStage": int(fg_stage[0]),
                "source": fg_source,
                "evidence": fg_evidence,
            }
        else:
            # 兜底：场景 fragment 启动（莎拉·摩根）⇒ 用「个人任务完成」当边
            fin = find_personal_finish_stage(src, int(q01["local"]))
            if fin is None:
                problems.append(f"{key}：{commit_edid} 找不到任何启动边"
                                f"（宿主 stage 上没有 StartCommitmentQuest，"
                                f"个人任务里也没有 FinishedPersonalQuest）")
            else:
                f_path, f_stage, f_ev = fin
                follow_up_gate = {
                    "hostEdid": q01["edid"],
                    "hostLocal": int(q01["local"]),
                    "hostMaster": q01.get("master", "Starfield.esm"),
                    "hostStage": int(f_stage),
                    "source": "personalQuestFinished",
                    "evidence": f"{f_ev}（承诺任务由场景 fragment 启动、无宿主 stage ⇒ "
                                f"退一步用「个人任务完成」当必要条件）",
                }

        for r in rows:
            k = kind_of(r["edid"])
            pin = (k == "personal")
            if k == "commitment":
                ev = (ev_q01 if not fg_evidence else fg_evidence)
                gate = follow_up_gate
            else:
                ev = find_direct_call(host_files, r["edid"]) or ev_q01
                gate = None
                if k == "other":
                    print(f"  !! {r['edid']}：既不是个人任务也不是承诺任务 ——"
                          f"按「后续」处理（不固定显示、不加启动边），请人工核实")
            group["quests"].append({
                "edid": r["edid"],
                # formid = 文件内原始 FormID（gen_quest_table.py 按它匹配表行）；
                # local = 记录号（运行期 = (加载序号 << 24) | local）。
                "formid": int(r["formid"]),
                "local": int(r["local"]),
                "master": r.get("master", "Starfield.esm"),
                "kind": k,
                "pin": pin,
                "evidence": ev,
                "followUpGate": gate,
            })
        out.append(group)

    # 全局好感度机制（1/2/3 级全局 + 两个启动函数）—— 证明「好感度里程碑」确实存在
    src = Path(a.src)
    if src.is_dir():
        affinity_file = src / "COM_CompanionQuestScript.psc"
        if not affinity_file.exists():
            problems.append("COM_CompanionQuestScript.psc 不存在（好感度机制证据缺失）")
        else:
            txt = affinity_file.read_text(encoding="utf-8", errors="replace")
            for needle in ("StartPersonalQuest", "StartCommitmentQuest",
                           "COM_AffinityLevel_1_Friendship",
                           "COM_AffinityLevel_3_Commitment"):
                if needle not in txt:
                    problems.append(f"COM_CompanionQuestScript.psc 里缺 `{needle}`")

    if problems:
        print("核验失败（不写产物）：")
        for p in problems:
            print("  !! " + p)
        return 1

    Path(a.out).write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"wrote {a.out}")
    n_q = sum(len(g["quests"]) for g in out)
    n_pin = sum(1 for g in out for q in g["quests"] if q["pin"])
    print(f"同伴好感度任务：{len(out)} 位同伴 / {n_q} 条任务（入口 {n_pin} 条固定显示 + "
          f"后续 {n_q - n_pin} 条走链式门槛；全部经官方 Papyrus 源码核验）")
    for g in out:
        print(f"  {g['key']:<12} {g['nameZh']} / {g['nameEn']}（宿主 {g['host']}）：")
        for q in g["quests"]:
            tag = "入口·固定显示" if q["pin"] else "后续·链式门槛"
            print(f"      {q['edid']:<40} 0x{q['local']:06X} [{tag}]")
            if q.get("followUpGate"):
                fg = q["followUpGate"]
                print(f"          启动边：{fg['hostEdid']}@{fg['hostStage']}（{fg['source']}）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
