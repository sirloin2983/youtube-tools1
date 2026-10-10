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
from flow import spec as SP, tools as T  # noqa: E402


class FakeClient:
    """「編集」の文字起こしと cut2resolve の API の最小の真似(ジョブを入れる・ジョブの一覧・受け渡しの JSON・パック)。設定(/api/settings)は持たない = 段は読まない"""

    def __init__(self):
        self.calls = []
        self.bodies = {}

    def call(self, tool, method, path, body=None):
        self.calls.append((tool, method, path))
        self.bodies[path.split("?")[0]] = body
        if path == "/api/transcribe":
            return 200, {"id": "j1"}
        if path == "/api/jobs":
            return 200, {"jobs": [{"id": "j1", "state": "done", "tid": "t1"}]}
        if path.startswith("/api/edit?"):
            return 200, {"edit": None, "rev": 0}
        if path == "/api/export-file":
            return 200, {"path": "/x/t1.transcript.json"}
        if path == "/api/build":
            return 200, {"job": {"id": "c1", "state": "running"}}
        if path.startswith("/api/job?"):
            return 200, {"id": "c1", "state": "done", "result": {"outDir": "/x/clip_pack", "files": []}}
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
        """動画ファイル → 文字起こし(素の Runner)。要求の設定は束から(RS6 b-0。GET /api/settings は読まない)"""
        c = FakeClient()
        r = R.run(c, {"path": self.media}, spec={"transcribe": {"model": "large-v3"}, "post": {"autoDict": False}},
                  hooks=R.Runner(c, poll=0, sleep=lambda s: None))
        self.assertEqual(r.spec, SP.validate(SP.merge({"transcribe": {"model": "large-v3"}, "post": {"autoDict": False}})))
        self.assertEqual((r.doc_id, r.docs, r.new_docs), ("t1", ["t1"], ["t1"]))
        self.assertEqual(r.step("transcribe")["state"], "done")
        self.assertEqual(r.message, "完了")
        self.assertIn(("transcribe", "POST", "/api/transcribe"), c.calls)
        self.assertNotIn("/api/settings", [x[2] for x in c.calls])
        self.assertEqual(c.bodies["/api/transcribe"], dict(SP.tx_opts(r.spec), sourcePath=self.media))
        self.assertEqual((c.bodies["/api/transcribe"]["model"], c.bodies["/api/transcribe"]["autoDict"]), ("large-v3", False))
        self.assertNotIn("engine", c.bodies["/api/transcribe"])   # 機器から決まるエンジンと同じなら書かない

    def test_bad_spec_does_not_start(self):
        """形の違う束は段を始めない(ValueError。ツールは呼ばない)"""
        c = FakeClient()
        for bad in ({"x": 1}, {"pack": {"size": "1x1"}}, {"transcribe": {"engine": "nai"}}):
            with self.assertRaises(ValueError, msg=bad):
                R.run(c, {"path": self.media}, spec=bad)
        self.assertEqual(c.calls, [])

    def test_doc_pack_reads_spec(self):
        """文書 → パック: パックの作り方は束の pack 節(大きさ・1 段の文字数・音量・カットの方法と無音の値)。画面の値が無ければ fps は固定の 30"""
        media = self.media

        class Docs(R.Runner):
            def _docs(self):
                return [{"id": "d1", "title": "題", "count": 1, "sourcePath": media, "segments": [{"start": 0, "end": 1, "text": "あ"}]}]
        c = FakeClient()
        spec = {"pack": {"size": "1920x1080", "volume": 50, "cut": "silence", "cutSilence": {"noise": -40}, "wrapChars": {"horizontal": 12}}}
        r = R.run(c, R.Run.from_input({"docId": "d1"}), spec=spec, hooks=Docs(c, poll=0, sleep=lambda s: None))
        self.assertEqual(r.step("pack")["state"], "done", r.steps)
        body = c.bodies["/api/build"]
        self.assertEqual(body["spec"], {"video": media, "transcript": "/x/t1.transcript.json", "mode": "silence",
                                        "silence": {"noise": -40, "min": 0.6, "pad": 0.15}})
        self.assertEqual(body["output"], {"textplus": True, "textplusWrap": 12, "textplusSize": "1920x1080", "textplusFps": "30",
                                          "speakerColors": True, "volume": 50})
        self.assertEqual(r.packs, [os.path.normpath("/x/clip_pack")])

    def test_tools_are_injected(self):
        """段は self.tools に頼む(既定は HttpTools(client)。tools を渡せば client は使わない)"""
        self.assertIsInstance(R.Runner(None).tools, T.HttpTools)
        calls = []

        class Tools(T.HttpTools):
            def transcribe_start(self, req, bundle=None):
                calls.append(("start", req["sourcePath"], bundle["transcribe"]["model"]))
                return "j9"

            def jobs(self):
                return [{"id": "j9", "state": "done", "tid": "t9"}]
        r = R.run(None, {"path": self.media}, tools=Tools(None))
        self.assertEqual((calls, r.doc_id), ([("start", self.media, "small")], "t9"))

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


class AdoptTools(T.HttpTools):
    """採用の段だけを見る道具(スタジオの採用の答えを決めて返す。本文を覚える)"""

    def __init__(self, res):
        super().__init__(None)
        self.res, self.bodies = res, []

    def request_marks(self, body):
        self.bodies.append(body)
        return self.res


class TestAdopt(unittest.TestCase):
    """採用の段(F-5。RS6 b-A): 規則はスタジオの 1 つ(request_marks の先)。段は数と余白を束 + Run の欄から渡し、答えを進み具合の文と run.marks にする"""

    def adopt(self, res, mode="full", top=3, ranges=None, spec=None, fresh=None):
        run = R.Run("abcdefghijk", "配信", mode, top, ranges=ranges, fresh=fresh)
        run.spec = SP.validate(SP.merge(spec))
        tools = AdoptTools(res)
        rn = R.Runner(None, tools=tools)
        st = run.step("adopt")
        st["state"] = "run"
        out = rn._step_adopt(run, st, {"duration": 1000})
        return out, st, run, tools.bodies[0]

    def test_human_adoption_counts_and_rest_is_filled(self):
        """人が 1 本採用した配信の再実行: 上限までの残り 2 本を自動で足す(以前は「人が採用済みなら自動は 0」で飛ばした)"""
        out, st, run, body = self.adopt({"rangeIds": [], "humanIds": ["h1"], "autoIds": ["a2", "a3"], "added": ["a2", "a3"]})
        self.assertEqual((out, st["state"], body), (None, "run", {"id": "abcdefghijk", "ranges": [], "top": 3}))
        self.assertEqual(st["detail"], "人が採用した 1 本・自動で 2 本を足しました(点数の高い順)")
        self.assertIsNone(run.marks)   # 配信の全部(区間の依頼でなければ扱う範囲は変えない)

    def test_nothing_new_is_skip(self):
        out, st, _run, _body = self.adopt({"rangeIds": [], "humanIds": ["h1", "h2", "h3"], "autoIds": [], "added": []})
        self.assertEqual((out, st["state"]), (None, "skip"))
        self.assertIn("人が採用した 3 本", st["detail"])
        self.assertIn("新しく採用したものはありません", st["detail"])

    def test_no_candidates_stops(self):
        out, st, run, _body = self.adopt({"rangeIds": [], "humanIds": [], "autoIds": [], "added": []})
        self.assertEqual((out, st["state"], run.message), ("stop", "skip", "採用できる候補がありませんでした"))

    def test_request_ranges_use_bundle_pad_and_set_marks(self):
        """友人の依頼(URL): 区間に束の adopt.pad の余白・扱うマークは区間 ∪ 人の採用 ∪ 自動・足りなければ知らせる"""
        res = {"rangeIds": ["r1"], "humanIds": ["h1"], "autoIds": ["a1"], "added": ["r1", "a1"]}
        out, st, run, body = self.adopt(res, mode="request", top=4, ranges=[(100.0, 120.0)], spec={"adopt": {"pad": 5.0}},
                                        fresh={"title": "題", "channel": "ch"})
        self.assertEqual(body, {"id": "abcdefghijk", "ranges": [[95.0, 125.0]], "top": 4, "title": "題", "channel": "ch"})
        self.assertEqual((out, st["state"], run.marks), (None, "run", ("r1", "h1", "a1")))
        self.assertEqual(st["detail"], "指定の区間 1 個(前後に 5 秒の余白)・人が採用した 1 本・自動で 1 本を足しました(点数の高い順)。候補が足りず 1 本は選べませんでした")

    def test_top_from_bundle_when_run_has_none(self):
        _out, _st, _run, body = self.adopt({"autoIds": ["a1"], "added": ["a1"]}, top=None, spec={"adopt": {"top": 5}})
        self.assertEqual(body["top"], 5)


if __name__ == "__main__":
    unittest.main()
