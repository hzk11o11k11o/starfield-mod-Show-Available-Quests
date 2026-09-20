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

		// ★ 只读地问一次界面当前状态（AS3 `SAQ_Report` 的返回值，已经是日志转义后的字符串）。
		// 用途：菜单开着时轮询，把「切到我们 tab 之后列表到底有几条」这类事实写进日志。
		// 返回 false = 桥没通 / SWF 是旧版 / 菜单正在换代（调用方静默跳过即可，别刷屏）。
		bool ReadUiReport(std::string& a_report);

		// ★ 第 10 轮：读 AS3 一个无参函数的字符串返回值（原样，不做日志转义、无前缀）。
		// 用途：引导请求（`_root.SAQ_PeekGuide` → "<seq>|<questFormID>"）。
		// 返回 false = 桥没通 / SWF 旧版 / 返回值不是字符串。
		bool ReadUiString(const char* a_path, std::string& a_value);

		// ★ 第 16 轮：把「引导请求的处理结果」回写给 AS3（`_root.SAQ_GuideReply`）。
		// 协议 "<seq>|<实际引导任务FormID>|<结果码>"（见 MissionMenu.as 里的说明）。
		// 结果码：0=成功 / 1=没有引导目标 / 2=写通道失败 / 3=静态表里没有
		//        ★ 第 19 轮新增 4 = 未生效（脚本确认超时 / 别名不存在）——界面回滚。
		// 为什么要它：没有回写时，玩家点到「没有引导目标」的任务会看到界面说
		// 「已设为引导」而实际什么都没发生（旧引导可能还在），界面状态长期不一致。
		// 返回 true = 调用发出且 AS3 给了应答（a_reply = ok/same/stale/bad…）；
		// false = 桥没通 / 调用失败（a_reply 里是原因）。
		bool NotifyGuideReply(int a_seq, std::uint32_t a_actualFormID, int a_code, std::string& a_reply);

		// ★ 第 16 轮：菜单打开、列表推送成功后，把「当前实际引导任务」同步给 AS3
		// （`_root.SAQ_SyncGuideState`）。菜单每次打开都是新 SWF 实例、界面的
		// SaqGuideQuest 归 0——不同步会丢竖条、点「正在引导的那条」第一次会变成重设。
		// a_formID = 0 表示当前没有引导（界面保持 0 即可，调用方通常跳过这种同步）。
		bool SyncGuideState(std::uint32_t a_formID, std::string& a_reply);
	}
}
