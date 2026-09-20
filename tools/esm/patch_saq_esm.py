#!/usr/bin/env python3
r"""patch_saq_esm.py - 给代理任务 SAQ_MainQuest 挂上「引导别名 + 引导目标」。

## 为什么要有这一步

需求里的引导（任务标记蓝点 + 扫描仪路径线）只有**正在运行、且有「已显示目标」**
的任务才有。未接取的任务引擎不管，所以 MOD 用一个代理任务把玩家导向目标引用：

    SAQ_MainQuest（Start Game Enabled，本补丁给它加）
      ├─ Reference Alias id=0  SAQ_GuideTarget   （不填，运行时由脚本 ForceRefTo）
      └─ Objective   index=10  NNAM=<Alias=SAQ_GuideTarget>
                                └─ Target: Alias 0

运行时脚本只需要 `SetObjectiveDisplayed(10)` + `SetActive(true)`，引擎就会画标记。

## 为什么用手工字节补丁（而不是 xEdit 写记录）

xEdit 的 Pascal 脚本 API 对「往记录里塞别名/目标」没有稳的写法（ElementAssign 对
多型别列表行为不确定），而这个文件只有几百字节、格式已经完全掌握。**记录格式来自
Starfield.esm 里的真实样板**（证据在 docs/05）：

    Reference Alias（无填充方式，脚本填充型，示例 SQ_Followers\AvailableFollowers）
      ALST(4)=别名id | ALID(N)=名字+NUL | FNAM(4)=标志 | ALFG(4) | VTCK(4) | ALED(0)
    Objective（示例 MB_Bounty01Far 的目标）
      QOBJ(2)=目标索引 | FNAM(4)=标志 | NNAM(文本) | QSTA(12)=别名id|标志|关键词
    ANAM(4) = 下一个空闲别名 id

文本用**内联字符串**（TES4 头里没有 0x80 = Localized 标志，实测本文件 flags=0x01），
所以不需要往游戏的 strings 里加 ID —— 目标文本直接写 `<Alias=SAQ_GuideTarget>`，
运行时引擎会用**目标引用自己的本地化名字**替换它（中英随游戏语言）。

## 幂等

每次运行都会先删掉记录里所有目标/别名相关子记录，再重新写一份 ⇒ 反复运行结果一致，
xEdit 重建 ESM（tools/run-esm-build.ps1）之后重新跑本工具即可。

## 第 20 轮：测试开关 GLOB（SAQ_TestMode）

控制台测试过滤（`set SAQ_TestMode to 1`）需要一个 DLL 能读到、玩家能改的全局变量。
SFSE 没有「注册控制台命令」的接口（见 SFSE\Interfaces.h：只有 Messaging/Trampoline/
Menu/Task），所以走最稳的路：**ESM 里加一条 GLOB**，玩家用游戏自带的控制台 `set`
命令改它，DLL 每次开菜单读一次。

本工具负责保证这条 GLOB 存在（记录号 0x804，初值 0），并且：
* **已存在就不动**（保留玩家当前设置的值；重新构建不会把测试模式清掉）；
* 新增时顺带把 TES4 HEDR 的 numRecords +1、nextObjectID 提到 ≥ 0x805。

用法：
    python tools/esm/patch_saq_esm.py                     # 原地补 esm/SAQ_ShowAvailableQuests.esm
    python tools/esm/patch_saq_esm.py --check             # 只解析并打印当前记录结构
"""
from __future__ import annotations

import argparse
import struct
import sys
from pathlib import Path

DEFAULT_ESM = "esm/SAQ_ShowAvailableQuests.esm"

QUEST_EDID = "SAQ_MainQuest"
ALIAS_ID = 0
ALIAS_NAME = "SAQ_GuideTarget"
ALIAS_FLAGS = 0x02          # 与 SQ_Followers\AvailableFollowers（脚本填充型别名）一致
OBJECTIVE_INDEX = 10
# ★ 文本必须带 NUL 终止（第 12 轮实证）：对照两个非本地化第三方 ESM 的文本子记录，
#   StarfieldAlwaysScan.esm 的 FULL 长度 12 = "Always Scan"(11)+NUL，
#   morelore_mantislegacy.esm 的 NNAM 也都是「文本长度+1」。
#   第 11 轮我们没有写 NUL（len=23 = 恰好 23 个可见字符），游戏里 HUD「任务更新」
#   显示成 "[...]"（文本为空）——补上 NUL 是这一轮的直接修复。
# ★ 第 13 轮：目标文本从 `<Alias=SAQ_GuideTarget>` 改成**固定文案**。
#   第 12 轮补了 NUL 后 HUD 仍显示 `[…]` ⇒ 别名替换没生效。实证：
#     • 扫遍本机所有非本地化第三方 ESM（QUST 内联 NNAM 共 9 条）——**没有一条**用 `<Alias=...>`；
#     • 原版（Starfield.esm）的 `<Alias=...>` 全部出现在**本地化 strings 表**里
#       （记录里只存字符串 ID，例如 0x0002D33A = "Collect the bounty on the <Alias=PrimaryRef> …"）。
#   ⇒「内联文本走别名替换」这条路没有先例，先用固定文案保证能显示。
#    「去找谁/去哪」由引导的蓝点 + 扫描仪路径线承担（QSTA 仍指向别名 0，不动）。
OBJECTIVE_TEXT = "前往接取地点".encode("utf-8") + b"\x00"
# 代理任务的任务名（QUST 记录级 FULL）。同样要 NUL 终止。
# 为什么要有名字：引擎会把「正在运行 + 有已显示目标」的任务塞进玩家任务日志
#   （第 11 轮日志实证：qdata 列表里出现「f000800:」——名字为空的那条就是它），
#   没名字时 HUD 的任务更新提示与任务日志都显示成空白/省略号。
QUEST_NAME = "可接任务".encode("utf-8") + b"\x00"

# ★ 第 20 轮：控制台测试开关（GLOB）。0x801..0x803 已被三个通道 GLOB 占用。
TEST_MODE_EDID = "SAQ_TestMode"
TEST_MODE_FORMID = 0x804

# ★ 第 21 轮：引导目标的「高位字节」（FormID >> 24）。
#
# 起因（实机 bug）：GLOB 是 float（尾数 24 位），完整 FormID 一旦 > 2^24
# （DLC 的引用，如 0x0107BDB2 = 17,284,530）就可能丢精度（奇数不可表示）——
# 轻则引导失效，重则指向**相邻的另一条记录**（错误的引导目标）。
# 拆成「低 24 位（≤0xFFFFFF 永远精确）+ 高 8 位（≤0xFF 永远精确）」两个 GLOB 后，
# 运行期拼接 = 精确。脚本按 `GuidePrefix 是否存在` 自动兼容旧通道。
GUIDE_PREFIX_EDID = "SAQ_GuidePrefix"
GUIDE_PREFIX_FORMID = 0x805

# 需要保证存在的 GLOB：(EDID, 记录号, 说明)
EXTRA_GLOBS = (
    (TEST_MODE_EDID, TEST_MODE_FORMID, "测试过滤开关（ini / 控制台，见 docs/05 第八节）"),
    (GUIDE_PREFIX_EDID, GUIDE_PREFIX_FORMID, "引导目标 FormID 高位（float 精度问题，见 docs/05）"),
)

# 记录里「目标 / 别名」相关的子记录（重建时先全部删掉）
ALIAS_SUBS = {b"ALST", b"ALLS", b"ALID", b"ALFG", b"ALED", b"VTCK", b"ALFA", b"ALRT",
              b"ALUA", b"ALFR", b"ALFL", b"ALCS", b"ALCO", b"ALFE", b"ALFI", b"ALPS",
              b"ALSP", b"ALFC", b"ALPC", b"ALCM", b"ALCC", b"ALNA", b"ALUB", b"ALEQ",
              b"ALSY", b"ALKF"}
OBJ_SUBS = {b"QOBJ", b"QSTA", b"NNAM", b"ANAM"}


def make_sub(sig: bytes, payload: bytes) -> bytes:
    return sig + struct.pack("<H", len(payload)) + payload


def split_subs(payload: bytes) -> list[tuple[bytes, bytes]]:
    out = []
    p = 0
    while p + 6 <= len(payload):
        sig = payload[p:p + 4]
        n = struct.unpack_from("<H", payload, p + 4)[0]
        if p + 6 + n > len(payload):
            raise ValueError(f"子记录越界 @{p}: {sig!r} len={n}")
        out.append((sig, payload[p + 6:p + 6 + n]))
        p += 6 + n
    return out


def build_quest_payload(old_payload: bytes) -> tuple[bytes, dict]:
    subs = split_subs(old_payload)
    info: dict = {"edid": "", "kept": [], "dropped": []}
    for sig, sp in subs:
        if sig == b"EDID":
            info["edid"] = sp.split(b"\x00")[0].decode("latin1")
    if info["edid"] != QUEST_EDID:
        raise SystemExit(f"这条 QUST 不是 {QUEST_EDID}（实际 {info['edid']!r}）")

    # ★ 用白名单重建，而不是「删掉已知的」：FNAM/NNAM/VTCK 在目标与别名里都会出现，
    #   用黑名单会把上一次运行留下的 FNAM 带进来（踩过一次：记录里出现两个多余的 FNAM）。
    # ★ 第 12 轮：FULL 从白名单去掉 —— 每次都用我们自己的 QUEST_NAME 重写一遍，
    #   保证「任务名」这一项也是幂等的（旧 FULL 一律丢弃）。
    keep = {b"EDID", b"VMAD", b"DNAM", b"NAM3", b"NEXT", b"QTYP", b"ENAM", b"QTGL"}
    head, tail = [], []
    for sig, sp in subs:
        if sig not in keep:
            info["dropped"].append(sig.decode("latin1"))
            continue
        # 目标放在「记录级字段之后、别名之前」：保留原顺序，遇到第一个别名/目标就切换
        head.append(make_sub(sig, sp))
        # 任务名（FULL）紧跟 EDID（BGS 惯例的排布）
        if sig == b"EDID":
            head.append(make_sub(b"FULL", QUEST_NAME))

    # 目标
    head.append(make_sub(b"QOBJ", struct.pack("<H", OBJECTIVE_INDEX)))
    head.append(make_sub(b"FNAM", struct.pack("<I", 0)))
    head.append(make_sub(b"NNAM", OBJECTIVE_TEXT))
    head.append(make_sub(b"QSTA", struct.pack("<III", ALIAS_ID, 0, 0)))
    head.append(make_sub(b"ANAM", struct.pack("<I", ALIAS_ID + 1)))
    # 别名
    head.append(make_sub(b"ALST", struct.pack("<I", ALIAS_ID)))
    head.append(make_sub(b"ALID", ALIAS_NAME.encode("latin1") + b"\x00"))
    head.append(make_sub(b"FNAM", struct.pack("<I", ALIAS_FLAGS)))
    head.append(make_sub(b"ALFG", struct.pack("<I", 0)))
    head.append(make_sub(b"VTCK", struct.pack("<I", 0)))
    head.append(make_sub(b"ALED", b""))
    return b"".join(head + tail), info


def make_glob_payload(edid: str, value: float) -> bytes:
    """GLOB 记录的 payload：EDID(名字+NUL) + FLTV(float)。格式照抄现有 GLOB 记录。"""
    return (make_sub(b"EDID", edid.encode("latin1") + b"\x00") +
            make_sub(b"FLTV", struct.pack("<f", value)))


def has_nested_groups(buf: bytes) -> bool:
    """顶层组里再出现 GRUP ⇒ 有嵌套组（第 29 轮的 CELL override 组就是嵌套结构）。

    为什么需要这个检查：本工具用「线性重建」处理顶层组 —— 遇到嵌套组会把层级拍平
    （内层组被当成同级组重写），静默破坏文件。所以一旦发现嵌套组，宁可拒绝运行。
    """
    pos = 24 + struct.unpack_from("<I", buf, 4)[0]
    while pos + 24 <= len(buf):
        if buf[pos:pos + 4] != b"GRUP":
            return False
        gsize = struct.unpack_from("<I", buf, pos + 4)[0]
        p = pos + 24
        end = pos + gsize
        while p + 4 <= end:
            if buf[p:p + 4] == b"GRUP":
                return True
            if p + 24 > end:
                break
            size = struct.unpack_from("<I", buf, p + 4)[0]
            p += 24 + size
        pos += gsize
    return False


def has_edid(buf: bytes, edid: str) -> bool:
    """整个文件里有没有这个 EDID 的记录（任何类型）。"""
    for kind, _off, hdr, payload in walk_linear(buf):
        if kind != "REC":
            continue
        for s, sp in split_subs(payload):
            if s == b"EDID" and sp.split(b"\x00")[0].decode("latin1") == edid:
                return True
    return False


def bump_tes4_hedr(head: bytearray, add_records: int, min_next_id: int) -> None:
    """把 TES4 头里 HEDR 的 numRecords 增加 add_records、nextObjectID 提到至少 min_next_id。

    HEDR payload = version(float 4) + numRecords(uint32) + nextObjectID(uint32)。
    （xEdit 生成的值：numRecords=6=4 记录+2 MAST，nextObjectID=0x804=最后一个记录号+1。）
    """
    size = struct.unpack_from("<I", head, 4)[0]
    p = 24
    end = 24 + size
    while p + 6 <= end:
        sig = bytes(head[p:p + 4])
        n = struct.unpack_from("<H", head, p + 4)[0]
        if sig == b"HEDR" and n >= 12:
            base = p + 6
            num = struct.unpack_from("<I", head, base + 4)[0]
            nxt = struct.unpack_from("<I", head, base + 8)[0]
            struct.pack_into("<I", head, base + 4, num + add_records)
            if nxt < min_next_id:
                struct.pack_into("<I", head, base + 8, min_next_id)
            return
        p += 6 + n


def walk_linear(buf: bytes):
    """线性遍历（**不依赖 GRUP 的 size**）：yield ('GRUP'|'REC', offset, hdr, payload)。

    为什么不用组 size 来定边界：一旦某次写入把组 size 写歪了，按组 size 走就会漏记录，
    于是「修不好」——线性走法对这种残留错误免疫（GRUP 头就当 24 字节的标记跳过）。
    """
    pos = 24 + struct.unpack_from("<I", buf, 4)[0]
    while pos + 24 <= len(buf):
        sig = buf[pos:pos + 4]
        size = struct.unpack_from("<I", buf, pos + 4)[0]
        if sig == b"GRUP":
            yield ("GRUP", pos, buf[pos:pos + 24], b"")
            pos += 24
            continue
        if pos + 24 + size > len(buf):
            break
        yield ("REC", pos, buf[pos:pos + 24], buf[pos + 24:pos + 24 + size])
        pos += 24 + size


def iter_file_structure(buf: bytes):
    """yield ('TES4'|'GRUP'|'REC', offset, sig, size, payload_bytes)。"""
    head_size = struct.unpack_from("<I", buf, 4)[0]
    yield ("TES4", 0, b"TES4", head_size, buf[24:24 + head_size])
    for kind, off, hdr, payload in walk_linear(buf):
        yield (kind, off, hdr[0:4], struct.unpack_from("<I", hdr, 4)[0], payload)


def describe(path: Path) -> int:
    buf = path.read_bytes()
    print(f"{path}（{len(buf)} B）")
    for kind, off, sig, size, payload in iter_file_structure(buf):
        if kind == "TES4":
            flags = struct.unpack_from("<I", buf, 8)[0]
            print(f"  TES4 @0x{off:X} size={size} flags={flags:#010x}"
                  f"（Localized={'是' if flags & 0x80 else '否'}，ESM={'是' if flags & 1 else '否'}）")
            masters = []
            p = 0
            while p + 6 <= len(payload):
                s = payload[p:p + 4]
                n = struct.unpack_from("<H", payload, p + 4)[0]
                if s == b"MAST":
                    masters.append(payload[p + 6:p + 6 + n].split(b"\x00")[0].decode("latin1"))
                p += 6 + n
            print(f"     masters: {masters}")
        elif kind == "GRUP":
            print(f"  GRUP @0x{off:X} size={size} label={buf[off + 8:off + 12].decode('latin1')}")
        else:
            subs = split_subs(payload)
            edid = ""
            for s, sp in subs:
                if s == b"EDID":
                    edid = sp.split(b"\x00")[0].decode("latin1")
            extra_glob = ""
            if sig == b"GLOB":
                for s, sp in subs:
                    if s == b"FLTV" and len(sp) == 4:
                        extra_glob = f"  value={struct.unpack('<f', sp)[0]:g}"
            print(f"    REC {sig.decode('latin1')} @0x{off:X} size={size} EDID={edid}{extra_glob}")
            if sig == b"QUST":
                for i, (s, sp) in enumerate(subs):
                    extra = ""
                    if s in (b"ALID", b"NNAM"):
                        extra = f"  {sp!r}"
                    elif s in (b"ALST", b"FNAM", b"ALFG", b"ANAM", b"QOBJ"):
                        extra = "  " + sp.hex(" ")
                    print(f"        [{i:3d}] {s.decode('latin1')} len={len(sp):3d}{extra}")
    return 0


def rebuild_file(buf: bytes, target_formid: int, new_payload: bytes,
                 glob_extras: list[tuple[int, bytes]] | None = None) -> bytes:
    """整体重新序列化（文件只有几百字节）：只换目标记录的 payload，其余原样搬运。

    组 size 是**重算**出来的，不是「原值 + 增量」—— 万一之前有过一次写坏（组 size 与
    记录对不上），增量法会把错误继承下去（踩过一次）。

    glob_extras = [(记录号低 24 位, payload), …]：往 GLOB 组的**末尾**追加新记录
    （测试开关 / 引导目标高位，见 EXTRA_GLOBS）。记录头以组内第一条记录为模板
    （flags/时间戳/FormVersion 全继承），只改 size 与 FormID 低位 —— 不靠猜字段。
    """
    head_size = struct.unpack_from("<I", buf, 4)[0]
    out = bytearray(buf[:24 + head_size])
    pending_hdr: bytes | None = None
    pending_records: list[tuple[bytes, bytes]] = []
    pending_is_glob = False

    def flush() -> None:
        nonlocal pending_hdr, pending_records, pending_is_glob
        if pending_hdr is None:
            return
        if pending_is_glob and glob_extras:
            if not pending_records:
                raise SystemExit("GLOB 组是空的 —— 没有可用的记录头模板，先跑一次 xEdit 生成")
            tmpl = bytearray(pending_records[0][0])
            for formid_low, extra_payload in glob_extras:
                hdr = bytearray(tmpl)
                struct.pack_into("<I", hdr, 4, len(extra_payload))
                cur_id = struct.unpack_from("<I", hdr, 12)[0]
                struct.pack_into("<I", hdr, 12, (cur_id & 0xFF000000) | formid_low)
                pending_records.append((bytes(hdr), extra_payload))
            bump_tes4_hedr(out, len(glob_extras), max(low for low, _ in glob_extras) + 1)
        gsize = 24 + sum(24 + len(pl) for _, pl in pending_records)
        hdr = bytearray(pending_hdr)
        hdr[4:8] = struct.pack("<I", gsize)
        out.extend(hdr)
        for rhdr, pl in pending_records:
            out.extend(rhdr)
            out.extend(pl)
        pending_hdr = None
        pending_records = []
        pending_is_glob = False

    for kind, _off, hdr, payload in walk_linear(buf):
        if kind == "GRUP":
            flush()
            pending_hdr = hdr
            pending_records = []
            pending_is_glob = hdr[8:12] == b"GLOB"
            continue
        rhdr = bytearray(hdr)
        pl = payload
        if rhdr[0:4] == b"QUST" and struct.unpack_from("<I", rhdr, 12)[0] == target_formid:
            pl = new_payload
        rhdr[4:8] = struct.pack("<I", len(pl))
        pending_records.append((bytes(rhdr), pl))
    flush()

    result = bytes(out)
    check_group_bounds(result)
    return result


def check_group_bounds(buf: bytes) -> None:
    """自校验：每条记录都必须正好填满自己所属的 GRUP。"""
    pos = 24 + struct.unpack_from("<I", buf, 4)[0]
    while pos + 24 <= len(buf):
        if buf[pos:pos + 4] != b"GRUP":
            break
        gsize = struct.unpack_from("<I", buf, pos + 4)[0]
        end = pos + gsize
        p = pos + 24
        while p + 24 <= end:
            size = struct.unpack_from("<I", buf, p + 4)[0]
            if p + 24 + size > end:
                raise SystemExit(
                    f"自校验失败：记录 @0x{p:X}（{size} B）越过 GRUP @0x{pos:X} 的边界（{gsize} B）")
            p += 24 + size
        if p != end:
            raise SystemExit(f"自校验失败：GRUP @0x{pos:X} 里的记录到不了组尾（0x{p:X} != 0x{end:X}）")
        pos += gsize


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--esm", default=DEFAULT_ESM)
    ap.add_argument("--check", action="store_true", help="只打印结构，不修改")
    a = ap.parse_args()
    path = Path(a.esm)
    if not path.exists():
        print(f"没有 {path}（先跑 tools/run-esm-build.ps1）")
        return 1
    if a.check:
        return describe(path)

    buf = path.read_bytes()
    flags = struct.unpack_from("<I", buf, 8)[0]
    if flags & 0x80:
        print("警告：TES4 头里 Localized 位被置起来了 —— 内联文本会失效（先确认为什么）")

    # ★ 第 29 轮防呆：本工具不认识嵌套组（CELL override 组）—— 遇到就拒绝运行，
    #   否则线性重建会把层级拍平、静默破坏文件。
    if has_nested_groups(buf):
        print("检测到嵌套组（CELL override 组）—— 本工具不认识嵌套结构，先清掉再跑：")
        print("    python tools/esm/persist_entry_refs.py --clean")
        print("（正常构建顺序是 patch → persist，见 build-saq.ps1）")
        return 1

    quest_off = None
    quest_formid = 0
    for kind, off, hdr, payload in walk_linear(buf):
        if kind == "REC" and hdr[0:4] == b"QUST":
            quest_off = off
            quest_formid = struct.unpack_from("<I", hdr, 12)[0]
            payload_old = payload
            break
    if quest_off is None:
        print("文件里没有 QUST 记录")
        return 1

    new_payload, info = build_quest_payload(payload_old)
    print(f"QUST @0x{quest_off:X} formid={quest_formid:08X}："
          f"payload {len(payload_old)} -> {len(new_payload)} B"
          f"（清掉 {len(info['dropped'])} 个子记录）")

    # ★ 第 20/21 轮：保证附加 GLOB 存在（已存在则原样保留 —— 玩家设置的值不能被清掉）
    glob_extras: list[tuple[int, bytes]] = []
    for edid, low, label in EXTRA_GLOBS:
        if has_edid(buf, edid):
            print(f"GLOB {edid}：已存在（保留当前值）")
        else:
            glob_extras.append((low, make_glob_payload(edid, 0.0)))
            print(f"GLOB {edid}：将新增（记录号 0x{low:03X}，初值 0）—— {label}")

    out = rebuild_file(buf, quest_formid, new_payload, glob_extras)
    path.write_bytes(out)
    print(f"已写回 {path}（{len(out)} B）")

    # 自校验：重新解析一遍
    print("\n--- 自校验（重新解析） ---")
    describe(path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
