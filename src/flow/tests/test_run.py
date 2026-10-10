# -*- coding: utf-8 -*-
"""pipeline/run.py(① の経路。RS1-7)のテスト。  py -3.10 -m unittest src/flow/tests/test_run.py -v
段の中身の細かい動きは src/home/tests/test_autorun.py(AutoRunner が Runner を継いだ形)で見る。ここは入口の関数・入力の形・hook の既定と、
層の決まり(home を知らずに読める)だけ。
"""
import os
os.environ.setdefault("YTT_DATA_DIR", "inplace")   # 作業データは読み書きしないが、ほかのテストとそろえる
import subprocess
import sys
import tempfile
import unittest

SRC = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))   # tests -> pipeline -> src
sys.path.insert(0, SRC)
from flow import run as R  # noqa: E402


class FakeClient:
    """「編集」の文字起こしの API の最小の真似(設定・ジョブを入れる・ジョブの一覧)"""

    def __init__(self):
        self.calls = []

    def call(self, tool, method, path, body=None):
        self.calls.append((tool, method, path))
        if path == "/api/settings":
            return 200, {"model": "small", "unknown": "x"}
        if path == "/api/transcribe":
            return 200, {"id": "j1"}
        if path == "/api/jobs":
            return 200, {"jobs": [{"id": "j1", "state": "done", "tid": "t1"}]}
        return 404, {}

    def ok(self, tool, method, path, body=None):
        st, obj = self.call(tool, method, path, body)
        if st != 200:
            raise R.StepError("HTTP %d" % st)
        return obj


class TestImport(unittest.TestCase):
    def test_imports_without_home(self):
        """home(案件・設定・届ける部品)を sys.path に置かずに読める = 層の向き"""
        code = ("import sys; sys.path.insert(0, %r); import flow.run as r; "
                "bad = [m for m in ('autorun', 'cases', 'prefs', 'deliver', 'friend_feedback', 'manage') if m in sys.modules]; "
                "print(bad); sys.exit(1 if bad else 0)") % SRC
        p = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=60)
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)


class TestFromInput(unittest.TestCase):
    def test_from_mode(self):
        self.assertEqual(R.FROM_MODE, {None: "full", "analyze": "full", "export": "adopted", "transcribe": R.DOC_MODE})

    def test_video(self):
        r = R.Run.from_input({"videoId": "abcdefghijk"})
        self.assertEqual((r.video_id, r.mode, r.top, r.doc_id, r.source_path, r.state), ("abcdefghijk", "full", 3, None, None, "queued"))
        self.assertEqual([s["key"] for s in r.steps], list(R.MODE_STEPS["full"]))
        self.assertEqual(R.Run.from_input({"videoId": "abcdefghijk", "top": 5}, "export").mode, "adopted")
        self.assertEqual(R.Run.from_input({"videoId": "abcdefghijk", "top": 5}, "export").top, 5)
        self.assertEqual(R.Run.from_input({"videoId": "abcdefghijk"}, "transcribe").mode, R.DOC_MODE)
        with self.assertRaises(ValueError):
            R.Run.from_input({"videoId": "abcdefghijk"}, "pack")
        with self.assertRaises(ValueError):
            R.Run.from_input({"videoId": "abcdefghijk", "top": 99})

    def test_doc_and_path(self):
        r = R.Run.from_input({"docId": "d1"})
        self.assertEqual((r.doc_id, r.mode, r.title, r.video_id), ("d1", R.DOC_MODE, "d1", None))
        r = R.Run.from_input({"path": "/x/clip.mp4", "title": "題"})
        self.assertEqual((r.source_path, r.mode, r.title), ("/x/clip.mp4", "file", "題"))
        self.assertEqual(R.Run.from_input({"path": "/x/clip.mp4"}).title, "clip.mp4")
        for bad in ({}, None, {"videoId": ""}, "abc"):
            with self.assertRaises(ValueError, msg=bad):
                R.Run.from_input(bad)

    def test_spec_not_saved(self):
        """spec は run() が置くだけ(待ちの記録・public には出さない)"""
        r = R.Run.from_input({"docId": "d1"})
        self.assertIsNone(r.spec)
        self.assertNotIn("spec", r.saved())
        self.assertNotIn("spec", r.public())

    def test_restore_skips_removed_post_analyze(self):
        """消した「あとから解析」(mode post_analyze。RS4)が以前の待ちの記録に残っていても、落ちずに読み飛ばす(同じ形の full は戻る)"""
        d = R.Run.from_input({"videoId": "abcdefghijk"}).saved()
        self.assertIsNotNone(R.Run.restore(d))
        self.assertNotIn("post_analyze", R.MODE_STEPS)
        self.assertIsNone(R.Run.restore(dict(d, mode="post_analyze", steps=[{"key": "analyze", "state": "run", "detail": ""}])))


class TestHooks(unittest.TestCase):
    def test_defaults_know_nothing(self):
        rn = R.Runner(None)
        run = R.Run.from_input({"docId": "d1"})
        run.resumed = True
        rn._await_tools(run)
        self.assertFalse(run.resumed)
        self.assertIsNone(rn._checkpoint(run))
        self.assertEqual(rn._studio_video("abcdefghijk"), {})
        self.assertIsNone(rn._friend_length())
        self.assertEqual(rn._docs(), [])
        self.assertIsNone(rn._pick_doc([], "abcdefghijk", "m1", "/x.mp4"))
        self.assertEqual(rn._pref("cut", "none"), "none")
        self.assertFalse(rn._live_auto_origin("/x.mp4"))
        self.assertIsNone(rn._auto_streamer(run))
        self.assertIsNone(run.streamer)
        self.assertIsNone(rn._after_pack(run, {}, ""))
        self.assertFalse(rn._remember_styles("t1", {"A": {"color": "#112233"}}))
        self.assertFalse(rn._remember_doc_streamer("t1", "A"))
        self.assertIsNone(rn.find_pack("/x.mp4"))
        self.assertFalse(rn.closed)
        self.assertEqual(rn._cut_method(), "none")


class TestRun(unittest.TestCase):
    def setUp(self):
        fd, self.media = tempfile.mkstemp(suffix=".mp4")
        os.close(fd)
        self.addCleanup(os.remove, self.media)

    def test_file_transcribe(self):
        """動画ファイル → 文字起こし(素の Runner。設定は「編集」のまま = TX_KEYS だけ渡す)"""
        c = FakeClient()
        r = R.run(c, {"path": self.media}, spec={"x": 1}, hooks=R.Runner(c, poll=0, sleep=lambda s: None))
        self.assertEqual(r.spec, {"x": 1})
        self.assertEqual((r.doc_id, r.docs, r.new_docs), ("t1", ["t1"], ["t1"]))
        self.assertEqual(r.step("transcribe")["state"], "done")
        self.assertEqual(r.message, "完了")
        self.assertIn(("transcribe", "POST", "/api/transcribe"), c.calls)

    def test_missing_file_default_runner(self):
        """hooks なし = 素の Runner。動画が無ければ StepError(ツールは呼ばない)"""
        c = FakeClient()
        with self.assertRaises(R.StepError):
            R.run(c, {"path": self.media + ".nai.mp4"})
        self.assertEqual(c.calls, [])

    def test_doc_nothing_to_do(self):
        """文書 → 文字起こし → パック: 文字起こし済み・パック済みなら両方飛ばして「やることがありませんでした」(hook で文書の一覧だけ渡す)"""
        media = self.media

        class Docs(R.Runner):
            def _docs(self):
                return [{"id": "d1", "title": "題", "count": 3, "sourcePath": media}]
        c = FakeClient()
        rn = Docs(c, poll=0, sleep=lambda s: None, find_pack=lambda p: {"dir": "/packs/x"})
        r = R.run(c, R.Run.from_input({"docId": "d1"}), hooks=rn)
        self.assertEqual([s["state"] for s in r.steps], ["skip", "skip"])
        self.assertTrue(r.nothing)
        self.assertTrue(r.message.startswith(R.NOTHING_MESSAGE))
        self.assertEqual(r.title, "題")


if __name__ == "__main__":
    unittest.main()
