"""「確かめる」の誰の声のカードのコラボ voice:collab(src/app/check/voice_collab.py)の単体テスト: 一覧の読み(形の違う物を飛ばす)・
音の無いカードは出さない・ボタン(出る人 + その他の人 + 混ざり)・予想を出さない・答えは記録だけ(実物を書かない・声を覚えない)。一時フォルダだけを使う。

実行(リポジトリ直下から): py -3.12 -m unittest tests/app/check/test_voice_collab.py -v
"""
import json
import os
import sys
import types
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _checkkit as kit  # noqa: E402

from app.check import lineup, sources, voice_collab as VC  # noqa: E402
from human.check import apply, voice as voice_mod  # noqa: E402


class State:
    def __init__(self, answers=()):
        self.answers = list(answers)

    def effective(self):
        return self.answers


def card(key, video, people):
    return {"key": key, "video": video, "title": "コラボ", "sec": 2.0, "people": people}


class VoiceCollabTest(unittest.TestCase):
    def setUp(self):
        self.app = kit.tempdir(self, "ytt-check-collab-")
        os.makedirs(os.path.join(self.app, "check", VC.DIR_NAME))

    def write(self, cards):
        with open(os.path.join(self.app, "check", VC.NAME), "w", encoding="utf-8") as f:
            json.dump({"cards": cards}, f, ensure_ascii=False)
        for c in cards:
            if VC.KEY_RE.match(str(c.get("key") or "")):
                open(os.path.join(self.app, "check", VC.DIR_NAME, c["key"] + ".wav"), "wb").close()

    def view(self):
        return sources.View(types.SimpleNamespace(root=None, env=None, app_dir=self.app), State())

    def test_cards_and_buttons(self):
        self.write([card("c1r01", "AAAAAAAAAAA", ["桃鈴ねね", "雪花ラミィ"]), card("c2r01", "BBBBBBBBBBB", ["白上フブキ", "さくらみこ", "大空スバル", "大神ミオ"]),
                    {"key": "BAD KEY", "video": "CCCCCCCCCCC", "people": ["a"]}, card("c3r01", "DDDDDDDDDDD", [])])
        got = {c["id"]: c for c in VC.voice_collab(self.view())}
        self.assertEqual(set(got), {"voice:collab:AAAAAAAAAAA#c1r01", "voice:collab:BBBBBBBBBBB#c2r01"})
        c = got["voice:collab:BBBBBBBBBBB#c2r01"]
        self.assertEqual(lineup.parse_id(c["id"])[:2], ("voice", "collab"))
        self.assertIsNone(c["guess"])   # 予想は出さない
        self.assertEqual([o["id"] for o in c["options"]], ["name:白上フブキ", "name:さくらみこ", "name:大空スバル", "name:大神ミオ", "name:その他の人", "mixed"])
        self.assertEqual(c["buttons"], 5)
        self.assertFalse(c["learn"])
        self.assertEqual(c["media"]["url"], "api/check/voicecollab?key=c2r01")
        self.assertTrue(VC.clip_path(self.app, "c1r01"))
        self.assertIsNone(VC.clip_path(self.app, "../x"))

    def test_no_clip_no_card(self):
        self.write([card("c1r01", "AAAAAAAAAAA", ["桃鈴ねね"])])
        os.remove(os.path.join(self.app, "check", VC.DIR_NAME, "c1r01.wav"))
        self.assertEqual(VC.voice_collab(self.view()), [])

    def test_apply_records_only_never_learns(self):
        self.assertTrue(apply._registered("voice", "collab"))
        self.assertNotIn("collab", voice_mod.SOURCES)   # 声の覚え直しの材料(_pending)に入らない
        ap = apply._REG[("voice", "collab")]
        c = {"target": {"collab": "c1r01", "videoId": "AAAAAAAAAAA"}}
        self.assertEqual(ap.apply(None, c, ap.check({"choice": "name:桃鈴ねね"})), {"collab": "c1r01", "video": "AAAAAAAAAAA"})
        self.assertEqual(ap.revert(None, {"applied": {"collab": "c1r01"}}), {"collab": "c1r01"})


if __name__ == "__main__":
    unittest.main()
