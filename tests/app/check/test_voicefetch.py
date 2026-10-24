"""誰の声の材料が無いメンバーの音を YouTube から(src/app/check/voicefetch.py。10-25)。RSS と yt-dlp は偽物(ネットに出ない)。
枠の分け合い(研究と yt-slot.json)・材料のある人は取らない・雑談らしい配信を選ぶ(歌・コラボ・ショートは外す)・bot 判定でその日は止める・動かす時刻。
実行(リポジトリ直下から): py -3.12 -m unittest tests/app/check/test_voicefetch.py -v
"""
import datetime
import json
import os
import sys
import unittest
from unittest import mock

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
<entry><yt:videoId>AAAAAAAAAA5</yt:videoId><title>【雑談】おはなし</title><published>2026-10-20T10:00:00+00:00</published></entry></feed>""".encode("utf-8")
OLD = [{"id": "NEWNEWNEW%02d" % i, "title": "【雑談】さいきん %d" % i, "month": "2026-10"} for i in range(VF.LIST_SKIP)] + [
    {"id": "OLDOLDOLD01", "title": "【雑談】同じ月", "month": "2026-10"}, {"id": "OLDOLDOLD02", "title": "【雑談】先月", "month": "2026-09"}]
SECTION_LEN = VF.SECTION[1] - VF.SECTION[0]
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

    def tick(self, now=NOON, counts=None, fetch=None):
        return VF.tick(self.app, R, dict(counts or {}), lambda: None, lambda req: self.jobs.append(req) or "j", self.logs.append,
                       now=now, rss=lambda ch: RSS, fetch=fetch or self.fetch, lister=lambda ch: (OLD, ""))

    def test_fetch_one_and_share_slot(self):
        self.assertEqual([n for n, _c in VF.members(R)], ["ときのそら", "ロボ子さん"])   # 卒業・ユニット・EN・ID の組は外す(10-25)
        full = {"ときのそら": VF.TARGET, "ロボ子さん": VF.TARGET}
        self.assertTrue(VF.wants(self.app, R, {"ときのそら": 1}, now=NOON))             # 取りたい = 学習用データの文字起こしは休む
        self.assertFalse(VF.wants(self.app, R, full, now=NOON))                         # 全員 TARGET 本あれば取らない
        self.assertEqual(self.tick(counts={"ときのそら": 1}), "ロボ子さん")            # 配信の材料が 0 本の人が先
        self.assertFalse(VF.wants(self.app, R, {}, now=NOON + 60))                       # 取った直後は枠が埋まる = 文字起こしに戻る
        self.assertEqual(self.got, ["AAAAAAAAAA5"])                                  # 1 本目 = RSS の雑談の印のある物(歌・ショート・コラボは外す)
        src = self.jobs[-1]["sourcePath"]
        self.assertTrue(voicefill.in_learn_dir(src) and "ロボ子さん" in os.path.basename(src))   # 誰の声のカードだけ・見立ての名前
        self.assertIsNone(self.tick(now=NOON + 600))                                 # 30 分たっていない
        self.assertIsNone(self.tick(now=NOON + 2000))                                # 自分が続けて(研究の番)
        with open(os.path.join(self.app, "check", VF.SLOT_NAME), "w", encoding="utf-8") as f:
            json.dump({"last": NOON + 2000, "by": "research"}, f)                    # 研究が問い合わせた
        self.assertIsNone(self.tick(now=NOON + 3000))
        self.assertEqual(self.tick(now=NOON + 3900, counts={"ときのそら": 1}), "ときのそら")   # どちらも 1 本 = 試した数の少ない人
        self.assertEqual(self.got[-1], "OLDOLDOLD01")                                 # 2 本目 = 一覧の古い方(頭の LIST_SKIP 本は使わない)
        self.assertEqual(self.tick(now=NOON + 9500, counts={"ときのそら": 1}), "ロボ子さん")
        self.assertEqual(self.got[-1], "OLDOLDOLD02")                                 # 取った配信(2026-10)と別の月
        self.assertIsNone(self.tick(now=NOON + 15100, counts={"ときのそら": 1}))       # 全員 TARGET 本(EN・ID は取らない)
        self.assertIsNotNone(VF.slot_free(self.app, datetime.datetime(2026, 10, 26, 3, 0).timestamp()))   # 夜中も動く

    def test_extra_channels(self):
        """名簿にチャンネルが無い人は、配信者の色の名簿(friend-apps/holo-colors/members.json)の控えで引く"""
        r = dict(R, groups=R["groups"] + [{"id": "regloss", "names": ["轟はじめ"]}])
        self.assertNotIn("轟はじめ", dict(VF.members(r)))
        self.assertEqual(dict(VF.members(r, {"轟はじめ": "UC" + "e" * 22}))["轟はじめ"], "UC" + "e" * 22)
        got = VF.extra_channels(os.path.dirname(kit.ROOT))   # リポジトリの本物の控え
        self.assertTrue(got and all(VF.CHANNEL_RE.match(c) for c in got.values()))

    def test_intake_from_research(self):
        """研究が置いた元の配信の音: 日本の対象のソロだけ自分の置き場へ移して頼み、取った配信に数える。ほかは消す(10-25)"""
        box = os.path.join(self.app, "check", VF.INBOX_NAME)
        os.makedirs(box)

        def put(vid, meta, audio=True):
            if audio:
                open(os.path.join(box, vid + ".m4a"), "wb").close()
            with open(os.path.join(box, vid + ".json"), "w", encoding="utf-8") as f:
                json.dump(dict(meta, videoId=vid), f, ensure_ascii=False)
        put("RRRRRRRRRR1", {"channel": "UC" + "b" * 22, "title": "【雑談】ゆっくり", "uploadDate": "20260901"})   # ロボ子さん
        put("RRRRRRRRRR2", {"channel": "UC" + "a" * 22, "title": "【歌枠】うたう"})                         # 歌
        put("RRRRRRRRRR3", {"channel": "UC" + "d" * 22, "title": "chatting"})                                # IRyS = EN
        put("RRRRRRRRRR4", {"channel": "UC" + "a" * 22, "title": "【雑談】ロボ子さんと"})                    # 題名にほかのメンバー
        put("RRRRRRRRRR5", {"channel": "UC" + "a" * 22, "title": "まだ書いている"}, audio=False)
        from pipeline.transcribe import roster
        with mock.patch.object(roster, "ROSTER", roster.BUNDLED):   # ソロの見分けは名簿を使う
            self.assertEqual(VF.intake(self.app, R, lambda req: self.jobs.append(req) or "j", self.logs.append), 1, self.logs)
        self.assertEqual(os.listdir(box), [])                                        # 研究の置き場には残さない
        self.assertIn("ロボ子さん", os.path.basename(self.jobs[-1]["sourcePath"]))
        self.assertTrue(voicefill.in_learn_dir(self.jobs[-1]["sourcePath"]))
        self.assertEqual(self.tick(counts={"ときのそら": 0}), "ときのそら")          # 研究の分で入ったロボ子さんは後ろへ

    @unittest.skipUnless(VF._tools.find_tool("ffmpeg"), "ffmpeg が無い")
    def test_long_research_audio_is_cut(self):
        """研究の音が配信の全部(長い)なら SECTION の 4 分だけ残す。短ければ写さない(呼び手がそのまま移す)。本物の ffmpeg"""
        import subprocess
        src, dst = os.path.join(self.app, "long.m4a"), os.path.join(self.app, "cut.m4a")
        subprocess.run([VF._tools.find_tool("ffmpeg"), "-hide_banner", "-nostdin", "-y", "-v", "error", "-f", "lavfi", "-i", "anullsrc=r=16000:cl=mono",
                        "-t", "1500", "-c:a", "aac", "-b:a", "16k", src], check=True, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        self.assertTrue(VF._shorten(src, dst))
        self.assertFalse(os.path.exists(src))
        self.assertAlmostEqual(VF._tools.media_duration(dst), SECTION_LEN, delta=2)
        self.assertFalse(VF._shorten(dst, dst + ".x.m4a"))   # 4 分は短い = そのまま

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
