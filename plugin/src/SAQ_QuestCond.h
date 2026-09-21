#pragma once

// ============================================================================
//  进度门槛求值（第 35 轮）—— 需求：「游戏进度还不能让玩家接到 ⇒ 不显示」
//
//  数据（生成物 SAQ_QuestTable.h 里的 kQuestConds[]）：任务的**记录级条件（CTDA）**
//  中「引用别的任务」的进度检查，只收：
//      GetQuestRunning / GetQuestCompleted / GetStageDone（等于比较、Run On=Subject）
//  提取规则与「为什么自引用条件不算」见 tools/esm/analyze_ctda.py 头注释。
//
//  求值是**保守**的：任何一步失败（目标任务取不到 / 状态读不了 / 引擎函数不可用）
//  都返回 kUnknown ⇒ 调用方**不做条件过滤**（宁可多显示，不可误藏真任务）。
//
//  引擎函数：「stage 是否完成」= Starfield.exe 的 0xD0DBD0（bool __fastcall(TESQuest*, u16)）——
//  Papyrus `Quest.IsStageDone` 的包装（0x20CB530）内部就 `call` 它；判据（stage 哈希表
//  0x1A0/0x1AC + stage 对象 +0x12 的 done 位）来自第 35 轮反汇编，见 docs/08。
//  调用前做 9 字节特征校验（换游戏版本后特征不符 ⇒ 不用它，返回 kUnknown）。
// ============================================================================

#include <cstdint>
#include <string>

#include "SAQ_Decision.h"   // ★ 第 64 轮（大项 K）：三态 / 聚合结果类型来自离线层

namespace SAQ
{
	// ★★ 第 64 轮（大项 K）：三态枚举与求值结果类型移到**离线层**（SAQ_Decision.h）——
	//   「一串三态怎么变成显示 / 隐藏 / 放行」的**聚合**语义在那里被单元测试钉死
	//   （plugin/tests/SAQ_DecisionTests.cpp 的真值表 / 组合矩阵）；
	//   本文件只负责**逐条查引擎**（LookupByID / IsStageDone / 读运行时状态）。
	using CondVerdict = Decision::CondVerdict;
	using CondEvalResult = Decision::GateDecision;

	// a_condBegin / a_condCount 来自 StaticQuestInfo（kQuestConds[] 的切片）。
	// 只在主线程调用（读引擎对象）。失败不清空缓存，无副作用。
	CondEvalResult EvaluateProgressGates(std::uint32_t a_condBegin, std::uint8_t a_condCount);

	// ★★ 大项 D（第 48 轮）：INFO 门槛求值 —— **对话侧**进度条件（数据见
	// SAQ_QuestTable.h 的 kInfoGroups / kInfoConds，生成链见 docs/08）。
	//
	// a_groupBegin / a_groupCount 来自 StaticQuestInfo（kInfoGroups[] 的切片）；
	// 每个 group 再切片到 kInfoConds[] ——「一条对话 = 一组条件（AND）」。
	//
	// 语义（保守，误藏最小化）：
	//   * 一条对话只要有**一条「已知为假」**的条件 ⇒ 这条对话不可用；
	//   * **全部对话都不可用** ⇒ kFail（进度没到 ⇒ 隐藏）；
	//   * 任何一条对话「没有已知为假的条件」（条件全真 / 有不可判定项 / 求值不了）
	//     ⇒ kPass（可能可用 ⇒ 显示）；
	//   * 切片越界等结构性异常 ⇒ kUnknown（放行）。
	// 设计依据（为什么只收「入口类 + 中性类」对话、为什么忽略无事件条件的对话）
	// 见 tools/esm/analyze_info_gates.py 头注释与 docs/08。
	// ★ 第 64 轮（大项 K）：本函数只做「逐组求值」（组内短路），**组间聚合**在
	//   Decision::DecideInfoGates（离线层，有单测）。
	CondEvalResult EvaluateInfoGates(std::uint32_t a_groupBegin, std::uint8_t a_groupCount);

	// ★★ 第 67 轮：**任务链门槛**求值 —— 「编号任务链」的启动边（数据见
	//   SAQ_QuestTable.h 的 kChainGates，生成器 tools/esm/gen_quest_chain.py：
	//   从官方 Papyrus 源码里挖出「上一个任务的收尾 stage 启动了下一个任务」的边）。
	//
	//   a_begin / a_count 来自 StaticQuestInfo 的 chainBegin / chainCount。
	//   每条边只查一次引擎：**前置任务的该 stage 是否已完成**（IsStageDone）。
	//
	//   语义（边之间是「或」，聚合在 Decision::DecideChainGates）：
	//     * 任一条边的 stage 已完成 ⇒ kPass（放行）；
	//     * 全部边都未完成 ⇒ kFail（进度没到 ⇒ 隐藏 —— 「菜鸟觐见」在「深藏不露」没做之前不显示）；
	//     * 前置任务取不到 / 求值器不可用 ⇒ kUnknown（放行，保守）。
	CondEvalResult EvaluateChainGates(std::uint32_t a_edgeBegin, std::uint8_t a_edgeCount);
}
