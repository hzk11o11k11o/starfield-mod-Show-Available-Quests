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
		//
		// ★ 第 16 轮：把「等待菜单就绪」和「推送失败」拆成两套计数。实测每次开菜单
		//   第 1 次推送都命中「UI 表里还没有 BSMissionMenu 条目」（菜单正在创建，0ms 就返回），
		//   原来固定 400ms 退避 + 计入 attempts，会让列表从内嵌数据切成 C++ 数据拖到 ~0.8 秒，
		//   而且日志每次都先来一条「推送失败（完整诊断）」。
		struct PendingPush
		{
			std::vector<QuestEntry> quests;
			std::size_t             total{};
			std::uint32_t           attempts{};        // 正式推送尝试（预算 14 次，指数退避）
			std::uint32_t           menuWaitTries{};   // 「菜单还没就绪」的等待次数（预算 24 次，150ms 短退避）
			bool                    done{};            // 本次菜单打开已处理完（成功/放弃）
			std::uint64_t           lastAttemptMs{};
			// ★ 第 11 轮：失败退避间隔（400 → 800 → 1600 → …封顶 4000）。
			//   实测「菜单打开后 40 秒才就绪」的场景（日志：重试间隔 15 秒 × 2 次），
			//   固定 400ms 会把 10 次机会在 4 秒内烧完；退避后覆盖 ~40 秒。
			std::uint64_t           backoffMs{ 400 };
			RuntimeFilterStats      stats;
		};
		PendingPush g_pending;
		constexpr std::uint32_t kMaxPushAttempts = 14;
		constexpr std::uint64_t kPushRetryIntervalMs = 400;
		constexpr std::uint64_t kPushRetryMaxMs = 4000;
		// 「菜单还没就绪」的短退避与等待预算（24 × 150ms ≈ 3.6 秒）
		constexpr std::uint64_t kMenuNotReadyRetryMs = 150;
		constexpr std::uint32_t kMaxMenuWaitTries = 24;

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
			// 第 11 轮：从 5 提到 40 —— 「某条任务为什么不在列表里」要能直接从日志里
			// 查到答案（被隐藏的通常 30 条上下，全列出来 ~1.5KB / 次打开菜单，可接受）。
			constexpr std::size_t kMaxSamples = 40;
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

				// ★ 第 11 轮修正（实测驱动）：**只挡「已完成」**，不再挡「已开始」。
				//
				//   证据：玩家在 GalBank 里报告「和 NPC 对话就能接到『全数到期』，但列表里没有」。
				//   完整隐藏名单日志（第 11 轮）证明它被这里挡掉了，状态是 `运行中 flags=0x8001`
				//   （TESQuest bit0=已开始）—— 但玩家任务日志（AS3 的 qdata=）里根本没有它：
				//     • 全数到期 = RAD05，**可重复接取**的辐射任务（GalBank 的 Landry Hollifeld 给）；
				//     • 引擎把这类任务提前置成 running（对话链/事件准备），并不代表玩家已接。
				//   当时的 30 条「隐藏」里只有 3 条在玩家日志里（玩家真正接了的），其余 27 条
				//   全是这种「引擎自启、玩家没接」的 —— 「已开始」不能当「已接取」用。
				//
				//   分工修正：**「已接取」的判据只认玩家任务日志**（AS3 侧的 FilterKnownQuests，
				//   用引擎推来的 QuestData 逐个比 uID）—— 那是显示层的权威数据。C++ 这层只挡
				//   「已完成」：做过的任务不该再出现在「可接」里（可重复任务除外，见下一步计划）。
				if (state.completed && state.vtableKnown) {
					++hiddenByRuntime;
					if (sampleCount < kMaxSamples) {
						++sampleCount;
						// FormID 必须带上：名字可能与玩家的叫法不一致（玩家反馈「某条没显示」
						// 时，靠 FormID 精确核对，而不是靠名字猜）。
						a_stats.samples += std::format("{}[0x{:08X} {}] ", info.nameZh, info.formID, Describe(state));
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

		// ------------------------------------------------------------------
		// UI 推送
		// ------------------------------------------------------------------

		// ★ 第 16 轮：区分「菜单还没建好」和「真推送失败」（两者日志与重试策略都不同）。
		// 判据是 UI 桥失败详情里的那句话（SAQ_UI.cpp::ResolveMapAndMenu 里唯一会这么写的地方）。
		constexpr std::string_view kMenuNotReadyMark = "UI 里没找到 BSMissionMenu 的菜单表条目";

		// 返回 true = 推送成功。a_menuNotReady = 失败原因是「菜单表条目还没出现」（预期现象）。
		bool PushToUI(const std::vector<QuestEntry>& a_quests, bool a_verbose, bool& a_menuNotReady)
		{
			std::string detail;
			const auto t0 = NowMs();
			const bool ok = UI::PushAvailableQuests(a_quests, detail);
			const auto cost = NowMs() - t0;
			a_menuNotReady = !ok && detail.find(kMenuNotReadyMark) != std::string::npos;
			// ★ 第 11 轮：耗时进日志。玩家报「打开任务菜单假死很久」——这一行能直接区分
			//   「我们这层慢」还是「主线程被别的东西占着」（后者见 Tick 里的停顿检测）。
			if (ok) {
				REX::INFO("推送成功：{} | {} 条 | 耗时 {} ms", detail, a_quests.size(), cost);
			} else if (a_menuNotReady) {
				// 菜单打开后头几百毫秒的**预期**状态（SWF 的菜单表条目还没挂上）——
				// 不是故障，不打完整诊断（那些指针细节只会淹日志）。
				REX::INFO("菜单尚未就绪（UI 表里还没有 BSMissionMenu 条目），稍后重试 | 耗时 {} ms", cost);
			} else if (a_verbose) {
				REX::WARN("推送失败（第 1 次，完整诊断）：{} | 耗时 {} ms", detail, cost);
			} else {
				// 重试时的失败只记前 240 字符：一次失败的完整诊断能带 30 个指针的 RTTI，
				// 重试几次就把日志淹了（定位卡顿时反而看不清）。
				REX::WARN("推送失败（重试）：{}… | 耗时 {} ms", detail.substr(0, 240), cost);
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
				// 完整名单（第 11 轮起不再只记前几条）：玩家反馈「某条任务没显示」时，
				// 先在 `隐藏:` 这一段里搜 FormID —— 在 = 被运行时状态挡住（看它后面括号里的状态）；
				// 不在 = 它已经被推送给 UI（详见 AS3 侧的 `qdata=` 名单）。
				out += " 隐藏: " + a_stats.samples;
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

		// 定义在下面「引导」一节；这里前向声明（推送成功后要把当前引导同步给界面）。
		void SyncGuideStateToUi();

		// 尝试把待推送的数据送进 SWF。
		//
		// ★ 第 16 轮：两种失败分开对待 ——
		//   ① 「菜单还没建好」（UI 表里没有 BSMissionMenu）：**预期现象**，用 150ms 短退避
		//      快速重试、不消耗正式重试预算。实测每次开菜单都要等 0.3~0.5 秒菜单才就绪；
		//      原来固定 400ms 退避会把「列表从内嵌数据切成 C++ 数据」拖到 ~0.8 秒
		//      （窗口期内玩家看到的是内嵌回退数据，里面还带着本该被运行时过滤的条目）。
		//   ② 真正的推送失败：指数退避（400 → 800 → …封顶 4000ms），预算 14 次。
		void TryPushPending()
		{
			if (g_pending.done || g_pending.quests.empty()) {
				return;
			}
			const auto now = NowMs();
			if (g_pending.lastAttemptMs != 0 && now - g_pending.lastAttemptMs < g_pending.backoffMs) {
				return;
			}
			g_pending.lastAttemptMs = now;

			// 第一次打开菜单时做一次性 UI 桥解析日志（只打一次，不刷屏）
			if (!g_firstMenuLogged.exchange(true)) {
				std::string bridgeDetail;
				const auto t0 = NowMs();
				if (UI::EnsureResolved(bridgeDetail)) {
					REX::INFO("UI 桥解析：{}", bridgeDetail);
				} else {
					REX::WARN("UI 桥解析失败（耗时 {} ms）：{}", NowMs() - t0, bridgeDetail);
				}
			}

			bool menuNotReady = false;
			if (PushToUI(g_pending.quests, g_pending.attempts == 0 && g_pending.menuWaitTries == 0, menuNotReady)) {
				const auto n = ++g_pushCount;
				REX::INFO("菜单打开：静态表={} 引擎里存在={} 推送条数={} (第 {} 次推送成功，另有 {} 次菜单未就绪等待)",
					g_pending.total, g_pending.stats.live, g_pending.quests.size(),
					g_pending.attempts + 1, g_pending.menuWaitTries);
				g_pending.quests.clear();
				g_pending.done = true;
				SyncGuideStateToUi();  // ★ 第 16 轮：新 SWF 实例不知道引导还在，把实际值同步过去
				return;
			}
			if (menuNotReady) {
				// 菜单还在创建：短退避快速重试（不计入正式重试预算）
				++g_pending.menuWaitTries;
				g_pending.backoffMs = kMenuNotReadyRetryMs;
				if (g_pending.menuWaitTries >= kMaxMenuWaitTries) {
					REX::WARN("菜单就绪等待超时：{} 次 × {} ms 仍未就绪（本次放弃，下次打开菜单再试）",
						g_pending.menuWaitTries, kMenuNotReadyRetryMs);
					g_pending.quests.clear();
					g_pending.done = true;
				}
				return;
			}
			// 真失败 ⇒ 退避加倍（封顶 kPushRetryMaxMs）：菜单加载慢时别把机会烧光。
			++g_pending.attempts;
			const auto doubled = g_pending.backoffMs * 2;
			g_pending.backoffMs = doubled < kPushRetryMaxMs ? doubled : kPushRetryMaxMs;
			if (g_pending.attempts >= kMaxPushAttempts) {
				REX::WARN("推送放弃：重试 {} 次仍未成功（下次打开菜单会再试）", g_pending.attempts);
				g_pending.quests.clear();
				g_pending.done = true;
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

		// ★ 第 16 轮：把引导结果回写给界面（`_root.SAQ_GuideReply`，协议见 MissionMenu.as）。
		//
		// 为什么必须回写：界面只能「本地立刻切状态」（音效/竖条/文案），但一条任务
		// 到底有没有引导目标只有这边知道。不回写时，玩家点到没有引导目标的任务
		// （202 条里 34 条）会看到界面说「已设为引导」，实际什么都没发生 —— 而且
		// 旧引导如果还在，游戏里指的仍是旧任务。
		void NotifyGuideReply(int a_seq, std::uint32_t a_actual, int a_code)
		{
			std::string reply;
			if (!UI::NotifyGuideReply(a_seq, a_actual, a_code, reply)) {
				REX::WARN("引导结果回写界面失败：{}（界面状态可能滞后；下次开菜单会自动同步）", reply);
				return;
			}
			REX::INFO("引导结果已回写界面：seq={} 实际=0x{:08X} 结果码={} 应答={}",
				a_seq, a_actual, a_code, reply.empty() ? std::string{ "?" } : reply);
		}

		// ★ 第 16 轮：菜单打开、列表推送成功后，把「实际引导任务」同步给界面。
		// （菜单每次打开都是新 SWF 实例、界面的 SaqGuideQuest 归 0——不同步会丢竖条、
		//   点「正在引导的那条」第一次会变成重设而不是取消。）
		void SyncGuideStateToUi()
		{
			if (g_guide.questFormID == 0) {
				return;  // 没有引导：界面本来就是 0，不用同步
			}
			std::string reply;
			if (!UI::SyncGuideState(g_guide.questFormID, reply)) {
				REX::WARN("引导状态同步界面失败：{}（竖条/取消语义可能滞后）", reply);
				return;
			}
			REX::INFO("引导状态已同步界面：当前=0x{:08X} 应答={}", g_guide.questFormID,
				reply.empty() ? std::string{ "?" } : reply);
		}

		// 应用一次引导请求，并把结果回写给界面。a_formID = 0 表示取消引导。
		// 结果码（与 AS3 的约定）：0=成功 / 1=没有引导目标 / 2=写通道失败 / 3=静态表里没有
		void ApplyGuideRequest(std::uint32_t a_formID, int a_seq)
		{
			if (a_formID == 0) {
				std::string detail;
				if (Guide::SetGuideTarget(0, detail)) {
					REX::INFO("引导请求：取消｜{}", detail);
					g_guide.questFormID = 0;
					g_guide.guideRef = 0;
					NotifyGuideReply(a_seq, 0, 0);
				} else {
					REX::WARN("引导请求：取消失败｜{}", detail);
					g_guide.questFormID = 0;
					g_guide.guideRef = 0;
					NotifyGuideReply(a_seq, 0, 2);
				}
				return;
			}
			const auto* entry = FindStaticQuest(a_formID);
			if (!entry) {
				REX::WARN("引导请求：静态表里没有 0x{:08X}（是内嵌回退表里的条目？）", a_formID);
				NotifyGuideReply(a_seq, g_guide.questFormID, 3);
				return;
			}
			if (entry->guideRef == 0) {
				REX::WARN("引导请求：{}（0x{:08X}）没有引导目标（离线没算出「去哪里接」的引用，见 docs/05）",
					entry->nameZh, a_formID);
				NotifyGuideReply(a_seq, g_guide.questFormID, 1);
				return;
			}
			std::string detail;
			if (!Guide::SetGuideTarget(entry->guideRef, detail)) {
				REX::WARN("引导请求：{}（0x{:08X}）写 ESM 通道失败｜{}", entry->nameZh, a_formID, detail);
				NotifyGuideReply(a_seq, g_guide.questFormID, 2);
				return;
			}
			g_guide.questFormID = a_formID;
			g_guide.guideRef = entry->guideRef;
			REX::INFO("引导请求：{}（0x{:08X}）→ 引用 0x{:08X}（{}）｜{}",
				entry->nameZh, a_formID, entry->guideRef, entry->whereZh, detail);
			NotifyGuideReply(a_seq, a_formID, 0);
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
			ApplyGuideRequest(static_cast<std::uint32_t>(fid), seq);
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
			// ★ 第 11 轮修正：原来用 IsAlreadyEngaged（已开始 **或** 已完成）——「已开始」
			//   会误伤 RAD05「全数到期」这类「引擎自启、玩家还没接」的任务：引导刚设上，
			//   下次菜单一开就被这里自动取消。只有「已完成」是明确的「不再需要引导」。
			if (!state.vtableKnown || !state.completed) {
				return;
			}
			std::string detail;
			const auto* entry = FindStaticQuest(g_guide.questFormID);
			if (Guide::SetGuideTarget(0, detail)) {
				REX::INFO("引导自动取消：{}（0x{:08X}）已完成（{}）｜{}",
					entry ? entry->nameZh : "?", g_guide.questFormID, Describe(state), detail);
			}
			g_guide.questFormID = 0;
			g_guide.guideRef = 0;
		}

		// ★ 第 16 轮：引导「静默失效」的自愈。
		//
		// 两种场景（都实测/推断过）：
		//   ① 脚本重挂：读档会让 SAQ_Main 重新 OnInit（Papyrus 日志实测一次会话 3 次），
		//      别名被清空、脚本把 GuideState 写成 3（已清除）—— 而这边还认为在引导，
		//      游戏里的蓝点却没了（UI 上也仍显示引导中）。
		//   ② 引用当时没加载：引导目标是非常驻引用、格子没加载时脚本报 2（取不到），
		//      之后玩家飞近了、引用加载了，但脚本不会自己重试。
		// 两种情况都靠「把通道重写一遍（GuideState 清 0）」让脚本重新应用一次。
		// 状态 4（别名不存在）不重发 —— ESM 补丁没生效，重写也没用。
		void ReissueGuideIfScriptLost()
		{
			if (g_guide.questFormID == 0) {
				return;  // 没在引导
			}
			const auto ch = Guide::EnsureChannel();
			if (!ch.resolved) {
				return;  // 通道没认领（ESM 没加载等）—— LogEsmChannel 已经记过原因
			}
			if (ch.guideState != 2.0f && ch.guideState != 3.0f) {
				return;  // 0=待处理（脚本会自己应用）/ 1=已应用（正常）
			}
			std::string detail;
			const auto* entry = FindStaticQuest(g_guide.questFormID);
			if (!Guide::SetGuideTarget(g_guide.guideRef, detail)) {
				REX::WARN("引导重新下发失败：{}（0x{:08X}）｜{}",
					entry ? entry->nameZh : "?", g_guide.questFormID, detail);
				return;
			}
			REX::INFO("引导重新下发：{}（0x{:08X}）脚本状态={:.0f}"
					  "（2=引用当时没加载 / 3=脚本重挂丢了别名），已清 0 让脚本再试｜{}",
				entry ? entry->nameZh : "?", g_guide.questFormID, ch.guideState, detail);
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
			g_pending.menuWaitTries = 0;
			g_pending.done = false;
			g_pending.lastAttemptMs = 0;
			g_pending.total = 0;
			g_pending.backoffMs = kPushRetryIntervalMs;  // 新一轮重试：退避复位
			const auto t0 = NowMs();
			CollectAvailableQuests(g_pending.quests, g_pending.total, g_pending.stats);
			const auto collectCost = NowMs() - t0;
			REX::INFO("{}", FormatRuntimeStats(g_pending.stats));
			REX::INFO("{}", FormatStaticFlagStats(g_pending.stats));
			// 语言这一项只是**日志参考**：实际显示语言由 AS3 侧按引擎推来的任务名判定。
			// 收集耗时进日志（第 11 轮）：正常应为毫秒级；若出现几百 ms，就是查询本身有问题。
			REX::INFO("菜单打开：静态表={} 引擎里存在={} 待推送={} 收集耗时={} ms INI语言={}(仅供参考) 标题=可接任务/Available(中英都推，由 UI 选)",
				g_pending.total, g_pending.stats.live, g_pending.quests.size(), collectCost, GetGameLanguage());

			// 引导（第 10 轮）：ESM 通道自证 + 已接取任务的引导自动取消 + 当前引导状态
			LogEsmChannel();
			AutoClearGuideIfAccepted();
			ReissueGuideIfScriptLost();  // ★ 第 16 轮：脚本重挂 / 引用没加载 → 重发一次
			LogGuideState();

			TryPushPending();
		}

		// Tick 停顿检测（第 11 轮）：只在菜单开着时统计（读档/加载时的长停顿不记，免得刷屏）。
		// 正常帧间隔 ~16ms；若日志里出现「主线程停顿：距上次 Tick 15000 ms」，
		// 说明阻塞发生在**我们之外**（引擎/Scaleform/其它插件），我们的重试只是被拖慢的受害者。
		std::uint64_t s_tickWatermark = 0;
		constexpr std::uint64_t kTickStallMs = 1000;

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

			// 停顿检测：菜单开着时，两次 Tick 的间隔超过 1 秒就记一行（含被卡了多久）。
			if (open) {
				const auto now = NowMs();
				if (s_tickWatermark != 0 && now - s_tickWatermark >= kTickStallMs) {
					REX::WARN("主线程停顿：距上次 Tick {} ms（菜单开着；本行由 SAQ 记录，但停顿多半来自引擎/其它插件）",
						now - s_tickWatermark);
				}
				s_tickWatermark = now;
			} else {
				s_tickWatermark = 0;
			}

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
