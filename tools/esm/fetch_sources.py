#!/usr/bin/env python3
"""fetch_sources.py - 准备好「静态任务表」需要的离线数据（缺什么补什么，可反复跑）。

需要两样东西，**每个 master 一份**：

  1. `ref/quests_all.json`      quest_dump.py 的导出（Starfield.esm + 各官方 DLC 的 QUST）
  2. `ref/strings/strings/<master>_{en,zhhans}.strings`
     每个插件的文本表（任务名就是 FULL 里的字符串 ID 在这里查；
     ★ DLC 的名字**不在**基础游戏的表里 —— 这是 DLC 支持最容易漏的一步）

数据来源（都在游戏安装目录里，本脚本只读、只解包）：

  master            字符串所在 ba2                     说明
  Starfield.esm     Starfield - Localization.ba2       基础游戏
  ShatteredSpace.esm ShatteredSpace - Main02.ba2       破碎空间（官方 DLC）
  SFBGS00D.esm      SFBGS00D - Main.ba2                自由航道更新（地球舰队的前置 master）
  SFBGS050.esm      SFBGS050 - Main.ba2                地球舰队（官方 DLC）

用法：
    python tools/esm/fetch_sources.py                 # 只补缺失的（秒级）
    python tools/esm/fetch_sources.py --force         # 全部重新导出
    python tools/esm/fetch_sources.py --list          # 只看现状，不做任何事
"""
from __future__ import annotations

import argparse
import mmap
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "re"))
import quest_dump  # noqa: E402
from ba2list import open_ba2, extract_entry  # noqa: E402  （tools/re/ba2list.py，mmap 读 ba2）

DEFAULT_DATA = r"D:\SteamLibrary\steamapps\common\Starfield\Data"

# (esm 文件, 字符串所在 ba2, 说明)
SOURCES: list[tuple[str, str, str]] = [
    ("Starfield.esm", "Starfield - Localization.ba2", "基础游戏"),
    ("ShatteredSpace.esm", "ShatteredSpace - Main02.ba2", "破碎空间（官方 DLC）"),
    ("SFBGS00D.esm", "SFBGS00D - Main.ba2", "自由航道更新（地球舰队的前置 master）"),
    ("SFBGS050.esm", "SFBGS050 - Main.ba2", "地球舰队（官方 DLC）"),
]
LANGS = ("en", "zhhans")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default=DEFAULT_DATA)
    ap.add_argument("--strings-dir", default="ref/strings/strings")
    ap.add_argument("--quests", default="ref/quests_all.json")
    ap.add_argument("--force", action="store_true", help="全部重新导出")
    ap.add_argument("--list", action="store_true", help="只看现状")
    a = ap.parse_args()

    data = Path(a.data)
    strings_dir = Path(a.strings_dir)
    quests_out = Path(a.quests)
    strings_dir.mkdir(parents=True, exist_ok=True)

    missing_esm: list[str] = []
    for esm, ba2, note in SOURCES:
        if not (data / esm).exists():
            missing_esm.append(esm)
        print(f"  {esm:20s} {note}　字符串在 {ba2}")

    # --- 1. 字符串表 ---
    todo_strings: list[tuple[Path, str, str, tuple[str, ...]]] = []
    for esm, ba2, _note in SOURCES:
        if not (data / esm).exists():
            print(f"跳过 {esm}：游戏目录里没有这个文件（没装这个 DLC）")
            continue
        key = Path(esm).stem.lower()
        wanted = tuple(f"strings/{key}_{lang}.strings" for lang in LANGS)
        targets = [strings_dir / Path(w).name for w in wanted]
        if a.force or any(not t.exists() for t in targets):
            todo_strings.append((data / ba2, key, esm, wanted))
        else:
            print(f"  {esm}: 字符串已就绪（{', '.join(t.name for t in targets)}）")

    if a.list:
        print(f"\n（--list：没有改动任何文件）")
        return 0

    for ba2, key, esm, wanted in todo_strings:
        print(f"从 {ba2.name} 抽取 {key}_*.strings ...")
        with open_ba2(ba2) as archive:
            for name in wanted:
                dest = strings_dir / Path(name).name
                size = extract_entry(archive, name, dest)
                if size is None:
                    print(f"  !! {ba2.name} 里没有 {name} —— {esm} 的任务名会取不到")
                else:
                    print(f"  {dest.name}（{size} B）")

    # --- 2. 任务导出 ---
    esms = [data / esm for esm, _b, _n in SOURCES if (data / esm).exists()]
    if not esms:
        print("游戏目录里一个 master 都没有 —— 检查 --data 路径")
        return 1

    if quests_out.exists() and not a.force:
        print(f"任务导出已存在：{quests_out}（要重做加 --force）")
        return 0

    quests = []
    for path in esms:
        buf = path.read_bytes()
        meta = quest_dump.read_tes4(buf)
        meta["file"] = path.name
        n0 = len(quests)
        for formid, flags, payload in quest_dump.walk_quests(buf):
            quests.append(quest_dump.parse_quest(formid, flags, payload, meta))
        print(f"  {path.name}: QUST {len(quests) - n0} 条（master={meta['masters']}，"
              f"自己的记录前缀=0x{meta['self_index']:02X}）")
    quests_out.parent.mkdir(parents=True, exist_ok=True)
    import json
    quests_out.write_text(json.dumps(quests, indent=1), encoding="utf-8")
    print(f"wrote {quests_out}（{quests_out.stat().st_size} B / {len(quests)} 条）")
    if missing_esm:
        print(f"注意：这些 master 不在游戏目录里，本次没有导出它们的任务：{missing_esm}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
