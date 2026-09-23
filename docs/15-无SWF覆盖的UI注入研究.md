# 15 · 无 SWF 覆盖的 UI 注入研究（第 117 轮）

> 2026-09-23 建立。研究问题 = `docs/99` 十一「下一步大项」的**大项 5**：
> 能否**不替换** `Data\Interface\missionmenu.swf`，而把「可接任务」tab 及其功能
> 注入原版（甚至第三方）任务菜单？
> **目的** = 消除与其它改任务菜单 UI mod 的**文件级二选一冲突**。
>
> 本文 = 离线取证 + 路线盘点 + 实验设计 + **实测判读（见第九·补节：U0 ✅ / U1 ❌ 能力边界 /
> U2 待补测 / U3 ✅ ⇒ 路线 A 不终止，下一步探针 v2 / P1.5）** + **探针 v2 落地
> （第九·补二节）** + **探针 v2 实测判读（第九·补三节：五段全 ok = 拦截 + 哨兵写 + U2
> 补测全成立 ⇒ 绕过路径实机确认，下一步 P2 = 原版 SWF 完整 PoC）** + **P2 落地
> （第九·补四节：`ui.research3` = 扩 tab 7→8 / 切 7 拦截哨兵 / `InitializeEntries`
> 列表注入；`build-saq.ps1 -P2` 部署开关 + verify `--p2`）** + **P2 首跑实测判读与修复
> （第九·补五节：五段 ok / 注入段 fail —— 真因 = 注入条目缺 `aObjectives`（原版
> `IsMission` = `hasOwnProperty("aObjectives")` 判定），已修 + verify 加防回归串）** +
> **P2 复跑实测判读（第九·补六节：六段全 ok + 注入段修复一击生效 `entryCount 1→3`
> ⇒ **P2 通过**（「无 SWF 覆盖」形态技术成立）；判据五连全绿；眼睛窗口 8 → 30 秒）** +
> **P2 眼睛判据达成 + 恢复部署（第九·补七节：30 秒窗口内玩家截图 = 第 8 个 tab `SAQ-PoC`
> + 3 条 `SAQ-PoC-Item i` ⇒ 判据 + 眼睛双绿，**P2 完全收口**；已按恢复流程还原部署）** +
> **路线 D 落地（第十节：冲突检测 + 停推降噪 + 玩家 HUD 提示 —— `ProbeChannelIdentity` /
> `SAQ_UiNotice`（0x80E）/ `ProcessUiChannelNotice`；`verify --dev` 全过 + 离线层 3/3；
> 待实机：正常态 43 条防误报 + P2 态正向）** + **功能迁移评估（第十一节 · 第 129 轮 ·
> 纯离线：迁移面按「归宿」分组（原版自带 ≈ 60%）+ 原版字段契约/接管点全清单 + 8 项清单
> 逐项落地设计 + 新增未知点 U5~U9 与探针 v4 设计 + 产品形态三选项（推荐 B 双形态自动切换）
> + 分期计划 P3/P4/P5 与轮次估算 + 风险自检）** + **探针 v4 落地（第十二节 · 第 130 轮：
> `ui.research4` / `ui.research4b` —— 一次问清 U5~U10 + 置灰的数据驱动验证；新发现
> `CreateObject` 带类名可造真 AS3 实例（换按钮 Data 的钥匙）；拆两段（渲染层需帧推进）+
> 拿 REJECT 当靶子（零观感影响 + Enabled 副证）；`verify --dev --p2` **782 行 / 0 MISS**
> + 离线层 4 步 + 正则离线自检；**P2 实验态已部署、待实机**）** + **P2 会话重跑判读
> （十二·补二 · 第 132 轮：3/3 全 PASS —— 两处探针修正验证生效（`接管=ok（回调收到 1 次）`
> / `关菜单入口=ok`）⇒ U5~U10 + 置灰 **全绿** ⇒ **探针 v4 全绿 / P3 立项条件达成**；
> 判据五连全绿）** + **P3-a 产品化 PoC 落地（第十三节 · 第 133 轮：新模块
> `SAQ_UiInject.{h,cpp}` + `ui.inject` —— 真实数据注入（扩 tab + 分时注入 + 引擎快照
> 恢复 + 对账）；离线全绿）** + **实机首跑与两处产品级缺陷修复（十三节实测段 · 第 134/135
> 轮：① 数据生命周期（`g_pending.quests` 被 notOurs 分支清空）② 注入上下文未接线
> （`InjectCtx::list` 从未赋值 ⇒ handler 两条分支全失败））** + **P2 复跑收口
> （十三·补二 · 第 136 轮：**4/4 全 PASS** —— `InjectCtx::list` 接线**一击生效**，
> 五段判据与预测**逐字一致**；判据五连全绿；**P3-a 判据收口**；眼睛 = 第 8 个 tab
> 「可接任务」+ 真实 206 条列表（待玩家确认））**。

## 一 ~ 八、研究初期（问题定义 / 现状回顾 / 离线取证 / 路线盘点 / 技术未知点 / 实验设计 / 迁移清单雏形 / 阶段结论）—— 已迁 `docs/90`

> 第 137 轮瘦身：这八节是研究初期的分析（其结论已被后续全部实测取代）——
> **逐字迁移**到 `docs/90-历史记录（UI注入研究 第117轮初期取证）.md`，保留原文备查。
> ★ 本文后续段落里对「第七节 / 第八节」的引用 = `docs/90` 的同名节。

## 九 ~ 十·补（研究产物 / 探针实测判读 / 路线 D）—— 已迁 `docs/90`

（第 140 轮瘦身：这一段的结论已全部收进下面的 11.x 设计与十三节 —— 原始记录
 迁到 `docs/90-历史记录（UI注入研究 第117轮初期取证）.md` 末尾，便于追溯。）

## 十一、功能迁移评估（第七节清单的落地设计 · 第 129 轮 · 纯离线）

> 触发：第七节结尾的「P2 通过之后才评估功能迁移」+ `docs/99` 十一「下一步候选 ⑦」。
> 本轮**只做评估**（不写产品代码）：① 把 2301 行 AS3 迁移面按「归宿」重新分组；
> ② 把原版菜单对条目对象的**字段契约 / 接管点**取全（决定哪些由原版自动完成、哪些必须我们补）；
> ③ 逐项给出替代机制与**新增未知点**；④ 设计探针 v4（U5~U9）；⑤ 给出产品形态选项、
> 分期计划与轮次估算、风险与自检、决策点。
> 证据目录 = `_tmp_ffdec_base/scripts/`（原版 FFDec 反编译，行号即该目录内文件行号）；
> 迁移面统计工具 = `tools/esm/_tmp_r117_diff_patch.py`。

### 11.0 结论摘要

| 问题 | 评估结论 |
| --- | --- |
| 技术可行性 | ✅ 三个历史硬点已实机通过（扩 tab / 越界拦截 / 列表注入），**剩余的是「工程化 + 接管面」问题，不是可行性问题** |
| 迁移量 | AS3 侧 2301 行 ≠ 要重写的量 —— 其中约 **60% 的功能原版自带**（渲染 / 分组 / 展开 / 详情面板 / 按钮条 / 音效 / 状态恢复），真正要重建的 = **数据构造 + 接管 + 自检**（估计 C++ 新增 2000~3100 行，可删 AS3 2301 行 + SWF 构建链） |
| 关键新发现 | ① 原版 `BSScrollingContainer.GetDataForEntry()` / `selectedEntry` **是 public** ⇒ 引擎任务数据不必靠事件订阅，**直接读列表即可**（原「U6 数据可达性」降级为小问题）；② 按钮回调可**劫持**：`UserEventData.funcCallback` / `sCodeCallback` 都是 public var，`MinimalButton.HandleUserEvent()` 是 public（可在探针里**程序化触发按键路径**验证）；③ 关菜单/回游戏可用 public 的 `MissionMenu.ProcessUserEvent("ReturnToStarMap"/"Missions", false)` |
| 主要风险 | 依赖原版**内部名与结构**（换游戏版本可能静默失效 ⇒ 必须有「结构指纹自检 + 失败回退 + HUD 提示」）；第三方 SWF 若改了 AS3 **逻辑**（不只是布局），注入可能半失效（与第七节「目标档」一致：只承诺「对方保留原版类结构」时叠加生效） |
| 产品形态建议 | **双形态 + 身份探测自动切换**（默认仍走 SWF；第 125 轮的 `notOurs` 判定从「停推 + 提示」升级为「可切注入」）。长期（注入形态判据等价 + 过一个游戏版本周期）可考虑**注入为唯一形态**，彻底删掉 SWF 一套 |
| 下一步 | 实现**探针 v4（`ui.research4`，U5~U9）**，在 P2 态（原版 SWF）跑一次 ⇒ 全绿再做 **P3 产品化 PoC**（真实数据注入，无交互） |

### 11.1 评估前提（已实机成立，不再重复论证）

| 能力 | 证据 |
| --- | --- |
| 定位 `_root.Menu_mc` / 读 public 对象与 getter（`numTabs` / `entryCount` / `filterMask`） | 第 118 轮 U0/U2 |
| 扩 tab：C++ 构造数组 → `TabbedFilterSelection_mc.SetTabsData` → `numTabs` 7→8 | 第 120 轮（P1.5）/ 第 122~124 轮（P2） |
| 越界拦截：`selectionChange` priority=100 + `stopImmediatePropagation` + 自写 `filterMask`（哨兵存活） | 第 120 轮 / 第 123 轮 |
| 列表注入：条目带 `aObjectives` ⇒ 原版认它是 mission 条目，`entryCount` 1→3 且**界面可见**（眼睛） | 第 122~124 轮 |
| 绑定 C++ 回调：`CreateFunction` + `addEventListener(..., priority=100)`，回调真实收到 | 第 118 轮 U3 |
| 身份探测：桥 OK + `SAQ_Report` 无指纹 ⇒ `notOurs`（第三方/原版界面） | 第 125 轮 |

### 11.2 迁移面盘点（2301 行的「归宿」分组）

统计口径：`ui/missionmenu/src/*` 与我们维护的 patch 源；函数行数 = 该函数体行数（脚本统计）。

| 组 | AS3 内容（函数 · 行数） | 注入形态的归宿 | 说明 |
| --- | --- | --- | --- |
| **A 数据 / 载荷 / 文案** ≈ 537 行 | `SaqParsePayload`(99)、`SaqBuildEntry`(77)、`SaqBuildObjective`(36)、`SaqDescriptionText`(109)、`SaqApproachNote`/`SaqCompanionNote`/`SaqNoPickupNote`/`SaqNotNavigablePrefix`/`SaqRepeatablePrefix`/`SaqCourseKeyName`(91)、`SaqSafeType`/`SaqIsEntryType`/`SaqSafeFaction`(37)、`SaqTabTitle`/`SaqApplyTabTitle`(18)、`SaqNameVerdict`/`SaqUseChinese`(60)、`SaqEmbeddedPayload`(10) | **迁到 C++（数据侧）** | 静态表里已有一切原始字段（名字中英 / 说明 / 候选 / 标记）；缺的是「把字段拼成 AS3 条目对象」+ 文案合成。**内嵌回退载荷直接删除**（注入由 DLL 驱动，不再需要 SWF 侧兜底） |
| **B 列表合并 / 过滤 / 掩码** ≈ 130 行 | `BuildMergedList` + `FilterKnownQuests`(77)、`SaqRefresh`(35)、`SaqSyncListMask`(16) | **迁到 C++**（且更简单） | 「已接取任务」判据 C++ 本来就有（`SAQ_QuestState` + `Decision::DecideRuntimeFilter`，含可重复豁免）；列表归属改为**按 tab 分时注入**（见 11.4-⑤），不需要「合并 + ALL 掩码改写」 |
| **C 交互 / 引导** ≈ 470 行 | `SaqToggleGuide`(98)、`SAQ_GuideReply`(85)、`SaqAutoCancelIfAccepted`(35)、`SaqQuestNameByID`(35)、`SaqApplyTrackedMarker`(27)、`SAQ_PeekGuide`(23)、`SaqReturnToGameForStarMap`(23)、`SaqNoteStarMapHandoff`(15)、`SaqQuestName`/`SaqBaseName`(38)、`SaqIsOurEntry`/`SaqEntryTag`(27)、`SAQ_SyncGuideState`(18) + 对 `OnPlotCourseEvent` / `onMissionListItemActivated` 的改造 | **迁到 C++（接管层）**，并**协议全部消失** | 引导逻辑本来就在 DLL（`Guide::`）；注入形态下 C++ 直接调用，`PeekGuide`（100ms 轮询）/ `GuideReply`（回写）/ `SyncGuideState`（同步）/ 推送协议（500ms）**四条通道一起退休** |
| **D 诊断探针** ≈ 430 行 | `SAQ_Report`(165)、`SaqEntryProbe`(40)、`SaqPinNoteProbe`(43)、`SaqRepeatNpcProbe`(56)、`SaqNotNavigableProbe`(47)、`SaqRepeatableQuestProbe`(37)、`SAQ_Probe`(11)、`SaqSnapshotTab`(32) | **改写成 C++ 直读**（约 150~250 行） | 注入形态下「界面状态」全在 C++ 手里（`GetDataForEntry` / `selectedEntry` / `filterMask` / 渲染文本），不必再让 AS3 拼字符串回传 —— 这是**净简化** |
| **E 测试入口** ≈ 202 行 | `SAQ_TestDriveTab/Select/SelectChild/Expand/Key/State`(172)、`SAQ_ApplyPayload`(30) | **删除**，由 harness 直接驱动 GFx | 原语层（`SAQ_TestOps`）已有 `menu.open` / `ui.*` 基础；注入态改用「C++ 注入原语 + 断言」即可 |
| **F 通道 / 发布** ≈ 100 行 | `SaqPublishEntryPoint`(76)、`SetAvailableQuests`(22) + `onAddedToStage` 里的挂载 | **删除** | root 上的 `SAQ_*` 入口是「AS3 侧提供服务」形态的产物；注入形态不缺入口 |
| **G 原版函数改造** ≈ 50~80 行 | `PopulateTabs`（ALL 掩码去 bit6 + 第 8 项）、`onFilterChanged`（快照探针）、`ProcessUserEvent`（事件探针）、`onMissionListItemActivated`（分支）、`OnPlotCourseEvent`（改走引导）、构造函数（tab 标题） | **不需要**（原版逻辑保持原样，我们在外面接管） | 这正是注入形态的**收益**：不再 fork 原版函数 |

### 11.3 原版契约（注入形态「必须提供 / 必须接管」全清单）

来源 = 本轮取证（`_tmp_ffdec_base/scripts/`）：

**A. 条目对象必补字段**（给不对就一定出问题）：

| 字段 | 谁读 | 不给的后果 |
| --- | --- | --- |
| `aObjectives`（数组，可空） | `MissionsListEntry.as:42-45`（`IsMission`）、`MissionsList.as:143-156` | 条目**不进列表**（原版树结构只收 mission + divider） |
| `sName` | `MissionsListEntry.as:162-172` | 行文本为空 |
| `iRemainingTime`（int，给 `-1`） | `MissionsListEntry.as:178,241-257` | `undefined` 会渲染 `NaN $$HOURS` 垃圾串 |
| `bComplete`（给 `false`） | `MissionsListEntry.as:178`、`MissionsList.as:52/175/211`、`MissionMenu.as:449/453` | 分组 / 完成 tab / 可追踪判定错乱 |
| `iType`（给 `6`）+ tab 掩码 `1<<6` | `MissionsList.as:215`、`QuestUtils.as:25-44` | **不给 iType 的条目在所有 tab 都可见**（`null` 分支恒真）⇒ 污染原版列表；给了才受掩码管辖 |
| `iFaction`（`-1` 或真实阵营） | `MissionsListEntry.as:186`、`MissionInfo.as:177-178` | 图标与详情面板阵营名缺失 |
| `bActive` | `MissionsListEntry.as:194-208`（左侧竖条）、`MissionMenu.as:600/620/639` | 追踪态不可见（缺省安全 = Inactive） |
| `sDescription` | `MissionInfo.as:191,205` → `MissionDescriptionScrollList.as:125-131` | 详情正文为空（**描述与说明文案全靠它**） |
| `uID` / `uInstanceID` / `uOwnerQuestFormID` / `uIndex` | `MissionMenu.as:553/572/630/680/421`、`MissionsList.as:84/125/225-244` | 追踪/展开态/父任务查找的键 |
| `bCanShowOnMap`（条目自身或 `aObjectives[0]`） | `MissionsListEntry.as:47-59`、`MissionMenu.as:457-458` | SET COURSE / SHOW ON MAP 按钮状态错（**「不可导航 ⇒ 置灰」就靠它**） |
| `bCanBeRejected`（不给 = false） | `MissionMenu.as:456` | REJECT 按钮误亮 |
| 分隔项 `{bIsDivider:true}`（可选） | `MissionsList.as:70`、`MissionsListEntry.as:136-141` | 需要分组时加 |
| `bIsMiscObjective` / `bIsMiscQuest` / `bFailed` / `strFactionIconName`（可选语义） | 见 11.4-③ | 影响点击分发 / 排序 / 图标；**不给更安全** |

> ⚠ 两个「给了反而危险」的字段：`bIsMiscObjective=true` 会让点击走「杂项目标」分支向引擎发
> 未知 `questID` 的 `MissionMenu_ToggleTrackingQuest`（`MissionMenu.as:610-613`）⇒ 我们的
> 条目**不要**设它；`iType` 不设则全 tab 可见（见上表）。

**B. 必须接管的点**：

| # | 接管点 | 原版出处 | 注入形态的做法 |
| --- | --- | --- | --- |
| 1 | 第 8 个 tab 的 `selectionChange`（原版会 `FilterInfoA[7]` 越界 TypeError） | `MissionMenu.as:343-354`、`169-172` | priority=100 监听 + `stopImmediatePropagation` + 自写 `filterMask`（**已实机**） |
| 2 | tab 数组（7 → 8 项，含我们 tab 的标题/掩码） | `MissionMenu.as:242-276` | `SetTabsData(8 项)`（**已实机**）；标题 = 字面量（中/英由 C++ 判定） |
| 3 | 列表内容（我们的 tab 显示我们的条目；其它 tab 保持原版） | `MissionMenu.as:278-303`（每次引擎推送都会 `InitializeEntries` **覆盖**） | **分时注入**：切到我们 tab ⇒ 注入我们的数组；切走 ⇒ 注入「引擎数组快照」；引擎推送用 watchdog 发现后重放（11.4-⑤） |
| 4 | SET COURSE（PC 的 R）/ SHOW ON MAP（Y）按键回调 | `MissionMenu.as:206-207`、`MinimalButton.as:368-388`（`funcCallback()` + `SendEvent(sCodeCallback)`） | **劫持**：保存原 `funcCallback` → 换成我们的 C++ 函数 → 我们的条目走引导、非我们的条目**委托回原函数**；同时把 `sCodeCallback` 换成惰性名，避免引擎收到不存在的 questID |
| 5 | 条目激活（Enter / 鼠标点击） | `MissionMenu.as:586-657`、`MissionsList.as:333-338`（`ITEM_ACTIVATED` 冒泡 + cancelable） | priority=100 监听：我们的条目 ⇒ 拦下（展开 / 引导）；非我们的 ⇒ 放行（`stopImmediatePropagation` 只对自家条目） |
| 6 | 详情面板（选中 → 右侧描述） | `MissionMenu.as:459-466` → `MissionInfo.as:169-216` | **不用接管**：选中我们条目时原版会自动按字段渲染（前提：字段齐全） |
| 7 | 按钮置灰（不可导航 ⇒ 灰） | `MissionMenu.as:457-458` | **不用接管**：`bCanShowOnMap=false` 即置灰；点击提示走 HUD 通道（`SAQ_UiNotice`，第 125 轮已有） |
| 8 | 关菜单 / 回游戏 / 星图交接 | `MissionMenu.as:371-390`（`ProcessUserEvent` **public**）、509-532 | `Invoke(Menu_mc,"ProcessUserEvent",["ReturnToStarMap"\|"Missions", false])`（后者 = 回游戏渲染，脚本侧再开星图） |
| 9 | 引导态同步（竖条 + 取消跟踪） | `MissionsListEntry.as:194-208`（`bActive`）、`MissionMenu.as:1732-1755`（自动取消） | C++ 自己维护「当前引导的 uID」⇒ 改 `bActive` + 就地刷新该行（11.4-⑦）；接到任务 ⇒ 自动取消（C++ 已有玩家日志） |
| 10 | 上次分类恢复（可能恢复到我们的 tab） | `MissionMenu.as:705-722` | 打开序列必须在「状态恢复事件」之前完成（**时序风险**，见 11.8-④） |

**C. 原版自带（不需要我们做）**：条目 clip 创建/复用/滚动/裁剪、文本截断与 `$` 本地化键、
名字/图标/时间字符串格式、树形展开折叠与分隔项跳过、分组与 divider 清理、过滤链本身、
详情面板布局与滚动、按钮条构建/排版/键名/hover 帧、tab 创建与宽度自适应、菜单音效、
焦点管理、打开/关闭/状态保存。「只显示已追踪」由**引擎**执行（AS3 只发开关事件）。

### 11.4 第七节 8 项清单：逐项落地设计

| # | 第七节原项 | 注入形态的做法（现状 → 结论） | 难度 | 依赖 |
| --- | --- | --- | --- | --- |
| ① | 载荷解析 / 合并列表 | 由 C++ 构造 AS3 条目数组（`CreateArray` + `PushBack` + 每项一个 `Object`），**不再有协议字符串**；「合并」改为 tab 分时注入 | 低 | — |
| ② | 排序（同伴 / 势力 / 可重复 / 入口固定） | 已是 C++ 数据侧（`Decision::PinnedOrderKey`，有离线单测）—— 数组顺序 = 我们的顺序（原版 `MissionsList.InitializeEntries` 对「未完成组」保持输入序） | 低 | — |
| ③ | 名称前缀（（不可导航）/（可重复）） | 数据侧拼 `sName`（前缀逻辑从 `SaqNotNavigablePrefix` / `SaqRepeatablePrefix` 搬过来） | 低 | — |
| ④ | 描述文案 / 简要说明 | 数据侧拼 `sDescription`（`SaqDescriptionText` 109 行的等价物 + note 三来源）；**注意**：正文是纯文本（`MissionDescriptionScrollList.as:125`），HTML/换行行为要跟现状对齐 | 低~中 | — |
| ⑤ | 列表过滤 | 不用 `bSaqAvailable`（那是我们 SWF 的扩展字段，原版没有）—— 改为 `iType=6` + 我们 tab 掩码 `1<<6`；「已接取/已完成」过滤在 C++ 完成（含可重复豁免）。**放弃「合并 + 改 ALL 掩码」**：改用分时注入，ALL tab 行为与原版**逐字一致** | 低 | — |
| ⑥ | 点击 / 双击 / 引导 / 跟踪 | 接管点 4/5/8/9（按钮劫持 + 激活拦截 + `ProcessUserEvent` 关菜单 + `bActive`） | **中** | **U5**（劫持实机验证） |
| ⑦ | 「不可导航」点击不闪烁 / SET COURSE 置灰 | `bCanShowOnMap=false` ⇒ 按钮自动置灰（原版逻辑）；点击提示走 HUD 中英文案（`SAQ_UiNotice` 通道已有） | 中（低） | — |
| ⑧ | 诊断探针 / 测试入口 | 探针改 C++ 直读（`GetDataForEntry` / `selectedEntry` / `filterMask` / 渲染文本字段）；测试入口删掉，harness 直接调注入原语 | 中（净简化） | **U7**（局部刷新）/ **U8**（渲染文本读取） |

### 11.5 新增未知点（U5~U9）与探针 v4 设计

| # | 未知点 | 为什么关键 | 判据（探针汇总行字段） |
| --- | --- | --- | --- |
| **U5** | 按钮回调**劫持**：读 `ButtonBar_mc.<Btn>_mc.Data.UserEvents`（public）→ 保存 `funcCallback` → 换成我们的 `CreateFunction` 函数 → 用 **public 的 `MinimalButton.HandleUserEvent("XButton",false,false)`** 程序化触发按键路径 | 决定「R = 设定航线 / 引导」这条主交互能否迁移 | `劫持=ok（回调收到 1 次）` + `还原=ok（还原后再触发，计数不变）` |
| **U6** | 引擎数据**直接读**：`MissionsList_mc.GetDataForEntry(i)`（public）能拿到引擎条目对象及其字段 | 决定「切走我们 tab 时恢复原版列表」能否实现（不必再靠事件订阅） | `读条目=ok（N 条，首条 uID/sName/字段非空）` |
| **U7** | 就地刷新：`GetClipByIndex(i).itemIndex` ↔ 我们的下标，`clip.SetEntryText(条目对象)` 改 `bActive` 后**渲染文本**是否更新 | 决定「切换引导态不重建列表」（否则每次按 R 列表会跳回顶部） | `刷新=ok（竖条帧名 N→M）` + `文本=<读回的名字>` |
| **U8** | 渲染文本读取（`TextField.text`）：用于 ① 验收（描述/名字真的显示）② **语言判定**（读一条原版本地化文本，含 CJK ⇒ 中文） | 语言判定在注入形态下没有 AS3 任务名可看，必须另找通道 | `文本=ok（…非空）` + `语言=zh\|en`（由采样文本判定） |
| **U9** | 菜单关闭原语可调用性：`Invoke(Menu_mc,"ProcessUserEvent",["SAQ_Research",false])` 返回 `false` 且无副作用（**不真关菜单**，真关留到 P4 用驱动器验证） | 决定「引导后交接星图」的关菜单路径 | `关菜单入口=ok（返回 false，未关闭）` |

**探针形态**（沿用第 117/119/121 轮纪律）：新 op `ui.research4`，**只在 `SAQ_WITH_HARNESS` 构建里存在**，
只在 P2 态（`build-saq.ps1 -P2`，原版 SWF）跑，结果一行汇总（红线六）+ 产品日志取证；
判据正则顺序固定，防拆散后漏段。

### 11.6 产品形态：三个选项

| 选项 | 形态 | 收益 | 代价 | 评估 |
| --- | --- | --- | --- | --- |
| **A** 维持现状（SWF 覆盖 + 路线 D 检测提示） | 已发布形态 | 零新成本、判据最足 | 文件级冲突仍在（用户二选一），第三方面板 mod 用户只能看提示 | 可接受，但**没解决 docs/15 的目标档** |
| **B** 双形态 + 身份探测**自动切换**（推荐） | 默认 SWF；`ProbeChannelIdentity ⇒ notOurs` 时按 ini（默认开）切注入 | 冲突场景下**功能照常可用**；不必立刻换默认形态；注入路径与 SWF 路径**共用**同一份数据/引导/决策逻辑 | 过渡期两套展示层要同时维护；注入层需要独立判据（harness 侧） | ★ 推荐过渡态：把第 125 轮的「停推 + 提示」升级为「切换 + 提示」 |
| **C** 注入为唯一形态（删 SWF） | 净减 2301 行 AS3 + 构建链（FFDec/双份源码/lrg/`stamp=`/内嵌载荷）+ 补丁同步纪律 | 彻底消除文件冲突；诊断/测试入口大幅简化 | 依赖原版内部结构（换版本风险）；**丢掉「与第三方 SWF 完全无关」这一优势**（第三方改 AS3 逻辑时我们受影响）；需要一轮完整的判据等价验证 | 长期目标，触发条件 = 注入形态判据与现 R 判据等价 + 过一个游戏版本周期无回归 |

### 11.7 分期计划与工作量估算

| 期 | 范围 | 主要产物 | 判据 | 轮次 |
| --- | --- | --- | --- | --- |
| **探针 v4** | U5~U9（见 11.5） | `ui.research4` + P2 计划 +1 条用例 + verify 特征串 | 判据链全 ok + 产品日志一行 + 离线层全绿 | **1 轮** |
| **P3 产品化 PoC** | 真实数据注入（tab + 掩码 + 条目构造 + 描述/前缀/排序/置灰 + 分时注入 + watchdog）**不含交互** | 新模块（建议 `SAQ_UiInject.{h,cpp}`，与 `SAQ_UI` 分文件）、`ui.inject` 原语、用例 2~3 条、verify +N | 原版 SWF 上：`entryCount == 期望`、`GetDataForEntry` 字段逐项对账、描述/名字读回一致、切走 tab 后原版列表恢复（条目数回到引擎数） | **2 轮** |
| **P4 交互接管** | 按钮劫持（X/Y）+ 激活拦截 + 引导态竖条 + 就地刷新 + 自动取消 + 星图交接（关菜单）+ 不可导航提示 + 诊断/测试入口迁移 | 接管层代码 + 用例（引导 A/B、取消、置灰、HUD 提示）+ verify +N | 判据与现「UI 通道」用例等价（引导状态、`bActive`、结果码、星图打开） | **2~3 轮** |
| **P5 双形态与发布** | 身份探测升级（notOurs ⇒ 切注入）、ini 开关、结构指纹自检 + 失败回退、日志/文档、打包 | 发布形态决策 + 文案 + 0.1.1x 包 | 正常态 43 条等价全绿 + P2 态注入用例全绿 + 眼睛 | **1~2 轮** |

**净代码量估算**（实现期）：注入内核 ≈ 600~900 行；条目构造 + 文案合成 ≈ 400~600 行；
交互接管 ≈ 300~500 行；自检/降级/日志 ≈ 150~250 行；harness 原语与用例 ≈ 300~500 行；
verify / 离线层改造 ≈ 200~400 行（并删除一批 SWF 专属检查）。
**可删**：AS3 2301 行（若走选项 C）、内嵌载荷、`build-saq.ps1` 的 SWF 步骤、`make_lrg_source.py`、双份 patch 同步。

### 11.8 风险与自检（即使注入成立也要处理的）

| # | 风险 | 处置 |
| --- | --- | --- |
| ① | 依赖原版**内部名 / 结构**（`Menu_mc`、`TabbedFilterSelection_mc`、`MissionsList_mc`、`Data.UserEvents`、`ProcessUserEvent`…）；换游戏版本若改名 ⇒ 注入**静默失效** | 打开序列做**结构指纹自检**（关键成员逐个 `HasMember` + `numTabs==7` + 按钮 `Data` 可读）——任一失败 ⇒ 不注入 + 一行 WARN + HUD 提示 + 走既有「停推」路径（不闪退、不半残） |
| ② | 第三方 SWF 改了 AS3 **逻辑**（不是布局） | 与第七节「目标档」一致：只承诺布局/资源类改动下叠加生效；指纹自检能挡住大部分（成员缺失/类型不对） |
| ③ | 我们的条目被引擎推送**覆盖** | watchdog（菜单开着时低频检查「首条是否我们 + 条数是否期望」）⇒ 重放注入（见 11.4-⑤） |
| ④ | **时序**：`MissionMenuStateData` 恢复「上次分类」（可能 = 我们的 tab 7）发生在我们的打开序列之前 ⇒ 原版 `FilterInfoA[7]` TypeError | 打开序列尽量早（菜单「由关变开」当拍完成 SetTabsData + 装监听）；必要时提高菜单存在性检查频率；evaluating 期先量化「恢复事件 vs 我们注入」的实际先后（P3 首跑日志） |
| ⑤ | 语言判定（注入形态没有 AS3 任务名可看） | U8 探针（读一条原版本地化渲染文本判 CJK）+ ini `[UI] Language=auto\|zh\|en` 兜底 |
| ⑥ | 引导态切换时的列表重建导致滚动/选中丢失 | U7 就地刷新（按 clip ↔ 下标映射 `SetEntryText`）；退化方案 = 重建 + 恢复 `scrollPosition` / `selectedIndex` |
| ⑦ | 双形态维护期成本 | 把差异**收敛在一层**：数据 / 决策 / 引导 / 提示全部留在现有 C++，只有「展示 + 接管」两套；SWF 侧不再加新功能（功能只进注入层，SWF 侧冻结） |

### 11.9 决策点（建议）

1. **本轮结论**：注入形态**值得推进**（技术可行性已被 P2 证完，剩余为工程化；且顺带带来「协议退休 + 诊断简化 + 可删 SWF 一套」的长期收益）；
2. **建议下一步 = 探针 v4**（1 轮，低风险、纯只读优先），把 U5/U6/U7/U8/U9 一次问清；
3. 探针 v4 全绿 ⇒ 进 **P3**（产品化 PoC，先只做数据不做交互，便于单独判定）；
4. 产品形态按 11.6 **选项 B** 起步（默认 SWF + 检测到冲突自动切注入），**选项 C** 作为长期目标，
   触发条件写进 `docs/99`；
5. 若探针 v4 出现红灯：U5 红 ⇒ 交互层退化为「Enter 激活引导 + 其余降级」；U6/U7 红 ⇒ 退化为
   「重建列表 + 恢复滚动/选中」；都不影响 P3 立项，只影响 P4 的实现路径。

## 十二、探针 v4 落地（2026-09-23 · 第 130 轮；`ui.research4` / `ui.research4b`）

**目标**：把第十一节列的 5 个未知点（U5~U9）+ 两项顺带取证（U10 类通道、`bCanShowOnMap`
⇒ SET COURSE 置灰）在**原版 SWF**（P2 态）上一次问清。判据纪律 = **「有结论」而不是
「必须全 ok」**（能力边界失败也有对应 fallback，见 11.4-⑥）：三项能力边界（类通道 /
造对象 / 接管）用 `(ok|fail)` 宽匹配，其余关键段（读条目 / 注入 / 选中 / 置灰 / 刷新 /
文本 / 关菜单入口）必须 ok。

**产物**：

| 层 | 产物 | 说明 |
| --- | --- | --- |
| DLL | `plugin/src/SAQ_UI.{h,cpp}` 的 `ResearchGfxInjection4` / `…4b` | **harness 段内**（发布构建零残留，verify 反向检查覆盖）；各打一行产品日志（红线六） |
| op | `plugin/src/SAQ_Test.cpp`：`ui.research4` / `ui.research4b` | 复用 `Kind::kUiResearch`（`step.text` = `4` / `4b`），timeout 10 s |
| 计划 | `tools/test/scenarios/SAQ_TestPlan_p2.txt`：`[case:r130_gfx_migrate]` | 三段断言（4a 首行 + 八段同现；4b 首行 + 三段同现）+ 帧推进窗口 `wait 1200` + 眼睛窗口 30 s；计划头同步更新 |
| verify | +8 条 DLL 特征串（dev 正向 / 发布反向）+ 6 条 P2 计划形状检查 | 含「CreateObject 类名」「读条目=」「造对象=」「类通道=」「刷新=」等判据标记 |
| 离线自检 | `tools/test/p2_plan_regex_check.py`（第 130 轮新建、入库） | P2 计划全部 `assert.log` 正则**编译** + 新增两段与**样例产品行匹配**（补 verify 只查存在性、不查正则语义的缺口） |

**判据链**（一次跑完，逐段读回验证）：

| 段 | 动作 | 判据字段 |
| --- | --- | --- |
| 4a-R1 | 环境（`entryCount` / `filterMask`）+ `List` / `ButtonBar` 可达 | `Menu_mc=ok` + `环境=(…)` |
| 4a-R2 | **U6**：`GetDataForEntry(0)` 读首条（uID / iType / sName / 8 个字段存在性）+ `selectedEntry` | `读条目=ok（N 条,首条 0x…:类型…:名…:字段8｜选中项=0x…）` |
| 4a-R3 | **U8a**：首条名字的 CJK 统计（与 SWF 版 `SaqNameVerdict` 同源） | `语言=zh（中文样本 N 字）/ en / ?（无样本）` |
| 4a-R4 | **U10**：`loaderInfo.applicationDomain.getDefinition("…BSUIDataManager")` → 静态 `hasEventListener("QuestData")` → `Subscribe("QuestData", C++ 函数)` | `类通道=ok（BSUIDataManager）｜静态=ok（…）｜订阅=ok` |
| 4a-R5 | **U5**：① 读 `Data`（protected，预期 fail）；② `CreateObject` 带类名造三级真实例（UserEventData → UserEventManager → ButtonBaseData）；③ `SetButtonData` 换到 REJECT 按钮（`Enabled` true→false = 被接受）；④ `RefreshButtonData` 复位；⑤ `HandleUserEvent("R3",false,false)` 程序化触发 | `读Data=…｜造对象=…｜接管=ok（回调收到 1 次 —— R 键可接管）` |
| 4a-R6 | 列表注入（2 条真实字段集：`aObjectives` 空数组 / `iRemainingTime=-1` / `bActive=false` / **`bCanShowOnMap` 0 与 1**）+ `selectedIndex` 读写 | `注入=ok（entryCount N→2）｜选中=ok（0x…）｜置灰=ok（不可导航=0，可导航=1）` |
| 4b-R1 | **U7**：`GetClipByIndex(i).itemIndex` ↔ 数据下标 → 改条目 `bActive` → `clip.SetEntryText(条目)` | `刷新=ok（竖条 Inactive→Active）` |
| 4b-R2 | **U8b**：读 clip 的 `MissionVisuals_mc.TextField_tf.text_tf.text` | `文本=ok（SAQ-Mig-0）` |
| 4b-R3 | **U9**：`Invoke(Menu_mc,"ProcessUserEvent",["SAQ_Research",false])` + 菜单仍在 | `关菜单入口=ok（返回 false，菜单仍在=是）` |
| 4b-R4 | U10 收口：订阅回调计数（会话内无新推送 ⇒ 0 正常） | `订阅回调=N 次` |

**本轮新发现（值得记住的 GFx 能力）**：`ASMovieRootBase::CreateObject(Value*, const char*
className, const Value* args, numArgs)` —— **带类名即造 AS3 类实例**（commonlibsf 的
0x2E 槽本来就带 `className` 参数，第 117 轮只用了无参形式）。这是 GFx 侧**唯一**能拿到
「真 `ButtonData` 实例」的路子：`MinimalButton.Data` 是 **protected trait**（读不到 ——
与 U1 同类边界），没有实例就换不了按钮回调。类名候选 = 全名 / 短名 / `::` 分隔三种写法
（探针逐个试，命中写法进日志 —— 三种写法本身也是要测的内容）。

**两个设计选择**：
- **为什么拆两段**：U7 是**渲染层**证据 —— clip 的 `itemIndex` 由
  `BSScrollingContainer.Update` 在**帧推进**时写，注入与读回之间必须隔一帧
  （计划里 `wait 1200`）；其余各项都是对象/数据层，同一次调用内完成。
- **为什么拿 REJECT（R3）当接管靶子**：它平时不可见（`bVisible=false`），探测期间
  被换 Data 对玩家无观感影响；`Enabled` 初值 = true ⇒ 换成 `bEnabled=false` 后读回
  false = **「实例被接受并被 AS3 侧读取」的副证**；随后复位 + public 的
  `HandleUserEvent` 触发 ⇒ 我们的 `funcCallback` 被调用 = R 键可接管的硬证据。
  副产品：`sCodeCallback` 会被换成惰性名 —— 即使接管成功也不会把「未知 questID」发给引擎。

**副作用（仅本次会话；随 `menu.close` 清理 —— 第 27/50 轮定案）**：注入 2 条
`SAQ-Mig-0/1`（`filterMask=1<<6`，其它 tab 不可见）；REJECT 按钮的 Data 被换成探针实例；
`Subscribe("QuestData")` 注册了一个回调（进程内残留、无副作用）。

**离线验证（全绿）**：
- 构建部署：DLL 开发构建（harness）**1116160 B**（1083392 → +32768）；**P2 实验态**
  （`Interface/missionmenu.swf` / `_lrg.swf` → `*.p2off`；ini `Harness=1` +
  `Plan=SAQ_TestPlan_p2.txt` + `AutoLoad=Save1_FDBB7678M54696D6D6568_000034_20260922142854_2_0_4`）；
- `verify --dev --p2`：**782 行 / 0 MISS / 全部通过**（含本轮 8 条 DLL 特征串 dev 正向
  + 6 条 P2 计划形状 + `*.p2off` 禁用证据 + `AutoLoad` 一致性）；
- 离线层 `run-all-tests.ps1` **5 步全过**（第 5 步 = 本轮新建的 P2 计划正则自检；决策单测
  本轮可执行 —— 第 128 轮的「环境拦截 exe」未复现；快照 16 件一致；tripwire「表内 leak 0」）；
- 断言正则自检 `tools/test/p2_plan_regex_check.py`：7 条正则编译全过 + 新增两段匹配样例行。

**待实机（下一次 P2 会话：`r120_gfx_poc` + `r125_ui_conflict` + `r130_gfx_migrate`）**：

| 段位 | 字段 | ok 的含义（→ 对 `docs/15` 十一节的影响） |
| --- | --- | --- |
| 4a | `读条目=ok` | 引擎条目直读可用 ⇒ **分时注入**（切走我们 tab 时恢复原版列表）与「选中项是不是我们的」判据成立（U6 ✅） |
| 4a | `语言=zh/en` | 语言判定有通道（引擎任务名 CJK）；`?` = 存档里一条任务都没有（罕见）⇒ 加 ini 兜底 |
| 4a | `类通道=ok` + `静态=ok（hasEventListener）` | `BSUIDataManager` 可达 ⇒ ① `Subscribe("QuestData")` 替代 watchdog 轮询；② `dispatchCustomEvent` 可用于**委托原版行为**（换按钮 Data 后仍保留真实任务的原版语义） |
| 4a | `造对象=ok（三级）` | `CreateObject` 带类名可用 ⇒ 换按钮 Data 的**钥匙**拿到（记住日志里的命中类名写法） |
| 4a | `接管=ok（回调收到 1 次）` | **R 键可接管** ⇒ 保持 SWF 版 UX（一键设定航线）；`fail` ⇒ 走 fallback：`bCanShowOnMap=false`（SET COURSE 置灰）+ 父条目 Enter = 引导（11.4-⑥） |
| 4a | `注入=ok` / `选中=ok` | 真实字段集条目注入 + 选中判据（P3 的验收手段） |
| 4a | `置灰=ok（不可导航=0，可导航=1）` | 「不可导航 ⇒ SET COURSE 置灰」是**数据驱动**的（11.4-⑦ 成立，不需要接管按钮） |
| 4b | `刷新=ok（竖条 Inactive→Active）` | 就地刷新成立 ⇒ 引导态切换**不重建列表**（不跳滚动位置、不丢展开态） |
| 4b | `文本=ok（SAQ-Mig-0）` | 渲染文本可读 ⇒ 验收手段（也能读描述面板，兼作 U8 收口） |
| 4b | `关菜单入口=ok` | `ProcessUserEvent` 可调 ⇒ 星图交接（关菜单 + 回游戏）有正门（U9 ✅） |
| 4b | `订阅回调=N 次` | 类通道订阅生效（会话内无新推送 ⇒ 0 正常；>0 = 引擎推送也收到了） |

**眼睛**：`r130` 用例的 30 秒窗口里，列表应显示 2 条 `SAQ-Mig-0/1`；选中一条时右侧
描述面板 = `sDescription` 字段（Probe 用 ASCII 文案，避免英文环境缺中文字形）；
`menu.close` 后重开 = 原版数据（副作用清理）。

## 十二·补、P2 会话判读与探针修正（2026-09-23 18:29 会话 · 第 131 轮）

**会话**（P2 实验态 · 原版 SWF · 开发 DLL 1116160 B · `Plan=SAQ_TestPlan_p2.txt`）：
3 条用例 = `r120_gfx_poc` **PASS**（42313 ms）/ `r125_ui_conflict` **PASS**（4750 ms）/
`r130_gfx_migrate` **FAIL**（13375 ms）—— 唯一 FAIL = 4b 的 `关菜单入口=ok` 断言
（探针判据写错，见下）。**眼睛**：玩家看到列表 **2 条 `SAQ-Mig-0/1`** ⇒ 与
`注入=ok（entryCount 1→2）` 逐项一致（判据 + 眼睛双达成）。

**探针 v4 判读（实测行 → 结论）**：

| 段 | 实测 | 结论 |
| --- | --- | --- |
| 4a | `读条目=ok（1 条,首条 0x00003448:类型1:名=一小步:字段8｜选中项=0x00003448）` | **U6 ✅** 引擎条目直读成立（分时注入 / 「选中项是不是我们的」判据可用） |
| 4a | `语言=zh（中文样本 3 字）` | **U8a ✅** 语言判定有通道（引擎任务名 CJK） |
| 4a | `类通道=ok（BSUIDataManager）｜静态=ok（hasEventListener=false）｜订阅=ok`；订阅回调立即收到 1 次（18:31:16.035） | **U10 ✅** 类通道 + 静态调用 + `Subscribe("QuestData")` 全通（可替代 watchdog；引擎推送也收到了） |
| 4a | `造对象=ok（三级）`（当时判据只查「造出来是 object」） | 三级实例都造出来了 —— 但**接线错了**（见修正①；新判据补 `接线 UserEvents=1`） |
| 4a | `接管=fail（刷新=ok 触发=fail 回调=0 次 Enabled=1）` | **探针缺陷（非能力边界）**：`SetButtonData` 被接受（Enabled 1→0→1 副证成立）+ `RefreshButtonData` ok，但 `HandleUserEvent("R3")` 调用失败、回调 0 次 —— 真因 = 旧版把 `UserEventManager` **实例**当 param2 传给 `ButtonBaseData`；原版 ctor 只接受 **UserEventData 或 Array**（其它类型 `TraceWarning` 忽略 ⇒ `UserEvents=null` ⇒ `HandleUserEvent` 里 `this.Data.UserEvents.CallForMatchingData` 空引用） |
| 4a | `注入=ok（entryCount 1→2）`（2 条真实字段集） | 判据成立（P3 验收手段）+ 与眼睛一致 |
| 4a | `选中=ok（0x56780001）｜置灰=ok（不可导航=0，可导航=1）` | **U10b ✅** `bCanShowOnMap` ⇒ SET COURSE 置灰是**数据驱动**（11.4-⑦ 成立，不需要接管按钮） |
| 4b | `刷新=ok（竖条 Inactive→Active）` | **U7 ✅** 就地刷新成立（不重建列表） |
| 4b | `文本=ok（SAQ-Mig-0）` | **U8b ✅** 渲染文本可读（验收手段） |
| 4b | `关菜单入口=fail（返回 true，菜单仍在=是）` | **探针判据错（非能力边界）**：原版 `MissionMenu.ProcessUserEvent` 末尾把返回值**覆盖**为 ButtonBar / TabbedFilterSelection 的结果 —— 未知事件返回 true 属正常且无副作用；真正的关菜单 = 传 `"ReturnToStarMap"` / `"Missions"`（留 P4） |
| 4b | `订阅回调=1 次` | 类通道订阅生效（会话内有引擎推送） |

**两条修正（第 131 轮 · 探针侧，产品零改动）**：
1. `SAQ_UI.cpp` `ResearchGfxInjection4`（U5）：`ButtonBaseData` 的 param2 改传**事件数组
   `[ud]`**（原版正典写法 `new ButtonBaseData("$REJECT",[new UserEventData("R3",fn)],…)`），
   并**读回 `data.UserEvents.NumUserEvents`** 作接线证据（日志 `造对象=ok（三级 + 接线
   UserEvents=1）`）；`UserEventManager` 的创建/读回保留为独立能力证据（`NumUserEvents=1`）。
2. `SAQ_UI.cpp` `ResearchGfxInjection4b`（U9）：判据改「**可调用 + 无副作用（菜单仍在）**」，
   返回值只作信息记录（`关菜单入口=ok（可调用=是；菜单仍在=是；返回 true，真关菜单留 P4）`）。

**判据链结论**：U6 / U7 / U8 / U10 / 置灰 **✅ 全绿**；U5 机制**未证否**（接线缺陷掩盖，
修正后预期 ok）；U9「可调用」**✅**（真关菜单留 P4）。⇒ **P3 立项不受阻**；
下一步 = 重跑 P2 会话（3 条用例）验证 `接管=ok` + `关菜单入口=ok`（4b 断言过）。

**验证（全离线全绿）**：DLL 开发构建 **1117184 B**（+1024）；P2 实验态重新部署
（`*.p2off` + `Harness=1` + `Plan=SAQ_TestPlan_p2.txt` + `AutoLoad=…142854_2_0_4`）；
`verify --dev --p2` **784 行 / 0 MISS / 全部通过**（+1 条特征串「接线 UserEvents=」——
dev 正向 / 发布反向，防「改回传 Manager 实例」再犯）；离线层 **5 步全过**；
`p2_plan_regex_check.py` **7 条正则编译 + 4 条样例匹配全过**。

## 十二·补二、P2 会话重跑判读（2026-09-23 18:41 会话 · 第 132 轮）

**会话**（P2 实验态 · 原版 SWF · 开发 DLL 1117184 B · `Plan=SAQ_TestPlan_p2.txt`）：
3 条用例 = `r120_gfx_poc` **PASS**（42343 ms）/ `r125_ui_conflict` **PASS**（4968 ms）/
`r130_gfx_migrate` **PASS**（33328 ms）—— **3/3 全 PASS（P2 会话首次全量全绿）**。

**判读（实测行 → 结论；对照第十二节「待实机」预期表逐项吻合）**：

| 段 | 实测 | 结论 |
| --- | --- | --- |
| 4a | `读条目=ok（1 条,首条 0x00003448:类型1:名=一小步:字段8｜选中项=0x00003448）` | **U6 ✅**（与上轮逐字一致） |
| 4a | `语言=zh（中文样本 3 字）` | **U8a ✅** |
| 4a | `类通道=ok（BSUIDataManager）｜静态=ok（hasEventListener=false）｜订阅=ok` | **U10 ✅** |
| 4a | `读Data=fail（Data 是 protected trait —— 与 U1 同类边界）` | **预期 fail（边界确认）** —— 第十二节 R5 明示「读 protected，预期 fail」；换按钮 Data 的钥匙仍是 `CreateObject` 造实例 |
| 4a | `造对象=ok（三级 + 接线 UserEvents=1）` | ★ **修正①生效**：新判据「接线 `UserEvents=1`」首次实测成立（防「再传 Manager 实例」回归） |
| 4a | `接管=ok（回调收到 1 次 —— R 键可接管）`；硬证据行「接管回调收到（第 1 次，argCount=0）」（18:43:59.371 「界面研究探针4」） | ★★ **U5 ✅ 机制成立**（上轮 FAIL → 一击修复）：`funcCallback` 被程序化触发调用 ⇒ R 键可接管 ⇒ 保持 SWF 版 UX（一键设定航线）有路 |
| 4a | `注入=ok（entryCount 1→2）` | 判据成立（P3 验收手段） |
| 4a | `选中=ok（0x56780001）` | ✅ |
| 4a | `置灰=ok（不可导航=0，可导航=1）` | **U10b ✅**（数据驱动，11.4-⑦ 成立） |
| 4b | `刷新=ok（竖条 Inactive→Active）` | **U7 ✅**（就地刷新，不重建列表） |
| 4b | `文本=ok（SAQ-Mig-0）` | **U8b ✅** |
| 4b | `关菜单入口=ok（可调用=是；菜单仍在=是；返回 false，真关菜单留 P4）` | ★★ **U9 ✅**（上轮判据错 → 修正生效：「可调用 + 无副作用」成立；返回 false 与第十二节 R3 判据吻合；真关菜单 = 传 `"ReturnToStarMap"` / `"Missions"`，留 P4） |
| 4b | `订阅回调=1 次` | 类通道订阅生效（与上轮一致） |

**结论**：**U5 / U6 / U7 / U8 / U9 / U10 + 置灰 全绿** —— 第十二节「待实机」表的 ok 判据全部达成
⇒ **探针 v4 全绿 ⇒ P2 会话收口 ⇒ P3 立项条件达成**（第十一节 11.9 决策点 3：探针 v4 全绿 ⇒ 进 P3）。
下一步 = **P3 产品化 PoC（2 轮，只做数据）**；之后 P4 交互接管（含真关菜单原语）→ P5 双形态与发布。

**判据五连（全绿）**：`check_results` **3/3**（退出码 0）+ `log_hygiene` 退出码 0（日志
**44939 B / 104 行 / 94 I / 10 W / 0 E** 零坏字节；[W] 10 = 3 个菜单周期 ×「UI 通道不可用」
系列（含第 1 个周期多一条「UI 桥解析失败」）= P2 实验态预期现象 —— 原版 SWF 下产品推送必然
失败、第 125 轮停推判定正常工作）+ `plan_regex_audit` P2 计划 **8/8** + `verify --dev --p2`
**784 行 / 0 MISS** + 离线层 **5 步全过**（19 用例 / 936 断言 + 折叠自检 + 快照 16 件 +
tripwire + P2 正则自检 7 条）。

**产品侧**：与基线同型 —— 静态表 280 / 引擎存在 280 / 待推送 206 / 入口 21（可导航 21）/
可重复 21（排末尾 19）/ 进度门槛 7(过1/藏6) / INFO 门槛 80(过52/藏25/放行2) / 链式 68(过2/藏64)。

**眼睛（玩家已确认）**：r130 的 30 秒窗口内列表 **2 条 `SAQ-Mig-0/1`** —— 与
`注入=ok（entryCount 1→2）` 逐项一致（判据 + 眼睛双达成）。

**下一步（第 132 轮 · 玩家已定）**：**直接进 P3 产品化 PoC** —— 并附一条硬要求：
★ **必须保持「随时返回 SWF 版本」的能力**。落地口径（P3 起执行）：
① 注入层独立成模块（`SAQ_UiInject.{h,cpp}`，与 `SAQ_UI` 分文件）+ **运行期开关**
（ini `[UI] UiMode=swf|auto|inject`，默认 `auto`；`swf` = 行为与现状逐字节不变、注入代码
不激活）；② SWF 覆盖文件与构建链**不删不动**（P3~P5 期间两形态并存，P5 才决策发布形态）；
③ 部署侧沿用两态切换（`build-saq.ps1 -P2` 实验态 ↔ 不带 `-P2` 常规态）。

## 十三、P3-a 产品化 PoC（第 133 轮）—— 已迁 `docs/91`

（第 144 轮瘦身：P3-a 已完全收口 —— 判据见十四 / 十五节；原始记录（链路八步 /
 新事实 / 判据）迁到 `docs/91-历史轮次记录（第120~124轮）.md` 末尾，便于追溯。）

## 十四、P4 交互接管（2026-09-23 · 第 140 轮；按钮劫持 X/Y + activate 拦截 + 星图交接）

### 14.0 前置：眼睛判据达成 ⇒ P3-b 完全收口

第 139 轮留的「待玩家点头」已闭合：三个 30 秒窗口（r133 再注入 / r137 激活 / 玩家手动窗口）
+ 玩家手动一次，**第 8 个 tab「可接任务」+ 真实任务列表（真任务名 / 真描述）都看到了**
⇒ P3-b（注入形态产品化：auto 自动激活 + watchdog + `UiMode` 开关）完全收口，
「随时可回 SWF」纪律不变（`swf` 档行为逐字节不变）。

### 14.1 接管面（三处交互 + 两个视觉）

| 交互点 | 原版实现 | 我们的接管（注入形态） |
| --- | --- | --- |
| X（SET COURSE）`PlotToLocationButton_mc` | `OnPlotCourseEvent` → `MissionMenu_PlotToLocation` | 我们的条目 ⇒ 引导 + 星图交接；原版条目 ⇒ **逐行复刻**其 dispatch 委托 |
| Y（SHOW ON MAP）`ShowOnMapButton_mc` | `OnShowOnMapEvent` → `MissionMenu_ShowItemLocation` | 我们的条目 ⇒ 只为它设引导（不开星图）；原版条目 ⇒ 同上委托 |
| 条目激活（Enter / 点击）`MissionsList::itemActivated` | `onMissionListItemActivated`（追踪/展开） | 我们的条目 ⇒ `stopPropagation` 拦下 + 子项切换引导；原版条目 ⇒ 完全放行 |
| 「引导中」竖条（TrackIndicator） | 条目 `bActive` 帧名 `Active/Inactive` | `bActive` = 当前引导（`SAQ::CurrentGuideQuestID`）+ **就地刷新**（U7 手法） |
| 按钮置灰 | `onMissionSelectionChange` 按 `CanShowOnMap` 写 `Enabled` | 不动原版逻辑 —— 我们的条目靠**数据字段**驱动（见 14.5，第 130 轮已实测） |

### 14.2 按钮劫持：为什么是「换 + 委托」而不是「保存-还原」

- 原版 `PlotToLocationButton_mc.Data` 是 **protected trait**（U5 实测：读不到 ⇒ 保存不了）。
- 换法：`CreateObject` 带类名造我们的 `UserEventData` + `ButtonBaseData`（label 用**原版
  label 键** `$SET COURSE` / `$SHOWONMAP` —— 按钮文本与本地化仍跟原版走，不写死）→
  `SetButtonData` → `RefreshButtonData`。
- **接线证据**：读回 `data.UserEvents.NumUserEvents == 1`。为什么坚持读回：第 131 轮的教训
  （`ButtonBaseData` 的 param2 只认 `UserEventData` 或 `Array`，传 Manager 实例会被
  `TraceWarning` 静默忽略 ⇒ `UserEvents=null` ⇒ `HandleUserEvent` 空引用 "造出来是个 object" ≠ 能触发）。
- **置灰态**：换 Data 前读下按钮当前 `Enabled`、换完写回（不抹掉原版按当前选中条目算好的状态；
  之后每次选中变化由原版照常重写）。
- 原版条目：**逐行复刻原版 AS3 的 dispatch**（`_tmp_ffdec_base/scripts/MissionMenu.as` 的
  `OnPlotCourseEvent` / `OnShowOnMapEvent`：`IsMission(entry) ? {uID,-1} : {uOwnerQuestFormID,uIndex}`
  + 事件名 + `MISSION_SHOW_ON_MAP_SOUND`）—— 与原版行为等价，且不依赖读不到的原 Data。

### 14.3 activate 拦截（Enter / 点击）

- 事件名 `MissionsList::itemActivated`（原版 `MissionsList.onEntryPress` 的最后一步：
  `super.onEntryPress(); dispatchEvent(new Event(ITEM_ACTIVATED,true,true))`），
  监听挂 **MissionsList_mc**、priority=100。
- ★★ **决定判据设计的关键事实**：原版 `BSScrollingTree.onEntryPress` 对「有子项的条目」
  **只做展开/收起、不派发 `itemActivated`** —— 真正会走激活事件的是**叶子行**。
  ⇒ ① 数据构造必须带子项（14.5）；② 探针必须用**子项行**验证这条链（R3/R4 如此）。
  （同理：我们的主条目行按 Enter = 原版树的展开/收起，天然正确。）
- 我们的条目 ⇒ `stopPropagation`（阻断冒泡到 `Menu_mc` 上的原版 `onMissionListItemActivated`
  —— 它会给引擎发**不存在的 questID**）；子项 = 切换引导，主条目 = 不做别的（展开已完成）。
- 原版条目 ⇒ 完全放行（不拦、不动作）—— 「原版条目走原版路」是这一层的第一原则。

### 14.4 星图交接 = 真关菜单原语

- **用**：`Menu_mc.ProcessUserEvent("Missions", false)` = 原版 `onCloseSubMenuToGame` →
  `CloseMenu(true)` → 时间轴 Close → `GlobalFunc.CloseAllMenus()`：**整个暂停菜单**一起关
  + `StartGameRender()` ⇒ 游戏恢复运行。
- **不用** `"ReturnToStarMap"`：它走 `OnCancelEvent` → `CloseMenu(false)` → 只关任务菜单**一层**，
  会停在暂停菜单里 ⇒ 脚本定时器继续冻结 ⇒ 星图永远打不开（第 131 轮 U9 的判据也记录了这条）。
- 链路：结果码 0 且要星图 ⇒ 关菜单 ⇒ 脚本节拍恢复（`SAQ_Main` 的 ApplyGuide 待办）
  ⇒ 下一个轮询打开星图（DLL 侧 `RequestStarMapOpen(formID, swfCloses=true)` 不发 kHide —— 与 SWF 同协议）。

### 14.5 数据构造补齐：P3 的最小集 → P4 的完整形态

- 每个主条目带 **1 条子项**（`aObjectives`，与 SWF 版 `SaqBuildObjective` 同源：任务板 /
  可重复 NPC / 普通任务三档子项名）。
- ★★ `MissionsListEntry.CanShowOnMap(parent)` 对「有子项的主条目」取的是
  **`aObjectives[0].bCanShowOnMap`** ⇒ 子项这个字段必须 = 这条能不能导航。
  **忘了它 = SET COURSE / SHOW ON MAP 永远置灰**（功能上等同坏掉，且不报错）。
- 子项字段：`uID` / `uOwnerQuestFormID` = 主条目 uID、`uIndex=0`、`iType=6`、`iFaction=-1`、
  `bIsMiscObjective=false`、`bCanShowOnMap=bSaqHasTarget`；**不带 `aObjectives`**（否则会被
  `IsMission` 当成任务、再次进根列表）。
- 我们的标记：`bSaqAvailable`（诊断）/ `bSaqHasTarget`（点击决策，与按钮置灰同源）/
  `bActive`（竖条）。

### 14.6 引导与竖条（复用同一条产品路径）

- `ApplyGuideRequest` 改**返回结果码**（0=成功 / 1=没有引导目标 / 2=写通道失败 /
  3=静态表里没有 / 5=目标尚未加载）；SWF 路径照旧靠回写（返回值忽略），注入路径直接拿返回值。
- `NotifyGuideReply(a_seq < 0)` **短路**：注入形态没有 AS3 协议侧，否则每次按键刷一条 WARN。
- 新公开 API：`SAQ::RequestGuideFromInject(formID, wantMap, toggleCancel)` +
  `SAQ::CurrentGuideQuestID()` —— 注入形态**复用整条产品引导路径**（候选池挑选 / ESM 通道 /
  结果确认 / 星图待办 / 接取后自动取消），不重建任何一半。
- 按键语义（与 SWF 版逐条对齐）：X = 引导 + 请求星图（**永不取消** —— 第 39 轮定案）；
  Y = 只为它设引导（不开星图）；Enter 子项 = 切换（同一条再按 = 取消）；
  不可导航 ⇒ OFF 音 + 日志、**不发请求**（按钮本来就灰；名字带「（不可导航）」前缀 + 描述写明原因）。
- 竖条：`bActive` = 当前引导 + **就地刷新**（逐个可见 clip → `itemIndex` ↔ 数据下标 →
  `SetEntryText`；不重建列表 ⇒ 不丢滚动 / 展开态）；watchdog 每拍先同步（外部变化也会反映：
  接取后自动取消引导 / 认领存档里的引导）。

### 14.7 判据（离线全绿）与待实机

- 新 harness op **`ui.interact [key X|key Y|state]`**（harness 专用；产品路径不依赖它）：
  · 无参 = 接管判据链（**dry-run**：装接管 → 分类 → dry 触发 X/Y → 激活拦截，一行汇总
    `接管= / 分类= / 触发= / 激活= / 真动作=0`）；
  · `key X|Y` = 真按键（选中我们的第一条可导航条目 → 走**真实回调** → 引导 + 星图交接）；
  · `state` = 只读状态（任务菜单 / 星图 / 注入 / 接管 / 当前引导 / 按压计数）。
- 新 P2 用例 **`r140_interact_takeover`**（三段判据 = 探针 dry-run / 真按键 + 星图入口 /
  端到端 `星图=开`）；P2 计划 5 → **6 条**。
- 离线证据：DLL 开发构建（harness）**1206272 B**（+44544）+ `verify --dev --p2` **859 行 / 0 MISS**
  （+29 条：13 条产品串 dev/release 双向、8 条 harness 串、P2 计划形状 11 条）+ 离线层 5 步全过
  （P2 正则自检 **18 条 / 15 样例**）。
- 回归判据（产品日志）：`界面注入：已激活（…，接管=ok）` /
  `菜单关闭：交互接管（X … ／ Y … ／ 激活 …｜拦下 …｜委托 …｜引导请求 …）`。
- **待实机（P2 会话 6 条**：r120 / r125 / r130 / r133 / r137 / **r140**）；眼睛 = 第 8 个 tab 里
  展开子项 + 按 X 真的打开星图。

### 14.8 风险与后手

- 换 Data 那一刻的按钮状态：只保证「不改变原版算好的状态」；此后由原版每次选中变化重写。
- Y 键语义：我们的条目没有「引擎地图位置」可显示 ⇒ 定为「只为它设引导」（不开星图）。
- 真按键会真的关掉整个暂停菜单（这正是「星图交接」要验的行为）⇒ 用例把它放在最后，
  清场（清引导 / 关任务菜单 / 关星图）由驱动器自动做（第 55 轮）。
- 接管安装失败不致命：注入照常工作、交互退回原版行为，只记一行 WARN（不阻塞出货形态）。

## 十四·补、r140 实机判读与探针修复（2026-09-23 21:11~21:14 会话 · 第 141 轮）

### 14·补.1 判读：6 用例 5 PASS / 1 FAIL（会话 236203 ms · P2 实验态 · 原版 SWF）

| 用例 | 结果 | 关键判读行 |
| --- | --- | --- |
| `r120_gfx_poc` | ✅ 42266 ms | 干净 7 tab 恢复（`扩tab=ok（7→8）`）+ 五段全 ok + `注入=ok（1→3）`（第 138 轮 `ui.mode swf` 隔离继续生效） |
| `r125_ui_conflict` | ✅ 4797 ms | `UI 通道不可用（第 2 次推送失败后判定）` + 无「推送放弃」；★ 同周期产品 auto 自动激活（`接管=ok`） |
| `r130_gfx_migrate` | ✅ 33344 ms | 4a 全绿（读条目 / 语言 / 类通道 / 造对象 / `接管=ok（回调 1 次）`/ 注入 / 选中 / 置灰）+ 4b `刷新=ok / 文本=ok / 关菜单入口=ok` |
| `r133_inject_data` | ✅ 32328 ms | 五段与第 136 轮逐字同型：`上下文=ok｜快照=ok（1 条）｜扩tab=ok（7→8）｜注入数据=ok（1→206，期望 206）｜对账=ok（0x002C5401:超越极限）｜恢复=ok` |
| `r140_interact_takeover` | ❌ 10171 ms | **唯一 FAIL**：`界面接管 Menu_mc=ok｜接管=fail（ButtonBar_mc 取不到）` —— 探针一行即止（分类 / 触发 / 激活 / 真按键三段没跑到） |
| `r137_product_inject` | ✅ 37313 ms | `界面注入：已激活（UiMode=auto，tab 7→8，条目 206，按键名=(空)，语言=zh，**接管=ok**）` + `菜单关闭：本轮为注入形态（watchdog 重放 0 次）` + 交互计数全 0 |

### 14·补.2 r140 真因 = 探针路径 `ctx.menu` 未接线（与第 135 轮 `ctx.list` 同一类）

- **对照证据（一次会话内同时出现）**：探针 `接管=fail（ButtonBar_mc 取不到）`（21:13:23.184）
  **vs** 产品路径两处 `界面注入：已激活（…，接管=ok）`（21:12:09.495 / 21:13:32.889 ——
  产品 `InstallTakeover` 成功）⇒ 不是环境 / 能力问题，是「谁接了 `ctx.menu`」：
  · `ActivateForMenu`（产品路径）：`ctx.menu = menu;`（第 140 轮已接）；
  · `RunInjectPoC`（探针 `ui.inject`）：只接了 `ctx.list`（第 135 轮）——
    `ctx.menu` 保持默认构造的空 `Value` ⇒ `SafeValueGetMember(&ctx.menu, "ButtonBar_mc")` 失败。
- `ctx.menu` 是 `ui.interact` 三处的**共同锚点**：接管安装（`ButtonBar_mc` 取 X/Y 按钮）/
  分类切 tab（`TabbedFilterSelection_mc`）/ 星图交接（`ProcessUserEvent("Missions")`）。
- 影响面：仅 harness 探针（注入本身与产品路径不受影响 —— 产品 `接管=ok` 实证）。

### 14·补.3 修复（第 141 轮，三处）

1. `RunInjectPoC`：补 `ctx.menu = menu;`（快照前、与 `ctx.list` 同段）；
2. **上下文自检升级**：`｜上下文=ok` 改为「list + menu 双证据」（fail 时写明
   `list=?,menu=?`）—— 第 135 轮「上下文自检」教训的推广（同类缺陷以后一眼可见）；
3. `tools/ui/verify_saq_build.py`：新增源码计数检查 `ctx.menu = menu;` **恰好 2 处**
   （产品 + 探针各自接线；少一处 = 那条路径必失败 —— 与第 135 轮 `ctx.list` 同款纪律）。

### 14·补.4 P2 计划调整：眼睛窗口去除（玩家要求 —— 判据已全部确认）

- `r120` / `r130` / `r133` 的 30 秒「眼睛窗口」（`wait 30000`）已去除 —— 这三个窗口在
  星图交接用例 `r140` **之前**，判据（含眼睛）全部确认完毕，复跑不再需要人工观察
  （要看时对相应用例临时加回 `wait 30000`）。
- `r137`（星图交接之后的用例 · 产品路径形态）的 30 秒窗口**保留**。

### 14·补.5 判据（离线全绿）与待实机

- DLL 开发构建（harness）**1206272 B**（SHA256 `B2FCFA4F…BCB376`；工作区 == 部署；
  新格式串已在二进制里核对）；P2 实验态已重新部署（`*.p2off` + ini `Plan` 指向 P2 计划）。
- `verify --dev --p2` **860 行 / 0 MISS**（含新检查 `ctx.menu = menu; 恰好 2 处（实测 2 处）`）；
- 离线层 **5 步全过**（P2 正则自检 18 条 / 15 样例）；
- 会话判据：`check_results` **5/6** + `log_hygiene` 退出码 0（251041 B / 663 行零坏字节）+
  `plan_regex_audit` 19 断言 / 6 段（5 条未命中 = r140 FAIL 同源）。
- **待实机 = P2 会话 6 条重跑**（预期 6/6 —— r140 的其余三段首跑没跑到）+ 眼睛 =
  第 8 个 tab 里展开子项 + 按 X（R 键）真的打开星图。

## 十四·补二、r140 修复复跑 6/6 全 PASS + 眼睛判据全部去除（2026-09-23 21:23~21:24 会话 · 第 142 轮）

### 14·补二.1 判读：6 用例 6 PASS / 0 FAIL（会话 145532 ms · P2 实验态 · 原版 SWF）

| 用例 | 结果 | 关键判读行 |
| --- | --- | --- |
| `r120_gfx_poc` | ✅ 12375 ms | 干净 7 tab + `扩tab=ok（7→8）` + `切3=ok｜切7=ok（拦截 1 次）｜切0=ok｜清理=ok｜注入=ok（1→3）` |
| `r125_ui_conflict` | ✅ 4953 ms | `UI 通道不可用（第 2 次推送失败后判定）` + 无「推送放弃」 |
| `r130_gfx_migrate` | ✅ 3282 ms | 4a 全绿（`读条目=ok｜语言=zh｜造对象=ok（三级 + 接线 UserEvents=1）｜接管=ok（回调收到 1 次）｜注入=ok｜选中=ok｜置灰=ok`）+ 4b `刷新=ok｜文本=ok｜关菜单入口=ok` |
| `r133_inject_data` | ✅ 2109 ms | 五段全 ok（`上下文=ok｜快照=ok（1 条）｜扩tab=ok（7→8）｜注入数据=ok（1→206，期望 206）｜对账=ok（0x002C5401:超越极限）｜恢复=ok（→1）`）+ `再注入=ok（→206）` |
| `r140_interact_takeover` | ✅ 6328 ms | **第 141 轮修复一次通过**：`接管=ok（X=ok Y=ok｜接线 1/1｜激活监听=ok）｜分类=ok（我们 1｜原版 1｜无选中 1）｜触发=ok｜激活=ok（回调 1 次／拦下 1 次）｜真动作=0`；真按键 = `按键=X｜回调=1 次｜引导=ok（0x002C5401）｜星图交接=已调用`；端到端 = `星图=开` |
| `r137_product_inject` | ✅ 37500 ms | `界面形态：UiMode=auto` + `界面注入：已激活（UiMode=auto，tab 7→8，条目 206，接管=ok）` + `菜单关闭：本轮为注入形态（watchdog 重放 0 次）` |

### 14·补二.2 眼睛判据全部去除（玩家要求：「测试完成开始检查，所有眼睛判据都可以去掉，可以不用看了」）

- **P2 计划**：`r120` 关菜单后 10 秒静默期（第 127 轮的提示观察窗口）+ `r137` 30 秒窗口删除
  ⇒ 加上第 141 轮已去的 `r120/r130/r133` 30 秒窗口，**全计划零人工观察**（要看界面时对相应
  用例临时加回 `wait 30000` / `wait 10000` —— 计划注释里已写明）。
- **探针与注释**：`｜眼睛=请切到第 8 个 tab 看真实列表` 输出删除；`再注入={}（…，供眼睛）`
  → `（…，可重入）`（该段保留 = 注入可重入复核：切走后再切回仍能注入）；`SAQ_UiInject.h` /
  `SAQ_UiInject.cpp` / `SAQ_UI.cpp` 的「眼睛窗口」注释全面改写 ⇒ 代码 / 工具 / 计划零
  「眼睛」残留（docs 历史记录保留原文）。
- **verify 同步**：特征串改钉 `｜再注入=`（替换原「眼睛=请切到…」检查项）+ 新增反向检查
  「P2 零人工观察窗口」（`step` 行里不许出现 `wait 30000` / `wait 10000`）；
  `tools/test/p2_plan_regex_check.py` 的样例文本同步（`供眼睛` → `可重入`）。

### 14·补二.3 判据（离线全绿）

- DLL 开发构建（harness）**1206272 B**（SHA256 `3E43FC22…`；工作区 == 部署；P2 实验态已重新部署）。
- `verify --dev --p2` **859 行 / 0 MISS**（含「再注入判据标记」+「P2 零人工观察窗口」两项新检查）。
- 离线层 **5 步全过**（决策单测 19 用例 / 936 断言；P2 正则 18 条 / 15 样例）。
- 会话判据：`check_results` **6/6**（退出码 0）+ `log_hygiene` 退出码 0（日志 347021 B /
  901 行零坏字节；结果 JSON 19263 B 干净）。
- 下一步 = **P5 双形态与发布**（「随时可回 SWF」纪律不变）；可选 = 零人工观察版 P2 6 条复跑
  （预期 6/6，时长约 −40 秒）。

## 十五、P5 双形态与发布（2026-09-23 · 第 143 轮）

### 15.1 范围（第十一节 11.7 表的 P5 行）

| 项 | 状态 |
| --- | --- |
| 身份探测升级（notOurs ⇒ 切注入） | ✅ 第 137 轮已落地（`UiMode=auto`：SWF 推送失败判定 notOurs ⇒ 自动切注入） |
| ini 开关（`[UI] UiMode=swf\|auto\|inject`） | ✅ 第 137 轮已落地（默认 auto；改完关开菜单生效） |
| **结构指纹自检 + 失败回退** | ✅ 本轮（第 143 轮）落地 —— 见 15.2（本节核心） |
| 日志 / 文档 | ✅ 本轮（失败 WARN + 激活行 `指纹=ok` + 本节） |
| 打包（0.1.16） | 见 15.5（待实机判读后执行） |
| 判据 | 正常态 43 条等价全绿 + P2 态注入用例全绿（6 条，含新增指纹断言）+ 眼睛 —— 见 15.4 |

### 15.2 结构指纹自检 + 失败回退（11.8 风险① 的落地）

**要解决的问题**：注入形态依赖原版 `MissionMenu` 的**内部名与结构**（`Menu_mc` /
`TabbedFilterSelection_mc` / `MissionsList_mc` / tab 数组 7 项 —— 我们的 tab 文本表按
7 项**硬编码**）。游戏版本更新若改了这些，注入会「静默失效」或更糟 ——「半残」：
例如原版加到 8 个 tab 时按 7 项处理，会把别的 tab 名写错。

**设计**（取向 = 宁可不提供功能，也不半残；判据 = 离线层纯函数，可单测枚举）：

| 场景 | 判定（`Decision::DecideUiFingerprint`） | 行为 |
| --- | --- | --- |
| 全齐（menu + tabSel + list + `numTabs == 7`） | `kOk`（**不论宽限期** —— 结构已就绪就直接放行，正常路径零额外时延） | 正常激活（激活行尾 `指纹=ok`） |
| 缺项 + 宽限期内（菜单刚打开、结构没建好） | `kWait` | 静默重试（既有 150 ms 激活节流） |
| 缺项 + 超宽限期 | `kNoMenu` / `kNoTabSel` / `kNoList` / `kTabCount`（依赖链顺序） | **不注入**：一行 WARN + `activateFailed`（本菜单周期不再重试）+ HUD 提示走既有「延迟判定」兜底（3 秒 → 「UI 通道不可用」） |

- 宽限期 `kFingerprintGraceMs = 1500`（起点 = `UiInject::OnMenuOpened`，SAQ.cpp 在
  菜单打开时调用）—— 实测桥 ~0.3~1 秒就绪、产品路径 ~1.2 秒内激活成功 ⇒ 1.5 秒留足余量；
  宽限期内**绝不**判失败（把「还没建好」误判成「结构不匹配」会把正常环境挡在门外）。
- 失败 WARN 文案（含「本次菜单不注入、不再重试」+「功能保持不可用，不会半残」——
  verify 特征串钉住）：`界面注入：结构指纹不匹配（原版 tab 数不是 7 项）—— …`。
- **按钮三件套**（`ButtonBar_mc` / `PlotToLocationButton_mc` / `ShowOnMapButton_mc`）属
  **软项**：缺失 ⇒ 接管安装失败 WARN（第 140 轮既有行为），注入照常（交互退化为原版）
  —— 不进硬指纹。11.8 原文提的「按钮 `Data` 可读」在 U5 已实测为 protected trait、
  读不到（第 131 轮），硬判据改为「接管安装结果」。

**产物**：

| 层 | 产物 |
| --- | --- |
| 离线层 | `SAQ_Decision.{h,cpp}`：`DecideUiFingerprint` / `UiFingerprintVerdictName` / `kExpectedOriginalTabCount`；单测 **+5 用例**（结构齐即通过 / 宽限期内一律等待 / 宽限期后按依赖链 / 80 组合不变量枚举 / 失败码文案互不相同且被工具钉住） |
| 产品 | `SAQ_UiInject.cpp`：`ActivateForMenu` 开头的指纹段（原 menu/tabSel/list 的「静默 return」全部并入指纹判定；`tabs0` 读取顺带收敛到这一处）+ `OnMenuOpened`（宽限期起点）+ 激活行 `指纹=ok`；`SAQ.cpp`：菜单打开时调 `UiInject::OnMenuOpened()`（恰好 1 处） |
| verify | +4 条产品特征串（失败告警 / `指纹=ok` / 失败原因文案 / 半残防护说明）+ 1 条 P2 计划形状（`.*指纹=ok`）+ 3 条源码结构（产品路径调用离线判据 / 宽限期接线恰好 1 处 / 离线层实现 + 单测用例在场） |
| P2 计划 | r137 断言升级为 `assert.log 界面注入：已激活（UiMode=auto.*指纹=ok`（自检通过 = 激活的前提；自检不匹配 ⇒ 走 WARN 且不激活，断言等不到） |
| 正则自检 | `p2_plan_regex_check.py` 样例同步（激活行尾 `指纹=ok`）—— 18 条正则 / 15 样例 |

**离线判据（全绿）**：DLL 开发构建（harness）**1208320 B**（1206272 → +2048）；`verify --dev`
**1049 行 / 0 MISS**；离线层 **5 步全过**（决策单测 **24 用例 / 1201 断言** —— 原 19/936）。

### 15.3 发布形态决策

按第十一节 11.6 的**选项 B**（推荐过渡态）发布：**SWF 覆盖随包安装（默认形态）+
检测到冲突（notOurs）自动切注入形态**（`UiMode=auto` 默认；`swf` / `inject` 可强制）。
理由：① 双形态维护成本已被「差异收敛在一层」设计压住（数据 / 决策 / 引导全留在 C++，
只有「展示 + 接管」两套；SWF 侧冻结不再加功能）；② 冲突场景（第三方改
missionmenu.swf）功能照常可用（第 139/142 轮实机两形态都全绿）；③ 选项 C（注入唯一）
的触发条件（判据等价 + 过一个游戏版本周期无回归）尚未满足 —— 保留为长期目标。

### 15.4 待实机（P5 验收）

| 会话 | 内容 | 判据 |
| --- | --- | --- |
| 常规态（带 SWF 覆盖） | 主计划 **43 条** | **等价全绿**（注入层在场不影响 SWF 形态 —— P5 的回归底线） |
| P2 实验态（原版 SWF） | 注入用例 **6 条** | 全绿（r137 含新增 `指纹=ok` 断言 ⇒ 结构指纹自检在实机通过） |
| 眼睛 | — | 第 142 轮已全部去除（玩家要求）；复跑零人工观察 |

**实机判读（2026-09-23 21:47~21:57 会话 · 常规态）**：

- 主计划 **43 条 43/43 全 PASS**（21:47:54~21:57:13 / 559266 ms / PID 30872）—— **等价回归
  底线达成**：判读 = SWF 形态（`推送成功 … 206 条` / `stamp=65` / `lang=zh`）+ `界面注入`
  **0 行**（auto 下 SWF 优先，符合设计）+ `推送放弃` 0 条 + `[E]` 0 / `[W]` 48（47 条
  「推送失败（第 1 次）」+ 1 条桥解析诊断 = 基线老现象）。
- 判据全绿：`check_results` **43/43**（退出码 0）+ `log_hygiene` 退出码 0（日志 3062 行
  零坏字节；结果 JSON 1086 行干净）+ `plan_regex_audit` **160 条断言全命中**（0 条
  永不匹配 / 49 用例段）+ `verify --dev` **1049 行 / 0 MISS** + 离线层 **5 步全过**
  （决策单测 **24 用例 / 1201 断言** + 内核自检 + 快照全一致 + tripwire OK + P2 正则
  18 条 / 15 样例）；DLL **1208320 B**（SHA256 `860D5392…`，工作区 == 部署）。
**实机判读（2026-09-23 22:06~22:08 会话 · P2 实验态（原版 SWF）· 第 144 轮）**：

- 注入用例 **6 条 6/6 全 PASS**（会话 101531 ms / PID 33976）：r120（干净 7 tab + 扩 tab +
  注入 1→3）/ r125（判定行 + 无「推送放弃」）/ r130（探针 v4 全绿：`接管=ok` / `造对象=ok`
  （三级 + 接线 UserEvents=1））/ r133（五段全 ok + 再注入）/ r140（接管三段 +
  真按键 `按键=X` → `回调=1 次｜引导=ok｜星图交接=已调用` + 端到端 `星图=开`）/
  **r137**（产品路径 `界面注入：已激活（UiMode=auto，tab 7→8，条目 206，接管=ok，指纹=ok）`
  ⇒ **结构指纹自检实机通过** + `菜单关闭：本轮为注入形态（watchdog 重放 0 次）`）。
- 判据全绿：`check_results` **6/6**（退出码 0）+ `log_hygiene` 退出码 0（日志 93526 B /
  236 行零坏字节；结果 JSON 18848 B 干净）+ `plan_regex_audit`（P2 计划）**19 条断言 /
  6 用例段全命中** + `p2_plan_regex_check` 18 条 / 15 样例 + `verify --dev --p2` 全过 +
  离线层 **5 步全过**；`[E]` 0 / `[W]` 19（全为原版 SWF 推送失败系列 = P2 态基线老现象）；
  DLL 1208320 B（`860D5392…`，工作区 == 部署）。
- ⇒ **P5 双形态回归底线全部达成**（常规态 43/43 + P2 态 6/6）—— 下一步 = 0.1.16 打包（15.5）。

### 15.5 打包 0.1.16（第 144 轮 · 已完成）

**本版新增内容** = 双形态发布（界面被覆盖 / 缺失时自动切注入形态 + 结构指纹自检）；文案
更新点 = README-mod.txt / nexus-description.md 的「界面未生效」段（从「只提示原因」升级为
「自动切换到注入形态、功能照常可用」）+ 已知限制的 UI 冲突条目（「需补丁」→「一般无需
补丁」）+ changelog v0.1.16；版本号 6 处同步（xmake.lua ×2 / main.cpp / build-saq.ps1 的
meta.ini / package-saq.ps1 默认值）。

**产物**：`dist\SAQ-ShowAvailableQuests-0.1.16.zip`（**1,883,980 B**，SHA256
`83CC33F8382C05B05FD41B7092F4A702D64388BF6033309B6F9FD1031A2D9563`；包内 7 文件 =
发布 DLL **921088 B**（`74739BF2…`，包内哈希 == 工作区）+ ESM 4805 B + SWF 733254 /
733359 B + PEX 19133 B + ini（[Test] Mode=0 / Harness=0 强制还原）+ README.txt（v0.1.16）；
`verify --release` 全过 + **打包后补跑 verify 覆盖新包**（检查项落在 0.1.16 包上）。
打完后已切回开发构建（`-SkipTable -SkipSwf -SkipPapyrus -Harness`）+ 部署还原
（SWF 覆盖拷回 733254/733359 B、`*.p2off` 清理、`[P2 恢复]` Plan 改回主计划、ini
`Harness=0` / `AutoLoad` 清空）；`verify --dev` **1049 行 / 0 MISS**。

**★ 发布构建首次暴露的两个问题（都只在 `saq_harness=n` 下出现，开发构建一直掩盖）**：

| # | 现象 | 真因 | 修复 |
| --- | --- | --- | --- |
| ① | xmake 构建失败：`SAQ_UiInject.cpp(41,1): fatal error C1075`（`{` 未匹配） | 第 140 轮起 `namespace SAQ::UiInject` 的**闭括号 `}` 落在文件末尾 `#if SAQ_WITH_HARNESS` 段内部** —— 开发构建（harness=y）段被包含所以平衡；发布构建段被整体排除 ⇒ 第 41 行的 `{` 悬空（第 137 轮起的结构，0.1.16 是它第一次跑发布构建） | 闭括号移到 `#endif` 之后（两构建等价）+ 注释钉住原因 |
| ② | `verify --release` 报「发布构建不含 harness 特征」MISS（3 条泄漏） | 3 条串是**产品与探针共用**的底层契约：`BSTabbedSelection::selectionChange`（产品订阅 tab 变化，常量在 SAQ_UiInject.cpp 第 304 行）/ `aObjectives`（注入条目子项字段）/ `Shared.Components.ButtonControls.ButtonData.UserEventData`（接管造 ButtonData 真实例）—— 第 137/140 轮产品化后它们**在发布构建里必须存在**，却被留在 harness 反向表 | 三条移到产品正向表（`UI_INJECT_PRODUCT_STRINGS`，dev/release 双向正向）—— 误报消除，且给这三条产品契约补上「发布构建也存在」的正向检查 |

**教训**：发布构建（`-Release`）必须**定期真跑**（本轮 0.1.16 是第 137 轮注入层产品化之后的
首次发布构建）—— 开发构建（harness=y）会掩盖只影响 `SAQ_WITH_HARNESS=0` 的结构问题；
`verify --release` 的特征表也要随「产品化」同步维护（探针专用标记仍反向，共用契约转正向）。

## 附：复现命令（离线证据）

```powershell
cd "d:\workspace\starfield mod\Show Available Quests"

# 反编译原版 SWF（首次；产出 _tmp_ffdec_base/scripts/**/*.as）
java -jar tools\ffdec\ffdec.jar -export script "_tmp_ffdec_base" ui\missionmenu\base\missionmenu.swf

# 导出 SWF 结构 XML（找 root 实例名 / 引用关系）
java -jar tools\ffdec\ffdec.jar -swf2xml "_tmp_ffdec_base\missionmenu.xml" ui\missionmenu\base\missionmenu.swf
java -jar tools\ffdec\ffdec.jar -swf2xml "_tmp_ffdec_base\patch.xml"      ui\missionmenu\build\missionmenu.swf
# 关键行：PlaceObject2Tag characterId="94" ... name="Menu_mc"（两版一致）

# 改动面统计（原版 vs 我们编译源）
python tools\esm\_tmp_r117_diff_patch.py

# 关键事实的源码出处
#   原版 FilterInfoA / currentFilterFlag:  _tmp_ffdec_base/scripts/MissionMenu.as:109,169-172,244-273,347
#   SetTabsData:                          _tmp_ffdec_base/scripts/Shared/AS3/BSTabbedSelection.as:141
#   ITEM_ACTIVATED / InitializeEntries:   _tmp_ffdec_base/scripts/MissionsList.as:16,35,333
#   BSUIDataManager.Subscribe:            _tmp_ffdec_base/scripts/Shared/AS3/Data/BSUIDataManager.as:70
```
