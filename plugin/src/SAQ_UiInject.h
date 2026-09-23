#pragma once

// ============================================================================
//  SAQ_UiInject —— 「无 SWF 覆盖」的 UI 注入形态（P3 产品化 PoC · docs/15 11.7）
//
//  目标形态：**不替换** `Data\Interface\missionmenu.swf`，直接用 GFx API 在原版
//  任务菜单上「扩一个 tab + 分时注入我们的条目」。全部技术未知点已被探针证完
//  （P1.5 `ui.research2` / P2 `ui.research3` / 探针 v4 `ui.research4`，见 docs/15
//  九·补 ~ 十二）：本模块把它们拼成一条完整产品链路：
//
//    ① **扩 tab**：`SetTabsData(8 项)` —— 前 7 项 = 原版 [text,flag] 原样（含
//       `$ALL` 的原版掩码；不像 SWF 版那样改 0xFFFFFFBF —— 因为切走即恢复，
//       「全部」里不会出现我们的条目）；第 8 项 = 我们的 tab（flag = 1<<6）。
//    ② **分时注入**：priority=100 拦 `selectionChange` ——
//         切到我们 tab ⇒ `stopImmediatePropagation`（原版 `FilterInfoA[7]` 越界
//           TypeError，必须拦）+ 设 `filterMask=1<<6` + `InitializeEntries(我们的条目)`；
//         从我们 tab 切走 ⇒ 先 `InitializeEntries(引擎快照)` 再**放行**原版
//           （原版 `onFilterChanged` 只设 mask、不重建列表 —— 所以必须自己恢复，
//            否则引擎条目在「列表里没有」的状态下被 mask 过滤掉 ⇒ 空列表）。
//    ③ **验收**：`entryCount == 期望`、`GetDataForEntry` 逐项对账（uID / 名字 /
//       置灰）、切走后 `entryCount` 回到引擎数。
//
//  ★ 引擎快照：注入前逐条 `GetDataForEntry(i)`（**引用**同一批条目对象）组成数组；
//    恢复 = `InitializeEntries(快照)` ⇒ 原版数据、展开态、图标字段全不丢。
//
//  ★ 隔离纪律（玩家要求「随时可返回 SWF 版本」，第 132 轮）：
//    · 与 SAQ_UI 的 SWF 通道**完全互不影响**：本模块不碰任何我们 SWF 里的入口；
//      解析层（找菜单）复用 `UI::EnsureResolved` / `UI::ResolvedAsMovieRoot()`；
//    · 只在 harness（SAQ_WITH_HARNESS）里编译 ⇒ 发布构建零残留；
//    · 全部副作用发生在「菜单打开期间」，随菜单关闭自然清理（第 27/50 轮定案）。
// ============================================================================

#include <string>
#include <vector>

#include "SAQ_UI.h"   // QuestEntry（与 SWF 通道同一份数据类型）

namespace SAQ::UiInject
{
#if SAQ_WITH_HARNESS
	// P3-a PoC（harness 原语 `ui.inject` 驱动）：把 a_quests（= 产品侧「待推送」
	// 同一份可接任务数据，见 SAQ::PendingQuests()）注入原版 MissionMenu，走完整
	// 链路并返回一行汇总（调用方打产品日志 —— 红线六）。
	//
	// 链路：环境读 → 语言判定 → 引擎快照 → 扩 tab（7→8）→ 切 7（拦截+注入）→
	//       对账读回 → 切 0（恢复）→ 对账读回 → 再切 7（注入 —— 供「眼睛窗口」
	//       玩家亲眼看到真实数据）→ 汇总。
	//
	// 副作用（菜单关闭后随 Movie 销毁，不还原 —— 第 27/50 轮定案）：
	//   tab 数组被替换为 8 项（末项 = 我们的 tab）、列表被替换为我们的条目、
	//   selectionChange 上留一个 priority=100 监听（**故意保留**：眼睛窗口里玩家
	//   切 tab 要靠它 —— 没有它切到第 8 个 tab 会触发原版越界 TypeError）。
	std::string RunInjectPoC(const std::vector<QuestEntry>& a_quests);
#endif
}
