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

HERE = os.path.dirname(os.path.abspath(__file__))
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
        self.saved = (S.TX_DIR, S.TMP_DIR, S.SETTINGS, S.EVAL_DIR, S.WORKER, S.WORKER_LOG, S.WORKER_CANCEL_GRACE, S.RUN_MARK)
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
        S.TX_DIR, S.TMP_DIR, S.SETTINGS, S.EVAL_DIR, S.WORKER, S.WORKER_LOG, S.WORKER_CANCEL_GRACE, S.RUN_MARK = self.saved
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
        self.assertIn("tx_worker.py が見つかりません", job["error"])

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


if __name__ == "__main__":
    unittest.main()
