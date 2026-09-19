// ============================================================================
//  Starfield Show Available Quests - 核心逻辑（SAQ_ShowAvailableQuests.dll）
//
//  目标（见 AGENTS.md）：
//    在游戏原版任务菜单（BSMissionMenu）里新增一个 tab「可接任务」，
//    列出当前游戏进度下玩家还能接到的任务（非主线）。
//
//  数据流：
//    UI 打开 BSMissionMenu
//      -> 本文件收集可接任务（静态任务表 + 引擎侧存在性校验）
//      -> SAQ_UI（自己按反汇编出来的算法查菜单表）拿到 ASMovieRoot
//      -> Invoke("SetAvailableQuests", <一行行文本>)（见 SAQ_UI.cpp 的协议）
//      -> AS3 侧解析成任务条目，并入任务列表，tab 过滤显示
//
//  几个「不要再踩」的坑（来自上一代项目 always scan 的实测）：
//    ① **绝不缓存 BSTArray 的 data()/capacity()**：清表可能释放/搬移缓冲，
//       缓存下来就是悬空指针。本文件每次现读。
//    ② **只看主线程**：读档期间加载线程也会跑到这里；加主线程判定。
//    ③ ★ **不要用 UI::GetMenuMovie()**：1.16.244.0 上它查的表（0x470）是错的，
//       真实菜单表在 UI+0x450（反汇编 UI::IsMenuOpen 实证）—— 详见 SAQ_UI.cpp。
//    ④ ★ **不要用 TESDataHandler::formArrays 数任务**：本机实测读到空表（见 docs/02），
//       改用 TESForm::LookupByID 按 FormID 问引擎。
// ============================================================================

#include "PCH.h"

#include "SAQ.h"
#include "SAQ_Guide.h"       // 引导通道（DLL ↔ ESM 的 GLOB ↔ SAQ_Main.psc）
#include "SAQ_QuestState.h"  // TESQuest 运行时状态（已开始/已完成/追踪中）
#include "SAQ_UI.h"          // UI 通道（菜单表 → IMenu → Movie → ASMovieRoot）
#include "SAQ_QuestTable.h"  // 生成物：FormID -> 中/英文名 + 类型 + 引导目标（tools/esm/gen_quest_table.py）

#include "RE/B/BSFixedString.h"
#include "RE/B/BSTEvent.h"
#include "RE/F/FormTypes.h"
#include "RE/IDs.h"  // 编译期 ID 审计要用（见下方 kIdUsable）
#include "RE/I/INISettingCollection.h"
#include "RE/S/Setting.h"
#include "RE/T/TESDataHandler.h"
#include "RE/T/TESForm.h"
#include "RE/U/UI.h"

#include <Windows.h>

#include <atomic>
#include <cstdint>
#include <format>
#include <memory>
#include <string>
#include <unordered_map>
#include <utility>
#include <vector>

namespace SAQ
{
	using namespace std::string_view_literals;

	namespace
	{
		constexpr const char* kMenuName = "BSMissionMenu";  // 原版任务菜单
		constexpr std::int32_t kAvailableQuestType = 6;     // AS3：QuestUtils.AVAILABLE_QUEST_TYPE

		// ==================================================================
		// 编译期 ID 审计（别删！）
		//
		// commonlibsf 的 RE/IDs.h 里，**这一版还没移植的接口其 REL::ID 值就是 0**。
		// 0 不是「未初始化」，运行时一碰就炸：REL::IDDB::offset() 查 Address
		// Library 查到 0 会直接 REX::FAIL，游戏里弹出
		//   "Failed to find offset for Address Library ID! ... Invalid ID: 0"
		// 的模态框（实测踩过：BGSStoryTeller::Singleton 就是 0）。
		//
		// 所以本插件依赖的每个 REL::ID 都在这里静态断言一次，把这类地雷
		// 挡在**编译期**。新增接口时把用到的 ID 一并登记。
		// （间接用到的也要登记：commonlibsf 里 inline 函数内部藏的 REL::ID
		// 一样会炸，例如 BSFixedString 的构造/析构走 BSStringPool。）
		// ==================================================================

		constexpr bool kIdUsable(REL::ID a_id) noexcept { return a_id.id() != 0; }

		static_assert(kIdUsable(RE::ID::UI::Singleton));                 // UI::GetSingleton
		static_assert(kIdUsable(RE::ID::UI::IsMenuOpen));                // UI::IsMenuOpen
		static_assert(kIdUsable(RE::ID::TESDataHandler::Singleton));     // TESDataHandler::GetSingleton（自检用）
		static_assert(kIdUsable(RE::ID::TESForm::LookupByID));           // 按 FormID 问引擎要表单
		static_assert(kIdUsable(RE::ID::INISettingCollection::Singleton));  // 读 sLanguage:General
		static_assert(kIdUsable(RE::ID::BSStringPool::GetEntry));        // BSFixedString 构造
		static_assert(kIdUsable(RE::ID::BSStringPool::Entry::Release));  // BSFixedString 析构

		std::atomic_bool g_installed{ false };
		std::atomic_bool g_firstMenuLogged{ false };
		std::atomic<std::uint64_t> g_pushCount{ 0 };
		std::atomic_uint32_t g_mainThreadId{ 0 };

		// 运行时过滤的统计（第 9 轮）：只为了「日志能自证」而留。
		struct RuntimeFilterStats
		{
			std::size_t live{};               // 引擎里确实存在这个 FormID
			std::size_t recognized{};         // 虚表核对通过（确认是 TESQuest）
			std::size_t unrecognized{};       // 虚表不认识（不计入过滤，留证据）
			std::size_t started{};            // 引擎已经开始
			std::size_t completed{};          // 已完成
			std::size_t tracked{};            // 正被玩家追踪
			std::size_t hidden{};             // 因运行时状态被剔掉的
			bool        filterApplied{};      // 这次到底有没有按运行时状态过滤
			std::string samples;              // 被剔掉的前几条（名字 + 状态）
			std::string vtableSamples;        // 未识别虚表的样本（诊断）
			// ---- 诊断用（不参与过滤）：静态 DNAM 标志位的分布 ----
			// 目的：搞清哪一位代表「引擎自动启动」——「进度没到不显示」要用它。
			// 判据：拿「引擎已开始」的那几条的 staticFlags 与全体做对比（见 samples 里的 DN 值）。
			std::size_t flagBitCount[24]{};   // 位 i 在候选里出现的次数
			std::size_t startedSamples{};     // 已开始的样本条数
			std::string startedFlags;         // 已开始任务的 `名字(DNAM=0x…)` 样本
		};

		// 推送重试状态（只在主线程读写，不需要锁）。
		// 菜单刚打开的那一两帧 SWF 可能还没初始化完，Invoke 会失败 —— 隔几帧再试。
		struct PendingPush
		{
			std::vector<QuestEntry> quests;
			std::size_t             total{};
			std::uint32_t           attempts{};
			std::uint64_t           lastAttemptMs{};
			RuntimeFilterStats      stats;
		};
		PendingPush g_pending;
		constexpr std::uint32_t kMaxPushAttempts = 10;
		constexpr std::uint64_t kPushRetryIntervalMs = 400;

		// ------------------------------------------------------------------
		// 本地化
		//
		// ★ 语言判定**不在 C++ 侧做**（只把读到的值打进日志）：
		//   本机实测：游戏界面是中文，但 `INISettingCollection::GetSetting("sLanguage:General")`
		//   取不到值（拿到的永远是兜底值），两个 INI 文件里也**根本没有 sLanguage 这一项**
		//   —— 也就是说这个值在 Steam 版里另有来源。上一轮就是被它坑到：
		//   日志打出「语言=en 标题=Available」，而游戏其实是中文。
		//
		//   所以现在：标题和任务名都带中英两份一起推给 AS3，由 AS3 侧用
		//   **引擎推来的本地化任务名**（QuestData）判定语言 —— 那才是最可靠的信号。
		// ------------------------------------------------------------------

		// 兜底：直接读 INI 文件（有的玩家会自己改 ini 设语言）
		std::string ReadIniLanguageFromDisk()
		{
			std::wstring gameIni;
			if (wchar_t exePath[MAX_PATH]{}; ::GetModuleFileNameW(nullptr, exePath, MAX_PATH) > 0) {
				std::wstring p{ exePath };
				if (const auto slash = p.find_last_of(L'\\'); slash != std::wstring::npos) {
					gameIni = p.substr(0, slash + 1) + L"Starfield.ini";
				}
			}
			std::wstring customIni;
			if (wchar_t profile[MAX_PATH]{}; ::GetEnvironmentVariableW(L"USERPROFILE", profile, MAX_PATH) > 0) {
				customIni = std::wstring{ profile } + L"\\Documents\\My Games\\Starfield\\StarfieldCustom.ini";
			}

			const std::wstring candidates[] = { customIni, gameIni };  // 自定义 INI 优先
			for (const auto& ini : candidates) {
				if (ini.empty()) {
					continue;
				}
				wchar_t buf[64]{};
				if (::GetPrivateProfileStringW(L"General", L"sLanguage", L"", buf, 64, ini.c_str()) > 0) {
					char utf8[128]{};
					if (::WideCharToMultiByte(CP_UTF8, 0, buf, -1, utf8, sizeof(utf8), nullptr, nullptr) > 0) {
						return utf8;
					}
				}
			}
			return {};
		}

		std::string GetGameLanguage()
		{
			if (auto* ini = RE::INISettingCollection::GetSingleton()) {
				const auto lang = ini->GetSetting<std::string_view>("sLanguage:General"sv, ""sv);
				if (!lang.empty()) {
					return std::string{ lang };
				}
			}
			if (auto disk = ReadIniLanguageFromDisk(); !disk.empty()) {
				return disk;
			}
			return "?";
		}

		std::uint64_t NowMs()
		{
			return ::GetTickCount64();
		}

		// ------------------------------------------------------------------
		// 数据收集
		// ------------------------------------------------------------------

		// ★ 关于「已经开始的 quest 怎么排除」（第 9 轮的结论）：
		//   老路（BGSStoryTeller::GetSingleton）走不通 —— commonlibsf 里它的
		//   REL::ID 就是 0，一碰弹 "Invalid ID: 0"（见文件上方 ID 审计）。
		//   这一轮改成**直接读 TESQuest 自己的运行时标志位**：读法不是猜的，
		//   而是把 Papyrus Quest 原生函数（IsRunning / IsCompleted / IsActive）
		//   在 exe 里的实现反汇编抄下来的，见 SAQ_QuestState.h 顶部注释。
		//
		//   两层过滤的分工：
		//     * C++（这里）：引擎**已经开始 / 已完成**的 → 不是「可接」任务，剔掉；
		//     * AS3（MissionMenu.FilterKnownQuests）：玩家任务日志里已有的 → 剔掉
		//       （日志来自引擎推给 UI 的 QuestData，最权威）。
		//   两层互不依赖、还能互相验证：日志里 C++ 的「隐藏」条数与 AS3 的
		//   `keep` 缺口应该对得上（第 8 轮实测 keep=199 ⇒ 有 3 条已被玩家拿到）。
		//
		// 收集"可接任务"候选 + 按运行时状态过滤。
		//
		// 规则：
		//   * 必须命中静态表 => 有 QTYP（玩家可见任务）且非主线
		//   * 引擎里确实存在这个 FormID（★ 用 TESForm::LookupByID 问引擎，
		//     **不再用 TESDataHandler::formArrays** —— 1.16.244.0 上实测那里读到空表，
		//     结果"quest 总数=0"、列表当然是空的，见 docs/02）
		//   * 引擎已经开始的 / 已完成的 → 剔掉（统计照原样写进日志）
		//   * 名称中英都带上，AS3 侧按游戏语言挑
		void CollectAvailableQuests(std::vector<QuestEntry>& a_out, std::size_t& a_totalQuests, RuntimeFilterStats& a_stats)
		{
			a_stats = {};
			a_totalQuests = kQuestTableSize;
			a_out.reserve(kQuestTableSize);

			// 第一遍：确认引擎里有这个表单 + 读运行时状态（同时统计）。
			// 结果按 kQuestTable 的下标对齐存放；被运行时状态剔掉的存 nullptr 占位。
			std::vector<const RE::TESForm*> forms(kQuestTableSize, nullptr);
			std::vector<QuestRuntimeState>  states(kQuestTableSize);
			std::size_t hiddenByRuntime = 0;
			constexpr std::size_t kMaxSamples = 5;
			std::size_t sampleCount = 0;

			for (std::size_t i = 0; i < kQuestTableSize; ++i) {
				const auto& info = kQuestTable[i];
				auto* form = RE::TESForm::LookupByID(static_cast<RE::TESFormID>(info.formID));
				if (!form) {
					continue;  // 这个 FormID 在当前加载顺序里不存在（理论上 Starfield.esm 必有）
				}
				++a_stats.live;

				const auto state = ReadQuestRuntimeState(form);
				states[i] = state;
				if (state.vtableKnown) {
					++a_stats.recognized;
				} else {
					++a_stats.unrecognized;
					if (a_stats.vtableSamples.size() < 400) {
						a_stats.vtableSamples += std::format("{}[vt={:#x} {}] ", info.nameEn, state.vtable, Describe(state));
					}
				}
				// 静态 DNAM 位分布（诊断）：位含义未知，先把数据攒下来 —— 等下一轮日志
				// 把「引擎已开始的那几条」的 DNAM 值一对比，就知道哪一位是「自动启动」。
				for (std::size_t bit = 0; bit < 24; ++bit) {
					if (info.staticFlags & (1u << bit)) {
						++a_stats.flagBitCount[bit];
					}
				}
				if (state.started) {
					++a_stats.started;
					if (a_stats.startedSamples < 6) {
						++a_stats.startedSamples;
						a_stats.startedFlags += std::format("{}[DN={:#x} {}] ", info.nameZh, info.staticFlags, Describe(state));
					}
				}
				if (state.completed) {
					++a_stats.completed;
				}
				if (state.active) {
					++a_stats.tracked;
				}

				if (IsAlreadyEngaged(state) && state.vtableKnown) {
					++hiddenByRuntime;
					if (sampleCount < kMaxSamples) {
						++sampleCount;
						a_stats.samples += std::format("{}（{}） ", info.nameZh, Describe(state));
					}
					continue;  // forms[i] 保持 nullptr ⇒ 第二遍不出条目
				}

				forms[i] = form;
			}

			// 安全阀：虚表识别率太低 ⇒ 说明「0x114 这套判据在这台机器/这个版本上不成立」，
			// 那就**不过滤**（只把证据写进日志），免得凭错误的对象把整个列表清空。
			const auto recognizedPct = a_stats.live == 0 ? 100u : static_cast<unsigned>(a_stats.recognized * 100 / a_stats.live);
			a_stats.filterApplied = recognizedPct >= 80;
			a_stats.hidden = a_stats.filterApplied ? hiddenByRuntime : 0;

			// 第二遍：出候选（被运行时状态剔掉的不再进来）。
			for (std::size_t i = 0; i < kQuestTableSize; ++i) {
				const auto* form = forms[i];
				if (!form) {
					continue;
				}
				const auto& info = kQuestTable[i];
				QuestEntry entry;
				entry.formID = info.formID;
				entry.type = kAvailableQuestType;  // 统一放到我们的 tab
				entry.nameZh = info.nameZh;        // 中英都带上，AS3 侧按游戏语言挑
				entry.nameEn = info.nameEn;
				a_out.push_back(std::move(entry));
			}
		}

		// 一次性自检：把几个 form 数组的长度打出来（只读长度、不迭代）。
		// 目的是把「为什么 TESDataHandler 那条路读到 0」这件事钉死（偏移过时 / 索引不对）。
		void LogFormArrayProbe()
		{
			auto* dataHandler = RE::TESDataHandler::GetSingleton();
			if (!dataHandler) {
				REX::INFO("自检: TESDataHandler = null");
				return;
			}
			const RE::FormType probe[] = {
				RE::FormType::kQUST,
				RE::FormType::kNPC_,
				RE::FormType::kARMO,
				RE::FormType::kWEAP,
				RE::FormType::kMESG,
				RE::FormType::kFLST,
			};
			std::string line;
			for (const auto type : probe) {
				const auto& arr = dataHandler->formArrays[std::to_underlying(type)].formArray;
				line += std::to_string(std::to_underlying(type));
				line += '=';
				line += std::to_string(arr.size());
				line += ' ';
			}
			REX::INFO("自检: TESDataHandler={:p} formArrays[类型=数量] {}", static_cast<const void*>(dataHandler), line);
		}

		// ------------------------------------------------------------------
		// UI 推送
		// ------------------------------------------------------------------

		bool PushToUI(const std::vector<QuestEntry>& a_quests)
		{
			std::string detail;
			const bool ok = UI::PushAvailableQuests(a_quests, detail);
			if (ok) {
				REX::INFO("推送成功：{} | {} 条", detail, a_quests.size());
			} else {
				REX::WARN("推送失败：{}", detail);
			}
			return ok;
		}

		// ------------------------------------------------------------------
		// 菜单打开检测
		//
		// 为什么不用 MenuOpenCloseEvent sink：它的定义在 RE/E/Events.h 里，
		// 而那个头文件不自包含（sizeof(HitData) 的 static_assert 会直接炸），
		// 于是改成每帧轮询 UI::IsMenuOpen —— 等效、零风险，且能精确拿到
		// 「由关变开」这一跳。
		// ------------------------------------------------------------------

		const RE::BSFixedString& MenuName()
		{
			// 静态局部：第一次调用时（游戏运行中）构造，之后零开销
			static const RE::BSFixedString name{ kMenuName };
			return name;
		}

		std::atomic_bool g_menuWasOpen{ false };

		// 运行时过滤统计的一行日志（菜单一开就打 —— 这一行要和 AS3 那份
		// `keep=` 交叉验证：C++ 剔掉的数量应当覆盖 AS3 任务日志里已有的那些）。
		std::string FormatRuntimeStats(const RuntimeFilterStats& a_stats)
		{
			std::string out = std::format(
				"运行时状态：引擎存在={} 虚表识别={} 未识别={} 已开始={} 已完成={} 追踪中={} 隐藏={} 过滤={}",
				a_stats.live, a_stats.recognized, a_stats.unrecognized,
				a_stats.started, a_stats.completed, a_stats.tracked, a_stats.hidden,
				a_stats.filterApplied ? "生效" : "跳过(识别率<80%)");
			if (!a_stats.samples.empty()) {
				out += " 隐藏例: " + a_stats.samples;
			}
			if (!a_stats.vtableSamples.empty()) {
				out += " 未识别例: " + a_stats.vtableSamples;
			}
			return out;
		}

		// 静态 DNAM 位的分布 + 「引擎已开始」样本（**诊断第二行**，不参与过滤）。
		// 想知道的是：「引擎自己启动的任务」在 DNAM 上是哪一位 ——
		// 那一位置起来 ⇒ 「进度没到不显示」就能靠静态数据实现（见 docs/04 第五节）。
		std::string FormatStaticFlagStats(const RuntimeFilterStats& a_stats)
		{
			std::string bits;
			for (std::size_t bit = 0; bit < 24; ++bit) {
				if (a_stats.flagBitCount[bit] == 0) {
					continue;
				}
				bits += std::format("位{}={} ", bit, a_stats.flagBitCount[bit]);
			}
			std::string out = "DNAM 位分布（候选 " + std::to_string(a_stats.live) + " 条）：" + (bits.empty() ? "全 0" : bits);
			if (!a_stats.startedFlags.empty()) {
				out += "已开始样本: " + a_stats.startedFlags;
			} else {
				out += "已开始样本: 无（说明这一档还没有任务被引擎启动）";
			}
			return out;
		}

		// 尝试把待推送的数据送进 SWF；失败就隔 400ms 再试（菜单刚开那一两帧 SWF 可能还没就绪）。
		void TryPushPending()
		{
			if (g_pending.quests.empty() || g_pending.attempts >= kMaxPushAttempts) {
				return;
			}
			const auto now = NowMs();
			if (g_pending.attempts > 0 && now - g_pending.lastAttemptMs < kPushRetryIntervalMs) {
				return;
			}
			g_pending.lastAttemptMs = now;
			++g_pending.attempts;

			// 第一次打开菜单时做一次性自检 + UI 桥解析日志（只打一次，不刷屏）
			if (!g_firstMenuLogged.exchange(true)) {
				LogFormArrayProbe();
				std::string bridgeDetail;
				if (UI::EnsureResolved(bridgeDetail)) {
					REX::INFO("UI 桥解析：{}", bridgeDetail);
				} else {
					REX::WARN("UI 桥解析失败：{}", bridgeDetail);
				}
			}

			if (PushToUI(g_pending.quests)) {
				const auto n = ++g_pushCount;
				REX::INFO("菜单打开：静态表={} 引擎里存在={} 推送条数={} (第{}次)",
					g_pending.total, g_pending.stats.live, g_pending.quests.size(), n);
				g_pending.quests.clear();
				g_pending.attempts = kMaxPushAttempts;  // 本次不再重试
			} else if (g_pending.attempts >= kMaxPushAttempts) {
				REX::WARN("推送放弃：重试 {} 次仍未成功（下次打开菜单会再试）", g_pending.attempts);
				g_pending.quests.clear();
			}
		}

		// ------------------------------------------------------------------
		// 界面状态轮询（第 9 轮新增）
		//
		// 第 8 轮只能证明「推送成功」，证明不了「玩家切到我们那个 tab 之后到底看到了什么」。
		// 现在菜单开着的时候每 500ms 读一次 AS3 自报状态（`_root.SAQ_Report`），
		// **只在内容变化时记一行** —— 切 tab、列表长度变化都会在日志里留下证据，
		// 关菜单时再把最后一条状态补记一次。
		// ------------------------------------------------------------------
		struct ReportPoll
		{
			std::uint64_t lastPollMs{};
			std::string   lastReport;
			std::uint32_t logged{};
		};
		ReportPoll g_poll;
		constexpr std::uint64_t kReportPollIntervalMs = 500;
		constexpr std::uint32_t kReportPollMaxLines = 60;  // 一次开菜单最多记这么多行

		void ResetReportPoll()
		{
			g_poll.lastPollMs = 0;
			g_poll.lastReport.clear();
			g_poll.logged = 0;
		}

		void PollUiReport()
		{
			if (g_poll.logged >= kReportPollMaxLines) {
				return;
			}
			const auto now = NowMs();
			if (g_poll.lastPollMs != 0 && now - g_poll.lastPollMs < kReportPollIntervalMs) {
				return;
			}
			g_poll.lastPollMs = now;

			std::string report;
			if (!UI::ReadUiReport(report)) {
				return;  // 桥没通 / SWF 旧版 / 换代的中间态：静默跳过，不刷屏
			}
			if (report == g_poll.lastReport) {
				return;  // 没变化就不记（这样日志里只留下「发生过什么」）
			}
			g_poll.lastReport = report;
			++g_poll.logged;
			REX::INFO("界面状态[{}]：{}", g_poll.logged, report);
		}

		// ------------------------------------------------------------------
		// 引导（第 10 轮）：AS3 请求 → 静态表查「引导目标引用」→ 写 ESM 通道
		//
		// 数据流（链路每一段都能在日志里自证，见 SAQ_Guide.h 顶部注释）：
		//   AS3 玩家按键 → _root.SAQ_PeekGuide() 返回 "<序号>|<任务FormID>"
		//   → 这里按 FormID 在静态表里取引导目标引用（离线从任务发布者/落脚点算出来的）
		//   → 写 GLOB（SAQ_GuideTargetRef = 目标, SAQ_GuideState = 0）
		//   → SAQ_Main.psc 轮询到 → ForceRefTo + 显示目标 + 设为追踪 → 引擎画标记
		// ------------------------------------------------------------------
		struct GuideRuntime
		{
			int           lastSeq{ -1 };   // 见过的最大请求序号（-1 = 没见过请求）
			std::string   lastPeek;        // 上次读到的原始字符串（变化才算新请求）
			std::uint64_t lastPollMs{};
			std::uint32_t questFormID{};   // 当前正在引导的任务（0 = 没有）
			std::uint32_t guideRef{};      // 写进 GLOB 的目标引用
			std::string   channelSummary;  // ESM 通道摘要（变化才记一行日志）
		};
		GuideRuntime g_guide;
		constexpr std::uint64_t kGuidePollIntervalMs = 100;

		const StaticQuestInfo* FindStaticQuest(std::uint32_t a_formID)
		{
			for (std::size_t i = 0; i < kQuestTableSize; ++i) {
				if (kQuestTable[i].formID == a_formID) {
					return &kQuestTable[i];
				}
			}
			return nullptr;
		}

		// ESM 通道摘要：只在变化时记一行。成功认领与失败原因都会留证。
		void LogEsmChannel()
		{
			const auto ch = Guide::EnsureChannel();
			if (ch.summary == g_guide.channelSummary) {
				return;
			}
			g_guide.channelSummary = ch.summary;
			if (ch.resolved) {
				REX::INFO("ESM 通道：{}", ch.summary);
			} else {
				REX::WARN("ESM 通道：{}", ch.summary);
			}
		}

		// 当前引导状态一行（菜单一开就记：任务、目标引用、脚本处理结果）。
		void LogGuideState()
		{
			const auto ch = Guide::EnsureChannel();
			const float scriptState = ch.resolved ? ch.guideState : -1.0f;
			if (g_guide.questFormID == 0) {
				REX::INFO("引导状态：无（还没选过引导目标）｜脚本状态={:.0f}", scriptState);
				return;
			}
			const auto* entry = FindStaticQuest(g_guide.questFormID);
			REX::INFO("引导状态：{}（0x{:08X}）目标引用=0x{:08X} {}｜脚本状态={:.0f}"
					  "（0 待处理 / 1 已应用 / 2 取不到 / 3 已清除 / 4 别名不存在）",
				entry ? entry->nameZh : "?", g_guide.questFormID, g_guide.guideRef,
				entry ? entry->whereZh : "", scriptState);
		}

		// 应用一次引导请求。a_formID = 0 表示取消引导。
		void ApplyGuideRequest(std::uint32_t a_formID)
		{
			if (a_formID == 0) {
				std::string detail;
				if (Guide::SetGuideTarget(0, detail)) {
					REX::INFO("引导请求：取消｜{}", detail);
				} else {
					REX::WARN("引导请求：取消失败｜{}", detail);
				}
				g_guide.questFormID = 0;
				g_guide.guideRef = 0;
				return;
			}
			const auto* entry = FindStaticQuest(a_formID);
			if (!entry) {
				REX::WARN("引导请求：静态表里没有 0x{:08X}（是内嵌回退表里的条目？）", a_formID);
				return;
			}
			if (entry->guideRef == 0) {
				REX::WARN("引导请求：{}（0x{:08X}）没有引导目标（离线没算出「去哪里接」的引用，见 docs/05）",
					entry->nameZh, a_formID);
				return;
			}
			std::string detail;
			if (!Guide::SetGuideTarget(entry->guideRef, detail)) {
				REX::WARN("引导请求：{}（0x{:08X}）写 ESM 通道失败｜{}", entry->nameZh, a_formID, detail);
				return;
			}
			g_guide.questFormID = a_formID;
			g_guide.guideRef = entry->guideRef;
			REX::INFO("引导请求：{}（0x{:08X}）→ 引用 0x{:08X}（{}）｜{}",
				entry->nameZh, a_formID, entry->guideRef, entry->whereZh, detail);
		}

		// 菜单开着时轮询 AS3 的引导请求（`_root.SAQ_PeekGuide` → "<序号>|<任务FormID>"）。
		// 序号 0 = 还没有请求；序号变化才算一次新请求（同一个请求不会被重复处理）。
		void PollGuideRequest()
		{
			const auto now = NowMs();
			if (g_guide.lastPollMs != 0 && now - g_guide.lastPollMs < kGuidePollIntervalMs) {
				return;
			}
			g_guide.lastPollMs = now;

			std::string peek;
			if (!UI::ReadUiString("_root.SAQ_PeekGuide", peek)) {
				return;  // 桥没通 / SWF 旧版：静默跳过，不刷屏
			}
			if (peek == g_guide.lastPeek) {
				return;  // 没变化
			}
			g_guide.lastPeek = peek;

			const auto bar = peek.find('|');
			if (bar == std::string::npos) {
				return;
			}
			int seq = 0;
			unsigned long fid = 0;
			try {
				seq = std::stoi(peek.substr(0, bar));
				fid = std::stoul(peek.substr(bar + 1));
			} catch (...) {
				REX::WARN("引导请求：解析失败 {}", peek);
				return;
			}
			if (seq <= 0 || seq == g_guide.lastSeq) {
				return;
			}
			g_guide.lastSeq = seq;
			ApplyGuideRequest(static_cast<std::uint32_t>(fid));
		}

		// 菜单打开时的收尾：被引导的任务如果已经「被引擎开始」（玩家接到了），
		// 就自动取消引导 —— 免得 HUD 上还挂着一条已经没用的指引。
		void AutoClearGuideIfAccepted()
		{
			if (g_guide.questFormID == 0) {
				return;
			}
			auto* form = RE::TESForm::LookupByID(static_cast<RE::TESFormID>(g_guide.questFormID));
			if (!form) {
				return;
			}
			const auto state = ReadQuestRuntimeState(form);
			if (!state.vtableKnown || !IsAlreadyEngaged(state)) {
				return;
			}
			std::string detail;
			const auto* entry = FindStaticQuest(g_guide.questFormID);
			if (Guide::SetGuideTarget(0, detail)) {
				REX::INFO("引导自动取消：{}（0x{:08X}）已经被引擎开始（{}）｜{}",
					entry ? entry->nameZh : "?", g_guide.questFormID, Describe(state), detail);
			}
			g_guide.questFormID = 0;
			g_guide.guideRef = 0;
		}

		void OnMissionMenuClosed()
		{
			if (!g_poll.lastReport.empty()) {
				REX::INFO("菜单关闭：界面最后状态={}", g_poll.lastReport);
			} else {
				REX::INFO("菜单关闭：界面状态一条都没读回来（桥没通 / SWF 是旧版 / 一次都没轮询到）");
			}
			ResetReportPoll();

			// 引导请求的「变化检测」状态跟着菜单一起重置：菜单重开时 SWF 新建，
			// AS3 侧的序号从 0 重新开始（当前引导本身存在 GLOB 里，不受影响）。
			g_guide.lastPeek.clear();
			g_guide.lastSeq = -1;
			g_guide.lastPollMs = 0;
		}

		void OnMissionMenuOpened()
		{
			// ★ 菜单是「新开的」，上一轮解析出来的 Movie 指针多半已经随菜单关闭销毁了，
			//   必须重新解析一遍（Reset 后第一次推送会重新走「菜单表 → IMenu → Movie」）。
			UI::Reset();
			ResetReportPoll();

			g_pending.quests.clear();
			g_pending.attempts = 0;
			g_pending.total = 0;
			CollectAvailableQuests(g_pending.quests, g_pending.total, g_pending.stats);
			REX::INFO("{}", FormatRuntimeStats(g_pending.stats));
			REX::INFO("{}", FormatStaticFlagStats(g_pending.stats));
			// 语言这一项只是**日志参考**：实际显示语言由 AS3 侧按引擎推来的任务名判定。
			REX::INFO("菜单打开：静态表={} 引擎里存在={} 待推送={} INI语言={}(仅供参考) 标题=可接任务/Available(中英都推，由 UI 选)",
				g_pending.total, g_pending.stats.live, g_pending.quests.size(), GetGameLanguage());

			// 引导（第 10 轮）：ESM 通道自证 + 已接取任务的引导自动取消 + 当前引导状态
			LogEsmChannel();
			AutoClearGuideIfAccepted();
			LogGuideState();

			TryPushPending();
		}

		void Tick()
		{
			// 只看主线程（读档期间加载线程也会跑到这里）
			if (::GetCurrentThreadId() != g_mainThreadId.load()) {
				return;
			}
			auto* ui = RE::UI::GetSingleton();
			if (!ui) {
				return;
			}
			const bool open = ui->IsMenuOpen(MenuName());
			const bool wasOpen = g_menuWasOpen.exchange(open);
			if (open && !wasOpen) {
				OnMissionMenuOpened();
			} else if (open) {
				TryPushPending();   // 上一轮没成功的话接着重试
				PollUiReport();     // 界面状态「变化即记」
				PollGuideRequest(); // 玩家按了引导键就下发给 ESM 通道（第 10 轮）
			} else if (wasOpen) {
				OnMissionMenuClosed();
			}
		}
	}

	bool Install()
	{
		if (g_installed.exchange(true)) {
			return true;
		}

		g_mainThreadId.store(::GetCurrentThreadId());

		auto* task = SFSE::GetTaskInterface();
		if (!task) {
			REX::WARN("SFSE 任务接口不可用，稍后重试");
			g_installed.store(false);
			return false;
		}
		task->AddPermanentTask(Tick);

		REX::INFO("SAQ 已安装（等待 {} 打开；主线程 {}）", kMenuName, g_mainThreadId.load());
		return true;
	}
}
