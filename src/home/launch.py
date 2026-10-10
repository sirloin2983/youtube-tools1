# -*- coding: utf-8 -*-
"""入口(ランチャー)— 3つのツールのサーバーをまとめて起動・終了し、入口の画面を出す。

    python src/home/launch.py [--no-open] [--port 8700] [--only studio,transcribe,cut2resolve]

統合計画の段階1(docs/design/integration-plan.md)。ツールのコードは変えず、各ツールのフォルダで
`serve.py <既定のポート> --no-open` を子プロセスとして起動する。ツール間の受け渡し・ポートの共有は従来どおり(docs/spec/pipeline.md)。

  GET  /                                  入口の画面(portal.html)
  GET  /api/ping                          {"app": "ytt-launcher", "version"}
  GET  /api/cases                         案件(配信1本)ごとの切り抜き・文字起こし・パック(src/manage/cases/cases.py)
  POST /api/cases/update                 {id, status?, memo?} 案件の状態・メモ
  POST /api/cases/auto                   {op: seen|deliver|discard, id, markId} 自動でできた切り抜き(線 D の M9・M12)を 見た・採用 = 友人へ届ける・
                                          要らない = ごみ箱フォルダへ(src/manage/cases/cases.py の auto_review。deliver の応答の job は api/ytt/deliver の status で聞き直す)
  GET  /api/autorun                       まとめて実行の状態(src/home/autorun.py)。runs = この起動の実行・past = 配信・文書ごとの前回の結果(記録のファイルから)
  GET  /api/autorun/history?limit=&offset=  終わった実行の記録(<作業データ>/app/logs/autorun-runs.jsonl と .1。新しい順。limit は既定 50・最大 200)
  POST /api/autorun/start                 {id, mode: full|adopted|transcribe, top?, streamer?, marks?, overwrite?} 配信1本ぶんを順に自動で(marks: そのマークだけ・overwrite: パックがあれば作り直す)
  POST /api/autorun/estimate              {id, mode, marks?, top?, overwrite?} か {ids, overwrite?} 実行と同じ規則の見積もり(段ごとの本数と飛ばす理由。書き込まない)
  POST /api/autorun/cancel                {runId}
  POST /api/autorun/start-docs            {ids: [文書の id], overwrite?} 「編集」の履歴で選んだ文書を、行が無ければ文字起こし → パック(12 ⑦(b))
  GET  /api/intake                        友人からの依頼の受付の状態・設定・最近の依頼(src/human/friend/intake.py。docs/spec/friend-intake.md)
  POST /api/intake/scan                   {} 今すぐフォルダを見る(裏で。応答は今の状態)
  GET  /api/backup                        作業データのバックアップの状態・設定(src/manage/keep/backup.py。docs/spec/data-location.md の「バックアップ」)
  POST /api/backup/run                    {} 今すぐ写す(裏で。応答は今の状態)
  GET  /api/accuracy                      精度の自動測定の状態・領域ごとの直近と前回・入口の条件 goals(今 / 目標 / あと。0.38.0)(src/eval/drill/accuracy.py。git の履歴(679ff01 以前)の docs/plan/q3-q4-design.md の (a))
  POST /api/accuracy/run                  {} 今すぐ測る(裏で。手が空くまで待つ。オフなら 409。応答は今の状態)
  POST /api/autorun/start-new             {items: [{id, title, channel}], top?, streamer?} スタジオの ① 探す で選んだ配信を「解析から全部」で
  GET  /api/status                        {"app", "version", "tools": [...], "dataDir"}(ツールごとの状態・作業データの置き場所)
  GET  /api/health[?refresh=1]            「調子」(段9 9-1。src/manage/ops/health.py): 版の期待と実際・認識ワーカー・ffmpeg/ffprobe/yt-dlp・空き容量・作業データの大きさ・エラーの件数
  GET  /api/cleanup                       片付けの候補(段9 9-2。src/manage/keep/cleanup.py)。POST /api/cleanup {ids} で候補に出した物だけをごみ箱フォルダへ移す(TRASH_DAYS 日で起動時に消える)
  GET  /api/log?tool=<ID>&lines=N         ツールの出力(<作業データ>/app/logs/<ID>.log)の末尾
  POST /api/tools/<ID>/start|stop|restart {} → {"tool": {...}}
  POST /api/shutdown                      {} → この入口から起動したツールを止めて、入口も終わる。録画中でなければ録画の部品も止める
                                          (録画中なら残して、応答に recorderKept・notice。0.38.1)
  POST /api/window                        {mode: browser|app} 画面を窓(Edge のアプリモード)で開くか(段階7-3。src/home/appwindow.py)
  POST api/ytt/client-log|open-window|open-external|focus-portal|streamer-colors   画面の共通の API(focus-portal: 入口の窓を前に出す・
                                          streamer-colors: 配信者の名前 → メンバーカラーの候補。2026-09-27)。入口の画面(/api/ytt/…)と、取り込んだツールの画面
                                          (/studio/api/ytt/… など。src/home/mount.py が入口へ回す)のどちらからも同じ(段階7。PortalServer.ytt_request)
  POST api/ytt/restart-self               {} → 入口ごと起動し直す(段9 9-3。src/manage/ops/restart.py)。重い処理・人が始めた処理・書き出しの最中は 409 と理由の文。
                                          まとめて実行の待ち・実行中は断らずに、応答に notice(何件が起動し直したあとに続くか。0.41.0)
  GET  /live/…・POST /live/…              リアルタイム切り抜き(線 D。src/home/live.py)。**設定 live.enabled がオンのときだけ**(オフなら今までどおり 404):
                                          録画を始める /live/api/begin・録画元(src/pipeline/ingest/recorder.py)への中継 /live/r/<録画元>/<残り>・マークと書き出し・
                                          サーバー側の「マーク + 書き出し」/live/api/adopt(線 D の M1。0.39.0)。
                                          画面はスタジオの中(P3。/live/ はスタジオへ 302)。0.40.0 から(線 D の M4〜M7): 「調子」の live.disk(空き容量)・
                                          archiveInfo.afterStream(配信後の全自動 = 設定 live.autoAfterStream)。まとめて実行の待ち・実行中は起動し直しで戻る
  POST api/ytt/live                       {op: "status"} → 録画中の録画(全ツールのヘッダーの札。オフなら {enabled: false})/ {op: "stop", recorder, recording}
  POST api/ytt/deliver                    {op: "start", dir, title} → {"job"} / {op: "status", job} → {"job"}。パックを友人へ届ける
                                          (Dropbox の見張るフォルダの 出力 に zip で置く。src/human/friend/deliver.py。2026-10-04)

設計の要点
- 子プロセスの出力は <作業データ>/app/logs/<ID>.log に書く(1つの黒い画面に3つのツールの出力が混ざらないように)
- ツールが準備できたかは、ツールが書く .runtime/<ID>.json のポートに /api/ping を問い合わせて確かめる。
  pid では確かめない(Windows の os.kill(pid, 0) はプロセスを終了させてしまう。docs/spec/pipeline.md の 4)
- すでに別の黒い画面で動いているツールは「別の画面で起動済み」として扱い、起動も停止もしない(二重起動で data.json を取り合わないため)
- 止めるときは、Windows は Ctrl+Break(子を別のプロセスグループで起動しておく)、Mac/Linux は SIGTERM を送る。
  どちらも各ツールが .runtime を消してから終わる合図。一定時間で終わらなければ強制終了する
"""
import argparse
import http.client
import json
import os
import queue
import re
import secrets
import signal
import socket
import subprocess
import sys
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler

CODE_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(CODE_DIR)
if ROOT not in sys.path:   # 共通部品 ytt(リポジトリ直下)
    sys.path.append(ROOT)
from manage.cases import txindex  # noqa: E402
from ytt import colors as colors_mod, datadir, fsio, httpsec, jobs, layout, runtime, tools, version as _version  # noqa: E402
import mount as mount_mod  # noqa: E402  (src/home/mount.py: 統合サーバーへのツールの取り込み)
import autorun as autorun_mod
from human.friend import intake as intake_mod  # noqa: E402  (src/human/friend/intake.py: 友人からの依頼の受付)
from manage.keep import backup as backup_mod  # noqa: E402  (src/manage/keep/backup.py: 作業データのバックアップ)
from eval.drill import accuracy as accuracy_mod  # noqa: E402  (src/eval/drill/accuracy.py: 精度の自動測定 = src/eval/tools/eval_*.py を手が空いた夜に子プロセスで)
from human.friend import deliver as deliver_mod  # noqa: E402  (src/human/friend/deliver.py: パックを友人へ届ける = Dropbox の 出力 に zip で置く)
from manage.cases import cases as cases_mod  # noqa: E402  (src/manage/cases/cases.py: 案件(配信1本)ごとの紐づけ)
from human.friend import friend_feedback as friend_feedback_mod  # noqa: E402  (src/human/friend/friend_feedback.py: 友人の「要らない」= 切り抜きとパックを ごみ箱 へ・記録を残す。マークは変えない)
import appwindow as appwindow_mod  # noqa: E402  (src/home/appwindow.py: 窓(Edge のアプリモード)で開く。段階7-3)
from manage.ops import clientlog as clientlog_mod  # noqa: E402  (src/manage/ops/clientlog.py: 画面のエラーの記録。段階7-0)
from manage.ops import health as health_mod  # noqa: E402  (src/manage/ops/health.py: 「調子」。段9 9-1)
from manage.keep import cleanup as cleanup_mod  # noqa: E402  (src/manage/keep/cleanup.py: 片付け。段9 9-2)
from manage.ops import restart as restart_mod  # noqa: E402  (src/manage/ops/restart.py: 入口ごと起動し直す。段9 9-3)
import prefs as prefs_mod  # noqa: E402  (src/home/prefs.py: ホームの設定。まとめて実行の既定・配信者の記憶・共通の再生キー)
import live as live_mod  # noqa: E402  (src/home/live.py: リアルタイム切り抜き(線 D)。既定はオフ)
try:   # src/analytics: 分析と日報(/analytics/ を受け持つ。plan/analytics-daily-report.md)。入口を一時フォルダに写すテストでは無いことがある
    from analytics import service as analytics_mod  # noqa: E402
except ImportError:
    analytics_mod = None

APP_ID = "ytt-launcher"
VERSION = _version.VERSION   # 全体の版(ytt/version.py の 1 か所。RS5-E。画面は /api/status の version を表示する)
TOOL_ID = "portal"         # .runtime/portal.json。各ツールの /api/siblings は3つのツールIDしか読まないので影響しない
DEFAULT_PORT = 8700        # 8700〜8719。文字起こし(8775〜8794)・スタジオ(8800〜)・cut2resolve(8810〜)の範囲と重ならない
PORT_RANGE = 20
UI_KIT_DIR = os.path.join(ROOT, layout.UI_KIT_DIR)   # 共通の見た目は正本をそのまま配る(写しを作らない)
LOG_MAX = 1024 * 1024     # ログ(*.log。.gitignore 済み)はこれを超えたら <名前>.old.log に回す(fsio.rotate。回せなければそのまま追記)
PING_TIMEOUT = 0.5
MAX_BODY = 4096
PORTAL_TITLE = "動画編集ツール — ホーム"   # ホームの画面(portal.html)の <title>。窓を前に出すときに題名で探す(test_launch が portal.html と比べる)
YTT_API = mount_mod.YTT_API   # 画面の共通の API の場所(入口の画面・取り込んだツールの画面の両方から。PortalServer.ytt_request)
YTT_BODY_MAX = 16 * 1024   # エラーのスタックが入るので、他の API より大きめ

def _spec(tid, name, sub, port, **kw):
    """ツールの表の 1 行。app(/api/ping の名前。互換のため変えない)と dir(src/ の中のフォルダ)は ytt の正(runtime.TOOL_APPS・layout.TOOL_DIRS)から。
    期待する版は全体の版(ytt/version.py。expected_version)なので、ツールごとの版のファイルは持たない"""
    d = layout.TOOL_DIRS[tid]
    return dict({"id": tid, "app": runtime.TOOL_APPS[tid], "name": name, "sub": sub, "dir": d, "port": port}, **kw)


# 作業の順番どおり。port は各ツールの既定(使用中ならツール自身が次の番号を選ぶ)
TOOLS = (
    _spec("studio", "切り抜きスタジオ", "配信を探す・切り抜く区間を選ぶ・書き出す", 8800),
    _spec("transcribe", "編集", "文字起こし・カット・Resolve へのパック", 8775, venv=True),
    # cut2resolve: 「編集」がパックを作るのに使う(/cut2resolve/api/...)。画面のカードは出さない(hidden。止まっている・落ちたときだけ出す。docs/design/edit-tool-design.md の 6)
    _spec("cut2resolve", "cut2resolve", "「編集」がパックを作るのに使う部品(Resolve へ渡すカットと字幕)", 8810, hidden=True),
)
TOOL_IDS = tuple(t["id"] for t in TOOLS)


# ---------- 小さな道具 ----------
def runtime_dir(root):
    """<リポジトリ直下>/.runtime。環境変数 YTT_RUNTIME_DIR があればそちら(各ツールと同じ規則。ytt.runtime)。"""
    return runtime.runtime_dir(layout.tool_dir("app", root))


# .runtime の読み書き・/api/ping・接続の確認は ytt.runtime(各ツールと同じ規則)
valid_port = runtime.valid_port
read_runtime = runtime.read_runtime     # (rdir, tool) → {"port", "version", "pid", "mtime"} / None。誰でも書けるファイルなので検証して読む


def ping(port, timeout=PING_TIMEOUT, path="/"):
    """127.0.0.1:port の <path>api/ping → {"app", "version"} / None(プロキシを通さない)。"""
    return runtime.ping(port, timeout, path)


def port_open(port, timeout=0.3):
    """そのポートで何かが待ち受けているか(つないですぐ切る)。動作中の確認はこれで行う:
    /api/ping を数秒ごとに送ると、アクセスを記録するツール(文字起こし)の黒い画面・ログが埋まるため。"""
    return runtime.port_open(port, timeout)


def tail(path, lines=200, max_bytes=256 * 1024):
    """ファイルの末尾 lines 行(読めなければ None)。大きなログでも末尾 max_bytes だけ読む。文字コードが崩れた所は置き換える。"""
    try:
        with open(path, "rb") as f:
            f.seek(0, os.SEEK_END)
            size = f.tell()
            start = max(0, size - max_bytes)
            f.seek(start)
            data = f.read()
    except OSError:
        return None
    if start > 0:   # 途中から読んだ最初の行は欠けているので捨てる
        nl = data.find(b"\n")
        data = data[nl + 1:] if nl >= 0 else b""
    text = data.decode("utf-8", "replace").replace("\r\n", "\n").replace("\r", "\n")
    out = text.split("\n")
    if out and out[-1] == "":
        out.pop()
    return out[-lines:] if lines > 0 else []


def expected_version(spec, root):
    """フォルダの中のコードの版 = 全体の版(ytt/version.py をディスクから読み直した値。読めなければ None)。別の画面で古い版が動いているのを見分けるため。
    spec は今は使わない(全ツール同じ版)が、呼び出しの形は残す"""
    return _version.on_disk(root) or None


def tool_python(tool_dir, spec):
    """子を起動する Python(取り込めなかったツールを子プロセスで動かすとき):
    Windows は入口と同じ(py -3 / python)、Mac/Linux の文字起こしは .venv があればそちら。"""
    if os.name != "nt" and spec.get("venv"):
        v = os.path.join(tool_dir, ".venv", "bin", "python")
        if os.access(v, os.X_OK):
            return v
    return sys.executable


def signal_stop(proc):
    """終わってほしい合図を送る(強制終了はしない)。Windows は子のプロセスグループへの Ctrl+Break(SIGBREAK)、
    それ以外は SIGTERM。どちらも各ツールが .runtime を消してから終わる処理につながっている。"""
    try:
        if os.name == "nt":
            os.kill(proc.pid, signal.CTRL_BREAK_EVENT)
        else:
            proc.send_signal(signal.SIGTERM)
    except (OSError, ValueError):
        pass


# ---------- ツール1つの状態 ----------
class Tool:
    """1つのツールのサーバー(子プロセス)の状態。値の変更は lock の中で行う。
    state: stopped 停止 / starting 起動中 / running 動作中 / external 別の画面で起動済み / stopping 停止中 /
           crashed 異常終了 / missing フォルダ・serve.py が無い
    mounted = True は、子プロセスではなく入口のサーバーの中に取り込んで動かしているもの(段階3。src/home/mount.py)"""

    def __init__(self, spec, root, logs_dir):
        self.spec = spec
        self.id = spec["id"]
        self.app = spec["app"]
        self.root = root
        self.dir = os.path.join(root, spec["dir"])
        self.script = os.path.join(self.dir, "serve.py")
        self.log_path = os.path.join(logs_dir, self.id + ".log")
        self.default_port = spec["port"]
        self.lock = threading.RLock()
        self.state = "stopped"
        self.message = ""
        self.since = time.time()
        self.proc = None
        self.managed = False      # この入口が起動した子プロセスか(別の画面で起動したものは止めない)
        self.port = None
        self.version = ""
        self.expected = None
        self.exit_code = None
        self.spawned_at = 0.0
        self.starts = 0
        self.last_ping = 0.0
        self.fail_pings = 0
        self.mounted = False
        self.mount = None
        self.path = "/"

    def set_state(self, state, message=""):
        self.state = state
        self.message = message
        self.since = time.time()

    def snapshot(self):
        with self.lock:
            return {
                "id": self.id, "name": self.spec["name"], "sub": self.spec["sub"], "state": self.state, "message": self.message,
                "since": round(self.since, 3), "port": self.port, "version": self.version, "expectedVersion": self.expected,
                "managed": self.managed, "exitCode": self.exit_code, "starts": self.starts, "mounted": self.mounted, "path": self.path,
                "hidden": bool(self.spec.get("hidden")),
                "log": os.path.relpath(self.log_path, self.root), "hasLog": os.path.exists(self.log_path),
            }


# ---------- まとめて管理 ----------
def app_data_dir(root):
    """入口の作業データの置き場所(%LOCALAPPDATA%\\youtube-tools\\app。inplace なら home フォルダ)。設定(settings.json)・窓の専用のプロファイル・記録。
    入口自身が決める側なので、登録(datadir.register)は見ない(規則は ytt.datadir.locate の1か所。main() が登録し、案件などは resolve で読む)"""
    return datadir.locate("app", root)


def logs_dir_for(root):
    """入口とツールの出力の記録の置き場所: 作業データの置き場所(ytt.datadir。%LOCALAPPDATA%\\youtube-tools\\app\\logs)。
    YTT_DATA_DIR=inplace(テスト)なら src\\home\\logs。記録だけなので、以前の場所からは写さない"""
    return os.path.join(app_data_dir(root), "logs")


class Supervisor:
    def __init__(self, root=ROOT, only=None, ready_timeout=90.0, stop_timeout=8.0, poll=0.5, log=None, ports=None, mounts=()):
        """ports: {"studio": 18800, ...} 既定のポートを変える(テスト用。本物のツールとぶつからないように)
        mounts: 入口のサーバーに取り込むツール("studio" など。src/home/mount.py の MOUNTS にあるもの)。attach() でサーバーを渡してから start する"""
        self.root = os.path.abspath(root)
        self.rdir = runtime_dir(self.root)
        self.logs_dir = logs_dir_for(self.root)
        self.tools = [Tool(s, self.root, self.logs_dir) for s in TOOLS if not only or s["id"] in only]
        for t in self.tools:
            t.default_port = int((ports or {}).get(t.id) or t.default_port)
        self.by_id = {t.id: t for t in self.tools}
        self.ready_timeout = ready_timeout
        self.stop_timeout = stop_timeout
        self.poll = poll
        self.log = log or (lambda msg: None)
        self._halt = threading.Event()
        self._thread = None
        self.mounts = tuple(m for m in mounts if m in mount_mod.MOUNTS)
        self.server = None

    def attach(self, server):
        """入口のサーバー(PortalServer)を渡す。取り込むツールはこのサーバーの中で動く。"""
        self.server = server

    # --- 状態 ---
    def status(self):
        return {"app": APP_ID, "version": VERSION, "tools": [t.snapshot() for t in self.tools],
                "dataDir": datadir.data_root(),   # 作業データの置き場所(画面に出す。inplace のときは null)
                "heavy": jobs.SLOTS.snapshot()}   # 重い処理の実行中・順番待ち(入口の中に取り込んだツールの分)

    def _find_external(self, t, scan=False):
        """別の画面で動いている同じツール (port, version)。.runtime のポートと既定のポートを問い合わせる
        (scan=True なら既定から20個。子が「すでに起動しています」で終わったとき用)。"""
        cands = []
        info = read_runtime(self.rdir, t.id)
        if info and not (self.server and info["port"] == self.server.server_address[1]):   # 自分(この入口)の記録は問い合わせない
            cands.append((info["port"], info["path"]))
        base = t.default_port
        cands += [(p, "/") for p in (range(base, base + PORT_RANGE) if scan else [base])]
        for p, path in dict.fromkeys(cands):   # 同じ所は 1 回だけ問い合わせる(順番はそのまま)
            r = ping(p, 0.3 if scan else PING_TIMEOUT, path)
            if r and r["app"] == t.app:
                return p, r["version"]
        return None

    # --- 起動 ---
    def start(self, tid):
        t = self.by_id[tid]
        with t.lock:
            if t.state in ("starting", "running", "stopping", "external"):
                return t.snapshot()
            t.expected = expected_version(t.spec, self.root)
            if not os.path.isfile(t.script):
                t.proc, t.managed, t.port = None, False, None
                t.set_state("missing", "%s が見つかりません" % os.path.relpath(t.script, self.root))
                self.log("× %s: %s" % (t.spec["name"], t.message))
                return t.snapshot()
            ext = self._find_external(t)
            if ext:
                self._mark_external(t, *ext)
                return t.snapshot()
            if t.id in self.mounts and self.server is not None and self._mount(t):
                return t.snapshot()
            self._spawn(t)
            return t.snapshot()

    def _mount(self, t):
        """入口のサーバーの中に取り込んで動かす。できなければ False(従来どおり子プロセスで起動する)。"""
        m = mount_mod.Mount(self.root, t.id, self.logs_dir)
        try:
            handler = m.start(self.server.server_address[1], self.server.allowed_hosts, self.server.token)
        except Exception as e:   # 取り込めなくても使えるように、子プロセスに切り替える
            self.log("※ %s をホームに取り込めませんでした(%s: %s)。別のプログラムとして起動します" % (t.spec["name"], e.__class__.__name__, e))
            return False
        self.server.mounts[m.prefix] = handler
        t.proc, t.managed, t.mounted, t.mount, t.fail_pings = None, True, True, m, 0
        t.port, t.path, t.version = self.server.server_address[1], m.path, m.version()
        t.starts += 1
        t.set_state("running")
        self.log("○ %s: http://localhost:%d%s (v%s・ホームに取り込み)" % (t.spec["name"], t.port, t.path, t.version))
        return True

    def unmount_all(self):
        """終了の後始末(取り込んだツールの .runtime を消す)。"""
        for t in self.tools:
            if t.mounted and t.mount:
                t.mount.stop()

    def _mark_external(self, t, port, version):
        t.proc, t.managed, t.port, t.version, t.fail_pings = None, False, port, version, 0
        msg = ""
        if t.expected and version and version != t.expected:
            msg = "古い版(v%s)が別の黒い画面で動いています。その画面を閉じてから「起動」を押すと、v%s で起動します" % (version, t.expected)
        t.set_state("external", msg)
        self.log("○ %s: 別の画面で起動済み http://localhost:%d/ (v%s)%s" % (t.spec["name"], port, version, "  ※" + msg if msg else ""))

    def _spawn(self, t):
        os.makedirs(self.logs_dir, exist_ok=True)
        fsio.rotate(t.log_path, LOG_MAX)
        env = dict(os.environ)
        env.setdefault("PYTHONIOENCODING", "utf-8:backslashreplace")   # ファイルへの出力で cp932 に無い文字(絵文字の題名など)で落ちないように
        env["PYTHONUNBUFFERED"] = "1"
        cmd = [tool_python(t.dir, t.spec), "-u", t.script, str(t.default_port), "--no-open"]
        kw = {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP} if os.name == "nt" else {}
        try:
            with open(t.log_path, "ab") as logf:
                logf.write(("\n==== %s ホームから起動 ====\n" % time.strftime("%Y-%m-%d %H:%M:%S")).encode("utf-8"))
                logf.flush()
                proc = subprocess.Popen(cmd, cwd=t.dir, env=env, stdin=subprocess.DEVNULL, stdout=logf, stderr=subprocess.STDOUT, **kw)
        except OSError as e:
            t.proc, t.managed = None, False
            t.set_state("crashed", "起動できませんでした(%s)" % tools.why(e))
            self.log("× %s: %s" % (t.spec["name"], t.message))
            return
        t.proc, t.managed, t.port, t.version, t.exit_code, t.fail_pings = proc, True, None, "", None, 0
        t.spawned_at = time.time()
        t.starts += 1
        t.set_state("starting")
        self.log("… %s を起動しています" % t.spec["name"])

    def start_all(self):
        for t in self.tools:
            self.start(t.id)

    # --- 停止 ---
    def stop(self, tid):
        t = self.by_id[tid]
        with t.lock:
            if t.state == "external":   # 別の画面で起動したものは止めない(その画面で作業中かもしれない)
                return t.snapshot()
            if t.mounted:   # 入口のサーバーの中で動いているので、単独では止めない(入口と一緒に終わる)
                return t.snapshot()
            proc = t.proc
            if proc is None:
                if t.state not in ("crashed", "missing"):
                    t.set_state("stopped")
                return t.snapshot()
            t.set_state("stopping")
            signal_stop(proc)
        try:   # 待つ間は lock を持たない(画面の状態表示を止めないため)
            proc.wait(self.stop_timeout)
        except subprocess.TimeoutExpired:
            self.log("※ %s が %d 秒で終わらないので強制終了します" % (t.spec["name"], self.stop_timeout))
            tools.kill_quiet(proc)
            try:
                proc.wait(5)
            except subprocess.TimeoutExpired:
                pass
        with t.lock:
            if t.proc is proc:
                self._finish(t, proc.returncode, "stopped", "")
                self.log("■ %s を止めました" % t.spec["name"])
            return t.snapshot()

    def restart(self, tid):
        self.stop(tid)
        return self.start(tid)

    def stop_all(self):
        ths = [threading.Thread(target=self.stop, args=(t.id,), daemon=True) for t in self.tools if t.proc is not None]
        for th in ths:
            th.start()
        for th in ths:
            th.join(self.stop_timeout + 7)

    def _finish(self, t, code, state, message):
        t.proc, t.exit_code = None, code
        t.set_state(state, message)
        self._cleanup_runtime(t)
        t.port = None

    def _cleanup_runtime(self, t):
        """強制終了などで子が消せなかった .runtime/<ID>.json を消す。今回起動した子が書いたもの(起動より後の更新時刻)で、
        そのポートが応答しないときだけ(別の画面で起動したツールの記録は消さない)。"""
        if not t.managed:
            return
        info = read_runtime(self.rdir, t.id)
        if not info or info["mtime"] < t.spawned_at - 2:
            return
        r = ping(info["port"], 0.3)
        if r and r["app"] == t.app:
            return
        fsio.unlink_quiet(os.path.join(self.rdir, t.id + ".json"))

    # --- 監視 ---
    def _tick(self, t):
        with t.lock:
            if t.mounted:   # 入口のサーバーの中で動いている(見張る子プロセスは無い)
                return
            now = time.time()
            if t.proc is not None:
                code = t.proc.poll()
                if code is not None:
                    return self._on_exit(t, code)
            if t.state == "starting":
                info = read_runtime(self.rdir, t.id)
                if info and info["mtime"] >= t.spawned_at - 2:   # 前回の古い記録は使わない
                    r = ping(info["port"])
                    if r and r["app"] == t.app:
                        t.port, t.version = info["port"], r["version"]
                        t.set_state("running")
                        t.last_ping = now
                        self.log("○ %s: http://localhost:%d/ (v%s)" % (t.spec["name"], t.port, t.version))
                        return
                if now - t.spawned_at > self.ready_timeout and not t.message:
                    t.message = "起動に時間がかかっています。下のログを確認してください"
            elif t.state in ("running", "external") and now - t.last_ping >= 3:
                t.last_ping = now
                if port_open(t.port):   # 誰のサーバーかは起動・検出のときに /api/ping で確かめ済み
                    t.fail_pings = 0
                    if t.state == "running" and t.message.startswith("応答"):
                        t.message = ""
                    return
                t.fail_pings += 1
                if t.state == "external" and t.fail_pings >= 2:
                    t.port = None
                    t.set_state("stopped", "別の画面で動いていたサーバーが終了しました")
                    self.log("■ %s: 別の画面のサーバーが終了しました" % t.spec["name"])
                elif t.state == "running" and t.fail_pings >= 3 and not t.message:
                    t.message = "応答がありません(重い処理の途中の可能性があります)"

    def _on_exit(self, t, code):
        """子プロセスが終わっていた。止めた最中なら停止、そうでなければ異常終了(または別の画面で起動済みだった)。"""
        if t.state == "stopping":   # 停止の合図で終わった(stop() の待ちより先に監視が気づいた)
            self._finish(t, code, "stopped", "")
            self.log("■ %s を止めました" % t.spec["name"])
            return
        if code == 0:   # 「すでに起動しています」で終わった(起動直前に別の画面で起動された)など
            ext = self._find_external(t, scan=True)
            if ext:
                t.proc, t.exit_code = None, code
                self._mark_external(t, *ext)
                return
            self._finish(t, code, "stopped", "終了しました")
            self.log("■ %s が終了しました" % t.spec["name"])
            return
        self._finish(t, code, "crashed", "異常終了しました(終了コード %s)。下のログを確認して、「起動」で起動し直せます" % code)
        last = tail(t.log_path, 5) or []
        self.log("× %s が異常終了しました(終了コード %s)。ログ: %s" % (t.spec["name"], code, os.path.relpath(t.log_path, self.root))
                 + "".join("\n    " + ln for ln in last))

    def _monitor(self):
        while not self._halt.wait(self.poll):
            for t in self.tools:
                try:
                    self._tick(t)
                except Exception as e:   # 監視は止めない
                    self.log("※ 監視中のエラー(%s): %s" % (t.id, e.__class__.__name__))

    def start_monitor(self):
        self._thread = threading.Thread(target=self._monitor, daemon=True, name="launcher-monitor")
        self._thread.start()

    def close(self):
        self._halt.set()
        if self._thread:
            self._thread.join(2)


# ---------- 入口の画面(HTTP) ----------
SETTINGS_DIR = os.path.join(CODE_DIR, "settings")   # 設定の画面(/settings。設定を 1 つに S5。スキーマ schema.json から UIKit.settingsForm が描く。
# 入口の直下の 1 枚にする = 画面の相対パス api/ytt/… が入口の API を指す(ui-kit の決まり。/settings/ のフォルダにすると /settings/api/… になる)
STATIC = {"/": ("portal.html", CODE_DIR), "/index.html": ("portal.html", CODE_DIR), "/portal.js": ("portal.js", CODE_DIR),
          "/portal.css": ("portal.css", CODE_DIR), "/ui-kit.css": ("ui-kit.css", UI_KIT_DIR), "/ui-kit.js": ("ui-kit.js", UI_KIT_DIR),
          "/settings": ("index.html", SETTINGS_DIR), "/settings.js": ("settings.js", SETTINGS_DIR),
          "/settings.css": ("settings.css", SETTINGS_DIR), "/settings-schema.json": ("schema.json", SETTINGS_DIR)}
STATIC_TYPES = {".html": "text/html; charset=utf-8", ".css": "text/css; charset=utf-8", ".js": "application/javascript; charset=utf-8", ".json": "application/json; charset=utf-8"}
NAV_PAGES = httpsec.PAGES + ("/settings",)   # ほかの画面のリンクで開ける画面(httpsec.navigation_ok)
CSP = ("default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; "
       "object-src 'none'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'")
ACTION_RE = re.compile(r"/api/tools/([a-z0-9]{1,20})/(start|stop|restart)")
# GET: 部品の今の状態をそのまま返す API(場所 → PortalServer の属性。どれも .snapshot())
GET_SNAPSHOTS = {"/api/intake": "intake",       # 友人からの依頼の受付(src/human/friend/intake.py)
                 "/api/backup": "backup",       # 作業データのバックアップの状態と設定(src/manage/keep/backup.py)
                 "/api/accuracy": "accuracy",   # 精度の自動測定の状態(src/eval/drill/accuracy.py)
                 "/api/autorun": "autorun"}     # まとめて実行の状態(src/home/autorun.py)
# POST: 場所 → (PortalHandler のメソッド, 終了の途中なら 409 で断るか)。合言葉・Origin などの検査と本文の読み取りは do_POST が先に済ませる
POST_ROUTES = {"/api/cases/update": ("_post_case", False), "/api/cases/auto": ("_post_case_auto", True),
               "/api/autorun/start": ("_post_autorun", True), "/api/autorun/cancel": ("_post_autorun", True),
               "/api/autorun/start-docs": ("_post_autorun", True), "/api/autorun/start-new": ("_post_autorun", True),
               "/api/autorun/estimate": ("_post_autorun", True),
               "/api/intake/scan": ("_post_intake_scan", True), "/api/backup/run": ("_post_backup_run", True),
               "/api/accuracy/run": ("_post_accuracy_run", True), "/api/window": ("_post_window", False),
               "/api/cleanup": ("_post_cleanup", False), "/api/shutdown": ("_post_shutdown", False)}


def query_int(q, key, default):
    """parse_qs の結果から整数の値(無い・数でなければ default)"""
    try:
        return int((q.get(key) or [str(default)])[0])
    except ValueError:
        return default


# 本文を断った理由(httpsec.BodyError の kind)→ (HTTP の番号, error, 画面の文)。ここに無いもの(read・short・json)は (400, "json", "JSON が読めません")
BODY_ERRORS = {"type": (415, "content_type", "application/json だけを受け付けます"),
               "length": (413, "size", "本文の大きさが正しくありません"), "size": (413, "size", "本文の大きさが正しくありません"),
               "object": (400, "json", "JSON のオブジェクトを送ってください")}
FORBIDDEN = {"error": "forbidden", "message": "この画面からは使えません"}
TOKEN_FAIL = mount_mod.TOKEN_FAIL


def read_json_body(h, limit=MAX_BODY):
    """要求 h の本文(JSON のオブジェクト)。-> (辞書, None) か (None, (HTTP の番号, エラーの JSON))。
    読み方は ytt.httpsec.read_json_body(application/json だけ = 他サイトのフォームはこの形を作れない・断るときは本文を読み捨てる)。
    入口は前から空の本文を {} として読み、NaN も通している(empty_ok・allow_nan)"""
    try:
        return httpsec.read_json_body(h, limit, empty_ok=True, allow_nan=True), None
    except httpsec.BodyError as e:
        code, err, msg = BODY_ERRORS.get(e.kind, (400, "json", "JSON が読めません"))
        return None, (code, {"error": err, "message": msg})


def site_ok(headers, allowed):
    """書き込み系の要求の出どころ: Host(DNS rebinding 対策)・Origin・Sec-Fetch-Site(他サイトからの操作 = CSRF 対策)。規則は ytt.httpsec"""
    return httpsec.host_ok(headers, allowed) and httpsec.origin_ok(headers, allowed) and httpsec.fetch_site_ok(headers)


def guarded_body(h, token, limit):
    """出どころ(site_ok)を確かめたあとの書き込み系の要求: 合言葉 → 本文。-> 本文の辞書か None(断りの応答を送った)。
    断るときは本文を読み捨てる(読まずに閉じると Windows では 403 が届かないことがある。httpsec.drain_body)"""
    if not httpsec.token_ok(h.headers, token, mount_mod.TOKEN_HEADER):
        httpsec.drain_body(h.headers, h.rfile)
        h._json(403, TOKEN_FAIL)
        return None
    body, err = read_json_body(h, limit)
    if err:
        h._json(*err)
    return body


class PortalHandler(BaseHTTPRequestHandler):
    server_version = "ytt-launcher"
    timeout = 30

    def log_message(self, fmt, *args):   # アクセスのたびに黒い画面へ出さない(状態の変化だけを出す)
        pass

    def _host_ok(self):          # DNS rebinding 対策
        return httpsec.host_ok(self.headers, self.server.allowed_hosts)

    def _site_ok(self):
        return httpsec.fetch_site_ok(self.headers)

    def _navigation_ok(self, path):
        """他のツールの画面のリンクで入口を開くのは許す(画面を開くだけで、URL で処理は始まらない)。API は同じ画面からだけ"""
        return httpsec.navigation_ok(self.headers, path, NAV_PAGES)

    def _send(self, code, body=b"", ctype="text/plain; charset=utf-8", extra=None):
        httpsec.send(self, code, body, ctype, extra)   # 見出し(no-store・nosniff)は ytt の 1 か所(取り込んだツールと同じ)

    def _json(self, code, obj):
        self._send(code, json.dumps(obj, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8")

    def _fail(self, code, err, message):
        self._json(code, {"error": err, "message": message})

    def do_GET(self):
        u = urllib.parse.urlsplit(self.path)
        if not (self._host_ok() and (self._site_ok() or self._navigation_ok(u.path))):
            return self._send(403, b"forbidden")
        if (u.path == "/live" or u.path.startswith("/live/")) and self.server.live.handle_get(self, u):   # リアルタイム切り抜き(オフなら下の 404 のまま)
            return
        if (u.path == "/analytics" or u.path.startswith("/analytics/")) and self.server.analytics and self.server.analytics.handle_get(self, u):
            return
        if u.path == "/cases.html":   # 案件の一覧はホーム(/)にまとめた(段階5)。以前のリンク・ブックマークはホームの案件の一覧へ
            return self._send(302, b"", "text/plain; charset=utf-8", {"Location": "/#cases"})
        if u.path in ("/settings/", "/settings/index.html"):   # 設定の画面は /settings(入口の直下。相対パスが入口の API を指すように)
            return self._send(302, b"", "text/plain; charset=utf-8", {"Location": "/settings"})
        if u.path in STATIC:
            name, base = STATIC[u.path]
            try:
                with open(os.path.join(base, name), "rb") as f:
                    body = f.read()
            except OSError:
                return self._send(404, b"not found")
            page = name.endswith(".html")
            if page:   # 書き込み系の API の合言葉(CSRF トークン)を画面に渡す。取り込んだツールと同じ合言葉
                body = mount_mod.inject_token(body, self.server.token)
            return self._send(200, body, STATIC_TYPES[os.path.splitext(name)[1]],
                              {"Content-Security-Policy": CSP, "X-Frame-Options": "DENY", "Referrer-Policy": "no-referrer"} if page else None)
        sup, q = self.server.sup, urllib.parse.parse_qs(u.query)
        if u.path == "/api/ping":
            return self._json(200, {"app": APP_ID, "version": VERSION})
        if u.path == "/api/status":
            st = sup.status()
            st["window"] = self.server.window.status()   # 画面を窓で開くか(段階7-3)
            return self._json(200, st)
        if u.path == "/api/health":   # 「調子」(段9 9-1。重い物は別のスレッドで数え、10 分は前の値。?refresh=1 で数え直す)
            return self._json(200, self.server.health.snapshot(refresh=(q.get("refresh") or ["0"])[0] == "1"))
        if u.path == "/api/cleanup":   # 片付けの候補(段9 9-2。候補の一覧は入口が持ち、POST は候補に出した物だけ)
            return self._json(200, self.server.cleanup_candidates())
        if u.path == "/api/log":
            tid = (q.get("tool") or [""])[0]
            if tid == "client":   # 画面のエラーの記録(段階7-0。1行 = 1件の JSON)
                path = self.server.client_log.path
            elif tid in sup.by_id:   # 決まったIDだけ。パスは受け取らない
                path = sup.by_id[tid].log_path
            else:
                return self._fail(404, "unknown_tool", "そのツールはありません")
            lines = tail(path, min(1000, max(1, query_int(q, "lines", 200))))
            return self._json(200, {"tool": tid, "exists": lines is not None, "lines": lines or [], "log": path})
        if u.path in GET_SNAPSHOTS:
            return self._json(200, getattr(self.server, GET_SNAPSHOTS[u.path]).snapshot())
        if u.path == "/api/autorun/history":   # 終わった実行の記録(段2 B-6。ホームの「まとめて実行の記録」を開いたときだけ読む)
            return self._json(200, self.server.autorun.history(query_int(q, "limit", autorun_mod.HISTORY_DEFAULT), query_int(q, "offset", 0)))
        if u.path == "/api/cases":   # 案件の一覧(各ツールのデータを読んで組み立て直す。src/manage/cases/cases.py)
            try:
                return self._json(200, cases_mod.snapshot(sup.root))
            except Exception as e:   # 読めないデータがあっても入口は落とさない
                return self._fail(500, "cases", "案件の一覧を作れませんでした: %s" % e.__class__.__name__)
        return self._fail(404, "not_found", "その操作はありません")

    def do_POST(self):
        u = urllib.parse.urlsplit(self.path)
        if not site_ok(self.headers, self.server.allowed_hosts):
            httpsec.drain_body(self.headers, self.rfile)
            return self._send(403, b"forbidden")
        if u.path.startswith(YTT_API):   # 画面の共通の API(取り込んだツールの画面からも同じ所へ来る。合言葉・本文の検査も ytt_request で)
            return self.server.ytt_request(self, "portal", VERSION)
        body = guarded_body(self, self.server.token, MAX_BODY)   # 合言葉 → 本文(断ったら応答は送ってある)
        if body is None:
            return
        if u.path.startswith("/live/") and self.server.live.enabled():   # リアルタイム切り抜き: 録画元へ中継(オフなら下の 404 のまま)
            return self.server.live.handle_post(self, u, body)
        if u.path.startswith("/analytics/") and self.server.analytics:   # 分析と日報(src/analytics/service.py)
            return self.server.analytics.handle_post(self, u, body)
        m = ACTION_RE.fullmatch(u.path)
        if m:
            tid, action = m.groups()
            if tid not in self.server.sup.by_id:
                return self._fail(404, "unknown_tool", "そのツールはありません")
            if self.server.closing.is_set():
                return self._fail(409, "closing", "終了の途中です")
            return self._json(200, {"tool": getattr(self.server.sup, action)(tid)})
        route = POST_ROUTES.get(u.path)
        if route is None:
            return self._fail(404, "not_found", "その操作はありません")
        if route[1] and self.server.closing.is_set():
            return self._fail(409, "closing", "終了の途中です")
        return getattr(self, route[0])(u.path, body)

    def _post_case(self, path, body):
        """案件の状態・メモ(案件ファイルに書く。各ツールのデータは触らない)"""
        try:
            return self._json(200, cases_mod.update(self.server.sup.root, body.get("id"), body.get("status"), body.get("memo")))
        except ValueError as e:
            return self._fail(400, "bad_request", str(e))
        except OSError as e:
            return self._fail(500, "write", "案件ファイルを書けませんでした: %s" % tools.why(e))

    def _post_case_auto(self, path, body):
        """自動でできた切り抜きの確認(線 D の M9・M12): 見た・採用 = 友人へ届ける・要らない。中身は src/manage/cases/cases.py の auto_review"""
        s = self.server
        return self._json(*cases_mod.auto_review(s.sup.root, body, deliveries=s.deliveries, studio=s.live.studio_call,
                                                 feedback=lambda row: s.live.exporter.feedback(row), trash=s.cleanup,
                                                 hide=lambda tid: s.prefs.hide("transcripts", [tid], True)))

    def _post_autorun(self, path, body):
        """まとめて実行(配信1本ぶん・選んだ文書を順に自動で)。/api/autorun/<start|cancel|start-docs|start-new|estimate>"""
        op, overwrite = path.rsplit("/", 1)[1], body.get("overwrite") is True
        try:
            ar = self.server.autorun
            if op == "estimate":   # 見積もり(書き込まない。段4): {ids, overwrite} か {id, mode, marks, top, overwrite}
                if isinstance(body.get("ids"), list):
                    return self._json(200, ar.estimate(doc_ids=body["ids"], overwrite=overwrite))
                return self._json(200, ar.estimate(body.get("id"), body.get("mode"), body.get("marks"), body.get("top"), overwrite=overwrite))
            if op == "start-new":   # ① 探す で選んだ配信(git の履歴(679ff01 以前)の docs/archive/followup-2026-09-27.md の 5)
                return self._json(200, ar.start_new(body.get("items"), body.get("top"), body.get("streamer")))
            if op == "start-docs":
                return self._json(200, ar.start_docs(body.get("ids"), overwrite, body.get("streamer")))
            if op == "start":
                return self._json(200, {"run": ar.start(body.get("id"), body.get("mode"), body.get("top"), body.get("streamer"), body.get("marks"),
                                                        overwrite=overwrite)})
            return self._json(200, {"run": ar.cancel(body.get("runId"))})
        except ValueError as e:
            return self._fail(400, "bad_request", str(e))

    def _post_intake_scan(self, path, body):
        """今すぐフォルダを見る(時間がかかることがあるので裏で。応答は今の状態)"""
        self.server.intake.wake.set()
        return self._json(200, self.server.intake.snapshot())

    def _post_backup_run(self, path, body):
        """今すぐ写す(裏で。応答は今の状態)"""
        self.server.backup.run_now()
        return self._json(200, self.server.backup.snapshot())

    def _post_accuracy_run(self, path, body):
        """今すぐ測る(裏で。手が空くまで待つ。応答は今の状態)"""
        if not self.server.accuracy.run_now():
            return self._fail(409, "off", "精度の自動測定がオフです")
        return self._json(200, self.server.accuracy.snapshot())

    def _post_window(self, path, body):
        """画面を窓で開くか(次に起動したときから。段階7-3)"""
        try:
            self.server.window.set_mode(body.get("mode"))
        except ValueError as e:
            return self._fail(400, "bad_request", str(e))
        except OSError as e:
            return self._fail(500, "write", "設定を書けませんでした: %s" % tools.why(e))
        return self._json(200, {"window": self.server.window.status()})

    def _post_cleanup(self, path, body):
        """候補に出した物を ごみ箱フォルダ へ移す(すぐには消さない。cleanup.TRASH_DAYS で起動時に消える)"""
        ids = body.get("ids")
        if not isinstance(ids, list) or not ids or len(ids) > cleanup_mod.MAX_ITEMS * 5:
            return self._fail(400, "bad_request", "移す物を選んでください")
        with self.server.cleanup_lock:
            return self._json(200, self.server.cleanup.move(ids))

    def _post_shutdown(self, path, body):
        """すべて終了(応答を返してから後始末)"""
        out = {"ok": True}
        try:   # 録画中なら録画の部品は止めずに残す(src/home/live.py の stop_recorder)。画面の「すべて終了しました」に知らせる
            if self.server.live.local_recording() is True:
                out.update(recorderKept=True, notice=live_mod.KEPT_NOTE)
        except Exception:
            pass
        self._json(200, out)
        threading.Thread(target=self.server.request_shutdown, daemon=True).start()


def _color_entry(e):
    return {k: e[k] for k in ("name", "en", "hex", "group", "mine")}


def streamer_colors(body):
    """api/ytt/streamer-colors の中身: {q, all?} → 入れた名前に合う人・候補(all なら全員も)/ {names: [...]} → 名前ごとに合う人
    (話者の名前をまとめて。画面が行ごとに通信しないように。気が利く画面へ 段2)。規則は src/ytt/colors.py"""
    entries = colors_mod.load()
    if isinstance(body.get("names"), list):
        names = list(dict.fromkeys(n.strip()[:colors_mod.NAME_MAX] for n in body["names"][:60] if isinstance(n, str) and n.strip()))
        matches = {n: colors_mod.lookup(n, entries)["match"] for n in names}
        return {"ok": True, "matches": {n: _color_entry(m) if m else None for n, m in matches.items()}}
    q = body.get("q") if isinstance(body.get("q"), str) else ""
    r = colors_mod.lookup(q[:colors_mod.NAME_MAX], entries)
    return {"ok": True, "match": _color_entry(r["match"]) if r["match"] else None, "candidates": [_color_entry(e) for e in r["candidates"]],
            "items": [_color_entry(e) for e in entries] if body.get("all") is True else []}


def hide_tokens(live_cfg):
    """設定の節 live を画面へ返す形に: 録画元の合言葉は渡さない(あるかどうかだけ)"""
    return dict(live_cfg, recorders=[dict(r, token="", hasToken=bool(r.get("token"))) for r in live_cfg.get("recorders") or []])


def peek_path(sock, timeout=10.0):
    """接続の最初の行(GET /studio/... HTTP/1.1)を、読み取らずに覗いてパスを返す(無い・壊れていれば None)。
    どのツールの Handler に渡すかを、要求を読み始める前に決めるため。つないですぐ切る接続(入口の動作確認)は None。"""
    end = time.monotonic() + timeout
    data = b""
    try:
        sock.settimeout(timeout)
        while True:
            data = sock.recv(8192, socket.MSG_PEEK)
            if not data or b"\r\n" in data or len(data) >= 8192 or time.monotonic() > end:
                break
            time.sleep(0.01)   # 続きがまだ届いていない(覗くだけなので同じ内容がすぐ返る)
    except OSError:
        return None
    line = data.split(b"\r\n", 1)[0].decode("latin-1", "replace")
    parts = line.split(" ")
    return parts[1] if len(parts) >= 3 else None


class PortalServer(httpsec.ExclusiveServer):
    """入口のサーバー。取り込んだツール(mounts: {"/studio": Handler})の要求は、そのツールの Handler に渡す。
    Windows では SO_REUSEADDR だと使用中のポートにも bind できてしまうので、代わりに SO_EXCLUSIVEADDRUSE で独占する(httpsec.ExclusiveServer。各ツールと同じ)。"""

    def __init__(self, addr, sup):
        super().__init__(addr, PortalHandler)
        self.sup = sup
        p = self.server_address[1]
        self.allowed_hosts = httpsec.allowed_hosts(p)
        self.closing = threading.Event()
        self.token = secrets.token_urlsafe(24)   # 書き込み系の API の合言葉(CSRF トークン)。起動ごとに変わる
        self.mounts = {}
        self._autorun = None
        self._autorun_lock = threading.Lock()
        self._torn_down = False
        self._teardown_lock = threading.Lock()
        app_dir = os.path.dirname(sup.logs_dir)   # 入口の作業データ(settings.json・prefs.json・依頼の受付などの記録)
        self.client_log = clientlog_mod.ClientLog(sup.logs_dir)   # 画面のエラーの記録(段階7-0)
        self.window = appwindow_mod.Opener(app_dir, fsio.atomic_write, log=sup.log)   # 窓で開く(段階7-3)
        self.prefs = prefs_mod.Prefs(os.path.join(app_dir, "prefs.json"), fsio.atomic_write)   # ホームの設定(気が利く画面へ 段1)
        # 友人からの依頼の受付(見張りは main で start。テストで作る入口では動かさない)
        self.intake = intake_mod.Intake(self.prefs, lambda: self.autorun, app_dir, log=sup.log,
                                        feedback=lambda fb: friend_feedback_mod.apply(sup.logs_dir, fb, trash=self.cleanup, log=sup.log,
                                                                                      discard=cases_mod.discard_clip),   # 片付ける部品は入口が渡す(friend_feedback は cases を読まない)
                                        live_begin=lambda url, ctx: self.live.begin_request(url, ctx),   # ライブ配信の依頼(2-15。live は下で作る)
                                        defaults=prefs_mod.DEFAULTS["intake"])   # 設定が読めないときの既定は入口が渡す(intake は prefs を読まない)
        # 作業データのバックアップ(見張りは main で start。inplace = テストなどでは写さない)
        self.backup = backup_mod.Backup(self.prefs, datadir.data_root(), app_dir, log=sup.log, defaults=prefs_mod.DEFAULTS["backup"])
        # 精度の自動測定(見張りは main で start。テストで作る入口では動かさない)。手が空いた判定は _accuracy_busy・_accuracy_last_edit
        self.accuracy = accuracy_mod.Accuracy(self.prefs, app_dir, sup.root, busy=self._accuracy_busy,
                                              last_edit=self._accuracy_last_edit, log=sup.log, defaults=prefs_mod.DEFAULTS["accuracy"])
        self.deliveries = deliver_mod.Deliveries(lambda: (self.prefs.get(["intake"])["intake"] or {}).get("folder") or "",
                                                 txindex.is_pack_dir, log=sup.log)   # 「編集」の ③ パックの「友人へ届ける」(api/ytt/deliver)
        # リアルタイム切り抜き(線 D。既定はオフ。見回り = 録画の部品を起こすのは main で start。テストで作る入口では動かさない)
        self.live = live_mod.Live(self.prefs, sup.root, sup.logs_dir, log=sup.log, server=self)   # server: P4 の作り直しがスタジオの API を呼ぶ
        self.live.unconfirmed = lambda: cases_mod.snapshot(sup.root)["auto"]["unconfirmed"]   # 自動の切り抜きの未確認の数(D-13: 20 本で自動の採用を休む)
        self.health = health_mod.Health(sup, sup.logs_dir, sup.root, worker_probe=self._worker_probe, extra_dirs=self._extra_dirs,
                                        live_probe=self.live.health, accuracy_probe=self.accuracy.snapshot)   # 「調子」(段9 9-1。録画の行はオンのときだけ・精度の行)
        # 片付け(段9 9-2)。ごみ箱フォルダは動画と同じドライブ(書き出し先\ごみ箱。2026-10-01 ユーザー決定)
        self.cleanup = cleanup_mod.Cleanup(app_dir, repo_root=sup.root, log=sup.log, out_dirs=self._extra_dirs)
        self.cleanup_lock = threading.Lock()
        # 分析と日報(見張りは main で start。テストで作る入口では動かさない。連携の設定が無ければ何もしない)
        self.analytics = analytics_mod.Service(log=sup.log, token=self.token) if analytics_mod else None

    def _accuracy_busy(self):
        """精度の自動測定の「手が空いているか」。空いていなければ理由の文、空いていれば None。
        入口の重い処理の順番(SLOTS)・まとめて実行・「編集」のジョブ(入口から loopback で /api/jobs を読む。編集が動いていなければ動いているジョブも無い)"""
        hv = jobs.SLOTS.snapshot()
        if hv.get("active") or hv.get("waiting"):
            return "重い処理"
        if self._autorun is not None and any(r.get("state") in ("queued", "running") for r in self._autorun.snapshot().get("runs") or []):
            return "まとめて実行"
        try:
            st, obj = autorun_mod.ToolClient(self.tool_endpoint, self.token, timeout=5).call("transcribe", "GET", "/api/jobs")
        except autorun_mod.StepError:
            return None
        if st == 200 and any(j.get("state") in ("queued", "loading", "extracting", "running") for j in obj.get("jobs") or [] if isinstance(j, dict)):
            return "文字起こしのジョブ"
        return None

    def _accuracy_last_edit(self):
        """文字起こしの文書(transcripts の直下のファイル)の最後の更新(エポック秒。無ければ None)"""
        d = cases_mod.locations(self.sup.root)["transcripts"]
        newest = None
        try:
            with os.scandir(d) as it:
                for e in it:
                    try:
                        if e.is_file():
                            m = e.stat().st_mtime
                            if newest is None or m > newest:
                                newest = m
                    except OSError:
                        continue
        except OSError:
            return None
        return newest

    def cleanup_candidates(self):
        """片付けの候補(案件 = スタジオと文字起こしの紐づけ・依頼の受付のフォルダから)"""
        try:
            cases = cases_mod.snapshot(self.sup.root).get("cases") or []
        except Exception as e:   # 案件を読めなくても、キャッシュ・ログの候補は出す
            self.sup.log("片付け: 案件を読めませんでした: %r" % (e,))
            cases = []
        try:
            folder = (self.intake._cfg() or {}).get("folder") or None
        except Exception:
            folder = None
        with self.cleanup_lock:
            return self.cleanup.candidates(cases, intake_dir=folder)

    def restart_self(self):
        """新しい入口(同じポートが空くのを待つ)を起こしてから、この入口は「すべて終了」と同じ後始末をして終わる。
        重い処理・取り込んだツールの処理(人が始めたもの・まとめて実行の書き出し)が動いていれば 409 で断る(理由の文)。
        まとめて実行の待ち・実行中は断らない(M5 で起動し直したあとに続きから進む。入口 0.41.0): 応答の notice と記録で何件続くかを知らせる。
        -> (HTTP の番号, JSON)"""
        if self.closing.is_set():
            return 409, {"ok": False, "error": "closing", "message": "終了の途中です"}
        ar = self._autorun
        info = ar.restart_info() if ar is not None else {}
        busy = [(t.id, t.spec["name"]) for t in self.sup.tools if t.mounted and t.mount and t.mount.busy()]
        why = restart_mod.can_restart(self.sup.status(), busy, info.get("redo"))
        if why:
            return 409, {"ok": False, "error": "busy", "message": why}
        notice = restart_mod.RESUME_NOTICE % info["runs"] if info.get("runs") else ""
        only = [t.id for t in self.sup.tools] if len(self.sup.tools) < len(TOOLS) else ()
        try:
            restart_mod.spawn_new_launcher(self.sup.root, args=restart_mod.restart_args(self.server_address[1], only, not self.sup.mounts),
                                           log=self.sup.log)
        except OSError as e:
            return 500, {"ok": False, "error": "spawn", "message": "ホームを起動し直せませんでした(新しいホームを起動できません): %s" % tools.why(e)}
        self.sup.log("画面から「起動し直す」が押されました" + ("(%s)" % notice if notice else ""))
        threading.Timer(0.3, self.request_shutdown).start()   # 応答を返してから後始末(新しい入口はポートが空くのを待っている)
        return 200, dict({"ok": True}, **({"notice": notice} if notice else {}))

    def purge_trash(self):
        """起動時: 日数(cleanup.TRASH_DAYS)を過ぎたごみ箱フォルダの日付を消す(裏で)"""
        try:
            n = self.cleanup.purge()
            if n:
                self.sup.log("ごみ箱フォルダから %d 日ぶんを消しました(%d 日を過ぎた)" % (n, self.cleanup.trash_days))
        except Exception as e:
            self.sup.log("ごみ箱フォルダを片付けられませんでした: %r" % (e,))

    def _worker_probe(self):
        """「編集」の /api/ping の worker(認識ワーカーの状態)。動いていなければ None"""
        try:
            st, d = autorun_mod.ToolClient(self.tool_endpoint, self.token, timeout=1.5).call("transcribe", "GET", "/api/ping")
        except (autorun_mod.StepError, http.client.HTTPException):
            return None
        w = d.get("worker") if st == 200 else None
        return w if isinstance(w, dict) else None

    def _extra_dirs(self):
        """空き容量を見る追加の場所・ごみ箱フォルダを置く書き出し先: スタジオの書き出し先(datadir.studio_out_dir。outDir が無ければ作業データの exports)。
        スタジオの settings.json がまだ無いとき(スタジオを一度も保存していない)は [](今までどおり。studio_out_dir は exports を返す)"""
        if not os.path.isfile(os.path.join(datadir.resolve("studio", self.sup.root), "settings.json")):
            return []
        return [datadir.studio_out_dir(self.sup.root)]

    def tool_ports(self):
        """別のプログラムとして動いているツールのポート(窓で開いてよい先。取り込んだツールは入口と同じポートなので含めない)"""
        own = self.server_address[1]
        out = []
        for t in self.sup.tools:
            snap = t.snapshot()
            if snap["state"] in ("running", "external") and snap["port"] and snap["port"] != own:
                out.append(snap["port"])
        return out

    def ytt_api(self, sub, body, tool="portal", version=""):
        """画面の共通の API の中身。-> (HTTP の番号, JSON)"""
        try:
            if sub == "client-log":
                return 200, {"ok": True, "kept": self.client_log.record(tool, body, version)}
            if sub == "open-window":
                return 200, {"ok": True, "url": self.window.open_url(body.get("url"), self.server_address[1], self.tool_ports(), tuple(self.mounts))}
            if sub == "open-external":
                return 200, {"ok": True, "url": self.window.open_external(body.get("url"))}
            if sub == "restart-self":   # 版の赤い帯の「起動し直す」(段9 9-3。ui-kit の UIKit.restart)
                return self.restart_self()
            if sub == "focus-portal":   # ツールの窓の「入口」: 入口の窓がほかにあれば前に出す(入口を二つにしない)
                return 200, {"ok": True, "focused": self.window.focus(PORTAL_TITLE)}
            if sub == "streamer-guess":   # 配信者の名前を自動で(覚えた名前 → チャンネル名から。段5)。{docId?, videoId?, channel?}
                return 200, self.streamer_guess(body.get("docId"), body.get("videoId"), body.get("channel"))
            if sub == "deliver":   # 「編集」の ③ パックの「友人へ届ける」。{op: "start", dir, title} → 裏で zip / {op: "status", job}
                if body.get("op") == "status":
                    j = self.deliveries.status(body.get("job"))
                    return (200, {"ok": True, "job": j}) if j else (404, {"error": "not_found", "message": "その仕事はありません(ホームを起動し直しましたか)"})
                return 200, {"ok": True, "job": self.deliveries.start(body.get("dir"), body.get("title"))}
            if sub == "live":   # リアルタイム切り抜き(線 D の P3): 全ツールのヘッダーの録画の札 {op: "status"} / 札の「停止」{op: "stop", recorder, recording}(src/home/live.py)
                return self.live.ytt(body)
            if sub == "prefs":   # ホームの設定(src/home/prefs.py。節ごとに読む・直す。全体を上書きしない)
                return 200, self.prefs_api(body)
            if sub == "streamer-colors":   # 配信者の名前の欄(字幕の色): 候補の一覧と、入れた名前に合う人(規則は src/ytt/colors.py)
                return 200, streamer_colors(body)
        except ValueError as e:
            return 400, {"error": "bad_request", "message": str(e)}
        except appwindow_mod.TooMany as e:
            return 429, {"error": "too_many", "message": str(e)}
        except appwindow_mod.Unavailable as e:
            return 409, {"error": "unavailable", "message": str(e)}
        except OSError as e:
            return 500, {"error": "open", "message": "開けませんでした: %s" % tools.why(e)}
        return 404, {"error": "not_found", "message": "その操作はありません"}

    def streamer_guess(self, doc_id=None, video_id=None, channel=None):
        """-> {"ok", "name", "source", "hex", "channel"}。文書だけ分かれば、その文書の元の配信(.clip.json)・チャンネル(スタジオ)を調べる"""
        doc_id = doc_id if isinstance(doc_id, str) and len(doc_id) <= 64 else None
        video_id = video_id if isinstance(video_id, str) and len(video_id) <= 64 else None
        channel = channel.strip()[:120] if isinstance(channel, str) and channel.strip() else None
        if doc_id and not video_id:
            d = next((x for x in cases_mod.read_transcripts(cases_mod.locations(self.sup.root)["transcripts"]) if x["id"] == doc_id), None)
            src = ((d or {}).get("clip") or {}).get("source") or {}
            video_id = src.get("videoId") if isinstance(src.get("videoId"), str) else None
        if video_id and not channel:
            v = cases_mod.read_studio(cases_mod.locations(self.sup.root)["studio"]).get(video_id) or {}
            channel = str(v.get("channel") or "").strip()[:120] or None
        r = prefs_mod.guess_streamer(self.prefs, doc_id, video_id, channel,
                                     from_channel=lambda ch: (colors_mod.from_channel(ch) or {}).get("name"))
        hit = colors_mod.lookup(r["name"])["match"] if r["name"] else None
        return dict(r, ok=True, hex=hit["hex"] if hit else None, channel=channel)

    def prefs_api(self, body):
        op = body.get("op")
        try:
            if op == "get":
                secs = body.get("sections")
                got = self.prefs.get([x for x in secs if isinstance(x, str)] if isinstance(secs, list) else None)
                if "live" in got:
                    got["live"] = hide_tokens(got["live"])
                return {"ok": True, "prefs": got}
            if op == "patch":
                value = self.prefs.patch(body.get("section"), body.get("value"))
                # 設定を変えたら、その部品がすぐ見直す: 受付(オン・フォルダ)・バックアップ(オンにした・先を変えた → 最初の1回を写す)・
                # 精度の自動測定(オフにした → 待っていた「今すぐ」を取り下げる)
                watcher = {"intake": self.intake, "backup": self.backup, "accuracy": self.accuracy}.get(body.get("section"))
                if watcher is not None:
                    watcher.wake.set()
                if body.get("section") == "live":   # リアルタイム切り抜き: オンにした・置き場所を変えた → 見回りをすぐ(録画の部品を起こす・置き場所を伝える)
                    self.live.on_patch(None, value)
                    value = hide_tokens(value)
                return {"ok": True, "value": value}
            if op == "remember":
                return {"ok": True, "streamer": self.prefs.remember(body.get("kind"), body.get("key"), body.get("name"))}
            if op == "hide":   # 一覧の項目を非表示にする・戻す(UIKit.hide。1件ずつ足す・外す)
                lst = body.get("list")
                return {"ok": True, "list": lst, "hidden": self.prefs.hide(lst, body.get("ids"), body.get("hidden") is not False)}
        except OSError as e:
            raise ValueError("設定を保存できませんでした(%s)" % tools.why(e))
        raise ValueError("その操作はありません: %s" % str(op)[:20])

    def ytt_request(self, h, tool, version=""):
        """画面の共通の API(api/ytt/<名前>)の要求を受け持つ。h は入口か、取り込んだツールの Handler(_json を持つ)。
        取り込んだツールの画面の /studio/api/ytt/… も src/home/mount.py がここへ回す(ツールごとに同じものを書かないため)。
        検査は入口の API と同じ: POST だけ・Host・Origin・Sec-Fetch-Site・合言葉・本文は application/json で 16KB まで。
        断るときは本文を読み捨てる(0.50.0 までは取り込んだ画面から来た要求を Host・Origin で断るときに読まずに閉じていた = Windows で 403 が届かないことがある形)"""
        path = urllib.parse.urlsplit(h.path).path
        if h.command != "POST":
            return h._json(405, {"error": "method", "message": "POST で送ってください"})
        if not site_ok(h.headers, self.allowed_hosts):
            httpsec.drain_body(h.headers, h.rfile)
            return h._json(403, FORBIDDEN)
        body = guarded_body(h, self.token, YTT_BODY_MAX)
        if body is None:
            return None
        code, obj = self.ytt_api(path[len(YTT_API):] if path.startswith(YTT_API) else "", body, tool, version)
        return h._json(code, obj)

    def tool_endpoint(self, tid):
        """まとめて実行(src/home/autorun.py)がツールの API を呼ぶ先 (ポート, 場所)。動いていなければ None"""
        t = self.sup.by_id.get(tid)
        if t is None:
            return None
        snap = t.snapshot()
        if snap["state"] not in ("running", "external") or not snap["port"]:
            return None
        return snap["port"], snap["path"] or "/"

    @property
    def autorun(self):
        with self._autorun_lock:
            if self._autorun is None:
                self._autorun = autorun_mod.AutoRunner(autorun_mod.ToolClient(self.tool_endpoint, self.token), self.sup.root, prefs=self.prefs,
                                                       log_dir=self.sup.logs_dir,   # 終わった実行の記録(画面のエラーの記録と同じ logs。B-6)
                                                       log=self.sup.log)   # 友人の区間の長さを使わなかった理由など(launcher.log に1行)
            return self._autorun

    def handler_for(self, path):
        if path and self.mounts:
            p = urllib.parse.urlsplit(path).path
            for prefix, handler in self.mounts.items():
                if p == prefix or p.startswith(prefix + "/"):
                    return handler
        return PortalHandler

    def finish_request(self, request, client_address):
        # 覗けなかった(何も送らずに切った接続・壊れた要求の行)ときは入口の Handler に任せる(読んで静かに終わる)
        self.handler_for(peek_path(request))(request, client_address, self)

    def close_watchers(self):
        """裏の見張りを止める(すべて終了・入口の終了の両方から。2 回呼んでもよい)"""
        self.intake.close()   # 依頼の受付の見張りを止める(まとめて実行に入れる前に)
        self.backup.close()
        self.accuracy.close()   # 測っている子プロセスも止める
        self.live.close()     # 録画の部品の見回りを止め、録画中でなければ録画の部品も止める(録画中なら残す = 録画は続く。0.38.1)
        if self.analytics:
            self.analytics.close()

    def teardown(self):
        """終了の後始末(1 回だけ。2 回目からは何もしない)。画面の「すべて終了」(request_shutdown)と main の終わり(Ctrl+C・黒い画面の×も)の両方から呼ぶ。
        順番: 裏の見張り → まとめて実行(実行中の段を止める。順番待ち・実行中の実行は次の起動で続く。M5)→ 監視 → ツールを止める → 取り込んだツールの後始末。
        0.50.0 までは「すべて終了」で 2 回走り(取り込んだツールの finish も 2 回)、Ctrl+C・× ではまとめて実行を閉じていなかった"""
        with self._teardown_lock:   # 途中で 2 つ目が来たら(「すべて終了」の後始末の最中の Ctrl+C)、終わるのを待ってから戻る
            if self._torn_down:
                return
            self._torn_down = True
            self.closing.set()
            self.close_watchers()
            if self._autorun is not None:
                self._autorun.close()
            self.sup.close()
            self.sup.stop_all()
            self.sup.unmount_all()

    def request_shutdown(self):
        """画面の「すべて終了」。この入口から起動したツールを止めてから、待ち受けを終える(serve_forever が戻る)。"""
        if self.closing.is_set():
            return
        self.closing.set()
        self.sup.log("画面から「すべて終了」が押されました")
        self.teardown()
        self.shutdown()


def make_server(start_port, sup):
    """start_port から20個のうち空いているポートで待ち受ける。入口がすでに動いていれば (None, そのポート)。
    start_port=0 は OS に空きポートを選ばせる(テスト用)。"""
    if start_port == 0:
        srv = PortalServer(("127.0.0.1", 0), sup)
        return srv, srv.server_address[1]
    for p in range(start_port, start_port + PORT_RANGE):
        r = ping(p)
        if r and r["app"] == APP_ID:
            return None, p
        if r is not None:   # 他のツールが使っている
            continue
        try:
            srv = PortalServer(("127.0.0.1", p), sup)
        except OSError:
            continue
        return srv, p
    raise SystemExit("空いているポートが見つかりません(%d〜%d)" % (start_port, start_port + PORT_RANGE - 1))


# ---------- 起動 ----------
def make_logger(path):
    """黒い画面と <作業データ>/app/logs/launcher.log に1行ずつ出す。
    黒い画面への表示は専用のスレッドに任せる: Windows の黒い画面は、文字を選択している間(簡易編集モード)は表示の書き込みが止まるので、
    監視や画面の API がその待ちに巻き込まれて固まらないように。"""
    lock = threading.Lock()
    q = queue.Queue(maxsize=1000)
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        fsio.rotate(path, LOG_MAX)
    except OSError:
        pass

    def printer():
        while True:
            msg = q.get()
            try:
                print(msg, flush=True)
            except (OSError, ValueError):
                pass
    threading.Thread(target=printer, daemon=True, name="launcher-console").start()

    def log(msg):
        try:
            q.put_nowait(msg)
        except queue.Full:   # 表示が長く止まっている。ファイルには残す
            pass
        with lock:
            try:
                with open(path, "a", encoding="utf-8") as f:
                    f.write("%s %s\n" % (time.strftime("%Y-%m-%d %H:%M:%S"), msg))
            except OSError:
                pass

    def flush(timeout=1.0):
        """終了の直前に、表示待ちの行を出し切る(黒い画面が止まっていれば待たない)"""
        end = time.time() + timeout
        while not q.empty() and time.time() < end:
            time.sleep(0.02)
    log.flush = flush
    return log


STOP_SIGNALS = ("SIGINT", "SIGTERM", "SIGBREAK", "SIGHUP")
_stop_requested = threading.Event()


def _set_stop_handlers(handler):
    for name in STOP_SIGNALS:
        sig = getattr(signal, name, None)
        if sig is not None:
            try:
                signal.signal(sig, handler)
            except (OSError, ValueError, RuntimeError):
                pass


def install_stop_signals():
    """Ctrl+C・黒い画面の×(Windows は SIGBREAK)・SIGTERM・SIGHUP で、子を止めて portal.json を消してから終わる。
    合図は1回だけ受け取る: 2回目(Ctrl+C の連打・×と同時の合図など)で後始末の途中に止まり、子が残るのを防ぐ。
    Windows は×で閉じてから約5秒で強制終了されるが、同じ画面の子にも同じ合図が届くので、子は自分で後始末する。"""
    def stop(_sig, _frame):
        if _stop_requested.is_set():
            return
        _stop_requested.set()
        raise KeyboardInterrupt()
    _set_stop_handlers(stop)


def ignore_stop_signals():
    """後始末の間は、追加の合図で中断されないようにする。"""
    _stop_requested.set()
    _set_stop_handlers(signal.SIG_IGN)


def parse_args(argv):
    ap = argparse.ArgumentParser(prog="launch.py", description="3つのツールをまとめて起動し、入口の画面を開く")
    ap.add_argument("--port", type=int, default=DEFAULT_PORT, help="入口の画面のポート(既定 %d。使用中なら次の番号)" % DEFAULT_PORT)
    ap.add_argument("--no-open", action="store_true", help="ブラウザを開かない")
    ap.add_argument("--only", default="", help="起動するツールを絞る(例: studio,transcribe)")
    ap.add_argument("--wait-port", action="store_true", help="「起動し直す」用: --port が空くまで(最大 30 秒)待ってから待ち受ける")
    ap.add_argument("--open-path", default="/", help="最初に開く画面の場所(例: /transcribe/ = 編集)")
    ap.add_argument("--app-window", action="store_true", help="設定にかかわらず Edge のアプリの窓で開く(無ければいつものブラウザ)")
    ap.add_argument("--no-mount", action="store_true",
                    help="ツールを入口に取り込まず、以前と同じく別のプログラムとして起動する(取り込みで問題が出たときの戻し方)")
    a = ap.parse_args(argv)
    only = [x.strip() for x in a.only.split(",") if x.strip()]
    bad = [x for x in only if x not in TOOL_IDS]
    if bad:
        ap.error("--only に使えるのは %s です(%s は不明)" % (", ".join(TOOL_IDS), ", ".join(bad)))
    a.only = only
    if not re.fullmatch(r"/[A-Za-z0-9._/\-]{0,120}", a.open_path) or ".." in a.open_path or "//" in a.open_path:
        ap.error("--open-path は / で始まる英数字の場所にしてください(例: /transcribe/)")
    return a


def main(argv=None):
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="replace")
        except Exception:
            pass
    opts = parse_args(sys.argv[1:] if argv is None else argv)
    datadir.register("app", app_data_dir(ROOT))   # 同じプロセスの案件など(datadir.resolve)が同じ場所を読む
    log = make_logger(os.path.join(logs_dir_for(ROOT), "launcher.log"))
    sup = Supervisor(ROOT, only=opts.only, log=log, mounts=() if opts.no_mount else tuple(mount_mod.MOUNTS))
    if opts.wait_port and not restart_mod.wait_port_free(opts.port):   # 「起動し直す」で起こされた: 古い入口がポートを離すまで待つ(段9 9-3)
        log("前のホームがポート %d を離しませんでした。次の番号で起動します" % opts.port)
    srv, port = make_server(opts.port, sup)
    url = "http://localhost:%d%s" % (port, opts.open_path)
    if srv is None:
        print("ホームはすでに起動しています。画面を開きます:", url)
        if not opts.no_open:
            op = appwindow_mod.Opener(app_data_dir(ROOT), fsio.atomic_write, log=log)
            if opts.app_window:
                op.force_mode = "app"
            op.open_start(url)
        return 0
    http_thread = None
    try:
        install_stop_signals()
        runtime.write_runtime(sup.rdir, TOOL_ID, port, VERSION)   # 書けなくても続ける(使う人はまだいない)
        log("ホーム v%s: %s (終了は画面の「すべて終了」・Ctrl+C・この黒い画面を閉じる)" % (VERSION, url))
        log("各ツールの出力: %s" % sup.logs_dir)
        sup.attach(srv)
        served = threading.Event()

        def serve():
            try:
                srv.serve_forever()
            finally:
                served.set()
        http_thread = threading.Thread(target=serve, daemon=True, name="portal-http")
        http_thread.start()   # 取り込みの準備中も画面を開けるように、先に待ち受ける
        sup.start_all()
        sup.start_monitor()
        try:   # まとめて実行を起動のときに作る: 前の起動で待ち・実行中だった実行(M5)を、ホームを開かなくても続ける
            srv.autorun
        except Exception as e:   # 作れなくても入口は動かす(画面から使うときにもう一度作る)
            log("まとめて実行を準備できませんでした: %r" % (e,))
        srv.intake.start()   # 友人からの依頼の受付(設定がオフなら何もしない。止まっていた間に届いた依頼もここで流れる)
        srv.backup.start()   # 作業データのバックアップ(設定がオフなら何もしない。起動の少しあとに、時間が来ていれば写す)
        srv.accuracy.start() # 精度の自動測定(設定がオフなら何もしない。夜の窓に手が空いていれば1日1回、src/eval/tools/eval_*.py を子プロセスで)
        srv.live.start()     # リアルタイム切り抜きの見回り(設定がオフなら何もしない。オンなら録画の部品を起こす)
        if srv.analytics:
            srv.analytics.start()   # 分析と日報(連携の設定が無ければ何もしない。新しいデータが来たら日報を作って LINE へ)
        threading.Thread(target=srv.purge_trash, daemon=True, name="trash-purge").start()   # 日数を過ぎたごみ箱フォルダ(段9 9-2)
        if opts.app_window:   # 設定にかかわらず窓で開く(設定には保存しない)
            srv.window.force_mode = "app"
        if not opts.no_open:   # 設定が「窓」なら Edge のアプリモード、それ以外・Edge が無いときはいつものブラウザ(段階7-3)
            threading.Timer(0.8, lambda: log("画面を開きました(%s)" % {"app": "窓", "browser": "ブラウザ"}[srv.window.open_start(url)])).start()
        while not served.wait(0.5):   # 待ち受けは別のスレッド。ここは Ctrl+C などの合図を受け取るために待つ
            pass
    except KeyboardInterrupt:
        ignore_stop_signals()
        log("終了の合図を受け取りました。このホームから起動したツールを止めています…")
    finally:
        ignore_stop_signals()
        srv.teardown()   # 「すべて終了」で済んでいれば何もしない
        if http_thread is not None and http_thread.is_alive():
            srv.shutdown()
        runtime.remove_runtime(sup.rdir, TOOL_ID, port)   # 自分が書いた記録のときだけ消す(別の入口が書き直したものは残す)
        srv.server_close()
        log("ホームを終了しました")
        log.flush()
    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
