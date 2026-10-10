#!/usr/bin/env python3
"""whisper.cpp のエンジン(tx_engines.WhisperCpp。精度改善の計画 段2-2)のテスト。test_metrics から読み込まれる。

本物の whisper-cli の代わりに tests/fake_whisper_cli.py を子プロセスで動かす(引数・応答ファイル・結果の JSON・GPU の行・進み具合・取り消し)。
確かめること: faster-whisper の引数 → whisper-cli の引数 / 日本語のヒントが UTF-8 の応答ファイルで渡る / 結果 → 行・単語・自信の度合い /
GPU を頼んだのに Vulkan で動かなければ止める(黙って CPU にしない)/ 取り消し / 取得するファイルの大きさと SHA-256 / サーバーの受付と準備の確認。
"""
import hashlib
import io
import json
import os
os.environ.setdefault("YTT_DATA_DIR", "inplace")   # テストは作業データを本物の置き場所に書かない
import shutil
import sys
import tempfile
import threading
import time
import unittest
import wave
from unittest import mock

TESTS = os.path.dirname(os.path.abspath(__file__))
HERE = os.path.dirname(TESTS)
os.environ.setdefault("YTT_CORE_DIR", os.path.dirname(HERE))
sys.path.insert(0, HERE)
import serve as S  # noqa: E402
from pipeline.transcribe import tx_engines as E  # noqa: E402

FAKE = [sys.executable, os.path.join(TESTS, "fake_whisper_cli.py")]


def make_wav(path, sec=10.0):
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(16000)
        w.writeframes(b"\x00\x00" * int(16000 * sec))


class WhisperCppTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="wcpp-test-")
        self.wav = os.path.join(self.tmp, "a.wav")
        make_wav(self.wav)
        open(os.path.join(self.tmp, "m.bin"), "wb").close()
        self.args_file = os.path.join(self.tmp, "args.json")
        self.env = mock.patch.dict(os.environ, {"FAKE_WCPP_ARGS": self.args_file})
        self.env.start()
        for k in ("FAKE_WCPP_GPU", "FAKE_WCPP_SLEEP", "FAKE_WCPP_FAIL"):
            os.environ.pop(k, None)

    def tearDown(self):
        self.env.stop()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def engine(self, device="vulkan"):
        return E.WhisperCpp("large-v3", device, {"cmd": FAKE, "model": os.path.join(self.tmp, "m.bin")})

    def sent_args(self):
        with open(self.args_file, encoding="utf-8") as f:
            return json.load(f)

    def test_transcribe_maps_args_and_parses(self):
        e = self.engine()
        prog = []
        e.hooks = {"progress": prog.append}
        kw = S.whisper_kwargs({"language": "ja", "beam": 5, "model": "large-v3", "vadMode": "weak", "wordSplit": True,
                               "glossary": ["白上フブキ", "さくらみこ"]})
        kw = S.filter_kwargs(e, kw)
        self.assertNotIn("hotwords", kw)                                   # whisper.cpp に無い引数は渡さない
        with mock.patch.dict(os.environ, {"TRANSCRIBE_WCPP_VAD": "1", "TRANSCRIBE_WCPP_SPEECH_FILTER": "1"}):   # 0.65.0 で消した測るときだけの切り替え = もう効かない
            segs, info = e.transcribe(self.wav, **kw)
        segs = list(segs)
        a = self.sent_args()
        self.assertEqual(a[a.index("-l") + 1], "ja")
        self.assertEqual(a[a.index("-bs") + 1], "5")
        self.assertEqual(a[a.index("-mc") + 1], "0")                       # 前の文を文脈にしない
        self.assertIn("用語: 白上フブキ、さくらみこ", a[a.index("--prompt") + 1])   # 日本語のヒントが化けずに届く(UTF-8 の応答ファイル)
        self.assertTrue(kw.get("vad_filter"))                              # 声の検出「弱め」の指定が来ても
        self.assertFalse({"--vad", "-vm", "-vt", "-vsd", "-vp"} & set(a))   # whisper.cpp 自身の声の検出は使わない(0.65.0 で経路ごと消した)
        self.assertEqual(a[a.index("-nth") + 1], "0.9")
        self.assertNotIn("-ng", a)
        self.assertIn("-nfa", a)                                           # フラッシュアテンションは既定で使わない(時刻が 1 秒単位に丸まる。2026-10-04)
        self.assertEqual(len(segs), 3)                                     # 10 秒 ÷ 4 秒
        s = segs[0]
        self.assertEqual((s.start, s.end, s.text), (0.0, 4.0, "テスト文1"))
        self.assertEqual([w.word for w in s.words], ["テスト", "文1"])      # 特別なトークン [_…] は単語にしない
        self.assertEqual((s.words[1].start, s.words[1].end, s.words[1].probability), (2.0, 4.0, 0.5))
        self.assertAlmostEqual(s.avg_logprob, (__import__("math").log(0.8) + __import__("math").log(0.5)) / 2, places=5)
        self.assertIsNone(s.no_speech_prob)
        self.assertGreater(s.compression_ratio, 0)
        self.assertEqual((info.language, info.duration, info.duration_after_vad), ("ja", 10.0, None))
        self.assertEqual(e.gpu_name, "AMD Radeon RX 7800 XT")
        self.assertTrue(prog and prog[-1] >= 0.99 - 1e-9)
        # seg_to_dict(サーバーの行の整え方)がそのまま読める
        d = S.seg_to_dict(s)
        self.assertEqual((d["text"], d["words"][0][2], d["wordProbs"]), ("テスト文1", "テスト", [0.8, 0.5]))

    def test_temp0_and_cpu_and_samples(self):
        e = self.engine("cpu")
        segs, info = e.transcribe([0.0] * 16000 * 5, language="ja", beam_size=5, temperature=0.0, vad_filter=False)   # サンプル(範囲の音声)は一時の wav に
        self.assertEqual(len(list(segs)), 2)
        a = self.sent_args()
        self.assertIn("-ng", a)
        self.assertEqual(a[a.index("-tp") + 1], "0")
        self.assertIn("-nf", a)
        self.assertNotIn("--vad", a)
        self.assertNotIn("--prompt", a)
        self.assertAlmostEqual(info.duration, 5.0)

    def test_gpu_required_when_asked(self):
        """GPU(Vulkan)を頼んだのに GPU が見つからなければ止める(黙って CPU の結果を GPU として残さない)"""
        os.environ["FAKE_WCPP_GPU"] = "none"
        with self.assertRaises(E.EngineError) as cm:
            self.engine("vulkan").transcribe(self.wav, language="ja")
        self.assertEqual(cm.exception.code, "gpu_failed")
        segs, _ = self.engine("cpu").transcribe(self.wav, language="ja")   # CPU を選んだときは動く
        self.assertEqual(len(list(segs)), 3)

    def test_failure_and_cancel(self):
        os.environ["FAKE_WCPP_FAIL"] = "1"
        with self.assertRaises(E.EngineError) as cm:
            self.engine().transcribe(self.wav, language="ja")
        self.assertEqual(cm.exception.code, "engine_failed")
        self.assertIn("failed to read audio", cm.exception.message)
        del os.environ["FAKE_WCPP_FAIL"]
        os.environ["FAKE_WCPP_SLEEP"] = "30"
        e, flag = self.engine(), threading.Event()
        e.hooks = {"cancelled": flag.is_set}
        threading.Timer(0.5, flag.set).start()
        t0 = time.monotonic()
        with self.assertRaises(E.EngineError) as cm:
            e.transcribe(self.wav, language="ja")
        self.assertEqual(cm.exception.code, "cancelled")
        self.assertLess(time.monotonic() - t0, 10)                         # 子プロセスを止めてすぐ戻る

    def test_device_order_never_falls_back(self):
        self.assertEqual(E.WhisperCpp.device_order("auto", False), ["vulkan"])
        self.assertEqual(E.WhisperCpp.device_order("cuda", True), ["vulkan"])
        self.assertEqual(E.WhisperCpp.device_order("cpu", True), ["cpu"])
        self.assertEqual(E.FasterWhisper.device_order("auto", True), ["cuda", "cpu"])   # faster-whisper は今までどおり

    def test_fetch_file_checks_size_and_hash(self):
        body = b"model-bytes" * 100
        spec = {"file": "x.bin", "url": "https://example.invalid/x.bin", "size": len(body), "sha256": hashlib.sha256(body).hexdigest()}
        folder = os.path.join(self.tmp, "models")

        class Resp(io.BytesIO):
            def __enter__(self):
                return self

            def __exit__(self, *a):
                self.close()
        with mock.patch("urllib.request.urlopen", lambda url, timeout=0: Resp(b"evil" + body[4:])):
            with self.assertRaises(E.EngineError) as cm:
                E.fetch_file(spec, folder)
        self.assertEqual(cm.exception.code, "fetch_failed")
        self.assertEqual(os.listdir(folder), [])                            # 中身が違えば .part も残さない
        with mock.patch("urllib.request.urlopen", lambda url, timeout=0: Resp(body)):
            p = E.fetch_file(spec, folder)
        self.assertEqual(open(p, "rb").read(), body)
        with mock.patch("urllib.request.urlopen", side_effect=AssertionError("通信しない")):
            self.assertEqual(E.fetch_file(spec, folder), p)                  # あって中身が合えば取らない
        with self.assertRaises(E.EngineError):
            E.fetch_file(dict(spec, url="http://example.invalid/x.bin", sha256="0" * 64), folder)   # https 以外からは取らない

    def test_pinned_files_are_https_and_hashed(self):
        for spec in list(E.WCPP_MODELS.values()) + [E.WCPP_VAD]:
            self.assertTrue(spec["url"].startswith("https://huggingface.co/"))
            self.assertRegex(spec["sha256"], r"^[0-9a-f]{64}$")
            self.assertGreater(spec["size"], 0)
        self.assertRegex(E.WHISPER_CPP["commit"], r"^[0-9a-f]{40}$")

    def test_server_accepts_engine_and_checks_ready(self):
        media = os.path.join(self.tmp, "v.wav")
        make_wav(media, 3)
        with mock.patch.object(S, "media_duration", lambda p: 3.0):
            spec = S.validate_job({"sourcePath": media, "model": "large-v3", "engine": "whisper.cpp"})
            self.assertEqual(spec["engine"], "whisper.cpp")
            self.assertEqual(S.validate_job({"sourcePath": media, "model": "small"})["engine"], "faster-whisper")
            for bad, code in (({"engine": "whisper.cpp", "model": "small"}, "bad_model"), ({"engine": "nope", "model": "small"}, "bad_engine")):
                with self.assertRaises(S.ApiError) as cm:
                    S.validate_job(dict({"sourcePath": media}, **bad))
                self.assertEqual(cm.exception.code, code)
        with mock.patch.object(S, "DATA_DIR", self.tmp):
            with self.assertRaises(S.ApiError) as cm:
                S.check_engine(spec)                                        # まだ作っていない → 理由を出して止める
            self.assertEqual(cm.exception.code, "engine_missing")
            self.assertIn("build-whisper-vulkan.bat", cm.exception.message)
            d = E.wcpp_bin_dir(self.tmp)
            os.makedirs(d)
            open(os.path.join(d, E.WCPP_EXE), "wb").close()
            with open(os.path.join(d, "build.json"), "w") as f:
                json.dump({"commit": "0" * 40}, f)
            with self.assertRaises(S.ApiError):                              # 版(コミット)が違う物は使わない
                S.check_engine(spec)
            with open(os.path.join(d, "build.json"), "w") as f:
                json.dump({"commit": E.WHISPER_CPP["commit"]}, f)
            S.check_engine(spec)
            self.assertEqual(S.engines_info()["wcpp"]["ready"], True)        # 画面の「処理方式」に GPU(whisper.cpp)を出す
        self.assertEqual(S.engines_info()["wcpp"]["ready"], False)
        rec = S.recognition_run(dict(spec, beam=5, vadMode="weak"), {"device": "vulkan"}, 1, 1)
        if S.backend_name() != "fake":
            self.assertEqual((rec["engine"], rec["engineVersion"]), ("whisper.cpp", E.WHISPER_CPP["version"]))

    def test_screen_device_vulkan_means_whispercpp(self):
        """画面の処理方式「GPU(AMD など・whisper.cpp)」= device "vulkan" → エンジン whisper.cpp・機器は自動(= Vulkan。黙って CPU にしない)"""
        media = os.path.join(self.tmp, "v.wav")
        make_wav(media, 3)
        with mock.patch.object(S, "media_duration", lambda p: 3.0):
            spec = S.validate_job({"sourcePath": media, "model": "large-v3", "device": "vulkan"})
            self.assertEqual((spec["engine"], spec["device"]), ("whisper.cpp", "auto"))
            with self.assertRaises(S.ApiError) as cm:
                S.validate_job({"sourcePath": media, "model": "small", "device": "vulkan"})
            self.assertEqual(cm.exception.code, "bad_model")
            self.assertIn("large-v3", cm.exception.message)                 # 使えるモデルを案内する
            self.assertEqual(S.validate_job({"sourcePath": media, "model": "small", "device": "cuda"})["engine"], "faster-whisper")


    def test_flash_attn_env(self):
        """TRANSCRIBE_WCPP_FA=1 のときだけフラッシュアテンションを使う(-nfa を付けない)"""
        e = self.engine()
        kw = {"language": "ja", "beam_size": 5}
        self.assertIn("-nfa", e.args(self.wav, os.path.join(self.tmp, "o"), kw))
        with mock.patch.dict(os.environ, {"TRANSCRIBE_WCPP_FA": "1"}):
            self.assertNotIn("-nfa", e.args(self.wav, os.path.join(self.tmp, "o"), kw))


def row(a, b, text, words=None):
    return {"start": a, "end": b, "text": text, "_words": words if words is not None else [(a, b, text)]}


class RowTidyTest(unittest.TestCase):
    """行の後処理(2026-10-04): 音声の長さで切る・同じ文字の行をまとめる(whisper.cpp の行の終わりを声の終わりへ寄せる pull_ends は 0.65.0 で消した)"""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="tidy-test-")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_clip_rows_to_duration(self):
        rows = [row(0.0, 2.0, "はい"), row(39.0, 42.0, "ああ", [(39.0, 40.5, "あ"), (40.5, 42.0, "あ")]), row(41.0, 43.0, "うう")]
        out = list(S.clip_rows(rows, 40.7))
        self.assertEqual([(r["start"], r["end"]) for r in out], [(0.0, 2.0), (39.0, 40.7)])   # 後ろの行は捨て、終わりは長さで切る
        self.assertEqual(out[1]["_words"], [(39.0, 40.5, "あ"), (40.5, 40.7, "あ")])         # 単語は捨てずに時刻を収める

    def test_merge_same_char_rows(self):
        rows = [row(0.0, 1.0, "痛い"), row(1.0, 1.5, "ああ"), row(1.6, 2.0, "あああああ"), row(2.1, 2.5, "ああ!"), row(2.6, 3.0, "ああ"),
                row(3.0, 4.0, "早く!早く!"), row(4.0, 5.0, "早く!早く!"), row(5.0, 6.0, "早く!早く!")]
        out = list(S.merge_repeats(rows))
        self.assertEqual([r["text"] for r in out], ["痛い", "あ" * 9 + "!ああ", "早く!早く!", "早く!早く!", "早く!早く!"])
        m = out[1]
        self.assertEqual((m["start"], m["end"], m["_rep"]), (1.0, 3.0, 4))                # 4 行 → 1 行(始まり = 最初・終わり = 最後)
        self.assertEqual(len(m["_words"]), 4)                                             # 単語はつなぐ
        self.assertNotIn("_rep", out[2])                                                  # 意味のある語の繰り返しの行はまとめない
        self.assertIn("繰り返しの可能性", S.make_flags(m, []))

    def test_merge_needs_three_rows_and_close(self):
        out = list(S.merge_repeats([row(0.0, 1.0, "ああ"), row(1.1, 2.0, "ああ")]))
        self.assertEqual(len(out), 2)                                                     # 2 行はそのまま
        out = list(S.merge_repeats([row(0.0, 1.0, "ああ"), row(1.1, 2.0, "ああ"), row(5.0, 6.0, "ああ")]))
        self.assertEqual(len(out), 3)                                                     # 間が 1 秒より大きければ続きではない
        out = list(S.merge_repeats([row(0.0, 1.0, "ああ"), row(1.1, 2.0, "うう"), row(2.1, 3.0, "ああ")]))
        self.assertEqual(len(out), 3)                                                     # 違う文字

    def test_squash_long_char_run(self):
        out = list(S.merge_repeats([row(0.0, 3.0, "うわ" + "あ" * 40)]))
        self.assertEqual(out[0]["text"], "うわ" + "あ" * S.REP_CHAR_KEEP)
        self.assertEqual(out[0]["_rep"], 1)
        self.assertNotIn("_rep", list(S.merge_repeats([row(0.0, 1.0, "すごーーい")]))[0])

    def test_expand_segments_whole_flow(self):
        seg = {"start": 0.0, "end": 9.0, "text": "前の行次の行あああ", "words": [(0.0, 1.98, "前の行"), (2.0, 4.0, "次の行"), (6.0, 9.0, "あああ")]}
        spec = {"wordSplit": True, "splitChars": 16, "stripPunct": True, "engine": "whisper.cpp"}
        out = list(S.expand_segments([seg], spec, 5.0))
        self.assertEqual([r["text"] for r in out], ["前の行次の行"])                     # 5 秒より後ろの行は捨てる
        self.assertEqual(out[0]["end"], 4.0)
        seg2 = {"start": 0.0, "end": 4.0, "text": "前の行次の行", "words": [(0.0, 1.98, "前の行"), (2.0, 4.0, "次の行")]}
        # 2026-10-05: 音の谷へ寄せる後処理は既定でやめた(前で切れすぎた。0.65.0 で部品ごと消した)。2026-10-07(0.57.1): 終わりを早める END_TRIM も既定でやめ(0)、
        # 続いている行(すき間 JOIN_GAP 0.5 秒以下)の終わりを次の行の始まりへ延ばす(行の時刻の原則 ① 言葉の末を切らない)
        with mock.patch.dict(os.environ, {"TRANSCRIBE_PULL_ENDS": "1"}):   # 0.65.0 で消した切り替え = もう効かない
            out = list(S.expand_segments([seg2], dict(spec, splitChars=3), 5.0))
        self.assertEqual([r["text"] for r in out], ["前の行", "次の行"])
        self.assertEqual(out[0]["end"], 2.0)                                               # 1.98 → 次の行の始まり 2.0 へ
        self.assertEqual(out[0]["_words"], [(0.0, 1.98, "前の行")])                         # 単語は変えない
        self.assertEqual(out[1]["start"], 2.0)                                             # 次の行の始まりは変えない
        self.assertEqual(out[1]["end"], 4.0)                                               # 最後の行(次が無い)は変えない
        with mock.patch.object(S, "JOIN_GAP", 0.0):                                       # つながなければ whisper.cpp の行の終わりもそのまま(寄せない・早めない)
            out = list(S.expand_segments([seg2], dict(spec, splitChars=3), 5.0))
        self.assertEqual(out[0]["end"], 1.98)
        self.assertEqual(out[1]["start"], 2.0)                                             # 次の行の始まりは変えない
        fw = dict(spec, splitChars=3, engine="faster-whisper")
        with mock.patch.object(S, "JOIN_GAP", 0.0):
            out = list(S.expand_segments([seg2], fw, 5.0))
        self.assertEqual(out[0]["end"], 1.98)
        out = list(S.expand_segments([seg2], fw, 5.0))
        self.assertEqual(out[0]["end"], 2.0)                                               # つなぐのは全エンジン
        for name in ("PULL_ENDS_ON", "row_levels", "pull_ends", "WavLevels", "quant_retime", "QUANT_ON"):
            self.assertFalse(hasattr(S, name), name)                               # 0.65.0 で消した部品

    def test_trim_ends(self):
        rows = [row(0.0, 1.0, "a"), row(1.1, 2.0, "b"), row(3.0, 3.25, "c"), row(3.3, 4.0, "d")]
        out = list(S.trim_ends(iter(rows), 0.1))
        self.assertAlmostEqual(out[0]["end"], 0.9, places=3)        # 次とのすき間 0.1 秒 → 0.1 秒早める
        self.assertEqual(out[1]["end"], 2.0)                         # 次まで 1 秒空いている → そのまま
        self.assertEqual(out[2]["end"], 3.25)                        # 短い行(TRIM_MIN より短くなる)は早めない(のばしもしない)
        self.assertEqual(out[3]["end"], 4.0)                         # 最後の行はそのまま
        two = [row(0.0, 1.0, "あ"), row(1.0, 2.0, "い")]
        wc = {"wordSplit": False, "engine": "whisper.cpp"}
        self.assertEqual(S.END_TRIM, 0.0)                             # 2026-10-07(0.57.1)から既定でやめた(原則 ① 言葉の末を切らない)
        out = list(S.expand_segments(two, wc))
        self.assertEqual(out[0]["end"], 1.0)                         # 既定(0)ならしない
        with mock.patch.object(S, "END_TRIM", 0.1), mock.patch.object(S, "JOIN_GAP", 0.0):
            out = list(S.expand_segments(two, wc))
            self.assertAlmostEqual(out[0]["end"], 0.9, places=3)     # TRANSCRIBE_END_TRIM=0.1 と TRANSCRIBE_JOIN_GAP=0 で 0.57.0 の形に戻せる
        with mock.patch.object(S, "END_TRIM", 0.1):
            out = list(S.expand_segments(two, wc))
            self.assertEqual(out[0]["end"], 1.0)                     # つなぐのは早めたあと = JOIN_GAP が 0 でなければ早めた分はつながって戻る


class JoinRowsTest(unittest.TestCase):
    """続いている行の終わりを次の行の始まりへ延ばす(2026-10-07 = 0.57.1。行の時刻の原則 ①。plan/line-b-row-timing.md の 7-2)"""

    def test_join_small_gaps_only(self):
        rows = [row(0.0, 1.0, "a"), row(1.3, 2.0, "b"), row(2.5, 3.0, "c"), row(3.51, 4.0, "d"), row(3.9, 5.0, "e"), row(5.0, 6.0, "f"), row(6.2, 7.0, "g")]
        out = list(S.join_rows(iter(rows), 0.5))
        self.assertEqual([(r["start"], r["end"]) for r in out],
                         [(0.0, 1.3),     # すき間 0.3 → つなぐ
                          (1.3, 2.5),     # ちょうど 0.5 → つなぐ
                          (2.5, 3.0),     # 0.51 → そのまま
                          (3.51, 4.0),    # 重なり(次の始まりが前の終わりより前)は触らない
                          (3.9, 5.0),     # すき間 0 → そのまま
                          (5.0, 6.2),
                          (6.2, 7.0)])    # 最後の行はそのまま
        self.assertEqual(out[0]["_words"], [(0.0, 1.0, "a")])                              # 単語・文字は変えない
        self.assertEqual(out[0]["text"], "a")
        self.assertEqual(rows[0]["end"], 1.0)                                              # 元の行は書き換えない
        self.assertEqual([r["end"] for r in S.join_rows(rows, 0.0)], [r["end"] for r in rows])   # 0 なら何もしない
        self.assertEqual(list(S.join_rows([], 0.5)), [])
        self.assertEqual(S.JOIN_GAP, 0.5)                                                  # 既定(TRANSCRIBE_JOIN_GAP)

    def test_expand_segments_joins_all_engines(self):
        rows = [row(0.0, 1.0, "あ"), row(1.4, 2.0, "い"), row(3.0, 4.0, "う")]
        for eng in ("whisper.cpp", "faster-whisper", "llama.cpp"):
            out = list(S.expand_segments(rows, {"wordSplit": False, "engine": eng}))
            self.assertEqual([r["end"] for r in out], [1.4, 2.0, 4.0], eng)
        with mock.patch.object(S, "JOIN_GAP", 0.0):                                       # TRANSCRIBE_JOIN_GAP=0 でやめる
            out = list(S.expand_segments(rows, {"wordSplit": False, "engine": "faster-whisper"}))
        self.assertEqual([r["end"] for r in out], [1.0, 2.0, 4.0])
        out = list(S.expand_segments(rows, {"wordSplit": False, "engine": "faster-whisper"}, join=False))
        self.assertEqual([r["end"] for r in out], [1.0, 2.0, 4.0])                         # 時刻を使わない呼び出し(2つ目のエンジンの候補)はつながない

    def test_range_lines_join_but_redo_does_not(self):
        raw = [{"start": 0.0, "end": 1.0, "text": "前の行"}, {"start": 1.2, "end": 2.0, "text": "次の行"}]
        spec = {"range": [10.0, 20.0], "language": "ja", "wordSplit": False, "engine": "whisper.cpp", "glossary": []}
        with mock.patch.object(S, "prompt_terms", lambda s: []):
            lines = S.finish_range_lines(raw, spec, 10.0)                                   # 範囲・全体の再認識(RangeRecognizer.main)はつなぐ
            self.assertEqual([(x["start"], x["end"]) for x in lines], [(10.0, 11.2), (11.2, 12.0)])
            lines = S.finish_range_lines(raw, spec, 10.0, join=False)                       # 疑わしい所の認識し直し(range_lines_real)はつながない
            self.assertEqual([(x["start"], x["end"]) for x in lines], [(10.0, 11.0), (11.2, 12.0)])

    def test_post_record(self):
        post = S.post_record()
        self.assertEqual(post["version"], S.SERVER_VERSION)
        self.assertEqual(post, {"version": S.SERVER_VERSION, "endTrim": 0.0, "joinGap": 0.5})   # 0.65.0 から pullEnds・retime は書かない(部品ごと消した)
        spec = {"engine": "whisper.cpp", "model": "large-v3", "beam": 5, "vadMode": "weak", "language": "ja", "glossary": []}
        with mock.patch.object(S, "prompt_terms", lambda s: []), mock.patch.object(S, "dict_version", lambda s: {}):
            run = S.recognition_run(spec, {"device": "vulkan"}, 40.0, 7.0)
        self.assertEqual(run["post"], post)                                                  # recognition.runs[].post(src/eval/tools/eval_timing.py が版ごとに分ける)
        self.assertNotIn("retimed", run)                                                     # 1 秒丸めの配り直しの記録も 0.65.0 から書かない
        doc = {"original": []}
        with mock.patch.object(S, "dict_version", lambda s: {}):
            S.record_rerun(doc, spec, "range", [[1.0, 2.0]], [])
        self.assertEqual(doc["recognition"]["runs"][-1]["post"]["joinGap"], 0.5)


if __name__ == "__main__":
    unittest.main()
