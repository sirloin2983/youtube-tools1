"""src/friendapp/engine.py(玄関の ② の組み立て)と oldcopy の写すだけの形のテスト。リポジトリ直下で: py -3.10 -m unittest src/friendapp/tests/test_engine.py

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

from friendapp import engine, inbox, oldcopy  # noqa: E402


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
        """届いた行はパックごとに確認用の動画(1 本ずつの組)。clip_preview が ① に無い間は batch_preview の 1 本"""
        self.ib.add("20261016-100000-aaaaaa", {"deliverBatch": 5}, {}, run_id="r1")
        dirs = self.packs(6)
        eng = self.make()
        self.calls = []
        with mock.patch.object(engine._preview, "clip_seconds", lambda ds: [30.0] * len(ds)), mock.patch.object(engine, "_CLIP_PREVIEW", None), \
                mock.patch.object(engine._preview, "batch_preview", self.fake_preview("batch")), mock.patch.object(engine._outbox, "build", lambda *a, **k: None):
            eng.after_run(fake_run("r1", "done", dirs))
            eng.make_previews("20261016-100000-aaaaaa")
        r = self.ib.row("20261016-100000-aaaaaa")
        self.assertEqual(r["state"], "arrived")
        self.assertEqual([len(g["names"]) for g in r["groups"]], [1] * 6)   # 組の本数(deliverBatch)は読まない
        self.assertTrue(all(g["preview"] and os.path.isfile(g["preview"]) for g in r["groups"]))
        self.assertEqual(r["packs"][0]["seconds"], 30.0)
        self.assertEqual([c[0] for c in self.calls], ["batch"] * 6)
        self.assertTrue(all(len(c[1]) == 1 for c in self.calls))
        self.assertEqual([p["preview"] for p in r["packs"]], [g["preview"] for g in r["groups"]])   # パックの確認用の動画 = 組の動画
        self.assertEqual(self.ib.pack_preview(r["id"], r["packs"][2]["name"]), r["groups"][2]["preview"])
        self.assertEqual(os.path.dirname(r["groups"][0]["preview"]), os.path.join(self.places["friend"], "previews"))

    def test_previews_use_clip_preview_when_available(self):
        self.ib.add("20261016-100000-aaaaaa", {}, {}, run_id="r1")
        dirs = self.packs(2)
        eng = self.make()
        self.calls = []
        with mock.patch.object(engine._preview, "clip_seconds", lambda ds: [30.0] * len(ds)), \
                mock.patch.object(engine, "_CLIP_PREVIEW", self.fake_preview("clip")), \
                mock.patch.object(engine._preview, "batch_preview", self.fake_preview("batch")), mock.patch.object(engine._outbox, "build", lambda *a, **k: None):
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
        with mock.patch.object(engine._preview, "clip_seconds", lambda ds: [30.0] * len(ds)), mock.patch.object(engine, "_CLIP_PREVIEW", self.fake_preview("clip")), \
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
        """ユーザーの PC に頼んだ行(F2-3)は ② の待ちに無くても失われていない(同期が見る)"""
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


class CopyOnlyTest(unittest.TestCase):
    """REMOVE_OLD が偽の間(今の送るアプリと並べて使う間)は写すだけ・古い方は消さない"""

    def test_copy_without_remove(self):
        import hashlib
        tmp = tempfile.mkdtemp(prefix="friend-oldcopy-")
        self.addCleanup(shutil.rmtree, tmp, True)
        old, new = os.path.join(tmp, "old"), os.path.join(tmp, "new")
        os.makedirs(os.path.join(old, "transcribe", "models"))
        data = b"model" * 100
        with open(os.path.join(old, "transcribe", "models", "m.bin"), "wb") as f:
            f.write(data)
        fetch = os.path.join(tmp, "fetch.json")
        with open(fetch, "w", encoding="utf-8") as f:
            json.dump({"items": [{"name": "m", "file": "m.bin", "url": "https://x/m.bin", "size": len(data), "sha256": hashlib.sha256(data).hexdigest(),
                                  "base": "data", "dest": "transcribe/models", "unzip": None}]}, f)
        got = oldcopy.migrate(fetch, old, new, os.path.join(tmp, "cat.json"), remove_old=False)
        self.assertEqual((got["copied"], got["deleted"]), (1, 0))
        self.assertTrue(os.path.isfile(os.path.join(old, "transcribe", "models", "m.bin")))
        self.assertTrue(os.path.isfile(os.path.join(new, "transcribe", "models", "m.bin")))
        got = oldcopy.migrate(fetch, old, new, os.path.join(tmp, "cat.json"), remove_old=True)   # あとで消すと決めたとき(F2-7)は目録から消せる
        self.assertEqual(got["deleted"], 1)
        self.assertFalse(os.path.isfile(os.path.join(old, "transcribe", "models", "m.bin")))


if __name__ == "__main__":
    unittest.main()
