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
}
