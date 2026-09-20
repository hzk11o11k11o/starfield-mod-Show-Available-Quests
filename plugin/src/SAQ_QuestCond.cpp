#include "PCH.h"

#include "SAQ_QuestCond.h"

#include "SAQ_Masters.h"      // MakeFormID（master 下标 + 记录号 → 运行期 FormID）
#include "SAQ_QuestState.h"   // ReadQuestRuntimeState（TESQuest 运行时状态）
#include "SAQ_QuestTable.h"   // kQuestConds / CondCheck
#include "SAQ.h"              // REX 日志（经 PCH）

#include "RE/T/TESForm.h"

#include <Windows.h>

#include <array>
#include <cstddef>
#include <format>

namespace SAQ
{
	namespace
	{
		// 引擎的「stage 是否完成」查询（第 35 轮反汇编，见 SAQ_QuestCond.h 顶部注释）。
		constexpr std::uintptr_t kIsStageDoneRva = 0xD0DBD0;
		// 函数头 9 字节特征（mov [rsp+8],rbx / mov r8d,[rcx+0x1AC] 的前 9 字节）：
		//   48 89 5C 24 08   mov qword ptr [rsp+8], rbx
		//   44 8B 81 AC …    mov r8d, dword ptr [rcx+0x1AC]
		constexpr std::array<std::uint8_t, 9> kIsStageDoneSig{
			0x48, 0x89, 0x5C, 0x24, 0x08, 0x44, 0x8B, 0x81, 0xAC
		};

		using IsStageDoneFn = bool(__fastcall*)(void*, std::uint16_t);

		// ★ 特征校验必须在**纯 POD 函数**里做（MSVC 的 __try 不能与需要析构展开的
		//   对象共存 —— 本项目已踩过，见 SAQ_QuestState.cpp 的注释）。
		void* ProbeStageDoneFn()
		{
			__try {
				const auto base = reinterpret_cast<std::uintptr_t>(::GetModuleHandleW(nullptr));
				if (!base) {
					return nullptr;
				}
				const auto* p = reinterpret_cast<const std::uint8_t*>(base + kIsStageDoneRva);
				for (std::size_t i = 0; i < kIsStageDoneSig.size(); ++i) {
					if (p[i] != kIsStageDoneSig[i]) {
						return nullptr;
					}
				}
				return const_cast<std::uint8_t*>(p);
			} __except (EXCEPTION_EXECUTE_HANDLER) {
				return nullptr;
			}
		}

		// 带保护的实际调用（同样只用 POD：bool 出参区分「调用成功」与「异常」）。
		bool CallStageDoneChecked(void* a_fn, void* a_quest, std::uint16_t a_stage, bool& a_out)
		{
			__try {
				a_out = reinterpret_cast<IsStageDoneFn>(a_fn)(a_quest, a_stage);
				return true;
			} __except (EXCEPTION_EXECUTE_HANDLER) {
				return false;
			}
		}

		IsStageDoneFn StageDoneFnOrNull()
		{
			static IsStageDoneFn cached = reinterpret_cast<IsStageDoneFn>(ProbeStageDoneFn());
			return cached;
		}
	}

	CondEvalResult EvaluateProgressGates(std::uint32_t a_condBegin, std::uint8_t a_condCount)
	{
		CondEvalResult out;
		if (a_condCount == 0) {
			return out;  // kNoGates：这条任务没有门槛
		}
		if (a_condBegin > kQuestCondCount || a_condCount > kQuestCondCount - a_condBegin) {
			out.verdict = CondVerdict::kUnknown;
			out.detail = "门槛切片越界";
			return out;
		}

		for (std::size_t i = 0; i < a_condCount; ++i) {
			const auto& g = kQuestConds[a_condBegin + i];
			const auto fid = Masters::MakeFormID(g.questMaster, g.questLocal);
			const auto* form = fid ? RE::TESForm::LookupByID(fid) : nullptr;
			if (!form) {
				// 目标任务取不到（master 没解析出来 / 记录不存在）⇒ 这条任务放行。
				out.verdict = CondVerdict::kUnknown;
				out.detail = std::format("目标 0x{:08X} 取不到", fid);
				return out;
			}

			bool actual = false;
			if (g.check == kCondStageDone) {
				const auto fn = StageDoneFnOrNull();
				if (!fn) {
					out.verdict = CondVerdict::kUnknown;
					out.detail = "IsStageDone 不可用（游戏版本特征不符）";
					return out;
				}
				bool ok = false;
				if (!CallStageDoneChecked(reinterpret_cast<void*>(fn),
						const_cast<RE::TESForm*>(form), g.stage, ok)) {
					out.verdict = CondVerdict::kUnknown;
					out.detail = "IsStageDone 调用异常";
					return out;
				}
				actual = ok;
			} else {
				const auto st = ReadQuestRuntimeState(form);
				if (!st.readOk || !st.vtableKnown) {
					out.verdict = CondVerdict::kUnknown;
					out.detail = std::format("目标 0x{:08X} 状态读不了", fid);
					return out;
				}
				actual = (g.check == kCondRunning) ? st.running : st.completed;
			}

			if (actual != (g.want != 0)) {
				out.verdict = CondVerdict::kFail;
				const char* what = (g.check == kCondRunning) ? "running"
					: (g.check == kCondCompleted) ? "completed" : "stageDone";
				out.detail = std::format("0x{:08X} {}={} 期望 {}", fid, what,
					actual ? 1 : 0, g.want);
				return out;
			}
		}

		out.verdict = CondVerdict::kPass;
		return out;
	}
}
