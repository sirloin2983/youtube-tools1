# -*- coding: utf-8 -*-
"""pipeline/transcribe/diarize(話者判別の計算・判別の記録・声の特徴。役割で組み直す RS2-9)を、編集の serve を読まずに使うテスト。

    py -3.10 -m unittest src/pipeline/transcribe/tests/test_diarize.py -v

細かい決まり(割り当て・ならし・記録・照らし合わせの条件)は編集のテスト(test_voices・test_smooth・test_ovdraft・test_autodiar。serve の名前で読む)が確かめる。
ここは「① が serve なしで読めて同じ物が動く」こと・置き場所が txenv の口から決まること・本物と疑似の口(backend)・
読み込みでネイティブの部品(numpy・sherpa_onnx)・app(serve・ed_*)・eval を読まないことだけ。
"""
import os
os.environ.setdefault("YTT_DATA_DIR", "inplace")   # 作業データは読み書きしないが、ほかのテストとそろえる
import shutil
import subprocess
import sys
import tempfile
import unittest

SRC = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))   # tests -> transcribe -> pipeline -> src
sys.path.insert(0, SRC)
from pipeline.transcribe import backend, diarize, txenv, worker_client  # noqa: E402


class _TxenvSaved(unittest.TestCase):
    """txenv の登録を試験の前に控え、後で戻す(serve と同じプロセスで流しても登録を壊さない)"""

    def setUp(self):
        self.saved = dict(txenv._providers)

    def tearDown(self):
        txenv._providers.clear()
        txenv._providers.update(self.saved)


class TestPure(unittest.TestCase):
    def test_assign_speakers(self):
        segs = [{"start": 0.0, "end": 2.0}, {"start": 9.0, "end": 12.0}, {"start": 30.0, "end": 30.5}]
        res = diarize.assign_speakers(segs, [(0.0, 10.0, 0), (10.0, 20.0, 1)], 0.0)
        self.assertEqual(res, [(0, False, False), (1, True, False), (None, False, True)])   # 2 人の区間にまたがる行は「声が混ざっている」・区間の外は不確か
        self.assertEqual(diarize.assign_speakers([{"start": 5.0, "end": 6.0}], [(0.0, 10.0, 3)], 100.0), [(None, False, True)])   # offset を足して元の動画の秒

    def test_smooth_labels(self):
        rows = [{"start": 0.0, "end": 2.0, "label": 0, "ratio": 1.0}, {"start": 2.1, "end": 2.6, "label": 1, "ratio": 0.2},
                {"start": 2.7, "end": 4.0, "label": 0, "ratio": 1.0}]
        self.assertEqual(diarize.smooth_labels(rows, []), {1: 0})
        self.assertEqual(diarize.smooth_labels(rows, [(2.1, 2.6)]), {})   # 別の話者の区間が重なる所はならさない

    def test_turn_overlaps_and_label_ratio(self):
        ts = [(0.0, 5.0, 0), (4.0, 6.0, 1)]
        self.assertEqual(diarize._turn_overlaps(ts), [[4.0, 5.0]])
        self.assertAlmostEqual(diarize.label_ratio(3.0, 5.0, 0, ts), 1.0)
        self.assertEqual(diarize.label_ratio(3.0, 5.0, None, ts), 0.0)

    def test_voice_groups_and_match(self):
        segs = [{"start": 0.0, "end": 2.0, "speaker": "S1"}, {"start": 3.0, "end": 3.5, "speaker": "S1"},   # 短い行は使わない
                {"start": 4.0, "end": 6.0, "speaker": "S2", "flag": diarize._txbase.MIXED_FLAG}]   # 声が混ざっている行は使わない
        self.assertEqual(diarize.voice_groups(segs, lambda g: g.get("speaker")), {"S1": ([(0.0, 2.0)], 2.0)})
        voices = {"A": {"vec": diarize._unit([1.0, 0.0])}, "B": {"vec": diarize._unit([0.0, 1.0])}}
        self.assertEqual(diarize.match_voices({"S1": [1.0, 0.0], "S2": [0.0, 1.0]}, voices), {"S1": ("A", 1.0), "S2": ("B", 1.0)})
        got, info = diarize.match_voices_explain({"S1": None}, voices)
        self.assertEqual((got, info["S1"]["reason"]), ({}, "no_feature"))


class TestPlaces(_TxenvSaved):
    def test_models_dir_follows_txenv(self):
        box = {"d": os.path.join("a", "data")}
        txenv.register(DATA_DIR=lambda: box["d"])
        self.assertEqual(diarize.diar_models_dir(), os.path.join("a", "data", "models", "diar"))
        box["d"] = os.path.join("b", "data")   # 作業データの切り替え(set_data_dir)に呼ぶたびについていく
        self.assertEqual(diarize._diar_path(diarize.DIAR_SEG), os.path.join("b", "data", "models", "diar", diarize.DIAR_SEG["file"]))
        saved, diarize.DIAR_DIR = diarize.DIAR_DIR, os.path.join("c", "diar")   # 上書き(dev/eval_speakers)
        try:
            self.assertEqual(diarize.diar_models_dir(), os.path.join("c", "diar"))
        finally:
            diarize.DIAR_DIR = saved

    def test_write_read_and_voices(self):
        tmp = tempfile.mkdtemp(prefix="rs29-diar-")
        try:
            txenv.register(TX_DIR=lambda: tmp)
            tid = "0123456789ab"
            self.assertIsNone(diarize.read_diar(tid))
            self.assertFalse(diarize.update_diar_voices(tid, {"speakers": {}}))   # 記録が無ければ何もしない
            diarize.write_diar(tid, {"at": 1, "labelMap": {"0": "S1"}})
            diarize.write_diar(tid, {"at": 2, "labelMap": {"0": "S1"}})
            d = diarize.read_diar(tid)
            self.assertEqual((d["schema"], d["latest"]["at"], [h["at"] for h in d["history"]]), (diarize.DIAR_SCHEMA, 2, [1]))
            self.assertTrue(diarize.update_diar_voices(tid, {"checked": True, "speakers": {"S1": {"decided": "A"}}}))
            self.assertEqual(diarize.read_diar(tid)["latest"]["voices"]["speakers"]["S1"]["label"], 0)   # labelMap の逆引きでラベルを付ける
            self.assertEqual(diarize.diar_path(tid), os.path.join(tmp, tid + ".diar.json"))
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_has_sherpa_reads_txenv(self):
        txenv.register(worker_fake=lambda: (lambda: True), worker_has=lambda: (lambda *m: False))
        self.assertTrue(diarize.has_sherpa())   # worker-fake は部品があるとみなす
        asked = []
        txenv.register(worker_fake=lambda: (lambda: False), worker_has=lambda: (lambda *m: asked.append(m) or False))
        self.assertFalse(diarize.has_sherpa())
        self.assertEqual(asked, [("sherpa_onnx", "numpy")])


class _Worker:
    def __init__(self, reply):
        self.reply, self.calls = reply, []

    def call(self, op, args, job):
        self.calls.append((op, args))
        return self.reply


class TestBackendAndWorker(unittest.TestCase):
    def setUp(self):
        self.saved = (worker_client.IN_WORKER, worker_client.WORKER)
        worker_client.IN_WORKER = False

    def tearDown(self):
        worker_client.IN_WORKER, worker_client.WORKER = self.saved
        backend.set_selector(lambda: backend.REAL)

    def test_embed_groups_through_backend(self):
        class Rec(backend.Backend):
            name = "rec"

            def embed(self, job, wav, emb, groups, real):
                return [emb, groups]
        backend.set_selector(lambda: Rec())
        self.assertEqual(diarize.embed_groups({}, "w.wav", "voxceleb", [[(10.0, 12.0), (4.0, 6.0)]], 5.0), ["voxceleb", [[[5.0, 7.0], [0.0, 1.0]]]])   # 音声の頭からの秒に

    def test_real_paths_ask_the_worker(self):
        worker_client.WORKER = _Worker([[1, 0.5]])
        self.assertEqual(diarize.embed_groups({}, "w.wav", "voxceleb", [[(0.0, 1.0)]], 0.0), [[1.0, 0.5]])
        self.assertEqual(worker_client.WORKER.calls, [("embed", {"wav": "w.wav", "emb": "voxceleb", "groups": [[[0.0, 1.0]]]})])
        worker_client.WORKER = _Worker([[0, 1.5, 2]])
        self.assertEqual(diarize.diarize_real({}, "a.wav", 0, "voxceleb"), [(0.0, 1.5, 2)])
        self.assertEqual(worker_client.WORKER.calls, [("diarize", {"wav": "a.wav", "num": 0, "emb": "voxceleb"})])   # 設定を渡さなければ以前と同じ形


class TestImportsAlone(unittest.TestCase):
    def test_no_native_app_or_eval(self):
        """diarize は numpy・sherpa_onnx などのネイティブの部品・serve と editor の ed_*(app)・eval を読まずに import できる"""
        code = ("import sys; sys.path.insert(0, %r); from pipeline.transcribe import diarize; "
                "native = ('numpy', 'faster_whisper', 'ctranslate2', 'sherpa_onnx', 'onnxruntime'); "
                "bad = [m for m in sys.modules if m in native or m.startswith('ed_') or m == 'serve' or m == 'eval' or m.startswith('eval.') or m.startswith('human')]; "
                "print(bad); sys.exit(1 if bad else 0)") % SRC
        p = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=60)
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)


if __name__ == "__main__":
    unittest.main()
