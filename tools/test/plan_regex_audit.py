#!/usr/bin/env python3
r"""plan_regex_audit.py —— 用例文件里的断言正则「体检」（第 83 轮；★★★ 第 159 轮：窗口自检）。

背景（三类同类事故，症状都是「日志里没出现 /…/」的超时，误导成产品没打这行）：
  * 第 68 轮：`r67_chain` 把 `\d` 写成 `\\d` —— ECMAScript 下等于「字面反斜杠 + d」，
    永不匹配；
  * 第 83 轮：`r80_repeatable_npc` 把**全角** `）` 写成半角转义 `\)` —— 同一类病
    （正则合法、永不匹配）；
  * ★★★ 第 159 轮（2026-09-24 23:01 会话 r155 的唯一 FAIL）：**正则没错、窗口错了** ——
    `assert.log … scope=prev` 的窗口 = **紧邻的上一步**（`g_prevMark` = 上一步开始时
    的打点）；连着写两条断言时，第二条的窗口只剩「上一条断言行」（`LogFind` 跳过含
    `harness：` 的记录）⇒ 必然等不到产品行 ⇒ 120 s 超时假 FAIL（产品全对）。
    见 docs/09 十五·5「窗口语义」。
    ★ `note` 步骤同样会「吃掉」窗口 —— 它只打 harness 行，不打产品行。

本工具做三件事（拿一份**真实跑过的日志**）：
  ① **段内体检**（第 83 轮）：按用例分段逐条试跑断言正则 —— 段内一次都没命中 ⇒ 报
     （正则写错 / 前置步骤没跑到）；
  ② **窗口自检**（第 159 轮）：照驱动器的窗口语义重建每个断言步骤当时**能看到的
     产品记录**，报告「只在窗口外命中」（= 现场必然假 FAIL 的断言，哪怕正则本身对）；
  ③ **静态窗口体检**（第 159 轮，只看用例文件、不需要日志、**提示级**）：列出
     `scope=prev` 断言里「紧邻上一步是 `note` / `assert.*`」的写法 —— 这类写法只有
     在目标行**异步**才打（脚本节拍 / 引擎事件）时才对（r26/r44/r62/r81 就是这种用法），
     需要人工过一眼（`--plan-only`）。

用法：
    python tools/test/plan_regex_audit.py                     # 默认读 MO2 部署目录的日志
    python tools/test/plan_regex_audit.py <日志路径> [用例文件]
    python tools/test/plan_regex_audit.py --plan-only         # 只跑静态窗口体检（秒级）

★ 第 94 轮：日志有 1MB 上限、超限会**清空全部旧内容**（main.cpp 的 SizeLimitedFileSink）——
  长会话（26 条用例）跑到后段时，**开头的用例段会被整个清掉**。此前这会被报成
  「N 条未命中（用例没跑到）」的大片噪声（其实段不存在 = 无从体检，不是缺陷）。
  现在分两类：① **前缀缺失**（缺的段全部早于最早的在段）= 日志滚动清掉的 ⇒ 只提示；
  ② 中间 / 末尾缺段 = 真的异常 ⇒ 仍计 bad。日志里一个用例段都没有 ⇒ 退出码 2
  （无从体检，不再静默假绿）。

★★★ 第 158 轮（增量测试感知）：日志同目录的 `SAQ_testresults.json` 里 `only` 非空
  = 本次是**增量跑**（只跑了 [Test] Only 命中的用例）—— 未选中的用例「没有段」是
  正常行为，不再计 bad（只提示），它们的断言也不参与体检（check 数只算选中用例）。
  only 为空 / 结果 JSON 不存在 ⇒ 行为与过去完全一致（全量跑）。

窗口模型（与 SAQ_TestOps.cpp 的 `LogRingSink` / `LogMark` / `LogFind` 逐条对齐）：
  * 环形缓冲的**一条记录** = 一次日志调用（多行文本算 1 条；续行没有时间戳前缀）；
    `LogMark()` 数的是记录数；
  * `LogFind` 跳过**含 `harness：` 的记录**（含它的续行 = 探针输出被抄进步骤行的那份），
    所以断言只认产品记录；
  * 窗口**只有下界**（`LogFind(from, …)` 搜 `idx >= from` 的记录、一直搜到本步轮询结束）：
    `scope=prev` = 上一步**开始**时的打点；`scope=this` = 本步开始时的打点；
    `scope=case` = 本用例开头的打点。
    ⇒ 断言能看到的 = 下界之后的所有产品记录（含本步轮询期间异步落下那些）。

退出码：0 = 体检通过（可含「滚动清掉、无从体检」「增量未选中」「未跑到」的提示）；
        1 = 有未命中 / 窗口外命中 / 真的缺段 / 静态窗口体检命中；
        2 = 无从体检（没有用例段 / 没解析出断言）。
"""
from __future__ import annotations

import json
import pathlib
import re
import sys

DEFAULT_LOG = pathlib.Path(
    r"D:\Mod Organizer 2\starfield_mods\mods\Show Available Quests (SFSE)"
    r"\SFSE\Plugins\SAQ_ShowAvailableQuests.log"
)
ROOT = pathlib.Path(__file__).resolve().parents[2]
DEFAULT_PLAN = ROOT / "tools/test/scenarios/SAQ_TestPlan.txt"

# 驱动器在解析后就从断言文本里摘掉的 token（见 SAQ_Test.cpp 的 ExtractTimeout/ExtractScope）
TOKEN_RE = re.compile(r"\s*(?:timeout=\d+|scope=\w+)")
CASE_START_RE = re.compile(r"===== 开始用例 (\S+?)（")
# 一条记录的开头 = 带时间戳的行（续行没有前缀）
REC_START_RE = re.compile(r"^\[\d{2}:\d{2}:\d{2}\.\d{3}\]")
# 步骤完成行：`harness：  [PASS] <步骤原文>（N ms） —— <明细>`
EXEC_STEP_RE = re.compile(r"harness：\s+\[(PASS|FAIL|note|SKIP)\]\s*(.*)$")
ELAPSED_RE = re.compile(r"（\d+ ms）")

ASSERT_OPS = ("assert.log", "assert.nolog", "assert.ui")


# ---------------------------------------------------------------------------
#  用例文件
# ---------------------------------------------------------------------------
def parse_plan(text: str) -> list[tuple[str, list[tuple[str, str, str]]]]:
    """[(case_id, [(op, rest, body), …]), …] —— rest 已去掉 op 名（timeout/scope 还在）。"""
    cases: list[tuple[str, list[tuple[str, str, str]]]] = []
    for raw in text.splitlines():
        s = raw.strip()
        if s.lower().startswith("[case:"):
            cases.append((s[len("[case:"):].rstrip("]").strip(), []))
            continue
        if not cases or not s.lower().startswith("step ="):
            continue
        body = s[len("step = "):].strip()
        op, _, rest = body.partition(" ")
        cases[-1][1].append((op, rest.strip(), body))
    return cases


def regex_of(rest: str) -> str:
    return TOKEN_RE.sub("", rest).strip()


def scope_of(rest: str) -> str:
    m = re.search(r"scope=(\w+)", rest)
    return m.group(1) if m else "this"


def static_window_lint(cases) -> list[tuple[str, str, str]]:
    """只看用例文件（提示级，不是判据）：`scope=prev` 断言的紧邻上一步是 note / assert。

    这类写法**不一定坏** —— 窗口只有下界（见 window_range 的说明），只要断言等的目标行
    是**异步**在轮询期间才打的（脚本节拍 / 引擎事件），它照样落在窗口里（r26/r44/r62/r81
    就是这种用法）。坏的是「目标行在上一步之前就同步打完了」（第 159 轮 r155 实测）。
    所以这里只列出来供人工过一眼；硬判据是窗口自检（要日志）。
    """
    sus: list[tuple[str, str, str]] = []
    for cid, steps in cases:
        prev_op: str | None = None
        for op, rest, body in steps:
            if op in ASSERT_OPS and scope_of(rest) == "prev" and prev_op is not None:
                if prev_op == "note" or prev_op.startswith("assert."):
                    sus.append((cid, body, prev_op))
            prev_op = op
    return sus


# ---------------------------------------------------------------------------
#  日志：记录模型
# ---------------------------------------------------------------------------
def split_records(lines: list[str]) -> list[list[str]]:
    """把日志切成「记录」：带时间戳的行开一条，其后无时间戳的续行归它。"""
    recs: list[list[str]] = []
    for ln in lines:
        if REC_START_RE.match(ln):
            recs.append([ln])
        elif recs:
            recs[-1].append(ln)
    return recs


def rec_text(rec: list[str]) -> str:
    return "\n".join(rec)


def is_harness(rec: list[str]) -> bool:
    """驱动器 `LogFind` 的判据：记录文本里含 `harness：` ⇒ 断言不认它。"""
    return any("harness：" in ln for ln in rec)


def exec_step_of(rec: list[str]) -> tuple[str, str] | None:
    """记录是「步骤完成行」⇒ 返回 (marker, body)；body 已去掉 `（N ms）` 与证据文本。"""
    if not is_harness(rec):
        return None
    m = EXEC_STEP_RE.search(rec[0])
    if not m:
        return None
    marker, rest = m.group(1), m.group(2)
    if marker == "note":
        return None  # `[note]` 只是 note 步骤的开场白；它的完成行是 `[PASS] note …`
    mm = ELAPSED_RE.search(rest)
    return marker, (rest[: mm.start()] if mm else rest).strip()


def build_case_index(recs) -> dict[str, dict]:
    """把已执行的用例段（起点 / 终点 + 步骤完成记录）索引出来。"""
    cases: dict[str, dict] = {}
    cur: str | None = None
    for i, rec in enumerate(recs):
        if is_harness(rec):
            m = CASE_START_RE.search(rec[0])
            if m:
                if cur is not None:
                    cases[cur]["end"] = i - 1
                cur = m.group(1)
                cases[cur] = {"start": i, "end": len(recs) - 1, "steps": []}
                continue
            if "全部用例结束" in rec[0]:
                if cur is not None:
                    cases[cur]["end"] = i
                cur = None
                continue
        if cur is None:
            continue
        st = exec_step_of(rec)
        if st is not None:
            cases[cur]["steps"].append((i, st[0], st[1]))
    return cases


def norm(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()


def plan_key(op: str, rest: str) -> str:
    return norm(rest)


def exec_key(marker: str, body: str) -> str:
    """把步骤完成行规整成与计划步骤同形（`note` 行不带 op 名，其余带 ⇒ 去掉首 token）。"""
    if marker == "note":
        return norm(body)
    parts = body.split(" ", 1)
    return norm(parts[1] if len(parts) > 1 else "")


def window_range(scope: str, case_start: int, marks: list[int], k: int) -> tuple[int, int]:
    """驱动器语义下的窗口（闭区间）——marks[j] = 第 j 步的完成记录下标。

    ★ 窗口**只有下界**（`LogFind(from, …)` 搜的是 `idx >= from` 的记录，一直搜到本步
      轮询结束）——上界 = 本步完成时。下限：
        * `scope=prev` = 上一步**开始**时的打点 = 上上步完成记录的下一条；
        * `scope=this` = 本步开始时的打点 = 上一步完成记录的下一条；
        * `scope=case` = 本用例开头（`开始用例` 记录）的打点。
      ⇒ 「上一步是 note / assert」不一定坏：只要断言的目标行是**异步**在轮询期间才打的
        （脚本节拍 / 引擎事件），它照样落在窗口里（r26/r44/r62/r81 就是这种用法）；
        坏的是「目标行在上一步之前就打完了」（r155 第 159 轮实测）。
    """
    if scope == "prev":
        if k == 0:
            return (case_start + 1, case_start)          # 空窗口（第 0 步没有「上一步」）
        lo = case_start if k == 1 else marks[k - 2] + 1  # 上一步开始时的打点
        return (lo, marks[k])
    if scope == "this":
        lo = case_start if k == 0 else marks[k - 1] + 1
        return (lo, marks[k])
    return (case_start, marks[k])                        # case：本用例开头起


# ---------------------------------------------------------------------------
#  结果 JSON（增量筛选）
# ---------------------------------------------------------------------------
def read_scan_scope(log_path: pathlib.Path) -> tuple[set[str] | None, str]:
    """★ 第 158 轮（增量感知）：读日志同目录的结果 JSON。

    返回 (selected, only)：
      * only 非空（增量跑）⇒ selected = 本次选中的用例 id 集合、only = 原始筛选值；
      * only 为空 / 结果 JSON 不存在 / 读不出 ⇒ (None, "")（全量口径，行为同旧版）。
    """
    res = log_path.with_name("SAQ_testresults.json")
    if not res.exists():
        return None, ""
    try:
        data = json.loads(res.read_bytes().decode("utf-8-sig", errors="replace"))
    except Exception:  # noqa: BLE001
        return None, ""
    only = str(data.get("only") or "").strip()
    if not only:
        return None, ""
    return {str(r.get("id", "")) for r in data.get("results", [])}, only


def run_audit(plan_cases, recs, exec_cases, selected, static_sus):
    """核心体检（可被自测复用）：返回 (checked, plan_order, missing, bad, info, win_ok)。"""
    checked = 0
    plan_order: list[str] = []
    missing: list[str] = []
    bad: list[tuple[str, str, str, str]] = []
    info: list[tuple[str, str, str, str]] = [
        (cid, "（用例文件）", body,
         f"提示：scope=prev 的上一步是 `{prev_op}`（不打产品行 —— 只有异步行才落进窗口）")
        for cid, body, prev_op in static_sus
    ]
    win_ok = 0

    for cid, steps in plan_cases:
        plan_order.append(cid)
        if selected is not None and cid not in selected:
            continue  # ★ 第 158 轮：增量跑 —— 没选中的用例不体检
        ec = exec_cases.get(cid)
        if ec is None:
            missing.append(cid)

        marks = [s[0] for s in ec["steps"]] if ec else []
        # 对齐：驱动器失败即停 ⇒ 已执行步骤必是计划步骤的前缀
        aligned = True
        if ec:
            for i, (op, rest, _body) in enumerate(steps):
                if i >= len(ec["steps"]):
                    break
                if plan_key(op, rest) != exec_key(ec["steps"][i][1], ec["steps"][i][2]):
                    aligned = False
                    info.append((cid, "（对齐）", steps[i][2],
                                 "计划步骤与日志步骤对不上号（用例文件在本次会话之后改过？"
                                 "本用例跳过窗口自检）"))
                    break

        case_pool = ([r for r in recs[ec["start"]:ec["end"] + 1] if not is_harness(r)]
                     if ec else [])

        for i, (op, rest, body) in enumerate(steps):
            if op not in ASSERT_OPS:
                continue
            rx_text = regex_of(rest)
            if not rx_text:
                continue
            try:
                rx = re.compile(rx_text, re.I)
            except re.error as e:
                bad.append((cid, op, rx_text, f"正则非法：{e}"))
                checked += 1
                continue
            checked += 1

            def hit_in(pool):
                for r in pool:
                    txt = rec_text(r)
                    if op == "assert.ui" and "_root.SAQ_Report=" not in txt:
                        continue
                    if rx.search(txt):
                        return True
                return False

            if ec is None:
                continue  # 段缺失：按 missing 统一报
            if not aligned or i >= len(ec["steps"]):
                tail = ""
                # scope=case 的下界 = 用例开头 ⇒ 与「跑没跑到」无关：目标行只要在这次
                # 日志里出现过，重跑（窗口只增不减）必然也命中 —— 可作乐观预演。
                if scope_of(rest) == "case" and op == "assert.log" and hit_in(case_pool):
                    tail = "；其窗口下界 = 用例开头 ⇒ 目标行已在这次日志里（重跑预期命中）"
                info.append((cid, op, rx_text, "未跑到（用例在更靠前的步骤失败 / 对齐不上）" + tail))
                continue

            # ★ `assert.ui` 读的是**界面实时报告**（`UI::ReadUiReport`），不走日志窗口 ——
            #   这里只做启发式体检：本用例段的 `界面状态 … _root.SAQ_Report=` 行里能不能
            #   匹配到（命中就说明那一刻界面确实报了这句话）。
            if op == "assert.ui":
                if hit_in(case_pool):
                    win_ok += 1
                else:
                    info.append((cid, op, rx_text,
                                 "界面实时报告型断言（不走日志窗口）—— 用例段的界面状态行里"
                                 "没匹配到，人工确认"))
                continue

            # ── ② 窗口自检 ──────────────────────────────────────────────
            scope = scope_of(rest)
            lo, hi = window_range(scope, ec["start"], marks, i)
            win_pool = [r for r in recs[lo:hi + 1] if not is_harness(r)] if hi >= lo else []
            hit_win = hit_in(win_pool)
            hit_anywhere = hit_in(case_pool)
            if op == "assert.nolog":
                if hit_win:
                    info.append((cid, op, rx_text,
                                 f"窗口（scope={scope}）里出现了（反向断言会判 FAIL —— 复核是否合理）"))
                else:
                    win_ok += 1
            elif hit_win:
                win_ok += 1
            elif hit_anywhere:
                bad.append((cid, op, rx_text,
                            f"**窗口外才命中**（scope={scope} 的窗口里没有产品行 ⇒ 现场必然假 FAIL）"))
            else:
                bad.append((cid, op, rx_text, "本用例段里一次都没命中（正则写错 / 前置步骤没跑）"))

    return checked, plan_order, missing, bad, info, win_ok


# ---------------------------------------------------------------------------
#  自测（--self-test）：合成日志钉住窗口语义（第 159 轮；离线层可跑）
# ---------------------------------------------------------------------------
SYNTH_PLAN = """\
[case:t_ok]
step = probe.demo
step = assert.log 探针 汇总：24 位 scope=prev timeout=1000
step = assert.log 探针 汇总：.*对照 3 位 / 不一致 0 位 scope=case timeout=1000
step = assert.log 探针 最后一行 scope=prev timeout=1000

[case:t_bad]
step = probe.demo
step = assert.log 探针 汇总：24 位 scope=prev timeout=1000
step = assert.log 探针 汇总：.*对照 3 位 / 不一致 0 位 scope=prev timeout=1000
"""

# t_ok：三条断言都应命中（第 1 条 prev = 探针步；第 3 条 prev = 上一条断言行，
#       但目标行是**异步**后落的 ⇒ 落进窗口 —— 这正是 r26/r44 那种用法的语义）；
# t_bad：第 3 条步（prev）= 上一条断言行 ⇒ 目标行在窗口下界**之前** ⇒ 应抓成假 FAIL。
SYNTH_LOG = """\
[10:00:00.100] [1] [I] harness：===== 开始用例 t_ok（窗口语义自测）=====
[10:00:00.200] [1] [I] 探针 汇总：24 位｜直读 3 位（对照 3 位 / 不一致 0 位）
[10:00:00.300] [1] [I] harness：  [PASS] probe.demo（100 ms） —— 探针 汇总：24 位｜直读 3 位（对照 3 位 / 不一致 0 位）
[10:00:00.400] [1] [I] harness：  [PASS] assert.log 探针 汇总：24 位 scope=prev timeout=1000（0 ms） —— 命中：探针 汇总：24 位
[10:00:00.500] [1] [I] harness：  [PASS] assert.log 探针 汇总：.*对照 3 位 / 不一致 0 位 scope=case timeout=1000（0 ms） —— 命中：…
[10:00:00.600] [1] [I] 探针 最后一行
[10:00:00.700] [1] [I] harness：  [PASS] assert.log 探针 最后一行 scope=prev timeout=1000（0 ms） —— 命中：探针 最后一行
[10:00:00.800] [1] [I] harness：用例 t_ok PASS（700 ms）
[10:00:00.900] [1] [I] harness：===== 开始用例 t_bad（窗口语义自测）=====
[10:00:01.000] [1] [I] 探针 汇总：24 位｜直读 3 位（对照 3 位 / 不一致 0 位）
[10:00:01.100] [1] [I] harness：  [PASS] probe.demo（100 ms） —— 探针 汇总：24 位｜直读 3 位（对照 3 位 / 不一致 0 位）
[10:00:01.200] [1] [I] harness：  [PASS] assert.log 探针 汇总：24 位 scope=prev timeout=1000（0 ms） —— 命中：探针 汇总：24 位
[10:00:01.300] [1] [I] harness：  [FAIL] assert.log 探针 汇总：.*对照 3 位 / 不一致 0 位 scope=prev timeout=1000（1000 ms）—— 日志里没出现 /探针 汇总：.*对照 3 位 / 不一致 0 位/
[10:00:01.400] [1] [I] harness：用例 t_bad FAIL（1000 ms）
[10:00:01.500] [1] [I] harness：全部用例结束（2 条；PASS 1 / FAIL 1 / SKIP 0）
"""


def self_test() -> int:
    plan = parse_plan(SYNTH_PLAN)
    recs = split_records(SYNTH_LOG.splitlines())
    exec_cases = build_case_index(recs)
    checked, _order, _missing, bad, _info, win_ok = run_audit(plan, recs, exec_cases, None, [])
    checks = [
        ("两个用例段都解析出来（note 行不算步骤）", len(exec_cases) == 2),
        ("t_ok 三条 + t_bad 首条都「窗口内命中」", win_ok == 4),
        ("只有 t_bad 的第二条 prev 被判「窗口外才命中」",
         len(bad) == 1 and bad and bad[0][0] == "t_bad" and "窗口外才命中" in bad[0][3]),
    ]
    print(f"窗口语义自测：用例段 {len(exec_cases)} 个、断言 {checked} 条、"
          f"窗口内命中 {win_ok}、问题 {len(bad)} 条")
    for name, good in checks:
        print(("OK   " if good else "MISS ") + " 窗口自测 · " + name)
    if not all(g for _, g in checks):
        for cid, op, rx, why in bad:
            print(f"      问题：[{cid}] {op} —— {why}\n      /{rx}/")
        return 1
    print("窗口语义自测全过（prev 只有下界 / 第二条 prev 抓得住 / 异步行落进窗口）。")
    return 0


def main() -> int:
    try:
        sys.stdout.reconfigure(errors="replace")
    except Exception:  # noqa: BLE001
        pass

    if "--self-test" in sys.argv[1:]:
        return self_test()

    args = [a for a in sys.argv[1:] if a != "--plan-only"]
    plan_only = "--plan-only" in sys.argv[1:]
    log_path = pathlib.Path(args[0]) if len(args) > 0 else DEFAULT_LOG
    plan_path = pathlib.Path(args[1]) if len(args) > 1 else DEFAULT_PLAN
    if not plan_path.exists():
        print(f"没有用例文件：{plan_path}")
        return 2

    plan_text = plan_path.read_text(encoding="utf-8", errors="replace")
    plan_cases = parse_plan(plan_text)
    if not plan_cases:
        print(f"用例文件里没解析出用例（{plan_path.name}）—— 无从体检。")
        return 2

    # ── ③ 静态窗口体检（只看用例文件；提示级 —— 硬判据是下面的窗口自检）─────
    static_sus = static_window_lint(plan_cases)
    if plan_only:
        print(f"静态窗口体检（{plan_path.name}）：{len(plan_cases)} 个用例里，"
              f"`scope=prev` 断言的紧邻上一步是 note / assert 的共 {len(static_sus)} 条")
        for cid, body, prev_op in static_sus:
            print(f"  [~] [{cid}] —— 上一步是 `{prev_op}`（不打产品行）：\n      {body}")
        print("（提示级：这类写法只有在目标行**异步**才打的时候才成立 —— 例如脚本节拍 /"
              " 引擎事件在断言轮询期间才落盘；\n  若目标行是上一步**同步**打的（探针/产品"
              "动作），窗口里等不到 ⇒ 现场假 FAIL。见 docs/09 十五·5。）")
        return 0

    if not log_path.exists():
        print(f"没有日志文件：{log_path}")
        print(f"（静态窗口体检：可疑 {len(static_sus)} 条 —— 用 --plan-only 看明细）")
        return 2

    lines = log_path.read_text(encoding="utf-8", errors="replace").splitlines()
    recs = split_records(lines)
    exec_cases = build_case_index(recs)
    selected, only = read_scan_scope(log_path)

    if not exec_cases:
        print(f"日志里没有任何用例段（{log_path.name}）—— 无从体检。")
        print("（日志被滚动清空 / 这不是这次会话的日志 / 用例根本没跑。"
              "先确认 harness 跑过，再看这份日志。）")
        return 2

    checked, plan_order, missing, bad, info, win_ok = run_audit(
        plan_cases, recs, exec_cases, selected, static_sus)

    if checked == 0:
        print(f"用例文件里没解析出可体检的断言（{plan_path.name}）—— 无从体检。")
        return 2

    # ★ 第 94 轮：缺段分两类 —— 前缀缺失（全部早于最早的在段）= 日志滚动清掉的（正常）；
    #   其余（中间 / 末尾有洞）= 真的异常，仍计 bad。
    rolled: list[str] = []
    holes = missing
    if missing:
        idx = {cid: i for i, cid in enumerate(plan_order)}
        present = [idx[c] for c in exec_cases if c in idx]
        if present and max(idx[c] for c in missing) < min(present):
            rolled, holes = missing, []
    for cid in holes:
        bad.append((cid, "（整个用例）", "—",
                    "这次日志里根本没有这个用例（没跑到 / 中途中止）"))

    print(f"检查 {checked} 条断言（日志 {log_path.name}｜用例段 {len(exec_cases)} 个）")
    if selected is not None:
        skipped = [c for c in plan_order if c not in selected]
        print(f"（提示）本次为**增量跑**：Only={only} —— 选中 {len(selected)} 条用例、"
              f"未选中 {len(skipped)} 条（未选中不是缺陷；收口 / 打包前请跑一次全量）。")
        if skipped:
            print(f"      未选中：{', '.join(skipped)}")
    print(f"窗口自检（第 159 轮）：窗口内命中 {win_ok} 条；问题 {len(bad)} 条"
          f"（静态窗口体检另列提示 {len(static_sus)} 条）")
    if rolled:
        print(f"（提示）{len(rolled)} 个用例段不在日志里、**无从体检**："
              f"{', '.join(rolled)}")
        print("      —— 全部集中在最早的段之前 = 日志滚动清掉了开头"
              "（1MB 上限的正常现象，不是缺陷）。")
    if bad:
        print(f"有 {len(bad)} 条问题（人工过一眼：写错的正则 / 窗口写错 / 前置步骤没跑到）：")
        for case_, op, regex, why in bad:
            print(f"  [{case_}] {op} —— {why}\n      /{regex[:150]}/")
    else:
        print("全部命中：没有「永不匹配」的断言正则、也没有「窗口外才命中」的断言。")
    for case_, op, regex, why in info:
        print(f"  （提示）[{case_}] {op} —— {why}\n      /{regex[:150]}/")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
