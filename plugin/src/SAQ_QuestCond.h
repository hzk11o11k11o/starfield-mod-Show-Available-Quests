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
#include <vector>

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
	// 每个 group 再切片到 kInfoConds[] ——「一条对话 = 一组条件」：
	//   ★ 第 106 轮（operator 全量产品化）：组内 = 无 OR 位的条件相互 AND、
	//   OR 组（自带 OR 位那条起、含关闭组的第一条无 OR 位条件）组内相互 OR、
	//   组作为整体参与 AND —— 复用 Decision::DecideProgressGates（与记录级
	//   同款引擎语义，见 docs/08 4.3）。
	//
	// 语义（保守，误藏最小化）：
	//   * 一条对话的条件组**确定为假** ⇒ 这条对话不可用；
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

#if SAQ_WITH_HARNESS
	// ★★★ 第 101 轮补丁（harness 只读探针 `quest.probe`）：把任意 (quest, stage) 的
	//   IsStageDone 与运行时状态用**一行文本**报出来 —— 走的是**与链式 / 进度门槛完全相同**
	//   的函数与调用路径（同一份 9 字节特征校验 + 同一个 CallStageDoneChecked），
	//   不是另写一套查询。
	//
	//   为什么需要它（第 101 轮 `r101_dlc_chain2_pass` 实测 FAIL 的定调用）：
	//   推 `MQ03@4000` 后链式判定与「已开始」**零变化**（「另一边」仍在「链式没到」名单），
	//   而 Papyrus 侧日志证明 `SetStage(SFBGS001_MQ03, 4000)` 调用成功（`=> 4000`）。
	//   现有证据无法区分这两件事 —— 这个探针就是那条判据：
	//     · stageDone(N)=0 ⇒ **写侧没生效**（引擎里 done 位始终为 0）⇒ 换用例构造；
	//     · stageDone(N)=1 而链式仍藏 ⇒ **读侧**没读到 ⇒ 查 IsStageDone 通道与判定链。
	//   同类先例：第 99 轮 `MQ01@10000`（「回执全成功但统计行逐字段一致」）。
	//   只读、无副作用、菜单开着也能跑（与 kGuideProbe 同款）。
	std::string ProbeQuestStages(std::uint32_t a_formID, const std::vector<std::uint16_t>& a_stages);

	// ★★★ 第 106 轮（operator 全量产品化 · harness 只读探针 `info.probe`）：
	//   把某条任务（参数 = **表内记录号**）的 INFO 门槛报告中**含 OR 位的对话组**
	//   逐组列出：`组[i]:<条件串>=真/假/未知` —— 组内求值走与产品**完全相同**的
	//   Decision::DecideProgressGates（同款 OR 组语义，见 docs/08 4.3），
	//   最后再报整任务的结论（EvaluateInfoGates 的三态）。
	//
	//   为什么需要它（用例怎么判读）：第 106 轮把 INFO 侧的 `== + OR 位` 条件
	//   纳入门槛（scan_info_gates.py 的 OR 组提取）—— 差异点是「这条对话**是否参与**
	//   判定」以及「OR 组里一条为真即组真」。用列表隐藏/显示做判据要构造 20+ 条
	//   对话全假的状态（不可达）；这个探针直接报「组求值」，A/B 两段可精确断言：
	//     · 112/114 都没完成 ⇒ `组[0]:112[OR]+114[OR]=假`；
	//     · 推 112 之后 ⇒ 同一条组变 `=真`（旧实现只提取无 OR 位的条件 ⇒ 组不存在）。
	//   只读、无副作用、菜单开着也能跑（与 kQuestProbe 同款）。
	std::string ProbeInfoGates(std::uint32_t a_localFormID);
#endif  // SAQ_WITH_HARNESS
}
