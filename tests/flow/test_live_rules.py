"""友人のライブ配信の依頼と録画の結びつき(src/flow/live_rules.py の RequestBook。作業データの live/requests.json。2-15)のテスト。

実行(リポジトリ直下から): python -m unittest tests/flow/test_live_rules.py -v
"""
import json
import os
import sys
import unittest
from unittest import mock

os.environ.setdefault("YTT_DATA_DIR", "inplace")
SRC = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "src")   # tests -> flow -> src
if SRC not in sys.path:
    sys.path.insert(0, SRC)

from flow import live_rules as LR  # noqa: E402
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))   # tests/(testkit)
import testkit  # noqa: E402


class LiveRequestsStoreTest(unittest.TestCase):
    """友人のライブ配信の依頼と録画の結びつき(src/flow/live_rules.py の RequestBook。作業データの live/requests.json。2-15)"""
    REC = "20261008-200000-abcdefghijk"

    def setUp(self):
        self.tmp = testkit.tempdir(self, "ytt-live-req-")
        self.path = os.path.join(self.tmp, "live", "requests.json")
        self.now = 1_800_000_000.0
        self.logs = []


    def store(self):
        return LR.RequestBook(self.path, clock=lambda: self.now, log=self.logs.append)

    def test_put_get_all_remove(self):
        s = self.store()
        self.assertEqual((s.get("local", self.REC), s.all()), (None, {}))
        self.assertFalse(os.path.exists(self.path), "読むだけでは書かない")
        ctx = {"rid": "20261008-200000-abc123", "deliverDir": "D:/Dropbox/切り抜き依頼/出力", "url": "https://www.youtube.com/watch?v=abcdefghijk",
               "title": "配信" + "x" * 400, "streamer": "兎田ぺこら", "speakers": {"count": 1, "names": ["兎田ぺこら"], "styles": {}}, "videoTracks": 2,
               "cut": "silence", "settings": {"sens": "low", "perHour": 99, "pad": 0.5}, "extra": "捨てる"}
        item = s.put("local", self.REC, ctx)
        self.assertEqual(item["settings"], dict(LR.SETTINGS_DEFAULT, sens="low", pad=0.5))   # 範囲の外(99)は既定
        self.assertEqual((len(item["title"]), item["createdAt"], "extra" in item), (LR.TEXT_MAX, self.now, False))
        self.assertEqual(sorted(item), ["createdAt", "cut", "deliverDir", "rid", "settings", "speakers", "streamer", "title", "url", "videoTracks"])
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
        self.now = 1_800_000_000.0 + LR.KEEP_DAYS * 86400 + 1   # 1 本目だけ KEEP_DAYS(30 日)を過ぎた = 31 日目
        self.assertEqual(s.prune(), 1)
        self.assertEqual(sorted(v["rid"] for v in s.kept_all().values()), ["r1", "r2"])
        self.assertEqual(sorted(v["rid"] for v in self.store().kept_all().values()), ["r1", "r2"], "消したら書く")
        with mock.patch.object(LR.fsio, "atomic_write") as w:
            self.assertEqual(s.prune(), 0)
            w.assert_not_called()   # 消すものが無ければ書かない(見回りのたびに呼ぶ)
        self.assertEqual(s.prune(keep_days=0), 2)
        self.assertEqual(self.store().kept_all(), {})

    def test_old_binding_is_read_only(self):
        """10-30: 結びつきは 30 日残すが、効くのは LIVE_DAYS(3 日)の中だけ(get・all・update = 検出・採用・配信後の全自動・区切りのパックが読む)。
        古い物は kept・kept_all で読むだけ = 前の 3 日で消していた時と同じ振る舞い"""
        self.assertEqual((LR.KEEP_DAYS, LR.MAX_ITEMS, LR.LIVE_DAYS), (30, 500, 3))
        s = self.store()
        s.put("local", self.REC, {"rid": "r0", "settings": {"afterStream": True}})
        self.now += LR.LIVE_DAYS * 86400
        self.assertEqual(s.get("local", self.REC)["rid"], "r0")   # 3 日ちょうどまでは効く
        self.now += 1
        self.assertIsNone(s.get("local", self.REC))
        self.assertEqual(s.all(), {})
        self.assertIsNone(s.update("local", self.REC, {"sens": "high"}))
        self.assertEqual(s.kept("local", self.REC)["rid"], "r0")
        self.assertEqual(list(s.kept_all()), ["local/" + self.REC])
        self.assertEqual(s.prune(), 0)   # 30 日までは残す
        self.now += (LR.KEEP_DAYS - LR.LIVE_DAYS) * 86400
        self.assertEqual(s.prune(), 1)
        self.assertIsNone(s.kept("local", self.REC))

    def test_max_items_drops_oldest(self):
        s = self.store()
        for i in range(LR.MAX_ITEMS + 2):
            self.now = 1_800_000_000.0 + i
            s.put("local", "rec-%03d" % i, {"rid": "r%03d" % i})
        keys = s.kept_all()
        self.assertEqual(len(keys), LR.MAX_ITEMS)
        self.assertEqual(("local/rec-000" in keys, "local/rec-001" in keys, "local/rec-002" in keys, "local/rec-%03d" % (LR.MAX_ITEMS + 1) in keys),
                         (False, False, True, True))
        self.assertEqual(len(self.store().kept_all()), LR.MAX_ITEMS)

    def test_broken_file(self):
        """壊れた・形の違う記録は読み飛ばす。読み直した項目も settings は検査済みの形・createdAt は数(live.py が settings["pad"] を、prune が引き算を使う)"""
        os.makedirs(os.path.dirname(self.path))
        for raw in (b"{broken", b"[]", b'{"v":1,"items":[1,2]}', b'{"v":1,"items":{"a/b":"x","c/d":{"rid":3}}}'):
            with open(self.path, "wb") as f:
                f.write(raw)
            self.assertEqual(self.store().all(), {}, raw)
        testkit.write_json(self.path, {"v": 1, "items": {"local/rec": {"rid": "r1", "settings": {"pad": 9, "sens": "low"}, "createdAt": "きのう"}}})
        s = self.store()
        got = s.kept("local", "rec")   # 時刻の分からない項目は効かない(get は None)
        self.assertEqual((got["settings"], got["createdAt"]), (dict(LR.SETTINGS_DEFAULT, sens="low"), 0))
        self.assertEqual(s.prune(), 1)   # 時刻の分からない項目は片付けで消える
        # 書けない(置き場所がファイル)→ 記録に残して続ける(メモリの結びつきは使える)
        blocked = os.path.join(self.tmp, "file")
        with open(blocked, "wb") as f:
            f.write(b"x")
        s2 = LR.RequestBook(os.path.join(blocked, "requests.json"), clock=lambda: self.now, log=self.logs.append)
        s2.put("local", self.REC, {"rid": "r9"})
        self.assertEqual(s2.get("local", self.REC)["rid"], "r9")
        self.assertTrue(any("書けませんでした" in m for m in self.logs), self.logs)


if __name__ == "__main__":
    unittest.main()
