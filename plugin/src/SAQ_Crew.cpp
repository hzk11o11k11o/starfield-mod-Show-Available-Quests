#include "PCH.h"

#include "SAQ_Crew.h"

#include "RE/A/Actor.h"
#include "RE/T/TESFaction.h"
#include "RE/T/TESForm.h"

#include <array>
#include <cstdint>

namespace SAQ::Crew
{
	namespace
	{
		// ====================================================================
		// ★★★ 第 157 轮（可招募船员 · 实机检查收口）：**直读槽位修正**
		//
		// 实机证据（第 156 轮 45 条会话 —— 判读见 docs/16 16.9）：
		//   * `crew.probe` 的「Papyrus vs 直读」对照暴露 12 位里 **4 位不一致**：
		//     Papyrus 读到 P=1 的 4 位（铁杆粉丝 / 吉迪恩·艾克 / 玛丽卡·波罗斯 /
		//     西米恩·班科夫斯基），直读全读 0；产品「船员门槛=」行同步显示「过 0」
		//     （可读位全部被错误隐藏 —— 界面实际少 4 条真「可招募」船员）。
		//   * 离线验证（tools/re · 1.16.244）：
		//       Papyrus native `Actor.IsInFaction` 的注册实现（RVA 0x1F1E7A0）
		//       就是一条 `call qword ptr [rax+0xBA0]` ⇒ 真正的 `Actor::IsInFaction`
		//       在 **vtable 槽 0x174**（RVA 0x1928CB0，接收 rdx = TESFaction*，签名吻合）。
		//   * 而 commonlibsf（tools/commonlibsf-main 的 Actor.h）把 IsInFaction 标在
		//     **0x175**（比 1.16.244 实际多 1 槽 —— 整体错位）：该槽实际是一个
		//     「按 1 字节索引查表」的函数（`movzx ebp, dl`），拿 faction 指针当索引用
		//     ⇒ 几乎恒 false（偶然依赖指针低字节的表项）。
		//
		// 结论：**不能调 `a_actor->IsInFaction()`** —— commonlibsf 的声明会编到 0x175。
		//   这里改为按槽显式调用 + **函数头指纹校验**：
		//     指纹不符（换游戏版本 / 游戏更新）⇒ 直读停用（保守放行）+ 一行 WARN
		//     （与 ini `[Filter] CrewCond=0` 构成两级回退）。
		//   换版本后重新验证的方法 = `python tools/re/find_papyrus_native.py IsInFaction`
		//   （工具会打出 native 实现 → 虚槽号 → 函数头字节，见 docs/16 16.9）。
		// ====================================================================
		constexpr std::size_t kIsInFactionSlot = 0x174;

		// 槽 0x174（1.16.244 · RVA 0x1928CB0）的函数头 20 字节：
		//   mov [rsp+8],rbx / mov [rsp+0x10],rsi / mov [rsp+0x18],rdi / mov [rsp+0x20],r12
		constexpr std::array<std::uint8_t, 20> kIsInFactionSig{
			0x48, 0x89, 0x5C, 0x24, 0x08,
			0x48, 0x89, 0x74, 0x24, 0x10,
			0x48, 0x89, 0x7C, 0x24, 0x18,
			0x4C, 0x89, 0x64, 0x24, 0x20
		};

		using IsInFactionFn = bool (*)(RE::Actor*, RE::TESFaction*);

		bool SigMatches(const void* a_fn)
		{
			const auto* p = static_cast<const std::uint8_t*>(a_fn);
			for (std::size_t i = 0; i < kIsInFactionSig.size(); ++i) {
				if (p[i] != kIsInFactionSig[i]) {
					return false;
				}
			}
			return true;
		}

		// 解析「槽 0x174」的函数指针（从任一 Actor 实例的 vtable 取 —— 同一类的
		// 实例共享同一张 vtable）+ 指纹校验。成功 ⇒ 缓存；失败 ⇒ 每次重试但只 WARN 一次。
		//   只在主线程调用（菜单打开时的收集路径）。
		IsInFactionFn ResolveIsInFaction(RE::Actor* a_actor)
		{
			static IsInFactionFn s_fn{};
			static bool          s_warned{};
			if (s_fn != nullptr) {
				return s_fn;  // 已解析成功
			}
			auto** vtable = *reinterpret_cast<void***>(a_actor);
			if (vtable == nullptr || vtable[kIsInFactionSlot] == nullptr) {
				if (!s_warned) {
					s_warned = true;
					REX::WARN("船员直读：Actor vtable 取不到（槽 0x174）—— 船员判据停用"
							  "（保守放行：判不了就不藏）");
				}
				return nullptr;
			}
			auto* fn = reinterpret_cast<IsInFactionFn>(vtable[kIsInFactionSlot]);
			if (!SigMatches(reinterpret_cast<const void*>(fn))) {
				if (!s_warned) {
					s_warned = true;
					REX::WARN("船员直读：槽 0x174 的函数指纹与该版本（1.16.244）不符"
							  "（游戏更新了？）—— 船员判据停用（保守放行）；要恢复请用 "
							  "tools/re/find_papyrus_native.py IsInFaction 在当前版本上重验"
							  "（见 docs/16 16.9）");
				}
				return nullptr;
			}
			s_fn = fn;
			REX::INFO("船员直读：槽 0x174 指纹=ok（Actor::IsInFaction 直读可用）");
			return s_fn;
		}

		// 一次 faction 成员查询。faction 取不到（ESM 没装全等）⇒ false（保守）。
		//   ★ 若「槽 0x174 直读」不可用（指纹不符 / vtable 取不到）⇒ false ——
		//   ReadState 对「不可用」与「读不到」走同一条保守路径（放行）。
		bool InFaction(RE::Actor* a_actor, std::uint32_t a_factionFormID)
		{
			auto* fn = ResolveIsInFaction(a_actor);
			if (fn == nullptr) {
				return false;
			}
			auto* form = RE::TESForm::LookupByID(static_cast<RE::TESFormID>(a_factionFormID));
			auto* faction = form ? form->As<RE::TESFaction>() : nullptr;
			return faction != nullptr && fn(a_actor, faction);
		}
	}

	State ReadState(std::uint32_t a_refFormID)
	{
		State st;
		if (a_refFormID == 0) {
			return st;
		}
		auto* form = RE::TESForm::LookupByID(static_cast<RE::TESFormID>(a_refFormID));
		auto* actor = form ? form->As<RE::Actor>() : nullptr;
		if (actor == nullptr) {
			return st;  // 引用未加载 / 不是 actor ⇒ readable = false（保守放行）
		}
		st.readable = true;
		st.available = InFaction(actor, kAvailableFaction);
		st.current = InFaction(actor, kCurrentFaction);
		st.potential = InFaction(actor, kPotentialFaction);
		return st;
	}
}
