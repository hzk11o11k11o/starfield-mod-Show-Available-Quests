// ============================================================================
//  SAQ_Masters 实现（设计与证据见 SAQ_Masters.h 顶部注释）
//
//  ★ 第 18 轮重写：**不再读 TESDataHandler::files**（commonlibsf 的结构体偏移
//  在本游戏版本上不可信 —— formArrays 第 5 轮踩过、files 第 17 轮踩过），
//  改成「前缀探测」：只用 LookupByID + 虚表核验反推每个 master 的加载序号。
// ============================================================================

#include "PCH.h"

#include "SAQ_Masters.h"
#include "SAQ_QuestState.h"   // 虚表核验（确认查到的对象是 TESQuest）
#include "SAQ_QuestTable.h"   // 生成物：kQuestMasters / kQuestTable

#include "RE/IDs.h"
#include "RE/T/TESForm.h"

#include <algorithm>
#include <format>
#include <vector>

namespace SAQ::Masters
{
	namespace
	{
		constexpr std::uint32_t kLightPrefix = 0xFE000000u;  // light(ESL) 插件的 FormID 前缀
		constexpr std::uint32_t kLocalMaskPlain = 0x00FFFFFFu;
		constexpr std::uint32_t kLocalMaskSmall = 0x00000FFFu;
		constexpr std::uint32_t kMaxFullPrefix = 0xFDu;      // 0xFE 留给 light；0xFF 没有插件
		constexpr std::uint32_t kMaxLightIndex = 0xFFFu;     // light 插件序号是 12 位
		constexpr std::size_t   kProbeSamples = 6;           // 阶段 1 最多换这么多条样本扫（一命中即停）
		constexpr unsigned      kAcceptPercent = 90;         // 认定阈值：全量确认命中率 ≥ 90%

		std::vector<Master> g_masters;
		bool                g_sessionResolved = false;  // 基础游戏解析成功 ⇒ 本会话不再重扫
		std::string         g_lastFailNote;             // 失败留证去重（内容没变就不重复打）

		// 查一个运行期 FormID 并核验虚表：只有「引擎里查得到 + 是 TESQuest」才算命中。
		bool ProbeForm(std::uint32_t a_formID)
		{
			const auto* form = RE::TESForm::LookupByID(static_cast<RE::TESFormID>(a_formID));
			return form != nullptr && ReadQuestRuntimeState(form).vtableKnown;
		}

		// 候选：full 插件用 prefix(0x00..0xFD)；light 插件用 smallIndex(0x000..0xFFF)。
		struct Candidate
		{
			bool          small{};
			std::uint32_t index{};
		};

		std::uint32_t CandidateFormID(const Candidate& a_candidate, std::uint32_t a_local)
		{
			return a_candidate.small
				? (kLightPrefix | (a_candidate.index << 12) | (a_local & kLocalMaskSmall))
				: ((a_candidate.index << 24) | (a_local & kLocalMaskPlain));
		}

		std::uint32_t CandidatePrefix(const Candidate& a_candidate)
		{
			return a_candidate.small
				? (kLightPrefix | (a_candidate.index << 12))
				: (a_candidate.index << 24);
		}

		// 该 master 在静态表里的记录号：去重 + 等距取 ≤ kProbeSamples 条（首尾都覆盖）。
		std::vector<std::uint32_t> CollectSamples(std::size_t a_masterIndex)
		{
			std::vector<std::uint32_t> all;
			for (std::size_t i = 0; i < kQuestTableSize; ++i) {
				if (static_cast<std::size_t>(kQuestTable[i].master) == a_masterIndex) {
					all.push_back(kQuestTable[i].localFormID);
				}
			}
			std::sort(all.begin(), all.end());
			all.erase(std::unique(all.begin(), all.end()), all.end());
			if (all.size() <= kProbeSamples) {
				return all;
			}
			std::vector<std::uint32_t> out;
			out.reserve(kProbeSamples);
			for (std::size_t i = 0; i < kProbeSamples; ++i) {
				out.push_back(all[i * (all.size() - 1) / (kProbeSamples - 1)]);
			}
			return out;
		}

		// 该 master 在静态表里的记录条数。
		std::uint32_t CountRecords(std::size_t a_masterIndex)
		{
			std::uint32_t total = 0;
			for (std::size_t i = 0; i < kQuestTableSize; ++i) {
				if (static_cast<std::size_t>(kQuestTable[i].master) == a_masterIndex) {
					++total;
				}
			}
			return total;
		}

		// 失败留证：内容变化才打（未解析成功的会话里每次开菜单都会走到这）。
		void NoteFailure(std::string a_note)
		{
			if (a_note == g_lastFailNote) {
				return;
			}
			g_lastFailNote = std::move(a_note);
			REX::WARN("前缀探测：{}", g_lastFailNote);
		}

		void ResolveOne(Master& a_master, std::size_t a_masterIndex)
		{
			a_master.loaded = false;
			a_master.small = false;
			a_master.index = 0;
			a_master.prefix = 0;
			a_master.sampleOk = 0;
			a_master.sampleTry = 0;

			const auto samples = CollectSamples(a_masterIndex);
			if (samples.empty()) {
				return;  // 表里没有这个 master 的记录（生成器问题；Describe 会显示 0/0）
			}

			// ---- 阶段 1：找候选 ----------------------------------------------
			// 用样本逐条扫全空间；一命中即停（多样本是为了容忍「某条记录被别的
			// 插件删掉」——那时换下一条样本继续找）。
			std::vector<Candidate> candidates;
			for (const auto local : samples) {
				if (!candidates.empty()) {
					break;
				}
				for (std::uint32_t prefix = 0; prefix <= kMaxFullPrefix; ++prefix) {
					if (ProbeForm((prefix << 24) | (local & kLocalMaskPlain))) {
						candidates.push_back(Candidate{ false, prefix });
					}
				}
				if (candidates.empty()) {
					// full 段一个都没命中，才扫 light 空间（0xFE | smallIndex<<12）。
					// 本机四个 master 都是 full 插件 —— 这一步是为「以后表里加 light
					// master」留的（算法来自 docs/06，尚未有真实样本可验）。
					for (std::uint32_t idx = 0; idx <= kMaxLightIndex; ++idx) {
						if (ProbeForm(kLightPrefix | (idx << 12) | (local & kLocalMaskSmall))) {
							candidates.push_back(Candidate{ true, idx });
						}
					}
				}
			}
			if (candidates.empty()) {
				return;  // 未加载（或档位不支持）⇒ 调用方整批跳过
			}

			// ---- 阶段 2：用全部记录数命中率，取最高者；≥ 90% 才认定 ----------
			const auto total = CountRecords(a_masterIndex);
			const Candidate* best = nullptr;
			std::uint32_t    bestHits = 0;
			for (const auto& candidate : candidates) {
				std::uint32_t hits = 0;
				for (std::size_t i = 0; i < kQuestTableSize; ++i) {
					const auto& info = kQuestTable[i];
					if (static_cast<std::size_t>(info.master) != a_masterIndex) {
						continue;
					}
					if (ProbeForm(CandidateFormID(candidate, info.localFormID))) {
						++hits;
					}
				}
				if (best == nullptr || hits > bestHits) {
					best = &candidate;
					bestHits = hits;
				}
			}
			if (best == nullptr || total == 0 ||
				bestHits * 100 < total * static_cast<std::uint32_t>(kAcceptPercent)) {
				NoteFailure(std::format(
					"{} 探测到 {} 个候选前缀，但全量确认最高只有 {}/{}（<{}%）——按「未加载」处理",
					a_master.name, candidates.size(), bestHits, total, kAcceptPercent));
				return;
			}

			a_master.loaded = true;
			a_master.small = best->small;
			a_master.index = best->index;
			a_master.prefix = CandidatePrefix(*best);
			a_master.sampleOk = bestHits;
			a_master.sampleTry = total;

			if (candidates.size() > 1) {
				// 极少见：一条样本在多个前缀下同时命中（别的插件里有同号记录）。
				// 已按全量命中率选出最高者，留一条证据即可。
				REX::INFO("前缀探测：{} 有 {} 个候选前缀，按全量命中率取 0x{:08X}（{} 命中 {}/{}）",
					a_master.name, candidates.size(), a_master.prefix,
					a_master.small ? "light" : "full", a_master.sampleOk, a_master.sampleTry);
			}
		}
	}

	void Refresh()
	{
		if (g_sessionResolved) {
			return;  // 一次游戏运行内加载顺序不会变 —— 解析成功后复用（读档也不变）
		}

		g_masters.assign(kQuestMasterCount, Master{});
		for (std::size_t i = 0; i < kQuestMasterCount; ++i) {
			auto& m = g_masters[i];
			m.name = kQuestMasters[i];
			ResolveOne(m, i);
		}

		// 自检锚点：Starfield.esm 必须解析出 0x00（基础游戏永远是第一个 master）。
		// 不符 ⇒ 探测法本身可能有问题，或「游戏尚未就绪」——留 WARN 作证据，且
		// **不缓存**结果（下次打开菜单重试），避免把瞬时状态钉死成「表里什么都没有」。
		const bool baseOk = !g_masters.empty() && g_masters[0].loaded && !g_masters[0].small &&
		                    g_masters[0].index == 0;
		if (baseOk) {
			g_sessionResolved = true;
			return;
		}
		NoteFailure(g_masters.empty()
				? std::string{ "master 表为空（生成器问题？）" }
				: std::format("自检未通过：Starfield.esm 未解析出 0x00（loaded={} small={} 序号=0x{:02X}）"
							  "—— 本次不缓存，下次打开菜单重试",
					  g_masters[0].loaded, g_masters[0].small, g_masters[0].index));
	}

	std::size_t Count()
	{
		return g_masters.size();
	}

	const Master& Get(std::size_t a_index)
	{
		static const Master kEmpty{};
		return a_index < g_masters.size() ? g_masters[a_index] : kEmpty;
	}

	std::uint32_t MakeFormID(std::size_t a_master, std::uint32_t a_local)
	{
		if (a_master >= g_masters.size()) {
			return 0;
		}
		const auto& m = g_masters[a_master];
		if (!m.loaded) {
			return 0;  // 没装 / 没启用 ⇒ 这条任务当「不存在」
		}
		const auto local = m.small ? (a_local & kLocalMaskSmall) : (a_local & kLocalMaskPlain);
		return m.prefix | local;
	}

	std::string Describe()
	{
		std::string out;
		for (std::size_t i = 0; i < g_masters.size(); ++i) {
			const auto& m = g_masters[i];
			if (!out.empty()) {
				out += "；";
			}
			if (!m.loaded) {
				out += std::format("{} 未加载（或档位不支持，跳过其任务）", m.name);
			} else if (m.small) {
				out += std::format("{} 序号=0x{:03X}(light) 前缀=0xFE|0x{:03X}<<12 记录命中 {}/{}",
					m.name, m.index, m.index, m.sampleOk, m.sampleTry);
			} else {
				out += std::format("{} 序号=0x{:02X} 前缀=0x{:02X} 记录命中 {}/{}",
					m.name, m.index, m.index, m.sampleOk, m.sampleTry);
			}
		}
		return out;
	}
}
