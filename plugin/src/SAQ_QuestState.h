#pragma once

// ============================================================================
//  SAQ_QuestState —— 读 TESQuest 的**运行时状态**（引擎自己的判据）
//
//  为什么需要它：需求里「已经接了的任务不显示」「进度没到不显示」都要看引擎
//  侧的真实状态；而 commonlibsf 的 TESQuest 几乎是空的
//  （只有一个 IsStageDone，而且 REL::ID = 0 —— 一碰就弹 "Invalid ID: 0" 的框）。
//
//  ★ 这一版的做法：**不猜偏移，直接看引擎自己怎么写**。
//  Papyrus 的 Quest 脚本原生函数（IsRunning / IsCompleted / IsActive / …）在
//  Starfield.exe 里的实现就是几行「读 TESQuest 某个字段、测某一位」的小函数，
//  把它们的反汇编抄下来，就得到了权威的字段偏移与位含义：
//
//    TESQuest + 0x114  dword  —— 运行时标志位
//        bit 0  = 已开始（in "running" state）
//        bit 1  = 已完成
//        bit 7  = 正在停止
//        bit 11 = 被玩家追踪（IsActive / SetActive）
//    TESQuest + 0x32C  byte   —— 停止/换代的过渡标志（IsRunning 要求它为 0）
//    TESQuest + 0x338  qword  —— 排队中的启动数据（IsRunning 要求它为 0）
//
//  依据（反汇编，tools/re/quest_api_scan.py 可复现）：
//    IsRunning   实现 RVA 0x20CDCA0 =  bit0 && !bit7 && [0x338]==0 && [0x32C]==0
//    IsCompleted 实现 RVA 0x20CDC30 =  (flags >> 1) & 1
//    IsActive    实现 RVA 0x20CDC20 =  (flags >> 11) & 1
//    IsStarting  实现 RVA 0x20CDCE0 =  bit0 && (bit7 || [0x338] || [0x32C])
//    IsStopping  实现 RVA 0x20CDD20 = !bit0 && bit7
//    IsStopped   实现 RVA 0x20CDD40 =  (byte[0x114] & 0x81) == 0
//  （Quest 脚本类型的原生函数注册表：RVA 0x20CC000 起，名字→实现见
//    ref/quest_natives2.txt；TESQuest 虚表 RVA 0x4BD80D8 / 0x4BD8410，
//    由 tools/re/rtti_slots.py --name "TESQuest@@" 得出。）
//
//  安全设计：读之前先核对对象的虚表指针 == 模块基址 + 上面两个 RVA 之一，
//  对不上就当「未识别」，**不做任何过滤**（宁可不滤，也不能误滤）。
// ============================================================================

#include <cstdint>
#include <string>

namespace RE
{
	class TESForm;
}

namespace SAQ
{
	struct QuestRuntimeState
	{
		bool           readOk{};         // 字段读出来了（没有访问违例）
		bool           vtableKnown{};    // 虚表命中已知 TESQuest 虚表 ⇒ 对象身份可信
		std::uintptr_t vtable{};         // 实测虚表值（未命中时留证据用）
		std::uint32_t  flags{};          // TESQuest + 0x114
		std::uint64_t  startPending{};   // TESQuest + 0x338
		std::uint8_t   stopFlag{};       // TESQuest + 0x32C
		bool           started{};        // bit0：引擎已经开始（含正在停止）
		bool           completed{};      // bit1
		bool           stopping{};       // bit7
		bool           active{};         // bit11：玩家正在追踪
		bool           running{};        // IsRunning 的完整判据（started 且不在过渡态）
	};

	// 读一个表单的运行时状态。传进来的必须是 QUST（本 MOD 的表只有 QUST，
	// 但函数自己会用虚表再核验一次）。
	QuestRuntimeState ReadQuestRuntimeState(const RE::TESForm* a_form);

	// 「引擎侧已介入」的判据：已经开始（含已完成）。
	//
	// ★ 第 11 轮起**不再用作「可接」过滤**（实测反例：RAD05「全数到期」）：
	//   引擎会把「玩家仍能从 NPC 接到」的任务提前置成 running ——
	//   「已开始」≠「已接取」。现在可接列表的判据是：
	//     C++ 只挡「已完成」；「已接取」只认玩家任务日志（AS3 侧的 QuestData 比对）。
	//   本函数保留给诊断与将来的新用途。
	bool IsAlreadyEngaged(const QuestRuntimeState& a_state);

	// 日志用的一行摘要，例如 "开始+追踪 flags=0x401" 。
	std::string Describe(const QuestRuntimeState& a_state);
}
