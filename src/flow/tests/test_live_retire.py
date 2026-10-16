"""録画の片付けの ② の口(src/flow/live_retire.py の Retire。OPT2 の 7x-1)と、書き出しのジョブの切り詰め(live_export の _trim・cleaned_up。7e-3)のテスト。
見回り・期限・録画元への delete は ④ の側(src/manage/keep/tests/test_live_cleanup.py)。ここは判断と記録の書き方だけを、本物の Exporter で確かめる。
実行(リポジトリ直下から): python -m unittest src/flow/tests/test_live_retire.py -v
"""
import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

os.environ.setdefault("YTT_DATA_DIR", "inplace")
SRC = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))   # tests -> flow -> src
if SRC not in sys.path:
    sys.path.insert(0, SRC)

from flow import live_export as LX  # noqa: E402
from flow import live_retire as LR  # noqa: E402
from ytt import fsio  # noqa: E402

RELEASE = 1790000000.0
REC = "20261005-120000-abcdefghijk"


class FakeExLive:
    def find(self, rid):
        return {"id": rid, "name": rid}


class Detector:
    def __init__(self):
        self.forgot = []

    def forget(self, rc, rec):
        self.forgot.append((rc, rec))


class Host:
    """親の代わり(exporter・detector。marks は試験ごとに足す)"""

    def __init__(self, store, out):
        self.exporter = LX.Exporter(FakeExLive(), store, lambda: out)
        self.detector = Detector()


class Book:
    def __init__(self, got):
        self.got = got

    def adopted(self, rc_id, rec):
        if isinstance(self.got, Exception):
            raise self.got
        return self.got


class RetireTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="ytt-live-retire-")
        self.out = os.path.join(self.tmp, "out")
        os.makedirs(self.out)
        self.host = Host(os.path.join(self.tmp, "live"), self.out)
        self.ex = self.host.exporter
        self.studio = []
        self.rt = LR.Retire(self.host, studio_marks=lambda rec: self.studio)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def job(self, n, rec=REC, state="done", arc="done", keep=None, at=None, **kw):
        j = {"id": "lx-%010x" % (n + 100 * len(self.ex.jobs)), "recorder": "local", "recording": rec, "markId": "lm-%012x" % n, "n": n,
             "state": state, "created": LX.now_iso(), "studio": {"video": rec, "mark": "m%d" % n, "start": n * 10.0, "end": n * 10.0 + 5}}
        if arc:
            j["archive"] = {"state": arc, "at": at or LX.now_iso(), "keep": keep}
        j.update(kw)
        self.ex.jobs.append(j)
        return j

    def saved(self):
        return fsio.read_json_file(os.path.join(self.tmp, "live", "exports.json"), 1 << 20)["jobs"]

    def test_verdict(self):
        """LD-1: 全部書き出し済み・採用のまま書き出していないマークなし・アーカイブ化を確かめた(archived が "")で消してよい"""
        V = LR.Verdict
        ok = lambda: ""   # noqa: E731  アーカイブ化を確かめた
        asked = []
        self.assertEqual(self.rt.verdict("local", REC, archived=ok), V(False, "", False))   # ジョブが無い = マークの無い録画の道へ
        self.job(1, arc=None)
        self.assertEqual(self.rt.verdict("local", REC, archived=ok), V(True, "", True))
        self.assertEqual(self.rt.verdict("local", REC).why, LR.NOT_ARCHIVED)   # 確かめる口が無い = 確かめられない
        self.assertEqual(self.rt.verdict("local", REC, archived=lambda: LR.NOT_ARCHIVED + "(処理中)").why, LR.NOT_ARCHIVED + "(処理中)")
        self.assertEqual(self.rt.verdict("local", REC, stale=True, archived=lambda: LR.NOT_ARCHIVED + "(x)"), V(True, "", False))   # 期限: 消してよい
        self.assertEqual(self.rt.verdict("local", REC, archived=lambda: 1 / 0).why, LR.NOT_ARCHIVED)   # 確かめる部品が落ちても消さない
        self.studio = [{"id": "m1", "status": "adopted", "start": 10.0, "end": 15.0}]   # 同じ区間の採用は数えない
        self.assertEqual(self.rt.verdict("local", REC, archived=ok), V(True, "", True))
        self.studio = [{"id": "m1", "status": "adopted", "start": 11.0, "end": 15.0}]   # 区間を直した
        self.assertEqual(self.rt.verdict("local", REC, archived=lambda: asked.append(1) or "").why, "採用のまま書き出していないマークがある")
        self.assertEqual(asked, [])   # ほかの理由があれば アーカイブ化は確かめない(yt-dlp を呼ばない)
        self.studio = None
        self.assertEqual(self.rt.verdict("local", REC, archived=ok).why, LR.STUDIO_UNKNOWN)
        self.studio = []
        self.job(2, state="error", arc=None)   # 書き出せなかった(失敗)
        self.assertEqual(self.rt.verdict("local", REC, archived=ok), V(True, LR.NOT_EXPORTED, False))
        self.assertEqual(self.rt.verdict("local", REC, stale=True, archived=ok), V(True, "", False))   # 期限を過ぎた: 消してよい
        self.studio = [{"id": "m9", "status": "adopted", "start": 90.0, "end": 95.0}]
        self.assertEqual(self.rt.verdict("local", REC, stale=True, archived=ok), V(True, "採用のまま書き出していないマークがある", False))
        self.job(3, state="error", arc="fetch", needsArchive=True)
        self.assertEqual(self.rt.verdict("local", REC, stale=True).why, "アーカイブからの書き出しの途中・待ち")   # ほかの理由は期限でも消さない
        self.ex.jobs[:] = []
        self.job(1, state="wait", arc=None, **{"from": "archive"})   # M7 の採用: アーカイブから書き出すのを待っている
        self.assertEqual(self.rt.verdict("local", REC, archived=ok).why, "アーカイブからの書き出しの途中・待ち")
        self.ex.jobs[:] = []
        self.job(1, state="encode", arc=None)
        self.assertEqual(self.rt.verdict("local", REC).why, "書き出しの途中")
        self.ex.jobs[:] = []
        self.job(1, recordingDeleted=LX.now_iso())
        self.assertEqual(self.rt.verdict("local", REC).why, "前に消しました")
        self.assertTrue(LR.stale_ok(LR.NOT_EXPORTED) and LR.stale_ok(LR.NOT_ARCHIVED + "(x)"))
        self.assertFalse(LR.stale_ok("書き出しの途中") or LR.stale_ok(None))

    def test_verdict_reads_marks_book(self):
        """親がマークの置き場(marks.adopted)を持てばそこを読み、studio_marks には聞かない。読めなければ確かめられない"""
        self.job(1)
        self.studio = None   # 聞いたら「確かめられない」になる
        self.host.marks = Book([{"id": "m1", "status": "exported", "start": 10.0, "end": 15.0}])
        self.assertEqual(self.rt.verdict("local", REC, archived=lambda: ""), LR.Verdict(True, "", True))
        self.host.marks = Book(RuntimeError("x"))
        self.assertEqual(self.rt.verdict("local", REC).why, LR.STUDIO_UNKNOWN)
        self.host.marks = Book(None)
        self.assertEqual(self.rt.verdict("local", REC).why, LR.STUDIO_UNKNOWN)

    def test_recording_deleted(self):
        ms = self.ex.marks
        j1, j2 = self.job(1), self.job(2)
        other = self.job(3, rec="20261005-130000-abcdefghijk")
        ms.upsert("local", REC, "lm-%012x" % 1, 1, LX.epoch_iso(RELEASE + 10), LX.epoch_iso(RELEASE + 15))
        self.assertEqual(self.rt.recording_deleted("local", REC), "")   # 入れ替え済みでない(3 日): 正本は残す
        self.assertTrue(os.path.exists(ms.path("local", REC)))
        self.assertTrue(j1["recordingDeleted"] and j2["recordingDeleted"])
        self.assertNotIn("recordingDeleted", other)
        self.assertEqual(sorted(j["id"] for j in self.saved() if j.get("recordingDeleted")), sorted([j1["id"], j2["id"]]))   # 記録に書いた
        self.assertEqual(self.host.detector.forgot, [("local", REC)])   # 検出の記録も
        self.assertEqual(self.rt.recording_deleted("local", REC, replaced=True), "dropped")
        self.assertFalse(os.path.exists(ms.path("local", REC)))
        self.assertEqual(self.rt.recording_deleted("local", REC, replaced=True), "gone")
        # スタジオなしの採用の印が案件に写っていない: 正本は残す
        rec2 = "20261005-140000-abcdefghijk"
        ms.adopt("local", rec2, "a00000000000f", RELEASE, 10.0, 15.0)
        self.assertEqual(self.rt.recording_deleted("local", rec2, replaced=True), "unsettled")
        self.assertTrue(os.path.exists(ms.path("local", rec2)))
        self.assertEqual(self.rt.recording_deleted("local", "../x", replaced=True), "unsettled")   # 形の悪い id: 読めない = 消さない
        del self.host.detector   # 検出の部品の無い親
        self.assertEqual(self.rt.recording_deleted("local", rec2), "")

    def test_has_marks(self):
        self.assertIs(self.rt.has_marks("local", REC), False)
        self.ex.marks.upsert("local", REC, "lm-000000000001", 1, LX.epoch_iso(RELEASE), LX.epoch_iso(RELEASE + 1))
        self.assertIs(self.rt.has_marks("local", REC), True)
        self.assertIsNone(self.rt.has_marks("local", "../x"))   # 読めない = 消さない

    def test_keeps_and_keep_deleted(self):
        at = LX.epoch_iso(RELEASE)
        j1 = self.job(1, keep=os.path.join(self.out, "a.mp4"), at=at)
        self.job(2, keep=None)                                   # 退避していない
        self.job(3, arc="error", keep=os.path.join(self.out, "c.mp4"))   # 入れ替えていない
        j4 = self.job(4, keep=os.path.join(self.out, "d.mp4"))
        j4["archive"]["keepDeleted"] = LX.now_iso()            # もう消した
        root, cand = self.rt.keeps()
        self.assertEqual(root, self.out)
        self.assertEqual(cand, [{"id": j1["id"], "keep": j1["archive"]["keep"], "at": RELEASE}])
        self.assertEqual(self.rt.keep_deleted([]), 0)
        self.assertEqual(self.rt.keep_deleted([j1["id"], "lx-0000000000"]), 1)
        self.assertTrue(j1["archive"]["keepDeleted"])
        self.assertTrue(any(j["id"] == j1["id"] and j["archive"].get("keepDeleted") for j in self.saved()))
        self.assertEqual(self.rt.keep_deleted([j1["id"]]), 0)   # 2 回は記さない
        self.assertEqual(self.rt.keeps()[1], [])
        self.ex.out_dir = lambda: 1 / 0                         # 書き出し先が分からない: 候補なし
        self.assertEqual(self.rt.keeps(), (None, []))

    def test_trim_cleaned_up_first(self):
        """7e-3: 終わったジョブを切るときは、録画と速報版の片付けが済んだ物から切る(足りなければ残りの古い順)"""
        stamp = LX.now_iso()
        old = [self.job(1, keep="k1"), self.job(2), self.job(3)]           # 片付けがまだ(古い)
        done1 = self.job(4, recordingDeleted=stamp)                        # 退避なし・録画を消した = 済み
        half = self.job(5, keep="k5", recordingDeleted=stamp)              # 速報版がまだ
        done2 = self.job(6, keep="k6", recordingDeleted=stamp)
        done2["archive"]["keepDeleted"] = stamp
        running = self.job(7, state="encode", arc=None)
        self.assertEqual([LX.cleaned_up(j) for j in old + [done1, half, done2]], [False, False, False, True, False, True])
        with mock.patch.object(LX, "KEEP_JOBS", 4):
            self.ex._trim()
        self.assertEqual(self.ex.jobs, old + [half, running])
        with mock.patch.object(LX, "KEEP_JOBS", 2):
            self.ex._trim()
        self.assertEqual(self.ex.jobs, old[2:] + [half, running])   # 済んだ物が無ければ古い順
        with mock.patch.object(LX, "KEEP_JOBS", 5):
            self.ex._trim()
        self.assertEqual(len(self.ex.jobs), 3)


if __name__ == "__main__":
    unittest.main()
