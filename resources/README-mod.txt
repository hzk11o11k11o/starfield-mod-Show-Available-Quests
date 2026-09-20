================================================================
 Show Available Quests (SFSE)   v{{VERSION}}
 可接任务                        v{{VERSION}}
================================================================

【中文】

一、这是什么
  在原版任务菜单里新增一个「可接任务」标签页：把当前还能接的支线 / 势力 /
  活动 / 事件任务（非主线）集中列出来。选中条目后，可以用游戏原生的引导
  系统（任务目标蓝点 + 扫描仪路径线）导航到接取地点。
  · 已经完成的、以及已在任务日志里的任务会自动隐藏
  · 汇总「无限任务」的接取入口（12 处任务板），点一下就能导航过去
  · 没有导航目标的任务会明确提示（按钮置灰），不会误导
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
  打开任务菜单（TAB）→ 切换到「可接任务」标签页 → 选中一条任务 →
  按引导键（如 SET COURSE）即可导航。再按一次取消引导。
  被引导的任务一旦接取，引导会自动取消。
  列表末尾还有「任务板 · XX」入口条目（无限任务 / 悬赏的接取点），用法相同。
  提示：引导在关闭任务菜单后生效（与原版一致，HUD 蓝点要关菜单才可见）。

五、可选设置（一般无需改动）
  文件：SFSE\Plugins\SAQ_ShowAvailableQuests.ini
  内含测试过滤开关（只显示有目标 / 无目标 / DLC / 任务板入口 ……），默认关闭。

六、已知限制
  · 少量任务（261 条中的 52 条）暂时没有可用的导航目标：界面会如实提示，
    不会假装能引导。
  · 无限生成任务本身不显示，但其接取入口（12 处任务板）会作为独立条目列出；
    无论你在哪都能一键导航过去——远处先给大致方位，走到那块板所在的区域后
    蓝点会自动落到板上（读档/重启后也会自动校正）。
  · 「游戏进度还没到时应当不显示」目前只按「已完成」判断，尚未按任务
    前置条件过滤。
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
  · Pickup points of radiant quests are included: 12 mission boards, one
    click to navigate
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
  select a quest -> press the guidance button (e.g. SET COURSE) to
  navigate. Press again to cancel. Guidance is cancelled automatically
  once you accept the quest.
  The list also ends with "Mission Board - XX" entries (pickup points of
  radiant quests) - same usage.
  Note: guidance applies after you close the mission menu (same as
  vanilla; the HUD marker only appears outside menus).

5. Optional settings
  File: SFSE\Plugins\SAQ_ShowAvailableQuests.ini
  Contains a test filter (only with target / without target / DLC only /
  mission boards only…), off by default.

6. Known limitations
  · 52 of 261 quests currently have no usable navigation target; the UI
    says so honestly instead of pretending.
  · Radiant (infinite) quests themselves are not listed, but their pickup
    points (12 mission boards) are listed as entries; every entry can be
    navigated to from anywhere - far away you get the approximate direction,
    and once you reach the board's area the marker snaps onto the board
    itself (it also self-corrects after a save reload or restart).
  · "Not shown when your progress is not far enough" is currently based
    only on the completed state, not on quest preconditions.
  · This mod overrides Interface\missionmenu.swf and
    missionmenu_lrg.swf: patches are needed if you use another mod that
    modifies the mission menu UI.

7. Log & troubleshooting
  Log: SFSE\Plugins\SAQ_ShowAvailableQuests.log (max 1 MB, auto-rolled)
  When reporting an issue please include the log, install method
  (MO2 / manual), and your game & SFSE versions.

8. License
  GPL-3.0-or-later. Uses SFSE / CommonLibSF.
