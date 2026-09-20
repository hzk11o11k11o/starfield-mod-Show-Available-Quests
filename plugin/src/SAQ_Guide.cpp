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
		const std::string testNote = out.testMode >= 0.0f
			? std::format("{:.0f}", out.testMode)
			: std::string{ "无(ESM 旧版)" };
		out.summary = std::format("前缀=0x{:02X} 目标={:.0f}(0x{:X}) 状态={:.0f} 通知={:.0f} 测试={}",
			g_prefix,
			out.targetRef, static_cast<std::uint32_t>(out.targetRef),
			out.guideState, out.notify, testNote);
		return out;
	}

	bool SetGuideTarget(std::uint32_t a_formID, std::string& a_detail)
	{
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
		if (state->value < -0.5f || state->value > 8.0f) {
			g_resolved = false;
			a_detail = std::format("拒绝写入：SAQ_GuideState 读出来是 {}（不像状态值）", state->value);
			return false;
		}
		if (target->value < 0.0f || target->value > 16777215.0f) {  // FormID 上限 0xFFFFFF
			g_resolved = false;
			a_detail = std::format("拒绝写入：SAQ_GuideTargetRef 读出来是 {}（不像 FormID）", target->value);
			return false;
		}
		target->value = static_cast<float>(a_formID);
		state->value = 0.0f;  // 0 = 待处理：脚本轮询到就会应用/清除
		a_detail = std::format("写入 SAQ_GuideTargetRef={}（0x{:X}）并把 SAQ_GuideState 清 0",
			a_formID, a_formID);
		return true;
	}

	void ResetChannel()
	{
		g_resolved = false;
		g_prefix = 0;
		g_failDetail.clear();
	}
}
