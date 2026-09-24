// ★★ 第 53 轮（大项 F · 发布就绪）：整个文件只在开发构建（SAQ_WITH_HARNESS=1）里编译。
//   发布构建（xmake saq_harness=n）里 xmake 根本不加入这个文件；这里再包一层 #if
//   是**双保险**（见 SAQ_Test.cpp 开头的同一段说明）。
#if SAQ_WITH_HARNESS

#include "PCH.h"

#include "SAQ_TestOps.h"

#include "SAQ.h"        // PluginDir()
#include "SAQ_Guide.h"  // FindGlob（按已认领的前缀取 GLOB）
#include "SAQ_UI.h"     // UI::InvokeUiTestDrive

#include "RE/B/BGSSaveLoad.h"  // ★★ 第 62 轮：自动读档（BGSSaveLoadManager —— 排队读档是内联写）
#include "RE/IDs.h"            // ★★ 第 62 轮：BGSSaveLoadManager::Singleton 的地址库 ID
#include "RE/T/TESGlobal.h"
#include "RE/U/UI.h"
#include "RE/U/UIMessageQueue.h"

#include <spdlog/sinks/base_sink.h>
#include <spdlog/spdlog.h>

#include <Windows.h>

#include <algorithm>
#include <atomic>
#include <cctype>
#include <cmath>
#include <cstring>
#include <deque>
#include <format>
#include <mutex>
#include <regex>

namespace SAQ::Test
{
	namespace
	{
		// ESM 里追加的记录号（低 24 位；见 tools/esm/patch_saq_esm.py 的 TEST_GLOBS）
		constexpr std::uint32_t kLowSeq = 0x806;      // GLOB SAQ_TestSeq
		constexpr std::uint32_t kLowCmd = 0x807;      // GLOB SAQ_TestCmd
		constexpr std::uint32_t kLowArgA = 0x808;     // GLOB SAQ_TestArgA（FormID 低 24 位）
		constexpr std::uint32_t kLowArgB = 0x809;     // GLOB SAQ_TestArgB（FormID 高 8 位）
		constexpr std::uint32_t kLowArgC = 0x80A;     // GLOB SAQ_TestArgC（数值参数）
		constexpr std::uint32_t kLowAck = 0x80B;      // GLOB SAQ_TestAck（脚本回执）
		constexpr std::uint32_t kLowResult = 0x80C;   // GLOB SAQ_TestResult（结果码）
		constexpr std::uint32_t kLowHarness = 0x80D;  // GLOB SAQ_TestHarness（0/1/2 见头文件）

		constexpr const char* kMenuName = "BSMissionMenu";  // 与 SAQ.cpp 的 kMenuName 一致

		std::uint64_t NowMs()
		{
			return ::GetTickCount64();
		}

		// ---------------- 日志环形缓冲 ----------------
		constexpr std::size_t kRingMax = 4000;  // 一行约 120 B ⇒ 上限约 0.5 MB

		std::mutex                                      g_ringMutex;
		std::deque<std::pair<std::uint64_t, std::string>> g_ring;
		std::atomic<std::uint64_t>                      g_ringTotal{ 0 };

		class LogRingSink final : public spdlog::sinks::base_sink<std::mutex>
		{
		protected:
			void sink_it_(const spdlog::details::log_msg& a_msg) override
			{
				spdlog::memory_buf_t buf;
				formatter_->format(a_msg, buf);
				std::string line{ buf.data(), buf.size() };
				while (!line.empty() && (line.back() == '\n' || line.back() == '\r')) {
					line.pop_back();
				}
				std::lock_guard lock{ g_ringMutex };
				g_ring.emplace_back(g_ringTotal.load(std::memory_order_relaxed), std::move(line));
				if (g_ring.size() > kRingMax) {
					g_ring.pop_front();
				}
				g_ringTotal.fetch_add(1, std::memory_order_relaxed);
			}

			void flush_() override {}
		};

		// ---------------- ini 开关（[Test] Harness）----------------
		bool   g_iniCached{};
		bool   g_iniValue{};
		std::uint64_t g_iniReadAtMs{};
		// ★ 1 秒（不是 3 秒）：驱动器每 2 秒复查一次「Harness 有没有被改成 1」，
		//   缓存太长会把「改完到开跑」的延迟拖到 5 秒以上，调试体感差（读一次 ini 很便宜）。
		constexpr std::uint64_t kIniCacheMs = 1000;

		bool ReadIniHarness()
		{
			const auto now = NowMs();
			if (g_iniCached && now - g_iniReadAtMs < kIniCacheMs) {
				return g_iniValue;
			}
			bool value = false;
			if (const auto dir = PluginDir(); !dir.empty()) {
				const auto path = (dir / L"SAQ_ShowAvailableQuests.ini").wstring();
				value = ::GetPrivateProfileIntW(L"Test", L"Harness", 0, path.c_str()) != 0;
			}
			g_iniCached = true;
			g_iniValue = value;
			g_iniReadAtMs = now;
			return value;
		}

		// ---------------- 命令状态 ----------------
		bool          g_busy{};
		bool          g_seqAdopted{};
		std::uint32_t g_lastSeq{};
		std::uint64_t g_submittedAtMs{};

		RE::TESGlobal* Glob(std::uint32_t a_low)
		{
			return Guide::FindGlob(a_low);
		}
	}

	const char* OpName(Op a_op)
	{
		switch (a_op) {
		case Op::kPing: return "Ping";
		case Op::kQuestReset: return "任务回滚(Reset)";
		case Op::kQuestStart: return "接取(Start)";
		case Op::kQuestStage: return "推阶段(SetStage)";
		case Op::kQuestComplete: return "完成(CompleteQuest)";
		case Op::kTeleport: return "传送玩家(MoveTo)";
		case Op::kCrewFaction: return "船员状态(Papyrus 只读)";
		case Op::kCrewSimRecruit: return "船员模拟招募(Papyrus 写+复原)";
		default: return "None";
		}
	}

	const char* ResultText(std::int32_t a_code)
	{
		switch (a_code) {
		case 0: return "成功";
		case 1: return "表单取不到（非常驻引用/所在 cell 没加载？）";
		case 2: return "表单类型不对";
		case 3: return "执行异常";
		case 4: return "未知操作码";
		case 5: return "通道未就绪";
		default: return "未知结果码";
		}
	}

	// ==================================================================
	//  日志环形缓冲
	// ==================================================================
	void InstallLogRing()
	{
		auto* logger = spdlog::default_logger_raw();
		if (!logger) {
			return;
		}
		for (const auto& sink : logger->sinks()) {
			if (dynamic_cast<LogRingSink*>(sink.get()) != nullptr) {
				return;  // 已经装过（Install 可能被调多次）
			}
		}
		logger->sinks().push_back(std::make_shared<LogRingSink>());
	}

	std::size_t LogMark()
	{
		return static_cast<std::size_t>(g_ringTotal.load(std::memory_order_relaxed));
	}

	bool LogFind(std::size_t a_from, const std::string& a_regex, std::string& a_line)
	{
		std::regex re;
		try {
			re = std::regex{ a_regex, std::regex::ECMAScript | std::regex::icase };
		} catch (const std::regex_error&) {
			return false;
		}
		const auto from = static_cast<std::uint64_t>(a_from);
		std::lock_guard lock{ g_ringMutex };
		for (const auto& [idx, line] : g_ring) {
			if (idx < from) {
				continue;
			}
			// ★★ 第 56 轮：断言只认**产品日志** —— harness 自己的行（`harness：…`）会原样
			//   复述它刚匹配到的正则与命中行（`[PASS] assert.log 引导已生效…` 这一句里
			//   就带着「引导已生效」四个字），留着会被后续断言当成「命中」的回声
			//   （09:22 会话 r26 的最后一条断言就这么过的）。
			if (line.find("harness：") != std::string::npos) {
				continue;
			}
			if (std::regex_search(line, re)) {
				a_line = line;
				return true;
			}
		}
		return false;
	}

	std::string LogTail(std::size_t a_maxLines)
	{
		std::string out;
		std::lock_guard lock{ g_ringMutex };
		const std::size_t skip = g_ring.size() > a_maxLines ? g_ring.size() - a_maxLines : 0;
		for (std::size_t i = skip; i < g_ring.size(); ++i) {
			out += g_ring[i].second;
			out += '\n';
		}
		return out;
	}

	std::string LogSince(std::size_t a_from, std::size_t a_maxLines)
	{
		const auto from = static_cast<std::uint64_t>(a_from);
		std::string out;
		std::size_t lines = 0;
		std::lock_guard lock{ g_ringMutex };
		for (const auto& [idx, line] : g_ring) {
			if (idx < from) {
				continue;
			}
			out += line;
			out += '\n';
			if (++lines >= a_maxLines) {
				out += "...（更多行已省略，完整日志看 mod 目录里的 SAQ_ShowAvailableQuests.log）\n";
				break;
			}
		}
		return out.empty() ? std::string{ "（本步骤之后没有产生任何日志行）\n" } : out;
	}

	// ==================================================================
	//  harness 开关（0/1/2 协议见头文件）
	// ==================================================================
	bool EnableHarnessIfNeeded()
	{
		auto* ctl = Glob(kLowHarness);
		if (!ctl) {
			return false;
		}
		if (!ReadIniHarness()) {
			// ini 关着：只在「DLL 刚请求过、脚本还没接手」时清 0（不动脚本已置的 2，
			// 免得来回改写同一个 GLOB）。
			const float v = ctl->value;
			if (v > 0.5f && v < 1.5f) {
				ctl->value = 0.0f;
			}
			return false;
		}
		const float v = ctl->value;
		if (v < 0.5f) {
			ctl->value = 1.0f;  // 请求启用；脚本下一拍回写 2
			return false;
		}
		return v >= 1.5f;  // 2 = 脚本已就绪
	}

	bool HarnessRequested()
	{
		return ReadIniHarness();  // ini 的 [Test] Harness（3 秒缓存）
	}

	bool HarnessReady(std::string& a_detail)
	{
		auto* ctl = Glob(kLowHarness);
		if (!ctl) {
			a_detail = "SAQ_TestHarness 取不到（ESM 没打第 49 轮补丁？）";
			return false;
		}
		const float v = ctl->value;
		if (v < 1.5f) {
			a_detail = std::format("脚本尚未就绪（SAQ_TestHarness={:.0f}，等它回写 2）", v);
			return false;
		}
		if (!g_seqAdopted) {
			// 首次就绪：把 DLL 的序号追平通道里的当前值（读档后通道里的值可能更大，
			// 不追平会出现「刚提交就被判成已回执」的假成功）。
			if (auto* seq = Glob(kLowSeq)) {
				const float raw = seq->value;
				g_lastSeq = (raw > 0.0f) ? static_cast<std::uint32_t>(raw) : 0u;
			}
			g_seqAdopted = true;
		}
		a_detail = std::format("就绪（seq={}）", g_lastSeq);
		return true;
	}

	bool ChannelReady(std::string& a_detail)
	{
		auto* seq = Glob(kLowSeq);
		auto* cmd = Glob(kLowCmd);
		auto* argA = Glob(kLowArgA);
		auto* argB = Glob(kLowArgB);
		auto* argC = Glob(kLowArgC);
		auto* ack = Glob(kLowAck);
		auto* result = Glob(kLowResult);
		if (!seq || !cmd || !argA || !argB || !argC || !ack || !result) {
			a_detail = "测试命令通道 GLOB 不全（0x806~0x80C）—— ESM 需要重跑 tools/esm/patch_saq_esm.py";
			return false;
		}
		// 读一遍自检：这几个 GLOB 的正常值都远小于 1e9；读到天文数字说明偏移/对象不对，
		// 此时**拒绝写内存**（与 Guide::SetGuideTarget 的「拒绝写入」同一思路）。
		for (const auto* g : { seq, cmd, argA, argB, argC, ack, result }) {
			if (!std::isfinite(g->value) || std::fabs(g->value) > 1.0e9f) {
				a_detail = std::format("通道读数像垃圾（{}）—— 拒绝写内存", g->value);
				return false;
			}
		}
		a_detail = "通道可用";
		return true;
	}

	// ==================================================================
	//  命令通道
	// ==================================================================
	bool Submit(Op a_op, std::uint32_t a_formID, std::int32_t a_arg, std::string& a_detail)
	{
		std::string why;
		if (!ChannelReady(why)) {
			a_detail = why;
			return false;
		}
		auto* seq = Glob(kLowSeq);
		auto* cmd = Glob(kLowCmd);
		auto* argA = Glob(kLowArgA);
		auto* argB = Glob(kLowArgB);
		auto* argC = Glob(kLowArgC);

		// 读档会让通道里的序号回退；提交前先跳过去（否则可能撞上一个「已经存在的 Ack」）。
		const float rawSeq = seq->value;
		if (rawSeq > 0.0f) {
			const auto chSeq = static_cast<std::uint32_t>(rawSeq);
			if (chSeq > g_lastSeq) {
				g_lastSeq = chSeq;
			}
		}
		const auto next = g_lastSeq + 1;

		argA->value = static_cast<float>(a_formID & 0xFFFFFFu);        // 低 24 位（float 精确）
		argB->value = static_cast<float>((a_formID >> 24) & 0xFFu);    // 高 8 位
		argC->value = static_cast<float>(a_arg);
		cmd->value = static_cast<float>(static_cast<std::int32_t>(a_op));
		seq->value = static_cast<float>(next);  // ★ 提交点（最后写）

		g_lastSeq = next;
		g_busy = true;
		g_submittedAtMs = NowMs();
		a_detail = std::format("seq={} {}", next, OpName(a_op));
		return true;
	}

	int Poll(std::int32_t& a_resultCode, std::string& a_detail)
	{
		if (!g_busy) {
			return 0;
		}
		auto* ack = Glob(kLowAck);
		if (!ack) {
			a_detail = "SAQ_TestAck 取不到";
			return -1;
		}
		const double ackVal = static_cast<double>(ack->value);
		if (ackVal + 0.5 < static_cast<double>(g_lastSeq)) {
			return 0;  // 还没回执
		}
		g_busy = false;
		a_resultCode = 0;
		if (auto* result = Glob(kLowResult)) {
			a_resultCode = static_cast<std::int32_t>(result->value + (result->value < 0.0f ? -0.5f : 0.5f));
		}
		a_detail = std::format("seq={} 结果={}（{}）", g_lastSeq, a_resultCode, ResultText(a_resultCode));
		return 1;
	}

	bool Busy()
	{
		return g_busy;
	}

	std::uint64_t SubmittedAtMs()
	{
		return g_submittedAtMs;
	}

	std::uint32_t LastSeq()
	{
		return g_lastSeq;
	}

	void Abandon(const char* a_why)
	{
		if (g_busy) {
			g_busy = false;
			REX::WARN("测试原语：放弃未完成的命令（seq={}）—— {}", g_lastSeq, a_why ? a_why : "");
		}
	}

	// ==================================================================
	//  菜单开关
	// ==================================================================
	bool MenuIsOpen(const char* a_name)
	{
		if (!a_name || !*a_name) {
			return false;
		}
		auto* ui = RE::UI::GetSingleton();
		return ui != nullptr && ui->IsMenuOpen(RE::BSFixedString{ a_name });
	}

	bool SetMenuOpenByName(const char* a_name, bool a_open, std::string& a_detail)
	{
		if (!a_name || !*a_name) {
			a_detail = "菜单名为空";
			return false;
		}
		auto* queue = RE::UIMessageQueue::GetSingleton();
		if (!queue) {
			a_detail = "UIMessageQueue 取不到（UI 还没起来？）";
			return false;
		}
		queue->AddMessage(RE::BSFixedString{ a_name },
			a_open ? RE::UI_MESSAGE_TYPE::kShow : RE::UI_MESSAGE_TYPE::kHide);
		a_detail = std::format("{}：{}", a_name, a_open ? "已请求打开（kShow）" : "已请求关闭（kHide）");
		return true;
	}

	// ★★ 第 58 轮：诊断助手（见头文件说明）。只查「有把握的注册名」—— IsMenuOpen 是
	//   引擎自己的函数（按注册名查哈希表），零结构体偏移风险；这与 SAQ.cpp 的
	//   OpenMenusSummary 同一思路（那里用于星图等待诊断）。
	std::string OpenMenusSummary()
	{
		static const RE::BSFixedString kNames[] = {
			"BSMissionMenu", "PauseMenu", "GalaxyStarMapMenu", "LoadingMenu", "FaderMenu", "MainMenu"
		};
		auto* ui = RE::UI::GetSingleton();
		if (!ui) {
			return "UI 单例不可用";
		}
		std::string out;
		for (const auto& name : kNames) {
			if (ui->IsMenuOpen(name)) {
				if (!out.empty()) {
					out += ", ";
				}
				out += name.c_str();
			}
		}
		return out.empty() ? std::string{ "无" } : out;
	}

	bool AnyLoadingMenuOpen()
	{
		auto* ui = RE::UI::GetSingleton();
		if (!ui) {
			return false;
		}
		// LoadingMenu = 加载画面本体；FaderMenu = 淡出淡入的黑幕（与加载同生共死，
		// 有时加载画面已关但黑幕还在）—— 两者都算「还没落地」。
		static const RE::BSFixedString kLoading{ "LoadingMenu" };
		static const RE::BSFixedString kFader{ "FaderMenu" };
		return ui->IsMenuOpen(kLoading) || ui->IsMenuOpen(kFader);
	}

	bool SetMenuOpen(bool a_open, std::string& a_detail)
	{
		std::string detail;
		if (!SetMenuOpenByName(kMenuName, a_open, detail)) {
			a_detail = detail;
			return false;
		}
		// 保持历史文案（verify 与用例判据都在用）
		a_detail = a_open ? "已请求打开任务菜单（kShow）" : "已请求关闭任务菜单（kHide）";
		return true;
	}

	bool ClearGuide(std::string& a_detail)
	{
		// 与玩家取消引导 / 接取后自动取消同一个调用（a_formID = 0 ⇒ 脚本 Clear + 取消目标显示）。
		std::string detail;
		if (!Guide::SetGuideTarget(0, detail)) {
			a_detail = "清除引导失败：" + detail;
			return false;
		}
		a_detail = detail;
		return true;
	}

	// ==================================================================
	//  ★★ 第 62 轮（大项 I）：自动读档（BGSSaveLoadManager）
	// ==================================================================
	//  路线（零新 RE 的完整推导，先读这里再看代码）：
	//
	//  ① 单例：commonlibsf 的 `ID::BGSSaveLoadManager::Singleton = 883588` 是**非 0**（可用）；
	//     而 `QueueBuildSaveGameList` / `DeleteSaveFile` / `BGSSaveLoadGame::LoadGame` 那几个
	//     都是 0（不可用）⇒ **不能**走它们的函数指针。
	//  ② 排队读档：`BGSSaveLoadManager::QueueLoadGame(entry)` 在 commonlibsf 里是**内联**的：
	//         queuedEntryToLoad = entry;  queuedTasks.set(QueuedTask::kLoadGame);
	//     游戏自己的「读取存档」菜单排的就是这两行（同一个写侧）—— 我们不复制逻辑，
	//     直接调这个内联函数。
	//  ③ 拿 entry：`saveGameList`（BSTArray<BGSSaveLoadFileEntry*>，偏移 0x018）里按
	//     `fileName`（entry 偏移 0x00）找。前提 `saveGameListBuilt`（0x030）为真 ——
	//     进过一次主菜单/「读取存档」界面就会被引擎构建。没构建时：把
	//     `kBuildSaveGameList`（0x1000）位写进 `queuedTasks`（偏移 0x050）—— 这是
	//     `QueueBuildSaveGameList` 的写侧等价（它的 ID=0，只能这样触发）；它的事务回调
	//     我们用不上 —— 驱动器轮询 `saveGameListBuilt` 变真就行。
	//
	//  ★ 安全性（项目通则：commonlibsf 偏移不可信）：
	//    · 结构体偏移来自 BGSSaveLoad.h 的 static_assert（saveGameList=0x018 / built=0x030 /
	//      count=0x034 / queuedTasks=0x050 / queuedEntryToLoad=0x058），但仍**先自校验**：
	//      built 只接受 0/1、count/list.size() 在 [0, 10000]、entry 名字必须全可打印 ASCII；
	//    · 所有指针解引用都走 SafeReadAt / SafeCopySaveName（__try 保护）——
	//      坏指针只付一次结构化异常；
	//    · 带 __try 的函数里不能有需要栈展开的对象（MSVC C2712）⇒ 探针函数统统只收裸指针、
	//      返回 POD（字符串拼装全在外面做）。
	//    · 写内存（queuedTasks / queuedEntryToLoad）前必须**已通过 shape 校验**；
	//      写完之后**读回校验**一次（对不上 ⇒ 报「偏移可能不对」并判失败，不静默）。
	// ==================================================================

	static_assert(RE::ID::BGSSaveLoadManager::Singleton.id() != 0,
		"自动读档依赖 BGSSaveLoadManager::Singleton（ID 883588）—— 为 0 时这套原语不可用");

	namespace
	{
		// 读一个 POD（SEH 保护）。注意：只放进「无栈展开对象」的小函数里（见上方 C2712 说明）。
		template <class T>
		bool SafeReadAt(const void* a_src, T& a_out)
		{
			__try {
				a_out = *static_cast<const T*>(a_src);
				return true;
			} __except (EXCEPTION_EXECUTE_HANDLER) {
				return false;
			}
		}

		// 把 C 字符串拷进定长缓冲（POD-only）。要求**非空且全可打印 ASCII** —— 存档名本来
		// 就是这样；读出一堆控制字符说明指针/偏移不对，返回 false。
		bool SafeCopySaveName(const char* a_src, char* a_out, std::size_t a_outSize)
		{
			a_out[0] = '\0';
			if (a_src == nullptr || a_outSize < 2) {
				return false;
			}
			__try {
				std::size_t i = 0;
				for (; i + 1 < a_outSize && a_src[i] != '\0'; ++i) {
					const unsigned char ch = static_cast<unsigned char>(a_src[i]);
					if (ch < 0x20 || ch > 0x7E) {
						a_out[0] = '\0';
						return false;  // 不可打印 ⇒ 形状不对
					}
					a_out[i] = static_cast<char>(ch);
				}
				if (i == 0 || i + 1 >= a_outSize) {
					a_out[0] = '\0';
					return false;
				}
				a_out[i] = '\0';
				return true;
			} __except (EXCEPTION_EXECUTE_HANDLER) {
				a_out[0] = '\0';
				return false;
			}
		}

		// 大小写不敏感的「a_haystack 含 a_needle」。
		bool ContainsNoCase(std::string_view a_haystack, std::string_view a_needle)
		{
			if (a_needle.empty() || a_needle.size() > a_haystack.size()) {
				return false;
			}
			auto lower = [](char c) {
				return static_cast<char>(std::tolower(static_cast<unsigned char>(c)));
			};
			for (std::size_t i = 0; i + a_needle.size() <= a_haystack.size(); ++i) {
				std::size_t j = 0;
				for (; j < a_needle.size(); ++j) {
					if (lower(a_haystack[i + j]) != lower(a_needle[j])) {
						break;
					}
				}
				if (j == a_needle.size()) {
					return true;
				}
			}
			return false;
		}
	}

	std::string SaveGameListSummary()
	{
		auto* mgr = RE::BGSSaveLoadManager::GetSingleton();
		if (mgr == nullptr) {
			return "BGSSaveLoadManager 单例取不到（地址库 ID 883588 没解析出来？）";
		}
		bool          built = false;
		std::uint32_t count = 0;
		if (!SafeReadAt(&mgr->saveGameListBuilt, built) || !SafeReadAt(&mgr->saveGameCount, count)) {
			return "读 saveGameListBuilt/saveGameCount 触发异常 —— 单例或偏移不对（拒绝使用）";
		}
		std::string out = std::format("单例=OK built={} count={}", built ? 1 : 0, count);
		if (!built) {
			out += "（列表未构建 —— 进过一次「读取存档」界面就会构建；save.load 会先请求构建）";
			return out;
		}
		const auto n = mgr->saveGameList.size();
		out += std::format(" listSize={}", n);
		if (n == 0) {
			out += "（列表是空的？）";
			return out;
		}
		if (n > 10000) {
			out += " —— listSize 不合理（偏移可能不对，拒绝继续读）";
			return out;
		}
		const auto* base = mgr->saveGameList.data();
		if (base == nullptr) {
			out += " —— 列表数据指针为空（偏移可能不对）";
			return out;
		}
		const std::uint32_t shown = std::min<std::uint32_t>(n, 8);
		std::uint32_t       readable = 0;
		for (std::uint32_t i = 0; i < shown; ++i) {
			RE::BGSSaveLoadFileEntry* e = nullptr;
			char                      name[192]{};
			if (!SafeReadAt(base + i, e) || e == nullptr) {
				out += std::format("｜[{}]=空", i);
				continue;
			}
			if (!SafeCopySaveName(e->fileName, name, sizeof(name))) {
				out += std::format("｜[{}]=(名字不可读 —— 偏移可能不对)", i);
				continue;
			}
			out += std::format("｜[{}]{}", i, name);
			++readable;
		}
		out += std::format("（前 {} 个里 {} 个名字可读）", shown, readable);
		return out;
	}

	bool QueueLoadSaveByName(const std::string& a_nameSubstring, std::string& a_detail)
	{
		if (a_nameSubstring.empty()) {
			a_detail = "存档名子串为空";
			return false;
		}
		auto* mgr = RE::BGSSaveLoadManager::GetSingleton();
		if (mgr == nullptr) {
			a_detail = "BGSSaveLoadManager 单例取不到（地址库 ID 883588 没解析出来？）";
			return false;
		}
		bool          built = false;
		std::uint32_t count = 0;
		if (!SafeReadAt(&mgr->saveGameListBuilt, built) || !SafeReadAt(&mgr->saveGameCount, count) ||
			count > 10000) {
			a_detail = "存档列表形状不对（built/count 读数异常）—— 拒绝使用（偏移可能不对）";
			return false;
		}
		if (!built) {
			// 触发异步构建（等价于 QueueBuildSaveGameList 的写侧 —— 它的事务回调我们用不上）。
			mgr->queuedTasks.set(RE::BGSSaveLoadManager::QueuedTask::kBuildSaveGameList);
			a_detail = "存档列表未构建 —— 已请求构建（驱动器下一拍再试）";
			return false;
		}
		const auto n = mgr->saveGameList.size();
		const auto* base = mgr->saveGameList.data();
		if (base == nullptr || n == 0 || n > 10000) {
			a_detail = std::format("存档列表形状不对（size={}）—— 拒绝使用", n);
			return false;
		}
		RE::BGSSaveLoadFileEntry* hit = nullptr;
		std::uint32_t             hitIndex = 0;
		char                      hitName[192]{};
		std::string               listed;
		for (std::uint32_t i = 0; i < n; ++i) {
			RE::BGSSaveLoadFileEntry* e = nullptr;
			char                      name[192]{};
			if (!SafeReadAt(base + i, e) || e == nullptr ||
				!SafeCopySaveName(e->fileName, name, sizeof(name))) {
				continue;
			}
			if (i < 8) {
				listed += std::format("{}「{}」", listed.empty() ? "" : "｜", name);
			}
			if (hit == nullptr && ContainsNoCase(name, a_nameSubstring)) {
				hit = e;
				hitIndex = i;
				std::memcpy(hitName, name, sizeof(hitName));
			}
		}
		if (hit == nullptr) {
			a_detail = std::format("没找到名字含「{}」的存档（共 {} 个；前几个：{}）",
				a_nameSubstring, n, listed.empty() ? std::string{ "（都不可读）" } : listed);
			return false;
		}
		// ★ 排队读档 —— 与游戏「读取存档」菜单同一个写侧（commonlibsf 的内联 QueueLoadGame）。
		mgr->QueueLoadGame(hit);
		// 写回校验：队列字段确实指向我们挑的 entry 吗（偏移不对时不静默）。
		RE::BGSSaveLoadFileEntry* check = nullptr;
		const bool queuedOk = SafeReadAt(&mgr->queuedEntryToLoad, check) && check == hit;
		a_detail = std::format("已排队读档：{}（列表第 {} 个 / 共 {}）{}", hitName, hitIndex, n,
			queuedOk ? "｜队列字段写回校验通过"
					 : "｜⚠ 队列字段写回校验失败（偏移可能不对，读档可能不会发生）");
		return queuedOk;
	}

	// ★★ 第 62 轮补：ini [Test] AutoLoad（见头文件说明）。
	//   与 ReadIniHarness 同一策略：1 秒缓存（改 ini 不必重启游戏，下一拍就生效）。
	std::string AutoLoadSaveName()
	{
		static std::uint64_t s_cachedAtMs = 0;
		static std::string   s_cached;
		const auto           now = NowMs();
		if (s_cachedAtMs != 0 && now - s_cachedAtMs < kIniCacheMs) {
			return s_cached;
		}
		s_cachedAtMs = now;
		s_cached.clear();
		if (const auto dir = PluginDir(); !dir.empty()) {
			const auto path = (dir / L"SAQ_ShowAvailableQuests.ini").wstring();
			wchar_t    buf[256]{};
			::GetPrivateProfileStringW(L"Test", L"AutoLoad", L"", buf,
				static_cast<DWORD>(std::size(buf)), path.c_str());
			// 存档名是 ASCII（如 Save7_3AB5A2FAM…）；宽字符直接窄化 —— 出现非 ASCII
			// 一律当作没配置（防手滑输入中文按键名，静默失败比报错难查）。
			for (const wchar_t w : buf) {
				if (w == L'\0') {
					break;
				}
				if (w > 0x7F) {
					s_cached.clear();
					return s_cached;
				}
				s_cached += static_cast<char>(w);
			}
		}
		return s_cached;
	}

	// ==================================================================
	//  UI 测试驱动（实现在 SAQ_UI.cpp —— 那里有桥的解析与 Invoke 校验）
	// ==================================================================
	bool InvokeUiTestDrive(const char* a_fn, const std::string& a_arg, std::string& a_reply)
	{
		return UI::InvokeUiTestDrive(a_fn, a_arg, a_reply);
	}
}

#endif  // SAQ_WITH_HARNESS

