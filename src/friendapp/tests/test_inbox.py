"""src/friendapp/inbox.py のテスト(受信箱の記録・決める・3 日の片付け・画面へ出す形)。リポジトリ直下で: py -3.10 -m unittest src/friendapp/tests/test_inbox.py"""
import datetime
import json
import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

os.environ.setdefault("YTT_DATA_DIR", "inplace")
SRC = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if SRC not in sys.path:
    sys.path.insert(0, SRC)
from friendapp import inbox  # noqa: E402

T0 = 1750000000.0          # 基準の時刻(秒)
DAY_MS = 86400 * 1000
RID = "20250615-120000-aaaaaa"
RID2 = "20250615-120100-bbbbbb"


class Clock:
    """時計(秒)。テストが t を書き換えて進める"""

    def __init__(self, t):
        self.t = t

    def __call__(self):
        return self.t


def day_of(t):
    return datetime.datetime.fromtimestamp(t).strftime("%Y%m%d")


class InboxTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="inbox-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.path = os.path.join(self.tmp, "friend", "inbox.json")
        self.outbox = os.path.join(self.tmp, "outbox")
        self.save = os.path.join(self.tmp, "save")
        self.cases = os.path.join(self.tmp, "cases")
        self.clock = Clock(T0)
        self.box = self.new_box()

    def new_box(self):
        return inbox.Inbox(self.path, self.outbox, lambda: self.save, lambda: self.cases, clock=self.clock)

    def make_case(self, rid, names):
        """案件フォルダ(一時保管の中)とその中のパックのフォルダを作る -> (案件, [パックのフォルダ])"""
        case = os.path.join(self.cases, "案件-" + rid)
        dirs = []
        for n in names:
            d = os.path.join(case, "パック", n)
            os.makedirs(d)
            with open(os.path.join(d, "clip.mp4"), "wb") as f:
                f.write(b"x")
            dirs.append(d)
        return case, dirs

    def arrive(self, rid, names, batch=5, run_id=None):
        """送った行を足して届いた状態にする -> (行, 案件, パックのフォルダ)"""
        run_id = run_id or "run-" + rid
        self.box.add(rid, {"url": "u", "videoId": "dQw4w9WgXcQ"}, {"url": "u", "videoId": "dQw4w9WgXcQ", "title": "題"}, run_id=run_id)
        case, dirs = self.make_case(rid, names)
        r = self.box.finished(run_id, "done", "", [{"dir": d, "seconds": 10.5} for d in dirs], batch, case=case)
        return r, case, dirs

    def failed_row(self, rid, state="cancelled", error=""):
        run_id = "run-" + rid
        self.box.add(rid, {"url": "u"}, {"url": "u", "videoId": "x", "title": "", "channel": ""}, run_id=run_id)
        return self.box.finished(run_id, state, error, [], 5)

    def verdict_path(self, rid, name):
        return os.path.join(self.outbox, "%s__%s.verdict.json" % (rid, name))

    def read_verdict(self, rid, name):
        with open(self.verdict_path(rid, name), encoding="utf-8") as f:
            return json.load(f)

    # ------------------------------------------------------------ 名前・形
    def test_pack_name_and_title(self):
        self.assertEqual(inbox.pack_name(os.path.join("a", "b", "題名_pack")), "題名_pack")
        self.assertEqual(inbox.pack_name("a*b?c.zip"), "a_b_c.zip")
        self.assertEqual(inbox.pack_name('x"<|>y'), "x____y")
        self.assertEqual(len(inbox.pack_name("a" * 300)), inbox.NAME_MAX)
        self.assertEqual(inbox.pack_name(None), "")
        self.assertEqual(inbox.pack_title("【雑談】テスト_pack"), "【雑談】テスト")
        self.assertEqual(inbox.pack_title("_pack"), "_pack")
        self.assertEqual(inbox.pack_title("ふつうの名前"), "ふつうの名前")

    def test_verdict_doc_shape(self):
        d = inbox.verdict_doc("keep", RID, "a_pack", "a", 123.7)
        self.assertEqual(d, {"v": 1, "verdict": "keep", "requestId": RID, "zip": "a_pack", "title": "a", "origin": "request", "at": 123})
        self.assertNotIn("by", d)
        self.assertEqual(inbox.verdict_doc("reject", RID, "a_pack", "a", 1, by="auto")["by"], "auto")

    def test_case_of(self):
        path = os.path.join(self.cases, "案件-1", "作業用", "runs", "abc.json")
        self.assertEqual(os.path.abspath(inbox.case_of(path)), os.path.abspath(os.path.join(self.cases, "案件-1")))
        self.assertIsNone(inbox.case_of(os.path.join(self.cases, "案件-1", "作業用", "abc.json")))
        self.assertIsNone(inbox.case_of(""))
        self.assertIsNone(inbox.case_of(None))

    # ------------------------------------------------------------ 送る
    def test_add_puts_sent_row_on_top(self):
        self.box.add(RID, {"top": 3}, {"url": "u"}, run_id="r1")
        r = self.box.add(RID2, {"top": 5}, {"url": "v"}, run_id="r2")
        self.assertEqual(self.box.rows[0]["id"], RID2)
        self.assertIs(self.box.row(RID2), r)
        self.assertEqual(r["state"], "sent")
        self.assertEqual(r["kind"], "url")
        self.assertEqual(r["packs"], [])
        self.assertEqual(r["groups"], [])
        self.assertEqual(r["runId"], "r2")
        self.assertEqual(r["createdAt"], int(T0 * 1000))

    def test_add_refuses_bad_id(self):
        for bad in ("", None, "../x", "a b", "x" * 65):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                self.box.add(bad, {}, {}, run_id="r")

    def test_making_only_from_sent(self):
        self.box.add(RID, {}, {}, run_id="r1")
        self.box.making("r1")
        self.assertEqual(self.box.row(RID)["state"], "making")
        self.box.making("nope")   # 無い実行は何もしない

    def test_finished_with_packs_arrives_and_groups(self):
        names = ["a_pack", "b_pack", "c_pack", "d_pack", "e_pack"]
        self.clock.t = T0 + 100
        r, case, dirs = self.arrive(RID, names, batch=2)
        self.assertEqual(r["state"], "arrived")
        self.assertEqual(r["arrivedAt"], int((T0 + 100) * 1000))
        self.assertEqual(r["case"], case)
        self.assertEqual([p["name"] for p in r["packs"]], names)
        self.assertEqual([p["title"] for p in r["packs"]], ["a", "b", "c", "d", "e"])
        self.assertEqual(r["packs"][0]["seconds"], 10.5)
        self.assertEqual(r["packs"][0]["dir"], dirs[0])
        self.assertEqual([(g["n"], g["names"]) for g in r["groups"]],
                         [(1, ["a_pack", "b_pack"]), (2, ["c_pack", "d_pack"]), (3, ["e_pack"])])
        self.assertTrue(all(g["preview"] is None for g in r["groups"]))

    def test_finished_batch_out_of_range_uses_five(self):
        names = ["p%d_pack" % i for i in range(6)]
        for i, batch in enumerate((None, 0, 11, "5", 2.0)):
            with self.subTest(batch=batch):
                rid = "20250615-1200%02d-ffffff" % i
                self.box.add(rid, {}, {}, run_id="run-" + rid)
                case, dirs = self.make_case(rid, names)
                r = self.box.finished("run-" + rid, "done", "", [{"dir": d} for d in dirs], batch, case=case)
                self.assertEqual([len(g["names"]) for g in r["groups"]], [5, 1])

    def test_finished_skips_missing_dirs(self):
        self.box.add(RID, {}, {}, run_id="r1")
        case, dirs = self.make_case(RID, ["a_pack"])
        r = self.box.finished("r1", "done", "", [{"dir": dirs[0]}, {"dir": os.path.join(case, "無い_pack")}, {"dir": None}], 5, case=case)
        self.assertEqual([p["name"] for p in r["packs"]], ["a_pack"])
        self.assertEqual(r["state"], "arrived")

    def test_finished_without_packs_fails_with_reason(self):
        r = self.failed_row(RID, state="cancelled")
        self.assertEqual(r["state"], "failed")
        self.assertEqual(r["error"], "止めました")
        self.assertEqual(r["failedAt"], int(T0 * 1000))
        r2 = self.failed_row(RID2, state="error", error="ffmpeg が落ちました")
        self.assertEqual(r2["error"], "ffmpeg が落ちました")
        self.box.add("20250615-120200-cccccc", {}, {}, run_id="r3")
        r3 = self.box.finished("r3", "error", "", [], 5)
        self.assertEqual(r3["state"], "failed")
        self.assertIn("パックができませんでした", r3["error"])

    def test_finished_unknown_run_is_none(self):
        self.assertIsNone(self.box.finished("nobody", "done", "", [], 5))

    def test_finished_keeps_note_on_arrival(self):
        self.box.add(RID, {}, {}, run_id="r1")
        case, dirs = self.make_case(RID, ["a_pack"])
        r = self.box.finished("r1", "done", "", [{"dir": dirs[0]}], 5, case=case, note="メモ")
        self.assertEqual(r["note"], "メモ")

    def test_set_preview(self):
        self.arrive(RID, ["a_pack", "b_pack"], batch=1)
        self.box.set_preview(RID, 2, "/x/preview2.mp4")
        self.assertEqual(self.box.row(RID)["groups"][1]["preview"], "/x/preview2.mp4")
        self.box.set_preview(RID, 9, "/x/none.mp4")   # 無い組は何もしない
        self.box.set_preview("nope", 1, "/x/none.mp4")
        self.assertIsNone(self.box.row(RID)["groups"][0]["preview"])

    # ------------------------------------------------------------ 決める
    def test_decide_keep_moves_to_save_and_writes_verdict(self):
        r, case, dirs = self.arrive(RID, ["【雑談】テスト_pack"])
        got = self.box.decide(RID, [], "keep")
        self.assertEqual(got["done"], ["【雑談】テスト_pack"])
        self.assertEqual(got["errors"], [])
        self.assertFalse(os.path.exists(dirs[0]))
        saved = os.path.join(self.save, "【雑談】テスト_pack")
        self.assertTrue(os.path.isdir(saved))
        self.assertEqual(got["row"]["packs"][0]["savedTo"], saved)
        self.assertEqual(got["row"]["packs"][0]["verdict"], "keep")
        self.assertEqual(self.read_verdict(RID, "【雑談】テスト_pack"), {
            "v": 1, "verdict": "keep", "requestId": RID, "zip": "【雑談】テスト_pack", "title": "【雑談】テスト",
            "origin": "request", "at": int(T0 * 1000)})

    def test_decide_reject_moves_to_trash_and_writes_verdict(self):
        r, case, dirs = self.arrive(RID, ["a_pack", "b_pack"])
        got = self.box.decide(RID, ["a_pack"], "reject")
        self.assertEqual(got["done"], ["a_pack"])
        trash_day = os.path.join(self.cases, inbox.TRASH_NAME, day_of(T0))
        self.assertTrue(os.path.isdir(os.path.join(trash_day, "a_pack")))
        self.assertFalse(os.path.exists(dirs[0]))
        self.assertEqual(self.read_verdict(RID, "a_pack")["verdict"], "reject")
        self.assertFalse(os.path.exists(self.verdict_path(RID, "b_pack")))

    def test_decide_names_limits_to_chosen_packs(self):
        self.arrive(RID, ["a_pack", "b_pack", "c_pack"])
        got = self.box.decide(RID, ["b_pack", "zzz_pack"], "keep")
        self.assertEqual(got["done"], ["b_pack"])
        row = self.box.row(RID)
        self.assertEqual(row["state"], "arrived")
        self.assertEqual([p["verdict"] for p in row["packs"]], [None, "keep", None])
        self.assertEqual(sum(1 for p in row["packs"] if not p["verdict"]), 2)

    def test_decide_all_closes_row_and_trashes_case(self):
        r, case, dirs = self.arrive(RID, ["a_pack", "b_pack"])
        self.box.decide(RID, ["a_pack"], "keep")
        self.assertEqual(self.box.row(RID)["state"], "arrived")
        self.assertTrue(os.path.isdir(case))
        self.clock.t = T0 + 60
        got = self.box.decide(RID, [], "reject")
        self.assertEqual(got["done"], ["b_pack"])
        row = self.box.row(RID)
        self.assertEqual(row["state"], "done")
        self.assertEqual(row["doneAt"], int((T0 + 60) * 1000))
        self.assertFalse(os.path.exists(case))
        self.assertTrue(os.path.isdir(os.path.join(self.cases, inbox.TRASH_NAME, day_of(T0 + 60), "案件-" + RID)))

    def test_decide_on_collision_gets_suffix(self):
        self.arrive(RID, ["same_pack"])
        self.box.decide(RID, [], "keep")
        self.arrive(RID2, ["same_pack"])
        got = self.box.decide(RID2, [], "keep")
        saved = got["row"]["packs"][0]["savedTo"]
        self.assertNotEqual(os.path.basename(saved), "same_pack")
        self.assertTrue(os.path.basename(saved).startswith("same_pack-"))
        self.assertTrue(os.path.isdir(saved))

    def test_decide_error_is_reported_and_not_decided(self):
        self.arrive(RID, ["a_pack"])
        with mock.patch("friendapp.inbox.shutil.move", side_effect=PermissionError("denied")):
            got = self.box.decide(RID, [], "keep")
        self.assertEqual(got["done"], [])
        self.assertEqual(len(got["errors"]), 1)
        self.assertEqual(got["errors"][0]["name"], "a_pack")
        self.assertIn("受け取るの保存先へ移せませんでした", got["errors"][0]["message"])
        self.assertIn("PermissionError", got["errors"][0]["message"])
        row = self.box.row(RID)
        self.assertEqual(row["state"], "arrived")
        self.assertIsNone(row["packs"][0]["verdict"])
        self.assertFalse(os.path.exists(self.verdict_path(RID, "a_pack")))

    def test_decide_reject_error_message(self):
        self.arrive(RID, ["a_pack"])
        with mock.patch("friendapp.inbox.shutil.move", side_effect=OSError("busy")):
            got = self.box.decide(RID, [], "reject")
        self.assertIn("ごみ箱へ移せませんでした", got["errors"][0]["message"])
        self.assertEqual(self.box.row(RID)["state"], "arrived")

    def test_decide_missing_pack_dir_is_error(self):
        r, case, dirs = self.arrive(RID, ["a_pack"])
        shutil.rmtree(dirs[0])
        got = self.box.decide(RID, [], "keep")
        self.assertEqual(got["done"], [])
        self.assertEqual(got["errors"][0]["name"], "a_pack")

    def test_decide_refuses_bad_verdict_and_wrong_state(self):
        self.arrive(RID, ["a_pack"])
        with self.assertRaises(ValueError):
            self.box.decide(RID, [], "video")
        with self.assertRaises(KeyError):
            self.box.decide("nope", [], "keep")
        self.box.add(RID2, {}, {}, run_id="r9")   # まだ届いていない(sent)
        with self.assertRaises(KeyError):
            self.box.decide(RID2, [], "keep")

    def test_decide_with_auto_marks_verdict(self):
        self.arrive(RID, ["a_pack"])
        self.box.decide(RID, [], "reject", by="auto")
        self.assertEqual(self.read_verdict(RID, "a_pack")["by"], "auto")

    # ------------------------------------------------------------ 3 日の片付け
    def test_left_days(self):
        self.arrive(RID, ["a_pack"])
        self.failed_row(RID2)
        self.assertEqual(self.box.left_days(self.box.row(RID)), 3)
        self.clock.t = T0 + 86400 + 5
        self.assertEqual(self.box.left_days(self.box.row(RID)), 2)
        self.assertEqual(self.box.left_days(self.box.row(RID2)), 2)
        self.clock.t = T0 + 3 * 86400
        self.assertEqual(self.box.left_days(self.box.row(RID)), 0)
        self.assertIsNone(self.box.left_days({"state": "sent"}))

    def test_sweep_auto_rejects_after_three_days(self):
        self.arrive(RID, ["a_pack", "b_pack"])
        self.box.decide(RID, ["a_pack"], "keep")
        self.clock.t = T0 + 3 * 86400 - 1
        self.assertEqual(self.box.sweep(), 0)
        self.assertEqual(self.box.row(RID)["state"], "arrived")
        self.clock.t = T0 + 3 * 86400
        self.assertEqual(self.box.sweep(), 1)
        row = self.box.row(RID)
        self.assertEqual(row["state"], "done")
        self.assertEqual(self.read_verdict(RID, "b_pack")["by"], "auto")
        self.assertEqual(self.read_verdict(RID, "b_pack")["verdict"], "reject")
        self.assertNotIn("by", self.read_verdict(RID, "a_pack"))

    def test_sweep_removes_failed_after_three_days_and_trashes_case(self):
        case, dirs = self.make_case(RID, ["a_pack"])
        self.box.add(RID, {}, {}, run_id="r1")
        self.box.finished("r1", "error", "x", [], 5, case=case)
        self.clock.t = T0 + 3 * 86400 - 1
        self.assertEqual(self.box.sweep(), 0)
        self.assertEqual(self.box.row(RID)["state"], "failed")
        self.assertTrue(os.path.isdir(case))
        self.clock.t = T0 + 3 * 86400
        self.box.sweep()
        self.assertIsNone(self.box.row(RID))
        self.assertFalse(os.path.exists(case))
        self.assertTrue(os.path.isdir(os.path.join(self.cases, inbox.TRASH_NAME, day_of(T0 + 3 * 86400), "案件-" + RID)))

    def test_sweep_removes_failed_row_and_keeps_fresh_one(self):
        self.failed_row(RID, error="x")
        self.clock.t = T0 + 3 * 86400 + 60
        self.failed_row(RID2, error="y")
        self.box.sweep()
        self.assertIsNone(self.box.row(RID))
        self.assertIsNotNone(self.box.row(RID2))

    def test_sweep_removes_done_after_three_days(self):
        self.arrive(RID, ["a_pack"])
        self.box.decide(RID, [], "keep")
        self.assertEqual(self.box.row(RID)["state"], "done")
        self.clock.t = T0 + 3 * 86400 - 10
        self.box.sweep()
        self.assertIsNotNone(self.box.row(RID))
        self.clock.t = T0 + 3 * 86400 + 10
        self.box.sweep()
        self.assertIsNone(self.box.row(RID))

    def test_sweep_purges_old_trash_days(self):
        trash = os.path.join(self.cases, inbox.TRASH_NAME)
        old = day_of(T0 - 4 * 86400)
        edge = day_of(T0 - 3 * 86400)
        fresh = day_of(T0)
        for d in (old, edge, fresh, "memo"):
            os.makedirs(os.path.join(trash, d, "x"))
        self.box.sweep()
        self.assertFalse(os.path.exists(os.path.join(trash, old)))
        self.assertTrue(os.path.isdir(os.path.join(trash, edge)))
        self.assertTrue(os.path.isdir(os.path.join(trash, fresh)))
        self.assertTrue(os.path.isdir(os.path.join(trash, "memo")))

    # ------------------------------------------------------------ 画面へ
    def test_view_hides_done_and_dir(self):
        self.arrive(RID, ["a_pack", "b_pack"])
        self.box.decide(RID, ["a_pack"], "keep")
        self.failed_row(RID2)
        self.box.add("20250615-120300-dddddd", {}, {}, run_id="r4")
        rows = self.box.view()
        ids = [r["id"] for r in rows]
        self.assertEqual(ids, ["20250615-120300-dddddd", RID2, RID])
        arrived = rows[2]
        self.assertEqual(arrived["undecided"], 1)
        self.assertEqual(arrived["left"], 3)
        self.assertTrue(all("dir" not in p for p in arrived["packs"]))
        self.assertIsNone(rows[0]["left"])
        self.assertEqual(rows[1]["left"], 3)
        self.assertIn("dir", self.box.row(RID)["packs"][0])   # 中の記録は消さない

    def test_view_is_a_copy(self):
        self.arrive(RID, ["a_pack"])
        v = self.box.view()[0]
        v["packs"][0]["name"] = "changed"
        self.assertEqual(self.box.row(RID)["packs"][0]["name"], "a_pack")

    def test_view_status_of_only_for_sent_or_making(self):
        self.box.add(RID, {}, {}, run_id="r1")
        self.box.add(RID2, {}, {}, run_id="r2")
        self.box.making("r2")
        self.arrive("20250615-120400-eeeeee", ["a_pack"], run_id="r3")
        seen = []

        def status_of(run_id):
            seen.append(run_id)
            return {"state": "running", "message": "進んでいます"} if run_id == "r2" else None

        rows = self.box.view(status_of=status_of)
        self.assertEqual(sorted(seen), ["r1", "r2"])
        by_id = {r["id"]: r for r in rows}
        self.assertEqual(by_id[RID2]["run"], {"state": "running", "message": "進んでいます"})
        self.assertIsNone(by_id[RID]["run"])
        self.assertNotIn("run", by_id["20250615-120400-eeeeee"])

    # ------------------------------------------------------------ retry・remove・記録
    def test_resent_puts_failed_row_back_to_sent(self):
        self.failed_row(RID, error="x")
        r = self.box.resent(RID, "newrun")
        self.assertEqual(r["state"], "sent")
        self.assertEqual(r["runId"], "newrun")
        self.assertEqual(r["error"], "")
        self.assertIsNone(r["failedAt"])
        self.assertEqual(self.box.by_run("newrun")["id"], RID)
        with self.assertRaises(KeyError):
            self.box.resent("nope", "r")

    def test_remove_only_failed_and_trashes_case(self):
        case, dirs = self.make_case(RID, ["a_pack"])
        self.box.add(RID, {}, {}, run_id="r1")
        self.box.finished("r1", "error", "x", [], 5, case=case)
        self.box.remove(RID)
        self.assertIsNone(self.box.row(RID))
        self.assertFalse(os.path.exists(case))
        self.assertTrue(os.path.isdir(os.path.join(self.cases, inbox.TRASH_NAME, day_of(T0), "案件-" + RID)))
        self.arrive(RID2, ["b_pack"])
        with self.assertRaises(KeyError):
            self.box.remove(RID2)
        with self.assertRaises(KeyError):
            self.box.remove("nope")

    def test_rows_persist_and_reload(self):
        self.arrive(RID, ["a_pack", "b_pack"], batch=1)
        self.box.decide(RID, ["a_pack"], "keep")
        self.failed_row(RID2, error="止め")
        again = self.new_box()
        self.assertEqual([r["id"] for r in again.rows], [RID2, RID])
        row = again.row(RID)
        self.assertEqual(row["state"], "arrived")
        self.assertEqual(row["packs"][0]["verdict"], "keep")
        self.assertEqual(row["packs"][1]["verdict"], None)
        self.assertEqual(len(row["groups"]), 2)
        self.assertEqual(again.row(RID2)["error"], "止め")
        self.assertEqual(again.view()[1]["undecided"], 1)

    def test_load_drops_bad_rows_and_other_version(self):
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        good = {"id": RID, "state": "failed", "failedAt": int(T0 * 1000)}
        bad_id = {"id": "../x", "state": "failed"}
        bad_state = {"id": RID2, "state": "weird"}
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump({"v": inbox.V, "rows": [good, bad_id, bad_state, "text"]}, f)
        self.assertEqual([r["id"] for r in self.new_box().rows], [RID])
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump({"v": 99, "rows": [good]}, f)
        self.assertEqual(self.new_box().rows, [])
        with open(self.path, "w", encoding="utf-8") as f:
            f.write("{ こわれた")
        self.assertEqual(self.new_box().rows, [])


if __name__ == "__main__":
    unittest.main()
