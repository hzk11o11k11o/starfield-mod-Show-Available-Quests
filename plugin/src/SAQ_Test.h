#pragma once

// ★ 第 53 轮（大项 F · 发布就绪）：本头文件只在开发构建（SAQ_WITH_HARNESS=1）里有内容 ——
//   发布构建里没人引用它（SAQ.cpp 的 include 在 #if 内）。
#if SAQ_WITH_HARNESS

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
//    teleport.entry <板uID>                       → 传送玩家到**任务板**（自动挑此刻可得的
//                                                   候选：板自身 / 新建常驻 marker / 常驻兜底）
//    wait <ms>                                    → 等
//    menu.open / menu.close                       → 任务菜单 kShow/kHide（原语层）
//    menu.hide <注册名>                            → 关掉**任意**菜单（如 GalaxyStarMapMenu ——
//                                                   星图也是暂停菜单，不关掉后面全冻住）
//    ui.select <uid> / ui.key <key> / ui.expand <uid>  → AS3 测试入口（真实处理路径）
//    ui.selectchild <uid>                          → ★ 第 54 轮：展开该条并选中它的**子项**
//                                                   （「前往接取地点」/「前往任务板」）——
//                                                   Enter 的「只引导、不开星图」走的是这条
//    ui.tab                                       → 切到「可接任务」tab 并重建列表
//    assert.log <正则> [timeout=ms] [scope=…]      → 内存日志环形缓冲里找（窗口见下）
//    assert.nolog <正则> [timeout=ms] [scope=…]    → ★ 第 54 轮：**反向断言** —— 整段窗口里
//                                                   都不许出现（「不该再有的行」用它）
//    assert.ui <正则> [timeout=ms]                 → 读 AS3 的 SAQ_Report
//    assert.menu open|closed [timeout=ms]         → 任务菜单开关状态
//    guide.clear                                  → 取消引导（teardown）
//    note <文本>                                   → 只往日志里打一行标记（分段用）
//
//  ## ★★ 增量筛选（ini [Test] Only）——「先只测改动的部分，收口再全量」（第 158 轮）
//
//    ini `[Test] Only=` 逗号分隔的用例 id **子串**（大小写不敏感、包含匹配）：
//      `Only=r47,r80` ⇒ 只跑 r47_board_marker + r80_repeatable_npc；
//      `Only=r98`     ⇒ r98_dlc_chain + r98_dlc_chain_pass（前缀同族全命中）。
//    空 / 缺键 = 跑全部（默认）。构建脚本 `build-saq.ps1 -Only …` 负责写这个键；
//    **不带 -Only 会清空它**（默认回到全量 —— 不会因为忘了清上一次的增量值而漏测）。
//    筛选器没命中任何用例 ⇒ 不跑 + WARN（列出可用 id；防「写错后静默跑全量」白等一轮）。
//    判读「本次是不是增量跑」看两处：日志的 `Only 增量筛选「…」` 行 + 结果 JSON 的
//    `only` 字段（判读工具据此区分「未选中」与「用例没跑到」）。
//
//  ## 断言的日志窗口（`scope=`）—— 为什么需要（★ 第 54 轮）
//
//    默认 `scope=this`：只找**本步骤开始之后**的行（第 49 轮的原始语义）。
//    问题：动作与它的日志常常落在**同一次 Tick** 里（SAQ.cpp 的 Tick 顺序是
//    「产品路径 → harness」）⇒「menu.open 之后的统计行」「ui.key 之后的引导请求」这类
//    断言会**看不到刚刚发生的那一行**（打点已经越过它了）。
//      · `scope=prev` = 从**上一步开始**算起（断言上一步引起的那行 —— 推荐写法）；
//      · `scope=case` = 从**本用例开始**算起（一条用例内查总账，如「整轮都没有复算抖动」）。
//
//  ## `~0x…` = 记录号（不是运行期 FormID）（★ 第 54 轮）
//
//    DLC 任务的运行期 FormID 高字节 = 加载顺序（本机 SFBGS050 是 0x03，别人的机器可能不同）
//    ⇒ 用例文件里写死运行期 FormID，换加载顺序后会指到别的记录。写成 `~0x0008EBDC`，
//    驱动器去静态表里查「记录号 + master 下标」，再用 Masters::MakeFormID 拼出运行期值
//    （也可写 `~2:0x0008EBDC` 显式指定 master 下标）。`ui.select* / ui.expand` 同样支持。
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

#endif  // SAQ_WITH_HARNESS

