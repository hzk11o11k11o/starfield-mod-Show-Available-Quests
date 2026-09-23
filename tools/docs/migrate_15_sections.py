"""docs/15 瘦身：把最早的研究阶段（九 ~ 十·补，第 117~127 轮）迁到 docs/90（第 140 轮）。

为什么：玩家要求「单个文档不得超过 100 KB」。docs/15 已 104290 B —— 继续加节必然超。
迁走的部分是**研究期的实测判读**（问题已收口：探针 v2/v3 结论已进 11.x 设计），
保留在 docs/90（它本来就是第 117 轮初期取证的迁移目标）供追溯。

用法：python tools/docs/migrate_15_sections.py          # 干跑（只打印边界）
      python tools/docs/migrate_15_sections.py --write  # 真写
"""
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
SRC = ROOT / "docs/15-无SWF覆盖的UI注入研究.md"
DST = ROOT / "docs/90-历史记录（UI注入研究 第117轮初期取证）.md"

BEGIN = "## 九、本轮产物（第 117 轮已落地）与待实机判读"
END = "## 十一、功能迁移评估"


def main() -> int:
    write = "--write" in sys.argv
    lines = SRC.read_text(encoding="utf-8").splitlines(keepends=True)
    bi = next(i for i, l in enumerate(lines) if l.startswith(BEGIN))
    ei = next(i for i, l in enumerate(lines) if l.startswith(END))
    block = lines[bi:ei]
    print(f"迁移区段：第 {bi + 1} ~ {ei} 行（{len(block)} 行，"
          f"{sum(len(b.encode('utf-8')) for b in block)} B）")
    print(f"  起：{block[0].rstrip()}")
    print(f"  止：{block[-1].rstrip()}")
    if not write:
        return 0

    pointer = (
        "## 九 ~ 十·补（研究产物 / 探针实测判读 / 路线 D）—— 已迁 `docs/90`\n"
        "\n"
        "（第 140 轮瘦身：这一段的结论已全部收进下面的 11.x 设计与十三节 —— 原始记录\n"
        " 迁到 `docs/90-历史记录（UI注入研究 第117轮初期取证）.md` 末尾，便于追溯。）\n"
        "\n"
    )
    SRC.write_text("".join(lines[:bi]) + pointer + "".join(lines[ei:]), encoding="utf-8")

    dst_old = DST.read_text(encoding="utf-8").rstrip() + "\n"
    dst_new = (dst_old + "\n\n---\n\n"
               "# 迁入：docs/15 第九 ~ 十·补节（第 117~127 轮 · 2026-09-23 第 140 轮迁移）\n\n"
               + "".join(block).rstrip() + "\n")
    DST.write_text(dst_new, encoding="utf-8")
    print(f"已写：{SRC.name}（{SRC.stat().st_size} B）/ {DST.name}（{DST.stat().st_size} B）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
