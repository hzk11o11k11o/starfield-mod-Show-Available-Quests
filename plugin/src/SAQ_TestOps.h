#pragma once

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

	// 取消引导（用例 teardown 用）。走的是**产品路径**：DLL 把引导目标写成 0、状态清 0，
	// 与「玩家自己取消引导 / 接取后自动取消」完全同一个调用（Guide::SetGuideTarget(0)）。
	// 注意：真正生效仍要等脚本的轮询节拍（菜单关着时），所以放在最后一步就行。
	bool ClearGuide(std::string& a_detail);

	// ------------------------------------------------------------------
	//  UI 测试驱动（调 AS3 的 SAQ_TestDrive*，见 MissionMenu.as）
	//
	//  ★ 这些入口在 AS3 侧**调用真实的处理函数**（选中 / 按键 / 展开），不复制逻辑 ——
	//    否则测的是测试代码，不是产品代码。返回 AS3 的状态串（如 "ok|idx=3"）。
	// ------------------------------------------------------------------
	bool InvokeUiTestDrive(const char* a_fn, const std::string& a_arg, std::string& a_reply);
}
