"""docs/99 头部瘦身（第 140 轮）：把「第 137~43 轮」的旧速查块压成速查行（原文迁 docs/91 附录）。

为什么：docs/99 已 113336 B —— 玩家要求单文件 ≤ 100 KB，且头部逐轮累积的旧速查块
（第 133~135 / 132~117 / 116~96 / 95~61 / 60~43）细节早已在 `docs/15` 与
`docs/91~98` 历史文件里，属于可压缩内容。

用法：python tools/docs/trim_99_header.py          # 干跑
      python tools/docs/trim_99_header.py --write  # 真写
"""
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
PROGRESS = ROOT / "docs/99-当前项目进度.md"
HISTORY = ROOT / "docs/91-历史轮次记录（第120~124轮）.md"

BEGIN = "> 更早：2026-09-23（**第 137 轮"
END = "## 一、当前状态"

COMPACT = """> 更早（第 137~133 轮，速查 —— 明细 = `docs/15` 十三节 / 十三·补三 / 十三·补四）：
> **137** P3-b 落地（完整描述文案迁移 / watchdog / ini `[UI] UiMode=swf|auto|inject` 默认 auto；
>   注入层产品路径**发布构建也编译**，`swf` 档行为逐字节不变；DLL 1160704 B / verify 824 行）；
> **136** 第 135 轮修复产物复跑 4/4 + **眼睛达成** ⇒ P3-a 完全收口（`InjectCtx::list` 接线生效）；
> **135** 复跑 3/4 + 第二处产品级缺陷（`ctx.list = list;` + 上下文自检）；**134** 数据生命周期
> 解耦（notOurs 不再清 `g_pending.quests`）；**133** P3-a 落地（`SAQ_UiInject.{h,cpp}` + `ui.inject`）。
>
> 更早（第 132~117 轮，速查）：**132/131/130** P2 会话全 PASS + 探针 v4（`ui.research4` +
> `CreateObject` 回调劫持）/ **129** 功能迁移评估 / **128** operator 二期 / **127** HUD 提示时机
> 修复 + P2 双收口 + 0.1.15 包 / **126** 43/43 全 PASS / **125** 路线 D 冲突检测 /
> **124~120** P2 眼睛达成 · 复跑 · 首跑（缺 `aObjectives` 真因）· P2 落地 · 42/42 /
> **119~117** 探针 v2 + UI 注入研究落地。
>
> 更早（第 116~96 轮，速查）：DLC 链式三期 + 可重复任务（`docs/11`）+ 任务专属图标 +
> 日志上限可配（`[Log] MaxSizeMB`）+ 追踪者联盟 + 引导质量 2.0 + operator 全量产品化 +
> 覆盖面复盘 + 0.1.10~0.1.14 包。
>
> 更早（第 95~61 轮，速查）：`plan_regex_audit` + 判据定稿 + 「（不可导航）」前缀 +
> 进度门槛 OR 组（`orBit`）+ operator 全解 + 驱动器 **v70** + 同伴条目文案 + 地球地标 +
> 入口第二形态（可重复 NPC）+ DLC INFO 门槛。
>
> 更早（第 60~43 轮，速查）：分诊探针 `ev=`/`btn=` + 星图由脚本**轮询节拍**打开 +
> 引导候选池 + 结果码 5 / INFO 门槛 + 引擎内 harness + `stamp=` 指纹 + 0.1.1 包。
>
> 明细/复盘：`docs/91`（120~124 及补）/ `docs/93`（106~119）/ `docs/95`（43~60 等）/
> `docs/96`（35~40）/ `docs/97`（53~55 等）/ `docs/98`（9~16）/ `docs/11` / `docs/06`。
> （第 140 轮瘦身：被压缩的原始速查块原文见 `docs/91` 末尾附录。）
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
    hist += ("\n\n---\n\n# 附录：docs/99 头部「第 137~43 轮速查块」原文"
             "（2026-09-23 第 140 轮 docs/99 瘦身迁移）\n\n" + "".join(block).rstrip() + "\n")
    HISTORY.write_text(hist, encoding="utf-8")
    print(f"已写：{PROGRESS.name}（{PROGRESS.stat().st_size} B）/ "
          f"{HISTORY.name}（{HISTORY.stat().st_size} B）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
