#include "PCH.h"

#include "SAQ_UiInject.h"

// ★ 第 36/84 轮同款依赖：日志截断按 UTF-8 字符边界（证据通道纪律）。
#include "SAQ_Decision.h"

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

#if SAQ_WITH_HARNESS

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

		// 描述文案 —— P3-a = **主干简化版**（完整 SaqDescriptionText 迁移 = P3-b）：
		//   首句（说明 / 同伴 / 入口 / 普通）+ 目标句（有 / 无导航）。
		//   语言与精度（任务名/说明/前缀）全部与 SWF 版同源；差异只在「按键名提示」等
		//   细节分支（P3-b 补齐）。
		std::string BuildDescription(const QuestEntry& a_e, bool a_zh)
		{
			std::string s;
			const std::string& note = a_zh ? a_e.noteZh : a_e.noteEn;
			if (!note.empty()) {
				s = note;
			} else if (a_e.companionPinned) {
				s = a_zh ?
					"这条同伴任务需要与同伴的好感度达到一定水平后才会自动开始（不需要找地方接取）。"
					"使用底部的「设定航线」即可引导到这位同伴的位置。" :
					"This companion quest starts automatically once your affinity with the companion is "
					"high enough (there is no pickup location). Use SET COURSE to be guided to the "
					"companion's location.";
			} else if (a_e.type == 100 || a_e.type == 101) {
				s = a_zh ?
					"这是一个无限任务入口 —— 与它交互就能接到不断刷新的任务。"
					"使用底部的「设定航线」即可引导到它的位置。" :
					"This is an endless-jobs entry point - interact with it to pick up endlessly "
					"refreshing jobs. Use SET COURSE to be guided to its location.";
			} else {
				s = a_zh ? "这条任务当前可以接取。" : "This quest is currently available.";
			}
			if (!a_e.hasGuideTarget) {
				s += a_zh ?
					"但它暂时还没有导航目标 —— 无法引导到接取地点（任务本身照常显示）。" :
					" It has no navigation target yet, so it cannot guide you to the pickup location.";
			} else {
				s += a_zh ?
					"展开后选中目标，或使用底部的「设定航线」即可引导到接取地点。" :
					" Expand it, then select the objective or use SET COURSE to be guided to the "
					"pickup location.";
			}
			return s;
		}

		// 构造我们的条目数组。字段集 = 探针 v4 已验证的最小集 + 真实值（第 130/131 轮）。
		bool BuildOurEntries(RE::Scaleform::GFx::ASMovieRootBase* a_root,
			const std::vector<QuestEntry>& a_quests, bool a_zh, RE::Scaleform::GFx::Value& a_out,
			InjectCtx& a_ctx, const char*& a_why)
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
				setStr("sDescription", BuildDescription(e, a_zh));
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
	// 五、PoC 主流程（harness 原语 `ui.inject` 的唯一入口）
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

		std::uint32_t snapCount = 0;
		const bool    snapOk = BuildEngineSnapshot(root, list, ctx.engineSnapshot, snapCount);
		ctx.engineCount = snapCount;
		out += std::format("｜快照={}（{} 条）", snapOk ? "ok" : "fail", NumStr(snapCount));
		if (!snapOk) {
			// 快照失败不致命（注入/对账仍可跑），但恢复段必然 fail —— 继续，让一行汇总说全。
		}

		// ---- R4 我们的条目数组（真实数据） ----
		const char* buildWhy = "ok";
		const bool  buildOk = BuildOurEntries(root, a_quests, zh, ctx.ourEntries, ctx, buildWhy);

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
		auto* handler = new InjectHandler();
		RE::Scaleform::GFx::Value fn;
		bool                     listenOk = false;
		if (VtableSlotInModule(root, kSlotAsRootCreateFunction) &&
			SafeCreateFunction(root, &fn, handler, nullptr)) {
			RE::Scaleform::GFx::Value evTitle;
			if (SafeCreateString(root, &evTitle, kEventName)) {
				RE::Scaleform::GFx::Value args[5];
				args[0] = evTitle;
				args[1] = fn;
				args[2] = false;
				args[3] = static_cast<std::uint32_t>(kInterceptPriority);
				args[4] = false;
				RE::Scaleform::GFx::Value ret;
				listenOk = SafeValueInvoke(&tabSel, "addEventListener", &ret, args, 5);
			}
		}
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
				if (i == 0 && nameBuf[0] != '\0') {
					firstNote = std::format("0x{:08X}:{}｜可导航{}", ctx.expectUid[0],
						EscapeForLog(nameBuf, 40), ctx.expectNav[0] ? 1 : 0);
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
		const bool passRestore = snapOk && r2 && entries2 == static_cast<double>(ctx.engineCount);
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
