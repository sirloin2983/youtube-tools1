# -*- coding: utf-8 -*-
"""flow/live_perf.py: 録画中だけ測る・CPU の差・子孫・スイッチ・片付け・本物の Windows の読み"""
import json
import os
import sys
import tempfile
import unittest

os.environ.setdefault("YTT_DATA_DIR", "inplace")   # テストは作業データを本物の置き場所に書かない(ytt.datadir)
SRC = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)
from flow import live_perf  # noqa: E402


class PerfLogTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.now = 1_000_000.0
        self.cpu = {10: 1.0, 20: 2.0, 21: 3.0, 30: 4.0}
        self.procs = {1: (0, "System"), 10: (1, "python.exe"), 20: (1, "python.exe"), 21: (20, "ffmpeg.exe"), 30: (10, "python.exe"),
                      99: (1, "other.exe")}
        self.sys = [100.0, 200.0]

    def log(self, **kw):
        return live_perf.PerfLog(self.tmp.name, lambda: {"入口": 10, "録画の部品": 20, "検出のワーカー": 30}, clock=lambda: self.now,
                                 snap=lambda: dict(self.procs), usage=lambda pid: (self.cpu[pid], 50.0),
                                 sys_times=lambda: tuple(self.sys), gpu=lambda: ({"util": 5.0, "memMB": 900.0}, {21: 120.0}),
                                 env={}, **kw)

    def test_records_only_while_recording(self):
        p = self.log()
        first = p.tick()
        self.assertEqual({r["pid"] for r in first["procs"]}, {10, 20, 21, 30})   # 99 は相手の子孫でない
        self.assertIsNone(first["procs"][0]["cpu"])
        self.assertIsNone(p.tick())   # 60 秒たっていない
        self.now += 60
        self.cpu[21] += 6.0 * (os.cpu_count() or 1)   # 60 秒で 6 秒 × CPU 数 = 10 %
        self.sys = [130.0, 260.0]
        row = {r["pid"]: r for r in p.tick()["procs"]}
        self.assertEqual(row[21]["cpu"], 10.0)
        self.assertEqual(row[21]["group"], "録画の部品")
        self.assertEqual(row[21]["gpuMB"], 120.0)
        lines = open(os.path.join(self.tmp.name, "perf", os.listdir(os.path.join(self.tmp.name, "perf"))[0]), encoding="utf-8").readlines()
        self.assertEqual(len(lines), 2)
        self.assertEqual(json.loads(lines[1])["sysCpu"], 50.0)
        del self.procs[21]   # 録画が終わった(ffmpeg がいない)= 測らない
        self.now += 60
        self.assertIsNone(p.tick())

    def test_switch_off_and_prune(self):
        p = self.log()
        p.env = {live_perf.SWITCH_ENV: "off"}
        self.assertIsNone(p.tick())
        os.makedirs(p.dir)
        open(os.path.join(p.dir, "19700101.jsonl"), "w").close()
        p.env = {}
        p.tick()
        self.assertNotIn("19700101.jsonl", os.listdir(p.dir))

    @unittest.skipUnless(os.name == "nt", "Windows だけ")
    def test_real_windows_reads(self):
        snap = live_perf.snapshot()
        self.assertIn(os.getpid(), snap)
        self.assertIn(os.getpid(), live_perf.descendants(snap, snap[os.getpid()][0]))
        cpu, mem = live_perf.proc_usage(os.getpid())
        self.assertGreater(cpu, 0)
        self.assertGreater(mem, 1)
        idle, total = live_perf.system_times()
        self.assertGreater(total, idle)


if __name__ == "__main__":
    unittest.main()
