#include "PCH.h"

#include "SAQ_UiInject.h"

// ★ 第 36/84 轮同款依赖：日志截断按 UTF-8 字符边界（证据通道纪律）。
#include "SAQ_Decision.h"

// ★ 第 137 轮（P3-b）：产品路径的数据源（`SAQ::PendingQuests()` —— 与 SWF 推送同一份数据）。
#include "SAQ.h"

// 解析层复用（找菜单那条链与通道形态无关 —— 见头文件说明）。
#include "SAQ_UI.h"

#include "RE/B/BSFixedString.h"
// 注意 include 顺序：ASMovieRootBase.h 不自包含（Value/Movie/FunctionHandler 都要先有），
// 顺序错了会报 C4430/C2061 一连串语法错误（与 SAQ_UI.cpp 同款，见 docs/01 坑 1）。
#include "RE/S/ScaleformGFxMovie.h"
#include "RE/S/ScaleformGFxValue.h"
#include "RE/S/ScaleformGFxFunctionHandler.h"
#include "RE/S/ScaleformGFxASMovieRootBase.h"

#include <Windows.h>

#include <atomic>
#include <format>
#include <string>

// ★★ 第 137 轮（P3-b）：本文件**不再整体**包在 SAQ_WITH_HARNESS 里 ——
//   上部 = 产品路径（发布构建也编译：前缀探测 / 完整描述 / 激活 / watchdog），
//   下部（文件末尾的 `#if SAQ_WITH_HARNESS`）= harness 探针 `RunInjectPoC`
//   （`ui.inject` 原语的判据链路，输出格式与第 133~135 轮逐字一致）。
namespace SAQ::UiInject
{
	namespace
	{
		// ====================================================================
		// 一、GFx 安全调用工具
		//
		// 本组函数与 SAQ_UI.cpp 的同名实现**同源**（那边在匿名 namespace 里、未导出；
		// 这里复制一份保持本模块独立 —— 玩家要求「随时可返回 SWF 版本」：注入层
		// 不依赖 SWF 通道的实现细节）。行为纪律完全一致：
		//   · 每一步都包 SEH（猜错最多返回失败，不会把游戏带崩）；
		//   · 调虚函数前用 VtableSlotInModule 核对槽位落在主模块。
		// ★ 改动本组函数时，SAQ_UI.cpp 的同名实现要同步（反之亦然）。
		// ====================================================================

		std::uintptr_t ModuleBase()
		{
			static const std::uintptr_t base = reinterpret_cast<std::uintptr_t>(::GetModuleHandleW(nullptr));
			return base;
		}

		std::size_t ModuleSize()
		{
			static const std::size_t size = [] {
				const auto base = ModuleBase();
				const auto* dos = reinterpret_cast<const IMAGE_DOS_HEADER*>(base);
				if (!base || dos->e_magic != IMAGE_DOS_SIGNATURE) {
					return std::size_t{ 0x8000000 };
				}
				const auto* nt = reinterpret_cast<const IMAGE_NT_HEADERS64*>(
					base + static_cast<std::uintptr_t>(dos->e_lfanew));
				return static_cast<std::size_t>(nt->OptionalHeader.SizeOfImage);
			}();
			return size;
		}

		bool VtableSlotInModule(const void* a_obj, std::size_t a_slot)
		{
			__try {
				const auto vtable = *reinterpret_cast<const std::uintptr_t* const*>(a_obj);
				const auto fn = vtable[a_slot];
				return fn >= ModuleBase() && fn < ModuleBase() + ModuleSize();
			} __except (EXCEPTION_EXECUTE_HANDLER) {
				return false;
			}
		}

		constexpr std::size_t kSlotAsRootCreateObject = 0x2E;    // CreateObject(Value*, className, args, n)
		constexpr std::size_t kSlotAsRootCreateArray = 0x2F;     // CreateArray(Value*)
		constexpr std::size_t kSlotAsRootCreateFunction = 0x30;  // CreateFunction(Value*, FunctionHandler*, void*)
		constexpr std::size_t kSlotAsRootGetVariable = 0x32;     // GetVariable(Value*, const char*) const

		bool SafeGetVariable(RE::Scaleform::GFx::ASMovieRootBase* a_root, const char* a_path,
			RE::Scaleform::GFx::Value* a_out)
		{
			__try {
				return a_root->GetVariable(a_out, a_path);
			} __except (EXCEPTION_EXECUTE_HANDLER) {
				return false;
			}
		}

		bool SafeCreateObject(RE::Scaleform::GFx::ASMovieRootBase* a_root, RE::Scaleform::GFx::Value* a_out)
		{
			__try {
				a_root->CreateObject(a_out);
				return true;
			} __except (EXCEPTION_EXECUTE_HANDLER) {
				return false;
			}
		}

		bool SafeCreateArray(RE::Scaleform::GFx::ASMovieRootBase* a_root, RE::Scaleform::GFx::Value* a_out)
		{
			__try {
				a_root->CreateArray(a_out);
				return true;
			} __except (EXCEPTION_EXECUTE_HANDLER) {
				return false;
			}
		}

		bool SafeCreateString(RE::Scaleform::GFx::ASMovieRootBase* a_root, RE::Scaleform::GFx::Value* a_out,
			const char* a_utf8)
		{
			__try {
				a_root->CreateString(a_out, a_utf8);
				return true;
			} __except (EXCEPTION_EXECUTE_HANDLER) {
				return false;
			}
		}

		bool SafeCreateFunction(RE::Scaleform::GFx::ASMovieRootBase* a_root, RE::Scaleform::GFx::Value* a_out,
			RE::Scaleform::GFx::FunctionHandler* a_handler, void* a_userData)
		{
			__try {
				a_root->CreateFunction(a_out, a_handler, a_userData);
				return true;
			} __except (EXCEPTION_EXECUTE_HANDLER) {
				return false;
			}
		}

		bool SafeValueGetMember(RE::Scaleform::GFx::Value* a_obj, const char* a_name,
			RE::Scaleform::GFx::Value* a_out)
		{
			__try {
				return a_obj->GetMember(a_name, a_out);
			} __except (EXCEPTION_EXECUTE_HANDLER) {
				return false;
			}
		}

		bool SafeValueSetMember(RE::Scaleform::GFx::Value* a_obj, const char* a_name,
			const RE::Scaleform::GFx::Value& a_value)
		{
			__try {
				return a_obj->SetMember(a_name, a_value);
			} __except (EXCEPTION_EXECUTE_HANDLER) {
				return false;
			}
		}

		bool SafeValueInvoke(RE::Scaleform::GFx::Value* a_obj, const char* a_name,
			RE::Scaleform::GFx::Value* a_result, RE::Scaleform::GFx::Value* a_args, std::size_t a_count)
		{
			__try {
				return a_obj->Invoke(a_name, a_result, a_args, a_count);
			} __except (EXCEPTION_EXECUTE_HANDLER) {
				return false;
			}
		}

		bool SafeValuePushBack(RE::Scaleform::GFx::Value* a_arr, const RE::Scaleform::GFx::Value& a_value)
		{
			__try {
				return a_arr->PushBack(a_value);
			} __except (EXCEPTION_EXECUTE_HANDLER) {
				return false;
			}
		}

		bool SafeReadValueNumber(const RE::Scaleform::GFx::Value& a_value, double& a_out)
		{
			__try {
				if (a_value.IsInt()) {
					a_out = static_cast<double>(a_value.GetInt());
					return true;
				}
				if (a_value.IsUInt()) {
					a_out = static_cast<double>(a_value.GetUInt());
					return true;
				}
				if (a_value.IsNumber()) {
					a_out = a_value.GetNumber();
					return true;
				}
				if (a_value.IsBoolean()) {
					a_out = a_value.GetBoolean() ? 1.0 : 0.0;
					return true;
				}
			} __except (EXCEPTION_EXECUTE_HANDLER) {
			}
			return false;
		}

		// POD 输出（避免 C2712：含 __try 的函数不能用需要 unwind 的对象 —— 与 SAQ_UI.cpp 同款）。
		bool SafeReadValueString(const RE::Scaleform::GFx::Value& a_value, char* a_out, std::size_t a_outSize)
		{
			a_out[0] = '\0';
			__try {
				if (a_value.IsString()) {
					const char* s = a_value.GetString();
					if (s) {
						std::size_t i = 0;
						for (; i + 1 < a_outSize && s[i] != '\0'; ++i) {
							a_out[i] = s[i];
						}
						a_out[i] = '\0';
						return true;
					}
				}
			} __except (EXCEPTION_EXECUTE_HANDLER) {
			}
			return false;
		}

		bool SafeReadValueBool(const RE::Scaleform::GFx::Value& a_value, bool& a_out)
		{
			__try {
				if (a_value.IsBoolean()) {
					a_out = a_value.GetBoolean();
					return true;
				}
				return false;
			} __except (EXCEPTION_EXECUTE_HANDLER) {
				return false;
			}
		}

		// 日志转义 + 截断（与 SAQ_UI.cpp 的 EscapeForLog 同源：截断按 UTF-8 字符边界）。
		std::string EscapeForLog(std::string_view a_text, std::size_t a_maxLen = 0)
		{
			const std::size_t take = Decision::Utf8SafeCut(a_text, a_maxLen);
			const bool clipped = take < a_text.size();
			std::string out;
			out.reserve(take + 8);
			for (std::size_t i = 0; i < take; ++i) {
				switch (a_text[i]) {
				case '\n': out += "\\n"; break;
				case '\r': out += "\\r"; break;
				case '\t': out += "\\t"; break;
				default: out += a_text[i]; break;
				}
			}
			if (clipped) {
				out += "…";
			}
			return out;
		}

		std::string NumStr(double a_v)
		{
			if (a_v < 0.0) {
				return "?";
			}
			return std::format("{:.0f}", a_v);
		}

		std::string MaskHex(double a_mask)
		{
			if (a_mask < 0.0) {
				return "?";
			}
			return std::format("0x{:08X}", static_cast<std::uint32_t>(static_cast<std::uint64_t>(a_mask)));
		}

		// 单调毫秒（watchdog / 激活节流用；与 SAQ.cpp 的 NowMs 同源 = GetTickCount64）。
		std::uint64_t NowMs()
		{
			return ::GetTickCount64();
		}

		// UTF-8 里的 CJK 统计（3 字节序列、前导字节 E4~E9 = U+4000~U+9FFF）——
		// 与 SWF 版 `SaqNameVerdict` / 探针 U8a 同源（引擎任务名是本地化的）。
		std::size_t CountCjkUtf8(const std::string& a_text)
		{
			std::size_t n = 0;
			for (std::size_t i = 0; i + 2 < a_text.size(); ++i) {
				const auto c = static_cast<unsigned char>(a_text[i]);
				if (c >= 0xE4 && c <= 0xE9) {
					++n;
				}
			}
			return n;
		}

		// ====================================================================
		// 二、产品常量（与 SWF 版 / 探针同源）
		// ====================================================================

		constexpr std::uint32_t kAvailableQuestType = 6;                  // QuestUtils.AVAILABLE_QUEST_TYPE
		constexpr std::uint32_t kOurTabFlag = 1u << kAvailableQuestType;   // 64 = 我们 tab 的掩码位
		constexpr const char*   kEventName = "BSTabbedSelection::selectionChange";
		constexpr std::uint32_t kInterceptPriority = 100;                  // 原版 onFilterChanged 是 0
		constexpr const char*   kTabTitleZh = "可接任务";
		constexpr const char*   kTabTitleEn = "Available";
		// 入口条目类型（与 SWF 版同源：MissionMenu.as 的 SAQ_ENTRY_TYPE / SAQ_REPEAT_NPC_TYPE）。
		constexpr std::int32_t  kEntryBoardType = 100;   // 任务板（无限任务入口）
		constexpr std::int32_t  kNpcEntryType = 101;     // 提供无限任务的 NPC
		// ★★ 第 137 轮（P3-b）：产品路径节拍 —— 激活重试 150ms（菜单可能还没建好）、
		//   watchdog 500ms（与 SAQ.cpp 的界面状态轮询同拍）。
		constexpr std::uint64_t kActivateRetryMs = 150;
		constexpr std::uint64_t kWatchdogIntervalMs = 500;

		// 原版 7 个 tab（text = 本地化键、flag = 掩码位）—— 从 SWF 版 PopulateTabs 逐项抄来
		//   （QuestUtils 枚举：ACTIVITY=0 / MAIN=1 / FACTION=2 / MISC=3 / MISSION=4 /
		//    COMPLETED=5 / AVAILABLE=6）。
		//   ★ `$ALL` 用**原版值** 0xFFFFFFFF（SWF 版改成 0xFFFFFFBF 是因为它一次性合并列表；
		//   注入形态没有这个需要 —— 我们 tab 之外列表已被恢复成引擎数据，不会污染「全部」）。
		struct TabDef
		{
			const char*   text;
			std::uint32_t flag;
		};
		constexpr TabDef kOriginalTabs[7] = {
			{ "$ALL", 0xFFFFFFFFu },
			{ "$Main", 1u << 1 },
			{ "$Faction", 1u << 2 },
			{ "$Misc", 1u << 3 },
			{ "$MISSION", 1u << 4 },
			{ "$Activity", 1u << 0 },
			{ "$Completed", 1u << 5 },
		};

		// ====================================================================
		// 三、注入上下文与拦截 handler
		//
		// 生命周期：静态存储（进程内一份）—— 每次 PoC 开始时重置。
		//   ★ 为什么不能用栈上的局部：handler 是**异步**的（玩家在眼睛窗口里切 tab
		//   也会触发），必须活到菜单关闭；GFx::Value 成员在菜单关闭（Movie 销毁）后
		//   失效，但那时也不会有新事件（读失效值被 SEH 挡下，返回失败）。
		// ====================================================================

		struct InjectCtx
		{
			RE::Scaleform::GFx::Value list;            // MissionsList_mc
			RE::Scaleform::GFx::Value ourEntries;      // 我们构造的条目数组
			RE::Scaleform::GFx::Value engineSnapshot;  // 引擎快照（同一批条目对象的引用数组）
			int                       ourTabIndex{ -1 };
			std::uint32_t             engineCount{};
			std::uint32_t             injectCount{};
			bool                      inOurTab{ false };
			// 对账期望（前两条：uID / 显示名 / 可导航）
			std::uint32_t expectUid[2]{};
			std::string   expectName[2];
			bool          expectNav[2]{};
			// ★★ 第 137 轮（P3-b 产品路径）：
			bool                      menuActive{ false };   // 本菜单已激活注入形态
			bool                      listening{ false };    // 本菜单已挂过拦截监听（防重复挂）
			// ★★★ 第 138 轮（P2 会话收口）：走到快照/构造/扩tab/监听任一失败 = 决定性
			//   失败 ⇒ 本菜单周期不再重试（防 150ms 级重试刷屏 + 每拍全量重建开销）。
			bool                      activateFailed{ false };
			std::uint32_t             replayCount{};         // watchdog 重放次数（引擎覆盖后）
			std::uint64_t             lastWatchdogMs{};      // watchdog 节拍（500ms）
		};

		InjectCtx  g_ctxStore;
		InjectCtx* g_ctx = nullptr;

		bool InitializeEntries(RE::Scaleform::GFx::Value& a_list, RE::Scaleform::GFx::Value& a_arr)
		{
			RE::Scaleform::GFx::Value ret;
			return SafeValueInvoke(&a_list, "InitializeEntries", &ret, &a_arr, 1);
		}

		bool InjectOurEntries(InjectCtx& a_ctx)
		{
			return InitializeEntries(a_ctx.list, a_ctx.ourEntries);
		}

		bool RestoreEngineEntries(InjectCtx& a_ctx)
		{
			return InitializeEntries(a_ctx.list, a_ctx.engineSnapshot);
		}

		class InjectHandler : public RE::Scaleform::GFx::FunctionHandler
		{
		public:
			void Call(const Params& a_params) override
			{
				int idx = -1;
				if (a_params.argCount >= 1 && a_params.args) {
					RE::Scaleform::GFx::Value iv;
					double                  d = -1.0;
					if (a_params.args[0].GetMember("iSelectedIndex", &iv) && SafeReadValueNumber(iv, d)) {
						idx = static_cast<int>(d);
					}
				}
				const int n = ++s_calls;
				s_lastIndex = idx;
				if (!g_ctx) {
					REX::INFO("界面注入：事件回调（第 {} 次 idx={}）—— 上下文未建立，忽略", n, idx);
					return;
				}
				if (idx == g_ctx->ourTabIndex) {
					// 切到我们 tab：先拦原版（priority=0 的 onFilterChanged 会读
					//   FilterInfoA[7].flag —— 原版数组只有 7 项 ⇒ 越界 TypeError），
					//   再自己设 mask + 注入我们的条目。
					RE::Scaleform::GFx::Value ret;
					if (a_params.argCount >= 1 && a_params.args) {
						(void)SafeValueInvoke(&a_params.args[0], "stopImmediatePropagation", &ret,
							nullptr, 0);
					}
					RE::Scaleform::GFx::Value f(static_cast<std::uint32_t>(kOurTabFlag));
					const bool maskOk = SafeValueSetMember(&g_ctx->list, "filterMask", f);
					const bool inj = InjectOurEntries(*g_ctx);
					g_ctx->inOurTab = true;
					++s_injects;
					REX::INFO("界面注入：切到我们的 tab（idx={}）→ mask=0x{:X}{} + 注入 {} 条（{}）",
						idx, kOurTabFlag, maskOk ? "" : "（写入失败！）", g_ctx->injectCount,
						inj ? "ok" : "fail");
				} else if (g_ctx->inOurTab) {
					// 从我们 tab 切走：**先恢复引擎快照再放行** ——
					//   原版 onFilterChanged（接下来执行）只设 filterMask、不重建列表；
					//   不恢复的话列表里只有我们的条目 ⇒ 被新掩码过滤掉 ⇒ 空列表。
					const bool ok = RestoreEngineEntries(*g_ctx);
					g_ctx->inOurTab = false;
					++s_restores;
					REX::INFO("界面注入：从我们的 tab 切走（idx={}）→ 恢复引擎列表（{}）",
						idx, ok ? "ok" : "fail");
				}
			}

			static std::atomic<int> s_calls;
			static std::atomic<int> s_injects;
			static std::atomic<int> s_restores;
			static std::atomic<int> s_lastIndex;
		};
		std::atomic<int> InjectHandler::s_calls{ 0 };
		std::atomic<int> InjectHandler::s_injects{ 0 };
		std::atomic<int> InjectHandler::s_restores{ 0 };
		std::atomic<int> InjectHandler::s_lastIndex{ -1 };

		// ★★ 第 137 轮（P3-b）：静态实例 —— 产品路径每次菜单激活都会挂拦截监听，
		//   复用同一实例（`new` 一次性的旧写法在「每菜单激活」下会累积泄漏）。
		//   AS3 的 addEventListener 对同一 listener 重复添加会被引擎忽略，安全。
		InjectHandler g_handler;

		// 挂 priority=100 的拦截监听（产品路径与 harness 共用）。
		bool AttachInterceptListener(RE::Scaleform::GFx::ASMovieRootBase* a_root,
			RE::Scaleform::GFx::Value& a_tabSel)
		{
			RE::Scaleform::GFx::Value fn;
			if (!(VtableSlotInModule(a_root, kSlotAsRootCreateFunction) &&
					SafeCreateFunction(a_root, &fn, &g_handler, nullptr))) {
				return false;
			}
			RE::Scaleform::GFx::Value evTitle;
			if (!SafeCreateString(a_root, &evTitle, kEventName)) {
				return false;
			}
			RE::Scaleform::GFx::Value args[5];
			args[0] = evTitle;
			args[1] = fn;
			args[2] = false;
			args[3] = static_cast<std::uint32_t>(kInterceptPriority);
			args[4] = false;
			RE::Scaleform::GFx::Value ret;
			return SafeValueInvoke(&a_tabSel, "addEventListener", &ret, args, 5);
		}

		// ====================================================================
		// 四、数据构造（QuestEntry → AS3 条目 / 名字 / 描述 / 置灰）
		// ====================================================================

		// 语言判定（探针 U8a 同源）：扫引擎前几条条目的名字，任一含 CJK ⇒ 中文。
		//   （比只看第一条稳：首条可能是纯数字/符号的任务名。）
		bool DetectUseChinese(RE::Scaleform::GFx::Value& a_list, bool& a_out, std::size_t& a_sampleCjk)
		{
			double count = 0.0;
			{
				RE::Scaleform::GFx::Value v;
				if (!(SafeValueGetMember(&a_list, "entryCount", &v) && SafeReadValueNumber(v, count)) ||
					count <= 0.0) {
					return false;
				}
			}
			const auto scan = static_cast<std::uint32_t>(count < 8.0 ? count : 8.0);
			std::size_t cjk = 0;
			for (std::uint32_t i = 0; i < scan; ++i) {
				RE::Scaleform::GFx::Value arg(static_cast<std::int32_t>(i));
				RE::Scaleform::GFx::Value entry;
				if (!SafeValueInvoke(&a_list, "GetDataForEntry", &entry, &arg, 1) || !entry.IsObject()) {
					continue;
				}
				RE::Scaleform::GFx::Value nm;
				char                    buf[256]{};
				if (SafeValueGetMember(&entry, "sName", &nm) && SafeReadValueString(nm, buf, sizeof(buf))) {
					cjk += CountCjkUtf8(buf);
					if (cjk > 0) {
						break;
					}
				}
			}
			a_sampleCjk = cjk;
			a_out = cjk > 0;
			return true;
		}

		// 显示名 = 前缀（可重复在前、不可导航在后 —— 与 SWF 版 SaqBuildEntry 同序）+ 名字。
		std::string BuildDisplayName(const QuestEntry& a_e, bool a_zh)
		{
			std::string out;
			if (a_e.repeatable) {
				out += a_zh ? "（可重复）" : "(Repeatable) ";
			}
			if (!a_e.hasGuideTarget) {
				out += a_zh ? "（不可导航）" : "(Not navigable) ";
			}
			out += a_zh ? a_e.nameZh : a_e.nameEn;
			return out;
		}

		// ★ 第 15 轮（SWF 版 SaqCourseKeyName 同源）：按键名 ——「设定航线」在当前控制
		//   映射下 = 键盘 R / 手柄 X 键等（**不要写死键名**）。取不到 ⇒ 空串
		//   （文案走「使用底部的『设定航线』」分支，安全降级）。
		std::string GetCourseKeyName(RE::Scaleform::GFx::ASMovieRootBase* a_root,
			RE::Scaleform::GFx::Value& a_menu)
		{
			RE::Scaleform::GFx::Value helper;
			if (!(SafeValueGetMember(&a_menu, "KeyHelper", &helper) && helper.IsObject())) {
				return {};
			}
			RE::Scaleform::GFx::Value args[2];
			if (!(SafeCreateString(a_root, &args[0], "XButton") &&
					SafeCreateString(a_root, &args[1], ""))) {
				return {};
			}
			RE::Scaleform::GFx::Value ret;
			if (!SafeValueInvoke(&helper, "GetButtonNameForEvent", &ret, args, 2)) {
				return {};
			}
			char buf[64]{};
			if (SafeReadValueString(ret, buf, sizeof(buf))) {
				return buf;
			}
			return {};
		}

		// 描述文案 —— ★★ 第 137 轮（P3-b）：SWF 版 `SaqDescriptionText`
		//   （MissionMenu.as 882~983 行）的**逐字迁移** —— 中英两套 / 按键名分支 /
		//   入口（板 100 / NPC 101）/ 同伴 / 简要说明 / 「需要靠近」全部分支。
		//   参数对齐（同 SWF 版）：hasGuideTarget / type / needsApproach /
		//   companionPinned / note（noteZh·En）；a_key = 按键名（空串 = 取不到）。
		//   ★ 改文案时两处要同步（SWF 版 SaqDescriptionText + 这里）。
		std::string BuildDescription(const QuestEntry& a_e, bool a_zh, const std::string& a_key)
		{
			// —— 入口分支（任务板 / 可重复 NPC；uID = 世界引用，没有「接取地点」）——
			if (a_e.type == kEntryBoardType || a_e.type == kNpcEntryType) {
				if (!a_e.hasGuideTarget) {
					return a_zh ?
						"暂时无法导航 —— 这个位置此刻取不到（多半是所在区域还没加载出来）。"
						"稍后重新打开一次任务菜单再试。" :
						"Cannot navigate right now - the location is not available at the moment "
						"(its area has not loaded yet). Reopen the mission menu and try again.";
				}
				const bool hasKey = !a_key.empty();
				if (a_e.type == kNpcEntryType) {
					if (!hasKey) {
						return a_zh ?
							"这位 NPC 会不断提供可重复任务 —— 与他交谈就能接到赏金、运输、勘探等不断刷新"
							"的任务。使用底部的「设定航线」即可引导到他的位置。" :
							"This NPC offers repeatable jobs - talk to them to pick up endlessly "
							"refreshing missions (bounties, transport, survey...). "
							"Use SET COURSE to be guided to their location.";
					}
					return a_zh ?
						"这位 NPC 会不断提供可重复任务 —— 与他交谈就能接到赏金、运输、勘探等不断刷新"
						"的任务。按 " + a_key + "（设定航线）即可引导到他的位置。" :
						"This NPC offers repeatable jobs - talk to them to pick up endlessly "
						"refreshing missions (bounties, transport, survey...). Press " + a_key +
						" (SET COURSE) to be guided to their location.";
				}
				if (!hasKey) {
					return a_zh ?
						"这是一块任务板 —— 与它交互就能接到赏金、运输、勘探等不断刷新的任务。"
						"使用底部的「设定航线」即可引导到它的位置。" :
						"This is a mission board - interact with it to pick up endlessly refreshing "
						"jobs (bounties, transport, survey...). Use SET COURSE to be guided to its location.";
				}
				return a_zh ?
					"这是一块任务板 —— 与它交互就能接到赏金、运输、勘探等不断刷新的任务。"
					"按 " + a_key + "（设定航线）即可引导到它的位置。" :
					"This is a mission board - interact with it to pick up endlessly refreshing "
					"jobs (bounties, transport, survey...). Press " + a_key +
					" (SET COURSE) to be guided to its location.";
			}

			// —— 首句：简要说明（势力开头任务）> 同伴 > 普通 ——
			std::string s;
			const std::string& note = a_zh ? a_e.noteZh : a_e.noteEn;
			if (!note.empty()) {
				s = note;
			} else if (a_e.companionPinned) {
				s = a_zh ?
					"这条同伴任务会在你与这位同伴的好感度达到一定水平后自动开始，不需要找地方接取"
					"（在那之前它会一直显示在这里）。好感度要靠带这位同伴一起冒险来提升；"
					"「设定航线」引导到的是这位同伴当前所在的位置。" :
					"This companion quest starts automatically once your affinity with the companion is "
					"high enough - there is nothing to accept (it stays listed here until then). "
					"Affinity grows while the companion travels with you; SET COURSE leads to wherever "
					"the companion currently is.";
			} else {
				s = a_zh ? "这条任务当前可以接取。" : "This quest is currently available.";
			}
			// 「需要靠近」句（第 46 轮；只有全非常驻候选的任务会带）。
			const std::string approach = a_e.needsApproach ?
				(a_zh ?
					" 注意：它的导航目标要靠近目标区域后才加载 —— 距离较远时按「设定航线」可能暂时"
					"看不到标记（靠近后会自动生效）。" :
					" Note: its navigation target loads only when you are near its area - from a "
					"distance SET COURSE may show no marker at first (it starts automatically once "
					"you get closer).") :
				std::string{};

			// —— 无导航目标（第 23/75/82 轮三分支）——
			if (!a_e.hasGuideTarget) {
				if (!note.empty()) {
					s += a_zh ?
						"它没有可以直接导航的接取地点 —— 按上面的说明推进即可。" :
						" There is no direct pickup location to navigate to - follow the note above.";
				} else if (a_e.companionPinned) {
					s += a_zh ?
						"但它暂时还没有导航目标 —— 无法引导到这位同伴的位置（条目照常显示）。" :
						" It has no navigation target yet, so it cannot guide you to the companion's "
						"location (the entry stays listed).";
				} else {
					s += a_zh ?
						"但它暂时还没有导航目标 —— 无法引导到接取地点（任务本身照常显示）。" :
						" It has no navigation target yet, so it cannot guide you to the pickup location.";
				}
				return s + approach;
			}

			// —— 有导航目标（尾部句：同伴 / 普通 × 有无按键名）——
			if (a_e.companionPinned) {
				if (a_key.empty()) {
					s += a_zh ?
						"使用底部的「设定航线」即可引导到这位同伴的位置。" :
						" Use SET COURSE to be guided to the companion's location.";
				} else {
					s += a_zh ?
						"按 " + a_key + "（设定航线）即可引导到这位同伴的位置。" :
						" Press " + a_key + " (SET COURSE) to be guided to the companion's location.";
				}
				return s + approach;
			}
			if (a_key.empty()) {
				s += a_zh ?
					"展开后选中目标，或使用底部的「设定航线」即可引导到接取地点。" :
					" Expand it, then select the objective or use SET COURSE to be guided to the "
					"pickup location.";
			} else {
				s += a_zh ?
					"展开后选中目标，或按 " + a_key + "（设定航线）即可引导到接取地点。" :
					" Expand it, then select the objective or press " + a_key +
					" (SET COURSE) to be guided to the pickup location.";
			}
			return s + approach;
		}

		// 构造我们的条目数组。字段集 = 探针 v4 已验证的最小集 + 真实值（第 130/131 轮）。
		//   ★ 第 137 轮：a_courseKey = 按键名（完整描述文案的分支用；空串 = 取不到）。
		bool BuildOurEntries(RE::Scaleform::GFx::ASMovieRootBase* a_root,
			const std::vector<QuestEntry>& a_quests, bool a_zh, const std::string& a_courseKey,
			RE::Scaleform::GFx::Value& a_out, InjectCtx& a_ctx, const char*& a_why)
		{
			RE::Scaleform::GFx::Value arr;
			if (!(VtableSlotInModule(a_root, kSlotAsRootCreateArray) && SafeCreateArray(a_root, &arr))) {
				a_why = "CreateArray";
				return false;
			}
			std::uint32_t i = 0;
			for (const auto& e : a_quests) {
				RE::Scaleform::GFx::Value item;
				if (!SafeCreateObject(a_root, &item)) {
					a_why = "CreateObject";
					return false;
				}
				auto setU32 = [&item](const char* a_name, std::uint32_t a_v) {
					RE::Scaleform::GFx::Value x(a_v);
					(void)SafeValueSetMember(&item, a_name, x);
				};
				auto setI32 = [&item](const char* a_name, std::int32_t a_v) {
					RE::Scaleform::GFx::Value x(a_v);
					(void)SafeValueSetMember(&item, a_name, x);
				};
				auto setBool = [&item](const char* a_name, bool a_v) {
					RE::Scaleform::GFx::Value x(a_v);
					(void)SafeValueSetMember(&item, a_name, x);
				};
				auto setStr = [a_root, &item](const char* a_name, const std::string& a_v) {
					RE::Scaleform::GFx::Value x;
					if (SafeCreateString(a_root, &x, a_v.c_str())) {
						(void)SafeValueSetMember(&item, a_name, x);
					}
				};
				// 身份 / 过滤字段 —— uID = 真实任务 FormID（未来引导要用它反查）。
				setU32("uID", e.formID);
				setU32("uInstanceID", 0);
				setU32("iType", kAvailableQuestType);   // 原版 EntryFilterCompare 按 iType 过滤
				setI32("iFaction", e.faction);
				setBool("bComplete", false);
				setBool("bFailed", false);
				setBool("bActive", false);
				setI32("iRemainingTime", -1);           // <0 ⇒ 隐藏时间标签（渲染路径防御）
				{
					// aObjectives = 空数组：原版 `MissionsListEntry.IsMission` =
					//   `hasOwnProperty("aObjectives")` —— 缺它整批被过滤（第 121 轮真因）。
					RE::Scaleform::GFx::Value objs;
					if (VtableSlotInModule(a_root, kSlotAsRootCreateArray) &&
						SafeCreateArray(a_root, &objs)) {
						(void)SafeValueSetMember(&item, "aObjectives", objs);
					}
				}
				setStr("sName", BuildDisplayName(e, a_zh));
				setStr("sDescription", BuildDescription(e, a_zh, a_courseKey));
				// 「不可导航 ⇒ SET COURSE 置灰」是**数据驱动**的（docs/15 11.4-⑦ 已实测）。
				setBool("bCanShowOnMap", e.hasGuideTarget);
				if (i < 2) {
					a_ctx.expectUid[i] = e.formID;
					a_ctx.expectName[i] = BuildDisplayName(e, a_zh);
					a_ctx.expectNav[i] = e.hasGuideTarget;
				}
				if (!SafeValuePushBack(&arr, item)) {
					a_why = "PushBack";
					return false;
				}
				++i;
			}
			a_ctx.injectCount = i;
			a_out = arr;
			return true;
		}

		// 引擎快照：逐条 `GetDataForEntry(i)`（**引用**同一批条目对象）→ 数组。
		//   恢复 = InitializeEntries(快照) ⇒ 原版数据、字段、展开态都不丢。
		bool BuildEngineSnapshot(RE::Scaleform::GFx::ASMovieRootBase* a_root,
			RE::Scaleform::GFx::Value& a_list, RE::Scaleform::GFx::Value& a_out, std::uint32_t& a_count)
		{
			double count = -1.0;
			{
				RE::Scaleform::GFx::Value v;
				if (!(SafeValueGetMember(&a_list, "entryCount", &v) && SafeReadValueNumber(v, count)) ||
					count < 0.0) {
					return false;
				}
			}
			RE::Scaleform::GFx::Value arr;
			if (!(VtableSlotInModule(a_root, kSlotAsRootCreateArray) && SafeCreateArray(a_root, &arr))) {
				return false;
			}
			const auto n = static_cast<std::uint32_t>(count);
			for (std::uint32_t i = 0; i < n; ++i) {
				RE::Scaleform::GFx::Value arg(static_cast<std::int32_t>(i));
				RE::Scaleform::GFx::Value entry;
				if (!SafeValueInvoke(&a_list, "GetDataForEntry", &entry, &arg, 1) || !entry.IsObject()) {
					return false;
				}
				if (!SafeValuePushBack(&arr, entry)) {
					return false;
				}
			}
			a_out = arr;
			a_count = n;
			return true;
		}

		// 8 项 tab 数组（原版 7 项原样 + 我们的）。
		bool BuildTabsArray(RE::Scaleform::GFx::ASMovieRootBase* a_root, const char* a_title,
			RE::Scaleform::GFx::Value& a_out)
		{
			RE::Scaleform::GFx::Value arr;
			if (!(VtableSlotInModule(a_root, kSlotAsRootCreateArray) && SafeCreateArray(a_root, &arr))) {
				return false;
			}
			auto push = [a_root, &arr](const char* a_text, std::uint32_t a_flag) -> bool {
				RE::Scaleform::GFx::Value item;
				if (!SafeCreateObject(a_root, &item)) {
					return false;
				}
				RE::Scaleform::GFx::Value t;
				if (SafeCreateString(a_root, &t, a_text)) {
					(void)SafeValueSetMember(&item, "text", t);
				}
				RE::Scaleform::GFx::Value f(a_flag);
				(void)SafeValueSetMember(&item, "flag", f);
				return SafeValuePushBack(&arr, item);
			};
			for (const auto& t : kOriginalTabs) {
				if (!push(t.text, t.flag)) {
					return false;
				}
			}
			if (!push(a_title, kOurTabFlag)) {
				return false;
			}
			a_out = arr;
			return true;
		}
	}

	// ====================================================================
	// 五、产品路径（P3-b：UiMode 开关 / 菜单激活 / watchdog）
	//
	// 与 harness 探针（第六节 `RunInjectPoC`）的关系：两者共用第三节的上下文与
	// 第四节的构造器；探针跑「固定判据链路」（切 7 / 对账 / 切 0 / 再切 7），
	// 产品路径只做「激活 + 等玩家切 tab（拦截 handler 分时注入）+ watchdog」。
	// ====================================================================

	UiMode        g_mode{ UiMode::kAuto };   // 默认 auto（ini 未配置时）
	// ★★★ 第 138 轮（P2 会话收口）：harness `ui.mode` 的运行期强制标记（覆盖 ini 的
	//   ResolveUiMode —— 菜单打开时 SAQ.cpp 会再调一次 SetMode，强制期间被忽略）。
	//   目的 = 让 P2 计划的各用例互不干扰：探针（research3 / ui.inject）跑 `swf`
	//   干净环境（原版 7 tab），产品路径用例跑 `auto`。发布构建里恒 false。
	bool          g_modeForced{ false };
	std::uint64_t g_lastActivateTryMs{};

	void SetMode(UiMode a_mode)
	{
		if (g_modeForced) {
			return;   // 强制期间忽略 ini 解析结果（harness `ui.mode reset` 清除）
		}
		g_mode = a_mode;
	}

	UiMode GetMode()
	{
		return g_mode;
	}

	const char* ModeName(UiMode a_mode)
	{
		switch (a_mode) {
		case UiMode::kSwf:    return "swf";
		case UiMode::kInject: return "inject";
		default:              return "auto";
		}
	}

	bool MenuActive()
	{
		return g_ctx != nullptr && g_ctx->menuActive;
	}

	std::uint32_t ReplayCount()
	{
		return g_ctx != nullptr ? g_ctx->replayCount : 0;
	}

	// 形态是否需要注入（auto = 已判定「界面不是我们的」）。
	bool WantInject(bool a_uiChannelDead)
	{
		switch (g_mode) {
		case UiMode::kInject: return true;
		case UiMode::kAuto:   return a_uiChannelDead;
		default:              return false;   // swf：行为与现状逐字节不变
		}
	}

	// 激活（产品路径）—— 与探针的 R1~R6 同源，但不做「切 7 / 对账 / 恢复」
	//   （那是探针的判据链路；产品路径等玩家自己切 tab，由拦截 handler 完成分时注入）。
	//   幂等：OnMenuTick 每拍都会来问，成功激活后直接返回 true。
	bool ActivateForMenu()
	{
		if (g_ctxStore.menuActive && g_ctx == &g_ctxStore) {
			return true;
		}
		const auto& quests = SAQ::PendingQuests();
		if (quests.empty()) {
			// 数据还没收集好（菜单刚开）/ 这次没有可接任务 —— 静默（节流在 OnMenuTick）。
			return false;
		}
		std::string why;
		if (!UI::EnsureResolved(why)) {
			return false;   // 桥还没通（菜单刚创建）—— 下一拍再试
		}
		auto* root = reinterpret_cast<RE::Scaleform::GFx::ASMovieRootBase*>(UI::ResolvedAsMovieRoot());
		if (!root) {
			return false;
		}
		RE::Scaleform::GFx::Value menu;
		if (!(SafeGetVariable(root, "_root.Menu_mc", &menu) && menu.IsObject())) {
			return false;   // 原版 SWF 之外（我们的 SWF / 第三方）—— 不该走到这
		}
		RE::Scaleform::GFx::Value tabSel;
		RE::Scaleform::GFx::Value list;
		if (!(SafeValueGetMember(&menu, "TabbedFilterSelection_mc", &tabSel) && tabSel.IsObject() &&
				SafeValueGetMember(&menu, "MissionsList_mc", &list) && list.IsObject())) {
			return false;
		}

		auto readNum = [](RE::Scaleform::GFx::Value& a_obj, const char* a_name, double& a_out) -> bool {
			RE::Scaleform::GFx::Value v;
			return SafeValueGetMember(&a_obj, a_name, &v) && SafeReadValueNumber(v, a_out);
		};

		// 语言判定（引擎条目名 CJK；与探针 U8a 同源）。
		bool        zh = true;
		std::size_t sampleCjk = 0;
		(void)DetectUseChinese(list, zh, sampleCjk);

		// 读原 tab —— 激活对玩家「无感」：快照完切回去（原版读档恢复上次分类、
		//   玩家可能正停在某个分类上；切 0 只是拿全量快照的手段）。
		double originalTab = 0.0;
		(void)readNum(tabSel, "selectedIndex", originalTab);

		auto switchTab = [&tabSel](std::uint32_t a_idx) -> bool {
			RE::Scaleform::GFx::Value arg(static_cast<std::uint32_t>(a_idx));
			RE::Scaleform::GFx::Value ret;
			return SafeValueInvoke(&tabSel, "SetSelectedCategoryIndex", &ret, &arg, 1);
		};

		// 上下文（每次激活重建 —— 与探针同一纪律：handler 的全部路径都走 ctx.list，
		//   它在下面**立刻**被赋值；「上下文未接线」那类缺陷在第 135 轮已收口）。
		g_ctxStore = InjectCtx{};
		g_ctx = &g_ctxStore;
		InjectCtx& ctx = g_ctxStore;
		ctx.list = list;

		// 切 0（$ALL）→ 引擎快照（全量）→ 切回原 tab（在挂监听**之前**，走原版路径）。
		(void)switchTab(0);
		std::uint32_t snapCount = 0;
		const bool    snapOk = BuildEngineSnapshot(root, list, ctx.engineSnapshot, snapCount);
		ctx.engineCount = snapCount;

		// 我们的条目（真实数据 + 完整描述；按键名 = KeyHelper）。
		const std::string courseKey = GetCourseKeyName(root, menu);
		const char*       buildWhy = "ok";
		const bool        buildOk = BuildOurEntries(root, quests, zh, courseKey, ctx.ourEntries,
			ctx, buildWhy);

		// 扩 tab（原版 7 项 + 我们的 → SetTabsData）。
		RE::Scaleform::GFx::Value tabsArr;
		double                   tabs0 = -1.0, tabs1 = -1.0;
		bool                     tabsOk = false;
		if (readNum(tabSel, "numTabs", tabs0) &&
			BuildTabsArray(root, zh ? kTabTitleZh : kTabTitleEn, tabsArr)) {
			RE::Scaleform::GFx::Value ret;
			tabsOk = SafeValueInvoke(&tabSel, "SetTabsData", &ret, &tabsArr, 1) &&
				readNum(tabSel, "numTabs", tabs1) && tabs1 == tabs0 + 1.0;
			ctx.ourTabIndex = static_cast<int>(tabs0);
		}

		// 挂拦截监听（priority=100）。
		ctx.listening = tabsOk && AttachInterceptListener(root, tabSel);

		// 切回原 tab（此刻监听已挂、inOurTab=false ⇒ handler 无动作、放行原版）。
		if (tabsOk && originalTab > 0.5) {
			(void)switchTab(static_cast<std::uint32_t>(originalTab));
		}

		const bool ok = snapOk && buildOk && tabsOk && ctx.listening;
		ctx.menuActive = ok;
		if (!ok) {
			// ★★★ 第 138 轮（P2 会话收口）：决定性失败 ⇒ 标记本菜单周期不再重试。
			//   第 137 轮 P2 会话实测：一旦失败（如 tab 数不是原版 7 项 ⇒ SetTabsData
			//   永远 +0），150 ms 节流的重试会持续刷 WARN（96 条 / 15 秒）且每拍全量
			//   重建（快照 + 构造 206 条）—— 菜单开着多久就烧多久。失败原因已记录
			//   （含 tab 数字，便于判读「环境不是原版 7 项」类现场）；下次菜单重开再试。
			ctx.activateFailed = true;
			REX::WARN("界面注入：激活失败（快照={} 构造={} 扩tab={} 监听={}；tab {}→{}）"
					  "—— 本次菜单不再重试（下次菜单重开再试）",
				snapOk ? "ok" : "fail", buildOk ? "ok" : "fail",
				tabsOk ? "ok" : "fail", ctx.listening ? "ok" : "fail",
				NumStr(tabs0), NumStr(tabs1));
			return false;
		}
		REX::INFO("界面注入：已激活（UiMode={}，tab {}→{}，条目 {}，按键名={}，语言={}）",
			ModeName(g_mode), NumStr(tabs0), NumStr(tabs1), NumStr(ctx.injectCount),
			courseKey.empty() ? "(空)" : courseKey, zh ? "zh" : "en");
		g_lastActivateTryMs = 0;   // 成功后清节流（下次菜单重新开始）
		return true;
	}

	void OnMenuClosed()
	{
		// GFx 引用随 Movie 销毁失效 —— 只清引用（handler 是静态实例、保留；
		//   菜单关闭后不会再收到事件，读失效值被 SEH 挡下返回失败）。
		g_ctxStore = InjectCtx{};
		g_ctx = nullptr;
		g_lastActivateTryMs = 0;
	}

	void OnMenuTick(bool a_uiChannelDead)
	{
		if (!WantInject(a_uiChannelDead)) {
			return;   // swf 模式 / auto 还没判定 ⇒ 零动作
		}
		if (!(g_ctx != nullptr && g_ctx->menuActive)) {
			// ★★★ 第 138 轮（P2 会话收口）：本菜单已决定性失败 ⇒ 不再重试
			//   （失败时已打一条 WARN；重试必失败且每次全量重建 —— 纯烧 CPU + 刷日志）。
			if (g_ctx != nullptr && g_ctx->activateFailed) {
				return;
			}
			// 激活尝试（节流 150 ms —— 菜单刚打开那几拍桥还没通 / 数据还没收集好）。
			const auto now = NowMs();
			if (g_lastActivateTryMs != 0 && now - g_lastActivateTryMs < kActivateRetryMs) {
				return;
			}
			g_lastActivateTryMs = now;
			(void)ActivateForMenu();
			return;
		}

		// ---- watchdog：玩家在我们的 tab 上 ⇒ 列表应始终是我们的注入数据 ----
		//   引擎刷新（任务状态推送 / 原版重建列表）会把列表换回引擎条目
		//   （此时 mask=1<<6 会把它们全过滤掉 ⇒ 空列表，看起来像坏了）——
		//   检测到就重放注入。开销 = 500 ms 两次 GFx 读（与界面轮询同拍）。
		InjectCtx& ctx = *g_ctx;
		if (!ctx.inOurTab) {
			return;
		}
		const auto now = NowMs();
		if (ctx.lastWatchdogMs != 0 && now - ctx.lastWatchdogMs < kWatchdogIntervalMs) {
			return;
		}
		ctx.lastWatchdogMs = now;

		double count = -1.0;
		{
			RE::Scaleform::GFx::Value v;
			if (!(SafeValueGetMember(&ctx.list, "entryCount", &v) && SafeReadValueNumber(v, count))) {
				return;   // 读不到（菜单收尾 / 销毁中）—— 静默
			}
		}
		bool ours = count == static_cast<double>(ctx.injectCount);
		if (ours && ctx.injectCount > 0) {
			// 首条 uID 复核（entryCount 相同 ≠ 内容相同）。
			RE::Scaleform::GFx::Value arg(static_cast<std::int32_t>(0));
			RE::Scaleform::GFx::Value entry;
			RE::Scaleform::GFx::Value uv;
			double                   uid = -1.0;
			if (SafeValueInvoke(&ctx.list, "GetDataForEntry", &entry, &arg, 1) && entry.IsObject() &&
				SafeValueGetMember(&entry, "uID", &uv) && SafeReadValueNumber(uv, uid)) {
				ours = static_cast<std::uint32_t>(uid) == ctx.expectUid[0];
			} else {
				ours = false;
			}
		}
		if (ours) {
			return;
		}
		// 重放：设 mask + 重新注入；日志节流（首次 + 每 10 次 —— 引擎频繁刷新不刷屏）。
		RE::Scaleform::GFx::Value f(static_cast<std::uint32_t>(kOurTabFlag));
		(void)SafeValueSetMember(&ctx.list, "filterMask", f);
		const bool inj = InjectOurEntries(ctx);
		++ctx.replayCount;
		if (ctx.replayCount == 1 || ctx.replayCount % 10 == 0) {
			REX::INFO("界面注入：列表被引擎刷新覆盖 → 已重放（第 {} 次，注入 {}）",
				ctx.replayCount, inj ? "ok" : "fail");
		}
	}

#if SAQ_WITH_HARNESS
	// ====================================================================
	// 五·附、运行期形态强制（harness `ui.mode` op；第 138 轮 P2 会话收口）
	//
	// 为什么放这里：产品段（五）必须保持「无预处理指令」的干净分层（发布构建也
	// 编译 —— verify 的分层检查按**第一个** `#if SAQ_WITH_HARNESS` 切分源码）。
	// ====================================================================
	void ForceMode(UiMode a_mode)
	{
		g_modeForced = true;
		g_mode = a_mode;
	}

	void ClearForceMode()
	{
		g_modeForced = false;
	}

	// ====================================================================
	// 六、PoC 主流程（harness 原语 `ui.inject` 的唯一入口）
	// ====================================================================
	std::string RunInjectPoC(const std::vector<QuestEntry>& a_quests)
	{
		std::string detail;
		if (!UI::EnsureResolved(detail)) {
			return "桥没通（" + EscapeForLog(detail, 200) + "）";
		}
		auto* root = reinterpret_cast<RE::Scaleform::GFx::ASMovieRootBase*>(UI::ResolvedAsMovieRoot());
		if (!root) {
			return "ASMovieRoot 指针为空";
		}
		if (a_quests.empty()) {
			return "待推送=0（菜单还没打开或这次没有可接任务 —— 先 menu.open 再看）";
		}

		std::string out;

		RE::Scaleform::GFx::Value menu;
		if (!(SafeGetVariable(root, "_root.Menu_mc", &menu) && menu.IsObject())) {
			return "Menu_mc=fail（原版 SWF 的 root 实例名对不上？后面全部依赖它）";
		}
		out += "Menu_mc=ok";

		RE::Scaleform::GFx::Value tabSel;
		RE::Scaleform::GFx::Value list;
		const bool tabSelOk = SafeValueGetMember(&menu, "TabbedFilterSelection_mc", &tabSel) &&
			tabSel.IsObject();
		const bool listOk = SafeValueGetMember(&menu, "MissionsList_mc", &list) && list.IsObject();
		if (!tabSelOk || !listOk) {
			return out + std::format("｜TabSel={} MissionsList={}（缺一个就做不下去）",
				tabSelOk ? "ok" : "fail", listOk ? "ok" : "fail");
		}

		auto readNum = [](RE::Scaleform::GFx::Value& a_obj, const char* a_name, double& a_out) -> bool {
			RE::Scaleform::GFx::Value v;
			return SafeValueGetMember(&a_obj, a_name, &v) && SafeReadValueNumber(v, a_out);
		};

		// ---- R1 环境 ----
		double tabs0 = -1.0, entries0 = -1.0, mask0 = -1.0;
		if (!(readNum(tabSel, "numTabs", tabs0) && readNum(list, "entryCount", entries0) &&
				readNum(list, "filterMask", mask0))) {
			return out + "｜环境=读失败（numTabs / entryCount / filterMask 三取一失败）";
		}

		// ---- R2 语言判定（文案口径；探针 U8a 同源） ----
		bool        zh = true;
		std::size_t sampleCjk = 0;
		const bool  langOk = DetectUseChinese(list, zh, sampleCjk);
		const char* title = zh ? kTabTitleZh : kTabTitleEn;

		out += std::format("｜环境=(numTabs {},entryCount {},mask {},语言 {})",
			NumStr(tabs0), NumStr(entries0), MaskHex(mask0),
			langOk ? (zh ? "zh" : "en") : "?");

		// 原版 public 入口（内部 SetSelectedIndex → dispatchEvent）；越界会被静默拒绝。
		//   （定义提前到这里：快照前要先把 tab 切回 0 —— 见下。）
		auto switchTab = [&tabSel](std::uint32_t a_idx) -> bool {
			RE::Scaleform::GFx::Value arg(static_cast<std::uint32_t>(a_idx));
			RE::Scaleform::GFx::Value ret;
			return SafeValueInvoke(&tabSel, "SetSelectedCategoryIndex", &ret, &arg, 1);
		};

		// ---- R2.5 先切回 0（$ALL）再快照 ----
		//   为什么：菜单可能恢复「上次分类」（玩家上次停在 $Misc 之类）—— 那时 entryCount
		//   只是该分类过滤后的子集，直接快照 ⇒ 恢复后其它分类缺条目。切 0 后原版自己设
		//   mask=0xFFFFFFFF（此刻我们的监听还没挂，走的是原版 onFilterChanged）。
		{
			double     maskAll = -1.0, entriesAll = -1.0;
			const bool swAll = switchTab(0) && readNum(list, "filterMask", maskAll) &&
				readNum(list, "entryCount", entriesAll);
			out += std::format("｜回ALL={}（mask {},entryCount {}）", swAll ? "ok" : "fail",
				MaskHex(maskAll), NumStr(entriesAll));
		}

		// ---- R3 引擎快照（$ALL 掩码下逐条读引用 —— 全量） ----
		g_ctxStore = InjectCtx{};
		g_ctx = &g_ctxStore;
		InjectCtx& ctx = g_ctxStore;
		// ★★★ 第 135 轮修复（P3-a 实机缺陷 · 注入上下文未接线）：把菜单打开期间持有的
		//   `MissionsList_mc` 存进上下文 —— 拦截 handler（切到我们 tab 时设 mask + 注入 /
		//   切走时恢复）**全部操作 `ctx.list`**，而它此前从未被赋值（默认构造的空 Value）：
		//   第 134 轮 P2 会话实测 = mask 写入失败 + `InitializeEntries` 失败 ⇒ 列表没换
		//   （玩家看到的还是原版那条「一小步」）；且 `恢复=ok` 是「1 == 1」巧合（假 PASS）。
		ctx.list = list;
		//   上下文自检（把「list 已接上」变成运行时证据 —— 上面那类缺陷以后一眼可见）：
		{
			double     ctxMask = -1.0;
			const bool ctxListOk = readNum(ctx.list, "filterMask", ctxMask);
			out += std::format("｜上下文={}", ctxListOk ? "ok" : "fail（list 没接上 ⇒ 切 tab 注入必失败）");
		}

		std::uint32_t snapCount = 0;
		const bool    snapOk = BuildEngineSnapshot(root, list, ctx.engineSnapshot, snapCount);
		ctx.engineCount = snapCount;
		out += std::format("｜快照={}（{} 条）", snapOk ? "ok" : "fail", NumStr(snapCount));
		if (!snapOk) {
			// 快照失败不致命（注入/对账仍可跑），但恢复段必然 fail —— 继续，让一行汇总说全。
		}

		// ---- R2b 按键名（完整描述文案的「按 R（设定航线）」分支；取不到 = 空串）----
		//   （不进判据行：输出格式与第 135 轮逐字一致 —— verify / P2 计划依赖它。）
		const std::string courseKey = GetCourseKeyName(root, menu);

		// ---- R4 我们的条目数组（真实数据） ----
		const char* buildWhy = "ok";
		const bool  buildOk = BuildOurEntries(root, a_quests, zh, courseKey, ctx.ourEntries,
			ctx, buildWhy);

		// ---- R5 扩 tab（7 项原样 + 我们的 → SetTabsData → numTabs 读回） ----
		RE::Scaleform::GFx::Value tabsArr;
		double                   tabs1 = -1.0;
		const bool tabsBuilt = BuildTabsArray(root, title, tabsArr);
		bool       tabsCalled = false;
		if (tabsBuilt) {
			RE::Scaleform::GFx::Value ret;
			tabsCalled = SafeValueInvoke(&tabSel, "SetTabsData", &ret, &tabsArr, 1);
		}
		const bool t1 = tabsCalled && readNum(tabSel, "numTabs", tabs1);
		const bool passExpand = t1 && tabs1 == tabs0 + 1.0;
		ctx.ourTabIndex = static_cast<int>(tabs0);
		out += std::format("｜扩tab={}（{}→{}）", passExpand ? "ok" : "fail",
			NumStr(tabs0), NumStr(tabs1));
		if (tabs0 != 7.0) {
			// 提示而不是失败：tab 数组的「原版 7 项」文本表是硬编码的（原版 1.16 实测 7 项），
			//   换版本/换环境后 numTabs 变了 ⇒ 文本可能对不上（拦截下标仍用动态值，所以
			//   分时注入本身照常工作 —— 只是 tab 标题可能不准）。
			out += std::format("（注意：原版 numTabs={} ≠ 7 —— tab 文本表按 7 项写）", NumStr(tabs0));
		}

		// ---- R6 挂拦截监听（priority=100）----
		const bool listenOk = AttachInterceptListener(root, tabSel);
		ctx.listening = listenOk;
		out += std::format("｜监听={}", listenOk ? "ok" : "fail");

		// ---- R7 切到我们 tab（拦截 + 注入）→ 读回 ----
		double     entries1 = -1.0;
		const bool sw7 = passExpand && switchTab(static_cast<std::uint32_t>(ctx.ourTabIndex));
		const bool r1 = sw7 && readNum(list, "entryCount", entries1);
		const bool passInject = buildOk && r1 && entries1 == static_cast<double>(ctx.injectCount);
		out += std::format("｜注入数据={}（entryCount {}→{}，期望 {}）",
			passInject ? "ok" : "fail", NumStr(entries0), NumStr(entries1), NumStr(ctx.injectCount));
		if (!buildOk) {
			out += std::format("（构造失败于 {}）", buildWhy);
		}

		// ---- R8 对账（前 2 条：uID / 名字 / 置灰）----
		{
			const std::uint32_t check = static_cast<std::uint32_t>(ctx.injectCount < 2 ?
				ctx.injectCount : 2);
			std::uint32_t good = 0;
			std::string   firstNote;
			for (std::uint32_t i = 0; i < check; ++i) {
				RE::Scaleform::GFx::Value arg(static_cast<std::int32_t>(i));
				RE::Scaleform::GFx::Value entry;
				if (!(SafeValueInvoke(&list, "GetDataForEntry", &entry, &arg, 1) && entry.IsObject())) {
					continue;
				}
				double uid = -1.0;
				char   nameBuf[256]{};
				bool   nav = false;
				RE::Scaleform::GFx::Value nm;
				RE::Scaleform::GFx::Value nv;
				const bool okUid = readNum(entry, "uID", uid) &&
					static_cast<std::uint32_t>(uid) == ctx.expectUid[i];
				const bool okName = SafeValueGetMember(&entry, "sName", &nm) &&
					SafeReadValueString(nm, nameBuf, sizeof(nameBuf)) &&
					std::string{ nameBuf } == ctx.expectName[i];
				const bool okNav = SafeValueGetMember(&entry, "bCanShowOnMap", &nv) &&
					SafeReadValueBool(nv, nav) && nav == ctx.expectNav[i];
				if (okUid && okName && okNav) {
					++good;
				}
				if (i == 0) {
					// ★ 第 135 轮：对账证据打**实际读回值**（期望值括注在后）—— 旧写法打
					//   「期望 uID + 实际名字」的混合值（第 134 轮实测 `0x002C5401:一小步`），
					//   判读时容易误以为 uID 已对上；这条线索本来要一眼看出「列表没被换」。
					const std::string shownName = nameBuf[0] != '\0' ?
						EscapeForLog(nameBuf, 40) : std::string{ "（读不到名字）" };
					firstNote = std::format("实际 0x{:08X}:{}｜可导航{}（期望 0x{:08X}）",
						uid < 0.0 ? 0u : static_cast<std::uint32_t>(uid), shownName,
						nav ? 1 : 0, ctx.expectUid[0]);
				}
			}
			const bool passCheck = check > 0 && good == check;
			out += std::format("｜对账={}（{}）", passCheck ? "ok" : "fail",
				firstNote.empty() ? "无样本" : firstNote);
		}

		// ---- R9 切走（恢复引擎快照）→ 读回 ----
		double     entries2 = -1.0;
		const bool sw0 = switchTab(0);
		const bool r2 = sw0 && readNum(list, "entryCount", entries2);
		// ★ 第 135 轮：恢复判据加 `passInject` 前置 —— 注入没成功时「恢复」没有意义
		//   （列表本来就没被换过，`entries2 == engineCount` 会因「1 == 1」巧合打出
		//   误导性的 `恢复=ok`；第 134 轮实测正是这种假 PASS）。
		const bool passRestore = snapOk && passInject && r2 &&
			entries2 == static_cast<double>(ctx.engineCount);
		out += std::format("｜恢复={}（切0 后 entryCount →{}，期望 {}）",
			passRestore ? "ok" : "fail", NumStr(entries2), NumStr(ctx.engineCount));

		// ---- R10 再切 7（供眼睛窗口：玩家能亲眼看到真实数据）→ 读回 ----
		double     entries3 = -1.0;
		const bool sw7b = switchTab(static_cast<std::uint32_t>(ctx.ourTabIndex));
		const bool r3 = sw7b && readNum(list, "entryCount", entries3);
		const bool passAgain = r3 && entries3 == static_cast<double>(ctx.injectCount);
		out += std::format("｜再注入={}（entryCount →{}，供眼睛）", passAgain ? "ok" : "fail",
			NumStr(entries3));

		// 统计（拦截器侧证据：切 7 一次注入 + 切走一次恢复 + 再切 7 一次注入 = 2/1）
		out += std::format("｜拦截=({} 次回调/{} 注入/{} 恢复)",
			InjectHandler::s_calls.load(), InjectHandler::s_injects.load(),
			InjectHandler::s_restores.load());

		// ★ 监听**故意保留**：眼睛窗口里玩家切 tab 要靠它（没有它切到第 8 个 tab
		//   会触发原版越界 TypeError）—— 副作用随 menu.close 自然清理（第 27/50 轮定案）。
		out += "｜眼睛=请切到第 8 个 tab 看真实列表";
		return out;
	}
}

#endif  // SAQ_WITH_HARNESS
