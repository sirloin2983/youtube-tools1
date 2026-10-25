"""src/app/check/ytnotify.py(取得の列の結果が届いたら研究のセッションを起こす知らせ)のテスト。claude は起こさない(spawn を差し替え)"""
import json
import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

os.environ.setdefault("YTT_DATA_DIR", "inplace")
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "src"))
from app.check import ytnotify as Y, ytqueue as Q  # noqa: E402
from human.friend import notify as N  # noqa: E402

T0 = 1792900000.0


class FakeProc:
    def __init__(self, pid):
        self.pid, self.code = pid, None

    def poll(self):
        return self.code

    def kill(self):
        self.code = -9


class YtNotifyTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.app, self.now, self.calls = os.path.join(self.tmp, "app"), T0, []
        os.makedirs(Q.qdir(self.app, "done"))
        N._running.clear()

    def spawn(self, cmd, cwd, out):
        self.calls.append(cmd)
        return FakeProc(2000 + len(self.calls))

    def tick(self):
        return Y.tick(self.app, clock=lambda: self.now, spawn=self.spawn)

    def done(self, rid, **body):
        with open(Q.qdir(self.app, "done", rid + ".json"), "w", encoding="utf-8") as f:
            json.dump(dict({"id": rid, "state": "done", "at": int(self.now)}, **body), f)

    def test_batches_kinds_and_counts_once(self):
        """5 分のあいだの結果を 1 通に(種類・本数・動画 id の数だけ)・同じ結果は 1 回・送り先は研究のセッションの名前"""
        self.done("r1", infos=[{"id": "a"}, {"id": "b"}])
        self.assertEqual(self.tick(), 0)
        self.now += 60
        self.done("r2", file="done/r2.m4a", info={"id": "c"})
        self.done("r3", state="error", error="bot")
        self.done("r-subs-1", files={"a": "a.json3", "b": "b.json3"}, infos={"a": "a.info.json"})   # 字幕の返事は infos も辞書で持つ(0.99.270〜)
        self.now += Y.BATCH_SEC
        self.assertEqual(self.tick(), 4)
        prompt = self.calls[0][self.calls[0].index("-p") + 1]
        self.assertIn("「%s」" % Y.RESEARCH_NAME, prompt)
        self.assertIn("動画の情報 1 本(動画 2)", prompt)
        self.assertIn("音 1 本(動画 1)", prompt)
        self.assertIn("失敗 1 本", prompt)
        self.assertIn("字幕 1 本(動画 2)", prompt)
        N._running.clear()
        self.now += Y.BATCH_SEC * 2
        self.assertEqual(self.tick(), 0)
        self.assertEqual(len(self.calls), 1)

    def test_switch_and_daily_max(self):
        self.done("r1", entries=[1, 2, 3])
        self.tick()
        self.now += Y.BATCH_SEC
        with mock.patch.dict(os.environ, {Y.SWITCH_ENV: "0"}):
            self.assertEqual(self.tick(), 0)
        with mock.patch.object(Y, "DAILY_MAX", 0):
            self.assertEqual(self.tick(), 0)
        self.assertEqual(self.calls, [])


if __name__ == "__main__":
    unittest.main()
