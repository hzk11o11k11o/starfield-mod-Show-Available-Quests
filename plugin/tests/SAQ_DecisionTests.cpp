// ============================================================================
//  SAQ_DecisionTests.cpp —— 离线层单元测试（第 64 轮 · 大项 K）
//
//  目标：把「过滤 / 门槛 / 候选池 / 引导复算」的**决策组合**在这里枚举断言 ——
//  毫秒级、零游戏。harness（引擎内用例）覆盖「引擎时序」，本文件覆盖「逻辑本身」。
//
//  跑法（在 plugin/ 下）：
//      xmake build SAQ_Tests && xmake run SAQ_Tests
//  或（推荐）：tools\test\run-decision-tests.ps1
//  退出码 0 = 全过。
// ============================================================================

#include "MiniTest.h"

#include "SAQ_Decision.h"

#include <array>
#include <cstdint>
#include <span>
#include <string>
#include <vector>

#ifdef _WIN32
#	include <Windows.h>
#endif

using namespace SAQ::Decision;

namespace
{
	using CondV = CondVerdict;

	CondCheck P() { return { CondV::kPass, {} }; }
	CondCheck F(std::string d = "假") { return { CondV::kFail, std::move(d) }; }
	CondCheck U(std::string d = "未知") { return { CondV::kUnknown, std::move(d) }; }
}

// ---------------------------------------------------------------- 1. 状态推导

MT_TEST(DeriveRuntimeFlags_标注位全组合)
{
	// flags 的 4 个标志位（bit0/1/7/11）× startPending(2) × stopFlag(2) = 64 组合
	for (unsigned bits = 0; bits < 16; ++bits) {
		const bool bStarted = (bits & 0x1) != 0;
		const bool bCompleted = (bits & 0x2) != 0;
		const bool bStopping = (bits & 0x4) != 0;
		const bool bActive = (bits & 0x8) != 0;

		std::uint32_t flags = 0;
		if (bStarted) flags |= 1u << 0;
		if (bCompleted) flags |= 1u << 1;
		if (bStopping) flags |= 1u << 7;
		if (bActive) flags |= 1u << 11;

		for (const std::uint64_t pending : { 0ull, 0x1234ull }) {
			for (const std::uint8_t stop : { std::uint8_t{ 0 }, std::uint8_t{ 1 } }) {
				const RawQuestFields raw{ flags, pending, stop };
				const auto f = DeriveRuntimeFlags(raw);
				MT_CHECK_EQ(f.started, bStarted);
				MT_CHECK_EQ(f.completed, bCompleted);
				MT_CHECK_EQ(f.stopping, bStopping);
				MT_CHECK_EQ(f.active, bActive);
				// IsRunning = 开始位 && 非停止位 && 无排队启动 && 无过渡标志
				MT_CHECK_EQ(f.running, bStarted && !bStopping && pending == 0 && stop == 0);
			}
		}
	}
	// 位定义不能被改：其它位（除 bit0/1/7/11 之外）不应影响判定
	constexpr std::uint32_t kOtherBits =
		~((1u << 0) | (1u << 1) | (1u << 7) | (1u << 11));
	const auto onlyHigh = DeriveRuntimeFlags(RawQuestFields{ kOtherBits, 0, 0 });
	MT_CHECK_EQ(onlyHigh.started, false);
	MT_CHECK_EQ(onlyHigh.completed, false);
	MT_CHECK_EQ(onlyHigh.stopping, false);
	MT_CHECK_EQ(onlyHigh.active, false);
	MT_CHECK_EQ(onlyHigh.running, false);
}

// ---------------------------------------------------------------- 2. 运行时过滤

MT_TEST(运行时过滤_只挡已完成且虚表已知)
{
	RuntimeFlags running;
	running.started = true;
	MT_CHECK_EQ(DecideRuntimeFilter(running, true), RuntimeFilterVerdict::kKeep);
	MT_CHECK_EQ(DecideRuntimeFilter(running, false), RuntimeFilterVerdict::kKeep);

	RuntimeFlags done;
	done.completed = true;
	MT_CHECK_EQ(DecideRuntimeFilter(done, false), RuntimeFilterVerdict::kKeep);  // 虚表不认识 ⇒ 不剔
	MT_CHECK_EQ(DecideRuntimeFilter(done, true), RuntimeFilterVerdict::kHideCompleted);

	RuntimeFlags both{ .started = true, .completed = true };
	MT_CHECK_EQ(DecideRuntimeFilter(both, true), RuntimeFilterVerdict::kHideCompleted);
}

MT_TEST(可重复任务_完成后仍显示)
{
	// ★★ 第 89 轮（可重复任务）：豁免判据 —— 与「只挡已完成」正交：
	//   * repeatable=false ⇒ 与旧行为逐字一致（= IsCompletedConfirmed 同源）；
	//   * repeatable=true ⇒ **恒 kKeep**（完成一次后继续显示 —— 设计上还能再接，
	//     见 docs/11-可重复任务盘点（第89轮）.md）。
	RuntimeFlags done{ .started = true, .completed = true };
	MT_CHECK_EQ(DecideRuntimeFilter(done, true, false), RuntimeFilterVerdict::kHideCompleted);
	MT_CHECK_EQ(DecideRuntimeFilter(done, true, true), RuntimeFilterVerdict::kKeep);   // 豁免
	MT_CHECK_EQ(DecideRuntimeFilter(done, false, true), RuntimeFilterVerdict::kKeep);  // 虚表未知也保留

	// 未完成时两种标记都是 kKeep（「已开始」不挡 —— 第 11 轮实证）
	RuntimeFlags running{ .started = true };
	MT_CHECK_EQ(DecideRuntimeFilter(running, true, false), RuntimeFilterVerdict::kKeep);
	MT_CHECK_EQ(DecideRuntimeFilter(running, true, true), RuntimeFilterVerdict::kKeep);

	// 全组合枚举：repeatable=true ⇒ 恒 kKeep；false ⇒ 与 IsCompletedConfirmed 同源
	for (int completed = 0; completed < 2; ++completed)
		for (int vtable = 0; vtable < 2; ++vtable) {
			const RuntimeFlags f{ .completed = completed != 0 };
			const bool known = vtable != 0;
			MT_CHECK_EQ(DecideRuntimeFilter(f, known, true), RuntimeFilterVerdict::kKeep);
			const bool hidden =
				DecideRuntimeFilter(f, known, false) == RuntimeFilterVerdict::kHideCompleted;
			MT_CHECK_EQ(hidden, IsCompletedConfirmed(f, known));
		}
}

MT_TEST(已完成确认_两个调用点的共同判据)
{
	// IsCompletedConfirmed = completed && vtableKnown（四个组合全枚举）
	RuntimeFlags f;
	f.completed = false;
	MT_CHECK_EQ(IsCompletedConfirmed(f, false), false);
	MT_CHECK_EQ(IsCompletedConfirmed(f, true), false);
	f.completed = true;
	MT_CHECK_EQ(IsCompletedConfirmed(f, false), false);
	MT_CHECK_EQ(IsCompletedConfirmed(f, true), true);

	// 与过滤判据必须同源：IsCompletedConfirmed ⇔ DecideRuntimeFilter == kHideCompleted
	for (int completed = 0; completed < 2; ++completed)
		for (int vtable = 0; vtable < 2; ++vtable) {
			const RuntimeFlags g{ .completed = completed != 0 };
			const bool confirmed = IsCompletedConfirmed(g, vtable != 0);
			const bool hidden =
				DecideRuntimeFilter(g, vtable != 0) == RuntimeFilterVerdict::kHideCompleted;
			MT_CHECK_EQ(confirmed, hidden);
		}
}

MT_TEST(安全阀_识别率阈值与除法)
{
	MT_CHECK_EQ(RuntimeFilterApplied(0), false);
	MT_CHECK_EQ(RuntimeFilterApplied(79), false);
	MT_CHECK_EQ(RuntimeFilterApplied(80), true);
	MT_CHECK_EQ(RuntimeFilterApplied(100), true);

	MT_CHECK_EQ(RecognizedPct(0, 0), 100u);   // 空表 ⇒ 不因安全阀放弃
	MT_CHECK_EQ(RecognizedPct(1, 3), 33u);    // 整除截断
	MT_CHECK_EQ(RecognizedPct(79, 100), 79u);
	MT_CHECK_EQ(RecognizedPct(80, 100), 80u);
	MT_CHECK_EQ(RecognizedPct(4, 5), 80u);
	MT_CHECK_EQ(RecognizedPct(3, 5), 60u);
}

// ---------------------------------------------------------------- 3. 进度门槛

MT_TEST(进度门槛_聚合与越界)
{
	const std::vector<CondCheck> t = { P(), F("A"), U("B"), P(), P() };
	const std::vector<std::uint8_t> no = { 0, 0, 0, 0, 0 };   // ★ 第 87 轮：无 OR 位

	MT_CHECK_EQ(DecideProgressGates(t, no, 0, 0).verdict, CondV::kNoGates);  // count=0 优先于越界检查
	MT_CHECK_EQ(DecideProgressGates(t, no, 5, 0).verdict, CondV::kNoGates);
	MT_CHECK_EQ(DecideProgressGates(t, no, 5, 1).verdict, CondV::kUnknown);  // begin == size ⇒ 越界
	MT_CHECK_EQ(DecideProgressGates(t, no, 6, 1).verdict, CondV::kUnknown);  // begin > size ⇒ 越界
	MT_CHECK_EQ(DecideProgressGates(t, no, 4, 2).verdict, CondV::kUnknown);  // count 超出剩余
	const auto over = DecideProgressGates(t, no, 9, 1);
	MT_CHECK_EQ(over.detail, std::string("门槛切片越界"));

	// ★ 第 87 轮：OR 位切片必须与条件同长（结构异常 ⇒ 放行）
	const std::vector<std::uint8_t> shortOrs = { 0, 0 };
	const auto orOver = DecideProgressGates(t, shortOrs, 0, 3);
	MT_CHECK_EQ(orOver.verdict, CondV::kUnknown);
	MT_CHECK_EQ(orOver.detail, std::string("门槛 OR 位切片越界"));

	MT_CHECK_EQ(DecideProgressGates(t, no, 0, 1).verdict, CondV::kPass);     // 单条 pass
	MT_CHECK_EQ(DecideProgressGates(t, no, 3, 2).verdict, CondV::kPass);     // 全 pass

	const auto f1 = DecideProgressGates(t, no, 1, 1);                        // [F]
	MT_CHECK_EQ(f1.verdict, CondV::kFail);
	MT_CHECK_EQ(f1.detail, std::string("A"));

	const auto u1 = DecideProgressGates(t, no, 2, 1);                        // [U] ⇒ unknown（放行）
	MT_CHECK_EQ(u1.verdict, CondV::kUnknown);
	MT_CHECK_EQ(u1.detail, std::string("B"));

	// ★ 第 87 轮：kUnknown 优先于 kFail（「不知道」不能下隐藏结论 —— 比旧实现更保守）
	MT_CHECK_EQ(DecideProgressGates(t, no, 1, 2).verdict, CondV::kUnknown);  // [F,U]
	MT_CHECK_EQ(DecideProgressGates(t, no, 0, 3).verdict, CondV::kUnknown);  // [P,F,U]
	MT_CHECK_EQ(DecideProgressGates(t, no, 2, 2).verdict, CondV::kUnknown);  // [U,P]
}

MT_TEST(进度门槛_OR组_引擎语义)
{
	// orBit：0 = 独立（AND）；1 = 本条**开始一个 OR 组**（语义见 SAQ_Decision.h / docs/08 4.3）
	const std::vector<std::uint8_t> or_010 = { 0, 1, 0 };

	// [A, B(OR), C] ⇒ A AND (B OR C)
	const std::vector<CondCheck> abc = { P(), F("B"), P() };
	MT_CHECK_EQ(DecideProgressGates(abc, or_010, 0, 3).verdict, CondV::kPass);
	const std::vector<CondCheck> abc2 = { P(), F("B"), F("C") };
	const auto abcFail = DecideProgressGates(abc2, or_010, 0, 3);
	MT_CHECK_EQ(abcFail.verdict, CondV::kFail);
	MT_CHECK_EQ(abcFail.detail, std::string("B"));       // detail = 第一条判假条件

	// [A(OR), B(OR)] ⇒ A OR B（组延伸到列表末尾）
	const std::vector<std::uint8_t> or_11 = { 1, 1 };
	const std::vector<CondCheck> ab = { F("A"), P() };
	MT_CHECK_EQ(DecideProgressGates(ab, or_11, 0, 2).verdict, CondV::kPass);
	const std::vector<CondCheck> ab2 = { F("A"), F("B") };
	MT_CHECK_EQ(DecideProgressGates(ab2, or_11, 0, 2).verdict, CondV::kFail);

	// FFConstantZ06 的形状（表内真实数据）：[UC04, Z04(OR), Z05(OR)] ⇒ UC04 AND (Z04 OR Z05)
	const std::vector<std::uint8_t> or_011 = { 0, 1, 1 };
	const std::vector<CondCheck> ff = { P(), F("Z04"), P() };
	MT_CHECK_EQ(DecideProgressGates(ff, or_011, 0, 3).verdict, CondV::kPass);  // Z04 没做、Z05 做了 ⇒ 显示
	const std::vector<CondCheck> ff2 = { P(), F("Z04"), F("Z05") };
	MT_CHECK_EQ(DecideProgressGates(ff2, or_011, 0, 3).verdict, CondV::kFail); // 两个都没做 ⇒ 隐藏
	const std::vector<CondCheck> ff3 = { F("UC04"), P(), P() };
	MT_CHECK_EQ(DecideProgressGates(ff3, or_011, 0, 3).verdict, CondV::kFail); // UC04 没做 ⇒ 隐藏

	// 独立段与 OR 组混合：[A, B(OR), C, D] ⇒ A AND (B OR C) AND D
	const std::vector<std::uint8_t> or_0100 = { 0, 1, 0, 0 };
	const std::vector<CondCheck> mixFail = { P(), P(), F("C"), F("D") };
	MT_CHECK_EQ(DecideProgressGates(mixFail, or_0100, 0, 4).verdict, CondV::kFail);
	const std::vector<CondCheck> mixPass = { P(), F("B"), P(), P() };
	MT_CHECK_EQ(DecideProgressGates(mixPass, or_0100, 0, 4).verdict, CondV::kPass);

	// OR 组里出现 unknown ⇒ 放行（保守 —— 不误藏）
	const std::vector<CondCheck> uk = { P(), U("B"), F("C") };
	MT_CHECK_EQ(DecideProgressGates(uk, or_010, 0, 3).verdict, CondV::kUnknown);
}

// ---------------------------------------------------------------- 4. INFO 门槛

MT_TEST(INFO门槛_全部对话都有已知假才隐藏)
{
	using G = InfoGroupEval;
	MT_CHECK_EQ(DecideInfoGates({}).verdict, CondV::kNoGates);

	// 单组：有已知假 ⇒ 隐藏（detail = 组内第一条 fail）
	const G oneFail[] = { { true, true, "A" } };
	const auto r1 = DecideInfoGates(oneFail);
	MT_CHECK_EQ(r1.verdict, CondV::kFail);
	MT_CHECK_EQ(r1.detail, std::string("A"));

	// 单组：无已知假（unknown 不算 / 或空组）⇒ 放行
	const G oneUnknown[] = { { true, false, {} } };
	MT_CHECK_EQ(DecideInfoGates(oneUnknown).verdict, CondV::kPass);

	// 两组：一假 + 一可用 ⇒ 放行（第二条对话可用）
	const G failThenFree[] = { { true, true, "A" }, { true, false, {} } };
	MT_CHECK_EQ(DecideInfoGates(failThenFree).verdict, CondV::kPass);

	// 两组都假 ⇒ 隐藏
	const G twoFail[] = { { true, true, "A" }, { true, true, "D" } };
	MT_CHECK_EQ(DecideInfoGates(twoFail).verdict, CondV::kFail);
	MT_CHECK_EQ(DecideInfoGates(twoFail).detail, std::string("A"));

	// 越界 ⇒ unknown（放行）
	const G outOfRange[] = { { false, false, {} } };
	MT_CHECK_EQ(DecideInfoGates(outOfRange).verdict, CondV::kUnknown);
	MT_CHECK_EQ(DecideInfoGates(outOfRange).detail, std::string("INFO 条件切片越界"));

	// 短路顺序（有意保留的保守语义）：前面一组无已知假 ⇒ 立刻 kPass，
	// 后面的越界根本不会被检查
	const G shortCircuit[] = { { true, false, {} }, { false, false, {} } };
	MT_CHECK_EQ(DecideInfoGates(shortCircuit).verdict, CondV::kPass);

	// 跨组第一条「非空」fail 说明（第一条为空 ⇒ 用第二条的）
	const G firstEmpty[] = { { true, true, "" }, { true, true, "Z" } };
	MT_CHECK_EQ(DecideInfoGates(firstEmpty).detail, std::string("Z"));

	// 全 fail 且说明全空 ⇒ 兜底文案
	const G allEmpty[] = { { true, true, "" }, { true, true, "" } };
	MT_CHECK_EQ(DecideInfoGates(allEmpty).detail, std::string("全部对话的条件都为假"));
}

// ★ 第 106 轮（operator 全量产品化）：INFO 门槛的「一条对话」= 一组条件 ——
//   组内语义与记录级完全相同（EvaluateInfoGates 组内直接复用 DecideProgressGates，
//   见 SAQ_QuestCond.cpp）：无 OR 位的条件相互 AND、OR 组内相互 OR。
//   这里用**表内真实形状**钉死本次纳入的两种（巴雷特：违约 [12(OR), 14] /
//   MQ05 [35E1A(OR), 30C2B] ⇒ 都是「A OR B」）。
MT_TEST(INFO门槛_组内OR_与记录级同款语义)
{
	const std::vector<std::uint8_t> orAB = { 1, 0 };   // [A(OR), B]

	// A 没完成、B 完成 ⇒ 组为真 ⇒ 对话可用
	const std::vector<CondCheck> ab1 = { F("A"), P() };
	MT_CHECK_EQ(DecideProgressGates(ab1, orAB, 0, 2).verdict, CondV::kPass);

	// ★ 新旧差异点：A 完成、B 没完成 ⇒ 组仍为真
	//   （旧实现只提取了 B（无 OR 位那条）⇒ 判假 ⇒ 可能误藏 —— 本次修正）
	const std::vector<CondCheck> ab2 = { P(), F("B") };
	MT_CHECK_EQ(DecideProgressGates(ab2, orAB, 0, 2).verdict, CondV::kPass);

	// 两个都没做 ⇒ 组为假 ⇒ 这条对话不可用（detail = 组内第一条判假）
	const std::vector<CondCheck> ab3 = { F("A"), F("B") };
	const auto both = DecideProgressGates(ab3, orAB, 0, 2);
	MT_CHECK_EQ(both.verdict, CondV::kFail);
	MT_CHECK_EQ(both.detail, std::string("A"));

	// 组内 unknown ⇒ 放行（保守，不误藏）
	const std::vector<CondCheck> ab4 = { U("A"), F("B") };
	MT_CHECK_EQ(DecideProgressGates(ab4, orAB, 0, 2).verdict, CondV::kUnknown);

	// 混合：[X, A(OR), B] ⇒ X AND (A OR B)
	const std::vector<std::uint8_t> orXAB = { 0, 1, 0 };
	const std::vector<CondCheck> x1 = { F("X"), P(), P() };
	MT_CHECK_EQ(DecideProgressGates(x1, orXAB, 0, 3).verdict, CondV::kFail);
	const std::vector<CondCheck> x2 = { P(), F("A"), P() };
	MT_CHECK_EQ(DecideProgressGates(x2, orXAB, 0, 3).verdict, CondV::kPass);
}

// ---------------------------------------------------------------- 4b. 链式门槛（第 67 轮）

MT_TEST(链式门槛_任一边触发即放行_全未触发才隐藏)
{
	// 边为空 ⇒ 不是链式后续 ⇒ 不做链式过滤
	MT_CHECK_EQ(DecideChainGates({}).verdict, CondV::kNoGates);

	// 单条边未触发（实机形态：CF02「菜鸟觐见」的前置 CF01 stage 1000 没完成）⇒ 隐藏
	const std::vector<CondCheck> oneFail = { F("前置 0x00009136 stage 1000 未完成") };
	const auto h1 = DecideChainGates(oneFail);
	MT_CHECK_EQ(h1.verdict, CondV::kFail);
	MT_CHECK_EQ(h1.detail, std::string("前置 0x00009136 stage 1000 未完成"));

	// 多条边全部未触发 ⇒ 隐藏；说明取第一条**非空**的
	const std::vector<CondCheck> twoFail = { F(""), F("B") };
	const auto h2 = DecideChainGates(twoFail);
	MT_CHECK_EQ(h2.verdict, CondV::kFail);
	MT_CHECK_EQ(h2.detail, std::string("B"));

	// 任一条边已触发 ⇒ 放行（「或」语义 —— 与进度门槛的 AND 相反）
	const std::vector<CondCheck> mixed = { F("A"), P(), F("C") };
	MT_CHECK_EQ(DecideChainGates(mixed).verdict, CondV::kPass);

	// 求值不了 ⇒ 放行（保守）：[F,U] ⇒ unknown
	const std::vector<CondCheck> fu = { F("A"), U("取不到") };
	const auto h3 = DecideChainGates(fu);
	MT_CHECK_EQ(h3.verdict, CondV::kUnknown);
	MT_CHECK_EQ(h3.detail, std::string("取不到"));

	// pass 优先于 unknown（有边已触发 ⇒ 放行）
	const std::vector<CondCheck> up = { U("X"), P() };
	MT_CHECK_EQ(DecideChainGates(up).verdict, CondV::kPass);

	// 全 unknown ⇒ unknown（detail = 第一条非空）
	const std::vector<CondCheck> uu = { U(""), U("Y") };
	const auto h4 = DecideChainGates(uu);
	MT_CHECK_EQ(h4.verdict, CondV::kUnknown);
	MT_CHECK_EQ(h4.detail, std::string("Y"));

	// 全 fail 且说明全空 ⇒ 兜底文案
	const std::vector<CondCheck> allEmpty = { F(""), F("") };
	MT_CHECK_EQ(DecideChainGates(allEmpty).detail, std::string("全部链式前置都还没到"));
}

// ---------------------------------------------------- 4c. 同伴好感度任务（第 74 轮）

MT_TEST(同伴固定显示_入口任务跳过三类门槛)
{
	// 判据一：companionPin（静态表字段）—— 1 = 「入口」同伴任务（个人任务，
	// 由好感度里程碑直接启动的那一环）；0 = 不是（普通任务 / 同伴线的「后续」承诺任务）。
	MT_CHECK_EQ(IsCompanionPinned(0), false);
	MT_CHECK_EQ(IsCompanionPinned(1), true);
	MT_CHECK_EQ(IsCompanionPinned(255), true);  // 字段只当布尔用

	// 判据二：门槛求值的最终动作（三个门槛共用）——
	//   只有 kFail（进度没到）才隐藏；固定显示的同伴任务改成 kPinBypass（放行 + 统计）。
	using A = GateAction;
	MT_CHECK_EQ(DecideGateAction(CondV::kNoGates, false), A::kNone);
	MT_CHECK_EQ(DecideGateAction(CondV::kNoGates, true), A::kNone);
	MT_CHECK_EQ(DecideGateAction(CondV::kPass, false), A::kNone);
	MT_CHECK_EQ(DecideGateAction(CondV::kPass, true), A::kNone);
	MT_CHECK_EQ(DecideGateAction(CondV::kUnknown, false), A::kNone);
	MT_CHECK_EQ(DecideGateAction(CondV::kUnknown, true), A::kNone);
	MT_CHECK_EQ(DecideGateAction(CondV::kFail, false), A::kHide);
	MT_CHECK_EQ(DecideGateAction(CondV::kFail, true), A::kPinBypass);

	// 全组合守卫：只有 kFail 会隐藏；固定显示时**任何** verdict 都不隐藏。
	for (int v = 0; v < 4; ++v) {
		const auto verdict = static_cast<CondV>(v);
		for (int pin = 0; pin < 2; ++pin) {
			const auto a = DecideGateAction(verdict, pin != 0);
			if (a == A::kHide) {
				MT_CHECK(verdict == CondV::kFail);
				MT_CHECK(pin == 0);   // 固定显示的同伴任务永不隐藏（玩家要求「固定显示」）
			}
			if (a == A::kPinBypass) {
				MT_CHECK(verdict == CondV::kFail);
				MT_CHECK(pin != 0);
			}
		}
	}
}

// ---------------------------------------------- 4d. 四大势力开头任务（第 75 轮）

MT_TEST(势力开头任务_固定显示与两类来源合并)
{
	// 判据：factionEntry ≥ 0 = 四大势力开头任务（0 = 联合殖民地 … 3 = 深红舰队）。
	MT_CHECK_EQ(IsFactionEntryPinned(-1), false);
	for (int i = 0; i < 4; ++i) {
		MT_CHECK_EQ(IsFactionEntryPinned(static_cast<std::int8_t>(i)), true);
	}
	MT_CHECK_EQ(IsFactionEntryPinned(127), true);   // 字段只当下标/布尔用

	// 合并判据：两个来源任一命中 ⇒ 固定显示（调用点只用这一个）。
	for (int pin = 0; pin < 2; ++pin) {
		for (int fac = -1; fac < 2; ++fac) {
			const bool want = pin != 0 || fac >= 0;
			MT_CHECK_EQ(IsGatePinned(static_cast<std::uint8_t>(pin),
				static_cast<std::int8_t>(fac)), want);
		}
	}
}

MT_TEST(列表顺序_势力开头在最前_同伴随后_其余保持原序_可重复垫底)
{
	// 键：group 0 = 势力开头任务（rank = factionEntry）；1 = 同伴（rank = 同伴*2 + 入口优先）；
	//     2 = 其余（rank 固定 0 —— 比较器对两个「其余」返回 false，保持输入顺序）；
	//     3 = 可重复任务（★★ 第 96 轮；rank 固定 0 —— 组内保持原顺序）。
	const auto f0 = PinnedOrderKey(0, -1, 0, false);
	const auto f3 = PinnedOrderKey(3, -1, 0, false);
	const auto c0 = PinnedOrderKey(-1, 0, 1, false);    // 同伴 0 的「入口」
	const auto c0f = PinnedOrderKey(-1, 0, 0, false);   // 同伴 0 的「后续」
	const auto c1 = PinnedOrderKey(-1, 1, 1, false);
	const auto other = PinnedOrderKey(-1, -1, 0, false);
	const auto other2 = PinnedOrderKey(-1, -1, 1, false);
	const auto r0 = PinnedOrderKey(-1, -1, 0, true);    // 可重复任务 ×2（组内保持原顺序）
	const auto r1 = PinnedOrderKey(-1, -1, 1, true);

	MT_CHECK_EQ(f0.group, 0);
	MT_CHECK_EQ(c0.group, 1);
	MT_CHECK_EQ(other.group, 2);
	MT_CHECK_EQ(r0.group, 3);              // ★★ 第 96 轮：可重复任务 = 组 3

	// 全序：势力（按下标升序）→ 同伴（按同伴分组、入口在后续前）→ 其余 → 可重复
	MT_CHECK(PinnedOrderLess(f0, f3));
	MT_CHECK(PinnedOrderLess(f3, c0));
	MT_CHECK(PinnedOrderLess(c0, c0f));    // 同一位同伴：入口在后续之前
	MT_CHECK(PinnedOrderLess(c0f, c1));    // 按同伴分组
	MT_CHECK(PinnedOrderLess(c1, other));
	MT_CHECK(PinnedOrderLess(other, r0));  // ★★ 第 96 轮：其余 → 可重复（垫底）
	MT_CHECK(PinnedOrderLess(other2, r1));
	// 其余之间 / 可重复之间：两个方向都 false（stable_sort ⇒ 保持原顺序）
	MT_CHECK_EQ(PinnedOrderLess(other, other2), false);
	MT_CHECK_EQ(PinnedOrderLess(other2, other), false);
	MT_CHECK_EQ(PinnedOrderLess(r0, r1), false);
	MT_CHECK_EQ(PinnedOrderLess(r1, r0), false);
	// 自反：任何键都不小于自己
	for (const auto& k : { f0, f3, c0, c0f, c1, other, r0, r1 }) {
		MT_CHECK_EQ(PinnedOrderLess(k, k), false);
	}
	// 势力组内按「固定顺序」：0（联合殖民地）→ 1（自由星）→ 2（龙神）→ 3（深红舰队）
	MT_CHECK(PinnedOrderLess(PinnedOrderKey(0, -1, 0, false), PinnedOrderKey(1, -1, 0, false)));
	MT_CHECK(PinnedOrderLess(PinnedOrderKey(1, -1, 0, false), PinnedOrderKey(2, -1, 0, false)));
	MT_CHECK(PinnedOrderLess(PinnedOrderKey(2, -1, 0, false), PinnedOrderKey(3, -1, 0, false)));
	// 语义优先级（静态表数据不会重叠，但语义要稳）：势力 > 同伴 > 可重复 ——
	//   同时带多个标记时按靠前的分组（可重复不抢同伴/势力分组）。
	MT_CHECK_EQ(PinnedOrderKey(2, 3, 1, false).group, 0);
	MT_CHECK_EQ(PinnedOrderKey(2, 3, 1, true).group, 0);    // 势力 + 可重复 ⇒ 仍归势力
	MT_CHECK_EQ(PinnedOrderKey(-1, 1, 1, true).group, 1);   // 同伴 + 可重复 ⇒ 仍归同伴
}

// ---------------------------------------------------------------- 5. 候选池

MT_TEST(候选选择_第一个可得的即最优)
{
	MT_CHECK_EQ(PickCandidate(std::span<const bool>{}).anyAlive, false);

	const std::array<bool, 1> none = { false };
	const auto r0 = PickCandidate(none);
	MT_CHECK_EQ(r0.anyAlive, false);
	MT_CHECK_EQ(r0.index, 0);

	const std::array<bool, 3> mid = { false, true, false };
	const auto r1 = PickCandidate(mid);
	MT_CHECK_EQ(r1.anyAlive, true);
	MT_CHECK_EQ(r1.index, 1);

	const std::array<bool, 2> first = { true, false };
	const auto r2 = PickCandidate(first);
	MT_CHECK_EQ(r2.anyAlive, true);
	MT_CHECK_EQ(r2.index, 0);

	const std::array<bool, 4> last = { false, false, false, true };
	const auto r3 = PickCandidate(last);
	MT_CHECK_EQ(r3.anyAlive, true);
	MT_CHECK_EQ(r3.index, 3);
}

MT_TEST(需要靠近_全候选非常驻)
{
	MT_CHECK_EQ(AllCandidatesNonPersistent(std::span<const std::uint8_t>{}), false);  // 空池不是「需要靠近」

	const std::array<std::uint8_t, 2> nonPersist = { 0, 0 };
	MT_CHECK(AllCandidatesNonPersistent(nonPersist));

	const std::array<std::uint8_t, 2> withPersist = { 0, kCandidateFlagPersistent };
	MT_CHECK_EQ(AllCandidatesNonPersistent(withPersist), false);

	const std::array<std::uint8_t, 1> singlePersist = { kCandidateFlagPersistent };
	MT_CHECK_EQ(AllCandidatesNonPersistent(singlePersist), false);

	// 其它位（bit1 起）不算常驻 —— 位定义不能被改
	const std::array<std::uint8_t, 1> otherBits = { 0xFE };
	MT_CHECK(AllCandidatesNonPersistent(otherBits));
}

// ---------------------------------------------------------------- 6. 引导复算状态机

MT_TEST(引导复算_降级要过观察期升级立即执行)
{
	using A = GuideRecalcAction;

	// 没有任何可得候选 ⇒ 当前取不到：开始观察，之后永远保持（没有可降级的目标）
	MT_CHECK_EQ(DecideGuideRecalc(false, 0, 0, false, false), A::kBeginObserve);
	MT_CHECK_EQ(DecideGuideRecalc(false, 0, 0, true, false), A::kHoldObserving);
	MT_CHECK_EQ(DecideGuideRecalc(false, 0, 0, true, true), A::kHoldObserving);

	// best > current ⇒ 当前候选此刻取不到（但有别的可得）
	MT_CHECK_EQ(DecideGuideRecalc(true, 1, 2, false, false), A::kBeginObserve);
	MT_CHECK_EQ(DecideGuideRecalc(true, 1, 2, true, false), A::kHoldObserving);      // 未满
	MT_CHECK_EQ(DecideGuideRecalc(true, 1, 2, true, true), A::kSwitchDowngrade);     // 满 ⇒ 降级

	// best == current ⇒ 已是最优
	MT_CHECK_EQ(DecideGuideRecalc(true, 1, 1, false, false), A::kHoldIdle);
	MT_CHECK_EQ(DecideGuideRecalc(true, 1, 1, true, true), A::kEndObserve);          // 恢复可得

	// best < current ⇒ 升级（立即，不受观察期影响）
	MT_CHECK_EQ(DecideGuideRecalc(true, 2, 1, false, false), A::kSwitchUpgrade);
	MT_CHECK_EQ(DecideGuideRecalc(true, 2, 1, true, false), A::kEndObserveSwitch);   // 恢复 + 同时升级
	MT_CHECK_EQ(DecideGuideRecalc(true, 3, 0, true, false), A::kEndObserveSwitch);
	MT_CHECK_EQ(DecideGuideRecalc(true, 0, 0, false, false), A::kHoldIdle);
}

MT_TEST(引导复算_全组合动作合法)
{
	// 2 × 4 × 4 × 2 × 2 = 128 组合：不崩、返回值都在枚举内
	for (int any = 0; any < 2; ++any)
		for (std::uint8_t cur = 0; cur < 4; ++cur)
			for (std::uint8_t best = 0; best < 4; ++best)
				for (int obs = 0; obs < 2; ++obs)
					for (int el = 0; el < 2; ++el) {
						const auto a = DecideGuideRecalc(any != 0, cur, best, obs != 0, el != 0);
						const int v = static_cast<int>(a);
						MT_CHECK(v >= 0 && v <= 6);
						// 观察未满（elapsed=false）时绝不允许降级
						if (el == 0) {
							MT_CHECK(a != GuideRecalcAction::kSwitchDowngrade);
						}
					}
}

// ---------------------------------------------------------------- 7. 测试过滤

MT_TEST(测试过滤_模式真值表)
{
	const TestFilterInput none{};

	MT_CHECK_EQ(PassesTestFilter(0, none), true);   // 0 = 不过滤
	MT_CHECK_EQ(PassesTestFilter(7, none), true);   // 未知值 = 不过滤

	TestFilterInput target{};
	target.hasTarget = false;
	MT_CHECK_EQ(PassesTestFilter(1, target), false);
	MT_CHECK_EQ(PassesTestFilter(2, target), true);
	target.hasTarget = true;
	MT_CHECK_EQ(PassesTestFilter(1, target), true);
	MT_CHECK_EQ(PassesTestFilter(2, target), false);

	TestFilterInput dlc{};
	dlc.isDlc = true;
	MT_CHECK_EQ(PassesTestFilter(3, dlc), true);
	MT_CHECK_EQ(PassesTestFilter(3, none), false);

	TestFilterInput named{};
	named.hasTarget = true;
	named.hasNamedPlace = false;
	MT_CHECK_EQ(PassesTestFilter(4, named), false);
	named.hasNamedPlace = true;
	MT_CHECK_EQ(PassesTestFilter(4, named), true);
	const TestFilterInput placeOnly{ .hasNamedPlace = true };
	MT_CHECK_EQ(PassesTestFilter(4, placeOnly), false);  // 有地点但没目标 ⇒ 不过

	// 模式 5 不在本函数处理（调用点整段跳过任务循环）⇒ 这里恒 true
	MT_CHECK_EQ(PassesTestFilter(5, TestFilterInput{}), true);
	MT_CHECK_EQ(PassesTestFilter(5, named), true);

	TestFilterInput need{};
	need.needsApproach = true;
	MT_CHECK_EQ(PassesTestFilter(6, need), true);
	MT_CHECK_EQ(PassesTestFilter(6, TestFilterInput{}), false);
}

// ---------------------------------------------------------------- 8. UTF-8 安全截断
//
// 第 84 轮（自动测试二跑复查）：结果 JSON 解不出来（一处非法 UTF-8）⇒ 判据通道
// 整体失效。真因 = 日志截断按字节切、切在多字节字符中间。这里把切点的边界语义
// 枚举钉死（含反向验证：任何上限下切点都落在字符边界上）。

namespace
{
	// true = a_text 的前 a_len 字节正好是若干个完整的 UTF-8 字符。
	bool CutOnCharBoundary(std::string_view a_text, std::size_t a_len)
	{
		std::size_t i = 0;
		while (i < a_len && i < a_text.size()) {
			const auto b = static_cast<unsigned char>(a_text[i]);
			if ((b & 0x80u) == 0) {
				i += 1;
			} else if ((b & 0xE0u) == 0xC0u) {
				i += 2;
			} else if ((b & 0xF0u) == 0xE0u) {
				i += 3;
			} else {
				i += 4;
			}
		}
		return i == a_len;
	}
}

MT_TEST(UTF8截断_切点绝不落在多字节字符中间)
{
	// 基线：上限 0 = 不截断；上限 ≥ 原长 = 不截断
	MT_CHECK_EQ(Utf8SafeCut("abc", 0), std::size_t{ 3 });
	MT_CHECK_EQ(Utf8SafeCut("abc", 10), std::size_t{ 3 });
	MT_CHECK_EQ(Utf8SafeCut("", 5), std::size_t{ 0 });
	MT_CHECK_EQ(Utf8SafeCut("abcdef", 3), std::size_t{ 3 });
	MT_CHECK_EQ(Utf8SafeCut("abcdef", 6), std::size_t{ 6 });

	// 3 字节汉字：`中文` = 6 字节 —— 切在第二个字中间 ⇒ 回退到 3
	constexpr std::string_view zh = "中文";
	MT_CHECK_EQ(zh.size(), std::size_t{ 6 });
	MT_CHECK_EQ(Utf8SafeCut(zh, 5), std::size_t{ 3 });
	MT_CHECK_EQ(Utf8SafeCut(zh, 4), std::size_t{ 3 });
	MT_CHECK_EQ(Utf8SafeCut(zh, 3), std::size_t{ 3 });
	MT_CHECK_EQ(Utf8SafeCut(zh, 2), std::size_t{ 0 });  // 切在第一个字中间 ⇒ 0
	MT_CHECK_EQ(Utf8SafeCut(zh, 1), std::size_t{ 0 });

	// 混合：`a中` = 1 + 3 字节
	constexpr std::string_view mix = "a中";
	MT_CHECK_EQ(mix.size(), std::size_t{ 4 });
	MT_CHECK_EQ(Utf8SafeCut(mix, 3), std::size_t{ 1 });
	MT_CHECK_EQ(Utf8SafeCut(mix, 2), std::size_t{ 1 });
	MT_CHECK_EQ(Utf8SafeCut(mix, 1), std::size_t{ 1 });

	// 4 字节字符（U+1F600）：`ab` + 4 字节 = 6 字节
	constexpr std::string_view emo = "ab\xF0\x9F\x98\x80";
	MT_CHECK_EQ(emo.size(), std::size_t{ 6 });
	MT_CHECK_EQ(Utf8SafeCut(emo, 5), std::size_t{ 2 });
	MT_CHECK_EQ(Utf8SafeCut(emo, 3), std::size_t{ 2 });
	MT_CHECK_EQ(Utf8SafeCut(emo, 6), std::size_t{ 6 });

	// ★ 反向验证：真实文案（含中文 + 全角括号 + 箭头），所有上限下
	//   ① 不超过上限；② 正好落在字符边界；③ 回退不超过一个字符（尽量贴近上限）。
	const std::string line = "任务板 · 赛多尼亚（0x001DF853）→ 引用";
	for (std::size_t cap = 0; cap <= line.size() + 2; ++cap) {
		const std::size_t cut = Utf8SafeCut(line, cap);
		MT_CHECK(cut <= line.size());
		MT_CHECK(CutOnCharBoundary(line, cut));
		if (cap != 0 && line.size() > cap) {
			MT_CHECK(cut <= cap);
			MT_CHECK(cut + 4 > cap);
		}
	}
}

// ---------------------------------------------------------------- 8. 界面结构指纹

MT_TEST(界面指纹_结构齐且七项即通过)
{
	using V = UiFingerprintVerdict;
	// 全齐 + numTabs == 7 ⇒ kOk（不论宽限期 —— 正常路径在宽限期内就成功时不能等）
	MT_CHECK_EQ(DecideUiFingerprint(true, true, true, kExpectedOriginalTabCount, false), V::kOk);
	MT_CHECK_EQ(DecideUiFingerprint(true, true, true, kExpectedOriginalTabCount, true), V::kOk);
	// 原版 tab 数常量不能被改（tab 文本表按它硬编码 —— 见 SAQ_UiInject.cpp）
	MT_CHECK_EQ(kExpectedOriginalTabCount, 7);
}

MT_TEST(界面指纹_宽限期内缺项一律等待)
{
	using V = UiFingerprintVerdict;
	// 2 × 2 × 2 × 4 = 32 组合：宽限期内「不全齐」一律 kWait（绝不误判失败 ——
	//   菜单刚打开、结构还没建好是常态，判失败会把正常环境挡在门外）。
	for (int m = 0; m < 2; ++m)
		for (int t = 0; t < 2; ++t)
			for (int l = 0; l < 2; ++l)
				for (const int n : { -1, 0, 6, 8 }) {
					MT_CHECK_EQ(DecideUiFingerprint(m != 0, t != 0, l != 0, n, false), V::kWait);
				}
}

MT_TEST(界面指纹_宽限期后按依赖链给出失败码)
{
	using V = UiFingerprintVerdict;
	// 全缺 ⇒ kNoMenu（依赖链第一环）
	MT_CHECK_EQ(DecideUiFingerprint(false, false, false, -1, true), V::kNoMenu);
	// menu 在、往后缺 ⇒ 逐项（顺序固定 —— 日志要指向最上游那个缺的）
	MT_CHECK_EQ(DecideUiFingerprint(true, false, false, -1, true), V::kNoTabSel);
	MT_CHECK_EQ(DecideUiFingerprint(true, true, false, -1, true), V::kNoList);
	// 三者都在、tab 数不对：读不到（-1）/ 异常值 / 6 / 8（原版加了 tab 的真实现场）
	MT_CHECK_EQ(DecideUiFingerprint(true, true, true, -1, true), V::kTabCount);
	MT_CHECK_EQ(DecideUiFingerprint(true, true, true, 0, true), V::kTabCount);
	MT_CHECK_EQ(DecideUiFingerprint(true, true, true, 6, true), V::kTabCount);
	MT_CHECK_EQ(DecideUiFingerprint(true, true, true, 8, true), V::kTabCount);
	MT_CHECK_EQ(DecideUiFingerprint(true, true, true, kExpectedOriginalTabCount + 1, true), V::kTabCount);
}

MT_TEST(界面指纹_全组合不崩且在枚举内)
{
	// 2 × 2 × 2 × 5 × 2 = 80 组合：返回值合法 + 两条不变量。
	for (int m = 0; m < 2; ++m)
		for (int t = 0; t < 2; ++t)
			for (int l = 0; l < 2; ++l)
				for (const int n : { -1, 0, 6, 7, 8 })
					for (int g = 0; g < 2; ++g) {
						const auto v = DecideUiFingerprint(m != 0, t != 0, l != 0, n, g != 0);
						const int  iv = static_cast<int>(v);
						MT_CHECK(iv >= 0 && iv <= 5);
						// 不变量①：kOk ⇔ 「三项齐 + numTabs == 7」
						const bool allReady = (m != 0) && (t != 0) && (l != 0) &&
							n == kExpectedOriginalTabCount;
						MT_CHECK_EQ(v == UiFingerprintVerdict::kOk, allReady);
						// 不变量②：宽限期内非 ok 必为 kWait（不能提前判失败）
						if (g == 0 && !allReady) {
							MT_CHECK_EQ(v, UiFingerprintVerdict::kWait);
						}
					}
}

MT_TEST(界面指纹_失败码文案非空且互不相同)
{
	// 文案 = 日志与报 issue 的抓手：每个失败码都要有非空、可区分的名字。
	const std::array<UiFingerprintVerdict, 6> all = {
		UiFingerprintVerdict::kOk, UiFingerprintVerdict::kWait,
		UiFingerprintVerdict::kNoMenu, UiFingerprintVerdict::kNoTabSel,
		UiFingerprintVerdict::kNoList, UiFingerprintVerdict::kTabCount,
	};
	for (std::size_t i = 0; i < all.size(); ++i) {
		const char* a = UiFingerprintVerdictName(all[i]);
		MT_CHECK(a != nullptr && a[0] != '\0');
		for (std::size_t j = i + 1; j < all.size(); ++j) {
			const char* b = UiFingerprintVerdictName(all[j]);
			MT_CHECK(std::string{ a } != std::string{ b });
		}
	}
	// ★ 关键文案被 verify 特征串钉住 —— 改动要同步（含 DLL 侧与工具侧）。
	MT_CHECK_EQ(std::string{ UiFingerprintVerdictName(UiFingerprintVerdict::kNoTabSel) },
		std::string{ "TabbedFilterSelection_mc 取不到" });
	MT_CHECK_EQ(std::string{ UiFingerprintVerdictName(UiFingerprintVerdict::kTabCount) },
		std::string{ "原版 tab 数不是 7 项" });
}

// ----------------------------------------------------------------

int main()
{
#ifdef _WIN32
	::SetConsoleOutputCP(CP_UTF8);
#endif
	return MiniTest::RunAll("SAQ_Decision（离线层 · 决策纯函数）");
}
