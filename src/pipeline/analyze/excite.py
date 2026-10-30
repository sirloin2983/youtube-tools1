"""盛り上がり(excitement)の式。スタジオのアーカイブの解析(src/pipeline/analyze/analyze.py)と、配信中の検出(src/pipeline/analyze/live_excite_worker.py。線 D の L2)が同じ式を読む(線 D の L1。資料の git:before-1028-cleanup:plan/line-d-detect.md)。

決まり:
- **一括の関数(smooth・local_baseline・robust_scale・audio_score・chat_z・estimate_lag・pick_clips …)は式・加算の順・丸めを変えない**。
  アーカイブの結果(候補・series)が golden と完全に一致することを tests/pipeline/analyze/test_excite.py の golden が確かめる。式を直すときは golden も作り直す(src/eval/tools/eval_marks.py の数字と比べられなくなるので WORKLOG に書く)
- 配信中は「未来を見る量」だけが違う(資料の git:before-1028-cleanup:plan/line-d-live-clipping.md の 0-10-2): ふだん = 前 back 秒・後 fwd 秒の中央値(アーカイブは 150/150、配信中は 270/30。チャットだけはアーカイブ 600/600・配信中 1170/30 = CHAT_HALF・ONLINE_CHAT_BACK)、
  跳ね上がりの尺度 = 直近 window 秒の MAD(アーカイブは全体)。これを持つのが Online(1 秒ずつ足す。一括の答え合わせは test_excite の windowed_scores)
- 候補の帳簿 PeakBook: 山の確定(0-10-3 の 5)・1 時間の枠と入れ替え(0-10-3 の 6)・採用と見送りの除外。純粋(時計・ファイルを持たない)で、JSON にして起動し直しに耐える。
  配信中だけの足し(どれも呼ばなければ候補は同じ): しきい値を上げる区間 thr_scale(雰囲気の変わり目 MoodShift のあと 60 秒は 1.3 倍。0-10-5)・
  仮の候補 fast_push(チャットを待たない音だけの先回り。候補が出るまでの遅れを縮める。本番の候補は変わらない)・
  配信の終わりの本数の埋め fill_quota(候補が 1 時間の本数 × 配信の時間に届かなければ、しきい値の下の山で埋める。印 fill)
- 標準ライブラリだけ(numpy は使わない。入口の子プロセスでも足さずに済む)

使い方:
    from pipeline.analyze import excite
    audio = excite.audio_score(full_db, band_db)                        # アーカイブ
    on = excite.Online(back=270, fwd=30, window=1800, lag=8)             # 配信中
    for t, total, parts in on.push(full, band, act): book.push(t, total, parts, level)
"""
import math
import re

CAP = 6.0
SENS = {"high": 1.2, "normal": 2.0, "low": 3.2}
LAG_MAX = 30
LAG_MIN_CORR = 0.08     # これ未満の一致度では推定しない
LAG_MIN_CONTRAST = 0.04  # 最良の遅れと最悪の遅れの一致度の差がこれ未満なら、はっきりした山がないので推定しない
PRE_RATIO_DEFAULT = 0.65   # 山の位置(区間の何割を山の前に置くか)の既定。スタジオの設定 preRatio と src/eval/tools/eval_marks.py が読む
PART_ON = {"audio": 1.5, "chat": 1.5, "comments": 0.8, "heat": 1.0}   # 点数の内訳が「効いた」とみなす値(候補の理由の文と src/eval/tools/eval_marks.py が同じ値を読む)
WARM_RE = re.compile(r"草|ｗ{2,}|w{3,}|笑|わら|8{3,}|８{3,}|！{2,}|!{2,}|すご|うま|上手|かわい|可愛|てぇてぇ|てえてえ|きた|キタ|やば|ヤバ|神|最高|えらい|www|lol|kusa|pog|LUL|😂|🤣|😆|😍|❤|💕|👏|🎉|:_?laugh|:_?kusa|:_?heart|:_?clap|:_?pog", re.I)
CHAT_KINDS = ("liveChatTextMessageRenderer", "liveChatPaidMessageRenderer", "liveChatPaidStickerRenderer", "liveChatMembershipItemRenderer")
PAID_KINDS = ("liveChatPaidMessageRenderer", "liveChatPaidStickerRenderer")
WARM_BONUS = 1.5   # 「草」などの反応の重み
PAID_BONUS = 4.0   # スーパーチャットは強い反応
ONLINE_BACK, ONLINE_FWD, ONLINE_WINDOW = 270, 30, 1800   # 配信中の既定(0-10-2)。アーカイブは back = fwd = 150・window = 全体
STEP = 10   # ふだんの中央値を取る間隔(秒)。local_baseline の step と同じ
# 式の数字(一括の関数と配信中の Online・PeakBook が同じ値を読む。値を変えると golden が食い違う)
AUDIO_PARTS = ((3, 0.6), (3, 0.4))   # 音の点数の (ならす幅(秒), 重み): 全帯域・高音域(笑い声・叫び)の順
AUDIO_FLOOR = 1.5                    # 音の跳ね上がりの尺度の下限(robust_scale の floor)
CHAT_SMOOTH, CHAT_FLOOR = 9, 0.25    # チャットの活気: ならす幅(秒)・尺度の下限
# チャットの「ふだん」を取る幅(10-22 heatmap = よく再生された所 45 本で選んだ。決定 3-135): 前後 150 秒 → 600 秒(アーカイブ)・
# 配信中は前 270 秒 → 1170 秒(後ろは ONLINE_FWD のまま = 候補の遅れは変わらない)。狭いとチャットの多い場面が続くと「ふだん」が追いついて山が消える。
# 音のふだんは今のまま(広げても良くならなかった)。スイッチ: 2 つを 150・ONLINE_BACK に戻すと前の式(golden は作り直し)。
# 印: archive の解析の記録 chatHalf・配信中の peaks.json の chatBack
CHAT_HALF = 600
ONLINE_CHAT_BACK = 1170
# コメント欄の時刻の点数の形(10-22 heatmap 45 本・友人の区間で選んだ。決定 3-137): 書かれた時刻の前はチャットが平らで、時刻から 45 秒ほど跳ねる
# → 山を時刻の 5 秒あとに置き、前は狭く(5 秒)後ろは広く(20 秒)。後ろ 30 秒(fwd30。0.99.101〜106)は場面ごとの区間を長くして
# clipfit の余分の中央値が 47 → 64 秒(合格の線 60 秒の外)になったので 20 秒に(余分 41 秒・heatmap の良さは組 A で同じ。10-22 夕方)。
# 15 秒にすると組 A の heatmap の良さが消える(崖が近い = 測り直すときは 15〜30 秒を並べる)。重み wComments は 0.7 のまま(上げると clipfit が悪化)
# スイッチ: COMMENT_SHAPE = "sym" で前の形(左右同じ ±20 秒・幅 8 秒。golden は作り直し)。印: archive の解析の記録 commentShape(無い記録は sym)
COMMENT_SHAPE = "fwd20"
COMMENT_FORMS = {"sym": (-20, 20, 0, 8.0, 8.0), "fwd": (-5, 71, 5, 5.0, 30.0), "fwd20": (-5, 49, 5, 5.0, 20.0)}   # (時刻からの秒の から, まで, 山の位置, 前の幅, 後ろの幅)
# 山を選ぶ点数だけコメントを重くする(10-23。notes:plan/heatmap-study.md の「順位と区間の形を分ける」。決定 3-147): (重み wComments に掛ける倍率, 形)。
# 区間の形(場面の始まり・終わり)は今の合計のまま = pick_clips の scene_total。友人の 30 区間で使える候補の順位の逆数 .25 → .32(片側 p .04)・heatmap も両方の組で上
# スイッチ: None で前の形(山も場面も同じ合計)。印: archive の解析の記録 peakComment(無い記録は前の形)
PEAK_COMMENT = (2.0, "fwd")
PICK_SMOOTH = 5                      # 山を探す前に合計をならす幅(秒)
LEVEL_SMOOTH = 3                     # 区間を静かな所へ合わせる前に音量をならす幅(秒)
SNAP_RADIUS = 4                      # 静かな所を探す前後の秒数(snap_quiet)
SNAP_RATIO = (0.7, 1.3)              # 合わせた区間の長さがこの倍率の中なら合わせる(山を含むときだけ)
PARTS_RADIUS = 6                     # 点数の内訳(parts)を取る山の前後の秒数
EXCLUDE_BEFORE, EXCLUDE_AFTER = 5, 6   # 確定した区間の前後(pick_clips の [s-5, e+6))は次の山にしない
# 場面ごとの長さ(LD-2b。notes:plan/done/ld2-clip-length.md): 区間 = 上りの始まり − 前振りの余白 〜 収まり + 余韻を 60〜300 秒に丸める。
# 守り: 候補に印 shape と固定の長さの区間 fixed を残す・下のスイッチ 1 つで今までの形(山から固定の長さ)に戻る・測る道具(src/eval/tools/clipfit.py)は形を自分で選ぶ
# 本数に届かないときの埋め(守り: 候補に印 fill と理由の文 FILL_REASON・下のスイッチ 1 つで埋めない・spec に fill が無ければ今までと同じ
# = 測る道具 src/eval は渡さない・archive の候補にも印が残る)
FILL_ON = True
FILL_REASON = "本数に届かないので埋めた(点数は低め)"
SHAPE_DEFAULT = "scene"   # スイッチ: "scene" = 場面ごと / "fixed" = 山から固定の長さ(0.88 まで)。解析の設定・配信中の spec の shape が上書きする
SHAPES = ("scene", "fixed")
# 固定の長さを使わない(10-28 ユーザー。notes:plan/今の前提.md の 2 章): 場面が取れないとき(山が平ら)の区間を、設定の長さ(既定 45 秒・長さの目安)でなく
# 同じ配信で取れた場面の長さの中央値を AUTO_LEN に丸めた長さ(取れた場面が無ければ AUTO_LEN_DEFAULT)にする。友人の依頼のライブはいつも場面ごと・
# 解析の設定の shape "fixed" は読まない(live_excite_worker・analyze が見る)。印: 候補の shape "auto"。測る道具(src/eval)は spec に fallback を渡さない = 今までと同じ。
# スイッチ: False で前の形(場面が取れなければ固定の長さ・友人の古い依頼は固定・設定の fixed を読む)
AUTO_LEN_ON = True
AUTO_LEN = (150.0, 180.0)
AUTO_LEN_DEFAULT = 165.0


def auto_length(lengths):
    """場面が取れないときの長さ: 取れた場面の長さ lengths の中央値を AUTO_LEN に丸める(無ければ AUTO_LEN_DEFAULT)"""
    v = [float(x) for x in lengths]
    return AUTO_LEN_DEFAULT if not v else max(AUTO_LEN[0], min(AUTO_LEN[1], median(v)))


# 割れた場面をつなぐ(10-28 ユーザー「既定でつなぐ」。notes:plan/候補の点数のしきい値の案-1028.md の付録): 山は高い順に選んで選んだ範囲だけを除くので、
# 1 つの場面が隣り合う 2 本に割れることがある(割れたパックは友人が 37 本中 0 本しか受け取っていない)。重なるか間 JOIN_GAP 秒以内の隣り合う候補を、
# つないだ長さ JOIN_MAX 秒までなら 1 本にする(減った本数は埋めない = 本数の基準と一緒にユーザーが決める)。
# 印: 候補の joined(元の範囲の一覧)と pieces(元の本数)。つないだ候補は本数の枠(count・1 時間の枠 per_hour・友人の依頼の top)で元の本数と数える
# (10-28 ユーザー「ただ繋げたものは 2 本と数えてほしい」= つないで枠が空いて次の山を足すことは起きない)。配信中は次の候補を作るときだけつなぐ(届けた = 採用した候補は書き換えない)。
# 測る道具(src/eval)は spec に join を渡さない = 今までと同じ。スイッチ: False で前の形
JOIN_ON = True
JOIN_GAP = 10.0
JOIN_MAX = 360.0


def pieces(c):
    """候補・マークを本数の枠で何本と数えるか(つないだ物は元の本数 pieces・ほかは 1)"""
    n = c.get("pieces") if isinstance(c, dict) else None
    return n if isinstance(n, int) and not isinstance(n, bool) and n > 1 else 1


def join_clips(out, gap=JOIN_GAP, mx=JOIN_MAX):
    """選んだ区間 out(pick_clips の形)のうち、重なるか間 gap 秒以内の隣り合う物を、つないだ長さ mx 秒までなら 1 本に -> 新しい一覧(点数の順)。
    つないだ区間は点数の高い方の山・点数・形を持ち、印 joined に元の範囲を残す。埋めた印 fill は両方とも埋めた物のときだけ"""
    res = []
    for c in sorted(out, key=lambda c: c["start"]):
        p = res[-1] if res else None
        if p is not None and c["start"] - p["end"] <= gap and max(p["end"], c["end"]) - p["start"] <= mx:
            top = dict(p if p["score"] >= c["score"] else c)
            top["joined"] = p.get("joined", [[p["start"], p["end"]]]) + [[c["start"], c["end"]]]
            top["pieces"] = pieces(p) + pieces(c)
            top["start"], top["end"] = p["start"], max(p["end"], c["end"])
            top.pop("fill", None)
            if p.get("fill") and c.get("fill"):
                top["fill"] = True
            res[-1] = top
        else:
            res.append(c)
    return sorted(res, key=lambda c: -c["score"])


# 場面を長くつなぐ(10-23 ユーザー「切り抜きたいところが欠けるのを減らす方が良い」。決定 3-151。notes:plan/heatmap-study.md の「区間の形」):
# hold 10 → 30 秒・rise 0.3 → 0.4。友人の 30 区間で 7 割を覆う候補が上位 20 本に入る割合が 4 組すべてで上がる(組 A .50 → .69)・余分は平均 +13 秒。
# 配信中(PeakBook)も同じ形(L-5)= 収まりの見極めが 20 秒長い。スイッチ: False で前の形(hold 10・rise 0.3)。印: archive の解析の記録 sceneForm・配信中の peaks.json の sceneForm
SCENE_LONG = True
SCENE = {"rise": 0.4 if SCENE_LONG else 0.3,   # 上りの始まり = 点数が「ふだん」+ この割合 ×(山 − ふだん)を超え始めた秒
         "settle": 0.3,    # 収まり = 山のあと、同じく決まった割合を下回って hold 秒続いた所の手前
         "hold": 30 if SCENE_LONG else 10,     # 上り・収まりの判定で、下回りがこの秒数続いたら場面の外(短い谷は同じ場面にまとめる)
         "lead": 90.0,     # 前振りの余白(秒)。lead・tail・rise・settle は LD-2a の物差し(src/eval/tools/clipfit.py --grid)で配信を 2 組に分けて選んだ
         "tail": 45.0,     # 余韻(秒。粗い系列で見た友人の終わり = 収まりの 27 秒あと より、1 秒の点数で測ると長めが合った)
         "min": 60.0, "max": 300.0,   # 長さの守り(L-3)
         "base": 300}      # 「ふだん」= 山の前のこの秒数の点数の下から 4 分の 1(配信中も同じに取れるよう前だけ)


# チャットの跳ねの続きと笑いの書き込みで選び直す(10-29 ユーザー「入れてすぐ反映して」。研究の仮説 8・9 = C:/dev/overlap-research の tools/hyp.py combo・combo_live。
# notes:plan/製品に入れる案-チャットの跳ねと笑い-1029.md): 候補を RERANK_POOL 本まで出し、点の z + 1.0 × 跳ねる箱の割合の z + 0.5 × 笑いの書き込みの割合の z で
# 本数(count)を選び直す(z = その配信の候補の中)。跳ねる箱 = 候補の中の 10 秒の箱のうち、チャットの件数が配信の箱の件数の中央値の 2 倍以上の箱。
# 笑いの書き込み = 候補の中の書き込みのうち、草・笑・w・笑いの絵文字のある物の割合。数えるのは文字の書き込み(liveChatTextMessageRenderer)だけ。
# 配信中(PeakBook.rerank)は、ふだん(中央値)をその候補の始まりより前のチャットだけで出し、1 時間の枠の入れ替えと控えから戻す順に使う(仮説 9)。
# 印: 候補の chatRank {rate, laugh, z, up}(up = 点だけなら選ばれなかった)・archive の解析の記録 spec の rerank と counts の rerank {raised, dropped}。
# チャットの文字の書き込みが無い配信は今のまま。測る道具(src/eval)は spec に rerank を渡さない = 今までと同じ。スイッチ: False で前の形
CHAT_RERANK_ON = True
RERANK_POOL = 30
RERANK_W = (1.0, 0.5)            # (跳ねる箱の割合, 笑いの書き込みの割合)の重み
RERANK_BOX = 10                  # 箱の秒
SETTLE_NEAR = 30                 # 印 chatRank.settle: 笑いの収まりを探す、山の前後の秒(研究と同じ)
LAUGH_NEAR = 60                  # 印 chatRank.lc: 山の前後この秒(候補の区間の中)の笑いの書き込みの件数(flow/live_batch の最終の候補の点・10-30)
LAUGH_RE = re.compile(r"草|笑|ワロ|わろ|lol|(?<![A-Za-z])[wｗW]+(?![A-Za-z])", re.I)   # 研究の chat_content.LAUGH と同じ
LAUGH_EMO = set("😂🤣😆😹😄😁")


def chat_text_flag(kind, renderer):
    """チャットの 1 件 -> 0(文字の書き込みでない)/ 1(文字の書き込み)/ 2(笑いの書き込み)。研究の chat_content.read_msgs と同じ見方"""
    if kind != "liveChatTextMessageRenderer" or not isinstance(renderer, dict):
        return 0
    runs = (renderer.get("message") or {}).get("runs") or []
    text = "".join(str(u.get("text", "")) for u in runs if isinstance(u, dict))
    emo = [u["emoji"] for u in runs if isinstance(u, dict) and isinstance(u.get("emoji"), dict)]
    laugh = bool(LAUGH_RE.search(text)) or any(e.get("emojiId") in LAUGH_EMO or any(("草" in s or "笑" in s or "w" == s.strip(":").lower())
                                                                                    for s in e.get("shortcuts") or [] if isinstance(s, str)) for e in emo)
    return 2 if laugh else 1


def zlist(v):
    """並べた値の z(母標準偏差。ばらつきが無ければ 0)"""
    if not v:
        return []
    m = sum(v) / len(v)
    s = math.sqrt(sum((x - m) ** 2 for x in v) / len(v))
    return [(x - m) / s if s > 0 else 0.0 for x in v]


class ChatFeats:
    """文字の書き込みの時刻と笑いの印 [(秒, 笑いか)] -> 候補の区間の跳ねる箱の割合・笑いの書き込みの割合(研究の tools/hyp.py の _rate・_rate_live・_laugh と同じ数え方)"""

    def __init__(self, msgs):
        import bisect
        self._bisect = bisect
        ms = sorted((float(t), bool(l)) for t, l in msgs if t >= 0)
        self.ts = [t for t, _l in ms]
        self.lp = [0]
        for _t, l in ms:
            self.lp.append(self.lp[-1] + (1 if l else 0))
        n = int(self.ts[-1] // RERANK_BOX) + 1 if self.ts else 0
        self.cnt = [0] * n
        for t in self.ts:
            self.cnt[int(t // RERANK_BOX)] += 1
        self.med = max(1.0, median(self.cnt)) if self.cnt else 1.0

    def __bool__(self):
        return bool(self.ts)

    def rate(self, a, b, live=False):
        """跳ねる箱の割合。live = ふだんを候補の始まりより前の箱だけで(前が無ければ最初の箱)"""
        i0 = int(a // RERANK_BOX)
        med = self.med
        if live:
            past = self.cnt[:i0] or self.cnt[:1]
            med = max(1.0, median(past)) if past else 1.0
        hit = sum(1 for i in range(i0, min(len(self.cnt), int(b // RERANK_BOX) + 1)) if self.cnt[i] >= 2 * med)
        return hit / max(1.0, (b - a) / RERANK_BOX)

    def laugh(self, a, b):
        i, j = self._bisect.bisect_left(self.ts, a), self._bisect.bisect_left(self.ts, b)
        return (self.lp[j] - self.lp[i]) / max(1, j - i)


def rerank(cands, feats, k, live=False):
    """候補(点数の高い順に並べ替える)から k 本を、点の z + 重み × 跳ねる箱の割合の z + 重み × 笑いの割合の z の順で選ぶ -> (選んだ候補, 落とした候補)。
    選んだ候補には印 chatRank。feats が空(文字の書き込みが無い)なら点数の上から k 本のまま(印なし)。落とした候補 = 点数の上から k 本のうち選ばなかった物"""
    cs = sorted(cands, key=lambda c: -c["score"])
    if not feats or not cs:
        return cs[:k], []
    fb = [feats.rate(c["start"], c["end"], live) for c in cs]
    fl = [feats.laugh(c["start"], c["end"]) for c in cs]
    wb, wl = RERANK_W
    sc = [p + wb * q + wl * r for p, q, r in zip(zlist([c["score"] for c in cs]), zlist(fb), zlist(fl))]
    order = sorted(range(len(cs)), key=lambda i: -sc[i])
    keep = set(order[:k])
    out = []
    for i in order[:k]:
        c = dict(cs[i])
        c["chatRank"] = {"rate": round(fb[i], 3), "laugh": round(fl[i], 3), "z": round(sc[i], 3), "up": i >= k}
        out.append(c)
    return out, [cs[i] for i in range(min(k, len(cs))) if i not in keep]   # 落とした = 点数だけなら選ばれていた物


# ---------------------------------------------------------------- 一括の式(アーカイブの解析。golden で固定 = 式・加算の順・丸めを変えない)
def smooth(x, w):
    """幅 w 秒の移動平均(w は奇数に丸める)。"""
    n, h = len(x), max(0, int(w) // 2)
    if h == 0 or n == 0:
        return list(x)
    pre = [0.0]
    for v in x:
        pre.append(pre[-1] + v)
    return [(pre[min(n, i + h + 1)] - pre[max(0, i - h)]) / (min(n, i + h + 1) - max(0, i - h)) for i in range(n)]


def median(v):
    s = sorted(v)
    m = len(s)
    return 0.0 if not m else (s[m // 2] if m % 2 else (s[m // 2 - 1] + s[m // 2]) / 2)


def local_baseline(x, half=150, step=STEP, back=None, fwd=None):
    """各秒の前後 half 秒の中央値(=その場面の「ふだんの音量」)。step 秒ごとに求めて補間する。
    back・fwd を渡すと前後の幅を別にできる(配信中は back 270・fwd 30。既定は前後とも half)。"""
    n = len(x)
    if n == 0:
        return []
    back = half if back is None else back
    fwd = half if fwd is None else fwd
    pts = list(range(0, n, step)) + [n - 1]
    med = [median(x[max(0, p - back):p + fwd + 1]) for p in pts]
    out, j = [], 0
    for i in range(n):
        while j + 1 < len(pts) - 1 and pts[j + 1] <= i:
            j += 1
        a, b = pts[j], pts[min(j + 1, len(pts) - 1)]
        out.append(med[j] if b == a else med[j] + (med[min(j + 1, len(pts) - 1)] - med[j]) * (i - a) / (b - a))
    return out


def robust_scale(dev, floor):
    """偏差の「ふつうの大きさ」(MAD×1.4826)。極端に小さくならないよう floor を下限にする。"""
    m = median(dev)
    return max(floor, 1.4826 * median([abs(v - m) for v in dev]))


def audio_score(full_db, band_db):
    """音量が「ふだん」からどれだけ跳ね上がったか(標準偏差のような無単位の値。0〜CAP)。高音域(笑い声・叫び)は少し重く見る。"""
    out = []
    for raw, (w, wt) in zip((full_db, band_db), AUDIO_PARTS):
        series = smooth(raw, w)
        base = local_baseline(series)
        dev = [a - b for a, b in zip(series, base)]
        sc = robust_scale(dev, AUDIO_FLOOR)
        out.append([wt * max(0.0, min(CAP, d / sc)) for d in dev])
    return [a + b for a, b in zip(*out)]


def chat_z(act):
    """チャットの活気(9秒平均)が「ふだん」(前後 CHAT_HALF 秒)からどれだけ増えたか(ずらす前)。"""
    x = [math.log1p(v) for v in smooth(act, CHAT_SMOOTH)]
    base = local_baseline(x, half=CHAT_HALF)
    dev = [a - b for a, b in zip(x, base)]
    sc = robust_scale(dev, CHAT_FLOOR)
    return [max(0.0, min(CAP, d / sc)) for d in dev]


def shift_chat(z, lag):
    """反応は少し遅れて来るので、lag 秒だけ前へずらす(t 秒の値 = z[t+lag])。"""
    k = int(round(lag))
    return z[k:] + [0.0] * k if k > 0 else list(z)


def estimate_lag(audio, chat, max_lag=LAG_MAX):
    """音量の山とチャットの山の相関から、チャットが音声より何秒遅れているかを推定する。(遅れ秒, 一致度) / はっきりしなければ (None, 一致度)。
    配信ごとに、チャットの遅れ(視聴者の反応時間・配信の遅延)は違うため、固定値ではずれる。"""
    n = min(len(audio), len(chat))
    if n < 300:
        return None, 0.0
    a, c = audio[:n], chat[:n]
    ma, mc = sum(a) / n, sum(c) / n
    a = [x - ma for x in a]
    c = [x - mc for x in c]
    va, vc = sum(x * x for x in a), sum(x * x for x in c)
    if va <= 1e-9 or vc <= 1e-9:
        return None, 0.0
    norm = math.sqrt(va * vc)
    corr = []
    for k in range(max_lag + 1):
        corr.append(sum(a[i] * c[i + k] for i in range(n - k)) / norm)
    sm = [sum(corr[max(0, i - 1):i + 2]) / len(corr[max(0, i - 1):i + 2]) for i in range(len(corr))]   # 前後1秒でならす(1秒の揺れで選ばない)
    best = max(range(len(sm)), key=lambda i: sm[i])
    if sm[best] < LAG_MIN_CORR or sm[best] - min(sm) < LAG_MIN_CONTRAST:
        return None, sm[best]
    return best, sm[best]


def ramp(t, head):
    """冒頭の減点の倍率: 0秒で0倍 → head 秒で1倍へ、なだらかに(2乗)戻す(head_ramp と Online が同じ式を読む。head > 0 のときだけ呼ぶ)"""
    return min(1.0, t / head) ** 2


def head_ramp(total, head):
    """配信の冒頭(挨拶・BGM・雑談の始まり)の減点。0秒で0倍 → head 秒で1倍へ、なだらかに(2乗)戻す。"""
    if head <= 0:
        return total
    return [v * ramp(i, head) for i, v in enumerate(total)]


def comment_score(stamps, n, shape=None):
    """コメント欄の時刻 [(秒, いいね数[, 重み])] -> 1 秒ごとの点数。形は COMMENT_FORMS(既定 COMMENT_SHAPE)"""
    lo, hi, c, before, after = COMMENT_FORMS[shape or COMMENT_SHAPE]
    out = [0.0] * n
    for st in stamps:
        t, likes = st[0], st[1]
        amp = min(3.0, 0.8 + 0.5 * math.log1p(likes)) * (st[2] if len(st) > 2 else 1.0)
        for d in range(lo, hi + 1):
            i = int(t) + d
            if 0 <= i < n:
                x = d - c
                out[i] += amp * math.exp(-(x / (before if x < 0 else after)) ** 2)
    return [min(CAP, v) for v in out]


def peak_total(total, stamps, n, w):
    """山を選ぶ点数(PEAK_COMMENT): 冒頭の減点の前の合計 total から、コメントの分(w × 今の形)を重い形に差し替える。スイッチが None・書き込みが無ければ None"""
    if not PEAK_COMMENT or not stamps or w <= 0:
        return None
    f, shape = PEAK_COMMENT
    now, heavy = comment_score(stamps, n), comment_score(stamps, n, shape)
    return [total[i] + w * (f * heavy[i] - now[i]) for i in range(n)]


def pick_clips(total, level, spec, n, scene_total=None):
    """合計スコアの山を高い順に選び、区間(開始・終了)にする。見つけた区間は重ならない。
    spec の shape が "scene" なら区間は場面ごと(scene_region。取れなければ固定の長さ・spec の fallback が "auto" なら auto_length)で、
    候補に shape と固定の長さの区間 fixed も付ける。
    shape が無い・"fixed" なら 固定の形(golden で固定)。
    spec の fill(数)があれば、しきい値を超える山が fill 個に届かないとき、しきい値の下の山(点数が 0 より上)で fill 個まで埋める(印 fill。
    例: チャットが 0 件で音声だけ・山 1 つ。スイッチ FILL_ON)。
    scene_total を渡すと、山は total で選び、場面の区間は scene_total で取る(PEAK_COMMENT。選んだ区間はどちらも 0 にする)"""
    length, pre = spec["length"], spec["preRatio"]
    scene = spec.get("shape") == "scene"
    sp = scene_params(spec.get("scene")) if scene else None
    work = list(smooth(total, PICK_SMOOTH))
    swork = work if scene_total is None else list(smooth(scene_total, PICK_SMOOTH))
    thr = SENS[spec["sensitivity"]]
    out = []
    lows = smooth(level, LEVEL_SMOOTH)
    fill = min(int(spec.get("fill") or 0), spec["count"]) if FILL_ON else 0   # 本数に届かないときに埋める数(既定 0 = 埋めない = golden と同じ)
    auto = scene and spec.get("fallback") == "auto"   # 場面が取れないときも自動の長さ(AUTO_LEN_ON。測る道具は渡さない)

    def around(peak, ln):   # 山の前に pre 割を置いた長さ ln の区間を、声の途中で切らないよう近くの静かなところに合わせる
        s = max(0.0, min(peak - ln * pre, n - ln))
        e = min(float(n), s + ln)
        return snap_region(lows, max(0.0, e - ln), e, peak, n, ln)

    while len(out) < spec["count"]:
        peak = max(range(n), key=lambda i: work[i]) if n else 0
        below = bool(n) and work[peak] < thr   # しきい値の下 = ここから先は埋めるだけ(山は低い順にしか出ない)
        if not n or (below and (len(out) >= fill or work[peak] <= 0)):   # 埋めるのは点数が 0 より上の山だけ(平らな所は区間にしない)
            break
        s, e = around(peak, length)
        c = {"start": round(s, 1), "end": round(e, 1), "peak": peak, "score": round(work[peak], 2)}
        if below:
            c["fill"] = True   # 印: しきい値に届かない山で埋めた(測る道具はこの印で外せる)
        if scene:
            c["fixed"] = [c["start"], c["end"]]
            r = scene_region(swork, peak, n, sp)   # 前に選んだ区間は 0 = 場面はそこで止まる(区間が重なりにくい)
            if r is not None and not r["open"]:
                s, e = snap_region(lows, r["start"], r["end"], peak, n, r["end"] - r["start"])
                c.update(start=round(s, 1), end=round(e, 1), shape="scene")
            elif auto:   # 場面が取れない(山が平ら)= 同じ配信の場面の長さ(auto_length。固定の長さは使わない)
                s, e = around(peak, auto_length([x["end"] - x["start"] for x in out if x.get("shape") == "scene"]))
                c.update(start=round(s, 1), end=round(e, 1), shape="auto")
            else:
                c["shape"] = "fixed"   # 場面が取れない(山が平ら)= 長さの目安の固定の長さ(LD-2d)
        out.append(c)
        a, b = max(0, int(s) - EXCLUDE_BEFORE), min(n, int(e) + EXCLUDE_AFTER)
        for i in range(a, b):
            work[i] = swork[i] = 0.0
    if spec.get("join") and JOIN_ON:   # 割れた場面をつなぐ(JOIN_ON。測る道具は渡さない)
        out = join_clips(out)
    return sorted(out, key=lambda c: -c["score"])


def scene_params(over=None):
    """場面の形の数(SCENE)に上書き over(測る道具が試す値。知らない鍵・数でない値は捨てる)を重ねる"""
    p = dict(SCENE)
    for k, v in (over or {}).items() if isinstance(over, dict) else ():
        if k in p and isinstance(v, (int, float)) and not isinstance(v, bool):
            p[k] = type(SCENE[k])(v)
    return p


def scene_region(work, peak, n, p=None, off=0, upto=None):
    """山 peak の場面の区間(LD-2b)。work = ならした合計(smooth(total, 5))で、work[i - off] が秒 i の値(配信中は手元にある分だけ)。
    upto = 値がある最後の秒(配信中。None なら n - 1 まで)。
    -> {"start", "end", "rise", "settle", "open"} か None(山がふだんより高くない)。open = 収まりがまだ録れていない(配信中は後で取り直す)。
    上りの始まり rise・収まり settle は「ふだん + 割合 ×(山 − ふだん)」を hold 秒続けて下回る所の内側。区間 = rise − lead 〜 settle + tail を min〜max 秒に丸める
    (長すぎれば山を中に残して削る・短すぎれば前後に半分ずつ足す)"""
    p = p or SCENE
    upto = n - 1 if upto is None else min(n - 1, upto)
    hold, mx, mn = int(p["hold"]), float(p["max"]), float(p["min"])
    top = work[peak - off]
    before = work[max(0, peak - int(p["base"]) - off):max(0, peak - off)]
    base = sorted(before)[len(before) // 4] if before else 0.0   # 下から 4 分の 1(長い場面の中でも「ふだん」が山に引っ張られない)
    if top - base <= 1e-9:
        return None
    lv_r, lv_s = base + p["rise"] * (top - base), base + p["settle"] * (top - base)
    rise, below = peak, 0
    for j in range(peak - 1, max(off, int(peak - mx)) - 1, -1):
        if work[j - off] >= lv_r:
            rise, below = j, 0
        else:
            below += 1
            if below >= hold:
                break
    settle, below, closed = peak, 0, False
    hi = min(upto, int(peak + mx))
    for j in range(peak + 1, hi + 1):
        if work[j - off] >= lv_s:
            settle, below = j, 0
        else:
            below += 1
            if below >= hold:
                closed = True
                break
    open_ = not closed and hi < min(n - 1, int(peak + mx))   # 収まりも上限も、まだ録れていない
    s, e = rise - float(p["lead"]), settle + float(p["tail"])
    if e - s > mx:
        s = max(s, min(peak - mx / 2, e - mx))
        e = min(e, s + mx)
    elif e - s < mn:
        g = (mn - (e - s)) / 2
        s, e = s - g, e + g
    if s < 0:
        s, e = 0.0, min(float(n), e - s)
    if e > n:
        s, e = max(0.0, s - (e - n)), float(n)
    return {"start": float(s), "end": float(e), "rise": rise, "settle": settle, "open": open_}


def snap_region(lows, s, e, peak, n, length):
    """区間 [s, e] の両端を静かな所(snap_quiet)へ合わせる -> (開始, 終わり)。合わせた長さが length の SNAP_RATIO 倍の中で、
    山 peak を含むときだけ合わせ、違えば元の (s, e)(pick_clips と PeakBook._snap が同じ規則を読む)"""
    s2, e2 = snap_quiet(lows, s, n), snap_quiet(lows, e, n)
    if length * SNAP_RATIO[0] <= e2 - s2 <= length * SNAP_RATIO[1] and s2 < peak < e2:
        return s2, e2
    return s, e


def snap_quiet(level, t, n, radius=SNAP_RADIUS):
    """t の前後 radius 秒のうち、いちばん静かな秒(できるだけ近いもの)へ。"""
    lo, hi = max(0, int(t) - radius), min(n - 1, int(t) + radius)
    if hi < lo:
        return t
    best = min(range(lo, hi + 1), key=lambda i: (round(level[i], 0), abs(i - t)))
    return float(best)


def downsample(x, points=600):
    n = len(x)
    if n <= points:
        return [round(v, 2) for v in x]
    step = n / points
    return [round(max(x[int(i * step):max(int(i * step) + 1, int((i + 1) * step))]), 2) for i in range(points)]


def candidates(picks, comps):
    """選んだ区間に、山の前後の材料ごとの点数(parts)と理由の文を付ける(アーカイブの解析と配信中の候補で同じ)"""
    cands = []
    for i, c in enumerate(picks):
        pk = c["peak"]
        parts = {k: round(max(comps[k][max(0, pk - PARTS_RADIUS):pk + PARTS_RADIUS + 1]), 2) for k in comps}
        cand = {"i": i, "start": c["start"], "end": c["end"], "peak": pk, "score": c["score"], "parts": parts, "reasons": reasons_of(parts)}
        cand.update({k: c[k] for k in ("shape", "fixed", "joined", "pieces", "chatRank") if k in c})   # 場面ごとの形の印と固定の長さの区間(LD-2b)・つないだ元の範囲(無ければ足さない)
        if c.get("fill"):   # しきい値の下で埋めた(印と理由の文。理由の文はスタジオのマークにも残る)
            cand["fill"] = True
            cand["reasons"] = cand["reasons"] + [FILL_REASON]
        cands.append(cand)
    return cands


# 足しの候補(10-26 まとめ役・研究 C:/dev/overlap-research の tools/cand_extra.py。notes:plan/研究データの製品への活用-1025.md):
# アーカイブの解析で、今の候補(枠はそのまま・並びも変えない)の後ろに、YouTube の heatmap(よく見られている場面)の上位の山を HEAT_EXTRA 個まで足す。
# 学習に使っていない 38 区間で 使える 27 → 30・悪くなる区間 0・余分の秒ほぼ同じ(決まり「欠けを減らす方を取る」)。今の候補に入る山は足さない。
# heatmap は解析が既に取っている動画の情報(fetch.slim_meta の heatmap)だけを読む(問い合わせは増やさない。配信中・ライブ・数の少ない動画は無い = 今のまま)。
# 印 = 候補の origin "heatmap" と理由の文 HEAT_REASON。HEAT_EXTRA_ON = False で前の形。測り直し: 研究の B(配信全体の音での比べ)の結論が出たら・遅くとも 11-09
HEAT_EXTRA_ON = True
# 点に heatmap を足す(10-26 まとめ役・研究 C:/dev/overlap-research の excite_recheck の B「全部」= 今の点 + heatmap の z × 1.0。重みは研究で先に 1.0 と決めて
# 動かしていない。学んでいない 85 区間・78 配信で 今より 勝ち 39・負け 18(p 0.008)・使える 上位 3/8/20 0.35/0.50/0.67 → 0.41/0.62/0.82)。
# 材料 heat = heat_z(配信の中で平均 0・ばらつき 1 にそろえた 1 秒ごとの値)を重み HEAT_W で合計に入れる(点の内訳 parts の heat にも出る)。
# heatmap の無い・平らな配信は今のまま。HEAT_SCORE_ON = False で前の形。測り直し: 11-09
HEAT_SCORE_ON = True
HEAT_W = 1.0
HEAT_EXTRA = 8           # 足す山の数の上限
HEAT_SEP = 60            # 山どうしの間(秒。研究の peaks_top と同じ)
HEAT_PEAKS = 40          # 見る山の数(上から。今の候補に入る山も数える = 研究の peaks_top(hz, 40) と同じ)
HEAT_REASON = "YouTube でよく見られている場面"


def heat_z(heatmap, n):
    """heatmap([[始め, 終わり, 値], ...] = fetch.slim_meta の形)-> 1 秒ごとの値を配信の中で平均 0・ばらつき 1 にそろえた列(長さ n)か None(無い・平ら)。
    研究の scene4.heat_z と同じ数え方(区間の終わりの秒も含める)"""
    if not heatmap or n <= 0:
        return None
    v = [0.0] * n
    for h in heatmap:
        try:
            a, b, val = int(float(h[0])), int(float(h[1])), float(h[2])
        except (TypeError, ValueError, IndexError):
            continue
        for i in range(max(0, a), min(n, b + 1)):
            v[i] = val
    m = sum(v) / n
    sd = (sum((x - m) ** 2 for x in v) / n) ** 0.5
    if sd <= 1e-9:
        return None
    return [(x - m) / sd for x in v]


def heat_extra(cands, heatmap, n, comps, pre=PRE_RATIO_DEFAULT, k=HEAT_EXTRA, head=0):
    """今の候補 cands の後ろに heatmap([[始め, 終わり, 値 0〜1], ...] = fetch.slim_meta の形)の上位の山を k 個まで足す -> 候補(元の並びはそのまま)。
    足す区間の長さ = 今の候補の長さの中央・山の前に pre の割合。今の候補(と足した候補)に入る山・値が平らな heatmap は飛ばす。
    head = 冒頭の減点の秒(今の候補と同じ head_ramp。配信の頭は見始めの再生で heatmap が高くなりやすい)"""
    if not HEAT_EXTRA_ON or not cands or not heatmap or n <= 0:
        return cands
    v = [0.0] * n
    for h in heatmap:
        try:
            a, b, val = int(float(h[0])), int(float(h[1])), float(h[2])
        except (TypeError, ValueError, IndexError):
            continue
        for i in range(max(0, a), min(n, b + 1)):
            v[i] = val
    if max(v) - min(v) <= 1e-9:
        return cands
    lens = sorted(b - a for c in cands for a, b in (c.get("joined") or [(c["start"], c["end"])]))   # つないだ候補はつなぐ前の長さで(研究で測った形)
    length = lens[len(lens) // 2]
    sm = head_ramp(smooth(v, PICK_SMOOTH), head) if head else smooth(v, PICK_SMOOTH)
    out, peaks, added = list(cands), [], 0
    for i in sorted(range(n), key=lambda j: -sm[j]):
        if added >= k or len(peaks) >= HEAT_PEAKS or sm[i] <= 0:
            break
        if any(abs(i - j) <= HEAT_SEP for j in peaks) or i < head / 3.0:   # 頭の 3 分の 1(減点が 1 割未満の所)の山は足さない
            continue
        peaks.append(i)
        if any(c["start"] <= i <= c["end"] for c in out):
            continue
        added += 1
        a = max(0.0, i - pre * length)
        b = min(float(n), a + length)
        if any(min(b, c["end"]) - max(a, c["start"]) > 0.5 * (b - a) for c in out):   # 今の候補・足した候補と半分以上重なる(同じ場面の広い山)は足さない
            added -= 1
            continue
        parts = {kk: round(max(comps[kk][max(0, i - PARTS_RADIUS):i + PARTS_RADIUS + 1]), 2) for kk in comps}
        low = min(c.get("score") or 0.0 for c in cands)
        out.append({"i": len(out), "start": round(a, 1), "end": round(b, 1), "peak": i, "score": low, "parts": parts,
                    "reasons": [HEAT_REASON], "origin": "heatmap"})
    return out


def reasons_of(parts):
    """点数の内訳 → 理由の文(しきい値は PART_ON の 1 か所)"""
    why_txt = []
    if parts.get("audio", 0) >= PART_ON["audio"]:
        why_txt.append("音量が急上昇")
    if parts.get("chat", 0) >= PART_ON["chat"]:
        why_txt.append("チャットが急増")
    if parts.get("comments", 0) >= PART_ON["comments"]:
        why_txt.append("コメント欄で時刻が指定されている")
    if parts.get("heat", 0) >= PART_ON["heat"]:
        why_txt.append(HEAT_REASON)
    return why_txt or ["音声の変化"]


def message_weight(kind, text):
    """チャット 1 件の重み -> (重み, 「草」などの反応か, スパチャか)。kind は yt-dlp の item の鍵(CHAT_KINDS 以外は None = 数えない)"""
    if kind not in CHAT_KINDS:
        return None, False, False
    w = 1.0
    warm = bool(WARM_RE.search(text or ""))
    if warm:
        w += WARM_BONUS
    paid = kind in PAID_KINDS
    if paid:
        w += PAID_BONUS
    return w, warm, paid


def chat_messages(actions):
    """yt-dlp のチャットの actions -> 数える 1 件ずつの (renderer, 重み, 反応か, スパチャか)。数えない種類・形の合わない物は飛ばす。
    解析(analyze.parse_chat)と配信中(live_excite_worker.parse_chat_line)の共通の読み方"""
    for a in actions or []:
        item = ((a.get("addChatItemAction") or {}).get("item")) if isinstance(a, dict) else None
        if not isinstance(item, dict) or not item:
            continue
        kind, r = next(iter(item.items()))
        if not isinstance(r, dict):
            continue
        w, warm, paid = message_weight(kind, message_text(r))
        if w is not None:
            yield r, w, warm, paid


def message_text(renderer):
    """yt-dlp のチャットの renderer から本文(絵文字は shortcuts の先頭 2 つ + 短い emojiId)"""
    text = ""
    for run in (renderer.get("message") or {}).get("runs") or []:
        if "text" in run:
            text += str(run["text"])
        elif "emoji" in run:
            e = run["emoji"]
            text += " " + " ".join(str(x) for x in (e.get("shortcuts") or [])[:2]) + " " + str(e.get("emojiId", "") if len(str(e.get("emojiId", ""))) < 4 else "")
    return text


# ---------------------------------------------------------------- 配信中の式(窓つき)。1 秒ずつ確定させる Online
def _int_keys(d):
    """JSON で文字列になった秒・点の鍵を int に戻す(to_json / load の往復)"""
    return {int(k): v for k, v in (d or {}).items()}


def _drop_before(d, k0):
    """d(秒・点 -> 値)から、鍵が k0 より前のものを捨てる(窓の分だけ持つ)"""
    for k in [k for k in d if k < k0]:
        del d[k]


class _Channel:
    """Online の 1 本の系列(test_excite の windowed_scores と同じ式を、1 秒ずつ確定させる)。古い値は捨てる(メモリは窓の分だけ)"""

    def __init__(self, floor, w, back, fwd, window, step, log=False):
        self.floor, self.w, self.h = floor, w, max(0, int(w) // 2)
        self.back, self.fwd, self.window, self.step, self.log = back, fwd, window, step, log
        self.raw = []        # 絶対の秒 raw_base からの生の値
        self.raw_base = 0
        self.sm = {}         # 確定したならした値(絶対の秒 -> 値)
        self.med = {}        # 点 -> 中央値
        self.dev = {}        # 絶対の秒 -> 偏差
        self.scale = {}      # 点 -> 尺度
        self.n = 0           # 足した数(= 次の絶対の秒)
        self.next_out = 0    # 次に出す秒

    def push(self, v):
        """1 秒分を足す -> [(秒, 点数)](新しく確定した分)"""
        self.raw.append(float(v))
        self.n += 1
        i = self.n - 1 - self.h   # ならした値が確定する秒
        if i >= 0:
            lo = max(0, i - self.h)
            seg = self.raw[lo - self.raw_base:i + self.h + 1 - self.raw_base]
            s = sum(seg) / len(seg)
            self.sm[i] = math.log1p(s) if self.log else s
            p = (i - self.fwd)
            if p >= 0 and p % self.step == 0:   # 点 p の中央値が取れる(sm[p+fwd] が確定した)
                self.med[p] = median([self.sm[k] for k in range(max(0, p - self.back), p + self.fwd + 1) if k in self.sm])   # 無い秒 = 窓を広げる前の版の保存から続けた(その間だけ狭い窓)
        out = []
        while True:
            t = self.next_out
            p = (t // self.step) * self.step
            q = p + self.step
            if p not in self.med or q not in self.med:
                break
            base = self.med[p] + (self.med[q] - self.med[p]) * (t - p) / (q - p)
            self.dev[t] = self.sm[t] - base
            if p not in self.scale:
                self.scale[p] = robust_scale([self.dev[k] for k in range(max(0, p - self.window + 1), p + 1)], self.floor)
            out.append((t, max(0.0, min(CAP, self.dev[t] / self.scale[p]))))
            self.next_out = t + 1
        self._trim()
        return out

    def _trim(self):
        """使い終わった古い値を捨てる(raw は back + fwd + h、sm は back、dev は window、点は 2 つ分だけ残す)"""
        keep_from = max(0, self.next_out - self.back - self.fwd - self.step - 2 * self.h - 2)
        if keep_from - self.raw_base > 64:
            del self.raw[:keep_from - self.raw_base]
            self.raw_base = keep_from
        for d, margin in ((self.sm, self.back + self.step + 2), (self.dev, self.window + self.step + 2)):
            if len(d) > margin + 64:
                _drop_before(d, self.next_out - margin)
        for d in (self.med, self.scale):
            if len(d) > 8:
                _drop_before(d, (self.next_out // self.step) * self.step - 2 * self.step)

    def to_json(self):
        return {"raw": self.raw, "raw_base": self.raw_base, "sm": self.sm, "med": self.med, "dev": self.dev, "scale": self.scale,
                "n": self.n, "next_out": self.next_out}

    def load(self, d):
        self.raw, self.raw_base, self.n, self.next_out = list(d["raw"]), int(d["raw_base"]), int(d["n"]), int(d["next_out"])
        self.sm, self.med, self.dev, self.scale = _int_keys(d["sm"]), _int_keys(d["med"]), _int_keys(d["dev"]), _int_keys(d["scale"])


class Online:
    """配信中の合計の点数を 1 秒ずつ足す。audio_score(全体 0.6 + 高音域 0.4。floor 1.5 = AUDIO_PARTS・AUDIO_FLOOR)と
    chat_z(9 秒平均・log1p・floor 0.25 = CHAT_SMOOTH・CHAT_FLOOR。ふだんは前 chat_back 秒 = ONLINE_CHAT_BACK)の窓つき版を合わせ、
    チャットは lag 秒だけ前へずらし(t の値 = chat[t+lag])、重み(w_audio・w_chat)で足して head_ramp をかける。
    push(full, band, act) -> [(秒, 合計, {"audio": 音の点数, "chat": チャットの点数, "chatRaw": ずらす前のその秒のチャットの点数})]
    (新しく確定した秒。遅れは fwd + step + 4 + lag 秒ほど。chatRaw は遅れの推定 estimate_lag 用)。
    lag は set_lag で途中から変えられる(過去の秒は出し直さない)。to_json / load で途中から続けられる。"""

    def __init__(self, back=ONLINE_BACK, fwd=ONLINE_FWD, window=ONLINE_WINDOW, step=STEP, lag=8, w_audio=1.0, w_chat=1.0, head=180, use_chat=True,
                 chat_back=ONLINE_CHAT_BACK):
        self.ch_full = _Channel(AUDIO_FLOOR, AUDIO_PARTS[0][0], back, fwd, window, step)
        self.ch_band = _Channel(AUDIO_FLOOR, AUDIO_PARTS[1][0], back, fwd, window, step)
        self.ch_chat = _Channel(CHAT_FLOOR, CHAT_SMOOTH, chat_back, fwd, window, step, log=True) if use_chat else None
        self.lag = int(round(lag))
        self.w_audio, self.w_chat, self.head = float(w_audio), float(w_chat), int(head)
        self.full, self.band, self.chat = {}, {}, {}   # 確定したが、まだ合計にしていない秒
        self.next_out = 0

    def set_lag(self, lag):
        self.lag = max(0, int(round(lag)))

    def push(self, full_db, band_db, act=0.0):
        for t, v in self.ch_full.push(full_db):
            self.full[t] = AUDIO_PARTS[0][1] * v
        for t, v in self.ch_band.push(band_db):
            self.band[t] = AUDIO_PARTS[1][1] * v
        if self.ch_chat is not None:
            for t, v in self.ch_chat.push(act):
                self.chat[t] = v
        out = []
        while True:
            t = self.next_out
            if t not in self.full or t not in self.band:
                break
            if self.ch_chat is not None:
                if t + self.lag not in self.chat:
                    break
                c = self.chat[t + self.lag]
            else:
                c = 0.0
            a = self.full[t] + self.band[t]
            total = self.w_audio * a + self.w_chat * c
            if self.head > 0:
                total = total * ramp(t, self.head)
            out.append((t, total, {"audio": a, "chat": c, "chatRaw": self.chat.get(t, 0.0) if self.ch_chat is not None else 0.0}))
            self.next_out = t + 1
            del self.full[t], self.band[t]
            if self.ch_chat is not None:
                _drop_before(self.chat, t + 1)   # ずらした分より前は要らない
        return out

    def to_json(self):
        return {"v": 1, "lag": self.lag, "next_out": self.next_out, "full": self.full, "band": self.band, "chat": self.chat,
                "ch_full": self.ch_full.to_json(), "ch_band": self.ch_band.to_json(), "ch_chat": self.ch_chat.to_json() if self.ch_chat else None}

    def load(self, d):
        self.lag, self.next_out = int(d["lag"]), int(d["next_out"])
        self.full, self.band, self.chat = _int_keys(d["full"]), _int_keys(d["band"]), _int_keys(d["chat"])
        self.ch_full.load(d["ch_full"])
        self.ch_band.load(d["ch_band"])
        if self.ch_chat is not None and d.get("ch_chat"):
            self.ch_chat.load(d["ch_chat"])
        return self


# ---------------------------------------------------------------- 雰囲気の変わり目(0-10-5。配信中だけ)
MOOD_SEC = 300          # 「5 分の中央値」
MOOD_DB = 6.0           # 直近 MOOD_SEC 秒の中央値が、その前の MOOD_SEC 秒よりこれ以上動いたら変わり目
MOOD_REARM_DB = 4.0     # 一度変わり目にしたら、差がこれ未満に戻るまで次の変わり目にしない(同じ変わり目を何度も数えない)
MOOD_HOLD = 60          # 変わり目のあと、この秒数は
MOOD_FACTOR = 1.3       # 山のしきい値をこの倍にする(PeakBook.thr_scale)


class MoodShift:
    """配信の雰囲気の変わり目(ゲーム → 雑談 → 歌)を 1 秒ずつ見る(0-10-5): 音の全帯域(dB)の直近 sec 秒の中央値が、その前の sec 秒の中央値より
    db 以上動いたら変わり目。push(dB) -> その秒が変わり目なら True(差が rearm 未満に戻るまで次は出さない)。中央値は step 秒ごとに取る(軽く)。
    持つのは直近 2 × sec 秒の値だけ。to_json / load で続きから。変わり目のあとは「ふだん」(local_baseline)がまだ追いついていないので、
    呼ぶ側(配信中の検出のワーカー)が PeakBook.thr_scale でしきい値を上げる"""

    def __init__(self, sec=MOOD_SEC, db=MOOD_DB, rearm=MOOD_REARM_DB, step=STEP):
        self.sec, self.db, self.rearm, self.step = int(sec), float(db), float(rearm), int(step)
        self.vals = []      # 直近 2 × sec 秒の dB
        self.n = 0          # 足した数
        self.armed = True
        self.diff = 0.0     # 最後に測った差(dB)

    def push(self, db):
        self.vals.append(float(db))
        if len(self.vals) > 2 * self.sec:
            del self.vals[:len(self.vals) - 2 * self.sec]
        self.n += 1
        if self.n % self.step or len(self.vals) < 2 * self.sec:
            return False
        self.diff = abs(median(self.vals[self.sec:]) - median(self.vals[:self.sec]))
        if self.armed and self.diff >= self.db:
            self.armed = False
            return True
        if not self.armed and self.diff < self.rearm:
            self.armed = True
        return False

    def to_json(self):
        return {"vals": self.vals, "n": self.n, "armed": self.armed, "diff": self.diff}

    def load(self, d):
        self.vals = [float(v) for v in d.get("vals") or []][-2 * self.sec:]
        self.n, self.armed, self.diff = int(d.get("n") or 0), d.get("armed") is not False, float(d.get("diff") or 0.0)
        return self


# ---------------------------------------------------------------- 候補の帳簿(配信中)
CONFIRM_DROP = 0.6      # しきい値のこの割合を下回ったら「下り」
CONFIRM_LOW_SEC = 10    # 下りがこの秒数続いたら確定
CONFIRM_MAX_SEC = 90    # 上り始めてからこの秒数たったら確定
CHANGES_KEEP = 500
SCENE_N = 1 << 40       # 配信中の場面: 配信の長さはまだ分からない(scene_region の n)・開いている間の「次の山にしない」
SCENE_KEEP = int(SCENE["max"] + SCENE["base"] + 120)   # 場面の形のために持つならした点数の秒(山の前 max + base と確定までの遅れ)
PROV_EXPIRE = CONFIRM_MAX_SEC + 30   # 仮の候補の山から、本番の計算(チャット込み)がこれだけ進んでも近くで確定しなければ外す(本番の山の区間に含まれていた = 重なり)


class PeakBook:
    """配信中の候補の帳簿(0-10-3 の 5・6)。push(t, total, parts, level) に確定した秒の合計を 1 秒ずつ渡すと、山を見つけて候補にする。
    - 山: smooth(total, 5) がしきい値(SENS)を超えたら上り、超えた中で最大の秒を覚え、しきい値の 6 割を 10 秒下回る(か上り始めて 90 秒)で確定
    - 区間: pick_clips と同じ(長さ・前の割合・snap_quiet で静かな所へ。終わりがまだ無ければ endPending)。確定した区間の前後は次の山にしない。
      shape "scene"(LD-2b)なら場面ごと(scene_region。手元のならした点数 work から)。収まりがまだ録れていなければ sceneOpen・endPending のまま、
      録れたら区間を取り直す(その間は次の山にしない = 収まる前の上り下りは同じ場面)。候補に shape と固定の長さの区間 fixed を残す
    - 枠: 1 時間(録画の頭からの 1 時間ずつ)に per_hour 本。埋まっていたら、枠の中でいちばん低い点より高い新しい山と入れ替える(外れた方は控え)
    - 人が採用した候補(origin manual)は枠に数えない。見送りも数えない。自動で採用した候補(origin auto)は枠に数えたまま固定(入れ替えで外れない。仮決め (bl))
    - 変更の番号 seq: 新しい・枠と控えの移動・採用・見送り・区間の確定のたびに増える。changes と seq を記録へ書き、画面の 3 秒の見回りへの差分は flow/live_detect が作る
    - しきい値を上げる区間 thr_scale(t, 倍, 秒): 雰囲気の変わり目(MoodShift)のあと。上り始めの判定だけに効く(下りの判定・式は変えない)
    - 仮の候補(provisional。候補が出るまでの遅れを縮める): fast_push(t, 合計, 音の点数) に「音だけの先回りの計算」
      (チャットを待たない Online)の確定した秒を渡すと、上り始めた所で仮の候補(provisional: true・endPending: true = 採用できない・枠に数えない)を出し、
      音だけの山が確定したら区間を合わせ直す。本番の計算(push)が近く(確定した区間の前後 = 次の山にしない所)で確定したら、同じ id のまま本番の候補に
      置き換える(provisional: false)。PROV_EXPIRE 秒たっても置き換わらなければ見送り(expired: true)にする。仮の候補は一度に 1 つだけ。
      fast_push を呼ばなければ今までと同じ(本番の候補・枠の規則は変わらない)
    純粋(時計・ファイルを持たない)。to_json / from_json で起動し直しに耐える。"""

    def __init__(self, length=45, pre=PRE_RATIO_DEFAULT, sens="normal", per_hour=6, confirm_low=CONFIRM_LOW_SEC, shape="fixed", scene=None,
                 fallback=None, join=False, rerank=False):
        self.length, self.pre, self.thr, self.per_hour = float(length), float(pre), SENS[sens if sens in SENS else "normal"], int(per_hour)
        self.confirm_low = int(confirm_low)
        self.shape = shape if shape in SHAPES else "fixed"   # 区間の形(呼ぶ側がスイッチ SHAPE_DEFAULT か spec の shape を渡す。引数の既定は 0.88 までと同じ固定)
        self.scene = scene_params(scene)
        self.rerank = bool(rerank)   # チャットの跳ねと笑いで枠の入れ替え・控えから戻す順を決める(呼ぶ側がスイッチ CHAT_RERANK_ON を渡す。仮説 9)
        self.chat_boxes = {}   # 文字の書き込みの件数(RERANK_BOX 秒の箱 -> 件数。録画の頭から全部 = ふだんをその時点までで出す)
        self.chat_secs = {}    # 文字の書き込み(秒 -> [件数, 笑いの件数]。直近だけ)
        self.laugh_boxes = {}  # 笑いの書き込みの件数(RERANK_BOX 秒の箱 -> 件数。録画の頭から全部 = 笑いの収まり settle の印。flow/live_batch の縮め)
        self.join = bool(join)   # 割れた場面をつなぐ(呼ぶ側がスイッチ JOIN_ON を渡す。次の候補を作るときだけ・採用した候補は書き換えない)
        self.fallback = fallback if fallback == "auto" else None   # "auto" = 場面が取れないときも自動の長さ(auto_length。呼ぶ側がスイッチ AUTO_LEN_ON で渡す)
        self.work = {}        # 直近のならした合計(秒 -> smooth(5) の値)。場面の形用
        self.boost = []       # [[から, まで), 倍](しきい値を上げる区間。thr_scale)
        self.fast = self._fast_init()   # 音だけの先回りの計算の状態(仮の候補)
        self.peaks = {}       # id -> 候補
        self.order = []       # id の順(確定順)
        self.changes = []     # [(seq, id, state)]
        self.seq = 0
        self.n_ids = 0
        self.total = {}       # 直近の合計(秒 -> 値)。smooth(5) 用
        self.parts = {}       # 直近の内訳(秒 -> {audio, chat})
        self.level = {}       # 直近の音量(秒 -> dB)。snap_quiet 用
        self.last_t = -1
        self.rising = None    # {"since": 秒, "peak": 秒, "value": 値, "low": 下りの秒数}
        self.block_until = -1  # この秒までは次の山にしない(確定した区間の後ろ + EXCLUDE_AFTER)
        self.pending = []     # 終わりがまだ録れていない候補の id
        self.tag = None       # 新しく確定する本番の候補に足す印({"audioOnly": True} など。呼ぶ側が決める。保存しない = 呼ぶ側が毎回入れ直す)

    # ---- 1 秒ずつ
    def push(self, t, total, parts, level):
        """確定した秒 t の合計・内訳・音量(dB)を足す -> 変更があった候補の id の一覧"""
        t = int(t)
        self.total[t], self.parts[t], self.level[t] = float(total), dict(parts or {}), float(level)
        self.last_t = max(self.last_t, t)
        sm = self._smooth5(self.total, t)
        if sm:
            self.work[sm[0]] = sm[1]
        changed = self._step(*sm) if sm else []
        changed += self._finish_pending()
        changed += self._expire()
        self._trim()
        return changed

    @staticmethod
    def _smooth5(d, t):
        """秒 t まで足した値 d(秒 -> 値)から、smooth(・, PICK_SMOOTH = 5) が確定する秒 w = t - 2 とその値 -> (w, 値) か None(前後の値がそろっていない)"""
        h = PICK_SMOOTH // 2
        w = t - h
        ks = range(max(0, w - h), w + h + 1)
        if w < 0 or not all(k in d for k in ks):
            return None
        return w, sum(d[k] for k in ks) / len(ks)

    def _auto_len(self):
        """場面が取れないときの長さ(auto_length): この配信で取れた場面の長さから"""
        return auto_length([p["end"] - p["start"] for p in self.peaks.values() if p.get("shape") == "scene"])

    def _region(self, peak, length=None):
        """山の秒 -> 区間 (開始, 終わり)(長さ length(無ければ self.length)の pre 割を山の前に置く。頭は 0 で止める)"""
        length = self.length if length is None else length
        s = max(0.0, peak - length * self.pre)
        return s, s + length

    @staticmethod
    def _block_end(e):
        """区間の終わり e -> この秒までは次の山にしない(pick_clips の [s-5, e+6) と同じ: int(e)+6 から次の山にできる)"""
        return int(e) + EXCLUDE_AFTER - 1

    def _climb(self, r, w, work):
        """上り中の山 r(本番・仮の候補で同じ形)に秒 w の smooth(5) の値を足す -> 確定したか
        (しきい値の CONFIRM_DROP 割を confirm_low 秒続けて下回った・上り始めて CONFIRM_MAX_SEC 秒たった)"""
        if work > r["value"]:
            r["peak"], r["value"] = w, work
        r["low"] = r["low"] + 1 if work < self.thr * CONFIRM_DROP else 0
        return r["low"] >= self.confirm_low or w - r["since"] >= CONFIRM_MAX_SEC

    def thr_scale(self, t, factor=MOOD_FACTOR, sec=MOOD_HOLD):
        """秒 t から sec 秒の間、山の上り始めのしきい値を factor 倍にする(雰囲気の変わり目のあと。0-10-5)。重なれば大きい方"""
        self.boost.append([int(t), int(t) + int(sec), float(factor)])

    def _thr_at(self, w):
        return self.thr * max([b[2] for b in self.boost if b[0] <= w < b[1]] or [1.0])

    def _step(self, w, work):
        r = self.rising
        if r is None:
            if work >= self._thr_at(w) and w > self.block_until:
                self.rising = {"since": w, "peak": w, "value": work, "low": 0}
            return []
        if not self._climb(r, w, work):
            return []
        self.rising = None
        return self._confirm(r["peak"], r["value"], w)

    def _scene_at(self, peak):
        """手元のならした点数で山 peak の場面(scene_region の形か None)"""
        if not self.work:
            return None
        lo, hi = max(0, int(peak - self.scene["max"] - self.scene["base"])), max(self.work)
        if peak < lo or peak > hi:
            return None
        return scene_region([self.work.get(k, 0.0) for k in range(lo, hi + 1)], peak, SCENE_N, self.scene, off=lo, upto=hi)

    def _scene_fill(self, pk, r):
        """場面 r を候補 pk の区間に(開いている間は次の山にしない。つないだ候補は前の候補の始まりから)"""
        pk["start"], pk["end"] = round(min(r["start"], pk.get("joinFrom", r["start"])), 1), round(r["end"], 1)
        if pk.get("joined"):
            pk["joined"][-1] = [round(r["start"], 1), round(r["end"], 1)]
        pk["sceneOpen"] = r["open"]
        self.block_until = SCENE_N if r["open"] else self._block_end(r["end"])

    def _confirm(self, peak, value, now):
        """本番の山を候補にする(区間・枠。近くに仮の候補があれば同じ id のまま本番に置き換える)-> 変更があった候補の id の一覧"""
        s, e = fs, fe = self._region(peak)
        r = self._scene_at(peak) if self.shape == "scene" else None
        auto = self.shape == "scene" and r is None and self.fallback == "auto"
        if r is not None:
            s, e = r["start"], r["end"]
        elif auto:   # 場面が取れない = この配信で取れた場面の長さ(固定の長さは使わない)。前の候補の終わりより前へは伸ばさない(重ねない)
            ln = self._auto_len()
            prev = max([p["end"] for p in self.peaks.values() if not p.get("provisional") and p["end"] <= peak] or [0.0])
            s, e = self._region(peak, ln)
            if s < prev:
                s, e = prev, prev + ln
        self.block_until = SCENE_N if r is not None and r["open"] else self._block_end(e)
        prov = self._absorbable(s, e)
        prev = self._join_target(s, e) if prov is None and self.join and JOIN_ON else None
        if prev is not None:   # 割れた場面: 前の候補(まだ採用していない)へつなぐ
            return self._join(prev, s, e, peak, value, r)
        if prov is not None:
            self.fast["open"] = None
            if prov["state"] != "frame":   # 仮の候補のうちに人が決めた(採用・見送り): 区間と状態はそのまま、点数だけ本番の値に
                prov.update(score=round(value, 2), parts=self._parts_at(peak), confirmedAt=now, provisional=False, endPending=False)
                prov["reasons"] = reasons_of(prov["parts"])
                self._mark(prov["id"])
                return [prov["id"]]
            pk = prov   # 仮の候補を本番の候補に置き換える(同じ id。画面の行が入れ替わらない)
            pk["provisional"] = False
        else:
            pk = {"id": "p%d-%d" % (self.n_ids, peak)}
            self.n_ids += 1
            self.peaks[pk["id"]] = pk
            self.order.append(pk["id"])
        pk.update({"start": round(s, 1), "end": round(e, 1), "peak": peak, "score": round(value, 2), "parts": self._parts_at(peak),
                   "confirmedAt": now, "hour": peak // 3600, "state": "frame", "endPending": True, "origin": None, "seq": pk.get("seq", 0)})
        pk["reasons"] = reasons_of(pk["parts"])
        if self.tag:
            pk.update(self.tag)
        if self.shape == "scene":
            pk.update(shape="scene" if r is not None else "auto" if auto else "fixed", fixed=[round(fs, 1), round(fe, 1)], sceneOpen=bool(r and r["open"]))
        if not pk.get("sceneOpen"):
            self._snap(pk)
        self._place(pk)
        if pk["endPending"]:
            self.pending.append(pk["id"])
        self._mark(pk["id"])
        return [pk["id"]]

    def _join_target(self, s, e):
        """新しい本番の区間 [s, e] をつなぐ前の候補か None: いちばん後ろの本番の候補で、まだ採用・見送りしていない(frame・bench)・
        場面が閉じている・重なるか間 JOIN_GAP 秒以内・つないだ長さ JOIN_MAX 秒まで"""
        real = [p for p in self.peaks.values() if not p.get("provisional")]
        if not real:
            return None
        p = max(real, key=lambda p: p["start"])
        if p["state"] not in ("frame", "bench") or p.get("sceneOpen") or p["start"] > s:
            return None
        return p if s - p["end"] <= JOIN_GAP and max(p["end"], e) - p["start"] <= JOIN_MAX else None

    def _join(self, pk, s, e, peak, value, r):
        """前の候補 pk に新しい山 peak の区間 [s, e] をつなぐ(同じ id。点数は高い方・山と枠の時間は前のまま)-> 変更があった候補の id の一覧"""
        pk["joined"] = pk.get("joined", [[pk["start"], pk["end"]]]) + [[round(s, 1), round(e, 1)]]
        pk["joinFrom"] = pk.get("joinFrom", pk["start"])
        pk["pieces"] = pieces(pk) + 1   # 枠では元の本数と数える(つないで枠が空かない)
        pk["end"] = round(max(pk["end"], e), 1)
        if value > pk["score"]:
            pk.update(score=round(value, 2), parts=self._parts_at(peak))
            pk["reasons"] = reasons_of(pk["parts"])
        pk.pop("fill", None)
        if r is not None and r["open"]:   # 新しい場面の収まりを待つ(取り直しは新しい山で)
            pk.update(sceneOpen=True, scenePeak=peak, endPending=True)
        elif not self._snap(pk):
            pk["endPending"] = True
        if pk.get("endPending") and pk["id"] not in self.pending:
            self.pending.append(pk["id"])
        self._mark(pk["id"])
        return [pk["id"]]

    # ---- 仮の候補(音だけの先回りの計算。チャットを待たない)
    @staticmethod
    def _fast_init():
        return {"total": {}, "audio": {}, "rising": None, "open": None, "block": -1}

    def fast_push(self, t, total, audio=0.0):
        """音だけの先回りの計算(src/pipeline/analyze/live_excite_worker.py。チャットを待たない Online)の確定した秒 t の合計と音の点数を足す -> 変更があった候補の id。
        上り始め(smooth(5) が上り始めのしきい値以上・本番の確定した区間の外・仮の候補がまだ無い)で仮の候補を出し、音だけの山が確定したら区間を合わせ直す"""
        t = int(t)
        f = self.fast
        f["total"][t], f["audio"][t] = float(total), float(audio)
        sm = self._smooth5(f["total"], t)
        changed = self._fast_step(sm[0], sm[1], t) if sm else []
        for d in (f["total"], f["audio"]):
            _drop_before(d, t - 12)
        return changed

    def _fast_step(self, w, work, t):
        f = self.fast
        r = f["rising"]
        if r is None:
            if work >= self._thr_at(w) and w > max(self.block_until, f["block"]) and f["open"] is None:
                f["rising"] = {"since": w, "peak": w, "value": work, "low": 0, "audio": self._fast_audio(w - PARTS_RADIUS, t)}
                return [self._provisional(w, work, f["rising"]["audio"])]
            return []
        r["audio"] = max(r["audio"], self._fast_audio(w - PARTS_RADIUS, t))
        if not self._climb(r, w, work):
            return []
        f["rising"] = None
        f["block"] = self._block_end(self._region(r["peak"])[1])
        pk = self.peaks.get(f["open"]) if f["open"] else None
        if pk is None or not pk.get("provisional") or pk["state"] != "frame" or pk["peak"] == r["peak"]:
            return []
        self._prov_fill(pk, r["peak"], r["value"], r["audio"])   # 音だけの山が確定した: 区間を山に合わせ直す(まだ仮)
        self._mark(pk["id"])
        return [pk["id"]]

    def _fast_audio(self, a, b):
        return max([v for k, v in self.fast["audio"].items() if a <= k <= b] or [0.0])

    def _prov_fill(self, pk, peak, value, audio):
        s, e = self._region(peak, self._auto_len() if self.shape == "scene" and self.fallback == "auto" else None)   # 仮の区間も固定の長さを使わない
        pk.update({"start": round(s, 1), "end": round(e, 1), "peak": peak, "score": round(value, 2),
                   "parts": {"audio": round(audio, 2), "chat": 0.0}, "confirmedAt": peak, "hour": peak // 3600})
        pk["reasons"] = reasons_of(pk["parts"])

    def _provisional(self, w, work, audio):
        pid = "p%d-%d" % (self.n_ids, w)
        self.n_ids += 1
        pk = {"id": pid, "state": "frame", "endPending": True, "origin": None, "seq": 0, "provisional": True}
        self._prov_fill(pk, w, work, audio)
        self.peaks[pid] = pk
        self.order.append(pid)
        self.fast["open"] = pid
        self._mark(pid)
        return pid

    def _absorbable(self, s, e):
        """本番の候補 [s, e] の前後(次の山にしない所)に山がある仮の候補(まだ本番に置き換わっていないもの)か None"""
        pk = self.peaks.get(self.fast["open"]) if self.fast["open"] else None
        if pk is None or not pk.get("provisional"):
            return None
        return pk if s - EXCLUDE_BEFORE <= pk["peak"] < int(e) + EXCLUDE_AFTER else None

    def _expire(self, force=False):
        """本番の計算が仮の候補の山から PROV_EXPIRE 秒進んでも置き換わらない(本番では別の山の区間に入っていた)→ 見送り(expired)。force = 配信の終わり"""
        pid = self.fast["open"]
        pk = self.peaks.get(pid) if pid else None
        if pk is None or not pk.get("provisional"):
            self.fast["open"] = None
            return []
        r = self.rising
        if not force and (self.last_t - pk["peak"] < PROV_EXPIRE or (r is not None and r["since"] <= pk["peak"] + self.length)):
            return []
        self.fast["open"] = None
        pk["expired"], pk["endPending"] = True, False
        if pk["state"] == "frame":
            pk["state"] = "dismissed"
        self._mark(pid)
        return [pid]

    def _parts_at(self, peak):
        ks = sorted({k for p in self.parts.values() for k in p})
        return {k: round(max([self.parts[i].get(k, 0.0) for i in range(peak - PARTS_RADIUS, peak + PARTS_RADIUS + 1) if i in self.parts] or [0.0]), 2)
                for k in ks}

    def _snap(self, pk):
        """pick_clips と同じ区間の合わせ方(静かな所へ。snap_region)。終わりの音量がまだ無ければ endPending のまま"""
        s, e = float(pk["start"]), float(pk["end"])
        need = int(e) + SNAP_RADIUS + LEVEL_SMOOTH // 2   # snap_quiet(radius 4)+ smooth(level, 3)
        if self.last_t < need:
            return False
        lo = max(0, int(s) - SNAP_RADIUS - LEVEL_SMOOTH // 2)
        if not all(k in self.level for k in range(lo, need + 1)):   # 欠け(繋ぎ直し)で音量が無い所がある → 合わせずに確定
            pk["endPending"] = False
            return True
        n = need + 1
        lows = [0.0] * lo + smooth([self.level[k] for k in range(lo, n)], LEVEL_SMOOTH)   # 絶対の秒で引けるよう前を埋める(lo より前は見ない。lo の値だけ端で縮むが使わない)
        s2, e2 = snap_region(lows, s, e, pk["peak"], n, e - s if pk.get("shape") in ("scene", "auto") else self.length)
        pk["start"], pk["end"] = round(s2, 1), round(e2, 1)   # 合わせなかったときは元の値(round 済み)のまま
        pk["endPending"] = False
        self.block_until = max(self.block_until, self._block_end(pk["end"]))
        return True

    def finish(self):
        """配信が終わった(これ以上 push が来ない): 上り中の山を確定し、終わり待ちの候補を今の区間のまま確定する -> 変更があった候補の id の一覧。
        配信中の検出のワーカー(src/pipeline/analyze/live_excite_worker.py)が録画の終わりに 1 回だけ呼ぶ"""
        changed = []
        if self.rising is not None:
            r, self.rising = self.rising, None
            changed += self._confirm(r["peak"], r["value"], max(self.last_t, r["peak"]))
        for pid in list(self.pending):
            self.pending.remove(pid)
            pk = self.peaks[pid]
            if pk.get("sceneOpen"):   # 収まる前に配信が終わった: 今の場面のまま
                r = self._scene_at(pk.get("scenePeak", pk["peak"]))
                if r is not None:
                    self._scene_fill(pk, r)
                pk["sceneOpen"] = False
                self.block_until = self._block_end(pk["end"])
            pk["endPending"] = False
            self._mark(pid)
            changed.append(pid)
        self.fast["rising"] = None
        return changed + self._expire(force=True)

    def have(self):
        """本数に数える候補(実際に届く枠と採用だけ。控え・仮の候補・見送りは数えない = 10-24 決定・欠けを減らす方)の数"""
        return sum(pieces(pk) for pk in self.peaks.values() if pk["state"] in ("frame", "adopted") and not pk.get("provisional"))   # つないだ物は元の本数

    def fill_quota(self, total, level, comps, need):
        """配信の終わり(finish のあと)に、候補が need 本に届かなければ、しきい値の下の山を高い順に足して埋める -> 足した候補の id の一覧。
        total・level・comps({audio, chat})は録画の頭からの 1 秒ずつの合計・音量(dB)・内訳(配信中の series)。帳簿は直近しか持たないので呼ぶ側が渡す。
        今の候補(見送り・仮も)の区間とその前後(pick_clips の [s-5, e+6))と、そこから続く下りの裾の山は使わない。区間・内訳・理由はアーカイブの解析と同じ pick_clips・candidates で、
        印もアーカイブと同じ fill: True と理由の文 FILL_REASON。足した候補は 1 時間の枠を見ずに枠(frame)へ入れる(本数を埋めるための候補なので控えにしない)"""
        short = int(need) - self.have()
        n = len(total)
        if short <= 0 or n == 0:
            return []
        work = [float(v) for v in total]
        sm = smooth(work, PICK_SMOOTH)
        for pk in self.peaks.values():
            a, b = max(0, int(pk["start"]) - EXCLUDE_BEFORE), min(n, int(pk["end"]) + EXCLUDE_AFTER)
            while b < n and sm[b] <= sm[b - 1]:   # 頂が区間の中にある山の下りの裾も使わない(裾が区間のすぐ外の「山」に見えるため)
                b += 1
            while a > 0 and sm[a - 1] <= sm[a]:
                a -= 1
            for i in range(a, b):
                work[i] = 0.0
        spec = {"length": self.length, "preRatio": self.pre, "sensitivity": "normal", "count": short, "fill": short,
                "shape": self.shape, "scene": self.scene, "fallback": self.fallback, "join": self.join}
        def fit(x):
            return [float(v) for v in x][:n] + [0.0] * max(0, n - len(x))
        picks = pick_clips(work, fit(level), spec, n)
        for c in picks:
            c["fill"] = True   # 枠に入らなかった山 = 配信中のしきい値(気分の変わり目・音だけの倍を含む)に届かなかった山
        added = []
        for c in sorted(candidates(picks, {k: fit(v) for k, v in comps.items()}), key=lambda c: c["peak"]):
            pk = {"id": "p%d-%d" % (self.n_ids, c["peak"]), "start": c["start"], "end": c["end"], "peak": c["peak"], "score": c["score"],
                  "parts": c["parts"], "reasons": c["reasons"], "confirmedAt": self.last_t, "hour": c["peak"] // 3600, "state": "frame",
                  "endPending": False, "origin": None, "seq": 0, "fill": True}
            pk.update({k: c[k] for k in ("joined", "pieces") if k in c})   # 埋めた候補どうしをつないだ印と元の本数(枠・報告で元の本数と数える)
            if self.shape == "scene":
                pk.update(shape=c.get("shape", "fixed"), fixed=c.get("fixed", [c["start"], c["end"]]), sceneOpen=False)
            if self.tag:
                pk.update(self.tag)
            self.n_ids += 1
            self.peaks[pk["id"]] = pk
            self.order.append(pk["id"])
            self._mark(pk["id"])
            added.append(pk["id"])
        return added

    def _finish_pending(self):
        done = []
        for pid in list(self.pending):
            pk = self.peaks[pid]
            if pk.get("sceneOpen"):   # 場面の収まりを待つ: 録れたら区間を取り直す(まだなら終わりを伸ばして見せる)
                r = self._scene_at(pk.get("scenePeak", pk["peak"]))
                if r is None:
                    pk["sceneOpen"] = False
                    self.block_until = self._block_end(pk["end"])
                else:
                    moved = round(r["end"], 1) != pk["end"]
                    self._scene_fill(pk, r)
                    if r["open"]:
                        if moved:
                            self._mark(pid)
                            done.append(pid)
                        continue
            if self._snap(pk):
                self.pending.remove(pid)
                self._mark(pid)
                done.append(pid)
        return done

    # ---- 枠
    def _frame(self, hour):
        return [p for p in self.order if self.peaks[p]["hour"] == hour and self._counted(self.peaks[p])]

    def _load(self, ids):
        """枠の候補 ids を本数で(つないだ物は元の本数)"""
        return sum(pieces(self.peaks[p]) for p in ids)

    def _counted(self, pk):
        """枠に数える候補: 枠の中(frame。仮の候補は数えない)か、自動で採用した候補(枠に数えたまま固定)"""
        return (pk["state"] == "frame" and not pk.get("provisional")) or (pk["state"] == "adopted" and pk["origin"] == "auto")

    # ---- チャットの跳ねと笑い(rerank。仮説 9)
    def chat_note(self, sec, laugh):
        """文字の書き込み 1 件(録画の頭からの秒・笑いか)を数える(配信中の検出のワーカーが、チャットを受け取るたびに)"""
        if not self.rerank or sec < 0:
            return
        b = int(sec // RERANK_BOX)
        self.chat_boxes[b] = self.chat_boxes.get(b, 0) + 1
        if laugh:
            self.laugh_boxes[b] = self.laugh_boxes.get(b, 0) + 1
        s = self.chat_secs.setdefault(int(sec), [0, 0])
        s[0] += 1
        s[1] += 1 if laugh else 0

    def _chat_feat(self, pk):
        """候補の跳ねる箱の割合(ふだん = 始まりより前の箱の件数の中央値)と笑いの書き込みの割合 -> 印 chatRank に入れる。書き込みが無ければ何もしない"""
        if not self.rerank or not self.chat_boxes:
            return
        a, b = float(pk["start"]), float(pk["end"])
        i0, top = int(a // RERANK_BOX), max(self.chat_boxes) + 1
        past = [self.chat_boxes.get(i, 0) for i in range(min(i0, top))] or [self.chat_boxes.get(0, 0)]
        med = max(1.0, median(past))
        hit = sum(1 for i in range(i0, min(top, int(b // RERANK_BOX) + 1)) if self.chat_boxes.get(i, 0) >= 2 * med)
        n = l = 0
        for s in range(int(math.ceil(a)), int(math.ceil(b))):
            c = self.chat_secs.get(s)
            if c:
                n, l = n + c[0], l + c[1]
        pk["chatRank"] = {"rate": round(hit / max(1.0, (b - a) / RERANK_BOX), 3), "laugh": round(l / max(1, n), 3)}
        self._laugh_near(pk)

    def _laugh_near(self, pk):
        """印 chatRank.lc = 山の前後 LAUGH_NEAR 秒(区間の中)の笑いの書き込みの件数(研究の queue200_201.lc_scores。flow/live_batch の最終の候補の点)"""
        at = pk.get("peak") if isinstance(pk.get("peak"), (int, float)) else (pk["start"] + pk["end"]) / 2.0
        a, b = max(float(pk["start"]), at - LAUGH_NEAR), min(float(pk["end"]), at + LAUGH_NEAR)
        pk["chatRank"]["lc"] = sum(self.chat_secs[s][1] for s in range(int(math.ceil(a)), int(math.ceil(b))) if s in self.chat_secs) if b > a else 0

    def note_laughs(self):
        """印の付いた候補の笑いの件数(chatRank.lc)を数え直す(区間が後から決まる・書き込みが後から届く分。ワーカーが peaks.json を書く前に)。
        数える秒の頭がもう捨てた秒(_trim)なら前の値のまま"""
        if not self.rerank or not self.chat_secs:
            return
        lo = min(self.chat_secs)
        for pk in self.peaks.values():
            cr = pk.get("chatRank")
            if not isinstance(cr, dict):
                continue
            at = pk.get("peak") if isinstance(pk.get("peak"), (int, float)) else (pk["start"] + pk["end"]) / 2.0
            cr["settle"], cr["settleAll"] = self._settle(pk, True), self._settle(pk, False)   # 笑いの収まり(ふだん = 始まりより前 / 全部)
            if max(float(pk["start"]), at - LAUGH_NEAR) < lo and "lc" in cr:
                continue
            self._laugh_near(pk)

    def _settle(self, pk, live):
        """笑いの収まりの秒(研究の queue135_136.LiveSettle・queue25_28_30.Settle の「笑い」): 笑いの書き込みが ふだん × 2 以上の 10 秒の箱を跳ねとみなし、
        山の前後 SETTLE_NEAR 秒に跳ねがあれば、最後の跳ねから 1 箱までの切れ目を続きとみなして伸ばした終わり。ふだん = live なら始まりより前の箱の中央値・
        そうでなければその時までの全部の箱の中央値(1 未満は 1)。跳ねが無ければ None"""
        if not self.laugh_boxes:
            return None
        n = max(max(self.laugh_boxes), max(self.chat_boxes) if self.chat_boxes else 0) + 1
        lc = [self.laugh_boxes.get(i, 0) for i in range(n)]
        base_of = lc[:max(1, int(pk["start"] // RERANK_BOX))] if live else lc
        base = max(1.0, median(base_of))
        at = pk.get("peak") if isinstance(pk.get("peak"), (int, float)) else (pk["start"] + pk["end"]) / 2.0
        i0, i1 = max(0, int((at - SETTLE_NEAR) // RERANK_BOX)), min(n, int((at + SETTLE_NEAR) // RERANK_BOX) + 1)
        hits = [i for i in range(i0, i1) if lc[i] >= 2 * base]
        if not hits:
            return None
        j = max(hits)
        while True:
            if j + 1 < n and lc[j + 1] >= 2 * base:
                j += 1
            elif j + 2 < n and lc[j + 2] >= 2 * base:
                j += 2
            else:
                break
        return float((j + 1) * RERANK_BOX)

    def _rank(self):
        """枠の入れ替え・控えから戻す順の鍵 {id: (鍵, 点数)}: 点の z + 重み × 跳ねる箱の割合の z + 重み × 笑いの割合の z(z = この録画の本番の候補の中)。
        チャットの書き込みが無い・選び直さない(rerank でない)なら点数"""
        pool = [p for p in self.peaks.values() if not p.get("provisional") and "chatRank" in p]
        if not (self.rerank and CHAT_RERANK_ON and len(pool) >= 2):
            return {k: (p["score"], p["score"]) for k, p in self.peaks.items()}
        wb, wl = RERANK_W
        zs_, zb, zl = zlist([p["score"] for p in pool]), zlist([p["chatRank"]["rate"] for p in pool]), zlist([p["chatRank"]["laugh"] for p in pool])
        out = {k: (float("-inf"), p["score"]) for k, p in self.peaks.items()}   # 印の無い候補(書き込みが届く前)はいちばん後ろ
        for p, a, b, c in zip(pool, zs_, zb, zl):
            out[p["id"]] = (round(a + wb * b + wl * c, 6), p["score"])
            p["chatRank"]["z"] = round(a + wb * b + wl * c, 3)
        return out

    def _place(self, pk):
        """新しい候補を枠か控えへ。枠が埋まっていれば、いちばん低い(固定でない)候補より高ければ入れ替える(高い・低い = _rank の順)"""
        self._chat_feat(pk)
        frame = [p for p in self._frame(pk["hour"]) if p != pk["id"]]
        if self._load(frame) < self.per_hour:
            pk["state"] = "frame"
            return
        movable = [p for p in frame if self.peaks[p]["state"] == "frame"]
        rank = self._rank()
        low = min(movable, key=lambda p: rank[p]) if movable else None
        if low is not None and rank[low] < rank[pk["id"]]:
            self.peaks[low]["state"] = "bench"
            self._mark(low)
            pk["state"] = "frame"
        else:
            pk["state"] = "bench"

    def _refill(self, hour):
        """枠が空いたら(採用・見送り)、控えでいちばん高い候補を枠へ戻す"""
        while self._load(self._frame(hour)) < self.per_hour:
            bench = [p for p in self.order if self.peaks[p]["hour"] == hour and self.peaks[p]["state"] == "bench"]
            if not bench:
                break
            rank = self._rank()
            best = max(bench, key=lambda p: rank[p])
            self.peaks[best]["state"] = "frame"
            self._mark(best)

    def decide(self, pid, state, origin="manual", mark_id=None, job_id=None):
        """人の採用・見送り・戻す、自動の採用。state = adopted | dismissed | restore(控えか枠へ戻す)"""
        pk = self.peaks.get(pid)
        if not pk or (state == "restore" and pk.get("provisional")):   # 仮の候補(と、置き換わらずに外れたもの)は戻せない
            return None
        if state == "adopted":
            pk["state"], pk["origin"] = "adopted", origin if origin in ("manual", "auto") else "manual"
            if mark_id:
                pk["markId"] = mark_id
            if job_id:
                pk["jobId"] = job_id
        elif state == "dismissed":
            pk["state"], pk["origin"] = "dismissed", None
        elif state == "restore":
            pk["state"], pk["origin"] = "bench", None
            self._place(pk)
        else:
            return None
        self._mark(pid)
        self._refill(pk["hour"])
        return pk

    def _mark(self, pid):
        self.seq += 1
        self.peaks[pid]["seq"] = self.seq
        self.changes.append((self.seq, pid, self.peaks[pid]["state"]))
        if len(self.changes) > CHANGES_KEEP:
            del self.changes[:len(self.changes) - CHANGES_KEEP]

    # ---- 読む
    def counts(self):
        """1 時間ごとの枠の数 {時間: 本数}"""
        out = {}
        for p in self.order:
            pk = self.peaks[p]
            if self._counted(pk):
                out[pk["hour"]] = out.get(pk["hour"], 0) + pieces(pk)   # つないだ物は元の本数
        return out

    def list(self, include_bench=True):
        return [dict(self.peaks[p]) for p in self.order if include_bench or self.peaks[p]["state"] != "bench"]

    def _trim(self):
        keep = self.last_t - 200
        for d in (self.total, self.parts, self.level):
            if len(d) > 400:
                _drop_before(d, keep)
        if len(self.work) > SCENE_KEEP + 200:   # 場面の形は山の前 max + base 秒まで見る
            _drop_before(self.work, self.last_t - SCENE_KEEP)
        if len(self.chat_secs) > SCENE_KEEP + 600:   # 笑いの書き込みは、これから確定する候補の区間(山の前 max + base 秒まで)だけ
            _drop_before(self.chat_secs, self.last_t - SCENE_KEEP - 300)
        if self.boost and self.boost[0][1] < self.last_t - 10:   # 本番の計算(先回りより遅い)が過ぎた区間は要らない
            self.boost = [b for b in self.boost if b[1] >= self.last_t - 10]

    def to_json(self):
        return {"v": 1, "length": self.length, "pre": self.pre, "thr": self.thr, "per_hour": self.per_hour, "peaks": self.peaks, "order": self.order,
                "changes": self.changes, "seq": self.seq, "n_ids": self.n_ids, "last_t": self.last_t, "rising": self.rising,
                "block_until": self.block_until, "pending": self.pending,
                "total": self.total, "parts": self.parts, "level": self.level, "confirmLow": self.confirm_low, "boost": self.boost,
                "shape": self.shape, "scene": self.scene, "work": self.work, "fallback": self.fallback, "join": self.join,
                "rerank": self.rerank, "chatBoxes": self.chat_boxes, "chatSecs": self.chat_secs, "laughBoxes": self.laugh_boxes,
                "fast": dict(self.fast)}   # 鍵は total・audio・rising・open・block(_fast_init と from_json がこの 5 つだけを作る)

    @classmethod
    def from_json(cls, d):
        b = cls(d["length"], d["pre"], "normal", d["per_hour"], d.get("confirmLow", CONFIRM_LOW_SEC), d.get("shape", "fixed"), d.get("scene"),
                d.get("fallback"), d.get("join", False), d.get("rerank", False))
        b.chat_boxes = {int(k): int(v) for k, v in (d.get("chatBoxes") or {}).items()}
        b.laugh_boxes = {int(k): int(v) for k, v in (d.get("laughBoxes") or {}).items()}   # 0.99.367 までの保存には無い(笑いの収まりはその後の書き込みから)
        b.chat_secs = {int(k): [int(v[0]), int(v[1])] for k, v in (d.get("chatSecs") or {}).items()}   # 0.88 までの保存は固定の形・0.99.323 までの保存は fallback なし(場面が取れなければ固定の長さ)
        b.work = _int_keys(d.get("work"))
        b.thr = float(d["thr"])
        b.boost = [[int(x[0]), int(x[1]), float(x[2])] for x in d.get("boost") or []]
        f = d.get("fast") if isinstance(d.get("fast"), dict) else {}
        b.fast = {"total": _int_keys(f.get("total")), "audio": _int_keys(f.get("audio")),
                  "rising": dict(f["rising"]) if f.get("rising") else None, "open": f.get("open") or None, "block": int(f.get("block", -1))}
        b.peaks = {k: dict(v) for k, v in d["peaks"].items()}
        b.order, b.seq, b.n_ids, b.last_t = list(d["order"]), int(d["seq"]), int(d["n_ids"]), int(d["last_t"])
        b.changes = [tuple(c) for c in d["changes"]]
        b.rising = dict(d["rising"]) if d.get("rising") else None
        b.block_until, b.pending = int(d["block_until"]), list(d["pending"])
        b.total, b.parts, b.level = _int_keys(d["total"]), _int_keys(d["parts"]), _int_keys(d["level"])
        return b
