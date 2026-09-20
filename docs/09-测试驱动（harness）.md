# 09 · 引擎内测试驱动（harness）

> 2026-09-20 第 49 轮建立。目的：把「进游戏测一次很贵、人工操作覆盖不全、存档不一定满足
> 条件」这三件事拆开解决 —— **判据写成用例文件，由 DLL 在引擎里自动执行**。
>
> 普通玩家不受影响：一切只在 ini `[Test] Harness=1` 时激活，且 Nexus 包用不带 harness
> 的构建（见本文末「发布包」）。

## 一、为什么是这个方案

| 痛点 | 这一轮的做法 |
| --- | --- |
| 进游戏贵（启动 + 读档 + 手点） | 一次启动跑完一批用例：DLL 自己开关菜单、自己选中条目、自己按键、自己断言 |
| 人工操作覆盖不全 | 判据落成用例（可枚举、可重复、可 diff），不再靠「回忆着点一遍」 |
| 存档不一定满足条件 | 用例自己**造状态**：`Quest.Reset/Start/SetStage/CompleteQuest` + `Actor.MoveTo` 传送 |
| 失败现场丢了（日志 1MB 滚动） | 失败时把「本步骤之后的日志」抄进结果 JSON 的 `evidence` 字段 |

**一条硬边界**：Starfield 不能真正无头（D3D12 + 引擎启动流程），所以 harness 仍然是
「在游戏进程里跑」，但它把**人的动作**全部消掉了。运行环境可以放虚拟桌面/独立会话
（本项目选的是「你手动启动游戏、harness 自动跑完」的最小风险路线）。

## 二、为什么写侧动作绕道 Papyrus（而不是 DLL 直调原生函数）

`docs/04` 2.1 节早就定案了：Papyrus 原生函数的调用约定是 `rcx=VM, rdx=栈帧, r8=self`
—— DLL 直接调它们要**伪造 VM 栈帧**（commonlibsf 里 `BSTThreadScrapFunction` 只是被
别名成 `std::function`，ABI 未验证）。所以：

```
DLL（SAQ_TestOps）                      Papyrus（SAQ_Main.ProcessTestCommand）
─────────────────                       ─────────────────────────────────────
写 ArgA/ArgB/ArgC                       读参数 → Quest.Reset/Start/SetStage/
写 Cmd                                         CompleteQuest、Actor.MoveTo
写 Seq  ← 提交点（最后写）              → 写 Result（结果码）+ 写 Ack = Seq
轮询 Ack == Seq
```

写侧动作在 Papyrus 里就是**语言级 API** —— 零 RVA、零特征字节、零栈帧。这是本轮
「不需要任何新 RE 工作」的原因。

## 三、通道（ESM 追加的 8 条 GLOB）

`tools/esm/patch_saq_esm.py` 的 `TEST_GLOBS`，记录号 **0x806~0x80D**（纯追加，
旧记录号 0x800~0x805 / 0x900+ 一个字节都不动 —— 存档按 FormID 记录脚本实例）：

| 记录号 | EDID | 方向 | 用途 |
| --- | --- | --- | --- |
| 0x806 | `SAQ_TestSeq` | DLL→脚本 | 序号，**提交点** |
| 0x807 | `SAQ_TestCmd` | DLL→脚本 | 操作码（1=Ping 2=Reset 3=Start 4=SetStage 5=Complete 6=Teleport） |
| 0x808 | `SAQ_TestArgA` | DLL→脚本 | FormID 低 24 位 |
| 0x809 | `SAQ_TestArgB` | DLL→脚本 | FormID 高 8 位 |
| 0x80A | `SAQ_TestArgC` | DLL→脚本 | 数值参数（stage 等） |
| 0x80B | `SAQ_TestAck` | 脚本→DLL | 已执行到的序号 |
| 0x80C | `SAQ_TestResult` | 脚本→DLL | 结果码（0 成功 / 1 表单取不到 / 2 类型不对 / 3 异常 / 4 未知操作码） |
| 0x80D | `SAQ_TestHarness` | 双向 | 总开关：0=关；**1=DLL 请求启用**；**2=脚本已就绪** |

### 为什么要有「1 → 2」这一步

脚本在通道初始化时会把「已执行序号」**追平当前 Seq**（避免读档后把上一局残留的命令
重放一遍）。所以 DLL 必须先等脚本就绪（`Harness==2`）再下第一条命令，否则第一条必超时。

DLL 侧还会在首次就绪时把**自己的序号追平通道里的值**（读档后通道里的值可能更大），
并在每次提交前再跳一次 —— 否则可能「撞上一个已经存在的 Ack」而被判成假成功。

### 脚本怎么找到这 8 条 GLOB（不需要 VMAD）

脚本用**自己任务的 FormID 前缀**（`GetFormID() >> 24`）算出完整 FormID，再
`Game.GetForm()` 动态取。于是 ESM 只需要追加 GLOB，**VMAD 一个字节都不用碰**。
已知限制：前缀 ≥ 128（加载顺序里超过 127 个全量插件）时 Papyrus 的 int 会溢出，
此时 harness 自动关闭（与 `CurrentGuideTargetFormID()` 同一限制）。

## 四、时序红线（用例作者必须知道）

第 27 轮实测定案：**菜单开着 = 游戏暂停 = Papyrus 定时器冻结** ⇒ 命令只在菜单关着时
被消化。所以：

* 造状态的步骤必须排在 `menu.open` **之前**；
* 断言引导结果的步骤必须排在 `menu.close` **之后**；
* 驱动器对「菜单开着时遇到命令步骤」会自动关菜单并记 WARN（容错，但会留下证据）。

## 五、用例文件（ini 风格，零依赖）

位置：mod 目录的 `SFSE\Plugins\SAQ_TestPlan.txt`（名字由 ini `[Test] Plan` 指定）。
仓库里的源在 `tools/test/scenarios/SAQ_TestPlan.txt`，部署时自动拷过去。

```
[case:名字]
desc = 说明（可省）
step = <操作> [参数] [timeout=毫秒]
```

### 步骤一览

| 操作 | 语义 |
| --- | --- |
| `ping` | 通道往返（最轻的自检） |
| `quest.reset <fid>` / `quest.start <fid>` / `quest.stage <fid> <n>` / `quest.complete <fid>` | 造任务状态（Papyrus 语言级 API） |
| `teleport <fid>` | 把玩家传到某个引用（触发 cell 加载） |
| `wait <ms>` | 等 |
| `menu.open` / `menu.close` | 开/关任务菜单（`UIMessageQueue::AddMessage` 的 kShow/kHide，与已实测的关菜单同一机制） |
| `ui.tab` | 切到「可接任务」tab 并重建列表 |
| `ui.select <uID>` / `ui.expand <uID>` | 选中/展开某一行（按 uID 在显示列表里找行） |
| `ui.key <事件名>` | 送一个 user event（`XButton` = 键盘 R / 手柄 X；`Accept` = 回车/点击） |
| `assert.log <正则>` | 内存日志环形缓冲里找（只找**本步骤之后**的行） |
| `assert.ui <正则>` | 读 AS3 `SAQ_Report` 自报状态 |
| `assert.menu open\|closed` | 任务菜单开关状态 |
| `guide.clear` | 取消引导（teardown；走产品路径 `Guide::SetGuideTarget(0)`） |
| `note <文本>` | 只打一行标记（分段用） |

默认步骤超时 5 秒（命令类 3 秒、菜单类 8 秒）。一条用例第一个失败步骤即停（后面的
步骤多半没意义），证据留在结果里。

### ★ 界面测试入口走真实路径

`MissionMenu.as` 的 `SAQ_TestDrive*` **不复制逻辑**，而是调用真实处理函数 ——
否则测的是测试代码：

| 入口 | 内部调用 |
| --- | --- |
| `SAQ_TestDriveKey` | `ProcessUserEvent(事件名, false)`（与玩家按键同一条链，含**按钮启用判定**）；`Accept` 走 `MissionsList.onEntryPress`（与鼠标点击同一条链） |
| `SAQ_TestDriveSelect` | 设 `selectedIndex` 后派发 `ScrollingEvent.SELECTION_CHANGE`（原版列表自己派发的就是它） |
| `SAQ_TestDriveExpand` | `MissionsList.ExpandOrCollapseSelection()` |
| `SAQ_TestDriveTab` | `MissionTabbedSelection.SetSelectedCategoryIndex(idx)` → 内部 `SetSelectedIndex` → 派发 `BSTabbedSelectionEvent` → `onFilterChanged`（与玩家切 tab / 原版读档恢复分类同一条路）+ `SaqRefresh()`；★ 第 52 轮修正：**不能写 `selectedIndex`（只读，抛 `Error #1074`）**，见第十二节 |
| `SAQ_TestDriveState` | 轻量状态串（tab/mask/条数/选中项），给断言用 |

按键语义核对过官方 Interface 源码：`MinimalButton.HandleUserEvent` 只在
**松开**（`!abPressed`）时回调 ⇒ DLL 送的是 `(事件名, false)`。

## 六、结果与查看

跑完写 `SFSE\Plugins\SAQ_testresults.json`（带 BOM；`summary` + 每条用例的每个步骤 +
失败步骤的证据）：

```powershell
python tools\test\check_results.py                # 默认读 MO2 部署目录里的那份
python tools\test\check_results.py <路径> --tail 40
```

退出码：0 全 PASS；1 有 FAIL/SKIP；2 结果文件不存在/解析不了。

## 七、怎么跑（当前流程）

```powershell
# ① 构建 + 部署，并把 ini 的 Harness 写成 1
& ".\tools\build-saq.ps1" -SkipTable -Harness

# ② 启动游戏（MO2）→ 读一个存档 → 什么都不用点
#    等日志出现：harness：全部用例结束

# ③ 看结果
python tools\test\check_results.py
```

* ★ **先备份存档**：harness 会改任务状态（`Reset/Start/Stage/Complete`），别在主力存档上跑。
* `Harness` 在插件加载时读一次；此外驱动器**每 2 秒复查**本文件 ⇒ 改 `0→1` 不必重启游戏
  （要重新载入用例：拨回 0 再置 1）。一轮跑完本会话不再重跑。
* ★★ **`Harness` / `Plan` 必须落在 `[Test]` 段里**。`GetPrivateProfileInt("Test", …)` 只认
  本段 —— 放在别的段（例如 `[Filter]`）会**静默不跑**：日志只有一句
  `harness：未启用（ini [Test] Harness=0）—— 引擎内自动化测试关闭`，游戏里「什么也没发生」。
  **实机踩过一次**（第 49 轮首测）：`build-saq.ps1` 原来是「把两个键追加到文件末尾」，
  而 `[Test]` 段在文件中间 ⇒ 键落进了 `[Filter]` 段。现在构建脚本改成「插在 `[Test]` 行之后」，
  并在 ini 模板里写了这条警告。
* 若日志里只有 `harness：已请求启用（SAQ_TestHarness=1），等脚本回写 2` 而没有
  「通道就绪」⇒ ESM 没打补丁 / 脚本没跑，用 `verify_saq_build.py` 的
  `ESM(…) · 测试命令通道 GLOB 8/8` 与 `PEX · 测试通道已就绪 Trace` 两条先排除。
* ★★ **无参入口必须按 0 参调用**（第 49 轮补丁，首测踩坑 ②）：`SAQ_TestDriveTab()` /
  `SAQ_TestDriveState()` 在 AS3 里是 **0 参**。`InvokeUiTestDrive` 原来无条件传 1 个参数
  （空字符串占位）⇒ Scaleform `Invoke` **直接失败**（耗时 0 ms，回
  `_root.SAQ_TestDriveTab=fail(路径不存在或调用失败；SWF 是旧版？)` —— 文案会误导成「SWF 旧版」，
  实际用 FFDec 反编译 `-export script` 能看到方法就在类里）。对照证据：同一 `_root` 上
  0 参的 `SAQ_Report`（走 0 参调用）与 1 参的 `SAQ_Probe`（走 1 参调用）都成功。
  现在 `a_arg` 为空即走 `numArgs=0`。规律：**实参个数必须与 AS3 签名一致**，别拿空串占位。
* 用例失败中止时（如首测卡在 `ui.tab`），后面的 `menu.close` 不会跑到 ⇒ 任务菜单会留在屏幕上
  （游戏暂停、脚本定时器冻结，要玩家手动按 Cancel）。补丁起 `finishAll`（含失败）会自动
  `kHide` 关掉菜单（日志 `harness：结束时菜单还开着 —— 已请求关闭`）。
* ★★ **SWF 改动必须「完全重启游戏」后才生效 —— 而且重启要点在构建部署之后**（第 50 轮查明）。
  Starfield 的 UI 资源在**游戏启动阶段**加载，早于 SFSE 插件加载日志里的时刻。实测（22:43~22:48）：
  SWF 22:43:58 部署 → 插件加载日志 22:46:41 → 22:48 跑用例仍是旧 SWF 的行为（`ui.tab` 0 ms 失败）；
  而 FFDec P-code 导出证明新 SWF 里的挂载与 traits 完全正确、DLL 里 0 参调用也正确
  ⇒ 唯一解释就是「游戏进程启动太早，界面还拿着部署前的旧 SWF」。
  ⇒ **跑测试的正确顺序：① 构建 + 部署完成；② 再启动游戏**（顺序反了就得重启游戏重来）。
  ⇒ 判定「游戏加载的是哪一版 SWF」：看 `SAQ_Report` 输出里有没有 `stamp=` 字段（新版构建有；
  没有 = 旧版）。`ui.tab` 失败时 DLL 会自己再读一次 `SAQ_Report` 并把结论写进失败详情
  （`｜SWF 指纹=…（新版 SWF 已加载 ⇒ 失败与 SWF 版本无关）` 或
  `｜…没有 stamp= 字段（⇒ 游戏加载的还是旧版 SWF…）`）。

## 八、第一条用例（smoke）与它的判据

`[case:smoke]` —— 目的是证明每一段都通，不挑任务难度：

目标任务 = 「沙布罗的解决方案」（`0x0006E0A1`，赛格哈特服饰店 / 新亚特兰蒂斯城）：
基础游戏任务、首选引导候选是**常驻的具名 NPC**（迪特里希·赛格哈特）⇒ 远处点引导也会
立即生效，不依赖「靠近才加载」。

| # | 步骤 | 期望（日志/结果里的证据） |
| --- | --- | --- |
| 1 | `ping` | 结果码 0（0.5~1 个轮询节拍内回执） |
| 2 | `quest.reset 0x0006E0A1` | 结果码 0（这条任务回滚成「可接取」） |
| 3 | `menu.open` + `assert.log 推送成功` | 菜单打开、C++ 载荷推送成功 |
| 4 | `ui.tab` / `ui.select 0x0006E0A1` | AS3 回 `ok|idx=…`；`assert.ui src=cpp` 命中 |
| 5 | `ui.key XButton` | `引导请求：…` 出现在 DLL 日志 |
| 6 | `menu.close` + `assert.log 引导已生效\|引导延迟生效\|引导确认` | 脚本在关菜单后应用引导 |

`harness：…` 开头的行是驱动器自己的日志（每一步 PASS/FAIL 都有一行）。

## 八·补、两轮实测的坑与修复（第 49 轮补丁）

### 1. ★★ 真因：新入口**没有挂到 `_root`**（补丁③，复测复查）

症状：首测（22:25）与复测（22:41）**失败形态完全相同** —— `ui.tab` 步 0 ms 失败：

```
_root.SAQ_TestDriveTab=fail(路径不存在或调用失败；SWF 是旧版？)
```

排查链（这次一步到位）：

| 疑点 | 排除方式 | 结论 |
| --- | --- | --- |
| 部署的是旧 DLL？ | 部署 DLL 907264 B / 22:36:28 == 工作区产物；会话 22:39:54 启动（在构建之后） | 排除 |
| 方法不在 SWF 里？ | SWF 特征串 + 反编译导出（首测已做）；verify 5 条测试入口检查通过 | 排除（**方法在类里**） |
| 参数个数？ | 补丁①已按 0 参调用（对 `SAQ_TestDriveTab()` 是正确约定），复测仍 0 ms 失败 | 不是（主）因 |

真因在 AS3 的**入口发布清单**：`MissionMenu` 是主时间轴的**子元件**，不是 root 本身
（第 8 轮的结论，见 `SaqPublishEntryPoint` 上方的背景注释）——C++ 只能调 `_root.xxx`，
所以每个入口都必须在 `SaqPublishEntryPoint()` 里挂一份函数引用。
第 49 轮加 `SAQ_TestDrive*` 时**只加进了类里、漏了这份清单** ⇒ `_root.SAQ_TestDriveTab`
在 root 上根本不存在 ⇒ Invoke 0 ms 失败。

同一 root 上的对照（同一会话、同一调用通道）：

| 入口 | 挂 root？ | 调用方式 | 结果 |
| --- | --- | --- | --- |
| `SAQ_Report` | ✅ | 0 参 | 一直成功（每 500ms 轮询在读） |
| `SAQ_Probe` | ✅ | 1 参 | 成功 |
| `SAQ_TestDriveTab` | ❌ | 0 参（补丁①后） | **仍失败** |

修法：`SaqPublishEntryPoint()` 追加 5 个挂载（Tab / Select / Expand / Key / State）。
教训：**加了新入口，必须同时加到那份清单里** —— 已固化成 verify 检查（见下）。

### 2. 防再犯检查（verify，+10 条）

SWF 常量池里同名常量只有一份 ⇒ 字符串检查**区分不了**「定义」与「挂载」。
所以 `verify_saq_build.py` 直接查 SWF 的**上游文本**（`ui/missionmenu/patch/MissionMenu.as`
与 lrg 版，均为构建产物、与编译进 SWF 的内容同源）：每个 `SAQ_TestDrive*` 名字
至少出现 2 次（一次 `public function` 定义 + 一次挂载清单引用）。

### 3. 补丁①（保留的有效部分）与其余修正

* **0 参入口按 0 参调用**（`InvokeUiTestDrive`）：`SAQ_TestDriveTab()` 是 0 参，
  此前无条件传 1 个空串占位 —— 这个约定本身是对的（实参个数必须与 AS3 签名一致），
  只是**不是本次的真因**；
* **失败中止也清菜单**（`finishAll`）：首测失败中止后 `menu.close` 没跑到，
  任务菜单留在屏幕上、游戏暂停；
* **降级观察期 20 秒**（候选复算，`kDowngradeHoldMs`）：读档后目标持续取不到
  ≈19 秒 ⇒ 不再误降级（[1]→[3]→[1] 对 + WARN 消失）。

### 4. ★★ 三轮失败的收口（第 50 轮）：产物全对 —— 问题在「游戏进程启动太早」

补丁③（入口挂 root）之后的复测（22:48 会话）**仍然** `ui.tab` 0 ms 失败，失败形态与首测/复测
一字不差。这一次把「产物正确性」查到了字节码级：

| 检查 | 方法 | 结论 |
| --- | --- | --- |
| SWF 里到底有没有挂载 / 方法 / 类 traits | FFDec `-format script:pcode` 导出 ABC 字节码 | ✅ 挂载语句（`pushstring "SAQ_TestDriveTab"` + `getproperty …"SAQ_TestDriveTab"` + `setproperty`）、方法定义、类 traits 全在（标准 + lrg 两版） |
| DLL 有没有编进全部补丁 | 二进制特征串 | ✅ 「SWF 是旧版？」「结束时菜单还开着」「先保持」等都在 |
| MO2 侧有没有第二份 SWF 覆盖 | 搜 `missionmenu*.swf`（mods / overwrite / 真实 Data） | ✅ 只有 mod 目录一份（727082，22:43:58）；overwrite 无、真实 Data 无 |
| 游戏进程走的哪条路 | MO2 `logs\usvfs-*.log` | ✅ 插件日志映射回 mod 目录 ⇒ 进程走 MO2、SWF 也只有这一份可读 |

⇒ 三个「产物」全对，而 22:48 会话的界面行为 = **部署前那份旧 SWF**（没有挂载那份）。
⇒ 真因：**游戏进程在 SWF 部署（22:44:00）之前就启动了**（进程启动 → 加载 UI 资源 →
22:46:41 才走到 SFSE 插件加载日志那一步）。Starfield 的 UI 在**启动阶段**加载，
**进程起来之后部署的 SWF 不会被已加载的界面采用**。

**收口措施（已做）：**

1. **SWF 构建指纹**：`SAQ_Report` 输出里加 `stamp=50`（`ui/missionmenu/src/MissionMenu.as`；
   以后改 SWF 把它 +1）。日志里有没有这个字段 = 游戏加载的是新版还是旧版 SWF；
2. **DLL 自动判定**：`ui.*` 失败时再读一次 `SAQ_Report`，把「有没有 `stamp=`」的结论写进失败详情
   （`｜SWF 指纹=…` / `｜…没有 stamp= 字段…`），一眼定性，不用再猜三轮；
3. **verify 防回归**（+3 条）：两个 SWF 的 `stamp=` 字段 + DLL 的「SWF 指纹」与「旧版 SWF 判定」
   文案；
4. **流程写死在本文第七节**：跑测试必须「先构建部署 → 再启动游戏」。

## 九、后续（本轮未做，按需排期）

1. **自动读档**：本轮起不做（读档会让通道序号回退、且 `BGSSaveLoadManager` 的
   `QueueSaveLoadTask` / `BGSSaveLoadBuilder` 在 commonlibsf 里 `REL::ID = 0` 不可用；
   `QueueLoadGame(entry)` 是纯内联写字段，但偏移要先按项目通则核验）。
   现在靠 `Quest.Reset` + `teleport` 回滚，需要「读档」的用例标 SKIP。
2. **把历史判据搬成用例**：第 44~48 轮的待实测判据（星图 / 候选复算 / INFO 门槛 /
   任务板 marker / 菜单久停）都可以按第五节的语法逐条落成用例。
3. **虚拟桌面/独立会话启动**：让游戏在后台跑（不影响前台键鼠）。当前是「你手动启动」。
4. **离线层（原 L0/L1 方案）**：把过滤/门槛/候选池的决策从引擎依赖里抽成纯函数 +
   单元测试（毫秒级、零游戏）+ 数据管线黄金快照。harness 覆盖「引擎时序」，
   离线层覆盖「决策逻辑的组合爆炸」，两者互补。

## 十、发布包（Nexus）

harness 的代码**编进 DLL**（同一份源码），但：

* 只有在 ini `[Test] Harness=1` 时激活（默认 0）⇒ 玩家侧零开销、零行为；
* 用例文件与结果文件都在 `SFSE\Plugins\` 下，随 mod 一起删干净；
* 若要做到「发布包完全不含 harness」，在 `plugin/xmake.lua` 加
  `add_defines("SAQ_WITH_HARNESS")` 并把 `SAQ_Test*.cpp` 用宏包起来，
  `package-saq.ps1` 用不带该宏的构建 —— 见下一轮排期。

## 十一、第 51 轮：ui.tab 仍未过 —— 诊断增强与判读

06:34 会话（**SWF 已是最新**，失败详情带 `｜SWF 指纹=50`）`ui.tab` 仍 0 ms 失败 ——
第 50 轮「游戏进程启动太早」的解释**在这个会话不成立**（那只是 22:48 会话的成立解释）。
本轮把静态层能查的全查了（部署 SWF 两版的挂载字节码、DLL 产物、0 参调用、SWF 覆盖），
全部排除 —— 详见 `docs/99` 第 51 轮。

**新增诊断（stamp=51，已构建部署，待下次启动游戏生效）**：

1. `SAQ_Report` 的 `ep=` 字段（`SaqEntryProbe`）：`pub=…,ep=…`
   —— `pub` = 挂载函数执行结果（ok / not-run / no-root / ex:…）；
   `ep=ok` = 11 个入口在 root 上全能取到，`ep=缺:…` = 列出取不到的（名字）；
2. 5 个 `SAQ_TestDrive*` 入口包 try-catch：内部异常以 `err|ex:<消息>` 回传
   （此前这种情况与「路径不存在」同为 0 ms 失败，完全不可区分）；
3. `InvokeUiTestDrive` 多写法尝试（裸名 / `_root.` / `_root.root.`），失败详情带
   每条写法的结果 + 入口自检；成功走非首选写法时补一行 INFO。

**判读表（下次失败时照此定性）**：

| 失败详情里看到的 | 结论 |
| --- | --- |
| 各写法 `=fail` + `ep=pub=ok,ep=ok` | 挂载全好 —— 问题在 Invoke/Scaleform 调用层 |
| `ep=pub=ok,ep=缺:<名>` | 该入口没挂上（拿名字去 `SaqPublishEntryPoint` 序列里查） |
| `ep=pub=not-run` | `onAddedToStage` 没执行（SWF 生命周期 / 不是这份 SWF） |
| `ep=pub=ex:…` | 挂载过程抛异常（消息即真因） |
| `ui.tab` 步返回 `err|ex:…` | 入口函数内部异常（消息即真因） |

★ 跑测试流程不变：**先构建部署 → 再启动游戏**（SWF 在启动阶段加载）。

## 十二、第 52 轮：`ui.tab` 的真因 —— 向只读属性写入（`Error #1074`）

06:45 会话（`stamp=51`、`ep=pub=ok,ep=ok`）的判读表命中了最后一行：

```
[W] harness：  [FAIL] ui.tab（0 ms）—— err|ex:Error #1074（SAQ_TestDriveTab）
```

`Error #1074` = **Illegal write to read-only property**（AS3 运行时错误表）——
「往只有 getter 的属性赋值」。对照 `Shared/AS3/BSTabbedSelection.as`：

```as
public function get selectedIndex() : int   // ← 只有 getter，没有 setter
{
   return this.iSelectedIndex;
}
```

而 `SAQ_TestDriveTab` 当时写的是 `this.TabbedFilterSelection_mc.selectedIndex = idx;`
⇒ 必抛异常（第 51 轮的 try-catch 把它变成可读的 `err|ex:…`；否则它的外形与
「路径不存在」的 0 ms 失败**完全一样**）。

### 修法：走原版公开入口

| 旧（错） | 新（对） |
| --- | --- |
| `TabbedFilterSelection_mc.selectedIndex = idx`（抛 #1074） | `TabbedFilterSelection_mc.SetSelectedCategoryIndex(idx)` |

`MissionTabbedSelection.SetSelectedCategoryIndex(uint)` 是 public（`MissionTabbedSelection.as`；
原版 `InitializeLastState` 用它恢复「上次的分类」）⇒ 内部 `SetSelectedIndex` →
改 `iSelectedIndex` → `dispatchEvent(BSTabbedSelectionEvent)` → `MissionMenu.onFilterChanged`
（掩码同步 + 切换音 + tab 快照）——**与玩家按肩键切 tab 完全同一条链**。
因此不再手动调 `onFilterChanged`；只有「本来就在该 tab」时 `SetSelectedIndex` 判定
「没变化」直接 return、不派发事件，代码里为这种情况补一次。

新增拒绝码 `err|tab-refused|from=…|want=…|now=…`：`SetSelectedIndex` 静默不生效
（`bDisableInput` / 越界）时**不再装作成功**。

### 同批核对（其余测试入口用到的 AS3 API）

| 入口 | 用到的 API | 结论 |
| --- | --- | --- |
| `SAQ_TestDriveSelect` / `Expand` | `MissionsList_mc.selectedIndex = n` | ✅ 可写（`BSScrollingContainer` 有 setter；原版自己也这么写） |
| `SAQ_TestDriveSelect` | `dispatchEvent(new ScrollingEvent(SELECTION_CHANGE))` | ✅ 常量在 `Shared/AS3/Events/ScrollingEvent.as` |
| `SAQ_TestDriveKey` | `MissionsList.onEntryPress` / `MissionMenu.ProcessUserEvent` | ✅ public |
| `SAQ_TestDriveExpand` | `MissionsList.ExpandOrCollapseSelection()` | ✅ public |

### 产物与验证

* `stamp=51 → 52`；
* `verify_saq_build.py` 新增 `测试入口-切tab拒绝码`（查 `tab-refused`：只在第 52 轮代码里
  出现 ⇒ 证明新逻辑进了两份 SWF 与 MO2 部署副本）；构建后 verify 全通过。

★ 教训：**AS3 里给属性赋值前先确认对方有 `set x()`** —— BS 组件里「只有 getter」的属性
（设计上只让组件自己改）赋值必抛 #1074，而且症状会被 Scaleform 的 Invoke 层压成
「0 ms 失败 / 路径不存在」的假象。
