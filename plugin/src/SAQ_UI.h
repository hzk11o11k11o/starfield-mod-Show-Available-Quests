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
		std::uint32_t formID{};   // FormID（运行期值：master 前缀 | 记录号）
		// 任务类型（原版 QuestUtils 枚举：0=Activities 1=Main 2=Factions 3=Misc 4=Mission）。
		// ★ 第 65 轮（任务专属图标）：此前统一推 6（AVAILABLE_QUEST_TYPE）⇒ 界面里
		//   所有条目的图标都是「任务」那一个；现在推**真实类型**，界面才能像原版一样
		//   区分活动 / 杂项 / 任务 / 势力（势力图标由下面的 faction 决定）。
		// ★ 任务板入口仍用 100（kEntryQuestType，非原版枚举）——界面识别它换文案，
		//   并在显示层折叠回「任务」图标。
		std::int32_t  type{};
		// ★ 第 65 轮（任务专属图标）：原版 UI 的阵营枚举（= SWF 里 FactionUtils 的顺序，
		//   -1 = 无阵营）——由 QUST 的 FTYP 关键字离线映射（gen_faction_types.py）。
		//   界面把它原样传给原版 MissionsListEntry.SetFactionIcon(iFaction, iType)，
		//   图标即与原版任务菜单完全一致（势力徽记 / 活动 / 杂项 / 任务）。
		//   详情面板（MissionInfo）也会用它显示阵营名与彩色图标。
		std::int32_t  faction{-1};
		// ★ 第 23 轮：这条任务有没有「引导目标」（静态表的 candCount > 0，第 45 轮起为候选池）。
		//   界面据此把「能不能导航」变成看得见的信息：无目标的条目点击时不发请求
		//   （避免「亮起→瞬间回滚」的闪烁）、描述里写明原因、SET COURSE 按钮置灰。
		bool          hasGuideTarget{};
		// ★★ 第 46 轮（大项 B）：这条任务的**精确目标（首选候选）是非常驻引用** —— 也就是
		//   「玩家在远处一定取不到，必须靠近目标所在区域（其 cell 加载）才能拿到精确目标」。
		//   界面据此在描述里**提前**告知玩家（「靠近后才可用」），而不是让玩家点了半天
		//   看不出反应（实测：「营救机器人」远处点 R ⇒ 脚本连报 5 次取不到、19 秒后引导
		//   被静默放弃）。
		//   ★★ 第 47 轮（大项 C）：判据从「全部候选都非常驻」改为「**首选**候选非常驻」 ——
		//   第 47 轮给这一类任务补了「同 cell 常驻兜底」候选（常驻 ⇒ 任何位置都取得到）：
		//   远处点引导会落到兜底（蓝点落在目标附近），靠近后自动升级回精确目标；
		//   但「精确目标要靠近才加载」这一事实不变 ⇒ 描述提示与测试模式 6 清单照旧。
		//   判据 = 静态表候选池**第 0 个**候选的 flags bit0（persistent）为 0 ——
		//   本机数据：209 条有目标的任务里 76 条属于这一类（见 docs/05 第二十/二十一节）。
		//   入口条目（任务板）不受影响：它们的候选链里有新建的常驻 marker。
		bool          needsApproach{};
		// ★★ 第 74 轮（同伴好感度任务）：这条是**固定显示**的「入口」同伴任务
		//   （个人任务 —— 由好感度里程碑直接启动的那一环，静态表的 companionPin）。
		//   界面据此在描述里提示「需要与同伴的好感度达到一定水平后才能接取」
		//   （载荷第 8 列）—— 任务名前缀（同伴名）已经在静态表的名字里。
		bool          companionPinned{};
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

#if SAQ_WITH_HARNESS
		// ★★ 第 49 轮（引擎内 harness）：调 AS3 的测试驱动入口（`_root.<a_fn>`，
		// 单字符串参数、返回字符串）—— 用来代替人做「选中条目 / 按键 / 展开子项」。
		// 入口名见 MissionMenu.as：SAQ_TestDriveSelect / SAQ_TestDriveKey / SAQ_TestDriveExpand。
		// 返回 false = 桥没通 / SWF 是旧版（没有这些入口）；true 时 a_reply = AS3 的短状态串。
		// ★ 第 53 轮（大项 F）：只在开发构建（SAQ_WITH_HARNESS=1）里存在 ——
		//   调用方只有 harness 原语层（SAQ_TestOps.cpp），发布构建不含它们。
		bool InvokeUiTestDrive(const char* a_fn, const std::string& a_arg, std::string& a_reply);
#endif
	}
}
