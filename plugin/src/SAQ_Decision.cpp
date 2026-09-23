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
//      Utf8SafeCut             ← ★ 第 84 轮：SAQ_UI.cpp::EscapeForLog 的字节截断
//                                 （修「切在多字节字符中间 ⇒ 非法 UTF-8」）
//      DecideUiFingerprint     ← ★★★ 第 143 轮（P5）：SAQ_UiInject.cpp::ActivateForMenu
//                                 的结构指纹自检判据（原版菜单结构变了就不注入）
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

	RuntimeFilterVerdict DecideRuntimeFilter(const RuntimeFlags& a_flags, bool a_vtableKnown,
											 bool a_repeatable)
	{
		// ★★ 第 89 轮（可重复任务）：这类任务**完成一次后继续显示**（豁免「已完成」过滤）——
		//   它们设计上还能再接：完成时引擎标记 completed，但下次接取会恢复 running
		//   （数据 ref/repeatable_quests.json / 静态表 StaticQuestInfo::repeatable；
		//   语义与证据见 docs/11-可重复任务盘点（第89轮）.md）。
		if (a_repeatable) {
			return RuntimeFilterVerdict::kKeep;
		}
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

	// ★★ 第 87 轮：**OR 组**（引擎语义 —— 第 86 轮反汇编实证，见 docs/08 4.3）：
	//   CTDA type 的 bit0（OR）标记「本条**开始一个 OR 组**」——
	//   组 = 从带 OR 位的那条起，直到**第一条不带 OR 位的条件**（含）或列表末尾；
	//   组内条件相互 OR、组作为整体 AND；无 OR 位的独立条件各自 AND。
	//   引擎算法（TESCondition::IsTrue @0xE46700）等价形态：
	//     acc = true; orAcc = false; inOr = false
	//     for c in conds:
	//       if !inOr: orBit ? (orAcc = c, inOr = true) : (acc = acc && c)
	//       else:     orAcc = orAcc || c; (!orBit) ? (inOr = false, acc = acc && orAcc) : skip
	//     if inOr: acc = acc && orAcc
	//   三态处理：任一条 kUnknown ⇒ 立即 kUnknown（放行 —— 不知道就不能下隐藏结论，
	//   ★ 比旧实现的「顺序决定」更保守，不误藏）；最终 acc == false ⇒ kFail
	//   （detail = 第一条判假条件的说明）。
	GateDecision DecideProgressGates(std::span<const CondCheck> a_conds,
		std::span<const std::uint8_t> a_orBits, std::uint32_t a_begin, std::uint8_t a_count)
	{
		GateDecision out;
		if (a_count == 0) {
			return out;  // kNoGates：这条任务没有门槛
		}
		// 越界检查（`||` 短路防止无符号下溢）
		const auto total = a_conds.size();
		if (a_begin > total || a_count > total - a_begin) {
			out.verdict = CondVerdict::kUnknown;
			out.detail = "门槛切片越界";
			return out;
		}
		// OR 位与条件必须同长（结构异常 ⇒ 放行）
		if (a_begin > a_orBits.size() || a_count > a_orBits.size() - a_begin) {
			out.verdict = CondVerdict::kUnknown;
			out.detail = "门槛 OR 位切片越界";
			return out;
		}

		bool acc = true;     // AND 累计（组外）
		bool orAcc = false;  // 当前 OR 组的累计
		bool inOr = false;   // 是否在 OR 组里
		std::string firstFail;

		for (std::size_t i = 0; i < a_count; ++i) {
			const auto& c = a_conds[a_begin + i];
			if (c.verdict == CondVerdict::kUnknown) {
				out.verdict = CondVerdict::kUnknown;  // 求值不了 ⇒ 放行
				out.detail = c.detail;
				return out;
			}
			const bool truth = (c.verdict == CondVerdict::kPass);
			if (!truth && firstFail.empty()) {
				firstFail = c.detail;
			}
			const bool orBit = (a_orBits[a_begin + i] != 0);
			if (!inOr) {
				if (orBit) {
					orAcc = truth;
					inOr = true;
				} else {
					acc = acc && truth;
				}
			} else {
				orAcc = orAcc || truth;
				if (!orBit) {
					inOr = false;
					acc = acc && orAcc;
				}
			}
		}
		if (inOr) {
			acc = acc && orAcc;  // 组延伸到列表末尾
		}
		if (acc) {
			out.verdict = CondVerdict::kPass;
		} else {
			out.verdict = CondVerdict::kFail;
			out.detail = firstFail.empty() ? std::string("门槛为假") : std::move(firstFail);
		}
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

	// ------------------------------------------------- 3b. 「固定显示」的两类任务（第 74/75 轮）

	bool IsCompanionPinned(std::uint8_t a_companionPin)
	{
		// 语义见 SAQ_QuestTable.h 的 StaticQuestInfo::companionPin：1 = 「入口」同伴任务
		// （个人任务 COM_Quest_<同伴>_Q01 —— 由好感度里程碑直接启动的那一环）⇒ 固定显示。
		// 「后续」（承诺任务）是 0：照旧走链式门槛（前置好感度里程碑没到就不显示）。
		return a_companionPin != 0;
	}

	bool IsFactionEntryPinned(std::int8_t a_factionEntry)
	{
		// ★★ 第 75 轮：语义见 SAQ_QuestTable.h 的 StaticQuestInfo::factionEntry：
		//   0..3 = 四大势力开头任务（同时是固定顺序）⇒ 固定显示 + 固定排前四。
		return a_factionEntry >= 0;
	}

	bool IsGatePinned(std::uint8_t a_companionPin, std::int8_t a_factionEntry)
	{
		// 两个来源的合并（调用点只用这一个）：入口同伴任务 / 四大势力开头任务。
		return IsCompanionPinned(a_companionPin) || IsFactionEntryPinned(a_factionEntry);
	}

	// ------------------------------------------------- 3c. 列表顺序（第 74/75/96 轮）

	EntryOrderKey PinnedOrderKey(std::int8_t a_factionEntry, std::int8_t a_companion,
		std::uint8_t a_companionPin, bool a_repeatable)
	{
		if (a_factionEntry >= 0) {
			// 四大势力开头任务：最靠前；组内按下标 = 固定顺序（UC → FC → RI → CF）。
			return { 0, a_factionEntry };
		}
		if (a_companion >= 0) {
			// 同伴任务：按同伴分组；同一位同伴的「入口」（pin）在「后续」之前。
			return { 1, a_companion * 2 + (IsCompanionPinned(a_companionPin) ? 0 : 1) };
		}
		if (a_repeatable) {
			// ★★ 第 96 轮（可重复任务分组）：整组排到列表末尾（组内保持表顺序 ——
			//   rank 恒 0 ⇒ 比较器对同组两元素返回 false，stable_sort 保持输入顺序）。
			//   ★ 入口条目（任务板 / 可重复 NPC，AppendEntryRows）也在 group 2，
			//   但它们**先追加、后排序**（输入在最后）⇒ 稳定排序后落在 group 2 末尾、
			//   即本组之前 —— 末尾连成一片「（可重复）…」条目（见 SAQ.cpp 的调用点）。
			return { 3, 0 };
		}
		return { 2, 0 };
	}

	bool PinnedOrderLess(const EntryOrderKey& a, const EntryOrderKey& b)
	{
		if (a.group != b.group) {
			return a.group < b.group;   // 势力开头 → 同伴 → 其余
		}
		if (a.group == 2) {
			return false;               // 其余：保持原顺序（stable_sort 的语义，别动）
		}
		return a.rank < b.rank;
	}

	GateAction DecideGateAction(CondVerdict a_verdict, bool a_pinned)
	{
		if (a_verdict != CondVerdict::kFail) {
			return GateAction::kNone;  // 没门槛 / 通过 / 求值不了 ⇒ 不动作（与抽取前一致）
		}
		// ★★ 第 74 轮：同伴「入口」任务固定显示 —— 门槛判「进度没到」也不隐藏
		//   （玩家要求「固定在可接任务列表里，并在提示里提示到达一定好感度才能接取」）。
		return a_pinned ? GateAction::kPinBypass : GateAction::kHide;
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

	// ---------------------------------------------------------------- 6. UTF-8 安全截断

	std::size_t Utf8SafeCut(std::string_view a_text, std::size_t a_maxBytes)
	{
		if (a_maxBytes == 0 || a_text.size() <= a_maxBytes) {
			return a_text.size();
		}
		std::size_t cut = a_maxBytes;
		// UTF-8 续字节 = 10xxxxxx：切点落在续字节上 ⇒ 正在切一个多字节字符 ⇒ 左移。
		while (cut > 0 && (static_cast<unsigned char>(a_text[cut]) & 0xC0u) == 0x80u) {
			--cut;
		}
		return cut;
	}

	// ---------------------------------------------------------------- 7. 界面结构指纹

	UiFingerprintVerdict DecideUiFingerprint(bool a_menu, bool a_tabSel, bool a_list,
		int a_numTabs, bool a_graceElapsed)
	{
		// ① 结构已就绪且匹配 ⇒ 直接放行（不论宽限期 —— 正常路径在宽限期内就成功）。
		if (a_menu && a_tabSel && a_list && a_numTabs == kExpectedOriginalTabCount) {
			return UiFingerprintVerdict::kOk;
		}
		// ② 还有缺项：宽限期内 = 可能只是没建好 ⇒ 静默重试（不当失败）。
		if (!a_graceElapsed) {
			return UiFingerprintVerdict::kWait;
		}
		// ③ 宽限期后仍缺 ⇒ 按「哪个硬项缺」给出失败码（顺序 = 依赖链：
		//    menu → tabSel / list → tab 数）。
		if (!a_menu) {
			return UiFingerprintVerdict::kNoMenu;
		}
		if (!a_tabSel) {
			return UiFingerprintVerdict::kNoTabSel;
		}
		if (!a_list) {
			return UiFingerprintVerdict::kNoList;
		}
		return UiFingerprintVerdict::kTabCount;   // 只剩 numTabs 读不到 / ≠ 7
	}

	const char* UiFingerprintVerdictName(UiFingerprintVerdict a_v)
	{
		switch (a_v) {
		case UiFingerprintVerdict::kOk:       return "ok";
		case UiFingerprintVerdict::kWait:     return "等待结构就绪";
		case UiFingerprintVerdict::kNoMenu:   return "Menu_mc 取不到";
		case UiFingerprintVerdict::kNoTabSel: return "TabbedFilterSelection_mc 取不到";
		case UiFingerprintVerdict::kNoList:   return "MissionsList_mc 取不到";
		default:                              return "原版 tab 数不是 7 项";
		}
	}
}
