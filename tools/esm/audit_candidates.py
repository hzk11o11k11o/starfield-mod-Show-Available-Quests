#!/usr/bin/env python3
"""audit_candidates.py - 覆盖面复盘第二步：把「有名字的未收录任务」分成真任务 / 容器。

输入：ref/coverage_audit.json（tools/esm/audit_coverage.py 产物）+ ref/quests_all.json。
流程（第 106 轮定稿）：
  ① 取「无 QTYP + 有正式本地化名」的候选（约 1000 条）；
  ② 排除内部类别关键词（对话 / 场景 / 遭遇 / 指示器 / 模板 / …）⇒ 约 289 条；
  ③ **核心判据 `subs.QOBJ > 0`（有任务目标子记录）** ⇒ 真任务（约 20 条）；
     QOBJ=0 且无 QTGL ⇒ 氛围 / 场景容器（如 City_*_FAB_Quest*），**不是可接任务**。

输出：真任务清单（含 stage 数 / QOBJ / VMAD 大小 / ctda 数）+ 容器清单摘要。

★ 结论要人工逐条核验再决定收不收（第 106 轮：20 条里 7 收 / 13 不收或待定 ——
  详见 docs/12 三节）。判据与理由都在那里。

用法：
    python tools/esm/audit_candidates.py            # 真任务在前
"""
from __future__ import annotations
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

d = json.loads((ROOT / "ref/coverage_audit.json").read_text(encoding="utf-8"))
cands = [r for r in d["all"] if r["qtyp"] is None and (r["nameZh"] or r["nameEn"])]

EX_EDID = re.compile(
    r"Convo|Dialogue|Encounter|Scene|WNPC|Support|Misc|Template|Debug|Test|Patch|"
    r"Trigger|Marker|Enabler|Pointer|SE_KT|BE_KT|BE_|OE_|^SE_|RAD\d|SFFL_SE|SFFL_R\d|"
    r"Companion_|EliteCrew|Traits_|CREW_|SFTER_Dialogue|FactionEncounters|"
    r"SpaceEnc|_Post$|_Misc|_POI\d|_Z\d\d_|LoadDoor|_AV$|Keyword", re.I)
EX_NAME = re.compile(r"对话|场景|遭遇|指示器|指示|模板|测试|调试|启用器|杂项|漫游|闲逛|"
                     r"巡游|战斗对话|标记|容器|载体|图像|图标|提示")
out = [r for r in cands
       if not EX_EDID.search(r["edid"] or "")
       and not EX_NAME.search((r["nameZh"] or "") + (r["nameEn"] or ""))]

qall = json.loads((ROOT / "ref/quests_all.json").read_text(encoding="utf-8"))
by = {(x.get("master") or "Starfield.esm", int(x["local"]) & 0xFFFFFF): x for x in qall}

rows = []
for r in out:
    q = by.get((r["master"], r["local"]))
    if not q:
        continue
    subs = q.get("subs") or {}
    rows.append({
        "edid": r["edid"], "name": r["nameZh"] or r["nameEn"],
        "master": r["master"], "local": r["local"],
        "nstage": len(q.get("stages") or []),
        "qobj": subs.get("QOBJ", 0),     # ★ 任务目标（>0 ⇒ 玩家可见的任务）
        "qtgl": subs.get("QTGL", 0),     # 目标位置引用
        "vmad": q.get("vmad_size", 0),
        "nctda": len(q.get("ctda") or []),
    })

real = [x for x in rows if x["qobj"] > 0]
scene = [x for x in rows if x["qobj"] == 0]
print(f"候选 {len(rows)} 条 → 有任务目标（QOBJ>0）**真任务** {len(real)} 条；"
      f"无目标（氛围/场景容器）{len(scene)} 条\n")
print(f"{'stage':>6}{'QOBJ':>6}{'vmad':>7}{'ctda':>5}  EDID / 名字")
for x in sorted(real, key=lambda y: -y["qobj"]):
    print(f"{x['nstage']:>6}{x['qobj']:>6}{x['vmad']:>7}{x['nctda']:>5}  "
          f"{x['edid']:<44} {x['name']}")
print("\n--- 无任务目标（不收）---")
for x in sorted(scene, key=lambda y: y["edid"] or ""):
    print(f"  {x['edid']:<46} {x['name']}")
