#!/usr/bin/env python3
"""話者の声を覚える(A-3。git の履歴(679ff01 以前)の docs/archive/backlog-ui-2026-09-27.md)のサーバー側のテスト。

    python -m unittest test_metrics test_resolve_export -q   # test_metrics がこのファイルのテストも読み込む
    python -m unittest test_voices -q                        # これだけ

声の特徴そのもの(sherpa-onnx)は使わず、embed_groups を差し替えて、行の選び方・覚え方(混ぜ方)・照らし合わせの決まり
(しきい値・2番目との差・1つの名前は1人)・仮の名前だけを置き換えることを確かめる。
段1(監査02・17・18): 評価用を断る・校正済みで音のメモが無い行だけ・一般的な名前を断る・覚える前の確認(preview)・既にある名前は確かめてから。
"""
import json
import os
os.environ.setdefault("YTT_DATA_DIR", "inplace")   # テストは作業データを本物の置き場所(AppData など)に書かない(ytt_core.datadir)
import shutil
import tempfile
import unittest
import urllib.request
from unittest import mock

from test_backend import S, TID, StoreDir, free_port, start_server, write_json


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

    def test_assign_ratio_matches_label_ratio(self):
        """割り当てのときに出す割合(_assign の 4 つ目)は、全区間を数え直す label_ratio とちょうど同じ値(判別の記録・ならしが使う)"""
        import random
        rnd = random.Random(7)
        for _ in range(30):
            ts, t = [], 0.0
            for _k in range(rnd.randint(0, 40)):
                a = t + rnd.uniform(-2.0, 3.0)
                ts.append((max(0.0, a), max(0.0, a) + rnd.uniform(0.05, 9.0), rnd.randint(0, 3)))
                t = max(t, a)
            ts.sort()
            segs = []
            for _k in range(rnd.randint(0, 30)):
                a = rnd.uniform(0.0, max(1.0, t + 5))
                segs.append({"start": a, "end": a + rnd.choice((0.0, 0.3, 1.5, 6.0))})
            full = S.ed_speakers._assign(segs, ts)
            self.assertEqual([r[:3] for r in full], S.assign_speakers(segs, ts, 0.0))
            for sg, (sp, _m, _w, ratio) in zip(segs, full):
                self.assertEqual(ratio, S.label_ratio(sg["start"], sg["end"], sp, ts), (sg, sp))

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


class TestDiarRecord(StoreDir):
    """判別の記録 <id>.diar.json(Q2): 機械の最初の割り当て・覚えた声との照合の経過を残す。行の speaker・名前(人の最終)は変えない"""

    def setUp(self):
        super().setUp()
        self.saved_vdir = S.VOICES_DIR
        S.VOICES_DIR = os.path.join(self.tmp, "voices")
        self.saved_delay = os.environ.get("TRANSCRIBE_FAKE_DELAY")
        os.environ["TRANSCRIBE_FAKE_DELAY"] = "0.001"

    def tearDown(self):
        if self.saved_delay is None:
            os.environ.pop("TRANSCRIBE_FAKE_DELAY", None)
        else:
            os.environ["TRANSCRIBE_FAKE_DELAY"] = self.saved_delay
        S.VOICES_DIR = self.saved_vdir
        super().tearDown()

    def job(self, spec):
        return {"id": "j1", "spec": spec, "cancel": False, "state": "queued", "phase": "", "progress": 0.0, "speakers": 0}

    def diarize(self, req):
        with mock.patch.object(S, "check_source", lambda p: p), mock.patch.object(S, "extract_audio", lambda *a: None), \
                mock.patch.object(S, "backend_name", lambda: "fake"), mock.patch.object(S, "embed_groups", lambda job, wav, emb, groups, off: [unit(1, 0, 0) for _ in groups]):
            spec = S.validate_diarize(dict(req, tid=TID))
            j = self.job(spec)
            S.run_diarize(j)
        self.assertEqual(j["state"], "done", j.get("error"))
        return j

    def doc(self):
        return doc_with_speakers([], [(0, 5, "", ""), (8, 14, "", ""), (14.5, 19, "", ""), (21, 28, "", "")])

    def read(self):
        with open(S.diar_path(TID), encoding="utf-8") as f:
            return json.load(f)

    def test_fake_diarize_writes_diar_json(self):
        self.put_doc(self.doc())
        self.diarize({"numSpeakers": 2})
        d = self.read()
        self.assertEqual(d["schema"], "youtube-tools-diar/v1")
        run = d["latest"]
        self.assertEqual((d["history"], run["engine"]["name"], run["engine"]["requested"]), ([], "fake", 2))
        self.assertEqual(run["turns"][0], {"start": 0.0, "end": 10.0, "label": 0})
        self.assertEqual(run["labelMap"], {"0": "S1", "1": "S2"})
        self.assertEqual(sorted(run["rows"]), ["s1", "s2", "s3", "s4"])
        self.assertEqual((run["rows"]["s1"]["speaker"], run["rows"]["s1"]["ratio"], run["rows"]["s1"]["weak"]), ("S1", 1.0, False))
        self.assertTrue(run["rows"]["s2"]["mixed"] or run["rows"]["s2"]["weak"] or run["rows"]["s2"]["ratio"] < 1.0)   # 10 秒でまたぐ行
        self.assertEqual(run["voices"]["checked"], True)   # 覚えた声が無い → 理由 no_voices
        self.assertEqual(run["voices"]["speakers"]["S1"]["reason"], "no_voices")
        self.assertEqual(run["voices"]["speakers"]["S1"]["label"], 0)
        with open(S.tx_path(TID), encoding="utf-8") as f:   # 人の最終(今の行の speaker・名前)は文書のまま
            doc = json.load(f)
        self.assertEqual([g["speaker"] for g in doc["segments"]], [run["rows"][k]["speaker"] for k in ("s1", "s2", "s3", "s4")])
        self.assertNotIn("vec", json.dumps(d))

    def test_overlaps_from_turns(self):
        ts = [(0.0, 10.0, 0), (8.0, 12.0, 1), (11.0, 15.0, 0), (20.0, 25.0, 1)]
        self.assertEqual(S._turn_overlaps(ts), [[8.0, 10.0], [11.0, 12.0]])
        self.assertEqual(S._turn_overlaps([(0, 5, 0), (3, 8, 0)]), [])   # 同じ話者どうしは重なりに数えない

    def test_voice_matching_details_recorded(self):
        S.save_voices("voxceleb", {"兎田ぺこら": {"vec": unit(1, 0, 0), "rows": 3, "sec": 30, "updatedAt": 1}})
        self.put_doc(self.doc())
        j = self.diarize({"numSpeakers": 2})
        named = j["named"]
        v = self.read()["latest"]["voices"]
        self.assertEqual(v["registered"], 1)
        hit = [sid for sid, x in v["speakers"].items() if x["decided"]]
        self.assertEqual([(n["speaker"]) for n in named], hit)   # 付いた名前と記録が同じ
        one = v["speakers"][hit[0]]
        self.assertEqual((one["top"], one["by"], one["reason"], one["score"] >= 0.6), ("兎田ぺこら", "threshold", None, True))
        other = [x for sid, x in v["speakers"].items() if sid not in hit]   # 同じ名前は1人だけ → もう1人は付かない
        self.assertTrue(all(x["decided"] is None and x["reason"] in ("name_taken", "already_named", "name_in_use") for x in other), other)

    def test_explain_reasons(self):
        voices = {"a": {"vec": unit(1, 0, 0)}, "b": {"vec": unit(0.9, 0.2, 0)}}
        out, info = S.match_voices_explain({"S1": unit(0, 0, 1), "S2": unit(1, 0.1, 0), "S3": None}, voices)
        self.assertEqual(out, {})
        self.assertEqual((info["S1"]["reason"], info["S2"]["reason"], info["S3"]["reason"]), ("below_match", "margin", "no_feature"))
        self.assertEqual((info["S2"]["top"], info["S2"]["second"]), ("a", "b"))
        self.assertTrue(info["S2"]["score"] - info["S2"]["secondScore"] < S.VOICE_MARGIN)
        out, info = S.match_voices_explain({"S1": unit(1, 0, 0)}, {"a": {"vec": unit(1, 0, 0)}})
        self.assertEqual((out, info["S1"]["by"]), ({"S1": ("a", 1.0)}, "threshold"))

    def test_single_speaker_writes_diar_json(self):
        self.put_doc(self.doc())
        with mock.patch.object(S, "check_source", lambda p: p):
            spec = S.validate_diarize({"tid": TID, "numSpeakers": 1, "names": ["さくらみこ"]})
        j = self.job(spec)
        S.run_diarize(j)
        self.assertEqual(j["state"], "done", j.get("error"))
        run = self.read()["latest"]
        self.assertEqual((run["engine"]["name"], run["turns"], sorted(run["rows"]), run["voices"]["speakers"]["S1"]["decided"]), ("single", [], ["s1", "s2", "s3", "s4"], "さくらみこ"))
        self.assertEqual({r["speaker"] for r in run["rows"].values()}, {"S1"})

    def test_redo_keeps_previous_runs(self):
        self.put_doc(self.doc())
        self.diarize({"numSpeakers": 2})
        first = self.read()["latest"]["at"]
        self.diarize({"numSpeakers": 3})
        d = self.read()
        self.assertEqual((len(d["history"]), d["history"][0]["at"], d["history"][0]["engine"]["requested"], d["latest"]["engine"]["requested"]), (1, first, 2, 3))
        with mock.patch.object(S, "check_source", lambda p: p):
            S.run_diarize(self.job(S.validate_diarize({"tid": TID, "numSpeakers": 1})))   # 1人指定のし直しも前を残す
        d = self.read()
        self.assertEqual(([h["engine"]["requested"] for h in d["history"]], d["latest"]["engine"]["name"]), ([3, 2], "single"))
        for n in range(6):
            self.diarize({"numSpeakers": 2})
        d = self.read()
        self.assertEqual(len(d["history"]), S.DIAR_KEEP - 1)   # 最新を含めて 5 回まで

    def test_write_failure_does_not_fail_diarize(self):
        self.put_doc(self.doc())
        with mock.patch.object(S, "write_diar", side_effect=OSError("disk full")):
            self.diarize({"numSpeakers": 2})
        self.assertFalse(os.path.exists(S.diar_path(TID)))
        with open(S.tx_path(TID), encoding="utf-8") as f:
            self.assertTrue(json.load(f)["speakers"])   # 判別の結果は残る


class TestOtherVoice(StoreDir):
    """組み込みの話者「ゲーム音声など」・行の印「字幕に出さない」(noSub)・話者ごとの字幕の見た目(sub)(2026-10-05。plan/line-b-overlap.md の 6)"""

    def setUp(self):
        super().setUp()
        self.saved_vdir = S.VOICES_DIR
        S.VOICES_DIR = os.path.join(self.tmp, "voices")

    def tearDown(self):
        S.VOICES_DIR = self.saved_vdir
        super().tearDown()

    def job(self, spec):
        return {"id": "j1", "spec": spec, "cancel": False, "state": "queued", "phase": "", "progress": 0.0, "speakers": 0}

    def read(self):
        with open(S.tx_path(TID), encoding="utf-8") as f:
            return json.load(f)

    def manual_doc(self):
        """s2 = ゲーム音声など(字幕に出さない)・s3 = 話者なしで字幕に出さない・s4 = 手で作った重なる行(声が重なる・ぺこら)"""
        d = doc_with_speakers([("S1", "話者1"), ("S2", "ぺこら")],
                              [(0, 5, "S1", ""), (8, 14, "other", "要確認"), (14.5, 19, "", ""), (21, 28, "S2", "", False, ["overlap"]), (30, 35, "", "")])
        d["speakers"].append({"id": "other", "name": "ゲーム音声など", "color": "#8a8f98", "builtin": "other"})
        d["segments"][1]["noSub"] = True
        d["segments"][2]["noSub"] = True
        return d

    def test_sanitize_keeps_marks_and_checks_sub(self):
        base = {"segments": [], "original": [{"start": 0, "end": 1, "text": "機械"}]}
        out = S.sanitize_transcript({"speakers": [
            {"id": "S1", "name": "ぺこら", "color": "#888", "sub": {"color": "ff8fdf", "font": "x", "size": 3}},
            {"id": "S2", "name": "みこ", "sub": {"color": "#12345"}},
            {"id": "other", "name": "書き換え", "color": "red", "sub": {"color": "#000000"}},
            {"id": "S3", "name": "x", "builtin": "other"}] + [{"id": "P%d" % i, "name": "p"} for i in range(20)],
            "segments": [{"id": "a", "start": 0, "end": 1, "text": "x", "speaker": "other", "noSub": True},
                         {"id": "b", "start": 1, "end": 2, "text": "y", "noSub": "yes"}]}, base)
        sp = {s["id"]: s for s in out["speakers"]}
        self.assertEqual(sp["S1"]["sub"], {"color": "#FF8FDF"})                     # 鍵ごとの許可の一覧(知らない鍵は捨てる・大文字の #RRGGBB)
        self.assertNotIn("sub", sp["S2"])                                           # 形の違う値は sub ごと持たない
        self.assertEqual(sp["other"], {"id": "other", "name": S.OTHER_SPK_NAME, "color": S.OTHER_SPK_COLOR, "builtin": "other"})   # 名前は変えさせない
        self.assertNotIn("builtin", sp["S3"])                                       # 決まった id の話者だけが組み込み
        self.assertEqual(len([s for s in out["speakers"] if s["id"] != "other"]), 20)   # 組み込みは 20 人に数えない
        self.assertEqual([(g["id"], g.get("noSub")) for g in out["segments"]], [("a", True), ("b", None)])   # 真のときだけ持つ
        self.assertEqual(out["segments"][0]["speaker"], "other")
        self.assertEqual(out["original"], base["original"])                         # 機械の出力は変えない

    def test_other_name_is_generic(self):
        self.assertTrue(S.is_generic_speaker_name("ゲーム音声など"))
        plan = S.voice_learn_plan(self.manual_doc())
        self.assertNotIn("ゲーム音声など", plan["groups"])
        self.assertFalse(any(r["name"] == "ゲーム音声など" for r in plan["refused"]))   # 断った扱いにもしない(一覧に出さない)

    def test_rediarize_keeps_manual_rows(self):
        """判別のやり直しは、字幕に出さない行・ゲーム音声などの行・重なりのメモつきで話者のある行の話者を変えない"""
        self.put_doc(self.manual_doc())
        with mock.patch.object(S, "check_source", lambda p: p), mock.patch.object(S, "extract_audio", lambda *a: None), \
                mock.patch.object(S, "backend_name", lambda: "fake"), mock.patch.object(S, "embed_groups", lambda job, wav, emb, groups, off: [unit(1, 0, 0) for _ in groups]):
            j = self.job(S.validate_diarize({"tid": TID, "numSpeakers": 2}))
            S.run_diarize(j)
        self.assertEqual(j["state"], "done", j.get("error"))
        d = self.read()
        g = {x["id"]: x for x in d["segments"]}
        names = {s["id"]: s["name"] for s in d["speakers"]}
        self.assertEqual((g["s2"]["speaker"], g["s2"]["noSub"], g["s2"]["flag"]), ("other", True, "要確認"))   # 印もそのまま
        self.assertEqual((g["s3"]["speaker"], g["s3"]["noSub"]), ("", True))
        self.assertEqual(names[g["s4"]["speaker"]], "ぺこら")                       # 重なる行の話者は同じ人のまま(id は新しい S2 と重ならないよう付け替え)
        self.assertNotEqual(g["s4"]["speaker"], "S2")
        self.assertIn(g["s1"]["speaker"], ("S1", "S2"))                            # 守らない行は判別のとおり
        self.assertEqual(d["speakers"][-1]["id"], "other")                         # 組み込みは最後(Alt+数字の番号に入らない)
        self.assertEqual(len({s["id"] for s in d["speakers"]}), len(d["speakers"]))

    def test_single_speaker_keeps_manual_rows(self):
        """「全行をこの人に」(1人指定)も同じ。同じ名前の守った話者は 1 人にまとめる"""
        self.put_doc(self.manual_doc())
        with mock.patch.object(S, "check_source", lambda p: p):
            j = self.job(S.validate_diarize({"tid": TID, "numSpeakers": 1, "names": ["ぺこら"]}))
        S.run_diarize(j)
        self.assertEqual(j["state"], "done", j.get("error"))
        d = self.read()
        self.assertEqual([(x["id"], x["speaker"]) for x in d["segments"]], [("s1", "S1"), ("s2", "other"), ("s3", ""), ("s4", "S1"), ("s5", "S1")])
        self.assertEqual([(s["id"], s["name"]) for s in d["speakers"]], [("S1", "ぺこら"), ("other", "ゲーム音声など")])

    def test_recognize_and_autodiar_ignore_other_rows(self):
        S.save_voices("voxceleb", {"兎田ぺこら": {"vec": unit(1, 0, 0), "rows": 3, "sec": 30, "updatedAt": 1}})
        d = self.manual_doc()
        d["speakers"][0]["name"] = "話者1"
        d["speakers"][1]["name"] = "話者2"
        self.put_doc(d)
        seen = []

        def emb(job, wav, e, groups, off):
            seen.extend(groups)
            return [unit(1, 0, 0)] + [unit(0, 0, 1)] * (len(groups) - 1)
        with mock.patch.object(S, "embed_groups", emb):
            S.recognize_voices(self.job({}), TID, "x.wav", 0.0, "voxceleb")
        self.assertFalse(any(a == 8 for g in seen for a, _b in g))   # ゲーム音声などの行(8〜14 秒)の声は照らし合わせない
        self.assertEqual(self.read()["speakers"][-1]["name"], "ゲーム音声など")
        # 自動の判別: 守る行(ゲーム音声など・字幕に出さない・重なりのメモ)だけに話者があるなら「話者あり」に数えない
        d2 = self.manual_doc()
        d2["segments"][0]["speaker"] = ""
        self.assertIsNone(S.autodiar_why_not(d2))
        self.assertEqual(S.autodiar_why_not(self.manual_doc()), "has_speakers")
        # 動画の手がかりの名前は、仮の名前の話者のうち話した秒の長い人に(字幕に出さない行は数えない・組み込みには付けない)
        d3 = self.manual_doc()
        d3["speakers"][1]["name"] = "話者2"
        d3["segments"][1]["end"] = 100.0   # ゲーム音声などが長くても選ばれない
        self.put_doc(d3)
        hit = S.autodiar_name_by_context(TID, "さくらみこ")
        self.assertIn(hit["speaker"], ("S1", "S2"))

    def test_speakers_sub_api(self):
        d = self.manual_doc()
        d["speakers"][1]["name"] = "兎田 ぺこら"
        d["speakers"][1]["sub"] = {"color": "#111111", "future": "x"}
        self.put_doc(d)
        before = self.read()["updatedAt"]
        r = S.speakers_sub_apply({"id": TID, "styles": {"兎田　ぺこら ": {"color": "7ec2fe", "font": "x"}, "いない人": {"color": "#000000"},
                                                        "ゲーム音声など": {"color": "#FFFFFF"}}})
        self.assertEqual(r, {"ok": True, "applied": ["兎田 ぺこら"]})                # NFKC・空白を寄せて名前がちょうど合った人だけ(組み込みには入れない)
        d2 = self.read()
        self.assertEqual(d2["speakers"][1]["sub"], {"color": "#7EC2FE"})            # 保存する形は検査のとおり(知らない鍵は持たない)
        self.assertNotIn("sub", d2["speakers"][-1])
        self.assertGreater(d2["updatedAt"], before)
        self.assertEqual(S.speakers_sub_apply({"id": TID, "styles": {"だれも": {"color": "#000000"}}}), {"ok": True, "applied": []})
        for bad in ({"id": TID, "styles": []}, {"id": TID, "styles": {"a": "#000000"}}, {"id": TID, "styles": {"a": {"color": "#00000g"}}}, {"id": "x", "styles": {}}):
            with self.assertRaises(S.ApiError) as cm:
                S.speakers_sub_apply(bad)
            self.assertEqual(cm.exception.status, 400, bad)
        with self.assertRaises(S.ApiError) as cm:
            S.speakers_sub_apply({"id": "fedcba987654", "styles": {}})
        self.assertEqual(cm.exception.status, 404)
        with mock.patch.dict(S._jobs, {"jx": {"kind": "diarize", "state": "running", "tid": TID, "spec": {"tid": TID}}}):
            with self.assertRaises(S.ApiError) as cm:
                S.speakers_sub_apply({"id": TID, "styles": {"兎田 ぺこら": {"color": "#000000"}}})
            self.assertEqual((cm.exception.status, cm.exception.code), (409, "busy"))
        with mock.patch.dict(S._jobs, {"jy": {"kind": "alt", "state": "running", "tid": TID, "spec": {"tid": TID}}}):   # 文書を書き換えないジョブは止めない
            self.assertEqual(S.speakers_sub_apply({"id": TID, "styles": {"兎田 ぺこら": {"color": "#000000"}}})["applied"], ["兎田 ぺこら"])

    def test_pack_output_speaker_styles(self):
        base = {"fps": "30", "size": "1080x1920", "wrap": 8, "textplus": True, "backup": False, "render": False, "speakerColors": False}
        out = S.sanitize_pack_output(dict(base, speakerStyles={"ぺこら": {"color": "7ec2fe", "x": 1}}))
        self.assertEqual(out["speakerStyles"], {"ぺこら": {"color": "#7EC2FE"}})
        self.assertIsNone(S.sanitize_pack_output(dict(base, speakerStyles={"ぺこら": {"color": "bad"}})))
        self.assertNotIn("speakerStyles", S.sanitize_pack_output(base))

    def test_eval_redo_treats_nosub_as_touched(self):
        segs = [{"id": "s1", "start": 0.0, "end": 2.0, "text": "a", "speaker": "", "flag": ""}, {"id": "s2", "start": 2.0, "end": 4.0, "text": "b", "speaker": "", "flag": ""}]
        d = {"evalSet": True, "model": "small", "segments": [dict(g) for g in segs], "original": [dict(g) for g in segs], "updatedAt": 1, "speakers": []}
        self.assertIsNone(S.eb_redo_why(TID, d, now=10 ** 13, media=False))   # 前提: 手つかず
        d["segments"][1]["noSub"] = True
        self.assertEqual(S.eb_redo_why(TID, d, now=10 ** 13, media=False), "noSub")
        self.assertIn("noSub", S.EB_REDO_TOUCHED)
        self.assertEqual(S._eb_touched_rows(d, "noSub"), 1)


class TestExclusive(StoreDir):
    """同じ文書に同時に入れない組み合わせ(ed_jobs.EXCLUSIVE)は、入口の検査(validate_*)と登録(add_job)で同じ組を断る
    (10-08 の見直しの疑い 11: 声を覚える・判別・再認識で、入口と登録の組がずれていた)"""

    def active(self, kind):
        return mock.patch.dict(S._jobs, {"jx": {"id": "jx", "kind": kind, "state": "queued", "tid": TID, "spec": {"tid": TID}}})

    def busy(self, fn):
        with self.assertRaises(S.ApiError) as cm:
            fn()
        self.assertEqual((cm.exception.status, cm.exception.code), (409, "busy"))

    def test_add_job_refuses_what_validate_refuses(self):
        # 声を覚える: 入口は再認識・疑わしい所の最中を断る。登録(add_job)も同じ組で断る(以前は判別と声を覚えるだけ)
        for other in ("retranscribe", "redo"):
            with self.active(other):
                self.busy(lambda: S.add_job({"tid": TID, "title": "t"}, "voice-learn"))
        self.assertNotIn("voice-learn", [j.get("kind") for j in S._jobs.values() if j["spec"].get("tid") == TID])

    def test_validate_refuses_what_add_job_refuses(self):
        self.put_doc(doc_with_speakers([("S1", "兎田ぺこら")], [(0, 5, "S1", ""), (6, 12, "S1", "")], proofed=True))
        with mock.patch.object(S, "check_source", lambda p: p):
            for other in ("redo", "voice-learn"):   # 判別: 以前の入口は判別・再認識だけを見て、疑わしい所・声を覚えるは登録で断っていた
                with self.active(other):
                    self.busy(lambda: S.validate_diarize({"tid": TID}))
            with self.active("redo"):   # 再認識: 以前の入口は疑わしい所の最中を見ていなかった
                self.busy(lambda: S.validate_retranscribe({"tid": TID, "ids": ["s1"]}))
            with self.active("diarize"):
                self.busy(lambda: S.validate_voice_learn({"tid": TID, "names": ["兎田ぺこら"]}))

    def test_table_is_the_only_rule(self):
        for kind in ("diarize", "voice-learn", "retranscribe", "redo"):
            for other in S.EXCLUSIVE[kind]:
                self.assertIn(other, S.EXCLUSIVE, (kind, other))
        self.assertEqual(set(S.EXCLUSIVE["voice-learn"]), {"diarize", "retranscribe", "redo", "voice-learn"})

    def test_table_is_symmetric(self):
        """0.65.0(decisions (fp)): a が b を断るなら b も a を断る(表の全組)。再認識・疑わしい所も声を覚えるの最中は断る
        (声を覚える途中で行の時刻が変わると、覚える区間がずれる)。サムネの案 thumb は文書を読むだけなので同じ種類どうしだけ(ほかと同時でよい)"""
        for a, others in S.EXCLUSIVE.items():
            for b in others:
                self.assertIn(b, S.EXCLUSIVE, (a, b))
                self.assertIn(a, S.EXCLUSIVE[b], "%s は %s を断るが、%s は %s を断らない" % (a, b, b, a))
        self.assertEqual(S.EXCLUSIVE["thumb"], ("thumb",))
        for kind in ("retranscribe", "redo"):
            self.assertIn("voice-learn", S.EXCLUSIVE[kind])
            with self.active("voice-learn"):   # 登録(add_job)も声を覚えるの最中は断る
                self.busy(lambda: S.add_job({"tid": TID, "title": "t"}, kind))

    def test_retranscribe_refused_while_learning_voices(self):
        self.put_doc(doc_with_speakers([("S1", "兎田ぺこら")], [(0, 5, "S1", ""), (6, 12, "S1", "")], proofed=True))
        with mock.patch.object(S, "check_source", lambda p: p), self.active("voice-learn"):
            with self.assertRaises(S.ApiError) as cm:
                S.validate_retranscribe({"tid": TID, "ids": ["s1"]})
        self.assertEqual((cm.exception.status, cm.exception.code), (409, "busy"))
        self.assertIn("声を覚える", cm.exception.message)


class TestDiarDelete(unittest.TestCase):
    """文書を消すと <id>.diar.json も消える(serve.py の _delete)"""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        cls.port = free_port()
        cls.proc = start_server(cls.tmp, cls.port, os.path.join(cls.tmp, ".runtime"))
        cls.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    @classmethod
    def tearDownClass(cls):
        cls.proc.terminate()
        cls.proc.wait(timeout=10)
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_delete_removes_diar_json(self):
        txdir = os.path.join(self.tmp, "transcripts")
        os.makedirs(txdir, exist_ok=True)
        write_json(os.path.join(txdir, TID + ".json"), doc_with_speakers([("S1", "話者1")], [(0, 5, "S1", "")]))
        dp = os.path.join(txdir, TID + ".diar.json")
        write_json(dp, {"schema": "youtube-tools-diar/v1", "latest": {"rows": {}}, "history": []})
        req = urllib.request.Request("http://127.0.0.1:%d/api/transcript?id=%s" % (self.port, TID), method="DELETE")
        with self.opener.open(req, timeout=30) as r:
            self.assertEqual(r.status, 200)
        self.assertFalse(os.path.exists(dp))
        self.assertFalse(os.path.exists(os.path.join(txdir, TID + ".json")))

    def post(self, path, body, headers=None):
        req = urllib.request.Request("http://127.0.0.1:%d%s" % (self.port, path), method="POST", data=json.dumps(body, ensure_ascii=False).encode(),
                                     headers=dict({"Content-Type": "application/json"}, **(headers or {})))
        try:
            with self.opener.open(req, timeout=30) as r:
                return r.status, json.loads(r.read())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read() or b"{}")

    def test_speakers_sub_http(self):
        """POST /api/speakers/sub(入口のまとめて実行が呼ぶ形)。書き込み系なので Host/Origin の検査も今の POST と同じ道"""
        tid = "abcdefabcdef"
        txdir = os.path.join(self.tmp, "transcripts")
        os.makedirs(txdir, exist_ok=True)
        write_json(os.path.join(txdir, tid + ".json"), doc_with_speakers([("S1", "兎田ぺこら"), ("S2", "話者2")], [(0, 5, "S1", ""), (6, 9, "S2", "")]))
        self.assertEqual(self.post("/api/speakers/sub", {"id": tid, "styles": {"兎田ぺこら": {"color": "#7ec2fe"}}}), (200, {"ok": True, "applied": ["兎田ぺこら"]}))
        with open(os.path.join(txdir, tid + ".json"), encoding="utf-8") as f:
            self.assertEqual(json.load(f)["speakers"][0]["sub"], {"color": "#7EC2FE"})
        self.assertEqual(self.post("/api/speakers/sub", {"id": "fedcba987654", "styles": {}})[0], 404)
        self.assertEqual(self.post("/api/speakers/sub", {"id": tid, "styles": {"兎田ぺこら": {"color": "red"}}})[0], 400)
        self.assertEqual(self.post("/api/speakers/sub", {"id": tid, "styles": {}}, {"Origin": "http://evil.example"})[0], 403)


if __name__ == "__main__":
    unittest.main()
