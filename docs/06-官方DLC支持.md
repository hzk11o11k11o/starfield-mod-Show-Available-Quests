# 06 · 官方 DLC 支持（破碎空间 + 地球舰队）

> 2026-09-20 第 17 轮。对应 AGENTS.md 的「支持 DLC」需求。
> 一句话：**表单不再写死 FormID，而是存「插件名 + 记录号」，运行期问引擎要加载序号拼出来。**

---

## 一、为什么原来只支持 Starfield.esm

第 10~16 轮的静态表里每行存一个 **FormID**（如 `0x000158E0`）。这个值的高字节是
**加载顺序序号** —— 只有游戏运行起来才知道。旧表能用，只有一个原因：

> Starfield.esm **永远是 0 号**（基础游戏必须是第一个 master），所以它的记录 FormID
> 在离线时就能写死。

DLC 不是 0 号：`ShatteredSpace.esm` 里的一条任务在文件里写的是 `0x01xxxxxx`
（前缀 = 它在自己 master 列表里的位置），而运行期可能是 `0x0Cxxxxxx`、`0x11xxxxxx`……
换个 MO2 排序就变。这就是「DLC 支持」的全部难点所在。

## 二、术语与实测数据（本机 2026-09-20）

| 插件 | 是什么 | TES4 flags | master 列表 | 自己的记录前缀 | QUST 条数 | 入表条数 |
| --- | --- | --- | --- | --- | --- | --- |
| `Starfield.esm` | 基础游戏 | `0x81`（ESM+Localized） | — | `0x00` | 2077 | 202 |
| `ShatteredSpace.esm` | **破碎空间**（官方 DLC） | `0x81` | `[starfield.esm]` | `0x01` | 241 | 22 |
| `SFBGS00D.esm` | 自由航道更新（地球舰队的前置 master） | `0x81` | `[starfield.esm]` | `0x01` | 116 | 15 |
| `SFBGS050.esm` | **地球舰队**（官方 DLC，`SFTER_*` 前缀） | `0x81` | `[starfield.esm, sfbgs00d.esm]` | `0x02` | 134 | 22 |

* 四个都是普通（full）插件 —— 没有 light/ESL。`SFBGS004/007/008/Constellation` 那些是
  light（flags 带 `0x100`），`SFBGS003/006` 是 medium（`0x400`）——**本项目目前不收录它们**
  （用户需求只点名的两个 DLC + 它们的前置更新）。
* 怎么自己复现这些数字：
  ```powershell
  python tools\esm\esm_header.py "D:\SteamLibrary\...\ShatteredSpace.esm"   # 头 + master + 组统计
  python tools\esm\quest_dump.py "D:\...\SFBGS050.esm"                       # QUST 条数 / 类型分布
  ```

## 三、链路改造（4 处）

```
离线（构建期）                          运行期（DLL）
─────────────────────────────────     ──────────────────────────────────────────
fetch_sources.py                       Masters::Refresh()
  ├ 每个 master 的 strings 表             └ 前缀探测（第 18 轮重写，见 3.4）：
  │  <master>_{en,zhhans}.strings            · 拿表里该 master 的记录号当样本
  └ quests_all.json（多 master QUST）        · 扫 prefix<<24 | local 问 LookupByID
        ↓                                    · 全量命中率 ≥90% ⇒ 认定序号
gen_quest_table.py → SAQ_QuestTable.h    MakeFormID(master, local) = prefix | local
  { localFormID, master, ... }                ↓
        ↓                                BuildRuntimeRows()  每次打开菜单重建
gen_guide_targets.py                      （master 没加载 ⇒ 整批跳过、日志写明条数）
  引导目标也是 { refrLocal, refrMaster }
```

### 3.1 字符串表：DLC 的名字在它自己那一份里（最容易漏的一步）

任务名 = QUST 的 `FULL`（u32 字符串 ID）→ 到**该插件自己的**.strings 里查。
DLC 的字符串不在 `Starfield - Localization.ba2` 里，而在：

| master | 字符串所在 ba2 | 文件 |
| --- | --- | --- |
| ShatteredSpace.esm | `ShatteredSpace - Main02.ba2` | `strings/shatteredspace_{en,zhhans}.strings` |
| SFBGS050.esm | `SFBGS050 - Main.ba2` | `strings/sfbgs050_{en,zhhans}.strings` |
| SFBGS00D.esm | `SFBGS00D - Main.ba2` | `strings/sfbgs00d_{en,zhhans}.strings` |

命名规律：**插件名小写 + `_语言.strings`**（`gen_quest_table.py::master_strings_key`）。
漏了这一步的症状很有迷惑性：DLC 任务**全部消失**（取不到名字 ⇒ 命中「无本地化名」过滤 ⇒
被当成内部任务），而不是报错。

抽取（`tools/re/ba2list.py` 现在用 mmap，4 GB 的 ba2 也能秒开）：
```powershell
python tools\esm\fetch_sources.py            # 缺什么补什么（推荐）
# 手工版：
python tools\re\ba2list.py "D:\...\SFBGS050 - Main.ba2" --grep sfbgs050_en.strings --extract ref\strings
```

### 3.2 引导目标也要记 master

一条 DLC 任务引用的 NPC / 地点**可能在基础游戏里**（反之亦然）。所以
`ref/guide_targets.json` 里每条目标带 `refrMaster` + `refrSmall`，表里存成
`guideRefLocal + guideRefMaster`，运行期再拼。实测四个 master 的目标分布正常
（ShatteredSpace 的 21 条目标都指向它自己）。

### 3.3 别名数据改成直接读 ESM（不再依赖 xEdit 导出）

原来靠 `ref/xedit/quests_typed.txt`（xEdit 无头导出，一个 ESM 几分钟）。
DLC 要再跑几次太贵，而 QUST 的别名子记录本来就在记录里：
`ALST`(别名 id) → `ALID`(名字) → `ALUA`(NPC) / `ALFR`(REFR) / `ALFL`(地点)。
`gen_guide_targets.py` 现在直接解析它们，xEdit 导出在这条链路上不再需要。

### 3.4 前缀探测（第 18 轮重写）+ 全量确认

**为什么重写**：第 17 轮用 `TESDataHandler::files` 拿「插件名 → 序号」，
2026-09-20 09:40 实测**四个 master 全部报「未加载」**（而游戏 Data 目录里它们都在、
ESM 通道前缀=0x0F 证明 16+ 插件已加载）—— commonlibsf 的 TESDataHandler 结构体
偏移在本游戏版本上不可信（formArrays 第 5 轮就踩过同款，见 docs/02）。
**结论：凡是 commonlibsf 硬编码的结构体偏移，都不要用。**

新方案「前缀探测」不碰任何结构体布局，只用两个已实测可靠的接口：
`TESForm::LookupByID`（按 ID 问引擎要表单）+ 虚表核验（确认是 TESQuest）：

```
对每个 master：
  1. 从静态表取该 master 的记录号（去重 + 等距采样 ≤6 条）；
  2. 阶段 1（找候选）：用样本扫全空间 ——
       full 插件：prefix<<24 | local，prefix ∈ 0x00..0xFD
       light(ESL)：0xFE000000 | (smallIndex<<12) | local，smallIndex ∈ 0x000..0xFFF
                    （只在 full 段一个都没命中时才扫）
     能查到且虚表是 TESQuest ⇒ 候选；一命中即停（多样本是容忍「某条记录被删」）
  3. 阶段 2（确认）：把该 master 的**全部**记录按候选前缀数一遍命中率，
     取最高者；≥90% ⇒ 认定，否则按「未加载」处理并留 WARN 作证据。
```

自检锚点：**Starfield.esm 必须解析出 0x00**（基础游戏永远是第一个 master）。
不满足 ⇒ 打 WARN，且本次**不缓存**结果（下次打开菜单重试）—— 避免把
「游戏尚未就绪」这种瞬时状态钉死成「表里什么都没有」。

日志形态（第 18 轮起）：

```
数据源：Starfield.esm 序号=0x00 前缀=0x00 记录命中 202/202；ShatteredSpace.esm 序号=0x0C 前缀=0x0C 记录命中 22/22；
       SFBGS050.esm 序号=0x0D 前缀=0x0D 记录命中 22/22；SFBGS00D.esm 序号=0x0B 前缀=0x0B 记录命中 15/15
```

「未加载（或档位不支持，跳过其任务）」就是探测不到的形态。

成本：已加载的 master ≈ 254 次扫描 + 全量确认；未加载的 master 最多再扫 light
空间（4096 次）—— 都在毫秒级以内，且**一次游戏运行内加载顺序不会变** ⇒ 基础游戏
解析成功后做会话级缓存，之后零成本。

medium / blueprint 档位探测不到（FormID 方案未验证）⇒ 表现为「未加载」，
**宁可跳过也不猜**；light 的扫描分支已实现但本机没有真实样本可验（算法来自引擎规则）。

## 四、不装 DLC 的玩家会怎样

* master 查不到 ⇒ 那批条目在 `BuildRuntimeRows()` 里就被丢掉（日志：`未加载（跳过其任务）`）；
* 引导目标属于未加载 master ⇒ 引导请求按「没有引导目标」拒绝（界面回滚竖条 + OFF 音）；
* 内嵌回退数据（`SaqEmbeddedPayload.inc`）**只含 Starfield.esm 的 202 条** ——
  内嵌载荷必须写运行期 FormID，DLC 的离线算不出来。代价是 C++ 推送成功前的那
  0.3~0.8 秒里看不到 DLC 条目。

## 五、结论与遗留

* 表规模：**202 → 261 条**（+59：破碎空间 22 / 地球舰队 22 / 自由航道更新 15）；
  引导目标覆盖 209/261 = 80%。
* 已知的显示问题（数据本身如此，不是解析错误）：地球舰队的
  `SFBGS033_Platypig / FungalTurtle / GuineaHopper / PygmyCoralBug / RazorCrestedBeetle`
  五条活动在**中英文里都叫「鸭嘴猪 / Platypig」**（B 社复用了同一个名字），列表里会看到
  5 条同名活动。
* 以后要再加 master（比如玩家装了其它官方 Creation）：在
  `tools/esm/fetch_sources.py` 的 `SOURCES` 里加一行（esm + 字符串所在 ba2），
  跑一次 `build-saq.ps1` 即可 —— DLL 侧完全不用改（表里带 master 名）。

## 六、第 78 轮：DLC 的「进度没到不显示」（对话条件 + 为什么没有 Papyrus 边）

DLC 的**剧情后续**（破碎空间 虚妄的得诺者→…→栉比堡垒 / 地球舰队 失踪的华庭号→…）也属于
「玩家还没到就接不到」的那一类。基础游戏靠 **Papyrus 源码里的启动边**（链式门槛，第 67~77 轮），
但**官方 DLC 不发 .psc**：

| 来源 | ShatteredSpace | SFBGS050（地球舰队） | 能不能当「启动边」证据 |
| --- | --- | --- | --- |
| `.psc` 源码（`Data\Scripts\Source\Base`） | ❌ 只有 `SFBGS00D` 等少数目录 | ❌ | — |
| BA2 里的 **`.pex`** | ✅ 363 个 | ✅ 311 个 | ✗ 只能抽字符串表（`tools/re/pex_strings.py`）：MQ_Shell / DialogueHV* 与各 MQ **双向引用** ⇒ 定不出方向 |
| QUST **记录级 CTDA** | ✅（`quests_all.json` 的 `ctda`） | ✅ | ✗ 只有 4 条任务有跨任务引用，且多为成对/非表内引用 |
| **DIAL/INFO 条件**（对话侧） | ✅ | ✅ | ✅ **采用**：`scan_info_gates.py --esm <DLC> --self-master <名>` → `analyze_info_gates.py`（第 78 轮扩成多 master） |

* **实现**：四个 master 各扫一份 `ref/info_gates*.json`（构建脚本在缺失时自动补扫）；
  前置任务的 master 写进 `kInfoConds` 的第 2 列（kQuestMasters 下标）⇒ 运行时
  `Masters::MakeFormID` 解析 ⇒ DLL 侧零改动。
* **效果**（空存档模拟）：DLC 20 条任务有门槛，其中地球舰队的
  失踪的华庭号 / 隐蔽入侵 / 生命之器 / 电力短缺 / 前哨三连会**真的被藏**；
  破碎空间的 MQ02~MQ06 因参与对话里含「只带 want=0 的中性组」按既有规则放行
  （保守 —— 详见 `docs/08` 十二·补二）。
* **结论/边界**：破碎空间主线后续目前仍会显示 —— 想收口需要「实机推进 + harness 验证」
  拿到真实的完成阶段，**不做猜测性门槛**（猜错 = 误藏，比误显更糟）。

## 七、第 90 轮：DLC 的「可重复任务」（SFBGS00D · SFFL 家族 5 条）

自由航道更新（`SFBGS00D.esm`）的 SFFL 家族 5 条**都是可重复任务**（官方脚本里的重启机制，
逐条证据见 `docs/11` 第 90 轮一节）：

| EDID | 任务 | 机制 | 接取点 |
| --- | --- | --- | --- |
| SFFL_R02 | 职业杀手 | `TimesCompleted.Mod(1)` + `Cooldown = GameDaysPassed + 1.5` | 锚点星际站 · 仲裁者 |
| SFFL_AnchorpointZ02A | 备用零件 | `SFFL_AnchorpointZ02_RepeatGlobal` + 重复管理器（计时 7200 秒 = 2 小时） | 锚点星际站 · 麦迪·温 |
| SFFL_AnchorpointZ04 | 回收行动 | `..._Z04_RepeatGlobal` + 同一管理器 | 锚点星际站 · 基利安·布莱斯 |
| SFFL_R01 | 危险材料 | `PlaythroughCount.Mod(1)` + `SFFL_R01_Timestamp = GameDaysPassed + 1~2` | **随机太空遭遇**（无固定接取点） |
| SFFL_R03 | 紧急救援 | `SEScript.SetCooldown()`（Space Encounter 冷却） | **随机太空遭遇**（无固定接取点） |

* **DLL 侧零改动**：可重复标记走静态表的 `repeatable` 列（第 89 轮的机制），
  DLC 行只是多了几行数据（`kRepeatableNotesZh/En` 的文案里写明「锚点星际站」等地点）；
* **随机太空遭遇**（R01 / R03）用 `noPickup` 标记：清单核验要求它们**恰好没有**引导候选
  （没得导航），文案写清触发方式（「完成后过 1~2 个游戏日在太空中还可能再次遇到」），
  不写「去找谁」；
* DLC 条目**不在内嵌回退载荷里**（那份只含基础游戏）⇒ 本轮**不需要重编 SWF**；
* 三条「未收」的基础游戏任务（独立盟之巅 / 供应线路 / 传播新闻）定案**不是**可重复任务
  —— 见 `docs/11` 第 90 轮 10.2（其中「供应线路」更正了第 89 轮「无 CQ 标记」的误判）。

## 八、第 98 轮：DLC 链式门槛取证 —— 反编译 `.pex`（六节遗留缺口的解法）

> 2026-09-22。起因 = 六节留下的那句「破碎空间主线后续目前仍会显示 —— 想收口需要
> 『实机推进 + harness 验证』，不做猜测性门槛」。本轮证明：**不需要人工玩，也不需要猜**
> —— 官方虽然不发 `.psc`，但 `.pex` 可以反编译回等价源码（含**属性声明**与**调用点**），
> 启动边与基础游戏一样是硬数据。

**结论（可行性）**：

| 环节 | 结论 |
| --- | --- |
| `.pex` 格式 | Starfield = **version 3.12 / gameId 4**；`tools/re/pexinfo.py` 能读头部与字符串表 |
| 反编译 | **Champollion（Orvid 分支）v1.3.2 直接支持**（`tools/champollion/Champollion.exe`，1.8 MB，第三方二进制不入库）：把 `qf_*.pex` 变回**可读 .psc**（属性声明 `Quest Property SFBGS001_MQ02`、fragment 函数体、调用原文都在） |
| 一键取证 | 新工具 **`tools/esm/gen_dlc_chain.py`**：① 从 BA2 抽 `.pex`（ShatteredSpace 363 / SFBGS050 311 / SFBGS00D 293）；② 反编译到 `tmp/psc_dlc/`；③ 抽候选启动边 → `ref/dlc_chain_candidates.json`（**33 条表内任务 / 137 条边**）；④ 定稿表逐条核验 → `ref/quest_chain_dlc.json` |
| 运行时 | **零代码改动**：`StaticChainGate` 本来就带 `hostMaster`（跨 master 前置），第 78 轮的 INFO 门槛已经跑通同一套 `Masters::MakeFormID` |

**破碎空间主线的 6 条真实启动边**（定稿 `ref/quest_chain_dlc.json`，全部核验通过）：

| 后续任务 | 启动边 | 官方字节码原文 |
| --- | --- | --- |
| 虚妄的得诺者 `MQ02` | `MQ01@10000` | `qf_sfbgs001_mq01…:529` `SFBGS001_MQ02.SetStage(100)` |
| 家族的调和 `MQ_Shell` | `MQ02@2000` | `qf_sfbgs001_mq02…:496` `SFBGS001_MQ_Shell.SetStage(100)` |
| 狂热逾界 `MQ03` | `MQ_Shell@100` | `qf_sfbgs001_mq_shell…:96` `SFBGS001_MQ03.SetStage(100)` |
| 信念之争 `MQ04` | `MQ_Shell@100` | 同上 `:97`（**三条议会任务一起开**） |
| 发掘过去 `MQ05` | `MQ_Shell@100` | 同上 `:98` |
| 栉比堡垒 `MQ06` | `MQ_Shell@1100` | `qf_sfbgs001_mq_shell…:233`（终局 fragment） |

**哪些形态不是启动边**（这批候选里的噪声，判据写进工具与本节，避免以后重踩）：

| 形态 | 例 | 为什么排除 |
| --- | --- | --- |
| 调试跳关 fragment（stage 0000/0001/0002…） | `MS04@0 → MQ02.SetStage(1000)`（同函数里 `MoveTo(测试 marker)`）/ `MQ_Shell@1` `Self.SetStage(0)→(100)` | 官方给 CK 用的「跳到某 stage」入口，玩家路径不会走到 |
| 版本补丁修复 fragment | `Patch_Update08@0 → MQ03.SetStage(160/400/100)` | 修老存档的补丁（片段自带条件），不是进程边 |
| 回写（后一个任务改前一个任务的 stage） | `MQ03@200 → MQ_Shell.SetStage(300)` | 不是「谁能启动谁」，收进来只会让门槛虚化 |
| `SetStage(0)` | — | 重置/回退 |

**顺带查的另一来源（SMQN / Story Manager）**：三个 DLC 共 101 个 `SMQN` 节点 / 180 条 `CTDA`
（新工具 **`tools/esm/scan_smqn_gates.py`** → `ref/smqn_gates.json`；函数号对照
`0x38=GetQuestRunning / 0x3A=GetStage / 0x3B=GetStageDone / 0x21F=GetQuestCompleted`）。
「引用别的任务」的条件共 13 条，其中**只有 2 条的目标是我们表内的任务**：

| 节点 | 条件 | 被启动的任务 |
| --- | --- | --- |
| `SFTER_MS01_IntroSE` | `GetQuestCompleted(SFTER_MQ01) == 1` | 地球舰队 · **失踪的地球人**（要先做完**失踪的华庭号**） |
| `SFTER_MS02QuestNode` | `GetQuestRunning(SFFL_MS02) == 0` | 地球舰队 · **隐蔽入侵**（守「星星派对没在跑」） |

其余 11 条的目标都是内部任务（随机对话 / PostQuest 节点），且 `GetQuestRunning/GetStageDone/
GetQuestCompleted(自己)` 这种自引用按既有约定**不算门槛**（`docs/08` 4.2）。
⇒ 收法建议：走**进度门槛**（`kQuestConds` 已支持 `GetQuestCompleted` / want=0/1），
或在 `analyze_ctda.py` 侧加一个「SMQN 来源」——属二期。

**二期候选**（候选清单里还没收的，`ref/dlc_chain_candidates.json` 可随时复跑核对）：

* 破碎空间 · 中插「另一侧」`MQIN` ← `MQ03@4000` / `MQ04@7000` / `MQ05@1600`（三条收尾）；
* 破碎空间 · `VKaiZ03b` ← `VKaiZ03a@300`、`VKaiZ03a` ← `VKaiZ03b@998/999`（结局分支）；
* 地球舰队链：`SE_MQIntro` ← `MQIntro@600`、`MQ01` ← `SE_MQIntro@200`、
  `MQ02B` ← `MQ02A@9999`、`MQOutpostUC/FC/RI` ← `MQ02B@1180/1182/1184`、`MS02` ← `MQ03@1700`；
  ★ `MQ02A ← MQ01`（`sfter_mq01questscript` 的 `QuestCompleted` 函数）**没有宿主 stage**
  —— 工具会以 `need_stage` 记下，需要人工翻成「MQ01 的完成 stage」再收；
* 自由航道：`SFFL_Z01 ← SFFL_Z01_SE1@10/150`、`SFFL_AnchorpointZ01/Z03 ← DialogueAnchorpoint@90/95`；
* ★ **待复核**：破碎空间的 `DialogueHVDazra@5` 一次 `Start()` 8 条城市支线
  （MS01/MS04/MS05/VKaiZ01/02/03a/DazraZ01/DazraZ03）—— 像调试入口，但也可能是
  「进城后解锁全城支线」的真实时点，需要对照 `DLC001_DialogueHVDazra` 的 stage 结构再定。

**落地（离线三步已完成，2026-09-22 同日）**：

| 步骤 | 内容 | 判据 |
| --- | --- | --- |
| ① 数据管线 | `gen_quest_table.py` 新增 `--chain-dlc`（四个数据源合并：编号链 + 扩展边 + **DLC** + 同伴后续）；`build-saq.ps1` 加一步跑 `gen_dlc_chain.py`（宽容：没 Champollion 就沿用旧产物） | 静态表 **链式边 63 → 69 条 / 有边任务 66**；`hostMaster = 3`（ShatteredSpace） |
| ② verify | 期望值改为「**四个**数据源逐边对账」，宿主过滤改成「在表内 master 集合里」（不再限定基础游戏），期望集合改用**记录号**（表行首列）—— DLC 的 `formid` 带 master 前缀，直接用会假红 | `verify` **0 MISS**，含 6 条 DLC 样本（`MQ02 ← MQ01@10000` … `MQ06 ← MQ_Shell@1100`）+ `kQuestMasters` 下标检查 |
| ③ 黄金快照 | 新增 `ref/quest_chain_dlc.json` 一件 + 表摘要「链式边 69」 | 离线层 **18 用例 / 929 断言 + 15 件快照全绿**；DLL 重建部署（`部署 == 工作区`，内嵌载荷未变 ⇒ 不用重编 SWF） |

★ 顺带修掉一个口径 bug：`gen_dlc_chain.py` 早先把 `formid` 写成了**记录号** ——
`ref/*.json` 的约定是**文件内 FormID**（带该文件自己的 master 前缀，DLC 即 `0x01xxxxxx`），
与 `quest_chain.json` / INFO 门槛一致；记录号只用在 `host_local` 一侧。

**harness 用例（已写好 ⇒ 第 100 轮 29/29 实测收口）**：`[case:r98_dlc_chain]`（A：空进度 ⇒ 六条后续里
**任一**进「链式没到」名单）+ `[case:r98_dlc_chain_pass]`（B：`quest.start/stage` MQ01@10000
⇒「虚妄的得诺者」不再被链式藏）—— 设计说明见 `docs/09` 十四·补二十四；跑完即为
「DLC 收口」实机验收（随后 0.1.10 打包）。

---

## 九、第 99 轮：B 段用例实测复盘 —— 写侧推不动「MQ01@10000」（改推 `MQ_Shell@100`）

> 2026-09-22（19:13~19:21 会话，第 98 轮产物全量实测：29 条用例 **28 PASS / 1 FAIL**）。
> 唯一 FAIL = `r98_dlc_chain_pass`（B 段）。**A 段 PASS**：六条 DLC 后续在空进度下确实
> 进「链式没到」名单（产品读端的「藏」方向 + 跨 master 读取 = 实机实证）；
> 出问题的是 B 段的**状态构造**（harness 写侧），不是产品。

**实测证据（为什么「推 MQ01」不可行）**：

* B 段发出 `quest.reset / quest.start / quest.stage ~0x000121DB 10000`（三条命令回执
  全部 `结果=0（成功）`、DLL 侧「参数解析 → 运行期 0x010121DB」正确），但推进前后
  `menu.open` 的整段统计行**逐字段一致**：`已开始=40` / `已完成=1` /
  `INFO门槛=78(过54/藏21/放行2/未知0)` / `链式门槛=55(过4/藏49/未知0)`（「虚妄的得诺者」
  仍在名单）—— 引擎状态**零变化**；
* 对照链路（写侧机制本身没问题）：基础游戏 `r67/r69/r77/r87` 的 B 段
  （`start + SetStage` 推进 CF01 / 面试 / 挑拨离间 / UC04 的链）实测都能让目标
  「不再被藏」；**DLC 也有成功样本** —— `r90`（职业杀手，SFBGS00D）用
  `reset → start → complete` 把「已完成」从 1 推到 2、清场后回到 1，闭环可见；
* **反编译源码给出更硬的定性**：`Fragment_Stage_10000_Item_00`
  （`qf_sfbgs001_mq01_010121db.psc:527`）的整个函数体 =
  `Self.SetObjectiveCompleted(2100)` → `SFBGS001_MQ02.SetStage(100)` →
  **`Game.AddAchievement(51)`** → **`Self.Stop()`**。
  ⇒ 即便推进成功，这条收尾 fragment 也会**立即 Stop 掉 quest**（stage done 位不可依赖、
  观测不到），而且会**解锁玩家成就**（污染测试账号）—— 这条路既不可观测、也不该走；
* ★ 根因备注（未完全定论）：写侧对 MQ01 无效有两种可能 —— ① 引擎拒绝脚本 `Start()`
  （大主线任务的 alias/依赖保护，启动后即中止）；② `SetStage(10000)` 生效、但收尾
  fragment 的 `Self.Stop()` 让 stage done 位事后不可依赖。现有日志无法区分二者，
  但**结论一致**：该路径不适合做用例判据。

**用例设计要点（第 98 轮定稿、第 99 轮沿用）**：

* A 段用「**六条任一**」而不是点名一条：测试存档的 DLC 进度未知，且 INFO 门槛在链式门槛
  **之前**判定 —— 只要有一条没被 INFO 先藏就会进链式名单（离线预判
  `ref/_dlc_info_precheck.py`：六条的 10/12/9/11/22/13 个对话组里分别有 6/3/3/2/9/3 组
  「可能可用」⇒ 都不会被 INFO 藏）；名单里的名字后面只写 `[0x`、不写死运行期 FormID
  （DLC 前缀随加载序变，`~0x…` 记录号写法就是为它存在的）；
* 两条用例插在 `r62_reload_observe`（读档用例）**之前**，各自清场（只动这 7 条 DLC
  任务；不传送、不开星图、不读档）。

**处置（第 99 轮：用例 + verify 同步，产品零改动）**：

* B 段改推**同族的开场边**：`quest.start/stage ~0x00035E1B 100`（「家族调和」MQ_Shell）——
  `Fragment_Stage_0100_Item_00`（`qf_sfbgs001_mq_shell_01035e1b.psc:92`）只做
  「显示 3 个 objective + `MQ03/MQ04/MQ05.SetStage(100)` + `MourningDevice_Control.Start()`
  + `SetActive`」——**没有 Stop、没有成就**；一次推进覆盖三条议会任务的共同边
  （MQ_Shell@100），断言「狂热逾界 / 信念之争 / 发掘过去」三条**都不在**「链式没到」名单
  （比原设计「一条」更强）；收尾 reset 七条照旧（自清场）；
* 顺带修两个名字笔误：原用例把 `MQ03` 写成「狂热逼界」、`MQ05` 写成「发觉过去」
  （游戏内真名 = **狂热逾界 / 发掘过去**）—— 旧版靠断言的「或」语义没暴露；
  A 段与 verify 的标签一并修正；
* verify：+1 条反向检查「不许再出现 `quest.stage ~0x000121DB 10000`」（防回归到不可达
  设计），B 段断言形状检查同步更新；离线层零变化（数据未动）；
* `MourningDevice_Control`（fragment 顺手启动的辅助任务）不在静态表内（`~0x` 解析不了）
  —— 不单独清场：它无害，且紧接着的 `r62` 读档会整体覆盖。

**★ 第 100 轮实测收口（19:40~19:47 会话 / 467687 ms / `驱动器 v70`）**：

* 全量 29 条 **29/29 全 PASS** —— B 段改推方案**一次通过**：`quest.start/stage ~0x00035E1B 100`
  后 `assert.nolog` 3000 ms 窗口无「狂热逾界 / 信念之争 / 发掘过去」命中；
* ★ 强佐证（引擎状态**真实变化**，与第 99 轮的正反对照）：B 段推送条数 **216 → 219（+3）**、
  `keep 212 → 215`、`questData 10 → 11`（`quest.start` 把 MQ_Shell 写进玩家日志）——
  第 99 轮推 MQ01@10000 时这些字段是**逐字段一致**的；
* 收尾 reset 七条自清场（`seq=119~125` 全成功）；`stamp=63` 全用例一致；
  A 段「藏」+ B 段「放行」= **DLC 链式门槛双向实证** ⇒ **DLC 收口完成**；
* 健康：日志 686948 B（曾超 1MB ⇒ `SizeLimitedFileSink` 清空旧内容，与第 94/97 轮同现象）+
  `[E]` 0 / `[W]` 0；`check_results.py` / `log_hygiene.py` 退出码均 0；verify 全过。

---

## 十、第 101 轮（B3）：链式门槛二期 —— 把候选清单里证据同样硬的边全收

> 起源：第 98 轮收口时留下的「二期候选」（本节末尾的清单）。本轮**只做取证 + 数据落地**：
> 运行时零改动（`StaticChainGate` 本来就只有 host/master/stage，跨 master 第 98 轮已通）。
> 结果：`ref/quest_chain_dlc.json` **6 → 21 条边 / 6 → 18 条任务**；
> 表内链式门栏 **66 条任务 / 69 边 → 78 条任务 / 84 条边**。

### 10.1 工具侧两处升级（`tools/esm/gen_dlc_chain.py`）

| 升级 | 内容 |
| --- | --- |
| **op 进定稿表** | 定稿元组从 4 元扩成 6 元：`(目标, 宿主, 写入表的 stage, op, 候选里的 stage, 说明)`。二期的新边大多是 `Start`（旧实现写死只认 `SetStage` ⇒ 一条都收不进来）。op 只做证据留档，运行时不用 |
| **need_stage 边可收** | 非 stage fragment 的形态（脚本函数里的 `QuestCompleted()` → `MQ02A.Start()`）现在能落成「宿主的 **Complete-Quest stage**」，且该 stage **从官方 ESM 现读核验**（QSDT bit0；写错 ⇒ 定稿直接失败）。`SFTER_MQ01` 的 CQ stage = **1700** |

### 10.2 收进来的 15 条边（逐条都有字节码原文）

| 分组 | 边 |
| --- | --- |
| 破碎空间 · 另一边 `MQIN` | ← `MQ03@4000` / `MQ04@7000` / `MQ05@1600`（三条收尾分支各 `MQIN.SetStage(10)`，fragment 里带 `If !MQIN.GetStageDone(10)` 守卫）|
| 地球舰队 `SFTER_SE_MQIntro` | ← `MQIntro`（地球舰队侵袭）@600 `Start()` |
| 地球舰队 `SFTER_MQ01`（失踪的华庭号） | ← `SE_MQIntro`@200 `Start()` |
| 地球舰队 `SFTER_MQ02A`（深入VOID） | ← `SFTER_MQ01`@1700（**need_stage**：`sfter_mq01questscript.psc:1008` 的 `QuestCompleted()`；1700 = CQ stage）|
| 地球舰队 `SFTER_MQ02B`（失控） | ← `MQ02A`@9999 `Start()` |
| 地球舰队 `MQOutpostUC/FC/RI`（互助互赢/互谅互让/互利互惠） | ← `MQ02B`@1180/1182/1184 `Start()` |
| 地球舰队 `SFTER_MS02`（隐蔽入侵） | ← `MQ03`@1700 `Start()` |
| 自由航道 `SFFL_Z01`（失踪的爱人） | ← `SFFL_Z01_SE1`@10 `Start()` / @150 `SetStage(120)` |
| 自由航道 `SFFL_AnchorpointZ01`（绝非虚言） | ← `SFFL_DialogueAnchorpoint`@95 `SetStage(5)` |
| 自由航道 `SFFL_AnchorpointZ03`（旧伤） | ← `SFFL_DialogueAnchorpoint`@90 `Start()`（+ 开场 Scene）|

### 10.3 三处「有意不收」（verify 里有反向检查，防以后被误加回来）

| 不收的对象 | 决定性证据 | 为什么不收 |
| --- | --- | --- |
| `SFTER_MQIntro`（地球舰队侵袭）← `SE_MQIntro@200` | 它是这条线的**入口**，全量反编译里它自己**没有任何启动边**（入口在数据侧）| 挂上链式门槛 ⇒ 永远不被放行 ⇒ **必然误藏**（比误显糟）|
| `DialogueHVDazra@5`（一次 Start 8 条城市支线：MS01/MS04/MS05/VKaiZ03a/DazraZ01…）| 全量反编译里 `SetStage(5)` **只**出现在 `Fragment_Stage_0000`（MS03 / DazraZ03），同函数里还有 `MoveTo(调试 marker)` + `AddPerk(...)`；正常路径一律 `SetStage(1)` | 调试入口，不是「进城解锁全城支线」|
| `VKaiZ03a`（失而复得）/ `VkaiZ03b` | 互启环：`VkaiZ03b` 的唯一 `Start()` 在 `VKaiZ03a@300`，`VKaiZ03a` 的 `Start()` 只有 `VkaiZ03b@998/999` + 上面那条调试 fragment；两者 `DNAM` bit0（Start Game Enabled）= 0 | 真实入口在数据侧（触发器/Scene）⇒ 挂上有误藏风险；留三期（需查 Scene 的 StartQuest 动作）|

### 10.4 噪声判据（本轮又用上两次）

第 98 轮定的四条判据照旧：**调试跳关 fragment（stage 0000/0001/0002）、版本补丁修复片段、回写、`SetStage(0)`** 都不算启动边。本轮实见两例：

* `MQIN ← MQ_Shell@2`：stage 0002 的 fragment 是「跳到某 stage 调试入口」；
* `MQIN ← MQ03@16`：整个函数是一长串 `Self.SetStage(...)` + `MoveTo(Alias_MQ03EkrisQS)` +
  `Self.SetStage(0)/(100)…` + `MQIN.SetStage(10)` + **`MQIN.Stop()`** ⇒ 典型调试跳关。

### 10.5 验证与落地（离线全绿）

| 步骤 | 判据 |
| --- | --- |
| 定稿 | `gen_dlc_chain.py --skip-extract --skip-decompile` ⇒ **18 条任务 / 21 条边**，全部对候选核验通过（含 need_stage 边的 CQ stage 现读核验）|
| 静态表 | `gen_quest_table.py` ⇒ 链式门槛 **78 条任务 / 84 条启动边** |
| verify | **0 MISS**：边集合与四个数据源逐边对账 `84/84 · 78/78`；+14 条二期样本（每条都带 host master 现算的下标）+ 两条反向检查（不含调试跳关边 / 「有意不收」三处未进表）+ 用例计划 4 条 |
| 离线层 | 18 用例 / 929 断言 + 15 件快照全绿（快照有意更新两处：`quest_chain_dlc.json` 6→21 边、`SAQ_QuestTable.h` 链式边 69→84）|
| 重编 | 内嵌回退载荷**逐字节不变**（DLC 条目不在里面）⇒ **不用重编 SWF**；Papyrus / ESM 也不动 ⇒ 只重编 DLL |

### 10.6 harness 用例（A 已落地；B 段第 103 轮并入 r98 B 段）

`[case:r101_dlc_chain2]`（A：reset 新目标与宿主 ⇒ 「链式没到」名单里**至少一条**新目标）。

B 段（二期边的**放行**判据）第 103 轮起并入 `[case:r98_dlc_chain_pass]` —— 原因：
**`MQ_Shell` 一个会话只能推一次**（引擎对「已运行过又被 Reset 的任务」拒绝再次 `Start`：
同会话第二次 `start` 后 `已开始=40` / `链式 过4/藏59` / 探针全无变化；而首次启动 =
`已开始 34→44` + `链式 过4→7`）。合并后的构造 = **一次预热覆盖两条判据**
（三条议会任务放行 +「另一边」此刻仍在名单里的负向对照；再 `stage MQ03 4000` ⇒
`ui.select ~0x0010AAD5` 命中），`stage MQ05 1600` **只记录不放行断言** ——
`MQIN` 也受「已运行过又被 Reset ⇒ 拒绝二次启动」约束（4000 那条 fragment 已经把它起了）
⇒「复位后再由 1600 单独放行」的隔离条件在一个会话里复现不了。设计要点：

* 「或」的成员挑**必然能走到链式判定**的（离线预判：深入VOID / 失控 / MQIntro星际遭遇战 /
  失踪的爱人 在 `ref/info_gates_final.json` 里**没有门槛**；另一边 / 互助互赢… 属 want=0 或
  成对条件形态 ⇒ 不会被 INFO 先藏）；
* 推的 `MQ03@4000` / `MQ05@1600` fragment = `SetObjectiveCompleted/Displayed` + 守卫 +
  关掉几个未死的 Actor —— **无 Stop、无成就**（第 99 轮的教训：不推带
  `Stop()`/`AddAchievement` 的收尾边）；
* 放行证据走**显示层**（`ui.select ~0x0010AAD5` 命中 = 「另一边」进了列表）——
  `链式没到` 是**累积名单**，合并用例里再用 `assert.nolog` 会命中前面那行「另一边 被藏」
  ⇒ 必然假 FAIL（verify 有反向检查）；
* 名字只写 `[0x`（运行期 FormID 带加载前缀，不写死）；用例自清场（reset 五条 + 七条）。
* 判读与实测复盘：`docs/09` 十四·补二十五 / 补二十六 / 补二十七；★ **第 104 轮**（自动测试
  复查 30 条 29 PASS / 1 FAIL 的定调用）：probe 断言的**必然假 FAIL** 与处置（`quest.probe`
  补一行产品日志 —— `assert.log` 只认产品行）见 **`docs/09` 十四·补二十八** / `docs/99`
  第 104 轮块（红线六）。★ **第 105 轮已实测收口**：30 条 **30/30 全 PASS**（五条 probe
  断言全中 + `ui.select ~0x0010AAD5` 命中「另一边」）⇒ 本条 DLC 链式门槛二期（84 边 /
  78 任务）随 **0.1.11** 上传包发布（`docs/09` 十四·补二十九）。
