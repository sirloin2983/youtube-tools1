# -*- coding: utf-8 -*-
"""入口(app/launch.py)のテスト。  python -m unittest app/test_launch.py -v

- 偽のツール(serve.py の約束だけをまねた小さなサーバー)で、起動・停止・再起動・異常終了・別の画面で起動済み・
  強制終了・ポートの繰り上げ・入口の画面の安全検査を確かめる
- 本物の3ツール(疑似モード)を一時フォルダに写して、入口から起動・停止できることを確かめる(RealToolsTest)
ポートは OS に空きを選ばせるので、本物のツールが動いている PC でも走らせられる。
"""
import http.client
import json
import os
import shutil
import socket
import sys
import tempfile
import textwrap
import threading
import time
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import launch as L  # noqa: E402

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
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass
        print("bye", flush=True)
''')

VERSIONS = {"studio": "0.2.0", "transcribe": "0.10.0", "cut2resolve": "0.3.0"}


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
        vline = ('SERVER_VERSION = "%s"\n' if spec["version_file"] == "serve.py" else 'VERSION = "%s"\n') % versions[spec["id"]]
        with open(os.path.join(d, spec["version_file"]), "a", encoding="utf-8") as f:
            f.write("\n" + vline)
    return tmp


def set_mode(root, tid, mode):
    spec = [s for s in L.TOOLS if s["id"] == tid][0]
    with open(os.path.join(root, spec["dir"], "mode.txt"), "w") as f:
        f.write(mode)


def wait_for(fn, timeout=15.0, step=0.1):
    end = time.time() + timeout
    while time.time() < end:
        v = fn()
        if v:
            return v
        time.sleep(step)
    return fn()


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="ytt-launch-")
        self.root = make_fake_root(self.tmp)
        self.rdir = os.path.join(self.tmp, ".runtime")
        self.env = mock.patch.dict(os.environ, {"YTT_RUNTIME_DIR": self.rdir})
        self.env.start()
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
        self.env.stop()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def state(self, tid):
        return self.sup.by_id[tid].snapshot()["state"]

    def wait_state(self, tid, *states, timeout=15):
        return wait_for(lambda: self.state(tid) in states, timeout)

    def spawn_external(self, tid, port):
        """入口を通さずに(別の黒い画面で起動したのと同じ)偽のツールを起動する"""
        import subprocess
        spec = [s for s in L.TOOLS if s["id"] == tid][0]
        p = subprocess.Popen([sys.executable, os.path.join(self.root, spec["dir"], "serve.py"), str(port), "--no-open"],
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
        self.assertIn("入口から起動", text)
        self.assertIn("listening", text)
        self.assertIn("bye", text)   # SIGTERM(Windows は Ctrl+Break)で正常に後始末して終わった

    def test_restart_replaces_process(self):
        self.sup.start("studio")
        self.sup.start_monitor()
        self.assertTrue(self.wait_state("studio", "running"))
        old = self.sup.by_id["studio"].proc
        self.sup.restart("studio")
        self.assertIsNotNone(old.poll(), "古いプロセスが残っている")
        self.assertTrue(self.wait_state("studio", "running"))
        self.assertIsNot(self.sup.by_id["studio"].proc, old)
        self.assertEqual(self.sup.by_id["studio"].snapshot()["starts"], 2)

    def test_start_is_idempotent(self):
        self.sup.start("studio")
        first = self.sup.by_id["studio"].proc
        self.sup.start("studio")   # 起動中にもう一度押しても2つ目は起動しない
        self.assertIs(self.sup.by_id["studio"].proc, first)

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
        d = os.path.join(self.root, "clip-studio")
        with open(os.path.join(d, "serve.py"), encoding="utf-8") as f:
            src = f.read()
        old_dir = os.path.join(self.tmp, "old", "clip-studio")
        os.makedirs(old_dir)
        with open(os.path.join(old_dir, "serve.py"), "w", encoding="utf-8") as f:
            f.write(src.replace("'0.2.0'", "'0.1.8'"))
        import subprocess
        p = subprocess.Popen([sys.executable, os.path.join(old_dir, "serve.py"), str(self.ports["studio"]), "--no-open"],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.extra_procs.append(p)
        self.assertTrue(wait_for(lambda: L.ping(self.ports["studio"]) is not None, 10))
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
        os.makedirs(self.rdir, exist_ok=True)
        path = os.path.join(self.rdir, "studio.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"tool": "studio", "port": other, "version": "0.2.0"}, f)
        old = time.time() - 3600
        os.utime(path, (old, old))
        self.sup.start_monitor()
        time.sleep(0.6)
        self.assertEqual(self.state("studio"), "starting", "古い記録のポートを今回の子と取り違えた")
        self.assertTrue(self.wait_state("studio", "running"))
        self.assertEqual(self.sup.by_id["studio"].snapshot()["port"], self.ports["studio"])
        # 範囲外のポートを書いた記録も信用しない
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"tool": "studio", "port": 1, "version": "x"}, f)
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
        self.tmp = tempfile.mkdtemp(prefix="ytt-launch-h-")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

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

    def test_rotate(self):
        p = os.path.join(self.tmp, "b.log")
        with open(p, "wb") as f:
            f.write(b"x" * 20)
        L.rotate(p, limit=10)
        self.assertFalse(os.path.exists(p))
        self.assertTrue(os.path.exists(os.path.join(self.tmp, "b.old.log")))

    def test_parse_args(self):
        self.assertEqual(L.parse_args(["--only", "studio, transcribe"]).only, ["studio", "transcribe"])
        with mock.patch("sys.stderr"):
            with self.assertRaises(SystemExit):
                L.parse_args(["--only", "studio,../x"])

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

    def test_port_ranges_do_not_overlap_tools(self):
        portal = set(range(L.DEFAULT_PORT, L.DEFAULT_PORT + L.PORT_RANGE))
        for spec in L.TOOLS:
            self.assertFalse(portal & set(range(spec["port"], spec["port"] + 20)), spec["id"])


class PortalHttpTest(Base):
    """入口の画面とAPI。本物のブラウザが送るヘッダー(Host・Origin・Sec-Fetch-*)で安全検査を確かめる"""

    def setUp(self):
        super().setUp()
        self.srv, self.port = L.make_server(0, self.sup)
        self.th = threading.Thread(target=self.srv.serve_forever, daemon=True)
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
        h = {"Content-Type": "application/json", "Origin": "http://" + self.host, "Sec-Fetch-Site": "same-origin"}
        h.update(headers or {})
        return self.req("POST", path, body, h)

    def test_page_and_headers(self):
        r, body = self.req("GET", "/")
        self.assertEqual(r.status, 200)
        self.assertIn("script-src 'self'", r.getheader("Content-Security-Policy"))
        self.assertIn("frame-ancestors 'none'", r.getheader("Content-Security-Policy"))
        self.assertEqual(r.getheader("X-Frame-Options"), "DENY")
        self.assertIn("作業の入口".encode("utf-8"), body)
        for path in ("/portal.js", "/portal.css", "/ui-kit.css", "/ui-kit.js"):
            r, body = self.req("GET", path)
            self.assertEqual(r.status, 200, path)
            self.assertEqual(r.getheader("X-Content-Type-Options"), "nosniff")
            self.assertGreater(len(body), 100, path)
        r, _ = self.req("GET", "/launch.py")   # コードや他のファイルは配らない
        self.assertEqual(r.status, 404)

    def test_host_check(self):
        r, _ = self.req("GET", "/api/status", headers={"Host": "evil.example:%d" % self.port})
        self.assertEqual(r.status, 403)
        r, _ = self.post("/api/tools/studio/start", headers={"Host": "evil.example"})
        self.assertEqual(r.status, 403)

    def test_cross_site_reads_and_navigation(self):
        r, _ = self.req("GET", "/api/status", headers={"Sec-Fetch-Site": "cross-site"})
        self.assertEqual(r.status, 403)
        nav = {"Sec-Fetch-Site": "same-site", "Sec-Fetch-Mode": "navigate", "Sec-Fetch-Dest": "document"}
        r, _ = self.req("GET", "/", headers=nav)   # 各ツールの画面のリンクで入口を開くのはよい
        self.assertEqual(r.status, 200)
        r, _ = self.req("GET", "/api/status", headers=nav)   # API は同じ画面からだけ
        self.assertEqual(r.status, 403)
        r, _ = self.req("GET", "/", headers=dict(nav, **{"Sec-Fetch-Dest": "iframe"}))
        self.assertEqual(r.status, 403)

    def test_post_guards(self):
        r, _ = self.req("POST", "/api/tools/studio/start", b"{}", {"Content-Type": "text/plain"})
        self.assertEqual(r.status, 415)
        r, _ = self.post("/api/tools/studio/start", headers={"Origin": "http://evil.example"})
        self.assertEqual(r.status, 403)
        r, _ = self.post("/api/tools/studio/start", headers={"Sec-Fetch-Site": "cross-site"})
        self.assertEqual(r.status, 403)
        r, _ = self.post("/api/tools/studio/start", headers={"Origin": "http://localhost:%d" % (self.port + 1)})
        self.assertEqual(r.status, 403)
        r, _ = self.post("/api/tools/studio/start", body=b"[1]")
        self.assertEqual(r.status, 400)
        r, _ = self.post("/api/tools/studio/start", body=b"x" * 5000)
        self.assertEqual(r.status, 413)
        r, _ = self.post("/api/tools/nope/start")
        self.assertEqual(r.status, 404)
        r, _ = self.post("/api/tools/studio/delete")
        self.assertEqual(r.status, 404)
        self.assertEqual(self.state("studio"), "stopped", "拒否したのに起動した")

    def test_actions_and_status(self):
        r, body = self.post("/api/tools/studio/start")
        self.assertEqual(r.status, 200)
        self.assertEqual(json.loads(body)["tool"]["state"], "starting")
        self.sup.start_monitor()
        self.assertTrue(self.wait_state("studio", "running"))
        r, body = self.req("GET", "/api/status", headers={"Sec-Fetch-Site": "same-origin"})
        st = json.loads(body)
        self.assertEqual(st["app"], L.APP_ID)
        self.assertEqual(st["version"], L.VERSION)
        by = {t["id"]: t for t in st["tools"]}
        self.assertEqual(by["studio"]["state"], "running")
        self.assertEqual(by["studio"]["port"], self.ports["studio"])
        self.assertEqual(by["transcribe"]["state"], "stopped")
        r, body = self.post("/api/tools/studio/restart")
        self.assertEqual(json.loads(body)["tool"]["state"], "starting")
        self.assertTrue(self.wait_state("studio", "running"))
        r, body = self.post("/api/tools/studio/stop")
        self.assertEqual(json.loads(body)["tool"]["state"], "stopped")

    def test_log_endpoint(self):
        self.sup.start("studio")
        self.sup.start_monitor()
        self.assertTrue(self.wait_state("studio", "running"))
        r, body = self.req("GET", "/api/log?tool=studio&lines=5")
        j = json.loads(body)
        self.assertTrue(j["exists"])
        self.assertLessEqual(len(j["lines"]), 5)
        self.assertTrue(any("listening" in ln for ln in j["lines"]))
        self.assertIn("studio.log", j["log"])
        for bad in ("../launcher", "..%2F..%2Fetc%2Fpasswd", "", "STUDIO"):
            r, _ = self.req("GET", "/api/log?tool=" + bad)
            self.assertEqual(r.status, 404, bad)
        r, body = self.req("GET", "/api/log?tool=studio&lines=abc")
        self.assertEqual(r.status, 200)
        r, body = self.req("GET", "/api/log?tool=transcribe")
        self.assertEqual(json.loads(body)["exists"], False)

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


def _copy_tool(src, dst):
    shutil.copytree(src, dst, ignore=shutil.ignore_patterns(
        "__pycache__", "*.log", "data.json*", "feedback.jsonl*", "config.json", "settings*.json", "registry.json", "cache", "archive",
        "exports", "clips", "transcripts", "dataset", "models", "work", ".venv", "*.mp4", "resolve-ui-test", "node_modules"))


@unittest.skipUnless(all(os.path.isfile(os.path.join(REPO, s["dir"], "serve.py")) for s in L.TOOLS), "本物のツールのフォルダが無い")
class RealToolsTest(unittest.TestCase):
    """本物の3ツール(疑似モード)を一時フォルダに写して、入口から起動 → 3つとも動作中 → 各ツールの「他のツール」の
    ポート共有(.runtime・/api/siblings)が働く → まとめて停止で .runtime が消える、を確かめる"""

    def test_real_tools(self):
        tmp = tempfile.mkdtemp(prefix="ytt-launch-real-")
        rdir = os.path.join(tmp, ".runtime")
        env = {"YTT_RUNTIME_DIR": rdir, "STUDIO_FAKE": "1", "TRANSCRIBE_BACKEND": "fake"}
        try:
            for s in L.TOOLS:
                _copy_tool(os.path.join(REPO, s["dir"]), os.path.join(tmp, s["dir"]))
            shutil.copytree(os.path.join(REPO, "ytt_core"), os.path.join(tmp, "ytt_core"), ignore=shutil.ignore_patterns("__pycache__"))   # 共通部品(本物と同じ並び)
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
                    time.sleep(7)
                    after = len(L.tail(tx.log_path, 10000) or [])
                    self.assertLessEqual(after - before, 1, "\n".join((L.tail(tx.log_path, 20) or [])))
                    self.assertEqual(sup.by_id["transcribe"].snapshot()["state"], "running")
                finally:
                    sup.close()
                    sup.stop_all()
                for t in sup.tools:
                    self.assertEqual(t.snapshot()["state"], "stopped", t.id)
                    self.assertFalse(os.path.exists(os.path.join(rdir, t.id + ".json")), t.id)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
