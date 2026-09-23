#pragma once
// 本文件由 tools/esm/gen_entry_table.py 自动生成，请勿手改。
//
// 「无限任务入口」条目（AGENTS.md 需求 —— 无限生成任务本身不显示，但「接取入口」
// 作为一条数据显示在列表里，点了就引导到它的位置）。两类：
//   kind=0（任务板，13 条）：ACTIVATOR `MissionBoardConsole*`，名字「任务板 · <地点>」；
//     ★★ 第 110 轮 +1：追踪者联盟总部（SFBGS003.esm · medium 档手工条目，见 EXTRA_ENTRIES）
//        —— ★★★ 第 150 轮：它追加在**任务板段末尾**、与 12 条基础任务板连成一段
//        （界面里紧挨其它「任务板 · <地点>」；此前排在表末尾 ⇒ 混进了「（可重复）…」堆）；
//   kind=1（可重复 NPC，8 条）：贸易管理局商人 / 追踪者联盟探员（第 80 轮），
//     名字自带「（可重复）」前缀 —— 数据 ref/repeatable_givers.json；
//     ★★★ 第 150 轮：本表**行顺序 = 界面列表顺序**（DLL 按表追加 + 组内稳定排序）
//       —— 段序固定为「任务板段 → 可重复 NPC 段」（main 有布局硬校验）。
//
// 字段说明（★ 第 30 轮起，引导目标是**候选链**：DLL 依次 LookupByID 取第一个命中的）——
//   refLocal   条目引用的记录号（任务板 ACTIVATOR / NPC 的 ACHR）—— 同时是界面条目的
//              uID（运行期 FormID）。
//   master     所属 master 下标（kQuestMasters[]；第 110 轮起含 SFBGS003.esm=medium）。
//   persistent 条目引用自身是否**原生常驻**（20 条里只有阿基拉城任务板是）。
//   markerLocal ① 本插件（ESM 记录号：任务板 0x900~0x90A、NPC 0x90B~0x911）新建的
//              **常驻 XMarker**，位置 = 条目坐标：常驻引用在 cell 未加载时依然存在
//              ⇒ 任何位置都取得到 ⇒ 引导目标。外景条目（阿基拉城广场的探员）不建
//              marker（外景 cell 无 per-cell 常驻引用可挂），= 0。
//              运行期 FormID = (本插件加载序号 << 24) | markerLocal —— 前缀取
//              Guide 通道的 ch.prefix（SAQ_Guide.cpp 已认领的值）。
//   fallback1/2 ③ 兜底候选（XMarker 系优先、≤25 m）—— 位置差 1~7 m：
//              内景条目 = 同 cell 的原生常驻引用；外景条目 = 该 worldspace 的**世界级
//              常驻引用**（`WRLD > WorldChildren > CellChildren > CellPersistent`）。
//   kind       0 = 任务板（AS3 type 100，子项「前往任务板」）；
//              1 = 可重复 NPC（AS3 type 101，子项「找他接活」+ 名字带「（可重复）」）。
//   nameZh/En  列表里显示的名字（中英都推，AS3 按游戏语言挑）。
//
// 实机排查看 DLL 日志的「入口=…(可导航 N｜marker a 原板 b 兜底 c 不可用 d)」与
// 「入口候选诊断：…」（SAQ.cpp::AppendEntryRows）。

#include <cstdint>

namespace SAQ
{
	// ★ 第 80 轮：与 AS3 载荷 type / gen_entry_table.py 的 KIND_* 对应。
	enum EntryKind : std::uint8_t
	{
		kEntryKindBoard = 0,        // 任务板（AS3 type 100）
		kEntryKindRepeatNpc = 1,    // 提供无限任务的 NPC（AS3 type 101）
	};

	struct StaticEntryInfo
	{
		std::uint32_t refLocal;
		std::uint8_t  master;
		bool          persistent;
		std::uint32_t markerLocal;   // ① 新建常驻 XMarker（0 = 没有）
		std::uint32_t fallback1;     // ③ 兜底候选（内景 = 同 cell；外景 = 同 world 世界级）
		std::uint32_t fallback2;
		std::uint8_t  kind;          // ★ 第 80 轮：EntryKind
		const char*   nameEn;
		const char*   nameZh;
	};

	inline constexpr StaticEntryInfo kEntryTable[] = {
		{ 0x0021001eu, 0u, false, 0x0000090au, 0x0002c14fu, 0x002bd876u, 0u, "Mission Board - New Atlantis", "任务板 · 新亚特兰蒂斯城" },
		{ 0x0014d497u, 0u, true , 0x00000000u, 0x0008c56du, 0x0013fa21u, 0u, "Mission Board - Akila City", "任务板 · 阿基拉城" },
		{ 0x00148c93u, 0u, false, 0x00000903u, 0x002bab78u, 0x0023ca79u, 0u, "Mission Board - Neon", "任务板 · 霓虹城" },
		{ 0x001df853u, 0u, false, 0x00000909u, 0x0029f410u, 0x0013d957u, 0u, "Mission Board - Cydonia", "任务板 · 赛多尼亚" },
		{ 0x001ded95u, 0u, false, 0x00000907u, 0x001fa55fu, 0x001eb56du, 0u, "Mission Board - Hopetown", "任务板 · 霍普镇" },
		{ 0x001df5bdu, 0u, false, 0x00000908u, 0x0021a870u, 0x0004a177u, 0u, "Mission Board - New Homestead", "任务板 · 新家园" },
		{ 0x00137573u, 0u, false, 0x00000901u, 0x0011b754u, 0x00110fb5u, 0u, "Mission Board - The Lodge", "任务板 · 陋室" },
		{ 0x0013f738u, 0u, false, 0x00000902u, 0x000c4078u, 0x000c406eu, 0u, "Mission Board - Ryujin Industries", "任务板 · 龙神集团" },
		{ 0x000c2d64u, 0u, false, 0x00000900u, 0x003de5a0u, 0x003de5a1u, 0u, "Mission Board - Deimos Staryards", "任务板 · 火卫二造船厂" },
		{ 0x0016265fu, 0u, false, 0x00000904u, 0x00205de2u, 0x0025a67au, 0u, "Mission Board - Trident Staryard", "任务板 · 海神叉造船厂" },
		{ 0x00167872u, 0u, false, 0x00000905u, 0x00001712u, 0x0011c577u, 0u, "Mission Board - Stroud-Eklund Staryards", "任务板 · 斯特劳艾克伦集团造船厂" },
		{ 0x00197d22u, 0u, false, 0x00000906u, 0x00315942u, 0x0022eef0u, 0u, "Mission Board - The Key", "任务板 · 星钥站" },
		{ 0xfd0024adu, 1u, false, 0x00000000u, 0xfd00f9ceu, 0xfd000033u, 0u, "Mission Board - Trackers Alliance HQ", "任务板 · 追踪者联盟总部" },
		{ 0x00214684u, 0u, false, 0x00000910u, 0x000c35bau, 0x0033d022u, 1u, "(Repeatable) Trade Authority - Duncan Lynch", "（可重复）贸易管理局 · 邓肯·林奇" },
		{ 0x00115442u, 0u, false, 0x0000090cu, 0x0015b130u, 0x0013154cu, 1u, "(Repeatable) Trade Authority - Kolman Lang", "（可重复）贸易管理局 · 科尔曼·朗" },
		{ 0x000137b2u, 0u, false, 0x0000090bu, 0x0024f4e8u, 0x0024f4e7u, 1u, "(Repeatable) Trade Authority - Zoe Kaminski", "（可重复）贸易管理局 · 卓伊·卡明斯基" },
		{ 0x00261764u, 0u, false, 0x00000911u, 0x00003a63u, 0x00299cd8u, 1u, "(Repeatable) Trade Authority - Saoirse Bowden", "（可重复）贸易管理局 · 希尔莎·包登" },
		{ 0x00216d34u, 0u, false, 0x00000000u, 0x0021d003u, 0x001cf972u, 1u, "(Repeatable) Trackers Alliance Agent - Akila City", "（可重复）追踪者联盟探员 · 阿基拉城" },
		{ 0x001d8bd1u, 0u, false, 0x0000090fu, 0x0024afd2u, 0x0024afd1u, 1u, "(Repeatable) Trackers Alliance Agent - Cydonia", "（可重复）追踪者联盟探员 · 赛多尼亚" },
		{ 0x001d8bceu, 0u, false, 0x0000090eu, 0x0010cac4u, 0x0010cac5u, 1u, "(Repeatable) Trackers Alliance Agent - Neon", "（可重复）追踪者联盟探员 · 霓虹城" },
		{ 0x001b20b3u, 0u, false, 0x0000090du, 0x001ebffdu, 0x001ebffbu, 1u, "(Repeatable) Trackers Alliance Agent - New Atlantis", "（可重复）追踪者联盟探员 · 新亚特兰蒂斯城" },
	};
	inline constexpr std::size_t kEntryTableSize = 21;
}
