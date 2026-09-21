"""op_survey.py - CTDA type 位域体检 + OR 组调查（第 86 轮；原 _tmp_op_survey2.py）。

语义已由反汇编确认（docs/08 4.3）：运算符 = type >> 5、flags = type & 0x1F。
本工具做数据侧交叉验证：零越界断言 + 带 OR 位的进度类外键条件清单。

新语义（引擎侧已实证，见 docs/08 第四节·补）：
  type 是 u32；运算符 = type >> 5（0..5 = ==,!=,>,>=,<,<=）；flags = type & 0x1F：
    bit0 OR / bit1 别名 / bit2 用 GLOB / bit3 Pack Data / bit4 交换主客体

本脚本：
  ① 全量 QUST 记录级 CTDA：验证「type == (op<<5) | (flags & 0x1F)」恒成立、flags 无越界；
  ② 统计运算符×flags 分布；
  ③ 列出「带 OR 位的进度类条件」（外键引用 + 进度函数）—— 这些是当前被放行、
     但按新语义本可纳入 OR 组求值的候选；
  ④ FFConstantZ06 逐条解码（验证第 35 轮的悬案）。
"""
from __future__ import annotations

import json
import struct
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
REF = ROOT / "ref"

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

OPS = {0: "==", 1: "!=", 2: ">", 3: ">=", 4: "<", 5: "<="}
GATE_FUNCS = {"GetQuestRunning", "GetQuestCompleted", "GetStageDone"}


def decode_type(t: int) -> tuple[int, int]:
    return t >> 5, t & 0x1F


def flag_str(f: int) -> str:
    names = []
    if f & 0x01:
        names.append("OR")
    if f & 0x02:
        names.append("别名")
    if f & 0x04:
        names.append("GLOB")
    if f & 0x08:
        names.append("PackData")
    if f & 0x10:
        names.append("交换")
    if f & 0x20:
        names.append("!!越界0x20")
    return "+".join(names) if names else ""


def main() -> int:
    quests = json.loads((REF / "quests.json").read_text(encoding="utf-8"))
    parsed = json.loads((REF / "quests_parsed.json").read_text(encoding="utf-8"))
    raw_by_fid = {q["formid"]: q for q in quests}

    op_dist = Counter()
    flag_dist = Counter()
    bad = []          # 不满足 type == (op<<5)|flags 的
    or_gates = []     # 带 OR 位的进度类条件
    ff06 = []

    for p in parsed:
        fid = int(p["formid"], 16)
        r = raw_by_fid.get(fid)
        if not r:
            continue
        rc = p.get("record_conditions") or []
        raws = r.get("ctda") or []
        for i, xc in enumerate(rc):
            if i >= len(raws):
                break
            b = bytes.fromhex(raws[i])
            if len(b) < 32:
                continue
            t = struct.unpack_from("<I", b, 0)[0]
            op, flags = decode_type(t)
            name = xc.get("Function", "?")
            p1 = struct.unpack_from("<I", b, 12)[0]
            runon = struct.unpack_from("<I", b, 20)[0]

            op_dist[op] += 1
            flag_dist[flags] += 1
            if op > 5 or (flags & ~0x1F):
                bad.append((p.get("edid"), hex(t), op, flags))

            if (flags & 0x01) and name in GATE_FUNCS and runon == 0 and p1 != fid:
                cmpv = round(struct.unpack_from("<f", b, 4)[0], 3)
                or_gates.append(f"{p.get('edid')}: {name}(0x{p1:08X}) {OPS[op]} {cmpv}"
                                f" [{flag_str(flags)}]")

            if "FFConstantZ06" in (p.get("edid") or ""):
                cmpv = round(struct.unpack_from("<f", b, 4)[0], 3)
                ff06.append(f"  {name:<20} type=0x{t:02X} op={OPS[op]:<3} flags={flag_str(flags):<8}"
                            f" cmp={cmpv} p1=0x{p1:08X} runOn={runon}")

    print(f"=== 运算符分布（type >> 5）===")
    for op, n in sorted(op_dist.items()):
        print(f"  {op} ({OPS.get(op, '?')})\t× {n}")
    print(f"\n=== flags 分布（type & 0x1F）===")
    for f, n in sorted(flag_dist.items()):
        print(f"  0x{f:02X} {flag_str(f):<12} × {n}")
    print(f"\n越界项（op>5 或 flags 超出低 5 位）：{len(bad)}")
    for e, t, op, f in bad[:10]:
        print(f"  {e}: type={t} op={op} flags=0x{f:02X}")

    print(f"\n=== 带 OR 位的「进度类外键条件」（当前被放行、可按 OR 组纳入）{len(or_gates)} 条 ===")
    for line in or_gates[:30]:
        print("  " + line)

    print("\n=== FFConstantZ06 逐条解码 ===")
    for line in ff06:
        print(line)
    return 0


if __name__ == "__main__":
    sys.exit(main())
