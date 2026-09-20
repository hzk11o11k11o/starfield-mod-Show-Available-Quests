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
  ├ 每个 master 的 strings 表             └ 遍历 TESDataHandler.files（当前加载的插件）
  │  <master>_{en,zhhans}.strings            · fileName 对上表里的 master 名（大小写不敏感）
  └ quests_all.json（多 master QUST）        · fileIndex.fullIndex / smallIndex = 序号
        ↓                                    · prefix = index << 24
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

### 3.4 抽样自校验（序号算错要能自己喊出来）

`Masters::Refresh()` 之后，每个 master 从表里挑 6 条记录号，按算出来的 FormID 问
`TESForm::LookupByID`，再核验虚表是不是 TESQuest，命中率写进日志：

```
数据源：Starfield.esm 序号=0x00 前缀=0x00 样本 6/6；ShatteredSpace.esm 序号=0x0C 前缀=0x0C 样本 6/6；
       SFBGS050.esm 序号=0x0D 前缀=0x0D 样本 6/6；SFBGS00D.esm 序号=0x0B 前缀=0x0B 样本 6/6
```

出现 `样本 0/6` 就是「序号/位宽算错了」——这条日志是这套机制的保险丝。
light（ESL）插件的方案也实现了（`0xFE000000 | (smallIndex << 12) | local`），
medium / blueprint 两种档位**明确标记为不支持**（宁可跳过也不猜）。

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
