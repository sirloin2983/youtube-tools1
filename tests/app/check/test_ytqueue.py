"""YouTube の取得の列(src/app/check/ytqueue.py。10-25)。yt-dlp と API は偽物(ネットに出ない)。
両方に効く候補が先・研究と声を交互・間隔と判定の止め(翌日に伸ばす)・研究の頼みの形の検査・API の説明欄は枠を使わない・途中の物を消す。
実行(リポジトリ直下から): py -3.12 -m unittest tests/app/check/test_ytqueue.py -v
"""
import datetime
import json
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _checkkit as kit  # noqa: E402

from app.check import voicefetch as VF, ytqueue as Q  # noqa: E402
from ytt.errors import ApiError  # noqa: E402

SORA, ROBO = "UC" + "a" * 22, "UC" + "b" * 22
R = {"groups": [{"id": "gen0", "names": ["ときのそら", "ロボ子さん"]}],
     "members": [{"name": "ときのそら", "channel": SORA}, {"name": "ロボ子さん", "channel": ROBO}]}
NOON = datetime.datetime(2026, 10, 25, 12, 0).timestamp()


class YtQueueTest(unittest.TestCase):
    def setUp(self):
        self.app = kit.tempdir(self, "ytt-ytqueue-")
        self.logs, self.calls = [], []
        p = mock.patch.object(Q, "_audio", self.audio)
        p.start()
        self.addCleanup(p.stop)

    def audio(self, app_dir, rid, url, section):
        self.calls.append((rid, url, section))
        os.makedirs(Q.qdir(app_dir, "done"), exist_ok=True)
        path = Q.qdir(app_dir, "done", rid + ".m4a")
        open(path, "wb").close()
        vid = url.rsplit("=", 1)[-1][-11:]
        return path, {"id": vid, "channel_id": SORA if "SORA" in vid else ROBO, "upload_date": "20260901", "title": "【雑談】おはなし"}

    def put_cands(self, items):
        os.makedirs(Q.qdir(self.app), exist_ok=True)
        with open(Q.qdir(self.app, "candidates.json"), "w", encoding="utf-8") as f:
            json.dump(items, f, ensure_ascii=False)

    def put_req(self, rid, body):
        os.makedirs(Q.qdir(self.app, "req"), exist_ok=True)
        with open(Q.qdir(self.app, "req", rid + ".json"), "w", encoding="utf-8") as f:
            json.dump(body, f)

    def tick(self, now, counts=None):
        return Q.tick(self.app, R, dict(counts or {}), lambda: None, lambda req: "j", self.logs.append, now=now)

    def test_dual_first_then_alternate(self):
        self.put_cands([{"video": "RESONLY0001", "t": 1000, "channel": "UC" + "z" * 22, "title": "よそ", "research": 0.9},
                        {"video": "SORADUAL001", "t": 2000, "channel": SORA, "title": "【雑談】そら", "uploadDate": "20260901", "research": 0.5}])
        self.assertEqual(self.tick(NOON, {"ロボ子さん": 2}), "candidate")
        self.assertEqual(self.calls[-1][0], "cand-SORADUAL001")                 # 研究と声の両方に効く候補が先
        self.assertEqual(self.calls[-1][2], [2000 - Q.AROUND[0], 2000 + Q.AROUND[1]])   # ?t= の前後
        self.assertTrue(os.path.exists(os.path.join(self.app, "check", VF.INBOX_NAME, "SORADUAL001.json")))   # 声の材料へも回す
        with open(Q.qdir(self.app, "done", "cand-SORADUAL001.json"), encoding="utf-8") as f:
            self.assertEqual(json.load(f)["state"], "done")
        self.assertIsNone(self.tick(NOON + 1800, {"ロボ子さん": 2}))             # 1 時間に 1 本
        self.put_req("r1", {"purpose": "research", "kind": "audio", "url": "https://www.youtube.com/watch?v=REQAUDIO001", "section": [10, 20]})
        self.put_req("bad", {"purpose": "research", "kind": "audio", "url": "https://evil.example.com/x"})   # YouTube でない = 取らない
        self.assertEqual(self.tick(NOON + 3700, {"ロボ子さん": 2}), "research")   # 次は研究(頼みが候補より先)
        self.assertEqual(self.calls[-1][:2], ("r1", "https://www.youtube.com/watch?v=REQAUDIO001"))
        with mock.patch.object(VF, "tick", lambda *a, **k: "ロボ子さん") as _t:
            self.assertEqual(self.tick(NOON + 7400, {"ときのそら": 2}), "voice")  # 次は声(候補に無いロボ子さんを RSS で)
        self.assertEqual(self.tick(NOON + 11100, {"ときのそら": 2, "ロボ子さん": 2}), "candidate")   # 声が足りれば研究だけの候補
        self.assertEqual(self.calls[-1][0], "cand-RESONLY0001")
        self.assertTrue(os.path.exists(Q.qdir(self.app, "ready.json")))

    def test_research_request_for_needy_member_first(self):
        """研究の音の頼みで、配信者(hint.streamer)が材料の少ない日本の対象のメンバー = 両方に効く = 声の番でも先に取り、声にも回す"""
        from pipeline.transcribe import roster
        self.put_req("r-rev-a", {"purpose": "research", "kind": "audio", "url": "https://www.youtube.com/watch?v=OTHERVIDEO1", "hint": {"streamer": "知らない人"}})
        self.put_req("r-rev-b", {"purpose": "research", "kind": "audio", "url": "https://www.youtube.com/watch?v=SORAVIDEO01", "hint": {"streamer": "ときのそら"}})
        st = Q._state(self.app)
        Q._save(self.app, dict(st, lastPurpose="research"))   # 普通なら声の番
        with mock.patch.object(roster, "ROSTER", roster.BUNDLED):
            self.assertEqual(self.tick(NOON, {"ロボ子さん": 2}), "research")
        self.assertEqual(self.calls[-1][0], "r-rev-b")
        self.assertEqual(Q._state(self.app)["lastPurpose"], "both")
        self.assertTrue(os.path.exists(os.path.join(self.app, "check", VF.INBOX_NAME, "SORAVIDEO01.json")))

    def test_candidates_filled_by_api(self):
        """研究の候補は channel・title・uploadDate が空(streamer だけ)= 列が API で埋めて点を付ける。キーが無ければ streamer だけで"""
        from pipeline.transcribe import roster
        self.put_cands([{"video": "SORAFILL001", "t": 500, "channel": None, "title": None, "uploadDate": None, "streamer": "ときのそら", "research": 1.0}])
        got = {"items": [{"id": "SORAFILL001", "snippet": {"title": "【歌枠】うた", "channelId": SORA, "publishedAt": "2026-08-01T00:00:00Z"}}]}
        with mock.patch.object(Q._ytapi, "get", lambda path, params: got):
            self.assertEqual(Q.fill_candidates(self.app, NOON, self.logs.append), 1)
        self.assertEqual(Q._state(self.app)["meta"]["SORAFILL001"]["title"], "【歌枠】うた")
        with mock.patch.object(roster, "ROSTER", roster.BUNDLED):
            self.assertEqual(self.tick(NOON, {"ロボ子さん": 2}), "candidate")   # 研究には効く
        self.assertIn("声 0.00", self.logs[-1])                                 # 埋めた題名が歌 = 声には効かない

    def test_bot_stops_and_ladder(self):
        self.put_req("r1", {"purpose": "research", "kind": "audio", "url": "https://www.youtube.com/watch?v=REQAUDIO001"})
        with mock.patch.object(Q, "_audio", lambda *a: (None, "ERROR: Sign in to confirm you're not a bot")):
            self.assertEqual(self.tick(NOON), "research")                        # 頼みは済ませた(結果は error)
        self.assertIn("今日は止めます", self.logs[-2])
        self.assertFalse(Q.due(self.app, NOON + 7200)[0])                        # 今日は止める
        nxt = datetime.datetime(2026, 10, 26, 9, 0).timestamp()
        self.assertTrue(Q.due(self.app, nxt)[0])
        self.assertEqual(Q._state(self.app)["hours"], 1.5)                      # 翌日から間隔を伸ばす

    def test_api_info_without_slot(self):
        self.put_req("i1", {"purpose": "research", "kind": "info", "urls": ["https://www.youtube.com/watch?v=INFOVIDEO01"]})
        got = {"items": [{"id": "INFOVIDEO01", "snippet": {"title": "t", "description": "【元配信】x", "channelId": SORA, "publishedAt": "2026-09-01T00:00:00Z"}}]}
        with mock.patch.object(Q._ytapi, "get", lambda path, params: got):
            Q.tidy(self.app, NOON)
            self.assertEqual(Q._api_infos(self.app, self.logs.append, NOON), 1)
        with open(Q.qdir(self.app, "done", "i1.json"), encoding="utf-8") as f:
            d = json.load(f)
        self.assertEqual((d["via"], d["infos"][0]["upload_date"]), ("api", "20260901"))
        self.assertTrue(Q.due(self.app, NOON)[0])                                # 枠は使っていない
        self.put_req("i2", {"purpose": "research", "kind": "info", "urls": ["https://www.youtube.com/watch?v=INFOVIDEO02"]})

        def no_key(path, params):
            raise ApiError("no_key", "x", 400)
        with mock.patch.object(Q._ytapi, "get", no_key):
            self.assertEqual(Q._api_infos(self.app, self.logs.append, NOON), 0)   # キーが無い = 今日は枠の yt-dlp で
        self.assertFalse(os.path.exists(Q.qdir(self.app, "done", "i2.json")))

    def test_tidy_removes_partial(self):
        os.makedirs(Q.qdir(self.app, "done"))
        open(Q.qdir(self.app, "done", "x.m4a.part"), "wb").close()
        Q.tidy(self.app, NOON)
        self.assertEqual(os.listdir(Q.qdir(self.app, "done")), [])


if __name__ == "__main__":
    unittest.main()
