# -*- coding: utf-8 -*-
"""flow/tools(段が道具を呼ぶ継ぎ目。役割で組み直す RS6 b-0)のテスト。  py -3.10 -m unittest src/flow/tests/test_tools.py -v

- LocalTools: 入口なしで 動画ファイル → 文字起こし → パック を 1 本(疑似のエンジン。疑似の差し込みはテストの側 = eval/fake/fake_asr の FAKE)
- LocalTools に無い段(配信・解析・採用・書き出し・話者分離)は「入口に頼んでください」の StepError
- HttpTools は今の API をそのまま呼ぶ(呼ぶ API と本文は src/home/tests/test_autorun.py が見る)
"""
import os
os.environ.setdefault("YTT_DATA_DIR", "inplace")   # 作業データは読み書きしない(一時フォルダだけ)
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

SRC = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))   # tests -> flow -> src
sys.path.insert(0, SRC)
from flow import run as R, tools as T  # noqa: E402
from pipeline.transcribe import backend, roster  # noqa: E402
from ytt import workdata  # noqa: E402
from eval.fake import fake_asr  # noqa: E402  (疑似の認識。flow は eval を読めないので、テストの側で差し込む)


def _make_video(path, sec=6):
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc=size=160x284:rate=30:duration=%d" % sec,
                    "-f", "lavfi", "-i", "sine=frequency=440:duration=%d" % sec, "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac",
                    "-shortest", path], check=True, timeout=120)


class TestHttpTools(unittest.TestCase):
    def test_calls_the_tool_api(self):
        calls = []

        class C:
            def call(self, tool, method, path, body=None):
                calls.append((tool, method, path, body))
                return 200, {"id": "j1", "jobs": [{"id": "j1"}], "items": [{"qid": "q1"}]}

            def ok(self, tool, method, path, body=None):
                return self.call(tool, method, path, body)[1]
        t = T.HttpTools(C())
        self.assertEqual(t.transcribe_start({"model": "small"}, bundle={"x": 1}), "j1")
        self.assertEqual(t.jobs(), [{"id": "j1"}])
        self.assertEqual(t.analyze_items(), [{"qid": "q1"}])
        t.edit("a b")
        self.assertEqual(t.docs(), [])
        self.assertEqual(calls, [("transcribe", "POST", "/api/transcribe", {"model": "small"}), ("transcribe", "GET", "/api/jobs", None),
                                 ("studio", "GET", "/api/queue", None), ("transcribe", "GET", "/api/edit?id=a%20b", None)])


class TestLocalRefuses(unittest.TestCase):
    def test_steps_that_need_the_portal(self):
        t = T.LocalTools()
        for f in (lambda: t.video("abcdefghijk"), lambda: t.analyze_add({}, {}), lambda: t.adopt_top("v", 1), lambda: t.export_start({}),
                  lambda: t.diarize_start({})):
            with self.assertRaisesRegex(R.StepError, "入口"):
                f()
        with self.assertRaisesRegex(R.StepError, "入口"):
            R.run(None, {"videoId": "abcdefghijk"}, tools=T.LocalTools())

    def test_no_data_dir(self):
        """作業データの置き場所が決まっていなければ、文字起こしのジョブは失敗(段は StepError)"""
        with mock.patch.object(workdata, "TX_DIR", None):
            t = T.LocalTools()
            jid = t.transcribe_start({"sourcePath": __file__})
            self.assertEqual(t.jobs()[0]["state"], "error")
            self.assertIn("置き場所", t.jobs()[0]["error"])
            self.assertEqual(t.jobs()[0]["id"], jid)


@unittest.skipUnless(shutil.which("ffmpeg"), "ffmpeg が無い")
class TestLocalTranscribePack(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="flowtools_")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        data = os.path.join(self.tmp, "data")
        for name, value in (("ROOT", self.tmp), ("DATA_DIR", data), ("TX_DIR", os.path.join(data, "transcripts")), ("TMP_DIR", os.path.join(data, "transcripts", ".tmp")),
                            ("SETTINGS", os.path.join(data, "settings.json"))):
            p = mock.patch.object(workdata, name, value)
            p.start()
            self.addCleanup(p.stop)
        p = mock.patch.object(roster, "ROSTER", os.path.join(self.tmp, "no-roster.json"))
        p.start()
        self.addCleanup(p.stop)
        p = mock.patch.dict(os.environ, {"TRANSCRIBE_FAKE_DELAY": "0"})
        p.start()
        self.addCleanup(p.stop)
        saved = backend._selector[0]
        backend.set_selector(lambda: fake_asr.FAKE)
        self.addCleanup(backend.set_selector, saved)
        self.video = os.path.join(self.tmp, "clip", "切り抜き.mp4")
        os.makedirs(os.path.dirname(self.video))
        _make_video(self.video)

    def test_file_then_pack(self):
        """動画ファイル → 文字起こし(② flow/tx の動詞で文書を書く)→ 同じ道具で 文書 → パック(① build_pack を直に)"""
        tools = T.LocalTools()
        spec = {"post": {"autoLlm": False}, "pack": {"volume": 100}}
        r1 = R.run(None, {"path": self.video}, spec=spec, tools=tools)
        self.assertEqual(r1.step("transcribe")["state"], "done", r1.steps)
        tid = r1.doc_id
        self.assertTrue(os.path.isfile(os.path.join(workdata.TX_DIR, tid + ".json")))
        self.assertTrue(os.path.isfile(os.path.join(workdata.TX_DIR, tid + ".asr.json")))
        doc = tools.docs()[0]
        self.assertEqual((doc["id"], doc["sourcePath"], doc["count"] > 0), (tid, os.path.abspath(self.video), True))
        self.assertTrue(doc["segments"][0]["text"].startswith("テスト文"))
        r2 = R.run(None, {"docId": tid}, spec=spec, tools=tools)
        self.assertEqual([s["state"] for s in r2.steps], ["skip", "done"], r2.steps)
        self.assertEqual(len(r2.packs), 1)
        names = os.listdir(r2.packs[0])
        self.assertTrue(any(n.endswith(".lua") for n in names), names)
        # もう一度: 同じ名前のパックがあるので上書きしない(409 exists = 段は飛ばす)
        r3 = R.run(None, {"docId": tid}, spec=spec, tools=tools)
        self.assertEqual(r3.step("pack")["state"], "skip", r3.steps)


if __name__ == "__main__":
    unittest.main()
