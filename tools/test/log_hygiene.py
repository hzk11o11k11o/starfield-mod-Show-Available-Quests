#!/usr/bin/env python3
r"""log_hygiene.py - 日志/结果文件「证据通道健康」体检（第 84 轮）。

背景（第 84 轮自动测试二跑复查）：
    结果 JSON 里出现**一处非法 UTF-8 字节** —— `EscapeForLog` 把「界面状态」行按
    字节截断，正好切在「追踪者联盟」的「者」中间（`追踪` + 0xE8 + `…`）⇒
    `check_results.py` 的 `json.loads` 前解码抛错、退出码 2：**22 条用例的结果
    一条也读不出来**（判据通道整体失效，比任何单条用例 FAIL 都严重）。

    真因两处（DLL 侧，均已修）：
      ① `UI::EscapeForLog` 字节截断 → 现在走 `Decision::Utf8SafeCut`（切点回退到字符首字节）；
      ② 指针诊断的 RTTI 抄录把随机字节原样写进日志（含控制字符，把一行诊断劈成好几行）
         → 现在只留可打印 ASCII（其余换成 `.`）。

本工具是**回归体检**：每一轮实机之后跑一次 —— 只要日志/结果里再出现非法 UTF-8
或控制字符（不含制表符），就当场报出位置与上下文。

用法：
    python tools/test/log_hygiene.py             # 默认查 MO2 部署里的日志 + 结果 JSON
    python tools/test/log_hygiene.py <文件>...   # 指定文件（可多个）

退出码：0 = 干净；1 = 发现非法字节 / 控制字符；2 = 文件不存在。

★ 注意：第 84 轮**之前**的 DLL 写的旧日志会（如实地）报出坏字节 —— 那是历史证据，
  不是回归。判据用「新 DLL 跑出来的新日志」。
"""
from __future__ import annotations

import pathlib
import sys

sys.stdout.reconfigure(errors="replace")

DEFAULT_FILES = [
    pathlib.Path(
        r"D:\Mod Organizer 2\starfield_mods\mods\Show Available Quests (SFSE)"
        r"\SFSE\Plugins\SAQ_ShowAvailableQuests.log"
    ),
    pathlib.Path(
        r"D:\Mod Organizer 2\starfield_mods\mods\Show Available Quests (SFSE)"
        r"\SFSE\Plugins\SAQ_testresults.json"
    ),
]

# 允许的控制字符：制表符（日志里不会出现，但转义前可能出现——不，转义后是 \t 文本）。
# 其余 C0 控制字符（除 \r\n）都算「会劈行 / 破坏证据」的字节。
ALLOWED_CTRL = {0x09}


def scan(path: pathlib.Path) -> tuple[int, int, int]:
    """返回（非法 UTF-8 处数, 控制字符处数, 总行数）。"""
    raw = path.read_bytes()
    text = raw.decode("utf-8", errors="replace")

    bad_utf8 = 0
    bad_ctrl = 0
    lines = text.splitlines()
    for i, line in enumerate(lines):
        if "\ufffd" in line:
            n = line.count("\ufffd")
            bad_utf8 += n
            ctx = line[:120]
            print(f"  [坏字节] 第 {i + 1} 行（{n} 处）：{ctx}")
        for ch in line:
            o = ord(ch)
            if o < 0x20 and o not in ALLOWED_CTRL:
                bad_ctrl += 1
    return bad_utf8, bad_ctrl, len(lines)


def main() -> int:
    args = sys.argv[1:]
    files = [pathlib.Path(a) for a in args] if args else DEFAULT_FILES

    all_clean = True
    for p in files:
        if not p.exists():
            print(f"[跳过] 文件不存在：{p}")
            continue
        print(f"== {p.name}（{p.stat().st_size} B） ==")
        bad_utf8, bad_ctrl, n_lines = scan(p)
        if bad_utf8 == 0 and bad_ctrl == 0:
            print(f"  OK：{n_lines} 行，无非法 UTF-8、无控制字符。")
        else:
            all_clean = False
            print(f"  FAIL：{n_lines} 行 —— 非法 UTF-8 {bad_utf8} 处 / 控制字符 {bad_ctrl} 处。")
            print("        （第 84 轮起 DLL 的截断按字符边界、RTTI 只留可打印 ASCII；")
            print("          若这是新 DLL 跑出来的日志，说明又出现了新的坏字节来源。）")
        print()

    if not files:
        return 2
    return 0 if all_clean else 1


if __name__ == "__main__":
    raise SystemExit(main())
