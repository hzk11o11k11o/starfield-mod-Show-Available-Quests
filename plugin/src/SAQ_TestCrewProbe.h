#pragma once
// 本文件由 tools/esm/gen_hirable_crew.py 自动生成，请勿手改。
//
// ★★ 第 155 轮（可招募船员跟踪 · 研究）：harness 只读探针 `crew.probe` 的数据表
//   —— 24 位可招募船员的 { 放置引用, 招募载体任务, 名字 }。
//   为什么需要：探针要在实机上把每位船员的「crew faction 三件套成员状态」
//   （Papyrus `Actor.IsInFaction`，需引用已加载）与「招募任务运行时状态」
//   （DLL 直读）配对读出来 —— 用于验证「已招募 ⇒ 隐藏」的判据（docs/16 16.3）。
//   本文件只被 SAQ_Test.cpp include（`#if SAQ_WITH_HARNESS` 内）—— 发布构建不含。
//   数据来源 = ref/hirable_crew.json（同一次扫描产出）。
#if SAQ_WITH_HARNESS

#include <cstdint>

namespace SAQ::Test
{
	struct CrewProbeInfo
	{
		std::uint32_t refForm;     // ACHR 放置引用（Starfield.esm，运行期 FormID 同值）
		std::uint32_t questForm;   // 招募载体任务 CREW_EliteCrew_*（同上）
		bool          noNav;       // 位置不适合导航（暂存格 / 运行时生成内景）
		const char*   nameZh;
		const char*   nameEn;
	};

	inline constexpr CrewProbeInfo kCrewProbeTable[] = {
		{ 0x001631c5u, 0x000078deu, false, "铁杆粉丝", "Adoring Fan" },
		{ 0x00299f66u, 0x0018e24fu, false, "阿梅莉亚·埃尔哈特", "Amelia Earhart" },
		{ 0x0016b3d0u, 0x0016b408u, false, "安德洛美达·开普勒", "Andromeda Kepler" },
		{ 0x001f0262u, 0x0019c209u, false, "奥特姆·麦克米伦", "Autumn MacMillan" },
		{ 0x0020dc69u, 0x0014e8f7u, true , "贝蒂·侯赛", "Betty Howser" },
		{ 0x001cdafcu, 0x001cdafbu, false, "丹尼·卡尔西亚", "Dani Garcia" },
		{ 0x0022198cu, 0x00196baeu, true , "埃里克·冯·普莱斯", "Erick Von Price" },
		{ 0x0017a859u, 0x0017a964u, false, "以西结", "Ezekiel" },
		{ 0x00015064u, 0x00014e55u, false, "吉迪恩·艾克", "Gideon Aker" },
		{ 0x002b17c4u, 0x001b3f7eu, false, "哈德良", "Hadrian" },
		{ 0x0000563cu, 0x001ad42eu, false, "海勒", "Heller" },
		{ 0x001d898eu, 0x001d8ae3u, false, "杰萨敏·格弗林", "Jessamine Griffin" },
		{ 0x00005639u, 0x001a8d9cu, false, "林监工", "Supervisor Lin" },
		{ 0x0017a858u, 0x001c50deu, false, "莱尔·布鲁尔", "Lyle Brewer" },
		{ 0x00015062u, 0x001e5e40u, false, "玛丽卡·波罗斯", "Marika Boros" },
		{ 0x000189b2u, 0x001bf8a1u, false, "马西斯·卡斯蒂罗", "Mathis Castillo" },
		{ 0x0016d16au, 0x0016d3c8u, false, "米奇·卡威亚", "Mickey Caviar" },
		{ 0x0029c982u, 0x001a430du, true , "莫亚拉·奥泰罗", "Moara Otero" },
		{ 0x001593f8u, 0x001594bfu, false, "奥马里·哈桑", "Omari Hassan" },
		{ 0x000c4632u, 0x001933d5u, false, "拉斐尔·阿盖罗", "Rafael Aguerro" },
		{ 0x001a0cb1u, 0x001d65c0u, false, "罗茜·泰诺希", "Rosie Tannehill" },
		{ 0x00015063u, 0x001df911u, false, "西米恩·班科夫斯基", "Simeon Bankowski" },
		{ 0x00147954u, 0x001499efu, false, "索菲亚·格雷丝", "Sophia Grace" },
		{ 0x000057beu, 0x00256f51u, false, "瓦斯科", "Vasco" },
	};
	inline constexpr std::size_t kCrewProbeCount = sizeof(kCrewProbeTable) / sizeof(kCrewProbeTable[0]);
}

#endif  // SAQ_WITH_HARNESS
