#!/usr/bin/env python3
"""ctda_ops.py - CTDA 运算符折叠内核（第 128 轮 · **operator 二期**）。

背景（已解出的语义，出处都是实证，别改口味）：
  * 第 86 轮反汇编：CTDA type 是位域 —— **运算符 = type >> 5**（0..5 =
    `==` / `!=` / `>` / `>=` / `<` / `<=`）、**flags = type & 0x1F**
    （bit0 OR / bit1 别名 / bit2 GLOB / bit3 Pack Data / bit4 交换主客体）；
  * 第 87/106 轮：产品只用了「`==` + OR 位」这一子集，其余运算符/flags 一律放行；
  * 第 109 轮盘点：operator 二期**当时没有可产品化对象**（表内 0 条），只留了 tripwire；
  * 第 128 轮（本轮）：把**折叠规则**真正落地 —— 三个门槛函数
    （GetQuestRunning / GetQuestCompleted / GetStageDone）都返回 0/1 布尔，所以
    比较运算符在 cmp∈{0,1} 时可以**精确**折叠成一个静态期望值 `want ∈ {0,1}`，
    或在少数组合下退化成常量（恒真 / 恒假）。

真值表（value = 函数结果 ∈ {0,1}；cmp ∈ {0,1}；`.want` = 期望 value 等于它）：

    op==  : value == cmp   → want = (cmp == 1)
    op!=  : value != cmp   → want = (cmp == 0)          （取反）
    op>   : value >  cmp   → cmp==1 ⇒ **恒假**（常量）；cmp==0 ⇒ want = 1
    op>=  : value >= cmp   → cmp==0 ⇒ **恒真**（常量）；cmp==1 ⇒ want = 1
    op<   : value <  cmp   → cmp==0 ⇒ **恒假**（常量）；cmp==1 ⇒ want = 0
    op<=  : value <= cmp   → cmp==1 ⇒ **恒真**（常量）；cmp==0 ⇒ want = 0

常量 / 不可折叠的处置（组语义，保守 —— **绝不引入误藏**，与 docs/08 4.6 的推演一致）：

    * 独立条件（无 OR 位）：
        - 不可折叠（flags 非 OR / cmp∉{0,1} / 非进度类 …）⇒ 丢弃（放行）；
        - 恒真 ⇒ 丢弃（*无约束*）；恒假 ⇒ 丢弃（按「不可门槛」保守处理 = 放行）；
    * OR 组（带 OR 位那条起，到第一条无 OR 位的条件（含）或末尾；组内 OR、组整体 AND）：
        - 任一成员不可折叠 ⇒ **整组放弃**（第 106 轮既有纪律：不倒半组）；
        - 任一成员恒真 ⇒ **整组丢弃**（`A OR TRUE = TRUE` ⇒ 整组无约束）；
        - 任一成员恒假 ⇒ **整组放弃**（保守；精确语义本可只丢该条，但不为省事冒风险）。

运行时（DLL）**零改动**：`StaticCondGate.want` 只是生成期算好的期望值；
组结构（`orBit`）在保留的条件之间原样保留（折叠不删已有门槛的成员 ⇒ 边界不动）。

用法：
    python tools/esm/ctda_ops.py --self-test    # 真值表 + 组语义自检（离线，毫秒级）
"""
from __future__ import annotations

import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

#: 运算符编号 → 显示名（type >> 5；第 86 轮反汇编）
OPS = {0: "==", 1: "!=", 2: ">", 3: ">=", 4: "<", 5: "<="}

#: fold_operator 的两种结果形态（用元组表达，便于比较与断言）
WANT = "want"     # ("want", 0|1) —— 折叠成静态期望值
CONST = "const"   # ("const", True|False) —— 恒真 / 恒假


def fold_operator(op: int, cmp_value: float) -> tuple[str, int] | tuple[str, bool] | None:
    """把「(运算符, 比较值)」折叠成 `("want", 0|1)` / `("const", True|False)`。

    不可折叠（运算符越界 / cmp 不是 0 或 1）⇒ None。
    """
    if op not in OPS or cmp_value not in (0.0, 1.0):
        return None
    c = 1 if cmp_value == 1.0 else 0
    if op == 0:                       # ==
        return (WANT, c)
    if op == 1:                       # !=
        return (WANT, 1 - c)
    if op == 2:                       # >   （value > 1 永假 / value > 0 ⇒ value==1）
        return (CONST, False) if c == 1 else (WANT, 1)
    if op == 3:                       # >=  （value >= 0 永真 / value >= 1 ⇒ value==1）
        return (CONST, True) if c == 0 else (WANT, 1)
    if op == 4:                       # <   （value < 0 永假 / value < 1 ⇒ value==0）
        return (CONST, False) if c == 0 else (WANT, 0)
    if op == 5:                       # <=  （value <= 0 ⇒ value==0 / value <= 1 永真）
        return (WANT, 0) if c == 0 else (CONST, True)
    return None


def or_group_end(or_bits, start: int) -> int:
    """OR 组的终点（**不含**的下标）—— 引擎语义（docs/08 4.3）：

    组 = 从 `start`（必须带 OR 位）起，直到**第一条不带 OR 位的条件（含在组内）**
    或列表末尾。

    `or_bits[start]` 不是 True 时调用方语义错（这里按「单条独立条件」返回 start+1）。
    """
    n = len(or_bits)
    if start >= n or not or_bits[start]:
        return min(start + 1, n)
    j = start
    while j < n and or_bits[j]:
        j += 1
    return j + 1 if j < n else j     # j < n ⇒ 把关闭组的那条无 OR 位条件也含进来


def group_spans(or_bits) -> list[tuple[int, int]]:
    """把条件列表切成「独立条件 / OR 组」的区间（半开区间 `[start, end)`）。

    与 `assemble_gates` / `or_group_end` 用**同一套边界**（一条真相源）——
    提取侧（scan_info_gates.py / analyze_ctda.py）用它做组级诊断。
    """
    spans: list[tuple[int, int]] = []
    n = len(or_bits)
    i = 0
    while i < n:
        j = or_group_end(or_bits, i) if or_bits[i] else i + 1
        spans.append((i, j))
        i = j
    return spans


def assemble_gates(folds, or_bits) -> list[tuple[int, int]]:
    """把「逐条折叠结果 + OR 位」组装成门槛输出序列。

    输入：
      * `folds[i]` ∈ `("want", 0|1)` / `("const", True|False)` / `None`（不可门槛）；
      * `or_bits[i]` = 该条 CTDA 是否带 OR 位（type bit0）。

    返回：`[(下标, want), ...]` —— 需要作为门槛保留的条件（顺序与输入一致；
    `want` 只可能 0/1）。常量与不可折叠成员按上面的「常量 / 不可折叠的处置」处理。
    """
    out: list[tuple[int, int]] = []
    for start, end in group_spans(or_bits):
        if start + 1 == end:                     # 独立条件
            f = folds[start]
            if f and f[0] == WANT:
                out.append((start, int(f[1])))
            continue
        group = folds[start:end]                 # OR 组
        if all(g and g[0] == WANT for g in group):
            out.extend((start + k, int(g[1])) for k, g in enumerate(group))
        # 不可折叠 / 恒真 / 恒假 ⇒ 整组不产出门槛（放行或「无约束」，都不误藏）
    return out


# ============================================================================
#  自检（离线，毫秒级）—— 真值表 + 组语义（含 docs/08 4.6 里推演过的形状）
# ============================================================================

def _self_test() -> int:
    fails: list[str] = []

    def eq(got, want, what: str) -> None:
        if got != want:
            fails.append(f"{what}: got {got!r} want {want!r}")

    # ① 真值表（6 运算符 × cmp∈{0,1}）—— 逐条钉死
    table = {
        (0, 0.0): (WANT, 0), (0, 1.0): (WANT, 1),
        (1, 0.0): (WANT, 1), (1, 1.0): (WANT, 0),
        (2, 0.0): (WANT, 1), (2, 1.0): (CONST, False),
        (3, 0.0): (CONST, True), (3, 1.0): (WANT, 1),
        (4, 0.0): (CONST, False), (4, 1.0): (WANT, 0),
        (5, 0.0): (WANT, 0), (5, 1.0): (CONST, True),
    }
    for (op, cmpv), want in table.items():
        eq(fold_operator(op, cmpv), want, f"真值表 op={OPS[op]} cmp={cmpv}")

    # ② 不可折叠：运算符越界 / cmp 不是 0/1
    eq(fold_operator(6, 0.0), None, "真值表 op=6（越界）")
    eq(fold_operator(0, 2.0), None, "真值表 cmp=2.0")
    eq(fold_operator(1, -1.0), None, "真值表 cmp=-1.0")

    # ③ OR 组边界：组 = OR 位连续段 + 关闭组的第一条无 OR 位条件
    eq(or_group_end([True, True, False, True], 0), 3, "OR 组 [T,T,F,T] @0")
    eq(or_group_end([True, True, False, True], 3), 4, "OR 组 @3（列表末尾）")
    eq(or_group_end([True, True], 0), 2, "OR 组 [T,T] @0（末尾）")
    eq(or_group_end([False, True], 0), 1, "非组起点（单条）")
    eq(group_spans([False, True, True, False, True]), [(0, 1), (1, 4), (4, 5)],
       "区间切分（独立 / OR 组 / 独立）")

    # ④ 组装：与第 87/106 轮的既有数据形状等价（FFConstantZ06）
    #    [UC04==1, Z04==1(OR), Z05==1(OR)] ⇒ 三条全保留、want 全 1
    eq(assemble_gates([(WANT, 1), (WANT, 1), (WANT, 1)], [False, True, True]),
       [(0, 1), (1, 1), (2, 1)], "FFConstantZ06 形状（OR 组保留）")

    # ⑤ 折叠：`!=`（SFTER_CREW_EliteCrew_Delta 形状，第 109 轮盘点里的外键）
    eq(fold_operator(1, 1.0), (WANT, 0), "!= cmp=1（取反）")
    #    `>=` cmp=1（SFTER_CREW_EliteCrew_Delta 的另一条 / SFFL 形状）
    eq(fold_operator(3, 1.0), (WANT, 1), ">= cmp=1")

    # ⑥ 组语义里常量的处置
    eq(assemble_gates([(CONST, True)], [False]), [], "独立恒真 ⇒ 丢弃")
    eq(assemble_gates([(CONST, False)], [False]), [], "独立恒假 ⇒ 丢弃（放行）")
    eq(assemble_gates([None], [False]), [], "独立不可门槛 ⇒ 丢弃")
    eq(assemble_gates([(WANT, 1), (CONST, True)], [True, False]), [],
       "OR 组含恒真 ⇒ 整组丢弃（A OR TRUE = TRUE）")
    eq(assemble_gates([(WANT, 1), (CONST, False)], [True, False]), [],
       "OR 组含恒假 ⇒ 整组放弃")
    eq(assemble_gates([(WANT, 1), None], [True, False]), [],
       "OR 组含不可门槛 ⇒ 整组放弃")
    eq(assemble_gates([(WANT, 0), (WANT, 1), (WANT, 1)], [False, True, True]),
       [(0, 0), (1, 1), (2, 1)], "独立 + OR 组混排（顺序保持）")

    if fails:
        print(f"[ctda_ops] 自检 FAIL（{len(fails)} 项）：")
        for f in fails:
            print("  · " + f)
        return 1
    print("[ctda_ops] 自检 OK：真值表 12 例 + 不可折叠 3 例 + 组边界 5 例 + 组装 10 例。")
    return 0


def main() -> int:
    import argparse
    ap = argparse.ArgumentParser(description="CTDA 运算符折叠内核（operator 二期）")
    ap.add_argument("--self-test", action="store_true", help="真值表 + 组语义自检")
    a = ap.parse_args()
    if a.self_test:
        return _self_test()
    ap.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
