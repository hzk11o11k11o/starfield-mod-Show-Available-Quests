#pragma once
// 本文件由 tools/esm/gen_entry_table.py 自动生成，请勿手改。
//
// 「无限任务入口」条目（任务板）：AGENTS.md 需求 —— 无限生成任务本身不显示，
// 但「接取入口」（任务板）作为一条数据显示在列表里，点了就引导到它的位置。
//
//
// 字段说明（★ 第 30 轮起，引导目标是**候选链**：DLL 依次 LookupByID 取第一个命中的）——
//   refLocal   任务板 ACTIVATOR 的放置引用记录号 —— 同时是界面条目的 uID（运行期 FormID）。
//   master     所属 master 下标（kQuestMasters[]；目前全部在 Starfield.esm）。
//   persistent 任务板引用自身是否**原生常驻**（12 条里只有阿基拉城是）。
//   markerLocal ① 本插件（ESM 记录号 0x900+i）新建的**常驻 XMarker**，位置 = 任务板坐标：
//              常驻引用在 cell 未加载时依然存在 ⇒ 任何位置都取得到 ⇒ 首选引导目标。
//              运行期 FormID = (本插件加载序号 << 24) | markerLocal —— 前缀取
//              Guide 通道的 ch.prefix（SAQ_Guide.cpp 已认领的值）。
//   fallback1/2 ③ 同 cell 里离板最近的**原生常驻引用**（XMarker 系优先、≤25 m）——
//              位置差 1~20 m，作为「新建 marker 万一不被引擎接受」的兜底。
//   nameZh/En  列表里显示的名字（中英都推，AS3 按游戏语言挑）。
//
// 实机排查看 DLL 日志的「入口目标来源：marker N / 原板 N / 兜底 N / 不可用 N」与
// 「入口候选诊断：…」（SAQ.cpp::AppendEntryRows）。

#include <cstdint>

namespace SAQ
{
	struct StaticEntryInfo
	{
		std::uint32_t refLocal;
		std::uint8_t  master;
		bool          persistent;
		std::uint32_t markerLocal;   // ① 新建常驻 XMarker（0 = 没有）
		std::uint32_t fallback1;     // ③ 同 cell 原生常驻引用（0 = 没有）
		std::uint32_t fallback2;
		const char*   nameEn;
		const char*   nameZh;
	};

	inline constexpr StaticEntryInfo kEntryTable[] = {
		{ 0x0021001eu, 0u, false, 0x0000090au, 0x0002c14fu, 0x002bd876u, "Mission Board - New Atlantis", "任务板 · 新亚特兰蒂斯城" },
		{ 0x0014d497u, 0u, true , 0x00000000u, 0x0008c56du, 0x0013fa21u, "Mission Board - Akila City", "任务板 · 阿基拉城" },
		{ 0x00148c93u, 0u, false, 0x00000903u, 0x002bab78u, 0x0023ca79u, "Mission Board - Neon", "任务板 · 霓虹城" },
		{ 0x001df853u, 0u, false, 0x00000909u, 0x0029f410u, 0x0013d957u, "Mission Board - Cydonia", "任务板 · 赛多尼亚" },
		{ 0x001ded95u, 0u, false, 0x00000907u, 0x001fa55fu, 0x001eb56du, "Mission Board - Hopetown", "任务板 · 霍普镇" },
		{ 0x001df5bdu, 0u, false, 0x00000908u, 0x0021a870u, 0x0004a177u, "Mission Board - New Homestead", "任务板 · 新家园" },
		{ 0x00137573u, 0u, false, 0x00000901u, 0x0011b754u, 0x00110fb5u, "Mission Board - The Lodge", "任务板 · 陋室" },
		{ 0x0013f738u, 0u, false, 0x00000902u, 0x000c4078u, 0x000c406eu, "Mission Board - Ryujin Industries", "任务板 · 龙神集团" },
		{ 0x000c2d64u, 0u, false, 0x00000900u, 0x003de5a0u, 0x003de5a1u, "Mission Board - Deimos Staryards", "任务板 · 火卫二造船厂" },
		{ 0x0016265fu, 0u, false, 0x00000904u, 0x00205de2u, 0x0025a67au, "Mission Board - Trident Staryard", "任务板 · 海神叉造船厂" },
		{ 0x00167872u, 0u, false, 0x00000905u, 0x00001712u, 0x0011c577u, "Mission Board - Stroud-Eklund Staryards", "任务板 · 斯特劳艾克伦集团造船厂" },
		{ 0x00197d22u, 0u, false, 0x00000906u, 0x00315942u, 0x0022eef0u, "Mission Board - The Key", "任务板 · 星钥站" },
	};
	inline constexpr std::size_t kEntryTableSize = 12;
}
