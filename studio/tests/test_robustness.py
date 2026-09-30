"""データを失わない・壊れたファイルで止まらない、のテスト(feedback.jsonl・registry.json・キャッシュ・ログ・ポートの確保)。
ネットワーク・ffmpeg は使わない(ポートは 127.0.0.1 の空きポートだけ)。 実行: python3 test_robustness.py"""
import gzip
import json
import os
os.environ.setdefault("YTT_DATA_DIR", "inplace")   # テストは作業データを本物の置き場所(AppData など)に書かない(ytt_core.datadir)
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

os.environ["STUDIO_FAKE"] = "1"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))   # ツールのフォルダ(studio/)
import analyze
import common
import exporter
import rank
import serve
from common import ApiError


class Home(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        common.set_home(self.tmp)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def lines(self, name):
        p = os.path.join(self.tmp, name)
        if not os.path.exists(p):
            return []
        with open(p, encoding="utf-8") as f:
            return [l for l in f.read().split("\n") if l]


VIDEO = {"id": "abcdefghijk", "kind": "youtube", "duration": 100, "analysis": None}


class TestFeedbackFile(Home):
    def write(self, n, start=0):
        for i in range(start, start + n):
            self.assertTrue(analyze.feedback_for_mark(VIDEO, {"start": i, "end": i + 1, "src": "manual"}, "good", "adopt"))

    def test_rotation_never_drops_rows(self):
        with patch.object(analyze, "MAX_FEEDBACK_BYTES", 1000):
            self.write(30)   # 何度も切り替わる量
        rows = [json.loads(l) for l in self.lines("feedback.jsonl.old") + self.lines("feedback.jsonl")]
        self.assertEqual(sorted(r["start"] for r in rows), list(range(30)))   # 以前は2回目の切り替えで古い行が消えていた
        self.assertGreater(len(self.lines("feedback.jsonl.old")), len(self.lines("feedback.jsonl")))

    def test_partial_last_line_is_not_joined(self):
        p = os.path.join(self.tmp, "feedback.jsonl")
        with open(p, "w", encoding="utf-8") as f:
            f.write('{"start": 0, "verdict": "go')   # 電源断などで書きかけの行
        self.write(1, start=5)
        lines = self.lines("feedback.jsonl")
        self.assertEqual(len(lines), 2)
        self.assertEqual(json.loads(lines[1])["start"], 5)   # 新しい行は読める

    def test_old_file_without_trailing_newline(self):
        with open(os.path.join(self.tmp, "feedback.jsonl.old"), "w", encoding="utf-8") as f:
            f.write('{"start": -1}')
        with patch.object(analyze, "MAX_FEEDBACK_BYTES", 10):
            self.write(3)
        old = self.lines("feedback.jsonl.old")
        self.assertEqual(json.loads(old[0])["start"], -1)
        self.assertTrue(all(json.loads(l) for l in old))

    def test_default_limit_is_large(self):
        self.assertGreaterEqual(analyze.MAX_FEEDBACK_BYTES, 32 * 1024 * 1024)


class TestRegistry(Home):
    def reg_path(self):
        return os.path.join(self.tmp, "registry.json")

    def test_corrupt_registry_is_quarantined_not_overwritten(self):
        with open(self.reg_path(), "w", encoding="utf-8") as f:
            f.write('{"agencies": [{"name": "自分の事務所", "channels": [')   # 壊れている
        reg = rank.get_registry()
        with open(rank.SEED, encoding="utf-8") as f:
            seed = rank.sanitize_registry(json.load(f))
        self.assertEqual(reg, seed)   # 使えるのは seed
        backups = [n for n in os.listdir(self.tmp) if n.startswith("registry.json.corrupt-")]
        self.assertEqual(len(backups), 1)
        self.assertTrue(backups[0].endswith(".bak"))   # .gitignore の *.bak に掛かる名前
        with open(os.path.join(self.tmp, backups[0]), encoding="utf-8") as f:
            self.assertIn("自分の事務所", f.read())   # 元の内容は残っている
        self.assertFalse(os.path.exists(self.reg_path()))

    def test_non_object_registry_is_quarantined(self):
        with open(self.reg_path(), "w", encoding="utf-8") as f:
            f.write("[1, 2]")
        rank.get_registry()   # 以前は AttributeError で 500
        self.assertTrue(any(n.startswith("registry.json.corrupt-") for n in os.listdir(self.tmp)))

    def test_transient_read_error_does_not_fall_back_to_seed(self):
        rank.put_registry({"agencies": [{"id": "me", "name": "自分", "channels": []}]})
        with patch("builtins.open", side_effect=PermissionError(13, "locked")):
            with self.assertRaises(ApiError) as cm:
                rank.load_registry()
        self.assertEqual(cm.exception.status, 500)
        self.assertEqual(rank.load_registry()["agencies"][0]["name"], "自分")   # ファイルは退避も上書きもされていない

    def test_bom_is_accepted(self):
        with open(self.reg_path(), "wb") as f:
            f.write(b"\xef\xbb\xbf" + json.dumps({"agencies": [{"id": "x", "name": "BOM"}]}).encode())
        self.assertEqual(rank.get_registry()["agencies"][0]["name"], "BOM")

    def test_odd_shapes_do_not_crash(self):
        for obj in ({"agencies": {"a": 1}}, {"agencies": "abc"}, {"agencies": [{"name": "A", "channels": {"x": 1}, "official": "UCxxx"}]}, [], "x"):
            reg = rank.sanitize_registry(obj)
            self.assertIsInstance(reg["agencies"], list)


class TestCaches(Home):
    def test_bad_meta_cache_is_ignored(self):
        os.makedirs(analyze.meta_dir())
        for bad in ({"title": "t", "tags": 5, "fetchedAt": time.time()}, {"title": 1, "fetchedAt": time.time()},
                    {"tags": ["a", 3], "fetchedAt": time.time()}, {"heatmap": "x", "fetchedAt": time.time()}, [1]):
            with open(os.path.join(analyze.meta_dir(), "abcdefghijk.json"), "w", encoding="utf-8") as f:
                json.dump(bad, f)
            self.assertIsNone(analyze.load_meta("abcdefghijk"), bad)
        good = {"title": "【歌枠】", "tags": ["x"], "categories": ["Music"], "heatmap": [], "chapters": [], "fetchedAt": time.time()}
        with open(os.path.join(analyze.meta_dir(), "abcdefghijk.json"), "w", encoding="utf-8") as f:
            json.dump(good, f)
        self.assertEqual(analyze.classify_stream(analyze.load_meta("abcdefghijk")), "歌枠")

    def test_archive_with_broken_runs_is_still_saved(self):
        p = analyze.archive_path("abcdefghijk")
        os.makedirs(os.path.dirname(p))
        with gzip.open(p, "wt", encoding="utf-8") as f:
            json.dump({"v": 1, "runs": {"not": "a list"}}, f)
        self.assertTrue(analyze.save_archive("abcdefghijk", {"n": 1}, {"at": 1}))
        self.assertEqual(analyze.load_archive("abcdefghijk")["runs"], [{"at": 1}])

    def test_sig_cache_write_leaves_no_temp_files(self):
        analyze.save_sig("abcdefghijk", 30.0, [-30.0] * 30, [-40.0] * 30)
        self.assertEqual(os.listdir(analyze.sig_cache_dir()), ["abcdefghijk.json"])
        self.assertEqual(analyze.load_sig("abcdefghijk")["dur"], 30.0)


class TestLogs(Home):
    def test_rotated_logs_keep_log_extension(self):
        # *.log のまま回す(.gitignore の *.log に掛かる。以前の studio.log.old は掛からず公開リポジトリに載るおそれがあった)
        self.assertEqual(common.old_log_name(os.path.join("d", "studio.log")), os.path.join("d", "studio.old.log"))
        p = os.path.join(self.tmp, "studio.log")
        with open(p, "w") as f:
            f.write("x" * 100)
        common.rotate_log(p, 50)
        self.assertEqual(sorted(os.listdir(self.tmp)), ["studio.old.log"])
        common.rotate_log(p, 50)   # 無いファイルは何もしない

    def test_old_names_are_migrated(self):
        for n in ("studio.log.old", "studio-errors.log.old"):
            with open(os.path.join(self.tmp, n), "w") as f:
                f.write(n)
        common.migrate_old_logs()
        self.assertEqual(sorted(os.listdir(self.tmp)), ["studio-errors.old.log", "studio.old.log"])

    def test_error_log_rotation_name(self):
        with open(os.path.join(self.tmp, "studio-errors.log"), "w") as f:
            f.write("x" * (1024 * 1024 + 10))
        common.log_failure("テスト", ValueError("boom"))
        self.assertIn("studio-errors.old.log", os.listdir(self.tmp))
        self.assertIn("boom", "\n".join(self.lines("studio-errors.log")))

    def test_studio_log_rotation(self):
        with open(os.path.join(self.tmp, "studio.log"), "w") as f:
            f.write("x" * 100)
        with patch.object(serve, "LOG_MAX", 50):
            serve._log("起動")
        self.assertIn("studio.old.log", os.listdir(self.tmp))
        self.assertTrue(self.lines("studio.log")[0].endswith("起動"))


class TestYtdlpTemplate(unittest.TestCase):
    def test_percent_in_folder_is_escaped(self):
        self.assertEqual(common.ytdlp_out(os.path.join("C:", "100%", "exports"), "a.%(ext)s"), os.path.join("C:", "100%%", "exports", "a.%(ext)s"))
        self.assertEqual(common.ytdlp_out("/plain", "chat.%(ext)s"), os.path.join("/plain", "chat.%(ext)s"))

    def test_all_ytdlp_calls_use_the_escaped_template(self):
        here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        for fn in ("analyze.py", "exporter.py"):
            with open(os.path.join(here, fn), encoding="utf-8") as f:
                src = f.read()
            self.assertNotIn('"-o", os.path.join(', src, fn)   # yt-dlp の -o は必ず common.ytdlp_out を通す


class TestPorts(unittest.TestCase):
    def test_busy_port_is_skipped(self):
        """使用中のポートは飛ばして次を使う(Windows では SO_REUSEADDR を使わないので、使用中のポートに bind しない)。"""
        blocker = socket.socket()
        blocker.bind(("127.0.0.1", 0))
        blocker.listen(1)
        busy = blocker.getsockname()[1]
        tmp = tempfile.mkdtemp()
        try:
            serve.init(tmp)
            with patch.object(serve, "probe", return_value=None):   # 応答しない相手の1秒待ちを省く
                srv, port = serve.make_server(busy)
            try:
                self.assertNotEqual(port, busy)
                self.assertTrue(busy < port < busy + 20)
                self.assertEqual(serve.ALLOWED_HOSTS, {"localhost:%d" % port, "127.0.0.1:%d" % port})
            finally:
                srv.server_close()
        finally:
            blocker.close()
            shutil.rmtree(tmp, ignore_errors=True)

    def test_windows_does_not_use_reuseaddr(self):
        self.assertEqual(serve.StudioServer.allow_reuse_address, os.name != "nt")
        self.assertTrue(serve.StudioServer.daemon_threads)

    def test_ephemeral_port(self):
        tmp = tempfile.mkdtemp()
        try:
            serve.init(tmp)
            srv, port = serve.make_server(0)
            srv.server_close()
            self.assertGreater(port, 0)
            self.assertEqual(serve.PORT, port)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


class TestDataHome(unittest.TestCase):
    """作業データの置き場所(段階4): STUDIO_HOME が無ければ ytt_core.datadir の場所。以前のデータはコピーし、元は残す"""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.legacy = os.path.join(self.tmp, "studio")
        os.makedirs(os.path.join(self.legacy, "cache", "meta"))
        with open(os.path.join(self.legacy, "data.json"), "w", encoding="utf-8") as f:
            f.write('{"videos": {}}')
        with open(os.path.join(self.legacy, "cache", "meta", "x.json"), "w", encoding="utf-8") as f:
            f.write("{}")
        self.env = patch.dict(os.environ, {"YTT_DATA_DIR": os.path.join(self.tmp, "data")})
        self.env.start()
        os.environ.pop("STUDIO_HOME", None)
        self.code = patch.object(serve, "CODE_DIR", self.legacy)
        self.code.start()

    def tearDown(self):
        self.code.stop()
        self.env.stop()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_copies_legacy_data(self):
        home = serve._data_home()
        self.assertEqual(home, os.path.join(self.tmp, "data", "studio"))
        self.assertTrue(os.path.isfile(os.path.join(home, "cache", "meta", "x.json")))
        self.assertTrue(os.path.isfile(os.path.join(self.legacy, "data.json")))        # 元は消さない
        self.assertEqual(serve.DATA_STATE["state"], "migrated")

    def test_legacy_exports_stay_the_output_folder(self):
        os.makedirs(os.path.join(self.legacy, "exports"))
        home = serve._data_home()
        common.set_home(home)
        common.load_out_dir()
        self.assertEqual(common.get_out_dir(), os.path.join(self.legacy, "exports"))

    def test_studio_home_wins(self):
        with patch.dict(os.environ, {"STUDIO_HOME": os.path.join(self.tmp, "h")}):
            self.assertEqual(serve._data_home(), os.path.join(self.tmp, "h"))
        self.assertFalse(os.path.exists(os.path.join(self.tmp, "data")))


# 子プロセスが「生きている」の印: 0.1 秒ごとにファイルの中身を書き換える(Windows の os.kill(pid, 0) は止めてしまうので使わない)
BEAT = "import sys, time\nwhile True:\n    open(sys.argv[1], 'w').write(str(time.time()))\n    time.sleep(0.1)\n"
# 孫を起動してから、自分も出力を出しながら長く動く(yt-dlp が ffmpeg を起動するのと同じ形)
PARENT = ("import subprocess, sys, time\nsubprocess.Popen([sys.executable, '-c', sys.argv[1], sys.argv[2]])\n"
          "while True:\n    print('tick', flush=True)\n    time.sleep(0.2)\n")


def _read(path):
    try:
        with open(path, encoding="utf-8") as f:
            return f.read()
    except OSError:
        return None


def _alive(path, wait=0.8):
    """印のファイルが wait 秒のうちに書き換わるか(= その子プロセスが動いているか)。"""
    before = _read(path)
    time.sleep(wait)
    after = _read(path)
    return after is not None and after != before


def _wait_file(path, sec=15):
    t0 = time.time()
    while time.time() - t0 < sec:
        if os.path.exists(path) and os.path.getsize(path) > 0:
            return True
        time.sleep(0.05)
    return False


class TestStopChildren(Home):
    """終了の流れで、実行中の子プロセス(ffmpeg・yt-dlp の代わりに長く動く python)を孫ごと止める(2026-09-30 の設計レビューの 1)。"""

    def tearDown(self):
        for p in common.children():
            common.hard_kill(p)
        super().tearDown()

    def test_no_children_returns_at_once(self):
        t0 = time.time()
        self.assertEqual(common.stop_children(), 0)
        self.assertLess(time.time() - t0, 0.2)   # 子が無いときの終了を遅くしない

    def test_stops_child_and_grandchild(self):
        beat = os.path.join(self.tmp, "grandchild.beat")
        proc = common.spawn([sys.executable, "-c", PARENT, BEAT, beat], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.assertIn(proc, common.children())
        self.assertTrue(_wait_file(beat), "孫が起動しなかった")
        self.assertTrue(_alive(beat))
        t0 = time.time()
        self.assertEqual(common.stop_children(2.0), 1)
        self.assertLess(time.time() - t0, 8)
        self.assertIsNotNone(proc.poll())
        self.assertEqual(common.children(), [])
        self.assertFalse(_alive(beat), "孫(yt-dlp が起動した ffmpeg に当たる)が残っている")

    def test_run_short_is_forgotten(self):
        r = common.run_short([sys.executable, "-c", "print('ok')"], timeout=30)
        self.assertEqual((r.returncode, r.stdout.strip()), (0, "ok"))
        self.assertEqual(common.children(), [])

    def test_run_short_timeout_kills(self):
        with self.assertRaises(subprocess.TimeoutExpired):
            common.run_short([sys.executable, "-c", "import time; time.sleep(60)"], timeout=0.5)
        self.assertEqual(common.children(), [])


class TestShutdownJobs(Home):
    """serve.shutdown_jobs: 解析の待ち・実行中と、書き出しのジョブを「中止」で終わらせ、子プロセスを止め、studio.log に残す。"""

    def setUp(self):
        super().setUp()
        serve.init(self.tmp)

    def tearDown(self):
        for p in common.children():
            common.hard_kill(p)
        for j in list(exporter._jobs.values()):
            j["cancel"] = True
        super().tearDown()

    def _log(self):
        p = os.path.join(self.tmp, "studio.log")
        if not os.path.exists(p):
            return ""
        with open(p, encoding="utf-8") as f:
            return f.read()

    def test_nothing_running_is_quick(self):
        t0 = time.time()
        self.assertEqual(serve.shutdown_jobs(), 0)
        self.assertLess(time.time() - t0, 0.3)
        self.assertNotIn("終了のため中断", self._log())

    def test_running_export_is_interrupted_and_child_killed(self):
        beat = os.path.join(self.tmp, "export.beat")
        src = os.path.join(self.tmp, "src.mp4")
        open(src, "wb").close()

        def fake_runner(job, spec, it, base):   # 書き出しの ffmpeg の代わりに、出力を出しながら長く動く子(孫つき)
            exporter._pump(job, [sys.executable, "-c", PARENT, BEAT, beat], it, 60)
            return spec["folder"] + "/" + base + ".mp4"
        clips = [{"id": "m1", "start": 0.0, "end": 60.0, "title": "a", "label": "", "src": "manual", "markStatus": ""},
                 {"id": "m2", "start": 60.0, "end": 90.0, "title": "b", "label": "", "src": "manual", "markStatus": ""}]
        spec = {"videoId": "fabcdefghij", "title": "t", "clips": clips, "fast": False, "maxHeight": 0, "volume": 100, "loudness": None,
                "kind": "file", "sourceTitle": "t", "sourceFile": src, "sourceDuration": 100, "combine": False, "mode": "file", "sourcePath": src}
        with patch.object(exporter, "run_ffmpeg", fake_runner):
            job = exporter.start_job(spec)
            self.assertTrue(_wait_file(beat), "書き出しの子が起動しなかった")
            self.assertTrue(exporter.is_busy())
            t0 = time.time()
            self.assertGreaterEqual(serve.shutdown_jobs(), 1)
            self.assertLess(time.time() - t0, 8)
        self.assertEqual(job["state"], "cancelled")
        self.assertTrue(job.get("interrupted"))
        self.assertEqual([i["status"] for i in job["items"]], ["cancelled", "cancelled"])   # 2本目は始めない
        self.assertFalse(exporter.is_busy())
        self.assertEqual(common.children(), [])
        self.assertFalse(_alive(beat))
        self.assertIn("終了のため中断しました: 解析 0 本", self._log())

    def test_queue_waiting_and_running_are_cancelled(self):
        b = serve.BATCH
        src = {"kind": "youtube", "videoId": "abcdefghijk", "name": "abcdefghijk"}
        wait_it = b._new_item(src, {}, "待ちの配信", "")
        run_it = b._new_item(dict(src, videoId="bbcdefghijk"), {}, "解析中の配信", "")
        run_it["status"], run_it["job"] = "running", analyze.new_job({})
        b.items += [run_it, wait_it]
        self.assertEqual(sorted(b.shutdown()), sorted(["待ちの配信", "解析中の配信"]))
        self.assertEqual((wait_it["status"], wait_it["error"]), ("cancelled", "終了のため中断しました"))
        self.assertTrue(run_it["job"]["cancel"])
        run_it["job"]["state"] = "cancelled"   # 解析のスレッドが中止を見て終わった
        b._complete(run_it, run_it["job"])
        self.assertEqual((run_it["status"], run_it["error"], run_it["phase"]), ("cancelled", "終了のため中断しました", "中断しました(終了)"))
        self.assertFalse(b.is_busy())
        with self.assertRaises(ApiError) as cm:   # 終了の流れのあとは新しく入れない
            b.add([{"kind": "youtube", "videoId": "cbcdefghijk"}], {})
        self.assertEqual(cm.exception.code, "closing")

    def test_finish_stops_jobs_before_runtime(self):
        calls = []
        with patch.object(serve, "shutdown_jobs", lambda: calls.append("jobs")), \
                patch.object(serve.handoff, "remove_runtime", lambda *a: calls.append("runtime")):
            serve.finish()
        self.assertEqual(calls, ["jobs", "runtime"])   # 入口の Mount.stop() → finish() で止まる


class TestExportJobSettles(Home):
    """書き出しのジョブが想定外の例外で「実行中」のまま残らない(設計レビューの 2)。"""

    def test_unexpected_error_does_not_leave_running(self):
        spec = {"videoId": "fabcdefghij", "clips": [{"id": "m1", "start": 0.0, "end": 1.0, "title": "a", "label": ""}]}
        job = {"id": "x", "videoId": spec["videoId"], "state": "running", "cancel": False, "proc": None, "created": time.time(),
               "items": [dict(c, status="queued", progress=0.0, file=None, error=None) for c in spec["clips"]]}
        with patch.object(exporter, "_run_job", side_effect=ValueError("boom")):
            with self.assertRaises(ValueError):
                exporter.run_job(job, spec)
        self.assertEqual(job["state"], "error")
        self.assertEqual(job["items"][0]["status"], "error")
        self.assertIn("studio-errors.log", job["items"][0]["error"])


if __name__ == "__main__":
    unittest.main(verbosity=1)
