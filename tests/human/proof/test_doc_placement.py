# -*- coding: utf-8 -*-
"""文書の置き場所(ytt/docloc の索引)を人の側の部品が使うことのテスト。

    py -3.12 -m unittest tests/human/proof/test_doc_placement.py -v

索引 transcripts/<id>.loc.json が案件の 作業用 を指す文書を、store(読み書き・履歴・一覧・消す)・alt が
その場所で読み書きすること。索引が無い・id の形が正しくない呼び手は今までどおり TX_DIR。
"""
import os
os.environ.setdefault("YTT_DATA_DIR", "inplace")   # 作業データ(AppData など)に触らない
import shutil
import sys
import unittest

SRC = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))), "src")
for _p in (os.path.join(SRC, "editor"), SRC):
    if _p not in sys.path:
        sys.path.insert(0, _p)
from human.proof import alt, store  # noqa: E402
from ytt import docloc, schemas, workdata  # noqa: E402
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "human"))   # tests/human/(_workdata)
from _workdata import temporary_workdata  # noqa: E402
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))   # tests/(testkit)
import testkit  # noqa: E402

TID = "0123456789ab"


class PlacementTest(unittest.TestCase):
    def setUp(self):
        self.tmp = temporary_workdata(self, "docplace-")
        self.tx = workdata.TX_DIR
        docloc._warned.clear()
        self.case = os.path.join(self.tmp, "案件", schemas.WORK_DIR)
        os.makedirs(self.case)

    def _place(self):
        testkit.write_json(os.path.join(self.case, TID + ".json"), {"id": TID, "segments": []})
        docloc.place(TID, self.case)

    def test_no_index_stays_in_tx_dir(self):
        self.assertEqual(store.tx_path(TID), os.path.join(self.tx, TID + ".json"))
        self.assertEqual(store.edit_path(TID), os.path.join(self.tx, TID + ".edit.json"))
        self.assertEqual(store._hist_dir(TID), os.path.join(self.tx, ".hist", TID))
        self.assertEqual(alt.alt_path(TID), os.path.join(self.tx, TID + ".alt.json"))
        # 壊れた id のときは古い場所のまま
        self.assertEqual(store.tx_path("../x"), os.path.join(self.tx, "../x.json"))
        self.assertEqual(store._hist_dir("zz"), os.path.join(self.tx, ".hist", "zz"))

    def test_placed_doc_paths_follow_index(self):
        self._place()
        self.assertEqual(store.tx_path(TID), os.path.join(self.case, TID + ".json"))
        self.assertEqual(store.edit_path(TID), os.path.join(self.case, TID + ".edit.json"))
        self.assertEqual(store._hist_dir(TID), os.path.join(self.case, ".hist", TID))
        self.assertEqual(alt.alt_path(TID), os.path.join(self.case, TID + ".alt.json"))
        self.assertEqual(store.read_transcript(TID)["id"], TID)
        # 書く・履歴・一覧も案件の場所
        store.write_doc(TID, {"id": TID, "segments": [], "n": 1})
        self.assertFalse(os.path.exists(os.path.join(self.tx, TID + ".json")))
        self.assertEqual(store.read_transcript(TID)["n"], 1)
        store.backup_doc(TID, "test")   # 履歴だけ(.bak の控えは作らない)
        self.assertTrue(os.path.isdir(os.path.join(self.case, ".hist", TID)))
        self.assertFalse(os.path.exists(os.path.join(self.case, ".bak")))
        self.assertFalse(os.path.exists(os.path.join(self.tx, ".bak")))
        self.assertEqual(store._tids(), [TID])

    def test_delete_doc_removes_files_history_index_and_dismissed(self):
        """消す口 store.delete_doc: 本体・横のファイル・履歴・以前の控え .bak・索引・要約・学習の記録の「この候補は出さない」を一緒に消す"""
        from human.proof import learn
        other = "ba9876543210"
        self._place()
        store.write_doc(TID, {"id": TID, "segments": [], "updatedAt": 1})
        store.backup_doc(TID, "x")
        for sfx in (".edit.json", ".words.json", schemas.HUM_SUFFIX):
            testkit.write_text(os.path.join(self.case, TID + sfx), "{}")
        for n in (TID + ".pre-diarize.json", other + ".pre-diarize.json"):   # 以前の版が残した控え(ほかの文書の分は残す)
            testkit.write_text(os.path.join(self.case, ".bak", n), "{}")
        testkit.write_json(workdata.FEEDBACK, {"stat": {"あ=>い": {"acc": 1, "rej": 1}}, "dismissed": {TID: ["s1|あ=>い"], other: ["s2|う=>え"]}})
        self.assertIsNotNone(store.transcript_summary(TID))
        store.delete_doc(TID)
        self.assertEqual(sorted(os.listdir(self.case)), [".bak"])
        self.assertEqual(os.listdir(os.path.join(self.case, ".bak")), [other + ".pre-diarize.json"])
        self.assertFalse(os.path.exists(docloc.loc_path(TID)))
        self.assertNotIn(TID, store._summary_cache)
        fb = learn.load_feedback()
        self.assertEqual((sorted(fb["dismissed"]), fb["stat"]["あ=>い"]["rej"]), ([other], 1))   # 採否の数は残す
        from ytt import errors
        with self.assertRaises(errors.ApiError) as cm:
            store.delete_doc(TID)
        self.assertEqual(cm.exception.status, 404)

    # ---------- 索引があるのに置き場所が見えない(ドライブが外れた)ときは書きを断る・読みは 404 ----------
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
        writes = (lambda: store.write_doc(TID, {"id": TID, "segments": []}),
                  lambda: store._hist_dir(TID, for_write=True), lambda: store.edit_path(TID, for_write=True),
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
        testkit.write_json(os.path.join(self.tx, TID + ".json"), {"id": TID, "segments": [], "updatedAt": 1})
        self.assertEqual(store.read_transcript(TID)["id"], TID)
        with self.assertRaises(errors.ApiError) as cm:
            store.save_transcript(TID, {"segments": []})
        self.assertEqual(cm.exception.code, docloc.UNSEEN_CODE)


if __name__ == "__main__":
    unittest.main()
