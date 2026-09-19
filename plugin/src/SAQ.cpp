// ============================================================================
//  Starfield Show Available Quests - 核心逻辑（SAQ_ShowAvailableQuests.dll）
//
//  目标（见 AGENTS.md）：
//    在游戏原版任务菜单（BSMissionMenu）里新增一个 tab「可接任务」，
//    列出当前游戏进度下玩家还能接到的任务（非主线）。
//
//  数据流：
//    UI 打开 BSMissionMenu
//      -> 本文件收集可接任务（遍历 TESDataHandler 的 QUST 数组 + 运行时过滤）
//      -> 组装 GFxValue 数组
//      -> asMovieRoot->Invoke("SetAvailableQuests", ...) 推给 AS3 侧
//      -> AS3 侧并入任务列表，tab 过滤显示
//
//  几个「不要再踩」的坑（来自上一代项目 always scan 的实测）：
//    ① **绝不缓存 BSTArray 的 data()/capacity()**：清表可能释放/搬移缓冲，
//       缓存下来就是悬空指针。本文件每次现读。
//    ② **只看主线程**：读档期间加载线程也会跑到这里；加主线程判定。
//    ③ GFx 的 Value 在 `Invoke` 之后即可释放（AS 侧已拷贝），
//       但构造时依赖 root->CreateObject/CreateArray 设置的 objectInterface。
// ============================================================================

#include "PCH.h"

#include "SAQ.h"
#include "SAQ_QuestTable.h"  // 生成物：FormID -> 中/英文名 + 类型（tools/esm/gen_quest_table.py）

#include "RE/B/BGSStoryTeller.h"
#include "RE/B/BSFixedString.h"
#include "RE/B/BSTEvent.h"
#include "RE/F/FormTypes.h"
#include "RE/I/INISettingCollection.h"
#include "RE/S/Setting.h"
// 注意 include 顺序：ASMovieRootBase.h 不自包含（Value/Movie/FunctionHandler 都要先有），
// 顺序错了会报 C4430/C2061 一连串语法错误。
#include "RE/S/ScaleformGFxMovie.h"
#include "RE/S/ScaleformGFxValue.h"
#include "RE/S/ScaleformGFxFunctionHandler.h"
#include "RE/S/ScaleformGFxASMovieRootBase.h"
#include "RE/T/TESDataHandler.h"
#include "RE/T/TESForm.h"
#include "RE/U/UI.h"

#include <Windows.h>

#include <atomic>
#include <cstdint>
#include <memory>
#include <string>
#include <unordered_map>
#include <unordered_set>
#include <utility>
#include <vector>

namespace SAQ
{
	using namespace std::string_view_literals;

	namespace
	{
		constexpr const char* kMenuName = "BSMissionMenu";       // 原版任务菜单
		constexpr const char* kPushFunc = "SetAvailableQuests";  // AS3 侧接收函数（SAQ 新增）
		constexpr std::int32_t kAvailableQuestType = 6;          // QuestUtils.AVAILABLE_QUEST_TYPE

		struct QuestEntry
		{
			RE::TESFormID formID{};
			std::uint32_t faction{};
			std::int32_t  type = kAvailableQuestType;
			std::string   name;
		};

		std::atomic_bool g_installed{ false };
		std::atomic_bool g_firstMenuLogged{ false };
		std::atomic<std::uint64_t> g_pushCount{ 0 };
		std::atomic_uint32_t g_mainThreadId{ 0 };

		// ------------------------------------------------------------------
		// 本地化
		// 原版 tab 文本走 translate_<lang>.txt（UTF-16LE）的 $Key，MOD 不便覆盖
		// 整张表，所以由 C++ 读游戏语言后把成品文本推给 AS3。
		// ------------------------------------------------------------------

		std::string_view GetGameLanguage()
		{
			auto* ini = RE::INISettingCollection::GetSingleton();
			if (!ini) {
				return "en"sv;
			}
			return ini->GetSetting<std::string_view>("sLanguage:General"sv, "en"sv);
		}

		const char* GetTabText()
		{
			const auto lang = GetGameLanguage();
			if (lang.starts_with("zh")) {
				return "可接任务";
			}
			return "AVAILABLE";
		}

		// ------------------------------------------------------------------
		// 数据收集
		// ------------------------------------------------------------------

		std::unordered_set<RE::TESFormID> CollectRunningQuestIDs()
		{
			std::unordered_set<RE::TESFormID> out;
			auto* storyteller = RE::BGSStoryTeller::GetSingleton();
			if (!storyteller) {
				return out;
			}
			// 注意：TESQuest 在 commonlibsf 中只有前置声明，这里只取 FormID，
			// 指针地址与首基类 TESForm 相同（reinterpret_cast 是安全的）。
			for (auto* quest : storyteller->runningQuests) {
				if (quest) {
					out.insert(reinterpret_cast<RE::TESForm*>(quest)->GetFormID());
				}
			}
			for (auto* quest : storyteller->queuedStartQuests) {
				if (quest) {
					out.insert(reinterpret_cast<RE::TESForm*>(quest)->GetFormID());
				}
			}
			return out;
		}

		// FormID -> 静态信息 索引（只建一次）
		const std::unordered_map<RE::TESFormID, const StaticQuestInfo*>& QuestIndex()
		{
			static const std::unordered_map<RE::TESFormID, const StaticQuestInfo*> index = [] {
				std::unordered_map<RE::TESFormID, const StaticQuestInfo*> m;
				m.reserve(kQuestTableSize * 2);
				for (std::size_t i = 0; i < kQuestTableSize; ++i) {
					m.emplace(kQuestTable[i].formID, std::addressof(kQuestTable[i]));
				}
				return m;
			}();
			return index;
		}

		// 收集"可接任务"候选。
		//
		// 规则（MVP）：
		//   * 必须命中静态表 => 有 QTYP（玩家可见任务）且非主线
		//   * 不在运行中/排队启动（BGSStoryTeller）
		//   * 属于 Starfield.esm（load order 0；静态表只收录了它的记录）
		//   * 名称按游戏语言从静态表取
		//
		// "玩家已知任务"（进行中/已完成）由 AS3 侧用引擎推送的 QuestData 再过滤一次。
		void CollectAvailableQuests(std::vector<QuestEntry>& a_out, std::size_t& a_totalQuests)
		{
			a_totalQuests = 0;
			auto* dataHandler = RE::TESDataHandler::GetSingleton();
			if (!dataHandler) {
				REX::WARN("TESDataHandler 不可用");
				return;
			}

			const auto running = CollectRunningQuestIDs();
			const auto& index = QuestIndex();
			const bool zh = GetGameLanguage().starts_with("zh");

			// 每次现读，绝不缓存数组指针（见文件头说明）
			const auto& formArray = dataHandler->formArrays[std::to_underlying(RE::FormType::kQUST)].formArray;
			a_out.reserve(512);

			for (const auto& ptr : formArray) {
				auto* form = ptr.get();
				if (!form || form->IsDeleted()) {
					continue;
				}
				++a_totalQuests;
				const auto formID = form->GetFormID();
				if ((formID & 0xFF000000u) != 0) {
					continue;  // 非 Starfield.esm（静态表暂只覆盖 master）
				}
				if (running.contains(formID)) {
					continue;
				}
				const auto it = index.find(formID);
				if (it == index.end()) {
					continue;  // 不在表里 => 不是"玩家可见的非主线任务"
				}
				const auto* info = it->second;
				QuestEntry entry;
				entry.formID = formID;
				entry.type = kAvailableQuestType;  // 统一放到我们的 tab；原类型由前缀图标体现
				entry.faction = 0;
				entry.name = zh ? info->nameZh : info->nameEn;
				a_out.push_back(std::move(entry));
			}
		}

		// ------------------------------------------------------------------
		// UI 推送
		// ------------------------------------------------------------------

		bool PushToUI(const std::vector<QuestEntry>& a_quests)
		{
			auto* ui = RE::UI::GetSingleton();
			if (!ui) {
				return false;
			}
			auto movie = ui->GetMenuMovie(RE::BSFixedString{ kMenuName });
			if (!movie) {
				return false;
			}
			auto* root = movie->asMovieRoot.get();
			if (!root) {
				return false;
			}

			RE::Scaleform::GFx::Value args[2];
			root->CreateArray(&args[0]);
			if (!args[0].IsArray()) {
				REX::WARN("推送失败：CreateArray 未返回数组");
				return false;
			}
			// 字符串一律走 CreateString（UTF-8 -> AS3 UTF-16），
			// 直接用 Value(const char*) 只是裸指针，含中文时不保险。
			root->CreateString(&args[1], GetTabText());

			std::size_t pushed = 0;
			for (const auto& q : a_quests) {
				RE::Scaleform::GFx::Value obj;
				root->CreateObject(&obj);
				if (!obj.IsObject()) {
					continue;
				}
				obj.SetMember("uID"sv, RE::Scaleform::GFx::Value(static_cast<std::uint32_t>(q.formID)));
				obj.SetMember("uInstanceID"sv, RE::Scaleform::GFx::Value(static_cast<std::uint32_t>(0)));
				obj.SetMember("iType"sv, RE::Scaleform::GFx::Value(q.type));
				obj.SetMember("iFaction"sv, RE::Scaleform::GFx::Value(static_cast<std::uint32_t>(q.faction)));
				RE::Scaleform::GFx::Value nameVal;
				root->CreateString(&nameVal, q.name.c_str());
				obj.SetMember("sName"sv, nameVal);
				obj.SetMember("bActive"sv, RE::Scaleform::GFx::Value(false));
				obj.SetMember("bComplete"sv, RE::Scaleform::GFx::Value(false));
				obj.SetMember("bFailed"sv, RE::Scaleform::GFx::Value(false));
				obj.SetMember("bIsMiscQuest"sv, RE::Scaleform::GFx::Value(false));
				obj.SetMember("bIsMiscObjective"sv, RE::Scaleform::GFx::Value(false));
				obj.SetMember("bCanShowOnMap"sv, RE::Scaleform::GFx::Value(false));
				obj.SetMember("iRemainingTime"sv, RE::Scaleform::GFx::Value(static_cast<std::int32_t>(-1)));

				// MissionsListEntry.IsMission() 用 hasOwnProperty("aObjectives") 判定，
				// 所以必须给一个（此刻为空的）目标数组。
				RE::Scaleform::GFx::Value objectives;
				root->CreateArray(&objectives);
				obj.SetMember("aObjectives"sv, objectives);

				if (!args[0].PushBack(obj)) {
					continue;
				}
				++pushed;
			}

			RE::Scaleform::GFx::Value ret;
			const bool ok = root->Invoke(kPushFunc, &ret, args, 2);
			if (!ok) {
				REX::WARN("Invoke(\"{}\") 失败：AS3 侧可能还没有这个函数", kPushFunc);
			} else if (ret.IsNumber() || ret.IsInt() || ret.IsUInt()) {
				// AS3 侧返回它实际收到的条目数（-1 = null）——最直接的成功判据
				REX::DEBUG("AS3 侧确认收到 {} 条", static_cast<int>(ret.GetNumber()));
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

		void OnMissionMenuOpened()
		{
			std::vector<QuestEntry> quests;
			std::size_t total = 0;
			CollectAvailableQuests(quests, total);

			const bool pushed = PushToUI(quests);
			const auto n = ++g_pushCount;
			if (!g_firstMenuLogged.exchange(true)) {
				REX::INFO("首次菜单打开：quest 总数={} 可接候选={} 推送={} (第{}次)",
					total, quests.size(), pushed ? "成功" : "失败", n);
			} else {
				REX::DEBUG("菜单打开：quest 总数={} 可接候选={} 推送={} (第{}次)",
					total, quests.size(), pushed ? "成功" : "失败", n);
			}
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
