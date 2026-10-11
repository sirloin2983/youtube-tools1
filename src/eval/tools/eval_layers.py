#!/usr/bin/env python3
"""文書を「機械の層 + 人の層」から組み立て直して、今の文書と同じになるかを本物の作業データで確かめる道具(RS8 O2-1。決定 3-37 の (r8u))。

    python src/eval/tools/eval_layers.py [--data-dir 作業データの親フォルダ] [--ids id1,id2] [--show N] [--json]

- 作業データは**読むだけ**(文字起こしの transcripts/<id>.json。案件の 作業用 に置いた文書も索引から)。何も書かない(--json も標準出力に出すだけ)
- 文書ごとに、機械の出力 original から機械の層を作り(human/proof/layers.mach_from_doc)、人の層 = diff(機械, 文書)、
  組み立て直した文書 = compose(機械, 人の層, 文書の機械の側の欄)を今の文書と比べる(行の id・時刻・文字・話者・印・そのほかの欄・並び・話者の表・文書の欄)。
  あわせて、機械を同じ中身のまま作り直した(行 id を付け替えた)つもりで組み立てても行の中身(id を除く)が同じかと、そのときの印 MACH_CHANGED の行の数も数える
- 出すもの: 合った本数・合わなかった本数と理由ごとの本数・人の層の大きさ(機械のままの行・属性の行・文字の行・消す印)・合わなかった文書の例
- original の無い文書も数える(機械の層が空 = 全部の行が人の文字の行になる)
"""
import argparse
import copy
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.dirname(os.path.dirname(HERE))   # tools -> eval -> src
if not __package__:   # スクリプトとして起動したとき(py -3.10 src/eval/tools/eval_layers.py)だけ。src を先頭に・この道具のフォルダは外す(見本 eval_fill.py)
    sys.path[:] = [SRC] + [p for p in sys.path if os.path.normcase(os.path.abspath(p or os.curdir)) not in (os.path.normcase(HERE), os.path.normcase(SRC))]
from eval.tools import _evalcommon as C  # noqa: E402  共通の部品(作業データの場所・読み方。src を sys.path に足す)
from human.proof import layers  # noqa: E402
from ytt import docloc  # noqa: E402

SCHEMA = "youtube-tools-layers-eval/v1"
SIZE_KEYS = ("rows", "kept", "attr", "text", "dead")


def _content(rows):
    """行の中身(id を除いた欄)の数え上げ"""
    out = {}
    for g in rows:
        if isinstance(g, dict):
            k = json.dumps({x: v for x, v in g.items() if x != "id"}, ensure_ascii=False, sort_keys=True)
            out[k] = out.get(k, 0) + 1
    return out


def rebuilt_same(doc, mach, hum):
    """機械を同じ中身のまま作り直した(行 id を全部付け替え・rev を上げた)つもりで組み立てても、行の中身(id を除く)が今の文書と同じか。
    -> (同じか, 印 MACH_CHANGED の行の数)。機械が作り直されたときの時刻の重なりの決まり(compose の機械が変わった道)を本物の文書で確かめる"""
    m2 = copy.deepcopy(mach)
    m2["rev"] = (m2.get("rev") or 0) + 1
    for i, r in enumerate(m2["rows"]):
        r["id"] = "r%d" % (i + 1)
    rows, st = layers.compose_rows(m2, hum)
    return _content(rows) == _content(doc.get("segments") or []), st["machChanged"]


def check_doc(doc):
    """1 本の文書 -> {ok, reasons[(理由, 例)…], size{rows, kept, attr, text, dead}, rebuilt(作り直しても同じ), machChanged}"""
    mach = layers.mach_from_doc(doc)
    hum, reasons = layers.roundtrip(mach, doc)
    same, changed = rebuilt_same(doc, mach, hum)
    rows = [g for g in doc.get("segments") or [] if isinstance(g, dict)]
    n_text = sum(1 for h in hum["rows"] if "text" in h)
    n_attr = len(hum["rows"]) - n_text
    size = {"rows": len(rows), "kept": max(0, len(rows) - len(hum["rows"])), "attr": n_attr, "text": n_text, "dead": len(hum["dead"])}
    return {"ok": not reasons, "reasons": reasons, "size": size, "rebuilt": same, "machChanged": changed}


def evaluate(data_dir=None, ids=None, show=10):
    """作業データ全体 -> 結果(JSON にそのまま出せる形)"""
    root = C.locate("transcribe", data_dir)
    want = set(ids) if ids else None
    res = {"schema": SCHEMA, "root": root, "docs": 0, "ok": 0, "ng": 0, "unreadable": 0, "noOriginal": 0, "rebuiltNg": [], "machChanged": 0,
           "reasons": {}, "size": {k: 0 for k in SIZE_KEYS}, "examples": []}
    for tid in docloc.iter_tids(root):
        if want is not None and tid not in want:
            continue
        doc = C.read_json(docloc.doc_file(tid, ".json", root), None, C.DOC_BYTES)
        if not isinstance(doc, dict) or not isinstance(doc.get("segments"), list):
            res["unreadable"] += 1
            continue
        res["docs"] += 1
        if not doc.get("original"):
            res["noOriginal"] += 1
        r = check_doc(doc)
        for k in SIZE_KEYS:
            res["size"][k] += r["size"][k]
        res["machChanged"] += r["machChanged"]
        if not r["rebuilt"]:
            res["rebuiltNg"].append(tid)
        if r["ok"]:
            res["ok"] += 1
            continue
        res["ng"] += 1
        for code, _ex in r["reasons"]:
            res["reasons"][code] = res["reasons"].get(code, 0) + 1
        if len(res["examples"]) < show:
            res["examples"].append({"id": tid, "title": str(doc.get("title") or "")[:40], "reasons": [[c, str(x)[:80]] for c, x in r["reasons"]]})
    return res


def print_report(res):
    print("機械の層 + 人の層の往復(%s)" % res["root"])
    print("文書 %d 本: 合った %d 本・合わない %d 本(読めない %d 本・original の無い文書 %d 本)" % (
        res["docs"], res["ok"], res["ng"], res["unreadable"], res["noOriginal"]))
    for code, n in sorted(res["reasons"].items(), key=lambda x: -x[1]):
        print("  %-10s %4d 本" % (layers.REASONS.get(code, code), n))
    s = res["size"]
    print("行 %d: 機械のまま %d・属性の行 %d・人の文字の行 %d・消す印 %d" % (s["rows"], s["kept"], s["attr"], s["text"], s["dead"]))
    print("機械を同じ中身で作り直したつもり(行 id を付け替え): 行の中身が違う文書 %d 本・印 MACH_CHANGED の行 %d%s" % (
        len(res["rebuiltNg"]), res["machChanged"], ("(" + ",".join(res["rebuiltNg"][:10]) + ")") if res["rebuiltNg"] else ""))
    for x in res["examples"]:
        print("  %s %-24s %s" % (x["id"], x["title"][:24], "・".join("%s(%s)" % (layers.REASONS.get(c, c), e) for c, e in x["reasons"])))


def main(argv=None):
    p = argparse.ArgumentParser(description="文書を機械の層 + 人の層から組み立て直して今の文書と同じかを確かめる(作業データは読むだけ)")
    p.add_argument("--data-dir", help="作業データの親フォルダ(既定 %%LOCALAPPDATA%%/youtube-tools。テスト用)")
    p.add_argument("--ids", help="この文書の id だけ(「,」区切り)")
    p.add_argument("--show", type=int, default=10, help="合わなかった文書の例をいくつ出すか(既定 10)")
    p.add_argument("--json", action="store_true", help="結果を JSON で標準出力に出す(ファイルには書かない)")
    args = p.parse_args(argv)
    C.utf8_stdout()
    res = evaluate(args.data_dir, C.split_ids(args.ids), max(0, args.show))
    if args.json:
        print(json.dumps(res, ensure_ascii=False, indent=1))
    else:
        print_report(res)
    return 0


if __name__ == "__main__":
    sys.exit(main())
