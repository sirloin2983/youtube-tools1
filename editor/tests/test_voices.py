#!/usr/bin/env python3
"""話者の声を覚える(A-3。docs/archive/backlog-ui-2026-09-27.md)のサーバー側のテスト。

    python -m unittest test_metrics test_resolve_export -q   # test_metrics がこのファイルのテストも読み込む
    python -m unittest test_voices -q                        # これだけ

声の特徴そのもの(sherpa-onnx)は使わず、embed_groups を差し替えて、行の選び方・覚え方(混ぜ方)・照らし合わせの決まり
(しきい値・2番目との差・1つの名前は1人)・仮の名前だけを置き換えることを確かめる。
段1(監査02・17・18): 評価用を断る・校正済みで音のメモが無い行だけ・一般的な名前を断る・覚える前の確認(preview)・既にある名前は確かめてから。
"""
import json
import os
os.environ.setdefault("YTT_DATA_DIR", "inplace")   # テストは作業データを本物の置き場所(AppData など)に書かない(ytt_core.datadir)
import unittest
from unittest import mock

from test_backend import S, TID, StoreDir


def unit(*xs):
    return S._unit(list(xs))


def doc_with_speakers(names, rows, proofed=False, eval_set=False):
    """names: [(id, 名前)]、rows: [(開始, 終了, 話者の id, flag[, 校正済み[, tags]])](校正済みを省いた行は proofed の値)"""
    segs = []
    for k, r in enumerate(rows, 1):
        a, b, sp, fl = r[:4]
        g = {"id": "s%d" % k, "start": a, "end": b, "text": "x", "speaker": sp, "flag": fl}
        if (r[4] if len(r) > 4 else proofed):
            g["proofed"] = True
        if len(r) > 5:
            g["tags"] = list(r[5])
        segs.append(g)
    d = {"schema": "transcribe/v1", "id": TID, "title": "t", "sourcePath": "C:\\x\\clip.mp4", "start": 0, "end": 60.0,
         "speakers": [{"id": i, "name": n, "color": "#888"} for i, n in names], "createdAt": 1, "updatedAt": 1000, "segments": segs}
    if eval_set:
        d["evalSet"] = True
    return d


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

    def test_generic_names(self):
        for n in ("本人", "ゲスト", "配信者", "ＭＣ", "mc", " 司会 ", "話者A", "話者Ａ", "話者", "Speaker 1", "speaker2", "SPK 3", "A", "ｂ", "7", "ナレーション", "その他"):
            self.assertTrue(S.is_generic_speaker_name(n), n)
        for n in ("兎田ぺこら", "ぺこら", "Pekora", "AZKi", "マリン船長", "話者A子", "私たち", "", "  "):
            self.assertFalse(S.is_generic_speaker_name(n), n)

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

    def run_learn(self, spec, vec=(1, 0, 0), calls=None):
        def emb(job, wav, e, groups, off):
            if calls is not None:
                calls.append(groups)
            return [unit(*vec) for _ in groups]
        with mock.patch.object(S, "check_source", lambda p: p), mock.patch.object(S, "extract_audio", lambda *a: None), \
                mock.patch.object(S, "has_sherpa", lambda: True), mock.patch.object(S, "ensure_diar_models", lambda *a: None), \
                mock.patch.object(S, "embed_groups", emb):
            j = self.job(spec)
            S.run_voice_learn(j)
        return j

    def validate(self, req):
        with mock.patch.object(S, "check_source", lambda p: p):
            return S.validate_voice_learn(req)

    def test_learn_named_speakers_only_and_mix(self):
        self.put_doc(doc_with_speakers([("S1", "兎田ぺこら"), ("S2", "話者2")], [(0, 5, "S1", ""), (6, 12, "S2", ""), (13, 20, "S1", "")], proofed=True))
        spec = self.validate({"tid": TID, "embedding": "voxceleb", "names": ["兎田ぺこら", "話者2"]})
        self.assertEqual(spec["names"], ["兎田ぺこら"])   # 仮の名前(話者2)は覚えない
        j = self.run_learn(spec)
        self.assertEqual((j["state"], j["learned"]), ("done", ["兎田ぺこら"]), j.get("error"))
        v = S.load_voices("voxceleb")
        self.assertEqual(list(v), ["兎田ぺこら"])
        self.assertEqual((v["兎田ぺこら"]["rows"], v["兎田ぺこら"]["sec"]), (2, 12.0))
        # もう一度(別の配信)覚えると、使った長さで重みを付けて混ぜる(既にある名前なので「同じ人」の確認が要る)
        with self.assertRaises(S.ApiError) as cm:
            self.validate({"tid": TID, "embedding": "voxceleb", "names": ["兎田ぺこら"]})
        self.assertEqual((cm.exception.code, cm.exception.status, cm.exception.extra), ("confirm_same", 409, {"names": ["兎田ぺこら"]}))
        spec = self.validate({"tid": TID, "embedding": "voxceleb", "names": ["兎田ぺこら"], "confirmSame": ["兎田ぺこら"]})
        self.assertEqual(spec["confirmSame"], ["兎田ぺこら"])
        self.run_learn(spec, vec=(0, 1, 0))
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
        self.put_doc(doc_with_speakers([("S1", "話者1")], [(0, 5, "S1", "")], proofed=True))
        with self.assertRaises(S.ApiError) as cm:
            self.validate({"tid": TID, "names": ["話者1"]})
        self.assertEqual(cm.exception.code, "no_names")

    def test_validate_needs_names_list(self):
        # 古い形(names なし)は受けない: 確認を飛ばして覚えない
        self.put_doc(doc_with_speakers([("S1", "兎田ぺこら")], [(0, 5, "S1", "")], proofed=True))
        for req in ({"tid": TID}, {"tid": TID, "names": "兎田ぺこら"}, {"tid": TID, "names": [1]}):
            with self.assertRaises(S.ApiError) as cm:
                self.validate(req)
            self.assertEqual((cm.exception.code, cm.exception.status), ("bad_request", 400), req)

    def test_learn_uses_proofed_rows_without_sound_tags(self):
        # 監査17: 校正済みで、重なり・BGM・聞き取れないの印が無い、1秒以上・声が混ざっていない行だけを使う
        self.put_doc(doc_with_speakers([("S1", "兎田ぺこら")], [
            (0, 5, "S1", "", True),                        # 使う
            (6, 12, "S1", "", False),                      # 未校正
            (13, 18, "S1", "", True, ["overlap"]),         # 声が重なる
            (19, 24, "S1", "", True, ["bgm"]),             # BGM が大きい
            (25, 30, "S1", "", True, ["unclear"]),         # 聞き取れない
            (31, 36, "S1", S.MIXED_FLAG, True),            # 声が混ざっている
            (37, 37.5, "S1", "", True),                    # 1秒未満
            (40, 47, "S1", "", True, ["other"]),           # 知らない印は無視(使う)
        ]))
        plan = S.voice_learn_plan(S.read_transcript(TID))
        self.assertEqual(plan["groups"]["兎田ぺこら"], ([(0, 5), (40, 47)], 12))
        self.assertEqual(plan["skipped"], {"unproofed": 1, "tagged": 3, "mixed": 1, "short": 1})
        calls = []
        j = self.run_learn(self.validate({"tid": TID, "embedding": "voxceleb", "names": ["兎田ぺこら"]}), calls=calls)
        self.assertEqual(j["state"], "done", j.get("error"))
        self.assertEqual(calls, [[[(0, 5), (40, 47)]]])
        self.assertEqual(S.load_voices("voxceleb")["兎田ぺこら"]["sec"], 12.0)

    def test_unproofed_only_is_refused(self):
        self.put_doc(doc_with_speakers([("S1", "兎田ぺこら")], [(0, 5, "S1", ""), (6, 12, "S1", "")]))
        pv = S.voice_preview(TID, "voxceleb")
        self.assertEqual((pv["people"], pv["refused"], pv["skipped"]["unproofed"]),
                         ([], [{"name": "兎田ぺこら", "speakers": ["S1"], "reason": "no_rows"}], 2))
        with self.assertRaises(S.ApiError) as cm:
            self.validate({"tid": TID, "names": ["兎田ぺこら"]})
        self.assertEqual((cm.exception.code, cm.exception.status), ("no_names", 400))

    def test_eval_set_is_refused(self):
        # 監査02: 評価用は validate(画面の前)と run(待っている間に評価用へ変えた)の両方で断る
        self.put_doc(doc_with_speakers([("S1", "兎田ぺこら")], [(0, 5, "S1", "")], proofed=True, eval_set=True))
        with self.assertRaises(S.ApiError) as cm:
            self.validate({"tid": TID, "names": ["兎田ぺこら"]})
        self.assertEqual((cm.exception.code, cm.exception.status), ("eval_set", 400))
        self.assertTrue(S.voice_preview(TID, "voxceleb")["evalSet"])
        j = self.run_learn({"tid": TID, "embedding": "voxceleb", "names": ["兎田ぺこら"], "confirmSame": []})
        self.assertEqual(j["state"], "error")
        self.assertIn("評価用", j["error"])
        self.assertEqual(S.load_voices("voxceleb"), {})

    def test_generic_names_are_not_learned(self):
        # 監査18: 一般的な名前は覚えない(ほかの名前は覚える)・全員が一般的な名前なら 400
        self.put_doc(doc_with_speakers([("S1", "本人"), ("S2", "ＭＣ"), ("S3", "話者A"), ("S4", "兎田ぺこら")],
                                       [(0, 5, "S1", ""), (6, 12, "S2", ""), (13, 20, "S3", ""), (21, 28, "S4", "")], proofed=True))
        pv = S.voice_preview(TID, "voxceleb")
        self.assertEqual([p["name"] for p in pv["people"]], ["兎田ぺこら"])
        self.assertEqual(sorted((r["name"], r["reason"]) for r in pv["refused"]), sorted([("ＭＣ", "generic"), ("本人", "generic"), ("話者A", "generic")]))
        spec = self.validate({"tid": TID, "embedding": "voxceleb", "names": ["本人", "ＭＣ", "兎田ぺこら"]})
        self.assertEqual(spec["names"], ["兎田ぺこら"])
        self.put_doc(doc_with_speakers([("S1", "本人"), ("S2", "ゲスト")], [(0, 5, "S1", ""), (6, 12, "S2", "")], proofed=True))
        with self.assertRaises(S.ApiError) as cm:
            self.validate({"tid": TID, "names": ["本人", "ゲスト"]})
        self.assertEqual((cm.exception.code, cm.exception.status), ("no_names", 400))
        self.assertIn("一般的な名前", cm.exception.message)

    def test_preview_counts_and_existing(self):
        S.save_voices("voxceleb", {"兎田ぺこら": {"vec": unit(1, 0, 0), "rows": 30, "sec": 240.0, "updatedAt": 5}})
        self.put_doc(doc_with_speakers([("S1", "兎田ぺこら"), ("S2", "さくらみこ"), ("S3", "話者3")], [
            (0, 5, "S1", "", True), (6, 12, "S1", "", False), (13, 20, "S2", "", True), (21, 22.5, "S2", "", True, ["bgm"]), (23, 30, "S3", "", True)]))
        pv = S.voice_preview(TID, "voxceleb")
        self.assertEqual(pv["people"], [
            {"name": "さくらみこ", "speaker": "S2", "speakers": ["S2"], "rows": 1, "sec": 7.0, "exists": False, "old": None},
            {"name": "兎田ぺこら", "speaker": "S1", "speakers": ["S1"], "rows": 1, "sec": 5.0, "exists": True, "old": {"rows": 30, "sec": 240.0, "updatedAt": 5}}])
        self.assertEqual(pv["skipped"], {"unproofed": 1, "tagged": 1, "mixed": 0, "short": 0})   # 仮の名前(話者3)の行は数えない
        self.assertEqual((pv["refused"], pv["evalSet"], pv["embedding"]), ([], False, "voxceleb"))
        self.assertEqual(S.voice_preview(TID, "no-such-model")["embedding"], S.DIAR_EMB_DEFAULT)

    def test_names_added_after_confirm_are_not_learned(self):
        # 確認のあとで名前を付けた人(spec["names"] に無い人)は黙って覚えない
        self.put_doc(doc_with_speakers([("S1", "兎田ぺこら"), ("S2", "話者2")], [(0, 5, "S1", ""), (6, 12, "S2", "")], proofed=True))
        spec = self.validate({"tid": TID, "embedding": "voxceleb", "names": ["兎田ぺこら"]})
        self.put_doc(doc_with_speakers([("S1", "兎田ぺこら"), ("S2", "さくらみこ")], [(0, 5, "S1", ""), (6, 12, "S2", "")], proofed=True))
        j = self.run_learn(spec)
        self.assertEqual((j["state"], j["learned"]), ("done", ["兎田ぺこら"]), j.get("error"))
        self.assertEqual(list(S.load_voices("voxceleb")), ["兎田ぺこら"])

    def test_run_does_not_mix_into_name_learned_meanwhile(self):
        # 確かめたあと・覚える前に、ほかで同じ名前を覚えた: 確かめていない人の声には足さない(注意を出す)
        self.put_doc(doc_with_speakers([("S1", "兎田ぺこら"), ("S2", "さくらみこ")], [(0, 5, "S1", ""), (6, 12, "S2", "")], proofed=True))
        spec = self.validate({"tid": TID, "embedding": "voxceleb", "names": ["兎田ぺこら", "さくらみこ"]})
        S.save_voices("voxceleb", {"兎田ぺこら": {"vec": unit(0, 0, 1), "rows": 3, "sec": 30, "updatedAt": 1}})
        j = self.run_learn(spec)
        self.assertEqual((j["state"], j["learned"]), ("done", ["さくらみこ"]), j.get("error"))
        self.assertEqual(S.load_voices("voxceleb")["兎田ぺこら"]["vec"], unit(0, 0, 1))
        self.assertTrue(any("兎田ぺこら" in w for w in j.get("warnings") or []))

    def test_summary_marks_generic_names(self):
        # すでに一般的な名前で覚えた声は消さず、一覧で知らせる(2026-09-29 ユーザー決定)
        S.save_voices("voxceleb", {"本人": {"vec": unit(1, 0, 0), "rows": 3, "sec": 30, "updatedAt": 1},
                                   "兎田ぺこら": {"vec": unit(0, 1, 0), "rows": 3, "sec": 30, "updatedAt": 1}})
        self.assertEqual({x["name"]: x["generic"] for x in S.voices_summary()["voxceleb"]}, {"本人": True, "兎田ぺこら": False})

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

    def test_names_limit_and_elimination(self):
        """出てくる人の名前(友人からの依頼・2026-10-01): 照らし合わせはその名前だけ、1人ずつ残れば消去法で付ける"""
        S.save_voices("voxceleb", {"兎田ぺこら": {"vec": unit(1, 0, 0), "rows": 3, "sec": 30, "updatedAt": 1},
                                   "さくらみこ": {"vec": unit(0, 1, 0), "rows": 3, "sec": 30, "updatedAt": 1}})
        self.put_doc(doc_with_speakers([("S1", "話者1"), ("S2", "話者2")], [(0, 5, "S1", ""), (6, 12, "S2", "")]))
        vec = {"S1": unit(1, 0.05, 0), "S2": unit(0.05, 1, 0)}   # S2 はみこに似ているが、みこは名前の一覧に無い
        with mock.patch.object(S, "embed_groups", lambda job, wav, emb, groups, off: [vec[k] for k in ("S1", "S2")]):
            named = S.recognize_voices(self.job({}), TID, "x.wav", 0.0, "voxceleb", ["兎田ぺこら", "宝鐘マリン"])
        self.assertEqual([(n["speaker"], n["name"], n["score"] is None) for n in named], [("S1", "兎田ぺこら", False), ("S2", "宝鐘マリン", True)])

    def test_single_speaker(self):
        """1人: 判別せずに全部の行をその人に(編集の「人数」の 1人・友人の依頼の話す人 1人)"""
        self.put_doc(doc_with_speakers([("S1", "話者1"), ("S2", "話者2")], [(0, 5, "S1", S.MIXED_FLAG), (6, 12, "S2", ""), (13, 14, "", S.NONE_FLAG)]))
        with mock.patch.object(S, "check_source", lambda p: p):
            spec = S.validate_diarize({"tid": TID, "numSpeakers": 1, "names": ["さくらみこ", " ", "話者3"]})
        self.assertEqual((spec["numSpeakers"], spec["names"]), (1, ["さくらみこ"]))
        j = self.job(spec)
        S.run_diarize(j)
        self.assertEqual(j["state"], "done", j.get("error"))
        with open(S.tx_path(TID), encoding="utf-8") as f:
            d = json.load(f)
        self.assertEqual(([s["name"] for s in d["speakers"]], {g["speaker"] for g in d["segments"]}, {g["flag"] for g in d["segments"]}),
                         (["さくらみこ"], {"S1"}, {""}))


if __name__ == "__main__":
    unittest.main()
