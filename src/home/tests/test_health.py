"""src/home/health.py(「調子」。段9 9-1)の単体テスト。

    python -m unittest src/home/tests/test_health.py
"""
import json
import os
import shutil
import sys
import subprocess
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
            # あとから解析(測るため)の失敗は数えない(依頼の失敗に見せない。2026-10-05)
            f.write(json.dumps({"state": "error", "mode": "post_analyze", "created": int((now - 3600) * 1000)}) + "\n")
            f.write(json.dumps({"state": "error", "mode": "request", "created": int((now - 3600) * 1000)}) + "\n")
        self.assertEqual(H.count_autorun_failed(p, now), 2)


NS = "http://schemas.microsoft.com/win/2004/08/events/event"


def _evt(provider, eid, data=None):
    d = "".join("<Data>%s</Data>" % x for x in (data or []))
    return ('<Event xmlns="%s"><System><Provider Name="%s"/><EventID Qualifiers="16384">%s</EventID></System>'
            '<EventData>%s</EventData></Event>' % (NS, provider, eid, d))


class FakeRun:
    """subprocess.run の代わり。ログ名(System / Application)ごとに XML を返す。out が None なら wevtutil が無い"""

    def __init__(self, system, application, code=0):
        self.by_log, self.code, self.calls = {"System": system, "Application": application}, code, []

    def __call__(self, cmd, **kw):
        self.calls.append((cmd, kw))
        out = self.by_log[cmd[2]]

        class R:
            returncode = self.code
            stdout = out.encode("utf-8")
        return R()


class CrashCountsTest(unittest.TestCase):
    def test_counts_os_and_apps(self):
        system = "".join([_evt("Microsoft-Windows-Kernel-Power", 41), _evt("Microsoft-Windows-Kernel-Power", 41),
                          _evt("Microsoft-Windows-Kernel-Power", 42),            # 41 以外は数えない
                          _evt("EventLog", 6008), _evt("Microsoft-Windows-WHEA-Logger", 17), _evt("Microsoft-Windows-WHEA-Logger", 18)])
        app = "".join([_evt("Application Error", 1000, ["Python.EXE", "3.10"]), _evt("Application Error", 1000, ["ffmpeg.exe"]),
                       _evt("Application Error", 1000, ["MSEdge.exe"]), _evt("Application Error", 1000, ["notepad.exe"]),
                       _evt("Application Error", 1000, ["explorer.exe"]), _evt("Application Error", 1001, ["python.exe"])])
        run = FakeRun(system, app)
        r = H.crash_counts(runner=run)
        self.assertEqual(r["windowSec"], 7 * 24 * 3600)
        self.assertEqual(r["os"], {"kernelPower41": 2, "unexpectedShutdown6008": 1, "whea": 2, "total": 5})
        self.assertEqual((r["apps"]["python.exe"], r["apps"]["ffmpeg.exe"], r["apps"]["msedge.exe"], r["apps"]["pythonw.exe"]), (1, 1, 1, 0))
        self.assertEqual((r["apps"]["other"], r["apps"]["total"]), (2, 5))     # 名前は小文字にそろえる。1001 は数えない
        cmd, kw = run.calls[0]
        self.assertEqual(cmd[:3], ["wevtutil", "qe", "System"])
        self.assertIn("604800000", cmd[3])                                     # 7 日(ミリ秒)
        self.assertEqual(kw["timeout"], 15.0)
        self.assertEqual(run.calls[1][0][2], "Application")

    def test_empty_logs_are_zero(self):
        r = H.crash_counts(runner=FakeRun("", ""))
        self.assertEqual(r["os"]["total"], 0)
        self.assertEqual(r["apps"]["total"], 0)

    def test_failure_returns_none(self):
        self.assertIsNone(H.crash_counts(runner=FakeRun("", "", code=5)))      # 権限(アクセスが拒否された)
        self.assertIsNone(H.crash_counts(runner=FakeRun("<broken", "")))       # 解析できない

        def missing(cmd, **kw):
            raise FileNotFoundError("wevtutil")

        def slow(cmd, **kw):
            raise subprocess.TimeoutExpired(cmd, 15)
        self.assertIsNone(H.crash_counts(runner=missing))
        self.assertIsNone(H.crash_counts(runner=slow))

    def test_count_worker_incidents(self):
        tmp = tempfile.mkdtemp(prefix="ytt-health-")
        try:
            now = time.time()
            stamp = lambda t: time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(t)) + ",123"  # noqa: E731
            p = os.path.join(tmp, "serve.log")
            with open(p, "w", encoding="utf-8") as f:
                f.write(stamp(now - 60) + " 認識ワーカーが異常終了しました(終了コード -1073741819)\n")
                f.write(stamp(now - 3600) + " 認識ワーカーから 600 秒なにも届かないため強制終了します\n")
                f.write(stamp(now - 10 * 86400) + " 認識ワーカーが異常終了しました(終了コード 1)\n")   # 7 日より前
                f.write(stamp(now - 60) + " ジョブ開始\n")
            with open(p + ".1", "w", encoding="utf-8") as f:
                f.write(stamp(now - 86400) + " 認識ワーカーが異常終了しました(終了コード None)\n")
            self.assertEqual(H.count_worker_incidents(p, now), {"crashed": 2, "hung": 1})
            self.assertEqual(H.count_worker_incidents(os.path.join(tmp, "none.log"), now), {"crashed": 0, "hung": 0})
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


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

    def test_snapshot_crashes(self):
        """異常終了の件数は data・tools のあとに入る(wevtutil が遅くても先の物は出る)。読めなければ events が None"""
        for fn, want in ((lambda: {"os": {"total": 1}}, {"os": {"total": 1}}), (lambda: None, None)):
            h = H.Health(FakeSup([]), self.logs, crash_fn=fn)
            s = h.snapshot()
            for _ in range(50):
                if s["crashes"] is not None:
                    break
                time.sleep(0.1)
                s = h.snapshot()
            self.assertEqual(s["crashes"]["events"], want)
            self.assertEqual(s["crashes"]["windowSec"], 7 * 24 * 3600)
            self.assertIsInstance(s["crashes"]["tool"], dict)
            self.assertFalse(s["computing"])

    def test_cache_and_refresh(self):
        calls = []
        orig = H.data_sizes
        H.data_sizes = lambda *a, **k: (calls.append(1), {"root": None, "dirs": [], "bytes": 0})[1]
        try:
            now = [1000.0]
            h = H.Health(FakeSup([]), self.logs, clock=lambda: now[0], cache_sec=100, crash_fn=lambda: None)
            h.snapshot()
            for _ in range(50):
                if h._slow and not h._computing:   # 異常終了の件数まで終わるのを待つ(終わるまで次の数え直しは始まらない)
                    break
                time.sleep(0.05)
            h.snapshot(); h.snapshot()
            self.assertEqual(len(calls), 1)             # 期限内は数え直さない
            now[0] += 200
            h.snapshot()
            for _ in range(50):
                if len(calls) >= 2 and not h._computing:
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
