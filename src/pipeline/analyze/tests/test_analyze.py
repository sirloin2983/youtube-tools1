"""pipeline/analyze/analyze.py のテスト。 実行(リポジトリ直下): py -3.12 -m unittest src/pipeline/analyze/tests/test_analyze.py
- TestAnalyzeRun: 本物の ffmpeg で、6 分の音声 + チャット・コメント・付加情報のファイル(疑似モード)を analyze.run に通す通し
- ほかは通しでは起こせない物(中止・途中の失敗・YouTube API・壊れた記録・上限・合成の系列で測る推定の確かさ)
(判定の記録 feedback は human/review/feedback.py)。"""
import os
os.environ.setdefault("YTT_DATA_DIR", "inplace")   # テストは作業データを本物の置き場所(AppData など)に書かない(ytt.datadir)
import json
import random
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))))   # tests → analyze → pipeline → src
from human.review import machinelog  # noqa: E402
from ytt import testkit, tools  # noqa: E402
from pipeline.analyze import analyze, excite, fetch  # noqa: E402
from ytt import studio_env  # noqa: E402
from ytt.errors import ApiError, Cancelled  # noqa: E402
from ytt.jobs import Ctl  # noqa: E402

FF = tools.find_tool("ffmpeg", "YTT_FFMPEG")


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
    """推定の確かさ(遅れ 6 通り × 乱数 3 通り)と端。見本 1 本の通しでは 1 つの遅れしか見えない"""

    def est(self, **kw):
        full, band, act = synth(**kw)
        return analyze.estimate_lag(analyze.audio_score(full, band), analyze.chat_z(act))

    def test_recovers_lag_from_synthetic(self):
        for lag in (0, 4, 8, 12, 20, 27):
            for seed in (1, 2, 3):
                est, r = self.est(lag=lag, seed=seed)
                self.assertIsNotNone(est, (lag, seed))
                self.assertLessEqual(abs(est - lag), 2, (lag, seed, est))   # chat の9秒平滑化があるので±2秒まで

    def test_short_or_flat_series_returns_none(self):
        self.assertEqual(analyze.estimate_lag([1.0] * 100, [1.0] * 100)[0], None)
        self.assertEqual(analyze.estimate_lag([0.0] * 1000, [0.0] * 1000)[0], None)

    def test_shift_chat_edges(self):
        self.assertEqual(analyze.shift_chat([1, 2, 3, 4], 0), [1, 2, 3, 4])
        self.assertEqual(analyze.shift_chat([1, 2, 3, 4], 2), [3, 4, 0.0, 0.0])
        self.assertEqual(analyze.chat_score([0.0] * 50, 3), analyze.shift_chat(analyze.chat_z([0.0] * 50), 3))


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
    def test_comment_score_accepts_legacy_pairs(self):
        out = analyze.comment_score([(100, 5)], 300)
        self.assertGreater(out[100], 0)


class TestSettings(unittest.TestCase):
    def test_feedback_records_new_keys(self):
        self.assertIn("lagAuto", machinelog.SETTING_KEYS)
        self.assertIn("headSec", machinelog.SETTING_KEYS)


class TestArchive(unittest.TestCase):
    def setUp(self):
        self.tmp = testkit.tempdir(self)
        studio_env.set_home(self.tmp)

    def test_bad_ids_and_corrupt_file(self):
        self.assertFalse(analyze.save_archive("../evil", {}, {}))
        self.assertFalse(analyze.save_archive("a b", {}, {}))
        self.assertIsNone(analyze.load_archive("../evil"))
        self.assertFalse(fetch.drop_chat_cache("../x"))
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


class TestRunCtl(unittest.TestCase):
    """analyze.run(spec, ctl) の中止と失敗(通しでは中止の瞬間・内部の失敗を起こせない)"""

    def setUp(self):
        tmp = testkit.tempdir(self)
        for p in (mock.patch.object(fetch, "work_dir", lambda: tmp), mock.patch.object(analyze, "_save_record", lambda *a, **k: None)):
            p.start()
            self.addCleanup(p.stop)
        self.spec = analyze.make_spec({"kind": "file", "path": "x.mp4", "name": "x.mp4", "videoId": "f_x"},
                                      analyze.validate_settings({"useComments": False, "count": 3, "length": 30, "noCache": True}))

    def levels(self):
        full, band, *_ = synth(n=600, events=6)
        return lambda *a, **k: (600.0, 600, full[:600], band[:600])

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


# ---------------------------------------------------------------- 通し
VID = "abcdefghijk"
DUR = 330                       # 遅れの推定は 300 秒から
LAG = 10                        # チャットは音の山の 10 秒あと
BURSTS = (110, 230)             # 本編の山(笑い声のような雑音 6 秒)
INTRO = 18                      # 冒頭の山(本編より大きい。冒頭の減点で負ける)
TEXT = "liveChatTextMessageRenderer"
CALM = ["こんにちは", "はい!", "ここ！", "普通"]          # 「草」などに数えない
WARM = ["草", "wwww", "すごい", "!!"]                      # 数える
HEAT = {"title": "【R.E.P.O.】深夜の突発PEPO", "channel": "Ch", "categories": ["Gaming"], "tags": ["ゲーム実況", "ホロライブ"], "view_count": 12345, "like_count": 999,
        "comment_count": 55, "channel_follower_count": 1000000, "upload_date": "20260920", "duration": 7856, "live_status": "was_live",
        "release_timestamp": 1760000000, "timestamp": 1760000100.7,
        "heatmap": [{"start_time": 0.0, "end_time": 78.5, "value": 1.0}, {"start_time": 78.5, "end_time": 157.0, "value": 0.42}, {"bad": 1}],
        "chapters": [{"start_time": 0, "end_time": 100, "title": "開始"}, {"oops": 1}], "formats": [{"x": "y"}] * 50}
COMMENTS = [{"text": "0:30 始まり\n1:50 雑談\n3:50 ゲーム\n5:00 終わり", "likes": 500},   # チャプターの一覧(時刻 4 つ = 重み 1/4)
            {"text": "1:50 ここ最高\n二行目", "likes": 3},                                    # 1 つ
            {"text": "3:50 と 4:20 が好き", "likes": 0},                                       # 2 つ(重みはそのまま)
            {"text": "99:00 と 0:00", "likes": 1}]                                             # 長さの外・0 秒は数えない


def chat_line(ms, kind, r):
    return json.dumps({"replayChatItemAction": {"videoOffsetTimeMsec": str(ms), "actions": [{"addChatItemAction": {"item": {kind: r}}}]}}, ensure_ascii=False)


def text(t, au):
    return {"message": {"runs": [{"text": t}]}, "authorExternalChannelId": au}


def rich_chat():
    """yt-dlp の live_chat.json の形: 3 秒ごとにふだんの発言・山の LAG 秒あとから 8 秒は 1 秒 6 件の「草」など・49〜53 秒に種類の違う物・壊れた行。
    -> (行, 数える件数, 「草」などの件数)"""
    rows, total, warm = [], 0, 0
    for s in range(DUR):
        if s % 3 == 0:
            rows.append(chat_line(s * 1000, TEXT, text(CALM[s // 3 % 4], "UC%d" % (s % 7))))
            total += 1
        for b in BURSTS + (INTRO + 4,):
            if b + LAG <= s < b + LAG + 8:
                for k in range(6):
                    rows.append(chat_line(s * 1000 + k * 100, TEXT, text(WARM[k % 4], "UF%d" % k)))
                total, warm = total + 6, warm + 6
    rows += [chat_line(49000, "liveChatPaidMessageRenderer", text("www", "UP1")),                   # スパチャ: 1 + 1.5 + 4
             chat_line(50000, "liveChatPaidStickerRenderer", {"authorExternalChannelId": "UP2"}),   # ステッカー: 1 + 4
             chat_line(52000, "liveChatViewerEngagementMessageRenderer", text("草", "")),            # 案内の行は数えない
             chat_line(53000, TEXT, {"message": {"runs": [{"emoji": {"shortcuts": [":_kusa:", ":k:", ":x:"], "emojiId": "UCabc/xyz"}}]},
                                     "authorExternalChannelId": "UE1"}),                               # 絵文字だけ(「草」の絵文字)
             "これは JSON ではない", json.dumps({"replayChatItemAction": {"videoOffsetTimeMsec": "x", "actions": []}}),
             chat_line(-1000, TEXT, text("草", "UZ")), chat_line(DUR * 1000 + 5000, TEXT, text("草", "UZ"))]   # 長さの外
    return rows, total + 3, warm + 2


@unittest.skipUnless(FF, "ffmpeg が見つかりません")
class TestAnalyzeRun(unittest.TestCase):
    """解析の通し: 本物の ffmpeg で音量を測り、チャット・コメント欄・付加情報は手元のファイル(疑似モード STUDIO_FAKE。yt-dlp と YouTube API の代わり)。
    同じ動画 ID で設定とチャットを変えて 6 回流す(音量の再利用・記録の履歴 5 回・埋め・推定できない・件数が少ない・付加情報なし)"""

    @classmethod
    def setUpClass(cls):
        cls.dir = tempfile.mkdtemp(prefix="ytt-analyze-run-")
        cls.media = os.path.join(cls.dir, "配信の音.m4a")
        loud = "+".join("between(t,%d,%d)" % (b, b + 6) for b in BURSTS)
        expr = "0.03*sin(2*PI*330*t)+if(%s,0.7*(2*random(0)-1),0)+if(between(t,%d,%d),0.9*(2*random(1)-1),0)" % (loud, INTRO, INTRO + 8)
        subprocess.run([FF, "-hide_banner", "-v", "error", "-y", "-f", "lavfi", "-i", "aevalsrc=%s:s=8000:d=%d" % (expr.replace(",", "\\,"), DUR),
                        "-c:a", "aac", "-b:a", "32k", cls.media], check=True, stdin=subprocess.DEVNULL, creationflags=tools.no_window_flags())
        rows, cls.total, cls.warm = rich_chat()
        cls.files = {}
        for name, body in (("chat", "\n".join(rows) + "\n"),
                           ("flat", "".join(chat_line(s * 1000, TEXT, text("普通", "UC1")) + "\n" for s in range(DUR))),   # 毎秒 1 件 = 山が無い
                           ("few", "".join(chat_line(s * 1000, TEXT, text("草", "UC1")) + "\n" for s in range(10))),
                           ("comments", json.dumps(COMMENTS, ensure_ascii=False)), ("meta", json.dumps(HEAT, ensure_ascii=False)),
                           ("garbage", json.dumps({"view_count": "x", "tags": "notalist", "heatmap": "no", "chapters": [1, None], "title": 5}))):
            cls.files[name] = os.path.join(cls.dir, name + ".json")
            with open(cls.files[name], "w", encoding="utf-8") as f:
                f.write(body)
        studio_env.set_home(os.path.join(cls.dir, "studio"))

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.dir, ignore_errors=True)

    def run_once(self, settings, chat=None, comments=None, meta=None, ctl=None):
        env = {"STUDIO_FAKE": "1", "STUDIO_FAKE_MEDIA": self.media}
        env.update({k: self.files[v] for k, v in (("STUDIO_FAKE_CHAT", chat), ("STUDIO_FAKE_COMMENTS", comments), ("STUDIO_FAKE_META", meta)) if v})
        with mock.patch.dict(os.environ, env):
            for k in ("STUDIO_FAKE_CHAT", "STUDIO_FAKE_COMMENTS", "STUDIO_FAKE_META"):
                if k not in env:
                    os.environ.pop(k, None)
            spec = analyze.make_spec({"kind": "youtube", "videoId": VID, "name": VID}, analyze.validate_settings(settings))
            return analyze.run(spec, ctl or Ctl())

    def test_runs(self):
        # 1 回目: 既定の設定・材料が全部ある
        seen = []
        a = self.run_once({}, chat="chat", comments="comments", meta="meta", ctl=Ctl(on_progress=lambda frac, msg: seen.append(frac)))
        self.assertEqual(set(a), {"source", "candidates", "series", "signals", "counts", "warnings", "spec", "stream"})
        self.assertEqual(seen[-1], 1.0)
        self.assertEqual(a["signals"], {"audio": True, "chat": True, "comments": True})
        self.assertEqual({k: a["counts"][k] for k in ("chat", "chatWarm", "commentStamps", "meta", "heatmap", "fills")}, {"chat": self.total, "chatWarm": self.warm,
                         "commentStamps": 7, "meta": True, "heatmap": 2, "fills": 0})
        self.assertEqual(a["stream"], {"releaseTs": 1760000000, "timestamp": 1760000100, "uploadDate": "20260920", "liveStatus": "was_live", "duration": 7856})
        sp = a["spec"]
        self.assertEqual((sp["lagAuto"], sp["headSec"], sp["fill"], sp["count"], sp["length"], sp["shape"]), (True, 180, 0, 8, 45, excite.SHAPE_DEFAULT))
        self.assertTrue(LAG - 2 <= sp["lag"] <= LAG + 4, sp)   # 推定した遅れ(山の幅の分だけ後ろに寄る)
        self.assertTrue(any("自動推定しました" in w for w in a["warnings"]), a["warnings"])
        cands = a["candidates"]
        self.assertEqual(sorted(min(BURSTS, key=lambda b: abs(b - c["peak"])) for c in cands), list(BURSTS), cands)   # 本編の山ごとに 1 本
        for c in cands:
            self.assertTrue(0 <= c["peak"] - min(BURSTS, key=lambda b: abs(b - c["peak"])) <= 8, c)
            self.assertGreaterEqual(c["parts"]["chat"], excite.PART_ON["chat"], c)   # 遅れの分だけ前へずらしたチャットが山に重なる
            self.assertTrue(c["start"] <= c["peak"] <= c["end"] and len(c["fixed"]) == 2 and c["shape"] in excite.SHAPES, c)
            self.assertNotIn("fill", c)
            self.assertNotIn(excite.FILL_REASON, c["reasons"])
        rec = analyze.load_archive(VID)
        m = rec["meta"]
        self.assertEqual((m["heatmap"], m["chapters"]), ([[0.0, 78.5, 1.0], [78.5, 157.0, 0.42]], [[0.0, 100.0, "開始"]]))   # 形の違う行は捨てる
        self.assertEqual((m["views"], m["likes"], m["followers"], m["releaseTs"], m["timestamp"]), (12345, 999, 1000000, 1760000000, 1760000100))
        self.assertNotIn("formats", m)
        ch = rec["chat"]
        self.assertEqual((ch["count"], ch["warmCount"]), (self.total, self.warm))
        self.assertEqual([ch["act"][s] for s in (49, 50, 52, 53)], [6.5, 5.0, 0.0, 2.5])   # スパチャ・ステッカー・案内・絵文字の重み
        self.assertEqual(([ch["paid"][s] for s in (49, 50, 53)], [ch["warm"][s] for s in (49, 50, 53)]), ([1, 1, 0], [1, 0, 1]))
        s = BURSTS[0] + LAG + 1   # 3 の倍数でない秒 = 山のあとの 6 人だけ
        self.assertEqual((ch["uniq"][s], ch["warm"][s], ch["act"][s]), (6, 6, 15.0))
        self.assertEqual((ch["uniq"][BURSTS[0] + LAG], ch["warm"][3], ch["act"][3]), (7, 0, 1.0))   # ふだんの発言の人も数える・「はい!」は数えない
        st = sorted(rec["stamps"])
        self.assertEqual([(t, lk, w) for t, lk, w, _ in st], [(30, 500, 0.25), (110, 3, 1.0), (110, 500, 0.25), (230, 0, 1.0), (230, 500, 0.25), (260, 0, 1.0),
                                                                (300, 500, 0.25)])
        self.assertIn("1:50 ここ最高 二行目", [x for *_, x in st])
        self.assertTrue(all(len(x) <= 60 and "\n" not in x for *_, x in st))
        self.assertEqual(rec["runs"][-1]["spec"]["lagAuto"], True)
        self.assertEqual([c["peak"] for c in rec["runs"][-1]["candidates"]], [c["peak"] for c in cands])

        # 2 回目: 範囲外の設定(丸める)・感度「低」で埋める・付加情報の形がおかしい・音量は前回の結果を再利用
        b = self.run_once({"lagAuto": False, "headSec": 99999, "lag": -5, "fill": 99, "sensitivity": "low", "useComments": "x"}, chat="chat", meta="garbage")
        sp = b["spec"]
        self.assertEqual((sp["lagAuto"], sp["headSec"], sp["lag"], sp["fill"], sp["sensitivity"]), (False, 600, 0, 30, "low"))
        self.assertTrue(any("前回の結果を再利用" in w for w in b["warnings"]), b["warnings"])
        self.assertFalse(any("自動推定" in w for w in b["warnings"]))
        fills = [c for c in b["candidates"] if c.get("fill")]
        self.assertTrue(fills, b["candidates"])
        self.assertTrue(all(excite.FILL_REASON in c["reasons"] for c in fills))
        self.assertEqual((b["counts"]["fills"], b["counts"]["cands"]), (len(fills), len(b["candidates"])))
        m = analyze.load_archive(VID)["meta"]
        self.assertEqual((m["views"], m["tags"], m["heatmap"], m["chapters"], m["title"]), (None, [], [], [], "5"))

        # 3 回目: 山の無いチャット(遅れを推定できない)・付加情報なし・冒頭の減点なし(冒頭の山が勝つ)
        c = self.run_once({"headSec": 0, "useComments": False}, chat="flat")
        self.assertTrue(any("自動推定できなかった" in w for w in c["warnings"]), c["warnings"])
        self.assertEqual(len([w for w in c["warnings"] if "付加情報" in w]), 1)
        self.assertEqual((c["counts"]["meta"], c["stream"], c["spec"]["lag"]), (False, {}, 8))
        self.assertTrue(any(INTRO <= x["peak"] <= INTRO + 10 for x in c["candidates"]), c["candidates"])
        self.assertFalse(any(x["peak"] < 60 for x in a["candidates"]), "冒頭の減点がある 1 回目では冒頭の山は候補にならない")

        # 4 回目: チャットが 30 件未満(配信の直後)= 使わず、取っておいたチャットも捨てる
        os.makedirs(fetch.chat_cache_dir(), exist_ok=True)
        with open(fetch.chat_cache_path(VID), "w", encoding="utf-8") as f:
            f.write("{}\n")
        d = self.run_once({"useComments": False}, chat="few")
        self.assertTrue(any("件数が少ない(10件)" in w for w in d["warnings"]), d["warnings"])
        self.assertEqual((d["signals"]["chat"], d["counts"]["chat"]), (False, 10))
        self.assertFalse(os.path.exists(fetch.chat_cache_path(VID)))

        # 5・6 回目: 記録の履歴は直近 5 回
        for _ in range(2):
            self.run_once({"useChat": False, "useComments": False})
        rec = analyze.load_archive(VID)
        self.assertEqual((len(rec["runs"]), rec["runs"][0]["spec"]["lagAuto"], rec["v"]), (5, False, 1))   # 1 回目は消えて 2 回目から
        self.assertEqual([r["at"] for r in rec["runs"]], sorted(r["at"] for r in rec["runs"]))
        self.assertIsNone(rec["meta"], "付加情報の無い回は付加情報なしで残す")


if __name__ == "__main__":
    unittest.main(verbosity=1)
