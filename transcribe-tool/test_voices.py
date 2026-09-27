#!/usr/bin/env python3
"""話者の声を覚える(A-3。docs/backlog-ui-2026-09-27.md)のサーバー側のテスト。

    python -m unittest test_metrics test_resolve_export -q   # test_metrics がこのファイルのテストも読み込む
    python -m unittest test_voices -q                        # これだけ

声の特徴そのもの(sherpa-onnx)は使わず、embed_groups を差し替えて、行の選び方・覚え方(混ぜ方)・照らし合わせの決まり
(しきい値・2番目との差・1つの名前は1人)・仮の名前だけを置き換えることを確かめる。
"""
import json
import os
os.environ.setdefault("YTT_DATA_DIR", "inplace")   # テストは作業データを本物の置き場所(AppData など)に書かない(ytt_core.datadir)
import unittest
from unittest import mock

from test_backend import S, TID, StoreDir


def unit(*xs):
    return S._unit(list(xs))


def doc_with_speakers(names, rows):
    """names: [(id, 名前)]、rows: [(開始, 終了, 話者の id, flag)]"""
    return {"schema": "transcribe/v1", "id": TID, "title": "t", "sourcePath": "C:\\x\\clip.mp4", "start": 0, "end": 60.0,
            "speakers": [{"id": i, "name": n, "color": "#888"} for i, n in names], "createdAt": 1, "updatedAt": 1000,
            "segments": [{"id": "s%d" % k, "start": a, "end": b, "text": "x", "speaker": sp, "flag": fl}
                         for k, (a, b, sp, fl) in enumerate(rows, 1)]}


class TestVoiceRules(unittest.TestCase):
    def test_groups_skip_short_and_mixed(self):
        segs = [{"start": 0, "end": 0.5, "speaker": "S1"}, {"start": 1, "end": 4, "speaker": "S1"},
                {"start": 5, "end": 9, "speaker": "S1", "flag": S.MIXED_FLAG}, {"start": 10, "end": 12, "speaker": ""},
                {"start": 13, "end": 20, "speaker": "S2"}]
        g = S.voice_groups(segs, lambda x: x.get("speaker"))
        self.assertEqual(g["S1"], ([(1, 4)], 3))                 # 短い行(相づち)・声が混ざっている行は使わない
        self.assertEqual(g["S2"], ([(13, 20)], 7))
        self.assertNotIn("", g)

    def test_groups_cap_longest_first(self):
        segs = [{"start": i * 10.0, "end": i * 10.0 + 8, "speaker": "S1"} for i in range(60)]
        pick, tot = S.voice_groups(segs, lambda x: "S1")["S1"]
        self.assertLessEqual(len(pick), S.VOICE_MAX_ROWS)
        self.assertLessEqual(tot, S.VOICE_MAX_SEC + 8)

    def test_match_threshold_margin_and_one_to_one(self):
        voices = {"ぺこら": {"vec": unit(1, 0, 0)}, "みこ": {"vec": unit(0, 1, 0)}}
        got = S.match_voices({"S1": unit(0.95, 0.1, 0), "S2": unit(0.1, 0.9, 0.1), "S3": unit(0, 0, 1)}, voices)
        self.assertEqual({k: v[0] for k, v in got.items()}, {"S1": "ぺこら", "S2": "みこ"})   # S3 はどの声とも似ていない
        got = S.match_voices({"S1": unit(1, 1, 0)}, voices)       # 2人のちょうど間: 差が無いので決めない
        self.assertEqual(got, {})
        got = S.match_voices({"S1": unit(1, 0.05, 0), "S2": unit(1, 0.1, 0)}, voices)   # 同じ名前は1人にだけ(似ている方)
        self.assertEqual({k: v[0] for k, v in got.items()}, {"S1": "ぺこら"})

    def test_fake_embeddings_follow_fake_diarization(self):
        a, b, c = S.embed_fake([[[0, 8]], [[21, 29]], [[10, 18]]])
        self.assertGreater(S._cos(a, b), 0.99)                     # 0〜10秒と20〜30秒は同じ偽の話者(偽の判別は既定 2人が 10秒ごとに入れ替わる)
        self.assertLess(S._cos(a, c), S.VOICE_MATCH)


class TestVoiceStore(StoreDir):
    def setUp(self):
        super().setUp()
        self.saved_vdir = S.VOICES_DIR
        S.VOICES_DIR = os.path.join(self.tmp, "voices")

    def tearDown(self):
        S.VOICES_DIR = self.saved_vdir
        super().tearDown()

    def job(self, spec):
        return {"id": "j1", "spec": spec, "cancel": False, "state": "queued", "phase": "", "progress": 0.0, "speakers": 0}

    def test_learn_named_speakers_only_and_mix(self):
        self.put_doc(doc_with_speakers([("S1", "兎田ぺこら"), ("S2", "話者2")], [(0, 5, "S1", ""), (6, 12, "S2", ""), (13, 20, "S1", "")]))
        spec = {"tid": TID, "embedding": "voxceleb", "title": "t"}
        with mock.patch.object(S, "check_source", lambda p: p), mock.patch.object(S, "extract_audio", lambda *a: None), \
                mock.patch.object(S, "has_sherpa", lambda: True), mock.patch.object(S, "ensure_diar_models", lambda *a: None), \
                mock.patch.object(S, "embed_groups", lambda job, wav, emb, groups, off: [unit(1, 0, 0) for _ in groups]):
            j = self.job(spec)
            S.run_voice_learn(j)
        self.assertEqual((j["state"], j["learned"]), ("done", ["兎田ぺこら"]), j.get("error"))   # 仮の名前(話者2)は覚えない
        v = S.load_voices("voxceleb")
        self.assertEqual(list(v), ["兎田ぺこら"])
        self.assertEqual((v["兎田ぺこら"]["rows"], v["兎田ぺこら"]["sec"]), (2, 12.0))
        # もう一度(別の配信)覚えると、使った長さで重みを付けて混ぜる
        with mock.patch.object(S, "check_source", lambda p: p), mock.patch.object(S, "extract_audio", lambda *a: None), \
                mock.patch.object(S, "has_sherpa", lambda: True), mock.patch.object(S, "ensure_diar_models", lambda *a: None), \
                mock.patch.object(S, "embed_groups", lambda job, wav, emb, groups, off: [unit(0, 1, 0) for _ in groups]):
            S.run_voice_learn(self.job(spec))
        v = S.load_voices("voxceleb")["兎田ぺこら"]
        self.assertEqual((v["rows"], v["sec"]), (4, 24.0))
        self.assertAlmostEqual(v["vec"][0], v["vec"][1], places=4)   # 同じ長さなら半分ずつ
        self.assertEqual(S.voices_summary()["voxceleb"][0]["name"], "兎田ぺこら")
        self.assertNotIn("vec", S.voices_summary()["voxceleb"][0])   # 一覧に特徴そのものは出さない
        S.delete_voice("voxceleb", "兎田ぺこら")
        self.assertEqual(S.load_voices("voxceleb"), {})
        with self.assertRaises(S.ApiError):
            S.delete_voice("voxceleb", "兎田ぺこら")

    def test_validate_needs_named_speaker(self):
        self.put_doc(doc_with_speakers([("S1", "話者1")], [(0, 5, "S1", "")]))
        with self.assertRaises(S.ApiError) as cm:
            S.validate_voice_learn({"tid": TID})
        self.assertEqual(cm.exception.code, "no_names")

    def test_recognize_renames_default_names_only(self):
        S.save_voices("voxceleb", {"兎田ぺこら": {"vec": unit(1, 0, 0), "rows": 3, "sec": 30, "updatedAt": 1},
                                   "さくらみこ": {"vec": unit(0, 1, 0), "rows": 3, "sec": 30, "updatedAt": 1}})
        self.put_doc(doc_with_speakers([("S1", "話者1"), ("S2", "みこち"), ("S3", "話者3")],
                                       [(0, 5, "S1", ""), (6, 12, "S2", ""), (13, 20, "S3", "")]))
        vec = {"S1": unit(1, 0.05, 0), "S2": unit(0.05, 1, 0), "S3": unit(0, 0, 1)}
        with mock.patch.object(S, "embed_groups", lambda job, wav, emb, groups, off: [vec[k] for k in ("S1", "S2", "S3")]):
            named = S.recognize_voices(self.job({}), TID, "x.wav", 0.0, "voxceleb")
        self.assertEqual([(n["speaker"], n["name"]) for n in named], [("S1", "兎田ぺこら")])   # S2 は自分で付けた名前なので変えない・S3 は似ていない
        with open(S.tx_path(TID), encoding="utf-8") as f:
            d = json.load(f)
        self.assertEqual([s["name"] for s in d["speakers"]], ["兎田ぺこら", "みこち", "話者3"])


if __name__ == "__main__":
    unittest.main()
