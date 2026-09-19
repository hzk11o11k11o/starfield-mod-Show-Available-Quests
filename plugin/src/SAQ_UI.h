#pragma once

// ============================================================================
//  SAQ_UI —— C++ 侧访问 BSMissionMenu 的 SWF（GFx）通道
//
//  为什么单独一层：commonlibsf 的 UI / IMenu / 菜单表**偏移在 1.16.244.0 上是过时的**
//  （实测：UI::menuMap 标 0x470，真实的菜单表在 UI+0x450）。所以这里不直接用
//  UI::GetMenuMovie()，而是自己按「反汇编出来的算法」查表，并且每一步都用
//  RTTI 名字 / 虚函数调用做校验，校验不过就换候选偏移 —— 猜错最坏是「推送失败」，
//  而不是把游戏带崩。
//
//  实测结论、算法与偏移来源见 SAQ_UI.cpp 顶部注释与 docs/02-UI通道逆向.md。
// ============================================================================

#include <cstdint>
#include <string>
#include <string_view>
#include <vector>

namespace SAQ
{
	// 一条「可接任务」记录。
	// 名字带中英两份：**语言判定放在 AS3 侧**（它能直接看到引擎推来的本地化任务名，
	// 比 C++ 去读 INI 可靠 —— 实测本机 INI 里根本没有 sLanguage）。
	struct QuestEntry
	{
		std::uint32_t formID{};   // FormID（Starfield.esm 的 master 区段）
		std::int32_t  type{};     // AS3：QuestUtils.AVAILABLE_QUEST_TYPE = 6
		std::string   nameZh;     // 中文显示名（UTF-8）
		std::string   nameEn;     // 英文显示名（UTF-8）
	};

	namespace UI
	{
		// 清掉解析缓存。★ 每次菜单「由关变开」都必须调：菜单一关，SWF 的 Movie
		// 对象通常会被销毁，缓存下来的指针就是野指针。
		void Reset();

		// 解析「UI → 菜单表 → IMenu → Movie → ASMovieRoot」这条链（结果在本次菜单打开期间缓存）。
		// 失败时 a_detail 写明卡在哪一步（直接进日志）。
		bool EnsureResolved(std::string& a_detail);

		// 把可接任务推给 AS3（MissionMenu.SetAvailableQuests，单个字符串参数，见 .cpp 里的协议）。
		// 标题与任务名都是「中英双语」一起推，由 AS3 侧按游戏语言挑。
		// 返回 true = GFx 侧调用成功（返回值写在 a_detail 里）。
		bool PushAvailableQuests(const std::vector<QuestEntry>& a_quests, std::string& a_detail);
	}
}
