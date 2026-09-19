#!/usr/bin/env python3
"""Starfield.exe RTTI 类名扫描器。

用途：
    在 100MB+ 的主程序里找出「类名里带某个关键词」的 RTTI 类型描述符
    （`.?AV<Class>@@` 形式的字符串），用来确认引擎里到底有哪些相关类。
    这是「不靠猜」的第一步：只有确认了类名，才谈得上找它的 vtable / 函数。

用法：
    python tools/re/rtti.py scan                          # 关键词 scan
    python tools/re/rtti.py "highlight|outline"           # 正则
    python tools/re/rtti.py scanner --full                # 打印完整名字（不折叠命名空间）
    python tools/re/rtti.py "Scan" --list-file out.txt    # 输出到文件

说明：
    MSVC 的 RTTI 名是 `. ? A V <mangled> @@`：
      `.?AVFoo@Bar@@`      = class Bar::Foo
      `.?AVFoo@@`          = class Foo
      `.?AUBar@@`          = struct Bar（U = struct）
      `.?AV?$BSTArray@...@@` = 模板实例
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

EXE = Path(r"D:\SteamLibrary\steamapps\common\Starfield\Starfield.exe")

# RTTI 类型描述符只允许这些字符（mangled name 的字符集）
NAME_RE = re.compile(rb"\.\?(?:AV|AU|AW)([A-Za-z0-9_@$?<>:,\-*.\[\]]{0,160}?)@@")


def demangle(mangled: str) -> str:
    """把 `Foo@Bar@Baz` 还原成 `Baz::Bar::Foo`（MSVC 是反序的）。"""
    parts = [p for p in mangled.split("@") if p]
    parts.reverse()
    return "::".join(parts)


def scan(exe: Path):
    data = exe.read_bytes()
    names: dict[str, str] = {}
    for m in NAME_RE.finditer(data):
        raw = m.group(1).decode("ascii", "replace")
        if raw not in names:
            names[raw] = demangle(raw)
    return names


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("pattern", help="关键词或正则（大小写不敏感）")
    ap.add_argument("--exe", default=str(EXE))
    ap.add_argument("--full", action="store_true", help="打印完整命名空间路径")
    ap.add_argument("--list-file", default=None, help="把结果写到文件")
    ap.add_argument("--max", type=int, default=400)
    a = ap.parse_args()

    exe = Path(a.exe)
    if not exe.exists():
        print(f"找不到 {exe}")
        return 2

    names = scan(exe)
    print(f"RTTI 名总数: {len(names)}", file=sys.stderr)

    rx = re.compile(a.pattern, re.I)
    hits = []
    for raw, pretty in names.items():
        target = raw if a.full else pretty
        if rx.search(raw) or rx.search(pretty):
            hits.append((target, raw))
    hits.sort()

    lines = [h[0] for h in hits[: a.max]]
    text = "\n".join(lines)
    if a.list_file:
        Path(a.list_file).write_text(text, encoding="utf-8")
        print(f"写出 {len(lines)} 行 -> {a.list_file}", file=sys.stderr)
    else:
        print(text)
    if len(hits) > a.max:
        print(f"...(共 {len(hits)} 条，已截断到 {a.max})", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
