"""「確かめる」の行ごとの話者のカード lines:seg(声の材料のかけら・src/app/check/voice_lines.py)の単体テスト: 一覧の読み(形の違う物を飛ばす)・
音の無いカードは出さない・行ごとの予想の 1 位・候補(声を覚えた全員 + 配信者 + 予想の名前)・答えの形・記録は全部の行(予想・答えた話者・元の文字・
直した文字)で実物を書かない・声を覚えない・本文の上限。一時フォルダだけを使う。

実行(リポジトリ直下から): py -3.12 -m unittest tests/app/check/test_voice_lines.py -v
"""
import json
import os
import sys
import types
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _checkkit as kit  # noqa: E402

from app.check import deck, lineup, sources, voice_lines as VL  # noqa: E402
from human.check import apply, voice as voice_mod  # noqa: E402


class State:
    def effective(self):
        return []


def row(i, a, b, text, *guess):
    return {"id": "r%d" % i, "start": a, "end": b, "text": text, "guess": [{"name": n, "score": s} for n, s in guess]}


def card(key, video, rows, sec=48.0):
    return {"key": key, "video": video, "title": "配信", "who": "大空スバル", "at": 1200.0, "sec": sec, "part": "mid2", "rows": rows}


class VoiceLinesTest(unittest.TestCase):
    def setUp(self):
        self.app = kit.tempdir(self, "ytt-check-lines-")
        os.makedirs(os.path.join(self.app, "check", VL.DIR_NAME))

    def write(self, cards, people=()):
        with open(os.path.join(self.app, "check", VL.NAME), "w", encoding="utf-8") as f:
            json.dump({"people": list(people), "cards": cards}, f, ensure_ascii=False)
        for c in cards:
            if VL.KEY_RE.match(str(c.get("key") or "")):
                open(os.path.join(self.app, "check", VL.DIR_NAME, c["key"] + ".wav"), "wb").close()

    def view(self):
        return sources.View(types.SimpleNamespace(root=None, env=None, app_dir=self.app), State())

    def test_cards_rows_and_people(self):
        good = [row(0, 0.4, 3.1, "はいどうも", ("大空スバル", 0.81), ("白上フブキ", 0.6)), row(1, 3.4, 6.0, "こんばんきーつね"), row(2, 6.2, 48.02, "末", ("尾丸ポルカ", 0.5))]
        self.write([card("a1", "AAAAAAAAAAA", good),
                    card("a2", "BBBBBBBBBBB", [row(0, 5.0, 4.0, "逆")]),                        # 時刻が逆 = 飛ばす
                    card("a3", "CCCCCCCCCCC", [row(0, 0, 1, "x"), row(0, 1, 2, "y")]),           # id が重なる
                    card("a4", "DDDDDDDDDDD", []),                                               # 行が無い
                    card("a5", "EEEEEEEEEEE", good, sec=120),                                    # 長すぎる
                    {"key": "BAD KEY", "video": "FFFFFFFFFFF", "who": "x", "sec": 4, "rows": good}],
                   people=["白上フブキ", "宝鐘マリン"])
        with mock.patch.object(VL, "roster_names", return_value=["宝鐘マリン", "さくらみこ"]):
            got = VL.voice_lines(self.view())
        self.assertEqual([c["id"] for c in got], ["lines:seg:AAAAAAAAAAA#a1#0", "lines:seg:AAAAAAAAAAA#a1#1"])   # 6 秒ほどの一切れに分ける(11-02)
        c, c2 = got
        self.assertEqual(lineup.parse_id(c["id"])[:2], ("lines", "seg"))
        self.assertEqual([(r["id"], r["guess"], r["score"]) for r in c["rows"]], [("r0", "大空スバル", 0.81), ("r1", None, None)])
        self.assertEqual((c["media"]["start"], c["media"]["end"], c["target"]["piece"]), (0.1, 6.3, 0))   # 再生の窓 = 一切れの行 ± 余白
        self.assertEqual(c["rows"][0]["second"], {"name": "白上フブキ", "score": 0.6})
        self.assertEqual(c2["rows"][0]["end"], 48.0)   # かけらの末に切り詰める
        self.assertEqual(c2["media"]["end"], 48.0)
        self.assertEqual(c["people"], ["大空スバル", "白上フブキ", "宝鐘マリン", "さくらみこ"])   # 出る人・一切れの予想の名前・声を覚えた全員・名簿の全員
        self.assertEqual(c["rows"][1]["words"], [[ch, round(3.4 + i * 2.6 / 8, 3), round(3.4 + (i + 1) * 2.6 / 8, 3)] for i, ch in enumerate("こんばんきーつね")])
        self.assertFalse(c["rows"][1]["timed"])   # 言葉の時刻が無い = 1 字ずつ・字数の割合
        self.assertEqual(c["otherPerson"], "ほかの人")
        self.assertEqual(c["media"]["url"], "api/check/voicelines?key=a1")
        self.assertNotIn("measureOnly", c)   # 答えで声を覚える(11-02)
        self.assertIsNone(VL.clip_path(self.app, "../x"))
        os.remove(os.path.join(self.app, "check", VL.DIR_NAME, "a1.wav"))
        self.assertEqual(VL.voice_lines(self.view()), [])   # 音の無いカードは出さない

    def test_pieces(self):
        r = lambda a, b: {"start": a, "end": b}   # noqa: E731
        self.assertEqual(VL.pieces([r(0, 2), r(2, 4), r(4.5, 6), r(6, 7), r(7, 20), r(20, 21)]),
                         [[r(0, 2), r(2, 4), r(4.5, 6)], [r(6, 7)], [r(7, 20)], [r(20, 21)]])   # 長い 1 行は 1 行で一切れ・行は割らない

    def test_in_lanes_and_voice_group(self):
        self.assertIn("lines", lineup.NORMAL_KINDS)
        self.assertIn("lines", deck.KIND_GROUP["voice"])   # 画面の「話者」で出る

    @mock.patch.object(voice_mod, "_maybe_relearn", return_value=[])
    def test_answer_records_all_rows(self, _relearn):
        self.assertTrue(apply._registered("lines", "seg"))
        self.assertIn("lines", voice_mod.CLIP_KINDS)   # 声の覚え直しはかけらの道(test_voice_lines_learn)
        ap = apply._REG[("lines", "seg")]
        self.assertGreater(ap.max_bytes, apply.MAX_ANSWER_BYTES)   # 40 行の直しが入る
        c = {"target": {"lines": "a1", "piece": 2, "videoId": "AAAAAAAAAAA"}, "who": "大空スバル", "at": 1200.0, "part": "mid2",
             "rows": [{"id": "r0", "start": 0.4, "end": 3.1, "text": "はいどうも", "guess": "大空スバル", "score": 0.81},
                      {"id": "r1", "start": 3.4, "end": 6.0, "text": "こんばんきつね", "guess": "白上フブキ", "score": 0.7},
                      {"id": "r2", "start": 6.2, "end": 9.0, "text": "うわっ", "guess": "尾丸ポルカ", "score": 0.4}]}
        for r in c["rows"]:   # 画面に出すときの形(言葉。r0 だけ Haas の言葉の時刻)
            r["words"], r["timed"] = VL.words_of(dict(r, guess=[]))
        c["rows"][0]["words"], c["rows"][0]["timed"] = [["はい", 0.4, 1.2], ["どう", 1.4, 2.2], ["も", 2.2, 3.1]], True
        self.assertEqual(ap.apply(None, c, ap.check({}))["rows"][1], {"id": "r1", "from": ["r1"], "start": 3.4, "end": 6.0, "guess": "白上フブキ", "guessScore": 0.7,
                                                                   "speaker": "白上フブキ", "text0": "こんばんきつね", "text": "こんばんきつね"})   # 変えない = 予想どおり・文字どおり
        # 区切りは元のまま: 話者と文字を直す・声なし
        a = ap.apply(None, c, ap.check({"rows": [{"w": [0, 3]}, {"w": [3, 10], "speaker": "尾丸ポルカ", "text": " こんばんきーつね "}, {"w": [10, 13], "none": True}],
                                        "voiceNoRow": True}))
        self.assertEqual((a["lines"], a["piece"], a["video"], a["who"], a["part"]), ("a1", 2, "AAAAAAAAAAA", "大空スバル", "mid2"))
        self.assertEqual([(r["speaker"], r["text"]) for r in a["rows"]], [("大空スバル", "はいどうも"), ("尾丸ポルカ", "こんばんきーつね"), (None, "うわっ")])
        self.assertTrue(a["rows"][2]["none"])
        self.assertTrue(a["voiceNoRow"])
        self.assertEqual((a["cuts0"], a["cuts"]), ([0, 3, 10], [0, 3, 10]))
        # 分ける: r0 を「はい」「どうも」に(言葉の時刻 = 確か)・r1 の頭の 2 字を r0 の末へ移す(字の割合 = 時刻は仮)・2 人同時・分からない
        a = ap.apply(None, c, ap.check({"rows": [{"w": [0, 1]}, {"w": [1, 5], "both": ["大空スバル", "白上フブキ"]}, {"w": [5, 10], "unknown": True}, {"w": [10, 13]}]}))
        r0, r01, r1, r2 = a["rows"]
        self.assertEqual((r0["id"], r0["start"], r0["end"], r0["text0"], r0.get("timeGuess")), ("r0", 0.4, 1.2, "はい", None))
        self.assertEqual((r01["id"], r01["from"], r01["start"], r01["end"], r01["text0"], r01["both"], r01["speaker"]),
                         ("r0.1", ["r0", "r1"], 1.4, round(3.4 + 2 * 2.6 / 7, 3), "どうもこん", ["大空スバル", "白上フブキ"], None))
        self.assertTrue(r01["timeGuess"])   # 字の割合の時刻の行の言葉が入る
        self.assertEqual((r1["id"], r1["start"], r1["text0"], r1["unknown"], r1["guess"]), ("r1.1", round(3.4 + 2 * 2.6 / 7, 3), "ばんきつね", True, "白上フブキ"))
        self.assertEqual(a["cuts"], [0, 1, 5, 10])
        self.assertEqual([x["row"] for x in a["learn"]], ["r2"])   # 2 人同時・分からない・時刻が仮・1 秒未満(r0 = 0.8 秒)は覚えない
        for bad in ({"rows": [{"w": [0, 3]}, {"w": [4, 13]}]}, {"rows": [{"w": [0, 3]}, {"w": [3, 12]}]}):
            with self.assertRaises(apply.Refused):
                ap.apply(None, c, ap.check(bad))   # 言葉に隙間・終わりまで届かない
        nog = dict(c, rows=[dict(c["rows"][0], guess=None, score=None)])
        with self.assertRaises(apply.Refused):
            ap.apply(None, nog, ap.check({}))   # 予想の無い行は話者を選ばないと答えられない
        self.assertEqual(ap.apply(None, nog, ap.check({"rows": [{"w": [0, 3], "speaker": "ほかの人"}]}))["rows"][0]["speaker"], "ほかの人")
        for bad in ({"rows": [{"w": [0, 3], "speaker": "a", "none": True}]}, {"rows": [{"w": [0, 3], "none": False}]}, {"rows": [{"w": [3, 3]}]},
                    {"rows": [{"w": [0, 3], "both": ["a", "a"]}]}, {"rows": [{"w": [0, 3], "both": ["a"]}]}, {"rows": [{"w": [0, True]}]},
                    {"rows": [{"id": "r0"}]}, {"rows": [{"w": [0, 3], "text": "x" * 201}]}, {"rows": "x"}, {"names": ["a"]}, {"voiceNoRow": 1}, "x"):
            with self.assertRaises(ValueError):
                ap.check(bad)

    def test_words_and_card_fields(self):
        r = row(0, 1.0, 3.0, "こんばんきーつね", ("白上フブキ", 0.8))
        r["words"] = [{"w": "こんばん", "start": 1.0, "end": 1.6}, {"w": "きーつね", "start": 1.7, "end": 2.9}]
        bad = dict(row(1, 3.0, 4.0, "ab"), words=[{"w": "a", "start": 3.5, "end": 3.9}, {"w": "b", "start": 3.1, "end": 3.2}])   # 順が逆 = 字の割合
        self.write([dict(card("b1", "AAAAAAAAAAA", [r, bad]), material=True, cast=["白上フブキ", "大空スバル", 3], **{"from": "friend", "scene": "ゲーム"})])
        with mock.patch.object(VL, "roster_names", return_value=[]):
            c = VL.voice_lines(self.view())[0]
        self.assertEqual(c["rows"][0]["words"], [["こんばん", 1.0, 1.6], ["きーつね", 1.7, 2.9]])
        self.assertTrue(c["rows"][0]["timed"])
        self.assertFalse(c["rows"][1]["timed"])
        self.assertEqual((c["cast"], c["from"], c["scene"], c["people"][:2]), (["大空スバル", "白上フブキ"], "friend", "ゲーム", ["大空スバル", "白上フブキ"]))
        self.assertTrue(VL.load(self.app)[1][0]["material"])


if __name__ == "__main__":
    unittest.main()
