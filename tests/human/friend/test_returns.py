"""src/human/friend/returns.py(友人の送り返しの受け取り。F1 の F2)のテスト。リポジトリ直下で:

    py -3.12 -m unittest tests/human/friend/test_returns.py

一時フォルダだけを使う(本物の作業データ・Dropbox には触らない)。
"""
import json
import os
import shutil
import sys
import time
import types
import unittest
import zipfile

os.environ.setdefault("YTT_DATA_DIR", "inplace")
SRC = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))), "src")   # tests -> friend -> human -> src
if SRC not in sys.path:
    sys.path.insert(0, SRC)

from flow import deliveries, outbox  # noqa: E402
from human import judgments as J  # noqa: E402
from human.friend import returns as R  # noqa: E402
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))   # tests/(testkit)
import testkit  # noqa: E402

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
        self.tmp = testkit.tempdir(self, "ytt-ret-")
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
        # 上限 MAX_FILES を超える zip を断る
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


G = '{"v":2,"id":"g1","judge":"good","at":%s}'   # 時刻だけ変える判断


class TestVerdict(Base):
    def test_verdict_stored_beside_request(self):
        self.good_zip()
        make_zip(os.path.join(self.inbox, "%s__パック1.verdict.json" % RID), {})   # 後で上書き
        vp = os.path.join(self.inbox, "%s__パック1.verdict.json" % RID)
        testkit.write_json(vp, {"v": 2, "id": "g1", "judge": "good", "at": 1760000000000})
        old = time.time() - 600
        os.utime(vp, (old, old))
        res = self.scan()
        self.assertEqual(sorted((r["kind"], r["state"]) for r in res), [("run", "accepted"), ("verdict", "accepted")])
        req = R.iter_requests(self.app)[0]
        self.assertEqual(req["verdicts"], {"パック1": {"judge": "good", "at": 1760000000000}})
        self.assertTrue(os.path.isfile(os.path.join(self.inbox, R.DONE_DIR, time.strftime("%Y-%m-%d"), os.path.basename(vp))))

    def test_bad_verdict_rejected(self):
        for name, body in (("%s__p.verdict.json" % RID, '{"v":2,"id":"a","judge":"great"}'), ("%s__p.verdict.json" % RID, "nope"),
                           ("%s__p.verdict.json" % RID, '{"verdict":"keep","at":5}'),   # v 2 でない形は断る
                           ("no-sep.verdict.json", '{"v":2,"id":"a","judge":"good"}')):
            p = os.path.join(self.inbox, name)
            with open(p, "w", encoding="utf-8") as f:
                f.write(body)
            os.utime(p, (time.time() - 600,) * 2)
            self.assertEqual(self.scan()[0]["state"], "rejected", body)
            shutil.rmtree(os.path.join(self.inbox, R.FAIL_DIR))
        self.assertEqual(R.iter_requests(self.app), [])


    def test_verdict_origin(self):
        """D-SEND 2-7: 判断の任意の origin(request・auto)を受けて並べた verdicts\\ と一覧に残す。知らない値・無い = 鍵ごと無し"""
        self.assertEqual(R.parse_verdict(b'{"v":2,"id":"a","judge":"good","at":5,"origin":"auto"}'), {"v": 2, "judge": "good", "id": "a", "at": 5, "origin": "auto"})
        self.assertNotIn("origin", R.parse_verdict(b'{"v":2,"id":"a","judge":"good","at":5,"origin":"x"}'))
        for name, origin in (("p1", "auto"), ("p2", None)):
            vp = os.path.join(self.inbox, "%s__%s.verdict.json" % (RID, name))
            testkit.write_json(vp, dict({"v": 2, "id": name, "judge": "good", "at": 1760000000000}, **({"origin": origin} if origin else {})))
            os.utime(vp, (time.time() - 600,) * 2)
        self.scan()
        self.assertEqual(R.iter_requests(self.app)[0]["verdicts"], {"p1": {"judge": "good", "at": 1760000000000, "origin": "auto"},
                                                                    "p2": {"judge": "good", "at": 1760000000000}})

    def test_parse_verdict(self):
        """正常な形・配列は断る。at が大きすぎる・無限・NaN・0 以下・数でない = 時刻なし。
        大きすぎる at の採否も受付済みへ片付け、送り返しに残さない"""
        self.assertEqual(R.parse_verdict(b'{"v":2,"id":"a","judge":"good","at":5}'), {"v": 2, "judge": "good", "id": "a", "at": 5})
        with self.assertRaises(ValueError):
            R.parse_verdict(b"[]")
        for raw in ('1e15', '1000000000000000', 'Infinity', '-Infinity', 'NaN', '0', '-5', '"5"', 'true', 'null'):
            self.assertIsNone(R.parse_verdict((G % raw).encode())["at"], raw)
        self.assertEqual(R.parse_verdict(b'{"v":2,"id":"g1","judge":"good","at":1760000000000.0}')["at"], 1760000000000)
        vp = os.path.join(self.inbox, "%s__p.verdict.json" % RID)
        for raw in ('1e15', 'Infinity'):
            with open(vp, "w", encoding="utf-8") as f:
                f.write(G % raw)
            os.utime(vp, (time.time() - 600,) * 2)
            self.assertEqual([r["state"] for r in self.scan()], ["accepted"], raw)
            self.assertFalse(os.path.exists(vp), raw)
        self.assertEqual(R.iter_requests(self.app)[0]["month"], time.strftime("%Y-%m"))

    def test_unexpected_error_moves_to_failed(self):
        """想定外の例外(OSError 以外)は 失敗 へ理由つき(送り返し\\ に残して毎回ログを増やさない)。OSError は次の見回りでもう一度"""
        from unittest import mock
        vp = os.path.join(self.inbox, "%s__p.verdict.json" % RID)
        with open(vp, "w", encoding="utf-8") as f:
            f.write(G % 5)
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

    def test_bad_of_dropbox_pack_discards(self):
        """Dropbox で届けたパックの bad・unknown(zip = Dropbox の zip の名前)は片付け(feedback)へ。good・zip の無い物(友人の PC で作った物)・
        片付けの失敗は判断の受け取りを止めない"""
        seen = []

        def fb(d):
            seen.append(d)
            if d["zip"] == "boom.zip":
                raise OSError("busy")
            return {"ok": True, "summary": "片付けた"}
        bodies = {"a": '{"v":2,"id":"a","judge":"unknown","at":5,"zip":"%s__a.zip","origin":"auto"}' % RID, "b": '{"v":2,"id":"b","judge":"good","at":5,"zip":"x.zip"}',
                  "c": '{"v":2,"id":"c","judge":"unknown","at":5,"zip":"p_pack"}', "d": '{"v":2,"id":"d","judge":"unknown","at":5}',
                  "e": '{"v":2,"id":"e","judge":"bad","reason":"cut","at":5,"zip":"boom.zip"}'}
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
    def to_inbox(self, run_id, envelope, **kw):
        """友人の PC の実行結果(run.json)を送り返しの zip にして受信箱へ置く"""
        from flow import runlog
        work = os.path.join(self.tmp, "case", "作業用")
        os.makedirs(os.path.join(work, "runs"), exist_ok=True)
        rp = testkit.write_json(os.path.join(work, "runs", run_id + ".json"),
                                {"schema": runlog.RESULT_SCHEMA, "id": run_id, "envelope": envelope, "state": "done", "outputs": {}, "packs": []})
        z = outbox.build(rp, self.app, **kw)
        dst = os.path.join(self.inbox, os.path.basename(z))
        shutil.copy(z, dst)
        os.utime(dst, (time.time() - 600,) * 2)

    def test_outbox_zip_to_returns(self):
        self.to_inbox("r9", {"requestId": RID})
        self.assertEqual(self.scan()[0]["state"], "accepted")
        run = R.iter_requests(self.app)[0]["runs"][0]
        self.assertEqual((run["runId"], run["manifest"]["schema"], run["result"]["state"]), ("r9", outbox.SCHEMA, "done"))

    def test_no_folder_is_quiet(self):
        shutil.rmtree(self.inbox)
        self.assertEqual(self.scan(), [])


class TestJudgments(Base):
    """送り返しの判断を人の判断の記録(judgments)に。届けた記録のパックは名前で引く"""

    def deliver(self, pack, mid):
        run = types.SimpleNamespace(request_id=RID, id="r1", video_id="VID", title="配信")
        d = os.path.join(self.tmp, "切り抜き", pack)
        deliveries.record(os.path.join(self.app, "logs"), os.path.join(self.tmp, "出力", "%s__r1.zip" % RID), run, [d], {d: {"path": "c.mp4", "markId": mid}} if mid else {})

    def verdict(self, pack, body):
        p = os.path.join(self.inbox, "%s__%s.verdict.json" % (RID, pack))
        with open(p, "w", encoding="utf-8") as f:
            f.write(body)
        os.utime(p, (time.time() - 600,) * 2)

    def test_missing_mark_or_pack_is_kept_by_pack_name(self):
        """マークの分からないパック(古い届けた記録・届けた記録に無い)は配信・マークを空にしてパック名で残す(物差しがパック名で突き合わせる)"""
        self.deliver("パック1", "")
        self.verdict("パック1", '{"v":2,"id":"k1","judge":"good","at":1760000000000}')
        self.verdict("パック9", '{"v":2,"id":"k9","judge":"good","at":1760000000001}')
        self.scan()
        rows = J.rows(self.app)
        self.assertEqual([(r["what"], r["videoId"], r["markId"], r["ref"]["pack"]) for r in rows], [("good", "", "", "パック1"), ("good", "", "", "パック9")])
        self.assertEqual(J.fold(rows), {}, "マークの分からない行は切り抜きごとに畳まない")
        self.assertEqual(len(R.iter_requests(self.app)[0]["verdicts"]), 2)


class TestV2(Base):
    """v 2: good・bad(reason)・unknown(by auto)・retract。名前の ~<at> で同じ切り抜きの記録を並べる。zip の名前で届けた記録を引く"""
    deliver = TestJudgments.deliver

    def v2(self, pack, body, at):
        p = os.path.join(self.inbox, "%s__%s~%013d.verdict.json" % (RID, pack, at))
        testkit.write_json(p, dict({"v": 2, "at": at, "zip": "%s__r1.zip" % RID}, **body))
        os.utime(p, (time.time() - 600,) * 2)

    def test_good_bad_unknown_and_retract(self):
        self.deliver("パック1", "m1")
        self.v2("パック1", {"id": "f1", "judge": "bad", "reason": "cut"}, 1760000000000)
        self.scan()
        self.v2("パック1", {"id": "f2", "judge": "retract", "of": "f1"}, 1760000000001)
        self.v2("パック1", {"id": "f3", "judge": "unknown", "by": "auto"}, 1760000000002)
        self.scan()
        rows = J.rows(self.app)
        self.assertEqual([(r["what"], r.get("reason"), r.get("by"), r["key"]) for r in rows],
                         [("bad", "cut", None, "vd2:f1"), ("retract", None, None, "vd2:f2"), ("unknown", None, "auto", "vd2:f3")])
        self.assertEqual(rows[1]["of"], rows[0]["id"])
        slot = J.fold(rows)[("VID", "m1")]
        self.assertEqual(J.friend_value(slot["friend"]), "unknown")
        self.assertEqual(len(R.iter_requests(self.app)[0]["verdicts"]), 3, "~<at> で上書きしない")

    def test_retract_of_last_empties_lane(self):
        self.deliver("パック1", "m1")
        self.v2("パック1", {"id": "f1", "judge": "good"}, 1760000000000)
        self.v2("パック1", {"id": "f2", "judge": "retract", "of": "f1"}, 1760000000001)
        self.scan()
        self.assertIsNone(J.fold(J.rows(self.app))[("VID", "m1")]["friend"])

    def test_meta_ids_for_friend_pc_packs(self):
        """届けた記録に無い(友人の PC で処理した)物は、返ってきた videoId・markId で引く"""
        self.v2("パック7", {"id": "f9", "judge": "good", "videoId": "V2", "markId": "m7", "zip": "x__パック7.zip"}, 1760000000000)
        self.scan()
        r = J.rows(self.app)[0]
        self.assertEqual((r["videoId"], r["markId"], r["what"]), ("V2", "m7", "good"))

    def test_bad_forms_refused(self):
        for i, body in enumerate(({"id": "a", "judge": "bad"}, {"id": "b", "judge": "great"}, {"judge": "good"}, {"id": "c", "judge": "retract"},
                                  {"id": "d", "judge": "bad", "reason": "long"})):
            self.v2("p%d" % i, body, 1760000000000 + i)
        res = self.scan()
        self.assertEqual([r["state"] for r in res], ["rejected"] * 5)
        self.assertEqual(J.rows(self.app), [])

    def test_bad_and_unknown_discard_but_feedback_does_not_judge_again(self):
        seen = []
        self.deliver("パック1", "m1")
        self.v2("パック1", {"id": "f1", "judge": "bad", "reason": "boring"}, 1760000000000)
        self.v2("パック2", {"id": "f2", "judge": "good"}, 1760000000001)
        R.scan(self.sync, self.app, log=self.msgs.append, feedback=lambda d: seen.append(d) or {"ok": True})
        self.assertEqual([(d["zip"], d["judged"]) for d in seen], [("%s__r1.zip" % RID, True)])

    def test_parse_v2_keeps_only_known_fields(self):
        v = R.parse_verdict(json.dumps({"v": 2, "id": "x", "judge": "unknown", "by": "auto", "at": 5, "origin": "auto", "markId": "bad id!"}).encode())
        self.assertEqual(v, {"v": 2, "judge": "unknown", "id": "x", "at": 5, "by": "auto", "origin": "auto"})


class TestNotice(Base):
    """[作る人に知らせる](C-2-16): <rid>__notice-<at>.notice.json を <依頼>\\notices\\ に並べ、ログに 1 行・recent_notices で 7 日の分"""

    def notice(self, body, at=1760000000000, rid=RID):
        p = os.path.join(self.inbox, "%s__notice-%013d.notice.json" % (rid, at))
        with open(p, "w", encoding="utf-8") as f:
            f.write(body if isinstance(body, str) else json.dumps(body))
        os.utime(p, (time.time() - 600,) * 2)
        return p

    def test_received_and_listed(self):
        p = self.notice({"v": 1, "kind": "failure", "title": "配信者|配信", "message": "直りませんでした", "detail": "x" * 9000, "code": "transcribe",
                         "appVersion": "1.0.0", "log": "ログ", "at": 1760000000000})
        res = self.scan()
        self.assertEqual([(r["kind"], r["state"]) for r in res], [("notice", "accepted")])
        self.assertFalse(os.path.exists(p))
        self.assertTrue(any("友人から知らせ" in m and "直りませんでした" in m for m in self.msgs))
        got = R.recent_notices(self.app)
        self.assertEqual(len(got), 1)
        self.assertEqual((got[0]["message"], got[0]["code"], got[0]["requestId"], got[0]["hasLog"], len(got[0]["detail"])),
                         ("直りませんでした", "transcribe", RID, True, R.NOTICE_TEXT["detail"]))
        self.assertEqual(R.iter_requests(self.app)[0]["runs"], [], "notices は実行の結果ではない")
        self.assertEqual(R.recent_notices(self.app, now=time.time() + 8 * 86400), [], "7 日を過ぎたら出さない")

    def test_bad_notice_rejected(self):
        self.notice("nope", at=1)
        self.notice({"v": 1, "kind": "failure", "message": ""}, at=2)
        p = os.path.join(self.inbox, "x__notice.notice.json")
        with open(p, "w", encoding="utf-8") as f:
            f.write("{}")
        os.utime(p, (time.time() - 600,) * 2)
        res = self.scan()
        self.assertEqual(sorted(r["state"] for r in res), ["rejected"] * 3)
        self.assertEqual(R.recent_notices(self.app), [])


if __name__ == "__main__":
    unittest.main()
