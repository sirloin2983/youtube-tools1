# -*- coding: utf-8 -*-
"""ytt のテスト。  python -m unittest src/ytt/tests/test_ytt_core.py -v
ネットワークは 127.0.0.1 の空きポートだけを使う。"""
import ast
import http.server
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest import mock

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))   # ytt/tests の2つ上 = src(ツールの親)
TOP = os.path.dirname(REPO)   # リポジトリ直下(dev/・friend-apps/・setup/)
sys.path.insert(0, REPO)
from manage.cases import txindex  # noqa: E402
from ytt import colors, datadir, errors, fsio, httpsec, jobs, layout, pick, procs, runtime, schemas, studio_env, tools  # noqa: E402


def locked(winerror=32):
    e = PermissionError(13, "in use", "x")
    e.winerror = winerror
    return e


class PingServer:
    """/api/ping に app で答える小さなサーバー(hang=True なら答えるまで2秒待つ)。"""

    def __init__(self, app, hang=False, status=200, body=None, routes=None):
        """routes: {"/studio/api/ping": "clip-studio", ...} を渡すと、その場所だけ答える(統合サーバーの模擬)"""
        class H(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                if hang:
                    time.sleep(2)
                if routes is not None:
                    who = routes.get(self.path)
                    data = json.dumps({"app": who, "version": "9"}).encode() if who else b"{}"
                    self.send_response(200 if who else 404)
                    self.send_header("Content-Length", str(len(data)))
                    self.end_headers()
                    self.wfile.write(data)
                    return
                data = body if body is not None else json.dumps({"app": app, "version": "1.2.3"}).encode()
                try:
                    self.send_response(status)
                    self.send_header("Content-Length", str(len(data)))
                    self.end_headers()
                    self.wfile.write(data)
                except OSError:
                    pass

            def log_message(self, *a):
                pass
        self.srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.srv.daemon_threads = True
        self.port = self.srv.server_address[1]
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()

    def close(self):
        self.srv.shutdown()
        self.srv.server_close()


def dead_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class TestFsio(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_atomic_write_and_no_temp_left(self):
        p = os.path.join(self.tmp, "sub", "a.json")
        fsio.atomic_write(p, b"one")
        fsio.atomic_write(p, b"two")
        with open(p, "rb") as f:
            self.assertEqual(f.read(), b"two")
        self.assertEqual(os.listdir(os.path.dirname(p)), ["a.json"])

    def test_windows_lock_is_retried_then_succeeds(self):
        p = os.path.join(self.tmp, "a.json")
        real, calls = os.replace, []

        def flaky(src, dst):
            calls.append(dst)
            if len(calls) < 3:
                raise locked()
            real(src, dst)
        with mock.patch.object(fsio.os, "replace", side_effect=flaky), mock.patch.object(fsio.time, "sleep") as sl:
            fsio.atomic_write(p, b"x")
        self.assertEqual(len(calls), 3)
        self.assertEqual([c.args[0] for c in sl.call_args_list], [0.1, 0.2])

    def test_permanent_lock_keeps_original(self):
        p = os.path.join(self.tmp, "a.json")
        fsio.atomic_write(p, b"original")
        with mock.patch.object(fsio.os, "replace", side_effect=locked(5)) as rep, mock.patch.object(fsio.time, "sleep"):
            with self.assertRaises(PermissionError):
                fsio.atomic_write(p, b"changed")
        self.assertEqual(rep.call_count, fsio.REPLACE_ATTEMPTS)
        with open(p, "rb") as f:
            self.assertEqual(f.read(), b"original")
        self.assertEqual(os.listdir(self.tmp), ["a.json"])

    def test_other_permission_errors_are_not_retried(self):
        for err in (PermissionError(), locked(1314)):
            with mock.patch.object(fsio.os, "replace", side_effect=err) as rep:
                with self.assertRaises(PermissionError):
                    fsio.replace_retry("a", "b")
            self.assertEqual(rep.call_count, 1)

    def test_fsync_required(self):
        p = os.path.join(self.tmp, "a.json")
        with mock.patch.object(fsio.os, "fsync", side_effect=OSError("no fsync")):
            fsio.atomic_write(p, b"ok")   # 既定は続ける
            with self.assertRaises(OSError):
                fsio.atomic_write(p, b"strict", fsync_required=True)
        with open(p, "rb") as f:
            self.assertEqual(f.read(), b"ok")
        self.assertEqual(os.listdir(self.tmp), ["a.json"])

    def test_cleanup_failure_does_not_hide_error(self):
        original = PermissionError("replace failed")
        with mock.patch.object(fsio.os, "replace", side_effect=original), mock.patch.object(fsio.os, "unlink", side_effect=OSError("x")):
            with self.assertRaises(PermissionError) as cm:
                fsio.atomic_write(os.path.join(self.tmp, "a.json"), b"d")
        self.assertIs(cm.exception, original)

    def test_create_new_never_overwrites(self):
        p = os.path.join(self.tmp, "a.srt")
        self.assertTrue(fsio.create_new(p, b"first"))
        self.assertFalse(fsio.create_new(p, b"second"))
        with open(p, "rb") as f:
            self.assertEqual(f.read(), b"first")
        with mock.patch.object(fsio.os, "link", side_effect=OSError("no hardlink")):   # exFAT など
            q = os.path.join(self.tmp, "b.srt")
            self.assertTrue(fsio.create_new(q, b"1"))
            self.assertFalse(fsio.create_new(q, b"2"))
        self.assertEqual(sorted(os.listdir(self.tmp)), ["a.srt", "b.srt"])

    def test_move_file_across_drives(self):
        """move_file(RS3-1 に editor/ed_relink の _move から): 名前の変更が効かない別のドライブはコピー → 元を消す。元を消せなければ元のまま"""
        a, b = os.path.join(self.tmp, "a.bin"), os.path.join(self.tmp, "sub", "b.bin")
        os.makedirs(os.path.dirname(b))
        with open(a, "wb") as f:
            f.write(b"video")
        self.assertTrue(fsio.same_drive(a, b))
        real = os.rename

        def no_rename_across(x, y):   # 別のドライブのふり: .part → 本名 の同じフォルダの中だけ通す
            if os.path.dirname(x) != os.path.dirname(y):
                raise OSError(17, "別のドライブ")
            return real(x, y)
        logged = []
        log = type("L", (), {"info": lambda self, *a: logged.append(a)})()
        with mock.patch.object(fsio, "same_drive", lambda x, y: False), mock.patch.object(fsio.os, "rename", no_rename_across):
            fsio.move_file(a, b, log=log)
        self.assertFalse(os.path.exists(a))
        with open(b, "rb") as f:
            self.assertEqual(f.read(), b"video")
        self.assertEqual(len(logged), 1)
        real_remove = os.remove
        with mock.patch.object(fsio, "same_drive", lambda x, y: False), mock.patch.object(fsio.os, "rename", no_rename_across), \
                mock.patch.object(fsio.os, "remove", lambda x: (_ for _ in ()).throw(PermissionError(13, "使用中")) if x == b else real_remove(x)):
            with self.assertRaises(OSError):
                fsio.move_file(b, a)
        self.assertTrue(os.path.isfile(b))
        self.assertEqual(sorted(os.listdir(self.tmp)), ["sub"])   # .part も残さない(a は消した = コピーを消して元のまま)
        self.assertFalse(fsio.is_remote_drive(self.tmp))

    def test_read_json_file_limits(self):
        p = os.path.join(self.tmp, "a.json")
        with open(p, "wb") as f:
            f.write(b'\xef\xbb\xbf{"a": 1}')
        self.assertEqual(fsio.read_json_file(p, 100), {"a": 1})
        with open(p, "wb") as f:
            f.write(b'{"a": NaN}')
        with self.assertRaises(ValueError):
            fsio.read_json_file(p, 100)
        with open(p, "wb") as f:
            f.write(b"[" + b"1," * 100 + b"1]")
        with self.assertRaises(ValueError):
            fsio.read_json_file(p, 50)

    def test_write_json_is_utf8_without_bom(self):
        p = os.path.join(self.tmp, "a.json")
        fsio.write_json(p, {"名前": "動画"})
        with open(p, "rb") as f:
            raw = f.read()
        self.assertFalse(raw.startswith(b"\xef\xbb\xbf"))
        self.assertIn("動画".encode("utf-8"), raw)

    def test_is_network_path(self):
        for p in ("\\\\host\\share\\x.mp4", "//host/x.mp4", "\\\\?\\UNC\\host\\x"):
            self.assertTrue(fsio.is_network_path(p), p)
        for p in ("C:\\x.mp4", "/home/x.mp4", "Z:/x.mp4", "", None):
            self.assertFalse(fsio.is_network_path(p), p)

    def test_write_json_options_and_append_jsonl(self):
        """詰めて書く・NaN を断る(元のファイルは壊さない)・fsync_required・1 行 1 JSON の追記・大きすぎる読みは TooLarge"""
        p = os.path.join(self.tmp, "w.json")
        fsio.write_json(p, {"a": [1, 2]}, indent=None, separators=(",", ":"), fsync_required=True)
        with open(p, "rb") as f:
            self.assertEqual(f.read(), b'{"a":[1,2]}')
        with self.assertRaises(ValueError):
            fsio.write_json(p, {"a": float("nan")}, indent=None, allow_nan=False)
        with open(p, "rb") as f:
            self.assertEqual(f.read(), b'{"a":[1,2]}')
        fsio.write_json(p, {"a": 1})
        with open(p, "rb") as f:
            self.assertEqual(f.read(), b'{\n  "a": 1\n}\n')
        j = os.path.join(self.tmp, "s.jsonl")
        fsio.append_jsonl(j, [{"t": 1}])
        fsio.append_jsonl(j, [{"t": 2}, {"t": 3}])
        with open(j, encoding="utf-8") as f:
            self.assertEqual(f.read(), '{"t":1}\n{"t":2}\n{"t":3}\n')
        with self.assertRaises(fsio.TooLarge):
            fsio.read_json_file(p, 3)

    def test_unlink_quiet(self):
        p = os.path.join(self.tmp, "a.txt")
        with open(p, "w") as f:
            f.write("x")
        fsio.unlink_quiet(p)
        self.assertFalse(os.path.exists(p))
        fsio.unlink_quiet(p)   # 無くても上げない

    def write(self, name, data):
        p = os.path.join(self.tmp, name)
        with open(p, "wb") as f:
            f.write(data if isinstance(data, bytes) else data.encode("utf-8"))
        return p

    def test_read_json_or(self):
        """読めなければ既定値(上げない)。BOM は可・NaN・大きすぎ・形の違いは既定値"""
        ok = self.write("ok.json", '\ufeff{"a": 1}')
        self.assertEqual(fsio.read_json_or(ok), {"a": 1})
        self.assertEqual(fsio.read_json_or(ok, kind=dict), {"a": 1})
        self.assertEqual(fsio.read_json_or(ok, "既定", kind=list), "既定")
        self.assertEqual(fsio.read_json_or(ok, kind=(list, dict)), {"a": 1})
        lst = self.write("l.json", "[1, 2]")
        self.assertEqual(fsio.read_json_or(lst, {}, kind=dict), {})
        default = {"x": 1}
        for p in (os.path.join(self.tmp, "無い.json"), self.write("broken.json", "{壊れ"), self.write("nan.json", '{"a": NaN}'),
                  self.write("sjis.json", '{"a": "あ"}'.encode("cp932")), self.write("deep.json", "[" * 100000 + "]" * 100000), self.tmp):
            self.assertIs(fsio.read_json_or(p, default), default, p)
        self.assertIsNone(fsio.read_json_or(ok, max_bytes=3))      # 上限を超える
        self.assertEqual(fsio.read_json_or(ok, max_bytes=100), {"a": 1})

    def test_stamp_and_cache(self):
        p = self.write("a.json", "1")
        st = fsio.stamp(p)
        self.assertEqual(st, (os.stat(p).st_mtime_ns, 1))
        self.assertIsNone(fsio.stamp(os.path.join(self.tmp, "無い")))
        self.assertIsNone(fsio.stamp("a\0b"))
        cache, calls = fsio.StampCache(), []

        def load(path):
            calls.append(path)
            return fsio.read_json_or(path)
        self.assertEqual(cache.get(p, load), 1)
        self.assertEqual(cache.get(p, load), 1)
        self.assertEqual(len(calls), 1)                           # 変わっていなければ読み直さない
        self.write("a.json", "22")
        os.utime(p, ns=(time.time_ns(), time.time_ns() + 10 ** 9))
        self.assertEqual(cache.get(p, load), 22)
        self.assertEqual(len(calls), 2)                           # 変わったら読み直す
        bad = self.write("b.json", "{壊れ")
        self.assertIsNone(cache.get(bad, load))
        self.assertIsNone(cache.get(bad, load))
        self.assertEqual(len(calls), 3)                           # 読めなかった結果(None)も覚える
        self.assertIsNone(cache.get(os.path.join(self.tmp, "無い"), load))
        self.assertEqual(len(calls), 3)                           # 無いファイルは load を呼ばない
        self.assertEqual((len(cache), p in cache, sorted(cache)), (2, True, sorted([p, bad])))
        other = os.path.join(self.tmp, "sub", "c.json")
        os.makedirs(os.path.dirname(other))
        self.write(os.path.join("sub", "c.json"), "3")
        cache.get(other, load)
        cache.prune([p], folder=self.tmp)                         # そのフォルダの直下で keep に無いものだけ外す
        self.assertEqual(sorted(cache), sorted([p, other]))
        cache.prune([])
        self.assertEqual(len(cache), 0)
        cache.get(p, load)
        cache.clear()
        self.assertNotIn(p, cache)
        with self.assertRaises(ZeroDivisionError):                # load の例外はそのまま(覚えない)
            cache.get(p, lambda path: 1 / 0)
        self.assertNotIn(p, cache)

    def test_cache_peek_and_set(self):
        """peek は読み直さずに覚えた値だけ(変わった・無いなら None)。set は今の stamp で上書きする(無いファイルは覚えない)"""
        p = self.write("a.json", "1")
        cache = fsio.StampCache()
        self.assertIsNone(cache.peek(p))                          # まだ覚えていない
        self.assertTrue(cache.set(p, "覚えた"))
        self.assertEqual(cache.peek(p), "覚えた")
        self.assertEqual(cache.get(p, lambda path: self.fail("読み直さない")), "覚えた")
        self.assertTrue(cache.set(p, "上書き"))
        self.assertEqual(cache.peek(p), "上書き")
        self.write("a.json", "22")
        os.utime(p, ns=(time.time_ns(), time.time_ns() + 10 ** 9))
        self.assertIsNone(cache.peek(p))                          # 変わったら覚えた値を返さない
        missing = os.path.join(self.tmp, "無い")
        self.assertFalse(cache.set(missing, 1))
        self.assertIsNone(cache.peek(missing))
        self.assertNotIn(missing, cache)

    def test_read_json_nan_option(self):
        """allow_nan=True なら NaN / Infinity を float として通す(既定は ValueError / 既定値)"""
        import math
        p = self.write("nan.json", '{"a": NaN, "b": Infinity}')
        self.assertIsNone(fsio.read_json_or(p))
        d = fsio.read_json_or(p, allow_nan=True)
        self.assertTrue(math.isnan(d["a"]) and d["b"] == float("inf"))
        with self.assertRaises(ValueError):
            fsio.read_json_file(p, 100)
        self.assertTrue(math.isnan(fsio.read_json_file(p, 100, allow_nan=True)["a"]))
        self.assertEqual(fsio.read_json_or(p, "既定", max_bytes=5, allow_nan=True), "既定")   # 上限は同じ

    def test_write_json_mode(self):
        p = os.path.join(self.tmp, "key.json")
        with mock.patch.object(fsio, "atomic_write") as aw:
            fsio.write_json(p, {"a": 1}, mode=0o600)
            fsio.write_json(p, {"a": 1})
        self.assertEqual([c.kwargs.get("mode") for c in aw.call_args_list], [0o600, None])
        fsio.write_json(p, {"a": 1}, indent=None, mode=0o600)
        with open(p, "rb") as f:
            self.assertEqual(f.read(), b'{"a": 1}')
        if os.name != "nt":
            self.assertEqual(os.stat(p).st_mode & 0o777, 0o600)

    def test_rotate(self):
        log = self.write("serve.log", "x" * 10)
        self.assertFalse(fsio.rotate(log, 10))                    # 上限ちょうどは回さない
        self.assertTrue(fsio.rotate(log, 9))
        self.assertEqual(sorted(os.listdir(self.tmp)), ["serve.old.log"])
        self.write("serve.log", "y" * 10)
        self.assertTrue(fsio.rotate(log, 1))                      # 前の世代は置き換わる(1 世代)
        with open(os.path.join(self.tmp, "serve.old.log")) as f:
            self.assertEqual(f.read(), "y" * 10)
        j = self.write("errors.jsonl", "z" * 10)
        self.assertTrue(fsio.rotate(j, 1, old=j + ".1"))           # 回した先を選べる(画面のエラーの記録)
        self.assertTrue(os.path.isfile(j + ".1"))
        other = self.write("x.txt", "z" * 10)
        self.assertTrue(fsio.rotate(other, 1))
        self.assertTrue(os.path.isfile(other + ".old"))           # .log でなければ <名前>.old
        self.assertFalse(fsio.rotate(os.path.join(self.tmp, "無い.log"), 1))   # 無くても上げない

    def test_append_line(self):
        """記録の 1 行の書き足し(RS3-0B で clientlog から移した): フォルダが無ければ作る・UTF-8・上限を超えていたら先に <名前>.1 へ 1 世代回す・書けなければ OSError"""
        p = os.path.join(self.tmp, "新しい", "rec.jsonl")
        fsio.append_line(p, '{"a": "あ"}\n', 100)
        fsio.append_line(p, '{"a": 2}\n', 100)
        with open(p, encoding="utf-8") as f:
            self.assertEqual(f.read(), '{"a": "あ"}\n{"a": 2}\n')
        self.assertFalse(os.path.exists(p + ".1"))
        fsio.append_line(p, '{"a": 3}\n', 5)                      # もう 5 バイトを超えている → 先に回してから新しく始める
        with open(p + ".1", encoding="utf-8") as f:
            self.assertEqual(f.read(), '{"a": "あ"}\n{"a": 2}\n')
        with open(p, encoding="utf-8") as f:
            self.assertEqual(f.read(), '{"a": 3}\n')
        os.makedirs(os.path.join(self.tmp, "dir.jsonl"))
        with self.assertRaises(OSError):                           # 書けなければ OSError(呼ぶ側が握りつぶすか決める)
            fsio.append_line(os.path.join(self.tmp, "dir.jsonl"), "x\n", 10 ** 9)

    def test_is_inside(self):
        root = os.path.join(self.tmp, "data")
        os.makedirs(os.path.join(root, "sub"))
        self.assertTrue(fsio.is_inside(os.path.join(root, "sub", "まだ無い.mp4"), root))
        self.assertTrue(fsio.is_inside(root, root))
        self.assertFalse(fsio.is_inside(root, root, strict=True))     # strict はフォルダそのものを含めない
        self.assertTrue(fsio.is_inside(os.path.join(root, "sub"), root, strict=True))
        self.assertTrue(fsio.is_inside(root.upper() if os.name == "nt" else root, root))   # Windows は大文字小文字を区別しない
        self.assertFalse(fsio.is_inside(root + "2", root))             # 文字列の頭ではなくフォルダの区切りで比べる
        self.assertFalse(fsio.is_inside(os.path.join(root, "..", "x"), root))
        self.assertFalse(fsio.is_inside(self.tmp, root))
        for bad in ("", None, "a\0b"):
            self.assertFalse(fsio.is_inside(bad, root), repr(bad))
            self.assertFalse(fsio.is_inside(root, bad), repr(bad))
        with mock.patch.object(fsio.os.path, "realpath") as rp:    # ネットワーク上のパスは調べずに False
            self.assertFalse(fsio.is_inside("\\\\server\\share\\a.mp4", root))
            self.assertFalse(fsio.is_inside(os.path.join(root, "a"), "//server/share"))
            rp.assert_not_called()
        if os.name == "nt":
            self.assertFalse(fsio.is_inside("Z:\\a\\b", "C:\\a"))        # 別のドライブ
        link = os.path.join(root, "外へ")
        try:
            os.symlink(self.tmp, link, target_is_directory=True)
        except (OSError, NotImplementedError):
            return                                                 # リンクを作れない(Windows の権限)なら飛ばす
        self.assertFalse(fsio.is_inside(os.path.join(link, "x.mp4"), root))   # リンクを解いた先で比べる

    def test_dir_size(self):
        d = os.path.join(self.tmp, "d")
        os.makedirs(os.path.join(d, "sub"))
        self.write(os.path.join("d", "a.bin"), b"12345")
        self.write(os.path.join("d", "sub", "b.bin"), b"123")
        self.assertEqual(fsio.dir_size(d), (8, 2))
        self.assertEqual(fsio.dir_size(os.path.join(d, "a.bin")), (5, 1))
        self.assertEqual(fsio.dir_size(os.path.join(self.tmp, "無い")), (0, 0))

    def test_existing_parent(self):
        """まだ無いフォルダは、ある所まで上へ(空き容量を調べる前。health.disk_free・live_export.Exporter.disk)"""
        self.assertEqual(fsio.existing_parent(self.tmp), self.tmp)
        self.assertEqual(fsio.existing_parent(os.path.join(self.tmp, "無い", "もっと")), self.tmp)
        self.assertEqual(fsio.existing_parent(""), "")
        self.assertIsNone(fsio.existing_parent(None))
        root = os.path.splitdrive(os.path.abspath(self.tmp))[0] + os.sep
        self.assertTrue(os.path.exists(fsio.existing_parent(os.path.join(root, "ytt-無いはず-" + os.urandom(4).hex(), "x"))))


class TestRuntime(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.servers = []

    def tearDown(self):
        for s in self.servers:
            s.close()
        shutil.rmtree(self.dir, ignore_errors=True)

    def server(self, app, **kw):
        s = PingServer(app, **kw)
        self.servers.append(s)
        return s

    def put(self, tool, obj, raw=None):
        with open(os.path.join(self.dir, tool + ".json"), "wb") as f:
            f.write(raw if raw is not None else json.dumps(obj).encode())

    def test_safe_stdio(self):
        """出せない文字は「?」に(reconfigure の無い入れ物でも上げない)"""
        import io
        raw = io.BytesIO()
        out = io.TextIOWrapper(raw, encoding="cp932", newline="\n")
        with mock.patch.object(sys, "stdout", out), mock.patch.object(sys, "stderr", object()):
            runtime.safe_stdio()
            print("あ\U0001F600", file=sys.stdout)
            sys.stdout.flush()
        self.assertEqual(raw.getvalue().decode("cp932"), "あ?\n")

    def test_install_stop_signals(self):
        """終了の合図の登録: この OS に無い合図は飛ばす・登録できなくても上げない・登録できた名前を返す"""
        import signal
        seen = []
        with mock.patch.object(signal, "signal", lambda sig, h: seen.append((sig, h))):
            got = runtime.install_stop_signals(print, ("SIGTERM", "SIG_NO_SUCH"))
        self.assertEqual(got, ["SIGTERM"])
        self.assertEqual(seen, [(signal.SIGTERM, print)])

        def refuse(sig, h):
            raise ValueError("signal only works in main thread")
        with mock.patch.object(signal, "signal", refuse):
            self.assertEqual(runtime.install_stop_signals(print), [])

    def test_runtime_dir(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("YTT_RUNTIME_DIR", None)
            self.assertEqual(runtime.runtime_dir("/a/b/studio"), os.path.join(os.path.abspath("/a/b"), ".runtime"))
            os.environ["YTT_RUNTIME_DIR"] = "rel"
            self.assertEqual(runtime.runtime_dir("/a/b/studio"), os.path.abspath("rel"))

    def test_write_read_remove_only_own(self):
        p = runtime.write_runtime(self.dir, "studio", 8801, "0.2.0")
        info = runtime.read_runtime(self.dir, "studio")
        self.assertEqual((info["port"], info["version"], info["pid"]), (8801, "0.2.0", os.getpid()))
        self.assertFalse(runtime.remove_runtime(self.dir, "studio", 8802))   # 別のポート
        self.put("studio", {"tool": "studio", "port": 8801, "pid": os.getpid() + 1})
        self.assertFalse(runtime.remove_runtime(self.dir, "studio", 8801))   # 別のプロセス
        runtime.write_runtime(self.dir, "studio", 8801, "0.2.0")
        self.assertTrue(runtime.remove_runtime(self.dir, "studio", 8801))
        self.assertFalse(os.path.exists(p))

    def test_ids_and_unwritable(self):
        for bad in ("../evil", "Studio", "", "a/b", None, "x" * 40):
            self.assertIsNone(runtime.write_runtime(self.dir, bad, 8800, "v"), bad)
            self.assertIsNone(runtime.read_runtime_port(self.dir, bad), bad)
        self.assertIsNotNone(runtime.write_runtime(self.dir, "portal", 8700, "v"))   # 入口も書ける
        self.assertIsNone(runtime.write_runtime(os.path.join(self.dir, "x\0y"), "studio", 8800, "v"))

    def test_read_validation(self):
        cases = [({"tool": "transcribe", "port": 8775}, 8775), ({"tool": "studio", "port": 8775}, None),
                 ({"tool": "transcribe", "port": "8775"}, None), ({"tool": "transcribe", "port": True}, None),
                 ({"tool": "transcribe", "port": 80}, None), ({"tool": "transcribe", "port": 70000}, None), ([1], None)]
        for obj, want in cases:
            self.put("transcribe", obj)
            self.assertEqual(runtime.read_runtime_port(self.dir, "transcribe"), want, obj)
        self.put("transcribe", None, b'\xef\xbb\xbf{"tool": "transcribe", "port": 1024}')
        self.assertEqual(runtime.read_runtime_port(self.dir, "transcribe"), 1024)
        self.put("transcribe", None, b'{"tool": "transcribe", "port": 8775, "x": "' + b"a" * 5000 + b'"}')
        self.assertIsNone(runtime.read_runtime_port(self.dir, "transcribe"))

    def test_tool_ids_are_fixed(self):
        """ツールの識別子(/api/ping の app・.clip.json の tool.name)は互換のため固定。各サーバーはこの表を読む(サーバー側の確かめは自分の APP_ID だけ)"""
        self.assertEqual(runtime.TOOL_APPS, {"studio": "clip-studio", "transcribe": "transcribe-tool", "cut2resolve": "cut2resolve"})

    def test_valid_port(self):
        for ok in (1024, 8800, 65535):
            self.assertTrue(runtime.valid_port(ok))
        for bad in (0, 80, 1023, 65536, True, 8.5, "8800", None, -1):
            self.assertFalse(runtime.valid_port(bad), bad)

    def test_ping(self):
        s = self.server("clip-studio")
        self.assertEqual(runtime.ping(s.port), {"app": "clip-studio", "version": "1.2.3"})
        self.assertEqual(runtime.ping_app(s.port), "clip-studio")
        self.assertIsNone(runtime.ping(dead_port()))
        self.assertIsNone(runtime.ping(self.server("x", status=500).port))
        self.assertIsNone(runtime.ping(self.server("x", body=b"not json").port))
        self.assertIsNone(runtime.ping(self.server("x", body=b'{"app": 1}').port))

    def test_ping_bad_ports_do_not_connect(self):
        with mock.patch.object(runtime.http.client, "HTTPConnection") as conn:
            for p in (0, 80, 70000, True, "8800", None):
                self.assertIsNone(runtime.ping(p))
            conn.assert_not_called()

    def test_ping_ignores_proxy_env(self):
        s = self.server("transcribe-tool")
        with mock.patch.dict(os.environ, {"http_proxy": "http://127.0.0.1:%d" % dead_port(), "HTTP_PROXY": "http://127.0.0.1:1", "no_proxy": "", "NO_PROXY": ""}):
            self.assertEqual(runtime.ping_app(s.port), "transcribe-tool")

    def test_port_open_is_silent(self):
        s = self.server("clip-studio")
        self.assertTrue(runtime.port_open(s.port))
        self.assertFalse(runtime.port_open(dead_port()))
        self.assertFalse(runtime.port_open(80))   # 範囲外のポートにはつながない

    def test_siblings(self):
        tt = self.server("transcribe-tool")
        wrong = self.server("something-else")
        self.put("transcribe", {"tool": "transcribe", "port": tt.port})
        self.put("cut2resolve", {"tool": "cut2resolve", "port": wrong.port})   # app が違う → 入れない
        self.put("evil", {"tool": "evil", "port": tt.port})                   # 知らない ID は読まない
        self.assertEqual(runtime.siblings(self.dir, "studio", 8800), {"tools": {"studio": 8800, "transcribe": tt.port}})
        self.assertEqual(runtime.siblings(self.dir, None, None), {"tools": {"transcribe": tt.port}})
        self.assertEqual(runtime.siblings(os.path.join(self.dir, "none"), "studio", 8800), {"tools": {"studio": 8800}})

    def test_siblings_does_not_wait_for_hung_server(self):
        hung = self.server("transcribe-tool", hang=True)
        self.put("transcribe", {"tool": "transcribe", "port": hung.port})
        t0 = time.monotonic()
        r = runtime.siblings(self.dir, "studio", 8800, timeout=0.3)
        self.assertLess(time.monotonic() - t0, 1.2)
        self.assertEqual(r, {"tools": {"studio": 8800}})

    def test_paths_for_mounted_tools(self):
        """統合サーバーに取り込まれたツールは、同じポートの /studio/ などにいる。記録・問い合わせ・siblings が場所を扱える"""
        unified = self.server(None, routes={"/api/ping": "ytt-launcher", "/studio/api/ping": "clip-studio"})
        p = runtime.write_runtime(self.dir, "studio", unified.port, "0.3.0", path="/studio/")
        with open(p, encoding="utf-8") as f:
            self.assertEqual(json.load(f)["path"], "/studio/")
        self.assertEqual(runtime.read_runtime(self.dir, "studio")["path"], "/studio/")
        self.assertEqual(runtime.ping_app(unified.port), "ytt-launcher")
        self.assertEqual(runtime.ping_app(unified.port, path="/studio/"), "clip-studio")
        tt = self.server("transcribe-tool")
        self.put("transcribe", {"tool": "transcribe", "port": tt.port})
        r = runtime.siblings(self.dir, "transcribe", tt.port)
        self.assertEqual(r, {"tools": {"studio": unified.port, "transcribe": tt.port}, "paths": {"studio": "/studio/"}})
        # 取り込まれたツール自身から見ても(自分の場所を付ける)
        r = runtime.siblings(self.dir, "studio", unified.port, self_path="/studio/")
        self.assertEqual(r, {"tools": {"studio": unified.port, "transcribe": tt.port}, "paths": {"studio": "/studio/"}})
        # 同じポートの別の場所にいる別のツールは、ポートが同じでも問い合わせる(ポートだけで自分と見なさない)
        self.put("cut2resolve", {"tool": "cut2resolve", "port": unified.port, "path": "/cut/"})
        r = runtime.siblings(self.dir, "studio", unified.port, self_path="/studio/")
        self.assertNotIn("cut2resolve", r["tools"])   # /cut/api/ping は答えない
        self.put("cut2resolve", {"tool": "cut2resolve", "port": unified.port, "path": "/studio/"})
        self.assertNotIn("cut2resolve", runtime.siblings(self.dir, "studio", unified.port, self_path="/studio/")["tools"])

    def test_path_validation(self):
        for bad in ("studio/", "/studio", "//evil.example/", "/../", "/Studio/", "/a/b/", "http://x/", None, 1, "/" + "a" * 40 + "/"):
            self.assertFalse(runtime.valid_path(bad), bad)
            self.assertIsNone(runtime.write_runtime(self.dir, "studio", 8800, "v", path=bad), bad)
            self.assertIsNone(runtime.ping(8800, path=bad), bad)
        for ok in ("/", "/studio/", "/cut2resolve/"):
            self.assertTrue(runtime.valid_path(ok), ok)
        self.put("studio", {"tool": "studio", "port": 8800, "path": "//evil.example/"})
        self.assertEqual(runtime.read_runtime(self.dir, "studio")["path"], "/")   # 形の違う場所は使わない
        runtime.write_runtime(self.dir, "studio", 8800, "v")
        with open(os.path.join(self.dir, "studio.json"), encoding="utf-8") as f:
            self.assertNotIn("path", json.load(f))   # 直下のときは書かない(以前の形のまま)

    def test_cut2resolve_uses_ytt_core(self):
        """cut2resolve も 2026-09-26 から ytt.runtime を使う(自分の写しを持たない)。TOOL_APPS を自分で書き直していないこと"""
        path = os.path.join(REPO, "cut2resolve", "serve.py")
        if not os.path.isfile(path):
            self.skipTest("cut2resolve が無い")
        with open(path, encoding="utf-8") as f:
            tree = ast.parse(f.read())
        found = [node.value for node in ast.walk(tree)
                 if isinstance(node, ast.Assign) and any(getattr(t, "id", None) == "TOOL_APPS" for t in node.targets)]
        self.assertEqual([ast.unparse(v) for v in found], ["_runtime.TOOL_APPS"])


class TestSchemas(unittest.TestCase):
    def test_now_ms(self):
        """今の時刻のミリ秒(整数。文書・記録の at・updatedAt と同じ単位。RS3-0B でスタジオの store.now_ms から出した)"""
        import time
        before = int(time.time() * 1000)
        v = schemas.now_ms()
        after = int(time.time() * 1000)
        self.assertIs(type(v), int)
        self.assertTrue(before <= v <= after, (before, v, after))

    def test_build_and_validate_clip(self):
        d = schemas.build_clip(os.path.join("x", "動画_0012.mp4"), 45.2345,
                               {"kind": "youtube", "videoId": "abcdefghijk", "title": "配信", "path": "/secret"},
                               (1234.5678, 1279.7), {"id": "m1", "label": "見どころ", "status": "exported", "src": "evil"},
                               {"mode": "fast", "actualStart": 1231.0}, {"name": "clip-studio", "version": "0.2.0"})
        self.assertEqual(d["schema"], schemas.CLIP_SCHEMA)
        self.assertEqual(d["media"]["durationSec"], 45.234)
        self.assertEqual(d["range"], {"start": 1234.568, "end": 1279.7})
        self.assertIsNone(d["source"]["path"])            # youtube のときはパスを入れない
        self.assertEqual(d["mark"]["src"], "manual")      # 知らない src は manual に
        self.assertEqual(d["tool"], {"name": "clip-studio", "version": "0.2.0"})
        clip, warn = schemas.validate_clip(json.loads(json.dumps(d)))
        self.assertIsNone(warn)
        self.assertEqual(schemas.clip_offset(clip), 1231.0)
        clip["range"]["start"] = 0
        self.assertEqual(d["range"]["start"], 1234.568)   # 複製なので元に響かない

    def test_validate_rejects(self):
        base = {"schema": schemas.CLIP_SCHEMA, "range": {"start": 10, "end": 20}}
        self.assertIsNotNone(schemas.validate_clip(base)[0])
        bad = [None, [], dict(base, schema="youtube-tools-clip/v2"), dict(base, schema="x"), dict(base, range={"start": 20, "end": 10}),
               dict(base, range={"start": -1, "end": 10}), dict(base, range={"start": True, "end": 10}), dict(base, media="x"),
               dict(base, export={"actualStart": -3}), dict(base, range={"start": float("nan"), "end": 10})]
        for obj in bad:
            self.assertIsNone(schemas.validate_clip(obj)[0], obj)
        self.assertIn("未対応の版", schemas.validate_clip(dict(base, schema="youtube-tools-clip/v2"))[1])

    def test_num(self):
        self.assertEqual([schemas.num(v) for v in (1, 2.5, True, "1", None, float("nan"), float("inf"), 10 ** 400)],
                         [1.0, 2.5, None, None, None, None, None, None])
        huge = {"schema": schemas.CLIP_SCHEMA, "range": {"start": 10 ** 400, "end": 10 ** 401}}
        self.assertIsNone(schemas.validate_clip(huge)[0])   # float にできない巨大な整数でも落ちない(以前は OverflowError)

    def test_paths_and_load(self):
        # 途中のファイルは 作業用\ に書く(2026-09-27。出力先の直下はパックと元動画だけ)。動画がもう 作業用 の中ならそこ
        W = schemas.WORK_DIR
        self.assertEqual(schemas.clip_path_for(os.path.join("x", "a.b.mp4")), os.path.abspath(os.path.join("x", W, "a.b.clip.json")))
        self.assertEqual(schemas.clip_path_for(os.path.join("x", W, "a_edit.mp4")), os.path.abspath(os.path.join("x", W, "a_edit.clip.json")))
        self.assertEqual(schemas.media_folder(os.path.join("x", W, "a.clip.json")), os.path.abspath("x"))
        self.assertEqual(schemas.media_folder(os.path.join("x", "a.clip.json")), os.path.abspath("x"))
        with tempfile.TemporaryDirectory() as tmp:
            v = os.path.join(tmp, "v.mp4")
            self.assertEqual(schemas.sidecar_candidates(v, ".srt"), [os.path.join(tmp, W, "v.srt"), os.path.join(tmp, "v.srt")])
            self.assertIsNone(schemas.find_sidecar(v, ".srt"))
            with open(os.path.join(tmp, "v.srt"), "w") as f:            # 以前の置き方(動画の隣)も読む
                f.write("1")
            self.assertEqual(schemas.find_sidecar(v, ".srt"), os.path.join(tmp, "v.srt"))
            os.makedirs(os.path.join(tmp, W))
            with open(os.path.join(tmp, W, "v.srt"), "w") as f:         # 作業用\ が先
                f.write("2")
            self.assertEqual(schemas.find_sidecar(v, ".srt"), os.path.join(tmp, W, "v.srt"))
            self.assertEqual(schemas.find_clip_path(v), None)
        with tempfile.TemporaryDirectory() as tmp:
            p = os.path.join(tmp, "a.clip.json")
            self.assertIsNone(schemas.load_clip_file(p)[0])
            with open(p, "w") as f:
                f.write(" " * (schemas.MAX_CLIP_BYTES + 1))
            self.assertIn("大きすぎ", schemas.load_clip_file(p)[1])
        self.assertIsNone(schemas.find_sidecar(os.path.join("x", "a\0b.mp4"), ".srt"))   # NUL を含むパスでも上げない

    def test_int_checks(self):
        vals = (1, 0, -3, True, False, 1.0, "1", None, float("nan"), 10 ** 400)
        self.assertEqual([schemas.is_int(v) for v in vals], [True, True, True, False, False, False, False, False, False, True])
        self.assertEqual([schemas.plain_int(v) for v in vals], [1, 0, -3, None, None, None, None, None, None, 10 ** 400])
        self.assertEqual([schemas.int_in(v, 0, 10) for v in (0, 10, 11, -1, True, 5.0, "5")], [0, 10, None, None, None, None, None])
        self.assertEqual([schemas.is_num(v) for v in (1, 2.5, True, "1", None, float("nan"), float("inf"), 10 ** 400)],
                         [True, True, False, False, False, False, False, False])

    def test_sidecar_suffixes(self):
        """途中のファイルの名前の一覧(全部入り)。各ツールの一覧はここの部分集合(まだ寄せていない)"""
        self.assertEqual(len(set(schemas.SIDECAR_SUFFIXES)), len(schemas.SIDECAR_SUFFIXES))
        for s in (schemas.CLIP_SUFFIX, ".edit.json", ".transcript.json", ".cut-plan.json", ".srt", "_edit.mp4", ".studio-id"):
            self.assertIn(s, schemas.SIDECAR_SUFFIXES)


class TestArtifactKey(unittest.TestCase):
    """成果物の鍵 youtube-tools-key/v1(RS1-5。形と純粋な関数だけ。書く側は RS6)"""
    SHA = "ab" * 32

    def inputs(self, start=12.345, end=40.0):
        return {"media": schemas.media_identity("archive", videoId="abc123"), "range": [start, end], "fps": 30, "opts": {"b": 1, "a": [True, None, "x"]}}

    def test_same_inputs_any_order_same_hash(self):
        a = schemas.make_key("export", {"x": 1, "y": {"p": 1, "q": 2}})
        b = schemas.make_key("export", {"y": {"q": 2, "p": 1}, "x": 1})
        self.assertEqual(a["hash"], b["hash"])
        self.assertEqual(len(a["hash"]), 64)
        self.assertEqual((a["schema"], a["v"], a["stage"]), (schemas.KEY_SCHEMA, schemas.KEY_VERSION, "export"))
        self.assertNotEqual(a["hash"], schemas.make_key("analyze", {"x": 1, "y": {"p": 1, "q": 2}})["hash"])   # 段が違えば別の鍵
        self.assertEqual(schemas.canon({"b": "日本", "a": [1, 2]}), '{"a":[1,2],"b":"日本"}')

    def test_ms_rounding(self):
        k = lambda s: schemas.make_key("export", self.inputs(s))["hash"]   # noqa: E731
        self.assertEqual(k(12.3456789), k(12.3460001))   # ミリ秒より細かい揺れは同じ鍵
        self.assertNotEqual(k(12.345), k(12.347))
        self.assertEqual(schemas.make_key("export", {"t": 12.0})["hash"], schemas.make_key("export", {"t": 12})["hash"])
        self.assertEqual(schemas.make_key("export", {"t": 3.4999})["inputs"], {"t": 3.5})
        self.assertEqual([schemas.sec_ms(v) for v in (1, 12.3456, 0.0006, -0.4)], [1000, 12346, 1, -400])
        for bad in (float("nan"), float("inf"), True, "1", None):
            with self.assertRaises(ValueError):
                schemas.sec_ms(bad)
        with self.assertRaises(ValueError):
            schemas.make_key("export", {"t": float("nan")})
        for bad in ({"t": object()}, {"t": {1: 2}}, {"t": b"x"}, {"t": {"s"}}):
            with self.assertRaises(TypeError):
                schemas.make_key("export", bad)
        with self.assertRaises(TypeError):
            schemas.make_key("export", [1])

    def test_at_and_made_by_do_not_affect_hash(self):
        a = schemas.make_key("export", self.inputs(), made_by={"name": "studio", "version": "1.0"})
        with mock.patch.object(schemas, "iso_now", return_value="2030-01-01T00:00:00+09:00"):
            b = schemas.make_key("export", self.inputs(), made_by={"name": "other", "version": "9"})
        c = schemas.make_key("export", self.inputs())
        self.assertEqual(b["at"], "2030-01-01T00:00:00+09:00")
        self.assertEqual(a["madeBy"], {"name": "studio", "version": "1.0"})
        self.assertNotIn("madeBy", c)
        self.assertTrue(a["hash"] == b["hash"] == c["hash"])
        self.assertEqual(a["hash"], json.loads(json.dumps(c))["hash"])   # ファイルに書いて読み戻しても同じ

    def test_media_identity(self):
        self.assertEqual(schemas.media_identity("recording", recorder="rec1", recording="r-0012"), {"kind": "recording", "recorder": "rec1", "recording": "r-0012"})
        self.assertEqual(schemas.media_identity("archive", videoId="abc123"), {"kind": "archive", "videoId": "abc123"})
        self.assertEqual(schemas.media_identity("file", sha256=self.SHA.upper()), {"kind": "file", "sha256": self.SHA})
        # 録画からの速報版とアーカイブからの本番版は同じ区間でも別の鍵(F-1)
        rec = schemas.make_key("export", dict(self.inputs(), media=schemas.media_identity("recording", recorder="rec1", recording="r-1")))
        self.assertNotEqual(rec["hash"], schemas.make_key("export", self.inputs())["hash"])
        bad = (("movie",), ("archive",), ("archive", {"videoId": ""}), ("archive", {"videoId": 5}), ("archive", {"videoId": "a", "x": "y"}),
               ("recording", {"recorder": "r"}), ("file", {"sha256": "zz"}), ("file", {"sha256": "ab" * 31}), ("file", {"path": "x.mp4"}))
        for args in bad:
            with self.assertRaises(ValueError, msg=args):
                schemas.media_identity(args[0], **(args[1] if len(args) > 1 else {}))

    def test_validate_key(self):
        k = schemas.make_key("transcribe", self.inputs())
        v, why = schemas.validate_key(json.loads(json.dumps(k)))
        self.assertIsNone(why)
        self.assertEqual(v, k)
        self.assertIsNot(v["inputs"], k["inputs"])   # 複製
        tampered = json.loads(json.dumps(k))
        tampered["inputs"]["fps"] = 60
        self.assertIn("合いません", schemas.validate_key(tampered)[1])
        for patch in ({"stage": "nope"}, {"stage": None}, {"hash": "xyz"}, {"hash": "A" * 64}, {"v": 2}, {"v": True}, {"inputs": [1]}, {"inputs": {"t": float("nan")}}):
            self.assertIsNone(schemas.validate_key(dict(k, **patch))[0], patch)
        self.assertIn("未対応の版", schemas.validate_key(dict(k, schema="youtube-tools-key/v2"))[1])
        self.assertIsNone(schemas.validate_key(dict(k, schema="youtube-tools-clip/v1"))[0])
        for obj in (None, [], "x", 1):
            self.assertIsNone(schemas.validate_key(obj)[0])
        with self.assertRaises(ValueError):
            schemas.make_key("bogus", {})
        self.assertIn("diar", schemas.KEY_STAGES)
        self.assertIn("post", schemas.KEY_STAGES)

    def test_file_digest(self):
        import hashlib
        data = b"0123456789" * 1000
        with tempfile.TemporaryDirectory() as tmp:
            p = os.path.join(tmp, "a.bin")
            with open(p, "wb") as f:
                f.write(data)
            self.assertEqual(schemas.file_digest(p), hashlib.sha256(data).hexdigest())
            self.assertEqual(schemas.file_digest(p, chunk=7), hashlib.sha256(data).hexdigest())
            q = os.path.join(tmp, "b.bin")
            with open(q, "wb") as f:
                f.write(data)
            os.utime(q, (1, 1))   # 更新日時が違っても中身が同じなら同じ
            self.assertEqual(schemas.file_digest(p), schemas.file_digest(q))
            self.assertEqual(schemas.media_identity("file", sha256=schemas.file_digest(p))["sha256"], schemas.file_digest(q))
            with self.assertRaises(OSError):
                schemas.file_digest(os.path.join(tmp, "none.bin"))

    def test_key_path(self):
        W = schemas.WORK_DIR
        self.assertEqual(schemas.key_path(os.path.join("x", "動画_0012.mp4"), "export"), os.path.abspath(os.path.join("x", W, "動画_0012.export.key.json")))
        self.assertEqual(schemas.key_path(os.path.join("x", W, "a.transcript.json"), "diar"), os.path.abspath(os.path.join("x", W, "a.transcript.diar.key.json")))
        with self.assertRaises(ValueError):
            schemas.key_path(os.path.join("x", "a.mp4"), "bogus")
        self.assertFalse(os.path.exists(os.path.join("x", W)))   # IO はしない


class TestHttpsec(unittest.TestCase):
    def test_checks(self):
        allowed = httpsec.allowed_hosts(8800)
        self.assertTrue(httpsec.host_ok({"Host": "127.0.0.1:8800"}, allowed))
        self.assertTrue(httpsec.host_ok({"Host": "localhost:8800"}, allowed))
        for h in ("evil.example:8800", "127.0.0.1:8801", "", None):
            self.assertFalse(httpsec.host_ok({"Host": h} if h is not None else {}, allowed), h)
        self.assertTrue(httpsec.origin_ok({}, allowed))
        self.assertTrue(httpsec.origin_ok({"Origin": "http://localhost:8800"}, allowed))
        for o in ("http://evil.example", "http://localhost:8801", "https://localhost:8800", "null", "localhost:8800"):
            self.assertFalse(httpsec.origin_ok({"Origin": o}, allowed), o)
        for s in (None, "same-origin", "none"):
            self.assertTrue(httpsec.fetch_site_ok({"Sec-Fetch-Site": s} if s else {}), s)
        for s in ("same-site", "cross-site"):
            self.assertFalse(httpsec.fetch_site_ok({"Sec-Fetch-Site": s}), s)
        nav = {"Sec-Fetch-Mode": "navigate", "Sec-Fetch-Dest": "document"}
        self.assertTrue(httpsec.navigation_ok(nav, "/"))
        self.assertTrue(httpsec.navigation_ok({"Sec-Fetch-Mode": "navigate"}, "/index.html"))
        self.assertFalse(httpsec.navigation_ok(nav, "/api/state"))
        self.assertFalse(httpsec.navigation_ok(dict(nav, **{"Sec-Fetch-Dest": "iframe"}), "/"))
        self.assertFalse(httpsec.navigation_ok({"Sec-Fetch-Mode": "cors"}, "/"))
        self.assertEqual(httpsec.PAGE_HEADERS["X-Frame-Options"], "DENY")

    def test_send(self):
        """応答の見出しの値と順番(スタジオ・編集・入口の _send とスタジオの動画で共通)。HEAD の要求には本文を書かない"""
        class H:
            def __init__(self, command):
                self.command, self.calls, self.body = command, [], b""
                self.wfile = self

            def write(self, b):
                self.body += b

            def send_response(self, code):
                self.calls.append(("status", code))

            def send_header(self, k, v):
                self.calls.append((k, v))

            def end_headers(self):
                self.calls.append(("end",))
        h = H("GET")
        httpsec.send(h, 404, b"not found", extra={"X-A": "1", "Location": "/x"})
        self.assertEqual(h.calls, [("status", 404), ("Content-Type", "text/plain; charset=utf-8"), ("Content-Length", "9"),
                                   ("Cache-Control", "no-store"), ("X-Content-Type-Options", "nosniff"), ("X-A", "1"), ("Location", "/x"), ("end",)])
        self.assertEqual(h.body, b"not found")
        h = H("HEAD")
        httpsec.send(h, 200, "あ".encode("utf-8"), "application/json")
        self.assertEqual(h.calls[1:3], [("Content-Type", "application/json"), ("Content-Length", "3")])   # HEAD でも長さは本文のもの
        self.assertEqual(h.body, b"")
        h = H("GET")
        httpsec.send_head(h, 206, "video/mp4", 100, {"Accept-Ranges": "bytes", "Content-Range": "bytes 0-99/500"})
        self.assertEqual(h.calls, [("status", 206), ("Content-Type", "video/mp4"), ("Content-Length", "100"), ("Cache-Control", "no-store"),
                                   ("X-Content-Type-Options", "nosniff"), ("Accept-Ranges", "bytes"), ("Content-Range", "bytes 0-99/500"), ("end",)])
        self.assertEqual(h.body, b"")
        h = H("GET")   # cache: Cache-Control だけ変える(録画の部品のセグメント・再生リスト)
        httpsec.send(h, 200, b"x", "video/mp2t", cache="private, max-age=86400")
        self.assertEqual(h.calls[3], ("Cache-Control", "private, max-age=86400"))
        h = H("GET")
        httpsec.send_head(h, 200, "application/vnd.apple.mpegurl", 0, cache="no-cache")
        self.assertEqual([c for c in h.calls if c[0] == "Cache-Control"], [("Cache-Control", "no-cache")])

    @staticmethod
    def body_handler(body, ctype="application/json", length=None):
        import io
        headers = {"Content-Type": ctype, "Content-Length": str(len(body)) if length is None else length}
        return mock.Mock(headers={k: v for k, v in headers.items() if v is not None}, rfile=io.BytesIO(body))

    def test_read_json_body(self):
        h = self.body_handler('{"a": "あ"}'.encode("utf-8"), "Application/JSON; charset=utf-8")
        self.assertEqual(httpsec.read_json_body(h, 100), {"a": "あ"})
        cases = [(self.body_handler(b"{}", "text/plain"), "type", 415), (self.body_handler(b"{}", length="x"), "length", 400),
                 (self.body_handler(b"{}" * 60), "size", 413), (self.body_handler(b""), "size", 413),
                 (self.body_handler(b"{}", length="-1"), "size", 413), (self.body_handler(b"{}", length="5"), "short", 400),
                 (self.body_handler(b"{bad"), "json", 400), (self.body_handler(b'{"a": NaN}'), "json", 400),
                 (self.body_handler(b"\xff\xfe"), "json", 400), (self.body_handler(b"[1]"), "object", 400)]
        for handler, kind, status in cases:
            with self.assertRaises(httpsec.BodyError) as cm:
                httpsec.read_json_body(handler, 100)
            self.assertEqual((cm.exception.kind, cm.exception.status), (kind, status), handler.rfile.getvalue())
        with self.assertRaises(httpsec.BodyError) as cm:   # 深すぎる JSON(読むと RecursionError)も「JSON として読めない」
            httpsec.read_json_body(self.body_handler(b'{"a":' + b"[" * 100000 + b"]" * 100000 + b"}"), 300000)
        self.assertEqual((cm.exception.kind, cm.exception.status), ("json", 400))
        self.assertEqual(httpsec.read_json_body(self.body_handler(b"", length=None), 100, empty_ok=True), {})   # 本文なし = {}
        nan = httpsec.read_json_body(self.body_handler(b'{"a": NaN}'), 100, allow_nan=True)["a"]
        self.assertNotEqual(nan, nan)                             # allow_nan=True なら NaN も通す(以前の入口と同じ)
        h = self.body_handler(b"x" * 50, "text/plain")
        with self.assertRaises(httpsec.BodyError):
            httpsec.read_json_body(h, 100)
        self.assertEqual(h.rfile.tell(), 50)                      # 断るときは本文を読み捨てる
        h = self.body_handler(b"x" * 50, "text/plain")
        with self.assertRaises(httpsec.BodyError):
            httpsec.read_json_body(h, 100, drain=False)
        self.assertEqual(h.rfile.tell(), 0)
        h = self.body_handler(b"{}")
        h.rfile = mock.Mock(read=mock.Mock(side_effect=OSError("timed out")))
        with self.assertRaises(httpsec.BodyError) as cm:
            httpsec.read_json_body(h, 100)
        self.assertEqual(cm.exception.kind, "read")

    def test_drain_body(self):
        import io
        r = io.BytesIO(b"x" * 10)
        httpsec.drain_body({"Content-Length": "10"}, r)
        self.assertEqual(r.tell(), 10)
        r = io.BytesIO(b"x" * 10)
        httpsec.drain_body({"Content-Length": "10"}, r, limit=5)     # 上限より大きければ読まない
        self.assertEqual(r.tell(), 0)
        httpsec.drain_body({"Content-Length": "x"}, r)              # 形が違っても上げない
        httpsec.drain_body({}, mock.Mock(read=mock.Mock(side_effect=OSError)))

    def test_token_ok(self):
        self.assertTrue(httpsec.token_ok({"X-YTT-Token": "abc"}, "abc"))
        self.assertFalse(httpsec.token_ok({"X-YTT-Token": "abd"}, "abc"))
        self.assertFalse(httpsec.token_ok({}, "abc"))
        self.assertFalse(httpsec.token_ok({"X-YTT-Token": ""}, ""))      # 合言葉が空なら常に断る
        self.assertFalse(httpsec.token_ok({"X-YTT-Token": "あ"}, "abc"))   # ASCII 以外でも落ちない
        self.assertTrue(httpsec.token_ok({"Authorization": "Bearer t1"}, "t1", "Authorization", "Bearer "))
        self.assertFalse(httpsec.token_ok({"Authorization": "t1"}, "t1", "Authorization", "Bearer "))

    def test_byte_range(self):
        self.assertEqual(httpsec.byte_range(None, 100), (0, 99, False))
        self.assertEqual(httpsec.byte_range("bytes=10-19", 100), (10, 19, True))
        self.assertEqual(httpsec.byte_range("bytes=10-", 100), (10, 99, True))
        self.assertEqual(httpsec.byte_range("bytes=-10", 100), (90, 99, True))
        self.assertEqual(httpsec.byte_range("bytes=-500", 100), (0, 99, True))
        self.assertEqual(httpsec.byte_range("bytes=50-5000", 100), (50, 99, True))
        self.assertEqual(httpsec.byte_range("bytes=-", 100), (0, 99, False))       # 読めない形は全体
        self.assertEqual(httpsec.byte_range("bytes=0-1,5-6", 100), (0, 99, False))
        for bad in ("bytes=100-", "bytes=20-10", "bytes=-0"):
            self.assertIsNone(httpsec.byte_range(bad, 100), bad)
        self.assertIsNone(httpsec.byte_range("bytes=0-", 0))

    def test_send_file(self):
        import io
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "v.mp4")
            with open(p, "wb") as f:
                f.write(bytes(range(200)) * 1000)

            def handler(rng=None, command="GET"):
                h = mock.Mock(command=command, headers={"Range": rng} if rng else {}, wfile=io.BytesIO())
                h.calls = []
                h.send_response.side_effect = lambda c: h.calls.append(("status", c))
                h.send_header.side_effect = lambda k, v: h.calls.append((k, v))
                return h
            h = handler("bytes=100-199")
            httpsec.send_file(h, p, "video/mp4", chunk=7)
            self.assertEqual(h.calls, [("status", 206), ("Content-Type", "video/mp4"), ("Content-Length", "100"), ("Cache-Control", "no-store"),
                                       ("X-Content-Type-Options", "nosniff"), ("Accept-Ranges", "bytes"), ("Content-Range", "bytes 100-199/200000")])
            self.assertEqual(h.wfile.getvalue(), bytes(range(100, 200)))
            h = handler()
            httpsec.send_file(h, p, "video/mp4", extra={"X-A": "1"})
            self.assertEqual(h.calls[0], ("status", 200))
            self.assertEqual(h.calls[-2:], [("Accept-Ranges", "bytes"), ("X-A", "1")])
            self.assertEqual(len(h.wfile.getvalue()), 200000)
            h = handler("bytes=0-9", "HEAD")
            httpsec.send_file(h, p, "video/mp4")
            self.assertEqual(h.wfile.getvalue(), b"")                 # HEAD は見出しだけ
            h = handler("bytes=999999-")
            httpsec.send_file(h, p, "video/mp4")
            h._send.assert_called_once_with(416, b"", extra={"Content-Range": "bytes */200000"})
            h = handler()
            h.wfile = mock.Mock(write=mock.Mock(side_effect=ConnectionResetError))
            httpsec.send_file(h, p, "video/mp4")                      # 送っている途中の切断は上げない
            with self.assertRaises(OSError):
                httpsec.send_file(handler(), os.path.join(d, "無い.mp4"), "video/mp4")

    def test_exclusive_server(self):
        class H(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                httpsec.send(self, 200, b"ok")

            def log_message(self, *a):
                pass
        srv = httpsec.ExclusiveServer(("127.0.0.1", 0), H)
        try:
            port = srv.server_address[1]
            self.assertTrue(srv.daemon_threads)
            if os.name == "nt":
                with self.assertRaises(OSError):                  # 使用中のポートには bind できない
                    httpsec.ExclusiveServer(("127.0.0.1", port), H)
                s = socket.socket()
                try:
                    httpsec.bind_opts(s)
                    with self.assertRaises(OSError):
                        s.bind(("127.0.0.1", port))
                finally:
                    s.close()
            threading.Thread(target=srv.serve_forever, daemon=True).start()
            import urllib.request
            opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
            with opener.open("http://127.0.0.1:%d/" % port, timeout=5) as r:
                self.assertEqual(r.read(), b"ok")
        finally:
            srv.shutdown()
            srv.server_close()
        s = socket.socket()
        try:
            httpsec.bind_opts(s)
            s.bind(("127.0.0.1", 0))                               # 空いているポートには bind できる
        finally:
            s.close()


class TestTools(unittest.TestCase):
    def test_find_tool_env_override(self):
        with tempfile.NamedTemporaryFile(delete=False) as f:
            fake = f.name
        try:
            with mock.patch.dict(os.environ, {"X_FFMPEG": fake}):
                self.assertEqual(tools.find_tool("ffmpeg", "X_FFMPEG"), fake)
            with mock.patch.dict(os.environ, {"X_FFMPEG": fake + ".missing"}), mock.patch.object(tools.shutil, "which", return_value="/p/ffmpeg"):
                self.assertEqual(tools.find_tool("ffmpeg", "X_FFMPEG"), "/p/ffmpeg")
        finally:
            os.unlink(fake)

    @unittest.skipUnless(os.name == "nt", "winget の場所は Windows だけ")
    def test_media_tool_finds_winget_and_sibling_ffprobe(self):
        """RS7-1 F-k: パックの ffmpeg / ffprobe は PATH に無くても winget の場所から(ffprobe は決めた ffmpeg の隣が先)。どこにも無ければ名前のまま"""
        tmp = tempfile.mkdtemp(prefix="ytt_media_tool_")
        self.addCleanup(shutil.rmtree, tmp, True)
        empty = os.path.join(tmp, "empty")
        os.makedirs(empty)
        env = {"LOCALAPPDATA": tmp, "PATH": empty, "TRANSCRIBE_FFMPEG": "", "YTT_FFMPEG": "", "YTT_FFPROBE": ""}
        with mock.patch.dict(os.environ, env):
            self.assertEqual((tools.media_tool("ffmpeg"), tools.media_tool("ffprobe"), tools.find_ffmpeg()), ("ffmpeg", "ffprobe", None))
            bin_dir = os.path.join(tmp, "Microsoft", "WinGet", "Packages", "Gyan.FFmpeg_x", "ffmpeg-9.0-full_build", "bin")
            os.makedirs(bin_dir)
            for n in ("ffmpeg.exe", "ffprobe.exe"):
                open(os.path.join(bin_dir, n), "wb").close()
            self.assertEqual(os.path.normcase(tools.media_tool("ffmpeg")), os.path.normcase(os.path.join(bin_dir, "ffmpeg.exe")))
            self.assertEqual(os.path.normcase(tools.media_tool("ffprobe")), os.path.normcase(os.path.join(bin_dir, "ffprobe.exe")))
            self.assertEqual(os.path.normcase(tools.find_ffmpeg()), os.path.normcase(os.path.join(bin_dir, "ffmpeg.exe")))
            other = os.path.join(tmp, "other")
            os.makedirs(other)
            for n in ("ffmpeg.exe", "ffprobe.exe"):
                open(os.path.join(other, n), "wb").close()
            with mock.patch.dict(os.environ, {"TRANSCRIBE_FFMPEG": os.path.join(other, "ffmpeg.exe")}):   # 環境変数で決めた ffmpeg の隣の ffprobe
                self.assertEqual(os.path.normcase(tools.media_tool("ffprobe")), os.path.normcase(os.path.join(other, "ffprobe.exe")))

    def test_subprocess_helpers(self):
        if os.name == "nt":
            self.assertEqual(tools.no_window_flags(), subprocess.CREATE_NO_WINDOW)
            self.assertEqual(tools.no_window_flags(new_group=True), subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP)
        else:
            self.assertEqual((tools.no_window_flags(), tools.no_window_flags(True)), (0, 0))
        done = mock.Mock(poll=mock.Mock(return_value=0))
        tools.kill_quiet(done)
        done.kill.assert_not_called()                       # 終わっていれば何もしない
        running = mock.Mock(poll=mock.Mock(return_value=None), kill=mock.Mock(side_effect=OSError("gone")))
        tools.kill_quiet(running)                           # 止められなくても上げない
        running.kill.assert_called_once()

    @unittest.skipUnless(os.name == "nt", "Windows のジョブオブジェクト")
    def test_kill_job(self):
        """KillJob(録画の部品の ffmpeg・streamlink、文字起こしの llama-server): 閉じると中の子が終わる・親が閉じずに落ちても子が残らない"""
        sleeper = [sys.executable, "-c", "import time; time.sleep(60)"]
        job = tools.KillJob()
        p = subprocess.Popen(sleeper, creationflags=tools.no_window_flags())
        try:
            self.assertTrue(job.add(p))
            self.assertIsNone(p.poll())
            job.close()
            self.assertIsNotNone(p.wait(10))                # 閉じたら中の子が終わる
            job.close()                                     # 2 回目は何もしない
            self.assertFalse(job.add(p))                    # 閉じたあとは入れない(上げない)
        finally:
            tools.kill_quiet(p)
        code = ("import os, subprocess, sys; sys.path.insert(0, sys.argv[1]); from ytt import tools; job = tools.KillJob(); "
                "c = subprocess.Popen(%r, creationflags=tools.no_window_flags()); print(c.pid, job.add(c), flush=True); os._exit(3)" % (sleeper,))
        out = subprocess.run([sys.executable, "-c", code, REPO], capture_output=True, text=True, timeout=60, creationflags=tools.no_window_flags())
        pid, added = out.stdout.split()
        import ctypes
        k = ctypes.WinDLL("kernel32", use_last_error=True)
        k.OpenProcess.restype = ctypes.c_void_p
        h = k.OpenProcess(0x00100001, False, int(pid))   # SYNCHRONIZE | PROCESS_TERMINATE
        try:
            gone = not h or k.WaitForSingleObject(ctypes.c_void_p(h), 10000) == 0
            if not gone:
                k.TerminateProcess(ctypes.c_void_p(h), 1)   # 残ったら片付けてから落とす
        finally:
            if h:
                k.CloseHandle(ctypes.c_void_p(h))
        self.assertEqual((out.returncode, added), (3, "True"))
        self.assertTrue(gone, "親が落ちたのに子が残った")   # 親(このテストの子)が落ちてジョブが閉じた = 孫も終わる

    def test_find_tool_ytt_env(self):
        """OPT1: 固有の環境変数 → YTT_<名前> → PATH(どの部品も YTT_ を見る)"""
        with tempfile.TemporaryDirectory() as d:
            a, b = os.path.join(d, "a.exe"), os.path.join(d, "b.exe")
            for p in (a, b):
                open(p, "wb").close()
            self.assertEqual(tools.ytt_env("yt-dlp"), "YTT_YTDLP")
            with mock.patch.dict(os.environ, {"YTT_YTDLP": a, "STUDIO_YTDLP": b}), mock.patch.object(tools.shutil, "which", return_value="/p/yt-dlp"):
                self.assertEqual(tools.find_tool("yt-dlp"), a)
                self.assertEqual(tools.find_tool("yt-dlp", "STUDIO_YTDLP"), b)     # 固有の名前が先(今までの指定が効く)
            with mock.patch.dict(os.environ, {"YTT_YTDLP": a + ".missing", "STUDIO_YTDLP": ""}), \
                    mock.patch.object(tools.shutil, "which", return_value="/p/yt-dlp"):
                self.assertEqual(tools.find_tool("yt-dlp", "STUDIO_YTDLP"), "/p/yt-dlp")   # 実在しなければ PATH

    @unittest.skipUnless(os.name == "nt", "winget の場所は Windows だけ")
    def test_find_tool_winget_for_every_caller(self):
        """OPT1 の不具合: PATH に無く winget だけで入れた ffmpeg・ffprobe・yt-dlp を、スタジオ・録画・ライブの探し方でも見つける。
        ffprobe は環境変数で決めた ffmpeg の隣が PATH より先"""
        tmp = tempfile.mkdtemp(prefix="ytt_find_tool_")
        self.addCleanup(shutil.rmtree, tmp, True)
        empty = os.path.join(tmp, "empty")
        os.makedirs(empty)
        env = {"LOCALAPPDATA": tmp, "PATH": empty}
        for v in ("STUDIO_FFMPEG", "STUDIO_FFPROBE", "STUDIO_YTDLP", "YTT_FFMPEG", "YTT_FFPROBE", "YTT_YTDLP", "TRANSCRIBE_FFMPEG"):
            env[v] = ""
        with mock.patch.dict(os.environ, env):
            self.assertIsNone(tools.find_tool("ffmpeg", "STUDIO_FFMPEG"))
            pk = os.path.join(tmp, "Microsoft", "WinGet", "Packages")
            bin_dir = os.path.join(pk, "Gyan.FFmpeg_x", "ffmpeg-9.0-full_build", "bin")
            yd_dir = os.path.join(pk, "yt-dlp.yt-dlp_x")
            for d, n in ((bin_dir, "ffmpeg.exe"), (bin_dir, "ffprobe.exe"), (yd_dir, "yt-dlp.exe")):
                os.makedirs(d, exist_ok=True)
                open(os.path.join(d, n), "wb").close()
            same = lambda p, d, n: self.assertEqual(os.path.normcase(p or ""), os.path.normcase(os.path.join(d, n)))
            same(studio_env.find_tool("ffmpeg"), bin_dir, "ffmpeg.exe")
            same(studio_env.find_tool("ffprobe"), bin_dir, "ffprobe.exe")
            same(tools.find_tool("ffmpeg"), bin_dir, "ffmpeg.exe")
            same(tools.find_tool("yt-dlp"), yd_dir, "yt-dlp.exe")
            other = os.path.join(tmp, "other")
            os.makedirs(other)
            for n in ("ffmpeg.exe", "ffprobe.exe"):
                open(os.path.join(other, n), "wb").close()
            with mock.patch.dict(os.environ, {"YTT_FFMPEG": os.path.join(other, "ffmpeg.exe")}):
                same(tools.find_tool("ffprobe"), other, "ffprobe.exe")
            with mock.patch.dict(os.environ, {"STUDIO_FFMPEG": os.path.join(other, "ffmpeg.exe")}):
                same(studio_env.find_tool("ffprobe"), other, "ffprobe.exe")

    def test_no_window_flags_priority(self):
        with self.assertRaises(ValueError):
            tools.no_window_flags(priority="idle")
        if os.name != "nt":
            self.assertEqual((tools.no_window_flags(priority="low"), tools.no_window_flags(True, "high")), (0, 0))
            return
        self.assertEqual(tools.no_window_flags(priority="low"), subprocess.CREATE_NO_WINDOW | subprocess.BELOW_NORMAL_PRIORITY_CLASS)
        self.assertEqual(tools.no_window_flags(new_group=True, priority="high"),
                         subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.ABOVE_NORMAL_PRIORITY_CLASS)

    def test_python_exe_and_why(self):
        with tempfile.TemporaryDirectory() as d:
            w = os.path.join(d, "pythonw.exe")
            self.assertEqual(tools.python_exe(w), w)                    # 隣に python.exe が無ければそのまま
            open(os.path.join(d, "python.exe"), "wb").close()
            self.assertEqual(tools.python_exe(w), os.path.join(d, "python.exe"))
            self.assertEqual(tools.python_exe(os.path.join(d, "python.exe")), os.path.join(d, "python.exe"))
        self.assertTrue(os.path.isfile(tools.python_exe()))           # 省けばこのプロセスの Python
        self.assertEqual(tools.why(FileNotFoundError(2, "見つかりません", "C:/秘密/x")), "見つかりません")   # パスは出さない
        self.assertEqual(tools.why(OSError("strerror の無い OSError")), "OSError")
        self.assertEqual(tools.why(ValueError("中身")), "ValueError")

    def test_kill_tree_fake_and_done(self):
        tools.kill_tree(None)
        fake = mock.Mock(poll=mock.Mock(return_value=None))
        tools.kill_tree(fake, wait=1)                               # Popen でなければ kill_quiet だけ(待たない)
        fake.kill.assert_called_once()
        fake.wait.assert_not_called()
        p = subprocess.Popen([sys.executable, "-c", "pass"], creationflags=tools.no_window_flags())
        p.wait(30)
        with mock.patch.object(tools.subprocess, "run") as run:
            tools.kill_tree(p)                                      # 終わっていれば何もしない
            run.assert_not_called()

    def test_kill_tree_kills_grandchild(self):
        code = ("import subprocess, sys, time; c = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)']); "
                "print(c.pid, flush=True); time.sleep(60)")
        extra = {} if os.name == "nt" else {"start_new_session": True}
        p = subprocess.Popen([sys.executable, "-c", code], stdout=subprocess.PIPE, creationflags=tools.no_window_flags(), **extra)
        try:
            child = int(p.stdout.readline())
            tools.kill_tree(p, wait=15)
            self.assertIsNotNone(p.poll())                          # 親が止まった(wait で待った)
            if os.name == "nt":
                import ctypes
                k = ctypes.WinDLL("kernel32", use_last_error=True)
                k.OpenProcess.restype = ctypes.c_void_p
                h = k.OpenProcess(0x00100001, False, child)          # SYNCHRONIZE | PROCESS_TERMINATE
                try:
                    gone = not h or k.WaitForSingleObject(ctypes.c_void_p(h), 10000) == 0
                    if not gone:
                        k.TerminateProcess(ctypes.c_void_p(h), 1)
                finally:
                    if h:
                        k.CloseHandle(ctypes.c_void_p(h))
            else:
                deadline = time.time() + 10
                while time.time() < deadline:
                    try:
                        os.kill(child, 0)
                    except OSError:
                        break
                    time.sleep(0.1)
                try:
                    os.kill(child, 0)
                    gone = False
                except OSError:
                    gone = True
            self.assertTrue(gone, "孫が残った")
        finally:
            tools.kill_quiet(p)
            p.stdout.close()

    def py(self, code):
        return [sys.executable, "-c", code]

    def test_run_collects_output(self):
        r = tools.run(self.py("import sys; print('出力'); sys.stderr.write('e1\\n\\ne2\\n'); sys.exit(3)"),
                      env=dict(os.environ, PYTHONIOENCODING="utf-8"))
        self.assertEqual((r.code, r.why), (3, None))
        self.assertEqual(r.out.decode("utf-8").strip(), "出力")
        self.assertEqual(r.err_lines(), ["e1", "e2"])
        self.assertEqual(r.err_lines(1), ["e2"])
        self.assertEqual(r.err_lines(0), [])
        r = tools.run(self.py("import sys\nfor i in range(50): sys.stderr.write('l%d\\n' % i)"), err_tail=3, stdout=False)
        self.assertEqual((r.out, r.err_lines(10)), (b"", ["l47", "l48", "l49"]))   # err_tail は最後の N 行だけ持つ
        seen = []
        tools.run(self.py("pass"), on_start=seen.append)
        self.assertEqual(len(seen), 1)
        self.assertIsInstance(seen[0], subprocess.Popen)
        with self.assertRaises(OSError):
            tools.run([os.path.join(tempfile.gettempdir(), "無いプログラム.exe")])

    def test_run_timeout_and_cancel(self):
        sleeper = self.py("import time; time.sleep(60)")
        t0 = time.monotonic()
        r = tools.run(sleeper, timeout=0.5, poll=0.1)
        self.assertEqual(r.why, "timeout")
        self.assertIsNotNone(r.code)
        self.assertLess(time.monotonic() - t0, 20)
        flag = {"n": 0}

        def cancelled():
            flag["n"] += 1
            return flag["n"] > 2
        self.assertEqual(tools.run(sleeper, cancelled=cancelled, poll=0.1).why, "cancel")
        seen = []

        class Stop(Exception):
            pass

        def boom():
            raise Stop()
        with self.assertRaises(Stop):                               # cancelled が上げたら、子を止めてから上げ直す(中止を例外で伝える形)
            tools.run(sleeper, cancelled=boom, on_start=seen.append, poll=0.1)
        self.assertIsNotNone(seen[0].poll())

    def test_run_progress(self):
        code = ("import sys, time\n"
                "for line in ['out_time_us=1500000', 'frame=10', 'progress=continue', '', 'error line', 'out_time_ms=3000000', 'x' * 30 + '=y']:\n"
                "    sys.stdout.write(line + '\\n')\n"
                "sys.stdout.flush(); sys.exit(4)\n")
        times = []
        code_, tail, why = tools.run_progress(self.py(code), on_time=times.append)
        self.assertEqual((code_, why), (4, None))
        self.assertEqual(times, [1.5, 3.0])
        self.assertEqual(tail, ["error line", "x" * 30 + "=y"])         # key=value(頭の 20 字に =)と進み具合の行は除く
        many = "import sys\nfor i in range(30): print('e%d' % i)\n"
        self.assertEqual(tools.run_progress(self.py(many), tail=2)[1], ["e28", "e29"])
        sleeper = self.py("import time; time.sleep(60)")
        self.assertEqual(tools.run_progress(sleeper, idle_sec=0.5)[2], "idle")
        self.assertEqual(tools.run_progress(sleeper, cancelled=lambda: True)[2], "cancel")
        calls = []

        def popen(cmd, **kw):
            calls.append(kw)
            return subprocess.Popen(cmd, **kw)
        tools.run_progress(self.py("pass"), flags=0, popen=popen)
        self.assertEqual(calls[0]["creationflags"], 0)               # 起動の差し替え・flags はそのまま渡す
        with self.assertRaises(OSError):
            tools.run_progress([os.path.join(tempfile.gettempdir(), "無いプログラム.exe")])

    def test_run_progress_options(self):
        """OPT2: 時間の上限・標準エラーを別に全部・行ごとの on_line・CR の区切り・作業フォルダ・spawn の一覧・既定は窓なしで優先度「低」"""
        both = ("import sys, os\n"
                "sys.stdout.write('out_time_us=2000000\\nhello\\nframe=1\\rtime=00:00:03.00\\n' + os.getcwd() + '\\n')\n"
                "sys.stderr.write('e1\\n\\nk=v\\n')\n"
                "sys.exit(2)\n")
        got, times = [], []
        cwd = tempfile.mkdtemp()
        try:
            code, err, why = tools.run_progress(self.py(both), on_time=times.append, on_line=got.append, split=True, tail=None, cwd=cwd)
        finally:
            shutil.rmtree(cwd, ignore_errors=True)
        self.assertEqual((code, why, times), (2, None, [2.0]))
        self.assertEqual(got[:3], ["hello", "frame=1", "time=00:00:03.00"])           # 進み具合の行は on_time へ・CR も行の区切り
        self.assertEqual(os.path.normcase(got[3]), os.path.normcase(cwd))
        self.assertEqual(err, ["e1", "", "k=v"])                                      # split = 標準エラーをそのまま全部
        sleeper = self.py("import time; time.sleep(60)")
        t0 = time.monotonic()
        self.assertEqual(tools.run_progress(sleeper, timeout=0.5)[2], "timeout")
        self.assertLess(time.monotonic() - t0, 20)
        calls, seen = [], []

        def popen(cmd, **kw):
            calls.append(kw)
            return subprocess.Popen(cmd, **kw)
        tools.run_progress(self.py("pass"), popen=popen, on_start=seen.append)
        self.assertEqual(calls[0]["creationflags"], tools.no_window_flags(priority="low"))
        self.assertIsNotNone(seen[0].poll())
        self.assertTrue(seen[0].stdout.closed)                                        # パイプを閉じる(ResourceWarning を出さない)
        started = []
        self.assertEqual(tools.run_progress(sleeper, cancelled=lambda: bool(started and started[0] in procs.children()), spawn=True,
                                            on_start=started.append)[2], "cancel")   # spawn の一覧に載り、終われば外れる
        self.assertNotIn(started[0], procs.children())

    def test_run_capture(self):
        """procs.run_capture(中身は run_progress): 標準出力は on_line・標準エラーは最後の 40 行・job[slot] は終われば空・パイプを閉じる"""
        code = "import sys\nprint('a'); print('out_time_us=1000000')\nfor i in range(50): sys.stderr.write('e%d\\n' % i)\nsys.exit(3)\n"
        got, times = [], []
        job = {"cancel": False, "proc": None}
        rc, err = procs.run_capture(job, self.py(code), got.append, on_time=times.append)
        self.assertEqual((rc, got, times, len(err), err[-1], job["proc"]), (3, ["a"], [1.0], 40, "e49", None))
        with self.assertRaises(errors.Cancelled):
            procs.run_capture({"cancel": True, "proc": None}, self.py("import time; time.sleep(60)"))
        with self.assertRaises(errors.ApiError) as cm:
            procs.run_capture({"cancel": False, "proc": None}, self.py("import time; time.sleep(60)"), idle_timeout=0.5, what="テスト")
        self.assertEqual(cm.exception.code, "timeout")
        self.assertEqual(procs.children(), [])

    def test_out_time(self):
        """-progress の進み具合の行(スタジオの exporter._pump も読む。us も ms もマイクロ秒)"""
        self.assertEqual(tools.OUT_TIME.match("out_time_us=1500000").group(1), "1500000")
        self.assertEqual(tools.OUT_TIME.match("out_time_ms=42").group(1), "42")
        for line in ("out_time=00:00:01.500000", "out_time_us=N/A", " out_time_us=1", "out_time_us=1 "):
            self.assertIsNone(tools.OUT_TIME.match(line), line)

    def test_tool_version(self):
        exe = sys.executable
        ver = ("-c", "print('ffmpeg version 9.0.2-full_build-www Copyright'); print('built with version 1')")
        self.assertEqual(tools.tool_version(exe, ver), "9.0.2-full_build-www")
        self.assertEqual(tools.tool_version(exe, ("-c", "print('2026.08.19')"), r"(\d{4}\.\d{2}\.\d{2})"), "2026.08.19")
        self.assertEqual(tools.tool_version(exe, ("-c", "print('no number here')")), "")
        self.assertEqual(tools.tool_version(exe, ("-c", "print('streamlink 7.1'); print('version 2')"), first_line=True), "streamlink 7.1")
        self.assertEqual(tools.tool_version(exe, ver, first_line=True), "9.0.2-full_build-www")
        self.assertEqual(tools.tool_version(os.path.join(tempfile.gettempdir(), "無い.exe")), "")
        self.assertIn("ffmpeg version", tools.tool_output(exe, ver))
        self.assertEqual(tools.tool_output(os.path.join(tempfile.gettempdir(), "無い.exe")), "")

    def test_process_memory_mb(self):
        now, peak = tools.process_memory_mb(), tools.process_memory_mb(peak=True)
        if os.name == "nt" or os.path.isfile("/proc/self/statm"):
            self.assertGreater(now, 1.0)
            self.assertGreaterEqual(peak, now * 0.5)
        with mock.patch.object(tools.os, "name", "posix"), mock.patch("builtins.open", side_effect=OSError):
            self.assertIsNone(tools.process_memory_mb())             # 測れなければ None


class TestDatadir(unittest.TestCase):
    """作業データの置き場所と、以前の場所からのコピー(段階4)"""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.legacy = os.path.join(self.tmp, "repo", "editor")
        os.makedirs(os.path.join(self.legacy, "transcripts", ".hist", "a"))
        for rel, body in (("transcripts/a.json", "{}"), ("transcripts/.hist/a/1.json", "old"), ("settings.json", '{"x": 1}')):
            with open(os.path.join(self.legacy, rel), "w", encoding="utf-8") as f:
                f.write(body)
        self.env = {"YTT_DATA_DIR": os.path.join(self.tmp, "data")}
        self.new = os.path.join(self.tmp, "data", "transcribe")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_studio_out_dir(self):
        """スタジオの書き出し先(入口の live.py・launch.py が読む): settings.json の outDir(絶対パス)か、無ければ作業データの exports"""
        env = {"YTT_DATA_DIR": os.path.join(self.tmp, "data")}
        sdir = os.path.join(self.tmp, "data", "studio")
        self.assertEqual(datadir.studio_out_dir(env=env), os.path.join(sdir, "exports"))
        os.makedirs(sdir)
        out = os.path.join(self.tmp, "書き出し")
        for body, want in ((json.dumps({"outDir": out}), out), (json.dumps({"outDir": "相対"}), None), (json.dumps({"outDir": ""}), None),
                           (json.dumps({"outDir": 3}), None), ("[1]", None), ("{壊れ", None)):
            with open(os.path.join(sdir, "settings.json"), "w", encoding="utf-8") as f:
                f.write(body)
            self.assertEqual(datadir.studio_out_dir(env=env), want or os.path.join(sdir, "exports"), body)

    def test_read_marker(self):
        d = os.path.join(self.tmp, "m")
        os.makedirs(d)
        self.assertIsNone(datadir.read_marker(d))
        for body, want in (('\ufeff{"items": []}', {"items": []}), ("[]", None), ("{壊れ", None), ('{"a": "' + "x" * datadir.MARKER_MAX + '"}', None)):
            with open(os.path.join(d, datadir.MARKER), "w", encoding="utf-8") as f:
                f.write(body)
            self.assertEqual(datadir.read_marker(d), want, body[:20])

    def test_root(self):
        self.assertEqual(datadir.data_root({"LOCALAPPDATA": r"C:\Users\u\AppData\Local"}, "win32"),
                         os.path.join(r"C:\Users\u\AppData\Local", "youtube-tools"))
        self.assertEqual(datadir.data_root({}, "win32", "/h"), os.path.join("/h", "AppData", "Local", "youtube-tools"))
        self.assertEqual(datadir.data_root({}, "linux", "/h"), os.path.join("/h", ".local", "share", "youtube-tools"))
        self.assertEqual(datadir.data_root({"XDG_DATA_HOME": "/x"}, "linux", "/h"), os.path.join("/x", "youtube-tools"))
        self.assertEqual(datadir.data_root({}, "darwin", "/h"), os.path.join("/h", "Library", "Application Support", "youtube-tools"))
        self.assertIsNone(datadir.data_root({"YTT_DATA_DIR": "InPlace"}, "win32"))
        self.assertEqual(datadir.tool_dir("studio", "/r/studio", {"YTT_DATA_DIR": "inplace"}), os.path.abspath("/r/studio"))

    def test_copy_once_and_keep_original(self):
        logs = []
        r = datadir.prepare("transcribe", self.legacy, ["transcripts", "settings.json", "dataset"], self.env, logs.append)
        self.assertEqual((r["state"], r["dir"], r["migrated"]), ("migrated", self.new, ["transcripts", "settings.json"]))
        with open(os.path.join(self.new, "transcripts", ".hist", "a", "1.json"), encoding="utf-8") as f:
            self.assertEqual(f.read(), "old")                                   # 隠しフォルダの中も写す
        self.assertTrue(os.path.isfile(os.path.join(self.legacy, "settings.json")))   # 元は消さない
        self.assertTrue(logs and "消しません" in logs[0])
        self.assertEqual(datadir.read_marker(self.new)["items"], ["transcripts", "settings.json"])
        # 2回目は写さない(以前の場所が変わっても、新しい場所が正)
        with open(os.path.join(self.legacy, "settings.json"), "w", encoding="utf-8") as f:
            f.write("changed")
        with open(os.path.join(self.new, "settings.json"), "w", encoding="utf-8") as f:
            f.write("new")
        self.assertEqual(datadir.prepare("transcribe", self.legacy, ["transcripts", "settings.json"], self.env)["state"], "done")
        with open(os.path.join(self.new, "settings.json"), encoding="utf-8") as f:
            self.assertEqual(f.read(), "new")

    def test_existing_items_are_not_overwritten(self):
        os.makedirs(self.new)
        with open(os.path.join(self.new, "settings.json"), "w", encoding="utf-8") as f:
            f.write("mine")
        r = datadir.prepare("transcribe", self.legacy, ["transcripts", "settings.json"], self.env)
        self.assertEqual(r["migrated"], ["transcripts"])
        with open(os.path.join(self.new, "settings.json"), encoding="utf-8") as f:
            self.assertEqual(f.read(), "mine")

    def test_nothing_to_copy(self):
        r = datadir.prepare("studio", os.path.join(self.tmp, "empty"), ["data.json"], self.env)
        self.assertEqual((r["state"], r["dir"]), ("new", os.path.join(self.tmp, "data", "studio")))

    def test_inplace(self):
        r = datadir.prepare("transcribe", self.legacy, ["transcripts"], {"YTT_DATA_DIR": "inplace"})
        self.assertEqual((r["state"], r["dir"]), ("inplace", os.path.abspath(self.legacy)))
        self.assertFalse(os.path.exists(self.new))

    def test_not_enough_space_keeps_legacy(self):
        r = datadir.prepare("transcribe", self.legacy, ["transcripts"], self.env, free_bytes=1024)
        self.assertEqual((r["state"], r["dir"]), ("failed", os.path.abspath(self.legacy)))
        self.assertIn("空き容量", r["warnings"][0])
        self.assertFalse(os.path.exists(os.path.join(self.new, "transcripts")))
        self.assertIsNone(datadir.read_marker(self.new))   # 次の起動でもう一度試す

    def test_copy_failure_keeps_legacy_and_removes_partial(self):
        real = datadir._copy_item
        calls = []

        def flaky(src, dst):
            calls.append(src)
            if src.endswith("settings.json"):
                raise OSError("disk error")
            return real(src, dst)
        with mock.patch.object(datadir, "_copy_item", flaky):
            r = datadir.prepare("transcribe", self.legacy, ["transcripts", "settings.json"], self.env)
        self.assertEqual((r["state"], r["dir"]), ("failed", os.path.abspath(self.legacy)))
        self.assertIn("disk error", r["warnings"][0])
        self.assertFalse(os.path.exists(os.path.join(self.new, "transcripts")))   # 途中まで写した分も消す(古くなるため)
        self.assertEqual(os.listdir(self.new), [])
        r = datadir.prepare("transcribe", self.legacy, ["transcripts", "settings.json"], self.env)   # 次の起動で写し直す
        self.assertEqual(r["state"], "migrated")

    def test_size_mismatch_is_a_failure_and_leaves_no_part(self):
        real_size = datadir._size
        with mock.patch.object(datadir, "_size", side_effect=lambda p: (0, 0) if datadir.PART in p else real_size(p)):
            r = datadir.prepare("transcribe", self.legacy, ["transcripts"], self.env)
        self.assertEqual(r["state"], "failed")
        self.assertEqual([n for n in os.listdir(self.new) if datadir.PART in n], [])

    def test_leftover_part_is_cleaned(self):
        os.makedirs(os.path.join(self.new, "transcripts" + datadir.PART + "123"))
        r = datadir.prepare("transcribe", self.legacy, ["transcripts"], self.env)
        self.assertEqual(r["state"], "migrated")
        self.assertEqual(sorted(os.listdir(self.new)), [datadir.MARKER, "transcripts"])

    @unittest.skipIf(os.name == "nt", "シンボリックリンクの作成に権限が要る")
    def test_links_are_not_followed(self):
        outside = os.path.join(self.tmp, "secret.txt")
        with open(outside, "w") as f:
            f.write("s")
        os.symlink(outside, os.path.join(self.legacy, "transcripts", "link.json"))
        datadir.prepare("transcribe", self.legacy, ["transcripts"], self.env)
        self.assertFalse(os.path.lexists(os.path.join(self.new, "transcripts", "link.json")))

    def test_resolve_precedence(self):
        """置き場所の求め方は datadir の1か所(2026-10-01): 登録 → ツールごとの環境変数 → YTT_DATA_DIR・既定。env を渡したら登録を見ない"""
        repo = os.path.join(self.tmp, "repo")
        reg = os.path.join(self.tmp, "registered")
        env = dict(self.env)
        self.addCleanup(datadir.register, "transcribe", None)
        self.addCleanup(datadir.register, "studio", None)
        self.assertEqual(datadir.resolve("transcribe", repo, env), self.new)                                  # ③ YTT_DATA_DIR
        self.assertEqual(datadir.resolve("transcribe", repo, {"YTT_DATA_DIR": "inplace"}), os.path.abspath(self.legacy))   # ③ inplace
        self.assertEqual(datadir.resolve("studio", repo, {"YTT_DATA_DIR": "inplace"}), os.path.join(repo, "studio"))
        env["TRANSCRIBE_DATA_DIR"] = os.path.join(self.tmp, "tx")
        self.assertEqual(datadir.resolve("transcribe", repo, env), os.path.join(self.tmp, "tx"))             # ② 環境変数が先
        self.assertEqual(datadir.resolve("studio", repo, env), os.path.join(self.tmp, "data", "studio"))     # 他のツールの環境変数は効かない
        self.assertEqual(datadir.resolve("app", repo, dict(env, STUDIO_HOME="/s")), os.path.join(self.tmp, "data", "app"))
        self.assertEqual(datadir.resolve("x", legacy_dir=self.legacy, env={"YTT_DATA_DIR": "inplace"}), os.path.abspath(self.legacy))
        self.assertEqual(datadir.register("transcribe", reg), reg)
        self.assertEqual(datadir.registered("transcribe"), reg)
        self.assertEqual(datadir.resolve("transcribe", repo, env), os.path.join(self.tmp, "tx"))             # env を渡したら登録を見ない(テスト)
        with mock.patch.dict(os.environ, env):
            self.assertEqual(datadir.resolve("transcribe", repo), reg)                                       # ① 登録が先
            self.assertEqual(datadir.locate("transcribe", repo), os.path.join(self.tmp, "tx"))              # locate は登録を見ない
            self.assertEqual(datadir.resolve("studio", repo), os.path.join(self.tmp, "data", "studio"))     # 登録は tool ごと
            datadir.register("transcribe", None)
            self.assertIsNone(datadir.registered("transcribe"))
            self.assertEqual(datadir.resolve("transcribe", repo), os.path.join(self.tmp, "tx"))

    def test_prepare_override_and_register(self):
        """prepare: ツールごとの環境変数があれば写さずにそこ(state=override)。env を渡さない(本物の起動)ときだけ登録する"""
        self.addCleanup(datadir.register, "transcribe", None)
        datadir.register("transcribe", None)
        tx = os.path.join(self.tmp, "tx")
        r = datadir.prepare("transcribe", self.legacy, ["transcripts"], dict(self.env, TRANSCRIBE_DATA_DIR=tx))
        self.assertEqual((r["dir"], r["state"], r["migrated"]), (tx, "override", []))
        self.assertFalse(os.path.exists(self.new))                        # 写さない
        self.assertIsNone(datadir.registered("transcribe"))               # env を渡したら登録しない
        datadir.prepare("transcribe", self.legacy, ["transcripts"], self.env)
        self.assertIsNone(datadir.registered("transcribe"))
        with mock.patch.dict(os.environ, self.env):
            os.environ.pop("TRANSCRIBE_DATA_DIR", None)
            r = datadir.prepare("transcribe", self.legacy, ["transcripts"])
            self.assertEqual(r["dir"], self.new)
            self.assertEqual(datadir.registered("transcribe"), self.new)  # 本物の起動は決めた場所を登録する
            self.assertEqual(datadir.resolve("transcribe", os.path.join(self.tmp, "else")), self.new)
            os.environ["TRANSCRIBE_DATA_DIR"] = tx
            self.assertEqual(datadir.prepare("transcribe", self.legacy, ["transcripts"])["state"], "override")
            self.assertEqual(datadir.registered("transcribe"), tx)
        with mock.patch.dict(os.environ, {"YTT_DATA_DIR": "inplace"}):
            os.environ.pop("TRANSCRIBE_DATA_DIR", None)
            self.assertEqual(datadir.prepare("transcribe", self.legacy, ["transcripts"])["state"], "inplace")
            self.assertEqual(datadir.registered("transcribe"), os.path.abspath(self.legacy))   # inplace でも使う場所を登録する

    def test_every_server_test_isolates_data_dir(self):
        """サーバー(serve.py・入口)を動かすテストは、必ず YTT_DATA_DIR を指定する。忘れると、移し済みの PC で
        テストのサーバーが本物の作業データ(AppData\\youtube-tools)を読み書きしてしまう"""
        import glob
        import re
        bad = []
        files = sorted(glob.glob(os.path.join(REPO, "**", "tests", "test_*.py"), recursive=True) + glob.glob(os.path.join(REPO, "**", "tests", "e2e_*.py"), recursive=True)
                       + glob.glob(os.path.join(TOP, "dev", "tests", "test_*.py")) + glob.glob(os.path.join(TOP, "dev", "tests", "e2e_*.py")))   # テストは各フォルダの tests/(段0。役割の層は pipeline/pack/tests のように入れ子)。dev/ は src の外
        self.assertTrue(any(os.path.basename(f) == "test_launch.py" for f in files), "テストの場所が見つからない")
        for f in files:
            with open(f, encoding="utf-8") as fp:
                src = fp.read()
            if re.search(r"\bserve\b|launch\.py|import launch|import mount", src) and "YTT_DATA_DIR" not in src:
                bad.append(os.path.relpath(f, REPO))
        self.assertEqual(bad, [])


class TestLayout(unittest.TestCase):
    """リポジトリの中のフォルダの並び(ytt/layout.py。段0・2026-10-07 の src/ と friend-apps/)"""

    def test_tool_dirs(self):
        self.assertEqual(layout.src_root(), REPO)
        self.assertEqual(layout.repo_root(), TOP)
        self.assertEqual(layout.repo_root("/x/src"), os.path.dirname(os.path.abspath("/x/src")))
        self.assertEqual(os.path.basename(REPO), layout.SRC_DIR)
        self.assertTrue(os.path.isfile(os.path.join(layout.src_root(), "ytt", "layout.py")))
        self.assertTrue(os.path.isfile(os.path.join(TOP, "start.bat")))
        want = {"app": "home", "studio": "studio", "transcribe": "editor", "cut2resolve": "cut2resolve"}
        for tool, name in want.items():
            self.assertEqual(layout.tool_dir(tool), os.path.join(REPO, name))
            self.assertEqual(layout.tool_dir(tool, "/r"), os.path.join("/r", name))
        for tool in ("studio", "transcribe", "cut2resolve"):
            self.assertTrue(os.path.isfile(os.path.join(layout.tool_dir(tool), "serve.py")), tool)
        self.assertTrue(os.path.isfile(os.path.join(layout.tool_dir("app"), "launch.py")))
        self.assertTrue(os.path.isfile(os.path.join(TOP, layout.HOLO_COLORS_DIR, "members.json")))
        self.assertEqual(layout.holo_colors_dir(), os.path.join(TOP, "friend-apps", "holo-colors"))
        self.assertTrue(os.path.isdir(os.path.join(TOP, layout.REQUEST_SENDER_DIR)))
        with self.assertRaises(KeyError):
            layout.tool_dir("clip-studio")   # 識別子はツールの ID(フォルダ名ではない)


class TestHeavySlots(unittest.TestCase):
    """重い処理の同時実行数の上限(ytt.jobs)"""

    def test_limit_from_env(self):
        self.assertEqual(jobs.limit_from_env({}), 2)
        self.assertEqual(jobs.limit_from_env({"YTT_MAX_HEAVY_JOBS": "3"}), 3)
        self.assertEqual(jobs.limit_from_env({"YTT_MAX_HEAVY_JOBS": "0"}), 1)
        self.assertEqual(jobs.limit_from_env({"YTT_MAX_HEAVY_JOBS": "99"}), jobs.MAX_LIMIT)
        self.assertEqual(jobs.limit_from_env({"YTT_MAX_HEAVY_JOBS": "x"}), 2)

    def test_limit_and_fifo(self):
        s = jobs.HeavySlots(1)
        order, waits = [], []
        first = s.acquire("studio", "a")
        started = threading.Event()

        def run(name):
            with s.slot(name, name, on_wait=lambda: waits.append(name), poll=0.01) as ok:
                order.append((name, ok))
        t1 = threading.Thread(target=run, args=("transcribe",))
        t1.start()
        time.sleep(0.1)
        t2 = threading.Thread(target=run, args=("cut2resolve",))
        t2.start()
        time.sleep(0.1)
        snap = s.snapshot()
        self.assertEqual([a["tool"] for a in snap["active"]], ["studio"])
        self.assertEqual([w["tool"] for w in snap["waiting"]], ["transcribe", "cut2resolve"])   # 先に来た順
        self.assertEqual(order, [])
        s.release(first)
        t1.join(5)
        t2.join(5)
        self.assertEqual(order, [("transcribe", True), ("cut2resolve", True)])
        self.assertEqual(sorted(waits), ["cut2resolve", "transcribe"])   # 待ち始めに1回ずつ
        self.assertEqual(s.snapshot(), {"limit": 1, "active": [], "waiting": []})
        started.set()

    def test_two_at_once_by_default(self):
        s = jobs.HeavySlots(2)
        a, b = s.acquire("x"), s.acquire("y")
        self.assertIsNotNone(a)
        self.assertIsNotNone(b)
        flag = []
        self.assertIsNone(s.acquire("z", cancelled=lambda: bool(flag.append(1)) or len(flag) > 2, poll=0.01))   # 3つ目は待つ → 取り消し
        s.release(a)
        self.assertIsNotNone(s.acquire("z"))

    def test_cancel_while_waiting_frees_the_queue(self):
        s = jobs.HeavySlots(1)
        held = s.acquire("studio")
        cancel = threading.Event()
        res = []
        t = threading.Thread(target=lambda: res.append(s.acquire("transcribe", cancelled=cancel.is_set, poll=0.01)))
        t.start()
        time.sleep(0.05)
        cancel.set()
        t.join(5)
        self.assertEqual(res, [None])
        s.release(held)
        self.assertIsNotNone(s.acquire("cut2resolve", poll=0.01))   # 取り消した人が列を塞がない

    def test_exception_releases(self):
        s = jobs.HeavySlots(1)
        with self.assertRaises(RuntimeError):
            with s.slot("x"):
                raise RuntimeError("boom")
        self.assertEqual(s.snapshot()["active"], [])


class TestTxIndex(unittest.TestCase):
    """文字起こしの文書を他のツールから読む(入口の案件・スタジオのセリフの表示で共通の紐づけの規則)"""
    VID = "abcdefghijk"

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.dir = os.path.join(self.tmp, "transcripts")
        os.makedirs(self.dir)
        self.clip = os.path.join(self.tmp, "exports", "01_a.mp4")
        os.makedirs(os.path.dirname(self.clip))
        with open(self.clip, "wb") as f:
            f.write(b"x")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_pack_info(self):
        """パックの有無の規則(入口の案件・文字起こしの一覧で共通): 切り抜きの隣の <名前>_pack に cut-plan.json があれば「あり」"""
        from manage.cases import txindex
        self.assertIsNone(txindex.pack_info(self.clip))
        self.assertIsNone(txindex.pack_info(""))
        d = os.path.join(os.path.dirname(self.clip), "01_a_pack")
        os.makedirs(d)
        self.assertIsNone(txindex.pack_info(self.clip))   # フォルダだけでは「あり」にしない(作りかけ)
        with open(os.path.join(d, "cut-plan.json"), "w") as f:
            f.write("{}")
        p = txindex.pack_info(self.clip)
        self.assertEqual((p["dir"], p["textplus"]), (d, False))
        self.assertGreater(p["updatedAt"], 0)
        with open(os.path.join(d, "textplus-import.json"), "w") as f:
            f.write("{}")
        self.assertTrue(txindex.pack_info(self.clip)["textplus"])
        self.assertFalse(txindex.is_pack_dir(d))   # 以前のパックでも、cut2resolve の書いた cut-plan.json でなければ「フォルダを開く」は許さない
        with open(os.path.join(d, "cut-plan.json"), "w") as f:
            json.dump({"schema": "youtube-tools-cut-plan/v1", "tool": {"name": "cut2resolve"}}, f)
        self.assertTrue(txindex.is_pack_dir(d))

    def test_pack_record(self):
        """2026-09-26(④)から: パックに cut-plan.json を置かず、cut2resolve の作業データ packs/ の記録で「パック済み」を決める"""
        import json as _json
        from manage.cases import txindex
        env = {"YTT_DATA_DIR": os.path.join(self.tmp, "data")}
        d = txindex.pack_dir(self.clip)
        os.makedirs(os.path.join(d, "media"))
        rec_dir = txindex.packs_dir(env)
        self.assertEqual(rec_dir, os.path.join(self.tmp, "data", "cut2resolve", "packs"))
        os.makedirs(rec_dir)
        rec = {"schema": txindex.PACK_RECORD_SCHEMA, "dir": d.upper() if os.name == "nt" else d, "textplus": True, "builtAt": 1790000000000,
               "files": ["create_resolve_textplus_project.lua", "media/01_a.mp4"]}
        with open(os.path.join(rec_dir, txindex.pack_key(d)), "w", encoding="utf-8") as f:
            _json.dump(rec, f)
        self.assertIsNone(txindex.pack_info(self.clip, env))                 # 記録したファイルがフォルダに無い(消した・作りかけ)
        self.assertFalse(txindex.is_pack_dir(d, env))
        with open(os.path.join(d, "media", "01_a.mp4"), "w") as f:
            f.write("x")
        self.assertEqual(txindex.pack_info(self.clip, env), {"dir": d, "textplus": True, "updatedAt": 1790000000000})
        self.assertTrue(txindex.is_pack_dir(d, env))
        self.assertIsNone(txindex.pack_info(self.clip, {"YTT_DATA_DIR": os.path.join(self.tmp, "other")}))   # 別の置き場所には無い
        for bad in ({"schema": "x"}, dict(rec, dir=os.path.join(self.tmp, "else")), dict(rec, files=["../../x"]), [1]):
            with open(os.path.join(rec_dir, txindex.pack_key(d)), "w", encoding="utf-8") as f:
                _json.dump(bad, f)
            self.assertIsNone(txindex.pack_info(self.clip, env), bad)
        self.assertNotEqual(txindex.pack_key(d), txindex.pack_key(d + "2"))

    def doc(self, tid, source="", clip=None, updated=1, segs=None, speakers=None):
        d = {"id": tid, "title": "t" + tid, "sourcePath": source, "updatedAt": updated, "speakers": speakers or [],
             "segments": segs if segs is not None else [{"id": "s1", "start": 1.0, "end": 2.5, "text": "こんにちは", "proofed": True},
                                                        {"id": "s2", "start": 3.0, "end": 4.0, "text": "切る", "cutState": "cut"}]}
        if clip:
            d["clip"] = clip
        with open(os.path.join(self.dir, tid + ".json"), "w", encoding="utf-8") as f:
            json.dump(d, f, ensure_ascii=False)

    def clipobj(self, vid=None, mid="m1", start=100.0, actual=None):
        ex = {"mode": "fast"}
        if actual is not None:
            ex["actualStart"] = actual
        return schemas.build_clip(self.clip, 30, {"kind": "youtube", "videoId": vid or self.VID}, (start, start + 30), {"id": mid}, ex, {"name": "t"})

    def test_load_parse_and_skip_broken(self):
        self.doc("aaaaaaaaaaaa", self.clip, speakers=[{"id": "S1", "name": "話者A"}],
                 segs=[{"start": 1, "end": 2, "text": "x", "speaker": "S1"}, {"start": -1, "end": 2, "text": "負"}, {"start": 3, "end": 2}, "壊れた行"])
        with open(os.path.join(self.dir, "bbbbbbbbbbbb.json"), "w", encoding="utf-8") as f:
            f.write("{壊れた")
        with open(os.path.join(self.dir, "notatranscript.json"), "w", encoding="utf-8") as f:
            f.write("{}")   # 名前の長さが違うものは読まない
        docs = txindex.load(self.dir)
        self.assertEqual([d["id"] for d in docs], ["aaaaaaaaaaaa"])
        self.assertEqual([(s["text"], s["speaker"]) for s in docs[0]["segments"]], [("x", "話者A")])
        self.assertEqual(txindex.load(os.path.join(self.tmp, "無い")), [])

    def test_cache_rereads_changed_files_and_forgets_removed(self):
        self.doc("aaaaaaaaaaaa", self.clip)
        first = txindex.load(self.dir)[0]
        self.assertIs(txindex.load(self.dir)[0], first)   # 変わっていなければ読み直さない
        self.doc("aaaaaaaaaaaa", self.clip, segs=[{"start": 0, "end": 1, "text": "新しい行が長くなった"}])
        p = os.path.join(self.dir, "aaaaaaaaaaaa.json")
        os.utime(p, ns=(time.time_ns(), time.time_ns() + 10 ** 9))
        self.assertEqual(txindex.load(self.dir)[0]["segments"][0]["text"], "新しい行が長くなった")
        os.remove(p)
        self.assertEqual(txindex.load(self.dir), [])
        self.assertFalse(any(k == p for k in txindex._cache))

    def test_match_by_path_or_clip_and_newest_wins(self):
        self.doc("aaaaaaaaaaaa", self.clip, updated=1)
        self.doc("bbbbbbbbbbbb", os.path.join(self.tmp, "moved.mp4"), clip=self.clipobj(), updated=5)   # 動画を動かしても .clip.json で
        self.doc("cccccccccccc", os.path.join(self.tmp, "moved.mp4"), clip=self.clipobj(mid="m9"), updated=9)   # 別のマーク
        docs = txindex.load(self.dir)
        best, n, ids = txindex.pick(docs, self.VID, "m1", self.clip)
        self.assertEqual((best["id"], n, sorted(ids)), ("bbbbbbbbbbbb", 2, ["aaaaaaaaaaaa", "bbbbbbbbbbbb"]))
        self.assertEqual(txindex.pick(docs, "zzzzzzzzzzz", "m1", "")[:2], (None, 0))
        self.assertEqual(txindex.summary(best), {"id": "bbbbbbbbbbbb", "title": "tbbbbbbbbbbbb", "segments": 2, "proofed": 1, "cut": 1, "updatedAt": 5})

    def test_match_by_path_before_normalize30(self):
        """2026-10-04 Q1: 「編集」が 30fps の写しへ付け替えた文書は、付け替える前のパス(relinks の why normalize30)でも見つかる"""
        p = os.path.join(self.dir, "aaaaaaaaaaaa.json")
        self.doc("aaaaaaaaaaaa", self.clip.replace(".mp4", "_30fps.mp4"))
        with open(p, encoding="utf-8") as f:
            d = json.load(f)
        d["relinks"] = [{"from": self.clip, "at": 1, "why": "normalize30"}, {"from": os.path.join(self.tmp, "other.mp4"), "at": 2}]
        with open(p, "w", encoding="utf-8") as f:
            json.dump(d, f, ensure_ascii=False)
        os.utime(p, ns=(time.time_ns(), time.time_ns() + 10 ** 9))
        docs = txindex.load(self.dir)
        self.assertEqual(txindex.pick(docs, "", "", self.clip)[1], 1)
        self.assertEqual(txindex.pick(docs, "", "", self.clip.replace(".mp4", "_30fps.mp4"))[1], 1)
        self.assertEqual(txindex.pick(docs, "", "", os.path.join(self.tmp, "other.mp4"))[1], 0)   # 選び直しの前のパス(why なし)は数えない

    def test_match_without_load(self):
        """load を通らずに作った文書(紐づけ用の _paths が無い)も同じ規則で紐づく"""
        doc = {"id": "x", "sourcePath": self.clip, "aliases": [], "clip": None, "updatedAt": 1}
        self.assertTrue(txindex.matches(doc, "", "", self.clip))
        self.assertEqual(txindex.pick([doc], "", "", os.path.join(os.path.dirname(self.clip), ".", "01_a.mp4"))[1], 1)
        self.assertFalse(txindex.matches(doc, "", "", os.path.join(self.tmp, "else.mp4")))
        loaded = dict(doc, _paths=frozenset())   # load の文書は読んだときに求めた _paths を使う
        self.assertFalse(txindex.matches(loaded, "", "", self.clip))

    def test_offset_sources(self):
        self.doc("aaaaaaaaaaaa", self.clip, clip=self.clipobj(start=100.0, actual=98.5))
        self.doc("bbbbbbbbbbbb", self.clip, clip=self.clipobj(vid="zzzzzzzzzzz", start=500.0))   # 別の配信の .clip.json は使わない
        self.doc("cccccccccccc", self.clip)
        d = {x["id"]: x for x in txindex.load(self.dir)}
        self.assertEqual(txindex.offset(d["aaaaaaaaaaaa"], self.VID, self.clip, 10), (98.5, "clip"))   # export.actualStart を優先
        self.assertEqual(txindex.offset(d["bbbbbbbbbbbb"], self.VID, self.clip, 10), (10.0, "mark"))
        self.assertEqual(txindex.offset(d["cccccccccccc"], self.VID, self.clip, 10), (10.0, "mark"))
        fsio.write_json(schemas.clip_path_for(self.clip), self.clipobj(start=200.0))   # mp4 の隣の .clip.json
        self.assertEqual(txindex.offset(d["cccccccccccc"], self.VID, self.clip, 10), (200.0, "sidecar"))
        with mock.patch.object(schemas, "load_clip_file", side_effect=AssertionError("触らない")):
            self.assertEqual(txindex.offset(d["cccccccccccc"], self.VID, r"\\server\share\a.mp4", 7), (7.0, "mark"))
        ln = txindex.lines(d["aaaaaaaaaaaa"], 98.5)
        self.assertEqual([(x["start"], x["end"], x["proofed"], x["cut"]) for x in ln], [(99.5, 101.0, True, False), (101.5, 102.5, False, True)])
        self.assertEqual(d["aaaaaaaaaaaa"]["segments"][0]["start"], 1.0)   # キャッシュの中身は変えない

    def test_key_state(self):
        """成果物の鍵の状態(読むだけ。RS6 b-K2): 文書の transcribe の鍵・既定のパックの鍵を、切り抜きの素性と文書の更新で比べる"""
        from flow import keys
        from ytt import workdata
        tid = "aaaaaaaaaaaa"
        with mock.patch.object(workdata, "TX_DIR", self.dir):
            self.assertEqual(txindex.key_state(self.clip, docs=[]), {"transcribe": "none", "pack": "none"})
            self.assertEqual(txindex.key_state("", docs=[]), {"transcribe": "none", "pack": "none"})
            self.doc(tid, self.clip, updated=1)
            docs = txindex.load(self.dir)
            self.assertEqual(txindex.key_state(self.clip, docs), {"transcribe": "none", "pack": "none"})   # 鍵なし(今までの成果物)
            run = {"engine": "faster-whisper", "engineVersion": "1", "model": "small", "language": "ja", "settings": {"beam": 5, "vadMode": "weak", "boost": False}}
            keys.write_after_transcribe(tid, {"sourcePath": self.clip, "whole": True}, run)
            keys.write_pack(str(keys._pack.default_out_dir(self.clip)), {"video": self.clip, "keeps": [[0, 1]]}, {"textplus": True})
            self.assertEqual(txindex.key_state(self.clip, docs), {"transcribe": "same", "pack": "same"})
            self.doc(tid, self.clip, updated=4102444800000)   # 文書をパックの後に直した = 字幕が新しい
            self.assertEqual(txindex.key_state(self.clip, txindex.load(self.dir)), {"transcribe": "same", "pack": "differ"})
            keys.write_export(self.clip, schemas.media_identity("archive", videoId=self.VID), 1, 9, {})   # 切り抜きを書き出し直した
            self.assertEqual(txindex.key_state(self.clip, txindex.load(self.dir))["transcribe"], "differ")

    def test_folder_follows_transcribe_rules(self):
        self.assertEqual(txindex.folder("/r", {"TRANSCRIBE_DATA_DIR": "/d"}), os.path.join(os.path.abspath("/d"), "transcripts"))
        self.assertEqual(txindex.folder("/r", {"YTT_DATA_DIR": "inplace"}), os.path.join(os.path.abspath("/r/editor"), "transcripts"))
        self.assertEqual(txindex.folder("/r", {"YTT_DATA_DIR": "/x"}), os.path.join(os.path.abspath("/x"), "transcribe", "transcripts"))

    def test_registered_dirs_are_read_by_other_tools(self):
        """起動したツールが登録した場所(datadir.register)を、同じプロセスの他のツールが読む(env を渡したテストは見ない)"""
        self.addCleanup(datadir.register, "transcribe", None)
        self.addCleanup(datadir.register, "cut2resolve", None)
        datadir.register("transcribe", "/tx")
        datadir.register("cut2resolve", os.path.abspath("/c2r"))
        self.assertEqual(datadir.registered("cut2resolve"), os.path.abspath("/c2r"))
        self.assertEqual(txindex.folder("/r"), os.path.join(os.path.abspath("/tx"), "transcripts"))
        self.assertEqual(txindex.packs_dir(), os.path.join(os.path.abspath("/c2r"), "packs"))
        self.assertEqual(txindex.packs_dir(c2r_dir="/other"), os.path.join(os.path.abspath("/c2r"), "packs"))   # 登録が先(以前と同じ)
        self.assertEqual(txindex.folder("/r", {"YTT_DATA_DIR": "inplace"}), os.path.join(os.path.abspath("/r/editor"), "transcripts"))
        self.assertEqual(txindex.packs_dir({"YTT_DATA_DIR": "inplace"}, "/other"), os.path.join(os.path.abspath("/other"), "packs"))
        datadir.register("cut2resolve", None)
        self.assertIsNone(datadir.registered("cut2resolve"))


class TestColors(unittest.TestCase):
    """配信者の名前 → メンバーカラー(ytt/colors.py。git の履歴(679ff01 以前)の docs/archive/followup-2026-09-27.md の 4)"""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="ytt-colors-")
        self.members = os.path.join(self.tmp, "members.json")
        with open(self.members, "w", encoding="utf-8") as f:
            json.dump({"version": 1, "groups": [
                {"id": "g0", "name": "0期生", "members": [{"id": "sakura-miko", "name": "さくらみこ", "en": "Sakura Miko", "hex": "#ff8fdf"},
                                                         {"id": "hoshimachi-suisei", "name": "星街すいせい", "en": "Hoshimachi Suisei", "hex": "#0078D7"}]},
                {"id": "g3", "name": "3期生", "members": [{"id": "usada-pekora", "name": "兎田ぺこら", "en": "Usada Pekora", "hex": "#7EC2FE"},
                                                         {"id": "shiranui-flare", "name": "不知火フレア", "en": "Shiranui Flare", "hex": "#FF5C33"},
                                                         {"id": "bad", "name": "壊れた色", "hex": "red"}]}]}, f, ensure_ascii=False)
        self.mine = os.path.join(self.tmp, "my-colors.json")
        self.env = {"YTT_DATA_DIR": "inplace", colors.MEMBERS_ENV: self.members}

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def entries(self, mine=True, fixed=""):
        return colors.load(self.env, mine=self.mine if mine else "", member_colors=fixed)

    def test_from_channel(self):
        """配信のチャンネル名から(気が利く画面へ 段5): 正式な名前か英語名(4文字以上)が含まれ、1人に決まるときだけ"""
        entries = [{"name": "兎田ぺこら", "en": "Usada Pekora", "id": "usada-pekora", "hex": "#7EC2FE", "group": "3期生", "mine": False},
                   {"name": "星街すいせい", "en": "Hoshimachi Suisei", "id": "hoshimachi-suisei", "hex": "#0ACAFF", "group": "0期生", "mine": False},
                   {"name": "AZKi", "en": "AZKi", "id": "azki", "hex": "#E0327D", "group": "0期生", "mine": False},
                   {"name": "兎田ぺこら", "en": "", "id": "", "hex": "#000000", "group": "マイカラー", "mine": True}]
        f = lambda ch: (colors.from_channel(ch, entries=entries) or {}).get("name")   # noqa: E731
        self.assertEqual(f("Pekora Ch. 兎田ぺこら"), "兎田ぺこら")
        self.assertEqual(f("Hoshimachi Suisei Ch."), "星街すいせい")      # 英語名がそのまま含まれる
        self.assertIsNone(f("Suisei Channel"))                            # 英語名の一部だけでは決めない
        self.assertEqual(f("AZKi Channel"), "AZKi")
        self.assertIsNone(f("ぺこら と すいせい の 兎田ぺこら 星街すいせい"))   # 2人に当たる = 決めない
        self.assertIsNone(f(""))
        self.assertIsNone(f("ホロライブ公式"))

    def test_lookup_rules(self):
        es = self.entries(mine=False)
        self.assertEqual([e["name"] for e in es], ["さくらみこ", "星街すいせい", "兎田ぺこら", "不知火フレア"])   # 形の違う色は飛ばす
        for q in ("さくらみこ", "サクラミコ", "ｻｸﾗﾐｺ", "sakura miko", "SAKURA-MIKO", " さくら・みこ "):
            self.assertEqual(colors.lookup(q, es)["match"]["hex"], "#FF8FDF", q)      # かな・全角半角・大小・空白と区切りを区別しない
        self.assertEqual(colors.lookup("ぺこら", es)["match"]["name"], "兎田ぺこら")    # 名前の一部で1人に決まる
        self.assertEqual(colors.lookup("pekora", es)["match"]["name"], "兎田ぺこら")    # ローマ字の一部(3文字から)
        r = colors.lookup("ら", es)
        self.assertIsNone(r["match"])                                                 # 2人以上なら決めない
        self.assertEqual({e["name"] for e in r["candidates"]}, {"さくらみこ", "兎田ぺこら"})              # 漢字はかなと見なさない(不知火)
        self.assertEqual(colors.lookup("", es), {"match": None, "candidates": []})

    def test_my_colors_come_first_and_resolve(self):
        with open(self.mine, "w", encoding="utf-8") as f:
            json.dump({"version": 1, "colors": [{"id": "x", "name": "さくらみこ", "hex": "#123456"}, {"name": "", "hex": "#000000"}]}, f)
        es = self.entries()
        self.assertEqual((es[0]["group"], es[0]["mine"], len(es)), ("マイカラー", True, 5))
        self.assertEqual(colors.resolve("みこ", entries=es), ("さくらみこ", "#123456"))      # 同じ名前ならマイカラーが先
        self.assertEqual(colors.resolve("  ", entries=es), (None, None))                   # 空 = 今までどおり(黒い文字)
        with self.assertRaisesRegex(ValueError, "複数"):
            colors.resolve("ら", entries=es)
        with self.assertRaisesRegex(ValueError, "見つかりません"):
            colors.resolve("存在しない人", entries=es)
        with self.assertRaisesRegex(ValueError, "長すぎ"):
            colors.resolve("あ" * 61, entries=es)
        self.assertEqual(colors.load({"YTT_DATA_DIR": "inplace", colors.MEMBERS_ENV: os.path.join(self.tmp, "無い.json")}), [])   # 読めなくても落ちない
        self.assertIsNone(colors.mine_path({"YTT_DATA_DIR": "inplace"}))                   # テスト(inplace)では本物のマイカラーを読まない

    def test_member_colors_and_fixed_colors(self):
        """members.json の colors(version 2)と、ホロカラーで直した色(member-colors.json)。字幕の色 = 主な色(段7 の 7-7)"""
        with open(self.members, encoding="utf-8") as f:
            d = json.load(f)
        miko = d["groups"][0]["members"][0]
        miko["colors"] = [{"hex": "#FE4B74", "label": "公式サイトの画像"}, {"hex": "red"}, 5, {"hex": "#ff8fdf", "label": "ホロジュール"},
                          {"hex": "#FE4B74"}, {"hex": "#123456", "label": "とても長いラベルの名前ですよね"}]
        with open(self.members, "w", encoding="utf-8") as f:
            json.dump(d, f, ensure_ascii=False)
        es = {e["id"]: e for e in self.entries(mine=False)}
        m = es["sakura-miko"]
        self.assertEqual(m["hex"], "#FF8FDF")                                                    # 主な色は hex(colors の順番ではない)
        self.assertEqual([c["hex"] for c in m["colors"]], ["#FF8FDF", "#FE4B74", "#123456"])     # hex を先頭へ・形の違う色と重なりは捨てる
        self.assertEqual(m["colors"][2]["label"], "とても長いラベルの名前で")                      # ラベルは 12 文字まで
        self.assertEqual(es["usada-pekora"]["colors"], [{"hex": "#7EC2FE", "label": ""}])       # colors の無い古い形は hex の1色
        self.assertFalse(m["custom"])

        fixed = os.path.join(self.tmp, "member-colors.json")
        with open(fixed, "w", encoding="utf-8") as f:
            json.dump({"version": 1, "members": {"sakura-miko": {"colors": [{"hex": "#fe4b74", "label": "公式"}, {"hex": "#FF8FDF"}]},
                                                 "usada-pekora": {"colors": [{"hex": "bad"}]}, "gone": {"colors": [{"hex": "#000000"}]}, "x": 5}}, f)
        es = self.entries(mine=False, fixed=fixed)
        by = {e["id"]: e for e in es}
        self.assertEqual((by["sakura-miko"]["hex"], by["sakura-miko"]["custom"]), ("#FE4B74", True))   # 直した主な色が字幕の色
        self.assertEqual(by["usada-pekora"]["hex"], "#7EC2FE")                                           # 形の違う直した色は使わない
        self.assertEqual(colors.resolve("みこ", entries=es), ("さくらみこ", "#FE4B74"))
        self.assertEqual(colors.speaker_colors(["さくらみこ"], entries=es)[0], {"さくらみこ": "#FE4B74"})
        self.assertNotIn("gone", by)                                                                     # members.json に無い id は使わない

        miko["subtitle"] = "#fe4b74"                                                                     # 字幕の既定の色(subtitle。2026-10-05)
        d["groups"][0]["members"][1]["subtitle"] = "#5683c8"
        d["groups"][1]["members"][0]["subtitle"] = "bad"
        with open(self.members, "w", encoding="utf-8") as f:
            json.dump(d, f, ensure_ascii=False)
        es = {e["id"]: e for e in self.entries(mine=False)}
        self.assertEqual([c["hex"] for c in es["sakura-miko"]["colors"]], ["#FE4B74", "#FF8FDF", "#123456"])   # subtitle が字幕の色(先頭)
        self.assertEqual(es["hoshimachi-suisei"]["colors"][0], {"hex": "#5683C8", "label": "字幕"})             # 一覧に無い色は先頭に足す
        self.assertEqual(es["usada-pekora"]["hex"], "#7EC2FE")                                                    # 形の違う subtitle は hex
        by = {e["id"]: e for e in self.entries(mine=False, fixed=fixed)}
        self.assertEqual(by["sakura-miko"]["hex"], "#FE4B74")                                                     # 直した色は subtitle より先
        with open(fixed, "w", encoding="utf-8") as f:
            json.dump({"version": 1, "members": {"hoshimachi-suisei": {"colors": [{"hex": "#49E0F4"}]}}}, f)
        self.assertEqual({e["id"]: e["hex"] for e in self.entries(mine=False, fixed=fixed)}["hoshimachi-suisei"], "#49E0F4")
        with open(fixed, "w", encoding="utf-8") as f:
            f.write('{"members": {"sakura-miko": ')                                                       # 壊れていても落ちない
        self.assertEqual({e["id"]: e["hex"] for e in self.entries(mine=False, fixed=fixed)}["sakura-miko"], "#FE4B74")   # = subtitle
        self.assertIsNone(colors.member_colors_path({"YTT_DATA_DIR": "inplace"}))                        # テスト(inplace)では本物の直した色を読まない
        self.assertEqual(colors.member_colors_path({"YTT_DATA_DIR": self.tmp}), os.path.join(os.path.abspath(self.tmp), "holo-colors", "member-colors.json"))

    def test_hex(self):
        self.assertEqual(colors.norm_hex("ff8fdf"), "#FF8FDF")
        self.assertIsNone(colors.norm_hex("#ff8fd"))

    def test_repo_members_json_is_readable(self):
        es = colors.load({"YTT_DATA_DIR": "inplace"})                                     # リポジトリの holo-colors/members.json
        self.assertGreater(len(es), 50)
        self.assertTrue(all(colors.norm_hex(e["hex"]) == e["hex"] for e in es))
        with open(colors.members_path({}), encoding="utf-8") as f:                         # version 2 の形(docs/design/holo-colors.md)
            d = json.load(f)
        self.assertEqual(d["version"], 2)
        ids = [m["id"] for g in d["groups"] for m in g["members"]]
        self.assertEqual(len(ids), len(set(ids)), "メンバーの id は全体で一意(直した色のキー)")
        known = {s["id"] for s in d["sources"]}
        for g in d["groups"]:
            for m in g["members"]:
                cs = m.get("colors")
                self.assertTrue(cs, m["name"])
                self.assertEqual(colors.norm_hex(cs[0]["hex"]), colors.norm_hex(m["hex"]), "colors の先頭 = hex: " + m["name"])
                for c in cs:
                    self.assertTrue(colors.norm_hex(c["hex"]), m["name"])
                    self.assertLessEqual(len(c.get("label", "")), colors.LABEL_MAX, m["name"])
                    self.assertIn(c.get("confidence"), ("high", "medium", "low"), m["name"])
                    self.assertTrue(set(c.get("src", [])) <= known, "知らない出典: %s %s" % (m["name"], c.get("src")))
                self.assertTrue(set(m.get("src", [])) <= known, "知らない出典: %s" % m["name"])
                if "subtitle" in m:
                    self.assertTrue(colors.norm_hex(m["subtitle"]), "subtitle の形: " + m["name"])


class TestPick(unittest.TestCase):
    """参照…の窓(ytt/pick.py。2026-10-01)。subprocess.run を差し替えるので本物の窓は開かない"""

    def run_result(self, stdout=b"", returncode=0, stderr=b""):
        return mock.Mock(returncode=returncode, stdout=stdout, stderr=stderr)

    def test_returns_normalized_path(self):
        out = json.dumps({"path": "C:/動画/a/../clip.mp4"}).encode("utf-8")
        with mock.patch.object(pick.subprocess, "run", return_value=self.run_result(out)) as run:
            p = pick.pick("file", "動画を選ぶ", "", (".mp4",))
        self.assertEqual(p, os.path.normpath("C:/動画/clip.mp4"))
        arg = json.loads(run.call_args[0][0][-1])           # 窓のスクリプトへ渡した引数
        self.assertEqual((arg["kind"], arg["title"]), ("file", "動画を選ぶ"))
        self.assertEqual(arg["types"][-1], ["すべてのファイル", "*.*"])
        self.assertEqual(run.call_args[1]["timeout"], pick.TIMEOUT)

    def test_kind_other_than_dir_is_file(self):
        with mock.patch.object(pick.subprocess, "run", return_value=self.run_result(b'{"path": ""}')) as run:
            pick.pick("なんでも")
            self.assertEqual(json.loads(run.call_args[0][0][-1])["kind"], "file")
            pick.pick("dir")
            self.assertEqual(json.loads(run.call_args[0][0][-1])["kind"], "dir")

    def test_cancel_is_empty_string(self):
        for out in (b'{"path": ""}', b"{}", b""):
            with mock.patch.object(pick.subprocess, "run", return_value=self.run_result(out)):
                self.assertEqual(pick.pick("file"), "", out)

    def test_nonzero_returncode_is_pick_error(self):
        err = "Traceback\nModuleNotFoundError: No module named 'tkinter'\n".encode("utf-8")
        with mock.patch.object(pick.subprocess, "run", return_value=self.run_result(returncode=1, stderr=err)):
            with self.assertRaises(pick.PickError) as c:
                pick.pick("file")
        self.assertIn("tkinter", str(c.exception))          # 最後の行を理由に出す
        with mock.patch.object(pick.subprocess, "run", return_value=self.run_result(returncode=3)):
            with self.assertRaises(pick.PickError) as c:
                pick.pick("file")
        self.assertIn("returncode 3", str(c.exception))

    def test_unreadable_output_and_oserror_are_pick_error(self):
        with mock.patch.object(pick.subprocess, "run", return_value=self.run_result(b"not json")):
            with self.assertRaises(pick.PickError):
                pick.pick("file")
        with mock.patch.object(pick.subprocess, "run", side_effect=OSError("起動できない")):
            with self.assertRaises(pick.PickError):
                pick.pick("file")

    def test_timeout_is_cancel_and_releases_lock(self):
        with mock.patch.object(pick.subprocess, "run", side_effect=pick.subprocess.TimeoutExpired("x", 1)):
            self.assertEqual(pick.pick("file"), "")
        self.assertFalse(pick._lock.locked())               # 放っておかれて閉じたあとも、次の窓を開ける

    def test_second_call_while_open_is_busy(self):
        seen = []

        def inner_run(*a, **k):
            try:
                pick.pick("file")                           # 窓が開いている間の2回目
            except pick.PickBusy as e:
                seen.append(e)
            return self.run_result(b'{"path": ""}')

        with mock.patch.object(pick.subprocess, "run", side_effect=inner_run):
            self.assertEqual(pick.pick("file"), "")
        self.assertEqual(len(seen), 1)
        self.assertFalse(pick._lock.locked())               # 終わったら次を受け付ける
        with pick._lock:                                    # 別のスレッドが持っている間も同じ
            with self.assertRaises(pick.PickBusy):
                pick.pick("dir")

    def test_types(self):
        self.assertEqual(pick._types((".MP4", ".wav", ".mp4", "mp3", None, 5)),
                         [["動画・音声", "*.mp4 *.wav"], ["すべてのファイル", "*.*"]])
        self.assertEqual(pick._types(()), [["すべてのファイル", "*.*"]])
        self.assertEqual(pick._types(None), [["すべてのファイル", "*.*"]])

    def test_initial_dir(self):
        with tempfile.TemporaryDirectory() as d:
            sub = os.path.join(d, "a")
            os.makedirs(sub)
            self.assertEqual(pick.initial_dir(sub), os.path.abspath(sub))
            # 存在しないファイル・フォルダは、存在するいちばん近い上のフォルダ
            self.assertEqual(pick.initial_dir(os.path.join(sub, "消えた", "x", "clip.mp4")), os.path.abspath(sub))
            self.assertEqual(pick.initial_dir('"%s"' % os.path.join(sub, "clip.mp4")), os.path.abspath(sub))   # 「パスとしてコピー」の "
            f = os.path.join(sub, "実在.mp4")
            with open(f, "wb") as fh:
                fh.write(b"x")
            self.assertEqual(pick.initial_dir(f), os.path.abspath(sub))   # ファイルならその入っているフォルダ
            self.assertEqual(pick.initial_dir(os.path.join(sub, "a\0b.mp4")), "")   # NUL を含むパスは上のフォルダへたどらない(以前と同じ)
        for bad in ("", None, "   ", "相対/パス/a.mp4", "clip.mp4"):
            self.assertEqual(pick.initial_dir(bad), "", repr(bad))

    @unittest.skipUnless(os.name == "nt", "Windows のネットワークパス")
    def test_initial_dir_network_path_untouched(self):
        with mock.patch.object(pick.os.path, "isdir") as isdir:
            self.assertEqual(pick.initial_dir("\\\\server\\share\\x\\a.mp4"), "")
            isdir.assert_not_called()                       # 存在の確認もしない(資格情報を送らない)


class TestLoudness(unittest.TestCase):
    """ラウドネスの決まり(ytt/loudness.py。スタジオの書き出し・パック作りが共通で使う)"""

    def test_check_target_and_volume(self):
        from ytt import loudness as L
        self.assertEqual([L.check_target(v) for v in (None, "", 0, "0", -14, "-18")], [None, None, None, None, -14.0, -18.0])
        for bad in (-20, "x", True, -14.5):
            with self.assertRaises(ValueError):
                L.check_target(bad)
        self.assertEqual([L.check_volume(v) for v in (None, "", 100, 70, "150")], [None, None, None, 70, 150])
        for bad in (0, 201, 7.5, True, "x"):
            with self.assertRaises(ValueError):
                L.check_volume(bad)
        self.assertEqual((L.pct_to_db(50), L.pct_to_db(200)), (-6.02, 6.02))

    def test_parse_and_gain(self):
        from ytt import loudness as L
        text = 'x\n{\n "input_i" : "-18.80",\n "input_tp" : "-4.10",\n "input_lra" : "7.9"\n}'
        self.assertEqual(L.parse(text), (-18.8, -4.1))
        self.assertEqual(L.parse('{"input_i" : "-inf", "input_tp" : "-inf"}'), (None, None))   # 無音
        self.assertEqual(L.parse(""), (None, None))
        self.assertEqual(L.gain(-14, -18.8, -4.1), 3.1)            # ピーク(-1 dBTP)で止まる
        self.assertEqual(L.gain(-18, -18.8, -4.1), 0.8)            # 2026-09-29 の実例: 「小さめ」でも元より少し上がる
        self.assertEqual(L.gain(-14, -50, -45), 20.0)              # 上げる量の上限
        self.assertEqual(L.gain(-14, -10, -2), -4.0)               # 下げる
        self.assertEqual(L.gain(-14, -20, -8, -2.0), 1.0)          # ほかのピーク(編集用素材)も見る
        self.assertIn("between(t,1.000,2.500)", L.select_filter([(1, 2.5), (3, 3)]))
        self.assertEqual(L.select_filter([]), "")
        self.assertEqual(L.select_filter([(i, i + 0.5) for i in range(L.MAX_SPANS + 1)]), "")   # 多すぎるときは全体で測る


class TestNames(unittest.TestCase):
    """書き出しの名前の規則(スタジオの exporter と入口の live_export が同じ物を読む。T8)。
    値は 2026-10-09 に一本化する前の両方の実装の出力(名前が 1 バイトでも変わると、前に書き出したフォルダと別になる)"""

    def setUp(self):
        from ytt import names
        self.N = names
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def test_text_rules(self):
        N = self.N
        self.assertEqual([N.compact_ts(t) for t in (0, 59.9, 3725.9, 36000, 359999)], ["00h00m00s", "00h00m59s", "01h02m05s", "10h00m00s", "99h59m59s"])
        self.assertEqual(N.compact_ts(-5), "00h00m00s")   # 負の数は 0(スタジオのマークは 0 以上。ライブは録画の頭より前を 0 に)
        self.assertEqual(N.safe_name('a/b:c*?"<>|%d', 30), "a_b_c_d")
        self.assertEqual(N.safe_name(" ..配信\x01\x1fです.. ", 60), "配信_です")
        self.assertEqual(N.safe_name(None, 10), "")
        self.assertEqual(N.safe_name("あいうえおかきくけこ", 3), "あいう")
        self.assertEqual(N.path_units("a😀"), 3)
        self.assertEqual(N.trim_units("ab😀", 3), "ab")
        self.assertEqual(N.trim_units("ab. c", 4), "ab")
        for name in ("CON", "con.txt", "COM1", "lpt9.mp4", "COM¹", "conin$", "NUL .x", "AUX"):
            self.assertTrue(N.is_reserved(name), name)
        for name in ("CONX", "COM0", "LPT10", "_CON", "配信"):
            self.assertFalse(N.is_reserved(name), name)

    def test_folder_and_owner(self):
        N = self.N
        name, path = N.pick_folder(self.tmp, "配信:1", "abcdefghijk", "abcdefghijk")
        self.assertEqual((name, path), ("配信_1", os.path.join(self.tmp, "配信_1")))
        self.assertEqual(N.read_owner(path), "abcdefghijk")
        self.assertTrue(os.path.isfile(os.path.join(path, schemas.WORK_DIR, ".studio-id")))
        self.assertEqual(N.pick_folder(self.tmp, "配信:1", "abcdefghijk", "x"), (name, path))     # 同じ持ち主は同じフォルダ
        self.assertEqual(N.pick_folder(self.tmp, "配信:1", "zzzzzzzzzzz", "x")[0], "配信_1_2")   # 別の持ち主は連番
        os.makedirs(os.path.join(self.tmp, "手"))                                                  # 印の無いフォルダはその持ち主のもの
        self.assertEqual(N.pick_folder(self.tmp, "手", "yyyyyyyyyyy", "x")[0], "手")
        self.assertEqual(N.read_owner(os.path.join(self.tmp, "手")), "yyyyyyyyyyy")
        self.assertEqual(N.pick_folder(self.tmp, "", "o", "既定")[0], "既定")                     # 題が空なら fallback
        self.assertEqual(N.pick_folder(self.tmp, "com²", "o", "x")[0], "_com²")                    # 予約名は _ を前に
        long_root = os.path.join(self.tmp, "d" * max(1, 170 - N.path_units(self.tmp)))
        os.makedirs(long_root)
        got = N.pick_folder(long_root, "あ" * 80, "o", "x")[0]
        self.assertEqual(got, "あ" * max(8, min(60, N.MAX_PATH_UNITS - N.path_units(long_root) - 5 - N.BASE_ROOM - N.SUFFIX_ROOM)))
        old = os.path.join(self.tmp, "以前")                                                       # 以前の置き方(直下の印)も読む
        os.makedirs(old)
        with open(os.path.join(old, ".studio-id"), "w", encoding="utf-8") as f:
            f.write("old\n")
        self.assertEqual(N.read_owner(old), "old")
        self.assertIsNone(N.read_owner(os.path.join(self.tmp, "無い")))

    def test_clip_names(self):
        N = self.N
        self.assertEqual(N.clip_base(self.tmp, 1, 3725.9, 3790.2, "いい:ところ"), "01_01h02m05s-01h03m10s_いい_ところ")
        self.assertEqual(N.clip_base(self.tmp, 12, 0, 5, ""), "12_00h00m00s-00h00m05s")
        self.assertEqual(N.clip_base(self.tmp, 2, 0, 5, None), "02_00h00m00s-00h00m05s")
        open(os.path.join(self.tmp, "01_00h00m00s-00h00m05s_a.mp4"), "w").close()
        self.assertEqual(N.clip_base(self.tmp, 1, 0, 5, "a"), "01_00h00m00s-00h00m05s_a_2")
        os.makedirs(os.path.join(self.tmp, schemas.WORK_DIR))
        open(os.path.join(self.tmp, schemas.WORK_DIR, "01_x_2_edit.clip.json"), "w").close()   # 作業用/ の <名前>_edit.* も使用中
        open(os.path.join(self.tmp, "01_x.mp4"), "w").close()
        self.assertEqual(N.unique_base("01_x", self.tmp), "01_x_3")
        long_folder = os.path.join(self.tmp, "f" * max(1, 150 - N.path_units(self.tmp)))
        base = N.clip_base(long_folder, 1, 0, 5, "ラベル" * 20)                                     # ラベルはパスの長さに収まる分だけ
        self.assertLessEqual(N.path_units(os.path.join(long_folder, base)) + N.SUFFIX_ROOM + 3, N.MAX_PATH_UNITS)
        self.assertTrue(base.startswith("01_00h00m00s-00h00m05s"))
        p = N.partial_path(self.tmp, "01_x")
        self.assertEqual(os.path.basename(p), "01_x.partial.mp4")
        self.assertTrue(N.is_partial(p))
        self.assertEqual(N.final_path(p), os.path.join(self.tmp, "01_x.mp4"))
        self.assertEqual(N.final_path(os.path.join(self.tmp, "a.mp4")), os.path.join(self.tmp, "a.mp4"))
        self.assertFalse(N.is_partial(None))


class TestRecproto(unittest.TestCase):
    """録画元との約束(録画の部品 rec_core・入口の live_export・配信中の検出のワーカーが同じ物を読む。T8)。
    以前は 3 か所の写しの一致を test_live_detect の SameAsExportTest で確かめていた(その例をここへ移した)"""

    def setUp(self):
        from ytt import recproto
        self.R = recproto

    def test_ids(self):
        R = self.R
        for ok in ("local", "pc-2", "a" * 16):
            self.assertTrue(R.RECORDER_ID_RE.match(ok), ok)
        for bad in ("Local", "2pc", "a" * 17, "a_b", "", "a\n"):
            self.assertFalse(R.RECORDER_ID_RE.match(bad), bad)
        for ok in ("20261009-120000", "20261009-120000-abcdefghijk", "20261009-120000-a1b2c3"):
            self.assertTrue(R.REC_ID_RE.match(ok), ok)
        for bad in ("20261009-12000", "20261009-120000-", "20261009-120000-" + "a" * 25, "../x", "20261009-120000\n"):
            self.assertFalse(R.REC_ID_RE.match(bad), bad)
        self.assertTrue(R.SEG_URI_RE.match("session_001/seg_000000.ts"))
        self.assertFalse(R.SEG_URI_RE.match("session_001/../seg_000000.ts"))
        self.assertEqual(R.SESSION_RE.match("session_012").group(1), "012")
        self.assertTrue(R.SEG_RE.match("seg_000001.ts") and not R.SEG_RE.match("seg_1.ts"))

    def test_time(self):
        R = self.R
        base = 1791549296.0   # 2026-10-09T12:34:56Z
        for s, want in (("2026-10-09T12:34:56Z", base), ("2026-10-09T12:34:56.789Z", base + 0.789), ("2026-10-09T12:34:56+00:00", base),
                        ("2026-10-09T12:34:56.5+00:00", base + 0.5), (" 2026-10-09T12:34:56Z ", base)):
            self.assertAlmostEqual(R.iso_epoch(s), want, places=6, msg=s)
        for s in ("2026-10-09T12:34:56", "2026-10-09T12:34:56.Z", "2026-13-09T12:34:56Z", "x", "", None, 5, "9" * 41, "2026-10-09T12:34:56+09:00"):
            self.assertIsNone(R.iso_epoch(s), s)
        self.assertEqual(R.epoch_iso(0), "1970-01-01T00:00:00.000Z")
        self.assertEqual(R.epoch_iso(base + 0.9999), "2026-10-09T12:34:56.999Z")   # ミリ秒は切り捨て
        self.assertEqual(R.epoch_iso(base + 0.123), "2026-10-09T12:34:56.123Z")
        self.assertAlmostEqual(R.iso_epoch(R.now_iso()), time.time(), delta=2)
        import datetime
        self.assertEqual(R.utc_text(datetime.datetime(2026, 10, 9, 21, 34, 56, 789000, tzinfo=datetime.timezone(datetime.timedelta(hours=9)))),
                         "2026-10-09T12:34:56.789Z")

    def test_video_id(self):
        R, rec = self.R, "20261009-120000-abcdefghijk"
        for url, rid, want in (("https://www.youtube.com/watch?v=abcdefghijk", "", "abcdefghijk"),
                               ("https://www.youtube.com/watch?x=1&v=abcdefghijk&t=3", "", "abcdefghijk"),
                               ("https://youtu.be/abcdefghijk", "", "abcdefghijk"), ("https://youtu.be/abcdefghijk?si=x", "", "abcdefghijk"),
                               ("https://www.youtube.com/live/abcdefghijk", "", "abcdefghijk"),
                               ("https://www.youtube.com/live/abcdefghijk?si=x", "", "abcdefghijk"),
                               ("https://www.youtube.com/watch?v=short", "", ""), ("", rec, "abcdefghijk"),
                               ("https://example.com/", "20261009-120000", ""), ("http://127.0.0.1:9/x.m3u8", rec, "abcdefghijk"),
                               (None, "", ""), ("https://www.youtube.com/watch?v=short", rec, "abcdefghijk"),
                               ("https://www.youtube.com/@x/live", "20261004-000000-ab-defghijk", "ab-defghijk"),
                               ("http://127.0.0.1:1/live.m3u8", "20261004-000000-a1b2c3", ""), ("http://[::1", "", "")):
            self.assertEqual(R.video_id_of(url, rid), want, (url, rid))


if __name__ == "__main__":
    unittest.main()
