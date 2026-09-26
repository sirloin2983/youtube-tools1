#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""文字起こしの「長い区間に文字が少ない行」(抜けの可能性)を数える(docs/edit-tool-design.md の 12 ③-1)。作業データは読むだけ。

規則は文字起こしの serve.py の sparse_row(4 秒より長くて、記号・空白を除いた文字数が 1 秒あたり 1.5 文字未満)。
機械の出力(文書の original)と、今の行(segments。人が直したあと)の両方で数える。対象は評価用(evalSet)と、最近の文字起こし。

    python tools/count_sparse_rows.py                 # 評価用すべてと、最近の 20 本
    python tools/count_sparse_rows.py --recent 40 --examples 5
    python tools/count_sparse_rows.py --dir <transcripts のフォルダ>

出力には文字起こしの文が入る(このパソコンの画面に出すだけ。ファイルには書かない)。
"""
import argparse
import glob
import json
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for d in (os.path.join(REPO, "transcribe-tool"), REPO):
    if d not in sys.path:
        sys.path.insert(0, d)

import serve as TX  # noqa: E402  文字起こしの serve.py(読み込むだけでは作業データに書かない。規則 sparse_row を使う)
from ytt_core import txindex  # noqa: E402


def load_docs(folder):
    out = []
    for p in sorted(glob.glob(os.path.join(folder, "*.json"))):
        n = os.path.basename(p)
        if n.count(".") != 1:   # <id>.edit.json などは飛ばす
            continue
        try:
            with open(p, encoding="utf-8") as f:
                d = json.load(f)
        except (OSError, ValueError):
            continue
        if isinstance(d, dict) and isinstance(d.get("segments"), list):
            d.setdefault("id", n[:-5])
            out.append(d)
    return out


def rows(doc, key):
    out = []
    for r in doc.get(key) or []:
        if not isinstance(r, dict):
            continue
        try:
            a, b = float(r.get("start")), float(r.get("end"))
        except (TypeError, ValueError):
            continue
        out.append((a, b, str(r.get("text") or "")))
    return out


def doc_len(doc, segs):
    try:
        if doc.get("whole", True) and float(doc.get("duration") or 0) > 0:
            return float(doc["duration"])
        if float(doc.get("end") or 0) > float(doc.get("start") or 0):
            return float(doc["end"]) - float(doc["start"])
    except (TypeError, ValueError):
        pass
    return max((b for _, b, _ in segs), default=0.0) - min((a for a, _, _ in segs), default=0.0)


def count(doc):
    orig = rows(doc, "original") or rows(doc, "segments")
    cur = rows(doc, "segments")
    so = [(a, b, t) for a, b, t in orig if TX.sparse_row(a, b, t)]
    sc = [(a, b, t) for a, b, t in cur if TX.sparse_row(a, b, t)]
    return {"id": doc["id"], "eval": bool(doc.get("evalSet")), "model": str(doc.get("model") or ""), "updatedAt": int(doc.get("updatedAt") or 0),
            "len": doc_len(doc, orig), "rows": len(orig), "orig": so, "cur": sc, "hasOriginal": bool(doc.get("original")),
            "vad": str((doc.get("options") or {}).get("vadMode") or doc.get("vadMode") or "")}


def fmt_t(sec):
    m, s = divmod(max(0.0, sec), 60)
    return "%d:%04.1f" % (m, s)


def report(items, title, examples):
    n_rows = sum(i["rows"] for i in items)
    n_o = sum(len(i["orig"]) for i in items)
    n_c = sum(len(i["cur"]) for i in items)
    sec_o = sum(b - a for i in items for a, b, _ in i["orig"])
    sec_c = sum(b - a for i in items for a, b, _ in i["cur"])
    total = sum(i["len"] for i in items) or 1.0
    print("\n== %s: %d 本・機械の出力 %d 行・長さ %.0f 秒" % (title, len(items), n_rows, total))
    print("   機械の出力: 該当 %d 行(%.1f%%)・合計 %.1f 秒(長さの %.1f%%)・該当のある文書 %d 本" % (
        n_o, 100 * n_o / max(1, n_rows), sec_o, 100 * sec_o / total, sum(1 for i in items if i["orig"])))
    print("   今の行(直したあと): 該当 %d 行・合計 %.1f 秒" % (n_c, sec_c))
    for i in items:
        if not i["orig"] and not i["cur"]:
            continue
        print("   %s %s %-16s 長さ %5.1f 秒・行 %3d・該当 %d 行 %.1f 秒(今の行 %d)" % (
            i["id"], "評価" if i["eval"] else "    ", i["model"][:16], i["len"], i["rows"], len(i["orig"]),
            sum(b - a for a, b, _ in i["orig"]), len(i["cur"])))
        for a, b, t in i["orig"][:examples]:
            print("       %s〜%s(%.1f 秒・%d 文字)「%s」" % (fmt_t(a), fmt_t(b), b - a, TX.text_chars(t), t[:40]))


def main(argv=None):
    ap = argparse.ArgumentParser(description="長い区間に文字が少ない行(抜けの可能性)を数える(読むだけ)")
    ap.add_argument("--dir", help="transcripts のフォルダ(既定は文字起こしの作業データ)")
    ap.add_argument("--recent", type=int, default=20, help="最近の文字起こしの本数(評価用を除く。既定 20)")
    ap.add_argument("--examples", type=int, default=3, help="文書ごとに出す例の数(既定 3)")
    a = ap.parse_args(argv)
    folder = a.dir or txindex.folder(REPO)
    docs = [count(d) for d in load_docs(folder)]
    print("フォルダ: %s(%d 本)" % (folder, len(docs)))
    print("規則: %.0f 秒より長くて、記号・空白を除いた文字数が 1 秒あたり %.1f 文字未満(serve.sparse_row)" % (TX.SPARSE_MIN_SEC, TX.SPARSE_MAX_CPS))
    ev = [d for d in docs if d["eval"]]
    recent = sorted((d for d in docs if not d["eval"]), key=lambda d: -d["updatedAt"])[:max(0, a.recent)]
    report(ev, "評価用(evalSet)", a.examples)
    report(recent, "最近の文字起こし(評価用を除く %d 本)" % len(recent), a.examples)
    return 0


if __name__ == "__main__":
    sys.exit(main())
