"""tools/eval_asr.py(文字起こしの精度を測る道具。計画 段0-2)のテスト。リポジトリ直下で:

    python -m unittest tools/test_eval_asr.py

作業データは一時フォルダに作る(本物の作業データは読まない)。run は偽の認識(TRANSCRIBE_BACKEND=fake)で流れだけ確かめる(ffmpeg が必要)。
"""
import hashlib
import io
import json
import os
import shutil
import sys
import tempfile
import unittest
import wave
from contextlib import redirect_stdout

os.environ.setdefault("YTT_DATA_DIR", "inplace")
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import eval_asr as E  # noqa: E402


def seg(i, a, b, text, proofed=True, tags=None, flag=""):
    g = {"id": "s%d" % i, "start": a, "end": b, "text": text, "speaker": "", "flag": flag}
    if proofed:
        g["proofed"] = True
    if tags:
        g["tags"] = tags
    return g


def silence_wav(path, sec):
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(16000)
        w.writeframes(b"\0\0" * int(16000 * sec))


def quiet(fn, *a):
    buf = io.StringIO()
    with redirect_stdout(buf):
        return fn(*a)


class EvalAsrTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="test_eval_asr_")
        self.data = os.path.join(self.tmp, "data")
        os.makedirs(os.path.join(self.data, "transcripts"))
        os.environ["TRANSCRIBE_FAKE_DELAY"] = "0"
        # 評価用: 置換 1(祭り→まつり)・重なり・人が足した行(抜け)・人が消した行(余分)・未校正の行(数えない)
        self.write("aaaaaaaaaaa1", evalSet=True, segments=[
            seg(1, 0.0, 4.0, "まつりが来た"), seg(2, 4.0, 8.0, "二人で話す", tags=["overlap"]), seg(3, 20.0, 22.0, "足した行"),
            seg(4, 30.0, 34.0, "まだ見ていない", proofed=False)],
            original=[{"start": 0.0, "end": 4.0, "text": "祭りが来た"}, {"start": 4.0, "end": 8.0, "text": "二人で話す"},
                      {"start": 12.0, "end": 13.0, "text": "ご視聴ありがとうございました"}, {"start": 30.0, "end": 34.0, "text": "まだ見てない"}])
        self.write("bbbbbbbbbbb2", segments=[seg(1, 0.0, 2.0, "学習用")], original=[{"start": 0.0, "end": 2.0, "text": "学習よう"}])

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def write(self, tid, **kw):
        doc = {"schema": "transcribe/v1", "id": tid, "title": tid, "sourcePath": "", "start": 0, "end": None, "language": "ja",
               "speakers": [], "updatedAt": 1, **kw}
        with open(os.path.join(self.data, "transcripts", tid + ".json"), "w", encoding="utf-8") as f:
            json.dump(doc, f, ensure_ascii=False)

    def snapshot(self):
        d = os.path.join(self.data, "transcripts")
        out = {}
        for n in sorted(os.listdir(d)):
            with open(os.path.join(d, n), "rb") as f:
                out[n] = hashlib.sha256(f.read()).hexdigest()
        return out

    def test_stored_counts_like_the_screen(self):
        before = self.snapshot()
        res = quiet(E.main, ["stored", "--data", self.data, "--no-save"])
        o = res["summary"]["overall"]
        self.assertEqual(res["meta"]["docs"], ["aaaaaaaaaaa1"])          # 既定は評価用だけ
        self.assertEqual(res["meta"]["mismatch"], [])                   # 画面の「認識精度の測定」と同じ数
        # 正解 = まつりが来た(6)+ 二人で話す(5)+ 足した行(4)= 15 字。祭り→まつり は置換 1・抜け 1(編集距離が最小の数え方)
        self.assertEqual(o["refChars"], 15)
        self.assertEqual(res["summary"]["byKind"]["両方にある"]["errs"], 2)
        self.assertEqual(res["summary"]["byKind"]["人が足した(抜け)"]["del"], 4)   # 人が足した行 = 抜け
        self.assertEqual(res["summary"]["byKind"]["人が消した(余分)"]["ins"], len("ご視聴ありがとうございました"))
        self.assertEqual(res["summary"]["byTag"]["声が重なる"]["refChars"], 5)
        self.assertEqual(res["summary"]["byTag"]["声が重なる"]["errs"], 0)
        self.assertTrue(all(g["start"] < 30 for g in res["groups"]))    # 未校正の行は数えない
        self.assertEqual(self.snapshot(), before)                       # 文書は書き換えない
        allres = quiet(E.main, ["stored", "--data", self.data, "--scope", "all", "--no-save"])
        self.assertEqual(sorted(allres["meta"]["docs"]), ["aaaaaaaaaaa1", "bbbbbbbbbbb2"])

    @unittest.skipUnless(shutil.which("ffmpeg"), "ffmpeg が無い")
    def test_run_recognizes_and_saves_without_touching_docs(self):
        os.environ["TRANSCRIBE_BACKEND"] = "fake"
        try:
            src = os.path.join(self.tmp, "clip.wav")
            silence_wav(src, 12.0)
            # 偽の認識は 4 秒ごとに「テスト文N」を出す
            self.write("ccccccccccc3", evalSet=True, sourcePath=src, start=0, end=12,
                       segments=[seg(1, 0.0, 4.0, "テスト文1"), seg(2, 4.0, 8.0, "テスト文2x"), seg(3, 8.0, 12.0, "テスト文3")], original=[])
            before = self.snapshot()
            res = quiet(E.main, ["run", "--data", self.data, "--docs", "ccccccccccc3", "--label", "fake-test"])
            o = res["summary"]["overall"]
            self.assertEqual((o["refChars"], o["sub"], o["del"], o["ins"]), (16, 0, 1, 0))   # 「x」が抜けた 1 字だけ
            self.assertEqual(res["meta"]["engine"]["engine"], "fake")
            self.assertEqual(res["meta"]["perDoc"][0]["audio"], "動画")
            self.assertGreater(res["meta"]["audioSec"], 11)
            self.assertEqual(self.snapshot(), before)                     # 文書は書き換えない
            saved = os.listdir(os.path.join(self.data, "evals", "asr"))
            self.assertEqual(len(saved), 1)
            self.assertTrue(saved[0].endswith("_fake-test.json"))
            # 元の動画が無ければ、保管データの全体の音声(文書の範囲の先頭 = 0 秒)で測る
            full = os.path.join(self.data, "dataset", "docs", "ccccccccccc3")
            os.makedirs(full)
            shutil.copy(src, os.path.join(full, "full.flac"))
            os.unlink(src)
            res2 = quiet(E.main, ["run", "--data", self.data, "--docs", "ccccccccccc3", "--no-save"])
            self.assertEqual(res2["meta"]["perDoc"][0]["audio"], "保管の音声")
            self.assertEqual(res2["summary"]["overall"]["errs"], 1)
        finally:
            os.environ.pop("TRANSCRIBE_BACKEND", None)

    def test_compare_same_docs(self):
        a = quiet(E.main, ["stored", "--data", self.data, "--label", "a"])
        pa = os.path.join(self.data, "evals", "asr", sorted(os.listdir(os.path.join(self.data, "evals", "asr")))[0])
        same = quiet(E.cmd_compare, pa, pa)
        self.assertEqual(same["diff"], 0)
        self.assertIn("差があるとは言えない", same["verdict"])
        # B: 置換の誤りを直した結果(文書を1本足して、文書ごとの差が出るように)
        b = json.loads(json.dumps(a))
        for g in b["groups"]:
            g["sub"] = 0
        pb = os.path.join(self.tmp, "b.json")
        with open(pb, "w", encoding="utf-8") as f:
            json.dump(b, f, ensure_ascii=False)
        out = quiet(E.cmd_compare, pa, pb)
        self.assertLess(out["diff"], 0)                                   # B の方が誤りが少ない
        self.assertEqual(out["docs"], 1)


if __name__ == "__main__":
    unittest.main()
