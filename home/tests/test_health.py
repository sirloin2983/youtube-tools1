"""home/health.py(「調子」。段9 9-1)の単体テスト。

    python -m unittest home/tests/test_health.py
"""
import json
import os
import shutil
import sys
import tempfile
import time
import unittest

os.environ.setdefault("YTT_DATA_DIR", "inplace")
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, os.path.dirname(os.path.dirname(HERE)))
import health as H  # noqa: E402


class SizesTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="ytt-health-")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def write(self, rel, size):
        p = os.path.join(self.tmp, rel)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "wb") as f:
            f.write(b"x" * size)
        return p

    def test_dir_size_and_top_items(self):
        self.write("a/one.bin", 300)
        self.write("a/sub/two.bin", 200)
        self.write("b.bin", 50)
        self.assertEqual(H.dir_size(self.tmp), (550, 3))
        self.assertEqual(H.dir_size(os.path.join(self.tmp, "b.bin")), (50, 1))
        self.assertEqual(H.dir_size(os.path.join(self.tmp, "nothing")), (0, 0))
        items = H.top_items(self.tmp)
        self.assertEqual([(i["name"], i["bytes"], i["files"], i["dir"]) for i in items], [("a", 500, 2, True), ("b.bin", 50, 1, False)])
        self.assertEqual(len(H.top_items(self.tmp, limit=1)), 1)

    def test_disk_free_dedupes_by_drive(self):
        out = H.disk_free([self.tmp, os.path.join(self.tmp, "not-yet", "deeper"), self.tmp])
        self.assertEqual(len(out), 1)                          # 同じドライブは1つ
        self.assertGreater(out[0]["totalBytes"], 0)
        self.assertLessEqual(out[0]["freeBytes"], out[0]["totalBytes"])
        self.assertEqual(H.disk_free([""]), [])

    def test_data_sizes_inplace(self):
        d = H.data_sizes()   # YTT_DATA_DIR=inplace → 各ツールのフォルダ(存在する物だけ)
        self.assertIn("dirs", d)
        self.assertTrue(all(os.path.isdir(x["path"]) for x in d["dirs"]))
        self.assertEqual(d["bytes"], sum(x["bytes"] for x in d["dirs"]))


class ToolsTest(unittest.TestCase):
    def test_parse_version_line(self):
        self.assertEqual(H.parse_version_line("ffmpeg", "ffmpeg version 6.1.1-full_build-www.gyan.dev Copyright (c) 2000-2023"), "6.1.1-full_build-www.gyan.dev")
        self.assertEqual(H.parse_version_line("yt-dlp", "2025.09.05\n"), "2025.09.05")
        self.assertEqual(H.parse_version_line("x", ""), "")

    def test_tool_version_missing(self):
        self.assertEqual(H.tool_version("ytt-no-such-program-xyz"), {"path": None, "version": ""})


class ErrorsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="ytt-health-")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_count_client_errors_window(self):
        now = time.time()
        p = os.path.join(self.tmp, "client-errors.jsonl")
        stamp = lambda t: time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(t))  # noqa: E731
        with open(p, "w", encoding="utf-8") as f:
            f.write(json.dumps({"at": stamp(now - 60), "tool": "studio", "msg": "a"}) + "\n")
            f.write(json.dumps({"at": stamp(now - 2 * 3600), "tool": "portal", "msg": "b"}) + "\n")
            f.write(json.dumps({"at": stamp(now - 3 * 86400), "tool": "portal", "msg": "old"}) + "\n")
            f.write("broken line\n")
            f.write(json.dumps({"tool": "portal", "msg": "no stamp"}) + "\n")
        with open(p + ".1", "w", encoding="utf-8") as f:
            f.write(json.dumps({"at": stamp(now - 5 * 3600), "tool": "portal", "msg": "rotated"}) + "\n")
        self.assertEqual(H.count_client_errors(p, now), 3)
        self.assertEqual(H.count_client_errors(os.path.join(self.tmp, "none.jsonl"), now), 0)

    def test_count_autorun_failed(self):
        now = time.time()
        p = os.path.join(self.tmp, "autorun-runs.jsonl")
        with open(p, "w", encoding="utf-8") as f:
            f.write(json.dumps({"state": "error", "created": int((now - 3600) * 1000)}) + "\n")
            f.write(json.dumps({"state": "done", "created": int((now - 3600) * 1000)}) + "\n")
            f.write(json.dumps({"state": "error", "created": int((now - 10 * 86400) * 1000)}) + "\n")
        self.assertEqual(H.count_autorun_failed(p, now), 1)


class FakeSup:
    def __init__(self, tools):
        self.tools = tools

    def status(self):
        return {"tools": self.tools, "heavy": {"limit": 1, "active": [], "waiting": []}}


class HealthTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="ytt-health-")
        self.logs = os.path.join(self.tmp, "logs")
        os.makedirs(self.logs)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_snapshot_shape_and_version_check(self):
        sup = FakeSup([{"id": "studio", "name": "スタジオ", "state": "running", "version": "0.13.0", "expectedVersion": "0.13.0"},
                       {"id": "transcribe", "name": "編集", "state": "running", "version": "0.29.0", "expectedVersion": "0.30.0"},
                       {"id": "cut2resolve", "name": "c2r", "state": "stopped", "version": "", "expectedVersion": "0.16.0"}])
        h = H.Health(sup, self.logs, worker_probe=lambda: {"alive": True, "pid": 1}, cache_sec=600)
        s = h.snapshot()
        self.assertEqual([(v["tool"], v["ok"]) for v in s["versions"]], [("studio", True), ("transcribe", False), ("cut2resolve", True)])
        self.assertEqual(s["worker"], {"alive": True, "pid": 1})
        self.assertEqual(s["errors"]["clientLast24h"], 0)
        self.assertEqual(s["heavy"]["limit"], 1)
        self.assertTrue(s["disk"] and s["disk"][0]["totalBytes"] > 0)
        for _ in range(50):   # 重い物は別のスレッド(1.5 秒は待つ)。終わっていれば data・tools が入る
            if s["data"] is not None:
                break
            time.sleep(0.1)
            s = h.snapshot()
        self.assertIsNotNone(s["data"])
        self.assertIn("ffmpeg", s["tools"])
        self.assertIn("countedAt", s)

    def test_cache_and_refresh(self):
        calls = []
        orig = H.data_sizes
        H.data_sizes = lambda *a, **k: (calls.append(1), {"root": None, "dirs": [], "bytes": 0})[1]
        try:
            now = [1000.0]
            h = H.Health(FakeSup([]), self.logs, clock=lambda: now[0], cache_sec=100)
            h.snapshot()
            for _ in range(50):
                if h._slow:
                    break
                time.sleep(0.05)
            h.snapshot(); h.snapshot()
            self.assertEqual(len(calls), 1)             # 期限内は数え直さない
            now[0] += 200
            h.snapshot()
            for _ in range(50):
                if len(calls) >= 2:
                    break
                time.sleep(0.05)
            self.assertEqual(len(calls), 2)             # 期限が過ぎたら数え直す
            h.snapshot(refresh=True)
            for _ in range(50):
                if len(calls) >= 3:
                    break
                time.sleep(0.05)
            self.assertEqual(len(calls), 3)             # 「数え直す」
        finally:
            H.data_sizes = orig

    def test_worker_probe_failure_is_tolerated(self):
        def boom():
            raise RuntimeError("x")
        s = H.Health(FakeSup([]), self.logs, worker_probe=boom).snapshot()
        self.assertIsNone(s["worker"])


if __name__ == "__main__":
    unittest.main()
