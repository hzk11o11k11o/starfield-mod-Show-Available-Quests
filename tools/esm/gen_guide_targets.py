#!/usr/bin/env python3
"""gen_guide_targets.py - 给每条「可接任务」找一个**引导目标**（世界里的一个 REFR）。

需求背景（第 10 轮）：AGENTS.md 里的「可以选中跟踪，能调用游戏的任务引导系统正常
引导到接取任务的地点（任务目标蓝点，扫描仪任务路径线）」。

引擎只会给「正在运行 + 目标已显示 + 目标是某个引用」的任务画标记；未接取的任务
引擎不管，所以本 MOD 用**代理任务**（ESM 里的 SAQ_MainQuest，带一个可强制填充的
Reference Alias + 一个目标指向该别名的 Objective）把玩家导向下面选出来的引用。

## 引导目标怎么选（按优先级）

| 优先级 | 来源 | 说明 |
| --- | --- | --- |
| 1 | **ALUA「Unique Actor」别名 → NPC 的放置引用（ACHR）** | 任务发布者常常就是「去哪里接」的答案；标记会跟着人走 |
| 2 | **ALFR「Forced Reference」别名 → 直接是 REFR** | 任务自己的落脚点（XMarker/EnableRef 之类） |
| 3 | QUST `LNAM` / ALFL「Specific Location」→ LCTN `MNAM` | 任务地点的**地图标记引用**（只有少部分地点有） |

排除项：落在「别名暂存格」（EDID 里有 AliasCell / DO NOT DELETE / Holding 等）里的
引用一律不用 —— 那种格子玩家进不去，标记会指向空气。

## ★ 多 master（第 17 轮，DLC 支持）

* 别名数据**改成直接读 ESM**（原来读 xEdit 的树状导出 `ref/xedit/quests_typed.txt`）：
  DLC 的导出要另外跑 xEdit（每个 ESM 几分钟），而 QUST 的别名子记录
  （`ALST/ALID/ALUA/ALFR/ALFL`）本来就在记录里，直接解析又快又不用等。
* 一条 DLC 任务引用的 NPC / 地点**可能属于基础游戏**（Starfield.esm），反之亦然；
  所以每个 master 都要扫一遍世界数据，并且每条引用都记下**它属于哪个插件**
  （由 FormID 前缀决定：前缀 < master 数 ⇒ 前缀指向的那份 master；== 自己 ⇒ 自己）。
* 输出里的 `refr` 是**记录号（local）**，配 `refrMaster` 一起用；
  DLL 运行期再按加载顺序拼出真正的 FormID（见 plugin/src/SAQ.cpp）。

## ★ 第 45 轮：候选池（多候选链）

每条任务输出**整个候选池**（顶层字段 = 第一候选，`cands` = 完整候选列表，含第一候选）：
运行时 DLL 先去写第一候选；脚本报「状态 2 = 引用取不到」（非常驻引用在 cell 没加载时
取不到）就**自动换下一个候选**（见 SAQ.cpp），一轮轮试到某个候选可用为止 —— 于是
「一次取不到」不再等于「这条任务不能导航」。

候选排序见 `cand_grade()` / `quality_key()`（「目标质量」第一：有名字的 NPC >
可读名落脚点 > 通用名 NPC > 内部名落脚点；同级内常驻优先）；同一条任务内
按 (refrMaster, refr) 去重、截断到 `MAX_CANDS`。

输出：
  ref/guide_targets.json   {任务的原始 FormID: {kind, refr, refrMaster, refrSmall,
                                              persistent, nameEn, nameZh, whereEn, whereZh, src,
                                              cands: [ {...}, ... ]}}
  （SAQ_QuestTable.h 的 guide* 字段由 gen_quest_table.py 读这个 JSON 生成）

用法：
    python tools/esm/gen_guide_targets.py                 # 全部 master（约 3-6 分钟）
    python tools/esm/gen_guide_targets.py --no-world      # 跳过世界数据（只出 ALFR，秒级）
    python tools/esm/gen_guide_targets.py --show 0x010158E0   # 打印单条任务的候选明细
"""
from __future__ import annotations

import argparse
import json
import mmap
import re
import struct
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from esm_probe import iter_records_with_context, subrecords, ascii_z  # noqa: E402
from quest_dump import read_tes4  # noqa: E402
from strings_probe import load_strings  # noqa: E402

DEFAULT_DATA = r"D:\SteamLibrary\steamapps\common\Starfield\Data"

# 「别名暂存格」特征（玩家到不了，别把标记指过去）
BAD_CELL_RE = re.compile(r"(aliascell|alias cell|do\s*not\s*delete|holdingcell|holding cell|_hold\b)", re.I)
# 通用/杂兵名（做发布者时优先级降低）
GENERIC_NAME_RE = re.compile(r"(guard|soldier|settler|citizen|worker|technician|scientist|merchant|vendor|"
                             r"security|pirate|spacer|crew|colonist|miner|civilian)", re.I)

# ★ 第 45 轮：引擎内部命名（EDID 泄漏到展示名里）——「质量分级」的判据之一。
#   实测反例：`FFNeonZ08_HeadlockEnableMarker001`（把玩家引到一个内部开关标记上）、
#   `RI_MasakoOfficeQSRef` / `Xmarker_HeadTrackRef` 之类 —— 玩家在日志/提示里看到这种名字
#   没有意义；如果同一条任务还有别的候选（真正的入口 / 有名字的 NPC），应当优先。
NAME_INTERNAL_RE = re.compile(
    r"(?:xmarker|mapmarker|enablemarker|enableref|sandboxmarker|startmarker|startqsref|qsref"
    r"|markerref|headtrack|puzzlemarker|holding|_ref\b|refref\b|ref$)",
    re.I)

# ★ 第 45 轮：候选池（多候选链）。
#   排序以「目标质量」优先（见 cand_grade / quality_key），运行时 DLL 还会在
#   「脚本报状态 2（取不到）」时自动换下一个候选（见 SAQ.cpp）——两者配合。
MAX_CANDS = 6  # 每条任务最多保留几个候选（候选链的边际价值衰减很快）


def name_quality(name: str) -> int:
    """0 = 有意义的展示名；1 = 引擎内部命名（EDID 泄漏）；2 = 空名。"""
    n = (name or "").strip()
    if not n:
        return 2
    return 1 if NAME_INTERNAL_RE.search(n) else 0


def cand_grade(c: dict) -> int:
    """候选的「质量等级」（越小越优）——★ 第 45 轮质量分级的核心。

    依据（按玩家实测反馈定）：
      1 = **有名字的 NPC**（actor、非通用名）—— 「去哪里接」语义最强的答案。
          实测反例：把「平衡账目」引到 `FFNeonZ09_EnableRef`（内部启用标记），
          而真正的发布者「黄（Huong Le）」就在霓虹城里 —— 旧的「常驻第一」排序
          把有名字的 NPC 压住了（31 条任务都是这个形态）。
      2 = 有可读名字的 ref 落脚点（如 `Trade Tower: Astral Lounge`）—— 位置明确。
      3 = 通用名 NPC（Guard / Worker…）—— 名字弱，但位置通常也对。
      4 = 内部命名 / 空名的 ref（`*EnableRef` / `*QSRef` / XMarker / 空）——
          玩家实测抱怨的那一类（`FFNeonZ08_HeadlockEnableMarker001`）。
      5 = 其它（地点地图标记等，目前没有）。
    """
    named = c.get("nameq", 0) == 0
    kind = c.get("kind")
    if kind == "actor":
        return 1 if c.get("generic", 0) == 0 else 3
    if kind == "ref":
        return 2 if named else 4
    return 5


def quality_key(c: dict):
    """候选排序键（越小越优）——★ 第 45 轮的「质量分级」。

    ① 质量等级（见 cand_grade）——「引到正确的接取点」是首要目标；
    ② persistent —— 同等级内常驻优先（脚本**任何时候都取得到**，更稳）；
    ③ order —— 别名里的出现顺序（稳定排序用）。

    ★ 为什么 persistent 不再是第一键：实测反馈里最糟的形态是「有名字的 NPC 发布者
      被内部标记压住」；而「取不到」不再是死路 —— 运行时 DLL 会在脚本报状态 2
      时自动换下一个候选（见 SAQ.cpp），代价只是同一个引导晚约 1 秒生效。
    """
    return (
        cand_grade(c),
        0 if c.get("persistent") else 1,
        c.get("order", 0),
    )


def u32(b: bytes) -> int:
    return struct.unpack_from("<I", b, 0)[0]


def load_meta(path: Path) -> dict:
    """读 TES4 头（master 列表 / 自己记录的前缀 / 是否 light）—— 只读头，不加载整个文件。"""
    with path.open("rb") as f:
        head = f.read(24)
        size = u32(head[4:8])
        body = f.read(size)
    meta = read_tes4(head + body)
    meta["file"] = path.name
    meta["path"] = str(path)
    return meta


def owner_of(formid: int, meta: dict) -> str:
    """记录属于哪个插件：FormID 前缀 = 该插件自己的 master 列表下标；== self_index 就是它自己。

    ★★ 第 110 轮：medium（0xFD）/ light（0xFE）文件里，**自己空间**的引用直接落在
    那两段（不是 master 下标）—— 先按档位短路，否则 0xFD 会被当成越界前缀
    （所有 SFBGS003 的引用都会失去 owner ⇒ 候选全部作废）。
    对这两类文件里的 override 引用（前缀 0x00 = starfield.esm）走原来的逻辑。
    """
    prefix = (formid >> 24) & 0xFF
    if prefix == 0xFD and meta.get("medium"):
        return meta["file"]
    if prefix == 0xFE and meta.get("small"):
        return meta["file"]
    masters = meta["masters"]
    if prefix < len(masters):
        return masters[prefix]
    if prefix == meta["self_index"]:
        return meta["file"]
    return ""


# ---------------------------------------------------------------------------
#  第一遍：任务的别名（ALUA / ALFR / ALFL）与地点（LCTN）
# ---------------------------------------------------------------------------
def scan_quests(mm: mmap.mmap, meta: dict, want: set[int]):
    """QUST 别名 + LCTN。返回 (aliases, lctns)。

    aliases[in-file formid] = {actors: [(别名名, NPC FormID)], refs: [(别名名, REFR FormID)],
                               locs: [LCTN FormID]}
    """
    aliases: dict[int, dict] = {}
    lctns: dict[int, dict] = {}
    for sig, formid, _flags, _cell, _world, payload in iter_records_with_context(mm):
        if sig == b"QUST":
            if formid not in want:
                continue
            info: dict = {"actors": [], "refs": [], "locs": [], "lctn": 0}
            alias_name = ""
            for s, sp in subrecords(payload):
                if s == b"LNAM" and len(sp) >= 4:
                    info["lctn"] = u32(sp)
                elif s == b"ALST" and len(sp) >= 4:
                    alias_name = ""          # 新别名块开始
                elif s == b"ALID":
                    alias_name = ascii_z(sp)
                elif s == b"ALUA" and len(sp) >= 4:
                    info["actors"].append((alias_name, u32(sp)))
                elif s == b"ALFR" and len(sp) >= 4:
                    info["refs"].append((alias_name, u32(sp)))
                elif s == b"ALFL" and len(sp) >= 4:
                    info["locs"].append(u32(sp))
            aliases[formid] = info
        elif sig == b"LCTN":
            info = {"edid": "", "full": 0, "marker": 0, "parent": 0, "owner": owner_of(formid, meta)}
            for s, sp in subrecords(payload):
                if s == b"EDID":
                    info["edid"] = ascii_z(sp)
                elif s == b"FULL" and len(sp) >= 4:
                    info["full"] = u32(sp)
                elif s == b"MNAM" and len(sp) >= 4:
                    info["marker"] = u32(sp)
                elif s == b"PNAM" and len(sp) >= 4:
                    info["parent"] = u32(sp)
            lctns[formid] = info
    return aliases, lctns


# ---------------------------------------------------------------------------
#  第二遍：世界数据（CELL/WRLD 名字、NPC 名字、放置引用、引用的常驻标志）
# ---------------------------------------------------------------------------
def scan_world(mm: mmap.mmap, meta: dict, wanted_npc: set[int], wanted_refr: set[int], acc: dict):
    """把世界数据累积进 acc（多 master 共用；后扫的覆盖同 FormID 的条目）。

    ★ 第 47 轮：REFR/ACHR 的 info 新增 `pos`（DATA 子记录前 12 字节 = 世界坐标）——
      「同 cell 常驻兜底」要用它算「哪个常驻引用离目标最近」。
    """
    for sig, formid, flags, cell, world, payload in iter_records_with_context(mm):
        if sig == b"NPC_":
            if formid in wanted_npc:
                for s, sp in subrecords(payload):
                    if s == b"FULL" and len(sp) >= 4:
                        acc["npc_names"][formid] = u32(sp)
                        break
        elif sig == b"CELL":
            # ★★ 第 110 轮：**非空才覆盖** —— override 记录（如 SFBGS003 的 5.5 万条
            #   CELL）可能不带 EDID/FULL；无条件覆盖会把基础游戏 cell 的名字清空
            #   （实测：13 条任务的「目标所在地」从城市名变成空串）。
            cur = acc["cells"].setdefault(formid, {"edid": "", "full": 0})
            for s, sp in subrecords(payload):
                if s == b"EDID":
                    if sp:
                        cur["edid"] = ascii_z(sp)
                elif s == b"FULL" and len(sp) >= 4:
                    cur["full"] = u32(sp)
        elif sig == b"WRLD":
            for s, sp in subrecords(payload):
                if s == b"FULL" and len(sp) >= 4:
                    acc["world_names"][formid] = u32(sp)
                    break
                if s == b"EDID":
                    break
        elif sig in (b"ACHR", b"REFR"):
            base = 0
            edid = ""
            pos = None
            for s, sp in subrecords(payload):
                if s == b"NAME" and len(sp) >= 4:
                    base = u32(sp)
                elif s == b"EDID":
                    edid = ascii_z(sp)
                elif s == b"DATA" and pos is None and len(sp) >= 12:
                    pos = tuple(struct.unpack_from("<3f", sp, 0))
            if base not in wanted_npc and formid not in wanted_refr:
                continue
            info = {
                "refr": formid,
                "cell": cell,
                "world": world,
                "persistent": bool(flags & 0x400),
                "edid": edid,
                "owner": owner_of(formid, meta),
                "pos": pos,
                "flags": flags,
            }
            if base in wanted_npc:
                acc["placements"].setdefault(base, []).append(info)
            if formid in wanted_refr:
                acc["refr_info"][formid] = info


# ---------------------------------------------------------------------------
#  ★★ 第 47 轮（大项 C）：同 cell 常驻兜底
# ---------------------------------------------------------------------------
def collect_cell_persistents(mm: mmap.mmap, cells: set[int]) -> list[tuple[int, int, tuple, int, str, int]]:
    """第三遍用：收集给定 cell 里的**常驻** REFR/ACHR。

    返回 [(formid, cell, pos, base, edid, flags)] —— 这是「同 cell 常驻兜底」的原料
    （引擎对常驻引用始终保留加载，任何位置 `LookupByID` 都取得到；见 docs/05）。
    ★ 距离只在**同一 cell 内**比较（不同 cell 的坐标不可比）。
    """
    out: list[tuple[int, int, tuple, int, str, int]] = []
    for sig, formid, flags, cell, world, payload in iter_records_with_context(mm):
        if sig not in (b"ACHR", b"REFR") or cell not in cells or not (flags & 0x400):
            continue
        pos = None
        base = 0
        edid = ""
        for s, sp in subrecords(payload):
            if s == b"DATA" and pos is None and len(sp) >= 12:
                pos = tuple(struct.unpack_from("<3f", sp, 0))
            elif s == b"NAME" and len(sp) >= 4:
                base = u32(sp)
            elif s == b"EDID":
                edid = ascii_z(sp)
        if pos:
            out.append((formid, cell, pos, base, edid, flags))
    return out


# ---------------------------------------------------------------------------
#  ★★ 第 114 轮（引导质量 2.0）：兜底第二档 —— 同 worldspace 的「world 级常驻引用」
# ---------------------------------------------------------------------------
def collect_world_persistents(mm: mmap.mmap, worlds: set[int]) -> dict[int, list]:
    """收集给定 worldspace 的**world 级常驻引用**（第 80 轮外景 NPC 条目的同一套口径）。

    为什么需要（第 114 轮实测）：Starfield 的**外景城市 cell 里官方不放 per-cell 常驻引用**
    （20 条「无兜底」任务的 23 个目标 cell 全 0 条：新亚特兰蒂斯商业区 / 加加林城 /
    天堂乐园 / 红英里 / 阿基拉贫民窟 …… 每个 cell 几千条引用，常驻 0）。它们的常驻引用
    全在 **world 层级**：组链 `Top 'WRLD'(0) > WRLD 组(1, label=world FormID) > … >
    CellPersistent(8)`（第 80 轮首次发现：外景探员条目就是这么兜底的，离目标 3.1 m）。
    ⇒ 对「同 cell 找不到兜底」的任务，在它候选的 worldspace 里找最近的 world 级常驻引用
    （实测 19/20 条命中，距离 0.2~8.4 m —— 蓝点仍落在正确位置）。

    返回 {world: [(formid, pos, base, edid)]}。
    """
    out: dict[int, list] = {}

    def rec(p: int, end: int, types: list, world_label: int) -> None:
        while p + 24 <= end:
            if mm[p:p + 4] == b"GRUP":
                size = u32(mm[p + 4:p + 8])
                if size < 24:
                    return
                gtype = struct.unpack_from("<i", mm, p + 12)[0]
                label = struct.unpack_from("<i", mm, p + 8)[0] & 0xFFFFFF
                # WRLD 组（type 1）的 label = worldspace 的 FormID
                wl = label if (gtype == 1 and world_label == 0) else world_label
                rec(p + 24, p + size, types + [gtype], wl)
                p += size
                continue
            sig = bytes(mm[p:p + 4])
            size = u32(mm[p + 4:p + 8])
            flags = u32(mm[p + 8:p + 12])
            if (sig in (b"ACHR", b"REFR") and (flags & 0x400) and types
                    and types[0] == 0 and types[-1] == 8 and world_label in worlds):
                payload = bytes(mm[p + 24:p + 24 + size])
                pos = None
                base = 0
                edid = ""
                for s, sp in subrecords(payload):
                    if s == b"DATA" and pos is None and len(sp) >= 12:
                        pos = tuple(struct.unpack_from("<3f", sp, 0))
                    elif s == b"NAME" and len(sp) >= 4:
                        base = u32(sp)
                    elif s == b"EDID":
                        edid = ascii_z(sp)
                if pos:
                    formid = u32(mm[p + 12:p + 16]) & 0xFFFFFF
                    out.setdefault(world_label, []).append((formid, pos, base, edid))
            p += 24 + size

    head = u32(mm[4:8])
    p = 24 + head
    while p + 24 <= len(mm):
        if bytes(mm[p:p + 4]) != b"GRUP":
            break
        gsize = u32(mm[p + 4:p + 8])
        rec(p + 24, p + gsize, [0], 0)
        p += gsize
    return out


def _dist3(a, b) -> float:
    return sum((x - y) ** 2 for x, y in zip(a, b)) ** 0.5


# ★★ 第 114 轮（引导质量 2.0）：兜底的「相关性」关键词 —— 任务 EDID 拆词（去通用词）。
#   用途：「兜底候选分层」——同池里若存在与任务**名字相关**的常驻引用（如 UCR01 的
#   `UC_TualaTravelMaker`），在距离不显著变差的前提下优先用它（比「最近的任意引用」更贴切）。
_STOP_WORDS = {
    "quest", "city", "location", "marker", "enable", "enablemark",
    "interior", "exterior", "holding", "alias", "cell", "refr", "refref",
    "always", "start", "end", "test", "temp",
}
_REL_MAX_EXTRA_M = 30.0   # 相关引用允许多走的距离（米）——超过就不为「相关性」牺牲精度


def task_keywords(edid: str) -> set[str]:
    """任务 EDID → 关键词集合（长度 ≥ 5 的字母数字词，去掉通用词）。"""
    toks = re.split(r"[^0-9a-zA-Z]+", (edid or "").lower())
    return {t for t in toks if len(t) >= 5 and t not in _STOP_WORDS}


def _ref_related(edid: str, kws: set[str]) -> int:
    """0 = 引用名与任务相关（含任一关键词）；1 = 无关 / 无名。"""
    if not edid or not kws:
        return 1
    low = edid.lower()
    return 0 if any(k in low for k in kws) else 1


def _pick_nearest(pool: dict[int, list], targets: list[tuple[int, tuple]],
                  kws: set[str]) -> tuple | None:
    """在 pool（按 cell/world 分池）里对 targets 的每个位置找候选：

    排序 = 「距离优先，相关性只在『距离差 ≤ 30 米』时作为 tie-break」——
    ★ 为什么不是「相关性第一」：最近的多在 1~3 米（蓝点准确），为名字匹配走到几十米外
      反而会让蓝点偏离接取点；30 米阈值保证「不显著变差」。
    返回 (dist, related, formid, pos, base, edid) 或 None。
    """
    cands: list[tuple[float, int, int, tuple, int, str]] = []
    for key, tp in targets:
        for formid, pos, base, edid in pool.get(key, []):
            cands.append((_dist3(pos, tp), _ref_related(edid, kws), formid, pos, base, edid))
    if not cands:
        return None
    nearest = min(cands, key=lambda x: x[0])
    rel = [c for c in cands if c[1] == 0]
    if rel:
        best_rel = min(rel, key=lambda x: x[0])
        if best_rel[0] <= nearest[0] + _REL_MAX_EXTRA_M:
            return best_rel
    return nearest


def find_fallbacks(pre_cands: dict[int, list[dict]], wanted_by_master: dict[str, set[int]],
                   meta_by_lower: dict[str, dict], esm_extra: list[str],
                   edid_by_task: dict[int, str] | None = None) -> dict[int, dict]:
    """为「全部候选都非常驻」的任务找**常驻兜底**（★ 第 47 轮；★★ 第 114 轮扩第二档）。

    起因（玩家实测「营救机器人」）：这类任务远处点引导时全部候选 `LookupByID`
    取不到 ⇒「引导不生效」，而世界里的标记仍是上一条生效引导的残留 —— 玩家观感
    =「导航点被锁定在某个地方不动、导航没用」。兜底 = 一个**常驻**引用（引擎始终
    能取到）⇒ 远处点引导立刻可用（蓝点落在目标附近），靠近后由运行时「候选复算」
    自动升级为首选（精确）。

    两档（★★ 第 114 轮新增第二档）：
      ① **同 cell 常驻引用**（第 47 轮）—— 同 cell 内离任一候选目标最近的常驻 REFR/ACHR；
      ② **同 worldspace 的 world 级常驻引用**（第 114 轮）—— ①找不到时用。
         实测依据：外景城市 cell 里官方不放 per-cell 常驻引用（20 条无兜底任务的 23 个
         目标 cell 全 0 条），常驻引用都在 `Top 'WRLD' > WRLD 组 > … > CellPersistent`；
         19/20 条任务命中，距离 0.2~8.4 m（第 80 轮外景探员条目的同一套口径）。

    分池理由：距离只在「同一 cell / 同一 worldspace」内可比（跨 worldspace 的坐标不可比）。
    返回 {任务 FormID: 兜底候选 dict}（含 kind="cell"/"world"，供 src 文案区分）。
    """
    # 1) 需要兜底的任务 → 候选目标（按 cell 与 world 两组）
    need_cell: dict[int, list[tuple[int, tuple]]] = {}
    need_world: dict[int, list[tuple[int, tuple]]] = {}
    cells: set[int] = set()
    worlds: set[int] = set()
    for fid, cands in pre_cands.items():
        if not cands or any(c.get("persistent") for c in cands):
            continue
        tc = [(c["cell"], c["pos"]) for c in cands if c.get("cell") and c.get("pos")]
        tw = [(c.get("world") or 0, c["pos"]) for c in cands if c.get("pos") and c.get("world")]
        if tc:
            need_cell[fid] = tc
            cells.update(c for c, _ in tc)
        if tw:
            need_world[fid] = tw
            worlds.update(w for w, _ in tw)
    if not need_cell and not need_world:
        return {}
    print(f"  需要常驻兜底的任务 {len(need_cell)} 条（{len(cells)} 个 cell / {len(worlds)} 个 worldspace）"
          "，扫描中...")

    # 2) 扫各 master：cell 池 + world 级池
    pool_cell: dict[int, list[tuple[int, tuple, int, str]]] = {c: [] for c in cells}
    pool_world: dict[int, list[tuple[int, tuple, int, str]]] = {w: [] for w in worlds}
    seen_files: set[str] = set()
    for m in list(dict.fromkeys(list(wanted_by_master) + list(esm_extra))):
        meta = meta_by_lower.get(m.lower())
        if not meta or meta["path"] in seen_files:
            continue
        seen_files.add(meta["path"])
        with Path(meta["path"]).open("rb") as f:
            mm = mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ)
            try:
                found = collect_cell_persistents(mm, cells) if cells else []
                wfound = collect_world_persistents(mm, worlds) if worlds else {}
            finally:
                mm.close()
        for formid, cell, pos, base, edid, flags in found:
            pool_cell.setdefault(cell, []).append((formid, pos, base, edid))
        for w, lst in wfound.items():
            pool_world.setdefault(w, []).extend(lst)
    print(f"  常驻引用池：cell 级 {sum(len(v) for v in pool_cell.values())} 条"
          f"（{len(cells)} 个 cell）；world 级 {sum(len(v) for v in pool_world.values())} 条"
          f"（{len(worlds)} 个 worldspace）")

    # 3) 每条任务：先同 cell，再 world 级
    out: dict[int, dict] = {}
    n_cell = n_world = n_rel = 0
    for fid in list(need_cell) + [f for f in need_world if f not in need_cell]:
        kws = task_keywords((edid_by_task or {}).get(fid, ""))
        best = _pick_nearest(pool_cell, need_cell.get(fid, []), kws)
        kind = "cell"
        if best is None:
            best = _pick_nearest(pool_world, need_world.get(fid, []), kws)
            kind = "world"
        if best is None:
            continue
        d, rel, formid, pos, base, edid = best
        out[fid] = {"refr": formid, "dist": d, "base": base, "edid": edid, "pos": pos,
                    "kind": kind, "related": rel}
        if kind == "cell":
            n_cell += 1
        else:
            n_world += 1
        if rel == 0:
            n_rel += 1
    if out:
        print(f"  兜底：同 cell {n_cell} 条 + world 级 {n_world} 条"
              f"（其中 {n_rel} 条命中了「任务相关名」优先规则）")
    return out


def collect_candidates(fid: int, info: dict, acc: dict, quest_lctn: dict, meta: dict,
                       meta_by_lower: dict, named, fallback: dict | None = None) -> list[dict]:
    """把一条任务的别名候选整理成候选列表（与第 10 轮的规则一致，只是数据来源换了）。

    ★ 第 47 轮：`fallback` = find_fallbacks() 为该任务找到的「同 cell 常驻兜底」
    （没有则为 None）—— 追加在候选列表尾部（质量最低但**永远可得**）。
    每个候选另带内部的 `pos` / `cell`（供第三遍扫描与兜底计算用；输出时会剥掉）。
    """
    cands: list[dict] = []

    def owner_fields(refr_id: int, fallback_meta: dict) -> tuple[str, int, bool, bool]:
        """→ (master 文件名, 记录号, isSmall, isMedium)。

        ★★ 第 110 轮：候选引用的位宽按所属插件的档位取 ——
        full 24 位 / medium 16 位（SFBGS003 的引用 = 0xFDxxxxxx）/ light 12 位。
        """
        owner = owner_of(refr_id, fallback_meta) or fallback_meta["file"]
        om = meta_by_lower.get(owner.lower(), fallback_meta)
        if om.get("medium"):
            return om["file"], refr_id & 0xFFFF, False, True
        if om.get("small"):
            return om["file"], refr_id & 0xFFF, True, False
        return om["file"], refr_id & 0xFFFFFF, False, False

    def bad_cell(cell_id: int) -> bool:
        return bool(BAD_CELL_RE.search(acc["cells"].get(cell_id, {}).get("edid", "")))

    def cell_desc(cell_id: int, world_id: int) -> tuple[str, str]:
        if world_id and world_id in acc["world_names"]:
            return named(acc["world_names"][world_id])
        if cell_id and cell_id in acc["cells"] and acc["cells"][cell_id]["full"]:
            return named(acc["cells"][cell_id]["full"])
        return "", ""

    # ① ALFR「Forced Reference」：任务自己写在记录里的落脚引用
    for order, (alias, refr) in enumerate(info.get("refs", [])):
        ri = acc["refr_info"].get(refr, {})
        if bad_cell(ri.get("cell", 0)) or BAD_CELL_RE.search(ri.get("edid", "")):
            continue  # 落在别名暂存格里：玩家到不了
        where_en, where_zh = cell_desc(ri.get("cell", 0), ri.get("world", 0))
        name = ri.get("edid", "") or where_en
        if name.lower() in ("", "xmarker", "xmarkerheading", "mapmarker"):
            name = where_en or name
        owner, local, small, medium = owner_fields(refr, meta)
        cands.append({
            "kind": "ref", "refr": local, "refrMaster": owner, "refrSmall": small,
            "refrMedium": medium,
            "persistent": ri.get("persistent", False),
            "nameEn": name, "nameZh": name,
            "whereEn": where_en, "whereZh": where_zh,
            "src": f"ALFR {alias}", "tier": 1, "generic": 0, "order": order,
            "pos": ri.get("pos"), "cell": ri.get("cell", 0), "world": ri.get("world", 0),
        })

    # ② ALUA「Unique Actor」：任务发布者（最常见，也最贴「去哪里接」）
    for order, (alias, npc) in enumerate(info.get("actors", [])):
        if npc in (0, 0x07, 0x14):  # Player / PlayerRef
            continue
        name_en, name_zh = named(acc["npc_names"].get(npc, 0))
        if not name_en:
            continue
        generic = 1 if GENERIC_NAME_RE.search(name_en) else 0
        for pl in acc["placements"].get(npc, []):
            if bad_cell(pl["cell"]):
                continue
            where_en, where_zh = cell_desc(pl["cell"], pl["world"])
            owner, local, small, medium = owner_fields(pl["refr"], meta)
            cands.append({
                "kind": "actor", "refr": local, "refrMaster": owner, "refrSmall": small,
                "refrMedium": medium,
                "persistent": pl["persistent"],
                "nameEn": name_en, "nameZh": name_zh,
                "whereEn": where_en, "whereZh": where_zh,
                "src": f"ALUA {alias}", "tier": 0, "generic": generic, "order": order,
                "pos": pl.get("pos"), "cell": pl.get("cell", 0), "world": pl.get("world", 0),
            })

    # ③ 任务地点的地图标记引用（只有少部分地点有，但指向最准）
    lctn = quest_lctn.get(fid, 0)
    lsrc = "LNAM"
    if not lctn and info.get("locs"):
        lctn = info["locs"][0]
        lsrc = "ALFL"
    if lctn:
        marker = acc["lctns"].get(lctn, {}).get("marker", 0)
        if marker:
            def name_of(lid: int, depth: int = 0) -> tuple[str, str]:
                li = acc["lctns"].get(lid)
                if not li:
                    return "", ""
                if li["full"]:
                    return named(li["full"])
                if li["parent"] and depth < 3:
                    return name_of(li["parent"], depth + 1)
                return "", ""
            n_en, n_zh = name_of(lctn)
            owner, local, small, medium = owner_fields(marker, meta)
            mi = acc["refr_info"].get(marker, {})
            cands.append({
                "kind": "loc", "refr": local, "refrMaster": owner, "refrSmall": small,
                "refrMedium": medium,
                "persistent": mi.get("persistent", False),
                "nameEn": n_en, "nameZh": n_zh, "whereEn": n_en, "whereZh": n_zh,
                "src": lsrc, "tier": 2, "generic": 0, "order": 0,
                "pos": mi.get("pos"), "cell": mi.get("cell", 0), "world": mi.get("world", 0),
            })
    # ★ 第 45 轮：统一补「名字质量」（质量分级的输入；见 quality_key）。
    for c in cands:
        c["nameq"] = name_quality(c.get("nameEn", ""))

    # ★★ 第 47 轮：同 cell 常驻兜底（候选池最后一位）。
    #   为什么需要它：这条任务的候选**全是非常驻引用**时，玩家在目标 cell 之外
    #   点引导 ⇒ `LookupByID` 全部取不到 ⇒「引导不生效」，世界里的标记仍是上一条
    #   生效引导的残留 —— 玩家观感 =「导航点被锁定在某处不动、导航没用」（实测：
    #   「营救机器人」）。兜底是一个**常驻**引用（引擎始终保留加载）⇒ 远处点引导
    #   立刻可用（蓝点落在目标附近），靠近后由运行时「候选复算」自动升级为首选。
    #   名字强制内部名质量（nameq=1 ⇒ grade 4）：它只是「就近落脚点」，不该在
    #   排序上压过任何真正的候选；但同 grade 内常驻优先 ⇒ 仍排在「非常驻内部名」之前。
    if fallback:
        owner, local, small, medium = owner_fields(fallback["refr"], meta)
        fname = fallback.get("edid") or f"Ref_{local:06X}"
        # ★★ 第 114 轮：两档兜底的 src 文案区分（日志/文档里一眼看出用了哪一档）
        src = (f"同 cell 常驻兜底（距目标 {fallback['dist']:.1f} 米）"
               if fallback.get("kind", "cell") == "cell"
               else f"world 级常驻兜底（距目标 {fallback['dist']:.1f} 米，外景城市）")
        cands.append({
            "kind": "ref", "refr": local, "refrMaster": owner, "refrSmall": small,
            "refrMedium": medium,
            "persistent": True,
            "nameEn": fname, "nameZh": fname, "nameq": 1,
            "whereEn": "", "whereZh": "",
            "src": src,
            "tier": 3, "generic": 1, "order": 999,
            "pos": fallback.get("pos"), "cell": 0, "world": 0,
        })
    return cands


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default=DEFAULT_DATA)
    ap.add_argument("--esm", action="append", default=[],
                    help="额外/覆盖的 master 路径（可多次；默认按 --data + master 名找）")
    ap.add_argument("--table", default="ref/quest_table_debug.json")
    ap.add_argument("--strings-dir", default="ref/strings/strings")
    ap.add_argument("--out", default="ref/guide_targets.json")
    ap.add_argument("--no-world", action="store_true", help="跳过世界数据遍历（只出 ALFR + 名字）")
    ap.add_argument("--show", default="", help="打印某条任务的候选明细（十六进制原始 FormID）")
    a = ap.parse_args()

    rows = json.loads(Path(a.table).read_text(encoding="utf-8"))
    wanted_by_master: dict[str, set[int]] = {}
    for r in rows:
        fid = r["formid"] if isinstance(r["formid"], int) else int(r["formid"], 16)
        wanted_by_master.setdefault(r.get("master", "Starfield.esm"), set()).add(fid)
    print(f"候选任务 {len(rows)} 条，来自 {len(wanted_by_master)} 个 master："
          + " ".join(f"{m}={len(v)}" for m, v in wanted_by_master.items()))

    meta_by_lower: dict[str, dict] = {}
    for m in list(wanted_by_master):
        path = Path(a.data) / m
        meta = load_meta(path)
        meta_by_lower[m.lower()] = meta
    for p in a.esm:
        meta = load_meta(Path(p))
        meta_by_lower[meta["file"].lower()] = meta

    # ---- 第一遍：别名 + LCTN ----
    aliases: dict[int, dict] = {}
    quest_lctn: dict[int, int] = {}
    acc: dict = {"cells": {}, "world_names": {}, "npc_names": {}, "placements": {}, "refr_info": {},
                 "lctns": {}}
    for m, wanted in wanted_by_master.items():
        meta = meta_by_lower[m.lower()]
        with Path(meta["path"]).open("rb") as f:
            mm = mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ)
            try:
                al, lc = scan_quests(mm, meta, wanted)
            finally:
                mm.close()
        aliases.update(al)
        acc["lctns"].update(lc)  # 地图标记（MNAM）在下面统一收集成 wanted_refr
        for fid, info in al.items():
            if info["lctn"]:
                quest_lctn[fid] = info["lctn"]
        print(f"  {m}: 别名 {len(al)}/{len(wanted)} 条；LCTN {len(lc)} 条")

    wanted_npc = {npc for info in aliases.values() for _al, npc in info["actors"] if npc not in (0, 0x07, 0x14)}
    wanted_refr = {refr for info in aliases.values() for _al, refr in info["refs"]}
    wanted_refr |= {info["marker"] for info in acc["lctns"].values() if info["marker"]}
    print(f"  需要定位的 NPC {len(wanted_npc)} 个；要查标志的引用 {len(wanted_refr)} 个")

    # ---- 第二遍：世界数据 ----
    if not a.no_world:
        for m in wanted_by_master:
            meta = meta_by_lower[m.lower()]
            print(f"  遍历 {m} 的世界数据...")
            with Path(meta["path"]).open("rb") as f:
                mm = mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ)
                try:
                    scan_world(mm, meta, wanted_npc, wanted_refr, acc)
                finally:
                    mm.close()
        print(f"  放置引用 {len(acc['placements'])}/{len(wanted_npc)} 个 NPC；"
              f"引用标志 {len(acc['refr_info'])}/{len(wanted_refr)} 个")

    # ---- 名字表（每个 master 一份）----
    strings: dict[str, tuple[dict, dict]] = {}
    for m in wanted_by_master:
        key = Path(m).stem.lower()
        en_f = Path(a.strings_dir) / f"{key}_en.strings"
        zh_f = Path(a.strings_dir) / f"{key}_zhhans.strings"
        if en_f.exists() and zh_f.exists():
            strings[m] = (load_strings(en_f), load_strings(zh_f))
        else:
            print(f"  !! 缺 {key}_*.strings（{m} 的名字会取不到）")
            strings[m] = ({}, {})

    def make_named(meta: dict):
        en, zh = strings.get(meta["file"], ({}, {}))
        return lambda sid: (en.get(sid, ""), zh.get(sid, "")) if sid else ("", "")

    # ---- ★★ 第 47 轮：第三遍 —— 为「全部候选都非常驻」的任务找「同 cell 常驻兜底」 ----
    #   ★★ 第 114 轮：扩第二档（同 worldspace 的 world 级常驻引用）+ 任务相关名优先。
    #   先预跑一遍候选（不带兜底）判定哪些任务需要兜底（判定与正式生成同一套规则），
    #   再扫各 master 的常驻引用（find_fallbacks 内部做）。
    edid_by_task = {r["formid"] if isinstance(r["formid"], int) else int(r["formid"], 16):
                    (r.get("edid") or "") for r in rows}
    fallbacks: dict[int, dict] = {}
    if not a.no_world:
        pre: dict[int, list[dict]] = {}
        for m, wanted in wanted_by_master.items():
            meta = meta_by_lower[m.lower()]
            named = make_named(meta)
            for fid in wanted:
                info = aliases.get(fid, {"actors": [], "refs": [], "locs": [], "lctn": 0})
                try:
                    pre[fid] = collect_candidates(fid, info, acc, quest_lctn, meta, meta_by_lower, named)
                except Exception:  # noqa: BLE001
                    pre[fid] = []
        fallbacks = find_fallbacks(pre, wanted_by_master, meta_by_lower, a.esm, edid_by_task)
        n_c = sum(1 for v in fallbacks.values() if v.get("kind", "cell") == "cell")
        n_w = len(fallbacks) - n_c
        print(f"  常驻兜底：{len(fallbacks)}/{len(pre)} 条任务找到兜底"
              f"（同 cell {n_c} + world 级 {n_w}）")

    out: dict[str, dict] = {}
    stats = Counter()
    samples: list[str] = []
    cand_hist = Counter()      # 候选数分布（键 = 候选数，6 = ≥6）
    changed: list[str] = []    # 质量分级相对旧排序改变了第一候选的任务（统计用）
    for m, wanted in wanted_by_master.items():
        meta = meta_by_lower[m.lower()]
        named = make_named(meta)
        for fid in wanted:
            info = aliases.get(fid, {"actors": [], "refs": [], "locs": [], "lctn": 0})
            try:
                cands = collect_candidates(fid, info, acc, quest_lctn, meta, meta_by_lower, named,
                                           fallbacks.get(fid))
            except Exception as exc:  # noqa: BLE001
                print(f"  候选生成失败 {m} 0x{fid:08X}: {exc}")
                cands = []
            if not cands:
                stats[f"无目标({m})"] += 1
                continue
            # ★ 第 45 轮：候选池 = 质量排序 + 去重（同一个引用可能从多个别名/来源重复出现）
            #   + 截断（MAX_CANDS —— 候选链的边际价值衰减很快）。
            cands.sort(key=quality_key)
            dedup: list[dict] = []
            seen_refs: set[tuple[str, int]] = set()
            for c in cands:
                key = (c.get("refrMaster", ""), int(c.get("refr") or 0))
                if key in seen_refs:
                    continue
                seen_refs.add(key)
                dedup.append(c)
            cands = dedup
            cand_hist[min(len(cands), 6)] += 1
            # 旧排序（第 10 轮起：常驻 + tier）—— 只为统计「质量分级改了多少条的第一候选」。
            old_first = min(cands, key=lambda c: (0 if c["persistent"] else 1, c["tier"], c["generic"], c["order"]))
            new_first = cands[0]
            if (old_first.get("refr"), old_first.get("refrMaster")) != (new_first.get("refr"), new_first.get("refrMaster")):
                changed.append(
                    f"0x{fid:08X} 新={new_first['refrMaster']}:0x{int(new_first['refr']):06X}"
                    f"({new_first['kind']},nameq={new_first['nameq']},{'常驻' if new_first['persistent'] else '非常驻'},"
                    f"{new_first['nameZh'] or new_first['nameEn']}) 旧=0x{int(old_first['refr']):06X}"
                    f"({old_first['kind']},nameq={old_first['nameq']},{'常驻' if old_first['persistent'] else '非常驻'},"
                    f"{old_first['nameZh'] or old_first['nameEn']})")
            if a.show and fid == int(a.show, 16):
                print(f"\n--- 0x{fid:08X}（{m}）候选 {len(cands)} 条（质量排序）：")
                for i, c in enumerate(cands):
                    print(f"    [{i}] {c}")
            # ★ 第 45 轮：截断时**保证常驻候选不被截掉**（至少保留 2 个）——
            #   常驻引用 = 脚本任何时候都取得到，是「玩家在远处点击」的备胎；
            #   直接取前 MAX_CANDS 个会把排名靠后的常驻候选砍掉（实测：24 条任务
            #   的常驻备胎被截，远处点击就再也回不到可用目标）。
            keep = cands[:MAX_CANDS]
            kept = {(c["refrMaster"], int(c["refr"])) for c in keep}
            n_persist_kept = sum(1 for c in keep if c["persistent"])
            for c in cands[MAX_CANDS:]:
                if n_persist_kept >= 2:
                    break
                if c["persistent"]:
                    key = (c["refrMaster"], int(c["refr"]))
                    if key not in kept:
                        keep.append(c)
                        kept.add(key)
                        n_persist_kept += 1
            cands = keep
            got = {k: v for k, v in cands[0].items()
                   if k not in ("tier", "generic", "order", "nameq", "pos", "cell", "world")}
            entry = dict(got)
            # ★ 第 45 轮：完整候选池（含第一候选）—— gen_quest_table.py 用它生成
            #   kGuideCandidates[]（运行时 DLL 在「脚本报取不到」时按顺序换下一个）。
            # ★ 第 47 轮：候选里带的 `pos`/`cell` 是内部字段（第三遍算兜底用），剥掉；
            # ★★ 第 114 轮：`world` 同属内部字段（world 级兜底用），一并剥掉。
            entry["cands"] = [{k: v for k, v in c.items()
                               if k not in ("tier", "pos", "cell", "world")} for c in cands]
            out[str(fid)] = entry
            srcs = [c.get("src", "") for c in cands if c["persistent"]]
            if any(s.startswith("同 cell 常驻兜底") for s in srcs):
                stats["兜底·同 cell"] += 1
            elif any(s.startswith("world 级常驻兜底") for s in srcs):
                stats["兜底·world 级"] += 1
            stats[got["kind"]] += 1
            stats["常驻" if got["persistent"] else "非常驻"] += 1
            if len(samples) < 12:
                samples.append(
                    f"{m} 0x{fid:08X} [{got['kind']:5s}{'持久' if got['persistent'] else '临时'}] "
                    f"{got['refrMaster']}:0x{got['refr']:06X} 目标={got['nameZh'] or got['nameEn']} "
                    f"位置={got['whereZh'] or got['whereEn']} ({got['src']}) 候选数={len(cands)}")

    Path(a.out).write_text(json.dumps(out, ensure_ascii=False, indent=1, sort_keys=True), encoding="utf-8")
    total = len(rows)
    have = len(out)
    print(f"\n有引导目标 {have}/{total}（{have * 100 // max(total, 1)}%）")
    for k, v in stats.most_common():
        print(f"  {k}: {v}")
    print(f"候选池分布（候选数 → 任务数）：{dict(sorted(cand_hist.items()))}")
    if changed:
        print(f"质量分级改变了 {len(changed)} 条任务的第一候选（前 15）：")
        for s in changed[:15]:
            print("  " + s)
    print("样本：")
    for s in samples:
        print("  " + s)
    print(f"wrote {a.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
