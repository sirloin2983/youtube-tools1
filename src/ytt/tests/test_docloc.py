#!/usr/bin/env python3
"""ytt/docloc.py(文字起こしの文書の置き場所を引く口。RS8 B-2)のテスト。

    python -m unittest src/ytt/tests/test_docloc.py

索引が無ければ今までどおり workdata.TX_DIR・索引があれば案件の 作業用・壊れた索引や使えない場所は TX_DIR に落ちる、を確かめる。
"""
import json
import os
os.environ.setdefault("YTT_DATA_DIR", "inplace")   # 作業データは読み書きしないが、ほかのテストとそろえる
import shutil
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))   # src
from ytt import docloc, schemas, workdata  # noqa: E402

TID = "0123456789ab"
TID2 = "ba9876543210"


class DoclocTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="docloc-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        saved = {n: getattr(workdata, n) for n in ("DATA_DIR", "TX_DIR", "TMP_DIR", "EVAL_BASE", "SETTINGS", "FEEDBACK")}
        self.addCleanup(lambda: [setattr(workdata, n, v) for n, v in saved.items()])
        workdata.set_data_dir(os.path.join(self.tmp, "data"))
        self.tx = workdata.TX_DIR
        os.makedirs(self.tx)
        docloc._warned.clear()
        self.case = os.path.join(self.tmp, "out", "題名", schemas.WORK_DIR)
        os.makedirs(self.case)

    def _doc(self, folder, tid=TID):
        with open(os.path.join(folder, tid + ".json"), "w", encoding="utf-8") as f:
            f.write("{}")

    def _loc(self, obj, tid=TID, root=None):
        with open(os.path.join(root or self.tx, tid + docloc.LOC_SUFFIX), "w", encoding="utf-8") as f:
            f.write(obj if isinstance(obj, str) else json.dumps(obj))

    def test_no_index_is_tx_dir(self):
        self.assertEqual(docloc.doc_dir(TID), self.tx)
        self.assertEqual(docloc.doc_file(TID, ".json"), os.path.join(self.tx, TID + ".json"))
        self.assertEqual(docloc.doc_file(TID, ".edit.json"), os.path.join(self.tx, TID + ".edit.json"))
        self.assertEqual(docloc.hist_dir(TID), os.path.join(self.tx, ".hist", TID))
        self.assertEqual(docloc.bak_dir(TID), os.path.join(self.tx, ".bak"))
        self.assertIsNone(docloc.placed(TID))

    def test_reads_tx_dir_each_call(self):
        other = os.path.join(self.tmp, "other", "transcripts")
        workdata.TX_DIR = other
        self.assertEqual(docloc.doc_dir(TID), other)

    def test_place_and_unplace(self):
        self._doc(self.case)
        path = docloc.place(TID, self.case)
        self.assertEqual(path, os.path.join(self.tx, TID + docloc.LOC_SUFFIX))
        with open(path, encoding="utf-8") as f:
            self.assertEqual(json.load(f), {"version": 1, "id": TID, "dir": os.path.normpath(self.case)})
        self.assertEqual(docloc.doc_dir(TID), os.path.normpath(self.case))
        self.assertEqual(docloc.doc_file(TID, ".diar.key.json"), os.path.join(os.path.normpath(self.case), TID + ".diar.key.json"))
        self.assertEqual(docloc.hist_dir(TID), os.path.join(os.path.normpath(self.case), ".hist", TID))
        self.assertEqual(docloc.bak_dir(TID), os.path.join(os.path.normpath(self.case), ".bak"))
        self.assertEqual(docloc.doc_dir(TID2), self.tx)   # 別の文書は今のまま
        self.assertTrue(docloc.unplace(TID))
        self.assertFalse(docloc.unplace(TID))
        self.assertEqual(docloc.doc_dir(TID), self.tx)

    def test_place_tx_root_is_unplace(self):
        self._doc(self.case)
        docloc.place(TID, self.case)
        self.assertIsNone(docloc.place(TID, self.tx))
        self.assertFalse(os.path.exists(docloc.loc_path(TID)))

    def test_place_rejects_bad_folder(self):
        not_work = os.path.join(self.tmp, "out", "題名")
        self._doc(not_work)
        for folder in (not_work, "relative/" + schemas.WORK_DIR, self.case, "", None):   # 作業用 でない・相対・文書が無い・空
            with self.subTest(folder=folder), self.assertRaises(ValueError):
                docloc.place(TID, folder)
        self.assertFalse(os.path.exists(docloc.loc_path(TID)))

    def test_broken_index_falls_back(self):
        self._doc(self.case)
        cases = ("{not json", [], {"version": 2, "id": TID, "dir": self.case}, {"version": 1, "id": TID2, "dir": self.case},
                 {"version": 1, "id": TID}, {"version": 1, "id": TID, "dir": "relative/" + schemas.WORK_DIR})
        for obj in cases:
            with self.subTest(obj=obj):
                self._loc(obj)
                with self.assertLogs("tx", "WARNING"):
                    self.assertEqual(docloc.doc_dir(TID), self.tx)
                docloc._warned.clear()

    def test_falls_back_once_logged(self):
        self._loc({"version": 1, "id": TID, "dir": self.case})   # 文書が無い 作業用
        with self.assertLogs("tx", "WARNING") as cm:
            for _ in range(3):
                self.assertEqual(docloc.doc_dir(TID), self.tx)
        self.assertEqual(len(cm.output), 1)
        self.assertIn("文書が無い", cm.output[0])

    def test_not_work_dir_falls_back(self):
        folder = os.path.join(self.tmp, "out", "題名")
        self._doc(folder)
        self._loc({"version": 1, "id": TID, "dir": folder})
        with self.assertLogs("tx", "WARNING") as cm:
            self.assertEqual(docloc.doc_dir(TID), self.tx)
        self.assertIn(schemas.WORK_DIR, cm.output[0])

    def test_network_path_rejected_without_touching(self):
        for unc in ("\\\\server\\share\\" + schemas.WORK_DIR, "//server/share/" + schemas.WORK_DIR):
            with self.subTest(unc=unc):
                self._loc({"version": 1, "id": TID, "dir": unc})
                with mock.patch("os.path.isfile", wraps=os.path.isfile) as isfile, self.assertLogs("tx", "WARNING") as cm:
                    self.assertEqual(docloc.doc_dir(TID), self.tx)
                self.assertIn("ネットワーク", cm.output[0])
                self.assertFalse([c for c in isfile.call_args_list if "server" in str(c)])   # サーバーのパスは調べない
                with self.assertRaises(ValueError):
                    docloc.place(TID, unc)
                docloc._warned.clear()

    def test_remote_drive_rejected(self):
        self._doc(self.case)
        self._loc({"version": 1, "id": TID, "dir": self.case})
        with mock.patch.object(docloc._fsio, "is_remote_drive", return_value=True), self.assertLogs("tx", "WARNING"):
            self.assertEqual(docloc.doc_dir(TID), self.tx)
            with self.assertRaises(ValueError):
                docloc.place(TID, self.case)

    def test_tid_checked(self):
        for bad in ("..", "../x", "0123456789AB", "0123456789a", "0123456789abc", "0123456789a/", None, 12):
            with self.subTest(tid=bad):
                for fn in (docloc.doc_dir, docloc.hist_dir, docloc.bak_dir, docloc.placed, docloc.loc_path, docloc.unplace):
                    with self.assertRaises(ValueError):
                        fn(bad)
                with self.assertRaises(ValueError):
                    docloc.doc_file(bad, ".json")
                with self.assertRaises(ValueError):
                    docloc.place(bad, self.case)

    def test_suffix_checked(self):
        for bad in (".tmp", "/../x.json", ".loc.json", ".transcript.json", ""):
            with self.subTest(suffix=bad), self.assertRaises(ValueError):
                docloc.doc_file(TID, bad)

    def test_doc_suffixes(self):
        s = docloc.DOC_SUFFIXES
        self.assertEqual(s[0], ".json")
        self.assertEqual(len(set(s)), len(s))
        for want in (".edit.json", ".edit.broken.json", ".words.json", ".asr.json", ".diar.json", ".alt.json", ".ytcap.json",
                     ".llm.json", ".over.json", ".transcribe.key.json", ".post.key.json", ".diar.key.json"):
            self.assertIn(want, s)
        self.assertNotIn(docloc.LOC_SUFFIX, s)   # 索引は根に残す物で、文書と一緒に動かさない

    def test_iter_tids_union(self):
        self._doc(self.tx, TID2)
        self._doc(self.tx, TID)            # 移す途中: 根にも案件にもある → 1 回だけ
        self._doc(self.case, TID)
        docloc.place(TID, self.case)
        third = "cccccccccccc"
        self._doc(self.case, third)
        docloc.place(third, self.case)     # 案件にだけある
        for n in (TID + ".edit.json", TID2 + ".diar.key.json", "notatid.json", ".write-test"):
            with open(os.path.join(self.tx, n), "w") as f:
                f.write("{}")
        os.makedirs(os.path.join(self.tx, ".hist", TID))
        self.assertEqual(docloc.iter_tids(), sorted([TID, TID2, third]))

    def test_iter_tids_skips_unusable_index(self):
        self._loc({"version": 1, "id": TID, "dir": self.case})   # 文書が無い = 読めない id は出さない
        self._doc(self.tx, TID2)
        self._loc("{broken", tid=TID2)                            # 索引が壊れても根に文書があれば出す
        with self.assertLogs("tx", "WARNING"):
            self.assertEqual(docloc.iter_tids(), [TID2])

    def test_iter_tids_missing_root(self):
        workdata.TX_DIR = os.path.join(self.tmp, "nowhere")
        self.assertEqual(docloc.iter_tids(), [])
        workdata.TX_DIR = None
        self.assertEqual(docloc.iter_tids(), [])

    def test_data_dir(self):
        other = os.path.join(self.tmp, "learning")
        root = os.path.join(other, "transcripts")
        os.makedirs(root)
        self._doc(root, TID2)
        self._doc(self.tx, TID)
        self.assertEqual(docloc.tx_root(other), root)
        self.assertEqual(docloc.doc_dir(TID, other), root)
        self.assertEqual(docloc.doc_file(TID2, ".json", data_dir=other), os.path.join(root, TID2 + ".json"))
        self.assertEqual(docloc.iter_tids(other), [TID2])
        self.assertEqual(docloc.iter_tids(), [TID])
        self._doc(self.case, TID2)
        docloc.place(TID2, self.case, data_dir=other)   # 索引も data_dir の根に
        self.assertTrue(os.path.isfile(os.path.join(root, TID2 + docloc.LOC_SUFFIX)))
        self.assertEqual(docloc.doc_dir(TID2, other), os.path.normpath(self.case))
        self.assertEqual(docloc.doc_dir(TID2), self.tx)   # 今の TX_DIR には索引が無い
        self.assertTrue(docloc.unplace(TID2, data_dir=other))

    def test_unseen(self):
        """索引はあるが使えない文書の数と理由(使える索引・索引の無い文書は数えない・ログは書かない)"""
        self.assertEqual(docloc.unseen(), {"count": 0, "reasons": {}})
        self._doc(self.case)
        docloc.place(TID, self.case)
        self._doc(self.tx, TID2)   # 索引の無い文書
        self.assertEqual(docloc.unseen()["count"], 0)
        self._loc({"version": 1, "id": TID2, "dir": os.path.join(self.tmp, "消えた", schemas.WORK_DIR)}, TID2)
        tid3 = "cccccccccccc"
        self._loc("{壊れた", tid3)
        with mock.patch.object(docloc.log, "warning") as warn:
            got = docloc.unseen()
        warn.assert_not_called()
        self.assertEqual(got, {"count": 2, "reasons": {"文書が無い": 1, "索引が読めない": 1}})
        self._loc("{}", "not-a-tid")   # id でない名前は数えない
        self.assertEqual(docloc.unseen()["count"], 2)
        self.assertEqual(docloc.unseen(os.path.join(self.tmp, "無い")), {"count": 0, "reasons": {}})

    # ---------- 新しい文書を案件に置く(RS8 B2-2) ----------
    @staticmethod
    def _writer(body=b"{}"):
        def write(path):
            with open(path, "wb") as f:
                f.write(body)
        return write

    def test_check_folder(self):
        self.assertIsNone(docloc.check_folder(self.case))   # 文書が無くてもよい(形だけ)
        self.assertIsNone(docloc.check_folder(os.path.join(self.tmp, "まだ無い", schemas.WORK_DIR)))
        self.assertEqual(docloc.check_folder("rel/" + schemas.WORK_DIR), "絶対パスではない")
        self.assertEqual(docloc.check_folder(None), "絶対パスではない")
        self.assertEqual(docloc.check_folder("//srv/share/" + schemas.WORK_DIR), "ネットワーク上のパス")
        self.assertIn("ではない", docloc.check_folder(os.path.join(self.tmp, "out")))

    def test_place_new_into_case(self):
        new = os.path.join(self.tmp, "out", "別の案件", schemas.WORK_DIR)
        os.makedirs(os.path.dirname(new))   # 案件の根はある・作業用 はまだ無い
        path = docloc.place_new(TID, new, self._writer())
        self.assertEqual(path, os.path.join(os.path.normpath(new), TID + ".json"))
        self.assertTrue(os.path.isfile(path))
        self.assertEqual(docloc.placed(TID), os.path.normpath(new))
        self.assertFalse(os.path.exists(os.path.join(self.tx, TID + ".json")))
        self.assertEqual(docloc.doc_file(TID, ".asr.json", for_write=True), os.path.join(os.path.normpath(new), TID + ".asr.json"))   # 横のファイルも案件へ

    def test_place_new_without_folder_is_tx_dir(self):
        path = docloc.place_new(TID, None, self._writer())
        self.assertEqual(path, os.path.join(self.tx, TID + ".json"))
        self.assertTrue(os.path.isfile(path))
        self.assertFalse(os.path.exists(docloc.loc_path(TID)))

    def test_place_new_unusable_folder_is_tx_dir(self):
        gone = os.path.join(self.tmp, "外れた", "案件", schemas.WORK_DIR)   # 案件の根が無い = 作らない
        for folder in (gone, os.path.join(self.tmp, "out"), "//srv/share/" + schemas.WORK_DIR):
            path = docloc.place_new(TID, folder, self._writer())
            self.assertEqual(path, os.path.join(self.tx, TID + ".json"), folder)
            self.assertFalse(os.path.exists(docloc.loc_path(TID)))
            os.remove(path)
        self.assertFalse(os.path.exists(os.path.join(self.tmp, "外れた")))

    def test_place_new_existing_id_is_not_forked(self):
        self._doc(self.tx)   # この id の文書がもう TX_DIR にある
        path = docloc.place_new(TID, self.case, self._writer(b'{"n": 2}'))
        self.assertEqual(path, os.path.join(self.tx, TID + ".json"))
        self.assertFalse(os.path.exists(os.path.join(self.case, TID + ".json")))

    def test_place_new_falls_back_when_place_fails(self):
        with mock.patch.object(docloc, "place", side_effect=OSError("disk")), mock.patch.object(docloc.log, "warning") as warn:
            path = docloc.place_new(TID, self.case, self._writer())
        self.assertEqual(path, os.path.join(self.tx, TID + ".json"))
        self.assertTrue(os.path.isfile(path))
        self.assertFalse(os.path.exists(os.path.join(self.case, TID + ".json")))   # 作業用 の本体は消す(索引の無い写しを残さない)
        self.assertFalse(os.path.exists(docloc.loc_path(TID)))
        self.assertEqual(warn.call_count, 1)
        self.assertEqual(docloc.doc_dir(TID), self.tx)

    def test_place_new_falls_back_when_write_fails(self):
        calls = []

        def write(path):
            calls.append(path)
            if len(calls) == 1:
                raise OSError("書けない")
            self._writer()(path)
        path = docloc.place_new(TID, self.case, write)
        self.assertEqual(calls, [os.path.join(os.path.normpath(self.case), TID + ".json"), os.path.join(self.tx, TID + ".json")])
        self.assertEqual(path, os.path.join(self.tx, TID + ".json"))
        self.assertFalse(os.path.exists(docloc.loc_path(TID)))

    def test_place_new_bad_id(self):
        with self.assertRaises(ValueError):
            docloc.place_new("../x", self.case, self._writer())

    # ---------- 索引があるのに使えないときは書きを断る(読みは TX_DIR に落ちる) ----------
    def test_for_write_refuses_unusable_index(self):
        from ytt import errors
        gone = os.path.join(self.tmp, "外れた", schemas.WORK_DIR)
        self._loc({"version": 1, "id": TID, "dir": gone})
        self.assertEqual(docloc.doc_dir(TID), self.tx)   # 読みは今までどおり
        self.assertEqual(docloc.doc_file(TID, ".json"), os.path.join(self.tx, TID + ".json"))
        for call in (lambda: docloc.doc_dir(TID, for_write=True), lambda: docloc.doc_file(TID, ".json", for_write=True),
                     lambda: docloc.doc_file(TID, ".words.json", for_write=True), lambda: docloc.hist_dir(TID, for_write=True),
                     lambda: docloc.bak_dir(TID, for_write=True), lambda: docloc.place_new(TID, None, self._writer())):
            with self.assertRaises(errors.ApiError) as cm:
                call()
            self.assertEqual((cm.exception.code, cm.exception.status, cm.exception.extra["reason"]), (docloc.UNSEEN_CODE, 503, "文書が無い"))
        self.assertFalse(os.path.exists(os.path.join(self.tx, TID + ".json")))   # TX_DIR に別の文書を作らない
        self._loc("{壊れた")
        with self.assertRaises(errors.ApiError):
            docloc.doc_file(TID, ".json", for_write=True)

    def test_for_write_follows_usable_index_or_tx_dir(self):
        self.assertEqual(docloc.doc_file(TID, ".json", for_write=True), os.path.join(self.tx, TID + ".json"))   # 索引なし = 今までどおり
        self._doc(self.case)
        docloc.place(TID, self.case)
        self.assertEqual(docloc.doc_file(TID, ".edit.json", for_write=True), os.path.join(os.path.normpath(self.case), TID + ".edit.json"))


if __name__ == "__main__":
    unittest.main()
