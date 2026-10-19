#!/usr/bin/env python3
"""認識ワーカー(src/pipeline/transcribe/worker.py。別プロセス)のテスト。  python -m unittest test_worker -v

RealWorkerTest = 本物の通し: 声の見本(Windows の音声合成)を本物の faster-whisper small(CPU)と sherpa-onnx の話者判別で、
文字起こし → 行ごと・範囲・全体の再認識 → 同じ動画の作り直し(人の行の引き継ぎ)→ 話者判別・声を覚える。部品・モデルが無ければ飛ばす(取りに行かない)。
WorkerTest = 本物では起こせない物だけ(TRANSCRIBE_BACKEND=worker-fake: サーバー側は本物の経路、ワーカーの中だけ偽のモデル eval/fake/fake_worker.install):
声の検出が捨てすぎる・途中で落ちて続きから・取り消し・応答しない・落ちる・部品が無い・サーバーがいなくなる・標準出力への余計な出力。
ffmpeg が必要。
"""
import json
import os
os.environ.setdefault("YTT_DATA_DIR", "inplace")   # テストは作業データを本物の置き場所(AppData など)に書かない(ytt.datadir)
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import types
import unittest
from unittest import mock

TESTS = os.path.dirname(os.path.abspath(__file__))
HERE = os.path.dirname(TESTS)   # ツール(editor/)のフォルダ
os.environ.setdefault("YTT_CORE_DIR", os.path.dirname(HERE))
sys.path.insert(0, HERE)
import serve as S  # noqa: E402
from human.proof import doc_jobs  # noqa: E402
from ytt import testkit, workdata  # noqa: E402
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "pipeline", "transcribe", "tests"))
import voice_fixture as VF  # noqa: E402

HAVE_FFMPEG = bool(shutil.which("ffmpeg") and shutil.which("ffprobe"))
HAVE_FW = HAVE_FFMPEG and VF.faster_whisper_small()


def counting(calls, fail_at=None):
    """RangeRecognizer.main の差し替え: 呼ばれた区間 (a, b) を calls に足して本物を呼ぶ。fail_at 回目は落ちる(途中で落ちたふり)"""
    real = S.RangeRecognizer.main

    def main(rec, a, b, share=(0.0, 1.0)):
        calls.append((a, b))
        if len(calls) == fail_at:
            raise RuntimeError("落ちた")
        return real(rec, a, b, share)
    return main


def wait_for(fn, timeout=20.0, step=0.05):
    return testkit.wait_for(fn, timeout, step)


PLACES = ("TX_DIR", "TMP_DIR", "SETTINGS", "WORKER", "WORKER_LOG", "WORKER_CANCEL_GRACE", "RUN_MARK", "WORKER_SILENCE_TIMEOUT", "VOICES_DIR")


def _texts(doc):
    return [g["text"] for g in doc["segments"]]


@unittest.skipUnless(HAVE_FW, "ffmpeg か faster-whisper の small が無い")
class RealWorkerTest(unittest.TestCase):
    """本物の通し(faster-whisper small・CPU)。見本 = 頭 1 秒の無音・「こんにちは。」・1.5 秒・「今日は配信に…」・2.5 秒・低い声の「それでは…」。
    動画は日本語の名前のフォルダの日本語の名前。作業データは一時フォルダ(判別のモデルだけ編集の作業データから写す)・ネットへ出ない(HF_HUB_OFFLINE)"""
    SPEC = {"model": "small", "language": "ja", "device": "cpu", "autoFill": False, "autoLlm": False}

    @classmethod
    def setUpClass(cls):
        cls.dir = tempfile.mkdtemp(prefix="tx-real-")
        wav = VF.make_voice(os.path.join(cls.dir, "見本", "声.wav"))
        if wav is None:
            shutil.rmtree(cls.dir, ignore_errors=True)
            raise unittest.SkipTest("日本語の音声合成が無い")
        cls.media = VF.to_media(wav, os.path.join(cls.dir, "見本", "声の見本.mp4"))
        cls.media2 = shutil.copyfile(cls.media, os.path.join(cls.dir, "見本", "声の見本_話者.mp4"))   # 話者の試験は別の動画(同じ動画の作り直しは人の行を引き継ぐ)
        cls.dur = S.media_duration(cls.media)
        cls.diar = VF.diar_models() is not None and S.has_sherpa()
        if cls.diar:
            VF.copy_diar(cls.dir)
        cls.saved = tuple(getattr(S, k) for k in PLACES)
        cls.patches = [mock.patch.dict(os.environ, {"HF_HUB_OFFLINE": "1"}), mock.patch.object(workdata, "DATA_DIR", cls.dir)]
        for p in cls.patches:
            p.start()
        os.environ.pop("TRANSCRIBE_BACKEND", None)
        S.TX_DIR, S.TMP_DIR = os.path.join(cls.dir, "transcripts"), os.path.join(cls.dir, ".tmp")
        os.makedirs(S.TX_DIR)
        S.SETTINGS, S.WORKER_LOG, S.RUN_MARK = (os.path.join(cls.dir, n) for n in ("settings.json", "worker.log", ".running.json"))
        S.VOICES_DIR = os.path.join(cls.dir, "voices")
        S.WORKER = S.WorkerClient()

    @classmethod
    def tearDownClass(cls):
        S.WORKER.close()
        for p in reversed(cls.patches):
            p.stop()
        for k, v in zip(PLACES, cls.saved):
            setattr(S, k, v)
        shutil.rmtree(cls.dir, ignore_errors=True)

    def run_job(self, spec, kind=None):
        job = S.add_job(spec, kind) if kind else S.add_job(spec)
        S.work_one(job["id"])
        self.assertEqual(job["state"], "done", job.get("error"))
        return job

    def transcribe(self, media=None, **req):
        return self.run_job(S.validate_job(dict(self.SPEC, sourcePath=media or self.media, **req)))

    def doc(self, tid):
        return testkit.read_json(S.tx_path(tid))

    def retranscribe(self, **req):
        spec = S.validate_retranscribe(dict({"model": "small", "device": "cpu"}, **req))
        return spec, self.run_job(spec, "retranscribe")

    def test_diarize_and_voices(self):
        """話者判別(人数 2・自動・しきい値)・声を覚えてもう一度判別する(層が正: 人の層の名前が残り、仮の名前の付け直しは無い)"""
        if not self.diar:
            self.skipTest("sherpa-onnx か判別のモデルが無い")
        self.assertEqual(S.worker_env()["TRANSCRIBE_DATA_DIR"], self.dir)
        tid = self.transcribe(self.media2)["tid"]
        job = self.run_job(S.validate_diarize({"tid": tid, "numSpeakers": 2}), "diarize")
        d = self.doc(tid)
        self.assertEqual((job["speakers"], len(d["speakers"])), (2, 2))
        self.assertNotEqual(d["segments"][0]["speaker"], d["segments"][-1]["speaker"])   # 低い声の 3 文目は別の話者
        os.makedirs(S.TMP_DIR, exist_ok=True)
        wav = os.path.join(S.TMP_DIR, "tune.wav")
        j = {"cancel": False, "proc": None, "phase": "", "state": "", "device": "", "progress": 0.0}
        S.extract_audio(j, {"sourcePath": self.media, "start": 0.0, "end": None}, wav)
        try:
            self.assertEqual({k for _, _, k in S.diarize_real(j, wav, 0, "voxceleb")}, {0, 1})                   # 人数 自動・設定は既定のまま
            self.assertEqual({k for _, _, k in S.diarize_real(j, wav, 0, "voxceleb", threshold=1.5)}, {0})     # 判別の設定がワーカーまで届く
        finally:
            os.unlink(wav)
        d["speakers"][0]["name"] = "兎田ぺこら"
        for g in d["segments"]:
            g["proofed"] = True   # 覚えるのは校正済みの行だけ
        S.save_transcript(tid, d)
        j2 = self.run_job(S.validate_voice_learn({"tid": tid, "names": ["兎田ぺこら"]}), "voice-learn")
        self.assertEqual(j2.get("learned"), ["兎田ぺこら"])
        j3 = self.run_job(S.validate_diarize({"tid": tid, "numSpeakers": 2}), "diarize")
        self.assertEqual(j3.get("named") or [], [])
        self.assertEqual([(s["id"], s["name"]) for s in self.doc(tid)["speakers"]], [("S1", "兎田ぺこら"), ("S2", "話者2")])
        self.assertEqual(os.listdir(S.TMP_DIR), [])

    def test_transcribe_and_rerun(self):
        """文字起こし(範囲の開始 0.5 秒・単語の時刻で行を分ける)→ 行ごと → 範囲 → 全体(校正済みの行を守る)→ 同じ動画の作り直し(人の行を引き継ぐ)→
        行が 0 の文書の全体 → エンジンを名前で読む・知らない名前は断る → GPU の調べは別プロセス → しばらく使わなければワーカーを終わらせる"""
        job = self.transcribe(start=0.5, wordSplit=True)
        self.assertEqual(job["device"], "cpu")
        tid = job["tid"]
        d = self.doc(tid)
        segs = d["segments"]
        self.assertEqual(len(segs), 3, _texts(d))                                    # 1.5 秒の間で分ける・2.5 秒の間も
        self.assertIn("配信", segs[1]["text"])
        self.assertIn("ゲーム", segs[2]["text"])
        self.assertFalse([t for t in _texts(d) if "。" in t])                         # 句読点を除く(既定)
        self.assertTrue(all(0.5 <= g["start"] < g["end"] <= self.dur + 0.01 for g in segs), segs)   # 範囲の開始を足した元の動画の秒
        self.assertGreater(segs[0]["start"], 0.8)                                     # 頭の 1 秒の無音の後
        self.assertGreater(segs[2]["start"] - segs[1]["end"], 1.5)                    # 2.5 秒の無音に行を延ばさない
        self.assertEqual(len(d["original"]), 3)
        run = d["recognition"]["runs"][0]
        self.assertEqual((run["engine"], run["model"], run["device"], run["language"]), ("faster-whisper", "small", "cpu", "ja"))
        self.assertNotIn("gpu", run)                                                  # 機器の名前が無ければ書かない
        self.assertNotIn("fill", run)                                                 # 後処理を使っていなければ記録も無い
        self.assertEqual(d["params"]["dict"], run["settings"]["dict"])
        ws = S.read_words(tid)                                                        # 単語の時刻は文書とは別の words.json
        self.assertNotIn("_words", segs[0])
        self.assertEqual("".join(w[2] for w in ws).replace("。", "").replace(" ", ""), "".join(_texts(d)))
        self.assertTrue(ws[0][0] >= 0.5 and all(ws[i][0] <= ws[i + 1][0] for i in range(len(ws) - 1)))
        asr = testkit.read_json(S.asr_path(tid))                                      # 生出力(分ける前・置換の前)も元の動画の秒
        self.assertEqual(asr["run"]["engine"], "faster-whisper")
        self.assertTrue(asr["segments"] and asr["segments"][0]["start"] >= 0.5 and asr["segments"][0]["words"])
        for stage in ("transcribe", "post"):
            self.assertTrue(os.path.isfile(os.path.join(S.TX_DIR, "%s.%s.key.json" % (tid, stage))), stage)
        self.assertFalse(os.path.exists(os.path.join(S.TX_DIR, tid + ".llm.json")))
        pid = S.WORKER.proc.pid
        # 行ごと・範囲の再認識(行ごとの音声と範囲の配列は一時ファイルで渡し、残さない)
        ids = [g["id"] for g in segs]
        self.retranscribe(tid=tid, ids=ids[1:2])
        self.assertEqual(os.listdir(S.TMP_DIR), [])
        self.assertIn("配信", self.doc(tid)["segments"][1]["text"])
        self.retranscribe(tid=tid, ids=ids[1:], mode="range")
        self.assertEqual(os.listdir(S.TMP_DIR), [])
        after = self.doc(tid)["segments"]
        self.assertEqual(len(after), 3)
        self.assertTrue(all(abs(a["start"] - b["start"]) < 0.3 for a, b in zip(after[1:], segs[1:])), after)   # 範囲の行も元の動画の秒
        # 全体の再認識: 校正済みの行は差し替えない・「標準」を頼んでも全体は「弱め」・履歴に実行前・短い動画は区間に分けない
        d = self.doc(tid)
        d["segments"][0].update(text="人が直した一行目", proofed=True, speaker="")
        S.save_transcript(tid, dict(d, baseUpdatedAt=d["updatedAt"]))
        before = self.doc(tid)
        spec, whole = self.retranscribe(tid=tid, mode="whole", vadMode="normal")
        self.assertEqual(spec["vadMode"], "weak")
        self.assertEqual(spec["ids"], [g["id"] for g in before["segments"][1:]])
        d = self.doc(tid)
        self.assertEqual((d["segments"][0]["text"], d["segments"][0].get("proofed")), ("人が直した一行目", True))
        self.assertTrue(len(d["segments"]) == 3 and "ゲーム" in d["segments"][2]["text"], _texts(d))
        self.assertEqual((whole["kept"], S.public_job(whole)["kept"]), (0, 0))       # 機械の文字は前と同じ = 3 択にする人の行は無い
        self.assertTrue(S.hist_stamps(tid))
        self.assertFalse(os.path.isdir(os.path.join(S.TX_DIR, ".resume")) and os.listdir(os.path.join(S.TX_DIR, ".resume")))
        self.assertEqual(S.WORKER.proc.pid, pid)                                      # 同じワーカー(モデルを持ったまま)を使い回す
        # 同じ動画を作り直すと、前の文書の人の行を引き継ぐ
        again = self.transcribe(start=0.5, wordSplit=True)
        d2 = self.doc(again["tid"])
        self.assertNotEqual(again["tid"], tid)
        self.assertEqual(d2["segments"][0]["text"], "人が直した一行目")
        self.assertGreaterEqual(d2["recognition"]["runs"][-1]["override"]["matched"], 1)
        self.assertTrue(any("引き継ぎました" in w for w in S.public_job(again)["warnings"]))
        # 行が 0 の文書(全部捨てられた文書)も全体で認識し直せる
        d = self.doc(tid)
        d["segments"] = []
        S.save_transcript(tid, dict(d, baseUpdatedAt=d["updatedAt"]))
        self.retranscribe(tid=tid, mode="whole")
        # エンジンを名前で読む(受け付ける引数はエンジンが答える)・知らない名前はワーカーが断り、ワーカーは落ちない
        j = {"phase": "", "progress": 0.0, "cancel": False}
        m, dev = S.load_model("small", j, "cpu", engine="faster-whisper")
        self.assertEqual((m.engine, dev), ("faster-whisper", "cpu"))
        self.assertIn("vad_filter", m.params)
        with self.assertRaises(S.ApiError) as cm:
            S.WORKER.call("transcribe", {"name": "small", "device": "cpu", "engine": "../evil", "audio": {"wav": self.media}, "kw": {}}, j)
        self.assertEqual(cm.exception.code, "bad_engine")
        self.assertTrue(S.WORKER.alive())
        self.assertEqual(S.WORKER.starts, 1)
        # GPU の有無は別プロセス(worker.py --probe)で調べる(サーバーのプロセスに ctranslate2 を読み込まない)
        p = subprocess.run([sys.executable, S.worker_script(), "--probe"], capture_output=True, timeout=60, env=S.worker_env(),
                           stdin=subprocess.DEVNULL, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertIsInstance(json.loads(p.stdout)["cuda"], bool)
        self.assertNotIn("ctranslate2", sys.modules)
        # しばらく使わなければワーカーを終わらせる
        with mock.patch.object(S, "MODEL_IDLE_SEC", 900):
            self.assertTrue(S.release_idle_models(time.time() + 1000))
        self.assertFalse(S.WORKER.alive())


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
        self.tmp = testkit.tempdir(self, prefix="tx-worker-store-")
        self.saved = (S.TX_DIR, S.TMP_DIR, S.SETTINGS, S.WORKER, S.WORKER_LOG, S.WORKER_CANCEL_GRACE, S.RUN_MARK, S.WORKER_SILENCE_TIMEOUT)
        S.RUN_MARK = os.path.join(self.tmp, ".running.json")   # 起動中の印もリポジトリのフォルダに書かない
        S.TX_DIR, S.TMP_DIR = self.tmp, os.path.join(self.tmp, ".tmp")
        S.SETTINGS = os.path.join(self.tmp, "settings.json")
        S.WORKER_LOG = os.path.join(self.tmp, "worker.log")
        S.WORKER = S.WorkerClient()
        self.env = mock.patch.dict(os.environ, {"TRANSCRIBE_BACKEND": "worker-fake", "TRANSCRIBE_FAKE_DELAY": "0.01"})
        self.env.start()
        os.environ.pop("TRANSCRIBE_WORKER_CRASH", None)

    def tearDown(self):
        S.WORKER.close()
        self.env.stop()
        S.TX_DIR, S.TMP_DIR, S.SETTINGS, S.WORKER, S.WORKER_LOG, S.WORKER_CANCEL_GRACE, S.RUN_MARK, S.WORKER_SILENCE_TIMEOUT = self.saved

    # ---- 手伝い
    def run_job(self, spec, kind=None):
        """ジョブを入れてその場で流す -> ジョブ"""
        job = S.add_job(spec, kind) if kind else S.add_job(spec)
        S.work_one(job["id"])
        return job

    def transcribe(self, **req):
        return self.run_job(S.validate_job(dict({"sourcePath": self.media, "model": "small", "language": "ja"}, **req)))

    def restart_worker(self):
        """ワーカーを閉じて新しい口に(環境変数を変えたあと、次のジョブで起動し直させる)"""
        S.WORKER.close()
        S.WORKER = S.WorkerClient()

    def doc(self, tid):
        return testkit.read_json(S.tx_path(tid))

    def worker_log(self):
        try:
            with open(S.WORKER_LOG, encoding="utf-8", errors="replace") as f:
                return f.read()
        except OSError:
            return ""

    # ---- 声の検出が捨てすぎたときのやり直し(docs/design/whole-retranscribe-design.md の 4-2)
    def test_vad_drops_everything_then_relaxes(self):
        """声の検出「標準」が全部を捨てた(複数人で 0 文字の例)→「弱め」でやり直して文字が出る。記録と知らせが残る(「なし」まで緩める段・捨てすぎていなければやり直さない、は単体)"""
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

    def test_whole_counts_proofed_rows_where_machine_changed(self):
        """機械の文字が前と変わった所の校正済みの行は 3 択の数(kept)に入る(同じ見本・同じモデルの本物では機械の文字が変わらない)"""
        tid = self.transcribe()["tid"]
        self._proof_first(tid)
        _spec, job = self._whole(tid)
        self.assertEqual(job["state"], "done", job.get("error"))
        self.assertEqual(self.doc(tid)["segments"][0]["text"], "人が直した一行目")
        self.assertEqual((job["kept"], S.public_job(job)["kept"]), (1, 1))

    def test_whole_resumes_from_saved_parts(self):
        """S-1: 長い動画の全体の再認識は区間ごとに書いておき、途中で落ちても、同じ設定でもう一度始めれば続きから。結果は通しで認識したときと同じ"""
        tid_a, tid_b = self.transcribe()["tid"], self.transcribe()["tid"]    # 同じ動画の同じ文書を2つ(通しと、途中で落ちて続きから)
        with mock.patch.object(S, "WHOLE_PART_SEC", 6):
            _s, job = self._whole(tid_a)
            self.assertEqual(job["state"], "done", job.get("error"))
            self.assertFalse(os.path.exists(S.resume_path(tid_a)))           # 反映したら続きの記録は消す
            calls = []
            with mock.patch.object(S.RangeRecognizer, "main", counting(calls, fail_at=2)):
                _s, job = self._whole(tid_b)
            self.assertEqual(job["state"], "error")
            cp = testkit.read_json(S.resume_path(tid_b))
            self.assertEqual((len(cp["parts"]), sorted(cp["done"])), (3, ["0"]))   # 20 秒 → 6 秒の目安で 3 区間・1つ目だけ済み
            self.assertEqual(cp["parts"][0], [0.0, 6.0])                      # 行(4 秒ごと)にすき間が無い → 目安の所で区切る
            calls.clear()
            with mock.patch.object(S.RangeRecognizer, "main", counting(calls)):
                _s, job = self._whole(tid_b)
            self.assertEqual(job["state"], "done", job.get("error"))
            self.assertEqual(calls, [tuple(p) for p in cp["parts"][1:]])      # 済んだ区間は認識しない
            self.assertEqual(job["resumed"], [1, 3])
            self.assertTrue(any("前回の途中から続けました" in w for w in S.public_job(job)["warnings"]))
            self.assertFalse(os.path.exists(S.resume_path(tid_b)))
        strip = lambda d: [(g["start"], g["end"], g["text"]) for g in d["segments"]]   # noqa: E731
        self.assertEqual(strip(self.doc(tid_b)), strip(self.doc(tid_a)))

    def test_whole_resume_needs_same_settings(self):
        """設定が違えば続きの記録は使わない(最初から認識して上書き)"""
        tid = self.transcribe()["tid"]
        with mock.patch.object(S, "WHOLE_PART_SEC", 6):
            calls = []
            with mock.patch.object(S.RangeRecognizer, "main", counting(calls, fail_at=2)):
                self._whole(tid)
            self.assertTrue(os.path.exists(S.resume_path(tid)))
            calls.clear()
            with mock.patch.object(S.RangeRecognizer, "main", counting(calls)):
                _s, job = self._whole(tid, model="large-v3")                 # モデルが違う
            self.assertEqual((job["state"], len(calls), job.get("resumed")), ("done", 3, None))

    def test_whole_loose_condition_fills_where_nothing_was_recognized(self):
        """新しい認識で 0 文字だった所は、緩い条件で文字が出ればそれで埋める(印つき)。0 文字のままなら元の行を残す印は範囲の単体"""
        tid = self.transcribe()["tid"]                                        # 4 秒ごとの行(8〜12 秒 = テスト文3)
        os.environ["TRANSCRIBE_FAKE_GAP"] = "8-12"
        os.environ["TRANSCRIBE_FAKE_LOOSE"] = "1"
        _spec, job = self._whole(tid)
        d = self.doc(tid)
        loose = [g for g in d["segments"] if g["text"].startswith("緩い条件")]
        self.assertTrue(loose and all(S.LOOSE_FLAG in g["flag"] for g in loose))
        self.assertFalse([g for g in d["segments"] if g["text"] == "テスト文3"])
        self.assertEqual(job["emptyKept"], 0)
        self.assertGreater(job["loose"], 0)

    def test_whole_rules(self):
        with mock.patch.object(S, "backend_name", lambda: "fake"):            # 下ごしらえの文字起こしはワーカーを起こさない
            tid = self.transcribe()["tid"]
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
        self.assertTrue(S.WORKER.alive())   # 取り消しに応じたワーカーはそのまま使える(偽のモデルの遅さは起動したときのまま = 4 秒の 1 行だけ)
        self.assertEqual(self.transcribe(end=4.0)["state"], "done")

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
        self.assertIn("native-like output", self.worker_log())      # 標準出力への余計な出力は worker.log へ回り、やり取りを壊さない

    def test_worker_killed_between_jobs_and_server_goes_away(self):
        """待機中に落ちていても次の要求で起動し直す。サーバーが落ちた(標準入力が閉じた)ら、ワーカーもすぐ終わる(メモリを持ったまま取り残されない)"""
        self.assertEqual(self.transcribe()["state"], "done")
        S.WORKER.proc.kill()
        S.WORKER.proc.wait(5)
        self.assertEqual(self.transcribe()["state"], "done")
        self.assertEqual(S.WORKER.starts, 2)
        p = S.WORKER.proc
        p.stdin.close()
        self.assertEqual(p.wait(10), 0)

    def test_worker_missing_and_retry(self):
        """部品が無い(内部の名前は errorDetail だけ)。失敗した文字起こしを、同じ指定でもう一度待機列に入れる(画面の [やり直す])。失敗していないものはやり直せない"""
        with mock.patch.object(S, "WORKER_SCRIPT", os.path.join(self.tmp, "nope.py")):
            job = self.transcribe()
        self.assertEqual(job["state"], "error")
        self.assertIn("文字起こしの部品が見つかりません", job["error"])
        self.assertIn("worker.py", job.get("errorDetail", ""))
        self.assertIn("nope.py", job.get("errorDetail", ""))
        self.assertTrue(S.public_job(job)["canRetry"])
        again = S.retry_job(job["id"])
        self.assertNotEqual(again["id"], job["id"])
        self.assertEqual(again["spec"]["sourcePath"], job["spec"]["sourcePath"])
        self.assertIsNot(again["spec"], job["spec"])   # 前の job と指定を共有しない
        with mock.patch.object(S, "backend_name", lambda: "fake"):            # やり直しの中身はワーカーを起こさない疑似の経路で
            S.work_one(again["id"])
        self.assertEqual(again["state"], "done")
        with self.assertRaises(S.ed_state.ApiError):
            S.retry_job(again["id"])
        with self.assertRaises(S.ed_state.ApiError):
            S.retry_job("nope")

    # ---- 終了
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

    # ---- 認識エンジンの口
    def test_whispercpp_through_worker(self):
        """whisper.cpp のエンジンで文字起こし(サーバー → ワーカー → 偽の whisper-cli)。GPU(Vulkan)で動き、記録にエンジンと機器が残る・
        GPU が無ければ黙って CPU にしない(whisper.cpp の本物の GPU の通しは 1 本だけで、ライブの文字起こしの側 = src/flow/tests/test_live_tx.py)"""
        job = self.transcribe(model="large-v3", engine="whisper.cpp")
        self.assertEqual(job["state"], "done", job.get("error"))
        self.assertEqual(job["device"], "vulkan")
        d = self.doc(job["tid"])
        self.assertEqual([g["text"] for g in d["segments"]][:2], ["テスト文1", "テスト文2"])
        run = d["recognition"]["runs"][0]
        self.assertEqual((run["engine"], run["device"]), ("whisper.cpp", "vulkan"))
        self.assertTrue(os.path.isfile(S.words_path(job["tid"])))            # トークンの時刻が単語の時刻になる
        with mock.patch.dict(os.environ, {"FAKE_WCPP_GPU": "none"}):
            self.restart_worker()                                       # 環境変数をワーカーに渡すため起動し直す
            job = self.transcribe(model="large-v3", engine="whisper.cpp")
        self.assertEqual(job["state"], "error")
        self.assertIn("GPU(Vulkan)を使えませんでした", job["error"])         # 黙って CPU にしない
        self.assertEqual(self.transcribe(model="large-v3", engine="whisper.cpp", device="cpu")["state"], "done")


class EngineTest(unittest.TestCase):
    """tx_engines: faster-whisper のエンジンは、引数と結果をそのまま通す・モデルはローカルだけ(local_files_only)"""

    def test_faster_whisper_passes_through(self):
        import types
        from pipeline.transcribe import tx_engines
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
        from pipeline.transcribe import tx_engines
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

    def test_sense_voice_reads_chunks_like_qwen3(self):
        """SenseVoice は Qwen3-ASR と同じ区切り方(_Qwen3Chunked。無音の区切りは読まない)で読み、区切りの中の行はトークンの時刻(sv_rows)で作る。
        時刻が無ければ Qwen3 と同じ割り振り(q3_rows)。認識器は言語ごとに読む前に 1 つ(知らない言語は auto)"""
        try:
            import numpy as np
        except ImportError:
            self.skipTest("numpy が無い")
        from pipeline.transcribe import tx_engines as E
        t = np.arange(16000 * 47) / 16000.0
        x = (0.2 * np.sin(2 * np.pi * 220 * t)).astype(np.float32)
        x[16000 * 20:16000 * 47] = 0.0   # 後ろは無音(読まない区切り)
        toks, stamps = ["<|ja|>", "あい", "う。", "え"], [0.0, 0.5, 0.9, 3.0]

        class Rec:
            def __init__(self, with_time):
                self.with_time, self.calls = with_time, []

            def create_stream(rec):
                st = types.SimpleNamespace(accept_waveform=lambda sr, w: rec.calls.append(len(w)))
                st.result = types.SimpleNamespace(tokens=toks if rec.with_time else [], timestamps=stamps if rec.with_time else [], text="あいう。え")
                return st

            def decode_stream(self, st):
                pass

        rms = E._frame_rms(x)
        loud = [(a, b) for a, b in E.q3_chunks(rms) if max(rms[a:b]) >= E.Q3_SILENT]
        self.assertTrue(loud and len(loud) < len(E.q3_chunks(rms)))
        for with_time in (True, False):
            rec = Rec(with_time)
            e = E.SenseVoice("sense-voice-small", "cpu", {"dir": "x", "rec": {"ja": rec}})
            segs, info = e.transcribe(x, language="ja")
            rows = [(s.start, s.end, s.text) for s in segs]
            self.assertEqual((info.language, info.duration), ("ja", 47.0))
            self.assertEqual(len(rec.calls), len(loud))                                    # 無音の区切りは読まない
            want = []
            for a, b in loud:
                a0, b0 = a * E.Q3_FRAME, b * E.Q3_FRAME
                floor = E.q3_floor(rms[a:b])
                want += E.sv_rows(toks, stamps, a0, b0) if with_time else E.q3_rows("あいう。え", a0, b0, voiced=[v > floor for v in rms[a:b]])
            self.assertEqual(rows, want)
        with mock.patch.object(E.SenseVoice, "_recognizer", lambda self, lang: self.model.setdefault("asked", lang) and Rec(True)):
            e = E.SenseVoice("sense-voice-small", "cpu", {"dir": "x", "rec": {}})
            self.assertEqual(e.transcribe(x[:16000 * 15], language="xx")[1].language, "auto")
            self.assertEqual(e.model["asked"], "auto")


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
        """ワーカーの diarize: threshold・minOn・minOff が無い要求は引数 4 つの呼び方。あれば名前つきで渡す"""
        from pipeline.transcribe import worker as W
        got, sent = [], []

        def fake(job, wav, num, emb, **kw):
            got.append(((wav, num, emb), kw))
            return [(0.0, 1.0, 0)]

        class Out:
            def send(self, obj):
                sent.append(obj)
        with mock.patch.object(S, "_diarize_local", fake):
            W.handle({"rid": 1, "op": "diarize", "wav": "a.wav", "num": 0, "emb": "voxceleb"}, Out(), set())
            W.handle({"rid": 2, "op": "diarize", "wav": "a.wav", "num": 2, "emb": "voxceleb", "threshold": 0.7, "minOn": 0.2, "minOff": 0.5}, Out(), set())
        self.assertEqual(got, [(("a.wav", 0, "voxceleb"), {}), (("a.wav", 2, "voxceleb"), {"threshold": 0.7, "min_on": 0.2, "min_off": 0.5})])
        self.assertEqual([m["ev"] for m in sent], ["result", "result"])


class JobHelperTest(unittest.TestCase):
    """ジョブの決まった手順の小道具(ed_jobs の check_cancel・job_temp_wav・job_title・_chars_in と tx_engines.env_num。注意の足し方は ed_state.add_warning)"""

    def test_cancel_and_title(self):
        S.check_cancel({"cancel": False})
        with self.assertRaises(S.Cancelled):
            S.check_cancel({"cancel": True})
        self.assertEqual(S.job_title("話者判別: ", {"title": ""}), "話者判別: 無題")
        self.assertEqual(S.job_title("x: ", {"title": "あ" * 150}), "x: " + "あ" * 100)

    def test_temp_wav(self):
        with mock.patch.object(S, "TMP_DIR", os.path.join(testkit.tempdir(self, "tx-wav-"), ".tmp")):
            job = {"id": "j1", "state": "running", "phase": ""}
            with S.job_temp_wav(job) as wav:
                self.assertTrue(os.path.isdir(S.TMP_DIR))                     # 一時のフォルダは作ってから渡す
                open(wav, "wb").close()
                raise S.Cancelled()
            self.assertFalse(os.path.exists(wav))                             # 終わったら消す
            self.assertEqual((job["state"], job["phase"]), ("cancelled", "中止しました"))
            with S.job_temp_wav(job, "中止しました(何も置き換えていません)", "例外") as wav:
                raise S.ApiError("no_file", "動画がありません", 400)
            self.assertEqual((job["state"], job["error"], job["errorCode"]), ("error", "動画がありません", "no_file"))
            with S.job_temp_wav(job) as wav:
                raise RuntimeError("boom")
            self.assertEqual((job["state"], job["error"], job["internal"]), ("error", S.INTERNAL_MSG, True))

    def test_numbers(self):
        from pipeline.transcribe import tx_engines
        c = doc_jobs._chars_in
        self.assertEqual([c(v, 4, 80) for v in (16, 16.9, 4, 80, 3, 81, True, float("nan"), float("inf"), 10 ** 400, "16", None)],
                         [16, 16, 4, 80, None, None, None, None, None, None, None, None])
        for env, want in (("", 7), ("12", 12), (" 3 ", 3), ("x", 7), ("-5", 0), ("999", 64)):
            with mock.patch.dict(os.environ, {"X_TEST_NUM": env}):
                self.assertEqual(tx_engines.env_num("X_TEST_NUM", 7, lo=0, hi=64), want, env)
        with mock.patch.dict(os.environ, {"X_TEST_NUM": "nan"}):
            self.assertEqual(tx_engines.env_num("X_TEST_NUM", 0.0, lo=0.0, hi=0.5, cast=float), 0.5)   # END_TRIM と同じ収め方


class CpuFallbackTest(unittest.TestCase):
    """GPU(CUDA)で実行時に失敗したときの決まり(新規の文字起こし・行ごとの再認識・範囲と全体の再認識。ed_jobs.cpu_fallback の 1 か所):
    処理方式が自動なら CPU で読み直してもう一度・GPU 固定なら gpu_failed・CPU で動いていたらそのまま上げる。
    偽のモデルで確かめる(ワーカーは起動しない)。CPU に切り替わったら phase と device を書き換える"""

    class Good:
        params = None

        def transcribe(self, audio, **kw):
            return iter([types.SimpleNamespace(start=0.0, end=1.0, text="CPUの行", words=[])]), types.SimpleNamespace(duration=None, duration_after_vad=None)

    class Bad:
        params = None

        def __init__(self, exc=None):
            self.exc = exc or RuntimeError("CUDA failed")

        def transcribe(self, audio, **kw):
            raise self.exc

    SPEC = {"model": "small", "language": "ja", "beam": 5, "vadMode": "off", "glossary": []}

    def loader(self, first, device, calls):
        def load(name, job, pref="auto", force_cpu=False, engine=None):
            calls.append(force_cpu)
            if job.get("cancel"):   # ワーカーは取り消し済みの要求を送らない(WorkerClient.stream)
                raise S.Cancelled()
            return (self.Good(), "cpu") if force_cpu else (first, device)
        return mock.patch.object(S, "load_model", load)

    def job(self):
        return {"id": "j", "phase": "", "state": "loading", "device": "", "cancel": False, "progress": 0.0, "segments": 0}

    def real(self, first, device, pref, job=None):
        calls, job = [], job or self.job()
        with self.loader(first, device, calls):
            rows = list(S.transcribe_real(job, dict(self.SPEC, device=pref), "a.wav", 1.0))
        return rows, job, calls

    def test_transcribe_real(self):
        rows, job, calls = self.real(self.Bad(), "cuda", "auto")
        self.assertEqual(([r["text"] for r in rows], job["device"], job["phase"], calls), (["CPUの行"], "cpu", "GPU が使えないため CPU で処理します", [False, True]))
        with self.assertRaises(S.ApiError) as cm:
            self.real(self.Bad(), "cuda", "cuda")
        self.assertEqual(cm.exception.code, "gpu_failed")
        self.assertIn("install-gpu.bat", cm.exception.message)   # 新規の文字起こしの文は GPU 用ライブラリの案内つき
        with self.assertRaises(RuntimeError):
            self.real(self.Bad(), "cpu", "auto")                 # CPU で動いていたら、そのまま上げる
        for exc in (S.Cancelled(), S.ApiError("worker_crashed", "落ちた", 500)):   # 取り消し・理由のある失敗は CPU でやり直さない
            calls = []
            with self.loader(self.Bad(exc), "cuda", calls), self.assertRaises(type(exc)):
                list(S.transcribe_real(self.job(), dict(self.SPEC, device="auto"), "a.wav", 1.0))
            self.assertEqual(calls, [False])

    def chunk(self, first, device, pref, row_first=True, job=None):
        calls, job = [], job or self.job()
        with self.loader(first, device, calls):
            cm = S.ChunkModel(job, "small", pref, dict(self.SPEC, device=pref))
            r = cm.recognize([0.0] * 16000, {"start": 0.0, "end": 1.0}, "", (), row_first)
        return r, job, calls

    def test_chunk_model(self):
        r, job, calls = self.chunk(self.Bad(), "cuda", "auto")
        self.assertEqual((r[0], job["device"], job["phase"], calls), ("CPUの行", "cpu", "GPU が使えないため CPU で処理します", [False, True]))
        with self.assertRaises(RuntimeError):
            self.chunk(self.Bad(), "cuda", "auto", row_first=False)   # CPU に切り替えるのは最初の行だけ
        with self.assertRaises(S.ApiError) as cm:
            self.chunk(self.Bad(), "cuda", "cuda")
        self.assertEqual(cm.exception.code, "gpu_failed")
        self.assertNotIn("install-gpu.bat", cm.exception.message)
        with self.assertRaises(RuntimeError):
            self.chunk(self.Bad(), "cpu", "auto")
        # 行ごとの再認識も、取り消し・理由のある失敗は CPU でやり直さずそのまま上げる(GPU 固定で取り消しても gpu_failed にしない = 新規の文字起こしと同じ)
        for exc in (S.Cancelled(), S.ApiError("worker_crashed", "落ちた", 500)):
            for pref in ("auto", "cuda"):
                with self.assertRaises(type(exc)) as cm:
                    self.chunk(self.Bad(exc), "cuda", pref)
                if isinstance(exc, S.ApiError):
                    self.assertEqual(cm.exception.code, "worker_crashed")

    def range_main(self, first, device, pref):
        calls, job = [], self.job()
        rec = S.RangeRecognizer(job, dict(self.SPEC, device=pref, wordSplit=False), "a.wav", 0.0)
        with self.loader(first, device, calls), mock.patch.object(S, "check_engine", lambda spec: None), \
                mock.patch.object(S, "read_wav_f32", lambda wav: [0.0] * 16000 * 3), mock.patch.object(S, "backend_name", lambda: "worker"):
            rec.fake = False
            lines = rec.main(0.0, 2.0)
        return lines, job, calls

    def test_range_recognizer(self):
        lines, job, calls = self.range_main(self.Bad(), "cuda", "auto")
        self.assertEqual(([x["raw"] for x in lines], job["device"], job["phase"], calls), (["CPUの行"], "cpu", "GPU が使えないため CPU で処理します", [False, True]))
        with self.assertRaises(S.ApiError) as cm:
            self.range_main(self.Bad(), "cuda", "cuda")
        self.assertEqual(cm.exception.code, "gpu_failed")
        with self.assertRaises(RuntimeError):
            self.range_main(self.Bad(), "cpu", "auto")
        for exc in (S.Cancelled(), S.ApiError("worker_crashed", "落ちた", 500)):
            with self.assertRaises(type(exc)):
                self.range_main(self.Bad(exc), "cuda", "auto")


if __name__ == "__main__":
    unittest.main()
