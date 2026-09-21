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
#include <vector>

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

		// 单条条件求值（进度门槛与 INFO 门槛共用）。
		// ★ 第 64 轮（大项 K）：产出离线层的 CondCheck（三态 + 说明）——
		//   怎么把一串三态变成显示 / 隐藏 / 放行走 Decision（有单测），这里只管查引擎。
		Decision::CondCheck EvalOneCond(const StaticCondGate& a_g)
		{
			Decision::CondCheck out;
			const auto fid = Masters::MakeFormID(a_g.questMaster, a_g.questLocal);
			const auto* form = fid ? RE::TESForm::LookupByID(fid) : nullptr;
			if (!form) {
				// 目标任务取不到（master 没解析出来 / 记录不存在）⇒ 放行（kUnknown）。
				out.verdict = CondVerdict::kUnknown;
				out.detail = std::format("目标 0x{:08X} 取不到", fid);
				return out;
			}

			bool actual = false;
			if (a_g.check == kCondStageDone) {
				const auto fn = StageDoneFnOrNull();
				if (!fn) {
					out.verdict = CondVerdict::kUnknown;
					out.detail = "IsStageDone 不可用（游戏版本特征不符）";
					return out;
				}
				bool ok = false;
				if (!CallStageDoneChecked(reinterpret_cast<void*>(fn),
						const_cast<RE::TESForm*>(form), a_g.stage, ok)) {
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
				actual = (a_g.check == kCondRunning) ? st.running : st.completed;
			}

			if (actual != (a_g.want != 0)) {
				out.verdict = CondVerdict::kFail;
				const char* what = (a_g.check == kCondRunning) ? "running"
					: (a_g.check == kCondCompleted) ? "completed" : "stageDone";
				out.detail = std::format("0x{:08X} {}={} 期望 {}", fid, what,
					actual ? 1 : 0, a_g.want);
				return out;
			}
			out.verdict = CondVerdict::kPass;
			return out;
		}

		// ★★ 第 67 轮：任务链门槛的单边求值 —— 「前置任务的这个 stage 完成了吗」。
		//   与 EvalOneCond 的区别：这里**固定**就是 StageDone（没有 want/check 字段），
		//   语义 = 「这条启动边是否已经触发」。
		Decision::CondCheck EvalChainEdge(const StaticChainGate& a_e)
		{
			Decision::CondCheck out;
			const auto fid = Masters::MakeFormID(a_e.hostMaster, a_e.hostLocal);
			const auto* form = fid ? RE::TESForm::LookupByID(fid) : nullptr;
			if (!form) {
				// 前置任务取不到（master 没解析出来 / 记录不存在）⇒ 放行（kUnknown）。
				out.verdict = CondVerdict::kUnknown;
				out.detail = std::format("链式前置 0x{:08X} 取不到", fid);
				return out;
			}

			const auto fn = StageDoneFnOrNull();
			if (!fn) {
				out.verdict = CondVerdict::kUnknown;
				out.detail = "IsStageDone 不可用（游戏版本特征不符）";
				return out;
			}
			bool ok = false;
			if (!CallStageDoneChecked(reinterpret_cast<void*>(fn),
					const_cast<RE::TESForm*>(form), a_e.hostStage, ok)) {
				out.verdict = CondVerdict::kUnknown;
				out.detail = "IsStageDone 调用异常";
				return out;
			}
			if (!ok) {
				out.verdict = CondVerdict::kFail;
				out.detail = std::format("前置 0x{:08X} stage {} 未完成", fid, a_e.hostStage);
				return out;
			}
			out.verdict = CondVerdict::kPass;
			return out;
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

		// ★ 第 64 轮（大项 K）：逐条求值（只读查询）→ **聚合**交给离线层纯函数
		//   （Decision::DecideProgressGates —— 一条非 pass 即返回的语义与抽取前一致，
		//   有单测）。与抽取前的唯一差别：求值阶段不再短路（多查几条只读条件，无副作用）。
		std::vector<Decision::CondCheck> checks;
		checks.reserve(a_condCount);
		for (std::size_t i = 0; i < a_condCount; ++i) {
			checks.push_back(EvalOneCond(kQuestConds[a_condBegin + i]));
		}
		return Decision::DecideProgressGates(checks, 0, static_cast<std::uint8_t>(checks.size()));
	}

	CondEvalResult EvaluateInfoGates(std::uint32_t a_groupBegin, std::uint8_t a_groupCount)
	{
		CondEvalResult out;
		if (a_groupCount == 0) {
			return out;  // kNoGates：这条任务没有 INFO 门槛
		}
		if (a_groupBegin > kInfoGroupCount || a_groupCount > kInfoGroupCount - a_groupBegin) {
			out.verdict = CondVerdict::kUnknown;
			out.detail = "INFO 门槛切片越界";
			return out;
		}

		// ★ 第 64 轮（大项 K）：逐组求值（**组内短路**：找第一条 kFail 即停；某组没有
		//   kFail ⇒ 该对话可能可用 ⇒ 后面的组也不必求值了）→ **组间聚合**交给离线层
		//   纯函数（Decision::DecideInfoGates，有单测）。
		std::vector<Decision::InfoGroupEval> evals;
		evals.reserve(a_groupCount);
		for (std::size_t i = 0; i < a_groupCount; ++i) {
			const auto& grp = kInfoGroups[a_groupBegin + i];
			if (grp.condBegin > kInfoCondCount || grp.condCount > kInfoCondCount - grp.condBegin) {
				evals.push_back(Decision::InfoGroupEval{ .inRange = false });
				break;  // 切片越界 ⇒ 整条 kUnknown（后面不用求值了）
			}
			Decision::InfoGroupEval ev;
			for (std::size_t j = 0; j < grp.condCount; ++j) {
				const auto r = EvalOneCond(kInfoConds[grp.condBegin + j]);
				if (r.verdict == CondVerdict::kFail) {
					ev.hasKnownFalse = true;
					ev.firstFail = r.detail;
					break;
				}
				// kPass / kUnknown 都继续：unknown 不算「已知为假」（保守 —— 可能可用）。
			}
			const bool possible = !ev.hasKnownFalse;
			evals.push_back(std::move(ev));
			if (possible) {
				break;  // 这条对话可能可用 ⇒ 最终 kPass（与抽取前一致：不再求后面的组）
			}
		}
		return Decision::DecideInfoGates(evals);
	}

	CondEvalResult EvaluateChainGates(std::uint32_t a_edgeBegin, std::uint8_t a_edgeCount)
	{
		CondEvalResult out;
		if (a_edgeCount == 0) {
			return out;  // kNoGates：这条任务不是链式后续
		}
		if (a_edgeBegin > kChainGateCount || a_edgeCount > kChainGateCount - a_edgeBegin) {
			out.verdict = CondVerdict::kUnknown;
			out.detail = "链式门槛切片越界";
			return out;
		}

		// ★★ 第 67 轮：逐条边求值 → 聚合交给离线层纯函数
		//   （Decision::DecideChainGates：任一边已触发 ⇒ 放行；全部未触发 ⇒ 隐藏；
		//   有求值不了的边 ⇒ 放行）。
		std::vector<Decision::CondCheck> edges;
		edges.reserve(a_edgeCount);
		for (std::size_t i = 0; i < a_edgeCount; ++i) {
			edges.push_back(EvalChainEdge(kChainGates[a_edgeBegin + i]));
		}
		return Decision::DecideChainGates(edges);
	}
}
