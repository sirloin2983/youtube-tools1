"""友人の「要らない」を PC 側に戻す(src/human/friend/friend_feedback.py)の単体テスト。ごみ箱は本物の cleanup.Cleanup(一時フォルダ)。
スタジオは呼ばない(マークは変えない。2026-10-08 ユーザー決定)。

実行(リポジトリ直下から): python -m unittest src/human/friend/tests/test_friend_feedback.py -v
"""
import json
import os
import sys
import types
import unittest

os.environ.setdefault("YTT_DATA_DIR", "inplace")
SRC = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))   # tests -> friend -> human -> src
if SRC not in sys.path:
    sys.path.insert(0, SRC)

from manage.cases import cases  # noqa: E402
from manage.keep import cleanup  # noqa: E402
from human import judgments as J  # noqa: E402
from human.friend import friend_feedback as F  # noqa: E402
from ytt import testkit  # noqa: E402


def put(path, data=b"x"):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(data)
    return path


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = testkit.tempdir(self, "ytt-ffb-")
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
        tmp = testkit.tempdir(self, "ytt-ffb-read-")
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

    def test_made_video_records_only(self):
        """動画にした(F1 F6a): 何も片付けず friend_feedback.jsonl に verdict made_video の 1 行。名前は送り返しの採否(returns.VERDICTS)と同じ"""
        from human.friend import returns
        self.assertTrue(set(F.VERDICTS) <= set(returns.VERDICTS))
        marks = {self.pack1: {"path": self.clip1, "markId": "m1"}}
        z = "20261002-120000-0a1b2c__配信A 1-2.zip"
        F.record_delivery(self.logs, os.path.join(self.tmp, "出力", z), self.run, [self.pack1], marks)
        fb = F.parse(json.dumps({"v": 1, "kind": "feedback", "verdict": "made_video", "zip": z, "requestId": "20261002-120000-0a1b2c"}))
        res = F.apply(self.logs, fb, trash=None, log=self.lines.append, discard=None)
        self.assertTrue(res["ok"], res)
        self.assertTrue(os.path.exists(self.clip1) and os.path.isdir(self.pack1), "片付けない")
        res2 = F.apply(self.logs, dict(fb, zip="無い.zip"), log=self.lines.append)   # 届けた記録が無くても数える
        self.assertTrue(res2["ok"])
        with open(os.path.join(self.logs, F.FEEDBACK_LOG), encoding="utf-8") as f:
            recs = [json.loads(l) for l in f if l.strip()]
        self.assertEqual([(r["verdict"], r["videoId"]) for r in recs], [("made_video", "VID"), ("made_video", "")])
        self.assertEqual(recs[0]["packs"], [{"dir": self.pack1, "markId": "m1"}])

    def test_origin_is_recorded(self):
        """D-SEND 2-7: 友人の返事の記録に出どころ(request・auto)。.feedback.json の任意の origin → 無ければ届けた記録の出どころ(手で届けるは auto)→ 無ければ null"""
        self.assertNotIn("origin", self.fb(), "古い形(origin 無し)も読める")
        z_auto, z_req, z_man = "20261002-120000-0a1b2c__自動.zip", "20261002-120000-0a1b2c__依頼.zip", "20261002-120000-0a1b2c__手.zip"
        F.record_delivery(self.logs, os.path.join(self.tmp, "出力", z_auto), self.run, [self.pack1], {}, "auto", 1000)
        F.record_delivery(self.logs, os.path.join(self.tmp, "出力", z_req), self.run, [self.pack1], {})
        F.record_delivery(self.logs, os.path.join(self.tmp, "出力", z_man), self.run, [self.pack1], {}, "manual")
        made = lambda z, extra="": F.parse('{"v":1,"kind":"feedback","verdict":"made_video","zip":"%s"%s}' % (z, extra))
        self.assertEqual(made(z_req, ',"origin":"auto"')["origin"], "auto")
        self.assertNotIn("origin", made(z_req, ',"origin":"weird"'), "知らない値は鍵ごと無し")
        for fb in (made(z_auto), made(z_req), made(z_man), made(z_req, ',"origin":"auto"'), made("無い.zip")):
            F.apply(self.logs, fb, log=self.lines.append)
        with open(os.path.join(self.logs, F.FEEDBACK_LOG), encoding="utf-8") as f:
            recs = [json.loads(l) for l in f if l.strip()]
        self.assertEqual([r["origin"] for r in recs], ["auto", "request", "auto", "auto", None])

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


    def test_judgments_for_reject(self):
        """人の判断の記録(app の judgments.jsonl): 要らないを届けた記録のパックの markId ごとに who friend で 1 行。ref に zip・パック・依頼・配信の id"""
        marks = {self.pack1: {"path": self.clip1, "markId": "m1"}, self.pack2: {"path": self.clip2, "markId": "m2"}}
        z = "20261002-120000-0a1b2c__配信A 1-2.zip"
        F.record_delivery(self.logs, os.path.join(self.tmp, "出力", z), self.run, [self.pack1, self.pack2], marks)
        res = F.apply(self.logs, self.fb(), trash=self.trash, log=self.lines.append, discard=cases.discard_clip)
        self.assertTrue(res["ok"], res)
        rows = J.rows(os.path.join(self.tmp, "app"))
        self.assertEqual(sorted((r["what"], r["markId"], r["videoId"], r["who"], r["via"], r["origin"]) for r in rows),
                         [("reject", "m1", "VID", "friend", "friend_file", "request"), ("reject", "m2", "VID", "friend", "friend_file", "request")])
        r = [x for x in rows if x["markId"] == "m1"][0]
        self.assertEqual((r["ref"]["zip"], r["ref"]["pack"], r["ref"]["requestId"], r["ref"]["runId"]), (z, "c1_pack", "20261002-120000-0a1b2c", "run1"))
        self.assertEqual(r["key"], "ff:%d:%s:m1" % (r["at"], z))
        with open(os.path.join(self.logs, F.FEEDBACK_LOG), encoding="utf-8") as f:
            self.assertEqual(len([l for l in f if l.strip()]), 1, "友人の返事の記録は今のまま 1 行")

    def test_judgments_made_video_and_old_row_without_mark(self):
        """動画にした: 人の判断の記録に made_video(who friend)。markId の無い古い行は配信・マークを空にしてパック名で残し、友人の返事の記録も残す"""
        app = os.path.join(self.tmp, "app")
        z = "20261002-120000-0a1b2c__配信A 1-2.zip"
        F.record_delivery(self.logs, os.path.join(self.tmp, "出力", z), self.run, [self.pack1], {self.pack1: {"path": self.clip1, "markId": "m1"}})
        fb = F.parse(json.dumps({"v": 1, "kind": "feedback", "verdict": "made_video", "zip": z, "requestId": "20261002-120000-0a1b2c"}))
        self.assertTrue(F.apply(self.logs, fb, log=self.lines.append)["ok"])
        self.assertEqual([(r["who"], r["what"], r["markId"], r["via"]) for r in J.rows(app)], [("friend", "made_video", "m1", "friend_file")])
        z2 = "20261002-120000-0a1b2c__古い.zip"
        F.record_delivery(self.logs, os.path.join(self.tmp, "出力", z2), self.run, [self.pack2], {})
        res = F.apply(self.logs, dict(fb, zip=z2), log=self.lines.append)
        self.assertTrue(res["ok"], res)
        rows = J.rows(app)
        self.assertEqual([(r["videoId"], r["markId"], r["ref"]["pack"]) for r in rows[1:]], [("", "", os.path.basename(self.pack2))], "markId の無い行はパック名で残す")
        with open(os.path.join(self.logs, F.FEEDBACK_LOG), encoding="utf-8") as f:
            self.assertEqual(len([l for l in f if l.strip()]), 2, "友人の返事の記録は残す")


if __name__ == "__main__":
    unittest.main()
