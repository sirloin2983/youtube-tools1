#!/usr/bin/env python3
"""data.json の配信と cases.json の状態を案件へ移す部品(src/manage/cases/markmove.py。RS8 B3-8)の確かめ。

    python -m unittest src/manage/cases/tests/test_markmove.py

一時フォルダにスタジオの作業データ(data.json)・入口の cases.json・書き出し先(案件のフォルダ)を作って流す(本物の作業データには触らない)。
前からある配信は、スタジオの Store で書き出し(案件にする所 casebook.case_of を None にして data.json の全部の形のまま)を作る。
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
from flow import casebook  # noqa: E402
from human.review import store  # noqa: E402
from manage.cases import cases as cases_mod, markmove as M  # noqa: E402
from ytt import casefiles, names, schemas, studio_env  # noqa: E402
from ytt.errors import ApiError  # noqa: E402

YT = {"kind": "youtube", "videoId": "abcdefghijk", "name": "abcdefghijk"}
YT2 = {"kind": "youtube", "videoId": "bbbbbbbbbbb", "name": "bbbbbbbbbbb"}


def read_json(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def rb(path):
    with open(path, "rb") as f:
        return f.read()


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="markmove-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        studio_env.set_home(os.path.join(self.tmp, "studio"))
        self.data = os.path.join(self.tmp, "studio", "data.json")
        self.cases = os.path.join(self.tmp, "app", "cases.json")
        self.out = os.path.join(self.tmp, "out")
        self.root = os.path.join(self.out, "題")
        os.makedirs(os.path.join(self.root, schemas.WORK_DIR))
        names.write_owner(self.root, YT["videoId"])
        p = mock.patch.object(casebook._fsio, "is_fixed_drive", return_value=True)
        p.start()
        self.addCleanup(p.stop)
        self.st = store.Store(self.data)
        self.logs = []

    def old_video(self, src=YT, root=None, marks=(("m1", 10, 40, "01.mp4"), ("m2", 100, 130, None)), title="t"):
        """前からある配信(書き出したマークがあるが data.json の全部の形)を作る -> 配信の id"""
        vid = src["videoId"]
        self.st.ensure(src, title, "ch")
        ms = [{"id": mid, "start": s, "end": e, "status": "adopted"} for mid, s, e, _ in marks]
        self.st.put_video(vid, title, ms, self.st.get(vid)[0]["rev"])
        with mock.patch.object(casebook, "case_of", return_value=None):   # 初めての書き出しで案件にしない = 前からある形
            for mid, s, e, name in marks:
                if name:
                    folder = root or self.root
                    path = os.path.join(folder, name)
                    with open(path, "wb") as f:
                        f.write(b"x")
                    self.assertTrue(self.st.mark_exported(vid, mid, os.path.basename(folder) + "/" + name, s, e, path))
        self.assertNotIn("case", self.row(vid))
        return vid

    def row(self, vid):
        return read_json(self.data)["videos"][vid]

    def save_case_row(self, vid, **rec):
        os.makedirs(os.path.dirname(self.cases), exist_ok=True)
        saved = cases_mod.load_saved(self.cases)
        saved[vid] = dict(rec, last={"title": "前の"})
        with open(self.cases, "w", encoding="utf-8") as f:
            json.dump({"schema": cases_mod.SCHEMA, "cases": saved}, f, ensure_ascii=False)

    def run_move(self, **kw):
        kw.setdefault("backup_ok", True)
        kw.setdefault("out_dir", self.out)
        return M.run(self.data, self.cases, log=self.logs.append, **kw)

    def full(self, vid):
        """スタジオを起動し直したときの配信 1 本(公開の形)"""
        return store.Store(self.data).get(vid)[0]

    def parts(self):
        return [os.path.join(d, n) for d, _, fs in os.walk(self.out) for n in fs if M.PART_MARK in n]


class MoveTest(Base):
    def test_moves_video_and_case_fields(self):
        vid = self.old_video()
        before = self.full(vid)
        self.save_case_row(vid, status="working", memo="メモ", statusUpdatedAt=1700000000000, auto={"m1": {"seenAt": 1}})
        r = self.run_move()
        self.assertEqual((r["state"], r["moved"], r["kept"], r["remaining"]), ("done", 1, {}, 0))
        row = self.row(vid)
        self.assertEqual(row["case"], os.path.normpath(self.root))
        self.assertNotIn("marks", row)
        self.assertEqual(self.full(vid), before)   # スタジオから見た配信は同じ
        cands, adopts = casefiles.read(self.root)
        self.assertEqual([m["id"] for m in adopts["marks"]], ["m1", "m2"])
        self.assertEqual(next(m for m in adopts["marks"] if m["id"] == "m1")["path"], "01.mp4")   # 根からの相対
        self.assertEqual((adopts["status"], adopts["memo"], adopts["statusUpdatedAt"], adopts["auto"]),
                         ("working", "メモ", 1700000000000, {"m1": {"seenAt": 1}}))
        self.assertNotIn(vid, cases_mod.load_saved(self.cases), "cases.json の行は 採用.json へ移したら消す")
        self.assertTrue(os.path.isfile(self.data + M.PRE_SUFFIX))
        self.assertIn('"m1"', rb(self.data + M.PRE_SUFFIX).decode("utf-8"))
        self.assertTrue(os.path.isfile(self.cases + M.PRE_SUFFIX))
        self.assertEqual(self.parts(), [])

    def test_video_without_export_is_not_a_target(self):
        self.st.ensure(YT2, "まだ", "ch")
        vid = self.old_video()
        r = self.run_move()
        self.assertEqual((r["moved"], r["kept"]), (1, {}))
        self.assertNotIn("case", self.row(YT2["videoId"]))
        self.assertIn("case", self.row(vid))

    def test_run_twice_is_same(self):
        vid = self.old_video()
        self.run_move()
        work = os.path.join(self.root, schemas.WORK_DIR)
        before = {n: rb(os.path.join(work, n)) for n in os.listdir(work)}
        data_before = rb(self.data)
        r = self.run_move()
        self.assertEqual((r["state"], r["moved"]), ("empty", 0))
        self.assertEqual({n: rb(os.path.join(work, n)) for n in os.listdir(work)}, before)
        self.assertEqual(rb(self.data), data_before)
        self.assertEqual(M.read_result(self.data)["movedTotal"], 1)
        self.assertIn("case", self.row(vid))

    def test_crash_while_renaming_leaves_data_json(self):
        """採用.json へ改名する所で落ちた -> 書きかけは消え、data.json は全部の形のまま・次の起動で移る"""
        vid = self.old_video()
        real, calls = M._fsio.replace_retry, []

        def flaky(src, dst):
            calls.append(dst)
            if dst.endswith(casefiles.ADOPTIONS_NAME):
                raise OSError("落ちた")
            real(src, dst)
        with mock.patch.object(M._fsio, "replace_retry", flaky):
            r = self.run_move()
        self.assertEqual(r["kept"], {"error": 1})
        self.assertEqual(self.parts(), [])
        self.assertNotIn("case", self.row(vid))
        self.assertIsNone(casefiles.merge(*casefiles.read(self.root), vid, self.root), "採用.json に入る前は案件に配信が見えない")
        r = self.run_move()
        self.assertEqual(r["moved"], 1)
        self.assertIn("case", self.row(vid))

    def test_crash_before_data_json(self):
        """案件のファイルを書いたあと data.json を書く前に落ちた -> 次の起動は書かずに索引の行にする・cases.json の行も消す"""
        vid = self.old_video()
        before = self.full(vid)
        self.save_case_row(vid, status="posted")
        with mock.patch.object(M, "_write_data", side_effect=OSError("落ちた")):
            with self.assertRaises(OSError):
                self.run_move()
        self.assertNotIn("case", self.row(vid))
        self.assertIn(vid, cases_mod.load_saved(self.cases))
        r = self.run_move()
        self.assertEqual((r["moved"], r["kept"]), (1, {}))
        self.assertEqual(self.full(vid), before)
        self.assertNotIn(vid, cases_mod.load_saved(self.cases))
        self.assertEqual(casefiles.read(self.root)[1]["status"], "posted")

    def test_stale_parts_are_removed(self):
        self.old_video()
        stale = casefiles.work_path(self.root, casefiles.ADOPTIONS_NAME) + M.PART_MARK + "999"
        with open(stale, "w", encoding="utf-8") as f:
            f.write("途中")
        self.run_move()
        self.assertEqual(self.parts(), [])

    def test_existing_case_keeps_other_source_and_fields(self):
        """同じ案件に先に入っていた配信(録画など)と、上の段の状態は引き継ぐ。cases.json の行は残す(上の段が既にある)"""
        other = self.old_video(YT2, marks=(("o1", 5, 9, "02.mp4"),))
        names.write_owner(self.root, YT2["videoId"])
        self.assertEqual(self.run_move()["moved"], 1)
        names.write_owner(self.root, YT["videoId"])
        _c, a = casefiles.read(self.root)
        casebook.write(self.root, adoptions=dict(a, status="working"))
        vid = self.old_video()
        self.save_case_row(vid, status="skipped")
        self.assertEqual(self.run_move()["moved"], 1)
        _c, a = casefiles.read(self.root)
        self.assertEqual(set(a["sources"]), {vid, other})
        self.assertEqual(a["status"], "working")
        self.assertIn(vid, cases_mod.load_saved(self.cases))
        self.assertTrue(any("cases.json の行は残します" in x for x in self.logs))
        self.assertTrue(os.path.isfile(casefiles.work_path(self.root, casefiles.ADOPTIONS_NAME) + ".bak"))


class KeepTest(Base):
    def kept(self, vid, **kw):
        r = self.run_move(**kw)
        self.assertEqual(r["moved"], 0)
        self.assertNotIn("case", self.row(vid))
        return r["kept"]

    def test_mismatch_is_kept(self):
        vid = self.old_video()
        with mock.patch.object(M, "_same_video", return_value=False):
            self.assertEqual(self.kept(vid), {"verify": 1})
        self.assertFalse(os.path.exists(casefiles.work_path(self.root, casefiles.ADOPTIONS_NAME)))

    def test_two_folders(self):
        """題が変わって書き出したフォルダが 2 つに割れた配信は移さない"""
        other = os.path.join(self.out, "新しい題")
        os.makedirs(os.path.join(other, schemas.WORK_DIR))
        names.write_owner(other, YT["videoId"])
        vid = self.old_video()
        with mock.patch.object(casebook, "case_of", return_value=None):
            m2 = next(m for m in self.st.get(vid)[0]["marks"] if m["id"] == "m2")
            path = os.path.join(other, "02.mp4")
            open(path, "wb").close()
            self.st.mark_exported(vid, "m2", "新しい題/02.mp4", m2["start"], m2["end"], path)
        self.assertEqual(self.kept(vid), {"multi": 1})

    def test_owner_and_outside_and_missing(self):
        vid = self.old_video()
        names.write_owner(self.root, "someone-else")
        self.assertEqual(self.kept(vid), {"owner": 1})
        self.assertEqual(self.kept(vid, out_dir=os.path.join(self.tmp, "ほか")), {"outside": 1})
        shutil.rmtree(self.root)
        self.assertEqual(self.kept(vid), {"missing": 1})

    def test_not_fixed_drive(self):
        vid = self.old_video()
        with mock.patch.object(casebook._fsio, "is_fixed_drive", return_value=False):
            self.assertEqual(self.kept(vid), {"outDir": 1})

    def test_case_has_other_record(self):
        vid = self.old_video()
        v = store.Store._load_video(vid, self.row(vid))
        casebook.write(self.root, *casebook.split(dict(v, title="違う"), self.root))
        self.assertEqual(self.kept(vid), {"caseHas": 1})
        self.assertEqual(casefiles.read(self.root)[1]["sources"][vid]["title"], "違う", "人の記録を上書きした")

    def test_broken_adoptions(self):
        vid = self.old_video()
        with open(casefiles.work_path(self.root, casefiles.ADOPTIONS_NAME), "w", encoding="utf-8") as f:
            f.write("{壊れた")
        self.assertEqual(self.kept(vid), {"caseBroken": 1})

    def test_wait_backup(self):
        vid = self.old_video()
        r = self.run_move(backup_ok=False)
        self.assertEqual(r["state"], "waitBackup")
        self.assertNotIn("case", self.row(vid))
        self.assertFalse(os.path.exists(self.data + M.PRE_SUFFIX))
        self.assertFalse(os.path.exists(M.result_path(self.data)))
        self.assertEqual(M.status(self.data, r)["state"], "waitBackup")

    def test_dry_run_writes_nothing(self):
        vid = self.old_video()
        before = rb(self.data)
        r = self.run_move(dry_run=True)
        self.assertEqual((r["moved"], r["dryRun"]), (1, True))
        self.assertEqual(rb(self.data), before)
        self.assertFalse(os.path.exists(casefiles.work_path(self.root, casefiles.ADOPTIONS_NAME)))
        self.assertFalse(os.path.exists(M.result_path(self.data)))
        self.assertNotIn("case", self.row(vid))


class BudgetTest(Base):
    def test_video_budget_then_next_start(self):
        a = self.old_video()
        root2 = os.path.join(self.out, "題2")
        os.makedirs(os.path.join(root2, schemas.WORK_DIR))
        names.write_owner(root2, YT2["videoId"])
        b = self.old_video(YT2, root=root2, marks=(("o1", 5, 9, "02.mp4"),))
        r = self.run_move(budget_videos=1)
        self.assertEqual((r["state"], r["moved"], r["remaining"]), ("partial", 1, 1))
        r = self.run_move(budget_videos=1)
        self.assertEqual((r["state"], r["moved"]), ("done", 1))
        self.assertEqual(M.read_result(self.data)["movedTotal"], 2)
        self.assertTrue(all("case" in self.row(x) for x in (a, b)))


class BackTest(Base):
    def test_back_then_paused_then_resume(self):
        vid = self.old_video()
        before = self.full(vid)
        self.save_case_row(vid, status="working", memo="m")
        self.run_move()
        r = M.back(self.data, self.cases, log=self.logs.append)
        self.assertEqual((r["back"], r["kept"]), (1, {}))
        self.assertNotIn("case", self.row(vid))
        self.assertEqual(self.full(vid), before)
        self.assertEqual({k: cases_mod.load_saved(self.cases)[vid][k] for k in ("status", "memo")}, {"status": "working", "memo": "m"})
        self.assertTrue(os.path.isfile(casefiles.work_path(self.root, casefiles.ADOPTIONS_NAME)), "案件のファイルは残す")
        self.assertEqual(self.run_move()["state"], "paused")
        self.assertEqual(M.status(self.data)["state"], "paused")
        # 戻したあとスタジオで直した配信も、再開すると今の data.json の形で案件へ(戻した配信 = backed は上書きしてよい)
        self.st = store.Store(self.data)
        self.st.put_video(vid, "直した題", self.st.get(vid)[0]["marks"], self.st.get(vid)[0]["rev"])
        M.set_paused(self.data, False)
        r = self.run_move()
        self.assertEqual((r["moved"], r["kept"]), (1, {}))
        self.assertEqual(self.full(vid)["title"], "直した題")
        self.assertEqual(M.read_result(self.data)["backed"], {})

    def test_back_skips_unseen_case(self):
        vid = self.old_video()
        self.run_move()
        shutil.move(self.root, self.root + "_動かした")
        r = M.back(self.data, self.cases, log=self.logs.append)
        self.assertEqual((r["back"], r["kept"]), (0, {"unseen": 1}))
        self.assertIn("case", self.row(vid))


class RelinkTest(Base):
    def setUp(self):
        super().setUp()
        self.vid = self.old_video()
        self.before = self.full(self.vid)
        self.run_move()

    def test_relink_by_command(self):
        moved = os.path.join(self.tmp, "動かした先")
        shutil.move(self.root, moved)
        with self.assertRaises(ApiError) as cm:
            store.Store(self.data).get(self.vid)
        self.assertEqual(cm.exception.status, 503)
        self.assertEqual(M.status(self.data)["unseen"], 1)
        wrong = os.path.join(self.tmp, "ちがう")
        os.makedirs(os.path.join(wrong, schemas.WORK_DIR))
        names.write_owner(wrong, "someone-else")
        self.assertIn("持ち主", M.relink(self.data, self.vid, wrong, log=self.logs.append))
        self.assertIn("案件にした配信", M.relink(self.data, "nonexistent00", moved, log=self.logs.append))
        self.assertIsNone(M.relink(self.data, self.vid, moved, log=self.logs.append))
        self.assertEqual(self.row(self.vid)["case"], os.path.normpath(moved))
        got = self.full(self.vid)
        self.assertEqual([m["id"] for m in got["marks"]], [m["id"] for m in self.before["marks"]])
        self.assertEqual(store.Store(self.data).internal(self.vid)["marks"][0]["path"], os.path.join(os.path.normpath(moved), "01.mp4"))
        self.assertEqual(M.status(self.data)["unseen"], 0)

    def test_relink_needs_source_in_adoptions(self):
        other = os.path.join(self.tmp, "持ち主だけ")
        os.makedirs(os.path.join(other, schemas.WORK_DIR))
        names.write_owner(other, YT["videoId"])
        self.assertIn("採用.json", M.relink(self.data, self.vid, other, log=self.logs.append))

    def test_out_dir_change_relinks_same_relative_path(self):
        M.relink_out_dir(self.data, self.out, log=self.logs.append)   # 起動のたびに今の書き出し先を覚える
        self.assertEqual(M.read_result(self.data)["outDirs"], [os.path.normpath(self.out)])
        new_out = os.path.join(self.tmp, "新しい書き出し先")
        shutil.move(self.out, new_out)
        self.assertEqual(M.relink_out_dir(self.data, new_out, log=self.logs.append), 1)
        self.assertEqual(self.row(self.vid)["case"], os.path.join(os.path.normpath(new_out), "題"))
        self.assertEqual(self.full(self.vid)["marks"][0]["path"], os.path.join(os.path.normpath(new_out), "題", "01.mp4"))
        self.assertEqual(M.read_result(self.data)["outDirs"][:2], [os.path.normpath(new_out), os.path.normpath(self.out)])
        self.assertEqual(M.status(self.data)["relinked"], 1)
        self.assertEqual(M.relink_out_dir(self.data, new_out, log=self.logs.append), 0)   # 2 回目は何もしない

    def test_out_dir_change_does_not_search_by_title(self):
        """相対パスが違う(題でフォルダ名が変わった)なら繋ぎ直さない・見えている案件は触らない"""
        M.relink_out_dir(self.data, self.out)
        new_out = os.path.join(self.tmp, "新しい書き出し先")
        os.makedirs(new_out)
        shutil.move(self.root, os.path.join(new_out, "別の題"))
        self.assertEqual(M.relink_out_dir(self.data, new_out), 0)
        self.assertEqual(self.row(self.vid)["case"], os.path.normpath(self.root))


class StatusAndCliTest(Base):
    def test_status_none_when_nothing(self):
        self.assertIsNone(M.status(self.data))

    def test_status_off_switch(self):
        self.assertEqual(M.status(self.data, {"state": "off", "moved": 0})["state"], "off")

    def test_status_after_move(self):
        self.old_video()
        last = self.run_move()
        st = M.status(self.data, last)
        self.assertEqual((st["state"], st["moved"], st["movedNow"], st["unseen"]), ("done", 1, 1, 0))
        self.assertIn("multi", st["reasons"])

    def cli(self, argv, answer="n"):
        with mock.patch.object(M._placement, "studio_data", return_value=self.data), \
                mock.patch.object(M._cases, "locations", return_value={"cases": self.cases}), \
                mock.patch.object(M._placement, "acquire", return_value=object()), mock.patch.object(M._placement, "release"), \
                mock.patch.object(M._datadir, "studio_out_dir", return_value=self.out), mock.patch("builtins.print"):
            return M.main(argv, ask=lambda prompt: answer)

    def test_cli_now_back_resume_relink(self):
        vid = self.old_video()
        self.assertEqual(self.cli(["--now", "--dry-run"]), 0)
        self.assertNotIn("case", self.row(vid))
        self.assertEqual(self.cli(["--now"], "n"), 0)
        self.assertNotIn("case", self.row(vid))
        self.assertEqual(self.cli(["--now"], "y"), 0)
        self.assertIn("case", self.row(vid))
        moved = os.path.join(self.tmp, "動かした先")
        shutil.move(self.root, moved)
        self.assertEqual(self.cli(["--relink", vid, os.path.join(self.tmp, "無い")]), 1)
        self.assertEqual(self.cli(["--relink", vid, moved]), 0)
        self.assertEqual(self.row(vid)["case"], os.path.normpath(moved))
        self.assertEqual(self.cli(["--back"]), 0)
        self.assertTrue(M.read_result(self.data)["paused"])
        self.assertEqual(self.cli(["--now"], "y"), 1, "止めてあるのに流した")
        self.assertEqual(self.cli(["--resume"]), 0)
        self.assertFalse(M.read_result(self.data)["paused"])

    def test_cli_lock_busy(self):
        busy = M._placement.LockBusy({"pid": 1, "port": 8700})
        with mock.patch.object(M._placement, "acquire", side_effect=busy), mock.patch("builtins.print"):
            self.assertEqual(M.main(["--resume"]), 4)


if __name__ == "__main__":
    unittest.main()
