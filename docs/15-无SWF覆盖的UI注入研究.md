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
> `IsMission` = `hasOwnProperty("aObjectives")` 判定），已修 + verify 加防回归串，待复跑）**。

## 一、问题定义与成功判据

**现状**：我们发布 `Data\Interface\missionmenu.swf`（松散文件覆盖）—— 里面是
「原版字节码 + 我们重编译的 3 个类」。任何同样替换该文件的 mod（如任务菜单重排 /
美化类）与我们是**同一个文件的二选一**（MO2 VFS 后加载者胜），用户的另一个 mod
或我们的 tab 必然有一个失效。

**"无 SWF 覆盖"的三档判据**：

| 档 | 判据 | 说明 |
| --- | --- | --- |
| 最低 | 磁盘上不含 `missionmenu.swf`，功能不减 | tab / 列表 / 交互 / 引导 / 三类门槛全在 |
| 目标 | 能寄生在**第三方版本**的 missionmenu.swf 上 | 对方保留原版 AS3 类结构（只改布局/资源）时叠加生效 |
| 不要求 | 合并对方对 AS3 **逻辑**的修改 | 那需要对方的源码，不现实（见第四节 F 路线） |

## 二、现状回顾（为什么现在"必须"改 SWF）

`missionmenu.swf` 的菜单结构**全部在 AS3 里硬编码**：

- tab 列表 = `MissionMenu.PopulateTabs()` 里 `FilterInfoA` 的 7 项
  （`$ALL / $Main / $Faction / $Misc / $MISSION / $Activity / $Completed`，
  原版 `$ALL` 掩码 = `0xFFFFFFFF`）；
- 列表数据 = `BSUIDataManager.Subscribe("QuestData")` 推来的**玩家任务日志**
  （原版不认未接任务）；
- 过滤 = `MissionsList` 的 `filterMask & (1 << iType)`（原版逻辑）；
- 交互（跟踪 / 引导 / 展开）全部在 AS3 类方法里。

**我们的改动面**（第 117 轮实测统计，`tools/esm/_tmp_r117_diff_patch.py`）：
**只改了 3 个文件**（其余 71 个类保持原版字节码）：

| 文件 | 原版 → patch | 增量 |
| --- | --- | --- |
| `MissionMenu.as` | 735 → 2848 行 | **+2113**（载荷解析 / 合并列表 / 排序 / 前缀 / 描述文案 / 引导交互 / 诊断探针 / 测试入口 / 入口发布） |
| `MissionsList.as` | 403 → 589 行 | +186（`bSaqAvailable` 过滤 + 按 uID 找行/子项 + 顺序探针） |
| `Shared/QuestUtils.as` | 66 → 68 行 | +2（`AVAILABLE_QUEST_TYPE` 常量） |

⇒ 这 2301 行就是"运行时注入"形态**要么数据化、要么用事件/C++ 替代**的全部内容。

## 三、离线取证（本轮新增的关键事实）

反编译命令见附录。**所有事实都有原始文件出处**：

| # | 事实 | 证据（出处） |
| --- | --- | --- |
| 1 | **root 上 MissionMenu 实例名 = `Menu_mc`**（characterId=94 = `MissionMenu` 类，depth=1）—— 原版与我们的 SWF **一致** | `_tmp_ffdec_base/missionmenu.xml:3378` + patch SWF 同款 PlaceObject2 |
| 2 | `FilterInfoA` 是 **private**，且原版**只有 3 处使用**：声明 / `currentFilterFlag` / `PopulateTabs` | 原版 `MissionMenu.as:109,169-172,244-273` |
| 3 | `currentFilterFlag` 的**唯一消费者** = `onFilterChanged`（`filterMask = currentFilterFlag`）⇒ 第 8 个 tab 的**越界风险点单一** | 原版 `MissionMenu.as:347` |
| 4 | `BSTabbedSelection.SetTabsData(Array, uint=0)` 是 **public** | `Shared/AS3/BSTabbedSelection.as:141` |
| 5 | `MissionsList.InitializeEntries(Array)` 是 **override public** | `MissionsList.as:35` |
| 6 | `MissionsList.ITEM_ACTIVATED = "MissionsList::itemActivated"`（public static const，**事件名字符串可硬编码在 C++**）；派发点 `onEntryPress`（冒泡 + cancelable） | `MissionsList.as:16,333-337` |
| 7 | `MissionMenu` 的 FLA 元件成员都是 **public var**：`MissionsList_mc` / `TabbedFilterSelection_mc` / `MissionInfo_mc` / `ButtonBar_mc` … | 原版 `MissionMenu.as:79-92` |
| 8 | `BSUIDataManager.Subscribe(String, Function, Boolean=false)` 是 **public static**（引擎数据订阅；`QuestData` / `MissionMenuStateData` …） | `Shared/AS3/Data/BSUIDataManager.as:70` |
| 9 | GFx `Value` 的**全部对象接口** commonlibsf 已封装：`GetMember` / `SetMember` / `HasMember` / `Invoke` / `VisitMembers` / `PushBack` / `SetArraySize` / `GetArraySize` … | `tools/commonlibsf-main/include/RE/S/ScaleformGFxValue.h` |
| 10 | `ASMovieRootBase` 有 `GetVariable`（槽 0x32，**未验证**）/ `SetVariable`（槽 0x31）/ `Invoke`（槽 0x39）/ `CreateFunction`（槽 0x30）/ `IsAvailable`（槽 0x37） | `ScaleformGFxASMovieRootBase.h` |

**推论**（待实验确认）：
- 位置链 `_root.Menu_mc` → `.MissionsList_mc` / `.TabbedFilterSelection_mc` 都可访问
  （实例名是动态属性、FLA 成员是 public trait；我们已实测 `_root.<动态属性>` 路径可用）；
- 加 tab（显示层面）= `SetTabsData(我们自己构造的 8 项数组)` —— public ✓；
- 剩余两个硬骨头 = **写 private `FilterInfoA`**（决定"不越界"）与**事件接管**（决定交互）。

## 四、候选路线盘点

| 路线 | 机制 | 能解决 | 判定 |
| --- | --- | --- | --- |
| **A 运行时 GFx 注入** | C++ 用 GFx API 直接操作原版 `MissionMenu` 的 AS3 对象（写 `FilterInfoA` / 调 `SetTabsData` / `InitializeEntries` / 挂事件监听） | 文件级零冲突；可寄生第三方 SWF；**唯一能真正共存** | ★ **首推，做 PoC** |
| B 数据层注入 | hook 引擎 → `QuestData` 数据通道追加假条目 | 数据自动进原版列表 | 只解决数据、**不解决 tab**（要新增 tab 仍需 A）⇒ 作 A 的备选/补充 |
| C AVMPlus 内存 patch | 改类的方法表（替换 `PopulateTabs` 等） | 完全控制 | 高风险、完全不可维护、换版本即碎 ⇒ **不做** |
| D 现状 + 冲突检测 | 继续 SWF 覆盖，加"检测到第三方 missionmenu.swf"提示 | 体验缓解（不让用户一脸问号） | 与 A 并行、低成本，值得顺手做 |
| E 独立菜单 / 热键 | 自建 UI 菜单（不碰 missionmenu.swf） | 零冲突 | **产品形态变了**（不是"原版任务菜单里加 tab"）⇒ 不满足需求 |
| F 合并构建（反编译对方 SWF → 打我们的补丁 → 重编译） | 发布"合并版" | 真共存 | 版权（不能分发他人资源）+ 每个版本都要重做 ⇒ **不可行** |

## 五、A 路线的 4 个技术未知点（= 探针实验清单）

| # | 未知点 | 为什么关键 | 失败的后果 |
| --- | --- | --- | --- |
| **U1** | **GFx `SetMember`/`GetMember` 能否读写 AS3 private 成员**（`FilterInfoA`） | 决定"第 8 个 tab"能否存在（`currentFilterFlag` 越界） | 若不能 ⇒ 换"事件拦截"方案（U3）或路线终止 |
| **U2** | **public 方法/属性调用**：`SetTabsData` / `InitializeEntries` / `numTabs` / `entryCount` / `filterMask`（含 getter 能否被 `Invoke`） | 注入的"手脚" | 若 getter 不可 Invoke ⇒ 用 `GetVariable` 槽（0x32，需先验证） |
| **U3** | **事件注入与拦截**：`addEventListener(…, 高 priority)` + `stopImmediatePropagation` + C++ `CreateFunction` 回调 | 决定交互（点击引导 / 双击 / 阻止原版误处理） | 若不能拦截 ⇒ 我们的 tab 点击会走原版逻辑（异常/无反应） |
| **U4** | **刷新时机**：引擎 `QuestData` 更新会覆盖我们的合并列表 | 列表是否稳定 | 备选 = 500ms 轮询重建（现有节奏可复用）或 `BSUIDataManager.Subscribe` 静态可达性 |

## 六、实验设计（`ui.research` 探针，dev-only）

**形态**：新增一个只读优先的研究探针 op（走 harness 驱动，结果进日志 + 步骤 JSON），
**只在 `SAQ_WITH_HARNESS` 构建里存在**（与 `quest.probe`/`info.probe` 同款纪律：
探针结果必须同时打一行**产品日志**，供 `assert.log` 取证）。

**步骤**（一次调用跑完全部，逐项打印，任一步失败不中断）：

| 步 | 动作 | 判据 |
| --- | --- | --- |
| 1 | 读 `_root` / `_root.Menu_mc`（`GetVariable` 或 `GetMember`） | 拿到对象 ⇒ 路径基础设施可用 |
| 2 | 读 `_root.Menu_mc.FilterInfoA`（**private**）→ 报 类型 / 长度 / 每项 text,flag | **U1 读**：能读到 7 项（原版 SWF）/ 8 项（我们的 SWF） |
| 3 | 读 `TabbedFilterSelection_mc.numTabs` / `MissionsList_mc.entryCount` / `filterMask` | **U2 读**：getter/属性可达性 |
| 4 | 写 `FilterInfoA`（复制 + 追加 1 项 `{text:"SAQ研究", flag:64}`，幂等：已有则替换）→ 读回验证长度 +1 | **U1 写**：写成功 ⇒ tab 注入可行 |
| 5 | 调 `TabbedFilterSelection_mc.SetTabsData(数组)` → 读回 `numTabs` | **U2 调用**：tab 数 +1（屏幕上应出现第 9/8 个 tab） |
| 6 | 给 `MissionsList_mc` 挂 C++ 回调（`CreateFunction` + `addEventListener("MissionsList::itemActivated", …, priority 100)`）→ 打印"已注册" | **U3**：随后玩家点列表条目 ⇒ 日志应出现"回调收到" |
| 7 | 汇总一行（`ui.research：…`）+ 步骤 JSON | 判读入口 |

**副作用处理**：写测试会改内存里的界面状态 —— **天然被"关菜单 ⇒ Movie 销毁
⇒ 下次打开重建"清理**（第 27/50 轮已定案），不需要额外还原。

**两阶段执行**：

| 阶段 | 环境 | 验证什么 | 成本 |
| --- | --- | --- | --- |
| **P1** | 我们的补丁 SWF（现状部署） | U1/U2/U3 的**能力边界**（FilterInfoA 已是 8 项，写第 9 项同样是"写 private"） | 零（跑一轮 harness 即可） |
| **P2** | **原版 SWF**（MO2 临时禁用我们的 SWF 覆盖） | 完整 PoC：7 项 → 8 项 tab + 数据注入 + 事件接管 —— **"无覆盖"目标形态** | 一轮（要改部署 + 恢复） |

> P2 通过之前，**不投入**任何产品化改造（迁移 2301 行 AS3 逻辑是大工程）。

## 七、若 A 成立：功能迁移清单（AS3 → C++/数据侧）

| 现有 AS3 功能 | 运行时注入形态的替代 | 难度 |
| --- | --- | --- |
| 载荷解析 / 合并列表 | 直接由 C++ 构造 AS3 数组（`CreateArray` + `PushBack`） | 低 |
| 排序（同伴 / 势力 / 可重复 / 入口固定） | 数据侧（现有 C++ 已有全部字段） | 低 |
| 名称前缀（（不可导航）/（可重复）） | 数据侧（`sName` 直接带前缀） | 低 |
| 描述文案 / 简要说明 | 数据侧（`sDescription`） | 低 |
| 列表过滤（`bSaqAvailable`） | 原版逻辑即可：`iType=6` + 第 8 tab 掩码 `1<<6`（**「全部」掩码需改 `FilterInfoA[0].flag`** ⇒ 依赖 U1） | 低（依赖 U1） |
| 点击 / 双击 / 引导 / 跟踪 | 事件接管（U3）+ C++ 现有 `Guide::` 实现 | 中 |
| 「不可导航」点击不闪烁 / SET COURSE 置灰 | 数据字段（`bCanShowOnMap` 等）+ 事件接管 | 中 |
| 诊断探针（`SAQ_Report` 等） | C++ 直接读 GFx 状态（本探针即是雏形） | 中 |
| 测试入口（`SAQ_TestDrive*`） | C++ 直接操作 GFx（替代 `ui.*` 的 AS3 侧） | 中 |

**风险（即使 A 成立）**：
- 依赖原版 AS3 的**内部名**（`Menu_mc`、`FilterInfoA`、事件字符串）—— 换游戏版本若改动它们，
  注入会静默失效（可加"自检日志"）；而"自定义 SWF"方案不受影响。
- 交互接管与**其它 UI mod** 的行为可能叠加出预期外结果（对方也改了同一段逻辑时）。
- ⇒ 建议形态：**可选的"兼容模式"**（默认仍走 SWF，检测到冲突时提示可切注入），
  而不是立即替换默认发布形态。

## 八、结论与下一步

1. **离线取证已把方案收敛到 3 个可实验的未知点（U1/U2/U3）** ——
   原版结构对我们的注入**友好**（root 实例名固定、关键接口 public、越界风险点单一）；
2. **U1（private 可写性）是成败关键**：GFx 的 `SetMember` 走 AS3 运行时属性语义，
   理论上可能成功（运行时 `setProperty` 不经过编译期命名空间检查），**必须实机验证**；
3. 下一步 = **实现 `ui.research` 探针 + 跑 P1**（记录 see `docs/99` 下一轮）；
   P1 全绿 ⇒ 做 P2（原版 SWF 完整 PoC）；
4. 无论 A 是否成立，**路线 D（冲突检测 + 文档说明）都值得顺手做**（低成本、直接改善体验）。

## 九、本轮产物（第 117 轮已落地）与待实机判读

**已落地**（构建 + 部署 + `verify --dev` **0 MISS** + 离线层 3/3 全过）：

| 产物 | 说明 |
| --- | --- |
| `plugin/src/SAQ_UI.{h,cpp}` | `ResearchGfxCapabilities(bool)` —— GFx 能力探针（U0 路径读 / U1 私有读写 / U2 `SetTabsData` / U3 事件注册）。**全部在 `#if SAQ_WITH_HARNESS` 段内**（发布构建零残留，verify 反向检查覆盖） |
| `plugin/src/SAQ_Test.cpp` | 新 op `ui.research [events]`（一次性完成；结果打一行**产品日志** `界面研究探针 …` = 红线六） |
| `tools/test/scenarios/SAQ_TestPlan.txt` | **+2 条用例**（用例集 39 → **41**）：`r117_gfx_research`（U1/U2）/ `r117_gfx_research_events`（U3） |
| `tools/ui/verify_saq_build.py` | +10 条检查（4 条 DLL 特征串 dev/release 双向 + 6 条用例计划形状） |
| MO2 部署 | 开发构建 DLL（含新探针）+ 41 条用例已同步；`Harness=0`（正常玩） |

**待实机（下一轮，41 条用例）** —— 判读入口 = 日志里的 `界面研究探针 …` 一行：

| 段落 | 值 | 含义 / 下一步 |
| --- | --- | --- |
| `GetVar槽=在\|无` | 无 | `GetVariable` 槽（0x32）在本版本不对 ⇒ 后续各项全 fail，要先换「Invoke/GetMember」路线（见下） |
| `Menu_mc=ok` | ok | `_root.Menu_mc` 定位成功（实例名来自 SWF 结构取证） |
| `私有读=(ok …)` | ok | **U1 读成立**：GFx 能读到 AS3 private 成员 ⇒ 注入"手脚"存在 |
| `私有写=ok（N→N+1）` | ok | **U1 写成立** ← **成败关键**：第 8 个 tab 可存在（`FilterInfoA` 可改） |
| `SetTabsData=ok（numTabs N→N+1）` | ok | **U2 成立**：tab 可控 |
| `事件注册=ok` + `事件回调收到` | ok | **U3 成立**：交互可接管 |

**眼睛（P1 副作用，可选看）**：写成功时 tab 条上会多一个第 9 个「SAQ研究」tab；
菜单关掉再开应恢复 8 个（Movie 重建 ⇒ 副作用自然清理）。

### 九·补、实测判读（2026-09-23 · 第 118 轮；41 条用例 41/41 全 PASS）

**实测两行**（`r117_gfx_research` / `r117_gfx_research_events`，14:23:07~09）：

```
界面研究探针 GetVar槽=在｜Menu_mc=ok｜私有读=(fail HasMember=0 项数=0)｜私有写=未做（读失败）｜TabSel=ok numTabs=8｜事件=未试
界面研究探针 GetVar槽=在｜Menu_mc=ok｜私有读=(fail HasMember=0 项数=0)｜私有写=未做（读失败）｜TabSel=ok numTabs=8｜MissionsList_mc=ok｜事件注册=ok
界面研究探针：事件回调收到（第 1 次，argCount=1）   ← 随后走原版路径（ui.key Accept → onEntryPress → ITEM_ACTIVATED）真实触发
```

| 未知点 | 实测 | 判读 |
| --- | --- | --- |
| **U0** 路径基础设施 | `GetVar槽=在` + `Menu_mc=ok` | ✅ `GetVariable`（0x32）槽在本版本有效；`_root.Menu_mc` 定位成功 |
| **U1** private 读写 | `私有读=(fail HasMember=0 项数=0)`；写被短路 | ❌ **能力边界**（非意外）：AVM2 private trait 带类私有 namespace，GFx 的 public multiname 查不到 ⇒ `SetMember` 写也只会创建 dynamic 公共属性、原版编译期绑定读不到 ⇒ **放弃"改 FilterInfoA"** |
| **U2** public 调用 | `TabSel=ok numTabs=8`（对象 + getter 可达）；`SetTabsData` **未执行** | ❓ **未验证**：探针把 `SetTabsData` 调用耦合在 `writeOk && readOk` 之后（**探针设计缺陷** —— 它本身不依赖 `FilterInfoA`，参数即数组）⇒ 下一轮补测 |
| **U3** 事件注入 | `事件注册=ok` + `事件回调收到（argCount=1）` | ✅ **成立**（`CreateFunction` + `addEventListener(..., priority=100)`，回调真实收到） |

**结论：路线 A 不终止** —— U1 的失败可完整绕开，离线依据（反编译源码）：

1. `FilterInfoA` 的唯一用途链 = `currentFilterFlag` getter（`FilterInfoA[idx].flag`，
   原版 `MissionMenu.as:169-172`，public getter）→ 唯一消费者 `onFilterChanged`
   （原版 `MissionMenu.as:343-354`，private）→ `MissionsList_mc.filterMask = currentFilterFlag`；
2. **拦截事件即可绕过**：`onFilterChanged` 也是通过
   `TabbedFilterSelection_mc.addEventListener(BSTabbedSelectionEvent.NAME, …)`
   （原版 `:274`）挂的 —— U3 已证明我们能挂 priority=100 监听（先于原版 priority=0 收到）；
   在切到第 8 tab（`iSelectedIndex==7`）时 `stopImmediatePropagation()` 拦住原版
   （防 `FilterInfoA[7].flag` 越界 TypeError），随后自己设过滤；
3. **自己设过滤可行**：`filterMask` 是 **public setter**（`BSScrollingTree.as:18-27`，
   set 内自动 `FilterRootEntries()` 刷新显示）⇒ C++ `SetMember(MissionsList_mc, "filterMask", 64)`
   （待 GFx 写验证）；
4. `SetTabsData(Array, uint=0)` 是 public（`BSTabbedSelection.as:141`）且**参数就是数组本身**
   ⇒ 加 tab 不依赖 U1（待补测）；
5. 事件类型字符串 = **`"BSTabbedSelection::selectionChange"`**（`BSTabbedSelectionEvent.NAME`）；
   事件对象带 `iSelectedIndex` / `iPreviousSelectionIndex`（public int，可供 C++ 回调读取）。

### 九·补二、探针 v2 已落地（2026-09-23 · 第 119 轮；`ui.research2`）

**实现**（`plugin/src/SAQ_UI.{h,cpp}` 的 `ResearchGfxInjection2`；harness 段内、发布零残留）：

| 段 | 动作 | 判定（汇总行字段） |
| --- | --- | --- |
| R1 | `ObjVisitor` 扫 `Menu_mc`（尽力模式，含 AS3 public 链） | `枚举=(N 个,FilterInfoA=有/无)` |
| R2 | 在 `TabbedFilterSelection_mc` 挂 `priority=100` 的 `"BSTabbedSelection::selectionChange"` 监听（原版 `onFilterChanged` 是 0） | `切7=ok`（拦截计数 ≥1） |
| R3 | handler 对 `iSelectedIndex==7` `stopImmediatePropagation()` + `SetMember(filterMask, 哨兵 1<<29)` + 读回 | **哨兵存活 = 拦截 + 写双成立**（若没拦住，原版随后执行会把值覆盖回自己的 flag） |
| R4 | C++ 构造数组 → `SetTabsData` → `numTabs` 读回 | `U2=ok（numTabs N→N+1→N）` |

**判据链（一次执行四段；切 tab 走原版 public 入口 `SetSelectedCategoryIndex`
—— 内部 `SetSelectedIndex` → `dispatchEvent`）**：

1. 挂监听 → 读 `filterMask` 初值（`$ALL`）；
2. 切 3 → 回调 idx=3（不拦）→ 原版执行 ⇒ mask 变化（**对照**：切换动作确实触发原版处理）；
3. 切 7 → 回调 idx=7 → stop + 自设哨兵 ⇒ mask == `0x20000000`（**拦截 + 写**）；
4. 切 0 → 回调 idx=0（不拦）→ 原版执行 ⇒ mask 回 `$ALL`（**不越权**：非 7 的 tab 不拦）；
5. `removeEventListener` 清理（统计先抄走 —— remove 后 handler 可能被 delete）；
6. U2 补测（破坏性，放最后）：构造 9 项 → `numTabs 8→9`；恢复 8 项 → `8`。

用例 = `r119_gfx_inject2`（用例集 **41 → 42**，728 步）；verify +10 条（5 条 DLL 特征
dev/release 双向 + 4 条用例计划形状 + 1 条只读反向）；断言 = **一条行内正则**
（`切3=ok.*切7=ok.*切0=ok.*清理=ok.*U2=ok` —— 顺序固定，防拆散后漏段）。

**副作用**：哨兵 `filterMask` / tab 数据被替换（`$SAQ测试0..8` / `$SAQ恢复0..7`）——
菜单关闭随 Movie 销毁清理（第 27/50 轮定案）；用例内不做后续 UI 断言（`menu.close` 收尾）。

**判读**：四段全 ok ⇒ 做 **P2**（原版 SWF 完整 PoC：MO2 临时禁用我们的 SWF 覆盖，
验证 7 → 8 个 tab + 数据注入 + 交互接管）；任一段 fail ⇒ 按该段的实测值定位
（哨兵不存活 = 拦截失败；`U2=fail` 自带原因）。若 2/3 又失败且无替代 ⇒ 路线 A 终止，
回到路线 D（现状 + 冲突检测）。**实测 = 九·补三（五段全 ok ⇒ 做 P2）**。

### 九·补三、探针 v2 实测判读（2026-09-23 · 第 120 轮；42 条用例 42/42 全 PASS）

**实测一行**（`r119_gfx_inject2` 用例，14:53:43.324）：

```
界面研究探针2 Menu_mc=ok｜枚举=(82 个,FilterInfoA=无)｜切3=ok（mask 0xFFFFFFBF→0x00000008）｜切7=ok（拦截 1 次,mask→0x20000000）｜切0=ok（mask→0xFFFFFFBF）｜回调=3 次（末次 idx=0）｜清理=ok｜U2=ok（TabsData 调用 ok，numTabs 8→9→8）
```

| 段 | 实测 | 判读 |
| --- | --- | --- |
| R1 成员枚举 | `枚举=(82 个, FilterInfoA=无)` | U1 能力边界**再次确认**（private trait 不在 public 枚举里 —— 82 个成员 = FLA 公开成员 + dynamic 属性） |
| R2 事件回调 | `回调=3 次（末次 idx=0）` | ✅ 三次切 tab（3/7/0）priority=100 监听**每次都先收到** |
| R3 拦截 + 写 | `切7=ok（拦截 1 次，mask→0x20000000）` | ✅ **哨兵存活 = 拦截 + 写双成立**：`stopImmediatePropagation` 确实拦住了原版 `onFilterChanged`（否则它随后会用 `FilterInfoA[idx]` 的值把 mask 覆盖回去），且 `SetMember(filterMask)` 生效 |
| R3 对照 | `切3=ok（mask 0xFFFFFFBF→0x00000008）` | ✅ 原版执行路径正常（切普通 tab 时 mask 按原版逻辑变化） |
| R3 不越权 | `切0=ok（mask→0xFFFFFFBF）` | ✅ 非 7 的 tab 一律放行（拦截只对第 8 tab 生效） |
| R4 U2 补测 | `U2=ok（TabsData 调用 ok，numTabs 8→9→8）` | ✅ **U2 成立**：`SetTabsData` 全链路（C++ 构造数组 → 调用 → getter 读回 → 恢复）可用 |
| 清理 | `清理=ok` | ✅ `removeEventListener` 正常 |

**结论：P1.5 全绿 —— 路线 A 的绕过路径实机确认**：

1. **加 tab 可行**（U2：`SetTabsData` + `numTabs` getter 读写）；
2. **不越界可行**（R3：拦截原版 `onFilterChanged` + 自设 `filterMask`，哨兵存活）；
3. **交互接管可行**（R2 + 第 118 轮 U3：priority=100 监听真实先收到，可 `stopImmediatePropagation`）；
4. 唯一限制 = 不能直接读写 `FilterInfoA`（U1）—— 但上述路径已完整绕开它。

⇒ **下一步 = P2**（原版 SWF 完整 PoC）：MO2 临时禁用我们的 SWF 覆盖 ⇒ 在**原版
7 个 tab** 的环境里验证「7 → 8 个 tab + 列表数据注入 + 交互接管」全链路；成功即
"无 SWF 覆盖"目标形态成立，之后才评估功能迁移（第七节）与产品形态（第七节风险：
建议"兼容模式"，默认仍走 SWF）。

**P2 的探针设计注意点**（从本轮实测推出的两条）：
- 原版 SWF 只有 7 个 tab（idx 0~6）⇒ 「切 7」在**扩 tab 之前**会被
  `SetSelectedCategoryIndex` 拒绝（拒绝码 `tab-refused`，第 51 轮已见过该机制）——
  P2 的探针顺序须改为「**先 `SetTabsData` 扩到 8 → 再切 7 验证拦截**」；
- `filterMask` 初值（`$ALL`）与 tab 数无关，对照段（切 3）在原版上照样可用。

### 九·补四、P2 已落地（2026-09-23 · 第 121 轮；`ui.research3`）

**实现**（`plugin/src/SAQ_UI.{h,cpp}` 的 `ResearchGfxInjection3`；harness 段内、发布零残留）：

| 段 | 动作 | 判定（汇总行字段） |
| --- | --- | --- |
| R1 | 读环境 `numTabs` / `entryCount` / `filterMask` | `环境=(numTabs 7,…)`（原版预期 7） |
| R2 | `TabbedFilterSelection_mc` 挂 priority=100 的 `"BSTabbedSelection::selectionChange"` 监听 | （拦截计数在 R5 用） |
| R3 | **扩 tab**：构造 N0+1 项（前 N0 项假数据 + 新 tab `"SAQ-PoC"` flag=1<<6）→ `SetTabsData` → `numTabs` 读回 | `扩tab=ok（7→8）` |
| R4 | 切 3（对照） | `切3=ok`（原版执行 ⇒ 读**自己的** `FilterInfoA[3]` ⇒ mask 变） |
| R5 | 切 N0（新 tab）：`stopImmediatePropagation` + 哨兵写 | **哨兵存活 = 拦截 + 写双成立**（`切7=ok（拦截 1 次,mask→0x20000000）`） |
| R6 | 切 0（放行） | `切0=ok`（mask 回到 `$ALL`） |
| R7 | `removeEventListener` | `清理=ok` |
| R8 | 自设 `filterMask` = 1<<6（模拟产品「我们的 tab」状态） | （为 R9 铺路） |
| R9 | **列表数据注入**：构造 3 条 iType=6 条目 → `MissionsList_mc.InitializeEntries` → `entryCount` 读回 | `注入=ok（entryCount 206→3）` |

**判据链**（一条行内正则；顺序 = 输出顺序，防拆散后漏段）：
`扩tab=ok.*切3=ok.*切7=ok.*切0=ok.*清理=ok.*注入=ok`。

**为什么 R5 是「必须拦截」的硬证据**：原版 SWF 的 `FilterInfoA` 只有 7 项 ——
原版 `onFilterChanged`（priority=0）会读 `FilterInfoA[7].flag` = `undefined.flag` ⇒
TypeError。我们 priority=100 + `stopImmediatePropagation` 拦住它、自己设 mask
（产品形态下 = 「切到我们的 tab」）；没拦住则哨兵被覆盖/异常打断 ⇒ 哨兵不存活。

**P2 部署（`build-saq.ps1 -P2`）**：

| 动作 | 细节 |
| --- | --- |
| SWF 覆盖禁用 | `Interface\missionmenu.swf` / `missionmenu_lrg.swf` → `*.p2off`（游戏加载原版） |
| 用例计划切换 | 拷入 `SAQ_TestPlan_p2.txt`（只含 `r120_gfx_poc` 一条 —— 原版下我们 SWF 的 `ui.*` 测试入口全不可用）并写 ini `[Test] Plan=SAQ_TestPlan_p2.txt` |
| 恢复 | 不带 `-P2` 再跑一次（例如 `-SkipTable -SkipSwf -Harness`）：SWF 拷回、`*.p2off` 清理、ini Plan 改回 `SAQ_TestPlan.txt` |

**verify（`--p2` 模式）**：P2 期间部署 SWF 是**有意缺失**的 ⇒ `--p2` 改查
`*.p2off` 存在证据、部署 ini `Plan` 必须指向 p2 计划；非 P2 模式反向检查
`*.p2off` 残留与 Plan 残留（防「P2 没恢复干净」）。新增检查：探针3 特征串
dev/release 双向 ×4 + r120 计划形状/断言 ×4 + 只读反向 ×1 + p2off 证据 ×2 +
Plan 一致性 ×1。

**待实机判读（下一轮）**：跑 P2 会话（`Harness=1` + `Plan=SAQ_TestPlan_p2.txt` +
SWF 禁用）⇒ 判读 `界面研究探针3 …` 一行（六段同现 = ok）+ **眼睛**：菜单 tab 条上
出现第 8 个 tab「SAQ-PoC」、列表被替换成 3 条「SAQ-PoC-Item i」（破坏性副作用，
`menu.close` 收尾）。六段全 ok ⇒ 「无 SWF 覆盖」目标形态成立（**P2 通过**），
再评估功能迁移（第七节）与产品形态（建议「兼容模式」，默认仍走 SWF）。

### 九·补五、P2 首跑实测判读与修复（2026-09-23 · 第 122 轮）
**五段 ok / 注入段 fail（真因已离线取证并修复，待复跑）**

会话 15:15（`Plan=SAQ_TestPlan_p2.txt`、SWF 已禁用、开发 DLL 1078784 B / `stamp=65`）——
用例 `r120_gfx_poc` FAIL（一条断言 = 六段同现正则）；实测行：

```
界面研究探针3 Menu_mc=ok｜环境=(numTabs 7,entryCount 1,mask 0xFFFFFFFF)｜扩tab=ok（7→8）
｜切3=ok（mask 0xFFFFFFFF→0x00000008）｜切7=ok（拦截 1 次,mask→0x20000000）
｜切0=ok（mask→0xFFFFFFFF）｜回调=3 次（末次 idx=0）｜清理=ok｜注入=fail（entryCount 1→0，期望 3）
```

| 段 | 实测 | 判读 |
| --- | --- | --- |
| 环境 | `numTabs 7` | ✅ **原版 SWF 生效**（P2 部署正确；我们的 SWF 是 8） |
| 扩tab（7→8） | ok | ✅ `SetTabsData` 在原版 `BSTabbedSelection` 上生效 |
| 切3（对照） | ok | ✅ 原版 `onFilterChanged` 正常执行（读自己的 `FilterInfoA[3]`） |
| 切7（拦截 + 哨兵） | ok（拦截 1 次，`mask→0x20000000`） | ✅ **拦截 + 写双成立**（原版直接切 idx 7 会越界 TypeError —— 第 8 个 tab 必须拦截的硬证据，与 P1.5 一致） |
| 切0（放行） | ok | ✅ 不越权 |
| 清理 | ok | ✅ `removeEventListener` |
| **注入** | **fail（entryCount 1→0）** | ❌ 真因见下（已修） |

**注入失败真因（离线取证）**：原版 `MissionsList.FilterRootEntries`
（`_tmp_ffdec_base/scripts/MissionsList.as:157`）的第一道门是
`IsRootEntry(param1) = MissionsListEntry.IsMission(param1) || param1.bIsDivider === true`，
而 `IsMission`（`MissionsListEntry.as:42`）= **`param1.hasOwnProperty("aObjectives")`** ——
初版注入条目只设了 `uID/sName/iType/iFaction/bComplete/bFailed`，**没带 `aObjectives`**
⇒ 3 条全部被过滤（`rawEntries` 收下、`entryList` 一条不留 ⇒ entryCount 0；起点 1 =
原版菜单里那条真任务被这次注入整体替换掉）。我们 SWF 版的产品条目**本来就带**该字段
（靠自加的 `bSaqAvailable` 分支放行）；原版没有该分支 ⇒ **运行时注入必须在字段上
模拟 mission 条目**。第二道门 `EntryFilterCompare_Impl`（`MissionsList.as:202`，
`(filterMask & 1 << iType) != 0`）本来就满足（iType=6 + mask=1<<6）。

**修复（第 122 轮）**：每条注入条目补 `aObjectives`（空数组 ⇒ `GetChildrenOfEntry`
返回空数组、行照常渲染、展开无子项）+ 渲染路径防御字段 `bActive=false` /
`iRemainingTime=-1`（不设会走 `GlobalFunc.GetQuestTimeRemainingString(undefined)`；
iType=6 的图标标签 = `default "None"`，帧存在、安全）；verify 新增特征串
`aObjectives`（dev 正向 / 发布反向）防「改回只设 iType」再犯。**已重建部署（P2 态），待复跑**。

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
