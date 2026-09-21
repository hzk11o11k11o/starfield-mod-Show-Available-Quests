#pragma once

// ★ 第 53 轮（大项 F · 发布就绪）：本头文件只在开发构建（SAQ_WITH_HARNESS=1）里有内容 ——
//   发布构建里没人引用它（SAQ.cpp 的 include 在 #if 内）。
#if SAQ_WITH_HARNESS

// ============================================================================
//  SAQ_TestOps —— 引擎内 harness（自动化测试）的**原语层**（第 49 轮）
//
//  背景：进游戏测一次很贵（启动 + 读档 + 人工点），而且存档不一定满足测试条件。
//  这套东西把「造状态 / 开菜单 / 点条目 / 看断言」全部变成可编程的，人只需要启动一次游戏。
//
//  ## 为什么写侧动作绕道 Papyrus（而不是 DLL 直接调原生函数）
//
//  docs/04 第 2.1 节定案：Papyrus 原生函数的调用约定是 `rcx=VM, rdx=栈帧, r8=self`，
//  DLL 直接调它们要伪造 VM 栈帧（SKSE 那套 DispatchStaticCall 在 commonlibsf 里只是
//  把 BSTThreadScrapFunction 别名成 std::function，ABI 未验证）—— 风险远大于收益。
//  所以：
//
//     DLL（本层）          脚本（SAQ_Main.psc 的 ProcessTestCommand）
//     ─────────────        ────────────────────────────────────────
//     写 ArgA/ArgB/ArgC    读参数 → Quest.Reset/Start/SetStage/CompleteQuest
//     写 Cmd               Actor.MoveTo
//     写 Seq（提交点）     → 写 Result + 写 Ack = Seq
//     轮询 Ack == Seq
//
//  通道 = ESM 里追加的 8 条 GLOB（0x806~0x80D，见 tools/esm/patch_saq_esm.py）。
//  用 GLOB 而不是别的东西：这是本项目唯一被实机验证过的 DLL → Papyrus 通道
//  （SAQ_GuideTargetRef 那套已经跑了十几轮）。
//
//  ## 时序红线
//
//  Papyrus 的轮询节拍在**菜单开着时冻结**（第 27 轮实测定案）⇒ 命令只在菜单关着时被消化。
//  用例的 setup 必须排在 menu.open 之前，断言必须排在 menu.close 之后（见 SAQ_Test.cpp）。
// ============================================================================

#include <cstdint>
#include <string>

namespace SAQ::Test
{
	// 操作码。★ 与 scripts/SAQ_Main.psc 的 ProcessTestCommand **一一对应** —— 改一处必须改另一处。
	enum class Op : std::int32_t
	{
		kNone = 0,
		kPing = 1,
		kQuestReset = 2,
		kQuestStart = 3,
		kQuestStage = 4,
		kQuestComplete = 5,
		kTeleport = 6,
	};

	const char* OpName(Op a_op);
	const char* ResultText(std::int32_t a_code);

	// ------------------------------------------------------------------
	//  日志环形缓冲（断言用）
	//
	//  为什么不用日志文件：① 文件有 1MB 上限、会滚动清空（main.cpp），证据可能被滚掉；
	//  ② 断言要的是「**本步骤开始之后**有没有出现某行」——内存里的序号最直接；
	//  ③ 失败时要能立刻把最近若干行当证据写进结果 JSON（不用读盘）。
	// ------------------------------------------------------------------
	void        InstallLogRing();                     // 由 SAQ::Install() 调一次
	std::size_t LogMark();                            // 步骤开始时打点（= 当前累计行数）
	bool        LogFind(std::size_t a_from, const std::string& a_regex, std::string& a_line);
	std::string LogTail(std::size_t a_maxLines);
	std::string LogSince(std::size_t a_from, std::size_t a_maxLines);  // 失败证据（本步骤之后的行）

	// ------------------------------------------------------------------
	//  harness 总开关（GLOB SAQ_TestHarness）
	//
	//  协议：0 = 关（脚本不做任何事）；1 = DLL 请求启用；2 = 脚本已就绪（可以下命令）。
	//  「1 → 2」这一拍是**必要**的：脚本在通道初始化时会把「已执行序号」追平当前 Seq
	//  （避免把上一局残留的命令重放一遍），所以 DLL 必须先等它就绪再下第一条命令。
	// ------------------------------------------------------------------
	bool EnableHarnessIfNeeded();                     // 按 ini 的开关写 1（幂等）；返回是否已就绪
	bool HarnessReady(std::string& a_detail);
	bool HarnessRequested();

	// ------------------------------------------------------------------
	//  命令通道
	// ------------------------------------------------------------------
	bool ChannelReady(std::string& a_detail);

	// 提交一条命令（ArgA/ArgB/ArgC → Cmd → Seq）。**Seq 最后写 = 提交点**（防读到半条）。
	bool Submit(Op a_op, std::uint32_t a_formID, std::int32_t a_arg, std::string& a_detail);

	// 轮询回执：0 = 还没回执；1 = 已回执（a_resultCode 有效）；-1 = 通道不可用。
	int  Poll(std::int32_t& a_resultCode, std::string& a_detail);
	bool Busy();
	std::uint64_t SubmittedAtMs();
	void Abandon(const char* a_why);                  // 放弃未完成的命令（记一行日志）
	std::uint32_t LastSeq();

	// ------------------------------------------------------------------
	//  菜单开关（原语）
	//
	//  与项目已实测的 kHide（第 37 轮关任务菜单）**同一机制**，kShow 是对称的那一半
	//  （UI_MESSAGE_TYPE::kShow = 0，同一个 AddMessage 函数，ID 已在 SAQ.cpp 的审计里）。
	//  于是「打开任务菜单」不需要人去按键 —— harness 全自动。
	// ------------------------------------------------------------------
	bool SetMenuOpen(bool a_open, std::string& a_detail);

	// ★ 第 54 轮：**任意菜单**的开关/查询（上面两个是 BSMissionMenu 的便捷包装）。
	//   用途：用例收尾要把**星图**（GalaxyStarMapMenu）关掉 —— 它同样是暂停菜单，
	//   不关掉的话游戏一直暂停、Papyrus 定时器不走，后面的命令步骤会全部超时
	//   （用例 DSL 的 `menu.hide <注册名>`）。
	bool MenuIsOpen(const char* a_name);
	bool SetMenuOpenByName(const char* a_name, bool a_open, std::string& a_detail);

	// ------------------------------------------------------------------
	// ★★ 第 58 轮：诊断助手 —— 「此刻还开着的菜单」一行 + 「是否有加载画面」。
	//
	//  为什么需要（10:31 会话的实测现象）：harness 传送玩家的 `MoveTo` 触发了一次加载，
	//  而那次加载**永远没结束**（Papyrus 日志停在 10:34:37、界面停在「加载转圈 + HUD
	//  蓝点」、之后所有命令无回执）。事后复查时，唯一能区分「游戏卡在加载画面」与
	//  「脚本 VM 僵死」的证据就是 LoadingMenu / FaderMenu 此刻是否开着 —— 而当时的
	//  超时文案只有一句静态猜测（「确认此刻菜单是关的」），什么也证明不了。
	//  ⇒ 超时/落地等待时把这一行写进日志与证据。
	// ------------------------------------------------------------------
	std::string OpenMenusSummary();     // 例："LoadingMenu, FaderMenu" / "无"
	bool        AnyLoadingMenuOpen();   // LoadingMenu / FaderMenu 任一开着

	// 取消引导（用例 teardown 用）。走的是**产品路径**：DLL 把引导目标写成 0、状态清 0，
	// 与「玩家自己取消引导 / 接取后自动取消」完全同一个调用（Guide::SetGuideTarget(0)）。
	// 注意：真正生效仍要等脚本的轮询节拍（菜单关着时），所以放在最后一步就行。
	bool ClearGuide(std::string& a_detail);

	// ------------------------------------------------------------------
	// ★★ 第 62 轮（大项 I）：**自动读档**（BGSSaveLoadManager）
	//
	//  为什么需要：候选降级观察期（第 49 轮补丁②）那半段「目标 cell 未加载 ⇒ 候选取不到
	//  ⇒ 先保持 20 秒 ⇒ 降级」**只能靠读档 / 加载窗口**触发（第 60/61 轮的实测结论），
	//  一直挂在「等自动读档落地后补用例」。
	//
	//  实现路线（为什么零新 RE —— 见 SAQ_TestOps.cpp 里的完整说明）：
	//    · 单例 ID 可用：`ID::BGSSaveLoadManager::Singleton{ 883588 }`；
	//    · `QueueLoadGame(entry)` 在 commonlibsf 里是**内联实现**（只写 `queuedEntryToLoad`
	//      与 `queuedTasks` 的 `kLoadGame` 位）—— 游戏自己的「读取存档」菜单排的就是这一队；
	//    · entry 从 `saveGameList` 里按**文件名子串**（大小写不敏感）找；列表没构建时
	//      把 `kBuildSaveGameList` 位写进 `queuedTasks`（内联版 QueueBuildSaveGameList 的
	//      写侧 —— 那个函数的 ID 是 0 不可用），回调用不上（驱动侧轮询 `saveGameListBuilt`）。
	//
	//  ★ 成员偏移全部来自 commonlibsf 的 static_assert，但按项目通则（commonlibsf 偏移
	//    不可信）**先自校验后使用**：shape 不对（built 非 0/1、count 越界、名字不可读）
	//    ⇒ 拒绝写内存并把「偏移可能不对」写进详情。
	// ------------------------------------------------------------------
	std::string SaveGameListSummary();   // 一行诊断：单例 / built / count / 前几个存档名（save.list）
	bool QueueLoadSaveByName(const std::string& a_nameSubstring, std::string& a_detail);

	// ------------------------------------------------------------------
	//  UI 测试驱动（调 AS3 的 SAQ_TestDrive*，见 MissionMenu.as）
	//
	//  ★ 这些入口在 AS3 侧**调用真实的处理函数**（选中 / 按键 / 展开），不复制逻辑 ——
	//    否则测的是测试代码，不是产品代码。返回 AS3 的状态串（如 "ok|idx=3"）。
	// ------------------------------------------------------------------
	bool InvokeUiTestDrive(const char* a_fn, const std::string& a_arg, std::string& a_reply);
}

#endif  // SAQ_WITH_HARNESS

