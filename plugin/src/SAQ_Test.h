#pragma once

// ============================================================================
//  SAQ_Test —— 引擎内 harness 的**用例驱动器**（第 49 轮）
//
//  痛点：每次验证一个判据都要「启动游戏 → 读档 → 手动点 → 翻日志」，而且存档不一定
//  满足测试条件（进度没到、任务已接、目标 cell 没加载…）。这一层把判据写成**用例文件**，
//  由 DLL 在引擎里自动执行：自己造状态、自己开菜单、自己点条目、自己断言，跑完写结果 JSON。
//
//  分工：
//    SAQ_TestOps.*   原语层（命令通道 / 菜单开关 / 日志环形缓冲 / UI 测试驱动）
//    SAQ_Test.*      本文件：计划解析 + 步骤状态机 + 断言 + 结果落盘
//    MissionMenu.as  界面的测试入口 SAQ_TestDrive*（内部走**真实**处理函数）
//
//  ## 用例文件（ini 风格，零依赖 —— commonlibsf 的 JSON 只服务于 REX 设置，不是通用解析器）
//
//    ; 注释行以 ; 开头
//    [case:smoke]
//    desc = 菜单打开 + 选中 + 按 R
//    step = ping
//    step = menu.open
//    step = ui.select 0x002A1B3C
//    step = ui.key R
//    step = assert.log 引导请求： timeout=2000
//    step = menu.close
//    step = assert.log 引导已生效|引导延迟生效 timeout=30000
//
//  ## 步骤一览（详细语义见 SAQ_Test.cpp 的 ParseStep）
//
//    ping / quest.reset <fid> / quest.start <fid> / quest.stage <fid> <n> /
//    quest.complete <fid> / teleport <fid>        → 走 Papyrus 命令通道（要**菜单关着**）
//    wait <ms>                                    → 等
//    menu.open / menu.close                       → kShow/kHide（原语层）
//    ui.select <uid> / ui.key <key> / ui.expand <uid>  → AS3 测试入口（真实处理路径）
//    ui.tab                                       → 切到「可接任务」tab 并重建列表
//    assert.log <正则> [timeout=ms]                → 内存日志环形缓冲里找（本步骤之后的行）
//    assert.ui <正则> [timeout=ms]                 → 读 AS3 的 SAQ_Report
//    assert.menu open|closed [timeout=ms]         → 任务菜单开关状态
//    guide.clear                                  → 取消引导（teardown）
//    note <文本>                                   → 只往日志里打一行标记（分段用）
//
//  ## 时序红线（写在用例里的人必须知道）
//
//    Papyrus 轮询节拍在菜单开着时冻结（第 27 轮实测定案）⇒ **造状态的步骤必须排在
//    menu.open 之前**，**断言引导结果必须排在 menu.close 之后**。驱动器对「菜单开着时
//    遇到命令步骤」会自动关菜单并记 WARN（容错，但会留下证据）。
// ============================================================================

#include <string>

namespace SAQ::Test
{
	// 每帧主线程调用（挂在 SAQ.cpp 的 Tick 末尾）。a_menuOpen = 任务菜单此刻是否开着。
	// 未启用时开销 = 一次 bool 判断。
	void Tick(bool a_menuOpen);

	// 读 ini（[Test] Harness / Plan）与用例文件。SAQ::Install() 调一次。
	void LoadPlan();

	bool        Enabled();
	bool        Finished();
	std::string StatusLine();  // 一行状态（日志用）
}
