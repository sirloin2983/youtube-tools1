#!/usr/bin/env python3
"""認識ワーカー(tx_worker.py。別プロセス。統合計画の段階3-3)のテスト。  python -m unittest test_worker -v

faster-whisper を入れていない環境でも動くよう、TRANSCRIBE_BACKEND=worker-fake で動かす:
サーバー側(serve.py)は本物の経路(ワーカーとのやり取り・RemoteModel)を通り、ワーカーの中だけ偽のモデル(tx_worker.install_fakes)を使う。
確かめること: 文字起こし・再認識(行ごと / 範囲)・設定の比較・話者判別がワーカー経由で動く / 取り消し /
ワーカーが落ちてもサーバーは止まらず、そのジョブだけ失敗し、次のジョブで起動し直す / 取り消しに応じなければ強制終了 /
しばらく使わなければワーカーを終わらせる / サーバーがいなくなればワーカーも終わる / 標準出力への余計な出力がやり取りを壊さない。
ffmpeg が必要。
"""
import json
import os
os.environ.setdefault("YTT_DATA_DIR", "inplace")   # テストは作業データを本物の置き場所(AppData など)に書かない(ytt_core.datadir)
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest import mock

TESTS = os.path.dirname(os.path.abspath(__file__))
HERE = os.path.dirname(TESTS)   # ツール(editor/)のフォルダ
os.environ.setdefault("YTT_CORE_DIR", os.path.dirname(HERE))
sys.path.insert(0, HERE)
import serve as S  # noqa: E402

HAVE_FFMPEG = bool(shutil.which("ffmpeg") and shutil.which("ffprobe"))


def wait_for(fn, timeout=20.0, step=0.05):
    end = time.time() + timeout
    while time.time() < end:
        if fn():
            return True
        time.sleep(step)
    return False


@unittest.skipUnless(HAVE_FFMPEG, "ffmpeg が無い")
class WorkerTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dir = tempfile.mkdtemp(prefix="tx-worker-")
        cls.media = os.path.join(cls.dir, "voice.mp4")
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "sine=frequency=440:duration=20", "-c:a", "aac", cls.media],
                       check=True, timeout=60)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.dir, ignore_errors=True)

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="tx-worker-store-")
        self.saved = (S.TX_DIR, S.TMP_DIR, S.SETTINGS, S.EVAL_DIR, S.WORKER, S.WORKER_LOG, S.WORKER_CANCEL_GRACE, S.RUN_MARK, S.WORKER_SILENCE_TIMEOUT)
        S.RUN_MARK = os.path.join(self.tmp, ".running.json")   # 起動中の印もリポジトリのフォルダに書かない
        S.TX_DIR, S.TMP_DIR = self.tmp, os.path.join(self.tmp, ".tmp")
        S.SETTINGS, S.EVAL_DIR = os.path.join(self.tmp, "settings.json"), os.path.join(self.tmp, "evals")
        S.WORKER_LOG = os.path.join(self.tmp, "worker.log")
        S.WORKER = S.WorkerClient()
        self.env = mock.patch.dict(os.environ, {"TRANSCRIBE_BACKEND": "worker-fake", "TRANSCRIBE_FAKE_DELAY": "0.01"})
        self.env.start()
        os.environ.pop("TRANSCRIBE_WORKER_CRASH", None)

    def tearDown(self):
        S.WORKER.close()
        self.env.stop()
        S.TX_DIR, S.TMP_DIR, S.SETTINGS, S.EVAL_DIR, S.WORKER, S.WORKER_LOG, S.WORKER_CANCEL_GRACE, S.RUN_MARK, S.WORKER_SILENCE_TIMEOUT = self.saved
        shutil.rmtree(self.tmp, ignore_errors=True)

    # ---- 手伝い
    def transcribe(self, **req):
        spec = S.validate_job(dict({"sourcePath": self.media, "model": "small", "language": "ja"}, **req))
        job = S.add_job(spec)
        S.work_one(job["id"])
        return job

    def doc(self, tid):
        with open(S.tx_path(tid), encoding="utf-8") as f:
            return json.load(f)

    def worker_log(self):
        try:
            with open(S.WORKER_LOG, encoding="utf-8", errors="replace") as f:
                return f.read()
        except OSError:
            return ""

    # ---- 通常の流れ
    def test_transcribe_through_worker(self):
        job = self.transcribe()
        self.assertEqual(job["state"], "done", job.get("error"))
        self.assertEqual(job["device"], "cpu")
        d = self.doc(job["tid"])
        self.assertEqual(len(d["segments"]), 5)   # 20秒 ÷ 4秒(偽のモデル)
        self.assertEqual([g["text"] for g in d["segments"]][:2], ["テスト文1", "テスト文2"])
        self.assertEqual(d["segments"][4]["flag"], "自信が低い")   # 行の情報(avg_logprob)がワーカーから届いている
        self.assertEqual(len(d["original"]), 5)
        # 計画 段0-1: 機械の出力に自信の度合いを残す(どの値のときに誤りが多いかを測るため)・認識の出どころを残す
        self.assertEqual({k: d["original"][4][k] for k in S.CONF_KEYS}, {"avg_logprob": -1.4, "no_speech_prob": 0.1, "compression_ratio": 1.2})
        self.assertEqual(d["original"][0]["avg_logprob"], -0.3)
        run = d["recognition"]["runs"][0]
        self.assertEqual((run["engine"], run["model"], run["device"], run["language"]), ("faster-whisper", d["model"], "cpu", "ja"))
        self.assertGreater(run["audioSec"], 19)
        self.assertGreaterEqual(run["wallSec"], 0)
        self.assertTrue(S.WORKER.alive())                # 次のジョブのためにモデルを持ったまま残る
        pid = S.WORKER.proc.pid
        self.assertEqual(self.transcribe()["state"], "done")
        self.assertEqual(S.WORKER.proc.pid, pid)          # 同じワーカーを使い回す
        self.assertIn("偽のモデルを読み込み", self.worker_log())   # 標準出力への出力は worker.log へ回り、やり取りを壊さない
        self.assertIn("native-like output", self.worker_log())

    def test_auto_redo_after_transcription(self):
        """設定「疑わしい所を自動で認識し直す」(12 ③-2): 文字起こしのあと、長い区間に文字が少ない行があれば認識し直すジョブを足し、良くなった行だけ置き換える"""
        def sparse_fake(job, spec, wav, total):   # 0〜6 秒に「黒」だけ(抜けの形)・6〜10 秒はふつうの行
            yield {"start": 0.0, "end": 6.0, "text": "黒", "avg_logprob": -0.8, "no_speech_prob": 0.1, "compression_ratio": 1.2}
            yield {"start": 6.0, "end": 10.0, "text": "ふつうに話している行です", "avg_logprob": -0.2, "no_speech_prob": 0.1, "compression_ratio": 1.2}
        with mock.patch.object(S, "backend_name", lambda: "fake"), mock.patch.object(S, "transcribe_fake", sparse_fake):
            job = self.transcribe(autoRedo=True)
            self.assertEqual(job["state"], "done", job.get("error"))
            redo = [j for j in S._jobs.values() if j.get("kind") == "redo" and j.get("tid") == job["tid"]]
            self.assertEqual(len(redo), 1)                                         # 自動で足された
            self.assertEqual(redo[0]["spec"]["oldLp"], {"s1": -0.8})               # 元の行の avg_logprob(良くなったかを比べる)
            S.work_one(redo[0]["id"])
            self.assertEqual((redo[0]["state"], redo[0]["segments"]), ("done", 1), redo[0].get("error"))
            d = self.doc(job["tid"])
            self.assertTrue(d["segments"][0]["text"].startswith("認識し直した文"))
            self.assertEqual(d["segments"][-1]["text"], "ふつうに話している行です")
            job2 = self.transcribe()                                               # 設定がオフなら足さない
            self.assertFalse([j for j in S._jobs.values() if j.get("kind") == "redo" and j.get("tid") == job2["tid"]])

    # ---- 声の検出が捨てすぎたときのやり直し(docs/design/whole-retranscribe-design.md の 4-2)
    def test_vad_drops_everything_then_relaxes(self):
        """声の検出「標準」が全部を捨てた(複数人で 0 文字の例)→「弱め」でやり直して文字が出る。記録と知らせが残る"""
        os.environ["TRANSCRIBE_FAKE_VAD"] = "drop-normal"
        job = self.transcribe(vadMode="normal")
        self.assertEqual(job["state"], "done", job.get("error"))
        d = self.doc(job["tid"])
        self.assertEqual(len(d["segments"]), 5)
        run = d["recognition"]["runs"][0]
        self.assertEqual((run["settings"]["vadMode"], run["vadUsed"]), ("normal", "weak"))
        self.assertEqual([(r["mode"], r["why"], r["kept"]) for r in run["vadRetries"]], [("normal", "kept", 0.0)])
        self.assertEqual(d["params"]["vadUsed"], "weak")
        pj = S.public_job(job)
        self.assertIn("声の検出: 標準→弱め", pj["vadNote"])
        self.assertIn(pj["vadNote"], pj["warnings"])                        # 処理状況にも出る
        # 声の検出をかけると全部捨てる → 「なし」まで緩める
        os.environ["TRANSCRIBE_FAKE_VAD"] = "drop-vad"
        S.WORKER.close()
        S.WORKER = S.WorkerClient()
        job = self.transcribe(vadMode="normal")
        run = self.doc(job["tid"])["recognition"]["runs"][0]
        self.assertEqual((run["vadUsed"], [r["mode"] for r in run["vadRetries"]]), ("off", ["normal", "weak"]))
        # 捨てすぎていなければ、やり直さない
        os.environ["TRANSCRIBE_FAKE_VAD"] = ""
        S.WORKER.close()
        S.WORKER = S.WorkerClient()
        job = self.transcribe(vadMode="normal")
        run = self.doc(job["tid"])["recognition"]["runs"][0]
        self.assertEqual((run["vadUsed"], run["vadRetries"], run["vadRemovedSec"]), ("normal", [], 0.0))
        self.assertEqual(S.public_job(job)["vadNote"], "")

    # ---- 動画全体の再認識(docs/design/whole-retranscribe-design.md の 3)。認識は疑似(3 秒ごとに「範囲再認識N」)
    def _whole(self, tid, **req):
        spec = S.validate_retranscribe(dict({"tid": tid, "mode": "whole", "model": "small"}, **req))
        job = S.add_job(spec, "retranscribe")
        with mock.patch.object(S, "backend_name", lambda: "fake"):
            S.work_one(job["id"])
        return spec, job

    def _proof_first(self, tid, text="人が直した一行目"):
        d = self.doc(tid)
        d["segments"][0].update(text=text, proofed=True, speaker="")
        S.save_transcript(tid, dict(d, baseUpdatedAt=d["updatedAt"]))
        return self.doc(tid)

    def test_whole_keeps_proofed_rows(self):
        tid = self.transcribe()["tid"]
        before = self._proof_first(tid)
        s1, orig1 = before["segments"][0], before["original"][0]
        spec, job = self._whole(tid)
        self.assertEqual(spec["vadMode"], "weak")                            # 全体は既定「弱め」
        self.assertEqual(spec["ids"], [g["id"] for g in before["segments"][1:]])   # 校正済みでない行だけ差し替える
        self.assertEqual(job["state"], "done", job.get("error"))
        d = self.doc(tid)
        self.assertEqual(d["segments"][0], s1)                               # 校正済みの行は文字・時刻・印そのまま
        self.assertIn(orig1, d["original"])                                  # その機械の出力も古いまま
        new = d["segments"][1:]
        self.assertTrue(new and all(g["text"].startswith("範囲再認識") for g in new))
        self.assertTrue(all(g["start"] >= s1["end"] for g in new))           # 校正済みの行にかかる新しい行は切り詰めた
        self.assertEqual((d["retranscribed"]["whole"], d["retranscribed"]["kept"], d["retranscribed"]["emptyKept"]), (True, 1, 0))
        self.assertEqual((job["kept"], S.public_job(job)["kept"]), (1, 1))
        self.assertTrue(os.path.isfile(os.path.join(S.TX_DIR, ".bak", tid + ".pre-retranscribe.json")))

    def test_whole_resumes_from_saved_parts(self):
        """S-1: 長い動画の全体の再認識は区間ごとに書いておき、途中で落ちても、同じ設定でもう一度始めれば続きから。結果は通しで認識したときと同じ"""
        tid_a, tid_b = self.transcribe()["tid"], self.transcribe()["tid"]    # 同じ動画の同じ文書を2つ(通しと、途中で落ちて続きから)
        with mock.patch.object(S, "WHOLE_PART_SEC", 6):
            _s, job = self._whole(tid_a)
            self.assertEqual(job["state"], "done", job.get("error"))
            self.assertFalse(os.path.exists(S.resume_path(tid_a)))           # 反映したら続きの記録は消す
            calls, real = [], S.RangeRecognizer.main

            def main_fails_second(rec, a, b, share=(0.0, 1.0)):
                calls.append((a, b))
                if len(calls) == 2:
                    raise RuntimeError("落ちた")
                return real(rec, a, b, share)
            with mock.patch.object(S.RangeRecognizer, "main", main_fails_second):
                _s, job = self._whole(tid_b)
            self.assertEqual(job["state"], "error")
            with open(S.resume_path(tid_b), encoding="utf-8") as f:
                cp = json.load(f)
            self.assertEqual((len(cp["parts"]), sorted(cp["done"])), (3, ["0"]))   # 20 秒 → 6 秒の目安で 3 区間・1つ目だけ済み
            self.assertEqual(cp["parts"][0], [0.0, 6.0])                      # 行(4 秒ごと)にすき間が無い → 目安の所で区切る
            calls.clear()
            with mock.patch.object(S.RangeRecognizer, "main", lambda rec, a, b, share=(0.0, 1.0): calls.append((a, b)) or real(rec, a, b, share)):
                _s, job = self._whole(tid_b)
            self.assertEqual(job["state"], "done", job.get("error"))
            self.assertEqual(calls, [tuple(p) for p in cp["parts"][1:]])      # 済んだ区間は認識しない
            self.assertEqual(job["resumed"], [1, 3])
            self.assertTrue(any("前回の途中から続けました" in w for w in S.public_job(job)["warnings"]))
            self.assertFalse(os.path.exists(S.resume_path(tid_b)))
        strip = lambda d: [(g["start"], g["end"], g["text"]) for g in d["segments"]]   # noqa: E731
        self.assertEqual(strip(self.doc(tid_b)), strip(self.doc(tid_a)))

    def test_whole_resume_needs_same_settings(self):
        """設定が違えば続きの記録は使わない(最初から認識して上書き)。短い動画は区間に分けず、記録も書かない"""
        tid = self.transcribe()["tid"]
        with mock.patch.object(S, "WHOLE_PART_SEC", 6):
            calls, real = [], S.RangeRecognizer.main

            def main_fails_second(rec, a, b, share=(0.0, 1.0)):
                calls.append((a, b))
                if len(calls) == 2:
                    raise RuntimeError("落ちた")
                return real(rec, a, b, share)
            with mock.patch.object(S.RangeRecognizer, "main", main_fails_second):
                self._whole(tid)
            self.assertTrue(os.path.exists(S.resume_path(tid)))
            calls.clear()
            with mock.patch.object(S.RangeRecognizer, "main", lambda rec, a, b, share=(0.0, 1.0): calls.append((a, b)) or real(rec, a, b, share)):
                _s, job = self._whole(tid, model="large-v3")                 # モデルが違う
            self.assertEqual((job["state"], len(calls), job.get("resumed")), ("done", 3, None))
        calls.clear()
        with mock.patch.object(S.RangeRecognizer, "main", lambda rec, a, b, share=(0.0, 1.0): calls.append((a, b)) or real(rec, a, b, share)):
            _s, job = self._whole(tid)                                        # 既定の目安(600 秒)では 20 秒は1回で
        self.assertEqual((job["state"], len(calls)), ("done", 1))
        self.assertFalse(os.path.isdir(os.path.join(S.TX_DIR, ".resume")) and os.listdir(os.path.join(S.TX_DIR, ".resume")))

    def test_whole_keeps_rows_where_nothing_was_recognized(self):
        """新しい認識で 0 文字だった所(声が重なる所の代わり)は元の行を残して印を付ける。緩い条件で文字が出れば、それで埋める"""
        tid = self.transcribe()["tid"]                                        # 4 秒ごとの行(8〜12 秒 = テスト文3)
        os.environ["TRANSCRIBE_FAKE_GAP"] = "8-12"
        _spec, job = self._whole(tid)
        self.assertEqual(job["state"], "done", job.get("error"))
        d = self.doc(tid)
        kept = [g for g in d["segments"] if g["text"] == "テスト文3"]
        self.assertEqual(len(kept), 1)
        self.assertIn(S.EMPTY_FLAG, kept[0]["flag"])
        self.assertEqual((job["emptyKept"], job["loose"]), (1, 0))
        self.assertTrue(any(o["text"] == "テスト文3" for o in d["original"]))  # 残した行の機械の出力も残す
        # 緩い条件なら文字が出る場合: その所は新しい行(印つき)になる
        tid2 = self.transcribe()["tid"]
        os.environ["TRANSCRIBE_FAKE_LOOSE"] = "1"
        _spec, job = self._whole(tid2)
        d = self.doc(tid2)
        loose = [g for g in d["segments"] if g["text"].startswith("緩い条件")]
        self.assertTrue(loose and all(S.LOOSE_FLAG in g["flag"] for g in loose))
        self.assertFalse([g for g in d["segments"] if g["text"] == "テスト文3"])
        self.assertEqual(job["emptyKept"], 0)
        self.assertGreater(job["loose"], 0)

    def test_range_keeps_rows_where_nothing_was_recognized(self):
        """「範囲をまとめて」も、0 文字だった所の元の行は消さない(以前は消えていた)"""
        tid = self.transcribe()["tid"]
        ids = [g["id"] for g in self.doc(tid)["segments"][1:4]]               # 4〜16 秒
        os.environ["TRANSCRIBE_FAKE_GAP"] = "8-12"
        spec = S.validate_retranscribe({"tid": tid, "mode": "range", "ids": ids, "model": "small"})
        job = S.add_job(spec, "retranscribe")
        with mock.patch.object(S, "backend_name", lambda: "fake"):
            S.work_one(job["id"])
        self.assertEqual(job["state"], "done", job.get("error"))
        texts = [g["text"] for g in self.doc(tid)["segments"]]
        self.assertIn("テスト文3", texts)
        self.assertNotIn("テスト文2", texts)
        self.assertEqual(job["emptyKept"], 1)

    def test_whole_rules(self):
        tid = self.transcribe()["tid"]
        d = self.doc(tid)
        d["segments"] = []
        S.save_transcript(tid, dict(d, baseUpdatedAt=d["updatedAt"]))       # 行が 0 の文書(全部捨てられた文書)も全体で認識し直せる
        _spec, job = self._whole(tid)
        self.assertEqual(job["state"], "done", job.get("error"))
        self.assertTrue(self.doc(tid)["segments"])
        self.assertEqual(S.validate_retranscribe({"tid": tid, "mode": "whole", "vadMode": "off"})["vadMode"], "off")   # 明示の「なし」は尊重
        self.assertEqual(S.validate_retranscribe({"tid": tid, "mode": "whole", "vadMode": "normal"})["vadMode"], "weak")
        d = self.doc(tid)
        S.atomic_write(S.tx_path(tid), json.dumps(dict(d, end=7 * 3600), ensure_ascii=False).encode("utf-8"))
        with self.assertRaises(S.ApiError) as c:
            S.validate_retranscribe({"tid": tid, "mode": "whole"})
        self.assertEqual(c.exception.code, "too_long")                        # 上限は新規の文字起こしと同じ 6 時間
        S.atomic_write(S.tx_path(tid), json.dumps(dict(d, evalSet=True), ensure_ascii=False).encode("utf-8"))
        with self.assertRaises(S.ApiError) as c:
            S.validate_retranscribe({"tid": tid, "mode": "whole"})
        self.assertEqual(c.exception.code, "eval_set")                        # 評価用は断る

    def test_word_split_uses_worker_words(self):
        job = self.transcribe(wordSplit=True)
        self.assertEqual(job["state"], "done", job.get("error"))
        segs = self.doc(job["tid"])["segments"]
        self.assertEqual(len(segs), 5)   # 単語の時刻(words)も届く。1秒以上の間がないので分けない
        ws = S.read_words(job["tid"])    # 単語の時刻は文書とは別の words.json に(12 ②。行のデータには入れない)
        self.assertEqual(len(ws), 10)
        self.assertEqual(ws[0], [0.0, 2.0, "テス"])
        self.assertEqual(ws[2][:2], [4.0, 6.0])
        self.assertNotIn("words", segs[0])
        self.assertNotIn("_words", segs[0])
        self.assertEqual(segs[0]["text"], "テスト文1")   # 単語をつなげた文と行の文が一致(単語が正しく届いている)

    def test_retranscribe_each_and_range_and_abtest(self):
        tid = self.transcribe()["tid"]
        spec = S.validate_retranscribe({"tid": tid, "ids": ["s2", "s3"], "model": "small"})
        job = S.add_job(spec, "retranscribe")
        S.work_one(job["id"])
        self.assertEqual(job["state"], "done", job.get("error"))   # 行ごとの音声(float32 の配列)は一時ファイルで渡す
        self.assertEqual(os.listdir(S.TMP_DIR), [])                # 一時ファイル(音声・範囲の配列)は残らない
        spec = S.validate_retranscribe({"tid": tid, "ids": ["s2", "s3"], "model": "small", "mode": "range"})
        job = S.add_job(spec, "retranscribe")
        S.work_one(job["id"])
        self.assertEqual(job["state"], "done", job.get("error"))
        d = self.doc(tid)
        for g in d["segments"]:
            g["proofed"] = True
        S.save_transcript(tid, d)
        spec = S.validate_abtest({"tid": tid, "variants": [{"model": "small"}, {"model": "medium", "glossary": False}]})
        job = S.add_job(spec, "abtest")
        S.work_one(job["id"])
        self.assertEqual(job["state"], "done", job.get("error"))
        self.assertEqual(os.listdir(S.TMP_DIR), [])

    def test_diarize_through_worker(self):
        tid = self.transcribe()["tid"]
        job = S.add_job(S.validate_diarize({"tid": tid, "numSpeakers": 2}), "diarize")
        S.work_one(job["id"])
        self.assertEqual(job["state"], "done", job.get("error"))
        self.assertEqual(job["speakers"], 2)
        self.assertEqual(len(self.doc(tid)["speakers"]), 2)

    def test_diarize_tune_through_worker(self):
        """判別の設定(dev/eval_speakers.py の run 用。任意)がワーカーまで届く。偽の判別はしきい値 1.0 以上・人数 自動で 1 人にまとめる"""
        os.makedirs(S.TMP_DIR, exist_ok=True)
        wav = os.path.join(S.TMP_DIR, "tune.wav")
        job = {"cancel": False, "proc": None, "phase": "", "state": "", "device": "", "progress": 0.0}
        S.extract_audio(job, {"sourcePath": self.media, "start": 0.0, "end": None}, wav)
        try:
            self.assertEqual({k for _, _, k in S.diarize_real(job, wav, 0, "voxceleb")}, {0, 1})               # 渡さない = 以前と同じ
            self.assertEqual({k for _, _, k in S.diarize_real(job, wav, 0, "voxceleb", threshold=1.5)}, {0})
            self.assertEqual({k for _, _, k in S.diarize_real(job, wav, 2, "voxceleb", threshold=1.5, min_on=0.2, min_off=0.4)}, {0, 1})
        finally:
            os.unlink(wav)

    def test_voice_learn_and_recognize_through_worker(self):
        """A-3: 名前を付けた話者の声を覚え(ワーカーで声の特徴)、もう一度判別すると、覚えた声の話者に名前が付く"""
        saved = S.VOICES_DIR
        S.VOICES_DIR = os.path.join(self.tmp, "voices")
        try:
            tid = self.transcribe()["tid"]
            j = S.add_job(S.validate_diarize({"tid": tid, "numSpeakers": 2}), "diarize")
            S.work_one(j["id"])
            self.assertEqual((j["state"], j.get("named") or []), ("done", []), j.get("error"))   # まだ何も覚えていない
            d = self.doc(tid)
            d["speakers"][0]["name"] = "兎田ぺこら"
            for g in d["segments"]:
                g["proofed"] = True   # 段1(監査17): 覚えるのは校正済みの行だけ
            S.save_transcript(tid, d)
            j2 = S.add_job(S.validate_voice_learn({"tid": tid, "names": ["兎田ぺこら"]}), "voice-learn")
            S.work_one(j2["id"])
            self.assertEqual((j2["state"], j2.get("learned")), ("done", ["兎田ぺこら"]), j2.get("error"))
            j3 = S.add_job(S.validate_diarize({"tid": tid, "numSpeakers": 2}), "diarize")   # 判別し直すと名前は「話者n」に戻る → 声で付け直す
            S.work_one(j3["id"])
            self.assertEqual(j3["state"], "done", j3.get("error"))
            self.assertEqual([n["name"] for n in j3.get("named") or []], ["兎田ぺこら"])
            self.assertEqual([s["name"] for s in self.doc(tid)["speakers"]], ["兎田ぺこら", "話者2"])
            self.assertEqual(os.listdir(S.TMP_DIR), [])
        finally:
            S.VOICES_DIR = saved

    # ---- 取り消し
    def test_cancel_running_job(self):
        os.environ["TRANSCRIBE_FAKE_DELAY"] = "0.5"
        spec = S.validate_job({"sourcePath": self.media, "model": "small"})
        job = S.add_job(spec)
        th = threading.Thread(target=S.work_one, args=(job["id"],))
        th.start()
        self.assertTrue(wait_for(lambda: job["state"] == "running" and isinstance(job.get("proc"), S._CancelHandle), 20))
        S.cancel_job(job["id"])
        th.join(20)
        self.assertEqual(job["state"], "cancelled", job.get("error"))
        self.assertTrue(S.WORKER.alive())   # 取り消しに応じたワーカーはそのまま使える
        os.environ["TRANSCRIBE_FAKE_DELAY"] = "0.01"
        self.assertEqual(self.transcribe()["state"], "done")

    def test_cancelled_before_request_is_not_sent(self):
        """取り消し済みのジョブは、ワーカーに要求を送らない(モデルの読み込みなど重い処理を始めない)"""
        job = {"cancel": True, "phase": "", "state": "", "progress": 0.0, "device": "", "proc": None}
        with self.assertRaises(S.Cancelled):
            S.load_model("small", job)
        self.assertEqual(S.WORKER.starts, 0)   # ワーカーも起動しない
        self.assertIsNone(job["proc"])

    def test_unresponsive_worker_is_killed_on_cancel(self):
        os.environ["TRANSCRIBE_FAKE_DELAY"] = "60"   # 1行ごとに60秒止まる(取り消しを確かめる機会が来ない)
        S.WORKER_CANCEL_GRACE = 0.5
        spec = S.validate_job({"sourcePath": self.media, "model": "small"})
        job = S.add_job(spec)
        th = threading.Thread(target=S.work_one, args=(job["id"],))
        th.start()
        self.assertTrue(wait_for(lambda: job["segments"] >= 1, 20))
        pid = S.WORKER.proc.pid
        t0 = time.time()
        S.cancel_job(job["id"])
        th.join(20)
        self.assertLess(time.time() - t0, 10)
        self.assertEqual(job["state"], "cancelled", job.get("error"))
        self.assertFalse(S.WORKER.alive())
        os.environ["TRANSCRIBE_FAKE_DELAY"] = "0.01"
        self.assertEqual(self.transcribe()["state"], "done")   # 次のジョブで起動し直す
        self.assertNotEqual(S.WORKER.proc.pid, pid)

    def test_silent_worker_is_killed_after_timeout(self):
        """黙ったワーカー(何も届かない)は WORKER_SILENCE_TIMEOUT で強制終了してそのジョブを失敗にする(SLOTS を持ったまま他のツールを塞がない)。次の要求で起動し直す"""
        os.environ["TRANSCRIBE_FAKE_DELAY"] = "60"   # 1行ごとに60秒黙る
        S.WORKER_SILENCE_TIMEOUT = 1.5
        t0 = time.time()
        job = self.transcribe()
        self.assertLess(time.time() - t0, 30)
        self.assertEqual(job["state"], "error", job.get("error"))
        self.assertIn("応答しないため止めました", job["error"])
        self.assertFalse(S.WORKER.alive())
        self.assertIsNone(job.get("proc"))
        self.assertIsNone(S.WORKER._busy_rid)
        os.environ["TRANSCRIBE_FAKE_DELAY"] = "0.01"
        S.WORKER_SILENCE_TIMEOUT = 60
        self.assertEqual(self.transcribe()["state"], "done")   # 次のジョブで起動し直す(新しい列で、前のプロセスの読み残しは混ざらない)
        self.assertEqual(S.WORKER.starts, 2)

    # ---- 異常終了
    def test_worker_crash_fails_only_that_job(self):
        os.environ["TRANSCRIBE_WORKER_CRASH"] = "2"   # 2行目を送ったあとにワーカーが落ちる
        job = self.transcribe()
        self.assertEqual(job["state"], "error")
        self.assertIn("途中で止まりました", job["error"])
        self.assertIn("終了コード 70", job["error"])
        self.assertFalse(S.WORKER.alive())
        self.assertIsNone(job.get("proc"))
        del os.environ["TRANSCRIBE_WORKER_CRASH"]
        job2 = self.transcribe()
        self.assertEqual(job2["state"], "done", job2.get("error"))   # 次のジョブでワーカーを起動し直す
        self.assertEqual(S.WORKER.starts, 2)

    def test_worker_killed_between_jobs(self):
        self.assertEqual(self.transcribe()["state"], "done")
        S.WORKER.proc.kill()
        S.WORKER.proc.wait(5)
        self.assertEqual(self.transcribe()["state"], "done")   # 待機中に落ちていても、次の要求で起動し直す
        self.assertEqual(S.WORKER.starts, 2)

    def test_worker_missing(self):
        with mock.patch.object(S, "WORKER_SCRIPT", os.path.join(self.tmp, "nope.py")):
            job = self.transcribe()
        self.assertEqual(job["state"], "error")
        self.assertIn("文字起こしの部品が見つかりません", job["error"])   # 内部の名前は errorDetail だけ(UI の見直し S12)
        self.assertIn("tx_worker.py", job.get("errorDetail", ""))

    # ---- 終了・メモリ
    def test_idle_release_stops_worker(self):
        self.assertEqual(self.transcribe()["state"], "done")
        now = time.time()
        with mock.patch.object(S, "MODEL_IDLE_SEC", 900):
            self.assertFalse(S.release_idle_models(now))              # まだ使って間もない
            self.assertTrue(S.release_idle_models(now + 1000))
        self.assertFalse(S.WORKER.alive())
        with mock.patch.object(S, "MODEL_IDLE_SEC", 0):
            self.assertFalse(S.release_idle_models(now + 10 ** 6))    # 0 は手放さない

    def test_worker_exits_when_server_goes_away(self):
        """サーバーが落ちた(標準入力が閉じた)ら、ワーカーもすぐ終わる(メモリを持ったまま取り残されない)。"""
        self.assertEqual(self.transcribe()["state"], "done")
        p = S.WORKER.proc
        p.stdin.close()
        self.assertEqual(p.wait(10), 0)

    def test_close_refuses_new_work(self):
        S.WORKER.close()
        job = self.transcribe()
        self.assertEqual(job["state"], "error")
        self.assertIn("終了処理中", job["error"])

    def test_server_process_loads_no_native_libs(self):
        """文字起こし・再認識・話者判別をしても、サーバーのプロセスには numpy・faster-whisper・ctranslate2・sherpa-onnx が入らない
        (入口に取り込んだとき、ネイティブコードの異常終了がスタジオ・cut2resolve に波及しないことの前提)。別の Python で確かめる。"""
        code = r'''
import os, sys, json
sys.path.insert(0, sys.argv[1])
import serve as S
S.TX_DIR = sys.argv[2]; S.TMP_DIR = os.path.join(sys.argv[2], ".tmp"); S.SETTINGS = os.path.join(sys.argv[2], "s.json")
S.WORKER_LOG = os.path.join(sys.argv[2], "worker.log"); S.RUN_MARK = os.path.join(sys.argv[2], ".running.json")
j = S.add_job(S.validate_job({"sourcePath": sys.argv[3], "model": "small"})); S.work_one(j["id"])
r = S.add_job(S.validate_retranscribe({"tid": j["tid"], "ids": ["s1"], "model": "small"}), "retranscribe"); S.work_one(r["id"])
d = S.add_job(S.validate_diarize({"tid": j["tid"]}), "diarize"); S.work_one(d["id"])
S.gpu_ready(); S.has_faster_whisper(); S.has_sherpa()
S.WORKER.close()
print(json.dumps({"states": [j["state"], r["state"], d["state"]],
                  "loaded": [m for m in ("numpy", "faster_whisper", "ctranslate2", "sherpa_onnx", "onnxruntime") if m in sys.modules]}))
'''
        env = dict(os.environ, TRANSCRIBE_BACKEND="worker-fake")
        p = subprocess.run([sys.executable, "-c", code, HERE, self.tmp, self.media], capture_output=True, text=True, timeout=120, env=env)
        self.assertEqual(p.returncode, 0, p.stderr[-2000:])
        out = json.loads(p.stdout.strip().splitlines()[-1])
        self.assertEqual(out["states"], ["done", "done", "done"], p.stderr[-2000:])
        self.assertEqual(out["loaded"], [])

    def test_gpu_probe_runs_in_separate_process(self):
        """GPU の有無は別プロセス(tx_worker.py --probe)で調べる(サーバーのプロセスに ctranslate2 を読み込まない)。"""
        env = dict(os.environ, TRANSCRIBE_BACKEND="worker-fake")
        p = subprocess.run([sys.executable, S.WORKER_SCRIPT, "--probe"], capture_output=True, timeout=60, env=env)
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(json.loads(p.stdout), {"cuda": False})
        self.assertNotIn("ctranslate2", sys.modules)

    # ---- 認識エンジンの口(精度改善の計画 段2-1・2-2)
    def test_whispercpp_through_worker(self):
        """whisper.cpp のエンジンで文字起こし(サーバー → ワーカー → 偽の whisper-cli)。GPU(Vulkan)で動き、記録にエンジンと機器が残る"""
        job = self.transcribe(model="large-v3-turbo", engine="whisper.cpp")
        self.assertEqual(job["state"], "done", job.get("error"))
        self.assertEqual(job["device"], "vulkan")
        d = self.doc(job["tid"])
        self.assertEqual([g["text"] for g in d["segments"]][:2], ["テスト文1", "テスト文2"])
        run = d["recognition"]["runs"][0]
        self.assertEqual((run["engine"], run["engineVersion"], run["device"], run["model"]), ("whisper.cpp", "v1.9.4", "vulkan", "large-v3-turbo"))
        self.assertTrue(os.path.isfile(S.words_path(job["tid"])))            # トークンの時刻が単語の時刻になる
        with mock.patch.dict(os.environ, {"FAKE_WCPP_GPU": "none"}):
            S.WORKER.close()
            S.WORKER = S.WorkerClient()                                       # 環境変数をワーカーに渡すため起動し直す
            job = self.transcribe(model="large-v3-turbo", engine="whisper.cpp")
        self.assertEqual(job["state"], "error")
        self.assertIn("GPU(Vulkan)を使えませんでした", job["error"])         # 黙って CPU にしない
        self.assertEqual(self.transcribe(model="large-v3-turbo", engine="whisper.cpp", device="cpu")["state"], "done")

    def test_engine_by_name_through_worker(self):
        """エンジンを名前で選べる(今は faster-whisper だけ)。知らない名前はワーカーが断り、ワーカーは落ちない"""
        job = {"phase": "", "progress": 0.0, "cancel": False}
        m, dev = S.load_model("small", job, "cpu", engine="faster-whisper")
        self.assertEqual((m.engine, dev), ("faster-whisper", "cpu"))
        self.assertIn("vad_filter", m.params)   # 受け付ける引数はエンジン(の中のモデル)が答える
        with self.assertRaises(S.ApiError) as cm:
            S.load_model("small", job, "cpu", engine="whisper.cpp-nope")
        self.assertEqual(cm.exception.code, "bad_engine")
        with self.assertRaises(S.ApiError) as cm:   # 認識の要求でも、知らないエンジンは断る
            S.WORKER.call("transcribe", {"name": "small", "device": "cpu", "engine": "../evil", "audio": {"wav": self.media}, "kw": {}}, job)
        self.assertEqual(cm.exception.code, "bad_engine")
        self.assertTrue(S.WORKER.alive())
        self.assertEqual(self.transcribe()["state"], "done")


class EngineTest(unittest.TestCase):
    """tx_engines: faster-whisper のエンジンは、引数と結果をそのまま通す(エンジンの口を作る前と出力が1文字も変わらない)"""

    def test_faster_whisper_passes_through(self):
        import types
        import tx_engines
        sentinel, seen = (iter(()), object()), {}

        class FakeModel:
            def __init__(self, name, device=None, compute_type=None, local_files_only=False, cpu_threads=0):
                seen["init"] = (name, device, compute_type, local_files_only)

            def transcribe(self, audio, language=None, beam_size=5, vad_filter=True, hotwords=None):
                seen["call"] = (audio, language, beam_size, vad_filter, hotwords)
                return sentinel

        fw = types.ModuleType("faster_whisper")
        fw.WhisperModel = FakeModel
        with mock.patch.dict(sys.modules, {"faster_whisper": fw}):
            e = tx_engines.get("faster-whisper").create("large-v3", "cpu", "int8")
        self.assertEqual(seen["init"], ("large-v3", "cpu", "int8", True))
        kw = {"language": "ja", "beam_size": 5, "vad_filter": False, "hotwords": "スバル"}
        self.assertIs(e.transcribe("a.wav", **kw), sentinel)
        self.assertEqual(seen["call"], ("a.wav", "ja", 5, False, "スバル"))
        self.assertEqual(e.params(), ["audio", "beam_size", "hotwords", "language", "vad_filter"])
        self.assertEqual(S.recognition_run({"model": "large-v3", "language": "ja", "beam": 5, "vadMode": "weak"}, {}, 1, 1)["engine"],
                         "fake" if S.backend_name() == "fake" else "faster-whisper")

    def test_unknown_engine(self):
        import tx_engines
        for bad in ("nope", "../x", "Engine", "__init__"):
            self.assertFalse(tx_engines.valid(bad))
            with self.assertRaises(ValueError):
                tx_engines.get(bad)
        self.assertTrue(tx_engines.valid(None))   # 無ければ既定(faster-whisper)
        with self.assertRaises(S.ApiError) as cm:
            S._load_model_local("small", {"phase": ""}, "cpu", False, "nope")
        self.assertEqual(cm.exception.code, "bad_engine")

    def test_whole_parts_cut_in_gaps(self):
        """S-1: 区切りは目安の前後 WHOLE_SPLIT_WINDOW 秒の中で、行の無いいちばん長いすき間の真ん中。短ければ分けない"""
        rows = lambda *ab: {"segments": [{"start": a, "end": b} for a, b in ab]}   # noqa: E731
        self.assertEqual(S.whole_parts(rows(), 0.0, 900.0), [[0.0, 900.0]])          # 600 × 1.5 まで1つ
        d = rows((0, 550), (560, 590), (620, 700), (700, 1300), (1310, 2000))
        parts = S.whole_parts(d, 0.0, 2000.0)
        self.assertEqual(parts[0], [0.0, 605.0])                                       # 590〜620 のすき間(10 秒より長い)の真ん中
        self.assertEqual(parts[1][0], 605.0)
        self.assertEqual(parts[1][1], 1205.0)                                          # 目安(1205)の前後 90 秒にすき間が無い(1300〜1310 は外)→ 目安の所
        self.assertEqual(parts[2], [1205.0, 2000.0])                                   # 残り 795 秒は 600 × 1.5 以下 → 最後の区間
        self.assertEqual(len(parts), 3)
        self.assertTrue(all(p[0] < p[1] for p in parts) and all(parts[i][1] == parts[i + 1][0] for i in range(len(parts) - 1)))

    def test_engine_module_has_no_native_imports(self):
        """tx_engines はサーバー側でも読む(名前と版)。ファイルの先頭でネイティブの部品を読み込まない"""
        code = "import sys; sys.path.insert(0, sys.argv[1]); import tx_engines; print([m for m in ('numpy', 'faster_whisper', 'ctranslate2') if m in sys.modules])"
        p = subprocess.run([sys.executable, "-c", code, HERE], capture_output=True, text=True, timeout=60)
        self.assertEqual(p.stdout.strip(), "[]", p.stderr)


class ProtocolTest(unittest.TestCase):
    """ワーカーの出力が壊れていても、サーバー側は読み飛ばす・異常終了として扱う。"""

    def test_error_mapping(self):
        e = S.WorkerClient._error({"code": "gpu_failed", "message": "GPU で…", "status": 500})
        self.assertIsInstance(e, S.ApiError)
        self.assertEqual((e.code, e.status), ("gpu_failed", 500))
        self.assertIsInstance(S.WorkerClient._error({"code": "cancelled"}), S.Cancelled)
        e = S.WorkerClient._error({"code": "exception", "type": "RuntimeError", "message": "CUDA failed"})
        self.assertIsInstance(e, S.WorkerError)
        self.assertIn("RuntimeError: CUDA failed", str(e))

    def test_apply_only_known_keys(self):
        job = {"phase": "", "progress": 0.0, "tid": "x"}
        S.WorkerClient._apply(job, {"k": "tid", "v": "evil"})
        S.WorkerClient._apply(job, {"k": "progress", "v": 5})
        S.WorkerClient._apply(job, {"k": "phase", "v": {"not": "str"}})
        S.WorkerClient._apply(job, {"k": "phase", "v": "x" * 500})
        self.assertEqual(job["tid"], "x")
        self.assertEqual(job["progress"], 0.99)
        self.assertEqual(len(job["phase"]), 200)

    def test_diarize_request_tune_is_optional(self):
        """ワーカーの diarize: threshold・minOn・minOff が無い要求は以前と同じ呼び方(引数 4 つ)。あれば名前つきで渡す"""
        import tx_worker
        got, sent = [], []

        def fake(job, wav, num, emb, **kw):
            got.append(((wav, num, emb), kw))
            return [(0.0, 1.0, 0)]

        class Out:
            def send(self, obj):
                sent.append(obj)
        with mock.patch.object(S, "_diarize_local", fake):
            tx_worker.handle(S, {"rid": 1, "op": "diarize", "wav": "a.wav", "num": 0, "emb": "voxceleb"}, Out(), set())
            tx_worker.handle(S, {"rid": 2, "op": "diarize", "wav": "a.wav", "num": 2, "emb": "voxceleb", "threshold": 0.7, "minOff": 0.5}, Out(), set())
        self.assertEqual(got, [(("a.wav", 0, "voxceleb"), {}), (("a.wav", 2, "voxceleb"), {"threshold": 0.7, "min_off": 0.5})])
        self.assertEqual([m["ev"] for m in sent], ["result", "result"])


if __name__ == "__main__":
    unittest.main()
