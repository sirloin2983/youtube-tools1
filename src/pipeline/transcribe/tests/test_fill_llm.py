# -*- coding: utf-8 -*-
"""pipeline/transcribe の fill(認識のあとの後処理 A・B・C・D)と llm(LLM の後処理 E)を、編集の serve・ed_state を読まずに使うテスト(役割で組み直す RS2-9)。

    py -3.10 -m unittest src/pipeline/transcribe/tests/test_fill_llm.py -v

細かい決まり(置き換えの 3 倍の条件・名簿の呼び名・検査と上限・ジョブの記録)は編集のテスト(src/editor/tests/test_fill.py・test_llm.py。serve の名前で読む)が確かめる。
ここは「① が serve なしで読めて、名簿のファイルは roster.ROSTER・作業データの置き場所は ytt/workdata(RS3-0A まで txenv の口)・疑似かどうかは backend・話者判別の部品の有無は diarize.has_sherpa から読む」ことと、
読み込みでネイティブの部品・app・eval を読まないことだけ。
"""
import os
os.environ.setdefault("YTT_DATA_DIR", "inplace")   # 作業データは読み書きしないが、ほかのテストとそろえる
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

SRC = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))   # tests -> transcribe -> pipeline -> src
sys.path.insert(0, SRC)
from pipeline.transcribe import backend, diarize, fill, llm, roster  # noqa: E402
from ytt import errors, studiodata, workdata  # noqa: E402


class _FakeBackend(backend.Backend):
    """eval/fake/fake_asr の FakeBackend と同じ口 fill_reader・llm_ask(この層のテストは eval を読まない。RS5-D)"""
    name = "fake"

    def fill_reader(self, job, spec, wav, real):
        text = os.environ.get("TRANSCRIBE_FAKE_FILL", "")
        return lambda s0, e0: [{"start": s0, "end": e0, "text": text}] if text else []

    def llm_ask(self, job, spec, real):
        reply = os.environ.get("TRANSCRIBE_FAKE_LLM", "")
        return lambda messages: reply


class _Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.roster = os.path.join(self.tmp, "roster.json")
        with open(self.roster, "w", encoding="utf-8") as f:
            json.dump({"groups": [{"id": "t", "label": "試し", "names": ["テスト分子"]}],
                       "members": [{"name": "テスト分子", "aliases": ["テスト分", "てすとぶん"]}]}, f, ensure_ascii=False)
        self.addCleanup(self._restore)
        for mod, name, value in ((roster, "ROSTER", self.roster), (workdata, "TX_DIR", self.tmp), (studiodata, "studio_stream", lambda vid: {})):
            p = mock.patch.object(mod, name, value)   # 試験の間だけ(終わったら元に戻す)
            p.start()
            self.addCleanup(p.stop)

    def _restore(self):
        backend.set_selector(lambda: backend.REAL)
        shutil.rmtree(self.tmp, ignore_errors=True)


class TestFill(_Base):
    def test_names_and_aliases_from_roster_file(self):
        """名簿のファイルは呼ぶたびに roster.ROSTER から(ed_state を読まない)"""
        names = fill.fill_spk_names({"glossary": ["マリン"], "context": {"terms": ["ぺこら"]}})
        self.assertTrue({"テスト分子", "テスト分", "マリン", "ぺこら"} <= names)
        self.assertEqual(fill.fill_aliases(), {"テスト分子", "テスト分", "てすとぶん"})
        other = os.path.join(self.tmp, "none.json")   # 無い名簿は空(読めなくても止めない)
        roster.ROSTER = other
        self.assertEqual(fill.fill_aliases(), set())

    def test_reader_fake_follows_backend_select(self):
        """窓の読みは backend.select() の口 fill_reader(RS5-D)。疑似は環境変数 TRANSCRIBE_FAKE_FILL の文字を窓いっぱいの 1 行に"""
        backend.set_selector(lambda: _FakeBackend())
        with mock.patch.dict(os.environ, {"TRANSCRIBE_FAKE_FILL": "別の読み"}):
            read = fill.fill_reader({}, {}, "w.wav")
            self.assertEqual(read(1.0, 3.0), [{"start": 1.0, "end": 3.0, "text": "別の読み"}])
        with mock.patch.dict(os.environ, {"TRANSCRIBE_FAKE_FILL": ""}):
            self.assertEqual(fill.fill_reader({}, {}, "w.wav")(1.0, 3.0), [])

    def test_reader_without_sherpa_is_api_error_from_diarize_has_sherpa(self):
        """本物の読み(SenseVoice)は話者判別の部品 sherpa-onnx が要る。有無は diarize.has_sherpa から(呼ぶたびに読む = patch.object が届く)。無ければ ytt.errors.ApiError"""
        with mock.patch.object(diarize, "has_sherpa", lambda: False):
            with self.assertRaises(errors.ApiError) as cm:
                fill.fill_reader({}, {}, "w.wav")
        self.assertEqual(cm.exception.code, "no_sherpa")

    def test_after_rows_warns_and_keeps_rows_without_sherpa(self):
        """読めないときは文字起こしを失敗にせず、ジョブに警告を足して whisper の結果のまま(警告は txbase.add_warning)"""
        rows = [{"start": 0.0, "end": 4.0, "text": "テスト文1"}]
        job = {"phase": "x"}
        with mock.patch.object(diarize, "has_sherpa", lambda: False):
            out, rec, read = fill.fill_after_rows(job, {"autoFill": True}, rows, "w.wav", 8.0)
        self.assertEqual((out, read), (rows, None))
        self.assertEqual((rec["windows"], rec["rows"], rec["dup"]), (0, 0, 0))
        self.assertEqual(len(job["warnings"]), 1)
        self.assertEqual(job["phase"], "x")
        self.assertEqual(fill.fill_after_rows({}, {}, rows, "w.wav", 8.0), (rows, None, None))   # 設定オフは何もしない


class TestLlm(_Base):
    def test_path_write_read_from_workdata_tx_dir(self):
        self.assertEqual(llm.llm_path("abcdefabcde1"), os.path.join(self.tmp, "abcdefabcde1.llm.json"))
        self.assertIsNone(llm.read_llm("abcdefabcde1"))
        llm.llm_write("abcdefabcde1", {"engine": "llama-text", "model": "qwen3-8b"}, [{"row": 0, "from": "あ", "to": "い"}])
        raw = llm.read_llm("abcdefabcde1")
        self.assertEqual((raw["schema"], raw["engine"], raw["items"]), (llm.LLM_SCHEMA, "llama-text", [{"row": 0, "from": "あ", "to": "い"}]))
        os.remove(llm.llm_path("abcdefabcde1"))
        with open(llm.llm_path("abcdefabcde1"), "w", encoding="utf-8") as f:
            f.write('{"schema": "other", "items": []}')   # 形が違えば None
        self.assertIsNone(llm.read_llm("abcdefabcde1"))

    def test_ask_fn_fake_follows_backend_select(self):
        backend.set_selector(lambda: _FakeBackend())
        with mock.patch.dict(os.environ, {"TRANSCRIBE_FAKE_LLM": '{"edits": []}'}):
            self.assertEqual(llm.llm_ask_fn({}, {})([{"role": "user", "content": "x"}]), '{"edits": []}')

    def test_after_doc_fixes_with_roster_file(self):
        """設定オフは何もしない・名簿の呼び名に 1 字違いの所があれば疑似の答えで直し、fill と印を付ける。選んだ所が無ければ LLM を呼ばない"""
        backend.set_selector(lambda: _FakeBackend())
        reply = json.dumps({"edits": [{"from": "テスト文", "to": "テスト分", "confidence": 0.9}]})
        spec = {"autoLlm": True, "title": "テスト分の配信", "sourcePath": "E:/v.mp4"}
        self.assertEqual(llm.llm_after_doc({}, {"title": "x"}, []), (None, None))
        segs = [{"id": "s1", "start": 0.0, "end": 4.0, "text": "テスト文1", "speaker": "", "flag": ""}]
        with mock.patch.dict(os.environ, {"TRANSCRIBE_FAKE_LLM": reply}):
            rec, items = llm.llm_after_doc({}, spec, segs)
        self.assertEqual((rec["picked"], rec["proposed"], rec["applied"]), (1, 1, 1))
        self.assertEqual((segs[0]["text"], segs[0]["fill"]), ("テスト分1", {"from": "テスト文1", "by": "llm"}))
        self.assertTrue(segs[0]["flag"].startswith(llm.LLM_FLAG))
        self.assertEqual(len(items), 1)
        calls = []
        other = [{"id": "s1", "start": 0.0, "end": 4.0, "text": "こんにちは", "speaker": "", "flag": ""}]
        with mock.patch.object(llm, "llm_ask_fn", side_effect=lambda job, spec: calls.append(1)):
            rec, items = llm.llm_after_doc({}, spec, other)
        self.assertEqual((rec["picked"], items, calls), (0, None, []))

    def test_after_doc_failure_is_warning_not_error(self):
        """LLM の読み込みに失敗しても文字起こしは止めない(警告は txbase.add_warning)"""
        def boom(job, spec):
            raise errors.ApiError("engine_failed", "llama-server が起動の途中で止まりました", 500)
        job = {}
        segs = [{"id": "s1", "start": 0.0, "end": 4.0, "text": "テスト文1", "speaker": "", "flag": ""}]
        with mock.patch.object(llm, "llm_ask_fn", side_effect=boom):
            rec, items = llm.llm_after_doc(job, {"autoLlm": True, "title": "テスト分の配信"}, segs)
        self.assertIsNone(items)
        self.assertIn("llama-server", rec["error"])
        self.assertEqual(segs[0]["text"], "テスト文1")
        self.assertTrue(any("LLM" in w for w in job["warnings"]))


class TestImportsAlone(unittest.TestCase):
    def test_no_native_app_or_eval(self):
        """fill・llm は numpy などのネイティブの部品・serve と ed_*(app)・eval を読まずに import できる"""
        code = ("import sys; sys.path.insert(0, %r); from pipeline.transcribe import fill, llm; "
                "native = ('numpy', 'faster_whisper', 'ctranslate2', 'sherpa_onnx', 'onnxruntime'); "
                "bad = [m for m in sys.modules if m in native or m.startswith('ed_') or m == 'serve' or m == 'eval' or m.startswith('eval.')]; "
                "print(bad); sys.exit(1 if bad else 0)") % SRC
        p = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=60)
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)


if __name__ == "__main__":
    unittest.main()
