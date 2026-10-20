# -*- coding: utf-8 -*-
"""flow/tx(② 文字起こしの動詞)の最小のテスト。編集の serve を読まずに、疑似のエンジンで使う。

    py -3.12 -m unittest src/flow/tests/test_tx.py -v

- transcribe_clip の fields に ③ の分が入らない
- write_clip_records・write_machine_doc: 機械の分の文書と機械の層を作業データ(ytt/workdata の TX_DIR)か案件の 作業用 に書く・書けないとき
- 受付の check_model・2 つ目のエンジンの engine_ready(疑似)・再認識の note_vad・時刻の候補 word_retime(単語なし)
本物の通し(ジョブ・fields の行と記録・words.json・asr.json・鍵)は src/editor/tests/test_worker.py の RealWorkerTest。
"""
import os
os.environ.setdefault("YTT_DATA_DIR", "inplace")   # 作業データは読み書きしない(一時フォルダだけ)。ほかのテストとそろえる
import json
import sys
import unittest
from unittest import mock

SRC = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))   # tests -> flow -> src
sys.path.insert(0, SRC)
from ytt.tests import testkit  # noqa: E402
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

    def engine_ready(self, engine, real):
        return True, ""   # 疑似は常に使える(backend の口。OPT-E2 1a-2)


class _Env(unittest.TestCase):
    def setUp(self):
        self.tmp = testkit.tempdir(self, "flowtx_")
        for mod, name, value in ((workdata, "TX_DIR", self.tmp), (workdata, "TMP_DIR", self.tmp), (workdata, "ROOT", self.tmp), (tools, "media_duration", lambda path: 4.0),
                                 (recognize, "extract_audio", lambda job, spec, wav: None),
                                 (roster, "ROSTER", os.path.join(self.tmp, "no-roster.json"))):
            p = mock.patch.object(mod, name, value)
            p.start()
            self.addCleanup(p.stop)
        saved = backend._selector[0]
        backend.set_selector(lambda: _FakeEngine())
        self.addCleanup(backend.set_selector, saved)


class TestTranscribe(_Env):
    def clip(self):
        job = {"id": "j1", "cancel": False, "state": "queued"}
        return job, tx.transcribe_clip(job, dict(SPEC), os.path.join(self.tmp, "w.wav"), [])

    def test_fields_are_the_machine_part(self):
        """題名・動画・clip・評価用・id は ③ が足す(② の fields に無い)。行・記録・words.json・asr.json・鍵は本物の通し src/editor/tests/test_worker.py"""
        _job, clip = self.clip()
        for key in ("title", "sourcePath", "clip", "evalSet", "id"):
            self.assertNotIn(key, clip["fields"])

    def test_machine_doc(self):
        """write_machine_doc(入口なしの道 = CLI・まとめて実行。編集の画面のジョブは ③ が書く)"""
        _job, clip = self.clip()
        path = tx.write_machine_doc("abc123def456", clip["fields"], SPEC)
        with open(path, encoding="utf-8") as fp:
            doc = json.load(fp)
        self.assertEqual((doc["schema"], doc["id"], doc["title"], doc["sourcePath"]), ("transcribe/v1", "abc123def456", "題名", "C:/x/a.mp4"))
        self.assertEqual(doc["createdAt"], clip["fields"]["updatedAt"])
        self.assertEqual(len(doc["segments"]), 2)
        with self.assertRaises(errors.ApiError):
            tx.write_machine_doc("../x", clip["fields"])

    def test_machine_doc_into_case_folder(self):
        """folder(placement.doc_home が決めた 作業用)を渡すと、本体を案件に書いてから索引を TX_DIR に(RS8 B2-2)"""
        from ytt import docloc, schemas
        _job, clip = self.clip()
        wd = os.path.join(self.tmp, "out", "題名", schemas.WORK_DIR)
        os.makedirs(os.path.dirname(wd))
        path = tx.write_machine_doc("abc123def456", clip["fields"], SPEC, wd)
        self.assertEqual(path, os.path.join(os.path.normpath(wd), "abc123def456.json"))
        self.assertEqual(docloc.placed("abc123def456"), os.path.normpath(wd))
        self.assertFalse(os.path.exists(os.path.join(self.tmp, "abc123def456.json")))
        tx.write_clip_records("abc123def456", clip, SPEC)   # 横のファイルは索引に従って案件へ
        self.assertTrue(os.path.isfile(os.path.join(wd, "abc123def456.asr.json")))
        self.assertTrue(os.path.isfile(os.path.join(wd, "abc123def456.transcribe.key.json")))
        self.assertTrue(os.path.isfile(os.path.join(wd, "abc123def456.mach.json")))   # 機械の層も文書と同じ所(RS8 O2-2)
        self.assertFalse(os.path.exists(os.path.join(self.tmp, "abc123def456.mach.json")))

    def read(self, name):
        with open(os.path.join(self.tmp, name), encoding="utf-8") as fp:
            return json.load(fp)

    def test_machine_layer(self):
        """② は機械の層 <id>.mach.json(fields の行)を書く。人の層があれば文書は ③ の物なので書かない (r8t。RS8 O2-2)"""
        from ytt import schemas
        _job, clip = self.clip()
        tx.write_machine_doc("abc123def456", clip["fields"], SPEC)
        mach = self.read("abc123def456.mach.json")
        self.assertEqual((mach["schema"], mach["rev"]), (schemas.MACH_SCHEMA, 1))
        self.assertEqual([r["text"] for r in mach["rows"]], ["テスト文1", "テスト文2"])
        testkit.write_json(os.path.join(self.tmp, "abc123def456.hum.json"), {"schema": schemas.HUM_SCHEMA, "rows": []})
        doc_before = self.read("abc123def456.json")
        fields = dict(clip["fields"], segments=[dict(clip["fields"]["segments"][0], text="新しい")])
        path = tx.write_machine_doc("abc123def456", fields, SPEC)
        self.assertEqual(path, os.path.join(self.tmp, "abc123def456.json"))
        self.assertEqual(self.read("abc123def456.json"), doc_before)   # 文書は書かない
        mach = self.read("abc123def456.mach.json")
        self.assertEqual((mach["rev"], [r["text"] for r in mach["rows"]]), (2, ["新しい"]))
        with mock.patch.dict(os.environ, {"TRANSCRIBE_LAYERS": "off"}):   # 古いスイッチが残っていても層を見る
            tx.write_machine_doc("abc123def456", fields, SPEC)
        self.assertEqual(self.read("abc123def456.json"), doc_before)
        self.assertEqual(self.read("abc123def456.mach.json")["rev"], 3)

    def test_machine_layer_primary(self):
        """層が正(RS8 O2-3): 人の層が無ければ 機械の層 → 写し(composedFrom = 機械の層の rev)。人の層があれば機械の層だけ。
        新しい文書(folder)は 写し → 機械の層。機械の層を書けなければ写しに版を付けない"""
        from ytt import schemas
        _job, clip = self.clip()
        tx.write_machine_doc("abc123def456", clip["fields"], SPEC)
        self.assertEqual(self.read("abc123def456.json")[schemas.COMPOSED_FROM], {"mach": 1, "hum": None})
        tx.write_machine_doc("abc123def456", clip["fields"], SPEC)
        self.assertEqual(self.read("abc123def456.json")[schemas.COMPOSED_FROM], {"mach": 2, "hum": None})
        self.assertEqual(self.read("abc123def456.mach.json")["rev"], 2)
        testkit.write_json(os.path.join(self.tmp, "abc123def456.hum.json"), {"schema": schemas.HUM_SCHEMA, "rev": 1, "rows": []})
        before = self.read("abc123def456.json")
        tx.write_machine_doc("abc123def456", clip["fields"], SPEC)
        self.assertEqual(self.read("abc123def456.json"), before)   # 写しは ③ が組み立て直す
        self.assertEqual(self.read("abc123def456.mach.json")["rev"], 3)
        wd = os.path.join(self.tmp, "out", "題名", schemas.WORK_DIR)
        os.makedirs(os.path.dirname(wd))
        path = tx.write_machine_doc("bbb123def456", clip["fields"], SPEC, wd)
        with open(path, encoding="utf-8") as fp:
            self.assertEqual(json.load(fp)[schemas.COMPOSED_FROM], {"mach": 1, "hum": None})
        self.assertTrue(os.path.isfile(os.path.join(wd, "bbb123def456.mach.json")))
        with mock.patch.object(tx._yschemas, "make_mach", side_effect=OSError("disk")), self.assertLogs("tx", level="WARNING"):
            tx.write_machine_doc("ccc123def456", clip["fields"], SPEC)
        self.assertNotIn(schemas.COMPOSED_FROM, self.read("ccc123def456.json"))

    def test_machine_layer_failure_keeps_doc(self):
        _job, clip = self.clip()
        with mock.patch.object(tx._yschemas, "make_mach", side_effect=OSError("disk")), self.assertLogs("tx", level="WARNING"):
            path = tx.write_machine_doc("abc123def456", clip["fields"], SPEC)
        self.assertTrue(os.path.isfile(path))


class TestSmallVerbs(_Env):
    def test_check_model(self):
        self.assertEqual(tx.check_model("small"), "small")
        self.assertEqual(tx.check_model("../x", fallback="large-v3"), "large-v3")
        with self.assertRaises(errors.ApiError) as cm:
            tx.check_model("../x")
        self.assertEqual(cm.exception.code, "bad_model")

    def test_engine_ready_fake(self):
        self.assertEqual(tx.engine_ready("whisper.cpp"), (True, ""))   # 疑似は常に使える

    def test_note_vad(self):
        job = {}
        self.assertEqual(tx.note_vad(job, None), "")
        self.assertNotIn("vadNote", job)
        note = tx.note_vad(job, {"used": "off", "retries": [{"mode": "weak"}]})
        self.assertTrue(note)
        self.assertEqual(job["vadNote"], note)

    def test_word_retime_without_words(self):
        self.assertIsNone(tx.word_retime("abc123def456", [], ["s1"]))


if __name__ == "__main__":
    unittest.main()
