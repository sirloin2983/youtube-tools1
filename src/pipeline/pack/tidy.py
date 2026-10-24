# -*- coding: utf-8 -*-
"""編集カットの形「無音を詰める」(10-24。ユーザー「言葉を削るんじゃなくて、無音を削ってほしい。ただ不自然になるから調整が必要」。
研究のセッションの試作 = C:/dev/overlap-research/notes/autocut-findings.md の「無音を、不自然にならないように詰める」と tools/silence_trim.py を製品の部品で)。
言葉は削らない(つなぎの言葉も)。話の間の無音だけを短くする:
  間     … 声の中央より QUIET_DB 以上静かな所が GAP 秒以上続く所
  残す   … 言い終わりの後に TAIL 秒(余韻)・話し始めの前に HEAD 秒(息)を残して、真ん中を削る(友人の切れ目のつなぎ目の無音 中央 0.04 / 90% 0.20 秒)
守り(言葉の頭と終わりを欠かない):
  - 単語(文字起こしの単語の時刻)の範囲のうち声のあるこま(声の中央から GUARD_DB 以内)は削らない。長さ 0 の単語はその時刻の前後 ZERO_PAD 秒
    (単語の時刻は後ろの無音まで含んで長く付くことがある = 範囲をそのまま守ると間を詰められない。声の無い部分は下の音の守りに任せる)
  - 削る所に、声の中央から GUARD_DB 以内の音(小さい声・息・語尾のかすれ)が GUARD_RUN 秒以上続けば、その間は詰めない
声の中央 = 単語のある所の 20 ms の音量(RMS)の中央値。音は edge_pause の levels(20 ms ごとの dB)・pauses を使う。
単語は呼ぶ側(② flow)が文字起こしの単語の時刻(*.words.json)から渡す(① は単語の時刻のファイルを読まない)。単語が無い文書は詰めない([])。
スイッチ: ON = False で使わない。つなぎ目のクロスフェード(研究は 10 ms)はパック・画面ではまだ付けていない
"""
import math
import statistics

from . import edge_pause as E

ON = True
GAP = 0.4          # 詰める間の最短(秒。研究: 0.3〜0.6 で数はほぼ同じ)
TAIL = 0.10        # 言い終わりの後に残す秒(余韻。0.05 だと語尾のかすれを欠く疑いが増えた)
HEAD = 0.05        # 話し始めの前に残す秒(息)
QUIET_DB = 15.0    # 間 = 声の中央よりこれだけ静か
GUARD_DB = 25.0    # 削る所に、声の中央からこの dB 以内の音が
GUARD_RUN = 0.06   # この秒以上続けば、その間は詰めない
ZERO_PAD = 0.05    # 長さ 0 の単語を守る前後の秒


def _rms_db(fr):
    """20 ms ごとの dB の並び -> まとめた強さ(dB)。空なら -120"""
    return 10 * math.log10(sum(10 ** (d / 10) for d in fr) / len(fr) + 1e-12) if fr else -120.0


def _free(p0, p1, guard):
    """[p0, p1] から guard([(始まり, 終わり)])にかかる所を除いた部分"""
    out, t0 = [], p0
    for a, b in sorted(g for g in guard if g[1] >= p0 and g[0] <= p1):
        if a > t0:
            out.append((t0, a))
        t0 = max(t0, b)
    if t0 < p1:
        out.append((t0, p1))
    return out


def drops(video, words, lo, hi):
    """[lo, hi](秒)の中の詰める所 -> [(始まり, 終わり, "pause")](時刻の順)。音が読めない・スイッチ・単語なしは []。
    words: [[開始, 終了, 文字], ...](video の秒)"""
    if not ON or hi - lo <= 0:
        return []
    ws = [w for w in words or [] if w[1] >= lo and w[0] <= hi and (w[2] or "").strip()]
    if not ws:
        return []
    db = E.levels(video, lo, hi)
    if not db:
        return []
    at = lambda t: max(0, min(len(db), int(round((t - lo) / E.HOP))))
    lv = statistics.median(_rms_db(db[at(a):max(at(a) + 1, at(b))]) for a, b, _t in ws)
    run = max(1, int(round(GUARD_RUN / E.HOP)))

    def faint(a, b):   # 削る所に小さい声・息が run 個(20 ms)以上続くか
        n = 0
        for d in db[at(a):at(b)]:
            n = n + 1 if d >= lv - GUARD_DB else 0
            if n >= run:
                return True
        return False
    guard = []
    for a, b, _t in ws:
        if b - a < E.HOP:
            guard.append((a - ZERO_PAD, b + ZERO_PAD))
            continue
        for i in range(at(a), max(at(a) + 1, at(b))):
            if i < len(db) and db[i] >= lv - GUARD_DB:
                guard.append((lo + i * E.HOP, lo + (i + 1) * E.HOP))
    out = []
    for p0, p1 in E.pauses(db, lo, lv, QUIET_DB, GAP):
        for s, e in _free(p0, p1, guard):
            a, b = s + TAIL, e - HEAD
            if e - s >= GAP and b > a and not faint(a, b):
                out.append((round(a, 3), round(b, 3), "pause"))
    return sorted(out)


def keeps(lo, hi, cut, min_len=0.05):
    """[lo, hi] から cut([(始まり, 終わり, ...)])を除いた残す区間 [(始まり, 終わり)](min_len 秒より短い切れ端は捨てる)"""
    out, t0 = [], lo
    for a, b, *_ in sorted(cut):
        if a > t0:
            out.append((t0, a))
        t0 = max(t0, b)
    if t0 < hi:
        out.append((t0, hi))
    return [(round(a, 3), round(b, 3)) for a, b in out if b - a > min_len]
