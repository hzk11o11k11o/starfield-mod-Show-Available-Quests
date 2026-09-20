#pragma once

// ============================================================================
//  SAQ_Masters —— 「插件名 + 记录号」→ 运行期 FormID（DLC / 多 master 支持的底座）
//
//  为什么需要它：静态表是在**离线**构建时生成的，那时只知道
//      「这条任务来自 ShatteredSpace.esm 的第 0x0116C7 条记录」；
//  而运行期 FormID 的高字节是**加载顺序**（有没有别的插件、MO2 怎么排、DLC 装没装），
//  只有游戏自己知道。离线写死 FormID 的后果：换个加载顺序，整张表指向别的记录。
//
//  做法（全部来自引擎自己的数据，不猜）：
//    1. TESDataHandler::files 是当前加载的插件列表（BSSimpleList<TESFile*>）；
//    2. TESFile::fileName 是插件名，TESFile::fileFlags 里的 kSmall 表示 light(ESL)，
//       TESFile::fileIndex 里的 fullIndex / smallIndex 就是「这个插件在 FormID 里的序号」
//       （引擎自己解析 FormID 时用的就是它）；
//    3. 于是
//         普通插件：FormID = (fullIndex << 24) | local
//         light    ：FormID = 0xFE000000 | (smallIndex << 12) | local（local 只有 12 位）
//    4. **抽样自校验**：每条 master 从表里挑几个记录号，按上面算出来的 FormID 问
//       TESForm::LookupByID，再核对虚表是不是 TESQuest —— 命中率进日志。
//       算错了（位宽/序号不对）会在日志里立刻显示成「样本 0/6」，而不是默默给错数据。
//
//  没装 / 没启用的 DLC：查不到对应的 TESFile ⇒ 那批条目**整批跳过**（日志里注明条数），
//  玩家没有那个 DLC 时什么都不会发生。
// ============================================================================

#include <cstddef>
#include <cstdint>
#include <string>

namespace SAQ::Masters
{
	struct Master
	{
		const char*   name{};          // kQuestMasters[] 里的名字
		bool          loaded{};        // 当前加载顺序里有它
		bool          small{};         // light / ESL 类插件
		bool          supported{};     // 序号方案已知（medium / blueprint 暂不支持）
		std::uint32_t index{};         // 引擎给的序号（日志用）
		std::uint32_t prefix{};        // 已 << 24 的前缀（small 时是 0xFE000000）
		std::uint32_t sampleOk{};      // 抽样自校验：命中数
		std::uint32_t sampleTry{};     // 抽样条数
	};

	// 按当前加载顺序重新解析（菜单打开时调用；读档换了顺序也能跟上）。
	// 只在主线程调用。
	void Refresh();

	std::size_t   Count();
	const Master& Get(std::size_t a_index);

	// master 下标 + 记录号 -> 运行期 FormID；0 = 这个 master 没加载 / 下标越界（调用方跳过这条）
	std::uint32_t MakeFormID(std::size_t a_master, std::uint32_t a_local);

	// 一行摘要（哪些 master 加载了、前缀、抽样自校验结果）—— 每次刷新变化才值得记
	std::string Describe();
}
