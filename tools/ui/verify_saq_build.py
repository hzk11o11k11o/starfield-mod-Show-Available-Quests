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

用法：python tools/ui/verify_saq_build.py
"""
from __future__ import annotations

import pathlib
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
        # 第 28 轮：入口「离得太远、引用未加载」的如实提示（与任务的「没有导航目标」分开）
        "入口太远描述(中)": "你现在离这个位置还很远".encode(),
        "入口太远描述(英)": b"You are too far from this location",
        "入口太远提示": "暂时无法导航（离得太远）".encode(),
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
            "入口条目数据": "任务板 · 新亚特兰蒂斯".encode(),
            "引导确认降噪文案": "关菜单后自动确认".encode(),
            # 第 28 轮：入口可用性的运行时判定（LookupByID；与脚本 Game.GetForm 同源）
            "入口统计列": "入口={}(可导航 {})".encode(),
            "入口太远不写通道": "的任务板引用当前取不到".encode(),
        }.items():
            all_ok &= check(f"DLL · {name}", blob, needle)
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
    for label, path in (("工作区", ROOT / "esm/SAQ_ShowAvailableQuests.esm"),
                        ("MO2 部署", MO2_MOD / "SAQ_ShowAvailableQuests.esm")):
        if path.exists():
            blob = path.read_bytes()
            all_ok &= check(f"ESM({label}) · 测试开关 GLOB", blob, b"SAQ_TestMode")
            # ★ 第 21 轮：引导目标高位 GLOB（+ VMAD 属性绑定）
            all_ok &= check(f"ESM({label}) · 引导目标高位 GLOB", blob, b"SAQ_GuidePrefix")
        else:
            print(f"MISS 缺少 {path}")
            all_ok = False

    print("---")
    print("全部通过" if all_ok else "存在缺失（见上面的 MISS）")
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
