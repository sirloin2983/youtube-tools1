"""dev/eval_cloud.py(クラウドの文字起こしとの比較。計画 B2 = E1)のテスト。リポジトリ直下で:

    py -3.10 -m unittest dev/tests/test_eval_cloud.py

作業データは一時フォルダに作る(本物の作業データは読まない)。通信は http_json を差し替えて偽の応答にする(外へは何も送らない)。
音声の取り出しは ffmpeg が要る(無ければ run のテストは skip)。
"""
import io
import json
import os
import shutil
import sys
import tempfile
import unittest
import wave
from contextlib import redirect_stdout
from unittest import mock

os.environ.setdefault("YTT_DATA_DIR", "inplace")
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # dev/
sys.path.insert(0, HERE)
import eval_cloud as EC  # noqa: E402

KEY = "sk-test-secret-key-0123456789"


def seg(i, a, b, text, speaker="A"):
    return {"id": "s%d" % i, "start": a, "end": b, "text": text, "speaker": speaker, "flag": "", "proofed": True}


def silence_wav(path, sec):
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(16000)
        w.writeframes(b"\0\0" * int(16000 * sec))


def quiet(fn, *a):
    buf = io.StringIO()
    with redirect_stdout(buf):
        try:
            return fn(*a), buf.getvalue()
        except SystemExit as e:
            return e, buf.getvalue()


class RowsTest(unittest.TestCase):
    """応答 -> 行(通信しない)"""

    def test_words_grouped_by_speaker_gap_and_length(self):
        words = [{"text": "こん", "start": 0.0, "end": 0.3, "type": "word", "speaker_id": "s0"}, {"text": " ", "start": 0.3, "end": 0.3, "type": "spacing", "speaker_id": "s0"},
                 {"text": "にちは", "start": 0.3, "end": 0.8, "type": "word", "speaker_id": "s0"},
                 {"text": "(笑)", "start": 0.9, "end": 1.0, "type": "audio_event"},
                 {"text": "はい", "start": 2.0, "end": 2.4, "type": "word", "speaker_id": "s0"},          # 0.6 秒以上の間 → 新しい行
                 {"text": "どうも", "start": 2.5, "end": 2.9, "type": "word", "speaker_id": "s1"},        # 話者が変わる → 新しい行
                 {"text": "ながい", "start": 3.0, "end": 3.2, "type": "word", "speaker_id": "s1"},
                 {"text": "x", "start": 15.5, "end": 15.6, "type": "word", "speaker_id": "s1"}]           # 12 秒を超える → 新しい行
        rows = EC.rows_from_words(words, 10.0)
        self.assertEqual([(r["start"], r["end"], r["text"], r.get("speaker")) for r in rows],
                         [(10.0, 10.8, "こんにちは", "s0"), (12.0, 12.4, "はい", "s0"), (12.5, 13.2, "どうもながい", "s1"), (25.5, 25.6, "x", "s1")])

    def test_words_without_time_follow_previous(self):
        rows = EC.rows_from_words([{"text": "あ", "start": None, "end": None, "type": "word"}, {"text": "い", "start": 1.0, "end": 1.5, "type": "word"}], 0.0)
        self.assertEqual([(r["start"], r["end"], r["text"]) for r in rows], [(1.0, 1.5, "あい")])

    def test_segments_and_text_only(self):
        segs = {"text": "全文", "segments": [{"id": 0, "start": 0.0, "end": 2.0, "speaker": "A", "text": " 前半 "}, {"start": 2.0, "end": 4.0, "text": "", "speaker": "B"}]}
        rows = EC.rows_from("openai", "gpt-4o-transcribe-diarize", segs, 5.0, 4.0)
        self.assertEqual(rows, [{"start": 5.0, "end": 7.0, "text": "前半", "speaker": "A"}])   # 文字の無い区間は捨てる
        # 時刻を返さないモデルは、文書全体を 1 行に(segments があっても使わない)
        rows = EC.rows_from("openai", "gpt-4o-transcribe", {"text": " ぜんぶ ", "segments": [{"start": 0, "end": 1, "text": "x"}]}, 5.0, 4.0)
        self.assertEqual(rows, [{"start": 5.0, "end": 9.0, "text": "ぜんぶ"}])
        self.assertEqual(EC.rows_from("openai", "gpt-4o-transcribe", {"text": ""}, 0.0, 4.0), [])
        self.assertEqual(EC.timing_kind("openai", "whisper-1"), "segments")
        self.assertEqual(EC.timing_kind("elevenlabs", "scribe_v2"), "words")
        self.assertEqual(EC.timing_kind("openai", "gpt-transcribe"), "none")

    def test_request_fields_without_hints(self):
        f = EC.request_fields("openai", "gpt-4o-transcribe-diarize")
        self.assertEqual((f["response_format"], f["chunking_strategy"], f["language"]), ("diarized_json", "auto", "ja"))
        self.assertEqual(EC.request_fields("openai", "whisper-1")["response_format"], "verbose_json")
        self.assertEqual(EC.request_fields("openai", "gpt-4o-transcribe")["response_format"], "json")
        f = EC.request_fields("elevenlabs", "scribe_v2")
        self.assertEqual((f["model_id"], f["diarize"], f["timestamps_granularity"], f["tag_audio_events"]), ("scribe_v2", "true", "word", "false"))
        for svc in ("openai", "elevenlabs"):
            for k in EC.request_fields(svc, "x"):
                self.assertNotIn(k, ("prompt", "keyterms"))   # ヒントは渡さない

    def test_multipart_has_fields_and_file(self):
        ctype, body = EC.multipart({"model": "m", "language": "ja"}, "a.wav", b"RIFFdata")
        self.assertTrue(ctype.startswith("multipart/form-data; boundary="))
        boundary = ctype.split("boundary=")[1].encode()
        self.assertEqual(body.count(b"--" + boundary), 4)   # 3 つの部品 + 終わり
        self.assertIn(b'name="model"\r\n\r\nm\r\n', body)
        self.assertIn(b'name="file"; filename="a.wav"\r\nContent-Type: audio/wav\r\n\r\nRIFFdata\r\n', body)
        self.assertTrue(body.endswith(b"--" + boundary + b"--\r\n"))


class RunTest(unittest.TestCase):
    """run の流れ(通信は偽)"""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="test_eval_cloud_")
        self.data = os.path.join(self.tmp, "data")
        os.makedirs(os.path.join(self.data, "transcripts"))
        self.src = os.path.join(self.tmp, "clip.wav")
        silence_wav(self.src, 8.0)
        self.write("ccccccccccc1", title="一本目", evalSet=True, evalReviewed={"at": 1}, sourcePath=self.src, start=0, end=8, durationSec=8,
                   segments=[seg(1, 0.0, 4.0, "テスト文1"), seg(2, 4.0, 8.0, "テスト文2x", "B")], original=[])
        self.calls = []
        self.env = mock.patch.dict(os.environ, {"TRANSCRIBE_BACKEND": "fake", "TRANSCRIBE_FAKE_DELAY": "0", "OPENAI_API_KEY": KEY, "ELEVENLABS_API_KEY": KEY})
        self.env.start()

    def tearDown(self):
        self.env.stop()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def write(self, i, **doc):
        path = os.path.join(self.data, "transcripts", i + ".json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(dict(id=i, **doc), f, ensure_ascii=False)

    def snapshot(self):
        d = os.path.join(self.data, "transcripts")
        out = {}
        for n in os.listdir(d):
            with open(os.path.join(d, n), "rb") as f:
                out[n] = f.read()
        return out

    def fake_http(self, responses):
        """http_json の偽: (method, url) の記録と、送り先ごとの応答。キーがヘッダー以外に出ていないことも見る"""
        def http(method, url, headers, body=None, content_type=None, timeout=None):
            self.calls.append((method, url, dict(headers), body))
            if method == "DELETE":
                return 200, {}
            self.assertIn(b'name="file"', body)
            self.assertNotIn(KEY.encode(), body)
            return 200, responses
        return http

    @unittest.skipUnless(shutil.which("ffmpeg"), "ffmpeg が無い")
    def test_plan_only_then_send_then_cached(self):
        before = self.snapshot()
        diar = {"task": "transcribe", "duration": 8.0, "text": "テスト文1テスト文2",
                "segments": [{"id": 0, "start": 0.0, "end": 4.0, "speaker": "A", "text": "テスト文1"}, {"id": 1, "start": 4.0, "end": 8.0, "speaker": "B", "text": "テスト文2"}]}
        with mock.patch.object(EC, "http_json", self.fake_http(diar)):
            # 1) --send なし = 見積もりだけ。通信せず・保存せず
            res, out = quiet(EC.main, ["run", "--service", "openai", "--model", "gpt-4o-transcribe-diarize", "--data", self.data])
            self.assertIsNone(res)
            self.assertEqual(self.calls, [])
            self.assertIn("送る", out)
            self.assertIn("見積もり $0.001", out)
            self.assertIn("--send", out)
            self.assertNotIn(KEY, out)
            self.assertFalse(os.path.isdir(os.path.join(self.data, "evals")))
            # 2) --send = 送って控えに残し、採点して eval_asr と同じ形で保存
            res, out = quiet(EC.main, ["run", "--service", "openai", "--model", "gpt-4o-transcribe-diarize", "--data", self.data, "--label", "cloud-test"])
            self.assertIsNone(res)   # まだ --send が無い(見積もりだけ)
            res, out = quiet(EC.main, ["run", "--service", "openai", "--model", "gpt-4o-transcribe-diarize", "--data", self.data, "--label", "cloud-test", "--send"])
            self.assertEqual(len(self.calls), 1)
            m, url, headers, _body = self.calls[0]
            self.assertEqual((m, url, headers["Authorization"]), ("POST", EC.SERVICES["openai"]["url"], "Bearer " + KEY))
            self.assertNotIn(KEY, out)
            o = res["summary"]["overall"]
            self.assertEqual((o["refChars"], o["sub"], o["del"], o["ins"]), (11, 0, 1, 0))   # 「x」が抜けた 1 字だけ
            self.assertEqual(res["meta"]["engine"]["engine"], "cloud:openai")
            self.assertEqual(res["meta"]["engine"]["settings"]["timing"], "segments")
            self.assertEqual(res["meta"]["cloud"]["service"], "openai")
            self.assertEqual(res["meta"]["perDoc"][0]["rows"], 2)
            self.assertEqual(res["meta"]["post"], EC.POST_NONE)
            self.assertEqual(self.snapshot(), before)   # 文書は書き換えない
            saved = os.listdir(os.path.join(self.data, "evals", "asr"))
            self.assertEqual(len(saved), 1)
            self.assertTrue(saved[0].endswith("_cloud-test.json"))
            cache = os.path.join(self.data, "evals", "cloud", "openai", "gpt-4o-transcribe-diarize", "ccccccccccc1.json")
            self.assertTrue(os.path.isfile(cache))
            with open(cache, encoding="utf-8") as f:
                rec = json.load(f)
            self.assertEqual(rec["response"], diar)
            self.assertNotIn(KEY, json.dumps(rec))
            # 3) 控えがあれば --send が無くても送らずに採点する(再送しない)
            self.calls.clear()
            res, out = quiet(EC.main, ["run", "--service", "openai", "--model", "gpt-4o-transcribe-diarize", "--data", self.data, "--no-save"])
            self.assertEqual(self.calls, [])
            self.assertIn("控えあり", out)
            self.assertEqual(res["summary"]["overall"]["refChars"], 11)
            # 4) 文書の範囲が変わったら控えは使わない(送り直し = --send が要る)
            self.write("ccccccccccc1", title="一本目", evalSet=True, evalReviewed={"at": 1}, sourcePath=self.src, start=0, end=7, durationSec=7,
                       segments=[seg(1, 0.0, 4.0, "テスト文1"), seg(2, 4.0, 7.0, "テスト文2x", "B")], original=[])
            res, out = quiet(EC.main, ["run", "--service", "openai", "--model", "gpt-4o-transcribe-diarize", "--data", self.data, "--no-save"])
            self.assertIsNone(res)
            self.assertEqual(self.calls, [])
            self.assertIn("送る", out)
        # 一覧
        rows, out = quiet(EC.main, ["list", "--data", self.data])
        self.assertEqual(rows, [("openai", "gpt-4o-transcribe-diarize", 1)])

    @unittest.skipUnless(shutil.which("ffmpeg"), "ffmpeg が無い")
    def test_elevenlabs_words_and_remote_delete(self):
        resp = {"transcription_id": "tr_abc/1", "language_code": "ja", "text": "テスト文1 テスト文2x",
                "words": [{"text": "テスト文1", "start": 0.5, "end": 3.5, "type": "word", "speaker_id": "speaker_0"},
                          {"text": " ", "start": 3.5, "end": 3.6, "type": "spacing", "speaker_id": "speaker_0"},
                          {"text": "テスト文2x", "start": 4.5, "end": 7.5, "type": "word", "speaker_id": "speaker_1"}]}
        with mock.patch.object(EC, "http_json", self.fake_http(resp)):
            res, out = quiet(EC.main, ["run", "--service", "elevenlabs", "--model", "scribe_v2", "--data", self.data, "--send", "--no-save"])
        self.assertEqual([(c[0], c[1]) for c in self.calls],
                         [("POST", EC.SERVICES["elevenlabs"]["url"]), ("DELETE", "https://api.elevenlabs.io/v1/speech-to-text/transcripts/tr_abc%2F1")])
        self.assertEqual(self.calls[0][2]["xi-api-key"], KEY)
        self.assertNotIn(KEY, out)
        o = res["summary"]["overall"]
        self.assertEqual((o["refChars"], o["sub"], o["del"], o["ins"]), (11, 0, 0, 0))
        self.assertEqual(res["meta"]["perDoc"][0]["rows"], 2)
        self.assertEqual(res["meta"]["perDoc"][0]["remote"], {"id": "tr_abc/1", "status": 200, "ok": True})
        self.assertEqual(res["meta"]["cloud"]["remoteDeleted"], 1)
        # --keep-remote なら消さない
        shutil.rmtree(os.path.join(self.data, "evals", "cloud"))
        self.calls.clear()
        with mock.patch.object(EC, "http_json", self.fake_http(resp)):
            res, out = quiet(EC.main, ["run", "--service", "elevenlabs", "--model", "scribe_v2", "--data", self.data, "--send", "--no-save", "--keep-remote"])
        self.assertEqual([c[0] for c in self.calls], ["POST"])
        self.assertIsNone(res["meta"]["perDoc"][0]["remote"])

    @unittest.skipUnless(shutil.which("ffmpeg"), "ffmpeg が無い")
    def test_text_only_model_scores_whole_doc(self):
        with mock.patch.object(EC, "http_json", self.fake_http({"text": "テスト文1テスト文2x"})):
            res, out = quiet(EC.main, ["run", "--service", "openai", "--model", "gpt-4o-transcribe", "--data", self.data, "--send", "--no-save"])
        o = res["summary"]["overall"]
        self.assertEqual((o["groups"], o["refChars"], o["cer"]), (1, 11, 0.0))
        self.assertEqual(res["summary"]["docText"]["cer"], 0.0)
        self.assertIn("時刻を返さない", out)
        self.assertEqual(res["meta"]["engine"]["settings"]["timing"], "none")

    @unittest.skipUnless(shutil.which("ffmpeg"), "ffmpeg が無い")
    def test_guards_key_and_cost_and_http_error(self):
        with mock.patch.object(EC, "http_json", self.fake_http({"text": "x"})):
            with mock.patch.dict(os.environ, {"OPENAI_API_KEY": ""}):
                res, out = quiet(EC.main, ["run", "--service", "openai", "--model", "gpt-4o-transcribe", "--data", self.data, "--send"])
            self.assertIsInstance(res, SystemExit)
            self.assertIn("OPENAI_API_KEY", str(res))
            self.assertEqual(self.calls, [])
            res, out = quiet(EC.main, ["run", "--service", "openai", "--model", "gpt-4o-transcribe", "--data", self.data, "--send", "--max-usd", "0"])
            self.assertIsInstance(res, SystemExit)
            self.assertIn("上限", str(res))
            self.assertEqual(self.calls, [])
        # 送り先のエラーは本ごとに「とばしました」で続け、採点できる応答が無ければ止まる(キーは出さない)
        def bad(method, url, headers, body=None, content_type=None, timeout=None):
            return 401, {"error": {"message": "Incorrect API key provided"}}
        with mock.patch.object(EC, "http_json", bad), mock.patch.object(EC, "RETRY_WAIT", 0):
            res, out = quiet(EC.main, ["run", "--service", "openai", "--model", "gpt-4o-transcribe", "--data", self.data, "--send"])
        self.assertIsInstance(res, SystemExit)
        self.assertIn("とばしました", out)
        self.assertIn("HTTP 401", out)
        self.assertNotIn(KEY, out)
        self.assertFalse(os.path.isdir(os.path.join(self.data, "evals", "asr")))

    def test_key_from_env_or_file(self):
        svc = dict(EC.SERVICES["elevenlabs"], id="elevenlabs")
        kf = os.path.join(self.tmp, "keys.txt")
        with open(kf, "w", encoding="utf-8") as f:
            f.write("# 鍵\nOPENAI_API_KEY = other\nELEVENLABS_API_KEY=\"file-key\"\n")
        with mock.patch.dict(os.environ, {"ELEVENLABS_API_KEY": " env-key "}):
            self.assertEqual(EC.load_key(svc, kf), ("env-key", "環境変数 ELEVENLABS_API_KEY"))
        with mock.patch.dict(os.environ, {"ELEVENLABS_API_KEY": ""}):
            self.assertEqual(EC.load_key(svc, kf), ("file-key", "鍵のファイル"))
            self.assertEqual(EC.load_key(svc, os.path.join(self.tmp, "none.txt")), ("", ""))
            self.assertEqual(EC.load_key(svc, None), ("", ""))

    def test_retry_once_on_429(self):
        seq = [(429, {"error": "slow down"}), (200, {"text": "ok"})]
        calls = []
        def http(method, url, headers, body=None, content_type=None, timeout=None):
            calls.append(method)
            return seq[len(calls) - 1]
        svc = dict(EC.SERVICES["openai"], id="openai")
        with mock.patch.object(EC, "http_json", http), mock.patch.object(EC, "RETRY_WAIT", 0):
            resp, _wall = EC.send_audio(svc, "gpt-4o-transcribe", KEY, b"RIFF")
        self.assertEqual((resp, calls), ({"text": "ok"}, ["POST", "POST"]))
        with mock.patch.object(EC, "http_json", lambda *a, **k: (400, {"error": "bad"})):
            with self.assertRaises(RuntimeError):
                EC.send_audio(svc, "gpt-4o-transcribe", KEY, b"RIFF")
        self.assertIsNone(EC.delete_remote(svc, KEY, "x"))   # OpenAI には消す口が無い(保持なし)

    def test_prices_lists_every_model(self):
        table, out = quiet(EC.main, ["prices"])
        for sid, svc in EC.SERVICES.items():
            for m in svc["models"]:
                self.assertIn(m, out)
        self.assertIn("保持", out)


if __name__ == "__main__":
    unittest.main()
