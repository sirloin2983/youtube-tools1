# -*- coding: utf-8 -*-
"""入口(src/app/server.py)のテスト。  python -m unittest tests/app/test_launch.py -v

- 偽のツール(serve.py の約束だけをまねた小さなサーバー)で、起動・停止・再起動・異常終了・別の画面で起動済み・
  強制終了・ポートの繰り上げ・入口の画面の安全検査を確かめる
- 本物の3ツール(疑似モード)を一時フォルダに写して、入口から起動・停止できることを確かめる(RealToolsTest)
ポートは OS に空きを選ばせるので、本物のツールが動いている PC でも走らせられる。
"""
import contextlib
import http.client
import io
import json
import os
os.environ.setdefault("YTT_DATA_DIR", "inplace")   # テストは作業データを本物の置き場所(AppData など)に書かない(ytt.datadir)
import shutil
import socket
import sys
import textwrap
import threading
import time
import unittest
import urllib.parse
from unittest import mock

TESTS = os.path.dirname(os.path.abspath(__file__))   # tests/app
HERE = os.path.join(os.path.dirname(os.path.dirname(TESTS)), "src", "app")   # home(入口の部品)
sys.path.insert(0, HERE)
sys.path.insert(0, TESTS)
sys.path.append(os.path.dirname(HERE))   # src(app 層。入口本体は src/app/server.py)
from app import server as L  # noqa: E402
from ytt import layout  # noqa: E402  (launch がリポジトリ直下を sys.path に入れる)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))   # tests/(testkit)
import testkit  # noqa: E402  (launch がリポジトリ直下を sys.path に入れる)

REPO = os.path.dirname(HERE)

# 偽のツール。各ツールの serve.py と同じ約束: `serve.py <開始ポート> --no-open`、使用中なら次の番号、
# .runtime/<ID>.json、/api/ping、SIGTERM/SIGBREAK で .runtime を消して終わる、同じツールが動いていれば「すでに起動しています」で 0 終了
FAKE_SERVE = textwrap.dedent(r'''
    import http.server, json, os, signal, socket, sys, time, urllib.request
    TOOL, APP, VER = %(tool)r, %(app)r, %(ver)r
    here = os.path.dirname(os.path.abspath(__file__))
    mode = open(os.path.join(here, "mode.txt")).read().strip() if os.path.exists(os.path.join(here, "mode.txt")) else "normal"
    rdir = os.environ.get("YTT_RUNTIME_DIR") or os.path.join(os.path.dirname(here), ".runtime")
    start = int([a for a in sys.argv[1:] if not a.startswith("--")][0])
    print("fake %%s start mode=%%s" %% (TOOL, mode), flush=True)
    if mode == "crash_now":
        print("起動に失敗しました(偽)", flush=True)
        sys.exit(2)
    if mode == "slow":
        time.sleep(1.5)

    class H(http.server.BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass
        def do_GET(self):
            body = json.dumps({"app": APP, "version": VER}).encode()
            self.send_response(200 if self.path == "/api/ping" else 404)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    def running(p):
        try:
            with urllib.request.build_opener(urllib.request.ProxyHandler({})).open("http://127.0.0.1:%%d/api/ping" %% p, timeout=0.3) as r:
                return json.load(r).get("app") == APP
        except Exception:
            return False

    srv = None
    for p in range(start, start + 20):
        if running(p):
            print("すでに起動しています", flush=True)
            sys.exit(0)
        try:
            srv = http.server.ThreadingHTTPServer(("127.0.0.1", p), H)
            break
        except OSError:
            continue
    port = srv.server_address[1]
    os.makedirs(rdir, exist_ok=True)
    path = os.path.join(rdir, TOOL + ".json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"tool": TOOL, "port": port, "version": VER, "pid": os.getpid()}, f)

    def stop(*_):
        if mode == "ignore_term":
            print("合図を無視します", flush=True)
            return
        raise KeyboardInterrupt()
    for n in ("SIGTERM", "SIGBREAK"):
        if hasattr(signal, n):
            signal.signal(getattr(signal, n), stop)
    if mode == "crash_later":
        import threading
        threading.Timer(0.8, lambda: os._exit(3)).start()
    print("listening", port, flush=True)
    try:
        srv.serve_forever(poll_interval=0.05)
    except KeyboardInterrupt:
        pass
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass
        print("bye", flush=True)
''')

VERSIONS = {"studio": "0.2.0", "transcribe": "0.2.0", "cut2resolve": "0.2.0"}   # 版は全体で 1 つ(ytt/version.py)なので全ツール同じ


def free_ports(n):
    """連続しない空きポートを n 個(それぞれ +20 まで空いていそうな所)。"""
    out = []
    while len(out) < n:
        s = socket.socket()
        s.bind(("127.0.0.1", 0))
        p = s.getsockname()[1]
        s.close()
        if p + 25 < 65535 and all(abs(p - q) > 25 for q in out):
            out.append(p)
    return out


def make_fake_root(tmp, versions=VERSIONS):
    for spec in L.TOOLS:
        d = os.path.join(tmp, spec["dir"])
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, "serve.py"), "w", encoding="utf-8") as f:
            f.write(FAKE_SERVE % {"tool": spec["id"], "app": spec["app"], "ver": versions[spec["id"]]})
    vpath = os.path.join(tmp, "ytt", "version.py")   # 期待する版(全体の版)はここから読む
    os.makedirs(os.path.dirname(vpath), exist_ok=True)
    with open(vpath, "w", encoding="utf-8") as f:
        f.write('VERSION = "%s"\n' % next(iter(versions.values())))
    return tmp


def set_mode(root, tid, mode):
    spec = [s for s in L.TOOLS if s["id"] == tid][0]
    with open(os.path.join(root, spec["dir"], "mode.txt"), "w") as f:
        f.write(mode)


def wait_for(fn, timeout=15.0, step=0.1):
    return testkit.wait_for(fn, timeout, step)


def _http(port, method, path, body=None, token=None):
    """入口へ 1 回(画面と同じ Host・Origin・Sec-Fetch-Site。POST は合言葉つき)-> (HTTP の番号, 本文)"""
    host = "127.0.0.1:%d" % port
    h = {"Host": host}
    if method == "POST":
        h.update({"Content-Type": "application/json", "Origin": "http://" + host, "Sec-Fetch-Site": "same-origin", "X-YTT-Token": token or ""})
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=30)
    try:
        conn.request(method, path, body=body, headers=h)
        r = conn.getresponse()
        return r.status, r.read()
    finally:
        conn.close()


@contextlib.contextmanager
def patched(patches):
    """mock.patch の並びを順に当てて、抜けるときに逆の順で外す"""
    with contextlib.ExitStack() as stack:
        for p in patches:
            stack.enter_context(p)
        yield


def quiet_logger(sink=None):
    """L.make_logger の代わり(黒い画面へは出さない。sink があれば行をそこへ)"""
    def make_logger(path):
        def log(msg, console=True):
            if sink is not None:
                sink.append(msg)
        log.flush = lambda timeout=1.0: None
        return log
    return make_logger


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = testkit.tempdir(self, "ytt-launch-")
        self.root = make_fake_root(self.tmp)
        self.rdir = os.path.join(self.tmp, ".runtime")
        env = mock.patch.dict(os.environ, {"YTT_RUNTIME_DIR": self.rdir})
        env.start()
        self.addCleanup(env.stop)
        self.ports = dict(zip(L.TOOL_IDS, free_ports(3)))
        self.events = []
        self.sup = L.Supervisor(self.root, ready_timeout=20, stop_timeout=3, poll=0.1, log=self.events.append, ports=self.ports)
        self.extra_procs = []

    def tearDown(self):
        self.sup.close()
        self.sup.stop_all()
        for p in self.extra_procs:
            if p.poll() is None:
                p.kill()
                p.wait(5)

    def state(self, tid):
        return self.sup.by_id[tid].snapshot()["state"]

    def wait_state(self, tid, *states, timeout=15):
        return wait_for(lambda: self.state(tid) in states, timeout)

    def spawn_external(self, tid, port, root=None):
        """入口を通さずに(別の黒い画面で起動したのと同じ)偽のツールを起動する。root: 別のフォルダの serve.py(古い版など)"""
        import subprocess
        p = subprocess.Popen([sys.executable, os.path.join(root or self.root, layout.TOOL_DIRS[tid], "serve.py"), str(port), "--no-open"],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.extra_procs.append(p)
        self.assertTrue(wait_for(lambda: L.ping(port) is not None, 10), "偽のツールが起動しない")
        return p


class SupervisorTest(Base):
    def test_start_all_then_stop_all(self):
        self.sup.start_all()
        self.sup.start_monitor()
        for tid in L.TOOL_IDS:
            self.assertTrue(self.wait_state(tid, "running"), tid)
            snap = self.sup.by_id[tid].snapshot()
            self.assertEqual(snap["port"], self.ports[tid])
            self.assertEqual(snap["version"], VERSIONS[tid])
            self.assertTrue(snap["managed"])
            self.assertTrue(os.path.exists(os.path.join(self.rdir, tid + ".json")))
        procs = [t.proc for t in self.sup.tools]
        self.sup.stop_all()
        for tid in L.TOOL_IDS:
            self.assertEqual(self.state(tid), "stopped")
            self.assertFalse(os.path.exists(os.path.join(self.rdir, tid + ".json")), "子が .runtime を消していない: " + tid)
        for p in procs:
            self.assertIsNotNone(p.poll())
        # 子の出力はログファイルへ
        with open(self.sup.by_id["studio"].log_path, encoding="utf-8") as f:
            text = f.read()
        self.assertIn("ホームから起動", text)
        self.assertIn("listening", text)
        self.assertIn("bye", text)   # SIGTERM(Windows は Ctrl+Break)で正常に後始末して終わった

    def test_restart_replaces_process(self):
        self.sup.start("studio")
        self.sup.start_monitor()
        self.assertTrue(self.wait_state("studio", "running"))
        old = self.sup.by_id["studio"].proc
        self.sup.start("studio")   # 起動中にもう一度押しても2つ目は起動しない
        self.assertIs(self.sup.by_id["studio"].proc, old)
        self.sup.stop("studio")
        self.sup.start("studio")
        self.assertIsNotNone(old.poll(), "古いプロセスが残っている")
        self.assertTrue(self.wait_state("studio", "running"))
        self.assertIsNot(self.sup.by_id["studio"].proc, old)
        self.assertEqual(self.sup.by_id["studio"].snapshot()["starts"], 2)

    def test_crash_is_reported_with_log(self):
        set_mode(self.root, "transcribe", "crash_later")
        self.sup.start("transcribe")
        self.sup.start_monitor()
        self.assertTrue(self.wait_state("transcribe", "crashed"))
        snap = self.sup.by_id["transcribe"].snapshot()
        self.assertEqual(snap["exitCode"], 3)
        self.assertIn("異常終了", snap["message"])
        self.assertIsNone(snap["port"])
        self.assertTrue(any("異常終了" in e and "listening" in e for e in self.events), "黒い画面にログの最後が出ていない")
        # 異常終了で子が消せなかった .runtime は入口が片付ける
        self.assertFalse(os.path.exists(os.path.join(self.rdir, "transcribe.json")))
        # 自動では起動し直さない
        time.sleep(0.5)
        self.assertEqual(self.state("transcribe"), "crashed")
        # 「起動」で起動し直せる
        set_mode(self.root, "transcribe", "normal")
        self.sup.start("transcribe")
        self.assertTrue(self.wait_state("transcribe", "running"))

    def test_immediate_failure(self):
        set_mode(self.root, "cut2resolve", "crash_now")
        self.sup.start("cut2resolve")
        self.sup.start_monitor()
        self.assertTrue(self.wait_state("cut2resolve", "crashed"))
        self.assertEqual(self.sup.by_id["cut2resolve"].snapshot()["exitCode"], 2)
        with open(self.sup.by_id["cut2resolve"].log_path, encoding="utf-8") as f:
            self.assertIn("起動に失敗しました(偽)", f.read())

    def test_external_is_not_started_or_stopped(self):
        ext = self.spawn_external("studio", self.ports["studio"])
        self.sup.start("studio")
        snap = self.sup.by_id["studio"].snapshot()
        self.assertEqual(snap["state"], "external")
        self.assertFalse(snap["managed"])
        self.assertEqual(snap["port"], self.ports["studio"])
        self.assertIsNone(self.sup.by_id["studio"].proc)
        self.sup.stop("studio")
        self.sup.stop_all()
        self.assertIsNone(ext.poll(), "別の画面で起動したツールを止めてしまった")
        self.assertEqual(self.state("studio"), "external")
        # 別の画面のツールが終わったら「停止」になり、入口から起動できる
        self.sup.start_monitor()
        ext.terminate()
        ext.wait(5)
        self.assertTrue(self.wait_state("studio", "stopped", timeout=10))
        self.sup.start("studio")
        self.assertTrue(self.wait_state("studio", "running"))
        self.assertTrue(self.sup.by_id["studio"].snapshot()["managed"])

    def test_external_found_via_runtime_file_on_other_port(self):
        other = free_ports(1)[0]
        self.spawn_external("transcribe", other)   # 既定のポートが使用中で、次の番号などで動いている
        self.sup.start("transcribe")
        snap = self.sup.by_id["transcribe"].snapshot()
        self.assertEqual((snap["state"], snap["port"]), ("external", other))

    def test_old_version_external_warns(self):
        # フォルダの中は 0.2.0 だが、動いているのは古い版
        with open(os.path.join(self.root, layout.TOOL_DIRS["studio"], "serve.py"), encoding="utf-8") as f:
            src = f.read()
        testkit.write_text(os.path.join(self.tmp, "old", layout.TOOL_DIRS["studio"], "serve.py"), src.replace("'0.2.0'", "'0.1.8'"))
        self.spawn_external("studio", self.ports["studio"], root=os.path.join(self.tmp, "old"))
        self.sup.start("studio")
        snap = self.sup.by_id["studio"].snapshot()
        self.assertEqual(snap["state"], "external")
        self.assertEqual(snap["version"], "0.1.8")
        self.assertEqual(snap["expectedVersion"], "0.2.0")
        self.assertIn("古い版", snap["message"])

    def test_force_kill_when_signal_ignored(self):
        set_mode(self.root, "studio", "ignore_term")
        self.sup.stop_timeout = 1
        self.sup.start("studio")
        self.sup.start_monitor()
        self.assertTrue(self.wait_state("studio", "running"))
        proc = self.sup.by_id["studio"].proc
        t0 = time.time()
        self.sup.stop("studio")
        self.assertLess(time.time() - t0, 8)
        self.assertIsNotNone(proc.poll())
        self.assertEqual(self.state("studio"), "stopped")
        self.assertTrue(any("強制終了" in e for e in self.events))
        # 強制終了で子が消せなかった .runtime は入口が片付ける
        self.assertFalse(os.path.exists(os.path.join(self.rdir, "studio.json")))

    def test_port_in_use_moves_to_next(self):
        blocker = socket.socket()
        blocker.bind(("127.0.0.1", self.ports["cut2resolve"]))
        blocker.listen(1)
        try:
            self.sup.start("cut2resolve")
            self.sup.start_monitor()
            self.assertTrue(self.wait_state("cut2resolve", "running"))
            self.assertEqual(self.sup.by_id["cut2resolve"].snapshot()["port"], self.ports["cut2resolve"] + 1)
        finally:
            blocker.close()

    def test_stale_runtime_file_is_not_trusted(self):
        # 前回の記録(古い更新時刻)が、今たまたま別のスタジオが応答するポートを指していても、それを「今回の子」と思わない
        other = free_ports(1)[0]
        with mock.patch.dict(os.environ, {"YTT_RUNTIME_DIR": os.path.join(self.tmp, "elsewhere")}):
            self.spawn_external("studio", other)   # 記録は別の置き場に書く(入口からは .runtime では見えない)
        set_mode(self.root, "studio", "slow")   # 子が自分の記録を書くまで少しかかる
        self.sup.start("studio")
        self.assertEqual(self.state("studio"), "starting")
        path = testkit.write_json(os.path.join(self.rdir, "studio.json"), {"tool": "studio", "port": other, "version": "0.2.0"})
        old = time.time() - 3600
        os.utime(path, (old, old))
        self.sup.start_monitor()
        time.sleep(0.6)
        self.assertEqual(self.state("studio"), "starting", "古い記録のポートを今回の子と取り違えた")
        self.assertTrue(self.wait_state("studio", "running"))
        self.assertEqual(self.sup.by_id["studio"].snapshot()["port"], self.ports["studio"])
        # 範囲外のポートを書いた記録も信用しない
        testkit.write_json(path, {"tool": "studio", "port": 1, "version": "x"})
        self.assertIsNone(L.read_runtime(self.rdir, "studio"))

    def test_missing_folder(self):
        os.unlink(os.path.join(self.root, "cut2resolve", "serve.py"))
        self.sup.start("cut2resolve")
        snap = self.sup.by_id["cut2resolve"].snapshot()
        self.assertEqual(snap["state"], "missing")
        self.assertIn("serve.py", snap["message"])

    def test_child_says_already_running(self):
        # 入口の確認の直後に別の画面で起動された → 子は「すでに起動しています」で 0 終了 → 別の画面で起動済みとして扱う
        port = self.ports["transcribe"]
        with mock.patch.object(self.sup, "_find_external", side_effect=[None, (port, "0.10.0")]):
            self.spawn_external("transcribe", port)
            self.sup.start("transcribe")
            self.sup.start_monitor()
            self.assertTrue(self.wait_state("transcribe", "external"))
        self.assertIsNone(self.sup.by_id["transcribe"].proc)

    def test_only(self):
        sup = L.Supervisor(self.root, only=["studio", "cut2resolve"], ports=self.ports)
        self.assertEqual([t.id for t in sup.tools], ["studio", "cut2resolve"])


class HelpersTest(unittest.TestCase):
    def setUp(self):
        self.tmp = testkit.tempdir(self, "ytt-launch-h-")

    def test_tail(self):
        p = os.path.join(self.tmp, "a.log")
        with open(p, "wb") as f:
            f.write(b"one\r\ntwo\n\xff\xfebad\nfour\n")
        self.assertEqual(L.tail(p, 10), ["one", "two", "��bad", "four"])
        self.assertEqual(L.tail(p, 2), ["��bad", "four"])
        self.assertIsNone(L.tail(os.path.join(self.tmp, "none.log")))
        with open(p, "wb") as f:
            f.write(b"x" * 100 + b"\n" + "最後の行\n".encode("utf-8"))
        self.assertEqual(L.tail(p, 10, max_bytes=30), ["最後の行"])   # 途中から読んだ欠けた行は捨てる

    def test_read_runtime_validation(self):
        def put(name, raw):
            with open(os.path.join(self.tmp, name + ".json"), "wb") as f:
                f.write(raw)
        put("studio", b'\xef\xbb\xbf{"tool": "studio", "port": 8800, "pid": 12}')   # BOM 付きも読む
        self.assertEqual(L.read_runtime(self.tmp, "studio")["port"], 8800)
        put("studio", b'{"tool": "transcribe", "port": 8800}')
        self.assertIsNone(L.read_runtime(self.tmp, "studio"))
        put("studio", b'{"tool": "studio", "port": 80}')
        self.assertIsNone(L.read_runtime(self.tmp, "studio"))
        put("studio", b'{"tool": "studio", "port": "8800"}')
        self.assertIsNone(L.read_runtime(self.tmp, "studio"))
        put("studio", b'{"tool": "studio", "port": 8800, "pad": "' + b"x" * 5000 + b'"}')
        self.assertIsNone(L.read_runtime(self.tmp, "studio"))
        put("studio", b"[1, 2]")
        self.assertIsNone(L.read_runtime(self.tmp, "studio"))

    def test_parse_args(self):
        self.assertEqual(L.parse_args(["--only", "studio, transcribe"]).only, ["studio", "transcribe"])
        with mock.patch("sys.stderr"):
            with self.assertRaises(SystemExit):
                L.parse_args(["--only", "studio,../x"])
        a = L.parse_args(["--only", "transcribe", "--open-path", "/transcribe/", "--app-window"])
        self.assertEqual((a.open_path, a.app_window), ("/transcribe/", True))
        self.assertEqual((L.parse_args([]).open_path, L.parse_args([]).app_window), ("/", False))
        for bad in ("transcribe/", "/../x", "//evil.example/x", "/a b", "/a?x=1", "/" + "a" * 200):
            with mock.patch("sys.stderr"), self.assertRaises(SystemExit):
                L.parse_args(["--open-path", bad])

    def test_relink_out_dirs_on_start(self):
        """書き出し先を変えたあとの案件の繋ぎ直し(起動のとき)。inplace(テスト)は何もしない・書き出し先は起動のたびに覚える・失敗しても上げない"""
        from types import SimpleNamespace
        tmp = self.tmp
        data = testkit.write_json(os.path.join(tmp, "studio", "data.json"), {"schema": "clip-studio/v1", "videos": {}, "groups": {}})
        srv =SimpleNamespace(sup=SimpleNamespace(root=tmp))
        logs = []
        self.assertIsNone(L.relink_out_dirs(srv, logs.append))   # inplace
        with mock.patch.object(L.datadir, "data_root", return_value=tmp), mock.patch.object(L.placement, "studio_data", return_value=data), \
                mock.patch.object(L.datadir, "studio_out_dir", return_value=os.path.join(tmp, "exports")):
            self.assertEqual(L.relink_out_dirs(srv, logs.append), 0)
            self.assertEqual(L.outdirs_mod.read_state(data)["outDirs"], [os.path.join(tmp, "exports")])
            with mock.patch.object(L.outdirs_mod, "relink_out_dir", side_effect=OSError("y")):
                self.assertIsNone(L.relink_out_dirs(srv, logs.append))
        self.assertTrue(any("繋ぎ直しができませんでした" in x for x in logs))

    def test_logger_does_not_block_when_console_is_stuck(self):
        # Windows の黒い画面で文字を選択している間は表示の書き込みが止まる。そのときも log() はすぐ戻り、ファイルには残る
        release = threading.Event()
        path = os.path.join(self.tmp, "logs", "launcher.log")
        with mock.patch("builtins.print", side_effect=lambda *a, **k: release.wait(10)):
            log = L.make_logger(path)
            t0 = time.time()
            for i in range(5):
                log("行%d" % i)
            self.assertLess(time.time() - t0, 1.0)
            release.set()
            log.flush()
        with open(path, encoding="utf-8") as f:
            self.assertEqual(f.read().count("行"), 5)


class PortalHttpTest(Base):
    """入口の画面とAPI。本物のブラウザが送るヘッダー(Host・Origin・Sec-Fetch-*)で安全検査を確かめる"""

    def setUp(self):
        super().setUp()
        self.srv, self.port = L.make_server(0, self.sup)
        self.th = threading.Thread(target=self.srv.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)   # 止めるのを待たない
        self.th.start()
        self.host = "127.0.0.1:%d" % self.port

    def tearDown(self):
        if not self.srv.closing.is_set():
            self.srv.shutdown()
        self.srv.server_close()
        super().tearDown()

    def req(self, method, path, body=None, headers=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=30)
        h = {"Host": self.host}
        h.update(headers or {})
        conn.request(method, path, body=body, headers=h)
        r = conn.getresponse()
        data = r.read()
        conn.close()
        return r, data

    def post(self, path, headers=None, body=b"{}"):
        h = {"Content-Type": "application/json", "Origin": "http://" + self.host, "Sec-Fetch-Site": "same-origin", "X-YTT-Token": self.srv.token}
        h.update(headers or {})
        return self.req("POST", path, body, h)

    def get_json(self, path, **kw):
        """GET -> (HTTP の番号, 本文の JSON)"""
        r, body = self.req("GET", path, **kw)
        return r.status, json.loads(body)

    def post_json(self, path, obj, **kw):
        """obj を JSON(UTF-8)で POST -> (HTTP の番号, 本文の JSON)"""
        r, body = self.post(path, body=json.dumps(obj, ensure_ascii=False).encode("utf-8"), **kw)
        return r.status, json.loads(body)

    def patch_prefs(self, section, value):
        """入口の設定(api/ytt/prefs)の節 section に value を重ねる -> (HTTP の番号, 本文の JSON)"""
        return self.post_json("/api/ytt/prefs", {"op": "patch", "section": section, "value": value})

    def file_envelope(self):
        """一時フォルダの動画 1 本の封筒(kind file。文字起こしだけにするのは束の run.upto transcribe)-> (動画のパス, 封筒)"""
        media = os.path.join(self.tmp, "切り抜き.mp4")
        with open(media, "wb") as f:
            f.write(b"x")
        return media, {"id": "0123456789", "kind": "file", "input": {"path": media, "title": "切り抜き"}, "specVersion": 2}

    def wait_stops(self, stops):
        """後始末の頼み(request_shutdown)は裏で届くので、届くまで少し待つ"""
        wait_for(lambda: stops, 1.5, 0.05)
        self.assertEqual(stops, [1])

    def test_page_and_headers(self):
        r, body = self.req("GET", "/")
        self.assertEqual(r.status, 200)
        self.assertIn("script-src 'self'", r.getheader("Content-Security-Policy"))
        self.assertIn("frame-ancestors 'none'", r.getheader("Content-Security-Policy"))
        self.assertEqual(r.getheader("X-Frame-Options"), "DENY")
        for path in ("/portal.js", "/portal.css", "/ui-kit.css", "/ui-kit.js", "/settings.js", "/settings.css", "/settings-schema.json"):
            r, body = self.req("GET", path)
            self.assertEqual(r.status, 200, path)
            self.assertEqual(r.getheader("X-Content-Type-Options"), "nosniff")
            self.assertGreater(len(body), 100, path)
        r, body = self.req("GET", "/settings")   # 設定の画面: 入口の画面と同じ CSP・合言葉
        self.assertEqual(r.status, 200)
        self.assertIn("script-src 'self'", r.getheader("Content-Security-Policy"))
        self.assertIn(b'name="ytt-token"', body)
        r, _ = self.req("GET", "/settings/")
        self.assertEqual((r.status, r.getheader("Location")), (302, "/settings"))
        self.assertEqual(self.req("GET", "/server.py")[0].status, 404)   # コードや他のファイルは配らない
        code, st = self.get_json("/api/status", headers={"Sec-Fetch-Site": "same-origin"})   # 入口の画面が読む形
        self.assertEqual((code, st["app"], st["version"]), (200, L.APP_ID, L.VERSION))
        self.assertNotIn("dataDir", st)   # 作業データの置き場所の欄は 10-24 に無くした
        self.assertEqual({t["id"] for t in st["tools"]}, set(L.TOOL_IDS))
        for t in st["tools"]:
            self.assertTrue({"state", "port"} <= set(t), t["id"])

    def test_cases_and_doc_lookup(self):
        """/api/cases?doc= の失敗の答え(一覧の中身は tests/manage/cases/test_cases.py・画面からは e2e_portal)"""
        r, body = self.req("GET", "/api/cases?doc=ffffffffffff")
        self.assertEqual(r.status, 404)
        r, body = self.req("GET", "/api/cases?doc=zz")
        self.assertEqual(r.status, 400)

    def test_host_check(self):
        self.assertEqual(self.req("GET", "/api/status", headers={"Host": "evil.example:%d" % self.port})[0].status, 403)
        self.assertEqual(self.post("/api/cases/auto", headers={"Host": "evil.example"})[0].status, 403)

    def test_cross_site_reads_and_navigation(self):
        self.assertEqual(self.req("GET", "/api/status", headers={"Sec-Fetch-Site": "cross-site"})[0].status, 403)
        nav = {"Sec-Fetch-Site": "same-site", "Sec-Fetch-Mode": "navigate", "Sec-Fetch-Dest": "document"}
        self.assertEqual(self.req("GET", "/", headers=nav)[0].status, 200)   # 各ツールの画面のリンクで入口を開くのはよい
        self.assertEqual(self.req("GET", "/api/status", headers=nav)[0].status, 403)   # API は同じ画面からだけ
        self.assertEqual(self.req("GET", "/", headers=dict(nav, **{"Sec-Fetch-Dest": "iframe"}))[0].status, 403)

    def test_post_guards(self):
        self.assertEqual(self.req("POST", "/api/cases/auto", b"{}", {"Content-Type": "text/plain", "X-YTT-Token": self.srv.token})[0].status, 415)
        self.assertEqual(self.post("/api/cases/auto", headers={"Origin": "http://evil.example"})[0].status, 403)
        self.assertEqual(self.post("/api/cases/auto", headers={"Sec-Fetch-Site": "cross-site"})[0].status, 403)
        self.assertEqual(self.post("/api/cases/auto", headers={"Origin": "http://localhost:%d" % (self.port + 1)})[0].status, 403)
        self.assertEqual(self.post("/api/cases/auto", body=b"[1]")[0].status, 400)
        self.assertEqual(self.post("/api/cases/auto", body=b"x" * 5000)[0].status, 413)
        self.assertEqual(self.post("/api/nope")[0].status, 404)

    def test_post_body_edges(self):
        """本文の読み取りの境目(httpsec.read_json_body)"""
        def err(r, body):
            return r.status, json.loads(body).get("error")
        self.assertEqual(err(*self.post("/api/cases/auto", body=b"")), (400, "bad_request"))   # 空の本文は {} として読む(案件の検査で断る)
        self.assertEqual(err(*self.post("/api/cases/auto", body=b'{"id": NaN}')), (400, "bad_request"))   # NaN は本文の読み取りでは通す(案件の検査で断る)
        self.assertEqual(err(*self.post("/api/cases/auto", headers={"Content-Length": "abc"}, body=None)), (413, "size"))
        self.assertEqual(err(*self.post("/api/cases/auto", headers={"Content-Type": "application/json; charset=UTF-8"}, body=b"[]")), (400, "json"))
        self.assertEqual(err(*self.post("/api/cases/auto", body=b'{"a": 1')), (400, "json"))
        self.assertEqual(err(*self.post("/api/cases/auto", body=b"[" * 3000)), (400, "json"))   # 深い入れ子でも落ちずに 400
        self.assertEqual(err(*self.post("/api/cases/auto", headers={"Content-Type": "text/plain"})), (415, "content_type"))
        self.assertEqual(self.post("/api/cases/auto", headers={"X-YTT-Token": "é" * 10})[0].status, 403)   # ASCII 以外の合言葉でも落ちずに 403

    def test_extra_dirs(self):
        """空き容量・ごみ箱フォルダの書き出し先(読み方の場合分けは datadir.studio_out_dir の単体)。settings.json が無ければ []"""
        sdir = os.path.join(self.tmp, "studio-data")
        os.makedirs(sdir)
        path = os.path.join(sdir, "settings.json")
        out = os.path.join(self.tmp, "書き出し")
        with mock.patch.object(L.datadir, "resolve", lambda tool, root=None, env=None: sdir):
            self.assertEqual(self.srv._extra_dirs(), [])
            testkit.write_json(path, {"outDir": out})
            self.assertEqual(self.srv._extra_dirs(), [out])

    def test_ytt_request_drains_refused_body(self):
        """取り込んだ画面から回ってきた api/ytt/… を Host/Origin・合言葉で断るときも本文を読み捨てる
        (読まずに閉じると Windows では接続ごと切られて 403 が届かないことがある。mount.py の parse_request が合言葉だけ見てから回す)"""
        body = b'{"message": "x"}'

        class H:
            command, path = "POST", "/api/ytt/client-log"

            def __init__(self, headers):
                self.headers = dict({"Content-Type": "application/json", "Content-Length": str(len(body))}, **headers)
                self.rfile, self.sent = io.BytesIO(body), []

            def _json(self, code, obj):
                self.sent.append((code, obj.get("error")))
        ok = {"Host": self.host, "Origin": "http://" + self.host, "Sec-Fetch-Site": "same-origin", "X-YTT-Token": self.srv.token}
        for bad, want in (({"Host": "evil.example"}, "forbidden"), ({"Origin": "http://evil.example"}, "forbidden"),
                          ({"Sec-Fetch-Site": "cross-site"}, "forbidden"), ({"X-YTT-Token": "x"}, "token")):
            h = H(dict(ok, **bad))
            self.srv.ytt_request(h, "studio", "1")
            self.assertEqual(h.sent, [(403, want)], bad)
            self.assertEqual(h.rfile.read(), b"", "断った要求の本文を読み捨てていない: %r" % (bad,))
        h = H(ok)
        self.srv.ytt_request(h, "studio", "1")
        self.assertEqual(h.sent, [(200, None)])

    def test_restart_self(self):
        """起動し直す: 重い処理の最中は 409 で断る。空いていれば新しい入口を --wait-port で起こし、後始末を頼む"""
        R, calls, stops = self.fake_restart()
        with mock.patch.object(R, "can_restart", lambda *a, **k: "実行中の処理があります(文字起こし)。終わってから起動し直してください"):
            r, body = self.post("/api/ytt/restart-self")
        self.assertEqual((r.status, json.loads(body)["error"]), (409, "busy"))
        self.assertEqual(calls, [])
        # ライブの録画中(偽の録画): 手で押しても 409 の live で止まることを言う(10-23)。画面が確かめて force で送り直したときだけ起こす
        with mock.patch.object(self.srv, "live_activity", lambda: {"recording": 1, "detecting": 0, "exporting": 0}):
            r, body = self.post("/api/ytt/restart-self")
            self.assertEqual((r.status, json.loads(body)["error"], calls), (409, "live", []), body)
            self.assertIn("録画が止まります", json.loads(body)["message"])
            self.assertIn("録画 1 本", json.loads(body)["message"])
            r, body = self.post("/api/ytt/restart-self", body=json.dumps({"force": "yes"}).encode())   # true だけを認める
            self.assertEqual((r.status, calls), (409, []), body)
            r, body = self.post("/api/ytt/restart-self", body=json.dumps({"force": True}).encode())
        self.assertEqual(r.status, 200, body)
        self.assertEqual(len(calls), 1)
        self.assertIn("--wait-port", calls[0])
        self.assertEqual(calls[0][calls[0].index("--port") + 1], str(self.srv.server_address[1]))
        self.wait_stops(stops)
        self.assertTrue(self.srv._handover)   # 起き直しの後始末は録画の部品に quit も kill も送らない

    def test_restart_self_hands_over_only_when_ok(self):
        """録画中: handover_ok が NG(スイッチ オフを含む)なら今までどおり 409 live・自動も待つ。OK なら handover.json を書いて起き直す"""
        R, calls, stops = self.fake_restart()
        wrote = []
        ok = {"v": (False, "録画中の起き直しはオフです")}
        for p in (mock.patch.object(self.srv, "live_activity", lambda: {"recording": 1, "detecting": 1, "exporting": 0}),
                  mock.patch.object(self.srv.live, "handover_ok", lambda: ok["v"]),
                  mock.patch.object(self.srv.live, "write_handover", lambda: wrote.append(1))):
            p.start()
            self.addCleanup(p.stop)
        r, body = self.post("/api/ytt/restart-self")
        self.assertEqual((r.status, json.loads(body)["error"], calls, wrote), (409, "live", [], []), body)
        self.assertEqual(self.srv.auto_busy(), "ライブの録画・検出・書き出しが動いています")
        ok["v"] = (True, "")
        self.assertIsNone(self.srv.auto_busy())
        r, body = self.post("/api/ytt/restart-self")
        self.assertEqual((r.status, len(calls), wrote), (200, 1, [1]), body)
        self.wait_stops(stops)

    def fake_restart(self):
        """新しい入口を起こす口と後始末の頼みを偽物に(このテストの間だけ)-> (restart のモジュール, 起こした引数, 後始末の頼み)"""
        from manage.ops import restart as R
        calls, stops = [], []
        for p in (mock.patch.object(R, "spawn_new_launcher", lambda root, args=(), log=None, **kw: calls.append(list(args))),
                  mock.patch.object(self.srv, "request_shutdown", lambda: stops.append(1))):
            p.start()
            self.addCleanup(p.stop)
        return R, calls, stops

    def test_auto_restart_check(self):
        """自動の起動し直し: 版が同じなら何もしない・処理中(まとめて実行・ライブ・編集の画面・重い処理)は待つ・空けば 1 回だけ起こす・
        同じ版はもう起こさない(起動し直しても版が変わらなかったとき = 赤い帯と手の口が残る)。本物は起こさない(偽の spawn)"""
        from ytt import autorestart as A
        R, calls, stops = self.fake_restart()
        app = os.path.join(self.tmp, "appdata")
        zero = {"recording": 0, "detecting": 0, "exporting": 0}
        runs = {"runs": 0, "redo": None}

        class Stub:
            def restart_info(self):
                return runs

            def close(self):
                pass
        settle = {"why": None}
        patches = [mock.patch.object(L, "app_data_dir", lambda root: app), mock.patch.object(self.srv, "_autorun", Stub()),
                   mock.patch.object(self.srv, "live_activity", lambda: zero), mock.patch.object(self.srv.sup, "status", lambda: {"heavy": {}}),
                   mock.patch.object(A, "settling", lambda path, now=None, secs=None: settle["why"])]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        disk = {"v": L.VERSION}
        with mock.patch.object(L._version, "on_disk", lambda root=None: disk["v"]):
            self.assertEqual(self.srv.auto_restart_check(), A.NOTHING)   # 同じ版
            disk["v"] = "9.9.9"
            settle["why"] = "版が上がってから 10 分待っています"
            self.assertEqual(self.srv.auto_restart_check(), A.WAIT)   # 版が変わってすぐ = 続けて land されても 1 回で済むように待つ
            settle["why"] = None
            runs["runs"] = 1
            self.assertEqual(self.srv.auto_restart_check(), A.WAIT)   # まとめて実行の待ち・実行中
            runs["runs"] = 0
            zero["recording"] = 1
            self.assertEqual(self.srv.auto_restart_check(), A.WAIT)   # ライブの録画中
            zero["recording"] = 0
            self.srv.editor_seen = time.monotonic()
            self.assertEqual(self.srv.auto_restart_check(), A.WAIT)   # 編集の画面を使っている
            self.srv.editor_seen = time.monotonic() - A.EDITOR_IDLE - 1
            with mock.patch.object(self.srv, "_busy_tools", lambda: [("studio", "スタジオ")]):
                self.assertEqual(self.srv.auto_restart_check(), A.WAIT)   # 取り込んだツールのジョブ
            self.assertEqual(calls, [])
            self.assertEqual(self.srv.auto_restart_check(), A.GO)
            self.assertEqual((len(calls), A.read_tried(os.path.join(app, A.STATE_NAME))), (1, "9.9.9"))
            self.assertIn("--wait-port", calls[0])
            self.wait_stops(stops)
            self.assertEqual(self.srv.auto_restart_check(), A.NOTHING)   # 版が変わらないまま = 1 版 1 回(輪にならない)
            self.assertEqual(len(calls), 1)
            disk["v"] = "9.9.10"   # 次の版は改めて 1 回
            self.assertEqual(self.srv.auto_restart_check(), A.GO)
            self.assertEqual(len(calls), 2)

    def test_settling_waits_for_quiet_version(self):
        """ディスクの版のファイルが変わってから SETTLE_SEC 秒は待つ・過ぎれば None・読めなければ None"""
        from ytt import autorestart as A
        f = os.path.join(self.tmp, "version.py")
        open(f, "w").close()
        now = os.path.getmtime(f)
        self.assertIn("待っています", A.settling(f, now + 60))
        self.assertIsNone(A.settling(f, now + A.SETTLE_SEC + 1))
        self.assertIsNone(A.settling(os.path.join(self.tmp, "none.py"), now))

    def test_editor_seen_ignores_polls(self):
        """開いたままの画面の版の見回り(/api/ping)などは「編集を使っている」に数えない(10-24: ping だけで自動の起動し直しが 6 時間待った)"""
        pre = L.mount_mod.MOUNTS["transcribe"]["prefix"]
        with mock.patch.object(self.srv, "mounts", {pre: object()}):
            self.srv.editor_seen = None
            for p in ("/api/ping", "/api/drill/status", "/api/eval-batch"):
                self.srv.handler_for(pre + p)
            self.assertIsNone(self.srv.editor_seen)
            self.srv.handler_for(pre + "/api/settings")
            self.assertIsNotNone(self.srv.editor_seen)

    def test_flow_status_live(self):
        """GET /api/flow/status の live 欄 = PortalServer.live_activity(ライブの録画中・検出中・書き出しの途中の数)。どれかが 0 でなければ idle は偽。
        リアルタイム切り抜きがオフなら全部 0 で、録画元に問い合わせない(読めないときの扱いは tests/flow/test_runqueue.py の TestStatusLive)"""
        zero = {"recording": 0, "detecting": 0, "exporting": 0}
        st = self.get_json("/api/flow/status")[1]
        self.assertEqual((st["live"], st["idle"]), (zero, True))   # 既定(オフ)
        from flow import livesession
        fake = mock.MagicMock()
        fake.activity = lambda: livesession.LiveSession.activity(fake)   # 数え方は本物(LiveSession.activity)
        fake.enabled.return_value = True
        fake.recent.return_value = [{"id": "a", "active": True}, {"id": "b", "active": False}]   # 終わって 10 分以内の録画は数えない
        fake.detector.enabled.return_value = True
        fake.detector.heartbeat.return_value = {"recordings": [{"recorder": "local", "id": "a"}, {"recorder": "local", "id": "c"}]}
        fake.detector.running.return_value = True
        fake._exporter.lock = threading.Lock()
        fake._exporter.jobs = [{"state": "fetch"}, {"state": "done", "handoffWait": "disk"}, {"state": "done"}, {"state": "failed"}]
        with mock.patch.object(self.srv, "live", fake):
            st = self.get_json("/api/flow/status")[1]
            self.assertEqual((st["live"], st["idle"], st["queued"], st["running"]), ({"recording": 1, "detecting": 2, "exporting": 2}, False, 0, 0))
            fake.recent.return_value = []
            fake.detector.running.return_value = False   # ワーカーが止まっている = 測っていない
            fake._exporter = None   # 書き出しを一度も使っていない
            self.assertEqual(self.srv.live_activity(), zero)
            fake.enabled.return_value = False
            fake.recent.reset_mock()
            self.assertEqual(self.srv.live_activity(), zero)
            fake.recent.assert_not_called()

    def test_restart_self_keeps_autorun_runs(self):
        """まとめて実行の待ち・実行中は断らずに起動し直し、何件が続くかを notice で知らせる(M5)。
        実行中の段の仕事でも、同じツールに人が始めた仕事があれば(others)断る"""
        class Stub:
            def __init__(self, redo):
                self.redo = redo

            def snapshot(self):
                return {"runs": [{"state": "running", "mode": "adopted"}, {"state": "queued", "mode": "request"}]}

            def restart_info(self):
                return {"runs": 2, "redo": self.redo}

            def close(self):
                pass
        R, calls, stops = self.fake_restart()
        heavy = {"limit": 2, "active": [{"tool": "transcribe", "label": "配信の切り抜き", "seconds": 3}], "waiting": []}
        with mock.patch.object(self.srv.sup, "status", lambda: {"heavy": heavy}), mock.patch.object(self.srv, "_autorun"):
            self.srv._autorun = Stub({"tool": "transcribe", "labels": ["配信の切り抜き"], "others": ["人が入れた文字起こし"]})
            r, body = self.post("/api/ytt/restart-self")
            self.assertEqual((r.status, calls), (409, []), body)
            self.assertIn("配信の切り抜き", json.loads(body)["message"])
            self.srv._autorun = Stub({"tool": "transcribe", "labels": ["配信の切り抜き"], "others": []})
            r, body = self.post("/api/ytt/restart-self")
        self.assertEqual((r.status, len(calls)), (200, 1), body)
        self.assertEqual(json.loads(body), {"ok": True, "notice": R.RESUME_NOTICE % 2})
        self.wait_stops(stops)

    def test_csrf_token(self):
        """書き込み系の API は、画面に埋め込んだ合言葉(CSRF トークン)が一致しないと受け付けない"""
        r, body = self.req("GET", "/")
        self.assertIn(('<meta name="ytt-token" content="%s">' % self.srv.token).encode(), body)
        for bad in ("", "x" * len(self.srv.token), self.srv.token + "x"):
            self.assertEqual(self.post("/api/cases/auto", headers={"X-YTT-Token": bad})[0].status, 403, bad)
        h = {"Content-Type": "application/json", "Origin": "http://" + self.host}
        self.assertEqual(self.req("POST", "/api/shutdown", b"{}", h)[0].status, 403)   # 合言葉なし
        self.assertFalse(self.srv.closing.is_set())
        self.assertEqual(self.state("studio"), "stopped")
        other, _ = L.make_server(0, self.sup)
        try:
            self.assertNotEqual(other.token, self.srv.token)   # 起動ごとに変わる
        finally:
            other.server_close()

    def test_log_endpoint(self):
        """ログの読み出しの境目: ツールの名前の許可範囲・数でない lines・まだ無いログ(出ているログの表示は e2e_portal の [B])"""
        for bad in ("../launcher", "..%2F..%2Fetc%2Fpasswd", "", "STUDIO"):
            self.assertEqual(self.req("GET", "/api/log?tool=" + bad)[0].status, 404, bad)
        r, body = self.req("GET", "/api/log?tool=studio&lines=abc")
        self.assertEqual(r.status, 200)
        r, body = self.req("GET", "/api/log?tool=transcribe")
        self.assertEqual(json.loads(body)["exists"], False)

    def test_autorun_history(self):
        """まとめて実行の記録(作業データの logs/autorun-runs.jsonl)。前回の結果は /api/flow/runs の past・一覧は /api/flow/history(limit・offset の丸めは tests/flow/test_runqueue.py の TestRunLog)"""
        logs = self.sup.logs_dir
        self.assertTrue(os.path.abspath(logs).startswith(os.path.abspath(self.tmp)), logs)   # テストは一時フォルダに書く
        os.makedirs(logs, exist_ok=True)
        with open(os.path.join(logs, "autorun-runs.jsonl"), "w", encoding="utf-8") as f:
            for i in range(250):
                f.write(json.dumps({"v": 1, "id": "r%03d" % i, "kind": "video", "videoId": "v%03d" % i, "docId": None, "state": "error",
                                    "error": "理由%d" % i, "steps": []}, ensure_ascii=False) + "\n")
        j = self.get_json("/api/flow/runs")[1]
        self.assertEqual((j["runs"], len(j["past"]), j["past"][0]["id"], j["past"][0]["error"]), ([], 50, "r249", "理由249"))
        r, body = self.req("GET", "/api/flow/history?limit=20&offset=240")   # 問い合わせの値が届く
        h = json.loads(body)
        self.assertEqual((r.status, len(h["runs"]), h["runs"][0]["id"], h["total"]), (200, 10, "r009", 250))
        self.assertEqual(self.req("GET", "/api/flow/history", headers={"Sec-Fetch-Site": "cross-site"})[0].status, 403)   # ほかのサイトからは読めない

    def test_flow_submit_and_status(self):
        """② の口 POST /api/flow/submit {envelope, spec}(合言葉が要る・形が違えば 400 と理由。理由の中身は tests/flow/test_envelope.py)と GET /api/flow/status"""
        r, body = self.req("GET", "/api/flow/status")
        j = json.loads(body)
        self.assertEqual((r.status, j["queued"], j["running"], j["idle"], j["runs"]), (200, 0, 0, True, []))
        media, env = self.file_envelope()
        payload = json.dumps({"envelope": env, "spec": {"transcribe": {"model": "large-v3"}, "run": {"upto": "transcribe"}}}, ensure_ascii=False).encode("utf-8")
        self.assertEqual(self.post("/api/flow/submit", headers={"X-YTT-Token": "x"}, body=payload)[0].status, 403)   # 書き込み系 = 合言葉が要る
        r, body = self.post("/api/flow/submit", body=json.dumps({"envelope": dict(env, kind="nai")}).encode("utf-8"))
        self.assertEqual((r.status, "封筒.kind" in json.loads(body)["message"]), (400, True))
        r, body = self.post("/api/flow/submit", body=payload)
        j = json.loads(body)
        self.assertEqual((r.status, j["run"]["id"], j["run"]["kind"], j["run"]["sourcePath"]), (200, "0123456789", "file", media))
        st = self.get_json("/api/flow/status")[1]
        self.assertEqual([x["id"] for x in st["runs"]], ["0123456789"])
        self.assertEqual(next(x for x in self.srv.autorun.runs if x.id == "0123456789").spec["transcribe"]["model"], "large-v3")   # 受けた束のまま
        self.assertEqual(self.req("GET", "/api/flow/status", headers={"Sec-Fetch-Site": "cross-site"})[0].status, 403)   # ほかのサイトからは読めない

    def test_flow_submit_waits_for_tools(self):
        """起動直後(ツールの取り込みの途中)の submit は取り込みが済むまで待つ・待ちきれなければ 503 starting(CLI が「編集が動いていない」で落ちない)"""
        self.srv.tools_started = threading.Event()
        try:
            with mock.patch.object(L, "SUBMIT_START_WAIT", 0.2):
                r, body = self.post("/api/flow/submit", body=json.dumps({}).encode("utf-8"))
                self.assertEqual((r.status, json.loads(body)["error"]), (503, "starting"))
            threading.Timer(0.3, self.srv.tools_started.set).start()
            r, body = self.post("/api/flow/submit", body=json.dumps({}).encode("utf-8"))   # 済んだら検査へ進む
            self.assertEqual(r.status, 400)
        finally:
            self.srv.tools_started = None
    def test_flow_submit_spec_errors(self):
        """F1 F0-1: 束の版の違いは 400 spec_version・束の知らない節・項目は 400 bad_spec(呼ぶアプリは「更新してください」と出せる)・封筒の形は bad_request"""
        _media, env = self.file_envelope()
        for bad, code in (({"envelope": dict(env, specVersion=3)}, "spec_version"), ({"envelope": env, "spec": {"nai": {}}}, "bad_spec"),
                          ({"envelope": env, "spec": {"transcribe": {"nai": 1}}}, "bad_spec"), ({"envelope": dict(env, kind="nai")}, "bad_request")):
            r, body = self.post("/api/flow/submit", body=json.dumps(bad, ensure_ascii=False).encode("utf-8"))
            self.assertEqual((r.status, json.loads(body)["error"]), (400, code), bad)
        self.assertEqual(self.srv.autorun.status()["runs"], [])

    def test_wire_learning(self):
        """F1 F6a: machine の learningDir が学習の束なら、入口の文字起こし(doc_jobs)とまとめて実行(束の版)がその読み手を使う。既定なら何もしない"""
        from human.proof import doc_jobs
        self.addCleanup(doc_jobs.set_learning, None)
        with mock.patch.object(L.learning_mod, "learning_dir_checked", return_value=(None, "")):
            self.assertIsNone(self.srv.wire_learning())
        self.assertIsNone(doc_jobs._learning[0])
        logs = []   # 作る側の PC: 束を読まずにログに 1 行(6d-1)
        with mock.patch.object(L.learning_mod, "learning_dir_checked", return_value=(None, "読みません")), \
                mock.patch.object(self.srv.sup, "log", side_effect=logs.append), mock.patch.object(L.learning_mod, "apply_places") as ap0:
            self.assertIsNone(self.srv.wire_learning())
        ap0.assert_not_called()
        self.assertEqual(logs, ["読みません"])
        self.assertIsNone(doc_jobs._learning[0])
        pack = os.path.join(self.tmp, "学習", "v9")
        testkit.write_json(os.path.join(pack, "learning.json"), {"version": "v9"})
        testkit.write_json(os.path.join(pack, "learned-rules.json"), {"high": [], "glossary": ["星街すいせい"], "dictLearned": "d1"})
        self.srv.autorun   # 先に作ってあっても読み手が入る
        with mock.patch.object(L.learning_mod, "learning_dir_checked", return_value=(pack, "")), mock.patch.object(L.learning_mod, "apply_places") as ap:
            lr = self.srv.wire_learning()
        ap.assert_called_once_with(pack)
        self.assertEqual(lr.version, "v9")
        self.assertIs(doc_jobs._learning[0], lr)
        self.assertIs(self.srv.autorun.learning, lr)   # 読み手の中身は tests/flow/test_learning.py の TestPackReader

    def test_build_learnpack_needs_intake_folder(self):
        """F1 F6a: 学習の束は依頼の受付のフォルダが設定されているときだけ <フォルダ>/学習 へ"""
        folder = os.path.join(self.tmp, "受付")
        with mock.patch.object(L.learnpack_mod, "build", return_value={"version": "v", "dir": "d", "created": True}) as build:
            with mock.patch.object(self.srv.prefs, "get", return_value={"intake": {"folder": ""}}):
                self.assertIsNone(self.srv.learnpack.once())
            os.makedirs(folder)
            with mock.patch.object(self.srv.prefs, "get", return_value={"intake": {"folder": folder}}):
                self.assertEqual(self.srv.learnpack.once()["version"], "v")
                build.side_effect = OSError("x")
                self.assertIsNone(self.srv.learnpack.once())
        self.assertEqual(build.call_args[0][0], os.path.join(folder, "学習"))
        self.assertIn("error", self.srv.learnpack.last)

    def test_flow_board_api(self):
        """② の口: status の rev・jobs・cases・?case= の検査と絞り込み・POST /api/flow/cancel
        (合言葉が要る・形が違えば 400・無い id は 404・できない物は 409)・GET /api/flow/history・POST /api/flow/estimate"""
        quote = urllib.parse.quote
        r, body = self.req("GET", "/api/flow/status")
        st = json.loads(body)
        self.assertEqual(r.status, 200)
        self.assertLessEqual({"queued", "running", "done", "idle", "closed", "live", "runs", "rev", "jobs", "cases"}, set(st))
        self.assertIsInstance(st["rev"], int)
        for path in ("/api/flow/status?case=" + quote("相対/パス"), "/api/flow/history?case=" + quote("x")):
            r, body = self.req("GET", path)
            self.assertEqual((r.status, json.loads(body)["error"]), (400, "bad_request"), path)
        _media, env = self.file_envelope()
        self.assertEqual(self.post_json("/api/flow/submit", {"envelope": env, "spec": {"run": {"upto": "transcribe"}}})[0], 200)
        st = self.get_json("/api/flow/status")[1]
        self.assertIn("run:0123456789", [j["id"] for j in st["jobs"]])   # ジョブの形は tests/flow/test_runqueue.py の test_board_job_shape
        st = self.get_json("/api/flow/status?case=" + quote(os.path.join(self.tmp, "nai")))[1]
        self.assertEqual((st["jobs"], [x["id"] for x in st["runs"]]), ([], ["0123456789"]))   # 絞るのは jobs だけ
        self.assertEqual(self.post("/api/flow/cancel", headers={"X-YTT-Token": "x"}, body=b'{"id": "run:0123456789"}')[0].status, 403)   # 書き込み系 = 合言葉が要る
        for payload, code, err in (({"id": "nai"}, 400, "bad_request"), ({}, 400, "bad_request"), ({"id": "run:ffffffffff"}, 404, "not_found")):
            r, body = self.post("/api/flow/cancel", body=json.dumps(payload).encode("utf-8"))
            self.assertEqual((r.status, json.loads(body)["error"]), (code, err), payload)
        r, body = self.post("/api/flow/cancel", body=b'{"id": "run:0123456789"}')
        self.assertIn(r.status, (200, 409))   # 実行中なら止める・もう終わっていれば cannot_cancel
        wait_for(lambda: self.srv.autorun.status()["idle"], 30, 0.05)
        r, body = self.post("/api/flow/cancel", body=b'{"id": "run:0123456789"}')
        self.assertEqual((r.status, json.loads(body)["error"]), (409, "cannot_cancel"))
        r, body = self.req("GET", "/api/flow/history?case=" + quote(self.tmp) + "&limit=5")
        self.assertEqual(r.status, 200)
        self.assertLessEqual({"runs", "total", "more", "offset"}, set(json.loads(body)))
        self.assertEqual(self.req("GET", "/api/flow/history", headers={"Sec-Fetch-Site": "cross-site"})[0].status, 403)   # ほかのサイトからは読めない
        self.assertEqual(self.post("/api/flow/estimate", body=b'{"ids": []}')[0].status, 400)   # 本文は submit と同じ {envelope, spec}(封筒が無ければ 400)

    def test_flow_submit_live_goes_to_live(self):
        """封筒 kind live は ② の口からライブ係(Live.submit)へ(入口が Queue.set_live_hook で登録)。リアルタイム切り抜きがオフなら 400 と理由
        (録画元・yt-dlp に聞かない)。オンなら Live.submit が受けた封筒 + 束で録画を始める"""
        env = {"id": "live000001", "kind": "live", "input": {"videoId": "abcdefghijk", "title": "配信"}}
        self.srv.live.probe = lambda url: self.fail("オフなら配信の状態を調べない")
        r, body = self.post("/api/flow/submit", body=json.dumps({"envelope": env}).encode("utf-8"))
        self.assertEqual((r.status, "オフ" in json.loads(body)["message"]), (400, True))
        seen = []
        with mock.patch.object(self.srv.live, "submit", lambda e, s: seen.append((e, s)) or {"id": e["id"], "live": True}):
            r, body = self.post("/api/flow/submit", body=json.dumps({"envelope": env, "spec": {"adopt": {"top": 10}}}).encode("utf-8"))
        self.assertEqual((r.status, json.loads(body)["run"], seen[0][0]["kind"]), (200, {"id": "live000001", "live": True}, "live"))   # 束の受け渡しは test_runqueue の TestSubmitLive
        self.assertEqual(self.srv.autorun.status()["runs"], [], "kind live は待ち行列に積まない")

    def test_intake_api(self):
        """友人からの依頼の受付(src/human/friend/intake.py): 状態・設定(api/ytt/prefs の節 intake)・今すぐ確認。受付の設定は作業データの prefs.json(一時フォルダ)"""
        st, j = self.get_json("/api/intake")
        self.assertEqual((st, j["enabled"], j["state"], j["requests"]), (200, False, "off", []))
        folder = os.path.join(self.tmp, "依頼")
        os.makedirs(folder)
        st, j = self.patch_prefs("intake", {"folder": "\\\\srv\\share"})
        self.assertEqual(st, 400)
        self.assertIn("ネットワーク", j["message"])
        st, j = self.patch_prefs("intake", {"enabled": True, "folder": folder, "top": 4})
        self.assertEqual((st, j["value"]["top"]), (200, 4))
        self.srv.intake.scan()
        j = self.get_json("/api/intake")[1]
        self.assertEqual((j["enabled"], j["folder"], j["state"], j["top"]), (True, folder, "watching", 4))
        self.assertEqual(self.post("/api/intake/scan", headers={"X-YTT-Token": "x"})[0].status, 403)   # 合言葉が要る
        st, j = self.post_json("/api/intake/scan", {})
        self.assertEqual((st, j["state"]), (200, "watching"))
        self.assertEqual(self.req("GET", "/api/intake", headers={"Sec-Fetch-Site": "cross-site"})[0].status, 403)

    def test_backup_api(self):
        """作業データのバックアップ(src/manage/keep/backup.py): 状態・設定(api/ytt/prefs の節 backup)・今すぐ写す。テスト(inplace)では作業データの親が無いので写さない"""
        st, j = self.get_json("/api/backup")
        self.assertEqual((st, j["enabled"], j["state"], j["everyHours"], j["source"]), (200, False, "off", 24, None))
        self.assertEqual(self.patch_prefs("backup", {"enabled": True})[0], 400)   # 先のフォルダが無いままではオンにできない
        self.assertEqual(self.patch_prefs("backup", {"folder": "\\\\srv\\share"})[0], 400)
        dest = os.path.join(self.tmp, "先")
        st, j = self.patch_prefs("backup", {"enabled": True, "folder": dest, "everyHours": 12})
        self.assertEqual((st, j["value"]), (200, {"enabled": True, "folder": dest, "everyHours": 12}))
        self.assertEqual(self.post("/api/backup/run", headers={"X-YTT-Token": "x"})[0].status, 403)   # 合言葉が要る
        st, j = self.post_json("/api/backup/run", {})
        self.assertEqual((st, j["folder"]), (200, dest))
        self.srv.backup.tick()   # inplace では写さない(本物の作業データに触らない)
        self.assertEqual((self.srv.backup.state, os.path.exists(dest)), ("off", False))
        self.assertEqual(self.req("GET", "/api/backup", headers={"Sec-Fetch-Site": "cross-site"})[0].status, 403)

    def test_shutdown_stops_children_and_server(self):
        self.sup.start_all()
        self.sup.start_monitor()
        for tid in L.TOOL_IDS:
            self.assertTrue(self.wait_state(tid, "running"), tid)
        procs = [t.proc for t in self.sup.tools]
        r, body = self.post("/api/shutdown")
        self.assertEqual(r.status, 200)
        self.th.join(20)
        self.assertFalse(self.th.is_alive(), "入口のサーバーが止まらない")
        for p in procs:
            self.assertIsNotNone(p.poll())
        self.assertEqual({t.snapshot()["state"] for t in self.sup.tools}, {"stopped"})

    def test_existing_launcher_is_detected(self):
        srv2, port2 = L.make_server(self.port, self.sup)
        self.assertIsNone(srv2)
        self.assertEqual(port2, self.port)


class MainShutdownTest(unittest.TestCase):
    """main() の終了の後始末は 1 回だけ。「すべて終了」(request_shutdown)のあとに finally でもう一度走らない・
    Ctrl+C・黒い画面の×(KeyboardInterrupt)の経路でもまとめて実行を閉じる(閉じないと実行中の段が「失敗」として記録され、次の起動で続かない。M5)"""

    def setUp(self):
        self.tmp = testkit.tempdir(self, "ytt-main-")
        self.root = make_fake_root(self.tmp)
        self.addCleanup(L.datadir.register, "app", L.datadir.registered("app"))

    def base_patches(self, make_logger, make_server):
        """main を一時フォルダの偽のツールで動かすための差し替え(ほかの差し替えは呼び手が足す)"""
        return [mock.patch.dict(os.environ, {"YTT_RUNTIME_DIR": os.path.join(self.tmp, ".runtime")}),
                mock.patch.object(L, "ROOT", self.root), mock.patch.object(L, "make_server", make_server),
                mock.patch.object(L, "make_logger", make_logger)]

    def keep_server(self, got):
        """本物の make_server で起こして、できたサーバーを got["srv"] に控える"""
        real_make_server = L.make_server

        def make_server(port, sup):
            got["srv"], p = real_make_server(port, sup)
            return got["srv"], p
        return make_server

    def run_main(self, on_live_start):
        got, unmounts = {}, []

        def live_start(live):   # 起動の最後のほう(まとめて実行を作ったあと)で、終了の合図を送る
            on_live_start(got["srv"])

        with patched(self.base_patches(quiet_logger(), self.keep_server(got)) + [
                mock.patch.object(L, "install_stop_signals"), mock.patch.object(L, "ignore_stop_signals"),
                mock.patch.object(L, "analytics_mod", None), mock.patch.object(L.Supervisor, "start_all"),
                mock.patch.object(L.Supervisor, "unmount_all", lambda sup: unmounts.append(1)),
                mock.patch.object(L.live_mod.Live, "start", live_start), mock.patch.object(L.PortalServer, "purge_trash", lambda srv: None)]):
            self.assertEqual(L.main(["--port", "0", "--no-open", "--no-mount"]), 0)
        return got["srv"], unmounts

    def test_shutdown_from_page_runs_teardown_once(self):
        srv, unmounts = self.run_main(lambda srv: srv.request_shutdown())
        self.assertEqual(unmounts, [1], "後始末が 2 回走った")
        self.assertTrue(srv._autorun.closed)

    def test_ctrl_c_closes_autorun(self):
        def interrupt(srv):
            raise KeyboardInterrupt()
        srv, unmounts = self.run_main(interrupt)
        self.assertEqual(unmounts, [1])
        self.assertTrue(srv.closing.is_set())
        self.assertTrue(srv._autorun.closed, "Ctrl+C の経路でまとめて実行を閉じていない")

    def run_started(self, argv):
        """main を本物のサーバー(ポート 0)で起こし、見張りの起動を数えて、起動のすぐあとに「すべて終了」する。-> (終了コード, srv, 起こした常駐の名前, 画面を開いた回数)"""
        got, started, opened = {}, [], []

        def live_start(live):
            started.append("live")
            got["srv"].request_shutdown()

        def rec(name):
            return lambda *a, **k: started.append(name)

        analytics = mock.MagicMock()
        with patched(self.base_patches(quiet_logger(), self.keep_server(got)) + [
                mock.patch.object(L, "install_stop_signals"), mock.patch.object(L, "ignore_stop_signals"),
                mock.patch.object(L, "analytics_mod", analytics), mock.patch.object(L.Supervisor, "start_all"),
                mock.patch.object(L.Supervisor, "unmount_all", lambda sup: None),
                mock.patch.object(L.live_mod.Live, "start", live_start),
                mock.patch.object(L.intake_mod.Intake, "start", rec("intake")), mock.patch.object(L.backup_mod.Backup, "start", rec("backup")),
                mock.patch.object(L.accuracy_mod.Accuracy, "start", rec("accuracy")),
                mock.patch.object(L.PortalServer, "purge_trash", rec("trash")),
                mock.patch.object(L.appwindow_mod.Opener, "open_start", lambda op, url: opened.append(url) or "browser")]):
            code = L.main(argv)
        if analytics.Service.return_value.start.called:
            started.append("analytics")
        return code, got["srv"], started, opened

    def test_normal_start_still_starts_watchers(self):
        """起動すると見張りを起こす(依頼の受付・バックアップ・精度の自動測定・分析と日報・ごみ箱の片付け・ライブ)"""
        code, srv, started, opened = self.run_started(["--port", "0", "--no-mount", "--no-open"])
        self.assertEqual(code, 0)
        wait_for(lambda: "trash" in started, 5)   # ごみ箱の片付けは裏のスレッド
        self.assertEqual(sorted(started), ["accuracy", "analytics", "backup", "intake", "live", "trash"])

    def run_main_failing(self, argv, wait_result=None, lock_busy=None, existing=False):
        """待ちの期限・.flow.lock の先客で、トレースバックにせず読める文を出して非 0 で終わる。existing: 入口がすでに動いている"""
        logs, errs, made = [], io.StringIO(), []

        def make_server(port, sup):
            if existing:
                return None, port
            srv = mock.MagicMock()
            made.append(srv)
            return srv, port

        patches = self.base_patches(quiet_logger(logs), make_server) + [mock.patch.object(sys, "stderr", errs)]
        if wait_result is not None:
            patches.append(mock.patch.object(L.restart_mod, "wait_old_launcher", lambda port, pid=None: wait_result))
        if lock_busy is not None:
            patches.append(mock.patch.object(L.placement, "acquire", mock.Mock(side_effect=L.placement.LockBusy(lock_busy))))
        with patched(patches):
            code = L.main(argv)
        return code, logs, errs.getvalue(), made

    def test_wait_port_deadline_exits_nonzero_without_next_port(self):
        code, logs, err, made = self.run_main_failing(["--port", "8700", "--wait-port", "--wait-pid", "99", "--no-open", "--no-mount"],
                                                       wait_result="前のホームが終わりません。start.bat で")
        self.assertEqual(code, 1)
        self.assertEqual(made, [], "期限が来たのに次の番号で起動しようとした")
        self.assertIn("前のホームが終わりません", err)
        self.assertTrue(any("前のホームが終わりません" in x for x in logs))

    def test_lock_busy_exits_nonzero_with_message(self):
        code, logs, err, made = self.run_main_failing(["--port", "0", "--no-open", "--no-mount"], lock_busy={"pid": 4242, "port": 8700})
        self.assertEqual(code, 1)
        self.assertIn("4242", err)
        self.assertIn("すべて終了", err)
        made[0].server_close.assert_called_once()


def _copy_tool(src, dst):
    shutil.copytree(src, dst, ignore=shutil.ignore_patterns(
        "__pycache__", "*.log", "data.json*", "feedback.jsonl*", "config.json", "settings*.json", "registry.json", "cache", "archive",
        "exports", "clips", "transcripts", "dataset", "models", "work", ".venv", "*.mp4", "node_modules", "tests"))


@unittest.skipUnless(all(os.path.isfile(os.path.join(REPO, s["dir"], "serve.py")) for s in L.TOOLS), "本物のツールのフォルダが無い")
class RealToolsTest(unittest.TestCase):
    """本物の3ツール(疑似モード)を一時フォルダに写して、入口から起動 → 3つとも動作中 → 各ツールの「他のツール」の
    ポート共有(.runtime・/api/siblings)が働く → まとめて停止で .runtime が消える、を確かめる"""

    def test_real_tools(self):
        tmp = testkit.tempdir(self, "ytt-launch-real-")
        rdir = os.path.join(tmp, ".runtime")
        env = {"YTT_RUNTIME_DIR": rdir, "STUDIO_FAKE": "1", "TRANSCRIBE_BACKEND": "fake"}
        for s in L.TOOLS:
            _copy_tool(os.path.join(REPO, s["dir"]), os.path.join(tmp, s["dir"]))
        layout.copy_shared_code(tmp, ignore=shutil.ignore_patterns("__pycache__"), root=REPO)   # 共通のコード(ytt と役割の層 = layout.SHARED_CODE_DIRS。本物と同じ並び)
        ports = dict(zip(L.TOOL_IDS, free_ports(3)))
        events = []
        with mock.patch.dict(os.environ, env):
            sup = L.Supervisor(tmp, ready_timeout=60, stop_timeout=10, poll=0.2, log=events.append, ports=ports)
            try:
                sup.start_all()
                sup.start_monitor()
                ok = wait_for(lambda: all(t.snapshot()["state"] == "running" for t in sup.tools), 60, 0.2)
                self.assertTrue(ok, "\n".join(events) + "\n" + json.dumps(sup.status(), ensure_ascii=False, indent=1))
                for t in sup.tools:
                    snap = t.snapshot()
                    self.assertEqual(snap["port"], ports[t.id])
                    self.assertEqual(snap["version"], snap["expectedVersion"], t.id)
                # スタジオの「他のツール」(/api/siblings)が、入口から起動した他の2つを見つける
                conn = http.client.HTTPConnection("127.0.0.1", ports["studio"], timeout=10)
                conn.request("GET", "/api/siblings", headers={"Host": "127.0.0.1:%d" % ports["studio"]})
                sib = json.loads(conn.getresponse().read())
                conn.close()
                self.assertEqual(sib["tools"], ports)
                # 監視の接続確認(つないですぐ切る)で、ツールのログにアクセスの行が増え続けない
                tx = sup.by_id["transcribe"]
                before = len(L.tail(tx.log_path, 10000) or [])
                time.sleep(3)   # 見回りは poll=0.2 秒ごと = 15 回つなぐ(1 回ごとに行が増えるなら必ず見える)
                after = len(L.tail(tx.log_path, 10000) or [])
                self.assertLessEqual(after - before, 1, "\n".join((L.tail(tx.log_path, 20) or [])))
                self.assertEqual(sup.by_id["transcribe"].snapshot()["state"], "running")
            finally:
                sup.close()
                sup.stop_all()
            for t in sup.tools:
                self.assertEqual(t.snapshot()["state"], "stopped", t.id)
                self.assertFalse(os.path.exists(os.path.join(rdir, t.id + ".json")), t.id)


if __name__ == "__main__":
    unittest.main()
