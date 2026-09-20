# Nexus 上传素材（v0.1.0）

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
[*] 汇总「无限任务」的接取入口（12 处任务板：新亚特兰蒂斯 / 阿基拉城 / 霓虹城 / 塞多尼亚 / 霍普镇 / 新家园 / 星船厂 / 星钥站……），点一下就能导航过去
[*] 选中即可调用游戏原生引导，导航到接取地点（蓝点 / 路径线）
[*] 已完成的、已在任务日志里的任务自动隐藏
[*] 没有导航目标的任务会明确提示（按钮置灰），不会让你白点
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
任务菜单（TAB）→ 「可接任务」→ 选中条目 → 按引导键（如 SET COURSE）。再按一次取消。

[b]已知限制[/b]
[list]
[*] 261 条任务中有 52 条暂无导航目标：界面会如实提示，不会假装能引导
[*] 无限生成任务本身不显示，但其接取入口（12 处任务板）作为独立条目列出；任何位置都能一键导航过去——在远处先给你一个大致方位，等你走到那块任务板所在的区域，蓝点会自动落到任务板上（不会停在几米外；读档或重启游戏后也会自动校正）
[*] 引导在关闭任务菜单后生效（与原版一致：HUD 蓝点本来就要关菜单才可见）
[*] 「进度没到就不显示」目前只按「已完成」判断，尚未按任务前置条件过滤
[*] 会覆盖任务菜单的 UI 文件（missionmenu.swf / missionmenu_lrg.swf），与其它改任务菜单的 mod 需要打补丁
[/list]

[b]兼容性[/b]
仅使用 SFSE + ESM，不修改任何原版记录（无 dirty edit）。与不触碰任务菜单 UI 的 mod 完全兼容；与修改任务菜单 SWF 的 mod 冲突（需补丁）。

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
[*] Includes the pickup points of radiant quests: 12 mission boards (New Atlantis / Akila City / Neon / Cydonia / Hopetown / New Homestead / staryards / The Key...), one click to navigate
[*] Native guidance: quest marker + scanner route line to the quest giver
[*] Already-completed quests and quests already in your log are hidden
[*] Quests with no navigation target are clearly flagged (button greyed out) — no dead ends
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
Mission menu (TAB) -> "Available Quests" -> select an entry -> press the guidance button (e.g. SET COURSE). Press again to cancel.

[b]Known limitations[/b]
[list]
[*] 52 of 261 quests currently have no navigation target; the UI says so honestly
[*] Radiant quests themselves are not listed, but their pickup points (12 mission boards) are listed as entries; every entry can be navigated to from anywhere — far away you get the approximate direction, and once you reach the board's area the marker automatically snaps onto the board itself (no more stopping a few metres short; it also self-corrects after a save reload or restart)
[*] Guidance applies after you close the mission menu (same as vanilla: the HUD marker only appears outside menus)
[*] "Hidden when your progress isn't far enough" is currently based only on the completed state, not on quest preconditions
[*] Overrides the mission menu UI (missionmenu.swf / missionmenu_lrg.swf): patching needed with other mission-menu mods
[/list]

[b]Compatibility[/b]
SFSE + ESM only — no vanilla records are edited (no dirty edits). Fully compatible with mods that don't touch the mission menu UI; conflicts with mission-menu SWF mods (patch required).

[b]Feedback[/b]
Please include SFSE\Plugins\SAQ_ShowAvailableQuests.log, install method (MO2 / manual), and your game & SFSE versions.
```

---

## 发布检查清单（上传前）

| 项 | 说明 |
| --- | --- |
| 上传包 | `dist\SAQ-ShowAvailableQuests-0.1.0.zip`（由 `tools\package-saq.ps1` 生成） |
| 版本号 | 三处一致：`plugin\xmake.lua`、`plugin\src\main.cpp`、`meta.ini` |
| 依赖声明 | Nexus 上标注 SFSE 为必需依赖（版本 0.2.21+） |
| 权限 | 若允许转载/整合，按 GPL-3.0 说明；建议注明"可自由打包，保留署名" |
| 截图 | 建议 3 张：列表全貌 / 选中条目细节 / 世界中的蓝点或路径线 |
