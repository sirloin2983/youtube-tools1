#!/usr/bin/env python3
"""「2つ目のエンジンとの食い違いの候補」(行に出る札「別」)が、校正を本当に速くしているかを数字で見る道具(精度改善の計画 第2版 D1-b の「印の当たり率」)。

    python src/eval/tools/eval_alt.py [--since YYYY-MM-DD] [--until YYYY-MM-DD] [--source alt|yt|both] [--include-eval] [--json] [--data-dir 作業データの親フォルダ]

- 作業データは**読むだけ**(transcribe の transcripts/<id>.json・<id>.alt.json と、学習の記録 learn-feedback.json)。何も書き換えない。
  --json のときだけ、結果を文字起こしの作業データの evals\\alt\\<日時>.json に残す(schema youtube-tools-alt-eval/v1。evals の置き場所は eval_cut.py・eval_speakers.py と同じ規則)。
- 対象 = 評価用でない文書のうち、alt.json(2つ目のエンジンの認識結果)があるもの(評価用には候補を出さない決まり)。editor の部品は eval_asr.py と同じやり方で読み込む
  (serve.py の alt_diffs・alt_fold・_groups を使う。作業データの場所はここで入口と同じ規則 ytt.datadir で決める。サーバーの DATA_DIR は一時フォルダ)。
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
- 字幕に出さない行 noSub(src/human/proof/learn.py の split_nosub。行の半分以上が noSub の行の時間に入る機械の行も)は、候補の当たり率にも拾えた率にも入れない(その行は字幕に出ないので、候補で直す意味がない)。
  その時間に出ていた候補の数と noSub の行の数だけ、結果の noSub に別に出す。noSub が無い文書の数は今までと同じ
- 判定できた候補が 100 件未満のときは「まだ少ない(参考)」と出す(少ないデータでエンジンや既定を決めない)
- 注意: original(機械の最初の出力)は、再認識(範囲・全体・疑わしい所)のあとは再認識後のものに替わる。alt.json は最初の文字起こしの範囲の音声に対するもの
- --source(候補の出どころ。既定 alt = 今までどおり): yt = 元の配信の YouTube の字幕の候補(案 A1。行の札「YT」。src/human/proof/ytcap.py)。
  保存してある配信ごとの字幕(作業データの ytcaps/<配信の ID>.json)を、文書の clip(スタジオの切り抜き)の範囲で切り出し(ytcap_doc_rows)、
  editor の ytcap_diffs(alt_diffs + 切り抜きの境目を出さない)で候補を出し直す。**道具は通信しない**(字幕が保存されていない文書は数えない = noYt)。
  エンジンごとの表は「youtube / auto(自動字幕)・manual(配信者の字幕)」。採否の記録は学習の記録の yt。
  both = alt と yt を別々に出し、両方がある文書で 2 つが同じ候補(同じ行・同じ位置・同じ直し)を出した所の当たり率(一致)も出す(一致は当たりやすいかを見るため)
- 名簿の呼び名(名前に強いかを見る): まとまりの人の最終(無ければ機械)の文字に名簿の名前・呼び名(src/pipeline/transcribe/roster.py の find_in_text)がある所の、
  候補の当たり / 外れ / 別の直しと、人の直しの拾えた率を、全体とは別に出す(names)
- --include-eval: 評価用の文書も測る(読むだけ。候補は画面に出さない決まりのまま・測るだけなら定点の正解は寄らない。評価用でしか確かめ済みの文書が無いときに)
"""
import argparse
import bisect
import difflib
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.dirname(os.path.dirname(HERE))   # tools -> eval -> src
if not __package__:   # スクリプトとして起動したとき(py -3.10 src/eval/tools/eval_alt.py)だけ。src を先頭に・この道具のフォルダは外す(兄弟は絶対 import で読む。見本 pipeline/transcribe/worker.py)
    sys.path[:] = [SRC] + [p for p in sys.path if os.path.normcase(os.path.abspath(p or os.curdir)) not in (os.path.normcase(HERE), os.path.normcase(SRC))]
from eval.tools import _evalcommon as C  # noqa: E402  共通の部品(作業データの場所・時期・率・保存。src を sys.path に足す)
from eval.tools._evalcommon import rate, read_json  # noqa: E402
from ytt import docloc  # noqa: E402

SCHEMA = "youtube-tools-alt-eval/v1"
FEW_CANDS = 100                    # 判定できた候補がこれより少ないときは「まだ少ない(参考)」
MAX_DOC_BYTES = C.DOC_BYTES
MAX_GROUP_CHARS = 4000             # まとまりの寄せた文字がこれを超えたら判定しない(比べる計算が重くなりすぎないように)
ENV0 = dict(os.environ)            # 作業データの場所を決めるための環境変数(serve.py を読み込むと TRANSCRIBE_DATA_DIR が一時フォルダになるので、その前の値)
UNKNOWN_LABELS = {"removed": "人の行が消された", "notProofed": "校正済みでない", "tooLong": "まとまりが長すぎる", "misaligned": "位置が合わない"}
STAT_KEYS = ("long", "cross", "mostly", "notation", "edge")
STAT_LABELS = {"long": "長すぎる", "cross": "行をまたぐ", "mostly": "行の半分以上が違う", "notation": "表記だけの違い", "edge": "窓の境目", "clipEdge": "切り抜きの境目"}
SOURCES = ("alt", "yt", "both")
SOURCE_LABELS = {"alt": "2つ目のエンジンの候補(札「別」)", "yt": "YouTube の字幕の候補(札「YT」)"}

_SERVE = None


# ---------------------------------------------------------------- 準備・読み込み(読むだけ)

def get_serve():
    """editor の serve.py(部品の名前の受付)。eval_asr.py と同じ読み込み方。書き込みは一時フォルダ。1プロセスで1回だけ"""
    global _SERVE
    if _SERVE is None:
        from eval.tools import eval_asr
        _SERVE = eval_asr.load_serve()
    return _SERVE


def locate(data_dir=None):
    """-> 文字起こしの作業データのフォルダ。置き場所の規則は ytt.datadir の1か所(data_dir はテスト用。そこを全ツールの作業データの親フォルダとして使う)"""
    return C.locate("transcribe", data_dir, ENV0)


def read_ytcache(S, root, vid):
    """作業データの ytcaps/<配信の ID>.json(配信ごとの YouTube の字幕。形が違えば None)。editor の ytcap_load は DATA_DIR(一時フォルダ)を見るので、ここで読む"""
    if not S.YTCAP_VID_RE.match(str(vid or "")):
        return None
    d = read_json(os.path.join(root, "ytcaps", vid + ".json"), None, S.YTCAP_MAX_CACHE_BYTES)
    return d if S.ytcap_valid_cache(d, vid) else None


def name_checker(S):
    """名簿の呼び名が文字にあるか(src/pipeline/transcribe/roster.py の find_in_text。正式な名前か、普通の言葉と重ならない 3 文字以上の呼び名)"""
    from pipeline.transcribe import roster
    r = roster.load(S.ROSTER)
    return lambda text: bool(roster.find_in_text(text, r))


def read_alt(S, tdir, tid):
    """<id>.alt.json(形が違えば None)。editor の read_alt は DATA_DIR(一時フォルダ)を見るので、ここで読む(tdir = 作業データ/transcripts)"""
    d = read_json(docloc.doc_file(tid, ".alt.json", os.path.dirname(tdir)), None, S.MAX_ALT_BYTES)
    if not isinstance(d, dict) or d.get("schema") != S.ALT_SCHEMA or not isinstance(d.get("rows"), list):
        return None
    return d


def read_feedback(S, root, key="alt"):
    """学習の記録(learn-feedback.json)の alt(yt)= {acc, rej} か None。読み方は editor の load_feedback(置き場所 S.FEEDBACK を一時的に差し替えて呼ぶ。
    持ち主は ytt/workdata = serve の名前の受付が届ける。RS3-0A まで ed_state に直に代入していた)"""
    old = S.FEEDBACK
    S.FEEDBACK = os.path.join(root, "learn-feedback.json")
    try:
        return S.load_feedback().get(key)
    finally:
        S.FEEDBACK = old


# ---------------------------------------------------------------- 数の小道具

def pct(x):
    """割合の表示(詰めた形。None は「-」)"""
    return C.pct(x).strip()


def num(x):
    return x if isinstance(x, (int, float)) and not isinstance(x, bool) and x == x else None


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


def judge_doc(S, doc, alt, since_ms=None, until_ms=None, diff_fn=None, has_name=None):
    """1つの文書(評価用でない・original と segments がある)と alt.json から、候補の判定と人の直しの拾えた数を出す。ファイルには触らない
    -> {"cands": [{"status", "why", "wrong", "right"}](時期の範囲の中のまとまりだけ), "fixes": [{"short", "covered", "hit"}], "stats": alt_diffs の数えた理由,
        "outOfRange": 時期の外で数えなかった候補の数, "inRange": 範囲の中のまとまりが 1 つでもあったか, "noSub": {"rows": noSub の行の数, "candidates": その時間に出ていた候補の数(数えない)}}
    diff_fn = 候補の出し方(既定 alt_diffs。yt は ytcap_diffs)。has_name = 文字に名簿の呼び名があるか(候補・直しの "name")。候補には機械の行の番号 row と位置 i も付ける(alt と yt の一致を見る)"""
    orig_all = clean_rows(doc.get("original"))
    segs = clean_rows(doc.get("segments"), with_text=False)
    # 候補は機械の行すべてで出す(alt_diffs は窓の境目の行を特別に扱うので、行を先に外すと別の行の候補が消える)。そのあとで、字幕に出さない行(noSub)の時間の機械の行の候補は
    # 当たり率にも拾えた率にも入れない(その行は字幕に出ない = 直す必要がない。editor の split_nosub)。数だけ別に数える
    orig, segs, ns_orig, ns_segs = S.split_nosub(orig_all, segs)
    rows = [{"id": "o%d" % k, "start": o["start"], "end": o["end"], "text": o["text"], "proofed": False} for k, o in enumerate(orig_all)]
    cands, stats = (diff_fn or S.alt_diffs)(rows, alt.get("rows") or [])
    main_idx = {id(o): j for j, o in enumerate(orig)}      # 全部の行の番号 → 本体の行の番号(noSub の時間の行は無い)
    ns_cands = 0
    doc_t = num(doc.get("updatedAt")) or 0
    groups = [Group(S, orig, segs, go, ge) for go, ge in S._groups(orig, segs)]
    grp_of = {k: gi for gi, g in enumerate(groups) for k in g.go}

    def group_time(g):
        ts = [num(segs[i].get("proofedAt")) or doc_t for i in g.ge]
        return max(ts) if g.proofed and ts else doc_t
    in_time = [C.in_period(group_time(g), since_ms, until_ms) for g in groups]   # まとまりが時期の中か(候補ごとに数え直さない)
    out = {"cands": [], "fixes": [], "stats": dict(stats), "outOfRange": 0, "inRange": False, "noSub": {"rows": len(ns_segs), "candidates": 0}}
    by_group = {}   # まとまり -> [(a, b, 判定)]
    named = {}      # まとまり -> 名簿の呼び名があるか(人の最終。無ければ機械の文字)

    def group_named(gi):
        if has_name is None:
            return False
        if gi not in named:
            g = groups[gi]
            named[gi] = has_name(g.final_text or g.orig_text)
        return named[gi]
    for cand in cands:
        k = main_idx.get(id(orig_all[int(cand["seg"][1:])]))
        if k is None:
            ns_cands += 1
            continue
        gi = grp_of.get(k)
        if gi is None:
            continue
        g = groups[gi]
        if not in_time[gi]:
            out["outOfRange"] += 1
            continue
        out["inRange"] = True
        status, why, span = judge_candidate(S, g, k, cand)
        out["cands"].append({"status": status, "why": why, "wrong": cand["wrong"], "right": cand["right"], "row": k, "i": cand["i"], "name": group_named(gi)})
        if span:
            by_group.setdefault(gi, []).append((span[0], span[1], status))
    out["noSub"]["candidates"] = ns_cands
    # 人の直しのうち、候補が同じ所に出ていたもの(機械の行も人の行もある・校正済み・長すぎないまとまりだけ)
    for gi, g in enumerate(groups):
        if not (g.go and g.ge and g.proofed) or g.too_long() or not in_time[gi]:
            continue
        out["inRange"] = True
        fo, _po, fh, ops = g.ops()
        for tag, i1, i2, j1, j2 in ops:
            if tag == "equal":
                continue
            hits = [st for a, b, st in by_group.get(gi, []) if (a < i2 and i1 < b) or (i1 == i2 and a <= i1 <= b)]
            out["fixes"].append({"short": (i2 - i1) <= S.ALT_MAX_CHARS and (j2 - j1) <= S.ALT_MAX_CHARS,
                                 "covered": bool(hits), "hit": "hit" in hits, "name": group_named(gi)})
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
        self.names = {"hit": 0, "miss": 0, "other": 0, "unknown": 0, "fixes": 0, "covered": 0, "coveredHit": 0}   # 名簿の呼び名がある所だけ

    def add(self, r):
        self.docs += 1
        for c in r["cands"]:
            self.cands += 1
            self.status[c["status"]] += 1
            if c["status"] == "unknown":
                self.why[c["why"]] = self.why.get(c["why"], 0) + 1
            if c.get("name"):
                self.names[c["status"]] += 1
        for k, v in r["stats"].items():   # yt は切り抜きの境目 clipEdge も
            self.stats[k] = self.stats.get(k, 0) + v
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
            if x.get("name"):
                self.names["fixes"] += 1
                self.names["covered"] += x["covered"]
                self.names["coveredHit"] += x["hit"]
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
                "skipped": dict(self.stats), "noSub": dict(self.nosub), "names": self.names_result()}

    def names_result(self):
        n = self.names
        judged = n["hit"] + n["miss"] + n["other"]
        return dict(n, candidates=judged + n["unknown"], judged=judged, hitRate=rate(n["hit"], judged),
                    coveredRate=rate(n["covered"], n["fixes"]), hitRateOfCovered=rate(n["coveredHit"], n["covered"]))


def engine_key(alt):
    return "%s / %s" % (alt.get("engine") or "?", alt.get("model") or "?")


# ---------------------------------------------------------------- 全体

def evaluate(data_dir=None, since=None, until=None, source="alt", include_eval=False):
    """source = alt(既定。今までと同じ結果)・yt・both(alt と yt を別々に + 2 つが同じ候補を出した所 agree)"""
    if source not in SOURCES:
        raise SystemExit("--source は %s のどれかです: %r" % ("・".join(SOURCES), source))
    root = locate(data_dir)       # serve.py を読み込む前に決める(読み込むと TRANSCRIBE_DATA_DIR が一時フォルダになる)
    S = get_serve()
    if source != "both":
        res = evaluate_one(S, root, source, since, until, include_eval)
        res.pop("_per")
        return res
    a = evaluate_one(S, root, "alt", since, until, include_eval)
    y = evaluate_one(S, root, "yt", since, until, include_eval)
    agree = Agg()
    for tid in sorted(set(a["_per"]) & set(y["_per"])):
        keys = {(c["row"], c["i"], c["wrong"], c["right"]) for c in y["_per"][tid]["cands"]}
        agree.add({"cands": [c for c in a["_per"][tid]["cands"] if (c["row"], c["i"], c["wrong"], c["right"]) in keys], "fixes": [], "stats": {}})
    a.pop("_per")
    y.pop("_per")
    meta = {"schema": SCHEMA, "source": "both", "at": int(time.time() * 1000), "since": since, "until": until, "includeEval": include_eval, "git": C.git_rev(), "dataDir": root}
    return {"meta": meta, "alt": a, "yt": y, "agree": agree.result()}


def evaluate_one(S, root, source, since=None, until=None, include_eval=False):
    """1 つの出どころ(alt / yt)の測定。結果の _per = 文書ごとの judge_doc の結果(both の一致に使う。evaluate が外す)"""
    tdir = os.path.join(root, "transcripts")
    since_ms, until_ms = C.period(since, until)
    total, by_engine, by_doc, per = Agg(), {}, [], {}
    skipped = {"evalSet": 0, "noOriginal": 0, "broken": 0, "outOfRange": 0}
    if source == "yt":
        skipped.update(noClip=0, noCaptions=0)
    has_name = name_checker(S)
    no_alt = out_cands = 0
    for tid in docloc.iter_tids(root):   # 案件の 作業用 に置いた文書も(索引があれば)
        if source == "alt" and not os.path.isfile(docloc.doc_file(tid, ".alt.json", root)):
            no_alt += 1
            continue
        doc = read_json(docloc.doc_file(tid, ".json", root), None, MAX_DOC_BYTES)
        alt = read_alt(S, tdir, tid) if source == "alt" else None
        if not isinstance(doc, dict) or (source == "alt" and alt is None):
            skipped["broken"] += 1
            continue
        if source == "alt":
            key, diff_fn = engine_key(alt), None
        else:   # yt: 文書の clip の配信の、保存してある字幕(通信しない)
            try:
                vid = S.ytcap_doc_range(doc)["videoId"]
            except S.ApiError:
                skipped["noClip"] += 1
                continue
            cache = read_ytcache(S, root, vid)
            if cache is None:
                no_alt += 1
                continue
            if cache["kind"] == "none":
                skipped["noCaptions"] += 1
                continue
            alt = {"rows": S.ytcap_doc_rows(doc, cache)[0]}
            key, diff_fn = "youtube / %s" % cache["kind"], S.ytcap_diffs
        if doc.get("evalSet") is True and not include_eval:
            skipped["evalSet"] += 1
            continue
        if not isinstance(doc.get("original"), list) or not doc["original"] or not isinstance(doc.get("segments"), list):
            skipped["noOriginal"] += 1
            continue
        r = judge_doc(S, doc, alt, since_ms, until_ms, diff_fn, has_name)
        out_cands += r["outOfRange"]
        if not r["inRange"]:
            skipped["outOfRange"] += 1
            continue
        per[tid] = r
        total.add(r)
        by_engine.setdefault(key, Agg()).add(r)
        one = Agg()
        one.add(r)
        o = one.result()
        by_doc.append({"id": tid, "title": str(doc.get("title") or "")[:40], "engine": key, "candidates": o["candidates"], "judged": o["judged"], "hit": o["hit"],
                       "miss": o["miss"], "other": o["other"], "unknown": o["unknown"], "hitRate": o["hitRate"]})
    res = total.result()
    few = res["judged"] < FEW_CANDS
    fb = read_feedback(S, root, source)
    notes = []
    if skipped["noOriginal"]:
        notes.append("機械の最初の出力(original)が無い文書が %d 件あります(測っていません)" % skipped["noOriginal"])
    if skipped["evalSet"]:
        notes.append(("評価用なのに alt.json がある文書が %d 件あります(測っていません)" if source == "alt" else
                      "評価用の文書 %d 件は測っていません(--include-eval で測れます。読むだけ)") % skipped["evalSet"])
    if source == "yt":
        notes.append("YouTube の字幕は、道具からは取りません(画面の「字幕を取って比べる」で保存した ytcaps/ だけ)。保存が無い文書 %d 件・元の配信が分からない文書 %d 件・字幕が無い配信の文書 %d 件"
                     % (no_alt, skipped["noClip"], skipped["noCaptions"]))
    if skipped["broken"]:
        notes.append("読めない文書・alt.json が %d 件あります" % skipped["broken"])
    if since or until:
        notes.append("採否の記録(採用・却下の数)は時期で絞れません(記録に時刻が無い)")
    notes.append("人は候補につられる(迷うと直さずに通す)ので、外れ・別の直しは少なめ(当たりは甘め)に出ます。校正済みでないまとまりは「分からない」にして率に入れていません")
    notes.append("機械の最初の出力(original)は、再認識のあとは再認識後のものです")
    meta = {"schema": SCHEMA, "source": source, "at": int(time.time() * 1000), "since": since, "until": until, "includeEval": include_eval, "git": C.git_rev(), "dataDir": root,
            "docs": total.docs, "noAlt" if source == "alt" else "noYt": no_alt, "candidates": res["candidates"], "judged": res["judged"], "few": few,
            "fewNote": "まだ少ない(参考): 判定できた候補が %d 件(%d 件未満)。これでエンジンや既定を決めない" % (res["judged"], FEW_CANDS) if few and total.docs else "",
            "skipped": skipped, "outOfRangeCandidates": out_cands, "notes": notes}
    feedback = None
    if fb:
        feedback = {"accepted": fb["acc"], "rejected": fb["rej"], "acceptRate": rate(fb["acc"], fb["acc"] + fb["rej"])}
    return {"meta": meta, "feedback": feedback, "total": res,
            "byEngine": {k: v.result() for k, v in sorted(by_engine.items())}, "byDoc": by_doc, "_per": per}


# ---------------------------------------------------------------- 表示・保存

def print_agg(title, r, indent="  "):
    print("%s[%s]  文書 %d 件・候補 %d 件(判定できた %d 件)" % (indent, title, r["docs"], r["candidates"], r["judged"]))
    if not r["candidates"]:
        return
    print("%s  当たり %d(%s)・外れ(人はそのまま)%d(%s)・別の直し %d(%s)  分からない %d%s"
          % (indent, r["hit"], pct(r["hitRate"]), r["miss"], pct(r["missRate"]), r["other"], pct(r["otherRate"]), r["unknown"],
             "(" + "・".join("%s %d" % (UNKNOWN_LABELS.get(k, k), n) for k, n in r["unknownWhy"].items()) + ")" if r["unknownWhy"] else ""))
    p = r["pickup"]
    if p["fixes"]:
        print("%s  拾えた率: 人の直し %d か所のうち、候補が同じ所に出ていた %d(%s)・そのうち当たり %d(%s)   短い直し(12 字以下)だけ: %d か所 → 候補あり %d(%s)・当たり %d(%s)"
              % (indent, p["fixes"], p["covered"], pct(p["coveredRate"]), p["coveredHit"], pct(p["hitRateOfCovered"]),
                 p["shortFixes"], p["shortCovered"], pct(p["shortCoveredRate"]), p["shortHit"], pct(p["shortHitRateOfCovered"])))
    ns = r.get("noSub") or {}
    if ns.get("rows"):
        print("%s  字幕に出さない(noSub)の行 %d(文書 %d 件)・その時間に出ていた候補 %d 件は数に入れていません" % (indent, ns["rows"], ns["docs"], ns["candidates"]))
    nm = r.get("names") or {}
    if nm.get("candidates") or nm.get("fixes"):
        print("%s  名簿の呼び名がある所: 候補 %d(判定 %d)当たり %d(%s)・外れ %d・別の直し %d   人の直し %d か所 → 候補あり %d(%s)・当たり %d"
              % (indent, nm["candidates"], nm["judged"], nm["hit"], pct(nm["hitRate"]), nm["miss"], nm["other"],
                 nm["fixes"], nm["covered"], pct(nm["coveredRate"]), nm["coveredHit"]))
    sk = r["skipped"]
    print("%s  出さなかった数: %s" % (indent, "・".join("%s %d" % (STAT_LABELS.get(k, k), n) for k, n in sk.items())))


def print_report(res):
    m = res["meta"]
    if m.get("source") == "both":
        for k in ("alt", "yt"):
            print_report(res[k])
            print()
        a = res["agree"]
        print("[2 つが同じ候補を出した所(alt と yt の一致。両方がある文書 %d 件)]" % a["docs"])
        print_agg("一致", a)
        return
    src = m.get("source") or "alt"
    tag = "「別」" if src == "alt" else "「YT」"
    rng = C.period_label(m["since"], m["until"])
    print("%sの当たり率の測定(%s)  文書 %d 件・候補 %d 件(判定できた %d 件)  作業データ: %s" % (SOURCE_LABELS[src], rng, m["docs"], m["candidates"], m["judged"], m["dataDir"]))
    fb = res["feedback"]
    if fb:
        print("採否の記録(画面で%sの候補を採用・却下した数): 採用 %d・却下 %d  採用率 %s" % (tag, fb["accepted"], fb["rejected"], pct(fb["acceptRate"])))
    else:
        print("採否の記録(画面で%sの候補を採用・却下した数): まだありません" % tag)
    if m["fewNote"]:
        print("★ " + m["fewNote"])
    if not m["docs"]:
        if src == "alt":
            print("(対象なし: 評価用でない文書で、2つ目のエンジンで聞いた結果(alt.json)がある文書がありません。alt.json なしの文書 %d 件)" % m["noAlt"])
        else:
            print("(対象なし: 元の配信の YouTube の字幕を保存してある文書がありません。保存なしの文書 %d 件)" % m["noYt"])
    else:
        print_agg("全部", res["total"])
        if len(res["byEngine"]) > 0:
            print("\n  [2つ目のエンジンごと]" if src == "alt" else "\n  [字幕の種類ごと(auto = 自動字幕・manual = 配信者の字幕)]")
            for k, r in res["byEngine"].items():
                print_agg(k, r, "   ")
        print("\n  [文書ごと(当たり率が低い順に10件)]")
        for d in sorted(res["byDoc"], key=lambda d: (d["hitRate"] if d["hitRate"] is not None else 2, d["id"]))[:10]:
            print("    %s %-34s 候補 %3d・判定 %3d  当たり %3d・外れ %3d・別の直し %3d・分からない %3d  当たり率 %s  %s"
                  % (d["id"], d["engine"], d["candidates"], d["judged"], d["hit"], d["miss"], d["other"], d["unknown"], pct(d["hitRate"]), d["title"]))
    for n in m["notes"]:
        print("注意: " + n)


def main(argv=None):
    p = argparse.ArgumentParser(description="2つ目のエンジンとの食い違いの候補の当たり率を、人の最終で測る(作業データは読むだけ)")
    C.add_period_args(p, "この日(YYYY-MM-DD)以後だけ(まとまりの時刻 = 人の行の proofedAt の最大、無ければ文書の更新時刻)",
                      json_help="同じ形の JSON を 文字起こしの作業データの evals/alt/<日時>.json に残す")
    p.add_argument("--source", choices=SOURCES, default="alt", help="候補の出どころ: alt(既定。2つ目のエンジン)・yt(元の配信の YouTube の字幕。保存してある ytcaps/ だけ・通信しない)・both")
    p.add_argument("--include-eval", action="store_true", help="評価用の文書も測る(読むだけ)")
    args = p.parse_args(argv)
    res = evaluate(args.data_dir, args.since, args.until, args.source, args.include_eval)
    print_report(res)
    C.report_saved(res, args.json, res["meta"]["dataDir"], "alt")
    return res


if __name__ == "__main__":
    C.utf8_stdout()
    main()
