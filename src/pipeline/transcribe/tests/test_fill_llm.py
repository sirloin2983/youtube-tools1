# -*- coding: utf-8 -*-
"""pipeline/transcribe の fill(認識のあとの後処理 A・B・C・D)と llm(LLM の後処理 E)のテスト。編集の serve・ed_state は読まない。

    py -3.12 -m unittest src/pipeline/transcribe/tests/test_fill_llm.py -v

- TestRealParts: 本物の部品で 1 回ずつ通す。窓の読み = SenseVoice small(sherpa-onnx・CPU)・LLM = Qwen3-4B(llama-server・Vulkan。LLM の通しはこの 1 本だけ)。
  声の見本は Windows の音声合成でファイルに書く(スピーカーへは出さない)。モデルは本物の作業データの transcribe の中から読むだけ(tx_engines.ENGINE_DIR)。
  取得の口(fetch_file)は差し替え、無ければ飛ばす(ネットへ取りに行かない)。部品・モデル・音声合成が無い PC では飛ばす。
- 規則の答え(行の並びの見本を後処理の入口に通す)は test_postproc.py。ここに残すのは通しで起こせない物(部品が無い・LLM が落ちる・壊れた記録)だけ。
"""
import os
os.environ.setdefault("YTT_DATA_DIR", "inplace")   # 作業データは一時フォルダだけ。ほかのテストとそろえる
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
import wave
from unittest import mock

SRC = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))   # tests -> transcribe -> pipeline -> src
sys.path.insert(0, SRC)
from ytt import testkit, tools  # noqa: E402
from pipeline.transcribe import backend, diarize, fill, llm, models, roster, tx_engines, worker_client  # noqa: E402
from ytt import errors, studiodata, workdata  # noqa: E402

REAL_HOME = os.path.join(os.environ.get("LOCALAPPDATA") or "", "youtube-tools", "transcribe")   # 本物のモデルの置き場所(読むだけ)
_VOICES = {"ja": "Microsoft Haruka Desktop", "en": "Microsoft Zira Desktop"}
_SAY_PS = ("$ErrorActionPreference='Stop'; Add-Type -AssemblyName System.Speech; $s = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
           "foreach ($l in (Get-Content -LiteralPath $env:YTT_SAY_LIST -Encoding UTF8)) { $p = $l -split \"`t\"; "
           "$s.SelectVoice($p[0]); $s.SetOutputToWaveFile($p[1]); $s.Speak($p[2]); $s.SetOutputToNull() }")


def say_wav(path, parts, gap=0.6):
    """parts = [("ja" | "en", 文)] を Windows の音声合成で 1 つの 16kHz・モノラルの wav に書く(スピーカーへは出さない。あいだに gap 秒の無音。
    en は 0.7 倍の速さで低くして別の人の声にする)。-> [(始め, 終わり)](声の区間の秒)。音声合成か ffmpeg が無ければ None"""
    ff = shutil.which("ffmpeg")
    if os.name != "nt" or not ff:
        return None
    d = tempfile.mkdtemp(prefix="ytt-say-")
    try:
        with open(os.path.join(d, "list.txt"), "w", encoding="utf-8") as f:
            f.write("\n".join("%s\t%s\t%s" % (_VOICES[v], os.path.join(d, "%d.wav" % i), t) for i, (v, t) in enumerate(parts)))
        r = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", _SAY_PS], capture_output=True, timeout=60,
                           env=dict(os.environ, YTT_SAY_LIST=os.path.join(d, "list.txt")), creationflags=tools.no_window_flags())
        if r.returncode:
            return None
        spans, t, args, fil = [], 0.0, [], ""
        for i, (v, _text) in enumerate(parts):
            w = os.path.join(d, "%d.wav" % i)
            with wave.open(w) as x:
                rate, sec = x.getframerate(), x.getnframes() / x.getframerate()
            low = "asetrate=%d," % int(rate * 0.7) if v == "en" else ""
            sec = sec / 0.7 if low else sec
            spans.append((round(t, 3), round(t + sec, 3)))
            t += sec + gap
            args += ["-i", w]
            fil += "[%d:a]%saresample=16000,aformat=channel_layouts=mono,apad=pad_dur=%s[a%d];" % (i, low, gap, i)
        fil += "".join("[a%d]" % i for i in range(len(parts))) + "concat=n=%d:v=0:a=1[o]" % len(parts)
        subprocess.run([ff, "-hide_banner", "-loglevel", "error", "-nostdin", "-y"] + args + ["-filter_complex", fil, "-map", "[o]", "-ar", "16000", "-ac", "1", path],
                       check=True, timeout=60, capture_output=True, creationflags=tools.no_window_flags())
        return spans
    except (OSError, subprocess.SubprocessError):
        return None
    finally:
        shutil.rmtree(d, ignore_errors=True)


def _have_sherpa():
    try:
        import sherpa_onnx  # noqa: F401
    except ImportError:
        return False
    return True


def _sense_voice_ready():
    spec = tx_engines.SENSE_VOICE_MODELS[fill.FILL_MODEL]
    mdir = os.path.join(tx_engines.sv_model_dir(REAL_HOME), spec["dir"])
    return _have_sherpa() and all(os.path.isfile(os.path.join(mdir, p)) for p in spec["parts"])


def _llm_ready(name):
    spec = tx_engines.LLAMA_TEXT_MODELS[name]["model"]
    p = os.path.join(REAL_HOME, "models", tx_engines.LlamaText.MODEL_SUBDIR, spec["file"])
    exe = os.path.join(tx_engines.llama_bin_dir(REAL_HOME), tx_engines.LLAMA_EXE)
    return os.path.isfile(exe) and os.path.isfile(p) and os.path.getsize(p) == spec["size"]


def _fetch_read_only(spec, folder, *a, **kw):
    """取得の口の代わり: 手元にあればそのパス(中身の SHA-256 は読み直さない)。無ければ取りに行かずに失敗"""
    p = os.path.join(folder, spec["file"])
    if os.path.isfile(p) and os.path.getsize(p) == spec["size"]:
        return p
    raise AssertionError("モデルを取りに行こうとした: %s" % p)


class TestRealParts(unittest.TestCase):
    """本物の部品をこのプロセスの中で読む(認識ワーカーの中と同じ道 = worker_client.IN_WORKER)"""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="ytt-fill-real-")
        cls.wav = os.path.join(cls.tmp, "a.wav")
        cls.spans = say_wav(cls.wav, [("ja", "こんにちは、今日はみんなでゲームをします。よろしくお願いします。")])

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def setUp(self):
        if not self.spans:
            self.skipTest("音声合成か ffmpeg が無い")
        self.enterContext(mock.patch.dict(os.environ, {"HF_HUB_OFFLINE": "1", "TRANSCRIBE_NO_FETCH": "1"}))
        for mod, name, value in ((worker_client, "IN_WORKER", True), (tx_engines, "ENGINE_DIR", REAL_HOME), (tx_engines, "fetch_file", _fetch_read_only),
                                 (studiodata, "studio_stream", lambda vid: None)):
            self.enterContext(mock.patch.object(mod, name, value))
        self.enterContext(mock.patch.dict(models._models, {}, clear=True))
        self.addCleanup(self._close_models)
        backend.set_selector(lambda: backend.REAL)

    @staticmethod
    def _close_models():
        for m in list(models._models.values()):   # llama-server を残さない
            getattr(m, "close", lambda: None)()

    @unittest.skipUnless(_sense_voice_ready(), "sherpa-onnx か SenseVoice のモデルが無い")
    def test_sense_voice_fills_sparse_row(self):
        a, b = self.spans[0]
        rows = [{"start": a, "end": b, "text": "こんにちは"}]   # 声は 6 秒あるのに 5 字(文字の少ない行)
        job = {"cancel": False}
        out, rec, read = fill.fill_after_rows(job, {"autoFill": True, "language": "ja"}, rows, self.wav, b + 0.6)
        self.assertFalse(job.get("warnings"), job.get("warnings"))
        self.assertEqual((rec["engine"], rec["windows"], rec["rows"]), ("sense-voice", 1, 1))
        self.assertEqual(out[0]["fill"], {"from": "こんにちは", "by": "sense-voice"})
        self.assertGreaterEqual(fill.fill_chars(out[0]["text"]), 15, out[0]["text"])
        self.assertIn("ゲーム", out[0]["text"])
        whole = read(0.0, b + 0.6)                           # D の全体の読みも同じ読み口
        self.assertTrue(whole and all(r["start"] >= 0 and r["end"] <= b + 0.6 + 0.01 for r in whole), whole)
        self.assertEqual(set(models._models), {(fill.FILL_MODEL, "cpu", fill.FILL_ENGINE)})

    @unittest.skipUnless(_llm_ready("qwen3-4b"), "llama-server か Qwen3-4B のモデルが無い")
    def test_llm_fixes_roster_name(self):
        path = os.path.join(self.tmp, "roster.json")
        testkit.write_json(path, {"groups": [], "members": [{"name": "雪花ラミィ", "aliases": ["ラミィ", "ラミィちゃん"], "common": []}]})
        segs = [{"id": "s%d" % i, "start": float(i), "end": i + 1.0, "text": t, "speaker": "", "flag": ""}
                for i, t in enumerate(["こんばんは", "今日は雑談をします", "生き花ラミーちゃんが好き", "ありがとう", "またね"])]
        job = {"cancel": False}
        with mock.patch.object(roster, "ROSTER", path):
            rec, items = llm.llm_after_doc(job, {"autoLlm": True, "llmModel": "qwen3-4b", "title": "雪花ラミィの配信", "sourcePath": "E:/v.mp4"}, segs)
        self.assertNotIn("error", rec)
        self.assertEqual((rec["model"], rec["picked"]), ("qwen3-4b", 1))
        self.assertGreaterEqual(rec["proposed"], 1)
        self.assertEqual([it["row"] for it in items], [2] * len(items))
        self.assertEqual([g["text"] for g in segs[:2] + segs[3:]], ["こんばんは", "今日は雑談をします", "ありがとう", "またね"])   # 選んでいない行は変えない
        if rec["applied"]:
            self.assertEqual((segs[2]["text"], segs[2]["fill"]), ("生き花ラミィちゃんが好き", {"from": "生き花ラミーちゃんが好き", "by": "llm"}))


class _Base(unittest.TestCase):
    def setUp(self):
        self.tmp = testkit.tempdir(self)
        self.roster = os.path.join(self.tmp, "roster.json")
        testkit.write_json(self.roster, {"groups": [{"id": "t", "label": "試し", "names": ["テスト分子"]}],
                                         "members": [{"name": "テスト分子", "aliases": ["テスト分", "てすとぶん"]}]})
        self.addCleanup(backend.set_selector, lambda: backend.REAL)
        for mod, name, value in ((roster, "ROSTER", self.roster), (workdata, "TX_DIR", self.tmp), (studiodata, "studio_stream", lambda vid: {})):
            self.enterContext(mock.patch.object(mod, name, value))   # 試験の間だけ(終わったら元に戻す)


class TestFailures(_Base):
    def test_missing_parts_and_failures_are_warnings(self):
        """部品 sherpa-onnx が無い(有無は呼ぶたびに diarize.has_sherpa)・LLM が起動の途中で落ちる・名簿が無い: 文字起こしは止めず、警告を足して認識の結果のまま"""
        rows = [{"start": 0.0, "end": 4.0, "text": "テスト文1"}]
        job = {"phase": "x"}
        with mock.patch.object(diarize, "has_sherpa", lambda: False):
            with self.assertRaises(errors.ApiError) as cm:
                fill.fill_reader({}, {}, "w.wav")
            self.assertEqual(cm.exception.code, "no_sherpa")
            out, rec, read = fill.fill_after_rows(job, {"autoFill": True}, rows, "w.wav", 8.0)
        self.assertEqual((out, read, (rec["windows"], rec["rows"], rec["dup"]), len(job["warnings"]), job["phase"]), (rows, None, (0, 0, 0), 1, "x"))
        self.assertEqual(fill.fill_after_rows({}, {}, rows, "w.wav", 8.0), (rows, None, None))   # 設定オフは何もしない

        def boom(job, spec):
            raise errors.ApiError("engine_failed", "llama-server が起動の途中で止まりました", 500)
        job = {}
        segs = [{"id": "s1", "start": 0.0, "end": 4.0, "text": "テスト文1", "speaker": "", "flag": ""}]
        with mock.patch.object(llm, "llm_ask_fn", side_effect=boom):
            rec, items = llm.llm_after_doc(job, {"autoLlm": True, "title": "テスト分の配信"}, segs)
        self.assertEqual((items, segs[0]["text"]), (None, "テスト文1"))
        self.assertIn("llama-server", rec["error"])
        self.assertTrue(any("LLM" in w for w in job["warnings"]))
        calls = []
        with mock.patch.object(llm, "llm_ask_fn", side_effect=lambda job, spec: calls.append(1)):   # 選んだ所が無ければ LLM を読み込まない・設定オフは何もしない
            rec, items = llm.llm_after_doc({}, {"autoLlm": True, "title": "テスト分の配信"}, [dict(segs[0], text="こんにちは")])
        self.assertEqual((rec["picked"], items, calls, llm.llm_after_doc({}, {"title": "x"}, [])), (0, None, [], (None, None)))
        self.assertEqual(fill.fill_aliases(), {"テスト分子", "テスト分", "てすとぶん"})
        roster.ROSTER = os.path.join(self.tmp, "none.json")   # 無い名簿は空(読めなくても止めない)
        self.assertEqual(fill.fill_aliases(), set())

    def test_llm_record_and_broken_file(self):
        self.assertEqual(llm.llm_path("abcdefabcde1"), os.path.join(self.tmp, "abcdefabcde1.llm.json"))   # 置き場所は ytt/workdata の TX_DIR
        self.assertIsNone(llm.read_llm("abcdefabcde1"))
        llm.llm_write("abcdefabcde1", {"engine": "llama-text", "model": "qwen3-8b"}, [{"row": 0, "from": "あ", "to": "い"}])
        raw = llm.read_llm("abcdefabcde1")
        self.assertEqual((raw["schema"], raw["engine"], raw["items"]), (llm.LLM_SCHEMA, "llama-text", [{"row": 0, "from": "あ", "to": "い"}]))
        with open(llm.llm_path("abcdefabcde1"), "w", encoding="utf-8") as f:
            f.write('{"schema": "other", "items": []}')   # 形が違えば None
        self.assertIsNone(llm.read_llm("abcdefabcde1"))


if __name__ == "__main__":
    unittest.main()
