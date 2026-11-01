# -*- coding: utf-8 -*-
"""pipeline/transcribe/diarize(話者判別の計算・判別の記録・声の特徴)を、編集の serve を読まずに使うテスト。

    py -3.12 -m unittest tests/pipeline/transcribe/test_diarize.py -v

本物の判別(Nemotron・speech.cpp)と声(sherpa-onnx)で判別 → 声を覚える → 判別し直すまでの通しは tests/human/proof/test_voices.py の TestDiarRealRun。
speech diarize の呼び方(機器 auto → CPU で取り直し・JSON の読み)は偽の speech(fake_speech_diarize.py)で確かめる。ここに残すのは、その通しの声の見本では
決まって起こせない境目(2 人にまたがる行・区間の外・offset・同じ話者どうしの重なり・混ぜる重みの上限と次元の違い)・置き場所・記録の上限・
サーバーからワーカーへの頼み方(通しはワーカーの中で読むので通らない)。
"""
import os
os.environ.setdefault("YTT_DATA_DIR", "inplace")   # 作業データは読み書きしないが、ほかのテストとそろえる
import sys
import unittest
from unittest import mock

SRC = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))), "src")   # tests -> transcribe -> pipeline -> src
sys.path.insert(0, SRC)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))   # tests/(testkit)
import testkit  # noqa: E402
from pipeline.transcribe import backend, diarize, worker_client  # noqa: E402
from ytt import workdata  # noqa: E402


class _Patches(unittest.TestCase):
    """持ち主(ytt/workdata・worker_client)の値を試験の間だけ差し替える"""

    def patch(self, mod, name, value):
        """mod.name を試験の間だけ value に(終わったら元に戻す。serve と同じプロセスで流しても壊さない)"""
        self.enterContext(mock.patch.object(mod, name, value))


class TestPure(unittest.TestCase):
    def test_edges_of_assign_overlaps_groups_and_blend(self):
        segs = [{"start": 0.0, "end": 2.0}, {"start": 9.0, "end": 12.0}, {"start": 30.0, "end": 30.5}]
        res = diarize.assign_speakers(segs, [(0.0, 10.0, 0), (10.0, 20.0, 1)], 0.0)
        self.assertEqual(res, [(0, False, False), (1, True, False), (None, False, True)])   # 2 人の区間にまたがる行は「声が混ざっている」・区間の外は不確か
        self.assertEqual(diarize.assign_speakers([{"start": 5.0, "end": 6.0}], [(0.0, 10.0, 3)], 100.0), [(None, False, True)])   # offset を足して元の動画の秒
        self.assertEqual(diarize._turn_overlaps([(0.0, 10.0, 0), (8.0, 12.0, 1), (11.0, 15.0, 0), (20.0, 25.0, 1)]), [[8.0, 10.0], [11.0, 12.0]])
        self.assertEqual(diarize._turn_overlaps([(0, 5, 0), (3, 8, 0)]), [])   # 同じ話者どうしは重なりに数えない
        segs = [{"start": 0.0, "end": 2.0, "speaker": "S1"}, {"start": 3.0, "end": 3.5, "speaker": "S1"},   # 短い行は使わない
                {"start": 4.0, "end": 6.0, "speaker": "S2", "flag": diarize._txbase.MIXED_FLAG}, {"start": 7.0, "end": 9.0, "speaker": ""}]   # 声が混ざっている行・話者の無い行は使わない
        self.assertEqual(diarize.voice_groups(segs, lambda g: g.get("speaker")), {"S1": ([(0.0, 2.0)], 2.0)})
        v, s = diarize.blend_voice([1.0, 0.0], 10.0, [0.0, 1.0], 10.0)
        self.assertAlmostEqual(v[0], v[1], places=6)                          # 同じ長さ同士は半々
        self.assertAlmostEqual(sum(x * x for x in v), 1.0, places=6)           # 長さ 1
        self.assertEqual(s, 20.0)
        v, s = diarize.blend_voice([1.0, 0.0], 36000.0, [0.0, 1.0], 10.0)
        self.assertAlmostEqual(v[0], diarize._unit([3600.0, 10.0])[0], places=6)   # 前の重みは 3600 秒で頭打ち
        self.assertEqual(s, 3610.0)
        self.assertEqual(diarize.blend_voice(None, 5.0, [0.0, 1.0], 7.0), ([0.0, 1.0], 7.0))   # 前が無い
        self.assertEqual(diarize.blend_voice([1.0, 0.0, 0.0], 5.0, [0.0, 1.0], 7.0), ([0.0, 1.0], 7.0))   # 次元が違う


class TestPlaces(_Patches):
    def test_models_dir_follows_workdata(self):
        self.patch(workdata, "DATA_DIR", os.path.join("a", "data"))
        self.assertEqual(diarize.diar_models_dir(), os.path.join("a", "data", "models", "diar"))
        workdata.DATA_DIR = os.path.join("b", "data")   # 作業データの切り替え(set_data_dir)に呼ぶたびについていく
        self.assertEqual(diarize._diar_path(diarize.DIAR_NEMO), os.path.join("b", "data", "models", "diar", diarize.DIAR_NEMO["file"]))
        saved, diarize.DIAR_DIR = diarize.DIAR_DIR, os.path.join("c", "diar")   # 上書き(src/eval/tools/eval_speakers)
        try:
            self.assertEqual(diarize.diar_models_dir(), os.path.join("c", "diar"))
        finally:
            diarize.DIAR_DIR = saved

    def test_write_read_and_voices(self):
        tmp = testkit.tempdir(self, prefix="rs29-diar-")
        self.patch(workdata, "TX_DIR", tmp)
        tid = "0123456789ab"
        self.assertIsNone(diarize.read_diar(tid))
        self.assertFalse(diarize.update_diar_voices(tid, {"speakers": {}}))   # 記録が無ければ何もしない
        for at in range(1, 8):
            diarize.write_diar(tid, {"at": at, "labelMap": {"0": "S1"}})
        d = diarize.read_diar(tid)
        self.assertEqual((d["schema"], d["latest"]["at"], [h["at"] for h in d["history"]]), (diarize.DIAR_SCHEMA, 7, [6, 5, 4, 3]))   # 最新を含めて DIAR_KEEP 回まで
        self.assertTrue(diarize.update_diar_voices(tid, {"checked": True, "speakers": {"S1": {"decided": "A"}}}))
        self.assertEqual(diarize.read_diar(tid)["latest"]["voices"]["speakers"]["S1"]["label"], 0)   # labelMap の逆引きでラベルを付ける
        self.assertEqual(diarize.diar_path(tid), os.path.join(tmp, tid + ".diar.json"))


class _Worker:
    def __init__(self, reply):
        self.reply, self.calls = reply, []

    def call(self, op, args, job):
        self.calls.append((op, args))
        return self.reply


class TestBackendAndWorker(unittest.TestCase):
    def setUp(self):
        self.enterContext(mock.patch.object(worker_client, "IN_WORKER", False))
        self.enterContext(mock.patch.object(worker_client, "WORKER", worker_client.WORKER))   # テストが入れた代わりのワーカーは終わりに外す
        self.addCleanup(backend.set_selector, backend._selector[0])   # 前の選び方に戻す(REAL に固定すると、同じプロセスのあとのテストの疑似の登録が消える)

    def test_backend_and_worker_paths(self):
        """声の特徴は backend の口を通る(元の動画の秒 → 音声の頭からの秒)。本物の道は、ワーカーの外ならワーカーに頼む(設定を渡さなければ既定の形)"""
        class Rec(backend.Backend):
            name = "rec"

            def embed(self, job, wav, emb, groups, real):
                return [emb, groups]
        backend.set_selector(lambda: Rec())
        self.assertEqual(diarize.embed_groups({}, "w.wav", "voxceleb", [[(10.0, 12.0), (4.0, 6.0)]], 5.0), ["voxceleb", [[[5.0, 7.0], [0.0, 1.0]]]])
        backend.set_selector(lambda: backend.REAL)
        worker_client.WORKER = _Worker([[1, 0.5]])
        self.assertEqual(diarize.embed_groups({}, "w.wav", "voxceleb", [[(0.0, 1.0)]], 0.0), [[1.0, 0.5]])
        self.assertEqual(worker_client.WORKER.calls, [("embed", {"wav": "w.wav", "emb": "voxceleb", "groups": [[[0.0, 1.0]]]})])
        worker_client.WORKER = _Worker([[0, 1.5, 2]])
        self.assertEqual(diarize.diarize_real({}, "a.wav", 0), [(0.0, 1.5, 2)])
        self.assertEqual(worker_client.WORKER.calls, [("diarize", {"wav": "a.wav", "num": 0})])


class TestSpeechDiarize(_Patches):
    """ワーカーの中の判別 = speech diarize を子プロセスで(11-01 に pyannote から Nemotron に入れ替えた)"""

    def setUp(self):
        home = testkit.tempdir(self, prefix="nemodiar-")
        self.patch(diarize.tx_engines, "ENGINE_DIR", home)
        self.patch(workdata, "DATA_DIR", home)
        self.patch(diarize, "DIAR_COMMAND", [sys.executable, os.path.join(os.path.dirname(os.path.abspath(__file__)), "fake_speech_diarize.py")])
        self.home = home

    def test_runs_gpu_then_cpu_and_reads_json(self):
        job = {"cancel": False}
        self.assertEqual(diarize._diarize_local(job, "a.wav", 0), [(0.0, 2.0, 0), (1.5, 3.0, 1)])   # 開始の順
        self.enterContext(mock.patch.dict(os.environ, {"FAKE_DIAR_FAIL": "auto"}))
        self.assertEqual(diarize._diarize_local(job, "a.wav", 2), [(0.0, 2.0, 0), (1.5, 3.0, 1)])   # GPU で落ちたら CPU で 1 回
        self.assertIn("CPU", job["phase"])
        os.environ["FAKE_DIAR_FAIL"] = "cpu"   # patch.dict の中(終わりに戻る)
        os.makedirs(diarize._txbase.speech_bin_dir(self.home), exist_ok=True)
        with open(os.path.join(diarize._txbase.speech_bin_dir(self.home), diarize._txbase.SPEECH_CHOICE), "w", encoding="utf-8") as fp:
            fp.write('{"ok": true, "device": "cpu"}')   # この PC で Haas を CPU に決めた = 判別も CPU だけ
        with self.assertRaises(diarize._errors.ApiError) as c:
            diarize._diarize_local(job, "a.wav", 0)
        self.assertEqual(c.exception.code, "diar_failed")
        self.assertIn("no device", c.exception.message)

    def test_parse_and_ready(self):
        out = '\n{"file": "a.wav", "segments": [{"start": 2, "end": 1, "speaker": 0}, {"start": 0, "end": 1, "speaker": 3}]}\nspeech: done\n'
        self.assertEqual(diarize.parse_diar_json(out), [(0.0, 1.0, 3)])   # 長さの無い区間は捨てる・JSON でない行は読まない
        self.assertTrue(diarize.has_diar())
        self.patch(diarize, "DIAR_COMMAND", None)
        self.patch(worker_client, "worker_fake", lambda: False)
        self.assertFalse(diarize.has_diar())                                # speech.cpp が置いていない
        self.assertEqual(diarize._diar_engine_real("campplus", 0)["name"], "nemotron-3-diarization")

    def test_model_fetch_is_verified(self):
        self.patch(worker_client, "worker_fake", lambda: False)
        seen = []
        self.patch(diarize.tx_engines, "fetch_file", lambda spec, folder, *a: seen.append((spec["sha256"], spec["size"], folder)) or "x")
        diarize.ensure_diar_model({"cancel": False})
        self.assertEqual(seen, [(diarize.DIAR_NEMO["sha256"], 106179488, diarize.diar_models_dir())])
        self.patch(diarize.tx_engines, "fetch_file", mock.Mock(side_effect=diarize.tx_engines.EngineError("fetch_failed", "中身が違う")))
        with self.assertRaises(diarize._errors.ApiError) as c:
            diarize.ensure_diar_model({"cancel": False})
        self.assertEqual(c.exception.code, "model_download")

if __name__ == "__main__":
    unittest.main()
