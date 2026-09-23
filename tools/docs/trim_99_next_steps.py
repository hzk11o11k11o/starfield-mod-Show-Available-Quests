"""docs/99 瘦身其二（第 140 轮）：把「十一、下一步」里第 117~132 轮的逐轮长块压成速查块。

为什么：这些块（UI 注入研究 → P3 全过程）的明细早已在 `docs/15` 与 `docs/90` / `docs/91`
里逐轮记录，留在进度文件里只占体积（玩家要求单文件 ≤ 100 KB）。

用法：python tools/docs/trim_99_next_steps.py          # 干跑
      python tools/docs/trim_99_next_steps.py --write  # 真写
"""
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
PROGRESS = ROOT / "docs/99-当前项目进度.md"
HISTORY = ROOT / "docs/91-历史轮次记录（第120~124轮）.md"

BEGIN = "0. ✅ **第 132 轮：P2 会话重跑收口"
END = "0. ✅ **第 87~116 轮的收口项与上传包记录"

COMPACT = """0. ✅ **第 117~132 轮（UI 注入研究 → P2 全过程）—— 速查**（逐轮明细已迁 `docs/15`
  与 `docs/90` / `docs/91`；第 140 轮瘦身，原文见 `docs/91` 末尾附录）：
  **132 / 131 / 130** P2 会话全 PASS + 探针 v4（U5 回调劫持 / U6 直读 / U7 就地刷新 /
  U8 语言判定 / U10 类通道）+ 两处探针修正（`[ud]` 数组接线 / 关菜单入口判据）；**129**
  功能迁移评估（注入可行 ⇒ 立项 P3）；**128** operator 二期；**127** HUD 提示时机修复 +
  P2 双收口 + 0.1.15 包；**126** 正常态 43/43 全 PASS；**125 起** 路线 D 冲突检测
  （`ProbeChannelIdentity` + 停推降噪 + HUD 提示 GLOB 0x80E）；**124~121** P2 眼睛达成 /
  复跑 / 首跑（注入缺 `aObjectives` 真因）/ P2 落地（探针 v3 + `build-saq.ps1 -P2`）；
  **120 / 118** 42-42 · 41-41 全 PASS；**119 / 117** 探针 v2（拦截 + `filterMask` 哨兵写 +
  `SetTabsData` 补测）+ UI 注入研究落地（能力边界 U0 ✅ / U1 ❌ / U3 ✅）。
"""


def main() -> int:
    write = "--write" in sys.argv
    lines = PROGRESS.read_text(encoding="utf-8").splitlines(keepends=True)
    bi = next(i for i, l in enumerate(lines) if l.startswith(BEGIN))
    ei = next(i for i, l in enumerate(lines) if l.startswith(END))
    block = lines[bi:ei]
    print(f"压缩区段：第 {bi + 1} ~ {ei} 行（{len(block)} 行，"
          f"{sum(len(b.encode('utf-8')) for b in block)} B）")
    if not write:
        return 0
    PROGRESS.write_text("".join(lines[:bi]) + COMPACT + "\n" + "".join(lines[ei:]),
                        encoding="utf-8")
    hist = HISTORY.read_text(encoding="utf-8").rstrip() + "\n"
    hist += ("\n\n---\n\n# 附录二：docs/99「十一、下一步」第 117~132 轮长块原文"
             "（2026-09-23 第 140 轮瘦身迁移）\n\n" + "".join(block).rstrip() + "\n")
    HISTORY.write_text(hist, encoding="utf-8")
    print(f"已写：{PROGRESS.name}（{PROGRESS.stat().st_size} B）/ "
          f"{HISTORY.name}（{HISTORY.stat().st_size} B）")
    print(f"进度文件是否 ≤ 100 KB：{'是' if PROGRESS.stat().st_size <= 102400 else '否'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
