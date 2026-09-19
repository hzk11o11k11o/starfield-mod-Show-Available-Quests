#!/usr/bin/env python3
"""gen_outlaws_names.py - compose Dark Universe: Outlaws NPC and book names from
the token tables, and report what could not be composed.

NPC_/FULL  "<given|gang> [<role>|<surname>]"
           "Erin Cho"          -> 艾琳·赵        (surname  -> separator)
           "Ghost Crew Mixer"  -> 幽灵船员调音师  (role     -> concatenated)
BOOK/FULL  "<person|phrase> <doctype>"
           "Jonah Patel Diary" -> 乔纳·帕特尔日记

Usage:
    python tools/re/gen_outlaws_names.py --mod tr/out/du_outlaws_01.tsv \\
        --pre tr/lang/tokens_out_pre.tsv --last tr/lang/tokens_out_last.tsv \\
        --roles tr/lang/tokens_out_roles.tsv --doctype tr/lang/tokens_out_doctype.tsv \\
        -o tr/lang/batches/b30_outlaws_names.tsv --miss tr/lang/todo/outlaws/miss.txt
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from tr_pipeline import load_dict, load_rows  # noqa: E402


def spaces(text):
    return [i for i, ch in enumerate(text) if ch == " "]


def make_resolver(pre, surname, role):
    def resolve(text):
        if text in pre:
            return pre[text]
        for i in reversed(spaces(text)):
            p, s = text[:i], text[i + 1:]
            zp = pre.get(p)
            if zp is None:
                continue
            if s in role:
                return zp + role[s]
            if s in surname:
                return zp + "·" + surname[s]
        return None

    return resolve


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mod", required=True)
    ap.add_argument("--pre", required=True)
    ap.add_argument("--last", required=True)
    ap.add_argument("--roles", required=True)
    ap.add_argument("--doctype", required=True)
    ap.add_argument("--qual", required=True)
    ap.add_argument("-o", "--out", required=True)
    ap.add_argument("--miss", default=None)
    a = ap.parse_args()

    pre = load_dict(Path(a.pre))
    lastall = load_dict(Path(a.last))
    role = load_dict(Path(a.roles))
    doctype = load_dict(Path(a.doctype))
    qual = load_dict(Path(a.qual))
    surname = {k: v for k, v in lastall.items() if k not in role}

    resolve = make_resolver(pre, surname, role)

    out = {}
    miss = []
    for r in load_rows(a.mod):
        if r[2] != "FULL":
            continue
        rec, text = r[0], r[5]
        if rec == "NPC_":
            zh = resolve(text)
            if zh:
                out[text] = zh
            else:
                miss.append(("NPC_", text))
        elif rec == "BOOK":
            i = text.rfind(" ")
            if i < 0:
                miss.append(("BOOK", text))
                continue
            rest, dt = text[:i], text[i + 1:]
            zd = doctype.get(dt)
            if zd is None:
                miss.append(("BOOK", text))
                continue
            zp = resolve(rest) or out.get(rest)
            if zp is None:
                # "<person> <qualifier> <doctype>", e.g. "Lena Park Ship Notes"
                parts = rest.split(" ")
                for k in (1, 2):
                    if len(parts) < k + 1:
                        break
                    head = " ".join(parts[:-k])
                    q = " ".join(parts[-k:])
                    zq = qual.get(q)
                    if not zq:
                        continue
                    zh2 = resolve(head) or out.get(head)
                    if zh2:
                        zp = zh2 + zq
                        break
            if zp is None:
                miss.append(("BOOK", text))
                continue
            out[text] = zp + zd

    Path(a.out).write_text(
        "#en\tzh\n# Dark Universe: Outlaws —— 由词元表自动组合的 NPC / 书籍名称\n"
        + "\n".join(f"{k}\t{v}" for k, v in sorted(out.items())) + "\n",
        encoding="utf-8")
    print(f"names: composed={len(out)} unresolved={len(miss)} -> {a.out}")
    if a.miss:
        Path(a.miss).write_text(
            "#rec\ttext\n" + "\n".join(f"{r}\t{t}" for r, t in miss) + "\n",
            encoding="utf-8")
        print(f"  unresolved list -> {a.miss}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
