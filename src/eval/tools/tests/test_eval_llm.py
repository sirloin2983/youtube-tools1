"""dev/eval_llm.py(LLM の後処理 P18 を先に測る道具)のテスト。リポジトリ直下で:

    py -3.10 -m unittest dev/tests/test_eval_llm.py

LLM・llama-server・作業データは使わない(問い合わせは偽の関数)。選ぶ・答えを読む・検査・当てる・当たりの判定だけを確かめる。
"""
import json
import os
import sys
import unittest

os.environ.setdefault("YTT_DATA_DIR", "inplace")
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # dev/ (道具の置き場所)
sys.path.insert(0, HERE)
import eval_llm as L  # noqa: E402

MEMBERS = [
    {"name": "雪花ラミィ", "aliases": ["ラミィ", "ラミィちゃん"], "common": []},
    {"name": "常闇トワ", "aliases": ["トワ", "トワ様"], "common": ["トワ"], "misrecognitions": [{"wrong": "トーイ", "right": "トワ"}]},
    {"name": "兎田ぺこら", "aliases": ["ぺこら", "ぺこーら"], "common": []},
]


def row(a, b, text):
    return {"start": a, "end": b, "text": text}


def doc(original, segments=None, title="配信_雪花ラミィ_x", speakers=None):
    return {"id": "d1", "title": title, "original": original, "segments": segments or [], "speakers": speakers or []}


class PickTest(unittest.TestCase):
    def test_members_of_doc(self):
        names = [m["name"] for m in L.doc_members(doc([], title="26-01-01_常闇トワ"), MEMBERS)]
        self.assertEqual(names, ["常闇トワ"])
        names = [m["name"] for m in L.doc_members(doc([], title="x", speakers=[{"name": "兎田ぺこら"}]), MEMBERS)]
        self.assertEqual(names, ["兎田ぺこら"])

    def test_near_name_keeps_longest_span(self):
        d = doc([row(0, 2, "生き花ラミーちゃんが好き"), row(2, 4, "ラミィちゃん来た")])
        picks = L.pick_doc(d, [], MEMBERS)
        spans = [(p["row"], p["span"]) for p in picks]
        self.assertIn((0, "ラミーちゃん"), spans)
        self.assertNotIn((0, "ラミー"), spans)   # 長い方に含まれる短い所は外す
        self.assertFalse(any(r == 1 for r, _ in spans))   # 呼び名がそのまま出ている行は選ばない

    def test_hiragana_word_is_not_near_katakana_name(self):
        mem = [{"name": "尾丸ポルカ", "aliases": ["ポルカ"], "common": []}]
        self.assertEqual(L.near_spans("言ってみるか", L.alias_targets(mem)), [])
        self.assertIn(("トルカ", "ポルカ"), L.near_spans("トルカ来た", L.alias_targets(mem)))   # 短い一部(ルカ)は pick_doc が外す

    def test_misrecognition_and_common_alias(self):
        d = doc([row(0, 2, "トーイ様こんばんは")], title="26-01-01_常闇トワ")
        picks = L.pick_doc(d, [], MEMBERS)
        self.assertEqual(picks[0]["why"], "mis")
        self.assertEqual(picks[0]["cands"], ["トワ"])

    def test_low_prob_words_skip_repeats(self):
        raw = [{"start": 0, "end": 2, "words": [[0.1, 0.5, "ーー", 0.1], [0.5, 1.0, "うわ", 0.9], [1.0, 1.5, "ゲーム", 0.2], [3.0, 3.5, "外", 0.1]]}]
        r = row(0, 2, "ーーうわゲーム")
        self.assertEqual(L.low_prob_words(r, raw), ["ゲーム"])

    def test_limit(self):
        d = doc([row(i, i + 1, "ラミーちゃん") for i in range(10)])
        self.assertEqual(len(L.pick_doc(d, [], MEMBERS, limit=3)), 3)


class ReplyTest(unittest.TestCase):
    def test_parse_reply(self):
        txt = '<think>\nうーん\n</think>\n答え: {"edits": [{"from": "ラミー", "to": "ラミィ", "confidence": 0.9}, {"from": 1}]} 以上'
        self.assertEqual(L.parse_reply(txt), [{"from": "ラミー", "to": "ラミィ", "confidence": 0.9}])
        self.assertEqual(L.parse_reply("直す所はありません"), [])
        self.assertEqual(L.parse_reply('{"edits": []}'), [])
        self.assertEqual(L.parse_reply('{"edits": [{"from": "a", "to": "b", "confidence": true}]}')[0]["confidence"], None)

    def test_messages_have_context(self):
        rows = [row(i, i + 1, "行%d" % i) for i in range(6)]
        m = L.build_messages(rows, 3, [{"row": 3, "span": "行", "why": "lowprob", "cands": []}], ["雪花ラミィ"])
        self.assertEqual(m[0]["role"], "system")
        self.assertIn("→ 行3", m[1]["content"])
        self.assertIn("行1", m[1]["content"])
        self.assertNotIn("行0", m[1]["content"])   # 前後 2 行だけ
        self.assertIn("雪花ラミィ", m[1]["content"])


class GuardTest(unittest.TestCase):
    def test_reasons(self):
        t = "生き花ラミーちゃんが好き"
        self.assertIsNone(L.guard(t, {"from": "ラミー", "to": "ラミィ", "confidence": 0.9}, ["ラミィ"]))
        self.assertEqual(L.guard(t, {"from": "無い", "to": "x", "confidence": 0.9}, []), "notInRow")
        self.assertEqual(L.guard(t, {"from": "ラミー", "to": "ラミー", "confidence": 0.9}, []), "noChange")
        self.assertEqual(L.guard(t, {"from": "ラミー", "to": "ラミィ", "confidence": 0.2}, []), "lowConfidence")
        self.assertEqual(L.guard(t, {"from": "好き", "to": "とても大好きです", "confidence": 0.9}, []), "length")
        self.assertEqual(L.guard(t, {"from": "生き花", "to": "雪花", "confidence": 0.9}, []), "farSound")
        self.assertIsNone(L.guard(t, {"from": "生き花", "to": "雪花", "confidence": 0.9}, ["雪花"]))   # 候補そのものなら音が遠くても通す

    def test_new_name_is_rejected(self):
        names = L.roster_names(MEMBERS + [{"name": "尾丸ポルカ", "aliases": ["ポルカ"], "common": []}])
        t = "とりあえず言ってみるか"
        self.assertEqual(L.guard(t, {"from": "みるか", "to": "ポルカ", "confidence": 0.8}, [], names), "newName")
        self.assertIsNone(L.guard(t, {"from": "みるか", "to": "ポルカ", "confidence": 0.8}, ["ポルカ"], names))   # 候補にある名前なら通す

    def test_cap_and_apply(self):
        rows = [row(i, i + 1, "あいう%d" % i) for i in range(10)]
        acc = [(0, {"from": "あ", "to": "か", "confidence": 0.9}), (1, {"from": "あ", "to": "か", "confidence": 0.6}),
               (2, {"from": "あ", "to": "か", "confidence": None})]
        keep, drop = L.cap_edits(acc, len(rows))   # 10 行の 15% = 1 行
        self.assertEqual([i for i, _ in keep], [0])
        self.assertEqual(len(drop), 2)
        out = L.apply_edits(rows, keep)
        self.assertEqual(out[0]["text"], "かいう0")
        self.assertEqual(rows[0]["text"], "あいう0")   # 元は書き換えない

    def test_judge_hit(self):
        d = doc([], segments=[{"start": 0, "end": 2, "text": "雪花ラミィちゃんが好き", "proofed": True}])
        r = row(0, 2, "生き花ラミーちゃんが好き")
        self.assertEqual(L.judge_hit(d, r, {"from": "ラミー", "to": "ラミィ"}), "hit")
        self.assertEqual(L.judge_hit(d, r, {"from": "好き", "to": "嫌い"}), "miss")
        self.assertEqual(L.judge_hit(d, r, {"from": "生き花", "to": "息花"}), "other")


class RunDocTest(unittest.TestCase):
    def test_run_doc_with_fake_llm(self):
        d = doc([row(0, 2, "生き花ラミーちゃんが好き"), row(2, 4, "こんばんは")] + [row(4 + i, 5 + i, "行") for i in range(8)],
                segments=[{"start": 0, "end": 2, "text": "雪花ラミィちゃんが好き", "proofed": True}])
        asked = []

        def ask(messages):
            asked.append(messages)
            return json.dumps({"edits": [{"from": "ラミーちゃん", "to": "ラミィちゃん", "confidence": 0.95}, {"from": "好き", "to": "大嫌いだよね", "confidence": 0.9}]})
        rows, rec = L.run_doc(d, [], MEMBERS, ask, 30)
        self.assertEqual(len(asked), 1)   # 疑わしい行だけ聞く
        self.assertEqual(rows[0]["text"], "生き花ラミィちゃんが好き")
        self.assertEqual(rec["applied"][0]["judge"], "hit")
        self.assertEqual(rec["rejected"], {"length": 1})
        self.assertEqual(d["original"][0]["text"], "生き花ラミーちゃんが好き")

    def test_run_doc_only(self):
        raw = [{"start": 0, "end": 2, "words": [[0.1, 0.5, "ゲーム", 0.1]]}]
        d = doc([row(0, 2, "ゲームのラミーちゃん")])
        _rows, rec = L.run_doc(d, raw, MEMBERS, None, 30, {"name"})
        self.assertEqual(rec["byWhy"], {"name": 1})

    def test_run_doc_dry(self):
        d = doc([row(0, 2, "ラミーちゃん")])
        rows, rec = L.run_doc(d, [], MEMBERS, None, 30)
        self.assertEqual(rec["picks"], 1)
        self.assertEqual(rec["applied"], [])
        self.assertEqual(rows[0]["text"], "ラミーちゃん")


if __name__ == "__main__":
    unittest.main()
