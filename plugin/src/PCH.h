#pragma once

// Windows.h 的 min/max 宏会和 std::min/std::max 打架（error C2589），
// 必须在任何 windows 头之前定义 NOMINMAX。
#ifndef NOMINMAX
#	define NOMINMAX
#endif

#include "SFSE/SFSE.h"

// ★ 第 53 轮（大项 F · 发布就绪）：引擎内 harness 的编译开关。
//   由 plugin\xmake.lua 的 `saq_harness` option 提供（默认开；发布构建 = 0）。
//   这里兜底定义：万一用别的构建方式（没带 -D）也不会把它当语法错误。
#ifndef SAQ_WITH_HARNESS
#	define SAQ_WITH_HARNESS 0
#endif

#include <cstdint>
#include <string>
#include <string_view>
#include <vector>
