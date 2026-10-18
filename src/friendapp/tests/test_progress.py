# -*- coding: utf-8 -*-
"""friendapp/progress.py の確かめ(F3-3)。ファイルもネットも使わない。

    py -3.10 -m unittest src/friendapp/tests/test_progress.py
"""
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, os.path.dirname(os.path.dirname(HERE)))
import progress as P   # noqa: E402


def st(key, state, detail=""):
    return {"key": key, "label": key, "state": state, "detail": detail}


class ClassifyTest(unittest.TestCase):
    def check(self, text, code, kind="url"):
        r = P.classify(text, kind)
        self.assertEqual(r["code"], code, text)
        self.assertEqual(r["detail"], text)
        return r

    def test_members(self):
        self.check("Join this channel to get access", "members")
        self.check("メンバー限定の動画です", "members")
        self.assertEqual(P.classify("members only")["retry"], False)

    def test_bot(self):
        r = self.check("方法1(区間取得): ERROR: [youtube] x: Sign in to confirm you’re not a bot. Use --cookies-from-browser", "bot")
        self.assertTrue(r["retry"])
        self.assertEqual((r["retryMax"], r["retryEvery"]), (1, 1800))   # 間を空けて 1 回だけ
        self.assertIn("YouTube に一時的に止められました", r["message"])
        self.check("Sign in to confirm you�fre not a bot", "bot")   # 化けた文でも当たる
        self.check("HTTP Error 429: Too Many Requests", "bot")
        self.check("Sign in to confirm your age. Use --cookies-from-browser", "unknown")   # 年齢の確認は別(bot ではない)
        self.assertNotIn("retryMax", P.classify("timed out"))

    def test_unavailable(self):
        self.check("この動画は非公開です", "unavailable")
        self.check("Private video. Sign in", "unavailable")
        self.check("Video unavailable", "unavailable")
        self.check("This live event will begin in 5 minutes.", "unavailable")
        self.check("まだ公開されていません", "unavailable")

    def test_no_archive(self):
        self.check("アーカイブが出ませんでした", "noArchive")
        self.check("アーカイブがまだ作られていません", "noArchive")
        self.check("no archive found for this stream", "noArchive")

    def test_range_over(self):
        self.check("区間が配信の長さを超えています", "rangeOver")
        self.check("requested range is out of range", "rangeOver")
        self.check("区間が長すぎます(3 時間まで)", "rangeOver")

    def test_range_over_not_for_file(self):
        self.check("区間が配信の長さを超えています", "unknown", kind="file")

    def test_disk(self):
        self.check("パソコンの空きが足りません", "disk")
        self.check("[Errno 28] No space left on device", "disk")
        self.assertTrue(P.classify("disk full")["retry"])

    def test_net(self):
        self.check("ネットにつながりませんでした", "net")
        self.check("<urlopen error [Errno 11001] getaddrinfo failed>", "net")
        self.check("ConnectionError: timed out", "net")
        self.assertTrue(P.classify("HTTP Error 503: Service Unavailable")["retry"])

    def test_transcribe(self):
        self.check("文字起こしの部品が見つかりません", "transcribe")
        self.check("whisper.cpp exited with code 1", "transcribe")
        self.assertFalse(P.classify("CUDA error")["retry"])

    def test_dropbox(self):
        self.check("Dropbox の鍵が無い", "dropbox")
        self.check("invalid_grant: refresh token expired", "dropbox")
        self.assertTrue(P.classify("expired_access_token")["retry"])

    def test_no_highlights(self):
        self.check("見どころが見つかりませんでした", "noHighlights")
        self.check("切り抜く所が見つかりませんでした", "noHighlights")
        self.check("no highlights were found", "noHighlights")
        self.check("候補が 0 件です", "noHighlights")

    def test_cancelled(self):
        self.check("止めました", "cancelled")
        self.check("Job cancelled by user", "cancelled")

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

    def test_elapsed_longer_than_average(self):
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

    def test_change_resets(self):
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

    def test_eta_formats(self):
        s = self.S
        self.assertEqual(P.text(s, 30, False), "2/5 見どころを探す・あと 1 分ほど")
        self.assertEqual(P.text(s, 60, False), "2/5 見どころを探す・あと約 1 分")
        self.assertEqual(P.text(s, 80 * 60, False), "2/5 見どころを探す・あと約 1 時間 20 分")
        self.assertEqual(P.text(s, 2 * 3600, False), "2/5 見どころを探す・あと約 2 時間")

    def test_none_stage(self):
        self.assertEqual(P.text(None, None, False), "")


if __name__ == "__main__":
    unittest.main()
