"""友人の「要らない」を PC 側に戻す(src/home/friend_feedback.py)の単体テスト。ごみ箱は本物の cleanup.Cleanup(一時フォルダ)。
スタジオは呼ばない(マークは変えない。2026-10-08 ユーザー決定)。

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

import cases  # noqa: E402
from manage.keep import cleanup  # noqa: E402
import friend_feedback as F  # noqa: E402


def put(path, data=b"x"):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(data)
    return path


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

    def test_read_text_limit_and_bom(self):
        """.feedback.json の読み取り: BOM は外す・上限ちょうどは読む・1 バイトでも超えれば ValueError・無ければ OSError"""
        tmp = tempfile.mkdtemp(prefix="ytt-ffb-read-")
        self.addCleanup(shutil.rmtree, tmp, True)
        p = put(os.path.join(tmp, "a.feedback.json"), b"\xef\xbb\xbf{\"v\":1}")
        self.assertEqual(F.read_text(p), '{"v":1}')
        put(p, b"x" * 10)
        self.assertEqual(F.read_text(p, limit=10), "x" * 10)
        with self.assertRaises(ValueError):
            F.read_text(p, limit=9)
        with self.assertRaises(OSError):
            F.read_text(os.path.join(tmp, "無い.feedback.json"))


class TestApply(Base):
    def test_record_and_apply(self):
        """届けた記録 → 要らない: 切り抜き・パックを ごみ箱 へ・friend_feedback.jsonl に 1 行(マークの id つき)。スタジオのマークは触らない"""
        marks = {self.pack1: {"path": self.clip1, "markId": "m1"}, self.pack2: {"path": self.clip2, "markId": "m2"}}
        F.record_delivery(self.logs, os.path.join(self.tmp, "出力", "20261002-120000-0a1b2c__配信A 1-2.zip"), self.run, [self.pack1, self.pack2], marks)
        F.record_delivery(self.logs, os.path.join(self.tmp, "出力", "other.zip"), self.run, [self.pack2], marks)
        row = F.find_delivery(self.logs, "20261002-120000-0a1b2c__配信A 1-2.zip")
        self.assertEqual((row["requestId"], row["videoId"], [p["markId"] for p in row["packs"]]), ("20261002-120000-0a1b2c", "VID", ["m1", "m2"]))
        self.assertIsNone(F.find_delivery(self.logs, "無い.zip"))
        res = F.apply(self.logs, self.fb(), trash=self.trash, log=self.lines.append, discard=cases.discard_clip)
        self.assertTrue(res["ok"], res)
        self.assertIn("2 本をごみ箱フォルダへ(スタジオのマークはそのまま", res["summary"])
        self.assertEqual(sorted(p["markId"] for p in res["packs"]), ["m1", "m2"], "不採用の記録にマークの id を残す")
        for p in (self.clip1, self.clip2, self.pack1, self.pack2):
            self.assertFalse(os.path.exists(p), p)
        trashed = [r for r in res["packs"] if r.get("trash")]
        self.assertEqual(len(trashed), 2)
        self.assertTrue(all(os.path.isdir(r["trash"]) for r in trashed))
        with open(os.path.join(self.logs, F.FEEDBACK_LOG), encoding="utf-8") as f:
            recs = [json.loads(l) for l in f if l.strip()]
        self.assertEqual((recs[-1]["zip"], recs[-1]["verdict"], recs[-1]["videoId"], len(recs[-1]["packs"])), ("20261002-120000-0a1b2c__配信A 1-2.zip", "reject", "VID", 2))
        self.assertEqual(sorted(p["markId"] for p in recs[-1]["packs"]), ["m1", "m2"], "あとで精度の道具が読めるように配信の id とマークの id を残す")
        self.assertTrue(any("要らない" in x for x in self.lines))

    def test_no_record_or_no_parts(self):
        res = F.apply(self.logs, self.fb(), trash=self.trash, discard=cases.discard_clip)
        self.assertFalse(res["ok"])
        self.assertIn("届けた記録に", res["reason"])
        F.record_delivery(self.logs, "x/20261002-120000-0a1b2c__配信A 1-2.zip", self.run, [self.pack1], {self.pack1: {"path": self.clip1, "markId": "m1"}})
        res = F.apply(self.logs, self.fb(), trash=None, discard=cases.discard_clip)
        self.assertFalse(res["ok"])
        self.assertTrue(os.path.exists(self.clip1), "部品が無ければ何も動かさない")
        res = F.apply(self.logs, self.fb(), trash=self.trash)   # 片付ける部品(discard=)を渡されなければ動かさない
        self.assertFalse(res["ok"])
        self.assertIn("部品が使えません", res["reason"])
        self.assertTrue(os.path.exists(self.clip1), "部品が無ければ何も動かさない")

    def test_discard_failure_is_recorded_not_raised(self):
        """渡された片付けが ReviewError(ValueError の子)・OSError で失敗しても、その 1 本の失敗として記録して続ける"""
        F.record_delivery(self.logs, "x/20261002-120000-0a1b2c__配信A 1-2.zip", self.run, [self.pack1, self.pack2],
                          {self.pack1: {"path": self.clip1, "markId": "m1"}, self.pack2: {"path": self.clip2, "markId": "m2"}})
        errs = iter([cases.ReviewError("ごみ箱へ移せません"), OSError("使用中")])

        def discard(*a):
            raise next(errs)
        res = F.apply(self.logs, self.fb(), trash=self.trash, discard=discard)
        self.assertFalse(res["ok"])
        self.assertEqual([("error" in r) for r in res["packs"]], [True, True])
        self.assertIn("片付けられなかった 2 本", res["summary"])
        self.assertTrue(os.path.exists(self.clip1))

    def test_pack_without_mark_is_only_trashed(self):
        """友人の動画の依頼(スタジオのマークが無い)は ごみ箱 へ移すだけ"""
        F.record_delivery(self.logs, "x/20261002-120000-0a1b2c__配信A 1-2.zip", self.run, [self.pack1], {})
        res = F.apply(self.logs, self.fb(), trash=self.trash, discard=cases.discard_clip)
        self.assertTrue(res["ok"], res)
        self.assertEqual([p["markId"] for p in res["packs"]], [""])
        self.assertFalse(os.path.isdir(self.pack1))
        self.assertTrue(os.path.exists(self.clip1), "記録に無い切り抜きの動画は触らない")


if __name__ == "__main__":
    unittest.main()
