# -*- coding: utf-8 -*-
"""録画中の入口の起き直し(引き継ぎ)の境目のテスト: 起き直しの後始末は録画の部品に quit も kill も送らない・普通の終了も録画中なら止めない・
running.json があれば 2 つ目を起こさない・recorder.lock を取れなければ 2 つ目は終わる・検出のワーカーの養子と親替え・_seen の読み戻し・
handover_ok の各 NG(スイッチ オフを含む)・handover.json の確かめ。

    py -3.12 -m unittest tests/flow/test_live_handover.py

偽の録画元(HTTP)と、何もしない子プロセス(sleep)だけを使う。本物の録画の部品(8730)・本物の作業データには触らない。
"""
import json
import os
import subprocess
import sys
import time
import types
import unittest
from unittest import mock

os.environ.setdefault("YTT_DATA_DIR", "inplace")   # テストは作業データを本物の置き場所(AppData など)に書かない(ytt.datadir)

TESTS = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.join(os.path.dirname(os.path.dirname(TESTS)), "src")
sys.path.insert(0, TESTS)
import _livefix as FIX  # noqa: E402
sys.path.insert(0, os.path.dirname(TESTS))
import testkit  # noqa: E402
from flow import live_export as LX  # noqa: E402
from flow import livesession as LS  # noqa: E402
from pipeline.analyze import live_excite_worker as EW  # noqa: E402
from ytt import fsio  # noqa: E402

TOKEN = FIX.TOKEN
REC = "20261004-000000-a"   # 録画の id の形(LX.REC_RE)
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def sleeper(test, sec=60):
    p = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(%d)" % sec], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL, creationflags=NO_WINDOW)

    def done():
        if p.poll() is None:
            p.kill()
            p.wait(5)
    test.addCleanup(done)
    return p


def write_json(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f)


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = testkit.tempdir(self, "ytt-live-handover-")
        self.logs = []
        self.fake = FIX.FakeRecorder()
        self.addCleanup(self.fake.close)
        self.rdata = os.path.join(self.tmp, "recdata")
        self.cfg = FIX.live_cfg(recorders=[{"id": "local", "name": "この PC", "url": self.fake.url, "token": TOKEN}])
        self.live = FIX.new_session(self.tmp, self.cfg, log=self.logs.append, root=REPO, data_dir=self.rdata)

    def quit_calls(self):
        return [s for s in self.fake.seen if s["path"] == "/live/quit"]

    def heartbeat(self, pid, recordings=True, age=0.0, parent=None):
        write_json(os.path.join(self.live.detector.dir, "worker.json"),
                   {"pid": pid, "parent": parent, "at": LX.epoch_iso(time.time() - age), "message": "",
                    "recordings": [{"recorder": "local", "id": "r1"}] if recordings else []})


class CloseTest(Base):
    def test_handover_close_sends_no_quit_and_no_kill(self):
        own = self.live.proc = sleeper(self)
        self.live.close(handover=True)
        self.assertEqual(self.quit_calls(), [])
        self.assertIsNone(own.poll())                                    # この入口が起こした部品でも止めない

    def test_normal_close_keeps_own_recorder_when_list_says_recording(self):
        own = self.live.proc = sleeper(self)
        self.fake.routes[("POST", "/live/quit")] = lambda b: (200, {"ok": True})   # quit を受けたのに終わらない(偽の /live/list は録画中)
        with mock.patch.object(LS, "QUIT_WAIT", 0.5):
            self.assertEqual(self.live.stop_recorder(), "kept")
        self.assertIsNone(own.poll())

    def test_handover_keeps_worker_that_measures(self):
        w = sleeper(self)
        self.heartbeat(w.pid)
        with mock.patch.object(self.live.detector, "stop") as stop:
            self.live.close(handover=True)
        stop.assert_not_called()
        live2 = FIX.new_session(self.tmp, self.cfg, log=self.logs.append, root=REPO, data_dir=self.rdata)
        with mock.patch.object(live2.detector, "stop") as stop:   # 普通の終了は止める
            live2.close()
        stop.assert_called_once()


class SecondRecorderTest(Base):
    def test_running_file_with_live_pid_blocks_spawn(self):
        p = sleeper(self)
        write_json(os.path.join(self.rdata, LS.RUNNING_FILE), {"pid": p.pid, "port": 1234})
        dead = "http://127.0.0.1:%d" % FIX.free_port()
        FIX.patch_cfg(self.cfg, {"recorders": [{"id": "local", "name": "この PC", "url": dead, "token": TOKEN}]})
        self.live.spawn_ok = True
        with mock.patch.object(self.live, "spawn") as spawn:
            self.assertEqual(self.live.tick(), "waiting")
        spawn.assert_not_called()
        self.assertTrue(any("新しく起こさずに" in m for m in self.logs), self.logs)
        os.remove(os.path.join(self.rdata, LS.RUNNING_FILE))           # 無ければ今までどおり起こす
        self.live._last_spawn = 0.0
        with mock.patch.object(self.live, "spawn", return_value=True) as spawn:
            self.assertEqual(self.live.tick(), "spawned")

    def test_default_local_uses_running_port(self):
        p = sleeper(self)
        write_json(os.path.join(self.rdata, LS.RUNNING_FILE), {"pid": p.pid, "port": 8999})
        FIX.patch_cfg(self.cfg, {"recorders": []})
        self.assertEqual(self.live.find("local")["url"], "http://127.0.0.1:8999")

    def test_lock_held_second_recorder_exits_2(self):
        lock = fsio.try_lock(os.path.join(self.rdata, "recorder.lock"))
        self.addCleanup(fsio.unlock, lock)
        r = subprocess.run([sys.executable, os.path.join(REPO, "pipeline", "ingest", "recorder.py"), "--port", str(FIX.free_port()),
                            "--data-dir", self.rdata, "--folder", os.path.join(self.tmp, "rec"), "--quiet"],
                           stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=60, creationflags=NO_WINDOW)
        self.assertEqual(r.returncode, 2, r.stdout.decode("utf-8", "replace"))
        self.assertFalse(os.path.exists(os.path.join(self.rdata, LS.RUNNING_FILE)))


class HandoverOkTest(Base):
    def setUp(self):
        super().setUp()
        self.rp = sleeper(self)
        self.fake.routes[("GET", "/api/ping")] = lambda b: (200, {"app": "ytt-recorder", "version": "0.0.1", "api": 1, "pid": self.rp.pid})
        write_json(os.path.join(self.rdata, LS.RUNNING_FILE), {"pid": self.rp.pid, "port": self.fake.port, "inJob": False})
        FIX.patch_cfg(self.cfg, {"restartWhileRecording": True})

    def assertNg(self, part):
        ok, why = self.live.handover_ok()
        self.assertFalse(ok)
        self.assertIn(part, why)

    def test_all_ok(self):
        self.assertEqual(self.live.handover_ok(), (True, ""))

    def test_switch_off(self):
        FIX.patch_cfg(self.cfg, {"restartWhileRecording": False})
        self.assertNg("オフ")

    def test_old_recorder_without_api(self):
        self.fake.routes[("GET", "/api/ping")] = lambda b: (200, {"app": "ytt-recorder", "version": "0.0.1"})
        self.assertNg("知らない版")

    def test_running_file_missing_or_other_pid(self):
        os.remove(os.path.join(self.rdata, LS.RUNNING_FILE))
        self.assertNg("running.json")
        write_json(os.path.join(self.rdata, LS.RUNNING_FILE), {"pid": os.getpid(), "port": self.fake.port})
        self.assertNg("running.json")

    def test_in_job(self):
        write_json(os.path.join(self.rdata, LS.RUNNING_FILE), {"pid": self.rp.pid, "port": self.fake.port, "inJob": True})
        with mock.patch.object(LS.procs, "in_job", return_value=False):
            self.assertNg("ジョブ")

    def test_encoding_export(self):
        self.live._exporter = types.SimpleNamespace(lock=mock.MagicMock(), jobs=[{"state": "encode"}])
        self.assertNg("書き出し")

    def test_worker_not_adoptable(self):
        self.heartbeat(os.getpid())                                     # 自分の pid = 引き継げない
        self.assertNg("ワーカー")
        w = sleeper(self)
        self.heartbeat(w.pid, age=999)                                  # 心拍が古い
        self.assertNg("ワーカー")
        self.heartbeat(w.pid)
        self.assertEqual(self.live.handover_ok(), (True, ""))

    def test_handover_file_checked(self):
        w = sleeper(self)
        self.heartbeat(w.pid, age=0)
        self.fake.routes[("GET", "/live/list")] = lambda b: (200, {"recordings": [{"id": REC, "active": True, "url": "", "title": ""}]})
        self.live.write_handover()
        path = os.path.join(self.live.store_dir, LS.HANDOVER_FILE)
        d = fsio.read_json_or(path, kind=dict)
        self.assertEqual((d["workerPid"], d["recorderPid"], [r["id"] for r in d["recordings"]]), (w.pid, self.rp.pid, [REC]))
        self.assertIsNone(self.live.check_handover(now=d["at"] + 5))    # 早すぎる間は確かめない
        self.assertTrue(os.path.exists(path))
        self.heartbeat(w.pid, age=-120)                                 # 起き直したあとに心拍が続いた
        self.assertEqual(self.live.check_handover(now=d["at"] + 61), [])
        self.assertFalse(os.path.exists(path))
        # 録画が終わっていた・ワーカーが替わった → 記録と「調子」
        self.live._handover_checked = False
        self.live.write_handover()
        self.fake.routes[("GET", "/live/list")] = lambda b: (200, {"recordings": [{"id": REC, "active": False, "url": "", "title": ""}]})
        self.heartbeat(os.getpid(), age=-120)
        bad = self.live.check_handover(now=time.time() + 61)
        self.assertEqual(len(bad), 2, bad)
        self.assertEqual([f["kind"] for f in self.live._handover_fails], ["handover", "handover"])


class AdoptWorkerTest(Base):
    def test_adopt_fresh_worker_without_spawning(self):
        w = sleeper(self)
        self.heartbeat(w.pid)
        det = self.live.detector
        with mock.patch.object(det, "_spawn") as spawn:
            self.assertEqual(det._ensure(), "adopted")
            self.assertEqual(det._ensure(), "adopted")
        spawn.assert_not_called()
        self.assertEqual(det.adopted, w.pid)
        self.assertEqual(fsio.read_json_or(os.path.join(det.dir, EW.PARENT_NAME), kind=dict)["pid"], os.getpid())
        self.assertEqual(sum("引き継ぎました" in m for m in self.logs), 1)

    def test_idle_worker_is_stopped_and_replaced(self):
        w = sleeper(self, 2)
        self.heartbeat(w.pid, recordings=False)
        det = self.live.detector
        with mock.patch.object(det, "_spawn", return_value=True) as spawn:
            self.assertEqual(det._ensure(), "spawned")
        spawn.assert_called_once()
        self.assertTrue(os.path.exists(os.path.join(det.dir, EW.STOP_NAME)))

    def test_stale_or_dead_worker_is_not_adopted(self):
        det = self.live.detector
        self.heartbeat(os.getpid())
        self.assertIsNone(det.adoptable())
        w = sleeper(self)
        self.heartbeat(w.pid, age=999)
        self.assertIsNone(det.adoptable())
        self.heartbeat(w.pid, parent=sleeper(self).pid)                 # 親が生きている = ほかの入口のワーカー
        self.assertIsNone(det.adoptable())
        self.heartbeat(w.pid, parent=os.getpid())                       # 親がこの入口: 引き継がない・終わる前の確かめでは可
        self.assertIsNone(det.adoptable())
        self.assertEqual(det.adoptable(leaving=True), w.pid)


class SeenTest(Base):
    def test_seen_survives_restart(self):
        det = self.live.detector
        det._load_seen(1000.0)
        det._seen[("local", "r1", "p1")] = 1000.0
        det._save_seen()
        det2 = FIX.new_session(self.tmp, self.cfg, log=self.logs.append, root=REPO, data_dir=self.rdata).detector
        det2._load_seen(1300.0)
        self.assertEqual(det2._seen, {("local", "r1", "p1"): 1000.0})   # 起点はそのまま(waitMin が延びない)
        self.assertEqual(det2._seen_at[("local", "r1", "p1")], 1300.0)


class WorkerOrphanTest(unittest.TestCase):
    def setUp(self):
        self.tmp = testkit.tempdir(self, "ytt-excite-orphan-")
        cfg = os.path.join(self.tmp, "config.json")
        write_json(cfg, {"v": 1, "dir": self.tmp, "recorders": []})
        self.now = [1000.0]
        self.logs = []
        self.w = EW.Worker(cfg, clock=lambda: self.now[0], log=self.logs.append, parent=999999)

    def test_no_recordings_ends(self):
        self.assertFalse(self.w._orphan_ok())

    def test_measuring_waits_up_to_limit(self):
        self.w.recs = {("local", "r1"): types.SimpleNamespace(finished=False)}
        self.assertTrue(self.w._orphan_ok())
        self.now[0] += EW.ORPHAN_SEC - 1
        self.assertTrue(self.w._orphan_ok())
        self.now[0] += 2
        self.assertFalse(self.w._orphan_ok())

    def test_new_parent_is_taken(self):
        p = sleeper(self)
        write_json(os.path.join(self.tmp, EW.PARENT_NAME), {"pid": p.pid})
        self.assertTrue(self.w._orphan_ok())
        self.assertEqual(self.w.parent, p.pid)
        self.assertIsNone(self.w.orphan_at)


if __name__ == "__main__":
    unittest.main()
