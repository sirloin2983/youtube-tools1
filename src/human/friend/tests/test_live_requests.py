"""友人のライブ配信の依頼と録画の結びつきの Store(src/human/friend/live_requests.py。入口の作業データの live/requests.json。2-15)のテスト。

実行(リポジトリ直下から): python -m unittest src/human/friend/tests/test_live_requests.py -v
"""
import json
import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

os.environ.setdefault("YTT_DATA_DIR", "inplace")
SRC = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))   # tests -> friend -> human -> src
if SRC not in sys.path:
    sys.path.insert(0, SRC)

from human.friend import live_requests as LR  # noqa: E402


class LiveRequestsStoreTest(unittest.TestCase):
    """友人のライブ配信の依頼と録画の結びつき(src/human/friend/live_requests.py の Store。入口の作業データの live/requests.json。2-15)"""
    REC = "20261008-200000-abcdefghijk"

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="ytt-live-req-")
        self.path = os.path.join(self.tmp, "live", "requests.json")
        self.now = 1_800_000_000.0
        self.logs = []

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def store(self):
        return LR.Store(self.path, clock=lambda: self.now, log=self.logs.append)

    def test_put_get_all_remove(self):
        s = self.store()
        self.assertEqual((s.get("local", self.REC), s.all()), (None, {}))
        self.assertFalse(os.path.exists(self.path), "読むだけでは書かない")
        ctx = {"rid": "20261008-200000-abc123", "deliverDir": "D:/Dropbox/切り抜き依頼/出力", "url": "https://www.youtube.com/watch?v=abcdefghijk",
               "title": "配信" + "x" * 400, "streamer": "兎田ぺこら", "speakers": {"count": 1, "names": ["兎田ぺこら"], "styles": {}}, "videoTracks": 2,
               "cut": "silence", "memo": "m", "settings": {"sens": "low", "perHour": 99, "pad": 0.5}, "extra": "捨てる"}
        item = s.put("local", self.REC, ctx)
        self.assertEqual(item["settings"], dict(LR.SETTINGS_DEFAULT, sens="low", pad=0.5))   # 範囲の外(99)は既定
        self.assertEqual((len(item["title"]), item["createdAt"], "extra" in item), (LR.TEXT_MAX, self.now, False))
        self.assertEqual(sorted(item), ["createdAt", "cut", "deliverBatch", "deliverDir", "memo", "rid", "settings", "speakers", "streamer", "title", "url", "videoTracks"])
        got = s.get("local", self.REC)
        self.assertEqual(got, item)
        got["settings"]["pad"] = 9   # 写しを返す(中の記録は変わらない)
        self.assertEqual(s.get("local", self.REC)["settings"]["pad"], 0.5)
        self.assertEqual(list(s.all()), ["local/" + self.REC])
        again = self.store()   # 書いた記録を読み直せる(入口を起動し直しても結びつきが残る)
        self.assertEqual(again.get("local", self.REC), item)
        with open(self.path, encoding="utf-8") as f:
            self.assertEqual(json.load(f)["v"], 1)
        # 形の違う値は入れない
        bad = s.put("local", "20261008-200000-bbbbbbbbbbb", {"rid": 5, "speakers": "A", "videoTracks": True, "cut": "", "settings": None, "title": None})
        self.assertEqual((bad["rid"], bad["speakers"], bad["videoTracks"], bad["cut"], bad["settings"], bad["title"]),
                         ("5", None, None, None, LR.SETTINGS_DEFAULT, ""))
        # 同じ録画に 2 つ目の依頼 → 新しいほうで置き換える
        s.put("local", self.REC, dict(ctx, rid="20261008-210000-def456"))
        self.assertEqual((s.get("local", self.REC)["rid"], len(s.all())), ("20261008-210000-def456", 2))
        # 消す(無いものは False)
        self.assertTrue(s.remove("local", self.REC))
        self.assertFalse(s.remove("local", self.REC))
        self.assertIsNone(s.get("local", self.REC))
        self.assertEqual(list(self.store().all()), ["local/20261008-200000-bbbbbbbbbbb"])

    def test_prune_old_only(self):
        s = self.store()
        for i in range(3):
            self.now = 1_800_000_000.0 + i * 86400   # 1 日ずつ後
            s.put("local", "20261008-20000%d-abcdefghijk" % i, {"rid": "r%d" % i})
        self.now = 1_800_000_000.0 + LR.KEEP_DAYS * 86400 + 1   # 1 本目だけ 14 日を過ぎた
        self.assertEqual(s.prune(), 1)
        self.assertEqual(sorted(v["rid"] for v in s.all().values()), ["r1", "r2"])
        self.assertEqual(sorted(v["rid"] for v in self.store().all().values()), ["r1", "r2"], "消したら書く")
        with mock.patch.object(LR.fsio, "atomic_write") as w:
            self.assertEqual(s.prune(), 0)
            w.assert_not_called()   # 消すものが無ければ書かない(見回りのたびに呼ぶ)
        self.assertEqual(s.prune(keep_days=0), 2)
        self.assertEqual(self.store().all(), {})

    def test_max_items_drops_oldest(self):
        s = self.store()
        for i in range(LR.MAX_ITEMS + 2):
            self.now = 1_800_000_000.0 + i
            s.put("local", "rec-%03d" % i, {"rid": "r%03d" % i})
        keys = s.all()
        self.assertEqual(len(keys), LR.MAX_ITEMS)
        self.assertEqual(("local/rec-000" in keys, "local/rec-001" in keys, "local/rec-002" in keys, "local/rec-%03d" % (LR.MAX_ITEMS + 1) in keys),
                         (False, False, True, True))
        self.assertEqual(len(self.store().all()), LR.MAX_ITEMS)

    def test_broken_file(self):
        """壊れた・形の違う記録は読み飛ばす。読み直した項目も settings は検査済みの形・createdAt は数(live.py が settings["pad"] を、prune が引き算を使う)"""
        os.makedirs(os.path.dirname(self.path))
        for raw in (b"{broken", b"[]", b'{"v":1,"items":[1,2]}', b'{"v":1,"items":{"a/b":"x","c/d":{"rid":3}}}'):
            with open(self.path, "wb") as f:
                f.write(raw)
            self.assertEqual(self.store().all(), {}, raw)
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump({"v": 1, "items": {"local/rec": {"rid": "r1", "settings": {"pad": 9, "sens": "low"}, "createdAt": "きのう"}}}, f)
        s = self.store()
        got = s.get("local", "rec")
        self.assertEqual((got["settings"], got["createdAt"]), (dict(LR.SETTINGS_DEFAULT, sens="low"), 0))
        self.assertEqual(s.prune(), 1)   # 時刻の分からない項目は片付けで消える
        # 書けない(置き場所がファイル)→ 記録に残して続ける(メモリの結びつきは使える)
        blocked = os.path.join(self.tmp, "file")
        with open(blocked, "wb") as f:
            f.write(b"x")
        s2 = LR.Store(os.path.join(blocked, "requests.json"), clock=lambda: self.now, log=self.logs.append)
        s2.put("local", self.REC, {"rid": "r9"})
        self.assertEqual(s2.get("local", self.REC)["rid"], "r9")
        self.assertTrue(any("書けませんでした" in m for m in self.logs), self.logs)


if __name__ == "__main__":
    unittest.main()
