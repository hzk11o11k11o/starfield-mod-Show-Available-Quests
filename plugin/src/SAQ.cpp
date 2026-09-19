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
#include "SAQ_UI.h"          // UI 通道（菜单表 → IMenu → Movie → ASMovieRoot）
#include "SAQ_QuestTable.h"  // 生成物：FormID -> 中/英文名 + 类型（tools/esm/gen_quest_table.py）

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

		// 推送重试状态（只在主线程读写，不需要锁）。
		// 菜单刚打开的那一两帧 SWF 可能还没初始化完，Invoke 会失败 —— 隔几帧再试。
		struct PendingPush
		{
			std::vector<QuestEntry> quests;
			std::size_t             total{};
			std::size_t             live{};
			std::uint32_t           attempts{};
			std::uint64_t           lastAttemptMs{};
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

		// ★ 关于「已经开始的 quest 怎么排除」：
		//   上一版用 RE::BGSStoryTeller::GetSingleton() 读 runningQuests /
		//   queuedStartQuests，结果游戏里一开任务菜单就弹
		//   "Invalid ID: 0" 的框 —— commonlibsf 的
		//   RE::ID::BGSStoryTeller::Singleton 就是 0（见文件上方 ID 审计）。
		//
		//   现在这条线索整个砍掉，改由 AS3 侧用**引擎自己推给 UI 的 QuestData**
		//   过滤（MissionMenu.FilterKnownQuests）：玩家已经拿到的任务（进行中/
		//   已完成）必然在 QuestData 里，这比 C++ 侧猜更准。C++ 只负责
		//   「静态表里的可接候选」这一层。
		//
		//   （下一代产品：若哪天 commonlibsf 补上 BGSStoryTeller 的 ID，或我们自己
		//   挖到正确 ID，再考虑把「已开始但没进日志」的任务也滤掉。）

		// 收集"可接任务"候选。
		//
		// 规则（MVP）：
		//   * 必须命中静态表 => 有 QTYP（玩家可见任务）且非主线
		//   * 引擎里确实存在这个 FormID（★ 用 TESForm::LookupByID 问引擎，
		//     **不再用 TESDataHandler::formArrays** —— 1.16.244.0 上实测那里读到空表，
		//     结果"quest 总数=0"、列表当然是空的，见 docs/02）
		//   * 名称按游戏语言从静态表取
		//
		// "玩家已知任务"（进行中/已完成）由 AS3 侧用引擎推送的 QuestData 再过滤一次。
		void CollectAvailableQuests(std::vector<QuestEntry>& a_out, std::size_t& a_totalQuests, std::size_t& a_liveQuests)
		{
			a_out.reserve(kQuestTableSize);
			a_totalQuests = kQuestTableSize;
			a_liveQuests = 0;

			for (std::size_t i = 0; i < kQuestTableSize; ++i) {
				const auto& info = kQuestTable[i];
				if (!RE::TESForm::LookupByID(static_cast<RE::TESFormID>(info.formID))) {
					continue;  // 这个 FormID 在当前加载顺序里不存在（理论上 Starfield.esm 必有）
				}
				++a_liveQuests;
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
					g_pending.total, g_pending.live, g_pending.quests.size(), n);
				g_pending.quests.clear();
				g_pending.attempts = kMaxPushAttempts;  // 本次不再重试
			} else if (g_pending.attempts >= kMaxPushAttempts) {
				REX::WARN("推送放弃：重试 {} 次仍未成功（下次打开菜单会再试）", g_pending.attempts);
				g_pending.quests.clear();
			}
		}

		void OnMissionMenuOpened()
		{
			// ★ 菜单是「新开的」，上一轮解析出来的 Movie 指针多半已经随菜单关闭销毁了，
			//   必须重新解析一遍（Reset 后第一次推送会重新走「菜单表 → IMenu → Movie」）。
			UI::Reset();

			g_pending.quests.clear();
			g_pending.attempts = 0;
			g_pending.total = 0;
			g_pending.live = 0;
			CollectAvailableQuests(g_pending.quests, g_pending.total, g_pending.live);
			// 语言这一项只是**日志参考**：实际显示语言由 AS3 侧按引擎推来的任务名判定。
			REX::INFO("菜单打开：静态表={} 引擎里存在={} 待推送={} INI语言={}(仅供参考) 标题=可接任务/Available(中英都推，由 UI 选)",
				g_pending.total, g_pending.live, g_pending.quests.size(), GetGameLanguage());
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
				TryPushPending();  // 上一轮没成功的话接着重试
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
