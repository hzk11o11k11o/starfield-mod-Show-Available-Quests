# Nexus 上传素材（v0.1.12）

> 用途：复制下面内容到 Nexus 的 mod 页。Summary 填「名称/摘要」栏，
> Description 填「描述」栏（Nexus 描述框可用 BBCode，纯文本换行也正常）。
> 英文版放在中文版之后，可另起一个描述分栏或直接接在后面。

---

## Mod 名称（Name）

```
Show Available Quests (SFSE) - 可接任务
```

## 摘要（Summary）

```
在任务菜单里新增「可接任务」标签页：列出所有当前能接的非主线任务，选中即可用游戏原生引导（蓝点+路径线）导航到接取地点。支持中文/英文与官方 DLC。
```

## 描述（Description · 中文）

```
[b]可接任务 — Show Available Quests[/b]

Starfield 从不告诉你去哪接任务，全靠自己撞见。这个 mod 在原版任务菜单里加了一个「可接任务」标签页，把当前还能接的支线 / 势力 / 活动 / 事件任务集中列出来——选中一条，就能用游戏原生的任务引导（目标蓝点 + 扫描仪路径线）导航到接取地点。

[b]功能[/b]
[list]
[*] 集中显示所有可接的非主线任务
[*] 收录「地球地标」系列 10 条（阿波罗 / 开罗 / 迪拜 / 香港 / 伦敦 / 洛杉矶 / 纽约 / 大阪 / 上海 / 圣路易斯）：描述里写明**去哪拿哪本书**（对应的书被拾取 / 购买后任务即开始）；点一下即可导航到那本书（伦敦那条书在各大书店，描述里注明）
[*] 汇总「无限任务」的接取入口（12 处任务板：新亚特兰蒂斯 / 阿基拉城 / 霓虹城 / 塞多尼亚 / 霍普镇 / 新家园 / 星船厂 / 星钥站…… + 8 位提供可重复任务的 NPC，条目带「（可重复）」标记），点一下就能导航过去
[*] 选中即可调用游戏原生引导，导航到接取地点（蓝点 / 路径线）
[*] 引导目标优先指向**有名字的任务发布者（NPC）**，而不是附近的路标 / 内部标记；你在远处时自动落到常驻目标，飞近后自动切回 NPC
[*] 已完成的、已在任务日志里的任务自动隐藏（**可重复任务例外**：这类任务完成一次后仍留在列表里 —— 共 20 条，名字前同样带「（可重复）」标记并整组排在列表末尾，描述第一句写明「（可重复）怎么再接」）
[*] **进度没到不会显示**：前置任务没做完、剧情还没推进到的任务不会出现在列表里（判据来自游戏数据里的任务条件 + 对话条件；列表里留下的都是你现在真能接的）
[*] 没有导航目标的任务会明确提示：条目名字前面直接标注**「（不可导航）」**，描述里写明原因，不用点就知道它没法引导
[*] 导航目标很远的任务：远处点引导会先落到**就近位置**（不再「点了没反应」），走近后自动切换到精确目标；极少数（20 条）连就近目标都取不到的任务，描述会**提前**写明「需要靠近」，HUD 会提示、引导保持待生效，靠近后自动生效（不必重新点）
[*] 被引导的任务一旦接取，引导自动取消
[*] 支持中文 / 英文
[*] 支持官方 DLC（破碎空间 / 地球舰队等；未安装的 DLC 不会显示其任务）
[*] 日志写在 mod 目录里，删 mod 不残留；日志不超过 1 MB 自动滚动
[/list]

[b]依赖[/b]
[list]
[*] Starfield 1.16.244
[*] SFSE (Starfield Script Extender) 0.2.21+ —— sfse_1_16_244.dll
[/list]

[b]安装[/b]
用 MO2「从压缩包安装」，启用后确认 SAQ_ShowAvailableQuests.esm 已在插件列表勾选。手动安装：解压后把文件放进 Starfield\Data\（详见包内 README.txt）。

[b]使用[/b]
任务菜单（TAB）→ 「可接任务」→ 选中条目 → 展开子项「前往接取地点」（Enter）= 开始引导（HUD 蓝点 + 扫描仪路径线）；按 SET COURSE（键盘 R / 手柄 X）= 引导 + **自动打开星图并把航线画到接取地点**（与按原版任务一样）。同一条再按一次 R = 引导保持不变、星图**再打开一次**（与原版一致：R 只负责显示目标位置，不会取消追踪）；要取消引导，展开条目选中子项「前往接取地点」再按 Enter。

[b]已知限制[/b]
[list]
[*] 278 条任务中有 54 条暂无导航目标：条目名会标注「（不可导航）」，界面如实提示，不会假装能引导
[*] 无限生成任务本身不显示，但其接取入口（12 处任务板 + 8 位提供可重复任务的 NPC）作为独立条目列出；任何位置都能一键导航过去——在远处先给你一个大致方位，等你走到那块任务板所在的区域，蓝点会自动落到任务板上（不会停在几米外；读档或重启游戏后也会自动校正）
[*] 引导在关闭任务菜单后生效（与原版一致：HUD 蓝点本来就要关菜单才可见）
[*] 「进度没到就不显示」覆盖**两层条件**：任务记录级条件里「引用别的任务」的那一类（7 条任务 / 11 条条件，含条件组里的「或」逻辑，例如「要先完成 A 才能接到 B」），以及任务对话（INFO）里的同类条件（80 条任务 / 415 条对话 / 501 条条件，含官方 DLC，例如「大器晚成」要「孤立无援」完成）；另有**任务链门槛**（后续任务在前置完成前不显示，含官方 DLC）；位置/遭遇类条件暂未覆盖
[*] 会覆盖任务菜单的 UI 文件（missionmenu.swf / missionmenu_lrg.swf），与其它改任务菜单的 mod 需要打补丁
[/list]

[b]兼容性[/b]
仅使用 SFSE + ESM。**不改任何原版数据**：本插件只往那些任务板 / 可重复任务 NPC 所在的 12 个 cell 里**新增**自己的常驻标记引用（用于精确导航）；为了让引擎接受这些新增引用，我们对这些 cell 各写一条**只含 EDID 的空壳 CELL 记录**（官方 Creation 对同一条 cell 用的就是这种写法），**不覆盖 cell 的任何数据字段**。与不触碰任务菜单 UI 的 mod 完全兼容；与修改任务菜单 SWF 的 mod 冲突（需补丁）。

[b]反馈[/b]
遇到问题请附上：SFSE\Plugins\SAQ_ShowAvailableQuests.log、安装方式（MO2 / 手动）、游戏与 SFSE 版本号。
```

## 描述（Description · English）

```
[b]Show Available Quests (SFSE)[/b]

Starfield never tells you where to pick up quests — you just have to stumble into them. This mod adds an "Available Quests" tab to the vanilla mission menu, listing every side / faction / activity / event quest you can still start. Select one and use the game's native guidance (quest marker + scanner route line) to navigate straight to the quest giver.

[b]Features[/b]
[list]
[*] Lists all available non-main quests in one place
[*] Includes the 10 "Landmark" quests (Apollo / Cairo / Dubai / Hong Kong / London / Los Angeles / New York / Osaka / Shanghai / St. Louis): the description tells you which book to pick up (picking it up / buying it starts the quest), and one click navigates you to that book
[*] Includes the pickup points of radiant quests: 12 mission boards (New Atlantis / Akila City / Neon / Cydonia / Hopetown / New Homestead / staryards / The Key...) plus 8 repeatable-job NPCs (4 Trade Authority merchants, 4 Trackers Alliance agents - their entries are tagged "(Repeatable)"), one click to navigate
[*] Native guidance: quest marker + scanner route line to the quest giver
[*] Guidance prefers the **named quest giver (NPC)** over nearby signposts / internal markers; from a distance it falls back to a persistent target and automatically upgrades back to the NPC once you get close
[*] SET COURSE (R / X) goes one step further: it also opens the star map with the route plotted to the pickup location, exactly like a vanilla quest
[*] Already-completed quests and quests already in your log are hidden (repeatable quests are the exception: they stay listed after you finish them - 20 of them - and are tagged "(Repeatable)" and grouped at the end of the list; their description tells you how to take them again)
[*] Quests with no navigation target are clearly flagged (the description explains why) — no dead ends
[*] Some pickup locations only load when you get near: the description says so in advance, and the HUD reminds you after you press guide; the guidance stays pending and activates automatically once you arrive (no need to press it again)
[*] Guidance is cancelled automatically once you accept the quest
[*] Chinese and English games supported
[*] Official DLC aware (Shattered Space, Earth Fleet, …); quests from DLC you don't own are never listed
[*] Log lives inside the mod folder (no leftovers), capped at 1 MB with auto-roll
[/list]

[b]Requirements[/b]
[list]
[*] Starfield 1.16.244
[*] SFSE (Starfield Script Extender) 0.2.21+ — sfse_1_16_244.dll
[/list]

[b]Installation[/b]
Install the archive with MO2 ("Install from archive"), then make sure SAQ_ShowAvailableQuests.esm is ticked. Manual install: copy the files into Starfield\Data\ (see README.txt in the archive).

[b]Usage[/b]
Mission menu (TAB) -> "Available Quests" -> select an entry -> expand the "Go to the pickup location" sub-entry (Enter) to start the guidance (HUD marker + scanner route line); press SET COURSE (R / X) to start the guidance **and** open the star map with the route plotted to the pickup location (just like a vanilla quest). Pressing R again on the same entry keeps the guidance and just opens the star map again (like vanilla: R never cancels tracking); to cancel, expand the entry, select the sub-entry and press Enter.

[b]Known limitations[/b]
[list]
[*] 54 of 278 quests currently have no navigation target; the UI says so honestly
[*] Radiant quests themselves are not listed, but their pickup points (12 mission boards + 8 repeatable-job NPCs) are listed as entries; every entry can be navigated to from anywhere — far away you get the approximate direction, and once you reach the board's area the marker automatically snaps onto the board itself (no more stopping a few metres short; it also self-corrects after a save reload or restart)
[*] Guidance applies after you close the mission menu (same as vanilla: the HUD marker only appears outside menus)
[*] "Hidden when your progress isn't far enough" covers **two layers**: record-level preconditions that reference another quest (7 quests / 11 conditions, including "or" groups, e.g. "you must finish A before B shows up") and the same kind of conditions inside a quest's dialogues (INFOs: 80 quests / 415 dialogues / 501 conditions, official DLC included), plus a quest-chain gate (a follow-up quest stays hidden until its prerequisite is done, official DLC included); location/encounter based conditions are not covered yet
[*] Overrides the mission menu UI (missionmenu.swf / missionmenu_lrg.swf): patching needed with other mission-menu mods
[/list]

[b]Compatibility[/b]
SFSE + ESM only. **No vanilla data is changed**: the plugin only *adds* its own persistent marker references inside the cells that contain those mission boards / NPCs. So the engine accepts them, one EDID-only "stub" CELL record is written per cell (the exact pattern the official Creations use for the same cells) — **none of the cell's data fields are overridden**. Fully compatible with mods that don't touch the mission menu UI; conflicts with mission-menu SWF mods (patch required).

[b]Feedback[/b]
Please include SFSE\Plugins\SAQ_ShowAvailableQuests.log, install method (MO2 / manual), and your game & SFSE versions.
```

---

## 更新日志（Changelog）

### v0.1.13（2026-09-23）
- 改进：**7 条补收任务补上了导航目标**（v0.1.12 里它们还标注着「（不可导航）」）—— 巴雷特个人任务「阴阳两隔」会引导到巴雷特本人；新亚特兰蒂斯「搜查与扣押 / 双城传说」引导到 UC 安保办公室的由实中士；阿基拉城「防御措施 / 误报 / 兽群领袖」引导到阿基拉城广场的戴维斯·威尔逊；「登陆不顺」引导到 GalBank 的马尔科·詹森。现在这 7 条点「前往接取地点」和别的任务一样有 HUD 蓝点 / 扫描仪路径线；无可导航任务的条数 61 → 54
- 其它：内部测试与验证设施更新（不影响游戏内行为；发布包仍不包含任何测试代码）

### v0.1.12（2026-09-23）
- 新增：**补收 7 条此前漏掉的任务** —— 巴雷特个人任务「阴阳两隔」、新亚特兰蒂斯「搜查与扣押 / 双城传说」、阿基拉城阿什塔线「防御措施 / 误报 / 兽群领袖 / 登陆不顺」。这些任务没有任务类型标记，此前被过滤掉了；现在正常显示，并带完整的前置条件判定（进度没到不会出现）。这几条暂无可导航的接取点，条目名会标注「（不可导航）」
- 改进：「进度没到就不显示」的对话（INFO）条件判定升级 —— 支持条件组里的「或」逻辑（例如「A **或** B 推进到某一步」即可显示，此前组里只要有一条没做过就可能一直隐藏）；同时把一批被误当成「接取前置」的任务推进对话从判定里剔除，个别任务不再被错误隐藏
- 其它：可接任务总数 271 → 278；内部测试与验证设施更新（不影响游戏内行为；发布包仍不包含任何测试代码）

### v0.1.11（2026-09-22）
- 改进：「进度没到就不显示」对官方 DLC 的覆盖继续补全 —— 破碎空间「另一边」、地球舰队后续任务（深入VOID / 失控 / 互助互赢·互谅互让·互利互惠 / 隐蔽入侵）、自由航道后续任务（失踪的爱人 / 绝非虚言 / 旧伤）现在也会在前置剧情没推进到时隐藏（判据全部取自官方脚本里的真实启动条件）
- 其它：内部测试与验证设施更新（不影响游戏内行为；发布包仍不包含任何测试代码）

### v0.1.10（2026-09-22）
- 改进：「进度没到就不显示」对官方 DLC 的覆盖补全 —— 破碎空间主线的后续任务（「家族调和」及其后的议会线）现在也会在前置剧情没推进到时隐藏（判据取自官方脚本里的真实启动条件；此前这几条只能保守放行）
- 其它：内部测试与验证设施更新（不影响游戏内行为；发布包仍不包含任何测试代码）

### v0.1.9（2026-09-22）
- 改进：**可重复任务的条目更好认、更好找** —— 做完一次还能再接的任务（共 20 条：城里的重复支线、赏金 / 回收类委托、DLC 锚点星际站的委托等）名字前面现在也标注「（可重复）」，并且**整组集中排列在列表末尾**（接在任务板 /「（可重复）」NPC 入口之后），一眼就能扫到；做完一次后它们依然留在列表里
- 其它：内部测试与验证设施更新（不影响游戏内行为；发布包仍不包含任何测试代码）

### v0.1.8（2026-09-22）
- 新增：**「可重复任务」完成一次后不再从列表里消失** —— 这类任务（共 20 条：赛多尼亚的丹尼斯·艾文林、新家园的几位商人、红里、龙神大厦、锚点星际站、随机太空遭遇……）设计上可以反复接取；完成一次后它们会继续留在列表里，描述第一句写明「（可重复）完成一次后还能再次接取 —— 去找 / 去哪 XX 即可」，照着描述就能再接
- 改进：**没有导航目标的任务一眼可辨** —— 条目名前面直接标注「（不可导航）」（此前要点开描述才知道）；右侧描述仍写明原因，点击时的提示里用的是任务原名
- 其它：内部测试与验证设施更新（不影响游戏内行为；发布包仍不包含任何测试代码）

### v0.1.7（2026-09-22）
- 改进：「进度没到就不显示」的门槛判定升级为引擎级精确语义 —— 支持任务条件里的「或」逻辑。极少数任务（如「亲爱的姐妹」）此前只要前置 A 完成就会显示，现在会等到「A 完成**且**（B **或** C 之一完成）」才显示，进一步减少「显示出来了却还接不到」的情况
- 其它：内部测试与验证设施更新（不影响游戏内行为；发布包仍不包含任何测试代码）

### v0.1.6（2026-09-22）
- 改进：**同伴好感度任务**条目的说明文案更明确 —— 这类任务会在好感度达到一定水平后**自动开始**（不需要跑去找人接取），描述末尾的引导说明同步改为「引导到这位同伴当前所在的位置」；好感度靠带这位同伴一起冒险提升
- 其它：内部测试与验证设施更新（不影响游戏内行为；发布包仍不包含任何测试代码）

### v0.1.5（2026-09-21）
- 新增：**「地球地标」系列任务**（10 条：阿波罗 / 开罗 / 迪拜 / 香港 / 伦敦 / 洛杉矶 / 纽约 / 大阪 / 上海 / 圣路易斯）现在会出现在列表里 —— 它们各对应一本**可以拾取 / 购买的书**，描述里写明「去哪拿哪本书」；点一下即可导航到那本书（或卖书的商人），拿到书任务即开始
- 改进：可接任务总数 261 → 271（+10 条地标任务）；其中 54 条暂无导航目标（界面如实提示）
- 其它：内部测试与验证设施更新（不影响游戏内行为；发布包仍不包含任何测试代码）

### v0.1.4（2026-09-21）
- 新增：**「提供无限任务的 NPC」入口** —— 8 位会提供可重复任务的 NPC（贸易管理局商人 ×4、追踪者联盟探员 ×4）现在也出现在「可接任务」列表里，名字带「（可重复）」标记；点一下即可导航到他们（远处先落常驻标记，走近自动精确到本人）
- 新增：**四大势力开头任务固定显示**（联合殖民地「超越极限」/ 自由星「枝节横生」/ 龙神「重返职场」/ 深红舰队「深藏不露」），固定排在最前，右侧描述写明加入方式；其中深红舰队只给说明（按设计不提供导航）
- 新增：**同伴好感度任务**入口固定显示（任务名前带同伴名，描述提示好感度要求）；后续「承诺任务」仍按进度条件显示
- 新增：**任务链门槛** —— 后续任务在前置任务完成前不再出现在列表里（含官方 DLC 的对话条件）
- 新增：**任务专属图标** —— 列表图标现在与原版任务菜单一致（阵营徽记 / 活动 / 杂项 / 任务）
- 改进：「进度没到就不显示」覆盖范围翻倍（60 → 80 条任务 / 418 条对话 / 492 条条件，含官方 DLC）
- 其它：内部测试与验证设施更新（不影响游戏内行为；发布包仍不包含任何测试代码）

### v0.1.3（2026-09-21）
- 修复：**读档过程中的一个稳定性问题** —— 极少数情况下，读档时插件仍在后台做例行刷新（查任务状态 / 校正导航目标），可能让读档失败退回主菜单，甚至导致游戏崩溃。现在**读档 / 加载画面期间会暂停这些后台工作**，读档完成后自动恢复（对正常游玩无任何影响）
- 其它：内部测试与验证设施更新（不影响游戏内行为；发布包仍不包含任何测试代码）

### v0.1.2（2026-09-21）
- 修复：极少数情况下关闭星图后它又被「残留的航线请求」重新弹开的问题
- 修复：按 SET COURSE（R）后星图偶发被记为「第 2 次尝试」并重画航线焦点 —— 把重试等待窗口放宽到脚本实际应用时间，航线/焦点更稳定（玩家可见行为与 v0.1.1 基本一致）
- 其它：内部测试与验证设施更新（不影响游戏内行为；发布包仍不包含任何测试代码）

### v0.1.1（2026-09-21）
- 「进度没到就不显示」扩展到任务对话（INFO）条件：例如「大器晚成」要「孤立无援」完成后才会出现在列表里（60 条任务 / 290 条对话 / 341 条条件）
- 导航目标很远的任务会**提前在描述里写明**「需要靠近」；点引导后 HUD 会提示、引导保持待生效，走近后自动生效（不必重新点）
- 修复：读档 / 快速旅行后引导目标偶发「降级再升回」的抖动（候选降级观察期）
- 修复：极少数情况下星图聚焦到「上一次」引导位置的问题（星图改由脚本节拍打开）
- 任务板入口：即便是远处也能给一个大致方位（就近常驻目标），走近后蓝点自动精确落到任务板上
- 内部：发布包不再包含引擎内测试代码（harness）

（v0.1.0 = 首个公开版本。）

---

## 发布检查清单（上传前）

| 项 | 说明 |
| --- | --- |
| 上传包 | `dist\SAQ-ShowAvailableQuests-0.1.12.zip`（由 `tools\package-saq.ps1` 生成；会先以发布构建重编 DLL —— 包里不含任何 harness/测试代码） |
| 测试功能 | 包内**不含任何测试资产**（用例文件 / 结果 JSON），配置强制为「正常玩」的默认值（ini `[Test] Mode=0 / Harness=0`）；发布 DLL 不含 harness 编译 —— 由打包脚本 + `verify_saq_build.py` 三层校验把守 |
| 版本号 | 三处一致：`plugin\xmake.lua`、`plugin\src\main.cpp`、`meta.ini` |
| 依赖声明 | Nexus 上标注 SFSE 为必需依赖（版本 0.2.21+） |
| 权限 | 若允许转载/整合，按 GPL-3.0 说明；建议注明"可自由打包，保留署名" |
| 截图 | 建议 3 张：列表全貌 / 选中条目细节 / 世界中的蓝点或路径线 |
