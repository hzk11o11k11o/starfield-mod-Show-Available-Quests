#!/usr/bin/env python3
r"""check_results.py - 读 harness 的结果 JSON，打印人类可读报告 + 退出码（第 49 轮）。

用法：
    python tools/test/check_results.py                     # 默认读 MO2 里的那份
    python tools/test/check_results.py <路径>              # 指定 SAQ_testresults.json
    python tools/test/check_results.py --tail 40           # 失败用例多打几行证据

退出码：0 = 全部 PASS；1 = 有 FAIL / SKIP；2 = 结果文件不存在或解析不了。

为什么要有它：结果 JSON 是给机器看的（也是证据），人只需要看「哪条红了、红在哪一步、
当步之后的日志是什么」。日志本身有 1MB 上限会滚动清空，所以证据被抄进了 JSON。
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys

DEFAULT = pathlib.Path(
    r"D:\Mod Organizer 2\starfield_mods\mods\Show Available Quests (SFSE)"
    r"\SFSE\Plugins\SAQ_testresults.json"
)


def main() -> int:
    try:
        sys.stdout.reconfigure(errors="replace")
    except Exception:
        pass

    ap = argparse.ArgumentParser()
    ap.add_argument("path", nargs="?", default=str(DEFAULT))
    ap.add_argument("--tail", type=int, default=25, help="失败步骤证据最多打几行")
    a = ap.parse_args()

    p = pathlib.Path(a.path)
    if not p.exists():
        print(f"没有结果文件：{p}")
        print("（harness 只在 ini [Test] Harness=1 且用例跑完后才写它；"
              "也可能是游戏还没跑到那一步。）")
        return 2
    try:
        # 用 utf-8-sig 读：插件写文件时带 UTF-8 BOM（记事本友好）
        data = json.loads(p.read_text(encoding="utf-8-sig"))
    except Exception as e:  # noqa: BLE001
        print(f"结果文件解析失败：{p}\n  {e}")
        return 2

    s = data.get("summary", {})
    print(f"=== SAQ harness 结果 ===")
    print(f"时间     : {data.get('generatedAt', '?')}（会话时长 {data.get('sessionMs', '?')} ms）")
    print(f"用例文件 : {data.get('plan', '?')}")
    print(f"汇总     : 用例 {s.get('cases', '?')}｜PASS {s.get('pass', 0)}"
          f"｜FAIL {s.get('fail', 0)}｜SKIP {s.get('skip', 0)}")
    print()

    bad = 0
    for r in data.get("results", []):
        status = r.get("status", "?")
        mark = {"PASS": "[OK  ]", "FAIL": "[FAIL]", "SKIP": "[SKIP]"}.get(status, "[????]")
        line = f"{mark} {r.get('id', '?')}（{r.get('elapsedMs', '?')} ms）"
        if r.get("desc"):
            line += f" —— {r['desc']}"
        if r.get("reason"):
            line += f"｜原因：{r['reason']}"
        print(line)
        for st in r.get("steps", []):
            if st.get("status") != "PASS":
                print(f"        步骤 {st.get('op', '?')} → {st.get('status')}"
                      f"（{st.get('elapsedMs', '?')} ms）")
                if st.get("detail"):
                    print(f"          说明：{st['detail']}")
                ev = (st.get("evidence") or "").rstrip().splitlines()
                if ev:
                    print(f"          证据（本步骤之后的日志，最多 {a.tail} 行）：")
                    for ln in ev[: a.tail]:
                        print(f"            {ln}")
        if status != "PASS":
            bad += 1
        if not r.get("steps"):
            print("        （没有任何步骤记录 —— 用例可能在开始前就被中断了）")

    print()
    if bad == 0 and s.get("cases"):
        print("全部通过。")
        return 0
    print(f"有 {bad} 条用例不是 PASS（或没有用例记录）。")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
