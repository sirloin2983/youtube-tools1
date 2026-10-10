#!/usr/bin/env python3
"""文書の一覧が、案件の 作業用 に置いた文書(索引 .loc.json があるもの)も拾うことの確かめ(RS8 B-2-1b)。

    python -m unittest src/manage/cases/tests/test_docloc_listing.py

txindex.load・accuracy.count_daily・eval_asr.load_docs は、
索引が無ければ今までどおり transcripts の直下だけ・索引があれば置いた先から読む。
"""
import json
import os
os.environ.setdefault("YTT_DATA_DIR", "inplace")
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))))   # src
from eval.drill import accuracy  # noqa: E402
from eval.tools import eval_asr  # noqa: E402
from manage.cases import txindex  # noqa: E402
from ytt import docloc, schemas, workdata  # noqa: E402

TID = "0123456789ab"
TID2 = "ba9876543210"


def doc(tid, text="あ"):
    return {"id": tid, "title": "t", "sourcePath": "x.mp4", "segments": [{"id": "s1", "start": 0, "end": 4, "text": text, "proofed": True}]}


class DocListingTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="doclisting-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        saved = {n: getattr(workdata, n) for n in ("DATA_DIR", "TX_DIR", "TMP_DIR", "EVAL_BASE", "SETTINGS", "FEEDBACK")}
        self.addCleanup(lambda: [setattr(workdata, n, v) for n, v in saved.items()])
        self.data = os.path.join(self.tmp, "data")
        workdata.set_data_dir(self.data)
        self.tx = workdata.TX_DIR
        os.makedirs(self.tx)
        docloc._warned.clear()
        self.case = os.path.join(self.tmp, "out", "題名", schemas.WORK_DIR)
        os.makedirs(self.case)

    def _write(self, folder, tid, d):
        with open(os.path.join(folder, tid + ".json"), "w", encoding="utf-8") as f:
            json.dump(d, f)

    def _place(self, tid):
        self._write(self.case, tid, doc(tid, "置いた先"))
        docloc.place(tid, self.case)

    def test_no_index_reads_tx_dir_only(self):
        self._write(self.tx, TID, doc(TID))
        self.assertEqual([d["id"] for d in txindex.load(self.tx)], [TID])
        self.assertEqual(accuracy.count_daily(self.tx)["docs"], 1)

    def test_load_reads_placed_doc(self):
        self._write(self.tx, TID, doc(TID))
        self._place(TID2)
        got = {d["id"]: d for d in txindex.load(self.tx)}
        self.assertEqual(sorted(got), [TID, TID2])
        self.assertEqual(got[TID2]["segments"][0]["text"], "置いた先")

    def test_count_daily_and_load_docs_follow_index(self):
        self._place(TID)
        self.assertEqual(accuracy.count_daily(self.tx)["docs"], 1)
        self.assertEqual([d["id"] for d in eval_asr.load_docs(self.data, "all")], [TID])


if __name__ == "__main__":
    unittest.main()
