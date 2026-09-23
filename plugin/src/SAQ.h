#pragma once

#include <filesystem>
#include <vector>

#include "SAQ_UI.h"   // QuestEntry（★ 第 133 轮：注入层与 harness 取同一份数据）

namespace SAQ
{
	// 安装插件（挂 UI 事件 sink 等）。可重复调用，只生效一次。
	bool Install();

	// ★ 第 22 轮：本插件（DLL）所在目录 —— MO2 下就是 mod 目录。
	//   日志与配置 ini 都写在这里（玩家要求：删 mod 时不要残留文件到 C 盘用户目录）。
	//   拿不到时返回空 path（调用方自行回退）。
	std::filesystem::path PluginDir();

	// ★★★ 第 133 轮（P3 产品化 PoC · docs/15 11.7）：「待推送」的可接任务列表 ——
	//   与 TryPushPending 推给 SWF 的是**同一份数据**（同一套运行期过滤 / 门槛 / 排序）。
	//   注入形态（SAQ::UiInject）与 harness 的 `ui.inject` 原语从这里取数据：
	//   「注入 = 推送的另一条通道」，不是第二份数据源。
	//   空 = 菜单还没打开（OnMissionMenuOpened 里收集）或这次没有任何可接任务。
	const std::vector<QuestEntry>& PendingQuests();

	// ★★★ 第 140 轮（P4 交互接管 · docs/15）：注入形态的引导请求入口。
	//
	// 背景：注入形态（不替换 missionmenu.swf）下没有 AS3 协议侧 —— `SAQ_PeekGuide` /
	// `SAQ_GuideReply` 那两个入口只存在于**我们的** SWF 里。玩家在界面上按 X（设定航线）/
	// Y（显示在地图上）/ 选中子项按 Enter（切换引导）时，由接管层（SAQ_UiInject）
	// 直接调这里，**复用同一条产品引导路径**（候选池挑选 / ESM 通道 / 结果确认 /
	// 星图待办 / 接取后自动取消）。
	//
	// a_formID = 任务 FormID（0 = 取消引导）；a_wantMap = 是否请求打开星图（只有 X 键传 true）；
	// a_toggleCancel = 是否允许「同一条再按一次 = 取消」（只有 Enter 子项传 true）。
	// 返回结果码（与 SWF 协议同源）：0=成功 / 1=没有引导目标 / 2=写通道失败 /
	//   3=静态表里没有 / 5=目标尚未加载（保持待生效，界面不该关菜单）。
	int RequestGuideFromInject(std::uint32_t a_formID, bool a_wantMap, bool a_toggleCancel);

	// 当前正在引导的任务 FormID（0 = 无）。注入形态的「引导态竖条」（条目 bActive）
	// 以它为准 —— 与 SWF 版 `SAQ_SyncGuideState` 同一份状态源。
	std::uint32_t CurrentGuideQuestID();
}
