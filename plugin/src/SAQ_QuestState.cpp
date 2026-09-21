#include "PCH.h"

#include "SAQ_QuestState.h"

#include "SAQ_Decision.h"   // ★ 第 64 轮（大项 K）：位推导（DeriveRuntimeFlags）

#include "RE/T/TESForm.h"

#include <Windows.h>

#include <array>
#include <cstddef>
#include <format>

namespace SAQ
{
	namespace
	{
		// 见 SAQ_QuestState.h 顶部注释（全部来自反汇编，不是猜的）
		constexpr std::uintptr_t kOffsetFlags = 0x114;
		constexpr std::uintptr_t kOffsetStopFlag = 0x32C;
		constexpr std::uintptr_t kOffsetStartPending = 0x338;

		// TESQuest 的虚表（模块相对 RVA）。多个：TESQuest 有多个 COL / 次要虚表，
		// 实测（rtti_slots.py）主虚表是 0x4BD80D8，次要是 0x4BD8410。
		constexpr std::array<std::uintptr_t, 2> kTesQuestVtables{ 0x4BD80D8, 0x4BD8410 };

		// ★ 第 64 轮（大项 K）：标志位定义与推导公式移到离线层
		//   （SAQ_Decision.h 的 kFlag* / DeriveRuntimeFlags —— 有全组合单元测试）。

		struct RawFields
		{
			std::uintptr_t vtable{};
			std::uint32_t  flags{};
			std::uint64_t  startPending{};
			std::uint8_t   stopFlag{};
		};

		// ★ 只用 POD，且不要求对象展开（MSVC 的 __try 不允许与析构函数共存）。
		bool RawRead(const void* a_object, RawFields& a_out)
		{
			__try {
				const auto* base = static_cast<const std::byte*>(a_object);
				a_out.vtable = *reinterpret_cast<const std::uintptr_t*>(base);
				a_out.flags = *reinterpret_cast<const std::uint32_t*>(base + kOffsetFlags);
				a_out.startPending = *reinterpret_cast<const std::uint64_t*>(base + kOffsetStartPending);
				a_out.stopFlag = *reinterpret_cast<const std::uint8_t*>(base + kOffsetStopFlag);
				return true;
			} __except (EXCEPTION_EXECUTE_HANDLER) {
				return false;
			}
		}
	}

	QuestRuntimeState ReadQuestRuntimeState(const RE::TESForm* a_form)
	{
		QuestRuntimeState state;
		if (!a_form) {
			return state;
		}

		RawFields raw;
		if (!RawRead(a_form, raw)) {
			return state;  // 读炸了：readOk 保持 false
		}

		state.readOk = true;
		state.vtable = raw.vtable;
		state.flags = raw.flags;
		state.startPending = raw.startPending;
		state.stopFlag = raw.stopFlag;

		const auto moduleBase = reinterpret_cast<std::uintptr_t>(::GetModuleHandleW(nullptr));
		for (const auto rva : kTesQuestVtables) {
			if (raw.vtable == moduleBase + rva) {
				state.vtableKnown = true;
				break;
			}
		}

		// ★ 第 64 轮（大项 K）：位推导在离线层（Decision::DeriveRuntimeFlags）——
		//   位含义（bit0/1/7/11）与 IsRunning 的完整判据在那里有全组合单元测试；
		//   这里只负责「把字段读出来」。
		const auto f = Decision::DeriveRuntimeFlags(Decision::RawQuestFields{
			.flags = raw.flags,
			.startPending = raw.startPending,
			.stopFlag = raw.stopFlag,
		});
		state.started = f.started;
		state.completed = f.completed;
		state.stopping = f.stopping;
		state.active = f.active;
		state.running = f.running;

		return state;
	}

	bool IsAlreadyEngaged(const QuestRuntimeState& a_state)
	{
		return a_state.started || a_state.completed;
	}

	std::string Describe(const QuestRuntimeState& a_state)
	{
		std::string out;
		if (!a_state.readOk) {
			return "读取失败";
		}
		if (!a_state.vtableKnown) {
			out += "未识别虚表 ";
		}
		if (a_state.running) {
			out += "运行中 ";
		} else if (a_state.started) {
			out += a_state.stopping ? "停止中 " : "已开始 ";
		} else {
			out += "未开始 ";
		}
		if (a_state.completed) {
			out += "已完成 ";
		}
		if (a_state.active) {
			out += "追踪中 ";
		}
		out += std::format("flags=0x{:X}", a_state.flags);
		return out;
	}
}
