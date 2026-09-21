// ★★ 第 53 轮（大项 F · 发布就绪）：整个文件只在开发构建（SAQ_WITH_HARNESS=1）里编译。
//   发布构建（xmake saq_harness=n）里 xmake 根本不加入这个文件；这里再包一层 #if
//   是**双保险** —— 万一被误加入编译，也只会编成空单元，不会产生任何引用
//   （SAQ.cpp 的调用点同样在 #if 里）。
#if SAQ_WITH_HARNESS

#include "PCH.h"

#include "SAQ_Test.h"

#include "SAQ.h"          // PluginDir()
#include "SAQ_TestOps.h"  // 原语层
#include "SAQ_UI.h"       // ReadUiReport

#include "SAQ_EntryTable.h"  // 任务板入口表（`teleport.entry` 要把「板/常驻 marker」解析成引用）
#include "SAQ_Guide.h"       // Guide::EnsureChannel（入口 marker 的运行期前缀）
#include "SAQ_Masters.h"     // Masters::MakeFormID（「master + 记录号」→ 运行期 FormID）
#include "SAQ_QuestTable.h"  // 静态任务表（`~0x…` = 记录号，按加载顺序解析成运行期 FormID）

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
		constexpr std::uint64_t kCommandAckTimeoutMs = 3000;   // 命令通道（脚本一拍 0.5 秒）
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
		// 连续多少次「命令无回执」就判定游戏端卡死（若此刻有加载画面，1 次就够）。
		constexpr int kStuckAbortTimeouts = 2;
		constexpr std::uint64_t kReadyCheckIntervalMs = 500;
		constexpr std::size_t   kEvidenceMaxLines = 60;

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
			bool          menuOpen{};         // kind == kMenu / kAssertMenu
			LogScope      logScope{ LogScope::kThis };
			// ★ 第 54 轮：① `~0x…` = 记录号（踢给静态表解析成运行期 FormID）；
			//   ② `teleport.entry` = 目标不是 FormID 而是**任务板 uID**（要按候选链解析引用）。
			bool          localFormID{};
			bool          resolveAsEntry{};
			std::uint8_t  localMaster{ 0xFF };  // `~N:0x…` 里显式指定的 master 下标（0xFF = 未指定）
			std::uint64_t timeoutMs{ kDefaultStepTimeoutMs };
		};

		struct Case
		{
			std::string       id;
			std::string       desc;
			std::vector<Step> steps;
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
		};
		StepState g_cur;

		// ★★ 第 58 轮：游戏端卡死（脚本 VM 无响应 / 卡在加载画面）的检测与中止 ——
		//   见 MarkStuck 的说明。只在 harness 会话内有效。
		int         g_consecutiveTimeouts{};
		bool        g_stuckAbort{};
		std::string g_stuckReason;

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

			// 命令类步骤：回执超时常量与步骤超时取小（避免「脚本没跑」时白等 5 秒以上）。
			// ★ 第 56 轮：传送例外 —— MoveTo 的等待窗口由 cell 加载决定，见 kTeleportAckTimeoutMs。
			if (a_step.kind == Kind::kCmd) {
				if (a_step.op == Op::kTeleport) {
					a_step.timeoutMs = kTeleportAckTimeoutMs;
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
						++bad;
					}
				} else {
					REX::WARN("harness：用例文件第 {} 行的未知键 {}（只认 desc / step）", lineNo, key);
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
			if (MenuIsOpen("GalaxyStarMapMenu")) {
				if (SetMenuOpenByName("GalaxyStarMapMenu", false, detail)) {
					REX::INFO("harness：用例收尾：星图还开着 —— 已请求关闭（{}）", detail);
				}
			}
			// ★★ 第 57 轮：本用例按过 R（请求过星图）⇒ 开一段延迟复查窗口 —— 星图很可能
			//   在清场**之后**才真的打开（见 g_cleanupRecheckUntilMs 的注释）。
			if (g_caseStarMapRisk) {
				g_cleanupRecheckUntilMs = NowMs() + kCleanupRecheckWindowMs;
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
				}
			}
			if (MissionMenuIsOpen()) {
				if (SetMenuOpen(false, detail)) {
					REX::INFO("harness：用例收尾复查：任务菜单还开着 —— 已请求关闭（{}）", detail);
					closedStarMap = true;
				}
			}
			// 星图既然已经出现过并被关掉，就没有「稍后再打开」的可能了 —— 提前结束窗口，
			// 别白等（脚本一次引导只开一次星图）。
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
				// 结果进步骤结果（SAQ_testresults.json）—— 「走远后候选是否仍可得」的硬证据。
				CompleteStep(true, detail, {});
				return true;
			}

			case Kind::kSaveList: {
				CompleteStep(true, SaveGameListSummary(), {});
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
				if (!g_cur.kicked) {
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
				std::string line;
				const auto from = EffectiveLogFrom(step);
				if (LogFind(from, step.text, line)) {
					CompleteStep(true, "命中：" + line, {});
					return true;
				}
				if (now >= g_cur.deadlineMs) {
					timeoutFail(std::format("日志里没出现 /{}/", step.text),
						std::format("窗口从 idx {} 起（scope={}）；本窗口的日志见 evidence", from,
							step.logScope == LogScope::kPrev ? "prev"
							: step.logScope == LogScope::kCase ? "case"
															   : "this"));
					return true;
				}
				return false;
			}

			// ★ 第 54 轮：反向断言 —— 整段窗口**都不许**出现某个模式（「不该再有的行」）。
			//   典型判据：第 44 轮「星图不该有第 2/3 次尝试」、第 49 轮补丁②「读档后不该立刻降级」、
			//   第 26 轮「菜单久停期间不该出现引导未生效」。
			case Kind::kAssertNoLog: {
				std::string line;
				const auto from = EffectiveLogFrom(step);
				if (LogFind(from, step.text, line)) {
					CompleteStep(false,
						std::format("出现了不该出现的日志 /{}/（窗口从 idx {} 起）", step.text, from) +
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
		REX::INFO("harness：已启用（{} 个用例；驱动器 v61：自动读档（save.list / save.load ——"
				  " BGSSaveLoadManager 排队读档 + 加载静默期 + 通道重新就绪）"
				  "（沿用：guide.probe / ~0x 参数写回 / 清场延迟复查 / 日志窗口按步保留 /"
				  " 传送 20 秒窗口 / 落地静默期每 Tick 推进 / 加载画面证据 / 卡死自动中止））"
				  " —— 等脚本通道就绪后自动开跑",
			g_cases.size());
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

