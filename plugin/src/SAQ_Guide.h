#pragma once

// ============================================================================
//  SAQ_Guide —— 「引导到接取任务的地点」的 C++ 侧（DLL <-> ESM <-> Papyrus）
//
//  需求：可接任务列表里选中一条，能让游戏的任务引导系统（任务标记蓝点 +
//        扫描仪路径线）指到「去哪里接这条任务」。
//
//  链路（每一段都能在日志里自证）：
//     AS3（列表选中 + 按键）→ `_root.SAQ_PeekGuide()` 返回 "<序号>|<任务FormID>"
//     → 本模块按任务 FormID 从静态表里取出**引导目标引用**（gen_guide_targets.py）
//     → 写进 ESM 的 GLOB `SAQ_GuideTargetRef`，并把 `SAQ_GuideState` 清 0（=有新请求）
//     → SAQ_Main.psc 轮询到，把该引用 ForceRefTo 到代理任务的别名 SAQ_GuideTarget、
//       显示目标 10、把代理任务设为「追踪中」
//     → 引擎于是画出标记与路径线
//
//  ## 为什么用 GLOB 而不是别的通道
//
//  SFSE 的接口只有 QueryInterface/Messaging/Trampoline/Menu/Task —— **没有** SKSE 那种
//  ModCallbackEvent（能直接给 Papyrus 发事件）的通道。所以 DLL→Papyrus 只能靠
//  「引擎自己认得的持久对象」：GLOB 是最简单的一种（一个 float）。
//
//  ## 怎么找到自己的 GLOB（本模块最关键的一步）
//
//  插件在加载顺序里的序号是**运行期才知道**的（MO2 的加载顺序、其它 DLC 都会影响），
//  而 FormID = (序号 << 24) | 记录号，所以不能把 0x02000801 这类值写死。
//  做法：**让脚本给我一个身份锚点** —— SAQ_Main.psc 在 OnInit 里把 `SAQ_Notify`
//  写成魔数 7777（之后每次菜单打开 +1）。DLL 遍历 0x00..0xFF 个前缀，在 0x803
//  上找「值落在 7777..8776 的 GLOB」，命中即为自己的插件；随后同一前缀下的
//  0x801 / 0x802 就是另两个 GLOB。
//
//  锚点顺带把「证据链」补齐了：日志里 `通知=7777` ⇒ ESM 已加载、代理任务在跑、
//  脚本活着；值在涨 ⇒ 脚本看得到任务菜单的开关事件。
//
//  ## 失败的姿态
//
//  认领不到就什么都不写（GLOB 不碰），只在日志里给候选值与原因 —— 引导不可用，
//  但列表、过滤、原版功能全都不受影响。
// ============================================================================

#include <cstdint>
#include <string>

namespace SAQ
{
	namespace Guide
	{
		// ESM 通道的当前状态（每次 EnsureChannel() 都重新读一遍值）
		struct Channel
		{
			bool          resolved{};   // 三个 GLOB 都认领到了
			std::uint32_t prefix{};     // 插件在加载顺序里的序号（FormID 高位）
			float         targetRef{};  // SAQ_GuideTargetRef：目标低 24 位（旧 ESM = 完整 FormID）
			// ★ 第 21 轮：SAQ_GuidePrefix（目标 FormID 的高 8 位）。
			//   -1 = ESM 旧版没有这条 GLOB（此时 targetRef 本身就是完整 FormID）。
			//   拆两半是为了绕开「GLOB 是 float，完整 FormID > 2^24 时精度丢失」的坑。
			float         targetPrefix{ -1.0f };
			std::uint32_t targetFormID{};  // 拼好的完整 FormID（0 = 无引导）—— 上层只读这个
			// SAQ_GuideState：脚本处理结果（0 待处理 / 1 已应用 / 2 取不到 / 3 已清除 / 4 无别名）
			// ★ 第 37 轮：DLL 写值多了 5 = 「待处理 + 应用后打开星图」（SET COURSE 触发）。
			float         guideState{};
			float         notify{};     // SAQ_Notify：7777 + 菜单打开次数
			// ★ 第 20 轮：控制台测试开关（SAQ_TestMode，0x804）。玩家在游戏控制台输入
			//   `set SAQ_TestMode to N` 切换「只显示适合测试的条目」，DLL 每次开菜单读一次。
			//   -1 = 这条 GLOB 不存在（旧 ESM / 还没跑最新 patch_saq_esm.py）⇒ 不过滤。
			float         testMode{ -1.0f };
			std::string   summary;      // 一行日志（认领失败时是诊断信息）
		};

		// 认领 + 读值。认领成功后缓存（后续只是三个 float 读取）。
		Channel EnsureChannel();

		// 写引导目标（a_formID = 0 表示取消引导）。
		// 成功时同时把 SAQ_GuideState 写成一个「待处理」值（0 或 5，告诉脚本「有新请求」）：
		//   0 = 普通请求（脚本应用引导就行）；
		//   5 = ★ 第 37 轮：**玩家按了「设定航线（R）」** —— 脚本应用完引导后还要调用
		//       引擎原生的 `Game.ShowGalaxyStarMapMenuAndPlotToLocation(地点)` 打开星图
		//       （见 SAQ_Main.psc 的状态表与 docs/05 第十一节）。
		//   a_starMap 只由「玩家请求」那条路传 true；内部路径（重发 / 动态更新 /
		//   静默更新 / 自动取消）一律 false —— 那些不是玩家在要航线。
		bool SetGuideTarget(std::uint32_t a_formID, std::string& a_detail, bool a_starMap = false);

		// 丢掉认领结果（换存档/换加载顺序后用；正常流程不需要）。
		void ResetChannel();
	}
}
