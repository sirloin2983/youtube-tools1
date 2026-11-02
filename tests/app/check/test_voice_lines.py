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
        got = VL.voice_lines(self.view())
        self.assertEqual([c["id"] for c in got], ["lines:seg:AAAAAAAAAAA#a1"])
        c = got[0]
        self.assertEqual(lineup.parse_id(c["id"])[:2], ("lines", "seg"))
        self.assertEqual([(r["id"], r["guess"], r["score"]) for r in c["rows"]], [("r0", "大空スバル", 0.81), ("r1", None, None), ("r2", "尾丸ポルカ", 0.5)])
        self.assertEqual(c["rows"][0]["second"], {"name": "白上フブキ", "score": 0.6})
        self.assertEqual(c["rows"][2]["end"], 48.0)   # かけらの末に切り詰める
        self.assertEqual(c["people"], ["大空スバル", "白上フブキ", "宝鐘マリン", "尾丸ポルカ"])   # 配信者・声を覚えた全員・予想の名前
        self.assertEqual(c["otherPerson"], "ほかの人")
        self.assertEqual(c["media"]["url"], "api/check/voicelines?key=a1")
        self.assertTrue(c["measureOnly"])
        self.assertIsNone(VL.clip_path(self.app, "../x"))
        os.remove(os.path.join(self.app, "check", VL.DIR_NAME, "a1.wav"))
        self.assertEqual(VL.voice_lines(self.view()), [])   # 音の無いカードは出さない

    def test_in_lanes_and_voice_group(self):
        self.assertIn("lines", lineup.NORMAL_KINDS)
        self.assertIn("lines", deck.KIND_GROUP["voice"])   # 画面の「話者」で出る

    def test_answer_records_all_rows_never_learns(self):
        self.assertTrue(apply._registered("lines", "seg"))
        self.assertNotIn("seg", voice_mod.SOURCES)   # 声の覚え直しの材料に入らない
        ap = apply._REG[("lines", "seg")]
        self.assertGreater(ap.max_bytes, apply.MAX_ANSWER_BYTES)   # 40 行の直しが入る
        c = {"target": {"lines": "a1", "videoId": "AAAAAAAAAAA"}, "who": "大空スバル", "at": 1200.0, "part": "mid2",
             "rows": [{"id": "r0", "start": 0.4, "end": 3.1, "text": "はいどうも", "guess": "大空スバル", "score": 0.81},
                      {"id": "r1", "start": 3.4, "end": 6.0, "text": "こんばんきつね", "guess": "白上フブキ", "score": 0.7},
                      {"id": "r2", "start": 6.2, "end": 9.0, "text": "うわっ", "guess": "尾丸ポルカ", "score": 0.4}]}
        self.assertEqual(ap.apply(None, c, ap.check({}))["rows"][1], {"id": "r1", "start": 3.4, "end": 6.0, "guess": "白上フブキ", "guessScore": 0.7,
                                                                   "speaker": "白上フブキ", "text0": "こんばんきつね", "text": "こんばんきつね"})   # 変えない = 予想どおり・文字どおり
        a = ap.apply(None, c, ap.check({"rows": [{"id": "r1", "speaker": "尾丸ポルカ", "text": " こんばんきーつね "}, {"id": "r2", "none": True}, {"id": "zz", "speaker": "x"}]}))
        self.assertEqual((a["lines"], a["video"], a["who"], a["part"]), ("a1", "AAAAAAAAAAA", "大空スバル", "mid2"))
        self.assertEqual([(r["speaker"], r["text"]) for r in a["rows"]], [("大空スバル", "はいどうも"), ("尾丸ポルカ", "こんばんきーつね"), (None, "うわっ")])
        self.assertTrue(a["rows"][2]["none"])
        nog = dict(c, rows=[dict(c["rows"][0], guess=None, score=None)])
        with self.assertRaises(apply.Refused):
            ap.apply(None, nog, ap.check({}))   # 予想の無い行は話者を選ばないと答えられない
        self.assertEqual(ap.apply(None, nog, ap.check({"rows": [{"id": "r0", "speaker": "ほかの人"}]}))["rows"][0]["speaker"], "ほかの人")
        for bad in ({"rows": [{"id": "r0", "speaker": "a", "none": True}]}, {"rows": [{"id": "r0", "none": False}]}, {"rows": [{"id": "r0"}, {"id": "r0"}]},
                    {"rows": [{"id": "r 0"}]}, {"rows": [{"id": "r0", "text": "x" * 201}]}, {"rows": "x"}, {"names": ["a"]}, "x"):
            with self.assertRaises(ValueError):
                ap.check(bad)


if __name__ == "__main__":
    unittest.main()
