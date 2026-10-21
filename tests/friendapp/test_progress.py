# -*- coding: utf-8 -*-
"""friendapp/progress.py の確かめ(F3-3)。ファイルもネットも使わない。

    py -3.12 -m unittest tests/friendapp/test_progress.py
"""
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(HERE)), "src", "friendapp"))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(HERE)), "src"))
import progress as P   # noqa: E402


def st(key, state, detail=""):
    return {"key": key, "label": key, "state": state, "detail": detail}


class ClassifyTest(unittest.TestCase):
    def check(self, text, code, kind="url"):
        r = P.classify(text, kind)
        self.assertEqual(r["code"], code, text)
        self.assertEqual(r["detail"], text)
        return r

    def test_codes_and_retry(self):
        """言葉 -> 失敗の種類と「もう一度送る」を出すか(None は種類だけ見る)"""
        for code, retry, texts in (
                ("members", False, ("Join this channel to get access", "メンバー限定の動画です", "members only")),
                ("unavailable", None, ("この動画は非公開です", "Private video. Sign in", "Video unavailable", "This live event will begin in 5 minutes.", "まだ公開されていません")),
                ("noArchive", None, ("アーカイブが出ませんでした", "アーカイブがまだ作られていません", "no archive found for this stream")),
                ("rangeOver", None, ("区間が配信の長さを超えています", "requested range is out of range", "区間が長すぎます(3 時間まで)")),
                ("disk", True, ("パソコンの空きが足りません", "[Errno 28] No space left on device", "disk full")),
                ("net", True, ("ネットにつながりませんでした", "<urlopen error [Errno 11001] getaddrinfo failed>", "ConnectionError: timed out", "HTTP Error 503: Service Unavailable")),
                ("gpu", False, ("文字起こし: GPU(Vulkan)を使えませんでした。GPU のドライバを確かめるか、処理方式を「CPU」にしてください",)),
                ("busy", True, ("[WinError 32] プロセスはファイルにアクセスできません。別のプロセスが使用中です。",)),
                ("longPath", False, ("[WinError 206] ファイル名または拡張子が長すぎます。",)),
                ("unknown", None, ("ごみ箱へ移す前の削除に失敗しました",)),   # 内部の「削除」は非公開・削除の動画と言わない
                ("transcribe", False, ("文字起こしの部品が見つかりません", "whisper.cpp exited with code 1", "CUDA error")),
                ("dropbox", True, ("Dropbox の鍵が無い", "invalid_grant: refresh token expired", "expired_access_token")),
                ("noHighlights", None, ("見どころが見つかりませんでした", "切り抜く所が見つかりませんでした", "no highlights were found", "候補が 0 件です")),
                ("cancelled", None, ("止めました", "Job cancelled by user"))):
            for text in texts:
                with self.subTest(text=text):
                    r = self.check(text, code)
                    if retry is not None:
                        self.assertEqual(r["retry"], retry)

    def test_bot(self):
        bot = "方法1(区間取得): ERROR: [youtube] x: Sign in to confirm you’re not a bot. Use --cookies-from-browser"
        r = self.check(bot, "bot")
        self.assertTrue(r["retry"])
        self.assertEqual((r["retryMax"], r["retryEvery"]), (1, 1800))   # 間を空けて 1 回だけ
        self.assertIn("[YouTube にログイン] でログインしてください", r["message"])   # ログインしていない = ログインを勧める
        self.assertNotIn("処理する PC", r["message"])
        self.assertIn("ログインが切れた可能性", P.classify(bot, login=True)["message"])   # ログインしてあっても止められた = 切れた
        self.assertIn("ログインが切れた可能性", P.classify("WARNING: The provided YouTube account cookies are no longer valid.")["message"])
        self.check("Sign in to confirm you�fre not a bot", "bot")   # 化けた文でも当たる
        r = self.check("HTTP Error 429: Too Many Requests", "rate")   # 429 はログインと別(待てば直る)
        self.assertEqual((r["retryMax"], r["retryEvery"]), (1, 1800))
        r = self.check("Sign in to confirm your age. Use --cookies-from-browser", "age")   # 年齢の確認 = ログインが要る(やり直さない)
        self.assertFalse(r["retry"])
        self.assertIn("YouTube にログイン", r["message"])
        self.assertEqual(P.LOGIN_CODES, ("bot", "age"))
        self.assertNotIn("retryMax", P.classify("timed out"))

    def test_range_over_not_for_file(self):
        r = self.check("区間が配信の長さを超えています", "unknown", kind="file")
        self.assertTrue(r["retry"])   # 当たらない失敗は「もう一度送る」を出す
        self.assertEqual(P.classify(None)["detail"], "")
        r = self.check("解析中に動画が削除されました", "unavailable", kind="file")   # 消えた動画は送り直しても同じ
        self.assertFalse(r["retry"])
        self.assertEqual(r["message"], P.FILE_UNAVAILABLE)

    def test_detail_cut(self):
        self.assertEqual(len(P.classify("x" * 900)["detail"]), 500)


class StageTest(unittest.TestCase):
    def test_url_full(self):
        steps = [st("analyze", "done"), st("adopt", "done"), st("export", "run", "12/30"),
                 st("transcribe", "wait"), st("pack", "wait")]
        r = P.stage(steps)
        self.assertEqual(r, {"index": 2, "total": 4, "label": "切り抜き", "detail": ""})   # 見どころ は 2 つ続くので 1 段にまとめる

    def test_url_ranged_drops_analyze_stage(self):
        steps = [st("analyze_later", "wait"), st("export", "run"), st("transcribe", "wait"), st("pack", "wait")]
        r = P.stage(steps, ranged=True)
        self.assertEqual((r["index"], r["total"], r["label"]), (2, 4, "切り抜き"))
        r2 = P.stage([st("analyze", "run"), st("export", "wait")], ranged=True)
        self.assertEqual(r2["total"], 1)   # 見どころを探す を数えない(段は切り抜きだけ)
        self.assertEqual(r2["label"], "切り抜き")

    def test_fetch_word_in_detail(self):
        r = P.stage([st("analyze", "run", "動画をダウンロード中")])
        self.assertEqual(r["label"], "動画を取得")
        r2 = P.stage([st("export", "run", "取得しています")])
        self.assertEqual(r2["label"], "動画を取得")

    def test_file_kind(self):
        steps = [st("normalize", "done"), st("transcribe", "run", "3/5"), st("pack", "wait")]
        r = P.stage(steps, kind="file")
        self.assertEqual(r, {"index": 2, "total": 3, "label": "文字起こし", "detail": "3/5 本"})

    def test_stage_progress_text(self):
        self.assertEqual(P.stage([st("transcribe", "run", "1 / 3 本 ・ 認識 42%")])["detail"], "1/3 本 42%")
        self.assertEqual(P.stage([st("normalize", "run", "30fps にそろえています(42%)")], kind="file")["detail"], "30fps にそろえています(42%)")
        self.assertEqual(P.stage([st("normalize", "run", "重い処理の枠が空くのを待っています")], kind="file")["detail"], "重い処理の枠が空くのを待っています")
        self.assertEqual(P.stage([st("normalize", "run", "30fps にそろえています(1/3)")], kind="file")["detail"], "")
        r = P.stage([st("transcribe", "run", "1 / 3 本 ・ 認識 42%")], with_raw=True)
        self.assertEqual(r["raw"], "1 / 3 本 ・ 認識 42%")

    def test_transcribe_percent_and_other_detail(self):
        self.assertEqual(P.stage([st("transcribe", "run", "42%")])["detail"], "42%")
        self.assertEqual(P.stage([st("export", "run", "12/30")])["detail"], "")

    def test_all_done_and_empty(self):
        self.assertIsNone(P.stage([st("pack", "done"), st("deliver", "skip")]))
        self.assertIsNone(P.stage([]))
        self.assertIsNone(P.stage(None))

    def test_next_after_done_when_none_running(self):
        steps = [st("analyze", "done"), st("export", "wait"), st("transcribe", "wait")]
        r = P.stage(steps)
        self.assertEqual((r["index"], r["label"]), (2, "切り抜き"))

    def test_consecutive_same_label_merged(self):
        steps = [st("analyze", "done"), st("adopt", "run"), st("export", "wait")]
        r = P.stage(steps)
        self.assertEqual((r["index"], r["total"], r["label"]), (1, 2, "見どころを探す"))
        steps2 = [st("analyze", "run", "取得"), st("export", "wait")]
        self.assertEqual(P.stage(steps2)["label"], "動画を取得")


class EtaTest(unittest.TestCase):
    STATS = {"動画を取得": [60, 80], "見どころを探す": [100], "切り抜き": [200, 200, 200], "文字起こし": [300],
             "仕上げ": [30]}

    def test_remaining(self):
        # 切り抜き 平均 200・経った 50 → 150 + 文字起こし 300 + 仕上げ 30
        self.assertEqual(P.eta(self.STATS, "url", False, "切り抜き", 50), 480)
        self.assertEqual(P.eta(self.STATS, "url", False, "切り抜き", 999), 330)

    def test_missing_record_is_none(self):
        self.assertIsNone(P.eta({"動画を取得": [60]}, "url", False, "動画を取得", 0))
        stats = dict(self.STATS)
        stats.pop("仕上げ")
        self.assertIsNone(P.eta(stats, "url", False, "切り抜き", 0))

    def test_ranged_skips_analyze_label(self):
        stats = {k: v for k, v in self.STATS.items() if k != "見どころを探す"}
        self.assertEqual(P.eta(stats, "url", True, "切り抜き", 0), 200 + 300 + 30)
        self.assertIsNone(P.eta(stats, "url", False, "見どころを探す", 0))

    def test_file_kind(self):
        stats = {"動画を取得": [60], "文字起こし": [300], "仕上げ": [30]}
        self.assertEqual(P.eta(stats, "file", False, "動画を取得", 10), 50 + 300 + 30)

    def test_record_keeps_five_newest(self):
        s = {}
        for i in range(7):
            s = P.record(s, "切り抜き", i)
        self.assertEqual(s["切り抜き"], [6, 5, 4, 3, 2])
        orig = {"切り抜き": [1]}
        P.record(orig, "切り抜き", 9)
        self.assertEqual(orig, {"切り抜き": [1]})


class SlowTest(unittest.TestCase):
    def test_boundary(self):
        self.assertFalse(P.slow(0, 0, 599999))
        self.assertTrue(P.slow(0, 0, 600000))
        self.assertFalse(P.slow(0, 500000, 1000000))
        self.assertTrue(P.slow(0, 500000, 1100000))
        self.assertFalse(P.slow(700000, 0, 1000000))


class TextTest(unittest.TestCase):
    S = {"index": 2, "total": 5, "label": "見どころを探す", "detail": ""}

    def test_blocked(self):
        self.assertEqual(P.text(None, None, False, blocked={"freeGB": 3.2, "minGB": 10}),
                         "パソコンの空きが少ないので待っています(あと 7 GB 空けると始まります)")
        self.assertEqual(P.text(None, None, False, blocked={"freeGB": 9.9, "minGB": 10}),
                         "パソコンの空きが少ないので待っています(あと 1 GB 空けると始まります)")
        self.assertEqual(P.text(None, None, False), "")   # 段も待ちも無い

    def test_eta_formats(self):
        s = self.S
        self.assertEqual(P.text(s, 30, False), "2/5 見どころを探す・あと 1 分ほど")
        self.assertEqual(P.text(s, 60, False), "2/5 見どころを探す・あと約 1 分")
        self.assertEqual(P.text(s, 80 * 60, False), "2/5 見どころを探す・あと約 1 時間 20 分")
        self.assertEqual(P.text(s, 2 * 3600, False), "2/5 見どころを探す・あと約 2 時間")


if __name__ == "__main__":
    unittest.main()
