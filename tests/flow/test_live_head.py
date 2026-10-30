# -*- coding: utf-8 -*-
"""遅れて始まったライブの頭を別に取る src/flow/live_head.py(HeadGrabber)のテスト。本物の yt-dlp・YouTube は使わない
(偽の yt-dlp = tests/flow/fake_ytdlp_head.py を本物の起こし方(窓なし・KillJob・木ごと止める)で動かす)。音は出さない(ffmpeg は書き出すだけ)。

    py -3.12 -m unittest tests/flow/test_live_head.py

確かめること(完了の条件。区切りに入って録れなかった所から外れる (b) は tests/flow/test_live_detect.py の test_batch_head):
  (a) 遅れ 60 秒未満は動かない・60 秒以上は 1 回だけ始める
  (c) 取得が失敗しても今の録画と検出(peaks.json)は変わらない・止めたあと自分が起こした PID の木(yt-dlp とその子)が残らない
  (d) yt-dlp に cookies を渡さない(引数にも環境変数にも)
  頭の検出(head_peaks)・頭の動画から書き出す(live_export の from head。ffmpeg があるときだけ)
"""
import ctypes
import json
import os
import shutil
import subprocess
import sys
import time
import unittest
from unittest import mock

os.environ.setdefault("YTT_DATA_DIR", "inplace")

TESTS = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, TESTS)
import _livefix as LF  # noqa: E402
import test_live_detect as TD  # noqa: E402
sys.path.insert(0, os.path.dirname(TESTS))
import testkit  # noqa: E402
from flow import live_head as LH  # noqa: E402
from flow import live_export as LX  # noqa: E402
from ytt import tools  # noqa: E402

FAKE = os.path.join(TESTS, "fake_ytdlp_head.py")
REC, T0, iso = TD.REC, TD.T0, TD.iso


def alive(pid):
    """pid のプロセスが動いているか(Windows は GetExitCodeProcess。ほかは kill 0)"""
    if os.name != "nt":
        try:
            os.kill(pid, 0)
            return True
        except OSError:
            return False
    k = ctypes.windll.kernel32
    h = k.OpenProcess(0x1000, False, pid)   # PROCESS_QUERY_LIMITED_INFORMATION
    if not h:
        return False
    try:
        code = ctypes.c_ulong()
        return bool(k.GetExitCodeProcess(h, ctypes.byref(code))) and code.value == 259   # STILL_ACTIVE
    finally:
        k.CloseHandle(h)


class HeadTest(unittest.TestCase):
    def setUp(self):
        self.tmp = testkit.tempdir(self, "ytt-head-")
        self.rec = TD.ListRecorder()
        self.live = LF.new_session(self.tmp, LF.recorder_cfg(self.rec.url, TD.TOKEN), log=lambda m: None)
        self.live.studio_call = LF.FakeStudio()
        self.live.exporter.start = lambda: None
        self.live.disk_usage = lambda p: (500 * LX.GB, 1000 * LX.GB)
        self.out = os.path.join(self.tmp, "fake-out")
        os.makedirs(self.out)
        self.g = self.live.head
        self.g.poll = 0.1
        self.live.detector.ytdlp = lambda: "yt-dlp"
        self.peaks_json = os.path.join(self.live.detector.folder("fake", REC), "peaks.json")
        os.makedirs(os.path.dirname(self.peaks_json), exist_ok=True)
        with open(self.peaks_json, "w", encoding="utf-8") as f:
            f.write('{"v": 1, "peaks": []}')

    def tearDown(self):
        self.g.stop()
        self.rec.close()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def stream(self, delay):
        row = dict(self.rec._rec(), streamStart=iso(T0 - delay))
        self.rec.routes[("GET", "/live/list")] = lambda body: (200, {"recordings": [row]})
        self.live.requests.put("fake", REC, {"rid": "20261008-120000-abcd", "deliverDir": os.path.join(self.tmp, "deliver"), "streamer": "", "settings": {}})

    def read_peaks(self):
        with open(self.peaks_json, encoding="utf-8") as f:
            return f.read()

    def fake_launcher(self):
        self.g.spawn = True
        self.g.launcher = lambda cmd, log: self.g._popen([sys.executable, FAKE] + cmd[1:], log)
        self.g.probe = lambda p: os.path.getsize(p) / 1000.0 if p and os.path.isfile(p) else None   # 1000 バイト = 1 秒の見立て

    def wait(self):
        for th in list(self.g.threads.values()):
            th.join(60)
        return self.g.load("fake", REC) or {}

    def test_a_delay_threshold(self):
        calls = []
        self.g.spawn = True
        self.g.launcher = lambda cmd, log: calls.append(cmd) or mock.Mock(poll=lambda: 1, pid=0)
        self.stream(30)   # 遅れ 30 秒: 動かない
        self.assertEqual(self.g.tick(), 0)
        self.assertEqual((calls, self.g.load("fake", REC)), ([], None))
        self.stream(120)
        self.assertEqual(self.g.tick(), 1)
        doc = self.wait()
        self.assertEqual(doc["state"], "error")   # 偽の起動は何も取らない = 使わない
        self.assertEqual(len(calls), 2)
        self.assertTrue(all("--live-from-start" in c for c in calls))
        self.assertEqual(self.g.tick(), 0)   # 1 録画 1 回
        with mock.patch.object(LH, "HEAD_ON", False):
            self.g.threads.clear()
            self.assertEqual(self.g.tick(), 0)

    def test_c_d_stop_tree_no_cookies(self):
        """偽の yt-dlp は子を作って書き続ける: 長さに届いたら PID の木ごと止まり、つなぎ(偽のデータ)で失敗しても録画と検出は変わらない"""
        self.fake_launcher()
        self.stream(60)
        before = self.read_peaks()
        with mock.patch.dict(os.environ, {tools.COOKIES_ENV: os.path.join(self.tmp, "cookies.txt"), "FAKE_HEAD_OUT": self.out}):
            self.assertEqual(self.g.tick(), 1)
            doc = self.wait()
        self.assertEqual(doc["state"], "error")
        self.assertGreaterEqual(doc["grabSec"], 0)
        for k in ("v", "a"):
            with open(os.path.join(self.out, k + ".args.json"), encoding="utf-8") as f:
                a = json.load(f)
            self.assertFalse(a["cookieEnv"])
            self.assertTrue({"--ignore-config", "--no-cookies", "--no-cookies-from-browser"} <= set(a["argv"]))
            self.assertFalse([x for x in a["argv"] if x in ("--cookies", "--cookies-from-browser")])
            with open(os.path.join(self.out, k + ".pids"), encoding="utf-8") as f:
                pids = [int(x) for x in f.read().split()]
            for _ in range(50):
                if not any(alive(p) for p in pids):
                    break
                time.sleep(0.1)
            self.assertFalse([p for p in pids if alive(p)])   # yt-dlp とその子が残らない
        self.assertFalse(os.path.isdir(self.g.work(REC)))   # 失敗したら作業の置き場を消す
        self.assertEqual(self.read_peaks(), before)   # 検出の正本は触らない
        self.assertEqual(self.g.peaks("fake", REC), [])
        self.assertEqual(self.g.cover("fake", REC), 0.0)

    def test_c_fail_reason(self):
        self.fake_launcher()
        self.stream(600)
        with mock.patch.dict(os.environ, {"FAKE_HEAD_MODE": "fail", "FAKE_HEAD_OUT": self.out}):
            self.g.tick()
            doc = self.wait()
        self.assertEqual(doc["state"], "error")
        self.assertIn("This live event has ended", doc["reason"])
        self.assertEqual((self.live.archiver.info.get(self.live.archiver.key("fake", REC)) or {}).get("head", {}).get("state"), "error")   # archive.json にも

    def test_disk_low_skips(self):
        self.fake_launcher()
        self.stream(600)
        self.live.disk_usage = lambda p: (6 * LX.GB, 1000 * LX.GB)
        self.g.tick()
        doc = self.wait()
        self.assertEqual(doc["state"], "skipped")
        self.assertIn("空き", doc["reason"])

    def test_head_peaks(self):
        """頭の音: 静かな所に 1 回の大きな山(600 秒目)と、録画の頭(upto)より後の山 → 頭の山だけ"""
        full = [-40.0] * 1500
        band = [-50.0] * 1500
        for t in range(600, 612):
            full[t], band[t] = -8.0, -12.0
        for t in range(1300, 1312):
            full[t], band[t] = -8.0, -12.0
        got = LH.head_peaks(full, band, {}, {"sens": "normal", "perHour": 10}, 1000)
        self.assertEqual(len(got), 1)
        self.assertTrue(560 <= got[0]["peak"] <= 620 and got[0].get("audioOnly"))

    @unittest.skipUnless(tools.find_tool("ffmpeg") and tools.find_tool("ffprobe"), "ffmpeg が無い")
    def test_export_from_head(self):
        """頭の動画(20 秒)から録画の頭の 15〜5 秒前を書き出す: 採用(hold head)→ from head のジョブ → 頭の動画から切って done"""
        wd = self.g.work(REC)
        os.makedirs(wd)
        path = os.path.join(wd, "head.mp4")
        subprocess.run([tools.find_tool("ffmpeg"), "-nostdin", "-v", "error", "-f", "lavfi", "-i", "testsrc=size=320x240:rate=30", "-f", "lavfi",
                        "-i", "sine=frequency=440", "-t", "20", "-c:v", "libx264", "-c:a", "aac", "-shortest", path],
                       check=True, creationflags=tools.no_window_flags())
        folder = self.live.detector.folder("fake", REC)
        with open(os.path.join(folder, LH.STATE_FILE), "w", encoding="utf-8") as f:
            json.dump({"v": 1, "state": "done", "coverSec": 18.0, "startAt": iso(T0 - 18), "endAt": iso(T0 + 2), "path": path, "peaks": []}, f)
        self.rec.routes[("GET", "/live/%s/segments" % REC)] = lambda body: (200, dict(self.rec._rec(), segments=[], gaps=[]))
        res = self.live.adopt({"recorder": "fake", "recording": REC, "start": -15, "end": -5, "origin": "auto", "label": ""}, "head")
        job = res["job"]
        self.assertEqual((job["from"], res["video"]), ("head", None))
        got = self.live.exporter._next_ready()
        self.assertEqual(got["id"], job["id"])
        self.live.exporter._process(got)
        j = next(x for x in self.live.exporter.snapshot("fake", REC) if x["id"] == job["id"])
        self.assertEqual(j["state"], "done", j.get("error"))
        self.assertTrue(os.path.isfile(j["path"]))
        again = self.live.adopt({"recorder": "fake", "recording": REC, "start": -15, "end": -5, "origin": "auto", "label": ""}, "head")
        self.assertTrue(again["existing"])   # 同じ区間は使い回す


if __name__ == "__main__":
    unittest.main()
