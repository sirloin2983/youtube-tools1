# -*- coding: utf-8 -*-
"""編集カットの形「言いよどみと長い間を詰める」(10-24。研究のセッションの試作 v2 = C:/dev/overlap-research/notes/autocut-findings.md を製品の部品で)。
発話は選ばない = 話した言葉は全部残し、要らない所だけを削る(ユーザー「話の内容を失ってはいけない」):
  間       … 声の中央より QUIET_DB 以上静かな所が GAP 秒以上続く所を、両側に KEEP 秒ずつ残して詰める
  言いよどみ … つなぎの言葉(FILLERS とぴったり同じ単語・FILLER_MAX 秒以下)を、内側 INNER 秒を残して削る(単語の時刻の粗さで言葉を欠かない)
守り: 間の中に、つなぎの言葉でない単語(内容)があれば、その単語の前後 KEEP 秒は詰めず、単語の無い部分(GAP 秒以上)だけを詰める
  (声が小さいだけで認識が聞き取った言葉 =「オッケー」「びっくり」など。単語の時刻は 1〜2 文字ずつで 0.1 秒未満も多いので、長さ・音量では選ばない)。
  = 内容の単語は、どの削る所にもかからない(言いよどみは内容ではない)。
声の中央 = 単語のある所の 20 ms の音量の中央値。音は edge_pause の levels(20 ms ごとの dB)・pauses を使う。
研究の 4 本(友人のパックの音で当てた正解)で: 内容を失った 0・友人が削った間の 38%・言いよどみ(一覧の物)は友人も削った物だけ。
返事になりうる「はい・そう・うん・その・なんか」は既定で削らない(REPLY_FILLERS。extra で足せる)。スイッチ: ON = False で使わない。
単語は呼ぶ側(② flow)が文字起こしの単語の時刻(*.words.json)から渡す(① は単語の時刻のファイルを読まない)。
"""
import math
import statistics

from . import edge_pause as E

ON = True
FILLERS = ("あの", "あのー", "あのぉ", "えっと", "えーっと", "えと", "えーと", "まあ", "まぁ", "まー", "うーん", "んー", "あー", "えー")
REPLY_FILLERS = ("はい", "そう", "うん", "その", "なんか")   # 返事・内容になりうる = 既定で削らない(extra で足す)
GAP = 0.4          # 詰める間の最短(秒)
KEEP = 0.08        # 詰めた間の両側に残す秒
INNER = 0.03       # つなぎの言葉の内側に残す秒
FILLER_MAX = 0.8   # これより長いつなぎの言葉は削らない(時刻が怪しい・伸ばしが内容)
QUIET_DB = 15.0
_PUNCT = " 、。,.!?！？…"


def _rms_db(fr):
    """20 ms ごとの dB の並び -> まとめた強さ(dB)。空なら -120"""
    return 10 * math.log10(sum(10 ** (d / 10) for d in fr) / len(fr) + 1e-12) if fr else -120.0


def _free(p0, p1, guard):
    """[p0, p1] から guard([(始まり, 終わり)])にかかる所を除いた部分"""
    out, t0 = [], p0
    for a, b in sorted(g for g in guard if g[1] > p0 and g[0] < p1):
        if a > t0:
            out.append((t0, a))
        t0 = max(t0, b)
    if t0 < p1:
        out.append((t0, p1))
    return out


def is_filler(text, extra=()):
    t = (text or "").strip(_PUNCT)
    return bool(t) and (t in FILLERS or t in extra)


def drops(video, words, lo, hi, extra=()):
    """[lo, hi](秒)の中の削る所 -> [(始まり, 終わり, "pause" | "filler")](時刻の順)。音が読めない・スイッチ・単語なしは []。
    words: [[開始, 終了, 文字], ...](video の秒)"""
    if not ON or hi - lo <= 0:
        return []
    ws = [w for w in words or [] if w[1] > lo and w[0] < hi and w[1] > w[0]]
    if not ws:
        return []
    db = E.levels(video, lo, hi)
    if not db:
        return []
    at = lambda t: max(0, min(len(db), int(round((t - lo) / E.HOP))))
    loud = lambda a, b: _rms_db(db[at(a):max(at(a) + 1, at(b))])   # 単語の区間の全体の強さ(研究と同じ RMS)
    lv = statistics.median(loud(a, b) for a, b, _t in ws)
    guard = [(a - KEEP, b + KEEP) for a, b, t in words if b >= lo and a <= hi and not is_filler(t, extra) and t.strip(_PUNCT)]   # 長さ 0 の単語も守る
    out = []
    for p0, p1 in E.pauses(db, lo, lv, QUIET_DB, GAP):
        for s, e in _free(p0, p1, guard):
            if e - s >= GAP:
                out.append((round(s + KEEP, 3), round(e - KEEP, 3), "pause"))
    for a, b, t in ws:
        if is_filler(t, extra) and b - a <= FILLER_MAX and b - a > 2 * INNER:
            out.append((round(max(lo, a + INNER), 3), round(min(hi, b - INNER), 3), "filler"))
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
