#!/usr/bin/env python3
"""make_lrg_source.py - 由「普通版改好的 AS3」生成 lrg（大字模式）版本。

背景：missionmenu.swf 与 missionmenu_lrg.swf 是同一套脚本，只有 MissionMenu.as
差 4 行（Embed symbol94 -> symbol96、多一句 largeTextMode = true、多一句
_loc2_ += "_LRG"）。改 UI 时两边都要打补丁，但维护两份手改脚本容易漂移，
所以：普通版是唯一手改的地方，lrg 版由本脚本机械生成。

用法：python tools/ui/make_lrg_source.py
"""
from __future__ import annotations

import io
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "ui/missionmenu/src"
DST = ROOT / "ui/missionmenu_lrg/src"

# 只从普通版覆盖这两个文件；其余脚本用 lrg 自己的反编译产物
COPY = [
    ("MissionMenu.as", "MissionMenu.as"),
    ("Shared/QuestUtils.as", "Shared/QuestUtils.as"),
]

# lrg 版与普通版的脚本差异（普通版 -> lrg 版）
REPLACEMENTS = [
    (
        'symbol="symbol94"',
        'symbol="symbol96"',
    ),
    (
        "addFrameScript(8,this.frame9,16,this.frame17);",
        "addFrameScript(8,this.frame9,16,this.frame17);\r\n         MissionsListEntry.largeTextMode = true;",
    ),
    (
        '_loc2_ = "$EXIT HOLD";',
        '_loc2_ = "$EXIT HOLD";\r\n               _loc2_ += "_LRG";',
    ),
]


def main() -> int:
    if not SRC.exists():
        print(f"缺少普通版源码目录：{SRC}", file=sys.stderr)
        return 1

    for rel_src, rel_dst in COPY:
        s = SRC / rel_src
        d = DST / rel_dst
        d.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(s, d)
        print(f"copy {rel_src} -> {d.relative_to(ROOT)}")

    mm = DST / "MissionMenu.as"
    text = io.open(mm, encoding="utf-8", errors="replace", newline="").read()

    for old, new in REPLACEMENTS:
        if old not in text:
            print(f"!! 未找到待替换片段：{old[:60]}", file=sys.stderr)
            return 2
        if new.split("\r\n")[0] != old and old in text:
            pass
        text = text.replace(old, new)
        print(f"patched: {old[:50]}")

    # 防重复（脚本跑两次时上面第二三条会被再插一次）
    for marker in ("MissionsListEntry.largeTextMode = true;", '_loc2_ += "_LRG";'):
        if text.count(marker) > 1:
            print(f"!! {marker} 出现 {text.count(marker)} 次（脚本被重复执行？）", file=sys.stderr)
            return 3

    io.open(mm, "w", encoding="utf-8", newline="").write(text)
    print(f"wrote {mm.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
