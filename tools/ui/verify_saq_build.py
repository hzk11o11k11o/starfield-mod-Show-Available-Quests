#!/usr/bin/env python3
"""verify_saq_build.py - 构建后验证：新代码特征是否真的进了四个产物。

为什么需要：SWF/DLL/PEX 都是二进制，肉眼无法确认「刚改的字符串/函数名在不在里面」。
本脚本按特征串逐个检查（SWF 先解 CWS 的 zlib 压缩），任何一处缺失都会退出码非 0。

检查的特征（随版本演进补充；旧特征缺失代表功能被回退，不要删）：
  第 16 轮：SAQ_GuideReply / SAQ_SyncGuideState / 引导失败文案 / 各类新日志

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
        }.items():
            all_ok &= check(f"DLL · {name}", blob, needle)
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
    else:
        print(f"MISS 缺少 PEX {pex}")
        all_ok = False

    print("---")
    print("全部通过" if all_ok else "存在缺失（见上面的 MISS）")
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
