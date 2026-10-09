"""dev/thumb_ideas.py(サムネの案の試作。提案 P5 の S)のテスト。リポジトリ直下で:

    py -3.10 -m unittest dev/tests/test_thumb_ideas.py

作業データは使わない(文字起こしの文書は一時フォルダに作る)。最後の 1 件だけ ffmpeg で 4 秒の試しの動画を作って 1 枚を描く(ffmpeg が無ければ飛ばす)。
"""
import json
import os
import struct
import subprocess
import sys
import tempfile
import unittest

os.environ.setdefault("YTT_DATA_DIR", "inplace")
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # dev/ (道具の置き場所)
sys.path.insert(0, HERE)
import thumb_ideas as T  # noqa: E402


def row(a, b, text):
    return {"start": a, "end": b, "text": text}


class TextTest(unittest.TestCase):
    def test_lines_of(self):
        self.assertEqual(T.lines_of("うわー", 7, 2), ["うわー"])
        self.assertEqual(T.lines_of("全てにおいて絶妙なバランスが好きなんです", 10, 4), ["全てにおいて", "絶妙なバランスが", "好きなんです"])
        out = T.lines_of("あいうえおかきくけこさしすせそたちつてと", 6, 2)
        self.assertEqual(len(out), 2)
        self.assertTrue(out[-1].endswith("…"))
        self.assertTrue(all(len(s) <= 6 for s in out))
        self.assertEqual(T.lines_of("", 6, 2), [])

    def test_one_word_and_score(self):
        self.assertEqual(T.one_word("ちょっと待ってよ"), "ちょ")
        self.assertEqual(T.one_word("こんにちは"), "こんに")
        self.assertGreater(T.excite_score("うわーーー！！なんで！？"), T.excite_score("こんにちは"))
        self.assertEqual(T.excite_score("こんにちは"), 0)

    def test_row_at_and_card_texts(self):
        rows = [row(0, 2, "前の行です"), row(3, 5, "見えそうで見えないの好き"), row(6, 8, "ちょっと")]
        self.assertEqual(T.row_at(rows, 4)["text"], "見えそうで見えないの好き")
        self.assertEqual(T.row_at(rows, 5.6)["text"], "ちょっと")
        self.assertIsNone(T.row_at([], 1))
        a = T.card_texts("A", rows, 4)
        self.assertEqual(a["top"], "前の行です")
        self.assertTrue(a["lines"])
        self.assertEqual(T.card_texts("D", rows, 7)["word"], "ちょ")
        self.assertLessEqual(len(T.card_texts("E", rows, 4)["lines"]), 4)


class TimesTest(unittest.TestCase):
    def test_select_times_gap_and_fill(self):
        cands = [(10.0, 5, "loud"), (11.0, 4, "loud"), (20.0, 3, "row"), (0.1, 9, "scene")]
        got = T.select_times(cands, 60.0, n=4)
        self.assertEqual(len(got), 4)
        ts = [g[0] for g in got]
        self.assertIn(10.0, ts)
        self.assertNotIn(11.0, ts)   # 10 秒と 3 秒以上離れていない
        self.assertNotIn(0.1, ts)    # 頭すぎる
        self.assertEqual(ts, sorted(ts))
        self.assertTrue(any(g[2] == "even" for g in got))   # 足りない分は均等に

    def test_crop_box(self):
        self.assertEqual(T.crop_box("center", 1920, 1080), (607, 1080, 656, 0))
        cw, ch, x, y = T.crop_box("right", 1920, 1080)
        self.assertEqual((x + cw, y + ch), (1920, 1080))
        cw, ch, x, y = T.crop_box("zoom", 1920, 1080, (800, 200, 300, 400))
        self.assertTrue(x <= 800 and x + cw >= 1100 and y <= 200 and y + ch >= 600)
        self.assertTrue(0 <= x and x + cw <= 1920 and 0 <= y and y + ch <= 1080)

    def test_crops_for(self):
        self.assertEqual(T.crops_for("alt", None), ["center", "right", "center", "right", "center", "right"])
        self.assertEqual(T.crops_for("alt", (1, 2, 3, 4)), ["center", "zoom", "center", "zoom", "center", "zoom"])
        self.assertEqual(set(T.crops_for("center", (1, 2, 3, 4))), {"center"})


class DocTest(unittest.TestCase):
    def test_find_doc_by_path_and_rows(self):
        with tempfile.TemporaryDirectory() as tmp:
            video = os.path.join(tmp, "clip.mp4")
            open(video, "wb").close()
            d = {"id": "aaaaaaaaaaaa", "start": 10.0, "sourcePath": video,
                 "segments": [{"start": 11, "end": 12, "text": "あ"}, {"start": 12, "end": 13, "text": "い", "noSub": True},
                              {"start": 13, "end": 14, "text": "う", "cutState": "cut"}, {"start": 14, "end": 15, "text": ""}]}
            with open(os.path.join(tmp, "aaaaaaaaaaaa.json"), "w", encoding="utf-8") as f:
                json.dump(d, f)
            got = T.find_doc(video, tdir=tmp)
            self.assertEqual(got["id"], "aaaaaaaaaaaa")
            self.assertIsNone(T.find_doc(os.path.join(tmp, "other.mp4"), tdir=tmp))
            self.assertEqual(T.doc_rows(got), [{"start": 1.0, "end": 2.0, "text": "あ"}])
            self.assertEqual(T.doc_rows(None), [])

    def test_fpath(self):
        self.assertEqual(T.fpath("C:\\Windows\\Fonts\\a.ttc"), "'C\\:/Windows/Fonts/a.ttc'")


class RenderTest(unittest.TestCase):
    def test_make_png(self):
        ff = T.tools.find_tool("ffmpeg", "YTT_FFMPEG")
        if not ff:
            self.skipTest("ffmpeg が無い")
        try:
            T.font_path()
        except SystemExit:
            self.skipTest("日本語のフォントが無い")
        with tempfile.TemporaryDirectory() as tmp:
            video = os.path.join(tmp, "clip.mp4")
            subprocess.run([ff, "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc2=size=1280x720:rate=30:duration=4",
                            "-f", "lavfi", "-i", "sine=f=440:d=4", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", video], check=True)
            doc = {"id": "bbbbbbbbbbbb", "start": 0, "segments": [{"start": 1, "end": 2, "text": "うわーなんで!?"}, {"start": 2.5, "end": 3.5, "text": "ちょっと待って"}]}
            out, rec = T.make(video, doc, None, os.path.join(tmp, "ideas.png"))
            with open(out, "rb") as f:
                head = f.read(24)
            self.assertEqual(head[:8], b"\x89PNG\r\n\x1a\n")
            self.assertEqual(struct.unpack(">II", head[16:24]), (T.W * 2, T.H * 3))
            self.assertEqual(len(rec["cards"]), 6)
            with open(os.path.join(tmp, "ideas.json"), encoding="utf-8") as f:
                self.assertEqual(json.load(f)["schema"], "youtube-tools-thumb-ideas/v1")


if __name__ == "__main__":
    unittest.main()
