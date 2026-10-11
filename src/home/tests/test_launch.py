# -*- coding: utf-8 -*-
"""入口(src/home/launch.py)のテスト。  python -m unittest src/home/tests/test_launch.py -v

- 偽のツール(serve.py の約束だけをまねた小さなサーバー)で、起動・停止・再起動・異常終了・別の画面で起動済み・
  強制終了・ポートの繰り上げ・入口の画面の安全検査を確かめる
- 本物の3ツール(疑似モード)を一時フォルダに写して、入口から起動・停止できることを確かめる(RealToolsTest)
ポートは OS に空きを選ばせるので、本物のツールが動いている PC でも走らせられる。
"""
import http.client
import io
import json
import os
os.environ.setdefault("YTT_DATA_DIR", "inplace")   # テストは作業データを本物の置き場所(AppData など)に書かない(ytt.datadir)
import shutil
import socket
import sys
import tempfile
import textwrap
import threading
import time
import unittest
from unittest import mock

TESTS = os.path.dirname(os.path.abspath(__file__))   # src/home/tests
HERE = os.path.dirname(TESTS)   # home(入口の部品)
sys.path.insert(0, HERE)
sys.path.insert(0, TESTS)
import launch as L  # noqa: E402
from ytt import layout  # noqa: E402  (launch がリポジトリ直下を sys.path に入れる)

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

VERSIONS = {"studio": "0.2.0", "transcribe": "0.2.0", "cut2resolve": "0.2.0"}   # 版は全体で 1 つ(RS5-E。ytt/version.py)なので全ツール同じ


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
    end = time.time() + timeout
    while time.time() < end:
        v = fn()
        if v:
            return v
        time.sleep(step)
    return fn()


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
        self.assertIn("ホームから起動", text)
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
        d = os.path.join(self.root, layout.TOOL_DIRS["studio"])
        with open(os.path.join(d, "serve.py"), encoding="utf-8") as f:
            src = f.read()
        old_dir = os.path.join(self.tmp, "old", layout.TOOL_DIRS["studio"])
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
        L.fsio.rotate(p, 10)   # 入口のログの回し方(0.50.1 で launch.rotate → fsio.rotate。名前は .old.log のまま)
        self.assertFalse(os.path.exists(p))
        self.assertTrue(os.path.exists(os.path.join(self.tmp, "b.old.log")))

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
        # 画面なし(RS7-2 G5a): 既定はオフ・--port と一緒に使える・画面を開く --app-window とは一緒にしない
        self.assertFalse(L.parse_args([]).headless)
        a = L.parse_args(["--headless", "--port", "8750", "--only", "transcribe"])
        self.assertEqual((a.headless, a.port, a.only), (True, 8750, ["transcribe"]))
        with mock.patch("sys.stderr"), self.assertRaises(SystemExit):
            L.parse_args(["--headless", "--app-window"])

    def test_move_docs_on_start(self):
        """RS8 B2-3: 起動のときの文書の移行。inplace(テスト)は何もしない・バックアップが済んでいなければ移さない・失敗しても上げない"""
        from types import SimpleNamespace
        tmp = tempfile.mkdtemp(prefix="movedocs-")
        self.addCleanup(shutil.rmtree, tmp, True)
        tx = os.path.join(tmp, "transcribe", "transcripts")
        os.makedirs(tx)
        with open(os.path.join(tx, "0123456789ab.json"), "w", encoding="utf-8") as f:
            json.dump({"id": "0123456789ab", "sourcePath": os.path.join(tmp, "desktop", "a.mp4")}, f)
        srv = SimpleNamespace(sup=SimpleNamespace(root=tmp), backup=SimpleNamespace(last={}))
        logs = []
        self.assertIsNone(L.move_docs(srv, logs.append))   # inplace
        with mock.patch.object(L.datadir, "data_root", return_value=tmp), mock.patch.object(L.txindex, "folder", return_value=tx), \
                mock.patch.object(L.datadir, "studio_out_dir", return_value=os.path.join(tmp, "exports")):
            with mock.patch.object(L.machine_mod, "get", return_value=False):   # この PC の設定 docMove の既定 = オフ
                self.assertEqual(L.move_docs(srv, logs.append), {"state": "off", "moved": 0})
            on = mock.patch.object(L.machine_mod, "get", side_effect=lambda f: True if f == "docMove" else None)
            on.start()
            self.addCleanup(on.stop)
            self.assertEqual(L.move_docs(srv, logs.append)["state"], "waitBackup")
            self.assertTrue(os.path.isfile(os.path.join(tx, "0123456789ab.json")))
            srv.backup.last = {"ok": 1700000000.0}
            r = L.move_docs(srv, logs.append)
            self.assertEqual((r["state"], r["moved"], r["kept"]), ("done", 0, {"noHome": 1}))
            self.assertTrue(os.path.isfile(os.path.join(tx, "0123456789ab.json")))
            with mock.patch.object(L.docmove_mod, "run", side_effect=OSError("x")):
                self.assertIsNone(L.move_docs(srv, logs.append))
        self.assertTrue(any("移せませんでした" in x for x in logs))

    def test_move_marks_on_start(self):
        """RS8 B3-8: 起動のときの配信の記録の移行。inplace は何もしない・スイッチ markMove がオフなら移さない(書き出し先の繋ぎ直しは毎回)・
        バックアップが済んでいなければ移さない・失敗しても上げない"""
        from types import SimpleNamespace
        tmp = tempfile.mkdtemp(prefix="movemarks-")
        self.addCleanup(shutil.rmtree, tmp, True)
        data = os.path.join(tmp, "studio", "data.json")
        os.makedirs(os.path.dirname(data))
        with open(data, "w", encoding="utf-8") as f:
            json.dump({"schema": "clip-studio/v1", "videos": {"abcdefghijk": {"id": "abcdefghijk", "kind": "youtube", "marks": []}}, "groups": {}}, f)
        srv = SimpleNamespace(sup=SimpleNamespace(root=tmp), backup=SimpleNamespace(last={}))
        logs = []
        self.assertIsNone(L.move_marks(srv, logs.append))   # inplace
        with mock.patch.object(L.datadir, "data_root", return_value=tmp), mock.patch.object(L.placement, "studio_data", return_value=data), \
                mock.patch.object(L.cases_mod, "locations", return_value={"cases": os.path.join(tmp, "app", "cases.json")}), \
                mock.patch.object(L.datadir, "studio_out_dir", return_value=os.path.join(tmp, "exports")):
            with mock.patch.object(L.machine_mod, "get", return_value=False):   # この PC の設定 markMove の既定 = オフ
                self.assertEqual(L.move_marks(srv, logs.append), {"state": "off", "moved": 0, "relinked": 0})
            self.assertEqual(L.markmove_mod.read_result(data)["outDirs"], [os.path.join(tmp, "exports")], "オフでも書き出し先は覚える")
            on = mock.patch.object(L.machine_mod, "get", side_effect=lambda f: True if f == "markMove" else None)
            on.start()
            self.addCleanup(on.stop)
            self.assertEqual(L.move_marks(srv, logs.append)["state"], "waitBackup")
            srv.backup.last = {"ok": 1700000000.0}
            r = L.move_marks(srv, logs.append)
            self.assertEqual((r["state"], r["moved"], r["kept"]), ("done", 0, {}))   # 書き出したマークの無い配信は対象でない
            with mock.patch.object(L.markmove_mod, "run", side_effect=OSError("x")):
                self.assertIsNone(L.move_marks(srv, logs.append))
            with mock.patch.object(L.markmove_mod, "relink_out_dir", side_effect=OSError("y")):
                self.assertEqual(L.move_marks(srv, logs.append)["relinked"], 0)
        self.assertTrue(any("移せませんでした" in x for x in logs))
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
        h = {"Content-Type": "application/json", "Origin": "http://" + self.host, "Sec-Fetch-Site": "same-origin", "X-YTT-Token": self.srv.token}
        h.update(headers or {})
        return self.req("POST", path, body, h)

    def test_page_and_headers(self):
        r, body = self.req("GET", "/")
        self.assertEqual(r.status, 200)
        self.assertIn("script-src 'self'", r.getheader("Content-Security-Policy"))
        self.assertIn("frame-ancestors 'none'", r.getheader("Content-Security-Policy"))
        self.assertEqual(r.getheader("X-Frame-Options"), "DENY")
        self.assertIn("動画編集ツール — ホーム".encode("utf-8"), body)
        for path in ("/portal.js", "/portal.css", "/ui-kit.css", "/ui-kit.js", "/settings.js", "/settings.css", "/settings-schema.json"):
            r, body = self.req("GET", path)
            self.assertEqual(r.status, 200, path)
            self.assertEqual(r.getheader("X-Content-Type-Options"), "nosniff")
            self.assertGreater(len(body), 100, path)
        r, body = self.req("GET", "/settings")   # 設定の画面(S5): 入口の画面と同じ CSP・合言葉
        self.assertEqual(r.status, 200)
        self.assertIn("script-src 'self'", r.getheader("Content-Security-Policy"))
        self.assertIn("動画編集ツール — 設定".encode("utf-8"), body)
        self.assertIn(b'name="ytt-token"', body)
        r, _ = self.req("GET", "/settings/")
        self.assertEqual((r.status, r.getheader("Location")), (302, "/settings"))
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
        r, _ = self.req("POST", "/api/tools/studio/start", b"{}", {"Content-Type": "text/plain", "X-YTT-Token": self.srv.token})
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

    def test_post_body_edges(self):
        """本文の読み取りの境目(0.50.1 で httpsec.read_json_body に寄せた。応答の番号と文は前と同じ)"""
        def err(r, body):
            return r.status, json.loads(body).get("error")
        self.assertEqual(err(*self.post("/api/cases/update", body=b"")), (400, "bad_request"))   # 空の本文は {} として読む(案件の検査で断る)
        self.assertEqual(err(*self.post("/api/cases/update", body=b'{"id": NaN}')), (400, "bad_request"))   # NaN は今までどおり通す(案件の検査で断る)
        self.assertEqual(err(*self.post("/api/cases/update", headers={"Content-Length": "abc"}, body=None)), (413, "size"))
        self.assertEqual(err(*self.post("/api/cases/update", headers={"Content-Type": "application/json; charset=UTF-8"}, body=b"[]")), (400, "json"))
        self.assertEqual(err(*self.post("/api/cases/update", body=b'{"a": 1')), (400, "json"))
        self.assertEqual(err(*self.post("/api/cases/update", body=b"[" * 3000)), (400, "json"))   # 深い入れ子でも落ちずに 400
        self.assertEqual(err(*self.post("/api/cases/update", headers={"Content-Type": "text/plain"})), (415, "content_type"))
        r, _ = self.post("/api/tools/studio/start", headers={"X-YTT-Token": "é" * 10})   # ASCII 以外の合言葉でも落ちずに 403
        self.assertEqual(r.status, 403)

    def test_extra_dirs(self):
        """空き容量・ごみ箱フォルダの書き出し先(0.50.1 で datadir.studio_out_dir に寄せた)。settings.json が無ければ今までどおり []"""
        sdir = os.path.join(self.tmp, "studio-data")
        os.makedirs(sdir)
        path = os.path.join(sdir, "settings.json")
        out = os.path.join(self.tmp, "書き出し")
        with mock.patch.object(L.datadir, "resolve", lambda tool, root=None, env=None: sdir):
            self.assertEqual(self.srv._extra_dirs(), [])
            for st, want in (({"outDir": out}, [out]), ({}, [os.path.join(sdir, "exports")]), ({"outDir": ""}, [os.path.join(sdir, "exports")]),
                             ([1], [os.path.join(sdir, "exports")]), ({"outDir": "rel/x"}, [os.path.join(sdir, "exports")])):
                with open(path, "w", encoding="utf-8") as f:
                    json.dump(st, f)
                self.assertEqual(self.srv._extra_dirs(), want, st)

    def test_ytt_request_drains_refused_body(self):
        """不具合の疑い 1(10-08 の見直し): 取り込んだ画面から回ってきた api/ytt/… を Host/Origin・合言葉で断るときも本文を読み捨てる
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

    def test_health_api(self):
        """「調子」(段9 9-1): 版・ワーカー・空き容量・エラーの件数・作業データの大きさ(別のスレッドで数える)"""
        r, body = self.req("GET", "/api/health")
        self.assertEqual(r.status, 200)
        h = json.loads(body)
        for k in ("at", "versions", "worker", "disk", "errors", "heavy", "computing", "data", "tools"):
            self.assertIn(k, h)
        self.assertEqual([v["tool"] for v in h["versions"]], [t.id for t in self.sup.tools])
        self.assertTrue(h["disk"] and h["disk"][0]["totalBytes"] > 0)
        self.assertEqual(h["errors"]["clientLast24h"], 0)
        for _ in range(60):
            if h["data"] is not None:
                break
            time.sleep(0.1)
            h = json.loads(self.req("GET", "/api/health")[1])
        self.assertIsNotNone(h["data"])
        self.assertIn("ffmpeg", h["tools"])
        r, body = self.req("GET", "/api/health?refresh=1")
        self.assertEqual(r.status, 200)

    def test_cleanup_api(self):
        """片付け(段9 9-2): 候補の一覧の形・移す物が無い/候補に出していない物は移さない"""
        r, body = self.req("GET", "/api/cleanup")
        self.assertEqual(r.status, 200)
        d = json.loads(body)
        self.assertEqual([k["kind"] for k in d["kinds"]], ["export", "work", "cache", "log", "intake"])
        for k in ("bytes", "trash", "trashRoots", "keepDays", "packAgeDays"):
            self.assertIn(k, d)
        r, _ = self.post("/api/cleanup", body=json.dumps({"ids": []}).encode())
        self.assertEqual(r.status, 400)
        r, body = self.post("/api/cleanup", body=json.dumps({"ids": ["nope"]}).encode())
        self.assertEqual((r.status, json.loads(body)["unknown"], json.loads(body)["moved"]), (200, ["nope"], []))

    def test_restart_self(self):
        """起動し直す(段9 9-3): 重い処理の最中は 409 で断る。空いていれば新しい入口を --wait-port で起こし、後始末を頼む"""
        from manage.ops import restart as R
        calls, stops = [], []
        saved = (R.spawn_new_launcher, self.srv.request_shutdown, R.can_restart)
        R.spawn_new_launcher = lambda root, args=(), log=None, **kw: calls.append(list(args))
        self.srv.request_shutdown = lambda: stops.append(1)
        try:
            R.can_restart = lambda *a, **k: "実行中の処理があります(文字起こし)。終わってから起動し直してください"
            r, body = self.post("/api/ytt/restart-self")
            self.assertEqual((r.status, json.loads(body)["error"]), (409, "busy"))
            self.assertEqual(calls, [])
            R.can_restart = saved[2]
            r, body = self.post("/api/ytt/restart-self")
            self.assertEqual(r.status, 200, body)
            self.assertEqual(len(calls), 1)
            self.assertIn("--wait-port", calls[0])
            self.assertEqual(calls[0][calls[0].index("--port") + 1], str(self.srv.server_address[1]))
            for _ in range(30):
                if stops:
                    break
                time.sleep(0.05)
            self.assertEqual(stops, [1])
        finally:
            R.spawn_new_launcher, self.srv.request_shutdown, R.can_restart = saved

    def test_restart_self_refused_when_headless(self):
        """画面なしの入口(--headless)は起動し直さない(新しい入口が送るアプリの子にならない)= 409 で新しい入口を起こさない"""
        from manage.ops import restart as R
        calls = []
        saved = R.spawn_new_launcher
        R.spawn_new_launcher = lambda root, args=(), log=None, **kw: calls.append(list(args))
        self.srv.headless = True
        try:
            r, body = self.post("/api/ytt/restart-self")
            self.assertEqual((r.status, json.loads(body)["error"]), (409, "headless"))
            self.assertEqual(calls, [])
        finally:
            R.spawn_new_launcher = saved
            self.srv.headless = False

    def test_flow_status_live(self):
        """RS7-2 G5a: GET /api/flow/status の live 欄 = ライブの録画中・検出中・書き出しの途中の数(PortalServer.live_activity)。
        どれかが 0 でなければ idle は偽。リアルタイム切り抜きがオフなら全部 0 で、録画元に問い合わせない"""
        r, body = self.req("GET", "/api/flow/status")
        st = json.loads(body)
        self.assertEqual((st["live"], st["idle"]), ({"recording": 0, "detecting": 0, "exporting": 0}, True))   # 既定(オフ)
        real = self.srv.live
        fake = mock.MagicMock()
        fake.enabled.return_value = True
        fake.recent.return_value = [{"id": "a", "active": True}, {"id": "b", "active": False}]   # 終わって 10 分以内の録画は数えない
        fake.detector.enabled.return_value = True
        fake.detector.heartbeat.return_value = {"recordings": [{"recorder": "local", "id": "a"}, {"recorder": "local", "id": "c"}]}
        fake.detector.running.return_value = True
        fake._exporter.lock = threading.Lock()
        fake._exporter.jobs = [{"state": "fetch"}, {"state": "done", "handoffWait": "disk"}, {"state": "done"}, {"state": "failed"}]
        self.srv.live = fake
        try:
            st = json.loads(self.req("GET", "/api/flow/status")[1])
            self.assertEqual((st["live"], st["idle"], st["queued"], st["running"]), ({"recording": 1, "detecting": 2, "exporting": 2}, False, 0, 0))
            fake.recent.return_value = []
            fake.detector.running.return_value = False   # ワーカーが止まっている = 測っていない
            fake._exporter = None   # 書き出しを一度も使っていない
            st = json.loads(self.req("GET", "/api/flow/status")[1])
            self.assertEqual((st["live"], st["idle"]), ({"recording": 0, "detecting": 0, "exporting": 0}, True))
            fake.recent.side_effect = OSError("録画元につながらない")   # 読めない = 閉じない側
            st = json.loads(self.req("GET", "/api/flow/status")[1])
            self.assertEqual((st["live"]["recording"], st["idle"]), (None, False))
            fake.enabled.return_value = False
            fake.recent.reset_mock()
            st = json.loads(self.req("GET", "/api/flow/status")[1])
            self.assertEqual((st["live"], st["idle"]), ({"recording": 0, "detecting": 0, "exporting": 0}, True))
            fake.recent.assert_not_called()
        finally:
            self.srv.live = real

    def test_restart_self_keeps_autorun_runs(self):
        """まとめて実行の待ち・実行中は断らずに起動し直し、何件が続くかを notice で知らせる(M5。入口 0.41.0)。
        実行中の段の仕事でも、同じツールに人が始めた仕事があれば(others)今までどおり断る"""
        from manage.ops import restart as R

        class Stub:
            def __init__(self, redo):
                self.redo = redo

            def snapshot(self):
                return {"runs": [{"state": "running", "mode": "adopted"}, {"state": "queued", "mode": "request"}]}

            def restart_info(self):
                return {"runs": 2, "redo": self.redo}

            def close(self):
                pass
        calls, stops = [], []
        saved = (R.spawn_new_launcher, self.srv.request_shutdown, self.srv._autorun, self.srv.sup.status)
        R.spawn_new_launcher = lambda root, args=(), log=None, **kw: calls.append(list(args))
        self.srv.request_shutdown = lambda: stops.append(1)
        heavy = {"limit": 2, "active": [{"tool": "transcribe", "label": "配信の切り抜き", "seconds": 3}], "waiting": []}
        self.srv.sup.status = lambda: {"heavy": heavy}
        try:
            self.srv._autorun = Stub({"tool": "transcribe", "labels": ["配信の切り抜き"], "others": ["人が入れた文字起こし"]})
            r, body = self.post("/api/ytt/restart-self")
            self.assertEqual((r.status, calls), (409, []), body)
            self.assertIn("配信の切り抜き", json.loads(body)["message"])
            self.srv._autorun = Stub({"tool": "transcribe", "labels": ["配信の切り抜き"], "others": []})
            r, body = self.post("/api/ytt/restart-self")
            self.assertEqual((r.status, len(calls)), (200, 1), body)
            self.assertEqual(json.loads(body), {"ok": True, "notice": R.RESUME_NOTICE % 2})
            for _ in range(30):
                if stops:
                    break
                time.sleep(0.05)
            self.assertEqual(stops, [1])
        finally:
            R.spawn_new_launcher, self.srv.request_shutdown, self.srv._autorun, self.srv.sup.status = saved

    def test_csrf_token(self):
        """書き込み系の API は、画面に埋め込んだ合言葉(CSRF トークン)が一致しないと受け付けない"""
        r, body = self.req("GET", "/")
        self.assertIn(('<meta name="ytt-token" content="%s">' % self.srv.token).encode(), body)
        for bad in ("", "x" * len(self.srv.token), self.srv.token + "x"):
            r, _ = self.post("/api/tools/studio/start", headers={"X-YTT-Token": bad})
            self.assertEqual(r.status, 403, bad)
        h = {"Content-Type": "application/json", "Origin": "http://" + self.host}
        r, _ = self.req("POST", "/api/shutdown", b"{}", h)   # 合言葉なし
        self.assertEqual(r.status, 403)
        self.assertFalse(self.srv.closing.is_set())
        self.assertEqual(self.state("studio"), "stopped")
        other, _ = L.make_server(0, self.sup)
        try:
            self.assertNotEqual(other.token, self.srv.token)   # 起動ごとに変わる
        finally:
            other.server_close()

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

    def test_autorun_history(self):
        """段2 B-6: まとめて実行の記録(作業データの logs/autorun-runs.jsonl)。limit は既定 50・最大 200・前回の結果は /api/autorun の past"""
        logs = self.sup.logs_dir
        self.assertTrue(os.path.abspath(logs).startswith(os.path.abspath(self.tmp)), logs)   # テストは一時フォルダに書く
        os.makedirs(logs, exist_ok=True)
        with open(os.path.join(logs, "autorun-runs.jsonl"), "w", encoding="utf-8") as f:
            for i in range(250):
                f.write(json.dumps({"v": 1, "id": "r%03d" % i, "kind": "video", "videoId": "v%03d" % i, "docId": None, "state": "error",
                                    "error": "理由%d" % i, "steps": []}, ensure_ascii=False) + "\n")
        r, body = self.req("GET", "/api/autorun")
        j = json.loads(body)
        self.assertEqual((j["runs"], len(j["past"]), j["past"][0]["id"], j["past"][0]["error"]), ([], 50, "r249", "理由249"))
        for q, n, first in (("", 50, "r249"), ("?limit=1000", 200, "r249"), ("?limit=abc&offset=x", 50, "r249"), ("?limit=0", 1, "r249"),
                            ("?limit=20&offset=240", 10, "r009"), ("?offset=-3", 50, "r249")):
            r, body = self.req("GET", "/api/autorun/history" + q)
            self.assertEqual(r.status, 200, q)
            h = json.loads(body)
            self.assertEqual((len(h["runs"]), h["runs"][0]["id"], h["total"]), (n, first, 250), q)
        r, _ = self.req("GET", "/api/autorun/history", headers={"Sec-Fetch-Site": "cross-site"})   # ほかのサイトからは読めない
        self.assertEqual(r.status, 403)

    def test_flow_submit_and_status(self):
        """RS7-1 S4: ② の口 POST /api/flow/submit {envelope, spec}(合言葉が要る・形が違えば 400 と理由)と GET /api/flow/status"""
        r, body = self.req("GET", "/api/flow/status")
        j = json.loads(body)
        self.assertEqual((r.status, j["queued"], j["running"], j["idle"], j["runs"]), (200, 0, 0, True, []))
        media = os.path.join(self.tmp, "切り抜き.mp4")
        with open(media, "wb") as f:
            f.write(b"x")
        env = {"id": "0123456789", "kind": "file", "input": {"path": media, "title": "切り抜き"}, "legacy": {"mode": "file"}}
        payload = json.dumps({"envelope": env, "spec": {"transcribe": {"model": "large-v3"}}}, ensure_ascii=False).encode("utf-8")
        r, _ = self.post("/api/flow/submit", headers={"X-YTT-Token": "x"}, body=payload)   # 書き込み系 = 合言葉が要る
        self.assertEqual(r.status, 403)
        for bad, why in (({"envelope": dict(env, kind="nai")}, "封筒.kind"),
                         ({"envelope": dict(env, input={"path": os.path.join(self.tmp, "nai.mp4")})}, "見つかりません"),
                         ({"envelope": env, "spec": {"transcribe": {"engine": "nai"}}}, "transcribe.engine"),
                         ({"envelope": "x"}, "封筒"), ({}, "封筒")):
            r, body = self.post("/api/flow/submit", body=json.dumps(bad, ensure_ascii=False).encode("utf-8"))
            self.assertEqual(r.status, 400, bad)
            self.assertIn(why, json.loads(body)["message"], bad)
        txt = os.path.join(self.tmp, "メモ.txt")
        with open(txt, "wb") as f:
            f.write(b"x")
        r, body = self.post("/api/flow/submit", body=json.dumps({"envelope": dict(env, input={"path": txt})}).encode("utf-8"))
        self.assertEqual((r.status, "動画・音声" in json.loads(body)["message"]), (400, True))   # 動画・音声の拡張子だけ
        r, body = self.post("/api/flow/submit", body=payload)
        j = json.loads(body)
        self.assertEqual((r.status, j["run"]["id"], j["run"]["kind"], j["run"]["sourcePath"]), (200, "0123456789", "file", media))
        r, body = self.req("GET", "/api/flow/status")
        st = json.loads(body)
        self.assertEqual([x["id"] for x in st["runs"]], ["0123456789"])
        self.assertEqual(next(x for x in self.srv.autorun.runs if x.id == "0123456789").spec["transcribe"]["model"], "large-v3")   # 受けた束のまま
        r, _ = self.req("GET", "/api/flow/status", headers={"Sec-Fetch-Site": "cross-site"})   # ほかのサイトからは読めない
        self.assertEqual(r.status, 403)

    def test_flow_submit_live_goes_to_live(self):
        """RS7-2 G2b: 封筒 kind live は ② の口からライブ係(Live.submit)へ(入口が Queue.set_live_hook で登録)。リアルタイム切り抜きがオフなら 400 と理由
        (録画元・yt-dlp に聞かない)。オンなら Live.submit が受けた封筒 + 束で録画を始める"""
        env = {"id": "live000001", "kind": "live", "input": {"videoId": "abcdefghijk", "title": "配信"}}
        self.srv.live.probe = lambda url: self.fail("オフなら配信の状態を調べない")
        r, body = self.post("/api/flow/submit", body=json.dumps({"envelope": env}).encode("utf-8"))
        self.assertEqual((r.status, "オフ" in json.loads(body)["message"]), (400, True))
        seen = []
        with mock.patch.object(self.srv.live, "submit", lambda e, s: seen.append((e, s)) or {"id": e["id"], "live": True}):
            r, body = self.post("/api/flow/submit", body=json.dumps({"envelope": env, "spec": {"adopt": {"top": 10}}}).encode("utf-8"))
        self.assertEqual((r.status, json.loads(body)["run"]), (200, {"id": "live000001", "live": True}))
        self.assertEqual((seen[0][0]["kind"], seen[0][1]["adopt"]["top"]), ("live", 10))
        self.assertEqual(self.srv.autorun.status()["runs"], [], "kind live は待ち行列に積まない")

    def test_intake_api(self):
        """友人からの依頼の受付(src/human/friend/intake.py): 状態・設定(api/ytt/prefs の節 intake)・今すぐ確認。受付の設定は作業データの prefs.json(一時フォルダ)"""
        r, body = self.req("GET", "/api/intake")
        j = json.loads(body)
        self.assertEqual((r.status, j["enabled"], j["state"], j["requests"]), (200, False, "off", []))
        folder = os.path.join(self.tmp, "依頼")
        os.makedirs(folder)
        r, body = self.post("/api/ytt/prefs", body=json.dumps({"op": "patch", "section": "intake", "value": {"folder": "\\\\srv\\share"}}).encode())
        self.assertEqual(r.status, 400)
        self.assertIn("ネットワーク", json.loads(body)["message"])
        r, body = self.post("/api/ytt/prefs", body=json.dumps({"op": "patch", "section": "intake", "value": {"enabled": True, "folder": folder, "top": 4}}).encode())
        self.assertEqual((r.status, json.loads(body)["value"]["top"]), (200, 4))
        self.srv.intake.scan()
        r, body = self.req("GET", "/api/intake")
        j = json.loads(body)
        self.assertEqual((j["enabled"], j["folder"], j["state"], j["top"]), (True, folder, "watching", 4))
        r, body = self.post("/api/intake/scan", headers={"X-YTT-Token": "x"})   # 合言葉が要る
        self.assertEqual(r.status, 403)
        r, body = self.post("/api/intake/scan")
        self.assertEqual((r.status, json.loads(body)["state"]), (200, "watching"))
        r, _ = self.req("GET", "/api/intake", headers={"Sec-Fetch-Site": "cross-site"})
        self.assertEqual(r.status, 403)

    def test_backup_api(self):
        """作業データのバックアップ(src/manage/keep/backup.py): 状態・設定(api/ytt/prefs の節 backup)・今すぐ写す。テスト(inplace)では作業データの親が無いので写さない"""
        r, body = self.req("GET", "/api/backup")
        j = json.loads(body)
        self.assertEqual((r.status, j["enabled"], j["state"], j["everyHours"], j["source"]), (200, False, "off", 1, None))
        r, body = self.post("/api/ytt/prefs", body=json.dumps({"op": "patch", "section": "backup", "value": {"enabled": True}}).encode())
        self.assertEqual(r.status, 400)   # 先のフォルダが無いままではオンにできない
        r, body = self.post("/api/ytt/prefs", body=json.dumps({"op": "patch", "section": "backup", "value": {"folder": "\\\\srv\\share"}}).encode())
        self.assertEqual(r.status, 400)
        dest = os.path.join(self.tmp, "先")
        r, body = self.post("/api/ytt/prefs", body=json.dumps({"op": "patch", "section": "backup", "value": {"enabled": True, "folder": dest, "everyHours": 12}}).encode())
        self.assertEqual((r.status, json.loads(body)["value"]), (200, {"enabled": True, "folder": dest, "everyHours": 12}))
        r, body = self.post("/api/backup/run", headers={"X-YTT-Token": "x"})   # 合言葉が要る
        self.assertEqual(r.status, 403)
        r, body = self.post("/api/backup/run")
        self.assertEqual((r.status, json.loads(body)["folder"]), (200, dest))
        self.srv.backup.tick()   # inplace では写さない(本物の作業データに触らない)
        self.assertEqual((self.srv.backup.state, os.path.exists(dest)), ("off", False))
        r, _ = self.req("GET", "/api/backup", headers={"Sec-Fetch-Site": "cross-site"})
        self.assertEqual(r.status, 403)

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
    """不具合の疑い 2(10-08 の見直し): main() の終了の後始末は 1 回だけ。「すべて終了」(request_shutdown)のあとに finally でもう一度走らない・
    Ctrl+C・黒い画面の×(KeyboardInterrupt)の経路でもまとめて実行を閉じる(閉じないと実行中の段が「失敗」として記録され、次の起動で続かない。M5)"""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="ytt-main-")
        self.root = make_fake_root(self.tmp)
        self.saved_app = L.datadir.registered("app")

    def tearDown(self):
        L.datadir.register("app", self.saved_app)
        shutil.rmtree(self.tmp, ignore_errors=True)

    def run_main(self, on_live_start):
        got, unmounts, logs = {}, [], []
        real_make_server = L.make_server

        def make_server(port, sup):
            got["srv"], p = real_make_server(port, sup)
            return got["srv"], p

        def make_logger(path):   # 黒い画面へは出さない
            def log(msg, console=True):
                logs.append(msg)
            log.flush = lambda timeout=1.0: None
            return log

        def live_start(live):   # 起動の最後のほう(まとめて実行を作ったあと)で、終了の合図を送る
            on_live_start(got["srv"])

        patches = [mock.patch.dict(os.environ, {"YTT_RUNTIME_DIR": os.path.join(self.tmp, ".runtime")}),
                   mock.patch.object(L, "ROOT", self.root), mock.patch.object(L, "make_server", make_server),
                   mock.patch.object(L, "make_logger", make_logger),
                   mock.patch.object(L, "install_stop_signals"), mock.patch.object(L, "ignore_stop_signals"),
                   mock.patch.object(L, "analytics_mod", None), mock.patch.object(L.Supervisor, "start_all"),
                   mock.patch.object(L.Supervisor, "unmount_all", lambda sup: unmounts.append(1)),
                   mock.patch.object(L.live_mod.Live, "start", live_start), mock.patch.object(L.PortalServer, "purge_trash", lambda srv: None)]
        for p in patches:
            p.start()
        try:
            self.assertEqual(L.main(["--port", "0", "--no-open", "--no-mount"]), 0)
        finally:
            for p in reversed(patches):
                p.stop()
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

    def run_headless(self, argv, on_ready):
        """画面なしで main を本物のサーバー(ポート 0)で起こす。標準出力の ready の 1 行が出たら on_ready(srv, ready) を呼んでから「すべて終了」。
        -> (終了コード, srv, 標準出力, 起こした常駐の名前, 画面を開いた回数)"""
        got, started, opened = {}, [], []
        out = io.StringIO()
        real_make_server = L.make_server

        def make_server(port, sup):
            got["srv"], p = real_make_server(port, sup)
            return got["srv"], p

        def make_logger(path):
            log = lambda msg, console=True: None
            log.flush = lambda timeout=1.0: None
            return log

        def live_start(live):   # ready は Live.start のあとに出る = 裏で ready を待ってから終える(画面ありはすぐ終える)
            started.append("live")
            if "--headless" not in argv:
                got["srv"].request_shutdown()
                return

            def wait_ready():
                for _ in range(200):
                    line = out.getvalue()
                    if line.endswith("\n"):
                        try:
                            got["result"] = on_ready(got["srv"], json.loads(line))
                        finally:
                            got["srv"].request_shutdown()
                        return
                    time.sleep(0.05)
                got["srv"].request_shutdown()
            threading.Thread(target=wait_ready, daemon=True).start()

        def rec(name):
            return lambda *a, **k: started.append(name)

        analytics = mock.MagicMock()
        patches = [mock.patch.dict(os.environ, {"YTT_RUNTIME_DIR": os.path.join(self.tmp, ".runtime")}),
                   mock.patch.object(L, "ROOT", self.root), mock.patch.object(L, "make_server", make_server),
                   mock.patch.object(L, "make_logger", make_logger),
                   mock.patch.object(L, "install_stop_signals"), mock.patch.object(L, "ignore_stop_signals"),
                   mock.patch.object(L, "analytics_mod", analytics), mock.patch.object(L.Supervisor, "start_all"),
                   mock.patch.object(L.Supervisor, "unmount_all", lambda sup: None),
                   mock.patch.object(L.live_mod.Live, "start", live_start),
                   mock.patch.object(L.intake_mod.Intake, "start", rec("intake")), mock.patch.object(L.backup_mod.Backup, "start", rec("backup")),
                   mock.patch.object(L.accuracy_mod.Accuracy, "start", rec("accuracy")),
                   mock.patch.object(L.PortalServer, "purge_trash", rec("trash")),
                   mock.patch.object(L.appwindow_mod.Opener, "open_start", lambda op, url: opened.append(url) or "browser"),
                   mock.patch.object(sys, "stdout", out)]
        for p in patches:
            p.start()
        try:
            code = L.main(argv)
            self.assertIs(sys.stdout, out, "標準出力を元に戻していない")
        finally:
            for p in reversed(patches):
                p.stop()
        if analytics.Service.return_value.start.called:
            started.append("analytics")
        return code, got["srv"], out.getvalue(), started, opened, got.get("result")

    def test_headless_ready_line_and_no_watchers(self):
        """RS7-2 G5a: --headless は ③④⑤ の常駐(依頼の受付・バックアップ・精度の自動測定・分析と日報・ごみ箱の片付け)を起こさず、画面を開かない。
        ②(まとめて実行 = Queue・ライブ)は載せる。標準出力は ready の 1 行の JSON だけ(合言葉とポートで ② の口が使える)"""
        def on_ready(srv, ready):
            st, body = _http(ready["port"], "GET", "/api/flow/status")
            st2, body2 = _http(ready["port"], "POST", "/api/ytt/restart-self", b"{}", ready["token"])
            return st, json.loads(body), st2, json.loads(body2)
        code, srv, out, started, opened, res = self.run_headless(["--headless", "--port", "0", "--no-mount"], on_ready)
        self.assertEqual(code, 0)
        self.assertEqual(out.count("\n"), 1, out)
        ready = json.loads(out)
        self.assertEqual(ready, {"event": "ready", "port": srv.server_address[1], "token": srv.token, "pid": os.getpid()})
        self.assertEqual(started, ["live"], "画面なしで ③ の見張りを起こした")
        self.assertEqual(opened, [])
        self.assertTrue(srv.headless)
        self.assertIsNotNone(srv._autorun, "② のまとめて実行を載せていない")
        self.assertTrue(srv._autorun.closed)
        st, status, st2, restart = res
        self.assertEqual((st, status["idle"], status["live"]), (200, True, {"recording": 0, "detecting": 0, "exporting": 0}))
        self.assertEqual((st2, restart["error"]), (409, "headless"))

    def test_headless_does_not_move_docs_without_backup(self):
        """RS8 B2-3: 画面なしも同じ位置で移行を呼ぶが、バックアップが動かない = 記録が無ければ移さない(backup_ok が偽)"""
        calls, real = [], L.move_docs

        def spy(srv, log):
            calls.append(srv.backup.last)
            with mock.patch.object(L.datadir, "data_root", return_value=self.tmp), mock.patch.object(L.machine_mod, "get", return_value=True), \
                    mock.patch.object(L.docmove_mod, "run", side_effect=lambda *a, **k: {"state": "waitBackup", "backup_ok": k["backup_ok"]}):
                return real(srv, log)
        with mock.patch.object(L, "move_docs", spy):
            code, srv, out, started, opened, _ = self.run_headless(["--headless", "--port", "0", "--no-mount"], lambda srv, ready: None)
        self.assertEqual((code, len(calls)), (0, 1))
        self.assertEqual(srv.docs_moved, {"state": "waitBackup", "backup_ok": False})

    def test_normal_start_still_starts_watchers(self):
        """画面ありの起動は今までどおり(見張りを起こす・ready の行を出さない)"""
        code, srv, out, started, opened, _ = self.run_headless(["--port", "0", "--no-mount", "--no-open"], lambda srv, ready: None)
        self.assertEqual((code, out, srv.headless), (0, "", False))
        wait_for(lambda: "trash" in started, 5)   # ごみ箱の片付けは裏のスレッド
        self.assertEqual(sorted(started), ["accuracy", "analytics", "backup", "intake", "live", "trash"])

    def test_headless_existing_launcher_exits_nonzero(self):
        """画面なし: そのポートの範囲に入口がすでに動いている = 画面を開かず、読める文を標準エラーへ出して EXIT_RUNNING"""
        opened = []
        with mock.patch.object(L.appwindow_mod.Opener, "open_start", lambda op, url: opened.append(url)):
            code, logs, err, made = self.run_main_failing(["--headless", "--port", "8700"], existing=True)
        self.assertEqual((code, opened), (L.EXIT_RUNNING, []))
        self.assertIn("すでに起動しています", err)
        self.assertIn("8700", err)
        self.assertEqual(err.count("すでに起動しています"), 1, "標準エラーに 2 回出した")
        self.assertTrue(any("すでに起動しています" in x for x in logs))   # launcher.log にも残す

    def test_headless_lock_busy_exits_running(self):
        code, logs, err, made = self.run_main_failing(["--headless", "--port", "0", "--no-mount"], lock_busy={"pid": 4242, "port": 8700})
        self.assertEqual(code, L.EXIT_RUNNING)
        self.assertIn("4242", err)
        made[0].server_close.assert_called_once()

    def run_main_failing(self, argv, wait_result=None, lock_busy=None, existing=False):
        """RS7-1 1d: 待ちの期限・.flow.lock の先客で、トレースバックにせず読める文を出して非 0 で終わる。existing: 入口がすでに動いている"""
        logs, errs = [], io.StringIO()
        made = []

        def make_logger(path):
            def log(msg, console=True):
                logs.append(msg)
            log.flush = lambda timeout=1.0: None
            return log

        def make_server(port, sup):
            if existing:
                return None, port
            srv = mock.MagicMock()
            made.append(srv)
            return srv, port

        patches = [mock.patch.dict(os.environ, {"YTT_RUNTIME_DIR": os.path.join(self.tmp, ".runtime")}),
                   mock.patch.object(L, "ROOT", self.root), mock.patch.object(L, "make_logger", make_logger),
                   mock.patch.object(L, "make_server", make_server), mock.patch.object(sys, "stderr", errs)]
        if wait_result is not None:
            patches.append(mock.patch.object(L.restart_mod, "wait_old_launcher", lambda port, pid=None: wait_result))
        if lock_busy is not None:
            patches.append(mock.patch.object(L.placement, "acquire", mock.Mock(side_effect=L.placement.LockBusy(lock_busy))))
        for p in patches:
            p.start()
        try:
            code = L.main(argv)
        finally:
            for p in reversed(patches):
                p.stop()
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
        "exports", "clips", "transcripts", "dataset", "models", "work", ".venv", "*.mp4", "resolve-ui-test", "node_modules", "tests"))


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
            from ytt import layout as _layout
            _layout.copy_shared_code(tmp, ignore=shutil.ignore_patterns("__pycache__"), root=REPO)   # 共通のコード(ytt と役割の層 = layout.SHARED_CODE_DIRS。本物と同じ並び)
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
