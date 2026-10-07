"""友人の「要らない」を PC 側に戻す(src/home/friend_feedback.py)の単体テスト。スタジオは偽物・ごみ箱は本物の cleanup.Cleanup(一時フォルダ)。

実行(リポジトリ直下から): python -m unittest src/home/tests/test_friend_feedback.py -v
"""
import json
import os
import shutil
import sys
import tempfile
import types
import unittest

os.environ.setdefault("YTT_DATA_DIR", "inplace")
HOME = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
ROOT = os.path.dirname(HOME)
for p in (HOME, ROOT):
    if p not in sys.path:
        sys.path.insert(0, p)

import cleanup  # noqa: E402
import friend_feedback as F  # noqa: E402


def put(path, data=b"x"):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(data)
    return path


class FakeStudio:
    """cases._studio_reject が使う GET /api/video と PUT /api/video の偽物(マーク m1・m2 の配信 VID)"""

    def __init__(self, marks=("m1", "m2"), down=False):
        self.marks = [{"id": m, "status": "exported", "start": 1, "end": 5} for m in marks]
        self.rev, self.puts, self.down = 3, [], down

    def __call__(self, method, path, body=None):
        if self.down:
            return None, {"message": "つながらない"}
        if method == "GET":
            return 200, {"video": {"id": "VID", "rev": self.rev, "marks": [dict(m) for m in self.marks]}}
        self.puts.append(body)
        self.marks = [dict(m) for m in body["marks"]]
        self.rev += 1
        return 200, {"ok": True}


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="ytt-ffb-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.logs = os.path.join(self.tmp, "app", "logs")
        self.trash = cleanup.Cleanup(os.path.join(self.tmp, "app"), env={"YTT_DATA_DIR": os.path.join(self.tmp, "data")})
        self.lines = []
        v = os.path.join(self.tmp, "clips")
        self.clip1, self.clip2 = put(os.path.join(v, "c1.mp4"), b"v1"), put(os.path.join(v, "c2.mp4"), b"v2")
        self.pack1, self.pack2 = os.path.join(v, "c1_pack"), os.path.join(v, "c2_pack")
        put(os.path.join(self.pack1, "cut-plan.json"), b"{}")
        put(os.path.join(self.pack2, "cut-plan.json"), b"{}")
        self.run = types.SimpleNamespace(request_id="20261002-120000-0a1b2c", id="run1", video_id="VID", title="配信A")

    def fb(self, zip_name="20261002-120000-0a1b2c__配信A 1-2.zip"):
        return F.parse(json.dumps({"v": 1, "kind": "feedback", "verdict": "reject", "zip": zip_name, "requestId": "20261002-120000-0a1b2c",
                                   "title": "配信A 1-2", "sentAt": "2026-10-08T01:02:03+09:00"}))


class TestParse(unittest.TestCase):
    def test_parse(self):
        fb = F.parse('{"v":1,"kind":"feedback","verdict":"reject","zip":"a__b 1-2.zip","requestId":"a","title":"b 1-2"}')
        self.assertEqual((fb["zip"], fb["verdict"], fb["requestId"], fb["title"]), ("a__b 1-2.zip", "reject", "a", "b 1-2"))
        for bad in ("{", "[]", '{"v":2,"kind":"feedback","verdict":"reject","zip":"a.zip"}', '{"v":1,"kind":"x","verdict":"reject","zip":"a.zip"}',
                    '{"v":1,"kind":"feedback","verdict":"keep","zip":"a.zip"}', '{"v":1,"kind":"feedback","verdict":"reject","zip":"../a.zip"}',
                    '{"v":1,"kind":"feedback","verdict":"reject","zip":"a.txt"}', '{"v":1,"kind":"feedback","verdict":"reject"}'):
            with self.assertRaises(ValueError, msg=bad):
                F.parse(bad)


class TestApply(Base):
    def test_record_and_apply(self):
        """届けた記録 → 要らない: 切り抜き・パックを ごみ箱 へ・スタジオのマークを不採用に・friend_feedback.jsonl に 1 行"""
        marks = {self.pack1: {"path": self.clip1, "markId": "m1"}, self.pack2: {"path": self.clip2, "markId": "m2"}}
        F.record_delivery(self.logs, os.path.join(self.tmp, "出力", "20261002-120000-0a1b2c__配信A 1-2.zip"), self.run, [self.pack1, self.pack2], marks)
        F.record_delivery(self.logs, os.path.join(self.tmp, "出力", "other.zip"), self.run, [self.pack2], marks)
        row = F.find_delivery(self.logs, "20261002-120000-0a1b2c__配信A 1-2.zip")
        self.assertEqual((row["requestId"], row["videoId"], [p["markId"] for p in row["packs"]]), ("20261002-120000-0a1b2c", "VID", ["m1", "m2"]))
        self.assertIsNone(F.find_delivery(self.logs, "無い.zip"))
        studio = FakeStudio()
        res = F.apply(self.logs, self.fb(), studio=studio, trash=self.trash, log=self.lines.append)
        self.assertTrue(res["ok"], res)
        self.assertIn("2 本をごみ箱フォルダへ(スタジオのマークを不採用 2 本)", res["summary"])
        self.assertEqual(len(studio.puts), 2)
        self.assertEqual({m["id"]: m["status"] for m in studio.marks}, {"m1": "rejected", "m2": "rejected"})
        for p in (self.clip1, self.clip2, self.pack1, self.pack2):
            self.assertFalse(os.path.exists(p), p)
        trashed = [r for r in res["packs"] if r.get("trash")]
        self.assertEqual(len(trashed), 2)
        self.assertTrue(all(os.path.isdir(r["trash"]) for r in trashed))
        with open(os.path.join(self.logs, F.FEEDBACK_LOG), encoding="utf-8") as f:
            recs = [json.loads(l) for l in f if l.strip()]
        self.assertEqual((recs[-1]["zip"], recs[-1]["verdict"], recs[-1]["videoId"], len(recs[-1]["packs"])), ("20261002-120000-0a1b2c__配信A 1-2.zip", "reject", "VID", 2))
        self.assertTrue(any("要らない" in x for x in self.lines))

    def test_no_record_or_no_parts(self):
        res = F.apply(self.logs, self.fb(), studio=FakeStudio(), trash=self.trash)
        self.assertFalse(res["ok"])
        self.assertIn("届けた記録に", res["reason"])
        F.record_delivery(self.logs, "x/20261002-120000-0a1b2c__配信A 1-2.zip", self.run, [self.pack1], {self.pack1: {"path": self.clip1, "markId": "m1"}})
        res = F.apply(self.logs, self.fb(), studio=None, trash=self.trash)
        self.assertFalse(res["ok"])
        self.assertTrue(os.path.exists(self.clip1), "部品が無ければ何も動かさない")

    def test_studio_down_keeps_files(self):
        """スタジオにつながらなければ、移した物を戻して失敗の文(パックだけ消えてマークが残る、を作らない)"""
        F.record_delivery(self.logs, "x/20261002-120000-0a1b2c__配信A 1-2.zip", self.run, [self.pack1], {self.pack1: {"path": self.clip1, "markId": "m1"}})
        res = F.apply(self.logs, self.fb(), studio=FakeStudio(down=True), trash=self.trash, log=self.lines.append)
        self.assertFalse(res["ok"], res)
        self.assertIn("片付けられなかった 1 本", res["summary"])
        self.assertTrue(os.path.exists(self.clip1) and os.path.isdir(self.pack1))

    def test_pack_without_mark_is_only_trashed(self):
        """友人の動画の依頼(スタジオのマークが無い)は ごみ箱 へ移すだけ"""
        F.record_delivery(self.logs, "x/20261002-120000-0a1b2c__配信A 1-2.zip", self.run, [self.pack1], {})
        studio = FakeStudio()
        res = F.apply(self.logs, self.fb(), studio=studio, trash=self.trash)
        self.assertTrue(res["ok"], res)
        self.assertEqual(studio.puts, [])
        self.assertFalse(os.path.isdir(self.pack1))
        self.assertTrue(os.path.exists(self.clip1), "記録に無い切り抜きの動画は触らない")


if __name__ == "__main__":
    unittest.main()
