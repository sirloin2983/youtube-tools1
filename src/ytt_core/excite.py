"""盛り上がり(excitement)の式。スタジオのアーカイブの解析(src/studio/analyze.py)と、配信中の検出(src/home/live_excite_worker.py。線 D の L2)が同じ式を読む(線 D の L1。plan/line-d-detect.md)。

決まり:
- **一括の関数(smooth・local_baseline・robust_scale・audio_score・chat_z・estimate_lag・pick_clips …)は analyze.py から移しただけ**で、式・加算の順・丸めを変えていない。
  アーカイブの結果(候補・series)が移す前と完全に一致することを ytt_core/tests/test_excite.py の golden が確かめる。式を直すときは golden も作り直す(dev/eval_marks.py の数字と比べられなくなるので WORKLOG に書く)
- 配信中は「未来を見る量」だけが違う(plan/line-d-live-clipping.md の 0-10-2): ふだん = 前 back 秒・後 fwd 秒の中央値(アーカイブは 150/150、配信中は 270/30)、
  跳ね上がりの尺度 = 直近 window 秒の MAD(アーカイブは全体)。この 2 つを持つのが windowed_scores(一括)と Online(1 秒ずつ足す)。2 つは同じ値を返す(テストで確かめる)
- 候補の帳簿 PeakBook: 山の確定(0-10-3 の 5)・1 時間の枠と入れ替え(0-10-3 の 6)・採用と見送りの除外。純粋(時計・ファイルを持たない)で、JSON にして起動し直しに耐える
- 標準ライブラリだけ(numpy は使わない。入口の子プロセスでも足さずに済む)

使い方:
    from ytt_core import excite
    audio = excite.audio_score(full_db, band_db)                        # アーカイブ(今までどおり)
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
PRE_RATIO_DEFAULT = 0.65   # 山の位置(区間の何割を山の前に置くか)の既定。スタジオの設定 preRatio と dev/eval_marks.py が読む
PART_ON = {"audio": 1.5, "chat": 1.5, "comments": 0.8}   # 点数の内訳が「効いた」とみなす値(候補の理由の文と dev/eval_marks.py が同じ値を読む)
WARM_RE = re.compile(r"草|ｗ{2,}|w{3,}|笑|わら|8{3,}|８{3,}|！{2,}|!{2,}|すご|うま|上手|かわい|可愛|てぇてぇ|てえてえ|きた|キタ|やば|ヤバ|神|最高|えらい|www|lol|kusa|pog|LUL|😂|🤣|😆|😍|❤|💕|👏|🎉|:_?laugh|:_?kusa|:_?heart|:_?clap|:_?pog", re.I)
CHAT_KINDS = ("liveChatTextMessageRenderer", "liveChatPaidMessageRenderer", "liveChatPaidStickerRenderer", "liveChatMembershipItemRenderer")
PAID_KINDS = ("liveChatPaidMessageRenderer", "liveChatPaidStickerRenderer")
WARM_BONUS = 1.5   # 「草」などの反応の重み
PAID_BONUS = 4.0   # スーパーチャットは強い反応
ONLINE_BACK, ONLINE_FWD, ONLINE_WINDOW = 270, 30, 1800   # 配信中の既定(0-10-2)。アーカイブは back = fwd = 150・window = 全体
STEP = 10   # ふだんの中央値を取る間隔(秒)。local_baseline の step と同じ


# ---------------------------------------------------------------- 一括の式(analyze.py から移しただけ。変えない)
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
    back・fwd を渡すと前後の幅を別にできる(配信中は back 270・fwd 30。既定は今までどおり前後 half)。"""
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
    for series, wt in ((smooth(full_db, 3), 0.6), (smooth(band_db, 3), 0.4)):
        base = local_baseline(series)
        dev = [a - b for a, b in zip(series, base)]
        sc = robust_scale(dev, 1.5)
        out.append([wt * max(0.0, min(CAP, d / sc)) for d in dev])
    return [a + b for a, b in zip(*out)]


def chat_z(act):
    """チャットの活気(9秒平均)が「ふだん」からどれだけ増えたか(ずらす前)。"""
    x = [math.log1p(v) for v in smooth(act, 9)]
    base = local_baseline(x)
    dev = [a - b for a, b in zip(x, base)]
    sc = robust_scale(dev, 0.25)
    return [max(0.0, min(CAP, d / sc)) for d in dev]


def shift_chat(z, lag):
    """反応は少し遅れて来るので、lag 秒だけ前へずらす(t 秒の値 = z[t+lag])。"""
    k = int(round(lag))
    return z[k:] + [0.0] * k if k > 0 else list(z)


def chat_score(act, lag):   # lint: keep スタジオのテスト(test_analyze)が呼ぶ
    return shift_chat(chat_z(act), lag)


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


def head_ramp(total, head):
    """配信の冒頭(挨拶・BGM・雑談の始まり)の減点。0秒で0倍 → head 秒で1倍へ、なだらかに(2乗)戻す。"""
    if head <= 0:
        return total
    return [v * min(1.0, i / head) ** 2 for i, v in enumerate(total)]


def comment_score(stamps, n):
    out = [0.0] * n
    for st in stamps:
        t, likes = st[0], st[1]
        amp = min(3.0, 0.8 + 0.5 * math.log1p(likes)) * (st[2] if len(st) > 2 else 1.0)
        for d in range(-20, 21):
            i = int(t) + d
            if 0 <= i < n:
                out[i] += amp * math.exp(-(d / 8.0) ** 2)
    return [min(CAP, v) for v in out]


def pick_clips(total, level, spec, n):
    """合計スコアの山を高い順に選び、区間(開始・終了)にする。見つけた区間は重ならない。"""
    length, pre = spec["length"], spec["preRatio"]
    work = list(smooth(total, 5))
    thr = SENS[spec["sensitivity"]]
    out = []
    lows = smooth(level, 3)
    while len(out) < spec["count"]:
        peak = max(range(n), key=lambda i: work[i]) if n else 0
        if not n or work[peak] < thr:
            break
        s = max(0.0, min(peak - length * pre, n - length))
        e = min(float(n), s + length)
        s = max(0.0, e - length)
        s2 = snap_quiet(lows, s, n)   # 声の途中で切らないよう、近くの静かなところに合わせる
        e2 = snap_quiet(lows, e, n)
        if length * 0.7 <= e2 - s2 <= length * 1.3 and s2 < peak < e2:
            s, e = s2, e2
        out.append({"start": round(s, 1), "end": round(e, 1), "peak": peak, "score": round(work[peak], 2)})
        a, b = max(0, int(s) - 5), min(n, int(e) + 6)
        for i in range(a, b):
            work[i] = 0.0
    return sorted(out, key=lambda c: -c["score"])


def snap_quiet(level, t, n, radius=4):
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
        parts = {k: round(max(comps[k][max(0, pk - 6):pk + 7]), 2) for k in comps}
        cands.append({"i": i, "start": c["start"], "end": c["end"], "peak": pk, "score": c["score"], "parts": parts, "reasons": reasons_of(parts)})
    return cands


def reasons_of(parts):
    """点数の内訳 → 理由の文(しきい値は PART_ON の 1 か所)"""
    why_txt = []
    if parts.get("audio", 0) >= PART_ON["audio"]:
        why_txt.append("音量が急上昇")
    if parts.get("chat", 0) >= PART_ON["chat"]:
        why_txt.append("チャットが急増")
    if parts.get("comments", 0) >= PART_ON["comments"]:
        why_txt.append("コメント欄で時刻が指定されている")
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


# ---------------------------------------------------------------- 配信中の式(窓つき)。一括の windowed_scores と 1 秒ずつの Online は同じ値
def _mad_scale(vals, floor):
    return robust_scale(vals, floor)


def _points_upto(n, step):
    return range(0, n, step)


def windowed_scores(x, floor, w, back=ONLINE_BACK, fwd=ONLINE_FWD, window=ONLINE_WINDOW, step=STEP, log=False):
    """1 本の系列の、窓つきの点数(一括。Online の答え合わせ用)。
    smooth(w)(log なら log1p も)→ 点 p(step の倍数)ごとに x[p-back..p+fwd] の中央値を取り間を直線で補間 → 偏差 →
    点 p ごとに直近 window 秒の偏差の MAD(robust_scale)を尺度にして [p, p+step) に使う → clip(0, CAP)。
    値が確定するのは「次の点の中央値が取れる秒」まで(= 一括でも末尾の fwd + step 秒ほどは出さない)。-> [score](確定した秒の分だけ)"""
    n = len(x)
    h = max(0, int(w) // 2)
    sm = [sum(x[max(0, i - h):i + h + 1]) / (min(n, i + h + 1) - max(0, i - h)) for i in range(n)]   # smooth と同じ値(Online と同じ足し方で、末尾の桁までそろえる)
    if log:
        sm = [math.log1p(v) for v in sm]
    final_sm = n - h   # smooth は未来 h 秒が要る(末尾 h 個は一括では窓が縮むので、配信中と同じ「未確定」として捨てる)
    med = {}
    for p in _points_upto(final_sm, step):
        if p + fwd < final_sm:
            med[p] = median(sm[max(0, p - back):p + fwd + 1])
    out, dev, scale = [], [], {}
    for i in range(final_sm):
        p = (i // step) * step
        q = p + step
        if p not in med or q not in med:
            break
        base = med[p] + (med[q] - med[p]) * (i - p) / (q - p)
        dev.append(sm[i] - base)
        if p not in scale:
            if i != p:
                break   # 点 p の偏差が無い(来ない)
            scale[p] = _mad_scale(dev[max(0, p - window + 1):p + 1], floor)
        out.append(max(0.0, min(CAP, dev[i] / scale[p])))
    return out


class _Channel:
    """Online の 1 本の系列(windowed_scores と同じ式を、1 秒ずつ確定させる)。古い値は捨てる(メモリは窓の分だけ)"""

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
                self.med[p] = median([self.sm[k] for k in range(max(0, p - self.back), p + self.fwd + 1)])
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
                self.scale[p] = _mad_scale([self.dev[k] for k in range(max(0, p - self.window + 1), p + 1)], self.floor)
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
                floor_k = self.next_out - margin
                for k in [k for k in d if k < floor_k]:
                    del d[k]
        for d in (self.med, self.scale):
            if len(d) > 8:
                floor_p = (self.next_out // self.step) * self.step - 2 * self.step
                for k in [k for k in d if k < floor_p]:
                    del d[k]

    def to_json(self):
        return {"raw": self.raw, "raw_base": self.raw_base, "sm": self.sm, "med": self.med, "dev": self.dev, "scale": self.scale,
                "n": self.n, "next_out": self.next_out}

    def load(self, d):
        self.raw, self.raw_base, self.n, self.next_out = list(d["raw"]), int(d["raw_base"]), int(d["n"]), int(d["next_out"])
        self.sm = {int(k): v for k, v in d["sm"].items()}
        self.med = {int(k): v for k, v in d["med"].items()}
        self.dev = {int(k): v for k, v in d["dev"].items()}
        self.scale = {int(k): v for k, v in d["scale"].items()}


class Online:
    """配信中の合計の点数を 1 秒ずつ足す。audio_score(全体 0.6 + 高音域 0.4。floor 1.5)と chat_z(9 秒平均・log1p・floor 0.25)の窓つき版を合わせ、
    チャットは lag 秒だけ前へずらし(t の値 = chat[t+lag])、重み(w_audio・w_chat)で足して head_ramp をかける。
    push(full, band, act) -> [(秒, 合計, {"audio": 音の点数, "chat": チャットの点数})](新しく確定した秒。遅れは fwd + step + 4 + lag 秒ほど)。
    lag は set_lag で途中から変えられる(過去の秒は出し直さない)。to_json / from_json で途中から続けられる。"""

    def __init__(self, back=ONLINE_BACK, fwd=ONLINE_FWD, window=ONLINE_WINDOW, step=STEP, lag=8, w_audio=1.0, w_chat=1.0, head=180, use_chat=True):
        self.ch_full = _Channel(1.5, 3, back, fwd, window, step)
        self.ch_band = _Channel(1.5, 3, back, fwd, window, step)
        self.ch_chat = _Channel(0.25, 9, back, fwd, window, step, log=True) if use_chat else None
        self.lag = int(round(lag))
        self.w_audio, self.w_chat, self.head = float(w_audio), float(w_chat), int(head)
        self.full, self.band, self.chat = {}, {}, {}   # 確定したが、まだ合計にしていない秒
        self.next_out = 0

    def set_lag(self, lag):
        self.lag = max(0, int(round(lag)))

    def push(self, full_db, band_db, act=0.0):
        for t, v in self.ch_full.push(full_db):
            self.full[t] = 0.6 * v
        for t, v in self.ch_band.push(band_db):
            self.band[t] = 0.4 * v
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
                total = total * min(1.0, t / self.head) ** 2
            out.append((t, total, {"audio": a, "chat": c, "chatRaw": self.chat.get(t, 0.0) if self.ch_chat is not None else 0.0}))   # chatRaw = ずらす前の t の値(遅れの推定 estimate_lag 用)
            self.next_out = t + 1
            del self.full[t], self.band[t]
            if self.ch_chat is not None:
                for k in [k for k in self.chat if k < t + 1]:   # ずらした分より前は要らない
                    del self.chat[k]
        return out

    def to_json(self):
        return {"v": 1, "lag": self.lag, "next_out": self.next_out, "full": self.full, "band": self.band, "chat": self.chat,
                "ch_full": self.ch_full.to_json(), "ch_band": self.ch_band.to_json(), "ch_chat": self.ch_chat.to_json() if self.ch_chat else None}

    def load(self, d):
        self.lag, self.next_out = int(d["lag"]), int(d["next_out"])
        self.full = {int(k): v for k, v in d["full"].items()}
        self.band = {int(k): v for k, v in d["band"].items()}
        self.chat = {int(k): v for k, v in d["chat"].items()}
        self.ch_full.load(d["ch_full"])
        self.ch_band.load(d["ch_band"])
        if self.ch_chat is not None and d.get("ch_chat"):
            self.ch_chat.load(d["ch_chat"])
        return self


# ---------------------------------------------------------------- 候補の帳簿(配信中)
CONFIRM_DROP = 0.6      # しきい値のこの割合を下回ったら「下り」
CONFIRM_LOW_SEC = 10    # 下りがこの秒数続いたら確定
CONFIRM_MAX_SEC = 90    # 上り始めてからこの秒数たったら確定
EXCLUDE_BEFORE, EXCLUDE_AFTER = 5, 6   # 確定した区間の前後(pick_clips の [s-5, e+6) と同じ)
PEAK_STATES = ("frame", "bench", "adopted", "dismissed")
CHANGES_KEEP = 500


class PeakBook:
    """配信中の候補の帳簿(0-10-3 の 5・6)。push(t, total, parts, level) に確定した秒の合計を 1 秒ずつ渡すと、山を見つけて候補にする。
    - 山: smooth(total, 5) がしきい値(SENS)を超えたら上り、超えた中で最大の秒を覚え、しきい値の 6 割を 10 秒下回る(か上り始めて 90 秒)で確定
    - 区間: pick_clips と同じ(長さ・前の割合・snap_quiet で静かな所へ。終わりがまだ無ければ endPending)。確定した区間の前後は次の山にしない
    - 枠: 1 時間(録画の頭からの 1 時間ずつ)に per_hour 本。埋まっていたら、枠の中でいちばん低い点より高い新しい山と入れ替える(外れた方は控え)
    - 人が採用した候補(origin manual)は枠に数えない。見送りも数えない。自動で採用した候補(origin auto)は枠に数えたまま固定(入れ替えで外れない。仮決め (bl))
    - 変更の番号 seq: 新しい・枠と控えの移動・採用・見送り・区間の確定のたびに増える。changes_since(seq) で差分だけ返せる(画面の 3 秒の見回り用)
    純粋(時計・ファイルを持たない)。to_json / from_json で起動し直しに耐える。"""

    def __init__(self, length=45, pre=PRE_RATIO_DEFAULT, sens="normal", per_hour=6):
        self.length, self.pre, self.thr, self.per_hour = float(length), float(pre), SENS[sens if sens in SENS else "normal"], int(per_hour)
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

    # ---- 1 秒ずつ
    def push(self, t, total, parts, level):
        """確定した秒 t の合計・内訳・音量(dB)を足す -> 変更があった候補の id の一覧"""
        t = int(t)
        self.total[t], self.parts[t], self.level[t] = float(total), dict(parts or {}), float(level)
        self.last_t = max(self.last_t, t)
        changed = []
        w = t - 2   # smooth(total, 5) が確定する秒
        if w >= 0 and all(k in self.total for k in range(max(0, w - 2), w + 3)):
            seg = [self.total[k] for k in range(max(0, w - 2), w + 3)]
            work = sum(seg) / len(seg)
            changed += self._step(w, work)
        changed += self._finish_pending()
        self._trim()
        return changed

    def _step(self, w, work):
        if self.rising is None:
            if work >= self.thr and w > self.block_until:
                self.rising = {"since": w, "peak": w, "value": work, "low": 0}
            return []
        r = self.rising
        if work > r["value"]:
            r["peak"], r["value"] = w, work
        if work < self.thr * CONFIRM_DROP:
            r["low"] += 1
        else:
            r["low"] = 0
        if r["low"] >= CONFIRM_LOW_SEC or w - r["since"] >= CONFIRM_MAX_SEC:
            self.rising = None
            return self._confirm(r["peak"], r["value"], w)
        return []

    def _confirm(self, peak, value, now):
        s = max(0.0, peak - self.length * self.pre)
        e = s + self.length
        pid = "p%d-%d" % (self.n_ids, peak)
        self.n_ids += 1
        pk = {"id": pid, "start": round(s, 1), "end": round(e, 1), "peak": peak, "score": round(value, 2), "parts": self._parts_at(peak),
              "confirmedAt": now, "hour": peak // 3600, "state": "frame", "endPending": True, "origin": None, "seq": 0}
        pk["reasons"] = reasons_of(pk["parts"])
        self.peaks[pid] = pk
        self.order.append(pid)
        self.block_until = int(e) + EXCLUDE_AFTER - 1   # pick_clips の [s-5, e+6) と同じ: int(e)+6 から次の山にできる
        changed = [pid]
        self._snap(pk)
        self._place(pk)
        if pk["endPending"]:
            self.pending.append(pid)
        self._mark(pid)
        return changed

    def _parts_at(self, peak):
        ks = sorted({k for p in self.parts.values() for k in p})
        return {k: round(max([self.parts[i].get(k, 0.0) for i in range(peak - 6, peak + 7) if i in self.parts] or [0.0]), 2) for k in ks}

    def _snap(self, pk):
        """pick_clips と同じ区間の合わせ方(静かな所へ)。終わりの音量がまだ無ければ endPending のまま"""
        s, e = float(pk["start"]), float(pk["end"])
        need = int(e) + 4 + 1   # snap_quiet(radius 4)+ smooth(level, 3)
        if self.last_t < need:
            return False
        lo = max(0, int(s) - 4 - 1)
        if not all(k in self.level for k in range(lo, need + 1)):   # 欠け(繋ぎ直し)で音量が無い所がある → 合わせずに確定
            pk["endPending"] = False
            return True
        n = need + 1
        lows = [0.0] * lo + smooth([self.level[k] for k in range(lo, n)], 3)   # 絶対の秒で引けるよう前を埋める(lo より前は見ない。lo の値だけ端で縮むが使わない)
        s2 = snap_quiet(lows, s, n)
        e2 = snap_quiet(lows, e, n)
        if self.length * 0.7 <= e2 - s2 <= self.length * 1.3 and s2 < pk["peak"] < e2:
            pk["start"], pk["end"] = round(s2, 1), round(e2, 1)
        pk["endPending"] = False
        self.block_until = max(self.block_until, int(pk["end"]) + EXCLUDE_AFTER - 1)
        return True

    def finish(self):
        """配信が終わった(これ以上 push が来ない): 上り中の山を確定し、終わり待ちの候補を今の区間のまま確定する -> 変更があった候補の id の一覧。
        配信中の検出のワーカー(src/home/live_excite_worker.py)が録画の終わりに 1 回だけ呼ぶ"""
        changed = []
        if self.rising is not None:
            r, self.rising = self.rising, None
            changed += self._confirm(r["peak"], r["value"], max(self.last_t, r["peak"]))
        for pid in list(self.pending):
            self.pending.remove(pid)
            self.peaks[pid]["endPending"] = False
            self._mark(pid)
            changed.append(pid)
        return changed

    def _finish_pending(self):
        done = []
        for pid in list(self.pending):
            pk = self.peaks[pid]
            if self._snap(pk):
                self.pending.remove(pid)
                self._mark(pid)
                done.append(pid)
        return done

    # ---- 枠
    def _frame(self, hour):
        return [p for p in self.order if self.peaks[p]["hour"] == hour and self._counted(self.peaks[p])]

    def _counted(self, pk):
        """枠に数える候補: 枠の中(frame)か、自動で採用した候補(枠に数えたまま固定)"""
        return pk["state"] == "frame" or (pk["state"] == "adopted" and pk["origin"] == "auto")

    def _place(self, pk):
        """新しい候補を枠か控えへ。枠が埋まっていれば、いちばん低い(固定でない)候補より高ければ入れ替える"""
        frame = [p for p in self._frame(pk["hour"]) if p != pk["id"]]
        if len(frame) < self.per_hour:
            pk["state"] = "frame"
            return
        movable = [p for p in frame if self.peaks[p]["state"] == "frame"]
        low = min(movable, key=lambda p: self.peaks[p]["score"]) if movable else None
        if low is not None and self.peaks[low]["score"] < pk["score"]:
            self.peaks[low]["state"] = "bench"
            self._mark(low)
            pk["state"] = "frame"
        else:
            pk["state"] = "bench"

    def _refill(self, hour):
        """枠が空いたら(採用・見送り)、控えでいちばん高い候補を枠へ戻す"""
        while len(self._frame(hour)) < self.per_hour:
            bench = [p for p in self.order if self.peaks[p]["hour"] == hour and self.peaks[p]["state"] == "bench"]
            if not bench:
                break
            best = max(bench, key=lambda p: self.peaks[p]["score"])
            self.peaks[best]["state"] = "frame"
            self._mark(best)

    def decide(self, pid, state, origin="manual", mark_id=None, job_id=None):
        """人の採用・見送り・戻す、自動の採用。state = adopted | dismissed | restore(控えか枠へ戻す)"""
        pk = self.peaks.get(pid)
        if not pk:
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
    def changes_since(self, seq):
        """seq より後の変更 [(seq, id, state)]。古すぎて残っていなければ None(全部を取り直す)"""
        if self.changes and seq < self.changes[0][0] - 1 and seq < self.seq:
            return None
        return [c for c in self.changes if c[0] > seq]

    def counts(self):
        """1 時間ごとの枠の数 {時間: 本数}"""
        out = {}
        for p in self.order:
            pk = self.peaks[p]
            if self._counted(pk):
                out[pk["hour"]] = out.get(pk["hour"], 0) + 1
        return out

    def list(self, include_bench=True):
        return [dict(self.peaks[p]) for p in self.order if include_bench or self.peaks[p]["state"] != "bench"]

    def _trim(self):
        keep = self.last_t - 200
        for d in (self.total, self.parts, self.level):
            if len(d) > 400:
                for k in [k for k in d if k < keep]:
                    del d[k]

    def to_json(self):
        return {"v": 1, "length": self.length, "pre": self.pre, "thr": self.thr, "per_hour": self.per_hour, "peaks": self.peaks, "order": self.order,
                "changes": self.changes, "seq": self.seq, "n_ids": self.n_ids, "last_t": self.last_t, "rising": self.rising,
                "block_until": self.block_until, "pending": self.pending,
                "total": self.total, "parts": self.parts, "level": self.level}

    @classmethod
    def from_json(cls, d):
        b = cls(d["length"], d["pre"], "normal", d["per_hour"])
        b.thr = float(d["thr"])
        b.peaks = {k: dict(v) for k, v in d["peaks"].items()}
        b.order, b.seq, b.n_ids, b.last_t = list(d["order"]), int(d["seq"]), int(d["n_ids"]), int(d["last_t"])
        b.changes = [tuple(c) for c in d["changes"]]
        b.rising = dict(d["rising"]) if d.get("rising") else None
        b.block_until, b.pending = int(d["block_until"]), list(d["pending"])
        b.total = {int(k): v for k, v in d["total"].items()}
        b.parts = {int(k): v for k, v in d["parts"].items()}
        b.level = {int(k): v for k, v in d["level"].items()}
        return b
