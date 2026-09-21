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
    ("harness 驱动器版本串",
     "驱动器 v59：落地静默期每 Tick 推进"),
    ("harness 落地静默期解耦文案", "落地静默期完成（回执后"),
    ("harness 传送落地静默期文案", "传送落地中（回执已到，但加载画面还没关"),
    ("harness 传送落地超限判定", "疑似卡在加载画面"),
    ("harness 卡死自动中止文案", "游戏端疑似卡死"),
    ("harness 命令超时菜单证据", "此刻打开的菜单"),
    ("harness 清场延迟复查文案", "用例收尾复查：星图在清场后才打开"),
    ("传送回执等待窗口文案", "传送等回执最多"),
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
            # 反向检查（第 58/59 轮）：v58 及更早的驱动器版本串不应再出现 —— 日志里那串
            #   「驱动器 v59：…」是「跑的是不是修好时序那版」的唯一判据（同 SWF stamp=）。
            gone = "驱动器 v57".encode() not in blob and "驱动器 v58".encode() not in blob
            print(("OK  " if gone else "MISS") + " DLL · 旧驱动器版本串 v57/v58 已替换(反向检查)")
            all_ok &= gone
            # ★★ 第 54 轮：用例计划本身也该被查 —— 历史判据（第 26/44~48 轮）落成用例后，
            #   最怕的是「源码改了没部署」或「用例被误删」。这里只查**开发模式**：
            #   ① 6 条用例都在（smoke + 5 条历史判据）；
            #   ② MO2 部署副本与工作区**字节一致**（部署未落后 —— 与 DLL 同一条教训）。
            plan_src = ROOT / "tools/test/scenarios/SAQ_TestPlan.txt"
            if plan_src.exists():
                plan_text = plan_src.read_text(encoding="utf-8", errors="replace")
                for cid in ("smoke", "r26_menu_idle", "r44_starmap", "r45_candidates",
                            "r47_board_marker", "r48_info_gate"):
                    all_ok &= check(f"用例计划 · [case:{cid}]", plan_text.encode(),
                                    f"[case:{cid}]".encode())
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

    # ★ 第 35 轮：进度门槛的**数据侧**校验（生成物 plugin/src/SAQ_QuestTable.h）——
    #   7 条 gated 任务 / 9 条条件（tools/esm/analyze_ctda.py → ctda_gates.json →
    #   gen_quest_table.py）。被检查任务的记录号必须是真正被引用的那几条。
    table_h = ROOT / "plugin/src/SAQ_QuestTable.h"
    if table_h.exists():
        blob = table_h.read_text(encoding="utf-8")
        for name, needle in {
            "门槛结构 StaticCondGate": "struct StaticCondGate",
            "门槛枚举 kCondStageDone": "kCondStageDone = 2",
            "被检查任务 UC04(0x2AAE8D)": "0x002AAE8D",
            "被检查任务 UC01(0x2C5401)": "0x002C5401",
            "被检查任务 Botany02(0x27071B)": "0x0027071B",
            "被检查任务 City_Neon_Gang03(0x2250C4)": "0x002250C4",
        }.items():
            ok = needle in blob
            print(("OK  " if ok else "MISS") + f" 静态表 · {name}")
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
        ok = n > 0
        print(("OK  " if ok else "MISS") + f" 静态表 · 门槛计数非空（kQuestCondCount = {n}）")
        all_ok &= ok

        # ★★ 第 45 轮：引导目标**候选池**（多候选链）—— 数据侧完整性（不只是特征串）：
        #   ① 结构/数组存在；② 候选计数 > 0；③ 任务表的切片 (candBegin+candCount)
        #   全部不越界、且有目标任务数与实测对齐（209 条）；④ 旧单目标字段已移除。
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
        ok = cand_total > 200 and n_with == 209 and n_oob == 0
        print(("OK  " if ok else "MISS") +
              f" 静态表 · 候选池完整（候选 {cand_total} 条 / 有目标任务 {n_with} / 切片越界 {n_oob}）")
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
        #   ① 结构/数组存在；② 计数与实测对齐（290 条对话 / 341 条条件）；
        #   ③ 全部对话与全部任务的切片不越界；④ 有门槛任务数 = 60；
        #   ⑤ 实测样本「大器晚成」（0x00270717）的门槛 = 「孤立无援」（0x0027071B）完成。
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
        ok = (info_cond_total == 341 and len(g_rows) == 290 and n_oob_g == 0
              and n_info_tasks == 60 and n_oob_t == 0)
        print(("OK  " if ok else "MISS") +
              f" 静态表 · INFO 门槛完整（对话 {len(g_rows)} 条 / 条件 {info_cond_total} 条 / "
              f"有门槛任务 {n_info_tasks} / 切片越界 {n_oob_g + n_oob_t}）")
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
                        r"\{\s*0x0027071Bu,\s*0u,\s*1u,\s*1u,\s*0u\s*\},", blob) is not None
        print(("OK  " if ok_bot else "MISS") +
              " 静态表 · 大器晚成 INFO 门槛（孤立无援 0x0027071B 完成）")
        all_ok &= ok_bot
    else:
        print(f"MISS 缺少 {table_h}")
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

    print("---")
    print("全部通过" if all_ok else "存在缺失（见上面的 MISS）")
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
