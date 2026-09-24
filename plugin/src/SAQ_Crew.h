#pragma once

// ============================================================================
//  ★★★ 第 156 轮（可招募船员 · 入口段落地）：crew faction 运行时判据（DLL 直读）
//
//  需求口径（docs/16 16.7 定案）：「显示 = P=1 / 隐藏 = A=1」——
//    * P（PotentialCrewFaction）：招募任务 stage 1 打的「可招募解锁」位（SetFactionRank 1）
//      ⇒ P=0 = 进度没到（未解锁）⇒ 隐藏；
//    * A（AvailableCrewFaction）：官方 `Crew_RecruitQuestScript.Recruited()` 的「首次
//      收费」判据（IsInFaction(AvailableCrewFaction) == false）+ `Game.AddToAvailableCrew`
//      ⇒ A=1 = 曾经招募过 ⇒ 隐藏（已招募）。
//
//  为什么是 DLL 直读而不是 Papyrus 通道：菜单打开时 Papyrus 定时器冻结（第 27 轮定案）
//  ⇒ 「开菜单当场读」只能走引擎调用。`Actor::IsInFaction(TESFaction*)` 的位置
//  **以实测为准 = vtable 槽 0x174**（第 157 轮修正 —— commonlibsf 的 Actor.h 标在
//  0x175，比 1.16.244 实际多 1 槽；证据 = Papyrus native 实现虚调用 `[rax+0xBA0]`，
//  见 SAQ_Crew.cpp 顶部注释与 docs/16 16.9）。直读实现带**函数头指纹校验**：
//  换游戏版本 ⇒ 指纹不符 ⇒ 自动停用（保守放行）+ 一行 WARN。
//  正确性验证 = harness `crew.probe` 同一会话里同时用 Papyrus op=7（官方同款读法）
//  与这里的直读逐位比对（不一致会在产品行里带「对照=不一致」+ 用例反向断言）。
//
//  引擎限制（与 Papyrus `Game.GetForm` 同源）：非常驻引用在所在 cell 未加载时
//  `LookupByID` 取不到 ⇒ readable = false ⇒ **保守放行（显示）**——判不了就不藏。
//  这一条与其它三类门槛的「求值不了 ⇒ 放行」纪律一致。
// ============================================================================

#include <cstdint>

namespace SAQ::Crew
{
	// crew faction 三件套（Starfield.esm 记录号；主数据 index 0 ⇒ 运行期 FormID 同值）。
	inline constexpr std::uint32_t kAvailableFaction = 0x00014314;  // AvailableCrewFaction
	inline constexpr std::uint32_t kCurrentFaction = 0x00014312;    // CurrentCrewFaction（在岗）
	inline constexpr std::uint32_t kPotentialFaction = 0x000143A2;  // PotentialCrewFaction（解锁）

	// 一位船员的运行时状态（引用未加载 ⇒ readable = false，其余位无意义）。
	struct State
	{
		bool readable{};
		bool available{};   // A：曾招募（收费判据）
		bool current{};     // C：当前在岗（不作判据，只记日志/探针）
		bool potential{};   // P：已解锁（可招募）
	};

	// 直读：LookupByID(ref) → As<Actor> → IsInFaction × 3。只在主线程调用。
	State ReadState(std::uint32_t a_refFormID);
}
