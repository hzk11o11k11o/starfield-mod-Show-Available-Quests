#!/usr/bin/env python3
"""run_verify.py - 可靠跑 verify_saq_build.py（子进程捕获 + 正确编码解码）。

为什么需要它（第 106 轮踩坑）：在 PowerShell 里 `python tools/ui/verify_saq_build.py *> log`
有两个坑 ——
  ① PowerShell 管道的编码可能把中文输出搅成乱码（按 UTF-8 解码会失败/错字），
     用 `Select-String` 过滤中文更是匹配不到；
  ② **verify 自身出错时曾静默中断**（第 106 轮一处 `.encode()` 类型错误 ⇒ 后续检查
     全不跑，但输出看起来"正常结束"）—— 所以跑完必须看「MISS 数量 + 是否有 Traceback」，
     不能只看退出码。

本工具：子进程跑 verify → 自动尝试 UTF-8/GBK 解码 → 打印 MISS 行、Traceback、
摘要行（「全部通过 / 存在缺失」）与退出码。

用法：
    python tools/ui/run_verify.py                # 默认模式
    python tools/ui/run_verify.py --release      # 发布模式（转为 verify 的参数）
"""
from __future__ import annotations
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

args = sys.argv[1:]
p = subprocess.run([sys.executable, str(ROOT / "tools/ui/verify_saq_build.py"), *args],
                   cwd=str(ROOT), capture_output=True)
raw = p.stdout + p.stderr
out = None
for enc in ("utf-8", "gbk"):
    try:
        out = raw.decode(enc)
        break
    except UnicodeDecodeError:
        continue
if out is None:
    out = raw.decode("utf-8", "replace")

lines = out.splitlines()
miss = [x for x in lines if x.startswith("MISS")]
tb = any("Traceback" in x for x in lines)
tail = [x for x in lines if ("全部通过" in x or "存在缺失" in x)]

print(f"输出 {len(lines)} 行；exit={p.returncode}")
print(f"MISS {len(miss)} 条" + ("；★ 有 Traceback（verify 崩了，检查不完整）" if tb else ""))
for x in miss:
    print("  " + x)
for x in tail:
    print("  " + x)
if tb:
    print("--- Traceback 尾部 ---")
    for x in lines[-15:]:
        print("  " + x)
sys.exit(p.returncode)
