# -*- coding: utf-8 -*-
"""① 字幕の読む速さの印(T2)と、直した行の時刻を単語の時刻から配り直す候補(T1 の簡易版)の計算。2026-10-05 に編集の ed_retime.py として作った。

役割で組み直す RS2-9(2026-10-10)に、計算の部分(subread_*・retime_raw・retime_candidates ほか。純粋な関数 = ファイルを読まない・書かない)を
編集の src/editor/ed_retime.py からここへ切り出した(中身は同じ)。文書と単語の時刻 words.json を読んで POST /api/retime に答える包み(retime_engine・retime_doc)は
src/human/proof/retime.py に残した(② の層)。標準ライブラリ・ytt(schemas)・同じパッケージの兄弟(txbase の alt_fold)だけを読む。ネイティブの部品は読み込まない。
名前は serve.py からも見える(serve.py の _ED_MODULES)。ほかの部品と重ならないよう subread_ / SUBREAD_ / retime_ / RETIME_ で始める。
ed_retime には別名・転送を置かない(差し替えが別名に当たる)。呼ぶ側は retime.名前 を呼ぶたびに読む。

1. 読む速さ(表示だけ。行を書き換えない)
   行ごとに「読む速さ」= 字幕として数える文字数(NFKC にして文字と数字だけ = 記号・空白・句読点・伸ばしの〜を除く。ー は数える)÷ 行の長さ(秒)。
   印は 2 つ: 速い(1 秒あたりの文字が SUBREAD_FAST_CPS を超える)・短い(表示の時間が SUBREAD_SHORT_SEC 未満)。どちらも文字が SUBREAD_MIN_CHARS 以上の行だけ。
   対象から外す: 字幕に出さない行(noSub)・空の下書き・文字の無い行・カット済の行。
   画面(app-rows.js の readMark)と同じ規則・同じ値(変えるときは両方。tests/test_retime.py が同じ例を固定)。
   値は設定の subtitle.read = {"fastCps", "shortSec"} で変えられる(任意の鍵。画面の欄は無い。subread_limits が範囲を確かめる)。
   しきい値の根拠(2026-10-05。本物の作業データを読むだけで測った): 確かめ済みの評価用 10 本の校正済み 148 行で 1 秒あたりの文字は
   中央値 5.8・p95 9.1・p99 13.2、長さは中央値 1.9 秒・p5 0.78 秒。速い > 10 字/秒・短い < 0.5 秒(2 文字以上)で、校正済みの行の 4.1%・全部の行(機械のまま含む 2098 行)の 11.9% に印。
   放送の字幕の目安(1 秒 4 文字)よりかなり速いが、ショートの字幕は人が通した行の中央値でもう 5.8 字/秒なので、それに合わせた

2. 時刻の配り直しの候補(**候補を出すだけ。文書を書き換えない**。採るのは画面の 1 押し)
   POST /api/retime {id, rows: [行の id…]} → {items: [{id, start, end, matched, dStart, dEnd, edges, from}], checked, updatedAt, reasonCode?, reason?}
   保存済みの文書と transcripts/<id>.words.json(認識のときの単語。行を直しても古いまま)で計算する。
   当て方: 行の今の時刻の前後 RETIME_PAD 秒にある単語の文字をつなげ、行の文字と寄せて(txbase.alt_fold。もとは ed_alt の alt_fold)比べる。
   単語の文字の並びのうち行の文字にいちばん合う所(両端は自由な編集距離 = fitting alignment)を探し、
   行の文字の最初・最後が当たった単語の開始・終了を候補にする(単語の途中の字なら字数で割り振る)。人が足した文字(単語に無い)は当たった所だけで決める。
   出す条件: 当たった文字の割合 RETIME_MIN_MATCH 以上・端ごとに、その端の字が当たっている・今との差 RETIME_MIN_DELTA 秒以上・
   同じ話者(か話者の無い行)の前後の行と重ならない所まで詰める(違う話者・字幕に出さない行・空の下書きとの重なりはそのまま)・行の長さが RETIME_MIN_LEN 秒以上。
   最後に当たった単語のすぐ後ろの「ー」「~」「!?」だけの単語(寄せると何も残らない)は行の終わりに含める(RETIME_JOIN)。
   行の終わりの調整(pipeline/transcribe/postproc の END_TRIM)は候補にかけない(かけると人から遠くなった。下の RETIME_END_SKIP の測った数字)。
"""
import bisect
import unicodedata

from ytt import schemas as _yschemas
from ytt import txbase as _txbase

# ---------- 1. 読む速さ ----------
SUBREAD_FAST_CPS = 10.0     # 1 秒あたりの字幕の文字がこれを超えたら「速い」(app-rows.js の READ_FAST_CPS と同じ値)
SUBREAD_SHORT_SEC = 0.5     # 表示の時間がこれ未満なら「短い」(READ_SHORT_SEC)
SUBREAD_MIN_CHARS = 2       # 文字がこれ未満の行(「え」「あ」の 1 文字)には印を付けない(READ_MIN_CHARS)
SUBREAD_RANGE = {"fastCps": (4.0, 40.0), "shortSec": (0.1, 3.0)}   # 設定 subtitle.read で変えるときの範囲(外れた値は既定)


def subread_chars(text):
    """字幕として数える文字数: NFKC にして、Unicode の分類が文字(L)・数字(N)のものだけ(記号・空白・句読点・〜 は数えない。ー は文字の Lm なので数える)"""
    return sum(1 for c in unicodedata.normalize("NFKC", str(text or "")) if unicodedata.category(c)[0] in "LN")


def subread_limits(settings=None):
    """しきい値 {"fastCps", "shortSec"}(設定の subtitle.read があればその値。範囲の外・形の違う値は既定)"""
    st = settings if isinstance(settings, dict) else {}
    sub = st.get("subtitle") if isinstance(st.get("subtitle"), dict) else {}
    rd = sub.get("read") if isinstance(sub.get("read"), dict) else {}
    out = {"fastCps": SUBREAD_FAST_CPS, "shortSec": SUBREAD_SHORT_SEC}
    for k, (lo, hi) in SUBREAD_RANGE.items():
        v = rd.get(k)
        if isinstance(v, (int, float)) and not isinstance(v, bool) and lo <= v <= hi:
            out[k] = float(v)
    return out


def subread_mark(row, limits=None):
    """行の読む速さの印 -> None(印なし・対象外)か {"chars", "sec", "cps", "fast", "short"}。
    対象外: 字幕に出さない行・空の下書き・文字の無い行・カット済の行。秒は終了 − 開始(負なら 0)"""
    if not isinstance(row, dict) or _yschemas.no_sub_row(row) or _yschemas.blank_draft_row(row) or row.get("cutState") == "cut":
        return None
    n = subread_chars(row.get("text"))
    if n < SUBREAD_MIN_CHARS:
        return None
    lim = limits or {"fastCps": SUBREAD_FAST_CPS, "shortSec": SUBREAD_SHORT_SEC}
    sec = max(0.0, (_yschemas.num_or(row.get("end"), 0.0) or 0.0) - (_yschemas.num_or(row.get("start"), 0.0) or 0.0))
    cps = n / sec if sec > 0 else float("inf")
    fast, short = cps > lim["fastCps"], sec < lim["shortSec"]
    if not (fast or short):
        return None
    return {"chars": n, "sec": round(sec, 3), "cps": round(cps, 2) if sec > 0 else None, "fast": fast, "short": short}


# ---------- 2. 時刻の配り直しの候補 ----------
RETIME_PAD = 1.5          # 行の今の時刻の前後この秒にある単語だけを見る(行を 2 秒以上動かした・別の所へ移した行は当たらない = 候補なし)
RETIME_MIN_MATCH = 0.6    # 行の文字のうち単語に当たった割合がこれ未満なら候補を出さない
RETIME_MIN_DELTA = 0.1    # 今の時刻との差がこれ未満の端は候補にしない(見える時刻 0.1 秒の単位で変わらない)
RETIME_MIN_LEN = 0.3      # 候補の行の長さがこれ未満になるなら候補を出さない
RETIME_MAX_CELLS = 60000  # 1 行の比べる表の大きさの上限(行の文字 × 単語の文字。長すぎる行は候補を出さない = 重くしない)
RETIME_MAX_ROWS = 4000    # 1 回に見る行の上限
RETIME_NEAR = 8           # 前後の行は 8 行まで見る(画面の重なりの赤 OVL_BACK と同じ)
RETIME_JOIN = 0.15        # 最後の単語のあとの「ー」「!?」などの単語を、すき間がこの秒以下なら行の終わりに含める
# 終わりの端を候補にしないエンジン(recognition.runs の最初の認識の engine。記録の無い古い文書は faster-whisper とみなす)。今は無し。
# 2026-10-05 本物の確かめ済み 10 本(whisper.cpp large-v3。人が時刻を直した校正済みの行 112)で、行の文字は人のまま・時刻は機械の行のままにして候補を出し、人の時刻と比べた:
#   開始 5 行: 機械 − 人 の |中央値| 0.87 秒 → 候補 0.20 秒(5 行とも候補の方が近い)
#   終了 11 行: 機械 0.88 秒 → 候補 0.10 秒(候補 − 人 の中央値 0.00・平均 −0.05。11 行とも候補の方が近い)。
#   END_TRIM(0.1 秒早める)を候補にもかけると ±0.1 秒以内が 45% → 18% に悪くなった = かけない(単語の終わりはもう trim 済みのことがある)。
# faster-whisper は人が時刻を直した校正済みの行がまだ無く測れていない(行の終わり = 最後の単語の終わりなので、同じ当て方で出す)。測れたらここで決め直す
RETIME_END_SKIP = ()


def _retime_same_group(a, b):
    """重なってはいけない 2 行か(画面の badOverlap と同じ: どちらかが字幕に出さない行・空の下書きなら気にしない・両方に話者があって違う人なら気にしない)"""
    if _yschemas.no_sub_row(a) or _yschemas.no_sub_row(b) or _yschemas.blank_draft_row(a) or _yschemas.blank_draft_row(b):
        return False
    sa, sb = str(a.get("speaker") or ""), str(b.get("speaker") or "")
    return not (sa and sb and sa != sb)


def _retime_fit(r, w):
    """r(行の寄せた文字)を w(単語の寄せた文字)のどこか連続した所に当てる(両端は自由・中は編集距離)。
    -> (当たった組 [(r の位置, w の位置)…], w の終わりの位置の候補ごとの費用が同じときに選べるよう、終わりの位置の一覧)"""
    n, m = len(r), len(w)
    inf = n + m + 1
    d = [[0] * (m + 1)]          # d[0][j] = 0(単語のどこから始めてもよい)
    for i in range(1, n + 1):
        prev, row = d[-1], [i] + [inf] * m
        ri = r[i - 1]
        for j in range(1, m + 1):
            v = prev[j - 1] + (0 if ri == w[j - 1] else 1)
            if prev[j] + 1 < v:
                v = prev[j] + 1        # 行の字が単語に無い(人が足した字)
            if row[j - 1] + 1 < v:
                v = row[j - 1] + 1     # 単語の字が行に無い
            row[j] = v
        d.append(row)
    best = min(d[n][1:]) if m else inf
    ends = [j for j in range(1, m + 1) if d[n][j] == best]
    return d, ends


def _retime_trace(d, r, w, j):
    """表 d を (len(r), j) からたどって、当たった組 [(r の位置, w の位置)…](前から)"""
    i, pairs = len(r), []
    while i > 0 and j > 0:
        v = d[i][j]
        if r[i - 1] == w[j - 1] and v == d[i - 1][j - 1]:
            pairs.append((i - 1, j - 1))
            i, j = i - 1, j - 1
        elif v == d[i - 1][j - 1] + 1:
            i, j = i - 1, j - 1
        elif v == d[i - 1][j] + 1:
            i -= 1
        else:
            j -= 1
    pairs.reverse()
    return pairs


def _retime_edge_time(word, pos, n, side):
    """単語 (開始, 終了, 文字) の寄せた字 n 個のうち pos 番目の字の開始(side=start)か終了(side=end)。途中の字は字数で割り振る"""
    a, b = float(word[0]), float(word[1])
    if n <= 1:
        return a if side == "start" else b
    k = pos if side == "start" else pos + 1
    return a + (b - a) * k / n


def retime_raw(row, words, starts=None):
    """1 行の候補(前後の行で詰める前)-> None か {"start", "end", "matched", "head", "tail"}(head/tail = 行の頭・末の字が当たったか)。
    words = [[開始, 終了, 文字]…](時刻の順)・starts = 単語の開始の並び(まとめて呼ぶときに使い回す)"""
    a, b = _yschemas.num_or(row.get("start")), _yschemas.num_or(row.get("end"))
    if a is None or b is None:
        return None
    r = _txbase.alt_fold(str(row.get("text") or ""))
    if not r or not words:
        return None
    starts = starts if starts is not None else [float(x[0]) for x in words]
    lo = max(0, bisect.bisect_left(starts, a - RETIME_PAD) - 1)
    hi = bisect.bisect_right(starts, b + RETIME_PAD)
    wch, win = [], []   # wch = (寄せた字, 単語の窓の中の番号, 単語の中の位置, 単語の寄せた字の数)・win = 窓の中の単語と寄せた文字
    for x in words[lo:hi]:
        mid = (float(x[0]) + float(x[1])) / 2
        if not (a - RETIME_PAD <= mid <= b + RETIME_PAD):
            continue
        f = _txbase.alt_fold(str(x[2]))
        win.append((x, f))
        for p, c in enumerate(f):
            wch.append((c, len(win) - 1, p, len(f)))
    if not wch or len(r) * len(wch) > RETIME_MAX_CELLS:
        return None
    w = "".join(c[0] for c in wch)
    d, ends = _retime_fit(r, w)
    if not ends:
        return None
    # 費用が同じ終わりの位置が複数あれば(同じ言葉の繰り返しなど)、今の行の終わりにいちばん近いもの
    j = min(ends, key=lambda e: abs(float(win[wch[e - 1][1]][0][1]) - b))
    pairs = _retime_trace(d, r, w, j)
    if not pairs:
        return None
    matched = len(pairs) / len(r)
    (ri0, wj0), (ri1, wj1) = pairs[0], pairs[-1]
    c0, c1 = wch[wj0], wch[wj1]
    end = _retime_edge_time(win[c1[1]][0], c1[2], c1[3], "end")
    if c1[2] == c1[3] - 1:
        # 最後に当たった単語のすぐ後ろの、寄せると何も残らない単語(伸ばし「ー」「~」・句読点「!?」)は行の声の続き: 終わりをそこまで延ばす
        # (「うわ」+「ー」の「ー」は 1 秒続くことがある。延ばさないと行の終わりが言葉の途中になった)
        k = c1[1]
        while k + 1 < len(win) and not win[k + 1][1] and float(win[k + 1][0][0]) - float(win[k][0][1]) <= RETIME_JOIN:
            k += 1
            end = float(win[k][0][1])
    return {"start": _retime_edge_time(win[c0[1]][0], c0[2], c0[3], "start"), "end": end,
            "matched": matched, "head": ri0 == 0, "tail": ri1 == len(r) - 1}


def retime_candidates(segments, words, ids=None, end_ok=True):
    """行の一覧 segments(文書の全部の行。前後の行で詰めるため)と単語の並び words から、ids の行(None なら全部)の候補。
    -> [{"id", "start", "end", "matched", "dStart", "dEnd", "edges": ["start"?, "end"?], "from": {"start", "end"}}](行の並びの順)。
    end_ok=False なら終わりの端は候補にしない(RETIME_END_ENGINES)。純粋な関数(ファイルを読まない・書かない)"""
    segs = sorted([g for g in segments or [] if isinstance(g, dict) and _yschemas.num_or(g.get("start")) is not None and _yschemas.num_or(g.get("end")) is not None],
                  key=lambda g: float(g["start"]))
    ws = sorted([[float(x[0]), float(x[1]), str(x[2])] for x in words or [] if isinstance(x, (list, tuple)) and len(x) >= 3], key=lambda x: (x[0], x[1]))
    starts = [x[0] for x in ws]
    want = None if ids is None else {str(i) for i in ids}
    raw = {}
    for k, g in enumerate(segs):
        if want is not None and str(g.get("id")) not in want:
            continue
        if len(raw) >= RETIME_MAX_ROWS or _yschemas.blank_draft_row(g) or not str(g.get("text") or "").strip():
            continue
        c = retime_raw(g, ws, starts)
        if not c or c["matched"] < RETIME_MIN_MATCH:
            continue
        a0, b0 = float(g["start"]), float(g["end"])
        s = c["start"] if c["head"] and abs(c["start"] - a0) >= RETIME_MIN_DELTA else None
        e = c["end"] if end_ok and c["tail"] and abs(c["end"] - b0) >= RETIME_MIN_DELTA else None
        if s is None and e is None:
            continue
        raw[k] = (s, e, c["matched"])
    out = []
    for k, (s, e, matched) in sorted(raw.items()):
        g = segs[k]
        a0, b0 = float(g["start"]), float(g["end"])
        # 前後の同じ話者の行と重ならない所まで詰める(相手にも候補があれば、今と候補のうち狭い方 = 両方を採っても重ならない)
        lo_b, hi_b = None, None
        for q in range(max(0, k - RETIME_NEAR), k):
            p = segs[q]
            if not _retime_same_group(p, g):
                continue
            pe = float(p["end"])
            if q in raw and raw[q][1] is not None:
                pe = max(pe, raw[q][1])
            lim = min(pe, a0)   # 今もう重なっている行は、今より悪くしない所まで
            lo_b = lim if lo_b is None else max(lo_b, lim)
        for q in range(k + 1, min(len(segs), k + 1 + RETIME_NEAR)):
            p = segs[q]
            if not _retime_same_group(p, g):
                continue
            ps = float(p["start"])
            if q in raw and raw[q][0] is not None:
                ps = min(ps, raw[q][0])
            lim = max(ps, b0)
            hi_b = lim if hi_b is None else min(hi_b, lim)
        if s is not None and lo_b is not None and s < lo_b:
            s = lo_b
        if e is not None and hi_b is not None and e > hi_b:
            e = hi_b
        s = round(s, 2) if s is not None else None
        e = round(e, 2) if e is not None else None
        if s is not None and abs(s - a0) < RETIME_MIN_DELTA:
            s = None
        if e is not None and abs(e - b0) < RETIME_MIN_DELTA:
            e = None
        if s is None and e is None:
            continue
        ns, ne = (s if s is not None else a0), (e if e is not None else b0)
        if ne - ns < RETIME_MIN_LEN:
            continue
        out.append({"id": str(g.get("id")), "start": ns, "end": ne, "matched": round(matched, 3),
                    "dStart": round(ns - a0, 2), "dEnd": round(ne - b0, 2),
                    "edges": [x for x, v in (("start", s), ("end", e)) if v is not None], "from": {"start": a0, "end": b0}})
    return out
