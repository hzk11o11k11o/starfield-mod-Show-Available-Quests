#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""gen_display_cases.py - 从 Starfield.esm 生成「展示柜容器」白名单头文件。

为什么需要它（v4.9）：
    v4.8 的 `cont probe:` 日志实锤 —— 武器箱（base=00246224
    `Loot_Display_WeaponsCase_Rifles_Common`）在**关闭**状态下
    `inventoryList.size == 0`，只有打开搜刮界面时才出现两条
    `fl=0x20`（`BGSInventoryItem::Flag::kTemporary`）的**临时条目**，
    关掉界面又归 0。⇒ 这类容器「关着不亮」不是判空逻辑的 bug，
    而是引擎根本不把内容放在库存里（只能靠静态数据识别）。

    离线扫描全量 Starfield.esm：707 个 CONT 里恰好 **118 个**带
    `BGSDisplayCase` 组件（记录里的 `BFCB "BGSDisplayCase"` + `DCSD`/`DCED`），
    数量可控 ⇒ 生成 FormID 白名单，DLL 对白名单内的 base 跳过「搜空判空」。

    运行时另有兜底：任何容器只要在打开期间读到过 kTemporary 条目，
    DLL 会把它的 base 记进内存集合（覆盖第三方 mod 新增的记录）。

用法:
    python tools/re/gen_display_cases.py <Starfield.esm> <输出的 .h 路径>
    # 例：
    python tools/re/gen_display_cases.py ^
        "D:\\SteamLibrary\\steamapps\\common\\Starfield\\Data\\Starfield.esm" ^
        plugin/src/SasDisplayCases.h

产物入库（plugin/src/SasDisplayCases.h），构建时**不会**自动重跑 ——
只有游戏版本更新 / 发现遗漏时才手动重生一次。
"""
from __future__ import annotations

import mmap
import struct
import sys
import zlib


def iter_subrecords(payload: bytes):
    """按子记录序列切分（sig + u16 size + data）。遇到错位就停。"""
    off = 0
    n = len(payload)
    while off + 6 <= n:
        sig = payload[off:off + 4]
        size = struct.unpack_from('<H', payload, off + 4)[0]
        if off + 6 + size > n:
            break
        yield sig, payload[off + 6:off + 6 + size]
        off += 6 + size


def scan(esm_path: str):
    """返回 [(formid, edid)]，按 FormID 升序。"""
    f = open(esm_path, 'rb')
    mm = mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ)
    head_size = struct.unpack_from('<I', mm, 4)[0]
    hits: list[tuple[int, str]] = []
    cont_total = 0

    def walk(p0: int, p1: int) -> None:
        nonlocal cont_total
        p = p0
        while p < p1:
            if mm[p:p + 4] == b'GRUP':
                g = struct.unpack_from('<I', mm, p + 4)[0]
                if g < 24 or p + g > p1:
                    return
                walk(p + 24, p + g)
                p += g
                continue
            sig = bytes(mm[p:p + 4])
            ds = struct.unpack_from('<I', mm, p + 4)[0]
            flags = struct.unpack_from('<I', mm, p + 8)[0]
            fid = struct.unpack_from('<I', mm, p + 12)[0]
            if p + 24 + ds > p1:
                return
            if sig == b'CONT':
                cont_total += 1
                payload = bytes(mm[p + 24:p + 24 + ds])
                if flags & 0x00040000 and payload:  # 压缩记录
                    try:
                        payload = zlib.decompress(payload[4:])
                    except Exception:
                        payload = b''
                edid = ''
                has_dcsd = False
                for s, v in iter_subrecords(payload):
                    if s == b'EDID':
                        edid = v.split(b'\x00')[0].decode('latin1', 'replace')
                        break  # EDID 是第一条；后面的 DCSD 继续扫
                for s, v in iter_subrecords(payload):
                    if s == b'DCSD':
                        has_dcsd = True
                        break
                if has_dcsd:
                    hits.append((fid, edid))
            p += 24 + ds
            if ds == 0:
                return

    walk(24 + head_size, len(mm))
    hits.sort()
    return hits, cont_total


HEADER = '''#pragma once
// ============================================================================
//  自动生成，请勿手改 —— 生成器：tools/re/gen_display_cases.py
//
//  「展示柜（Display Case）」容器白名单：带 BGSDisplayCase 组件（DCSD）的 CONT。
//  这类容器的内容**只在搜刮界面打开期间**以 kTemporary（fl=0x20）条目投影进
//  inventoryList，关闭时读到 size=0 —— 判空规则对它们不适用（v4.9 起跳过）。
//  完整背景见 AlwaysScan.cpp 常量区「v4.9 展示柜」长注释。
//
//  数据来源：Starfield.esm（游戏 1.16.244.0），%d 个 CONT 中命中 %d 个。
//  重新生成（游戏大版本更新后可跑一次，产物需入库）：
//      python tools/re/gen_display_cases.py <Starfield.esm> plugin/src/SasDisplayCases.h
// ============================================================================

#include <cstddef>
#include <cstdint>

namespace SAS::DisplayCases
{
	// 升序排列（运行期用 std::binary_search 查询）。
	inline constexpr std::uint32_t kBaseIDs[] = {
'''


def main(argv):
    if len(argv) < 3:
        print(__doc__)
        return 2
    esm, out_path = argv[1], argv[2]
    hits, cont_total = scan(esm)

    lines = [HEADER % (cont_total, len(hits))]
    for fid, edid in hits:
        lines.append('\t\t0x%08Xu,%s// %s\n' % (fid, ' ' * max(1, 16 - len('0x%08Xu,' % fid)), edid))
    lines.append('\t};\n')
    lines.append('\tinline constexpr std::size_t kBaseIDCount = sizeof(kBaseIDs) / sizeof(kBaseIDs[0]);\n')
    lines.append('}\n')

    with open(out_path, 'w', encoding='utf-8', newline='\n') as fo:
        fo.write(''.join(lines))
    print('CONT total=%d  display-case hits=%d  ->  %s' % (cont_total, len(hits), out_path))
    return 0


if __name__ == '__main__':
    raise SystemExit(main(sys.argv))
