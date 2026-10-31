"""主の文字起こしを Haas(speech.cpp)に替える 1 か所(段 3。src/flow/tx.py の main_engine)と、Haas が読めなかった時に whisper.cpp で読み直す守り
(src/pipeline/transcribe/recognize.py の transcribe_rows)の単体テスト。認識は偽物(音・窓を出さない)。

実行(リポジトリ直下から): py -3.12 -m unittest tests/flow/test_haas_main.py -v
"""
import os
import sys
import unittest
from unittest import mock

os.environ.setdefault("YTT_DATA_DIR", "inplace")
ROOT = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "src")
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from flow import tx as FT  # noqa: E402
from pipeline.transcribe import recognize as RC, tx_engines as E  # noqa: E402
from ytt import errors as _errors  # noqa: E402


class MainEngineTest(unittest.TestCase):
    def pick(self, req, model="large-v3", ready=True, env=None):
        with mock.patch.object(E.HaasSpeechCpp, "ready", classmethod(lambda cls, d: (ready, ""))), \
                mock.patch.dict(os.environ, env or {}, clear=False):
            if env is None:
                os.environ.pop(FT.HAAS_MAIN_ENV, None)
            return FT.main_engine(req, model)

    def test_old_main_goes_to_haas(self):
        for req in ({}, {"engine": "whisper.cpp"}, {"device": "cuda"}, {"device": "auto"}):
            r, m = self.pick(dict(req))
            self.assertEqual((r["engine"], r["device"], m), ("haas-speechcpp", "vulkan", "haas-ja-v1.0"), req)
        r, m = self.pick({"device": "cpu"})
        self.assertEqual((r["engine"], r["device"]), ("haas-speechcpp", "cpu"))

    def test_choice_cpu(self):
        with mock.patch.object(FT._txbase, "speech_choice", return_value={"ok": True, "device": "cpu"}):
            r, m = self.pick({"device": "vulkan"})
        self.assertEqual((r["engine"], r["device"]), ("haas-speechcpp", "cpu"))   # この PC の試しで CPU でだけ動いた

    def test_keeps_whisper(self):
        self.assertEqual(self.pick({}, ready=False), ({}, "large-v3"))                       # speech.cpp が置いていない(友人の PC は段 5 まで)
        self.assertEqual(self.pick({}, env={FT.HAAS_MAIN_ENV: "off"}), ({}, "large-v3"))     # スイッチで戻す
        self.assertEqual(self.pick({"engine": "haas"}, model="haas-ja-v1.0"), ({"engine": "haas"}, "haas-ja-v1.0"))   # 名指しの頼み(声の材料)
        self.assertEqual(self.pick({}, model="small"), ({}, "small"))


class FallbackTest(unittest.TestCase):
    def test_haas_failure_reads_again_with_whisper(self):
        seen = []

        class Back:
            def transcribe(self, job, spec, wav, total, real):
                seen.append(spec["engine"])
                if spec["engine"] == "haas-speechcpp":
                    raise _errors.ApiError("engine_failed", "speech worker が終わりました", 500)
                yield {"start": 0.0, "end": 1.0, "text": "あい", "words": [], "wordProbs": [], "avg_logprob": -0.2, "no_speech_prob": 0.0, "compression_ratio": 1.0}

        spec = {"engine": "haas-speechcpp", "model": "haas-ja-v1.0", "device": "vulkan", "start": 0.0, "end": 1.0, "wordSplit": False, "stripPunct": True}
        job = {}
        with mock.patch.object(RC, "extract_audio"), mock.patch.object(RC._tools, "media_duration", return_value=1.0), \
                mock.patch.object(RC._backend, "select", return_value=Back()), mock.patch.object(RC, "haas_voice", return_value=None):
            out = RC.transcribe_rows(job, spec, "a.wav")
        self.assertEqual(seen, ["haas-speechcpp", "whisper.cpp"])
        self.assertEqual((spec["engine"], spec["model"], spec["device"]), ("whisper.cpp", "large-v3", "vulkan"))
        self.assertEqual([r["text"] for r in out["rows"]], ["あい"])
        self.assertTrue(any("whisper.cpp で読み直しました" in w for w in job.get("warnings") or []))

    def test_other_errors_go_up(self):
        class Back:
            def transcribe(self, job, spec, wav, total, real):
                raise _errors.ApiError("cancelled_by_user", "x", 400)
                yield None

        spec = {"engine": "haas-speechcpp", "model": "haas-ja-v1.0", "start": 0.0, "end": 1.0}
        with mock.patch.object(RC, "extract_audio"), mock.patch.object(RC._tools, "media_duration", return_value=1.0), \
                mock.patch.object(RC._backend, "select", return_value=Back()):
            with self.assertRaises(_errors.ApiError):
                RC.transcribe_rows({}, spec, "a.wav")


if __name__ == "__main__":
    unittest.main()
