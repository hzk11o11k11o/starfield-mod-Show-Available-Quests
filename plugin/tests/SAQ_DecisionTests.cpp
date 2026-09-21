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

	MT_CHECK_EQ(DecideProgressGates(t, 0, 0).verdict, CondV::kNoGates);   // count=0 优先于越界检查
	MT_CHECK_EQ(DecideProgressGates(t, 5, 0).verdict, CondV::kNoGates);
	MT_CHECK_EQ(DecideProgressGates(t, 5, 1).verdict, CondV::kUnknown);   // begin == size ⇒ 越界
	MT_CHECK_EQ(DecideProgressGates(t, 6, 1).verdict, CondV::kUnknown);   // begin > size ⇒ 越界
	MT_CHECK_EQ(DecideProgressGates(t, 4, 2).verdict, CondV::kUnknown);   // count 超出剩余
	const auto over = DecideProgressGates(t, 9, 1);
	MT_CHECK_EQ(over.detail, std::string("门槛切片越界"));

	MT_CHECK_EQ(DecideProgressGates(t, 0, 1).verdict, CondV::kPass);      // 单条 pass
	MT_CHECK_EQ(DecideProgressGates(t, 3, 2).verdict, CondV::kPass);      // 全 pass

	const auto f1 = DecideProgressGates(t, 0, 3);                          // [P,F,U] ⇒ 第一条非 pass
	MT_CHECK_EQ(f1.verdict, CondV::kFail);
	MT_CHECK_EQ(f1.detail, std::string("A"));

	const auto u1 = DecideProgressGates(t, 2, 1);                          // [U] ⇒ unknown（放行）
	MT_CHECK_EQ(u1.verdict, CondV::kUnknown);
	MT_CHECK_EQ(u1.detail, std::string("B"));

	MT_CHECK_EQ(DecideProgressGates(t, 0, 4).verdict, CondV::kFail);       // fail 优先于后面的 unknown
	MT_CHECK_EQ(DecideProgressGates(t, 1, 2).verdict, CondV::kFail);       // [F,U] ⇒ fail
	MT_CHECK_EQ(DecideProgressGates(t, 2, 2).verdict, CondV::kUnknown);    // [U,P] ⇒ unknown
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

// ----------------------------------------------------------------

int main()
{
#ifdef _WIN32
	::SetConsoleOutputCP(CP_UTF8);
#endif
	return MiniTest::RunAll("SAQ_Decision（离线层 · 决策纯函数）");
}
