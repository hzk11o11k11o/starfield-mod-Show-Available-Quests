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
    # ★★ 第 84 轮：非法 UTF-8 不再让**整份报告**读不出来。
    #   实测（06:11 会话）：DLL 把「界面状态」行按字节截断到 900 —— 正好切在
    #   「追踪者联盟」的「者」中间（`追踪` + 0xE8 + `…`）⇒ 这一处坏字节被抄进结果
    #   JSON ⇒ `json.loads` 前的解码抛错 ⇒ 22 条用例的结果一条也读不出（退出码 2，
    #   比任何单条 FAIL 都严重 —— 判据通道整体失效）。
    #   DLL 侧已修（截断按字符边界：Decision::Utf8SafeCut）；这里再做一层防御：
    #   用替换字符读出 + 明确提示（若再看到提示，说明线上 DLL 还是旧的）。
    bad_utf8 = False
    try:
        text = p.read_bytes().decode("utf-8-sig")   # 插件写文件时带 BOM（记事本友好）
    except UnicodeDecodeError:
        text = p.read_bytes().decode("utf-8-sig", errors="replace")
        bad_utf8 = True
    try:
        data = json.loads(text)
    except Exception as e:  # noqa: BLE001
        print(f"结果文件解析失败：{p}\n  {e}")
        return 2
    if bad_utf8:
        print("提示：结果文件含非法 UTF-8 字节（已用替换字符读出下文）。")
        print("      第 84 轮前的 DLL 会在截断（日志 / 界面状态行）时切坏多字节字符，")
        print("      或把指针诊断的乱码字节原样写进日志；两处均已修 —— 若仍看到本提示，")
        print("      请先用 verify 确认部署的 DLL 是第 84 轮之后的产物。")
        print()

    s = data.get("summary", {})
    print(f"=== SAQ harness 结果 ===")
    print(f"时间     : {data.get('generatedAt', '?')}（会话时长 {data.get('sessionMs', '?')} ms）")
    print(f"用例文件 : {data.get('plan', '?')}")
    # ★★★ 第 158 轮（增量测试）：结果 JSON 的 `only` 非空 = 本次只跑了命中的用例
    #   （日志窗口纪律：判读时别把「没跑到的用例」当成异常）。
    only = str(data.get("only") or "").strip()
    if only:
        print(f"增量筛选 : Only={only}（★ 不是全量 —— 收口 / 打包前需不带 -Only 跑全量）")
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
