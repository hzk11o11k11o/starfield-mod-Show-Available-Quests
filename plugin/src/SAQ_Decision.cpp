// ============================================================================
//  SAQ_Decision.cpp —— 决策纯函数实现（第 64 轮 · 大项 K）
//
//  ★ 本文件（与 SAQ_Decision.h）不 include 任何 RE / SFSE / PCH 头 ——
//    `plugin/tests` 的独立测试 target 直接编译它（不链接 commonlibsf）。
//  ★ 这里的每个分支都必须与「抽取前的原始实现」逐字一致：
//    改行为的正确顺序 = 先改纯函数 + 单测（会 FAIL）→ 再改调用点。
//    对照（抽取前 → 抽取后）：
//      DeriveRuntimeFlags      ← SAQ_QuestState.cpp::ReadQuestRuntimeState 的位推导
//      DecideRuntimeFilter     ← SAQ.cpp::CollectAvailableQuests 的「只挡已完成」
//      RecognizedPct / 安全阀   ← 同函数的识别率安全阀
//      DecideProgressGates     ← SAQ_QuestCond.cpp::EvaluateProgressGates
//      DecideInfoGates         ← SAQ_QuestCond.cpp::EvaluateInfoGates
//      PickCandidate           ← SAQ.cpp::PickGuideCandidate（去引擎查询后）
//      AllCandidatesNonPersistent ← SAQ.cpp 同名函数
//      DecideGuideRecalc       ← SAQ.cpp::UpdateQuestGuideTarget 的判据部分
//      PassesTestFilter        ← SAQ.cpp::PassesTestFilter（换成结构体输入）
// ============================================================================

#include "SAQ_Decision.h"

namespace SAQ::Decision
{
	// ---------------------------------------------------------------- 1. 状态推导

	RuntimeFlags DeriveRuntimeFlags(const RawQuestFields& a_raw)
	{
		RuntimeFlags f;
		f.started = (a_raw.flags & kFlagStarted) != 0;
		f.completed = (a_raw.flags & kFlagCompleted) != 0;
		f.stopping = (a_raw.flags & kFlagStopping) != 0;
		f.active = (a_raw.flags & kFlagActive) != 0;
		// IsRunning 的完整判据（原 SAQ_QuestState.cpp 第 87 行）：
		f.running = f.started && !f.stopping && a_raw.startPending == 0 && a_raw.stopFlag == 0;
		return f;
	}

	// ---------------------------------------------------------------- 2. 运行时过滤

	bool IsCompletedConfirmed(const RuntimeFlags& a_flags, bool a_vtableKnown)
	{
		// 原判据（SAQ.cpp 两处）：`state.completed && state.vtableKnown`。
		return a_flags.completed && a_vtableKnown;
	}

	RuntimeFilterVerdict DecideRuntimeFilter(const RuntimeFlags& a_flags, bool a_vtableKnown)
	{
		// 「已开始」不挡 —— 第 11 轮实证：引擎会把玩家仍能接的任务提前置 running。
		return IsCompletedConfirmed(a_flags, a_vtableKnown) ? RuntimeFilterVerdict::kHideCompleted
														   : RuntimeFilterVerdict::kKeep;
	}

	bool RuntimeFilterApplied(unsigned a_recognizedPct)
	{
		return a_recognizedPct >= kMinRecognizedPct;
	}

	unsigned RecognizedPct(std::size_t a_recognized, std::size_t a_live)
	{
		// 原实现：live == 0 ⇒ 100（没有可判定的 ⇒ 不因安全阀而放弃过滤）
		return a_live == 0 ? 100u
						   : static_cast<unsigned>(a_recognized * 100 / a_live);
	}

	// ---------------------------------------------------------------- 3. 条件门槛

	GateDecision DecideProgressGates(std::span<const CondCheck> a_conds,
		std::uint32_t a_begin, std::uint8_t a_count)
	{
		GateDecision out;
		if (a_count == 0) {
			return out;  // kNoGates：这条任务没有门槛
		}
		// 越界检查（与 SAQ_QuestCond.cpp 一致；`||` 短路防止无符号下溢）
		const auto total = a_conds.size();
		if (a_begin > total || a_count > total - a_begin) {
			out.verdict = CondVerdict::kUnknown;
			out.detail = "门槛切片越界";
			return out;
		}

		for (std::size_t i = 0; i < a_count; ++i) {
			const auto& c = a_conds[a_begin + i];
			if (c.verdict != CondVerdict::kPass) {
				// kFail = 进度没到；kUnknown = 求值不了 ⇒ 放行（原样带回结论与说明）
				out.verdict = c.verdict;
				out.detail = c.detail;
				return out;
			}
		}
		out.verdict = CondVerdict::kPass;
		return out;
	}

	GateDecision DecideInfoGates(std::span<const InfoGroupEval> a_groups)
	{
		GateDecision out;
		if (a_groups.empty()) {
			return out;  // kNoGates
		}

		std::string firstFail;  // 跨组第一条非空的「已知为假」说明（隐藏时给日志）
		for (const auto& g : a_groups) {
			// 与抽取前一致：越界检查发生在**遍历到该组时**（前一组已 kPass 返回的话，
			// 后面的越界根本不会被检查 —— 这是有意的保守短路，别"顺手修"）。
			if (!g.inRange) {
				out.verdict = CondVerdict::kUnknown;
				out.detail = "INFO 条件切片越界";
				return out;
			}
			if (!g.hasKnownFalse) {
				// 这一条对话「没有已知为假的条件」⇒ 可能可用 ⇒ 这条任务不隐藏。
				out.verdict = CondVerdict::kPass;
				return out;
			}
			if (firstFail.empty()) {
				firstFail = g.firstFail;
			}
		}

		// 全部对话都至少有「一条已知为假」的条件 ⇒ 进度没到。
		out.verdict = CondVerdict::kFail;
		out.detail = firstFail.empty() ? "全部对话的条件都为假" : firstFail;
		return out;
	}

	GateDecision DecideChainGates(std::span<const CondCheck> a_edges)
	{
		GateDecision out;
		if (a_edges.empty()) {
			return out;  // kNoGates：不是链式后续（不做链式过滤）
		}

		// 边之间是「或」：先看有没有已经触发的前置（有 ⇒ 放行）。
		std::string firstFail;
		std::string firstUnknown;
		for (const auto& e : a_edges) {
			if (e.verdict == CondVerdict::kPass) {
				out.verdict = CondVerdict::kPass;
				return out;
			}
			if (e.verdict == CondVerdict::kUnknown) {
				if (firstUnknown.empty()) {
					firstUnknown = e.detail;
				}
			} else if (firstFail.empty()) {
				firstFail = e.detail;
			}
		}

		// 没有已触发的边：只要有求值不了的边 ⇒ 放行（保守 —— 别因为取不到前置就隐藏）。
		if (!firstUnknown.empty()) {
			out.verdict = CondVerdict::kUnknown;
			out.detail = firstUnknown;
			return out;
		}

		// 全部边都「已知未触发」⇒ 进度没到 ⇒ 隐藏。
		out.verdict = CondVerdict::kFail;
		out.detail = firstFail.empty() ? "全部链式前置都还没到" : firstFail;
		return out;
	}

	// ---------------------------------------------------------------- 4. 候选池

	CandidatePick PickCandidate(std::span<const bool> a_alive)
	{
		CandidatePick out;
		for (std::size_t i = 0; i < a_alive.size(); ++i) {
			if (a_alive[i]) {
				out.index = static_cast<std::uint8_t>(i);
				out.anyAlive = true;
				return out;
			}
		}
		return out;  // 空表 / 全不可得 ⇒ { 0, false }
	}

	bool AllCandidatesNonPersistent(std::span<const std::uint8_t> a_candFlags)
	{
		if (a_candFlags.empty()) {
			return false;  // 没有目标：那是「暂无导航目标」，与「需要靠近」是两回事
		}
		for (const auto flags : a_candFlags) {
			if ((flags & kCandidateFlagPersistent) != 0) {
				return false;  // 有任何一个常驻（或槽位异常 —— 调用方按常驻传入）：保守判 false
			}
		}
		return true;
	}

	GuideRecalcAction DecideGuideRecalc(bool a_anyAlive, std::uint8_t a_currentIndex,
		std::uint8_t a_bestIndex, bool a_observing, bool a_observeElapsed)
	{
		// 原判据（SAQ.cpp::UpdateQuestGuideTarget）：
		//   currentAlive = anyAlive && best <= current ⇔ 当前候选此刻取得到
		const bool currentAlive = a_anyAlive && a_bestIndex <= a_currentIndex;
		if (!currentAlive) {
			if (!a_observing) {
				return GuideRecalcAction::kBeginObserve;  // 记观察起点（这一拍必定保持）
			}
			if (!a_anyAlive) {
				return GuideRecalcAction::kHoldObserving;  // 没有任何可降级的目标 ⇒ 永远保持
			}
			if (!a_observeElapsed) {
				return GuideRecalcAction::kHoldObserving;  // 观察期未满 ⇒ 通道保持不动
			}
			return GuideRecalcAction::kSwitchDowngrade;  // 观察期满仍取不到 ⇒ 降级
		}
		// 当前候选可得：
		if (a_observing) {
			// 恢复可得 ⇒ 清观察（+ 日志）；若 best 更优则**同时**升级（原实现是顺序两条）
			return a_bestIndex < a_currentIndex ? GuideRecalcAction::kEndObserveSwitch
												: GuideRecalcAction::kEndObserve;
		}
		if (a_bestIndex < a_currentIndex) {
			return GuideRecalcAction::kSwitchUpgrade;  // 升级立即执行
		}
		return GuideRecalcAction::kHoldIdle;  // 已是最优可得的
	}

	// ---------------------------------------------------------------- 5. 测试过滤

	bool PassesTestFilter(int a_mode, const TestFilterInput& a_in)
	{
		switch (a_mode) {
		case 1:
			return a_in.hasTarget;  // 只显示「有引导目标」
		case 2:
			return !a_in.hasTarget;  // 只显示「没有引导目标」
		case 3:
			return a_in.isDlc;  // 只显示 DLC
		case 4:
			return a_in.hasTarget && a_in.hasNamedPlace;  // 有目标 + 有具名地点
		case 6:
			return a_in.needsApproach;  // 「需要靠近」的那一类
		default:
			return true;  // 0 / 未知值 = 不过滤
			// 模式 5 不在这里处理：它在 CollectAvailableQuests 里让整段任务循环不跑。
		}
	}
}
