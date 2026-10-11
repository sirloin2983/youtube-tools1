# -*- coding: utf-8 -*-
"""ライブのテストが共有する部品(偽の設定・偽のスタジオ・偽の親の組み立て・HLS の偽物の入口)。

テストの名前ではない(unittest は読まない)。flow の tests と、入口 home の残りのテストの両方が `import _livefix as LF` で使う
(home のテストは sys.path に src/flow/tests を足す)。入口 home の Live は使わず、ライブ係 flow/livesession.LiveSession を直に組む。
"""
import copy
import json
import os
import socket
import subprocess
import sys
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

TESTS = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.dirname(os.path.dirname(TESTS))
if SRC not in sys.path:
    sys.path.insert(0, SRC)

from flow import live_adopt  # noqa: E402
from flow import livesession as LS  # noqa: E402
from ytt import normalize, tools  # noqa: E402

TOKEN = "t" * 40   # FakeRecorder の合言葉
FF = tools.find_tool("ffmpeg", "YTT_FFMPEG")

# ホームの設定の節 live の既定(src/home/prefs.py の DEFAULTS["live"] と同じ値。flow のテストは入口を読まないので写す)
LIVE_DEFAULTS = {"enabled": False, "folder": "", "recorders": [], "quality": "1080p", "autoArchive": True, "autoDelete": True,
                 "auto": {"after": "check", "cut": "", "engine": "", "model": "", "pad": 2.0}, "autoAfterStream": False, "afterStreamPerHour": 6,
                 "detect": {"enabled": True, "sens": "normal", "perHour": 6}, "autoAdopt": {"enabled": True, "waitMin": 5},
                 "liveTx": {"enabled": True, "model": "large-v3"}, "autoDeliver": True}


def patch_cfg(cfg, patch):
    """Prefs.patch("live", patch) と同じ合わせ方(入れ子の辞書は鍵ごとに重ねる)。cfg を直して返す"""
    for k, v in patch.items():
        if isinstance(v, dict) and isinstance(cfg.get(k), dict):
            cfg[k] = dict(cfg[k], **v)
        else:
            cfg[k] = v
    return cfg


def live_cfg(**patch):
    """既定のライブの設定(オン)に patch を重ねた新しい辞書"""
    return patch_cfg(copy.deepcopy(dict(LIVE_DEFAULTS, enabled=True)), patch)


def recorder_cfg(url, token, rid="fake", **patch):
    return live_cfg(recorders=[{"id": rid, "name": "偽物", "url": url, "token": token}], **patch)


class Requests(LS.MemoryRequests):
    """友人の依頼の結びつき(human/friend/live_requests.Store の代わり。メモリだけ)。テストが結びつきを消せる"""

    def put(self, rc, rec, ctx):
        """依頼の設定は human/friend/live_requests.SETTINGS_DEFAULT で欠けを埋める(Store.put と同じ)"""
        ctx = dict(ctx, settings=dict({"sens": "normal", "perHour": 6, "length": 45, "waitMin": 5, "pad": 2.0, "afterStream": True}, **(ctx.get("settings") or {})))
        return super().put(rc, rec, ctx)

    def remove(self, rc, rec):
        return self.items.pop("%s/%s" % (rc, rec), None) is not None


def new_session(tmp, cfg, log=None, root=None, **kw):
    """テスト用のライブ係(spawn なし・記録と書き出し先は tmp の中)。cfg は辞書(後から patch_cfg で直すと次の読みから効く)。
    採用のマークの置き場はスタジオ(StudioMarks)。s.studio_call を差し替えて使う"""
    holder = {}
    opts = dict(spawn=False, requests=Requests(), store_dir=os.path.join(tmp, "live"), out_dir=lambda: os.path.join(tmp, "out"),
                marks=live_adopt.StudioMarks(lambda m, p, b=None: holder["s"].studio_call(m, p, b)))
    opts.update(kw)
    s = LS.LiveSession(root or tmp, os.path.join(tmp, "logs"), cfg=lambda: cfg, log=log, **opts)
    holder["s"] = s
    return s


def hls_fixture():
    """pipeline/ingest/tests/hls_fixture(配信中のふりの HLS を出す偽物)"""
    d = os.path.join(SRC, "pipeline", "ingest", "tests")
    if d not in sys.path:
        sys.path.insert(0, d)
    import hls_fixture as F
    return F


def ff(*args):
    subprocess.run([FF, "-hide_banner", "-nostdin", "-y", "-v", "error"] + list(args), check=True,
                   stdin=subprocess.DEVNULL, capture_output=True)


def wait_for(fn, timeout=60.0, step=0.1):
    end = time.time() + timeout
    while time.time() < end:
        v = fn()
        if v:
            return v
        time.sleep(step)
    return fn()


class ArchiveStudio:
    """スタジオの POST /api/live/section・GET /api/export・POST /api/export/cancel の代わり(アーカイブから ffmpeg で 30fps に切る)"""

    def __init__(self, archive, shifts=(), block=False, busy=0):
        self.archive, self.shifts, self.block, self.busy = archive, list(shifts), block, busy
        self.calls, self.jobs, self.cancelled = [], {}, []

    def __call__(self, method, path, body):
        if method == "POST" and path == "/api/live/section":
            if self.busy > 0:   # ほかの書き出しが動いている(スタジオは同時に 1 本だけ)
                self.busy -= 1
                return 409, {"error": "busy", "message": "ほかの書き出しが動いています"}
            p = body["path"]
            assert os.path.isabs(p) and p.endswith(".mp4") and not p.endswith(".partial.mp4") and not os.path.exists(p), p
            assert os.path.isdir(os.path.dirname(p)), p
            self.calls.append(dict(body))
            jid = uuid.uuid4().hex[:12]
            job = {"id": jid, "state": "running", "items": [{"status": "running", "progress": 0, "error": None, "path": None}], "cancel": False}
            self.jobs[jid] = job
            start = body["start"] + (self.shifts[len(self.calls) - 1] if len(self.calls) <= len(self.shifts) else 0.0)   # shifts: n 回目の書き出しを頼まれた区間からずらして作る
            threading.Thread(target=self._run, args=(job, start, body["end"] - body["start"], p), daemon=True).start()
            return 200, {"id": jid, "state": "running", "items": job["items"]}
        if method == "GET" and path.startswith("/api/export?id="):
            j = self.jobs.get(path.split("=", 1)[1])
            return (404, {"error": "not_found"}) if j is None else (200, {"id": j["id"], "state": j["state"], "items": j["items"]})
        if method == "POST" and path == "/api/export/cancel":
            self.cancelled.append(body["id"])
            j = self.jobs.get(body["id"])
            if j:
                j["cancel"] = True
            return 200, {"ok": True}
        return 404, {"error": "not_found"}

    def _run(self, job, start, dur, path):
        it = job["items"][0]
        if self.block:
            while not job["cancel"]:
                time.sleep(0.05)
            it["status"], job["state"] = "cancelled", "cancelled"
            return
        try:
            ff("-ss", "%.3f" % start, "-i", self.archive, "-t", "%.3f" % dur, "-map", "0:v:0", "-map", "0:a:0",
               *normalize.encode_args("ultrafast"), path)
            it.update(status="done", progress=1.0, path=path)
            job["state"] = "done"
        except subprocess.CalledProcessError as e:
            it.update(status="error", error=e.stderr.decode("utf-8", "replace")[-200:])
            job["state"] = "error"


class FakeStudio:
    """取り込んだスタジオの API の代わり(studio_call に差し替える。M1): 配信の登録・読む・マークの保存(baseRev)・ライブの採用(RS8 B3-5)・書き出し済み"""

    def __init__(self):
        self.videos = {}
        self.calls = []
        self.conflicts = 0     # この回数だけ PUT を 409(画面の保存とぶつかった)にする
        self.seq = 0

    def __call__(self, method, path, body=None):
        self.calls.append((method, path.split("?")[0], json.loads(json.dumps(body)) if body is not None else None))
        if method == "POST" and path == "/api/videos/open":
            v = self.videos.setdefault(body["recording"], {"id": body["recording"], "kind": "live", "rev": 1, "marks": [], "title": body.get("title") or ""})
            return 200, {"video": json.loads(json.dumps(v))}
        if method == "GET" and path.startswith("/api/video?id="):
            v = self.videos.get(path.split("=", 1)[1])
            return (200, {"video": json.loads(json.dumps(v))}) if v else (404, {"message": "無い"})
        if method == "PUT" and path == "/api/video":
            v = self.videos[body["id"]]
            if self.conflicts:
                self.conflicts -= 1
                v["rev"] += 1
                return 409, {"message": "ぶつかった"}
            if body.get("baseRev") != v["rev"]:
                return 409, {"message": "古い"}
            marks = []
            for m in body["marks"]:
                m = dict(m)
                if not m.get("id"):
                    self.seq += 1
                    m["id"] = "m%d" % self.seq
                    m.setdefault("src", "manual")
                m["start"], m["end"] = round(m["start"], 1), round(m["end"], 1)   # スタジオは小数 1 桁に丸める
                marks.append(m)
            v["marks"], v["rev"] = marks, v["rev"] + 1
            return 200, {"video": json.loads(json.dumps(v))}
        if method == "POST" and path == "/api/live/adopt":   # 入口のライブの採用(RS8 B3-5。スタジオの Store.adopt_live と同じ決まり)
            v = self.videos.setdefault(body["recording"], {"id": body["recording"], "kind": "live", "rev": 1, "marks": [], "title": body.get("title") or ""})
            a, b = body["start"], body["end"]
            hit = next((m for m in v["marks"] if abs(m["start"] - a) <= 0.5 and abs(m["end"] - b) <= 0.5), None)
            if hit is None or hit.get("status") not in ("adopted", "exported"):
                if hit is None:
                    self.seq += 1
                    hit = {"id": "m%d" % self.seq, "src": "manual", "start": round(a, 1), "end": round(b, 1), "label": body.get("label") or ""}
                    v["marks"].append(hit)
                hit["status"] = "adopted"
                v["rev"] += 1
            order = sorted(v["marks"], key=lambda m: (m["start"], m["end"]))
            return 200, {"video": v["id"], "mark": json.loads(json.dumps(hit)), "n": next(i + 1 for i, m in enumerate(order) if m["id"] == hit["id"])}
        if method == "POST" and path == "/api/live/exported":
            v = self.videos[body["id"]]
            m = next((x for x in v["marks"] if x["id"] == body["markId"]), None)
            if m is None:
                return 200, {"ok": False}
            m.update(status="exported", path=body["path"])
            return 200, {"ok": True}
        return 404, {"message": "なし"}


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


class FakeRecorder:
    """録画元の代わり(合言葉と Host を確かめ、受けた要求を覚える)"""

    def __init__(self):
        self.seen = []
        self.routes = {}   # (method, path) -> fn(body) -> (HTTP の番号, JSON)。path は ? の前まで。無ければ下の決まった応答
        owner = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _out(self, code, body, ctype):
                self.send_response(code)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-cache")
                self.end_headers()
                self.wfile.write(body)

            def _handle(self, body=None):
                owner.seen.append({"method": self.command, "path": self.path, "auth": self.headers.get("Authorization"),
                                   "host": self.headers.get("Host"), "origin": self.headers.get("Origin"), "body": body})
                if self.headers.get("Authorization") != "Bearer " + TOKEN:
                    return self._out(403, b'{"error":"token","message":"x"}', "application/json")
                fn = owner.routes.get((self.command, self.path.split("?")[0]))
                if fn is not None:
                    code, obj = fn(body)
                    return self._out(code, json.dumps(obj).encode(), "application/json")
                if self.path == "/api/ping":
                    return self._out(200, b'{"app":"ytt-recorder","version":"0.0.1"}', "application/json")
                if self.path == "/live/list":
                    return self._out(200, json.dumps({"folder": "X:\\rec", "folderOk": True, "folderMessage": "", "freeBytes": 5 * 1024 ** 3,
                                                      "totalBytes": 9 * 1024 ** 3, "streamlink": True, "version": "0.0.1", "active": 1,
                                                      "recordings": [{"id": "20261004-000000-a", "title": "t", "state": "recording", "active": True,
                                                                      "segments": 3, "lastPdt": None, "message": ""}]}).encode(), "application/json")
                if self.path == "/live/20261004-000000-a/index.m3u8":
                    return self._out(200, b"#EXTM3U\n", "application/vnd.apple.mpegurl")
                if self.path == "/live/20261004-000000-a/session_001/seg_000000.ts":
                    return self._out(200, b"\x47" * 188 * 10, "video/mp2t")
                if self.path == "/live/html":
                    return self._out(200, b"<script>alert(1)</script>", "text/html")
                if self.path.startswith("/live/20261004-000000-a/status"):
                    return self._out(200, json.dumps({"path": self.path}).encode(), "application/json")
                return self._out(404, b'{"error":"not_found","message":"x"}', "application/json")

            def do_GET(self):
                self._handle()

            def do_POST(self):
                n = int(self.headers.get("Content-Length") or 0)
                self._handle(json.loads(self.rfile.read(n).decode()) if n else None)

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.httpd.daemon_threads = True
        self.port = self.httpd.server_address[1]
        self.url = "http://127.0.0.1:%d" % self.port
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def close(self):
        self.httpd.shutdown()
        self.httpd.server_close()
