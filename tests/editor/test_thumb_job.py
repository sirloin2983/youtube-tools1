#!/usr/bin/env python3
"""サムネの案(ジョブ ed_thumb.py → thumb_ideas.py → ① thumb_cards)のテスト。

    py -3.12 -m unittest tests/eval/drill/test_metrics.py   # test_metrics がこのファイルのテストも読み込む
    py -3.12 -m unittest tests/editor/test_thumb_job.py

通し(本物の ffmpeg で 12 秒の見本の動画から 6 案を描く): 指定の検査・作っている最中は 409 → ジョブ → 作業用/<名前>_thumb-ideas.png と .json →
GET の形。見本の音は 6 秒の所だけ大きく、文書には 字幕に出さない行・カットした行・空の行・長い行・感情の強い行・文書の開始の秒 を混ぜて、
時刻の選び方(点数の順・3 秒あける・足りない分は均等)と型ごとの文字(行の折り返し・…・一語)を案の記録で確かめる。
コマンドの道(動画のパスから文書を探す・文書なし・アバターの矩形へ寄せる)も 1 枚描く。
単体は切り取りの箱の計算だけ(出来上がった絵からは読めない)。
"""
import json
import os
os.environ.setdefault("YTT_DATA_DIR", "inplace")   # テストは作業データを本物の置き場所に書かない(ytt.datadir)
import shutil
import struct
import subprocess
import sys
import tempfile
import unittest

TESTS = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(TESTS)), "src", "editor"))
sys.path.insert(0, TESTS)
from test_backend import TID, StoreDir  # noqa: F401,E402  (S = serve)
from human.proof import store as _store  # noqa: E402
from ytt import settings as _settings  # noqa: E402
from human.proof import doc_jobs  # noqa: E402
from flow import jobs  # noqa: E402
from pipeline.export import thumb_cards as _cards  # noqa: E402  (crop_box・W・H は ① の名前)
import ed_state  # noqa: E402
import ed_thumb  # noqa: E402
import thumb_ideas  # noqa: E402

HAVE_FF = bool(shutil.which("ffmpeg"))


def _have_font():
    try:
        _cards.font_path()
        return True
    except _cards.ThumbError:
        return False


def _drop_jobs(match):
    """このテストのジョブを表から外す(ほかのテストの run_job に拾われないように)"""
    with jobs._jobs_lock:
        for k in [k for k, j in jobs._jobs.items() if match(j)]:
            jobs._jobs.pop(k, None)


# 文書の秒 = 動画の秒 + 100(文書の開始)。字幕に出さない行・カットした行・空の行は案に使わない
SEGMENTS = [{"id": "s0", "start": 100.0, "end": 100.4, "text": "前の行です"},
            {"id": "s1", "start": 100.5, "end": 102.0, "text": "こんにちは"},
            {"id": "s2", "start": 102.2, "end": 103.8, "text": "うわーーー！！なんで！？"},   # いちばん感情が強い = 3.0 秒
            {"id": "s3", "start": 104.0, "end": 105.0, "text": "えっ", "noSub": True},
            {"id": "s4", "start": 105.0, "end": 105.5, "text": "やばい", "cutState": "cut"},
            {"id": "s5", "start": 105.6, "end": 105.9, "text": ""},
            {"id": "s6", "start": 106.0, "end": 108.0, "text": "今日は絶妙なバランスが好きなんだよねほんとに"},   # 感情の言葉 1 つ(点数 3 < 音)
            {"id": "s7", "start": 110.0, "end": 111.5, "text": "ちょっと待ってよ"}]   # 2 番目 = 10.75 秒


@unittest.skipUnless(HAVE_FF and _have_font(), "ffmpeg と日本語のフォントが必要")
class TestThumbJob(StoreDir):
    @classmethod
    def setUpClass(cls):
        cls.src_dir = tempfile.mkdtemp()
        cls.video = os.path.join(cls.src_dir, "切り抜き.mp4")
        # 映像は止まった絵(場面の切り替わりなし)・音は 6.05〜6.45 秒だけ(0.5 秒ごとの音の大きさで 6.25 秒が 1 つだけ大きい)
        subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin", "-y", "-f", "lavfi", "-i", "color=c=0x336699:s=320x180:r=30:d=12",
                        "-f", "lavfi", "-i", "aevalsrc='if(between(t,6.05,6.45),0.5*sin(2*PI*440*t),0)':s=44100:d=12",
                        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", cls.video],
                       check=True, timeout=120, stdin=subprocess.DEVNULL)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.src_dir, ignore_errors=True)

    def setUp(self):
        super().setUp()
        self.put_doc({"id": TID, "title": "サムネの試し", "start": 100.0, "sourcePath": self.video, "updatedAt": 123, "segments": SEGMENTS})

    def tearDown(self):
        _drop_jobs(lambda j: (j.get("spec") or {}).get("sourcePath") == self.video)
        shutil.rmtree(os.path.join(self.src_dir, "作業用"), ignore_errors=True)
        super().tearDown()

    def png_size(self, path):
        with open(path, "rb") as f:
            head = f.read(24)
        self.assertEqual(head[:8], b"\x89PNG\r\n\x1a\n")
        return struct.unpack(">II", head[16:24])

    def test_thumb_through(self):
        # 作る前: 無い・画像は 404・切り取りの値・文書が無い
        self.assertEqual(ed_thumb.thumb_info(TID)["ok"], False)
        with self.assertRaises(ed_state.ApiError) as cm:
            ed_thumb.thumb_image_path(TID)
        self.assertEqual(cm.exception.status, 404)
        with self.assertRaises(ed_state.ApiError) as cm:
            ed_thumb.thumb_spec(TID, {"crop": "zoom"})
        self.assertEqual(cm.exception.status, 400)
        with self.assertRaises(ed_state.ApiError):
            ed_thumb.thumb_spec("0123456789ac", {})
        # 画面が選んだ切り取りは編集の設定 thumbCrop に覚える(矩形の zoom は設定にできない)
        self.assertTrue(_settings.patch_settings({"values": {"thumbCrop": "right"}})["ok"])
        self.assertEqual(_settings.load_settings()["thumbCrop"], "right")
        with self.assertRaises(ed_state.ApiError):
            _settings.patch_settings({"values": {"thumbCrop": "zoom"}})
        # ジョブ(既定 = 中央と右下を交互)。待っている間にもう一度 → 409
        spec = ed_thumb.thumb_spec(TID, {})
        self.assertEqual((spec["crop"], spec["sourcePath"], spec["title"]), ("alt", self.video, "サムネの案: サムネの試し"))
        job = jobs.add_job(spec, "thumb")
        self.assertEqual(job["tid"], TID)
        with self.assertRaises(ed_state.ApiError) as cm:
            ed_thumb.thumb_spec(TID, {})
        self.assertEqual(cm.exception.status, 409)
        doc_jobs.run_job(job)
        self.assertEqual(job["state"], "done", job.get("error"))
        png, js = ed_thumb.thumb_paths(self.video)
        self.assertEqual(os.path.dirname(png), os.path.join(self.src_dir, "作業用"))
        self.assertEqual(self.png_size(png), (_cards.W * 2, _cards.H * 3))   # 2 列 × 3 行
        with open(js, encoding="utf-8") as f:
            rec = json.load(f)
        self.assertEqual((rec["schema"], rec["doc"], rec["video"]), ("youtube-tools-thumb-ideas/v1", TID, self.video))
        info = ed_thumb.thumb_info(TID)
        self.assertTrue(info["ok"])
        self.assertEqual((len(info["cards"]), info["crops"], info["file"]), (6, ["center", "right"], "切り抜き_thumb-ideas.png"))
        self.assertEqual(ed_thumb.thumb_image_path(TID), png)
        with open(_store.tx_path(TID), encoding="utf-8") as f:
            self.assertEqual(json.load(f)["updatedAt"], 123)   # 文書は読むだけ
        # 時刻: 点数の順(感情の強い行 3.0・10.75 → 音の大きい 6.25)に 3 秒あけて選び、足りない分を均等に(12 秒 × 1/7・3/7・4/7。2/7 は 3.0 に近すぎる)
        got = [(c["n"], c["layout"], c["from"], c["crop"]) for c in info["cards"]]
        self.assertEqual(got, [(1, "A", "even", "center"), (2, "B", "row", "right"), (3, "C", "even", "center"),
                               (4, "D", "loud", "right"), (5, "E", "even", "center"), (6, "F", "row", "right")])
        at = [c["at"] for c in info["cards"]]
        for a, want in zip(at, (12 / 7, 3.0, 12 * 3 / 7, 6.25, 12 * 4 / 7, 10.75)):
            self.assertAlmostEqual(a, want, delta=0.06)
        # 型ごとの文字: A = 前の行 + 2 行 / B = 6 字で 2 行(記号のあとで切る・続く！は 1 つに)/ C = 9 字で 2 行(入りきらなければ …)/
        # D = 感情の言葉 1 つ / E・F = 10 字で 4 行まで(助詞のあとで切る)
        texts = [(c["top"], c["lines"], c["word"]) for c in info["cards"]]
        self.assertEqual(texts, [("前の行です", ["こんにちは"], None),
                                 (None, ["うわーーー!", "なんで!?"], None),
                                 (None, ["今日は絶妙なバラン", "スが好きなんだよ…"], None),
                                 (None, [], "好き"),
                                 (None, ["今日は絶妙なバランス", "が好きなんだよね", "ほんとに"], None),
                                 (None, ["ちょっと待ってよ"], None)])
        # コマンドの道: 動画のパスから文書を探す(作業データの文書の根でないフォルダ = そのまま並べて読む)・文書なし・アバターの矩形へ寄せる
        self.assertEqual(thumb_ideas.find_doc(self.video, tdir=self.tmp)["id"], TID)
        self.assertIsNone(thumb_ideas.find_doc(os.path.join(self.src_dir, "other.mp4"), tdir=self.tmp))
        out = os.path.join(self.tmp, "コマンド", "案.png")
        out_png, rec2 = thumb_ideas.make(self.video, None, None, out, "alt", (200, 100, 60, 60))
        self.assertEqual(self.png_size(out_png), (_cards.W * 2, _cards.H * 3))
        self.assertEqual([c["crop"] for c in rec2["cards"]], ["center", "zoom"] * 3)
        self.assertEqual([(c["lines"], c["word"]) for c in rec2["cards"]][:4], [([], None), ([], None), ([], None), ([], "…")])
        self.assertIsNone(rec2["doc"])
        # 動画が無くなった文書は断る
        self.put_doc({"id": TID, "title": "x", "sourcePath": os.path.join(self.src_dir, "無い.mp4"), "segments": []})
        with self.assertRaises(ed_state.ApiError):
            ed_thumb.thumb_spec(TID, {})


class TestWordRe(unittest.TestCase):
    def test_words_not_inside_other_words(self):
        """感情の言葉は語の途中に当てない(「において」の「おい」・「好きなんです」の「なんで」・「おいしい」)。文の頭・句読点のあとには当てる"""
        for t in ("私においては", "好きなんです", "おいしいね"):
            self.assertEqual(thumb_ideas.WORD_RE.findall(t), [] if "好き" not in t else ["好き"], t)
        self.assertEqual(thumb_ideas.one_word("なんでやねん"), "なんで")
        self.assertEqual(thumb_ideas.one_word("え、おい！"), "おい")
        self.assertEqual(thumb_ideas.one_word("それは無理"), "無理")


class TestCropBox(unittest.TestCase):
    def test_crop_box(self):
        """切り取りの箱(中央は縦いっぱい・右下へ寄せる・矩形を含む 9:16 の箱は画面の中に収める)"""
        self.assertEqual(_cards.crop_box("center", 1920, 1080), (607, 1080, 656, 0))
        cw, ch, x, y = _cards.crop_box("right", 1920, 1080)
        self.assertEqual((x + cw, y + ch), (1920, 1080))
        cw, ch, x, y = _cards.crop_box("zoom", 1920, 1080, (800, 200, 300, 400))
        self.assertTrue(x <= 800 and x + cw >= 1100 and y <= 200 and y + ch >= 600)
        self.assertTrue(0 <= x and x + cw <= 1920 and 0 <= y and y + ch <= 1080)


if __name__ == "__main__":
    unittest.main()
