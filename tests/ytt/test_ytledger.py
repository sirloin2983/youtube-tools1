"""ytt/ytledger(YouTube への問い合わせの帳簿)。一時フォルダの帳簿だけ(本物の作業データには書かない)"""
import json
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "src"))
from ytt import ytledger as L  # noqa: E402

T0 = 1792900000.0


class LedgerTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.p = os.path.join(self.tmp, "logs", L.NAME)

    def test_weights_hits_lives_and_window(self):
        """重み = 取得 1・情報 0.2・録画中のライブ 0.5(終わりの行で外す)・直近 30 分だけ・当たりの種類・出どころを外す"""
        L.record("fetch", 1, src="tools", now=T0 - 3600, p=self.p)                 # 30 分より前 = 数えない
        L.record("light", 0.2, src="tools", now=T0 - 60, p=self.p)
        L.record("fetch", 1, ok=False, err="ERROR: Sign in to confirm you're not a bot", src="tools", now=T0 - 30, p=self.p)
        L.record("live", 0.5, src="recorder", id="r1", now=T0 - 7200, p=self.p)
        L.record("live", 0.5, src="recorder", id="r2", now=T0 - 7200, p=self.p)
        L.record("live-end", 0, src="recorder", id="r2", now=T0 - 600, p=self.p)
        L.record("fetch", 1, src="queue", now=T0 - 10, p=self.p)
        got = L.load(T0, exclude_src=("queue",), p=self.p)
        self.assertEqual((got["weight"], got["lives"]), (1.7, 1))                   # 0.2 + 1 + ライブ 1 本 0.5
        self.assertEqual(got["hits"], [(T0 - 30, "bot", "tools")])

    def test_ytdlp_weight_and_no_secrets(self):
        """yt-dlp の引数から重み(--version は数えない)・帳簿にキーや URL を書かない"""
        self.assertEqual(L.ytdlp_weight(["yt-dlp", "-f", "ba", "--", "https://youtu.be/x"]), 1.0)
        self.assertEqual(L.ytdlp_weight(["yt-dlp.exe", "--skip-download", "--write-subs", "--", "u"]), 0.2)
        self.assertEqual(L.ytdlp_weight(["yt-dlp", "-f", "ba", "--write-auto-subs", "--print", "after_move:filepath", "--", "u"]), 1.0)   # 音の取得(字幕も書く)は 1
        self.assertIsNone(L.ytdlp_weight(["yt-dlp", "--version"]))
        self.assertTrue(L.is_ytdlp([r"C:\x\yt-dlp.EXE", "-g"]))
        L.record("api", 0.2, src="api", now=T0, p=self.p)
        with open(self.p, encoding="utf-8") as f:
            row = json.loads(f.readline())
        self.assertEqual(set(row), {"at", "kind", "w", "ok", "src"})

    def test_day_counts_and_prune(self):
        L.record("fetch", 1, src="queue", now=T0 - 5 * 86400, p=self.p)
        L.record("fetch", 1, src="queue", now=T0, p=self.p)
        L.record("light", 0.2, ok=False, err="HTTP Error 429: Too Many Requests", src="tools", now=T0, p=self.p)
        dc = L.day_counts(T0 - 100, T0 + 100, p=self.p)
        self.assertEqual((dc["by"], dc["hits"]), ({"queue:fetch": 1, "tools:light": 1}, {"tools:rate": 1}))
        L.prune(T0, p=self.p)
        self.assertEqual(len(L.rows(0, p=self.p)), 2)                                # 3 日より古い行を消す

    def test_inplace_writes_nothing(self):
        self.assertIsNone(L.path({"YTT_DATA_DIR": "inplace"}))


if __name__ == "__main__":
    unittest.main()
