#pragma once

// Windows.h 的 min/max 宏会和 std::min/std::max 打架（error C2589），
// 必须在任何 windows 头之前定义 NOMINMAX。
#ifndef NOMINMAX
#	define NOMINMAX
#endif

#include "SFSE/SFSE.h"

#include <cstdint>
#include <string>
#include <string_view>
#include <vector>
