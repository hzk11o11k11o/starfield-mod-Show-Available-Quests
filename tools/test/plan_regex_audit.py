#!/usr/bin/env python3
r"""plan_regex_audit.py —— 用例文件里的断言正则「体检」（第 83 轮）。

背景（两次同类事故）：
  * 第 68 轮：`r67_chain` 把 `\d` 写成 `\\d` —— ECMAScript 下等于「字面反斜杠 + d」，
    永不匹配；症状却是「日志里没出现 /…/」的超时（误导成产品没打这行）。
  * 第 83 轮：`r80_repeatable_npc` 把**全角** `）` 写成半角转义 `\)` —— 同一类病：
    正则合法（解析期编译校验查不出来），但永远匹配不到。

本工具做的事：拿一份**真实跑过的日志**，按**用例分段**（`===== 开始用例 <id> =====`
到下一个用例开始）逐条试跑所有断言正则：
  * `assert.log`  / `assert.ui`：本用例段里一次都没命中 ⇒ 报告（要么正则写错，
    要么这条断言的前置步骤没跑到 —— 报告里会区分「用例没跑到」和「段内没命中」）；
  * `assert.nolog`：本用例段里命中了 ⇒ 提示（驱动器看的是更小的窗口，段内命中
    未必是问题，人工过一眼）。

用法：
    python tools/test/plan_regex_audit.py                     # 默认读 MO2 部署目录的日志
    python tools/test/plan_regex_audit.py <日志路径> [用例文件]

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

退出码：0 = 体检通过（可含「滚动清掉、无从体检」「增量未选中」的提示）；1 = 有未命中 /
        真的缺段；2 = 无从体检（没有用例段 / 没解析出断言）。
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
DEFAULT_PLAN = pathlib.Path("tools/test/scenarios/SAQ_TestPlan.txt")

# 驱动器在解析后就从断言文本里摘掉的 token（见 SAQ_Test.cpp 的 ExtractTimeout/ExtractScope）
TOKEN_RE = re.compile(r"\s*(?:timeout=\d+|scope=\w+)")
CASE_START_RE = re.compile(r"===== 开始用例 (\S+?)（")


def split_cases(lines: list[str]) -> dict[str, list[str]]:
    """把日志按用例切成段（断言只认产品日志 —— harness 自己的行会复述命中文本）。"""
    cases: dict[str, list[str]] = {}
    cur: str | None = None
    for ln in lines:
        if "harness：" in ln:
            m = CASE_START_RE.search(ln)
            if m:
                cur = m.group(1)
                cases.setdefault(cur, [])
                continue
            if "全部用例结束" in ln:
                cur = None
            continue
        if cur is not None:
            cases[cur].append(ln)
    return cases


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


def main() -> int:
    try:
        sys.stdout.reconfigure(errors="replace")
    except Exception:
        pass

    log_path = pathlib.Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_LOG
    plan_path = pathlib.Path(sys.argv[2]) if len(sys.argv) > 2 else DEFAULT_PLAN
    if not log_path.exists():
        print(f"没有日志文件：{log_path}")
        return 2
    if not plan_path.exists():
        print(f"没有用例文件：{plan_path}")
        return 2

    lines = log_path.read_text(encoding="utf-8", errors="replace").splitlines()
    cases = split_cases(lines)
    selected, only = read_scan_scope(log_path)

    plan = plan_path.read_text(encoding="utf-8")
    case = "?"
    checked = 0
    plan_order: list[str] = []
    missing: list[str] = []
    bad: list[tuple[str, str, str, str]] = []
    info: list[tuple[str, str, str, str]] = []
    for raw in plan.splitlines():
        s = raw.strip()
        if s.lower().startswith("[case:"):
            case = s[len("[case:"):].rstrip("]").strip()
            if case not in plan_order:
                plan_order.append(case)
            continue
        if not s.lower().startswith("step = assert"):
            continue
        # ★ 第 158 轮（增量感知）：本次没选中的用例不体检 —— 日志里没有它们的段是
        #   正常行为（不是「用例没跑到」），它们的断言也不计入 check 数。
        if selected is not None and case not in selected:
            continue
        body = s[len("step = "):]
        op, _, rest = body.partition(" ")
        if op == "assert.menu":  # 看的是菜单开关状态，不是日志行 —— 本工具不适用
            continue
        rest = TOKEN_RE.sub("", rest.strip())
        if not rest:
            continue
        try:
            rx = re.compile(rest, re.I)
        except re.error as e:
            bad.append((case, op, rest, f"正则非法：{e}"))
            continue
        checked += 1
        seg = cases.get(case)
        if seg is None:
            if case not in missing:
                missing.append(case)
            continue
        pool = seg
        if op == "assert.ui":
            pool = [ln for ln in seg if "_root.SAQ_Report=" in ln]
        hit = any(rx.search(ln) for ln in pool)
        if op == "assert.nolog":
            if hit:
                info.append((case, op, rest, "本用例段里出现了（驱动器窗口更小，人工确认）"))
        elif not hit:
            bad.append((case, op, rest, "本用例段里一次都没命中"))

    if not cases:
        print(f"日志里没有任何用例段（{log_path.name}）—— 无从体检。")
        print("（日志被滚动清空 / 这不是这次会话的日志 / 用例根本没跑。"
              "先确认 harness 跑过，再看这份日志。）")
        return 2
    if checked == 0:
        print(f"用例文件里没解析出可体检的断言（{plan_path.name}）—— 无从体检。")
        return 2
    # ★ 第 94 轮：缺段分两类 —— 前缀缺失（全部早于最早的在段）= 日志滚动清掉的（正常）；
    #   其余（中间 / 末尾有洞）= 真的异常，仍计 bad。
    rolled: list[str] = []
    holes = missing
    if missing:
        idx = {cid: i for i, cid in enumerate(plan_order)}
        present = [idx[c] for c in cases if c in idx]
        if present and max(idx[c] for c in missing) < min(present):
            rolled, holes = missing, []
    for cid in holes:
        bad.append((cid, "（整个用例）", "—",
                    "这次日志里根本没有这个用例（没跑到 / 中途中止）"))

    print(f"检查 {checked} 条断言（日志 {log_path.name}｜用例段 {len(cases)} 个）")
    if selected is not None:
        skipped = [c for c in plan_order if c not in selected]
        print(f"（提示）本次为**增量跑**：Only={only} —— 选中 {len(selected)} 条用例、"
              f"未选中 {len(skipped)} 条（未选中不是缺陷；收口 / 打包前请跑一次全量）。")
        if skipped:
            print(f"      未选中：{', '.join(skipped)}")
    if rolled:
        print(f"（提示）{len(rolled)} 个用例段不在日志里、**无从体检**："
              f"{', '.join(rolled)}")
        print("      —— 全部集中在最早的段之前 = 日志滚动清掉了开头"
              "（1MB 上限的正常现象，不是缺陷）。")
    if bad:
        print(f"有 {len(bad)} 条未命中（人工过一眼：写错的正则 / 前置步骤没跑到）：")
        for case_, op, regex, why in bad:
            print(f"  [{case_}] {op} —— {why}\n      /{regex[:150]}/")
    else:
        print("全部命中：没有「永不匹配」的断言正则。")
    for case_, op, regex, why in info:
        print(f"  （提示）[{case_}] {op} —— {why}\n      /{regex[:150]}/")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
