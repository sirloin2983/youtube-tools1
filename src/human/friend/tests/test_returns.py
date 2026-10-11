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
import unittest
import zipfile

os.environ.setdefault("YTT_DATA_DIR", "inplace")
SRC = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))   # tests -> friend -> human -> src
if SRC not in sys.path:
    sys.path.insert(0, SRC)

from flow import outbox  # noqa: E402
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
        self.assertTrue(os.path.isfile(os.path.join(self.inbox, R.DONE_DIR, "%s__r1.zip" % RID)))

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
        self.assertTrue(os.path.isfile(os.path.join(self.inbox, R.DONE_DIR, os.path.basename(vp))))

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

    def test_no_folder_is_quiet(self):
        shutil.rmtree(self.inbox)
        self.assertEqual(self.scan(), [])


if __name__ == "__main__":
    unittest.main()
