"""store.py の単体テスト(ネットワーク・ffmpeg 不要)。 実行: python3 test_studio.py"""
import glob
import json
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common
import store
from common import ApiError

YT = {"kind": "youtube", "videoId": "abcdefghijk", "name": "abcdefghijk"}
YT2 = {"kind": "youtube", "videoId": "bbbbbbbbbbb", "name": "bbbbbbbbbbb"}
YT3 = {"kind": "youtube", "videoId": "ccccccccccc", "name": "ccccccccccc"}


def cand(s, e, score=5.0):
    return {"start": s, "end": e, "score": score, "reasons": ["音量"], "peak": s + 1, "parts": {"audio": 1.0}}


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        common.set_home(self.tmp)
        self.path = os.path.join(self.tmp, "data.json")
        self.st = store.Store(self.path)
        self.st.ensure(YT, "t", "c")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def video(self):
        return self.st.get(YT["videoId"])[0]

    def marks(self):
        return self.video()["marks"]

    def auto(self, *spans):
        self.st.replace_auto(YT["videoId"], [cand(s, e) for s, e in spans], {"spec": {}}, 600, {"t": [0]})

    def put(self, marks, rev=None):
        return self.st.put_video(YT["videoId"], "t", marks, rev)

    def feedback(self):
        p = os.path.join(self.tmp, "feedback.jsonl")
        if not os.path.exists(p):
            return []
        with open(p, encoding="utf-8") as f:
            return [json.loads(l) for l in f if l.strip()]


class TestCheckTimes(unittest.TestCase):
    def test_ok_rounds(self):
        self.assertEqual(store.check_times(1.04, 10.26), (1.0, 10.3))

    def test_rejects(self):
        for a, b in [("1", 2), (True, 2), (float("nan"), 2), (-1, 5), (5, 5), (5, 4), (0, 3601), (0, 1e9), (None, 1)]:
            with self.assertRaises(store.BadMark, msg=(a, b)):
                store.check_times(a, b)


class TestValidate(Base):
    def test_new_mark_is_manual_and_server_fields_ignored(self):
        out = self.put([{"start": 1, "end": 9, "src": "auto", "score": 99, "status": "exported", "file": "x.mp4", "auto0": [1, 9]}])
        m = out["marks"][0]
        self.assertEqual((m["src"], m["status"], m["file"], m["score"]), ("manual", "", "", None))
        self.assertNotIn("auto0", m)
        self.assertTrue(m["id"].startswith("m"))

    def test_client_can_set_adopted_rejected_on_new(self):
        out = self.put([{"start": 1, "end": 9, "status": "adopted"}, {"start": 20, "end": 30, "status": "rejected"}])
        self.assertEqual([m["status"] for m in out["marks"]], ["adopted", "rejected"])

    def test_bad_marks_change_nothing(self):
        self.put([{"id": "a1", "start": 1, "end": 9}])
        rev = self.video()["rev"]
        for bad in ([{"id": "a1", "start": 1, "end": 9}, {"id": "a1", "start": 2, "end": 9}],   # 重複
                    [{"id": "bad id!", "start": 1, "end": 9}],
                    [{"id": "x", "start": 9, "end": 1}],
                    ["notdict"]):
            with self.assertRaises(ApiError) as c:
                self.put(bad)
            self.assertEqual((c.exception.code, c.exception.status), ("bad_marks", 400))
        self.assertEqual(self.video()["rev"], rev)
        self.assertEqual(len(self.marks()), 1)

    def test_too_many(self):
        with self.assertRaises(ApiError):
            self.put([{"start": i, "end": i + 1} for i in range(store.MAX_MARKS + 1)])

    def test_conflict_409_returns_latest(self):
        rev = self.video()["rev"]
        self.put([{"id": "a1", "start": 1, "end": 9}], rev)
        with self.assertRaises(ApiError) as c:
            self.put([], rev)   # 古い rev
        self.assertEqual(c.exception.status, 409)
        self.assertEqual(len(c.exception.extra["video"]["marks"]), 1)

    def test_baserev_type(self):
        for r in ("1", True, 1.5):
            with self.assertRaises(ApiError):
                self.put([], r)


class TestStatus(Base):
    def setUp(self):
        super().setUp()
        self.auto((10, 40))
        self.m = self.marks()[0]

    def send(self, **kw):
        m = dict(self.m, **kw)
        return self.put([m])["marks"][0]

    def test_exported_then_status_returns_to_state_and_drops_file(self):
        self.st.mark_exported(YT["videoId"], self.m["id"], "f/a.mp4")
        self.m = self.marks()[0]
        self.assertEqual((self.m["status"], self.m["file"]), ("exported", "f/a.mp4"))
        for s in ("adopted", "rejected", ""):
            self.st.mark_exported(YT["videoId"], self.m["id"], "f/a.mp4")
            self.m = self.marks()[0]
            r = self.send(status=s)
            self.assertEqual((r["status"], r["file"]), (s, ""))

    def test_client_cannot_set_exported(self):
        r = self.send(status="exported", file="evil.mp4")
        self.assertEqual((r["status"], r["file"]), ("", ""))

    def test_moving_exported_reverts_to_adopted(self):
        self.st.mark_exported(YT["videoId"], self.m["id"], "f/a.mp4")
        self.m = self.marks()[0]
        r = self.send(start=self.m["start"] + 2)
        self.assertEqual((r["status"], r["file"]), ("adopted", ""))

    def test_tiny_move_keeps_exported(self):
        self.st.mark_exported(YT["videoId"], self.m["id"], "f/a.mp4")
        self.m = self.marks()[0]
        r = self.send(start=self.m["start"] + 0.04)
        self.assertEqual(r["status"], "exported")

    def test_server_fields_not_overridable(self):
        r = self.send(score=999, src="manual", reasons=["x"], auto0=[0, 1])
        self.assertEqual(r["src"], "auto")
        self.assertEqual(r["score"], self.m["score"])
        self.assertEqual(r["auto0"], self.m["auto0"])


class TestFeedback(Base):
    def setUp(self):
        super().setUp()
        self.auto((10, 40), (100, 130), (200, 230))
        self.ms = self.marks()

    def verdicts(self):
        return [r["verdict"] for r in self.feedback()]

    def test_adopt_reject(self):
        a, b, c = self.ms
        self.put([dict(a, status="adopted"), dict(b, status="rejected"), c])
        self.assertEqual(sorted(self.verdicts()), ["bad", "good"])

    def test_no_double_record_and_only_on_transition(self):
        a = self.ms[0]
        self.put([dict(a, status="adopted"), self.ms[1], self.ms[2]])
        cur = self.marks()
        self.put(cur)                              # 変化なし
        self.assertEqual(self.verdicts(), ["good"])

    def test_delete_candidate_is_bad_delete_judged_is_silent(self):
        a, b, c = self.ms
        self.put([dict(a, status="adopted"), b, c])          # a: good
        cur = self.marks()
        self.put([m for m in cur if m["id"] == a["id"]])     # b, c(候補)を削除 → bad ×2、a は残す
        self.assertEqual(sorted(self.verdicts()), ["bad", "bad", "good"])
        self.put([])                                         # 採用済み a を削除 → 記録しない
        self.assertEqual(len(self.feedback()), 3)

    def test_manual_marks_recorded_only_when_adopted_or_rejected(self):
        self.put([{"id": "m1", "start": 500, "end": 520}])                       # 候補のまま作っただけ: 記録しない
        self.assertEqual([r for r in self.feedback() if r["start"] == 500], [])
        self.put([dict(m, status="adopted") if m["id"] == "m1" else m for m in self.marks()])
        rows = [r for r in self.feedback() if r["start"] == 500]
        self.assertEqual([(r["verdict"], r["src"], r["event"]) for r in rows], [("good", "manual", "adopt")])
        self.assertNotIn("auto0", rows[0])
        self.put([m for m in self.marks() if m["id"] != "m1"])                    # 手動の削除は記録しない
        self.assertEqual(len([r for r in self.feedback() if r["start"] == 500]), 1)

    def test_manual_created_already_adopted_is_recorded(self):
        self.put([{"id": "m2", "start": 700, "end": 730, "status": "adopted"}])
        self.assertEqual([(r["verdict"], r["src"]) for r in self.feedback() if r["start"] == 700], [("good", "manual")])

    def test_events_and_edit_deltas_recorded(self):
        a, b, c = self.ms
        moved = dict(a, status="adopted", start=a["start"] - 5, end=a["end"] + 5)   # 開始を5秒早め、終了を5秒遅らせて採用
        self.put([moved, dict(b, status="rejected"), c])
        rows = {r["event"]: r for r in self.feedback()}
        self.assertEqual((rows["adopt"]["dStart"], rows["adopt"]["dEnd"], rows["adopt"]["src"]), (-5.0, 5.0, "auto"))
        self.assertEqual(rows["adopt"]["auto0"], a["auto0"])
        self.assertEqual(rows["reject"]["verdict"], "bad")
        self.put([m for m in self.marks() if m["id"] != c["id"]])
        self.assertIn("delete", [r["event"] for r in self.feedback()])

    def test_manual_export_recorded_as_good(self):
        self.put([{"id": "m3", "start": 900, "end": 960}])
        self.st.mark_exported(YT["videoId"], "m3", "f/m.mp4")
        self.st.mark_exported(YT["videoId"], "m3", "f/m.mp4")
        rows = [r for r in self.feedback() if r["start"] == 900]
        self.assertEqual([(r["verdict"], r["src"], r["event"]) for r in rows], [("good", "manual", "export")])

    def test_export_first_time_good_only(self):
        a = self.ms[0]
        self.st.mark_exported(YT["videoId"], a["id"], "f/a.mp4")
        self.st.mark_exported(YT["videoId"], a["id"], "f/a.mp4")   # 2回目は記録しない
        self.assertEqual(self.verdicts(), ["good"])


class TestReplaceAuto(Base):
    def test_untouched_autos_replaced(self):
        self.auto((10, 40), (100, 130))
        self.auto((300, 330))
        ms = self.marks()
        self.assertEqual([(m["start"], m["src"]) for m in ms], [(300.0, "auto")])

    def test_touched_kept_as_manual_and_rejected_not_revived(self):
        self.auto((10, 40), (100, 130), (200, 230))
        a, b, c = self.marks()
        self.put([dict(a, status="rejected"), dict(b, label="ネタ"), dict(c, start=c["start"] + 3)])
        self.auto((10, 40), (100, 130), (203, 230), (400, 430))   # 同じ区間 + 新規
        ms = self.marks()
        self.assertEqual(len(ms), 4)                    # 3つ残る + 新規1
        by = {m["start"]: m for m in ms}
        self.assertEqual(by[10.0]["status"], "rejected")
        self.assertEqual(by[10.0]["src"], "manual")
        self.assertNotIn("auto0", by[10.0])
        self.assertEqual(by[400.0]["src"], "auto")
        self.assertEqual(sum(1 for m in ms if abs(m["start"] - 10) < 1), 1)   # 不採用が復活して重複しない

    def test_exported_kept(self):
        self.auto((10, 40))
        m = self.marks()[0]
        self.st.mark_exported(YT["videoId"], m["id"], "f/a.mp4")
        self.auto((500, 530))
        kept = [x for x in self.marks() if x["start"] == 10.0][0]
        self.assertEqual((kept["status"], kept["src"], kept["file"]), ("exported", "manual", "f/a.mp4"))

    def test_invalid_candidates_skipped(self):
        n = self.st.replace_auto(YT["videoId"], [cand(5, 5), {"start": "x"}, cand(0, 5000), cand(1, 11)], {"spec": {}}, 0, {})
        self.assertEqual(n, 1)

    def test_deleted_video_returns_none(self):
        self.assertIsNone(self.st.replace_auto("zzzzzzzzzzz", [], {}, 0, {}))


class TestPersistence(Base):
    def test_reload_roundtrip(self):
        self.auto((10, 40))
        self.put(self.marks() + [{"id": "m1", "start": 50, "end": 60, "label": "L"}])
        st2 = store.Store(self.path)
        self.assertEqual(st2.get(YT["videoId"])[0]["marks"], self.marks())

    def test_corrupt_file_quarantined(self):
        with open(self.path, "wb") as f:
            f.write(b"{not json")
        st2 = store.Store(self.path)
        self.assertEqual(st2.videos, {})
        w, b = st2.take_warning()
        self.assertTrue(w and b)
        self.assertTrue(glob.glob(self.path + ".corrupt-*"))
        self.assertEqual(st2.take_warning(), ("", ""))   # 一度だけ

    def test_one_bad_video_skipped_others_kept(self):
        with open(self.path, encoding="utf-8") as f:
            d = json.load(f)
        d["videos"]["badbadbad11"] = {"id": "other", "kind": "youtube"}
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump(d, f)
        st2 = store.Store(self.path)
        self.assertIn(YT["videoId"], st2.videos)
        self.assertNotIn("badbadbad11", st2.videos)
        self.assertTrue(st2.take_warning()[0])

    def test_save_failure_leaves_memory_unchanged(self):
        self.auto((10, 40))
        before = self.video()
        orig = store.atomic_write
        store.atomic_write = lambda *a, **k: (_ for _ in ()).throw(OSError("disk full"))
        try:
            with self.assertRaises(ApiError) as c:
                self.put([])
            self.assertEqual(c.exception.status, 500)
        finally:
            store.atomic_write = orig
        self.assertEqual(self.video(), before)
        self.assertEqual(self.feedback(), [])   # 保存に失敗したら feedback も書かない

    def test_series_persist_and_trim(self):
        self.st.series[YT["videoId"]] = {"a": 1}
        st2 = store.Store(self.path)
        self.assertEqual(st2.series.get(YT["videoId"]), {"a": 1})
        for i in range(store.SERIES_KEEP + 5):
            self.st.series["v%010d" % i] = {"i": i}
        files = os.listdir(os.path.join(self.tmp, "cache", "series"))
        self.assertLessEqual(len(files), store.SERIES_KEEP)

    def test_delete_removes_series(self):
        self.st.series[YT["videoId"]] = {"a": 1}
        self.assertTrue(self.st.delete(YT["videoId"]))
        self.assertNotIn(YT["videoId"], self.st.series)
        self.assertFalse(self.st.delete(YT["videoId"]))

    def test_summary_counts(self):
        self.auto((10, 40), (100, 130), (200, 230))
        a, b, c = self.marks()
        self.put([dict(a, status="adopted"), dict(b, status="rejected"), c])
        self.st.mark_exported(YT["videoId"], a["id"], "f.mp4")
        s = self.st.list()[0]
        self.assertEqual((s["marks"], s["exported"], s["adopted"], s["candidates"]), (3, 1, 0, 1))


class TestCollab(Base):
    """コラボ動画のマーク転写(グループ+オフセット)。"""

    def setUp(self):
        super().setUp()
        self.st.ensure(YT2, "t2", "c2")
        self.st.ensure(YT3, "t3", "c3")

    def vmarks(self, vid):
        return self.st.get(vid)[0]["marks"]

    def putv(self, vid, marks, rev=None):
        return self.st.put_video(vid, "t", marks, rev)

    def group(self, members=None, base=None, name=""):
        return self.st.create_group(members or [YT["videoId"], YT2["videoId"]], name, base)

    # ---- グループの作成・編集 ----
    def test_create_group_basic(self):
        g = self.group()
        self.assertEqual(g["base"], YT["videoId"])
        by = {m["id"]: m for m in g["members"]}
        self.assertTrue(by[YT["videoId"]]["isBase"] and by[YT["videoId"]]["offsetSet"])
        self.assertFalse(by[YT2["videoId"]]["offsetSet"])
        self.assertFalse(g["allSet"])

    def test_create_group_needs_two(self):
        with self.assertRaises(ApiError) as c:
            self.st.create_group([YT["videoId"]], "", None)
        self.assertEqual(c.exception.code, "bad_request")

    def test_create_group_too_many(self):
        ids = [YT["videoId"], YT2["videoId"], YT3["videoId"]] + ["extra%d" % i for i in range(6)]
        with self.assertRaises(ApiError) as c:
            self.st.create_group(ids, "", None)
        self.assertEqual(c.exception.code, "bad_request")

    def test_create_group_missing_video(self):
        with self.assertRaises(ApiError) as c:
            self.st.create_group([YT["videoId"], "nosuchvideo1"], "", None)
        self.assertEqual(c.exception.status, 404)

    def test_create_group_conflict_already_grouped(self):
        self.group()
        with self.assertRaises(ApiError) as c:
            self.st.create_group([YT["videoId"], YT3["videoId"]], "", None)
        self.assertEqual(c.exception.code, "conflict")

    def test_add_members(self):
        g = self.group()
        g2 = self.st.add_members(g["id"], [YT3["videoId"]])
        self.assertEqual(len(g2["members"]), 3)

    def test_remove_non_base_member_keeps_group(self):
        g = self.st.create_group([YT["videoId"], YT2["videoId"], YT3["videoId"]], "", YT["videoId"])
        r = self.st.remove_member(g["id"], YT3["videoId"])
        self.assertEqual(len(r["members"]), 2)

    def test_remove_base_deletes_whole_group(self):
        g = self.st.create_group([YT["videoId"], YT2["videoId"], YT3["videoId"]], "", YT["videoId"])
        self.assertIsNone(self.st.remove_member(g["id"], YT["videoId"]))
        with self.assertRaises(ApiError):
            self.st.get_group(g["id"])

    def test_remove_down_to_one_deletes_whole_group(self):
        g = self.group()
        self.assertIsNone(self.st.remove_member(g["id"], YT2["videoId"]))
        with self.assertRaises(ApiError):
            self.st.get_group(g["id"])

    def test_delete_video_detaches_from_group(self):
        g = self.st.create_group([YT["videoId"], YT2["videoId"], YT3["videoId"]], "", YT["videoId"])
        self.st.delete(YT3["videoId"])
        self.assertEqual(len(self.st.get_group(g["id"])["members"]), 2)

    def test_delete_base_video_removes_group(self):
        g = self.group()
        self.st.delete(YT["videoId"])
        with self.assertRaises(ApiError):
            self.st.get_group(g["id"])

    # ---- アンカー点からのオフセット計算 ----
    def test_offset_from_anchors_one_point(self):
        p = store.offset_from_anchors([[100, 110]])
        self.assertEqual((p["a"], p["b"]), (1.0, 10.0))

    def test_offset_from_anchors_two_points(self):
        p = store.offset_from_anchors([[100, 108], [400, 408]])
        self.assertAlmostEqual(p["a"], 1.0)
        self.assertAlmostEqual(p["b"], 8.0)

    def test_offset_from_anchors_too_close(self):
        with self.assertRaises(store.BadMark):
            store.offset_from_anchors([[100, 108], [105, 113]])

    def test_offset_from_anchors_bad_slope(self):
        with self.assertRaises(store.BadMark):
            store.offset_from_anchors([[0, 0], [100, 400]])   # a=4 は範囲外

    def test_set_anchor_rejects_base(self):
        g = self.group()
        with self.assertRaises(ApiError):
            self.st.set_anchor(g["id"], YT["videoId"], [[0, 0]])

    # ---- 採用時の転写 ----
    def test_transfer_on_adopt_base_to_member(self):
        g = self.group()
        self.st.set_anchor(g["id"], YT2["videoId"], [[100.0, 110.0]])   # v2の100秒 = 基準の110秒
        self.putv(YT["videoId"], [{"id": "m1", "start": 110.0, "end": 120.0, "status": "adopted"}])
        v2 = self.vmarks(YT2["videoId"])
        self.assertEqual(len(v2), 1)
        c = v2[0]
        self.assertEqual(c["src"], "collab")
        self.assertEqual(c["status"], "")   # 候補どまり(自動採用しない)
        self.assertAlmostEqual(c["start"], 100.0 - store.COLLAB_MARGIN)
        self.assertAlmostEqual(c["end"], 110.0 + store.COLLAB_MARGIN)
        self.assertEqual(c["collabFrom"], {"videoId": YT["videoId"], "markId": "m1"})

    def test_transfer_on_adopt_member_to_base(self):
        g = self.group()
        self.st.set_anchor(g["id"], YT2["videoId"], [[100.0, 110.0]])
        self.putv(YT2["videoId"], [{"id": "m2", "start": 100.0, "end": 110.0, "status": "adopted"}])
        c = self.vmarks(YT["videoId"])[0]
        self.assertAlmostEqual(c["start"], 110.0 - store.COLLAB_MARGIN)
        self.assertAlmostEqual(c["end"], 120.0 + store.COLLAB_MARGIN)
        self.assertEqual(c["collabFrom"]["videoId"], YT2["videoId"])

    def test_no_duplicate_transfer_when_readopted(self):
        g = self.group()
        self.st.set_anchor(g["id"], YT2["videoId"], [[100.0, 110.0]])
        self.putv(YT["videoId"], [{"id": "m1", "start": 110.0, "end": 120.0, "status": "adopted"}])
        self.assertEqual(len(self.vmarks(YT2["videoId"])), 1)
        cur = self.vmarks(YT["videoId"])[0]
        self.putv(YT["videoId"], [dict(cur, status="")])            # 候補に戻す
        self.putv(YT["videoId"], [dict(self.vmarks(YT["videoId"])[0], status="adopted")])   # もう一度採用
        self.assertEqual(len(self.vmarks(YT2["videoId"])), 1)       # 転写は重複しない

    def test_transfer_skipped_when_target_offset_unset(self):
        self.group()   # アンカー未設定のまま
        self.putv(YT["videoId"], [{"id": "m1", "start": 10.0, "end": 20.0, "status": "adopted"}])
        self.assertEqual(self.vmarks(YT2["videoId"]), [])

    def test_transfer_skipped_when_source_offset_unset(self):
        self.group()
        self.putv(YT2["videoId"], [{"id": "m2", "start": 10.0, "end": 20.0, "status": "adopted"}])
        self.assertEqual(self.vmarks(YT["videoId"]), [])

    def test_transfer_skipped_when_not_in_a_group(self):
        self.putv(YT["videoId"], [{"id": "m1", "start": 10.0, "end": 20.0, "status": "adopted"}])
        self.assertEqual(self.vmarks(YT2["videoId"]), [])

    def test_collab_mark_start_clamped_to_zero(self):
        g = self.group()
        self.st.set_anchor(g["id"], YT2["videoId"], [[1.0, 3.0]])   # v2:1秒 = 基準:3秒
        self.putv(YT["videoId"], [{"id": "m1", "start": 3.0, "end": 10.0, "status": "adopted"}])
        self.assertEqual(self.vmarks(YT2["videoId"])[0]["start"], 0.0)

    def test_collab_mark_end_clamped_to_duration(self):
        self.st.replace_auto(YT2["videoId"], [], {"spec": {}}, 50.0, {})   # v2 の長さ = 50秒
        g = self.group()
        self.st.set_anchor(g["id"], YT2["videoId"], [[40.0, 50.0]])
        self.putv(YT["videoId"], [{"id": "m1", "start": 50.0, "end": 60.0, "status": "adopted"}])
        self.assertEqual(self.vmarks(YT2["videoId"])[0]["end"], 50.0)

    def test_collab_mark_rejects_client_src_spoof_and_keeps_collab_from(self):
        g = self.group()
        self.st.set_anchor(g["id"], YT2["videoId"], [[100.0, 110.0]])
        self.putv(YT["videoId"], [{"id": "m1", "start": 110.0, "end": 120.0, "status": "adopted"}])
        c = self.vmarks(YT2["videoId"])[0]
        r = self.putv(YT2["videoId"], [dict(c, src="manual", score=99, start=c["start"] + 1)])["marks"][0]
        self.assertEqual(r["src"], "collab")
        self.assertIsNone(r["score"])
        self.assertEqual(r["collabFrom"], c["collabFrom"])

    def test_remove_member_keeps_already_transferred_marks(self):
        g = self.group()
        self.st.set_anchor(g["id"], YT2["videoId"], [[100.0, 110.0]])
        self.putv(YT["videoId"], [{"id": "m1", "start": 110.0, "end": 120.0, "status": "adopted"}])
        self.assertEqual(len(self.vmarks(YT2["videoId"])), 1)
        self.st.remove_member(g["id"], YT2["videoId"])   # 残り1本になりグループごと削除される
        self.assertEqual(len(self.vmarks(YT2["videoId"])), 1)   # 転写済みマークは残る

    # ---- 永続化 ----
    def test_group_persists_across_reload(self):
        g = self.group()
        self.st.set_anchor(g["id"], YT2["videoId"], [[100.0, 110.0]])
        st2 = store.Store(self.path)
        g2 = st2.get_group(g["id"])
        self.assertTrue(g2["allSet"])
        by = {m["id"]: m for m in g2["members"]}
        self.assertEqual(by[YT2["videoId"]]["offset"], {"a": 1.0, "b": 10.0})

    def test_corrupt_group_skipped_others_kept(self):
        self.group()
        with open(self.path, encoding="utf-8") as f:
            d = json.load(f)
        d["groups"]["badbadbad11"] = {"id": "other"}
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump(d, f)
        st2 = store.Store(self.path)
        self.assertEqual(len(st2.groups), 1)
        self.assertTrue(st2.take_warning()[0])


class TestEnsure(Base):
    def test_empty_title_does_not_erase(self):
        self.st.ensure(YT, "", "")
        v = self.video()
        self.assertEqual((v["title"], v["channel"]), ("t", "c"))

    def test_title_change_bumps_rev(self):
        r = self.video()["rev"]
        self.st.ensure(YT, "new", "")
        self.assertEqual(self.video()["rev"], r + 1)


if __name__ == "__main__":
    unittest.main(verbosity=1)
