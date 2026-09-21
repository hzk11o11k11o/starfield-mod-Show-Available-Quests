#pragma once

// ============================================================================
//  MiniTest —— 极简测试框架（第 64 轮 · 大项 K）
//
//  为什么自写而不是引第三方（doctest/Catch2）：本项目的工具链一直是「零依赖」
//  风格（用例 DSL / 结果 JSON / 报告器都是自写）；这里需要的只是
//  「注册用例 + 断言 + 计数 + 退出码」，60 行就够，还能完全掌控输出格式。
//
//  用法：
//      MT_TEST(名字) { ... MT_CHECK(cond); MT_CHECK_EQ(a, b); ... }
//      int main() { return MiniTest::RunAll("套件名"); }
//
//  断言失败会打 `[FAIL] 文件:行 说明`，进程退出码 0 = 全过、1 = 有失败
//  （xmake test / CI 都按退出码判定）。
// ============================================================================

#include <cstdio>
#include <cstdint>
#include <exception>
#include <functional>
#include <string>
#include <type_traits>
#include <vector>

#include <format>

namespace MiniTest
{
	struct Case
	{
		const char* name;
		void (*fn)();
	};

	inline std::vector<Case>& Registry()
	{
		static std::vector<Case> r;
		return r;
	}

	inline int& FailCount()
	{
		static int n = 0;
		return n;
	}

	inline int& CheckCount()
	{
		static int n = 0;
		return n;
	}

	inline void ReportFailure(const char* a_file, int a_line, const std::string& a_msg)
	{
		++FailCount();
		std::printf("       [FAIL] %s:%d  %s\n", a_file, a_line, a_msg.c_str());
	}

	// 值 → 字符串（枚举按整数打印；其它能 format 的按 format）
	template <typename T>
	std::string ToStr(const T& a_v)
	{
		if constexpr (std::is_enum_v<T>) {
			return std::format("{}", static_cast<long long>(a_v));
		} else if constexpr (std::is_same_v<T, bool>) {
			return a_v ? "true" : "false";
		} else if constexpr (std::is_arithmetic_v<T>) {
			return std::format("{}", a_v);
		} else if constexpr (requires { std::format("{}", a_v); }) {
			return std::format("{}", a_v);
		} else {
			return "<值>";
		}
	}

	template <typename T1, typename T2>
	void ReportEqFailure(const char* a_file, int a_line, const char* a_ea, const char* a_eb,
		const T1& a_va, const T2& a_vb)
	{
		ReportFailure(a_file, a_line,
			std::string("期望相等于 [") + a_ea + " == " + a_eb + "]；实际 " +
				ToStr(a_va) + " vs " + ToStr(a_vb));
	}

	inline int RunAll(const char* a_suite)
	{
		std::printf("=== %s：%zu 个用例 ===\n", a_suite, Registry().size());
		int failedCases = 0;
		for (const auto& c : Registry()) {
			const int before = FailCount();
			std::printf("[ RUN  ] %s\n", c.name);
			try {
				c.fn();
			} catch (const std::exception& e) {
				ReportFailure(__FILE__, 0, std::string("抛异常：") + e.what());
			} catch (...) {
				ReportFailure(__FILE__, 0, "抛未知异常");
			}
			if (FailCount() > before) {
				++failedCases;
				std::printf("[ FAIL ] %s\n", c.name);
			} else {
				std::printf("[  OK  ] %s\n", c.name);
			}
		}
		std::printf("=== 结果：%zu 个用例，%d 个失败；共 %d 条断言 ===\n",
			Registry().size(), failedCases, CheckCount());
		return failedCases == 0 ? 0 : 1;
	}
}

// ---------------------------------------------------------------------------

#define MT_TEST(name)                                                     \
	static void mt_case_##name();                                        \
	namespace                                                             \
	{                                                                     \
		const bool mt_reg_##name = [] {                                   \
			::MiniTest::Registry().push_back({ #name, mt_case_##name });   \
			return true;                                                  \
		}();                                                              \
	}                                                                     \
	static void mt_case_##name()

#define MT_CHECK(cond)                                                          \
	do {                                                                        \
		++::MiniTest::CheckCount();                                             \
		if (!(cond)) {                                                          \
			::MiniTest::ReportFailure(__FILE__, __LINE__, "断言失败：" #cond);    \
		}                                                                       \
	} while (0)

#define MT_CHECK_EQ(a, b)                                                       \
	do {                                                                        \
		++::MiniTest::CheckCount();                                             \
		const auto& _va = (a);                                                  \
		const auto& _vb = (b);                                                  \
		if (!(_va == _vb)) {                                                    \
			::MiniTest::ReportEqFailure(__FILE__, __LINE__, #a, #b, _va, _vb);  \
		}                                                                       \
	} while (0)
