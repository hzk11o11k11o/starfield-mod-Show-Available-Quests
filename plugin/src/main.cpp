#include "PCH.h"

#include "SAQ.h"

// ★ 第 112 轮：读 ini（GetPrivateProfileStringW）—— 与 SAQ.cpp 同一套 Profile API。
//   （PCH.h 已定义 NOMINMAX，Windows.h 的 min/max 宏不会和 std::min/std::max 打架。）
#include <Windows.h>

#include <atomic>
#include <cstddef>
#include <cstdlib>
#include <exception>
#include <filesystem>
#include <memory>
#include <string>

#include <spdlog/details/file_helper.h>
#include <spdlog/sinks/base_sink.h>
#include <spdlog/sinks/msvc_sink.h>
#include <spdlog/spdlog.h>

// 注意：SFSE_PLUGIN_VERSION 由 commonlibsf.plugin 规则生成的 commonlibsf-plugin.cpp
// 提供（配置见 plugin/xmake.lua 的 add_rules 参数），这里不要再定义一份，
// 否则会报 LNK2005 重复定义。

namespace
{
	std::atomic_bool g_installed{ false };

	// SFSE 日志名（对应 SFSE\Logs\<name>.log）
	constexpr const char* kLogName = "SAQ_ShowAvailableQuests";

	// 日志文件上限：写新一行时若会超过就把旧内容整体清空（不是滚动保留旧文件）。
	//
	// ★ 第 112 轮（玩家需求）：做成**可配置** —— ini `[Log] MaxSizeMB`（单位 **MB**）。
	//   · 不填 = 按构建类型默认：**发布构建（Nexus 包）1 MB / 开发构建 10 MB**
	//     （开发跑 harness 时 1 MB 很快把证据滚掉 —— 第 108 轮日志 948 KB 已贴近上限）；
	//   · 填 N = 用 N MB（范围 1~1024；越界/非数字 ⇒ 日志 WARN + 按默认处理）。
	constexpr int kDefaultLogMaxMB =
#if SAQ_WITH_HARNESS
		10;
#else
		1;
#endif
	constexpr int kMinLogMaxMB = 1;     // 再小装不下一轮 harness 会话，没有意义
	constexpr int kMaxLogMaxMB = 1024;  // 兜底上限（防 ini 被填疯值把盘写满）

	// 从 ini 解析日志上限（拿不到插件目录 / 没填 / 填了非法值 ⇒ 用编译期默认）。
	// `aFromIni` = 值确实来自 ini —— 启动日志里说清来源，排查时一眼看出「改没改到」。
	int ResolveLogMaxMB(bool& aFromIni)
	{
		aFromIni = false;
		std::wstring iniPath;
		if (const auto dir = SAQ::PluginDir(); !dir.empty()) {
			iniPath = (dir / L"SAQ_ShowAvailableQuests.ini").wstring();
		}
		if (iniPath.empty()) {
			return kDefaultLogMaxMB;
		}
		// 用字符串读：要区分「没填键」（静默用默认，正常情形）与「填了非法值」（WARN）。
		wchar_t buf[32]{};
		if (::GetPrivateProfileStringW(L"Log", L"MaxSizeMB", L"", buf, 32, iniPath.c_str()) == 0 ||
			buf[0] == L'\0') {
			return kDefaultLogMaxMB;
		}
		wchar_t*   end = nullptr;
		const long v   = std::wcstol(buf, &end, 10);
		const bool valid = end && end != buf && *end == L'\0' &&
						   v >= kMinLogMaxMB && v <= kMaxLogMaxMB;
		if (!valid) {
			REX::WARN("日志上限：ini [Log] MaxSizeMB 的值不合法（应为 {}~{} 的整数）——"
					  "按默认 {} MB 处理｜ini：SAQ_ShowAvailableQuests.ini",
				kMinLogMaxMB, kMaxLogMaxMB, kDefaultLogMaxMB);
			return kDefaultLogMaxMB;
		}
		aFromIni = true;
		return static_cast<int>(v);
	}

	// 「单文件封顶」文件 sink（commonlibsf 默认的 basic_file_sink 会无限追加）。
	class SizeLimitedFileSink final : public spdlog::sinks::base_sink<std::mutex>
	{
	public:
		SizeLimitedFileSink(const std::filesystem::path& a_path, std::size_t a_maxBytes) :
			_maxBytes(a_maxBytes)
		{
#ifdef SPDLOG_WCHAR_FILENAMES
			_file.open(a_path.wstring(), false);  // 追加打开：保留上次运行的内容
#else
			_file.open(a_path.string(), false);
#endif
			_bytesWritten = _file.size();
		}

	protected:
		void sink_it_(const spdlog::details::log_msg& a_msg) override
		{
			spdlog::memory_buf_t formatted;
			formatter_->format(a_msg, formatted);

			if (_bytesWritten + formatted.size() > _maxBytes) {
				_file.reopen(true);
				_bytesWritten = 0;
			}

			_file.write(formatted);
			_bytesWritten += formatted.size();
		}

		void flush_() override
		{
			_file.flush();
		}

	private:
		spdlog::details::file_helper _file;
		std::size_t                   _maxBytes;
		std::size_t                   _bytesWritten{};
	};

	// 把 commonlibsf 建的默认 logger 换成「限长文件 sink」版。
	// 必须在 SFSE::Init 之后调用（logger 到那时才存在）。
	//
	// ★ 第 22 轮（玩家需求）：日志**写在插件自己的目录**（MO2 下 = mod 目录，
	//   即 SFSE\Plugins\ 旁边），不再写 C 盘用户目录 —— 删 mod 时日志一起删掉，
	//   不留残留。插件目录建不出文件时回退到 SFSE 默认日志目录（保证有日志可查）。
	void ApplyLogSizeLimit()
	{
		auto* logger = spdlog::default_logger_raw();
		if (!logger) {
			return;
		}

		// ★ 第 112 轮：上限来自 ini（可配）—— 先解析好，下面三条建日志路径共用。
		bool             fromIni  = false;
		const int        mb       = ResolveLogMaxMB(fromIni);
		const std::size_t maxBytes = static_cast<std::size_t>(mb) * 1024 * 1024;

		std::filesystem::path fileName{ kLogName };
		fileName += ".log";

		std::shared_ptr<spdlog::sinks::sink> fileSink;
		if (const auto dir = SAQ::PluginDir(); !dir.empty()) {
			try {
				fileSink = std::make_shared<SizeLimitedFileSink>(dir / fileName, maxBytes);
			} catch (const std::exception& e) {
				REX::WARN("插件目录里建日志失败（{}）—— 回退到默认日志目录", e.what());
			}
		}
		if (!fileSink) {
			if (const auto dir = SFSE::log::log_directory()) {
				try {
					fileSink = std::make_shared<SizeLimitedFileSink>(*dir / fileName, maxBytes);
				} catch (const std::exception&) {
				}
			}
		}
		if (!fileSink) {
			REX::WARN("日志文件建不出来（继续用 MSVC 调试输出；不影响任何功能）");
			return;
		}

		// clear() 会析构 commonlibsf 打开的文件 sink（关掉旧句柄）——
		// 否则新旧两个句柄同时写同一文件会互相打架。
		logger->sinks().clear();
		logger->sinks().push_back(std::make_shared<spdlog::sinks::msvc_sink_mt>());
		logger->sinks().push_back(fileSink);

		spdlog::set_pattern("[%T.%e] [%=5t] [%L] %v");
#if SAQ_WITH_HARNESS
		const char* limitSource =
			fromIni ? "来自 ini [Log] MaxSizeMB" : "开发构建默认；ini [Log] MaxSizeMB 可改";
#else
		const char* limitSource =
			fromIni ? "来自 ini [Log] MaxSizeMB" : "发布构建默认；ini [Log] MaxSizeMB 可改";
#endif
		REX::INFO("日志文件：插件目录（mod 目录）内的 {}｜上限 {} MB（{}）",
			fileName.string(), mb, limitSource);
	}

	// 插件加载时可能过早（SFSE 的任务系统还没起来），所以在
	// PostPostLoad / PostDataLoad 消息里再兜底试一次。
	void TryInstall()
	{
		if (g_installed.load()) {
			return;
		}
		if (SAQ::Install()) {
			g_installed.store(true);
		}
	}

	void OnMessage(SFSE::MessagingInterface::Message* a_msg)
	{
		if (!a_msg) {
			return;
		}
		switch (a_msg->type) {
		case SFSE::MessagingInterface::kPostPostLoad:
			TryInstall();
			break;
		case SFSE::MessagingInterface::kPostDataLoad:
			TryInstall();
			break;
		default:
			break;
		}
	}
}

SFSE_PLUGIN_LOAD(const SFSE::LoadInterface* a_sfse)
{
	SFSE::Init(a_sfse, { .logName = kLogName });
	ApplyLogSizeLimit();

	REX::INFO("SAQ_ShowAvailableQuests v0.1.17 loading (SFSE build {})", SFSE::GetSFSEVersion());

	// ★★ 第 84 轮（自动测试二跑复查）：结果 JSON 因**一处非法 UTF-8** 整体读不出来
	//   （`check_results.py` 退出码 2 —— 判据通道失效，比单条用例 FAIL 严重得多）。
	//   真因 = 日志/结果里的两处字节级截断/抄录：
	//     ① `UI::EscapeForLog` 截「界面状态」报告时切在多字节字符中间；
	//     ② 指针诊断的 RTTI 抄录把随机字节原样写进日志（含控制字符）。
	//   两处都已修（截断走 `Decision::Utf8SafeCut` + RTTI 只留可打印 ASCII）。
	//   这一行是**实机判据**：日志里出现它 ⇒ 跑的是第 84 轮之后的 DLL
	//   （同时被 verify 当 DLL 特征串检查）。
	REX::INFO("证据通道：日志/结果截断按 UTF-8 字符边界（第 84 轮）—— 不会再写入非法 UTF-8 字节");

	if (auto* messaging = SFSE::GetMessagingInterface()) {
		messaging->RegisterListener(OnMessage);
	} else {
		REX::WARN("messaging interface unavailable");
	}

	TryInstall();
	return true;
}
