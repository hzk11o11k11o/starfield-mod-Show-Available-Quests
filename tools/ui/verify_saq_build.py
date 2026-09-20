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

用法：python tools/ui/verify_saq_build.py
"""
from __future__ import annotations

import json
import pathlib
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


def check_esm_markers(path: pathlib.Path, expect_refs: set[int], label: str) -> bool:
    """★ 第 30 轮：expect_refs 里的任务板必须各有一条**新建的常驻 XMarker marker**。

    第 29 轮的 override 路线已被实机 + 数据双重否定（override 只替换记录数据、不改变引用的
    加载分类；官方 70 条同类 override 原记录本来就全是常驻）—— 现在改成本插件空间（记录号
    0x900+i）的**新记录**（tools/esm/create_board_markers.py）：

      * EDID = `SAQ_BoardMarker_<板记录号>`、base = XMarker(0x3B)（无模型、纯位置标记）
      * flags = 0x400、组链 = … > CellChildren > CellPersistent
      * 记录头 FormID 的空间索引 = 本文件 MAST 数量（自身空间；写错会落进别的 master 空间）

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
            if bytes(buf[p:p + 4]) in REF_SIGS:
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
    ok = hit == len(expect_refs) and not problems
    print(("OK  " if ok else "MISS") +
          f" ESM({label}) · 新建常驻 marker {hit}/{len(expect_refs)} 条"
          f"（XMarker + CellPersistent + 0x400）")
    for p_ in problems:
        print(f"       - {p_}")
    return ok


def main() -> int:
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

    dll = ROOT / "plugin/build/windows/x64/releasedbg/SAQ_ShowAvailableQuests.dll"
    if dll.exists():
        blob = dll.read_bytes()
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
        }.items():
            all_ok &= check(f"DLL · {name}", blob, needle)
        # 反向检查：第 31 轮把候选链顺序换掉，第 30 轮的「marker 优先」诊断文案不应再出现
        gone = "这些条目没走新建的常驻 marker".encode() not in blob
        print(("OK  " if gone else "MISS") + " DLL · 旧候选链诊断文案已替换(反向检查)")
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
    else:
        print(f"MISS 缺少 PEX {pex}")
        all_ok = False

    # ★ 第 20 轮：ESM 里的测试开关 GLOB（控制台 `set SAQ_TestMode to N` 的落点）
    # ★ 第 30 轮：同时按组结构解析「11 条任务板的新建常驻 XMarker marker」（数据侧保证，
    #   不只是特征串）—— 第 29 轮的 override 路线已被实机否定，见 check_esm_markers。
    entries = json.loads((ROOT / "ref/entry_targets.json").read_text(encoding="utf-8"))
    expect_markers = {e["refLocal"] for e in entries if e.get("markerLocal")}
    for label, path in (("工作区", ROOT / "esm/SAQ_ShowAvailableQuests.esm"),
                        ("MO2 部署", MO2_MOD / "SAQ_ShowAvailableQuests.esm")):
        if path.exists():
            blob = path.read_bytes()
            all_ok &= check(f"ESM({label}) · 测试开关 GLOB", blob, b"SAQ_TestMode")
            # ★ 第 21 轮：引导目标高位 GLOB（+ VMAD 属性绑定）
            all_ok &= check(f"ESM({label}) · 引导目标高位 GLOB", blob, b"SAQ_GuidePrefix")
            all_ok &= check_esm_markers(path, expect_markers, label)
        else:
            print(f"MISS 缺少 {path}")
            all_ok = False

    print("---")
    print("全部通过" if all_ok else "存在缺失（见上面的 MISS）")
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
