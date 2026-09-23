#pragma once

// ============================================================================
//  SAQ_Masters —— 「插件名 + 记录号」→ 运行期 FormID（DLC / 多 master 支持的底座）
//
//  为什么需要它：静态表是在**离线**构建时生成的，那时只知道
//      「这条任务来自 ShatteredSpace.esm 的第 0x000116C7 条记录」；
//  而运行期 FormID 的高字节是**加载顺序**（有没有别的插件、MO2 怎么排、DLC 装没装），
//  只有游戏自己知道。离线写死 FormID 的后果：换个加载顺序，整张表指向别的记录。
//
//  ★ 第 18 轮：解析方式从「读 TESDataHandler::files」改成 **前缀探测**。
//    原因（两次实测）：commonlibsf 的 TESDataHandler 结构体偏移在本游戏版本上
//    不可信 —— formArrays 读到空表（第 5 轮，docs/02），第 17 轮新用的 files
//    成员同样读到空链表（09:40 实测日志：四个 master 全「未加载」，而游戏 Data
//    目录里它们都在、ESM 通道前缀=0x0F 证明 16+ 插件已加载）⇒ 整张表被误判成
//    「master 全未加载」。**凡是 commonlibsf 硬编码的结构体偏移，都不要用。**
//
//    前缀探测不碰任何结构体布局，只用**已实测可靠**的引擎接口：
//      TESForm::LookupByID(FormID)（按 ID 问引擎要表单，第 5 轮起就在用）
//      + 虚表核验（SAQ_QuestState::ReadQuestRuntimeState，确认查到的对象是 TESQuest）。
//
//    算法（详见 SAQ_Masters.cpp）：
//      1. 从静态表取属于该 master 的记录号（去重 + 等距采样 ≤6 条）；
//      2. 阶段 1：用样本扫全空间找候选 ——
//           full  插件：FormID = prefix << 24（prefix 0x00..0xFC）；
//           medium 插件：FormID = 0xFD000000 | (mediumIndex << 16) | local16
//                        （0x000..0xFF；★★ 第 110 轮，样本 = SFBGS003 追踪者联盟）——
//                        与 full 段**同一样本一起扫**（medium 的 16 位记录号在别的 full
//                        插件里可能撞号，单靠 full 命中会误判 ⇒ 两个 tier 都收候选）；
//           light 插件：FormID = 0xFE000000 | (smallIndex << 12)（0x000..0xFFF，
//                        只在前两段一个都没命中时才扫）；
//         能查到且虚表是 TESQuest ⇒ 候选（先命中的样本即停）；
//      3. 阶段 2：把该 master 的**全部**记录按候选前缀数一遍命中率，
//         取最高者；≥90% ⇒ 认定（序号/命中率写进日志，如 `记录命中 22/22`），
//         否则该 master 当「未加载」（不显示、不报错，留一条 WARN 作证据）。
//
//    自检锚点：Starfield.esm 必须解析出 0x00（基础游戏永远是第一个 master）。
//    不满足 ⇒ 打 WARN 作证据，且**不缓存**结果（下次打开菜单重试，避免把
//    「游戏尚未就绪」这种瞬时状态钉死成「表里什么都没有」）。
//
//  没装 / 没启用的 DLC：探测不到 ⇒ 那批条目**整批跳过**（日志里注明条数），
//  玩家没有那个 DLC 时什么都不会发生。
//
//  成本：已加载的 full master ≈ 253 次扫描 + 全量确认（≤261 次）LookupByID；
//  未加载的 master 最多再扫 medium（256 次）+ light 空间（4096 次）—— 都在
//  毫秒级以内；且一次游戏运行内加载顺序不会变 ⇒ 解析成功后做会话级缓存。
// ============================================================================

#include <cstddef>
#include <cstdint>
#include <string>

namespace SAQ::Masters
{
	struct Master
	{
		const char*   name{};          // kQuestMasters[] 里的名字
		bool          loaded{};        // 探测到了（当前加载顺序里有它）
		bool          small{};         // light / ESL 类插件（前缀 0xFE000000 | idx<<12）
		bool          medium{};        // ★★ 第 110 轮：medium / ESH 类（0xFD000000 | idx<<16）
		std::uint32_t index{};         // 序号（fullIndex / mediumIndex / smallIndex，日志用）
		std::uint32_t prefix{};        // 前缀（full：idx<<24；medium：0xFD|idx<<16；light：0xFE|idx<<12）
		std::uint32_t sampleOk{};      // 探测确认：全量记录里的命中数
		std::uint32_t sampleTry{};     // 探测确认：全量记录条数
	};

	// 按当前加载顺序重新解析（菜单打开时调用；读档换了顺序也能跟上）。
	// 只在主线程调用。内部有会话级缓存（基础游戏解析成功后不再重扫）。
	void Refresh();

	// ★ 第 33 轮：本会话「解析成功」了吗？
	//   为什么需要单独问一句：MakeFormID 在未解析时**静默返回 0** —— 菜单关着时做「认领已有
	//   引导」的反查全都会落空，日志里表现为「静态表里没有哪条任务/入口的引导目标是它」
	//   （实机 13:44:09 会话，见 docs/99 一·补十八）。调用方据此区分
	//   「表还没就绪（等会儿再试）」与「目标真的认不出（另一个存档留下的）」。
	bool Resolved();

	std::size_t   Count();
	const Master& Get(std::size_t a_index);

	// master 下标 + 记录号 -> 运行期 FormID；0 = 这个 master 没加载 / 下标越界（调用方跳过这条）
	std::uint32_t MakeFormID(std::size_t a_master, std::uint32_t a_local);

	// 一行摘要（哪些 master 加载了、前缀、探测命中率）—— 每次刷新变化才值得记
	std::string Describe();
}
