"""human/review/store.py の単体テスト(ネットワーク・ffmpeg 不要)。 実行(リポジトリ直下): py -3.10 -m unittest src/human/review/tests/test_studio.py
RS3-5(2026-10-10)で studio/tests から移した。"""
import glob
import json
import os
os.environ.setdefault("YTT_DATA_DIR", "inplace")   # テストは作業データを本物の置き場所(AppData など)に書かない(ytt.datadir)
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))))   # tests → review → human → src
from human.review import store  # noqa: E402
from ytt import yturl  # noqa: E402
from ytt import studio_env  # noqa: E402
from ytt.errors import ApiError  # noqa: E402

YT = {"kind": "youtube", "videoId": "abcdefghijk", "name": "abcdefghijk"}
YT2 = {"kind": "youtube", "videoId": "bbbbbbbbbbb", "name": "bbbbbbbbbbb"}
YT3 = {"kind": "youtube", "videoId": "ccccccccccc", "name": "ccccccccccc"}


def cand(s, e, score=5.0):
    return {"start": s, "end": e, "score": score, "reasons": ["音量"], "peak": s + 1, "parts": {"audio": 1.0}}


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        studio_env.set_home(self.tmp)
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
        self.st.mark_exported(YT["videoId"], self.m["id"], "f/a.mp4", self.m["start"], self.m["end"])
        self.m = self.marks()[0]
        self.assertEqual((self.m["status"], self.m["file"]), ("exported", "f/a.mp4"))
        for s in ("adopted", "rejected", ""):
            self.st.mark_exported(YT["videoId"], self.m["id"], "f/a.mp4", self.m["start"], self.m["end"])
            self.m = self.marks()[0]
            r = self.send(status=s)
            self.assertEqual((r["status"], r["file"]), (s, ""))

    def test_exported_keeps_absolute_path_and_client_cannot_change_it(self):
        ap = os.path.abspath(os.path.join("out", "f", "a.mp4"))
        self.st.mark_exported(YT["videoId"], self.m["id"], "f/a.mp4", self.m["start"], self.m["end"], ap)
        self.m = self.marks()[0]
        self.assertEqual((self.m["status"], self.m["file"], self.m.get("path")), ("exported", "f/a.mp4", ap))
        r = self.send(path="C:\\evil.mp4", label="名前を変える")   # 名前を変えても書き出し済みの情報は残り、path は書き換えられない
        self.assertEqual((r["status"], r.get("path")), ("exported", ap))
        r = self.send(start=self.m["start"] + 2)                 # 範囲を動かすと file と一緒に path も外れる
        self.assertEqual((r["status"], r["file"], r.get("path")), ("adopted", "", None))

    def test_exported_without_or_relative_path_has_no_path(self):
        self.st.mark_exported(YT["videoId"], self.m["id"], "f/a.mp4", self.m["start"], self.m["end"], "f/a.mp4")
        self.assertNotIn("path", self.marks()[0])
        self.st.mark_exported(YT["videoId"], self.m["id"], "f/a.mp4", self.m["start"], self.m["end"])
        self.assertNotIn("path", self.marks()[0])

    def test_client_cannot_set_exported(self):
        r = self.send(status="exported", file="evil.mp4")
        self.assertEqual((r["status"], r["file"]), ("", ""))

    def test_moving_exported_reverts_to_adopted(self):
        self.st.mark_exported(YT["videoId"], self.m["id"], "f/a.mp4", self.m["start"], self.m["end"])
        self.m = self.marks()[0]
        r = self.send(start=self.m["start"] + 2)
        self.assertEqual((r["status"], r["file"]), ("adopted", ""))

    def test_tiny_move_keeps_exported(self):
        self.st.mark_exported(YT["videoId"], self.m["id"], "f/a.mp4", self.m["start"], self.m["end"])
        self.m = self.marks()[0]
        r = self.send(start=self.m["start"] + 0.04)
        self.assertEqual(r["status"], "exported")

    def test_server_fields_not_overridable(self):
        r = self.send(score=999, src="manual", reasons=["x"], auto0=[0, 1])
        self.assertEqual(r["src"], "auto")
        self.assertEqual(r["score"], self.m["score"])
        self.assertEqual(r["auto0"], self.m["auto0"])

    def test_export_completion_preserves_changed_range(self):
        for change in ({"start": 12}, {"end": 45}):
            with self.subTest(change=change):
                self.send(status="adopted", **change)
                before, feedback = self.video(), self.feedback()
                saved = self.st.mark_exported(YT["videoId"], self.m["id"], "f/old.mp4", self.m["start"], self.m["end"])
                self.assertFalse(saved)
                self.assertEqual(self.video(), before)
                self.assertEqual(self.feedback(), feedback)
                reloaded = store.Store(self.path)
                self.assertEqual(reloaded.get(YT["videoId"])[0]["marks"], before["marks"])

    def test_export_completion_allows_label_edit(self):
        self.send(status="adopted", label="new label")
        self.assertTrue(self.st.mark_exported(YT["videoId"], self.m["id"], "f/a.mp4", self.m["start"], self.m["end"]))
        m = self.marks()[0]
        self.assertEqual((m["label"], m["status"], m["file"]), ("new label", "exported", "f/a.mp4"))

    def test_export_completion_does_not_recreate_deleted_mark(self):
        self.put([])
        self.assertFalse(self.st.mark_exported(YT["videoId"], self.m["id"], "f/a.mp4", self.m["start"], self.m["end"]))
        self.assertEqual(self.marks(), [])


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
        self.put([])                                         # 採用済み a を削除 → good / bad は増やさず、取り消しの行(delete_judged)を1行足す
        self.assertEqual(sorted(self.verdicts()), ["bad", "bad", "good", "retract"])
        row = [r for r in self.feedback() if r["event"] == "delete_judged"][0]
        self.assertEqual((row["prevStatus"], row["start"], row["auto0"]), ("adopted", a["start"], a["auto0"]))

    def fb_at(self, start, *events):
        return [(r["verdict"], r["src"], r["event"]) for r in self.feedback() if r["start"] == start and (not events or r["event"] in events)]

    def test_manual_marks_good_bad_only_when_adopted_or_rejected(self):
        self.put(self.marks() + [{"id": "m1", "start": 500, "end": 520}])        # 候補のまま作っただけ: good / bad は書かない(見逃しの行だけ)
        self.assertEqual(self.fb_at(500), [("miss", "manual", "manual_add")])
        self.put([dict(m, status="adopted") if m["id"] == "m1" else m for m in self.marks()])
        rows = [r for r in self.feedback() if r["start"] == 500 and r["event"] == "adopt"]
        self.assertEqual([(r["verdict"], r["src"], r["event"]) for r in rows], [("good", "manual", "adopt")])
        self.assertNotIn("auto0", rows[0])
        self.assertEqual(len(self.fb_at(500)), 2)

    def test_manual_created_already_adopted_is_recorded(self):
        self.put(self.marks() + [{"id": "m2", "start": 700, "end": 730, "status": "adopted"}])
        self.assertEqual(sorted(self.fb_at(700)), [("good", "manual", "adopt"), ("miss", "manual", "manual_add")])

    def test_manual_add_records_nearest_auto(self):
        a, b, c = self.ms   # (10,40) (100,130) (200,230)、点数はどれも 5.0
        self.put(self.ms + [{"id": "m4", "start": 135, "end": 150}])
        row = [r for r in self.feedback() if r["event"] == "manual_add"][0]
        self.assertEqual((row["verdict"], row["src"], row["autoCount"]), ("miss", "manual", 3))
        self.assertEqual(row["nearAuto"], {"score": 5.0, "distance": 5.0, "start": b["start"], "end": b["end"], "status": ""})
        self.assertNotIn("auto0", row)
        self.put(self.marks() + [{"id": "m5", "start": 120, "end": 125}])        # 自動マークの中: 距離 0
        row = [r for r in self.feedback() if r["event"] == "manual_add"][-1]
        self.assertEqual(row["nearAuto"]["distance"], 0.0)

    def test_manual_add_without_auto_marks(self):
        self.put([])                                                             # 自動マークを全部消したあとに足す(同じ保存の中で消した自動マークは「その時あった」ものとして数える)
        self.put([{"id": "m6", "start": 300, "end": 320}])
        row = [r for r in self.feedback() if r["event"] == "manual_add"][0]
        self.assertEqual((row["autoCount"], row["nearAuto"]), (0, None))

    def test_manual_remove_recorded(self):
        self.put(self.marks() + [{"id": "m1", "start": 500, "end": 520}])
        self.put([m for m in self.marks() if m["id"] != "m1"])                    # 手で足した候補を消した
        self.assertEqual(self.fb_at(500), [("miss", "manual", "manual_add"), ("unmiss", "manual", "manual_remove")])

    def test_unadopt_recorded(self):
        a = self.ms[0]
        self.put([dict(a, status="adopted"), self.ms[1], self.ms[2]])
        self.put([dict(m, status="") if m["id"] == a["id"] else m for m in self.marks()])
        self.assertEqual(self.fb_at(a["start"]), [("good", "auto", "adopt"), ("retract", "auto", "unadopt")])
        row = [r for r in self.feedback() if r["event"] == "unadopt"][0]
        self.assertEqual(row["prevStatus"], "adopted")
        self.put([dict(m, status="rejected") if m["id"] == a["id"] else m for m in self.marks()])   # 候補 → 不採用は今までどおり reject だけ
        self.assertEqual([r["event"] for r in self.feedback() if r["start"] == a["start"]], ["adopt", "unadopt", "reject"])

    def test_delete_judged_rejected_and_exported(self):
        a, b, c = self.ms
        self.put([dict(a, status="rejected"), b, c])
        self.st.mark_exported(YT["videoId"], b["id"], "f/b.mp4", b["start"], b["end"])
        self.put([m for m in self.marks() if m["id"] == c["id"]])                 # 不採用の a と書き出し済みの b を削除
        rows = {r["start"]: r for r in self.feedback() if r["event"] == "delete_judged"}
        self.assertEqual((rows[a["start"]]["prevStatus"], rows[b["start"]]["prevStatus"]), ("rejected", "exported"))
        self.assertEqual(rows[a["start"]]["verdict"], "retract")

    def test_unchanged_save_writes_nothing(self):
        n = len(self.feedback())
        self.put(self.marks())
        self.assertEqual(len(self.feedback()), n)

    def test_auto_adoption_is_not_recorded(self):
        ids, _ = self.st.adopt_top(YT["videoId"], 2)
        self.assertEqual(len(ids), 2)
        self.assertEqual(self.feedback(), [])
        self.st.request_marks(YT["videoId"], [[400, 420]], 1)
        self.assertEqual(self.feedback(), [])

    def test_machine_adoption_is_marked_and_cleared_by_human(self):
        """機械が採用にしたマークには adoptedBy(auto / request)。書き出しの行にも付く(人の「よかった」と分ける)。人が状態を変えたら外れる"""
        ids, _ = self.st.adopt_top(YT["videoId"], 2)
        by = {m["id"]: m for m in self.marks()}
        self.assertEqual({by[i].get("adoptedBy") for i in ids}, {"auto"})
        rids, _, _ = self.st.request_marks(YT["videoId"], [[400, 420]], 0)
        self.assertEqual({m["id"]: m for m in self.marks()}[rids[0]].get("adoptedBy"), "request")
        m0 = by[ids[0]]
        self.st.mark_exported(YT["videoId"], m0["id"], "f/x.mp4", m0["start"], m0["end"])
        row = [r for r in self.feedback() if r["event"] == "export"][0]
        self.assertEqual((row["adoptedBy"], row["markId"]), ("auto", m0["id"]))
        self.put([dict(m, status="") if m["id"] == ids[1] else m for m in self.marks()])     # 人が候補に戻す
        self.put([dict(m, status="adopted") if m["id"] == ids[1] else m for m in self.marks()])   # 人が採用にし直す
        again = {m["id"]: m for m in self.marks()}[ids[1]]
        self.assertNotIn("adoptedBy", again)
        row = [r for r in self.feedback() if r["event"] == "adopt"][-1]
        self.assertNotIn("adoptedBy", row)
        self.assertEqual(row["markId"], ids[1])

    def test_reanalyzed_mark_keeps_auto0_in_feedback(self):
        a = self.ms[0]
        self.put([dict(a, status="adopted", start=a["start"] - 5), self.ms[1], self.ms[2]])
        self.auto((10, 40), (100, 130), (300, 330))                               # 再解析: a は手動に変わる
        kept = [m for m in self.marks() if m["status"] == "adopted"][0]
        self.assertEqual((kept["src"], kept["auto0"] if "auto0" in kept else None, kept["auto0Orig"]), ("manual", None, a["auto0"]))
        self.st.mark_exported(YT["videoId"], kept["id"], "f/a.mp4", kept["start"], kept["end"])
        row = [r for r in self.feedback() if r["event"] == "export"][0]
        self.assertEqual((row["src"], row["auto0"], row["dStart"], row["reanalyzed"]), ("manual", a["auto0"], -5.0, True))

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
        self.put(self.marks() + [{"id": "m3", "start": 900, "end": 960}])
        self.st.mark_exported(YT["videoId"], "m3", "f/m.mp4", 900, 960)
        self.st.mark_exported(YT["videoId"], "m3", "f/m.mp4", 900, 960)
        self.assertEqual(self.fb_at(900, "export"), [("good", "manual", "export")])

    def test_export_first_time_good_only(self):
        a = self.ms[0]
        self.st.mark_exported(YT["videoId"], a["id"], "f/a.mp4", a["start"], a["end"])
        self.st.mark_exported(YT["videoId"], a["id"], "f/a.mp4", a["start"], a["end"])   # 2回目は記録しない
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
        self.assertEqual(by[10.0]["auto0Orig"], [10.0, 40.0])   # 手動に変わっても最初の自動区間は残る(3つとも)
        self.assertEqual(by[100.0]["auto0Orig"], [100.0, 130.0])
        self.assertEqual(by[203.0]["auto0Orig"], [200.0, 230.0])
        self.assertNotIn("auto0Orig", by[400.0])
        self.assertEqual(by[400.0]["src"], "auto")
        st2 = store.Store(self.path)   # 保存し直しても消えない・画面から送り直しても書き換えられない
        self.assertEqual(st2.get(YT["videoId"])[0]["marks"], ms)
        r = self.put([dict(m, auto0Orig=[1, 2]) if m["start"] == 10.0 else m for m in ms])
        self.assertEqual([m for m in r["marks"] if m["start"] == 10.0][0]["auto0Orig"], [10.0, 40.0])
        r = self.put(r["marks"] + [{"id": "mx", "start": 700, "end": 710, "auto0Orig": [1, 2]}])
        self.assertNotIn("auto0Orig", [m for m in r["marks"] if m["id"] == "mx"][0])
        self.assertEqual(sum(1 for m in ms if abs(m["start"] - 10) < 1), 1)   # 不採用が復活して重複しない

    def test_exported_kept(self):
        self.auto((10, 40))
        m = self.marks()[0]
        self.st.mark_exported(YT["videoId"], m["id"], "f/a.mp4", m["start"], m["end"])
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
        with patch.object(store._fsio, "atomic_write", side_effect=OSError("disk full")):   # 保存(ytt.fsio.atomic_write)を失敗させる
            with self.assertRaises(ApiError) as c:
                self.put([])
            self.assertEqual(c.exception.status, 500)
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
        self.st.mark_exported(YT["videoId"], a["id"], "f.mp4", a["start"], a["end"])
        s = self.st.list()[0]
        self.assertEqual((s["marks"], s["exported"], s["adopted"], s["candidates"]), (3, 1, 0, 1))
        # v0.8.0: 一覧で「いつの配信か」を出すため、スタジオに追加した時刻も返す(足しただけ。更新の時刻より後にはならない)
        self.assertTrue(isinstance(s["createdAt"], int) and 0 < s["createdAt"] <= s["updatedAt"])


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


LIVE = {"recorder": "rec", "recording": "20261005-185300-U972n0ncl4k", "url": "https://www.youtube.com/watch?v=U972n0ncl4k", "videoId": "U972n0ncl4k"}
LIVE_SRC = {"kind": "live", "videoId": LIVE["recording"], "name": LIVE["recording"], "live": LIVE}


class TestLive(Base):
    """kind "live"(録画の部品で録っている配信)。既存の youtube・file の記録の形は変えない"""
    def test_ensure_list_get_shape(self):
        v = self.st.ensure(LIVE_SRC, "配信")
        self.assertEqual((v["id"], v["kind"], v["live"], v["title"]), (LIVE["recording"], "live", LIVE, "配信"))
        row = next(x for x in self.st.list() if x["id"] == LIVE["recording"])
        self.assertEqual((row["kind"], row["live"], row["marks"]), ("live", LIVE, 0))
        self.assertNotIn("live", next(x for x in self.st.list() if x["id"] == YT["videoId"]))   # youtube・file には足さない
        self.assertNotIn("live", self.video())
        self.assertEqual(self.st.get(LIVE["recording"])[0]["live"], LIVE)
        self.assertIsNone(self.st.media_path(LIVE["recording"]))
        row["live"]["url"] = "x"   # 呼び出し側が書き換えても内部に影響しない
        self.assertEqual(self.st.get(LIVE["recording"])[0]["live"]["url"], LIVE["url"])

    def test_ensure_twice_keeps_and_fills_empty_title(self):
        self.st.ensure(LIVE_SRC, "")
        rev = self.st.get(LIVE["recording"])[0]["rev"]
        self.assertEqual(self.st.ensure(LIVE_SRC, "")["rev"], rev)
        self.assertEqual(self.st.ensure(LIVE_SRC, "題", "ch")["title"], "題")
        v = self.st.ensure(LIVE_SRC, "別の題", "ch2")
        self.assertEqual((v["title"], v["channel"]), ("題", "ch"))   # 題・チャンネル名は空のときだけ入れる(既にあれば上書きしない。チャンネル名は配信者の名前 = 字幕の色を決める)
        rev = v["rev"]
        self.assertEqual(self.st.ensure(LIVE_SRC, "別の題", "ch2")["rev"], rev)   # 何も変わらなければ版も上げない
        self.st.ensure(dict(LIVE_SRC, videoId="20261005-185311", name="20261005-185311", live=dict(LIVE, recording="20261005-185311")), "", "ch3")
        self.assertEqual(self.st.get("20261005-185311")[0]["channel"], "ch3")   # 題が無くてもチャンネル名だけ入る

    def test_reload_roundtrip_and_bad_live_skipped(self):
        self.st.ensure(LIVE_SRC, "配信")
        self.st.put_video(LIVE["recording"], "配信", [{"id": "m1", "start": 5, "end": 20, "status": "adopted"}])
        st2 = store.Store(self.path)
        self.assertEqual(st2.get(LIVE["recording"])[0], self.st.get(LIVE["recording"])[0])
        with open(self.path, encoding="utf-8") as f:
            d = json.load(f)
        bad1 = json.loads(json.dumps(d["videos"][LIVE["recording"]]))
        bad1["id"] = "20261005-185301"      # live の録画 ID と違う
        bad2 = json.loads(json.dumps(d["videos"][LIVE["recording"]]))
        bad2["id"], bad2["live"] = "20261005-185302", {"recorder": "rec", "recording": "20261005-185302", "url": "http://evil.example/"}
        bad3 = {"id": "20261005-185303", "kind": "live"}     # live が無い
        d["videos"].update({"20261005-185301": bad1, "20261005-185302": bad2, "20261005-185303": bad3})
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump(d, f)
        st3 = store.Store(self.path)
        self.assertEqual(sorted(st3.videos), sorted([YT["videoId"], LIVE["recording"]]))
        self.assertTrue(st3.take_warning()[0])

    def test_analysis_entrypoints_refuse(self):
        self.st.ensure(LIVE_SRC, "配信")
        with self.assertRaises(ApiError) as c:
            self.st.adopt_top(LIVE["recording"], 3)
        self.assertEqual(c.exception.status, 400)
        with self.assertRaises(ApiError) as c:
            self.st.request_marks(LIVE["recording"], [[1, 5]], 0)
        self.assertEqual(c.exception.status, 400)
        self.assertIsNone(self.st.replace_auto(LIVE["recording"], [cand(1, 9)], {"spec": {}}, 100, {}))
        self.assertEqual(self.st.get(LIVE["recording"])[0]["marks"], [])

    def test_mark_exported_and_delete(self):
        self.st.ensure(LIVE_SRC, "配信")
        self.st.put_video(LIVE["recording"], "配信", [{"id": "m1", "start": 5, "end": 20, "status": "adopted"}])
        self.assertTrue(self.st.mark_exported(LIVE["recording"], "m1", "f/a.mp4", 5.0, 20.0, os.path.join(self.tmp, "a.mp4")))
        m = self.st.get(LIVE["recording"])[0]["marks"][0]
        self.assertEqual((m["status"], m["file"]), ("exported", "f/a.mp4"))
        # 解析していない録画の手のマーク(手で足した・採用・書き出し・削除)は、盛り上がりの学習の記録(feedback.jsonl)に書かない
        self.st.put_video(LIVE["recording"], "配信", [dict(m, status="adopted"), {"id": "m2", "start": 30, "end": 40, "status": ""}])
        self.st.put_video(LIVE["recording"], "配信", [])
        fb = os.path.join(self.tmp, "feedback.jsonl")
        self.assertFalse(os.path.exists(fb) and LIVE["recording"] in open(fb, encoding="utf-8").read())
        self.assertTrue(self.st.delete(LIVE["recording"]))
        self.assertFalse(self.st.has(LIVE["recording"]))

    def _live_exported(self, **kw):
        rid = LIVE["recording"]
        self.st.ensure(LIVE_SRC, "配信")
        self.st.put_video(rid, "配信", [{"id": "m1", "start": 5, "end": 20, "status": "adopted"}])
        self.assertTrue(self.st.mark_exported(rid, "m1", "f/a.mp4", 5.0, 20.0, os.path.join(self.tmp, "a.mp4"), **kw))
        return rid

    def mark(self, rid=None):
        return self.st.get(rid or LIVE["recording"])[0]["marks"][0]

    def test_archived_is_set_only_by_the_server_and_follows_path(self):
        """archived(本番版に入れ替え済みの印。線 D の P4): mark_exported(archived=True) だけが立てる。path・file と同じ扱い"""
        rid = self._live_exported()
        self.assertNotIn("archived", self.mark())
        self.assertEqual(next(x for x in self.st.list() if x["id"] == rid)["archived"], 0)
        # 既に書き出し済みで path が同じでも、印だけ立てられる
        self.assertTrue(self.st.mark_exported(rid, "m1", "f/a.mp4", 5.0, 20.0, os.path.join(self.tmp, "a.mp4"), True))
        m = self.mark()
        self.assertEqual((m["status"], m["file"], m["archived"]), ("exported", "f/a.mp4", True))
        self.assertEqual(next(x for x in self.st.list() if x["id"] == rid)["archived"], 1)
        # 画面からの保存(PUT)では立てられない・保たれる
        self.st.put_video(rid, "配信", [dict(m, archived=False, label="x")])
        self.assertTrue(self.mark()["archived"])
        self.st.put_video(rid, "配信", [dict(self.mark(), archived=True), {"id": "m2", "start": 30, "end": 40, "status": "adopted", "archived": True, "file": "z.mp4"}])
        ms = self.st.get(rid)[0]["marks"]
        self.assertTrue(ms[0]["archived"])
        self.assertNotIn("archived", ms[1])
        # 再読み込みしても残る(load_marks を通る)
        st2 = store.Store(self.path)
        self.assertTrue(st2.get(rid)[0]["marks"][0]["archived"])
        # 省略(None)は、同じファイルなら今のまま・違うファイルになったら外れる。False で外す。True に戻せる
        self.assertTrue(self.st.mark_exported(rid, "m1", "f/a.mp4", 5.0, 20.0, os.path.join(self.tmp, "a.mp4")))
        self.assertTrue(self.mark()["archived"])
        self.assertTrue(self.st.mark_exported(rid, "m1", "f/b.mp4", 5.0, 20.0, os.path.join(self.tmp, "b.mp4")))
        self.assertNotIn("archived", self.mark())
        self.st.mark_exported(rid, "m1", "f/b.mp4", 5.0, 20.0, os.path.join(self.tmp, "b.mp4"), True)
        self.st.mark_exported(rid, "m1", "f/b.mp4", 5.0, 20.0, os.path.join(self.tmp, "b.mp4"), False)
        self.assertNotIn("archived", self.mark())

    def test_archived_goes_away_when_the_mark_is_moved_or_status_changes(self):
        rid = self._live_exported(archived=True)
        m = self.mark()
        self.assertTrue(m["archived"])
        self.st.put_video(rid, "配信", [dict(m, start=6.0)])   # 時刻を変えたら書き出し済みが採用に戻る = 印も消える
        m2 = self.mark()
        self.assertEqual((m2["status"], m2["file"]), ("adopted", ""))
        self.assertNotIn("archived", m2)
        self.assertNotIn("path", m2)
        self.assertEqual(next(x for x in self.st.list() if x["id"] == rid)["archived"], 0)
        # 採用 → 書き出し済み(印なし)→ 状態を変える
        self.st.mark_exported(rid, "m1", "f/a.mp4", 6.0, 20.0, os.path.join(self.tmp, "a.mp4"), True)
        self.st.put_video(rid, "配信", [dict(self.mark(), status="rejected")])
        self.assertNotIn("archived", self.mark())
        # 古い記録(書き出し済みでない)に archived が付いていても読み込みで落ちる
        with open(self.path, encoding="utf-8") as f:
            d = json.load(f)
        d["videos"][rid]["marks"][0]["archived"] = True   # status は rejected
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump(d, f)
        self.assertNotIn("archived", store.Store(self.path).get(rid)[0]["marks"][0])

    def test_archived_never_on_non_live(self):
        yid = YT["videoId"]
        self.st.put_video(yid, "t", [{"id": "m1", "start": 5, "end": 20, "status": "adopted"}])
        self.assertTrue(self.st.mark_exported(yid, "m1", "f/a.mp4", 5.0, 20.0, os.path.join(self.tmp, "a.mp4"), True))   # youtube には付かない
        self.assertNotIn("archived", self.st.get(yid)[0]["marks"][0])
        self.assertNotIn("archived", next(x for x in self.st.list() if x["id"] == yid))
        with open(self.path, encoding="utf-8") as f:   # data.json を手で直されても、読み込みで外す
            d = json.load(f)
        d["videos"][yid]["marks"][0]["archived"] = True
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump(d, f)
        self.assertNotIn("archived", store.Store(self.path).get(yid)[0]["marks"][0])

    def test_conflict_with_other_kind(self):
        self.st.ensure(LIVE_SRC, "配信")
        with self.assertRaises(ApiError) as c:
            self.st.ensure(dict(YT, videoId=LIVE["recording"]), "")
        self.assertEqual(c.exception.status, 409)


class TestCheckLive(unittest.TestCase):
    def test_ok(self):
        self.assertEqual(yturl.check_live(LIVE), LIVE)
        self.assertEqual(yturl.check_live(dict(LIVE, url="https://youtu.be/U972n0ncl4k"))["videoId"], "U972n0ncl4k")
        self.assertEqual(yturl.check_live(dict(LIVE, recording="20261005-185300", url="https://www.youtube.com/@x/live"))["videoId"], "")

    def test_rejects(self):
        for kw in (dict(recorder="A"), dict(recorder="x" * 17), dict(recording="2026"), dict(recording="20261005-185300-"), dict(url="http://www.youtube.com/watch?v=U972n0ncl4k"),
                   dict(url="https://example.com/watch?v=U972n0ncl4k"), dict(url="https://www.youtube.com/" + "a" * 300), dict(url=1)):
            with self.assertRaises(ApiError, msg=kw):
                yturl.check_live(dict(LIVE, **kw))
        for x in (None, "x", [], {}):
            with self.assertRaises(ApiError):
                yturl.check_live(x)


if __name__ == "__main__":
    unittest.main(verbosity=1)
