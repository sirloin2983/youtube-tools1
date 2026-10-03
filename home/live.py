# -*- coding: utf-8 -*-
"""リアルタイム切り抜き(線 D の P1。docs/plan/live-clipping-plan.md の 0)の入口の側。**既定はオフ**(ホームの設定の節 live.enabled)。
オフの間は何もしない: /live/… は今までどおり 404(handle が False を返し、入口の 404 になる)・録画の部品も起動しない・「調子」にも出さない。

オンのとき:
  GET  /live/                         録画と再生の画面(live.html。hls.js は home/vendor/ に同梱 = CSP script-src 'self' のまま)
  GET  /live/api/info                 録画元の一覧(名前・URL。合言葉は出さない)・録画の置き場所の設定
  GET|POST /live/r/<録画元>/<残り>    録画元(recorder/recorder.py)の /live/<残り> へ中継する(同じオリジンのまま。合言葉は入口が付ける)
                                       例: /live/r/local/list・/live/r/local/start・/live/r/local/<録画>/index.m3u8・…/session_001/seg_000000.ts
  GET  /live/api/marks?recorder=&recording=   録画1本のマークと書き出し(P2。中身は home/live_export.py)
  POST /live/api/marks   {op: add|update|delete, recorder, recording, id?, start?, end?, label?, url?, title?}  マーク(押すたびに fsync)
  GET  /live/api/exports                 書き出しのジョブの一覧(状態: 録画待ち・取得中・作り直し中・済み・失敗と理由・取り消し)
  POST /live/api/export  {recorder, recording, markId, transcribe}   書き出しを頼む(録画待ち → 取得 → 30fps → 検証 → 文字起こしへ)
  POST /live/api/export/cancel  {id}     取り消し
  検査は入口の API と同じ(Host・Sec-Fetch-Site。POST は Origin と入口の合言葉 X-YTT-Token も。launch.py の do_GET / do_POST が先に通す)

録画元の一覧(設定 live.recorders。空 = 手元の1つ「この PC」http://127.0.0.1:8730)を通して読む: 2台(P5)のときは一覧に1行足すだけ。
手元の録画元の合言葉は、録画の部品の作業データの token.txt を読む(設定に書かない)。

録画の部品の起動(計画の 0-3 から選んだ形): オンの間、入口が 30 秒ごとに手元の録画元に問い合わせ、動いていなければ入口と切り離して起動する
(別のプロセスグループ・隠れた黒い画面 = 入口の「すべて終了」・黒い画面を閉じる・Ctrl+C で止まらない。落ちても次の見回りで起こし直す)。
スタートアップのショートカットにしない理由: 既定オフ(オンにするまで自動で起動しない)を、ショートカットを置く・消す手作業なしで守れるため。
ログインしたら録画も上げたいときは、今までどおり入口を裏で起動するショートカット(home\\start_hidden.vbs)を置けば、入口が録画の部品も起こす。
"""
import http.client
import json
import os
import re
import subprocess
import sys
import threading
import time
import urllib.parse

from ytt_core import datadir
import live_export  # noqa: E402  (マークと書き出し。P2)
import mount as mount_mod  # noqa: E402  (入口と同じ合言葉を画面に渡す)

CODE_DIR = os.path.dirname(os.path.abspath(__file__))
VENDOR_DIR = os.path.join(CODE_DIR, "vendor")
DEFAULT_FOLDER = r"E:\Video\live-rec"     # recorder/rec_core.py の DEFAULT_FOLDER と同じ(2026-10-04 ユーザー決定)
RECORDER_PORT = 8730                      # recorder/recorder.py の DEFAULT_PORT と同じ
LOCAL = {"id": "local", "name": "この PC", "url": "http://127.0.0.1:%d" % RECORDER_PORT, "token": ""}
PAGES = {"/live/": ("live.html", CODE_DIR), "/live/index.html": ("live.html", CODE_DIR), "/live/live.js": ("live.js", CODE_DIR),
         "/live/live.css": ("live.css", CODE_DIR), "/live/hls.min.js": ("hls.min.js", VENDOR_DIR)}
TYPES = {".html": "text/html; charset=utf-8", ".css": "text/css; charset=utf-8", ".js": "application/javascript; charset=utf-8"}
# 入口の画面の CSP に、hls.js の再生(MediaSource の blob: URL)だけを足す
PAGE_CSP = ("default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; media-src 'self' blob:; "
            "object-src 'none'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'")
RELAY_RE = re.compile(r"^/live/r/([a-z][a-z0-9-]{0,15})/([A-Za-z0-9._/-]{1,200})\Z")
PASS_TYPES = ("application/json", "application/vnd.apple.mpegurl", "video/mp2t")   # 中継で返してよい種類
RELAY_TIMEOUT = 15.0
WATCH_SEC = 30.0
SPAWN_GAP = 30.0
VERSION_RE = re.compile(r'^VERSION\s*=\s*"([^"]+)"', re.M)


def recorder_data_dir(root):
    """録画の部品の作業データ(token.txt)。recorder/recorder.py の data_dir() と同じ規則"""
    return datadir.locate("recorder", legacy_dir=os.path.join(root, "recorder", "data"))


def is_local_url(url):
    try:
        return (urllib.parse.urlsplit(url).hostname or "") in ("127.0.0.1", "localhost")
    except ValueError:
        return False


def studio_out_dir(root):
    """スタジオの書き出し先(スタジオの settings.json の outDir。無ければスタジオの作業データの exports。読むだけ。launch.py の _extra_dirs と同じ)"""
    sdir = datadir.resolve("studio", root)
    try:
        with open(os.path.join(sdir, "settings.json"), "r", encoding="utf-8") as f:
            st = json.load(f)
        out = st.get("outDir") if isinstance(st, dict) else None
        if isinstance(out, str) and out and os.path.isabs(out):
            return out
    except (OSError, ValueError):
        pass
    return os.path.join(sdir, "exports")


class Live:
    def __init__(self, prefs, root, logs_dir, log=None, python=None, data_dir=None, watch_sec=WATCH_SEC, spawn=True,
                 store_dir=None, out_dir=None, runner=None):
        """prefs: home/prefs.py の Prefs。data_dir: 手元の録画の部品の作業データ(テスト用。既定 recorder_data_dir)。
        store_dir: マークと書き出しの記録(既定 入口の作業データの live)。out_dir(): 書き出し先(既定 スタジオの書き出し先)。
        runner(): 文字起こしへ渡す まとめて実行(既定 入口の server.autorun。画面の要求が来たときに覚える)"""
        self.prefs, self.root, self.logs_dir = prefs, root, logs_dir
        self.store_dir = store_dir or os.path.join(os.path.dirname(logs_dir), "live")
        self.out_dir = out_dir or (lambda: studio_out_dir(self.root))
        self.runner = runner or (lambda: getattr(self._server, "autorun", None) if self._server is not None else None)
        self._server = None
        self._exporter = None
        self._ex_lock = threading.Lock()
        self.log = log or (lambda m: None)
        self.python = python or sys.executable
        self.data_dir = data_dir or recorder_data_dir(root)
        self.watch_sec, self.spawn_ok = watch_sec, spawn
        self.wake = threading.Event()
        self._halt = threading.Event()
        self._thread = None
        self._last_spawn = 0.0
        self.proc = None

    # --- 設定 ---
    def cfg(self):
        try:
            return self.prefs.get(["live"])["live"]
        except Exception:
            return {"enabled": False, "folder": "", "recorders": []}

    def enabled(self):
        return self.cfg().get("enabled") is True

    def recorders(self, cfg=None):
        """録画元の一覧(合言葉つき。画面には出さない)。空 = 手元の1つ"""
        cfg = cfg or self.cfg()
        out = []
        for r in (cfg.get("recorders") or [dict(LOCAL)]):
            r = dict(r)
            if not r.get("token") and is_local_url(r.get("url") or ""):
                r["token"] = self.local_token()
            out.append(r)
        return out

    def find(self, rid):
        return next((r for r in self.recorders() if r.get("id") == rid), None)

    @property
    def exporter(self):
        """マークと書き出し(home/live_export.py)。オンにして初めて使うときに作る(オフの間は作業データに何も作らない)"""
        with self._ex_lock:
            if self._exporter is None:
                self._exporter = live_export.Exporter(self, self.store_dir, lambda: self.out_dir(), runner=lambda: self.runner(), log=self.log)
            return self._exporter

    def local_token(self):
        try:
            with open(os.path.join(self.data_dir, "token.txt"), "r", encoding="ascii") as f:
                return f.read().strip()[:200]
        except (OSError, UnicodeError):
            return ""

    def expected_version(self):
        try:
            with open(os.path.join(self.root, "recorder", "recorder.py"), "r", encoding="utf-8") as f:
                m = VERSION_RE.search(f.read())
            return m.group(1) if m else ""
        except (OSError, UnicodeError):
            return ""

    # --- 録画元への要求 ---
    def request(self, rc, method, path, body=None, timeout=RELAY_TIMEOUT):
        """-> (HTTPConnection, HTTPResponse)。呼んだ側が読んで conn.close() する。つながらなければ OSError"""
        u = urllib.parse.urlsplit(rc.get("url") or "")
        if u.scheme != "http" or not u.hostname or not u.port:
            raise OSError("録画元の URL が正しくありません")
        conn = http.client.HTTPConnection(u.hostname, u.port, timeout=timeout)
        headers = {"Host": u.netloc, "Authorization": "Bearer " + (rc.get("token") or ""), "Accept": "*/*"}
        data = None
        if body is not None:
            data = json.dumps(body, ensure_ascii=False).encode("utf-8")
            headers["Content-Type"] = "application/json"
        try:
            conn.request(method, path, body=data, headers=headers)
            return conn, conn.getresponse()
        except (OSError, http.client.HTTPException) as e:
            conn.close()
            raise OSError(str(e) or e.__class__.__name__)

    def call(self, rc, method, path, body=None, timeout=3.0):
        """JSON の API を呼ぶ -> (HTTP の番号, JSON)。つながらなければ (None, None)"""
        try:
            conn, r = self.request(rc, method, path, body, timeout)
        except OSError:
            return None, None
        try:
            raw = r.read(4 * 1024 * 1024)
            try:
                return r.status, json.loads(raw.decode("utf-8", "replace"))
            except ValueError:
                return r.status, None
        except (OSError, http.client.HTTPException):
            return None, None
        finally:
            conn.close()

    def ping(self, rc, timeout=1.5):
        code, d = self.call(rc, "GET", "/api/ping", timeout=timeout)
        return d if code == 200 and isinstance(d, dict) and d.get("app") == "ytt-recorder" else None

    # --- 画面と中継(launch.py の PortalHandler から) ---
    def handle_get(self, h, u):
        """GET /live…。オフなら False(入口の今までどおりの 404 になる)"""
        if not self.enabled():
            return False
        if u.path == "/live":
            h._send(301, b"", "text/plain; charset=utf-8", {"Location": "/live/"})
            return True
        if u.path in PAGES:
            name, base = PAGES[u.path]
            try:
                with open(os.path.join(base, name), "rb") as f:
                    body = f.read()
            except OSError:
                h._fail(404, "not_found", "その場所はありません")
                return True
            page = name.endswith(".html")
            if page:
                body = mount_mod.inject_token(body, h.server.token)
            h._send(200, body, TYPES[os.path.splitext(name)[1]],
                    {"Content-Security-Policy": PAGE_CSP, "X-Frame-Options": "DENY", "Referrer-Policy": "no-referrer"} if page else None)
            return True
        if u.path in ("/live/api/marks", "/live/api/exports"):
            self._server = h.server
            q = urllib.parse.parse_qs(u.query)
            try:
                if u.path == "/live/api/exports":
                    return h._json(200, {"jobs": self.exporter.snapshot()}) or True
                rc, rec = (q.get("recorder") or [""])[0], (q.get("recording") or [""])[0]
                d = self.exporter.marks.load(rc, rec)
                h._json(200, {"marks": d["marks"], "title": d.get("title") or "", "url": d.get("url") or "",
                              "exports": self.exporter.snapshot(rc, rec)})
            except live_export.LiveError as e:
                h._fail(e.code, "bad_request" if e.code == 400 else "not_found" if e.code == 404 else "error", str(e))
            return True
        if u.path == "/live/api/info":
            cfg = self.cfg()
            h._json(200, {"enabled": True, "folder": cfg.get("folder") or "", "defaultFolder": DEFAULT_FOLDER,
                          "recorders": [{"id": r["id"], "name": r["name"], "url": r["url"], "local": is_local_url(r["url"])} for r in self.recorders(cfg)]})
            return True
        m = RELAY_RE.match(u.path)
        if m and ".." not in m.group(2) and "//" not in m.group(2):
            self._relay(h, "GET", m.group(1), m.group(2), u.query)
            return True
        h._fail(404, "not_found", "その場所はありません")
        return True

    def handle_post(self, h, u, body):
        """POST /live…(入口の合言葉・Origin の検査と本文の読み取りは launch.py が済ませてある)。オフなら False"""
        if not self.enabled():
            return False
        if u.path.startswith("/live/api/"):
            self._server = h.server
            self._api_post(h, u.path, body)
            return True
        m = RELAY_RE.match(u.path)
        if m and ".." not in m.group(2) and "//" not in m.group(2):
            self._relay(h, "POST", m.group(1), m.group(2), "", body)
            return True
        h._fail(404, "not_found", "その操作はありません")
        return True

    def _api_post(self, h, path, body):
        """マークと書き出し(P2)"""
        ex = self.exporter
        try:
            if path == "/live/api/marks":
                rc, rec = body.get("recorder"), body.get("recording")
                if self.find(rc) is None:
                    raise live_export.LiveError("その録画元はありません", 404)
                m, marks = ex.marks.apply(rc, rec, body)
                return h._json(200, {"mark": m, "marks": marks})
            if path == "/live/api/export":
                return h._json(200, {"job": ex.add(body.get("recorder"), body.get("recording"), body.get("markId"), body.get("transcribe") is not False)})
            if path == "/live/api/export/cancel":
                return h._json(200, {"job": ex.cancel(body.get("id"))})
        except live_export.LiveError as e:
            return h._fail(e.code, "bad_request" if e.code == 400 else "not_found" if e.code == 404 else "conflict" if e.code == 409 else "error", str(e))
        h._fail(404, "not_found", "その操作はありません")

    def _relay(self, h, method, rid, rest, query="", body=None):
        rc = self.find(rid)
        if rc is None:
            return h._fail(404, "unknown_recorder", "その録画元はありません")
        path = "/live/" + rest + ("?" + query[:200] if query else "")
        try:
            conn, r = self.request(rc, method, path, body)
        except OSError:
            return h._fail(502, "recorder_down", "録画元「%s」につながりません。録画の部品が起動するまで少し待ってください(%s)" % (rc["name"], rc["url"]))
        try:
            ctype = (r.getheader("Content-Type") or "").split(";")[0].strip().lower()
            if ctype not in PASS_TYPES:
                return h._fail(502, "recorder_bad", "録画元から思わぬ応答がありました")
            length = r.getheader("Content-Length")
            h.send_response(r.status)
            h.send_header("Content-Type", r.getheader("Content-Type"))
            if length and length.isdigit():
                h.send_header("Content-Length", length)
            else:
                h.close_connection = True
            h.send_header("Cache-Control", r.getheader("Cache-Control") or "no-store")
            h.send_header("X-Content-Type-Options", "nosniff")
            h.end_headers()
            if h.command == "HEAD":
                return
            while True:
                chunk = r.read(256 * 1024)
                if not chunk:
                    break
                h.wfile.write(chunk)
        except (OSError, http.client.HTTPException):
            h.close_connection = True   # 途中で切れた(再生を止めた・録画元が落ちた)
        finally:
            conn.close()

    # --- 設定を変えたとき ---
    def on_patch(self, old, new):
        """設定の節 live を変えた。オンにした・置き場所を変えた → 見回りをすぐ。オンにしたときは画面を待たせない(起動は裏で)"""
        self.wake.set()

    def note(self, msg):
        """同じ知らせを見回りのたびに記録しない"""
        if msg != getattr(self, "_last_note", None):
            self._last_note = msg
            self.log(msg)

    # --- 見回り(手元の録画の部品を起こす) ---
    def start(self):
        if self._thread is None:
            self._thread = threading.Thread(target=self._watch, daemon=True, name="live-watch")
            self._thread.start()

    def close(self):
        """入口の終了: 見回りだけ止める(録画の部品は止めない = 入口を起動し直しても録画は続く。計画の 0-3)"""
        self._halt.set()
        self.wake.set()
        if self._exporter is not None:   # 書き出しの途中なら ffmpeg を止める(ジョブは「録画待ち」に戻り、次の起動でやり直す)
            self._exporter.close()

    def _watch(self):
        while not self._halt.is_set():
            try:
                self.tick()
            except Exception as e:   # 見回りは止めない
                self.log("録画の部品の見回りでエラー: %r" % (e,))
            self.wake.wait(self.watch_sec)
            self.wake.clear()

    def tick(self):
        """オンなら: 手元の録画元が動いていなければ起動する・古い版なら(録画中でなければ)起動し直す・置き場所の設定が違えば伝える。
        -> "off"|"running"|"spawned"|"waiting"|"failed\""""
        cfg = self.cfg()
        if cfg.get("enabled") is not True:
            return "off"
        if os.path.isfile(os.path.join(self.store_dir, "exports.json")) and self.exporter.pending():   # 入口を起動し直した: 途中の書き出しを続ける
            self.exporter.start()
        local = next((r for r in self.recorders(cfg) if is_local_url(r.get("url") or "")), None)
        if local is None:
            return "off"
        info = self.ping(local)
        if info:
            exp = self.expected_version()
            if exp and info.get("version") != exp:   # コードを直した(版が上がった): 録画中でなければ終わってもらって、新しい版で起こし直す
                code, _d = self.call(local, "POST", "/live/quit", {})
                if code == 200:
                    self.note("録画の部品が古い版(v%s)なので、v%s で起動し直します" % (info.get("version"), exp))
                    end = time.time() + 15
                    while time.time() < end and self.ping(local, 0.5):
                        time.sleep(0.3)
                    self._last_spawn = 0.0
                    return "spawned" if self.spawn_ok and self.spawn(local, cfg.get("folder") or "") else "waiting"
                self.note("録画の部品が古い版(v%s)ですが、録画中なので録画が終わってから起動し直します" % info.get("version"))
            folder = cfg.get("folder") or ""
            if folder:
                code, d = self.call(local, "GET", "/live/config")
                if code == 200 and isinstance(d, dict) and os.path.normcase(d.get("folder") or "") != os.path.normcase(os.path.normpath(folder)):
                    code, d = self.call(local, "POST", "/live/config", {"folder": folder})
                    self.note("録画の置き場所を %s にしました" % folder if code == 200 else
                              "録画の置き場所を変えられませんでした: %s" % ((d or {}).get("message") or code))
            return "running"
        if not self.spawn_ok:
            return "waiting"
        if time.time() - self._last_spawn < SPAWN_GAP:   # 起動したばかり(待ち受けの準備中)
            return "waiting"
        return "spawned" if self.spawn(local, cfg.get("folder") or "") else "failed"

    def spawn(self, rc, folder=""):
        """手元の録画の部品を、入口と切り離して起動する(入口と同じ Python = start.bat と同じ選び方で選ばれたもの)"""
        self._last_spawn = time.time()
        script = os.path.join(self.root, "recorder", "recorder.py")
        if not os.path.isfile(script):
            self.log("録画の部品が見つかりません: %s" % script)
            return False
        port = urllib.parse.urlsplit(rc["url"]).port or RECORDER_PORT
        cmd = [self.python, "-u", script, "--port", str(port), "--quiet", "--data-dir", self.data_dir]
        if folder:
            cmd += ["--folder", folder]
        env = dict(os.environ)
        env.setdefault("PYTHONIOENCODING", "utf-8:backslashreplace")
        env["PYTHONUNBUFFERED"] = "1"
        flags = 0
        if os.name == "nt":   # 別のプロセスグループ(入口への Ctrl+Break が届かない)・隠れた黒い画面(入口の黒い画面を閉じても止まらない)
            flags = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW | getattr(subprocess, "ABOVE_NORMAL_PRIORITY_CLASS", 0)
        os.makedirs(self.logs_dir, exist_ok=True)
        try:
            with open(os.path.join(self.logs_dir, "recorder.log"), "ab") as logf:
                logf.write(("\n==== %s 入口から起動 ====\n" % time.strftime("%Y-%m-%d %H:%M:%S")).encode("utf-8"))
                logf.flush()
                kw = dict(cwd=os.path.dirname(script), env=env, stdin=subprocess.DEVNULL, stdout=logf, stderr=subprocess.STDOUT)
                try:   # 入口がジョブ(閉じると子も消える)の中で動いていても、録画の部品は外へ出す。出られないジョブならそのまま
                    self.proc = subprocess.Popen(cmd, creationflags=flags | getattr(subprocess, "CREATE_BREAKAWAY_FROM_JOB", 0), **kw)
                except OSError:
                    self.proc = subprocess.Popen(cmd, creationflags=flags, **kw)
        except OSError as e:
            self.log("録画の部品を起動できませんでした: %s" % (e.strerror or e.__class__.__name__))
            return False
        self.log("録画の部品を起動しました(%s。置き場所 %s)" % (rc["url"], folder or "前回の設定か既定 " + DEFAULT_FOLDER))
        return True

    # --- 「調子」 ---
    def health(self):
        """オフなら None(「調子」に出さない)。オンなら録画元ごとの状態と空き容量"""
        cfg = self.cfg()
        if cfg.get("enabled") is not True:
            return None
        expected = self.expected_version()
        out = []
        for rc in self.recorders(cfg):
            row = {"id": rc["id"], "name": rc["name"], "url": rc["url"], "ok": False, "version": "", "expected": expected if is_local_url(rc["url"]) else "",
                   "folder": None, "folderOk": None, "folderMessage": "", "freeBytes": None, "totalBytes": None, "streamlink": None,
                   "active": 0, "recordings": [], "message": ""}
            code, d = self.call(rc, "GET", "/live/list", timeout=2.0)
            if code == 200 and isinstance(d, dict):
                row.update(ok=True, version=str(d.get("version") or ""), folder=d.get("folder"), folderOk=d.get("folderOk"),
                           folderMessage=d.get("folderMessage") or "", freeBytes=d.get("freeBytes"), totalBytes=d.get("totalBytes"),
                           streamlink=d.get("streamlink"), active=d.get("active") or 0,
                           recordings=[{k: x.get(k) for k in ("id", "title", "state", "message", "segments", "lastPdt")}
                                       for x in (d.get("recordings") or []) if x.get("active")][:5])
            elif code is None:
                row["message"] = "つながりません(録画の部品が起動していません)"
            else:
                row["message"] = ((d or {}).get("message") if isinstance(d, dict) else "") or "応答が正しくありません(HTTP %s)" % code
            out.append(row)
        return {"recorders": out}

