"""src/flow/outbox.py(送り返しの zip。F1 の F2)のテスト。リポジトリ直下で:

    py -3.10 -m unittest src/flow/tests/test_outbox.py

一時フォルダだけを使う(本物の作業データ・Dropbox には触らない)。
"""
import json
import os
import sys
import unittest
import zipfile

os.environ.setdefault("YTT_DATA_DIR", "inplace")
SRC = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))   # tests -> flow -> src
if SRC not in sys.path:
    sys.path.insert(0, SRC)

from ytt import testkit  # noqa: E402
from flow import outbox, runlog  # noqa: E402

SECRET = "AIzaSyA1234567890abcdefghijklmnopqrstuv"


def put(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(data if isinstance(data, bytes) else json.dumps(data, ensure_ascii=False).encode("utf-8"))
    return path


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = testkit.tempdir(self, "ytt-outbox-")
        self.app = os.path.join(self.tmp, "app")
        self.case = os.path.join(self.tmp, "case")
        self.work = os.path.join(self.case, "作業用")
        self.doc = put(os.path.join(self.tmp, "tx", "0123456789ab.json"), {"segments": [{"text": "こんにちは"}]})
        self.key = put(os.path.join(self.tmp, "tx", "0123456789ab.transcribe.key.json"), {"stage": "transcribe", "inputs": {"engine": "whisper", "model": "large-v3", "device": "cuda"}})
        self.pack = os.path.join(self.case, "pack1")
        self.pkey = put(os.path.join(self.pack, "pack.key.json"), {"stage": "pack", "inputs": {}})
        put(os.path.join(self.pack, "video.mp4"), b"MOVIE" * 1000)   # 動画は入れない
        put(os.path.join(self.work, "候補.json"), {"marks": [{"id": "m1", "score": 87}]})
        put(os.path.join(self.work, "採用.json"), {"adopted": ["m1"]})
        self.result = {"schema": runlog.RESULT_SCHEMA, "id": "r20261011", "envelope": {"requestId": "20261011-120000-abcdef", "apiKey": "x" * 10},
                       "spec": {"yt": {"token": "tttttttt"}}, "state": "done", "message": "", "error": "",
                       "outputs": {"transcribe": [{"doc": "0123456789ab", "path": self.doc, "key": self.key, "post": None}],
                                   "pack": [{"path": self.pack, "key": self.pkey}]},
                       "packs": [self.pack], "created": 1, "at": 2}
        self.rp = put(os.path.join(self.work, "runs", "r20261011.json"), self.result)
        self.logp = put(os.path.join(self.tmp, "ytt.log"), ("\n".join("行%d" % i for i in range(3000)) + "\nkey=" + SECRET + "\n").encode("utf-8"))

    def names(self, p):
        with zipfile.ZipFile(p) as z:
            return z.namelist()


class TestBuild(Base):
    def test_contents_and_no_media(self):
        p = outbox.build(self.rp, self.app, log_path=self.logp, now=1.0)
        self.assertEqual(os.path.basename(p), "20261011-120000-abcdef__r20261011.zip")
        n = self.names(p)
        for need in ("run.json", "manifest.json", "health.json", "candidates.json", "adopted.json", "log-tail.txt", "docs/0123456789ab.json"):
            self.assertIn(need, n)
        self.assertTrue(any(x.startswith("keys/transcribe/") for x in n))
        self.assertTrue(any(x.startswith("keys/pack/") for x in n))
        self.assertFalse(any(x.endswith(".mp4") for x in n))
        with zipfile.ZipFile(p) as z:
            mf = json.loads(z.read("manifest.json").decode("utf-8"))
            self.assertEqual((mf["schema"], mf["runId"], mf["trimmed"]), (outbox.SCHEMA, "r20261011", []))

    def test_secrets_are_masked(self):
        p = outbox.build(self.rp, self.app, log_path=self.logp)
        with zipfile.ZipFile(p) as z:
            blob = b"".join(z.read(i) for i in z.namelist())
            run = json.loads(z.read("run.json").decode("utf-8"))
            tail = z.read("log-tail.txt").decode("utf-8")
        self.assertNotIn(SECRET.encode(), blob)
        self.assertNotIn(b"tttttttt", blob)
        self.assertEqual(run["envelope"]["apiKey"], outbox.MASK)
        self.assertEqual(run["spec"]["yt"]["token"], outbox.MASK)
        self.assertEqual(len(tail.splitlines()), outbox.LOG_TAIL_LINES)

    def test_no_request_id_means_no_zip(self):
        self.result["envelope"] = {}
        put(self.rp, self.result)
        self.assertIsNone(outbox.build(self.rp, self.app))
        self.assertTrue(outbox.build(self.rp, self.app, request_id="rq1"))

    def test_bad_result_is_none(self):
        put(self.rp, {"schema": "other"})
        self.assertIsNone(outbox.build(self.rp, self.app))
        self.assertIsNone(outbox.build(os.path.join(self.tmp, "none.json"), self.app))

    def test_size_limit_trims_docs_first(self):
        put(self.doc, {"segments": [{"text": os.urandom(60000).hex()}]})
        p = outbox.build(self.rp, self.app, log_path=self.logp, max_bytes=100 * 1024)
        self.assertLessEqual(os.path.getsize(p), 100 * 1024)
        with zipfile.ZipFile(p) as z:
            mf = json.loads(z.read("manifest.json").decode("utf-8"))
            self.assertIn("doc", mf["trimmed"])
            self.assertNotIn("docs/0123456789ab.json", z.namelist())
            self.assertIn("run.json", z.namelist())


class TestListDone(Base):
    def test_list_and_done(self):
        p = outbox.build(self.rp, self.app)
        open(os.path.join(os.path.dirname(p), "x.zip.part"), "wb").close()
        lst = outbox.list_outbox(self.app)
        self.assertEqual([x["id"] for x in lst], [os.path.basename(p)])
        self.assertEqual((lst[0]["requestId"], lst[0]["runId"]), ("20261011-120000-abcdef", "r20261011"))
        self.assertFalse(outbox.mark_done(self.app, "../evil.zip"))
        self.assertFalse(outbox.mark_done(self.app, "nothing__x.zip"))
        self.assertTrue(outbox.mark_done(self.app, lst[0]["id"]))
        self.assertEqual(outbox.list_outbox(self.app), [])
        self.assertTrue(os.path.isfile(os.path.join(self.app, "outbox", outbox.DONE_DIR, lst[0]["id"])))
        self.assertFalse(outbox.mark_done(self.app, lst[0]["id"]))

    def test_empty_when_no_folder(self):
        self.assertEqual(outbox.list_outbox(os.path.join(self.tmp, "nope")), [])


if __name__ == "__main__":
    unittest.main()
