// ★★ 第 53 轮（大项 F · 发布就绪）：整个文件只在开发构建（SAQ_WITH_HARNESS=1）里编译。
//   发布构建（xmake saq_harness=n）里 xmake 根本不加入这个文件；这里再包一层 #if
//   是**双保险** —— 万一被误加入编译，也只会编成空单元，不会产生任何引用
//   （SAQ.cpp 的调用点同样在 #if 里）。
#if SAQ_WITH_HARNESS

#include "PCH.h"

#include "SAQ_Test.h"

#include "SAQ.h"          // PluginDir() / ★ 第 133 轮：PendingQuests()
#include "SAQ_TestOps.h"  // 原语层
#include "SAQ_UI.h"       // ReadUiReport
#include "SAQ_UiInject.h" // ★★★ 第 133 轮（P3）：ui.inject —— 数据注入 PoC

#include "SAQ_EntryTable.h"  // 任务板入口表（`teleport.entry` 要把「板/常驻 marker」解析成引用）
#include "SAQ_Guide.h"       // Guide::EnsureChannel（入口 marker 的运行期前缀）
#include "SAQ_Masters.h"     // Masters::MakeFormID（「master + 记录号」→ 运行期 FormID）
#include "SAQ_Crew.h"        // ★★★ 第 156 轮：crew.probe 的直读对照（与产品 kind=2 同一套）
#include "SAQ_QuestCond.h"   // ★ 第 101 轮补丁：ProbeQuestStages（quest.probe 只读探针）
#include "SAQ_QuestState.h"  // ★★★ 第 155 轮：crew.probe 读招募任务的运行时状态
#include "SAQ_QuestTable.h"  // 静态任务表（`~0x…` = 记录号，按加载顺序解析成运行期 FormID）
#include "SAQ_TestCrewProbe.h"  // ★★★ 第 155 轮：crew.probe 的 24 位可招募船员数据（生成物）

#include "RE/T/TESForm.h"
#include "RE/U/UI.h"

#include <Windows.h>

#include <algorithm>
#include <cctype>
#include <fstream>
#include <format>
#include <regex>
#include <string_view>
#include <vector>

namespace SAQ::Test
{
	namespace
	{
		constexpr const char* kMenuName = "BSMissionMenu";
		constexpr std::uint64_t kDefaultStepTimeoutMs = 5000;
		// ★★ 第 66 轮（14:35 会话 r44 的唯一 FAIL）：命令回执窗口 3000 → 8000。
		//   实测形态：r44 的第一步 `ping`（seq=17）在 3000 ms 内没等到回执 ⇒ FAIL；
		//   而 **Papyrus 日志证明脚本正常执行了这条命令**
		//   （`测试命令：seq=17 op=1 结果=0 —— Ping`），只是晚了约 **3.4 秒**；
		//   同一时段的现场：DLL 超时诊断「此刻打开的菜单：无」（不是加载画面）、
		//   紧随其后的下一条用例 `ping`（seq=18）**只用 47 ms** 就成功
		//   ⇒ **脚本节拍被偶发拖慢**（菜单刚关、世界活动），既不是产品缺陷也不是通道问题。
		//   窗口留 8 秒（2.3 倍余量）吸收这类抖动；真·脚本僵死仍由
		//   「连续 2 次无回执 / 有加载画面立即判卡死」（kStuckAbortTimeouts）兜底。
		constexpr std::uint64_t kCommandAckTimeoutMs = 8000;   // 命令通道（脚本一拍 0.5 秒）
		// ★ 第 66 轮：回执 ≥ 这个值就在日志里留一行 note（脚本节拍被拖慢的迹象）——
		//   没有它的话，「脚本执行了但晚了」与「通道没通」只能靠翻 Papyrus 日志区分。
		constexpr std::uint64_t kSlowAckNoteMs = 2000;
		// ★★ 第 56 轮：传送（MoveTo）的回执要**等 cell 加载完**才算完 —— 脚本是在 MoveTo
		//   返回之后才写 TestResult/TestAck 的。09:22 会话实测：两次 teleport 的回执分别在
		//   提交后 4.3 s / 4.5 s 才到（Papyrus 侧 `结果=0`，传送确实成功），而 3 秒窗口把
		//   两条用例判成 FAIL（还让「teleport 之后玩家在哪」这条用例前提变成假象）。
		//   ⇒ 传送单独给 20 秒（冷加载余量），其余命令保持 3 秒（脚本没跑时要快速失败）。
		constexpr std::uint64_t kTeleportAckTimeoutMs = 20000;
		// ★★ 第 58 轮（10:31 会话实测「MoveTo 永不返回」）：传送**成功（收到回执）之后**
		//   也不能立刻做下一步 —— 回执是「cell 加载完成」时写的，但加载画面
		//   （LoadingMenu/FaderMenu）与随后的淡入淡出还会持续一会儿。
		//
		//   实测形态（10:31 会话）：第 3 次传送的回执 10:34:35 到，**38 ms 后**又提交了一条
		//   MoveTo（脚本约 2 秒后执行它）⇒ 第二次加载**永远没结束**：
		//     · Papyrus 日志停在 10:34:37（VM 卡在 MoveTo 里，`测试命令` 再没出现过）；
		//     · 界面停在「右下角加载转圈 + HUD 任务蓝点」（玩家截图为证）；
		//     · 之后 3 条用例的命令全部无回执（r45 FAIL + r48/r44 陪跑）。
		//   为什么以前没遇到过：这是「走远」那一步**第一次**真正跑到（第 56/57 轮都更早
		//   就失败退出了），而历史上成功的传送间隔都是 5~10 秒。
		//   ⇒ 传送后加一道「落地静默期」：
		//     ① 加载画面（LoadingMenu/FaderMenu）必须**先消失**，再连续静默 1.5 秒；
		//     ② 距回执至少 3.5 秒。
		//   ★ 第 59 轮补充（11:04 会话 r47/r45 假 FAIL）：这三条判据必须**每 Tick**推进
		//     （读到回执只算「登记」）—— `Poll` 是一次性消费，把检查绑在「读到回执那一
		//     Tick」会让它之后再也跑不到（只打了一行「传送落地中」就被 deadline 误报成
		//     没有回执）。见 kCmd case 里的解耦实现。
		constexpr std::uint64_t kTeleportSettleCleanMs = 1500;
		constexpr std::uint64_t kTeleportMinGapMs = 3500;
		// 落地静默期的上限：超了说明加载画面一直没结束 ⇒ 判这一步 FAIL 并标记「游戏端
		// 卡死」（剩余用例转 SKIP，见 MarkStuck —— 免得后面每条用例都白等一次超时）。
		constexpr std::uint64_t kTeleportSettleMaxMs = 25000;
		// ★★ 第 62 轮（大项 I）：自动读档（save.load）的等待窗口 —— 读档比传送慢得多
		//   （世界重载 + Papyrus VM 重建 + 脚本重新回写「通道就绪」），整套给 120 秒。
		//   「完成」判据与传送的落地静默期同款：加载画面消失 + 连续静默 2 秒 +
		//   距排队 ≥5 秒 + 命令通道重新就绪（读档后 GLOB 回到存档值，脚本要重新握手）。
		constexpr std::uint64_t kSaveLoadTimeoutMs = 120000;
		constexpr std::uint64_t kSaveLoadSettleCleanMs = 2000;
		constexpr std::uint64_t kSaveLoadMinGapMs = 5000;
		// 读档后命令通道迟迟不就绪 ⇒ **唤醒脚本**：开一次任务菜单再关掉（第 26 轮的机制 ——
		//   脚本在 OnMenuOpenCloseEvent 里重挂轮询定时器）。为什么需要：游戏内读档会重建
		//   Papyrus VM，脚本实例是从存档恢复的（OnInit 不跑、定时器也可能没恢复），而
		//   harness 通道的「1→2」回写靠的就是这个轮询节拍。最多唤醒 4 次（每次间隔 3 秒）。
		constexpr std::uint64_t kSaveLoadWakeIntervalMs = 3000;
		constexpr std::uint32_t kSaveLoadWakeMax = 4;
		// ★★ 第 62 轮补（用户实测反馈 12:21 会话）：**主菜单自动读档**（ini [Test] AutoLoad）。
		//   为什么需要：游戏停在「按任意键继续 / 主菜单」时游戏世界还没加载 ⇒ Papyrus
		//   脚本实例不存在 ⇒ harness 的「1→2」握手永远等不到（日志停在「等脚本回写 2」，
		//   玩家看不出任何动静）。这里在主菜单阶段直接用 save.load 的原语替玩家读档 ——
		//   整个自测流程只剩「启动游戏 + 按任意键」。
		constexpr const char*   kMainMenuName = "MainMenu";
		constexpr std::uint64_t kAutoLoadRetryIntervalMs = 3000;
		constexpr std::uint32_t kAutoLoadMaxAttempts = 10;  // ≈30 秒（等列表构建 / 引擎状态）
		// ★★ 第 62 轮补②（12:2x 实测：自动读档后游戏退回主菜单 + 跳出）：
		//   主菜单**出现后先等一会儿**再排队。依据（SAS_AlwaysScan 的菜单事件日志，
		//   同一个 12:30:52 会话）：主菜单 12:31:07.8 出现，而该插件自己的
		//   「forms bound」直到 12:31:26 才打出来 —— 主菜单刚出来的十几秒里引擎还在
		//   做初始化（插件数据 / Papyrus VM / 存档列表…）。过早排队会让读档请求一直
		//   压在引擎的初始化窗口上（实测：12:31:09 排队，引擎 12:31:41.9 才关闭主菜单
		//   开始读档）。等 5 秒既避开头几秒的初始化，又几乎不增加等待。
		constexpr std::uint64_t kAutoLoadMinMenuAgeMs = 5000;
		// 连续多少次「命令无回执」就判定游戏端卡死（若此刻有加载画面，1 次就够）。
		constexpr int kStuckAbortTimeouts = 2;
		constexpr std::uint64_t kReadyCheckIntervalMs = 500;
		constexpr std::size_t   kEvidenceMaxLines = 60;

		// ★★★ 第 155 轮（可招募船员跟踪研究 · docs/16 16.3）：`crew.probe` 的窗口 ——
		//   24 位里只有「引用已加载」的位需要 Papyrus 往返（0.5 秒脚本节拍 + 回执），
		//   其余位 DLL 侧判定不可读直接跳过（与 Papyrus Game.GetForm 同源）⇒ 正常几秒
		//   跑完；给 3 分钟兜住最坏情况（每位最多 kCrewProbeAckTimeoutMs，
		//   连续 kCrewProbeMaxTimeouts 位无回执立刻判失败 —— 防脚本僵死时白跑 24 位）。
		constexpr std::uint64_t kCrewProbeTotalTimeoutMs = 180000;
		constexpr std::uint64_t kCrewProbeAckTimeoutMs = 8000;
		constexpr int           kCrewProbeMaxTimeouts = 2;

		std::uint64_t NowMs()
		{
			return ::GetTickCount64();
		}

		// ----------------------------------------------------------------
		//  步骤 / 用例
		// ----------------------------------------------------------------
		enum class Kind
		{
			kCmd,          // 走 Papyrus 命令通道（要菜单关着）
			kWait,
			kMenu,         // menu.open / menu.close
			kMenuHide,     // ★ 第 54 轮：menu.hide <注册名>（任意菜单，如星图）
			kUi,           // ui.select / ui.selectchild / ui.key / ui.expand / ui.tab
			kAssertLog,
			kAssertNoLog,  // ★ 第 54 轮：反向断言（整段窗口不许出现）
			kAssertUi,
			kAssertMenu,
			kNote,
			kGuideClear,   // 取消引导（DLL 自己的产品路径：Guide::SetGuideTarget(0)）
			kGuideProbe,   // ★ 第 60 轮：候选可得性探针（只读，见 ProbeGuideCandidates）
			kQuestProbe,   // ★★ 第 101 轮补丁：quest.probe —— 直读 IsStageDone（只读，见 ProbeQuestStages）
			kInfoProbe,    // ★★★ 第 106 轮：info.probe —— INFO 门槛 OR 组探针（只读，见 ProbeInfoGates）
			kCrewProbe,    // ★★★ 第 155 轮：crew.probe —— 可招募船员只读探针（faction + 招募任务）
			kUiResearch,   // ★★★ 第 117 轮：ui.research —— GFx 注入能力探针（见 ResearchGfxCapabilities）
			kUiInject,     // ★★★ 第 133 轮：ui.inject —— 数据注入 PoC（见 SAQ_UiInject.h）
			kUiMode,       // ★★★ 第 138 轮：ui.mode —— 运行期强制 UI 形态（隔离探针/产品路径）
			kUiInteract,   // ★★★ 第 140 轮：ui.interact —— 交互接管探针/真按键/状态（P4）
			kSaveList,     // ★★ 第 62 轮：存档列表诊断（BGSSaveLoadManager，只读）
			kSaveLoad,     // ★★ 第 62 轮：自动读档（排队 → 等加载走完 → 通道重新就绪）
		};

		// ★ 第 54 轮：日志断言的时间窗口起点（见 SAQ_Test.h 的 `scope=` 说明）
		enum class LogScope
		{
			kThis = 0,   // 本步骤开始之后（默认，第 49 轮语义）
			kPrev,       // 上一步开始之后（断言「上一步引起的那一行」）
			kCase,       // 本用例开始之后（查总账）
		};

		struct Step
		{
			Kind          kind{ Kind::kNote };
			Op            op{ Op::kNone };    // kind == kCmd 时有效
			std::string   raw;                // 原始行（日志/结果里原样带出来）
			std::string   opName;             // "quest.stage" / "assert.log" …
			std::string   text;               // 正则 / 备注文本 / ui 参数 / 菜单名
			std::uint32_t formId{};
			std::int32_t  num{};
			// ★★ 第 101 轮补丁：`quest.probe` 的 stage 列表（只读探针要读哪几个 stage）。
			std::vector<std::uint16_t> stages;
			bool          menuOpen{};         // kind == kMenu / kAssertMenu
			LogScope      logScope{ LogScope::kThis };
			// ★ 第 54 轮：① `~0x…` = 记录号（踢给静态表解析成运行期 FormID）；
			//   ② `teleport.entry` = 目标不是 FormID 而是**任务板 uID**（要按候选链解析引用）。
			bool          localFormID{};
			bool          resolveAsEntry{};
			std::uint8_t  localMaster{ 0xFF };  // `~N:0x…` 里显式指定的 master 下标（0xFF = 未指定）
			std::uint64_t timeoutMs{ kDefaultStepTimeoutMs };
			// ★★ 第 68 轮：断言正则非法（ECMAScript 编译失败）—— **解析期**就编译校验，
			//   运行期立刻失败并写清原因。不校验的话 LogFind 只能静默返回 false，症状是
			//   「日志里没出现 /…/」这种误导性超时（15:24 会话 r67_chain 的 `\\d` 双反斜杠
			//   踩过：ECMAScript 下 `\\d` = 字面反斜杠 + d，永远匹配不上）。
			bool          regexOk{ true };
		};

		struct Case
		{
			std::string       id;
			std::string       desc;
			std::vector<Step> steps;
			// ★★ 第 69 轮：本用例有步骤/键解析失败（见 ParsePlan）—— 非空 ⇒ 这条用例
			//   直接判 FAIL（不静默丢步）。起因：15:43 会话 r65_icons 里的
			//   `step = ui.state` 是未知步骤，老行为只留一条 WARN、把这一步丢掉，
			//   用例照样 PASS（「少测了一步」在报告里看不出来 —— 与第 68 轮的红线同源）。
			std::string       parseError;
		};

		struct StepResult
		{
			std::string op;
			bool        pass{};
			std::string detail;
			std::string evidence;
			std::uint64_t elapsedMs{};
		};

		struct CaseResult
		{
			std::string             id;
			std::string             desc;
			std::string             status{ "PENDING" };  // PASS / FAIL / SKIP
			std::string             reason;               // SKIP 的原因
			std::vector<StepResult> steps;
			std::uint64_t           elapsedMs{};
		};

		std::vector<Case>       g_cases;
		std::vector<CaseResult> g_results;

		bool        g_enabled{};
		bool        g_loaded{};
		// ★ 未启用时的复查节流 + 「这次变成要跑了吗」的边沿标记（见 PollEnable）
		bool        g_wantHarness{};
		std::uint64_t g_lastEnableCheckMs{};
		constexpr std::uint64_t kEnableCheckIntervalMs = 2000;
		// ★ 第 55 轮：用例之间的间隔 —— 上一条用例收尾（清场）后给引擎一点时间把
		//   菜单关闭处理完，再开下一条（否则下一条的 `ping` 可能撞上「游戏仍暂停」）。
		std::uint64_t g_nextCaseAtMs{};
		constexpr std::uint64_t kInterCaseDelayMs = 700;
		// ★★ 第 57 轮：清场**延迟复查** —— 只在上一条用例「可能触发星图」（按过 R）时才开窗口。
		//   为什么需要：R（XButton）链路的星图由脚本在「菜单关闭后 1~1.5 秒」才打开，而用例
		//   结束时清场当时它还没出现 ⇒ 星图落在下一条用例开头（游戏暂停 ⇒ 脚本定时器冻结
		//   ⇒ `ping` 超时 3 秒被判 FAIL）。09:35 会话实证：smoke 18.315 结束、星图 18.495
		//   才打开 ⇒ r26 第一条 `ping` 超时 —— 产品侧完全正确（第 55 轮的清场救不了这种
		//   「清场跑得比星图打开早」的时序）。
		//   窗口行为：一旦观察到星图/任务菜单打开 ⇒ 关掉并**提前结束**窗口；一直没出现
		//   ⇒ 等满窗口（覆盖脚本「第 2 次尝试」才成功的情形）。窗口没结束就不开下一条。
		bool          g_caseStarMapRisk{};
		std::uint64_t g_cleanupRecheckUntilMs{};
		constexpr std::uint64_t kCleanupRecheckWindowMs = 4000;
		bool        g_harnessReady{};
		bool        g_readyWarned{};
		bool        g_active{};
		bool        g_finished{};
		bool        g_wroteResults{};
		std::string g_planPath;                 // 计划文件路径（日志用）
		std::string g_channelDetail;
		std::size_t g_caseIdx{};
		std::size_t g_stepIdx{};
		std::uint64_t g_lastReadyCheckMs{};
		std::uint64_t g_caseStartedMs{};
		std::uint64_t g_sessionStartMs{};
		// ★ 第 54 轮：日志窗口打点（见 SAQ_Test.h 的 `scope=` 说明）——
		//   g_caseMark = 本用例开始；g_prevMark = 上一步开始（断言上一步引起的那一行）。
		std::size_t g_caseMark{};
		std::size_t g_prevMark{};

		struct StepState
		{
			bool          started{};
			std::uint64_t deadlineMs{};
			std::uint64_t startedAtMs{};
			std::size_t   logMark{};
			bool          kicked{};
			std::string   kickDetail;
			// ★★ 第 58 轮：传送步骤的「落地静默期」状态（见 kTeleportSettleCleanMs）；
			//   ★ 第 59 轮：settleAckDetail = 回执文案（静默期完成时把它并进步骤结果）。
			std::uint64_t settleAckAtMs{};       // 收到回执的时刻（静默期从它起算）
			std::uint64_t settleCleanSinceMs{};  // 「没见过加载画面」这段连续时间的起点
			bool          settleNoted{};         // 已记过一行「传送落地中」
			std::string   settleAckDetail;       // 回执文案（第 59 轮）
			// ★★ 第 62 轮：自动读档（save.load）的状态（与传送的 settle* 分开，语义不同）
			std::uint64_t loadQueuedAtMs{};      // 排队成功时刻（静默期与 5 秒下限从它起算）
			std::uint64_t loadCleanSinceMs{};    // 「没见过加载画面」这段连续时间的起点
			bool          loadSeenLoading{};     // 观察过加载画面（LoadingMenu/FaderMenu）
			bool          loadNoted{};           // 「列表未构建 / 读档加载中」已记过一行
			std::uint64_t loadWakeAtMs{};        // 上一次「开菜单唤醒」的时刻
			std::uint32_t loadWakeCount{};       // 已唤醒次数（上限 kSaveLoadWakeMax）
			bool          loadWakeOpen{};        // 唤醒用的菜单此刻是否开着（下一拍关掉）
			// ★★ 第 83 轮：`ui.*` 遇到「桥没通」时的重试节流（见 kUi 分支）——
			//   桥解析（EnsureResolved）不便宜，别每帧都试。
			std::uint64_t uiRetryAtMs{};
			// ★★★ 第 155 轮：`crew.probe` 的逐位推进状态（见 kCrewProbe 分支）——
			//   一位一个阶段：未提交 ⇒ 预检引用可读性 / 提交 Papyrus；已提交 ⇒ 等回执。
			std::size_t   crewIndex{};        // 下一位要处理的船员下标（== 表长时收尾）
			bool          crewSubmitted{};    // 当前位是否已提交 Papyrus 命令（等回执中）
			int           crewTimeouts{};     // 连续「无回执」计数（防脚本僵死白跑 24 位）
			std::string   crewReport;         // 累积的逐位报告（进步骤 detail / 结果 JSON）
			// 收尾汇总用的统计（Papyrus 读到位数 / A·C·P·分配 各 1 数 / 任务状态分布）
			std::size_t   crewRead{};
			std::size_t   crewA{};
			std::size_t   crewC{};
			std::size_t   crewP{};
			std::size_t   crewAssign{};
			std::size_t   crewQNotStarted{};
			std::size_t   crewQRunning{};
			std::size_t   crewQDone{};
			std::size_t   crewQOther{};
			// ★★★ 第 156 轮（crew.probe 扩展）：
			//   ③ 直读对照 —— 与产品 kind=2 过滤同一套 SAQ_Crew::ReadState；
			//      只有「Papyrus 与直读都读到位」的位参与对照。
			std::size_t   crewDirectRead{};    // 直读读到位数（应与 Papyrus 读到位数一致）
			std::size_t   crewDirectPairs{};   // 参与对照的位数（两边都读到）
			std::size_t   crewMismatch{};      // 三者（A/C/P）有不一致的位数 —— 应为 0
			//   ④ 模拟招募往返（可选 sim=<FormID>；净副作用为零）
			bool          crewSimDone{};       // 是否已做完（或跳过）
			std::string   crewSimNote;         // 判定简语（进汇总行；空 = 未做）
		};
		StepState g_cur;

		// ★★ 第 58 轮：游戏端卡死（脚本 VM 无响应 / 卡在加载画面）的检测与中止 ——
		//   见 MarkStuck 的说明。只在 harness 会话内有效。
		int         g_consecutiveTimeouts{};
		bool        g_stuckAbort{};
		std::string g_stuckReason;

		// ★★ 第 62 轮补：主菜单自动读档的状态（见 TryAutoLoadFromMainMenu）
		bool          g_autoLoadDone{};
		std::uint64_t g_autoLoadCheckMs{};
		std::uint32_t g_autoLoadAttempts{};
		// ★★ 第 62 轮补②：主菜单稳定性门槛 + 排队后的结果侦测（见 kAutoLoadMinMenuAgeMs
		//   与 NoteAutoLoadOutcome）
		std::uint64_t g_autoLoadMenuSeenMs{};    // 首次看到主菜单的时刻（0 = 此刻不在主菜单）
		std::uint64_t g_autoLoadQueuedAtMs{};    // 排队成功时刻（0 = 还没排队）
		bool          g_autoLoadLeftMainMenu{};  // 排队后主菜单**关过**（= 引擎真的开始处理读档）
		bool          g_autoLoadOutcomeNoted{};  // 「读档失败」WARN 只打一次

		// ----------------------------------------------------------------
		//  小工具
		// ----------------------------------------------------------------
		std::string Trim(std::string_view a_in)
		{
			std::size_t b = 0;
			std::size_t e = a_in.size();
			while (b < e && (std::isspace(static_cast<unsigned char>(a_in[b])) != 0)) ++b;
			while (e > b && (std::isspace(static_cast<unsigned char>(a_in[e - 1])) != 0)) --e;
			return std::string{ a_in.substr(b, e - b) };
		}

		std::vector<std::string> SplitWs(std::string_view a_in)
		{
			std::vector<std::string> out;
			std::size_t i = 0;
			while (i < a_in.size()) {
				while (i < a_in.size() && std::isspace(static_cast<unsigned char>(a_in[i])) != 0) ++i;
				std::size_t b = i;
				while (i < a_in.size() && std::isspace(static_cast<unsigned char>(a_in[i])) == 0) ++i;
				if (i > b) {
					out.emplace_back(a_in.substr(b, i - b));
				}
			}
			return out;
		}

		bool ParseFormID(const std::string& a_text, std::uint32_t& a_out)
		{
			try {
				a_out = static_cast<std::uint32_t>(std::stoul(a_text, nullptr, 16));
				return true;
			} catch (...) {
				return false;
			}
		}

		// 从串里摘出 `timeout=N`（其余部分原样返回）
		std::string ExtractTimeout(std::string a_text, std::uint64_t& a_out)
		{
			for (std::size_t pos = 0; (pos = a_text.find("timeout=", pos)) != std::string::npos;) {
				const std::size_t end = a_text.find_first_of(" \t", pos);
				const std::string tok = a_text.substr(pos + 8,
					(end == std::string::npos ? a_text.size() : end) - (pos + 8));
				try {
					a_out = static_cast<std::uint64_t>(std::stoull(tok));
				} catch (...) {
				}
				a_text.erase(pos, (end == std::string::npos ? a_text.size() : end) - pos);
				break;
			}
			return Trim(a_text);
		}

		// ★ 第 54 轮：从串里摘出 `scope=this|prev|case`（其余部分原样返回）。
		std::string ExtractScope(std::string a_text, LogScope& a_out)
		{
			for (std::size_t pos = 0; (pos = a_text.find("scope=", pos)) != std::string::npos;) {
				const std::size_t end = a_text.find_first_of(" \t", pos);
				const std::string tok = a_text.substr(pos + 6,
					(end == std::string::npos ? a_text.size() : end) - (pos + 6));
				if (tok == "prev") {
					a_out = LogScope::kPrev;
				} else if (tok == "case") {
					a_out = LogScope::kCase;
				} else {
					a_out = LogScope::kThis;
				}
				a_text.erase(pos, (end == std::string::npos ? a_text.size() : end) - pos);
				break;
			}
			return Trim(a_text);
		}

		// ★ 第 54 轮：`~0x…` = 静态表里的**记录号** ⇒ 运行期 FormID。
		//   为什么需要：DLC 任务的 FormID 高字节是**加载顺序**（本机 SFBGS050 = 0x03）——
		//   用例文件里写死运行期值，换一台机器/换一次加载顺序就会指到别的记录
		//   （第 17 轮「DLC 任务全部消失」的同一类坑）。写成 `~0x0008EBDC` 由这里解析。
		bool ResolveLocalFormID(std::uint32_t a_local, std::uint8_t a_master, std::uint32_t& a_out,
			std::string& a_detail)
		{
			for (std::size_t i = 0; i < kQuestTableSize; ++i) {
				const auto& q = kQuestTable[i];
				if (q.localFormID != a_local) {
					continue;
				}
				if (a_master != 0xFF && q.master != a_master) {
					continue;
				}
				const auto id = Masters::MakeFormID(q.master, q.localFormID);
				if (id == 0) {
					a_detail = std::format(
						"静态表还没就绪（master {} 未解析）—— 先开一次菜单再跑本用例", q.master);
					return false;
				}
				a_out = id;
				a_detail = std::format("记录号 0x{:06X}@master{}（{}）→ 运行期 0x{:08X}",
					a_local, q.master, q.nameZh, id);
				return true;
			}
			// ★★★ 第 110 轮：**显式 master 的「表外记录」**（`~1:0x00000CF2` 形态）——
			//   用例要推的**前置任务**可能不在「可接任务」静态表里（如追踪者联盟的
			//   `SFBGS003_MiscPointer`：SGE 自启的引导任务、不进列表），而上面的表查找
			//   只认表内记录 ⇒ 旧实现直接失败（r110 用例的硬阻塞）。
			//   显式 master 的语义本来就是「直接用这个 master 拼运行期 FormID」（不依赖表）
			//   ⇒ 表里没有时按它直拼。证据（第 110 轮）：`quest.stage ~1:0x00000CF2 1000`。
			//   注意：仍然要求 master 已解析（未加载 / 表没就绪 ⇒ 失败并给同一句提示）。
			if (a_master != 0xFF) {
				const auto id = Masters::MakeFormID(a_master, a_local);
				if (id == 0) {
					a_detail = std::format(
						"master {} 未解析（没装 / 静态表还没就绪）—— 先开一次菜单再跑本用例", a_master);
					return false;
				}
				a_out = id;
				a_detail = std::format("记录号 0x{:06X}@master{}（表外记录，直拼）→ 运行期 0x{:08X}",
					a_local, a_master, id);
				return true;
			}
			a_detail = std::format("静态表里没有记录号 0x{:06X}（master {}）", a_local,
				a_master == 0xFF ? std::string{ "任意" } : std::to_string(a_master));
			return false;
		}

		// ★ 第 54 轮：任务板条目的**传送目标** —— 依次取「此刻引擎里取得到」的第一个候选：
		//   ① 任务板引用自身（精确；cell 加载时才有）② 新建常驻 XMarker（任意位置可用）
		//   ③ 同 cell 的原生常驻兜底。与产品代码的候选链**同序**（SAQ.cpp::EvaluateEntryGuide），
		//   但这里只关心「取得到」（要能 MoveTo —— 取不到的引用 Papyrus 也拿不到）。
		bool ResolveEntryTarget(std::uint32_t a_boardID, std::uint32_t& a_out, std::string& a_detail)
		{
			std::size_t idx = kEntryTableSize;
			for (std::size_t i = 0; i < kEntryTableSize; ++i) {
				const auto& e = kEntryTable[i];
				if (Masters::MakeFormID(e.master, e.refLocal) == a_boardID || e.refLocal == a_boardID) {
					idx = i;
					break;
				}
			}
			if (idx >= kEntryTableSize) {
				a_detail = std::format("入口表里没有 0x{:08X}", a_boardID);
				return false;
			}
			const auto& e = kEntryTable[idx];
			const auto ch = Guide::EnsureChannel();
			const std::uint32_t markerPrefix = (ch.resolved && ch.prefix <= 0xFF) ? (ch.prefix << 24) : 0;
			const std::uint32_t cands[4] = {
				Masters::MakeFormID(e.master, e.refLocal),
				e.markerLocal ? (markerPrefix | e.markerLocal) : 0,
				e.fallback1 ? Masters::MakeFormID(0, e.fallback1) : 0,
				e.fallback2 ? Masters::MakeFormID(0, e.fallback2) : 0,
			};
			const char* names[4] = { "任务板自身", "新建常驻 marker", "同 cell 常驻兜底1", "同 cell 常驻兜底2" };
			std::string tried;
			for (std::size_t i = 0; i < 4; ++i) {
				if (cands[i] == 0) {
					tried += std::format("{}[无] ", names[i]);
					continue;
				}
				const bool hit = RE::TESForm::LookupByID(static_cast<RE::TESFormID>(cands[i])) != nullptr;
				tried += std::format("{}[{}] ", names[i], hit ? "命中" : "未命中");
				if (hit) {
					a_out = cands[i];
					a_detail = std::format("{}（0x{:08X}）｜{}", names[i], cands[i], tried);
					return true;
				}
			}
			a_detail = std::format("{}（0x{:08X}）此刻一个候选都取不到：{}", e.nameZh, a_boardID, tried);
			return false;
		}

		// ★★ 第 60 轮：候选可得性探针（`guide.probe <任务>`）—— 与产品的「候选复算」用
		//   **同一套查询**（静态表候选池 + `TESForm::LookupByID`），只读、不改任何状态。
		//
		//   为什么需要（第 60 轮 r45 现场）：走远后「候选复算」一行日志都没打 —— 光看日志
		//   分不清这两种情况：
		//     ① 当前候选仍可得 ⇒ 复算按设计「无动作」（保持是对的，蓝点留在目标上）；
		//     ② 当前候选取不到、但观察期/复算没跑（产品缺陷）。
		//   这一行把每个候选的可得性**当场**写进日志与步骤结果 JSON（事后可查）。
		//   实测（11:26 会话）：走远 15 秒后 [1]「G型」=可得 ⇒ ①，用例的旧期望（走远 ⇒
		//   取不到 ⇒ 先保持）不成立 —— 详见 SAQ_TestPlan.txt 用例 4 的注释。
		bool ProbeGuideCandidates(std::uint32_t a_formID, std::string& a_detail)
		{
			const StaticQuestInfo* quest = nullptr;
			for (std::size_t i = 0; i < kQuestTableSize; ++i) {
				if (Masters::MakeFormID(kQuestTable[i].master, kQuestTable[i].localFormID) == a_formID) {
					quest = &kQuestTable[i];
					break;
				}
			}
			if (quest == nullptr) {
				a_detail = std::format("静态表里没有 0x{:08X}（不是静态任务表里的任务？）", a_formID);
				return false;
			}
			std::string parts;
			for (std::uint8_t i = 0; i < quest->candCount; ++i) {
				const auto slot = static_cast<std::size_t>(quest->candBegin) + i;
				if (slot >= kGuideCandidateCount) {
					break;  // 表损坏 / 切片越界：不越界读（verify 另有完整性检查）
				}
				const auto& c = kGuideCandidates[slot];
				const auto id = Masters::MakeFormID(c.refrMaster, c.refrLocal);
				const bool alive = id != 0 &&
					RE::TESForm::LookupByID(static_cast<RE::TESFormID>(id)) != nullptr;
				parts += std::format("{}[{}]「{}」0x{:08X}={}", parts.empty() ? "" : "｜",
					i + 1, c.nameZh, id, alive ? "可得" : "取不到");
			}
			const std::string body = parts.empty() ? std::string{ "（没有候选）" } : "｜" + parts;
			a_detail = std::format("候选可得性：{}（0x{:08X}）{}", quest->nameZh, a_formID, body);
			return true;
		}

		// 解析步骤的最终 FormID（`~` 记录号 / 任务板 uID / 原样运行期值）。
		bool ResolveStepFormID(const Step& a_step, std::uint32_t& a_out, std::string& a_detail)
		{
			if (a_step.resolveAsEntry) {
				return ResolveEntryTarget(a_step.formId, a_out, a_detail);
			}
			if (a_step.localFormID) {
				return ResolveLocalFormID(a_step.formId, a_step.localMaster, a_out, a_detail);
			}
			a_out = a_step.formId;
			return true;
		}

		// 断言的日志窗口起点（见 SAQ_Test.h 的 `scope=` 说明）。
		// ★★ 第 56 轮：打点为 0（= 环形缓冲开头）时退到**本用例起点** —— 绝不允许
		//   「窗口起点 0」这种退化：那等于拿整段缓冲区做断言（假 PASS 的来源，见 CompleteStep）。
		std::size_t EffectiveLogFrom(const Step& a_step)
		{
			switch (a_step.logScope) {
			case LogScope::kPrev: return g_prevMark != 0 ? g_prevMark : g_caseMark;
			case LogScope::kCase: return g_caseMark;
			default:              return g_cur.logMark != 0 ? g_cur.logMark : g_caseMark;
			}
		}

		std::string JsonEscape(std::string_view a_in)
		{
			std::string out;
			out.reserve(a_in.size() + 16);
			for (const char c : a_in) {
				switch (c) {
				case '"': out += "\\\""; break;
				case '\\': out += "\\\\"; break;
				case '\n': out += "\\n"; break;
				case '\r': break;
				case '\t': out += "\\t"; break;
				default:
					if (static_cast<unsigned char>(c) < 0x20) {
						out += std::format("\\u{:04X}", static_cast<unsigned>(static_cast<unsigned char>(c)));
					} else {
						out += c;
					}
				}
			}
			return out;
		}

		// 任务菜单这一刻开着吗。（★ 第 54 轮改名：`MenuIsOpen` 这个名字已经被原语层的
		// **任意菜单**版本（`SAQ::Test::MenuIsOpen(const char*)`）占用 —— 同名会把它隐藏掉，
		// 于是 `MenuIsOpen("GalaxyStarMapMenu")` 会编译不过。）
		bool MissionMenuIsOpen()
		{
			auto* ui = RE::UI::GetSingleton();
			return ui != nullptr && ui->IsMenuOpen(RE::BSFixedString{ kMenuName });
		}

		// ----------------------------------------------------------------
		//  计划解析
		// ----------------------------------------------------------------
		bool ParseStep(const std::string& a_line, Step& a_step, std::string& a_error)
		{
			// op 名与其余部分分开（assert.log 的正则里可能有空格）
			std::size_t sp = a_line.find_first_of(" \t");
			const std::string op = sp == std::string::npos ? a_line : a_line.substr(0, sp);
			std::string rest = sp == std::string::npos ? std::string{} : a_line.substr(sp + 1);
			a_step = Step{};
			a_step.raw = a_line;
			a_step.opName = op;
			a_step.timeoutMs = kDefaultStepTimeoutMs;

			// ★ 第 54 轮：`~0x…`（记录号）与 `~<master>:0x…`（显式 master 下标）——
			//   解析推迟到**步骤开跑时**（那时静态表一定已就绪），见 ResolveStepFormID。
			auto parseFormIDToken = [&](const std::string& a_tok, std::uint32_t& a_out) -> bool {
				std::string tok = a_tok;
				if (!tok.empty() && tok[0] == '~') {
					a_step.localFormID = true;
					tok.erase(0, 1);
					const auto colon = tok.find(':');
					if (colon != std::string::npos) {
						try {
							a_step.localMaster = static_cast<std::uint8_t>(std::stoul(tok.substr(0, colon)));
						} catch (...) {
							a_error = "master 下标不是数字：" + tok.substr(0, colon);
							return false;
						}
						tok = tok.substr(colon + 1);
					}
				}
				std::string hex = tok;
				if (hex.rfind("0x", 0) != 0 && hex.rfind("0X", 0) != 0) {
					hex = "0x" + hex;
				}
				return ParseFormID(hex, a_out);
			};

			auto needFormID = [&](std::uint32_t& a_out) -> bool {
				const auto toks = SplitWs(rest);
				if (toks.empty() || !parseFormIDToken(toks[0], a_out)) {
					a_error = "需要 FormID 参数（如 0x002A1B3C；DLC 任务用 ~0x记录号）";
					return false;
				}
				return true;
			};

			if (op == "ping") {
				a_step.kind = Kind::kCmd;
				a_step.op = Op::kPing;
				// ★★ 第 66 轮：ping 也支持 `timeout=`（不写就用命令默认窗口 ——
				//   见文件末尾 kCmd 分支的 kCommandAckTimeoutMs 取法）。
				rest = ExtractTimeout(rest, a_step.timeoutMs);
			} else if (op == "quest.reset" || op == "quest.start" || op == "quest.complete" || op == "teleport") {
				a_step.kind = Kind::kCmd;
				a_step.op = (op == "quest.reset")    ? Op::kQuestReset
					: (op == "quest.start")          ? Op::kQuestStart
					: (op == "quest.complete")       ? Op::kQuestComplete
													 : Op::kTeleport;
				if (!needFormID(a_step.formId)) {
					return false;
				}
			} else if (op == "teleport.entry") {
				// ★ 第 54 轮：传送到**任务板**（目标 = 候选链里此刻可得的第一个 —— 板自身 /
				//   新建常驻 marker / 同 cell 常驻兜底）。为什么需要：用例要「站远 / 走近」来
				//   触发候选复算（第 45/47 轮判据），而板所在 cell 决定了目标任务是否加载。
				a_step.kind = Kind::kCmd;
				a_step.op = Op::kTeleport;
				a_step.resolveAsEntry = true;
				const auto toks = SplitWs(rest);
				if (toks.empty() || !parseFormIDToken(toks[0], a_step.formId)) {
					a_error = "需要任务板 uID（如 0x0021001E）";
					return false;
				}
			} else if (op == "quest.stage") {
				a_step.kind = Kind::kCmd;
				a_step.op = Op::kQuestStage;
				const auto toks = SplitWs(rest);
				if (toks.size() < 2 || !parseFormIDToken(toks[0], a_step.formId)) {
					a_error = "需要 <FormID> <stage> 两个参数";
					return false;
				}
				try {
					a_step.num = static_cast<std::int32_t>(std::stol(toks[1]));
				} catch (...) {
					a_error = "stage 不是数字：" + toks[1];
					return false;
				}
			} else if (op == "quest.probe") {
				// ★★ 第 101 轮补丁：**只读**探针（不进 Papyrus 命令通道、不等回执、菜单开关不影响）——
				//   用与链式 / 进度门槛**同一个**引擎函数读任意 (quest, stage) 的 IsStageDone，
				//   把结果写进日志（可被 assert.log 取证，也进步骤结果 JSON）。
				//   为什么需要：第 101 轮 `r101_dlc_chain2_pass`（推 MQ03@4000）实测
				//   「写侧回执成功（Papyrus `=> 4000`）但链式判定与『已开始』零变化」——
				//   必须区分「写侧没生效」与「读侧读不到」；同类先例 = 第 99 轮 MQ01@10000。
				a_step.kind = Kind::kQuestProbe;
				const auto toks = SplitWs(rest);
				if (toks.empty() || !parseFormIDToken(toks[0], a_step.formId)) {
					a_error = "需要 <FormID> [stage...]（如 quest.probe ~0x00030C2B 100 4000）";
					return false;
				}
				for (std::size_t i = 1; i < toks.size(); ++i) {
					try {
						a_step.stages.push_back(static_cast<std::uint16_t>(std::stoul(toks[i])));
					} catch (...) {
						a_error = "stage 不是数字：" + toks[i];
						return false;
					}
				}
			} else if (op == "info.probe") {
				// ★★★ 第 106 轮（operator 全量产品化）：`info.probe <记录号>` —— 只读探针：
				//   报出该任务 INFO 门槛里**含 OR 位的对话组**的求值结果（组内走与产品相同的
				//   Decision::DecideProgressGates）+ 整任务结论（见 ProbeInfoGates）。
				//   参数 = **静态表内的记录号**（不是运行期 FormID —— 不需要 master 解析）。
				a_step.kind = Kind::kInfoProbe;
				const auto itoks = SplitWs(rest);
				if (itoks.empty() || !parseFormIDToken(itoks[0], a_step.formId)) {
					a_error = "需要 <记录号>（如 info.probe 0x001C7185）";
					return false;
				}
			} else if (op == "crew.probe") {
				// ★★★ 第 155 轮（可招募船员跟踪研究 · docs/16 16.3）：`crew.probe` ——
				//   **只读**探针：逐位读 24 位可招募船员（数据表 = 生成物
				//   SAQ_TestCrewProbe.h）的：
				//     ① crew faction 三件套成员状态 + 已分配（Papyrus op=7，
				//        `Actor.IsInFaction` —— 需要引用已加载；引用没加载的位跳过）；
				//     ② 招募载体任务 CREW_EliteCrew_* 的运行时状态（DLL 直读 ——
				//        不依赖引用加载，24/24 总有结果 ⇒ 判据的主证据）。
				//   用途：验证「已招募 ⇒ 隐藏」的判据（faction vs 任务状态，哪个可靠）。
				//   ★★★ 第 156 轮扩展：
				//     ③ **直读对照** —— 与产品 kind=2 过滤**同一套** DLL 直读
				//        （SAQ_Crew::ReadState）逐位读，与 Papyrus 值对照（不一致会带
				//        「对照=不一致」⇒ 用例反向断言）。
				//     ④ 可选 `sim=<FormID>` —— 全表读完后对这位做「模拟招募往返」
				//        （Papyrus op=8：Add → 读 → Remove → 读；净副作用为零）——
				//        「已招募 ⇒ 隐藏」判据的正样本复核（docs/16 16.8）。
				//   参数：可选 `timeout=`（总窗口）/ `sim=<FormID>`。
				a_step.kind = Kind::kCrewProbe;
				rest = ExtractTimeout(rest, a_step.timeoutMs);
				if (a_step.timeoutMs == kDefaultStepTimeoutMs) {
					a_step.timeoutMs = kCrewProbeTotalTimeoutMs;
				}
				for (const auto& tok : SplitWs(rest)) {
					if (tok.rfind("sim=", 0) == 0) {
						if (!parseFormIDToken(tok.substr(4), a_step.formId)) {
							a_error = "sim= 的 FormID 解析失败：" + tok.substr(4);
							return false;
						}
					} else {
						a_error = "不接受的参数：" + tok + "（可选 timeout= / sim=<FormID>）";
						return false;
					}
				}
			} else if (op == "ui.research") {
				// ★★★ 第 117 轮（无 SWF 覆盖的 UI 注入研究 · docs/15）：
				//   只用 GFx API 直接操作原版 MissionMenu 的 AS3 对象（**不经过我们 SWF
				//   里的任何入口**）—— 验证 U1 私有成员读写 / U2 public 方法调用 /
				//   U3 事件注入三项能力。参数可选：`events` = 同时做 U3（事件注册；
				//   单独一步便于定位问题，见 SAQ_UI.cpp 的 ResearchGfxCapabilities）。
				a_step.kind = Kind::kUiResearch;
				a_step.text = Trim(rest);
				a_step.timeoutMs = 5000;
			} else if (op == "ui.research2") {
				// ★★★ 第 119 轮（探针 v2 / P1.5 · docs/15 九·补）：第 118 轮判明
				//   U1 读不到 private（不碰 FilterInfoA）⇒ 本轮验证绕过路径：
				//   R1 成员枚举 / R2 事件拦截（selectionChange priority=100 +
				//   stopImmediatePropagation）/ R3 filterMask 哨兵写 / R4 SetTabsData
				//   补测。四段一次跑完（见 SAQ_UI.cpp 的 ResearchGfxInjection2）。
				a_step.kind = Kind::kUiResearch;
				a_step.text = "2";
				a_step.timeoutMs = 8000;
			} else if (op == "ui.research3") {
				// ★★★ 第 120 轮（P2 · 原版 SWF 完整 PoC · docs/15 九·补三/九·补四）：
				//   把「扩 tab + 拦截 + 列表数据注入」拼成原版环境下的完整链路
				//   （R1 环境 / R3 SetTabsData 7→8 / R4 切3 对照 / R5 切7 拦截哨兵 /
				//   R6 切0 放行 / R7 清理 / R9 InitializeEntries 注入）。
				//   一次跑完（见 SAQ_UI.cpp 的 ResearchGfxInjection3）。
				a_step.kind = Kind::kUiResearch;
				a_step.text = "3";
				a_step.timeoutMs = 8000;
			} else if (op == "ui.research4") {
				// ★★★ 第 130 轮（功能迁移探针 v4 · docs/15 十一）：把评估列的 5 个
				//   未知点一次问清（**原版 SWF** 上跑）：U5 按键接管（Data 读不到 ⇒
				//   走 CreateObject 带类名造真 AS3 实例 → 换按钮 Data → 程序化触发）、
				//   U6 引擎条目直读（GetDataForEntry）、U8 语言判定（引擎任务名 CJK）、
				//   U9 关闭原语（ProcessUserEvent）、U10 类通道（applicationDomain
				//   → BSUIDataManager 静态调用 + Subscribe("QuestData")）；
				//   另含 `bCanShowOnMap` ⇒ SET COURSE 置灰的数据驱动验证。
				//   一次跑完（见 SAQ_UI.cpp 的 ResearchGfxInjection4）。
				a_step.kind = Kind::kUiResearch;
				a_step.text = "4";
				a_step.timeoutMs = 10000;
			} else if (op == "ui.research4b") {
				// ★★★ 第 130 轮：探针 v4 第二段（**渲染层** —— U7 就地刷新
				//   （clip.itemIndex ↔ 数据下标 → SetEntryText → 竖条帧名）+
				//   U8b 渲染文本 + U9 关闭原语）。注入与读回之间必须隔一帧
				//   （P2 计划里 `wait 1200`，见 SAQ_UI.cpp 的 ResearchGfxInjection4b）。
				a_step.kind = Kind::kUiResearch;
				a_step.text = "4b";
				a_step.timeoutMs = 10000;
			} else if (op == "ui.inject") {
				// ★★★ 第 133 轮（P3 产品化 PoC · docs/15 11.7）：**真正的数据注入**
				//   （不是探针假数据）—— 把产品侧「待推送」的可接任务列表
				//   （`SAQ::PendingQuests()`，与 SWF 通道同一份数据）注进原版
				//   MissionMenu：扩 tab（7→8）+ 分时注入（切到我们 tab 拦截 + 注入 /
				//   切走恢复引擎快照）+ 对账读回。
				//   一次跑完（见 SAQ_UiInject.cpp 的 RunInjectPoC）。
				a_step.kind = Kind::kUiInject;
				a_step.text = Trim(rest);
				a_step.timeoutMs = 15000;
			} else if (op == "ui.mode") {
				// ★★★ 第 138 轮（P2 会话收口）：运行期强制 UI 形态 —— `swf` / `auto` /
				//   `inject` / `reset`（清除强制、回 ini 语义）。目的 = P2 计划的用例
				//   隔离：第 137 轮产品路径（UiMode=auto）上线后会在冲突环境**自动激活**
				//   注入（tab 7→8），而 `ui.research3` / `ui.inject` 探针假设「原版 7 tab
				//   干净环境」⇒ 必须先 `ui.mode swf` 关掉产品激活再跑探针（详见计划头）。
				//   生效范围 = 直到 `reset` 或进程结束（菜单打开时的 ini 解析被忽略）。
				a_step.kind = Kind::kUiMode;
				a_step.text = Trim(rest);
				a_step.timeoutMs = 3000;
				if (a_step.text.empty()) {
					a_error = "需要 swf|auto|inject|reset";
					return false;
				}
			} else if (op == "ui.interact") {
				// ★★★ 第 140 轮（P4 交互接管 · docs/15 十四节）：`ui.interact [key X|key Y|state]`
				//   —— 无参 = 接管判据链（装接管 + 分类 + dry 触发 + 激活拦截；一行汇总）；
				//   `key X|Y` = 真按键（走真实回调：引导 + 星图交接）；`state` = 只读状态
				//   （任务菜单 / 星图 / 引导 —— 星图交接的端到端判据）。
				//   一次性完成（不进 Papyrus 通道；**菜单必须开着**）。
				a_step.kind = Kind::kUiInteract;
				a_step.text = Trim(rest);
				a_step.timeoutMs = 15000;
				if (!a_step.text.empty()) {
					const auto toks = SplitWs(a_step.text);
					const bool okVerb = toks.size() == 2 && toks[0] == "key" &&
						(toks[1] == "X" || toks[1] == "Y");
					if (!okVerb && a_step.text != "state") {
						a_error = "只接受空 / key X / key Y / state（给的是 " + a_step.text + "）";
						return false;
					}
				}
			} else if (op == "wait") {
				a_step.kind = Kind::kWait;
				const auto toks = SplitWs(rest);
				if (toks.empty()) {
					a_error = "需要毫秒数";
					return false;
				}
				try {
					a_step.timeoutMs = static_cast<std::uint64_t>(std::stoull(toks[0]));
				} catch (...) {
					a_error = "wait 参数不是数字：" + toks[0];
					return false;
				}
			} else if (op == "menu.open" || op == "menu.close") {
				a_step.kind = Kind::kMenu;
				a_step.menuOpen = (op == "menu.open");
				a_step.timeoutMs = 8000;
			} else if (op == "menu.hide") {
				// ★ 第 54 轮：关掉**任意**菜单（用例收尾用，典型 = GalaxyStarMapMenu ——
				//   星图也是暂停菜单，不关掉的话游戏一直暂停、脚本定时器不走）。
				a_step.kind = Kind::kMenuHide;
				rest = ExtractTimeout(rest, a_step.timeoutMs);
				a_step.text = Trim(rest);
				a_step.timeoutMs = a_step.timeoutMs == kDefaultStepTimeoutMs ? 8000 : a_step.timeoutMs;
				if (a_step.text.empty()) {
					a_error = "需要菜单注册名（如 GalaxyStarMapMenu）";
					return false;
				}
			} else if (op == "ui.select" || op == "ui.selectchild" || op == "ui.key" ||
					   op == "ui.expand" || op == "ui.tab") {
				a_step.kind = Kind::kUi;
				a_step.text = Trim(rest);
				a_step.timeoutMs = 3000;
				if (op != "ui.tab" && a_step.text.empty()) {
					a_error = "需要参数（uID 或按键名）";
					return false;
				}
				// uID 习惯上写成 0x…（与日志一致），AS3 侧按十进制 Number 比较 ⇒ 这里转一次。
				// `~0x…`（记录号，多为 DLC 任务）**不在这里转** —— 运行期 FormID 要等静态表
				// 就绪，改成步骤开跑时解析（见 RunStep 的 kUi 分支）。
				// 转换失败就原样传（关键字参数，如 ui.key XButton）。
				if ((op == "ui.select" || op == "ui.selectchild" || op == "ui.expand") &&
					a_step.text.rfind("~", 0) == 0) {
					std::uint32_t uid = 0;
					if (!parseFormIDToken(a_step.text, uid)) {
						a_error = "uID 解析失败：" + a_step.text;
						return false;
					}
					// ★★ 第 57 轮修：这里**必须把解析值写回 a_step.formId** —— 漏了这一行，
					//   ResolveStepFormID 拿到的是 0 ⇒ 报「静态表里没有记录号 0x000000」。
					//   09:35 会话实证：`ui.selectchild ~0x0008EBDC`（营救机器人）因此 FAIL，
					//   而同一条 `quest.reset ~0x0008EBDC` 正常（那条走 needFormID 分支）。
					a_step.formId = uid;
					a_step.text.clear();  // 运行期值由 ResolveStepFormID 补上
				} else if ((op == "ui.select" || op == "ui.selectchild" || op == "ui.expand") &&
						   a_step.text.rfind("0x", 0) == 0) {
					std::uint32_t uid = 0;
					if (ParseFormID(a_step.text, uid)) {
						a_step.text = std::to_string(uid);
					}
				}
			} else if (op == "assert.log" || op == "assert.nolog" || op == "assert.ui") {
				a_step.kind = (op == "assert.log")    ? Kind::kAssertLog
					: (op == "assert.nolog")          ? Kind::kAssertNoLog
													 : Kind::kAssertUi;
				rest = ExtractTimeout(rest, a_step.timeoutMs);
				if (op != "assert.ui") {
					rest = ExtractScope(rest, a_step.logScope);
				}
				a_step.text = rest;
				if (a_step.text.empty()) {
					a_error = "需要正则表达式";
					return false;
				}
				// ★★ 第 68 轮：断言正则**解析期**编译一遍 —— 非法模式（例如把 `\d` 写成
				//   `\\d`：ECMAScript 下等于「字面反斜杠 + d」）在这里就报出来；不校验的话
				//   运行期 LogFind 只能静默 false ⇒ 症状是「日志里没出现 /…/」的误导性超时
				//   （15:24 会话 r67_chain 实测：正则写了双反斜杠，白查一轮）。
				try {
					const std::regex probe{ a_step.text, std::regex::ECMAScript | std::regex::icase };
					(void)probe;
				} catch (const std::regex_error&) {
					a_step.regexOk = false;
					REX::WARN("harness：断言正则非法（这一步必定失败）：{}", a_step.raw);
				}
			} else if (op == "assert.menu") {
				a_step.kind = Kind::kAssertMenu;
				const auto toks = SplitWs(ExtractTimeout(rest, a_step.timeoutMs));
				if (toks.empty() || (toks[0] != "open" && toks[0] != "closed")) {
					a_error = "需要 open|closed";
					return false;
				}
				a_step.menuOpen = (toks[0] == "open");
			} else if (op == "guide.clear") {
				a_step.kind = Kind::kGuideClear;
			} else if (op == "guide.probe") {
				// ★ 第 60 轮：`guide.probe ~0x…` —— 只读探针：把这条任务的候选池
				//   「此刻哪些取得到」写进步骤结果（不改任何状态，见 ProbeGuideCandidates）。
				a_step.kind = Kind::kGuideProbe;
				if (!needFormID(a_step.formId)) {
					return false;
				}
			} else if (op == "save.list") {
				// ★★ 第 62 轮（大项 I）：存档列表只读诊断 —— 单例 / built / count /
				//   前几个存档名（判「BGSSaveLoadManager 偏移对不对」的第一现场）。
				a_step.kind = Kind::kSaveList;
			} else if (op == "save.load") {
				// ★★ 第 62 轮：自动读档 —— `save.load <存档名子串>`（大小写不敏感）。
				//   驱动器：排队 → 等「加载画面消失 + 连续静默 2 秒 + 距排队 ≥5 秒 +
				//   通道重新就绪」⇒ 这一步才算完（整个过程默认给 120 秒）。
				a_step.kind = Kind::kSaveLoad;
				rest = ExtractTimeout(rest, a_step.timeoutMs);
				a_step.text = Trim(rest);
				if (a_step.text.empty()) {
					a_error = "需要存档名子串（如 save.load Save7_3AB5A2FA）";
					return false;
				}
			} else if (op == "note") {
				a_step.kind = Kind::kNote;
				a_step.text = Trim(rest);
			} else {
				a_error = "未知步骤：" + op;
				return false;
			}

			// 命令类步骤的回执窗口（见 kCommandAckTimeoutMs 的说明）。
			// ★ 第 56 轮：传送例外 —— MoveTo 的等待窗口由 cell 加载决定，见 kTeleportAckTimeoutMs。
			// ★★ 第 66 轮：**不写 `timeout=` 就用 kCommandAckTimeoutMs** —— 此前是
			//   `min(step.timeoutMs, kCommandAckTimeoutMs)`，而 step 的默认值
			//   kDefaultStepTimeoutMs(5000) 会把窗口封在 5 秒（14:35 会话那次 3.4 秒的
			//   节拍停摆只剩 1.6 秒余量）。写在用例里的 `timeout=` 仍然生效（调小可用，
			//   调大封顶在 kCommandAckTimeoutMs）。
			if (a_step.kind == Kind::kCmd) {
				if (a_step.op == Op::kTeleport) {
					a_step.timeoutMs = kTeleportAckTimeoutMs;
				} else if (a_step.timeoutMs == kDefaultStepTimeoutMs) {
					a_step.timeoutMs = kCommandAckTimeoutMs;
				} else {
					a_step.timeoutMs = std::min(a_step.timeoutMs, kCommandAckTimeoutMs);
				}
			}
			return true;
		}

		void ParsePlan(const std::string& a_path)
		{
			g_cases.clear();
			std::ifstream f{ a_path.c_str(), std::ios::binary };
			if (!f) {
				REX::WARN("harness：读不到用例文件 {}（[Test] Plan 指向它）", a_path);
				return;
			}
			std::string line;
			Case* cur = nullptr;
			std::size_t lineNo = 0;
			std::size_t bad = 0;
			while (std::getline(f, line)) {
				++lineNo;
				if (!line.empty() && line.back() == '\r') {
					line.pop_back();
				}
				if (lineNo == 1 && line.size() >= 3 &&
					static_cast<unsigned char>(line[0]) == 0xEF &&
					static_cast<unsigned char>(line[1]) == 0xBB &&
					static_cast<unsigned char>(line[2]) == 0xBF) {
					line.erase(0, 3);  // UTF-8 BOM（记事本另存会加；不剥会让第一行解析失败）
				}
				const std::string trimmed = Trim(line);
				if (trimmed.empty() || trimmed[0] == ';' || trimmed[0] == '#') {
					continue;
				}
				if (trimmed[0] == '[') {
					const auto close = trimmed.find(']');
					if (close == std::string::npos) {
						REX::WARN("harness：用例文件第 {} 行缺少 ']'：{}", lineNo, trimmed);
						++bad;
						continue;
					}
					std::string header = trimmed.substr(1, close - 1);
					if (header.rfind("case:", 0) != 0) {
						REX::WARN("harness：用例文件第 {} 行不是 [case:...]：{}", lineNo, trimmed);
						++bad;
						continue;
					}
					g_cases.emplace_back();
					cur = &g_cases.back();
					cur->id = Trim(header.substr(5));
					continue;
				}
				const auto eq = trimmed.find('=');
				if (eq == std::string::npos) {
					REX::WARN("harness：用例文件第 {} 行不是 key = value：{}", lineNo, trimmed);
					++bad;
					continue;
				}
				if (cur == nullptr) {
					REX::WARN("harness：用例文件第 {} 行在 [case:...] 之前：{}", lineNo, trimmed);
					++bad;
					continue;
				}
				const std::string key = Trim(trimmed.substr(0, eq));
				const std::string value = Trim(trimmed.substr(eq + 1));
				if (key == "desc") {
					cur->desc = value;
				} else if (key == "step") {
					Step st;
					std::string err;
					if (ParseStep(value, st, err)) {
						cur->steps.push_back(std::move(st));
					} else {
						REX::WARN("harness：用例 {} 第 {} 行的步骤解析失败（{}）：{}", cur->id, lineNo, err, value);
						// ★★ 第 69 轮：解析失败 = 这条用例直接判 FAIL（见 Case::parseError）。
						if (cur->parseError.empty()) {
							cur->parseError = std::format("第 {} 行步骤解析失败（{}）：{}",
								lineNo, err, value);
						}
						++bad;
					}
				} else {
					REX::WARN("harness：用例文件第 {} 行的未知键 {}（只认 desc / step）", lineNo, key);
					if (cur->parseError.empty()) {
						cur->parseError = std::format("第 {} 行未知键 {}（只认 desc / step）", lineNo, key);
					}
					++bad;
				}
			}
			std::size_t total = 0;
			for (const auto& c : g_cases) {
				total += c.steps.size();
			}
			REX::INFO("harness：用例文件已载入（{} 个用例 / {} 个步骤{}）—— {}", g_cases.size(), total,
				bad ? std::format("，{} 行解析失败（见上面 WARN）", bad) : std::string{},
				a_path);
			for (const auto& c : g_cases) {
				REX::INFO("harness：  用例 {}（{} 步）{}", c.id, c.steps.size(), c.desc.empty() ? "" : " —— " + c.desc);
			}
		}

		std::string PlanPathFromIni(std::string& a_detail)
		{
			const auto dir = PluginDir();
			if (dir.empty()) {
				a_detail = "插件目录取不到";
				return {};
			}
			const auto iniPath = (dir / L"SAQ_ShowAvailableQuests.ini").wstring();
			wchar_t buf[MAX_PATH]{};
			::GetPrivateProfileStringW(L"Test", L"Plan", L"SAQ_TestPlan.txt", buf, MAX_PATH, iniPath.c_str());
			const auto path = dir / buf;
			a_detail = path.string();
			return path.string();
		}

		// ----------------------------------------------------------------
		//  结果落盘
		// ----------------------------------------------------------------
		void WriteResults()
		{
			const auto dir = PluginDir();
			if (dir.empty()) {
				return;
			}
			const auto path = dir / L"SAQ_testresults.json";

			std::size_t pass = 0, fail = 0, skip = 0;
			for (const auto& r : g_results) {
				if (r.status == "PASS") ++pass;
				else if (r.status == "FAIL") ++fail;
				else if (r.status == "SKIP") ++skip;
			}

			SYSTEMTIME st{};
			::GetLocalTime(&st);

			std::string out;
			out += "{\n";
			out += std::format("  \"generatedAt\": \"{:04}-{:02}-{:02} {:02}:{:02}:{:02}\",\n",
				st.wYear, st.wMonth, st.wDay, st.wHour, st.wMinute, st.wSecond);
			out += std::format("  \"sessionMs\": {},\n", NowMs() - g_sessionStartMs);
			out += std::format("  \"plan\": \"{}\",\n", JsonEscape(g_planPath));
			out += std::format("  \"summary\": {{ \"cases\": {}, \"pass\": {}, \"fail\": {}, \"skip\": {} }},\n",
				g_results.size(), pass, fail, skip);
			out += "  \"results\": [\n";
			for (std::size_t i = 0; i < g_results.size(); ++i) {
				const auto& r = g_results[i];
				out += "    {\n";
				out += std::format("      \"id\": \"{}\",\n", JsonEscape(r.id));
				out += std::format("      \"desc\": \"{}\",\n", JsonEscape(r.desc));
				out += std::format("      \"status\": \"{}\",\n", r.status);
				out += std::format("      \"elapsedMs\": {},\n", r.elapsedMs);
				if (!r.reason.empty()) {
					out += std::format("      \"reason\": \"{}\",\n", JsonEscape(r.reason));
				}
				out += "      \"steps\": [\n";
				for (std::size_t j = 0; j < r.steps.size(); ++j) {
					const auto& s = r.steps[j];
					out += "        {";
					out += std::format("\"op\": \"{}\", \"status\": \"{}\", \"elapsedMs\": {}",
						JsonEscape(s.op), s.pass ? "PASS" : "FAIL", s.elapsedMs);
					if (!s.detail.empty()) {
						out += std::format(", \"detail\": \"{}\"", JsonEscape(s.detail));
					}
					if (!s.evidence.empty()) {
						out += std::format(", \"evidence\": \"{}\"", JsonEscape(s.evidence));
					}
					out += "}";
					out += (j + 1 < r.steps.size()) ? ",\n" : "\n";
				}
				out += "      ]\n";
				out += "    }";
				out += (i + 1 < g_results.size()) ? ",\n" : "\n";
			}
			out += "  ]\n}\n";

			// ★ 用「先删后写」而不是 std::ofstream 直接写：MO2 的 usvfs 下要保证文件落在
			//   mod 目录（部署时已预建空文件，见 build-saq.ps1 的部署步骤）。
			std::ofstream f{ path.c_str(), std::ios::binary | std::ios::trunc };
			if (!f) {
				REX::WARN("harness：结果文件写不进去（{}）—— 结果只在日志里", path.string());
				return;
			}
			f.write("\xEF\xBB\xBF", 3);  // BOM：记事本/编辑器都认 UTF-8（含中文细节）
			f.write(out.data(), static_cast<std::streamsize>(out.size()));
			f.close();
			g_wroteResults = true;
			REX::INFO("harness：结果已写入 {}（{} 个用例：PASS {} / FAIL {} / SKIP {}）",
				path.string(), g_results.size(), pass, fail, skip);
		}

		// ----------------------------------------------------------------
		//  用例/步骤推进
		// ----------------------------------------------------------------
		// ★ 第 55 轮：用例结束（含失败中止）时的**清场**。
		//
		//  实测（09:06 会话，6 条用例全 FAIL 的真因之二）：smoke 的 R 链路会由脚本
		//  打开星图（产品行为、正确）—— 用例因断言假失败中止后，星图留在屏幕上 ⇒
		//  游戏暂停 ⇒ 脚本定时器冻结 ⇒ 后面 5 条用例的 `ping` 全部超时（3000 ms）。
		//  第 54 轮只在 finishAll（**全部**用例跑完）时清场，来不及救中间的用例。
		//
		//  顺序有意：**先清引导**（写通道；脚本下一拍会把「待打开的星图」待办作废，
		//  见 SAQ_Main.psc 的 ApplyGuide「任何一次新请求先作废星图待办」）—— 否则
		//  在游戏恢复运行的瞬间，残留的星图待办可能又开一次星图。
		//  动作都是「请求」级别（引擎下一帧处理），用例之间的间隔（kInterCaseDelayMs）
		//  给它留时间。
		void CleanupAfterCase()
		{
			std::string detail;
			if (!ClearGuide(detail)) {
				REX::INFO("harness：用例收尾：清引导没成功（{}）—— 多半本来就没有引导", detail);
			}
			if (MissionMenuIsOpen()) {
				if (SetMenuOpen(false, detail)) {
					REX::INFO("harness：用例收尾：任务菜单还开着 —— 已请求关闭（{}）", detail);
				}
			}
			// ★★ 第 83 轮：清场这一刻星图**就已经开着**（r44 式用例：R 的星图在用例内
			//   就打开了）⇒ 不会再有「稍后才打开」那一幕 —— 关掉它，并把延迟复查窗口
			//   缩短成「只等引擎把 kHide 处理掉」；否则白等满 4 秒。
			bool starMapOpenNow = false;
			if (MenuIsOpen("GalaxyStarMapMenu")) {
				if (SetMenuOpenByName("GalaxyStarMapMenu", false, detail)) {
					REX::INFO("harness：用例收尾：星图还开着 —— 已请求关闭（{}）", detail);
					starMapOpenNow = true;
				}
			}
			// ★★ 第 57 轮：本用例按过 R（请求过星图）⇒ 开一段延迟复查窗口 —— 星图很可能
			//   在清场**之后**才真的打开（见 g_cleanupRecheckUntilMs 的注释）。
			if (g_caseStarMapRisk) {
				g_cleanupRecheckUntilMs = NowMs() + (starMapOpenNow ? kInterCaseDelayMs
																   : kCleanupRecheckWindowMs);
				g_nextCaseAtMs = std::max(g_nextCaseAtMs, NowMs() + kInterCaseDelayMs);
				REX::INFO("harness：用例收尾：本条按过 R —— 延迟复查窗口开启（{} ms{}）",
					starMapOpenNow ? kInterCaseDelayMs : kCleanupRecheckWindowMs,
					starMapOpenNow ? "；星图已在清场时关掉，只等关闭生效" : "");
			}
		}

		// ★★ 第 57 轮：延迟复查的一次检查（由 Tick 每帧调用，直到窗口结束）。
		//   返回语义：无（窗口是否结束由 g_cleanupRecheckUntilMs 表达）。
		void CleanupRecheck()
		{
			std::string detail;
			bool closedStarMap = false;
			if (MenuIsOpen("GalaxyStarMapMenu")) {
				if (SetMenuOpenByName("GalaxyStarMapMenu", false, detail)) {
					REX::INFO("harness：用例收尾复查：星图在清场后才打开 —— 已请求关闭（{}）", detail);
					closedStarMap = true;
					// 刚请求关闭星图 ⇒ 别立刻开下一条：等引擎把 kHide 处理掉
					// （星图也是暂停菜单：没关掉就切下一条，`ping` 会撞上「游戏仍暂停」）。
					g_nextCaseAtMs = std::max(g_nextCaseAtMs, NowMs() + kInterCaseDelayMs);
				}
			}
			if (MissionMenuIsOpen()) {
				if (SetMenuOpen(false, detail)) {
					REX::INFO("harness：用例收尾复查：任务菜单还开着 —— 已请求关闭（{}）", detail);
				}
			}
			// ★★ 第 83 轮修：**只有真的看到并关掉星图**才算「稍后打开那一幕已经发生」——
			//   第 57 轮的实现把「关掉残留的任务菜单」也当成结束条件。22:52 会话实测的真因：
			//   r81 用例在 `ui.tab` 失败中止时，清场复查先关掉残留的任务菜单 ⇒ 窗口被提前
			//   结束 ⇒ 约 1 秒后才由**脚本节拍**打开的星图没人管 ⇒ 下一条用例的 `ping`
			//   在「星图开着（暂停、脚本定时器冻结）」下超时 FAIL（三条 FAIL 里的第三条）。
			if (closedStarMap || NowMs() >= g_cleanupRecheckUntilMs) {
				g_cleanupRecheckUntilMs = 0;
			}
		}

		// ★★ 第 58 轮：判定「游戏端卡死」并中止剩余用例。
		//
		//  为什么需要（10:31 会话的实测）：一条 `teleport.entry` 把游戏卡在加载画面后，
		//  r48/r44 两条用例各自白等一次超时 —— 它们只是同一次卡死的陪葬，却在报告里
		//  显示成两个独立失败。现在：一旦确认（此刻有加载画面，或连续多次命令无回执），
		//  就把剩余用例标成 SKIP 并写明原因，报告一眼可读。
		//
		//  ★ 顺手做一次**安全冲刷**：把通道里最新一条命令换成无害的 Ping。脚本只执行
		//    「最新序号」那条命令（见 SAQ_Main.psc 的 ProcessTestCommand）—— 如果游戏
		//    之后自己恢复了，它执行的会是这条 Ping，而不是「卡住时排队的那条传送」
		//    （否则玩家会莫名其妙被传走）。
		void MarkStuck(const std::string& a_why)
		{
			if (g_stuckAbort) {
				return;
			}
			g_stuckAbort = true;
			g_stuckReason = a_why;
			std::string detail;
			if (Submit(Op::kPing, 0, 0, detail)) {
				Abandon("游戏端卡死冲刷（用 Ping 顶掉通道里未执行的命令）");
			}
			REX::WARN("harness：游戏端疑似卡死 —— {}；剩余用例将全部 SKIP（证据见结果 JSON）", a_why);
		}

		// ★★ 第 58 轮：卡死中止时，把没跑到的用例补成 SKIP（报告里不缺项、原因统一）。
		void FillRemainingSkipped()
		{
			while (g_results.size() < g_cases.size()) {
				const auto idx = g_results.size();
				CaseResult r;
				r.id = g_cases[idx].id;
				r.desc = g_cases[idx].desc;
				r.status = "SKIP";
				r.reason = "游戏端疑似卡死（未执行）：" + g_stuckReason;
				g_results.push_back(std::move(r));
			}
		}

		void FinishCase(bool a_ok, const std::string& a_reason)
		{
			if (g_caseIdx >= g_results.size()) {
				return;
			}
			auto& r = g_results[g_caseIdx];
			r.elapsedMs = NowMs() - g_caseStartedMs;
			if (a_ok) {
				r.status = "PASS";
				REX::INFO("harness：用例 {} PASS（{} ms）", r.id, r.elapsedMs);
			} else {
				r.status = a_reason.empty() ? "FAIL" : "SKIP";
				r.reason = a_reason;
				if (a_reason.empty()) {
					REX::WARN("harness：用例 {} FAIL（{} ms）—— 详细证据见 SAQ_testresults.json", r.id, r.elapsedMs);
				} else {
					REX::WARN("harness：用例 {} SKIP —— {}", r.id, a_reason);
				}
			}
			g_active = false;
			g_stepIdx = 0;
			// ★ 第 55 轮：用例一结束（无论 PASS/FAIL）就清场 —— 见 CleanupAfterCase；
			//   再留一段间隔，让引擎把菜单关闭处理完，然后才开下一条用例。
			CleanupAfterCase();
			g_nextCaseAtMs = NowMs() + kInterCaseDelayMs;
		}

		void StartCase(std::size_t a_index)
		{
			g_caseIdx = a_index;
			g_stepIdx = 0;
			g_cur = StepState{};
			g_caseStarMapRisk = false;  // ★ 第 57 轮：延迟复查窗口的触发标记，按用例清零
			g_caseStartedMs = NowMs();
			// ★ 第 54 轮：`scope=case` 的窗口起点（本用例第一行日志之前）；
			//   同时把 g_cur.logMark 也钉在这里 —— 否则第一步的 `scope=prev` 会退化成
			//   「整个环形缓冲」（g_cur 刚被重置成 0）。
			g_caseMark = LogMark();
			g_prevMark = g_caseMark;
			g_cur.logMark = g_caseMark;
			CaseResult r;
			r.id = g_cases[a_index].id;
			r.desc = g_cases[a_index].desc;
			g_results.push_back(std::move(r));
			g_active = true;
			REX::INFO("harness：===== 开始用例 {}（{}）=====", g_cases[a_index].id,
				g_cases[a_index].desc.empty() ? g_cases[a_index].id : g_cases[a_index].desc);
			// ★★ 第 69 轮：用例文件解析失败 ⇒ 立刻判 FAIL（证据进结果 JSON 的 parse 步骤）。
			//   老行为只留 WARN + 丢步 ⇒ 用例照样能 PASS（少测一步看不出来）。
			if (!g_cases[a_index].parseError.empty()) {
				StepResult sr;
				sr.op = "parse";
				sr.pass = false;
				sr.detail = "用例文件解析失败（修复用例文件后重跑）：" + g_cases[a_index].parseError;
				g_results.back().steps.push_back(std::move(sr));
				FinishCase(false, "");
			}
		}

		// 步骤成功/失败收尾（写结果 + 推进）
		void CompleteStep(bool a_pass, const std::string& a_detail, const std::string& a_evidence)
		{
			const auto& step = g_cases[g_caseIdx].steps[g_stepIdx];
			StepResult sr;
			sr.op = step.raw;
			sr.pass = a_pass;
			sr.detail = a_detail;
			sr.evidence = a_evidence;
			sr.elapsedMs = NowMs() - g_cur.startedAtMs;
			g_results[g_caseIdx].steps.push_back(std::move(sr));

			if (a_pass) {
				REX::INFO("harness：  [PASS] {}（{} ms）{}", step.raw, sr.elapsedMs,
					a_detail.empty() ? "" : " —— " + a_detail);
				++g_stepIdx;
				// ★★ 第 56 轮修复（09:22 会话实测）：**不能**把 logMark 一起清 0 ——
				//   下一步开跑时会做 `g_prevMark = g_cur.logMark` ⇒ 0 ⇒ 所有 `scope=prev`
				//   断言退化成「整个环形缓冲」：既会匹配到本会话最早那几行（假 PASS，
				//   r26/r47/r48/r44 四条用例都中招），又会把早就翻篇的行当成「不该出现」
				//   （r48 的假 FAIL，报文里那句「窗口从 idx 0 起」就是它）。
				const auto keepMark = g_cur.logMark;
				g_cur = StepState{};
				g_cur.logMark = keepMark;
				if (g_stepIdx >= g_cases[g_caseIdx].steps.size()) {
					FinishCase(true, {});
				}
				return;
			}

			REX::WARN("harness：  [FAIL] {}（{} ms）—— {}", step.raw, sr.elapsedMs, a_detail);
			// 一条用例失败就停（后面的步骤多半也没意义），把证据留在结果里
			FinishCase(false, {});  // 空 reason ⇒ FAIL（不是 SKIP）
		}

		// 返回值：true = 这一步已经处理完（成功或失败都已收尾）
		bool RunStep(bool a_menuOpen)
		{
			const Case& c = g_cases[g_caseIdx];
			const Step& step = c.steps[g_stepIdx];
			const std::uint64_t now = NowMs();

			if (!g_cur.started) {
				g_cur.started = true;
				g_cur.startedAtMs = now;
				// ★ 第 54 轮：`scope=prev` 要的是**上一步**的起点 —— 先把当前记成"上一步"，
				//   再取这一刻的打点作为本步骤的窗口起点（顺序不能反）。
				g_prevMark = g_cur.logMark;
				g_cur.logMark = LogMark();
				// menu.open / menu.close 的 deadline 从「发动之后」开始算
				g_cur.deadlineMs = now + step.timeoutMs;
			}

			auto timeoutFail = [&](const std::string& a_what, const std::string& a_extra) {
				CompleteStep(false, a_what + "（超时 " + std::to_string(step.timeoutMs) + " ms；" + a_extra + "）",
					LogSince(g_cur.logMark, kEvidenceMaxLines));
			};

			switch (step.kind) {
			case Kind::kNote:
				REX::INFO("harness：  [note] {}", step.text);
				CompleteStep(true, step.text, {});
				return true;

			case Kind::kGuideClear: {
				std::string detail;
				if (!ClearGuide(detail)) {
					CompleteStep(false, detail, LogSince(g_cur.logMark, kEvidenceMaxLines));
					return true;
				}
				// 真正生效要等脚本的轮询节拍（菜单关着时）—— 这里只确认请求已下发。
				CompleteStep(true, detail + "（脚本下一拍清除）", {});
				return true;
			}

			case Kind::kGuideProbe: {
				std::uint32_t formID = step.formId;
				if (step.localFormID) {
					std::string resolved;
					if (!ResolveStepFormID(step, formID, resolved)) {
						CompleteStep(false, "FormID 解析失败：" + resolved, {});
						return true;
					}
					REX::INFO("harness：  参数解析 {}", resolved);
				}
				std::string detail;
				if (!ProbeGuideCandidates(formID, detail)) {
					CompleteStep(false, detail, LogSince(g_cur.logMark, kEvidenceMaxLines));
					return true;
				}
				// ★★★ 第 147 轮（r146 首跑收口 · 补记「红线六」）：探针结果必须**同时打一行
				//   产品日志** —— `assert.log` 只认产品行（`LogFind` 跳过一切含 `harness：`
				//   的行 = 第 56 轮防回声红线）。本 op（第 60 轮）此前只把结果放进
				//   `[PASS] guide.probe …` 步骤行 ⇒ 第 146 轮新用例 r146_vkaiz02_fb 第一次
				//   对探针输出做 assert.log，当场**假 FAIL**（步骤自身 PASS、断言超时、
				//   evidence 为空 —— 与第 104 轮 quest.probe 踩过的完全同型）。
				//   修法照抄 kQuestProbe：结果照打一行产品日志，断言语义不变。
				REX::INFO("引导探针 {}", detail);
				// 结果进步骤结果（SAQ_testresults.json）—— 「走远后候选是否仍可得」的硬证据。
				CompleteStep(true, detail, {});
				return true;
			}

			case Kind::kSaveList: {
				CompleteStep(true, SaveGameListSummary(), {});
				return true;
			}

			case Kind::kQuestProbe: {
				// ★★ 第 101 轮补丁：只读探针 —— 一次性完成（不等回执；菜单开着也能跑）。
				//   detail 里带 `stageDone(N)=0/1` ⇒ 用例可以 assert.log 取证，
				//   结果也会原样进 SAQ_testresults.json 的步骤 detail（失败现场的第一证据）。
				std::uint32_t formID = step.formId;
				if (step.localFormID) {
					std::string resolved;
					if (!ResolveStepFormID(step, formID, resolved)) {
						CompleteStep(false, "FormID 解析失败：" + resolved, {});
						return true;
					}
					REX::INFO("harness：  参数解析 {}", resolved);
				}
				const auto probe = ProbeQuestStages(formID, step.stages);
				// ★★ 第 104 轮（2026-09-22 22:40 会话 r98 B 段 FAIL 的定调用）：探针结果
				//   必须**同时打一行产品日志** —— `assert.log` 只认产品行（`LogFind` 跳过
				//   一切含 `harness：` 的行，第 56 轮红线防回声），而 probe 输出此前只出现在
				//   `[PASS] quest.probe …` 这条 harness 步骤行里 ⇒ 第 103 轮 r98 B 段的
				//   5 条 probe 断言**全部必然假 FAIL**（步骤自身 PASS、断言却超时；报文
				//   「窗口从 idx … 起」+「本步骤之后没有产生任何日志行」就是它）。
				//   ★ 只加这一行产品日志，不改任何判据语义：断言的窗口规则照旧适用。
				REX::INFO("任务探针 {}", probe);
				CompleteStep(true, probe, {});
				return true;
			}

			case Kind::kInfoProbe: {
				// ★★★ 第 106 轮（operator 全量产品化）：只读探针 —— 一次性完成
				//   （不等回执；菜单开着也能跑，与 quest.probe 同款）。
				//   红线六（第 104 轮）：探针结果必须**同时打一行产品日志** ——
				//   `assert.log` 只认产品行（LogFind 跳过一切含 `harness：` 的行）。
				const auto probe = ProbeInfoGates(step.formId);
				REX::INFO("信息探针 {}", probe);
				CompleteStep(true, probe, {});
				return true;
			}

			case Kind::kCrewProbe: {
				// ★★★ 第 155 轮（可招募船员跟踪研究 · docs/16 16.3）：**只读**探针 ——
				//   逐位读 24 位可招募船员（表 = SAQ_TestCrewProbe.h 生成物）：
				//     ① crew faction 三件套成员状态 + 已分配（Papyrus op=7 的
				//        `Actor.IsInFaction` / `GetCrewAssignment` —— 引用没加载就读不到，
				//        跳过该位；这是引擎限制，如实记录）；
				//     ② 招募载体任务 CREW_EliteCrew_* 的运行时状态（DLL 直读 ——
				//        不依赖引用加载，24/24 总有结果 ⇒ 判据的主证据）。
				//   为什么这样配对：判据「已招募 ⇒ 隐藏」的候选来源 = faction 状态或
				//   任务状态，实机数据说话（faction 只有站在附近才读得到）。
				//   红线六（第 104 轮）：逐位行 + 汇总行都打**产品日志**（assert.log
				//   只认产品行，LogFind 跳过一切含 `harness：` 的行）。
				//   时序：命令只在菜单关着时被脚本消化（第 27 轮定案）⇒ 开着先请求关闭。
				if (a_menuOpen) {
					std::string detail;
					SetMenuOpen(false, detail);
					return false;
				}
				if (now >= g_cur.deadlineMs) {
					timeoutFail("船员探针没有跑完",
						std::format("已处理 {}/{} 位；连续无回执 {} 次",
							g_cur.crewIndex, kCrewProbeCount, g_cur.crewTimeouts));
					return true;
				}

				// 逐位报告的一行（产品日志 + 结果 JSON 的 detail 累积）。
				auto emit = [&](std::size_t a_idx, const std::string& a_papyrus, bool a_read,
								unsigned a_mask) {
					const auto& info = kCrewProbeTable[a_idx];
					const auto* q = RE::TESForm::LookupByID(info.questForm);
					std::string qt;
					if (q == nullptr) {
						qt = "表单取不到";
						++g_cur.crewQOther;
					} else {
						const auto st = ReadQuestRuntimeState(q);
						qt = Describe(st);
						if (!st.readOk) {
							++g_cur.crewQOther;
						} else if (st.completed) {
							++g_cur.crewQDone;
						} else if (st.running) {
							++g_cur.crewQRunning;
						} else if (!st.started) {
							++g_cur.crewQNotStarted;
						} else {
							++g_cur.crewQOther;
						}
					}
					if (a_read) {
						++g_cur.crewRead;
						g_cur.crewA += (a_mask & 1u) ? 1 : 0;
						g_cur.crewC += (a_mask & 2u) ? 1 : 0;
						g_cur.crewP += (a_mask & 4u) ? 1 : 0;
						g_cur.crewAssign += (a_mask & 8u) ? 1 : 0;
					}
					// ★★★ 第 156 轮：直读对照（与产品 kind=2 过滤同一套 SAQ_Crew::ReadState）——
					//   「Papyrus 与直读都读到」的位参与对照（三者 A/C/P 全同 = 一致）。
					//   用途：产品过滤用的是直读 ⇒ 直读的正确性必须被独立来源（Papyrus）
					//   钉死；不一致会打「对照=不一致」+ 用例反向断言（见 r155）。
					const auto direct = Crew::ReadState(info.refForm);
					std::string directText = direct.readable
						? std::format("A={} C={} P={}",
							direct.available ? 1 : 0, direct.current ? 1 : 0,
							direct.potential ? 1 : 0)
						: std::string{ "引用未加载" };
					std::string cmpText;
					if (direct.readable) {
						++g_cur.crewDirectRead;
					}
					if (a_read && direct.readable) {
						++g_cur.crewDirectPairs;
						const bool same = ((a_mask & 1u) != 0) == direct.available &&
							((a_mask & 2u) != 0) == direct.current &&
							((a_mask & 4u) != 0) == direct.potential;
						if (!same) {
							++g_cur.crewMismatch;
							cmpText = "｜对照=不一致";  // ← 用例反向断言盯这个（正常恒不出现）
						} else {
							cmpText = "｜对照=一致";
						}
					}
					std::string line = std::format(
						"[{}/{}] {}（0x{:08X}）｜Papyrus: {}｜直读: {}｜招募任务 {}{}",
						a_idx + 1, kCrewProbeCount, info.nameZh, info.refForm, a_papyrus,
						directText, qt, cmpText);
					REX::INFO("船员探针 {}", line);
					g_cur.crewReport += "船员探针 " + line + "\n";
				};

				while (g_cur.crewIndex < kCrewProbeCount) {
					const auto idx = g_cur.crewIndex;
					const auto& info = kCrewProbeTable[idx];
					if (!g_cur.crewSubmitted) {
						// 引用可读性预检（与 Papyrus `Game.GetForm` 同源：非常驻引用在
						// 所在 cell 未加载时取不到）—— 不可读就不必走 Papyrus（省一次往返）。
						if (RE::TESForm::LookupByID(info.refForm) == nullptr) {
							emit(idx, "引用未加载（A/C/P 读不到）", false, 0);
							++g_cur.crewIndex;
							continue;
						}
						std::string detail;
						if (!Submit(Op::kCrewFaction, info.refForm, 0, detail)) {
							CompleteStep(false,
								std::format("提交（{}）失败：{}", info.nameZh, detail),
								LogSince(g_cur.logMark, kEvidenceMaxLines));
							return true;
						}
						g_cur.crewSubmitted = true;
						return false;  // 等回执（下一 Tick 继续）
					}
					// 已提交：等回执
					std::int32_t code = 0;
					std::string detail;
					const int rc = Poll(code, detail);
					if (rc == 0) {
						if (now - SubmittedAtMs() >= kCrewProbeAckTimeoutMs) {
							Abandon("crew.probe 等回执超时");
							emit(idx, std::format("等回执超时（{} ms）", kCrewProbeAckTimeoutMs), false, 0);
							g_cur.crewSubmitted = false;
							++g_cur.crewIndex;
							if (++g_cur.crewTimeouts >= kCrewProbeMaxTimeouts) {
								CompleteStep(false,
									std::format("连续 {} 位没有回执（脚本僵死？）—— 已中止（明细见 detail）",
										g_cur.crewTimeouts),
									LogSince(g_cur.logMark, kEvidenceMaxLines));
								return true;
							}
							continue;
						}
						return false;  // 继续等
					}
					if (rc < 0) {
						CompleteStep(false, "命令通道不可用：" + detail,
							LogSince(g_cur.logMark, kEvidenceMaxLines));
						return true;
					}
					// rc == 1：回执到了
					g_cur.crewTimeouts = 0;
					g_cur.crewSubmitted = false;
					++g_cur.crewIndex;
					if (code >= 16) {
						// 结果码 = 16 + 状态位（bit0 A / bit1 C / bit2 P / bit3 已分配）
						const unsigned mask = static_cast<unsigned>(code - 16);
						emit(idx,
							std::format("A={} C={} P={} 分配={}",
								(mask & 1u) ? 1 : 0, (mask & 2u) ? 1 : 0,
								(mask & 4u) ? 1 : 0, (mask & 8u) ? 1 : 0),
							true, mask);
					} else if (code == 1) {
						emit(idx, "取不到（引用 / cell 未加载？）", false, 0);
					} else {
						emit(idx, std::format("失败（结果码 {}：{}）", code, ResultText(code)), false, 0);
					}
				}

				// ★★★ 第 156 轮：阶段 2 —— **模拟招募往返**（可选 `sim=<FormID>`）。
				//   用途（docs/16 16.8）：「已招募 ⇒ 隐藏」判据（A 位）的正样本复核 ——
				//   对一位未招募（A=0）的船员走一遍 `AddToAvailableCrew → 读 → Remove
				//   → 读`（官方 `Recruited()` 内的同一条引擎调用；净副作用为零），
				//   看 A 位是否 0→1。A=1 的位 Papyrus 侧跳过写入（不碰既有状态）。
				if (step.formId != 0 && !g_cur.crewSimDone) {
					const std::uint32_t simRef = step.formId;
					std::string simName;  // 表内查名字（不在表里也允许 —— 用 0x… 代替）
					for (const auto& ci : kCrewProbeTable) {
						if (ci.refForm == simRef) {
							simName = ci.nameZh;
							break;
						}
					}
					// 模拟招募的产品行（红线六：产品日志 + 结果 JSON 的 detail 都记）。
					const auto emitSim = [&](const std::string& a_tail) {
						const std::string line = std::format("模拟招募：{}（0x{:08X}）｜{}",
							simName.empty() ? std::string{ "?" } : simName, simRef, a_tail);
						REX::INFO("船员探针 {}", line);
						g_cur.crewReport += "船员探针 " + line + "\n";
					};

					if (!g_cur.crewSubmitted) {
						// 引用可读性预检（与 Papyrus `Game.GetForm` 同源）—— 不可读直接跳过
						// （用例编排应先把玩家传送到目标附近；跳过 = 用例断言会 FAIL 提醒）。
						if (RE::TESForm::LookupByID(simRef) == nullptr) {
							g_cur.crewSimDone = true;
							g_cur.crewSimNote = "引用未加载 —— 跳过（未做写入）";
							emitSim("引用未加载 —— 跳过（未做写入；先传送/靠近再试）");
						} else {
							std::string detail;
							if (!Submit(Op::kCrewSimRecruit, simRef, 0, detail)) {
								CompleteStep(false, std::format("模拟招募提交失败：{}", detail),
									LogSince(g_cur.logMark, kEvidenceMaxLines));
								return true;
							}
							g_cur.crewSubmitted = true;
							return false;  // 等回执（下一 Tick 继续）
						}
					} else {
						std::int32_t code = 0;
						std::string detail;
						const int rc = Poll(code, detail);
						if (rc == 0) {
							if (now - SubmittedAtMs() >= kCrewProbeAckTimeoutMs) {
								Abandon("crew.probe 模拟招募等回执超时");
								g_cur.crewSubmitted = false;
								g_cur.crewSimDone = true;
								g_cur.crewSimNote = std::format("等回执超时（{} ms）", kCrewProbeAckTimeoutMs);
								emitSim(g_cur.crewSimNote);
							} else {
								return false;  // 继续等
							}
						} else if (rc < 0) {
							CompleteStep(false, "命令通道不可用：" + detail,
								LogSince(g_cur.logMark, kEvidenceMaxLines));
							return true;
						} else {
							// rc == 1：回执到了。结果码 = 32 + 状态位（见 Papyrus op=8）。
							g_cur.crewSubmitted = false;
							g_cur.crewSimDone = true;
							if (code >= 32) {
								const unsigned mask = static_cast<unsigned>(code - 32);
								const unsigned pre = mask & 1u, add = mask & 2u, rem = mask & 4u;
								std::string verdict;
								if (pre != 0) {
									verdict = "前置已招募 —— 跳过写入（不动既有状态）";
								} else if (add != 0 && rem == 0) {
									verdict = "A 位随招募往返 0→1→0（A 判据成立）";
								} else if (add == 0) {
									verdict = "AddToAvailableCrew 未改变 A 位（A 判据不成立）";
								} else {
									verdict = "Remove 后仍 A=1 —— 未复原（状态可能残留）";
								}
								g_cur.crewSimNote = verdict;
								emitSim(std::format("前置 A={}｜Add 后 A={}｜Remove 后 A={}｜判定：{}",
									pre != 0 ? 1 : 0, add != 0 ? 1 : 0, rem != 0 ? 1 : 0, verdict));
							} else {
								g_cur.crewSimNote = std::format("失败（结果码 {}：{}）", code, ResultText(code));
								emitSim(g_cur.crewSimNote);
							}
						}
					}
				}

				// 全部处理完：汇总行（逐位行已在上面逐条打出）
				//   ★★★ 第 156 轮：+直读对照段（直读到位数 / 对照位数 / 不一致数）与
				//   模拟招募段（只在实际做过时出现 —— 不写 sim= 时汇总行保持原格式）。
				const auto summary = std::format(
					"汇总：{} 位｜Papyrus 读到 {} 位（A=1 {} / C=1 {} / P=1 {} / 已分配 {}）"
					"｜直读读到 {} 位（对照 {} 位 / 不一致 {} 位）"
					"｜招募任务：未开始 {} / 运行中 {} / 已完成 {} / 其它 {}{}",
					kCrewProbeCount, g_cur.crewRead, g_cur.crewA, g_cur.crewC, g_cur.crewP,
					g_cur.crewAssign, g_cur.crewDirectRead, g_cur.crewDirectPairs,
					g_cur.crewMismatch, g_cur.crewQNotStarted, g_cur.crewQRunning,
					g_cur.crewQDone, g_cur.crewQOther,
					g_cur.crewSimNote.empty()
						? std::string{}
						: std::format("｜模拟招募：{}", g_cur.crewSimNote));
				REX::INFO("船员探针 {}", summary);
				CompleteStep(true, g_cur.crewReport + "船员探针 " + summary, {});
				return true;
			}

			case Kind::kUiInject: {
				// ★★★ 第 133 轮（P3 产品化 PoC · docs/15 11.7）：`ui.inject` —— 把产品侧
				//   「待推送」的可接任务列表（SAQ::PendingQuests()，同一份数据）真实
				//   注进原版 MissionMenu（扩 tab + 分时注入 + 对账 + 恢复对账）。
				//   一次性完成（不进 Papyrus 通道；**菜单必须开着** —— 它操作界面里的
				//   AS3 对象）。红线六（第 104 轮）：结果必须**同时打一行产品日志**
				//   （`assert.log` 只认产品行，LogFind 跳过一切含 `harness：` 的行）。
				const auto inject = UiInject::RunInjectPoC(SAQ::PendingQuests());
				REX::INFO("界面注入PoC {}", inject);
				CompleteStep(true, inject, {});
				return true;
			}

			case Kind::kUiMode: {
				// ★★★ 第 138 轮（P2 会话收口）：`ui.mode <swf|auto|inject|reset>` ——
				//   运行期强制 UI 形态（见 SAQ_UiInject 的 ForceMode / ClearForceMode）。
				//   一次性完成（纯内存开关，不碰界面、不需要菜单状态）。
				//   红线六（第 104 轮）：结果必须**同时打一行产品日志**（assert.log 只认
				//   产品行）—— 计划里可断言这行确认模式已生效。
				std::string result;
				if (step.text == "swf") {
					UiInject::ForceMode(UiInject::UiMode::kSwf);
					result = "swf";
				} else if (step.text == "auto") {
					UiInject::ForceMode(UiInject::UiMode::kAuto);
					result = "auto";
				} else if (step.text == "inject") {
					UiInject::ForceMode(UiInject::UiMode::kInject);
					result = "inject";
				} else if (step.text == "reset") {
					UiInject::ClearForceMode();
					result = "reset（回到 ini 语义）";
				} else {
					CompleteStep(false, "参数必须是 swf|auto|inject|reset（给的是 " + step.text + "）", {});
					return true;
				}
				REX::INFO("界面形态覆盖：UiMode={}（harness 强制；reset 清除）", result);
				CompleteStep(true, "UiMode 覆盖 → " + result, {});
				return true;
			}

			case Kind::kUiInteract: {
				// ★★★ 第 140 轮（P4 交互接管）：三条子命令（各自一行产品日志 —— 红线六；
				//   一次性完成，不进 Papyrus 通道；**菜单必须开着** —— 它操作界面里的 AS3 对象）。
				if (step.text == "state") {
					const auto state = UiInject::RunInteractState();
					REX::INFO("界面接管状态 {}", state);
					CompleteStep(true, state, {});
					return true;
				}
				if (!step.text.empty()) {
					// `key X` / `key Y`：真按键（选中我们的第一条可导航条目 → 触发）。
					const auto toks = SplitWs(step.text);
					const char* key = (toks.size() == 2 && toks[1] == "Y") ? "Y" : "X";
					const auto  result = UiInject::RunInteractKey(key);
					REX::INFO("界面接管按键 {}", result);
					CompleteStep(true, result, {});
					return true;
				}
				const auto probe = UiInject::RunInteractProbe();
				REX::INFO("界面接管 {}", probe);
				CompleteStep(true, probe, {});
				return true;
			}

			case Kind::kUiResearch: {
				// ★★★ 第 117 轮（无 SWF 覆盖的 UI 注入研究 · docs/15）：GFx 注入能力探针。
				//   一次性完成（不进 Papyrus 通道、不等回执；**菜单必须开着** —— 它读的是
				//   界面里的 AS3 对象）。红线六（第 104 轮）：探针结果必须**同时打一行
				//   产品日志**（`assert.log` 只认产品行，LogFind 跳过一切含 `harness：` 的行）。
				//
				//   ★★★ 第 119 轮（探针 v2 / P1.5）：`ui.research2` —— parse 时用
				//   `step.text == "2"` 标记（复用同一 kind）；结果打 `界面研究探针2 …`
				//   （同样一行产品日志，红线六）。
				if (step.text == "2") {
					const auto probe2 = UI::ResearchGfxInjection2();
					REX::INFO("界面研究探针2 {}", probe2);
					CompleteStep(true, probe2, {});
					return true;
				}
				// ★★★ 第 120 轮（P2 · 原版 SWF 完整 PoC）：`ui.research3` ——
				//   原版环境（我们的 SWF 覆盖被临时禁用）下的完整链路：扩 tab 7→8 +
				//   切 7 拦截哨兵 + 列表数据注入（InitializeEntries）。同样一行产品日志。
				if (step.text == "3") {
					const auto probe3 = UI::ResearchGfxInjection3();
					REX::INFO("界面研究探针3 {}", probe3);
					CompleteStep(true, probe3, {});
					return true;
				}
				// ★★★ 第 130 轮（功能迁移探针 v4 · docs/15 十一）：`ui.research4`
				//   （U5/U6/U8/U9/U10 + 置灰）与 `ui.research4b`（U7 渲染层 + U8b +
				//   U9 收口）。两段各一行产品日志（红线六）。
				if (step.text == "4") {
					const auto probe4 = UI::ResearchGfxInjection4();
					REX::INFO("界面研究探针4a {}", probe4);
					CompleteStep(true, probe4, {});
					return true;
				}
				if (step.text == "4b") {
					const auto probe4b = UI::ResearchGfxInjection4b();
					REX::INFO("界面研究探针4b {}", probe4b);
					CompleteStep(true, probe4b, {});
					return true;
				}
				const bool withEvents = step.text.find("events") != std::string::npos;
				const auto probe = UI::ResearchGfxCapabilities(withEvents);
				REX::INFO("界面研究探针 {}", probe);
				CompleteStep(true, probe, {});
				return true;
			}

			// ★★ 第 62 轮（大项 I）：自动读档。为什么放在驱动器而不是 Papyrus 命令通道：
			//   读档会**重建世界与脚本 VM** —— 命令通道（GLOB）自己会被存档值覆盖，让脚本
			//   去执行「读档」既没接口也自相矛盾；这本来就是引擎侧的排队动作
			//   （BGSSaveLoadManager::QueueLoadGame，与游戏「读取存档」菜单同一个写侧）。
			//
			//   完成判据（与传送的落地静默期同款，但窗口更长）：
			//     ① 加载画面（LoadingMenu/FaderMenu）消失，且连续静默 ≥2 秒；
			//     ② 距排队 ≥5 秒（读档不可能更快）；
			//     ③ 命令通道**重新就绪** —— 读档后 GLOB 回到存档值，脚本要重新握手
			//        （EnableHarnessIfNeeded 重写 1、脚本回 2；HarnessReady 会重新追平 seq）。
			case Kind::kSaveLoad: {
				if (!g_cur.kicked) {
					// 时序红线：读档要在「游戏在跑」的状态下排队（菜单开着时游戏暂停）。
					if (a_menuOpen) {
						std::string detail;
						REX::WARN("harness：  读档步骤出现在菜单开着时（用例 {} 的 {}）—— 自动关菜单后继续",
							c.id, step.raw);
						SetMenuOpen(false, detail);
						return false;
					}
					// 读档会重载世界：在飞的命令一律作废（读档后 seq/ack 都会回到存档值）。
					Abandon("自动读档会重置世界");
					std::string detail;
					if (!QueueLoadSaveByName(step.text, detail)) {
						// 「列表未构建」是可等待的中间态（引擎异步构建中）—— 等；
						// 其它失败（找不到存档 / 形状不对）直接判 FAIL，不白等 120 秒。
						if (detail.rfind("存档列表未构建", 0) == 0 && now < g_cur.deadlineMs) {
							if (!g_cur.loadNoted) {
								g_cur.loadNoted = true;
								REX::INFO("harness：  {}", detail);
							}
							return false;
						}
						CompleteStep(false, "排队读档失败：" + detail,
							LogSince(g_cur.logMark, kEvidenceMaxLines));
						return true;
					}
					g_cur.kicked = true;
					g_cur.kickDetail = detail;
					g_cur.loadQueuedAtMs = now;
					g_cur.deadlineMs = now + step.timeoutMs;
					REX::INFO("harness：  {} —— 等加载画面走完 + 通道重新就绪（最久 {} ms）",
						detail, step.timeoutMs);
					return false;
				}
				// —— 等读档完成（每 Tick 推进，与第 59 轮的传送静默期同一原则）——
				if (AnyLoadingMenuOpen()) {
					g_cur.loadSeenLoading = true;
					g_cur.loadCleanSinceMs = 0;
					if (!g_cur.loadNoted) {
						g_cur.loadNoted = true;
						REX::INFO("harness：  读档加载中（{}）—— 等它走完", OpenMenusSummary());
					}
				} else if (g_cur.loadSeenLoading || now - g_cur.loadQueuedAtMs >= kSaveLoadMinGapMs) {
					// 加载画面已关（或「从没观察到加载画面」但等待已过下限 —— 读档照样在跑）。
					if (g_cur.loadCleanSinceMs == 0) {
						g_cur.loadCleanSinceMs = now;
					}
				}
				// 通道重新就绪（读档后 VM 重建：脚本要重新回写「已就绪」；seq 走追平/跳号）。
				std::string readyDetail;
				const bool ready = HarnessReady(readyDetail);
				if (!ready) {
					EnableHarnessIfNeeded();  // 幂等：把总开关顶回「请求启用」等脚本回 2
				}
				// 通道迟迟没恢复 ⇒ 唤醒脚本（开一次任务菜单再关 —— 见 kSaveLoadWakeIntervalMs）。
				//   只在「加载确实走完」之后做，免得在加载过程中乱开菜单。
				if (!ready && g_cur.loadCleanSinceMs != 0 && g_cur.loadWakeCount < kSaveLoadWakeMax) {
					if (g_cur.loadWakeOpen) {
						std::string detail;
						SetMenuOpen(false, detail);
						g_cur.loadWakeOpen = false;
						g_cur.loadWakeAtMs = now;
						REX::INFO("harness：  通道还没恢复 —— 已开/关一次任务菜单唤醒脚本（第 {} 次，"
								  "第 26 轮的定时器重挂机制）",
							g_cur.loadWakeCount);
					} else if (now - g_cur.loadWakeAtMs >= kSaveLoadWakeIntervalMs) {
						std::string detail;
						SetMenuOpen(true, detail);
						g_cur.loadWakeOpen = true;
						++g_cur.loadWakeCount;
						g_cur.loadWakeAtMs = now;
					}
				}
				const bool clean = g_cur.loadCleanSinceMs != 0 &&
					now - g_cur.loadCleanSinceMs >= kSaveLoadSettleCleanMs;
				const bool gap = now - g_cur.loadQueuedAtMs >= kSaveLoadMinGapMs;
				if (clean && gap && ready) {
					const auto cleanMs = g_cur.loadCleanSinceMs != 0 ? (now - g_cur.loadCleanSinceMs) : 0;
					CompleteStep(true,
						std::format("{}；读档完成（排队后 {} ms，加载画面已关 {} ms，通道重新就绪：{}）",
							g_cur.kickDetail, now - g_cur.loadQueuedAtMs, cleanMs, readyDetail),
						{});
					return true;
				}
				if (now >= g_cur.deadlineMs) {
					if (g_cur.loadWakeOpen) {
						std::string detail;
						SetMenuOpen(false, detail);  // 别把唤醒用的菜单留在开着（收尾更干净）
					}
					timeoutFail("读档没有完成",
						std::format("此刻打开的菜单：{}；通道：{}；加载画面{}观察到", OpenMenusSummary(),
							readyDetail, g_cur.loadSeenLoading ? "已" : "未"));
					return true;
				}
				return false;
			}

			case Kind::kWait:
				if (now - g_cur.startedAtMs >= step.timeoutMs) {
					CompleteStep(true, std::format("等了 {} ms", step.timeoutMs), {});
					return true;
				}
				return false;

			case Kind::kMenu: {
				if (!g_cur.kicked) {
					std::string detail;
					if (!SetMenuOpen(step.menuOpen, detail)) {
						CompleteStep(false, "菜单操作失败：" + detail, LogSince(g_cur.logMark, kEvidenceMaxLines));
						return true;
					}
					g_cur.kicked = true;
					g_cur.kickDetail = detail;
					g_cur.deadlineMs = NowMs() + step.timeoutMs;
				}
				if (MissionMenuIsOpen() == step.menuOpen) {
					CompleteStep(true, std::format("{} → 已{}", g_cur.kickDetail, step.menuOpen ? "打开" : "关闭"), {});
					return true;
				}
				if (now >= g_cur.deadlineMs) {
					timeoutFail(std::format("菜单没有{}", step.menuOpen ? "打开" : "关闭"), g_cur.kickDetail);
					return true;
				}
				return false;
			}

			// ★ 第 54 轮：menu.hide <注册名> —— 关掉任意菜单（典型 = 星图）。
			case Kind::kMenuHide: {
				if (!g_cur.kicked) {
					std::string detail;
					if (!SetMenuOpenByName(step.text.c_str(), false, detail)) {
						CompleteStep(false, "菜单操作失败：" + detail, LogSince(g_cur.logMark, kEvidenceMaxLines));
						return true;
					}
					g_cur.kicked = true;
					g_cur.kickDetail = detail;
					g_cur.deadlineMs = NowMs() + step.timeoutMs;
				}
				if (!MenuIsOpen(step.text.c_str())) {
					CompleteStep(true, std::format("{} → 已关闭", g_cur.kickDetail), {});
					return true;
				}
				if (now >= g_cur.deadlineMs) {
					timeoutFail(std::format("菜单 {} 没有关闭", step.text), g_cur.kickDetail);
					return true;
				}
				return false;
			}

			case Kind::kAssertMenu:
				if (MissionMenuIsOpen() == step.menuOpen) {
					CompleteStep(true, std::format("菜单{}（符合预期）", step.menuOpen ? "开着" : "关着"), {});
					return true;
				}
				if (now >= g_cur.deadlineMs) {
					timeoutFail(std::format("菜单没有{}", step.menuOpen ? "打开" : "关闭"), "assert.menu");
					return true;
				}
				return false;

			case Kind::kUi: {
				// ★★ 第 83 轮：`ui.*` 的「桥没通」重试 —— 节流期里什么都不做
				//   （桥解析 `EnsureResolved` 不便宜，每帧调一次等于每帧做一次解析）。
				constexpr std::uint64_t kUiBridgeRetryIntervalMs = 250;
				if (g_cur.uiRetryAtMs != 0) {
					if (now < g_cur.uiRetryAtMs) {
						return false;
					}
					g_cur.uiRetryAtMs = 0;  // 到点：放行这一次尝试
				}
				{
					const char* fn = (step.opName == "ui.select")      ? "SAQ_TestDriveSelect"
						: (step.opName == "ui.selectchild")            ? "SAQ_TestDriveSelectChild"
						: (step.opName == "ui.key")                    ? "SAQ_TestDriveKey"
						: (step.opName == "ui.tab")                    ? "SAQ_TestDriveTab"
																	   : "SAQ_TestDriveExpand";
					// ★ 第 54 轮：`ui.select/selectchild/expand` 的参数是 uID —— 如果用例写的
					//   是 `~0x…`（记录号，DLC 任务常用），这里才把它解析成运行期 FormID
					//   （AS3 侧按十进制 Number 比较 uID）。
					std::string arg = step.text;
					if (step.localFormID) {
						std::uint32_t id = 0;
						std::string detail;
						if (!ResolveStepFormID(step, id, detail)) {
							CompleteStep(false, "uID 解析失败：" + detail, {});
							return true;
						}
						arg = std::to_string(id);
						REX::INFO("harness：  参数解析 {}", detail);
					}
					std::string reply;
					const bool ok = InvokeUiTestDrive(fn, arg, reply);
					// ★★ 第 57 轮：按 R（XButton）会请求星图 —— 它可能在**用例结束之后**
					//   才真的打开（脚本节拍）⇒ 记下来给清场的延迟复查用（否则星图会留在
					//   下一条用例开头，游戏暂停、`ping` 超时）。
					if (ok && step.opName == "ui.key" && step.text == "XButton") {
						g_caseStarMapRisk = true;
					}
					if (!ok) {
						// ★★ 第 83 轮修（22:52 会话 r81 的 `ui.tab` FAIL「桥没通」的真因）：
						//   菜单刚（重）打开的那一两拍里，DLL 还没解析出 Movie/ASMovieRoot
						//   （产品侧同一次 Tick 的首次推送也会失败、约 0.8 秒后重试成功）——
						//   此时调 AS3 入口必然「桥没通」。这**不是**用例失败：在步骤超时
						//   内重试，等桥就绪（AS3 函数一次都没被调到，重试不会重复触发动作）。
						//   仅在「桥没通」这一种回执上重试；其它原因（函数不存在等）照旧立刻失败。
						//   重试节拍 = 本分支开头的 kUiBridgeRetryIntervalMs（250 ms）。
						if (reply == "桥没通" && now < g_cur.deadlineMs) {
							if (!g_cur.kicked) {
								g_cur.kicked = true;  // 只在第一次重试时记一行，别刷屏
								REX::INFO("harness：  {} 桥没通 —— 等界面桥就绪后重试"
										  "（菜单刚打开时首次解析常失败，产品侧同一拍也会重推）", fn);
							}
							g_cur.uiRetryAtMs = now + kUiBridgeRetryIntervalMs;
							return false;
						}
						CompleteStep(false, std::format("{} 调用失败：{}", fn, reply),
							LogSince(g_cur.logMark, kEvidenceMaxLines));
						return true;
					}
					// AS3 约定：回串以 "ok" 开头 = 动作已送出；"err" = 找不到目标等
					const bool pass = reply.rfind("ok", 0) == 0;
					CompleteStep(pass, std::format("{}（{}）", reply.empty() ? "无返回串" : reply, fn),
						pass ? std::string{} : LogSince(g_cur.logMark, kEvidenceMaxLines));
					return true;
				}
				return false;
			}

			case Kind::kAssertLog: {
				// ★★ 第 68 轮：正则非法 ⇒ 立刻失败（解析期已 WARN）—— 别让它退化成
				//   「日志里没出现」的超时报文（那是「产品没打这行」和「正则写错」两种情况
				//   混在一起，15:24 会话为此白查一轮）。
				if (!step.regexOk) {
					CompleteStep(false, "正则非法（ECMAScript 编译失败）：" + step.text,
						LogSince(g_cur.logMark, kEvidenceMaxLines));
					return true;
				}
				std::string line;
				const auto from = EffectiveLogFrom(step);
				if (LogFind(from, step.text, line)) {
					CompleteStep(true, "命中：" + line, {});
					return true;
				}
				if (now >= g_cur.deadlineMs) {
					// ★★ 第 83 轮：把**三个打点**都写进报文 —— 「窗口起点怎么算的」是这类
					//   超时最费解的一点（r80 那次只有一个数字，无从判断是窗口偏了还是
					//   正则没匹配上；配上「本步/用例」两个基准，一眼就能定位）。
					timeoutFail(std::format("日志里没出现 /{}/", step.text),
						std::format("窗口从 idx {} 起（scope={}；本步起点 idx={}；用例起点 idx={}）"
									"；本窗口的日志见 evidence",
							from,
							step.logScope == LogScope::kPrev ? "prev"
							: step.logScope == LogScope::kCase ? "case"
															   : "this",
							g_cur.logMark, g_caseMark));
					return true;
				}
				return false;
			}

			// ★ 第 54 轮：反向断言 —— 整段窗口**都不许**出现某个模式（「不该再有的行」）。
			//   典型判据：第 44 轮「星图不该有第 2/3 次尝试」、第 49 轮补丁②「读档后不该立刻降级」、
			//   第 26 轮「菜单久停期间不该出现引导未生效」。
			case Kind::kAssertNoLog: {
				// ★★ 第 68 轮：同 kAssertLog —— 正则非法要立刻说清楚（反向断言尤其危险：
				//   静默 false 会被当成「整段窗口没有出现」= **假 PASS**）。
				if (!step.regexOk) {
					CompleteStep(false, "正则非法（ECMAScript 编译失败）：" + step.text,
						LogSince(g_cur.logMark, kEvidenceMaxLines));
					return true;
				}
				std::string line;
				const auto from = EffectiveLogFrom(step);
				if (LogFind(from, step.text, line)) {
					CompleteStep(false,
						std::format("出现了不该出现的日志 /{}/（窗口从 idx {} 起；本步起点 idx={}；"
									"用例起点 idx={}）",
							step.text, from, g_cur.logMark, g_caseMark) +
							" ← " + line,
						LogSince(g_cur.logMark, kEvidenceMaxLines));
					return true;
				}
				if (now >= g_cur.deadlineMs) {
					CompleteStep(true,
						std::format("整段窗口（{} ms）没有出现 /{}/（符合预期）", step.timeoutMs, step.text), {});
					return true;
				}
				return false;
			}

			case Kind::kAssertUi: {
				std::string report;
				if (UI::ReadUiReport(report) && !report.empty()) {
					try {
						if (std::regex_search(report, std::regex{ step.text, std::regex::ECMAScript | std::regex::icase })) {
							CompleteStep(true, "界面报告命中：" + report, {});
							return true;
						}
					} catch (const std::regex_error&) {
						CompleteStep(false, "正则写错：" + step.text, {});
						return true;
					}
				}
				if (now >= g_cur.deadlineMs) {
					timeoutFail(std::format("界面报告里没出现 /{}/", step.text),
						report.empty() ? "读不到界面报告（菜单关着？/ 桥没通？）" : "最后读到：" + report);
					return true;
				}
				return false;
			}

			case Kind::kCmd: {
				if (!g_cur.kicked) {
					// 时序红线：命令只在菜单关着时被脚本消化（第 27 轮实测定案）。
					// 这里容错（自动关菜单），但记 WARN —— 用例写错了要在日志里看得见。
					if (a_menuOpen) {
						std::string detail;
						REX::WARN("harness：  命令步骤出现在菜单开着时（用例 {} 的 {}）—— 自动关菜单后继续（用例顺序应该修）",
							c.id, step.raw);
						SetMenuOpen(false, detail);
						return false;
					}
					// ★ 第 54 轮：命令的 FormID 可能是「记录号」（`~0x…`，DLC 任务）或
					//   「任务板 uID」（`teleport.entry`）—— 都在**开跑这一刻**解析
					//   （那时静态表/加载顺序一定已经就绪）。
					std::uint32_t formID = step.formId;
					if (step.localFormID || step.resolveAsEntry) {
						std::string resolved;
						if (!ResolveStepFormID(step, formID, resolved)) {
							CompleteStep(false, "FormID 解析失败：" + resolved, {});
							return true;
						}
						REX::INFO("harness：  参数解析 {}", resolved);
					}
					std::string detail;
					if (!Submit(step.op, formID, step.num, detail)) {
						CompleteStep(false, "提交命令失败：" + detail, LogSince(g_cur.logMark, kEvidenceMaxLines));
						return true;
					}
					g_cur.kicked = true;
					g_cur.kickDetail = detail;
					g_cur.deadlineMs = now + step.timeoutMs;
					REX::INFO("harness：  提交命令 {}", detail);
					// ★ 第 56 轮：传送的等待窗口写明白（回执要等 cell 加载，实测约 4 秒）——
					//   以后再看日志就知道「这一步为什么等这么久」。
					if (step.op == Op::kTeleport) {
						REX::INFO("harness：  传送等回执最多 {} ms（MoveTo 要等 cell 加载完成，实测约 4 秒）",
							step.timeoutMs);
					}
					return false;
				}
				std::int32_t code = 0;
				std::string detail;
				const int rc = Poll(code, detail);
				if (rc == 1) {
					g_consecutiveTimeouts = 0;  // ★ 第 58 轮：通道活着（回执到了）
					const bool pass = (code == 0);
					if (!pass) {
						CompleteStep(false, detail + std::format("；命令={} {}", step.raw, ResultText(code)),
							LogSince(g_cur.logMark, kEvidenceMaxLines));
						return true;
					}
					if (step.op != Op::kTeleport) {
						// ★ 第 66 轮：回执偏慢（≥ kSlowAckNoteMs）就在日志里留痕 ——
						//   14:35 会话 r44 的 ping 正是这一类（脚本执行了、结果=0，但晚了
						//   3.4 秒），当时只能翻 Papyrus 日志才能与「通道没通」区分开。
						if (const auto took = now - SubmittedAtMs(); took >= kSlowAckNoteMs) {
							REX::INFO("harness：  [note] 命令回执偏慢：{} 用了 {} ms（脚本节拍被拖慢的迹象；判据不受影响）",
								step.raw, took);
						}
						CompleteStep(true, detail, {});
						return true;
					}
					// ★★ 第 58 轮：传送的「落地静默期」（见 kTeleportSettleCleanMs 的说明）。
					//   回执 = cell 加载完成，但加载画面/黑幕可能还在 —— 这一步要等
					//   「加载菜单消失 + 连续静默 1.5 秒 + 距回执 ≥3.5 秒」才算真正做完。
					//
					//   ★★ 第 59 轮（11:04 会话 r47/r45 两条假 FAIL 的真因）：**静默期检查
					//   必须与「读到回执」解耦** —— `Poll` 是一次性消费（读到后 g_busy=false，
					//   之后永远返回 0），v58 把整套静默期逻辑写在 `rc==1` 分支里 ⇒ 回执那
					//   一 Tick 之后再也检查不到「加载画面已关」（实测那条日志只有一行），
					//   20 秒 deadline 一到就误报「命令没有回执」——而那些用例的传送其实
					//   完全正常（回执 4.4/4.9 秒就到、超时瞬间菜单列表 = 无；Papyrus 侧
					//   两次 `MoveTo` 都 `结果=0`）。⇒ 这里只**登记**回执（时刻 + 文案），
					//   静默期检查移到下面，**每 Tick** 都跑。
					if (g_cur.settleAckAtMs == 0) {
						g_cur.settleAckAtMs = now;
						g_cur.settleAckDetail = detail;
					}
				}
				if (rc < 0) {
					CompleteStep(false, "通道不可用：" + detail, LogSince(g_cur.logMark, kEvidenceMaxLines));
					return true;
				}
				// ★★ 落地静默期（第 58 轮引入 / 第 59 轮解耦）：回执已到 ⇒ **每 Tick** 推进 ——
				//   「加载画面消失 + 连续 1.5 秒 + 距回执 ≥3.5 秒」才算真正做完；加载画面
				//   25 秒还没结束 ⇒ 判卡在加载画面（MarkStuck，剩余用例转 SKIP）。
				//   这一段在 deadline 检查**之前** ⇒ 回执到了之后「没有回执」的 20 秒窗口
				//   立即失效（它只负责「等回执」那一段）。
				if (step.op == Op::kTeleport && g_cur.settleAckAtMs != 0) {
					if (AnyLoadingMenuOpen()) {
						g_cur.settleCleanSinceMs = 0;
						if (!g_cur.settleNoted) {
							g_cur.settleNoted = true;
							// 注意措辞：这里不能用「还开着：」这个串 —— 第 48 轮的反向
							// 检查把「星图：等待中（…还开着：无）」列为必须消失的旧文案。
							REX::INFO("harness：  传送落地中（回执已到，但加载画面还没关：{}）"
									  "—— 等它关掉再推进下一步（第 58 轮：紧接着再传送会卡死）",
								OpenMenusSummary());
						}
					} else if (g_cur.settleCleanSinceMs == 0) {
						g_cur.settleCleanSinceMs = now;
					}
					const bool cleanLongEnough = g_cur.settleCleanSinceMs != 0 &&
						now - g_cur.settleCleanSinceMs >= kTeleportSettleCleanMs;
					const bool gapLongEnough = now - g_cur.settleAckAtMs >= kTeleportMinGapMs;
					if (cleanLongEnough && gapLongEnough) {
						CompleteStep(true,
							std::format("{}；落地静默期完成（回执后 {} ms，加载画面已关 {} ms）",
								g_cur.settleAckDetail, now - g_cur.settleAckAtMs,
								now - g_cur.settleCleanSinceMs),
							{});
						return true;
					}
					if (now - g_cur.settleAckAtMs >= kTeleportSettleMaxMs) {
						const auto menus = OpenMenusSummary();
						MarkStuck(std::format("传送已回执，但加载画面一直没有结束（{} ms；"
											  "此刻打开的菜单：{}）",
							now - g_cur.settleAckAtMs, menus));
						CompleteStep(false, std::format("传送已回执，但加载画面一直没有结束（疑似卡在加载画面；"
														"此刻打开的菜单：{}）",
													 menus),
							LogSince(g_cur.logMark, kEvidenceMaxLines));
						return true;
					}
					return false;  // 落地静默期未满：不推进（也不消耗 deadline）
				}
				if (now >= g_cur.deadlineMs) {
					// ★★ 第 58 轮：超时的时候必须把**现场**写下来 —— 「此刻打开的菜单」是
					//   区分「游戏卡在加载画面（LoadingMenu/FaderMenu）」与「脚本 VM 僵死」
					//   的唯一证据（10:31 会话就是靠事后重建这条才定性的）。
					const auto menus = OpenMenusSummary();
					const bool loading = AnyLoadingMenuOpen();
					Abandon("命令回执超时");
					++g_consecutiveTimeouts;
					if (loading || g_consecutiveTimeouts >= kStuckAbortTimeouts) {
						MarkStuck(std::format("命令无回执（seq={} {}；超时 {} ms；步骤 {}）+ 此刻打开的菜单：{}"
											  "{}",
							LastSeq(), g_cur.kickDetail, step.timeoutMs, step.raw, menus,
							loading ? "（含加载画面）"
									: std::format("（连续 {} 次无回执）", g_consecutiveTimeouts)));
					}
					timeoutFail("命令没有回执", std::format("{}；此刻打开的菜单：{}"
													 "（脚本定时器在菜单开着时冻结；列表里出现 LoadingMenu/FaderMenu"
													 " = 游戏卡在加载画面上）",
													 g_cur.kickDetail, menus));
					return true;
				}
				return false;
			}
			}
			return false;
		}
	}

	// ==================================================================
	//  对外
	// ==================================================================
	bool Enabled()
	{
		return g_enabled;
	}

	bool Finished()
	{
		return g_finished;
	}

	std::string StatusLine()
	{
		if (!g_enabled) {
			return "harness=关";
		}
		if (!g_loaded) {
			return "harness=待载入";
		}
		if (g_finished) {
			std::size_t pass = 0, fail = 0, skip = 0;
			for (const auto& r : g_results) {
				if (r.status == "PASS") ++pass;
				else if (r.status == "FAIL") ++fail;
				else if (r.status == "SKIP") ++skip;
			}
			return std::format("harness=已完成（用例 {}：PASS {} / FAIL {} / SKIP {}）", g_results.size(), pass, fail, skip);
		}
		if (!g_active) {
			return g_harnessReady ? "harness=就绪" : "harness=等脚本就绪";
		}
		return std::format("harness=运行中（用例 {}/{}，步骤 {}/{}）", g_caseIdx + 1, g_cases.size(),
			g_stepIdx + 1, g_cases[g_caseIdx].steps.size());
	}

	void LoadPlan()
	{
		g_enabled = HarnessRequested();
		if (!g_enabled) {
			REX::INFO("harness：未启用（ini [Test] Harness=0）—— 引擎内自动化测试关闭");
			return;
		}
		std::string pathDetail;
		g_planPath = PlanPathFromIni(pathDetail);
		if (g_planPath.empty()) {
			REX::WARN("harness：拿不到用例文件路径（{}）", pathDetail);
			g_enabled = false;
			return;
		}
		ParsePlan(g_planPath);
		if (g_cases.empty()) {
			REX::WARN("harness：用例文件里没有任何 [case:...] —— 不做任何事（{}）", g_planPath);
			g_enabled = false;
			return;
		}
		g_sessionStartMs = NowMs();
		g_results.clear();
		g_loaded = true;
		g_finished = false;
		g_wroteResults = false;
		g_harnessReady = false;
		g_active = false;
		g_readyWarned = false;
		// ★ 第 56 轮：带上**驱动器版本串** —— 与 SWF 的 `stamp=` 同一个道理：日志里有没有
		//   这一串，是「跑的是不是修好窗口 bug 的那版驱动器」的唯一判据（旧版会把
		//   断言窗口起点清 0 ⇒ 假 PASS/假 FAIL）。
		//   ★★ 第 69 轮：**用例文件解析失败 ⇒ 该用例直接判 FAIL**（老行为只留 WARN +
		//   丢步 —— 15:43 会话 r65_icons 的 `step = ui.state` 就是这样「少测一步还 PASS」）。
		//   ★★ 第 83 轮（v70）：`ui.*` 桥没通自动重试 + 清场延迟复查只在「真的见到星图」
		//   时提前结束 + 断言超时报文带上三个打点。
		//   ★★★ 第 155 轮（v71）：新 op `crew.probe`（可招募船员只读探针，docs/16 16.3）
		//   —— 逐位读 24 位的 faction 三件套（Papyrus op=7）+ 招募任务状态（直读）
		//   + 汇总行；引用未加载的位跳过（引擎限制）。
		//   ★★★ 第 156 轮（v72）：`crew.probe` 扩展 —— ③ 直读对照（与产品 kind=2 过滤
		//   同一套 SAQ_Crew::ReadState；「对照=不一致」+ 汇总不一致数）+ ④ 可选
		//   `sim=<FormID>` 模拟招募往返（Papyrus op=8；A 判据正样本复核，docs/16 16.8）。
		REX::INFO("harness：已启用（{} 个用例；驱动器 v72：`crew.probe` 扩展 —— ③ 直读对照"
				  "（与产品 kind=2 过滤同一套 SAQ_Crew::ReadState）+ ④ 可选 `sim=<FormID>`"
				  " 模拟招募往返（Papyrus op=8：Add→读→Remove→读；A 判据正样本复核）"
				  "；v71 新 op `crew.probe`（可招募船员只读探针 —— 24 位逐位读 Papyrus faction"
				  " 三件套 + DLL 直读招募任务状态；引用未加载的位跳过）；沿用以来的：v70 `ui.*`"
				  " 遇到「桥没通」在步骤超时内自动重试"
				  "（菜单刚打开那一两拍，产品侧首次推送同样会失败）/ 清场延迟复查只在**真的看到"
				  "并关掉星图**时才提前结束（关残留任务菜单不算 —— 22:52 会话 r62 的 ping 超时"
				  "就是这么来的）/ 断言超时报文带「窗口/本步/用例」三个打点 / v69 用例解析失败"
				  " ⇒ 判 FAIL / v68 断言正则解析期编译校验（非法正则立刻报「正则非法」，不再"
				  "退化成「日志里没出现」的误导性超时）/ 回执 ≥ {} ms 留一行 note / v66 命令"
				  "回执窗口 8000 ms + ping 用满窗口 / v63 主菜单稳定 {} ms 后自动读档 / save.list /"
				  " save.load / guide.probe / 传送 20 秒窗口 / 落地静默期每 Tick 推进 /"
				  " 加载画面证据 / 卡死自动中止））"
				  " —— 等脚本通道就绪后自动开跑",
			g_cases.size(), kSlowAckNoteMs, kAutoLoadMinMenuAgeMs);
	}

	namespace
	{
		// 未启用时每 2 秒复查一次 ini：允许「Harness 改 0→1」**当场**载入用例并开跑。
		//
		// 为什么值得加这一段：ini 是在插件加载时读一次，而实机第一次跑 smoke 就因为
		// 「两个键被构建脚本追加到了 [Filter] 段 ⇒ 读到 0」白重启了一次游戏。有了这条复查，
		// 「改开关 → 看结果」的循环不需要重启（要重新载入用例：把 Harness 拨回 0 再置 1）。
		bool PollEnable()
		{
			const auto now = NowMs();
			if (now - g_lastEnableCheckMs < kEnableCheckIntervalMs) {
				return false;
			}
			g_lastEnableCheckMs = now;
			if (!HarnessRequested()) {
				g_wantHarness = false;
				return false;
			}
			if (g_wantHarness) {
				return false;  // 已经尝试过载入（失败要重试就把开关拨一次）
			}
			g_wantHarness = true;
			LoadPlan();
			return true;
		}

		// ★★ 第 62 轮补②：排队后的结果侦测（定义在 TryAutoLoadFromMainMenu 之后）。
		void NoteAutoLoadOutcome();

		// ★★ 第 62 轮补：主菜单自动读档（见常量 kMainMenuName 的说明）。
		//   返回 true = 本拍已经做过事（调用方直接 return）。
		//   行为：只在「主菜单开着」（= 玩家在标题界面、世界还没加载）时动手；ini
		//   `[Test] AutoLoad` 给了存档名子串就排队读它；排队成功即停手（游戏会开始加载 ⇒
		//   进世界 ⇒ 脚本实例起来 ⇒ 通道就绪 ⇒ 用例自动开跑）。失败（列表没构建）每 3 秒
		//   重试，最多 10 次；放弃时打一行 WARN 提示手动读档。
		bool TryAutoLoadFromMainMenu()
		{
			// ★★ 第 62 轮补②：排队后的结果侦测 —— 与「还没排队」的流程分开，先跑
			//   （它自带「只反映一次」的判据，见函数说明）。
			if (g_autoLoadDone) {
				NoteAutoLoadOutcome();
				return false;
			}
			// 先查菜单（便宜），再读 ini（1 秒缓存）—— 不在主菜单时这一整个功能零开销。
			if (!MenuIsOpen(kMainMenuName)) {
				g_autoLoadMenuSeenMs = 0;  // 离开过主菜单 ⇒ 下次再来重新算「稳定」窗口
				return false;
			}
			const auto now = NowMs();
			// ★ 第 62 轮补②：主菜单**出现后先等 kAutoLoadMinMenuAgeMs**（见常量说明：
			//   主菜单头几秒引擎还在初始化，过早排队会让读档请求压在初始化窗口上）。
			if (g_autoLoadMenuSeenMs == 0) {
				g_autoLoadMenuSeenMs = now;
				return false;
			}
			if (now - g_autoLoadMenuSeenMs < kAutoLoadMinMenuAgeMs) {
				return false;
			}
			if (now - g_autoLoadCheckMs < kAutoLoadRetryIntervalMs) {
				return false;
			}
			g_autoLoadCheckMs = now;
			const std::string target = AutoLoadSaveName();
			if (target.empty()) {
				return false;  // ini 没配置（或玩家删了值）—— 什么都不做
			}
			std::string detail;
			if (QueueLoadSaveByName(target, detail)) {
				g_autoLoadDone = true;
				g_autoLoadQueuedAtMs = now;
				REX::INFO("harness：主菜单自动读档已排队（主菜单已稳定 {} ms）—— {}"
						  "（游戏随后自动进入该存档，用例会自动开跑）",
					now - g_autoLoadMenuSeenMs, detail);
				return true;
			}
			if (++g_autoLoadAttempts <= kAutoLoadMaxAttempts) {
				if (g_autoLoadAttempts == 1) {
					REX::INFO("harness：主菜单自动读档：存档列表还没就绪（{}）—— 每 {} ms 重试",
						detail, kAutoLoadRetryIntervalMs);
				}
				return true;
			}
			if (g_autoLoadAttempts == kAutoLoadMaxAttempts + 1) {
				g_autoLoadDone = true;
				REX::WARN("harness：主菜单自动读档放弃（试了 {} 次）—— 请手动读一个存档，用例会自动开跑：{}",
					kAutoLoadMaxAttempts, detail);
			}
			return true;
		}

		// ★★ 第 62 轮补②：自动读档**排队之后**的结果侦测（12:2x 实测补的现场判据）。
		//
		//   为什么需要：读档失败（引擎读完又退回主菜单）时，harness 只会安静地停在
		//   「等脚本回写 2」—— 玩家看不出发生了什么（12:31 会话：12:32:05.598 主菜单
		//   又出现、12:32:11 崩溃，日志里一个字都没有）。这里把它变成一行 WARN。
		//
		//   判据（为什么这三条）：
		//     ① 排队后主菜单**关过** = 引擎真的开始处理这次排队（实测排队到关闭之间
		//        可能隔着 ~30 秒 —— 引擎要等主菜单初始化完成，所以只看时间不够）；
		//     ② 之后主菜单**又出现**，且命令通道从未就绪 ⇒ 读档没进世界（失败）；
		//     ③ 通道已就绪 ⇒ 之前确实进过世界，后来回主菜单是玩家自己退出 —— 不报。
		void NoteAutoLoadOutcome()
		{
			if (g_autoLoadOutcomeNoted || g_autoLoadQueuedAtMs == 0) {
				return;
			}
			if (!MenuIsOpen(kMainMenuName)) {
				g_autoLoadLeftMainMenu = true;
				return;
			}
			if (!g_autoLoadLeftMainMenu || g_harnessReady) {
				return;
			}
			g_autoLoadOutcomeNoted = true;
			REX::WARN("harness：自动读档似乎失败了 —— 读档窗口结束后又回到主菜单，用例不会自动开跑"
					  "（排队于 {} ms 前；若手动读同一个存档也退回主菜单，那是存档 / 引擎这次加载的问题，"
					  "换一个存档名或用例文件里的 save.load 档位重试）",
				NowMs() - g_autoLoadQueuedAtMs);
		}
	}

	void Tick(bool a_menuOpen)
	{
		// ★★ 第 57 轮：延迟复查放在最前 —— `finishAll`（全部用例结束）之后也要跑到；
		//   窗口结束后这里只剩一次时间戳比较（零开销）。
		if (g_cleanupRecheckUntilMs != 0) {
			CleanupRecheck();
		}
		if (g_finished) {
			return;
		}
		if (!g_enabled || !g_loaded) {
			// 未启用（或载入失败）：只在「这一次变成要跑」时载入一次，其余情况立刻返回
			// ⇒ 零开销（一次时间戳比较）。
			PollEnable();
			return;
		}

		auto finishAll = [&]() {
			// ★ 第 49 轮补丁 / 第 54/55 轮：结束（含失败中止）时把「暂停菜单」恢复成常态。
			//   首测实证：smoke 在 ui.tab 失败中止 ⇒ 后面的 menu.close 步骤没跑到 ⇒
			//   任务菜单（暂停菜单）一直留在屏幕上（游戏暂停、脚本定时器冻结）。
			//   09:06 会话又实证了星图版本（smoke 失败 ⇒ 星图留屏 ⇒ 后续用例全冻死）。
			//   第 55 轮起这段逻辑收进 CleanupAfterCase，**每条用例结束**都会执行。
			CleanupAfterCase();
			g_finished = true;
			WriteResults();
			REX::INFO("harness：全部用例结束 —— {}", StatusLine());
		};

		if (!g_active) {
			// ★★ 第 58 轮：游戏端卡死 ⇒ 剩余用例全部 SKIP 并收尾（见 MarkStuck）。
			//   放在「开下一条用例」之前：卡死时后面的用例只会各自白等一次超时
			//   （10:31 会话：r45 的传送卡死后，r48/r44 都陪跑）。
			if (g_stuckAbort) {
				FillRemainingSkipped();
				finishAll();
				return;
			}
			// ① 等脚本把通道置成「就绪」（SAQ_TestHarness 由 1 → 2），见 SAQ_TestOps.h 的协议说明
			if (!g_harnessReady) {
				// ★★ 第 62 轮补：主菜单阶段的**自动读档**（见 TryAutoLoadFromMainMenu 的说明）——
				//   放在节流之前（它自带 3 秒节流；不在主菜单时零开销）。
				if (TryAutoLoadFromMainMenu()) {
					return;
				}
				const auto now = NowMs();
				if (now - g_lastReadyCheckMs < kReadyCheckIntervalMs) {
					return;
				}
				g_lastReadyCheckMs = now;
				if (!EnableHarnessIfNeeded()) {
					if (!g_readyWarned) {
						g_readyWarned = true;
						REX::INFO("harness：已请求启用（SAQ_TestHarness=1），等脚本回写 2（脚本每 0.5 秒一拍）");
					}
					return;
				}
				std::string detail;
				if (!HarnessReady(detail)) {
					g_channelDetail = detail;
					return;
				}
				g_harnessReady = true;
				g_channelDetail = detail;
				REX::INFO("harness：通道就绪（{}）", detail);
				return;
			}
			// ② 走完一条就开下一条（★ 第 55 轮：先等「用例间隔」—— 上一条的收尾清场
			//    要一点时间才能让引擎真正关掉菜单/星图；不等的话下一条的 `ping` 可能
			//    撞上「游戏仍暂停 ⇒ 脚本定时器冻结」而超时，看起来像被测功能坏了）。
			// ★★ 第 57 轮：延迟复查窗口没结束就不开下一条（上一条可能触发过星图，
			//   它会在清场之后才打开 —— 让它先出现、被关掉，再开下一条）。
			if (g_cleanupRecheckUntilMs != 0 || NowMs() < g_nextCaseAtMs) {
				return;
			}
			if (g_results.size() > g_caseIdx) {
				++g_caseIdx;
			}
			if (g_caseIdx >= g_cases.size()) {
				finishAll();
				return;
			}
			StartCase(g_caseIdx);
			return;
		}

		RunStep(a_menuOpen);
	}
}

#endif  // SAQ_WITH_HARNESS

