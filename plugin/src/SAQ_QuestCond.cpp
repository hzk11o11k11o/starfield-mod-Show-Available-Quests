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
		//   （Decision::DecideProgressGates，有单测）。
		//   ★★ 第 87 轮：一并喂 OR 位（CTDA type bit0，引擎 OR 组语义见 docs/08 4.3）。
		std::vector<Decision::CondCheck> checks;
		std::vector<std::uint8_t> orBits;
		checks.reserve(a_condCount);
		orBits.reserve(a_condCount);
		for (std::size_t i = 0; i < a_condCount; ++i) {
			const auto& g = kQuestConds[a_condBegin + i];
			checks.push_back(EvalOneCond(g));
			orBits.push_back(g.orBit);
		}
		return Decision::DecideProgressGates(checks, orBits, 0, static_cast<std::uint8_t>(checks.size()));
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

		// ★ 第 64 轮（大项 K）：逐组求值 → **组间聚合**交给离线层纯函数
		//   （Decision::DecideInfoGates，有单测）。组间短路保留：某组可能可用 ⇒
		//   后面的组不必求值（与抽取前一致）。
		// ★ 第 106 轮（operator 全量产品化）：**组内**改用离线层的 OR 组聚合
		//   （Decision::DecideProgressGates —— 无 OR 位的条件相互 AND、OR 组内
		//   相互 OR、组作为整体参与 AND；引擎语义见 docs/08 4.3）——
		//   kInfoConds 第 6 元 = orBit（scan_info_gates.py 的 OR 组提取）。
		//   不再「找第一条 kFail 即停」：OR 组里某条为假 ≠ 整组为假。
		std::vector<Decision::InfoGroupEval> evals;
		evals.reserve(a_groupCount);
		for (std::size_t i = 0; i < a_groupCount; ++i) {
			const auto& grp = kInfoGroups[a_groupBegin + i];
			if (grp.condBegin > kInfoCondCount || grp.condCount > kInfoCondCount - grp.condBegin) {
				evals.push_back(Decision::InfoGroupEval{ .inRange = false });
				break;  // 切片越界 ⇒ 整条 kUnknown（后面不用求值了）
			}
			std::vector<Decision::CondCheck> checks;
			std::vector<std::uint8_t> orBits;
			checks.reserve(grp.condCount);
			orBits.reserve(grp.condCount);
			for (std::size_t j = 0; j < grp.condCount; ++j) {
				const auto& g = kInfoConds[grp.condBegin + j];
				checks.push_back(EvalOneCond(g));
				orBits.push_back(g.orBit);
			}
			Decision::InfoGroupEval ev;
			const auto r = Decision::DecideProgressGates(checks, orBits, 0,
				static_cast<std::uint8_t>(checks.size()));
			if (r.verdict == CondVerdict::kFail) {   // 组内「确定假」⇒ 这条对话不可用
				ev.hasKnownFalse = true;
				ev.firstFail = r.detail;
			}
			// kPass / kUnknown ⇒ 可能可用（unknown 不算「已知为假」，保守）。
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

#if SAQ_WITH_HARNESS
	// ★★★ 第 101 轮补丁（harness 只读探针 `quest.probe`，声明与设计说明见头文件）：
	//   一次报出「运行时状态 + 逐个 stage 的 IsStageDone」—— 与链式判定**同源**
	//   （同一个 StageDoneFnOrNull 特征校验 + 同一个 CallStageDoneChecked 保护调用）。
	std::string ProbeQuestStages(std::uint32_t a_formID, const std::vector<std::uint16_t>& a_stages)
	{
		const auto* form = a_formID
			? RE::TESForm::LookupByID(static_cast<RE::TESFormID>(a_formID))
			: nullptr;
		if (!form) {
			return std::format("quest.probe 0x{:08X}：表单取不到（master 没加载 / 记录不存在）", a_formID);
		}
		const auto st = ReadQuestRuntimeState(form);
		std::string out = std::format("quest.probe 0x{:08X}：{}", a_formID, Describe(st));
		if (a_stages.empty()) {
			out += "｜（没给 stage —— 用法 quest.probe <FormID> [stage...]）";
			return out;
		}
		const auto fn = StageDoneFnOrNull();
		if (!fn) {
			out += "｜IsStageDone 不可用（游戏版本特征不符）";
			return out;
		}
		for (const auto stage : a_stages) {
			bool ok = false;
			if (!CallStageDoneChecked(reinterpret_cast<void*>(fn),
					const_cast<RE::TESForm*>(form), stage, ok)) {
				out += std::format("｜stageDone({})=调用异常", stage);
				continue;
			}
			out += std::format("｜stageDone({})={}", stage, ok ? 1 : 0);
		}
		return out;
	}

	// ★★★ 第 106 轮（operator 全量产品化 · 只读探针 `info.probe`，设计见头文件）：
	//   列出该任务 INFO 门槛里**含 OR 位的对话组**的求值结果（组内走与产品相同的
	//   Decision::DecideProgressGates）+ 整任务结论（EvaluateInfoGates）。
	std::string ProbeInfoGates(std::uint32_t a_localFormID)
	{
		const StaticQuestInfo* q = nullptr;
		for (const auto& row : kQuestTable) {
			if (row.localFormID == a_localFormID) {
				q = &row;
				break;
			}
		}
		if (!q) {
			return std::format("INFO探针 0x{:06X}：静态表里没有这条记录号", a_localFormID);
		}
		if (q->infoGroupCount == 0) {
			return std::format("INFO探针 0x{:06X}：这条任务没有 INFO 门槛", a_localFormID);
		}
		if (q->infoGroupBegin > kInfoGroupCount
			|| q->infoGroupCount > kInfoGroupCount - q->infoGroupBegin) {
			return std::format("INFO探针 0x{:06X}：INFO 门槛切片越界", a_localFormID);
		}
		std::string groups;
		int n_or = 0;
		int n_oob = 0;
		for (std::size_t gi = 0; gi < q->infoGroupCount; ++gi) {
			const auto& grp = kInfoGroups[q->infoGroupBegin + gi];
			if (grp.condBegin > kInfoCondCount
				|| grp.condCount > kInfoCondCount - grp.condBegin) {
				++n_oob;
				continue;
			}
			std::vector<Decision::CondCheck> checks;
			std::vector<std::uint8_t> orBits;
			checks.reserve(grp.condCount);
			orBits.reserve(grp.condCount);
			bool hasOr = false;
			std::string condStr;
			for (std::size_t j = 0; j < grp.condCount; ++j) {
				const auto& g = kInfoConds[grp.condBegin + j];
				checks.push_back(EvalOneCond(g));
				orBits.push_back(g.orBit);
				if (g.orBit) {
					hasOr = true;
				}
				if (!condStr.empty()) {
					condStr += "+";
				}
				// 条件串：StageDone 用 stage 号（s112）；Run/Completed 用被检查任务记录号
				condStr += (g.check == kCondStageDone)
					? std::format("s{}", g.stage)
					: std::format("q0x{:06X}", g.questLocal & 0xFFFFFFu);
				if (g.orBit) {
					condStr += "[OR]";
				}
			}
			if (!hasOr) {
				continue;   // 只报含 OR 位的组（本次改动的作用面）
			}
			++n_or;
			if (n_or > 8) {
				continue;   // 输出上限（证据够用即可）
			}
			const auto r = Decision::DecideProgressGates(checks, orBits, 0,
				static_cast<std::uint8_t>(checks.size()));
			const char* res = (r.verdict == CondVerdict::kPass) ? "真"
				: (r.verdict == CondVerdict::kFail ? "假" : "未知");
			groups += std::format("｜组[{}]:{}{}", gi, condStr, res);
		}
		const auto fin = EvaluateInfoGates(q->infoGroupBegin, q->infoGroupCount);
		const char* finName = (fin.verdict == CondVerdict::kNoGates) ? "无门槛"
			: (fin.verdict == CondVerdict::kPass ? "放行"
				: (fin.verdict == CondVerdict::kFail ? "隐藏" : "未知(放行)"));
		return std::format("INFO探针 0x{:06X}：门槛对话={}｜含OR组={}{}｜任务={}{}",
			a_localFormID, q->infoGroupCount, n_or, groups, finName,
			(n_oob > 0) ? std::format("｜切片越界{}", n_oob) : std::string{});
	}
#endif  // SAQ_WITH_HARNESS
}
