# -*- coding: utf-8 -*-
"""Papyrus .pex 头部 / 字符串表解析（零依赖）。

用法:
    python pexinfo.py <file.pex> [--strings N] [--dump-all]

输出:
    - magic / 版本 / gameId / 编译时间 / 源文件名 / 编译者
    - 字符串表（全部标识符：脚本名 / 属性 / 函数 / 类型 / 字符串字面量）

说明:
    字符串表位于 debugInfo 之前，因此本工具只做「头部 + 字符串表」，
    不依赖对后续指令流的精确解析 —— 结果 100% 可靠（不存在错位风险）。
"""
import struct
import sys
import os


def read_string(buf, off):
    n = struct.unpack_from('<H', buf, off)[0]
    off += 2
    if n == 0:
        return '', off
    raw = buf[off:off + n]
    off += n
    if raw.endswith(b'\x00'):
        raw = raw[:-1]
    return raw.decode('utf-8', errors='replace'), off


def parse(path):
    with open(path, 'rb') as f:
        buf = f.read()
    info = {'size': len(buf), 'path': path}
    magic = struct.unpack_from('<I', buf, 0)[0]
    info['magic'] = magic
    info['major'] = buf[4]
    info['minor'] = buf[5]
    info['gameId'] = struct.unpack_from('<H', buf, 6)[0]
    info['time'] = struct.unpack_from('<q', buf, 8)[0]
    off = 16
    info['source'], off = read_string(buf, off)
    info['username'], off = read_string(buf, off)
    info['machine'], off = read_string(buf, off)
    count = struct.unpack_from('<H', buf, off)[0]
    off += 2
    strings = []
    for _ in range(count):
        s, off = read_string(buf, off)
        strings.append(s)
    info['strings'] = strings
    info['strings_end'] = off
    return info


def ts(t):
    import datetime
    try:
        return datetime.datetime.fromtimestamp(t).strftime('%Y-%m-%d %H:%M:%S')
    except Exception:
        return str(t)


def main():
    args = sys.argv[1:]
    if not args:
        print(__doc__)
        return
    path = args[0]
    show = 40
    dump_all = '--dump-all' in args
    if '--strings' in args:
        show = int(args[args.index('--strings') + 1])
    info = parse(path)
    print(f"file    : {os.path.basename(path)}  ({info['size']} B)")
    print(f"magic   : 0x{info['magic']:08X}  version={info['major']}.{info['minor']}  gameId={info['gameId']}")
    print(f"time    : {info['time']}  ({ts(info['time'])})")
    print(f"source  : {info['source']}")
    print(f"author  : {info['username']} @ {info['machine']}")
    ss = info['strings']
    print(f"strings : {len(ss)}")
    n = len(ss) if dump_all else min(show, len(ss))
    for s in ss[:n]:
        print(f"   {s}")
    if not dump_all and len(ss) > n:
        print(f"   ... ({len(ss) - n} more, use --dump-all)")


if __name__ == '__main__':
    main()
