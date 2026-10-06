# -*- coding: utf-8 -*-
"""入口を起動し直す部品(src/home/restart.py。段9 9-3)のテスト。  python -m unittest src/home/tests/test_restart.py -v

- spawn_new_launcher: 一時フォルダに偽の home/launch.py(受け取った引数・環境変数・作業フォルダを書いて終わる)を置き、
  本物の Python で起動して、引数・環境・作業フォルダ・待ち受けのソケットを引き継がないことを確かめる
- wait_port_free / port_free: 本物の待ち受けのソケット(少しあとで閉じる)で
- can_restart: 重い処理の枠(ytt_core.jobs.SLOTS.snapshot() の形)・まとめて実行の状態で
"""
import json
import os
os.environ.setdefault("YTT_DATA_DIR", "inplace")   # テストは作業データを本物の置き場所に書かない(ここではサーバーを動かさないが、約束として)
import shutil
import socket
import subprocess
import sys
import tempfile
import textwrap
import threading
import time
import unittest
from unittest import mock

TESTS = os.path.dirname(os.path.abspath(__file__))   # src/home/tests
HERE = os.path.dirname(TESTS)   # home
REPO = os.path.dirname(HERE)
sys.path.insert(0, HERE)
if REPO not in sys.path:
    sys.path.append(REPO)
import restart as R  # noqa: E402
from ytt_core import jobs, layout  # noqa: E402

FAKE_LAUNCH = textwrap.dedent(r'''
    import json, os, sys, time
    out = os.environ["YTT_TEST_RESTART_OUT"]
    with open(out + ".tmp", "w", encoding="utf-8") as f:
        json.dump({"argv": sys.argv[1:], "cwd": os.getcwd(), "exe": sys.executable,
                   "marker": os.environ.get("YTT_TEST_RESTART_MARK"), "data": os.environ.get("YTT_DATA_DIR")}, f)
    os.replace(out + ".tmp", out)
    time.sleep(float(os.environ.get("YTT_TEST_RESTART_SLEEP") or "0"))
''')


def listening_socket():
    """入口と同じ形(Windows は SO_EXCLUSIVEADDRUSE)で、OS に選ばせた空きポートで待ち受ける"""
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    if os.name == "nt" and hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
        s.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
    s.bind(("127.0.0.1", 0))
    s.listen(5)
    return s, s.getsockname()[1]


def stop(proc):
    if proc.poll() is None:
        proc.kill()
    proc.wait(10)


class SpawnTest(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="ytt-restart-")
        self.addCleanup(shutil.rmtree, self.root, True)
        os.makedirs(os.path.join(self.root, "home"))
        with open(os.path.join(self.root, "home", "launch.py"), "w", encoding="utf-8") as f:
            f.write(FAKE_LAUNCH)
        self.out = os.path.join(self.root, "record.json")

    def wait_record(self, proc, timeout=20):
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            if os.path.exists(self.out):
                with open(self.out, encoding="utf-8") as f:
                    return json.load(f)
            if proc.poll() not in (None, 0):
                self.fail("偽の入口が失敗しました(終了コード %s)" % proc.returncode)
            time.sleep(0.05)
        self.fail("偽の入口が記録を書きませんでした")

    def test_args(self):
        self.assertEqual(R.restart_args(8700), ["--port", "8700", "--wait-port", "--no-open"])
        self.assertEqual(R.restart_args(8701, ["studio", "transcribe"], True),
                         ["--port", "8701", "--wait-port", "--no-open", "--only", "studio,transcribe", "--no-mount"])
        self.assertEqual(R.launcher_script(self.root), os.path.join(os.path.abspath(self.root), "home", "launch.py"))

    def test_spawns_launcher_with_same_python_env_and_cwd(self):
        env = dict(os.environ, YTT_TEST_RESTART_OUT=self.out, YTT_TEST_RESTART_MARK="mark-1")
        logs = []
        with mock.patch.dict(os.environ, env, clear=True):
            proc = R.spawn_new_launcher(self.root, None, R.restart_args(8765, ["studio"]), log=logs.append)
        self.addCleanup(stop, proc)
        rec = self.wait_record(proc)
        proc.wait(20)
        self.assertEqual(rec["argv"], ["--port", "8765", "--wait-port", "--no-open", "--only", "studio"])
        self.assertEqual(os.path.normcase(os.path.realpath(rec["cwd"])), os.path.normcase(os.path.realpath(layout.repo_root(self.root))))
        self.assertEqual(rec["marker"], "mark-1")                       # 今のプロセスの環境変数を写す
        self.assertEqual(rec["data"], os.environ.get("YTT_DATA_DIR"))   # テストの inplace も引き継ぐ
        self.assertEqual(os.path.normcase(os.path.realpath(rec["exe"])), os.path.normcase(os.path.realpath(sys.executable)))
        self.assertTrue(logs and str(proc.pid) in logs[0])

    def test_explicit_env_and_python(self):
        proc = R.spawn_new_launcher(self.root, sys.executable, [], env={**os.environ, "YTT_TEST_RESTART_OUT": self.out})
        self.addCleanup(stop, proc)
        rec = self.wait_record(proc)
        proc.wait(20)
        self.assertEqual(rec["argv"], [])
        self.assertIsNone(rec["marker"])

    def test_listening_socket_is_not_inherited(self):
        """古い入口の待ち受けを新しい入口が持ったままだと、ポートが空かない(新しい入口が動いている間に閉じて、空くことを確かめる)"""
        srv, port = listening_socket()
        env = {**os.environ, "YTT_TEST_RESTART_OUT": self.out, "YTT_TEST_RESTART_SLEEP": "6"}
        proc = R.spawn_new_launcher(self.root, None, R.restart_args(port), env=env)
        self.addCleanup(stop, proc)
        self.wait_record(proc)
        self.assertIsNone(proc.poll(), "偽の入口がまだ動いている間に確かめる")
        srv.close()
        self.assertTrue(R.wait_port_free(port, timeout=3), "子がソケットを引き継いでいるとポートが空かない")
        self.assertIsNone(proc.poll())

    def test_creation_flags(self):
        calls = []

        def fake_popen(cmd, **kw):
            calls.append((cmd, kw))
            return mock.Mock(pid=4321)
        R.spawn_new_launcher(self.root, "python-x", ["--no-open"], popen=fake_popen)
        R.spawn_new_launcher(self.root, "python-x", [], popen=fake_popen, visible=True)
        (cmd, kw), (_, kw2) = calls
        self.assertEqual(cmd, ["python-x", R.launcher_script(self.root), "--no-open"])
        self.assertTrue(kw["close_fds"])
        self.assertEqual(kw["cwd"], layout.repo_root(self.root))   # 作業フォルダは start.bat と同じリポジトリ直下(root = src の1つ上)
        if os.name == "nt":
            # 見えないコンソール(子の ffmpeg などが黒い画面を開かない・Ctrl+Break が届く)。コンソール無し(DETACHED_PROCESS)にはしない
            self.assertTrue(kw["creationflags"] & subprocess.CREATE_NO_WINDOW)
            self.assertFalse(kw["creationflags"] & subprocess.DETACHED_PROCESS)
            self.assertEqual(kw["stdout"], subprocess.DEVNULL)
            self.assertTrue(kw2["creationflags"] & subprocess.CREATE_NEW_CONSOLE)
            self.assertFalse(kw2["creationflags"] & subprocess.CREATE_NEW_PROCESS_GROUP)   # 新しい黒い画面で Ctrl+C を効かせる
            self.assertEqual(kw2["startupinfo"].wShowWindow, R.SW_SHOWMINNOACTIVE)
        else:
            self.assertTrue(kw["start_new_session"])


class WaitPortTest(unittest.TestCase):
    def test_returns_when_listener_closes(self):
        srv, port = listening_socket()
        self.assertFalse(R.port_free(port))
        timer = threading.Timer(0.6, srv.close)
        timer.start()
        self.addCleanup(timer.cancel)
        t0 = time.monotonic()
        self.assertTrue(R.wait_port_free(port, timeout=10, poll=0.05))
        self.assertGreaterEqual(time.monotonic() - t0, 0.5)
        self.assertTrue(R.port_free(port))

    def test_times_out_while_in_use(self):
        srv, port = listening_socket()
        self.addCleanup(srv.close)
        t0 = time.monotonic()
        self.assertFalse(R.wait_port_free(port, timeout=0.4, poll=0.05))
        self.assertLess(time.monotonic() - t0, 3)

    def test_bound_but_not_listening_is_not_free(self):
        """待ち受けを止めてソケットをまだ閉じていない(古い入口が閉じる途中): つなげないが bind できない → まだ空いていない"""
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.addCleanup(s.close)
        if os.name == "nt" and hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            s.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
        self.assertFalse(R.port_free(port))
        s.close()
        self.assertTrue(R.port_free(port))

    def test_free_port_returns_at_once(self):
        srv, port = listening_socket()
        srv.close()
        sleeps = []
        self.assertTrue(R.wait_port_free(port, timeout=5, sleep=sleeps.append))
        self.assertEqual(sleeps, [])


class CanRestartTest(unittest.TestCase):
    def status(self, active=(), waiting=()):
        return {"app": "ytt-launcher", "heavy": {"limit": 1, "active": list(active), "waiting": list(waiting)}}

    def test_idle(self):
        self.assertIsNone(R.can_restart(self.status()))
        self.assertIsNone(R.can_restart({}))
        self.assertIsNone(R.can_restart(None))
        self.assertIsNone(R.can_restart(self.status(), runs=[{"state": "done"}, {"state": "error"}, {"state": "cancelled"}]))
        self.assertIsNone(R.can_restart({"heavy": jobs.HeavySlots().snapshot()}))   # 本物の形(何も動いていない)

    def test_heavy_active_or_waiting(self):
        msg = R.can_restart(self.status(active=[{"tool": "transcribe", "label": "文字起こし", "seconds": 12}]))
        self.assertEqual(msg, "実行中の処理があります(文字起こし)。終わってから起動し直してください")
        msg = R.can_restart(self.status(waiting=[{"tool": "studio", "label": "", "seconds": 1}]))
        self.assertIn("studio", msg)

    def test_real_slots_snapshot(self):
        slots = jobs.HeavySlots(1)
        with slots.slot("transcribe", "文字起こし"):
            msg = R.can_restart({"heavy": slots.snapshot()})
        self.assertIn("文字起こし", msg)
        self.assertIsNone(R.can_restart({"heavy": slots.snapshot()}))

    def test_autorun_and_busy_tools(self):
        self.assertIn("まとめて実行 2 件", R.can_restart(self.status(), runs=[{"state": "running"}, {"state": "queued"}, {"state": "done"}]))
        self.assertIn("編集", R.can_restart(self.status(), busy_tools=["編集"]))
        self.assertIsNone(R.can_restart(self.status(), busy_tools=["", None]))
        # あとから解析(測るため)だけなら起動し直せる(終了で止まり、一覧に残って次の起動で続く。2026-10-05)
        self.assertIsNone(R.can_restart(self.status(), runs=[{"state": "running", "mode": "post_analyze"}, {"state": "done"}]))
        self.assertIn("まとめて実行 1 件", R.can_restart(self.status(), runs=[{"state": "running", "mode": "post_analyze"}, {"state": "queued", "mode": "request"}]))

    def test_message_lists_at_most_three(self):
        act = [{"tool": "t", "label": "処理%d" % i} for i in range(5)]
        msg = R.can_restart(self.status(active=act))
        self.assertIn("処理0・処理1・処理2", msg)
        self.assertNotIn("処理3", msg)


if __name__ == "__main__":
    unittest.main()
