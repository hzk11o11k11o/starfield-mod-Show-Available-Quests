#include "PCH.h"

#include "SAQ_Test.h"

#include "SAQ.h"          // PluginDir()
#include "SAQ_TestOps.h"  // 原语层
#include "SAQ_UI.h"       // ReadUiReport

#include "RE/U/UI.h"

#include <Windows.h>

#include <algorithm>
#include <cctype>
#include <fstream>
#include <format>
#include <regex>
#include <string_view>
#include <vector>

namespace SAQ::Test
{
	namespace
	{
		constexpr const char* kMenuName = "BSMissionMenu";
		constexpr std::uint64_t kDefaultStepTimeoutMs = 5000;
		constexpr std::uint64_t kCommandAckTimeoutMs = 3000;   // 命令通道（脚本一拍 0.5 秒）
		constexpr std::uint64_t kReadyCheckIntervalMs = 500;
		constexpr std::size_t   kEvidenceMaxLines = 60;

		std::uint64_t NowMs()
		{
			return ::GetTickCount64();
		}

		// ----------------------------------------------------------------
		//  步骤 / 用例
		// ----------------------------------------------------------------
		enum class Kind
		{
			kCmd,          // 走 Papyrus 命令通道（要菜单关着）
			kWait,
			kMenu,         // menu.open / menu.close
			kUi,           // ui.select / ui.key / ui.expand / ui.tab
			kAssertLog,
			kAssertUi,
			kAssertMenu,
			kNote,
			kGuideClear,   // 取消引导（DLL 自己的产品路径：Guide::SetGuideTarget(0)）
		};

		struct Step
		{
			Kind          kind{ Kind::kNote };
			Op            op{ Op::kNone };    // kind == kCmd 时有效
			std::string   raw;                // 原始行（日志/结果里原样带出来）
			std::string   opName;             // "quest.stage" / "assert.log" …
			std::string   text;               // 正则 / 备注文本 / ui 参数
			std::uint32_t formId{};
			std::int32_t  num{};
			bool          menuOpen{};         // kind == kMenu / kAssertMenu
			std::uint64_t timeoutMs{ kDefaultStepTimeoutMs };
		};

		struct Case
		{
			std::string       id;
			std::string       desc;
			std::vector<Step> steps;
		};

		struct StepResult
		{
			std::string op;
			bool        pass{};
			std::string detail;
			std::string evidence;
			std::uint64_t elapsedMs{};
		};

		struct CaseResult
		{
			std::string             id;
			std::string             desc;
			std::string             status{ "PENDING" };  // PASS / FAIL / SKIP
			std::string             reason;               // SKIP 的原因
			std::vector<StepResult> steps;
			std::uint64_t           elapsedMs{};
		};

		std::vector<Case>       g_cases;
		std::vector<CaseResult> g_results;

		bool        g_enabled{};
		bool        g_loaded{};
		// ★ 未启用时的复查节流 + 「这次变成要跑了吗」的边沿标记（见 PollEnable）
		bool        g_wantHarness{};
		std::uint64_t g_lastEnableCheckMs{};
		constexpr std::uint64_t kEnableCheckIntervalMs = 2000;
		bool        g_harnessReady{};
		bool        g_readyWarned{};
		bool        g_active{};
		bool        g_finished{};
		bool        g_wroteResults{};
		std::string g_planPath;                 // 计划文件路径（日志用）
		std::string g_channelDetail;
		std::size_t g_caseIdx{};
		std::size_t g_stepIdx{};
		std::uint64_t g_lastReadyCheckMs{};
		std::uint64_t g_caseStartedMs{};
		std::uint64_t g_sessionStartMs{};

		struct StepState
		{
			bool          started{};
			std::uint64_t deadlineMs{};
			std::uint64_t startedAtMs{};
			std::size_t   logMark{};
			bool          kicked{};
			std::string   kickDetail;
		};
		StepState g_cur;

		// ----------------------------------------------------------------
		//  小工具
		// ----------------------------------------------------------------
		std::string Trim(std::string_view a_in)
		{
			std::size_t b = 0;
			std::size_t e = a_in.size();
			while (b < e && (std::isspace(static_cast<unsigned char>(a_in[b])) != 0)) ++b;
			while (e > b && (std::isspace(static_cast<unsigned char>(a_in[e - 1])) != 0)) --e;
			return std::string{ a_in.substr(b, e - b) };
		}

		std::vector<std::string> SplitWs(std::string_view a_in)
		{
			std::vector<std::string> out;
			std::size_t i = 0;
			while (i < a_in.size()) {
				while (i < a_in.size() && std::isspace(static_cast<unsigned char>(a_in[i])) != 0) ++i;
				std::size_t b = i;
				while (i < a_in.size() && std::isspace(static_cast<unsigned char>(a_in[i])) == 0) ++i;
				if (i > b) {
					out.emplace_back(a_in.substr(b, i - b));
				}
			}
			return out;
		}

		bool ParseFormID(const std::string& a_text, std::uint32_t& a_out)
		{
			try {
				a_out = static_cast<std::uint32_t>(std::stoul(a_text, nullptr, 16));
				return true;
			} catch (...) {
				return false;
			}
		}

		// 从串里摘出 `timeout=N`（其余部分原样返回）
		std::string ExtractTimeout(std::string a_text, std::uint64_t& a_out)
		{
			for (std::size_t pos = 0; (pos = a_text.find("timeout=", pos)) != std::string::npos;) {
				const std::size_t end = a_text.find_first_of(" \t", pos);
				const std::string tok = a_text.substr(pos + 8,
					(end == std::string::npos ? a_text.size() : end) - (pos + 8));
				try {
					a_out = static_cast<std::uint64_t>(std::stoull(tok));
				} catch (...) {
				}
				a_text.erase(pos, (end == std::string::npos ? a_text.size() : end) - pos);
				break;
			}
			return Trim(a_text);
		}

		std::string JsonEscape(std::string_view a_in)
		{
			std::string out;
			out.reserve(a_in.size() + 16);
			for (const char c : a_in) {
				switch (c) {
				case '"': out += "\\\""; break;
				case '\\': out += "\\\\"; break;
				case '\n': out += "\\n"; break;
				case '\r': break;
				case '\t': out += "\\t"; break;
				default:
					if (static_cast<unsigned char>(c) < 0x20) {
						out += std::format("\\u{:04X}", static_cast<unsigned>(static_cast<unsigned char>(c)));
					} else {
						out += c;
					}
				}
			}
			return out;
		}

		bool MenuIsOpen()
		{
			auto* ui = RE::UI::GetSingleton();
			return ui != nullptr && ui->IsMenuOpen(RE::BSFixedString{ kMenuName });
		}

		// ----------------------------------------------------------------
		//  计划解析
		// ----------------------------------------------------------------
		bool ParseStep(const std::string& a_line, Step& a_step, std::string& a_error)
		{
			// op 名与其余部分分开（assert.log 的正则里可能有空格）
			std::size_t sp = a_line.find_first_of(" \t");
			const std::string op = sp == std::string::npos ? a_line : a_line.substr(0, sp);
			std::string rest = sp == std::string::npos ? std::string{} : a_line.substr(sp + 1);
			a_step = Step{};
			a_step.raw = a_line;
			a_step.opName = op;
			a_step.timeoutMs = kDefaultStepTimeoutMs;

			auto needFormID = [&](std::uint32_t& a_out) -> bool {
				const auto toks = SplitWs(rest);
				if (toks.empty() || !ParseFormID(toks[0], a_out)) {
					a_error = "需要 FormID 参数（如 0x002A1B3C）";
					return false;
				}
				return true;
			};

			if (op == "ping") {
				a_step.kind = Kind::kCmd;
				a_step.op = Op::kPing;
			} else if (op == "quest.reset" || op == "quest.start" || op == "quest.complete" || op == "teleport") {
				a_step.kind = Kind::kCmd;
				a_step.op = (op == "quest.reset")    ? Op::kQuestReset
					: (op == "quest.start")          ? Op::kQuestStart
					: (op == "quest.complete")       ? Op::kQuestComplete
													 : Op::kTeleport;
				if (!needFormID(a_step.formId)) {
					return false;
				}
			} else if (op == "quest.stage") {
				a_step.kind = Kind::kCmd;
				a_step.op = Op::kQuestStage;
				const auto toks = SplitWs(rest);
				if (toks.size() < 2 || !ParseFormID(toks[0], a_step.formId)) {
					a_error = "需要 <FormID> <stage> 两个参数";
					return false;
				}
				try {
					a_step.num = static_cast<std::int32_t>(std::stol(toks[1]));
				} catch (...) {
					a_error = "stage 不是数字：" + toks[1];
					return false;
				}
			} else if (op == "wait") {
				a_step.kind = Kind::kWait;
				const auto toks = SplitWs(rest);
				if (toks.empty()) {
					a_error = "需要毫秒数";
					return false;
				}
				try {
					a_step.timeoutMs = static_cast<std::uint64_t>(std::stoull(toks[0]));
				} catch (...) {
					a_error = "wait 参数不是数字：" + toks[0];
					return false;
				}
			} else if (op == "menu.open" || op == "menu.close") {
				a_step.kind = Kind::kMenu;
				a_step.menuOpen = (op == "menu.open");
				a_step.timeoutMs = 8000;
			} else if (op == "ui.select" || op == "ui.key" || op == "ui.expand" || op == "ui.tab") {
				a_step.kind = Kind::kUi;
				a_step.text = Trim(rest);
				a_step.timeoutMs = 3000;
				if (op != "ui.tab" && a_step.text.empty()) {
					a_error = "需要参数（uID 或按键名）";
					return false;
				}
				// uID 习惯上写成 0x…（与日志一致），AS3 侧按十进制 Number 比较 ⇒ 这里转一次。
				// 转换失败就原样传（关键字参数，如 ui.key XButton）。
				if ((op == "ui.select" || op == "ui.expand") && a_step.text.rfind("0x", 0) == 0) {
					std::uint32_t uid = 0;
					if (ParseFormID(a_step.text, uid)) {
						a_step.text = std::to_string(uid);
					}
				}
			} else if (op == "assert.log" || op == "assert.ui") {
				a_step.kind = (op == "assert.log") ? Kind::kAssertLog : Kind::kAssertUi;
				rest = ExtractTimeout(rest, a_step.timeoutMs);
				a_step.text = rest;
				if (a_step.text.empty()) {
					a_error = "需要正则表达式";
					return false;
				}
			} else if (op == "assert.menu") {
				a_step.kind = Kind::kAssertMenu;
				const auto toks = SplitWs(ExtractTimeout(rest, a_step.timeoutMs));
				if (toks.empty() || (toks[0] != "open" && toks[0] != "closed")) {
					a_error = "需要 open|closed";
					return false;
				}
				a_step.menuOpen = (toks[0] == "open");
			} else if (op == "guide.clear") {
				a_step.kind = Kind::kGuideClear;
			} else if (op == "note") {
				a_step.kind = Kind::kNote;
				a_step.text = Trim(rest);
			} else {
				a_error = "未知步骤：" + op;
				return false;
			}

			// 命令类步骤：回执超时常量与步骤超时取小（避免「脚本没跑」时白等 5 秒以上）
			if (a_step.kind == Kind::kCmd) {
				a_step.timeoutMs = std::min(a_step.timeoutMs, kCommandAckTimeoutMs);
			}
			return true;
		}

		void ParsePlan(const std::string& a_path)
		{
			g_cases.clear();
			std::ifstream f{ a_path.c_str(), std::ios::binary };
			if (!f) {
				REX::WARN("harness：读不到用例文件 {}（[Test] Plan 指向它）", a_path);
				return;
			}
			std::string line;
			Case* cur = nullptr;
			std::size_t lineNo = 0;
			std::size_t bad = 0;
			while (std::getline(f, line)) {
				++lineNo;
				if (!line.empty() && line.back() == '\r') {
					line.pop_back();
				}
				if (lineNo == 1 && line.size() >= 3 &&
					static_cast<unsigned char>(line[0]) == 0xEF &&
					static_cast<unsigned char>(line[1]) == 0xBB &&
					static_cast<unsigned char>(line[2]) == 0xBF) {
					line.erase(0, 3);  // UTF-8 BOM（记事本另存会加；不剥会让第一行解析失败）
				}
				const std::string trimmed = Trim(line);
				if (trimmed.empty() || trimmed[0] == ';' || trimmed[0] == '#') {
					continue;
				}
				if (trimmed[0] == '[') {
					const auto close = trimmed.find(']');
					if (close == std::string::npos) {
						REX::WARN("harness：用例文件第 {} 行缺少 ']'：{}", lineNo, trimmed);
						++bad;
						continue;
					}
					std::string header = trimmed.substr(1, close - 1);
					if (header.rfind("case:", 0) != 0) {
						REX::WARN("harness：用例文件第 {} 行不是 [case:...]：{}", lineNo, trimmed);
						++bad;
						continue;
					}
					g_cases.emplace_back();
					cur = &g_cases.back();
					cur->id = Trim(header.substr(5));
					continue;
				}
				const auto eq = trimmed.find('=');
				if (eq == std::string::npos) {
					REX::WARN("harness：用例文件第 {} 行不是 key = value：{}", lineNo, trimmed);
					++bad;
					continue;
				}
				if (cur == nullptr) {
					REX::WARN("harness：用例文件第 {} 行在 [case:...] 之前：{}", lineNo, trimmed);
					++bad;
					continue;
				}
				const std::string key = Trim(trimmed.substr(0, eq));
				const std::string value = Trim(trimmed.substr(eq + 1));
				if (key == "desc") {
					cur->desc = value;
				} else if (key == "step") {
					Step st;
					std::string err;
					if (ParseStep(value, st, err)) {
						cur->steps.push_back(std::move(st));
					} else {
						REX::WARN("harness：用例 {} 第 {} 行的步骤解析失败（{}）：{}", cur->id, lineNo, err, value);
						++bad;
					}
				} else {
					REX::WARN("harness：用例文件第 {} 行的未知键 {}（只认 desc / step）", lineNo, key);
					++bad;
				}
			}
			std::size_t total = 0;
			for (const auto& c : g_cases) {
				total += c.steps.size();
			}
			REX::INFO("harness：用例文件已载入（{} 个用例 / {} 个步骤{}）—— {}", g_cases.size(), total,
				bad ? std::format("，{} 行解析失败（见上面 WARN）", bad) : std::string{},
				a_path);
			for (const auto& c : g_cases) {
				REX::INFO("harness：  用例 {}（{} 步）{}", c.id, c.steps.size(), c.desc.empty() ? "" : " —— " + c.desc);
			}
		}

		std::string PlanPathFromIni(std::string& a_detail)
		{
			const auto dir = PluginDir();
			if (dir.empty()) {
				a_detail = "插件目录取不到";
				return {};
			}
			const auto iniPath = (dir / L"SAQ_ShowAvailableQuests.ini").wstring();
			wchar_t buf[MAX_PATH]{};
			::GetPrivateProfileStringW(L"Test", L"Plan", L"SAQ_TestPlan.txt", buf, MAX_PATH, iniPath.c_str());
			const auto path = dir / buf;
			a_detail = path.string();
			return path.string();
		}

		// ----------------------------------------------------------------
		//  结果落盘
		// ----------------------------------------------------------------
		void WriteResults()
		{
			const auto dir = PluginDir();
			if (dir.empty()) {
				return;
			}
			const auto path = dir / L"SAQ_testresults.json";

			std::size_t pass = 0, fail = 0, skip = 0;
			for (const auto& r : g_results) {
				if (r.status == "PASS") ++pass;
				else if (r.status == "FAIL") ++fail;
				else if (r.status == "SKIP") ++skip;
			}

			SYSTEMTIME st{};
			::GetLocalTime(&st);

			std::string out;
			out += "{\n";
			out += std::format("  \"generatedAt\": \"{:04}-{:02}-{:02} {:02}:{:02}:{:02}\",\n",
				st.wYear, st.wMonth, st.wDay, st.wHour, st.wMinute, st.wSecond);
			out += std::format("  \"sessionMs\": {},\n", NowMs() - g_sessionStartMs);
			out += std::format("  \"plan\": \"{}\",\n", JsonEscape(g_planPath));
			out += std::format("  \"summary\": {{ \"cases\": {}, \"pass\": {}, \"fail\": {}, \"skip\": {} }},\n",
				g_results.size(), pass, fail, skip);
			out += "  \"results\": [\n";
			for (std::size_t i = 0; i < g_results.size(); ++i) {
				const auto& r = g_results[i];
				out += "    {\n";
				out += std::format("      \"id\": \"{}\",\n", JsonEscape(r.id));
				out += std::format("      \"desc\": \"{}\",\n", JsonEscape(r.desc));
				out += std::format("      \"status\": \"{}\",\n", r.status);
				out += std::format("      \"elapsedMs\": {},\n", r.elapsedMs);
				if (!r.reason.empty()) {
					out += std::format("      \"reason\": \"{}\",\n", JsonEscape(r.reason));
				}
				out += "      \"steps\": [\n";
				for (std::size_t j = 0; j < r.steps.size(); ++j) {
					const auto& s = r.steps[j];
					out += "        {";
					out += std::format("\"op\": \"{}\", \"status\": \"{}\", \"elapsedMs\": {}",
						JsonEscape(s.op), s.pass ? "PASS" : "FAIL", s.elapsedMs);
					if (!s.detail.empty()) {
						out += std::format(", \"detail\": \"{}\"", JsonEscape(s.detail));
					}
					if (!s.evidence.empty()) {
						out += std::format(", \"evidence\": \"{}\"", JsonEscape(s.evidence));
					}
					out += "}";
					out += (j + 1 < r.steps.size()) ? ",\n" : "\n";
				}
				out += "      ]\n";
				out += "    }";
				out += (i + 1 < g_results.size()) ? ",\n" : "\n";
			}
			out += "  ]\n}\n";

			// ★ 用「先删后写」而不是 std::ofstream 直接写：MO2 的 usvfs 下要保证文件落在
			//   mod 目录（部署时已预建空文件，见 build-saq.ps1 的部署步骤）。
			std::ofstream f{ path.c_str(), std::ios::binary | std::ios::trunc };
			if (!f) {
				REX::WARN("harness：结果文件写不进去（{}）—— 结果只在日志里", path.string());
				return;
			}
			f.write("\xEF\xBB\xBF", 3);  // BOM：记事本/编辑器都认 UTF-8（含中文细节）
			f.write(out.data(), static_cast<std::streamsize>(out.size()));
			f.close();
			g_wroteResults = true;
			REX::INFO("harness：结果已写入 {}（{} 个用例：PASS {} / FAIL {} / SKIP {}）",
				path.string(), g_results.size(), pass, fail, skip);
		}

		// ----------------------------------------------------------------
		//  用例/步骤推进
		// ----------------------------------------------------------------
		void FinishCase(bool a_ok, const std::string& a_reason)
		{
			if (g_caseIdx >= g_results.size()) {
				return;
			}
			auto& r = g_results[g_caseIdx];
			r.elapsedMs = NowMs() - g_caseStartedMs;
			if (a_ok) {
				r.status = "PASS";
				REX::INFO("harness：用例 {} PASS（{} ms）", r.id, r.elapsedMs);
			} else {
				r.status = a_reason.empty() ? "FAIL" : "SKIP";
				r.reason = a_reason;
				if (a_reason.empty()) {
					REX::WARN("harness：用例 {} FAIL（{} ms）—— 详细证据见 SAQ_testresults.json", r.id, r.elapsedMs);
				} else {
					REX::WARN("harness：用例 {} SKIP —— {}", r.id, a_reason);
				}
			}
			g_active = false;
			g_stepIdx = 0;
		}

		void StartCase(std::size_t a_index)
		{
			g_caseIdx = a_index;
			g_stepIdx = 0;
			g_cur = StepState{};
			g_caseStartedMs = NowMs();
			CaseResult r;
			r.id = g_cases[a_index].id;
			r.desc = g_cases[a_index].desc;
			g_results.push_back(std::move(r));
			g_active = true;
			REX::INFO("harness：===== 开始用例 {}（{}）=====", g_cases[a_index].id,
				g_cases[a_index].desc.empty() ? g_cases[a_index].id : g_cases[a_index].desc);
		}

		// 步骤成功/失败收尾（写结果 + 推进）
		void CompleteStep(bool a_pass, const std::string& a_detail, const std::string& a_evidence)
		{
			const auto& step = g_cases[g_caseIdx].steps[g_stepIdx];
			StepResult sr;
			sr.op = step.raw;
			sr.pass = a_pass;
			sr.detail = a_detail;
			sr.evidence = a_evidence;
			sr.elapsedMs = NowMs() - g_cur.startedAtMs;
			g_results[g_caseIdx].steps.push_back(std::move(sr));

			if (a_pass) {
				REX::INFO("harness：  [PASS] {}（{} ms）{}", step.raw, sr.elapsedMs,
					a_detail.empty() ? "" : " —— " + a_detail);
				++g_stepIdx;
				g_cur = StepState{};
				if (g_stepIdx >= g_cases[g_caseIdx].steps.size()) {
					FinishCase(true, {});
				}
				return;
			}

			REX::WARN("harness：  [FAIL] {}（{} ms）—— {}", step.raw, sr.elapsedMs, a_detail);
			// 一条用例失败就停（后面的步骤多半也没意义），把证据留在结果里
			FinishCase(false, {});  // 空 reason ⇒ FAIL（不是 SKIP）
		}

		// 返回值：true = 这一步已经处理完（成功或失败都已收尾）
		bool RunStep(bool a_menuOpen)
		{
			const Case& c = g_cases[g_caseIdx];
			const Step& step = c.steps[g_stepIdx];
			const std::uint64_t now = NowMs();

			if (!g_cur.started) {
				g_cur.started = true;
				g_cur.startedAtMs = now;
				g_cur.logMark = LogMark();
				// menu.open / menu.close 的 deadline 从「发动之后」开始算
				g_cur.deadlineMs = now + step.timeoutMs;
			}

			auto timeoutFail = [&](const std::string& a_what, const std::string& a_extra) {
				CompleteStep(false, a_what + "（超时 " + std::to_string(step.timeoutMs) + " ms；" + a_extra + "）",
					LogSince(g_cur.logMark, kEvidenceMaxLines));
			};

			switch (step.kind) {
			case Kind::kNote:
				REX::INFO("harness：  [note] {}", step.text);
				CompleteStep(true, step.text, {});
				return true;

			case Kind::kGuideClear: {
				std::string detail;
				if (!ClearGuide(detail)) {
					CompleteStep(false, detail, LogSince(g_cur.logMark, kEvidenceMaxLines));
					return true;
				}
				// 真正生效要等脚本的轮询节拍（菜单关着时）—— 这里只确认请求已下发。
				CompleteStep(true, detail + "（脚本下一拍清除）", {});
				return true;
			}

			case Kind::kWait:
				if (now - g_cur.startedAtMs >= step.timeoutMs) {
					CompleteStep(true, std::format("等了 {} ms", step.timeoutMs), {});
					return true;
				}
				return false;

			case Kind::kMenu: {
				if (!g_cur.kicked) {
					std::string detail;
					if (!SetMenuOpen(step.menuOpen, detail)) {
						CompleteStep(false, "菜单操作失败：" + detail, LogSince(g_cur.logMark, kEvidenceMaxLines));
						return true;
					}
					g_cur.kicked = true;
					g_cur.kickDetail = detail;
					g_cur.deadlineMs = NowMs() + step.timeoutMs;
				}
				if (MenuIsOpen() == step.menuOpen) {
					CompleteStep(true, std::format("{} → 已{}", g_cur.kickDetail, step.menuOpen ? "打开" : "关闭"), {});
					return true;
				}
				if (now >= g_cur.deadlineMs) {
					timeoutFail(std::format("菜单没有{}", step.menuOpen ? "打开" : "关闭"), g_cur.kickDetail);
					return true;
				}
				return false;
			}

			case Kind::kAssertMenu:
				if (MenuIsOpen() == step.menuOpen) {
					CompleteStep(true, std::format("菜单{}（符合预期）", step.menuOpen ? "开着" : "关着"), {});
					return true;
				}
				if (now >= g_cur.deadlineMs) {
					timeoutFail(std::format("菜单没有{}", step.menuOpen ? "打开" : "关闭"), "assert.menu");
					return true;
				}
				return false;

			case Kind::kUi: {
				if (!g_cur.kicked) {
					const char* fn = (step.opName == "ui.select")  ? "SAQ_TestDriveSelect"
						: (step.opName == "ui.key")                ? "SAQ_TestDriveKey"
						: (step.opName == "ui.tab")                ? "SAQ_TestDriveTab"
																   : "SAQ_TestDriveExpand";
					std::string reply;
					const bool ok = InvokeUiTestDrive(fn, step.text, reply);
					if (!ok) {
						CompleteStep(false, std::format("{} 调用失败：{}", fn, reply),
							LogSince(g_cur.logMark, kEvidenceMaxLines));
						return true;
					}
					// AS3 约定：回串以 "ok" 开头 = 动作已送出；"err" = 找不到目标等
					const bool pass = reply.rfind("ok", 0) == 0;
					CompleteStep(pass, std::format("{}（{}）", reply.empty() ? "无返回串" : reply, fn),
						pass ? std::string{} : LogSince(g_cur.logMark, kEvidenceMaxLines));
					return true;
				}
				return false;
			}

			case Kind::kAssertLog: {
				std::string line;
				if (LogFind(g_cur.logMark, step.text, line)) {
					CompleteStep(true, "命中：" + line, {});
					return true;
				}
				if (now >= g_cur.deadlineMs) {
					timeoutFail(std::format("日志里没出现 /{}/", step.text), "本步骤之后的日志见 evidence");
					return true;
				}
				return false;
			}

			case Kind::kAssertUi: {
				std::string report;
				if (UI::ReadUiReport(report) && !report.empty()) {
					try {
						if (std::regex_search(report, std::regex{ step.text, std::regex::ECMAScript | std::regex::icase })) {
							CompleteStep(true, "界面报告命中：" + report, {});
							return true;
						}
					} catch (const std::regex_error&) {
						CompleteStep(false, "正则写错：" + step.text, {});
						return true;
					}
				}
				if (now >= g_cur.deadlineMs) {
					timeoutFail(std::format("界面报告里没出现 /{}/", step.text),
						report.empty() ? "读不到界面报告（菜单关着？/ 桥没通？）" : "最后读到：" + report);
					return true;
				}
				return false;
			}

			case Kind::kCmd: {
				if (!g_cur.kicked) {
					// 时序红线：命令只在菜单关着时被脚本消化（第 27 轮实测定案）。
					// 这里容错（自动关菜单），但记 WARN —— 用例写错了要在日志里看得见。
					if (a_menuOpen) {
						std::string detail;
						REX::WARN("harness：  命令步骤出现在菜单开着时（用例 {} 的 {}）—— 自动关菜单后继续（用例顺序应该修）",
							c.id, step.raw);
						SetMenuOpen(false, detail);
						return false;
					}
					std::string detail;
					if (!Submit(step.op, step.formId, step.num, detail)) {
						CompleteStep(false, "提交命令失败：" + detail, LogSince(g_cur.logMark, kEvidenceMaxLines));
						return true;
					}
					g_cur.kicked = true;
					g_cur.kickDetail = detail;
					g_cur.deadlineMs = now + step.timeoutMs;
					REX::INFO("harness：  提交命令 {}", detail);
					return false;
				}
				std::int32_t code = 0;
				std::string detail;
				const int rc = Poll(code, detail);
				if (rc == 1) {
					const bool pass = (code == 0);
					CompleteStep(pass, detail + (pass ? "" : std::format("；命令={} {}", step.raw, ResultText(code))),
						pass ? std::string{} : LogSince(g_cur.logMark, kEvidenceMaxLines));
					return true;
				}
				if (rc < 0) {
					CompleteStep(false, "通道不可用：" + detail, LogSince(g_cur.logMark, kEvidenceMaxLines));
					return true;
				}
				if (now >= g_cur.deadlineMs) {
					Abandon("命令回执超时");
					timeoutFail("命令没有回执", std::format("{}（脚本定时器在菜单开着时冻结；确认此刻菜单是关的）",
														g_cur.kickDetail));
					return true;
				}
				return false;
			}
			}
			return false;
		}
	}

	// ==================================================================
	//  对外
	// ==================================================================
	bool Enabled()
	{
		return g_enabled;
	}

	bool Finished()
	{
		return g_finished;
	}

	std::string StatusLine()
	{
		if (!g_enabled) {
			return "harness=关";
		}
		if (!g_loaded) {
			return "harness=待载入";
		}
		if (g_finished) {
			std::size_t pass = 0, fail = 0, skip = 0;
			for (const auto& r : g_results) {
				if (r.status == "PASS") ++pass;
				else if (r.status == "FAIL") ++fail;
				else if (r.status == "SKIP") ++skip;
			}
			return std::format("harness=已完成（用例 {}：PASS {} / FAIL {} / SKIP {}）", g_results.size(), pass, fail, skip);
		}
		if (!g_active) {
			return g_harnessReady ? "harness=就绪" : "harness=等脚本就绪";
		}
		return std::format("harness=运行中（用例 {}/{}，步骤 {}/{}）", g_caseIdx + 1, g_cases.size(),
			g_stepIdx + 1, g_cases[g_caseIdx].steps.size());
	}

	void LoadPlan()
	{
		g_enabled = HarnessRequested();
		if (!g_enabled) {
			REX::INFO("harness：未启用（ini [Test] Harness=0）—— 引擎内自动化测试关闭");
			return;
		}
		std::string pathDetail;
		g_planPath = PlanPathFromIni(pathDetail);
		if (g_planPath.empty()) {
			REX::WARN("harness：拿不到用例文件路径（{}）", pathDetail);
			g_enabled = false;
			return;
		}
		ParsePlan(g_planPath);
		if (g_cases.empty()) {
			REX::WARN("harness：用例文件里没有任何 [case:...] —— 不做任何事（{}）", g_planPath);
			g_enabled = false;
			return;
		}
		g_sessionStartMs = NowMs();
		g_results.clear();
		g_loaded = true;
		g_finished = false;
		g_wroteResults = false;
		g_harnessReady = false;
		g_active = false;
		g_readyWarned = false;
		REX::INFO("harness：已启用（{} 个用例）—— 等脚本通道就绪后自动开跑", g_cases.size());
	}

	namespace
	{
		// 未启用时每 2 秒复查一次 ini：允许「Harness 改 0→1」**当场**载入用例并开跑。
		//
		// 为什么值得加这一段：ini 是在插件加载时读一次，而实机第一次跑 smoke 就因为
		// 「两个键被构建脚本追加到了 [Filter] 段 ⇒ 读到 0」白重启了一次游戏。有了这条复查，
		// 「改开关 → 看结果」的循环不需要重启（要重新载入用例：把 Harness 拨回 0 再置 1）。
		bool PollEnable()
		{
			const auto now = NowMs();
			if (now - g_lastEnableCheckMs < kEnableCheckIntervalMs) {
				return false;
			}
			g_lastEnableCheckMs = now;
			if (!HarnessRequested()) {
				g_wantHarness = false;
				return false;
			}
			if (g_wantHarness) {
				return false;  // 已经尝试过载入（失败要重试就把开关拨一次）
			}
			g_wantHarness = true;
			LoadPlan();
			return true;
		}
	}

	void Tick(bool a_menuOpen)
	{
		if (g_finished) {
			return;
		}
		if (!g_enabled || !g_loaded) {
			// 未启用（或载入失败）：只在「这一次变成要跑」时载入一次，其余情况立刻返回
			// ⇒ 零开销（一次时间戳比较）。
			PollEnable();
			return;
		}

		auto finishAll = [&]() {
			// ★ 第 49 轮补丁：结束（含失败中止）时把菜单恢复成「关着」。
			//   首测实证：smoke 在 ui.tab 失败中止 ⇒ 后面的 menu.close 步骤没跑到
			//   ⇒ 任务菜单（暂停菜单）一直留在屏幕上（游戏暂停、脚本定时器冻结），
			//   得玩家手动按 Cancel 才能继续。用例跑完菜单该回到常态。
			if (MenuIsOpen()) {
				std::string detail;
				if (SetMenuOpen(false, detail)) {
					REX::INFO("harness：结束时菜单还开着 —— 已请求关闭（{}）", detail);
				}
			}
			g_finished = true;
			WriteResults();
			REX::INFO("harness：全部用例结束 —— {}", StatusLine());
		};

		if (!g_active) {
			// ① 等脚本把通道置成「就绪」（SAQ_TestHarness 由 1 → 2），见 SAQ_TestOps.h 的协议说明
			if (!g_harnessReady) {
				const auto now = NowMs();
				if (now - g_lastReadyCheckMs < kReadyCheckIntervalMs) {
					return;
				}
				g_lastReadyCheckMs = now;
				if (!EnableHarnessIfNeeded()) {
					if (!g_readyWarned) {
						g_readyWarned = true;
						REX::INFO("harness：已请求启用（SAQ_TestHarness=1），等脚本回写 2（脚本每 0.5 秒一拍）");
					}
					return;
				}
				std::string detail;
				if (!HarnessReady(detail)) {
					g_channelDetail = detail;
					return;
				}
				g_harnessReady = true;
				g_channelDetail = detail;
				REX::INFO("harness：通道就绪（{}）", detail);
				return;
			}
			// ② 走完一条就开下一条
			if (g_results.size() > g_caseIdx) {
				++g_caseIdx;
			}
			if (g_caseIdx >= g_cases.size()) {
				finishAll();
				return;
			}
			StartCase(g_caseIdx);
			return;
		}

		RunStep(a_menuOpen);
	}
}
