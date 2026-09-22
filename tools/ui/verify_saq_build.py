#!/usr/bin/env python3
"""verify_saq_build.py - 构建后验证：新代码特征是否真的进了四个产物。

为什么需要：SWF/DLL/PEX 都是二进制，肉眼无法确认「刚改的字符串/函数名在不在里面」。
本脚本按特征串逐个检查（SWF 先解 CWS 的 zlib 压缩），任何一处缺失都会退出码非 0。

检查的特征（随版本演进补充；旧特征缺失代表功能被回退，不要删）：
  第 16 轮：SAQ_GuideReply / SAQ_SyncGuideState / 引导失败文案 / 各类新日志
  第 17 轮：SaqAutoCancelIfAccepted（已接取自动取消引导）/ 多 master 的日志与字段
  第 18 轮：前缀探测（不再读 TESDataHandler::files）/ 新「未加载」文案 / 空推送说明
  第 19 轮：脚本活性探测（DLL 复读通知值 + Papyrus 菜单事件 Trace）/
           引导未生效收尾（结果码 4 回写）/ drop= 被过滤名单 / 报告缓冲 512→2048
  第 20 轮：控制台测试过滤（set SAQ_TestMode to N）——ESM 里的开关 GLOB +
           DLL 的过滤开关与日志（测试模式 / 测试过滤统计）
  第 26 轮：引导确认与菜单状态绑定 —— 菜单开着不判失败（脚本只在关菜单时应用），
           关菜单时重置确认窗口（DLL 两条新文案 + PEX 里菜单事件重挂定时器）
  第 27 轮：无限任务入口（任务板）—— DLL 入口条目表 + 测试模式 5；
           SWF 入口专用文案（前往任务板 / 任务板描述）；
           降噪（菜单开着时不轮询引导确认、停顿行加「有事在等」条件）
  第 28 轮：入口可用性判定（LookupByID）+ 入口专用提示文案
  第 29 轮：11 条任务板引用 override 成**常驻引用**（ESM 的 CellPersistent 组 + flags 0x400，
           任何位置都能导航）；「太远」文案退场（换中性兜底）
  第 30 轮：★ 入口引导目标改成**候选链**（ESM 新建 11 条常驻 XMarker marker +
           同 cell 常驻兜底；DLL 依次 LookupByID 取第一个命中的 + 诊断日志）——
           第 29 轮的 override 路线已被实机 + 数据双重否定（override 不改变引用的加载分类，
           官方 70 条同类 override 的原记录本来就全是常驻）
  第 33 轮：★ ESM 再加 11 条 **CELL 记录**（官方「空壳」写法：只留 EDID + flags 0x4000，
           且与它自己的 CellChildren 组配对出现）—— 官方对同一条 cell（SFBGS003 → 霓虹城）
           就是这么写的；实机 `marker 0` 说明缺它时引擎不并入我们的 CellChildren 组。
           DLL 侧修「静态表只在开菜单时建」（菜单关着时的认领此前三条反查全落空 ⇒
           第 32 轮的自愈形同虚设）
  第 35 轮：★ 进度门槛（「游戏进度还不能让玩家接到 ⇒ 不显示」）——
           DLL 求值/统计/名单文案 + 开关（ini [Filter] ProgressCond）+
           静态表数据侧（StaticCondGate / kQuestCondCount / 被检查任务记录号）
  第 36 轮：SET COURSE（R）尝试走原版 `MissionMenu_PlotToLocation` 流程
           （SWF 的「星图:已请求(代理任务 0x…)」note 是链路证据）
  第 37 轮：★ SET COURSE 的星图真正落地 —— 第 36 轮那条 dispatch 被证明**引擎无 sink**
           （离线复核，见 docs/05 第十一节）；改成「DLL 写 GuideState=5 + 用 UI 消息
           (kHide) 关掉任务菜单 → 脚本在菜单关闭事件里调用引擎原生的
           Game.ShowGalaxyStarMapMenuAndPlotToLocation(地点)」。
           本脚本检查：DLL 的三条星图日志 + 状态 5 文案 + 原生函数名（DLL/PEX）+ PEX 的
           OpenStarMapFor 痕迹
  第 38 轮：★ 修「R 键现象混乱」（玩家实测）——只 kHide 任务菜单会停在**暂停菜单顶层**
           （游戏仍暂停 ⇒ 脚本定时器不走 ⇒ 星图 R 后 4~5 秒才出现）；
           改成界面侧在成功回写后走原版「退回游戏」路径（CloseMenu(true) →
           CloseAllMenus）整个暂停菜单一起关；DLL 用 peek 第四段识别新协议（不发 kHide），
           星图探测改多段窗口（中途记「任务菜单/暂停菜单」状态 + R 后多少秒打开）；
           脚本侧星图目的地加「行星诊断 + 父地点链兜底」。
           本脚本检查：DLL 新协议/等待中/耗时日志 + SWF 关菜单 note + PEX 行星/父地点文案
  第 39 轮：★ R（SET COURSE）**不再取消引导**（玩家实测：已引导的条目再按 R 会
           「取消选中」而不是打开星图）——`SaqToggleGuide` 加第三参数
           （param3 = 是否允许「再按一次 = 取消」的切换语义），R 传 false：
           已引导时退化为「保持引导 + 再请求一次星图」。本脚本检查 SWF 里的
           「重复设定航线」note（R 重复请求的链路证据）
  第 40 轮：星图「开不起来」修调用时机（延时 1.5 秒 + DLL 自动重试 2.5s×3、
           重试时依次换地点候选 5/6/7）+ 引擎「地点 → 星图节点」解析器（0xAC2AB0）
           只读诊断。本脚本检查 DLL 8 条 + PEX 6 条星图文案/API
  第 41 轮：★★ 两个确定性 bug 的修正 —— ① 星图**注册名**是 GalaxyStarMapMenu
           （引擎 ShowGalaxyStarMapMenu* 调 0x253cfa0 拿到的静态 BSFixedString，
           .rdata 0x4C96340）；第 37~40 轮误查菜单名表里的 MapMenu ⇒「星图没打开」
           全是假阴性（星图其实每次都开了）；②「地点 → 星图节点」解析器的函数头
           特征字节抄反（`mov r11,rsp` = `4C 8B DC`，不是 `4C 89 1C 24`）⇒ 运行时
           特征校验永远失败、诊断不可用。本脚本检查：注册名特征 + 修正后的特征字节
           （含反向检查：旧的错误字节不应再出现在 DLL 里）
  第 42 轮：R 键「导航目标不是我悬停的那条」—— 补 press=/sel= 硬证据 + 修两处会改掉
           目的地的缺陷（DLL 重试抢跑 / 脚本星图延时待办不失效）
  第 43 轮：「按 R 没反应」的分诊探针（ev=/btn=）+ 关闭时刻现场读报告 +
           关闭前补一次引导请求轮询 + SET COURSE 不再置灰
  第 44 轮：★★ R 键「星图位置永远是上一个导航的位置」—— 第 36 轮那条原版 dispatch
           在实机日志（18:34~18:35 会话）里被证明确实生效（第 37 轮「无 sink」的结论
           不成立）：它用**代理任务上一次的目标位置**打开星图，而且一打开游戏就暂停
           ⇒ 脚本那条补救调用永远跑不到（三次按 R 全无 Papyrus Trace）。
           修法：删除 dispatch（SWF 只留音效 + 「星图:交给脚本」note）；脚本侧把
           「StartTimer(1.5 s)」换成**轮询节拍**驱动（StarMapPendingTicks →
           ProcessStarMapPending）—— 节拍到点 = 菜单已关、游戏在跑，不会被暂停吃掉；
           DLL 的重试等待从 3 s 收到 1.5 s 与脚本新窗口对齐。
           本脚本检查：SWF 新 note（+ 反向检查：旧 note 不应再出现）+ PEX 节拍待办三件套
           + DLL 两条新文案
  第 45 轮：★★ 引导质量收口（大项 A）—— 引导目标升级为**候选池**（多候选链）：
           ① 数据：gen_guide_targets.py 每条任务输出按质量排序的候选列表（有名字的
              NPC > 可读名落脚点 > 通用名 NPC > 内部名落脚点；同级常驻优先；最多 6+2）；
           ② 表：SAQ_QuestTable.h 生成 kGuideCandidates[] + 每条任务 candBegin/candCount
              （旧的单目标字段 guideRefLocal/guideRefMaster 已移除）；
           ③ DLL：点引导时用 LookupByID 挑「此刻可得的、质量最优的」候选；脚本报状态 2
              （取不到）时自动换下一个候选（循环）；菜单关着时复算（飞近后自动升级回
              有名字的 NPC / 目标失效时回退到可得候选）；认领遍历候选池并记住下标。
           本脚本检查：DLL 5 条新日志 + 静态表候选池完整性（数据侧：切片不越界 /
           209 条有目标 / 旧字段反向检查）
  第 47 轮：★★ 引导可用性收口（大项 C）—— 「同 cell 常驻兜底」候选：
           起因（玩家实测「营救机器人」）：「全部候选都非常驻」的任务（76 条）在目标
           cell 之外点引导时 `LookupByID` 全不可得 ⇒「引导不生效」，而世界里的标记
           仍是上一条生效引导的残留 —— 玩家观感 =「导航点被锁定在某个位置不动、
           导航没用」。
           修法：① 数据：gen_guide_targets.py 新增 find_fallbacks —— 为这类任务在
              **候选目标所在的 cell** 里找最近的**常驻** REFR/ACHR 作为候选池最后一位
              （常驻 ⇒ 任何位置都取得到；本机 56/76 条补到）；② 表：候选总数 875→931；
              ③ DLL：「需要靠近」判据从「全部候选都非常驻」改为「**首选**候选非常驻」
              （兜底是常驻的，不能把这一类判没 —— 描述提示/测试模式 6 清单照旧 76 条）。
           本脚本检查：静态表常驻兜底已并入 + 营救机器人兜底链（0x08ECA5→0x08ECA6）+
           DLL 新判据文案 + 反向检查（旧「全是 非常驻」说法已替换）

  第 53 轮（大项 F · 发布就绪）：DLL 两种构建模式 —— 开发构建（xmake saq_harness=y，
           含 harness）与**发布构建**（saq_harness=n，DLL 里不允许出现任何 harness
           特征；多一条「发布构建提示」正向检查 + 13 项反向检查）。默认按 DLL 内容
           自动探测，`--release` / `--dev` 强制（打包脚本用 --release）。
           另加：MO2 部署副本与工作区**字节一致**（部署未落后 —— 第 50 轮的教训）。
           注：SWF / PEX / ESM 两种模式相同（AS3 测试入口与脚本测试执行器保留 ——
           它们只在 DLL 主动调用/写通道时才起作用，发布版 DLL 已无调用路径；
           见 docs/09 第十一节）。
  第 58 轮（10:31 会话实测的「MoveTo 永不返回」）：harness 驱动器 v58 三件事 ——
           ① 传送后的**落地静默期**（成功回执 ≠ 能立刻走下一步：实测「回执后 38 ms
              又提交一条 MoveTo」会让第二次加载永远不结束 —— Papyrus 日志停在 10:34:37、
              界面停在「加载转圈 + HUD 蓝点」，后面 3 条用例全部陪跑）；
           ② 超时/落地等待时把**此刻打开的菜单**写进日志与证据（LoadingMenu / FaderMenu）；
           ③ 卡死检测：确认卡死 ⇒ 剩余用例 SKIP + 用一条 Ping 冲刷通道。
           本脚本检查：驱动器版本串 v58 + 落地静默期/卡死/菜单证据文案
           + 反向检查（旧的静态提示「确认此刻菜单是关的」与 v57 版本串必须不在）。
  第 59 轮（11:04 会话 r47/r45 两条假 FAIL）：落地静默期与「读到回执那一 Tick」解耦 ——
           `Poll` 是一次性消费，v58 把检查写在 `rc==1` 分支里 ⇒ 回执之后再也跑不到，
           20 秒 deadline 误报「命令没有回执」（实测传送完全正常：回执 4.4/4.9 秒到、
           超时瞬间菜单列表 = 无、Papyrus 两次 `MoveTo` 结果=0）。
           本脚本检查：驱动器版本串 v59 + 落地静默期解耦文案 + 反向检查（v58 及更早不在）。
  第 60 轮（11:26 会话只剩 r45 一条 FAIL，真因 = **用例期望不可达**）：用例 4 旧断言要求
           「走远 ⇒ 当前候选取不到 ⇒ `候选复算：…先保持`」，但引导目标一旦被脚本
           ForceRefTo 到别名上，走远后 `LookupByID` **一直查得到**（11:26 实测：走远
           15 秒里复算按 1.5 秒节拍一直在跑、零日志 = 每次都 `best == 当前`；Papyrus
           `MoveTo` 到赛多尼亚成功、后续用例全 PASS）⇒ 产品行为正确（保持精确目标）。
           本脚本检查：新 op `guide.probe`（候选可得性只读探针）+ 驱动器版本串 v60 +
           用例计划里「探针步骤在、旧『先保持』断言不在」+ 反向检查（v59 及更早不在）。
  第 62 轮（大项 I · 自动读档）：新 op `save.list`（BGSSaveLoadManager 只读诊断：单例 /
           built / count / 前几个存档名 —— 偏移不对会被 shape 校验挡下）+ `save.load
           <存档名子串>`（与游戏「读取存档」菜单同一写侧排队；驱动器等「加载画面消失 +
           静默 2 秒 + 距排队 ≥5 秒 + 命令通道重新就绪」，通道叫不醒就开一次任务菜单
           唤醒脚本 —— 游戏内读档会重建 Papyrus VM，定时器可能没恢复）。
           本脚本检查：驱动器版本串 v61 + 存档列表诊断/读档排队/读档完成/唤醒脚本四条
           文案            + 两个 op 名 + 反向检查（v60 及更早不在）+ 用例计划（r62 用例在、
           **只用用户指定的存档** Save1_FDBB7678M54696D6D6568_000034_20260922142854_2_0_4，
           ★ 第 101 轮切 Exit0（第 103 轮切 Save1）；该子串必须与部署 ini 的
           `[Test] AutoLoad` 一致）。
  第 62 轮补（用户实测反馈 12:21 会话：游戏停在「按任意键继续 / 主菜单」时 harness 一直
           等脚本通道 —— 世界没加载、脚本实例不存在）：**主菜单自动读档** —— ini
           `[Test] AutoLoad`（存档名子串，空 = 关）；驱动器在主菜单阶段用 save.load 的原语
           替玩家读档（每 3 秒重试、最多 10 次；成功/放弃都写日志）。
           本脚本检查：驱动器版本串 + 「主菜单自动读档已排队 / 放弃」两条文案
           + 反向检查（v61 及更早不在）。
  第 62 轮补②（用户实测反馈 12:2x 会话：**自动读档后游戏退回主菜单、随后崩溃**）：
           ① **产品侧**：「任务菜单没开」≠「游戏世界里」—— Tick 的 else 分支此前把
              主菜单 / LoadingMenu / FaderMenu 全当成「菜单关着」，于是读档窗口里跑了
              静态表预建（261 次 LookupByID + TESDataHandler 遍历）+ 认领 + 复算。
              实测（12:31 会话，对照 SAS_AlwaysScan 的菜单事件日志）：12:31:44 静态表
              就绪 + 认领落在 LoadingMenu 开着期间；12:32:05.598 MainMenu 重新打开
              （读档失败退回标题）；12:32:11 引擎崩溃（两次转储现场一致：
              exe+0x1999E57 `mov eax,[rcx+0x20]`、rcx=0、访问 0x20，故障线程 =
              文件 I/O 工作线程）。⇒ 世界未就绪时暂缓例行认领/候选复算（WorldBusyForUpkeep）。
           ② **harness 侧**：排队前等「主菜单稳定」5 秒（引擎在主菜单头十几秒还在初始化）；
              排队后侦测「又回到主菜单且通道未就绪」⇒ WARN（读档失败不再静默）。
           本脚本检查：驱动器版本串 v63 + 「主菜单已稳定 / 自动读档似乎失败了」两条文案
           + 产品侧「例行认领 / 候选复算暂缓」文案 + 反向检查（v62 及更早不在）。
  第 65 轮（任务专属图标）：列表图标与原版任务菜单对齐 ——
           ① 数据：QUST 的 FTYP 关键字 -> 原版 UI 阵营枚举（tools/esm/gen_faction_types.py
              → ref/faction_types.json → StaticQuestInfo.faction，-1 = 无阵营）；
           ② 协议：payload 的 Q 行追加第 7 列「阵营」（DLL 与内嵌回退数据逐列对齐）；
           ③ 界面：条目带**真实** iType + iFaction（SaqSafeFaction 收敛边界），
              原版 MissionsListEntry.SetFactionIcon / MissionInfo 直接消费 ——
              活动/杂项/任务/各势力徽记与原版完全一致（图标 sprite Icons_mc 实测 13 帧，
              含 None，解析见 tools/ui 的 SWF 帧探针）。
           本脚本检查：SWF 的 SaqSafeFaction + stamp=54 + 静态表阵营列完整性
           （表行尾 faction 值域 -1..9 / 有阵营任务数 74 / 样本「深藏不露」=BlackFleet）。
  第 65 轮注：内嵌回退载荷此前缺「需要靠近」列（第 46 轮加的 C++ 列没同步进
           gen_quest_table.py 的内嵌数据）——本轮补齐并逐列对齐，否则阵营列会被
          AS3 当成「需要靠近」读（协议纪律：新列只能追加在最后）。
  第 91 轮（不可导航提示更明显 —— 玩家要求「提示更明显」）：没有引导目标的条目
          （载荷第 5 列 bSaqHasTarget = false）在**列表名前面**加「（不可导航）」——
          此前「不可导航」只有右侧描述（第 23 轮）+ 点击后的提示（第 28 轮），
          长列表里看不出来、点了没反应像 bug。名字前缀是纯显示层改动：
          ① 前缀函数 SaqNotNavigablePrefix（中/英）；
          ② 原名另存 sSaqBaseName，提示/探针改走 SaqBaseName（「该任务暂无导航目标:…」
             报原名，不带前缀）；
          ③ 新探针 `nonav=[<N>|0x<uID>=<显示名>]`（SaqNotNavigableProbe 报 sName =
             MissionsListEntry.SetEntryText 渲染的字段 —— 前缀真的进显示名的运行期证据）。
          本脚本检查：SWF 的 ①/②/③ 六条 + stamp=62 + 反向检查（stamp=61 不残留）；
          用例计划：r75 新增 nonav= 断言 + 提示语仍报原名（两条断言都在）。
  第 96 轮（可重复任务分组 —— 玩家反馈）：「豁免『已完成』过滤的那些条目前面也加上
          （可重复）提示，然后一样把它们排列在一起（就像第 80 轮的『（可重复）NPC』
          入口那样）」——两类改动：
          ① **显示名前缀**（SWF）：SaqRepeatablePrefix（中/英）+ SaqBuildEntry 按
             载荷第 11 列 bSaqRepeatable 给 sName 加前缀（原名仍在 sSaqBaseName）；
          ② **整组排在列表末尾**（C++ + 内嵌载荷）：Decision::PinnedOrderKey 新增
             group 3（可重复任务；入口条目「先追加、后稳定排序」⇒ 落在 group 2 末尾、
             正好接在「（可重复）NPC」入口之后）；gen_quest_table.py::payload_order
             同序（内嵌回退载荷的最后一段就是可重复任务）。
          本脚本检查：SWF 的 ① 三条 + `rq=` 探针（SaqRepeatableQuestProbe：报可重复
          条目的**显示名** = 前缀真的进渲染字段的运行期证据）+ `order=` 的 `|tail=` 段
          （MissionsList.SAQ_OrderProbe 末两行的 uID=显示名 —— 整组排末尾的运行期证据）
          + stamp=63 + 反向检查（stamp=62 不残留）；静态表/载荷侧检查 payload_order 的
          组序（可重复任务在最后）+ 用例计划：r96 新增两条断言。

用法：python tools/ui/verify_saq_build.py [--release|--dev]
"""
from __future__ import annotations

import json
import pathlib
import re
import struct
import sys
import zlib

ROOT = pathlib.Path(__file__).resolve().parents[2]
MO2_MOD = pathlib.Path(r"D:\Mod Organizer 2\starfield_mods\mods\Show Available Quests (SFSE)")


def swf_text_bytes(path: pathlib.Path) -> bytes:
    d = path.read_bytes()
    if d[:3] == b"CWS":
        return zlib.decompress(d[8:])
    if d[:3] == b"FWS":
        return d[8:]
    raise ValueError(f"{path} 不是 SWF（头三字节={d[:3]!r}）")


def check(name: str, blob: bytes, needle: bytes) -> bool:
    ok = needle in blob
    print(("OK  " if ok else "MISS") + f" {name}")
    return ok


REF_SIGS = (b"REFR", b"ACHR", b"PGRE", b"PMIS", b"PARW", b"PBAR", b"PHZD")


def check_esm_markers(path: pathlib.Path, expect_refs: dict[int, str], label: str) -> bool:
    """★ 第 30 轮：expect_refs 里的任务板必须各有一条**新建的常驻 XMarker marker**。

    第 29 轮的 override 路线已被实机 + 数据双重否定（override 只替换记录数据、不改变引用的
    加载分类；官方 70 条同类 override 原记录本来就全是常驻）—— 现在改成本插件空间（记录号
    0x900+i）的**新记录**（tools/esm/create_board_markers.py）：

      * EDID = `SAQ_BoardMarker_<板记录号>`、base = XMarker(0x3B)（无模型、纯位置标记）
      * flags = 0x400、组链 = … > CellChildren > CellPersistent
      * 记录头 FormID 的空间索引 = 本文件 MAST 数量（自身空间；写错会落进别的 master 空间）

    ★ 第 33 轮**再加一条**：每个 marker 所在 cell 还必须有一条 **CELL 记录 override**
    （整条照抄 Starfield.esm）。实机 `marker 0` + 官方先例（6/6 个 cell 都写了 CELL 记录）
    说明引擎只把「本插件也写过该 CELL 记录」的 CellChildren 组并进那个 cell —— 缺它 =
    11 条 marker 全部取不到。这里按组结构解析 + 解压校验 EDID 是否就是那个 cell。

    expect_refs: {板记录号(低 24 位): 该 cell 的 EDID}（EDID 来自 ref/entry_targets.json）
    这是「任何位置都能导航」的**数据侧保证** —— 必须真正按组结构解析
    （顺带做组边界自检：结构被写坏时立刻能看出来）。
    """
    buf = path.read_bytes()
    head_size = struct.unpack_from("<I", buf, 4)[0]
    n_mast = 0
    p, end = 24, 24 + head_size
    while p + 6 <= end:
        sig = buf[p:p + 4]
        ln = struct.unpack_from("<H", buf, p + 4)[0]
        if sig == b"MAST":
            n_mast += 1
        p += 6 + ln

    found: dict[int, tuple] = {}
    cells: dict[int, tuple] = {}
    problems: list[str] = []

    def walk(p: int, end_: int, chain: tuple) -> None:
        while p + 24 <= end_:
            if buf[p:p + 4] == b"GRUP":
                sub = struct.unpack_from("<I", buf, p + 4)[0]
                if sub < 24 or p + sub > end_:
                    problems.append(f"GRUP 越界 @0x{p:X}")
                    return
                gt = struct.unpack_from("<i", buf, p + 12)[0]
                lb = bytes(buf[p + 8:p + 12])
                walk(p + 24, p + sub, chain + ((gt, lb),))
                p += sub
                continue
            size = struct.unpack_from("<I", buf, p + 4)[0]
            flags = struct.unpack_from("<I", buf, p + 8)[0]
            fid = struct.unpack_from("<I", buf, p + 12)[0]
            sig4 = bytes(buf[p:p + 4])
            if sig4 == b"CELL":
                # ★ 第 33 轮：CELL 记录（官方空壳写法 —— 只有 EDID + flags 0x4000，非压缩）
                payload = buf[p + 24:p + 24 + size]
                edid = ""
                subs: list[str] = []
                if not (flags & 0x00040000):
                    q = 0
                    while q + 6 <= len(payload):
                        s = payload[q:q + 4]
                        n = struct.unpack_from("<H", payload, q + 4)[0]
                        subs.append(s.decode("latin1"))
                        if s == b"EDID":
                            edid = payload[q + 6:q + 6 + n].split(b"\x00")[0].decode("latin1")
                        q += 6 + n
                cells[fid & 0xFFFFFF] = (flags, chain, fid, size, edid, subs)
            elif sig4 in REF_SIGS:
                payload = buf[p + 24:p + 24 + size]
                edid = None
                base = None
                q = 0
                while q + 6 <= len(payload):
                    s = payload[q:q + 4]
                    n = struct.unpack_from("<H", payload, q + 4)[0]
                    if s == b"EDID":
                        edid = payload[q + 6:q + 6 + n].split(b"\x00")[0].decode("latin1")
                    if s == b"NAME":
                        base = struct.unpack_from("<I", payload, q + 6)[0]
                    q += 6 + n
                if edid and edid.startswith("SAQ_BoardMarker_"):
                    try:
                        ref_low = int(edid.rsplit("_", 1)[1], 16)
                    except ValueError:
                        ref_low = -1
                    found[ref_low] = (flags, chain, fid, base)
            p += 24 + size

    pos = 24 + head_size
    while pos + 24 <= len(buf):
        if buf[pos:pos + 4] != b"GRUP":
            problems.append(f"顶层 @0x{pos:X} 不是 GRUP")
            break
        gsize = struct.unpack_from("<I", buf, pos + 4)[0]
        if pos + gsize > len(buf):
            problems.append(f"顶层 GRUP @0x{pos:X} size 越界")
            break
        walk(pos + 24, pos + gsize, ())
        pos += gsize

    hit = 0
    cell_hit = 0
    want_cells: dict[int, str] = {}
    for low in sorted(expect_refs):
        got = found.get(low)
        if got is None:
            problems.append(f"0x{low:06X} 没有 SAQ_BoardMarker_ 记录")
            continue
        flags, chain, fid, base = got
        why = []
        if not (flags & 0x400):
            why.append(f"flags=0x{flags:X} 缺 0x400")
        if not chain or [g for g, _ in chain][-4:] != [2, 3, 6, 8]:
            why.append(f"组链={[g for g, _ in chain]}")
        if (fid >> 24) != n_mast:
            why.append(f"空间索引={fid >> 24}≠{n_mast}(MAST 数)")
        if base != 0x3B:
            why.append(f"base=0x{base:08X}≠XMarker(0x3B)")
        if why:
            problems.append(f"0x{low:06X}：" + "；".join(why))
        else:
            hit += 1
        if chain and [g for g, _ in chain][-4:] == [2, 3, 6, 8]:
            want_cells[struct.unpack_from("<i", chain[-2][1])[0] & 0xFFFFFF] = expect_refs[low]

    for cell_low in sorted(want_cells):
        c = cells.get(cell_low)
        want_edid = want_cells[cell_low]
        if c is None:
            problems.append(f"cell 0x{cell_low:06X} 没有 CELL 记录"
                            f"（第 33 轮：缺它 = 引擎不会并入我们的 CellChildren 组）")
            continue
        cflags, cchain, cfid, csize, cedid, csubs = c
        why = []
        if (cfid >> 24) != 0:
            why.append(f"不是 override（空间索引={cfid >> 24}，应 0）")
        if [g for g, _ in cchain][-2:] != [2, 3]:
            why.append(f"组链={[g for g, _ in cchain]}")
        if not (cflags & 0x00004000):
            why.append(f"flags=0x{cflags:X} 缺 0x4000（官方空壳标记）")
        if cflags & 0x00040000:
            why.append("是压缩记录（空壳应非压缩）")
        if csubs != ["EDID"]:
            why.append(f"子记录={csubs}≠['EDID']（空壳不许写数据字段，否则会覆盖 cell 数据）")
        if cedid != want_edid:
            why.append(f"EDID={cedid!r}≠{want_edid!r}")
        if why:
            problems.append(f"cell 0x{cell_low:06X} 的 CELL 空壳：" + "；".join(why))
        else:
            cell_hit += 1

    ok = hit == len(expect_refs) and cell_hit == len(want_cells) and not problems
    print(("OK  " if ok else "MISS") +
          f" ESM({label}) · 新建常驻 marker {hit}/{len(expect_refs)} 条"
          f"（XMarker + CellPersistent + 0x400）+ CELL 空壳 {cell_hit}/{len(want_cells)} 条"
          f"（EDID + 0x4000，不覆盖 cell 数据）")
    for p_ in problems:
        print(f"       - {p_}")
    return ok


TEST_GLOBS = (
    (0x806, "SAQ_TestSeq"),
    (0x807, "SAQ_TestCmd"),
    (0x808, "SAQ_TestArgA"),
    (0x809, "SAQ_TestArgB"),
    (0x80A, "SAQ_TestArgC"),
    (0x80B, "SAQ_TestAck"),
    (0x80C, "SAQ_TestResult"),
    (0x80D, "SAQ_TestHarness"),
)


# ★★ 第 53 轮（大项 F · 发布就绪）：开发构建（SAQ_WITH_HARNESS=1）里必须有的 harness 特征串。
#   发布构建（xmake f --saq_harness=n）里**这些一条都不该出现** —— 同一张表反向用：
#   · 开发模式：逐条必须命中（缺 = 功能被回退）；
#   · 发布模式：逐条必须不见（出现 = 「发布包」里带着测试代码/能力）。
HARNESS_STRINGS = (
    ("harness 用例载入", "harness：用例文件已载入"),
    ("harness 通道就绪", "harness：通道就绪"),
    ("harness 结果落盘", "harness：结果已写入"),
    ("harness 未启用文案", "引擎内自动化测试关闭"),
    ("harness 状态行", "harness="),
    ("命令通道自检", "测试命令通道 GLOB"),
    ("通道垃圾读数拒写", "拒绝写内存"),
    ("脚本未就绪判定", "SAQ_TestHarness"),
    ("界面测试驱动入口", "SAQ_TestDriveSelect"),
    # ★★ 第 54 轮：harness 的三件新原语（历史判据落成用例时必须有的能力）——
    #   ① 反向日志断言（第 26/44/49 轮的「不该再出现」类判据）；
    #   ② 关掉任意菜单（星图也是暂停菜单，用例收尾必须能关掉它）；
    #   ③ 传送到任务板（用例要「站远 / 走近」触发候选复算）。
    ("反向日志断言", "assert.nolog"),
    ("任意菜单关闭", "menu.hide"),
    ("传送到任务板", "teleport.entry"),
    ("界面测试驱动-子项", "SAQ_TestDriveSelectChild"),
    ("菜单 kShow 开关", "已请求打开任务菜单"),
    # ★ 第 55 轮：用例收尾清场从「全部用例结束一次」改成**每条用例结束**都做
    #   （09:06 会话：smoke 失败中止 ⇒ 星图留屏 ⇒ 后续 5 条用例的 ping 全被冻死）。
    ("harness 用例收尾清菜单", "harness：用例收尾：任务菜单还开着"),
    ("harness 用例收尾清星图", "harness：用例收尾：星图还开着"),
    ("失败带 SWF 指纹", "SWF 指纹"),
    ("旧版 SWF 判定文案", "游戏加载的还是旧版 SWF"),
    # ★★ 第 56 轮（09:22 会话实测出的两个**驱动器**缺陷，都不在产品侧）——
    #   两条都只存在于 SAQ_Test*.cpp ⇒ 发布构建里必须一条都不见（同一张表反向检查）：
    #   ① 日志窗口起点曾被 `CompleteStep` 随 StepState 一起清 0 ⇒ 所有 `scope=prev`
    #      断言退化成「整个环形缓冲」（假 PASS：匹配本会话最早那几行；r48 的假 FAIL
    #      报文「窗口从 idx 0 起」也是它）。用**驱动器版本串**做判据 —— 与 SWF 的
    #      `stamp=` 同一个道理：日志里有没有这一串，是「跑的是不是修好的那版」的唯一判据。
    #   ② 传送（MoveTo）的回执要等 cell 加载（实测 4.3 秒）⇒ 传送单独给 20 秒窗口，
    #      否则「传送成功」会被判 FAIL（本例最危险的一类：假 FAIL 掩盖了用例前提已成立）。
    # ★★ 第 57 轮（09:35 会话实测出的两个**驱动器**缺陷 + 一条清场时序）——
    #   ① `ui.select/selectchild/expand` 的 `~0x…` 参数漏写回 `formId` ⇒ 被当成
    #      记录号 0x000000（r45 的 `ui.selectchild ~0x0008EBDC` 假 FAIL）；
    #   ② R 链路的星图由脚本在菜单关闭后 1~1.5 秒才打开 ⇒ 清场当时查不到它，
    #      它会落在下一条用例开头（游戏暂停 ⇒ 脚本冻结 ⇒ `ping` 超时，r26 实证）。
    #      修法 = 「按过 R 的用例」结束后开 **4 秒延迟复查窗口**（观察到就关、提前结束）。
    # ★★ 第 58 轮（10:31 会话实测的「MoveTo 永不返回」—— 游戏端卡在加载画面，
    #   三条用例陪跑；本轮修的是**驱动器**的时序与诊断）：
    #   ① 传送成功（回执）≠ 立刻能走下一步 ⇒ 加**落地静默期**（加载画面消失 + 连续
    #      静默 1.5 秒 + 距回执 ≥3.5 秒）—— 实测「回执后 38 ms 又提交一条 MoveTo」
    #      会让第二次加载**永远不结束**（Papyrus 日志停在 10:34:37、界面停在
    #      「加载转圈 + HUD 蓝点」）。
    #   ② 超时/落地等待时把**此刻打开的菜单**写进日志与证据（LoadingMenu/FaderMenu
    #      开着 = 卡在加载画面）—— 旧文案只有一句静态猜测，事后无法定性。
    #   ③ 卡死检测：确认卡死 ⇒ 剩余用例 SKIP + 用一条 Ping 冲刷通道（防游戏恢复后
    #      执行那条排队的传送）。
    # ★★ 第 59 轮（11:04 会话 r47/r45 两条假 FAIL —— 落地静默期被绑死在「读到回执那一
    #   Tick」：`Poll` 是一次性消费，之后再也检查不到「加载画面已关」，20 秒 deadline
    #   一到就误报「命令没有回执」；实测回执 4.4/4.9 秒就到、超时瞬间菜单列表 = 无、
    #   Papyrus 侧两次 `MoveTo` 都 `结果=0`）：
    #   ① 静默期检查改为**每 Tick**推进（回执只登记时刻 + 文案）；
    #   ② deadline 只管「等回执」阶段（回执到了立即失效）；
    #   ③ 静默期完成时把证据写进步骤结果（回执后 ms + 加载画面已关 ms）。
    # ★★ 第 60 轮（11:26 会话 r45 的「先保持」断言不可达 —— 见文件头）：新 op `guide.probe`
    #   （候选可得性只读探针：与产品候选复算同一套查询，结果进步骤 JSON，事后可对账）。
    # ★★ 第 62 轮（大项 I）：自动读档 —— 新 op `save.list`（BGSSaveLoadManager 只读诊断）
    #   与 `save.load`（排队读档 → 加载静默期 → 通道重新就绪 → 叫不醒就开菜单唤醒脚本）。
    # ★★ 第 66 轮（14:35 会话 r44 的唯一 FAIL = **驱动器窗口太紧**，产品全对）：
    #   命令回执窗口 3000 → 8000 + ping 用满窗口（此前被 kDefaultStepTimeoutMs 5000
    #   封顶）+ 回执 ≥2000 ms 留一行 note。实测依据：脚本执行了 seq=17 的 Ping
    #   （Papyrus `测试命令：seq=17 op=1 结果=0`）但晚了约 3.4 秒；超时瞬间 DLL
    #   诊断「此刻打开的菜单：无」（不是加载画面）；紧接着的下一条用例 ping 只用 47 ms。
    # ★★ 第 69 轮（15:43 会话复查：r65_icons 的 `step = ui.state` 是未知步骤，
    #   老驱动器只留 WARN + 丢步 ⇒ 用例照样 PASS —— 「少测一步」看不出来）：
    #   解析失败 ⇒ 该用例直接判 FAIL（证据进结果 JSON 的 parse 步骤）。
    # ★★ 第 83 轮（22:52 会话：22 条用例 19 PASS / 3 FAIL，**三条 FAIL 全在用例/驱动器
    #   侧、产品全对** —— 判据见下）：
    #   ① `r80_repeatable_npc`：断言把产品日志里的**全角** `）` 写成半角转义 `\)`
    #      ⇒ 正则合法但永不匹配（与第 68 轮 `\\d` 同一类病；症状是「日志里没出现 /…/」）。
    #      顺带把这条断言的窗口从 `scope=prev` 改成 `scope=case`（该行由 menu.open 同一次
    #      Tick 的产品处理打印，窗口基准在个别时序下会落在它之后）。
    #   ② `r81_landmark`：第二次 `menu.open` 之后立刻 `ui.tab` —— 那一两拍 DLL 还没解析出
    #      Movie/ASMovieRoot（产品侧同一次 Tick 的首次推送同样失败、约 0.8 秒后重试成功）
    #      ⇒ 「桥没通」。修法：驱动器 v70 在步骤超时内重试 + 用例补「等推送成功再切 tab」。
    #   ③ `r62_reload_observe` 的首步 `ping` 超时：r81 中止后清场复查先关掉残留的**任务
    #      菜单**就提前结束了延迟复查窗口 ⇒ 约 1 秒后由脚本节拍打开的星图没人管
    #      （星图 = 暂停菜单 ⇒ 脚本定时器冻结 ⇒ ping 无回执）。修法：只有**真的看到并
    #      关掉星图**才提前结束窗口；关掉星图后再留一段（kInterCaseDelayMs）才开下一条。
    ("harness 驱动器版本串",
     "驱动器 v70：`ui.*` 遇到「桥没通」在步骤超时内自动重试"),
    ("harness ui 桥没通重试文案", "桥没通 —— 等界面桥就绪后重试"),
    ("harness 清场延迟复查窗口开启文案", "延迟复查窗口开启"),
    ("harness 清场时星图已开（短窗口）文案", "星图已在清场时关掉，只等关闭生效"),
    ("harness 断言超时三打点文案", "；本步起点 idx="),
    ("harness 用例解析失败文案", "用例文件解析失败（修复用例文件后重跑）"),
    # ★★ 第 68 轮（15:24 会话 r67_chain 的唯一 FAIL = **用例自己的正则写错**，产品全对）：
    #   断言正则此前只会在运行期由 `LogFind` 静默编译失败 ⇒ 报文退化成
    #   「日志里没出现 /…/」（「产品没打这行」与「正则写错」两种情况混在一起）。
    #   现在驱动器在**解析期**就编译校验 + 运行期立刻失败（见 SAQ_Test.cpp 的 Step::regexOk）。
    ("harness 断言正则非法文案", "正则非法（ECMAScript 编译失败）"),
    ("harness 慢回执留痕文案", "命令回执偏慢："),
    ("harness 主菜单自动读档文案", "主菜单自动读档已排队"),
    ("harness 主菜单自动读档放弃文案", "主菜单自动读档放弃"),
    # ★★ 第 62 轮补②（12:2x 会话实测：自动读档后游戏退回主菜单 + 跳出）：
    #   ① 排队前等「主菜单稳定」（kAutoLoadMinMenuAgeMs）；
    #   ② 排队后的失败侦测（读档窗口结束后又回主菜单 ⇒ WARN，不再静默）。
    ("harness 自动读档稳定门槛文案", "主菜单已稳定"),
    ("harness 自动读档失败侦测文案", "自动读档似乎失败了"),
    ("harness 候选可得性探针文案", "候选可得性："),
    ("harness 探针 op 名", "guide.probe"),
    ("harness 存档列表诊断文案", "单例=OK built="),
    ("harness 读档排队文案", "已排队读档："),
    ("harness 读档完成文案", "读档完成（排队后"),
    ("harness 读档唤醒脚本文案", "唤醒脚本（第"),
    ("harness 读档 op 名", "save.load"),
    ("harness 存档列表 op 名", "save.list"),
    ("harness 落地静默期解耦文案", "落地静默期完成（回执后"),
    ("harness 传送落地静默期文案", "传送落地中（回执已到，但加载画面还没关"),
    ("harness 传送落地超限判定", "疑似卡在加载画面"),
    ("harness 卡死自动中止文案", "游戏端疑似卡死"),
    ("harness 命令超时菜单证据", "此刻打开的菜单"),
    ("harness 清场延迟复查文案", "用例收尾复查：星图在清场后才打开"),
    ("传送回执等待窗口文案", "传送等回执最多"),
    # ★★ 第 101 轮补丁（2026-09-22 20:41 会话实测 FAIL 的定调用）：**只读探针**
    #   `quest.probe` —— 用与链式 / 进度门槛**同一个**引擎函数直读 IsStageDone，
    #   区分「写侧没生效」与「读侧读不到」（同类先例：第 99 轮 MQ01@10000）。
    #   实现只在开发构建里（SAQ_QuestCond.cpp 的 #if SAQ_WITH_HARNESS 内 +
    #   SAQ_Test.cpp 的 op 名）⇒ 发布 DLL 必须一条都不见（本表反向检查覆盖）。
    ("harness 引擎直读探针 op 名", "quest.probe"),
    ("harness 引擎直读探针文案", "quest.probe 0x"),
    # ★★★ 第 104 轮（2026-09-22 22:40 会话 r98 B 段唯一 FAIL 的定调用）：探针结果
    #   必须**同时打一行产品日志**（`任务探针 quest.probe 0x…`）—— `assert.log` 只认
    #   产品行（`LogFind` 跳过一切含 `harness：` 的行 = 第 56 轮防回声红线），probe
    #   输出若只出现在 `[PASS] quest.probe …` 这条 harness 步骤行里，任何 probe 断言
    #   都必然假 FAIL（症状：步骤 PASS、断言「日志里没出现」+ evidence 为空）。
    #   ⇒ 这条特征串钉住「探针结果会打一行产品日志」不被回退。
    #   ★ 实现细节：产品行是 `REX::INFO("任务探针 {}", probe)` —— 二进制里
    #     `任务探针 {}`（本条）与 `quest.probe 0x…`（上一条）是**两段独立字面量**，
    #     拼不出 `任务探针 quest.probe 0x` 这样的连续串（第一版写错成那个，MISS 过）。
    #     两条必须**成对**在：上一条管「探针输出格式」，本条管「结果会进产品日志」。
    ("harness 探针产品行（可被 assert.log 取证）", "任务探针 {}"),
)


def dll_build_mode(blob: bytes) -> str:
    """探测 DLL 是开发构建（含 harness）还是发布构建（无 harness）。

    判据用「harness：通道就绪」——这条只在 SAQ_Test.cpp 里，发布构建（saq_harness=n）
    整个翻译单元都不参与编译。`--release` / `--dev` 可强制覆盖（发布校验用强制，
    免得「构建没切过去」时 auto 探测把带 harness 的 DLL 当成发布版放行 —— 那是最危险的失败模式）。
    """
    return "dev" if "harness：通道就绪".encode() in blob else "release"


def check_esm_test_globs(path: pathlib.Path, label: str, require_zero: bool) -> bool:
    """★ 第 49 轮：引擎内 harness 的**测试命令通道 GLOB**（0x806~0x80D，共 8 条）。

    为什么在构建校验里查它：这套通道是「DLL 写命令 → Papyrus 执行 → 脚本回执」的唯一
    落点（写侧动作必须走 Papyrus 语言级 API，见 docs/04 的调用约定结论）。缺一条，
    harness 就会静默失效（脚本取不到 GLOB 就整个关闭）——正是最该在构建期挡住的那类问题。

    只查三样：记录号 → EDID 对得上、初值 0（工作区副本）、HEDR nextObjectID 已经提上去。
    **不查**已有记录号（0x801~0x805）：它们必须原地不动（存档按 FormID 记录脚本实例）。
    """
    buf = path.read_bytes()
    head_size = struct.unpack_from("<I", buf, 4)[0]

    # HEDR：numRecords / nextObjectID（追加记录必须同步，否则 xEdit 重存会重编号）
    next_id = None
    p, end = 24, 24 + head_size
    while p + 6 <= end:
        sig = buf[p:p + 4]
        n = struct.unpack_from("<H", buf, p + 4)[0]
        if sig == b"HEDR" and n >= 12:
            next_id = struct.unpack_from("<I", buf, p + 6 + 8)[0]
            break
        p += 6 + n

    found: dict[int, tuple[str, float | None]] = {}
    pos = 24 + head_size
    while pos + 24 <= len(buf):
        if buf[pos:pos + 4] != b"GRUP":
            break
        gsize = struct.unpack_from("<I", buf, pos + 4)[0]
        if gsize < 24 or pos + gsize > len(buf):
            break
        if bytes(buf[pos + 8:pos + 12]) == b"GLOB":
            q = pos + 24
            while q + 24 <= pos + gsize:
                if buf[q:q + 4] == b"GRUP":
                    break
                size = struct.unpack_from("<I", buf, q + 4)[0]
                fid = struct.unpack_from("<I", buf, q + 12)[0]
                payload = buf[q + 24:q + 24 + size]
                edid, value = "", None
                r = 0
                while r + 6 <= len(payload):
                    s = payload[r:r + 4]
                    m = struct.unpack_from("<H", payload, r + 4)[0]
                    if s == b"EDID":
                        edid = payload[r + 6:r + 6 + m].split(b"\x00")[0].decode("latin1")
                    elif s == b"FLTV" and m == 4:
                        value = struct.unpack_from("<f", payload, r + 6)[0]
                    r += 6 + m
                found[fid & 0xFFFFFF] = (edid, value)
                q += 24 + size
        pos += gsize

    problems: list[str] = []
    hit = 0
    for low, edid in TEST_GLOBS:
        if low not in found:
            problems.append(f"缺记录 0x{low:03X}（{edid}）")
            continue
        hit += 1
        got_edid, got_val = found[low]
        if got_edid != edid:
            problems.append(f"0x{low:03X} 的 EDID 是 {got_edid!r}，期望 {edid!r}")
        elif require_zero and got_val != 0.0:
            problems.append(f"0x{low:03X} 的初值是 {got_val}，期望 0")
    if next_id is not None and next_id < 0x80E:
        problems.append(f"HEDR nextObjectID=0x{next_id:X}，应 >= 0x80E（追加 8 条记录后没同步）")

    ok = not problems
    print(("OK  " if ok else "MISS") +
          f" ESM({label}) · 测试命令通道 GLOB {hit}/{len(TEST_GLOBS)} 条"
          f"（0x806~0x80D，追加不占用旧记录号）")
    for p_ in problems:
        print(f"       - {p_}")
    return ok


def main() -> int:
    # ★ 第 53 轮（大项 F · 发布就绪）：构建模式 ——
    #   `--release` 强制按**发布构建**校验（package-saq.ps1 用：即使 xmake 配置没切过去，
    #     也会因为「DLL 里还有 harness 字符串」直接失败，挡住「带着测试代码打包」）；
    #   `--dev` 强制开发构建；默认按 DLL 内容自动探测。
    force_release = "--release" in sys.argv[1:]
    force_dev = "--dev" in sys.argv[1:]
    if force_release and force_dev:
        print("参数互斥：只能给 --release 或 --dev 之一")
        return 2
    all_ok = True

    swf_checks = {
        "SAQ_GuideReply 函数名": b"SAQ_GuideReply",
        "SAQ_SyncGuideState 函数名": b"SAQ_SyncGuideState",
        "无引导目标文案": "该任务暂无引导目标".encode(),
        "通道失败文案": "引导通道写入失败".encode(),
        # 第 17 轮：被引导的任务一旦被玩家接取，界面自己发一条取消请求
        "已接取自动取消引导": "已接取，自动取消引导".encode(),
        # 第 19 轮：确认超时/脚本未响应时的界面回滚文案 + 被过滤名单（drop=）
        "引导未生效文案": "引导未生效:脚本未响应".encode(),
        "被过滤名单 drop=": b" drop[",
        # 第 23 轮：无导航目标的条目在界面上「看得见」（描述 + 点击拦截 + 按钮置灰）
        "无导航目标描述": "还没有导航目标".encode(),
        "点击拦截提示": "该任务暂无导航目标".encode(),
        # 第 27 轮：无限任务入口（任务板）—— 子项名与描述用专门文案
        "入口子项名(中)": "前往任务板".encode(),
        "入口子项名(英)": b"Go to the mission board",
        "入口描述(中)": "这是一块任务板".encode(),
        "入口描述(英)": b"This is a mission board",
        # 第 28 轮：入口「引用取不到」的如实提示（与任务的「没有导航目标」分开）
        # ★ 第 29 轮：引用已常驻化（任何位置都取得到）⇒ 文案不再提「太远」，改中性兜底
        "入口不可用描述(中)": "这个位置此刻取不到".encode(),
        "入口不可用描述(英)": b"the location is not available at the moment",
        "入口不可用提示": "暂时无法导航:".encode(),
        # ★★ 第 44 轮：SET COURSE 的星图改由 Papyrus 打开 —— 第 36 轮那条原版
        #   dispatch 已**删除**。它在实机日志里被证明确实生效（第 37 轮的「无 sink」
        #   结论不成立），但用的是代理任务**上一次**的目标位置 ⇒ 星图位置永远滞后
        #   一条；而且它先把星图打开（暂停 ⇒ 脚本定时器冻结）⇒ 补救调用永远跑不到。
        #   现在只留音效 + 这行 note（「已交给脚本」的链路证据）。
        "星图交给脚本 note": "星图:交给脚本(菜单关闭后)".encode(),
        # ★ 第 37 轮：报告里的星图标记（R = 1 / Enter = 0），与 peek 第三段同源
        "星图标记(map=)": b" map=",
        # ★ 第 38 轮：界面侧会在回写成功后关掉整个暂停菜单（CloseMenu(true) 路径），
        #   这行 note 是「新协议第四段」的链路证据。
        "星图关菜单 note": "星图:菜单已交界面关闭".encode(),
        # ★ 第 39 轮：R 在「已引导」的条目上重复按下时不取消引导，只再请求一次星图
        #   （note 进报告/日志，与「已设为引导」区分）。
        "R 重复请求 note": "重复设定航线:".encode(),
        # ★★ 第 42 轮：R 键「导航目标不是我悬停的那条」的定性证据 ——
        #   报告里新增 press=[…]（按键那一刻界面用的是哪一行）与 sel=[…]（列表选中项）。
        #   这两个字段是「界面到底选了哪条」的唯一硬证据（C++ 侧抄进引导请求日志）。
        "按键行 press=[": b" press=[",
        "选中行 sel=[": b" sel=[",
        "R 按键行标记": b"R@",
        "Enter 按键行标记": b"E@",
        # ★★ 第 43 轮：「按 R 没反应」的分诊探针（第 42 轮遗留问题：press 无记录时，
        #   「按键没进界面」与「事件到了但按钮被禁用」两种病分不开）——
        #   ev=[…] = 最近收到的 user event（事件名 + ↓按下/↑松开）；
        #   btn=[…] = 选中项变化那一刻的按钮状态（our/std:plot=1/0:map=1/0）；
        #   另外本轮取消了 SET COURSE 的「置灰」（沉默失败 → 改回点击给提示）。
        "按键事件探针 ev=[": b" ev=[",
        "按钮状态探针 btn=[": b" btn=[",
        "事件探针函数": b"SaqNoteUserEvent",
        "按钮状态字段": b"SaqLastBtnNote",
        # ★★ 第 49 轮（引擎内 harness）：界面的测试驱动入口 —— 只有 DLL 会调，
        #   内部**调用真实的处理函数**（ProcessUserEvent / onEntryPress / ScrollingEvent），
        #   于是「造状态 → 开关菜单 → 选中 → 按键 → 断言」可以全自动跑。
        "测试入口-选中": b"SAQ_TestDriveSelect",
        # ★★ 第 54 轮：**子项**选中入口（`ui.selectchild`）—— 主标题的 Enter 只展开（与原版
        #   一致），「只引导、不开星图」那条链只有子项上的 Enter 才走（第 26 轮判据要用它）。
        #   配套：MissionsList 的 `SAQ_FindChildIndexByUID`（子项 uID 与父项相同 ⇒ 不能按 uID 找）。
        "测试入口-选中子项": b"SAQ_TestDriveSelectChild",
        "列表按uID找子项": b"SAQ_FindChildIndexByUID",
        "测试入口-按键": b"SAQ_TestDriveKey",
        "测试入口-切 tab": b"SAQ_TestDriveTab",
        "测试入口-状态": b"SAQ_TestDriveState",
        # ★★ 第 52 轮：`ui.tab` 修「向只读属性 selectedIndex 写入」——
        #   真因 `Error #1074: Illegal write to read-only property`（BSTabbedSelection
        #   的 selectedIndex 只有 getter）。新逻辑改走原版 public 入口
        #   `MissionTabbedSelection.SetSelectedCategoryIndex`，并新增拒绝码
        #   `tab-refused`（SetSelectedIndex 静默不生效时不再装作成功）。
        #   两个片段都只在第 52 轮的代码里出现（SetSelectedCategoryIndex 这个 multiname
        #   原版就有，单查它证明不了什么；tab-refused 是新增的）。
        "测试入口-切tab拒绝码": b"tab-refused",
        "列表按 uID 找行": b"SAQ_FindEntryIndexByUID",
        # ★★ 第 50 轮：SWF 构建指纹（进 SAQ_Report 的输出）—— 诊断「游戏加载的是
        #   哪一版 SWF」。起因：第 49 轮补丁③ 的产物经字节码级验证（FFDec P-code）
        #   确认无误，而 22:48 会话 ui.tab 仍 0 ms 失败 ⇒ 证据指向「游戏加载的仍是
        #   部署前的旧 SWF」（Starfield 的 UI 资源在**游戏启动阶段**加载，早于 SFSE
        #   插件加载日志的时刻）。日志里 SAQ_Report 带 `stamp=NN` = 本次构建的新版；
        #   没有该字段 = 旧版 ⇒ 完全重启游戏后再测。
        "SWF 构建指纹 stamp=": b"stamp=",
        # ★★ 第 46 轮（大项 B）：引导可用性 + 提示收口 ——
        #   ① 描述里**提前**告知「目标要靠近才加载」（载荷第 6 列 bSaqNeedsApproach）；
        #   ② 结果码 5 = 已排定但目标尚未加载（保持竖条、不回滚、不关菜单）。
        "需要靠近描述(中)": "它的导航目标要靠近目标区域后才加载".encode(),
        "需要靠近描述(英)": b"its navigation target loads only when you are near its area",
        "需要靠近函数": b"SaqApproachNote",
        "载荷第 6 列": b"bSaqNeedsApproach",
        "目标未加载 note": "目标尚未加载:靠近后自动生效".encode(),
        # ★ 第 48 轮：诊断标签的 NaN 兜底 —— 子项（「前往接取地点」）没有 uID，
        #   旧写法会打出「0xNaN@…」，新写法给「「名字」(子项)」。
        "子项标签": "(子项)".encode(),
        # ★★ 第 65 轮（任务专属图标）：阵营列的边界收敛函数（NaN / 越界 -> -1）——
        #   这个名字只可能来自本轮新代码（SaqParsePayload 解析第 7 列 +
        #   SaqBuildEntry 用真实 iType/iFaction 喂原版 SetFactionIcon）。
        "阵营边界函数 SaqSafeFaction": b"SaqSafeFaction",
        # ★★ 第 65 轮：构建指纹 ——**以后每改一次 SWF 都要 +1 并同步这里**。
        #   ★★ 第 74 轮（同伴好感度任务）：stamp 54 → 55（载荷加第 8 列 + 描述提示）
        #     → 56（同轮续：`order=` 顺序探针 —— 同伴任务分组）。
        #   ★★ 第 75 轮（四大势力开头任务）：stamp 57 —— 载荷加第 9/10 列（简要说明）+
        #     描述第一句改用说明 + 新增 `pin=` 探针（说明真的进了描述）。
        #   ★★ 第 80 轮（可重复 NPC 入口）：stamp 58 —— type 101 条目文案
        #     （子项「与他交谈（可重复任务）」+ 可重复任务描述）+ `rep=` 探针。
        #   ★★ 第 81 轮（地球地标任务）：stamp 59 —— **AS3 代码本身没改**，改的是
        #     内嵌回退载荷（+10 条地标任务 + 其说明文本）⇒ 重编译 SWF 让内嵌数据
        #     与 C++ 载荷重新逐条对齐（协议纪律：先改 SWF 必须留下指纹）。
        #   ★★ 第 82 轮（同伴文案说透）：stamp 60 —— 同伴条目描述首句 + 尾部落点文案
        #     改写（「自动开始 / 不需要找地方接取 / 引导到的是这位同伴的位置」）。
        #   ★★ 第 89 轮（可重复任务）：stamp 61 —— 载荷加第 11 列（可重复标记）
        #     + FilterKnownQuests 对「已完成 + 可重复」放行 + `rptk=` 探针。
        #   ★★ 第 91 轮（不可导航提示更明显）：stamp 62 —— 不可导航条目的显示名加
        #     「（不可导航）」前缀（SaqNotNavigablePrefix）+ 提示/探针改报原名
        #     （SaqBaseName / sSaqBaseName）+ `nonav=` 探针。
        #   ★★ 第 96 轮（可重复任务分组 —— 玩家反馈）：stamp 63 —— 可重复任务
        #     （载荷第 11 列 bSaqRepeatable）的显示名加「（可重复）」前缀
        #     （SaqRepeatablePrefix）+ `rq=` 探针（显示名证据）+ `order=` 的
        #     `|tail=` 段（末两行 —— 整组排列表末尾的运行期证据）。
        "构建指纹 stamp=63": b"stamp=63",
        # ★★ 第 80 轮（可重复 NPC 入口）：type 101 的界面链路 ——
        #   ① 常量与合并判据（SaqIsEntryType —— 子项/描述/不可导航提示统一用它）；
        #   ② 子项名与描述文案（中英各一段，证明不是只改了判据没接文案）；
        #   ③ `rep=` 探针（可重复 NPC 条目的运行期证据，见 SaqRepeatNpcProbe）。
        "可重复NPC类型常量": b"SAQ_REPEAT_NPC_TYPE",
        "入口类型合并判据": b"SaqIsEntryType",
        "可重复NPC子项名(中)": "与他交谈（可重复任务）".encode(),
        "可重复NPC子项名(英)": b"Talk to them (repeatable job)",
        "可重复NPC描述(中)": "这位 NPC 会不断提供可重复任务".encode(),
        "可重复NPC描述(英)": b"This NPC offers repeatable jobs",
        "可重复NPC报告探针": b"SaqRepeatNpcProbe",
        "可重复NPC报告字段": b"rep=[",
        # ★★ 第 74 轮（同伴好感度任务）：「入口」同伴任务固定显示 + 描述提示 + 名字前缀。
        #   ① 载荷第 8 列（bSaqCompanion）与解析分支；
        #   ② 描述提示函数（SaqCompanionNote，中英文案）；
        #   ③ 内嵌回退载荷里的名字前缀（「巴雷特：违约」）—— 证明静态表的名字前缀
        #      也进了 SWF 的内嵌数据（不只是 C++ 载荷）。
        "同伴标记列 bSaqCompanion": b"bSaqCompanion",
        "同伴提示函数 SaqCompanionNote": b"SaqCompanionNote",
        #   ★★ 第 82 轮（文案说透 —— 玩家反馈「好感度不够时这些引导意义何在」）：
        #     旧句「达到一定水平后才能接取」会让人以为要跑去某个接取点 —— 实际是
        #     里程碑自动开始（官方 StartPersonalQuest → PersonalQuest.Start）。
        #     新句写清：① 自动开始、不需要找地方接取；② 好感度靠带同伴冒险；
        #     ③ 「设定航线」引导到的是**这位同伴本人**的位置。
        "同伴提示(中)": "好感度达到一定水平后自动开始".encode(),
        "同伴提示(英)": b"starts automatically once your affinity",
        #   ★★ 第 82 轮：尾部落点文案也必须换（首句说清了、尾部还写「接取地点」
        #     照样误导）—— 中/英各一条（SaqDescriptionText 的第 4 参数分支）。
        "同伴落点文案(中)": "引导到这位同伴的位置".encode(),
        "同伴落点文案(英)": b"to the companion's location",
        "内嵌载荷同伴名前缀(中)": "巴雷特：违约".encode(),
        # ★★ 第 74 轮续（「把它们放在一起」）：列表**顺序**探针 ——
        #   SAQ_Report 新增 `order=[…]`（MissionsList.SAQ_OrderProbe：我们 tab 前几行
        #   的 uID）。它是「同伴条目前置 + 按同伴分组」在**运行期**的唯一硬证据
        #   （载荷顺序 → InitializeEntries → entryList 这条链路只靠代码保证）。
        "列表顺序探针函数": b"SAQ_OrderProbe",
        "报告字段 order=[": b" order=[",
        # ★★ 第 75 轮（四大势力开头任务）：载荷加第 9/10 列（「简要说明」中/英），
        #   描述第一句改用它（取代「这条任务当前可以接取」）；「深红舰队」那条
        #   没有导航目标 ⇒ 另写一句「没有可以直接导航的接取地点」。
        "势力说明列(中) sSaqNoteZh": b"sSaqNoteZh",
        "势力说明列(英) sSaqNoteEn": b"sSaqNoteEn",
        "不可导航说明函数 SaqNoPickupNote": b"SaqNoPickupNote",
        "不可导航说明(中)": "没有可以直接导航的接取地点".encode(),
        "不可导航说明(英)": b"no direct pickup location",
        # ★★ 第 75 轮：`pin=` 探针 + 内嵌回退载荷里的说明文本（数据 → SWF 的硬证据：
        #   说明不是只写在静态表里，也真的跟着内嵌载荷进了 SWF）。
        "说明进描述探针函数 SaqPinNoteProbe": b"SaqPinNoteProbe",
        "报告字段 pin=[": b" pin=[",
        "内嵌载荷说明(UC 中)": "加入联合殖民地先锋队".encode(),
        "内嵌载荷说明(深红舰队 中)": "加入深红舰队".encode(),
        # ★★ 第 65 轮：图标帧自检 —— SAQ_Report 的 icon= 字段 + MissionsList.SAQ_IconProbe。
        #   数据层对了 ≠ 图标帧真的切过去了（索引错位 / 帧名拼错 / sprite 结构变化都会
        #   停在第 1 帧）；实机日志里的 `icon=[0x…:Constellation,…]` 是图标真的画出来的证据。
        "图标帧探针函数": b"SAQ_IconProbe",
        "报告字段 icon=": b" icon=[",
        # ★★ 第 89 轮（可重复任务）：载荷第 11 列 + 显示层豁免链 ——
        #   ① 解析列（bSaqRepeatable，SaqParsePayload 第 11 列）+ SaqBuildEntry 的字段传递；
        #   ② FilterKnownQuests 的豁免（已完成 + 可重复 ⇒ 保留 —— 否则 C++ 侧的
        #      「已完成」豁免会被 AS3 的「在玩家日志里」再丢一次，两边判据缺一不可）；
        #   ③ `rptk=` 探针（放行名单的运行期证据 —— harness 用例的直接判据）。
        "可重复任务标记列 bSaqRepeatable": b"bSaqRepeatable",
        "可重复保留名单 SaqRepeatKeptList": b"SaqRepeatKeptList",
        "可重复保留探针": b"SaqRepeatKept",
        "报告字段 rptk=[": b" rptk=[",
        # ★★ 第 91 轮（不可导航提示更明显 —— 玩家要求）：没有引导目标的条目
        #   （载荷第 5 列 bSaqHasTarget = false）在**列表名前面**加「（不可导航）」，
        #   不用选中就能看出「这条点了不会导航」（此前只有右侧描述 + 点击后的提示，
        #   长列表里看不出来，像 bug）。
        #   ① 前缀函数 + 中/英两条文案（英文带空格分隔）；
        #   ② 原名字段（sSaqBaseName / SaqBaseName）—— 「该任务暂无导航目标:…」
        #      提示与探针报**原名**（否则提示里会再带一次前缀）；
        #   ③ `nonav=` 探针（SaqNotNavigableProbe：报不可导航条目的**显示名** ——
        #      sName 正是 MissionsListEntry.SetEntryText 渲染的字段，运行期证据）。
        "不可导航前缀函数": b"SaqNotNavigablePrefix",
        "不可导航前缀(中)": "（不可导航）".encode(),
        "不可导航前缀(英)": b"(Not navigable)",
        "条目原名字段 sSaqBaseName": b"sSaqBaseName",
        "条目原名取值 SaqBaseName": b"SaqBaseName",
        "不可导航探针函数": b"SaqNotNavigableProbe",
        "报告字段 nonav=[": b" nonav=[",
        # ★★ 第 96 轮（可重复任务分组 —— 玩家反馈「前面也加上（可重复）提示，
        #   然后一样把他们排列在一起（就像图里的（可重复）NPC 入口那样）」）：
        #   ① 前缀函数（中/英文案由 SaqUseChinese 选，见函数体）；
        #   ② `rq=` 探针（SaqRepeatableQuestProbe：报可重复条目的**显示名** ——
        #      sName 正是 MissionsListEntry.SetEntryText 渲染的字段，前缀真的进
        #      显示名的运行期证据，与 nonav= 同一思路）；
        #   ③ `order=` 的 `|tail=` 段（MissionsList.SAQ_OrderProbe 从列表**末尾**
        #      回收两行的 `<uID>=<显示名>` —— 「整组排在列表末尾」的运行期证据）。
        "可重复前缀函数": b"SaqRepeatablePrefix",
        "可重复任务探针函数": b"SaqRepeatableQuestProbe",
        "报告字段 rq=[": b" rq=[",
        "顺序探针末尾段 |tail=": b"|tail=",
        }
    swf_paths = [
        ROOT / "ui/missionmenu/build/missionmenu.swf",
        ROOT / "ui/missionmenu_lrg/build/missionmenu_lrg.swf",
        MO2_MOD / "Interface/missionmenu.swf",
        MO2_MOD / "Interface/missionmenu_lrg.swf",
    ]
    for p in swf_paths:
        if not p.exists():
            print(f"MISS 缺少产物 {p}")
            all_ok = False
            continue
        blob = swf_text_bytes(p)
        for name, needle in swf_checks.items():
            all_ok &= check(f"{p.name} · {name}", blob, needle)
        # 反向检查：第 29 轮起「太远」的说法退场（玩家反馈不该有这种限制）
        gone = "离得太远".encode() not in blob and b"You are too far from this location" not in blob
        print(("OK  " if gone else "MISS") + f" {p.name} · 旧「太远」文案已移除(反向检查)")
        all_ok &= gone
        # 反向检查：★★ 第 44 轮 —— 原版星图 dispatch 已删除（星图位置滞后一条的病根），
        #   SWF 里不应再有那条「星图:已请求(代理任务 …)」note。
        gone = "星图:已请求(代理任务".encode() not in blob
        print(("OK  " if gone else "MISS") + f" {p.name} · 已删除原版星图 dispatch(反向检查)")
        all_ok &= gone
        # 反向检查：★★ 第 96 轮 —— 旧构建指纹不许残留（同一份 SWF 只该带一个 stamp；
        #   起因同第 50 轮的教训：部署了但游戏加载的是旧 SWF 时，指纹是唯一判据）。
        gone = b"stamp=62" not in blob
        print(("OK  " if gone else "MISS") + f" {p.name} · 旧构建指纹 stamp=62 已替换(反向检查)")
        all_ok &= gone

    # ★★ 第 49 轮补丁③（复测复查）：**入口发布清单**检查 —— 新增 root 入口必须挂到 root。
    #   事故：第 49 轮的 `SAQ_TestDrive*` 只加进了 MissionMenu 类，漏了
    #   `SaqPublishEntryPoint()`（把函数挂到 `_root` 的那份清单）—— 而 C++ 只能调
    #   `_root.*`（MissionMenu 是主时间轴的子元件）⇒ 首测与复测连续两轮 `ui.tab`
    #   都是 0 ms 失败（`fail(路径不存在或调用失败)`），排查一度被「参数个数」误导。
    #   为什么查 patch 源而不是 SWF：SWF 常量池里同名常量只有一份 —— 字符串检查
    #   **区分不了**「定义」与「挂载」；patch 源是 SWF 的直接上游（构建产物、同源文本）
    #   ⇒ 每个入口名至少出现 2 次（一次 `public function` 定义 + 一次挂载清单引用）。
    for p in [ROOT / "ui/missionmenu/patch/MissionMenu.as",
              ROOT / "ui/missionmenu_lrg/patch/MissionMenu.as"]:
        if not p.exists():
            print(f"MISS 缺少产物 {p}（先跑构建）")
            all_ok = False
            continue
        text = p.read_text(encoding="utf-8", errors="replace")
        # ★ 第 54 轮：新增子项选中入口（Enter 的「只引导」链 —— 第 26 轮「菜单久停」
        #   判据要靠它停在菜单里；主标题的 Enter 只展开，不切引导）。
        for fn in ("SAQ_TestDriveTab", "SAQ_TestDriveSelect", "SAQ_TestDriveSelectChild",
                   "SAQ_TestDriveExpand", "SAQ_TestDriveKey", "SAQ_TestDriveState"):
            cnt = text.count(fn)
            ok = cnt >= 2
            print(("OK  " if ok else "MISS")
                  + f" {p.parent.parent.name} · 入口已挂 root：{fn}（出现 {cnt} 次，需 ≥2 = 定义 + 挂载）")
            all_ok &= ok

    # ★★ 第 65 轮（任务专属图标）：图标帧探针必须进 MissionsList 的 patch
    #   （它是 SWF 里 MissionsList 类的直接上游 —— 定义在列表内部才拿得到 entryList/clip）。
    for ml in [ROOT / "ui/missionmenu/patch/MissionsList.as",
               ROOT / "ui/missionmenu_lrg/patch/MissionsList.as"]:
        if not ml.exists():
            print(f"MISS 缺少产物 {ml}（先跑构建）")
            all_ok = False
            continue
        ml_text = ml.read_text(encoding="utf-8", errors="replace")
        cnt = ml_text.count("SAQ_IconProbe")
        ok = cnt >= 1
        print(("OK  " if ok else "MISS")
              + f" {ml.parent.parent.name} · 图标探针已进列表 patch：SAQ_IconProbe（{cnt} 次）")
        all_ok &= ok

    dll = ROOT / "plugin/build/windows/x64/releasedbg/SAQ_ShowAvailableQuests.dll"
    release_mode = force_release
    if dll.exists():
        blob = dll.read_bytes()
        if not force_release and not force_dev:
            release_mode = dll_build_mode(blob) == "release"
        print("---- DLL 构建模式：" +
              ("发布构建（无 harness）" if release_mode else "开发构建（含 harness）") +
              ("（--release 强制）" if force_release else "") + " ----")
        for name, needle in {
            "引导结果回写": "引导结果已回写界面".encode(),
            "引导状态同步": "引导状态已同步界面".encode(),
            "菜单尚未就绪": "菜单尚未就绪".encode(),
            "引导重新下发": "引导重新下发".encode(),
            # 第 17 轮：多 master（DLC）+ 引导结果确认 + 认领已有引导
            "master 数据源日志": "数据源：".encode(),
            # ★ 第 18 轮改了文案（前缀探测下「未加载」也可能是「档位不支持」）
            "master 未加载跳过": "未加载（或档位不支持，跳过其任务）".encode(),
            "引导结果确认": "引导已生效".encode(),
            "认领已有引导": "认领已有引导".encode(),
            # 第 18 轮：前缀探测（替代 TESDataHandler::files）+ 空推送说明
            "前缀探测日志": "前缀探测：".encode(),
            "记录命中率": "记录命中 {}/{}".encode(),
            "空推送说明": "本轮没有可推送的条目".encode(),
            # 第 19 轮：脚本活性探测 + 引导未生效收尾（清通道 + 结果码 4 回写界面）
            "脚本活性探测": "脚本活性探测".encode(),
            "脚本未响应提示": "没有响应菜单事件".encode(),
            "引导未生效收尾": "引导未生效：".encode(),
            # 第 20 轮：控制台测试过滤（set SAQ_TestMode to N）
            "测试模式日志": "测试模式：".encode(),
            "测试模式说明": "只显示「有引导目标」的条目".encode(),
            "测试过滤统计": "测试过滤".encode(),
            # 第 20 轮补丁：实机上控制台 `set` 不认 EDID（Unknown variable）⇒ ini 文件兜底
            "ini 兜底开关": "SAQ_ShowAvailableQuests.ini".encode(),
            "测试模式来源": "[来源=".encode(),
            # 第 21 轮：引导目标 FormID 拆「低 24 位 + 高 8 位」（float 精度 + 上限 bug 修复）
            "引导目标高位拆分": "SAQ_GuidePrefix".encode(),
            "通道垃圾值文案": "通道读数是垃圾".encode(),
            # 第 22 轮：日志与配置写进插件目录（mod 目录），不落 C 盘用户目录
            "日志写在插件目录": "插件目录（mod 目录）内".encode(),
            "ini 写在插件目录": "插件目录内的 SAQ_ShowAvailableQuests.ini".encode(),
            # 第 26 轮：确认窗口与菜单状态绑定（菜单开着不判失败 / 关菜单重置窗口）
            "菜单开着不判失败": "脚本只在菜单关闭时应用引导".encode(),
            "关菜单重置确认窗口": "脚本会在关闭事件里应用引导".encode(),
            # 第 27 轮：无限任务入口（任务板）+ 降噪
            "入口条目表日志": "入口条目表=".encode(),
            "入口测试模式说明": "无限任务入口".encode(),
            "入口认领日志": "认领已有引导（任务板入口）".encode(),
            # ★ 第 28 轮修正：中文名用游戏官中译名（"任务板 · 陋室" = The Lodge）
            "入口条目数据": "任务板 · 陋室".encode(),
            # ★★ 第 80 轮（可重复 NPC 入口）：入口表两类的计数日志 + NPC 名字前缀
            #   （数据真的进了 DLL 的静态表 —— 不只是生成脚本写对了文件）。
            "入口两类计数(日志)": "（任务板 {} + 可重复 NPC {}）".encode(),
            "可重复NPC名字前缀(中)": "（可重复）贸易管理局 · 邓肯·林奇".encode(),
            "可重复NPC名字前缀(英)": b"(Repeatable) Trackers Alliance Agent - Akila City",
            "引导确认降噪文案": "关菜单后自动确认".encode(),
            # ★ 第 30 轮：入口引导目标的**候选链**（marker → 原板 → 常驻兜底）+ 统计/诊断
            "入口统计列(候选链)": "入口={}(可导航 {}｜marker {} 原板 {} 兜底 {} 不可用 {})".encode(),
            "入口无可用目标不写通道": "当前没有可用的引导目标".encode(),
            "入口候选诊断": "入口候选诊断".encode(),
            # 不可导航名单（正常应恒为空；第 28/29 轮的兜底诊断，第 30 轮起带候选命中详情）
            "入口不可导航名单": "入口不可导航: ".encode(),
            # ★ 第 31 轮：候选链改「精确优先」（任务板自身 → 常驻 marker → 常驻兜底）
            #   + 引导过程中的目标动态更新 + marker 取不到时的数据侧探测
            "入口精确目标来源": "任务板自身（精确）".encode(),
            "入口目标动态更新": "入口引导目标已更新".encode(),
            "入口 marker 探测": "入口 marker 探测".encode(),
            "入口静默更新不清通道": "通道保持不动".encode(),
            # ★ 第 32 轮：菜单关着时的例行认领 + 通道对账（重启/读档后不进菜单也能自愈）
            "引导状态对账日志": "引导状态对账：".encode(),
            # ★ 第 33 轮：菜单关着时**也要**保证静态表就绪（否则认领三条反查全落空，
            #   第 32 轮的自愈形同虚设 —— 13:43 会话实证）
            "静态表预建日志": "静态表已就绪（菜单关着时预建".encode(),
            "静态表未就绪日志": "静态表尚未就绪".encode(),
            # ★ 第 35 轮：进度门槛（「游戏进度还不能让玩家接到 ⇒ 不显示」）
            "进度门槛统计": "进度门槛=".encode(),
            "进度没到名单": "进度没到: ".encode(),
            "进度门槛开关(ini)": "ProgressCond".encode(),
            "进度门槛切片越界保护": "门槛切片越界".encode(),
            "★ 第 87 轮 OR 位切片保护": "门槛 OR 位切片越界".encode(),
            "IsStageDone 不可用提示": "IsStageDone 不可用".encode(),
            # ★★ 第 37 轮：SET COURSE 的星图 —— 关任务菜单 + 结果探测 + 状态 5
            "星图请求(旧协议 kHide)": "星图：已请求关闭任务菜单".encode(),
            "星图结果(已打开)": "星图：已打开（GalaxyStarMapMenu 在屏幕上".encode(),
            # ★ 第 40 轮：这句补上「已尝试 N 次」，所以只查前缀
            "星图结果(没打开)": "秒内没有打开".encode(),
            # ★ 第 40 轮：状态值改由 std::format 生成（5/6/7 三个地点候选），所以只查后缀
            "星图请求状态文案": "（星图请求）".encode(),
            "星图原生函数名": b"ShowGalaxyStarMapMenuAndPlotToLocation",
            # ★★ 第 41 轮：星图的**注册名** = GalaxyStarMapMenu（不是 MapMenu）。
            #   引擎自己的 ShowGalaxyStarMapMenu*（0x2010170 / 0x2010210）调 0x253cfa0
            #   拿到的静态 BSFixedString 内容就是它（.rdata 0x4C96340）—— 第 37~40 轮
            #   误用菜单名表里的 MapMenu ⇒ 所有「星图没打开」判定都是假阴性。
            "星图菜单名(注册名)": b"GalaxyStarMapMenu",
            # ★★ 第 38 轮：SET COURSE 的「最外层主菜单 / 要等好久」修复 ——
            #   新协议（界面侧关整个暂停菜单）+ 多段探测（还开着哪些菜单 / R 后多少秒打开）
            "星图请求(新协议 界面关菜单)": "星图：界面侧会自己关掉整个暂停菜单".encode(),
            # ★★ 第 44 轮：R 键星图位置滞后一条的修复 ——
            #   ① 日志写明星图的唯一入口 = 脚本的轮询节拍（原版 dispatch 已删）；
            #   ② 重试等待文案与脚本新窗口（1 个轮询节拍）对齐。
            "星图唯一入口说明": "星图由脚本在菜单关闭后的下一个轮询节拍打开".encode(),
            "星图脚本应用后窗口": "它的星图调用在下一个轮询节拍".encode(),
            "星图等待(通用)": "星图：等待中".encode(),
            "星图等待(任务菜单仍开着)": "星图：等待中——任务菜单仍开着".encode(),
            #   ★ 第 48 轮：文案改清楚 —— 旧「还开着：」在空列表时自相矛盾（「等待中…还开着：无」）。
            "星图等待(列出开着的菜单)": "其它打开的菜单：".encode(),
            "星图打开(带耗时)": "R 后约".encode(),
            # 暂停菜单的真正注册名（exe 菜单名表里是 PauseMenu，没有 DataMenu）
            "暂停菜单名": b"PauseMenu",
            # ★★ 第 40 轮：星图「没开就自动重试」+「地点 → 星图节点」只读诊断
            #   （16:28 会话：脚本在菜单关闭后 0.5 秒调用 ⇒ 星图根本没开）
            "星图重试日志": "星图：第".encode(),
            "星图重试换候选": "地点候选随之切换".encode(),
            "星图放弃重试": "星图：放弃重试".encode(),
            "星图诊断(地点链)": "星图诊断（".encode(),
            "星图诊断(父地点)": "父地点".encode(),
            "星图诊断(节点)": "节点=0x".encode(),
            "星图诊断(未命中)": "（未命中：星图不会定位到这个地点）".encode(),
            "星图诊断(玩家对照)": "玩家所在地点".encode(),
            "星图节点解析器特征校验": "节点解析器不可用".encode(),
            # ★★ 第 41 轮：修正后的函数头特征字节（mov r11,rsp / [r11+0x20],rbx / push rbp）
            #   —— 上面的字符串检查只证明「有这么一句日志」，这一条才证明字节真的修了
            #   （数组是 constexpr，MSVC 把它放在 .rdata，二进制里能直接查到）
            "星图节点解析器特征字节": b"\x4c\x8b\xdc\x49\x89\x5b\x20\x55",
            # ★★ 第 42 轮：R 键「导航目标不是我悬停的那条」——
            #   ① 引导请求日志尾上带界面的 press/sel（ExtractBracketField/As3PressNote）；
            #   ② 星图重试改成「脚本确认应用（状态 1）后再等一段余量」，不再抢在脚本
            #      自己的 1.5 秒延时前面改地点候选（那会让星图航线/目的地跳变）。
            "界面按键行抄录": b"press={} sel={}",
            "界面报告读不到的说明": "press=? sel=?（界面报告读不到）".encode(),
            "星图等脚本确认应用": "脚本已应用这次引导（状态=1）".encode(),
            "星图不改候选只等待": "这段时间内不改地点候选，只等星图出现".encode(),
            "星图重试带上已应用时长": "脚本已应用 {:.1f} 秒仍未出现".encode(),
            # ★★ 第 43 轮：菜单关闭时刻的两项补强 —— ① 现场读一次界面报告（不再只用
            #   500ms 轮询的缓存，否则「按 R 与关菜单同周期」时日志会把现场抹掉）；
            #   ② 关闭前补一次引导请求轮询（否则按 R 后立刻关菜单时，请求会被
            #   紧随其后的 lastSeq 重置丢掉）。
            "菜单关闭补处理请求": "补处理了关闭瞬间的引导请求".encode(),
            # ★★ 第 45 轮：引导目标**候选池**（多候选链）——
            #   ① 点引导时挑「此刻可得的、质量最优的」候选（远处不会先撞取不到的 NPC）；
            #   ② 脚本报状态 2（取不到）时自动换下一个候选；
            #   ③ 菜单关着时复算（飞近后自动升级回有名字的 NPC / 目标失效时回退）。
            "引导换候选日志": "引导换候选：".encode(),
            "候选复算日志": "引导目标已更新（候选复算）".encode(),
            "候选全不可得日志": "个候选此刻都取不到".encode(),
            "请求日志带候选注记": "候选 [".encode(),
            "认领日志带候选下标": "（候选 [".encode(),
            # ★★ 第 45 轮补丁（实机日志复查：「朱诺的计谋」星图里没有目标位置）：
            #   目标在飞船内部/动态创建的内部地点时星图节点解析**全层 = 0** ⇒ 脚本不开
            #   星图、改发 HUD 提示；DLL 侧不重试、超时文案改「按预期未打开」。
            "星图诊断全层未命中": "地点链全层节点=0".encode(),
            "星图按预期未打开": "星图：按预期未打开".encode(),
            # ★★ 第 46 轮（大项 B）：引导可用性 + 提示收口 —— 点引导时「所有候选都取不到」
            #   不再 19 秒后静默放弃，改为**保持待生效** + 退避重试 + 界面/HUD 提示。
            "待生效判定日志": "保持待生效".encode(),
            "待生效确认日志": "目标尚未加载".encode(),
            "延迟生效日志": "引导延迟生效".encode(),
            "退避重试日志": "引导重试（等待目标加载）".encode(),
            "重试停手日志": "引导待生效（暂停重试）".encode(),
            "星图本次不打开": "星图：本次不打开（目标尚未加载）".encode(),
            # ★★ 第 46 轮：测试过滤新增 Mode=6 —— 只显示「需要靠近」的任务
            #   （实测样本「营救机器人」），方便实测时找条目。
            #   ★ 第 47 轮：判据升级为「首选候选非常驻」（兜底候选是常驻的）。
            "测试模式 6 日志文案": "只显示「需要靠近」的条目".encode(),
            # ★ 第 48 轮：判据回退为「全部候选都非常驻」（20 条）—— ini 说明同步。
            "测试模式 6 ini 说明": "全部候选都非常驻，20 条".encode(),
            # 上限写死成 5 曾把 Mode=6 静默折成 0（玩家看到的是「过滤失效」）⇒ 现在
            # 超范围要 WARN，且模式行**无论开没开都打**（缺了这行就没法区分「ini 没读到」）。
            "测试模式超范围告警": "超出已知范围".encode(),
            # ★★ 第 47 轮（大项 C）→ 第 48 轮收口：「需要靠近」判据 = **全部**候选都非常驻
            #   （第 47 轮曾放宽为「首选候选非常驻」，实测命中 158 条 ⇒ 提示噪音化，已回退）。
            "需要靠近判据(全部)": "全部候选都非常驻".encode(),
            # ★★ 第 48 轮（大项 D）：INFO 门槛（对话侧条件）—— 统计行 / 名单 /
            #   误判告警（引擎已开始却要隐藏 ⇒ WARN）/ ini 开关与说明。
            "INFO 门槛统计": "INFO门槛=".encode(),
            "INFO 没到名单": "INFO没到:".encode(),
            #   ★ 第 48 轮补丁（实机日志复查抓到的误藏）：引擎已开始 ⇒ **放行**（不隐藏）。
            #   依据：第 11 轮实证「引擎 started 的任务玩家仍可能接到」（RAD05「全数到期」）；
            #   21:46 会话的交叉验证自动抓出它 + 「陌生人的善意」两条误藏。
            "INFO 门槛引擎自启放行": "INFO 门槛判定『进度没到』但引擎已开始 —— 放行".encode(),
            "INFO 统计含放行": "/放行".encode(),
            "ini INFO 开关": "InfoCond=1".encode(),
            "ini 对话条件说明": "对话条件过滤".encode(),
            # ★ 第 48 轮：认领后的复算宽限期（读档瞬间引擎查询不可靠）+ 引导更新未确认
            #   文案去「入口」二字（普通任务的候选复算也走同一个 WARN）。
            "认领宽限说明": "读档 / 脚本未运行期间出现这一行属预期".encode(),
            "引导更新未确认(新文案)": "引导目标更新未被脚本确认".encode(),
            # ★ 第 49 轮补丁（读档复算抖动）：候选**降级观察期** ——
            #   当前候选取不到时先保持（通道不动），持续约 20 秒仍取不到才降级；
            #   一旦恢复可得立即清观察（升级路径一直是立即执行）。依据：21:57 会话
            #   实测读档后目标持续取不到 ≈19 秒才恢复（8 秒宽限期挡不住 ⇒ [1]→[3]→[1]）。
            "候选降级观察期(先保持)": "此刻取不到 —— 先保持".encode(),
            "降级观察结束(恢复可得)": "恢复可得 —— 观察结束".encode(),
            "入口降级观察期": "入口引导目标复算".encode(),
            # ★★ 第 62 轮补②（12:2x 会话「自动读档后游戏退回主菜单 + 跳出」）：
            #   读档 / 加载窗口内**暂缓**例行认领与候选复算 ——
            #   「任务菜单没开」≠「游戏世界里」（主菜单 / LoadingMenu / FaderMenu 也走
            #   "菜单关着"分支，而那正是引擎卸载/重建世界数据的时刻）。实测（12:31 会话，
            #   对照 SAS_AlwaysScan 的菜单事件日志）：静态表预建 + 认领正好落在读档窗口内，
            #   读档随后失败（MainMenu 重新打开），6 秒后引擎空指针崩溃（exe+0x1999E57，
            #   两次转储现场一致：rcx=0、读 0x20、故障线程 = 文件 I/O 工作线程）。
            "读档/加载窗口暂缓文案": "例行认领 / 候选复算暂缓".encode(),
        }.items():
            all_ok &= check(f"DLL · {name}", blob, needle)
        # 反向检查：第 47 轮把「候选**全是**非常驻引用」的旧说法换掉
        #   （判据已改为「全部候选都非常驻」）
        gone = "候选全是非常驻引用".encode() not in blob
        print(("OK  " if gone else "MISS") + " DLL · 旧「全是 非常驻」判据文案已替换(反向检查)")
        all_ok &= gone
        # 反向检查（第 48 轮）：① 「首选候选非常驻」的放宽判据文案已回退；
        #   ② 「入口引导目标更新未被脚本确认」的旧 WARN 文案去掉「入口」二字；
        #   ③ 星图旧「还开着：」文案已替换（空列表时自相矛盾）；
        #   ④ 补丁：旧「INFO 门槛要隐藏…但引擎已开始」的 WARN 已换成「放行」。
        gone = ("首选候选非常驻".encode() not in blob
                and "入口引导目标更新未被脚本确认".encode() not in blob
                and "还开着：".encode() not in blob
                and "INFO 门槛要隐藏".encode() not in blob)
        print(("OK  " if gone else "MISS") + " DLL · 第 48 轮旧文案已替换(反向检查)")
        all_ok &= gone
        # 反向检查：第 31 轮把候选链顺序换掉，第 30 轮的「marker 优先」诊断文案不应再出现
        gone = "这些条目没走新建的常驻 marker".encode() not in blob
        print(("OK  " if gone else "MISS") + " DLL · 旧候选链诊断文案已替换(反向检查)")
        all_ok &= gone
        # 反向检查：第 33 轮把「认不出通道目标」的误导文案改掉（静态表没就绪 ≠ 另一个存档留下的）
        gone = "另一个存档留下的？".encode() not in blob
        print(("OK  " if gone else "MISS") + " DLL · 旧「认不出」误导文案已替换(反向检查)")
        all_ok &= gone
        # 反向检查：第 27 轮把「每次切条目打一行」的旧说明换成「每菜单一行」，旧串不应再出现
        gone = "脚本状态还是 0，但菜单还开着".encode() not in blob
        print(("OK  " if gone else "MISS") + " DLL · 旧引导确认文案已替换(反向检查)")
        all_ok &= gone
        # 反向检查：第 18 轮换掉的旧「未加载」文案不应再出现（新文案不含完整旧串）
        gone = "未加载（跳过其任务）".encode() not in blob
        print(("OK  " if gone else "MISS") + " DLL · 旧未加载文案已替换(反向检查)")
        all_ok &= gone
        # 反向检查：第 19 轮把「确认超时」整体换成「引导未生效」收尾，旧文案不应再出现
        gone = "引导结果确认超时：".encode() not in blob
        print(("OK  " if gone else "MISS") + " DLL · 旧确认超时文案已替换(反向检查)")
        all_ok &= gone
        # 反向检查：第 30 轮把「任务板引用取不到」换成候选链判定，旧文案不应再出现
        gone = "的任务板引用当前取不到".encode() not in blob
        print(("OK  " if gone else "MISS") + " DLL · 旧入口取不到文案已替换(反向检查)")
        all_ok &= gone
        # 反向检查：第 38 轮把「2.5 秒单点判定」的旧文案换成多段窗口，旧串不应再出现
        gone = ("星图：任务菜单没被关掉".encode() not in blob
                and "星图：没有打开（MapMenu 不在屏幕上）".encode() not in blob)
        print(("OK  " if gone else "MISS") + " DLL · 旧单点星图探测文案已替换(反向检查)")
        all_ok &= gone
        # 反向检查：第 41 轮修正的特征字节 —— 旧的 `4C 89 1C 24`（mov [rsp],r11，抄反了）
        #   不应再出现在 DLL 里（新字节里第一个 dword 是 4C 8B DC）
        gone = b"\x4c\x89\x1c\x24\x49\x89\x5b\x20" not in blob
        print(("OK  " if gone else "MISS") + " DLL · 旧星图节点解析器特征字节已修正(反向检查)")
        all_ok &= gone
        # ★★ 第 67 轮：任务链门槛（「上一个任务的收尾 stage 启动下一个任务」）——
        #   产品侧三处特征：统计/名单日志 + ini 模板里的开关（[Filter] ChainCond）。
        for name, needle in {
            "链式门槛统计（链式门槛= 过/藏/未知）": "链式门槛=",
            "链式门槛名单（链式没到:）": "链式没到: ",
            "链式门槛 ini 开关（[Filter] ChainCond）": "ChainCond=1",
            # ★★ 第 74 轮（同伴好感度任务）：「入口」同伴任务固定显示 —— 统计与名单。
            #   `其中 N 条被门槛判「进度没到」但放行` = 固定显示真的起作用的证据；
            #   名单每条带「同伴=」与「跳过门槛」标记；「后续」（承诺任务）不在这里
            #   —— 它们照旧走链式门槛（前置没到 ⇒ 在「链式没到」名单里）。
            "同伴固定统计（同伴固定=）": "同伴固定=",
            "同伴固定名单（同伴固定名单:）": "同伴固定名单: ",
            "同伴固定放行标记（跳过门槛）": "跳过门槛",
            "同伴名查表（kCompanionNamesZh）": "同伴=",
            # ★★ 第 74 轮续（「把它们放在一起」）：同伴条目前置的统计 ——
            #   `同伴分组前置=N(按同伴分组，入口在后续前)`。
            "同伴分组前置统计": "同伴分组前置=",
            # ★★ 第 75 轮（四大势力开头任务）：固定显示 + 固定排前四。
            #   ① 统计与名单（单独一行 —— 见 FormatPinStats 的拆行理由）；
            #   ② 数据侧两条说明文本编进 DLL（kFactionEntryNotes*）——证明数组真的在；
            #   ③ 势力名（kFactionEntryNames*）与排序/固定顺序的文案。
            "势力入口固定统计（势力入口固定=）": "势力入口固定=",
            "势力入口固定名单（势力入口固定名单:）": "势力入口固定名单: ",
            "势力入口前置统计（势力入口前置=）": "势力入口前置=",
            "势力入口固定顺序文案": "固定顺序：联合殖民地→自由星→龙神→深红舰队",
            "势力说明数据(UC)": "加入联合殖民地先锋队",
            "势力说明数据(深红舰队)": "加入深红舰队",
            "势力名数据(kFactionEntryNamesZh)": "联合殖民地先锋队",
            # ★★ 第 81 轮（地球地标任务）：说明数组（kLandmarkNotesZh/En）编进 DLL ——
            #   两条样本（阿波罗 / 上海）证明数组真的在（描述第一句会用它）。
            "地标说明数据(阿波罗)": "拾取《利文斯通爵士的第二篇日志》",
            "地标说明数据(上海)": "拾取《现代宏观经济学概论》",
            # ★★ 第 89 轮（可重复任务）：说明数组（kRepeatableNotesZh/En）编进 DLL
            #   + 运行期豁免的统计/名单（FormatRuntimeStats）。
            #   ① 说明数据（两条样本：翻新商品 / 全数到期）证明数组真的在（描述第一句用它）；
            #   ② `可重复任务=N(已完成保留M)` 与 `可重复保留: 名单` = 豁免真的在运行期
            #      生效的证据（`已完成保留` = 本该被「只挡已完成」剔掉、因可重复留下的条数）。
            "可重复任务说明数据(翻新商品)": "（可重复）完成一次后还能再次接取",
            "可重复任务说明数据(全数到期)": "盖尔银行",
            # ★★ 第 90 轮：DLC 的 SFFL 家族两条样本 —— 有接取人（仲裁者）与随机太空遭遇
            #   （「随机太空遭遇」这个说法只可能来自本轮新加的 DLC 文案）。
            "可重复任务说明数据(职业杀手)": "仲裁者",
            "可重复任务说明数据(危险材料)": "随机太空遭遇",
            "可重复任务统计（可重复任务=）": "可重复任务=",
            "可重复任务保留名单（可重复保留:）": "可重复保留: ",
        }.items():
            all_ok &= check(f"DLL · {name}", blob, needle.encode())
        # ★★ 第 49 轮（引擎内 harness）：用例驱动器 + 原语层。
        #   ① 驱动器（SAQ_Test.cpp）：读用例文件、按步骤状态机跑、写结果 JSON；
        #   ② 原语层（SAQ_TestOps.cpp）：日志环形缓冲 / 命令通道（GLOB 0x806~0x80D）/
        #      菜单开关（kShow/kHide，与已实测的关菜单同一机制）/ 界面测试驱动；
        #   ③ 只有 ini [Test] Harness=1 才启用（其余情况零开销）。
        #   ★ 第 49 轮补丁：无参 AS3 入口按 0 参调用（传空串占位 ⇒ 首测卡在 ui.tab）；
        #     用例结束（含失败中止）清菜单（否则失败后菜单留在屏幕上、游戏暂停）。
        #   ★★ 第 50 轮：ui.* 失败时带「SWF 版本指纹」（读 SAQ_Report 的 stamp=，
        #     分清「游戏加载的是新版还是旧版 SWF」）。
        #   ★★ 第 53 轮（大项 F · 发布就绪）：这些条目在**发布构建**
        #     （SAQ_WITH_HARNESS=0）里一条都不该出现 —— 同一张表反向检查
        #     （漏一条 = 发布包里带着测试代码，正是本层要挡的事）。
        if release_mode:
            leaked = [name for name, needle in HARNESS_STRINGS if needle.encode() in blob]
            if leaked:
                print("MISS DLL · 发布构建不含 harness 特征（泄漏：" + "、".join(leaked) + "）")
                all_ok = False
            else:
                print(f"OK   DLL · 发布构建不含 harness 特征（{len(HARNESS_STRINGS)} 项全无）")
            # 反过来的正向要求：发布版要带上「Harness=1 但没编译」的那行 WARN ——
            # 否则「改了开关没反应」又变成静默失败（第 49 轮 ini 段坑的教训）。
            all_ok &= check("DLL · 发布构建提示（Harness=1 时 WARN）", blob, "未编译 harness".encode())
        else:
            for name, needle in HARNESS_STRINGS:
                all_ok &= check(f"DLL · {name}", blob, needle.encode())
            # 反向检查（第 58 轮）：命令超时的旧文案是一句**静态猜测**
            #   （「确认此刻菜单是关的」）—— 10:31 会话「MoveTo 永不返回」时它什么也
            #   证明不了（该带上的证据 = 此刻 LoadingMenu/FaderMenu 是否开着）。
            gone = "确认此刻菜单是关的".encode() not in blob
            print(("OK  " if gone else "MISS") +
                  " DLL · 旧「确认此刻菜单是关的」静态提示已替换(反向检查)")
            all_ok &= gone
            # 反向检查（第 58~62 轮）：旧驱动器版本串不应再出现 —— 日志里那串
            #   「驱动器 v61：…」是「跑的是不是这一版驱动器」的唯一判据（同 SWF stamp=）。
            gone = ("驱动器 v57".encode() not in blob and "驱动器 v58".encode() not in blob and
                    "驱动器 v59".encode() not in blob and "驱动器 v60".encode() not in blob and
                    "驱动器 v61".encode() not in blob and "驱动器 v62".encode() not in blob and
                    "驱动器 v63".encode() not in blob and
                    # ★★ 第 68 轮：v66（命令回执窗口那版）也不许再出现 —— 新版串里
                    #   带的是「沿用：v66 …」而不是「驱动器 v66 …」（同一条判据的延伸）。
                    "驱动器 v66".encode() not in blob and
                    # ★★ 第 69 轮：v68 同理（新版串里带的是「沿用 v68 …」）。
                    "驱动器 v68".encode() not in blob)
            print(("OK  " if gone else "MISS") +
                  " DLL · 旧驱动器版本串 v57~v63/v66/v68 已替换(反向检查)")
            all_ok &= gone
            # ★★ 第 54 轮：用例计划本身也该被查 —— 历史判据（第 26/44~48 轮）落成用例后，
            #   最怕的是「源码改了没部署」或「用例被误删」。这里只查**开发模式**：
            #   ① 7 条用例都在（smoke + 5 条历史判据 + 第 62 轮自动读档）；
            #   ② MO2 部署副本与工作区**字节一致**（部署未落后 —— 与 DLL 同一条教训）。
            plan_src = ROOT / "tools/test/scenarios/SAQ_TestPlan.txt"
            if plan_src.exists():
                plan_text = plan_src.read_text(encoding="utf-8", errors="replace")
                for cid in ("smoke", "r26_menu_idle", "r44_starmap", "r45_candidates",
                            "r47_board_marker", "r48_info_gate", "r65_icons",
                            "r67_chain", "r67_chain_pass",
                            # ★★ 第 69 轮：链式门槛扩展边（霓虹城帮派线 A/B 两条）
                            "r69_chain_extra", "r69_chain_extra_pass",
                            # ★★ 第 71 轮：链式门槛全量入边审计（CF 线 / 火星城官僚线 A/B）
                            "r71_chain_cf", "r71_chain_redtape", "r71_chain_redtape_pass",
                            # ★★ 第 74 轮：同伴好感度任务（入口固定显示 + 后续走链式门槛）
                            "r74_companion",
                            # ★★ 第 75 轮：四大势力开头任务（固定显示 + 固定排前四 +
                            #   深红舰队只给说明）
                            "r75_faction_entry",
                            # ★★ 第 77 轮：龙神线后续（「RIR 留专项」收口）—— A/B 两条
                            "r77_chain_ryujin", "r77_chain_ryujin_pass",
                            # ★★ 第 78 轮：DLC 的 INFO 门槛（地球舰队的后续被藏）
                            "r78_dlc_info_gate",
                            # ★★ 第 80 轮：提供无限任务的 NPC 条目（8 条 + 名字前缀 +
                            #   引导落常驻 marker）
                            "r80_repeatable_npc",
                            # ★★ 第 81 轮：地球地标任务（10 条进列表 + 引导落常驻兜底 +
                            #   伦敦只给说明）
                            "r81_landmark",
                            # ★★ 第 87 轮：进度门槛 OR 组（A：被藏 / B：补做 Z04 放行）
                            "r87_or_group", "r87_or_group_pass",
                            # ★★ 第 89 轮：可重复任务做完一次后仍显示（C++ 豁免 +
                            #   显示层 FilterKnownQuests 放行 —— rptk= 探针为直接判据）
                            "r89_repeatable",
                            # ★★ 第 90 轮：DLC（SFBGS00D）可重复任务同一条链路 ——
                            #   目标 = 「职业杀手」（记录号 0x0002A418，`~0x…` 写法）
                            "r90_dlc_repeatable",
                            # ★★ 第 96 轮：可重复任务 —— 名字「（可重复）」前缀 +
                            #   整组排在列表末尾（rq= / order= 的 |tail= 段为判据）
                            "r96_repeatable_group",
                            # ★★★ 第 98 轮：DLC 链式门槛（官方 .pex 反编译取证）——
                            #   A：破碎空间主线后续在「链式没到」名单里；B：推进 MQ01
                            #   到收尾 stage 后「虚妄的得诺者」不再被链式藏
                            "r98_dlc_chain", "r98_dlc_chain_pass",
                            # ★★★ 第 101 轮：DLC 链式门槛**二期**（14 + 1 条新边）——
                            #   A：新目标在「链式没到」名单里。
                            #   ★★ 第 101 轮补丁（20:41 会话实测 FAIL）：+ 只读探针
                            #   `quest.probe`（直读引擎）。
                            #   ★★★ 第 103 轮：B 段的放行判据**并入上面那条
                            #   `r98_dlc_chain_pass`**（MQ_Shell 一个会话只能推一次 ——
                            #   引擎对「已运行过又被 Reset 的任务」拒绝再次 Start），
                            #   所以 `r101_dlc_chain2_pass` / `r101_dlc_chain2_mq05`
                            #   两条用例已删除（不是漏掉，别再"补"回来）。
                            "r101_dlc_chain2",
                            # ★★★ 第 106 轮（operator 全量产品化）：INFO 门槛 OR 组 ——
                            #   A：112/114 都没做 ⇒ 探针报「组[0]=假」；B：推 112 ⇒ 组=真
                            "r106_info_or", "r106_info_or_pass",
                            "r62_reload_observe"):
                    all_ok &= check(f"用例计划 · [case:{cid}]", plan_text.encode(),
                                    f"[case:{cid}]".encode())
                # ★★★ 第 98 轮：两条 DLC 链式用例的断言形状（防被改回「点名一条」
                #   或写死运行期 FormID —— 六条里任意一条命中即可；ID 用 `[0x` 通配）。
                #   ★ 第 99 轮：名字修正（「狂热逾界」「发掘过去」—— 旧版手打成了
                #   「狂热逼界」「发觉过去」，靠断言的「或」语义没暴露）。
                all_ok &= check("用例计划 · r98 DLC 链式门槛断言（A：六条任一被藏）",
                                plan_text.encode(),
                                "assert.log 链式没到: .*(虚妄的得诺者|家族的调和|狂热逾界".encode())
                # ★★★ 第 99 轮（实测复盘修正）：B 段从「推 MQ01@10000」改成
                #   「推 MQ_Shell@100」—— 原设计实测造不出状态（所有统计行逐字段不变），
                #   且 MQ01 的收尾 fragment 是 `Self.Stop()` + `AddAchievement(51)`
                #   （不可观测 + 成就污染风险）；MQ_Shell@100 的三条议会任务边安全可观测。
                all_ok &= check("用例计划 · r98 DLC 链式门槛放行断言（B：assert.nolog）",
                                plan_text.encode(),
                                "assert.nolog 链式没到:.*(狂热逾界|信念之争|发掘过去) scope=case".encode())
                # 反向检查①：DLC 用例里不许把运行期 FormID 写死（必须用 `~0x…` 记录号）。
                bad_dlc_fid = ("quest.reset 0x010116C7" in plan_text
                               or "quest.start 0x01035E1B" in plan_text)
                print(("MISS " if bad_dlc_fid else "OK  ") +
                      " 用例计划 · r98 DLC 用例用 ~0x 记录号（反向检查）")
                all_ok &= not bad_dlc_fid
                # 反向检查②（第 99 轮）：不许再出现「推 MQ01@10000」的不可达写法
                #   （实测造不出 + fragment 带 Stop/成就，见 docs/09 十四·补二十四）。
                bad_mq01_push = "quest.stage ~0x000121DB 10000" in plan_text
                print(("MISS " if bad_mq01_push else "OK  ") +
                      " 用例计划 · r98 不再推 MQ01@10000（反向检查，第 99 轮）")
                all_ok &= not bad_mq01_push
                # ★★★ 第 101 轮（B3 · DLC 链式门槛二期）：新用例的断言形状 ——
                #   A：新目标**任一**进「链式没到」名单（名字只写 `[0x`，不写死 FormID）；
                #      「或」的成员 = 离线预判里必然能走到链式判定的那几条（深入VOID / 失控 /
                #      MQIntro星际遭遇战 / 失踪的爱人 在 INFO 数据里没有门槛）。
                #   B（★ 第 103 轮并入 r98 B 段，见下方第 103 轮检查）：两条二期边
                #      （发掘过去@1600 / 狂热逾界@4000）的「产品放行」判据。
                all_ok &= check("用例计划 · r101 DLC 链式二期断言（A：新目标任一被藏）",
                                plan_text.encode(),
                                "assert.log 链式没到: .*(另一边|深入VOID|失控|MQIntro星际遭遇战|失踪的爱人)\\[0x".encode())
                # ★★★ 第 103 轮（2026-09-22 21:52 会话实测判读）：**MQ_Shell 一个会话
                #   只能推一次** —— 引擎对「已经运行过、又被 Reset 的任务」拒绝再次
                #   Start（第二次 start 后 `已开始=40` / `链式 过4/藏59` / probe 全无变化；
                #   而首次启动 = `已开始 34→44` + `链式 过4→7`）。⇒ 二期两条边的放行
                #   判据**并入 r98 B 段**（同一次预热覆盖三条判据）。verify 要钉住两件事：
                #     ① 「唯一推 MQ_Shell 的地方」这句说明还在（防又拆成两条用例）；
                #     ② 放行证据走**显示层**（`ui.select` 命中 = 进了列表 = 玩家可见行为）。
                all_ok &= check("用例计划 · 第 103 轮「MQ_Shell 只能推一次」说明",
                                plan_text.encode(),
                                "全用例集里唯一推 MQ_Shell 的地方".encode())
                all_ok &= check("用例计划 · r101 放行判据走显示层（ui.select 另一边）",
                                plan_text.encode(), "ui.select ~0x0010AAD5".encode())
                # ★★★ 第 106 轮（operator 全量产品化 · INFO 门槛 OR 组）：断言形状 ——
                #   只读探针 `info.probe` + 组求值结果（A 段假 / B 段真），两条都必须以
                #   `scope=prev` 取证**探针那一行**（产品日志 `信息探针 INFO探针 …`）。
                #   ★★ 第 106 轮实测修正：产品探针格式**没有等号**
                #     （`组[0]:s112[OR]+s114[OR]假`，见 SAQ_QuestCond.cpp 的 `组[{}]:{}{}`）
                #     —— 首跑两条用例 FAIL 就是断言多写了一个 `=`（正则永不匹配；同批
                #     探针输出本身全对，与第 83 轮 r80 半角括号同族）。断言必须照抄产品格式。
                all_ok &= check("用例计划 · r106 INFO OR 组断言（A：组为假）",
                                plan_text.encode(),
                                "assert.log 信息探针 .*组\\[0\\]:s112\\[OR\\]\\+s114\\[OR\\]假 scope=prev".encode())
                all_ok &= check("用例计划 · r106 INFO OR 组断言（B：组为真）",
                                plan_text.encode(),
                                "assert.log 信息探针 .*组\\[0\\]:s112\\[OR\\]\\+s114\\[OR\\]真 scope=prev".encode())
                all_ok &= check("用例计划 · r106 info.probe 步骤存在",
                                plan_text.encode(), "info.probe 0x001C7185".encode())
                #   反向检查（第 106 轮修正防回退）：步骤行里不许再出现「多一个等号」的
                #   旧写法（`…[OR]=真/假`）。★ 只扫 `step =` 行（第 103 轮的教训）——
                #   注释里解释「为什么没有等号」的那几句话不该把这条检查顶红。
                bad_info_or_eq = bool(re.search(r"(?m)^\s*step\s*=.*OR\\\]=.*$", plan_text))
                print(("MISS " if bad_info_or_eq else "OK  ") +
                      " 用例计划 · r106 探针断言不再多写等号（反向检查，第 106 轮）")
                all_ok &= not bad_info_or_eq
                # 反向检查：INFO OR 组不许「见第一条 kFail 即停」的旧写法残留 ——
                #   DLL 侧特征（`不再「找第一条 kFail 即停」` 的说明字符串不在二进制里）
                #   由离线单测 + 用例钉死；这里只挡注释文档层面的旧说法。
                gone = "INFO 侧条件复用 StaticCondGate 结构 ⇒ 第 6 元恒 0".encode() \
                    not in plan_text.encode()
                print(("OK  " if gone else "MISS") +
                      " 用例计划 · 旧「INFO 第 6 元恒 0」说明已替换(反向检查)")
                all_ok &= gone
                #   反向检查④（第 103 轮）：不许再用 `assert.nolog 链式没到:.*另一边` ——
                #   「链式没到」是**累积名单**：本用例前面必然打过一行「另一边 被藏」
                #   （预热后它的三条边都没触发）⇒ 必然假 FAIL（第 103 轮改判的直接产物）。
                #   ★ 只扫**步骤行**（`step = …`）：注释里解释「为什么不用它」的那句话
                #     不该把这条反向检查顶红（第 103 轮实现时踩过一次）。
                bad_nolog_mqin = bool(re.search(
                    r"(?m)^\s*step\s*=\s*assert\.nolog\s+链式没到:\.\*另一边", plan_text))
                print(("MISS " if bad_nolog_mqin else "OK  ") +
                      " 用例计划 · 不再用「链式没到 无 另一边」的反向断言（反向检查，第 103 轮）")
                all_ok &= not bad_nolog_mqin
                # ★★ 第 101 轮补丁：FAIL 现场的第一证据 = 只读探针（直读引擎的
                #   IsStageDone，与链式判定同源）—— 两条边都必须带着它跑，
                #   否则下一轮实测又只能看「零变化」。
                all_ok &= check("用例计划 · r101 探针步骤（quest.probe 直读引擎，B 段）",
                                plan_text.encode(),
                                "quest.probe ~0x00030C2B 100 4000".encode())
                all_ok &= check("用例计划 · r101 探针步骤（quest.probe 直读引擎，对照段）",
                                plan_text.encode(),
                                "quest.probe ~0x00035E1C 100 1600".encode())
                all_ok &= check("用例计划 · r101 对照边用例（MQ05@1600）",
                                plan_text.encode(),
                                "quest.stage ~0x00035E1C 1600".encode())
                # ★★★ 第 102 / 103 轮：二期两条边的**构造前提**（预热）与断言链 ——
                #   预热步骤（MQ_Shell@100）→ `stageDone(100)=1`（预热成立）→
                #   `stageDone(1600/4000)=1` + MQIN `stageDone(10)=1`（目标边落到引擎 +
                #   fragment 顺手把 MQIN 起了）→ `ui.select` 命中（产品放行）。
                #   这些检查就是「防下次又被改回不可达的写法」。
                all_ok &= check("用例计划 · r101 预热步骤（MQ_Shell@100，B 段）",
                                plan_text.encode(),
                                "quest.stage ~0x00035E1B 100".encode())
                all_ok &= check("用例计划 · r101 预热成立的断言（stageDone(100)=1，B 段）",
                                plan_text.encode(),
                                "assert.log quest\\.probe 0x[0-9A-F]{2}030C2B：.*stageDone\\(100\\)=1".encode())
                all_ok &= check("用例计划 · r101 目标边落到引擎的断言（stageDone(4000)=1）",
                                plan_text.encode(),
                                "assert.log quest\\.probe 0x[0-9A-F]{2}030C2B：.*stageDone\\(4000\\)=1".encode())
                all_ok &= check("用例计划 · r101 预热成立的断言（stageDone(100)=1，对照段）",
                                plan_text.encode(),
                                "assert.log quest\\.probe 0x[0-9A-F]{2}035E1C：.*stageDone\\(100\\)=1".encode())
                all_ok &= check("用例计划 · r101 目标边落到引擎的断言（stageDone(1600)=1）",
                                plan_text.encode(),
                                "assert.log quest\\.probe 0x[0-9A-F]{2}035E1C：.*stageDone\\(1600\\)=1".encode())
                all_ok &= check("用例计划 · r101 fragment 起了 MQIN 的判据（stageDone(10)=1）",
                                plan_text.encode(),
                                "assert.log quest\\.probe 0x[0-9A-F]{2}10AAD5：.*stageDone\\(10\\)=1".encode())
                all_ok &= check("用例计划 · r98 预热段的探针（宿主是否被 fragment 启动）",
                                plan_text.encode(),
                                "quest.probe ~0x00030C2B 100".encode())
                # 反向检查③（第 102 轮；第 103 轮复核后仍然有效）：不许再出现**没有预热**
                #   的直接推宿主写法 —— 实测 `Reset+Start+SetStage` 对 MQ03/MQ05 零效果，
                #   探针 `未开始 + stageDone(…)=0`（第 103 轮定性：这两条主线任务的
                #   「首次启动」要经 MQ_Shell 的开场 fragment，且同一会话里只会成功一次）；
                #   留着直接写法只会制造假 FAIL。
                bad_r101_direct = ("quest.start ~0x00030C2B" in plan_text
                                   or "quest.start ~0x00035E1C" in plan_text)
                print(("MISS " if bad_r101_direct else "OK  ") +
                      " 用例计划 · r101 不再直接 Start 主线宿主（反向检查，第 102 轮）")
                all_ok &= not bad_r101_direct
                # 反向检查①：二期用例里同样不许写死运行期 FormID（必须 `~0x…` 记录号）。
                bad_r101_fid = ("quest.reset 0x0110AAD5" in plan_text
                                or "quest.stage 0x01030C2B" in plan_text)
                print(("MISS " if bad_r101_fid else "OK  ") +
                      " 用例计划 · r101 DLC 用例用 ~0x 记录号（反向检查）")
                all_ok &= not bad_r101_fid
                # 反向检查②：**不许**把「有意不收」的三处写进用例（防以后被误加回来）：
                #   · `DialogueHVDazra`（调试入口，8 条城市支线）
                #   · `SFBGS001_VKaiZ03a` / `VkaiZ03b`（结局分支互启环）
                #   · `SFTER_MQIntro`（线的入口 —— 挂了会永远被藏）
                bad_unwanted = any(s in plan_text for s in (
                    "quest.reset ~0x0002FD76", "quest.reset ~0x0003DB1D",
                    "quest.reset ~0x00040788", "quest.reset ~0x000059A0"))
                print(("MISS " if bad_unwanted else "OK  ") +
                      " 用例计划 · r101 不碰「有意不收」的任务（反向检查）")
                all_ok &= not bad_unwanted
                # ★★ 第 65 轮（任务专属图标）：r65 用例的图标断言必须走**界面报告**
                #   （assert.ui —— icon= 字段是 SAQ_Report 的实时值，比日志断言更直接）。
                all_ok &= check("用例计划 · r65 图标断言（assert.ui icon=）",
                                plan_text.encode(), "assert.ui icon=\\[0x".encode())
                # ★★ 第 67 轮：r67 用例的两条链式门槛断言
                #   （A：前置没做 ⇒ 菜鸟觐见被藏；B：推进前置后放行）。
                all_ok &= check("用例计划 · r67 链式门槛断言（链式没到 + 菜鸟觐见）",
                                plan_text.encode(), "assert.log 链式没到: .*菜鸟觐见".encode())
                all_ok &= check("用例计划 · r67 前置推进后放行（assert.nolog）",
                                plan_text.encode(), "assert.nolog 链式没到:.*菜鸟觐见".encode())
                # ★★ 第 68 轮（15:24 会话 r67_chain 的唯一 FAIL = **用例自己的正则写错**，
                #   产品侧全对：`链式门槛=22(过0/藏22/未知0)` 那行在 15:23:26.672 就打了、
                #   名单里有「菜鸟觐见」）。两个写法红线：
                #   ① 正则里只写**单**反斜杠（`\\d` 在 ECMAScript 下 = 字面反斜杠 + d ⇒ 永不匹配）；
                #   ② 统计行（`链式门槛=…`）在推送前若干毫秒打印 ⇒ 断言要 `scope=case`
                #      （`scope=prev` 的窗口起点 = 上一步开始，实测差 3 ms 漏掉）。
                all_ok &= check("用例计划 · r67 链式门槛统计断言（scope=case + 单反斜杠）",
                                plan_text.encode(),
                                "assert.log 链式门槛=\\d+\\(过\\d+/藏\\d+/未知\\d+ scope=case".encode())
                bad_esc = "assert.log 链式门槛=\\\\d+" in plan_text
                print(("MISS" if bad_esc else "OK  ") +
                      " 用例计划 · 旧的双反斜杠写法已修（反向检查）")
                all_ok &= not bad_esc
                # ★★ 第 69 轮（链式门槛扩展边）：r69 两条用例的断言 ——
                #   A：前置没做 ⇒「展示力量」在「链式没到」名单里（scope=case：统计行在推送前打印）；
                #   B：推进「面试」@500 后 ⇒ 本条用例窗口里名单没有「展示力量」。
                all_ok &= check("用例计划 · r69 扩展链式边断言（展示力量被藏）",
                                plan_text.encode(),
                                "assert.log 链式没到: .*展示力量\\[0x00226527 scope=case".encode())
                all_ok &= check("用例计划 · r69 扩展链式边放行断言（assert.nolog）",
                                plan_text.encode(),
                                "assert.nolog 链式没到:.*展示力量 scope=case".encode())
                # ★★ 第 71 轮（链式门槛全量入边审计）：r71 三条用例的断言。
                #   ★ 17:04 会话实测修正（第 72 轮）：「遗产的结局」被 **INFO 门槛先藏**
                #   （对话条件引用前置 0x00178B1E 未完成）⇒ 不进链式判定、不在
                #   「链式没到」名单里 —— 旧断言（只在链式名单里找它）期望不可达、
                #   假 FAIL（产品全对）。断言按「被任一门槛藏」写 + 反向检查挡旧写法。
                all_ok &= check("用例计划 · r71 CF 四条断言（链式没到 · 宝藏号的结局）",
                                plan_text.encode(),
                                "assert.log 链式没到: .*宝藏号的结局\\[0x001B41D0 scope=case".encode())
                all_ok &= check("用例计划 · r71 遗产的结局断言（任一门槛藏 INFO|链式）",
                                plan_text.encode(),
                                "assert.log (INFO没到|链式没到): .*遗产的结局\\[0x001EF7F1 scope=case".encode())
                gone = "assert.log 链式没到: .*遗产的结局\\[0x001EF7F1" not in plan_text
                print(("OK  " if gone else "MISS") +
                      " 用例计划 · 旧「遗产的结局只在链式名单」写法已替换(反向检查)")
                all_ok &= gone
                # ★ 第 72 轮（r65_icons 实测）：原「记录性核对：选中深藏不露」退役 ——
                #   深藏不露的启动边（UC02@860 → CF01）收进链式门槛后，存档没开深红
                #   舰队线时它被藏（ui.select 报 notfound = 修复生效，不是用例缺陷）。
                #   ★★ 第 75 轮更新：深藏不露升格为「四大势力开头任务」后**又会显示**
                #   （固定显示）—— 同一句 `ui.select 0x00009136` 在 r75 用例里**是正当的**
                #   ⇒ 反向检查收窄到 **r65_icons 这一段**（它不该再选中深藏不露：
                #   黑色舰队图标帧的正确性由离线图标映射表保证）。
                i65 = plan_text.find("[case:r65_icons]")
                i65_end = plan_text.find("[case:", i65 + 1) if i65 >= 0 else -1
                r65_sec = plan_text[i65:i65_end if i65_end > i65 else len(plan_text)] if i65 >= 0 else ""
                gone = "0x00009136" not in r65_sec
                print(("OK  " if gone else "MISS") +
                      " 用例计划 · r65 旧「选中深藏不露」记录步骤已退役(反向检查，只看 r65 段)")
                all_ok &= gone
                # 反向检查：15:43 会话里那条未知步骤 `ui.state`（老驱动器只 WARN + 丢步 ⇒ 用例
                #   照样 PASS）已删；新驱动器对解析失败直接判 FAIL（见 SAQ_Test.cpp v69）。
                gone_state = "step = ui.state" not in plan_text
                print(("OK  " if gone_state else "MISS") +
                      " 用例计划 · 未知步骤 ui.state 已删（反向检查）")
                all_ok &= gone_state
                # ★★ 第 68 轮：**通用守卫** —— 用例里每条断言的日志正则都必须能编译、
                #   且不许出现连续两个反斜杠（`\\d` / `\\[` 这类过度转义 = 永远匹配不上；
                #   静默失败最坏的一面是**反向断言假 PASS**）。这一条把整类错挡在构建期。
                bad_asserts = []
                for ln in plan_text.splitlines():
                    s = ln.strip()
                    for op in ("assert.log ", "assert.nolog "):
                        if not s.startswith("step = " + op):
                            continue
                        pat = s[len("step = " + op):]
                        pat = re.split(r"\s+(?:scope|timeout)=", pat)[0].strip()
                        if "\\\\" in pat:
                            bad_asserts.append("过度转义（双反斜杠）：" + pat)
                            continue
                        try:
                            re.compile(pat)
                        except re.error as exc:
                            bad_asserts.append(f"正则非法（{exc}）：" + pat)
                ok_asserts = not bad_asserts
                print(("OK  " if ok_asserts else "MISS") +
                      " 用例计划 · 断言正则全部可编译且无过度转义")
                for item in bad_asserts:
                    print("         - " + item)
                all_ok &= ok_asserts
                # ★★ 第 83 轮（22:52 会话 r80 的唯一 FAIL）：断言把产品日志里的**全角** `）`
                #   写成**半角转义** `\)` —— 正则合法（上面的编译校验查不出）、但永不匹配；
                #   症状是同第 68 轮 `\\d` 那类：「日志里没出现 /…/」的超时（看着像产品
                #   没打这行）。全角括号**不需要**转义（正向检查见上面 r80 那条）。
                #   通用的体检见 tools/test/plan_regex_audit.py（拿真实日志逐条试跑）。
                bad_paren = "可重复 NPC 8\\)" in plan_text
                print(("MISS" if bad_paren else "OK  ") +
                      " 用例计划 · r80 旧的全角/半角括号混写已修（反向检查）")
                all_ok &= not bad_paren
                # ★★ 第 83 轮（22:52 会话 r81 的 `ui.tab` FAIL = 桥没通）：r81 的**两段**
                #   都要「先等推送成功再切 tab」（第 57 轮红线）—— 判据：r81 段里
                #   `assert.log 推送成功` 出现 ≥2 次（第一段本来就有，第二段是本轮补的）。
                i81 = plan_text.find("[case:r81_landmark]")
                i81_end = plan_text.find("[case:", i81 + 1) if i81 >= 0 else -1
                sec81 = plan_text[i81:i81_end if i81_end > i81 else len(plan_text)] if i81 >= 0 else ""
                ok81 = sec81.count("assert.log 推送成功") >= 2
                print(("OK  " if ok81 else "MISS") +
                      " 用例计划 · r81 两段都「等推送成功再切 tab」（第 57 轮红线）")
                all_ok &= ok81
                # ★★ 第 87 轮（进度门槛 OR 组）：r87 两条用例的判据 ——
                #   ① A 段：UC04 完成 + Z04/Z05 都没做 ⇒ 「亲爱的姐妹」在「进度没到」名单
                #      （★ 旧实现只看 UC04 ⇒ 会放行 —— 这条断言正是新旧语义的差异点）；
                #   ② B 段：补做 Z04（complete 0x002149FA）⇒ 名单里没有它（本条用例窗口内）；
                #   ③ 反向：A 段不得写成 `assert.nolog`（那就测不出「被藏」）。
                all_ok &= check("用例计划 · r87 A 段（OR 组不满足 -> 被藏）",
                                plan_text.encode(),
                                "assert.log 进度没到: .*亲爱的姐妹\\[0x002117CA scope=case".encode())
                all_ok &= check("用例计划 · r87 B 段（补做 Z04 -> 放行）",
                                plan_text.encode(),
                                "assert.nolog 进度没到: .*亲爱的姐妹\\[0x002117CA scope=case".encode())
                i87 = plan_text.find("[case:r87_or_group]")
                i87b = plan_text.find("[case:r87_or_group_pass]")
                ok87 = (i87 >= 0 and i87b > i87
                        and "quest.complete 0x002149FA" in plan_text[i87b:])
                print(("OK  " if ok87 else "MISS") +
                      " 用例计划 · r87 两条都在 + B 段补做 Z04（complete 0x002149FA）")
                all_ok &= ok87
                # ★★ 第 90 轮（DLC 可重复任务）：r90 的两条判据 ——
                #   ① DLC 任务在**两个 op 家族**里都用 `~0x…` 记录号（`quest.complete` /
                #      `ui.select`）—— 写成运行期 FormID 会因加载顺序变化指错记录（第 17 轮
                #      同款坑：本机 SFBGS00D 序号 0x0B，换机器就不是它）；
                #   ② 豁免名单断言容忍 DLC 加载顺序前缀，只钉 8 位 UID 的尾段（2A418）。
                all_ok &= check("用例计划 · r90 DLC 任务用记录号（quest.complete ~0x0002A418）",
                                plan_text.encode(), "quest.complete ~0x0002A418".encode())
                all_ok &= check("用例计划 · r90 豁免名单断言（职业杀手，容忍 DLC 前缀）",
                                plan_text.encode(),
                                "assert.log 可重复保留: .*职业杀手\\[0x[0-9A-F]+2A418 scope=case".encode())
                # ★★ 第 93 轮（2026-09-22 复跑复查 · 第三次实测）：r89/r90 的判据定稿 ——
                #   「在玩家日志里 + 已完成」这个状态在本引擎**构造不出来**：任务完成即从
                #   玩家日志移除（两轮「先 start 再 complete / 加 qdata 断言」的假设都被
                #   现场否掉；整份日志 rptk= 非零值 = 0 次；C++ 侧 `已完成` 计数 2→3 证明
                #   complete 生效）。⇒ 删除 `assert.ui qdata` 与 `assert.ui rptk` 断言，
                #   显示层证据改为 **ui.tab + ui.select 命中**（切到「可接任务」tab 后能
                #   选中它 = 真的还在列表里）。判据：
                #   ① 段内有 `ui.tab`（不切 tab 会停在原版任务列表 ⇒ select 必 notfound）；
                #   ② 段内有 `ui.select <uid>`（记录号 `~0x…` 写法原样保留）；
                #   ③ 段内**不得**再出现 qdata/rptk 断言（防回退：那两条断言的测试目标
                #   在本引擎不可达，写回去就是注定的假 FAIL）。
                for cid, uid in (("r89_repeatable", "0x00224FE8"),
                                 ("r90_dlc_repeatable", "~0x0002A418")):
                    i = plan_text.find(f"[case:{cid}]")
                    i_end = plan_text.find("[case:", i + 1) if i >= 0 else -1
                    sec = plan_text[i:i_end if i_end > i else len(plan_text)] if i >= 0 else ""
                    steps = [ln.strip() for ln in sec.splitlines()
                             if ln.strip().startswith("step =")]
                    ok93 = ("step = ui.tab" in steps
                            and f"step = ui.select {uid}" in steps
                            and not any(s.startswith("step = assert.ui qdata") for s in steps)
                            and not any(s.startswith("step = assert.ui rptk") for s in steps))
                    print(("OK  " if ok93 else "MISS") +
                          f" 用例计划 · {cid} ui.tab + ui.select 显示层证据（第 93 轮定稿）")
                    all_ok &= ok93
                # ★★ 第 96 轮（可重复任务分组 —— 玩家反馈）：r96 用例的三条判据 ——
                #   ① `rq=` 探针（SaqRepeatableQuestProbe）报的可重复任务**显示名**
                #      带「（可重复）」前缀（前缀真的进了渲染字段 sName）；
                #   ② `order=` 的 `|tail=` 段（本 tab 最后两行）带「（可重复）」——
                #      「整组排在列表末尾」的运行期证据；
                #   ③ C++ 统计行带「排在末尾N」（分组真的执行了）。
                all_ok &= check("用例计划 · r96 显示名前缀断言（assert.ui rq=）",
                                plan_text.encode(),
                                "assert.ui rq=\\[\\d+\\|0x[0-9a-f]+=（可重复）".encode())
                all_ok &= check("用例计划 · r96 整组在末尾断言（order= 的 |tail= 段）",
                                plan_text.encode(),
                                "assert.ui order=\\[.*\\|tail=0x[0-9a-f]+=（可重复）".encode())
                all_ok &= check("用例计划 · r96 C++ 统计（排在末尾）",
                                plan_text.encode(),
                                "assert.log 可重复任务=\\d+\\(已完成保留\\d+｜排在末尾[1-9]".encode())
                plan_deployed = MO2_MOD / "SFSE/Plugins/SAQ_TestPlan.txt"
                if plan_deployed.exists():
                    same = plan_deployed.read_bytes() == plan_src.read_bytes()
                    print(("OK  " if same else "MISS") +
                          " 用例计划 · MO2 部署副本与工作区一致（部署未落后）")
                    all_ok &= same
                else:
                    print(f"MISS 用例计划 · MO2 部署副本不存在：{plan_deployed}")
                    all_ok = False
                # ★ 第 55 轮：smoke 的三条「上一步副作用」断言必须带 `scope=prev` ——
                #   09:06 会话的假失败就是漏写它（「引导请求」行其实打了，只是落在
                #   断言窗口起点之前 —— 动作与它的日志常在同一次 Tick）。
                all_ok &= check("用例计划 · smoke 引导请求断言带 scope=prev",
                                plan_text.encode(), "assert.log 引导请求： scope=prev".encode())
                gone = "引导请求： timeout=" not in plan_text
                print(("OK  " if gone else "MISS") +
                      " 用例计划 · 旧「引导请求」断言（不带 scope）已替换(反向检查)")
                all_ok &= gone
                # ★★ 第 56 轮：smoke 的「脚本已应用」断言必须**不带裸「引导确认」** ——
                #   「引导确认：菜单还开着」只是说「还没应用、不会判失败」，不是证据；
                #   09:22 会话这一条就是靠在整段缓冲里翻到它才过的（假 PASS）。
                all_ok &= check("用例计划 · smoke 引导已生效断言（不带裸「引导确认」）",
                                plan_text.encode(),
                                "assert.log 引导已生效|引导延迟生效 scope=prev".encode())
                gone = "引导已生效|引导延迟生效|引导确认" not in plan_text
                print(("OK  " if gone else "MISS") +
                      " 用例计划 · 旧宽松断言（带裸「引导确认」）已替换(反向检查)")
                all_ok &= gone
                # ★★ 第 57 轮：三条实测修正的用例侧判据 —— 防「改回旧写法」再犯：
                #   ① r47 切 tab 前必须等「推送成功」（否则撞上内嵌回退数据 202 条、
                #      不含任务板入口 ⇒ ui.selectchild 报 err|notfound）；
                #   ② r26 的 `引导确认：菜单还开着` 用 scope=case（与上一条断言同批行，
                #      scope=prev 的窗口会被上一条断言消耗掉 —— 实测假 FAIL）；
                #   ③ r48 的 `INFO没到:` 用 scope=case（统计与名单在**同一行**，同理）。
                all_ok &= check("用例计划 · r47 切 tab 前等推送成功（scope=case）",
                                plan_text.encode(), "assert.log 推送成功 scope=case".encode())
                all_ok &= check("用例计划 · r26 引导确认断言（scope=case）",
                                plan_text.encode(),
                                "assert.log 引导确认：菜单还开着 scope=case".encode())
                all_ok &= check("用例计划 · r48 INFO没到断言（scope=case）",
                                plan_text.encode(),
                                "assert.log INFO没到: .*无凭无据\\[0x00082D5A scope=case".encode())
                gone = ("引导确认：菜单还开着 scope=prev" not in plan_text
                        and "无凭无据\\[0x00082D5A scope=prev" not in plan_text)
                print(("OK  " if gone else "MISS") +
                      " 用例计划 · 旧的 scope=prev 写法（同批行断言）已替换(反向检查)")
                all_ok &= gone
                # ★★ 第 60 轮：r45 尾段改判（真因见文件头）—— 防「改回不可达的旧期望」再犯：
                #   ① 走远后仍用只读探针 `guide.probe` 记候选可得性（进结果 JSON，可对账）；
                #   ② 尾段判「不许早降级 + 引导仍指向精确候选 [1]」—— 不再要求
                #      「候选复算：…先保持」（走远并不会让目标取不到；那半段需要读档/加载
                #      窗口才能触发，等「自动读档」落地后补用例）。
                all_ok &= check("用例计划 · r45 候选可得性探针（guide.probe）",
                                plan_text.encode(), "guide.probe ~0x0008EBDC".encode())
                all_ok &= check("用例计划 · r45 走远后判「引导仍指向 [1]」",
                                plan_text.encode(),
                                "assert.log 引导状态：营救机器人.*候选 \\[1\\]「G型」".encode())
                gone = "assert.log 候选复算：.*先保持" not in plan_text
                print(("OK  " if gone else "MISS") +
                      " 用例计划 · 旧「先保持」断言（需读档窗口，不可达）已替换(反向检查)")
                all_ok &= gone
                # ★★ 第 74 轮（同伴好感度任务）：r74 用例的三条断言 ——
                #   ① 固定显示统计行（`同伴固定=N(其中M条被门槛判「进度没到」但放行)`）；
                #   ② 入口任务在名单里且名字带同伴前缀（「巴雷特：违约」0x000369AB）；
                #   ③ 「后续」（承诺任务「巴雷特：承诺」0x001C7185）照旧在链式名单里
                #      （= 没被固定显示放行 —— 玩家要求「只显示入口任务」）。
                all_ok &= check("用例计划 · r74 同伴固定统计断言",
                                plan_text.encode(),
                                "assert.log 同伴固定=\\d+\\(其中\\d+条被门槛判".encode())
                all_ok &= check("用例计划 · r74 入口任务名单断言（名字带同伴前缀）",
                                plan_text.encode(),
                                "assert.log 同伴固定名单: .*巴雷特：违约\\[0x000369AB".encode())
                all_ok &= check("用例计划 · r74 后续任务仍走链式门槛断言",
                                plan_text.encode(),
                                "assert.log 链式没到: .*巴雷特：承诺\\[0x001C7185".encode())
                #   ★★ 第 74 轮续（「把它们放在一起」）：④ 分组前置 —— 日志统计 +
                #   界面顺序探针（`order=` 的第一条必须是 4 条入口同伴任务之一）。
                all_ok &= check("用例计划 · r74 同伴分组前置统计断言",
                                plan_text.encode(),
                                "assert.log 同伴分组前置=\\d+\\(按同伴分组".encode())
                #   ★★ 第 75 轮变更：两类「固定显示」条目都在最前 —— 首条是四大势力开头
                #   任务或入口同伴任务之一（精确的「前四条 = 四个势力任务」见 r75 用例）。
                all_ok &= check("用例计划 · r74 界面顺序探针断言（order= 首条为固定显示条目）",
                                plan_text.encode(),
                                "assert.ui order=\\[0x(2c5401|29a8f0|2c9c97|9136|21ecd0|369ab|263262|2c7c11)".encode())
                # ★★ 第 75 轮（四大势力开头任务）：r75 用例的四条判据 ——
                #   ① 固定显示统计行（`势力入口固定=4(其中N条被门槛判「进度没到」但放行)`）
                #      + 名单里有「超越极限」/「深藏不露」（后者带「跳过门槛」）；
                #   ② 固定排前四：日志统计 + 界面 `order=` 探针的**前四条**精确匹配；
                #   ③ 「简要说明」真的进了描述（`pin=` 探针）；
                #   ④ 「深藏不露」按 R 只给「暂无导航目标」提示（不可引导也要提示玩家）。
                all_ok &= check("用例计划 · r75 势力入口固定统计断言",
                                plan_text.encode(),
                                "assert.log 势力入口固定=4\\(其中\\d+条被门槛判".encode())
                all_ok &= check("用例计划 · r75 名单含「超越极限」与「深藏不露」",
                                plan_text.encode(),
                                "assert.log 势力入口固定名单: .*深藏不露\\[0x00009136".encode())
                all_ok &= check("用例计划 · r75 固定排前四（order= 前四条精确）",
                                plan_text.encode(),
                                "assert.ui order=\\[0x2c5401,0x29a8f0,0x2c9c97,0x9136".encode())
                all_ok &= check("用例计划 · r75 说明进描述（pin= 探针）",
                                plan_text.encode(),
                                "assert.ui pin=\\[0x2c5401=加入联合殖民地先锋队".encode())
                all_ok &= check("用例计划 · r75 深红舰队不可导航提示",
                                plan_text.encode(),
                                "assert.ui guide=\\d+\\|\\d+\\|该任务暂无导航目标:深藏不露".encode())
                #   ★★ 第 91 轮（不可导航提示更明显）：同一条用例新增一条判据 ——
                #     `nonav=` 探针里深藏不露的**显示名**带「（不可导航）」前缀
                #     （SaqNotNavigableProbe 报的是 sName = 列表渲染字段 —— 前缀真的
                #     进了显示名的运行期证据）；而上面那条提示语断言必须在**不改名**
                #     的前提下继续过（前缀不该污染「该任务暂无导航目标:…」——
                #     名字走 SaqBaseName 剥前缀）。两条一起 = 显示名带前缀 + 提示报原名。
                all_ok &= check("用例计划 · r91 不可导航前缀断言（nonav= 探针）",
                                plan_text.encode(),
                                "assert.ui nonav=\\[\\d+\\|.*0x9136=（不可导航）深藏不露".encode())
                # ★★ 第 77 轮（龙神线后续 · 「RIR 留专项」收口）：A/B 两条 ——
                #   A：玩家只接了入口任务 ⇒「人生处处有意外」（0x002A8319，玩家报告的那条）
                #      在「链式没到」名单里（连同其余五条后续）；
                #   B：推进「挑拨离间」@600 ⇒ 它不再被藏（「或」语义），其余仍被藏。
                all_ok &= check("用例计划 · r77 龙神后续被藏（人生处处有意外 0x002A8319）",
                                plan_text.encode(),
                                "assert.log 链式没到: .*人生处处有意外\\[0x002A8319".encode())
                all_ok &= check("用例计划 · r77 前置推进后放行（assert.nolog）",
                                plan_text.encode(),
                                "assert.nolog 链式没到:.*人生处处有意外".encode())
                #   ★★ 第 79 轮：这条断言（「领先一步」0x002C572B 在链式名单里）曾因
                #   **名单打印上限**（kMaxSamples = 40）不可达 —— 它是表内顺序最后 3 条
                #   之一（前 40 名之外）。修法是日志侧的「未列出摘要」（见下面 DLL 检查），
                #   断言本身保持原样（它同时钉住「截断留痕别被删掉」）。
                all_ok &= check("用例计划 · r77 领先一步断言（依赖未列出摘要，表内顺序第 60）",
                                plan_text.encode(),
                                "assert.log 链式没到: .*领先一步\\[0x002C572B".encode())
                # ★★ 第 78 轮（DLC 的 INFO 门槛）：断言 = 统计行（scope=case，周期行红利）
                #   + 两条地球舰队后续在「INFO没到」名单里。
                #   ★ 不写 FormID：DLC 的运行期 FormID 依赖加载顺序（高字节会变）。
                all_ok &= check("用例计划 · r78 DLC INFO 门槛统计（scope=case）",
                                plan_text.encode(),
                                "assert.log INFO门槛=\\d+\\(过\\d+/藏\\d+/放行\\d+/未知\\d+ scope=case".encode())
                all_ok &= check("用例计划 · r78 DLC 后续被藏（失踪的华庭号）",
                                plan_text.encode(),
                                "assert.log INFO没到: .*失踪的华庭号 scope=case".encode())
                #   ★ r71 用例的修正（第 75 轮）：CF01 升格为固定显示 ⇒ 它**不该**再出现在
                #   「链式没到」名单里（否则「固定显示」没生效）；这条反向断言同时是
                #   「两类名单必须分行」那条纪律的落点（见 DLL · FormatPinStats）。
                all_ok &= check("用例计划 · r71「深藏不露」不再进链式名单（反向断言）",
                                plan_text.encode(),
                                "assert.nolog 链式没到:.*深藏不露".encode())
                # ★★ 第 80 轮（可重复 NPC 入口）：r80 用例的三条判据 ——
                #   ① DLL 两类计数（`入口条目表=20 条（任务板 12 + 可重复 NPC 8）`）；
                #   ② 界面 `rep=` 探针（8 条 + 名字前缀「（可重复）」进了载荷/解析）；
                #   ③ 点邓肯·林奇 ⇒ 引导目标 = **精确目标**（第 84 轮改判：原板 / marker
                #      二选一 —— 见下面的说明）。
                #   ★★ 第 83 轮修正（22:52 会话这条断言的唯一 FAIL）：产品那行是**全角**
                #      `（…）`，用例原来写成半角转义 `\)` ⇒ 正则合法但**永不匹配**；
                #      同时把窗口从 `scope=prev` 改成 `scope=case`（该行由 menu.open 同一次
                #      Tick 的产品处理打印，窗口基准在个别时序下会落在它之后）。
                all_ok &= check("用例计划 · r80 NPC 两类计数断言（全角括号 + scope=case）",
                                plan_text.encode(),
                                "assert.log 入口条目表=20 条（任务板 12 \\+ 可重复 NPC 8） scope=case".encode())
                all_ok &= check("用例计划 · r80 界面 rep= 探针断言（8 条 + 名字前缀）",
                                plan_text.encode(),
                                "assert.ui rep=\\[8\\|0x214684=（可重复）贸易管理局 · 邓肯·林奇".encode())
                #   ★★ 第 84 轮改判（06:11 会话这条是唯一 FAIL，产品全对）：实测产品落
                #      「**任务板自身（精确）**」（引用 0x00214684 = NPC 本人）—— 候选链
                #      是「精确优先」（① 条目引用自身 → ② 新建常驻 marker；第 31 轮起），
                #      而 8 位 NPC 是活体引用、运行期可得（同一会话
                #      `入口=20(可导航 20｜marker 10 原板 10 兜底 0 不可用 0)` 从头恒定）
                #      ⇒ 落原板比 marker 更精确、更好。旧断言写死 marker = 假 FAIL。
                #      ⇒ 判据放宽为「**精确目标二选一**（原板 / marker；兜底才是异常）」；
                #      marker 链路仍由 `入口=…(marker N…兜底 0 不可用 0)` 覆盖（r47 的断言）。
                all_ok &= check("用例计划 · r80 精确目标二选一断言（原板 / marker）",
                                plan_text.encode(),
                                "林奇.*(任务板自身（精确）|新建常驻 marker（精确）)".encode())
                bad_old = "林奇.*新建常驻 marker（精确） scope=prev" in plan_text
                print(("MISS" if bad_old else "OK  ") +
                      " 用例计划 · r80 旧「必须 marker」写法已放宽(反向检查)")
                all_ok &= not bad_old
                # ★★ 第 81 轮（地球地标任务）：r81 用例的三条判据 ——
                #   ① 阿波罗地标任务能选中（条目真的进了列表）；
                #   ② 按 R ⇒ 引导落**第 2 候选 = 同 cell 常驻兜底 0x0008C3E8**
                #      （第 1 候选是陋室里的书，非常驻 ⇒ 站远处取不到）；
                #   ③ 伦敦地标任务「只给说明」⇒ 按 R 只给「暂无导航目标」提示。
                all_ok &= check("用例计划 · r81 地标条目可选中",
                                plan_text.encode(), "ui.select 0x00026EB0".encode())
                all_ok &= check("用例计划 · r81 引导落常驻兜底断言",
                                plan_text.encode(),
                                "assert.log 引导请求：阿波罗地标任务（0x00026EB0）→ 引用 0x0008C3E8.*候选 \\[2/4\\]".encode())
                all_ok &= check("用例计划 · r81 伦敦只给说明断言",
                                plan_text.encode(),
                                "assert.ui guide=\\d+\\|\\d+\\|该任务暂无导航目标:伦敦地标任务".encode())
                #   ★ 第 80 轮更新：r47 的入口统计从 12 → **20**（任务板 12 + NPC 8）——
                #   反向钉住「改回 12」的回归（NPC 条目静默消失时这条会 MISS）。
                all_ok &= check("用例计划 · r47 入口统计 20 条（含第 80 轮 NPC）",
                                plan_text.encode(),
                                "assert.log 入口=20\\(可导航 20｜marker".encode())
                # ★★ 第 62 轮（大项 I）：自动读档用例 —— ① 只允许用**用户指定的那个存档**
                #   （子串 ★ 第 101 轮切到 Exit0 → ★★★ 第 103 轮切到 Save1）；② 读档步骤在；
                #   ③ 存档列表诊断在；④ **与部署 ini 的 [Test] AutoLoad 一致**（见下）。
                all_ok &= check("用例计划 · r62 自动读档（指定存档）",
                                plan_text.encode(),
                                "save.load Save1_FDBB7678M54696D6D6568_000034_20260922142854_2_0_4".encode())
                all_ok &= check("用例计划 · r62 存档列表诊断步骤",
                                plan_text.encode(), "save.list".encode())
                # ★★★ 第 101 轮（测试存档切换）：r62 的指定存档必须与**部署 ini** 的
                #   `[Test] AutoLoad` 指的是同一个存档 —— 不然「自动读 A、用例读 B」，
                #   两边状态不同、判据互相打架还看不出来。AutoLoad 为空（关自动读档）时不查。
                _ini_deployed = MO2_MOD / "SFSE/Plugins/SAQ_ShowAvailableQuests.ini"
                if _ini_deployed.exists():
                    _ini_txt = _ini_deployed.read_text(encoding="utf-8", errors="replace")
                    _m_al = re.search(r"(?mi)^\s*AutoLoad\s*=\s*(.+?)\s*$", _ini_txt)
                    _al = (_m_al.group(1) if _m_al else "").strip()
                    _m_sl = re.search(r"(?mi)^\s*step\s*=\s*save\.load\s+(\S+)", plan_text)
                    _sl = (_m_sl.group(1) if _m_sl else "").strip()
                    if not _al:
                        print("OK   用例计划 · 部署 ini 未开自动读档（AutoLoad 空 ⇒ 不查一致性）")
                    else:
                        _same_save = (_sl.lower() == _al.lower()
                                      or _sl.lower() in _al.lower()
                                      or _al.lower() in _sl.lower())
                        print(("OK  " if _same_save else "MISS") +
                              f" 用例计划 · r62 指定存档与部署 ini AutoLoad 一致"
                              f"（{_sl} vs {_al}）")
                        all_ok &= _same_save
            else:
                print(f"MISS 缺少用例计划 {plan_src}")
                all_ok = False
        # ★★ 第 55 轮（09:06 会话实测的两个星图收口）：这两条属于**产品路径**
        #   （SAQ.cpp），开发/发布两种构建里都在 —— 不能放进 HARNESS_STRINGS
        #   （那张表在发布模式是反向检查，放进去会误报「发布包里带测试代码」）。
        #   ① 星图已打开时把通道标回普通状态（防「未被脚本消费的重试请求（状态 6/7）」
        #      在星图关闭后又被执行一次 —— 玩家看到星图自己又弹一回）；
        #   ② 换候选重试的等待窗口 1.5 s → 3 s（脚本实测窗口 1.6~2.5 秒，1.5 s 会假重试）。
        all_ok &= check("DLL · 星图残留请求回收", blob,
                        "防残留的星图请求在星图关闭后再执行一次".encode())
        all_ok &= check("DLL · 星图重试等待窗口文案", blob, "后仍没有才考虑换候选重试".encode())
        # ★★ 第 84 轮（06:11 会话复查：22 条用例 21 PASS / 1 FAIL，唯一 FAIL 在用例侧、
        #   产品全对；但新发现一个**更严重的问题** —— 结果 JSON 含非法 UTF-8 ⇒
        #   `check_results.py` 退出码 2，22 条用例的结果一条也读不出来 = 判据通道失效）：
        #   ① 产品（DLL，两种构建里都在 ⇒ 不能放进 HARNESS_STRINGS —— 那是发布模式的
        #      反向检查表，放进去会被误判「发布包里带测试代码」）：
        #      · 日志/结果的截断改走 `Decision::Utf8SafeCut`（切点回退到字符首字节）——
        #        实测 `EscapeForLog(报告, 900)` 把「追踪者联盟」切成 `追踪` + 半个 `者`；
        #        「界面状态」报告上限同时 900 → 1500（icon=/order=/pin=/rep= 探针后，
        #        900 字节会在 qdata 名单中间截断）；
        #      · 指针诊断的 RTTI 抄录只留可打印 ASCII（旧实现把随机字节写进日志：
        #        非法 UTF-8 + 控制字符把一行诊断劈成好几行）。
        #      下面这行是**启动自检串**：实机日志出现它 ⇒ 跑的是第 84 轮之后的 DLL。
        all_ok &= check("DLL · 证据通道自检串（第 84 轮）", blob,
                        "证据通道：日志/结果截断按 UTF-8 字符边界（第 84 轮）".encode())
        #   ② 判据通道的工具/单测（文件级检查 —— 「修了但没提交/没同步」也能挡住）：
        #      · 结果检查器的非法 UTF-8 容错（一处坏字节不再让整份报告读不出来）；
        #      · 离线层单测覆盖 `Utf8SafeCut`（切点边界语义，毫秒级可回归）。
        tool_src = ROOT / "tools/test/check_results.py"
        if tool_src.exists():
            all_ok &= check("结果检查器 · 非法 UTF-8 容错（errors=replace）",
                            tool_src.read_bytes(), b'errors="replace"')
        else:
            print(f"MISS 缺少 {tool_src}")
            all_ok = False
        tests_src = ROOT / "plugin/tests/SAQ_DecisionTests.cpp"
        if tests_src.exists():
            all_ok &= check("离线层单测 · UTF-8 截断用例（Utf8SafeCut）",
                            tests_src.read_bytes(), b"Utf8SafeCut")
        else:
            print(f"MISS 缺少 {tests_src}")
            all_ok = False
        # ★★ 第 79 轮（名单截断留痕 —— r77 的「领先一步」断言不可达的真因）：
        #   四个名单（进度 / INFO / 链式 / 隐藏）此前把超出打印上限（kMaxSamples = 40）
        #   的条目**静默丢弃** ⇒ 日志里「被藏」看起来像「没被藏」（本次会话
        #   r77_chain_ryujin 的唯一 FAIL 即由此而来：复查证明产品判据全对 ——
        #   43 条 kFail，只是表内顺序最后 3 条（通行是关键 / 全新的故事 / 领先一步）
        #   被 40 条上限截掉，断言 `链式没到: .*领先一步[0x002C572B` 因此不可达）。
        #   现在超出的条目以紧凑形式（名字 + FormID）追加在各自名单之后：
        #   `（另有 N 条未列出：…）` —— 断言对截断区同样可达，日志也不再骗人。
        all_ok &= check("DLL · 名单截断留痕（未列出摘要）", blob, "条未列出".encode())
        all_ok &= check("DLL · 名单截断留痕（另有文案）", blob, "另有".encode())
        # 反向检查：第 55 轮把「结束时…」文案统一成了「用例收尾：…」（收尾从
        #   「全部用例结束」提前到「每条用例结束」，旧文案不该再出现）。
        gone = "结束时菜单还开着".encode() not in blob and "结束时星图还开着".encode() not in blob
        print(("OK  " if gone else "MISS") + " DLL · 旧「结束时…」收尾文案已替换(反向检查)")
        all_ok &= gone
        # ★ 第 17 轮的核心判据：DLC 的两个 + 基础游戏一共 4 个数据源名都编进了 DLL
        for master in (b"Starfield.esm", b"ShatteredSpace.esm", b"SFBGS050.esm", b"SFBGS00D.esm"):
            all_ok &= check(f"DLL · 数据源 {master.decode()}", blob, master)
        # 反向检查：第 17 轮删掉的 DNAM 诊断行不应再出现
        gone = "DNAM 位分布".encode() not in blob
        print(("OK  " if gone else "MISS") + " DLL · DNAM 诊断已移除(反向检查)")
        all_ok &= gone
        # 反向检查：第 16 轮删掉的无用自检不应再出现
        gone = "formArrays[类型=数量]".encode() not in blob
        print(("OK  " if gone else "MISS") + " DLL · 旧自检已移除(反向检查)")
        all_ok &= gone
        # ★ 第 53 轮（大项 F · 发布就绪）：MO2 部署副本必须与工作区**字节一致** ——
        #   第 50 轮的教训：游戏进程加载的是「部署那一刻的产物」，构建了但没部署 =
        #   玩家跑的还是旧的（当时排查半天，最后靠 usvfs 日志才定性）。
        mo2_dll = MO2_MOD / "SFSE/Plugins/SAQ_ShowAvailableQuests.dll"
        if mo2_dll.exists():
            same = mo2_dll.read_bytes() == blob
            print(("OK  " if same else "MISS") +
                  " DLL · MO2 部署副本与工作区一致（部署未落后）")
            all_ok &= same
        else:
            print(f"MISS DLL · MO2 部署副本不存在：{mo2_dll}")
            all_ok = False
    else:
        print(f"MISS 缺少 DLL {dll}")
        all_ok = False

    pex = ROOT / "scripts/build/SAQ_Main.pex"
    if pex.exists():
        blob = pex.read_bytes()
        all_ok &= check("PEX · 重挂自愈", blob, "脚本重挂且引导目标仍在".encode())
        # 第 19 轮：菜单事件 Trace（DLL 侧「脚本活性探测」的 Papyrus 佐证）
        all_ok &= check("PEX · 菜单事件 Trace", blob, "[SAQ] 菜单打开".encode())
        # 第 21 轮：引导目标高位属性（与 ESM VMAD 绑定对应）
        all_ok &= check("PEX · 引导目标高位属性", blob, b"GuidePrefix")
        # ★ 第 37 轮：SET COURSE 打开星图（OpenStarMapFor 的 Trace + 引擎原生函数名）
        all_ok &= check("PEX · 星图请求 Trace", blob, "星图请求".encode())
        all_ok &= check("PEX · 原生星图函数调用", blob, b"ShowGalaxyStarMapMenuAndPlotToLocation")
        # ★ 第 38 轮：星图目的地的「行星诊断」+「父地点链兜底」（第 38 轮新增的两段文案）
        all_ok &= check("PEX · 星图行星诊断", blob, "，行星=".encode())
        all_ok &= check("PEX · 父地点 API", blob, b"GetParentLocations")
        all_ok &= check("PEX · 行星 API", blob, b"GetCurrentPlanet")
        # ★ 第 40 轮：三个地点候选 + 逐候选诊断（地点链 / 采用地点 / 候选号 / 行星地点）
        all_ok &= check("PEX · 地点链日志", blob, "星图请求：父地点[".encode())
        all_ok &= check("PEX · 采用地点诊断", blob, "采用地点=".encode())
        all_ok &= check("PEX · 候选号诊断", blob, "候选号=".encode())
        all_ok &= check("PEX · 行星地点 API", blob, b"GetLocation")
        all_ok &= check("PEX · 地点候选属性", blob, b"StarMapPendingMode")
        # ★★ 第 42 轮：星图延时请求的**过期校验** —— 延时窗口里玩家换了引导（或取消）时
        #   不能把上一条任务的航线开出来（玩家反馈「导航目标不是悬停那条」的脚本侧根因）。
        all_ok &= check("PEX · 星图过期校验 Trace", blob, "星图请求已过期".encode())
        all_ok &= check("PEX · 当前目标 FormID 助手", blob, b"CurrentGuideTargetFormID")
        all_ok &= check("PEX · 待开星图目标 FormID", blob, b"StarMapPendingFormID")
        # ★★ 第 44 轮：星图待办改由**轮询节拍**推进（原来那个 1.5 秒的延时定时器实测
        #   三次按 R 一次都没跑到 —— 星图被界面侧 dispatch 提前打开 ⇒ 暂停 ⇒ 冻结）。
        all_ok &= check("PEX · 星图节拍待办", blob, b"StarMapPendingTicks")
        all_ok &= check("PEX · 星图待办处理函数", blob, b"ProcessStarMapPending")
        all_ok &= check("PEX · 星图节拍文案", blob, "下一个轮询节拍".encode())
        # ★★ 第 45 轮补丁：星图无法定位（目标在飞船内/动态内部地点）⇒ 不打开星图 +
        #   发一条 HUD 通知如实说明（中英双语，脚本侧判定「地点链无行星」）。
        all_ok &= check("PEX · 不在星图上的早退 Trace", blob, "目标地点不在星图上".encode())
        all_ok &= check("PEX · 不在星图上的通知", blob, b"not on the star map")
        # ★★ 第 45 轮补丁 2（玩家反馈「提示消失太快」）：引擎的 HUD 通知单条只停 ~2 秒，
        #   Papyrus 改不了 ⇒ 同一条文案再发 2 次、间隔 ~2 秒（轮询节拍驱动），总覆盖约 6 秒。
        #   ★ 第 46 轮把这两个变量/函数从「星图专用」升级为**通用**（HUD 提示槽位）。
        all_ok &= check("PEX · 提示重复函数", blob, b"ProcessNotice")
        all_ok &= check("PEX · 提示重复间隔", blob, b"StarMapNoticeInterval")
        all_ok &= check("PEX · 提示重复 Trace", blob, "HUD 提示已补发".encode())
        all_ok &= check("PEX · 提示统一入口", blob, b"ShowNotice")
        all_ok &= check("PEX · 提示文案函数", blob, b"GuideNoticeText")
        # ★★ 第 46 轮（大项 B）：目标尚未加载 —— 脚本如实提示玩家（可重复 3 次）
        #   + 失败 Trace 节流 + 提示冷却（DLL 每 10~60 秒自动重试一次，不能每次都弹）。
        all_ok &= check("PEX · 目标未加载提示", blob, "目标地点尚未加载".encode())
        all_ok &= check("PEX · 提示冷却属性", blob, b"GuideNoticeCooldownTicks")
        all_ok &= check("PEX · 失败次数节流", blob, b"GuideFailCount")
        # ★★ 第 49 轮（引擎内 harness）：脚本侧的测试命令执行器 ——
        #   DLL 写命令 → 这里执行（Quest.Reset/Start/SetStage/CompleteQuest、Actor.MoveTo）
        #   → 写回执。写侧动作用**语言级 API**（不经原生函数指针，见 docs/04 的调用约定）。
        all_ok &= check("PEX · 测试通道就绪 Trace", blob, "测试通道已就绪".encode())
        all_ok &= check("PEX · 测试命令 Trace", blob, "测试命令：seq=".encode())
        all_ok &= check("PEX · 测试通道不可用提示", blob, "测试通道不可用".encode())
        all_ok &= check("PEX · 写侧-完成", blob, b"CompleteQuest")
        all_ok &= check("PEX · 写侧-推阶段", blob, b"SetStage")
        all_ok &= check("PEX · 写侧-传送", blob, b"MoveTo")
        # 反向检查：第 40 轮把「地点自己没有行星，改用父地点」并入候选链诊断，旧串不应再出现
        gone = "地点自己没有行星，改用父地点".encode() not in blob
        print(("OK  " if gone else "MISS") + " PEX · 旧父地点兜底文案已替换(反向检查)")
        all_ok &= gone
        # 反向检查：第 46 轮把「星图专用」的提示机制改成通用（HUD 提示槽位）——
        #   旧函数名 / 旧变量不应再出现在 PEX 里。
        gone = (b"ProcessStarMapNotice" not in blob and b"StarMapNoticeLeft" not in blob
                and "不在星图上的提示已重复".encode() not in blob)
        print(("OK  " if gone else "MISS") + " PEX · 旧星图专用提示机制已替换(反向检查)")
        all_ok &= gone
    else:
        print(f"MISS 缺少 PEX {pex}")
        all_ok = False

    # ★ 第 35 轮（★★ 第 87 轮更新）：进度门槛的**数据侧**校验（生成物
    #   plugin/src/SAQ_QuestTable.h）—— 7 条 gated 任务 / **11 条条件**
    #   （含 FFConstantZ06 的 2 条 OR 组条件；第 86/87 轮引擎语义见 docs/08 4.3）。
    #   数据链：tools/esm/analyze_ctda.py → ctda_gates.json → gen_quest_table.py。
    table_h = ROOT / "plugin/src/SAQ_QuestTable.h"
    if table_h.exists():
        blob = table_h.read_text(encoding="utf-8")
        for name, needle in {
            "门槛结构 StaticCondGate": "struct StaticCondGate",
            "门槛枚举 kCondStageDone": "kCondStageDone = 2",
            "★ 第 87 轮 OR 位字段": "orBit;",
            "★ 第 87 轮 OR 组行(Z04, orBit=1)": "{ 0x002149FAu, 0u, 1u, 1u, 0u, 1u }",
            "★ 第 87 轮 OR 组行(Z05, orBit=1)": "{ 0x0021261Eu, 0u, 1u, 1u, 0u, 1u }",
            "被检查任务 UC04(0x2AAE8D)": "0x002AAE8D",
            "被检查任务 UC01(0x2C5401)": "0x002C5401",
            "被检查任务 Botany02(0x27071B)": "0x0027071B",
            "被检查任务 City_Neon_Gang03(0x2250C4)": "0x002250C4",
        }.items():
            ok = needle in blob
            print(("OK  " if ok else "MISS") + f" 静态表 · {name}")
            all_ok &= ok
        # ★ 第 87 轮：kQuestConds 段必须是 **6 列**格式（行尾 orBit），
        #   且 OR 组条件恰好 2 条（FFConstantZ06 的 Z04/Z05）。
        import re as _re
        q_start = blob.find("kQuestConds[] = {")
        q_end = blob.find("};", q_start) if q_start >= 0 else -1
        q_blob = blob[q_start:q_end] if (q_start >= 0 and q_end > q_start) else ""
        q_rows = _re.findall(
            r"\{ 0x([0-9A-F]{8})u, (\d+)u, (\d+)u, (\d+)u, (\d+)u, (\d+)u \},", q_blob)
        ok = len(q_rows) == 11
        print(("OK  " if ok else "MISS") +
              f" 静态表 · 进度门槛行 6 列格式且恰 11 行（实测 {len(q_rows)}）")
        all_ok &= ok
        n_or = sum(1 for r in q_rows if r[5] == "1")
        ok = n_or == 2
        print(("OK  " if ok else "MISS") + f" 静态表 · OR 组条件恰 2 条（实测 {n_or}）")
        all_ok &= ok
        key = "kQuestCondCount = "
        idx = blob.find(key)
        n = 0
        if idx >= 0:
            digits = ""
            for ch in blob[idx + len(key):]:
                if ch.isdigit():
                    digits += ch
                else:
                    break
            n = int(digits) if digits else 0
        ok = n == 11
        print(("OK  " if ok else "MISS") + f" 静态表 · 门槛计数 == 11（kQuestCondCount = {n}）")
        all_ok &= ok

        # ★★ 第 45 轮：引导目标**候选池**（多候选链）—— 数据侧完整性（不只是特征串）：
        #   ① 结构/数组存在；② 候选计数 > 0；③ 任务表的切片 (candBegin+candCount)
        #   全部不越界、且有目标任务数与实测对齐；④ 旧单目标字段已移除。
        #   ★★ 第 75 轮：有目标任务 209 → **208**、候选 931 → **924** ——
        #   「深红舰队·深藏不露」（CF01）按玩家要求「只保留简要说明」，
        #   生成期**故意清空**它的 7 个引导候选（见 gen_quest_table.py 的候选循环）。
        def _num_after(text: str, k: str) -> int:
            i = text.find(k)
            if i < 0:
                return -1
            digits = ""
            for ch in text[i + len(k):]:
                if ch.isdigit():
                    digits += ch
                else:
                    break
            return int(digits) if digits else -1

        for name, needle in {
            "候选池结构 StaticGuideCandidate": "struct StaticGuideCandidate",
            "候选池数组 kGuideCandidates": "kGuideCandidates[] = {",
        }.items():
            ok = needle in blob
            print(("OK  " if ok else "MISS") + f" 静态表 · {name}")
            all_ok &= ok
        cand_total = _num_after(blob, "kGuideCandidateCount = ")
        n_with = 0
        n_oob = 0
        t0 = blob.find("kQuestTable[] = {")
        t1 = blob.find("kQuestTableSize")
        region = blob[t0:t1] if 0 <= t0 < t1 else ""
        for m in re.finditer(
                r"\{\s*0x([0-9A-F]+)u,\s*(\d+)u,\s*(\d+)u,\s*0x([0-9A-F]+)u,"
                r"\s*(\d+)u,\s*(\d+)u,\s*(\d+)u,\s*(\d+)u,", region):
            begin, count = int(m.group(5)), int(m.group(6))
            if count:
                n_with += 1
                if cand_total >= 0 and begin + count > cand_total:
                    n_oob += 1
        #   ★★ 第 81 轮（地球地标任务）：候选 924 → **960**、有目标任务 208 → **217**
        #   （+10 条地标任务；其中 9 条各 4 个候选（书/书商 + 3 兜底）= +36 候选，
        #   伦敦那条只给说明 ⇒ 0 候选 —— 所以有目标数是 +9 而不是 +10）。
        ok = cand_total > 200 and n_with == 217 and n_oob == 0
        print(("OK  " if ok else "MISS") +
              f" 静态表 · 候选池完整（候选 {cand_total} 条 / 有目标任务 {n_with}（第 81 轮起 217）"
              f" / 切片越界 {n_oob}）")
        all_ok &= ok
        gone = "guideRefLocal" not in blob and "guideRefMaster" not in blob
        print(("OK  " if gone else "MISS") + " 静态表 · 旧单目标字段已移除(反向检查)")
        all_ok &= gone
        # ★★ 第 47 轮（大项 C）：同 cell 常驻兜底候选 —— 数据侧完整性：
        #   ① 「全部候选都非常驻」的任务（76 条）里 56 条补到了常驻兜底 ⇒ 候选总数
        #      875 → 931、常驻候选 283 → 339；
        #   ② 实测样本「营救机器人」（0x0008EBDC）的候选切片 = 2 条：第 1 条是非常驻的
        #      「G型」（Model G），第 2 条 = 常驻的 0x08ECA6（距目标 3.3 米的
        #      「损坏 Model G 家具标记」—— 玩家在远处点引导时命中的就是它）。
        c0 = blob.find("kGuideCandidates[] = {")
        c1 = blob.find("kGuideCandidateCount")
        cand_region = blob[c0:c1] if 0 <= c0 < c1 else ""
        c_rows = re.findall(r"\{\s*0x([0-9A-F]+)u,\s*(\d+)u,\s*0x([0-9A-F]+)u,\s*(\d+)u,", cand_region)
        n_persist = sum(1 for r in c_rows if int(r[2], 16) & 0x01)
        ok = n_persist >= 330
        print(("OK  " if ok else "MISS") +
              f" 静态表 · 常驻兜底候选已并入（候选 {len(c_rows)} 条，其中常驻 {n_persist} 条）")
        all_ok &= ok
        m_row = re.search(
            r"\{\s*0x0008EBDCu,\s*\d+u,\s*\d+u,\s*0x[0-9A-F]+u,\s*(\d+)u,\s*(\d+)u,", blob)
        ok_slice = False
        if m_row and len(c_rows) > 0:
            begin, cnt = int(m_row.group(1)), int(m_row.group(2))
            if cnt == 2 and begin + 2 <= len(c_rows):
                first, second = c_rows[begin], c_rows[begin + 1]
                ok_slice = (first[0] == "08ECA5" and (int(first[2], 16) & 0x01) == 0
                            and second[0] == "08ECA6" and (int(second[2], 16) & 0x01) == 1)
        print(("OK  " if ok_slice else "MISS") +
              " 静态表 · 营救机器人兜底链（0x08ECA5 非常驻 → 0x08ECA6 常驻）")
        all_ok &= ok_slice
        # ★★ 第 54 轮：把第 45 轮的**判据本身**落成离线检查（harness 的 r45 用例覆盖
        #   「预选/升级/降级观察期」的运行时行为；「首选候选的质量」是纯数据事实，
        #   离线查更稳 —— 玩家实测抱怨的那两条任务必须有「有名字的 NPC」当第一候选，
        #   而不是 EnableMarker / HeadlockMarker 这类内部落脚点）：
        #     · 平衡账目 0x0000351A：[1] 阿香（0x05797D）
        #     · 群众心态 0x00063F4C：[1] 弗兰克斯卡·摩尔（0x19B086）
        # 带名字的候选行（第 5 组 = nameZh）—— 匹配到 `}` 为止（不吞下一行的 `{`）
        c_full = re.findall(
            r"\{\s*0x([0-9A-F]+)u,\s*(\d+)u,\s*0x([0-9A-F]+)u,\s*(\d+)u,\s*\"([^\"]*)\"\s*\}",
            cand_region)
        first_ok = {}
        for local, want_name, want_ref in (("0000351A", "阿香", "05797D"),
                                           ("00063F4C", "弗兰克斯卡·摩尔", "19B086")):
            m = re.search(
                r"\{\s*0x" + local + r"u,\s*\d+u,\s*\d+u,\s*0x[0-9A-F]+u,\s*(\d+)u,\s*(\d+)u,", blob)
            hit = False
            if m and len(c_full) > 0:
                begin = int(m.group(1))
                if begin < len(c_full):
                    row = c_full[begin]
                    hit = (row[0].upper() == want_ref and row[4] == want_name)
            first_ok[local] = hit
        ok_first = all(first_ok.values())
        print(("OK  " if ok_first else "MISS") +
              " 静态表 · 第 45 轮首选候选质量（平衡账目[1]=阿香 / 群众心态[1]=弗兰克斯卡·摩尔）"
              + ("" if ok_first else f" ← {first_ok}"))
        all_ok &= ok_first
        # 反向检查：这两个 EnableMarker 不该再当第一候选（第 45 轮玩家实测的抱怨形态）
        bad_first = any(r[4] in ("FFNeonZ09_EnableRef", "FFNeonZ08_HeadlockEnableMarker001")
                        for r in c_full[:1] + c_full[47:48])
        print(("OK  " if not bad_first else "MISS") +
              " 静态表 · 旧「EnableMarker 当首选」形态已替换(反向检查)")
        all_ok &= not bad_first

        # ★★ 第 48 轮（大项 D）：INFO 门槛（对话侧条件）—— 数据侧完整性：
        #   ① 结构/数组存在；② 计数与**数据源**对齐（第 78 轮起不写死：基础游戏 60 条
        #   之外又并入 DLC —— SFBGS00D 2 / SFBGS050 7 / ShatteredSpace 11）；
        #   ③ 全部对话与全部任务的切片不越界；④ 有门槛任务数 = 数据源条数；
        #   ⑤ 实测样本「大器晚成」（0x00270717）的门槛 = 「孤立无援」（0x0027071B）完成；
        #   ⑥ 第 78 轮新增样本：DLC 的跨 master 前置（失踪的华庭号 ← 地球舰队侵袭@75、
        #      栉比堡垒 ← 破碎空间 LC06@940）。
        for name, needle in {
            "INFO 门槛结构 StaticInfoGroup": "struct StaticInfoGroup",
            "INFO 门槛数组 kInfoGroups": "kInfoGroups[] = {",
            "INFO 条件数组 kInfoConds": "kInfoConds[] = {",
        }.items():
            ok = needle in blob
            print(("OK  " if ok else "MISS") + f" 静态表 · {name}")
            all_ok &= ok
        info_cond_total = _num_after(blob, "kInfoCondCount = ")
        info_group_total = _num_after(blob, "kInfoGroupCount = ")
        g0 = blob.find("kInfoGroups[] = {")
        g1 = blob.find("kInfoGroupCount")
        g_region = blob[g0:g1] if 0 <= g0 < g1 else ""
        g_rows = re.findall(r"\{\s*(\d+)u,\s*(\d+)u\s*\},", g_region)
        n_oob_g = sum(1 for a, b in g_rows if int(a) + int(b) > info_cond_total)
        n_info_tasks = 0
        n_oob_t = 0
        for m in re.finditer(
                r"\{\s*0x[0-9A-F]+u,\s*\d+u,\s*\d+u,\s*0x[0-9A-F]+u,"
                r"\s*\d+u,\s*\d+u,\s*\d+u,\s*\d+u,\s*(\d+)u,\s*(\d+)u,", region):
            begin, count = int(m.group(1)), int(m.group(2))
            if count:
                n_info_tasks += 1
                if info_group_total >= 0 and begin + count > info_group_total:
                    n_oob_t += 1
        #   ★★ 第 78 轮：期望值改为从 ref/info_gates_final.json **现算**（DLC 并入门槛后
        #   条数会变；写死会掩盖漏跑生成器的情形 —— 与链式门槛同一纪律）。
        exp_tasks = exp_groups = exp_conds = None
        igp = ROOT / "ref" / "info_gates_final.json"
        if igp.exists():
            ig_data = json.loads(igp.read_text(encoding="utf-8"))
            exp_tasks = len(ig_data)
            exp_groups = sum(len(t["infos"]) for t in ig_data)
            exp_conds = sum(len(i["conds"]) for t in ig_data for i in t["infos"])
        ok = (exp_conds is not None and info_cond_total == exp_conds
              and len(g_rows) == exp_groups and n_oob_g == 0
              and n_info_tasks == exp_tasks and n_oob_t == 0)
        print(("OK  " if ok else "MISS") +
              f" 静态表 · INFO 门槛完整（对话 {len(g_rows)}/{exp_groups} 条 / "
              f"条件 {info_cond_total}/{exp_conds} 条 / 有门槛任务 {n_info_tasks}/{exp_tasks} / "
              f"切片越界 {n_oob_g + n_oob_t}）")
        all_ok &= ok
        m_bot = re.search(
            r"\{\s*0x00270717u,\s*\d+u,\s*\d+u,\s*0x[0-9A-F]+u,"
            r"\s*\d+u,\s*\d+u,\s*\d+u,\s*\d+u,\s*(\d+)u,\s*(\d+)u,", blob)
        ok_bot = False
        if m_bot:
            gb, gc = int(m_bot.group(1)), int(m_bot.group(2))
            if gc == 1 and gb + 1 <= len(g_rows):
                cc = int(g_rows[gb][1])
                if cc == 1:
                    ok_bot = re.search(
                        r"\{\s*0x0027071Bu,\s*0u,\s*1u,\s*1u,\s*0u,\s*0u\s*\},", blob) is not None
        print(("OK  " if ok_bot else "MISS") +
              " 静态表 · 大器晚成 INFO 门槛（孤立无援 0x0027071B 完成）")
        all_ok &= ok_bot
        # ★★ 第 78 轮（DLC 的 INFO 门槛）：两个跨 master 样本 ——
        #   ① 失踪的华庭号（SFTER_MQ01）← 地球舰队侵袭（SFTER_MQIntro，master 2）@75 完成；
        #   ② 栉比堡垒（SFBGS001_MQ06）← 破碎空间 LC06（master 3）@940 完成。
        #   （这两条就在 kInfoConds 里，形态 = { 记录号, master, check, want, stage, orBit }。）
        for label, needle in (
                ("失踪的华庭号 ← 地球舰队侵袭@75（master 2）", "{ 0x0000599Fu, 2u, 2u, 1u, 75u, 0u },"),
                ("栉比堡垒 ← 破碎空间 LC06@940（master 3）", "{ 0x0001D3C6u, 3u, 2u, 1u, 940u, 0u },"),
        ):
            hit = needle in blob
            print(("OK  " if hit else "MISS") + f" 静态表 · DLC INFO 门槛样本（{label}）")
            all_ok &= hit

        # ★★★ 第 106 轮（operator 全量产品化）：INFO 门槛的条件**带 OR 位** ——
        #   ① 计数与数据源对齐（kInfoConds 里 orBit=1 的条数 = info_gates_final
        #      的 or_bit 条件数）；② 样本：巴雷特：违约（0x000369AB）的对话
        #      [StageDone(0x001C7187,12)==1[OR], StageDone(...,14)==1] ——
        #      12 那条 orBit=1（本次修正：旧实现只提取无 OR 位的 14 那条 ⇒ 会算错
        #      OR 语义）；③ 反向检查：旧「INFO 侧第 6 元恒 0」注释文案已替换。
        i0 = blob.find("kInfoConds[] = {")
        i1 = blob.find("kInfoCondCount")
        i_region = blob[i0:i1] if 0 <= i0 < i1 else ""
        i_rows = re.findall(
            r"\{\s*0x([0-9A-Fa-f]+)u,\s*(\d+)u,\s*(\d+)u,\s*(\d+)u,\s*(\d+)u,\s*(\d+)u\s*\},", i_region)
        n_ib_or = sum(1 for r in i_rows if r[5] == "1")
        exp_or = (sum(1 for t in ig_data for i in t["infos"] for c in i["conds"]
                      if c.get("or_bit")) if exp_conds is not None else -1)
        ok = (exp_or > 0 and n_ib_or == exp_or)
        print(("OK  " if ok else "MISS") +
              f" 静态表 · INFO 门槛 OR 位（{n_ib_or}/{exp_or} 条）")
        all_ok &= ok
        ok = "{ 0x001C7187u, 0u, 2u, 1u, 12u, 1u }," in blob
        print(("OK  " if ok else "MISS") + " 静态表 · INFO 门槛 OR 位样本（巴雷特：违约 @12）")
        all_ok &= ok
        gone = "第 6 元恒 0" not in blob     # blob 是 str（table_h.read_text）—— 别加 .encode()
        print(("OK  " if gone else "MISS") + " 静态表 · 旧「INFO 侧第 6 元恒 0」注释已替换(反向检查)")
        all_ok &= gone

        # ★★★ 第 106 轮（覆盖面全量复盘）：补收的 7 条「无 QTYP 但完整」漏收任务 ——
        #   ① ref/extra_quests.json 的每一条都在表里（按记录号 + itype 对齐）；
        #   ② 链式样本：阴阳两隔（0x00002FAE）的边 = Com_Companion_Barrett@208；
        #   ③ 无前置的 2 条（防御措施 / 登陆不顺）chainCount = 0。
        ex_path = ROOT / "ref" / "extra_quests.json"
        ex_ok = True
        n_ex = 0
        if ex_path.exists():
            ex_data = json.loads(ex_path.read_text(encoding="utf-8"))
            ex_entries = ex_data.get("entries", []) if isinstance(ex_data, dict) else ex_data
            n_ex = len(ex_entries)
            for e in ex_entries:
                loc = int(e["local"], 16) if isinstance(e["local"], str) else int(e["local"])
                # 表里的 FormID 是 8 位十六进制（0x00002FAEu）—— 别用 %06X。
                if not re.search(r"\{\s*0x%08Xu,\s*\d+u,\s*%du," % (loc, int(e.get("itype", 3))),
                                 blob):
                    print(f"MISS 静态表 · 补收任务 0x{loc:06X} {e['edid']} 不在表里")
                    ex_ok = False
        print(("OK  " if ex_ok else "MISS") + f" 静态表 · 补收任务 {n_ex} 条全在表里（无 QTYP 人工名单）")
        all_ok &= ex_ok
        ok_edge = "{ 0x001C7187u, 0u, 208u }," in blob
        print(("OK  " if ok_edge else "MISS") +
              " 静态表 · 补收链式边样本（阴阳两隔 ← Com_Companion_Barrett@208）")
        all_ok &= ok_edge
        for loc, nm in ((0x21625F, "防御措施"), (0x1A8B64, "登陆不顺")):
            m_nc = re.search(
                r"\{\s*0x%08Xu,\s*\d+u,\s*\d+u,\s*0x[0-9A-Fa-f]+u,"
                r"\s*\d+u,\s*\d+u,\s*\d+u,\s*\d+u,\s*\d+u,\s*\d+u,\s*\d+u,\s*(\d+)u," % loc, blob)
            ok_nc = bool(m_nc) and int(m_nc.group(1)) == 0
            print(("OK  " if ok_nc else "MISS") + f" 静态表 · 补收无前置任务 chainCount=0（{nm}）")
            all_ok &= ok_nc

        # ★★ 第 67 轮：任务链门槛（编号任务链的启动边）—— 数据侧完整性：
        #   ① 结构/数组存在；② 边数/有边任务数与**两个数据源**（编号链 + 第 69 轮的扩展边）
        #   对齐（去重后）/ 切片不越界；③ 实测样本：CF02「菜鸟觐见」（0x000192D2）的唯一边 =
        #   CF01「深藏不露」（0x00009136）@ stage 1000（玩家反馈的那条链）。
        #   ★★ 第 69 轮：期望值不再写死 —— 从 ref/quest_chain.json + ref/quest_chain_extra.json
        #   现算（合并去重），数据一变这里就跟着变（写死会掩盖漏跑生成器的情形）。
        for name, needle in {
            "链式门槛结构 StaticChainGate": "struct StaticChainGate",
            "链式门槛数组 kChainGates": "kChainGates[] = {",
            "扩展链式边数据 (ref/quest_chain_extra.json)": "quest_chain_extra",
            # ★★★ 第 98 轮：DLC 的链式启动边（官方 .pex 反编译取证）——
            #   数据文件必须在（它是 gen_quest_table 的输入；缺了说明管线跑漏了）。
            "DLC 链式边数据 (ref/quest_chain_dlc.json)": "quest_chain_dlc",
        }.items():
            if name.startswith("扩展链式边"):
                p = ROOT / "ref" / "quest_chain_extra.json"
                ok = p.exists()
            elif name.startswith("DLC 链式边"):
                p = ROOT / "ref" / "quest_chain_dlc.json"
                ok = p.exists()
            else:
                ok = needle in blob
            print(("OK  " if ok else "MISS") + f" 静态表 · {name}")
            all_ok &= ok

        def _expected_chain_edges() -> tuple[int, int, set[tuple[int, int, int]]]:
            """(边数, 有边任务数, {(目标记录号, 宿主记录号, 宿主stage)})。

            ★ 数据源里的边**不是全部进表**（如 MQ106/MQ302b/MQ402 这类主线任务不在
            「可接任务」表里；宿主 master 不在表内的边也会被生成器跳过）⇒ 期望值要先按
            「目标在表内 + 宿主是基础游戏」过滤，才能和 kChainGates 对得上。
            ★★ 第 74 轮：**三个**数据源 —— 编号链（quest_chain.json）+ 扩展边
            （quest_chain_extra.json）+ **同伴「后续」任务的启动边**
            （companion_quests.json 的 followUpGate：承诺任务只能由好感度里程碑启动，
            并入链式门槛 ⇒ 前置没到不显示 —— 玩家要求「只显示入口任务」）。
            ★★★ 第 98 轮：**四个**数据源 —— 再加 DLC 的启动边（quest_chain_dlc.json，
            官方 .pex 反编译取证）。两处口径与生成器对齐：
              · 宿主 master 只要在「全部 quest 的 master 集合」里就收（不再限定
                Starfield.esm）—— DLC 边全是跨 master 的；
              · 表行里 `formid` 是**文件内 FormID**（DLC 带自己的 master 前缀，
                如 0x010116C7），而 kChainGates 的对账集合用的是**记录号**
                （kQuestTable 行的首列）⇒ 期望集合要用 local。
            """
            tbl = json.loads((ROOT / "ref" / "quest_table_debug.json").read_text(encoding="utf-8"))
            table_formids = {int(t["formid"]) for t in tbl}
            local_of = {int(t["formid"]): int(t["local"]) & 0xFFFFFF for t in tbl}
            masters: set[str] = set()
            qp = ROOT / "ref" / "quests_all.json"
            if qp.exists():
                masters = {(q.get("master") or "Starfield.esm")
                           for q in json.loads(qp.read_text(encoding="utf-8"))}
            if not masters:
                masters = {(t.get("master") or "Starfield.esm") for t in tbl}
            merged: dict[int, set[tuple[int, int]]] = {}
            for fn in ("quest_chain.json", "quest_chain_extra.json", "quest_chain_dlc.json"):
                p = ROOT / "ref" / fn
                if not p.exists():
                    continue
                for t in json.loads(p.read_text(encoding="utf-8")):
                    if int(t["formid"]) not in table_formids:
                        continue
                    for e in t.get("edges", []):
                        if (e.get("host_master") or "Starfield.esm") not in masters:
                            continue
                        merged.setdefault(local_of[int(t["formid"])], set()).add(
                            (int(e["host_local"]) & 0xFFFFFF, int(e["host_stage"])))
            cp = ROOT / "ref" / "companion_quests.json"
            if cp.exists():
                for g in json.loads(cp.read_text(encoding="utf-8")):
                    for q in g.get("quests", []):
                        fg = q.get("followUpGate")
                        if not fg or int(q["formid"]) not in table_formids:
                            continue
                        if (fg.get("hostMaster") or "Starfield.esm") not in masters:
                            continue
                        merged.setdefault(local_of[int(q["formid"])], set()).add(
                            (int(fg["hostLocal"]) & 0xFFFFFF, int(fg["hostStage"])))
            n_edges = sum(len(v) for v in merged.values())
            return n_edges, len(merged), {(t, h, s) for t, v in merged.items() for (h, s) in v}

        exp_edges, exp_tasks, exp_set = _expected_chain_edges()
        chain_total = _num_after(blob, "kChainGateCount = ")
        c0 = blob.find("kChainGates[] = {")
        c1 = blob.find("kChainGateCount")
        c_region = blob[c0:c1] if 0 <= c0 < c1 else ""
        c_rows = re.findall(r"\{\s*0x([0-9A-F]+)u,\s*(\d+)u,\s*(\d+)u\s*\},", c_region)
        n_chain_tasks = 0
        n_oob_c = 0
        got_set: set[tuple[int, int, int]] = set()
        for m in re.finditer(
                r"\{\s*0x([0-9A-F]+)u,\s*\d+u,\s*\d+u,\s*0x[0-9A-F]+u,"
                r"\s*\d+u,\s*\d+u,\s*\d+u,\s*\d+u,\s*\d+u,\s*\d+u,\s*(\d+)u,\s*(\d+)u,",
                region):
            target = int(m.group(1), 16)
            begin, count = int(m.group(2)), int(m.group(3))
            if count:
                n_chain_tasks += 1
                if chain_total >= 0 and begin + count > chain_total:
                    n_oob_c += 1
                for i in range(count):
                    if begin + i < len(c_rows):
                        host, _master, stage = c_rows[begin + i]
                        got_set.add((target, int(host, 16), int(stage)))
        ok = (chain_total == exp_edges and len(c_rows) == exp_edges
              and n_chain_tasks == exp_tasks and n_oob_c == 0
              and got_set == exp_set)
        print(("OK  " if ok else "MISS") +
              f" 静态表 · 链式门槛完整（启动边 {len(c_rows)}/{exp_edges} 条 / "
              f"有边任务 {n_chain_tasks}/{exp_tasks} / 切片越界 {n_oob_c} / "
              f"边集合{'一致' if got_set == exp_set else '不一致'}）")
        all_ok &= ok
        m_cf02 = re.search(
            r"\{\s*0x000192D2u,\s*\d+u,\s*\d+u,\s*0x[0-9A-F]+u,"
            r"\s*\d+u,\s*\d+u,\s*\d+u,\s*\d+u,\s*\d+u,\s*\d+u,\s*(\d+)u,\s*(\d+)u,", blob)
        ok_cf02 = False
        if m_cf02:
            cb, cc = int(m_cf02.group(1)), int(m_cf02.group(2))
            if cc == 1 and cb < len(c_rows):
                host, _master, stage = c_rows[cb]
                ok_cf02 = host.upper() == "00009136" and stage == "1000"
        print(("OK  " if ok_cf02 else "MISS") +
              " 静态表 · 菜鸟觐见链式门槛（CF01 深藏不露 @ stage 1000）")
        all_ok &= ok_cf02

        # ★★★ 第 98 轮（DLC 链式门槛 —— 官方 .pex 反编译取证）：破碎空间主线的四条代表边。
        #   取证与判据见 docs/06 八节；这里查的是「数据真的进了表且 host/master/stage 都对」：
        #     MQ02      ← MQ01@10000        （残留之物收尾启动虚妄的得诺者）
        #     MQ_Shell  ← MQ02@2000
        #     MQ03/MQ04/MQ05 ← MQ_Shell@100 （三条议会任务一起开）
        #     MQ06      ← MQ_Shell@1100
        #   ★ master 下标从表里的 kQuestMasters 现算（不写死 3 —— 将来加 master 也不假红）。
        m_masters = re.search(r"kQuestMasters\[\]\s*=\s*\{(.*?)\};", blob, re.S)
        ss_idx = -1
        if m_masters:
            names = re.findall(r'"([^"]+)"', m_masters.group(1))
            for i, nm in enumerate(names):
                if nm.lower() == "shatteredspace.esm":
                    ss_idx = i
        print(("OK  " if ss_idx >= 0 else "MISS") +
              f" 静态表 · kQuestMasters 含 ShatteredSpace.esm（下标 {ss_idx}）")
        all_ok &= ss_idx >= 0
        #   ★ 行首 = 记录号（kQuestTable 用的就是 local，不带 master 前缀）：
        #     MQ02 = 0x0116C7 / MQ_Shell = 0x035E1B / MQ03 = 0x030C2B /
        #     MQ04 = 0x035E1A / MQ05 = 0x035E1C / MQ06 = 0x01221C / MQ01 = 0x0121DB。
        for label, tgt, host, stage in (
                ("虚妄的得诺者 ← 残留之物@10000", "000116C7", "000121DB", "10000"),
                ("家族的调和 ← 虚妄的得诺者@2000", "00035E1B", "000116C7", "2000"),
                ("狂热逾界 ← 家族的调和@100", "00030C2B", "00035E1B", "100"),
                ("信念之争 ← 家族的调和@100", "00035E1A", "00035E1B", "100"),
                ("发掘过去 ← 家族的调和@100", "00035E1C", "00035E1B", "100"),
                ("栉比堡垒 ← 家族的调和@1100", "0001221C", "00035E1B", "1100"),
        ):
            ok_e = False
            m = re.search(r"\{\s*0x" + tgt + r"u,\s*\d+u,\s*\d+u,\s*0x[0-9A-F]+u,"
                          r"\s*\d+u,\s*\d+u,\s*\d+u,\s*\d+u,\s*\d+u,\s*\d+u,"
                          r"\s*(\d+)u,\s*(\d+)u,", blob)
            if m:
                cb, cc = int(m.group(1)), int(m.group(2))
                for i in range(cc):
                    if cb + i >= len(c_rows):
                        continue
                    h, mast, st = c_rows[cb + i]
                    if (h.upper() == host and int(st) == int(stage)
                            and (ss_idx < 0 or int(mast) == ss_idx)):
                        ok_e = True
            print(("OK  " if ok_e else "MISS") + f" 静态表 · DLC 链式边样本（{label}）")
            all_ok &= ok_e

        # ★★★ 第 101 轮（B3 · DLC 链式门槛二期）：14 条新边的代表样本 + 反向检查。
        #   判据与第 98 轮同构，但 **host master 不再假定是 ShatteredSpace** ——
        #   二期同时收 SFBGS050.esm（地球舰队）与 SFBGS00D.esm（自由航道）的边，
        #   所以每条样本都带 master 名、下标从 kQuestMasters 现算（不写死）。
        _masters_all = re.findall(r'"([^"]+)"', m_masters.group(1)) if m_masters else []

        def _master_idx(name: str) -> int:
            for i, nm in enumerate(_masters_all):
                if nm.lower() == name.lower():
                    return i
            return -1

        for label, tgt, host, stage, master in (
                # ① 破碎空间「另一边」（MQIN = 0x0010AAD5）：三条收尾分支各一条边
                ("另一边 ← 狂热逾界@4000", "0010AAD5", "00030C2B", "4000", "ShatteredSpace.esm"),
                ("另一边 ← 信念之争@7000", "0010AAD5", "00035E1A", "7000", "ShatteredSpace.esm"),
                ("另一边 ← 发掘过去@1600", "0010AAD5", "00035E1C", "1600", "ShatteredSpace.esm"),
                # ② 地球舰队（SFBGS050.esm）六级链
                ("MQIntro星际遭遇战 ← 地球舰队侵袭@600", "0000599F", "000059A0", "600", "SFBGS050.esm"),
                ("失踪的华庭号 ← 遭遇战@200", "0002808F", "0000599F", "200", "SFBGS050.esm"),
                ("深入VOID ← 失踪的华庭号@1700（need_stage→CQ）", "00015670", "0002808F", "1700", "SFBGS050.esm"),
                ("失控 ← 深入VOID@9999", "0001A39D", "00015670", "9999", "SFBGS050.esm"),
                ("互助互赢 ← 失控@1180", "00028235", "0001A39D", "1180", "SFBGS050.esm"),
                ("互谅互让 ← 失控@1182", "00028236", "0001A39D", "1182", "SFBGS050.esm"),
                ("互利互惠 ← 失控@1184", "00028237", "0001A39D", "1184", "SFBGS050.esm"),
                ("隐蔽入侵 ← SFTER_MQ03@1700", "00043828", "00028050", "1700", "SFBGS050.esm"),
                # ③ 自由航道 / 锚点星际站（SFBGS00D.esm）
                ("失踪的爱人 ← SFFL_Z01_SE1@10", "000325E6", "000325E7", "10", "SFBGS00D.esm"),
                ("绝非虚言 ← 锚点站对话@95", "00033A2A", "00025B98", "95", "SFBGS00D.esm"),
                ("旧伤 ← 锚点站对话@90", "0003D1DE", "00025B98", "90", "SFBGS00D.esm"),
        ):
            want_m = _master_idx(master)
            ok_e = want_m >= 0
            if ok_e:
                m = re.search(r"\{\s*0x" + tgt + r"u,\s*\d+u,\s*\d+u,\s*0x[0-9A-F]+u,"
                              r"\s*\d+u,\s*\d+u,\s*\d+u,\s*\d+u,\s*\d+u,\s*\d+u,"
                              r"\s*(\d+)u,\s*(\d+)u,", blob)
                ok_e = False
                if m:
                    cb, cc = int(m.group(1)), int(m.group(2))
                    for i in range(cc):
                        if cb + i >= len(c_rows):
                            continue
                        h, mast, st = c_rows[cb + i]
                        if (h.upper() == host and int(st) == int(stage)
                                and int(mast) == want_m):
                            ok_e = True
            print(("OK  " if ok_e else "MISS") +
                  f" 静态表 · DLC 链式边二期样本（{label}）")
            all_ok &= ok_e

        # 反向检查①（第 101 轮）：**噪声边不许进表** —— 「另一边」的两条候选是
        #   调试 fragment（MQ_Shell@2 = stage 0002；MQ03@16 = 整段 Self.SetStage +
        #   MoveTo(调试 marker) + MQIN.Stop()）⇒ MQIN 的切片里不许出现这两条。
        ok_noise = True
        m_mqin = re.search(r"\{\s*0x0010AAD5u,\s*\d+u,\s*\d+u,\s*0x[0-9A-F]+u,"
                           r"\s*\d+u,\s*\d+u,\s*\d+u,\s*\d+u,\s*\d+u,\s*\d+u,"
                           r"\s*(\d+)u,\s*(\d+)u,", blob)
        if m_mqin:
            cb, cc = int(m_mqin.group(1)), int(m_mqin.group(2))
            for i in range(cc):
                if cb + i >= len(c_rows):
                    continue
                h, _mast, st = c_rows[cb + i]
                if (h.upper() == "00035E1B" and int(st) == 2) or \
                        (h.upper() == "00030C2B" and int(st) == 16):
                    ok_noise = False
        else:
            ok_noise = False
        print(("OK  " if ok_noise else "MISS") +
              " 静态表 · 「另一边」不含调试跳关边（MQ_Shell@2 / MQ03@16，反向检查）")
        all_ok &= ok_noise

        # 反向检查②（第 101 轮）：**有意不收的三处不许进表** ——
        #   ① 「地球舰队侵袭」（MQIntro = 0x000059A0）是这条线的入口：它自己没有任何
        #      脚本启动边（入口在数据侧）⇒ 挂上链式门槛会**永远被藏**（误藏）；
        #   ② `DialogueHVDazra@5` 的 8 条城市支线（调试入口 —— 只有 Fragment_Stage_0000
        #      调它，同函数里还有 MoveTo(调试 marker) + AddPerk）；
        #   ③ `VKaiZ03a` / `VkaiZ03b`（结局分支互启环 + 真实入口在数据侧）。
        ok_unwanted = True
        #   （MQIntro 是「宿主」出现在别人的边里 —— 要查的是**它自己有没有链式边**）
        m_intro = re.search(r"\{\s*0x000059A0u,\s*\d+u,\s*\d+u,\s*0x[0-9A-F]+u,"
                            r"\s*\d+u,\s*\d+u,\s*\d+u,\s*\d+u,\s*\d+u,\s*\d+u,"
                            r"\s*(\d+)u,\s*(\d+)u,", blob)
        if m_intro and int(m_intro.group(2)) != 0:
            ok_unwanted = False
        #   ②/③：直接查数据文件（比解表更直观）—— quest_chain_dlc.json 的宿主里
        #   不许出现 DialogueHVDazra / VKaiZ03a / VkaiZ03b。
        dlc_chain_json = ROOT / "ref" / "quest_chain_dlc.json"
        bad_hosts = []
        if dlc_chain_json.exists():
            for t in json.loads(dlc_chain_json.read_text(encoding="utf-8")):
                for e in t.get("edges", []):
                    he = (e.get("host_edid") or "").lower()
                    if he in ("sfbgs001_dialoguehvdazra", "sfbgs001_vkaiz03a",
                              "sfbgs001_vkaiz03b"):
                        bad_hosts.append(he)
        if bad_hosts:
            ok_unwanted = False
        print(("OK  " if ok_unwanted else "MISS") +
              " 静态表 · 「有意不收」的三处未进链式门槛（MQIntro/DialogueHVDazra/VKaiZ03*，反向检查）")
        all_ok &= ok_unwanted

        # ★★ 第 69 轮（扩展链式边 · 同类问题收口）：样本 —— 两条实测过的形态
        #   ① Eleos 静修地线：「幽灵狩猎」（0x0016D4D1）← 「完全停止」（0x0017134F）@1000；
        #   ② 霓虹城帮派线：「展示力量」（0x00226527）← 「面试」（0x00229EE7）@500。
        for label, tgt, host, stage in (
                ("幽灵狩猎 ← 完全停止@1000", "0016D4D1", "0017134F", "1000"),
                ("展示力量 ← 面试@500", "00226527", "00229EE7", "500"),
                # ★★ 第 74 轮：同伴「后续」（承诺任务）的启动边 —— 前置没到不显示
                #   （玩家要求「只显示入口任务」）：
                #     安德列娅：承诺（0x000B8633）← 宿主 @2000（fragment 里 StartCommitmentQuest）
                #     莎拉·摩根：承诺（0x0027B667）← 个人任务完成 @1000（场景 fragment 启动 ⇒
                #       退一步用「个人任务完成」当必要条件）
                ("安德列娅·承诺 ← 宿主@2000", "000B8633", "0023DF2A", "2000"),
                ("莎拉·摩根·承诺 ← 个人任务@1000", "0027B667", "002C7C11", "1000"),
                # ★★ 第 77 轮（龙神线 · 「RIR 留专项」收口）：三条代表边
                #   ① 「人生处处有意外」（0x002A8319，玩家报告的那条）←「挑拨离间」@600；
                #   ② 「领先一步」（0x002C572B）←「重返职场」@1300（龙神第 2 环）；
                #   ③ 「通行是关键」（0x002BABF3）←「全新故事」@300（**故事事件**形态：
                #      工具新增 op SendStoryEvent 核验 `RIR03_QuestStartKeyword.SendStoryEvent()`）。
                ("人生处处有意外 ← 挑拨离间@600", "002A8319", "002AAC9C", "600"),
                ("领先一步 ← 重返职场@1300", "002C572B", "002C9C97", "1300"),
                ("通行是关键 ← 全新故事@300", "002BABF3", "002C2561", "300"),
        ):
            ok_e = False
            m = re.search(r"\{\s*0x" + tgt + r"u,\s*\d+u,\s*\d+u,\s*0x[0-9A-F]+u,"
                          r"\s*\d+u,\s*\d+u,\s*\d+u,\s*\d+u,\s*\d+u,\s*\d+u,"
                          r"\s*(\d+)u,\s*(\d+)u,", blob)
            if m:
                cb, cc = int(m.group(1)), int(m.group(2))
                for i in range(cc):
                    if cb + i < len(c_rows) and c_rows[cb + i][0].upper() == host \
                            and c_rows[cb + i][2] == stage:
                        ok_e = True
            print(("OK  " if ok_e else "MISS") + f" 静态表 · 扩展链式边样本（{label}）")
            all_ok &= ok_e

        # ★★ 第 65 轮（任务专属图标）：阵营列（表行尾的 faction）—— 数据侧完整性：
        #   ① 行数 = kQuestTableSize；② 值域 -1..9（-1 = 无阵营；界面另有边界收敛，
        #      但数据本身必须是干净的枚举）；③ 有阵营任务数与实测对齐（74 条：
        #      UC 19 / Ryujin 16 / HouseVaruun 8 / Freestar 10 / BlackFleet 12 /
        #      Constellation 3 / TerranArmada 6）；④ 实测样本「深藏不露」
        #      （0x00009136，Crimson Fleet 任务）= 5。
        #   ★★ 第 74 轮：行尾追加两列（companion / companionPin）⇒ 正则要显式取
        #   「名字之后的那两个数」，不能再拿「最后一个数」当 faction。
        #   ★★ 第 75 轮：再追加一列（factionEntry，-1 = 不是势力开头任务）⇒ 正则更新为
        #   行尾四列（faction / companion / companionPin / factionEntry）+ 开头补上
        #   记录号（第 75 轮的势力入口完整性检查要按记录号对账）。
        #   ★★ 第 81 轮（地球地标任务）：再追加一列（landmark，-1 = 不是地标任务）⇒
        #   行尾五列（faction / companion / companionPin / factionEntry / landmark）。
        #   ★★ 第 89 轮（可重复任务）：再追加一列（repeatable，-1 = 不是可重复任务）⇒
        #   行尾六列（… / landmark / repeatable）；解包点同步加一位。
        fac_rows = re.findall(
            r'\{\s*0x([0-9A-F]+)u,\s*\d+u,\s*\d+u,\s*0x[0-9A-F]+u,\s*\d+u,\s*\d+u,'
            r'\s*\d+u,\s*\d+u,\s*\d+u,\s*\d+u,\s*\d+u,\s*\d+u,'
            r'.*?,\s*(-?\d+)\s*,\s*(-?\d+)\s*,\s*(\d+)u\s*,\s*(-?\d+)\s*,\s*(-?\d+)\s*,'
            r'\s*(-?\d+)\s*\},',
            region)
        table_size = _num_after(blob, "kQuestTableSize = ")
        n_with_fac = sum(1 for _l, v, _c, _p, _fe, _lm, _rp in fac_rows if int(v) >= 0)
        fac_ok = (len(fac_rows) == table_size and table_size > 0
                  and all(-1 <= int(v) <= 9 for _l, v, _c, _p, _fe, _lm, _rp in fac_rows)
                  and n_with_fac == 74)
        print(("OK  " if fac_ok else "MISS") +
              f" 静态表 · 阵营列完整（行 {len(fac_rows)}/{table_size} / 有阵营 {n_with_fac} /"
              f" 值域 -1..9）")
        all_ok &= fac_ok
        m_fac = re.search(
            r"\{\s*0x00009136u,.*?,\s*(-?\d+)\s*,\s*(-?\d+)\s*,\s*(\d+)u\s*,\s*(-?\d+)\s*,"
            r"\s*(-?\d+)\s*,\s*-?\d+\s*\},", blob)
        ok_fac = m_fac is not None and int(m_fac.group(1)) == 5
        print(("OK  " if ok_fac else "MISS") +
              " 静态表 · 样本「深藏不露」阵营（Crimson Fleet = 5）")
        all_ok &= ok_fac

        # ★★ 第 74 轮（同伴好感度任务）：同伴列完整性 —— 数据侧（不只是特征串）：
        #   ① 表里恰好 8 条 COM_Quest_ 任务带 companion ≥ 0（4 位同伴 × 入口/后续）；
        #   ② 「入口」（companionPin == 1）恰好 4 条，且名字都带同伴前缀
        #      （「巴雷特：违约」/「Sarah Morgan: In Memoriam」形态）；
        #   ③ 名字数组 kCompanionNamesZh/En 与同伴表（ref/companion_quests.json）逐项一致；
        #   ④ 实测样本：「巴雷特：违约」（0x000369AB）= Barrett(1) + pin 1；
        #      「巴雷特：承诺」（0x001C7185）= Barrett(1) + pin 0（**后续** ⇒ 走链式门槛）。
        comp_rows = [(int(l, 16), int(c), int(p))
                     for (l, _f, c, p, _fe, _lm, _rp) in fac_rows if int(c) >= 0]
        n_pin = sum(1 for _f, _c, p in comp_rows if p)
        comp_json = ROOT / "ref" / "companion_quests.json"
        names_zh, names_en, n_json_q = [], [], 0
        if comp_json.exists():
            cj = json.loads(comp_json.read_text(encoding="utf-8"))
            names_zh = [g["nameZh"] for g in cj]
            names_en = [g["nameEn"] for g in cj]
            n_json_q = sum(len(g["quests"]) for g in cj)
        m_zh = re.search(r"kCompanionNamesZh\[\]\s*=\s*\{(.*?)\};", blob, re.S)
        m_en = re.search(r"kCompanionNamesEn\[\]\s*=\s*\{(.*?)\};", blob, re.S)
        rows_zh = re.findall(r'"([^"]*)"', m_zh.group(1)) if m_zh else []
        rows_en = re.findall(r'"([^"]*)"', m_en.group(1)) if m_en else []
        comp_ok = (len(comp_rows) == 8 == n_json_q and n_pin == 4
                   and rows_zh == names_zh and rows_en == names_en
                   and _num_after(blob, "kCompanionCount = ") == len(names_zh) > 0)
        print(("OK  " if comp_ok else "MISS") +
              f" 静态表 · 同伴好感度任务完整（标记 {len(comp_rows)}/8、入口固定显示 {n_pin}/4、"
              f"名字表 {len(rows_zh)} 位/与 ref 逐项一致={rows_zh == names_zh}）")
        all_ok &= comp_ok
        for local, want_pin, want_name, label in (
                ("000369AB", 1, "巴雷特：违约", "入口·固定显示"),
                ("001C7185", 0, "巴雷特：承诺", "后续·链式门槛"),
                ("00263262", 1, "萨姆·科尔：哈特家事", "入口·固定显示"),
                ("0027B667", 0, "莎拉·摩根：承诺", "后续·链式门槛")):
            m = re.search(r"\{\s*0x" + local + r"u,.*?,\s*(-?\d+)\s*,\s*(-?\d+)\s*,\s*(\d+)u\s*,\s*(-?\d+)\s*,"
                          r"\s*(-?\d+)\s*,\s*-?\d+\s*\},", blob)
            ok_row = (m is not None and int(m.group(3)) == want_pin
                      and f'"{want_name}"' in blob)
            print(("OK  " if ok_row else "MISS") +
                  f" 静态表 · 同伴样本 {label}（{want_name} pin={want_pin}）")
            all_ok &= ok_row

        # ★★ 第 75 轮（四大势力开头任务）：数据侧完整性 ——
        #   ① 表里恰好 4 条 factionEntry ≥ 0，下标 = 0..3（= 固定顺序，无重复）；
        #   ② 与 ref/faction_entry_quests.json 的 uID / 下标 / 说明文本逐项一致；
        #   ③ 「深红舰队」那条（guide=false）的**引导候选被清空**（candCount == 0）——
        #      界面因此走「不可导航」通路（只给说明）；
        #   ④ 样本：「深藏不露」= 下标 3 + 阵营 5 + 候选 0；「超越极限」= 下标 0 + 候选 > 0。
        fe_rows = [(l, int(fe)) for (l, _f, _c, _p, fe, _lm, _rp) in fac_rows if int(fe) >= 0]
        fe_json = ROOT / "ref" / "faction_entry_quests.json"
        fe_ok = len(fe_rows) == 4 and sorted(v for _f, v in fe_rows) == [0, 1, 2, 3]
        want_fe = []
        if fe_json.exists():
            fej = json.loads(fe_json.read_text(encoding="utf-8"))
            want_fe = [(f"{int(g['quest']['local']):08X}", i) for i, g in enumerate(fej)]
            fe_ok = fe_ok and sorted(fe_rows) == sorted(want_fe)
            # 说明文本（中/英）逐条编进静态表（kFactionEntryNotesZh/En）
            m_notes_zh = re.search(r"kFactionEntryNotesZh\[\]\s*=\s*\{(.*?)\};", blob, re.S)
            m_notes_en = re.search(r"kFactionEntryNotesEn\[\]\s*=\s*\{(.*?)\};", blob, re.S)
            for i, g in enumerate(fej):
                if g["noteZh"] not in blob or g["noteEn"] not in blob:
                    fe_ok = False
                    print(f"MISS 静态表 · 势力说明文本缺失（{g['key']}）")
                    break
        print(("OK  " if fe_ok else "MISS") +
              f" 静态表 · 四大势力开头任务完整（标记 {len(fe_rows)}/4、下标 {sorted(v for _f, v in fe_rows)}"
              + (f"、与 ref 逐项一致" if fe_json.exists() else "（缺 ref/faction_entry_quests.json）") + "）")
        all_ok &= fe_ok
        #   ④ 样本行：下标 / 阵营 / 候选数
        for local, want_fe_idx, want_fac, want_cands, tag in (
                ("002C5401", 0, 1, True, "联合殖民地·超越极限（可引导）"),
                ("0029A8F0", 1, 4, True, "自由星·枝节横生（可引导）"),
                ("002C9C97", 2, 2, True, "龙神·重返职场（可引导）"),
                ("00009136", 3, 5, False, "深红舰队·深藏不露（只给说明 → 候选被清空）")):
            m = re.search(r"\{\s*0x" + local + r"u,\s*\d+u,\s*\d+u,\s*0x[0-9A-F]+u,"
                          r"\s*\d+u,\s*(\d+)u,.*?,\s*(-?\d+)\s*,\s*(-?\d+)\s*,\s*(\d+)u\s*,\s*(-?\d+)\s*,"
                          r"\s*(-?\d+)\s*,\s*-?\d+\s*\},",
                          blob)
            #   组号：1 = candCount；2 = faction；3 = companion；4 = companionPin；
            #         5 = factionEntry（行尾六列的顺序见 StaticQuestInfo；第 89 轮起
            #         尾部还有 landmark / repeatable —— 用非捕获匹配，组号不受影响）
            ok_row = (m is not None and int(m.group(2)) == want_fac
                      and int(m.group(5)) == want_fe_idx
                      and ((int(m.group(1)) > 0) == want_cands))
            print(("OK  " if ok_row else "MISS") +
                  f" 静态表 · 势力入口样本 {tag}（下标 {want_fe_idx} / 阵营 {want_fac} / "
                  f"候选{'>0' if want_cands else '=0'}）")
            all_ok &= ok_row

        # ★★ 第 81 轮（地球地标任务）：「雪景球」收集线 10 条 —— 数据侧完整性：
        #   ① 表里恰好 10 条 landmark ≥ 0，下标 = 0..9（与 ref/landmark_quests.json 逐项一致）；
        #   ② 说明文本（kLandmarkNotesZh/En）逐条编进静态表（描述第一句用它）；
        #   ③ 样本：「阿波罗地标任务」（0x0026EB0）= 下标 0 + 候选 4；
        #      「开罗地标任务」（0x00009A2C）= 下标 1 + 候选 4（书商引导）；
        #      「伦敦地标任务」（0x0000994A）= 下标 4 + 候选 0（只给说明 —— 界面走
        #      「不可导航」通路）。
        lm_rows = [(l, int(lm)) for (l, _f, _c, _p, _fe, lm, _rp) in fac_rows if int(lm) >= 0]
        lm_json = ROOT / "ref" / "landmark_quests.json"
        lm_ok = len(lm_rows) == 10 and sorted(v for _f, v in lm_rows) == list(range(10))
        if lm_json.exists():
            lmj = json.loads(lm_json.read_text(encoding="utf-8"))
            want_lm = [(f"{int(g['quest']['local']):08X}", i) for i, g in enumerate(lmj)]
            lm_ok = lm_ok and sorted(lm_rows) == sorted(want_lm)

            def _c_esc(s: str) -> str:
                # 生成器（gen_quest_table.py::c_escape）把头文件里的字符串做 C 转义
                # （`"` → `\"`、`\` → `\\`）—— 比对前做同样处理。
                # ★ 第 81 轮踩过：英文说明里的书名带引号 ⇒ 原文比对永远匹配不上。
                return (s.replace("\\", "\\\\").replace('"', '\\"')
                        .replace("\n", "\\n").replace("\t", "\\t"))

            for g in lmj:
                if _c_esc(g["noteZh"]) not in blob or _c_esc(g["noteEn"]) not in blob:
                    lm_ok = False
                    print(f"MISS 静态表 · 地标说明文本缺失（{g['key']}）")
                    break
            lm_ok = lm_ok and _num_after(blob, "kLandmarkCount = ") == len(lmj)
        print(("OK  " if lm_ok else "MISS") +
              f" 静态表 · 地球地标任务完整（标记 {len(lm_rows)}/10、"
              f"下标 {sorted(v for _f, v in lm_rows)}"
              + ("、与 ref 逐项一致" if lm_json.exists() else "（缺 ref/landmark_quests.json）")
              + "）")
        all_ok &= lm_ok
        for local, want_lm_idx, want_cands, tag in (
                ("00026EB0", 0, True, "阿波罗（可引导，候选 4）"),
                ("00009A2C", 1, True, "开罗（书商引导，候选 4）"),
                ("0000994A", 4, False, "伦敦（只给说明 → 候选为空）")):
            m = re.search(r"\{\s*0x" + local + r"u,\s*\d+u,\s*\d+u,\s*0x[0-9A-F]+u,"
                          r"\s*\d+u,\s*(\d+)u,.*?,\s*(-?\d+)\s*,\s*(-?\d+)\s*,\s*(\d+)u\s*,\s*(-?\d+)\s*,"
                          r"\s*(-?\d+)\s*,\s*-?\d+\s*\},",
                          blob)
            #   组号：1 = candCount；2 = faction；3 = companion；4 = companionPin；
            #         5 = factionEntry；6 = landmark（行尾六列的顺序见 StaticQuestInfo；
            #         第 89 轮起的尾部 repeatable 用非捕获匹配，组号不受影响）
            ok_row = (m is not None and int(m.group(6)) == want_lm_idx
                      and ((int(m.group(1)) > 0) == want_cands))
            print(("OK  " if ok_row else "MISS") +
                  f" 静态表 · 地标样本 {tag}（下标 {want_lm_idx} / "
                  f"候选{'>0' if want_cands else '=0'}）")
            all_ok &= ok_row

        # ★★ 第 89 轮（可重复任务）：静态表 repeatable 列 + 说明文本 —— 数据侧完整性：
        #   ① 表里恰好 20 条 repeatable ≥ 0，下标 = 0..19（与 ref/repeatable_quests.json
        #      逐项一致）；② 说明文本（kRepeatableNotesZh/En）逐条编进静态表
        #      （描述第一句用它 ——「（可重复）完成一次后还能再次接取 …」）；
        #   ③ 样本：「翻新商品」（0x00224FE8）= 下标 0（Denis Averin 那条，玩家反馈的
        #      起点）；「全数到期」（0x002AD3D5）= 下标 12。
        #   ★★ 第 90 轮：清单扩到 20 条（DLC 的 SFFL 家族 5 条，追加在末尾 ⇒
        #      老下标不动）；新增 DLC 样本（职业杀手 15 / 危险材料 18 = 随机太空遭遇）。
        #   （运行期豁免链另有两处检查：C++ 载荷第 11 列 + AS3 FilterKnownQuests，
        #     见本文件后面的「可重复任务豁免链」段。）
        rp_rows = [(l, int(rp)) for (l, _f, _c, _p, _fe, _lm, rp) in fac_rows if int(rp) >= 0]
        rp_json = ROOT / "ref" / "repeatable_quests.json"
        rp_ok = len(rp_rows) == 20 and sorted(v for _f, v in rp_rows) == list(range(20))
        if rp_json.exists():
            rpj = json.loads(rp_json.read_text(encoding="utf-8"))

            def _c_esc_rp(s: str) -> str:
                return (s.replace("\\", "\\\\").replace('"', '\\"')
                        .replace("\n", "\\n").replace("\t", "\\t"))

            want_rp = [(f"{int(g['local']):08X}", i) for i, g in enumerate(rpj)]
            rp_ok = rp_ok and sorted(rp_rows) == sorted(want_rp)
            for g in rpj:
                if _c_esc_rp(g["noteZh"]) not in blob or _c_esc_rp(g["noteEn"]) not in blob:
                    rp_ok = False
                    print(f"MISS 静态表 · 可重复任务说明文本缺失（{g['key']}）")
                    break
            rp_ok = rp_ok and _num_after(blob, "kRepeatableCount = ") == len(rpj)
        print(("OK  " if rp_ok else "MISS") +
              f" 静态表 · 可重复任务完整（标记 {len(rp_rows)}/20"
              + ("、与 ref 逐项一致" if rp_json.exists() else "（缺 ref/repeatable_quests.json）")
              + "）")
        all_ok &= rp_ok
        for local, want_rp_idx, tag in (
                ("00224FE8", 0, "翻新商品（Denis Averin，玩家反馈的起点）"),
                ("002AD3D5", 12, "全数到期（GalBank 兰德里）"),
                # ★★ 第 90 轮：DLC 的 SFFL 家族 —— 有接取人（15）/ 随机太空遭遇（18）
                ("0002A418", 15, "职业杀手（锚点星际站的仲裁者）"),
                ("000296F5", 18, "危险材料（随机太空遭遇，无接取点）")):
            m = re.search(r"\{\s*0x" + local + r"u,\s*\d+u,\s*\d+u,\s*0x[0-9A-F]+u,"
                          r"\s*\d+u,\s*\d+u,.*?,\s*-?\d+\s*,\s*-?\d+\s*,\s*\d+u\s*,\s*-?\d+\s*,"
                          r"\s*-?\d+\s*,\s*(-?\d+)\s*\},", blob)
            ok_row = m is not None and int(m.group(1)) == want_rp_idx
            print(("OK  " if ok_row else "MISS") +
                  f" 静态表 · 可重复任务样本 {tag}（下标 {want_rp_idx}）")
            all_ok &= ok_row

        # ★★ 第 74 轮续（「把它们放在一起」）：**内嵌回退载荷的条目顺序** —— 与 C++ 侧
        #   逐条对齐（同伴任务前置 + 按同伴分组、入口在后续前；其余保持表顺序）。
        #   为什么查它：C++ 推送失败的头 0.3~0.8 秒用的是这份内嵌数据 —— 顺序不一致会
        #   让「列表开头忽然跳变」（与第 65 轮「列不对齐」同一类协议纪律）。
        inc_path = ROOT / "ui/missionmenu/saqdata/SaqEmbeddedPayload.inc"
        if inc_path.exists():
            inc = inc_path.read_text(encoding="utf-8", errors="replace")
            # 期望的表头 12 条：
            #   ★★ 第 75 轮：前 4 条 = **四大势力开头任务**（固定顺序 =
            #     UC01 超越极限 → FC01 枝节横生 → RI01 重返职场 → CF01 深藏不露）；
            #   ★ 第 74 轮：接着 8 条 = 同伴任务（顺序 = 同伴下标，每位同伴「入口在后续前」）
            #     安德列娅 难侍二主/承诺 → 巴雷特 违约/承诺 → 萨姆·科尔 哈特家事/承诺
            #     → 莎拉·摩根 难忘逝者/承诺。
            want_head = [int(f, 16) for f in
                         ("002C5401", "0029A8F0", "002C9C97", "00009136",
                          "0021ECD0", "000B8633", "000369AB", "001C7185",
                          "00263262", "000DF7AD", "002C7C11", "0027B667")]
            head = [int(x) for x in re.findall(r"Q\\t(\d+)\\t", inc)[:12]]
            ok_head = head == want_head
            print(("OK  " if ok_head else "MISS") +
                  " 内嵌载荷 · 势力开头任务在前四条 + 同伴任务随后（与 C++ 排序逐条同序）"
                  + ("" if ok_head else f" ← 实际 {[hex(x) for x in head]}"))
            all_ok &= ok_head
            # 反向检查：第一条不能再是基础游戏的最小记录号（0x351A = 平衡账目）——
            #   那是「未分组」的旧顺序（势力/同伴任务散在 261 条里）。
            gone = not head or head[0] != 0x351A
            print(("OK  " if gone else "MISS") + " 内嵌载荷 · 旧「未分组」顺序已替换(反向检查)")
            all_ok &= gone
            # ★★ 第 75 轮：内嵌载荷带上了第 9/10 列（「简要说明」中/英）—— 这正是
            #   「C++ 推送失败的头 0.3~0.8 秒里描述也对」的保证（列不对齐会让说明串行）。
            note_ok = ("加入联合殖民地先锋队" in inc and "加入深红舰队" in inc
                       and "Join the UC Vanguard" in inc)
            print(("OK  " if note_ok else "MISS") +
                  " 内嵌载荷 · 四大势力开头任务的「简要说明」两列都在")
            all_ok &= note_ok
            # ★★ 第 96 轮（可重复任务分组 —— 玩家反馈「一样把他们排列在一起」）：
            #   内嵌回退载荷的**最后一段**必须全是可重复任务（末列 repeatable = "1"）——
            #   与 C++ 的 group 3（列表末尾）逐条同序；回退载荷只含 Starfield.esm 的
            #   212 条 ⇒ 末尾连续段长度 = 该 master 的可重复任务数（ref 清单里 = 15）。
            #   ★ 行级判断必须基于**还原后的载荷**：chunk 在 6000 字符处切分，实测有
            #   2 行 Q 正好被切在两段字面量之间 ⇒ 在原始文本里按行扫会漏行（顺序检查
            #   会假红/假绿——这里一次性把「提取字面量 → 反转义 → join」写成通用做法）。
            _inc_chunks = re.findall(r'"((?:[^"\\]|\\.)*)"', inc, re.S)
            _inc_parts: list[str] = []
            for _c in _inc_chunks:
                try:
                    _inc_parts.append(json.loads('"' + _c + '"'))
                except json.JSONDecodeError:
                    _inc_parts.append(_c)   # 反解失败就原样保留（不静默丢内容）
            payload_rows = [r for r in "".join(_inc_parts).split("\n")
                            if r.startswith("Q\t")]
            want_tail = (sum(1 for g in rpj if g.get("master") == "Starfield.esm")
                         if rp_json.exists() else 15)
            tail_run = 0
            for _r in reversed(payload_rows):
                if not _r.endswith("\t1"):
                    break
                tail_run += 1
            tail_ok = (want_tail > 0 and tail_run == want_tail
                       and len(payload_rows) > tail_run)
            print(("OK  " if tail_ok else "MISS") +
                  f" 内嵌载荷 · 可重复任务整组在末尾（末尾连续 repeatable=1 共 "
                  f"{tail_run}/{want_tail} 条；总行 {len(payload_rows)}）")
            all_ok &= tail_ok

        # ★★ 第 65 轮（任务专属图标）：**图标映射表** —— 「数据 -> 图标帧」永不落空。
        #
        #   界面最终执行的映射链（复刻自 SWF 源码，两侧都要复刻才对得上）：
        #     SaqSafeType（非原版枚举 -> 4）→ SaqSafeFaction（越界 -> -1）
        #       → QuestUtils.GetQuestIconLabel(faction, type) → gotoAndStop(帧名)
        #   这里用表里**实际存在的** (type, faction) 组合跑一遍，断言每一个结果帧名
        #   都在 Icons_mc 实际存在的 13 个帧里（帧清单 = SWF sprite 解析，见 docs/02）：
        #     Activities / Misc / Missions / None / BlackFleet / FreestarCollective /
        #     HouseVaruun / RyujinIndustries / UnitedColonies / TrackersAlliance /
        #     Constellation / TerranArmada / Creations
        #   ⇒ 保证任何数据都不会让 gotoAndStop 找不到帧（那会抛异常把整行渲染带崩）。
        icon_frames = {
            "Activities", "Misc", "Missions", "None", "BlackFleet", "FreestarCollective",
            "HouseVaruun", "RyujinIndustries", "UnitedColonies", "TrackersAlliance",
            "Constellation", "TerranArmada", "Creations",
        }
        fac_frame = {0: "None", 1: "UnitedColonies", 2: "RyujinIndustries", 3: "HouseVaruun",
                     4: "FreestarCollective", 5: "BlackFleet", 6: "Constellation",
                     7: "TrackersAlliance", 8: "TerranArmada", 9: "Creations"}

        def saq_safe_type(tp: int) -> int:
            return tp if tp in (0, 1, 2, 3, 4) else 4

        def saq_safe_faction(fac: int) -> int:
            return fac if 0 <= fac <= 9 else -1

        def icon_label(fac: int, tp: int) -> str:
            tp = saq_safe_type(tp)
            fac = saq_safe_faction(fac)
            if tp == 0:
                return "Activities"
            if fac != -1:
                return fac_frame[fac]
            if tp == 3:
                return "Misc"
            if tp == 4:
                return "Missions"
            return "None"

        #   ★★ 第 74 轮：行尾多了 companion / companionPin 两列 ⇒ 这里显式取
        #   「type + faction」（此前用 `.*?,\s*(-?\d+)\s*\},` 取最后一个数 —— 会读到
        #   companionPin，把图标映射检查变成瞎猜）；★★ 第 75 轮行尾再多一列
        #   （factionEntry）⇒ 尾部模式跟着更新；★★ 第 81 轮再多一列（landmark）⇒ 同步；
        #   ★★ 第 89 轮再多一列（repeatable）⇒ 尾部模式再加一位。
        tf_pairs = {(int(m.group(1)), int(m.group(2))) for m in re.finditer(
            r"\{\s*0x[0-9A-F]+u,\s*\d+u,\s*(\d+)u,\s*0x[0-9A-F]+u,"
            r".*?,\s*(-?\d+)\s*,\s*(-?\d+)\s*,\s*\d+u\s*,\s*-?\d+\s*,\s*-?\d+\s*,\s*-?\d+\s*\},", region)}
        tf_bad = sorted(p for p in tf_pairs if icon_label(p[1], p[0]) not in icon_frames)
        ok_icon = not tf_bad and len(tf_pairs) > 0
        print(("OK  " if ok_icon else "MISS") +
              f" 静态表 · 图标映射永不落空（{len(tf_pairs)} 个 (type,faction) 组合"
              + (f"；越界：{tf_bad}" if tf_bad else "，全部命中 13 个实际帧") + "）")
        all_ok &= ok_icon
        probe_icon = (icon_label(5, 2) == "BlackFleet"      # 深藏不露（Crimson Fleet）
                      and icon_label(-1, 0) == "Activities"  # 活动
                      and icon_label(-1, 3) == "Misc"        # 杂项
                      and icon_label(-1, 4) == "Missions"    # 任务
                      and icon_label(6, 2) == "Constellation"  # 星座组织
                      and icon_label(-1, 100) == "Missions"    # 入口（100 -> 4）
                      and icon_label(99, 2) == "None")          # 越界阵营 -> None（不崩）
        print(("OK  " if probe_icon else "MISS") +
              " 静态表 · 图标映射关键通路（BlackFleet/Activities/Misc/Missions/"
              "Constellation/入口折叠/越界兜底）")
        all_ok &= probe_icon
    else:
        print(f"MISS 缺少 {table_h}")
        all_ok = False

    # ★★ 第 80 轮（可重复 NPC 入口）：入口条目表（SAQ_EntryTable.h）**数据侧**完整性 ——
    #   ① 20 条（任务板 12 + 可重复 NPC 8；kEntryTableSize）；
    #   ② 名字前缀「（可重复）」/"(Repeatable)" **只在 NPC 条目上**（玩家要求：
    #      「任务板不需要，只需要 NPC 这样做」）；
    #   ③ 与 ref/repeatable_givers.json（数据源）逐项一致：uID / 名字 / 兜底候选；
    #   ④ 与 ref/board_markers.json（ESM 侧建档产物）一致：markerLocal；
    #   ⑤ marker 分配：NPC 从 0x90B 起连续 7 条（外景条目 0x00216D34 无 marker = 0）；
    #   ⑥ 样本：邓肯·林奇（0x00214684）= marker 0x910 + 兜底 0xC35BA（内景：同 cell）；
    #      「追踪者联盟探员 · 阿基拉城」（0x00216D34）= marker 0 + 兜底 0x21D003
    #      （外景：世界级常驻引用）。
    entry_h = ROOT / "plugin" / "src" / "SAQ_EntryTable.h"
    if entry_h.exists():
        ent_blob = entry_h.read_text(encoding="utf-8", errors="replace")
        #   注意：生成器把 `true` 写成 `true `（尾随空格对齐 `false`）⇒ 真值后允许空白
        #   （第 80 轮首次跑 verify 抓出来的：严格 `true,` 会漏掉唯一常驻的那条 ⇒ 11 而非 12）。
        ent_rows = re.findall(
            r'\{\s*0x([0-9A-Fa-f]+)u,\s*(\d+)u,\s*(true|false)\s*,\s*0x([0-9A-Fa-f]+)u,\s*'
            r'0x([0-9A-Fa-f]+)u,\s*0x([0-9A-Fa-f]+)u,\s*(\d+)u,\s*"([^"]*)",\s*"([^"]*)"\s*\},',
            ent_blob)
        m_ent_size = re.search(r"kEntryTableSize\s*=\s*(\d+);", ent_blob)
        ent_size = int(m_ent_size.group(1)) if m_ent_size else -1
        n_board = sum(1 for r_ in ent_rows if r_[6] == "0")
        n_npc = sum(1 for r_ in ent_rows if r_[6] == "1")
        bad_prefix = [r_[0] for r_ in ent_rows
                      if (r_[6] == "1") != (r_[8].startswith("（可重复）")
                                            and r_[7].startswith("(Repeatable)"))]
        ent_ok = (len(ent_rows) == 20 == ent_size and n_board == 12 and n_npc == 8
                  and not bad_prefix)
        print(("OK  " if ent_ok else "MISS") +
              f" 入口表 · 20 条（任务板 {n_board} + 可重复 NPC {n_npc}；"
              f"「（可重复）」前缀只在 NPC 上={not bad_prefix}）")
        all_ok &= ent_ok

        by_local = {int(r_[0], 16): r_ for r_ in ent_rows}
        gv_json = ROOT / "ref" / "repeatable_givers.json"
        gv_ok = gv_json.exists()
        if gv_ok:
            gv = json.loads(gv_json.read_text(encoding="utf-8"))
            gv_ok = len(gv) == 8
            for g in gv:
                r_ = by_local.get(g["refLocal"])
                if r_ is None or (int(r_[6]) != 1 or r_[8] != g["nameZh"]
                                  or r_[7] != g["nameEn"]
                                  or int(r_[4], 16) != (g["fallback1"] or 0)
                                  or int(r_[5], 16) != (g["fallback2"] or 0)):
                    gv_ok = False
                    break
        print(("OK  " if gv_ok else "MISS") +
              " 入口表 · NPC 条目与 ref/repeatable_givers.json 逐项一致（8 条）")
        all_ok &= gv_ok

        bm_json = ROOT / "ref" / "board_markers.json"
        bm_ok = bm_json.exists()
        if bm_ok:
            bm = {m["refLocal"]: m["markerLocal"]
                  for m in json.loads(bm_json.read_text(encoding="utf-8"))["markers"]}
            bm_ok = all(int(r_[3], 16) == bm.get(int(r_[0], 16), 0) for r_ in ent_rows)
        print(("OK  " if bm_ok else "MISS") +
              " 入口表 · markerLocal 与 board_markers.json 一致（20 条）")
        all_ok &= bm_ok

        npc_markers = sorted(int(r_[3], 16) for r_ in ent_rows
                             if r_[6] == "1" and int(r_[3], 16))
        mk_ok = npc_markers == list(range(0x90B, 0x912))
        print(("OK  " if mk_ok else "MISS") +
              " 入口表 · NPC marker 连续 7 条 0x90B~0x911（"
              + " ".join(f"0x{v:X}" for v in npc_markers) + "）")
        all_ok &= mk_ok
        for local, want_mk, want_fb1, tag in (
                ("00214684", 0x910, 0x000C35BA, "贸易管理局·邓肯·林奇（内景：marker + 同 cell 兜底）"),
                ("00216D34", 0x0, 0x0021D003, "追踪者联盟探员·阿基拉城（外景：无 marker，世界级兜底）")):
            r_ = by_local.get(int(local, 16))
            ok_row = (r_ is not None and int(r_[3], 16) == want_mk
                      and int(r_[4], 16) == want_fb1 and int(r_[6]) == 1)
            print(("OK  " if ok_row else "MISS") + f" 入口表 · NPC 样本（{tag}）")
            all_ok &= ok_row
    else:
        print(f"MISS 缺少 {entry_h}")
        all_ok = False

    # ★ 第 20 轮：ESM 里的测试开关 GLOB（控制台 `set SAQ_TestMode to N` 的落点）
    # ★ 第 30 轮：同时按组结构解析「11 条任务板的新建常驻 XMarker marker」（数据侧保证，
    #   不只是特征串）—— 第 29 轮的 override 路线已被实机否定，见 check_esm_markers。
    entries = json.loads((ROOT / "ref/entry_targets.json").read_text(encoding="utf-8"))
    # ★ 第 33 轮：marker 所在 cell 还必须有一条 CELL 记录 override（值 = 该 cell 的 EDID，用来比对）
    expect_markers = {e["refLocal"]: e["cell"] for e in entries if e.get("markerLocal")}
    for label, path in (("工作区", ROOT / "esm/SAQ_ShowAvailableQuests.esm"),
                        ("MO2 部署", MO2_MOD / "SAQ_ShowAvailableQuests.esm")):
        if path.exists():
            blob = path.read_bytes()
            all_ok &= check(f"ESM({label}) · 测试开关 GLOB", blob, b"SAQ_TestMode")
            # ★ 第 21 轮：引导目标高位 GLOB（+ VMAD 属性绑定）
            all_ok &= check(f"ESM({label}) · 引导目标高位 GLOB", blob, b"SAQ_GuidePrefix")
            # ★ 第 49 轮：测试命令通道 GLOB（0x806~0x80D）。MO2 副本的值会被 harness
            #   在运行期改（运行中的 mod 用那份），所以只有工作区副本要求初值 0。
            all_ok &= check_esm_test_globs(path, label, require_zero=(label == "工作区"))
            all_ok &= check_esm_markers(path, expect_markers, label)
        else:
            print(f"MISS 缺少 {path}")
            all_ok = False

    # ★★ 第 62 轮（用户要求）：打包产物不许带测试功能 / 测试配置 —— 三层检查：
    #   ① 源 ini（resources）：[Test] 段必须是玩家默认值（Mode=0 / Harness=0）；
    #   ② dist\stage（上次打包的 staging；存在时查）：**包内实际那份** ini 同样必须
    #      是默认值（package-saq.ps1 组装时会强制还原，这里是「真的还原了吗」的事后校验）；
    #   ③ dist 里最新的上传包：文件清单不许含测试资产
    #      （SAQ_TestPlan.txt / SAQ_testresults.json）。
    #   为什么放在 verify 里：脚本是「构建/打包流程的守门人」，把用户要求变成机器判据，
    #   以后谁改脏了 ini 或者往打包清单里塞了测试文件，这里立刻 MISS。
    def _ini_is_default(text: str) -> bool:
        return (re.search(r"(?m)^\s*Mode\s*=\s*0\s*$", text) is not None
                and re.search(r"(?m)^\s*Harness\s*=\s*0\s*$", text) is not None)

    ini_src = ROOT / "resources/SAQ_ShowAvailableQuests.ini"
    if ini_src.exists():
        ok = _ini_is_default(ini_src.read_text(encoding="utf-8", errors="replace"))
        print(("OK  " if ok else "MISS") + " 打包源 ini · 玩家默认值（[Test] Mode=0 / Harness=0）")
        all_ok &= ok
    ini_stage = ROOT / "dist/stage/SFSE/Plugins/SAQ_ShowAvailableQuests.ini"
    if ini_stage.exists():
        ok = _ini_is_default(ini_stage.read_text(encoding="utf-8", errors="replace"))
        print(("OK  " if ok else "MISS") +
              " 上传包 staging ini · 玩家默认值（[Test] Mode=0 / Harness=0）")
        all_ok &= ok
    zips = sorted((ROOT / "dist").glob("SAQ-ShowAvailableQuests-*.zip"),
                  key=lambda p: p.stat().st_mtime)
    if zips:
        import zipfile
        with zipfile.ZipFile(zips[-1]) as zf:
            names = zf.namelist()
        bad = [n for n in names
               if "TestPlan" in n or "testresults" in n or "SAQ_Test" in n]
        ok = not bad
        print(("OK  " if ok else "MISS") +
              f" 上传包({zips[-1].name}) · 不含测试资产（{len(names)} 个文件）"
              + ("" if ok else "（含：" + "、".join(bad) + "）"))
        all_ok &= ok

    print("---")
    print("全部通过" if all_ok else "存在缺失（见上面的 MISS）")
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
