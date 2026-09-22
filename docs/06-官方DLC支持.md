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
