# -*- coding: utf-8 -*-
"""flow/runqueue.py(② の待ち行列と実行の糸。RS7-1 S5)のテスト。  py -3.10 -m unittest src/flow/tests/test_runqueue.py -v
home(入口の AutoRunner・案件・ホームの設定)を読まずに、素の Queue だけで submit → status → 完了・待ちの記録の保存と復元・中止を見る。
受付と hook を埋めた形(AutoRunner)の細かい動きは src/home/tests/test_autorun.py。
"""
import os
os.environ.setdefault("YTT_DATA_DIR", "inplace")   # 作業データは読み書きしない(記録は一時フォルダ)
import json
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unittest

SRC = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))   # tests -> flow -> src
sys.path.insert(0, SRC)
from flow import runqueue as Q, run as R, spec as SP, tools as T  # noqa: E402

WAIT = 10.0


class Tools(T.HttpTools):
    """文字起こしだけの道具の真似(client なし)。gate が閉じている間はジョブが終わらない"""

    def __init__(self):
        super().__init__(None)
        self.started = []            # (動画, 束の transcribe.model, 束の post.llmModel)
        self.gate = threading.Event()
        self.gate.set()
        self.cancelled = []

    def docs(self):
        return []

    def transcribe_start(self, req, bundle=None):
        self.started.append((req["sourcePath"], bundle["transcribe"]["model"], bundle["post"]["llmModel"]))
        return "j%d" % len(self.started)

    def jobs(self):
        state = "done" if self.gate.is_set() else "running"
        return [{"id": "j%d" % i, "state": state, "tid": "t%d" % i, "progress": 0.5} for i in range(1, len(self.started) + 1)]

    def transcribe_cancel(self, jid):
        self.cancelled.append(jid)


def _until(cond, what):
    end = time.time() + WAIT
    while time.time() < end:
        if cond():
            return
        time.sleep(0.01)
    raise AssertionError("待っても %s になりませんでした" % what)


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.logs = os.path.join(self.tmp, "logs")
        os.makedirs(self.logs)
        self.media = []
        for i in range(3):
            p = os.path.join(self.tmp, "clip%d.mp4" % i)
            with open(p, "wb") as f:
                f.write(b"x")
            self.media.append(p)
        self.env = {"YTT_MACHINE_FILE": os.path.join(self.tmp, "nai", "machine.json")}   # この PC の設定は無い(既定)

    def queue(self, tools=None, env=None):
        q = Q.Queue(None, env=env or self.env, poll=0.01, tools=tools or Tools(), log_dir=self.logs)
        self.addCleanup(q.close)
        return q

    @staticmethod
    def env_of(path, eid="0123456789"):
        return {"id": eid, "kind": "file", "input": {"path": path, "title": "切り抜き"}, "legacy": {"mode": "file"}}   # 文字起こしだけ

    def active_file(self):
        with open(os.path.join(self.logs, Q.ACTIVE_FILE), encoding="utf-8") as f:
            return json.load(f)


class TestImport(unittest.TestCase):
    def test_imports_without_home(self):
        """home・human・manage を読まずに読める = 層の向き(画面なし・③ なしの ②)"""
        code = ("import sys; sys.path.insert(0, %r); import flow.runqueue as q; "
                "bad = [m for m in ('autorun', 'cases', 'prefs', 'deliver', 'delivery', 'friend_feedback', 'manage', 'human', 'home') "
                "if m in sys.modules]; print(bad); sys.exit(1 if bad else 0)") % SRC
        p = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=60)
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)


class TestSubmit(Base):
    def test_submit_status_done(self):
        """封筒 + 束を積む → 糸が束のとおりに進める → status で 0 本に戻る・記録と history に 1 行"""
        tools = Tools()
        q = self.queue(tools, env=dict(self.env, YTT_MACHINE_LLM_MODEL="qwen3-4b"))
        pub = q.submit(self.env_of(self.media[0]), {"transcribe": {"model": "large-v3"}})
        self.assertEqual((pub["id"], pub["kind"], pub["sourcePath"]), ("0123456789", "file", self.media[0]))
        _until(lambda: q.status()["idle"], "待ち・実行中が 0")
        st = q.status()
        self.assertEqual((st["queued"], st["running"], st["done"], st["closed"]), (0, 0, 1, False))
        one = st["runs"][0]
        self.assertEqual((one["id"], one["kind"], one["state"], one["step"]), ("0123456789", "file", "done", None))
        self.assertEqual([s["key"] for s in one["steps"]], ["transcribe"])
        self.assertIsInstance(one["startedAt"], int)
        self.assertTrue(all(isinstance(s.get("finishedAt"), int) for s in one["steps"] if s["state"] != "wait"))
        # 受けた束 + この PC の設定(machine の llmModel)のまま流れた(build_spec は呼ばない)
        self.assertEqual(tools.started, [(self.media[0], "large-v3", "qwen3-4b")])
        hist = q.history()
        self.assertEqual((hist["total"], hist["runs"][0]["id"], hist["runs"][0]["state"]), (1, "0123456789", "done"))
        self.assertEqual(self.active_file()["runs"], [])   # 終わった実行は待ちの記録から外れる

    def test_submit_rejects(self):
        """封筒の形が違う・同じ入力が待ち・実行中・同じ id は理由つきの ValueError(積まない)"""
        tools = Tools()
        tools.gate.clear()
        q = self.queue(tools)
        with self.assertRaises(ValueError):
            q.submit({"id": "x", "kind": "nai", "input": {}})
        with self.assertRaises(ValueError):
            q.submit(self.env_of(self.media[0]), {"transcribe": {"engine": "nai"}})
        q.submit(self.env_of(self.media[0]))
        with self.assertRaisesRegex(ValueError, "すでに実行中・順番待ち"):
            q.submit(self.env_of(self.media[0], "abcdef0123"))
        with self.assertRaisesRegex(ValueError, "もう待ち・実行中"):
            q.submit(self.env_of(self.media[1]))
        self.assertEqual(len(q.status()["runs"]), 1)
        tools.gate.set()
        _until(lambda: q.status()["idle"], "待ち・実行中が 0")

    def test_without_spec_uses_build_spec_hook(self):
        """束を持たない実行(画面の欄から作った Run)は hook の build_spec(既定 = 束の既定 + この PC の設定)"""
        tools = Tools()
        q = self.queue(tools)
        with q.cv:
            out = q._push(R.Run(None, "t", "file", None, source_path=self.media[0]))
        _until(lambda: q.status()["idle"], "待ち・実行中が 0")
        self.assertEqual(tools.started, [(self.media[0], SP.DEFAULTS["transcribe"]["model"], SP.DEFAULTS["post"]["llmModel"])])
        self.assertEqual(q.status()["runs"][0]["id"], out["id"])


class TestRestore(Base):
    def test_close_keeps_and_next_queue_resumes(self):
        """終了(close)で止まった実行は待ちの記録(封筒 + 束)に残り、次の Queue が同じ id のまま、受けたときの束で続ける"""
        tools = Tools()
        tools.gate.clear()
        q = self.queue(tools)
        q.submit(self.env_of(self.media[0]), {"transcribe": {"model": "large-v3"}})
        q.submit(self.env_of(self.media[1], "abcdef0123"))
        _until(lambda: q.status()["running"] == 1 and tools.started, "実行中")
        st = q.status()
        self.assertEqual((st["queued"], st["running"], st["idle"], st["runs"][0]["step"]), (1, 1, False, "transcribe"))
        q.close()
        _until(lambda: not q.thread.is_alive(), "糸が止まる")
        saved = self.active_file()["runs"]
        self.assertEqual([r["id"] for r in saved], ["0123456789", "abcdef0123"])
        self.assertEqual(saved[0]["envelope"]["kind"], "file")
        self.assertEqual(saved[0]["spec"]["transcribe"]["model"], "large-v3")
        self.assertEqual(q.history()["total"], 0)   # 終了で止まった実行は「中止」と書かない

        tools2 = Tools()
        q2 = self.queue(tools2)
        _until(lambda: q2.status()["idle"], "戻した 2 本が済む")
        self.assertEqual([(r["id"], r["state"]) for r in q2.status()["runs"]], [("0123456789", "done"), ("abcdef0123", "done")])
        self.assertEqual([m for _p, m, _l in tools2.started], ["large-v3", SP.DEFAULTS["transcribe"]["model"]])

    def test_old_form_and_too_old(self):
        """古い形(欄だけ・束なし)の待ちの記録も戻す。RESTORE_MAX_AGE より前の物は戻さず記録に「中止」"""
        now = time.time()
        old = {"id": "0123456789", "mode": "file", "title": "古い形", "sourcePath": self.media[0], "created": now - 60,
               "steps": [{"key": "transcribe", "state": "wait", "detail": ""}]}
        stale = dict(old, id="abcdef0123", sourcePath=self.media[1], created=now - Q.RESTORE_MAX_AGE - 60)
        with open(os.path.join(self.logs, Q.ACTIVE_FILE), "w", encoding="utf-8") as f:
            json.dump({"v": Q.ACTIVE_VERSION, "runs": [old, stale]}, f)
        tools = Tools()
        q = self.queue(tools)
        _until(lambda: q.status()["idle"], "戻した 1 本が済む")
        self.assertEqual([(r["id"], r["state"]) for r in q.status()["runs"]], [("0123456789", "done")])
        self.assertEqual([p for p, _m, _l in tools.started], [self.media[0]])
        states = {r["id"]: r["state"] for r in q.history()["runs"]}
        self.assertEqual(states, {"0123456789": "done", "abcdef0123": "cancelled"})


class TestCancel(Base):
    def test_cancel_queued_and_running(self):
        """待ちの中止はすぐ「中止」・実行中の中止は段が止まってから。どちらも待ちの記録から外れ、記録に残る"""
        tools = Tools()
        tools.gate.clear()
        q = self.queue(tools)
        q.submit(self.env_of(self.media[0]))
        q.submit(self.env_of(self.media[1], "abcdef0123"))
        _until(lambda: q.status()["running"] == 1, "実行中")
        self.assertEqual(q.cancel("abcdef0123")["state"], "cancelled")
        self.assertEqual([r["id"] for r in self.active_file()["runs"]], ["0123456789"])
        q.cancel("0123456789")
        _until(lambda: q.status()["idle"], "待ち・実行中が 0")
        self.assertEqual([r["state"] for r in q.status()["runs"]], ["cancelled", "cancelled"])
        self.assertEqual(self.active_file()["runs"], [])
        self.assertEqual(sorted(r["id"] for r in q.history()["runs"]), ["0123456789", "abcdef0123"])
        self.assertEqual(tools.cancelled, ["j1"])   # 実行中の段の仕事も取り消す
        with self.assertRaises(ValueError):
            q.cancel("ffffffffff")


if __name__ == "__main__":
    unittest.main()
