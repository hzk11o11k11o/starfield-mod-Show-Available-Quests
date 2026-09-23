#pragma once

// ============================================================================
//  SAQ_UiInject —— 「无 SWF 覆盖」的 UI 注入形态（P3 产品化；docs/15 十一~十三）
//
//  目标形态：**不替换** `Data\Interface\missionmenu.swf`，直接用 GFx API 在原版
//  任务菜单上「扩一个 tab + 分时注入我们的条目」。全部技术未知点已被探针证完
//  （P1.5 / P2 / 探针 v4 / P3-a，见 docs/15 九·补 ~ 十三）。
//
//  ★★ 第 137 轮（P3-b）：**分层**（此前整体在 harness 内）——
//    · **产品路径**（发布构建也编译）：`OnMenuTick`（激活尝试 + watchdog）/
//      `OnMenuClosed` / `SetMode`；完整描述文案（SWF 版 `SaqDescriptionText`
//      逐字迁移，含 KeyHelper 按键名）。
//    · **harness 段**（`SAQ_WITH_HARNESS`）：`RunInjectPoC`（`ui.inject` 原语 ——
//      P3-a 判据链路；输出格式与第 133~135 轮逐字一致，verify / P2 计划依赖它）。
//
//  形态开关（ini `[UI] UiMode`，SAQ.cpp 读取后 `SetMode`；改 ini 关开菜单生效）：
//    · `swf`    = 行为与现状逐字节不变（注入代码不激活）；
//    · `auto`（默认）= SWF 通道可用 ⇒ 走 SWF；判定 notOurs（原版 / 第三方 SWF）
//      ⇒ 自动切注入；
//    · `inject` = 只用注入（菜单打开后不推送，直接激活）。
//
//  链路（激活，与 P3-a 逐项同源）：
//    ① 读 `_root.Menu_mc` → `TabbedFilterSelection_mc` / `MissionsList_mc`；
//    ② 语言判定（引擎条目名 CJK）+ 取按键名（`KeyHelper.GetButtonNameForEvent`）；
//    ③ 记原 tab → 切 0（`$ALL`，全量快照的前提）→ 引擎快照（逐条 `GetDataForEntry`
//       的**引用**）→ 切回原 tab（挂监听前，走原版路径）；
//    ④ 构造我们的条目（真实数据 + 完整描述）→ `SetTabsData`（7→8）→
//       priority=100 拦 `selectionChange`（切到我们 tab：`stopImmediatePropagation`
//       + `filterMask=1<<6` + `InitializeEntries(我们的条目)`；切走：先恢复快照）；
//    ⑤ watchdog（`OnMenuTick`，500ms 节拍）：在 我们的 tab 上检查列表是否仍是我们
//       的（entryCount + 首条 uID）—— 被引擎刷新覆盖 ⇒ 重放注入（日志节流）。
//
//  ★ 隔离纪律（玩家要求「随时可返回 SWF 版本」，第 132 轮）：
//    · 与 SAQ_UI 的 SWF 通道互不影响：本模块不碰任何我们 SWF 里的入口；
//      解析层（找菜单）复用 `UI::EnsureResolved` / `UI::ResolvedAsMovieRoot()`；
//    · SWF 覆盖文件与构建链不删不动（两形态并存）；
//    · 副作用只在「菜单打开期间」（随菜单关闭自然清理；`OnMenuClosed` 清引用）。
// ============================================================================

#include <cstdint>
#include <string>
#include <vector>

#include "SAQ_UI.h"   // QuestEntry（与 SWF 通道同一份数据类型）

namespace SAQ::UiInject
{
	// 运行期形态（ini [UI] UiMode）。默认 auto。
	enum class UiMode
	{
		kSwf,     // 只用 SWF 推送（注入完全不激活 —— 行为与既有版本逐字节一致）
		kAuto,    // 先按 SWF 推送；判定「界面不是我们的」⇒ 自动切注入
		kInject,  // 只用注入（菜单打开后不推送）
	};

	void        SetMode(UiMode a_mode);
	UiMode      GetMode();
	const char* ModeName(UiMode a_mode);   // "swf" / "auto" / "inject"（日志用）

	// 本次菜单是否已激活注入形态（诊断 / HUD 提示条件）。
	bool MenuActive();

	// watchdog 重放次数（引擎刷新覆盖我们的列表后重放注入 —— 诊断用）。
	std::uint32_t ReplayCount();

	// ★★★ 第 140 轮（P4 交互接管）：接管层计数（诊断 / 断言用）。
	//
	// 接管层 = 把原版界面的三处交互换成我们的实现（都是「我们的条目走我们的路 /
	// 原版条目原样委托回原版」）：
	//   · X（SET COURSE，`PlotToLocationButton_mc`）——我们的条目 ⇒ 引导 + 星图交接；
	//   · Y（SHOW ON MAP，`ShowOnMapButton_mc`）——我们的条目 ⇒ 只为它设引导（不开星图）；
	//   · 条目激活（`MissionsList::itemActivated`，Enter / 鼠标点击）——我们的子项 ⇒
	//     切换引导（再按一次 = 取消）；我们的主条目 ⇒ 拦下（展开由原版树逻辑完成）。
	// 原版条目一律**委托**：按原版 AS3 源码逐行复刻它的 dispatch（见 .cpp）。
	struct TakeoverCounts
	{
		std::uint32_t keyX{};      // X 回调收到次数
		std::uint32_t keyY{};      // Y 回调收到次数
		std::uint32_t activate{};  // 条目激活回调收到次数
		std::uint32_t ours{};      // 命中「我们的条目」次数（决策侧）
		std::uint32_t delegated{}; // 委托回原版路径次数
		std::uint32_t blocked{};   // 拦下（stopPropagation）次数
		std::uint32_t guideReq{};  // 真下发到引导通道的请求数
		std::uint32_t acted{};     // 真动作数（dry-run 时为 0 —— 见 harness 探针）
	};
	TakeoverCounts GetTakeoverCounts();

	// 接管层是否已装（本菜单；诊断 / 断言用）。
	bool TakeoverActive();

	// Tick 的「任务菜单开着」分支每拍调用（★ 第 137 轮）：
	//   · 未激活 + 形态需要注入 ⇒ 节流尝试激活（150 ms；菜单可能还没建好）；
	//   · 已激活 ⇒ watchdog（500 ms 节拍：列表被引擎刷新覆盖 ⇒ 重放）。
	// a_uiChannelDead = SAQ.cpp 的 notOurs 判定（auto 模式的切换依据）。
	// 未激活且形态不需要注入时 = 一次枚举比较（零开销）。
	void OnMenuTick(bool a_uiChannelDead);

	// 菜单关闭时调用：清上下文（GFx 引用在 Movie 销毁后失效）。
	void OnMenuClosed();

#if SAQ_WITH_HARNESS
	// ★★★ 第 138 轮（P2 会话收口）：运行期强制形态（harness `ui.mode` op）——
	//   ini 的 [UI] UiMode 只在菜单打开时读一次；P2 计划里各用例需要互不干扰的形态
	//   （探针 research3 / ui.inject 跑 `swf` 干净环境；产品路径用例跑 `auto`）——
	//   强制值优先于 ini 解析（菜单打开时的 SetMode 被忽略），`ClearForceMode` 恢复。
	void ForceMode(UiMode a_mode);
	void ClearForceMode();

	// P3-a PoC（harness 原语 `ui.inject` 驱动）：把 a_quests（= 产品侧「待推送」
	// 同一份可接任务数据，见 SAQ::PendingQuests()）注入原版 MissionMenu，走完整
	// 链路并返回一行汇总（调用方打产品日志 —— 红线六）。
	//
	// 链路：环境读 → 语言判定 → 引擎快照 → 扩 tab（7→8）→ 切 7（拦截+注入）→
	//       对账读回 → 切 0（恢复）→ 对账读回 → 再切 7（注入可重入复核）→ 汇总。
	//
	// 副作用（菜单关闭后随 Movie 销毁，不还原 —— 第 27/50 轮定案）：
	//   tab 数组被替换为 8 项（末项 = 我们的 tab）、列表被替换为我们的条目、
	//   selectionChange 上留一个 priority=100 监听（**故意保留**：切到第 8 个 tab
	//   要靠它 —— 没有它切到第 8 个 tab 会触发原版越界 TypeError）。
	std::string RunInjectPoC(const std::vector<QuestEntry>& a_quests);

	// ★★★ 第 140 轮（P4 交互接管）：`ui.interact` —— 接管层的判据链（**原版 SWF** 上跑）。
	//
	// 前置：注入上下文已建立（先跑 `ui.inject`，或等产品路径 UiMode=auto 自动激活）。
	// 链路（一行汇总，红线六）：
	//   R1 上下文（注入已激活）→ R2 装接管（劫持 X/Y + 挂 itemActivated 监听；幂等）
	//   → R3 分类判据（只读：我们的条目 / 引擎条目 / 无选中 —— 用真实对象走真分类函数）
	//   → R4 我们的条目上 dry 触发 X / Y（`HandleUserEvent` 走真实按键路径；dry ⇒ 不动作）
	//   → R5 激活拦截（派发 `MissionsList::itemActivated`；dry ⇒ 不动作，但照常
	//      stopPropagation —— 证明原版处理器被挡住）。
	//   ★ dry-run = 「只验证接管接线与分类，不产生任何副作用」；真按键用
	//     `ui.interact key X`（会真的下发引导 + 关菜单）。
	std::string RunInteractProbe();

	// `ui.interact key X|Y` —— 真按键路径（不复刻逻辑：走我们装在按钮上的真实回调）。
	// 选中我们的第一条**有导航目标**的条目 → 触发 → 引导下发（结果码进日志）+
	// 结果码 0 且要星图 ⇒ 原版「回游戏」原语关掉整个暂停菜单（星图交接）。
	std::string RunInteractKey(const char* a_key);

	// `ui.interact state` —— 只读状态行（任务菜单 / 星图 / 当前引导 / 注入是否激活）。
	// 用途：真按键之后断言「星图已由脚本打开」（星图交接的端到端判据）。
	std::string RunInteractState();
#endif
}
