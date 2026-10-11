# -*- coding: utf-8 -*-
"""文書を書く唯一の口 human/proof/store.commit のテスト(RS8 O2-0。動きは write_doc と同じ・why をログに残す)。

    py -3.10 -m unittest src/human/proof/tests/test_commit.py -v
"""
import json
import os
os.environ.setdefault("YTT_DATA_DIR", "inplace")   # 作業データ(AppData など)に触らない
import re
import shutil
import sys
import tempfile
import unittest
from unittest import mock

SRC = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
for _p in (os.path.join(SRC, "editor"), SRC):
    if _p not in sys.path:
        sys.path.insert(0, _p)
from human.proof import store  # noqa: E402
from ytt import workdata  # noqa: E402

TID = "0123456789ab"


class CommitTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="commit-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        saved = {n: getattr(workdata, n) for n in ("DATA_DIR", "TX_DIR", "TMP_DIR", "EVAL_BASE", "SETTINGS", "FEEDBACK")}
        self.addCleanup(lambda: [setattr(workdata, n, v) for n, v in saved.items()])
        workdata.set_data_dir(os.path.join(self.tmp, "data"))
        os.makedirs(workdata.TX_DIR)

    def test_commit_writes_like_write_doc_and_logs_why(self):
        doc = {"id": TID, "segments": [{"id": 1, "start": 0, "end": 1, "text": "あ"}]}
        with self.assertLogs("tx", level="INFO") as cm:
            store.commit(TID, doc, why="save")
        with open(store.tx_path(TID), "rb") as f:
            got = f.read()
        self.assertEqual(got, json.dumps(doc, ensure_ascii=False, indent=1).encode("utf-8"))
        self.assertTrue(any("why=save" in m and "by=human" in m for m in cm.output), cm.output)

    def test_machine_why_and_unknown_why(self):
        with self.assertLogs("tx", level="INFO") as cm:
            store.commit(TID, {"id": TID, "segments": []}, why="rerun_each")
        self.assertTrue(any("why=rerun_each" in m and "by=machine" in m for m in cm.output), cm.output)
        with self.assertRaises(ValueError):
            store.commit(TID, {"id": TID}, why="nope")

    def test_mach_hum_not_yet(self):
        with self.assertRaises(NotImplementedError):
            store.commit(TID, {"id": TID}, why="save", mach={})

    def test_save_transcript_goes_through_commit(self):
        store.commit(TID, {"id": TID, "title": "t", "segments": [], "updatedAt": 1}, why="save")
        with mock.patch.object(store, "commit", wraps=store.commit) as c:
            store.save_transcript(TID, {"id": TID, "title": "t2", "segments": [], "updatedAt": 1})
        self.assertEqual([x.kwargs.get("why") for x in c.call_args_list], ["save"])

    def test_every_doc_write_in_src_uses_commit(self):
        """文書を書く呼び出しは store.commit だけ(write_doc は store.py の中の commit からだけ)"""
        pat = re.compile(r"\bwrite_doc\(")
        bad = []
        for base, dirs, files in os.walk(SRC):
            dirs[:] = [d for d in dirs if d not in ("tests", "__pycache__", ".runtime")]
            for fn in files:
                if not fn.endswith(".py"):
                    continue
                path = os.path.join(base, fn)
                with open(path, encoding="utf-8") as f:
                    for i, ln in enumerate(f, 1):
                        if pat.search(ln) and not ln.lstrip().startswith(("#", "def write_doc")):
                            bad.append((os.path.relpath(path, SRC), i))
        self.assertEqual([b[0] for b in bad], [os.path.join("human", "proof", "store.py")], bad)


if __name__ == "__main__":
    unittest.main()
