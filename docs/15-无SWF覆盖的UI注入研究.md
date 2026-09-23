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

### 九·补六、P2 复跑实测判读（2026-09-23 · 第 123 轮）
**六段全 ok + 注入段修复一击生效 ⇒ P2 通过（「无 SWF 覆盖」目标形态技术成立）**

会话 15:25~15:27（82172 ms / `Plan=SAQ_TestPlan_p2.txt`、SWF 覆盖已禁用、开发 DLL
1079296 B）—— 用例 `r120_gfx_poc` **PASS**（10375 ms）；实测行：

```
界面研究探针3 Menu_mc=ok｜环境=(numTabs 7,entryCount 1,mask 0xFFFFFFFF)｜扩tab=ok（7→8）｜切3=ok（mask 0xFFFFFFFF→0x00000008）｜切7=ok（拦截 1 次,mask→0x20000000）｜切0=ok（mask→0xFFFFFFFF）｜回调=3 次（末次 idx=0）｜清理=ok｜注入=ok（entryCount 1→3）
```

| 段 | 实测 | 判读 |
| --- | --- | --- |
| 环境 | `numTabs 7`、`entryCount 1`、`mask 0xFFFFFFFF` | ✅ 原版 SWF 生效（P2 部署正确；我们的 SWF 是 8） |
| 扩tab（7→8） | ok | ✅ `SetTabsData` 在原版 `BSTabbedSelection` 上生效 |
| 切3（对照） | ok（mask → `0x00000008`） | ✅ 原版 `onFilterChanged` 正常执行（读自己的 `FilterInfoA[3]`） |
| 切7（拦截 + 哨兵） | ok（拦截 1 次，`mask→0x20000000`） | ✅ **拦截 + 写双成立**（原版直接切 idx 7 会越界 TypeError —— 被 we priority=100 拦住） |
| 切0（放行） | ok（mask → `0xFFFFFFFF`） | ✅ 不越权 |
| 清理 | ok | ✅ `removeEventListener` 正常 |
| **注入** | **ok（entryCount 1→3）** | ✅ 第 122 轮修复（补 `aObjectives` 空数组）**一击生效** |

**本轮判据五连全绿**（退出码均为 0）：
- `check_results.py`（1 条用例 PASS / 0 FAIL / 0 SKIP）；
- `log_hygiene.py`（日志 39910 B / 89 行、结果 JSON —— 零坏字节零控制字符）；
- `plan_regex_audit.py`（2/2 全命中）；
- `verify_saq_build.py --dev --p2`（含 `*.p2off` 禁用证据 + 部署 == 工作区）；
- 离线层 3/3（19 用例 / 936 断言 + 快照 16 件 + tripwire）。

**眼睛窗口（重要说明）**：探针副作用（8 个 tab / 列表 3 条）只在「探针执行后 →
`menu.close`」之间可见（本次 ~8 秒；tab 条前 7 项 = 探针假数据 `$SAQ-keep0..6`、
第 8 项 = `SAQ-PoC`；列表被整体替换为 3 条 `SAQ-PoC-Item i`）。菜单关闭后 Movie
销毁、重开时由原版重建 ⇒ 回到 7 tab + 原版 entries（玩家截图 = 重开后状态，**无残留**）。
为便于亲验：计划窗口 **8 → 30 秒**（第 123 轮，`wait 30000`）+ 保持 P2 部署。

**P2 形态的两条产品化观察（功能迁移的输入）**：
1. **产品推送在原版 SWF 下必然失败** —— 我们的 `SAQ_PushData` / `SAQ_Report` 等 AS3
   入口不存在于原版 SWF ⇒ DLL 每 500 ms 重试、日志持续「推送失败（重试）」+
   「界面状态一条都没读回来」。未来「兼容模式」要么检测到原版 SWF 即停推（降频降噪），
   要么把产品 UI 通道整体切换为注入形态（迁移面 = MissionMenu +2113 行 /
   MissionsList +186 / QuestUtils +2，见第七节）；
2. 重开菜单时偶见「菜单尚未就绪（UI 表里还没有 BSMissionMenu 条目），稍后重试」= 老
   时序现象（稍后重试即恢复，与 P2 无关）。

**下一步**：①（可选）眼睛会话（30 秒窗口亲验）—— ✅ **已完成（第 124 轮，见九·补七）**；
② 恢复部署（`build-saq.ps1 -SkipTable -SkipSwf -Harness` —— SWF 拷回 + `*.p2off` 清理 +
ini `Plan` 改回）—— ✅ **已完成（第 124 轮）**；③ 评估功能迁移（第七节）与产品形态
（建议「兼容模式」，默认仍走 SWF）—— **进行中**（先做第八节的路线 D 冲突检测）。

### 九·补七、P2 眼睛判据达成 + 恢复部署（2026-09-23 · 第 124 轮）
**30 秒窗口内玩家截图取得眼睛证据 ⇒ P2 判据 + 眼睛双绿，P2 完全收口**

会话 15:43~15:45（`Plan=SAQ_TestPlan_p2.txt` / SWF 覆盖已禁用 / 开发 DLL 1079296 B）——
`r120_gfx_poc` **PASS**（32344 ms）；探针行与九·补六一致（六段全 ok + 注入
`entryCount 1→3`）。玩家在「探针执行（15:44:48）→ `menu.close`（15:45:18）」的
**30 秒窗口**内截图：

| 截图上看到的 | 判读 |
| --- | --- |
| tab 条 8 项：前 7 项 = 探针假数据（显示为 `SAQ-keep…` 连串）、第 8 项 = `SAQ-PoC` | ✅ 原版 SWF 上成功扩出新 tab（`SetTabsData` 生效的肉眼证据） |
| 列表 3 条 `SAQ-PoC-Item 0/1/2` | ✅ `InitializeEntries` 注入可见（第 122 轮 `aObjectives` 修复的肉眼证据） |
| 悬停行 = 原版「按下[R]…」tooltip | 描述/交互尚未接管（预期内，产品化迁移时再做） |

**侧面证据（同一会话日志）**：菜单开着期间「推送失败（重试）」循环 + 关闭时
`菜单关闭：界面状态一条都没读回来` = 原版 SWF 里没有我们的产品 AS3 入口
（与九·补六「产品化观察①」一致 —— 兼容模式必须处理的点）。

**恢复部署（本轮）**：`build-saq.ps1 -SkipTable -SkipSwf -Harness` —— SWF 覆盖拷回
（`*.p2off` 清理）、ini `Plan` 改回主计划、回到常规测试态（开发构建 harness + 42 条用例）；
`verify --dev`（非 P2 模式）**全部通过**（含「P2 残留已清理（反向检查）」+ 部署 == 工作区）。
P2 实验态结束。

## 十、路线 D 落地：UI 通道冲突检测 + 停推降噪 + 玩家提示（2026-09-23 · 第 125 轮）

**背景**（八节路线 D + 九·补六「产品化观察①」）：P2 通过确认了「无 SWF 覆盖」形态的
技术可行性，也暴露两条产品化缺口 —— 我们的 `missionmenu.swf` 覆盖被其它 mod 覆盖 /
未安装 / 版本过旧时：① DLL 每菜单退避重试 14 次（日志持续「推送失败（重试）」）；
② 玩家完全看不出「mod 没生效」的原因（像静默失效）。

**本轮产物**（全部为产品路径 —— 发布构建同样包含）：

| 层 | 产物 | 说明 |
| --- | --- | --- |
| DLL 探测 | `UI::ProbeChannelIdentity`（`SAQ_UI.{h,cpp}`） | 桥解析成功 + `_root.SAQ_Report` 可调用且带 `stamp=` ⇒ `ours`；调用失败 / 无指纹 ⇒ `notOurs`；桥没通 ⇒ `unknown`（不判定、保持重试） |
| DLL 判定 | `SAQ.cpp`（`TryPushPending` 真失败分支） | 第 2 次尝试起探测；`notOurs` ⇒ 本菜单停推（`done`）+ 一行 WARN `UI 通道不可用（第 N 次推送失败后判定）：…` + 请脚本提示 |
| DLL 降噪 | `PollUiReport` / `PollGuideRequest` / 菜单关闭现场读 | `g_uiChannelDead` 时全部短路（不再每 500ms / 100ms 空调一次） |
| 提示通道 | ESM GLOB `SAQ_UiNotice`（0x80E）+ `Guide::SetUiNotice` | DLL 写 1（**进程内只请求一次**），脚本读到 1 ⇒ HUD 提示 + 清 0（边沿语义） |
| 脚本提示 | `SAQ_Main.psc` `ProcessUiChannelNotice` | 轮询节拍里读 GLOB；文案「可接任务界面未生效：可能被其它任务菜单 mod 覆盖 / Available Quests UI not active - likely overridden by another mission menu mod」（中英，重复 3 次 ≈ 6 秒） |

**判据纪律（宁可漏判不可误判 —— 误判会让正常界面被停推）**：
- 只在**真失败**（非「菜单还没就绪」）且第 2 次尝试起探测；
- `notOurs` 需要「桥解析成功 + `SAQ_Report` 失败 / 无指纹」双条件（两个入口同时瞬态失败的概率极低）；
- 每菜单打开重置判定（重开菜单 = 新的一次机会）；提示（GLOB）进程内一次。

**验证**（2026-09-23 · 第 125 轮）：
- 构建部署：DLL 开发构建 **1083392 B** / Papyrus 重编（PEX **19026 B**）/
  ESM 4752 → **4805 B**（+0x80E）——部署 == 工作区；
- `verify --dev` **全部通过**（+第 125 轮检查：DLL 特征串 ×3 / PEX 特征 ×4 /
  ESM UI 提示 GLOB（工作区 + 部署）/ 主计划 r125 段头 / P2 计划 r125 三条 +
  断言正则编译校验全过）；
- 离线层 3/3（19 用例 / 936 断言 + 快照 16 件（ESM 有意变化已 `--update`）+ tripwire）。

**实测（2026-09-23 · 第 126 轮）**：
- ✅ ① 正常态（我们的 SWF）：主计划 **43 条 43/43 全 PASS**（会话 16:01~16:10 / 577703 ms /
  `驱动器 v70` / `stamp=65`）—— `r125_ui_channel_ok` PASS（4562 ms）：菜单打开后
  `推送成功`（16:10:36 命中）+ `assert.nolog UI 通道不可用`（整段窗口零判定行）⇒
  **防误报成立**；全日志除用例段头 ×2 + 断言行 ×1 外无任何「UI 通道」产品行
  （也无「推送放弃」）；判据五连全绿（`check_results` / `log_hygiene` 退出码 0 +
  `plan_regex_audit` **160/160** + `verify --dev` + 离线层 3/3）。
- ★ ② P2 态（原版 SWF）：**已按 P2 实验部署**（`build-saq.ps1 -SkipTable -SkipSwf -Harness -P2`
  + `verify --dev --p2` 全过 = 756 OK），P2 计划 **2 条**（`r120_gfx_poc` + `r125_ui_conflict`）
  —— **待实机**：`UI 通道不可用（第 N 次推送失败后判定）` 出现 + **不再出现**
  「推送放弃：重试 14 次」（停推降噪生效）+ 日志一行 `UI 通道提示已请求`（进程内首判时）；
  眼睛 = 关菜单后 HUD 提示（中英，重复 3 次 ≈ 6 秒）。跑完恢复：
  `build-saq.ps1 -SkipTable -SkipSwf -Harness`（SWF 拷回 + `*.p2off` 清理 + Plan 改回主计划）。

### 十·补、提示时机修复 + P2 双收口（2026-09-23 · 第 127 轮）

**起因（第 126 轮 P2 会话的意外发现）**：P2 会话 16:25 实测 —— 轮询节拍在菜单开着时
**也会走**几拍（菜单打开后 ~8 秒窗口内），于是「UI 通道不可用」提示 3 次全落在菜单里
发完（16:25:02/05/08），玩家关菜单后什么也看不到（与设计意图「脚本将在菜单关闭后提示
玩家」不符 —— 该文案出自 `SAQ.cpp` 的 `UI 通道提示已请求` 行）。

**修复（提示时机）**：
- `SAQ_Main.psc`：新增 `MissionMenuOpen`（`OnMenuOpenCloseEvent` 维护）；
  `ProcessUiChannelNotice` / `ProcessNotice` 在菜单开着时一律不发（GLOB 的 1 保留 /
  补发计数冻结）；**关菜单事件里立刻补调一次** `ProcessUiChannelNotice`（玩家一回到
  HUD 就能看到解释，不必等下一拍）。
- P2 计划：`r120_gfx_poc` 末尾加 `wait 10000`（关菜单后的静默窗口 —— 让 3 次提示
  完整播完、不被下一条用例的 `menu.open` 打断）。
- `verify` +2 条：`PEX · UI 提示等菜单关闭（MissionMenuOpen）`（防回退）+
  `用例计划 · P2 眼睛窗口（关菜单后提示静默期）`。

**实测（2026-09-23 · 第 127 轮；P2 态 2 条 + 眼睛）**：
- 会话 16:48~16:50（118828 ms / `Plan=SAQ_TestPlan_p2.txt` / SWF 覆盖禁用 / 开发 DLL
  1083392 B / PEX **19133 B**）—— **2/2 PASS**：
  - `r120_gfx_poc` PASS（42532 ms）：六段全 ok + `注入=ok（entryCount 1→3）`；
    ★ 提示首发 `16:50:03` = **关菜单瞬间**（DLL `16:50:03.922 菜单关闭` 同一秒）+
    补发 `16:50:06/09`（共 3 次）—— **修复精确生效**（对照第 126 轮：首发 16:25:02
    落在菜单里）；
  - `r125_ui_conflict` PASS（4812 ms）：第二个菜单周期**独立判定行**
    `16:50:15.809 UI 通道不可用（第 2 次推送失败后判定）` + `assert.nolog 推送放弃`
    通过 —— 「每菜单重新判定 + 停推降噪」成立；
- 判据三连（本会话产物）：`check_results` 退出码 0（2/2）+ `log_hygiene` 退出码 0
  （日志 39959 B / 95 行零坏字节；结果 JSON 4081 B / 39 行）+
  `plan_regex_audit`（P2 计划）**4/4 全命中**；`verify --dev --p2` 全过 + 离线层 3/3；
- ★ **眼睛双达成**（玩家确认）：① 第 8 个 tab「SAQ-PoC」可见（前 7 = 探针假数据
  `$SAQ-keep0..6`）+ 3 条 `SAQ-PoC-Item 0/1/2` **界面可见** —— 显示在「当前选中的
  第 1 个 tab」下（探针末次回调 idx=0 后才执行 R9 注入，属设计行为；切到第 8 个
  tab 时列表走的是拦截后的掩码过滤结果）；② 关菜单后 HUD 中英提示可见；
- ★ 已恢复常规部署（`build-saq.ps1 -SkipTable -SkipSwf -Harness`：SWF 拷回 +
  `*.p2off` 清理 + ini `Plan` 改回主计划）；`verify --dev`（非 P2）全部通过。

**顺带观察（产品化输入）**：`wait` 步骤按「游戏运行时间」计 —— 16:37 会话
`wait 10000` 实测 51438 ms（期间游戏被暂停约 41 秒），属驱动器正常行为（暂停期间
不计时），不是缺陷。

**发布（已完成）**：0.1.15 上传包 = `dist\SAQ-ShowAvailableQuests-0.1.15.zip`
（**1,852,719 B**，SHA256 `6359DEAF1FA8CA3E3F0A5D2F2B42DA5A4830CB6B1ED66819FFEDEAEADD95006F`；
= 0.1.14 + 第 125 轮冲突检测 + 本轮提示时机修复）；`verify --release` 全过
（发布构建 63 项 harness 特征全无）+ 包内 6 产物哈希与工作区逐一致（发布 DLL
**852480 B**）；打完后已切回开发构建 + MO2 ini 还原正常玩（`Harness=0` / AutoLoad 清空）。

**下一步（大项决策）**：评估功能迁移（七节 8 项清单）与产品形态
（建议默认仍走 SWF；冲突检测已兜住体验）。

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

## 十三、P3-a 产品化 PoC（2026-09-23 · 第 133 轮；`ui.inject`）

**目标**（第十一节 11.7 的 P3）：**真实数据注入** —— 扩 tab + 分时注入 + 对账 + 恢复，
**不含交互**（交互接管 = P4；完整描述文案迁移与 watchdog = P3-b）。

**产物**：

| 层 | 产物 | 说明 |
| --- | --- | --- |
| 模块 | `plugin/src/SAQ_UiInject.{h,cpp}`（新） | 注入层独立模块（与 SAQ_UI 分文件；GFx 安全调用工具自带一份 —— 「随时可回 SWF」的隔离纪律） |
| 接口 | `SAQ_UI::ResolvedAsMovieRoot()` / `SAQ::PendingQuests()` | 解析层复用（不重复猜偏移）+ 数据源接线（与 SWF 推送同一份数据） |
| op | `SAQ_Test.cpp`：`ui.inject`（`Kind::kUiInject`） | harness 段内；一行产品日志 `界面注入PoC …`（红线六） |
| 计划 | P2 计划 +`[case:r133_inject_data]` | 两条断言（首行 + 五段同现）+ 眼睛窗口 30 s |
| verify | +8 条 DLL 特征串 + 5 条 P2 计划形状检查 | dev 正向 / 发布反向（注入模块整体在 `SAQ_WITH_HARNESS` 内编译） |
| 正则自检 | `p2_plan_regex_check.py` +样例「界面注入PoC」 | 编译 + 样例匹配（9 条正则 / 6 条样例） |

**链路（`RunInjectPoC`，一次跑完 —— 判据一行汇总）**：
R1 环境 → R2 语言（引擎任务名 CJK，U8a 同源）→ R2.5 **回 $ALL**（防「菜单恢复上次分类」
导致快照只是子集）→ R3 引擎快照（逐条 `GetDataForEntry` 的**引用数组**）→ R4 构造我们的
条目（真实数据）→ R5 扩 tab（7→8）→ R6 挂 priority=100 拦截 → R7 切 7（拦截 + 设 mask +
注入）→ R8 对账（前 2 条 uID/名字/置灰）→ R9 切 0（**恢复引擎快照**）→ R10 再切 7（供眼睛）
→ 汇总。

**关键机制（与原版行为逐项对齐 —— 本轮的新事实）**：
- ★ 原版 `onFilterChanged`（`MissionMenu.as:2336-2346`）在切 tab 时**只设 `filterMask`、
  不重建列表** ⇒ 分时注入必须「切到我们 tab 注入 / 切走恢复快照」**两边都自己做**
  （与 SWF 版「一次性合并 + 掩码过滤」完全不同）；
- 原版 `FilterInfoA` 只有 7 项（private、改不了）⇒ 第 8 个 tab 必须拦截
  （否则原版读 `FilterInfoA[7].flag` = TypeError）；
- 我们的 tab flag = `1<<6`（`AVAILABLE_QUEST_TYPE=6`，与条目 `iType=6` 配对才有显示）；
  `$ALL` 用**原版值** `0xFFFFFFFF`（不像 SWF 版改 `0xFFFFFFBF` —— 切走即恢复，
  「全部」里不会出现我们的条目 ⇒ 不需要改）；
- 原版 7 项 tab 的 flag 映射（从 SWF 版 `PopulateTabs` 逐项抄）：`$ALL=0xFFFFFFFF` /
  `$Main=1<<1` / `$Faction=1<<2` / `$Misc=1<<3` / `$MISSION=1<<4` / `$Activity=1<<0` /
  `$Completed=1<<5`（`QuestUtils` 枚举 ACTIVITY=0 / MAIN=1 / FACTION=2 / MISC=3 /
  MISSION=4 / COMPLETED=5 / AVAILABLE=6 —— P2 实测「切 3 → mask 0x08」吻合）；
- 条目字段 = 探针 v4 已验证最小集 + 真实值（`uID`=真实任务 FormID / `iType=6` /
  `aObjectives=[]` / `bCanShowOnMap`=有无引导目标 …）；名字前缀（可重复 / 不可导航）与
  描述主干按 SWF 版规则拼。

**边界 / 已知差异（P3-b 或以后处理）**：
- 描述文案 = **主干简化版**（缺 SWF 版 `SaqDescriptionText` 的「按键名提示」等细节分支）；
- 图标：`iType=6` + `iFaction=-1` 时原版 `GetQuestIconLabel` 走 default 分支（PoC 接受）；
- watchdog（引擎推送覆盖我们的注入后重放）与 `UiMode` 运行期开关 = P3-b；
- 点击条目：原版 activate 路径尚未接管（P4）—— 眼睛窗口建议**只切 tab 看列表**；
- 监听**故意保留**（不 `removeEventListener`）：眼睛窗口里玩家切 tab 要靠它
  （没有它切到第 8 个 tab 会触发原版越界 TypeError）；副作用随 `menu.close` 清理。

**离线验证（全绿）**：DLL 开发构建（harness）**1141248 B**（1117184 → +24064；含注入
模块）；P2 实验态部署（`*.p2off` + `Harness=1` + `Plan=SAQ_TestPlan_p2.txt` +
`AutoLoad=…142854_2_0_4`；工作区 == 部署哈希一致）；`verify --dev --p2` **797 行 / 0 MISS**
（+8 特征串 + 5 计划形状）；离线层 **5 步全过**；`p2_plan_regex_check` **9 条正则 / 6 条
样例全过**。

**判读表（P2 会话 4 条 = r120 / r125 / r130 / +`r133_inject_data`；首跑 = 第 134 轮，见下）**：

| 段 | ok 的含义 |
| --- | --- |
| `快照=ok（N 条）` | 引擎条目引用可全量读回（`GetDataForEntry` 逐个）⇒ 恢复手段成立 |
| `扩tab=ok（7→8）` | `SetTabsData` 8 项（前 7 项原版 text/flag）被接受 |
| `注入数据=ok（entryCount N→M，期望 M）` | **真实数据注入**生效（M = 产品待推送列表长度） |
| `对账=ok（0x…:名字｜可导航0/1）` | 注入后读回的前 2 条与构造期望逐项一致（uID/名字/置灰） |
| `恢复=ok（切0 后 entryCount →N，期望 N）` | 切走我们 tab 后引擎列表**完整恢复**（分时注入闭环） |
| `再注入=ok` + `眼睛=…` | 界面停在我们的 tab（真实列表），供眼睛确认 |
| 眼睛 | 第 8 个 tab「可接任务」+ **真实可接任务列表**（真任务名/描述）；切回原版 tab = 原版内容 |

**实机首跑与收口（第 134 轮 · 19:14~19:16 P2 会话 4 条）**：

① 结果：`r120_gfx_poc` **PASS**（六段全 ok + 注入 1→3）/ `r125_ui_conflict` **PASS** /
`r130_gfx_migrate` **PASS**（U5~U10 全绿）/ **`r133_inject_data` FAIL**（唯一）——
`ui.inject` 汇总 = 「待推送=0（菜单还没打开或这次没有可接任务 —— 先 menu.open 再看）」，
两条断言无行。判据 = `check_results` 3/4 + `log_hygiene` 退出码 0（日志 57036 B / 130 行
零坏字节）+ `plan_regex_audit` 8/10（未命中 2 条 = r133 两条断言，同源）。

② ★ 真因（**产品级缺陷，不是用例问题**）：`TryPushPending` 的 notOurs 分支
（`SAQ.cpp` 第 125 轮代码）里 `g_pending.quests.clear()` —— notOurs（原版 / 第三方 SWF）
**恰恰是注入形态要工作的场景** ⇒ 菜单打开时收集的 206 条在推送判定（停推降噪）时被清空
⇒ `SAQ::PendingQuests()`（注入唯一数据源）读到空 ⇒ `RunInjectPoC` 在空数据分支提前返回。
日志证据链：19:15:41.099 `菜单打开：…待推送=206` → :41.950 `UI 通道不可用（第 2 次推送
失败后判定）` → :42.909 `界面注入PoC 待推送=0`。r120/r130 探针（假数据）不依赖
`PendingQuests()` ⇒ 不受影响 —— `r133` 是首条依赖它的用例，一次把缺陷照出来。

③ ★ 修复（生命周期解耦）：`g_pending.quests` 生命周期 = **一次菜单打开周期**
（`OnMissionMenuOpened` 收集 → `OnMissionMenuClosed` 释放）；4 个推送子分支
（推送成功 / 菜单就绪超时 / notOurs / 推送放弃）一律**不再清数据**。产品化理由：P4 分时注入
（每次切到我们 tab 都要注入）本来就要求数据在菜单打开期间常驻 —— 前置修掉，P4 不再踩。

④ 离线判据（全绿）：DLL **1141248 B**（哈希 `0D28150206FC8117…67112DAD`；工作区 == 部署）
+ `verify --dev --p2` **798 行 / 0 MISS**（+1 条源码级检查：`g_pending.quests.clear();`
恰好 2 处 —— 防「推送子分支顺手清」回归）+ 离线层 5 步全过 + P2 正则自检 9/6。

⑤ 复跑判据（下一会话，4 条用例）：`r133_inject_data` 期望上表五段全 ok（`entryCount`
期望 206 = 当次待推送条数）+ 眼睛 = 第 8 个 tab「可接任务」+ 真实 206 条列表。

### 十三·补、复跑实测与第二处缺陷修复（2026-09-23 · 第 135 轮）

**复跑（19:25~19:29 P2 会话 · 4 条）**：第 134 轮修复（数据生命周期）一击生效 ——
`回ALL=ok（mask 0xFFFFFFFF,entryCount 1）/ 快照=ok（1 条）/ 扩tab=ok（7→8）/ 监听=ok`，
`RunInjectPoC` 也拿到了 **206 条**（不再提前返回「待推送=0」）；但 `r133_inject_data`
仍 FAIL（4 条 **3 PASS / 1 FAIL**），其余三条与基线同型。

**① 新真因（产品级缺陷 · 注入上下文未接线）**：`InjectCtx::list`（= `MissionsList_mc`）
**从未被赋值**（默认构造的空 `GFx::Value`），而拦截 handler 的两条路径（切到我们 tab：
设 `filterMask` + `InitializeEntries`；切走：恢复快照）**全部操作 `ctx.list`** ⇒ 二者
必然失败。日志逐行吻合：
- `界面注入：切到我们的 tab（idx=7）→ mask=0x40（写入失败！） + 注入 206 条（fail）`；
- `对账=fail（0x002C5401:一小步｜可导航1）` —— 列表压根没换（玩家看到的还是原版那条
  「一小步」；旧诊断打「期望 uID + 实际名字」的混合值，把「没换」读成了「uID 对上」）；
- `恢复=ok` 是**假 PASS**（注入从未生效，`entries2 == engineCount` 因 1 == 1 巧合成立）。
- 为什么此前没暴露：R1~R6（环境 / 回 ALL / 快照 / 构造 / 扩 tab / 挂监听）用的都是
  **局部** `list`；只有「切 tab 的注入路径」（handler 内）走 `ctx` —— P3-a 之前没有任何
  用例触发过 handler 的这两个分支（r120 / r130 探针各自持有自己的对象）。

**② 修复（三处，`SAQ_UiInject.cpp`）**：
- ★ 核心：R3 快照前 `ctx.list = list;`（异步 handler 在上下文里持有菜单打开期间的引用）；
- **上下文自检**段 `｜上下文=ok`（读一次 `filterMask`）—— 这类缺陷以后一眼可见；
- 对账诊断改打**实际读回值**（`实际 0x…:名字｜可导航N（期望 0x…）`）—— 混合值不再误导；
- 恢复判据加 `passInject` 前置（注入没成功 ⇒ `恢复=fail`，消灭「1 == 1」假 PASS）。

**③ 离线判据（全绿）**：DLL **1142272 B**（+1024）；P2 实验态部署（`*.p2off` +
`Harness=1` + `Plan=SAQ_TestPlan_p2.txt` + `AutoLoad=…142854_2_0_4`；工作区 == 部署）；
`verify --dev --p2` **800 行 / 0 MISS**（+1 特征串「｜上下文=」+1 源码级检查
「`ctx.list = list;` 恰好 1 处」）；离线层 **5 步全过**；P2 正则自检 9/6。

**④ 复跑判据（下一会话 · 4 条）**：`r133_inject_data` 期望五段全 ok（`entryCount` 期望
206 = 当次待推送条数；`对账=ok（实际 0x002C5401:超越极限｜可导航1（期望 0x002C5401））`）
+ 眼睛 = 第 8 个 tab「可接任务」+ 真实 206 条列表（切回原版 tab 恢复原版内容）。

### 十三·补二、复跑收口（2026-09-23 · 第 136 轮 —— 4/4 全 PASS）

**会话（19:55~19:59 P2 会话 · 4 用例 / 35 步 / 184000 ms）**：**PASS 4 / FAIL 0 /
SKIP 0**（P2 实验态全量全绿）。`r133_inject_data` **PASS（32063 ms）** —— 第 135 轮
修复（`InjectCtx::list` 接线）**一击生效**，判读表五段与预测**逐字一致**：

| 判据 | 实测 |
| --- | --- |
| `上下文=ok` | ✅（第 135 轮新增自检段 —— 「这类缺陷以后一眼可见」成立） |
| `快照=ok（1 条）` | ✅ |
| `扩tab=ok（7→8）` | ✅ |
| `注入数据=ok（entryCount 1→206，期望 206）` | ✅ 与当次待推送 206 一致 |
| `对账=ok（实际 0x002C5401:超越极限｜可导航1（期望 0x002C5401））` | ✅ **与第 135 轮预测逐字一致**（首条 = 势力入口固定「超越极限」） |
| `恢复=ok（切0 后 entryCount →1，期望 1）` | ✅ 真恢复（`passInject` 前置下成立 —— 不再是「1 == 1」假 PASS） |
| `再注入=ok（entryCount →206，供眼睛）` | ✅（30 秒眼睛窗口） |

★ 两条关键诊断行（修复前 = 「mask=0x40（写入失败！） + 注入 206 条（fail）」）：
`界面注入：切到我们的 tab（idx=7）→ mask=0x40 + 注入 206 条（ok）` —— **写 + 注入双成立**；
`界面注入：从我们的 tab 切走（idx=0）→ 恢复引擎列表（ok）`。

**其余三条与基线同型**：`r120_gfx_poc` PASS（六段全 ok + 注入 1→3）/ `r125_ui_conflict`
PASS（`UI 通道不可用` 判定行 + `assert.nolog 推送放弃`）/ `r130_gfx_migrate` PASS
（U5~U10 全绿：`接管=ok（回调收到 1 次）` / `关菜单入口=ok` / `造对象=ok（三级 + 接线
UserEvents=1）`）。

**判据（五连全绿）**：
- `check_results` **4/4**（退出码 0）；
- `log_hygiene` 退出码 0（日志 59655 B / 135 行 = **122 I + 13 W + 0 E** —— W 全为
  「原版 SWF 推送失败」预期现象（4 个菜单周期 × 3 条 + 1 条桥解析诊断）；结果 JSON
  75 行零坏字节）；
- `plan_regex_audit`（P2 计划）**10/10 全命中**（4 个用例段全在）；
- `verify --dev --p2` **800 行 / 0 MISS**；`p2_plan_regex_check` **9 条正则 / 6 样例**；
- 离线层 **5 步全过**（决策单测 / 折叠内核自检 / 黄金快照 4 件一致 / tripwire / P2 正则自检）。
- DLL 工作区 == 部署（**1142272 B**，SHA256 `3FF24385…43723553`）。

**眼睛（★ 玩家已确认）**：30 秒窗口（19:57:57.373 再注入 → 19:58:27 menu.close）第 8 个
tab「可接任务」+ **真实 206 条列表**（真任务名/描述）—— 玩家确认「第 8 个 tab「可接任务」
+ 真实任务列表都看到了」⇒ **判据 + 眼睛双达成，P3-a 完全收口**。

**结论**：P3-a（真实数据注入）**完全收口（判据 + 眼睛双达成）** —— 「分时注入」闭环
（切到我们 tab ⇒ 注入 206 条 / 切走 ⇒ 完整恢复引擎列表）在「无 SWF 覆盖」形态下
**产品级成立**。

**下一步（玩家已定 = 直接进 P3-b；P2 实验态继续保留）**：完整 `SaqDescriptionText`
文案迁移 + watchdog（引擎推送覆盖我们的注入后重放）+ `UiMode` 运行期开关
（ini `[UI] UiMode=swf|auto|inject`，默认 `auto`；`swf` = 行为与现状逐字节不变）
⇒ P4 交互接管。

### 十三·补三、P3-b 落地（2026-09-23 · 第 137 轮 —— 注入形态产品化）

**三块内容**（玩家已定「直接进 P3-b、P2 实验态继续保留」）：

① **完整 `SaqDescriptionText` 迁移**（`SAQ_UiInject.cpp` `BuildDescription`）：SWF 版
   `MissionMenu.as` 882~983 行的**逐字搬运** —— 入口（板 100 / NPC 101）× 有无按键名 /
   同伴完整句 / 势力「简要说明」/「需要靠近」句 / 无导航目标三分支 / 尾部句（同伴 vs
   普通）× 有无按键名；按键名 = `Menu_mc.KeyHelper.GetButtonNameForEvent("XButton","")`
   （取不到 ⇒ 空串 ⇒ 走「使用底部的『设定航线』」分支）。**两形态描述从此一致**
   （以后改文案要两处同步：`SaqDescriptionText` + `BuildDescription`）。

② **watchdog**（`OnMenuTick`，500 ms 节拍）：玩家在我们的 tab 上时，检查列表是否仍是
   我们的注入数据（`entryCount` + 首条 `uID` 双判据）—— 引擎刷新覆盖（任务状态推送 /
   原版重建列表）⇒ 重放（设 mask + `InitializeEntries(ourEntries)`）；日志节流
   （首次 + 每 10 次 —— 引擎频繁刷新不刷屏）。

③ **`UiMode` 运行期开关**（ini `[UI] UiMode=swf|auto|inject`，默认 `auto`）：
   · `swf` = 行为与现状逐字节不变（注入代码不激活）；
   · `auto` = SWF 优先；推送失败判定 notOurs ⇒ **自动切注入**（Tick 里 150 ms 节流激活）；
   · `inject` = 只用注入（菜单打开后不推送）。
   ★ HUD 提示改「延迟判定」：auto / inject 下注入激活成功 ⇒ **不提示**（功能已生效）；
   3 秒（`kInjectNoticeGraceMs`）还没起来才补发「UI 通道不可用」（与第 125 轮语义衔接，
   且保持进程内一次）。
   ★ 激活对玩家「无感」：记原 tab（`selectedIndex`）→ 切 0 取全量快照 → 切回原 tab
   （挂监听之前走原版路径）。

**分层改造**（隔离纪律的延续）：
- `SAQ_UiInject.{h,cpp}` 不再整体包在 `SAQ_WITH_HARNESS` 里：**产品路径**（类型探测 /
  完整描述 / 激活 / watchdog / UiMode）**发布构建也编译**；harness 探针
  （`RunInjectPoC` / `ui.inject`）仍在 harness 段（输出格式与第 135 轮**逐字一致** ——
  verify / P2 计划依赖它）。
- `SAQ.cpp` 接线：`ResolveUiMode()`（ini 读取，未知值 WARN + 按 auto）+ Tick 的 open
  分支（`UiInject::OnMenuTick` + 提示兜底）+ 菜单打开读形态 + 菜单关闭清理
  （`UiInject::OnMenuClosed`）+ `TryPushPending` 的 inject 短路 + `PollUiReport` 跳过。

**离线判据（全绿）**：DLL 开发构建（harness）**1160704 B**（1142272 → +18432）；
P2 实验态部署（工作区 == 部署；SWF 覆盖 `*.p2off` + `Harness=1` + `Plan=SAQ_TestPlan_p2.txt`
+ `AutoLoad=…142854_2_0_4`）；`verify --dev --p2` **824 行 / 0 MISS**（+12 条产品路径
特征串 dev/release **双向**正向 + 源码级结构/分层检查 + ini 模板 [UI] 段 + P2 计划形状）；
离线层 **5 步全过**（P2 正则自检 **12 条正则 / 9 条样例**）；ini 模板
（`resources/`）与部署 ini 均含 `[UI] UiMode=auto`。

**P2 计划 +1 条用例 = `r137_product_inject`**（产品路径验收 —— **不依赖 `ui.inject`
原语**）：`界面形态：UiMode=auto` + `界面注入：已激活（UiMode=auto，…）`（约菜单打开后
1~2 秒：推送 2 次失败 + 判定 + 节流）+ `菜单关闭：本轮为注入形态（已激活；watchdog
重放 N 次）`；30 秒眼睛窗口（玩家切到第 8 个 tab 看真实列表）。

**待实机（下一次 P2 会话 5 条）**：`r120` / `r125` / `r130` / `r133` / **`r137`**；
眼睛 = 第 8 个 tab「可接任务」+ 真实列表（**产品路径**，不靠探针）；观察项 = watchdog
是否触发（引擎刷新场景 —— 平时应保持 0 次）。

### 十三·补四、P2 会话判读与两处修复（2026-09-23 · 第 138 轮 —— 5 条 3 PASS / 2 FAIL 的根因与收口）

**会话（20:20~20:24 / 187094 ms / P2 实验态 · 原版 SWF / 5 用例）**：
`r120_gfx_poc` **FAIL**（10078 ms）/ `r125_ui_conflict` PASS（4828 ms）/ `r130_gfx_migrate`
PASS（33406 ms）/ `r133_inject_data` **FAIL**（17079 ms）/ **`r137_product_inject` PASS**
（37531 ms）。判据 = `check_results` 3/5 + `log_hygiene` 退出码 0（250 行零坏字节）+
`plan_regex_audit` 11/13（未命中 2 条与 FAIL 同源）+ `verify --dev --p2` 0 MISS + 离线层 5 步。

**★ 产品路径本身成立（r137 全绿 —— 第 137 轮三块全部实机验证）**：
`20:23:00.954 界面形态：UiMode=auto` → `20:23:01.781 界面注入：已激活（UiMode=auto，
tab 7→8，条目 206，按键名=(空)，语言=zh）`（推送 2 次失败 → notOurs 判定 → 自动激活，
时机 ≈ 菜单打开后 1.2 秒）→ `20:23:36.017 菜单关闭：本轮为注入形态（已激活；
watchdog 重放 0 次）` ⇒ **watchdog 0 次（符合预测：无引擎刷新）**；r125 判定行 + 无
「推送放弃」照旧。

**根因（两条 FAIL 同源）= 第 137 轮产品路径抢先激活，打破探针的「原版 7 tab 干净环境」
前提**：
- `r120`：产品先在 20:21:53.442 激活（tab 7→8）⇒ 探针看到 `环境=(numTabs 8,…)`、
  自己再扩 `8→9`、切的是 `切8=ok（拦截 1 次）` —— 探针五段本身全 ok，只是断言硬编码
  `切7=ok` 等不到（实际是 `切8`）。**探针自适应正常，断言过窄（用例侧）。**
- `r133`：产品先激活（20:22:43.884）⇒ 探针 `扩tab=fail（8→8）`（`SetTabsData` 8 项后
  `numTabs` 不变，判据 `tabs1 == tabs0+1` 不成立）⇒ 后续级联 fail（注入数据/对账/恢复）。
  且 `ui.inject` 开头 `g_ctxStore = InjectCtx{}`（重建共享上下文）把产品 `menuActive`
  清成 false ⇒ 产品每 150 ms 重试激活（tab 数已是 8 ⇒ 扩 tab 永远 fail）——
  **20:22:44.883~20:22:59.873 共 96 条 `激活失败` WARN / 15 秒，每次全量重建
  （切0 + 快照 + 构造 206 条）= 真产品缺陷：失败无退避、日志无节流、纯烧 CPU。**

**修复（两条线）**：
1. **产品侧（真缺陷）**：`ActivateForMenu` 区分失败性质 —— 早退（数据未收集 / 桥未通 /
   `Menu_mc` 缺）保持静默 150 ms 重试；走到快照/构造/扩tab/监听任一失败 = **决定性
   失败** ⇒ `ctx.activateFailed = true`（本菜单周期不再重试，菜单重开再试）+ 一条 WARN
   （含 `tab x→y` 数字 + 「本次菜单不再重试」—— 既是诊断也是回归特征串）。
   `OnMenuTick` 激活分支开头据此提前返回。
2. **测试侧（用例隔离）**：新 harness op **`ui.mode <swf|auto|inject|reset>`** ——
   运行期强制形态（`ForceMode` / `ClearForceMode`；强制期间忽略菜单打开时的 ini 解析）。
   P2 计划各用例显式设形态：探针（`r120`/`r130`/`r133`）= **`ui.mode swf`**（产品不激活、
   干净 7 tab 环境）；`r125`/`r137` = **`ui.mode auto`**（产品路径行为）。判读新增一行
   产品日志 `界面形态覆盖：UiMode=swf（harness 强制；reset 清除）`。
   （`ForceMode` 实现放文件末尾 harness 段 —— 产品段保持「无预处理指令」的分层纪律。）

**离线判据（全绿）**：DLL 开发构建（harness）**1161728 B**（+1024）；`verify --dev --p2`
**829 行 / 0 MISS**（+2 harness 特征串 +1 产品特征串 +2 计划形状；分层检查修正 =
`ForceMode` 移入 harness 段）；离线层 **5 步全过**（P2 正则 12/9）；P2 态已重新部署
（工作区 == 部署；`ui.mode` 5 处已进部署副本）。

**待实机（P2 会话重跑 5 条）**：预期 **5/5 全 PASS**（探针恢复干净环境 7→8；产品路径
照旧）+ 眼睛（第 8 个 tab「可接任务」+ 真实列表 ×2 形态）。

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
