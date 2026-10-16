"""src/human/friend/returns.py(友人の送り返しの受け取り。F1 の F2)のテスト。リポジトリ直下で:

    py -3.10 -m unittest src/human/friend/tests/test_returns.py

一時フォルダだけを使う(本物の作業データ・Dropbox には触らない)。
"""
import json
import os
import shutil
import sys
import tempfile
import time
import types
import unittest
import zipfile

os.environ.setdefault("YTT_DATA_DIR", "inplace")
SRC = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))   # tests -> friend -> human -> src
if SRC not in sys.path:
    sys.path.insert(0, SRC)

from flow import deliveries, outbox  # noqa: E402
from human import judgments as J  # noqa: E402
from human.friend import returns as R  # noqa: E402

RID = "20261011-120000-abcdef"


def make_zip(path, members):
    with zipfile.ZipFile(path, "w") as z:
        for name, data in members.items():
            z.writestr(name, data)
    old = time.time() - 600
    os.utime(path, (old, old))
    return path


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="ytt-ret-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.sync = os.path.join(self.tmp, "Dropbox")
        self.app = os.path.join(self.tmp, "app")
        self.inbox = os.path.join(self.sync, R.IN_DIR)
        os.makedirs(self.inbox)
        self.msgs = []

    def scan(self):
        return R.scan(self.sync, self.app, log=self.msgs.append)

    def good_zip(self, name=None):
        mf = {"schema": outbox.SCHEMA, "requestId": RID, "runId": "r1", "at": int(time.time() * 1000), "trimmed": []}
        return make_zip(os.path.join(self.inbox, name or "%s__r1.zip" % RID),
                        {"manifest.json": json.dumps(mf), "run.json": json.dumps({"state": "done", "packs": ["pk"]}), "docs/a.json": "{}"})


class TestZip(Base):
    def test_extract_and_move(self):
        self.good_zip()
        res = self.scan()
        self.assertEqual([(r["kind"], r["state"]) for r in res], [("run", "accepted")])
        reqs = R.iter_requests(self.app)
        self.assertEqual(len(reqs), 1)
        self.assertEqual((reqs[0]["requestId"], [r["runId"] for r in reqs[0]["runs"]]), (RID, ["r1"]))
        self.assertTrue(os.path.isfile(os.path.join(reqs[0]["dir"], "r1", "docs", "a.json")))
        self.assertEqual(reqs[0]["month"], time.strftime("%Y-%m"))
        self.assertEqual(os.listdir(self.inbox), [R.DONE_DIR])
        self.assertTrue(os.path.isfile(os.path.join(self.inbox, R.DONE_DIR, time.strftime("%Y-%m-%d"), "%s__r1.zip" % RID)), "受付済み は日付のフォルダ(受付と同じ)")

    def test_zip_slip_refused(self):
        for bad in ("../evil.txt", "a/../../evil.txt", "/abs.txt", "C:/win.txt", "..\\evil.txt"):
            for f in os.listdir(self.inbox):
                shutil.rmtree(os.path.join(self.inbox, f), ignore_errors=True) if os.path.isdir(os.path.join(self.inbox, f)) else os.unlink(os.path.join(self.inbox, f))
            make_zip(os.path.join(self.inbox, "%s__r2.zip" % RID), {"ok.txt": "1", bad: "x"})
            res = self.scan()
            self.assertEqual(res[0]["state"], "rejected", bad)
            self.assertTrue(os.path.isfile(os.path.join(self.inbox, R.FAIL_DIR, "%s__r2.zip" % RID)), bad)
            shutil.rmtree(os.path.join(self.inbox, R.FAIL_DIR))
        self.assertFalse(os.path.exists(os.path.join(self.tmp, "evil.txt")))
        self.assertFalse(os.path.exists(os.path.join(self.app, "evil.txt")))
        self.assertEqual(R.iter_requests(self.app), [])   # 途中まで書いた物を残さない

    def test_windows_reserved_names_refused(self):
        """Windows の予約名(拡張子つき・大文字小文字・末尾の . も)と : を含む名前は断る(9e-2)"""
        for bad in ("CON", "docs/nul.json", "aux.txt", "a/Com1", "lpt9.log", "prn.", "a:b.txt", "docs/x:stream"):
            make_zip(os.path.join(self.inbox, "%s__r5.zip" % RID), {"ok.txt": "1", bad: "x"})
            res = self.scan()
            self.assertEqual(res[0]["state"], "rejected", bad)
            shutil.rmtree(os.path.join(self.inbox, R.FAIL_DIR))
        self.assertEqual(R.iter_requests(self.app), [])
        make_zip(os.path.join(self.inbox, "%s__r6.zip" % RID), {"console.txt": "1", "connect/a.txt": "1"})   # 予約名で始まるだけの名前は通す
        self.assertEqual(self.scan()[0]["state"], "accepted")

    def test_too_many_files_refused(self):
        make_zip(os.path.join(self.inbox, "%s__r3.zip" % RID), {"f%d" % i: "" for i in range(R.MAX_FILES + 1)})
        self.assertEqual(self.scan()[0]["state"], "rejected")

    def test_bad_name_and_corrupt(self):
        make_zip(os.path.join(self.inbox, "weird name.zip"), {"a": "1"})
        p = os.path.join(self.inbox, "%s__r4.zip" % RID)
        with open(p, "wb") as f:
            f.write(b"not a zip")
        old = time.time() - 600
        os.utime(p, (old, old))
        res = {r["name"]: r["state"] for r in self.scan()}
        self.assertEqual(res["weird name.zip"], "rejected")
        self.assertEqual(res["%s__r4.zip" % RID], "wait")   # 同期の途中かもしれない
        self.assertTrue(os.path.isfile(p))
        os.utime(p, (time.time() - 7200,) * 2)
        self.assertEqual(self.scan()[0]["state"], "rejected")

    def test_fresh_file_waits(self):
        p = self.good_zip()
        os.utime(p, None)
        self.assertEqual(self.scan(), [])
        self.assertTrue(os.path.isfile(p))


class TestVerdict(Base):
    def test_verdict_stored_beside_request(self):
        self.good_zip()
        make_zip(os.path.join(self.inbox, "%s__パック1.verdict.json" % RID), {})   # 後で上書き
        vp = os.path.join(self.inbox, "%s__パック1.verdict.json" % RID)
        with open(vp, "w", encoding="utf-8") as f:
            json.dump({"verdict": "made_video", "at": 1760000000000}, f)
        old = time.time() - 600
        os.utime(vp, (old, old))
        res = self.scan()
        self.assertEqual(sorted((r["kind"], r["state"]) for r in res), [("run", "accepted"), ("verdict", "accepted")])
        req = R.iter_requests(self.app)[0]
        self.assertEqual(req["verdicts"], {"パック1": {"verdict": "made_video", "at": 1760000000000}})
        self.assertTrue(os.path.isfile(os.path.join(self.inbox, R.DONE_DIR, time.strftime("%Y-%m-%d"), os.path.basename(vp))))

    def test_bad_verdict_rejected(self):
        for name, body in (("%s__p.verdict.json" % RID, '{"verdict": "great"}'), ("%s__p.verdict.json" % RID, "nope"), ("no-sep.verdict.json", '{"verdict":"keep"}')):
            p = os.path.join(self.inbox, name)
            with open(p, "w", encoding="utf-8") as f:
                f.write(body)
            os.utime(p, (time.time() - 600,) * 2)
            self.assertEqual(self.scan()[0]["state"], "rejected", body)
            shutil.rmtree(os.path.join(self.inbox, R.FAIL_DIR))
        self.assertEqual(R.iter_requests(self.app), [])

    def test_parse_verdict(self):
        self.assertEqual(R.parse_verdict(b'{"verdict":"keep","at":5}'), {"verdict": "keep", "at": 5})
        with self.assertRaises(ValueError):
            R.parse_verdict(b"[]")

    def test_verdict_origin(self):
        """D-SEND 2-7: 採否の任意の origin(request・auto)を受けて並べた verdicts\\ と一覧に残す。知らない値・無い = 鍵ごと無し(古い形)"""
        self.assertEqual(R.parse_verdict(b'{"verdict":"reject","at":5,"origin":"auto"}'), {"verdict": "reject", "at": 5, "origin": "auto"})
        self.assertNotIn("origin", R.parse_verdict(b'{"verdict":"reject","at":5,"origin":"x"}'))
        for name, origin in (("p1", "auto"), ("p2", None)):
            vp = os.path.join(self.inbox, "%s__%s.verdict.json" % (RID, name))
            with open(vp, "w", encoding="utf-8") as f:
                json.dump(dict({"verdict": "keep", "at": 1760000000000}, **({"origin": origin} if origin else {})), f)
            os.utime(vp, (time.time() - 600,) * 2)
        self.scan()
        self.assertEqual(R.iter_requests(self.app)[0]["verdicts"], {"p1": {"verdict": "keep", "at": 1760000000000, "origin": "auto"},
                                                                    "p2": {"verdict": "keep", "at": 1760000000000}})

    def test_parse_verdict_odd_at_is_none(self):
        """at が大きすぎる・無限・NaN・0 以下・数でない = 時刻なし(前は大きすぎる at で OSError / OverflowError になり、送り返し\\ に残り続けた。9e-1)"""
        for raw in ('1e15', '1000000000000000', 'Infinity', '-Infinity', 'NaN', '0', '-5', '"5"', 'true', 'null'):
            self.assertIsNone(R.parse_verdict(('{"verdict":"keep","at":%s}' % raw).encode())["at"], raw)
        self.assertEqual(R.parse_verdict(b'{"verdict":"keep","at":1760000000000.0}')["at"], 1760000000000)

    def test_huge_at_is_filed_not_left(self):
        vp = os.path.join(self.inbox, "%s__p.verdict.json" % RID)
        for raw in ('1e15', 'Infinity'):
            with open(vp, "w", encoding="utf-8") as f:
                f.write('{"verdict":"keep","at":%s}' % raw)
            os.utime(vp, (time.time() - 600,) * 2)
            self.assertEqual([r["state"] for r in self.scan()], ["accepted"], raw)
            self.assertFalse(os.path.exists(vp), raw)
        self.assertEqual(R.iter_requests(self.app)[0]["month"], time.strftime("%Y-%m"))

    def test_unexpected_error_moves_to_failed(self):
        """想定外の例外(OSError 以外)は 失敗 へ理由つき(送り返し\\ に残して毎回ログを増やさない)。OSError は次の見回りでもう一度"""
        from unittest import mock
        vp = os.path.join(self.inbox, "%s__p.verdict.json" % RID)
        with open(vp, "w", encoding="utf-8") as f:
            f.write('{"verdict":"keep","at":5}')
        os.utime(vp, (time.time() - 600,) * 2)
        with mock.patch.object(R, "parse_verdict", side_effect=OSError(13, "busy")):
            self.assertEqual(self.scan(), [])
        self.assertTrue(os.path.isfile(vp), "OSError は残してやり直す")
        with mock.patch.object(R, "parse_verdict", side_effect=OverflowError("too big")):
            res = self.scan()
        self.assertEqual([(r["kind"], r["state"]) for r in res], [("verdict", "rejected")])
        failed = os.path.join(self.inbox, R.FAIL_DIR, os.path.basename(vp))
        self.assertTrue(os.path.isfile(failed))
        with open(os.path.splitext(failed)[0] + ".理由.txt", encoding="utf-8-sig") as f:
            self.assertIn("OverflowError", f.read())

    def test_reject_of_dropbox_pack_discards_like_feedback(self):
        """新しい友人のアプリ(F2-3)は Dropbox で届けたパックの要らないも .verdict.json(zip = Dropbox の zip の名前)で返す
        = .feedback.json と同じ片付け(feedback)へ。keep・zip の無い物(友人の PC で作った物)・片付けの失敗は採否の受け取りを止めない"""
        seen = []

        def fb(d):
            seen.append(d)
            if d["zip"] == "boom.zip":
                raise OSError("busy")
            return {"ok": True, "summary": "片付けた"}
        bodies = {"a": '{"verdict":"reject","at":5,"zip":"%s__a.zip","origin":"auto"}' % RID, "b": '{"verdict":"keep","at":5,"zip":"x.zip"}',
                  "c": '{"verdict":"reject","at":5,"zip":"p_pack"}', "d": '{"verdict":"reject","at":5}', "e": '{"verdict":"reject","at":5,"zip":"boom.zip"}'}
        for name, body in bodies.items():
            vp = os.path.join(self.inbox, "%s__%s.verdict.json" % (RID, name))
            with open(vp, "w", encoding="utf-8") as f:
                f.write(body)
            os.utime(vp, (time.time() - 600,) * 2)
        res = R.scan(self.sync, self.app, log=self.msgs.append, feedback=fb)
        self.assertEqual(sorted(r["state"] for r in res), ["accepted"] * 5)
        self.assertEqual([d["zip"] for d in seen], ["%s__a.zip" % RID, "boom.zip"])
        self.assertEqual((seen[0]["verdict"], seen[0]["requestId"], seen[0]["origin"]), ("reject", RID, "auto"))
        self.assertTrue(any("片付けませんでした" in m and "busy" in m for m in self.msgs))
        self.assertEqual(R.scan(self.sync, self.app), [], "feedback なし(古い呼び方)でも動く")


class TestRoundTrip(Base):
    def test_outbox_zip_to_returns(self):
        work = os.path.join(self.tmp, "case", "作業用")
        os.makedirs(os.path.join(work, "runs"))
        from flow import runlog
        rp = os.path.join(work, "runs", "r9.json")
        with open(rp, "w", encoding="utf-8") as f:
            json.dump({"schema": runlog.RESULT_SCHEMA, "id": "r9", "envelope": {"requestId": RID}, "state": "done", "outputs": {}, "packs": []}, f)
        z = outbox.build(rp, self.app)
        dst = os.path.join(self.inbox, os.path.basename(z))
        shutil.copy(z, dst)
        os.utime(dst, (time.time() - 600,) * 2)
        self.assertEqual(self.scan()[0]["state"], "accepted")
        run = R.iter_requests(self.app)[0]["runs"][0]
        self.assertEqual((run["runId"], run["manifest"]["schema"], run["result"]["state"]), ("r9", outbox.SCHEMA, "done"))
        self.assertEqual(R.requested_videos(self.app), {}, "封筒に配信の id が無い実行は数えない")

    def test_requested_videos(self):
        """D-SEND 2-9: 友人の PC で処理した依頼の配信(送り返しの run.json の封筒 input.videoId)-> {配信: 受け取った時刻(秒)}"""
        work = os.path.join(self.tmp, "case", "作業用")
        os.makedirs(os.path.join(work, "runs"))
        from flow import runlog
        rp = os.path.join(work, "runs", "r8.json")
        with open(rp, "w", encoding="utf-8") as f:
            json.dump({"schema": runlog.RESULT_SCHEMA, "id": "r8", "envelope": {"requestId": RID, "input": {"videoId": "abcdefghijk"}},
                       "state": "done", "outputs": {}, "packs": []}, f)
        z = outbox.build(rp, self.app, now=1760000000)
        dst = os.path.join(self.inbox, os.path.basename(z))
        shutil.copy(z, dst)
        os.utime(dst, (time.time() - 600,) * 2)
        self.scan()
        self.assertEqual(R.requested_videos(self.app), {"abcdefghijk": 1760000000.0})
        self.assertEqual(R.requested_videos(os.path.join(self.tmp, "無い")), {})

    def test_no_folder_is_quiet(self):
        shutil.rmtree(self.inbox)
        self.assertEqual(self.scan(), [])


class TestJudgments(Base):
    """送り返しの採否を人の判断の記録(judgments)に: keep → adopt・reject → reject・made_video → made_video。by auto は書かない。届けた記録のパックは名前で引く"""

    def deliver(self, pack, mid):
        run = types.SimpleNamespace(request_id=RID, id="r1", video_id="VID", title="配信")
        d = os.path.join(self.tmp, "切り抜き", pack)
        deliveries.record(os.path.join(self.app, "logs"), os.path.join(self.tmp, "出力", "%s__r1.zip" % RID), run, [d], {d: {"path": "c.mp4", "markId": mid}} if mid else {})

    def verdict(self, pack, body):
        p = os.path.join(self.inbox, "%s__%s.verdict.json" % (RID, pack))
        with open(p, "w", encoding="utf-8") as f:
            f.write(body)
        os.utime(p, (time.time() - 600,) * 2)

    def test_verdicts_are_judged(self):
        self.deliver("パック1", "m1")
        self.deliver("パック2", "m2")
        self.verdict("パック1", '{"verdict":"keep","at":1760000000000}')
        self.verdict("パック2", '{"verdict":"reject","at":1760000000001}')
        self.verdict("パック3", '{"verdict":"made_video","at":1760000000002}')   # 届けた記録に無い = 配信・マークを空にしてパック名で残す
        self.scan()
        rows = J.rows(self.app)
        self.assertEqual(sorted((r["what"], r["markId"], r["videoId"], r["who"], r["via"], r["origin"]) for r in rows),
                         [("adopt", "m1", "VID", "friend", "friend_verdict", "request"), ("made_video", "", "", "friend", "friend_verdict", "request"),
                          ("reject", "m2", "VID", "friend", "friend_verdict", "request")])
        self.assertEqual([x["ref"]["pack"] for x in rows if not x["markId"]], ["パック3"])
        r = [x for x in rows if x["markId"] == "m1"][0]
        self.assertEqual(r["key"], "vd:%s:パック1:1760000000000" % RID)
        self.assertEqual((r["ref"]["pack"], r["ref"]["zip"], r["ref"]["runId"], r["ref"]["requestId"]), ("パック1", "%s__r1.zip" % RID, "r1", RID))
        self.assertEqual(sorted(R.iter_requests(self.app)[0]["verdicts"]), ["パック1", "パック2", "パック3"], "採否の記録は今のまま残す")

    def test_auto_is_not_judged(self):
        self.deliver("パック1", "m1")
        self.verdict("パック1", '{"verdict":"reject","at":1760000000000,"by":"auto"}')
        self.scan()
        self.assertEqual(J.rows(self.app), [], "3 日で自動の要らないは人の判断ではない")
        self.assertIn("パック1", R.iter_requests(self.app)[0]["verdicts"])

    def test_missing_mark_or_pack_is_kept_by_pack_name(self):
        """マークの分からないパック(古い届けた記録・届けた記録に無い)は配信・マークを空にしてパック名で残す(物差しがパック名で突き合わせる)"""
        self.deliver("パック1", "")
        self.verdict("パック1", '{"verdict":"keep","at":1760000000000}')
        self.verdict("パック9", '{"verdict":"keep","at":1760000000001}')
        self.scan()
        rows = J.rows(self.app)
        self.assertEqual([(r["what"], r["videoId"], r["markId"], r["ref"]["pack"]) for r in rows], [("adopt", "", "", "パック1"), ("adopt", "", "", "パック9")])
        self.assertEqual(J.fold(rows), {}, "マークの分からない行は切り抜きごとに畳まない")
        self.assertEqual(len(R.iter_requests(self.app)[0]["verdicts"]), 2)


if __name__ == "__main__":
    unittest.main()
