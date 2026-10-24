# -*- coding: utf-8 -*-
"""編集カットの形「無音を詰める」(10-24。ユーザー「言葉を削るんじゃなくて、無音を削ってほしい。ただ不自然になるから調整が必要」。
研究のセッションの試作 = C:/dev/overlap-research/notes/autocut-findings.md の「無音を、不自然にならないように詰める」と tools/silence_trim.py を製品の部品で)。
言葉は削らない(つなぎの言葉も)。話の間の無音だけを短くする:
  間     … 声の中央より QUIET_DB 以上静かな所が GAP 秒以上続く所
  残す   … 言い終わりの後に TAIL 秒(余韻)・話し始めの前に HEAD 秒(息)を残して、真ん中を削る(友人の切れ目のつなぎ目の無音 中央 0.04 / 90% 0.20 秒)
守り(言葉の頭と終わりを欠かない):
  - 単語(文字起こしの単語の時刻)の範囲のうち声のあるこま(声の中央から GUARD_DB 以内)は削らない。長さ 0 の単語はその時刻の前後 ZERO_PAD 秒の中の声のあるこま
    (単語の時刻は後ろの無音まで含んで長く付くことがある = 範囲をそのまま守ると間を詰められない。声の無い部分は下の音の守りに任せる)
  - 削る所に、声の中央から GUARD_DB 以内の音(小さい声・息・語尾のかすれ)が GUARD_RUN 秒以上続けば、その音の前後 FAINT_PAD 秒は詰めず、
    その両側の静かな所を、それぞれ SPLIT_GAP 秒以上あれば詰める(研究の 39 本: 間を丸ごと残すより 欠けの疑い 33 → 11・詰めた 272 → 328 秒。もとの間は GAP 以上)
  - 削る所の端が単語の声の端から EDGE_NEAR 秒以内なら、その端だけ EDGE_PAD 秒多く残す(言葉の端の近くの欠けの疑いを減らす)
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
GUARD_DB = 27.0    # 削る所に、声の中央からこの dB 以内の音が(研究の 39 本: 25 では内容を失った 1・27 で 0)
GUARD_RUN = 0.06   # この秒以上続けば、その間は詰めない
ZERO_PAD = 0.05    # 長さ 0 の単語を守る前後の秒
FAINT_PAD = 0.05   # 小さい声・息の続きを守る前後の秒
SPLIT_GAP = 0.3    # 小さい声・息で分けた静かな所を詰める最短(秒)
EDGE_NEAR = 0.15   # 削る所の端が単語の声の端からこの秒以内なら
EDGE_PAD = 0.05    # その端だけこの秒多く残す(研究の 39 本: 言葉の端の近くの欠けの疑い 9 → 3・詰める秒は 2 割減)


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
    faint, n, s0 = [], 0, 0   # 小さい声・息の続き(run こま以上)の前後 FAINT_PAD 秒
    for i, d in enumerate(list(db) + [-120.0]):
        if d >= lv - GUARD_DB:
            s0, n = (i if n == 0 else s0), n + 1
            continue
        if n >= run:
            faint.append((lo + s0 * E.HOP - FAINT_PAD, lo + i * E.HOP + FAINT_PAD))
        n = 0
    guard = []
    for a, b, _t in ws:
        if b - a < E.HOP:   # 長さ 0: 前後 ZERO_PAD 秒に声があるときだけ(無音の中に付いた時刻の怪しい単語で間を分けない)
            a, b = a - ZERO_PAD, b + ZERO_PAD
        for i in range(at(a), max(at(a) + 1, at(b))):
            if i < len(db) and db[i] >= lv - GUARD_DB:
                guard.append((lo + i * E.HOP, lo + (i + 1) * E.HOP))
    ends, starts = [g[1] for g in guard], [g[0] for g in guard]
    out = []
    for p0, p1 in E.pauses(db, lo, lv, QUIET_DB, GAP):
        for s, e in _free(p0, p1, guard):
            if e - s < GAP:
                continue
            inner = [(fa, fb) for fa, fb in faint if fb - FAINT_PAD > s + TAIL and fa + FAINT_PAD < e - HEAD]   # 詰める所の中の物だけ
            for s2, e2 in _free(s, e, inner):
                a = s2 + (TAIL if s2 == s else 0)   # TAIL・HEAD は間のもとの端の側だけ(小さい声の側は FAINT_PAD で残してある)
                b = e2 - (HEAD if e2 == e else 0)
                if EDGE_PAD and any(0 <= a - g <= EDGE_NEAR for g in ends):
                    a += EDGE_PAD
                if EDGE_PAD and any(0 <= g - b <= EDGE_NEAR for g in starts):
                    b -= EDGE_PAD
                if e2 - s2 >= SPLIT_GAP and b > a:
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
