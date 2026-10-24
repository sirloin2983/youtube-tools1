"""「確かめる」の誰の声のカード(src/human/check/voice.py)の単体テスト: 答えの形・選択肢と予想・文書の行への反映(commit why check:voice)と Z・
評価用と処理中を断る・層と食い違わない・声の覚え直し(1 人 30 秒・rows= で行を明示・learnedFrom で 2 度覚えない・待っている覚え直しを数えない)・
human/proof/speakers.voice_learn_plan の rows=。一時フォルダの作業データだけを使う。

実行(リポジトリ直下から): py -3.12 -m unittest tests/human/check/test_voice.py -v
"""
import os
import sys
import unittest
from unittest import mock

os.environ.setdefault("YTT_DATA_DIR", "inplace")
ROOT = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))), "src")   # tests -> check -> human -> src
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from flow import diar as _diar, jobs as _heavy  # noqa: E402
from human.check import answerlog, apply, voice  # noqa: E402
from human.proof import layers, speakers, store  # noqa: E402
from ytt import schemas, txbase, workdata  # noqa: E402
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "human"))   # tests/human/(_workdata)
from _workdata import temporary_workdata  # noqa: E402
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))   # tests/(testkit)
import testkit  # noqa: E402

TID = "0123456789ab"
EMB = _diar.learn_embedding(_diar.default_embedding())   # カードで覚える声の帳のモデル(声の名前付け = VOICE_EMB。10-22)


def row(rid, a, b, sp, flag="", **kw):
    return dict({"id": rid, "start": a, "end": b, "text": "行" + rid, "speaker": sp, "flag": flag}, **kw)


def make_doc(**kw):
    d = {"schema": "transcribe/v1", "id": TID, "title": "テストの配信", "updatedAt": 1000, "diarization": {"embedding": EMB},
         "speakers": [{"id": "S1", "name": "ぺこら", "color": "#2f62d6"}, {"id": "S2", "name": "話者2", "color": "#d9534f"}],
         "segments": [row("s1", 0.0, 12.0, "S2", txbase.WEAK_FLAG), row("s2", 12.0, 24.0, "S2"), row("s3", 24.0, 24.5, "S1"),
                      row("s4", 30.0, 50.0, "S1"), row("s5", 50.0, 62.0, "S2", tags=["bgm"])]}
    d.update(kw)
    return d


def card(rid, guess=None):
    return {"id": "voice:diar:%s#%s" % (TID, rid), "kind": "voice", "source": "diar", "case": {"id": "", "title": "t"},
            "target": {"docId": TID, "row": rid, "videoId": None}, "guess": guess}


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = temporary_workdata(self, "check-voice-")
        p = mock.patch.object(_diar, "VOICES_DIR", os.path.join(self.tmp, "voices"))
        p.start()
        self.addCleanup(p.stop)
        self.app = os.path.join(self.tmp, "app")
        self.ctx = apply.Context(self.app)
        self.put(make_doc())

    def put(self, doc):
        store.commit(TID, doc, why="whole")

    def doc(self):
        return store.read_transcript(TID)

    def seg(self, rid):
        return next(g for g in self.doc()["segments"] if g["id"] == rid)

    def answer(self, rid, ans, guess=None):
        return apply.answer(self.ctx, card(rid, guess), {"answer": ans})

    def refused(self, rid, ans, error):
        with self.assertRaises(apply.Refused) as cm:
            self.answer(rid, ans)
        self.assertEqual(cm.exception.error, error)


class AnswerFormTest(unittest.TestCase):
    def test_check_answer(self):
        self.assertEqual(voice._check_answer({"choice": "S1"}), {"choice": "S1"})
        self.assertEqual(voice._check_answer({"choice": "name:みこ"}), {"name": "みこ"})
        self.assertEqual(voice._check_answer({"name": " みこ "}), {"name": "みこ"})
        self.assertEqual(voice._check_answer({"choice": "name:みこ", "bgm": True}), {"name": "みこ", "bgm": True})
        for bad in ("S1", {"choice": "S1", "x": 1}, {"choice": "a b"}, {"name": ""}, {"name": "x" * 31}, {"name": "a\nb"}, {}, {"choice": 3},
                    {"choice": "S1", "bgm": 1}, {"bgm": True}):
            with self.assertRaises(ValueError, msg=repr(bad)):
                voice._check_answer(bad)

    def test_registered(self):
        self.assertTrue(apply._registered("voice", "diar"))

    def test_options_and_guess(self):
        doc = make_doc()
        doc["speakers"].append({"id": "other", "name": "ゲーム音声など", "builtin": "other"})
        reg = {"みこ": {"vec": [1.0], "updatedAt": 5}, "ぺこら": {"vec": [1.0], "updatedAt": 9}, "本人": {"vec": [1.0]}, "話者3": {"vec": [1.0]}}
        opts = voice.options_for(doc, reg)
        self.assertEqual([o["id"] for o in opts], ["S1", "S2", "name:みこ", "other", "mixed"])   # 一般的な名前・仮の名前・文書にいる人は登録簿から出さない
        self.assertEqual([o.get("voice") for o in opts[:3]], [True, False, True])
        self.assertEqual(voice.guess_for(doc, "S1", {}, opts), {"id": "S1", "name": "ぺこら"})
        self.assertEqual(voice.guess_for(doc, "S2", {"top": "みこ"}, opts), {"id": "name:みこ", "name": "みこ"})   # 仮の名前の話者は照合のいちばん近い声
        self.assertEqual(voice.guess_for(doc, "S2", {"top": "だれか"}, opts), {"id": "S2", "name": "話者2"})
        self.assertIsNone(voice.guess_for(doc, "", {}, opts))

    def test_buttons_and_people(self):
        """名前のボタンは見立てに近い順に 3 人 + その他 + 混ざり・ほかの人は people(文書の話者 → 登録簿 → 名簿。同じ人は 1 つ・仮の名前は名簿から入れない)"""
        named = [{"id": "S%d" % i, "name": "人%d" % i} for i in range(1, 6)]
        opts = named + [{"id": "other", "name": "その他"}, {"id": "mixed", "name": "混ざり"}]
        self.assertEqual([o["id"] for o in voice.buttons(opts, ["S4", None, "S2"])], ["S4", "S2", "S1", "other", "mixed"])
        doc = make_doc()
        doc["speakers"].append({"id": "other", "name": "ゲーム音声など", "builtin": "other"})
        got = voice.people_for(doc, {"みこ": {}}, ["ぺこら", "ミコ", "すいせい", "話者3", ""])
        self.assertEqual(got, [{"id": "S1", "name": "ぺこら"}, {"id": "S2", "name": "話者2"}, {"id": "name:みこ", "name": "みこ"}, {"id": "name:すいせい", "name": "すいせい"}])


class ApplyTest(Base):
    def test_name_choice(self):
        before = self.doc()["updatedAt"]
        got = self.answer("s1", {"choice": "S1"}, guess={"id": "S2", "name": "話者2"})
        g = self.seg("s1")
        self.assertEqual((g["speaker"], g["flag"]), ("S1", ""))   # 話者の印(話者が不確か)は外れる
        self.assertNotIn("proofed", g)                          # カードの行は校正済みにしない
        self.assertGreater(self.doc()["updatedAt"], before)
        self.assertEqual(got["applied"]["learn"], {"name": "ぺこら", "sec": 12.0, "emb": EMB})
        self.assertIn("check:voice", store.HUMAN_WHYS)
        row = answerlog.state(self.app).answers[got["answer"]]
        self.assertEqual((row["guess"], row["answer"]), ({"id": "S2", "name": "話者2"}, {"choice": "S1"}))   # 答える前の予想と答え(おまけの記録)

    def test_mixed_and_other(self):
        got = self.answer("s2", {"choice": "mixed"})
        g = self.seg("s2")
        self.assertEqual((g["speaker"], g["flag"], g["tags"]), ("S2", txbase.MIXED_FLAG, ["overlap"]))
        self.assertNotIn("learn", got["applied"])
        got = self.answer("s4", {"choice": "other"})
        g, d = self.seg("s4"), self.doc()
        self.assertEqual((g["speaker"], g.get("noSub")), ("other", True))   # その他 = 組み込みの「ゲーム音声など」+ 字幕に出さない
        self.assertTrue(any(schemas.other_speaker(s) for s in d["speakers"]))
        self.assertEqual(got["applied"]["added"], "other")
        self.assertNotIn("learn", got["applied"])
        apply.undo(self.ctx, got["answer"])
        g, d = self.seg("s4"), self.doc()
        self.assertEqual((g["speaker"], g.get("noSub")), ("S1", None))
        self.assertFalse(any(schemas.other_speaker(s) for s in d["speakers"]))   # 足した話者は誰も使っていなければ外す

    def test_new_name_and_undo(self):
        got = self.answer("s2", {"name": "みこ"})
        d = self.doc()
        sp = next(s for s in d["speakers"] if s["name"] == "みこ")
        self.assertEqual((sp["id"], self.seg("s2")["speaker"], got["applied"]["added"]), ("S3", "S3", "S3"))
        self.assertEqual(got["applied"]["learn"]["name"], "みこ")
        got2 = self.answer("s1", {"name": "みこ"})                       # 同じ名前はもういる人に
        self.assertEqual((self.seg("s1")["speaker"], got2["applied"]["added"]), ("S3", None))
        apply.undo(self.ctx, got["answer"])
        self.assertEqual(self.seg("s2")["speaker"], "S2")
        self.assertTrue(any(s["name"] == "みこ" for s in self.doc()["speakers"]))   # s1 がまだ使っている
        with self.assertRaises(apply.Refused) as cm:
            apply.undo(self.ctx, got["answer"])
        self.assertEqual(cm.exception.error, "undone")

    def test_undo_refused_after_edit(self):
        got = self.answer("s1", {"choice": "S1"})
        d = self.doc()
        d["segments"][0]["speaker"] = "S2"                               # 編集の画面で直した
        store.commit(TID, d, why="save")
        with self.assertRaises(apply.Refused) as cm:
            apply.undo(self.ctx, got["answer"])
        self.assertEqual(cm.exception.error, "changed")

    def test_refuse(self):
        self.refused("s1", {"choice": "S9"}, "gone")
        self.refused("zz", {"choice": "S1"}, "no_row")
        with mock.patch.object(_heavy, "doc_busy", return_value=True):
            self.refused("s1", {"choice": "S1"}, "busy")
        self.put(make_doc(evalSet=True))
        self.refused("s1", {"choice": "S1"}, "eval")
        self.assertEqual(answerlog.state(self.app).order, [])           # 断った答えは記録しない

    def test_layers_match(self):
        """人の層の話者の表と行の話者が文書と同じ"""
        self.answer("s2", {"name": "みこ"})
        self.answer("s4", {"choice": "other"})
        d = self.doc()
        mach = testkit.read_json(os.path.join(workdata.TX_DIR, TID + schemas.MACH_SUFFIX))
        hum = testkit.read_json(os.path.join(workdata.TX_DIR, TID + schemas.HUM_SUFFIX))
        out = layers.compose(mach, hum, layers.split_meta(d))
        self.assertEqual(out["speakers"], d["speakers"])
        self.assertEqual([(g["id"], g.get("speaker"), g.get("noSub")) for g in out["segments"]], [(g["id"], g.get("speaker"), g.get("noSub")) for g in d["segments"]])


class PrimaryLayersTest(Base):
    def test_primary_roundtrip(self):
        """層が正: 答えも Z も組み立てた文書に出る"""
        got = self.answer("s2", {"name": "みこ"})
        d = self.doc()
        self.assertEqual(self.seg("s2")["speaker"], "S3")
        self.assertTrue(any(s["name"] == "みこ" for s in d["speakers"]))
        apply.undo(self.ctx, got["answer"])
        self.assertEqual(self.seg("s2")["speaker"], "S2")
        self.assertFalse(any(s["name"] == "みこ" for s in self.doc()["speakers"]))


class RelearnTest(Base):
    def setUp(self):
        super().setUp()
        self.jobs = []

        def add_job(spec, kind):
            self.jobs.append((kind, spec))
            return {"id": "job%d" % len(self.jobs)}
        for p in (mock.patch.dict(_heavy.JOB_RUNNERS, {"voice-learn": lambda job: None}), mock.patch.object(_diar, "models_ready", return_value=True),
                  mock.patch.object(voice._tools, "check_source", return_value="x.mp4"), mock.patch.object(_heavy, "add_job", side_effect=add_job)):
            p.start()
            self.addCleanup(p.stop)

    def test_learn_after_30_sec(self):
        self.answer("s1", {"choice": "S1"})                              # ぺこら 12 秒
        self.answer("s3", {"choice": "S1"})                              # 1 秒未満 = 材料にしない
        self.answer("s5", {"choice": "S1"})                              # BGM のメモ = 材料にしない
        self.assertEqual(self.jobs, [])
        got = self.answer("s4", {"choice": "S1"})                         # + 20 秒 = 32 秒 ≥ 30
        self.assertEqual(len(self.jobs), 1)
        kind, spec = self.jobs[0]
        self.assertEqual((kind, spec["tid"], spec["names"], spec["rows"], spec["by"], spec["confirmSame"], spec["embedding"]),
                         ("voice-learn", TID, ["ぺこら"], ["s1", "s4"], "check", ["ぺこら"], EMB))
        self.assertEqual(got["applied"]["relearn"][0]["job"], "job1")
        self.assertNotIn("proofed", self.seg("s4"))
        # 覚えた(登録簿の learnedFrom に行を控えた)= もう材料に数えない
        with _diar.voices_edit(EMB) as v:
            v["ぺこら"] = _diar.merge_voice(None, [1.0, 0.0], 2, 32.0, TID, by="check", row_ids=["s1", "s4"])
        self.assertEqual(voice._pending(self.ctx), {})

    def test_undo_and_threshold_and_inflight(self):
        a = self.answer("s1", {"choice": "S1"})
        apply.undo(self.ctx, a["answer"])                                # Z で戻した = 材料から外れる
        self.answer("s4", {"choice": "S1"})                              # 20 秒だけ
        self.assertEqual(self.jobs, [])
        self.assertEqual(voice._pending(self.ctx), {(EMB, "ぺこら"): {TID: {"s4": 20.0}}})
        with mock.patch.object(voice._settings, "load_settings", return_value={"check": {"voiceRelearnSec": 10}}):
            self.assertEqual(voice._relearn_sec(), 10.0)
            with mock.patch.dict(_heavy._jobs, {"j": {"kind": "voice-learn", "state": "running", "spec": {"by": "check", "tid": TID, "rows": ["s4"]}}}):
                self.assertEqual(voice._maybe_relearn(self.ctx), [])          # 待っている・動いている覚え直しの行は数えない
            got = voice._maybe_relearn(self.ctx)
        self.assertEqual((got[0]["names"], self.jobs[0][1]["rows"]), (["ぺこら"], ["s4"]))
        with mock.patch.object(voice._settings, "load_settings", return_value={"check": {"voiceRelearnSec": 1}}):
            self.assertEqual(voice._relearn_sec(), voice.RELEARN_SEC_DEFAULT)   # 範囲の外は既定

    def test_bgm_answer_and_undo(self):
        """ゲーム音・BGM が大きい: 話者はその人・音のメモ bgm・覚える材料にしない。Z で話者・音のメモが戻り、材料にも数えない"""
        got = self.answer("s2", {"choice": "S1", "bgm": True})
        g = self.seg("s2")
        self.assertEqual((g["speaker"], g["tags"]), ("S1", ["bgm"]))
        self.assertNotIn("learn", got["applied"])
        self.answer("s4", {"choice": "S1"})                              # 20 秒だけ(s2 の 12 秒は数えない = 30 秒に届かない)
        self.assertEqual((self.jobs, voice._pending(self.ctx)), ([], {(EMB, "ぺこら"): {TID: {"s4": 20.0}}}))
        apply.undo(self.ctx, got["answer"])
        g = self.seg("s2")
        self.assertEqual((g["speaker"], g.get("tags")), ("S2", None))

    def test_failed_relearn_is_not_repeated(self):
        """失敗した覚え直しと同じ行だけなら、答えるたびに足し直さない(材料が増えたらまた試す)"""
        with mock.patch.dict(_heavy._jobs, {"j": {"kind": "voice-learn", "state": "error", "spec": {"by": "check", "tid": TID, "rows": ["s1", "s4"]}}}):
            self.answer("s1", {"choice": "S1"})
            got = self.answer("s4", {"choice": "S1"})                     # 32 秒 ≥ 30 だが前に失敗した行と同じ
            self.assertEqual(self.jobs, [])
            self.assertIn("skipped", got["applied"]["relearn"][0])
            self.answer("s2", {"choice": "S1"})                          # 材料が増えた = また試す
        self.assertEqual(self.jobs[0][1]["rows"], ["s1", "s2", "s4"])

    def test_name_rules(self):
        self.answer("s4", {"choice": "S2"})                              # 「話者2」= 仮の名前は覚えない
        self.assertEqual(voice._pending(self.ctx), {})
        # 名前は ytt.textutil.person_key で比べる(カタカナ・全角半角・空白の違いは同じ人)
        got = self.answer("s2", {"name": "ペコラ"})
        self.assertEqual((self.seg("s2")["speaker"], got["applied"]["added"]), ("S1", None))

    def test_not_ready(self):
        with mock.patch.object(_diar, "models_ready", return_value=False):
            self.answer("s4", {"choice": "S1"})
            self.answer("s1", {"choice": "S1"})
        self.assertEqual(self.jobs, [])                                  # 部品が無い = 材料は残す
        self.assertEqual(sum(voice._pending(self.ctx)[(EMB, "ぺこら")][TID].values()), 32.0)


class LearnPlanRowsTest(unittest.TestCase):
    def test_rows_override_proofed(self):
        doc = make_doc()
        doc["segments"][3]["proofed"] = True
        plan = speakers.voice_learn_plan(doc)
        self.assertEqual(plan["rowIds"], {"ぺこら": ["s4"]})
        plan = speakers.voice_learn_plan(doc, rows=["s1", "s5"])            # s1 の話者は「話者2」(仮)= 覚えない・s5 は BGM
        self.assertEqual(plan["groups"], {})
        doc["segments"][0]["speaker"] = "S1"
        plan = speakers.voice_learn_plan(doc, rows=["s1"])                   # 校正済みでなくても指定の行は使う・指定に無い s4 は使わない
        self.assertEqual((plan["rowIds"], plan["groups"]["ぺこら"][1]), ({"ぺこら": ["s1"]}, 12.0))


if __name__ == "__main__":
    unittest.main()
