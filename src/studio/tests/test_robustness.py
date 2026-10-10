"""データを失わない・壊れたファイルで止まらない、のテスト(feedback.jsonl・registry.json・キャッシュ・ログ・ポートの確保)。
ネットワーク・ffmpeg は使わない(ポートは 127.0.0.1 の空きポートだけ)。 実行: python3 test_robustness.py"""
import gzip
import json
import os
os.environ.setdefault("YTT_DATA_DIR", "inplace")   # テストは作業データを本物の置き場所(AppData など)に書かない(ytt.datadir)
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
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))   # src(解析などは ytt・pipeline を読む。RS3-4 から common を読まない)
import common
from human.find import rank
from human.review import feedback
from pipeline.analyze import analyze
from pipeline.export import exporter
import serve
from ytt import fsio  # noqa: E402  置き換え(スタジオの common.replace_file は RS3-4 で ytt.fsio.replace_retry を直に使う形にした)
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
            self.assertTrue(feedback.feedback_for_mark(VIDEO, {"start": i, "end": i + 1, "src": "manual"}, "good", "adopt"))

    def test_rotation_never_drops_rows(self):
        with patch.object(feedback, "MAX_FEEDBACK_BYTES", 1000):
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
        with patch.object(feedback, "MAX_FEEDBACK_BYTES", 10):
            self.write(3)
        old = self.lines("feedback.jsonl.old")
        self.assertEqual(json.loads(old[0])["start"], -1)
        self.assertTrue(all(json.loads(l) for l in old))

    def test_default_limit_is_large(self):
        self.assertGreaterEqual(feedback.MAX_FEEDBACK_BYTES, 32 * 1024 * 1024)


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
        self.assertEqual(analyze.load_meta("abcdefghijk")["title"], "【歌枠】")

    def test_archive_with_broken_runs_is_still_saved(self):
        p = analyze.archive_path("abcdefghijk")
        os.makedirs(os.path.dirname(p))
        with gzip.open(p, "wt", encoding="utf-8") as f:
            json.dump({"v": 1, "runs": {"not": "a list"}}, f)
        self.assertTrue(analyze.save_archive("abcdefghijk", {"n": 1}, {"at": 1}))
        self.assertEqual(analyze.load_archive("abcdefghijk")["runs"], [{"at": 1}])

    def test_prefetch_refuses_non_ascii_video_id(self):
        """先読みの動画 ID の検査は common.VID_RE と同じ(ASCII だけ)。以前は [\\w-]{11} で全角の英字なども通っていた"""
        with patch.object(common, "fake", return_value=False), patch.object(common, "find_tool", return_value="yt-dlp"), \
                patch.object(analyze, "download_chat", return_value=(None, "テスト")) as dl:
            for vid in ("ａｂｃｄｅｆｇｈｉｊｋ", "あいうえおかきくけこさ", "abcdefghijé", "abcdefghijk\n", None, ""):
                self.assertEqual(analyze.prefetch_chat(vid, 60), "skip", repr(vid))
            dl.assert_not_called()
            self.assertEqual(analyze.prefetch_chat("abcdefghijk", 60), "started")   # 正しい ID は先読みする
            for _ in range(100):
                if not analyze.PREFETCH:
                    break
                time.sleep(0.05)
            self.assertEqual(analyze.PREFETCH, {})
            dl.assert_called_once()

    def test_sig_cache_write_leaves_no_temp_files(self):
        analyze.save_sig("abcdefghijk", 30.0, [-30.0] * 30, [-40.0] * 30)
        self.assertEqual(os.listdir(analyze.sig_cache_dir()), ["abcdefghijk.json"])
        self.assertEqual(analyze.load_sig("abcdefghijk")["dur"], 30.0)


class TestChatCacheSize(Home):
    """チャットのキャッシュは件数だけでなく合計の大きさでも古いものから消す(設計レビュー studio の 7。実機で 30 件・2.0GB だった)。"""

    def make(self, vid, size, age):
        d = analyze.chat_cache_dir()
        os.makedirs(d, exist_ok=True)
        p = os.path.join(d, vid + ".live_chat.json")
        with open(p, "wb") as f:
            f.write(b"x" * size)
        t = time.time() - age
        os.utime(p, (t, t))
        return p

    def left(self):
        d = analyze.chat_cache_dir()
        return sorted(n.split(".", 1)[0] for n in os.listdir(d)) if os.path.isdir(d) else []

    def test_total_size_limit_removes_oldest_first(self):
        for i, age in enumerate((500, 400, 300, 200, 100)):
            self.make("v%010d" % i, 1000, age)
        freed = analyze.prune_chat_cache(limit=2500)
        self.assertEqual(freed, 3000)
        self.assertEqual(self.left(), ["v0000000003", "v0000000004"])   # 新しい2つ(合計 2000 ≤ 2500)

    def test_count_limit_still_applies(self):
        for i in range(5):
            self.make("c%010d" % i, 10, 100 - i)
        analyze.prune_chat_cache(limit=10 ** 9, keep=3)
        self.assertEqual(self.left(), ["c0000000002", "c0000000003", "c0000000004"])

    def test_in_use_and_prefetch_and_newest_are_kept(self):
        self.make("aaaaaaaaaaa", 1000, 500)   # 解析が使っている最中
        self.make("bbbbbbbbbbb", 1000, 400)   # 先読みが取得中
        self.make("ccccccccccc", 1000, 300)
        self.make("ddddddddddd", 5000, 100)   # いちばん新しい(1つで上限を超えていても残す)
        with open(os.path.join(analyze.chat_cache_dir(), "eeeeeeeeeee.live_chat.json.tmp"), "wb") as f:
            f.write(b"t" * 10)   # 途中で止まった写し
        analyze.use_chat_cache("aaaaaaaaaaa", +1)
        with analyze._pf_lock:
            analyze.PREFETCH["bbbbbbbbbbb"] = {"job": {}, "done": None, "why": "", "path": None}
        try:
            analyze.prune_chat_cache(limit=100)
        finally:
            analyze.use_chat_cache("aaaaaaaaaaa", -1)
            with analyze._pf_lock:
                analyze.PREFETCH.pop("bbbbbbbbbbb", None)
        self.assertEqual(self.left(), ["aaaaaaaaaaa", "bbbbbbbbbbb", "ddddddddddd"])
        self.assertEqual(analyze._chat_in_use, {})
        analyze.prune_chat_cache(limit=100)   # 使い終わったら次の機会に消える
        self.assertEqual(self.left(), ["ddddddddddd"])

    def test_limit_from_env(self):
        with patch.dict(os.environ, {"STUDIO_CHAT_CACHE_MB": "300"}):
            self.assertEqual(analyze.chat_cache_limit(), 300 * 1024 * 1024)
        for bad in ("", "0", "-5", "abc"):
            with patch.dict(os.environ, {"STUDIO_CHAT_CACHE_MB": bad}):
                self.assertEqual(analyze.chat_cache_limit(), 1024 ** 3)

    def test_startup_cleanup_prunes(self):
        for i in range(3):
            self.make("s%010d" % i, 1000, 100 - i)
        with patch.object(analyze, "chat_cache_limit", return_value=1500):
            serve._clean_leftovers()
        self.assertEqual(self.left(), ["s0000000002"])


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
        for fn in (os.path.join("..", "pipeline", "analyze", "analyze.py"), os.path.join("..", "pipeline", "export", "exporter.py")):   # analyze は RS3-5 で pipeline/analyze へ・exporter は RS1-4 で pipeline/export へ
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
    """作業データの置き場所(段階4): STUDIO_HOME が無ければ ytt.datadir の場所。以前のデータはコピーし、元は残す"""

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
        serve.datadir.register(serve.TOOL_ID, None)   # _data_home が登録した一時フォルダを、同じプロセスの後のテストに残さない
        self.code.stop()
        self.env.stop()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_copies_legacy_data(self):
        home = serve._data_home()
        self.assertEqual(home, os.path.join(self.tmp, "data", "studio"))
        self.assertTrue(os.path.isfile(os.path.join(home, "cache", "meta", "x.json")))
        self.assertTrue(os.path.isfile(os.path.join(self.legacy, "data.json")))        # 元は消さない
        self.assertEqual(serve.DATA_STATE["state"], "migrated")
        self.assertEqual(serve.datadir.registered(serve.TOOL_ID), home)

    def test_legacy_exports_stay_the_output_folder(self):
        os.makedirs(os.path.join(self.legacy, "exports"))
        home = serve._data_home()
        common.set_home(home)
        common.load_out_dir()
        self.assertEqual(common.get_out_dir(), os.path.join(self.legacy, "exports"))

    def test_studio_home_wins(self):
        with patch.dict(os.environ, {"STUDIO_HOME": os.path.join(self.tmp, "h")}):
            self.assertEqual(serve._data_home(), os.path.join(self.tmp, "h"))
            self.assertEqual(serve.datadir.registered(serve.TOOL_ID), os.path.join(self.tmp, "h"))   # 決めた場所を登録する(入口の中の他のツールが読む)
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


FAKE_INFO = "  Duration: 00:00:05.00, start: 0\n  Stream #0:0: Video: h264, 64x64\n  Stream #0:1: Audio: aac\n"


class TestMediaInfoCache(Home):
    """common.media_info は (パス・更新日時・大きさ) が同じあいだ ffmpeg -i を動かし直さない(2026-10-09 見直し T7。書き出し 1 本で 11 回 → 5 回)"""

    def setUp(self):
        super().setUp()
        common._media_cache.clear()
        self.calls = []

        def fake_run(cmd, timeout, merge_stderr=False):
            self.calls.append(cmd[-1])
            if self.fail:
                raise subprocess.TimeoutExpired(cmd, timeout)
            return subprocess.CompletedProcess(cmd, 0, FAKE_INFO, "")
        self.fail = False
        self.patches = [patch.object(common, "find_tool", return_value="ffmpeg-fake"), patch.object(common, "run_short", side_effect=fake_run)]
        for p in self.patches:
            p.start()
        self.path = os.path.join(self.tmp, "a.mp4")
        with open(self.path, "wb") as f:
            f.write(b"x" * 10)

    def tearDown(self):
        for p in self.patches:
            p.stop()
        common._media_cache.clear()
        super().tearDown()

    def test_same_file_is_probed_once(self):
        want = (5.0, True, True, "Stream #0:0: Video: h264, 64x64")
        self.assertEqual(common.media_info(self.path), want)
        self.assertEqual(common.media_info(self.path), want)
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(common.media_info_known(self.path), want)

    def test_changed_file_is_probed_again(self):
        common.media_info(self.path)
        with open(self.path, "wb") as f:
            f.write(b"y" * 20)   # 大きさが変わった = 書き直された
        common.media_info(self.path)
        self.assertEqual(len(self.calls), 2)

    def test_missing_file_and_failures_are_not_remembered(self):
        self.assertEqual(common.media_info(os.path.join(self.tmp, "none.mp4")), (None, False, False, ""))
        self.assertEqual(self.calls, [])   # 無いファイルには ffmpeg を動かさない
        self.fail = True
        self.assertEqual(common.media_info(self.path), (None, False, False, ""))
        self.fail = False
        self.assertEqual(common.media_info(self.path)[0], 5.0)   # 時間切れは覚えない(次は測り直す)
        self.assertEqual(len(self.calls), 2)

    def test_renamed_file_keeps_the_result(self):
        """書き出しの置き換え(一時の名前 → 本当の名前)では、移す前の結果を覚えさせる(exporter.promote・_reencode_audio)"""
        info = common.media_info(self.path)
        dst = os.path.join(self.tmp, "b.mp4")
        known = common.media_info_known(self.path)
        fsio.replace_retry(self.path, dst)
        common.remember_media_info(dst, known)
        self.assertEqual(common.media_info(dst), info)
        self.assertEqual(len(self.calls), 1)
        self.assertIsNone(common.media_info_known(os.path.join(self.tmp, "c.mp4")))
        common.remember_media_info(dst, None)   # None なら何もしない

    def test_other_ffmpeg_forgets(self):
        common.media_info(self.path)
        with patch.object(common, "find_tool", return_value="ffmpeg-other"):
            common.media_info(self.path)
        self.assertEqual(len(self.calls), 2)


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
