#include "PCH.h"

#include "SAQ_Guide.h"

#include "RE/T/TESForm.h"
#include "RE/T/TESGlobal.h"

#include <format>

namespace SAQ::Guide
{
	namespace
	{
		// SAQ_ShowAvailableQuests.esm 里的记录号（低 24 位；见 tools/xedit-scripts/build_saq.pas
		// 的记录表与 tools/esm/patch_saq_esm.py）。高 8 位（本插件在加载顺序里的序号）
		// 运行期才知道，靠魔数认领，见文件头注释。
		constexpr std::uint32_t kFormIDTargetRef = 0x801;   // GLOB SAQ_GuideTargetRef
		constexpr std::uint32_t kFormIDGuideState = 0x802;  // GLOB SAQ_GuideState
		constexpr std::uint32_t kFormIDNotify = 0x803;      // GLOB SAQ_Notify
		// ★ 第 20 轮：控制台测试开关（玩家 `set SAQ_TestMode to N`）。可选记录 ——
		//   旧 ESM 里没有它，读不到就保持 -1（不过滤），不影响任何既有功能。
		constexpr std::uint32_t kFormIDTestMode = 0x804;    // GLOB SAQ_TestMode
		// ★ 第 21 轮：引导目标的「高位字节」（FormID >> 24）。可选记录 ——
		//   为什么要拆（实机 bug 的根治）：GLOB 是 float（尾数 24 位），完整 FormID
		//   超过 2^24（DLC 的引用，如 0x0107BDB2）后**奇数不可精确表示**，轻则
		//   GetForm 取不到（状态 2），重则指向相邻的另一条记录（错误的引导目标）。
		//   低 24 位（≤0xFFFFFF）+ 高 8 位（≤0xFF）分别存两个 float ⇒ 都精确。
		//   旧 ESM 没有它 ⇒ -1，按旧语义（target 里就是完整 FormID）处理。
		constexpr std::uint32_t kFormIDGuidePrefix = 0x805; // GLOB SAQ_GuidePrefix

		// 脚本写的身份锚点：7777 + 菜单打开次数（允许 1000 次）
		constexpr float kNotifyMagic = 7777.0f;
		constexpr float kNotifyMagicMax = kNotifyMagic + 1000.0f;

		bool          g_resolved{};
		std::uint32_t g_prefix{};
		std::string   g_failDetail;

		// 按「前缀 + 记录号」拿 GLOB。类型用 TESForm::As<TESGlobal>()（内部就是比对
		// formType），拿不到就返回 nullptr —— 认领过程靠这个把「其它插件的同名位」挡掉。
		RE::TESGlobal* GlobAt(std::uint32_t a_prefix, std::uint32_t a_lowId)
		{
			auto* form = RE::TESForm::LookupByID((a_prefix << 24) | a_lowId);
			return form ? form->As<RE::TESGlobal>() : nullptr;
		}

		// 把「低 24 位 + 高 8 位」拼成完整 FormID（第 21 轮）。
		//   a_prefix < 0  ⇒ ESM 旧版没有 SAQ_GuidePrefix ⇒ a_targetRef 本身就是完整 FormID；
		//   a_targetRef > 0xFFFFFF ⇒ 通道里是修复前的「遗留完整值」⇒ 同样按完整值处理。
		std::uint32_t CombineTargetFormID(float a_targetRef, float a_prefix)
		{
			if (!(a_targetRef > 0.0f)) {
				return 0;  // 0 或 NaN 都当「没有引导」
			}
			const auto local = static_cast<std::uint32_t>(a_targetRef);
			if (local > 0xFFFFFFu || a_prefix < 0.0f) {
				return local;  // 旧语义：完整 FormID
			}
			const auto high = static_cast<std::uint32_t>(a_prefix);
			return ((high & 0xFFu) << 24) | (local & 0xFFFFFFu);
		}
	}

	Channel EnsureChannel()
	{
		if (!g_resolved) {
			std::string tried;
			for (std::uint32_t p = 0; p <= 0xFF; ++p) {
				auto* notify = GlobAt(p, kFormIDNotify);
				if (!notify) {
					continue;
				}
				const float v = notify->value;
				if (v < kNotifyMagic || v > kNotifyMagicMax) {
					if (tried.size() < 220) {
						tried += std::format(" 0x{:02X}:{:.0f}", p, v);
					}
					continue;
				}
				// 锚点命中：同前缀下另两个也必须是 GLOB，否则当我们认错人了
				if (!GlobAt(p, kFormIDTargetRef) || !GlobAt(p, kFormIDGuideState)) {
					continue;
				}
				g_resolved = true;
				g_prefix = p;
				g_failDetail.clear();
				break;
			}
			if (!g_resolved) {
				g_failDetail = std::format(
					"未认领（SAQ_Notify 里没有魔数 {:.0f}：ESM 没启用 / 脚本没跑 / 记录号变了）｜候选:{}",
					kNotifyMagic, tried.empty() ? std::string{ " 一个都不存在" } : tried);
			}
		}

		Channel out;
		out.resolved = g_resolved;
		out.prefix = g_prefix;
		if (!g_resolved) {
			out.summary = g_failDetail;
			return out;
		}

		auto* target = GlobAt(g_prefix, kFormIDTargetRef);
		auto* state = GlobAt(g_prefix, kFormIDGuideState);
		auto* notify = GlobAt(g_prefix, kFormIDNotify);
		if (!target || !state || !notify) {
			// 认领过但指针没了（换局/换加载顺序）⇒ 丢缓存重来
			g_resolved = false;
			out.resolved = false;
			out.summary = "GLOB 指针失效（已丢弃认领结果，下次重新认领）";
			return out;
		}
		out.targetRef = target->value;
		out.guideState = state->value;
		out.notify = notify->value;
		// ★ 第 20 轮：测试开关（可选 GLOB）——读不到就保持 -1（旧 ESM 兼容，不过滤）
		if (auto* tm = GlobAt(g_prefix, kFormIDTestMode)) {
			out.testMode = tm->value;
		}
		// ★ 第 21 轮：引导目标高位（可选 GLOB）+ 拼出完整 FormID（见 CombineTargetFormID）
		if (auto* pfx = GlobAt(g_prefix, kFormIDGuidePrefix)) {
			out.targetPrefix = pfx->value;
		}
		out.targetFormID = CombineTargetFormID(out.targetRef, out.targetPrefix);
		const std::string testNote = out.testMode >= 0.0f
			? std::format("{:.0f}", out.testMode)
			: std::string{ "无(ESM 旧版)" };
		out.summary = std::format("前缀=0x{:02X} 目标=0x{:08X} 状态={:.0f} 通知={:.0f} 测试={}",
			g_prefix, out.targetFormID, out.guideState, out.notify, testNote);
		return out;
	}

	bool SetGuideTarget(std::uint32_t a_formID, std::string& a_detail, bool a_starMap, float a_starMapState)
	{
		// ★ 第 37 轮：「设定航线（R）」= 除了设引导，还要打开星图。
		//   状态的约定（与 SAQ_Main.psc 一致，见 docs/05 第十一节）：
		//     0   = 待处理（脚本应用引导即可）
		//     5   = 待处理 + 应用后打开星图（只有玩家按 R 的那条路会写这个值）
		//     6/7 = ★ 第 40 轮：同 5，但换别的地点候选（星图重试时用，见 SAQ.cpp）
		//   取消引导（a_formID == 0）永远写 0 —— 玩家要的是「撤掉引导」，不是要航线。
		const float kStarMapRequest = 5.0f;
		const float requested = (a_starMap && a_formID != 0) ? a_starMapState : 0.0f;
		const std::string requestedNote = requested > 0.0f
			? std::format("{:.0f}（星图请求）", requested)
			: std::string{ "0" };
		if (!g_resolved) {
			EnsureChannel();
		}
		if (!g_resolved) {
			a_detail = g_failDetail;
			return false;
		}
		auto* target = GlobAt(g_prefix, kFormIDTargetRef);
		auto* state = GlobAt(g_prefix, kFormIDGuideState);
		if (!target || !state) {
			g_resolved = false;
			a_detail = "GLOB 指针取不到（通道失效，已丢弃认领结果）";
			return false;
		}
		// ★ 写之前再自检一次当前值：认领靠的是「SAQ_Notify 的值落在魔数区间」，
		//   已经证明 TESGlobal::value 的偏移在这台机器上是对的；这里再加一道，
		//   万一另两个 GLOB 的读数是垃圾（偏移不对 / 认错对象），就拒绝写内存。
		//
		//   ★★ 第 21 轮修正（实机 bug）：这里原来把上限写成 `16777215`（= 0xFFFFFF），
		//   那是「低 24 位」的上限，而 target 里存的是**完整 FormID** —— 第 17 轮支持
		//   DLC 后，目标引用会超过它（如 0x0107BDB2 = 17,284,530）。后果：只要通道里
		//   存过这种值，之后**每一次**写入都被这里拒绝（结果码 2）—— 玩家看到的是
		//   「点亮一条 DLC 任务后，其余条目全都点不亮、取消也失败」。
		//   现在：有拆分 GLOB（kFormIDGuidePrefix）时按「低 24 位 + 高 8 位」分别检查
		//   并分别写入（顺便根治 float 精度问题）；旧 ESM 按完整 FormID 上限 0xFEFFFFFF。
		if (state->value < -0.5f || state->value > 8.0f) {
			g_resolved = false;
			a_detail = std::format("拒绝写入：SAQ_GuideState 读出来是 {}（不像状态值）", state->value);
			return false;
		}
		if (auto* prefixGlob = GlobAt(g_prefix, kFormIDGuidePrefix)) {
			// 上限用**完整 FormID** 的范围：修复前的存档里 target 可能残留
			// 「完整 FormID」（如 0x0107BDB2 = 17,284,530，此时 prefix 还是初值 0）——
			// 那正是这次要覆盖掉的值，不能因为「它不像新语义的低 24 位」而拒绝。
			if (target->value < 0.0f || target->value > 4278190080.0f ||
				prefixGlob->value < 0.0f || prefixGlob->value > 255.0f) {
				g_resolved = false;
				a_detail = std::format("拒绝写入：通道读数是垃圾（低位={} 高位={}）",
					target->value, prefixGlob->value);
				return false;
			}
			target->value = static_cast<float>(a_formID & 0xFFFFFFu);
			prefixGlob->value = static_cast<float>((a_formID >> 24) & 0xFFu);
			state->value = requested;
			a_detail = std::format(
				"写入 SAQ_GuideTargetRef=0x{:06X} + SAQ_GuidePrefix={}（完整 0x{:08X}）"
				"并把 SAQ_GuideState 置 {}",
				a_formID & 0xFFFFFFu, (a_formID >> 24) & 0xFFu, a_formID, requestedNote);
			return true;
		}
		if (target->value < 0.0f || target->value > 4278190080.0f) {  // 完整 FormID 上限 0xFEFFFFFF
			g_resolved = false;
			a_detail = std::format("拒绝写入：SAQ_GuideTargetRef 读出来是 {}（不像 FormID）", target->value);
			return false;
		}
		target->value = static_cast<float>(a_formID);
		state->value = requested;  // 待处理：脚本轮询到就会应用/清除（5 = 还要打开星图）
		a_detail = std::format("写入 SAQ_GuideTargetRef={}（0x{:X}）并把 SAQ_GuideState 置 {}",
			a_formID, a_formID, requestedNote);
		return true;
	}

	void ResetChannel()
	{
		g_resolved = false;
		g_prefix = 0;
		g_failDetail.clear();
	}

	// ★★ 第 49 轮：给 harness（SAQ_TestOps）用的「按记录号取 GLOB」。
	//   认领流程与 EnsureChannel 完全一致（魔数锚点 + 类型校验），只是不缓存指针 ——
	//   GLOB 数量很少、调用频率很低（每 0.5 秒几条），没必要再维护一份缓存。
	RE::TESGlobal* FindGlob(std::uint32_t a_lowId)
	{
		if (!g_resolved) {
			EnsureChannel();
		}
		if (!g_resolved) {
			return nullptr;
		}
		return GlobAt(g_prefix, a_lowId);
	}
}
