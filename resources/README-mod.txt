================================================================
 Show Available Quests (SFSE)   v{{VERSION}}
 可接任务                        v{{VERSION}}
================================================================

【中文】

一、这是什么
  在原版任务菜单里新增一个「可接任务」标签页：把当前还能接的支线 / 势力 /
  活动 / 事件任务（非主线）集中列出来。选中条目后，可以用游戏原生的引导
  系统（任务目标蓝点 + 扫描仪路径线）导航到接取地点。
  · 已经完成的、以及已在任务日志里的任务会自动隐藏（可重复任务例外：做完一次后
    仍会显示，描述里写明怎么再接）
  · 汇总「无限任务」的接取入口（12 处任务板 + 8 位提供可重复任务的 NPC），点一下就能导航过去
  · 没有导航目标的任务会明确提示：条目名前面标注「（不可导航）」，按钮置灰，不会误导
  · 中文 / 英文游戏都支持；自动适配官方 DLC（未安装的 DLC 不会显示其任务）

二、依赖
  · Starfield 1.16.244
  · SFSE (Starfield Script Extender) 0.2.21 或更新 —— sfse_1_16_244.dll
    注意：SFSE 必须与游戏版本匹配。游戏更新后请等 SFSE 更新再玩。

三、安装
  A. MO2（推荐）
     把本压缩包用 MO2 的「从压缩包安装」装进一个新 mod，启用即可；
     确认 SAQ_ShowAvailableQuests.esm 已在 MO2 的插件列表里勾选。
  B. 手动安装
     解压后，把下面这些全部放进 Starfield\Data\ 目录：
       SAQ_ShowAvailableQuests.esm
       SFSE\Plugins\SAQ_ShowAvailableQuests.dll
       SFSE\Plugins\SAQ_ShowAvailableQuests.ini
       Interface\missionmenu.swf
       Interface\missionmenu_lrg.swf
       Scripts\SAQ_Main.pex
     （游戏需已装好 SFSE）

四、使用
  打开任务菜单（TAB）→ 切换到「可接任务」标签页 → 选中一条任务，然后二选一：
    · 展开子项「前往接取地点」（Enter）= 开始引导（HUD 蓝点 + 扫描仪路径线）；
    · 按 SET COURSE（键盘 R / 手柄 X）= 引导 + 自动打开星图并把航线画到接取地点
      （与原版任务按 R 的表现一致；此时会先自动关闭任务菜单）。
  同一条再按一次 R = 保持引导并把星图**再打开一次**（与原版一致：R 只负责「显示目标
  位置」，不会取消追踪）；要**取消**引导，展开条目后选中子项「前往接取地点」再按 Enter。
  被引导的任务一旦接取，引导会自动取消。
  列表末尾集中排列「（可重复）…」条目：任务板入口（无限任务 / 悬赏的接取点）
  与做完一次还能再接的任务本身，名字前都带「（可重复）」标记，用法相同。
  提示：引导在关闭任务菜单后生效（与原版一致，HUD 蓝点要关菜单才可见）。

五、可选设置（一般无需改动）
  文件：SFSE\Plugins\SAQ_ShowAvailableQuests.ini
  内含测试过滤开关（只显示有目标 / 无目标 / DLC / 任务板入口 ……），默认关闭。

六、已知限制
  · 少量任务（278 条中的 54 条）暂时没有可用的导航目标：条目名会标注
    「（不可导航）」，界面如实提示，不会假装能引导。
  · 无限生成任务本身不显示，但其接取入口（12 处任务板 + 8 位可重复任务 NPC）会作为独立条目列出；
    无论你在哪都能一键导航过去——远处先给大致方位，走到那块板所在的区域后
    蓝点会自动落到板上（读档/重启后也会自动校正）。
  · 少数任务的导航目标所在区域要**先靠近才会加载**：远处点引导会先落到附近
    位置（HUD 会提示「目标尚未加载」），走近后自动生效，不必重新点。
  · 「游戏进度还没到时应当不显示」覆盖两类条件：任务记录里「引用别的任务」的
    前置条件（7 条任务 / 11 条条件，含条件组里的「或」逻辑），以及任务对话
    （INFO）里的同类条件（80 条任务 / 415 条对话 / 501 条条件，含官方 DLC，
    例如「大器晚成」要「孤立无援」完成）；另有任务链门槛（后续任务在前置完成前
    不显示）；位置/遭遇类条件暂未覆盖。
  · 本 mod 会覆盖 Interface\missionmenu.swf 与 missionmenu_lrg.swf：
    与其它修改任务菜单 UI 的 mod 同时使用时，需要做补丁（patch）。

七、日志与排错
  日志：SFSE\Plugins\SAQ_ShowAvailableQuests.log（不超过 1 MB，自动滚动）
  反馈问题时请附上：日志、安装方式（MO2 / 手动）、游戏与 SFSE 版本号。

八、许可
  GPL-3.0-or-later。使用了 SFSE / CommonLibSF。

================================================================

【English】

1. What is this
  Adds an "Available Quests" tab to the vanilla mission menu. It lists all
  side / faction / activity / event quests (non-main) that are still
  available to start. Selecting an entry lets you use the game's native
  guidance (quest marker + scanner route line) to navigate to the quest
  giver.
  · Already-completed quests and quests already in your log are hidden
    (repeatable quests are the exception: they stay listed after you finish
    them, and their description tells you how to take them again)
  · Pickup points of radiant quests are included: 12 mission boards plus
    8 repeatable-job NPCs, one click to navigate
  · Quests without a navigation target are clearly flagged (button greyed
    out) instead of silently failing
  · Works with Chinese and English games; official DLC aware (quests from
    DLC you don't own are never listed)

2. Requirements
  · Starfield 1.16.244
  · SFSE (Starfield Script Extender) 0.2.21+ — sfse_1_16_244.dll
    SFSE must match your game version. After a game update, wait for an
    SFSE update before playing.

3. Installation
  A. Mod Organizer 2 (recommended)
     Drag the archive into MO2 ("Install from archive"), enable the mod,
     and make sure SAQ_ShowAvailableQuests.esm is ticked in the plugins
     list.
  B. Manual
     Extract and copy everything below into Starfield\Data\ :
       SAQ_ShowAvailableQuests.esm
       SFSE\Plugins\SAQ_ShowAvailableQuests.dll
       SFSE\Plugins\SAQ_ShowAvailableQuests.ini
       Interface\missionmenu.swf
       Interface\missionmenu_lrg.swf
       Scripts\SAQ_Main.pex
     (SFSE must already be installed.)

4. Usage
  Open the mission menu (TAB) -> switch to the "Available Quests" tab ->
  select a quest, then either:
    - expand the "Go to the pickup location" sub-entry (Enter) to start
      the guidance (HUD marker + scanner route line); or
    - press SET COURSE (R / X) to start the guidance AND open the star map
      with the route plotted to the pickup location (same as a vanilla
      quest does; the mission menu closes automatically first).
  Pressing R again on the same entry keeps the guidance and simply opens
  the star map again (like vanilla: R only shows the target location, it
  never cancels tracking). To CANCEL the guidance, expand the entry,
  select the "Go to the pickup location" sub-entry and press Enter.
  Guidance is cancelled automatically once you accept the quest.
  The list ends with a "(Repeatable)" group: the "Mission Board - XX"
  entries (pickup points of radiant quests) plus the repeatable quests
  themselves - same usage.
  Note: guidance applies after you close the mission menu (same as
  vanilla; the HUD marker only appears outside menus).

5. Optional settings
  File: SFSE\Plugins\SAQ_ShowAvailableQuests.ini
  Contains a test filter (only with target / without target / DLC only /
  mission boards only…), off by default.

6. Known limitations
  · 54 of 278 quests currently have no usable navigation target; the UI
    says so honestly instead of pretending.
  · Radiant (infinite) quests themselves are not listed, but their pickup
    points (12 mission boards + 8 repeatable-job NPCs) are listed as
    entries; every entry can be navigated to from anywhere - far away you
    get the approximate direction, and once you reach the board's area the
    marker snaps onto the board itself (it also self-corrects after a save
    reload or restart).
  · A few quest targets only load once you get near: from afar the guide
    first lands on a nearby spot (the HUD says "target not loaded yet"), and
    it activates automatically once you arrive - no need to press again.
  · "Not shown when your progress is not far enough" covers two layers of
    conditions: record-level preconditions that reference another quest
    (7 quests / 11 conditions, including "or" groups) and the same kind of
    conditions inside a quest's dialogues (INFOs, 80 quests / 415 dialogues
    / 501 conditions, official DLC included, e.g. "A House Divided" needs
    "The Empty Nest" finished), plus a quest-chain gate (a follow-up quest
    stays hidden until its prerequisite is done); location/encounter based
    conditions are not covered yet.
  · This mod overrides Interface\missionmenu.swf and
    missionmenu_lrg.swf: patches are needed if you use another mod that
    modifies the mission menu UI.

7. Log & troubleshooting
  Log: SFSE\Plugins\SAQ_ShowAvailableQuests.log (max 1 MB, auto-rolled)
  When reporting an issue please include the log, install method
  (MO2 / manual), and your game & SFSE versions.

8. License
  GPL-3.0-or-later. Uses SFSE / CommonLibSF.
