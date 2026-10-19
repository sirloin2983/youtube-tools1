#!/usr/bin/env python3
"""話者の声を覚える(A-3)のサーバー側のテスト。

    python -m unittest test_metrics test_resolve_export -q   # test_metrics がこのファイルのテストも読み込む
    python -m unittest test_voices -q                        # これだけ

声の特徴そのもの(sherpa-onnx)は使わず、embed_groups を差し替えて、行の選び方・覚え方(混ぜ方)・照らし合わせの決まり
(しきい値・2番目との差・1つの名前は1人)・仮の名前だけを置き換えることを確かめる。
段1(監査02・17・18): 評価用を断る・校正済みで音のメモが無い行だけ・一般的な名前を断る・覚える前の確認(preview)・既にある名前は確かめてから。
TestDiarRealRun だけは本物の sherpa-onnx(判別・声の特徴)で、Windows の音声合成の 2 人の声を 判別 → 声を覚える(2 回)→ 判別し直して名前を付ける まで通す
(モデルは本物の作業データの models/diar から読むだけ。部品・モデル・音声合成が無い PC では飛ばす)。
"""
import importlib.util
import json
import os
os.environ.setdefault("YTT_DATA_DIR", "inplace")   # テストは作業データを本物の置き場所(AppData など)に書かない(ytt.datadir)
import shutil
import tempfile
import unittest
from unittest import mock

from test_backend import S, TID, StoreDir
from pipeline.transcribe import diarize as transcribe_diarize  # noqa: E402
from pipeline.transcribe import worker_client  # noqa: E402
from ytt import schemas as ys  # noqa: E402

_FILL_LLM = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "pipeline", "transcribe", "tests", "test_fill_llm.py")
_spec = importlib.util.spec_from_file_location("_tx_test_fill_llm", _FILL_LLM)
_fill_llm = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_fill_llm)   # 声の見本を書く say_wav・本物のモデルの置き場所(読むだけ)
REAL_DIAR = os.path.join(_fill_llm.REAL_HOME, "models", "diar")


def _diar_ready():
    files = [os.path.join(REAL_DIAR, x["file"]) for x in (transcribe_diarize.DIAR_SEG, transcribe_diarize.DIAR_EMBS[transcribe_diarize.DIAR_EMB_DEFAULT])]
    return _fill_llm._have_sherpa() and all(os.path.isfile(f) and os.path.getsize(f) > 1000 for f in files)   # 取りに行く条件(diarize._have)と同じ


def _no_download(*a, **kw):
    raise AssertionError("話者判別のモデルを取りに行こうとした")


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
    def test_groups_cap_longest_first(self):
        segs = [{"start": i * 10.0, "end": i * 10.0 + 8, "speaker": "S1"} for i in range(60)]
        pick, tot = S.voice_groups(segs, lambda x: "S1")["S1"]
        self.assertLessEqual(len(pick), S.VOICE_MAX_ROWS)
        self.assertLessEqual(tot, S.VOICE_MAX_SEC + 8)

    def test_match_threshold_margin_and_one_to_one(self):
        voices = {"ぺこら": {"vec": unit(1, 0, 0)}, "みこ": {"vec": unit(0, 1, 0)}}
        got, _info = S.match_voices_explain({"S1": unit(0.95, 0.1, 0), "S2": unit(0.1, 0.9, 0.1), "S3": unit(0, 0, 1)}, voices)
        self.assertEqual({k: v[0] for k, v in got.items()}, {"S1": "ぺこら", "S2": "みこ"})   # S3 はどの声とも似ていない
        got, _info = S.match_voices_explain({"S1": unit(1, 1, 0)}, voices)       # 2人のちょうど間: 差が無いので決めない
        self.assertEqual(got, {})
        got, _info = S.match_voices_explain({"S1": unit(1, 0.05, 0), "S2": unit(1, 0.1, 0)}, voices)   # 同じ名前は1人にだけ(似ている方)
        self.assertEqual({k: v[0] for k, v in got.items()}, {"S1": "ぺこら"})
        voices = {"a": {"vec": unit(1, 0, 0)}, "b": {"vec": unit(0.9, 0.2, 0)}}
        out, info = S.match_voices_explain({"S1": unit(0, 0, 1), "S2": unit(1, 0.1, 0), "S3": None}, voices)
        self.assertEqual(out, {})
        self.assertEqual((info["S1"]["reason"], info["S2"]["reason"], info["S3"]["reason"]), ("below_match", "margin", "no_feature"))
        self.assertEqual((info["S2"]["top"], info["S2"]["second"]), ("a", "b"))
        self.assertTrue(info["S2"]["score"] - info["S2"]["secondScore"] < S.VOICE_MARGIN)
        out, info = S.match_voices_explain({"S1": unit(1, 0, 0)}, {"a": {"vec": unit(1, 0, 0)}})
        self.assertEqual((out, info["S1"]["by"]), ({"S1": ("a", 1.0)}, "threshold"))

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
            full = transcribe_diarize._assign(segs, ts)
            self.assertEqual([r[:3] for r in full], S.assign_speakers(segs, ts, 0.0))
            for sg, (sp, _m, _w, ratio) in zip(segs, full):
                self.assertEqual(ratio, S.label_ratio(sg["start"], sg["end"], sp, ts), (sg, sp))

    def test_fake_embeddings_follow_fake_diarization(self):
        a, b, c = S.embed_fake([[[0, 8]], [[21, 29]], [[10, 18]]])
        self.assertGreater(S._cos(a, b), 0.99)                     # 0〜10秒と20〜30秒は同じ偽の話者(偽の判別は既定 2人が 10秒ごとに入れ替わる)
        self.assertLess(S._cos(a, c), S.VOICE_MATCH)


class VoiceDir(StoreDir):
    """覚えた声の置き場所を一時フォルダに向け、ジョブの入れ物と文書の読み出しを用意する"""

    def setUp(self):
        super().setUp()
        self.patch(S, "VOICES_DIR", os.path.join(self.tmp, "voices"))

    def job(self, spec):
        return {"id": "j1", "spec": spec, "cancel": False, "state": "queued", "phase": "", "progress": 0.0, "speakers": 0}

    def read(self):
        with open(S.tx_path(TID), encoding="utf-8") as f:
            return json.load(f)


class TestVoiceStore(VoiceDir):
    def run_learn(self, spec, vec=(1, 0, 0)):
        def emb(job, wav, e, groups, off):
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

    def test_learn_refusals(self):
        """覚える前の確認(validate・preview)と実行で断る: 古い形(names なし)・仮の名前だけ・校正済みの行が無い・評価用(待っている間に変えた場合も)・全員が一般的な名前"""
        self.put_doc(doc_with_speakers([("S1", "兎田ぺこら")], [(0, 5, "S1", "")], proofed=True))
        for req in ({"tid": TID}, {"tid": TID, "names": "兎田ぺこら"}, {"tid": TID, "names": [1]}):
            with self.assertRaises(S.ApiError) as cm:
                self.validate(req)
            self.assertEqual((cm.exception.code, cm.exception.status), ("bad_request", 400), req)
        for names, rows, proofed, eval_set, code, word in (
                ([("S1", "話者1")], [(0, 5, "S1", "")], True, False, "no_names", None),
                ([("S1", "兎田ぺこら")], [(0, 5, "S1", ""), (6, 12, "S1", "")], False, False, "no_names", None),
                ([("S1", "兎田ぺこら")], [(0, 5, "S1", "")], True, True, "eval_set", None),
                ([("S1", "本人"), ("S2", "ゲスト")], [(0, 5, "S1", ""), (6, 12, "S2", "")], True, False, "no_names", "一般的な名前")):
            with self.subTest(code=code, names=names):
                self.put_doc(doc_with_speakers(names, rows, proofed=proofed, eval_set=eval_set))
                with self.assertRaises(S.ApiError) as cm:
                    self.validate({"tid": TID, "names": [n for _i, n in names]})
                self.assertEqual((cm.exception.code, cm.exception.status), (code, 400))
                if word:
                    self.assertIn(word, cm.exception.message)
        pv = S.voice_preview(TID, "voxceleb")
        self.assertEqual(sorted((r["name"], r["reason"]) for r in pv["refused"]), [("ゲスト", "generic"), ("本人", "generic")])
        self.put_doc(doc_with_speakers([("S1", "兎田ぺこら")], [(0, 5, "S1", ""), (6, 12, "S1", "")]))
        pv = S.voice_preview(TID, "voxceleb")
        self.assertEqual((pv["people"], pv["refused"], pv["skipped"]["unproofed"]), ([], [{"name": "兎田ぺこら", "speakers": ["S1"], "reason": "no_rows"}], 2))
        self.put_doc(doc_with_speakers([("S1", "兎田ぺこら")], [(0, 5, "S1", "")], proofed=True, eval_set=True))
        self.assertTrue(S.voice_preview(TID, "voxceleb")["evalSet"])
        j = self.run_learn({"tid": TID, "embedding": "voxceleb", "names": ["兎田ぺこら"], "confirmSame": []})
        self.assertEqual(j["state"], "error")
        self.assertIn("評価用", j["error"])
        self.assertEqual(S.load_voices("voxceleb"), {})

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
        # すでに一般的な名前で覚えた声は消さず、一覧で知らせる(ユーザー決定)
        S.save_voices("voxceleb", {"本人": {"vec": unit(1, 0, 0), "rows": 3, "sec": 30, "updatedAt": 1},
                                   "兎田ぺこら": {"vec": unit(0, 1, 0), "rows": 3, "sec": 30, "updatedAt": 1}})
        self.assertEqual({x["name"]: x["generic"] for x in S.voices_summary()["voxceleb"]}, {"本人": True, "兎田ぺこら": False})

    def test_names_limit_and_elimination(self):
        """出てくる人の名前(友人からの依頼): 照らし合わせはその名前だけ、1人ずつ残れば消去法で付ける"""
        S.save_voices("voxceleb", {"兎田ぺこら": {"vec": unit(1, 0, 0), "rows": 3, "sec": 30, "updatedAt": 1},
                                   "さくらみこ": {"vec": unit(0, 1, 0), "rows": 3, "sec": 30, "updatedAt": 1}})
        self.put_doc(doc_with_speakers([("S1", "話者1"), ("S2", "話者2")], [(0, 5, "S1", ""), (6, 12, "S2", "")]))
        vec = {"S1": unit(1, 0.05, 0), "S2": unit(0.05, 1, 0)}   # S2 はみこに似ているが、みこは名前の一覧に無い
        with mock.patch.object(S, "embed_groups", lambda job, wav, emb, groups, off: [vec[k] for k in ("S1", "S2")]):
            named = S._recognize_voices(self.job({}), TID, "x.wav", 0.0, "voxceleb", ["兎田ぺこら", "宝鐘マリン"])
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
        S.run_diarize(self.job(spec))   # 1 人指定のし直しも前の判別を残す
        dz = S.read_diar(TID)
        run = dz["latest"]
        self.assertEqual((run["engine"]["name"], run["turns"], sorted(run["rows"]), run["voices"]["speakers"]["S1"]["decided"], len(dz["history"])),
                         ("single", [], ["s1", "s2", "s3"], "さくらみこ", 1))
        self.assertEqual({r["speaker"] for r in run["rows"].values()}, {"S1"})


class TestDiarRecord(VoiceDir):
    """判別の記録 <id>.diar.json が書けなくても判別の結果は残す(保存の失敗は本物の通しでは起こせない。疑似の判別)"""

    def test_write_failure_does_not_fail_diarize(self):
        self.put_doc(doc_with_speakers([], [(0, 5, "", ""), (8, 14, "", ""), (14.5, 19, "", ""), (21, 28, "", "")]))
        with mock.patch.dict(os.environ, {"TRANSCRIBE_FAKE_DELAY": "0.001"}), mock.patch.object(S, "check_source", lambda p: p), \
                mock.patch.object(S, "extract_audio", lambda *a: None), mock.patch.object(S, "backend_name", lambda: "fake"), \
                mock.patch.object(S, "embed_groups", lambda job, wav, emb, groups, off: [unit(1, 0, 0) for _ in groups]), \
                mock.patch.object(S, "write_diar", side_effect=OSError("disk full")):
            j = self.job(S.validate_diarize({"tid": TID, "numSpeakers": 2}))
            S.run_diarize(j)
        self.assertEqual(j["state"], "done", j.get("error"))
        self.assertFalse(os.path.exists(S.diar_path(TID)))
        with open(S.tx_path(TID), encoding="utf-8") as f:
            self.assertTrue(json.load(f)["speakers"])   # 判別の結果は残る


@unittest.skipUnless(_diar_ready(), "sherpa-onnx か話者判別のモデルが無い")
class TestDiarRealRun(VoiceDir):
    """本物の判別の通し: 2 人の声(日本語の声 → 低くした英語の声 → 日本語の声)。行は 校正済み・音のメモ・短い行・手で作った行(ゲーム音声など・字幕に出さない)・
    声の外の定型の幻覚(autoFill の文書は判別のあとに捨てる)を混ぜる"""

    @classmethod
    def setUpClass(cls):
        cls.src = tempfile.mkdtemp(prefix="ytt-diar-real-")
        cls.wav = os.path.join(cls.src, "talk.wav")
        cls.spans = _fill_llm.say_wav(cls.wav, [("ja", "こんにちは、今日はみんなでゲームをします。よろしくお願いします。"),
                                                ("en", "Hello everyone, thank you for joining the stream today."),
                                                ("ja", "それでは始めましょう。まずは操作の確認からです。")])

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.src, ignore_errors=True)

    def setUp(self):
        if not self.spans:
            self.skipTest("音声合成か ffmpeg が無い")
        super().setUp()
        for obj, name, value in ((worker_client, "IN_WORKER", True), (transcribe_diarize, "DIAR_DIR", REAL_DIAR), (transcribe_diarize, "has_sherpa", _fill_llm._have_sherpa),
                                 (transcribe_diarize, "_download_verified", _no_download)):
            self.patch(obj, name, value)   # ワーカーの中と同じ道(このプロセスで sherpa-onnx を読む)

    def validate(self, req):
        return S.validate_voice_learn(req)

    def run_job(self, run, spec, jid):
        j = self.job(spec)
        j["id"] = jid
        run(j)
        self.assertEqual(j["state"], "done", j.get("error"))
        return j

    def test_diarize_learn_and_name(self):
        (a1, b1), (a2, b2), (a3, b3) = self.spans

        def row(i, a, b, **kw):
            return dict({"id": "s%d" % i, "start": round(a, 2), "end": round(b, 2), "text": "x", "speaker": "", "flag": "", "proofed": True}, **kw)
        segs = sorted([row(1, a1 + 0.2, b1 - 0.2), row(2, a1 + 3.0, a2 + 3.0, tags=["bgm"]), row(3, a2 + 0.2, b2 - 0.2), row(4, a3 + 0.2, b3 - 0.2),
                       row(5, a3 + 0.3, a3 + 0.8), row(6, b3 + 0.05, b3 + 0.55, text="ご視聴ありがとうございました", proofed=False),
                       row(7, a2 + 0.3, a2 + 1.3, speaker="other", noSub=True), row(8, b2 - 2.0, b2 - 0.5, proofed=False),
                       row(9, a2 + 0.5, b2 - 0.5, tags=["overlap"]), row(10, a3 + 0.5, b3 - 0.5, tags=["unclear"]), row(11, a1 + 0.5, b1 - 0.5, tags=["other"]),
                       row(12, a2 - 0.5, a2 - 0.1, noSub=True)], key=lambda g: g["start"])
        self.put_doc({"schema": "transcribe/v1", "id": TID, "title": "t", "sourcePath": self.wav, "start": 0, "end": None, "createdAt": 1, "updatedAt": 1000,
                      "speakers": [{"id": "other", "name": S.OTHER_SPK_NAME, "color": S.OTHER_SPK_COLOR, "builtin": "other"}], "segments": segs,
                      "original": [{"start": g["start"], "end": g["end"], "text": g["text"]} for g in segs], "params": {"autoFill": True}})
        # 1. 判別(人数 2・ならす)。日本語の声の行どうしが同じ話者・英語の声が別の話者・手で作った行はそのまま・声の外の定型の幻覚は捨てる
        j = self.run_job(S.run_diarize, S.validate_diarize({"tid": TID, "numSpeakers": 2, "smooth": True}), "j1")
        d = self.read()
        g = {x["id"]: x for x in d["segments"]}
        ja, en = g["s1"]["speaker"], g["s3"]["speaker"]
        self.assertEqual((j["speakers"], sorted({ja, en}), g["s4"]["speaker"], g["s11"]["speaker"], g["s10"]["speaker"]), (2, ["S1", "S2"], ja, ja, ja))
        self.assertEqual((g["s8"]["speaker"], g["s9"]["speaker"]), (en, en))
        self.assertEqual((g["s7"]["speaker"], g["s7"]["noSub"], g["s12"]["speaker"]), ("other", True, ""))
        self.assertNotIn("s6", g)
        self.assertIn(S.WEAK_FLAG, g["s5"]["flag"])                                     # 0.8 秒未満の行は話者が不確か
        self.assertTrue(any(f in g["s2"]["flag"] for f in (S.WEAK_FLAG, ys.MIXED_FLAG)), g["s2"]["flag"])   # 2 人にまたがる行
        self.assertEqual({k: d["diarization"][k] for k in ("engine", "requested", "found", "fillDropped")}, {"engine": "sherpa-onnx", "requested": 2, "found": 2, "fillDropped": 1})
        dz = S.read_diar(TID)
        run = dz["latest"]
        self.assertEqual((dz["history"], run["engine"]["name"], run["engine"]["requested"], sorted(run["labelMap"].values())), ([], "sherpa-onnx", 2, ["S1", "S2"]))
        self.assertGreaterEqual(len(run["turns"]), 3)
        self.assertEqual(run["smooth"]["on"], True)                                     # 要求の smooth が判別の記録まで届く
        self.assertEqual({k: run["rows"][k]["speaker"] for k in ("s1", "s3")}, {"s1": ja, "s3": en})
        self.assertEqual((run["voices"]["checked"], run["voices"]["speakers"][ja]["reason"]), (True, "no_voices"))
        self.assertNotIn("vec", json.dumps(dz))
        # 2. 名前を付けて声を覚える。確かめた人だけ・校正済みで音のメモ(重なり・BGM・聞き取れない)が無い 1 秒以上の行だけ(知らない印は無視・ゲーム音声などは数えない)
        for sp in d["speakers"]:
            sp["name"] = {ja: "兎田ぺこら", en: "さくらみこ"}.get(sp["id"], sp["name"])
        self.put_doc(d)
        pv = S.voice_preview(TID, "voxceleb")
        sec = round(sum(g[k]["end"] - g[k]["start"] for k in ("s1", "s4", "s11")), 1)
        self.assertEqual([(p["name"], p["speaker"], p["rows"], p["exists"]) for p in pv["people"]], [("さくらみこ", en, 1, False), ("兎田ぺこら", ja, 3, False)])
        self.assertAlmostEqual(pv["people"][1]["sec"], sec, places=0)
        self.assertEqual((pv["refused"], pv["skipped"]), ([], {"unproofed": 1, "tagged": 3, "mixed": 0, "short": 1}))
        self.assertEqual(S.voice_preview(TID, "no-such-model")["embedding"], S.DIAR_EMB_DEFAULT)
        spec = self.validate({"tid": TID, "embedding": "voxceleb", "names": ["兎田ぺこら"]})
        self.assertEqual(self.run_job(S.run_voice_learn, spec, "j2")["learned"], ["兎田ぺこら"])
        v = S.load_voices("voxceleb")
        self.assertEqual((list(v), v["兎田ぺこら"]["rows"], [x["doc"] for x in v["兎田ぺこら"]["learnedFrom"]]), (["兎田ぺこら"], 3, [TID]))
        first = list(v["兎田ぺこら"]["vec"])
        self.assertAlmostEqual(sum(x * x for x in first), 1.0, places=4)
        # 3. もう一度覚える: 既にある名前は「同じ人」の確認が要る。使った長さで重みを付けて混ぜる(同じ文書は learnedFrom に重ねない)
        with self.assertRaises(S.ApiError) as cm:
            self.validate({"tid": TID, "embedding": "voxceleb", "names": ["兎田ぺこら"]})
        self.assertEqual((cm.exception.code, cm.exception.status, cm.exception.extra), ("confirm_same", 409, {"names": ["兎田ぺこら"]}))
        self.assertEqual(S.voice_preview(TID, "voxceleb")["people"][1]["old"]["rows"], 3)
        self.run_job(S.run_voice_learn, self.validate({"tid": TID, "embedding": "voxceleb", "names": ["兎田ぺこら"], "confirmSame": ["兎田ぺこら"]}), "j3")
        v = S.load_voices("voxceleb")["兎田ぺこら"]
        self.assertEqual((v["rows"], len(v["learnedFrom"])), (6, 1))
        self.assertAlmostEqual(v["sec"], 2 * pv["people"][1]["sec"], delta=0.2)
        self.assertGreater(sum(a * b for a, b in zip(v["vec"], first)), 0.999)          # 同じ声を混ぜても向きは同じ
        self.assertEqual([(x["name"], "vec" in x) for x in S.voices_summary()["voxceleb"]], [("兎田ぺこら", False)])   # 一覧に特徴そのものは出さない
        # 4. 判別し直す: 人の話者の表は残し、覚えた声に近い仮の名前の話者だけに名前を付ける(自分で付けた名前は変えない・似ていない声には付けない)
        d = self.read()
        for sp in d["speakers"]:
            sp["name"] = {ja: "話者1", en: "みこち"}.get(sp["id"], sp["name"])
        self.put_doc(d)
        j = self.run_job(S.run_diarize, S.validate_diarize({"tid": TID, "numSpeakers": 2}), "j4")
        self.assertEqual([(n["speaker"], n["name"], n["by"]) for n in j["named"]], [(ja, "兎田ぺこら", "threshold")])
        d = self.read()
        self.assertEqual({sp["id"]: sp["name"] for sp in d["speakers"]}, {ja: "兎田ぺこら", en: "みこち", "other": S.OTHER_SPK_NAME})
        g = {x["id"]: x for x in d["segments"]}
        self.assertEqual((g["s1"]["speaker"], g["s3"]["speaker"], g["s9"]["speaker"], g["s7"]["speaker"]), (ja, en, en, "other"))   # 重なりのメモつきの行も守る
        dz = S.read_diar(TID)
        vs = dz["latest"]["voices"]
        self.assertEqual((len(dz["history"]), "smooth" in dz["latest"], vs["registered"]), (1, False, 1))   # 前の判別を残す・既定はならさない
        self.assertEqual((vs["speakers"][ja]["decided"], vs["speakers"][ja]["by"]), ("兎田ぺこら", "threshold"))
        self.assertGreaterEqual(vs["speakers"][ja]["score"], S.VOICE_MATCH)
        self.assertIn(vs["speakers"][en]["reason"], ("below_match", "already_named"))
        S.delete_voice("voxceleb", "兎田ぺこら")
        self.assertEqual(S.load_voices("voxceleb"), {})
        with self.assertRaises(S.ApiError):
            S.delete_voice("voxceleb", "兎田ぺこら")


class TestOtherVoice(VoiceDir):
    """組み込みの話者「ゲーム音声など」・行の印「字幕に出さない」(noSub)・話者ごとの字幕の見た目(sub)"""

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
            S._recognize_voices(self.job({}), TID, "x.wav", 0.0, "voxceleb")
        self.assertFalse(any(a == 8 for g in seen for a, _b in g))   # ゲーム音声などの行(8〜14 秒)の声は照らし合わせない
        self.assertEqual(self.read()["speakers"][-1]["name"], "ゲーム音声など")
        # 自動の判別: 守る行(ゲーム音声など・字幕に出さない・重なりのメモ)だけに話者があるなら「話者あり」に数えない
        d2 = self.manual_doc()
        d2["segments"][0]["speaker"] = ""
        self.assertIsNone(S._autodiar_why_not(d2))
        self.assertEqual(S._autodiar_why_not(self.manual_doc()), "has_speakers")
        # 動画の手がかりの名前は、仮の名前の話者のうち話した秒の長い人に(字幕に出さない行は数えない・組み込みには付けない)
        d3 = self.manual_doc()
        d3["speakers"][1]["name"] = "話者2"
        d3["segments"][1]["end"] = 100.0   # ゲーム音声などが長くても選ばれない
        self.put_doc(d3)
        hit = S._autodiar_name_by_context(TID, "さくらみこ")
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

    def test_speakers_sub_name_key_ignores_case_and_kana(self):
        """字幕の色の名前合わせも person_key(大文字小文字・ひらがなとカタカナ・全角半角を無視。OPT-H1 Q8)"""
        d = self.manual_doc()
        d["speakers"][0]["name"] = "Pekora"
        d["speakers"][1]["name"] = "兎田ペコラ"
        self.put_doc(d)
        r = S.speakers_sub_apply({"id": TID, "styles": {"pekora": {"color": "#111111"}, "兎田ぺこら": {"color": "#222222"}}})
        self.assertEqual(sorted(r["applied"]), ["Pekora", "兎田ペコラ"])

    def test_kept_speaker_survives_max_speakers(self):
        """判別が 20 人を見つけ、守る行の話者が 1 人いても、保存で守った話者が消えない(新しい話者は 20 − 守った人数まで。4d-2)"""
        rows = [(i * 2.0, i * 2.0 + 1.5, "", "") for i in range(22)] + [(50.0, 52.0, "S1", "", False, ["overlap"])]
        self.put_doc(doc_with_speakers([("S1", "ぺこら")], rows))
        S.apply_diarization(TID, [(i * 2.0, i * 2.0 + 1.5, i) for i in range(22)], 0.0, 0)
        d = self.read()
        ids = {s["id"] for s in d["speakers"]}
        self.assertLessEqual(len(d["speakers"]), S.MAX_SPEAKERS)
        kept = d["segments"][-1]
        self.assertIn(kept["speaker"], ids)
        self.assertEqual({s["id"]: s["name"] for s in d["speakers"]}[kept["speaker"]], "ぺこら")

    def test_pack_output_speaker_styles(self):
        base = {"fps": "30", "size": "1080x1920", "wrap": 8, "textplus": True, "render": False, "speakerColors": False}
        out = S.sanitize_pack_output(dict(base, speakerStyles={"ぺこら": {"color": "7ec2fe", "x": 1}}))
        self.assertEqual(out["speakerStyles"], {"ぺこら": {"color": "#7EC2FE"}})
        mixed = S.sanitize_pack_output(dict(base, speakerStyles={"ぺこら": {"color": "bad"}, "みこ": {"color": "#FF0000"}, "": {"color": "#000000"}}))
        self.assertEqual(mixed["speakerStyles"], {"みこ": {"color": "#FF0000"}})   # 正しくない項目だけ捨てる(① request.py と同じ。2c-5)
        self.assertNotIn("speakerStyles", S.sanitize_pack_output(dict(base, speakerStyles={"ぺこら": {"color": "bad"}})))
        many = {"人%d" % i: {"color": "#000000"} for i in range(60)}
        self.assertEqual(len(S.sanitize_pack_output(dict(base, speakerStyles=many))["speakerStyles"]), 50)
        self.assertNotIn("speakerStyles", S.sanitize_pack_output(base))

    def test_eval_redo_treats_nosub_as_touched(self):
        segs = [{"id": "s1", "start": 0.0, "end": 2.0, "text": "a", "speaker": "", "flag": ""}, {"id": "s2", "start": 2.0, "end": 4.0, "text": "b", "speaker": "", "flag": ""}]
        d = {"evalSet": True, "model": "small", "segments": [dict(g) for g in segs], "original": [dict(g) for g in segs], "updatedAt": 1, "speakers": []}
        self.assertIsNone(S.eb_redo_why(TID, d, now=10 ** 13, media=False))   # 前提: 手つかず
        d["segments"][1]["noSub"] = True
        self.assertEqual(S.eb_redo_why(TID, d, now=10 ** 13, media=False), "noSub")
        self.assertIn("noSub", S.EB_REDO_TOUCHED)


class TestExclusive(StoreDir):
    """同じ文書に同時に入れない組み合わせ(ed_jobs.EXCLUSIVE)は、入口の検査(validate_*)と登録(add_job)で同じ組を断る
    (声を覚える・判別・再認識で、入口と登録の組がずれない)"""

    def active(self, kind):
        return mock.patch.dict(S._jobs, {"jx": {"id": "jx", "kind": kind, "state": "queued", "tid": TID, "spec": {"tid": TID}}})

    def busy(self, fn):
        with self.assertRaises(S.ApiError) as cm:
            fn()
        self.assertEqual((cm.exception.status, cm.exception.code), (409, "busy"))

    def test_add_job_refuses_what_validate_refuses(self):
        # 声を覚える: 入口は再認識の最中を断る。登録(add_job)も同じ組で断る
        with self.active("retranscribe"):
            self.busy(lambda: S.add_job({"tid": TID, "title": "t"}, "voice-learn"))
        self.assertNotIn("voice-learn", [j.get("kind") for j in S._jobs.values() if j["spec"].get("tid") == TID])

    def test_validate_refuses_what_add_job_refuses(self):
        self.put_doc(doc_with_speakers([("S1", "兎田ぺこら")], [(0, 5, "S1", ""), (6, 12, "S1", "")], proofed=True))
        with mock.patch.object(S, "check_source", lambda p: p):
            with self.active("voice-learn"):
                self.busy(lambda: S.validate_diarize({"tid": TID}))
            with self.active("diarize"):
                self.busy(lambda: S.validate_voice_learn({"tid": TID, "names": ["兎田ぺこら"]}))

    def test_table_is_symmetric(self):
        """a が b を断るなら b も a を断る(表の全組)。再認識も声を覚えるの最中は断る(声を覚える途中で行の時刻が変わると、
        覚える区間がずれる)。サムネの案 thumb は文書を読むだけなので同じ種類どうしだけ(ほかと同時でよい)"""
        for a, others in S.EXCLUSIVE.items():
            for b in others:
                self.assertIn(b, S.EXCLUSIVE, (a, b))
                self.assertIn(a, S.EXCLUSIVE[b], "%s は %s を断るが、%s は %s を断らない" % (a, b, b, a))
        self.assertEqual(set(S.EXCLUSIVE["voice-learn"]), {"diarize", "retranscribe", "voice-learn"})
        self.assertEqual(S.EXCLUSIVE["thumb"], ("thumb",))
        with self.active("voice-learn"):   # 登録(add_job)も声を覚えるの最中は断る
            self.busy(lambda: S.add_job({"tid": TID, "title": "t"}, "retranscribe"))

    def test_retranscribe_refused_while_learning_voices(self):
        self.put_doc(doc_with_speakers([("S1", "兎田ぺこら")], [(0, 5, "S1", ""), (6, 12, "S1", "")], proofed=True))
        with mock.patch.object(S, "check_source", lambda p: p), self.active("voice-learn"):
            with self.assertRaises(S.ApiError) as cm:
                S.validate_retranscribe({"tid": TID, "ids": ["s1"]})
        self.assertEqual((cm.exception.status, cm.exception.code), (409, "busy"))
        self.assertIn("声を覚える", cm.exception.message)


if __name__ == "__main__":
    unittest.main()
