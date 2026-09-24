#include "PCH.h"

#include "SAQ_Crew.h"

#include "RE/A/Actor.h"
#include "RE/T/TESFaction.h"
#include "RE/T/TESForm.h"

namespace SAQ::Crew
{
	namespace
	{
		// 一次 faction 成员查询。faction 取不到（ESM 没装全等）⇒ false（保守）。
		//   ★ 虚函数调用（Actor vtable 175 条）—— 与 Papyrus `Actor.IsInFaction` 同源；
		//   正确性由 harness `crew.probe` 的「Papyrus vs 直读」逐位对照钉死（docs/16 16.8）。
		bool InFaction(RE::Actor* a_actor, std::uint32_t a_factionFormID)
		{
			auto* form = RE::TESForm::LookupByID(static_cast<RE::TESFormID>(a_factionFormID));
			auto* faction = form ? form->As<RE::TESFaction>() : nullptr;
			return faction != nullptr && a_actor->IsInFaction(faction);
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
