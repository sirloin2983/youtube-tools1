"""誰の声の材料が無いメンバーの音を YouTube から(src/app/check/voicefetch.py。10-25)。RSS と yt-dlp は偽物(ネットに出ない)。
枠の分け合い(研究と yt-slot.json)・材料のある人は取らない・雑談らしい配信を選ぶ(歌・コラボ・ショートは外す)・bot 判定でその日は止める・動かす時刻。
実行(リポジトリ直下から): py -3.12 -m unittest tests/app/check/test_voicefetch.py -v
"""
import datetime
import json
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _checkkit as kit  # noqa: E402

from app.check import voicefetch as VF, voicefill  # noqa: E402

R = {"groups": [{"id": "gen0", "names": ["ときのそら", "ロボ子さん"]}, {"id": "en_myth", "names": ["IRyS"]}, {"id": "alum", "names": ["桐生ココ"]}, {"id": "units", "names": ["ホロライブ"]}],
     "members": [{"name": "ときのそら", "channel": "UC" + "a" * 22, "region": "JP"}, {"name": "ロボ子さん", "channel": "UC" + "b" * 22, "region": "JP"}, {"name": "桐生ココ", "channel": "UC" + "c" * 22}, {"name": "IRyS", "channel": "UC" + "d" * 22, "region": "EN"}]}
RSS = """<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom" xmlns:yt="http://www.youtube.com/xml/schemas/2015">
<entry><yt:videoId>AAAAAAAAAA1</yt:videoId><title>【歌枠】うたう</title></entry>
<entry><yt:videoId>AAAAAAAAAA2</yt:videoId><title>すこしだけ #shorts</title></entry>
<entry><yt:videoId>AAAAAAAAAA3</yt:videoId><title>【コラボ】みんなで</title></entry>
<entry><yt:videoId>AAAAAAAAAA4</yt:videoId><title>【マイクラ】建築</title></entry>
<entry><yt:videoId>AAAAAAAAAA5</yt:videoId><title>【雑談】おはなし</title></entry></feed>""".encode("utf-8")
NOON = datetime.datetime(2026, 10, 25, 12, 0).timestamp()


class VoiceFetchTest(unittest.TestCase):
    def setUp(self):
        self.app = kit.tempdir(self, "ytt-voicefetch-")
        self.logs, self.jobs, self.got = [], [], []

    def fetch(self, vid, base):
        self.got.append(vid)
        p = base + ".m4a"
        open(p, "wb").close()
        return p, ""

    def tick(self, now=NOON, have=frozenset(), fetch=None):
        return VF.tick(self.app, R, set(have), lambda: None, lambda req: self.jobs.append(req) or "j", self.logs.append,
                       now=now, rss=lambda ch: RSS, fetch=fetch or self.fetch)

    def test_fetch_one_and_share_slot(self):
        self.assertEqual([n for n, _c in VF.members(R)], ["ときのそら", "ロボ子さん"])   # 卒業・ユニット・EN・ID の組は外す(10-25)
        self.assertTrue(VF.wants(self.app, R, {"ときのそら", "IRyS"}, now=NOON))              # 取りたい = 学習用データの文字起こしは休む
        self.assertFalse(VF.wants(self.app, R, {"ときのそら", "ロボ子さん", "IRyS"}, now=NOON))   # 材料の無い人がいなければ取らない
        self.assertEqual(self.tick(have={"ときのそら"}), "ロボ子さん")              # 材料のある人は取らない
        self.assertFalse(VF.wants(self.app, R, set(), now=NOON + 60))             # 取った直後は枠が埋まる = 文字起こしに戻る
        self.assertEqual(self.got, ["AAAAAAAAAA5"])                                  # 雑談の印のある物(歌・ショート・コラボは外す)
        src = self.jobs[-1]["sourcePath"]
        self.assertTrue(voicefill.in_learn_dir(src) and "ロボ子さん" in os.path.basename(src))   # 誰の声のカードだけ・見立ての名前
        self.assertIsNone(self.tick(now=NOON + 600))                                 # 30 分たっていない
        self.assertIsNone(self.tick(now=NOON + 2000))                                # 自分が続けて(研究の番)
        with open(os.path.join(self.app, "check", VF.SLOT_NAME), "w", encoding="utf-8") as f:
            json.dump({"last": NOON + 2000, "by": "research"}, f)                    # 研究が問い合わせた
        self.assertIsNone(self.tick(now=NOON + 3000))
        self.assertEqual(self.tick(now=NOON + 3900), "ときのそら")
        self.assertIsNone(self.tick(now=NOON + 3900 + 11000))                        # 全員取れた(EN・ID は取らない)
        self.assertIsNotNone(VF.slot_free(self.app, datetime.datetime(2026, 10, 26, 3, 0).timestamp()))   # 夜中も動く

    def test_extra_channels(self):
        """名簿にチャンネルが無い人は、配信者の色の名簿(friend-apps/holo-colors/members.json)の控えで引く"""
        r = dict(R, groups=R["groups"] + [{"id": "regloss", "names": ["轟はじめ"]}])
        self.assertNotIn("轟はじめ", dict(VF.members(r)))
        self.assertEqual(dict(VF.members(r, {"轟はじめ": "UC" + "e" * 22}))["轟はじめ"], "UC" + "e" * 22)
        got = VF.extra_channels(os.path.dirname(kit.ROOT))   # リポジトリの本物の控え
        self.assertTrue(got and all(VF.CHANNEL_RE.match(c) for c in got.values()))

    def test_bot_stops_the_day(self):
        got = self.tick(fetch=lambda vid, base: (None, "ERROR: Sign in to confirm you're not a bot"))
        self.assertIsNone(got)
        with open(os.path.join(self.app, "check", VF.SLOT_NAME), encoding="utf-8") as f:
            self.assertEqual(json.load(f)["stopDay"], "2026-10-25")
        self.assertEqual(VF.slot_free(self.app, NOON + 3600 * 3)[0], False)   # 同じ日は止まったまま
        self.assertEqual(VF.slot_free(self.app, NOON + 86400 + 3600 * 2)[0], True)   # 翌日は動く
        self.assertIn("今日は止めます", self.logs[-1])


if __name__ == "__main__":
    unittest.main()
