"""home/cleanup.py(作業データの片付け。段9 9-2)の単体テスト。

    python -m unittest home/tests/test_cleanup.py
"""
import os
import shutil
import sys
import tempfile
import time
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, os.path.dirname(os.path.dirname(HERE)))
import cleanup as C  # noqa: E402


def touch(path, size=10, mtime=None):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(b"x" * size)
    if mtime is not None:
        os.utime(path, (mtime, mtime))
    return path


class CleanupTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="ytt-cleanup-")
        self.app = os.path.join(self.tmp, "app")
        self.now = [time.time()]
        self.env = {"YTT_DATA_DIR": os.path.join(self.tmp, "data")}   # 作業データの置き場所を一時フォルダに(cache・log の候補)
        os.makedirs(os.path.join(self.tmp, "data", "transcribe", "cache", "peaks"))
        self.cl = C.Cleanup(self.app, env=self.env, clock=lambda: self.now[0], keep_days=14)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_export_candidates_need_pack_and_done_status(self):
        v = os.path.join(self.tmp, "vid")
        a = touch(os.path.join(v, "a.mp4"), 100)
        b = touch(os.path.join(v, "b.mp4"), 100)
        c = touch(os.path.join(v, "c.mp4"), 100)
        cases = [{"id": "1", "title": "終わった配信", "status": "posted", "clips": [{"path": a, "exists": True, "pack": {"dir": a + "_pack"}}, {"path": b, "exists": True, "pack": None}]},
                 {"id": "2", "title": "作業中", "status": "", "clips": [{"path": c, "exists": True, "pack": {"dir": c + "_pack"}}]}]
        r = self.cl.candidates(cases)
        exp = next(k for k in r["kinds"] if k["kind"] == "export")
        self.assertEqual([i["path"] for i in exp["items"]], [a])              # パックがあり、案件が投稿済み/見送りのものだけ
        self.assertIn("終わった配信", exp["items"][0]["note"])
        self.assertEqual(exp["bytes"], 100)
        self.assertEqual(r["bytes"], 100)
        self.assertEqual(r["keepDays"], 14)

    def test_work_orphans(self):
        v = os.path.join(self.tmp, "vid")
        a = touch(os.path.join(v, "a.mp4"))
        touch(os.path.join(v, "作業用", "a.transcript.json"))        # 元の動画がある → 候補にしない
        orphan = touch(os.path.join(v, "作業用", "gone.clip.json"))   # 元の動画が無い → 候補
        touch(os.path.join(v, "作業用", "memo.txt"))                  # 知らない形 → 候補にしない
        r = self.cl.candidates([{"id": "1", "status": "", "clips": [{"path": a, "exists": True}]}])
        work = next(k for k in r["kinds"] if k["kind"] == "work")
        self.assertEqual([i["path"] for i in work["items"]], [orphan])
        self.assertIn("gone", work["items"][0]["note"])

    def test_cache_logs_and_intake(self):
        peaks = os.path.join(self.tmp, "data", "transcribe", "cache", "peaks")
        p1 = touch(os.path.join(peaks, "x.peaks"), 50)
        old = touch(os.path.join(self.app, "logs", "portal.old.log"), 20)
        touch(os.path.join(self.app, "logs", "portal.log"), 20)      # 今のログは候補にしない
        runs1 = touch(os.path.join(self.app, "logs", "autorun-runs.jsonl.1"), 20)
        intake = os.path.join(self.tmp, "intake")
        old_day = time.strftime("%Y-%m-%d", time.localtime(self.now[0] - 20 * 86400))
        new_day = time.strftime("%Y-%m-%d", time.localtime(self.now[0] - 2 * 86400))
        touch(os.path.join(intake, "受付済み", old_day, "v.mp4"), 30)
        touch(os.path.join(intake, "受付済み", new_day, "v.mp4"), 30)
        r = self.cl.candidates([], intake_dir=intake)
        by = {k["kind"]: k for k in r["kinds"]}
        self.assertEqual([i["path"] for i in by["cache"]["items"]], [p1])
        self.assertEqual(sorted(i["path"] for i in by["log"]["items"]), sorted([old, runs1]))
        self.assertEqual([i["name"] for i in by["intake"]["items"]], [old_day])
        self.assertTrue(by["intake"]["items"][0]["dir"])

    def test_move_only_known_and_purge(self):
        peaks = os.path.join(self.tmp, "data", "transcribe", "cache", "peaks")
        p1 = touch(os.path.join(peaks, "x.peaks"), 50)
        p2 = touch(os.path.join(peaks, "y.peaks"), 50)
        r = self.cl.candidates([])
        ids = [i["id"] for i in next(k for k in r["kinds"] if k["kind"] == "cache")["items"]]
        res = self.cl.move([ids[0], "nope", 3])
        self.assertEqual([m["path"] for m in res["moved"]], [p1])
        self.assertEqual(res["unknown"], ["nope", "3"])
        self.assertFalse(os.path.exists(p1))
        self.assertTrue(os.path.exists(p2))
        day = time.strftime("%Y-%m-%d", time.localtime(self.now[0]))
        dest = os.path.join(self.app, "ごみ箱", day, "cache", "x.peaks")
        self.assertTrue(os.path.isfile(dest))
        with open(os.path.join(self.app, "ごみ箱", day, "manifest.jsonl"), encoding="utf-8") as f:
            self.assertIn(p1.replace("\\", "\\\\"), f.read())
        self.assertEqual(self.cl.move([ids[0]])["unknown"], [ids[0]])   # 移した物はもう候補ではない
        # 同じ名前が来たら (1) を付ける
        touch(os.path.join(peaks, "x.peaks"), 5)
        r = self.cl.candidates([])
        ids = {i["name"]: i["id"] for i in next(k for k in r["kinds"] if k["kind"] == "cache")["items"]}
        self.cl.move([ids["x.peaks"]])
        self.assertTrue(os.path.isfile(os.path.join(self.app, "ごみ箱", day, "cache", "x (1).peaks")))
        # purge: 14 日を過ぎた日付のフォルダだけ消す
        self.assertEqual(self.cl.purge(), 0)
        self.now[0] += 15 * 86400
        self.assertEqual(self.cl.purge(), 1)
        self.assertFalse(os.path.isdir(os.path.join(self.app, "ごみ箱", day)))

    def test_paths_not_offered_cannot_be_moved(self):
        secret = touch(os.path.join(self.tmp, "secret.txt"))
        res = self.cl.move([C._id(secret)])
        self.assertEqual(res["moved"], [])
        self.assertTrue(os.path.exists(secret))


if __name__ == "__main__":
    unittest.main()
