"""「確かめる」の誰の声のカードの測る分 voice:measure(src/app/check/voice_measure.py)の単体テスト: 一覧の読み(形の違う物を飛ばす)・
音の無いカードは出さない・予想(1 位・2 位)と選択肢・先に出す人・目標に届いた人は出さない・答えは記録だけ(実物を書かない)。一時フォルダだけを使う。

実行(リポジトリ直下から): py -3.12 -m unittest tests/app/check/test_voice_measure.py -v
"""
import json
import os
import sys
import types
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _checkkit as kit  # noqa: E402

from app.check import lineup, sources, voice_measure as VM  # noqa: E402
from human.check import apply  # noqa: E402


class State:
    def __init__(self, answers=()):
        self.answers = list(answers)

    def effective(self):
        return self.answers


def card(key, who, video, g1="大空スバル", g2="白上フブキ"):
    return {"key": key, "who": who, "video": video, "title": "配信", "sec": 2.5, "guess": [{"name": g1, "score": 0.8}, {"name": g2, "score": 0.7}]}


class VoiceMeasureTest(unittest.TestCase):
    def setUp(self):
        self.app = kit.tempdir(self, "ytt-check-measure-")
        os.makedirs(os.path.join(self.app, "check", VM.DIR_NAME))

    def write(self, cards, people=()):
        with open(os.path.join(self.app, "check", VM.NAME), "w", encoding="utf-8") as f:
            json.dump({"people": list(people), "cards": cards}, f, ensure_ascii=False)
        for c in cards:
            if VM.KEY_RE.match(str(c.get("key") or "")):
                open(os.path.join(self.app, "check", VM.DIR_NAME, c["key"] + ".wav"), "wb").close()

    def view(self, answers=()):
        return sources.View(types.SimpleNamespace(root=None, env=None, app_dir=self.app), State(answers))

    def test_cards_and_guess(self):
        self.write([card("s001", "大空スバル", "AAAAAAAAAAA"), card("s002", "さくらみこ", "BBBBBBBBBBB", g1="白上フブキ", g2="さくらみこ"),
                    {"key": "BAD KEY", "who": "x", "video": "CCCCCCCCCCC", "guess": [{"name": "a"}, {"name": "b"}]},
                    card("s003", "", "DDDDDDDDDDD")], people=["さくらみこ"])
        got = {c["id"]: c for c in VM.voice_measure(self.view())}
        self.assertEqual(set(got), {"voice:measure:AAAAAAAAAAA#s001", "voice:measure:BBBBBBBBBBB#s002"})
        c = got["voice:measure:BBBBBBBBBBB#s002"]
        self.assertEqual(lineup.parse_id(c["id"])[:2], ("voice", "measure"))
        self.assertEqual(c["guess"]["name"], "白上フブキ")   # 予想 = 道具の 1 位(配信者ではない)
        self.assertEqual(c["guess"]["second"]["name"], "さくらみこ")
        self.assertEqual([o["id"] for o in c["options"]][:2], ["name:白上フブキ", "name:さくらみこ"])   # 予想・配信者の順
        self.assertIn("mixed", [o["id"] for o in c["options"]])
        self.assertEqual(c["media"]["url"], "api/check/voicemeasure?key=s002")
        self.assertLess(c["_order"][:2], got["voice:measure:AAAAAAAAAAA#s001"]["_order"][:2])   # 先に出す人
        self.assertTrue(VM.clip_path(self.app, "s001"))
        self.assertIsNone(VM.clip_path(self.app, "../x"))

    def test_no_clip_no_card(self):
        self.write([card("s001", "大空スバル", "AAAAAAAAAAA")])
        os.remove(os.path.join(self.app, "check", VM.DIR_NAME, "s001.wav"))
        self.assertEqual(VM.voice_measure(self.view()), [])

    def test_reached_person_stops(self):
        self.write([card("s%03d" % i, "大空スバル", "AAAAAAAAAAA") for i in range(1, 3)])
        ans = [{"kind": "voice", "source": "measure", "answer": {"name": "大空スバル"}, "applied": {"who": "大空スバル"},
                "target": {"videoId": "V%d" % (i % 3)}} for i in range(VM.TARGET_ROWS)]
        self.assertEqual(VM.voice_measure(self.view(ans[:-1])) != [], True)   # 1 行足りない
        self.assertEqual(VM.voice_measure(self.view(ans)), [])
        bgm = [dict(a, answer={"name": "大空スバル", "bgm": True}) for a in ans]   # BGM 大の答えは数えない
        self.assertNotEqual(VM.voice_measure(self.view(bgm)), [])

    def test_apply_records_only(self):
        self.assertTrue(apply._registered("voice", "measure"))
        ap = apply._REG[("voice", "measure")]
        c = {"who": "大空スバル", "target": {"measure": "s001", "videoId": "AAAAAAAAAAA"}}
        self.assertEqual(ap.apply(None, c, ap.check({"choice": "name:大空スバル"})), {"measure": "s001", "who": "大空スバル", "video": "AAAAAAAAAAA"})
        self.assertEqual(ap.revert(None, {"applied": {"measure": "s001"}}), {"measure": "s001"})


if __name__ == "__main__":
    unittest.main()
