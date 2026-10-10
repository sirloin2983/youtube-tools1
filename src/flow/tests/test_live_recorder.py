# -*- coding: utf-8 -*-
"""ライブ係(flow/livesession.LiveSession)の録画元まわりのテスト: 配信の状態を調べる yt-dlp の呼び方(probe_live・validate_url)・
入口の終了で録画の部品を止める(stop_recorder)・見回りが本物の録画の部品を切り離して起動する(tick)。入口 home の Live は使わない。

    py -3.10 -m unittest src/flow/tests/test_live_recorder.py

偽の yt-dlp(この Python で動く小さなスクリプト)・偽の録画元(HTTP。合言葉)で、本物の YouTube へは繋がない。
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock

os.environ.setdefault("YTT_DATA_DIR", "inplace")   # テストは作業データを本物の置き場所(AppData など)に書かない(ytt.datadir)

TESTS = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(TESTS))   # tests -> flow -> src
sys.path.insert(0, TESTS)
import _livefix as FIX  # noqa: E402
from flow import live_export as LX  # noqa: E402
from flow import livesession as LS  # noqa: E402

TOKEN = FIX.TOKEN


def wait_for(fn, timeout=20.0, step=0.2):
    end = time.time() + timeout
    while time.time() < end:
        v = fn()
        if v:
            return v
        time.sleep(step)
    return fn()


class ProbeTest(unittest.TestCase):
    """yt-dlp の呼び方(probe_live)。偽の yt-dlp(この Python で動く小さなスクリプト)で、本物の YouTube へは繋がない"""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="ytt-live-probe-")
        self.args = os.path.join(self.tmp, "args.json")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def fake(self, out="", err="", code=0, sleep=0):
        """find_tool が返す yt-dlp を、この Python で動くスクリプトに置き換える(.bat を通すと cmd が引数の % を読むので、実行の直前で差し替える)"""
        script = os.path.join(self.tmp, "fake_ytdlp.py")
        with open(script, "w", encoding="utf-8") as f:
            f.write("import json, sys, time\njson.dump(sys.argv[1:], open(%r, 'w'))\ntime.sleep(%r)\n"
                    "sys.stdout.buffer.write(%r.encode('utf-8'))\nsys.stderr.buffer.write(%r.encode('utf-8'))\nsys.exit(%d)\n"
                    % (self.args, sleep, out, err, code))
        real = subprocess.Popen   # 起こすのは ytt/tools.run(OPT1)

        def run(cmd, *a, **kw):
            self.assertIsInstance(cmd, list)              # シェルを通さない(引数のリスト)
            self.assertNotIn("shell", kw)
            self.assertEqual(cmd[0], "FAKE-YT-DLP")
            return real([sys.executable, script] + cmd[1:], *a, **kw)
        stack = __import__("contextlib").ExitStack()
        stack.enter_context(mock.patch.object(LS.tools, "find_tool", lambda name, *a, **k: "FAKE-YT-DLP" if name == "yt-dlp" else None))
        stack.enter_context(mock.patch.object(LS.tools.subprocess, "Popen", run))
        return stack

    def test_live_status_and_title(self):
        with self.fake(out="is_live\tPekora Ch. 兎田ぺこら\x07\t【雑談】配信の題\tつづき\x07\n"):
            r = LS.probe_live("https://www.youtube.com/watch?v=abcdefghijk")
        self.assertEqual(r, {"status": "is_live", "title": "【雑談】配信の題つづき", "channel": "Pekora Ch. 兎田ぺこら", "message": ""})   # 題のタブは崩さない
        with open(self.args, encoding="utf-8") as f:
            args = json.load(f)
        self.assertEqual(args[-2:], ["--", "https://www.youtube.com/watch?v=abcdefghijk"])   # URL は1つの引数・オプションとして読ませない
        for flag in ("--skip-download", "--no-playlist", "--ignore-no-formats-error"):
            self.assertIn(flag, args)
        self.assertEqual(args[args.index("--print") + 1], "%(live_status)s\t%(channel,uploader)s\t%(title)s")

    def test_other_states(self):
        with self.fake(out="was_live\tNA\tNA\n"):
            self.assertEqual(LS.probe_live("https://www.youtube.com/watch?v=abcdefghijk"), {"status": "was_live", "title": "", "channel": "", "message": ""})
        with self.fake(out="", err="ERROR: [youtube] x: This live event will begin in 3 hours.\n", code=1):
            self.assertEqual(LS.probe_live("https://www.youtube.com/watch?v=abcdefghijk")["status"], "is_upcoming")
        with self.fake(out="", err="ERROR: Video unavailable\n", code=1):
            r = LS.probe_live("https://www.youtube.com/watch?v=abcdefghijk")
        self.assertEqual(r["status"], "unknown")
        self.assertIn("Video unavailable", r["message"])
        with self.fake(out="NA\tNA\tNA\n"):
            self.assertEqual(LS.probe_live("https://www.youtube.com/watch?v=abcdefghijk")["status"], "unknown")
        with self.fake(out="is_live\tc\tx\n", sleep=3):
            r = LS.probe_live("https://www.youtube.com/watch?v=abcdefghijk", timeout=0.5)
        self.assertEqual(r["status"], "unknown")
        self.assertIn("秒で調べられませんでした", r["message"])
        with mock.patch.object(LS.tools, "find_tool", lambda *a, **k: None):
            self.assertIn("yt-dlp が見つからない", LS.probe_live("https://www.youtube.com/watch?v=abcdefghijk")["message"])

    def test_validate_url(self):
        self.assertEqual(LS.validate_url(" https://youtu.be/abcdefghijk "), "https://www.youtube.com/watch?v=abcdefghijk")
        self.assertEqual(LS.validate_url("https://m.youtube.com/watch?v=abcdefghijk&t=1"), "https://www.youtube.com/watch?v=abcdefghijk")
        self.assertEqual(LS.validate_url("https://www.youtube.com/@channel/live"), "https://www.youtube.com/@channel/live")   # id の無い形はそのまま
        for bad in ("https://www.youtube.com:8443/x", "https://user:pw@www.youtube.com/x", "ftp://www.youtube.com/x", "https://www.youtube.com/\x00"):
            with self.assertRaises(LX.LiveError, msg=bad):
                LS.validate_url(bad)


class StopRecorderTest(unittest.TestCase):
    """入口の終了で録画の部品を止める(src/home/live.py の stop_recorder。入口 0.38.1)。止める相手・応答が無いとき・終わらないとき"""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="ytt-live-stop-")
        self.logs = []
        self.fake = FIX.FakeRecorder()
        self.procs = []

    def tearDown(self):
        for p in self.procs:
            if p.poll() is None:
                p.kill()
                p.wait(5)
        self.fake.close()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def live(self, enabled=True, url=None):
        cfg = FIX.live_cfg(enabled=enabled, recorders=[{"id": "local", "name": "この PC", "url": url or self.fake.url, "token": TOKEN}])
        return FIX.new_session(self.tmp, cfg, log=self.logs.append, root=REPO, data_dir=os.path.join(self.tmp, "recdata"))

    def sleeper(self):
        """この入口が起動した録画の部品の代わり(応答しない・終わらないプロセス)"""
        p = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL, creationflags=getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0))
        self.procs.append(p)
        return p

    def test_off_and_not_spawned_is_left_alone(self):
        lv = self.live(enabled=False)
        lv.close()
        self.assertEqual(lv.stop_recorder(), "none")
        self.assertFalse(self.fake.seen)                                    # オフで、人が別に起動したものは触らない
        self.assertIs(lv.local_recording(), False)

    def test_not_running_is_none(self):
        lv = self.live(url="http://127.0.0.1:%d" % FIX.free_port())
        self.assertEqual(lv.stop_recorder(), "none")                        # つながらない・この入口が起動したものでもない

    def test_unresponsive_own_process_is_killed(self):
        lv = self.live(enabled=False, url="http://127.0.0.1:%d" % FIX.free_port())
        lv.proc = self.sleeper()                                            # オフでも、この入口が起動したものは止める
        self.assertEqual(lv.stop_recorder(), "killed")
        self.assertIsNotNone(lv.proc.poll())
        self.assertTrue(any("応答しない" in m for m in self.logs), self.logs)

    def test_quit_accepted_but_own_process_does_not_exit_is_killed(self):
        lv = self.live()
        lv.proc = self.sleeper()
        self.fake.routes[("POST", "/live/quit")] = lambda b: (200, {"ok": True})
        with mock.patch.object(LS, "QUIT_WAIT", 0.6):
            self.assertEqual(lv.stop_recorder(), "killed")
        self.assertIsNotNone(lv.proc.poll())

    def test_refused_is_left_and_spawn_stops_after_close(self):
        lv = self.live()
        self.fake.routes[("POST", "/live/quit")] = lambda b: (500, {"message": "壊れた"})
        lv.close()
        self.assertEqual(lv.stop_recorder(), "failed")                      # 断られたら(録画中かもしれないので)止めない
        self.assertTrue(any("壊れた" in m for m in self.logs), self.logs)
        self.assertIs(lv.local_recording(), True)                           # 偽物の /live/list は録画中 1 本
        self.assertFalse(lv.spawn(lv.find("local")))                        # 終了の途中は見回りが起こし直さない


class SpawnTest(unittest.TestCase):
    """見回りが本物の録画の部品(src/pipeline/ingest/recorder.py)を切り離して起動する"""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="ytt-live-spawn-")
        self.port = FIX.free_port()
        self.rec_folder = os.path.join(self.tmp, "live-rec")
        self.cfg = FIX.live_cfg(folder=self.rec_folder, recorders=[{"id": "local", "name": "この PC", "url": "http://127.0.0.1:%d" % self.port}])
        self.logs = []
        self.live = FIX.new_session(self.tmp, self.cfg, log=self.logs.append, root=REPO, data_dir=os.path.join(self.tmp, "recdata"), spawn=True)

    def tearDown(self):
        rc = self.live.find("local")
        if rc and self.live.ping(rc):
            self.live.call(rc, "POST", "/live/quit", {})
            wait_for(lambda: not self.live.ping(rc, 0.5), 15)
        if self.live.proc:
            try:
                self.live.proc.wait(10)
            except Exception:
                self.live.proc.kill()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_spawn_then_running_then_restart_old_version(self):
        self.assertEqual(self.live.tick(), "spawned", self.logs)
        rc = self.live.find("local")
        self.assertTrue(wait_for(lambda: self.live.ping(rc), 30), self.logs)
        self.assertTrue(self.live.local_token())   # 録画の部品が作った合言葉を読める
        rc = self.live.find("local")               # 合言葉は起動したあとにできる(読み直す)
        self.assertEqual(self.live.tick(), "running")
        code, d = self.live.call(rc, "GET", "/live/list")
        self.assertEqual(code, 200, d)
        self.assertEqual(os.path.normcase(d["folder"]), os.path.normcase(self.rec_folder))   # 設定の置き場所で起動した
        h = self.live.health()
        self.assertTrue(h["recorders"][0]["ok"])
        self.assertEqual(h["recorders"][0]["version"], h["recorders"][0]["expected"])
        # 置き場所を変えた → 見回りが伝える
        other = os.path.join(self.tmp, "other")
        FIX.patch_cfg(self.cfg, {"folder": other})
        self.assertEqual(self.live.tick(), "running")
        self.assertEqual(os.path.normcase(self.live.call(rc, "GET", "/live/config")[1]["folder"]), os.path.normcase(other))
        # コードの版が上がった → 録画中でなければ終わってもらって起動し直す
        old = self.live.proc
        with mock.patch.object(self.live, "expected_version", return_value="99.0.0"):
            self.assertEqual(self.live.tick(), "spawned", self.logs)
        self.assertIsNot(self.live.proc, old)
        self.assertEqual(old.wait(15), 0)
        self.assertTrue(wait_for(lambda: self.live.ping(rc), 30), self.logs)
        # オフにすると見回りは何もしない(録画の部品は止めない)
        FIX.patch_cfg(self.cfg, {"enabled": False})
        self.assertEqual(self.live.tick(), "off")
        self.assertTrue(self.live.ping(rc))


if __name__ == "__main__":
    unittest.main()
