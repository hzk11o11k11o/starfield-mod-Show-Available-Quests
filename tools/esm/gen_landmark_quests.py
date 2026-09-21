#!/usr/bin/env python3
r"""gen_landmark_quests.py - 第 81 轮：**地球地标任务表**（「雪景球」收集线，10 条）。

起因（玩家 2026-09-21）：
  「我发现『地球地标』系列任务好像在可接任务列表里一个都没有，检查一下」

复查结论（本轮）：
  * 它们此前被 `gen_quest_table.py::filter_reason` 的「地标」规则排除（第 7 轮判断
    「走近即完成、无从『接』」）—— **这个判断不准确**；
  * 正确机制（数据证据）：每条地标任务都有一本对应的**书**
    （如 `Landmark_ApolloBook_NOCLUTTER`「利文斯通爵士的第二篇日志」），书上挂着
    官方脚本 `defaultrefoncontainerchangedto`—— 书**进入玩家物品栏（拾取 / 购买）**
    时，把对应任务 `SetStage(100)` ⇒ 任务出现在玩家日志（Activities）。
    这就是「接取」：**去哪里拿到那本书**。
  * 它们是有目标（访问地标 / 找到雪景球）、可完成、有奖励（集齐 11 个给旧地球宇航服）
    的 Activities ⇒ 符合 MOD 的收录标准。

★ 第 11 条（火星「机遇号」Landmark_Opportunity）**不在本表**：它没有对应的书 /
  可拾取物，由主线「发掘（Unearthed）」期间的博物馆展品互动触发（wiki + 数据侧
  字节级复查：全 ESM 没有引用它的可拾取触发物）—— 属于主线流程内容，不入表。

## 10 条（任务 / 书 / 接取点）

| 任务 | 书（官方中/英名） | 接取点（引导首选） |
| --- | --- | --- |
| Landmark_Apollo     | 利文斯通爵士的第二篇日志 / Sir Livingstone's Second Journal | 陋室（新亚特兰蒂斯城）内的一张桌子 |
| Landmark_Cairo      | 古埃及文明 / The Ancient Civilization of Egypt | 阿基拉城书店（书商阿琼·辛克莱尔**有售**） |
| Landmark_Dubai      | 奔向天堂 / Race to the Heavens | 星之海妖号 VIP 室（深红舰队任务线期间） |
| Landmark_HongKong   | 莫里斯·里昂的日志 / Maurice Lyon's Journal | 新家园（土卫六）博物馆 |
| Landmark_London     | 雾都孤儿 / Oliver Twist | ★ 无固定接取点（书店有售 / 各处书堆；**只给说明**） |
| Landmark_LosAngeles | 霍普家谱 / Hope Family Tree | 霍普科技（罗恩·霍普的办公室） |
| Landmark_NewYork    | 我们失落的遗产 / Our Lost Heritage | 新亚特兰蒂斯城 MAST 大楼（总统办公室） |
| Landmark_Osaka      | 永田恭介的日记 / Diary of Kyosuke Nagata | 星钥站（德尔加多的办公室；深红舰队任务线期间） |
| Landmark_Shanghai   | 现代宏观经济学概论 / Essentials of Modern Macroeconomics | 地球殖民飞船永恒号（教室） |
| Landmark_StLouis    | 命运的代价 / The Price of Destiny | 贸易大楼：巴尤的顶层公寓（霓虹城） |

## 引导候选（写进 ref/landmark_quests.json 的 cands）

* 首选 = 书的世界放置引用（REFR，**非常驻** —— 走进 cell 才会加载）；
* 兜底 = **同 cell 的常驻引用**（离书最近的最多 3 条）—— 远处点引导时先落到它
  （立刻生效、蓝点在书附近），走近后由候选复算自动升级为精确的书（第 45/47 轮机制）；
* Cairo 特殊：书在商店库存里（无世界引用）⇒ 首选 = 书商 AhnjongSinclair 的 ACHR
  （0x1AF6CA「阿琼·辛克莱尔」），兜底 = 她所在 cell 的常驻引用；
* London 特殊：书有 20 处放置（书店 / 各种书堆）⇒ `guide=false`，构建期清空候选
  （与 CF01「深藏不露」同款：界面走「不可导航」通路，点击给提示 + 描述写明原因）。

## 构建期核验（任一不符 ⇒ 不写产物、退出码 1）

① 10 条任务都在 `ref/quests_all.json`（Starfield.esm），QTYP = Activities；
② 10 本书的 VMAD 里：脚本 = `defaultrefoncontainerchangedto`、
   `QuestToSetOrCheck` 属性 == 对应任务的 FormID、`StageToSet` == 100
   （自写精简 VMAD 解析，见 parse_vmad —— 这就是「拾取书会接到这条任务」的直接证据）；
③ 书的官方中/英名从 strings 表取（不写死）；
④ 书的世界放置引用存在（除 Cairo / London），且 base == 书；书所在 cell 有 LCTN
   （取官方地点名写导语的 where / 说明文案）；
⑤ 兜底候选全部是**常驻**引用（CellPersistent 组）；
⑥ 说明文本非空、无 Tab / 换行、≤ 200 字符。

产物：`ref/landmark_quests.json`（gen_quest_table.py 消费：filter 豁免 + 引导候选 +
说明文本 → 载荷最后两列）。

用法：
    python tools/esm/gen_landmark_quests.py           # 扫描 + 核验 + 写产物
    python tools/esm/gen_landmark_quests.py --list    # 只看当前产物
"""
from __future__ import annotations

import argparse
import json
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from esm_probe import DEFAULT_ESM, record_base_form, record_edid, subrecords  # noqa: E402
from scan_entry_persistent import refr_position, walk  # noqa: E402
from strings_probe import load_strings  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
REF = ROOT / "ref"

NOTE_MAX = 200
MAX_FALLBACKS = 3
FALLBACK_MAX_DIST = 60.0   # 兜底候选离书超过这个距离就不要了（避免把蓝点指到房间外）

# ---------------------------------------------------------------------------
# 10 条（顺序 = 产物里的顺序 = 静态表里的顺序，仅作稳定顺序用，不特殊排序）
# ---------------------------------------------------------------------------
LANDMARKS: list[dict] = [
    {
        "key": "Apollo",
        "questEdid": "Landmark_Apollo",
        "bookEdid": "Landmark_ApolloBook_NOCLUTTER",
        "guide": True,
        "noteZh": "拾取《利文斯通爵士的第二篇日志》即可接取"
                  "（新亚特兰蒂斯城·陋室，马蒂奥·卡特里的房间）。",
        "noteEn": "Pick up \"Sir Livingstone's Second Journal\" to start this quest "
                  "(The Lodge, New Atlantis - Matteo Khatri's room).",
    },
    {
        "key": "Cairo",
        "questEdid": "Landmark_Cairo",
        "bookEdid": "Landmark_CairoBook_NOCLUTTER",
        "guide": True,
        "cairoShop": True,
        "noteZh": "在阿基拉城找书商阿琼·辛克莱尔购买《古埃及文明》即可接取。",
        "noteEn": "Buy \"The Ancient Civilization of Egypt\" from the bookseller "
                  "Ahnjong Sinclair in Akila City to start this quest.",
    },
    {
        "key": "Dubai",
        "questEdid": "Landmark_Dubai",
        "bookEdid": "Landmark_DubaiBook_NOCLUTTER",
        "guide": True,
        "noteZh": "拾取《奔向天堂》即可接取（星之海妖号的 VIP 室；"
                  "仅在深红舰队任务线期间可进入）。",
        "noteEn": "Pick up \"Race to the Heavens\" to start this quest "
                  "(VIP room of the Siren of the Stars; only reachable during the "
                  "Crimson Fleet questline).",
    },
    {
        "key": "HongKong",
        "questEdid": "Landmark_HongKong",
        "bookEdid": "Landmark_HongKongBook_NOCLUTTER",
        "guide": True,
        "noteZh": "拾取《莫里斯·里昂的日志》即可接取（土卫六·新家园的博物馆）。",
        "noteEn": "Pick up \"Maurice Lyon's Journal\" to start this quest "
                  "(the museum in New Homestead, Titan).",
    },
    {
        "key": "London",
        "questEdid": "Landmark_London",
        "bookEdid": "EAW_CD_Book_OliverTwist_m",
        "guide": False,      # ★ 无固定接取点：只给说明（见头注释）
        "noteZh": "阅读《雾都孤儿》即可接取（各大城市的书店有售，"
                  "也可在各处书堆里找到）。",
        "noteEn": "Read \"Oliver Twist\" to start this quest "
                  "(sold at bookstores in major cities; also found in book piles).",
    },
    {
        "key": "LosAngeles",
        "questEdid": "Landmark_LosAngeles",
        "bookEdid": "Landmark_LosAngelesBook_NOCLUTTER",
        "guide": True,
        "noteZh": "拾取《霍普家谱》即可接取（霍普镇·霍普科技，罗恩·霍普的办公室）。",
        "noteEn": "Pick up \"Hope Family Tree\" to start this quest "
                  "(HopeTech in Hopetown - Ron Hope's office).",
    },
    {
        "key": "NewYork",
        "questEdid": "Landmark_NewYork",
        "bookEdid": "Landmark_NewYorkBook_NOCLUTTER",
        "guide": True,
        "noteZh": "拾取《我们失落的遗产》即可接取（新亚特兰蒂斯城·MAST 大楼的总统办公室）。",
        "noteEn": "Pick up \"Our Lost Heritage\" to start this quest "
                  "(the President's office in the MAST building, New Atlantis).",
    },
    {
        "key": "Osaka",
        "questEdid": "Landmark_Osaka",
        "bookEdid": "Landmark_OsakaBook_NOCLUTTER",
        "guide": True,
        "noteZh": "拾取《永田恭介的日记》即可接取（星钥站·德尔加多的办公室；"
                  "仅在深红舰队任务线期间可进入）。",
        "noteEn": "Pick up \"Diary of Kyosuke Nagata\" to start this quest "
                  "(Delgado's office on The Key; only reachable during the "
                  "Crimson Fleet questline).",
    },
    {
        "key": "Shanghai",
        "questEdid": "Landmark_Shanghai",
        "bookEdid": "Landmark_ShanghaiBook_NOCLUTTER",
        "guide": True,
        "noteZh": "拾取《现代宏观经济学概论》即可接取（地球殖民飞船永恒号的教室）。",
        "noteEn": "Pick up \"Essentials of Modern Macroeconomics\" to start this quest "
                  "(the classroom aboard the ECS Constant).",
    },
    {
        "key": "StLouis",
        "questEdid": "Landmark_StLouis",
        "bookEdid": "Landmark_StLouisBook_NOCLUTTER",
        "guide": True,
        "noteZh": "拾取《命运的代价》即可接取（霓虹城·贸易大楼：巴尤的顶层公寓）。",
        "noteEn": "Pick up \"The Price of Destiny\" to start this quest "
                  "(Trade Tower: Bayu's Penthouse, Neon).",
    },
]

# Cairo 的书商（book store owner）——书在商店库存里，没有世界放置引用。
SHOP_NPC_EDID = "AhnjongSinclairREF"

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


# ---------------------------------------------------------------------------
# 精简 VMAD 解析
# ---------------------------------------------------------------------------
def rd_u16(b: bytes, p: int) -> tuple[int, int]:
    return struct.unpack_from("<H", b, p)[0], p + 2


def rd_str(b: bytes, p: int) -> tuple[str, int]:
    n, p = rd_u16(b, p)
    return b[p:p + n].split(b"\x00")[0].decode("latin1"), p + n


def parse_vmad(v: bytes) -> list[dict]:
    """解析 VMAD（version 2+）的脚本表 —— 只要脚本名与属性名/值。

    属性值格式（Starfield version 6，实测）：
      * Object(1)：8 字节，**后 4 字节 = FormID**（前 4 字节含 alias=-1）
      * String(2)：长度前缀字符串
      * Int(3)：4 字节
      * Float(4)：4 字节
      * Bool(5)：1 字节
    数组类型（6/0x0C..0x11）本工具用不到，遇到就跳过整段（保守：解析失败即核验报错）。
    """
    out: list[dict] = []
    if len(v) < 6:
        return out
    _ver, p = rd_u16(v, 0)
    _objfmt, p = rd_u16(v, p)
    nscript, p = rd_u16(v, p)
    for _ in range(nscript):
        name, p = rd_str(v, p)
        flags = v[p]
        p += 1
        nprop, p = rd_u16(v, p)
        props: dict[str, object] = {}
        for _ in range(nprop):
            pname, p = rd_str(v, p)
            ptype = v[p]
            p += 2  # type + status
            val: object = None
            if ptype == 1:                 # Object
                raw = v[p:p + 8]
                p += 8
                val = struct.unpack_from("<I", raw, 4)[0]
            elif ptype == 2:               # String
                val, p = rd_str(v, p)
            elif ptype == 3:               # Int
                val = struct.unpack_from("<i", v, p)[0]
                p += 4
            elif ptype == 4:               # Float
                val = struct.unpack_from("<f", v, p)[0]
                p += 4
            elif ptype == 5:               # Bool
                val = v[p]
                p += 1
            else:
                raise ValueError(f"VMAD 属性 {pname} 的类型 {ptype:#x} 未支持（解析会失真）")
            props[pname] = val
        out.append({"name": name, "flags": flags, "props": props})
    return out


def dist(a, b) -> float:
    return sum((x - y) ** 2 for x, y in zip(a, b)) ** 0.5


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--esm", default=DEFAULT_ESM)
    ap.add_argument("--quests", default=str(REF / "quests_all.json"))
    ap.add_argument("--strings-dir", default=str(REF / "strings" / "strings"))
    ap.add_argument("--out", default=str(REF / "landmark_quests.json"))
    ap.add_argument("--list", action="store_true")
    a = ap.parse_args()

    if a.list:
        p = Path(a.out)
        if not p.exists():
            print(f"（还没有 {p} —— 先跑一次本工具）")
            return 0
        for g in json.loads(p.read_text(encoding="utf-8")):
            q, bk = g["quest"], g["book"]
            tag = f"{len(g['cands'])} 个候选" if g["guide"] else "只给说明（构建期清空候选）"
            print(f"  {g['key']:<11} {q['nameZh']} / {q['nameEn']}  0x{q['local']:06X}  [{tag}]")
            print(f"      书：{bk['nameZh']} / {bk['nameEn']}  0x{bk['local']:06X}")
            print(f"      说明：{g['noteZh']}")
            for c in g["cands"]:
                print(f"        - {c['src']:<8} 0x{c['refr']:06X} 常驻={c['persistent']} "
                      f"{c.get('nameZh') or c.get('nameEn') or ''}")
            print(f"      证据：{g['evidence']}")
        return 0

    qpath = Path(a.quests)
    if not qpath.exists():
        print(f"（没有 {qpath} —— 保留现有 {a.out}，跳过核验）")
        return 0
    strings_dir = Path(a.strings_dir)
    if not (strings_dir / "starfield_en.strings").exists():
        print(f"（没有官方 strings 表 {strings_dir} —— 保留现有 {a.out}，跳过核验）")
        return 0
    str_en = load_strings(strings_dir / "starfield_en.strings")
    str_zh = load_strings(strings_dir / "starfield_zhhans.strings")

    quests = json.loads(qpath.read_text(encoding="utf-8"))
    q_by_edid = {(q.get("edid") or ""): q for q in quests if q.get("master") == "Starfield.esm"}

    want_quest_edids = {e["questEdid"] for e in LANDMARKS}
    want_book_edids = {e["bookEdid"] for e in LANDMARKS}

    problems: list[str] = []

    # ---- 第一遍：QUST / BOOK / CELL(XLCN) / LCTN(FULL) / 书的 REFR / 书商 ACHR ----
    buf = Path(a.esm).read_bytes()
    print(f"读 {a.esm} …")
    quests_esm: dict[str, dict] = {}     # EDID -> {local, full, qtyp, formid}
    books_esm: dict[str, dict] = {}      # EDID -> {local, full, vmad}
    book_by_local: dict[int, dict] = {}
    book_refs: dict[int, list] = {}      # 书 local -> [REFR 行]
    cell_lctn: dict[int, int] = {}       # cell formid -> lctn formid
    lctn_full: dict[int, int] = {}
    npc_rows: dict[int, dict] = {}       # NPC_ local -> {full}
    shop_npc_refs: list = []
    target_cell_hint: set = set()
    target_world_hint: set = set()

    def cb1(sig, formid, flags, chain, cell, world, payload):
        low = formid & 0xFFFFFF
        if sig == b"QUST":
            edid = record_edid(payload)
            if edid in want_quest_edids:
                full = None
                qtyp = None
                for s, sp in subrecords(payload):
                    if s == b"FULL" and len(sp) >= 4:
                        full = struct.unpack_from("<I", sp, 0)[0]
                    elif s == b"QTYP" and len(sp) >= 4:
                        qtyp = struct.unpack_from("<I", sp, 0)[0]
                quests_esm[edid] = {"local": low, "formid": formid, "full": full, "qtyp": qtyp}
            return
        if sig == b"BOOK":
            edid = record_edid(payload)
            if edid in want_book_edids:
                full = None
                vmad = None
                for s, sp in subrecords(payload):
                    if s == b"FULL" and len(sp) >= 4:
                        full = struct.unpack_from("<I", sp, 0)[0]
                    elif s == b"VMAD":
                        vmad = sp
                books_esm[edid] = {"local": low, "full": full,
                                   "vmad": parse_vmad(vmad) if vmad else []}
                book_by_local[low] = books_esm[edid]
            return
        if sig == b"CELL":
            for s, sp in subrecords(payload):
                if s == b"XLCN" and len(sp) >= 4:
                    cell_lctn[low] = struct.unpack_from("<I", sp, 0)[0] & 0xFFFFFF
            return
        if sig == b"LCTN":
            for s, sp in subrecords(payload):
                if s == b"FULL" and len(sp) >= 4:
                    lctn_full[low] = struct.unpack_from("<I", sp, 0)[0]
            return
        if sig == b"NPC_":
            for s, sp in subrecords(payload):
                if s == b"FULL" and len(sp) >= 4:
                    npc_rows[low] = {"full": struct.unpack_from("<I", sp, 0)[0]}
            return
        if sig in (b"REFR", b"ACHR"):
            edid = record_edid(payload) or ""
            if edid == SHOP_NPC_EDID:
                shop_npc_refs.append({"sig": sig.decode("latin1"), "local": low,
                                      "base": record_base_form(payload) & 0xFFFFFF,
                                      "cell": cell, "world": world, "flags": flags,
                                      "pos": refr_position(payload),
                                      "persistent": bool(flags & 0x400) or (chain and chain[-1][0] == 8)})
                target_cell_hint.add(cell)
                if world:
                    target_world_hint.add(world)
            base = record_base_form(payload) & 0xFFFFFF
            if base in book_by_local:
                pos = refr_position(payload)
                book_refs.setdefault(base, []).append({
                    "local": low, "base": base, "flags": flags, "cell": cell,
                    "world": world,
                    "pos": pos, "edid": edid,
                    "persistent": bool(flags & 0x400) or bool(chain and chain[-1][0] == 8),
                })
                if pos:
                    target_cell_hint.add(cell)
                if world:
                    target_world_hint.add(world)

    walk(buf, cb1)

    # ---- 第二遍：目标 cell / 目标 world 的常驻引用（兜底候选）----
    #
    # ★ 外景（如阿基拉城的街区）里官方**不放 per-cell 常驻引用**（第 80 轮实测：
    #   CityAkilaSlums01 的 8698 条引用里 0 条常驻）——外景的常驻引用在 **world 级**
    #   （`WRLD > WorldChildren > CellChildren > CellPersistent`），所以两个来源都收。
    print(f"目标 cell {len(target_cell_hint)} 个 / world {len(target_world_hint)} 个 —— "
          f"第二遍收集常驻兜底 …")
    persistent_by_cell: dict[int, list] = {}
    persistent_by_world: dict[int, list] = {}

    def cb2(sig, formid, flags, chain, cell, world, payload):
        if sig not in (b"REFR", b"ACHR"):
            return
        if not (chain and chain[-1][0] == 8):
            return
        row = {
            "local": formid & 0xFFFFFF, "base": record_base_form(payload) & 0xFFFFFF,
            "edid": record_edid(payload) or "", "pos": refr_position(payload),
        }
        if cell in target_cell_hint:
            persistent_by_cell.setdefault(cell, []).append(row)
        elif world in target_world_hint:
            persistent_by_world.setdefault(world, []).append(row)

    walk(buf, cb2)

    # ---- 组装 ----
    out: list[dict] = []
    for ent in LANDMARKS:
        qe = quests_esm.get(ent["questEdid"])
        if qe is None:
            problems.append(f"{ent['questEdid']}：ESM 里找不到这条任务")
            continue
        if qe["qtyp"] != 0x000475F8:
            problems.append(f"{ent['questEdid']}：QTYP 不是 Activities（{qe['qtyp']}）")
            continue
        name_en = (str_en.get(qe["full"], "") if qe["full"] else "").strip()
        name_zh = (str_zh.get(qe["full"], "") if qe["full"] else "").strip()
        if not name_en or not name_zh:
            problems.append(f"{ent['questEdid']}：官方名取不到（full={qe['full']}）")
            continue

        be = books_esm.get(ent["bookEdid"])
        if be is None:
            problems.append(f"{ent['bookEdid']}：ESM 里找不到这本书")
            continue
        book_name_en = (str_en.get(be["full"], "") if be["full"] else "").strip()
        book_name_zh = (str_zh.get(be["full"], "") if be["full"] else "").strip()
        if not book_name_en or not book_name_zh:
            problems.append(f"{ent['bookEdid']}：官方书名取不到（full={be['full']}）")
            continue

        # ② VMAD 核验：拾取书 ⇒ SetStage(100) 到对应任务
        hit_prop = None
        for sc in be["vmad"]:
            if sc["name"].lower() != "defaultrefoncontainerchangedto":
                continue
            props = sc["props"]
            if int(props.get("QuestToSetOrCheck", -1)) == qe["formid"] and \
               int(props.get("StageToSet", -1)) == 100:
                hit_prop = sc
        if hit_prop is None:
            got = [(sc["name"], sc["props"]) for sc in be["vmad"]]
            problems.append(f"{ent['bookEdid']}：VMAD 里没有「QuestToSetOrCheck == "
                            f"0x{qe['formid']:06X} 且 StageToSet == 100」的脚本（实际：{got}）")
            continue

        # 引导候选
        cands: list[dict] = []
        where_zh = where_en = ""
        anchor = None    # 精确候选（书 / 书商）的 REFR 行 —— 用来挑兜底
        if ent["guide"]:
            if ent.get("cairoShop"):
                if len(shop_npc_refs) != 1:
                    problems.append(f"{ent['questEdid']}：书商引用（{SHOP_NPC_EDID}）应有且"
                                    f"仅有 1 条，实际 {len(shop_npc_refs)} 条")
                    continue
                anchor = shop_npc_refs[0]
                npc_full = npc_rows.get(anchor["base"], {}).get("full")
                npc_zh = (str_zh.get(npc_full, "") if npc_full else "").strip()
                npc_en = (str_en.get(npc_full, "") if npc_full else "").strip()
                lctn = cell_lctn.get(anchor["cell"])
                where_zh = (str_zh.get(lctn_full.get(lctn, -1), "") if lctn else "").strip()
                where_en = (str_en.get(lctn_full.get(lctn, -1), "") if lctn else "").strip()
                if not where_zh or not where_en:
                    problems.append(f"{ent['questEdid']}：书商所在 cell 0x{anchor['cell']:08X} "
                                    f"没有 LCTN 名")
                    continue
                cands.append({
                    "refr": anchor["local"], "refrMaster": "Starfield.esm", "refrSmall": False,
                    "persistent": anchor["persistent"], "kind": "actor",
                    "nameZh": npc_zh or npc_en, "nameEn": npc_en or npc_zh,
                    "whereZh": where_zh, "whereEn": where_en, "src": "shop-npc",
                })
            else:
                refs = book_refs.get(be["local"], [])
                if len(refs) != 1:
                    problems.append(f"{ent['bookEdid']}：期望 1 条世界放置引用，实际 {len(refs)} 条")
                    continue
                anchor = refs[0]
                lctn = cell_lctn.get(anchor["cell"])
                where_zh = (str_zh.get(lctn_full.get(lctn, -1), "") if lctn else "").strip()
                where_en = (str_en.get(lctn_full.get(lctn, -1), "") if lctn else "").strip()
                if not where_zh or not where_en:
                    problems.append(f"{ent['questEdid']}：书所在 cell 0x{anchor['cell']:08X} 没有 "
                                    f"LCTN 名")
                    continue
                cands.append({
                    "refr": anchor["local"], "refrMaster": "Starfield.esm", "refrSmall": False,
                    "persistent": anchor["persistent"], "kind": "ref",
                    "nameZh": book_name_zh, "nameEn": book_name_en,
                    "whereZh": where_zh, "whereEn": where_en, "src": "book",
                })
            # ★ 兜底（两种分支共用）：同 cell 常驻引用（离精确目标最近的最多 3 条）。
            #   外景 cell 里官方不放 per-cell 常驻引用（第 80 轮实测 0 条）⇒ 退到
            #   **world 级常驻引用**（WRLD > WorldChildren > CellChildren > CellPersistent）。
            if anchor and anchor.get("pos"):
                pool = persistent_by_cell.get(anchor["cell"], [])
                pool_kind = "cell"
                if not pool and anchor.get("world"):
                    pool = persistent_by_world.get(anchor["world"], [])
                    pool_kind = "world"
                scored = []
                for c in pool:
                    if not c["pos"]:
                        continue
                    if c["local"] == anchor["local"]:
                        continue
                    d = dist(anchor["pos"], c["pos"])
                    if d > FALLBACK_MAX_DIST:
                        continue
                    scored.append((d, c))
                scored.sort(key=lambda t: t[0])
                for d, c in scored[:MAX_FALLBACKS]:
                    cname = c["edid"] or f"0x{c['base']:06X}"
                    cands.append({
                        "refr": c["local"], "refrMaster": "Starfield.esm", "refrSmall": False,
                        "persistent": True, "kind": "ref",
                        "nameZh": cname, "nameEn": cname,
                        "whereZh": where_zh, "whereEn": where_en,
                        "src": f"fallback-{pool_kind}({d:.1f}m)",
                    })
                if not scored:
                    problems.append(f"{ent['questEdid']}：没有兜底候选（{pool_kind} 池里 "
                                    f"{len(pool)} 条常驻引用，{FALLBACK_MAX_DIST:.0f} m 内一个都没有）")
                    continue
        else:
            n_refs = len(book_refs.get(be["local"], []))
            if n_refs == 0:
                problems.append(f"{ent['bookEdid']}：guide=false 但一条世界引用都没有（证据不足）")
                continue

        # ⑥ 说明文本
        for lang, note in (("zh", ent["noteZh"]), ("en", ent["noteEn"])):
            if not note.strip():
                problems.append(f"{ent['questEdid']}：{lang} 说明为空")
            if any(c in note for c in "\t\r\n"):
                problems.append(f"{ent['questEdid']}：{lang} 说明里有 Tab / 换行")
            if len(note) > NOTE_MAX:
                problems.append(f"{ent['questEdid']}：{lang} 说明超长（{len(note)} > {NOTE_MAX}）")

        if not cands and ent["guide"]:
            problems.append(f"{ent['questEdid']}：guide=true 但一个候选都没有")
            continue

        evidence = (f"书 {ent['bookEdid']} 的 VMAD：defaultrefoncontainerchangedto "
                    f"QuestToSetOrCheck=0x{qe['formid']:06X} StageToSet=100"
                    f"；世界引用 {len(book_refs.get(be['local'], []))} 条"
                    f"；候选 {len(cands)} 个"
                    f"（首选 {cands[0]['src'] if cands else '无'}）")
        out.append({
            "key": ent["key"],
            "guide": bool(ent["guide"]),
            "quest": {
                "edid": ent["questEdid"], "formid": qe["formid"], "local": qe["local"],
                "master": "Starfield.esm", "nameZh": name_zh, "nameEn": name_en,
            },
            "book": {
                "edid": ent["bookEdid"], "local": be["local"],
                "nameZh": book_name_zh, "nameEn": book_name_en,
            },
            "noteZh": ent["noteZh"], "noteEn": ent["noteEn"],
            "whereZh": where_zh, "whereEn": where_en,
            "cands": cands,
            "evidence": evidence,
        })

    if problems:
        print("核验失败（不写产物）：")
        for p in problems:
            print("  !! " + p)
        return 1

    Path(a.out).write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"wrote {a.out}")
    print(f"地球地标任务：{len(out)} 条（可引导 {sum(1 for g in out if g['guide'])} 条；"
          f"只给说明 {sum(1 for g in out if not g['guide'])} 条）")
    for g in out:
        q = g["quest"]
        n_fb = len([c for c in g["cands"] if c["src"].startswith("fallback")])
        tag = f"候选 {len(g['cands'])}（含兜底 {n_fb}）" if g["guide"] else "只给说明"
        print(f"  {g['key']:<11} {q['nameZh']} / {q['nameEn']}"
              f"（书：{g['book']['nameZh']}）0x{q['local']:06X} [{tag}]")
        print(f"      {g['evidence']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
