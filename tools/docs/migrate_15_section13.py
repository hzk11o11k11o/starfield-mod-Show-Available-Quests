"""docs/15 瘦身其三（第 144 轮）：把「十三、P3-a 产品化 PoC」（第 133 轮）迁到 docs/91。

为什么：玩家要求「单个文档不得超过 100 KB」。docs/15 在补完 P2 判读与 0.1.16 打包记录后
到 102811 B —— 继续留大段已收口的研究记录不合理。P3-a 的结论已全部收进产品代码
（SAQ_UiInject.cpp）与十四/十五节的收口记录，原样迁入 docs/91 供追溯。

用法：python tools/docs/migrate_15_section13.py          # 干跑（只打印边界）
      python tools/docs/migrate_15_section13.py --write  # 真写
"""
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
SRC = ROOT / "docs/15-无SWF覆盖的UI注入研究.md"
DST = ROOT / "docs/91-历史轮次记录（第120~124轮）.md"

BEGIN = "## 十三、P3-a 产品化 PoC"
END = "## 十四、P4 交互接管"


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
        "## 十三、P3-a 产品化 PoC（第 133 轮）—— 已迁 `docs/91`\n"
        "\n"
        "（第 144 轮瘦身：P3-a 已完全收口 —— 判据见十四 / 十五节；原始记录（链路八步 /\n"
        " 新事实 / 判据）迁到 `docs/91-历史轮次记录（第120~124轮）.md` 末尾，便于追溯。）\n"
        "\n"
    )
    SRC.write_text("".join(lines[:bi]) + pointer + "".join(lines[ei:]), encoding="utf-8")

    dst_old = DST.read_text(encoding="utf-8").rstrip() + "\n"
    dst_new = (dst_old + "\n\n---\n\n"
               "# 迁入：docs/15 第十三节 · P3-a 产品化 PoC（第 133 轮 · 2026-09-23 第 144 轮迁移）\n\n"
               + "".join(block).rstrip() + "\n")
    DST.write_text(dst_new, encoding="utf-8")
    print(f"已写：{SRC.name}（{SRC.stat().st_size} B）/ {DST.name}（{DST.stat().st_size} B）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
