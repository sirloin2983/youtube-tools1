#!/usr/bin/env python3
"""「2つ目のエンジンとの食い違いの候補」(行に出る札「別」)が、校正を本当に速くしているかを数字で見る道具(精度改善の計画 第2版 D1-b の「印の当たり率」)。

    python dev/eval_alt.py [--since YYYY-MM-DD] [--until YYYY-MM-DD] [--json] [--data-dir 作業データの親フォルダ]

- 作業データは**読むだけ**(transcribe の transcripts/<id>.json・<id>.alt.json と、学習の記録 learn-feedback.json)。何も書き換えない。
  --json のときだけ、結果を文字起こしの作業データの evals\\alt\\<日時>.json に残す(schema youtube-tools-alt-eval/v1。evals の置き場所は eval_cut.py・eval_speakers.py と同じ規則)。
- 対象 = 評価用でない文書のうち、alt.json(2つ目のエンジンの認識結果)があるもの(評価用には候補を出さない決まり)。editor の部品は eval_asr.py と同じやり方で読み込む
  (serve.py の alt_diffs・alt_fold・_groups を使う。作業データの場所はここで入口と同じ規則 ytt_core.datadir で決める。サーバーの DATA_DIR は一時フォルダ)。
- 指標:
    採否の記録: 学習の記録の alt = {acc, rej}(画面で「別」の候補を採用・却下した数)→ 採用率。時期の指定は効かない(記録に時刻が無い)
    当たり率(候補 → 人の最終): 機械の最初の出力(文書の original。人が直す前の行)に対して alt_diffs で候補を出し直し(今の行ではなく、直す前の行)、
      候補ごとに、同じ時刻の重なりのまとまり(editor の _groups = 精度測定と同じ)の人の最終(segments)と比べて分ける。比べるときの文字の寄せ方は alt_fold(記号・伸ばし・空白・かな/カナ・全半角を無視)
        当たり … 人の最終がその所で候補の right になっている
        外れ(人はそのまま)… 人の最終に wrong がそのまま残っている
        別の直し … 人はその所を wrong でも right でもない文字に直した(隣に文字を足した・消した場合も、その所に触ったので数える)
        分からない … まとまりの人の行が校正済みでない・行が消された・まとまりが長すぎる(判定しない)。**率は校正済みのまとまりだけで出す**
      率 = 当たり ÷ (当たり + 外れ + 別の直し)。「当たり」は候補を採ったら正しかった割合の目安(人はつられて直さないこともある = 外れは甘く出る)
    拾えた率(人の直し → 候補): 校正済みのまとまり(機械の行も人の行もある)で、人が機械の文字を直した所(寄せた文字の食い違い。置き換え・足し・消し)のうち、
      同じ所に候補が出ていた割合と、そのうち候補が当たりだった割合。長い直し(寄せた文字で 12 字を超える)は候補の対象外なので、短い直し(12 字以下)だけの数も並べる
    alt_diffs が出さなかった数の内訳: long(長すぎる)・cross(行をまたぐ)・mostly(行の半分以上が違う)・notation(表記だけの違いらしい)・edge(窓の境目)の合計
    2つ目のエンジン(alt.json の engine・model)ごとの表と、文書ごと(当たり率が低い順に 10 件)の表
- --since / --until(原則 4: 時期で分ける)は まとまりの時刻で絞る(until はその日を含む)。まとまりの時刻 = 人の行の校正した時刻 proofedAt の最大(あれば)、無ければ文書の更新時刻 updatedAt
  (eval_speakers.py と同じ考え方。proofedAt を作る前に校正済みになった行は更新時刻になる)
- 字幕に出さない行 noSub(editor/ed_learn.py の split_nosub。行の半分以上が noSub の行の時間に入る機械の行も)は、候補の当たり率にも拾えた率にも入れない(その行は字幕に出ないので、候補で直す意味がない)。
  その時間に出ていた候補の数と noSub の行の数だけ、結果の noSub に別に出す。noSub が無い文書の数は今までと同じ
- 判定できた候補が 100 件未満のときは「まだ少ない(参考)」と出す(少ないデータでエンジンや既定を決めない)
- 注意: original(機械の最初の出力)は、再認識(範囲・全体・疑わしい所)のあとは再認識後のものに替わる。alt.json は最初の文字起こしの範囲の音声に対するもの
"""
import argparse
import bisect
import datetime
import difflib
import json
import os
import re
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
if REPO not in sys.path:
    sys.path.insert(0, REPO)
if HERE not in sys.path:
    sys.path.insert(0, HERE)
from ytt_core import datadir  # noqa: E402

SCHEMA = "youtube-tools-alt-eval/v1"
FEW_CANDS = 100                    # 判定できた候補がこれより少ないときは「まだ少ない(参考)」
MAX_DOC_BYTES = 64 * 1024 * 1024
MAX_GROUP_CHARS = 4000             # まとまりの寄せた文字がこれを超えたら判定しない(比べる計算が重くなりすぎないように)
DOC_RE = re.compile(r"^[0-9a-f]{12}\.json\Z")
ENV0 = dict(os.environ)            # 作業データの場所を決めるための環境変数(serve.py を読み込むと TRANSCRIBE_DATA_DIR が一時フォルダになるので、その前の値)
UNKNOWN_LABELS = {"removed": "人の行が消された", "notProofed": "校正済みでない", "tooLong": "まとまりが長すぎる", "misaligned": "位置が合わない"}
STAT_KEYS = ("long", "cross", "mostly", "notation", "edge")
STAT_LABELS = {"long": "長すぎる", "cross": "行をまたぐ", "mostly": "行の半分以上が違う", "notation": "表記だけの違い", "edge": "窓の境目"}

_SERVE = None


# ---------------------------------------------------------------- 準備・読み込み(読むだけ)

def get_serve():
    """editor の serve.py(部品の名前の受付)。eval_asr.py と同じ読み込み方。書き込みは一時フォルダ。1プロセスで1回だけ"""
    global _SERVE
    if _SERVE is None:
        import eval_asr
        _SERVE = eval_asr.load_serve()
    return _SERVE


def read_json(path, default=None, limit=None):
    try:
        if limit and os.path.getsize(path) > limit:
            return default
        with open(path, "r", encoding="utf-8-sig") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def locate(data_dir=None):
    """-> 文字起こしの作業データのフォルダ。置き場所の規則は ytt_core.datadir の1か所(data_dir はテスト用。そこを全ツールの作業データの親フォルダとして使う)"""
    env = {"YTT_DATA_DIR": os.path.abspath(data_dir)} if data_dir else ENV0
    return datadir.locate("transcribe", REPO, env)


def read_alt(S, tdir, tid):
    """<id>.alt.json(形が違えば None)。editor の read_alt は DATA_DIR(一時フォルダ)を見るので、ここで読む"""
    d = read_json(os.path.join(tdir, tid + ".alt.json"), None, S.MAX_ALT_BYTES)
    if not isinstance(d, dict) or d.get("schema") != S.ALT_SCHEMA or not isinstance(d.get("rows"), list):
        return None
    return d


def read_feedback(S, root):
    """学習の記録(learn-feedback.json)の alt = {acc, rej} か None。読み方は editor の load_feedback(置き場所を一時的に差し替えて呼ぶ)"""
    import ed_state
    old = ed_state.FEEDBACK
    ed_state.FEEDBACK = os.path.join(root, "learn-feedback.json")
    try:
        return S.load_feedback().get("alt")
    finally:
        ed_state.FEEDBACK = old


# ---------------------------------------------------------------- 日時・数の小道具

def day_ms(s, end=False):
    """YYYY-MM-DD(この PC の時刻)-> その日の始まり(end=True なら次の日の始まり)のミリ秒"""
    try:
        d = datetime.datetime.strptime(s, "%Y-%m-%d")
    except (TypeError, ValueError):
        raise SystemExit("日付は YYYY-MM-DD で指定してください: %r" % s)
    if end:
        d += datetime.timedelta(days=1)
    return int(time.mktime(d.timetuple()) * 1000)


def pct(x):
    return "  -  " if x is None else "%4.0f%%" % (x * 100)


def rate(c, n):
    return round(c / n, 4) if n else None


def num(x):
    return x if isinstance(x, (int, float)) and not isinstance(x, bool) and x == x else None


def in_range(t, since_ms, until_ms):
    return not ((since_ms is not None and t < since_ms) or (until_ms is not None and t >= until_ms))


# ---------------------------------------------------------------- 1つの文書(純粋な関数)

def clean_rows(items, with_text=True):
    """start・end が数の行だけを start の順に(安定)。editor の _groups・alt_diffs が使える形"""
    out = [g for g in items or [] if isinstance(g, dict) and num(g.get("start")) is not None and num(g.get("end")) is not None
           and (not with_text or isinstance(g.get("text"), str))]
    return sorted(out, key=lambda g: g["start"])


def fold_text(S, text):
    """寄せた文字(alt_fold)の並びと、それぞれの元の位置 -> (str, [位置])"""
    cs, ps = [], []
    for p, ch in enumerate(text):
        for c in S.alt_fold(ch):
            cs.append(c)
            ps.append(p)
    return "".join(cs), ps


class Group:
    """時刻の重なりのまとまり 1 つ(機械の行 go・人の行 ge)。比べる計算は呼ばれたときに 1 回だけ"""

    def __init__(self, S, orig, segs, go, ge):
        self.S, self.go, self.ge = S, go, ge
        self.orig_text, self.offsets = "", {}
        for k in go:
            self.offsets[k] = len(self.orig_text)
            self.orig_text += str(orig[k].get("text") or "")
        self.final_text = "".join(str(segs[i].get("text") or "") for i in ge)
        self.proofed = bool(ge) and all(segs[i].get("proofed") is True for i in ge)
        self._ops = None

    def too_long(self):
        return len(self.orig_text) > MAX_GROUP_CHARS or len(self.final_text) > MAX_GROUP_CHARS

    def ops(self):
        """(寄せた機械の文字, その位置, 寄せた人の文字, [opcodes])"""
        if self._ops is None:
            fo, po = fold_text(self.S, self.orig_text)
            fh, _ph = fold_text(self.S, self.final_text)
            self._ops = (fo, po, fh, difflib.SequenceMatcher(None, fo, fh, autojunk=False).get_opcodes())
        return self._ops


def map_span(ops, a, b, inclusive):
    """機械の寄せた文字の区間 [a, b) に対応する、人の寄せた文字の区間 [c, d)。
    等しい所は 1 対 1・置き換えと消しは、区間がかかった塊の全体。inclusive は区間のすぐ隣の足した文字(挿入)も入れる"""
    c = d = None
    for tag, i1, i2, j1, j2 in ops:
        if c is None:
            if tag == "insert":
                if i1 == a:
                    c = j1 if inclusive else j2
            elif i1 <= a < i2:
                c = j1 + (a - i1) if tag == "equal" else j1
        if i1 < b <= i2 and tag != "insert":
            d = j1 + (b - i1) if tag == "equal" else j2
        elif tag == "insert" and i1 == b and d is not None and inclusive:
            d = j2
    return c, d


def judge_candidate(S, g, cand_k, cand):
    """候補 1 つ(機械の行 cand_k の中の位置 cand["i"]・wrong・right)を、そのまとまり g の人の最終で判定する
    -> ("hit" | "miss" | "other" | "unknown", 理由, 機械の寄せた文字の区間 (a, b) か None)"""
    if not g.ge:
        return "unknown", "removed", None
    if not g.proofed:
        return "unknown", "notProofed", None
    if g.too_long():
        return "unknown", "tooLong", None
    wrong, right = cand["wrong"], cand["right"]
    p0 = g.offsets[cand_k] + cand["i"]
    p1 = p0 + len(wrong)
    if g.orig_text[p0:p1] != wrong:
        return "unknown", "misaligned", None
    fo, po, fh, ops = g.ops()
    a, b = bisect.bisect_left(po, p0), bisect.bisect_left(po, p1)
    if a >= b:
        return "unknown", "misaligned", None
    fw, fr = S.alt_fold(wrong), S.alt_fold(right)
    spans = []
    for inclusive in (False, True):
        c, d = map_span(ops, a, b, inclusive)
        if c is None or d is None or d < c:
            return "unknown", "misaligned", None
        spans.append(fh[c:d])
    excl, incl = spans
    if fr and fr in (excl, incl):
        return "hit", "", (a, b)
    if incl == fw:
        return "miss", "", (a, b)
    return "other", "", (a, b)


def judge_doc(S, doc, alt, since_ms=None, until_ms=None):
    """1つの文書(評価用でない・original と segments がある)と alt.json から、候補の判定と人の直しの拾えた数を出す。ファイルには触らない
    -> {"cands": [{"status", "why", "wrong", "right"}](時期の範囲の中のまとまりだけ), "fixes": [{"short", "covered", "hit"}], "stats": alt_diffs の数えた理由,
        "outOfRange": 時期の外で数えなかった候補の数, "inRange": 範囲の中のまとまりが 1 つでもあったか, "noSub": {"rows": noSub の行の数, "candidates": その時間に出ていた候補の数(数えない)}}"""
    orig_all = clean_rows(doc.get("original"))
    segs = clean_rows(doc.get("segments"), with_text=False)
    # 候補は機械の行すべてで出す(alt_diffs は窓の境目の行を特別に扱うので、行を先に外すと別の行の候補が消える)。そのあとで、字幕に出さない行(noSub)の時間の機械の行の候補は
    # 当たり率にも拾えた率にも入れない(その行は字幕に出ない = 直す必要がない。editor の split_nosub)。数だけ別に数える
    orig, segs, ns_orig, ns_segs = S.split_nosub(orig_all, segs)
    rows = [{"id": "o%d" % k, "start": o["start"], "end": o["end"], "text": o["text"], "proofed": False} for k, o in enumerate(orig_all)]
    cands, stats = S.alt_diffs(rows, alt.get("rows") or [])
    main_idx = {id(o): j for j, o in enumerate(orig)}      # 全部の行の番号 → 本体の行の番号(noSub の時間の行は無い)
    ns_cands = 0
    doc_t = num(doc.get("updatedAt")) or 0
    groups = [Group(S, orig, segs, go, ge) for go, ge in S._groups(orig, segs)]
    grp_of = {k: gi for gi, g in enumerate(groups) for k in g.go}

    def group_time(g):
        ts = [num(segs[i].get("proofedAt")) or doc_t for i in g.ge]
        return max(ts) if g.proofed and ts else doc_t
    out = {"cands": [], "fixes": [], "stats": dict(stats), "outOfRange": 0, "inRange": False, "noSub": {"rows": len(ns_segs), "candidates": 0}}
    by_group = {}   # まとまり -> [(a, b, 判定)]
    for cand in cands:
        k = main_idx.get(id(orig_all[int(cand["seg"][1:])]))
        if k is None:
            ns_cands += 1
            continue
        gi = grp_of.get(k)
        if gi is None:
            continue
        g = groups[gi]
        if not in_range(group_time(g), since_ms, until_ms):
            out["outOfRange"] += 1
            continue
        out["inRange"] = True
        status, why, span = judge_candidate(S, g, k, cand)
        out["cands"].append({"status": status, "why": why, "wrong": cand["wrong"], "right": cand["right"]})
        if span:
            by_group.setdefault(gi, []).append((span[0], span[1], status))
    out["noSub"]["candidates"] = ns_cands
    # 人の直しのうち、候補が同じ所に出ていたもの(機械の行も人の行もある・校正済み・長すぎないまとまりだけ)
    for gi, g in enumerate(groups):
        if not (g.go and g.ge and g.proofed) or g.too_long() or not in_range(group_time(g), since_ms, until_ms):
            continue
        out["inRange"] = True
        fo, _po, fh, ops = g.ops()
        for tag, i1, i2, j1, j2 in ops:
            if tag == "equal":
                continue
            hits = [st for a, b, st in by_group.get(gi, []) if (a < i2 and i1 < b) or (i1 == i2 and a <= i1 <= b)]
            out["fixes"].append({"short": (i2 - i1) <= S.ALT_MAX_CHARS and (j2 - j1) <= S.ALT_MAX_CHARS,
                                 "covered": bool(hits), "hit": "hit" in hits})
    return out


# ---------------------------------------------------------------- 集計

class Agg:
    """文書の集まりぶんの集計"""

    def __init__(self):
        self.docs = self.cands = 0
        self.status = {"hit": 0, "miss": 0, "other": 0, "unknown": 0}
        self.why = {}
        self.stats = {k: 0 for k in STAT_KEYS}
        self.fix = {"total": 0, "covered": 0, "coveredHit": 0, "short": 0, "shortCovered": 0, "shortHit": 0}
        self.nosub = {"docs": 0, "rows": 0, "candidates": 0}   # 字幕に出さない行(数に入れない。件数だけ)

    def add(self, r):
        self.docs += 1
        for c in r["cands"]:
            self.cands += 1
            self.status[c["status"]] += 1
            if c["status"] == "unknown":
                self.why[c["why"]] = self.why.get(c["why"], 0) + 1
        for k in STAT_KEYS:
            self.stats[k] += r["stats"].get(k, 0)
        ns = r.get("noSub") or {}
        if ns.get("rows"):
            self.nosub["docs"] += 1
            self.nosub["rows"] += ns["rows"]
            self.nosub["candidates"] += ns.get("candidates", 0)
        f = self.fix
        for x in r["fixes"]:
            f["total"] += 1
            f["covered"] += x["covered"]
            f["coveredHit"] += x["hit"]
            if x["short"]:
                f["short"] += 1
                f["shortCovered"] += x["covered"]
                f["shortHit"] += x["hit"]

    def result(self):
        s, f = self.status, self.fix
        judged = s["hit"] + s["miss"] + s["other"]
        return {"docs": self.docs, "candidates": self.cands, "judged": judged,
                "hit": s["hit"], "miss": s["miss"], "other": s["other"], "unknown": s["unknown"], "unknownWhy": dict(sorted(self.why.items())),
                "hitRate": rate(s["hit"], judged), "missRate": rate(s["miss"], judged), "otherRate": rate(s["other"], judged),
                "pickup": {"fixes": f["total"], "covered": f["covered"], "coveredRate": rate(f["covered"], f["total"]),
                           "coveredHit": f["coveredHit"], "hitRateOfCovered": rate(f["coveredHit"], f["covered"]),
                           "shortFixes": f["short"], "shortCovered": f["shortCovered"], "shortCoveredRate": rate(f["shortCovered"], f["short"]),
                           "shortHit": f["shortHit"], "shortHitRateOfCovered": rate(f["shortHit"], f["shortCovered"])},
                "skipped": dict(self.stats), "noSub": dict(self.nosub)}


def engine_key(alt):
    return "%s / %s" % (alt.get("engine") or "?", alt.get("model") or "?")


# ---------------------------------------------------------------- 全体

def evaluate(data_dir=None, since=None, until=None):
    root = locate(data_dir)       # serve.py を読み込む前に決める(読み込むと TRANSCRIBE_DATA_DIR が一時フォルダになる)
    S = get_serve()
    tdir = os.path.join(root, "transcripts")
    since_ms = day_ms(since) if since else None
    until_ms = day_ms(until, end=True) if until else None
    total, by_engine, by_doc = Agg(), {}, []
    skipped = {"evalSet": 0, "noOriginal": 0, "broken": 0, "outOfRange": 0}
    no_alt = out_cands = 0
    for name in sorted(os.listdir(tdir)) if os.path.isdir(tdir) else []:
        if not DOC_RE.match(name):
            continue
        tid = name[:-5]
        if not os.path.isfile(os.path.join(tdir, tid + ".alt.json")):
            no_alt += 1
            continue
        doc = read_json(os.path.join(tdir, name), None, MAX_DOC_BYTES)
        alt = read_alt(S, tdir, tid)
        if not isinstance(doc, dict) or alt is None:
            skipped["broken"] += 1
            continue
        if doc.get("evalSet") is True:
            skipped["evalSet"] += 1
            continue
        if not isinstance(doc.get("original"), list) or not doc["original"] or not isinstance(doc.get("segments"), list):
            skipped["noOriginal"] += 1
            continue
        r = judge_doc(S, doc, alt, since_ms, until_ms)
        out_cands += r["outOfRange"]
        if not r["inRange"]:
            skipped["outOfRange"] += 1
            continue
        key = engine_key(alt)
        total.add(r)
        by_engine.setdefault(key, Agg()).add(r)
        one = Agg()
        one.add(r)
        o = one.result()
        by_doc.append({"id": tid, "title": str(doc.get("title") or "")[:40], "engine": key, "candidates": o["candidates"], "judged": o["judged"], "hit": o["hit"],
                       "miss": o["miss"], "other": o["other"], "unknown": o["unknown"], "hitRate": o["hitRate"]})
    res = total.result()
    few = res["judged"] < FEW_CANDS
    fb = read_feedback(S, root)
    notes = []
    if skipped["noOriginal"]:
        notes.append("機械の最初の出力(original)が無い文書が %d 件あります(測っていません)" % skipped["noOriginal"])
    if skipped["evalSet"]:
        notes.append("評価用なのに alt.json がある文書が %d 件あります(測っていません)" % skipped["evalSet"])
    if skipped["broken"]:
        notes.append("読めない文書・alt.json が %d 件あります" % skipped["broken"])
    if since or until:
        notes.append("採否の記録(採用・却下の数)は時期で絞れません(記録に時刻が無い)")
    notes.append("人は候補につられる(迷うと直さずに通す)ので、外れ・別の直しは少なめ(当たりは甘め)に出ます。校正済みでないまとまりは「分からない」にして率に入れていません")
    notes.append("機械の最初の出力(original)は、再認識のあとは再認識後のものです")
    meta = {"schema": SCHEMA, "at": int(time.time() * 1000), "since": since, "until": until, "git": git_rev(), "dataDir": root,
            "docs": total.docs, "noAlt": no_alt, "candidates": res["candidates"], "judged": res["judged"], "few": few,
            "fewNote": "まだ少ない(参考): 判定できた候補が %d 件(%d 件未満)。これでエンジンや既定を決めない" % (res["judged"], FEW_CANDS) if few and total.docs else "",
            "skipped": skipped, "outOfRangeCandidates": out_cands, "notes": notes}
    feedback = None
    if fb:
        feedback = {"accepted": fb["acc"], "rejected": fb["rej"], "acceptRate": rate(fb["acc"], fb["acc"] + fb["rej"])}
    return {"meta": meta, "feedback": feedback, "total": res,
            "byEngine": {k: v.result() for k, v in sorted(by_engine.items())}, "byDoc": by_doc}


def git_rev():
    try:
        return subprocess.run(["git", "-C", REPO, "rev-parse", "--short", "HEAD"], capture_output=True, text=True, timeout=10).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return ""


# ---------------------------------------------------------------- 表示・保存

def print_agg(title, r, indent="  "):
    print("%s[%s]  文書 %d 件・候補 %d 件(判定できた %d 件)" % (indent, title, r["docs"], r["candidates"], r["judged"]))
    if not r["candidates"]:
        return
    print("%s  当たり %d(%s)・外れ(人はそのまま)%d(%s)・別の直し %d(%s)  分からない %d%s"
          % (indent, r["hit"], pct(r["hitRate"]).strip(), r["miss"], pct(r["missRate"]).strip(), r["other"], pct(r["otherRate"]).strip(), r["unknown"],
             "(" + "・".join("%s %d" % (UNKNOWN_LABELS.get(k, k), n) for k, n in r["unknownWhy"].items()) + ")" if r["unknownWhy"] else ""))
    p = r["pickup"]
    if p["fixes"]:
        print("%s  拾えた率: 人の直し %d か所のうち、候補が同じ所に出ていた %d(%s)・そのうち当たり %d(%s)   短い直し(12 字以下)だけ: %d か所 → 候補あり %d(%s)・当たり %d(%s)"
              % (indent, p["fixes"], p["covered"], pct(p["coveredRate"]).strip(), p["coveredHit"], pct(p["hitRateOfCovered"]).strip(),
                 p["shortFixes"], p["shortCovered"], pct(p["shortCoveredRate"]).strip(), p["shortHit"], pct(p["shortHitRateOfCovered"]).strip()))
    ns = r.get("noSub") or {}
    if ns.get("rows"):
        print("%s  字幕に出さない(noSub)の行 %d(文書 %d 件)・その時間に出ていた候補 %d 件は数に入れていません" % (indent, ns["rows"], ns["docs"], ns["candidates"]))
    sk = r["skipped"]
    print("%s  alt_diffs が出さなかった数: %s" % (indent, "・".join("%s %d" % (STAT_LABELS[k], sk[k]) for k in STAT_KEYS)))


def print_report(res):
    m = res["meta"]
    rng = "%s 〜 %s" % (m["since"] or "最初", m["until"] or "今") if (m["since"] or m["until"]) else "全期間"
    print("2つ目のエンジンの候補の当たり率の測定(%s)  文書 %d 件・候補 %d 件(判定できた %d 件)  作業データ: %s" % (rng, m["docs"], m["candidates"], m["judged"], m["dataDir"]))
    fb = res["feedback"]
    if fb:
        print("採否の記録(画面で「別」の候補を採用・却下した数): 採用 %d・却下 %d  採用率 %s" % (fb["accepted"], fb["rejected"], pct(fb["acceptRate"]).strip()))
    else:
        print("採否の記録(画面で「別」の候補を採用・却下した数): まだありません")
    if m["fewNote"]:
        print("★ " + m["fewNote"])
    if not m["docs"]:
        print("(対象なし: 評価用でない文書で、2つ目のエンジンで聞いた結果(alt.json)がある文書がありません。alt.json なしの文書 %d 件)" % m["noAlt"])
    else:
        print_agg("全部", res["total"])
        if len(res["byEngine"]) > 0:
            print("\n  [2つ目のエンジンごと]")
            for k, r in res["byEngine"].items():
                print_agg(k, r, "   ")
        print("\n  [文書ごと(当たり率が低い順に10件)]")
        for d in sorted(res["byDoc"], key=lambda d: (d["hitRate"] if d["hitRate"] is not None else 2, d["id"]))[:10]:
            print("    %s %-34s 候補 %3d・判定 %3d  当たり %3d・外れ %3d・別の直し %3d・分からない %3d  当たり率 %s  %s"
                  % (d["id"], d["engine"], d["candidates"], d["judged"], d["hit"], d["miss"], d["other"], d["unknown"], pct(d["hitRate"]).strip(), d["title"]))
    for n in m["notes"]:
        print("注意: " + n)


def save(res, root):
    d = os.path.join(root, "evals", "alt")
    os.makedirs(d, exist_ok=True)
    path = os.path.join(d, "%s.json" % datetime.datetime.now().strftime("%Y%m%d-%H%M%S"))
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(res, f, ensure_ascii=False, indent=1)
    os.replace(tmp, path)
    return path


def main(argv=None):
    p = argparse.ArgumentParser(description="2つ目のエンジンとの食い違いの候補の当たり率を、人の最終で測る(作業データは読むだけ)")
    p.add_argument("--since", help="この日(YYYY-MM-DD)以後だけ(まとまりの時刻 = 人の行の proofedAt の最大、無ければ文書の更新時刻)")
    p.add_argument("--until", help="この日(YYYY-MM-DD。この日を含む)までだけ")
    p.add_argument("--json", action="store_true", help="同じ形の JSON を 文字起こしの作業データの evals/alt/<日時>.json に残す")
    p.add_argument("--data-dir", help="作業データの親フォルダ(既定 %%LOCALAPPDATA%%\\youtube-tools。テスト用)")
    args = p.parse_args(argv)
    res = evaluate(args.data_dir, args.since, args.until)
    print_report(res)
    if args.json:
        print("\n保存: " + save(res, res["meta"]["dataDir"]))
    return res


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass
    main()
