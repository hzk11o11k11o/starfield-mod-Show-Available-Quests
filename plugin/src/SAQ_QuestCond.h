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

namespace SAQ
{
	enum class CondVerdict : std::uint8_t
	{
		kNoGates = 0,  // 没有门槛（condCount == 0）⇒ 正常显示
		kPass,         // 有门槛且全部为真 ⇒ 显示
		kFail,         // 有门槛且有假（进度没到）⇒ 隐藏
		kUnknown,      // 求值不了 ⇒ 放行（保守）
	};

	struct CondEvalResult
	{
		CondVerdict verdict{ CondVerdict::kNoGates };
		std::string detail;  // kFail / kUnknown 时给日志的简短说明
	};

	// a_condBegin / a_condCount 来自 StaticQuestInfo（kQuestConds[] 的切片）。
	// 只在主线程调用（读引擎对象）。失败不清空缓存，无副作用。
	CondEvalResult EvaluateProgressGates(std::uint32_t a_condBegin, std::uint8_t a_condCount);
}
