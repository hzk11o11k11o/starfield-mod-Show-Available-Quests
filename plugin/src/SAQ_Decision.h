#pragma once

// ============================================================================
//  SAQ_Decision —— **离线层**：把「过滤 / 门槛 / 候选池」的决策从引擎查询里剥出来
//  （第 64 轮 · 大项 K）
//
//  为什么要这个文件：
//    · harness（引擎内用例）覆盖的是「引擎时序」—— 真实，但要开游戏、只能跑固定脚本；
//    · 这里的纯函数覆盖「决策组合爆炸」—— 毫秒级、零游戏：条件三态（真/假/未知）的
//      排列、候选可得性位图、引导降级观察期状态机、testMode 过滤矩阵、运行时标志位
//      组合…… 全部在 `plugin/tests/SAQ_DecisionTests.cpp` 里枚举断言。
//    · 两者互补：harness 保证「和引擎接得对」，本层保证「逻辑本身对」。
//
//  ★ 约束（别破坏）：本文件与 SAQ_Decision.cpp **不 include 任何 RE / SFSE / PCH 头**
//    —— 否则 `plugin/tests` 的独立测试 target（不链接 commonlibsf）编不过。
//    分工：引擎侧调用点（SAQ.cpp / SAQ_QuestCond.cpp / SAQ_QuestState.cpp）负责
//    「查引擎」（LookupByID / 读字段 / 读 GLOB），把查到的原始值喂给这里的纯函数，
//    再按返回值执行副作用（日志 / 写通道 / 计时戳）。
//
//  ★ 语义必须与抽取前**逐字一致**（这一层的价值就在于「把现有行为钉死」）：
//    某个判据的细节改了 ⇒ 先改这里的纯函数 + 单测（会 FAIL），再改调用点。
// ============================================================================

#include <cstddef>
#include <cstdint>
#include <string>
#include <string_view>
#include <span>

namespace SAQ::Decision
{
	// ========================================================================
	//  1. TESQuest 运行时状态推导（原 SAQ_QuestState.cpp）
	//
	//  位含义来自 Papyrus Quest 原生函数的反汇编（见 SAQ_QuestState.h 顶部注释）:
	//    +0x114 bit0 已开始 / bit1 已完成 / bit7 正在停止 / bit11 玩家追踪中
	//    +0x32C 停止-换代过渡标志（IsRunning 要求为 0）
	//    +0x338 排队中的启动数据（IsRunning 要求为 0）
	// ========================================================================

	inline constexpr std::uint32_t kFlagStarted = 1u << 0;
	inline constexpr std::uint32_t kFlagCompleted = 1u << 1;
	inline constexpr std::uint32_t kFlagStopping = 1u << 7;
	inline constexpr std::uint32_t kFlagActive = 1u << 11;

	struct RawQuestFields
	{
		std::uint32_t flags{};         // TESQuest + 0x114
		std::uint64_t startPending{};  // TESQuest + 0x338
		std::uint8_t  stopFlag{};      // TESQuest + 0x32C
	};

	struct RuntimeFlags
	{
		bool started{};
		bool completed{};
		bool stopping{};
		bool active{};
		bool running{};   // IsRunning 的完整判据：开始位 && 不在停止位 && 无排队启动 && 无过渡标志
	};

	RuntimeFlags DeriveRuntimeFlags(const RawQuestFields& a_raw);

	// ========================================================================
	//  2. 运行时过滤判据（原 CollectAvailableQuests 的「只挡已完成」）
	// ========================================================================

	enum class RuntimeFilterVerdict : std::uint8_t
	{
		kKeep = 0,       // 保留（显示）——「已开始」不挡（第 11 轮 RAD05 实证）
		kHideCompleted,  // 已完成 + 虚表已识别 ⇒ 隐藏
	};

	// 「已完成 + 身份可信」—— 两个调用点的**共同判据**（一个真相源）：
	//   ① CollectAvailableQuests：已完成 ⇒ 不进「可接」列表；
	//   ② AutoClearGuideIfAccepted：已完成 ⇒ 引导自动取消（HUD 上不再挂没用的指引）。
	// a_vtableKnown = 虚表命中已知 TESQuest 虚表（对象身份可信）；
	// 虚表不认识 ⇒ 一律 false（宁可不动作，也不能凭错误的对象下判断）。
	bool IsCompletedConfirmed(const RuntimeFlags& a_flags, bool a_vtableKnown);

	RuntimeFilterVerdict DecideRuntimeFilter(const RuntimeFlags& a_flags, bool a_vtableKnown);

	// 安全阀：虚表识别率（百分数）≥ 80 ⇒ 过滤生效（否则整层不过滤，只留证据）。
	inline constexpr unsigned kMinRecognizedPct = 80;
	bool RuntimeFilterApplied(unsigned a_recognizedPct);
	unsigned RecognizedPct(std::size_t a_recognized, std::size_t a_live);

	// ========================================================================
	//  3. 条件门槛（进度门槛 / INFO 门槛）—— 聚合语义
	//
	//  单条件求值（查引擎那半）在 SAQ_QuestCond.cpp 里，产出 CondCheck（三态 + 说明）；
	//  这里只做**聚合**：怎么把一串三态变成「显示 / 隐藏 / 放行」。
	// ========================================================================

	enum class CondVerdict : std::uint8_t
	{
		kNoGates = 0,  // 没有门槛（count == 0）⇒ 正常显示
		kPass,         // 有门槛且结论为真 ⇒ 显示
		kFail,         // 有门槛且有假（进度没到）⇒ 隐藏
		kUnknown,      // 求值不了 / 结构异常 ⇒ 放行（保守）
	};

	struct CondCheck
	{
		CondVerdict verdict{ CondVerdict::kUnknown };
		std::string detail;  // kFail / kUnknown 时给日志的简短说明（可为空）
	};

	struct GateDecision
	{
		CondVerdict verdict{ CondVerdict::kNoGates };
		std::string detail;  // kFail / kUnknown 时 = 对应条件的说明（与抽取前一致）
	};

	// 进度门槛（CTDA 记录级条件，AND 语义）：
	//   * a_count == 0 ⇒ kNoGates；
	//   * 切片越界（a_begin / a_count vs a_conds.size()）⇒ kUnknown（"门槛切片越界"）；
	//   * 逐条求值结果里**第一条非 kPass** 的结论原样返回（kFail = 进度没到；
	//     kUnknown = 求值不了 ⇒ 放行）；全 kPass ⇒ kPass。
	GateDecision DecideProgressGates(std::span<const CondCheck> a_conds,
		std::uint32_t a_begin, std::uint8_t a_count);

	// INFO 门槛（对话分组：一条对话 = 一组条件（AND），组间是「任一条对话可用即可」）。
	//
	// 组内求值（含切片越界检查与「找第一条 kFail 就停」）在引擎侧完成并给出
	// InfoGroupEval；**组间聚合**（隐藏 / 放行）在这里 —— 它才是需要被离线单测
	// 钉死的决策组合（组顺序 + 越界短路的顺序语义）。
	struct InfoGroupEval
	{
		bool        inRange{ true };        // false = 该组切片越界（结构异常）
		bool        hasKnownFalse{ false }; // true = 组内至少有一条「已知为假」的条件
		std::string firstFail;              // hasKnownFalse 时 = 组内第一条 kFail 的说明
	};

	// 聚合语义（与抽取前逐字一致）：
	//   * a_groups 为空 ⇒ kNoGates；
	//   * 逐组遍历：
	//       - !inRange ⇒ kUnknown（"INFO 条件切片越界"）—— 注意这是**遍历到该组时**
	//         才发生：前面已有一组 hasKnownFalse == false 的话，早就 kPass 返回了
	//         （有意的保守短路，别"顺手修"）；
	//       - 该组 !hasKnownFalse ⇒ 立刻 kPass（这条对话可能可用 ⇒ 任务不隐藏）；
	//   * 全部组 hasKnownFalse ⇒ kFail（说明 = 跨组第一条非空 firstFail；
	//     全空时用兜底文案）。
	GateDecision DecideInfoGates(std::span<const InfoGroupEval> a_groups);

	// ========================================================================
	//  4. 引导候选池：选择 / 需要靠近 判定 / 降级观察期状态机
	// ========================================================================

	// 候选 flags 位定义（与 SAQ_QuestTable.h / gen_guide_targets.py 一致）
	inline constexpr std::uint8_t kCandidateFlagPersistent = 0x01;  // bit0 = 常驻引用

	// 挑「此刻可得的、质量最优的」候选：候选列表已按质量排序 ⇒ 第一个
	// alive == true 的即最优。空表 / 全不可得 ⇒ { 0, false }（调用方照常写第一候选）。
	struct CandidatePick
	{
		std::uint8_t index{};    // 选中的下标（全不可得时为 0）
		bool         anyAlive{}; // 是否有任何一个候选此刻可得
	};

	CandidatePick PickCandidate(std::span<const bool> a_alive);

	// 「需要靠近」（needsApproach）判定：候选池**全部**候选都非常驻 ⇒ true。
	//   * 空池 ⇒ false（「暂无导航目标」是另一回事，不该提示「靠近」）；
	//   * 任何一个常驻（或槽位异常 —— 调用方把异常槽以「常驻」传入）⇒ false（保守）。
	bool AllCandidatesNonPersistent(std::span<const std::uint8_t> a_candFlags);

	// 引导目标「动态复算」的状态机（原 UpdateQuestGuideTarget 的判据部分）：
	//   语义：**降级要过观察期，升级立即执行**（第 49 轮补丁② —— 读档/加载瞬间
	//   LookupByID 会短暂返回 null，立刻降级会让蓝点抖动）。
	//
	//   调用方先在引擎侧算出：a_anyAlive（是否有候选可得）、a_bestIndex（最优可得
	//   候选下标）、当前状态（a_observing / a_observeElapsed —— 观察期是否已满，
	//   由调用方按时间戳算），然后按下面返回的动作执行（日志 + 计时戳 + 写通道）。
	enum class GuideRecalcAction : std::uint8_t
	{
		kHoldIdle = 0,         // 什么都不做（已是最优 / 没有可复算的）
		kHoldObserving,        // 保持（观察中未满 / 无任何可得候选 —— 后者永不降级）
		kBeginObserve,         // 当前候选取不到：记观察起点（保持通道不动 + 日志）
		kEndObserve,           // 当前候选恢复可得且已是最优：清观察（+ 日志）
		kEndObserveSwitch,     // 当前候选恢复可得、但 best 更优：清观察 + 立即升级
		kSwitchUpgrade,        // 升级（本来不在观察期）
		kSwitchDowngrade,      // 观察期满仍取不到：降级到 best
	};

	GuideRecalcAction DecideGuideRecalc(bool a_anyAlive, std::uint8_t a_currentIndex,
		std::uint8_t a_bestIndex, bool a_observing, bool a_observeElapsed);

	// ========================================================================
	//  5. 控制台测试过滤（testMode，原 PassesTestFilter）
	// ========================================================================

	struct TestFilterInput
	{
		bool hasTarget{};       // candCount != 0（有引导目标）
		bool isDlc{};           // master != 0（DLC / 非基础游戏）
		bool hasNamedPlace{};   // whereZh 非空（有具名落脚点）
		bool needsApproach{};   // 全部候选都非常驻（见 AllCandidatesNonPersistent）
	};

	// 模式表（与抽取前一致；模式 5 不在这里处理 —— 它在收集循环外整段跳过）：
	//   0 / 未知 = 不过滤；1 = 只显示有目标；2 = 只显示无目标；3 = 只显示 DLC；
	//   4 = 有目标 + 有具名地点；6 = 「需要靠近」的那一类。
	bool PassesTestFilter(int a_mode, const TestFilterInput& a_in);
}
