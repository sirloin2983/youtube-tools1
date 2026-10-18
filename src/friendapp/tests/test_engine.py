"""src/friendapp/engine.py(玄関の ② の組み立て)のテスト。リポジトリ直下で: py -3.12 -m unittest src/friendapp/tests/test_engine.py

本物の ② の待ち行列は起こさない(queue_factory を差し替える)。一時フォルダだけを使う。
"""
import json
import os
import shutil
import sys
import tempfile
import types
import unittest
from unittest import mock

os.environ.setdefault("YTT_DATA_DIR", "inplace")
SRC = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if SRC not in sys.path:
    sys.path.insert(0, SRC)

from ytt import testkit  # noqa: E402
from friendapp import engine, inbox  # noqa: E402


class FakeQueue:
    def __init__(self, book, log_dir, log=None):
        self.hook, self.closed = None, False

    def set_finished_hook(self, fn):
        self.hook = fn

    def status(self):
        return {"idle": True, "runs": []}

    def history(self, limit=None):
        return {"runs": []}

    def close(self):
        self.closed = True


def fake_run(run_id, state, packs, result_path=None, error=""):
    return types.SimpleNamespace(id=run_id, state=state, error=error, result_path=result_path, all_packs=lambda: list(packs))


class EngineTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="friend-engine-")
        self.places = {"data": os.path.join(self.tmp, "data"), "friend": os.path.join(self.tmp, "friend"), "studio": None}
        os.makedirs(self.places["friend"])
        self.cases = os.path.join(self.tmp, "cases")
        self.ib = inbox.Inbox(os.path.join(self.tmp, "inbox.json"), os.path.join(self.tmp, "outbox"),
                              lambda: os.path.join(self.tmp, "save"), lambda: self.cases)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def packs(self, n):
        out = []
        for i in range(n):
            d = os.path.join(self.cases, "c", "p%d_pack" % i)
            os.makedirs(d)
            out.append(d)
        return out

    def make(self):
        eng = engine.Engine(self.places, self.ib, queue_factory=FakeQueue)
        self.addCleanup(eng.close)
        return eng

    def fake_preview(self, tag):
        """確認用の動画の偽物(ffmpeg は使わない)。呼ばれた dirs を self.calls に残す"""
        def fn(ds, log=None):
            self.calls.append((tag, list(ds) if isinstance(ds, (list, tuple)) else ds))
            p = os.path.join(self.tmp, "tmp-%s-%d.mp4" % (tag, len(self.calls)))
            with open(p, "wb") as f:
                f.write(b"x")
            return p
        return fn

    def test_after_run_arrives_and_makes_one_preview_per_pack(self):
        """届いた行はパックごとに確認用の動画(1 本ずつの枠)"""
        self.ib.add("20261016-100000-aaaaaa", {}, {}, run_id="r1")
        dirs = self.packs(6)
        eng = self.make()
        self.calls = []
        with mock.patch.object(engine._preview, "pack_seconds", lambda d: 30.0), mock.patch.object(engine._preview, "clip_preview", self.fake_preview("clip")), \
                mock.patch.object(engine._outbox, "build", lambda *a, **k: None):
            eng.after_run(fake_run("r1", "done", dirs))
            eng.make_previews("20261016-100000-aaaaaa")
        r = self.ib.row("20261016-100000-aaaaaa")
        self.assertEqual(r["state"], "arrived")
        self.assertEqual([len(g["names"]) for g in r["groups"]], [1] * 6)
        self.assertTrue(all(g["preview"] and os.path.isfile(g["preview"]) for g in r["groups"]))
        self.assertEqual(r["packs"][0]["seconds"], 30.0)
        self.assertEqual(self.calls, [("clip", d) for d in dirs])   # 1 本のフォルダを渡す
        self.assertEqual([p["preview"] for p in r["packs"]], [g["preview"] for g in r["groups"]])   # パックの確認用の動画 = 枠の動画
        self.assertEqual(self.ib.pack_preview(r["id"], r["packs"][2]["name"]), r["groups"][2]["preview"])
        self.assertEqual(os.path.dirname(r["groups"][0]["preview"]), os.path.join(self.places["friend"], "previews"))

    def test_previews_are_not_made_twice(self):
        self.ib.add("20261016-100000-aaaaaa", {}, {}, run_id="r1")
        dirs = self.packs(2)
        eng = self.make()
        self.calls = []
        with mock.patch.object(engine._preview, "pack_seconds", lambda d: 30.0), \
                mock.patch.object(engine._preview, "clip_preview", self.fake_preview("clip")), mock.patch.object(engine._outbox, "build", lambda *a, **k: None):
            eng.after_run(fake_run("r1", "done", dirs))
            eng.make_previews("20261016-100000-aaaaaa")
            n = len(self.calls)
            eng.make_previews("20261016-100000-aaaaaa")   # 作った物は作り直さない
            self.assertEqual(len(self.calls), n)
        self.assertEqual(self.calls, [("clip", dirs[0]), ("clip", dirs[1])])   # 1 本のフォルダを渡す
        self.assertTrue(all(g["preview"] for g in self.ib.row("20261016-100000-aaaaaa")["groups"]))

    def test_previews_skip_packs_already_decided(self):
        self.ib.add("20261016-100000-aaaaaa", {}, {}, run_id="r1")
        dirs = self.packs(2)
        eng = self.make()
        self.calls = []
        with mock.patch.object(engine._preview, "pack_seconds", lambda d: 30.0), mock.patch.object(engine._preview, "clip_preview", self.fake_preview("clip")), \
                mock.patch.object(engine._outbox, "build", lambda *a, **k: None):
            eng.after_run(fake_run("r1", "done", dirs))
            r = self.ib.row("20261016-100000-aaaaaa")
            r["packs"][0]["verdict"] = "skip"   # 作る前に見送った
            eng.make_previews(r["id"])
        self.assertEqual(self.calls, [("clip", dirs[1])])

    def test_after_run_cancelled_row_is_removed(self):
        """[取り消す] で止めた実行(届いた物なし)は行ごと消える"""
        self.ib.add("20261016-100000-bbbbbb", {}, {}, run_id="r2")
        eng = self.make()
        with mock.patch.object(engine._outbox, "build", lambda *a, **k: None):
            eng.after_run(fake_run("r2", "cancelled", []))
        self.assertIsNone(self.ib.row("20261016-100000-bbbbbb"))

    def test_after_run_error_fails_row(self):
        self.ib.add("20261016-100000-bbbbbb", {}, {}, run_id="r2")
        eng = self.make()
        with mock.patch.object(engine._outbox, "build", lambda *a, **k: None):
            eng.after_run(fake_run("r2", "error", [], error="配信を取ってこられませんでした"))
        r = self.ib.row("20261016-100000-bbbbbb")
        self.assertEqual((r["state"], r["error"]), ("failed", "配信を取ってこられませんでした"))

    def test_after_run_ignores_other_runs(self):
        eng = self.make()
        eng.after_run(fake_run("other", "done", []))
        self.assertEqual(self.ib.rows, [])

    def test_outbox_built_for_request(self):
        self.ib.add("20261016-100000-cccccc", {}, {}, run_id="r3")
        eng = self.make()
        got = []
        with mock.patch.object(engine._outbox, "build", lambda path, app_dir, request_id=None, **k: got.append((path, request_id))):
            eng.after_run(fake_run("r3", "error", [], result_path="x.json", error="e"))
        self.assertEqual(got, [("x.json", "20261016-100000-cccccc")])

    def test_reconcile_lost_row(self):
        self.ib.add("20261016-100000-dddddd", {}, {}, run_id="gone")
        self.make()
        r = self.ib.row("20261016-100000-dddddd")
        self.assertEqual(r["state"], "failed")
        self.assertIn("もう一度送る", r["error"])

    def test_reconcile_leaves_user_pc_rows(self):
        """ユーザーの PC に頼んだ行は ② の待ちに無くても失われていない(同期が見る)"""
        self.ib.add("20261016-100000-eeeeee", {}, {}, pc="user")
        self.make()
        self.assertEqual(self.ib.row("20261016-100000-eeeeee")["state"], "sent")

    def test_friend_queue_drops_deliver_and_skips_later_analysis(self):
        q = engine.FriendQueue.__new__(engine.FriendQueue)
        run = types.SimpleNamespace(steps=[{"key": "export"}, {"key": "deliver"}, {"key": "analyze_later"}])
        q._shape_steps(run)
        q._shape_steps(run)   # 何度呼んでも同じ(_accept と復元の両方から呼ばれる)
        self.assertEqual([s["key"] for s in run.steps], ["export", "analyze_later"])
        st = {}
        self.assertIsNone(q._step_analyze_later(run, st, {}))
        self.assertEqual(st["state"], "skip")


class RunLogTest(unittest.TestCase):
    """友人のログ friendapp.log に残す 1 依頼ぶんの記録(段ごとの時刻と秒・文字起こしの装置)。偽の実行だけ(本物の認識も ffmpeg も動かさない)"""

    def run_obj(self, **kw):
        steps = [{"key": "normalize", "label": "30fps", "state": "done", "detail": "30fps にそろえました", "startedAt": 1000000, "finishedAt": 1090500},
                 {"key": "transcribe", "label": "文字起こし", "state": "done", "detail": "1 本を文字起こししました", "startedAt": 1090500, "finishedAt": 1150500},
                 {"key": "pack", "label": "パック", "state": "wait", "detail": ""}]   # 始まらなかった段は書かない
        d = dict(id="r9", request_id="20261018-100000-abcdef", state="done", error="", steps=steps, docs=["t1", "told"])
        d.update(kw)
        return types.SimpleNamespace(**d)

    DOCS = {"t1": {"recognition": {"runs": [{"at": 1100000, "device": "vulkan", "engine": "whisper.cpp", "engineVersion": "1.9.4", "model": "large-v3",
                                              "audioSec": 120.0, "wallSec": 60.0, "backend": "Vulkan0", "gpu": "NVIDIA GeForce RTX 3060"}]}},
            "told": {"recognition": {"runs": [{"at": 5, "device": "cpu", "model": "old", "audioSec": 1, "wallSec": 1}]}}}   # 飛ばした既存の文書(段の前の記録)

    def test_stage_lines_one_per_started_stage(self):
        lines = engine.stage_lines(self.run_obj())
        self.assertEqual(len(lines), 2)
        self.assertIn("依頼=20261018-100000-abcdef normalize(動画を取得)", lines[0])
        self.assertIn("90.5 秒 done", lines[0])
        self.assertIn("transcribe(文字起こし)", lines[1])
        self.assertIn("60.0 秒", lines[1])

    def test_transcribe_line_has_engine_device_model_rtf(self):
        lines = engine.transcribe_lines(self.run_obj(), read_doc=self.DOCS.get)
        self.assertEqual(len(lines), 1)   # 段の前の記録は書かない
        s = lines[0]
        for want in ("エンジン=A(whisper.cpp 1.9.4)", "装置=Vulkan0 GPU=NVIDIA GeForce RTX 3060", "モデル=large-v3", "音声=120.0 秒", "かかった=60.0 秒", "実時間比=0.50"):
            self.assertIn(want, s)

    def test_transcribe_line_cpu_and_missing_device(self):
        self.assertIn("装置=CPU(GPU は使っていません)", engine.transcribe_line("x", {"device": "cpu", "audioSec": 10, "wallSec": 40}))
        self.assertIn("実時間比=4.00", engine.transcribe_line("x", {"device": "cpu", "audioSec": 10, "wallSec": 40}))
        s = engine.transcribe_line("x", {"device": "cuda", "model": "large-v3"})   # GPU の行を拾えていない
        self.assertIn("エンジン=C", s)
        self.assertIn("CPU に落ちた疑い", s)
        self.assertIn("実時間比=?", s)

    def test_log_run_writes_stage_transcribe_and_end_lines(self):
        tmp = testkit.tempdir(self, "friend-runlog-")
        lines = []
        eng = engine.Engine.__new__(engine.Engine)
        eng.log = lines.append
        with mock.patch.object(engine, "_read_doc", self.DOCS.get):
            eng.log_run(self.run_obj())
            eng.log_run(self.run_obj(state="error", error="GPU(Vulkan)を使えませんでした", docs=[]))
        self.assertEqual(len([x for x in lines if x.startswith("段 ")]), 4)
        self.assertEqual(len([x for x in lines if x.startswith("文字起こし ")]), 1)
        self.assertIn("実行の終わり 依頼=20261018-100000-abcdef 状態=done", lines[3])
        self.assertTrue(lines[-1].endswith("理由=GPU(Vulkan)を使えませんでした"))

    def test_transcribe_progress_reads_running_job(self):
        eng = engine.Engine.__new__(engine.Engine)
        eng.queue = types.SimpleNamespace(tools=types.SimpleNamespace(jobs=lambda: [
            {"kind": "transcribe", "state": "done", "progress": 1.0}, {"kind": "transcribe", "state": "running", "progress": 0.423}]))
        self.assertEqual(eng.transcribe_progress(), "42%")
        eng.queue = types.SimpleNamespace(tools=types.SimpleNamespace(jobs=lambda: [{"kind": "transcribe", "state": "done"}]))
        self.assertIsNone(eng.transcribe_progress())
        eng.queue = types.SimpleNamespace()   # tools が無い(偽の待ち行列)
        self.assertIsNone(eng.transcribe_progress())


if __name__ == "__main__":
    unittest.main()
