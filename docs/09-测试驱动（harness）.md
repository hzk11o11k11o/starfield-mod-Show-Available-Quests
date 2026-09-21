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

## 十、发布构建：DLL 不含 harness（第 53 轮已落地）

发布包给玩家，DLL 里不该带测试代码（能改任务状态的命令通道 / 界面测试驱动 / 结果落盘）。
第 49 轮时 harness 是「整份编进 DLL、靠 ini 开关零开销」的；第 53 轮起改为**编译开关**：

```powershell
# 发布构建（DLL 不含 harness）+ 部署：
& ".\tools\build-saq.ps1" -Release -SkipTable -SkipSwf -SkipPapyrus

# 开发/自测构建（默认：含 harness）：
& ".\tools\build-saq.ps1" -SkipTable -SkipSwf -SkipPapyrus
```

* 开关 = `plugin/xmake.lua` 的 xmake option **`saq_harness`**（默认 `y`）；
  关闭时 `SAQ_Test.cpp` / `SAQ_TestOps.cpp` **不参与编译**，`SAQ.cpp` 的三个调用点与
  `SAQ_UI.cpp` 的 `InvokeUiTestDrive` 都在 `#if SAQ_WITH_HARNESS` 内 ⇒ DLL 里不出现
  任何 harness 字符串（实测 911360 B → **784896 B**）。
  ★ 两个文件自身也用 `#if SAQ_WITH_HARNESS` 包住（**双保险**：即使被误加入编译，
  也只编成空单元，不会产生对 `UI::InvokeUiTestDrive` 之类的引用）。
* 发布版若发现 ini `[Test] Harness=1`，打一行 WARN（`…但本 DLL 是发布构建（未编译 harness）…`）
  —— 不静默（第 49 轮 ini 段坑的教训：开关失效要能一眼看出来）。
* `tools\package-saq.ps1` 自动完成：**发布构建 + 部署 → `verify_saq_build.py --release`
  → 打包**。`--release` = 13 项反向检查（DLL 出现任何 harness 特征即失败）+
  1 项正向检查（发布提示串在）—— 能挡住「xmake 配置没切过去、带着测试代码打包」。
* **SWF / PEX / ESM 两版相同**：AS3 的 `SAQ_TestDrive*` 入口与脚本侧的测试命令执行器
  保留 —— 它们只在「DLL 主动调用 / 写通道」时才起作用，而发布版 DLL 已无任何调用路径
  （改 SWF/PEX 的成本与风险不值得；见 `docs/99` 第 53 轮）。
* verify 的两种模式：默认按 DLL 内容自动探测；`--release` 强制作发布校验（打包用），
  `--dev` 强制开发校验。另加一条：**MO2 部署副本与工作区字节一致**（部署未落后 ——
  第 50 轮「游戏加载的是部署时那份」的教训）。

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

## 十三、★ 实测：`[case:smoke]` 首次全绿（2026-09-21 06:53 会话）

按第七节的流程（**先构建部署 → 再启动游戏**）重进游戏、读档，harness 自动跑完并全过：

* `python tools\test\check_results.py`：用例 1｜**PASS 1**｜FAIL 0｜SKIP 0；`smoke` 2640 ms；
* `ui.tab` = `ok|tab=7|mask=64|n=245`（第 52 轮 `SetSelectedCategoryIndex` 修复生效）；
* `SAQ_Report` 带 `stamp=52` + `ep=pub=ok,ep=ok`（新版 SWF 已加载 + 入口挂载全好）；
* 引导链完整：`press=R@…` → `引导请求` → 菜单关闭 → 828 ms `引导已生效`（脚本状态=1）
  → 星图 1.1 秒打开（第 1 次尝试）→ `guide.clear` → `引导状态对账：通道里已没有目标`；
* 读档候选无抖动（补丁②复查通过）；全会话仅 2 条 `[W]`（开菜单第 1 次推送桥解析失败，
  0.8 s 后第 2 次成功）、无 `[E]`。

⇒ 链路（用例 DSL → DLL 驱动器 → Papyrus 写侧 → 界面真实处理路径 → 断言 → 结果 JSON）
端到端跑通；后续把更多判据落成用例即可（见 `docs/99` 十四·第 7 节）。

## 十四、第 54 轮（大项 G）：历史判据落成用例 —— 新能力 + 5 条用例

目标：把**已经人工验过、但没有自动判据**的第 26/44~48 轮结论写进用例文件，避免以后
每次改代码都靠人回忆着点一遍。落成过程中补齐了 harness 缺的四类能力 —— 每一条都对应
一个「人工判据里躲不掉的动作」。

### 1. 新增步骤 / 语法

| 新能力 | 用途（对应判据） |
| --- | --- |
| `assert.nolog <正则> [timeout=ms] [scope=…]` | **反向断言**：整段窗口不许出现某模式。第 26 轮「菜单久停无假失败」、第 44 轮「星图不许有第 2/3 次尝试」、第 49 轮补丁②「读档后不许立刻降级」都是「不该出现」型判据 |
| `scope=this\|prev\|case` | 断言的**日志窗口起点**：默认 `this` = 本步骤开始之后。问题：SAQ.cpp 的 Tick 顺序是「产品路径 → harness」，动作与它的日志常落在**同一次 Tick** ⇒ 「menu.open 之后的统计行」「ui.key 之后的引导请求」这类断言看不到刚刚那行（打点已越过）。`prev` = 上一步开始（断言上一步引起的那行）；`case` = 本用例开始（查总账） |
| `ui.selectchild <uID>` | 展开该条并选中它的**子项**（「前往接取地点」/「前往任务板」）。与原版对齐：主标题的 Enter **只展开**，只有子项的 Enter 才切引导 ⇒ 第 26 轮「停菜单里 27 秒」必须走这条（R 那条链成功后会由界面关掉整个暂停菜单） |
| `menu.hide <注册名>` | 关掉**任意**菜单。用例收尾要关**星图**（`GalaxyStarMapMenu` 同样是暂停菜单：不关的话游戏一直暂停、脚本定时器不走，后面的命令步骤全超时）。`finishAll` 收尾也顺手关它 |
| `teleport.entry <板uID>` | 把玩家传送到任务板（自动挑此刻可得的候选：板自身 / 新建常驻 marker / 常驻兜底）。用例要「站远 / 走近」来触发候选复算（第 45/47 轮）与 cell 加载差异 |
| `~0x…`（记录号） | **不写运行期 FormID**：DLC 任务的高字节是加载顺序（本机 SFBGS050 = 0x03）——`~0x0008EBDC` 由驱动器查静态表 + `Masters::MakeFormID` 解析（`~2:0x…` 可显式指定 master）。`quest.*` / `ui.select*` 都支持 |

### 2. 五条用例（`tools/test/scenarios/SAQ_TestPlan.txt`）

| 用例 | 判据来源 | 断言要点（自动） |
| --- | --- | --- |
| `r26_menu_idle` | 第 26/27 轮实测（菜单里停 27 秒无假失败 + 关菜单 0.9 秒生效） | `引导确认：菜单还开着` → **27 秒内不许出现** `引导未生效` → `assert.menu open` → 关菜单 → `引导确认：菜单已关` → `引导已生效`（步骤耗时 ms 进结果 JSON） |
| `r47_board_marker` | 第 30~34 轮（任务板任意位置精确导航） | `入口=12(可导航 12｜marker [1-9]… 不可用 0)` + 站在阿基拉城点新亚特兰蒂斯板 ⇒ `引导请求：…新建常驻 marker（精确）`（证明引擎接受新建常驻引用，且没退化成兜底）+ `引导已生效 脚本状态=1` |
| `r45_candidates` | 第 45 轮（候选池）、第 47 轮（常驻兜底）、第 49 轮补丁②（降级观察期） | 远处（赛多尼亚）点「营救机器人」⇒ `候选 [2/2]「Ref_08ECA6」` + 立即生效 → 传送进 The Well ⇒ 升级 `[2]「Ref_08ECA6」→ [1]「G型」` → 再走远 ⇒ `先保持` 且 **12 秒内不许降级** → 观察期满后正常降级 `[1]→[2]` |
| `r48_info_gate` | 第 48 轮（INFO 门槛 = 对话侧「进度没到不显示」） | 造状态 A（回滚前置 `DialogueFCNeon` + 目标任务）⇒ `INFO门槛=<N>(过x/藏y/放行z/未知w)` + `INFO没到:` 名单里有 `无凭无据[0x00082D5A`；B（前置 `Start`+`SetStage 295`）⇒ 不再出现在名单里（反向断言） |
| `r44_starmap` | 第 44 轮（星图由脚本节拍打开、位置不再滞后） | `引导请求：…星图=是` → 菜单被界面关掉 → `星图：已打开（GalaxyStarMapMenu…第 1 次尝试）`（第 1 次 = 没抢跑换地点重画）+ `scope=case` 反向检查「等待中——任务菜单仍开着」→ `menu.hide GalaxyStarMapMenu` 收尾 |

### 3. 跑之前要知道的三件事

1. **`[Test] Mode` 用 0（显示全部）**：全部用例在 0 下成立；`Mode=6` 时列表里没有
   「营救机器人」（第 47 轮起它有常驻兜底）且入口条目不再追加（`r47` 的 `入口=`统计会变 0）；
   `Mode=5` 只有入口条目（`r47` 可用，其余用例看不到任务行）。
2. **流程不变**：先构建部署（`build-saq.ps1 -SkipTable -Harness`）→ 再启动游戏 → 读档；
   SWF 指纹 `stamp=53`（第 54 轮构建）。
3. **用例会改任务状态并传送玩家**：先备份存档；跑完位置在最后一次 `teleport.entry` 处。

### 4. 仍然只能靠眼睛确认的部分（用例覆盖不了）

* 星图**聚焦哪颗星球**：DLL 只能看到「`GalaxyStarMapMenu` 在屏幕上」+ `星图诊断`
  的地点链节点值（引擎自己知不知道这个地点）—— 用例覆盖「链路 + 不重画」这一半，
  航线画在哪颗星仍要看屏幕（第 44 轮已人工验收）。
* 蓝点/扫描仪路径线的**视觉位置**（第 34 轮玩家验收过的「蓝点落板」）。

### 5. 本轮验证（已做）

* 构建：SWF 727801 / 727931 B（`stamp=53`，新增 `SAQ_TestDriveSelectChild` 并挂 root）、
  DLL **923136 B**（开发构建，含 harness）；已部署到 MO2（含用例文件）。
* `verify_saq_build.py` 全过（0 条 MISS）：新增 harness 特征 4 条（`assert.nolog` /
  `menu.hide` / `teleport.entry` / `SAQ_TestDriveSelectChild`）、SWF 3 条（子项入口 +
  `SAQ_FindChildIndexByUID`）、入口挂 root +1、用例计划 6 条 + 部署一致、静态表 2 条
  （第 45 轮首选候选质量 + 反向检查）。
* **待实测**：重进游戏（`Harness=1` 已保留）⇒ `python tools\test\check_results.py`
  期望 6 条用例全 PASS（smoke + 5 条）。

---

## 十四·补、第 55 轮：首测复查（09:06 会话）与两条用例编写红线

### 1. 首测结果：6 条全 FAIL，但**产品链路全部正常**

时间线（09:04 启动 → 09:06:22 结束，ini `[Test] Mode=0`、`stamp=53`）：

| 时刻 | 证据 | 判定 |
| --- | --- | --- |
| 09:06:02.810 | 推送成功 249 条 | ✅ |
| 09:06:02.923 | `引导请求：沙布罗的解决方案 → 候选 [1/6]… 星图=是` | ✅ |
| 09:06:03.173 | `菜单关闭：界面最后状态`（界面自己关暂停菜单） | ✅ |
| 09:06:03.916 | 脚本 `引导已应用：Neon_DietrichSieghartREF`（743 ms） | ✅ |
| 09:06:05.709 | `星图：已打开（…第 2 次尝试）` | ⚠ 见 §4 |
| 09:06:06.918 | `assert.log 引导请求：` **FAIL**（那行在断言窗口起点之前） | ❌ 假失败 |
| 09:06:07~22 | 后续 5 条用例 `ping` 全超时（星图留屏 ⇒ 游戏暂停 ⇒ 节拍冻结） | ❌ 驱动器缺陷 |

### 2. 红线一：断言「上一步的副作用行」必须 `scope=prev`

`scope` 的窗口起点 = **本步骤开始时**的日志环形缓冲序号。动作与它的日志常落在同一次
Tick（产品路径先跑、harness 后跑）⇒ 若日志行在本步骤开始**之前**已写入（例如
`ui.key` 提交后、`assert.log` 开始前的间隙里 DLL 轮询到了引导请求），默认的
`scope=this` 就看不到它 —— 09:06 的假失败正是如此（06:53 那次命中纯属时序运气）。

**规则**：凡是断言「上一步动作引起的那一行」（推送成功 / 引导请求 / 引导已生效 /
菜单关闭…），一律写 `scope=prev`。查整条用例的总账用 `scope=case`。

### 3. 红线二：用例结束必须清场（驱动器已内置）

R 链路（`ui.key XButton`）的产品行为是**打开星图**（暂停菜单）。用例若在星图开着时
失败中止，星图留在屏幕上 ⇒ 游戏暂停 ⇒ 脚本定时器冻结 ⇒ **后续用例的 `ping` 全部
3000 ms 超时**（看起来像「通道坏了」，其实是现场没恢复）。

修法（第 55 轮起驱动器自动做）：`CleanupAfterCase()` 在**每条用例结束**（PASS/FAIL）
时执行 —— 清引导（写通道，让脚本下一拍作废未执行的星图待办）→ 关任务菜单（如开）→
关星图（如开）；用例之间再留 700 ms（`kInterCaseDelayMs`）让引擎把菜单关闭处理完。

### 4. 同轮修掉的两个星图收口问题（产品侧）

* **重试等待 1.5 s 太紧**：脚本「脚本已应用 → 下一拍打开星图」实测窗口 **1.6~2.5 秒**
  （装待办 2 拍 + 暂停菜单真正关闭的延迟）⇒ 星图马上要开却被 DLL 记「第 2 次尝试」
  并写通道换候选。`kStarMapRetryAfterAppliedMs` 1500 → **3000**。
* **残留重试请求会再开一次星图**：重试写下的「待处理 + 星图 6」若未被脚本消费，会在
  星图关闭、游戏恢复运行后被消费（09:06:22 实测第二次打开）—— 玩家侧 =「我关了它又弹」。
  修法：星图已打开且 `attempts > 1` 时把通道**标回普通待处理（状态 0）**，脚本下一拍
  重新应用同一条引导并作废星图待办。

### 5. 本轮产物与验证

DLL **924672 B** / 用例文件 17637 B（工作区与 MO2 部署字节一致）；`verify_saq_build.py`
**全过（+7 条检查）**：`harness 用例收尾清菜单/清星图`、`星图残留请求回收`、
`星图重试等待窗口文案`、`用例计划 · smoke 引导请求断言带 scope=prev` + 3 组反向检查。

**待重测**：重进游戏读档 ⇒ 6 条用例全 PASS；smoke 的 `引导请求：` 应 16 ms 级命中；
星图应为「第 1 次尝试」。

## 十四·补二、第 56 轮：第二次首测（09:22 会话）—— 两个**驱动器**缺陷（产品侧全对）

### 1. 结果：6 条用例 PASS 2 / FAIL 4

| 用例 | 结果 | 真因 |
| --- | --- | --- |
| `smoke` | PASS | 但「脚本已应用」一步曾误命中（§4） |
| `r26_menu_idle` | PASS | 断言命中 4 秒前的旧行 = 假 PASS（§2） |
| `r47_board_marker` | FAIL | 传送回执超时（传送其实成功，§3） |
| `r45_candidates` | FAIL | 同上（两次传送都被判超时） |
| `r48_info_gate` | FAIL | **假 FAIL**（§2）—— 产品行为正确 |
| `r44_starmap` | FAIL | `ui.tab`「桥没通」= 上游假 PASS 的连带（§2） |

### 2. ★★ 缺陷①：断言窗口起点被清 0（假 PASS 与假 FAIL 同源）

`CompleteStep()` 收尾时 `g_cur = StepState{}` 把 `logMark` 一起清成 0 ⇒ 下一步开跑时
`g_prevMark = g_cur.logMark = 0` ⇒ **所有 `scope=prev` 断言退化成「整个环形缓冲」**：

* 假 PASS：r26 的 `assert.log 推送成功 scope=prev` 在 09:22:30.173（**0 ms**）命中了
  **4 秒前**（09:22:25.927）那一行；本次真正的推送 09:22:30.985 才发生（实测 ~800 ms）；
* 连带：r44 因此没等新推送就调 `ui.tab` ⇒「桥没通」（桥是开菜单推送那一刻才解析的）；
* 假 FAIL：r48 的反向断言报文写着「窗口从 idx 0 起」，匹配到 09:22:25.109 的旧名单 ——
  而 09:23:16.607 的新名单 `INFO门槛=58(过38/藏18/放行2/未知0)` 里**已经**没有『无凭无据』。

修法：`CompleteStep` 保留 `logMark`（只重置其余字段）+ `EffectiveLogFrom` 兜底
（起点 0 ⇒ 退到本用例起点）。**红线三**：任何「窗口起点」都不许是 0（= 整段缓冲）。

### 3. ★ 缺陷②：传送回执要等 **cell 加载**（3 秒窗口太紧）

DLL 09:22:58.689 提交 `seq=6 传送玩家(MoveTo)`、09:23:01.695 放弃（3000 ms）；Papyrus 侧：

```text
[09:23:03] 测试命令：seq=6 op=6 结果=0 —— MoveTo [FCMissionBoardREF (0014D497)]（cell=CityAkilaCityTheRock）
[09:23:12] 测试命令：seq=9 op=6 结果=0 —— MoveTo [ (001DF853)]（cell=CityCydoniaMainLevel）
```

回执在 `MoveTo` **返回之后**才写（提交 → 回执 = **4.3 / 4.5 秒**）⇒ `kTeleportAckTimeoutMs = 20000`
（其余命令仍 3 秒），并把等待窗口写进日志（`传送等回执最多 … ms`）。

### 4. 顺带：断言要「只认产品日志」+ 收紧 smoke 的宽松断言

* r26 最后一条 `assert.log 引导已生效 scope=prev` 命中的是 harness 自己的 `[PASS]` 行
  （它原样复述正则与命中行 = **回声**）⇒ `LogFind` 跳过所有 `harness：` 行；
* smoke 的 `引导已生效|引导延迟生效|引导确认` 会匹配「引导确认：菜单还开着」（那句恰恰是
  「还没应用」）⇒ 收紧为 `引导已生效|引导延迟生效`。

### 5. 产物与验证

DLL **924672 B**（开发构建）/ 用例文件 **18759 B**（工作区与 MO2 字节一致）；
`build-saq.ps1 -SkipTable -SkipSwf -SkipPapyrus -Harness` ✓（ESM 重建后仍 3947 B）；
`verify_saq_build.py` **全过（+5 条）**：`harness 驱动器版本串`
（`驱动器 v56：日志窗口按步保留 / 传送 20 秒窗口`）、`传送回执等待窗口文案`、
`用例计划 · smoke 引导已生效断言（不带裸「引导确认」）` + 反向检查。

**待重测**：重进游戏读档 ⇒ `check_results.py` 期望 6 条全 PASS；日志里先确认 `驱动器 v56` 串。

## 十四·补三、第 57 轮：第三次实测（09:35 会话）—— 三条新真因（仍全在驱动器/用例侧）

### 1. 结果：6 条用例 PASS 2 / FAIL 4，产品侧依旧全对

| 用例 | 结果 | 真因 |
| --- | --- | --- |
| `smoke` | PASS（2640 ms） | ——（R 链路完整：推送 249 / `ui.tab` / 引导 813 ms / 星图 1.1 s） |
| `r26_menu_idle` | FAIL | 第一条 `ping` 超时 —— **smoke 的星图在清场之后才打开**（§2） |
| `r47_board_marker` | FAIL | `ui.selectchild` `err\|notfound` —— **没等 C++ 推送就切 tab**（§4） |
| `r45_candidates` | FAIL | `ui.selectchild ~0x0008EBDC` 报「没有记录号 0x000000」—— `~0x…` 解析漏写回（§3） |
| `r48_info_gate` | FAIL | **假 FAIL**：`INFO没到:` 断言的窗口被上一条断言消耗（§5）—— 产品行为正确 |
| `r44_starmap` | PASS（6625 ms） | 星图第 1 次尝试 1.2 s、`assert.nolog` 通过（上一轮的连带问题已消） |

### 2. ★ 真因①：星图在**清场之后**才打开（r26 的 `ping` 超时）

第 55 轮的「每条用例结束都清场」救不了这种时序：

```text
[09:35:18.315] smoke 最后一步 guide.clear → 用例结束 → 清场（此刻星图还没出现）
[09:35:18.495] 星图：已打开（GalaxyStarMapMenu 在屏幕上，R 后约 1.1 秒，第 1 次尝试）
[09:35:19.218] r26 第一条 `ping` 提交
[09:35:22.215] FAIL：命令没有回执（超时 3000 ms）—— 星图 = 暂停菜单 ⇒ 脚本定时器冻结
[09:35:22.215] 用例收尾：星图还开着 —— 已请求关闭（这次它才被看到）
```

R 链路的星图由**脚本节拍**在菜单关闭后 1~1.5 秒打开（第 44 轮的产品设计，正确）；清场
发生时它还没出现 ⇒ 落在下一条用例开头。

修法（驱动器 v57）：**「按过 R（XButton）」的用例结束后开一段 4 秒延迟复查窗口** ——
每帧查一次星图/任务菜单，观察到就关掉并**提前结束窗口**（脚本一次引导只开一次星图，
出现过就不会再来）；一直没出现才等满 4 秒（覆盖脚本「第 2 次尝试」才成功的情形）。
窗口没结束不开下一条用例。（只有 R 用例会触发，其它用例间隔仍是 700 ms。）

### 3. ★ 真因②：`ui.select/selectchild/expand` 的 `~0x…` 参数漏写回 `formId`

`ParseStep` 的 kUi 分支解析 `~0x0008EBDC` 成功，但**没有把解析值存进 `a_step.formId`**
（`a_step.text.clear()` 之后就丢了）⇒ `ResolveStepFormID` 拿到 0 ⇒
`静态表里没有记录号 0x000000（master 任意）`（r45 的原始报文）。
对照：`quest.reset ~0x0008EBDC` 正常（走 `needFormID` 分支，值存进了 `formId`）。
修法：`a_step.formId = uid;` 一行。

### 4. ★ 真因③：没等 C++ 推送就切 tab（r47 撞上内嵌回退数据）

`assert.log 入口=12(…)` 命中的是**收集阶段**的「运行时状态」行（推送**之前**打印）——
本机开菜单的第一次推送常因桥解析失败、0.8 秒后才重试成功：

```text
[09:35:30.506] 运行时状态：… 入口=12(可导航 12｜marker 10 原板 2 兜底 0 不可用 0) …
[09:35:30.507] [W] 推送失败（第 1 次，完整诊断）：Movie/ASMovieRoot 解析失败…
[09:35:30.534] 界面状态[1]：src=embedded raw=202 keep=199   ← 界面此刻还是**内嵌回退数据**
[09:35:30.542] ui.tab → ok|tab=7|mask=64|n=199（= embedded 的 keep 数）
[09:35:30.701] ui.selectchild 0x0021001E → err|notfound|n=199  ← 内嵌数据不含任务板入口
```

修法（用例）：`ui.tab` 前加 `assert.log 推送成功 scope=case timeout=12000`
——「内嵌回退数据不含入口条目」这条降级窗口（第 17 轮记录）在 harness 里第一次咬人。

### 5. ★ 真因④（用例红线）：两条断言共享同一批行时，第二条要 `scope=case`

`scope=prev` 的窗口起点 = **上一步开始**时刻 —— 会被上一条断言「消耗」掉：
同一 Tick 早先打印的行落在窗口之外。r48 的 `INFO门槛=` 与 `INFO没到:` 是**同一行**
（统计与名单一起打印），第二条因此超时；r26 的 `引导请求` / `引导确认：菜单还开着`
同理（本次没跑到，但必定假 FAIL）。修法：这两处的第二条断言改 `scope=case`。

### 6. 产物与验证

DLL **925696 B**（开发构建）/ 用例文件 **21093 B**（工作区与 MO2 字节一致）；
`build-saq.ps1 -SkipTable -SkipSwf -SkipPapyrus -Harness` ✓（ESM 重建后仍 3947 B；
日志里「移除 CELL 组 1 个（1271 B）」是 `--clean → 重建` 的**中间态**，最终 3947 B）；
`verify_saq_build.py` **全过（+5 条、0 MISS）**：`harness 驱动器版本串`
（`驱动器 v57：~0x 参数写回 / 清场延迟复查 / 日志窗口按步保留 / 传送 20 秒窗口`）、
`harness 清场延迟复查文案`、`用例计划 · r47 切 tab 前等推送成功（scope=case）`、
`用例计划 · r26 引导确认断言（scope=case）`、`用例计划 · r48 INFO没到断言（scope=case）`
+ 反向检查（旧的 `scope=prev` 写法必须不在）。

**待重测**：重进游戏读档 ⇒ `check_results.py` 期望 6 条全 PASS；日志里先确认 `驱动器 v57` 串
（没有它 = 还是旧驱动器）与 `用例收尾复查：星图在清场后才打开`（若星图又晚开）。

## 十四·补四、第 58 轮：第四次实测（10:31 会话）—— 游戏端卡在加载画面（驱动器加防护 + 诊断）

### 1. 现象（玩家侧看到的 + 日志侧证实的）

自动会话跑到 r45 的「再走远」那一步（`teleport.entry 0x001DF853`）时，游戏**卡在加载画面**：

* 玩家侧：右下角一直转圈（加载中），画面上**同时**还有 HUD 的任务引导蓝点 ——
  正常游玩这两个元素不会同时出现；其实这正是「加载流程没走完」的表现：它没走到
  「关掉加载菜单、恢复 HUD」那一步；
* **Papyrus 日志**（`Documents\My Games\Starfield\Logs\Script\Papyrus.0.log`）**停在 10:34:37**，
  最后一行是 `[SAQ] 引导已应用：[elitecrewdebugscript < (0308ECA5)>]`，之后再没有任何行；
* **DLL 日志**一直写到 10:35:03（harness 全部用例结束，含两条收尾用例的陪跑超时）
  ⇒ 主线程还活着，卡住的是 **Papyrus VM**（`player.MoveTo` 这个调用永远没返回）。

### 2. 取证：这次传送为什么卡（时间线）

| 时刻 | 事件 |
| --- | --- |
| 10:34:35.393 | `seq=10 传送玩家(MoveTo)`（→ 新亚特兰蒂斯城 The Well 任务板）**回执**（Papyrus `结果=0`） |
| 10:34:35.431 | harness 提交 `seq=11 传送玩家(MoveTo)`（→ 赛多尼亚）—— **距上一条回执仅 38 ms** |
| 10:34:37 | 脚本节拍：先 `引导已应用`（候选复算升级到 `0x0308ECA5`），紧接着执行 seq=11 的 `MoveTo` ⇒ **卡住** |
| 10:34:55 | harness 放弃 seq=11（20 秒窗口到）⇒ r45 FAIL |
| 10:34:56~10:35:03 | r48 / r44 的 `ping` 全部超时（VM 冻结）⇒ 两条用例**陪跑** |
| 之后 | 游戏一直停在加载画面（用户截图为证），直到关掉进程 |

历史对照：这条「再走远」的传送在第 54~57 轮**从没跑到过**（都在更早的步骤失败退出），
而历史上成功的传送间隔是 **5~10 秒**（seq=6→9 隔 10 s、seq=9→10 隔 5 s）—— 只有这次是
「回执后 38 ms」。

### 3. 结论与处置（本轮修的是**驱动器**，不是产品）

* **不是产品缺陷**：这段时间里 mod 没做任何异常事（DLL 只读通道/记日志；脚本只做
  「应用引导」这件正常事）。卡死点在**引擎处理玩家 `MoveTo` 的加载流程**上 —— 而
  `MoveTo` 只由 harness 使用（玩家不会在 2 秒内被连传两次）。
* 驱动器 v58 三件事：
  1. **传送落地静默期**（`kTeleportSettleCleanMs` / `kTeleportMinGapMs` /
     `kTeleportSettleMaxMs`）：`teleport.*` 步骤要等「加载画面（LoadingMenu/FaderMenu）
     消失 + 连续静默 1.5 秒 + 距回执 ≥3.5 秒」才算做完 ⇒ 传送步骤比过去多 2~5 秒（正常）。
  2. **加载画面证据**：命令超时/落地等待时把**此刻打开的菜单**写进日志与证据
     （`LoadingMenu, FaderMenu` 出现 = 卡在加载画面）。旧的静态提示
     「确认此刻菜单是关的」已被替换（它什么也证明不了）。
  3. **卡死自动中止**（`MarkStuck` / `FillRemainingSkipped`）：确认卡死（有加载画面，
     或连续 2 次命令无回执）⇒ 剩余用例标 SKIP 并写明原因，不再逐条陪跑超时；
     同时用一条 **Ping 冲刷通道**（脚本只执行「最新序号」那条命令 ⇒ 万一游戏之后恢复，
     执行的是这条无害的 Ping，而不是那条排队的传送）。
* 判据：日志里的 `驱动器 v58：传送落地静默期 / 加载画面证据 / 卡死自动中止`。

### 4. 产物与验证（已做）

DLL **934400 B**（开发构建；工作区与 MO2 部署字节一致）、用例文件 **22248 B**（同）；
`verify_saq_build.py` **全过（423 条 OK、0 MISS）** —— 新增 5 条正向
（v58 版本串 + 落地静默期/超限判定/卡死/菜单证据文案）+ 2 条反向
（旧的静态提示「确认此刻菜单是关的」、旧 `驱动器 v57` 串必须不在）。

### 5. 待重测（重进游戏一次会话，什么都不用点）

1. `python tools\test\check_results.py` ⇒ 期望 **6 条全 PASS**；
2. 日志里先确认 `驱动器 v58` 串（没有 = 还是旧驱动器）；
3. 若又卡加载画面，应能看到
   `harness：  传送落地中（回执已到，但加载画面还没关：LoadingMenu, FaderMenu）`
   与 `harness：游戏端疑似卡死 —— …`，且 r48/r44 报的是 **SKIP（原因写明）**，
   而不是两条独立的 FAIL；
4. 传送步骤（`teleport.entry`）的耗时从 ~5 秒变成 ~8 秒属**正常**（落地静默期）。

## 十四·补五、第 59 轮（11:04 会话）：r47/r45 两条假 FAIL —— 落地静默期与回执解耦

### 1. 实测结果：6 条用例 PASS 4 / FAIL 2，两条 FAIL 同源、**产品与游戏侧全对**

| 用例 | 结果 | 真因 |
| --- | --- | --- |
| `smoke` | PASS（3047 ms） | 推送 249 / `ui.tab` / R → 引导 828 ms 生效 / 星图 1.1 s |
| `r26_menu_idle` | PASS（32515 ms） | 菜单里停 27 秒无假失败；关菜单 828 ms 生效 |
| `r47_board_marker` | FAIL（20609 ms） | `teleport.entry` 报「命令没有回执」—— **假 FAIL**（§2） |
| `r45_candidates` | FAIL（23594 ms） | 同上（第二次传送） |
| `r48_info_gate` | PASS（6141 ms） | `INFO门槛=58(过37/藏19/放行2/未知0)` + `INFO没到:` 名单 |
| `r44_starmap` | PASS（6656 ms） | 星图第 1 次尝试 1.4 s、`assert.nolog` 通过 |

### 2. 真因：`Poll` 是一次性消费，落地静默期被绑死在「读到回执那一 Tick」

时间线（r47；r45 同形态）：

```text
11:04:37.499  提交 seq=6 传送（→ 阿基拉城 CityAkilaCityTheRock）
11:04:41.907  传送落地中（回执已到，但加载画面还没关：LoadingMenu, FaderMenu）  ← 唯一一次检查
11:04:57.496  [FAIL] 命令没有回执（超时 20000 ms；此刻打开的菜单：无）          ← 20 秒 deadline
```

* Papyrus 侧两次 `MoveTo` 都成功：`11:04:41 seq=6 结果=0` / `11:05:06 seq=9 结果=0`，
  且整段 VM 一直在跑（seq=7~16 全部正常执行）；
* 超时瞬间「此刻打开的菜单：无」= **加载画面其实早就关了**；
* 病根在 `Poll` 的语义（SAQ_TestOps.cpp:347）：读到回执后 `g_busy = false`，之后永远
  返回 0；而 v58 把整套静默期检查写在 `rc == 1` 分支里 ⇒ 回执之后一个 Tick 也跑不到，
  20 秒 deadline 一到就报「命令没有回执」。
* 与第 58 轮现场（真卡死）的区分点 = **超时瞬间的菜单列表**：
  `LoadingMenu/FaderMenu` = 卡在加载画面；`无` = 正常落地（本轮就是）。

### 3. 修法（驱动器 v59）

1. **登记与推进分离**：收到回执只登记（`settleAckAtMs` + `settleAckDetail`），
   静默期检查移到 `rc==1` 之外、**每 Tick** 推进；
2. **deadline 只管「等回执」阶段**：静默期块位于 deadline 检查之前 ⇒ 回执到了之后
   「没有回执」的 20 秒窗口立即失效；加载画面 25 秒不结束仍走 `MarkStuck`（转 SKIP）；
3. **落地完成证据**：完成时步骤结果写明
   `…；落地静默期完成（回执后 N ms，加载画面已关 M ms）`。

### 4. 产物与验证（已做）

* DLL **935424 B**（开发构建；工作区与 MO2 部署字节一致）；用例文件 22248 B（未动）；
* `verify_saq_build.py` **全过（+3 条、0 MISS）**：`驱动器 v59：落地静默期每 Tick 推进` /
  `落地静默期完成（回执后` + 反向检查（`驱动器 v57`、`驱动器 v58` 必须不在）。

### 5. 待重测（重进游戏一次会话，什么都不用点）

1. `python tools\test\check_results.py` ⇒ 期望 **6 条全 PASS**；
2. 日志里必须出现 `驱动器 v59` 串（没有 = 还是旧驱动器）；
3. `teleport.entry` 步骤应回 PASS，且结果里带「落地静默期完成（回执后 …）」；
4. r47 应跑到「入口 12/12 + 引导落新建常驻 marker」、r45 应跑到候选池三段判据
   （这两条用例本轮因假 FAIL 中断，重跑里补齐）。
