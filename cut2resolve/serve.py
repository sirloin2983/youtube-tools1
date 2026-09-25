#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""cut2resolve の画面のサーバー(Python 標準ライブラリのみ。外部ツール: ffmpeg / ffprobe)。

    python serve.py [開始ポート] [--no-open]      (既定のポート 8810。使用中なら次の番号)

127.0.0.1 だけで待ち受け、Host / Origin / Sec-Fetch-Site を検査する。カットの計算とパックの作成は pack.py(CLI と同じ関数)。

API(画面の app.js の api() からだけ呼ぶ。統合時はベースのパスを app.js の1か所で変える):
  GET  /api/ping                 {"app": "cut2resolve", "version"}
  GET  /api/siblings             {"tools": {"studio": 8800, "transcribe": 8775, "cut2resolve": 8810}}(docs/pipeline.md の 4)
  GET  /api/state                ffmpeg の有無・既定値・実行中のジョブ・アップロードの上限など
  POST /api/inspect              {video?, srt?, transcript?, plan?} → 各入力の中身(動画の情報・件数)と配信用の mediaUrl
  POST /api/plan                 {spec} → ジョブ(試算。ファイルは作らない)
  POST /api/build                {spec, output: {dir?, render, copyVideo, fcpxml, textplus, textplusFps?, textplusSize?, force, crf?}} → ジョブ。既存の出力があれば 409 exists
  GET  /api/job?id=              ジョブの状態 {state: running|done|error|cancelled, progress, message, result|error}
  POST /api/job/cancel           {id}
  POST /api/open-folder          {path}(このサーバーがパックを書いたフォルダだけ)
  POST /api/upload?kind=&name=   字幕・文字起こし・cut-plan の中身(application/octet-stream)→ work/uploads/ に保存して {path}
  GET  /media/<token>            入力に指定した動画・作った粗編集の動画だけ(Range 対応)

入口(start-all.bat)の統合サーバーに取り込まれたときは http://localhost:8700/cut2resolve/ で動く(app/mount.py。段階3-2)。
そのときは prepare() / finish() が起動・終了の準備を行い、状態は MOUNT に持つ。書き込み系の API には合言葉(X-YTT-Token)が要る(mount.py が検査)
"""
import http.client
import json
import os
import re
import secrets
import shutil
import socket
import subprocess
import sys
import threading
import time
import traceback
import urllib.parse
import urllib.request
import webbrowser
from collections import OrderedDict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

CODE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, CODE_DIR)
import auto_cut as AC  # noqa: E402
import cut2resolve_core as C  # noqa: E402
import pack  # noqa: E402
import resolve_textplus as TP  # noqa: E402
import srt2resolve as S  # noqa: E402

APP_ID = "cut2resolve"
TOOL_ID = "cut2resolve"
SERVER_VERSION = C.VERSION        # 版の正は cut2resolve_core.VERSION の1か所
DEFAULT_PORT = 8810
WORK_DIR = os.path.join(CODE_DIR, "work")          # .gitignore の **/work/ で管理外
UPLOAD_DIR = os.path.join(WORK_DIR, "uploads")
LOG_PATH = os.path.join(WORK_DIR, "serve.log")
LOG_MAX = 1024 * 1024
MAX_BODY = 2 * 1024 * 1024                          # JSON の要求の上限(時刻リストの貼り付けを含む)
UPLOAD_LIMITS = {"srt": (S.MAX_SUB_BYTES, (".srt", ".vtt")), "transcript": (C.MAX_JSON_BYTES, (".json",)),
                 "plan": (C.MAX_JSON_BYTES, (".json",))}
UPLOAD_KEEP = 40                                    # 残しておくアップロードの数(古いものから消す。起動時には全部消す)
SOCKET_TIMEOUT = 120
MEDIA_EXTS = {".mp4", ".m4v", ".mov", ".mkv", ".webm", ".avi", ".mxf", ".ts", ".mts", ".m2ts", ".flv", ".wmv"}
# ブラウザで再生するときの Content-Type。mov は中身が mp4 と同じ仲間、mkv は webm と同じ仲間なので、再生できる見込みの高い型にする
MEDIA_TYPES = {".mp4": "video/mp4", ".m4v": "video/mp4", ".mov": "video/mp4", ".mkv": "video/webm", ".webm": "video/webm",
               ".avi": "video/x-msvideo", ".ts": "video/mp2t", ".mts": "video/mp2t", ".m2ts": "video/mp2t"}
STATIC = {"/": "index.html", "/index.html": "index.html", "/app.js": "app.js", "/app.css": "app.css",
          "/ui-kit.css": "ui-kit.css", "/ui-kit.js": "ui-kit.js"}
STATIC_TYPES = {".html": "text/html; charset=utf-8", ".css": "text/css; charset=utf-8",
                ".js": "application/javascript; charset=utf-8"}
CSP = ("default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; media-src 'self'; "
       "connect-src 'self'; object-src 'none'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'")
QUIET_PATHS = ("/api/job", "/media/", "/api/siblings", "/api/ping")
TOOL_APPS = {"studio": "clip-studio", "transcribe": "transcribe-tool", "cut2resolve": "cut2resolve"}   # docs/pipeline.md の 4
PING_TIMEOUT = 0.3
RUNTIME_MAX_BYTES = 4096
BASE_PATH = "/"          # 画面の場所。入口の統合サーバーに取り込まれたときは "/cut2resolve/"(app/mount.py が prepare() で入れる)
ALLOWED_HOSTS = set()    # 取り込まれたときに許す Host(app/mount.py が入口のポートで入れる。単独で動くときはサーバーごとに持つ)
MOUNT = None             # 取り込まれたときの状態(port・allowed_hosts・app)。単独で動くときは C2RServer が持つ


class ApiError(Exception):
    def __init__(self, code, message, status=400, extra=None):
        super().__init__(message)
        self.code, self.message, self.status, self.extra = code, message, status, extra or {}


# ---------------------------------------------------------------- ログ

_log_lock = threading.Lock()


def log(msg):
    """work/serve.log に1行追記(想定外のエラーの調べ用。1MB を超えたら serve.old.log に回す。失敗しても何もしない)"""
    line = "%s %s\n" % (time.strftime("%Y-%m-%d %H:%M:%S"), msg)
    try:
        with _log_lock:
            os.makedirs(WORK_DIR, exist_ok=True)
            if os.path.exists(LOG_PATH) and os.path.getsize(LOG_PATH) > LOG_MAX:
                os.replace(LOG_PATH, os.path.join(WORK_DIR, "serve.old.log"))
            with open(LOG_PATH, "a", encoding="utf-8") as f:
                f.write(line)
    except Exception:
        pass


# ---------------------------------------------------------------- 実行中のポートの共有(.runtime)と /api/siblings
# clip-studio/handoff.py・transcribe-tool/pipeline_io.py と同じ約束(フォルダ単体で動かすため写して使う)

def runtime_dir():
    d = os.environ.get("YTT_RUNTIME_DIR")
    return os.path.abspath(d) if d else os.path.join(os.path.dirname(CODE_DIR), ".runtime")


def valid_port(p):
    return type(p) is int and 1024 <= p <= 65535


def _read_small_json(path):
    with open(path, "rb") as f:
        raw = f.read(RUNTIME_MAX_BYTES + 1)
    if len(raw) > RUNTIME_MAX_BYTES:
        return None
    try:
        return json.loads(raw.decode("utf-8-sig"))
    except (UnicodeDecodeError, ValueError):
        return None


def write_runtime(port, base_path="/"):
    """起動時に <runtime>/cut2resolve.json を書く。書けなくても起動は続ける。pid は「自分が書いたか」を消すときに確かめるためだけ
    (生きているかの確認には使わない。Windows の os.kill(pid, 0) はプロセスを終了させてしまうため)"""
    try:
        d = runtime_dir()
        os.makedirs(d, exist_ok=True)
        path = os.path.join(d, TOOL_ID + ".json")
        info = {"tool": TOOL_ID, "port": int(port), "version": SERVER_VERSION,
                "startedAt": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "pid": os.getpid()}
        if base_path != "/" and RUNTIME_PATH_RE.match(base_path):   # 入口に取り込まれたときだけ書く(以前の形の記録と同じに保つ)
            info["path"] = base_path
        S.write_bytes_atomic(path, (json.dumps(info, ensure_ascii=False) + "\n").encode("utf-8"))
        return path
    except OSError as e:
        log("warn: .runtime を書けません: %s" % e)
        return None


def remove_runtime(port):
    try:
        path = os.path.join(runtime_dir(), TOOL_ID + ".json")
        d = _read_small_json(path)
        if isinstance(d, dict) and d.get("port") == port and d.get("pid") == os.getpid():
            os.remove(path)
            return True
    except OSError:
        pass
    return False


RUNTIME_PATH_RE = re.compile(r"^/(?:[a-z0-9][a-z0-9-]{0,31}/)?\Z")   # 画面の場所(入口の統合サーバーに取り込まれたツールは "/studio/" など。ytt_core.runtime と同じ規則)


def read_runtime_entry(tool):
    """(ポート, 画面の場所) か None。場所が無い・形が違うときは "/"(以前の記録・他人が書いた値で、別の場所へ向けさせない)。"""
    try:
        d = _read_small_json(os.path.join(runtime_dir(), tool + ".json"))
    except OSError:
        return None
    if not isinstance(d, dict) or d.get("tool") != tool or not valid_port(d.get("port")):
        return None
    path = d.get("path")
    return d["port"], (path if isinstance(path, str) and RUNTIME_PATH_RE.match(path) else "/")


def read_runtime_port(tool):
    e = read_runtime_entry(tool)
    return e[0] if e else None


def ping_app(port, timeout=PING_TIMEOUT, path="/"):
    """127.0.0.1:<port><path>api/ping の app。http.client を使う(環境変数・Windows のプロキシ設定で 127.0.0.1 宛てがプロキシに回らないように)"""
    if not valid_port(port) or not RUNTIME_PATH_RE.match(path or ""):
        return None
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=timeout)
    try:
        conn.request("GET", path + "api/ping", headers={"Host": "127.0.0.1:%d" % port, "Accept": "application/json"})
        r = conn.getresponse()
        if r.status != 200:
            return None
        d = json.loads(r.read(RUNTIME_MAX_BYTES).decode("utf-8", "replace"))
        app = d.get("app") if isinstance(d, dict) else None
        return app if isinstance(app, str) else None
    except (OSError, ValueError, http.client.HTTPException):
        return None
    finally:
        conn.close()


def siblings(self_port, timeout=PING_TIMEOUT, self_path="/"):
    """.runtime の記録の場所に並行して /api/ping を問い合わせ、app が一致したものだけ(自分自身は問い合わせずに含める)。
    入口の統合サーバーに取り込まれたツール(場所が "/" 以外)があれば {"paths": {"studio": "/studio/"}} も付ける(ytt_core.runtime.siblings と同じ形)"""
    found, paths = ({TOOL_ID: self_port} if valid_port(self_port) else {}), {}
    if TOOL_ID in found and self_path != "/" and RUNTIME_PATH_RE.match(self_path or ""):
        paths[TOOL_ID] = self_path
    todo = []
    for tid, app in TOOL_APPS.items():
        e = read_runtime_entry(tid) if tid != TOOL_ID else None
        if e and not (e[0] == self_port and e[1] == "/"):   # 同じポートでも別の場所なら、統合サーバーの中の別のツール
            todo.append((tid, app, e[0], e[1]))
    lock = threading.Lock()

    def one(tid, app, port, path):
        if ping_app(port, timeout, path) == app:
            with lock:
                found[tid] = port
                if path != "/":
                    paths[tid] = path
    ths = [threading.Thread(target=one, args=t, daemon=True) for t in todo]
    for th in ths:
        th.start()
    t0 = time.monotonic()
    for th in ths:
        th.join(max(0.0, timeout + 0.2 - (time.monotonic() - t0)))
    with lock:
        out = {"tools": {k: found[k] for k in TOOL_APPS if k in found}}
        if paths:
            out["paths"] = {k: paths[k] for k in TOOL_APPS if k in paths}
        return out


# ---------------------------------------------------------------- 入力のパス

LABELS = {"video": "動画", "srt": "字幕(SRT)", "transcript": "文字起こし", "plan": "残す区間(cut-plan)", "out": "出力フォルダ"}
FIELD_EXTS = {"video": MEDIA_EXTS, "srt": S.SUB_EXTS, "transcript": C.JSON_EXTS, "plan": C.JSON_EXTS}


def clean_path(value, field):
    """画面から来たパスを整える。空なら None。Windows の「パスのコピー」の "…"・file:/// の URL も受け付ける。
    相対パスは断る(サーバーの作業フォルダ基準になって、思わぬ場所を指すため)"""
    label = LABELS.get(field, field)
    if value is None or value == "":
        return None
    if not isinstance(value, str):
        raise ApiError("bad_path", "%sのパスは文字列で指定してください" % label)
    s = value.strip()
    if len(s) >= 2 and s[0] == s[-1] and s[0] in "\"'":
        s = s[1:-1].strip()
    if s.lower().startswith("file:"):
        u = urllib.parse.urlsplit(s)
        s = urllib.request.url2pathname(u.path)
        if u.netloc and u.netloc.lower() != "localhost":
            s = "//" + u.netloc + s
    if not s:
        return None
    if len(s) > 4000 or "\x00" in s or "\n" in s or "\r" in s:
        raise ApiError("bad_path", "%sのパスが正しくありません" % label)
    if not os.path.isabs(s):
        raise ApiError("bad_path", "%sは、C:\\ から始まる完全なパスで指定してください(エクスプローラーでファイルを右クリック →「パスのコピー」)" % label)
    return os.path.normpath(s)


def input_path(value, field):
    """入力ファイルのパス(存在・拡張子を確かめる)。空なら None"""
    p = clean_path(value, field)
    if p is None:
        return None
    label = LABELS[field]
    ext = os.path.splitext(p)[1].lower()
    if ext not in FIELD_EXTS[field]:
        raise ApiError("bad_ext", "%sの拡張子(%s)は使えません。使えるもの: %s" % (label, ext or "なし", " ".join(sorted(FIELD_EXTS[field]))))
    try:
        ok = os.path.isfile(p)
    except (OSError, ValueError):
        ok = False
    if not ok:
        raise ApiError("not_found", "%sが見つかりません: %s" % (label, p))
    return Path(p)


# ---------------------------------------------------------------- アプリの状態(ジョブ・配信の許可・キャッシュ)

class Job:
    def __init__(self, kind):
        self.id = secrets.token_hex(6)
        self.kind = kind
        self.state = "running"
        self.progress = None
        self.message = ""
        self.result = None
        self.error = None
        self.started = time.time()
        self.finished = None
        self.task = C.Task(self._on_progress)

    def _on_progress(self, frac, message):
        if frac is not None:
            self.progress = round(float(frac), 4)
        if message:
            self.message = message
            self.progress = None if frac is None else self.progress

    def public(self):
        d = {"id": self.id, "kind": self.kind, "state": self.state, "progress": self.progress, "message": self.message,
             "elapsed": round((self.finished or time.time()) - self.started, 1)}
        if self.result is not None:
            d["result"] = self.result
        if self.error is not None:
            d["error"] = self.error
        return d


class AppState:
    """1つのサーバーの状態。テストで複数のサーバーを作ってもぶつからないよう、グローバルではなくサーバーに持たせる"""

    def __init__(self, opener=None):
        self.lock = threading.Lock()
        self.jobs = OrderedDict()
        self.running = None
        self.cache = pack.Cache()
        self.media = OrderedDict()        # token -> 実際のパス(入力に指定した動画・作った粗編集の動画だけ)
        self.media_by_path = {}
        self.out_dirs = set()             # パックを書いたフォルダ(「フォルダを開く」を許すもの)
        self.opener = opener or open_folder

    # ---- 配信を許すファイル
    def register_media(self, path):
        real = os.path.realpath(str(path))
        key = os.path.normcase(real)
        with self.lock:
            tok = self.media_by_path.get(key)
            if tok is None:
                tok = secrets.token_urlsafe(12)
                self.media_by_path[key] = tok
            self.media[tok] = real
            self.media.move_to_end(tok)
            while len(self.media) > 64:
                old, p = self.media.popitem(last=False)
                self.media_by_path.pop(os.path.normcase(p), None)
        return "/media/" + tok

    def media_path(self, tok):
        with self.lock:
            return self.media.get(tok)

    def allow_out_dir(self, path):
        with self.lock:
            self.out_dirs.add(os.path.normcase(os.path.realpath(str(path))))

    def out_dir_allowed(self, path):
        with self.lock:
            return os.path.normcase(os.path.realpath(str(path))) in self.out_dirs

    # ---- ジョブ(同時に1つだけ。無音の検出・書き出しは重いので、画面の二度押しで並ばないように)
    def start_job(self, kind, fn):
        with self.lock:
            if self.running is not None and self.running.state == "running":
                raise ApiError("busy", "前の処理が終わっていません(「取り消す」で止められます)", 409,
                               {"job": self.running.public()})
            job = Job(kind)
            self.running = job
            self.jobs[job.id] = job
            while len(self.jobs) > 20:
                self.jobs.popitem(last=False)
        th = threading.Thread(target=self._run, args=(job, fn), daemon=True, name="job-" + kind)
        th.start()
        return job

    def _run(self, job, fn):
        try:
            job.result = fn(job.task)
            job.state = "done"
        except C.Cancelled:
            job.state = "cancelled"
            job.message = "取り消しました"
        except C.OutputExists as e:
            job.state = "error"
            job.error = {"code": "exists", "message": str(e), "files": [p.name for p in e.existing]}
        except (C.ToolError, ApiError) as e:
            job.state = "error"
            job.error = {"code": getattr(e, "code", "tool"), "message": getattr(e, "message", None) or str(e)}
        except Exception as e:   # 想定外でもサーバーは落とさない(詳細は serve.log)
            log("error: job %s: %s" % (job.kind, traceback.format_exc()))
            job.state = "error"
            job.error = {"code": "internal", "message": "内部エラー: %s %s(work/serve.log に記録しました)" % (e.__class__.__name__, str(e)[:200])}
        finally:
            job.finished = time.time()

    def job(self, jid):
        with self.lock:
            j = self.jobs.get(str(jid or ""))
        if j is None:
            raise ApiError("not_found", "その処理は見つかりません(サーバーを起動し直した可能性があります)", 404)
        return j


def open_folder(path):
    """フォルダをエクスプローラー(Mac は Finder)で開く。フォルダであることは呼び出し側で確かめる(実行ファイルを起動しないように)"""
    if os.name == "nt":
        os.startfile(path)  # noqa: S606(フォルダだけ。シェルは通さない)
    elif sys.platform == "darwin":
        subprocess.Popen(["open", path])
    else:
        subprocess.Popen(["xdg-open", path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


# ---------------------------------------------------------------- 画面の指定 → pack.Request

def _num(v, what, lo, hi, default=None, integer=False):
    if v is None or v == "":
        if default is None:
            raise ApiError("bad_value", "%sを入れてください" % what)
        return default
    if isinstance(v, str):
        try:
            v = float(v.strip())
        except ValueError:
            raise ApiError("bad_value", "%sは数値で入れてください" % what)
    if isinstance(v, bool) or not isinstance(v, (int, float)) or v != v or v in (float("inf"), float("-inf")):
        raise ApiError("bad_value", "%sは数値で入れてください" % what)
    if not lo <= v <= hi:
        raise ApiError("bad_value", "%sは %g〜%g で入れてください" % (what, lo, hi))
    return int(v) if integer else float(v)


def _str(v, what, maxlen=200):
    if v is None:
        return ""
    if not isinstance(v, str) or len(v) > maxlen:
        raise ApiError("bad_value", "%sが正しくありません" % what)
    return v.strip()


def request_from_spec(spec):
    """画面の指定(JSON)→ pack.Request。モード: silence(① 無音で自動カット)/ keep(② 残す区間)/ list(③ 時刻リスト)
    どのモードでも、文字起こしがあれば「カット済」の行を削る(dropCutRows。既定 true)を重ねられる。②③では無音も重ねられる"""
    if not isinstance(spec, dict):
        raise ApiError("bad_request", "指定の形が正しくありません")
    video = input_path(spec.get("video"), "video")
    if video is None:
        raise ApiError("no_video", "動画のパスを入れてください")
    sub = input_path(spec.get("srt"), "srt")
    tr = input_path(spec.get("transcript"), "transcript")
    plan = input_path(spec.get("plan"), "plan")
    mode = spec.get("mode") or "silence"
    if mode not in ("silence", "keep", "list"):
        raise ApiError("bad_value", "カットの決め方が正しくありません")
    sil = spec.get("silence") if isinstance(spec.get("silence"), dict) else {}
    noise = _num(sil.get("noise"), "無音とみなす音量", -90, 0, -35.0)
    smin = _num(sil.get("min"), "無音の長さ", 0.05, 60, 0.6)
    spad = _num(sil.get("pad"), "話の前後に残す秒数", 0, 10, 0.15)
    use_silence = mode == "silence" or bool(spec.get("silenceExtra"))
    base, keep_pairs, drop_pairs, handles = "all", None, [], None
    if mode == "keep":
        src = spec.get("keepSource") or ("plan" if plan else "transcript")
        if src == "plan":
            if plan is None:
                raise ApiError("no_plan", "残す区間(cut-plan)のファイルを入れてください")
            base = "plan"
        elif src == "transcript":
            if tr is None:
                raise ApiError("no_transcript", "文字起こしのファイルを入れてください")
            base = "rows"
        else:
            raise ApiError("bad_value", "残す区間の元が正しくありません")
        if spec.get("handles") not in (None, ""):
            handles = _num(spec.get("handles"), "前後の余白", 0, 600)
    elif mode == "list":
        text = spec.get("listText") or ""
        if not isinstance(text, str) or len(text) > 1_000_000:
            raise ApiError("bad_value", "時刻リストが長すぎます")
        try:
            pairs = C.parse_cut_list(text)
        except C.ToolError as e:
            raise ApiError("bad_list", "時刻リスト: %s" % e)
        if spec.get("listKind") == "drop":
            drop_pairs = pairs
        else:
            if not pairs:
                raise ApiError("bad_list", "残す区間を1行以上書いてください(例: 0:05 0:20)")
            base, keep_pairs = "list", pairs
    adv = spec.get("advanced") if isinstance(spec.get("advanced"), dict) else {}
    fps = _str(adv.get("fps"), "フレームレート", 20) or None
    frames = adv.get("frames")
    frames = None if frames in (None, "") else _num(frames, "フレーム数", 1, 10**9, integer=True)
    return pack.Request(
        video=video, sub=sub, transcript=tr, plan=plan, base=base, keep_pairs=keep_pairs, drop_pairs=drop_pairs,
        handles=handles, silence=use_silence, noise=noise, silence_min=smin, silence_pad=spad,
        drop_cut_rows=spec.get("dropCutRows") is not False,
        min_len=_num(spec.get("minLen"), "最短の長さ", 0, 3600, 0.3), join_gap=_num(spec.get("joinGap"), "つなぐ隙間", 0, 3600, 0.0),
        fps=fps, frames=frames, src_start_tc=_str(adv.get("srcStartTc"), "元動画の開始タイムコード", 20) or None,
        rec_start=_str(adv.get("recStart"), "タイムラインの開始タイムコード", 20) or "01:00:00:00",
        reel=_str(adv.get("reel"), "リール名", 40) or "AX", name=_str(adv.get("name"), "EDL のタイトル", 200) or None)


def output_from_spec(o, video):
    o = o if isinstance(o, dict) else {}
    out = clean_path(o.get("dir"), "out")
    textplus = bool(o.get("textplus"))
    try:
        target = TP.parse_target(o.get("textplusFps"), o.get("textplusSize"))
    except ValueError as e:
        raise ApiError("bad_textplus", str(e))
    return {"dir": Path(out) if out else pack.default_out_dir(video), "render": bool(o.get("render")),
            "copyVideo": bool(o.get("copyVideo")) or textplus, "fcpxml": bool(o.get("fcpxml")) and not textplus,
            "textplus": textplus, "textplusTarget": target, "force": o.get("force") is True,
            "crf": _num(o.get("crf"), "粗編集の画質", 0, 51, 18, integer=True)}


FILE_NOTES = {"edl": "カット(EDL)", "srt": "カット後の字幕", "readme": "友人向けの手順(Text+ パックでは予備の EDL の手順)", "plan": "カットの記録",
              "fcpxml": "補助の FCPXML", "roughcut": "粗編集の動画", "video": "元動画のコピー",
              "textplus_plan": "Text+生成用データ", "textplus_script": "Resolve内で実行するLua Text+生成スクリプト",
              "textplus_install": "Luaスクリプト登録用PowerShell", "textplus_launcher": "Luaスクリプト登録バッチ",
              "textplus_readme": "友人向けの手順(Text+)"}


def file_info(kind, p):
    try:
        size = os.path.getsize(p)
    except OSError:
        size = None
    return {"kind": kind, "name": Path(p).name, "path": str(p), "size": size, "note": FILE_NOTES.get(kind, "")}


# ---------------------------------------------------------------- 入力の中身(/api/inspect)

def fps_label(fps):
    v = fps[0] / fps[1]
    return ("%.3f" % v).rstrip("0").rstrip(".")


def inspect_inputs(app, o):
    out, suggest = {}, None
    for field in ("video", "srt", "transcript", "plan"):
        if o.get(field) in (None, ""):
            continue
        try:
            p = input_path(o.get(field), field)
            out[field] = dict(_inspect_one(app, field, p), ok=True, path=str(p), name=p.name)
            if field in ("transcript", "plan") and out[field].get("mediaPath") and not o.get("video"):
                suggest = suggest or out[field]["mediaPath"]
        except (ApiError, C.ToolError) as e:
            out[field] = {"ok": False, "error": getattr(e, "message", None) or str(e)}
    return {"inputs": out, "suggestVideo": suggest}


def _inspect_one(app, field, p):
    if field == "video":
        meta = app.cache.probe(p)
        fps = meta["fps"]
        src, desc, w = C.resolve_src_start(p, None, meta)
        return {"size": os.path.getsize(p), "w": meta["w"], "h": meta["h"], "fps": list(fps), "fpsLabel": fps_label(fps),
                "total": meta["total"], "durationSec": round(meta["total"] * fps[1] / fps[0], 3), "audio": bool(meta["audio"]),
                "codec": meta["codec"], "pixFmt": meta["pix_fmt"], "framesSource": meta["frames_source"], "vfr": meta.get("vfr", False),
                "startTc": src, "startTcDesc": desc,
                "warnings": [m for m in meta["warnings"] if "開始タイムコード" not in m] + w + C.name_warnings(p),
                "mediaUrl": app.register_media(p), "defaultOutDir": str(pack.default_out_dir(p))}
    if field == "srt":
        cues = S.parse_subs(S.read_sub_file(p))
        if not cues:
            raise C.ToolError("字幕を1件も読み取れませんでした(SRT/VTT の形式を確認してください)")
        return {"count": len(cues), "lastSec": round(max(b for _, b, _ in cues) / 1000, 3),
                "preview": [t[:60] for _, _, t in cues[:3]]}
    if field == "transcript":
        tr = C.read_transcript(p)
        rows = tr["rows"]
        return {"rows": len(rows), "kept": sum(1 for r in rows if C.row_is_kept(r)), "cut": sum(1 for r in rows if r["cut"]),
                "bad": tr["bad"], "title": tr["title"][:120], "mediaPath": C.resolve_media_path(tr["media"], p)}
    doc = AC.read_cut_plan(p)
    return {"segments": len(doc["segments"]), "tool": doc["tool"][:60], "fineGrained": doc["fineGrained"],
            "includesHandles": doc["includesHandles"], "defaultHandles": AC.default_handles(doc),
            "totalSec": round(sum(s["end_seconds"] - s["start_seconds"] for s in doc["segments"]), 3),
            "mediaPath": C.resolve_media_path(doc["media"], p)}


# ---------------------------------------------------------------- アップロード(字幕・文字起こし・cut-plan の中身)

_WIN_RESERVED = {"CON", "PRN", "AUX", "NUL"} | {"COM%d" % i for i in range(1, 10)} | {"LPT%d" % i for i in range(1, 10)}


def safe_upload_name(name, kind):
    """ブラウザから来たファイル名を、保存してよい名前に(フォルダの部分・使えない文字・Windows の予約名を除く)"""
    exts = UPLOAD_LIMITS[kind][1]
    base = os.path.basename(str(name or "").replace("\\", "/"))
    base = re.sub(r'[\x00-\x1f<>:"/\\|?*]+', "_", base).strip(" .")
    stem, ext = os.path.splitext(base)
    if ext.lower() not in exts:
        raise ApiError("bad_ext", "このファイルの種類(%s)はここに入れられません。使えるもの: %s" % (ext or "拡張子なし", " ".join(exts)))
    stem = stem[:80] or "upload"
    if stem.split(".")[0].upper() in _WIN_RESERVED:
        stem = "_" + stem
    return stem + ext.lower()


def clean_uploads(keep=UPLOAD_KEEP):
    """古いアップロードを消す(keep=0 で全部。起動時)"""
    try:
        dirs = sorted((d for d in os.scandir(UPLOAD_DIR) if d.is_dir()), key=lambda d: d.name)
    except OSError:
        return
    for d in dirs[:max(0, len(dirs) - keep)] if keep else dirs:
        shutil.rmtree(d.path, ignore_errors=True)


def save_upload(kind, name, data):
    if kind not in UPLOAD_LIMITS:
        raise ApiError("bad_kind", "アップロードの種類が正しくありません")
    fname = safe_upload_name(name, kind)
    folder = os.path.join(UPLOAD_DIR, time.strftime("%Y%m%d-%H%M%S-") + secrets.token_hex(4))
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, fname)
    S.write_bytes_atomic(path, data)
    clean_uploads()
    return {"path": path, "name": fname, "size": len(data)}


# ---------------------------------------------------------------- HTTP

def disk_version():
    """ディスク上の cut2resolve_core.py の版(画面に埋め込む)。動いているサーバー(メモリ上の SERVER_VERSION)と違えば、
    古いサーバーが新しいファイルを配っている = 起動し直しが必要、と画面が気づける(版の正は core の1か所のまま)"""
    try:
        with open(os.path.join(CODE_DIR, "cut2resolve_core.py"), encoding="utf-8") as f:
            m = re.search(r'^VERSION\s*=\s*"([^"]+)"', f.read(), re.M)
        return m.group(1) if m else SERVER_VERSION
    except OSError:
        return SERVER_VERSION


class Handler(BaseHTTPRequestHandler):
    server_version = "cut2resolve"
    timeout = SOCKET_TIMEOUT

    @property
    def ctx(self):
        """port・allowed_hosts・app を持つもの。単独ではこのサーバー(C2RServer)、入口に取り込まれたときは MOUNT"""
        if isinstance(self.server, C2RServer) or MOUNT is None:
            return self.server
        return MOUNT

    @property
    def app(self):
        return self.ctx.app

    def log_message(self, fmt, *args):
        if self.path.startswith(QUIET_PATHS):
            return
        sys.stderr.write("[%s] %s\n" % (self.log_date_time_string(), fmt % args))

    # ---- 検査
    def _host_ok(self):          # DNS rebinding 対策
        return (self.headers.get("Host") or "") in self.ctx.allowed_hosts

    def _origin_ok(self):        # 他サイトからの書き込み(CSRF)対策。"http://" + 許可した Host と完全一致だけ
        o = self.headers.get("Origin")
        return o is None or o in {"http://" + h for h in self.ctx.allowed_hosts}

    def _fetch_site_ok(self):
        return self.headers.get("Sec-Fetch-Site") in (None, "same-origin", "none")

    def _navigation_ok(self, path):
        """他のツールの画面のリンク(http://localhost:8800 → http://localhost:8810/?video=...)で、この画面を開くのは許す。
        ポートが違うだけでもブラウザは Sec-Fetch-Site: same-site を送るため、以前の検査では 403 になっていた。
        画面を開くだけで、URL で処理は始まらない(docs/pipeline.md の 3)。API は同じ画面からだけ。iframe は frame-ancestors で拒否"""
        return (path in ("/", "/index.html") and self.headers.get("Sec-Fetch-Mode") == "navigate"
                and self.headers.get("Sec-Fetch-Dest", "document") == "document")

    def _guard(self, write, path=""):
        if not self._host_ok():
            self._fail(403, "forbidden", "このツールは http://localhost:%d%s から開いてください(Host が違います)" % (self.ctx.port, BASE_PATH))
            return False
        if not (self._fetch_site_ok() or (not write and self._navigation_ok(path))) or (write and not self._origin_ok()):
            self._fail(403, "forbidden", "別のサイト・別のツールの画面からの操作は受け付けません")
            return False
        return True

    # ---- 応答
    def _send(self, code, body=b"", ctype="text/plain; charset=utf-8", extra=None):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _json(self, code, obj):
        self._send(code, json.dumps(obj, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8")

    def _fail(self, code, error, message, extra=None):
        self._json(code, dict(extra or {}, error=error, message=message))

    def _safe(self, fn):
        try:
            fn()
        except ApiError as e:
            self._fail(e.status, e.code, e.message, e.extra)
        except C.OutputExists as e:
            self._fail(409, "exists", str(e), {"files": [p.name for p in e.existing]})
        except C.ToolError as e:
            self._fail(400, "tool", str(e))
        except (BrokenPipeError, ConnectionError, socket.timeout):
            pass
        except Exception as e:
            log("error: %s %s: %s" % (self.command, self.path.split("?", 1)[0], traceback.format_exc()))
            try:
                self._fail(500, "internal", "内部エラー: %s(work/serve.log に記録しました)" % e.__class__.__name__)
            except Exception:
                pass

    def _read_body(self, limit, ctype):
        if (self.headers.get("Content-Type") or "").split(";")[0].strip().lower() != ctype:
            raise ApiError("bad_type", "Content-Type は %s にしてください" % ctype, 415)
        try:
            length = int(self.headers.get("Content-Length") or "")
        except ValueError:
            raise ApiError("bad_length", "Content-Length が正しくありません", 411)
        if length <= 0 or length > limit:
            raise ApiError("too_big", "送る内容が空か、大きすぎます(上限 %dMB)" % max(1, limit // 1048576), 413)
        data = self.rfile.read(length)
        if len(data) != length:
            raise ApiError("bad_length", "送る内容が途中で切れました", 400)
        return data

    def _read_json(self):
        raw = self._read_body(MAX_BODY, "application/json")
        try:
            obj = json.loads(raw.decode("utf-8"), parse_constant=C._reject_constant)
        except (UnicodeDecodeError, ValueError):
            raise ApiError("bad_json", "JSON として読めません")
        if not isinstance(obj, dict):
            raise ApiError("bad_json", "JSON のオブジェクトを送ってください")
        return obj

    # ---- GET
    def do_HEAD(self):
        self._safe(self._get)

    def do_GET(self):
        self._safe(self._get)

    def _get(self):
        u = urllib.parse.urlsplit(self.path)
        if not self._guard(False, u.path):
            return
        q = urllib.parse.parse_qs(u.query)
        if u.path in STATIC:
            return self._static(STATIC[u.path])
        if u.path.startswith("/media/"):
            return self._media(u.path[len("/media/"):])
        routes = {
            "/api/ping": lambda: {"app": APP_ID, "version": SERVER_VERSION},
            "/api/siblings": lambda: siblings(self.ctx.port, self_path=BASE_PATH),
            "/api/state": self._state,
            "/api/job": lambda: self.app.job((q.get("id") or [""])[0]).public(),
        }
        fn = routes.get(u.path)
        if fn is None:
            return self._fail(404, "not_found", "見つかりません")
        self._json(200, fn())

    def _static(self, name):
        fn = os.path.join(CODE_DIR, name)
        try:
            with open(fn, "rb") as f:
                body = f.read()
        except OSError:
            return self._fail(404, "not_found", "%s が見つかりません(ファイルが欠けています)" % name)
        extra = {}
        if name == "index.html":
            body = body.replace(b"__APP_VERSION__", disk_version().encode("ascii", "replace"))
            extra = {"Content-Security-Policy": CSP, "X-Frame-Options": "DENY"}
        self._send(200, body, STATIC_TYPES[os.path.splitext(name)[1]], extra)

    def _state(self):
        job = self.app.running
        return {"app": APP_ID, "version": SERVER_VERSION, "ffmpeg": bool(shutil.which("ffmpeg")), "ffprobe": bool(shutil.which("ffprobe")),
                "platform": sys.platform, "canOpenFolder": True,
                "job": job.public() if job is not None and job.state == "running" else None,
                "defaults": {"noise": -35.0, "silenceMin": 0.6, "silencePad": 0.15, "minLen": 0.3, "joinGap": 0.0,
                             "handlesPlan": AC.DEFAULT_HANDLES, "handlesTranscript": 0.0, "crf": 18, "recStart": "01:00:00:00"},
                "uploadLimits": {k: v[0] for k, v in UPLOAD_LIMITS.items()}}

    def _media(self, tok):
        """入力に指定した動画・作った粗編集の動画だけを Range 対応で配信する(パスは受け取らない。登録した合言葉だけ)"""
        real = self.app.media_path(tok) if re.fullmatch(r"[A-Za-z0-9_-]{8,40}", tok or "") else None
        if not real or not os.path.isfile(real):
            return self._fail(404, "not_found", "見つかりません")
        size = os.path.getsize(real)
        ext = os.path.splitext(real)[1].lower()
        a, b, code = 0, size - 1, 200
        m = re.match(r"^bytes=(\d*)-(\d*)$", (self.headers.get("Range") or "").strip())
        if m and (m.group(1) or m.group(2)):
            if m.group(1):
                a = int(m.group(1))
                b = int(m.group(2)) if m.group(2) else size - 1
            else:
                a = max(0, size - int(m.group(2)))
            b = min(b, size - 1)
            if a > b or a >= size:
                return self._send(416, b"", extra={"Content-Range": "bytes */%d" % size})
            code = 206
        self.send_response(code)
        self.send_header("Content-Type", MEDIA_TYPES.get(ext, "application/octet-stream"))
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Length", str(b - a + 1 if size else 0))
        if code == 206:
            self.send_header("Content-Range", "bytes %d-%d/%d" % (a, b, size))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Security-Policy", "default-src 'none'; sandbox")
        self.end_headers()
        if self.command == "HEAD" or not size:
            return
        with open(real, "rb") as f:
            f.seek(a)
            left = b - a + 1
            while left > 0:
                chunk = f.read(min(256 * 1024, left))
                if not chunk:
                    break
                self.wfile.write(chunk)
                left -= len(chunk)

    # ---- POST
    def do_POST(self):
        self._safe(self._post)

    def _post(self):
        u = urllib.parse.urlsplit(self.path)
        if not self._guard(True, u.path):
            return
        if u.path == "/api/upload":
            q = urllib.parse.parse_qs(u.query)
            kind = (q.get("kind") or [""])[0]
            if kind not in UPLOAD_LIMITS:
                raise ApiError("bad_kind", "アップロードの種類が正しくありません")
            data = self._read_body(UPLOAD_LIMITS[kind][0], "application/octet-stream")
            return self._json(200, save_upload(kind, (q.get("name") or [""])[0], data))
        routes = {"/api/inspect": self._inspect, "/api/plan": self._plan, "/api/build": self._build,
                  "/api/job/cancel": self._cancel, "/api/open-folder": self._open_folder}
        fn = routes.get(u.path)
        if fn is None:
            return self._fail(404, "not_found", "見つかりません")
        obj = self._read_json()
        self._json(200, fn(obj))

    def _inspect(self, o):
        return inspect_inputs(self.app, o)

    def _plan(self, o):
        req = request_from_spec(o.get("spec"))
        app = self.app
        out_opts = output_from_spec(o.get("output"), req.video)

        def work(task):
            plan = pack.plan_cut(req, task=task, cache=app.cache)
            out_dir, paths, existing = pack.planned_outputs(plan, out_opts["dir"], out_opts["render"], out_opts["copyVideo"],
                                                            out_opts["fcpxml"], out_opts["textplus"])
            res = pack.summary(plan)
            res["mediaUrl"] = app.register_media(plan.video)
            res["outputs"] = {"dir": str(out_dir), "files": [p.name for p in paths.values()], "existing": [p.name for p in existing]}
            return res
        return {"job": app.start_job("plan", work).public()}

    def _build(self, o):
        req = request_from_spec(o.get("spec"))
        app = self.app
        out = output_from_spec(o.get("output"), req.video)
        if out["dir"].exists() and not out["dir"].is_dir():
            raise ApiError("bad_out", "出力先がフォルダではありません: %s" % out["dir"])
        if not out["force"]:   # 先に分かる範囲で上書きの確認(字幕の有無は入力から見積もる。最終的な確認はジョブの中でも行う)
            names = pack.pack_paths(req.video, out["dir"], bool(req.sub or req.transcript), out["render"], out["copyVideo"],
                                    out["fcpxml"], out["textplus"])
            existing = [p for p in names.values() if p.exists()]
            if existing:
                raise ApiError("exists", "出力ファイルが既にあります", 409, {"files": [p.name for p in existing], "dir": str(out["dir"])})

        def work(task):
            plan = pack.plan_cut(req, task=task, cache=app.cache)
            res = pack.build_pack(plan, out["dir"], render=out["render"], copy_video=out["copyVideo"], fcpxml=out["fcpxml"],
                                  textplus=out["textplus"], textplus_target=out["textplusTarget"],
                                  force=out["force"], crf=out["crf"], task=task)
            app.allow_out_dir(res["out_dir"])
            files = [file_info(k, p) for k, p in res["files"]]
            r = {"outDir": str(res["out_dir"]), "files": files, "readme": res["readme"], "warnings": res["warnings"],
                 "summary": pack.summary(plan), "mediaUrl": app.register_media(plan.video)}
            rough = dict(res["files"]).get("roughcut")
            if rough:
                r["roughcutUrl"] = app.register_media(rough)
            return r
        return {"job": app.start_job("build", work).public()}

    def _cancel(self, o):
        job = self.app.job(o.get("id"))
        if job.state == "running":
            job.task.cancel()
        return {"ok": True, "job": job.public()}

    def _open_folder(self, o):
        p = clean_path(o.get("path"), "out")
        if p is None or not self.app.out_dir_allowed(p):
            raise ApiError("not_allowed", "開けるのは、この画面で作ったパックのフォルダだけです", 403)
        if not os.path.isdir(p):
            raise ApiError("not_found", "フォルダが見つかりません: %s" % p, 404)
        try:
            self.app.opener(os.path.realpath(p))
        except OSError as e:
            raise ApiError("open_failed", "フォルダを開けませんでした: %s" % (e.strerror or e))
        return {"ok": True}


class C2RServer(ThreadingHTTPServer):
    """Windows では SO_REUSEADDR を付けると「他のアプリが使用中のポート」にも bind できてしまい、どちらに繋がるか分からなくなる
    (clip-studio の見直しで見つかった問題)。Windows では使わず、代わりに SO_EXCLUSIVEADDRUSE で独占する"""
    allow_reuse_address = os.name != "nt"
    daemon_threads = True

    def server_bind(self):
        if os.name == "nt" and hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        super().server_bind()


def probe(port):
    """そのポートで動いている cut2resolve の版(cut2resolve でなければ None)"""
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=1)
    try:
        conn.request("GET", "/api/ping", headers={"Host": "127.0.0.1:%d" % port})
        r = conn.getresponse()
        j = json.loads(r.read(4096).decode("utf-8", "replace")) if r.status == 200 else {}
        return str(j.get("version", "")) if isinstance(j, dict) and j.get("app") == APP_ID else None
    except (OSError, ValueError, http.client.HTTPException):
        return None
    finally:
        conn.close()


def _bound(srv, opener=None):
    p = srv.server_address[1]
    srv.port = p
    srv.allowed_hosts = {"localhost:%d" % p, "127.0.0.1:%d" % p}
    srv.app = AppState(opener)
    return srv, p


def make_server(start_port=DEFAULT_PORT, opener=None):
    """start_port から20個のうち空いているポートで待ち受ける。同じ版の cut2resolve が動いていれば (None, そのポート)。
    start_port=0 は OS に空きポートを選ばせる(テスト用: 他のテストと同時に走らせてもぶつからない)"""
    if start_port == 0:
        return _bound(C2RServer(("127.0.0.1", 0), Handler), opener)
    for p in range(start_port, start_port + 20):
        ver = probe(p)
        if ver == SERVER_VERSION:
            return None, p
        if ver is not None:
            print("※ ポート%d では古い版の cut2resolve が動いています。その黒い画面を閉じてください。" % p)
            continue
        try:
            srv = C2RServer(("127.0.0.1", p), Handler)
        except OSError:
            continue
        return _bound(srv, opener)
    raise SystemExit("空いているポートが見つかりません(%d〜%d)" % (start_port, start_port + 19))


class MountContext:
    """入口の統合サーバーに取り込まれたときの状態(単独のときの C2RServer の port・allowed_hosts・app に当たるもの)"""

    def __init__(self, port, allowed_hosts, opener=None):
        self.port = port
        self.allowed_hosts = set(allowed_hosts)
        self.app = AppState(opener)


def _startup(port, base_path="/"):
    """待ち受け以外の起動の準備。前回のアップロードを消し、.runtime を書く。戻り値は .runtime のパス(書けなければ None)"""
    global BASE_PATH
    BASE_PATH = base_path
    shutil.rmtree(UPLOAD_DIR, ignore_errors=True)   # 前回のアップロードは消す(画面に残ったパスは読み込み直しで分かる)
    runtime = write_runtime(port, base_path)
    log("起動 v%s port=%d%s pid=%d python=%s" % (SERVER_VERSION, port, "" if base_path == "/" else " path=" + base_path,
                                               os.getpid(), sys.version.split()[0]))
    return runtime


def prepare(port, base_path="/", opener=None):
    """入口の統合サーバー(app/mount.py)に取り込まれるときの起動の準備。状態(ジョブ・配信を許す動画など)は MOUNT に持つ。
    許す Host は、mount.py が先に入れた ALLOWED_HOSTS(入口のポート)。シグナルの受け取りは入口が行う"""
    global MOUNT
    MOUNT = MountContext(port, ALLOWED_HOSTS or {"localhost:%d" % port, "127.0.0.1:%d" % port}, opener)
    return _startup(port, base_path)


def busy():
    """書き出しなどのジョブが動いているか(入口の「すべて終了」の確認用)"""
    job = MOUNT.app.running if MOUNT else None
    return job is not None and job.state == "running"


def finish():
    """取り込まれたときの後始末。動いているジョブ(ffmpeg での書き出しなど)を取り消し、自分が書いた .runtime の記録を消す"""
    if MOUNT is None:
        return
    job = MOUNT.app.running
    if job is not None and job.state == "running":
        job.task.cancel()
    remove_runtime(MOUNT.port)
    log("終了(入口)")


def mounted_elsewhere():
    """入口(start-all.bat)の統合サーバーの中で cut2resolve が動いていれば、その URL。
    start.bat からの起動は2つ目のサーバーを立てず、そちらを開くだけにする(出力フォルダの取り合い・混乱を避ける)"""
    e = read_runtime_entry(TOOL_ID)
    if e and e[1] != "/" and ping_app(e[0], 1, e[1]) == APP_ID:
        return "http://localhost:%d%s" % e
    return None


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="replace")
        except Exception:
            pass
    live = mounted_elsewhere()
    if live:
        print("入口の中ですでに起動しています。ブラウザで開きます:", live)
        if "--no-open" not in argv:
            webbrowser.open(live)
        return 0
    args = [a for a in argv if not a.startswith("--")]
    srv, port = make_server(int(args[0]) if args else DEFAULT_PORT)
    url = "http://localhost:%d/" % port
    if srv is None:
        print("すでに起動しています。ブラウザで開きます:", url)
        if "--no-open" not in argv:
            webbrowser.open(url)
        return 0
    runtime = _startup(port)
    print("cut2resolve:", url, "(終了は Ctrl+C またはこの画面を閉じる)")
    if not (shutil.which("ffmpeg") and shutil.which("ffprobe")):
        print("※ ffmpeg / ffprobe が見つかりません(README の準備を確認してください)")

    import signal

    def on_signal(signum, frame):
        raise SystemExit(0)
    for n in ("SIGTERM", "SIGHUP", "SIGBREAK"):   # 黒い画面の×(Windows は SIGBREAK)・kill でも .runtime を消してから終わる
        if hasattr(signal, n):
            try:
                signal.signal(getattr(signal, n), on_signal)
            except (ValueError, OSError):
                pass
    if "--no-open" not in argv:
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nCtrl+C を受け取ったので終了します")
    finally:
        if runtime:
            remove_runtime(port)
        log("終了")
    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
