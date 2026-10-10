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

    # ---------- 索引があるのに置き場所が見えない(ドライブが外れた)ときは書きを断る・読みは 404(RS8 B2-2) ----------
    def _unseen(self):
        self._place()
        shutil.rmtree(self.case)   # 案件のフォルダが見えなくなった

    def test_unseen_refuses_writes_and_reads_404(self):
        from ytt import errors, txwords
        from pipeline.transcribe import records
        from flow import keys
        self._unseen()
        with self.assertRaises(errors.ApiError) as cm:
            store.read_transcript(TID)
        self.assertEqual(cm.exception.status, 404)
        writes = (lambda: store.write_doc(TID, {"id": TID, "segments": []}), lambda: store.backup_doc(TID, "x"),
                  lambda: store._hist_dir(TID, for_write=True), lambda: store.edit_path(TID, for_write=True),
                  lambda: overrides.write(TID, {"rows": []}),
                  lambda: txwords.write_words(TID, [[0.0, 1.0, "a"]]), lambda: records.write_asr(TID, [], {}))
        for w in writes:
            with self.assertRaises(errors.ApiError) as cm:
                w()
            self.assertEqual((cm.exception.code, cm.exception.status), (docloc.UNSEEN_CODE, 503))
        self.assertEqual(keys.write_diar(TID, []), False)   # 鍵は断られても段を失敗にしない(ログだけ)
        self.assertEqual(sorted(os.listdir(self.tx)), [TID + docloc.LOC_SUFFIX])   # TX_DIR に文書・横のファイルを作らない

    def test_tx_dir_copy_is_not_written_when_unseen(self):
        """索引が見えないあいだに TX_DIR に古い写しが残っていても、書きは断る(写しを読めはする = 枝分かれさせない)"""
        from ytt import errors
        self._unseen()
        with open(os.path.join(self.tx, TID + ".json"), "w", encoding="utf-8") as f:
            f.write(json.dumps({"id": TID, "segments": [], "updatedAt": 1}))
        self.assertEqual(store.read_transcript(TID)["id"], TID)
        with self.assertRaises(errors.ApiError) as cm:
            store.save_transcript(TID, {"segments": []})
        self.assertEqual(cm.exception.code, docloc.UNSEEN_CODE)


class OpenVideoPlacementTest(unittest.TestCase):
    """「文字起こしせずに開く」の新しい文書: 書き出し先の下の案件(作業用/.studio-id)の動画なら その 作業用 に置く。案件でなければ TX_DIR"""

    def setUp(self):
        from unittest import mock
        from flow import placement
        from ytt import names
        self.tmp = tempfile.mkdtemp(prefix="docplace-open-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        saved = {n: getattr(workdata, n) for n in ("DATA_DIR", "TX_DIR", "TMP_DIR", "EVAL_BASE", "SETTINGS", "FEEDBACK")}
        self.addCleanup(lambda: [setattr(workdata, n, v) for n, v in saved.items()])
        workdata.set_data_dir(os.path.join(self.tmp, "data"))
        self.tx = workdata.TX_DIR
        os.makedirs(self.tx)
        store._summary_cache.clear()
        self.addCleanup(store._summary_cache.clear)
        self.out = os.path.join(self.tmp, "out")
        self.wd = os.path.join(self.out, "題名", schemas.WORK_DIR)
        os.makedirs(self.wd)
        with open(os.path.join(self.wd, names.OWNER_FILE), "w", encoding="utf-8") as f:
            f.write("vid")
        for p in (mock.patch.object(placement._datadir, "studio_out_dir", return_value=self.out),
                  mock.patch.object(placement._fsio, "is_fixed_drive", return_value=True),
                  mock.patch.object(store._tools, "probe_media", return_value=(10.0, True, True))):
            p.start()
            self.addCleanup(p.stop)

    def _video(self, folder, name="題名_01.mp4"):
        os.makedirs(folder, exist_ok=True)
        path = os.path.join(folder, name)
        with open(path, "wb") as f:
            f.write(b"x")
        return path

    def test_case_video_goes_to_work_dir(self):
        src = self._video(os.path.dirname(self.wd))
        got = store.open_video({"path": src})
        tid = got["id"]
        self.assertTrue(got["created"])
        self.assertTrue(os.path.isfile(os.path.join(self.wd, tid + ".json")))
        self.assertFalse(os.path.exists(os.path.join(self.tx, tid + ".json")))
        self.assertEqual(docloc.placed(tid), os.path.normpath(self.wd))
        self.assertEqual(store.read_transcript(tid)["sourcePath"], src)
        self.assertEqual(store.open_video({"path": src}), {"id": tid, "created": False, "warnings": []})   # 2 回目は同じ文書(一覧が索引を読む)

    def test_other_video_stays_in_tx_dir(self):
        src = self._video(os.path.join(self.tmp, "よそ"))
        tid = store.open_video({"path": src})["id"]
        self.assertTrue(os.path.isfile(os.path.join(self.tx, tid + ".json")))
        self.assertFalse(os.path.exists(docloc.loc_path(tid)))


if __name__ == "__main__":
    unittest.main()
