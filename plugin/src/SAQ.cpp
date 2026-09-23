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
#include "SAQ_Decision.h"    // ★★ 第 64 轮（大项 K）：离线层决策纯函数（有单元测试）
#include "SAQ_Guide.h"       // 引导通道（DLL ↔ ESM 的 GLOB ↔ SAQ_Main.psc）
#include "SAQ_Masters.h"     // 「插件名 + 记录号」→ 运行期 FormID（DLC / 多 master）
#include "SAQ_QuestCond.h"   // ★ 第 35 轮：进度门槛（「进度没到不显示」）
#include "SAQ_QuestState.h"  // TESQuest 运行时状态（已开始/已完成/追踪中）
#include "SAQ_UI.h"          // UI 通道（菜单表 → IMenu → Movie → ASMovieRoot）
#if SAQ_WITH_HARNESS
#	include "SAQ_Test.h"    // ★ 第 49 轮：引擎内 harness 的用例驱动器（ini [Test] Harness）
#	include "SAQ_TestOps.h" // ★ 第 49 轮：harness 原语（日志环形缓冲 / 命令通道 / 菜单开关）
#endif
#include "SAQ_QuestTable.h"  // 生成物：master + 记录号 -> 中/英文名 + 类型 + 引导目标（tools/esm/gen_quest_table.py）
#include "SAQ_EntryTable.h"  // 生成物：无限任务入口（任务板）条目（tools/esm/gen_entry_table.py）

#include "RE/B/BGSLocation.h"   // ★ 第 40 轮：星图诊断要沿父地点链看引擎认哪个地点
#include "RE/B/BSFixedString.h"
#include "RE/B/BSTEvent.h"
#include "RE/F/FormTypes.h"
#include "RE/IDs.h"  // 编译期 ID 审计要用（见下方 kIdUsable）
#include "RE/I/INISettingCollection.h"
#include "RE/P/PlayerCharacter.h"  // ★ 第 40 轮：星图诊断里记玩家所在地点（对照用）
#include "RE/S/Setting.h"
#include "RE/T/TESDataHandler.h"
#include "RE/T/TESForm.h"
#include "RE/T/TESObjectREFR.h"   // ★ 第 40 轮：GetCurrentLocation / GetEditorLocation
#include "RE/U/UI.h"
// ★ 第 37 轮：SET COURSE（R）要打开星图 —— 用引擎自己的 UI 消息队列关掉任务菜单
//   （kHide），脚本才能在下一次「菜单关闭」事件里调用 Papyrus 原生函数打开星图。
#include "RE/U/UIMessageQueue.h"

#include <Windows.h>

#include <algorithm>   // ★ 第 64 轮：std::min（候选池固定数组收集）
#include <array>
#include <atomic>
#include <cstdint>
#include <cstring>
#include <filesystem>
#include <format>
#include <fstream>
#include <memory>
#include <span>        // ★ 第 64 轮：离线层纯函数的输入（std::span）
#include <string>
#include <string_view>
#include <unordered_map>
#include <utility>
#include <vector>

namespace SAQ
{
	using namespace std::string_view_literals;

	namespace
	{
		constexpr const char* kMenuName = "BSMissionMenu";  // 原版任务菜单
		// ★ 第 65 轮（任务专属图标）：不再使用 AS3 的 AVAILABLE_QUEST_TYPE(6) 当 type ——
		//   payload 的 type 列改推**真实任务类型**（0=活动 2=派系 3=杂项 4=任务），
		//   界面才能像原版一样区分图标（势力图标另由 faction 列决定）。
		//   「只出现在我们 tab」由 bSaqAvailable 标记 + 掩码判定，与 type 无关
		//   （见 MissionsList.EntryFilterCompare_Impl）。

		// ★ 第 27 轮：无限任务入口（任务板）—— payload 的 type 列用这个值，AS3 侧据此
		//   换文案（子项「前往任务板」+ 专用描述），普通任务不会用到 100。
		constexpr std::int32_t kEntryQuestType = 100;
		// ★★ 第 80 轮：「提供无限任务的 NPC」入口（贸易管理局商人 / 追踪者联盟探员）——
		//   载荷 type 用 101（AS3 侧：子项「找他接活」+ 可重复任务专用描述）。
		//   名字里自带「（可重复）」前缀（数据侧加好，见 SAQ_EntryTable.h）。
		constexpr std::int32_t kNpcEntryQuestType = 101;

		// ★ 第 80 轮：入口表两类的条数（编译期从静态表算 —— 日志/用例对账用）。
		constexpr std::size_t CountEntryKind(std::uint8_t a_kind)
		{
			std::size_t n = 0;
			for (const auto& e : kEntryTable) {
				if (e.kind == a_kind) {
					++n;
				}
			}
			return n;
		}
		constexpr std::size_t kEntryBoardCount = CountEntryKind(kEntryKindBoard);
		constexpr std::size_t kEntryNpcCount = CountEntryKind(kEntryKindRepeatNpc);
		// 测试模式 5 = 只显示入口条目（在列表里单独验证任务板入口，不受 260 条任务干扰）。
		constexpr int kEntryOnlyTestMode = 5;
		// ★ 第 46 轮：测试模式值的**上限**（6 = 只显示「需要靠近」的任务）。
		//   加新模式时**必须**一起改这里 —— 上限原先写死成 `v > 5`（第 27 轮），
		//   结果 `Mode=6` 被静默折成 0（=不过滤）：玩家看到的是「过滤失效，所有任务都在」。
		constexpr int kMaxTestMode = 6;

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
		static_assert(kIdUsable(RE::ID::UIMessageQueue::Singleton));     // ★ 第 37 轮：UI 消息队列（关任务菜单）
		static_assert(kIdUsable(RE::ID::UIMessageQueue::AddMessage));    // ★ 第 37 轮：kHide 关菜单

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
			std::size_t entries{};            // ★ 第 27 轮：这次加入的「无限任务入口」（任务板）条数
			std::size_t entryNavigable{};     // ★ 第 28 轮：其中「引用当前可加载、能导航」的条数
			// ★ 第 30 轮：能导航的入口里，引导目标是「候选链」的哪一档
			//   （marker = 新建常驻 XMarker / board = 任务板引用自身 / fallback = 同 cell 常驻兜底）
			std::size_t entryByMarker{};
			std::size_t entryByBoard{};
			std::size_t entryByFallback{};
			std::size_t skippedMaster{};      // 所属 master 没加载（DLC 没装/没启用）而跳过的
			// ★ 第 35 轮：进度门槛（「游戏进度还不能让玩家接到 ⇒ 不显示」）
			std::size_t progressGated{};      // 带门槛的任务数（静态表 condCount>0 的）
			std::size_t progressPassed{};     // 门槛全真 → 显示
			std::size_t progressHidden{};     // 门槛有假（进度没到）→ 隐藏
			std::size_t progressUnknown{};    // 求值不了 → 放行（保守）
			bool        progressFilterOff{};  // ini 把过滤关了（只统计不隐藏）
			std::string progressSamples;      // 「进度没到」的名单（名字 + 没通过的检查）
			// ★★ 大项 D（第 48 轮）：INFO 门槛（对话侧条件）
			std::size_t infoGated{};          // 带 INFO 门槛的任务数（静态表 infoGroupCount>0 的）
			std::size_t infoPassed{};         // 全部对话都有「已知为假」以外的出路 → 显示
			std::size_t infoHidden{};         // 全部对话都有已知为假的条件 → 隐藏
			std::size_t infoExempt{};         // ★ 第 48 轮补丁：判「进度没到」但引擎已开始 → 放行
			std::size_t infoUnknown{};        // 结构异常 → 放行（保守）
			bool        infoFilterOff{};      // ini 把过滤关了（只统计不隐藏）
			std::string infoSamples;          // 「INFO 没到」的名单（名字 + 已知为假的条件）
			// ★★ 第 67 轮：链式门槛（编号任务链的启动边 ——「上一个任务的收尾 stage
			//   启动下一个任务」；数据见 kChainGates / tools/esm/gen_quest_chain.py）。
			std::size_t chainGated{};         // 带链式门槛的任务数（静态表 chainCount>0 的）
			std::size_t chainPassed{};        // 至少一条启动边已触发 → 显示
			std::size_t chainHidden{};        // 全部启动边都没触发（进度没到）→ 隐藏
			std::size_t chainUnknown{};       // 求值不了 → 放行（保守）
			bool        chainFilterOff{};     // ini 把过滤关了（只统计不隐藏）
			std::string chainSamples;         // 「链式没到」的名单（名字 + 未触发的前置）
			// ★★ 第 74 轮（同伴好感度任务）：「入口」同伴任务（个人任务）**固定显示** ——
			//   跳过三类门槛（进度 / INFO / 链式）；完成过滤仍生效（做过的任务不再显示）。
			//   「后续」（承诺任务）不在其中：照旧走链式门槛（见 kChainGates 里的同伴边）。
			std::size_t companionPinned{};    // 固定显示的同伴任务数
			std::size_t companionGateMiss{};  // 其中被门槛判「进度没到」但被放行的条数
			std::size_t companionOrdered{};   // ★ 前置到列表开头的同伴条目数（按同伴分组）
			std::string companionSamples;     // 名单（任务名已带同伴前缀）
			// ★★ 第 75 轮（四大势力开头任务）：UC01 / FC01 / RI01 / CF01 四条 ——
			//   玩家要求「固定显示，并固定排在可接任务列表的前四个」。
			//   跳过三类门槛（同同伴「入口」），完成过滤仍生效；固定顺序 = 静态表下标。
			std::size_t factionPinned{};      // 固定显示的势力开头任务数
			std::size_t factionGateMiss{};    // 其中被门槛判「进度没到」但被放行的条数
			std::size_t factionOrdered{};     // ★ 前置到列表**最前**的势力条目数（固定顺序）
			std::string factionSamples;       // 名单（任务名 + 势力 + 是否跳过门槛）
			// ★★ 第 89 轮（可重复任务）：这一类「做完一次还能再接」（静态表
			//   StaticQuestInfo::repeatable ≥ 0）⇒ **豁免「已完成」过滤**（完成后继续显示）。
			//   数据 ref/repeatable_quests.json（gen_repeatable_quests.py）；见 docs/11。
			//   ★ AS3 侧还有第二道过滤（FilterKnownQuests：在玩家日志里就丢）——
			//     载荷第 11 列 = 可重复标记，AS3 对「已完成 + 可重复」同样豁免。
			std::size_t repeatableTotal{};    // 这次列表里的可重复任务数（含未完成的）
			std::size_t repeatableKept{};     // 其中**已完成但被豁免保留**的条数（核心证据）
			std::string repeatableSamples;    // 被豁免保留的名单（名字 + FormID + 状态）
			//   ★★ 第 96 轮（可重复任务分组）：整组排到列表末尾（顺序见 SAQ.cpp 的
			//     stable_sort 调用点 / Decision::PinnedOrderKey 的 group 3）——
			//     这里的数字 = 排序后落在末尾的可重复任务数（日志/用例证据；
			//     顺序本身的运行期证据见界面 `order=` 探针第 96 轮起的 `|tail=` 段）。
			std::size_t repeatableOrdered{};  // 列表**末尾**的可重复任务数
			bool        filterApplied{};      // 这次到底有没有按运行时状态过滤
			std::string samples;              // 被剔掉的前几条（名字 + 状态）
			std::string vtableSamples;        // 未识别虚表的样本（诊断）
			std::string entryUnavailable;     // ★ 第 29/30 轮：不可导航入口的名单 + 候选命中诊断
			// ★★ 第 79 轮：**名单截断留痕**（四个名单共用同一形式）——
			//   名单都有打印上限（kMaxSamples = 40），超出的条目此前被**静默丢弃**
			//   （`if (count < kMaxSamples)` 没有 else）⇒ 排查时「被藏」看起来像
			//   「没被藏」。本轮起因就是它：第 77 轮的用例断言
			//   `assert.log 链式没到: .*领先一步[0x002C572B` 报「日志里没出现」，
			//   复查证明产品判据全对（43 条 kFail，含这条），只是表内顺序最后 3 条
			//   被 40 条上限截掉了 —— 断言不可达是日志缺陷，不是产品回归。
			//   现在：超出的条目记进这里（**紧凑格式**：名字 + FormID，不带 detail ——
			//   上限的本意是控制行长度，紧凑形式每条 ~25 字符、最多 ~23 条 ≈ 0.6 KB），
			//   Format 时以 `（另有 N 条未列出：…）` 追加在各自名单之后，
			//   断言 `名单:.*<名字>[<FormID>` 对截断区同样可达。
			std::size_t progressOverflow{};         // 「进度没到」名单未列出的条数
			std::string progressOverflowSamples;    // 未列出条目的紧凑名单
			std::size_t infoOverflow{};             // 「INFO没到」名单未列出的条数
			std::string infoOverflowSamples;
			std::size_t chainOverflow{};            // 「链式没到」名单未列出的条数
			std::string chainOverflowSamples;
			std::size_t hiddenOverflow{};           // 「隐藏」名单未列出的条数
			std::string hiddenOverflowSamples;
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

		// ★★★ 第 125 轮（路线 D · 冲突检测）：UI 通道身份判定状态。
		//
		// 背景（docs/15 九·补六「产品化观察①」）：我们的补丁 SWF 被其它修改
		//   `missionmenu.swf` 的 mod 覆盖（或没安装 / 版本过旧）时，界面上不存在我们的
		//   任何 AS3 入口 —— 旧行为是每次开菜单退避重试 14 次（日志持续
		//   「推送失败（重试）」），玩家侧则看不出「mod 没生效」的原因。
		//   第 125 轮起：真失败时探测界面身份（UI::ProbeChannelIdentity）——
		//   判定 notOurs ⇒ 本次菜单停推（done）+ 一行 WARN + 请脚本给玩家一条 HUD 提示。
		//
		// 判定纪律（宁可漏判，不可误判 —— 误判会让正常界面被停推）：
		//   · 只在**真失败**（非「菜单还没就绪」）且第 2 次尝试起才探测；
		//   · notOurs 的判据 = 桥解析成功（Movie/ASMovieRoot 有效）+ `_root.SAQ_Report`
		//     调用失败或没有 stamp= 指纹（见 SAQ_UI.cpp 的 ProbeChannelIdentity）；
		//   · 每菜单打开重置一次（重开菜单 = 新的一次机会）；
		//   · 提示（GLOB）**进程内只请求一次**，避免反复打扰。
		UI::ChannelIdentity g_uiChannel{ UI::ChannelIdentity::unknown };
		bool                g_uiChannelDead{};   // notOurs ⇒ 本菜单会话停用一切 UI 交互
		bool                g_uiNoticeSent{};    // 进程级：提示只请求一次

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
		// ★ 第 33 轮：菜单关着时预建静态表 —— 「表还没就绪」只记一次（见 EnsureStaticTablesReady）
		bool g_staticNotReadyLogged{};

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

		// ★★ 第 33 轮：菜单关着时也要保证「静态表」可用（master 前缀 + 运行期行表）。
		//
		// 起因（13:43 会话实证，docs/99 一·补十八）：第 32 轮的「例行认领」确实跑了，但认领要用的
		// 两张表**只在菜单打开时才建**（BuildRuntimeRows 的唯一调用点在 OnMissionMenuOpened）——
		// 于是没开过菜单的会话里 `Masters::MakeFormID()` 对未解析的 master 一律返回 0，
		// 三条反查（任务 guideRef / 入口 uID / 入口候选）全部落空，日志打出「静态表里没有哪条
		// 任务/入口的引导目标是它（另一个存档留下的？）」——**自愈形同虚设**，玩家的旧引导
		// （偏 3.41 m 的兜底引用）继续生效。
		//
		// 现在菜单关着时也能把表建起来：已就绪 ⇒ 零开销直接返回；未就绪 ⇒ 试一次
		// （Refresh 内部有会话级缓存、失败会打去重 WARN），失败不缓存、下次 Tick 再试。
		// 返回 false 时调用方**不要**做任何「认不出目标」的判断 —— 那只是表还没建好。
		bool EnsureStaticTablesReady(std::string_view a_why)
		{
			if (!Masters::Resolved()) {
				Masters::Refresh();
			}
			if (!Masters::Resolved()) {
				if (!g_staticNotReadyLogged) {
					g_staticNotReadyLogged = true;
					REX::INFO("静态表尚未就绪（{}）：master 前缀还没解析出来 —— 稍后自动重试"
							  "（这期间不做认领、也不把通道目标当「认不出」）",
						a_why);
				}
				return false;
			}
			if (g_runtimeRows.empty()) {
				RuntimeFilterStats stats{};
				const auto masters = BuildRuntimeRows(stats);
				if (g_runtimeRows.empty()) {
					return false;   // 极端情况：master 在、但一条记录都查不到 —— 下次再试
				}
				REX::INFO("静态表已就绪（菜单关着时预建，{}）：{}；运行期行 {}/{}（master 未加载而跳过 {}）",
					a_why, masters, g_runtimeRows.size(), kQuestTableSize, stats.skippedMaster);
			}
			return true;
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
		//
		// ★ 第 27 轮：N=5 = 只显示「无限任务入口」（任务板）条目 —— 验证任务板入口时
		//   不受 260 条任务干扰（见 CollectAvailableQuests 里的 kEntryOnlyTestMode 分支）。
		// ★★ 第 46 轮：N=6 = 只显示「需要靠近」的任务。
		// ★★ 第 47 轮（大项 C）：判据一度放宽为「**首选**（质量最优）候选非常驻」。
		// ★★ 第 48 轮（本轮）：**回退为「全部候选都非常驻」**（实测反馈：放宽后
		//   209 条有目标的任务里 158 条命中 ⇒ 测试模式 6 显示 155 条、描述提示覆盖 76%
		//   的任务，「提示」噪音化）。
		//
		//   现在只把**真正会「点了暂时没反应」**的任务算进这一类（本机 20 条）：
		//   候选池里一个常驻都没有 ⇒ 远处点引导 = 全不可得 = 待生效链路
		//   （结果码 5 + HUD 提示 + 退避重试，靠近后自动生效）。
		//   对比：「首选非常驻 + 池里有常驻候选」的 138 条 —— 远处点引导会**落到常驻候选**
		//   （立即生效、蓝点在目标附近），靠近后由复算自动升级 → 不需要提示，
		//   也不在这场清单里。
		// ------------------------------------------------------------------

		// ★★ 第 64 轮（大项 K）：QuestRuntimeState → 离线层 RuntimeFlags
		//   （「只挡已完成」的判据在 Decision::DecideRuntimeFilter，有单测）。
		Decision::RuntimeFlags ToDecisionFlags(const QuestRuntimeState& a_state)
		{
			return Decision::RuntimeFlags{
				.started = a_state.started,
				.completed = a_state.completed,
				.stopping = a_state.stopping,
				.active = a_state.active,
				.running = a_state.running,
			};
		}

		// ★ 第 46 轮：候选池判定助手 —— 定义在下面的候选池区（`CandidateAt` 之后）。
		//   ★ 第 47 轮改名 FirstCandidateNonPersistent（判据放宽），第 48 轮改回本名。
		//   两处调用：① 这里的测试模式 6（筛「需要靠近」的任务）；② CollectAvailableQuests
		//   组 QuestEntry 时算 needsApproach（推给界面提示用）。
		bool AllCandidatesNonPersistent(const StaticQuestInfo& a_info);

		bool PassesTestFilter(const StaticQuestInfo& a_info, int a_mode)
		{
			// ★ 第 64 轮（大项 K）：模式真值表移到离线层（Decision::PassesTestFilter，
			//   有单测）；这里只把任务信息装成结构体。
			//   注：needsApproach 只在模式 6 时计算（与抽取前的调用次数一致）。
			Decision::TestFilterInput in{
				.hasTarget = a_info.candCount != 0,   // ★ 第 45 轮：候选池代替旧的单目标字段
				.isDlc = a_info.master != 0,
				.hasNamedPlace = a_info.whereZh != nullptr && a_info.whereZh[0] != '\0',
			};
			if (a_mode == 6) {
				in.needsApproach = AllCandidatesNonPersistent(a_info);
			}
			return Decision::PassesTestFilter(a_mode, in);
			// 模式 5 不在这里处理：它在 CollectAvailableQuests 里让整段任务循环都不跑
			// （只加入口条目），不依赖逐条判定。
		}

		std::string_view TestModeNote(int a_mode)
		{
			switch (a_mode) {
			case 1: return "只显示「有引导目标」的条目";
			case 2: return "只显示「没有引导目标」的条目（测界面回滚）";
			case 3: return "只显示 DLC 条目";
			case 4: return "只显示「有引导目标 + 有具名地点」的条目";
			case 5: return "只显示「无限任务入口」（任务板）条目";
			case 6: return "只显示「需要靠近」的条目（全部候选都非常驻：远处点引导进入待生效、靠近后自动生效）";
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
				";   5 = 只显示「无限任务入口」（任务板，12 条）—— 验证任务板条目的显示与引导\r\n"
				";   6 = 只显示「需要靠近」的任务（全部候选都非常驻，20 条）—— 远处点「前往接取地点」\r\n"
				";       会提示「目标尚未加载」并等待你靠近（靠近后自动生效）；验证待生效 / HUD 提示 /\r\n"
				";       自动重试链路（第 46/48 轮）\r\n"
				"; 控制台（如果你的游戏认 `set SAQ_TestMode to N`）非 0 时优先于本文件。\r\n"
				"[Test]\r\n"
				"Mode=0\r\n"
				"; ★★ 第 49 轮：harness 的两个键**必须在这个 [Test] 段里** —— 放到别的段\r\n"
				";   （例如 [Filter]）插件读不到（GetPrivateProfileInt(\"Test\", …) 只认本段；\r\n"
				";   实机踩过一次：构建脚本原来是「追加到文件末尾」，结果落进 [Filter] 段，\r\n"
				";   harness 静默不跑）。\r\n"
				";   0 = 关（默认，普通玩家）；1 = 启用引擎内自动化测试：插件会读 Plan 指向的\r\n"
				";   用例文件，在游戏里自动造进度 / 开关菜单 / 选中 / 按键 / 断言，跑完把结果\r\n"
				";   写到同目录的 SAQ_testresults.json。★ 会改任务状态：先备份存档。\r\n"
				";   ★ 改 0→1 不必重启游戏（插件每 2 秒复查本文件；再置 1 会重新载入用例）。\r\n"
				";   ★ Nexus 下载的发布版不含 harness 编译（这两个键不起作用；自编译开发版才有效）。\r\n"
				"Harness=0\r\n"
				"Plan=SAQ_TestPlan.txt\r\n"
				";\r\n"
				"; ---- 进度门槛过滤（第 35 轮，「游戏进度还不能让玩家接到就不显示」） ----\r\n"
				"; 判据来自任务记录级条件里「引用别的任务」的 GetQuestRunning / GetQuestCompleted\r\n"
				"; / GetStageDone（比较运算符在生成期折叠成期望值，第 128 轮）—— 目前覆盖 7 条任务\r\n"
				"; （如「迟到者」要「枝节横生」完成）。\r\n"
				";   1 = 过滤（默认）：进度没到的任务不显示\r\n"
				";   0 = 不过滤：只把判据结果写进日志（便于对照界面）\r\n"
				";\r\n"
				"; ---- 对话条件过滤（第 48 轮·大项 D，「进度没到」的第二判据） ----\r\n"
				"; 判据来自任务自己的对话（INFO）里「引用别的任务」的同类条件 —— 全部参与判定的\r\n"
				"; 对话都「有已知为假的条件」⇒ 进度没到 ⇒ 不显示（目前覆盖 60 条任务）。\r\n"
				";   1 = 过滤（默认）；0 = 只写日志（便于对照界面）\r\n"
				";\r\n"
				"; ---- 任务链门槛（第 67 轮，「进度没到」的第三判据） ----\r\n"
				"; 势力线/主线那种「编号任务链」的后续任务（菜鸟觐见、风驰电掣、联合殖民地第 3 章…）\r\n"
				"; 只能由前一个任务的收尾阶段自动开始 —— 前置没做完时它们**根本接不到**，不该显示。\r\n"
				"; 判据来自官方 Papyrus 源码里的启动边（CF01 stage 1000 里 CF02.SetStage(10) 这种，\r\n"
				"; 目前覆盖 25 条任务 / 26 条启动边）：全部启动边都还没触发 ⇒ 不显示。\r\n"
				";   1 = 过滤（默认）；0 = 只写日志（便于对照界面）\r\n"
				"[Filter]\r\n"
				"ProgressCond=1\r\n"
				"InfoCond=1\r\n"
				"ChainCond=1\r\n"
				";\r\n"
				"; ---- 日志文件大小上限（第 112 轮） ----\r\n"
				"; 单位 MB：写新一行时若会超过就把旧内容整体清空（不是滚动保留旧文件）。\r\n"
				";   Nexus 发布包默认 1；开发构建默认 10 —— 想留更长的记录就改这个值。\r\n"
				"[Log]\r\n"
#if SAQ_WITH_HARNESS
				"MaxSizeMB=10\r\n";
#else
				"MaxSizeMB=1\r\n";
#endif
			std::ofstream f{ path.c_str(), std::ios::binary };
			if (!f) {
				REX::WARN("测试开关 ini 写不进去（忽略；不影响其它功能）");
				return;
			}
			f.write("\xEF\xBB\xBF", 3);  // BOM：记事本识别中文注释
			f.write(tmpl, static_cast<std::streamsize>(std::strlen(tmpl)));
			REX::INFO("已生成测试开关 ini 模板（插件目录内的 SAQ_ShowAvailableQuests.ini）");
		}

#if !SAQ_WITH_HARNESS
		// ★★ 第 53 轮（大项 F · 发布就绪）：发布构建（SAQ_WITH_HARNESS=0）里没有 harness。
		//   如果 ini 里 `[Test] Harness=1`（开发时打开过，而本次装的是发布版 DLL），
		//   必须打一行明确的 WARN —— 否则现象就是「改了开关没反应」（第 49 轮踩过同类坑：
		//   开关落错 ini 段 ⇒ harness 静默不跑、日志里什么都没有，排查全靠猜）。
		//   正常玩家永远是 Harness=0，这行不会出现。
		void WarnIfHarnessRequestedWithoutSupport()
		{
			const auto path = TestModeIniPath();
			if (path.empty() ||
				::GetPrivateProfileIntW(L"Test", L"Harness", 0, path.c_str()) == 0) {
				return;
			}
			REX::WARN("ini [Test] Harness=1，但本 DLL 是发布构建（未编译 harness）——"
					  "引擎内自动化测试不可用。要跑测试请用 tools\\build-saq.ps1 -Harness "
					  "重新构建并部署（详见 docs/09）");
		}
#endif

		// 最终模式 = 控制台（GLOB，非 0 优先）否则 ini。a_globMode < 0 = ESM 旧版没有 GLOB。
		struct TestModeResolved
		{
			int         mode{};
			const char* source{ "默认" };
		};

		TestModeResolved ResolveTestMode(float a_globMode)
		{
			if (a_globMode >= 0.5f) {
				const int m = static_cast<int>(a_globMode + 0.5f);
				if (m > kMaxTestMode) {
					// ★ 第 46 轮：超范围**不静默**（旧写法把 Mode=6 折成 0，看起来就是「过滤失效」）
					REX::WARN("测试模式：控制台值 {} 超出已知范围（0~{}）—— 按 0（不过滤）处理",
						m, kMaxTestMode);
					return { 0, "控制台(未知值)" };
				}
				return { m, "控制台" };
			}
			const auto path = TestModeIniPath();
			if (!path.empty()) {
				const int v = static_cast<int>(::GetPrivateProfileIntW(L"Test", L"Mode", 0, path.c_str()));
				if (v > 0) {
					if (v > kMaxTestMode) {
						// 未知值按 0（不过滤）处理，但要**说出来** —— 否则玩家只知道「过滤没生效」
						REX::WARN("测试模式：ini 的 Mode={} 超出已知范围（0~{}）—— 按 0（不过滤）处理"
								  "｜ini：SAQ_ShowAvailableQuests.ini（[Test] Mode）",
							v, kMaxTestMode);
						return { 0, "ini(未知值)" };
					}
					return { v, "ini" };
				}
			}
			return { 0, "默认" };
		}

		// ★ 第 35 轮：进度门槛过滤开关（ini `[Filter] ProgressCond`）。
		//   1 = 过滤（默认）：任务的记录级条件「引用别的任务」的进度检查没过 ⇒ 不显示；
		//   0 = 只把判据结果写进日志、**不隐藏**（实机对照用：能直接对照「进度没到」名单
		//       和界面里实际出现的条目）。
		bool ResolveProgressCondFilter()
		{
			const auto path = TestModeIniPath();
			if (!path.empty()) {
				return ::GetPrivateProfileIntW(L"Filter", L"ProgressCond", 1, path.c_str()) != 0;
			}
			return true;
		}

		// ★★ 大项 D（第 48 轮）：INFO 门槛过滤开关（ini `[Filter] InfoCond`）。
		//   1 = 过滤（默认）：任务自己的对话条件判定「进度没到」⇒ 不显示；
		//   0 = 只把判据结果写进日志、**不隐藏**（实机对照用：能直接对照「INFO 没到」名单
		//       和界面里实际出现的条目）。
		bool ResolveInfoCondFilter()
		{
			const auto path = TestModeIniPath();
			if (!path.empty()) {
				return ::GetPrivateProfileIntW(L"Filter", L"InfoCond", 1, path.c_str()) != 0;
			}
			return true;
		}

		// ★★ 第 67 轮：任务链门槛过滤开关（ini `[Filter] ChainCond`）。
		//   1 = 过滤（默认）：编号任务链的后续任务、且全部启动边都没触发 ⇒ 不显示；
		//   0 = 只把判据结果写进日志、**不隐藏**（实机对照用）。
		bool ResolveChainCondFilter()
		{
			const auto path = TestModeIniPath();
			if (!path.empty()) {
				return ::GetPrivateProfileIntW(L"Filter", L"ChainCond", 1, path.c_str()) != 0;
			}
			return true;
		}

		// ==================================================================
		// ★★ 第 30 轮：入口条目的**引导目标候选链**
		//
		// 背景（第 29 轮实测 FAIL）：把非常驻引用 override 成「常驻」不生效 ——
		// override 只替换记录数据、**不改变引用的加载分类**（官方 SFBGS003/008 的 70 条
		// 同类 override，原记录本来就全是常驻 = 零先例；见 check_persist_precedent.py）。
		// 实机日志（12:45 会话）：
		//     入口=12(可导航 2) 入口不可导航: 任务板 · 新亚特兰蒂斯城[0x0021001E] …（10 条）
		//
		// 现在改成**候选链**（数据由 tools/esm/gen_entry_table.py 生成，见 SAQ_EntryTable.h）：
		//   ① markerLocal：本插件新建的**常驻 XMarker**（ESM 记录号 0x900+i，位置 = 任务板
		//      坐标；tools/esm/create_board_markers.py）—— 常驻引用在 cell 未加载时依然存在
		//      （实证：原生常驻的阿基拉城板在玩家位于赛多尼亚时一直可导航）⇒ 首选；
		//   ② 任务板引用自身 —— 原生常驻的总是可用；非常驻只有 cell 加载时可用；
		//   ③ fallback1/2：同 cell 里离板最近的原生常驻引用（位置差 1~20 m）—— 兜底。
		//
		// 这里用与脚本**同一个引擎查询**（`LookupByID`，Papyrus 的 Game.GetForm 也是它）
		// 依次取第一个命中的。日志 `入口=12(可导航 N｜marker a 原板 b 兜底 c 不可用 d)`：
		//   a=11 ⇒ 新建常驻引用被引擎接受（理想）；若 b/c 为主，看「入口候选诊断」行定位。
		// ==================================================================
		enum class EntryGuideSource : std::uint8_t { none, exactBoard, exactMarker, fallback };
		struct EntryGuideState
		{
			std::uint32_t    target{};   // 选中的引导目标（0 = 不可导航）
			EntryGuideSource source{ EntryGuideSource::none };
			std::string      diag;       // 每个候选的命中情况（日志用）
		};
		std::array<EntryGuideState, kEntryTableSize> g_entryGuide{};
		bool g_entryMarkerProbeLogged{};   // 第 31 轮：marker 探测一行，每会话一次

		const char* SourceName(EntryGuideSource a_src)
		{
			switch (a_src) {
			case EntryGuideSource::exactBoard:  return "任务板自身（精确）";
			case EntryGuideSource::exactMarker: return "新建常驻 marker（精确）";
			case EntryGuideSource::fallback:    return "同 cell 常驻兜底（大致位置）";
			default:                            return "无";
			}
		}

		// ★★ 第 31 轮：候选链改成**精确目标优先**。
		//
		// 实机反馈（2026-09-20 13:15 截图）：任务板的蓝点停在板子旁边 2~3 m。日志证据：
		//     入口=12(可导航 12｜marker 0 原板 2 兜底 10 不可用 0)
		//   ① 11 条新建常驻 marker **全部 `marker[未命中]`**（引擎里取不到，见 LogEntryMarkerProbe）；
		//   ② 于是 10 条条目落到「同 cell 最近的原生常驻引用」——离线数据里它们离板 1.8~8.1 m
		//      （陋室的兜底是 `MQ204_NoelBasement_Marker01a`，3.41 m ⇒ 正是截图里那个偏差）；
		//   ③ 而玩家走到板前时，**任务板引用本身其实已经可用**（cell 加载了，非常驻引用就存在）——
		//      可第 30 轮的顺序把 marker 排在最前、兜底排在原板后面，精确的目标永远轮不到。
		//
		// 现在的顺序（同样依次 `LookupByID` 取第一个命中的）：
		//   ① 任务板引用自身 —— **精确**（蓝点就落在板上；cell 加载时才有，且引擎会给它高亮）
		//   ② 新建常驻 marker —— **精确**，设计上任意位置可用（第 30 轮；目前实测取不到，见探测）
		//   ③ 同 cell 的原生常驻引用兜底 —— 大致位置（1.8~8 m），只用于「板所在 cell 还没加载」
		//
		// ★ 目标会在引导过程中动态更新（见 UpdateEntryGuideTarget）：从远处选时用兜底，
		//   走到板所在 cell 后自动换成精确目标，蓝点随之上板。
		EntryGuideState EvaluateEntryGuide(std::size_t a_index, bool aWantDiag = true)
		{
			EntryGuideState st;
			const auto& e = kEntryTable[a_index];
			const auto boardID = Masters::MakeFormID(e.master, e.refLocal);
			// ① marker 的运行期 FormID = (本插件加载序号 << 24) | markerLocal；序号取 Guide
			//   通道认领出来的前缀（SAQ_Guide.cpp 的「魔数 7777」探测，日志 `ESM 通道：前缀=0x0F`）。
			const auto ch = Guide::EnsureChannel();
			const std::uint32_t markerPrefix = (ch.resolved && ch.prefix <= 0xFF) ? (ch.prefix << 24) : 0;
			const auto tryCand = [&](std::uint32_t a_id, EntryGuideSource a_src, const char* a_tag) {
				if (a_id == 0) {
					if (aWantDiag) {
						st.diag += std::format("{}[无] ", a_tag);
					}
					return;
				}
				if (st.target != 0) {
					return;  // 已选中，剩下的候选不必再查（省一次 LookupByID）
				}
				const bool hit = RE::TESForm::LookupByID(static_cast<RE::TESFormID>(a_id)) != nullptr;
				if (aWantDiag) {
					st.diag += std::format("{}[{}] ", a_tag, hit ? "命中" : "未命中");
				}
				if (hit) {
					st.target = a_id;
					st.source = a_src;
				}
			};
			tryCand(boardID, EntryGuideSource::exactBoard, "原板");
			tryCand(e.markerLocal ? (markerPrefix | e.markerLocal) : 0,
				EntryGuideSource::exactMarker, "marker");
			// ★★ 第 110 轮：兜底候选的 master **跟条目走**（旧写法硬编码 master 0）——
			//   SFBGS003 条目（追踪者联盟悬赏信息台）的兜底也在它自己的 medium 空间里
			//   （展示柜 0xFD00F9CE / 总部外 marker 0xFD000033），必须用 e.master 解析。
			//   对基础游戏的 12 条板无行为变化（e.master = 0）。
			tryCand(e.fallback1 ? Masters::MakeFormID(e.master, e.fallback1) : 0,
				EntryGuideSource::fallback, "兜底1");
			tryCand(e.fallback2 ? Masters::MakeFormID(e.master, e.fallback2) : 0,
				EntryGuideSource::fallback, "兜底2");
			return st;
		}

		// ★ 第 31 轮：新建常驻 marker 取不到时的**数据侧探针**（一行，够定位）。
		//
		// 要回答的两件事：
		//   ① 基类 `XMarker`（0x0000003B）在引擎里存在吗？（不存在 ⇒ 我们的记录会被引擎丢掉）
		//   ② marker 的 FormID 是不是算错了？——除了通道前缀，再扫一遍**全部 256 个加载序号**，
		//      看 0x900 这个记录号有没有落在别的序号上（若有 ⇒ 「通道前缀 != 插件序号」，
		//      说明 GLOB 和引用被引擎放在了不同的序号空间）。
		void LogEntryMarkerProbe()
		{
			if (g_entryMarkerProbeLogged) {
				return;
			}
			g_entryMarkerProbeLogged = true;

			const auto probe = [](std::uint32_t a_id) {
				return RE::TESForm::LookupByID(static_cast<RE::TESFormID>(a_id)) != nullptr;
			};
			const auto ch = Guide::EnsureChannel();
			const std::uint32_t prefix = (ch.resolved && ch.prefix <= 0xFF)
				? static_cast<std::uint32_t>(ch.prefix)
				: 0;
			const std::uint32_t sample = kEntryTable[0].markerLocal;   // 0x90A（新亚特兰蒂斯城）
			std::string otherHits;
			for (std::uint32_t p = 0; p <= 0xFF; ++p) {
				if (p == prefix) {
					continue;
				}
				if (probe((p << 24) | sample)) {
					otherHits += std::format(" 0x{:02X}", p);
				}
			}
			// 对照：同一个前缀下我们**自己的 QUST**（0x800）—— 它在脚本里一直是好的
			// （引导能应用），所以它可以区分「序号映射坏了」和「只有 CELL 组里的引用没被加载」。
			constexpr std::uint32_t kOwnQuestLocal = 0x800;
			REX::INFO("入口 marker 探测：XMarker 基类(0x00003B)={}｜通道前缀=0x{:02X}（GLOB 认领值，"
					  "兼作 marker 序号）｜marker 0x{:03X}@0x{:02X}={}｜该记录号在别的序号上={}"
					  "｜对照 QUST@0x{:02X}={}",
				probe(0x3Bu) ? "有" : "无", prefix, sample, prefix,
				probe((prefix << 24) | sample) ? "有" : "无",
				otherHits.empty() ? "无" : otherHits,
				prefix, probe((prefix << 24) | kOwnQuestLocal) ? "有" : "无");
		}

		// ★ 第 27 轮：「无限任务入口」条目（第 80 轮起含「提供无限任务的 NPC」）——
		//   uID = 界面标识 = 条目引用的运行期 FormID（任务板 ACTIVATOR / NPC 的 ACHR）。
		//
		// 需求（AGENTS.md）：无限生成任务本身不显示，但「接取入口」（任务板、提供无限任务的
		// NPC）作为一条数据出现在列表里，点了就引导到它的位置。入口不是 quest，所以不走
		// 「已完成 / 已接取」那套运行时过滤。
		void AppendEntryRows(std::vector<QuestEntry>& a_out, RuntimeFilterStats& a_stats)
		{
			std::string diagAbnormal;  // 没走精确目标（走兜底/不可用）的条目诊断 —— 正常应完全为空

			for (std::size_t i = 0; i < kEntryTableSize; ++i) {
				const auto& e = kEntryTable[i];
				const auto boardID = Masters::MakeFormID(e.master, e.refLocal);
				if (boardID == 0) {
					continue;  // 所属 master 没加载（入口目前全在基础游戏，理论上不会发生）
				}
				const auto st = EvaluateEntryGuide(i);
				g_entryGuide[i] = st;

				QuestEntry entry;
				entry.formID = boardID;
				// AS3：入口条目（子项/描述换文案）—— 任务板 100 / 可重复 NPC 101（第 80 轮）。
				entry.type = (e.kind == kEntryKindRepeatNpc) ? kNpcEntryQuestType : kEntryQuestType;
				// 入口不是任务：没有阵营（界面把 type=100 折叠回「任务」图标显示）。
				entry.faction = -1;
				entry.hasGuideTarget = (st.target != 0);
				entry.nameZh = e.nameZh;
				entry.nameEn = e.nameEn;
				if (entry.hasGuideTarget) {
					++a_stats.entryNavigable;
					switch (st.source) {
					case EntryGuideSource::exactMarker: ++a_stats.entryByMarker;   break;
					case EntryGuideSource::exactBoard:  ++a_stats.entryByBoard;    break;
					case EntryGuideSource::fallback:    ++a_stats.entryByFallback; break;
					default: break;
					}
					// 只有「兜底」才值得诊断（精确目标 = 正常；第 31 轮：板自身也是精确的）
					if (st.source == EntryGuideSource::fallback) {
						diagAbnormal += std::format("{}[0x{:08X} {}] ", e.nameZh, boardID, st.diag);
					}
				} else {
					// 所有候选都取不到（连兜底常驻引用都取不到）——留完整诊断，便于判断
					// 「常驻引用是否真的与 cell 加载无关」这个引擎行为问题。
					a_stats.entryUnavailable += std::format("{}[0x{:08X} {}] ", e.nameZh, boardID, st.diag);
				}
				a_out.push_back(std::move(entry));
				++a_stats.entries;
			}
			if (!diagAbnormal.empty()) {
				REX::INFO("入口候选诊断（这些条目只拿到「大致位置」，见 docs/05 第九节）：{}", diagAbnormal);
				LogEntryMarkerProbe();
			}
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
		//   * ★ 第 27 轮：最后追加「无限任务入口」（任务板）条目（见 AppendEntryRows）
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
			a_out.reserve(g_runtimeRows.size() + kEntryTableSize);

			std::size_t hiddenByRuntime = 0;
			// 第 11 轮：从 5 提到 40 —— 「某条任务为什么不在列表里」要能直接从日志里
			// 查到答案（被隐藏的通常 30 条上下，全列出来 ~1.5KB / 次打开菜单，可接受）。
			constexpr std::size_t kMaxSamples = 40;
			std::size_t sampleCount = 0;

			// ★ 第 35 轮：进度门槛过滤开关（ini `[Filter] ProgressCond`，默认开）。
			const bool progressFilter = ResolveProgressCondFilter();
			a_stats.progressFilterOff = !progressFilter;
			std::size_t progressSampleCount = 0;

			// ★★ 大项 D（第 48 轮）：INFO 门槛（对话侧条件）过滤开关（ini `[Filter] InfoCond`）。
			const bool infoFilter = ResolveInfoCondFilter();
			a_stats.infoFilterOff = !infoFilter;
			std::size_t infoSampleCount = 0;

			// ★★ 第 67 轮：链式门槛（编号任务链的启动边）过滤开关（ini `[Filter] ChainCond`）。
			const bool chainFilter = ResolveChainCondFilter();
			a_stats.chainFilterOff = !chainFilter;
			std::size_t chainSampleCount = 0;

			// ★★ 第 74 轮（同伴好感度任务）：「入口」同伴任务的名单样本上限（与其它名单一致）。
			std::size_t companionSampleCount = 0;
			// ★★ 第 75 轮（四大势力开头任务）：同上（四条，其实永远在上限内）。
			std::size_t factionSampleCount = 0;
			// ★★ 第 89 轮（可重复任务）：被豁免保留（已完成）的名单上限。
			std::size_t repeatableSampleCount = 0;

			// ★ 第 27 轮：模式 5（只显示入口条目）跳过整段任务循环（入口在下面单独追加）。
			const bool entryOnly = (a_testMode == kEntryOnlyTestMode);
			if (!entryOnly) for (const auto& row : g_runtimeRows) {
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
				//   「已完成」：做过的任务不该再出现在「可接」里。
				// ★ 第 64 轮（大项 K）：判据在离线层（Decision::DecideRuntimeFilter，有单测）。
				// ★★ 第 89 轮（可重复任务）：静态表 repeatable ≥ 0 ⇒ **豁免**「已完成 ⇒ 隐藏」
				//   （这类任务做完一次后继续显示 —— 设计上还能再接；见 docs/11）。
				const bool repeatable = (info.repeatable >= 0);
				if (repeatable) {
					++a_stats.repeatableTotal;
					if (state.completed && state.vtableKnown) {
						++a_stats.repeatableKept;   // 核心证据：已完成但被豁免保留
						if (repeatableSampleCount < kMaxSamples) {
							++repeatableSampleCount;
							a_stats.repeatableSamples += std::format("{}[0x{:08X} {}] ",
								info.nameZh, row.formID, Describe(state));
						}
					}
				}
				if (Decision::DecideRuntimeFilter(ToDecisionFlags(state), state.vtableKnown,
												  repeatable) ==
					Decision::RuntimeFilterVerdict::kHideCompleted) {
					++hiddenByRuntime;
					if (sampleCount < kMaxSamples) {
						++sampleCount;
						// FormID 必须带上：名字可能与玩家的叫法不一致（玩家反馈「某条没显示」
						// 时，靠 FormID 精确核对，而不是靠名字猜）。
						a_stats.samples += std::format("{}[0x{:08X} {}] ", info.nameZh, row.formID, Describe(state));
					} else {
						// ★★ 第 79 轮：超出打印上限的条目不再静默丢弃（紧凑名单，见结构体说明）。
						++a_stats.hiddenOverflow;
						a_stats.hiddenOverflowSamples += std::format("{}[0x{:08X}] ", info.nameZh, row.formID);
					}
					continue;
				}

				// ★★ 第 74 轮（同伴好感度任务）：「入口」同伴任务（个人任务 —— 由好感度
				//   里程碑直接启动的那一环）**固定显示**：跳过下面三类门槛（进度 / INFO /
				//   链式），界面另有描述提示「需要一定好感度才能接取」（载荷第 8 列）。
				//   需求（玩家）：「把所有达到一定好感度才能接到的同伴任务**固定**在可接
				//   任务列表里，任务名称前面写上同伴的名字，并在提示里提示到达一定好感度
				//   才能接取」。
				//   ★ 只对「入口」生效：「后续」（承诺任务）companionPin == 0，照旧走链式
				//     门槛 —— 玩家要求「链式关系的后续任务还是不要显示，只显示入口任务」。
				// ★★ 第 75 轮（四大势力开头任务）：UC01 / FC01 / RI01 / CF01 四条同样
				//   **固定显示**（玩家要求「固定显示，并固定排在可接任务列表的前四个」）——
				//   它们各自的「进度门槛」（如 RI01 的 INFO 门槛、CF01 的链式门槛
				//   UC02@860）不再隐藏它们；描述里写「简要说明」（载荷第 9/10 列）。
				//   ★ 不跳过「已完成 ⇒ 隐藏」（做过的任务不该再出现在「可接」里），
				//     也不跳过控制台测试过滤（diagnostic，与产品语义正交）。
				const bool pinnedCompanion = Decision::IsCompanionPinned(info.companionPin);
				const bool pinnedFaction = Decision::IsFactionEntryPinned(info.factionEntry);
				const bool pinned = Decision::IsGatePinned(info.companionPin, info.factionEntry);
				bool pinnedBypassed = false;   // 被门槛判「进度没到」但固定显示放行（统计证据）

				// ★ 第 35 轮：进度门槛（需求「游戏进度还不能让玩家接到 ⇒ 不显示」）。
				//
				// 判据 = 任务记录级条件（CTDA）里「引用别的任务」的进度检查（只收
				// GetQuestRunning/GetQuestCompleted/GetStageDone；★ 第 128 轮起比较运算符
				// 在生成期折叠成 want —— 数据由 tools/esm/analyze_ctda.py 提取，见
				// SAQ_QuestTable.h 的 kQuestConds）。
				// 求值见 SAQ_QuestCond.cpp：任何一步求不了 ⇒ kUnknown ⇒ **放行**
				// （宁可在进度没到的时候多显示一条，也不能因为求值器的问题把真任务藏掉）。
				if (info.condCount) {
					++a_stats.progressGated;
					const auto gate = EvaluateProgressGates(info.condBegin, info.condCount);
					switch (gate.verdict) {
					case CondVerdict::kPass:
						++a_stats.progressPassed;
						break;
					case CondVerdict::kFail:
						// ★★ 第 74 轮：判据在离线层（Decision::DecideGateAction，有单测）——
						//   kPinBypass = 同伴「入口」任务：不隐藏、不进「进度没到」名单
						//   （名单的语义是「因为进度没到被隐藏」，放行的任务不该混进去）。
						if (Decision::DecideGateAction(gate.verdict, pinned) ==
							Decision::GateAction::kPinBypass) {
							pinnedBypassed = true;
							break;
						}
						// 名单无条件记录（即使 ini 把过滤关了 —— 那是实机对照的对照物）。
						if (progressSampleCount < kMaxSamples) {
							++progressSampleCount;
							a_stats.progressSamples += std::format("{}[0x{:08X} {}] ",
								info.nameZh, row.formID, gate.detail);
						} else {
							// ★★ 第 79 轮：超出打印上限的条目不再静默丢弃（紧凑名单，见结构体说明）。
							++a_stats.progressOverflow;
							a_stats.progressOverflowSamples += std::format("{}[0x{:08X}] ",
								info.nameZh, row.formID);
						}
						if (progressFilter) {
							++a_stats.progressHidden;
							continue;
						}
						break;
					case CondVerdict::kUnknown:
						++a_stats.progressUnknown;
						break;
					default:
						break;
					}
					}

					// ★★ 大项 D（第 48 轮）：INFO 门槛（对话侧条件）——「进度没到」的第二判据。
					//
					//   任务自己的对话（INFO）里、条件「引用别的任务」的那些：全部参与判定的
					//   对话都至少有「一条已知为假」的条件 ⇒ 进度没到 ⇒ 隐藏（判据设计与
					//   两例实测对照见 tools/esm/analyze_info_gates.py 与 docs/08）。
					//   求值语义（保守）：任何一条对话「没有已知为假的条件」（全真 / 不可判定）
					//   ⇒ 显示；数据结构异常 ⇒ 放行。
					if (info.infoGroupCount) {
						++a_stats.infoGated;
						const auto infoGate = EvaluateInfoGates(info.infoGroupBegin, info.infoGroupCount);
						switch (infoGate.verdict) {
						case CondVerdict::kPass:
							++a_stats.infoPassed;
							break;
						case CondVerdict::kFail:
							// ★★ 第 74 轮：同伴「入口」任务固定显示（判据同上，离线层有单测）。
							if (Decision::DecideGateAction(infoGate.verdict, pinned) ==
								Decision::GateAction::kPinBypass) {
								pinnedBypassed = true;
								break;
							}
							// ★ 第 48 轮补丁（实机日志复查抓到的误藏）：引擎已把这个任务标成
							//   「已开始」⇒ **放行**，不隐藏。依据 = 第 11 轮的实证：引擎 started
							//   的任务玩家**仍可能接到**（「全数到期」RAD05 就是那一轮的案例 ——
							//   它在 21:46 会话里又被 INFO 门槛误藏，交叉验证 WARN 自动抓出）。
							//   判据因此收窄为：「引擎**没启动** + 全部对话都有已知假条件 ⇒ 隐藏」
							//   （引擎都没启动的任务，大概率确实还没到接取点）。
							if (state.started) {
								++a_stats.infoExempt;
								REX::INFO("INFO 门槛判定『进度没到』但引擎已开始 —— 放行"
										  "（引擎自启的任务玩家仍可能接到，第 11 轮经验）："
										  "{}（0x{:08X}）｜{}",
									info.nameZh, row.formID, infoGate.detail);
								break;
							}
							// 名单无条件记录（即使 ini 把过滤关了 —— 那是实机对照的对照物）。
							if (infoSampleCount < kMaxSamples) {
								++infoSampleCount;
								a_stats.infoSamples += std::format("{}[0x{:08X} {}] ",
									info.nameZh, row.formID, infoGate.detail);
							} else {
								// ★★ 第 79 轮：超出打印上限的条目不再静默丢弃（紧凑名单，见结构体说明）。
								++a_stats.infoOverflow;
								a_stats.infoOverflowSamples += std::format("{}[0x{:08X}] ",
									info.nameZh, row.formID);
							}
							if (infoFilter) {
								++a_stats.infoHidden;
								continue;
							}
							break;
						case CondVerdict::kUnknown:
							++a_stats.infoUnknown;
							break;
						default:
							break;
						}
						}

						// ★★ 第 67 轮：链式门槛（「进度没到」的第三判据）—— 编号任务链的后续任务
						//   （CF02「菜鸟觐见」/ CF06「风驰电掣」这种）只能由前一个任务的收尾阶段自动
						//   开始；前置没做完时它们**根本接不到**，不该出现在「可接任务」里。
						//
						//   数据 = 官方 Papyrus 源码里的启动边（kChainGates；CF01 的 stage 1000
						//   fragment 里 `CF02.SetStage(10)` 那种，提取见 tools/esm/gen_quest_chain.py）。
						//   判据：全部启动边都还没触发 ⇒ 隐藏；任一条已触发 / 求值不了 ⇒ 放行（保守）。
						//   实机案例（玩家反馈）：存档没开深红舰队线，列表里却有 CF02 / CF06。
						if (info.chainCount) {
						++a_stats.chainGated;
						const auto chainGate = EvaluateChainGates(info.chainBegin, info.chainCount);
						switch (chainGate.verdict) {
						case CondVerdict::kPass:
							++a_stats.chainPassed;
							break;
						case CondVerdict::kFail:
							// ★★ 第 74 轮：同伴「入口」任务固定显示（判据同上，离线层有单测）。
							//   ★ 同伴线的**后续**任务（承诺任务）companionPin == 0 ⇒ 到这里
							//     照旧判「链式没到 ⇒ 隐藏」（玩家要求「后续任务不要显示」）；
							//     它们的启动边（好感度里程碑）见 gen_companion_quests.py。
							if (Decision::DecideGateAction(chainGate.verdict, pinned) ==
								Decision::GateAction::kPinBypass) {
								pinnedBypassed = true;
								break;
							}
							// 名单无条件记录（即使 ini 把过滤关了 —— 那是实机对照的对照物）。
							if (chainSampleCount < kMaxSamples) {
								++chainSampleCount;
								a_stats.chainSamples += std::format("{}[0x{:08X} {}] ",
									info.nameZh, row.formID, chainGate.detail);
							} else {
								// ★★ 第 79 轮：超出打印上限的条目不再静默丢弃（紧凑名单，见结构体说明）。
								//   本条就是「领先一步」被截掉的现场：43 条 kFail 只打得下 40 条，
								//   表内顺序最后的 3 条（通行是关键 / 全新的故事 / 领先一步）此前无声消失。
								++a_stats.chainOverflow;
								a_stats.chainOverflowSamples += std::format("{}[0x{:08X}] ",
									info.nameZh, row.formID);
							}
							if (chainFilter) {
								++a_stats.chainHidden;
								continue;
							}
							break;
						case CondVerdict::kUnknown:
							++a_stats.chainUnknown;
							break;
						default:
							break;
						}
						}

				// ★★ 第 74 轮（同伴好感度任务）：「入口」同伴任务固定显示 ——
				//   到这里说明它过了完成过滤、且没有被三类门槛藏掉（pinned ⇒ 门槛
				//   一律放行）；把统计与名单记下来（「固定显示」真的生效的证据）。
				// ★★ 第 75 轮（四大势力开头任务）：同一段统计，名单分成两份
				//   （「势力入口固定名单」/「同伴固定名单」），日志里一眼能分开。
				if (pinnedFaction) {
					++a_stats.factionPinned;
					if (pinnedBypassed) {
						++a_stats.factionGateMiss;
					}
					if (factionSampleCount < kMaxSamples) {
						++factionSampleCount;
						a_stats.factionSamples += std::format("{}[0x{:08X}{}{}] ",
							info.nameZh, row.formID,
							(info.factionEntry >= 0 &&
								static_cast<std::size_t>(info.factionEntry) < kFactionEntryCount)
								? std::format(" 势力={}", kFactionEntryNamesZh[info.factionEntry])
								: std::string{},
							pinnedBypassed ? " 跳过门槛" : "");
					}
				} else if (pinnedCompanion) {
					++a_stats.companionPinned;
					if (pinnedBypassed) {
						++a_stats.companionGateMiss;
					}
					if (companionSampleCount < kMaxSamples) {
						++companionSampleCount;
						a_stats.companionSamples += std::format("{}[0x{:08X}{}{}] ",
							info.nameZh, row.formID,
							(info.companion >= 0 &&
								static_cast<std::size_t>(info.companion) < kCompanionCount)
								? std::format(" 同伴={}", kCompanionNamesZh[info.companion])
								: std::string{},
							pinnedBypassed ? " 跳过门槛" : "");
					}
				}

						// ★ 第 20 轮：控制台测试过滤（`set SAQ_TestMode to N`，见 PassesTestFilter）。
				//   只影响显示，与上面的运行时过滤是「与」的关系。
				if (!PassesTestFilter(info, a_testMode)) {
					++a_stats.testFiltered;
					continue;
				}

				QuestEntry entry;
				entry.formID = row.formID;
				// ★★ 第 74 轮（同伴好感度任务）：界面据此在描述里提示「需要一定好感度
				//   才能接取」（载荷第 8 列）—— 固定显示的「入口」同伴任务才有这个标记。
				//   ★ 第 75 轮：只认同伴来源（势力开头任务不写这句 —— 它们的描述第一句
				//     是各自的「简要说明」，见下面的 noteZh/noteEn）。
				entry.companionPinned = pinnedCompanion;
				// ★★ 第 74 轮：同伴下标（只用于下面的列表排序 —— 同伴任务前置 + 分组）。
				entry.companion = info.companion;
				// ★★ 第 75 轮（四大势力开头任务）：下标（只用于排序 —— 固定排前四个）
				//   + 描述里的「简要说明」（载荷最后两列；只有这四条非空）。
				entry.factionEntry = info.factionEntry;
				if (info.factionEntry >= 0 &&
					static_cast<std::size_t>(info.factionEntry) < kFactionEntryCount) {
					entry.noteZh = kFactionEntryNotesZh[info.factionEntry];
					entry.noteEn = kFactionEntryNotesEn[info.factionEntry];
				}
				// ★★ 第 81 轮（地球地标任务）：说明文本的第二个来源 —— 这 10 条「雪景球」
				//   收集线的描述第一句 = 「去哪拿哪本书」（载荷最后两列）。两类互斥
				//   （factionEntry 与 landmark 不会同时 >= 0），这里排在势力之后只为次序。
				else if (info.landmark >= 0 &&
					static_cast<std::size_t>(info.landmark) < kLandmarkCount) {
					entry.noteZh = kLandmarkNotesZh[info.landmark];
					entry.noteEn = kLandmarkNotesEn[info.landmark];
				}
				// ★★ 第 89 轮（可重复任务）：说明文本的第三个来源 ——「（可重复）…」
				//   （做完一次后还能再接；描述第一句）。三类互斥，排在最后只为次序。
				else if (info.repeatable >= 0 &&
					static_cast<std::size_t>(info.repeatable) < kRepeatableCount) {
					entry.noteZh = kRepeatableNotesZh[info.repeatable];
					entry.noteEn = kRepeatableNotesEn[info.repeatable];
				}
				// ★★ 第 89 轮（可重复任务）：可重复标记（载荷第 11 列，见 SAQ_UI.cpp 的协议说明）
				//   —— AS3 侧 FilterKnownQuests 据此豁免「在玩家日志里」的丢弃。
				entry.repeatable = (info.repeatable >= 0);
				// ★ 第 65 轮（任务专属图标）：type 推真实任务类型（此前推 6「可接任务」
				//   统一值）—— 界面按它 + faction 选图标，与原版任务菜单一致。
				entry.type = info.type;
				// ★ 第 65 轮：阵营枚举（-1 = 无阵营）—— 势力任务的专属图标靠它。
				entry.faction = info.faction;
				// ★ 第 23 轮：把「有没有引导目标」也推给界面（能不能导航要看得见）
				// ★ 第 45 轮：判据换成候选池（candCount > 0 等价于旧 guideRefLocal != 0）。
				entry.hasGuideTarget = info.candCount != 0;
				// ★★ 第 46 轮（大项 B）：远处点引导会「点了暂时没反应」（待生效）的任务，
				//   界面据此在描述里**提前**告知玩家「靠近目标区域后才会自动生效」。
				//   ★ 第 47 轮曾放宽为「首选候选非常驻」；第 48 轮改回「**全部**候选都非常驻」
				//   —— 有常驻候选的任务远处点引导会落到常驻候选（立即生效），不需要提示。
				entry.needsApproach = AllCandidatesNonPersistent(info);
				entry.nameZh = info.nameZh;        // 中英都带上，AS3 侧按游戏语言挑
				entry.nameEn = info.nameEn;
				a_out.push_back(std::move(entry));
			}

			// 安全阀：虚表识别率太低 ⇒ 说明「0x114 这套判据在这台机器/这个版本上不成立」，
			// 那就**不过滤**（只把证据写进日志），免得凭错误的对象把整个列表清空。
			// ★ 第 64 轮（大项 K）：识别率计算与 80 的门槛在离线层（有单测）。
			a_stats.filterApplied = Decision::RuntimeFilterApplied(
				Decision::RecognizedPct(a_stats.recognized, a_stats.live));
			a_stats.hidden = a_stats.filterApplied ? hiddenByRuntime : 0;

			// ★ 第 27 轮：追加「无限任务入口」（任务板；第 80 轮起还有「（可重复）NPC」）
			//   条目（见 AppendEntryRows）。
			//   默认模式（0）与「只显示入口」模式（5）显示；其它测试模式 1~4 不加
			//   （那几种是任务筛选的测试，混进入口条目会干扰验证）。
			//   ★★ 第 96 轮：**移到排序之前** —— 入口条目属于 group 2（「其余」），
			//   先追加（输入在最后）+ 稳定排序 ⇒ 它们保持在本组非可重复任务之后、
			//   可重复任务（group 3）之前 ⇒ 列表末尾连成一片「（可重复）…」条目。
			if (a_testMode == 0 || entryOnly) {
				AppendEntryRows(a_out, a_stats);
			}

			// ★★ 第 74 轮（同伴好感度任务）：**把它们放在一起**（玩家要求：「同伴任务是
			//   不是都放在一起（我观察到任务板都是按顺序放在一起的），如果不是，把它们
			//   放在一起」）—— 同伴任务前置到列表开头，按同伴分组、同一位同伴的
			//   「入口」（个人任务）在「后续」（承诺任务）之前；其余任务保持原顺序
			//   （稳定排序 ⇒ 非同伴条目相对顺序不变）。
			// ★★ 第 75 轮（四大势力开头任务）：玩家要求「固定排在可接任务列表的**前四个**」
			//   ⇒ 这一组排在最前（排在同伴之前），组内按静态表下标 = 固定顺序
			//   （联合殖民地 → 自由星 → 龙神 → 深红舰队）。
			// ★★ 第 96 轮（可重复任务分组）：玩家要求「豁免『已完成』过滤的那些条目
			//   前面也加上（可重复）提示，然后一样把它们排列在一起（就像图里的
			//   （可重复）NPC 入口那样）」⇒ 可重复任务整组排到列表**末尾**（group 3；
			//   名称前缀在 AS3 侧加，见 MissionMenu.SaqRepeatablePrefix）。
			//   排序判据在离线层（Decision::PinnedOrderKey / PinnedOrderLess，有单测）；
			//   内嵌回退载荷（gen_quest_table.py::payload_order）与此**逐条同序**。
			//   排序在界面侧同样成立：载荷顺序 → BuildMergedList → InitializeEntries
			//   （`_loc2_` 正常段保持输入顺序）→ 我们的 tab 只看 bSaqAvailable 条目
			//   （运行期证据 = SAQ_Report 的 `order=` 探针：前 6 条 + 第 96 轮起的
			//   `|tail=` 末尾两行）。
			std::stable_sort(a_out.begin(), a_out.end(),
				[](const QuestEntry& a, const QuestEntry& b) {
					return Decision::PinnedOrderLess(
						Decision::PinnedOrderKey(a.factionEntry, a.companion,
							a.companionPinned ? 1u : 0u, a.repeatable),
						Decision::PinnedOrderKey(b.factionEntry, b.companion,
							b.companionPinned ? 1u : 0u, b.repeatable));
				});
			for (const auto& e : a_out) {
				if (e.factionEntry >= 0) {
					++a_stats.factionOrdered;     // 列表**最前**的势力开头任务数
				} else if (e.companion >= 0) {
					++a_stats.companionOrdered;   // 列表开头的同伴条目数（日志/用例证据）
				} else if (e.repeatable) {
					++a_stats.repeatableOrdered;  // ★★ 第 96 轮：列表**末尾**的可重复任务数
				}
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
				// ★★ 第 84 轮：切点回退到 UTF-8 字符边界 —— detail 里带中文文案/任务名，
				//   旧写法 `substr(0, 240)` 按字节切（与 EscapeForLog 是同一类病：
				//   切在汉字中间 ⇒ 非法 UTF-8）。
				REX::WARN("推送失败（重试）：{}… | 耗时 {} ms",
					detail.substr(0, Decision::Utf8SafeCut(detail, 240)), cost);
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
				"运行时状态：引擎存在={} 虚表识别={} 未识别={} 已开始={} 已完成={} 追踪中={} 隐藏={} 测试过滤={} 跳过(master未加载)={} 入口={}(可导航 {}｜marker {} 原板 {} 兜底 {} 不可用 {}) 过滤={}",
				a_stats.live, a_stats.recognized, a_stats.unrecognized,
				a_stats.started, a_stats.completed, a_stats.tracked, a_stats.hidden,
				a_stats.testFiltered,
				a_stats.skippedMaster,
				a_stats.entries,        // ★ 第 27 轮：任务板入口条目数
				a_stats.entryNavigable, // ★ 第 28 轮：其中引用当前可取（能导航）的条数
				// ★ 第 30 轮：能导航的里边，引导目标来自候选链的哪一档
				//   （marker = 新建常驻 XMarker，理想值 = 全部；见 AppendEntryRows）
				a_stats.entryByMarker, a_stats.entryByBoard, a_stats.entryByFallback,
				a_stats.entries - a_stats.entryNavigable,
				a_stats.filterApplied ? "生效" : "跳过(识别率<80%)");
			// ★ 第 35 轮：进度门槛统计（只在有门槛任务时打 —— 正常恒为 7 条）。
			//   `过` = 门槛全真显示；`藏` = 进度没到隐藏；`未知` = 求不了放行。
			if (a_stats.progressGated) {
				out += std::format(" 进度门槛={}(过{}/藏{}/未知{}",
					a_stats.progressGated, a_stats.progressPassed,
					a_stats.progressHidden, a_stats.progressUnknown);
				out += a_stats.progressFilterOff ? "｜过滤=ini关闭)" : ")";
			}
			if (!a_stats.progressSamples.empty()) {
				// 「进度没到」名单：玩家报「某条任务没显示」时，先在这里搜 FormID；
				// 每条后面括号里是**没通过的检查**（哪个任务是什么状态、期望什么）。
				out += " 进度没到: " + a_stats.progressSamples;
			}
			if (a_stats.progressOverflow) {
				// ★★ 第 79 轮：名单截断留痕（超出的条目以紧凑形式列出，见结构体说明）。
				out += std::format("（另有 {} 条未列出：{}）",
					a_stats.progressOverflow, a_stats.progressOverflowSamples);
			}
			// ★★ 大项 D（第 48 轮）：INFO 门槛（对话侧条件）的统计与名单。
			//   ★ 第 48 轮补丁：「放行」= 判「进度没到」但引擎已开始（引擎自启的任务
			//   玩家仍可能接到 ⇒ 不隐藏，见 CollectAvailableQuests 的注释）。
			if (a_stats.infoGated) {
				out += std::format(" INFO门槛={}(过{}/藏{}/放行{}/未知{}",
					a_stats.infoGated, a_stats.infoPassed,
					a_stats.infoHidden, a_stats.infoExempt, a_stats.infoUnknown);
				out += a_stats.infoFilterOff ? "｜过滤=ini关闭)" : ")";
			}
			if (!a_stats.infoSamples.empty()) {
				out += " INFO没到: " + a_stats.infoSamples;
			}
			if (a_stats.infoOverflow) {
				// ★★ 第 79 轮：名单截断留痕（超出的条目以紧凑形式列出，见结构体说明）。
				out += std::format("（另有 {} 条未列出：{}）",
					a_stats.infoOverflow, a_stats.infoOverflowSamples);
			}
			// ★★ 第 67 轮：链式门槛（编号任务链的启动边）的统计与名单。
			//   `过` = 至少一条启动边已触发 ⇒ 显示；`藏` = 全部启动边都没触发
			//   ⇒ 进度没到（前置任务没做，后续任务接不到）；`未知` = 求值不了 ⇒ 放行。
			//   名单里每条后面括号里是**没触发的前置**（哪个任务、哪个 stage 没完成）。
			if (a_stats.chainGated) {
				out += std::format(" 链式门槛={}(过{}/藏{}/未知{}",
					a_stats.chainGated, a_stats.chainPassed,
					a_stats.chainHidden, a_stats.chainUnknown);
				out += a_stats.chainFilterOff ? "｜过滤=ini关闭)" : ")";
			}
			if (!a_stats.chainSamples.empty()) {
				out += " 链式没到: " + a_stats.chainSamples;
			}
			if (a_stats.chainOverflow) {
				// ★★ 第 79 轮：名单截断留痕（超出的条目以紧凑形式列出，见结构体说明）——
				//   第 77 轮的 `assert.log 链式没到: .*领先一步[0x002C572B` 依赖的就是
				//   这一段（它是被 40 条上限截掉的 3 条之一，此前无声消失 ⇒ 断言不可达）。
				out += std::format("（另有 {} 条未列出：{}）",
					a_stats.chainOverflow, a_stats.chainOverflowSamples);
			}
			if (!a_stats.samples.empty()) {
				// 名单（第 11 轮起不只记前几条；★★ 第 79 轮起带截断留痕，上限 kMaxSamples）：
				// 玩家反馈「某条任务没显示」时，先在 `隐藏:` 这一段里搜 FormID ——
				// 在 = 被运行时状态挡住（看它后面括号里的状态）；不在 = 它已经被推送给 UI
				// （详见 AS3 侧的 `qdata=` 名单）。
				out += " 隐藏: " + a_stats.samples;
			}
			if (a_stats.hiddenOverflow) {
				// ★★ 第 79 轮：名单截断留痕（超出的条目以紧凑形式列出，见结构体说明）。
				out += std::format("（另有 {} 条未列出：{}）",
					a_stats.hiddenOverflow, a_stats.hiddenOverflowSamples);
			}
			if (!a_stats.vtableSamples.empty()) {
				out += " 未识别例: " + a_stats.vtableSamples;
			}
			if (!a_stats.entryUnavailable.empty()) {
				// ★ 第 29 轮：入口引用取不到 = 常驻化 override 没生效（正常应恒为空）
				out += " 入口不可导航: " + a_stats.entryUnavailable;
			}
			// ★★ 第 89 轮（可重复任务）：统计与「已完成但保留」名单 ——
			//   `已完成保留` = 本该被「只挡已完成」剔掉、因可重复豁免**留在列表里**的条数
			//   （这类任务做完一次还能再接，见 docs/11）。名单供玩家反馈时核对 FormID。
			if (a_stats.repeatableTotal) {
				// ★★ 第 96 轮（可重复任务分组）：追加「排在末尾」数 —— 玩家要求
				//   「一样把他们排列在一起（像图里的（可重复）NPC 入口）」；顺序本身
				//   见界面 `order=` 探针的 `|tail=` 段（末尾两行的 uID=显示名）。
				out += std::format(" 可重复任务={}(已完成保留{}｜排在末尾{})",
					a_stats.repeatableTotal, a_stats.repeatableKept,
					a_stats.repeatableOrdered);
			}
			if (!a_stats.repeatableSamples.empty()) {
				out += " 可重复保留: " + a_stats.repeatableSamples;
			}
			return out;
		}

		// ★★ 第 75 轮（四大势力开头任务）：**「固定显示」的两类条目单独一行**。
		//
		//   为什么拆行（而不是并进上面那行）：上面那行同时带着三类门槛的**名单**
		//   （`进度没到:` / `INFO没到:` / `链式没到:`）。而「固定显示」的条目按其定义
		//   **会被放行、不进那些名单** —— 但它们的名字（如「深藏不露」）会出现在这一行
		//   自己的名单里 ⇒ 如果两类名单同处一行，用例里的反向断言
		//   `assert.nolog 链式没到:.*深藏不露` 会**假命中**（正则跨字段匹配：`链式没到:`
		//   出现在后面的 `势力入口固定名单:` 之前）——「假 PASS / 假 FAIL」的又一形态，
		//   与「断言窗口 / 共享同一批行」那几条用例红线同一类纪律。
		//   返回空串 ⇒ 不打这一行（没有固定显示条目时零噪音）。
		std::string FormatPinStats(const RuntimeFilterStats& a_stats)
		{
			std::string out;
			// ★★ 第 74 轮：同伴好感度任务（「入口」固定显示）的统计与名单。
			//   「其中 N 条被门槛判『进度没到』但放行」= 固定显示真的起了作用的证据
			//   （否则这些任务会出现在上面那行的「进度没到 / INFO没到 / 链式没到」名单里）。
			//   名单里每条带所属同伴与「跳过门槛」标记；「后续」（承诺任务）不在这里
			//   —— 它们照旧走链式门槛（前置没到 ⇒ 出现在「链式没到」名单里）。
			if (a_stats.companionPinned) {
				out += std::format(" 同伴固定={}(其中{}条被门槛判「进度没到」但放行)",
					a_stats.companionPinned, a_stats.companionGateMiss);
			}
			// ★★ 第 74 轮：「把它们放在一起」—— 同伴条目被**前置**到列表开头（按同伴
			//   分组、入口在后续前）。这里的数字 = 列表开头连续的同条目数；界面侧的
			//   `order=` 探针给出**顺序本身**（SAQ_Report 报前几条的 uID）。
			if (a_stats.companionOrdered) {
				out += std::format(" 同伴分组前置={}(按同伴分组，入口在后续前)",
					a_stats.companionOrdered);
			}
			if (!a_stats.companionSamples.empty()) {
				out += " 同伴固定名单: " + a_stats.companionSamples;
			}
			// ★★ 第 75 轮（四大势力开头任务）：统计与名单（固定显示 + 固定排前四）。
			//   「其中 N 条被门槛判『进度没到』但放行」= 固定显示真的起了作用的证据
			//   —— 例如「深藏不露」的链式前置 UC02@860、「重返职场」的 INFO 门槛
			//   （名单里那条会带「跳过门槛」标记）。名单每条带势力名（任务名是官方名）。
			if (a_stats.factionPinned) {
				out += std::format(" 势力入口固定={}(其中{}条被门槛判「进度没到」但放行)",
					a_stats.factionPinned, a_stats.factionGateMiss);
			}
			//   固定顺序（玩家要求「固定排在可接任务列表的前四个」）：这里的数字 = 被前置
			//   到列表最前的势力条目数；`order=` 探针给出顺序本身（前四条应是这四个 uID）。
			if (a_stats.factionOrdered) {
				out += std::format(" 势力入口前置={}(固定顺序：联合殖民地→自由星→龙神→深红舰队)",
					a_stats.factionOrdered);
			}
			if (!a_stats.factionSamples.empty()) {
				out += " 势力入口固定名单: " + a_stats.factionSamples;
			}
			if (out.empty()) {
				return out;
			}
			return "固定显示（这两类条目跳过进度/INFO/链式三类门槛）：" + out;
		}

		// （第 17 轮删掉了「DNAM 位分布」那行诊断日志：它要回答的问题在 xEdit 的
		//   flag 名里已经有答案（位0 = Start Game Enabled），而这一位**不是**可用的
		//   「进度没到」判据（见 docs/99 第 10 轮），每次开菜单白刷一行。）

		// 定义在下面「引导」一节；这里前向声明（推送成功后要把当前引导同步给界面）。
		void SyncGuideStateToUi();

		// ★★★ 第 125 轮（路线 D · 冲突检测）：判定「UI 通道不可用」后请脚本给玩家
		//   一条 HUD 提示（GLOB `SAQ_UiNotice` = 1；脚本在菜单关闭后的轮询节拍里读到、
		//   提示 + 清 0，见 SAQ_Main.psc 的 ProcessUiChannelNotice）。
		//   进程内只请求一次（每次启动游戏最多一条 HUD 提示 —— 反复提示是骚扰）；
		//   旧 ESM 没有该 GLOB ⇒ 失败只记一行 WARN（判定与停推照常，不受影响）。
		void NotifyUiChannelDead()
		{
			if (g_uiNoticeSent) {
				return;
			}
			g_uiNoticeSent = true;
			std::string detail;
			if (Guide::SetUiNotice(1.0f, detail)) {
				REX::INFO("UI 通道提示已请求（脚本将在菜单关闭后提示玩家；进程内只请求一次）：{}", detail);
			} else {
				REX::WARN("UI 通道提示写入失败：{}（只影响这条 HUD 提示，不影响判定与停推）", detail);
			}
		}

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
				++g_pushCount;  // 计数（第 27 轮顺手消掉 C4189：原来赋给未使用的局部变量）
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

			// ★★★ 第 125 轮（路线 D · 冲突检测）：真失败时探测「界面是不是我们的 SWF」。
			//   第 2 次尝试起探测（第 1 次失败常常只是菜单刚创建、桥还没通）；
			//   定性 ours ⇒ 继续按退避重试（现状）；notOurs ⇒ 停推 + 提示玩家；
			//   unknown（桥还没通）⇒ 保持 unknown、下次失败再探（开销 = 一次缓存查询 + 一次 Invoke）。
			if (g_uiChannel == UI::ChannelIdentity::unknown && g_pending.attempts >= 2) {
				std::string probeDetail;
				const auto id = UI::ProbeChannelIdentity(probeDetail);
				if (id == UI::ChannelIdentity::ours) {
					g_uiChannel = UI::ChannelIdentity::ours;
					REX::INFO("UI 通道探测：界面是我们的 SWF（{}）—— 继续按退避重试（不是冲突）",
						probeDetail);
				} else if (id == UI::ChannelIdentity::notOurs) {
					g_uiChannel = UI::ChannelIdentity::notOurs;
					g_uiChannelDead = true;
					g_pending.quests.clear();
					g_pending.done = true;
					REX::WARN("UI 通道不可用（第 {} 次推送失败后判定）：任务菜单界面里没有在运行 "
							  "Show Available Quests 的界面（可能被其它修改 missionmenu.swf 的 mod 覆盖、"
							  "未安装或版本过旧）—— 本次菜单起停用界面推送（不再空转重试）。探测：{}",
						g_pending.attempts, probeDetail);
					NotifyUiChannelDead();
					return;
				}
			}

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

		// ★★ 第 42 轮：把 AS3 报告里的 `press=[…]` / `sel=[…]` 抄出来（诊断用，见 MissionMenu.as）。
		//
		//   为什么需要：玩家反馈「R 键的导航结果似乎不太稳定，有时候导航的目标似乎不是鼠标
		//   悬停的任务的目标」。此前日志里只有「引导请求：<任务名>」（= C++ 解析出的任务），
		//   没有办法区分两种可能：① 界面按键那一刻用的行**本来就不是**鼠标悬停的那条；
		//   ② 界面选对了，是后面的通道/脚本/星图环节错了。
		//   现在 AS3 会把「按键用的行（press）」与「列表选中项（sel）」都写进报告，
		//   这里抄进引导请求日志 —— 一次会话即可定性，不用再猜。
		//   取值：方括号包起来（任务名里可能有空格，不能按空格切），找不到给 "?"。
		std::string ExtractBracketField(std::string_view a_report, std::string_view a_key)
		{
			const std::string needle = std::string{ a_key } + "=[";
			const auto at = a_report.find(needle);
			if (at == std::string_view::npos) {
				return "?";
			}
			const auto begin = at + needle.size();
			const auto end = a_report.find(']', begin);
			if (end == std::string_view::npos) {
				return "?";
			}
			return std::string{ a_report.substr(begin, end - begin) };
		}

		// 现场读一次界面报告（不缓存）并拼成 `press=… sel=…`；桥不通就给一句话说明。
		std::string As3PressNote()
		{
			std::string report;
			if (!UI::ReadUiReport(report)) {
				return "press=? sel=?（界面报告读不到）";
			}
			return std::format("press={} sel={}",
				ExtractBracketField(report, "press"), ExtractBracketField(report, "sel"));
		}

		void PollUiReport()
		{
			// ★★★ 第 125 轮（路线 D）：已判定「界面不是我们的」⇒ 别再每 500ms 空调一次
			if (g_uiChannelDead) {
				return;
			}
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
			std::uint32_t verifyTries{};   // 菜单**关着**时的确认次数（菜单开着不计数，第 26 轮）
			std::uint32_t verifySeq{};     // 这次确认对应的请求序号（防止和自我重试打架）
			std::uint32_t verifyResends{}; // 状态 2/3 的重发次数（≤2；第 26 轮改为独立计数）
			// ★ 第 27 轮：「菜单还开着，脚本不会响应」的说明是否已打过 —— **每菜单一次**。
			//   第 26 轮是「每请求一次」，实测 27 秒内切换 12 条条目会打 9 行（纯噪声）：
			//   既然已实锤「菜单开着时脚本不可能响应」（第 27 轮结论，见 PollGuideVerify），
			//   每菜单留一行说明就够。在 OnMissionMenuOpened 里重置。
			bool          verifyWaitNoted{};
			// ★ 第 31 轮：这次下发是「入口目标的静默更新」（玩家没操作，见 UpdateEntryGuideTarget）。
			//   确认超时/失败时**不清通道、不回写界面** —— 否则会把玩家原本可用的引导一起清掉。
			bool          verifySilent{};
			std::uint64_t lastTargetCheckMs{};   // 入口目标复算的节流时间戳（第 31 轮）
			// ---- 第 32 轮：菜单关着时的例行认领/对账（见 PollGuideUpkeep）----
			//   玩家重启游戏后直接读档看 HUD（不进菜单）是常态：此时 DLL 必须自己把
			//   通道里遗留的引导认领回来，动态更新才有机会把蓝点挪到板上。
			std::uint32_t adoptWarnRef{};      // 「认不出的通道目标」已 WARN 过的值（同一目标只刷一次）
			std::uint64_t upkeepMs{};          // 例行认领/对账的节流时间戳（第 32 轮）
			// ★ 第 48 轮：认领后的**复算宽限期**（见 kAdoptGraceMs）——
			//   实测（20:42 会话）：读档瞬间 `LookupByID` 对还没加载完的引用返回 null，
			//   「候选复算」据此把目标从 NPC 误降级到同 cell 兜底，10 秒后又升回去。
			//   宽限期内不复算（目标保持通道里的原值，等引擎稳定）。
			std::uint64_t adoptGraceUntilMs{};
			// ★ 第 49 轮补丁：候选**降级观察期**（见 kDowngradeHoldMs）——
			//   宽限期只兜「认领后的头 8 秒」；实测（21:57 会话）读档加载更久，
			//   宽限期一到就复算、仍取不到 ⇒ 还是误降级到兜底、10 秒后又升回。
			//   现在：当前候选取不到时先进入观察（通道完全不动），持续
			//   kDowngradeHoldMs 仍取不到才执行降级；任何一次「取得到」都清掉观察。
			std::uint64_t downgradeSinceMs{};  // 观察开始时间（0 = 没在观察）
			// ★ 第 45 轮：候选池 —— 当前引导用的是第几个候选（0-based，列表按质量排序）。
			//   「脚本报状态 2（取不到）」时换下一个（循环）；菜单关着时还会定期复算
			//   「有没有更优的候选变得可用了」（见 UpdateQuestGuideTarget）。
			std::uint8_t  candIndex{};         // 入口条目不用（它的候选链在 EvaluateEntryGuide 里）
			std::uint32_t candSwitches{};      // 本次引导换过多少次候选（日志/诊断用）
			// ---- ★★ 第 46 轮（大项 B）：引导「待生效」（目标尚未加载）----
			//   点引导那一刻所有候选都取不到 ⇒ 不再 19 秒后静默放弃，而是：
			//     ① 界面回写结果码 5（保持竖条 + note 写明原因，不播 OFF 音、不回滚）；
			//     ② 脚本侧发一次 HUD 提示（「目标地点尚未加载，靠近后自动生效」）；
			//     ③ 菜单关着时按**退避**慢速重试（10/20/40/60 秒…），目标 cell 一加载
			//        就会生效（蓝点自动出现）—— 见 PollApproachRetry。
			bool          approachPending{};    // 正在等「目标加载」（只有普通任务会置位）
			std::uint32_t approachTries{};      // 已重试次数（到 kApproachMaxTries 后停手，引导仍保持）
			std::uint64_t approachRetryAtMs{};  // 下一次重试的时间点
		};
		GuideRuntime g_guide;
		constexpr std::uint64_t kGuidePollIntervalMs = 100;
		constexpr std::uint64_t kGuideVerifyFirstMs = 900;   // 下发后第一次查状态的时间
		constexpr std::uint64_t kGuideVerifyRetryMs = 2000;  // 之后每次重查的间隔
		constexpr std::uint32_t kGuideVerifyMaxTries = 6;    // 最多查这么久（≈ 11 秒）
		constexpr std::uint64_t kEntryTargetCheckMs = 1500;  // 入口引导目标复算间隔（第 31 轮）
		// ★ 第 48 轮：认领已有引导后的复算宽限期 —— 读档/开局瞬间引擎查询不稳定，
		//   立即复算会把目标误降级（实测例：补给之行 [1]NPC → [3]兜底 → 10 秒后又升回）。
		constexpr std::uint64_t kAdoptGraceMs = 8000;
		// ★ 第 49 轮补丁：候选**降级观察期** —— 当前候选取不到时不立刻降级，先保持
		//   这么久（通道完全不动、界面上「正在引导」不变）。20 秒的依据：21:57 会话实测
		//   读档后目标持续取不到 ≈19 秒才恢复；而真正的「飞远」场景里目标 cell 卸载后
		//   候选**多半全不可得**（复算本来就不会降级，见 UpdateQuestGuideTarget）⇒
		//   拉长观察期几乎不损失功能，换掉读档窗口里「8 秒宽限期之后」仍会发生的
		//   [1]→[3]→[1] 抖动（日志 WARN + 蓝点闪动）。
		constexpr std::uint64_t kDowngradeHoldMs = 20000;
		constexpr std::uint64_t kUpkeepIntervalMs = 2000;    // 菜单关着时例行认领/对账间隔（第 32 轮）
		// ★ 第 46 轮：引导「待生效」（目标尚未加载）的退避重试参数（见 PollApproachRetry）。
		constexpr std::uint64_t kApproachRetryFirstMs = 10000;  // 第一次重试：10 秒
		constexpr std::uint64_t kApproachRetryMaxMs   = 60000;  // 之后最多每 60 秒一次
		constexpr std::uint32_t kApproachMaxTries     = 40;     // 约 35 分钟后停手（引导保持）

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

		// ==================================================================
		// ★★ 第 45 轮：候选池（每条任务一个按质量排序的引导目标列表）
		//
		//   静态表 kGuideCandidates[] + StaticQuestInfo.candBegin/candCount（生成器见
		//   tools/esm/gen_quest_table.py）。四个用法：
		//     ① 点引导时 `PickGuideCandidate` 挑「此刻可得的、质量最优的」（一次到位，
		//        玩家在远处时不会先去撞一个取不到的非常驻 NPC）；
		//     ② 脚本报「状态 2 = 取不到」时 `SwitchGuideCandidate` 换下一个（循环）；
		//     ③ 菜单关着时 `UpdateQuestGuideTarget` 定期复算（飞近了自动升级回 NPC）；
		//     ④ 认领已有引导时遍历候选池（通道里的目标可能是第 2/3 个候选）。
		//
		//   「可得」判据 = `TESForm::LookupByID` 查得到 —— 与脚本的 Game.GetForm 是
		//   同一个引擎查询；入口条目的候选链（第 31 轮）已实测：非持久引用在所在
		//   cell 未加载时这里也查不到（「原板」只在走进那个 cell 后才命中）。
		// ==================================================================
		// ★ 第 46 轮：候选 flags 的位定义（与 SAQ_QuestTable.h / gen_guide_targets.py 一致）。
		//   ★ 第 64 轮（大项 K）：位定义移到离线层（Decision::kCandidateFlagPersistent）。
		//   候选池每条任务最多几个：生成器是「质量 top 6 + 最多 2 个常驻备胎」= 8，
		//   这里放宽到 16（离线层 API 用固定数组收集，超限截断 —— 由 verify 的表检查兜底）。
		constexpr std::size_t kMaxCandidatesPerQuest = 16;

		const StaticGuideCandidate* CandidateAt(const StaticQuestInfo& a_info, std::uint8_t a_index)
		{
			const auto slot = static_cast<std::size_t>(a_info.candBegin) + a_index;
			return (a_index < a_info.candCount && slot < kGuideCandidateCount)
				? &kGuideCandidates[slot]
				: nullptr;
		}

		std::uint32_t CandidateFormID(const StaticQuestInfo& a_info, std::uint8_t a_index)
		{
			const auto* c = CandidateAt(a_info, a_index);
			return c ? Masters::MakeFormID(c->refrMaster, c->refrLocal) : 0;
		}

		const char* CandidateName(const StaticQuestInfo& a_info, std::uint8_t a_index)
		{
			const auto* c = CandidateAt(a_info, a_index);
			return c ? c->nameZh : "";
		}

		bool CandidateAlive(const StaticQuestInfo& a_info, std::uint8_t a_index)
		{
			const auto id = CandidateFormID(a_info, a_index);
			return id != 0 && RE::TESForm::LookupByID(static_cast<RE::TESFormID>(id)) != nullptr;
		}

		// 挑「此刻可得的、质量最优的」候选（列表已按质量排序 ⇒ 第一个可得的即最优）。
		// a_anyAlive = 是否有任何一个候选此刻可得；全不可得时返回 0 —— 调用方照常写
		// 第一候选：脚本会报状态 2，随后由换候选 / 等玩家靠近后的重发兜底。
		std::uint8_t PickGuideCandidate(const StaticQuestInfo& a_info, bool& a_anyAlive)
		{
			// ★ 第 64 轮（大项 K）：选择逻辑在离线层（Decision::PickCandidate，有单测）——
			//   这里只做「逐个候选问引擎可得性」＋装数组。
			bool alive[kMaxCandidatesPerQuest]{};
			const auto n = std::min<std::size_t>(a_info.candCount, kMaxCandidatesPerQuest);
			for (std::size_t i = 0; i < n; ++i) {
				alive[i] = CandidateAlive(a_info, static_cast<std::uint8_t>(i));
			}
			const auto pick = Decision::PickCandidate(std::span<const bool>(alive, n));
			a_anyAlive = pick.anyAlive;
			return pick.index;
		}

		// ★★ 第 46 轮（大项 B）／第 48 轮（定稿）：「需要靠近」判定 —— 这条任务的候选池里
		//   **一个常驻候选都没有** ⇒ 玩家在远处（目标的 cell 没加载）时全部取不到，
		//   引导进入「待生效」链路（结果码 5 + HUD 提示 + 退避重试），必须靠近才能看到标记。
		//
		//   为什么不用「首选候选非常驻」（第 47 轮的判据）：实测 209 条有目标的任务里
		//   158 条命中 ⇒ 描述提示 + 测试模式 6 覆盖 76% 的任务，而其中 138 条
		//   （首选非常驻、但池里有常驻候选/兜底）在远处点引导会**立即落到常驻候选**、
		//   只是位置未必最精确，靠近后由「候选复算」自动升级 —— 玩家侧有即时反馈，
		//   不需要（也不该）提前警告，否则真会「没反应」的那 20 条反而被淹没。
		//
		//   用途：① 推给界面，在描述里**提前**告知（MissionMenu 的 bSaqNeedsApproach）；
		//         ② 点引导且全不可得时走「保持待生效 + 慢速重试 + HUD 提示」
		//            （不安排 19 秒超时判定）而不是静默放弃。
		//   数据来源 = StaticGuideCandidate.flags bit0（离线由持久位算出）。
		bool AllCandidatesNonPersistent(const StaticQuestInfo& a_info)
		{
			if (a_info.candCount == 0) {
				return false;  // 没有目标：那是「暂无导航目标」，与「需要靠近」是两回事
			}
			// ★ 第 64 轮（大项 K）：判定在离线层（Decision::AllCandidatesNonPersistent，
			//   有单测）—— 这里只收集候选 flags；槽位异常按「常驻」传入（保守）。
			std::uint8_t flags[kMaxCandidatesPerQuest]{};
			const auto n = std::min<std::size_t>(a_info.candCount, kMaxCandidatesPerQuest);
			for (std::size_t i = 0; i < n; ++i) {
				const auto* c = CandidateAt(a_info, static_cast<std::uint8_t>(i));
				flags[i] = (!c || (c->flags & Decision::kCandidateFlagPersistent) != 0)
					? Decision::kCandidateFlagPersistent
					: 0;
			}
			return Decision::AllCandidatesNonPersistent(std::span<const std::uint8_t>(flags, n));
		}

		// ★ 第 45 轮：换候选（定义在下方 ReissueGuideIfScriptLost 之前）——
		//   这里先声明：PollGuideVerify（早于定义）用它做「状态 2 ⇒ 换下一个候选」。
		bool SwitchGuideCandidate(const StaticQuestInfo& a_info, std::string_view a_reason);

		// ★ 第 17 轮：反向查（运行期 FormID -> 静态行）。用于「DLL 刚启动/刚读档，而
		//   ESM 通道里还留着上一次会话设的引导」——把那条任务认领回来（见 AdoptExistingGuide）。
		//   ★ 第 45 轮：遍历**候选池**（通道里的目标可能是第 2/3 个候选），出参带上下标。
		const StaticQuestInfo* FindQuestByGuideRef(std::uint32_t a_guideRefID, std::uint8_t& a_outIndex)
		{
			a_outIndex = 0;
			for (const auto& row : g_runtimeRows) {
				const auto& info = *row.info;
				for (std::uint8_t i = 0; i < info.candCount; ++i) {
					if (CandidateFormID(info, i) == a_guideRefID) {
						a_outIndex = i;
						return &info;
					}
				}
			}
			return nullptr;
		}

		// ★ 第 30 轮：入口下标（按界面 uID 找；找不到 ⇒ kEntryTableSize）。
		std::size_t FindEntryIndexByFormID(std::uint32_t a_formID)
		{
			for (std::size_t i = 0; i < kEntryTableSize; ++i) {
				const auto& e = kEntryTable[i];
				if (Masters::MakeFormID(e.master, e.refLocal) == a_formID) {
					return i;
				}
			}
			return kEntryTableSize;
		}

		// ★ 第 27 轮：入口条目（任务板）反查 —— 条目的 uID 就是任务板引用的运行期 FormID。
		const StaticEntryInfo* FindEntryByFormID(std::uint32_t a_formID)
		{
			const auto i = FindEntryIndexByFormID(a_formID);
			return i < kEntryTableSize ? &kEntryTable[i] : nullptr;
		}

		// ★ 第 30 轮：按「引导目标候选」反查入口 —— 「认领已有引导」用（见 AdoptExistingGuide）。
		//   候选 = 新建常驻 marker（前缀来自 Guide 通道）或同 cell 常驻兜底引用。
		std::size_t FindEntryIndexByGuideCandidate(std::uint32_t a_id)
		{
			if (a_id == 0) {
				return kEntryTableSize;
			}
			const auto ch = Guide::EnsureChannel();
			const std::uint32_t markerPrefix = (ch.resolved && ch.prefix <= 0xFF) ? (ch.prefix << 24) : 0;
			for (std::size_t i = 0; i < kEntryTableSize; ++i) {
				const auto& e = kEntryTable[i];
				if (e.markerLocal && markerPrefix && (markerPrefix | e.markerLocal) == a_id) {
					return i;
				}
				if (e.fallback1 && Masters::MakeFormID(0, e.fallback1) == a_id) {
					return i;
				}
				if (e.fallback2 && Masters::MakeFormID(0, e.fallback2) == a_id) {
					return i;
				}
			}
			return kEntryTableSize;
		}

		// 引导相关日志的显示名（任务 / 入口条目 / 未知）—— 日志里永远给人看得懂的名字。
		std::string_view DisplayNameOf(std::uint32_t a_formID)
		{
			if (const auto* q = FindStaticQuest(a_formID)) {
				return q->nameZh;
			}
			if (const auto* e = FindEntryByFormID(a_formID)) {
				return e->nameZh;
			}
			return "?";
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
			// 目标所在地：只有任务表里有这个字段（入口条目没有 —— 显示空串）。
			// ★ 第 45 轮：带候选下标/名字（「现在用的是第几个候选」一眼可见）。
			const auto* quest = FindStaticQuest(g_guide.questFormID);
			const std::string candNote = (quest && quest->candCount)
				? std::format("（候选 [{}]「{}」/ 共 {}）", g_guide.candIndex + 1u,
					  CandidateName(*quest, g_guide.candIndex), quest->candCount)
				: std::string{};
			REX::INFO("引导状态：{}（0x{:08X}）目标引用=0x{:08X}{} {}｜脚本状态={:.0f}"
					  "（0 待处理 / 1 已应用 / 2 取不到 / 3 已清除 / 4 别名不存在）{}",
				DisplayNameOf(g_guide.questFormID), g_guide.questFormID, g_guide.guideRef,
				candNote, quest ? quest->whereZh : "", scriptState,
				// ★ 第 46 轮：这条引导是「点的时候目标还没加载、等靠近」的那一类
				g_guide.approachPending
					? std::format("｜待生效：目标尚未加载（已重试 {} 次）", g_guide.approachTries)
					: std::string{});
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
		// ★ 第 27 轮：不再重置 verifyWaitNoted（「菜单还开着」说明是**每菜单一次**，
		//   由 OnMissionMenuOpened 重置 —— 否则每次切条目都会重新打一行）。
		void ScheduleGuideVerify(int a_seq)
		{
			g_guide.verifyAtMs = NowMs() + kGuideVerifyFirstMs;
			g_guide.verifyTries = 0;
			g_guide.verifySeq = static_cast<std::uint32_t>(a_seq);
			g_guide.verifyResends = 0;
			g_guide.verifySilent = false;   // 玩家请求：失败要回滚界面（静默更新会自己再设 true，见下）
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

		// ★★ 第 37 轮：「设定航线（R）」的**星图**这一半。
		//
		// 玩家反馈：可接任务里按 R 只有「选中条目」的效果；原版任务按 R 会打开星图、
		// 展示目标所在星球并询问是否导航。第 36 轮试着把**代理任务**交给原版的
		// `MissionMenu_PlotToLocation` 流程（AS3 dispatch），实测**引擎没有任何反应**——
		// 离线复核给出了原因（见 docs/05 第十一节）：
		//   `BSTGlobalEvent::EventSource<MissionMenu_PlotToLocation>` 这个事件源在整个
		//   exe 里**只有它自己的静态初始化**引用它（`ref/MissionMenu` 探针：单例
		//   0x5F31A30 的 5 处引用全在初始化函数里），也就是说**没有任何 C++ sink**
		//   —— dispatch 出去的事件没人处理（MissionMenu_ShowItemLocation /
		//   MissionMenu_ToggleTrackingQuest / DataMenu_PlotToLocation 三个事件同样如此）。
		//   ⇒ 这条「照抄原版」的路走不通，只能我们自己调用引擎的原生能力。
		//
		// 引擎原生 API（Papyrus，`Data\Scripts\Source\Base\Game.psc`）：
		//   `Game.ShowGalaxyStarMapMenuAndPlotToLocation(Location aLocation)`
		//   —— 打开星图 + 把航线画到那个地点（原版 SET COURSE 的同款能力）。
		//
		// 为什么必须由**脚本**来调（DLL 不能直接调）：
		//   * 这是一条 Papyrus 原生函数，从 DLL 直接调要么自己伪造 VM 栈帧（风险高），
		//     要么走 VM 的 DispatchStaticCall（星图相关的参数/句柄构造同样没实证）；
		//   * Papyrus 侧只要一行：`Game.ShowGalaxyStarMapMenuAndPlotToLocation(loc)`，
		//     而且引导目标引用本来就在脚本手里（别名 ForceRefTo 的那一个）。
		//
		// 为什么由 DLL **关菜单**来触发（而不是等玩家自己关）：
		//   第 27 轮实测定案：任务菜单开着时 Papyrus 定时器不走 ⇒ 脚本只能在
		//   「菜单关闭」事件里跑（引导也是那一刻应用的）。玩家按 R 之后必须立刻离开
		//   菜单，脚本才有机会打开星图 —— 所以这里用引擎自己的 UI 消息
		//   （kHide）把任务菜单关掉，脚本随即在关闭事件里：
		//     ① 应用引导（蓝点/路径线，原有链路）；
		//     ② 看到 SAQ_GuideState == 5 ⇒ 调上面的原生函数打开星图。
		//   体验上等价于原版：按 R ⇒ 星图出现并画好航线。
		//
		// 判据（下一轮日志）：`星图：已请求关闭任务菜单` → 脚本 `[SAQ] 星图请求：<地点>`
		//   → 本文件的 `星图：已打开（GalaxyStarMapMenu 在屏幕上）`（或没打开的 WARN）。
		// ==================================================================
		// ★ 第 40 轮：星图诊断 —— 引擎自己的「地点 → 星图节点」解析器（RVA 0xAC2AB0）。
		//
		//   为什么需要它：玩家反馈「R 能打开星图，但所有任务都指到沃利阿尔法星」。离线复核
		//   （docs/05）证明：引擎的 `ShowGalaxyStarMapMenuAndPlotToLocation`（0x2010210）
		//   第一步就是 `0xac2ab0(&node, 地点)`，node 会原样进 UI 消息载荷，星图靠它定位；
		//   同一个解析器也是 `Location.GetCurrentPlanet()` 的实现（0x1FEACE0：解析结果必须
		//   是 PNDT(0xBA) 记录，否则返回 null）—— 所以它可以直接当判据：
		//      节点 != 0 ⇒ 引擎认得这个地点（星图能定位到它对应的行星）
		//      节点 == 0 ⇒ 引擎不认这个地点 ⇒ 星图只会按「当前位置」打开（玩家看到的现象）
		//
		//   这些函数**只读、只写日志**：不改任何行为，玩家再报「指错星球」时拿它定性。
		//   调用约定（与 0x2010210 / 0x1FEACE0 一致）：rcx = 8 字节出参缓冲，rdx = 地点表单。
		// ==================================================================
		constexpr std::uintptr_t kResolveNodeRva = 0xAC2AB0;
		// 函数头 8 字节: mov r11,rsp (4C 8B DC) / mov [r11+0x20],rbx (49 89 5B 20) / push rbp (55)
		//   ★ 第 41 轮修正：第 40 轮把 `mov r11,rsp` 的机器码抄成了 `4C 89 1C 24`
		//   （那是 `mov [rsp],r11` —— 方向抄反），导致运行时特征校验永远失败，
		//   日志里全是「节点解析器不可用：游戏版本特征不符」，这一路诊断形同虚设。
		//   复现：python tools/re/dis_range.py 0xac2ab0 0xac2ae0
		constexpr std::array<std::uint8_t, 8> kResolveNodeSig{
			0x4C, 0x8B, 0xDC, 0x49, 0x89, 0x5B, 0x20, 0x55
		};

		using ResolveNodeFn = void(__fastcall*)(void*, void*);

		// ★ 特征校验与调用都必须放在**纯 POD 函数**里（MSVC 的 __try 不能与需要析构展开的
		//   对象共存 —— 本项目已踩过，见 SAQ_QuestState.cpp 的注释）。
		void* ProbeResolveNodeFn()
		{
			__try {
				const auto base = reinterpret_cast<std::uintptr_t>(::GetModuleHandleW(nullptr));
				if (!base) {
					return nullptr;
				}
				const auto* p = reinterpret_cast<const std::uint8_t*>(base + kResolveNodeRva);
				for (std::size_t i = 0; i < kResolveNodeSig.size(); ++i) {
					if (p[i] != kResolveNodeSig[i]) {
						return nullptr;
					}
				}
				return const_cast<std::uint8_t*>(p);
			} __except (EXCEPTION_EXECUTE_HANDLER) {
				return nullptr;
			}
		}

		bool PODResolveNode(void* a_fn, void* a_out, void* a_loc)
		{
			__try {
				reinterpret_cast<ResolveNodeFn>(a_fn)(a_out, a_loc);
				return true;
			} __except (EXCEPTION_EXECUTE_HANDLER) {
				return false;
			}
		}

		bool PODFormID(const void* a_form, std::uint32_t& a_out)
		{
			__try {
				a_out = static_cast<const RE::TESForm*>(a_form)->GetFormID();
				return true;
			} __except (EXCEPTION_EXECUTE_HANDLER) {
				return false;
			}
		}

		bool PODParentLocation(const void* a_loc, void*& a_out)
		{
			__try {
				a_out = static_cast<const RE::BGSLocation*>(a_loc)->parentLocation.get();
				return true;
			} __except (EXCEPTION_EXECUTE_HANDLER) {
				return false;
			}
		}

		bool PODCurrentLocation(void* a_ref, void*& a_out)
		{
			__try {
				a_out = static_cast<RE::TESObjectREFR*>(a_ref)->GetCurrentLocation();
				return true;
			} __except (EXCEPTION_EXECUTE_HANDLER) {
				return false;
			}
		}

		bool PODEditorLocation(void* a_ref, void*& a_out)
		{
			__try {
				a_out = static_cast<RE::TESObjectREFR*>(a_ref)->GetEditorLocation();
				return true;
			} __except (EXCEPTION_EXECUTE_HANDLER) {
				return false;
			}
		}

		bool PODPlayerLocation(void*& a_out)
		{
			__try {
				auto* player = RE::PlayerCharacter::GetSingleton();
				a_out = player ? player->GetCurrentLocation() : nullptr;
				return true;
			} __except (EXCEPTION_EXECUTE_HANDLER) {
				return false;
			}
		}

		// 「地点 → 星图节点」一行（节点 + 第二个出参）。取不到就写原因。
		std::string StarMapNodeOf(void* a_loc)
		{
			if (!a_loc) {
				return "（地点为空）";
			}
			static void* s_fn = ProbeResolveNodeFn();
			if (!s_fn) {
				return "（节点解析器不可用：游戏版本特征不符）";
			}
			std::uint32_t buf[2]{};
			if (!PODResolveNode(s_fn, buf, a_loc)) {
				return "（节点解析调用异常）";
			}
			return std::format("节点=0x{:08X}｜标记=0x{:08X}{}",
				buf[0], buf[1], buf[0] ? "" : "（未命中：星图不会定位到这个地点）");
		}

		// ★★ 第 45 轮补丁：这一层地点能不能解析出星图节点（三态）——
		//   kUnknown = 判不了（地点为空 / 节点解析器特征不符 / 调用异常）⇒ 不参与判定；
		//   kMiss    = 解析成功但节点 = 0（星图不会定位到这个地点）；
		//   kHit     = 节点非 0（星图能定位）。
		//   用途：LogStarMapDiagnosis 统计「地点链全层都 Miss」= 目标不在星图上。
		enum class NodeProbe : std::uint8_t { kUnknown, kMiss, kHit };

		NodeProbe StarMapNodeProbe(void* a_loc)
		{
			if (!a_loc) {
				return NodeProbe::kUnknown;
			}
			static void* s_fn = ProbeResolveNodeFn();
			if (!s_fn) {
				return NodeProbe::kUnknown;
			}
			std::uint32_t buf[2]{};
			if (!PODResolveNode(s_fn, buf, a_loc)) {
				return NodeProbe::kUnknown;
			}
			return buf[0] ? NodeProbe::kHit : NodeProbe::kMiss;
		}

		// ★★ 第 45 轮补丁：`星图诊断` 的结论 —— 地点链（含父链）**全层节点都 = 0**，
		//   即「目标位置不在星图上」（飞船内部 / 引擎动态创建的内部地点，实测例：
		//   `MS03JunoShip_CreatedInteriorLocationDungeon`——「朱诺的计谋」的目标）。
		//   脚本此时**不打开星图**、改发 HUD 提示（脚本侧补丁，见 SAQ_Main.psc 的
		//   OpenStarMapFor）⇒ CheckStarMapOpened 据此**不重试**、超时文案改成如实的
		//   「按预期未打开」（否则会打一条误导的 WARN + 让脚本重复发通知）。
		//   每次诊断重算（LogStarMapDiagnosis 开头清零）。
		bool g_starMapDiagAllMiss{};

		// ★ 第 40 轮：星图诊断（每次按 R 记一次）——把「引导引用所在的地点链」逐层解析。
		//   引擎认哪一层 = 星图该用哪一层（脚本会把「行星自己的地点」优先传给原生函数）。
		void LogStarMapDiagnosis(const char* a_why)
		{
			const auto refID = g_guide.guideRef;
			if (refID == 0) {
				return;
			}
			g_starMapDiagAllMiss = false;  // ★ 第 45 轮补丁：每次诊断重算
			auto* form = RE::TESForm::LookupByID(refID);
			auto* refr = form ? form->As<RE::TESObjectREFR>() : nullptr;
			if (!refr) {
				REX::INFO("星图诊断（{}）：引导引用 0x{:08X} 取不到（所在格子没加载）", a_why, refID);
				return;
			}
			void* loc = nullptr;
			const char* kind = "当前地点";
			if (!PODCurrentLocation(refr, loc) || !loc) {
				kind = "编辑地点";
				if (!PODEditorLocation(refr, loc) || !loc) {
					REX::INFO("星图诊断（{}）：引用 0x{:08X} 的当前/编辑地点都是空"
							  "（脚本会在请求时自己找地点）",
						a_why, refID);
					return;
				}
			}
			bool anyHit = false;    // 有任意一层能解析出节点（星图能定位）
			bool anyKnown = false;  // 有任意一层的节点解析是「可用且成功」的（能下判定）
			for (int depth = 0; depth <= 3; ++depth) {
				std::uint32_t fid = 0;
				if (!PODFormID(loc, fid)) {
					break;
				}
				const auto probe = StarMapNodeProbe(loc);
				anyKnown = anyKnown || probe != NodeProbe::kUnknown;
				anyHit = anyHit || probe == NodeProbe::kHit;
				REX::INFO("星图诊断（{}）：地点链[{}]{}＝0x{:08X}｜{}", a_why, depth,
					depth == 0 ? kind : "父地点", fid, StarMapNodeOf(loc));
				void* parent = nullptr;
				if (!PODParentLocation(loc, parent) || !parent || parent == loc) {
					break;
				}
				loc = parent;
			}
			// ★ 第 45 轮补丁：全层都显式解析为「未命中」⇒ 目标位置不在星图上。
			//   （没有一层能下判定（解析器不可用等）时保持 false —— 那是真失败，照旧 WARN。）
			g_starMapDiagAllMiss = anyKnown && !anyHit;
			if (g_starMapDiagAllMiss) {
				REX::INFO("星图诊断（{}）：地点链全层节点=0 —— 目标位置不在星图上"
						  "（飞船内部/动态创建的内部地点），脚本将改发 HUD 提示（不打开星图）",
					a_why);
			}
			void* playerLoc = nullptr;
			if (PODPlayerLocation(playerLoc) && playerLoc) {
				std::uint32_t fid = 0;
				PODFormID(playerLoc, fid);
				REX::INFO("星图诊断（{}）：玩家所在地点＝0x{:08X}（对照：星图若「站在原地」就是这个）",
					a_why, fid);
			}
		}

		struct StarMapProbe
		{
			bool          pending{};      // 已发出「关菜单 + 开星图」请求，等验证
			std::uint64_t startMs{};      // 请求时刻（用来算「R 后多少秒星图才出现」）
			std::uint64_t midCheckMs{};   // 中途那次「菜单状态」日志的时间点
			std::uint64_t deadlineMs{};   // 到点还没开就 WARN
			bool          midLogged{};    // 中途日志只打一次
			// ★ 第 38 轮：界面侧会自己走原版的「退回游戏」路径关掉**整个**暂停菜单。
			bool          closedBySwf{};
			std::uint32_t questID{};      // 请求时的引导任务（日志用）
			// ★ 第 40 轮：**自动重试**。16:28 会话的实测：脚本在「菜单关闭」后 0.5 秒就调了
			//   原生函数，而那一刻暂停菜单还在关（关闭动画/收尾）⇒ 星图**根本没开**，
			//   12 秒窗口内一次都没出现过（当时误查 MapMenu —— 第 41 轮已更正为
			//   GalaxyStarMapMenu，见 StarMapMenuName()）。而第 38 轮那三次
			//   「星图开了但要等好久」的会话里，脚本调用发生在菜单关掉 4~5 秒之后 ⇒ 开了。
			//   所以：没开就再让脚本调一次（重写「待处理 + 星图」状态），号码见下。
			int           attempts{};     // 已尝试次数（1 = 玩家按 R 的那一次）
			std::uint64_t retryAtMs{};    // 下一次重试的时间点
			std::uint32_t guideRef{};     // 请求时的引导引用（变了/取消了就放弃重试）
			// ★★ 第 42 轮：重试的**前置条件** —— 必须先看到脚本把这次引导应用了
			//   （GuideState == 1），再等 kStarMapRetryAfterAppliedMs 才允许重试换候选。
			//
			//   起因（玩家反馈「R 的导航结果不太稳定，有时目标不是悬停那条」）：第 40 轮的
			//   重试只看「距请求多少秒」，于是有两类**会换掉目的地**的抢跑：
			//     ① 脚本还没跑到（状态还是 5/6/7）就把候选从 5 改成 6 —— 第一个候选
			//        （行星自己的地点）**根本没被试过**，日志里却是「第 2 次尝试」；
			//     ② 脚本刚应用完、它自己的 1.5 秒延时还没到，重试就把候选改掉了 ——
			//        星图先按候选 5 打开、随后又被重画成候选 6/7（玩家看到航线/焦点跳变）。
			//   现在：appliedAtMs = 脚本报告「已应用」的时刻（0 = 还没看到）；
			//   到点后先问一句通道状态，只有「脚本确实应用过 + 再等一段余量」才换候选。
			std::uint64_t appliedAtMs{};    // 脚本确认应用（GuideState==1）的时刻
			std::uint64_t appliedProbeMs{}; // 上面那次状态检查的节流
			bool          appliedNoted{};   // 「脚本已应用」只记一行
		};
		StarMapProbe g_starMap;

		// ★ 第 38 轮：探测改「多段窗口」。
		//   第 37 轮的单点判定（2.5 秒）给出了假结论：只 kHide 任务菜单时，暂停菜单
		//   还开着 ⇒ 游戏仍暂停 ⇒ 脚本的 0.5 秒定时器走不动（VM 冻结）⇒ 星图要等玩家
		//   手动关掉暂停菜单才出现（实测 R 后 4~5 秒），而探测早已超时打了「没有打开」。
		//   现在：中途记一行「任务菜单/暂停菜单」状态（一眼看出卡在哪），窗口放到 12 秒，
		//   星图一出现就记「R 后约 N 秒」。
		constexpr std::uint64_t kStarMapMidCheckMs = 1500;
		constexpr std::uint64_t kStarMapWindowMs = 12000;
		// ★ 第 40 轮：重试节奏与上限。第 2/3 次会顺带**换地点候选**（状态值告诉脚本用哪个，
		//   脚本侧见 SAQ_Main.psc 的取值表）：
		//     第 1 次 = 状态 5（优先「行星自己的地点」——第 40 轮的新默认）
		//     第 2 次 = 状态 6（引用当前/编辑地点原样 —— 第 37~39 轮的行为）
		//     第 3 次 = 状态 7（父地点链里第一个带行星的地点）
		//   三个候选各试一次，日志里能看出「哪一次把星图打开了」。
		constexpr std::uint64_t kStarMapRetryMs = 2500;
		constexpr int           kStarMapMaxAttempts = 3;
		// ★★ 第 42 轮：**换候选前必须给脚本自己的尝试留足时间**。
		//   脚本拿到「待处理 + 星图」后：先应用引导（写状态 1），再由**轮询节拍**
		//   调原生函数（★ 第 44 轮起约 0.5~1 秒，见 SAQ_Main.psc 的 ProcessStarMapPending）。
		//   第 40 轮的重试从**请求时刻**起算 2.5 秒，正好落在那段窗口里 ⇒ 星图其实马上
		//   要开了，却被重试改掉候选、重画一次航线（玩家看到目的地跳变 = 「不稳定」）。
		//   第 42 轮改成「从脚本确认已应用那一刻起 + 3 秒」才允许重试。
		//   ★ 第 44 轮：脚本侧的窗口从「1.5 s 延时定时器」缩短成「1 个轮询节拍」，这里
		//   也同步收到 1.5 s（仍明显大于脚本那段窗口，不会抢跑；也没有再缩的必要 ——
		//   缩得比脚本窗口小才是问题）。
		//   ★★ 第 55 轮：1.5 s **太紧**了 —— 09:06 会话（harness 首跑 6 条历史用例）
		//   实测脚本这一段实际要 **1.6~2.5 秒**：装星图待办（1 拍）+ 到点执行（再 1 拍）
		//   之外，还要等「界面侧关闭整个暂停菜单 ⇒ 游戏真正恢复运行」那一段（引擎负载
		//   高时能拖到 1 秒以上）。结果：星图**马上就要开了**，DLL 却已经记「第 2 次尝试」
		//   并写通道换候选 —— 还留下一个未被脚本消费的「星图 6」请求（星图关闭后脚本
		//   又执行了一次，玩家看到星图自己再弹一回；本函数下面的写回就是修这个）。
		//   放宽到 3 s：覆盖脚本窗口 + 恢复运行延迟；真失败时也只是晚 1.5 秒重试。
		constexpr std::uint64_t kStarMapRetryAfterAppliedMs = 3000;

		// 请求「关菜单 + 开星图」。调用方保证通道已经写好状态 5。
		// ★ 第 38 轮：a_swfCloses = 新 SWF 会在收到回写后自己调 CloseMenu(true)
		//   （原版「退回游戏」路径 → 动画结束 → GlobalFunc.CloseAllMenus()，整个暂停菜单
		//   一步关完）。那种情况下这里**不发 kHide**：
		//   只隐藏任务菜单会停在「暂停菜单顶层」——游戏仍暂停、星图要等玩家手动关，
		//   正是玩家反馈的「有时候只是切换到了最外层主菜单 / 要等好久」。
		void RequestStarMapOpen(std::uint32_t a_questID, bool a_swfCloses)
		{
			const auto now = NowMs();
			g_starMap.pending = true;
			g_starMap.startMs = now;
			g_starMap.midCheckMs = now + kStarMapMidCheckMs;
			g_starMap.deadlineMs = now + kStarMapWindowMs;
			g_starMap.midLogged = false;
			g_starMap.closedBySwf = a_swfCloses;
			g_starMap.questID = a_questID;
			// ★ 第 40 轮：重试与诊断的现场快照
			g_starMap.attempts = 1;
			g_starMap.retryAtMs = now + kStarMapRetryMs;
			g_starMap.guideRef = g_guide.guideRef;
			// ★ 第 42 轮：重试的「脚本已应用」前置条件（见 StarMapProbe::appliedAtMs）
			g_starMap.appliedAtMs = 0;
			g_starMap.appliedProbeMs = 0;
			g_starMap.appliedNoted = false;
			// ★ 第 40 轮：把「引擎认不认这个地点」写进日志（只读诊断，见上面注释）
			LogStarMapDiagnosis("R 请求");
			if (a_swfCloses) {
				// ★ 第 44 轮：星图的**唯一**打开入口 = 脚本的 ProcessStarMapPending
				//   （菜单关闭后的第一个轮询节拍，约 0.5~1 秒后）。界面侧曾经另外
				//   dispatch 一次原版 MissionMenu_PlotToLocation，但它用的是代理任务
				//   **上一次**的目标位置 ⇒ 星图位置永远滞后一条，已删除（见
				//   MissionMenu.as 的 SaqNoteStarMapHandoff）。
				REX::INFO("星图：界面侧会自己关掉整个暂停菜单（新协议，不发 kHide）；"
						  "星图由脚本在菜单关闭后的下一个轮询节拍打开｜引导任务={}（0x{:08X}）",
					DisplayNameOf(a_questID), a_questID);
				return;
			}
			auto* queue = RE::UIMessageQueue::GetSingleton();
			if (!queue) {
				REX::WARN("星图：UI 消息队列取不到（UIMessageQueue 单例为空）—— 本次不发（引导本身不受影响）");
				return;
			}
			// 菜单名与 UIMessageQueue 的地址库 ID 都是 commonlibsf 里已有的（ID::UIMessageQueue::*）
			queue->AddMessage(RE::BSFixedString{ kMenuName }, RE::UI_MESSAGE_TYPE::kHide);
			REX::INFO("星图：已请求关闭任务菜单（旧协议 kHide；脚本会在菜单关闭时调用 "
					  "Game.ShowGalaxyStarMapMenuAndPlotToLocation）｜引导任务={}（0x{:08X}）",
				DisplayNameOf(a_questID), a_questID);
		}

		// ★★ 第 41 轮：星图的**注册名** = `GalaxyStarMapMenu`（不是 `MapMenu`）。
		//
		//   来历（离线、可复现）：引擎打开星图的 `ShowGalaxyStarMapMenu`（0x2010170）与
		//   `ShowGalaxyStarMapMenuAndPlotToLocation`（0x2010210）都调用 `0x253CFA0` 取菜单名
		//   —— 那是一个惰性初始化的静态 BSFixedString，内容是 `.rdata 0x4C96340` 的
		//   `"GalaxyStarMapMenu"`，随后用它 `UIMessageQueue::AddMessage(…, kShow, …)`。
		//   复现：`python tools/re/dis_range.py 0x253cfa0 0x253d060`
		//
		//   第 37~40 轮误用了菜单名表（`.rdata 0x4D7E010`）里的 `MapMenu` —— 那是**另一个**
		//   菜单的名字 ⇒ DLL 从第 37 轮起所有「星图没有打开」判定都是**假阴性**：星图其实
		//   每次都开了（玩家反馈「R 键可以打开星图」才是真相）。本函数是唯一正确的探测入口。
		const RE::BSFixedString& StarMapMenuName()
		{
			static const RE::BSFixedString name{ "GalaxyStarMapMenu" };
			return name;
		}

		// 诊断：把「此刻还开着的菜单」拼成一行（只查有把握的几个）。
		// 为什么不用 UI::menuStack / IMenu：那要读 commonlibsf 的结构体偏移（本项目通则：
		// 偏移一律不可信），而 IsMenuOpen 是引擎自己的函数，按注册名查哈希表 —— 零风险。
		// 名字来源：exe 的菜单名表（`.rdata 0x4D7DF00` 一带）：PauseMenu / BSMissionMenu /
		// SkillsMenu / StatusMenu …（注意表里**没有 DataMenu** —— 那只是 AS3 事件前缀；
		// 带 tab 栏的外层暂停菜单注册名是 PauseMenu）+ 星图的 GalaxyStarMapMenu（★ 它不在
		// 那张表里，用 StarMapMenuName() 拿）。
		std::string OpenMenusSummary()
		{
			static const RE::BSFixedString kNames[] = {
				"BSMissionMenu", "PauseMenu", "GalaxyStarMapMenu", "SkillsMenu", "StatusMenu",
				"ContainerMenu", "DataSlateMenu", "LoadingMenu", "MainMenu", "FaderMenu"
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

		// ★★ 第 62 轮补（用户实测 12:2x 会话「自动读档后游戏退回主菜单 + 跳出」）：
		//   判定「游戏世界此刻能不能做例行工作」—— 主菜单 / 加载画面 / 过渡黑屏 = 不能。
		//
		//   起因：Tick 的「菜单关着」判定只查 BSMissionMenu ⇒ **主菜单（MainMenu）、
		//   加载画面（LoadingMenu）、过渡黑屏（FaderMenu）**全被当成「菜单关着」，
		//   而这三个窗口正是引擎卸载/重建世界数据的时刻（读档 / 换场景 / 回标题）。
		//
		//   证据链（三份日志对齐，12:30:52 会话 / 主线程 24240）：
		//     · SAS_AlwaysScan 的菜单事件日志：
		//         12:31:07.805 MainMenu opening（标题界面）
		//         12:31:41.897 MainMenu closing → LoadingMenu opening（读档开始）
		//         12:32:02.5 / 12:32:05.5 LoadingMenu closing（两段加载完成）
		//         12:32:05.598 MainMenu opening（★ 读档结束又退回主菜单）
		//         12:32:11 崩溃（Starfield_09-21-04-32.dmp）
		//     · 本插件日志：12:31:44「静态表已就绪（菜单关着时预建，认领已有引导）」
		//         + 12:32:04「引导状态对账…」—— 两句都落在 LoadingMenu 开着期间；
		//     · 崩溃转储（12:30:08 / 12:32:11 两次现场完全一致）：
		//         exe+0x1999E57 `mov eax,[rcx+0x20]`，rcx=0（空指针）、访问 0x20，
		//         故障线程 = 文件 I/O 工作线程（栈上是 usvfs）——
		//         典型的「世界重建中途引擎对象被拆掉、后续流程拿着空指针继续跑」。
		//
		//   ⇒ 世界未就绪时把「例行认领 / 候选复算」这类**成串的引擎查询**全部暂缓
		//     （那是 261 次 LookupByID + TESDataHandler 遍历，读的都是引擎正在重建的表）。
		//     它们本来就有 2 秒节流，等世界稳定后自然继续 —— 这些窗口里既没有 HUD
		//     也没有任务菜单，玩家看不到任何差别。
		//   ★ 只影响「产品侧的例行工作」：harness 的驱动器照跑（它要靠观察加载画面
		//     判断 save.load 的完成）；引导确认（PollGuideVerify）也保留 —— 它是
		//     时序敏感的（玩家点完引导可能立刻快速旅行），且以只读为主。
		bool WorldBusyForUpkeep()
		{
			auto* ui = RE::UI::GetSingleton();
			if (!ui) {
				return true;  // 拿不到 UI 一律当作「忙」（宁可暂缓，不在这种状态下做查询）
			}
			// 注册名来源：exe 菜单名表（第 41/43 轮已在用这三个名字，见 OpenMenusSummary）。
			static const RE::BSFixedString kBusyMenus[] = { "MainMenu", "LoadingMenu", "FaderMenu" };
			for (const auto& name : kBusyMenus) {
				if (ui->IsMenuOpen(name)) {
					return true;
				}
			}
			return false;
		}

		// 「世界未就绪 ⇒ 例行工作暂缓」只在**进入**这个状态时留一行（下次翻现场的第一证据）；
		//   离开窗口时复位，下次读档/换场景还能再记一行。
		bool g_worldBusyNoted = false;

		void NoteWorldBusyEntered()
		{
			if (g_worldBusyNoted) {
				return;
			}
			g_worldBusyNoted = true;
			REX::INFO("读档 / 加载窗口（{} 开着）—— 例行认领 / 候选复算暂缓"
					  "（第 62 轮补：不在引擎重建世界时做查询；窗口结束后自动恢复）",
				OpenMenusSummary());
		}

		void ResetWorldBusyNote()
		{
			g_worldBusyNoted = false;
		}

		// 每帧调用（内部按 pending/到点自我短路，没请求时零开销）：
		//   ① 星图一出现就记一行（带 R 后的秒数与尝试次数）；
		//   ② 中途记一行「还开着哪些菜单」（卡在 PauseMenu = 游戏仍暂停 = 脚本定时器不走
		//      = 星图要等玩家手动关菜单，正是第 37 轮那个 4~5 秒延迟）；
		//   ③ ★ 第 40 轮：没开就自动重试（重写「待处理 + 星图」状态，脚本再调一次原生函数；
		//      第 2/3 次顺带换地点候选 —— 见 kStarMapRetryMs 上面的说明）；
		//   ④ 窗口结束还没出现才 WARN。
		void CheckStarMapOpened()
		{
			if (!g_starMap.pending) {
				return;
			}
			auto* ui = RE::UI::GetSingleton();
			if (!ui) {
				return;
			}
			const auto now = NowMs();
			const auto elapsed = static_cast<double>(now - g_starMap.startMs) / 1000.0;

			// ★ 第 41 轮：用引擎自己的注册名 GalaxyStarMapMenu（见 StarMapMenuName()）。
			if (ui->IsMenuOpen(StarMapMenuName())) {
				g_starMap.pending = false;
				// ★★ 第 55 轮：本次若发生过「换候选重试」（attempts > 1），通道里可能还
				//   留着一个**未被脚本消费**的「待处理 + 星图 6/7」。脚本的轮询节拍在
				//   星图开着时冻结，等玩家把星图一关、游戏恢复运行，那笔残留请求就会被
				//   消费 ⇒ 星图**自己又弹出来一次**（09:06 会话实测：22 秒处第二次打开；
				//   对玩家就是「我明明关掉了它又自己开了」）。
				//   这里把通道标回**普通待处理（状态 0）**：脚本下一拍重新应用同一条引导
				//   —— 顺带作废任何未执行的星图待办（ApplyGuide 的「任何新请求先作废」
				//   第 42 轮语义），且状态 0 不要求开星图，不会再弹。
				std::string retryNote;
				if (g_starMap.attempts > 1 && g_guide.guideRef != 0) {
					std::string detail;
					if (Guide::SetGuideTarget(g_guide.guideRef, detail, /*a_starMap=*/false)) {
						retryNote = std::format("；本次换过候选（第 {} 次尝试）⇒ 已把通道标回普通状态"
												"（防残留的星图请求在星图关闭后再执行一次）",
							g_starMap.attempts);
					} else {
						retryNote = std::format("；⚠ 把通道标回普通状态失败（{}）—— 星图关闭后可能又弹一次",
							detail);
					}
				}
				REX::INFO("星图：已打开（GalaxyStarMapMenu 在屏幕上，R 后约 {:.1f} 秒，第 {} 次尝试）"
						  "—— SET COURSE 链路完整{}",
					elapsed, g_starMap.attempts, retryNote);
				return;
			}
			if (!g_starMap.midLogged && now >= g_starMap.midCheckMs) {
				g_starMap.midLogged = true;
				const auto menus = OpenMenusSummary();
				if (ui->IsMenuOpen(MenuName())) {
					// 任务菜单还开着 ⇒ 脚本跑不到（菜单暂停游戏 ⇒ 定时器不走）。
					REX::WARN("星图：等待中——任务菜单仍开着（R 后 {:.1f} 秒｜其它打开的菜单：{}）：{}",
						elapsed, menus,
						g_starMap.closedBySwf
							? "界面侧还没关菜单（旧 SWF？回写没到？）"
							: "kHide 没生效？请看 docs/05 第十一节");
				} else {
					// ★ 第 48 轮：文案改清楚（旧文案「还开着：无」自相矛盾 —— 空列表 = 除星图外
					//   没有别的菜单挡着，只是脚本的轮询节拍还没到）。
					REX::INFO("星图：等待中（R 后 {:.1f} 秒｜星图还没出现；其它打开的菜单：{}）——"
							  "脚本的定时器要等游戏恢复运行才走（PauseMenu 还在 = 玩家还没离开暂停菜单）",
						elapsed, menus);
				}
			}
			// ★ 第 40 轮：自动重试。只在「没有任何菜单开着」时重试 —— 菜单开着时游戏暂停、
			//   脚本定时器不走，重试请求要等菜单关了才会被处理；与其干等，不如推迟。
			//   ★★ 第 42 轮：再补一道**前置条件** —— 必须先看到脚本应用了这次引导（状态 1），
			//   并从那一刻起再等 kStarMapRetryAfterAppliedMs，才允许换地点候选重试。
			//   理由见 StarMapProbe::appliedAtMs：脚本自己还要 1.5 秒才调原生函数，
			//   从「请求时刻」起算 2.5 秒的重试正好落在它的窗口里 ⇒ 星图本来就要开了，
			//   却被我们改掉候选重画一次（玩家看到航线/目的地跳变 = 「不稳定」）。
			if (g_starMap.appliedAtMs == 0 && now >= g_starMap.appliedProbeMs) {
				g_starMap.appliedProbeMs = now + 1000;   // 节流：每秒问一次通道状态
				const auto ch = Guide::EnsureChannel();
				if (ch.resolved && ch.guideState == 1.0f) {
					g_starMap.appliedAtMs = now;
					if (!g_starMap.appliedNoted) {
						g_starMap.appliedNoted = true;
						REX::INFO("星图：脚本已应用这次引导（状态=1）—— 它的星图调用在下一个轮询节拍"
								  "（约 0.5~1 秒）内到达；这段时间内不改地点候选，只等星图出现"
								  "（{} ms 后仍没有才考虑换候选重试；第 55 轮实测脚本窗口 1.6~2.5 秒）",
							kStarMapRetryAfterAppliedMs);
					}
				}
			}
			const bool retryDue = g_starMap.appliedAtMs != 0 &&
				now >= g_starMap.appliedAtMs + kStarMapRetryAfterAppliedMs;
			// ★ 第 45 轮补丁：诊断显示「目标不在星图上」（全层节点=0）时**不重试** ——
			//   脚本不会打开星图（改发 HUD 提示），重试只会让它重复跑一遍
			//   （玩家看到通知刷多条）。
			if (retryDue && g_starMap.attempts < kStarMapMaxAttempts && !g_starMapDiagAllMiss) {
				const auto menus = OpenMenusSummary();
				if (menus != "无") {
					g_starMap.retryAtMs = now + 1000;
					return;
				}
				if (g_guide.guideRef == 0 || g_guide.guideRef != g_starMap.guideRef) {
					g_starMap.pending = false;
					REX::INFO("星图：放弃重试（引导目标已取消/已换：0x{:08X} → 0x{:08X}）",
						g_starMap.guideRef, g_guide.guideRef);
					return;
				}
				++g_starMap.attempts;
				const float state = g_starMap.attempts == 2 ? 6.0f : 7.0f;
				std::string detail;
				if (Guide::SetGuideTarget(g_guide.guideRef, detail, /*a_starMap=*/true, state)) {
					REX::INFO("星图：第 {} 次尝试（脚本已应用 {:.1f} 秒仍未出现 ⇒ 把通道重设为待处理 + "
							  "星图 {:.0f}：脚本会在菜单关着时再调一次原生函数，地点候选随之切换）｜R 后约 {:.1f} 秒",
						g_starMap.attempts,
						static_cast<double>(now - g_starMap.appliedAtMs) / 1000.0, state, elapsed);
				} else {
					REX::WARN("星图：第 {} 次尝试写通道失败｜{}", g_starMap.attempts, detail);
				}
				// 换候选后脚本要重新应用一次 ⇒ 重新等它的「已应用 + 延时」
				g_starMap.appliedAtMs = 0;
				g_starMap.appliedProbeMs = 0;
				g_starMap.appliedNoted = false;
				g_starMap.retryAtMs = now + kStarMapRetryMs;
				g_starMap.deadlineMs = now + kStarMapWindowMs;   // 窗口跟着顺延
				return;
			}
			if (now >= g_starMap.deadlineMs) {
				g_starMap.pending = false;
				if (g_starMapDiagAllMiss) {
					// ★ 第 45 轮补丁：**按预期**没打开 —— 目标位置不在星图上（诊断：全层节点=0）。
					//   脚本不打开星图、改为发一条 HUD 通知（见 SAQ_Main.psc 的 OpenStarMapFor）
					//   —— 这不是失败，不要用 WARN 误导排查。
					REX::INFO("星图：按预期未打开（`星图诊断` 全层节点=0：目标位置不在星图上）"
							  "—— 脚本已改发 HUD 提示（不开无意义的星图），不算失败");
				} else {
					REX::WARN("星图：{:.1f} 秒内没有打开（已尝试 {} 次｜GalaxyStarMapMenu 不在屏幕上｜其它打开的菜单：{}）"
							  "—— 看 Papyrus 的 `[SAQ] 星图请求` 两行有没有出现（取不到地点 / 脚本没跑）",
						static_cast<double>(kStarMapWindowMs) / 1000.0, g_starMap.attempts,
						OpenMenusSummary());
				}
			}
		}

		// 应用一次引导请求，并把结果回写给界面。a_formID = 0 表示取消引导。
		// 结果码（与 AS3 的约定）：0=成功 / 1=没有引导目标 / 2=写通道失败 / 3=静态表里没有
		//   ★ 第 46 轮新增 5 = 「已排定，但目标此刻还没加载」（保持引导 + 界面提示「靠近后自动生效」，
		//   不回滚、不播 OFF 音、不开星图；见下面 approachPending 分支与 SAQ_Main.psc）。
		// ★ 第 37 轮：a_wantMap = 玩家这次按的是「设定航线（R）」（AS3 在 peek 第三段传来）
		//   —— 成功时除了设引导，还要关掉任务菜单让脚本打开星图（见 RequestStarMapOpen）。
		// ★ 第 38 轮：a_swfCloses = 新 SWF 会在收到回写后自己关掉**整个**暂停菜单
		//   （peek 第四段；旧 SWF 没有这一段 ⇒ false ⇒ 沿用 kHide 的旧路径）。
		void ApplyGuideRequest(std::uint32_t a_formID, int a_seq, bool a_wantMap, bool a_swfCloses)
		{
			// ★ 第 46 轮：每次玩家请求都先清「待生效」状态（下面的 !anyAlive 分支会重新置位）。
			g_guide.approachPending = false;
			g_guide.approachTries = 0;
			g_guide.approachRetryAtMs = 0;

			if (a_formID == 0) {
				g_guide.verifyAtMs = 0;  // 取消：没有「结果」要确认
				g_guide.verifySeq = 0;
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
			// ★ 第 27 轮：也可能是「无限任务入口」（任务板）条目 —— 它的 uID 在世界引用
			//   空间，引导目标就是它自己（见 AppendEntryRows / tools/esm/gen_entry_table.py）。
			const auto* gap = entry ? nullptr : FindEntryByFormID(a_formID);
			if (!entry && !gap) {
				REX::WARN("引导请求：静态表里没有 0x{:08X}（是内嵌回退表里的条目？）", a_formID);
				NotifyGuideReply(a_seq, g_guide.questFormID, 3);
				return;
			}
			std::uint32_t guideRefID = 0;
			std::string_view displayName;
			const char* whereZh = "";
			// ★ 第 46 轮：点引导时所有候选都取不到 ⇒ 走「待生效」路径（见下面的分支）。
			bool approachPending = false;
			if (entry) {
				if (entry->candCount == 0) {
					REX::WARN("引导请求：{}（0x{:08X}）没有引导目标（离线没算出「去哪里接」的引用，见 docs/05）",
						entry->nameZh, a_formID);
					NotifyGuideReply(a_seq, g_guide.questFormID, 1);
					return;
				}
				// ★★ 第 45 轮：从候选池里挑「此刻可得的、质量最优的」候选。列表按质量
				//   排序（有名字的 NPC > 常驻备胎……），第一个 LookupByID 命中的即最优。
				//   玩家在远处时非常驻 NPC 取不到 ⇒ 直接落到常驻备胎上（一次到位，不必
				//   先撞一次失败再换）；全不可得时仍写第一候选，等靠近后由重试/换候选自愈。
				bool anyAlive = false;
				const auto candIdx = PickGuideCandidate(*entry, anyAlive);
				// ★ 第 17 轮：引导目标也是「master + 记录号」，运行期拼成 FormID
				//（DLC 任务的目标可能在基础游戏里，反之亦然）。
				guideRefID = CandidateFormID(*entry, candIdx);
				const auto* candSlot = CandidateAt(*entry, candIdx);
				if (guideRefID == 0 || !candSlot) {
					REX::WARN("引导请求：{}（0x{:08X}）的引导目标属于未加载的 master（{}）",
						entry->nameZh, a_formID,
						candSlot ? Masters::Get(candSlot->refrMaster).name : "?");
					NotifyGuideReply(a_seq, g_guide.questFormID, 1);
					return;
				}
				g_guide.candIndex = candIdx;
				g_guide.candSwitches = 0;
				g_guide.downgradeSinceMs = 0;  // ★ 第 49 轮补丁：新引导不带旧任务的降级观察
				displayName = entry->nameZh;
				whereZh = entry->whereZh;
				if (!anyAlive) {
					// ★★ 第 46 轮（大项 B）：点引导那一刻**所有候选都取不到** ——
					//   实测（「营救机器人」19:27 会话）：旧行为是照常写通道、界面显示
					//   「已设为引导」，然后脚本连报 5 次取不到、19 秒后引导被**静默放弃**
					//   + 界面回滚 ⇒ 玩家看到的是「按了没反应，过一会儿又自己取消了」。
					//   现在：① 界面回写结果码 5（保持竖条 + note 写明原因，不回滚、不播 OFF 音）；
					//        ② 脚本侧发 HUD 提示（见 SAQ_Main.psc 的 ShowNotice）；
					//        ③ 不安排 19 秒确认窗口，改由菜单关着时的**退避慢速重试**
					//           等目标 cell 加载（见 PollApproachRetry）—— 玩家靠近即自动生效。
					approachPending = true;
					REX::INFO("引导请求：{}（0x{:08X}）的 {} 个候选此刻都取不到（玩家离得远？）"
							  "—— 保持待生效：界面已提示、脚本会发 HUD 提示，靠近目标区域后自动生效"
							  "（每 10~60 秒自动重试一次）",
						entry->nameZh, a_formID, entry->candCount);
				}
			} else {
				// ★ 第 30 轮：用候选链选出来的目标；★ 第 31 轮：**点击时重算一次**（候选链
				//   顺序改成「精确优先」后，这里重算就等于「按此刻的加载状态挑最精确的目标」——
				//   玩家已经走到板前时，拿到的就是任务板引用自身，而不是几米外的兜底引用）。
				//   EvaluateEntryGuide 内部只返回**此刻取得到**的引用，所以不需要再复检。
				const auto idx = FindEntryIndexByFormID(a_formID);
				const auto st = (idx < kEntryTableSize) ? EvaluateEntryGuide(idx, false) : EntryGuideState{};
				guideRefID = st.target;
				whereZh = SourceName(st.source);
				displayName = gap->nameZh;
				if (guideRefID == 0) {
					REX::INFO("引导请求：{}（0x{:08X}）当前没有可用的引导目标"
							  "（任务板 / 常驻 marker / 常驻兜底 全取不到）—— 按「暂时无法导航」处理，不写通道",
						displayName, a_formID);
					NotifyGuideReply(a_seq, g_guide.questFormID, 1);
					return;
				}
			}
			std::string detail;
			// ★ 第 37 轮：按了「设定航线（R）」的请求 —— 状态写 5，脚本应用引导后打开星图；
			//   Enter（只开始引导）走 0，行为与历史一致。
			// ★ 第 46 轮：「目标尚未加载」的请求**不带星图意图**（星图要等引导真的生效才有意义；
			//   界面侧也据此不关菜单，见下面 approachPending 分支）。
			const bool wantMap = a_wantMap && !approachPending;
			if (!Guide::SetGuideTarget(guideRefID, detail, /*a_starMap=*/wantMap)) {
				REX::WARN("引导请求：{}（0x{:08X}）写 ESM 通道失败｜{}", displayName, a_formID, detail);
				NotifyGuideReply(a_seq, g_guide.questFormID, 2);
				return;
			}
			g_guide.questFormID = a_formID;
			g_guide.guideRef = guideRefID;
			// ★ 第 42 轮：尾上带 `界面按键行` —— 与这里的任务名并排即可回答
			//   「导航的目标不是我悬停的那条」到底是界面选错了行，还是后面某一段错了（见 As3PressNote）。
			// ★ 第 45 轮：带上候选注记（用的是第几个候选、叫什么）。
			const std::string candNote = entry
				? std::format("候选 [{}/{}]「{}」", g_guide.candIndex + 1u, entry->candCount,
					  CandidateName(*entry, g_guide.candIndex))
				: std::string{ "任务板入口" };
			REX::INFO("引导请求：{}（0x{:08X}）→ 引用 0x{:08X}（{}）｜{}｜{}｜星图={}｜{}",
				displayName, a_formID, guideRefID, whereZh, candNote, detail,
				wantMap ? "是（设定航线）"
						: (a_wantMap ? "否（按了 R，但目标尚未加载）" : "否"),
				As3PressNote());
			if (approachPending) {
				// ★★ 第 46 轮：目标尚未加载 —— 界面**不回滚**（结果码 5 = 保持引导 + 写明原因），
				//   也不关菜单（星图这一半要等引导真的生效才有意义，见下）。
				//   确认窗口不安排：这条引导的兑现时间取决于玩家什么时候靠近，不是几秒的事。
				g_guide.approachPending = true;
				g_guide.approachTries = 0;
				g_guide.approachRetryAtMs = 0;   // 0 = 下一拍例行检查时立刻试第一次
				NotifyGuideReply(a_seq, a_formID, 5);
				REX::INFO("引导确认：目标尚未加载 —— 保持待生效（不做 19 秒超时判定）："
						  "{}（0x{:08X}）｜靠近目标区域后会自动生效（脚本加载到引用即应用）",
					displayName, a_formID);
				if (a_wantMap) {
					REX::INFO("星图：本次不打开（目标尚未加载）—— 引导生效后玩家再按一次"
							  "「设定航线」即可；界面侧不关菜单");
				}
				return;
			}
			NotifyGuideReply(a_seq, a_formID, 0);
			ScheduleGuideVerify(a_seq);
			if (wantMap) {
				// ★ 第 37/38 轮：关掉任务菜单（或由界面侧关掉整个暂停菜单），让脚本打开星图
				RequestStarMapOpen(a_formID, a_swfCloses);
			}
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

			// ★ 第 31 轮：静默的「入口目标更新」确认超时时**不清通道、不回写界面**。
			//   理由：那是我们自己发起的优化（把兜底换成精确目标 / 精确目标失效后换回兜底），
			//   玩家没有请求过任何东西；确认不上只说明脚本没在跑 —— 此时更应该把目标**留在
			//   通道里**等脚本下次运行（开菜单/关菜单）时应用，而不是把引导一并放弃。
			if (g_guide.verifySilent) {
				g_guide.verifySilent = false;
				g_guide.verifyAtMs = 0;
				g_guide.verifySeq = 0;
				// ★ 第 48 轮：文案去掉「入口」（普通任务的候选复算也走这里）；
				//   并说明「读档/脚本未运行期间属预期」（实测：确认窗口整段落在读档 VM 冻结期）。
				REX::WARN("引导目标更新未被脚本确认：{}（0x{:08X}）—— {}；"
						  "通道保持不动（脚本下次运行/关菜单时会应用它；"
						  "读档 / 脚本未运行期间出现这一行属预期）",
					DisplayNameOf(questID), questID, a_why);
				return;
			}

			std::string detail;
			const bool cleared = Guide::SetGuideTarget(0, detail);
			g_guide.questFormID = 0;
			g_guide.guideRef = 0;
			g_guide.verifyAtMs = 0;
			g_guide.verifySeq = 0;
			g_guide.approachPending = false;  // ★ 第 46 轮：放弃引导时一并清「待生效」

			REX::WARN("引导未生效：{}（0x{:08X}）—— {}；已放弃本次引导（清通道{}）",
				DisplayNameOf(questID), questID, a_why,
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
			// ★ 第 27 轮：菜单开着时**完全不做确认轮询**（连 GLOB 都不读）。
			//
			//   第 27 轮的日志复查（DLL × Papyrus 交叉）实锤：游戏在任务菜单打开时暂停 ⇒
			//   Papyrus 的 StartTimer 不走 ⇒ 脚本在菜单开着时**不可能**处理引导请求
			//   （`引导已应用` 只出现在「菜单关闭」那一刻，三次会话一一对应）。
			//   于是这里不再每 2 秒读一次状态（第 26 轮的写法会打一串
			//   「脚本状态还是 0，但菜单还开着」—— 实测 27 秒 9 行，纯噪声）；
			//   等待中的请求也不会被误判：菜单关闭时 OnMissionMenuClosed 会把确认窗口
			//   重置为「900ms 首验 + 6×2s」，真正的超时判定只发生在菜单关着时。
			if (aMenuOpen) {
				if (g_guide.verifyAtMs != 0 && !g_guide.verifyWaitNoted) {
					g_guide.verifyWaitNoted = true;
					REX::INFO("引导确认：菜单还开着 —— 脚本只在菜单关闭时应用引导，关菜单后自动确认（不会判失败）");
				}
				return;
			}
			if (g_guide.verifyAtMs == 0 || NowMs() < g_guide.verifyAtMs) {
				return;
			}
			g_guide.verifyAtMs = 0;  // 先清掉，下面的分支需要时再安排下一次
			const auto ch = Guide::EnsureChannel();
			if (!ch.resolved) {
				REX::WARN("引导结果确认失败：ESM 通道未认领（ESM 没启用？）");
				return;
			}
			const auto again = [&]() { g_guide.verifyAtMs = NowMs() + kGuideVerifyRetryMs; };
			if (ch.guideState == 1.0f) {
				REX::INFO("引导已生效：{}（0x{:08X}）脚本状态=1（世界里应该能看到标记/扫描仪路径线）",
					DisplayNameOf(g_guide.questFormID), g_guide.questFormID);
				g_guide.verifySeq = 0;
				return;
			}
			if (ch.guideState == 4.0f) {
				AbortUnverifiedGuide("脚本状态=4（别名 SAQ_GuideTarget 不存在 —— ESM 补丁没生效，重发无用）",
					aMenuOpen);
				return;
			}
			if ((ch.guideState == 2.0f || ch.guideState == 3.0f) && g_guide.verifyResends < 2) {
				++g_guide.verifyResends;
				// ★ 第 45 轮：状态 2（引用取不到）优先**换下一个候选**（质量次优、此刻
				//   可能可得）；换不成（只有一个候选 / 写失败）才重发当前目标（第 16 轮语义：
				//   等玩家靠近 —— 非常驻引用加载后自然可用）。状态 3 与候选无关，照旧重发。
				bool switched = false;
				if (ch.guideState == 2.0f) {
					const auto* info = FindStaticQuest(g_guide.questFormID);
					switched = info && SwitchGuideCandidate(*info, "脚本报取不到");
				}
				if (!switched) {
					std::string detail;
					if (Guide::SetGuideTarget(g_guide.guideRef, detail)) {
						REX::INFO("引导重发：{}（0x{:08X}）脚本状态={:.0f}"
								  "（2=引用当时没加载 / 3=脚本重挂丢了别名），已清 0 让脚本再试｜{}",
							DisplayNameOf(g_guide.questFormID), g_guide.questFormID, ch.guideState, detail);
					}
				}
			}
			// ★ 第 26/27 轮：超时判定只发生在**菜单关着**时（菜单开着时的短路在函数开头）。
			//   历史：第 26 轮修掉「菜单开着 11 秒就判失败」（玩家挑条目久一点 = 假失败 +
			//   真失效：星海派对 / 回收行动 / 失踪的地球人三次实测）；第 27 轮更进一步 ——
			//   菜单开着时连状态都不读（脚本不可能响应，读了只是噪声）。
			// ★ 第 37 轮：状态 5（待处理 + 星图请求）与 0 同属「脚本还没跑」，走到这里
			//   同样按超时窗口收尾 —— 只是把值写进文案，免得看成未知状态。
			if (++g_guide.verifyTries >= kGuideVerifyMaxTries) {
				AbortUnverifiedGuide(std::format("脚本状态一直是 {:.0f}"
					"（0 待处理 / 2 取不到 / 3 已清除 / 5 星图请求待处理 —— 看 Papyrus 日志里"
					" SAQ_Main 有没有在跑）",
					ch.guideState), aMenuOpen);
				return;
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
		//
		// ★ 第 32 轮：本函数现在**菜单关着时也会被例行调用**（PollGuideUpkeep，每 2 秒一次）——
		//   玩家重启游戏/读档后直接看 HUD（不进菜单）时，旧引导必须在这里被认领回来，
		//   第 31 轮的「目标动态更新」才有机会把蓝点从兜底引用挪到任务板上。
		void AdoptExistingGuide()
		{
			if (g_guide.questFormID != 0) {
				return;  // 这次会话里已经设过引导了，不用认领
			}
			// ★ 第 33 轮：菜单关着时本函数会被例行调用，而**静态表可能还没建**
			//   （它此前只在打开菜单时建）。表没就绪时三条反查全会落空 ——
			//   那不代表「这条引导认不出来」，只代表「等会儿再试」，见 EnsureStaticTablesReady。
			if (!EnsureStaticTablesReady("认领已有引导")) {
				return;
			}
			const auto ch = Guide::EnsureChannel();
			// ★ 第 21 轮：用拼好的完整 FormID（ch.targetFormID）—— 目标值在通道里是
			//   「低 24 位 + 高 8 位」两个 GLOB（float 精度所限，见 SAQ_Guide.cpp）。
			const auto targetID = ch.targetFormID;
			if (!ch.resolved || targetID == 0) {
				return;
			}
			// ★ 第 45 轮：通道里的目标可能是候选池里的第 2/3 个 —— 反查顺带取回下标，
			//   后续换候选 / 动态升级都从它继续（不然会从第 1 个重新数）。
			std::uint8_t adoptCandIdx = 0;
			const auto* entry = FindQuestByGuideRef(targetID, adoptCandIdx);
			if (!entry) {
				// ★ 第 27 轮：也可能是「无限任务入口」（任务板）—— 旧会话的目标 = 条目 uID（板自身）。
				// ★ 第 30 轮：新会话的目标是候选链选中的那一个（新建常驻 marker / 同 cell 兜底），
				//   按候选反查回它所属的入口条目（FindEntryIndexByGuideCandidate）。
				const auto* gap = FindEntryByFormID(targetID);
				std::size_t gapIdx = kEntryTableSize;
				if (!gap) {
					gapIdx = FindEntryIndexByGuideCandidate(targetID);
					if (gapIdx < kEntryTableSize) {
						gap = &kEntryTable[gapIdx];
					}
				}
				if (gap) {
					// 条目的「界面 uID」= 任务板引用自身的运行期 FormID（不是 marker/兜底引用的）。
					const auto uid = Masters::MakeFormID(gap->master, gap->refLocal);
					g_guide.questFormID = uid;
					g_guide.guideRef = targetID;
					g_guide.lastTargetCheckMs = 0;
					// ★ 第 48 轮：宽限期内不复算（读档瞬间的引擎查询不可靠，见 kAdoptGraceMs）。
					g_guide.adoptGraceUntilMs = NowMs() + kAdoptGraceMs;
					g_guide.adoptWarnRef = 0;
					g_guide.downgradeSinceMs = 0;  // ★ 第 49 轮补丁：认领不带旧的降级观察
					REX::INFO("认领已有引导（任务板入口）：{}（0x{:08X}）引导目标=0x{:08X}｜脚本状态={:.0f}"
							  "（上一次会话/读档留下的，界面会同步成「正在引导」）",
						gap->nameZh, uid, targetID, ch.guideState);
					return;
				}
				// ★ 第 32 轮：菜单关着时本函数每 2 秒被调用一次 —— 同一个认不出的目标只 WARN 一次。
				// ★ 第 33 轮：能走到这里说明静态表**就绪**（见函数开头的 EnsureStaticTablesReady），
				//   所以「认不出」是真的认不出（不是表没建好）—— 文案里带上表的规模当证据。
				if (g_guide.adoptWarnRef != targetID) {
					g_guide.adoptWarnRef = targetID;
					REX::WARN("ESM 通道里有引导目标 0x{:08X}，但静态表里没有哪条任务/入口的引导目标是它"
							  "（另一个存档 / 老版本留下的？；静态表已就绪：运行期行 {}/{}）"
							  "—— 已按「没有引导」处理，下次点引导会覆盖它",
						targetID, g_runtimeRows.size(), kQuestTableSize);
				}
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
			g_guide.candIndex = adoptCandIdx;   // ★ 第 45 轮：从通道里的那个候选继续
			g_guide.candSwitches = 0;
			g_guide.lastTargetCheckMs = 0;
			// ★ 第 48 轮：宽限期内不复算（读档瞬间的引擎查询不可靠，见 kAdoptGraceMs）。
			g_guide.adoptGraceUntilMs = NowMs() + kAdoptGraceMs;
			g_guide.adoptWarnRef = 0;
			g_guide.downgradeSinceMs = 0;  // ★ 第 49 轮补丁：认领不带旧的降级观察
			REX::INFO("认领已有引导：{}（0x{:08X}）目标引用=0x{:08X}（候选 [{}]「{}」/ 共 {}）"
					  "｜脚本状态={:.0f}（上一次会话/读档留下的，界面会同步成「正在引导」）",
				entry->nameZh, questID, targetID, adoptCandIdx + 1u,
				CandidateName(*entry, adoptCandIdx), entry->candCount, ch.guideState);
		}

		// 菜单开着时轮询 AS3 的引导请求（`_root.SAQ_PeekGuide` → "<序号>|<任务FormID>"）。
		// 序号 0 = 还没有请求；序号变化才算一次新请求（同一个请求不会被重复处理）。
		void PollGuideRequest()
		{
			// ★★★ 第 125 轮（路线 D）：界面不是我们的 ⇒ 不会有我们的引导请求，别空轮询
			if (g_uiChannelDead) {
				return;
			}
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
			// ★ 第 37 轮：第三段 = 要不要打开星图（1 = 玩家按的是「设定航线（R）」，
			//   0 / 缺省 = Enter 子项等普通引导）。旧 SWF 只给两段 ⇒ 按 0 处理，
			//   行为与第 36 轮之前完全一致（只设引导，不动菜单）。
			// ★ 第 38 轮：第四段 = 界面侧会不会自己关掉整个暂停菜单（1/0）。
			//   新 SWF 在「设定航线」成功回写后走原版「退回游戏」路径（CloseMenu(true)），
			//   那样 DLL 就不必（也不该）发 kHide —— 只隐藏任务菜单会停在暂停菜单顶层。
			//   旧 SWF 没有第四段 ⇒ false ⇒ 沿用 kHide 的旧路径（行为不变）。
			std::string_view rest = std::string_view{ peek }.substr(bar + 1);
			bool             wantMap = false;
			bool             swfCloses = false;
			if (const auto bar2 = rest.find('|'); bar2 != std::string_view::npos) {
				std::string_view third = rest.substr(bar2 + 1);
				if (const auto bar3 = third.find('|'); bar3 != std::string_view::npos) {
					swfCloses = third.substr(bar3 + 1).find('1') != std::string_view::npos;
					third = third.substr(0, bar3);
				}
				wantMap = third.find('1') != std::string_view::npos;
				rest = rest.substr(0, bar2);
			}
			int seq = 0;
			unsigned long fid = 0;
			try {
				seq = std::stoi(peek.substr(0, bar));
				fid = std::stoul(std::string{ rest });
			} catch (...) {
				REX::WARN("引导请求：解析失败 {}", peek);
				return;
			}
			if (seq <= 0 || seq == g_guide.lastSeq) {
				return;
			}
			g_guide.lastSeq = seq;
			ApplyGuideRequest(static_cast<std::uint32_t>(fid), seq, wantMap, swfCloses);
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
			//   ★ 第 64 轮（大项 K）：判据在离线层（Decision::IsCompletedConfirmed，
			//   与「已完成 ⇒ 隐藏」同源、有单测）。
			if (!Decision::IsCompletedConfirmed(ToDecisionFlags(state), state.vtableKnown)) {
				return;
			}
			std::string detail;
			if (Guide::SetGuideTarget(0, detail)) {
				REX::INFO("引导自动取消：{}（0x{:08X}）已完成（{}）｜{}",
					DisplayNameOf(g_guide.questFormID), g_guide.questFormID, Describe(state), detail);
			}
			g_guide.questFormID = 0;
			g_guide.guideRef = 0;
			g_guide.approachPending = false;   // ★ 第 46 轮：自动取消时不带「待生效」状态
			g_guide.approachTries = 0;
			g_guide.approachRetryAtMs = 0;
		}

		// ★★ 第 45 轮：把引导换到候选池里的**下一个**候选（循环回绕）。
		//
		//   触发场景（都来自实测反馈的形状）：
		//     * 点引导时第一候选（有名字的 NPC）非常驻、人在远处 ⇒ 脚本报状态 2；
		//     * 认领的候选后来随 cell 卸载而不可用。
		//   换成「质量次优但此刻可能可得」的候选，比干等一个取不到的目标强。
		//   候选转一圈都没可得时，调用方会回到「重发当前目标」等玩家靠近（第 16 轮语义）。
		//
		//   返回 true = 已换并写好通道；false = 没得换（候选 ≤1 / 写失败）。
		bool SwitchGuideCandidate(const StaticQuestInfo& a_info, std::string_view a_reason)
		{
			if (a_info.candCount <= 1) {
				return false;
			}
			const auto next = static_cast<std::uint8_t>((g_guide.candIndex + 1) % a_info.candCount);
			const auto nextID = CandidateFormID(a_info, next);
			if (nextID == 0) {
				return false;  // 下一个候选的 master 没加载 —— 不换（保持现状）
			}
			std::string detail;
			if (!Guide::SetGuideTarget(nextID, detail)) {
				REX::WARN("引导换候选失败：{}（0x{:08X}）候选 [{}] → [{}]｜{}",
					DisplayNameOf(g_guide.questFormID), g_guide.questFormID,
					g_guide.candIndex + 1u, next + 1u, detail);
				return false;
			}
			const auto old = g_guide.guideRef;
			const auto oldIdx = g_guide.candIndex;
			g_guide.guideRef = nextID;
			g_guide.candIndex = next;
			++g_guide.candSwitches;
			// 重新开始确认窗口（900ms 后复查）。**不重置 verifyTries/verifyResends**：
			// 那是「总重试预算」，由调用方（PollGuideVerify）统一管理 —— 否则换候选
			// 会无限给自己续命。
			g_guide.verifyAtMs = NowMs() + kGuideVerifyFirstMs;
			g_guide.verifySeq = 0;
			REX::INFO("引导换候选：{}（0x{:08X}）0x{:08X} → 0x{:08X}"
					  "（[{}]「{}」→ [{}]「{}」；{}）｜{}",
				DisplayNameOf(g_guide.questFormID), g_guide.questFormID, old, nextID,
				oldIdx + 1u, CandidateName(a_info, oldIdx), next + 1u, CandidateName(a_info, next),
				a_reason, detail);
			return true;
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
		// ★ 第 45 轮：状态 2（取不到）时优先**换下一个候选**（见 SwitchGuideCandidate）；
		//   候选只有一个 / 换不成才重发当前目标（第 16 轮语义：等玩家靠近后自愈）。
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
			// ★ 第 45 轮：状态 2（取不到）优先换下一个候选；状态 3（脚本重挂丢别名）
			//   与候选无关，照旧重发。
			if (ch.guideState == 2.0f) {
				const auto* info = FindStaticQuest(g_guide.questFormID);
				if (info && SwitchGuideCandidate(*info, "脚本报取不到")) {
					return;
				}
			}
			std::string detail;
			if (!Guide::SetGuideTarget(g_guide.guideRef, detail)) {
				REX::WARN("引导重新下发失败：{}（0x{:08X}）｜{}",
					DisplayNameOf(g_guide.questFormID), g_guide.questFormID, detail);
				return;
			}
			REX::INFO("引导重新下发：{}（0x{:08X}）脚本状态={:.0f}"
					  "（2=引用当时没加载 / 3=脚本重挂丢了别名），已清 0 让脚本再试｜{}",
				DisplayNameOf(g_guide.questFormID), g_guide.questFormID, ch.guideState, detail);
		}

		// ★★ 第 45 轮：普通任务的候选池「动态复算」（菜单关着时定期跑，与入口同一套思路）。
		//
		// 场景：
		//   ① 玩家从远处点引导（第一候选 = 有名字的 NPC 非常驻取不到 ⇒ 已落到常驻备胎）；
		//      随后飞近、NPC 的 cell 加载了 ⇒ 这里把引导**升级**回 NPC（更贴「去哪里接」）；
		//   ② 玩家飞远 / 目标随 cell 卸载 ⇒ 换回此刻可得的候选（蓝点至少还在）。
		// 只写通道、不碰界面：换的是**同一条任务**的引导目标，界面上的「正在引导」不变
		// （静默确认：失败不清通道、不回滚界面，见 AbortUnverifiedGuide）。
		void UpdateQuestGuideTarget(const StaticQuestInfo& a_info)
		{
			if (a_info.candCount <= 1) {
				return;  // 只有一个候选：没什么可复算的
			}
			const auto now = NowMs();
			if (now < g_guide.adoptGraceUntilMs) {
				return;  // ★ 第 48 轮：认领后的复算宽限期（读档瞬间查询不可靠，见 kAdoptGraceMs）
			}
			if (g_guide.lastTargetCheckMs != 0 &&
				now - g_guide.lastTargetCheckMs < kEntryTargetCheckMs) {
				return;  // 节流：1.5 秒最多复算一次（与入口共用同一个节流戳）
			}
			g_guide.lastTargetCheckMs = now;

			bool anyAlive = false;
			const auto best = PickGuideCandidate(a_info, anyAlive);
			// ★ 第 49 轮补丁：**降级要过观察期，升级立即执行**。
			//   `best > candIndex` ⇔ 当前候选此刻取不到（best 只从可得的里挑，见 PickGuideCandidate）；
			//   先保持通道不动，持续 kDowngradeHoldMs 仍取不到才换（依据见 kDowngradeHoldMs 注释）。
			//   ★★ 第 64 轮（大项 K）：判据抽到**离线层**（Decision::DecideGuideRecalc，
			//   有全组合单测）—— 这里按它给的动作执行副作用（日志 / 计时戳 / 换目标）。
			const bool observing = g_guide.downgradeSinceMs != 0;
			const bool observeElapsed =
				observing && now - g_guide.downgradeSinceMs >= kDowngradeHoldMs;
			const auto recalc = Decision::DecideGuideRecalc(
				anyAlive, g_guide.candIndex, best, observing, observeElapsed);
			if (recalc == Decision::GuideRecalcAction::kHoldIdle ||
				recalc == Decision::GuideRecalcAction::kHoldObserving) {
				return;  // 通道保持不动（已最优 / 观察中未满 / 没有任何可降级的目标）
			}
			if (recalc == Decision::GuideRecalcAction::kBeginObserve) {
				g_guide.downgradeSinceMs = now;
				REX::INFO("候选复算：{}（0x{:08X}）当前候选 [{}]「{}」此刻取不到 —— 先保持"
						  "（观察 {:.0f} 秒仍取不到才降级；读档 / 加载中常见）",
					DisplayNameOf(g_guide.questFormID), g_guide.questFormID,
					g_guide.candIndex + 1u, CandidateName(a_info, g_guide.candIndex),
					static_cast<double>(kDowngradeHoldMs) / 1000.0);
				return;
			}
			if (recalc == Decision::GuideRecalcAction::kEndObserve ||
				recalc == Decision::GuideRecalcAction::kEndObserveSwitch) {
				REX::INFO("候选复算：{}（0x{:08X}）当前候选 [{}]「{}」恢复可得 —— 观察结束（未降级）",
					DisplayNameOf(g_guide.questFormID), g_guide.questFormID,
					g_guide.candIndex + 1u, CandidateName(a_info, g_guide.candIndex));
				g_guide.downgradeSinceMs = 0;
				if (recalc == Decision::GuideRecalcAction::kEndObserve) {
					return;  // 恢复可得且已是最优 ⇒ 通道保持不动
				}
			}
			// 到这里 = kEndObserveSwitch / kSwitchUpgrade / kSwitchDowngrade ⇒ 切换目标。
			const auto bestID = CandidateFormID(a_info, best);
			if (bestID == 0) {
				return;
			}
			std::string detail;
			if (!Guide::SetGuideTarget(bestID, detail)) {
				REX::WARN("引导目标更新失败（候选复算）：{}（0x{:08X}）候选 [{}] → [{}]｜{}",
					DisplayNameOf(g_guide.questFormID), g_guide.questFormID,
					g_guide.candIndex + 1u, best + 1u, detail);
				return;
			}
			const auto old = g_guide.guideRef;
			const auto oldIdx = g_guide.candIndex;
			g_guide.guideRef = bestID;
			g_guide.candIndex = best;
			ScheduleGuideVerify(0);
			g_guide.verifySilent = true;  // 静默：失败不清通道、不回滚界面
			REX::INFO("引导目标已更新（候选复算）：{}（0x{:08X}）0x{:08X} → 0x{:08X}"
					  "（[{}]「{}」→ [{}]「{}」）｜{}",
				DisplayNameOf(g_guide.questFormID), g_guide.questFormID, old, bestID,
				oldIdx + 1u, CandidateName(a_info, oldIdx), best + 1u, CandidateName(a_info, best),
				detail);
		}

		// ★★ 第 31 轮：入口条目的引导目标**动态更新**（只写通道 + 记日志，不碰界面）。
		//
		// 场景（玩家的实际走法，也是 13:15 截图的成因）：
		//   ① 站在别处选「任务板 · 陋室」→ 那一刻板所在 cell 没加载 ⇒ 目标只能落
		//      「同 cell 常驻兜底引用」（`MQ204_NoelBasement_Marker01a`，离板 3.41 m）；
		//   ② 玩家飞/走到陋室，蓝点仍停在那个兜底引用上 ⇒ 看起来「蓝点不在板上」。
		//
		// 这里在**菜单关着**时定期（1.5 s）复算候选链：
		//   * 更精确的目标（任务板自身 / 常驻 marker）变得可用 ⇒ 换过去（蓝点随之上板）；
		//   * 当前目标已经不可用（非常驻引用随 cell 卸载而消失）⇒ 换回兜底（蓝点回到大致位置）。
		// 只处理「无限任务入口」条目 —— 普通任务的目标是离线算好的常驻引用，不需要动。
		//
		// 为什么不做任何界面动作：换的是**同一个条目**的引导目标（uID 不变），界面上
		// 「正在引导的那条」没有任何变化，回写反而是噪声（且静默更新没有对应的请求序号）。
		void UpdateEntryGuideTarget()
		{
			if (g_guide.questFormID == 0) {
				return;  // 没在引导
			}
			if (g_guide.verifyAtMs != 0) {
				return;  // 有一次下发还没确认（正常请求或上一次静默更新），别插队
			}
			const auto idx = FindEntryIndexByFormID(g_guide.questFormID);
			if (idx >= kEntryTableSize) {
				// ★ 第 45 轮：不是入口条目 —— 普通任务走**候选池**的动态复算
				//   （同一个节流戳；函数内部 candCount ≤ 1 时直接返回）。
				const auto* info = FindStaticQuest(g_guide.questFormID);
				if (info) {
					UpdateQuestGuideTarget(*info);
				}
				return;
			}
			const auto now = NowMs();
			if (now < g_guide.adoptGraceUntilMs) {
				return;  // ★ 第 48 轮：认领后的复算宽限期（读档瞬间查询不可靠，见 kAdoptGraceMs）
			}
			if (g_guide.lastTargetCheckMs != 0 &&
				now - g_guide.lastTargetCheckMs < kEntryTargetCheckMs) {
				return;  // 节流：1.5 秒最多复算一次
			}
			g_guide.lastTargetCheckMs = now;

			const auto st = EvaluateEntryGuide(idx, false);
			if (st.target == 0 || st.target == g_guide.guideRef) {
				return;  // 没有可用目标（保持现状）/ 已经是最优的
			}
			const bool toExact = (st.source == EntryGuideSource::exactBoard ||
								  st.source == EntryGuideSource::exactMarker);
			const bool currentAlive = RE::TESForm::LookupByID(
										  static_cast<RE::TESFormID>(g_guide.guideRef)) != nullptr;
			if (!toExact && currentAlive) {
				return;  // 现在这个目标还活着而且不会更差 —— 不换（避免精确→兜底的无谓抖动）
			}
			// ★ 第 49 轮补丁：降级（当前目标取不到 ⇒ 换兜底）先过**观察期** ——
			//   与普通任务的候选复算同一套语义（读档/加载瞬间 LookupByID 会短暂返回
			//   null，旧行为会据此把精确目标换成兜底、加载完再升回 ⇒ 蓝点闪动）。
			if (!toExact) {
				if (g_guide.downgradeSinceMs == 0) {
					g_guide.downgradeSinceMs = now;
					REX::INFO("入口引导目标复算：{}（0x{:08X}）当前目标 0x{:08X} 此刻取不到 —— 先保持"
							  "（观察 {:.0f} 秒仍取不到才降级；读档 / 加载中常见）",
						DisplayNameOf(g_guide.questFormID), g_guide.questFormID, g_guide.guideRef,
						static_cast<double>(kDowngradeHoldMs) / 1000.0);
				}
				if (now - g_guide.downgradeSinceMs < kDowngradeHoldMs) {
					return;  // 观察期未满 ⇒ 通道保持不动
				}
			} else {
				g_guide.downgradeSinceMs = 0;  // 能换更精确的目标（升级）⇒ 立即执行并清观察
			}

			std::string detail;
			if (!Guide::SetGuideTarget(st.target, detail)) {
				REX::WARN("入口引导目标更新失败：{}（0x{:08X}）0x{:08X} → 0x{:08X}（{}）｜{}",
					DisplayNameOf(g_guide.questFormID), g_guide.questFormID, g_guide.guideRef,
					st.target, SourceName(st.source), detail);
				return;
			}
			const auto old = g_guide.guideRef;
			g_guide.guideRef = st.target;
			ScheduleGuideVerify(0);            // 预约一次确认（失败不清通道，见 AbortUnverifiedGuide）
			g_guide.verifySilent = true;
			REX::INFO("入口引导目标已更新：{}（0x{:08X}）0x{:08X} → 0x{:08X}（{}）{}｜{}",
				DisplayNameOf(g_guide.questFormID), g_guide.questFormID, old, st.target,
				SourceName(st.source),
				currentAlive ? std::string_view{} : std::string_view{ "（原目标已不可用）" }, detail);
		}

		// ★★ 第 46 轮（大项 B）：等待「目标加载」的引导 —— **退避慢速重试**。
		//
		//   场景：玩家在远处点了一条候选全是非常驻的任务（或目标 cell 恰好没加载）。
		//   DLL 在点击那一刻就知道「全不可得」⇒ 不安排 19 秒超时判定（见 ApplyGuideRequest），
		//   改由这里在菜单关着时把通道重写一遍（GuideState 清 0）让脚本再试 ——
		//   玩家飞/走进目标区域、cell 一加载，这一下就成功，蓝点自动出现；
		//   界面上的「正在引导」自始至终没变（与真实状态一致），玩家侧另有 HUD 提示。
		//
		//   为什么退避（10 秒起步、上限 60 秒、约 35 分钟停手）：每次失败脚本都会写状态 2
		//   并留一行 Trace —— 固定 2 秒重试会让两侧日志刷屏；而「等玩家靠近」本来就是分钟级的事。
		//   停手后引导**保持**：下次打开菜单时 ReissueGuideIfScriptLost 会再试一次。
		void PollApproachRetry(const Guide::Channel& a_ch, std::uint64_t a_now)
		{
			if (!g_guide.approachPending || g_guide.questFormID == 0) {
				return;  // 没在等目标加载：零开销
			}
			if (a_ch.guideState == 1.0f) {
				g_guide.approachPending = false;
				REX::INFO("引导延迟生效：{}（0x{:08X}）目标已加载并被脚本应用（共重试 {} 次）"
						  "—— 玩家在远处点引导时，靠这条路径兑现",
					DisplayNameOf(g_guide.questFormID), g_guide.questFormID, g_guide.approachTries);
				return;
			}
			if (g_guide.approachTries >= kApproachMaxTries) {
				g_guide.approachPending = false;
				REX::INFO("引导待生效（暂停重试）：{}（0x{:08X}）已重试 {} 次、目标区域仍未加载"
						  "—— 引导保持（开一次任务菜单会再试），玩家靠近后按一次「设定航线」即可",
					DisplayNameOf(g_guide.questFormID), g_guide.questFormID, g_guide.approachTries);
				return;
			}
			if (g_guide.approachRetryAtMs != 0 && a_now < g_guide.approachRetryAtMs) {
				return;  // 还没到下一次重试的时间
			}
			std::string detail;
			if (!Guide::SetGuideTarget(g_guide.guideRef, detail)) {
				g_guide.approachRetryAtMs = a_now + kApproachRetryMaxMs;
				REX::WARN("引导重试（等待目标加载）写通道失败：{}（0x{:08X}）｜{}",
					DisplayNameOf(g_guide.questFormID), g_guide.questFormID, detail);
				return;
			}
			++g_guide.approachTries;
			// 退避：10 / 20 / 40 / 60 / 60 … 秒
			const auto shift = std::min<std::uint32_t>(g_guide.approachTries, 3);
			const auto delay = std::min<std::uint64_t>(kApproachRetryMaxMs, kApproachRetryFirstMs << shift);
			g_guide.approachRetryAtMs = a_now + delay;
			REX::INFO("引导重试（等待目标加载）：{}（0x{:08X}）第 {} 次（目标 0x{:08X}，脚本状态={:.0f}）"
					  "—— 约 {} 秒后再试；玩家靠近目标区域即自动生效",
				DisplayNameOf(g_guide.questFormID), g_guide.questFormID, g_guide.approachTries,
				g_guide.guideRef, a_ch.guideState, delay / 1000);
		}

		// ★★ 第 32 轮：菜单关着时的**例行认领 + 通道对账**（每 2 秒一次）。
		//
		// 起因（玩家本轮实测：重启游戏后蓝点仍然偏 3.41 m）：第 31 轮的「目标动态更新」
		// 只在 DLL **已经认领**引导之后才会跑，而认领此前只发生在「菜单打开」时 ——
		// 玩家重启游戏、读档、直接看 HUD（全程不进菜单）时：
		//   • DLL 侧 questFormID == 0 ⇒ UpdateEntryGuideTarget 直接短路；
		//   • 存档里（GLOB）残留的旧目标（上次会话选的兜底引用，离板 ~3 m）继续生效
		//     ⇒ 「蓝点不在板上」原样复现。
		//
		// 现在菜单关着时定期做三件事（都很便宜；只在状态不一致时才有动作）：
		//   ① 没在引导 + 通道里有目标 ⇒ **认领**（AdoptExistingGuide）—— 同一帧后面的
		//      UpdateEntryGuideTarget 就会把目标换成当前最精确的可用引用（蓝点自动上板）；
		//   ② 在引导 + 通道里没有目标（读档到了「没有引导」的存档）⇒ 重置本侧状态；
		//   ③ 在引导 + 通道目标与本侧不一致（同会话里读了另一个存档 / 通道被外部改）
		//      ⇒ 清本侧状态，下一轮按通道值重新配对（认知以通道/存档为准）。
		//   ★★ 第 46 轮：另加 ④ 目标一致、但这条引导还在「等目标加载」⇒ 退避重试
		//      （PollApproachRetry）—— 玩家靠近后蓝点自动出现的兑现路径。
		void PollGuideUpkeep()
		{
			const auto now = NowMs();
			if (g_guide.upkeepMs != 0 && now - g_guide.upkeepMs < kUpkeepIntervalMs) {
				return;
			}
			g_guide.upkeepMs = now;

			const auto ch = Guide::EnsureChannel();
			if (!ch.resolved) {
				return;  // 通道没认领（ESM 没加载等）—— LogEsmChannel 已经记过原因
			}
			if (g_guide.questFormID == 0) {
				if (ch.targetFormID != 0) {
					AdoptExistingGuide();  // ①
				}
				return;
			}
			if (ch.targetFormID == g_guide.guideRef) {
				// ★ 第 46 轮：一致 —— 如果这条引导还在「等目标加载」，在这里推进退避重试。
				PollApproachRetry(ch, now);
				return;
			}

			// ② / ③：不一致，以通道（= 存档）为准，清本侧等重新配对。
			if (ch.targetFormID == 0) {
				REX::INFO("引导状态对账：通道里已没有目标（读档到了没有引导的存档？）—— 重置本侧"
						  "（原先：{} 0x{:08X} 目标 0x{:08X}）",
					DisplayNameOf(g_guide.questFormID), g_guide.questFormID, g_guide.guideRef);
			} else {
				REX::INFO("引导状态对账：通道目标 0x{:08X} ≠ 本侧 0x{:08X}（读档切换 / 外部改动？）"
						  "—— 按通道重新配对",
					ch.targetFormID, g_guide.guideRef);
			}
			g_guide.questFormID = 0;
			g_guide.guideRef = 0;
			g_guide.verifyAtMs = 0;
			g_guide.verifySeq = 0;
			g_guide.verifySilent = false;
			g_guide.lastTargetCheckMs = 0;
			g_guide.adoptWarnRef = 0;
			g_guide.downgradeSinceMs = 0;      // ★ 第 49 轮补丁：重新配对不带旧的降级观察
			g_guide.approachPending = false;   // ★ 第 46 轮：重新配对时不带「待生效」状态
			g_guide.approachTries = 0;
			g_guide.approachRetryAtMs = 0;
		}

		void OnMissionMenuClosed()
		{
			// ★★ 第 43 轮：关闭时刻的两项补强（排查「按 R 没反应」时定位出来的）。
			//
			//   ① 界面报告**现场读一次**，而不是只用 500ms 轮询的缓存 ——
			//      玩家按 R 与菜单关闭常常落在同一个轮询周期里：旧代码打印的
			//      `菜单关闭：界面最后状态` 是**按键之前**的缓存，日志里因此看起来
			//      「按 R 什么都没发生」（press/btn/ev 探针全被缓存遮住）。
			//   ② 关闭前**补一次引导请求轮询**：PollGuideRequest 只在「菜单开着」
			//      那一支里跑（见 Tick），而按 R 后菜单常常立刻关掉（界面侧
			//      CloseMenu(true) / 玩家取消）—— 旧代码紧接着就把 lastSeq 重置，
			//      那次请求会被**丢掉**。先在重置前 poll 一次，能救回来。
			//      （节流按「距上次 100ms」判定，关闭时刻这一下强制读 —— lastPollMs 清零。）
			{
				std::string live;
				// ★★★ 第 125 轮（路线 D）：界面不是我们的 SWF ⇒ 跳过现场读（读了也只有 fail）
				if (!g_uiChannelDead && UI::ReadUiReport(live) && !live.empty()) {
					g_poll.lastReport = std::move(live);
				}
			}
			const auto seqBeforeClose = g_guide.lastSeq;
			g_guide.lastPollMs = 0;
			PollGuideRequest();
			if (g_guide.lastSeq != seqBeforeClose) {
				REX::INFO("菜单关闭：补处理了关闭瞬间的引导请求（序号 {} → {}）",
					seqBeforeClose, g_guide.lastSeq);
			}
			if (!g_poll.lastReport.empty()) {
				REX::INFO("菜单关闭：界面最后状态={}", g_poll.lastReport);
			} else if (g_uiChannelDead) {
				// ★★★ 第 125 轮（路线 D）：已判定界面不是我们的 —— 说清楚（不是「读不到」）
				REX::INFO("菜单关闭：界面状态未读取（本轮已判定 UI 通道不可用 —— 界面不是我们的 SWF）");
			} else {
				REX::INFO("菜单关闭：界面状态一条都没读回来（桥没通 / SWF 是旧版 / 一次都没轮询到）");
			}
			ResetReportPoll();

			// 引导请求的「变化检测」状态跟着菜单一起重置：菜单重开时 SWF 新建，
			// AS3 侧的序号从 0 重新开始（当前引导本身存在 GLOB 里，不受影响）。
			g_guide.lastPeek.clear();
			g_guide.lastSeq = -1;
			g_guide.lastPollMs = 0;

			// ★ 第 26 轮：菜单关闭 = 脚本真正「拿到」引导请求的时刻（见 PollGuideVerify 的说明：
			//   脚本靠 OnMenuOpenCloseEvent(关闭) 里的 ApplyGuide 应用引导）。
			//   到这里才把确认窗口重置一次 —— 玩家在菜单里挑条目挑多久都不会被判失败，
			//   关菜单后给脚本 ≈11 秒的完整窗口。
			if (g_guide.verifyAtMs != 0) {
				g_guide.verifyTries = 0;
				g_guide.verifyResends = 0;
				g_guide.verifyAtMs = NowMs() + kGuideVerifyFirstMs;
				REX::INFO("引导确认：菜单已关 —— 脚本会在关闭事件里应用引导，{} ms 后开始确认（窗口约 {} 秒）",
					kGuideVerifyFirstMs,
					(kGuideVerifyFirstMs + kGuideVerifyRetryMs * (kGuideVerifyMaxTries - 1)) / 1000);
			}
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

			// ★★★ 第 125 轮（路线 D · 冲突检测）：每菜单打开重置判定 —— 新菜单 = 新 SWF
			//   实例（玩家可能刚调了加载顺序 / 热重载）⇒ 给它新的一次探测机会。
			//   g_uiNoticeSent 不重置（进程级：HUD 提示每次启动游戏最多一次）。
			g_uiChannel = UI::ChannelIdentity::unknown;
			g_uiChannelDead = false;

			// ★ 第 27 轮：「菜单还开着，脚本不会响应」说明是**每菜单一次**（见 PollGuideVerify）。
			g_guide.verifyWaitNoted = false;

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
			// ★ 第 27 轮：入口条目表一并报出来 —— 排查「入口没显示」先看这里。
			//   ★ 第 80 轮：两类（任务板 + 提供无限任务的 NPC），数字让排查一眼能对账。
			REX::INFO("数据源：{}；入口条目表={} 条（任务板 {} + 可重复 NPC {}）",
				masters, kEntryTableSize, kEntryBoardCount, kEntryNpcCount);
			// ★ 第 46 轮：**无论开没开都打这一行**。起因：ini 写 `Mode=6` 而解析层把未知值
			//   静默折成 0 时，日志里**一行都没有** —— 玩家只知道「过滤没生效」，无从下手。
			//   现在 mode=0 也会写 `测试模式：0（关闭（显示全部））[来源=ini]`，
			//   一眼能看出「ini 读到了、但值是 0」和「ini 根本没读到（来源=默认）」的区别。
			REX::INFO("测试模式：{}（{}）[来源={}] —— 控制台 set SAQ_TestMode to 0 或改 ini，均可关闭",
				testMode.mode, TestModeNote(testMode.mode), testMode.source);
			REX::INFO("{}", FormatRuntimeStats(g_pending.stats));
			// ★★ 第 75 轮：「固定显示」的两类条目单独一行（拆行的理由见 FormatPinStats）。
			{
				const auto pinLine = FormatPinStats(g_pending.stats);
				if (!pinLine.empty()) {
					REX::INFO("{}", pinLine);
				}
			}
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

		// Tick 停顿检测（第 11 轮；★ 第 27 轮加「有事在等」条件）。
		//
		// 目的：当**我们确实有事情在等**（推送重试中 / 引导确认窗口开着）而 Tick 被卡住时，
		// 日志要能证明「不是我们的重试慢，是主线程被别的东西占了」。
		//
		// ★ 第 27 轮修正：原来只要菜单开着、Tick 间隔 >1 秒就记 —— 实测全是噪声：
		//   7.7s / 8.6s / 14.8s 是玩家在菜单里浏览（我们根本没有任何待办），432s 是挂机/切出
		//   游戏，而同一会话里推送耗时全是 0~15ms —— 没有一行指向真正的卡顿。
		//   现在只在 pending/verify 未完成时统计（有那两类日志可交叉验证才值得记）。
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

			// 停顿检测：菜单开着、且我们有事在等（推送重试 / 引导确认）时，
			// 两次 Tick 的间隔超过 1 秒就记一行（含被卡了多久）。见上面的第 27 轮说明。
			const bool watchStall = open && (!g_pending.done || g_guide.verifyAtMs != 0);
			if (watchStall) {
				const auto now = NowMs();
				if (s_tickWatermark != 0 && now - s_tickWatermark >= kTickStallMs) {
					REX::WARN("主线程停顿：距上次 Tick {} ms（菜单开着且有待办；停顿多半来自引擎/其它插件或切出游戏）",
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
			} else {
				// ★★ 第 62 轮补：先判「世界就绪」——「任务菜单没开」≠「游戏世界里」
				//   （主菜单 / 加载画面 / 过渡黑屏也走这个分支，见 WorldBusyForUpkeep 的推导）。
				//   读档窗口里引擎正在卸载/重建世界数据，例行认领/候选复算的成串引擎查询
				//   会把半成品状态当正常数据用（12:31 会话实测：静态表预建落在读档窗口内，
				//   读档随后失败退回主菜单，6 秒后引擎空指针崩溃）。
				if (WorldBusyForUpkeep()) {
					NoteWorldBusyEntered();
				} else {
					ResetWorldBusyNote();
					// ★ 第 32 轮：菜单关着时先做例行认领/对账 —— 玩家重启游戏后直接读档看 HUD
					//   （不进菜单）时，只有这里能把「存档里遗留的引导」认领回来，让下面那句
					//   动态更新把蓝点挪到板上。（函数内部按 2 秒自我节流。）
					PollGuideUpkeep();
					// ★ 第 31 轮：菜单关着时才算「入口条目的引导目标能不能更精确」
					//   （玩家从远处选完就关菜单去赶路 —— 蓝点该在到达后自动上板）。
					//   函数内部按 lastTargetCheckMs 自我节流，没在引导时零开销。
					UpdateEntryGuideTarget();
				}
			}

			// ★ 第 17 轮：引导结果确认 —— **菜单关掉之后也要继续跑**
			//   （脚本在菜单关闭时会立刻应用一次引导，玩家点完往往马上关菜单去看 HUD 上的蓝点；
			//    这里只读 ESM 的 GLOB + 静态表，不碰 UI，所以关着菜单调用是安全的。
			//    函数内部用 verifyAtMs==0 自我短路，没请求时零开销。）
			//   ★ 第 19 轮：把 open 传进去 —— 超时/失败时要回写界面（菜单开着才做）。
			PollGuideVerify(open);

			// ★ 第 37 轮：SET COURSE 的星图这一半 —— 到点后查一次 **GalaxyStarMapMenu**
			//   （引擎自己的注册名，第 41 轮修正）在不在屏幕上，把「R 键链路通没通」写进
			//   日志（内部按 pending/dueMs 自我短路）。
			CheckStarMapOpened();

			// ★ 第 19 轮：脚本活性探测（菜单打开 1.5 秒后复读通知值，见 CheckScriptLiveness）。
			//   内部按「是否武装 + 到点没有」自我短路，菜单关着/没请求时零开销。
			if (open) {
				CheckScriptLiveness();
			}

			// ★★ 第 49 轮：引擎内 harness（自动化测试）的用例驱动器。
			//   放在最后：它可能自己开/关菜单、下命令、读界面报告，让「产品路径」先跑完。
			//   ini 里 [Test] Harness=0 时这里是**一次 bool 判断**（零开销）。
			//   ★ 第 53 轮：发布构建（SAQ_WITH_HARNESS=0）里整段不编译 —— 不存在。
#if SAQ_WITH_HARNESS
			Test::Tick(open);
#endif
		}
	}

	// ★★★ 第 133 轮（P3 产品化 PoC · docs/15 11.7）：见 SAQ.h 里的说明。
	const std::vector<QuestEntry>& PendingQuests()
	{
		return g_pending.quests;
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

#if SAQ_WITH_HARNESS
		// ★★ 第 49 轮：引擎内 harness（自动化测试）。
		//   ① 装日志环形缓冲（断言要「本步骤之后有没有出现某行」——比读日志文件可靠：
	//      文件有上限、会滚动清空；★ 第 112 轮起上限可配，默认发布 1MB / 开发 10MB）；
		//      必须在 ApplyLogSizeLimit 之后调，否则 sink 会被那次 clear() 清掉）；
		//   ② 读 ini + 用例文件（[Test] Harness=0 时不读、不注册任何东西）。
		Test::InstallLogRing();
		Test::LoadPlan();
#else
		// ★ 第 53 轮（大项 F）：发布构建（SAQ_WITH_HARNESS=0）—— 没有 harness；
		//   ini 里若是 Harness=1 就明确 WARN（不静默）。
		WarnIfHarnessRequestedWithoutSupport();
#endif

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
