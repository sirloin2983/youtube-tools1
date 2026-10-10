# -*- coding: utf-8 -*-
"""flow/tx(② 文字起こしの動詞。役割で組み直す RS6 a-3)の最小のテスト。編集の serve を読まずに、疑似のエンジンで使う。

    py -3.10 -m unittest src/flow/tests/test_tx.py -v

- transcribe_clip: ① clipjob の行に、② が文書の機械の分 fields(recognition.runs・params)と後処理の記録を足す
- write_clip_records・write_machine_doc: 記録と機械の分の文書を作業データ(ytt/workdata の TX_DIR)に書く
- 受付の check_model・2 つ目のエンジンの engine_ready(疑似)・再認識の end_whole・note_vad・時刻の候補 word_retime(単語なし)
通しの動き(ジョブ・文書・画面)は編集のテスト(src/editor/tests/test_metrics.py ほか。serve の名前で読む)。
"""
import os
os.environ.setdefault("YTT_DATA_DIR", "inplace")   # 作業データは読み書きしない(一時フォルダだけ)。ほかのテストとそろえる
import json
import shutil
import sys
import tempfile
import unittest
from unittest import mock

SRC = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))   # tests -> flow -> src
sys.path.insert(0, SRC)
from flow import tx  # noqa: E402
from pipeline.transcribe import backend, recognize, roster  # noqa: E402
from ytt import errors, tools, workdata  # noqa: E402

ROWS = [{"start": 0.0, "end": 2.0, "text": "テスト文1", "avg_logprob": -0.3, "words": [(0.0, 2.0, "テスト文1")]},
        {"start": 2.0, "end": 4.0, "text": "テスト文2", "avg_logprob": -0.3}]
SPEC = {"start": 0.0, "end": 4.0, "whole": True, "duration": 4.0, "language": "ja", "wordSplit": False, "stripPunct": True,
        "glossary": [], "glossAuto": [], "context": {"members": [], "terms": []}, "autoFill": False, "autoLlm": False, "stripNames": False,
        "model": "small", "engine": "faster-whisper", "beam": 5, "vadMode": "weak", "boost": False, "splitChars": 24,
        "title": "題名", "sourcePath": "C:/x/a.mp4", "sourceName": "a.mp4"}


class _FakeEngine(backend.Backend):
    name = backend.FAKE_NAME

    def transcribe(self, job, spec, wav, total, real):
        job["state"], job["device"] = "running", "cpu"
        return iter([dict(r) for r in ROWS])

    def engine_ids(self, spec, real):
        return "fake", ""


class _Env(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="flowtx_")
        for mod, name, value in ((workdata, "TX_DIR", self.tmp), (workdata, "TMP_DIR", self.tmp), (workdata, "ROOT", self.tmp), (tools, "media_duration", lambda path: 4.0),
                                 (recognize, "extract_audio", lambda job, spec, wav: None),
                                 (roster, "ROSTER", os.path.join(self.tmp, "no-roster.json"))):
            p = mock.patch.object(mod, name, value)
            p.start()
            self.addCleanup(p.stop)
        saved = backend._selector[0]
        backend.set_selector(lambda: _FakeEngine())
        self.addCleanup(backend.set_selector, saved)

    def tearDown(self):
        shutil.rmtree(self.tmp, True)


class TestTranscribe(_Env):
    def clip(self):
        job = {"id": "j1", "cancel": False, "state": "queued"}
        return job, tx.transcribe_clip(job, dict(SPEC), os.path.join(self.tmp, "w.wav"), [])

    def test_fields_are_the_machine_part(self):
        job, clip = self.clip()
        f = clip["fields"]
        self.assertEqual([g["text"] for g in f["segments"]], ["テスト文1", "テスト文2"])
        self.assertEqual(f["original"], clip["original"])
        self.assertEqual(len(f["recognition"]["runs"]), 1)
        run = f["recognition"]["runs"][0]
        self.assertEqual((run["engine"], run["model"], run["device"], run["audioSec"]), ("fake", "small", "cpu", 4.0))
        self.assertEqual(f["params"]["dict"], run["settings"]["dict"])
        self.assertNotIn("fill", run)   # 後処理を使っていなければ記録も無い
        for key in ("title", "sourcePath", "clip", "evalSet", "id"):   # 題名・動画・clip・評価用は ③ が足す
            self.assertNotIn(key, f)

    def test_records_and_machine_doc(self):
        _job, clip = self.clip()
        tx.write_clip_records("abc123def456", clip, SPEC)
        with open(os.path.join(self.tmp, "abc123def456.words.json"), encoding="utf-8") as fp:
            self.assertEqual(json.load(fp)["words"], [[0.0, 2.0, "テスト文1"]])
        self.assertTrue(os.path.isfile(os.path.join(self.tmp, "abc123def456.asr.json")))
        self.assertFalse(os.path.exists(os.path.join(self.tmp, "abc123def456.llm.json")))   # LLM を使っていない
        for stage in ("transcribe", "post"):   # 成果物の鍵(RS6 b-K1)。post は transcribe の hash を材料にする
            self.assertTrue(os.path.isfile(os.path.join(self.tmp, "abc123def456.%s.key.json" % stage)), stage)
        path = tx.write_machine_doc("abc123def456", clip["fields"], SPEC)
        with open(path, encoding="utf-8") as fp:
            doc = json.load(fp)
        self.assertEqual((doc["schema"], doc["id"], doc["title"], doc["sourcePath"]), ("transcribe/v1", "abc123def456", "題名", "C:/x/a.mp4"))
        self.assertEqual(doc["createdAt"], clip["fields"]["updatedAt"])
        self.assertEqual(len(doc["segments"]), 2)
        with self.assertRaises(errors.ApiError):
            tx.write_machine_doc("../x", clip["fields"])


class TestSmallVerbs(_Env):
    def test_check_model(self):
        self.assertEqual(tx.check_model("small"), "small")
        self.assertEqual(tx.check_model("../x", fallback="large-v3"), "large-v3")
        with self.assertRaises(errors.ApiError) as cm:
            tx.check_model("../x")
        self.assertEqual(cm.exception.code, "bad_model")

    def test_engine_ready_fake(self):
        self.assertEqual(tx.engine_ready("whisper.cpp"), (True, ""))   # 疑似は常に使える

    def test_note_vad_and_end_whole(self):
        job = {}
        self.assertEqual(tx.note_vad(job, None), "")
        self.assertNotIn("vadNote", job)
        note = tx.note_vad(job, {"used": "off", "retries": [{"mode": "weak"}]})
        self.assertTrue(note)
        self.assertEqual(job["vadNote"], note)
        with mock.patch.object(recognize, "drop_resume") as drop:
            tx.end_whole({"mode": "range", "tid": "t"})
            drop.assert_not_called()
            tx.end_whole({"mode": "whole", "tid": "t"})
            drop.assert_called_once_with("t")

    def test_word_retime_without_words(self):
        self.assertIsNone(tx.word_retime("abc123def456", [], ["s1"], "faster-whisper"))


if __name__ == "__main__":
    unittest.main()
