#pragma once

#include <filesystem>

namespace SAQ
{
	// 安装插件（挂 UI 事件 sink 等）。可重复调用，只生效一次。
	bool Install();

	// ★ 第 22 轮：本插件（DLL）所在目录 —— MO2 下就是 mod 目录。
	//   日志与配置 ini 都写在这里（玩家要求：删 mod 时不要残留文件到 C 盘用户目录）。
	//   拿不到时返回空 path（调用方自行回退）。
	std::filesystem::path PluginDir();
}
