// ★★ 第 53 轮（大项 F · 发布就绪）：整个文件只在开发构建（SAQ_WITH_HARNESS=1）里编译。
//   发布构建（xmake saq_harness=n）里 xmake 根本不加入这个文件；这里再包一层 #if
//   是**双保险**（见 SAQ_Test.cpp 开头的同一段说明）。
#if SAQ_WITH_HARNESS

#include "PCH.h"

#include "SAQ_TestOps.h"

#include "SAQ.h"        // PluginDir()
#include "SAQ_Guide.h"  // FindGlob（按已认领的前缀取 GLOB）
#include "SAQ_UI.h"     // UI::InvokeUiTestDrive

#include "RE/T/TESGlobal.h"
#include "RE/U/UIMessageQueue.h"

#include <spdlog/sinks/base_sink.h>
#include <spdlog/spdlog.h>

#include <Windows.h>

#include <algorithm>
#include <atomic>
#include <cmath>
#include <deque>
#include <format>
#include <mutex>
#include <regex>

namespace SAQ::Test
{
	namespace
	{
		// ESM 里追加的记录号（低 24 位；见 tools/esm/patch_saq_esm.py 的 TEST_GLOBS）
		constexpr std::uint32_t kLowSeq = 0x806;      // GLOB SAQ_TestSeq
		constexpr std::uint32_t kLowCmd = 0x807;      // GLOB SAQ_TestCmd
		constexpr std::uint32_t kLowArgA = 0x808;     // GLOB SAQ_TestArgA（FormID 低 24 位）
		constexpr std::uint32_t kLowArgB = 0x809;     // GLOB SAQ_TestArgB（FormID 高 8 位）
		constexpr std::uint32_t kLowArgC = 0x80A;     // GLOB SAQ_TestArgC（数值参数）
		constexpr std::uint32_t kLowAck = 0x80B;      // GLOB SAQ_TestAck（脚本回执）
		constexpr std::uint32_t kLowResult = 0x80C;   // GLOB SAQ_TestResult（结果码）
		constexpr std::uint32_t kLowHarness = 0x80D;  // GLOB SAQ_TestHarness（0/1/2 见头文件）

		constexpr const char* kMenuName = "BSMissionMenu";  // 与 SAQ.cpp 的 kMenuName 一致

		std::uint64_t NowMs()
		{
			return ::GetTickCount64();
		}

		// ---------------- 日志环形缓冲 ----------------
		constexpr std::size_t kRingMax = 4000;  // 一行约 120 B ⇒ 上限约 0.5 MB

		std::mutex                                      g_ringMutex;
		std::deque<std::pair<std::uint64_t, std::string>> g_ring;
		std::atomic<std::uint64_t>                      g_ringTotal{ 0 };

		class LogRingSink final : public spdlog::sinks::base_sink<std::mutex>
		{
		protected:
			void sink_it_(const spdlog::details::log_msg& a_msg) override
			{
				spdlog::memory_buf_t buf;
				formatter_->format(a_msg, buf);
				std::string line{ buf.data(), buf.size() };
				while (!line.empty() && (line.back() == '\n' || line.back() == '\r')) {
					line.pop_back();
				}
				std::lock_guard lock{ g_ringMutex };
				g_ring.emplace_back(g_ringTotal.load(std::memory_order_relaxed), std::move(line));
				if (g_ring.size() > kRingMax) {
					g_ring.pop_front();
				}
				g_ringTotal.fetch_add(1, std::memory_order_relaxed);
			}

			void flush_() override {}
		};

		// ---------------- ini 开关（[Test] Harness）----------------
		bool   g_iniCached{};
		bool   g_iniValue{};
		std::uint64_t g_iniReadAtMs{};
		// ★ 1 秒（不是 3 秒）：驱动器每 2 秒复查一次「Harness 有没有被改成 1」，
		//   缓存太长会把「改完到开跑」的延迟拖到 5 秒以上，调试体感差（读一次 ini 很便宜）。
		constexpr std::uint64_t kIniCacheMs = 1000;

		bool ReadIniHarness()
		{
			const auto now = NowMs();
			if (g_iniCached && now - g_iniReadAtMs < kIniCacheMs) {
				return g_iniValue;
			}
			bool value = false;
			if (const auto dir = PluginDir(); !dir.empty()) {
				const auto path = (dir / L"SAQ_ShowAvailableQuests.ini").wstring();
				value = ::GetPrivateProfileIntW(L"Test", L"Harness", 0, path.c_str()) != 0;
			}
			g_iniCached = true;
			g_iniValue = value;
			g_iniReadAtMs = now;
			return value;
		}

		// ---------------- 命令状态 ----------------
		bool          g_busy{};
		bool          g_seqAdopted{};
		std::uint32_t g_lastSeq{};
		std::uint64_t g_submittedAtMs{};

		RE::TESGlobal* Glob(std::uint32_t a_low)
		{
			return Guide::FindGlob(a_low);
		}
	}

	const char* OpName(Op a_op)
	{
		switch (a_op) {
		case Op::kPing: return "Ping";
		case Op::kQuestReset: return "任务回滚(Reset)";
		case Op::kQuestStart: return "接取(Start)";
		case Op::kQuestStage: return "推阶段(SetStage)";
		case Op::kQuestComplete: return "完成(CompleteQuest)";
		case Op::kTeleport: return "传送玩家(MoveTo)";
		default: return "None";
		}
	}

	const char* ResultText(std::int32_t a_code)
	{
		switch (a_code) {
		case 0: return "成功";
		case 1: return "表单取不到（非常驻引用/所在 cell 没加载？）";
		case 2: return "表单类型不对";
		case 3: return "执行异常";
		case 4: return "未知操作码";
		case 5: return "通道未就绪";
		default: return "未知结果码";
		}
	}

	// ==================================================================
	//  日志环形缓冲
	// ==================================================================
	void InstallLogRing()
	{
		auto* logger = spdlog::default_logger_raw();
		if (!logger) {
			return;
		}
		for (const auto& sink : logger->sinks()) {
			if (dynamic_cast<LogRingSink*>(sink.get()) != nullptr) {
				return;  // 已经装过（Install 可能被调多次）
			}
		}
		logger->sinks().push_back(std::make_shared<LogRingSink>());
	}

	std::size_t LogMark()
	{
		return static_cast<std::size_t>(g_ringTotal.load(std::memory_order_relaxed));
	}

	bool LogFind(std::size_t a_from, const std::string& a_regex, std::string& a_line)
	{
		std::regex re;
		try {
			re = std::regex{ a_regex, std::regex::ECMAScript | std::regex::icase };
		} catch (const std::regex_error&) {
			return false;
		}
		const auto from = static_cast<std::uint64_t>(a_from);
		std::lock_guard lock{ g_ringMutex };
		for (const auto& [idx, line] : g_ring) {
			if (idx < from) {
				continue;
			}
			if (std::regex_search(line, re)) {
				a_line = line;
				return true;
			}
		}
		return false;
	}

	std::string LogTail(std::size_t a_maxLines)
	{
		std::string out;
		std::lock_guard lock{ g_ringMutex };
		const std::size_t skip = g_ring.size() > a_maxLines ? g_ring.size() - a_maxLines : 0;
		for (std::size_t i = skip; i < g_ring.size(); ++i) {
			out += g_ring[i].second;
			out += '\n';
		}
		return out;
	}

	std::string LogSince(std::size_t a_from, std::size_t a_maxLines)
	{
		const auto from = static_cast<std::uint64_t>(a_from);
		std::string out;
		std::size_t lines = 0;
		std::lock_guard lock{ g_ringMutex };
		for (const auto& [idx, line] : g_ring) {
			if (idx < from) {
				continue;
			}
			out += line;
			out += '\n';
			if (++lines >= a_maxLines) {
				out += "...（更多行已省略，完整日志看 mod 目录里的 SAQ_ShowAvailableQuests.log）\n";
				break;
			}
		}
		return out.empty() ? std::string{ "（本步骤之后没有产生任何日志行）\n" } : out;
	}

	// ==================================================================
	//  harness 开关（0/1/2 协议见头文件）
	// ==================================================================
	bool EnableHarnessIfNeeded()
	{
		auto* ctl = Glob(kLowHarness);
		if (!ctl) {
			return false;
		}
		if (!ReadIniHarness()) {
			// ini 关着：只在「DLL 刚请求过、脚本还没接手」时清 0（不动脚本已置的 2，
			// 免得来回改写同一个 GLOB）。
			const float v = ctl->value;
			if (v > 0.5f && v < 1.5f) {
				ctl->value = 0.0f;
			}
			return false;
		}
		const float v = ctl->value;
		if (v < 0.5f) {
			ctl->value = 1.0f;  // 请求启用；脚本下一拍回写 2
			return false;
		}
		return v >= 1.5f;  // 2 = 脚本已就绪
	}

	bool HarnessRequested()
	{
		return ReadIniHarness();  // ini 的 [Test] Harness（3 秒缓存）
	}

	bool HarnessReady(std::string& a_detail)
	{
		auto* ctl = Glob(kLowHarness);
		if (!ctl) {
			a_detail = "SAQ_TestHarness 取不到（ESM 没打第 49 轮补丁？）";
			return false;
		}
		const float v = ctl->value;
		if (v < 1.5f) {
			a_detail = std::format("脚本尚未就绪（SAQ_TestHarness={:.0f}，等它回写 2）", v);
			return false;
		}
		if (!g_seqAdopted) {
			// 首次就绪：把 DLL 的序号追平通道里的当前值（读档后通道里的值可能更大，
			// 不追平会出现「刚提交就被判成已回执」的假成功）。
			if (auto* seq = Glob(kLowSeq)) {
				const float raw = seq->value;
				g_lastSeq = (raw > 0.0f) ? static_cast<std::uint32_t>(raw) : 0u;
			}
			g_seqAdopted = true;
		}
		a_detail = std::format("就绪（seq={}）", g_lastSeq);
		return true;
	}

	bool ChannelReady(std::string& a_detail)
	{
		auto* seq = Glob(kLowSeq);
		auto* cmd = Glob(kLowCmd);
		auto* argA = Glob(kLowArgA);
		auto* argB = Glob(kLowArgB);
		auto* argC = Glob(kLowArgC);
		auto* ack = Glob(kLowAck);
		auto* result = Glob(kLowResult);
		if (!seq || !cmd || !argA || !argB || !argC || !ack || !result) {
			a_detail = "测试命令通道 GLOB 不全（0x806~0x80C）—— ESM 需要重跑 tools/esm/patch_saq_esm.py";
			return false;
		}
		// 读一遍自检：这几个 GLOB 的正常值都远小于 1e9；读到天文数字说明偏移/对象不对，
		// 此时**拒绝写内存**（与 Guide::SetGuideTarget 的「拒绝写入」同一思路）。
		for (const auto* g : { seq, cmd, argA, argB, argC, ack, result }) {
			if (!std::isfinite(g->value) || std::fabs(g->value) > 1.0e9f) {
				a_detail = std::format("通道读数像垃圾（{}）—— 拒绝写内存", g->value);
				return false;
			}
		}
		a_detail = "通道可用";
		return true;
	}

	// ==================================================================
	//  命令通道
	// ==================================================================
	bool Submit(Op a_op, std::uint32_t a_formID, std::int32_t a_arg, std::string& a_detail)
	{
		std::string why;
		if (!ChannelReady(why)) {
			a_detail = why;
			return false;
		}
		auto* seq = Glob(kLowSeq);
		auto* cmd = Glob(kLowCmd);
		auto* argA = Glob(kLowArgA);
		auto* argB = Glob(kLowArgB);
		auto* argC = Glob(kLowArgC);

		// 读档会让通道里的序号回退；提交前先跳过去（否则可能撞上一个「已经存在的 Ack」）。
		const float rawSeq = seq->value;
		if (rawSeq > 0.0f) {
			const auto chSeq = static_cast<std::uint32_t>(rawSeq);
			if (chSeq > g_lastSeq) {
				g_lastSeq = chSeq;
			}
		}
		const auto next = g_lastSeq + 1;

		argA->value = static_cast<float>(a_formID & 0xFFFFFFu);        // 低 24 位（float 精确）
		argB->value = static_cast<float>((a_formID >> 24) & 0xFFu);    // 高 8 位
		argC->value = static_cast<float>(a_arg);
		cmd->value = static_cast<float>(static_cast<std::int32_t>(a_op));
		seq->value = static_cast<float>(next);  // ★ 提交点（最后写）

		g_lastSeq = next;
		g_busy = true;
		g_submittedAtMs = NowMs();
		a_detail = std::format("seq={} {}", next, OpName(a_op));
		return true;
	}

	int Poll(std::int32_t& a_resultCode, std::string& a_detail)
	{
		if (!g_busy) {
			return 0;
		}
		auto* ack = Glob(kLowAck);
		if (!ack) {
			a_detail = "SAQ_TestAck 取不到";
			return -1;
		}
		const double ackVal = static_cast<double>(ack->value);
		if (ackVal + 0.5 < static_cast<double>(g_lastSeq)) {
			return 0;  // 还没回执
		}
		g_busy = false;
		a_resultCode = 0;
		if (auto* result = Glob(kLowResult)) {
			a_resultCode = static_cast<std::int32_t>(result->value + (result->value < 0.0f ? -0.5f : 0.5f));
		}
		a_detail = std::format("seq={} 结果={}（{}）", g_lastSeq, a_resultCode, ResultText(a_resultCode));
		return 1;
	}

	bool Busy()
	{
		return g_busy;
	}

	std::uint64_t SubmittedAtMs()
	{
		return g_submittedAtMs;
	}

	std::uint32_t LastSeq()
	{
		return g_lastSeq;
	}

	void Abandon(const char* a_why)
	{
		if (g_busy) {
			g_busy = false;
			REX::WARN("测试原语：放弃未完成的命令（seq={}）—— {}", g_lastSeq, a_why ? a_why : "");
		}
	}

	// ==================================================================
	//  菜单开关
	// ==================================================================
	bool SetMenuOpen(bool a_open, std::string& a_detail)
	{
		auto* queue = RE::UIMessageQueue::GetSingleton();
		if (!queue) {
			a_detail = "UIMessageQueue 取不到（UI 还没起来？）";
			return false;
		}
		queue->AddMessage(RE::BSFixedString{ kMenuName },
			a_open ? RE::UI_MESSAGE_TYPE::kShow : RE::UI_MESSAGE_TYPE::kHide);
		a_detail = a_open ? "已请求打开任务菜单（kShow）" : "已请求关闭任务菜单（kHide）";
		return true;
	}

	bool ClearGuide(std::string& a_detail)
	{
		// 与玩家取消引导 / 接取后自动取消同一个调用（a_formID = 0 ⇒ 脚本 Clear + 取消目标显示）。
		std::string detail;
		if (!Guide::SetGuideTarget(0, detail)) {
			a_detail = "清除引导失败：" + detail;
			return false;
		}
		a_detail = detail;
		return true;
	}

	// ==================================================================
	//  UI 测试驱动（实现在 SAQ_UI.cpp —— 那里有桥的解析与 Invoke 校验）
	// ==================================================================
	bool InvokeUiTestDrive(const char* a_fn, const std::string& a_arg, std::string& a_reply)
	{
		return UI::InvokeUiTestDrive(a_fn, a_arg, a_reply);
	}
}

#endif  // SAQ_WITH_HARNESS

