#include "PCH.h"

#include "SAQ.h"

#include <atomic>
#include <cstddef>
#include <exception>
#include <filesystem>
#include <memory>

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

	// 日志文件上限 1 MiB：写新一行时若会超过就把旧内容整体清空（不是滚动保留旧文件）。
	constexpr std::size_t kLogMaxBytes = 1024 * 1024;

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

		std::filesystem::path fileName{ kLogName };
		fileName += ".log";

		std::shared_ptr<spdlog::sinks::sink> fileSink;
		if (const auto dir = SAQ::PluginDir(); !dir.empty()) {
			try {
				fileSink = std::make_shared<SizeLimitedFileSink>(dir / fileName, kLogMaxBytes);
			} catch (const std::exception& e) {
				REX::WARN("插件目录里建日志失败（{}）—— 回退到默认日志目录", e.what());
			}
		}
		if (!fileSink) {
			if (const auto dir = SFSE::log::log_directory()) {
				try {
					fileSink = std::make_shared<SizeLimitedFileSink>(*dir / fileName, kLogMaxBytes);
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
		REX::INFO("日志文件：插件目录（mod 目录）内的 {}", fileName.string());
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

	REX::INFO("SAQ_ShowAvailableQuests v0.1.4 loading (SFSE build {})", SFSE::GetSFSEVersion());

	if (auto* messaging = SFSE::GetMessagingInterface()) {
		messaging->RegisterListener(OnMessage);
	} else {
		REX::WARN("messaging interface unavailable");
	}

	TryInstall();
	return true;
}
