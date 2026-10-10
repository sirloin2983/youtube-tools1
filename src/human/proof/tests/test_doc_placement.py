# -*- coding: utf-8 -*-
"""文書の置き場所(ytt/docloc の索引)を人の側の部品が使うことのテスト(RS8 B-2-1b)。

    py -3.10 -m unittest src/human/proof/tests/test_doc_placement.py -v

索引 transcripts/<id>.loc.json が案件の 作業用 を指す文書を、store(読み書き・履歴・控え・一覧)・alt・ytcap・overrides が
その場所で読み書きすること。索引が無い・id の形が正しくない呼び手は今までどおり TX_DIR。
"""
import json
import os
os.environ.setdefault("YTT_DATA_DIR", "inplace")   # 作業データ(AppData など)に触らない
import shutil
import sys
import tempfile
import unittest

SRC = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
for _p in (os.path.join(SRC, "editor"), SRC):
    if _p not in sys.path:
        sys.path.insert(0, _p)
from human.proof import alt, overrides, store, ytcap  # noqa: E402
from ytt import docloc, schemas, workdata  # noqa: E402

TID = "0123456789ab"


class PlacementTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="docplace-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        saved = {n: getattr(workdata, n) for n in ("DATA_DIR", "TX_DIR", "TMP_DIR", "EVAL_BASE", "SETTINGS", "FEEDBACK")}
        self.addCleanup(lambda: [setattr(workdata, n, v) for n, v in saved.items()])
        workdata.set_data_dir(os.path.join(self.tmp, "data"))
        self.tx = workdata.TX_DIR
        os.makedirs(self.tx)
        docloc._warned.clear()
        self.case = os.path.join(self.tmp, "案件", schemas.WORK_DIR)
        os.makedirs(self.case)

    def _place(self):
        with open(os.path.join(self.case, TID + ".json"), "w", encoding="utf-8") as f:
            f.write(json.dumps({"id": TID, "segments": []}))
        docloc.place(TID, self.case)

    def test_no_index_stays_in_tx_dir(self):
        self.assertEqual(store.tx_path(TID), os.path.join(self.tx, TID + ".json"))
        self.assertEqual(store.edit_path(TID), os.path.join(self.tx, TID + ".edit.json"))
        self.assertEqual(store._hist_dir(TID), os.path.join(self.tx, ".hist", TID))
        self.assertEqual(alt.alt_path(TID), os.path.join(self.tx, TID + ".alt.json"))
        self.assertEqual(ytcap.ytcap_path(TID), os.path.join(self.tx, TID + ".ytcap.json"))
        self.assertEqual(overrides.over_path(TID), os.path.join(self.tx, TID + ".over.json"))

    def test_bad_id_keeps_old_path(self):
        self.assertEqual(store.tx_path("../x"), os.path.join(self.tx, "../x.json"))
        self.assertEqual(store._hist_dir("zz"), os.path.join(self.tx, ".hist", "zz"))

    def test_placed_doc_paths_follow_index(self):
        self._place()
        self.assertEqual(store.tx_path(TID), os.path.join(self.case, TID + ".json"))
        self.assertEqual(store.edit_path(TID), os.path.join(self.case, TID + ".edit.json"))
        self.assertEqual(store._hist_dir(TID), os.path.join(self.case, ".hist", TID))
        self.assertEqual(alt.alt_path(TID), os.path.join(self.case, TID + ".alt.json"))
        self.assertEqual(ytcap.ytcap_path(TID), os.path.join(self.case, TID + ".ytcap.json"))
        self.assertEqual(overrides.over_path(TID), os.path.join(self.case, TID + ".over.json"))
        self.assertEqual(store.read_transcript(TID)["id"], TID)

    def test_placed_doc_write_backup_and_list(self):
        self._place()
        store.write_doc(TID, {"id": TID, "segments": [], "n": 1})
        self.assertFalse(os.path.exists(os.path.join(self.tx, TID + ".json")))
        self.assertEqual(store.read_transcript(TID)["n"], 1)
        store.backup_doc(TID, "test")
        self.assertTrue(os.path.isfile(os.path.join(self.case, ".bak", TID + ".pre-test.json")))
        self.assertTrue(os.path.isdir(os.path.join(self.case, ".hist", TID)))
        self.assertFalse(os.path.exists(os.path.join(self.tx, ".bak")))
        self.assertEqual(store._tids(), [TID])

    def test_placed_over_roundtrip(self):
        self._place()
        overrides.write(TID, {"rows": [], "speakers": []}, "k")
        self.assertTrue(os.path.isfile(os.path.join(self.case, TID + ".over.json")))
        self.assertFalse(os.path.exists(os.path.join(self.tx, TID + ".over.json")))
        self.assertIsNotNone(overrides.read(TID))


if __name__ == "__main__":
    unittest.main()
