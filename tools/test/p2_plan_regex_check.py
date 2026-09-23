"""P2 计划 `assert.log` 正则**编译 + 样例匹配**自检（第 130 轮建立）。

为什么需要：断言正则由 DLL 在**解析期**编译（非法正则 ⇒ 该用例判 FAIL，不再退化成
「日志里没出现」的误导性超时 —— 第 68 轮），但那只在实机会话里才发生；本脚本在
离线阶段就把「正则合法 + 能匹配预期产品行」验一遍（与 `verify` 里的存在性检查互补：
verify 只看串在不在，不看它是不是合法正则、能不能匹配）。

用法：python tools/test/p2_plan_regex_check.py
"""
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
PLAN = ROOT / "tools/test/scenarios/SAQ_TestPlan_p2.txt"

# 探针 v4 两行产品日志的**样例形态**（字段/顺序照 SAQ_UI.cpp 的拼装顺序写死；
# 数值与文本用实测时不定的占位值，只为验证正则的「顺序 + 段同现」语义）。
SAMPLES = {
    "4a": (
        "界面研究探针4a Menu_mc=ok｜环境=(entryCount 1,mask 0xFFFFFFFF)｜"
        "读条目=ok（1 条,首条 0x0000006F:类型3:名=你的名字:字段8｜选中项=0x0000006F）｜"
        "语言=zh（中文样本 4 字）｜类通道=ok（BSUIDataManager）｜静态=ok（hasEventListener=false）｜"
        "订阅=ok｜读Data=fail（Data 是 protected trait —— 与 U1 同类边界）｜"
        "造对象=ok（三级 + 接线 UserEvents=1）｜"
        "接管=ok（回调收到 1 次 —— R 键可接管）｜注入=ok（entryCount 1→2）｜"
        "选中=ok（0x56780001）｜置灰=ok（不可导航=0，可导航=1）"
    ),
    "4b": (
        "界面研究探针4b Menu_mc=ok｜环境=(entryCount 2,mask 0x00000040)｜"
        "刷新=ok（竖条 Inactive→Active）｜文本=ok（SAQ-Mig-0）｜"
        "关菜单入口=ok（可调用=是；菜单仍在=是；返回 true，真关菜单留 P4）｜订阅回调=0 次"
    ),
    # ★★★ 第 133 轮（P3 产品化 PoC · docs/15 11.7）：`ui.inject` 产品行 ——
    # 字段/顺序照 SAQ_UiInject.cpp 的拼装顺序写死（快照在扩 tab 之前 —— 快照采的
    # 是引擎列表）；数值与任务名用实测时不定的占位值，只为验证「顺序 + 段同现」。
    "界面注入PoC": (
        "界面注入PoC Menu_mc=ok｜环境=(numTabs 7,entryCount 1,mask 0xFFFFFFFF,语言 zh)｜"
        "回ALL=ok（mask 0xFFFFFFFF,entryCount 1）｜快照=ok（1 条）｜扩tab=ok（7→8）｜"
        "监听=ok｜注入数据=ok（entryCount 1→206，期望 206）｜"
        "对账=ok（0x002C5401:超越极限｜可导航1）｜"
        "恢复=ok（切0 后 entryCount →1，期望 1）｜"
        "再注入=ok（entryCount →206，可重入）｜拦截=(3 次回调/2 注入/1 恢复)"
    ),
    # ★★ 第 137 轮（P3-b · UI 注入形态产品化）：`r137_product_inject` 的三条产品行 ——
    # 产品路径（UiMode=auto ⇒ 冲突环境自动激活注入；不依赖 harness 原语）。
    # 文本照 SAQ.cpp / SAQ_UiInject.cpp 的实际拼装写死；数值用占位值。
    "界面形态：UiMode=auto": (
        "界面形态：UiMode=auto（swf=只用 SWF 推送 / auto=SWF 优先、冲突时自动切注入 / "
        "inject=只用注入）"
    ),
    "界面注入：已激活": (
        #  ★★★ 第 143 轮（P5）：行尾 `指纹=ok`（结构指纹自检通过）—— r137 的断言
        #  含 `.*指纹=ok`，样例不带上它就匹配不到（离线自检会 MISS）。
        "界面注入：已激活（UiMode=auto，tab 7→8，条目 206，按键名=R，语言=zh，接管=ok，指纹=ok）"
    ),
    "菜单关闭：本轮为注入形态": (
        "菜单关闭：本轮为注入形态（已激活；watchdog 重放 0 次）"
    ),
    # ★★★ 第 140 轮（P4 交互接管 · docs/15 十四节）：`r140_interact_takeover` 的四条
    # 产品行 —— 文本照 SAQ_UiInject.cpp 的实际拼装写死；数值用占位值。
    # 标记串用「行首 + 段名」的子串，保证同时命中计划里的两条探针断言。
    "界面接管 .*": (
        "界面接管 Menu_mc=ok｜接管=ok（X=ok Y=ok｜接线 1/1｜激活监听=ok）｜"
        "分类=ok（我们 1｜原版 1｜无选中 1）｜"
        "触发=ok（子项 0x002C5401｜X 1 次／Y 1 次，dry-run：只验证接线不动作）｜"
        "激活=ok（派发=ok；回调 1 次／拦下 1 次 —— 原版处理器被 stopPropagation 挡住）｜"
        "真动作=0（dry-run 期望 0）｜引导请求=0"
    ),
    "界面接管按键": (
        "界面接管按键 选中=0x002C5401（ok）｜按键=X（调用 ok）｜回调=1 次｜"
        "引导=ok（0x002C5401）｜星图交接=已调用（原版「回游戏」原语）"
    ),
    "界面接管状态": (
        "界面接管状态 任务菜单=关｜星图=开｜注入=激活｜接管=已装｜当前引导=0x002C5401"
        "｜按压(X 1／Y 0／激活 0)｜拦下 0｜委托 0｜引导请求 1｜真动作 1"
    ),
    "星图：界面侧会自己关掉整个暂停菜单": (
        "星图：界面侧会自己关掉整个暂停菜单（新协议，不发 kHide）；"
        "星图由脚本在菜单关闭后的下一个轮询节拍打开｜引导任务=超越极限（0x002C5401）"
    ),
}


def main() -> int:
    text = PLAN.read_text(encoding="utf-8", errors="replace")
    patterns = [
        line.split("assert.log ", 1)[1].rsplit(" scope=", 1)[0].strip()
        for line in text.splitlines()
        if line.startswith("step = assert.log")
    ]
    bad = 0
    checked = 0
    for p in patterns:
        try:
            rx = re.compile(p)
        except re.error as e:  # noqa: PERF203
            print(f"非法   {p[:70]}…（{e}）")
            bad += 1
            continue
        for tag, sample in SAMPLES.items():
            if tag in p:
                checked += 1
                if rx.search(sample):
                    print(f"OK     {tag} 正则编译 + 样例匹配：{p[:60]}…")
                else:
                    print(f"MISS   {tag} 正则合法但**匹配不到样例**：{p}")
                    bad += 1
    print(f"—— 共 {len(patterns)} 条 assert 正则：编译全过（{checked} 条样例匹配已验）；问题 {bad} 条")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
