#!/usr/bin/env python3
"""gen_poi_names.py - map Dark Universe "rg_poi_<name><code>" quest names onto
the already translated station names.

The mod ships 152 QUST FULL values such as "rg_poi_penpt627" which are the raw
internal names of the procedural stations ("Pen PT-627").  Leaving them as ids
would put an English id in the (otherwise Chinese) quest log, so derive them
from the translated GBFM names instead:

    GBFM FULL  "Pen PT-627"  ->  围栏站 PT-627
    QUST FULL  "rg_poi_penpt627"  ->  围栏站 PT-627

Usage:
    python tools/re/gen_poi_names.py --mod tr/out/du_retrograde.tsv \\
        --prefix tr/lang/tokens_prefix_all.tsv \\
        --suffix tr/lang/tokens_du_suffix.tsv -o tr/lang/batches/b21_poi.tsv
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from tr_pipeline import compose, load_dict, load_rows  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mod", required=True)
    ap.add_argument("--prefix", required=True)
    ap.add_argument("--suffix", required=True)
    ap.add_argument("-o", "--out", required=True)
    a = ap.parse_args()

    prefix_dict = load_dict(Path(a.prefix))
    suffix_dict = load_dict(Path(a.suffix))

    station_by_key = {}
    for r in load_rows(a.mod):
        if r[2] != "FULL" or r[0] != "GBFM":
            continue
        name = r[5]
        zh = compose(prefix_dict, suffix_dict, name)
        if zh is None:
            continue
        key = "rg_poi_" + name.lower().replace(" ", "").replace("-", "")
        station_by_key[key] = zh

    lines = ["#en\tzh", "# Dark Universe: Retrograde —— rg_poi_* 任务名还原为站点名"]
    hits = 0
    for r in load_rows(a.mod):
        if r[2] != "FULL" or r[0] != "QUST":
            continue
        name = r[5]
        if not name.startswith("rg_poi_"):
            continue
        zh = station_by_key.get(name)
        if zh is None:
            continue
        lines.append(name + "\t" + zh)
        hits += 1

    Path(a.out).write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"poi names: stations={len(station_by_key)} mapped={hits} -> {a.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
