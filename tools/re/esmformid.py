#!/usr/bin/env python3
"""在 .esm/.esp 里按 EDID 字符串反查记录头（签名 + FormID + 长度）。

原理：Bethesda 插件里 EDID 是明文 ASCII，而且它几乎总是记录的第一个子记录。
从字符串往前找到 EDID 子记录头（"EDID" + u16 size），再往前 24 字节就是记录头：

    char   type[4];      // 记录签名，例如 MGEF / SPEL
    uint32 dataSize;
    uint32 flags;
    uint32 formID;       // ★ 这就是我们要的
    uint32 versionControl;
    uint16 internalVersion;
    uint16 unknown;

用法：
    python tools/re/esmformid.py ScannerGuideEffect
    python tools/re/esmformid.py Guide --limit 20
"""
from __future__ import annotations

import argparse
import struct
import sys
from pathlib import Path

DEFAULT_ESM = Path(r"D:\SteamLibrary\steamapps\common\Starfield\Data\Starfield.esm")
HDR = 24  # 记录头长度


def chunks(path: Path, size: int = 8 << 20):
    with open(path, "rb") as f:
        while True:
            b = f.read(size)
            if not b:
                return
            yield b


def analyze(blob: bytes, pos: int, base_off: int):
    """pos = 字符串在 blob 里的位置；往前找 EDID 子记录头。"""
    for back in range(6, 64):  # EDID + u16 size 就在字符串前面
        p = pos - back
        if p < 0:
            break
        if blob[p:p + 4] != b"EDID":
            continue
        size = struct.unpack_from("<H", blob, p + 4)[0]
        if p + 6 + size < pos or size < 4 or size > 256:
            continue
        rec = p - HDR
        if rec < 0:
            return None
        sig = blob[rec:rec + 4]
        data_size, flags, form_id = struct.unpack_from("<III", blob, rec + 4)
        return sig.decode("latin1"), form_id, data_size, flags
    return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("needle")
    ap.add_argument("--esm", default=str(DEFAULT_ESM))
    ap.add_argument("--limit", type=int, default=30)
    a = ap.parse_args()

    needle = a.needle.encode()
    hits = 0
    seen: set[str] = set()
    offset = 0
    for blob in chunks(Path(a.esm)):
        k = blob.find(needle)
        while k != -1:
            # 字符串必须落在可打印区（不是别的数据的巧合）
            ok = True
            i = k
            while i < len(blob) and 0x20 <= blob[i] < 0x7F:
                i += 1
            if i - k < len(needle):
                ok = False
            info = analyze(blob, k, offset) if ok else None
            name = blob[k:i].decode("latin1")
            key = f"{info}|{name}" if info else name
            if ok and key not in seen:
                seen.add(key)
                if info:
                    sig, form_id, data_size, flags = info
                    print(f"0x{offset + k:08X}  sig={sig}  formID=0x{form_id:08X}  "
                          f"(local 0x{form_id & 0xFFFFFF:06X})  size={data_size}  flags=0x{flags:X}  \"{name}\"")
                else:
                    print(f"0x{offset + k:08X}  (record header not found)  \"{name}\"")
                hits += 1
            k = blob.find(needle, k + 1)
        if hits >= a.limit:
            break
        offset += len(blob)

    print(f"[done] {hits} hit(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
