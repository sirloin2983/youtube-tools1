# -*- coding: utf-8 -*-
"""pipeline/analyze/excite.py(盛り上がりの式)のテスト。  py -3.12 -m unittest src/pipeline/analyze/tests/test_excite.py -v
本物の音とチャットのファイルを通す解析の通しは test_analyze.TestAnalyzeRun(チャットの種類ごとの重み・埋めの印・場面ごとの区間の形もそこ)。
ここは通しでは見えない物: 式の値を桁まで(golden)・2 つの計算の比べ・配信中の帳簿の規則(時間・人の決定)
- golden: 同じ合成の入力で出した値(data/excite_golden.json)と一致する(式を変えたら作り直す)
- Online(1 秒ずつ)= windowed_scores(一括。同じ窓。この下で定義)
- PeakBook(候補の帳簿)の規則: 確定・1 時間の枠・入れ替え・採用は数えない・見送りは外す・JSON の往復
- 配信中だけの足し: しきい値を上げる区間(thr_scale)・仮の候補(fast_push。同じ id で本番に置き換わる・外れる・人の決定)・
  雰囲気の変わり目(MoodShift)
"""
import os
os.environ.setdefault("YTT_DATA_DIR", "inplace")   # 作業データは読み書きしないが、ほかのテストとそろえる
import json
import math
import random
import sys
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))   # tests の 3 つ上 = src
sys.path.insert(0, REPO)
from pipeline.analyze import excite  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))


def windowed_scores(x, floor, w, back=excite.ONLINE_BACK, fwd=excite.ONLINE_FWD, window=excite.ONLINE_WINDOW, step=excite.STEP, log=False):
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
    for p in range(0, final_sm, step):
        if p + fwd < final_sm:
            med[p] = excite.median(sm[max(0, p - back):p + fwd + 1])
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
            scale[p] = excite.robust_scale(dev[max(0, p - window + 1):p + 1], floor)
        out.append(max(0.0, min(excite.CAP, dev[i] / scale[p])))
    return out

GOLDEN = os.path.join(HERE, "data", "excite_golden.json")
SPEC = {"length": 45, "preRatio": 0.65, "sensitivity": "normal", "count": 8}
STAMPS = [(100, 5), (250, 40, 0.5), (390, 0)]


def synth(seed, n=2400, lag=11):
    """合成の 1 秒の系列(音量 dB・高音域 dB・チャットの活気)。山が 6 つ、チャットは lag 秒遅れて増える。seed で決まる"""
    rnd = random.Random(seed)
    full = [-30.0 + rnd.gauss(0, 1.2) for _ in range(n)]
    band = [-42.0 + rnd.gauss(0, 1.5) for _ in range(n)]
    act = [max(0.0, rnd.gauss(2.0, 1.0)) for _ in range(n)]
    for k in range(6):
        c = 200 + k * 360 + rnd.randint(-30, 30)
        amp = 6.0 + k * 1.5
        for d in range(-12, 13):
            g = math.exp(-(d / 5.0) ** 2)
            if 0 <= c + d < n:
                full[c + d] += amp * g
                band[c + d] += (amp + 3) * g
            if 0 <= c + d + lag < n:
                act[c + d + lag] += 20 * g * (1 + k * 0.3)
    return full, band, act


class TestGolden(unittest.TestCase):
    """golden(synth(7) から計算した値)と完全に同じ値。式を直したら、このクラスが読む鍵を新しい式で計算して data/excite_golden.json を書き直す"""

    @classmethod
    def setUpClass(cls):
        with open(GOLDEN, encoding="utf-8") as f:
            cls.g = json.load(f)
        cls.full, cls.band, cls.act = synth(7)

    def same(self, a, b):
        self.assertEqual(len(a), len(b))
        for i, (x, y) in enumerate(zip(a, b)):
            self.assertAlmostEqual(x, y, places=9, msg="index %d" % i)

    def test_audio_chat_total_candidates(self):
        g, n = self.g, self.g["n"]
        self.assertEqual(len(self.full), n)
        audio = excite.audio_score(self.full, self.band)
        self.same(audio, g["audio"])
        cz = excite.chat_z(self.act)
        self.same(cz, g["chat_z"])
        est, corr = excite.estimate_lag(audio, cz)
        self.assertEqual(est, g["lag"][0])
        self.assertAlmostEqual(corr, g["lag"][1], places=9)
        chat = excite.shift_chat(cz, g["lag_used"])
        total = excite.head_ramp([audio[i] + chat[i] for i in range(n)], 180)
        self.same(total, g["total"])
        picks = excite.pick_clips(total, self.full, SPEC, n)
        self.assertEqual(picks, g["picks"])
        self.assertEqual(excite.candidates(picks, {"audio": audio, "chat": chat}), g["candidates"])
        self.assertEqual(excite.downsample(total, 100), g["downsample"])

    def test_small_functions(self):
        g = self.g
        self.same(excite.smooth(g["total"][:50], 5), g["smooth5"])
        self.assertAlmostEqual(excite.median(self.full[:101]), g["median"], places=12)
        self.same(excite.local_baseline(self.full[:700]), g["baseline"])
        self.assertAlmostEqual(excite.robust_scale([v - 1.0 for v in self.band[:500]], 1.5), g["scale"], places=12)
        n = len(self.full)
        self.assertEqual([excite.snap_quiet(excite.smooth(self.full, 3), t, n) for t in (0.0, 12.0, 333.3, float(n - 1))], g["snap"])
        self.same(excite.comment_score(STAMPS, 400), g["comment"])

    def test_helpers_and_constants(self):
        """1 か所にまとめた数字と小さな関数(snap_region・ramp・_drop_before)"""
        self.assertEqual([excite.ramp(t, 180) for t in (0, 90, 180, 400)], [0.0, 0.25, 1.0, 1.0])
        self.assertEqual(excite.head_ramp([2.0, 2.0, 2.0], 2), [2.0 * excite.ramp(i, 2) for i in range(3)])
        lows = [5.0] * 100
        lows[18], lows[62] = 0.0, 0.0                               # 静かな所
        self.assertEqual(excite.snap_region(lows, 20.0, 60.0, 40, 100, 40), (18.0, 62.0))   # 両端を静かな所へ
        self.assertEqual(excite.snap_region(lows, 20.0, 60.0, 62, 100, 40), (20.0, 60.0))   # 合わせた区間が山を含まなければ元のまま
        self.assertEqual(excite.snap_region(lows, 20.0, 60.0, 40, 100, 20), (20.0, 60.0))   # 長さが 0.7〜1.3 倍の外なら元のまま
        d = {1: "a", 5: "b", 9: "c"}
        excite._drop_before(d, 5)
        self.assertEqual(d, {5: "b", 9: "c"})

    def test_baseline_back_fwd_default_is_same(self):
        x = self.full[:500]
        self.same(excite.local_baseline(x, back=150, fwd=150), excite.local_baseline(x))
        a = excite.local_baseline(x, back=270, fwd=30)
        self.assertEqual(len(a), 500)
        self.assertNotEqual(a, excite.local_baseline(x))


class TestOnline(unittest.TestCase):
    """1 秒ずつ足す Online が、同じ窓の一括(windowed_scores)と同じ値を出す"""

    def test_channel_equals_batch(self):
        full, band, act = synth(3, n=4200)
        for x, floor, w, log in ((full, excite.AUDIO_FLOOR, excite.AUDIO_PARTS[0][0], False), (act, excite.CHAT_FLOOR, excite.CHAT_SMOOTH, True)):
            batch = windowed_scores(x, floor, w, back=270, fwd=30, window=600, log=log)
            ch = excite._Channel(floor, w, 270, 30, 600, excite.STEP, log=log)
            got = []
            for v in x:
                got += ch.push(v)
            self.assertGreater(len(batch), 4000)
            self.assertEqual([t for t, _ in got], list(range(len(got))))
            self.assertEqual(len(got), len(batch))
            for (t, v), b in zip(got, batch):
                self.assertAlmostEqual(v, b, places=12, msg="t=%d" % t)
            self.assertLess(len(ch.raw), 270 + 30 + 10 + 2 * 4 + 2 + 64 + 64)   # 古い値は捨てている(back + fwd + step + 2h + 2 に、64 個ずつ捨てる分の余り)
            self.assertLess(len(ch.dev), 600 + 10 + 2 + 64 + 64)

    def test_online_total_and_resume(self):
        full, band, act = synth(5, n=3000)
        on = excite.Online(back=270, fwd=30, window=600, lag=11)
        out = []
        snap = None
        for i in range(len(full)):
            out += on.push(full[i], band[i], act[i])
            if i == 1500:
                snap = json.loads(json.dumps(on.to_json()))
        self.assertEqual([t for t, _, _ in out], list(range(len(out))))
        self.assertGreater(len(out), 2900)
        # 同じ値を一括で
        (w_full, wt_full), (w_band, wt_band) = excite.AUDIO_PARTS   # 式の数字は excite の 1 か所(値は golden が守る)
        a = windowed_scores(full, excite.AUDIO_FLOOR, w_full, back=270, fwd=30, window=600)
        b = windowed_scores(band, excite.AUDIO_FLOOR, w_band, back=270, fwd=30, window=600)
        c = windowed_scores(act, excite.CHAT_FLOOR, excite.CHAT_SMOOTH, back=270, fwd=30, window=600, log=True)
        for t, total, parts in out:
            ref_a = wt_full * a[t] + wt_band * b[t]
            ref = (ref_a + c[t + 11]) * excite.ramp(t, 180)
            self.assertAlmostEqual(total, ref, places=12, msg="t=%d" % t)
            self.assertAlmostEqual(parts["audio"], ref_a, places=12)
        # 途中の状態から続けても同じ
        on2 = excite.Online(back=270, fwd=30, window=600, lag=11).load(snap)
        out2 = []
        for i in range(1501, len(full)):
            out2 += on2.push(full[i], band[i], act[i])
        tail = [o for o in out if o[0] >= out2[0][0]]
        self.assertEqual(len(out2), len(tail))
        for (t1, v1, _), (t2, v2, _) in zip(out2, tail):
            self.assertEqual(t1, t2)
            self.assertAlmostEqual(v1, v2, places=12)

    def test_no_chat_and_lag_change(self):
        full, band, act = synth(9, n=1200)
        on = excite.Online(back=100, fwd=30, window=300, use_chat=False, head=0)
        out = []
        for i in range(len(full)):
            out += on.push(full[i], band[i])
        self.assertTrue(all(p["chat"] == 0.0 for _, _, p in out))
        on = excite.Online(back=100, fwd=30, window=300, lag=5, head=0)
        n1 = 0
        for i in range(len(full)):
            got = on.push(full[i], band[i], act[i])
            n1 += len(got)
            if i == 600:
                on.set_lag(8)
        self.assertGreater(n1, 1000)


def feed(book, total, level, parts=None, start=0):
    changed = []
    for t in range(start, len(total)):
        changed += book.push(t, total[t], parts[t] if parts else {"audio": total[t], "chat": 0.0}, level[t])
    return changed


def series_with_peaks(peaks, n, amp=5.0, width=6):
    total = [0.0] * n
    for c, a in peaks:
        for d in range(-width * 3, width * 3 + 1):
            if 0 <= c + d < n:
                total[c + d] += (a if a is not None else amp) * math.exp(-(d / float(width)) ** 2)
    return total


class TestPeakBook(unittest.TestCase):
    def test_confirm_and_region(self):
        n = 600
        total = series_with_peaks([(200, 5.0)], n)
        level = [-30.0] * n
        level[172] = -45.0   # 静かな所(開始の近く)
        book = excite.PeakBook(length=45, pre=0.65, sens="normal", per_hour=6)
        changed = feed(book, total, level)
        pk = book.list()
        self.assertEqual(len(pk), 1)
        p = pk[0]
        self.assertEqual(p["peak"], 200)
        self.assertEqual(p["state"], "frame")
        self.assertFalse(p["endPending"])
        self.assertEqual(p["start"], 171.0)   # 170.75 → 静かな秒(171〜173 が同じ静かさ。いちばん近い 171)へ
        self.assertEqual(p["end"], 216.0)     # 215.75 → いちばん近い秒
        self.assertTrue(p["start"] < 200 < p["end"])
        self.assertGreaterEqual(p["confirmedAt"], 200 + 10)
        self.assertLess(p["confirmedAt"], 200 + 90)
        self.assertEqual(p["reasons"], ["音量が急上昇"])
        self.assertIn(p["id"], changed)
        self.assertEqual(book.counts(), {0: 1})

    def test_end_pending_then_fixed(self):
        n = 250   # 山 230 は t=249 で確定し、区間の終わり(245.75)+ 5 秒の音量はまだ無い
        total = series_with_peaks([(230, 5.0)], n)
        level = [-30.0] * n
        book = excite.PeakBook(length=45, pre=0.65)
        feed(book, total, level)
        p = book.list()[0]
        self.assertTrue(p["endPending"])   # 終わり(≈ 245)までの音量がまだ無い
        seq0 = book.seq
        feed(book, [0.0] * 300, [-30.0] * 300, start=n)
        p = book.list()[0]
        self.assertFalse(p["endPending"])
        self.assertGreater(book.seq, seq0)

    def test_quota_replace_adopt_dismiss(self):
        n = 3600
        peaks = [(300 + k * 400, 3.0 + k * 0.5) for k in range(8)]   # 8 つ(点数は後ろほど高い)
        total = series_with_peaks(peaks, n)
        level = [-30.0] * n
        book = excite.PeakBook(length=45, pre=0.65, per_hour=3)
        feed(book, total, level)
        allp = book.list()
        self.assertEqual(len(allp), 8)
        frame = [p for p in allp if p["state"] == "frame"]
        bench = [p for p in allp if p["state"] == "bench"]
        self.assertEqual(len(frame), 3)
        self.assertEqual(len(bench), 5)
        self.assertEqual(sorted(p["peak"] for p in frame), [300 + k * 400 for k in (5, 6, 7)])   # 高い 3 つが枠
        self.assertEqual(book.counts(), {0: 3})
        # 人が採用 → 枠に数えない → 控えの最高が枠へ
        top = max(frame, key=lambda p: p["score"])
        book.decide(top["id"], "adopted", origin="manual", mark_id="m1", job_id="j1")
        self.assertEqual(book.peaks[top["id"]]["state"], "adopted")
        self.assertEqual(book.peaks[top["id"]]["markId"], "m1")
        frame = [p for p in book.list() if p["state"] == "frame"]
        self.assertEqual(len(frame), 3)
        self.assertIn(300 + 4 * 400, [p["peak"] for p in frame])
        # 自動で採用 → 枠に数えたまま固定
        auto = frame[0]
        book.decide(auto["id"], "adopted", origin="auto")
        self.assertEqual(book.counts(), {0: 3})
        # 見送り → 枠から外れ、控えが上がる
        other = [p for p in book.list() if p["state"] == "frame"][0]
        book.decide(other["id"], "dismissed")
        self.assertEqual(book.peaks[other["id"]]["state"], "dismissed")
        self.assertEqual(book.counts(), {0: 3})
        # 戻す → 控えへ(枠が埋まっているので)
        book.decide(other["id"], "restore")
        self.assertIn(book.peaks[other["id"]]["state"], ("bench", "frame"))
        # 差分
        self.assertEqual(book.changes[-1][0], book.seq)
        # JSON の往復
        b2 = excite.PeakBook.from_json(json.loads(json.dumps(book.to_json())))
        self.assertEqual(b2.list(), book.list())
        self.assertEqual(b2.counts(), book.counts())
        self.assertEqual([tuple(c) for c in b2.changes], [tuple(c) for c in book.changes])

    def test_hours_and_exclusion(self):
        n = 7400
        total = series_with_peaks([(100, 5.0), (120, 9.0), (3700, 4.0)], n)   # 100 と 120 は 1 つの山(確定した区間の後ろは次の山にしない)
        level = [-30.0] * n
        book = excite.PeakBook(length=45, pre=0.65, per_hour=6)
        feed(book, total, level)
        ps = book.list()
        self.assertEqual([p["hour"] for p in ps], [0, 1])
        self.assertEqual(ps[0]["peak"], 120)
        self.assertEqual(book.counts(), {0: 1, 1: 1})

    def test_resume_mid_rise(self):
        n = 400
        total = series_with_peaks([(200, 5.0)], n)
        level = [-30.0] * n
        book = excite.PeakBook()
        feed(book, total[:205], level[:205])
        self.assertIsNotNone(book.rising)
        b2 = excite.PeakBook.from_json(json.loads(json.dumps(book.to_json())))
        feed(b2, total, level, start=205)
        self.assertEqual(len(b2.list()), 1)
        self.assertEqual(b2.list()[0]["peak"], 200)

    def test_thr_scale_only_for_the_window(self):
        """雰囲気の変わり目のあと(thr_scale)は上り始めのしきい値が 1.3 倍: しきい値の 1.1 倍ほどの山は、その間だけ候補にならない。JSON の往復でも残る"""
        n = 600
        total = series_with_peaks([(200, 2.4)], n)   # smooth(5) の山 ≈ 2.27(normal のしきい値 2.0 より上・2.6 より下)
        level = [-30.0] * n
        plain = excite.PeakBook()
        feed(plain, total, level)
        self.assertEqual([p["peak"] for p in plain.list()], [200])
        boosted = excite.PeakBook()
        boosted.thr_scale(150, excite.MOOD_FACTOR, excite.MOOD_HOLD)   # 150〜210 秒は 2.6
        feed(boosted, total[:160], level[:160])
        boosted = excite.PeakBook.from_json(json.loads(json.dumps(boosted.to_json())))
        self.assertEqual(boosted.boost, [[150, 210, 1.3]])
        feed(boosted, total, level, start=160)
        self.assertEqual(boosted.list(), [])
        later = excite.PeakBook()
        later.thr_scale(300, 1.3, 60)   # 山より後の区間は効かない
        feed(later, total, level)
        self.assertEqual([p["peak"] for p in later.list()], [200])
        self.assertEqual(later.boost, [], "過ぎた区間は捨てる")


def feed_two(book, audio, chat, level, lead, upto=None, start=0, stop_at=None):
    """先回り(音だけ)を lead 秒先に、本番(音 + チャット)を後から足す(ワーカーと同じ順)。stop_at(t) が真になったら止めて t を返す"""
    n = len(audio)
    end = n + lead if upto is None else upto
    for t in range(start, end):
        if t < n:
            book.fast_push(t, audio[t], audio[t])
        m = t - lead
        if 0 <= m < n:
            book.push(m, audio[m] + chat[m], {"audio": audio[m], "chat": chat[m]}, level[m])
        if stop_at is not None and stop_at(book):
            return t + 1
    return end


class TestProvisional(unittest.TestCase):
    """仮の候補(音だけの先回り。候補が出るまでの遅れを縮める): 上り始めで出る → 音だけの山で合わせ直す → 本番が同じ id で置き換える / 置き換わらなければ外れる"""
    LEAD = 40

    def setUp(self):
        self.n = 800
        self.audio = series_with_peaks([(200, 5.0)], self.n)
        self.chat = series_with_peaks([(206, 2.0)], self.n)
        self.level = [-30.0] * self.n

    def test_appears_early_then_replaced_with_same_id(self):
        book = excite.PeakBook()
        t = feed_two(book, self.audio, self.chat, self.level, self.LEAD, stop_at=lambda b: b.peaks)
        self.assertLess(t, 200 + 5, "上り始めで出る")
        p = book.list()[0]
        self.assertEqual((p["provisional"], p["endPending"], p["state"]), (True, True, "frame"))
        self.assertEqual(book.counts(), {}, "仮の候補は枠に数えない")
        self.assertLessEqual(abs(p["peak"] - 200), 15)
        # 途中で JSON にしても続く(先回りの上り・開いている仮の候補)
        book = excite.PeakBook.from_json(json.loads(json.dumps(book.to_json())))
        t = feed_two(book, self.audio, self.chat, self.level, self.LEAD, start=t, stop_at=lambda b: b.fast["rising"] is None)
        p = book.list()[0]
        self.assertTrue(p["provisional"])
        self.assertEqual(p["peak"], 200, "音だけの山が確定したら合わせ直す")
        feed_two(book, self.audio, self.chat, self.level, self.LEAD, start=t)
        ps = book.list()
        self.assertEqual(len(ps), 1, ps)
        p = ps[0]
        self.assertEqual((p["provisional"], p["endPending"], p["state"]), (False, False, "frame"))
        self.assertEqual(book.counts(), {0: 1})
        # 本番だけ(先回りなし)と同じ区間・点数
        ref = excite.PeakBook()
        for m in range(self.n):
            ref.push(m, self.audio[m] + self.chat[m], {"audio": self.audio[m], "chat": self.chat[m]}, self.level[m])
        r = ref.list()[0]
        self.assertEqual([p[k] for k in ("start", "end", "peak", "score", "parts", "confirmedAt", "hour")],
                         [r[k] for k in ("start", "end", "peak", "score", "parts", "confirmedAt", "hour")])

    def test_expires_when_final_never_comes(self):
        """本番では山にならなかった(ここでは本番に 0 を渡す)→ PROV_EXPIRE 秒たったら見送り(expired)・戻せない"""
        book = excite.PeakBook()
        for t in range(self.n):
            book.fast_push(t, self.audio[t], self.audio[t])
            if t >= self.LEAD:
                book.push(t - self.LEAD, 0.0, {"audio": 0.0, "chat": 0.0}, -30.0)
        p = book.list()[0]
        self.assertEqual((p["state"], p["expired"], p["endPending"], p["provisional"]), ("dismissed", True, False, True))
        self.assertIsNone(book.fast["open"])
        self.assertIsNone(book.decide(p["id"], "restore"))
        self.assertEqual(book.counts(), {})

    def test_human_decision_on_provisional_keeps_region(self):
        """仮の候補を人が採用した(画面では押せないが API では来うる)→ 本番が確定しても区間と状態はそのまま、点数だけ本番の値に"""
        book = excite.PeakBook()
        t = feed_two(book, self.audio, self.chat, self.level, self.LEAD, stop_at=lambda b: b.peaks)
        pid = book.list()[0]["id"]
        book.decide(pid, "adopted", origin="manual", mark_id="m1")
        region = (book.peaks[pid]["start"], book.peaks[pid]["end"])
        feed_two(book, self.audio, self.chat, self.level, self.LEAD, start=t)
        p = book.peaks[pid]
        self.assertEqual((p["state"], p["origin"], p["markId"], p["provisional"], (p["start"], p["end"])), ("adopted", "manual", "m1", False, region))
        self.assertGreater(p["score"], 4.0)
        self.assertEqual(len(book.list()), 1)

    def test_finish_expires_open_provisional(self):
        book = excite.PeakBook()
        feed_two(book, self.audio, self.chat, self.level, self.LEAD, upto=215)   # 本番はまだ 175 秒まで
        self.assertTrue(book.list()[0]["provisional"])
        book.finish()
        p = book.list()[0]
        self.assertEqual((p["state"], p.get("expired")), ("dismissed", True))


class TestMoodShift(unittest.TestCase):
    """雰囲気の変わり目: 全帯域の直近 5 分の中央値が前の 5 分より 6dB 以上動いたら 1 回(差が戻るまで次は出さない)"""

    @staticmethod
    def series():
        rnd = random.Random(4)
        out = []
        for i in range(2700):
            base = -20.0 if 900 <= i < 1800 else -30.0   # 900 秒で +10dB・1800 秒で -10dB
            out.append(base + rnd.uniform(-0.3, 0.3))
        return out

    def test_shift_up_and_down(self):
        ms = excite.MoodShift()
        hits = [i for i, v in enumerate(self.series()) if ms.push(v)]
        self.assertEqual(len(hits), 2, hits)
        self.assertTrue(1045 <= hits[0] <= 1065, hits)   # 新しい値が直近 5 分の半分を超えた所(10 秒ごとに見る)
        self.assertTrue(1945 <= hits[1] <= 1965, hits)

    def test_small_change_and_resume(self):
        ms = excite.MoodShift()
        self.assertFalse(any(ms.push(-30.0 + (4.0 if i >= 900 else 0.0)) for i in range(1800)), "4dB は変わり目にしない")
        a = excite.MoodShift()
        s = self.series()
        hits = []
        for i, v in enumerate(s[:1000]):
            if a.push(v):
                hits.append(i)
        b = excite.MoodShift().load(json.loads(json.dumps(a.to_json())))
        for i, v in enumerate(s[1000:], 1000):
            if b.push(v):
                hits.append(i)
        ref = excite.MoodShift()
        self.assertEqual(hits, [i for i, v in enumerate(s) if ref.push(v)])
        self.assertLessEqual(len(b.vals), 2 * excite.MOOD_SEC)


def bump(n, c, amp, width, base=0.0):
    """合計の点数の合成: 平らな base に、秒 c を中心に幅 width の台形の山(上り・下り 10 秒)"""
    out = [base] * n
    for i in range(n):
        d = abs(i - c)
        if d <= width / 2:
            out[i] = base + amp
        elif d <= width / 2 + 10:
            out[i] = base + amp * (1 - (d - width / 2) / 10)
    return out


class TestScene(unittest.TestCase):
    """場面ごとの区間(LD-2b。scene_region・pick_clips の shape scene・PeakBook の shape scene)"""

    def test_region_follows_scene_and_limits(self):
        p = excite.scene_params({"lead": 20, "tail": 30, "rise": 0.3, "settle": 0.3})
        w = bump(2000, 1000, 5.0, 100)
        r = excite.scene_region(w, 1000, 2000, p)
        self.assertFalse(r["open"])
        self.assertTrue(940 <= r["rise"] <= 950 and 1050 <= r["settle"] <= 1060, r)
        self.assertAlmostEqual(r["start"], r["rise"] - 20)
        self.assertAlmostEqual(r["end"], r["settle"] + 30)
        short = excite.scene_region(bump(2000, 1000, 5.0, 4), 1000, 2000, excite.scene_params({"lead": 0, "tail": 0}))
        self.assertAlmostEqual(short["end"] - short["start"], excite.SCENE["min"])   # 短い場面は 60 秒に足す
        long_ = excite.scene_region(bump(3000, 1500, 5.0, 400), 1500, 3000)
        self.assertAlmostEqual(long_["end"] - long_["start"], excite.SCENE["max"])   # 長すぎれば 300 秒に削る(山は中)
        self.assertTrue(long_["start"] <= 1500 <= long_["end"])
        self.assertIsNone(excite.scene_region([1.0] * 500, 250, 500))   # 平ら = 場面が取れない
        self.assertIsNone(excite.scene_region(bump(3000, 1500, 5.0, 900), 1500, 3000))   # 山の前もずっと高い = 取れない(固定の長さへ)
        head = excite.scene_region(bump(400, 20, 5.0, 10), 20, 400)
        self.assertEqual(head["start"], 0.0)   # 頭は 0 で止める

    def test_region_open_until_settled(self):
        w = bump(2000, 1000, 5.0, 100)
        r = excite.scene_region(w[:1030], 1000, 1 << 40, upto=1029)
        self.assertTrue(r["open"])
        r = excite.scene_region(w, 1000, 1 << 40, upto=1999)
        self.assertFalse(r["open"])

    def test_pick_clips_scene_marks_and_keeps_fixed(self):
        full, band, act = synth(3)
        total = excite.audio_score(full, band)
        fixed = excite.pick_clips(total, full, SPEC, len(total))
        scene = excite.pick_clips(total, full, dict(SPEC, shape="scene"), len(total))
        self.assertTrue(all("shape" not in c for c in fixed))   # 形の指定が無ければ固定の長さ(golden と同じ)
        self.assertEqual([c["peak"] for c in scene][:3], [c["peak"] for c in fixed][:3])
        for c in scene:
            self.assertIn(c["shape"], excite.SHAPES)
            self.assertEqual(len(c["fixed"]), 2)
            self.assertTrue(c["start"] <= c["peak"] <= c["end"], c)
            self.assertLessEqual(c["end"] - c["start"], excite.SCENE["max"] * excite.SNAP_RATIO[1])
        cands = excite.candidates(scene, {"audio": total})
        self.assertEqual((cands[0]["shape"], cands[0]["fixed"]), (scene[0]["shape"], scene[0]["fixed"]))

    def test_peakbook_scene_waits_for_settle(self):
        n = 1600
        w = bump(n, 800, 6.0, 120)
        b = excite.PeakBook(45, 0.65, "normal", 6, shape="scene")
        seen_open = False
        for t in range(n):
            b.push(t, w[t], {"audio": w[t]}, -30.0)
            pk = b.list()
            if pk and pk[0].get("sceneOpen"):
                seen_open = True
        pk = b.list()
        self.assertEqual(len(pk), 1, pk)
        pk = pk[0]
        self.assertTrue(seen_open)
        self.assertEqual((pk["shape"], pk["sceneOpen"], pk["endPending"]), ("scene", False, False))
        self.assertTrue(pk["start"] < 740 - 60 and pk["end"] > 860 + 30, pk)   # 前振りと余韻
        self.assertEqual(len(pk["fixed"]), 2)
        c = excite.PeakBook.from_json(json.loads(json.dumps(b.to_json())))
        self.assertEqual((c.shape, c.scene), (b.shape, b.scene))
        old = b.to_json()
        for k in ("shape", "scene", "work"):
            old.pop(k)
        self.assertEqual(excite.PeakBook.from_json(old).shape, "fixed")   # 形の欄の無い保存は固定の形

    def test_peakbook_finish_closes_open_scene(self):
        w = bump(1000, 900, 6.0, 300)
        b = excite.PeakBook(45, 0.65, "normal", 6, shape="scene")
        for t in range(1000):
            b.push(t, w[t], {"audio": w[t]}, -30.0)
        b.finish()
        pk = b.list()[0]
        self.assertEqual((pk["sceneOpen"], pk["endPending"]), (False, False))
        self.assertTrue(pk["start"] <= pk["peak"] <= pk["end"])


class TestFill(unittest.TestCase):
    """本数に届かないときの埋め(spec の fill。例: チャット 0 件・感度「低」で山が 1 つだけ → 頼んだ 5 本に届かない)"""

    def total(self):
        n = 3000
        w = bump(n, 500, 5.0, 0)   # しきい値(低 3.2)を超える山は 1 つ
        for c, amp in ((1200, 1.5), (1800, 1.2), (2400, 1.0)):   # しきい値に届かない小さな山(音声の盛り上がり)
            w = [a + b for a, b in zip(w, bump(n, c, amp, 0))]
        return w, [-30.0] * n, n

    def test_fill_up_to_requested_with_mark(self):
        w, lv, n = self.total()
        picks = excite.pick_clips(w, lv, dict(SPEC, sensitivity="low", fill=3), n)
        self.assertEqual([p["peak"] for p in picks], [500, 1200, 1800])   # 点数の高い順に、しきい値の下の山で 3 本まで
        self.assertEqual([bool(p.get("fill")) for p in picks], [False, True, True])
        cands = excite.candidates(picks, {"audio": w})
        self.assertNotIn(excite.FILL_REASON, cands[0]["reasons"])
        self.assertTrue(cands[1]["fill"])
        self.assertIn(excite.FILL_REASON, cands[1]["reasons"])

    def test_fill_stops_at_flat_and_at_count(self):
        w, lv, n = self.total()
        self.assertEqual(len(excite.pick_clips(w, lv, dict(SPEC, sensitivity="low", fill=8), n)), 4)   # 平ら(点数 0)は埋めに使わない
        self.assertEqual(len(excite.pick_clips(w, lv, dict(SPEC, sensitivity="low", fill=8, count=2), n)), 2)   # 解析の数 count が上限


if __name__ == "__main__":
    unittest.main()
