#!/usr/bin/env python3
"""スタジオの data.json の配信を「候補 + 採用」(flow/casebook)に分けて重ね直し、今の配信と同じになるかを本物の作業データで確かめる道具
(RS8 B3-3。決定 3-37 の (r8j)〜(r8q))。

    python src/eval/tools/eval_casebook.py [--data-dir 作業データの親フォルダ] [--out-dir 書き出し先] [--ids id1,id2] [--show N] [--json]

- 作業データは**読むだけ**(スタジオの data.json と、案件のフォルダの 作業用/.studio-id)。何も書かない(--json も標準出力に出すだけ)
- 配信ごとに案件を引き(casebook.case_of。書き出したマークの path の親・持ち主の印・書き出し先の下)、同じ案件の配信は 1 つの
  候補.json・採用.json に順に split で入れる(sources が 2 本になる案件も確かめる)。JSON に書いて読んだつもり(parse_*)で merge し、
  Store が読み込んだ形(human/review/store の _load_video)の配信と比べる(欄・マークの数・中身・並び)。
  あわせて人の保存の道(keep_candidates=True で候補を書き換えない)でも同じになり、消した印が増えないかを見る
- 出すもの: 配信の数・案件を引けた数・合った数・合わなかった配信と理由・候補 / 採用のマークの数・採用の側に残した手つかずの候補の数・
  並びを持った配信の数・相対にした path の数
"""
import argparse
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.dirname(os.path.dirname(HERE))   # tools -> eval -> src
if not __package__:   # スクリプトとして起動したとき(py -3.10 src/eval/tools/eval_casebook.py)だけ。src を先頭に・この道具のフォルダは外す(見本 eval_fill.py)
    sys.path[:] = [SRC] + [p for p in sys.path if os.path.normcase(os.path.abspath(p or os.curdir)) not in (os.path.normcase(HERE), os.path.normcase(SRC))]
from eval.tools import _evalcommon as C  # noqa: E402  共通の部品(作業データの場所・読み方。src を sys.path に足す)
from flow import casebook  # noqa: E402
from human.review import store as _store  # noqa: E402
from ytt import datadir, fsio, marks as _marks  # noqa: E402

SCHEMA = "youtube-tools-casebook-eval/v1"
DATA_BYTES = 256 * 2**20
REASONS = {"fields": "配信の欄が違う", "count": "マークの数が違う", "marks": "マークの中身が違う", "order": "マークの並びが違う",
           "missing": "重ねると配信が無い", "keep": "人の保存の道で違う", "keepRejected": "人の保存の道で消した印が増えた"}


def _through_json(docs):
    """ファイルに書いて読んだつもり(JSON の往復 + parse_*)"""
    c, a = docs
    return (casebook.parse_candidates(json.loads(json.dumps(c, ensure_ascii=False))),
            casebook.parse_adoptions(json.loads(json.dumps(a, ensure_ascii=False))))


def diff_reasons(want, got):
    """配信 2 つの違い -> [(理由の code, 例)]。同じなら []"""
    if got is None:
        return [("missing", "")]
    out = []
    keys = sorted((set(want) | set(got)) - {"marks"})
    bad = [k for k in keys if want.get(k) != got.get(k)]
    if bad:
        out.append(("fields", ",".join(bad)))
    wm, gm = want.get("marks") or [], got.get("marks") or []
    if len(wm) != len(gm):
        out.append(("count", "%d -> %d" % (len(wm), len(gm))))
    elif [m["id"] for m in wm] != [m["id"] for m in gm]:
        if sorted(m["id"] for m in wm) == sorted(m["id"] for m in gm):
            out.append(("order", ""))
        else:
            out.append(("marks", "id"))
    else:
        for a, b in zip(wm, gm):
            if a != b:
                ks = sorted(k for k in set(a) | set(b) if a.get(k) != b.get(k))
                out.append(("marks", "%s: %s" % (a["id"], ",".join(ks))))
                break
    return out


def _load_videos(path):
    """data.json -> {id: Store が読み込んだ形の配信}(壊れた配信は数えるだけ)。-> (videos, 読めなかった数)"""
    d = fsio.read_json_or(path, None, DATA_BYTES, allow_nan=True)   # スタジオは NaN も書ける(json.dumps の既定)
    if not isinstance(d, dict) or not isinstance(d.get("videos"), dict):
        return None, 0
    out, broken = {}, 0
    for vid, v in d["videos"].items():
        try:
            out[vid] = _store.Store._load_video(vid, v)
        except Exception:
            broken += 1
    return out, broken


def evaluate(data_dir=None, out_dir=None, ids=None, show=10):
    """作業データの data.json 全体 -> 結果(JSON にそのまま出せる形)"""
    sdir = C.locate("studio", data_dir)
    path = os.path.join(sdir, "data.json")
    out = out_dir or datadir.studio_out_dir(C.REPO, C.data_env(data_dir))
    res = {"schema": SCHEMA, "dataJson": path, "outDir": out, "videos": 0, "broken": 0, "cases": 0, "withCase": 0, "sharedCases": 0,
           "ok": 0, "ng": 0, "reasons": {}, "examples": [], "candidateMarks": 0, "adoptionMarks": 0, "pinned": 0, "ordered": 0,
           "relPaths": 0, "unreadable": False}
    videos, broken = _load_videos(path)
    if videos is None:
        res["unreadable"] = True
        return res
    res["broken"] = broken
    want = set(ids) if ids else None
    groups = {}   # 案件の根(None = 引けない配信は 1 本ずつ)-> [配信]
    for vid, v in videos.items():
        if want is not None and vid not in want:
            continue
        res["videos"] += 1
        root = casebook.case_of(v, out)
        groups.setdefault(root or ("", vid), []).append(v)
    for key, vs in groups.items():
        root = key if isinstance(key, str) else None
        if root:
            res["cases"] += 1
            res["withCase"] += len(vs)
            res["sharedCases"] += 1 if len(vs) > 1 else 0
        docs = (None, None)
        for v in vs:
            docs = casebook.split(v, root, prev=docs)
        cands, adopts = _through_json(docs)
        res["relPaths"] += sum(1 for m in adopts["marks"] if m.get("path") and not os.path.isabs(m["path"]))
        res["adoptionMarks"] += len(adopts["marks"])
        for v in vs:
            cs = cands["sources"].get(v["id"]) or {}
            res["candidateMarks"] += len(cs.get("auto") or [])
            res["pinned"] += sum(1 for m in adopts["marks"] if m["source"] == v["id"] and m.get("src") == "auto" and not _marks.touched(m))
            res["ordered"] += 1 if adopts["sources"].get(v["id"], {}).get("order") else 0
            reasons = diff_reasons(v, casebook.merge(cands, adopts, v["id"], root))
            kc, ka = _through_json(casebook.split(v, root, prev=(cands, adopts), keep_candidates=True))
            if diff_reasons(v, casebook.merge(kc, ka, v["id"], root)):
                reasons.append(("keep", ""))
            if len(ka["rejected"]) != len(adopts["rejected"]):
                reasons.append(("keepRejected", "%d -> %d" % (len(adopts["rejected"]), len(ka["rejected"]))))
            if not reasons:
                res["ok"] += 1
                continue
            res["ng"] += 1
            for code, _ex in reasons:
                res["reasons"][code] = res["reasons"].get(code, 0) + 1
            if len(res["examples"]) < show:
                res["examples"].append({"id": v["id"], "title": str(v.get("title") or "")[:40], "case": bool(root),
                                        "reasons": [[c, str(x)[:80]] for c, x in reasons]})
    return res


def print_report(res):
    print("候補 + 採用の往復(%s・書き出し先 %s)" % (res["dataJson"], res["outDir"]))
    if res["unreadable"]:
        print("data.json が読めません")
        return
    print("配信 %d 本(読めない %d 本): 合った %d 本・合わない %d 本" % (res["videos"], res["broken"], res["ok"], res["ng"]))
    print("案件を引けた配信 %d 本(案件 %d・配信が 2 本以上の案件 %d)" % (res["withCase"], res["cases"], res["sharedCases"]))
    print("マーク: 候補 %d・採用 %d(採用の側に残した手つかずの候補 %d)・並びを持った配信 %d・相対にした path %d" % (
        res["candidateMarks"], res["adoptionMarks"], res["pinned"], res["ordered"], res["relPaths"]))
    for code, n in sorted(res["reasons"].items(), key=lambda x: -x[1]):
        print("  %-24s %4d 本" % (REASONS.get(code, code), n))
    for x in res["examples"]:
        print("  %s %-24s %s" % (x["id"], x["title"][:24], "・".join("%s(%s)" % (REASONS.get(c, c), e) for c, e in x["reasons"])))


def main(argv=None):
    p = argparse.ArgumentParser(description="スタジオの配信を候補 + 採用に分けて重ね直し、今の配信と同じかを確かめる(作業データは読むだけ)")
    p.add_argument("--data-dir", help="作業データの親フォルダ(既定 %%LOCALAPPDATA%%/youtube-tools。テスト用)")
    p.add_argument("--out-dir", help="スタジオの書き出し先(既定 = スタジオの設定の outDir)")
    p.add_argument("--ids", help="この配信の id だけ(「,」区切り)")
    p.add_argument("--show", type=int, default=10, help="合わなかった配信の例をいくつ出すか(既定 10)")
    p.add_argument("--json", action="store_true", help="結果を JSON で標準出力に出す(ファイルには書かない)")
    args = p.parse_args(argv)
    C.utf8_stdout()
    res = evaluate(args.data_dir, args.out_dir, C.split_ids(args.ids), max(0, args.show))
    if args.json:
        print(json.dumps(res, ensure_ascii=False, indent=1))
    else:
        print_report(res)
    return 0 if not res["unreadable"] else 1


if __name__ == "__main__":
    sys.exit(main())
