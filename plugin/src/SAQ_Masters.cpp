// ============================================================================
//  SAQ_Masters 实现（设计与证据见 SAQ_Masters.h 顶部注释）
// ============================================================================

#include "PCH.h"

#include "SAQ_Masters.h"
#include "SAQ_QuestState.h"   // 抽样自校验要核验虚表（确认取到的是 TESQuest）
#include "SAQ_QuestTable.h"   // 生成物：kQuestMasters / kQuestTable

#include "RE/B/BSTList.h"
#include "RE/IDs.h"
#include "RE/T/TESDataHandler.h"
#include "RE/T/TESFile.h"
#include "RE/T/TESForm.h"

#include <format>
#include <vector>

namespace SAQ::Masters
{
	namespace
	{
		constexpr std::uint32_t kLightPrefix = 0xFE000000u;  // light 插件的 FormID 前缀
		constexpr std::uint32_t kLocalMaskPlain = 0x00FFFFFFu;
		constexpr std::uint32_t kLocalMaskSmall = 0x00000FFFu;
		constexpr std::uint32_t kSamplePerMaster = 6;        // 抽样自校验条数

		std::vector<Master> g_masters;
		std::string         g_lastDescribe;

		bool EqualNoCase(const char* a_lhs, std::string_view a_rhs) noexcept
		{
			std::size_t i = 0;
			for (; i < a_rhs.size(); ++i) {
				char a = a_lhs[i];
				if (a == '\0') {
					return false;
				}
				char b = a_rhs[i];
				if (a >= 'A' && a <= 'Z') {
					a = static_cast<char>(a - 'A' + 'a');
				}
				if (b >= 'A' && b <= 'Z') {
					b = static_cast<char>(b - 'A' + 'a');
				}
				if (a != b) {
					return false;
				}
			}
			return a_lhs[i] == '\0';
		}

		// 在「当前加载的插件列表」里按名字找（大小写不敏感：ESM 的 MAST 里是全小写，
		// 而 plugins.txt / 文件夹里可能是 Starfield.esm 这种写法）。
		RE::TESFile* FindLoadedFile(std::string_view a_name)
		{
			auto* dh = RE::TESDataHandler::GetSingleton();
			if (!dh) {
				return nullptr;
			}
			for (auto* file : dh->files) {
				if (file && EqualNoCase(file->fileName, a_name)) {
					return file;
				}
			}
			return nullptr;
		}

		void ResolveOne(Master& a_master)
		{
			auto* file = FindLoadedFile(a_master.name);
			if (!file) {
				a_master.loaded = false;
				return;
			}
			a_master.loaded = true;
			a_master.small = file->fileFlags.any(RE::TESFile::Flags::kSmall);

			// medium / blueprint 这两种档位的 FormID 方案本项目还没验证过 —— 与其猜，
			// 不如明确标记「不支持」并让调用方跳过（日志里会写出来，方便以后补）。
			const bool exotic = file->fileFlags.any(RE::TESFile::Flags::kMedium) ||
			                    file->fileFlags.any(RE::TESFile::Flags::kBlueprint);
			if (exotic) {
				a_master.supported = false;
				// 仍然记下序号，日志里能看到它到底排在哪儿
				a_master.index = a_master.small ? file->fileIndex.smallIndex : file->fileIndex.fullIndex;
				a_master.prefix = 0;
				return;
			}

			if (a_master.small) {
				a_master.index = file->fileIndex.smallIndex;
				a_master.prefix = kLightPrefix | (a_master.index << 12);
			} else {
				a_master.index = file->fileIndex.fullIndex;
				a_master.prefix = a_master.index << 24;
			}
			a_master.supported = true;
		}

		// 抽样自校验：拿表里属于这个 master 的几个记录号，问引擎要表单并核验虚表。
		// 这是「序号/位宽算错了」的自动报警器 —— 算错时日志会出现「样本 0/6」。
		void SelfCheck(Master& a_master, std::size_t a_masterIndex)
		{
			a_master.sampleOk = 0;
			a_master.sampleTry = 0;
			if (!a_master.loaded || !a_master.supported) {
				return;
			}
			for (std::size_t i = 0; i < kQuestTableSize && a_master.sampleTry < kSamplePerMaster; ++i) {
				const auto& info = kQuestTable[i];
				if (info.master != a_masterIndex) {
					continue;
				}
				++a_master.sampleTry;
				const auto id = MakeFormID(a_masterIndex, info.localFormID);
				if (id == 0) {
					continue;
				}
				if (const auto* form = RE::TESForm::LookupByID(static_cast<RE::TESFormID>(id))) {
					if (ReadQuestRuntimeState(form).vtableKnown) {
						++a_master.sampleOk;
					}
				}
			}
		}
	}

	void Refresh()
	{
		g_masters.assign(kQuestMasterCount, Master{});
		for (std::size_t i = 0; i < kQuestMasterCount; ++i) {
			auto& m = g_masters[i];
			m.name = kQuestMasters[i];
			m.supported = true;
			ResolveOne(m);
			SelfCheck(m, i);
		}
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
		if (!m.loaded || !m.supported) {
			return 0;  // 没装 / 没启用 / 档位不支持 ⇒ 这条任务当「不存在」
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
				out += std::format("{} 未加载（跳过其任务）", m.name);
			} else if (!m.supported) {
				out += std::format("{} 序号=0x{:02X} 档位暂不支持（medium/blueprint，跳过其任务）",
					m.name, m.index);
			} else {
				out += std::format("{} 序号=0x{:02X}{} 前缀=0x{:02X} 样本 {}/{}",
					m.name, m.index, m.small ? "(light)" : "", m.prefix >> 24,
					m.sampleOk, m.sampleTry);
			}
		}
		return out;
	}
}
