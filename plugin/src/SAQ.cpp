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
//    ④ ★ **不要读 TESDataHandler 的任何成员**：formArrays 读到空表（第 5 轮，见 docs/02）、
//       files 读到空链表（第 17 轮，四个 master 全被误判「未加载」，见 docs/99 第 18 轮）——
//       它的结构体偏移在本机游戏版本上整体不可信。改用 TESForm::LookupByID 按 FormID 问引擎；
//       master 序号走「前缀探测」（SAQ_Masters.h）。
// ============================================================================

#include "PCH.h"

#include "SAQ.h"
#include "SAQ_Guide.h"       // 引导通道（DLL ↔ ESM 的 GLOB ↔ SAQ_Main.psc）
#include "SAQ_Masters.h"     // 「插件名 + 记录号」→ 运行期 FormID（DLC / 多 master）
#include "SAQ_QuestState.h"  // TESQuest 运行时状态（已开始/已完成/追踪中）
#include "SAQ_UI.h"          // UI 通道（菜单表 → IMenu → Movie → ASMovieRoot）
#include "SAQ_QuestTable.h"  // 生成物：master + 记录号 -> 中/英文名 + 类型 + 引导目标（tools/esm/gen_quest_table.py）

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
#include <cstring>
#include <filesystem>
#include <format>
#include <fstream>
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
			std::size_t testFiltered{};       // ★ 第 20 轮：被控制台测试模式（SAQ_TestMode）过滤掉的
			std::size_t skippedMaster{};      // 所属 master 没加载（DLC 没装/没启用）而跳过的
			bool        filterApplied{};      // 这次到底有没有按运行时状态过滤
			std::string samples;              // 被剔掉的前几条（名字 + 状态）
			std::string vtableSamples;        // 未识别虚表的样本（诊断）
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
			bool                    emptiedLogged{};   // ★ 第 18 轮：「本轮没有可推送条目」的日志只打一次
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
		// 静态表里「这一版加载顺序下确实存在」的行（master 已解析 + 引擎里查得到表单）。
		// ★ 第 17 轮：表的 FormID 是「master + 记录号」，运行期要在每次打开菜单时按当前
		//   加载顺序重新解析 —— 没装/没启用 DLC 的条目在这里就被丢掉（不会显示、也不会报错）。
		struct RuntimeRow
		{
			std::uint32_t          formID{};   // 运行期 FormID
			const RE::TESForm*     form{};     // 引擎里的表单（上面这个 ID 查到的）
			const StaticQuestInfo* info{};
		};
		std::vector<RuntimeRow> g_runtimeRows;

		// 解析 master + 建运行期行表。菜单打开时调用（读档换了加载顺序也能跟上）。
		std::string BuildRuntimeRows(RuntimeFilterStats& a_stats)
		{
			Masters::Refresh();
			const auto masters = Masters::Describe();

			g_runtimeRows.clear();
			g_runtimeRows.reserve(kQuestTableSize);
			a_stats.skippedMaster = 0;

			for (std::size_t i = 0; i < kQuestTableSize; ++i) {
				const auto& info = kQuestTable[i];
				const auto id = Masters::MakeFormID(info.master, info.localFormID);
				if (id == 0) {
					++a_stats.skippedMaster;  // 所属 master 没加载 / 档位不支持
					continue;
				}
				auto* form = RE::TESForm::LookupByID(static_cast<RE::TESFormID>(id));
				if (!form) {
					// master 加载了但查不到这条记录：不正常（多半是序号算错或记录被别的插件删了），
					// 记进 skippedMaster 并在日志里和抽样自校验一起看。
					++a_stats.skippedMaster;
					continue;
				}
				g_runtimeRows.push_back(RuntimeRow{ id, form, &info });
			}
			return masters;
		}

		// ------------------------------------------------------------------
		// ★ 第 20 轮：控制台测试过滤（GLOB SAQ_TestMode）
		//
		// 目的：261 条候选里想验证某一件事（引导/回滚/DLC）时，在列表里滚动找条目
		// 太费劲。玩家在游戏控制台输入 `set SAQ_TestMode to N`，DLL 每次开菜单读一次：
		//
		//   N=0（默认）不过滤（想恢复时 set 回 0）
		//   N=1 只显示「有引导目标」的（点了能出蓝点，验证引导链路）
		//   N=2 只显示「没有引导目标」的（验证界面回滚 / 结果码 1）
		//   N=3 只显示 DLC 条目（验证 DLC 支持）
		//   N=4 只显示「有引导目标 + 有具名地点」的（最少最好找）
		//
		// 只影响「显示哪些」—— 与既有过滤（已完成 / master 未加载 / 玩家日志）是
		// 「与」的关系，不改变任何既有判定。GLOB 不存在（旧 ESM）⇒ 模式 0。
		// ------------------------------------------------------------------
		bool PassesTestFilter(const StaticQuestInfo& a_info, int a_mode)
		{
			switch (a_mode) {
			case 1:
				return a_info.guideRefLocal != 0;
			case 2:
				return a_info.guideRefLocal == 0;
			case 3:
				return a_info.master != 0;
			case 4:
				return a_info.guideRefLocal != 0 && a_info.whereZh != nullptr && a_info.whereZh[0] != '\0';
			default:
				return true;  // 0 / 未知值 = 不过滤
			}
		}

		std::string_view TestModeNote(int a_mode)
		{
			switch (a_mode) {
			case 1: return "只显示「有引导目标」的条目";
			case 2: return "只显示「没有引导目标」的条目（测界面回滚）";
			case 3: return "只显示 DLC 条目";
			case 4: return "只显示「有引导目标 + 有具名地点」的条目";
			default: return "关闭（显示全部）";
			}
		}

		// ★ 第 20 轮补丁（实机反馈）：`set SAQ_TestMode to 4` 在控制台里报
		//   `Unknown variable`（ESM 明明加载了 —— 通道摘要里能看到 `测试=0`），
		//   说明这台机器的控制台 **不按 EDID 解析 mod 的 GLOB**。
		//   于是补一条**不依赖控制台**的通路：读 ini 文件（每次开菜单读一次，
		//   改完文件关开菜单即可生效，不用重启游戏；文件不存在时首次运行自动写一份模板）。
		//
		//   路径（★ 第 22 轮改）：**插件目录内的 SAQ_ShowAvailableQuests.ini**
		//   （MO2 下就是 mod 目录里的 SFSE\Plugins\）——玩家要求配置文件不落 C 盘
		//   用户目录，删 mod 时一起删掉。
		//   内容：[Test] / Mode=N（N 与 GLOB 同一套取值，见 PassesTestFilter）
		//
		//   优先级：**GLOB（控制台）非 0 时优先**；否则用 ini；都是 0 = 不过滤。
		std::wstring TestModeIniPath()
		{
			if (const auto dir = PluginDir(); !dir.empty()) {
				return (dir / L"SAQ_ShowAvailableQuests.ini").wstring();
			}
			return {};
		}

		// 首次运行写一份带说明的模板（已存在就不动 —— 玩家的设置不能被覆盖）。
		void EnsureTestModeIniTemplate()
		{
			const auto path = TestModeIniPath();
			if (path.empty() || ::GetFileAttributesW(path.c_str()) != INVALID_FILE_ATTRIBUTES) {
				return;
			}
			const char* tmpl =
				"; Show Available Quests - 测试过滤开关\r\n"
				"; 改完保存，然后关闭并重新打开一次任务菜单即可生效（不用重启游戏）。\r\n"
				"; Mode 取值：\r\n"
				";   0 = 关闭（默认，显示全部可接任务）\r\n"
				";   1 = 只显示「有引导目标」的任务（209 条，点了能出蓝点）\r\n"
				";   2 = 只显示「没有引导目标」的任务（52 条，测界面回滚）\r\n"
				";   3 = 只显示 DLC 任务（59 条）\r\n"
				";   4 = 只显示「有引导目标 + 有具名地点」的任务（85 条，最少最好找）\r\n"
				"; 控制台（如果你的游戏认 `set SAQ_TestMode to N`）非 0 时优先于本文件。\r\n"
				"[Test]\r\n"
				"Mode=0\r\n";
			std::ofstream f{ path.c_str(), std::ios::binary };
			if (!f) {
				REX::WARN("测试开关 ini 写不进去（忽略；不影响其它功能）");
				return;
			}
			f.write("\xEF\xBB\xBF", 3);  // BOM：记事本识别中文注释
			f.write(tmpl, static_cast<std::streamsize>(std::strlen(tmpl)));
			REX::INFO("已生成测试开关 ini 模板（插件目录内的 SAQ_ShowAvailableQuests.ini）");
		}

		// 最终模式 = 控制台（GLOB，非 0 优先）否则 ini。a_globMode < 0 = ESM 旧版没有 GLOB。
		struct TestModeResolved
		{
			int         mode{};
			const char* source{ "默认" };
		};

		TestModeResolved ResolveTestMode(float a_globMode)
		{
			if (a_globMode >= 0.5f) {
				return { static_cast<int>(a_globMode + 0.5f), "控制台" };
			}
			const auto path = TestModeIniPath();
			if (!path.empty()) {
				const int v = static_cast<int>(::GetPrivateProfileIntW(L"Test", L"Mode", 0, path.c_str()));
				if (v > 0) {
					return { v > 4 ? 0 : v, "ini" };  // 未知值按 0（不过滤）处理
				}
			}
			return { 0, "默认" };
		}

		// 收集"可接任务"候选 + 按运行时状态过滤。
		//
		// 规则：
		//   * 必须命中静态表 => 有 QTYP（玩家可见任务）且非主线
		//   * 所属 master 必须在当前加载顺序里（DLC 没装 ⇒ 静默跳过）
		//   * 引擎里确实存在这个 FormID（★ 用 TESForm::LookupByID 问引擎，
		//     **不再用 TESDataHandler::formArrays** —— 1.16.244.0 上实测那里读到空表，
		//     结果"quest 总数=0"、列表当然是空的，见 docs/02）
		//   * 引擎**已完成**的 → 剔掉（统计照原样写进日志）
		//   * 名称中英都带上，AS3 侧按游戏语言挑
		void CollectAvailableQuests(std::vector<QuestEntry>& a_out, std::size_t& a_totalQuests,
			RuntimeFilterStats& a_stats, int a_testMode)
		{
			// ★ 第 18 轮：这里原来是无条件 `a_stats = {}`，把 BuildRuntimeRows 刚写进去的
			//   `skippedMaster`（master 未加载而跳过的条数）清零了 —— 第 17 轮实测日志里
			//   因此出现自相矛盾的一行：「引擎存在=0 … 跳过(master未加载)=0」。
			//   现在只清本函数自己要写的字段，保留上游统计。
			const auto skippedByMaster = a_stats.skippedMaster;
			a_stats = {};
			a_stats.skippedMaster = skippedByMaster;
			a_totalQuests = kQuestTableSize;
			a_out.reserve(g_runtimeRows.size());

			std::size_t hiddenByRuntime = 0;
			// 第 11 轮：从 5 提到 40 —— 「某条任务为什么不在列表里」要能直接从日志里
			// 查到答案（被隐藏的通常 30 条上下，全列出来 ~1.5KB / 次打开菜单，可接受）。
			constexpr std::size_t kMaxSamples = 40;
			std::size_t sampleCount = 0;

			for (const auto& row : g_runtimeRows) {
				const auto* form = row.form;
				const auto& info = *row.info;
				++a_stats.live;

				const auto state = ReadQuestRuntimeState(form);
				if (state.vtableKnown) {
					++a_stats.recognized;
				} else {
					++a_stats.unrecognized;
					if (a_stats.vtableSamples.size() < 400) {
						a_stats.vtableSamples += std::format("{}[vt={:#x} {}] ", info.nameEn, state.vtable, Describe(state));
					}
				}
				if (state.started) {
					++a_stats.started;
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
						a_stats.samples += std::format("{}[0x{:08X} {}] ", info.nameZh, row.formID, Describe(state));
					}
					continue;
				}

				// ★ 第 20 轮：控制台测试过滤（`set SAQ_TestMode to N`，见 PassesTestFilter）。
				//   只影响显示，与上面的运行时过滤是「与」的关系。
				if (!PassesTestFilter(info, a_testMode)) {
					++a_stats.testFiltered;
					continue;
				}

				QuestEntry entry;
				entry.formID = row.formID;
				entry.type = kAvailableQuestType;  // 统一放到我们的 tab
				entry.nameZh = info.nameZh;        // 中英都带上，AS3 侧按游戏语言挑
				entry.nameEn = info.nameEn;
				a_out.push_back(std::move(entry));
			}

			// 安全阀：虚表识别率太低 ⇒ 说明「0x114 这套判据在这台机器/这个版本上不成立」，
			// 那就**不过滤**（只把证据写进日志），免得凭错误的对象把整个列表清空。
			const auto recognizedPct = a_stats.live == 0 ? 100u : static_cast<unsigned>(a_stats.recognized * 100 / a_stats.live);
			a_stats.filterApplied = recognizedPct >= 80;
			a_stats.hidden = a_stats.filterApplied ? hiddenByRuntime : 0;
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
				"运行时状态：引擎存在={} 虚表识别={} 未识别={} 已开始={} 已完成={} 追踪中={} 隐藏={} 测试过滤={} 跳过(master未加载)={} 过滤={}",
				a_stats.live, a_stats.recognized, a_stats.unrecognized,
				a_stats.started, a_stats.completed, a_stats.tracked, a_stats.hidden,
				a_stats.testFiltered,
				a_stats.skippedMaster,
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

		// （第 17 轮删掉了「DNAM 位分布」那行诊断日志：它要回答的问题在 xEdit 的
		//   flag 名里已经有答案（位0 = Start Game Enabled），而这一位**不是**可用的
		//   「进度没到」判据（见 docs/99 第 10 轮），每次开菜单白刷一行。）

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
				// ★ 第 18 轮：空集合原来直接 return，日志里没有任何一行说明「C++ 这次没推」
				//   （第 17 轮实测：master 解析失败 ⇒ 待推送=0 ⇒ 整条推送路径静默停摆，
				//   玩家看到的是 SWF 内嵌回退数据，日志却只能靠 `src=embedded` 反推）。
				//   补一行 INFO，把「为什么没推」写清楚（每轮菜单只打一次）。
				if (!g_pending.done && g_pending.quests.empty() && !g_pending.emptiedLogged) {
					g_pending.emptiedLogged = true;
					REX::INFO("本轮没有可推送的条目（静态表={} 引擎里存在={} 跳过(master未加载)={}）"
							  "—— 本次由 SWF 内嵌回退数据兜底",
						g_pending.total, g_pending.stats.live, g_pending.stats.skippedMaster);
				}
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
				} else if (bridgeDetail.find(kMenuNotReadyMark) != std::string::npos) {
					// ★ 第 19 轮降噪：菜单刚开的头几帧「菜单表里还没有 BSMissionMenu」是
					//   **预期**状态（推送侧已有同样的分流），不该占一行 WARN。
					REX::INFO("菜单尚未就绪（UI 表里还没有 BSMissionMenu 条目）| 桥解析耗时 {} ms",
						NowMs() - t0);
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
			// ---- 第 17 轮：下发后的**结果确认**（脚本到底有没有真的应用）----
			// 起因：第 16 轮的日志能证明「请求写进去了」，但「脚本应用成功没有」只在
			// 下次打开菜单时才会被读到 —— 玩家当下看到的蓝点有没有出现，日志里是空白。
			std::uint64_t verifyAtMs{};    // 0 = 没有待确认的请求
			std::uint32_t verifyTries{};
			std::uint32_t verifySeq{};     // 这次确认对应的请求序号（防止和自我重试打架）
		};
		GuideRuntime g_guide;
		constexpr std::uint64_t kGuidePollIntervalMs = 100;
		constexpr std::uint64_t kGuideVerifyFirstMs = 900;   // 下发后第一次查状态的时间
		constexpr std::uint64_t kGuideVerifyRetryMs = 2000;  // 之后每次重查的间隔
		constexpr std::uint32_t kGuideVerifyMaxTries = 6;    // 最多查这么久（≈ 11 秒）

		const StaticQuestInfo* FindStaticQuest(std::uint32_t a_formID)
		{
			// 表里存的是「master + 记录号」，所以运行期比对要用解析出来的 FormID
			// （g_runtimeRows 在每次打开菜单时重建，这里只查它 —— 263 条，线性扫足够）。
			for (const auto& row : g_runtimeRows) {
				if (row.formID == a_formID) {
					return row.info;
				}
			}
			return nullptr;
		}

		// ★ 第 17 轮：反向查（运行期 FormID -> 静态行）。用于「DLL 刚启动/刚读档，而
		//   ESM 通道里还留着上一次会话设的引导」——把那条任务认领回来（见 AdoptExistingGuide）。
		const StaticQuestInfo* FindQuestByGuideRef(std::uint32_t a_guideRefID)
		{
			for (const auto& row : g_runtimeRows) {
				const auto& info = *row.info;
				if (info.guideRefLocal == 0) {
					continue;
				}
				if (Masters::MakeFormID(info.guideRefMaster, info.guideRefLocal) == a_guideRefID) {
					return &info;
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

		// 安排一次「下发结果确认」（第 17 轮）：900ms 后查脚本状态，见 PollGuideVerify。
		void ScheduleGuideVerify(int a_seq)
		{
			g_guide.verifyAtMs = NowMs() + kGuideVerifyFirstMs;
			g_guide.verifyTries = 0;
			g_guide.verifySeq = static_cast<std::uint32_t>(a_seq);
		}

		// ★ 第 19 轮：**脚本活性探测**。
		//
		// 起因（第 18 轮实测日志）：本次会话的 Papyrus 日志里**没有任何 SAQ_Main 痕迹**
		// （历史会话每次都有 `SAQ_Main OnInit`），而 DLL 侧读到的 `通知=7778` 与上一次
		// 会话完全相同 —— 无法区分「脚本实例从存档恢复后僵死（收不到菜单事件）」和
		// 「DLL 读通道比脚本处理早」。若真僵死，玩家点引导会「写入成功但没人处理」。
		//
		// 判据：脚本的 OnMenuOpenCloseEvent 每次菜单打开都会把 SAQ_Notify +1，并在
		// Papyrus 日志留一条 `[SAQ] 菜单打开 通知=N`。这里在开菜单 1.5 秒后复读一次：
		//   值涨了 = 脚本活着（静默，不留噪音）；
		//   没涨   = WARN 留证（每轮菜单最多一次）。
		struct ScriptLiveness
		{
			bool          pending{};        // 菜单打开后等待复读
			bool          warned{};         // 本轮菜单已警告过（不重复刷）
			float         notifyAtOpen{};   // 打开时读到的通知值
			std::uint64_t dueMs{};          // 复读时间点
		};
		ScriptLiveness g_liveness;
		constexpr std::uint64_t kLivenessDelayMs = 1500;

		// 菜单打开时武装一次（读当前通知值作为基线）。
		void ArmScriptLiveness()
		{
			g_liveness.pending = false;
			g_liveness.warned = false;
			const auto ch = Guide::EnsureChannel();
			if (!ch.resolved) {
				return;  // 通道没认领（ESM 没启用等）—— LogEsmChannel 已经记过原因
			}
			g_liveness.notifyAtOpen = ch.notify;
			g_liveness.dueMs = NowMs() + kLivenessDelayMs;
			g_liveness.pending = true;
		}

		// 菜单开着时每帧调用（内部按 dueMs 自我短路，没到点/没武装时零开销）。
		void CheckScriptLiveness()
		{
			if (!g_liveness.pending || NowMs() < g_liveness.dueMs) {
				return;
			}
			g_liveness.pending = false;
			const auto ch = Guide::EnsureChannel();
			if (!ch.resolved) {
				return;
			}
			if (ch.notify > g_liveness.notifyAtOpen) {
				return;  // 通知值 +1 ⇒ 脚本响应了菜单事件（正常路径，不留噪音）
			}
			if (!g_liveness.warned) {
				g_liveness.warned = true;
				REX::WARN("脚本活性探测：开菜单 {} ms 后 SAQ_Notify 仍是 {:.0f}（没有 +1）——"
						  "SAQ_Main 可能没有响应菜单事件（实例从存档恢复后僵死？），"
						  "引导请求会写入成功但无人处理。看 Papyrus 日志有没有 `[SAQ] 菜单打开`；"
						  "若确实缺失，重新读一次档/重开游戏后再试",
					kLivenessDelayMs, ch.notify);
			}
		}

		// 应用一次引导请求，并把结果回写给界面。a_formID = 0 表示取消引导。
		// 结果码（与 AS3 的约定）：0=成功 / 1=没有引导目标 / 2=写通道失败 / 3=静态表里没有
		void ApplyGuideRequest(std::uint32_t a_formID, int a_seq)
		{
			if (a_formID == 0) {
				g_guide.verifyAtMs = 0;  // 取消：没有「结果」要确认
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
			if (entry->guideRefLocal == 0) {
				REX::WARN("引导请求：{}（0x{:08X}）没有引导目标（离线没算出「去哪里接」的引用，见 docs/05）",
					entry->nameZh, a_formID);
				NotifyGuideReply(a_seq, g_guide.questFormID, 1);
				return;
			}
			// ★ 第 17 轮：引导目标也是「master + 记录号」，运行期拼成 FormID
			//（DLC 任务的目标可能在基础游戏里，反之亦然）。
			const auto guideRefID = Masters::MakeFormID(entry->guideRefMaster, entry->guideRefLocal);
			if (guideRefID == 0) {
				REX::WARN("引导请求：{}（0x{:08X}）的引导目标属于未加载的 master（{}）",
					entry->nameZh, a_formID, Masters::Get(entry->guideRefMaster).name);
				NotifyGuideReply(a_seq, g_guide.questFormID, 1);
				return;
			}
			std::string detail;
			if (!Guide::SetGuideTarget(guideRefID, detail)) {
				REX::WARN("引导请求：{}（0x{:08X}）写 ESM 通道失败｜{}", entry->nameZh, a_formID, detail);
				NotifyGuideReply(a_seq, g_guide.questFormID, 2);
				return;
			}
			g_guide.questFormID = a_formID;
			g_guide.guideRef = guideRefID;
			REX::INFO("引导请求：{}（0x{:08X}）→ 引用 0x{:08X}（{}）｜{}",
				entry->nameZh, a_formID, guideRefID, entry->whereZh, detail);
			NotifyGuideReply(a_seq, a_formID, 0);
			ScheduleGuideVerify(a_seq);
		}

		// ★ 第 19 轮：一次引导请求「确定没能生效」时的收尾（确认超时 / 脚本状态 4）。
		//
		// 原来的行为只打一行 WARN，然后**什么都不做** —— 后果：
		//   ① 界面（由 SyncGuideState / AdoptExistingGuide 驱动）继续显示「正在引导」，
		//      而世界里根本没有标记 —— 界面说谎；
		//   ② 通道里的目标引用一直留着，下次开菜单又会被「认领」回来，无限重复。
		// 现在：清 ESM 通道 + 清本侧状态 +（菜单开着时）用结果码 4 回写界面回滚，
		// 让「界面上显示的」与「世界里真实发生的」重新对齐。
		void AbortUnverifiedGuide(std::string_view a_why, bool aMenuOpen)
		{
			const auto questID = g_guide.questFormID;
			const auto seq = static_cast<int>(g_guide.verifySeq);
			const auto* entry = FindStaticQuest(questID);

			std::string detail;
			const bool cleared = Guide::SetGuideTarget(0, detail);
			g_guide.questFormID = 0;
			g_guide.guideRef = 0;
			g_guide.verifyAtMs = 0;

			REX::WARN("引导未生效：{}（0x{:08X}）—— {}；已放弃本次引导（清通道{}）",
				entry ? entry->nameZh : "?", questID, a_why,
				cleared ? "成功" : ("失败: " + detail));
			if (aMenuOpen) {
				NotifyGuideReply(seq, 0, 4);  // 4 = 未生效：界面回滚竖条 + OFF 音
			}
		}

		// ★ 第 17 轮：引导下发后的结果确认。
		//
		// 为什么需要：第 16 轮把「请求已写入通道」和「界面回写」都补齐了，但**脚本那一半**
		// 只在下次打开菜单时才会被读到 —— 玩家点完引导、抬头看 HUD 有没有蓝点的那几秒，
		// 日志里什么都证明不了（第 16 轮实测日志：09:18:39 下发成功，到 09:18:46 关菜单
		// 都没有「脚本状态=1」的行）。
		//
		// 判据（脚本状态，见 docs/05 第四节）：
		//   1 = 已应用（蓝点应该出现了）→ 记一行 INFO，收工
		//   2 = 目标引用当时取不到（非常驻引用 + 格子没加载）→ 重发一次（最多 2 次）
		//   3 = 已清除（脚本重挂丢别名）→ 重发一次
		//   0 = 还没被脚本处理（脚本没跑 / 轮询太慢）→ 继续等，超时后收尾（第 19 轮起）
		//   4 = 别名不存在（ESM 补丁没生效）→ 收尾（重发无用）
		void PollGuideVerify(bool aMenuOpen)
		{
			if (g_guide.verifyAtMs == 0 || NowMs() < g_guide.verifyAtMs) {
				return;
			}
			g_guide.verifyAtMs = 0;  // 先清掉，下面的分支需要时再安排下一次
			const auto ch = Guide::EnsureChannel();
			if (!ch.resolved) {
				REX::WARN("引导结果确认失败：ESM 通道未认领（ESM 没启用？）");
				return;
			}
			const auto* entry = FindStaticQuest(g_guide.questFormID);
			if (++g_guide.verifyTries >= kGuideVerifyMaxTries) {
				AbortUnverifiedGuide(std::format("脚本状态一直是 {:.0f}"
					"（0 待处理 / 2 取不到 / 3 已清除 —— 看 Papyrus 日志里 SAQ_Main 有没有在跑）",
					ch.guideState), aMenuOpen);
				return;
			}
			const auto again = [&]() { g_guide.verifyAtMs = NowMs() + kGuideVerifyRetryMs; };
			if (ch.guideState == 1.0f) {
				REX::INFO("引导已生效：{}（0x{:08X}）脚本状态=1（世界里应该能看到标记/扫描仪路径线）",
					entry ? entry->nameZh : "?", g_guide.questFormID);
				return;
			}
			if (ch.guideState == 4.0f) {
				AbortUnverifiedGuide("脚本状态=4（别名 SAQ_GuideTarget 不存在 —— ESM 补丁没生效，重发无用）",
					aMenuOpen);
				return;
			}
			if ((ch.guideState == 2.0f || ch.guideState == 3.0f) && g_guide.verifyTries <= 2) {
				std::string detail;
				if (Guide::SetGuideTarget(g_guide.guideRef, detail)) {
					REX::INFO("引导重发：{}（0x{:08X}）脚本状态={:.0f}"
							  "（2=引用当时没加载 / 3=脚本重挂丢了别名），已清 0 让脚本再试｜{}",
						entry ? entry->nameZh : "?", g_guide.questFormID, ch.guideState, detail);
				}
			}
			again();
		}

		// ★ 第 17 轮：认领「上一次会话留下的引导」。
		//
		// 场景（第 16 轮的日志推出来的）：引导状态存在 GLOB 里（跟着存档走），而 DLL 的
		// 内存状态每次启动/读档都是空的 —— 于是「游戏里还在引导 A，DLL 却说『没有引导』」：
		//   • UI 上那条任务的竖条不亮、点它第一次变成「重设」而不是「取消」；
		//   • 玩家没有任何办法取消它（除非再点一条别的任务）；
		//   • AutoClear / Reissue 这两条自愈路径都因为 questFormID==0 直接返回。
		// 判据：通道认得出来 + 通道里的目标引用 != 0 + 静态表里有一条任务的引导目标正好是它。
		void AdoptExistingGuide()
		{
			if (g_guide.questFormID != 0) {
				return;  // 这次会话里已经设过引导了，不用认领
			}
			const auto ch = Guide::EnsureChannel();
			// ★ 第 21 轮：用拼好的完整 FormID（ch.targetFormID）—— 目标值在通道里是
			//   「低 24 位 + 高 8 位」两个 GLOB（float 精度所限，见 SAQ_Guide.cpp）。
			const auto targetID = ch.targetFormID;
			if (!ch.resolved || targetID == 0) {
				return;
			}
			const auto* entry = FindQuestByGuideRef(targetID);
			if (!entry) {
				REX::WARN("ESM 通道里有引导目标 0x{:08X}，但静态表里没有哪条任务的引导目标是它"
						  "（另一个存档留下的？）—— 已按「没有引导」处理，下次点引导会覆盖它",
					targetID);
				return;
			}
			// 反查运行期 FormID（表里是 master + 记录号）
			std::uint32_t questID = 0;
			for (const auto& row : g_runtimeRows) {
				if (row.info == entry) {
					questID = row.formID;
					break;
				}
			}
			if (questID == 0) {
				return;
			}
			g_guide.questFormID = questID;
			g_guide.guideRef = targetID;
			REX::INFO("认领已有引导：{}（0x{:08X}）目标引用=0x{:08X}｜脚本状态={:.0f}"
					  "（上一次会话/读档留下的，界面会同步成「正在引导」）",
				entry->nameZh, questID, targetID, ch.guideState);
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
			g_pending.emptiedLogged = false;  // 第 18 轮：新的一轮菜单，「没有可推送条目」日志可再打一次
			g_pending.lastAttemptMs = 0;
			g_pending.total = 0;
			g_pending.backoffMs = kPushRetryIntervalMs;  // 新一轮重试：退避复位

			// ★ 第 17 轮：先按**当前加载顺序**把「master + 记录号」解析成运行期 FormID，
			//   再建运行期行表（没装/没启用的 DLC 在这一步被丢掉）。
			//   ★ 第 18 轮：解析方式改为「前缀探测」（不再读 TESDataHandler —— 它的结构体
			//   偏移在本游戏版本上不可信），设计与证据见 SAQ_Masters.h 顶部注释。
			const auto t0 = NowMs();
			// ★ 第 20 轮：测试过滤开关 —— 控制台（GLOB，非 0 优先）或 ini（实机反馈的兜底）。
			const auto testMode = ResolveTestMode(Guide::EnsureChannel().testMode);
			const auto masters = BuildRuntimeRows(g_pending.stats);
			CollectAvailableQuests(g_pending.quests, g_pending.total, g_pending.stats, testMode.mode);
			const auto collectCost = NowMs() - t0;
			REX::INFO("数据源：{}", masters);
			if (testMode.mode > 0) {
				// 测试模式醒目提示（只在开启时打 —— 免得玩家忘了关、以为列表坏了）
				REX::INFO("测试模式：{}（{}）[来源={}] —— 控制台 set SAQ_TestMode to 0 或改 ini，均可关闭",
					testMode.mode, TestModeNote(testMode.mode), testMode.source);
			}
			REX::INFO("{}", FormatRuntimeStats(g_pending.stats));
			// 语言这一项只是**日志参考**：实际显示语言由 AS3 侧按引擎推来的任务名判定。
			// 收集耗时进日志（第 11 轮）：正常应为毫秒级；若出现几百 ms，就是查询本身有问题。
			REX::INFO("菜单打开：静态表={} 引擎里存在={} 待推送={} 收集耗时={} ms INI语言={}(仅供参考) 标题=可接任务/Available(中英都推，由 UI 选)",
				g_pending.total, g_pending.stats.live, g_pending.quests.size(), collectCost, GetGameLanguage());

			// 引导（第 10 轮）：ESM 通道自证 + 已接取任务的引导自动取消 + 当前引导状态
			LogEsmChannel();
			AdoptExistingGuide();        // ★ 第 17 轮：认领上一次会话/读档留下的引导
			AutoClearGuideIfAccepted();
			ReissueGuideIfScriptLost();  // ★ 第 16 轮：脚本重挂 / 引用没加载 → 重发一次
			LogGuideState();

			TryPushPending();
			ArmScriptLiveness();  // ★ 第 19 轮：菜单打开 1.5 秒后复读通知值，验证脚本活性
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

			// ★ 第 17 轮：引导结果确认 —— **菜单关掉之后也要继续跑**
			//   （脚本在菜单关闭时会立刻应用一次引导，玩家点完往往马上关菜单去看 HUD 上的蓝点；
			//    这里只读 ESM 的 GLOB + 静态表，不碰 UI，所以关着菜单调用是安全的。
			//    函数内部用 verifyAtMs==0 自我短路，没请求时零开销。）
			//   ★ 第 19 轮：把 open 传进去 —— 超时/失败时要回写界面（菜单开着才做）。
			PollGuideVerify(open);

			// ★ 第 19 轮：脚本活性探测（菜单打开 1.5 秒后复读通知值，见 CheckScriptLiveness）。
			//   内部按「是否武装 + 到点没有」自我短路，菜单关着/没请求时零开销。
			if (open) {
				CheckScriptLiveness();
			}
		}
	}

	std::filesystem::path PluginDir()
	{
		// ★ 第 22 轮：通过「本模块里一个函数的地址」反查模块句柄 —— 不依赖 SFSE 接口，
		//   也不怕同时加载了多个插件（FROM_ADDRESS 精确到本 DLL）。
		//   MO2 下插件从 mod 目录加载，日志/配置文件就落在那里（或它映射出的虚拟
		//   Data\SFSE\Plugins\），删 mod 时一起消失。
		HMODULE self{};
		if (!::GetModuleHandleExW(
				GET_MODULE_HANDLE_EX_FLAG_FROM_ADDRESS | GET_MODULE_HANDLE_EX_FLAG_UNCHANGED_REFCOUNT,
				reinterpret_cast<LPCWSTR>(&PluginDir), &self) ||
			self == nullptr) {
			return {};
		}
		wchar_t buf[MAX_PATH]{};
		if (::GetModuleFileNameW(self, buf, MAX_PATH) == 0) {
			return {};
		}
		return std::filesystem::path{ buf }.parent_path();
	}

	bool Install()
	{
		if (g_installed.exchange(true)) {
			return true;
		}

		g_mainThreadId.store(::GetCurrentThreadId());

		// ★ 第 20 轮：首次运行生成测试开关 ini 模板（存在就不动；失败不影响任何功能）
		EnsureTestModeIniTemplate();

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
