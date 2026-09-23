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

	// ★★ 第 89 轮（可重复任务）：a_repeatable = 「可重复任务」（静态表
	//   StaticQuestInfo::repeatable >= 0）—— 这类任务**完成一次后继续显示**
	//   （设计上还能再接：完成时引擎标记 completed，但下次接取会恢复 running；
	//   判据见 docs/11-可重复任务盘点（第89轮）.md）。
	//   默认 false ⇒ 与旧行为逐字一致（既有调用点不需要改）。
	RuntimeFilterVerdict DecideRuntimeFilter(const RuntimeFlags& a_flags, bool a_vtableKnown,
											 bool a_repeatable = false);

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

	// 进度门槛（CTDA 记录级条件；★★ 第 87 轮起支持 **OR 组**）：
	//   * a_count == 0 ⇒ kNoGates；
	//   * 切片越界（a_begin / a_count vs a_conds.size() 或 a_orBits.size()）⇒ kUnknown
	//     （"门槛切片越界" / "门槛 OR 位切片越界"）；
	//   * a_orBits[i] = 该条 CTDA 的 type bit0（OR 位）—— 语义 = 「本条**开始一个
	//     OR 组**」（第 86 轮反汇编实证，见 docs/08 4.3）：组 = 从本条起直到第一条
	//     不带 OR 位的条件（含）或列表末尾；**组内相互 OR、组作为整体 AND**；
	//   * 任一条 kUnknown ⇒ kUnknown（求值不了 ⇒ 放行 —— 不误藏）；
	//   * 最终结果：组合为真 ⇒ kPass；否则 kFail（detail = 第一条判假条件）。
	//   ★ 无 OR 位时与旧实现（逐条 AND、第一条非 pass 原样返回）等价；
	//     唯一的宽松化：kFail 之后还有 kUnknown ⇒ 放行（旧实现是顺序决定）。
	GateDecision DecideProgressGates(std::span<const CondCheck> a_conds,
		std::span<const std::uint8_t> a_orBits, std::uint32_t a_begin, std::uint8_t a_count);

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

	// ★★ 第 67 轮：**任务链门槛**（「编号任务链」的启动边 —— 见 SAQ_QuestTable.h 的
	//   kChainGates 与 tools/esm/gen_quest_chain.py）。
	//
	//   每条边 = (前置任务, 触发 stage)：那条 stage 完成 ⇒ 这个后续任务才可能开始
	//   （例如 `CF01` 的 stage 1000 fragment 里 `CF02.SetStage(10)`）。
	//
	//   语义（**边之间是「或」**，与进度门槛的 AND 相反）：
	//     * a_edges 为空 ⇒ kNoGates（这条任务不是链式后续 ⇒ 不做链式过滤）；
	//     * 任一条边 kPass（该 stage 已完成）⇒ kPass（前置做到了 ⇒ 放行，保守）；
	//     * 否则若任一条 kUnknown（前置任务取不到 / 求值器不可用）⇒ kUnknown（放行）；
	//     * 否则（全部边 kFail）⇒ kFail（**进度没到 ⇒ 隐藏** —— 玩家还没做完前一个
	//       任务，这个后续任务接不到，例如深红舰队的 CF02「菜鸟觐见」）。
	GateDecision DecideChainGates(std::span<const CondCheck> a_edges);

	// ========================================================================
	//  3b. 「固定显示」的两类任务（第 74/75 轮）：入口同伴 / 四大势力开头
	//
	//  需求（玩家）：
	//    · 第 74 轮：「把所有达到一定好感度才能接到的同伴任务**固定**在可接任务
	//      列表里，任务名称前面写上同伴的名字，并在提示里提示到达一定好感度才能接取」
	//      + 「链式关系的后续任务还是不要显示，只显示入口任务」；
	//    · 第 75 轮：「把四大势力开头任务…**固定显示**，并固定排在可接任务列表的
	//      前四个；除了深红舰队，其他都能正常引导；深红舰队只保留简要说明」。
	//
	//  数据：StaticQuestInfo::companion（哪一位同伴）+ companionPin（1 = **入口**
	//  同伴任务 = 个人任务 COM_Quest_<同伴>_Q01 —— 由好感度里程碑直接启动的那一环）；
	//  ★★ 第 75 轮追加 StaticQuestInfo::factionEntry（≥ 0 = 四大势力开头任务，
	//  同时也是固定顺序：0 = 联合殖民地 … 3 = 深红舰队）。
	//  生成器 tools/esm/gen_companion_quests.py / tools/esm/gen_faction_entry_quests.py
	//  （都对着官方 Papyrus 源码核验）。
	//  ========================================================================

	// a_companionPin != 0 ⇒ 这条是「入口」同伴任务（固定显示）。
	bool IsCompanionPinned(std::uint8_t a_companionPin);

	// ★★ 第 75 轮：a_factionEntry >= 0 ⇒ 这条是四大势力开头任务（固定显示 +
	//   固定排在列表前四个，见下面的 PinnedOrderKey/PinnedOrderLess）。
	bool IsFactionEntryPinned(std::int8_t a_factionEntry);

	// 两个来源合并后的「要不要跳过三类门槛」判据（调用点只用这一个 ——
	// 免得两处各写一份 `||`，漏改一处就是「某类任务忽然被藏」）。
	bool IsGatePinned(std::uint8_t a_companionPin, std::int8_t a_factionEntry);

	// ========================================================================
	//  3c. 列表顺序（第 74/75/96 轮）：「固定显示」的任务**前置**、可重复任务**后置**
	//
	//  收集完成后按这个键排序（stable_sort ⇒ 其余条目保持表顺序）：
	//    ① ★★ 第 75 轮：四大势力开头任务 —— 玩家要求「固定排在可接任务列表的
	//       前四个」；组内按 factionEntry 升序 = 固定顺序（联合殖民地 → 自由星 →
	//       龙神 → 深红舰队）；
	//    ② ★ 第 74 轮：同伴任务 —— 玩家要求「把它们放在一起」；按同伴下标分组，
	//       同一位同伴的「入口」（个人任务）在「后续」（承诺任务）之前；
	//    ③ 其余：group 2 —— 比较器对两个「其余」都返回 false（保持原顺序）；
	//    ④ ★★ 第 96 轮：可重复任务（a_repeatable，做完一次还能再接的那 20 条）——
	//       玩家要求「前面加（可重复）提示 + 一样把它们排列在一起（像图里的
	//       （可重复）NPC 入口那样）」⇒ group 3 = 整组排到**列表末尾**。
	//       ★ 关键：任务板 / 可重复 NPC 入口（SAQ.cpp::AppendEntryRows）是**先追加、
	//       后排序**（它们落在 group 2 的末尾 —— 输入在最后 + 稳定排序）⇒ 这一组会
	//       恰好接在「（可重复）NPC」入口之后，末尾连成一片「（可重复）…」条目。
	//    ⑤ 数据语义（静态表不会这样，但语义要稳）：势力 > 同伴 > 可重复 ——
	//       一条任务同时命中多个标记时按前一个分组（重复任务不抢同伴/势力分组）。
	//
	//  界面侧的 `order=` 探针（MissionsList.SAQ_OrderProbe —— 前 6 条 + `|tail=`
	//  末尾两行的 uID=显示名）给出运行期真实顺序；内嵌回退载荷
	//  （gen_quest_table.py::payload_order）必须与本排序**逐条同序**。
	//  ========================================================================
	struct EntryOrderKey
	{
		std::int32_t group{};  // 0 = 势力开头任务；1 = 同伴任务；2 = 其余；3 = 可重复任务
		std::int32_t rank{};   // 组内次序（势力 = factionEntry；同伴 = companion*2 + 入口优先）
	};

	// ★★ 第 96 轮：a_repeatable（静态表 repeatable ≥ 0）⇒ 组 3（列表末尾）。
	EntryOrderKey PinnedOrderKey(std::int8_t a_factionEntry, std::int8_t a_companion,
		std::uint8_t a_companionPin, bool a_repeatable);

	// 是否 a 应排在 b 前面（stable_sort 的比较器；同组的两个键 ⇒ false = 保持原顺序）。
	bool PinnedOrderLess(const EntryOrderKey& a, const EntryOrderKey& b);

	// 门槛求值的最终动作（三个门槛 —— 进度 / INFO / 链式 —— 共用）：
	//   * kNone       —— 没有门槛 / 求值通过 / 求值不了（放行，不动作）；
	//   * kHide       —— 进度没到 ⇒ 隐藏（调用方还要看对应 ini 开关是否关闭）；
	//   * kPinBypass  —— 本来该隐藏，但这是**固定显示**的任务（a_pinned：入口同伴 /
	//                    四大势力开头）⇒ 放行（调用方只记统计 —— 「固定显示」真的
	//                    起了作用的证据）。
	enum class GateAction : std::uint8_t
	{
		kNone = 0,
		kHide,
		kPinBypass,
	};

	// 判据（阈值/组合都在这里，调用点不许各写一份）：
	//   verdict == kFail 时：pinned ⇒ kPinBypass；否则 kHide；
	//   其余 verdict（kNoGates / kPass / kUnknown）⇒ kNone。
	// a_pinned 由调用方用 IsGatePinned(companionPin, factionEntry) 算（两个来源合并）。
	GateAction DecideGateAction(CondVerdict a_verdict, bool a_pinned);

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

	// ========================================================================
	//  6. 证据通道：**UTF-8 安全截断**（第 84 轮）
	//
	//  起因（第 84 轮自动测试复查）：`python tools\test\check_results.py` 报
	//  「'utf-8' codec can't decode byte 0xe8 in position 221910」—— 22 条用例的
	//  结果一条也读不出来（**判据通道整体失效**，比任何单条用例 FAIL 都严重）。
	//
	//  真因：日志/结果里一条「界面状态」行按**字节**截断到上限（EscapeForLog），
	//  正好切在多字节汉字中间（`追踪` + `者` 的首字节 `0xE8` + `…`）⇒ 整行成为
	//  非法 UTF-8；同一处被抄进结果 JSON ⇒ `json.loads` 前的解码抛异常。
	//
	//  语义：返回「不超过 a_maxBytes 字节、且**不切断任何多字节字符**」的前缀长度
	//  （切点若落在续字节上则向左回退到该字符的首字节）。
	//    * a_maxBytes == 0 ⇒ 原长（不截断）；
	//    * 已在上限内 ⇒ 原长；
	//    * 上限落在某字符中间 ⇒ 回退到该字符之前（宁可少一个字符，不留坏字节）。
	//  ★ 只处理 UTF-8 边界，不做转义 —— 转义（\n → \\n 等）由调用点做。
	// ========================================================================
	std::size_t Utf8SafeCut(std::string_view a_text, std::size_t a_maxBytes);

	// ========================================================================
	//  7. 界面结构指纹自检（★★★ 第 143 轮 · P5 双形态与发布；docs/15 11.8 风险①）
	//
	//  为什么需要：注入形态（`SAQ_UiInject`）依赖**原版** MissionMenu 的内部成员名与
	//  结构（`Menu_mc` / `TabbedFilterSelection_mc` / `MissionsList_mc` / tab 数组 7 项）。
	//  游戏版本更新若改了这些，注入会「静默失效」甚至「半残」——例如 tab 文本表是按
	//  原版 7 项**硬编码**的，原版改成 8 个 tab 时把它当成 7 项处理会把别的 tab 名写错。
	//  ⇒ 打开序列先做结构指纹自检：**任一硬项不匹配 ⇒ 不注入**（一行 WARN + HUD 提示，
	//  走既有「UI 通道不可用」路径 + 本菜单不再重试），宁可不提供功能，也不半残。
	//
	//  判据（每个失败都有名字 —— 日志与报 issue 都要它）：
	//    · 全部齐（menu / tabSel / list 都在 + numTabs == kExpectedOriginalTabCount）
	//      ⇒ kOk（不论宽限期 —— 结构已就绪就直接放行，正常路径零额外时延）；
	//    · 缺项且**还在宽限期内**（菜单刚打开、结构可能还没建好）⇒ kWait
	//      （调用方静默重试 —— 与既有 150ms 激活节流一致）；
	//    · 缺项且超出宽限期 ⇒ 对应的失败码（kNoMenu / kNoTabSel / kNoList / kTabCount）。
	//
	//  输入语义（调用方读 GFx 后填充）：
	//    a_menu / a_tabSel / a_list —— 对应对象**是否为有效对象**；
	//    a_numTabs —— 读到的 tab 数（**-1 = 读不到**）；
	//    a_graceElapsed —— 菜单打开后是否已超过宽限期（kFingerprintGraceMs）。
	// ========================================================================

	// 原版 tab 数（1.16 实测 7 项：$ALL / $Main / $Faction / $Misc / $MISSION /
	//   $Activity / $Completed）—— 我们的 tab 文本表按它硬编码（见 SAQ_UiInject.cpp）。
	inline constexpr int kExpectedOriginalTabCount = 7;

	enum class UiFingerprintVerdict : std::uint8_t
	{
		kOk = 0,     // 结构就绪且匹配 ⇒ 可以注入
		kWait,       // 还在宽限期内、结构未就绪 ⇒ 静默重试（不是失败）
		kNoMenu,     // 宽限期后仍取不到 `_root.Menu_mc`（root 结构变了？）
		kNoTabSel,   // `TabbedFilterSelection_mc` 取不到
		kNoList,     // `MissionsList_mc` 取不到
		kTabCount,   // tab 数读不到 / ≠ 7（原版结构已变化）
	};

	UiFingerprintVerdict DecideUiFingerprint(bool a_menu, bool a_tabSel, bool a_list,
		int a_numTabs, bool a_graceElapsed);

	// 失败码 → 日志文案（"ok" / "等待结构就绪" / "Menu_mc 取不到" / …）。
	const char* UiFingerprintVerdictName(UiFingerprintVerdict a_v);
}
