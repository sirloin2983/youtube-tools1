# -*- coding: utf-8 -*-
"""③ 校正の小物(名前の比べ方・学習の統計・名簿・覚え直しの行・再認識の単語)のテスト。serve なしで読める。

    py -3.12 -m unittest src/human/proof/tests/test_opt_h1_fixes.py -v

- 名前の比べ方は ytt.textutil.person_key 1 つ: 一般的な名前の判定
- 採否の記録の取り消しが学習の統計を減らさない・辞書の版の材料は確度「高」の組だけ
- 壊れた名簿でも 500 にならない(① roster.load の整え方)・用語の自動追加の選び方は ① と同じ
- 確かめるの覚え直しで、声に使わなかった行を「覚えた」と控えない
- 再認識の words.json の差し替えは ② flow/tx
"""
import json
import os
os.environ.setdefault("YTT_DATA_DIR", "inplace")   # 作業データ(AppData など)に触らない
import sys
import unittest
from unittest import mock

SRC = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
for _p in (os.path.join(SRC, "editor"), SRC):
    if _p not in sys.path:
        sys.path.insert(0, _p)
from human.proof import learn, speakers  # noqa: E402
from flow import tx as flowtx  # noqa: E402
from pipeline.transcribe import replace, roster  # noqa: E402
from ytt import textutil, workdata  # noqa: E402
from human.tests._workdata import temporary_workdata  # noqa: E402
from ytt.tests import testkit  # noqa: E402

TID = "0123456789ab"


class _Tmp(unittest.TestCase):
    def setUp(self):
        self.tmp = temporary_workdata(self, "opth1-")


class PersonKeyTest(unittest.TestCase):
    def test_person_key_and_generic_names(self):
        k = textutil.person_key
        self.assertEqual(k("Pekora"), k("pekora"))
        self.assertEqual(k("兎田 ぺこら"), k("兎田　ペコラ"))
        self.assertEqual(k("ＭＣ"), "mc")
        self.assertNotEqual(k("pekora"), k("ぺこら"))   # ローマ字とかなは結ばない(名簿の呼び名で結ぶ)
        for n in ("本人", "ゲスト", "ＭＣ", "Speaker 1", "スピーカー2", "すぴーかー", "話者A", "ゲーム音声など"):
            self.assertTrue(speakers.is_generic_speaker_name(n), n)
        for n in ("兎田ぺこら", "Pekora", "話者", ""):
            self.assertEqual(speakers.is_generic_speaker_name(n), n == "話者", n)
        self.assertIs(speakers._spk_name_key, textutil.person_key)   # ⑤ eval/drill が読む内部名は同じ決まり


class FeedbackTest(_Tmp):
    def test_unrecord_alt_does_not_touch_stat(self):
        """取り消す候補に出どころ(alt・yt)があれば、記録にその欄が無くても学習の統計 stat を減らさない"""
        testkit.write_json(workdata.FEEDBACK, {"stat": {"天気=>電気": {"acc": 3, "rej": 0}}, "dismissed": {}})
        item = {"seg": "s1", "wrong": "天気", "right": "電気", "tier": "alt"}
        learn.unrecord_feedback({"tid": TID, "action": "accept", "items": [item]})
        self.assertEqual(learn.load_feedback()["stat"]["天気=>電気"], {"acc": 3, "rej": 0})
        learn.record_feedback({"tid": TID, "action": "accept", "items": [item]})
        learn.unrecord_feedback({"tid": TID, "action": "accept", "items": [item]})
        fb = learn.load_feedback()
        self.assertEqual((fb["alt"], fb["stat"]["天気=>電気"]), ({"acc": 0, "rej": 0}, {"acc": 3, "rej": 0}))
        plain = dict(item, tier=None)
        learn.unrecord_feedback({"tid": TID, "action": "accept", "items": [plain]})   # 出どころの無い候補は今までどおり stat
        self.assertEqual(learn.load_feedback()["stat"]["天気=>電気"]["acc"], 2)

    def test_dict_version_only_follows_high_pairs(self):
        """辞書の版の材料は確度「高」の組だけ = 候補を 1 つ却下しても(dismissed)・中の規則が増えても変わらない"""
        rules = {("てんき", "天気"): {"pos": 3, "docs": {"a", "b"}, "pctx": [], "neg": [], "ctx": False},
                 ("ぺこ", "ペコ"): {"pos": 1, "docs": {"a"}, "pctx": [("", "")], "neg": [], "ctx": False}}
        fb0 = {"stat": {}, "dismissed": {}}
        base = learn.dict_learned_text(rules, fb0)
        self.assertEqual(json.loads(base), {"high": [["てんき", "天気"]]})
        self.assertEqual(learn.dict_learned_text(rules, {"stat": {}, "dismissed": {TID: ["s1|ぺこ=>ペコ"]}}), base)
        self.assertEqual(learn.dict_learned_text(rules, {"stat": {"ぺこ=>ペコ": {"acc": 1, "rej": 0}}, "dismissed": {}}), base)
        self.assertNotEqual(learn.dict_learned_text(rules, {"stat": {"てんき=>天気": {"acc": 0, "rej": 1}}, "dismissed": {}}), base)   # 却下で「高」から落ちたら変わる
        with mock.patch.object(learn, "learn_rules", lambda settings=None: rules), mock.patch.object(learn, "load_feedback", lambda: fb0):
            ex = learn.export_rules()
        self.assertEqual((ex["dictLearned"], [h["wrong"] for h in ex["high"]]), (base, ["てんき"]))


class RosterTest(unittest.TestCase):
    def setUp(self):
        self.tmp = testkit.tempdir(self, "opth1-roster-")
        saved = roster.ROSTER
        self.addCleanup(lambda: setattr(roster, "ROSTER", saved))

    def put(self, d):
        roster.ROSTER = os.path.join(self.tmp, "r%d.json" % len(os.listdir(self.tmp)))
        with open(roster.ROSTER, "w", encoding="utf-8-sig") as f:
            json.dump(d, f, ensure_ascii=False)

    def test_broken_groups_do_not_500(self):
        self.put({"asOf": "2026-10-01", "note": "n", "groups": ["壊れた", {"id": "g", "label": "G", "names": "兎田ぺこら"},
                                                               {"id": "h", "label": "H", "names": ["さくらみこ", 3, ""]}]})
        r = learn.load_roster()
        self.assertEqual(r, {"asOf": "2026-10-01", "note": "n", "groups": [{"id": "h", "label": "H", "names": ["さくらみこ", "3"]}]})   # 文字列の names は 1 字ずつに割らない
        self.assertEqual(r["groups"], roster.load(roster.ROSTER)["groups"])   # 認識と同じ整え方
        # 名簿が無い・未設定のとき空で返す
        roster.ROSTER = None
        self.assertEqual(learn.load_roster(), {"asOf": "", "note": "", "groups": []})
        roster.ROSTER = os.path.join(self.tmp, "無い.json")
        self.assertEqual(learn.load_roster(), {"asOf": "", "note": "", "groups": []})

    def test_glossary_pick_is_the_same_as_friend_pc(self):
        rules = {("w%d" % i, "語%02d" % i): {"pos": 10 - i, "docs": {"a"}, "pctx": [], "neg": [], "ctx": False} for i in range(8)}
        with mock.patch.object(learn, "learn_rules", lambda settings=None: rules), mock.patch.object(learn, "load_feedback", lambda: {"stat": {}, "dismissed": {}}):
            got = learn.auto_glossary(["語00"], limit=20)
            self.assertEqual(got, replace.pick_glossary(["語00"], learn.export_rules()["glossary"], 20))
        self.assertEqual(got, ["語01", "語02", "語03", "語04"])


class VoiceRowsTest(unittest.TestCase):
    def test_row_ids_are_only_the_rows_used(self):
        """1 人 50 行 9 秒ずつ: 声に使うのは上限(① voice_groups)までの行だけ = rowIds もその行だけ"""
        segs = [{"id": "s%d" % i, "start": i * 10.0, "end": i * 10.0 + 9.0, "text": "x", "speaker": "S1", "flag": "", "proofed": True} for i in range(50)]
        doc = {"speakers": [{"id": "S1", "name": "ぺこら"}], "segments": segs}
        plan = speakers.voice_learn_plan(doc)
        used = plan["groups"]["ぺこら"][0]
        self.assertLess(len(used), 50)
        self.assertEqual(len(plan["rowIds"]["ぺこら"]), len(used))
        by_id = {g["id"]: (g["start"], g["end"]) for g in segs}
        self.assertEqual(sorted(by_id[r] for r in plan["rowIds"]["ぺこら"]), sorted(used))
        plan2 = speakers.voice_learn_plan(doc, rows=[g["id"] for g in segs])   # 確かめるの声のカード(行の指定)でも同じ
        self.assertEqual(len(plan2["rowIds"]["ぺこら"]), len(plan2["groups"]["ぺこら"][0]))


class SpanWordsTest(unittest.TestCase):
    def test_replace_span_words(self):
        old = [[0.0, 1.0, "あ"], [2.0, 3.0, "い"], [4.0, 5.0, "う"], [6.0, 7.0, "え"]]
        got = {}
        with mock.patch.object(flowtx._txwords, "read_words", lambda tid: [list(w) for w in old]), \
                mock.patch.object(flowtx._txwords, "write_words", lambda tid, words, model: got.update(words=words, model=model)):
            flowtx.replace_span_words(TID, 1.5, 6.0, [(2.1, 2.9, "イ")], "m", keep_spans=[(4.0, 5.0)])
        self.assertEqual(got["words"], [[0.0, 1.0, "あ"], [4.0, 5.0, "う"], [6.0, 7.0, "え"], [2.1, 2.9, "イ"]])   # 範囲の中で守る区間の単語は残す
        self.assertEqual(got["model"], "m")
        with mock.patch.object(flowtx._txwords, "read_words", lambda tid: None), \
                mock.patch.object(flowtx._txwords, "write_words", lambda tid, words, model: got.update(words=words)):
            flowtx.replace_span_words(TID, 0, 9, [(1.0, 2.0, "x")])
        self.assertEqual(got["words"], [[1.0, 2.0, "x"]])   # 以前の単語が無い文書は新しい単語だけ


if __name__ == "__main__":
    unittest.main()
