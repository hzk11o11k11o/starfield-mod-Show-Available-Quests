#pragma once
// 本文件由 tools/esm/gen_entry_table.py 自动生成，请勿手改。
//
// 「无限任务入口」条目（任务板）：AGENTS.md 需求 —— 无限生成任务本身不显示，
// 但「接取入口」（任务板）作为一条数据显示在列表里，点了就引导到它的位置。
//
// 字段说明：
//   refLocal   任务板 ACTIVATOR（MissionBoardConsole*）在世界里的放置引用（REFR）记录号。
//              ★ 它同时是界面条目的 uID（运行期 FormID）：与任务的 FormID 空间不冲突，
//                且「引导目标 = 它自己」（DLL 收到该 uID 的引导请求时直接写这个引用）。
//   master     所属 master 下标（kQuestMasters[]；目前全部在 Starfield.esm）。
//   persistent REFR 是否常驻引用 —— **引导能不能生效的关键**：
//              非常驻引用在所在 cell 未加载时脚本 Game.GetForm 取不到（状态 2）。
//              实机验证哪块板能引导就看这一列（见 docs/99 第 27 轮）。
//   nameZh/En  列表里显示的名字（中英都推，AS3 按游戏语言挑）。

#include <cstdint>

namespace SAQ
{
	struct StaticEntryInfo
	{
		std::uint32_t refLocal;
		std::uint8_t  master;
		bool          persistent;
		const char*   nameEn;
		const char*   nameZh;
	};

	inline constexpr StaticEntryInfo kEntryTable[] = {
		{ 0x0021001eu, 0u, false, "Mission Board - New Atlantis", "任务板 · 新亚特兰蒂斯" },
		{ 0x0014d497u, 0u, true , "Mission Board - Akila City", "任务板 · 阿基拉城" },
		{ 0x00148c93u, 0u, false, "Mission Board - Neon", "任务板 · 霓虹城" },
		{ 0x001df853u, 0u, false, "Mission Board - Cydonia", "任务板 · 塞多尼亚" },
		{ 0x001ded95u, 0u, false, "Mission Board - Hopetown", "任务板 · 霍普镇" },
		{ 0x001df5bdu, 0u, false, "Mission Board - New Homestead", "任务板 · 新家园" },
		{ 0x00137573u, 0u, false, "Mission Board - The Lodge", "任务板 · 星座小屋" },
		{ 0x0013f738u, 0u, false, "Mission Board - Ryujin Industries", "任务板 · 龙神工业" },
		{ 0x000c2d64u, 0u, false, "Mission Board - Deimos Staryard", "任务板 · 狄摩斯星船厂" },
		{ 0x0016265fu, 0u, false, "Mission Board - Trident Staryard", "任务板 · 三叉戟星船厂" },
		{ 0x00167872u, 0u, false, "Mission Board - Stroud-Eklund Staryard", "任务板 · 斯特劳德-埃克伦德星船厂" },
		{ 0x00197d22u, 0u, false, "Mission Board - The Key", "任务板 · 星钥站" },
	};
	inline constexpr std::size_t kEntryTableSize = 12;
}
