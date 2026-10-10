#!/usr/bin/env python3
"""文書を案件の 作業用 へ移す部品(src/manage/cases/docmove.py。RS8 B2-3)の確かめ。

    python -m unittest src/manage/cases/tests/test_docmove.py

一時フォルダに 編集の作業データ(transcripts)と書き出し先(案件のフォルダ)を作って流す(本物の作業データには触らない)。
"""
import json
import os
os.environ.setdefault("YTT_DATA_DIR", "inplace")
import shutil
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))))   # src
from manage.cases import docmove as M  # noqa: E402
from ytt import docloc, schemas, workdata  # noqa: E402

TID = "0123456789ab"
TID2 = "ba9876543210"
TID3 = "aaaaaaaaaaaa"


def write(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(obj if isinstance(obj, str) else json.dumps(obj, ensure_ascii=False))


def read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="docmove-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.data = os.path.join(self.tmp, "transcribe")
        self.tx = os.path.join(self.data, "transcripts")
        self.out = os.path.join(self.tmp, "exports")
        os.makedirs(self.tx)
        self.case = self.make_case("配信A", "vidA")
        self.work = os.path.join(self.case, schemas.WORK_DIR)
        self.logs = []

    def make_case(self, name, owner=None, case_json=False):
        root = os.path.join(self.out, name)
        os.makedirs(os.path.join(root, schemas.WORK_DIR))
        write(os.path.join(root, "clip.mp4"), "mp4")
        if owner:
            write(os.path.join(root, schemas.WORK_DIR, ".studio-id"), owner)
        if case_json:
            write(os.path.join(root, schemas.WORK_DIR, "case.json"), {"schema": "youtube-tools-case/v1", "id": "x"})
        return root

    def make_doc(self, tid=TID, case=None, vid="vidA", side=True, **extra):
        src = os.path.join(case or self.case, "clip.mp4")
        doc = dict({"id": tid, "title": "t", "sourcePath": src, "segments": [{"id": "s1", "start": 0, "end": 1, "text": "あ"}]}, **extra)
        if vid:
            doc["clip"] = {"source": {"videoId": vid}}
        write(os.path.join(self.tx, tid + ".json"), doc)
        if side:
            write(os.path.join(self.tx, tid + ".edit.json"), {"cuts": []})
            write(os.path.join(self.tx, docloc.HIST_DIR, tid, "1700000000.json"), {"old": 1})
            write(os.path.join(self.tx, docloc.BAK_DIR, tid + ".pre-relink.json"), {"bak": 1})
        return doc

    def run_move(self, **kw):
        kw.setdefault("backup_ok", True)
        return M.run(self.data, self.out, log=self.logs.append, **kw)

    def assert_moved(self, tid=TID, work=None, side=True):
        work = work or self.work
        self.assertEqual(docloc.placed(tid, self.data), os.path.normpath(work))
        self.assertTrue(os.path.isfile(os.path.join(work, tid + ".json")))
        self.assertFalse(os.path.exists(os.path.join(self.tx, tid + ".json")))
        mig = os.path.join(self.tx, M.MIGRATED_DIR)
        self.assertTrue(os.path.isfile(os.path.join(mig, tid + ".json")))
        if side:
            for rel in (tid + ".edit.json", os.path.join(docloc.HIST_DIR, tid, "1700000000.json"), os.path.join(docloc.BAK_DIR, tid + ".pre-relink.json")):
                self.assertTrue(os.path.isfile(os.path.join(work, rel)), rel)
                self.assertTrue(os.path.isfile(os.path.join(mig, rel)), rel)
                self.assertFalse(os.path.exists(os.path.join(self.tx, rel)), rel)
            self.assertFalse(os.path.exists(os.path.join(self.tx, docloc.HIST_DIR, tid)), "空の履歴のフォルダを残した")

    def parts(self):
        return [os.path.join(d, n) for d, _, fs in os.walk(self.out) for n in fs if M.PART_MARK in n]


class MoveTest(Base):
    def test_moves_doc_side_files_hist_bak(self):
        self.make_doc()
        r = self.run_move()
        self.assertEqual((r["state"], r["moved"], r["kept"], r["remaining"]), ("done", 1, {}, 0))
        self.assert_moved()
        self.assertEqual(docloc.doc_file(TID, ".edit.json", self.data), os.path.join(os.path.normpath(self.work), TID + ".edit.json"))
        self.assertEqual(M.read_result(self.data)["movedTotal"], 1)
        self.assertEqual(self.parts(), [])

    def test_case_json_without_owner_is_a_case(self):
        case = self.make_case("依頼B", case_json=True)
        self.make_doc(case=case, vid=None, side=False)   # clip の無い文書(open_video 由来)はパスの条件だけ
        self.assertEqual(self.run_move()["moved"], 1)
        self.assert_moved(work=os.path.join(case, schemas.WORK_DIR), side=False)

    def test_run_twice_is_same(self):
        self.make_doc()
        self.run_move()
        before = sorted(os.listdir(self.work))
        r = self.run_move()
        self.assertEqual((r["state"], r["moved"]), ("empty", 0))
        self.assertEqual(sorted(os.listdir(self.work)), before)
        self.assert_moved()

    def test_crash_before_retire_then_second_run_sends_leftovers(self):
        """索引を書いたあと・元を .migrated へ送る前に落ちた -> 次の起動で同じ中身なら .migrated へ"""
        self.make_doc()
        with mock.patch.object(M, "_retire", side_effect=OSError("落ちた")):
            r = self.run_move()
        self.assertEqual(r["kept"], {"error": 1})
        self.assertTrue(os.path.isfile(os.path.join(self.tx, TID + ".json")))
        self.assertTrue(docloc.placed(TID, self.data))
        r = self.run_move()
        self.assertEqual((r["cleaned"], r["kept"]), (1, {}))
        self.assert_moved()

    def test_leftover_with_other_content_stays(self):
        self.make_doc()
        with mock.patch.object(M, "_retire", side_effect=OSError("落ちた")):
            self.run_move()
        write(os.path.join(self.tx, TID + ".json"), {"id": TID, "changed": True})
        r = self.run_move()
        self.assertEqual(r["kept"], {"leftover": 1})
        self.assertIn('"changed"', read(os.path.join(self.tx, TID + ".json")))
        self.assertTrue(os.path.isfile(os.path.join(self.tx, M.MIGRATED_DIR, TID + ".edit.json")), "同じ中身の横のファイルは送る")

    def test_crash_during_rename_cleans_parts_and_retries(self):
        self.make_doc()
        calls = []
        real = M._rename_new

        def flaky(src, dst):
            calls.append(dst)
            if len(calls) == 2:
                raise OSError("落ちた")
            real(src, dst)
        with mock.patch.object(M, "_rename_new", flaky):
            r = self.run_move()
        self.assertEqual(r["kept"], {"error": 1})
        self.assertEqual(self.parts(), [])
        self.assertIsNone(docloc.placed(TID, self.data))
        self.assertTrue(os.path.isfile(os.path.join(self.tx, TID + ".json")), "元は残る")
        r = self.run_move()   # 先に改名できた物は同じ中身 = 飛ばして先へ
        self.assertEqual(r["moved"], 1)
        self.assert_moved()

    def test_stale_parts_are_removed(self):
        self.make_doc()
        stale = os.path.join(self.work, TID + ".json" + M.PART_MARK + "999")
        write(stale, "途中")
        write(os.path.join(self.work, docloc.HIST_DIR, TID, "x.json.part-999"), "途中")
        self.run_move()
        self.assertEqual(self.parts(), [])
        self.assert_moved()

    def test_copy_mismatch_leaves_original(self):
        self.make_doc()
        with mock.patch.object(M, "_same", side_effect=lambda a, b: M.PART_MARK not in b and os.path.isfile(b) and read(a) == read(b)):
            r = self.run_move()
        self.assertEqual(r["kept"], {"error": 1})
        self.assertEqual(self.parts(), [])
        self.assertTrue(os.path.isfile(os.path.join(self.tx, TID + ".json")))
        self.assertIsNone(docloc.placed(TID, self.data))

    def test_same_name_same_content_in_work_is_skipped(self):
        self.make_doc()
        shutil.copy2(os.path.join(self.tx, TID + ".edit.json"), os.path.join(self.work, TID + ".edit.json"))
        self.assertEqual(self.run_move()["moved"], 1)
        self.assert_moved()

    def test_same_name_other_content_in_work_is_kept(self):
        self.make_doc()
        write(os.path.join(self.work, TID + ".edit.json"), {"other": 1})
        before = sorted(os.listdir(self.work))
        r = self.run_move()
        self.assertEqual(r["kept"], {"conflict": 1})
        self.assertEqual(sorted(os.listdir(self.work)), before, "ぶつかったら何も写さない")
        self.assertTrue(os.path.isfile(os.path.join(self.tx, TID + ".json")))
        self.assertIn('"other"', read(os.path.join(self.work, TID + ".edit.json")))

    def test_migrated_collision(self):
        """.migrated に同じ名前: 同じ中身なら上書き・違えば <名前>.<時刻>"""
        self.make_doc()
        mig = os.path.join(self.tx, M.MIGRATED_DIR)
        shutil.copy2(os.path.join(self.tx, TID + ".json"), os.path.join(self.tmp, "same.json"))
        write(os.path.join(mig, TID + ".json"), read(os.path.join(self.tmp, "same.json")))
        write(os.path.join(mig, TID + ".edit.json"), {"older": 1})
        self.run_move()
        names = sorted(os.listdir(mig))
        self.assertEqual(len([n for n in names if n.startswith(TID + ".json")]), 1)
        self.assertIn('"older"', read(os.path.join(mig, TID + ".edit.json")))
        stamped = [n for n in names if n.startswith(TID + ".edit.json.")]
        self.assertEqual(len(stamped), 1)
        self.assertIn('"cuts"', read(os.path.join(mig, stamped[0])))


class KeepTest(Base):
    def kept(self, **kw):
        r = self.run_move(**kw)
        self.assertEqual(r["moved"], 0)
        self.assertTrue(os.path.isfile(os.path.join(self.tx, TID + ".json")))
        self.assertIsNone(docloc.placed(TID, self.data))
        return r["kept"]

    def test_eval_flag(self):
        self.make_doc(evalSet=True)
        self.assertEqual(self.kept(), {"eval": 1})

    def test_eval_dir_from_settings(self):
        self.make_doc()
        write(os.path.join(self.data, "settings.json"), {"evalDirs": [self.case]})
        # 入口の起動のとき = 編集の作業データがまだ決まっていない(workdata.SETTINGS が None)= doc_home が datadir の transcribe の設定を読む
        with mock.patch.object(workdata, "SETTINGS", None), mock.patch.object(M._datadir, "resolve", return_value=self.data):
            self.assertEqual(self.kept(), {"noHome": 1})

    def test_no_source(self):
        self.make_doc()
        write(os.path.join(self.tx, TID + ".json"), {"id": TID})
        self.assertEqual(self.kept(), {"noSource": 1})

    def test_unreadable(self):
        write(os.path.join(self.tx, TID + ".json"), "{壊れた")
        self.assertEqual(self.kept(), {"unreadable": 1})

    def test_outside_out_dir(self):
        other = os.path.join(self.tmp, "desktop", "x")
        os.makedirs(os.path.join(other, schemas.WORK_DIR))
        write(os.path.join(other, schemas.WORK_DIR, ".studio-id"), "vidA")
        write(os.path.join(other, "clip.mp4"), "mp4")
        self.make_doc(case=other)
        self.assertEqual(self.kept(), {"noHome": 1})

    def test_not_a_case(self):
        case = os.path.join(self.out, "ただのフォルダ")
        os.makedirs(case)
        write(os.path.join(case, "clip.mp4"), "mp4")
        self.make_doc(case=case)
        self.assertEqual(self.kept(), {"noHome": 1})

    def test_video_missing(self):
        self.make_doc()
        os.remove(os.path.join(self.case, "clip.mp4"))
        self.assertEqual(self.kept(), {"noHome": 1})

    def test_not_fixed_drive(self):
        self.make_doc()
        with mock.patch.object(M._fsio, "is_fixed_drive", return_value=False):
            self.assertEqual(self.kept(), {"noHome": 1})

    def test_owner_mismatch(self):
        self.make_doc(vid="vidOther")
        self.assertEqual(self.kept(), {"owner": 1})
        self.assertTrue(any("持ち主" in x for x in self.logs))

    def test_wait_backup(self):
        self.make_doc()
        r = self.run_move(backup_ok=False)
        self.assertEqual(r["state"], "waitBackup")
        self.assertIsNone(docloc.placed(TID, self.data))
        self.assertFalse(os.path.exists(M.result_path(self.data)), "移していないのに結果を書いた")
        self.assertTrue(any("バックアップ" in x for x in self.logs))
        st = M.status(self.data, r)
        self.assertEqual(st["state"], "waitBackup")

    def test_unseen_index(self):
        self.make_doc()
        write(docloc.loc_path(TID, self.data), {"version": 1, "id": TID, "dir": os.path.join(self.tmp, "外れた", schemas.WORK_DIR)})
        self.assertEqual(self.kept(), {"unseen": 1})
        u = M.status(self.data)["unseen"]
        self.assertEqual((u["count"], sum(u["reasons"].values())), (1, 1))   # 理由の文は docloc.unseen の持ち物


class BudgetTest(Base):
    def setUp(self):
        super().setUp()
        for t in (TID, TID2, TID3):
            self.make_doc(t, side=False)

    def test_doc_budget_then_next_start(self):
        r = self.run_move(budget_docs=2)
        self.assertEqual((r["state"], r["moved"], r["remaining"]), ("partial", 2, 1))
        r = self.run_move(budget_docs=2)
        self.assertEqual((r["state"], r["moved"], r["remaining"]), ("done", 1, 0))
        self.assertEqual(M.read_result(self.data)["movedTotal"], 3)
        for t in (TID, TID2, TID3):
            self.assertTrue(docloc.placed(t, self.data))

    def test_time_budget(self):
        ticks = iter([0, 0, 30, 30, 30])   # 始め・1 本目の前・2 本目の前(予算を過ぎた)・終わり
        r = self.run_move(clock=lambda: next(ticks))
        self.assertEqual((r["moved"], r["remaining"]), (1, 2))


class BackTest(Base):
    def test_back_then_paused_then_resume(self):
        self.make_doc()
        self.run_move()
        with open(os.path.join(self.work, TID + ".json"), "a", encoding="utf-8") as f:
            f.write(" ")   # 移したあとに直した
        dry = M.back(self.data, dry_run=True, log=self.logs.append)
        self.assertEqual(dry["back"], 1)
        self.assertTrue(docloc.placed(TID, self.data), "dry-run で変えた")
        self.assertFalse(M.read_result(self.data).get("paused"))
        r = M.back(self.data, log=self.logs.append)
        self.assertEqual((r["back"], r["kept"]), (1, {}))
        self.assertIsNone(docloc.placed(TID, self.data))
        self.assertTrue(read(os.path.join(self.tx, TID + ".json")).endswith(" "), "直した中身が戻らない")
        self.assertTrue(os.path.isfile(os.path.join(self.tx, docloc.HIST_DIR, TID, "1700000000.json")))
        self.assertTrue(os.path.isfile(os.path.join(self.work, TID + ".json")), "作業用の写しは残す")
        self.assertEqual(self.run_move()["state"], "paused")
        self.assertEqual(M.status(self.data)["state"], "paused")
        M.set_paused(self.data, False)
        self.assertEqual(self.run_move()["state"], "done")

    def test_back_does_not_overwrite(self):
        self.make_doc()
        self.run_move()
        write(os.path.join(self.tx, TID + ".edit.json"), {"newer": 1})
        r = M.back(self.data, log=self.logs.append)
        self.assertEqual((r["back"], r["kept"]), (0, {"conflict": 1}))
        self.assertTrue(docloc.placed(TID, self.data))
        self.assertIn('"newer"', read(os.path.join(self.tx, TID + ".edit.json")))


class StatusAndCliTest(Base):
    def test_status_none_when_nothing(self):
        self.assertIsNone(M.status(self.data))

    def test_status_off_switch(self):
        """入口のスイッチ docMove がオフ(move_docs が {"state": "off"})= 移した記録が無くても「止めています」の行を出す"""
        self.assertEqual(M.status(self.data, {"state": "off", "moved": 0})["state"], "off")
        M.set_paused(self.data, True)
        self.assertEqual(M.status(self.data, {"state": "off"})["state"], "off")
        self.assertEqual(M.status(self.data)["state"], "paused")

    def test_status_after_move(self):
        self.make_doc()
        self.make_doc(TID2, vid="other", side=False)
        last = self.run_move()
        st = M.status(self.data, last)
        self.assertEqual((st["state"], st["moved"], st["movedNow"], st["kept"]), ("done", 1, 1, {"owner": 1}))
        self.assertIn("owner", st["reasons"])

    def test_backup_done(self):
        self.assertFalse(M.backup_done({}))
        self.assertFalse(M.backup_done({"ok": True}))
        self.assertTrue(M.backup_done({"ok": 1700000000.5}))

    def cli(self, argv, answer="n"):
        with mock.patch.object(M._datadir, "resolve", return_value=self.data), \
                mock.patch.object(M._placement, "acquire", return_value=object()), mock.patch.object(M._placement, "release"), \
                mock.patch.object(M._datadir, "studio_out_dir", return_value=self.out), mock.patch("builtins.print"):
            return M.main(argv, ask=lambda prompt: answer)

    def test_cli_purge_migrated_asks(self):
        self.make_doc()
        self.run_move()
        mig = os.path.join(self.tx, M.MIGRATED_DIR)
        self.assertEqual(self.cli(["--purge-migrated"], "n"), 0)
        self.assertTrue(os.path.isdir(mig))
        self.assertEqual(self.cli(["--purge-migrated"], "y"), 0)
        self.assertFalse(os.path.exists(mig))
        self.assert_moved_still()

    def assert_moved_still(self):
        self.assertTrue(docloc.placed(TID, self.data))

    def test_cli_now_and_back_and_resume(self):
        self.make_doc()
        self.assertEqual(self.cli(["--now"], "n"), 0)
        self.assertIsNone(docloc.placed(TID, self.data))
        self.assertEqual(self.cli(["--now"], "y"), 0)
        self.assertTrue(docloc.placed(TID, self.data))
        self.assertEqual(self.cli(["--back"]), 0)
        self.assertTrue(M.read_result(self.data)["paused"])
        self.assertEqual(self.cli(["--now"], "y"), 1, "止めてあるのに流した")
        self.assertEqual(self.cli(["--resume"]), 0)
        self.assertFalse(M.read_result(self.data)["paused"])

    def test_cli_lock_busy(self):
        busy = M._placement.LockBusy({"pid": 1, "port": 8700})
        with mock.patch.object(M._datadir, "resolve", return_value=self.data), \
                mock.patch.object(M._placement, "acquire", side_effect=busy), mock.patch("builtins.print"):
            self.assertEqual(M.main(["--resume"]), 4)


if __name__ == "__main__":
    unittest.main()
