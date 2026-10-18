"""pipeline/analyze/analyze.py の判定ロジックのテスト(ネットワーク・ffmpeg 不要)。 実行(リポジトリ直下): py -3.12 -m unittest src/pipeline/analyze/tests/test_analyze.py
RS3-5(2026-10-10)で studio/tests から移した(判定の記録 feedback は human/review/feedback.py)。"""
import os
os.environ.setdefault("YTT_DATA_DIR", "inplace")   # テストは作業データを本物の置き場所(AppData など)に書かない(ytt.datadir)
import random
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))))   # tests → analyze → pipeline → src
from human.review import feedback  # noqa: E402
from ytt import testkit  # noqa: E402
from pipeline.analyze import analyze, fetch  # noqa: E402
from ytt import studio_env  # noqa: E402
from ytt.errors import ApiError, Cancelled  # noqa: E402
from ytt.jobs import Ctl  # noqa: E402


def synth(n=4000, lag=12, events=40, seed=1, chat_noise=1.0, related=True):
    """音量(dB)とチャット(1秒ごとの件数)の合成データ。音声のイベントの lag 秒後にチャットが増える。"""
    rnd = random.Random(seed)
    full = [-30 + rnd.gauss(0, 1.5) for _ in range(n)]
    band = [-40 + rnd.gauss(0, 1.5) for _ in range(n)]
    act = [max(0.0, rnd.gauss(3, chat_noise)) for _ in range(n)]
    ev = sorted(rnd.sample(range(100, n - 100), events))
    for t in ev:
        for d in range(0, 6):
            full[t + d] += 12 - d
            band[t + d] += 10 - d
        if related:
            for d in range(0, 10):
                act[t + lag + d] += 25 - 2 * d
    if not related:   # 音声とは無関係な時刻にチャットの山
        for t in rnd.sample(range(100, n - 100), events):
            for d in range(0, 10):
                act[t + d] += 25 - 2 * d
    return full, band, act


class TestLagEstimate(unittest.TestCase):
    def est(self, **kw):
        full, band, act = synth(**kw)
        return analyze.estimate_lag(analyze.audio_score(full, band), analyze.chat_z(act))

    def test_recovers_lag_from_synthetic(self):
        for lag in (0, 4, 8, 12, 20, 27):
            for seed in (1, 2, 3):
                est, r = self.est(lag=lag, seed=seed)
                self.assertIsNotNone(est, (lag, seed))
                self.assertLessEqual(abs(est - lag), 2, (lag, seed, est))   # chat の9秒平滑化があるので±2秒まで

    def test_no_relation_falls_back(self):
        for seed in (1, 2, 3, 4):
            est, _ = self.est(related=False, seed=seed)
            self.assertIsNone(est, seed)

    def test_short_or_flat_series_returns_none(self):
        self.assertEqual(analyze.estimate_lag([1.0] * 100, [1.0] * 100)[0], None)
        self.assertEqual(analyze.estimate_lag([0.0] * 1000, [0.0] * 1000)[0], None)

    def test_shift_direction_puts_chat_peak_at_audio_time(self):
        full, band, act = synth(lag=15, events=20, seed=5)
        a = analyze.audio_score(full, band)
        z = analyze.chat_z(act)
        est, _ = analyze.estimate_lag(a, z)
        shifted = analyze.shift_chat(z, est)
        self.assertEqual(len(shifted), len(z))
        # ずらした後の方が、音声との一致が高い
        def dot(x, y):
            return sum(p * q for p, q in zip(x, y))
        self.assertGreater(dot(a, shifted), dot(a, z))
        # 元のチャット(遅れたまま)より、8秒固定より、推定値の方が一致が高い
        self.assertGreater(dot(a, shifted), dot(a, analyze.shift_chat(z, 8)))

    def test_shift_chat_edges(self):
        self.assertEqual(analyze.shift_chat([1, 2, 3, 4], 0), [1, 2, 3, 4])
        self.assertEqual(analyze.shift_chat([1, 2, 3, 4], 2), [3, 4, 0.0, 0.0])
        self.assertEqual(analyze.chat_score([0.0] * 50, 3), analyze.shift_chat(analyze.chat_z([0.0] * 50), 3))


class TestHeadRamp(unittest.TestCase):
    def test_ramp(self):
        r = analyze.head_ramp([10.0] * 400, 180)
        self.assertEqual(r[0], 0.0)
        self.assertAlmostEqual(r[90], 10 * 0.25)
        self.assertAlmostEqual(r[180], 10.0)
        self.assertEqual(r[399], 10.0)
        self.assertTrue(all(r[i] <= r[i + 1] for i in range(399)))   # 単調に戻る

    def test_disabled(self):
        x = [1.0, 2.0, 3.0]
        self.assertEqual(analyze.head_ramp(x, 0), x)

    def test_intro_peak_loses_to_later_peak(self):
        n = 1000
        total = [0.0] * n
        for i in range(55, 66):
            total[i] = 5.0      # 冒頭(60秒)の山
        for i in range(495, 506):
            total[i] = 4.0      # 本編の山
        spec = {"length": 45, "preRatio": 0.65, "sensitivity": "normal", "count": 1}
        level = [0.0] * n
        top = analyze.pick_clips(analyze.head_ramp(total, 180), level, spec, n)[0]
        self.assertTrue(490 <= top["peak"] <= 510, top)
        top0 = analyze.pick_clips(total, level, spec, n)[0]   # 減点なしなら冒頭が勝つ
        self.assertTrue(50 <= top0["peak"] <= 70, top0)


class TestFetchComments(unittest.TestCase):
    """fetch_comments は ytt/ytapi.get を通る(キーは URL に入れない)。失敗の文"""

    def run_with(self, err_or_data):
        def get(path, params):
            self.seen = (path, dict(params))
            if isinstance(err_or_data, Exception):
                raise err_or_data
            return err_or_data
        with mock.patch.object(fetch._env, "fake", return_value=False), mock.patch.object(fetch._key, "get_api_key", return_value=("KEY", "env")), \
                mock.patch.object(fetch._ytapi, "get", get):
            return fetch.fetch_comments("v" * 11, 600)

    def test_key_not_in_params(self):
        st, why = self.run_with({"items": [{"snippet": {"topLevelComment": {"snippet": {"textOriginal": "1:00 ここ", "likeCount": 2}}}}]})
        self.assertEqual((self.seen[0], "key" in self.seen[1], why), ("commentThreads", False, ""))
        self.assertEqual(st, [(60, 2, 1.0)])

    def test_quota_says_limit(self):
        st, why = self.run_with(ApiError("quota", "YouTube APIの1日の利用上限に達しました", 429))
        self.assertIsNone(st)
        self.assertIn("上限", why)


class TestComments(unittest.TestCase):
    def test_chapter_list_downweighted(self):
        chapters = "0:30 始まり\n10:00 雑談\n25:10 ゲーム\n40:00 終わり\n55:00 おまけ"
        st = fetch.stamps_from([{"text": chapters, "likes": 500}], 4000)
        self.assertEqual(len(st), 5)
        self.assertTrue(all(abs(w - 0.2) < 1e-9 for _, _, w in st))

    def test_single_and_pair_comments_full_weight(self):
        st = fetch.stamps_from([{"text": "12:34 ここ最高", "likes": 3}, {"text": "1:00 と 2:00 が好き", "likes": 0}], 4000)
        self.assertEqual([w for *_, w in st], [1.0, 1.0, 1.0])

    def test_out_of_range_ignored(self):
        st = fetch.stamps_from([{"text": "99:00 と 0:00", "likes": 1}], 300)
        self.assertEqual(st, [])

    def test_score_much_lower_for_list_than_for_individual_comments(self):
        n = 3000
        lst = fetch.stamps_from([{"text": "5:00 a\n20:00 b\n30:00 c\n40:00 d", "likes": 200}], n)
        ind = fetch.stamps_from([{"text": "20:00 ここ", "likes": 200}], n)
        self.assertLess(max(analyze.comment_score(lst, n)), 0.3 * max(analyze.comment_score(ind, n)))

    def test_comment_score_accepts_legacy_pairs(self):
        out = analyze.comment_score([(100, 5)], 300)
        self.assertGreater(out[100], 0)


class TestSettings(unittest.TestCase):
    def test_defaults(self):
        s = analyze.validate_settings({})
        self.assertEqual((s["lagAuto"], s["headSec"], s["lag"]), (True, 180, 8))

    def test_clamped_and_types(self):
        s = analyze.validate_settings({"lagAuto": False, "headSec": 99999, "lag": -5})
        self.assertEqual((s["lagAuto"], s["headSec"], s["lag"]), (False, 600, 0))
        self.assertEqual(analyze.validate_settings({"headSec": -3})["headSec"], 0)
        self.assertTrue(analyze.validate_settings({"lagAuto": "no"})["lagAuto"])   # False 以外は既定の「自動」

    def test_feedback_records_new_keys(self):
        self.assertIn("lagAuto", feedback.FB_SETTING_KEYS)
        self.assertIn("headSec", feedback.FB_SETTING_KEYS)


class TestChatWarm(unittest.TestCase):
    def parse(self, texts, tmp):
        import json
        p = os.path.join(tmp, "c.jsonl")
        with open(p, "w", encoding="utf-8") as f:
            for i, t in enumerate(texts):
                f.write(json.dumps({"replayChatItemAction": {"videoOffsetTimeMsec": str(i * 1000), "actions": [{"addChatItemAction": {"item": {"liveChatTextMessageRenderer": {"message": {"runs": [{"text": t}]}}}}}]}}) + "\n")
        return analyze.parse_chat(p, len(texts) + 1)

    def test_single_exclamation_not_warm_but_kusa_is(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            _, total, warm = self.parse(["はい!", "ここ！", "おはよう！", "草", "wwww", "すごい", "!!", "普通"], d)
        self.assertEqual((total, warm), (8, 4))   # 草 / wwww / すごい / !! だけ


HEAT = {"title": "【R.E.P.O.】深夜の突発PEPO", "channel": "Ch", "categories": ["Gaming"], "tags": ["ゲーム実況", "ホロライブ"], "view_count": 12345, "like_count": 999,
        "comment_count": 55, "channel_follower_count": 1000000, "upload_date": "20260920", "duration": 7856, "live_status": "was_live",
        "heatmap": [{"start_time": 0.0, "end_time": 78.5, "value": 1.0}, {"start_time": 78.5, "end_time": 157.0, "value": 0.42}, {"bad": 1}],
        "chapters": [{"start_time": 0, "end_time": 100, "title": "開始"}, {"oops": 1}], "formats": [{"x": "y"}] * 50}


class TestMeta(unittest.TestCase):
    def test_slim_keeps_only_needed_and_skips_bad_rows(self):
        m = fetch.slim_meta(HEAT)
        self.assertEqual(m["heatmap"], [[0.0, 78.5, 1.0], [78.5, 157.0, 0.42]])
        self.assertEqual(m["chapters"], [[0.0, 100.0, "開始"]])
        self.assertEqual((m["views"], m["likes"], m["followers"], m["liveStatus"]), (12345, 999, 1000000, "was_live"))
        self.assertNotIn("formats", m)
        self.assertEqual((m["releaseTs"], m["timestamp"]), (None, None))
        m2 = fetch.slim_meta(dict(HEAT, release_timestamp=1760000000, timestamp=1760000100.7))   # D-SEND: 配信の始まり(終わった時刻 = releaseTs + duration の元)
        self.assertEqual((m2["releaseTs"], m2["timestamp"], m2["duration"], m2["liveStatus"]), (1760000000, 1760000100, 7856, "was_live"))
        self.assertIsNone(fetch.slim_meta(dict(HEAT, release_timestamp="x"))["releaseTs"])
        self.assertIsNone(fetch.slim_meta([1]))
        self.assertIsNone(fetch.slim_meta(None))

    def test_slim_tolerates_garbage_types(self):
        m = fetch.slim_meta({"view_count": "x", "tags": "notalist", "heatmap": "no", "chapters": [1, None], "title": 5})
        self.assertEqual((m["views"], m["tags"], m["heatmap"], m["chapters"]), (None, [], [], []))


class TestArchive(unittest.TestCase):
    def setUp(self):
        self.tmp = testkit.tempdir(self)
        studio_env.set_home(self.tmp)

    def test_roundtrip_and_run_history_capped(self):
        for i in range(7):
            self.assertTrue(analyze.save_archive("abcdefghijk", {"full": [1.0, 2.0], "meta": {"title": "日本語"}}, {"at": i, "candidates": []}))
        d = analyze.load_archive("abcdefghijk")
        self.assertEqual(d["meta"]["title"], "日本語")
        self.assertEqual([r["at"] for r in d["runs"]], [2, 3, 4, 5, 6])   # 直近5回
        self.assertEqual(d["v"], 1)

    def test_bad_ids_and_corrupt_file(self):
        self.assertFalse(analyze.save_archive("../evil", {}, {}))
        self.assertFalse(analyze.save_archive("a b", {}, {}))
        self.assertIsNone(analyze.load_archive("../evil"))
        p = analyze.archive_path("abcdefghijk")
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "wb") as f:
            f.write(b"not gzip")
        self.assertIsNone(analyze.load_archive("abcdefghijk"))
        self.assertTrue(analyze.save_archive("abcdefghijk", {}, {"at": 1}))   # 壊れていても作り直せる
        self.assertEqual(len(analyze.load_archive("abcdefghijk")["runs"]), 1)

    def test_prune_keeps_newest(self):
        for i in range(5):
            analyze.save_archive("v%010d" % i, {}, {"at": i}, keep=3)
            os.utime(analyze.archive_path("v%010d" % i), (1000 + i, 1000 + i))
        analyze.save_archive("v%010d" % 9, {}, {"at": 9}, keep=3)
        left = sorted(os.listdir(os.path.dirname(analyze.archive_path("v0000000000"))))
        self.assertEqual(len(left), 3)


class TestChatExtra(unittest.TestCase):
    def test_extra_counts(self):
        import json, tempfile
        rows = []
        def add(t, text, au, kind="liveChatTextMessageRenderer"):
            rows.append({"replayChatItemAction": {"videoOffsetTimeMsec": str(t * 1000), "actions": [{"addChatItemAction": {"item": {kind: {"message": {"runs": [{"text": text}]}, "authorExternalChannelId": au}}}}]}})
        add(1, "草", "u1"); add(1, "草", "u2"); add(1, "はい", "u1"); add(2, "ありがとう", "u3", "liveChatPaidMessageRenderer"); add(3, "普通", "u1")
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "c.jsonl")
            with open(p, "w", encoding="utf-8") as f:
                f.write("\n".join(json.dumps(r) for r in rows))
            ex = {}
            act, total, warm = analyze.parse_chat(p, 5, ex)
            self.assertEqual((total, warm), (5, 2))
            self.assertEqual(ex["warm"], [0, 2, 0, 0, 0])
            self.assertEqual(ex["paid"], [0, 0, 1, 0, 0])
            self.assertEqual(ex["uniq"], [0, 2, 1, 1, 0])   # 1秒目は u1・u2 の2人
            self.assertEqual(analyze.parse_chat(p, 5)[1:], (5, 2))   # extra なしでも従来どおり


class TestCommentTexts(unittest.TestCase):
    def test_texts_parallel_to_stamps(self):
        texts = []
        st = fetch.stamps_from([{"text": "12:34 ここ最高\n二行目", "likes": 1}, {"text": "1:00 a 2:00 b 3:00 c", "likes": 0}], 4000, texts)
        self.assertEqual(len(st), len(texts))
        self.assertTrue(texts[0].startswith("12:34 ここ最高 二行目"))
        self.assertTrue(all(len(t) <= 60 for t in texts))


class TestRunCtl(unittest.TestCase):
    """analyze.run(spec, ctl)(OPT2 の J1): 進み具合は ctl.report・取り消しは Cancelled・失敗は ApiError・互換の包みは辞書に写す"""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        for p in (mock.patch.object(fetch, "work_dir", lambda: tmp.name), mock.patch.object(analyze, "_save_record", lambda *a, **k: None)):
            p.start()
            self.addCleanup(p.stop)
        self.spec = analyze.make_spec({"kind": "file", "path": "x.mp4", "name": "x.mp4", "videoId": "f_x"},
                                      analyze.validate_settings({"useComments": False, "count": 3, "length": 30, "noCache": True}))

    def levels(self):
        full, band, *_ = synth(n=600, events=6)
        return lambda *a, **k: (600.0, 600, full[:600], band[:600])

    def test_run_returns_result_and_reports(self):
        seen = []
        ctl = Ctl(on_progress=lambda frac, msg: seen.append((frac, msg)))
        with mock.patch.object(analyze, "_levels", self.levels()):
            res = analyze.run(self.spec, ctl)
        self.assertTrue(res["candidates"])
        self.assertEqual(set(res), {"source", "candidates", "series", "signals", "counts", "warnings", "spec", "stream"})
        self.assertEqual(res["stream"], {}, "付加情報が取れなかったときは空")
        self.assertEqual(seen[-1], (1.0, "解析が完了しました"))
        self.assertIn((None, "素材を取得中"), seen)

    def test_run_carries_stream_times(self):
        """D-SEND: 付加情報の配信の始まり・長さを結果の stream に写す(batch が analysis に入れる。② flow/sendpolicy.ended_at_of が読む)"""
        real = analyze._weights
        meta = fetch.slim_meta(dict(HEAT, release_timestamp=1760000000, timestamp=1760000100))

        def with_meta(run, spec, warnings):
            return real(run, spec, warnings)[0], meta
        with mock.patch.object(analyze, "_levels", self.levels()), mock.patch.object(analyze, "_weights", with_meta):
            res = analyze.run(self.spec, Ctl())
        self.assertEqual(res["stream"], {"releaseTs": 1760000000, "timestamp": 1760000100, "uploadDate": "20260920", "liveStatus": "was_live", "duration": 7856})

    def test_cancel_and_failure_are_exceptions(self):
        ctl = Ctl()
        ctl.cancel()
        with self.assertRaises(Cancelled):
            analyze.run(self.spec, ctl)
        with mock.patch.object(analyze, "_levels", side_effect=ValueError("boom")), mock.patch.object(analyze._env, "log_failure", lambda *a: None):
            with self.assertRaises(ApiError) as cm:
                analyze.run(self.spec)   # ctl なし
        self.assertEqual(cm.exception.code, "internal")

    def test_cancel_during_run(self):
        ctl = Ctl()

        def levels(*a, **k):
            ctl.cancel()   # 区切りで見つかる
            return self.levels()()
        with mock.patch.object(analyze, "_levels", levels), self.assertRaises(Cancelled):
            analyze.run(self.spec, ctl)


if __name__ == "__main__":
    unittest.main(verbosity=1)
