#!/usr/bin/env python3
"""行の時刻(字幕の区間)を、行の時刻の原則(docs/spec/row-timing-policy.md)の数字で測る道具(plan/line-b-row-timing.md の 7-4)。

    python src/eval/tools/eval_timing.py [--since YYYY-MM-DD] [--until YYYY-MM-DD] [--json] [--out 結果.json] [--data-dir 作業データの親フォルダ] [--apply]

- 作業データは**読むだけ**(transcribe の transcripts/<id>.json と、--apply のときの <id>.asr.json)。何も書き換えない。--json のときだけ、結果を
  文字起こしの作業データの evals/timing/<日時>.json(schema youtube-tools-timing-eval/v1)に残す(置き場所は eval_effort.py・eval_cut.py と同じ規則)。
  --out を付けたら、作業データではなくそのファイルに書く。
- 正解 = 確かめ済みの評価用の文書(evalSet と evalReviewed。eval_asr.is_reviewed = src/eval/drill/drill.py の drill_is_reviewed と同じ条件)の、
  校正済み(proofed)で文字のある人の行。機械の行 = 文書の original(保存してある機械の出力 = 今の original を作った認識の結果)。
  人の行ごとに、時刻がいちばん長く重なる機械の行を選び、頭の MATCH_CHARS 文字か末の MATCH_CHARS 文字(NFKC にして文字と数字だけ)が合うときだけ数える
  (= 文字が合う行)。人が文字を大きく直した行・機械が別の言葉にした行は、同じ発言かが分からないので時刻を比べない(数は unmatched)
- 数字(原則の文書の「測り方」と同じ。余裕 TOL = 0.1 秒。割合は文字が合う行に対して):
    ①頭 head = 発言の頭が切れる: 機械の始まり > 人の始まり + 0.1
    ①末 tail = 発言の末が切れる: 機械の終わり < 人の終わり − 0.1
    ②前 prev = 前の発言が入る:   機械の始まり < 前の人の行の終わり − 0.1
    ②次 next = 次の発言が入る:   機械の終わり > 次の人の行の始まり + 0.1
          (前・次の人の行 = 文字のある人の行を時刻の順に並べたときの隣。校正済みでなくてよい。無ければ「入らない」)
    ③ extra  = 喋っていない時間: 人の区間の外へはみ出した秒(前のはみ出し + 後ろのはみ出し)の中央値・平均
  2026-10-07 の試算(plan/line-b-row-timing.md の 7 の表の「今」= 確かめ済み 22 本・文字が合う 255 行)と同じ尺度
- 組: 全体・文書ごと・最初の認識(recognition.runs の kind の無い記録 = 今の original を作った認識。eval_asr.draft_run)の engine・model と
  行の後処理の記録 post(編集 0.57.1 から。{version, endTrim, joinGap}。0.64.0 までは pullEnds・retime も(0.65.0 で部品ごと消した。古い記録の鍵は読んで見出しに出す)。
  無い記録は「後処理の記録なし(0.57.0 まで)」・1 秒丸めの配り直しの記録 retimed(0.64.0 まで)があればそう書く)
- 行の境目の一致率(I-5 字幕の分け方。2026-10-08。plan/line-b-row-split.md): 人の行と機械の行の境目を文字の位置で突き合わせ、的中(機械の境目のうち人も境目にした割合)と
  再現(人の境目のうち機械にもあった割合)。人の境目は両側が校正済みで話者が同じ所だけ(boundary_agreement)。全体・組ごと・文書ごと・--apply の当て直しにも出す
- --apply: 保存してある生出力 <id>.asr.json(分ける前の認識の行と単語)に、行の後処理を当て直したときの数字も出す(VARIANTS: 0.57.0 の後処理 /
  7-1 だけ / 0.57.1 / 0.59.5 = 0.57.1 + 行を分ける文字数 40 / 0.59.6 = 24(splitChars は spec に入れる))。後処理は editor の ed_jobs.expand_segments をそのまま使う(eval_asr.load_serve。serve の作業データは一時の置き場で、最後に消す)。
  音声を聞き直す 1 秒丸めの配り直し(quant_retime。編集 0.65.0 で消した)はかけない(音声を聞き直さない = 認識し直さない)。
  「0.57.0 の後処理」を当て直した行が保存してある original と同じか(reproduced。始まり・終わりが REPRO_TOL 以内の行の割合)も出す
  (低い文書は、original を作ったときの後処理がそれと違う = 0.53.1 より前の文書・配り直しのあった文書・人が分け直した文書)
- --since / --until は機械の出力を作った時刻(最初の認識の at。無ければ updatedAt)で絞る(until はその日を含む)。文字が合う行が FEW_ROWS 未満なら「まだ少ない(参考)」
"""
import argparse
import difflib
import os
import re
import statistics
import sys
import time
import unicodedata

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.dirname(os.path.dirname(HERE))   # tools -> eval -> src
if not __package__:   # スクリプトとして起動したとき(py -3.10 src/eval/tools/eval_timing.py)だけ。src を先頭に・この道具のフォルダは外す(兄弟は絶対 import で読む。見本 pipeline/transcribe/worker.py)
    sys.path[:] = [SRC] + [p for p in sys.path if os.path.normcase(os.path.abspath(p or os.curdir)) not in (os.path.normcase(HERE), os.path.normcase(SRC))]
from eval.tools import _evalcommon as C  # noqa: E402  共通の部品(作業データの場所・時期・率・git の rev・保存。src を sys.path に足す)
from eval.tools._evalcommon import rate, read_json  # noqa: E402
from ytt.schemas import num  # noqa: E402  有限の数(bool は除く)なら float、それ以外は None
from eval.tools import eval_asr  # noqa: E402  確かめ済みの条件(is_reviewed)・最初の認識(draft_run)・後処理を当て直す editor の読み込み(load_serve)は eval_asr.py と同じ

SCHEMA = "youtube-tools-timing-eval/v1"
ASR_SCHEMA = "youtube-tools-asr-raw/v1"   # src/pipeline/transcribe/records.py の ASR_SCHEMA(editor は --apply のときだけ読み込む)
TOL = 0.1                      # 原則の測り方の余裕(秒)
EPS = 1e-6                     # 浮動小数の誤差(0.1 秒ちょうどのずれは数えない)
MATCH_CHARS = 3                # 「文字が合う」= 頭か末のこの文字数が同じ
FEW_ROWS = 100                 # 文字が合う行がこれより少ないときは「まだ少ない(参考)」
REPRO_TOL = 0.011              # --apply の reproduced: 当て直した行と original の行の端がこの秒以内なら同じ(行の時刻は 0.01 秒で保存)
MAX_BYTES = C.DOC_BYTES
DOC_RE = re.compile(r"^[0-9a-f]{12}\.json\Z")
KEYS = (("head", "①頭"), ("tail", "①末"), ("prev", "②前"), ("next", "②次"))
POST_NONE = "後処理の記録なし(0.57.0 まで)"
# --apply で当て直す後処理(editor の ed_jobs の値を一時的に差し替える)。0.57.1 の既定 = END_TRIM 0・JOIN_GAP 0.5
VARIANTS = (("v0570", "0.57.0 の後処理(END_TRIM 0.1 秒・つながない)", {"END_TRIM": 0.1, "JOIN_GAP": 0.0}),
            ("trim0", "7-1 だけ(END_TRIM 0・つながない)", {"END_TRIM": 0.0, "JOIN_GAP": 0.0}),
            ("v0571", "0.57.1 の後処理(END_TRIM 0・すき間 0.5 秒以下をつなぐ)", {"END_TRIM": 0.0, "JOIN_GAP": 0.5}),
            ("split40", "0.59.5(0.57.1 の後処理 + 行を分ける文字数 40)", {"END_TRIM": 0.0, "JOIN_GAP": 0.5, "splitChars": 40}),   # splitChars は spec に入れる(ed_jobs の値ではない)
            ("split24", "0.59.6(0.57.1 の後処理 + 行を分ける文字数 24 = 今の既定)", {"END_TRIM": 0.0, "JOIN_GAP": 0.5, "splitChars": 24}))


# ---------------------------------------------------------------- 読み込み(読むだけ)

def letters(text):
    """比べる文字: NFKC にして、文字と数字だけ(記号・空白・句読点・_ を除く)"""
    return re.sub(r"[^\w]", "", unicodedata.normalize("NFKC", str(text or ""))).replace("_", "")


def text_rows(items):
    """文字のある行(start・end が数)を時刻の順に -> [dict(元の行 + "start"・"end" を float に)]"""
    out = []
    for g in items or []:
        if not isinstance(g, dict):
            continue
        a, b = num(g.get("start")), num(g.get("end"))
        if a is None or b is None or not letters(g.get("text")):
            continue
        out.append(dict(g, start=a, end=b))
    return sorted(out, key=lambda g: (g["start"], g["end"]))


# ---------------------------------------------------------------- 1つの文書(純粋な関数)

def text_match(a, b, k=MATCH_CHARS):
    """文字が合うか: 頭の k 文字か末の k 文字が同じ(どちらかが空なら合わない)"""
    la, lb = letters(a), letters(b)
    return bool(la and lb) and (la[:k] == lb[:k] or la[-k:] == lb[-k:])


def best_overlap(h, machine):
    """人の行 h といちばん長く重なる機械の行(重なりが 0 以下なら None)"""
    best, bo = None, 0.0
    for r in machine:
        ov = min(h["end"], r["end"]) - max(h["start"], r["start"])
        if ov > bo:
            best, bo = r, ov
    return best


def measure_rows(human, machine):
    """human = 文字のある人の行(時刻の順。proofed を見る)・machine = 文字のある機械の行(時刻の順)
    -> {"proofed": 校正済みの行の数, "rows": [文字が合う行ごとの判定 {"head", "tail", "prev", "next", "extra", "dStart", "dEnd"}]}"""
    out, proofed = [], 0
    for i, h in enumerate(human):
        if h.get("proofed") is not True:
            continue
        proofed += 1
        m = best_overlap(h, machine)
        if m is None or not text_match(h.get("text"), m.get("text")):
            continue
        prev_end = human[i - 1]["end"] if i > 0 else None
        next_start = human[i + 1]["start"] if i + 1 < len(human) else None
        out.append({"head": m["start"] > h["start"] + TOL + EPS,
                    "tail": m["end"] < h["end"] - TOL - EPS,
                    "prev": prev_end is not None and m["start"] < prev_end - TOL - EPS,
                    "next": next_start is not None and m["end"] > next_start + TOL + EPS,
                    "extra": round(max(0.0, h["start"] - m["start"]) + max(0.0, m["end"] - h["end"]), 3),
                    "dStart": round(m["start"] - h["start"], 3), "dEnd": round(m["end"] - h["end"], 3)})
    return {"proofed": proofed, "rows": out}


# ---------------------------------------------------------------- 行の境目の一致率(I-5 字幕の分け方。2026-10-08。plan/line-b-row-split.md)

def _pos_map(src, dst):
    """src の文字の位置 p -> dst の文字の位置(difflib の一致ブロックで写す。一致の中なら正確、外なら近い方のブロックの端)"""
    blocks = [b for b in difflib.SequenceMatcher(None, src, dst, autojunk=False).get_matching_blocks() if b.size > 0]

    def f(p):
        prev = None
        for b in blocks:
            if b.a <= p <= b.a + b.size:
                return b.b + (p - b.a)
            if b.a > p:
                if prev is None:
                    return b.b
                return prev.b + prev.size if p - (prev.a + prev.size) <= b.a - p else b.b
            prev = b
        return prev.b + prev.size if prev else 0
    return f


def boundary_agreement(human, machine):
    """行の境目の一致(人の行と機械の行を、文字(letters)を並べた位置で突き合わせる)。
    -> {"machine": 数えた機械の境目, "human": 数えた人の境目, "hit": 人も境目にした機械の境目, "rec": 機械も境目にした人の境目}
    人の境目 = 両側が校正済みで話者が同じ所(話者が変わる所は判別が決めるので数えない)。機械の境目のうち、人の「数えない境目」の位置に当たるものも数えない。
    的中 = hit / machine・再現 = rec / human(数えた境目が 0 なら None)"""
    hs = "".join(letters(r.get("text")) for r in human)
    ms = "".join(letters(r.get("text")) for r in machine)
    to_m = _pos_map(hs, ms)
    eligible, excluded, pos = set(), set(), 0
    for a, b in zip(human, human[1:]):
        pos += len(letters(a.get("text")))
        q = to_m(pos)
        if a.get("proofed") is True and b.get("proofed") is True and (a.get("speaker") or "") == (b.get("speaker") or ""):
            eligible.add(q)
        else:
            excluded.add(q)
    mpos, pos = set(), 0
    for r in machine[:-1]:
        pos += len(letters(r.get("text")))
        mpos.add(pos)
    counted = [q for q in mpos if q not in excluded or q in eligible]
    return {"machine": len(counted), "human": len(eligible), "hit": sum(1 for q in counted if q in eligible), "rec": sum(1 for q in eligible if q in mpos)}


def boundary_sum(items):
    """文書ごとの boundary を足して 的中・再現 を付ける"""
    out = {k: sum(int(b.get(k) or 0) for b in items) for k in ("machine", "human", "hit", "rec")}
    out["precision"] = rate(out["hit"], out["machine"])
    out["recall"] = rate(out["rec"], out["human"])
    return out


def summarize(rows):
    """文字が合う行の判定の一覧 -> {"n", "head", "tail", "prev", "next"(割合), "counts", "extraMedian", "extraMean"}"""
    n = len(rows)
    counts = {k: sum(1 for r in rows if r[k]) for k, _ in KEYS}
    ex = [r["extra"] for r in rows]
    out = {"n": n, "counts": counts, "extraMedian": round(statistics.median(ex), 3) if ex else None, "extraMean": round(sum(ex) / n, 3) if n else None}
    out.update({k: rate(counts[k], n) for k, _ in KEYS})
    return out


def post_label(run):
    """最初の認識の記録の行の後処理(post)の見出し。記録の無い認識は POST_NONE(配り直しの記録 retimed があればそう足す)。
    pullEnds・retime・retimed は編集 0.64.0 までの記録だけにある(0.65.0 で部品ごと消した = 読むだけ)"""
    if not isinstance(run, dict):
        return POST_NONE
    p = run.get("post")
    if not isinstance(p, dict):
        return POST_NONE + ("・配り直しあり" if run.get("retimed") else "")
    parts = ["後処理"]
    if p.get("version"):
        parts.append("v%s" % p["version"])
    parts.append("endTrim=%s" % p.get("endTrim"))
    parts.append("join=%s" % p.get("joinGap"))
    if p.get("pullEnds"):
        parts.append("pullEnds")
    if "retime" in p:   # 0.57.1〜0.64.0 の記録だけ(0.65.0 から書かない)
        parts.append("配り直し=%s" % (p.get("retime") or "なし"))
    return " ".join(parts)


def engine_label(run):
    if not isinstance(run, dict) or not (run.get("engine") or run.get("model")):
        return eval_asr.DRAFT_NONE
    return " ".join(str(x) for x in (run.get("engine"), run.get("model")) if x)


def doc_record(doc):
    """確かめ済みの文書 1 件 -> (記録 or None, 飛ばした理由 or "")。記録には集計に使う判定の一覧 "_rows" を付ける(結果には出さない)"""
    machine = text_rows(doc.get("original"))
    if not machine:
        return None, "noOriginal"
    human = text_rows(doc.get("segments"))
    run = eval_asr.draft_run(doc)
    at = next((int(v) for v in (num(run.get("at")) if isinstance(run, dict) else None, num(doc.get("updatedAt"))) if v), None)
    m = measure_rows(human, machine)
    eng, post = engine_label(run), post_label(run)
    rec = {"id": str(doc.get("id") or ""), "title": str(doc.get("title") or "")[:40], "engine": eng, "post": post, "group": "%s | %s" % (eng, post),
           "at": at, "proofed": m["proofed"], "unmatched": m["proofed"] - len(m["rows"]), **summarize(m["rows"]), "_rows": m["rows"],
           "boundary": boundary_agreement(human, machine)}
    return rec, ""


# ---------------------------------------------------------------- --apply(保存してある生出力に後処理を当て直す)

def asr_raw(doc, asr):
    """生出力(<id>.asr.json の中身)-> (分ける前の行 [行の秒 = 文書の範囲の先頭が 0], 後処理の spec, 音声の秒, 範囲の先頭の秒) か None(使えない)。
    生出力の時刻は元の動画の秒(capture_raw が範囲の先頭を足している)なので、行の秒に戻して run_job と同じ形で後処理に渡す"""
    if not isinstance(asr, dict) or asr.get("schema") != ASR_SCHEMA or not isinstance(asr.get("segments"), list):
        return None
    run = asr.get("run") if isinstance(asr.get("run"), dict) else {}
    params = doc.get("params") if isinstance(doc.get("params"), dict) else {}
    start = num(doc.get("start")) or 0.0
    raw = []
    for s in asr["segments"]:
        if not isinstance(s, dict) or num(s.get("start")) is None or num(s.get("end")) is None:
            continue
        ws = [(float(w[0]) - start, float(w[1]) - start, str(w[2])) for w in s.get("words") or []
              if isinstance(w, (list, tuple)) and len(w) >= 3 and num(w[0]) is not None and num(w[1]) is not None]
        raw.append({"start": float(s["start"]) - start, "end": float(s["end"]) - start, "text": str(s.get("text") or ""), "words": ws})
    eng = str(run.get("engine") or "")
    spec = {"wordSplit": params.get("wordSplit", True) is not False, "stripPunct": params.get("stripPunct", True) is not False, "engine": eng}
    if num(params.get("splitChars")):
        spec["splitChars"] = int(params["splitChars"])
    dur = num(run.get("audioSec")) or None
    return raw, spec, dur, start


def reapply(S, raw, spec, dur, start):
    """後処理(S.expand_segments)を当て直した機械の行(元の動画の秒・文字のある行だけ)"""
    return [{"start": round(s["start"] + start, 2), "end": round(s["end"] + start, 2), "text": s["text"]}
            for s in S.expand_segments([dict(r) for r in raw], spec, dur) if s.get("text")]


def reproduced(rows, original):
    """当て直した行のうち、original に始まり・終わりとも REPRO_TOL 以内で同じ行がある割合(original の行に対して)"""
    orig = text_rows(original)
    if not orig:
        return None
    have = [(r["start"], r["end"]) for r in rows]
    same = sum(1 for o in orig if any(abs(o["start"] - a) <= REPRO_TOL and abs(o["end"] - b) <= REPRO_TOL for a, b in have))
    return rate(same, len(orig))


def apply_variants(docs, tdir, S=None):
    """--apply: 文書ごとに生出力へ VARIANTS の後処理を当て直して測る。S = 読み込んだ serve(テストで渡す。無ければ eval_asr.load_serve("fake"))
    -> {"variants": [{"key", "label", "settings", "overall", "byDoc": [{"id", "n", "head"…, "reproduced"?}]}], "docs", "skipped": {"noAsr", "badAsr"}}"""
    S = S or eval_asr.load_serve("fake")
    # 値は持ち主の部品(pipeline/transcribe/postproc)に直接入れる(load_serve は serve を登録して読むので S.名前 = … でも届くが、登録せずに読んだ serve を渡されても効くように)。
    # "splitChars" だけは postproc の値ではなく後処理の spec に入れる(行を分ける文字数。0.59.5)
    from pipeline.transcribe import postproc as J  # noqa: E402
    saved = {k: getattr(J, k) for _key, _label, st in VARIANTS for k in st if k != "splitChars"}
    res = {"variants": [{"key": key, "label": label, "settings": dict(st), "rows": [], "bnd": [], "byDoc": []} for key, label, st in VARIANTS],
           "docs": 0, "skipped": {"noAsr": 0, "badAsr": 0}}
    try:
        for doc in docs:
            tid = str(doc.get("id") or "")
            asr = read_json(os.path.join(tdir, tid + ".asr.json"), None, MAX_BYTES)
            if asr is None:
                res["skipped"]["noAsr"] += 1
                continue
            got = asr_raw(doc, asr)
            if got is None:
                res["skipped"]["badAsr"] += 1
                continue
            raw, spec, dur, start = got
            human = text_rows(doc.get("segments"))
            res["docs"] += 1
            for v, (key, _label, st) in zip(res["variants"], VARIANTS):
                for k, val in st.items():
                    if k != "splitChars":
                        setattr(J, k, val)
                rows = reapply(S, raw, dict(spec, splitChars=st["splitChars"]) if "splitChars" in st else spec, dur, start)
                mrows = text_rows(rows)
                m = measure_rows(human, mrows)
                v["rows"] += m["rows"]
                b = boundary_agreement(human, mrows)
                v["bnd"].append(b)
                d = {"id": tid, **summarize(m["rows"]), "boundary": b}
                d.pop("counts", None)
                if key == "v0570":
                    d["reproduced"] = reproduced(rows, doc.get("original"))
                v["byDoc"].append(d)
    finally:
        for k, val in saved.items():
            setattr(J, k, val)
    for v in res["variants"]:
        v["overall"] = summarize(v.pop("rows"))
        v["boundary"] = boundary_sum(v.pop("bnd"))
    return res


# ---------------------------------------------------------------- 全体

def evaluate(data_dir=None, since=None, until=None, apply=False, serve=None):
    root = C.locate("transcribe", data_dir)
    tdir = os.path.join(root, "transcripts")
    since_ms, until_ms = C.period(since, until)
    skipped = {"broken": 0, "notReviewed": 0, "noOriginal": 0, "outOfRange": 0}
    recs, docs = [], []
    for name in sorted(os.listdir(tdir)) if os.path.isdir(tdir) else []:
        if not DOC_RE.match(name):
            continue
        doc = read_json(os.path.join(tdir, name), None, MAX_BYTES)
        if not isinstance(doc, dict):
            skipped["broken"] += 1
            continue
        if not eval_asr.is_reviewed(doc):
            skipped["notReviewed"] += 1
            continue
        rec, why = doc_record(doc)
        if rec is None:
            skipped[why] += 1
            continue
        if not C.in_period(rec["at"], since_ms, until_ms, unknown=False):   # 時期を指定したときは、時刻の分からない文書も外す
            skipped["outOfRange"] += 1
            continue
        recs.append(rec)
        docs.append(doc)
    rows = [r for rec in recs for r in rec["_rows"]]
    overall = summarize(rows)
    overall["boundary"] = boundary_sum([rec["boundary"] for rec in recs])
    by = {}
    for rec in recs:
        by.setdefault(rec["group"], []).append(rec)
    groups = [dict(summarize([r for rec in rs for r in rec["_rows"]]), key=k, docs=len(rs), boundary=boundary_sum([rec["boundary"] for rec in rs])) for k, rs in by.items()]
    groups.sort(key=lambda g: (-g["n"], g["key"]))
    for rec in recs:
        rec.pop("_rows", None)
    few = overall["n"] < FEW_ROWS
    meta = {"schema": SCHEMA, "at": int(time.time() * 1000), "since": since, "until": until, "git": C.git_rev(), "dataDir": root,
            "docs": len(recs), "proofedRows": sum(r["proofed"] for r in recs), "matchedRows": overall["n"],
            "unmatchedRows": sum(r["unmatched"] for r in recs), "few": few,
            "fewNote": "まだ少ない(参考): 文字が合う行が %d 行(%d 行未満)" % (overall["n"], FEW_ROWS) if few else "",
            "skipped": skipped, "tol": TOL, "matchChars": MATCH_CHARS, "apply": bool(apply)}
    res = {"meta": meta, "overall": overall, "groups": groups, "byDoc": sorted(recs, key=lambda r: r["id"])}
    if apply:
        res["apply"] = apply_variants(docs, tdir, serve)
    return res


# ---------------------------------------------------------------- 表示・保存

def pct(x):
    return "  - " if x is None else "%3.0f%%" % (x * 100)


def sec(x):
    return "  -  " if x is None else "%.2f" % x


def line(s):
    """1 行の数字(原則の 5 つ)"""
    return "%s  %s  %s  %s  ③ 中央 %s / 平均 %s 秒  (%d 行)" % tuple(
        ["%s %s" % (lb, pct(s[k])) for k, lb in KEYS] + [sec(s["extraMedian"]), sec(s["extraMean"]), s["n"]])


def bline(b):
    """行の境目の一致率の 1 行(的中 = 機械の境目のうち人も / 再現 = 人の境目のうち機械も)"""
    if not b:
        return ""
    return "境目 的中 %s(%d/%d)・再現 %s(%d/%d)" % (pct(b.get("precision")), b.get("hit", 0), b.get("machine", 0), pct(b.get("recall")), b.get("rec", 0), b.get("human", 0))


def print_report(res):
    m = res["meta"]
    rng = "%s 〜 %s" % (m["since"] or "最初", m["until"] or "今") if (m["since"] or m["until"]) else "全期間"
    print("行の時刻の原則の数字(%s)  確かめ済みの文書 %d 本・校正済み %d 行・文字が合う %d 行  作業データ: %s" % (
        rng, m["docs"], m["proofedRows"], m["matchedRows"], m["dataDir"]))
    print("  ①頭 = 頭が切れる・①末 = 末が切れる・②前 = 前の発言が入る・②次 = 次の発言が入る(どれも 0.1 秒の余裕。少ないほど良い)・③ = 人の区間の外へはみ出した秒")
    if m["fewNote"]:
        print("★ " + m["fewNote"])
    sk = m["skipped"]
    shown = {k: v for k, v in sk.items() if v and k != "notReviewed"}
    print("  確かめ済みでない文書 %d 本は数えない%s" % (sk.get("notReviewed", 0), ("・飛ばした: " + "・".join("%s %d" % kv for kv in shown.items())) if shown else ""))
    if not m["docs"]:
        print("(測れる文書がありません。評価ドリルで確かめ済みが貯まると測れます)")
        return
    print("  [全体・保存してある機械の出力]  " + line(res["overall"]))
    print("  [行の境目の一致率(I-5。人の境目 = 両側が校正済みで同じ話者)]  " + bline(res["overall"].get("boundary")))
    print("  [組ごと: 最初の認識のエンジン・モデル | 行の後処理]")
    for g in res["groups"]:
        print("    %-70s 文書 %2d 本  %s  %s" % (g["key"], g["docs"], line(g), bline(g.get("boundary"))))
    ap = res.get("apply")
    if ap:
        print("  [--apply: 保存してある生出力(asr.json)に後処理を当て直した数字。文書 %d 本(生出力が無い %d・読めない %d)。1 秒丸めの配り直しはかけない]" % (
            ap["docs"], ap["skipped"]["noAsr"], ap["skipped"]["badAsr"]))
        for v in ap["variants"]:
            print("    %-46s %s  %s" % (v["label"], line(v["overall"]), bline(v.get("boundary"))))
        rp = [d["reproduced"] for d in ap["variants"][0]["byDoc"] if d.get("reproduced") is not None]
        if rp:
            low = [d["id"] for d in ap["variants"][0]["byDoc"] if d.get("reproduced") is not None and d["reproduced"] < 0.9]
            print("    0.57.0 の後処理で保存してある original を再現できた行の割合: 中央値 %s(9 割未満の文書 %d 本%s)" % (
                pct(round(statistics.median(rp), 3)), len(low), (": " + ", ".join(low[:8])) if low else ""))
    print("  [文書ごと]")
    for r in res["byDoc"]:
        b = r.get("boundary") or {}
        print("    %s 校正済み %3d・合う %3d  %s  境目 %d/%d・%d/%d  %s" % (r["id"], r["proofed"], r["n"], line(r), b.get("hit", 0), b.get("machine", 0), b.get("rec", 0), b.get("human", 0), r["title"]))


def main(argv=None):
    p = argparse.ArgumentParser(description="行の時刻を原則(①頭・①末・②前・②次・③)の数字で測る(作業データは読むだけ)")
    C.add_period_args(p, "この日(YYYY-MM-DD)以後に作った機械の出力だけ(最初の認識の at、無ければ updatedAt)",
                      json_help="同じ形の JSON を 文字起こしの作業データの evals/timing/<日時>.json に残す")
    p.add_argument("--out", help="JSON をこのファイルに書く(作業データには書かない。--json を付けなくてよい)")
    p.add_argument("--apply", action="store_true", help="保存してある生出力(asr.json)に後処理(0.57.0 / 7-1 だけ / 0.57.1)を当て直した数字も出す")
    args = p.parse_args(argv)
    res = evaluate(args.data_dir, args.since, args.until, args.apply)
    print_report(res)
    C.report_saved(res, args.json or args.out, res["meta"]["dataDir"], "timing", out=args.out)
    return res


if __name__ == "__main__":
    C.utf8_stdout()
    main()
