#!/usr/bin/env python3
"""文字起こしツール用のローカルサーバー(標準ライブラリ + faster-whisper)。

    python3 serve.py [開始ポート] [--no-open]

  GET  /                     index.html
  GET  /app.js, /ui-kit.js, /cut.js, /pack-tab.js   画面の JS(CSP script-src 'self' のため外部ファイルで配信)
  GET  /api/ping             起動確認
  GET  /api/tools            ffmpeg / faster-whisper / GPU の有無
  GET  /api/settings, PUT    用語集・置換辞書・前回の設定
  GET  /api/marker           隣の clip-marker/data.json のポイント一覧(あれば)
  POST /api/transcribe       文字起こしジョブを追加(順番に1つずつ処理)
  GET  /api/jobs             ジョブの一覧と進捗 / POST /api/transcribe/cancel で中止
  POST /api/diarize          話者の自動判別ジョブを追加(sherpa-onnx。文字起こしと同じ待機列。recognize: 覚えている声で名前を付ける。既定オン)。
                             numSpeakers 1 = 判別せず全部の行をその1人に / names = 出てくる人の名前(照らし合わせをこの名前だけに・1人だけ残れば消去法で付ける。友人からの依頼)
  GET  /api/voices           覚えている声の一覧(A-3。判別モデルごと。特徴そのものは返さない。generic = 一般的な名前)
  GET  /api/voices/preview   ?tid=&embedding= 覚える前の確認(読むだけ。覚える人・行・秒・既にある名前・断った名前・使わなかった行の数。段1)
  POST /api/voices/learn     {tid, embedding, names, confirmSame} 名前を付けた話者の声を覚えるジョブを追加(A-3。作業データの voices/ に保存。
                             校正済みの行だけ・評価用は断る・一般的な名前は覚えない・既にある名前は confirmSame に入れたときだけ足す。段1)
  POST /api/voices/delete    覚えている声を消す {embedding, name}
  POST /api/retranscribe     選んだ行だけを、別のモデルで再認識するジョブを追加
  POST /api/redo             {"tid", "redoLarge"?} 疑わしい所(「長い区間に文字が少ない」の行)だけ認識し直すジョブ(12 ③-2。良くなったときだけ置き換える)
  POST /api/resplit          {"id", "orientation"?, "splitChars"?, "baseUpdatedAt"?} 今の文書の長い行を、保存してある単語の時刻(transcripts/<id>.words.json)で分け直す(12 ②)
  GET  /api/learned          修正から学習した「誤=>正」の候補
  GET  /api/suggest?id=      この文字起こしの各行への「修正の提案」(文脈つきの統計)
  POST /api/suggest/feedback 提案の採用・却下を記録
  POST /api/export-corrections  修正データ(音声の範囲+直した文章)をzipで書き出す(scope=proofed で校正済みの行すべて)
  GET  /api/metrics?id=&legacy=1  校正済みの行を正解とした文字誤り率(CER)。id 省略で全件
  POST /api/abtest           校正済みの行の音声を複数の設定で認識し直し、正解との差を比べるジョブ(文字起こしは書き換えない)
  GET  /api/evals?id=        比較の結果の一覧(id=文字起こし。省略で全件) / GET /api/eval?id= で1件
  GET  /api/transcripts      保存済みの文字起こし一覧
  GET/PUT/DELETE /api/transcript?id=   1件の取得・保存・削除
  GET  /media?id=            文字起こしの元ファイルを再生用に配信(Range対応)
  「編集」(docs/design/edit-tool-design.md の 5):
  GET/PUT /api/edit?id=      編集の内容(残す区間)。PUT {"edit", "baseRev"} → {"rev", "cutRows"}(rev が違えば 409。行の cutState も合わせる)
  GET  /api/edit/draft?id=&rows=1  動画の fps・長さと、たたき台「行から」(pack.TRANSCRIPT_ROWS。残す行が無ければ全部)・隣の .cut-plan.json。
                             「行から」はカットが無い文書か rows=1 のときだけ計算する(設定の rowEdge = 行の端を声の止まる所まで広げるか)
  POST /api/edit/pack        {"id", "rev", "docUpdatedAt", "dir", "files", "output"?} パックを作り終えた記録(packRev)。output = 作ったときの出力の設定(壊れていれば保存しない)
  POST /api/edit/preview     {"id", "keeps"} カットのとおりに作ったときのパックの見積もり(ファイルは作らない)
  GET  /api/edit/pack-readme?id=  前回のパックの手順書(友人へ.txt)
  POST /api/open-video       {"path", "title"?} 文字起こしせずに開く → {"id", "created"}(同じ動画の文書があればそれ)
  GET  /api/doc-for?path=    その動画の文書 → {"doc": {"id", "rows"} | null}(?media= で開いたとき。パスを比べるだけ)
  GET  /api/peaks?id=        音の波形(0〜255 の1バイトの並び。X-Peaks-Rate・X-Peaks-Duration)。作っている間は 202
  受け渡し(docs/spec/pipeline.md。本体は pipeline_io.py):
  GET  /api/clip-info?path=  動画(または .clip.json)の隣の youtube-tools-clip/v1 → {"clip", "clipPath", "mediaPath", "warning"}
  GET  /api/transcript-v1?id= youtube-tools-transcript/v1 の JSON
  POST /api/export-file      {"id", "format": transcript-v1|srt|cut-plan-v1} 動画の隣に保存 → {"path", "name", "overwritten", "format", "count"}
  GET  /api/siblings         実行中の他のツールのポート {"tools": {"transcribe": 8775, ...}}

127.0.0.1 にのみバインドし、Host / Origin / Sec-Fetch-Site を検査する(画面 / への遷移だけは、他のツールのリンクから開けるよう別扱い)。
"""
import array
import bisect
import difflib
import faulthandler
import gc
import hashlib
import itertools
import json
import logging
import logging.handlers
import math
import os
import queue
import re
import shutil
import socket
import subprocess
import sys
import tarfile
import threading
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
import uuid
import wave
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))   # 別のフォルダから起動しても、隣の部品(pipeline_io.py・resolve_export.py)を読めるように


def _load_core():
    """共通部品 ytt_core(リポジトリ直下。統合計画の段階2)を読み込めるようにする。
    探す場所: 環境変数 YTT_CORE_DIR(一時フォルダに写して動かすテスト用)→ このフォルダの1つ上。sys.path の末尾に足す(隣の部品を隠さないため)。"""
    here = os.path.dirname(os.path.abspath(__file__))
    for d in (os.environ.get("YTT_CORE_DIR"), os.path.dirname(here)):
        if d and os.path.isfile(os.path.join(d, "ytt_core", "__init__.py")):
            if d not in sys.path:
                sys.path.append(d)
            return
    raise SystemExit("共通部品 ytt_core が見つかりません(%s の隣に ytt_core フォルダが必要です)。"
                     "リポジトリのフォルダの中身をまとめて置き直してください" % here)


_load_core()
from ytt_core import datadir as _datadir, fsio as _fsio, httpsec, layout as _layout, jobs as _heavy, runtime as _runtime, schemas as _yschemas, tools as _tools  # noqa: E402
import roster as _roster  # noqa: E402  (名簿の呼び名・配信ごとの文脈。隣の部品)


APP_ID = "transcribe-tool"
SERVER_VERSION = "0.31.0"  # app.js 側の APP_VERSION と揃える
ROOT = os.path.dirname(os.path.abspath(__file__))
INDEX = os.path.join(ROOT, "index.html")
APP_JS = os.path.join(ROOT, "app.js")      # 画面の JS(CSP で index.html からインラインの <script> を外したため、静的配信する)
UI_KIT_JS = os.path.join(ROOT, "ui-kit.js")  # ui-kit/ui-kit.js の写し(dev/sync_ui_kit.py。同上)
PAGE_JS = ("cut.js", "pack-tab.js")          # 「編集」のタブの JS(docs/design/edit-tool-design.md の 7。app.js より先に読む。無いものは 404)
# 作業データの置き場所(段階4)。起動時に prepare() が ytt_core.datadir で決めて set_data_dir() で切り替え、
# 認識ワーカーにも環境変数 TRANSCRIBE_DATA_DIR で渡す(ワーカーは import した時点でそれを使う)。import した直後はこのフォルダ(テスト用)
DATA_DIR = os.environ.get("TRANSCRIBE_DATA_DIR") or ROOT
TX_DIR = os.path.join(DATA_DIR, "transcripts")
ROSTER = os.path.join(ROOT, "hololive-roster.json")   # ホロライブの名簿(用語集に足すための一覧)
DATASET_DIR = os.path.join(DATA_DIR, "dataset")   # 校正の成果と音声の保管(将来の学習・声紋登録用)
EVAL_DIR = os.path.join(DATA_DIR, "evals")   # 設定の比較(A/B)の結果
TMP_DIR = os.path.join(TX_DIR, ".tmp")
SETTINGS = os.path.join(DATA_DIR, "settings.json")
FEEDBACK = os.path.join(DATA_DIR, "learn-feedback.json")   # 提案の採用・却下の記録(設定ファイルとは別にして、画面側の保存と競合させない)
MARKER_DATA = os.environ.get("TRANSCRIBE_MARKER_DATA") or os.path.join(os.path.dirname(ROOT), "clip-marker", "data.json")
STUDIO_DATA = os.environ.get("TRANSCRIBE_STUDIO_DATA") or os.path.join(_layout.tool_dir("studio", os.path.dirname(ROOT)), "data.json")   # 切り抜きスタジオのマーク(読むだけ)
PORT = 8775
ALLOWED_HOSTS = set()
BASE_PATH = "/"   # 画面の場所。入口の統合サーバーに取り込まれたときは "/transcribe/"(home/mount.py が prepare() で入れる)
MAX_BODY = 32 * 1024 * 1024
MAX_SEGMENTS = 20000
TAGS = ("unclear", "overlap", "bgm")   # 行に付けるメモ。unclear(聞き取れない)の行は、精度測定・学習の正解に使わない
MAX_TEXT = 2000
MAX_SPAN_SEC = 6 * 3600
MAX_QUEUE = 200   # フォルダ一括で入れる分も含めた、待機できる最大件数
TID_RE = re.compile(r"^[0-9a-f]{12}$")
MODEL_RE = re.compile(r"^(?!\.)[A-Za-z0-9_.-]+(/(?!\.)[A-Za-z0-9_.-]+)?$")   # 「..」で始まる名前(親フォルダの指定)は受け付けない


def valid_model(name):
    """モデル名として受け付けるか。faster-whisper は、名前と同じフォルダが(起動したフォルダからの相対で)あれば、
    それをモデルとして読み込むので、手元に実在するパスになる名前は断る(例: 「transcripts」「models/diar」)。
    Hugging Face の「組織/名前」と、small・large-v3 などの名前だけを通す。"""
    if not isinstance(name, str) or len(name) > 100 or not MODEL_RE.match(name):
        return False
    try:
        return not (os.path.exists(name) or os.path.exists(os.path.join(ROOT, name)))
    except (OSError, ValueError):
        return False
MEDIA_TYPES = {
    ".mp4": "video/mp4", ".m4v": "video/mp4", ".mov": "video/quicktime", ".webm": "video/webm", ".mkv": "video/x-matroska",
    ".avi": "video/x-msvideo", ".ts": "video/mp2t", ".flv": "video/x-flv",
    ".mp3": "audio/mpeg", ".m4a": "audio/mp4", ".aac": "audio/aac", ".wav": "audio/wav", ".flac": "audio/flac",
    ".ogg": "audio/ogg", ".opus": "audio/ogg", ".wma": "audio/x-ms-wma",
}
MODELS = [
    ("small", "small(軽い・精度はそこそこ)"),
    ("medium", "medium(バランス型)"),
    ("large-v3", "large-v3(高精度・重い。GPU推奨)"),
    ("large-v3-turbo", "large-v3-turbo(large-v3に近い精度で、より速い)"),
    ("kotoba-tech/kotoba-whisper-v2.0-faster", "kotoba-whisper v2.0(日本語特化・高速。聞き取りにくい音声は苦手なことも)"),
]
LANGS = ["ja", "en", "ko", "zh", "auto"]
HALLUC = ("ご視聴ありがとうございました", "チャンネル登録", "字幕", "Thanks for watching", "Subtitles by", "ご清聴ありがとうございました")
# よくある誤認識の文(S-3。2026-09-29 に足した分): 配信者が本当に言うこともある文なので、**行のほとんどがその文のとき**だけ印を付ける
# (上の HALLUC は以前からの決まりのまま = 文の一部に含まれれば印)。Whisper が無音・BGM から出しやすい動画の締めの決まり文句と、音楽の表記
HALLUC_LINE = ("ご視聴いただきありがとうございました", "ご視聴いただきありがとうございます", "ご覧いただきありがとうございました",
               "最後までご視聴", "高評価よろしくお願いします", "高評価お願いします", "高評価とチャンネル登録", "グッドボタン",
               "次回もお楽しみに", "次の動画でお会いしましょう", "次回の動画でお会いしましょう", "また次回お会いしましょう",
               "今日の動画はここまで", "今回の動画はここまで", "Thank you for watching", "Please subscribe", "Amara.org")
HALLUC_LINE_REST = 3    # 決まり文句を除いた残りがこの文字数以下なら「行のほとんどがその文」
MUSIC_ONLY = re.compile(r"^[\s♪♫♬～~〜・.。、]*([(（\[［【]\s*(音楽|拍手|BGM|ＢＧＭ)\s*[)）\]］】])?[\s♪♫♬～~〜・.。、]*$")
LEAK_FLAG = "ヒントの語だけ(プロンプトの漏れ出しの可能性)"
LEAK_MAX_SEC = 3.0      # 短い区間で、認識のヒントに渡した語だけが出た行(声が無い所でヒントを書き写すことがある。S-3)
REP_MIN = 5             # 行の中で同じ語(2〜10 文字)がこの回数以上続いたら「繰り返しの可能性」(笑い・叫びの 1 文字の繰り返しは除く)
REP_RE = re.compile(r"(.{2,10}?)\1{%d,}" % (REP_MIN - 1))


def _reject_json_constant(name):
    raise ValueError("NaN / Infinity は受け付けません: %s" % name)


class ApiError(Exception):
    def __init__(self, code, message, status=400, extra=None):
        super().__init__(message)
        self.code, self.message, self.status, self.extra = code, message, status, extra or {}


# ---------- ユーティリティ ----------
def replace_retry(src, dst):
    """os.replace。Windows でウイルス対策ソフト・検索インデックスが一瞬ファイルを開いていて失敗したときは、少し待ってやり直す
    (自動保存がたまに「保存できません」になるのを防ぐ。規則は ytt_core.fsio.replace_retry)。"""
    _fsio.replace_retry(src, dst)


def atomic_write(path, data: bytes):
    """一時ファイルに書き、ディスクへ確実に書き出して(fsync)から置き換える(ytt_core.fsio.atomic_write)。
    fsync に失敗したら保存も失敗にする: 停電・強制終了のあとに「中身が空の文字起こし」が残るのを防ぐため(校正の成果を失わないことを優先)。"""
    _fsio.atomic_write(path, data, fsync_required=True)


# ---------- 記録(落ちたときの手がかり) ----------
# serve.log: 起動・終了・ジョブの開始と終了(使っているメモリつき)・例外。serve.crash.log: Python が捕まえられない異常終了(ネイティブの落ち)のときの手がかり。
# .running.json: 起動中の印(実行中のジョブつき)。正常に終了すれば消える。次の起動で残っていれば「前回は異常終了」と表示する。
LOG_FILE = os.path.join(DATA_DIR, "serve.log")
CRASH_FILE = os.path.join(DATA_DIR, "serve.crash.log")
RUN_MARK = os.path.join(DATA_DIR, ".running.json")
TOOL_ID = "transcribe"   # docs/spec/pipeline.md の 4 のツールID(.runtime/transcribe.json)
_pio_mod = []


def pio(required=True):
    """受け渡しの部品 pipeline_io(docs/spec/pipeline.md。clip/v1・transcript/v1・cut-plan/v1・動画の隣への保存・.runtime)。
    必要になったときに読み込む: serve.py だけを差し替えた(隣の .py を更新し忘れた)場合でも、サーバー自体は起動して従来の機能は使えるように。
    required=False なら、読めないとき None(文字起こしの開始時の .clip.json 探しなど、無くても続けられる所で使う)。"""
    if not _pio_mod:
        try:
            import pipeline_io
            _pio_mod.append(pipeline_io)
        except ImportError as e:
            if not required:
                return None
            raise ApiError("missing_module", "受け渡しの部品(pipeline_io.py / resolve_export.py)が見つかりません。"
                                             "ツールのフォルダの中身(.py と index.html)をまとめて更新してください(%s)" % e, 500)
    return _pio_mod[0]
log = logging.getLogger("tx")
_run_state = {"pid": os.getpid(), "started": 0, "job": None}
_crash_fp = None


def rss_mb():
    """このプロセスが使っているメモリ(MB)。取れなければ None。"""
    try:
        if os.name == "nt":
            import ctypes
            from ctypes import wintypes

            class PMC(ctypes.Structure):
                _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD), ("PeakWorkingSetSize", ctypes.c_size_t), ("WorkingSetSize", ctypes.c_size_t),
                            ("QuotaPeakPagedPoolUsage", ctypes.c_size_t), ("QuotaPagedPoolUsage", ctypes.c_size_t), ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                            ("QuotaNonPagedPoolUsage", ctypes.c_size_t), ("PagefileUsage", ctypes.c_size_t), ("PeakPagefileUsage", ctypes.c_size_t)]
            pmc = PMC()
            pmc.cb = ctypes.sizeof(pmc)
            k32, ps = ctypes.windll.kernel32, ctypes.windll.psapi
            k32.GetCurrentProcess.restype = wintypes.HANDLE
            ps.GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.POINTER(PMC), wintypes.DWORD]
            if ps.GetProcessMemoryInfo(k32.GetCurrentProcess(), ctypes.byref(pmc), pmc.cb):
                return pmc.WorkingSetSize / 1048576.0
            return None
        with open("/proc/self/statm", "r") as f:
            return int(f.read().split()[1]) * os.sysconf("SC_PAGE_SIZE") / 1048576.0
    except Exception:
        return None


def _mem():
    m = rss_mb()
    return "%dMB" % m if m is not None else "?"


def setup_logging(hooks=True):
    """ログとクラッシュ記録を有効にする(起動時に1回だけ)。ファイルが作れなくても動く。
    hooks=False(入口の統合サーバーに取り込まれたとき)は、プロセス全体の設定(未処理の例外の記録先・faulthandler)は変えない(入口のもの)。"""
    global _crash_fp
    if not log.handlers:
        log.setLevel(logging.INFO)
        log.propagate = False
        try:
            h = logging.handlers.RotatingFileHandler(LOG_FILE, maxBytes=512 * 1024, backupCount=2, encoding="utf-8")
            h.setFormatter(logging.Formatter("%(asctime)s %(message)s"))
            log.addHandler(h)
        except OSError:
            log.addHandler(logging.NullHandler())
    if not hooks:
        return
    sys.excepthook = lambda t, v, tb: log.error("未処理の例外", exc_info=(t, v, tb))
    threading.excepthook = lambda a: log.error("スレッド %s の未処理の例外", getattr(a.thread, "name", "?"), exc_info=(a.exc_type, a.exc_value, a.exc_traceback))
    try:
        if os.path.exists(CRASH_FILE) and os.path.getsize(CRASH_FILE) > 256 * 1024:
            os.unlink(CRASH_FILE)
        _crash_fp = open(CRASH_FILE, "a", encoding="utf-8")
        faulthandler.enable(file=_crash_fp, all_threads=True)
    except (OSError, RuntimeError, ValueError):
        pass


def write_mark(job=None):
    """起動中の印を書く(job=実行中のジョブの情報。None なら実行中なし)。"""
    _run_state["job"] = job
    try:
        atomic_write(RUN_MARK, json.dumps(_run_state, ensure_ascii=False).encode("utf-8"))
    except OSError:
        pass


def check_previous_run():
    """前回の印が残っていれば(=正常に終了しなかった)、その内容を返す。なければ None。"""
    try:
        with open(RUN_MARK, "r", encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {"pid": "?"}
    except (OSError, ValueError):
        return None


def clear_mark():
    try:
        os.unlink(RUN_MARK)
    except OSError:
        pass


def find_ffmpeg():
    """環境変数 TRANSCRIBE_FFMPEG があればそれ、無ければ PATH から。"""
    return _tools.find_tool("ffmpeg", "TRANSCRIBE_FFMPEG")


def media_duration(path):
    ff = find_ffmpeg()
    if not ff:
        return None
    try:
        p = subprocess.run([ff, "-hide_banner", "-nostdin", "-i", path], stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                           stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace", timeout=30)
    except (OSError, subprocess.SubprocessError):
        return None
    m = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", p.stdout or "")
    return int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3)) if m else None


def num(x, default=None):
    try:
        v = float(x)
    except (TypeError, ValueError):
        return default
    return v if math.isfinite(v) else default


def fmt_hms(t):
    t = max(0, int(t))
    return "%d:%02d:%02d" % (t // 3600, t % 3600 // 60, t % 60)


def check_source(path):
    p = os.path.abspath(str(path or "").strip().strip('"'))
    if not os.path.isfile(p):
        raise ApiError("no_file", "ファイルが見つかりません(パスを確認してください)", 400)
    if os.path.splitext(p)[1].lower() not in MEDIA_TYPES:
        raise ApiError("bad_ext", "動画・音声ファイルではないようです(対応: %s)" % " ".join(sorted(MEDIA_TYPES)), 400)
    return p


def setup_cuda_paths():
    """pip の nvidia-cublas-cu12 / nvidia-cudnn-cu12 が入れた DLL / .so を、ctranslate2 が見つけられるようにする。"""
    try:
        import importlib.util
        spec = importlib.util.find_spec("nvidia")
        roots = list(spec.submodule_search_locations or []) if spec else []
    except Exception:
        roots = []
    for root in roots:
        try:
            names = os.listdir(root)
        except OSError:
            continue
        for n in names:
            for sub in ("bin", "lib"):
                d = os.path.join(root, n, sub)
                if os.path.isdir(d):
                    if hasattr(os, "add_dll_directory"):
                        try:
                            os.add_dll_directory(d)
                        except OSError:
                            pass
                    os.environ["PATH"] = d + os.pathsep + os.environ.get("PATH", "")


_nv_cache = []


def nvidia_gpu():
    """NVIDIA GPU の名前(nvidia-smi で確認)。なければ None。"""
    if _nv_cache:
        return _nv_cache[0]
    name = None
    exe = shutil.which("nvidia-smi")
    if exe:
        try:
            p = subprocess.run([exe, "--query-gpu=name", "--format=csv,noheader"], stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                               stderr=subprocess.DEVNULL, text=True, encoding="utf-8", errors="replace", timeout=10)
            name = (p.stdout or "").strip().splitlines()[0].strip()[:80] if p.returncode == 0 and (p.stdout or "").strip() else None
        except (OSError, subprocess.SubprocessError, IndexError):
            name = None
    _nv_cache.append(name)
    return name


def has_faster_whisper():
    if worker_fake():
        return True
    return worker_has("faster_whisper")


_has_cache = {}


def worker_python():
    """認識ワーカーを動かす Python。Mac/Linux で このフォルダに .venv があればそちら(install.command が faster-whisper を入れる先。
    入口(home/launch.py)が単独起動のときに使うのと同じ規則)。Windows は今と同じ Python。"""
    if os.name != "nt":
        v = os.path.join(ROOT, ".venv", "bin", "python")
        if os.path.isfile(v):
            return v
    return sys.executable


def worker_has(*mods):
    """認識ワーカーの Python に、そのモジュールが入っているか(読み込みはしない)。サーバーと同じ Python ならその場で調べ、
    違う Python(入口に取り込まれ、ワーカーは .venv のとき)なら1回だけ別プロセスで調べて覚えておく。"""
    key = mods
    if key in _has_cache:
        return _has_cache[key]
    import importlib.util
    py = worker_python()
    ok = False
    try:
        if os.path.normcase(os.path.abspath(py)) == os.path.normcase(os.path.abspath(sys.executable)):
            ok = all(importlib.util.find_spec(m) is not None for m in mods)
        else:
            code = "import importlib.util,sys; sys.exit(0 if all(importlib.util.find_spec(m) for m in sys.argv[1:]) else 1)"
            ok = subprocess.run([py, "-c", code] + list(mods), stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                timeout=60, creationflags=_worker_flags()).returncode == 0
    except Exception:
        ok = False
    _has_cache[key] = ok
    return ok


def cuda_count():
    try:
        import ctranslate2
        return int(ctranslate2.get_cuda_device_count())
    except Exception:
        return 0


def cuda_libs_ok():
    """GPU 処理に必要な cuBLAS(CUDA 12) と cuDNN(9) が読み込めるか。ドライバだけでは GPU 処理はできない。"""
    import ctypes
    names = (("cublas64_12.dll", "cudnn64_9.dll") if os.name == "nt" else ("libcublas.so.12", "libcudnn.so.9"))
    try:
        for n in names:
            ctypes.CDLL(n)
        return True
    except OSError:
        return False


def _gpu_ready_local():
    """このプロセスで GPU(CUDA)が使えるか。ctranslate2 を読み込むので、認識ワーカーの中でだけ呼ぶ。"""
    return cuda_count() > 0 and cuda_libs_ok()


_gpu_cache = {}


def gpu_ready():
    """GPU で文字起こしできるか(画面の表示用)。サーバーのプロセスでは ctranslate2(ネイティブのライブラリ)を読み込まないよう、
    1回だけ別プロセス(tx_worker.py --probe)で調べて覚えておく。調べ終わるまでは False。"""
    if IN_WORKER:
        return _gpu_ready_local()
    if "v" in _gpu_cache:
        return _gpu_cache["v"]
    if backend_name() == "fake" or worker_fake() or not has_faster_whisper():
        _gpu_cache["v"] = False
        return False
    if not _gpu_cache.get("started"):
        _gpu_cache["started"] = True
        threading.Thread(target=_probe_gpu, daemon=True, name="gpu-probe").start()
    return False


def _probe_gpu():
    ok = False
    try:
        p = subprocess.run([worker_python(), WORKER_SCRIPT, "--probe"], stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                           timeout=120, env=worker_env(), cwd=ROOT, creationflags=_worker_flags())
        ok = p.returncode == 0 and b'"cuda": true' in (p.stdout or b"")
    except (OSError, subprocess.SubprocessError):
        ok = False
    _gpu_cache["v"] = ok


def backend_name():
    return "fake" if os.environ.get("TRANSCRIBE_BACKEND") == "fake" else "faster-whisper"


def worker_fake():
    """テスト用: TRANSCRIBE_BACKEND=worker-fake のとき、サーバーは本物の経路(認識ワーカー)を使い、ワーカーの中だけ偽のモデルで動く。
    faster-whisper を入れていない環境でも、ワーカーとのやり取り・異常終了からの立ち直りを確かめられるようにする。"""
    return os.environ.get("TRANSCRIBE_BACKEND") == "worker-fake"


# ---------- 文字起こしの保存 ----------
def tx_path(tid):
    return os.path.join(TX_DIR, tid + ".json")


def sanitize_transcript(obj, base=None):
    """クライアントから来た編集内容を検査して、保存できる形にする。"""
    speakers, seen = [], set()
    for s in (obj.get("speakers") or [])[:20]:
        if not isinstance(s, dict):
            continue
        sid = re.sub(r"[^\w-]", "", str(s.get("id", "")))[:12]
        if not sid or sid in seen:
            continue
        seen.add(sid)
        speakers.append({"id": sid, "name": str(s.get("name", ""))[:30] or sid,
                         "color": re.sub(r"[^#\w]", "", str(s.get("color", "")))[:9]})
    segs, ids = [], set()
    for i, sg in enumerate(obj.get("segments") or []):
        if i >= MAX_SEGMENTS:
            raise ApiError("too_many", "行数が多すぎます", 400)
        if not isinstance(sg, dict):
            continue
        a, b = num(sg.get("start")), num(sg.get("end"))
        if a is None or b is None or a < 0 or b < a:
            continue
        sid = re.sub(r"[^\w-]", "", str(sg.get("id", "")))[:16] or "s%d" % (i + 1)
        while sid in ids:
            sid += "x"
        ids.add(sid)
        sp = str(sg.get("speaker", ""))
        one = {"id": sid, "start": round(a, 2), "end": round(b, 2), "text": str(sg.get("text", ""))[:MAX_TEXT],
               "speaker": sp if sp in seen else "", "flag": str(sg.get("flag", ""))[:100]}
        tg = [t for t in TAGS if isinstance(sg.get("tags"), list) and t in sg["tags"]]   # 音の状態のメモ(聞き取れない・声が重なる・BGMが大きい)
        if tg:
            one["tags"] = tg
        if sg.get("proofed") is True:   # 校正済み(人が聞いて、この行の文字が正しいと確認した印)。学習・精度測定の正解データに使う
            one["proofed"] = True
        if sg.get("cutState") == "cut":
            one["cutState"] = "cut"
        segs.append(one)
    out = dict(base or {})
    if "evalSet" in obj:   # 評価用の印(キーが来たときだけ変える。古い画面から保存しても外れないように)
        if obj.get("evalSet") is True:
            out["evalSet"] = True
        else:
            out.pop("evalSet", None)
    out.update({"title": str(obj.get("title", out.get("title", "")))[:120], "speakers": speakers, "segments": segs,
                "updatedAt": int(time.time() * 1000)})
    return out


_summary_cache = {}   # tid -> ((更新日時ns, 大きさ), 要約)。一覧・文字起こし済みの判定のたびに、全部の文書を JSON として読み直さないため


def transcript_summary(tid):
    """文書1件の要約(一覧の1行 + 元ファイル・範囲)。ファイルの更新日時と大きさが同じなら、前に読んだ結果を使う。読めなければ None。"""
    try:
        st = os.stat(tx_path(tid))
        key = (st.st_mtime_ns, st.st_size)
        hit = _summary_cache.get(tid)
        if hit and hit[0] == key:
            return hit[1]
        with open(tx_path(tid), "r", encoding="utf-8") as f:
            d = json.load(f)
    except (OSError, ValueError):
        return None
    if not isinstance(d, dict):
        return None
    segs = [s for s in (d.get("segments") or []) if isinstance(s, dict)]
    text_rows = sum(1 for s in segs if str(s.get("text") or "").strip())
    proofed = sum(1 for s in segs if s.get("proofed") is True and str(s.get("text") or "").strip())
    a = num(d.get("start"), 0.0) or 0.0
    b = num(d.get("end"))
    dur = num(d.get("duration"))
    if b is not None and b > a:
        length = b - a
    elif dur is not None and dur > a:
        length = dur - a
    else:   # 古い文書・長さの記録が無い文書は、最後の行の終わりまで
        length = max([num(s.get("end"), 0.0) or 0.0 for s in segs] or [0.0]) - a
    clip = d.get("clip") if isinstance(d.get("clip"), dict) else None
    src = clip.get("source") if clip and isinstance(clip.get("source"), dict) else {}
    rng = clip.get("range") if clip and isinstance(clip.get("range"), dict) else {}
    mk = clip.get("mark") if clip and isinstance(clip.get("mark"), dict) else {}
    sm = {"id": tid, "title": d.get("title", ""), "sourceName": d.get("sourceName", ""), "start": d.get("start", 0),
          "end": d.get("end"), "model": d.get("model", ""), "segments": len(d.get("segments") or []),
          "createdAt": d.get("createdAt", 0), "updatedAt": d.get("updatedAt", 0), "evalSet": d.get("evalSet") is True,
          "hasClip": clip is not None,
          # v0.15.0: 履歴の一覧で見分け・絞り込みに使う(校正の進み具合・長さ・元の配信)
          "rows": text_rows, "proofed": proofed, "cut": sum(1 for s in segs if s.get("cutState") == "cut"),
          "flagged": sum(1 for s in segs if str(s.get("flag") or "").strip()), "durationSec": round(max(0.0, length), 1),
          "videoId": str(src.get("videoId") or "")[:40] if clip else "", "clipTitle": str(src.get("title") or "")[:200] if clip else "",
          "clipStart": num(rng.get("start")), "clipEnd": num(rng.get("end")), "markLabel": str(mk.get("label") or "")[:80],
          "_sourcePath": d.get("sourcePath") or "", "_whole": bool(d.get("whole"))}
    _summary_cache[tid] = (key, sm)
    return sm


def _tids():
    return [n[:-5] for n in (os.listdir(TX_DIR) if os.path.isdir(TX_DIR) else []) if n.endswith(".json") and TID_RE.match(n[:-5])]


_studio_cache = {"key": None, "path": None, "videos": {}, "groups": []}   # スタジオの data.json から読んだ {videoId: {"channel", "title"}} と
                                                                        # コラボのまとまり [[videoId, …]](更新日時と大きさでキャッシュ)
_studio_lock = threading.Lock()


def _studio_load():
    """切り抜きスタジオの data.json(読むだけ。置き場所は studio_data_path() と同じ規則 = 入口の案件の画面・ytt_core.txindex と同じ)。
    -> ({videoId: {"channel", "title"}}, コラボのまとまり [[videoId, …]])。一覧のたびに大きな data.json を読み直さないよう、
    ファイルの更新日時と大きさが同じなら前の結果を使う。"""
    path = STUDIO_DATA
    try:
        st = os.stat(path)
        key = (st.st_mtime_ns, st.st_size)
    except (OSError, ValueError):
        return {}, []
    with _studio_lock:
        if _studio_cache["key"] == key and _studio_cache["path"] == path:
            return _studio_cache["videos"], _studio_cache["groups"]
    d = _read_json_file(path)
    out, groups = {}, []
    vids = d.get("videos") if isinstance(d, dict) else None
    if isinstance(vids, dict):
        for vid, v in list(vids.items())[:5000]:
            if isinstance(v, dict):
                out[str(vid)[:40]] = {"channel": str(v.get("channel") or "")[:100], "title": str(v.get("title") or "")[:200]}
    gs = d.get("groups") if isinstance(d, dict) else None
    for g in (list(gs.values())[:2000] if isinstance(gs, dict) else []):
        ms = g.get("members") if isinstance(g, dict) else None
        if isinstance(ms, list):
            groups.append([str(m)[:40] for m in ms[:50] if isinstance(m, str)])
    with _studio_lock:
        _studio_cache.update({"key": key, "path": path, "videos": out, "groups": groups})
    return out, groups


def studio_videos():
    """-> {videoId: {"channel", "title"}}(履歴の一覧の配信者・配信の題名)"""
    return _studio_load()[0]


def studio_stream(video_id):
    """配信 -> {"channel", "title", "collab": [{"videoId", "channel", "title"}]}(コラボ = スタジオで同じまとまりにした他の配信)。無ければ None"""
    vids, groups = _studio_load()
    vid = str(video_id or "")[:40]
    if vid not in vids:
        return None
    collab, seen = [], {vid}
    for g in groups:
        if vid in g:
            for m in g:
                if m not in seen and len(collab) < 12:
                    seen.add(m)
                    collab.append(dict(vids.get(m) or {"channel": "", "title": ""}, videoId=m))
    return dict(vids[vid], collab=collab)


PACK_CHECK_BUDGET = 2.0   # 秒。一覧1回でパック・動画の有無を調べる時間の上限(外付けの取り外し・つながらないネットワークドライブで一覧が止まらないように)


def pack_info(media_path):
    """動画の隣の <名前>_pack(cut2resolve の既定の出力先)。規則は ytt_core/txindex.pack_info の1か所(入口の案件の画面と同じ判定)。
    -> {"textplus": bool, "updatedAt": ms} か None(一覧の API にフォルダのパスは出さない)"""
    from ytt_core import txindex as _txi   # 一覧を作るときだけ使う(読み込みを軽く)
    p = _txi.pack_info(media_path)
    return {"textplus": p["textplus"], "updatedAt": p["updatedAt"]} if p else None


def _files_state(items):
    """一覧の各文書の、元の動画の有無(mediaOk)とパック(pack)。フォルダごとに1回だけ存在を確かめ、全体で PACK_CHECK_BUDGET 秒まで。
    ネットワーク上のパス(\\\\サーバー\\…)は調べない(一覧を開くだけでそのサーバーへ資格情報を送らないため。clip_info と同じ考え)。
    調べなかった・調べきれなかったものは mediaOk = None(不明)。"""
    t0 = time.monotonic()
    dirs = {}
    for it in items:
        sp = it.pop("_sp", "")
        it["mediaOk"], it["pack"] = None, None
        if not sp or not os.path.isabs(sp) or _fsio.is_network_path(sp):
            if not sp:
                it["mediaOk"] = False
            continue
        if time.monotonic() - t0 > PACK_CHECK_BUDGET:
            continue
        folder = os.path.dirname(sp)
        if folder not in dirs:
            try:
                dirs[folder] = os.path.isdir(folder)
            except (OSError, ValueError):
                dirs[folder] = False
        if not dirs[folder]:
            it["mediaOk"] = False
            continue
        try:
            it["mediaOk"] = os.path.isfile(sp)
        except (OSError, ValueError):
            it["mediaOk"] = False
        it["pack"] = pack_info(sp)


def list_transcripts():
    """GET /api/transcripts の items。作った日が新しい順(画面で並べ替える)。
    v0.15.0: 校正の進み具合(rows・proofed・cut・flagged)・長さ(durationSec)・元の配信(videoId・clipTitle・clipStart/End・markLabel)・
    配信者(channel。スタジオの data.json から)・元の動画の有無(mediaOk)・パック(pack)も返す。"""
    items, seen = [], set()
    for tid in _tids():
        seen.add(tid)
        sm = transcript_summary(tid)
        if sm:
            it = dict({k: v for k, v in sm.items() if not k.startswith("_")}, _sp=sm["_sourcePath"])
            it.update(edit_summary(tid))   # 「編集」: カットの有無・rev・パックを作った rev(履歴の「パック済み」「作り直しが要る」)
            it["packStale"] = pack_stale(it)
            it.pop("_packDocAt", None)
            items.append(it)
    for cache in (_summary_cache, _edit_cache):   # 消した文書の分は捨てる
        for k in [k for k in cache if k not in seen]:
            cache.pop(k, None)
    studio = studio_videos()
    for it in items:
        sv = studio.get(it["videoId"]) if it["videoId"] else None
        it["channel"] = sv["channel"] if sv else ""
        if sv and sv["title"]:
            it["streamTitle"] = sv["title"]   # スタジオで題名を直していれば、そちらを見出しに使う
    _files_state(items)
    items.sort(key=lambda x: x["createdAt"], reverse=True)
    return items


def read_transcript(tid):
    if not TID_RE.match(tid or "") or not os.path.isfile(tx_path(tid)):
        raise ApiError("not_found", "文字起こしが見つかりません", 404)
    try:
        with open(tx_path(tid), "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        raise ApiError("broken", "文字起こしファイルを読み込めません", 500)


# ---------- 履歴(自動スナップショット)と保存の競合検出 ----------
HIST_INTERVAL = 600     # 秒。保存のたびではなく、前回の履歴からこれだけ経っていたら1つ残す
HIST_KEEP = 30          # 1本あたりの保持数(古いものから消す)
_save_lock = threading.Lock()


def _hist_dir(tid):
    return os.path.join(TX_DIR, ".hist", tid)


def hist_stamps(tid):
    d = _hist_dir(tid)
    out = []
    if os.path.isdir(d):
        for n in os.listdir(d):
            if n.endswith(".json") and n[:-5].isdigit():
                out.append(int(n[:-5]))
    return sorted(out)


def hist_snapshot(tid, force=False):
    """いまの保存内容を履歴へ1つ残す。直近の履歴が新しければ(force でなければ)何もしない。"""
    src = tx_path(tid)
    if not os.path.isfile(src):
        return None
    stamps = hist_stamps(tid)
    now = int(time.time() * 1000)
    if not force and stamps and now - stamps[-1] < HIST_INTERVAL * 1000:
        return None
    d = _hist_dir(tid)
    os.makedirs(d, exist_ok=True)
    ts = now if not stamps or now > stamps[-1] else stamps[-1] + 1
    shutil.copy2(src, os.path.join(d, "%d.json" % ts))
    stamps.append(ts)
    for old in stamps[:-HIST_KEEP]:
        try:
            os.unlink(os.path.join(d, "%d.json" % old))
        except OSError:
            pass
    return ts


def list_history(tid):
    read_transcript(tid)
    items = []
    for ts in reversed(hist_stamps(tid)):
        try:
            with open(os.path.join(_hist_dir(tid), "%d.json" % ts), "r", encoding="utf-8") as f:
                d = json.load(f)
        except (OSError, ValueError):
            continue
        segs = d.get("segments") or []
        items.append({"ts": ts, "segments": len(segs), "proofed": sum(1 for s in segs if s.get("proofed") is True),
                      "chars": sum(len(s.get("text", "")) for s in segs)})
    return items


def save_transcript(tid, obj):
    """編集内容の保存。baseUpdatedAt が付いていて、保存済みの版とずれていれば 409(別のタブ・再認識などで先に更新されている)。"""
    with _save_lock:
        base = read_transcript(tid)
        b = obj.get("baseUpdatedAt")
        if b is not None and not obj.get("force") and base.get("updatedAt") and b != base.get("updatedAt"):
            raise ApiError("conflict", "別の場所で先に更新されています(別のタブ、再認識、話者分離など)。読み込み直すか、この内容で上書きするか選んでください", 409)
        doc = sanitize_transcript(obj, base)
        apply_edit_cuts(tid, doc)   # 編集の内容があれば、行の「カット済」はそちらから決める(画面の古い印で上書きしない)
        try:
            hist_snapshot(tid)
        except OSError:
            pass    # 履歴が残せなくても保存は止めない
        atomic_write(tx_path(tid), json.dumps(doc, ensure_ascii=False, indent=1).encode("utf-8"))
        return doc


def restore_history(tid, ts):
    with _save_lock:
        read_transcript(tid)
        if not isinstance(ts, int) or ts not in hist_stamps(tid):
            raise ApiError("not_found", "その履歴は見つかりません", 404)
        p = os.path.join(_hist_dir(tid), "%d.json" % ts)
        try:
            with open(p, "r", encoding="utf-8") as f:
                old = json.load(f)
            hist_snapshot(tid, force=True)      # 戻す前の状態も残す(戻したことを取り消せるように)
            old["updatedAt"] = int(time.time() * 1000)
            apply_edit_cuts(tid, old)   # 戻すのは文字と行。カットは今の編集の内容のまま
            atomic_write(tx_path(tid), json.dumps(old, ensure_ascii=False, indent=1).encode("utf-8"))
        except (OSError, ValueError):
            raise ApiError("broken", "履歴を読み込めません", 500)
        return old


# ---------- 編集の内容(残す区間。「編集」ツールのカットの正。docs/design/edit-tool-design.md の 4・5) ----------
# 文書 transcripts/<id>.json の隣の <id>.edit.json。校正の保存(文書の baseUpdatedAt)と、タイムラインの細かい保存(rev)を別にするため別のファイル。
# 行の「カット済」(cutState)は、編集の内容があるときは常にそこから決める(文書のどの書き込みでも apply_edit_cuts を通す)。
EDIT_SCHEMA = "youtube-tools-edit/v1"
MAX_EDIT_BYTES = 1024 * 1024
MAX_CLIPS = 5000
MAX_MEDIA_SEC = 24 * 3600
EDIT_ORIGINS = ("rows", "silence", "list", "plan", "manual", "all", "whole")   # whole = 「カットしない(動画全体)」を選んだ(気が利く画面へ 段3)
CUT_TOLERANCE_FRAMES = 0.75   # 行の時間のうち、残す区間に入るのがこれ未満(フレーム)なら「カット済」。区間の端はフレームに、行の時刻は 0.01 秒に丸めてあるため
_edit_cache = {}   # tid -> ((更新日時ns, 大きさ), 一覧用の要約)


def edit_path(tid):
    return os.path.join(TX_DIR, tid + ".edit.json")


def _real(x):
    """JSON の数(真偽値・文字列・NaN は数として扱わない)。-> float か None"""
    if isinstance(x, bool) or not isinstance(x, (int, float)):
        return None
    x = float(x)
    return x if math.isfinite(x) else None


def _fps_pair(v):
    if not isinstance(v, list) or len(v) != 2 or any(isinstance(x, bool) or not isinstance(x, int) for x in v):
        return None
    n, d = v
    if not (1 <= n <= 1000000 and 1 <= d <= 1000000 and 1 <= n / d <= 300):
        return None
    return [n, d]


def sanitize_edit(obj):
    """画面から来た編集の内容を検査して、保存できる形にする(知らない項目は捨てる。rev・packRev はサーバーが付ける)。
    v1: 動画は文書の動画1本だけ(sources は1つ・clips の src は 0)。区間は元の動画の秒で、時刻の順・重ならない。区間が0個も受け付ける(全部削った状態)"""
    if not isinstance(obj, dict):
        raise ApiError("bad_edit", "編集の内容の形が正しくありません", 400)
    srcs = obj.get("sources")
    if not isinstance(srcs, list) or len(srcs) != 1 or not isinstance(srcs[0], dict):
        raise ApiError("bad_edit", "動画(sources)は1つだけにしてください(複数の切り抜きをつなぐのは、まだ使えません)", 400)
    fps, dur = _fps_pair(srcs[0].get("fps")), _real(srcs[0].get("duration"))
    if fps is None or dur is None or not 0 < dur <= MAX_MEDIA_SEC:
        raise ApiError("bad_edit", "動画の fps・長さが正しくありません", 400)
    clips = obj.get("clips")
    if not isinstance(clips, list) or len(clips) > MAX_CLIPS:
        raise ApiError("bad_edit", "区間(clips)は %d 個までです" % MAX_CLIPS, 400)
    limit = dur + fps[1] / fps[0] + 1e-6   # 長さ + 1フレームまで(フレームの境目に丸めた分)
    out, prev = [], 0.0
    for c in clips:
        if not isinstance(c, dict):
            raise ApiError("bad_edit", "区間の形が正しくありません", 400)
        src = c.get("src", 0)
        if isinstance(src, bool) or src != 0:
            raise ApiError("bad_edit", "区間の動画(src)は 0 だけにしてください(複数の切り抜きをつなぐのは、まだ使えません)", 400)
        a, b = _real(c.get("in")), _real(c.get("out"))
        if a is None or b is None or not 0 <= a < b <= limit:
            raise ApiError("bad_edit", "区間の時刻が正しくありません(0 ≤ 始まり < 終わり ≤ 動画の長さ)", 400)
        if a < prev - 1e-6:
            raise ApiError("bad_edit", "区間は時刻の順に、重ならないように並べてください", 400)
        ra, rb = round(a, 3), round(b, 3)
        if rb <= ra:
            raise ApiError("bad_edit", "区間が短すぎます", 400)
        out.append({"src": 0, "in": ra, "out": rb})
        prev = b
    return {"sources": [{"fps": fps, "duration": round(dur, 3)}], "clips": out,
            "origin": obj.get("origin") if obj.get("origin") in EDIT_ORIGINS else "manual"}


def read_edit(tid):
    """保存済みの編集の内容。-> (中身 または None, 壊れているか)。形が正しくないもの(手で書き換えた・書きかけ)は壊れている扱い"""
    try:
        with open(edit_path(tid), "rb") as f:
            raw = f.read(MAX_EDIT_BYTES + 1)
    except FileNotFoundError:
        return None, False
    except OSError:
        return None, True
    try:
        d = json.loads(raw.decode("utf-8-sig"), parse_constant=_reject_json_constant) if len(raw) <= MAX_EDIT_BYTES else None
        if not isinstance(d, dict) or d.get("schema") != EDIT_SCHEMA or isinstance(d.get("rev"), bool) or not isinstance(d.get("rev"), int):
            return None, True
        out = sanitize_edit(d)
    except (UnicodeDecodeError, ValueError, ApiError):
        return None, True
    pr = d.get("packRev")
    out.update({"schema": EDIT_SCHEMA, "rev": max(0, d["rev"]), "updatedAt": d.get("updatedAt") if isinstance(d.get("updatedAt"), int) else 0,
                "packRev": pr if isinstance(pr, int) and not isinstance(pr, bool) and pr >= 0 else 0})
    if isinstance(d.get("pack"), dict):
        out["pack"] = d["pack"]
    return out, False


def edit_cut_flags(segs, edit):
    """編集の内容から、各行が「カット済」か。-> [bool](segs と同じ順)。
    行の時間が全部、削る区間に入っていれば(残す区間に入るのが CUT_TOLERANCE_FRAMES 未満なら)カット済。
    ごく短い行(2 × 許す幅 以下)は、行の真ん中が残す区間に入っているかで決める。画面の cut.js も同じ規則"""
    clips = edit["clips"]
    fps = edit["sources"][0]["fps"]
    tol = CUT_TOLERANCE_FRAMES * fps[1] / fps[0]
    starts = [c["in"] for c in clips]
    out = []
    for s in segs:
        a, b = num(s.get("start"), 0.0), num(s.get("end"), 0.0)
        i = max(0, bisect.bisect_right(starts, a) - 1)
        if b - a <= 2 * tol:
            mid = (a + b) / 2
            j = bisect.bisect_right(starts, mid) - 1
            out.append(not (j >= 0 and clips[j]["in"] <= mid < clips[j]["out"]))
            continue
        kept = 0.0
        while i < len(clips) and clips[i]["in"] < b:
            kept += max(0.0, min(b, clips[i]["out"]) - max(a, clips[i]["in"]))
            i += 1
        out.append(kept < tol)
    return out


def apply_edit_cuts(tid, doc, edit=None):
    """編集の内容があれば、文書の行の cutState をそれに合わせる(文書の書き込みは全部ここを通す)。
    -> 変わった行の数。編集の内容が無い・壊れているときは None(行の cutState はそのまま = 以前の使い方)"""
    if edit is None:
        edit, _broken = read_edit(tid)
        if not edit:
            return None
    segs = [s for s in (doc.get("segments") or []) if isinstance(s, dict)]
    changed = 0
    for s, cut in zip(segs, edit_cut_flags(segs, edit)):
        if cut != (s.get("cutState") == "cut"):
            changed += 1
        if cut:
            s["cutState"] = "cut"
        else:
            s.pop("cutState", None)
    return changed


DRAFT_SLOT_WAIT = 10.0   # 「行から」の行の端の無音を調べる順番(SLOTS)を待つ上限(秒)。過ぎたら無音を調べずに決まった余白で広げる


def _draft_slot(label):
    deadline = time.monotonic() + DRAFT_SLOT_WAIT
    return _heavy.SLOTS.slot(TOOL_ID, label, cancelled=lambda: time.monotonic() > deadline)


def edit_draft(tid, rows=False):
    """GET /api/edit/draft?id=&rows=1 : 動画の fps・長さと、たたき台「行から」(残す行が無ければ全部残す)。計算は cut2resolve の pack.py(resolve_export.edit_draft)。
    「行から」を計算するのは、カットが無い(壊れている)文書か rows=1(「行から」のボタン)のときだけ(行の端の無音を調べるのは重いので、開くたびにしない)。
    行の端を広げるかは設定の rowEdge(docs/design/edit-tool-design.md の 12 ⑥)。無音の検出は SLOTS を通す(DRAFT_SLOT_WAIT 秒待っても空かなければ決まった余白)。
    カット・パックに使えないとき(動画が無い・ネットワーク上・音声だけ)は {"unavailable": {"code", "message"}}。
    ネットワーク上の動画は調べない(カット・パックに使えない理由を画面に出す。一覧・clip-info と同じく、開くだけで資格情報を送らない)。
    隣の .cut-plan.json(スタジオなどの残す区間の指定)があるかも返す(たたき台「スタジオ」)"""
    import resolve_export
    doc = read_transcript(tid)
    src = str(doc.get("sourcePath") or "")

    def unavailable(code, message):   # 使えない理由は 200 で返す(画面が毎回エラーとして記録しないように。文書が無いときだけ 404)
        return {"unavailable": {"code": code, "message": message}}
    if not src:
        return unavailable("no_source", "この文書には動画のパスがありません")
    if _fsio.is_network_path(src):
        return unavailable("network_path", "ネットワーク上の動画は、カットとパックに使えません(このパソコンにコピーして開いてください)")
    if not os.path.isfile(src):
        return unavailable("source_missing", "元の動画が見つかりません(移動・削除した可能性があります)")
    try:
        need = bool(rows) or not read_edit(tid)[0]
        out = resolve_export.edit_draft(doc, SERVER_VERSION, rows=need, row_edge=load_settings().get("rowEdge"), heavy=_draft_slot)
    except resolve_export.ResolveExportError as e:
        msg = str(e)
        if "動画ストリーム" in msg:
            return unavailable("no_video", "映像の無いファイル(音声だけ)は、カットとパックに使えません")
        return unavailable("draft_failed", msg)
    out["planBeside"] = _yschemas.find_sidecar(src, ".cut-plan.json") or ""   # 作業用\ → 以前の置き方(動画の隣)
    return out


def edit_keeps_sec(edit):
    """編集の内容の残す区間(秒)。接している区間(分割しただけ)は1つにまとめる(パックと同じ)"""
    out = []
    for c in edit["clips"]:
        if out and c["in"] <= out[-1][1] + 1e-9:
            out[-1][1] = max(out[-1][1], c["out"])
        else:
            out.append([c["in"], c["out"]])
    return out


def keeps_arg(v):
    """画面から来た残す区間 [[開始, 終了], ...](秒)の検査(cut2resolve の keeps_from_spec と同じ決まり)"""
    if not isinstance(v, list) or not 1 <= len(v) <= MAX_CLIPS:
        raise ApiError("bad_keeps", "残す区間は 1〜%d 個にしてください" % MAX_CLIPS, 400)
    out, prev = [], 0.0
    for x in v:
        a, b = (_real(x[0]), _real(x[1])) if isinstance(x, list) and len(x) == 2 else (None, None)
        if a is None or b is None or not 0 <= a < b <= MAX_MEDIA_SEC or a < prev:
            raise ApiError("bad_keeps", "残す区間は時刻の順に、重ならないように [開始, 終了] で指定してください", 400)
        out.append([a, b])
        prev = b
    return out


def edit_preview(obj):
    """POST /api/edit/preview {"id", "keeps"}: カットのとおりに作ったときのパックの見積もり(区間の数・カット後の長さ・Text+ 字幕の数・注意)。ファイルは作らない"""
    import resolve_export
    doc = read_transcript(str(obj.get("id") or ""))
    keeps = keeps_arg(obj.get("keeps"))
    src = str(doc.get("sourcePath") or "")
    if not src or _fsio.is_network_path(src) or not os.path.isfile(src):
        raise ApiError("no_media", "元の動画が見つかりません", 400)
    try:
        return resolve_export.edit_preview(doc, keeps, SERVER_VERSION, wrap_arg(obj.get("wrap")))
    except resolve_export.ResolveExportError as e:
        raise ApiError("preview_failed", str(e), 400)


def wrap_arg(v, size=None):
    """Text+ 字幕の1段の文字数(0〜40)。無ければ設定の subtitle.wrapChars(size が横 1920x1080 なら横、それ以外は縦)"""
    if isinstance(v, (int, float)) and not isinstance(v, bool) and 0 <= v <= 40:
        return int(v)
    sub = subtitle_settings()
    return sub["wrapChars"]["horizontal" if str(size or "") == "1920x1080" else "vertical"]


PACK_README_NAMES = ("友人へ.txt", "予備_EDLで開く手順.txt")   # 2026-09-27 より前のパック(今は手順書のファイルを入れない)


def pack_readme(tid):
    """GET /api/edit/pack-readme?id=: 前回のパックの Resolve での手順。記録したフォルダが cut2resolve のパック
    (cut2resolve のパックを作った記録があるか、以前のパックなら中に cut-plan.json。ytt_core.txindex.is_pack_dir)のときだけ読む。
    今のパックは手順書のファイルが無いので、パックの Lua から作り直す(resolve_export.pack_instructions)。以前のパックはファイルを読む"""
    from ytt_core import txindex as _txi
    read_transcript(tid)
    d, _ = read_edit(tid)
    pk = (d or {}).get("pack") or {}
    folder = pk.get("dir") if isinstance(pk.get("dir"), str) else ""
    if not folder or _fsio.is_network_path(folder) or not _txi.is_pack_dir(folder):
        raise ApiError("not_found", "前回のパックのフォルダが見つかりません(移動・削除した可能性があります)", 404)
    import resolve_export
    text = resolve_export.pack_instructions(folder)
    if text:
        return {"name": "", "text": text}
    for n in PACK_README_NAMES:
        try:
            with open(os.path.join(folder, n), "rb") as f:
                return {"name": n, "text": f.read(256 * 1024).decode("utf-8-sig", "replace")}
        except OSError:
            continue
    raise ApiError("not_found", "パックの中に Resolve での手順を作る材料(.lua)がありません", 404)


def get_edit(tid):
    """GET /api/edit?id= -> {"edit": 中身 | null, "rev", "broken"}(無ければ null と rev 0)"""
    doc = read_transcript(tid)
    d, broken = read_edit(tid)
    pk = (d or {}).get("pack") or {}
    stale = pack_stale({"packRev": d["packRev"] if d else 0, "editRev": d["rev"] if d else 0, "updatedAt": doc.get("updatedAt") or 0,
                        "_packDocAt": pk.get("docUpdatedAt") if isinstance(pk.get("docUpdatedAt"), int) else 0})
    return {"edit": d, "rev": d["rev"] if d else 0, "broken": broken, "packStale": stale}


def save_edit(tid, obj):
    """PUT /api/edit?id= {"edit", "baseRev"} -> {"rev", "cutRows", "updatedAt"}。baseRev が保存済みの rev と違えば 409(別のタブ・窓で先に保存された)。
    文書の行の cutState も同じロックの中で合わせる(画面から2回に分けて送らない)。文書の updatedAt は変えない
    (cutState は編集の内容から決まる値なので、校正の保存の競合の検出(baseUpdatedAt)に巻き込まない)"""
    base = obj.get("baseRev")
    if isinstance(base, bool) or not isinstance(base, int) or base < 0:
        raise ApiError("bad_request", "baseRev(読み込んだときの rev)を付けてください", 400)
    clean = sanitize_edit(obj.get("edit"))
    with _save_lock:
        doc = read_transcript(tid)
        cur, broken = read_edit(tid)
        rev = cur["rev"] if cur else 0
        if base != rev:
            raise ApiError("conflict", "別のタブか窓で、先にカットが保存されています。読み直すか、こちらの内容で上書きするか選んでください", 409, {"rev": rev})
        if broken:   # 壊れたファイルは上書きする前に1つだけ残す(調べられるように)
            try:
                shutil.copy2(edit_path(tid), os.path.join(TX_DIR, tid + ".edit.broken.json"))
            except OSError:
                pass
        now = int(time.time() * 1000)
        d = dict(clean, schema=EDIT_SCHEMA, rev=rev + 1, updatedAt=now, packRev=cur["packRev"] if cur else 0)
        if cur and cur.get("pack"):
            d["pack"] = cur["pack"]
        body = json.dumps(d, ensure_ascii=False, indent=1).encode("utf-8")
        if len(body) > MAX_EDIT_BYTES:
            raise ApiError("too_big", "区間が多すぎて保存できません", 413)
        atomic_write(edit_path(tid), body)   # 先に編集の内容(文書の書き込みが失敗しても、次の保存で cutState は合う)
        if apply_edit_cuts(tid, doc, d):
            atomic_write(tx_path(tid), json.dumps(doc, ensure_ascii=False, indent=1).encode("utf-8"))
        cut_rows = [s.get("id") for s in doc.get("segments") or [] if isinstance(s, dict) and s.get("cutState") == "cut"]
        return {"rev": d["rev"], "cutRows": cut_rows, "updatedAt": now}


PACK_OUTPUT_LOUDNESS = (0, -11, -14, -16, -18)


def _pack_text(v, limit):
    """出力の設定の文字列: 長さの上限以内・制御文字なし(改行・タブ・NUL などを含めば None)"""
    if not isinstance(v, str) or len(v) > limit or any(ord(ch) < 32 or ord(ch) == 127 for ch in v):
        return None
    return v


def sanitize_pack_output(o):
    """POST /api/edit/pack の output(作ったときの出力の設定)を確かめる。決まった鍵だけ残し(余計な鍵は黙って捨てる)、
    必須の鍵が1つでも正しくなければ、あるいは任意の鍵が入っていて正しくなければ None(= 記録には output を入れない。
    古い画面・まとめて実行 home/autorun.py は output を送らないので、エラーにはしない)。bool は int でもあるので先に isinstance(bool) で見る"""
    if not isinstance(o, dict):
        return None
    out = {}
    fps = o.get("fps")
    if not isinstance(fps, str) or not re.fullmatch(r"\d{1,3}", fps, re.A):
        return None
    out["fps"] = fps
    if o.get("size") not in ("1080x1920", "1920x1080"):
        return None
    out["size"] = o["size"]
    wrap = o.get("wrap")
    if isinstance(wrap, bool) or not isinstance(wrap, int) or not 0 <= wrap <= 40:
        return None
    out["wrap"] = wrap
    for k in ("textplus", "backup", "render", "speakerColors"):
        if not isinstance(o.get(k), bool):
            return None
        out[k] = o[k]
    if "streamer" in o:
        st = _pack_text(o["streamer"], 200)
        if st is None:
            return None
        out["streamer"] = st
    if "loudness" in o:
        v = o["loudness"]
        if isinstance(v, bool) or not isinstance(v, (int, float)) or v not in PACK_OUTPUT_LOUDNESS:
            return None
        out["loudness"] = v
    if "volume" in o:
        v = o["volume"]
        if isinstance(v, bool) or not isinstance(v, int) or not 1 <= v <= 200:
            return None
        out["volume"] = v
    if "advanced" in o:
        adv = o["advanced"]
        if not isinstance(adv, dict):
            return None
        a = {}
        for k in ("srcStartTc", "recStart", "reel"):
            if k in adv:
                t = _pack_text(adv[k], 40)
                if t is None:
                    return None
                a[k] = t
        out["advanced"] = a
    return out


def record_pack(obj):
    """POST /api/edit/pack {"id", "rev", "docUpdatedAt", "dir", "files"}: 画面がパックを作り終えたときに呼ぶ(rev は増やさない)。
    packRev = そのパックを作った編集の rev。rev ≠ packRev か、文書の updatedAt が docUpdatedAt より新しければ「作り直し」"""
    tid = str(obj.get("id") or "")
    rev, dua = obj.get("rev"), obj.get("docUpdatedAt")
    if isinstance(rev, bool) or not isinstance(rev, int) or rev < 1 or isinstance(dua, bool) or not isinstance(dua, int) or dua < 0:
        raise ApiError("bad_request", "rev・docUpdatedAt が正しくありません", 400)
    out_dir = obj.get("dir")
    if not isinstance(out_dir, str) or not out_dir or len(out_dir) > 1000 or any(ch in out_dir for ch in "\x00\r\n") or not os.path.isabs(out_dir):
        raise ApiError("bad_request", "パックのフォルダ(dir)が正しくありません", 400)
    files = [os.path.basename(str(x))[:200] for x in (obj.get("files") or []) if isinstance(x, str)][:40] if isinstance(obj.get("files"), list) else []
    output = sanitize_pack_output(obj.get("output"))
    with _save_lock:
        read_transcript(tid)
        cur, _broken = read_edit(tid)
        if not cur:
            raise ApiError("no_edit", "カットがまだ保存されていません", 409)
        if rev > cur["rev"]:
            raise ApiError("bad_request", "rev が保存済みのカットより新しくなっています", 400)
        now = int(time.time() * 1000)
        pk = {"rev": rev, "at": now, "docUpdatedAt": dua, "dir": out_dir, "files": files}
        if output is not None:
            pk["output"] = output
        d = dict(cur, packRev=rev, pack=pk)
        atomic_write(edit_path(tid), json.dumps(d, ensure_ascii=False, indent=1).encode("utf-8"))
        return {"ok": True, "packRev": rev, "at": now}


def edit_summary(tid):
    """一覧の各文書の編集・パックの状態(ファイルの更新日時と大きさが同じなら前の結果)。"""
    try:
        st = os.stat(edit_path(tid))
    except OSError:
        _edit_cache.pop(tid, None)
        return {"hasEdit": False, "editRev": 0, "packRev": 0, "_packDocAt": 0, "packAt": 0}
    key = (st.st_mtime_ns, st.st_size)
    hit = _edit_cache.get(tid)
    if hit and hit[0] == key:
        return hit[1]
    d, _broken = read_edit(tid)
    pk = (d or {}).get("pack") or {}
    sm = {"hasEdit": bool(d), "editRev": d["rev"] if d else 0, "packRev": d["packRev"] if d else 0,
          "_packDocAt": pk.get("docUpdatedAt") if isinstance(pk.get("docUpdatedAt"), int) else 0,
          "packAt": pk.get("at") if isinstance(pk.get("at"), int) else 0}
    _edit_cache[tid] = (key, sm)
    return sm


def pack_stale(item):
    """パックを作ったあとにカットか文字が変わったか(一覧と画面の「作り直し」の知らせ。規則はここ1か所)"""
    return bool(item.get("packRev")) and (item.get("editRev") != item.get("packRev") or (item.get("updatedAt") or 0) > (item.get("_packDocAt") or 0))


def doc_has_rows(doc):
    return any(isinstance(s, dict) and str(s.get("text") or "").strip() for s in doc.get("segments") or [])


def fill_doc(spec, fields):
    """文字起こしの結果を、文字起こしの無い文書(intoDoc)に入れる。id・題名・作った日・clip・編集の内容はそのまま。
    -> 入れた文書の id。その間に文書が消えた・行が入った・動画が変わったときは None(呼び出し側が新しい文書にする。結果は捨てない)"""
    tid = spec["intoDoc"]
    with _save_lock:
        try:
            doc = read_transcript(tid)
        except ApiError:
            doc = None
        same = doc is not None and os.path.normcase(os.path.abspath(str(doc.get("sourcePath") or ""))) == os.path.normcase(spec["sourcePath"])
        if not same or doc_has_rows(doc):
            spec.setdefault("warnings", []).append("文字起こしを入れる文書が変わっていたため、新しい文字起こしとして保存しました")
            return None
        doc.update(fields)
        if spec.get("clip") and not doc.get("clip"):
            doc["clip"] = spec["clip"]
        if spec.get("evalSet"):
            doc["evalSet"] = True   # 評価用として文字起こしした(外すのは画面の「評価用にする」)
        apply_edit_cuts(tid, doc)   # 先にカットを決めてあれば、行の「カット済」もそれに合わせる
        atomic_write(tx_path(tid), json.dumps(doc, ensure_ascii=False, indent=1).encode("utf-8"))
        return tid


def probe_media(path):
    """ffmpeg -i で長さと、映像・音声の有無を調べる。-> (長さ秒 または None, 映像あり, 音声あり)。
    カバー画像(音声ファイルに付いた attached pic)は映像に数えない"""
    ff = find_ffmpeg()
    if not ff:
        raise ApiError("no_ffmpeg", "ffmpeg が見つかりません(README の準備手順を確認してください)", 400)
    try:
        p = subprocess.run([ff, "-hide_banner", "-nostdin", "-i", path], stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                           stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace", timeout=30)
    except (OSError, subprocess.SubprocessError):
        return None, False, False
    out = p.stdout or ""
    m = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", out)
    dur = int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3)) if m else None
    streams = [l for l in out.splitlines() if re.match(r"\s*Stream #\d+:\d+", l)]
    has_v = any(": Video:" in l and "attached pic" not in l for l in streams)
    has_a = any(": Audio:" in l for l in streams)
    return dur, has_v, has_a


_open_lock = threading.Lock()


def find_doc_for_media(path):
    """その動画の文書(行のある文書・更新が新しいものを先に)。-> {"id", "rows"} か None。パスを比べるだけで、ファイルには触らない"""
    p = str(path or "").strip().strip('"')
    if not p or "\x00" in p:
        return None
    key = os.path.normcase(os.path.abspath(p))
    best = None
    for tid in _tids():
        sm = transcript_summary(tid)
        if not sm or not sm["_sourcePath"] or os.path.normcase(os.path.abspath(sm["_sourcePath"])) != key:
            continue
        rank = (sm["rows"] > 0, sm.get("updatedAt") or 0)
        if best is None or rank > best[0]:
            best = (rank, {"id": tid, "rows": sm["rows"]})
    return best[1] if best else None


def open_video(req):
    """POST /api/open-video {"path", "title"?} -> {"id", "created", "warnings"}。「文字起こしせずに開く」: 動画のパスだけで文書を作る。
    同じ動画の文書があればそれを返す(行のある文書・新しいものを先に)。隣の .clip.json があれば文書の clip に入れる(スタジオの切り抜きと紐づく)。
    文書にした動画は /media で配るので、動画・音声の拡張子で、ffmpeg で映像か音声が読めるものだけ受け付ける"""
    src = check_source(req.get("path"))
    with _open_lock:   # 同じ動画を続けて2回開いても、文書を2つ作らない
        hit = find_doc_for_media(src)
        if hit:
            return {"id": hit["id"], "created": False, "warnings": []}
        dur, has_v, has_a = probe_media(src)
        if not (has_v or has_a):
            raise ApiError("bad_media", "動画・音声として読めませんでした(壊れているか、対応していない形式です)", 400)
        pm = pio(required=False)
        clip, warn, _cp = pm.find_clip(src, dur) if pm else (None, None, None)
        tid = uuid.uuid4().hex[:12]
        now = int(time.time() * 1000)
        doc = {"schema": "transcribe/v1", "id": tid, "title": str(req.get("title") or "").strip()[:120] or os.path.splitext(os.path.basename(src))[0][:120],
               "sourcePath": src, "sourceName": os.path.basename(src), "start": 0, "end": round(dur, 2) if dur else None, "whole": True,
               "duration": dur, "model": "", "language": "", "params": {}, "speakers": [], "segments": [], "original": [],
               "createdAt": now, "updatedAt": now}
        if clip:
            doc["clip"] = clip
        with _save_lock:
            atomic_write(tx_path(tid), json.dumps(doc, ensure_ascii=False, indent=1).encode("utf-8"))
    log.info("文字起こしせずに開く: %s", os.path.basename(src))
    return {"id": tid, "created": True, "warnings": [warn] if warn else []}


# ---------- 動画を選び直す(付け替え。全体の計画の段2 B-4・監査 19。docs/plan/phase2-data-safety.md の 1) ----------
# 動画を移した・改名した文書の sourcePath を、行・校正・話者・カットを残したまま新しいパスに直す。
# 選べる場所は「このパソコンのドライブならどこでも」(ユーザー決定 2026-09-29)。ネットワーク上・ツールの作業データの中・リンクの先がそれらになるものは断る。
# URL の引数では付け替えない(POST + 合言葉 + Origin 検査だけ)。候補の自動の推測はしない
RELINK_KEEP = 10          # 文書に残す付け替えの記録(relinks)の数
RELINK_TOL_SEC = 1.0      # 動画全体の文書: 長さの差がこれ(か 0.5%)以下なら同じ動画とみなす
RELINK_TOL_RATIO = 0.005
RELINK_RANGE_TOL = 0.5    # 範囲の文書: 新しい動画の長さ ≥ 範囲の終わり − これ


def _remote_drive(p):
    """Windows のネットワークドライブ(net use で割り当てた Z: など)か。ドライブの種類を聞くだけで、ファイルには触らない"""
    if os.name != "nt":
        return False
    drive = os.path.splitdrive(p)[0]
    if len(drive) != 2 or drive[1] != ":":
        return False
    try:
        import ctypes
        return ctypes.windll.kernel32.GetDriveTypeW(drive + "\\") == 4   # DRIVE_REMOTE
    except (AttributeError, OSError, ValueError):
        return False


def _inside(p, folder):
    try:
        a, b = os.path.normcase(os.path.realpath(p)), os.path.normcase(os.path.realpath(folder))
    except (OSError, ValueError):
        return False
    return a == b or a.startswith(b.rstrip("\\/") + os.sep)


def relink_path(raw):
    """付け替え先のパスの検査。ネットワーク上のパスは、ファイルに触る前に断る(存在を確かめるだけで資格情報を送るため)。
    ジャンクション・リンクを解いた先でも、もう一度 ネットワーク・「:」(NTFS の代替ストリーム)・拡張子・作業データの中 を確かめる。-> 実体のパス"""
    s = str(raw or "").strip().strip('"').strip()
    if not s or len(s) > 1000 or any(ch in s for ch in "\x00\r\n"):
        raise ApiError("bad_path", "パスを入れてください", 400)
    if _fsio.is_network_path(s):
        raise ApiError("network_path", "ネットワーク上のファイルは選べません(このパソコンにコピーしてから選んでください)", 400)
    if not os.path.isabs(s):
        raise ApiError("bad_path", "ドライブから始まるパス(例: D:\\動画\\配信.mp4)を入れてください", 400)
    p = os.path.abspath(s)
    for resolved in (False, True):
        if resolved:   # 1回目の検査を通ってから(ネットワーク上のパスには触らない)リンクを解く
            try:
                p = os.path.realpath(p)
            except (OSError, ValueError):
                raise ApiError("no_file", "ファイルが見つかりません(パスを確認してください)", 400)
        if _fsio.is_network_path(p) or _remote_drive(p):
            raise ApiError("network_path", "ネットワーク上のファイルは選べません(このパソコンにコピーしてから選んでください)", 400)
        if ":" in os.path.splitdrive(p)[1]:
            raise ApiError("bad_path", "パスに「:」が入っています(ファイルそのもののパスを入れてください)", 400)
        if os.path.splitext(p)[1].lower() not in MEDIA_TYPES:
            raise ApiError("bad_ext", "動画・音声ファイルではないようです(対応: %s)" % " ".join(sorted(MEDIA_TYPES)), 400)
        if _inside(p, DATA_DIR):   # このツールの作業データ(文書・設定・保管)。スタジオの既定の書き出し先(作業データの studio\exports)は選べる
            raise ApiError("bad_path", "このツールの作業データの中のファイルは選べません", 400)
    if not os.path.isfile(p):
        raise ApiError("no_file", "ファイルが見つかりません(パスを確認してください)", 400)
    return p


def _relink_ref(doc):
    """比べる長さ。-> (長さ秒 または None, 動画全体の文書か)。動画全体の文書は記録した長さ、範囲の文書は範囲の終わり(無ければ最後の行の終わり)"""
    dur, end = num(doc.get("duration")), num(doc.get("end"))
    if doc.get("whole") is not False and dur and dur > 0:
        return dur, True
    if end and end > 0:
        return end, False
    ends = [num(s.get("end"), 0.0) or 0.0 for s in doc.get("segments") or [] if isinstance(s, dict)]
    return (max(ends), False) if ends and max(ends) > 0 else (None, False)


def relink_check(obj):
    """POST /api/relink/check {"id", "path"}: 付け替える前の確認(書き込まない)。
    -> {path, name, durationSec, fps, hasVideo, docDuration, diffSec, mismatch, sameAsNow, usedBy: [{id, title}], rowsAfterEnd, warnings}。
    fps・長さはカットのタブと同じ測り方(resolve_export.edit_draft。音声だけのファイルは ffmpeg の長さ)"""
    import resolve_export
    tid = str(obj.get("id") or "")
    doc = read_transcript(tid)
    p = relink_path(obj.get("path"))
    dur, has_v, has_a = probe_media(p)
    if not (has_v or has_a):
        raise ApiError("bad_media", "動画・音声として読めませんでした(壊れているか、対応していない形式です)", 400)
    fps, warnings = None, []
    if has_v:
        try:
            dr = resolve_export.edit_draft(dict(doc, sourcePath=p), SERVER_VERSION, rows=False)
            fps, dur = dr["fps"], dr["durationSec"]
        except resolve_export.ResolveExportError as e:
            warnings.append("fps を調べられませんでした(%s)。カットのタブで使えない可能性があります" % str(e)[:200])
    else:
        warnings.append("映像の無いファイル(音声だけ)です。文字の直しはできますが、カットとパックには使えません")
    if not dur or dur <= 0:
        raise ApiError("bad_media", "動画の長さを読めませんでした(壊れているか、対応していない形式です)", 400)
    ref, whole = _relink_ref(doc)
    diff = round(dur - ref, 2) if ref else None
    if ref is None:
        mismatch = False
        warnings.append("この文書には元の長さの記録が無いため、長さを比べられません")
    elif whole:
        mismatch = abs(dur - ref) > max(RELINK_TOL_SEC, RELINK_TOL_RATIO * ref)
    else:
        mismatch = dur < ref - RELINK_RANGE_TOL
    if mismatch:
        warnings.append("長さが元の動画と違います(元 %s・選んだ動画 %s)。別の動画の可能性があります" % (fmt_hms(ref), fmt_hms(dur)))
    after = sum(1 for s in doc.get("segments") or [] if isinstance(s, dict) and (num(s.get("start"), 0.0) or 0.0) >= dur)
    if after:
        warnings.append("選んだ動画の終わりより後ろに %d 行あります(その行は再生できません)" % after)
    key = os.path.normcase(p)
    used = []
    for other in _tids():
        if other == tid:
            continue
        sm = transcript_summary(other)
        if sm and sm["_sourcePath"] and not _fsio.is_network_path(sm["_sourcePath"]) \
                and os.path.normcase(os.path.abspath(sm["_sourcePath"])) == key:
            used.append({"id": other, "title": str(sm.get("title") or "")[:120]})
            if len(used) >= 10:
                break
    cur = str(doc.get("sourcePath") or "")
    same = bool(cur) and not _fsio.is_network_path(cur) and os.path.normcase(os.path.abspath(cur)) == key
    return {"path": p, "name": os.path.basename(p), "durationSec": round(dur, 3), "fps": fps, "hasVideo": bool(has_v),
            "docDuration": round(ref, 3) if ref else None, "diffSec": diff, "mismatch": mismatch, "sameAsNow": same,
            "usedBy": used, "rowsAfterEnd": after, "warnings": warnings}


def _doc_busy(tid):
    """その文書を読み書きするジョブ(話者判別・再認識・声を覚える・比較・この文書に入れる文字起こし)が動いているか"""
    with _jobs_lock:
        return any(j["state"] in ACTIVE_STATES and (j.get("tid") == tid or (j.get("spec") or {}).get("tid") == tid
                                                    or (j.get("spec") or {}).get("intoDoc") == tid) for j in _jobs.values())


def relink_doc(obj):
    """POST /api/relink {"id", "path", "baseUpdatedAt", "acceptDiff"}: 文書の動画を付け替える。
    書き換えるのは sourcePath・sourceName・updatedAt と記録 relinks だけ(行・校正・話者・original・clip・start/end・カットは変えない。
    カットは秒で持っているので、fps が違っても読み込むときに合わせ直る)。書く前に .bak/<id>.pre-relink.json・履歴・.bak/<id>.edit.pre-relink.json を残す。
    409: 先に更新された(conflict)・ジョブの最中(busy)・長さが違うのに acceptDiff が無い(duration_mismatch)"""
    tid = str(obj.get("id") or "")
    base = obj.get("baseUpdatedAt")
    if isinstance(base, bool) or not isinstance(base, int):
        raise ApiError("bad_request", "baseUpdatedAt(読み込んだときの更新日時)を付けてください", 400)
    chk = relink_check(obj)   # 動画を調べるのは時間がかかるので、ロックの外で
    if chk["sameAsNow"]:
        raise ApiError("same_path", "今と同じ動画です(付け替える必要はありません)", 400)
    with _save_lock:
        doc = read_transcript(tid)
        if doc.get("updatedAt") and base != doc.get("updatedAt"):
            raise ApiError("conflict", "別の場所で先に更新されています。読み込み直してから、もう一度選んでください", 409)
        if _doc_busy(tid):
            raise ApiError("busy", "この文書は、いま別の処理(文字起こし・話者判別・再認識など)の最中です。終わってから付け替えてください", 409)
        if chk["mismatch"] and obj.get("acceptDiff") is not True:
            raise ApiError("duration_mismatch", "長さが元の動画と違います。別の動画でないか確かめてから付け替えてください", 409, {"check": chk})
        bak = os.path.join(TX_DIR, ".bak")
        os.makedirs(bak, exist_ok=True)
        shutil.copy2(tx_path(tid), os.path.join(bak, tid + ".pre-relink.json"))   # 直前の状態を1世代だけ(話者判別の pre-diarize と同じ)
        if os.path.isfile(edit_path(tid)):
            shutil.copy2(edit_path(tid), os.path.join(bak, tid + ".edit.pre-relink.json"))
        try:
            hist_snapshot(tid, force=True)   # 「以前の版に戻す」で元のパスへ戻せる
        except OSError:
            pass
        now = max(int(time.time() * 1000), int(doc.get("updatedAt") or 0) + 1)
        prev = [r for r in doc.get("relinks") or [] if isinstance(r, dict)]
        doc["relinks"] = (prev + [{"from": str(doc.get("sourcePath") or ""), "at": now, "diffSec": chk["diffSec"]}])[-RELINK_KEEP:]
        doc.update({"sourcePath": chk["path"], "sourceName": chk["name"], "updatedAt": now})
        apply_edit_cuts(tid, doc)
        atomic_write(tx_path(tid), json.dumps(doc, ensure_ascii=False, indent=1).encode("utf-8"))
    log.info("動画を付け替え: %s → %s", tid, chk["name"])
    return {"ok": True, "updatedAt": now, "sourcePath": chk["path"], "sourceName": chk["name"], "warnings": chk["warnings"]}


# ---------- まとめて付け替える・「参照…」(2026-10-01。ユーザー決定: 参照の窓 + 履歴からまとめて) ----------
# 付け替えそのものは1件ずつ /api/relink(控え・長さの確認・競合の確認を同じにするため)。ここは候補を集めるだけで、書き込まない。
# 「候補の自動の推測はしない」(段2 B-4)を、ユーザーが選んだフォルダの中の「同じファイル名」に限って緩めた。候補を選んでも、
# 長さを確かめて画面で選んだものだけを付け替える(長さが違うものは既定で選ばない)
FIND_BUDGET_SEC = 8.0     # フォルダを探す時間の上限(ドライブ全体を選ばれても固まらない)
FIND_MAX_ENTRIES = 50000  # 見るファイルとフォルダの数の上限
FIND_MAX_DEPTH = 6        # 選んだフォルダから下へ何段まで
FIND_PER_DOC = 5          # 1文書あたりの候補の数
_FIND_SKIP = {"$recycle.bin", "system volume information", "windows", "program files", "program files (x86)", "programdata", "appdata"}


def relink_missing():
    """POST /api/relink/missing: 元の動画が見つからない文書(パスの記録があるものだけ)。
    -> {items: [{id, title, sourcePath, sourceName, updatedAt}], skipped}。ネットワーク上のパスは調べない(skipped に数える)"""
    items, skipped, dirs = [], 0, {}
    for tid in _tids():
        sm = transcript_summary(tid)
        sp = str((sm or {}).get("_sourcePath") or "")
        if not sp:
            continue
        if _fsio.is_network_path(sp) or not os.path.isabs(sp):
            skipped += 1
            continue
        folder = os.path.dirname(sp)
        try:
            if folder not in dirs:
                dirs[folder] = os.path.isdir(folder)
            ok = dirs[folder] and os.path.isfile(sp)
        except (OSError, ValueError):
            ok = False
        if not ok:
            items.append({"id": tid, "title": str(sm.get("title") or "")[:200], "sourcePath": sp,
                          "sourceName": str(sm.get("sourceName") or os.path.basename(sp))[:260], "updatedAt": sm.get("updatedAt") or 0})
    items.sort(key=lambda x: -(x["updatedAt"] or 0))
    return {"items": items, "skipped": skipped}


def relink_folder(raw):
    """探すフォルダの検査(relink_path と同じ考え: ネットワークはフォルダに触る前に断る → リンクを解いてもう一度)。-> 実体のパス"""
    s = str(raw or "").strip().strip('"').strip()
    if not s or len(s) > 1000 or any(ch in s for ch in "\x00\r\n"):
        raise ApiError("bad_path", "フォルダのパスを入れてください", 400)
    net = ApiError("network_path", "ネットワーク上のフォルダは選べません", 400)
    if _fsio.is_network_path(s):
        raise net
    if not os.path.isabs(s):
        raise ApiError("bad_path", "ドライブから始まるパス(例: D:\\動画)を入れてください", 400)
    p = os.path.abspath(s)
    if _remote_drive(p):
        raise net
    try:
        p = os.path.realpath(p)
    except (OSError, ValueError):
        raise ApiError("no_dir", "フォルダが見つかりません", 400)
    if _fsio.is_network_path(p) or _remote_drive(p):
        raise net
    if ":" in os.path.splitdrive(p)[1]:
        raise ApiError("bad_path", "パスに「:」が入っています", 400)
    if not os.path.isdir(p):
        raise ApiError("no_dir", "フォルダが見つかりません(パスを確認してください)", 400)
    if _inside(p, DATA_DIR):
        raise ApiError("bad_path", "このツールの作業データの中は探せません", 400)
    return p


def relink_find(obj):
    """POST /api/relink/find {"folder", "ids"}: 選んだフォルダ(とその下)から、各文書の元の動画と同じファイル名(大文字小文字は区別しない)の動画を探す。
    -> {folder, candidates: {id: [path, …]}, scanned, truncated}。時間・数・深さに上限があり、超えたら truncated"""
    root = relink_folder(obj.get("folder"))
    want = {}
    for tid in [str(x) for x in (obj.get("ids") or [])][:500]:
        if not TID_RE.match(tid):
            continue
        sm = transcript_summary(tid)
        name = re.split(r"[\\/]", str((sm or {}).get("_sourcePath") or ""))[-1] or str((sm or {}).get("sourceName") or "")
        if name and os.path.splitext(name)[1].lower() in MEDIA_TYPES:
            want.setdefault(os.path.normcase(name), []).append(tid)
    found = {k: [] for k in want}
    t0, seen, truncated = time.monotonic(), 0, False
    base_depth = root.rstrip("\\/").count(os.sep)
    for cur, dnames, fnames in os.walk(root):   # リンクは辿らない(followlinks=False)
        seen += len(dnames) + len(fnames)
        if seen > FIND_MAX_ENTRIES or time.monotonic() - t0 > FIND_BUDGET_SEC:
            truncated = True
            break
        for fn in fnames:
            k = os.path.normcase(fn)
            if k in found and len(found[k]) < FIND_PER_DOC:
                found[k].append(os.path.join(cur, fn))
        if cur.rstrip("\\/").count(os.sep) - base_depth >= FIND_MAX_DEPTH:
            if dnames:
                truncated = True
            dnames[:] = []
        else:
            dnames[:] = sorted(d for d in dnames if not d.startswith(".") and d.lower() not in _FIND_SKIP
                               and not _inside(os.path.join(cur, d), DATA_DIR))
    cands = {tid: found[k] for k, tids in want.items() for tid in tids if found[k]}
    return {"folder": root, "candidates": cands, "scanned": seen, "truncated": truncated}


def pick_path(obj):
    """POST /api/pick {"kind": "file"|"dir", "hint"}: PC の標準の窓で動画かフォルダを選ぶ(ytt_core/pick.py)。
    -> {path}(やめたら "")。選んだ動画の検査は、そのあとの /api/relink/check と /api/relink/find が行う"""
    from ytt_core import pick as _pick
    kind = "dir" if obj.get("kind") == "dir" else "file"
    try:
        p = _pick.pick(kind, "動画のあるフォルダを選ぶ" if kind == "dir" else "動画を選ぶ", obj.get("hint") or "", MEDIA_TYPES)
    except _pick.PickBusy as e:
        raise ApiError("pick_busy", str(e), 409)
    except _pick.PickError as e:
        raise ApiError("pick_unavailable", "%s。パスを貼り付けてください" % e, 400)
    return {"path": p}


# ---------- 音の波形(カットのタイムライン用。docs/design/edit-tool-design.md の 5・8) ----------
# ffmpeg で 8kHz・モノラルの 16bit にして、区切りごとの最大の振れ幅を 0〜255(平方根で小さい声も見えるように)の1バイトに。
# numpy は使わない(サーバーのプロセスで読み込まない決まり)。重い処理なので ytt_core.jobs.SLOTS を通し、画面は 202 の間くり返し問い合わせる
PEAKS_VERSION = 1
PEAKS_SR = 8000
PEAKS_TIMEOUT = 600
_peaks_tasks = {}   # 鍵 -> {"sig", "state": waiting|running|done|error, "message", "code", "at"}
_peaks_lock = threading.Lock()
_PEAK_LUT = None


def peaks_rate(duration):
    """1秒あたりの数。長い動画は下げる(10分まで 100 = 10ミリ秒ごと、1時間まで 50、それより長いと 20)"""
    d = duration or 0
    return 100 if d <= 600 else 50 if d <= 3600 else 20


def _peaks_files(path):
    h = hashlib.sha1(os.path.normcase(path).encode("utf-8", "surrogatepass")).hexdigest()[:24]
    d = os.path.join(DATA_DIR, "cache", "peaks")
    return d, os.path.join(d, h + ".bin"), os.path.join(d, h + ".json")


def compute_peaks(path, task=None):
    """-> (波形のバイト列, 1秒あたりの数, 長さ秒)。音声が無ければ空のバイト列"""
    global _PEAK_LUT
    ff = find_ffmpeg()
    if not ff:
        raise ApiError("no_ffmpeg", "ffmpeg が見つかりません(README の準備手順を確認してください)", 400)
    dur, _has_v, has_a = probe_media(path)
    rate = peaks_rate(dur)
    if not has_a:
        return b"", rate, dur or 0.0
    if _PEAK_LUT is None:
        _PEAK_LUT = bytes(min(255, int(255 * math.sqrt(v / 32768.0) + 0.5)) for v in range(32769))
    lut, step = _PEAK_LUT, PEAKS_SR // rate
    cmd = [ff, "-hide_banner", "-nostdin", "-loglevel", "error", "-protocol_whitelist", "file", "-i", path,
           "-vn", "-ac", "1", "-ar", str(PEAKS_SR), "-f", "s16le", "-acodec", "pcm_s16le", "-"]
    p = subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    err = []
    drain = threading.Thread(target=lambda: err.append(p.stderr.read()[-2000:]), daemon=True)   # エラーの出力でパイプが詰まらないように
    drain.start()
    timer = threading.Timer(PEAKS_TIMEOUT, p.kill)
    timer.start()
    out, buf = bytearray(), b""
    try:
        while True:
            chunk = p.stdout.read(step * 2 * 2000)
            if not chunk:
                break
            buf += chunk
            usable = len(buf) - len(buf) % (step * 2)
            a = array.array("h")
            a.frombytes(buf[:usable])
            buf = buf[usable:]
            if sys.byteorder == "big":
                a.byteswap()
            for i in range(0, len(a), step):
                seg = a[i:i + step]
                out.append(lut[min(32768, max(max(seg), -min(seg)))])
        if len(buf) >= 2:
            a = array.array("h")
            a.frombytes(buf[:len(buf) - len(buf) % 2])
            if sys.byteorder == "big":
                a.byteswap()
            out.append(lut[min(32768, max(max(a), -min(a)))])
        p.wait()
    finally:
        timer.cancel()
        if p.poll() is None:
            p.kill()
            p.wait()
        p.stdout.close()
        drain.join(5)
        p.stderr.close()
    if p.returncode != 0 and not out:
        tail = (err[0] if err else b"").decode("utf-8", "replace").strip().splitlines()[-1:] or [""]
        raise ApiError("peaks_failed", "音の波形を作れませんでした: " + tail[0][:200], 500)
    return bytes(out), rate, dur or len(out) / rate


def _peaks_run(key, path, sig, t):
    try:
        with _heavy.SLOTS.slot(TOOL_ID, "波形 " + os.path.basename(path)[:40],
                               on_wait=lambda: t.update(state="waiting", message=_heavy.WAIT_MESSAGE)):
            t.update(state="running", message="音の波形を作っています")
            data, rate, dur = compute_peaks(path)
        d, bin_p, meta_p = _peaks_files(path)
        os.makedirs(d, exist_ok=True)
        atomic_write(bin_p, data)
        atomic_write(meta_p, json.dumps({"sig": sig, "rate": rate, "duration": round(dur, 3), "n": len(data)}).encode("utf-8"))
        t.update(state="done", message="", at=time.time())
    except ApiError as e:
        t.update(state="error", code=e.code, message=e.message, at=time.time())
    except Exception as e:   # 想定外でもサーバーは止めない
        log.exception("波形の作成で例外")
        t.update(state="error", code="internal", message="内部エラー: %s %s" % (e.__class__.__name__, str(e)[:200]), at=time.time())


def get_peaks(tid):
    """GET /api/peaks?id= -> ("ready", バイト列, 1秒あたりの数, 長さ) か ("busy", {"state", "message"})。
    動画のパスは文書から取る(パスを引数で受けない)。作業データの cache/peaks/ に保存し、動画のパス・大きさ・更新日時が同じなら使い回す"""
    doc = read_transcript(tid)
    try:
        path = check_source(doc.get("sourcePath"))
        st = os.stat(path)
    except (ApiError, OSError):
        raise ApiError("source_missing", "元の動画・音声が見つかりません(移動・削除した可能性があります)", 404)
    sig = [os.path.normcase(path), st.st_size, st.st_mtime_ns, PEAKS_VERSION]
    _d, bin_p, meta_p = _peaks_files(path)
    meta = _read_json_file(meta_p)
    if isinstance(meta, dict) and meta.get("sig") == sig:
        try:
            with open(bin_p, "rb") as f:
                data = f.read()
            if len(data) == meta.get("n"):
                return "ready", data, meta["rate"], meta["duration"]
        except OSError:
            pass
    key = sig[0]
    with _peaks_lock:
        t = _peaks_tasks.get(key)
        if t and t["sig"] == sig and t["state"] in ("waiting", "running"):
            return "busy", {"state": t["state"], "message": t["message"]}
        if t and t["sig"] == sig and t["state"] == "error" and time.time() - t["at"] < 30:
            raise ApiError(t["code"], t["message"], 500 if t["code"] == "internal" else 400)
        t = {"sig": sig, "state": "waiting", "message": "音の波形を作る準備をしています", "code": "", "at": time.time()}
        _peaks_tasks[key] = t
        for k in [k for k, v in _peaks_tasks.items() if v["state"] in ("done", "error") and time.time() - v["at"] > 600]:
            _peaks_tasks.pop(k, None)
    threading.Thread(target=_peaks_run, args=(key, path, sig, t), daemon=True, name="peaks").start()
    return "busy", {"state": t["state"], "message": t["message"]}


# ---------- ジョブ ----------
_jobs = {}
_order = []
_jobs_lock = threading.Lock()
_queue = queue.PriorityQueue()   # (優先度, 通し番号, jid)。話者判別は文字起こしの待機列を追い越せるよう優先度を分ける(実行中のジョブを中断はしない。次の空きで割り込む)
_seq_counter = itertools.count()
JOB_PRIORITY = {"diarize": 0}   # 未指定(transcribe/retranscribe/abtest 等)は既定の1。数値が小さいほど先に実行
_models = {}
_model_lock = threading.Lock()
_model_used = [0.0]   # 最後にモデルを使った時刻(ジョブの終わりにも更新する)
try:
    MODEL_IDLE_SEC = max(0, int(os.environ.get("TRANSCRIBE_MODEL_IDLE_SEC", "900")))
except ValueError:
    MODEL_IDLE_SEC = 900
# 読み込んだモデル(large-v3 で数GB)は次のジョブのために残すが、この秒数ジョブが無ければ手放す(0 = 手放さない)。
# 画面を開いたまま他の作業(動画編集など)をするときにメモリを返すため。次の文字起こしでは読み込み直し(10〜30秒程度)が入る。


def release_idle_models(now=None):
    """しばらく使っていないモデルを手放す。ワーカー(ジョブを実行するスレッド)がジョブの合間にだけ呼ぶので、使用中のモデルは消さない。
    サーバーのプロセスでは、認識ワーカー(別プロセス)ごと終わらせる(モデルのメモリを OS に確実に返す)。次のジョブで起動し直す。"""
    if MODEL_IDLE_SEC <= 0:
        return False
    now = time.time() if now is None else now
    if not IN_WORKER:
        return WORKER.stop_if_idle(MODEL_IDLE_SEC, now)
    with _model_lock:
        if not _models or now - _model_used[0] < MODEL_IDLE_SEC:
            return False
        log.info("しばらく使っていないモデルを解放: %s(メモリ %s)", ", ".join("%s/%s" % k for k in _models), _mem())
        _models.clear()
    gc.collect()
    return True


class Cancelled(Exception):
    pass


# ---------- 認識ワーカー(別プロセス。統合計画の段階3-3) ----------
# faster-whisper(ctranslate2)と sherpa-onnx はネイティブコードで、メモリ不足・GPU のドライバなどで Python ごと落ちることがある。
# 入口の統合サーバーに取り込むと、同じプロセスにスタジオ・cut2resolve もいるので、落ちると全部が止まり編集中の内容が消える。
# そこで、モデルの読み込み・認識・話者判別だけを tx_worker.py(別プロセス)で行う。サーバー側のジョブの流れ(待機列・行の整形・保存)は変えない。
# やり取り: ワーカーの標準入力に要求を1行1件の JSON(ASCII)で送り、標準出力から途中経過・結果を1行1件で受け取る。1度に1つの要求だけ。
# 落ちたら(標準出力が閉じたら)そのジョブを「失敗」にし、次の要求でワーカーを起動し直す。しばらく使わなければワーカーごと終わらせてメモリを返す。
IN_WORKER = False   # tx_worker.py の中で True にする(そのときは load_model などが本体をその場で実行する)
WORKER_SCRIPT = os.path.join(ROOT, "tx_worker.py")
WORKER_LOG = os.path.join(DATA_DIR, "worker.log")
WORKER_LOG_MAX = 1024 * 1024
WORKER_CANCEL_GRACE = 15   # 取り消してから、この秒数で止まらなければワーカーを強制終了する
WORKER_SILENCE_TIMEOUT = 20 * 60   # ワーカーから何も届かない時間の上限(秒)。超えたら強制終了してそのジョブを失敗にする(黙ったワーカーを待ち続けて SLOTS を持ったまま他のツールを塞がない。夜間の見直し 高。2026-10-01 ユーザー決定)
WORKER_LINE_MAX = 8 * 1024 * 1024


def _worker_flags():
    """Windows: 黒い画面を増やさない・Ctrl+C / Ctrl+Break がワーカーに直接届かないようにする(終わらせるのは親の役目)。"""
    if os.name != "nt":
        return 0
    return getattr(subprocess, "CREATE_NO_WINDOW", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)


def worker_env():
    env = dict(os.environ)
    env["PYTHONUNBUFFERED"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    import ytt_core as _yc   # ワーカーも同じ ytt_core を使う(一時フォルダに写したテストでも見つかるように)
    env["YTT_CORE_DIR"] = os.path.dirname(os.path.dirname(os.path.abspath(_yc.__file__)))
    return env


class WorkerError(Exception):
    """ワーカーの中で起きた想定外の例外(元の型の名前を message に含める)。"""


class _CancelHandle:
    """job["proc"] に入れる、取り消し用の窓口。cancel_job() は proc.poll() / proc.terminate() を呼ぶので、同じ形にする
    (ffmpeg の子プロセスを止めるのと同じ仕組みで、ワーカーの処理も止められる)。"""

    def __init__(self, client, rid):
        self.client, self.rid, self.done = client, rid, False

    def poll(self):
        return 0 if self.done else None

    def terminate(self):
        if not self.done:
            self.client.cancel(self.rid)

    kill = terminate


class WorkerClient:
    """認識ワーカー(tx_worker.py)の起動・要求・取り消し・強制終了。要求は1度に1つ(ジョブを実行するスレッドは1本)。"""

    def __init__(self):
        self.lock = threading.RLock()     # 要求の直列化
        self.wlock = threading.Lock()     # 標準入力への書き込み(取り消しは HTTP のスレッドからも来る)
        self.proc = None
        self.log_fp = None
        self.rids = itertools.count(1)
        self.last_used = 0.0
        self.starts = 0
        self.killed_rid = None            # 取り消しで強制終了した要求(その要求は「中止」にする)
        self.closed = False
        self.q = queue.Queue()            # ワーカーの標準出力の行(読み取り専用のスレッドが入れる。待つ側は get(timeout) で時限を付ける)

    # ---- 起動・終了
    def alive(self):
        return self.proc is not None and self.proc.poll() is None

    def _spawn(self):
        if self.closed:
            raise ApiError("stopping", "終了処理中のため、文字起こしを始められません", 503)
        if not os.path.isfile(WORKER_SCRIPT):
            raise ApiError("missing_module", "tx_worker.py が見つかりません。ツールのフォルダの中身をまとめて更新してください", 500)
        try:
            if os.path.exists(WORKER_LOG) and os.path.getsize(WORKER_LOG) > WORKER_LOG_MAX:
                replace_retry(WORKER_LOG, WORKER_LOG + ".old")
        except OSError:
            pass
        try:
            self.log_fp = open(WORKER_LOG, "ab")
        except OSError:
            self.log_fp = None
        self.proc = subprocess.Popen([worker_python(), "-u", WORKER_SCRIPT], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                     stderr=self.log_fp or subprocess.DEVNULL, cwd=ROOT, env=worker_env(), creationflags=_worker_flags())
        self.starts += 1
        self.q = queue.Queue()   # 起動ごとに新しい列(前のプロセスの読み残しを混ぜない)
        threading.Thread(target=self._reader, args=(self.proc, self.q), daemon=True, name="tx-worker-reader").start()
        log.info("認識ワーカーを起動 pid=%s(%d回目)", self.proc.pid, self.starts)

    @staticmethod
    def _reader(p, q):
        """ワーカーの標準出力を読む専用のスレッド。readline 自体は止められないので、待つ側(_read)を queue.get(timeout) にして時限を付ける。
        EOF(b"")か、閉じられて読めなくなったら b"" を入れて終わる"""
        try:
            while True:
                line = p.stdout.readline(WORKER_LINE_MAX)
                q.put(line)
                if not line:
                    return
        except (OSError, ValueError):
            q.put(b"")

    def _ensure(self):
        if self.proc is not None and self.proc.poll() is not None:
            log.warning("認識ワーカーが終わっていました(終了コード %s)。起動し直します", self.proc.returncode)
            self._reap()
        if self.proc is None:
            self._spawn()

    def _reap(self):
        p, self.proc = self.proc, None
        if p is not None:
            for f in (p.stdin, p.stdout):
                try:
                    f.close()
                except (OSError, ValueError):
                    pass
            try:
                p.wait(5)
            except subprocess.TimeoutExpired:
                pass
        if self.log_fp is not None:
            try:
                self.log_fp.close()
            except OSError:
                pass
            self.log_fp = None

    def kill(self):
        p = self.proc
        if p is not None and p.poll() is None:
            try:
                p.kill()
            except OSError:
                pass

    def stop(self, timeout=5):
        """ワーカーを終わらせる(次の要求で起動し直す)。要求の途中なら、その要求は失敗・中止になる。"""
        p = self.proc
        if p is None:
            return
        if p.poll() is None:
            try:
                with self.wlock:
                    p.stdin.write(b'{"op":"quit"}\n')
                    p.stdin.flush()
            except (OSError, ValueError):
                pass
            try:
                p.wait(timeout)
            except subprocess.TimeoutExpired:
                self.kill()
        if self.lock.acquire(timeout=timeout):
            try:
                if self.proc is p:
                    self._reap()
            finally:
                self.lock.release()

    def close(self):
        """サーバーの終了時。以後は起動しない。"""
        self.closed = True
        self.stop(3)

    def stop_if_idle(self, idle_sec, now=None):
        now = time.time() if now is None else now
        if not self.alive() or now - self.last_used < idle_sec:
            return False
        if not self.lock.acquire(blocking=False):   # 要求の途中(使用中)
            return False
        try:
            log.info("しばらく使っていないので認識ワーカーを終了(モデルのメモリを返す)")
            self.stop()
            return True
        finally:
            self.lock.release()

    # ---- やり取り
    def _write(self, obj):
        data = (json.dumps(obj, ensure_ascii=True, separators=(",", ":")) + "\n").encode("ascii")
        with self.wlock:
            self.proc.stdin.write(data)
            self.proc.stdin.flush()

    def cancel(self, rid):
        """取り消し(HTTP のスレッドから)。ワーカーに伝え、WORKER_CANCEL_GRACE 秒で止まらなければ強制終了する。"""
        p = self.proc
        if p is None or p.poll() is not None:
            return
        try:
            self._write({"op": "cancel", "rid": rid})
        except (OSError, ValueError):
            pass

        def force():
            if self.proc is p and p.poll() is None and self._busy_rid == rid:
                log.warning("認識ワーカーが取り消しに応じないため強制終了します")
                self.killed_rid = rid
                self.kill()
        t = threading.Timer(WORKER_CANCEL_GRACE, force)
        t.daemon = True
        t.start()

    _busy_rid = None

    def _read(self, rid):
        try:
            line = self.q.get(timeout=WORKER_SILENCE_TIMEOUT)
        except queue.Empty:   # 黙ったワーカー(ネイティブの部品で止まった・デッドロック)。待ち続けると SLOTS を持ったまま他のツールの重い処理まで塞ぐので、強制終了して失敗にする
            log.error("認識ワーカーから %.0f 秒なにも届かないため強制終了します", WORKER_SILENCE_TIMEOUT)
            self.kill()
            self._reap()
            if self.killed_rid == rid:
                raise Cancelled()
            raise ApiError("worker_hung", "文字起こしの部品(認識を行う別プロセス)が %d 分なにも応答しないため止めました。もう一度実行すると部品を起動し直します"
                                          "(モデルの初回のダウンロード中に出たときは、そのままもう一度実行してください。詳しくは worker.log)" % max(1, round(WORKER_SILENCE_TIMEOUT / 60)), 500)
        if not line:
            code = None
            try:
                code = self.proc.wait(5)
            except subprocess.TimeoutExpired:
                self.kill()
            self._reap()
            if self.killed_rid == rid:
                raise Cancelled()
            log.error("認識ワーカーが異常終了しました(終了コード %s)", code)
            raise ApiError("worker_crashed", "文字起こしの部品(認識を行う別プロセス)が途中で止まりました(終了コード %s)。"
                                             "メモリ不足などが考えられます。もう一度実行すると部品を起動し直します(詳しくは worker.log)" % code, 500)
        try:
            m = json.loads(line.decode("utf-8"))
        except (UnicodeDecodeError, ValueError):
            log.warning("認識ワーカーの出力を読めません: %r", line[:200])
            return None
        return m if isinstance(m, dict) else None

    @staticmethod
    def _apply(job, m):
        k = m.get("k")
        if isinstance(job, dict) and k in ("phase", "state", "device", "progress"):
            v = m.get("v")
            if k == "progress":
                try:
                    v = max(0.0, min(0.99, float(v)))
                except (TypeError, ValueError):
                    return
            elif not isinstance(v, str):
                return
            job[k] = v[:200] if isinstance(v, str) else v

    @staticmethod
    def _error(m):
        code, msg = str(m.get("code") or ""), str(m.get("message") or "")[:500]
        if code == "cancelled":
            return Cancelled()
        if code == "exception":
            return WorkerError("%s: %s" % (m.get("type") or "Exception", msg))
        try:
            status = int(m.get("status") or 500)
        except (TypeError, ValueError):
            status = 500
        return ApiError(code or "worker_error", msg or "文字起こしの部品でエラーが起きました", status)

    def stream(self, op, args, job=None):
        """要求を送り、("item", v) を途中で、最後に ("result", v) を返す生成器。エラーは例外(ApiError / Cancelled / WorkerError)。
        途中で使うのをやめた(close された)ときは、ワーカーに取り消しを伝えて結果を読み捨て、やり取りの順番をそろえてから抜ける。"""
        if isinstance(job, dict) and job.get("cancel"):   # 取り消し済みなら、ワーカーの起動も要求もしない
            raise Cancelled()
        with self.lock:
            self._ensure()
            rid = next(self.rids)
            handle = _CancelHandle(self, rid)
            self._busy_rid, self.killed_rid = rid, None
            if isinstance(job, dict):
                job["proc"] = handle
            finished = False
            try:
                try:
                    self._write(dict(args, op=op, rid=rid))
                except (OSError, ValueError):
                    self.kill()
                    self._read(rid)   # 閉じている → 異常終了として扱う
                while True:
                    m = self._read(rid)
                    if m is None or m.get("rid") != rid:
                        continue   # 以前の要求の読み残し・読めない行
                    ev = m.get("ev")
                    if ev == "set":
                        self._apply(job, m)
                    elif ev in ("item", "info"):   # info = 声の検出の結果(行より先に届く)
                        yield ev, m.get("v")
                    elif ev == "result":
                        finished = True
                        yield "result", m.get("v")
                        return
                    elif ev == "error":
                        finished = True
                        raise self._error(m)
            finally:
                handle.done = True
                if isinstance(job, dict) and job.get("proc") is handle:
                    job["proc"] = None
                if not finished and self.alive():
                    self._drain(rid)
                self._busy_rid = None
                self.last_used = time.time()

    def _drain(self, rid):
        """途中でやめた要求の残りを読み捨てる(止まらなければ強制終了)。"""
        self.cancel(rid)
        try:
            while self.proc is not None:
                m = self._read(rid)
                if m and m.get("rid") == rid and m.get("ev") in ("result", "error"):
                    return
        except (ApiError, Cancelled):
            pass

    def call(self, op, args, job=None):
        """結果だけを返す要求(モデルの読み込み・話者判別)。"""
        g = self.stream(op, args, job)
        try:
            for kind, v in g:
                if kind == "result":
                    return v
        finally:
            g.close()
        raise ApiError("worker_error", "文字起こしの部品から結果が返りませんでした", 500)


WORKER = WorkerClient()


class _Obj:
    def __init__(self, d):
        self.__dict__.update(d)


class _Segs:
    """RemoteModel.transcribe の行の生成器。読まずに close() しても、ワーカーとのやり取り(stream)を閉じる
    (始まっていない生成器の close() は finally を通らないため。声の検出が捨てすぎたときに、行を読まずにやり直す)"""

    def __init__(self, gen, stream):
        self.gen, self.stream = gen, stream

    def __iter__(self):
        return self

    def __next__(self):
        return next(self.gen)

    def close(self):
        self.gen.close()
        self.stream.close()


class RemoteModel:
    """ワーカーの中のモデルの代理。transcribe() は faster-whisper の WhisperModel.transcribe と同じ形 (行の生成器, 情報) を返す。
    行は属性(start・end・text・avg_logprob・no_speech_prob・compression_ratio・words)で読めるので、呼び出し側のコードは変えなくてよい。"""

    def __init__(self, client, name, device, params, job):
        self.client, self.name, self.device, self.job = client, name, device, job
        self.params = set(params or ())

    def transcribe(self, audio, **kw):
        if isinstance(audio, str):
            a = {"wav": audio}
        elif isinstance(audio, WavSlice):   # 範囲の音声は、wav のパスとサンプルの範囲だけを渡す(ワーカーが読む)
            a = {"wav": audio.path, "from": audio.a, "to": audio.b}
        elif isinstance(audio, WavRef):
            a = {"wav": audio.path}
        else:
            raise TypeError("認識する音声は wav のパスか WavRef / WavSlice で渡してください")
        g = self.client.stream("transcribe", {"name": self.name, "device": self.device, "audio": a, "kw": kw}, self.job)
        info = _Obj({"language": kw.get("language"), "duration": None, "duration_after_vad": None})
        first = None
        try:   # faster-whisper と同じく、声の検出の結果(info)は行を読む前に分かるようにする(最初の知らせを先に読む)
            first = next(g)
        except StopIteration:
            pass
        except BaseException:
            g.close()
            raise
        if first and first[0] == "info" and isinstance(first[1], dict):
            info.__dict__.update({k: first[1].get(k) for k in ("duration", "duration_after_vad")})
            first = None

        def conv(v):
            return _Obj(dict(v, words=[_Obj(w) for w in v.get("words") or [] if isinstance(w, dict)]))

        def segs():
            try:
                if first and first[0] == "item" and isinstance(first[1], dict):
                    yield conv(first[1])
                for kind, v in g:
                    if kind == "item" and isinstance(v, dict):
                        yield conv(v)
            finally:
                g.close()
        return _Segs(segs(), g), info


def validate_job(req):
    src = check_source(req.get("sourcePath"))
    dur = media_duration(src)
    start = num(req.get("start"), 0.0) or 0.0
    end = num(req.get("end"))
    if start < 0:
        raise ApiError("bad_range", "開始時刻が正しくありません", 400)
    if dur is not None and start >= dur - 0.5:
        raise ApiError("bad_range", "開始時刻がファイルの長さ(%s)を超えています" % fmt_hms(dur), 400)
    if end is None or (dur is not None and end > dur):
        end = dur
    if end is not None and end <= start + 0.5:
        raise ApiError("bad_range", "終了は開始より後にしてください", 400)
    if end is not None and end - start > MAX_SPAN_SEC:
        raise ApiError("too_long", "1回に処理できるのは6時間までです。範囲を分けてください", 400)
    whole = start == 0 and (end is None or dur is None or abs(end - dur) < 0.5)
    # 切り抜きスタジオが書き出した mp4 なら、隣の .clip.json(youtube-tools-clip/v1)を読んで文書に残す(元の配信のどこかが分かる)。
    # 不正・別の版なら使わずに警告だけ(文字起こし自体は続ける)。範囲指定でも clip はそのまま残す:
    # 文書の時刻は「動画ファイルの先頭 = 0 秒」のままなので、元の配信の時刻は常に clip_offset(clip) + 行の時刻になる(範囲の開始で補正しない)
    pm = pio(required=False)
    clip, clip_warn, _clip_path = pm.find_clip(src, dur) if pm else (None, None, None)
    warnings = [clip_warn] if clip_warn else []
    model = str(req.get("model") or "small").strip()
    if not valid_model(model):
        raise ApiError("bad_model", "モデル名が正しくありません", 400)
    lang = str(req.get("language") or "ja")
    if lang not in LANGS:
        lang = "ja"
    glossary = [t.strip() for t in re.split(r"[\r\n,、]+", str(req.get("glossary") or "")) if t.strip()][:200]
    gauto = auto_glossary(glossary) if req.get("autoGloss") is not False else []
    ev = req.get("evalSet") is True   # 評価用として文字起こしする: 用語集・呼び名・置換辞書・学習した置換を使わない(docs/archive/project/eval-set-procedure.md の 2)
    into = None
    if req.get("intoDoc") not in (None, ""):
        # 「編集」の文字起こしの無い文書(文字起こしせずに開いた動画)に行を入れる。id・題名・作った日・clip・編集の内容はそのまま
        into = str(req.get("intoDoc"))
        target = read_transcript(into)
        if os.path.normcase(os.path.abspath(str(target.get("sourcePath") or ""))) != os.path.normcase(src):
            raise ApiError("bad_request", "文字起こしを入れる文書の動画と、選んだ動画が違います", 400)
        if doc_has_rows(target):
            raise ApiError("not_empty", "この文書にはもう行があります(新しい文字起こしとして作ってください)", 409)
        if not str(req.get("title") or "").strip():
            req = dict(req, title=target.get("title") or "")
        ev = ev or target.get("evalSet") is True
    if ev:
        glossary, gauto = [], []
    title = str(req.get("title") or "")[:120] or os.path.splitext(os.path.basename(src))[0][:120]
    ctx = stream_context({"clip": clip, "title": title, "sourceName": os.path.basename(src), "sourcePath": src}, req.get("autoContext") is True and not ev)
    return {"sourcePath": src, "sourceName": os.path.basename(src), "start": round(start, 2), "end": round(end, 2) if end else None, "intoDoc": into,
            "duration": dur, "whole": whole, "model": model, "language": lang, "beam": 1 if req.get("quality") == "fast" else 5,
            "device": req.get("device") if req.get("device") in ("cuda", "cpu") else "auto",
            "vadMode": req.get("vadMode") if req.get("vadMode") in ("weak", "normal", "off") else ("off" if req.get("vad") is False else "weak"),
            "boost": req.get("boost") is True, "autoDict": req.get("autoDict") is not False and not ev, "wordSplit": req.get("wordSplit") is not False,
            "splitChars": split_chars_for(req),
            "autoRedo": req.get("autoRedo") is True, "redoLarge": req.get("redoLarge") is not False,
            "stripPunct": req.get("stripPunct") is not False, "glossary": glossary + gauto, "glossAuto": gauto, "context": ctx, "evalSet": ev,
            "autoLearned": req.get("autoLearned") is True and not ev, "clip": clip, "warnings": warnings,
            "title": title}


ACTIVE_STATES = ("queued", "loading", "extracting", "running")
EXCLUSIVE = {"diarize": ("diarize", "retranscribe", "redo", "voice-learn"), "voice-learn": ("diarize", "voice-learn"),
             "retranscribe": ("diarize", "retranscribe", "redo"),
             "redo": ("diarize", "retranscribe", "redo"), "abtest": ("abtest",)}   # 同じ文字起こしに同時に入れない組み合わせ


def add_job(spec, kind="transcribe"):
    with _jobs_lock:
        waiting = sum(1 for j in _jobs.values() if j["state"] in ACTIVE_STATES)
        if waiting >= MAX_QUEUE:
            raise ApiError("busy", "待機中のジョブが多すぎます(最大%d件)" % MAX_QUEUE, 429)
        excl = EXCLUSIVE.get(kind)
        if excl and spec.get("tid") and any(j.get("kind") in excl and j["spec"].get("tid") == spec["tid"] and j["state"] in ACTIVE_STATES for j in _jobs.values()):
            # validate_* でも確かめているが、確認と登録の間に同じ要求が割り込めたので、登録と同じロックの中でもう一度確かめる
            raise ApiError("busy", "この文字起こしは、すでに別の処理(話者判別・再認識・比較)の最中です", 409)
        jid = uuid.uuid4().hex[:12]
        job = {"id": jid, "title": spec["title"], "state": "queued", "phase": "順番待ち", "progress": 0.0, "tid": spec["tid"] if kind in ("diarize", "retranscribe", "redo", "voice-learn") else None, "error": None,
               "segments": 0, "speakers": 0, "unsure": 0, "kind": kind, "device": "", "createdAt": int(time.time() * 1000), "cancel": False, "proc": None, "spec": spec}
        _jobs[jid] = job
        _order.append(jid)
        while len(_order) > 100:
            old = _order.pop(0)
            if _jobs.get(old, {}).get("state") not in ("queued", "loading", "extracting", "running"):
                _jobs.pop(old, None)
            else:
                _order.insert(0, old)
                break
        _queue.put((JOB_PRIORITY.get(kind, 1), next(_seq_counter), jid))
    return job


def public_job(j):
    out = {k: j[k] for k in ("id", "title", "state", "phase", "progress", "tid", "error", "segments", "speakers", "unsure", "kind", "device", "createdAt")}
    out["warnings"] = list((j.get("spec") or {}).get("warnings") or [])   # 例: 隣の .clip.json が壊れている・別の版(文字起こしは続ける)
    out["hasClip"] = bool((j.get("spec") or {}).get("clip"))
    out["into"] = (j.get("spec") or {}).get("intoDoc") or None   # 「編集」: 文字起こしの無い文書に入れる文字起こし(画面の「この動画を文字起こしする」)
    out["named"] = list(j.get("named") or [])       # A-3: 話者判別のあと、覚えている声で名前を付けた話者 [{"speaker", "name", "score"}]
    out["learned"] = list(j.get("learned") or [])   # A-3: 声を覚えた人の名前
    if j.get("voiceError"):
        out["warnings"].append(j["voiceError"])
    out["warnings"] += [w for w in (j.get("warnings") or []) if w not in out["warnings"]]   # ジョブの中で足した注意(以前は画面に届いていなかった)
    out["vadNote"] = j.get("vadNote") or ""          # 声の検出を緩めてやり直した(4-2)
    out["kept"], out["emptyKept"], out["loose"] = j.get("kept", 0), j.get("emptyKept", 0), j.get("loose", 0)   # 全体の再認識で残した行(3-4)
    return out


def extract_audio(job, spec, wav):
    ff = find_ffmpeg()
    if not ff:
        raise ApiError("no_ffmpeg", "ffmpeg が見つかりません(README の準備手順を確認してください)", 400)
    cmd = [ff, "-hide_banner", "-nostdin", "-y", "-protocol_whitelist", "file"]
    if spec["start"] > 0:
        cmd += ["-ss", "%.3f" % spec["start"]]
    cmd += ["-i", spec["sourcePath"]]
    if spec["end"]:
        cmd += ["-t", "%.3f" % (spec["end"] - spec["start"])]
    cmd += ["-vn"]
    if spec.get("boost"):  # 小さい声を持ち上げる(低域のこもりを削り、音量のばらつきをならす)
        cmd += ["-af", "highpass=f=70,dynaudnorm=f=200:g=15:m=15"]
    cmd += ["-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", wav]
    p = subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True,
                         encoding="utf-8", errors="replace")
    job["proc"] = p
    try:
        err = p.stderr.read()
        p.wait()
    finally:
        job["proc"] = None
        if p.poll() is None:
            p.kill()
        p.stderr.close()   # 読み終えたパイプを閉じる(閉じないと GC まで残る)
    if job["cancel"]:
        raise Cancelled()
    if p.returncode != 0 or not os.path.isfile(wav) or os.path.getsize(wav) < 1000:
        tail = " / ".join([l.strip() for l in (err or "").splitlines() if l.strip()][-2:])
        raise ApiError("extract_failed", "音声を取り出せませんでした(音声トラックがないか、壊れたファイルの可能性): " + tail[:200], 400)


LATIN_MIN_LETTERS = 4   # 英字がこの数以上で、文字全体の LATIN_RATIO 以上を占め、
LATIN_RATIO = 0.3       # かつ「英字が LATIN_LONG 文字以上」か「英字の語が2つ以上」の行、
LATIN_LONG = 6          # または、英字と空白が LATIN_RUN 文字以上続く行を「英語の幻覚かも」とする(初期値。実データで調整する)
LATIN_RUN = 8
_LATIN_RUN_RE = re.compile(r"[A-Za-z][A-Za-z' ]{%d,}" % (LATIN_RUN - 1))


def latin_suspect(text, terms=()):
    """日本語の音声なのに英字が目立つ行か(英語のでたらめな文の幻覚に多い)。用語集にある英字の語(Apex など)は数えない。
    Apex・GG のような短い英単語が1つだけ混じる行は対象外(要確認だらけになるのを避ける)。"""
    t = str(text or "")
    for w in sorted({x for x in terms if x and re.search(r"[A-Za-z]", x)}, key=len, reverse=True):
        t = t.replace(w, "")
    t = re.sub(r"(?i)w{2,}|\b(?:lol|lmao|gg|wp|ok)\b", "", t)   # 笑いの「wwww」や定番の略語は数えない
    letters = len(re.findall(r"[A-Za-z]", t))
    if letters < LATIN_MIN_LETTERS:
        return False
    body = len(re.sub(r"[\W_]+", "", t))   # 記号・空白を除いた文字数(日本語も数える)
    if body and letters / body >= LATIN_RATIO and (letters >= LATIN_LONG or len(re.findall(r"[A-Za-z']+", t)) >= 2):
        return True
    return bool(_LATIN_RUN_RE.search(t))


SPARSE_MIN_SEC = 4.0    # 「長い区間に文字が少ない」行(docs/design/edit-tool-design.md の 12 ③-1): この長さより長くて
                        # (ちょうど 4.0 秒は含めない。疑似の文字起こしの行(4.0 秒に「テスト文N」)を対象にしないため。本物の行への影響は境目だけ)
SPARSE_MAX_CPS = 1.5    # 記号・空白を除いた文字数が 1 秒あたりこれ未満
SPARSE_FLAG = "長い区間に文字が少ない(抜けの可能性)"


def text_chars(text):
    """記号・空白を除いた文字数(文字と数字だけ。かな・漢字・英数字)"""
    return sum(1 for ch in str(text or "") if unicodedata.category(ch)[0] in "LN")


def sparse_row(start, end, text):
    """長い区間に文字が少ない行か(③-1)。取りこぼしを減らすために VAD を甘くしている(vadMode weak)ので、BGM やゲーム音が声として通り、
    Whisper が長い塊に単語1つを出したり、途中を飛ばしたりする(区間ごとの抜け)。その形をつかまえる"""
    try:
        dur = float(end) - float(start)
    except (TypeError, ValueError):
        return False
    return dur > SPARSE_MIN_SEC and text_chars(text) < SPARSE_MAX_CPS * dur


def _letters(text):
    """比べる用: NFKC・小文字・文字と数字だけ"""
    return "".join(ch for ch in unicodedata.normalize("NFKC", str(text or "")).lower() if unicodedata.category(ch)[0] in "LN")


def stock_phrase(text):
    """よくある誤認識の文か(時間は見ない): 以前からの HALLUC が含まれる・行のほとんどが HALLUC_LINE の文・音楽の表記だけ(♪・(音楽))"""
    t = str(text or "")
    if any(h in t for h in HALLUC):
        return True
    if t.strip() and MUSIC_ONLY.match(t) and ("♪" in t or "♫" in t or "♬" in t or "(" in t or "（" in t or "[" in t or "【" in t or "［" in t):
        return True
    n = _letters(t)
    for h in HALLUC_LINE:
        k = _letters(h)
        if k and k in n and len(n) - len(k) <= HALLUC_LINE_REST:
            return True
    return False


def repeats_in_line(text):
    """行の中で同じ語(2〜10 文字)が REP_MIN 回以上続くか(「ぱんぱんぱんぱんぱん…」。1 文字の繰り返し = 笑い・叫びは除く)"""
    m = REP_RE.search(_letters(text))
    while m:
        if len(set(m.group(1))) > 1:
            return True
        m = REP_RE.search(_letters(text), m.start() + 1)
    return False


def make_flags(seg, prev_texts, lang=None, terms=()):
    """Whisper は BGM・無音・歌で幻覚(でたらめな文)を出しやすいので、要確認の印を付ける。
    lang が "ja" のときは、英字が目立つ行も対象にする(terms = 認識のヒントに渡した語(prompt_terms)。その中の英字の語は数えない)。
    長い区間に文字が少ない行(抜けの可能性。sparse_row)にも付ける(2026-09-26 ③-1)。
    S-3(2026-09-29): よくある誤認識の文を増やした(stock_phrase)・行の中の繰り返し(repeats_in_line)・近くの行に同じ文が3回・
    短い区間でヒントの語だけが出た行(LEAK_FLAG。roster.leak_only)"""
    why = []
    lp, ns, cr = seg.get("avg_logprob"), seg.get("no_speech_prob"), seg.get("compression_ratio")
    if lp is not None and lp < -1.0:
        why.append("自信が低い")
    if ns is not None and ns > 0.6:
        why.append("音声でない可能性(BGMなど)")
    text = seg["text"]
    if (cr is not None and cr > 2.4) or repeats_in_line(text):
        why.append("繰り返しの可能性")
    dur = seg["end"] - seg["start"]
    if stock_phrase(text) and dur < 8:
        why.append("よくある誤認識の文")
    key = _letters(text)
    if text and (prev_texts[-2:] == [text, text] or (len(key) >= 4 and sum(1 for p in prev_texts[-5:] if _letters(p) == key) >= 2)):
        why.append("同じ文の繰り返し")   # 続けて3回、または近く(前の5行)に同じ文が2回あって3回目
    if terms and (("用語" in text and ":" in unicodedata.normalize("NFKC", text)) or (dur <= LEAK_MAX_SEC and _roster.leak_only(text, terms))):
        why.append(LEAK_FLAG)
    if lang == "ja" and latin_suspect(text, terms):
        why.append("英字が多い(英語の幻覚の可能性)")
    if sparse_row(seg.get("start"), seg.get("end"), text):
        why.append(SPARSE_FLAG)
    return "、".join(why)


def load_model(name, job, pref="auto", force_cpu=False):
    """(モデル, 使用デバイス) を返す。サーバーのプロセスでは、モデルは認識ワーカー(別プロセス)の中に読み込み、
    ここではその代理(RemoteModel。transcribe() を呼ぶとワーカーで認識する)を返す。faster-whisper のネイティブコードが落ちても、
    落ちるのはワーカーだけになる(統合計画の段階3-3)。"""
    if IN_WORKER:
        return _load_model_local(name, job, pref, force_cpu)
    v = WORKER.call("load", {"name": name, "pref": pref, "force_cpu": bool(force_cpu)}, job)
    return RemoteModel(WORKER, name, v["device"], v.get("params"), job), v["device"]


def _load_model_local(name, job, pref="auto", force_cpu=False):
    """(モデル, 使用デバイス) を返す(認識ワーカーの中で動く本体)。同じ設定のモデルは使い回す。
    pref: auto=GPU があれば GPU(失敗したら CPU) / cuda=GPU 固定(失敗したらエラー) / cpu=CPU 固定"""
    from faster_whisper import WhisperModel
    env = os.environ.get("TRANSCRIBE_DEVICE")
    if force_cpu:
        pref = "cpu"
    elif env in ("cuda", "cpu"):
        pref = env
    if pref == "cpu":
        order = ["cpu"]
    elif pref == "cuda":
        order = ["cuda"]
    else:
        order = ["cuda", "cpu"] if gpu_ready() else ["cpu"]
    with _model_lock:
        last = None
        for dev in order:
            key = (name, dev)
            _model_used[0] = time.time()
            if key in _models:
                return _models[key], dev
            if _models:   # 別のモデルは手放す(large-v3 と turbo を交互に使ってもメモリが積み上がらない。落ちる原因の1つ)
                log.info("モデルを解放: %s(メモリ %s)", ", ".join("%s/%s" % k for k in _models), _mem())
                _models.clear()
                gc.collect()
            job["phase"] = "モデルを読み込み中(初回はダウンロードのため数分かかります)"
            try:
                log.info("モデルを読み込み: %s/%s(メモリ %s)", name, dev, _mem())
                m = _new_whisper(WhisperModel, name, dev)
                log.info("モデルを読み込み終わり: %s/%s(メモリ %s)", name, dev, _mem())
            except MemoryError:
                raise ApiError("no_memory", "メモリが足りずモデルを読み込めませんでした。他のアプリ(動画編集ソフトなど)を閉じてから、もう一度試してください", 500)
            except Exception as e:
                last = e
                if dev == "cuda" and pref == "auto":
                    continue  # 自動のときは、GPU が使えなければ CPU にする
                if dev == "cuda":
                    raise ApiError("gpu_failed", "GPU で読み込めませんでした: %s(GPU 用ライブラリが未導入の可能性があります。install-gpu.bat を実行するか、処理方式を「自動」か「CPU」にしてください)" % str(e)[:160], 500)
                raise ApiError("model_failed", "モデルを読み込めませんでした: %s(ネットワーク接続とモデル名を確認してください)" % str(e)[:200], 500)
            _models[key] = m
            return m, dev
        raise ApiError("model_failed", "モデルを読み込めませんでした: %s" % str(last)[:200], 500)


def _new_whisper(WhisperModel, name, dev):
    """モデルを作る。ダウンロード済みなら手元のファイルだけで読む(読むたびに Hugging Face へ版の確認の通信をしない。
    オフラインでも読め、通信の待ちが無くなる。計画 段0-4)。手元に無い(初回)・手元だけでは読めないときは、今までどおりネットワークから取る"""
    ct = "float16" if dev == "cuda" else "int8"
    try:
        return WhisperModel(name, device=dev, compute_type=ct, local_files_only=True)
    except MemoryError:
        raise
    except Exception as e:
        log.info("手元のファイルだけではモデルを読めないので、ネットワークから取ります: %s(%s)", name, str(e)[:120])
    return WhisperModel(name, device=dev, compute_type=ct)


def whisper_kwargs(spec):
    kw = dict(language=None if spec["language"] == "auto" else spec["language"], beam_size=spec["beam"], condition_on_previous_text=False)
    mode = spec.get("vadMode", "weak")
    if mode == "off":
        kw["vad_filter"] = False
    elif mode == "weak":   # 声が重なる・BGMがある配信で、話している部分を落としにくくする
        kw["vad_filter"] = True
        kw["vad_parameters"] = {"threshold": 0.3, "min_silence_duration_ms": 1000, "speech_pad_ms": 600}
        kw["no_speech_threshold"] = 0.9
    else:
        kw["vad_filter"] = True
        kw["vad_parameters"] = {"min_silence_duration_ms": 500}
    if spec.get("wordSplit"):
        kw["word_timestamps"] = True   # 単語の時刻。長い行を分け、行の始まり・終わりを声のある所にそろえる(対応していない版では filter_kwargs が外す)
    if "kotoba" in spec["model"].lower():
        kw["chunk_length"] = 15   # kotoba-whisper が推奨する設定
    if spec.get("temp0"):
        kw["temperature"] = 0.0   # 温度のやり直し(乱数を使う)をしない。精度を比べる道具(dev/eval_asr.py --temp0)だけが使う
    terms = prompt_terms(spec)
    if terms:
        kw["initial_prompt"] = "用語: " + "、".join(terms)
        kw["hotwords"] = ", ".join(_roster.fit(list(spec.get("glossary") or []) + list((spec.get("context") or {}).get("terms") or []), _roster.HOT_LIMIT, 2))
    return kw


def prompt_terms(spec):
    """認識のヒント(initial_prompt)に渡す語: 用語集(自動で足した語を含む)→ 配信ごとの文脈(出る人の名前と呼び名。段1-2)。
    先頭 150 字に収まるだけ(語の途中で切らない)。プロンプトの漏れ出しの印(S-3)も、この語で調べる"""
    return _roster.fit(list(spec.get("glossary") or []) + list((spec.get("context") or {}).get("terms") or []))


def stream_context(doc, enabled=True):
    """配信ごとの文脈(段1-2): その配信に出る人を、配信のチャンネル名・コラボ相手(スタジオの data.json を読むだけ)・話者の名前・題名から決め、
    その人の名前と呼び名だけをヒントの語にする。**題名の文字列そのものは渡さない**。
    doc: clip・title・sourceName・sourcePath・speakers を持つ辞書。-> {"members": [{"name", "from"}], "terms": [語]}"""
    if not enabled:
        return {"members": [], "terms": []}
    r = _roster.load(ROSTER)
    clip = doc.get("clip") if isinstance(doc.get("clip"), dict) else {}
    src = clip.get("source") if isinstance(clip.get("source"), dict) else {}
    try:
        info = studio_stream(src.get("videoId")) if src.get("videoId") else None
    except Exception as e:   # 他のツールのデータが読めなくても、文脈なしで続ける
        log.info("スタジオの配信の情報を読めませんでした: %s", str(e)[:120])
        info = None
    path = str(doc.get("sourcePath") or "")
    titles = [src.get("title"), (info or {}).get("title"), doc.get("title"), doc.get("sourceName"),
              os.path.basename(os.path.dirname(path)) if path else ""]   # 動画の入ったフォルダ(スタジオは配信の題名のフォルダに書き出す)
    ctx = _roster.build_context(r, (info or {}).get("channel", ""), [c["channel"] for c in (info or {}).get("collab") or []],
                                [s.get("name") for s in doc.get("speakers") or [] if isinstance(s, dict)], [str(t or "")[:300] for t in titles])
    ctx["terms"] = _roster.member_terms([m["name"] for m in ctx["members"]], r)
    return ctx


def filter_kwargs(model, kw):
    """使っている faster-whisper が対応していない引数は渡さない(古い版でも動くように)。
    認識ワーカーの代理(RemoteModel)は、ワーカーが調べた引数の一覧(params)を持っている。"""
    params = getattr(model, "params", None)
    if params:
        return {k: v for k, v in kw.items() if k in params}
    try:
        import inspect
        accepted = set(inspect.signature(model.transcribe).parameters)
        return {k: v for k, v in kw.items() if k in accepted}
    except (TypeError, ValueError):
        return kw


# ---------- 声の検出(VAD)が捨てすぎたときのやり直し(docs/design/whole-retranscribe-design.md の 4-2) ----------
# 声が重なる所・BGM のある所を、Silero VAD が「声ではない」と判断して全部捨て、モデルに何も渡らないことがある(2026-09-28。40 秒が 0 文字)。
# 残った割合が VAD_MIN_KEEP 未満か、文字が 1 つも出なかったら、「弱め」→「なし」の順に緩めてやり直す
VAD_MIN_KEEP = 0.2
VAD_LADDER = {"normal": ("normal", "weak", "off"), "weak": ("weak", "off"), "off": ("off",)}
VAD_NAMES = {"normal": "標準", "weak": "弱め", "off": "なし"}


def seg_to_dict(s, shift=0.0):
    """認識の1行(faster-whisper の行・ワーカーの代理)→ 辞書(秒は shift を足す)"""
    words = [(float(w.start) + shift, float(w.end) + shift, str(w.word)) for w in (getattr(s, "words", None) or [])
             if getattr(w, "start", None) is not None and getattr(w, "end", None) is not None]
    return {"start": float(s.start) + shift, "end": float(s.end) + shift, "text": (s.text or "").strip(), "avg_logprob": getattr(s, "avg_logprob", None),
            "no_speech_prob": getattr(s, "no_speech_prob", None), "compression_ratio": getattr(s, "compression_ratio", None), "words": words}


def vad_kept(info, mode):
    """(声の検出のあとに残った割合, 捨てた秒)。声の検出をかけていない・分からないときは (None, 0.0)"""
    d, k = getattr(info, "duration", None), getattr(info, "duration_after_vad", None)
    if mode == "off" or not isinstance(d, (int, float)) or not isinstance(k, (int, float)) or d <= 0:
        return None, 0.0
    return max(0.0, min(1.0, k / d)), round(max(0.0, d - k), 2)


def vad_note(vad):
    """やり直したときに画面に出す文(やり直していなければ '')"""
    if not vad or not vad.get("retries"):
        return ""
    steps = "→".join([VAD_NAMES.get(r["mode"], r["mode"]) for r in vad["retries"]] + [VAD_NAMES.get(vad["used"], vad["used"])])
    return "声の検出で大部分が「声ではない」と判断されたので、検出を緩めて認識しました(声の検出: %s)" % steps


def transcribe_vad_fallback(job, model, audio, spec, on_seg=None):
    """声の検出を spec["vadMode"] から始め、捨てすぎ・文字が 0 なら緩めてやり直す。-> (行の辞書の一覧, 声の検出の記録)。
    記録 = {"requested", "used", "removedSec"(使った設定で捨てた秒), "retries": [{"mode", "kept", "removedSec", "why": "kept"|"empty"}]}。
    よくある誤認識の文(HALLUC)しか出なかったときも「文字が 0」とみなす(2026-09-28 白上フブキ03: 標準で 22 秒捨て、残りから「ご視聴ありがとうございました」だけ)"""
    mode0 = spec.get("vadMode", "weak")
    ladder = VAD_LADDER.get(mode0, (mode0,))
    retries = []
    for i, mode in enumerate(ladder):
        last = i == len(ladder) - 1
        kw = filter_kwargs(model, whisper_kwargs(dict(spec, vadMode=mode)))
        segs, info = model.transcribe(audio, **kw)
        kept, removed = vad_kept(info, mode)
        if kept is not None and kept < VAD_MIN_KEEP and not last:
            close = getattr(segs, "close", None)
            if close:
                close()   # 行は読まない(ほとんど捨てた結果なので)
            retries.append({"mode": mode, "kept": round(kept, 3), "removedSec": removed, "why": "kept"})
            log.info("声の検出が %.0f%% を捨てたので、緩めてやり直します(%s)", (1 - kept) * 100, mode)
            continue
        raw = []
        for s in segs:
            if job["cancel"]:
                raise Cancelled()
            raw.append(seg_to_dict(s))
            if on_seg:
                on_seg(raw[-1], len(raw))   # この回(やり直しごと)の行の数
        terms = prompt_terms(spec)
        if not any(r["text"] and not stock_phrase(r["text"]) and not _roster.leak_only(r["text"], terms) for r in raw) and not last:
            # 「ご視聴ありがとうございました」だけ・ヒントの語だけ = 文字が 0 と同じ
            retries.append({"mode": mode, "kept": None if kept is None else round(kept, 3), "removedSec": removed, "why": "empty"})
            log.info("文字が出なかったので、声の検出を緩めてやり直します(%s)", mode)
            continue
        return raw, {"requested": mode0, "used": mode, "removedSec": removed, "retries": retries}
    return [], {"requested": mode0, "used": ladder[-1], "removedSec": 0.0, "retries": retries}


def transcribe_real(job, spec, wav, total):
    model, device = load_model(spec["model"], job, spec.get("device", "auto"))
    job["device"] = device
    if job["cancel"]:
        raise Cancelled()
    job["phase"], job["state"] = "文字起こし中", "running"

    def progress(r, n):
        job["progress"] = min(0.99, r["end"] / total) if total else 0.0
        job["segments"] = n   # 処理状況の「n 行」(行は最後まで読んでから流すので、ここで数える)

    # やり直しに備えて、行は最後まで読んでから流す(やり直す前の行を文書に入れないため)
    try:
        raw, vad = transcribe_vad_fallback(job, model, wav, spec, progress)
    except (Cancelled, ApiError):
        raise
    except Exception:
        if device == "cuda" and spec.get("device") == "cuda":
            raise ApiError("gpu_failed", "GPU での処理に失敗しました。GPU 用ライブラリが未導入の可能性があります(install-gpu.bat を実行するか、処理方式を「自動」か「CPU」にしてください)", 500)
        if device != "cuda":
            raise
        # 自動のとき、GPU で実行時に失敗(CUDA ライブラリ不足など)したら CPU でやり直す
        job["phase"], job["device"] = "GPU が使えないため CPU で処理します", "cpu"
        model, _ = load_model(spec["model"], job, force_cpu=True)
        raw, vad = transcribe_vad_fallback(job, model, wav, spec, progress)
    job["vad"] = vad
    for x in raw:
        yield x


SPLIT_GAP, SPLIT_SEC, SPLIT_CHARS = 1.0, 8.0, 40   # 単語の間がこの秒数以上あいたら行を分ける / 1行の最大の長さ(秒・文字。文字は設定の「1つの字幕の最大文字数」が優先)
SPLIT_SLACK = 2          # 最大文字数を 2 文字まで超えるのは許す(無理に分けて変な所で切らない。docs/design/edit-tool-design.md の 12 ②)
# 字幕の文字数(12 ②。ユーザー決定 2026-09-26: 縦 16・横 28、パックの字幕は2段 = 縦 8・横 14 文字前後で改行)。設定の "subtitle" に保存する
SUBTITLE_DEFAULT = {"orientation": "vertical", "maxChars": {"vertical": 16, "horizontal": 28}, "wrapChars": {"vertical": 8, "horizontal": 14}}
ORIENTATIONS = ("vertical", "horizontal")


def subtitle_settings(st=None):
    """設定の subtitle(字幕の向き・1つの字幕の最大文字数・パックの字幕の改行の文字数)を、範囲を確かめて返す(無い・おかしい値は既定)"""
    v = (st if st is not None else load_settings()).get("subtitle")
    v = v if isinstance(v, dict) else {}
    out = {"orientation": v.get("orientation") if v.get("orientation") in ORIENTATIONS else SUBTITLE_DEFAULT["orientation"]}
    for key, lo, hi in (("maxChars", 4, 80), ("wrapChars", 2, 40)):
        src = v.get(key) if isinstance(v.get(key), dict) else {}
        out[key] = {}
        for o in ORIENTATIONS:
            n = src.get(o)
            out[key][o] = int(n) if isinstance(n, (int, float)) and not isinstance(n, bool) and lo <= n <= hi else SUBTITLE_DEFAULT[key][o]
    return out


def split_chars_for(req=None, st=None):
    """行を分けるときの最大文字数(要求の splitChars → 要求の subtitleOrientation → 設定の字幕の向き)。
    画面は今の欄の値を splitChars で渡す(設定の保存は少し遅れて送られるため)。まとめて実行は設定を使う"""
    req = req or {}
    n = req.get("splitChars")
    if isinstance(n, (int, float)) and not isinstance(n, bool) and 4 <= n <= 80:
        return int(n)
    sub = subtitle_settings(st)
    o = req.get("subtitleOrientation")
    return sub["maxChars"][o if o in ORIENTATIONS else sub["orientation"]]
STRIP_PUNCT_CHARS = "、。？！?!"   # ショート動画のテロップでは句読点が浮きやすいので、既定で取り除く対象(全角の読点・句点・疑問符・感嘆符と、その半角形)
_strip_punct_re = re.compile("[%s]" % re.escape(STRIP_PUNCT_CHARS))


def strip_punct(text):
    """テロップ表示用に、句読点(、。？！ と半角の ?!)を取り除く。"""
    return _strip_punct_re.sub("", text)


def _cut_words(ws, max_chars=SPLIT_CHARS):
    """単語の並び ws=[(開始,終了,文字)] を、長すぎる間は「間が大きい・句読点のあと・真ん中に近い」所で分けていく。
    文字数は max_chars + SPLIT_SLACK まで許す。同じ種類の文字(カタカナ・漢字・英数字)の並びの途中では、なるべく切らない(12 ②)"""
    dur = ws[-1][1] - ws[0][0]
    chars = sum(len(t.strip()) for _a, _b, t in ws)
    if len(ws) < 2 or (dur <= SPLIT_SEC and chars <= max_chars + SPLIT_SLACK):
        return [ws]
    best, bi = None, 1
    for i in range(1, len(ws)):
        gap = max(0.0, ws[i][0] - ws[i - 1][1])
        prev_t, next_t = ws[i - 1][2].rstrip(), ws[i][2].lstrip()
        tail = prev_t[-1:]
        punct = 1.0 if tail in "。！？!?" else (0.4 if tail in "、,，" else 0.0)
        balance = 1.0 - abs((ws[i - 1][1] - ws[0][0]) / dur - 0.5) if dur > 0 else 0.5
        same = 1.0 if prev_t and next_t and _cc(prev_t[-1]) and _cc(prev_t[-1]) == _cc(next_t[0]) else 0.0   # 語の途中
        score = gap * 2 + punct + balance * 0.5 - same
        if best is None or score > best:
            best, bi = score, i
    return _cut_words(ws[:bi], max_chars) + _cut_words(ws[bi:], max_chars)


def split_segment(s, max_chars=SPLIT_CHARS):
    """認識した1行 s を、単語の時刻で整える。①行の始まり・終わりを最初・最後の単語にそろえる(声のない所まで伸びた行を直す)
    ②単語の間が1秒以上あいた所で分ける ③長すぎる行(8秒・max_chars 文字 + 2 超)は区切りのよい所で分ける。
    単語の並びが行の文章と合わないとき、単語の時刻が無いときは、何もせずそのまま返す。
    分けた行には、その行の単語を "_words" に付ける(文書の words.json に保存する用。行のデータには入れない)"""
    words = s.get("words") or []
    if not words:
        return [s]
    ws = [(a, b, t) for a, b, t in words if b >= a]
    squash = lambda x: re.sub(r"\s+", "", x)
    if not ws or squash("".join(t for _a, _b, t in ws)) != squash(s.get("text", "")):
        return [s]
    groups, cur = [], [ws[0]]
    for w in ws[1:]:
        if w[0] - cur[-1][1] >= SPLIT_GAP:
            groups.append(cur)
            cur = []
        cur.append(w)
    groups.append(cur)
    parts = [p for g in groups for p in _cut_words(g, max_chars)]
    out = []
    for p in parts:
        text = "".join(t for _a, _b, t in p).strip()
        if text:
            out.append({**{k: v for k, v in s.items() if k != "words"}, "start": p[0][0], "end": max(p[-1][1], p[0][0]), "text": text, "_words": p})
    return out or [s]


def expand_segments(gen, spec):
    """認識の出力を、split_segment で整えながら流す(wordSplit が無効なら、そのまま)。
    句読点の除去(stripPunct、既定オン)は、単語分割が句読点を判断材料に使い終えたあとの、最後の1回だけにかける
    (分割の精度には影響させず、かつ text と original の両方に必ず同じ結果が入るよう、ここ1か所にまとめる)。"""
    strip = spec.get("stripPunct", True)
    mc = spec.get("splitChars") or SPLIT_CHARS
    for s in gen:
        for p in (split_segment(s, mc) if spec.get("wordSplit") else [s]):
            yield {**p, "text": strip_punct(p["text"])} if strip and p.get("text") else p


CONF_KEYS = ("avg_logprob", "no_speech_prob", "compression_ratio")   # 機械の出力 original の各行に残す、認識の自信の度合い(文字起こしの改善の計画 段0-1)


def machine_conf(s):
    """認識の1行の自信の度合い {avg_logprob, no_speech_prob, compression_ratio}(分かるものだけ。小数4桁)。
    original に残して、どの値のときに誤りが多いか(怪しい所だけ別の方法で聞き直す判断の材料)を測れるようにする"""
    out = {}
    for k in CONF_KEYS:
        v = s.get(k)
        if isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v):
            out[k] = round(float(v), 4)
    return out


_pkg_versions = {}


def pkg_version(name):
    """入っているパッケージの版(読み込まずに dist-info から読む = サーバー側で faster_whisper などのネイティブの部品を import しない)。無ければ ''"""
    if name not in _pkg_versions:
        try:
            import importlib.metadata as _md
            _pkg_versions[name] = str(_md.version(name))
        except Exception:
            _pkg_versions[name] = ""
    return _pkg_versions[name]


def recognition_run(spec, job, audio_sec, wall_sec):
    """文書の recognition.runs に残す、この認識の出どころ(エンジン・版・モデル・機器・かかった時間)。精度と速さを後から比べるため(計画 段0-1)"""
    fake = backend_name() == "fake"
    return {"engine": "fake" if fake else "faster-whisper", "engineVersion": "" if fake else pkg_version("faster-whisper"),
            "model": spec["model"], "device": job.get("device", ""), "language": spec["language"],
            "settings": {"beam": spec["beam"], "vadMode": spec["vadMode"], "boost": bool(spec.get("boost")), "wordSplit": bool(spec.get("wordSplit")),
                         "glossaryChars": len("、".join(spec.get("glossary") or [])), "promptChars": len("、".join(prompt_terms(spec))),
                         "context": [m["name"] for m in (spec.get("context") or {}).get("members") or []]},
            "audioSec": round(float(audio_sec or 0), 2), "wallSec": round(float(wall_sec), 2), "at": int(time.time() * 1000),
            **vad_record(job.get("vad"))}


def context_record(spec):
    """文書の params に残す配信ごとの文脈(出る人と材料・ヒントに入った語の数)。使っていなければ None"""
    ctx = spec.get("context") or {}
    if not ctx.get("members"):
        return None
    return {"members": [{"name": m["name"], "from": list(m.get("from") or [])} for m in ctx["members"]][:10], "terms": len(ctx.get("terms") or [])}


def vad_record(vad):
    """recognition.runs に残す声の検出の記録(使った設定・捨てた秒・やり直し)。分からなければ {}"""
    if not vad:
        return {}
    return {"vadUsed": vad.get("used"), "vadRemovedSec": vad.get("removedSec", 0.0), "vadRetries": list(vad.get("retries") or [])}


def row_words(p, shift=0.0):
    """expand_segments が出した行の単語(split_segment の "_words" か、分けなかった行の "words")→ [[開始, 終了, 文字]](絶対の秒)"""
    return [[round(a + shift, 3), round(b + shift, 3), t] for a, b, t in (p.get("_words") or p.get("words") or [])]


# ---------- 単語の時刻(12 ②。transcripts/<id>.words.json。行のデータには入れない = 画面の保存で落ちたり古くなったりしないように) ----------
WORDS_SCHEMA = "youtube-tools-words/v1"
MAX_WORDS_BYTES = 32 * 1024 * 1024


def words_path(tid):
    return os.path.join(TX_DIR, tid + ".words.json")


def read_words(tid):
    """文書の単語の時刻 [[開始, 終了, 文字], ...](時刻の順)。無い・壊れていれば None"""
    try:
        d = _fsio.read_json_file(words_path(tid), MAX_WORDS_BYTES)
    except (OSError, UnicodeError, ValueError):
        return None
    if not isinstance(d, dict) or d.get("schema") != WORDS_SCHEMA or not isinstance(d.get("words"), list):
        return None
    out = []
    for w in d["words"]:
        if isinstance(w, list) and len(w) == 3 and all(isinstance(x, (int, float)) and not isinstance(x, bool) for x in w[:2]) and isinstance(w[2], str):
            out.append([float(w[0]), float(w[1]), w[2]])
    return sorted(out, key=lambda w: (w[0], w[1]))


def write_words(tid, words, model=""):
    """単語の時刻を保存する(空なら消す)。書けなくても文字起こしは失敗にしない(呼び出し側で記録だけ)"""
    if not words:
        try:
            os.unlink(words_path(tid))
        except FileNotFoundError:
            pass
        return
    body = {"schema": WORDS_SCHEMA, "model": str(model or ""), "updatedAt": int(time.time() * 1000),
            "words": sorted(words, key=lambda w: (w[0], w[1]))}
    atomic_write(words_path(tid), json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))


def replace_words(tid, a, b, new_words, model="", keep_spans=()):
    """範囲 [a, b] の単語を、認識し直した単語に差し替える(真ん中が範囲に入る単語を消す。keep_spans の区間の単語は残す)。
    以前の単語が無い文書は、新しい単語だけにしない(範囲の外の単語が無いまま一部だけあると、分け直すときに紛らわしいため、範囲の単語だけで作る)"""
    old = read_words(tid) or []
    keep = [w for w in old if not (a - 1e-6 <= (w[0] + w[1]) / 2 <= b + 1e-6) or _in_spans((w[0] + w[1]) / 2, keep_spans)]
    write_words(tid, keep + [list(w) for w in new_words], model)


def _squash(text):
    return re.sub(r"\s+", "", str(text or ""))


def resplit_doc(obj):
    """POST /api/resplit {"id", "orientation"?, "baseUpdatedAt"?}: 今の文書の長い行を、保存してある単語の時刻で分け直す(12 ②)。
    分けるのは: 校正済みでない・文字が単語と一致する(人が直していない)・最大文字数 + 2 を超える行だけ。分けた行は話者・印・タグ・メモを引き継ぐ。
    分ける前の文書は履歴に残す(「以前の版に戻す」で戻せる)。-> {"changed": 分けた行の数, "added": 増えた行, "skipped": 単語と一致しない長い行, "rows", "updatedAt"}"""
    tid = str(obj.get("id") or "")
    o = obj.get("orientation")
    max_chars = split_chars_for({"subtitleOrientation": o, "splitChars": obj.get("splitChars")})
    with _save_lock:
        doc = read_transcript(tid)
        base = obj.get("baseUpdatedAt")
        if isinstance(base, int) and not isinstance(base, bool) and base != int(doc.get("updatedAt") or 0):
            raise ApiError("conflict", "別の画面で先に保存されています。読み直してから、もう一度押してください", 409)
        words = read_words(tid)
        if not words:
            raise ApiError("no_words", "この文字起こしには単語の時刻がありません(v0.17.0 より前の文字起こし・単語の時刻を使わない設定)。"
                                       "行を選んで「範囲を再認識」すると、その範囲の単語の時刻を取り直せます", 400)
        mids = [(w[0] + w[1]) / 2 for w in words]
        segs = [g for g in doc.get("segments") or [] if isinstance(g, dict)]
        used = {str(g.get("id")) for g in segs}
        out, changed, added, skipped = [], 0, 0, 0
        for g in segs:
            text = str(g.get("text") or "")
            if g.get("proofed") is True or len(_squash(text)) <= max_chars + SPLIT_SLACK:
                out.append(g)
                continue
            a, b = float(g.get("start") or 0), float(g.get("end") or 0)
            lo, hi = bisect.bisect_left(mids, a - 0.05), bisect.bisect_right(mids, b + 0.05)
            ws = [tuple(w) for w in words[lo:hi]]
            joined = "".join(t for _a, _b, t in ws)
            if ws and _squash(joined) == _squash(text):
                strip = False
            elif ws and _squash(strip_punct(joined)) == _squash(text):
                strip = True        # 句読点を取り除いた行(stripPunct)
            else:
                skipped += 1        # 人が直した行・辞書で置き換えた行・単語の無い行は分けない
                out.append(g)
                continue
            parts = split_segment({"start": a, "end": b, "text": joined, "words": ws}, max_chars)
            if len(parts) < 2:
                out.append(g)
                continue
            changed += 1
            added += len(parts) - 1
            for k, p in enumerate(parts):
                t = strip_punct(p["text"]) if strip else p["text"]
                sid = base = str(g.get("id"))
                if k:   # 2つめからは <元の id>-2, -3 …(ほかの行と重ならない番号)
                    n = k + 1
                    sid = "%s-%d" % (base, n)
                    while sid in used:
                        n += 1
                        sid = "%s-%d" % (base, n)
                    used.add(sid)
                out.append(dict(g, id=sid, start=round(p["start"], 2), end=round(p["end"], 2), text=t[:MAX_TEXT]))
        if not changed:
            return {"changed": 0, "added": 0, "skipped": skipped, "rows": len(segs), "updatedAt": int(doc.get("updatedAt") or 0)}
        try:
            hist_snapshot(tid, force=True)   # 分ける前を「以前の版に戻す」に残す
        except OSError:
            pass
        doc["segments"] = sorted(out, key=lambda g: (g["start"], g["end"]))
        doc["updatedAt"] = int(time.time() * 1000)
        doc["resplit"] = {"maxChars": max_chars, "rows": changed, "at": doc["updatedAt"]}
        apply_edit_cuts(tid, doc)
        atomic_write(tx_path(tid), json.dumps(doc, ensure_ascii=False, indent=1).encode("utf-8"))
        return {"changed": changed, "added": added, "skipped": skipped, "rows": len(doc["segments"]), "updatedAt": doc["updatedAt"]}


def transcribe_fake(job, spec, wav, total):
    """テスト用(環境変数 TRANSCRIBE_BACKEND=fake)。実際の音声認識は行わない。"""
    job["phase"], job["state"], job["device"] = "文字起こし中", "running", "cpu"
    t, i = 0.0, 0
    while t < total:
        if job["cancel"]:
            raise Cancelled()
        e = min(total, t + 4.0)
        i += 1
        yield {"start": t, "end": e, "text": "テスト文%d" % i, "avg_logprob": -1.4 if i % 5 == 0 else -0.3,
               "no_speech_prob": 0.1, "compression_ratio": 1.2}
        job["progress"] = min(0.99, e / total)
        time.sleep(float(os.environ.get("TRANSCRIBE_FAKE_DELAY", "0.05")))
        t = e


def run_job(job):
    if job.get("kind") == "diarize":
        return run_diarize(job)
    if job.get("kind") == "voice-learn":
        return run_voice_learn(job)
    if job.get("kind") == "retranscribe":
        return run_retranscribe(job)
    if job.get("kind") == "redo":
        return run_redo(job)
    if job.get("kind") == "abtest":
        return run_abtest(job)
    spec = job["spec"]
    wav = os.path.join(TMP_DIR, job["id"] + ".wav")
    try:
        os.makedirs(TMP_DIR, exist_ok=True)
        job["state"], job["phase"] = "extracting", "音声を取り出し中"
        extract_audio(job, spec, wav)
        total = media_duration(wav) or (spec["end"] - spec["start"] if spec["end"] else 0)
        t_rec = time.monotonic()   # 認識にかかった時間(モデルの読み込みを含む)。recognition.runs に残す
        if backend_name() == "fake":
            gen = transcribe_fake(job, spec, wav, total)
        else:
            if not has_faster_whisper():
                raise ApiError("no_whisper", "faster-whisper が入っていません(README の準備手順を確認してください)", 400)
            job["state"] = "loading"
            gen = transcribe_real(job, spec, wav, total)
        segs, prev, original, pairs, dict_n, all_words = [], [], [], (parse_replacements(load_settings().get("replacements")) if spec.get("autoDict") else []), 0, []
        sparse_lp = {}   # 「長い区間に文字が少ない」行の avg_logprob(認識し直したときに、良くなったかを比べる。③-2)
        learn_n = 0
        lrules, lfb = (learn_rules(), load_feedback()) if spec.get("autoLearned") else ({}, None)
        for s in expand_segments(gen, spec):
            if not s["text"]:
                continue
            seg = {"id": "s%d" % (len(segs) + 1), "start": round(s["start"] + spec["start"], 2), "end": round(s["end"] + spec["start"], 2),
                   "text": s["text"][:MAX_TEXT], "speaker": "", "flag": ""}
            seg["flag"] = make_flags({**s, "text": seg["text"], "start": seg["start"], "end": seg["end"]}, prev, spec["language"], prompt_terms(spec))
            prev.append(seg["text"])
            if SPARSE_FLAG in seg["flag"] and s.get("avg_logprob") is not None:
                sparse_lp[seg["id"]] = float(s["avg_logprob"])
            if lrules:   # 確度が高い学習済みの置換は、機械の出力側にも反映する(そうしないと自分の置換を「人が直した」と数えて自己強化してしまう)
                seg["text"], ln = auto_learned_replace(seg["text"], lrules, lfb)
                learn_n += ln
            original.append({"start": seg["start"], "end": seg["end"], "text": seg["text"], **machine_conf(s)})   # 機械の出力をそのまま残す(修正からの学習・精度の測定に使う)
            all_words.extend(row_words(s, spec["start"]))
            seg["text"], n = apply_replacements(seg["text"], pairs)
            dict_n += n
            segs.append(seg)
            job["segments"] = len(segs)
        if job["cancel"]:
            raise Cancelled()
        now = int(time.time() * 1000)
        fields = {"start": spec["start"], "end": spec["end"], "whole": spec["whole"], "duration": spec["duration"], "model": spec["model"],
                  "language": spec["language"], "params": {"beam": spec["beam"], "vadMode": spec["vadMode"], "boost": spec["boost"], "device": job.get("device", ""), "glossary": spec["glossary"][:50],
                                                           "autoDict": bool(spec.get("autoDict")), "dictApplied": dict_n, "wordSplit": bool(spec.get("wordSplit")),
                                                           "splitChars": spec.get("splitChars"), "stripPunct": spec.get("stripPunct", True) is not False,
                                                           "autoLearned": bool(spec.get("autoLearned")), "learnApplied": learn_n, "glossAuto": spec.get("glossAuto", [])[:20],
                                                           "context": context_record(spec)},
                  "speakers": [], "segments": segs, "original": original, "updatedAt": now,
                  "recognition": {"runs": [recognition_run(spec, job, total, time.monotonic() - t_rec)]}}
        if job.get("vad"):
            fields["params"]["vadUsed"] = job["vad"].get("used")
            note = vad_note(job["vad"])
            if note:
                spec.setdefault("warnings", []).append(note)
                job["vadNote"] = note
        tid = fill_doc(spec, fields) if spec.get("intoDoc") else None
        if tid is None:
            tid = uuid.uuid4().hex[:12]
            doc = dict({"schema": "transcribe/v1", "id": tid, "title": spec["title"], "sourcePath": spec["sourcePath"], "sourceName": spec["sourceName"]},
                       **fields, createdAt=now)
            if spec.get("clip"):
                doc["clip"] = spec["clip"]   # youtube-tools-clip/v1 の中身そのもの(transcript/v1 にもそのまま入る)
            if spec.get("evalSet"):
                doc["evalSet"] = True
            atomic_write(tx_path(tid), json.dumps(doc, ensure_ascii=False, indent=1).encode("utf-8"))
        try:
            write_words(tid, all_words, spec["model"])
        except OSError as e:
            log.warning("単語の時刻を保存できませんでした: %s %s", tid, e)
        job["tid"], job["progress"], job["state"], job["phase"] = tid, 1.0, "done", "完了"
        if spec.get("autoRedo") and any(SPARSE_FLAG in g["flag"] for g in segs):   # 疑わしい所を自動で認識し直す(設定。既定オフ。③-2)
            try:
                add_job(redo_spec(tid, {"redoLarge": spec.get("redoLarge", True), "oldLp": sparse_lp}), "redo")
            except ApiError as e:
                job["warnings"] = list(job.get("warnings") or []) + ["疑わしい所の認識し直しを始められませんでした: " + e.message]
    except Cancelled:
        job["state"], job["phase"] = "cancelled", "中止しました"
    except ApiError as e:
        job["state"], job["error"], job["phase"] = "error", e.message, "失敗"
    except Exception as e:  # 想定外の失敗でもワーカーは止めない
        job["state"], job["error"], job["phase"] = "error", "内部エラー: %s %s" % (e.__class__.__name__, str(e)[:200]), "失敗"
    finally:
        try:
            if os.path.exists(wav):
                os.unlink(wav)
        except OSError:
            pass


def worker():
    while True:
        try:
            _priority, _seq, jid = _queue.get(timeout=60)
        except queue.Empty:
            release_idle_models()   # ジョブが無い間に、長く使っていないモデルを手放す
            continue
        work_one(jid)


def work_one(jid):
    job = _jobs.get(jid)
    try:
        if job and job["state"] == "queued" and not job["cancel"]:
            sp = job.get("spec") or {}
            info = {"id": job["id"], "kind": job.get("kind", "transcribe"), "model": sp.get("model", ""), "title": str(sp.get("title", ""))[:60], "at": int(time.time())}
            write_mark(info)
            t0 = time.time()
            # 重い処理の同時実行数の上限(入口の中では他のツールの解析・書き出しと順番を待つ。ytt_core.jobs)
            with _heavy.SLOTS.slot(TOOL_ID, info["title"], cancelled=lambda: job["cancel"],
                                   on_wait=lambda: job.update(phase=_heavy.WAIT_MESSAGE)) as ok:
                if not ok:
                    job["state"], job["phase"] = "cancelled", "中止しました"
                    return
                log.info("ジョブ開始 %s %s モデル=%s(メモリ %s)", info["kind"], info["id"], info["model"], _mem())
                run_job(job)
            log.info("ジョブ終了 %s %s 状態=%s %.0f秒(メモリ %s)%s", info["kind"], info["id"], job["state"], time.time() - t0, _mem(), (" エラー: " + str(job.get("error"))) if job.get("error") else "")
        elif job and job["state"] == "queued":
            job["state"], job["phase"] = "cancelled", "中止しました"
    except Exception as e:   # 想定外でもワーカーを止めない(止まると、以後のジョブが動かないまま待機列に残る)
        log.exception("ワーカーで例外")
        if job:
            job["state"], job["error"], job["phase"] = "error", "内部エラー: %s %s" % (e.__class__.__name__, str(e)[:200]), "失敗"
    finally:
        _model_used[0] = time.time()   # 手放すまでの時間は、ジョブが終わった時から数える
        write_mark(None)


def cancel_job(jid):
    job = _jobs.get(str(jid))
    if not job:
        raise ApiError("not_found", "ジョブが見つかりません", 404)
    job["cancel"] = True
    if job["state"] == "queued":
        job["state"], job["phase"] = "cancelled", "中止しました"
    p = job.get("proc")
    if p and p.poll() is None:
        try:
            p.terminate()
        except OSError:
            pass


# ---------- 話者の自動判別(sherpa-onnx) ----------
# 流れ: 音声を取り出す → 「誰がいつ話したか」の区間を求める(diarization) → 文字起こしの各行に、重なりが最も長い人を割り当てる。
# 文字起こしモデルとは独立に動くので、どのモデルで作った文字起こしにも使える。CPU で動く(PyTorch 不要)。
DIAR_DIR = os.path.join(DATA_DIR, "models", "diar")
DIAR_SEG = {"file": "segmentation.onnx", "member": "sherpa-onnx-pyannote-segmentation-3-0/model.onnx", "label": "話者の切り替わり検出",
            "url": "https://github.com/k2-fsa/sherpa-onnx/releases/download/speaker-segmentation-models/sherpa-onnx-pyannote-segmentation-3-0.tar.bz2",
            "sha256": "24615ee884c897d9d2ba09bb4d30da6bb1b15e685065962db5b02e76e4996488", "max": 40 * 1024 * 1024}
_GH = "https://github.com/k2-fsa/sherpa-onnx/releases/download/speaker-recongition-models/"
# 声の特徴を取り出すモデル(どれが日本語の音声に合うかは、実際の音声で比べないと分からないので、選べるようにしてある)
DIAR_EMBS = {
    "voxceleb": {"file": "embedding-voxceleb.onnx", "member": None, "label": "VoxCeleb ResNet34(多言語の声で学習・おすすめ)", "mb": 27, "max": 80 * 1024 * 1024,
                 "url": _GH + "wespeaker_en_voxceleb_resnet34_LM.onnx", "sha256": "e9848563da86f263117134dfd7ad63c92355b37de492b55e325400c9d9c39012"},
    "campplus": {"file": "embedding-campplus.onnx", "member": None, "label": "3D-Speaker CAM++(中国語+英語)", "mb": 28, "max": 80 * 1024 * 1024,
                 "url": _GH + "3dspeaker_speech_campplus_sv_zh_en_16k-common_advanced.onnx", "sha256": "aa3cfc16963a10586a9393f5035d6d6b57e98d358b347f80c2a30bf4f00ceba2"},
    "standard": {"file": "embedding.onnx", "member": None, "label": "3D-Speaker ERes2Net(中国語。v0.3 の標準)", "mb": 40, "max": 120 * 1024 * 1024,
                 "url": _GH + "3dspeaker_speech_eres2net_base_sv_zh-cn_3dspeaker_16k.onnx", "sha256": "1a331345f04805badbb495c775a6ddffcdd1a732567d5ec8b3d5749e3c7a5e4b"},
}
DIAR_EMB_DEFAULT = "voxceleb"
MAX_DIAR_SEC = 3 * 3600
MAX_SPEAKERS = 20
MIXED_FLAG = "声が混ざっている可能性"
WEAK_FLAG = "話者が不確か"
NONE_FLAG = "話者を判別できなかった"
SPK_COLORS = ["#2f62d6", "#d9534f", "#2e9e5b", "#c98a12", "#8a4fd6", "#0f9aa8", "#d6479a", "#6b7280"]


def has_sherpa():
    if worker_fake():
        return True
    return worker_has("sherpa_onnx", "numpy")


def _diar_path(item):
    return os.path.join(DIAR_DIR, item["file"])


def _have(item):
    return os.path.isfile(_diar_path(item)) and os.path.getsize(_diar_path(item)) > 1000


def diar_info():
    return {"ready": backend_name() == "fake" or has_sherpa(), "segReady": _have(DIAR_SEG), "default": DIAR_EMB_DEFAULT,
            "embeddings": [{"key": k, "label": v["label"], "mb": v["mb"], "ready": _have(v)} for k, v in DIAR_EMBS.items()]}


def _download_verified(job, item, tmp):
    """固定の URL からダウンロードし、SHA-256 が想定と一致したものだけを受け入れる(改ざん・別ファイルの混入を防ぐ)。"""
    req = urllib.request.Request(item["url"], headers={"User-Agent": "transcribe-tool"})
    h, done = hashlib.sha256(), 0
    with urllib.request.urlopen(req, timeout=30) as r, open(tmp, "wb") as f:
        total = int(r.headers.get("Content-Length") or 0)
        while True:
            if job["cancel"]:
                raise Cancelled()
            chunk = r.read(256 * 1024)
            if not chunk:
                break
            done += len(chunk)
            if done > item["max"]:
                raise ApiError("model_download", "モデルのサイズが想定より大きいため中止しました", 500)
            h.update(chunk)
            f.write(chunk)
            if total:
                job["phase"] = "話者判別のモデルをダウンロード中(%s %d%%)" % (item["label"], min(100, done * 100 // total))
    if h.hexdigest() != item["sha256"]:
        raise ApiError("model_hash", "ダウンロードしたモデルが想定と一致しません(配布元で差し替えられた可能性があります)。ツールの更新を確認してください", 500)


def ensure_diar_models(job, emb=DIAR_EMB_DEFAULT):
    if worker_fake():   # テスト用(ワーカーの中の偽の判別を使う。モデルはダウンロードしない)
        return
    os.makedirs(DIAR_DIR, exist_ok=True)
    for item in (DIAR_SEG, DIAR_EMBS[emb]):
        dest = _diar_path(item)
        if os.path.isfile(dest) and os.path.getsize(dest) > 1000:
            continue
        tmp, part = dest + ".download", dest + ".part"
        try:
            _download_verified(job, item, tmp)
            if item["member"]:  # tar.bz2 から model.onnx だけを取り出す(展開先のパスは tar の中身に依存させない)
                with tarfile.open(tmp, "r:bz2") as tf:
                    m = tf.getmember(item["member"])
                    if not m.isfile() or m.size > item["max"]:
                        raise ApiError("model_download", "モデルの形式が想定と違います", 500)
                    with tf.extractfile(m) as src, open(part, "wb") as out:
                        shutil.copyfileobj(src, out)
                os.replace(part, dest)
            else:
                os.replace(tmp, dest)
        except (urllib.error.URLError, OSError, tarfile.TarError, KeyError) as e:
            raise ApiError("model_download", "話者判別のモデルをダウンロードできませんでした(初回はインターネット接続が必要です): %s" % str(e)[:150], 500)
        finally:
            for x in (tmp, part):
                try:
                    if os.path.exists(x):
                        os.unlink(x)
                except OSError:
                    pass


class WavRef:
    """16kHz・モノラル・16bit の wav を「読まずに」表す(サーバーのプロセス用)。audio[a:b] は WavSlice になり、
    認識ワーカーに渡すと、ワーカーがその範囲だけを読む。サーバーのプロセスに numpy(と音声全体のメモリ)を持ち込まないため。"""

    def __init__(self, path):
        with wave.open(path, "rb") as w:
            if w.getnchannels() != 1 or w.getsampwidth() != 2 or w.getframerate() != 16000:
                raise ApiError("diar_failed", "音声の形式が想定と違います", 500)
            self.n = w.getnframes()
        self.path = path

    def __len__(self):
        return self.n

    def __getitem__(self, sl):
        if not isinstance(sl, slice) or sl.step not in (None, 1):
            raise TypeError("WavRef は audio[a:b] の形でだけ使えます")
        a, b, _ = sl.indices(self.n)
        return WavSlice(self.path, a, max(a, b))


class WavSlice:
    def __init__(self, path, a, b):
        self.path, self.a, self.b = path, a, b

    def __len__(self):
        return self.b - self.a


def read_wav_f32(path):
    if not IN_WORKER:
        return WavRef(path)
    import numpy as np
    with wave.open(path, "rb") as w:
        if w.getnchannels() != 1 or w.getsampwidth() != 2 or w.getframerate() != 16000:
            raise ApiError("diar_failed", "音声の形式が想定と違います", 500)
        raw = w.readframes(w.getnframes())
    return np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0


def diarize_real(job, wav, num, emb=DIAR_EMB_DEFAULT):
    """話者の判別。sherpa-onnx(ネイティブコード)は認識ワーカー(別プロセス)の中で動かす。戻り値は [(開始, 終了, 話者番号)]。"""
    if IN_WORKER:
        return _diarize_local(job, wav, num, emb)
    turns = WORKER.call("diarize", {"wav": wav, "num": int(num), "emb": emb}, job)
    return [(float(a), float(b), int(k)) for a, b, k in turns]


def _diarize_local(job, wav, num, emb=DIAR_EMB_DEFAULT):
    import sherpa_onnx as so
    threads = max(1, min(4, os.cpu_count() or 2))
    cfg = so.OfflineSpeakerDiarizationConfig(
        segmentation=so.OfflineSpeakerSegmentationModelConfig(
            pyannote=so.OfflineSpeakerSegmentationPyannoteModelConfig(model=_diar_path(DIAR_SEG)), num_threads=threads),
        embedding=so.SpeakerEmbeddingExtractorConfig(model=_diar_path(DIAR_EMBS[emb]), num_threads=threads),
        clustering=so.FastClusteringConfig(num_clusters=num if num > 0 else -1, threshold=0.5),
        min_duration_on=0.1, min_duration_off=0.3)   # 短い相づちを落としにくくする
    if not cfg.validate():
        raise ApiError("diar_failed", "話者判別の設定を読み込めませんでした(モデルファイルが壊れている可能性があります。models フォルダを削除して、もう一度試してください)", 500)
    sd = so.OfflineSpeakerDiarization(cfg)
    if sd.sample_rate != 16000:
        raise ApiError("diar_failed", "話者判別のモデルの形式が想定と違います", 500)
    samples = read_wav_f32(wav)

    def cb(done, total, *_):
        if total:
            job["progress"] = min(0.99, done / total)
        return 1 if job["cancel"] else 0   # 0 以外を返すと中断する

    res = sd.process(samples, callback=cb).sort_by_start_time()
    if job["cancel"]:
        raise Cancelled()
    return [(float(r.start), float(r.end), int(r.speaker)) for r in res]


def diarize_fake(job, total, num):
    """テスト用: 10秒ごとに話者が入れ替わる(行の途中で切り替わる場面も作る)。"""
    n, t, k, turns = (num or 2), 0.0, 0, []
    while t < total:
        if job["cancel"]:
            raise Cancelled()
        e = min(total, t + 10.0)
        turns.append((t, e, k % n))
        job["progress"] = min(0.99, e / total)
        time.sleep(float(os.environ.get("TRANSCRIBE_FAKE_DELAY", "0.05")))
        t, k = e, k + 1
    return turns


def assign_speakers(segs, turns, offset):
    """各行に、重なりがいちばん長い話者を割り当てる。戻り値: [(話者番号 or None, 声が混ざっているか, 話者が不確か)]。
    不確か = 短い行(0.8秒未満。声の特徴が取りにくい)、行の半分以上が話者区間の外、または最寄りの区間で代用した行。
    turns は [(開始, 終了, 話者番号)](音声先頭からの秒)、offset を足すと元動画の時刻になる。"""
    ts = sorted((a + offset, b + offset, s) for a, b, s in turns)
    starts = [t[0] for t in ts]
    dmax = max((t[1] - t[0] for t in ts), default=0.0)
    out = []
    for sg in segs:
        a, b = sg["start"], sg["end"]
        dur = max(1e-6, b - a)
        lo, hi = bisect.bisect_left(starts, a - dmax), bisect.bisect_right(starts, b)
        ov = {}
        for x, y, s in ts[lo:hi]:
            d = min(b, y) - max(a, x)
            if d > 0:
                ov[s] = ov.get(s, 0.0) + d
        if ov:
            ranked = sorted(ov.items(), key=lambda kv: -kv[1])
            second = ranked[1][1] if len(ranked) > 1 else 0.0
            out.append((ranked[0][0], second >= max(1.0, 0.3 * dur), dur < 0.8 or ranked[0][1] / dur < 0.5))
            continue
        near, best = None, 1.5   # 重なりがなければ、前後1.5秒以内でいちばん近い区間
        for x, y, s in ts[lo:hi + 20]:
            gap = max(x - b, a - y, 0.0)
            if gap < best:
                near, best = s, gap
        out.append((near, False, True))
    return out


def apply_diarization(tid, turns, offset, requested, emb=DIAR_EMB_DEFAULT):
    """最新の文字起こしを読み直して話者を書き込む(判別中に行を編集されていても、時刻で割り当てるので矛盾しない)。
    読み直し〜書き込みは保存と同じロックの中で行う(間に画面の保存が挟まると、その保存が黙って上書きされるため)。"""
    with _save_lock:
        return _apply_diarization(tid, turns, offset, requested, emb)


def _apply_diarization(tid, turns, offset, requested, emb):
    doc = read_transcript(tid)
    segs = doc.get("segments") or []
    res = assign_speakers(segs, turns, offset)
    spent = {}
    for sg, (sp, _, _) in zip(segs, res):
        if sp is not None:
            spent[sp] = spent.get(sp, 0.0) + max(0.0, sg["end"] - sg["start"])
    order = sorted(spent, key=lambda k: -spent[k])[:MAX_SPEAKERS]   # 話した時間が長い人から「話者1」「話者2」…
    idmap = {raw: "S%d" % (i + 1) for i, raw in enumerate(order)}
    speakers = [{"id": "S%d" % (i + 1), "name": "話者%d" % (i + 1), "color": SPK_COLORS[i % len(SPK_COLORS)]} for i in range(len(order))]
    unsure = 0
    for sg, (sp, mixed, weak) in zip(segs, res):
        sg["speaker"] = idmap.get(sp, "")
        parts = [x for x in str(sg.get("flag", "")).split("、") if x and x not in (MIXED_FLAG, WEAK_FLAG, NONE_FLAG)]
        mark = NONE_FLAG if not sg["speaker"] else MIXED_FLAG if mixed else WEAK_FLAG if weak else ""
        if mark:
            parts.append(mark)
            unsure += 1
        sg["flag"] = "、".join(parts)[:100]
    bak = os.path.join(TX_DIR, ".bak")
    os.makedirs(bak, exist_ok=True)
    shutil.copy2(tx_path(tid), os.path.join(bak, tid + ".pre-diarize.json"))   # 直前の状態を1世代だけ残す
    try:
        hist_snapshot(tid, force=True)      # 履歴にも残す(画面の「履歴」から戻せる)
    except OSError:
        pass
    doc.update({"speakers": speakers, "segments": segs, "updatedAt": int(time.time() * 1000),
                "diarization": {"engine": "sherpa-onnx", "embedding": emb, "requested": requested, "found": len(order), "unsure": unsure, "at": int(time.time() * 1000)}})
    atomic_write(tx_path(tid), json.dumps(doc, ensure_ascii=False, indent=1).encode("utf-8"))
    return len(order), unsure


def validate_diarize(req):
    tid = str(req.get("tid") or "")
    doc = read_transcript(tid)
    if not doc.get("segments"):
        raise ApiError("empty", "行がないため、話者を判別できません", 400)
    check_source(doc.get("sourcePath"))
    try:
        n = int(req.get("numSpeakers") or 0)
    except (TypeError, ValueError):
        n = 0
    with _jobs_lock:
        if any(j.get("kind") in ("diarize", "retranscribe") and j["spec"].get("tid") == tid and j["state"] in ("queued", "loading", "extracting", "running") for j in _jobs.values()):
            raise ApiError("busy", "この文字起こしは、すでに別の処理(話者判別・再認識)の最中です", 409)
    emb = str(req.get("embedding") or DIAR_EMB_DEFAULT)
    names = []   # 出てくる人の名前(友人からの依頼の「話す人」。2026-10-01)
    for x in req.get("names") if isinstance(req.get("names"), list) else []:
        s = str(x or "").strip()[:60] if isinstance(x, str) else ""
        if s and not any(ord(ch) < 32 for ch in s) and s not in names and not DEFAULT_SPK_NAME.match(s):
            names.append(s)
    return {"tid": tid, "numSpeakers": n if 1 <= n <= 10 else 0, "names": names[:10], "embedding": emb if emb in DIAR_EMBS else DIAR_EMB_DEFAULT, "title": "話者判別: " + (str(doc.get("title") or "") or "無題")[:100],
            "recognize": req.get("recognize") is not False}   # A-3: 覚えている声と照らし合わせる(既定オン)


def single_speaker(tid, name):
    """話す人が1人: 判別せずに全部の行をその人に(名前が無ければ「話者1」)。-> 行の数"""
    with _save_lock:
        doc = read_transcript(tid)
        segs = doc.get("segments") or []
        for sg in segs:
            sg["speaker"] = "S1"
            sg["flag"] = "、".join(x for x in str(sg.get("flag", "")).split("、") if x and x not in (MIXED_FLAG, WEAK_FLAG, NONE_FLAG))[:100]
        bak = os.path.join(TX_DIR, ".bak")
        os.makedirs(bak, exist_ok=True)
        shutil.copy2(tx_path(tid), os.path.join(bak, tid + ".pre-diarize.json"))
        try:
            hist_snapshot(tid, force=True)
        except OSError:
            pass
        doc.update({"speakers": [{"id": "S1", "name": name or "話者1", "color": SPK_COLORS[0]}], "segments": segs, "updatedAt": int(time.time() * 1000),
                    "diarization": {"engine": "single", "requested": 1, "found": 1, "unsure": 0, "at": int(time.time() * 1000)}})
        atomic_write(tx_path(tid), json.dumps(doc, ensure_ascii=False, indent=1).encode("utf-8"))
        return len(segs)


def run_diarize(job):
    spec = job["spec"]
    wav = os.path.join(TMP_DIR, job["id"] + ".wav")
    if spec.get("numSpeakers") == 1:   # 1人なら判別しない(音声も取り出さない)
        try:
            single_speaker(spec["tid"], (spec.get("names") or [""])[0])
            job["speakers"], job["unsure"] = 1, 0
            job["named"] = [{"speaker": "S1", "name": spec["names"][0], "score": None}] if spec.get("names") else []
            job["tid"], job["progress"], job["state"], job["phase"] = spec["tid"], 1.0, "done", "完了"
        except Exception as e:
            job["state"], job["error"], job["phase"] = "error", "話者を付けられませんでした: %s %s" % (e.__class__.__name__, str(e)[:150]), "失敗"
        return
    try:
        os.makedirs(TMP_DIR, exist_ok=True)
        doc = read_transcript(spec["tid"])
        src = check_source(doc.get("sourcePath"))
        start, end = num(doc.get("start"), 0.0) or 0.0, num(doc.get("end"))
        span = (end if end else (media_duration(src) or 0.0)) - start
        if span > MAX_DIAR_SEC:
            raise ApiError("too_long", "話者判別は3時間までの範囲で使えます。範囲を分けて文字起こししてください", 400)
        job["state"], job["phase"], job["device"] = "extracting", "音声を取り出し中", "cpu"
        extract_audio(job, {"sourcePath": src, "start": start, "end": end}, wav)
        total = media_duration(wav) or span
        if backend_name() == "fake":
            job["state"], job["phase"] = "running", "話者を判別中"
            turns = diarize_fake(job, total, spec["numSpeakers"])
        else:
            if not has_sherpa():
                raise ApiError("no_sherpa", "話者判別の部品(sherpa-onnx)が入っていません。フォルダ内の install-diarize.bat(Mac は install-diarize.command)を実行してください", 400)
            job["state"] = "loading"
            ensure_diar_models(job, spec["embedding"])
            job["state"], job["phase"], job["progress"] = "running", "話者を判別中(CPU。長い音声は時間がかかります)", 0.0
            try:
                turns = diarize_real(job, wav, spec["numSpeakers"], spec["embedding"])
            except (Cancelled, ApiError):
                raise
            except Exception as e:
                raise ApiError("diar_failed", "話者の判別に失敗しました: %s %s" % (e.__class__.__name__, str(e)[:150]), 500)
        if job["cancel"]:
            raise Cancelled()
        job["speakers"], job["unsure"] = apply_diarization(spec["tid"], turns, start, spec["numSpeakers"], spec["embedding"])
        if spec.get("recognize", True):   # A-3: 覚えている声と照らし合わせて、仮の名前(話者n)に名前を付ける。失敗しても判別の結果は残す
            try:
                job["named"] = recognize_voices(job, spec["tid"], wav, start, spec["embedding"], spec.get("names") or None)
            except Cancelled:
                raise
            except Exception as e:
                log.warning("声の照らし合わせに失敗: %s %s", e.__class__.__name__, str(e)[:200])
                job["voiceError"] = "覚えている声との照らし合わせに失敗しました(話者の判別の結果はそのまま): %s" % str(e)[:120]
        job["tid"], job["progress"], job["state"], job["phase"] = spec["tid"], 1.0, "done", "完了"
    except Cancelled:
        job["state"], job["phase"] = "cancelled", "中止しました"
    except ApiError as e:
        job["state"], job["error"], job["phase"] = "error", e.message, "失敗"
    except Exception as e:
        job["state"], job["error"], job["phase"] = "error", "内部エラー: %s %s" % (e.__class__.__name__, str(e)[:200]), "失敗"
    finally:
        try:
            if os.path.exists(wav):
                os.unlink(wav)
        except OSError:
            pass


# ---------- 話者の声を覚える(A-3。docs/archive/backlog-ui-2026-09-27.md) ----------
# 名前を付けた話者の行の音声から「声の特徴」(sherpa-onnx の話者の埋め込み。判別モデルごとに別)を作って覚え、
# 次からの話者判別のあとで、見つかった話者を覚えている声と比べて名前を付ける。
# 声の特徴は個人を見分けられる情報なので、作業データ(voices/)にだけ置く(リポジトリ・パックには入れない)。
# 計算(numpy・sherpa-onnx)は認識ワーカーの中だけ(_embed_local)。サーバーでは読み込まない
VOICES_DIR = os.path.join(DATA_DIR, "voices")
VOICE_MATCH = 0.60        # 覚えている声とのコサイン類似度がこれ以上なら同じ人とみなす
VOICE_MARGIN = 0.08       # 2番目に近い声との差がこれより小さければ決めない(似た声を取り違えるより、名前を付けない方が安全)
VOICE_MIN_ROW = 1.0       # 声の特徴を取る行の最短(秒)。短い行(相づち)は特徴が安定しない
VOICE_MAX_ROWS = 40       # 1人あたり使う行の数の上限(長い行から)
VOICE_MAX_SEC = 240.0     # 1人あたり使う長さの上限(秒)
VOICE_MAX_PEOPLE = 300
DEFAULT_SPK_NAME = re.compile(r"^話者\d+$")   # 話者判別が付けた仮の名前(覚えない・声で付けた名前で置き換えてよい)
_voices_lock = threading.Lock()
# 一般的な名前(監査18。段1・2026-09-29 ユーザー決定): 声を覚えると、別の配信の「本人」「ゲスト」に同じ名前が付いてしまう(人ではなく役の名前)ので覚えない。
# 判定は is_generic_speaker_name の1か所(画面は preview の結果を出すだけ)。比べる前に NFKC・小文字・空白を寄せる(全角の「ＭＣ」・「Speaker 1」も同じに)
GENERIC_SPK_NAMES = frozenset(("本人", "ゲスト", "配信者", "私", "自分", "相手", "司会", "mc", "男性", "女性", "不明", "その他", "視聴者", "ナレーション",
                               "話者", "speaker", "スピーカー"))
GENERIC_SPK_FORM = re.compile(r"^(?:話者|speaker|spk|スピーカー)?(?:\d+|[a-z])$")   # 話者A・話者1・Speaker 1・英字1文字・数字だけ


def _spk_name_key(name):
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", str(name or "")).lower())


def is_generic_speaker_name(name):
    k = _spk_name_key(name)
    return bool(k) and (k in GENERIC_SPK_NAMES or bool(GENERIC_SPK_FORM.match(k)))


def voices_path(emb):
    return os.path.join(VOICES_DIR, emb + ".json")


def load_voices(emb):
    """{名前: {"vec": [...], "rows": 使った行の数, "sec": 使った秒, "updatedAt": ms}}(判別モデル emb ごと)"""
    try:
        with open(voices_path(emb), encoding="utf-8") as f:
            d = json.load(f)
    except (OSError, ValueError):
        return {}
    v = d.get("voices") if isinstance(d, dict) else None
    if not isinstance(v, dict):
        return {}
    return {str(k)[:60]: x for k, x in v.items() if isinstance(x, dict) and isinstance(x.get("vec"), list) and x["vec"]}


def save_voices(emb, voices):
    os.makedirs(VOICES_DIR, exist_ok=True)
    atomic_write(voices_path(emb), json.dumps({"schema": "ytt-voices/v1", "embedding": emb, "voices": voices}, ensure_ascii=False).encode("utf-8"))


def _unit(v):
    s = math.sqrt(sum(x * x for x in v)) if v else 0.0
    return [x / s for x in v] if s > 0 else None


def _cos(a, b):
    """どちらも長さ 1 の特徴どうしのコサイン類似度(次元が違えば -1 = 比べられない)"""
    return sum(x * y for x, y in zip(a, b)) if a and b and len(a) == len(b) else -1.0


def voice_groups(segs, key):
    """行 → {キー: ([(開始, 終了)...], 合計秒)}。key(行) が空の行は使わない。
    短い行・「声が混ざっている」行は使わない。長い行から VOICE_MAX_ROWS 行・VOICE_MAX_SEC 秒まで"""
    by = {}
    for g in segs:
        k = key(g)
        if not k:
            continue
        a, b = num(g.get("start")), num(g.get("end"))
        if a is None or b is None or b - a < VOICE_MIN_ROW or MIXED_FLAG in str(g.get("flag") or ""):
            continue
        by.setdefault(k, []).append((a, b))
    out = {}
    for k, rs in by.items():
        rs.sort(key=lambda r: -(r[1] - r[0]))
        pick, tot = [], 0.0
        for a, b in rs[:VOICE_MAX_ROWS]:
            if tot >= VOICE_MAX_SEC:
                break
            pick.append((a, b))
            tot += b - a
        out[k] = (sorted(pick), tot)
    return out


def embed_groups(job, wav, emb, groups, offset):
    """groups: [[(開始, 終了)...]](元の動画の時刻)。wav は offset 秒から始まる音声。-> [長さ 1 の特徴 or None](groups と同じ並び)"""
    rel = [[[max(0.0, a - offset), max(0.0, b - offset)] for a, b in g] for g in groups]
    if backend_name() == "fake":
        return embed_fake(rel)
    if IN_WORKER:
        return _embed_local(job, wav, emb, rel)
    res = WORKER.call("embed", {"wav": wav, "emb": emb, "groups": rel}, job)
    return [[float(x) for x in v] if isinstance(v, list) and v else None for v in res]


def embed_fake(groups):
    """テスト用: 偽の話者判別(diarize_fake: 10秒ごとに入れ替わる)と同じ区切りの番号ごとに、向きの違う特徴"""
    out = []
    for g in groups:
        votes = {}
        for a, b in g:
            k = int(((a + b) / 2.0) // 10) % 2   # diarize_fake の既定(2人)と同じ入れ替わり
            votes[k] = votes.get(k, 0.0) + (b - a)
        if not votes:
            out.append(None)
            continue
        v = [0.1] * 8
        v[max(votes, key=votes.get)] = 1.0
        out.append(_unit(v))
    return out


def _embed_local(job, wav, emb, groups):
    """認識ワーカーの中だけで動く(numpy・sherpa-onnx)。区間ごとの特徴を長さで重みを付けて平均し、長さ 1 に"""
    import numpy as np
    import sherpa_onnx as so
    threads = max(1, min(4, os.cpu_count() or 2))
    cfg = so.SpeakerEmbeddingExtractorConfig(model=_diar_path(DIAR_EMBS[emb]), num_threads=threads)
    if not cfg.validate():
        raise ApiError("diar_failed", "声の特徴のモデルを読み込めませんでした(models フォルダを削除して、もう一度試してください)", 500)
    ex = so.SpeakerEmbeddingExtractor(cfg)
    samples, sr = read_wav_f32(wav), 16000
    total, done, out = max(1, sum(len(g) for g in groups)), 0, []
    for g in groups:
        vecs, weights = [], []
        for a, b in g:
            if job["cancel"]:
                raise Cancelled()
            done += 1
            job["progress"] = min(0.99, done / total)
            seg = samples[int(a * sr):int(b * sr)]
            if len(seg) < sr // 2:
                continue
            st = ex.create_stream()
            st.accept_waveform(sample_rate=sr, waveform=seg)
            st.input_finished()
            if not ex.is_ready(st):
                continue
            e = np.array(ex.compute(st), dtype=np.float32)
            n = float(np.linalg.norm(e))
            if n > 0:
                vecs.append(e / n)
                weights.append(b - a)
        if not vecs:
            out.append(None)
            continue
        m = np.average(np.stack(vecs), axis=0, weights=np.array(weights))
        n = float(np.linalg.norm(m))
        out.append([float(x) for x in (m / n)] if n > 0 else None)
    return out


def match_voices(found, voices):
    """found: {話者の id: 特徴}、voices: 覚えている声。-> {話者の id: (名前, 似ている度合い)}。
    VOICE_MATCH 以上・2番目との差が VOICE_MARGIN 以上のときだけ。1つの名前は1人にだけ(似ている順に決める)"""
    names = list(voices)
    cands = []
    for sid, v in found.items():
        if not v:
            continue
        sc = sorted(((_cos(v, voices[n]["vec"]), n) for n in names), reverse=True)
        if not sc or sc[0][0] < VOICE_MATCH:
            continue
        if len(sc) > 1 and sc[0][0] - sc[1][0] < VOICE_MARGIN:
            continue
        cands.append((sc[0][0], sid, sc[0][1]))
    out, used = {}, set()
    for score, sid, name in sorted(cands, reverse=True):
        if sid in out or name in used:
            continue
        out[sid] = (name, round(score, 3))
        used.add(name)
    return out


def recognize_voices(job, tid, wav, offset, emb, names=None):
    """話者判別のあと: 見つかった話者を覚えている声と比べ、仮の名前(話者n)のままの話者に名前を付ける。-> [{"speaker", "name", "score"}]。
    names(出てくる人の名前。友人からの依頼)があれば、照らし合わせをその名前だけにし、最後に仮の名前の話者と使っていない名前が1つずつ残れば消去法で付ける(score None)"""
    voices = load_voices(emb)
    if names:
        voices = {n: v for n, v in voices.items() if n in names}
    got = {}
    if voices:
        doc = read_transcript(tid)
        grp = voice_groups(doc.get("segments") or [], lambda g: g.get("speaker") or "")
        ids = list(grp)
        if ids:
            job["phase"] = "覚えている声と照らし合わせ中"
            vecs = embed_groups(job, wav, emb, [grp[i][0] for i in ids], offset)
            got = match_voices(dict(zip(ids, vecs)), voices)
    if not got and not names:
        return []
    named = []
    with _save_lock:   # 読み直し〜書き込みは保存と同じロックの中(話者判別の書き込みと同じ)
        doc = read_transcript(tid)
        taken = {str(s.get("name") or "") for s in doc.get("speakers") or [] if isinstance(s, dict)}
        for s in doc.get("speakers") or []:
            hit = got.get(s.get("id")) if isinstance(s, dict) else None
            if hit and DEFAULT_SPK_NAME.match(str(s.get("name") or "")) and hit[0] not in taken:
                s["name"] = hit[0]
                taken.add(hit[0])
                named.append({"speaker": s["id"], "name": hit[0], "score": hit[1]})
        if names:   # 消去法: 名前の無い話者と使っていない名前が1つずつなら、その人
            left = [s for s in doc.get("speakers") or [] if isinstance(s, dict) and DEFAULT_SPK_NAME.match(str(s.get("name") or ""))]
            unused = [n for n in names if n not in taken]
            if len(left) == 1 and len(unused) == 1:
                left[0]["name"] = unused[0]
                named.append({"speaker": left[0]["id"], "name": unused[0], "score": None})
        if named:
            doc["updatedAt"] = int(time.time() * 1000)
            atomic_write(tx_path(tid), json.dumps(doc, ensure_ascii=False, indent=1).encode("utf-8"))
    return named


VOICE_LEARN_TAGS = ("overlap", "bgm", "unclear")   # この印の行は覚えない(声が重なる・BGM が大きい・聞き取れない。監査17)
EVAL_SET_VOICE_MSG = "評価用の文字起こしでは声を覚えません(評価用のデータを、ほかの文書の話者の名前付けに使わないため)。評価用を外してから行ってください"


def voice_learn_plan(doc):
    """声を覚えるときに使う行(監査17。段1): voice_groups の条件(1秒以上・声が混ざっていない)に加えて、校正済みで、音のメモ(重なり・BGM・聞き取れない)が無い行だけ。
    話者判別のときの照らし合わせ(recognize_voices)は voice_groups のまま(校正前の文書でも名前が付くように。変えない決定)。
    -> {"groups": {名前: ([(開始, 終了)...], 秒)}, "speakers": {名前: [話者の id]}, "refused": [{"name", "speakers", "reason": "generic"|"no_rows"}],
        "skipped": {"unproofed", "tagged", "mixed", "short"}(覚える人の行のうち使わなかった数。理由は 1秒未満 → 混ざる → 音のメモ → 未校正 の順に1つ)}"""
    names = {s.get("id"): str(s.get("name") or "").strip()[:60] for s in doc.get("speakers") or [] if isinstance(s, dict)}
    by_name, refused = {}, {}
    for sid, n in names.items():
        if not n or DEFAULT_SPK_NAME.match(n):
            continue   # 仮の名前 = 名前を付けていない(断った扱いにもしない)
        if is_generic_speaker_name(n):
            refused.setdefault(n, {"name": n, "speakers": [], "reason": "generic"})["speakers"].append(sid)
            continue
        by_name.setdefault(n, []).append(sid)
    who = {sid: n for n, sids in by_name.items() for sid in sids}
    skipped = {"unproofed": 0, "tagged": 0, "mixed": 0, "short": 0}
    ok = []
    for g in doc.get("segments") or []:
        if not isinstance(g, dict) or g.get("speaker") not in who:
            continue
        a, b = num(g.get("start")), num(g.get("end"))
        tags = g.get("tags") if isinstance(g.get("tags"), list) else []
        if a is None or b is None or b - a < VOICE_MIN_ROW:
            skipped["short"] += 1
        elif MIXED_FLAG in str(g.get("flag") or ""):
            skipped["mixed"] += 1
        elif any(t in tags for t in VOICE_LEARN_TAGS):
            skipped["tagged"] += 1
        elif g.get("proofed") is not True:
            skipped["unproofed"] += 1
        else:
            ok.append(g)
    groups = voice_groups(ok, lambda g: who.get(g.get("speaker")) or "")
    for n, sids in by_name.items():
        if n not in groups:
            refused[n] = {"name": n, "speakers": sids, "reason": "no_rows"}
    return {"groups": groups, "speakers": {n: sids for n, sids in by_name.items() if n in groups},
            "refused": sorted(refused.values(), key=lambda r: r["name"]), "skipped": skipped}


def _voice_emb(req, doc):
    emb = str(req.get("embedding") or (doc.get("diarization") or {}).get("embedding") or DIAR_EMB_DEFAULT)
    return emb if emb in DIAR_EMBS else DIAR_EMB_DEFAULT


def voice_preview(tid, emb):
    """覚える前の確認(GET /api/voices/preview。読むだけ・ジョブを作らない。監査17・18)"""
    doc = read_transcript(str(tid or ""))
    emb = _voice_emb({"embedding": emb}, doc)
    plan = voice_learn_plan(doc)
    voices = load_voices(emb)
    people = []
    for n in sorted(plan["groups"]):
        rs, sec = plan["groups"][n]
        old = voices.get(n)
        people.append({"name": n, "speaker": plan["speakers"][n][0], "speakers": plan["speakers"][n], "rows": len(rs), "sec": round(sec, 1), "exists": bool(old),
                       "old": {"rows": int(old.get("rows") or 0), "sec": float(old.get("sec") or 0.0), "updatedAt": int(old.get("updatedAt") or 0)} if old else None})
    return {"tid": tid, "embedding": emb, "evalSet": doc.get("evalSet") is True, "people": people, "refused": plan["refused"], "skipped": plan["skipped"]}


def validate_voice_learn(req):
    tid = str(req.get("tid") or "")
    doc = read_transcript(tid)
    if doc.get("evalSet") is True:   # 監査02: 評価用の声を覚えると、評価用のデータがほかの文書の名前付けに使われる
        raise ApiError("eval_set", EVAL_SET_VOICE_MSG, 400)
    want = req.get("names")
    if not isinstance(want, list) or not all(isinstance(n, str) for n in want):   # 画面と API の版はそろえて上げる(古い形は受けない = 確認を飛ばして覚えない)
        raise ApiError("bad_request", "覚える人の指定(names)がありません。画面を読み込み直してから、もう一度押してください", 400)
    plan = voice_learn_plan(doc)
    names = [n for n in dict.fromkeys(str(x).strip()[:60] for x in want) if n in plan["groups"]]
    if not names:
        gen = [r["name"] for r in plan["refused"] if r["reason"] == "generic"]
        raise ApiError("no_names", "覚えられる話者がいません。校正済みの行(1秒以上・音のメモなし)がある、名前を付けた話者の声だけを覚えます"
                       "(「話者1」のような仮の名前%sは覚えません)" % ("・「%s」のような一般的な名前" % "」「".join(gen[:3]) if gen else ""), 400)
    check_source(doc.get("sourcePath"))
    emb = _voice_emb(req, doc)
    same = {str(x) for x in req.get("confirmSame") or [] if isinstance(x, str)}
    voices = load_voices(emb)
    ask = [n for n in names if n in voices and n not in same]
    if ask:   # 監査18: 既にある名前に足すのは「同じ人」と確かめたときだけ(別人の声が混ざると、その名前の照らし合わせが外れる)
        raise ApiError("confirm_same", "「%s」の声はもう覚えています。同じ人か確かめてから、もう一度押してください" % "」「".join(ask), 409, extra={"names": ask})
    with _jobs_lock:
        if any(j.get("kind") in ("diarize", "retranscribe", "redo", "voice-learn") and j["spec"].get("tid") == tid and j["state"] in ACTIVE_STATES for j in _jobs.values()):
            raise ApiError("busy", "この文字起こしは、すでに別の処理(話者判別・再認識・声を覚える)の最中です", 409)
    return {"tid": tid, "embedding": emb, "names": names, "confirmSame": sorted(same & set(names)),
            "title": "声を覚える: " + (str(doc.get("title") or "") or "無題")[:100]}


def run_voice_learn(job):
    spec = job["spec"]
    wav = os.path.join(TMP_DIR, job["id"] + ".wav")
    try:
        os.makedirs(TMP_DIR, exist_ok=True)
        doc = read_transcript(spec["tid"])
        if doc.get("evalSet") is True:   # 待っている間に評価用へ変えた場合も断る(監査02)
            raise ApiError("eval_set", EVAL_SET_VOICE_MSG, 400)
        src = check_source(doc.get("sourcePath"))
        start, end = num(doc.get("start"), 0.0) or 0.0, num(doc.get("end"))
        plan = voice_learn_plan(doc)   # 読み直した文書で決め直し、確認した人(spec["names"])との積だけを覚える(確認のあとで名前を付けた人を黙って覚えない)
        grp = {n: plan["groups"][n] for n in spec.get("names") or [] if n in plan["groups"]}
        if not grp:
            raise ApiError("no_names", "覚えられる話者の行がありません(待っている間に名前・校正済みの印が変わった可能性があります)", 400)
        if backend_name() != "fake" and not has_sherpa():
            raise ApiError("no_sherpa", "声を覚えるには話者判別の部品(sherpa-onnx)が要ります。フォルダ内の install-diarize.bat を実行してください", 400)
        job["state"], job["phase"], job["device"] = "extracting", "音声を取り出し中", "cpu"
        extract_audio(job, {"sourcePath": src, "start": start, "end": end}, wav)
        if backend_name() != "fake":
            job["state"] = "loading"
            ensure_diar_models(job, spec["embedding"])
        job["state"], job["phase"], job["progress"] = "running", "声の特徴を取り出し中(CPU)", 0.0
        people = sorted(grp)
        vecs = embed_groups(job, wav, spec["embedding"], [grp[n][0] for n in people], start)
        if job["cancel"]:
            raise Cancelled()
        learned = []
        with _voices_lock:
            voices = load_voices(spec["embedding"])
            same = set(spec.get("confirmSame") or [])
            for n, v in zip(people, vecs):
                if not v:
                    continue
                rows, sec = len(grp[n][0]), grp[n][1]
                old = voices.get(n)
                if old and n not in same:   # 待っている間にほかで同じ名前を覚えた(確かめていない人の声には足さない)
                    job.setdefault("warnings", []).append("「%s」の声は、待っている間にほかで覚えられたので足しませんでした(同じ人なら、もう一度「声を覚える」を押してください)" % n)
                    continue
                if old and len(old["vec"]) == len(v):   # 前に覚えた声と、使った長さで重みを付けて混ぜる(配信ごとの声の揺れをならす)
                    w0 = min(float(old.get("sec") or 0.0), 3600.0)
                    v = _unit([a * w0 + b * sec for a, b in zip(old["vec"], v)]) or v
                    rows, sec = rows + int(old.get("rows") or 0), sec + w0
                voices[n] = {"vec": [round(x, 6) for x in v], "rows": rows, "sec": round(sec, 1), "updatedAt": int(time.time() * 1000)}
                learned.append(n)
            if len(voices) > VOICE_MAX_PEOPLE:
                raise ApiError("too_many", "覚えられる声は %d 人までです(使わない声を消してください)" % VOICE_MAX_PEOPLE, 400)
            if learned:
                save_voices(spec["embedding"], voices)
        if not learned:
            raise ApiError("no_voice", "声の特徴を取り出せませんでした(行が短すぎる・音声が無い可能性があります)", 400)
        job["learned"] = learned
        job["speakers"] = len(learned)
        job["tid"], job["progress"], job["state"], job["phase"] = spec["tid"], 1.0, "done", "完了"
    except Cancelled:
        job["state"], job["phase"] = "cancelled", "中止しました"
    except ApiError as e:
        job["state"], job["error"], job["phase"] = "error", e.message, "失敗"
    except Exception as e:
        job["state"], job["error"], job["phase"] = "error", "内部エラー: %s %s" % (e.__class__.__name__, str(e)[:200]), "失敗"
    finally:
        try:
            if os.path.exists(wav):
                os.unlink(wav)
        except OSError:
            pass


def voices_summary():
    """覚えている声の一覧(特徴そのものは返さない)。{判別モデル: [{"name", "rows", "sec", "updatedAt"}]}"""
    out = {}
    for emb in DIAR_EMBS:
        v = load_voices(emb)
        if v:
            out[emb] = sorted(({"name": n, "rows": int(x.get("rows") or 0), "sec": float(x.get("sec") or 0.0), "updatedAt": int(x.get("updatedAt") or 0),
                                "generic": is_generic_speaker_name(n)}   # 一般的な名前で前に覚えた声(消さない。一覧で「忘れることをおすすめします」と出す)
                               for n, x in v.items()), key=lambda r: r["name"])
    return out


def delete_voice(emb, name):
    if emb not in DIAR_EMBS:
        raise ApiError("bad_request", "判別モデルの指定が正しくありません", 400)
    with _voices_lock:
        voices = load_voices(emb)
        if name not in voices:
            raise ApiError("not_found", "その声は覚えていません", 404)
        del voices[name]
        save_voices(emb, voices)


# ---------- 置換辞書・修正からの学習 ----------
def load_settings():
    try:
        with open(SETTINGS, "r", encoding="utf-8-sig") as f:   # メモ帳の「UTF-8 (BOM 付き)」で直されても読めるように
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


# ほかの画面から直してよい設定と、その値の検査(送ったキーだけ直す。全体を上書きしない = 窓を並べても他の値を消さない。気が利く画面へ 1)
SETTINGS_PATCH_KEYS = {"packLoudness": lambda v: not isinstance(v, bool) and v in (0, -11, -14, -16, -18),   # パックの音量(LUFS。0 = % で決める)
                       "packVolume": lambda v: isinstance(v, int) and not isinstance(v, bool) and 1 <= v <= 200,   # packLoudness が 0 のときの音量(%)
                       # パックの出力(3 パック のタブ・まとめて実行の欄が同じ値を読み書きする。気が利く画面へ 段4)
                       "packFps": lambda v: v in ("24", "25", "30", "50", "60"),
                       "packSize": lambda v: v in ("1080x1920", "1920x1080"),
                       "speakerColors": lambda v: isinstance(v, bool),
                       "packBackup": lambda v: isinstance(v, bool),
                       "packRender": lambda v: isinstance(v, bool),   # 粗編集の動画つき(段4 4-2: 覚える)
                       # キー配置(校正のキー。キーの一覧 = 設定の部品 UIKit.keymap が送る。気が利く画面へ 段6)
                       "keymap": lambda v: _keymap_ok(v)}
_KM_ID_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,40}$")
_KM_COMBO_RE = re.compile(r"^(?:Shift\+)?(?:[^\x00-\x1f\x7f]|[A-Z][A-Za-z0-9]{1,20})$")   # UIKit.keys.comboOf の表記(home/prefs.py と同じ)


def _keymap_ok(v):
    return (isinstance(v, dict) and len(v) <= 60
            and all(isinstance(k, str) and _KM_ID_RE.fullmatch(k) and isinstance(c, str) and (c == "" or _KM_COMBO_RE.fullmatch(c)) for k, c in v.items()))


_settings_lock = threading.Lock()


def patch_settings(obj):
    vals = obj.get("values")
    if not isinstance(vals, dict) or not vals:
        raise ApiError("bad_request", "直す値がありません", 400)
    for k, v in vals.items():
        chk = SETTINGS_PATCH_KEYS.get(k)
        if not chk or not chk(v):
            raise ApiError("bad_request", "その設定は直せません: %s" % str(k)[:40], 400)
    with _settings_lock:
        st = load_settings()
        st.update(vals)
        atomic_write(SETTINGS, json.dumps(st, ensure_ascii=False, indent=1).encode("utf-8"))
    return {"ok": True, "values": {k: st[k] for k in vals}}


def merge_settings(obj):
    """PUT /api/settings {"patch": {キー: 値 | null}}: 最上位のキーだけを、ロックの中で今のファイルに合わせる(null = そのキーを消す)。
    api/settings/patch で直す項目(SETTINGS_PATCH_KEYS)は、丸ごとの保存と同じくここでは変えない(値の検査があるそちらの API だけで直す)。
    案の比較: 版(rev)で 409 にする案は競合を確実に見つけるが、設定の画面に「読み直す/上書き」の選択を作ることになる
    → キー単位の合わせで十分(同じキーを2つの窓で同時に変えたときだけ後勝ち。docs/plan/phase2-data-safety.md の 6)"""
    p = obj.get("patch")
    if set(obj) != {"patch"} or not isinstance(p, dict) or len(p) > 200             or any(not isinstance(k, str) or not k or len(k) > 60 for k in p):
        raise ApiError("bad_request", "設定の直し方(patch)の形が正しくありません", 400)
    with _settings_lock:
        st = load_settings()
        for k, v in p.items():
            if k in SETTINGS_PATCH_KEYS:
                continue
            if v is None:
                st.pop(k, None)
            else:
                st[k] = v
        body = json.dumps(st, ensure_ascii=False, indent=1).encode("utf-8")
        if len(body) > 400000:
            raise ApiError("too_big", "設定が大きすぎます", 413)
        atomic_write(SETTINGS, body)
    return {"ok": True}


def parse_replacements(text):
    """「誤=>正」を1行に1つ書いた文字列 → [(誤, 正)](長い誤りから先に置換する)。"""
    pairs = []
    for line in str(text or "").splitlines():
        k = line.find("=>")
        if k > 0 and line[:k].strip():
            pairs.append((line[:k].strip(), line[k + 2:].strip()))
    return sorted(pairs[:500], key=lambda p: -len(p[0]))


def _cc(ch):
    """文字の種類。K=カタカナ(ー・を含む) / H=漢字 / A=英数字。それ以外(ひらがな・記号・空白)は空。単語の切れ目の判定に使う。"""
    o = ord(ch)
    if 0x30A1 <= o <= 0x30FA or ch in "ー・ヽヾ":
        return "K"
    if 0x4E00 <= o <= 0x9FFF or ch in "々〆":
        return "H"
    if (ch.isascii() and ch.isalnum()) or 0xFF10 <= o <= 0xFF19 or 0xFF21 <= o <= 0xFF3A or 0xFF41 <= o <= 0xFF5A:
        return "A"
    return ""


def _bounded(text, k, w):
    """text の位置 k にある w が、同じ種類の文字の並び(カタカナ・漢字・英数字)の途中で切れていないか。
    例: 「トル」は「トルコ」の中では×、「トル様」の中なら○(ひらがな・記号との境目は切れ目とみなす)。"""
    c = _cc(w[0])
    if c and k > 0 and _cc(text[k - 1]) == c:
        return False
    c = _cc(w[-1])
    if c and k + len(w) < len(text) and _cc(text[k + len(w)]) == c:
        return False
    return True


def wb_split(w):
    """置換辞書の「誤」が |語| の形なら、(語, True)。単語の途中には当てない指定。それ以外は (w, False)。"""
    if len(w) >= 3 and w[0] == "|" and w[-1] == "|":
        return w[1:-1], True
    return w, False


def apply_replacements(text, pairs):
    n = 0
    for w, r in pairs:
        core, wb = wb_split(w)
        if not core or core not in text:
            continue
        if not wb:
            n += text.count(core)
            text = text.replace(core, r)
            continue
        out, i, k = [], 0, text.find(core)
        while k >= 0:
            if _bounded(text, k, core):
                out.append(text[i:k]); out.append(r); i = k + len(core); n += 1
                k = text.find(core, i)
            else:
                k = text.find(core, k + 1)
        out.append(text[i:]); text = "".join(out)
    return text, n


PUNCT_ONLY = re.compile(r"^[\s、。,.!?！？…・「」『』()（）ー〜~-]*$")


def _groups(orig, segs):
    """機械の出力(orig)と修正後(segs)を、時刻が重なるまとまりごとに対応づける(分割・結合・時刻の微調整があっても比べられる)。"""
    items = sorted([(o["start"], o["end"], 0, i) for i, o in enumerate(orig)] + [(g["start"], g["end"], 1, i) for i, g in enumerate(segs)])
    groups, cur, cur_end = [], None, -1.0
    for a, b, k, i in items:
        if cur is not None and a < cur_end - 0.05:
            cur[k].append(i)
            cur_end = max(cur_end, b)
        else:
            if cur is not None:
                groups.append(cur)
            cur = ([], [])
            cur[k].append(i)
            cur_end = b
    if cur is not None:
        groups.append(cur)
    return groups


def _prep(doc):
    orig = sorted([o for o in (doc.get("original") or []) if isinstance(o, dict) and num(o.get("start")) is not None and num(o.get("end")) is not None],
                  key=lambda o: o["start"])
    segs = sorted([g for g in (doc.get("segments") or []) if isinstance(g, dict)], key=lambda g: g["start"])
    return orig, segs


def _norm(items, idx):
    return re.sub(r"\s+", "", "".join(str(items[i].get("text", "")) for i in idx))


def learn_events(doc):
    """1件の文字起こしから、「機械の出力 → 人が直した文章」を (誤, 正, 前後1文字を足したか, 誤の直前2文字, 誤の直後2文字) で取り出す。"""
    orig, segs = _prep(doc)
    if not orig or not segs:
        return []
    out = []
    for go, ge in _groups(orig, segs):
        if not go or not ge:
            continue   # 片方にしかない(行の追加・削除)は、置換ではないので対象外
        a, b = _norm(orig, go), _norm(segs, ge)
        if a == b or len(a) > 600 or len(b) > 600:
            continue
        for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, a, b, autojunk=False).get_opcodes():
            if tag != "replace":
                continue
            w, r = a[i1:i2], b[j1:j2]
            if PUNCT_ONLY.match(w) or PUNCT_ONLY.match(r) or len(w) > 12 or len(r) > 12:
                continue   # 句読点だけの違い・言い回しごと書き換えた箇所は、辞書向きでない
            # 語の途中だけ(「ーイ→ワ」など)にならないよう、同じ種類の文字(カタカナ・漢字・英数字)が続く分は語の全体まで広げる
            while i1 > 0 and j1 > 0 and a[i1 - 1] == b[j1 - 1] and _cc(a[i1 - 1]) and _cc(a[i1 - 1]) == _cc(a[i1]) == _cc(b[j1]):
                i1 -= 1; j1 -= 1
            while i2 < len(a) and j2 < len(b) and a[i2] == b[j2] and _cc(a[i2]) and _cc(a[i2]) == _cc(a[i2 - 1]) == _cc(b[j2 - 1]):
                i2 += 1; j2 += 1
            w, r = a[i1:i2], b[j1:j2]
            if len(w) > 12 or len(r) > 12:
                continue
            ctx = False
            si, ei = i1, i2
            if len(w) < 2 and len(r) < 2:   # 1文字だけの違いは、前後1文字を足して誤爆を減らす
                ctx = True
                lc = a[i1 - 1] if i1 > 0 and j1 > 0 and a[i1 - 1] == b[j1 - 1] else ""
                rc = a[i2] if i2 < len(a) and j2 < len(b) and a[i2] == b[j2] else ""
                w, r = lc + w + rc, lc + r + rc
                si, ei = i1 - len(lc), i2 + len(rc)
            if len(w) >= 2 and w != r:
                out.append((w, r, ctx, a[max(0, si - 2):si], a[ei:ei + 2]))
    return out


def learn_pairs(doc):
    return [(w, r, c) for w, r, c, _l, _r in learn_events(doc)]


def learn_groups(doc, scope="changed"):
    """人が直した行(まとまり)を [{start,end,original,text}] で返す(修正データの書き出し用)。
    scope="proofed" のときは、直した行に限らず、校正済みの行すべてを返す(直していない行は changed=False。original が無い文字起こしは original="")。"""
    orig, segs = _prep(doc)
    out = []
    if scope == "proofed":
        if not segs:
            return out
        if not orig:
            for g in segs:
                b = re.sub(r"\s+", "", str(g.get("text", "")))
                if g.get("proofed") and b and "unclear" not in (g.get("tags") or []):
                    out.append({"start": g["start"], "end": g["end"], "original": "", "text": b, "changed": True, "proofed": True})
            return out
        for go, ge in _groups(orig, segs):
            if not go or not ge or not all(segs[i].get("proofed") and "unclear" not in (segs[i].get("tags") or []) for i in ge):
                continue
            a, b = _norm(orig, go), _norm(segs, ge)
            if not b:
                continue
            out.append({"start": min(segs[i]["start"] for i in ge), "end": max(segs[i]["end"] for i in ge), "original": a, "text": b, "changed": a != b, "proofed": True})
        return out
    if not orig or not segs:
        return out
    for go, ge in _groups(orig, segs):
        if not go or not ge:
            continue
        a, b = _norm(orig, go), _norm(segs, ge)
        if a == b or not b:
            continue
        st, en = min(segs[i]["start"] for i in ge), max(segs[i]["end"] for i in ge)
        out.append({"start": st, "end": en, "original": a, "text": b})
    return out


_info_cache = {}


def _doc_info(tid):
    """文字起こし1件の学習用の情報(修正の一覧・各行の文章・修正した行数)。更新日時でキャッシュする。"""
    mt = os.stat(tx_path(tid)).st_mtime_ns
    hit = _info_cache.get(tid)
    if hit and hit[0] == mt:
        return hit[1]
    with open(tx_path(tid), "r", encoding="utf-8") as f:
        d = json.load(f)
    if d.get("evalSet") is True:
        info = None   # 評価用は、辞書・提案・用語の自動追加・修正データの書き出しの元にしない(答えを見てから測ることになるため)
    elif d.get("original"):
        ev = learn_events(d)
        info = {"events": ev, "lines": len(learn_groups(d)),
                "texts": [re.sub(r"\s+", "", str(g.get("text", ""))) for g in (d.get("segments") or []) if isinstance(g, dict)]}
    else:
        info = None   # v0.5 より前の文字起こしは、機械の出力が残っていないので学習できない
    _info_cache[tid] = (mt, info)
    return info


def _all_infos():
    out = []
    if os.path.isdir(TX_DIR):
        for name in sorted(os.listdir(TX_DIR)):
            tid = name[:-5]
            if not name.endswith(".json") or not TID_RE.match(tid):
                continue
            try:
                info = _doc_info(tid)
            except (OSError, ValueError):
                continue
            if info is not None:
                out.append((tid, info))
    return out


def learned_candidates(min_count=1):
    settings = load_settings()
    have = {(wb_split(w)[0], r) for w, r in parse_replacements(settings.get("replacements"))}
    ignore = {str(x) for x in (settings.get("learnIgnore") or [])[:1000]}
    counts, docs, ctxs, used, lines = {}, {}, {}, 0, 0
    for tid, info in _all_infos():
        used += 1
        lines += info["lines"]
        for w, r, ctx, _l, _r in info["events"]:
            pr = (w, r)
            counts[pr] = counts.get(pr, 0) + 1
            docs.setdefault(pr, set()).add(tid)
            ctxs[pr] = ctx
    items = [{"wrong": w, "right": r, "count": c, "docs": len(docs[(w, r)]), "ctx": ctxs[(w, r)]} for (w, r), c in counts.items()
             if c >= min_count and (w, r) not in have and "%s=>%s" % (w, r) not in ignore]
    items.sort(key=lambda x: (-x["count"], -len(x["wrong"]), x["wrong"]))
    return {"items": items[:100], "docs": used, "lines": lines}


# ---------- 文脈つきの統計 → 修正の提案 / 自動置換 / 用語集 ----------
# 「直された回数」と「同じ語をそのまま残した回数」を数え、確度で3段階に分ける。
#   高: 3回以上・2件以上の文字起こしで直され、そのまま残した例が1つもない → 自動置換の対象(設定でオン時のみ)
#   中: 直した例が多く、そのまま残した例(と却下)より優勢 → 行に「候補」として出すだけ
#   低: 何も出さない
HIGH_POS, HIGH_DOCS, MID_RATIO, REJECT_WEIGHT = 3, 2, 0.6, 2
MAX_RULES = 300
_rules_cache = {"key": None, "val": None}
_fb_lock = threading.Lock()


def load_feedback():
    try:
        with open(FEEDBACK, "r", encoding="utf-8-sig") as f:
            d = json.load(f)
        if isinstance(d, dict):
            return {"stat": d.get("stat") if isinstance(d.get("stat"), dict) else {}, "dismissed": d.get("dismissed") if isinstance(d.get("dismissed"), dict) else {}}
    except (OSError, ValueError):
        pass
    return {"stat": {}, "dismissed": {}}


def record_feedback(obj):
    tid = str(obj.get("tid") or "")
    action = obj.get("action")
    if action not in ("accept", "reject") or not TID_RE.match(tid):
        raise ApiError("bad_request", "記録の内容が正しくありません", 400)
    items = []
    for x in (obj.get("items") or [])[:500]:
        if isinstance(x, dict) and all(isinstance(x.get(k), str) and 0 < len(x[k]) <= 60 for k in ("wrong", "right")):
            items.append((re.sub(r"[^\w-]", "", str(x.get("seg", "")))[:16], x["wrong"], x["right"]))
    with _fb_lock:
        fb = load_feedback()
        for seg, w, r in items:
            st = fb["stat"].setdefault("%s=>%s" % (w, r), {"acc": 0, "rej": 0})
            st["acc" if action == "accept" else "rej"] += 1
            if action == "reject" and seg:
                lst = fb["dismissed"].setdefault(tid, [])
                key = "%s|%s=>%s" % (seg, w, r)
                if key not in lst:
                    lst.append(key)
                del lst[:-2000]
        if len(fb["stat"]) > 5000:
            fb["stat"] = dict(list(fb["stat"].items())[-5000:])
        atomic_write(FEEDBACK, json.dumps(fb, ensure_ascii=False).encode("utf-8"))
    return len(items)


def _spans(text, w, r):
    """text の中で w がある位置(r の一部になっている箇所は除く)。"""
    rs = []
    if r:
        k = text.find(r)
        while k >= 0:
            rs.append((k, k + len(r)))
            k = text.find(r, k + 1)
    out, k = [], text.find(w)
    while k >= 0:
        if not any(a <= k and k + len(w) <= b for a, b in rs) and _bounded(text, k, w):   # 単語の途中には当てない(トル→ポル が「トルコ」に当たらない)
            out.append(k)
        k = text.find(w, k + 1)
    return out


def learn_rules():
    """全文字起こしの修正から、{(誤,正): {pos, docs, pctx, neg(そのまま残した例の前後), ctx}} を作る。"""
    settings = load_settings()
    have = {(wb_split(w)[0], r) for w, r in parse_replacements(settings.get("replacements"))}
    ignore = {str(x) for x in (settings.get("learnIgnore") or [])[:1000]}
    infos = _all_infos()
    key = (tuple((t, _info_cache[t][0]) for t, _ in infos), tuple(sorted(have)), tuple(sorted(ignore)))
    if _rules_cache["key"] == key:
        return _rules_cache["val"]
    rules = {}
    for tid, info in infos:
        for w, r, ctx, l, rr in info["events"]:
            if (w, r) in have or "%s=>%s" % (w, r) in ignore:
                continue
            x = rules.setdefault((w, r), {"pos": 0, "docs": set(), "pctx": [], "neg": [], "ctx": False})
            x["pos"] += 1
            x["docs"].add(tid)
            x["pctx"].append((l, rr))
            x["ctx"] = x["ctx"] or ctx
    top = sorted(rules.items(), key=lambda kv: -kv[1]["pos"])[:MAX_RULES]
    rules = dict(top)
    for tid, info in infos:
        if not info["events"]:
            continue   # 1か所も直していない文字起こしは、見直していない可能性があるので「そのまま残した例」に数えない
        for text in info["texts"]:
            for (w, r), x in rules.items():
                if w in text:
                    for k in _spans(text, w, r):
                        x["neg"].append((text[max(0, k - 2):k], text[k + len(w):k + len(w) + 2]))
    _rules_cache["key"], _rules_cache["val"] = key, rules
    return rules


def _match(cl, cr, L, R):
    return bool((cl[-1:] and cl[-1:] == L[-1:]) or (cr[:1] and cr[:1] == R[:1]))


def _tier(x, L, R, st):
    """確度('high' / 'mid' / None)と、判断に使った (直した例, そのまま残した例)。"""
    acc, rej = st.get("acc", 0), st.get("rej", 0)
    pm, nm = x["pos"], 0
    if x["neg"]:
        pm = sum(1 for cl, cr in x["pctx"] if _match(cl, cr, L, R))
        nm = sum(1 for cl, cr in x["neg"] if _match(cl, cr, L, R))
        if pm + nm == 0:   # 前後の文字では判断できないときは、全体の比率で見る
            pm, nm = x["pos"], len(x["neg"])
    p, n = pm + acc, nm + REJECT_WEIGHT * rej
    if not x["neg"] and rej == 0 and x["pos"] >= HIGH_POS and len(x["docs"]) >= HIGH_DOCS:
        return "high", x["pos"], 0
    if p >= 1 and p / (p + n) >= MID_RATIO:
        return "mid", pm, nm
    return None, pm, nm


def find_suggestions(text, rules, fb, skip=(), only_high=False):
    """1行の文章への提案 [{i, wrong, right, tier, pos, neg}]。長い誤りを優先し、重なる提案は出さない。"""
    cands = []
    for (w, r), x in rules.items():
        if w not in text:
            continue
        st = fb["stat"].get("%s=>%s" % (w, r), {})
        for k in _spans(text, w, r):
            t, pm, nm = _tier(x, text[max(0, k - 2):k], text[k + len(w):k + len(w) + 2], st)
            if t and (t == "high" or not only_high):
                cands.append((k, w, r, t, pm, nm))
    cands.sort(key=lambda c: (-len(c[1]), c[0]))
    used, out = [], []
    for k, w, r, t, pm, nm in cands:
        if any(k < b and a < k + len(w) for a, b in used) or ("%s=>%s" % (w, r)) in skip:
            continue
        used.append((k, k + len(w)))
        out.append({"i": k, "wrong": w, "right": r, "tier": t, "pos": pm, "neg": nm})
    out.sort(key=lambda c: c["i"])
    return out


def suggest_for_doc(tid):
    doc = read_transcript(tid)
    rules, fb = learn_rules(), load_feedback()
    dismissed = set(fb["dismissed"].get(tid, []))
    items = []
    for g in doc.get("segments") or []:
        if not isinstance(g, dict):
            continue
        text = str(g.get("text", ""))
        skip = {d.split("|", 1)[1] for d in dismissed if d.split("|", 1)[0] == g.get("id") and "|" in d}
        for sug in find_suggestions(text, rules, fb, skip):
            sug["seg"] = g.get("id")
            items.append(sug)
            if len(items) >= 1000:
                return {"items": items, "rules": len(rules)}
    return {"items": items, "rules": len(rules)}


def auto_learned_replace(text, rules, fb):
    """確度が「高」の学習済み置換だけを適用する。(新しい文章, 置換した数)"""
    sugs = find_suggestions(text, rules, fb, only_high=True)
    for sg in reversed(sugs):
        text = text[:sg["i"]] + sg["right"] + text[sg["i"] + len(sg["wrong"]):]
    return text, len(sugs)


def load_roster():
    """同梱の名簿。読めない・形が違うときは空(画面では「名簿を読めません」と出す)。中身は文字列だけに整える。"""
    try:
        with open(ROSTER, "rb") as f:
            d = json.loads(f.read().decode("utf-8-sig"))   # README で「直せます」と案内しているので、BOM 付きでも読む
        groups = []
        for g in d.get("groups") or []:
            names = [str(n).strip() for n in g.get("names") or [] if str(n).strip()]
            if names and g.get("id") and g.get("label"):
                groups.append({"id": str(g["id"])[:40], "label": str(g["label"])[:80], "names": names[:100]})
        return {"asOf": str(d.get("asOf") or "")[:20], "note": str(d.get("note") or "")[:400], "groups": groups}
    except (OSError, ValueError):
        return {"asOf": "", "note": "", "groups": []}


def auto_glossary(user_terms, limit=150):
    """よく直される正しい語を、認識のヒントとして自動で足す(ヒント全体が limit 文字に収まる範囲)。"""
    have = list(user_terms)
    out = []
    ranked = sorted(((x["pos"], r) for (w, r), x in learn_rules().items() if not x["ctx"] and x["pos"] >= 2 and 2 <= len(r) <= 15), key=lambda t: (-t[0], t[1]))
    for _pos, r in ranked:
        if r in have or r in out:
            continue
        if len("、".join(have + out + [r])) > limit:
            continue
        out.append(r)
        if len(out) >= 20:
            break
    return out


# ---------- 認識精度の測定(文字誤り率 CER) ----------
# 正解 = 人が「校正済み」にした行の文章 / 機械の出力 = original。句読点・空白・記号・全角半角・大文字小文字の違いは数えない。
# CER = (置換 + 脱落 + 挿入) ÷ 正解の文字数。置換=別の字に間違えた、脱落=正解にある字が機械に無い、挿入=機械が余計な字を出した(幻覚など)。
MAX_LEV_CELLS = 250000   # 1まとまりの文字数が多すぎるときは、厳密な編集距離をやめて近似にする


def norm_cer(text):
    t = unicodedata.normalize("NFKC", str(text or "")).lower()
    return "".join(ch for ch in t if unicodedata.category(ch)[0] in "LNM")


def lev_counts(ref, hyp):
    """(置換, 脱落, 挿入)。ref=正解、hyp=機械の出力。編集距離が最小になる組み合わせで数える。"""
    n, m = len(ref), len(hyp)
    if n == 0:
        return (0, 0, m)
    if m == 0:
        return (0, n, 0)
    if n * m > MAX_LEV_CELLS:   # 近似(difflib)。極端に長い1まとまりだけ
        s = d = i = 0
        for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, ref, hyp, autojunk=False).get_opcodes():
            if tag == "replace":
                a, b = i2 - i1, j2 - j1
                s += min(a, b)
                d += max(0, a - b)
                i += max(0, b - a)
            elif tag == "delete":
                d += i2 - i1
            elif tag == "insert":
                i += j2 - j1
        return (s, d, i)
    prev = [(j, 0, 0, j) for j in range(m + 1)]
    for a in range(1, n + 1):
        cur = [(a, 0, a, 0)]
        ra = ref[a - 1]
        for b in range(1, m + 1):
            if ra == hyp[b - 1]:
                best = prev[b - 1]
            else:
                p = prev[b - 1]
                best = (p[0] + 1, p[1] + 1, p[2], p[3])
                q = prev[b]
                if q[0] + 1 < best[0]:
                    best = (q[0] + 1, q[1], q[2] + 1, q[3])
                r = cur[b - 1]
                if r[0] + 1 < best[0]:
                    best = (r[0] + 1, r[1], r[2], r[3] + 1)
            cur.append(best)
        prev = cur
    return prev[m][1:]


def metric_terms(settings=None):
    """「用語が正しく出たか」を数えるための用語(用語集 + 置換辞書の「正」)。正規化済み・2文字以上。"""
    st = settings if settings is not None else load_settings()
    raw = [t.strip() for t in re.split(r"[\r\n,、]+", str(st.get("glossary") or "")) if t.strip()]
    raw += [r for _w, r in parse_replacements(st.get("replacements")) if r]
    out = []
    for t in raw:
        n = norm_cer(t)
        if len(n) >= 2 and n not in out:
            out.append(n)
    return out[:300]


def new_acc():
    return {"groups": 0, "changed": 0, "refChars": 0, "sub": 0, "del": 0, "ins": 0, "termRef": 0, "termHit": 0, "termExtra": 0,
            "machineOnly": 0, "machineOnlyChars": 0, "worst": []}


def acc_line(acc, ref, hyp, terms=(), info=None, machine_only=False):
    """1まとまり(正解 ref と機械の出力 hyp。どちらも norm_cer 済み)を集計に足す。"""
    s, d, i = lev_counts(ref, hyp)
    acc["groups"] += 1
    acc["refChars"] += len(ref)
    acc["sub"] += s
    acc["del"] += d
    acc["ins"] += i
    if s + d + i:
        acc["changed"] += 1
        if info is not None:
            acc["worst"].append({**info, "errs": s + d + i})
            acc["worst"].sort(key=lambda x: -x["errs"])
            del acc["worst"][10:]
    if machine_only:
        acc["machineOnly"] += 1
        acc["machineOnlyChars"] += len(hyp)
    for t in terms:
        rc, hc = ref.count(t), hyp.count(t)
        acc["termRef"] += rc
        acc["termHit"] += min(rc, hc)
        acc["termExtra"] += max(0, hc - rc)   # 正解に無いのに機械が出した用語(用語集が誘発した誤挿入の疑い)


def acc_merge(a, b):
    for k in ("groups", "changed", "refChars", "sub", "del", "ins", "termRef", "termHit", "termExtra", "machineOnly", "machineOnlyChars"):
        a[k] += b[k]
    a["worst"] = sorted(a["worst"] + b["worst"], key=lambda x: -x["errs"])[:10]


def acc_finish(acc):
    out = dict(acc)
    errs = acc["sub"] + acc["del"] + acc["ins"]
    out["errs"] = errs
    out["cer"] = round(errs / acc["refChars"], 4) if acc["refChars"] else None
    out["termRate"] = round(acc["termHit"] / acc["termRef"], 4) if acc["termRef"] else None
    return out


def doc_metrics(doc, legacy=False, terms=()):
    """1件の文字起こしの集計。校正済みの行が無ければ None(legacy=True なら、校正済みの印が無くても、修正のある文書は全行を校正済みとみなして仮計算)。
    数える対象: ①機械と人の両方にある まとまり(全行が校正済み) ②機械だけにある まとまり(人が行を消した=挿入の誤り。校正した範囲の中だけ)
    ③人だけにある まとまり(人が足した行=脱落の誤り。全行が校正済み)"""
    orig, segs = _prep(doc)
    if not orig or not segs:
        return None
    proofed = [g for g in segs if g.get("proofed")]
    basis = "proofed"
    if proofed:
        lo, hi = min(g["start"] for g in proofed), max(g["end"] for g in proofed)
        is_ok = lambda g: bool(g.get("proofed")) and "unclear" not in (g.get("tags") or [])
    elif legacy:
        if "".join(norm_cer(o.get("text", "")) for o in orig) == "".join(norm_cer(g.get("text", "")) for g in segs):
            return None   # 修正が無い文書は、見直したのか分からないので数えない
        basis = "legacy"
        lo, hi = min(g["start"] for g in segs), max(g["end"] for g in segs)
        is_ok = lambda g: "unclear" not in (g.get("tags") or [])
    else:
        return None
    acc = new_acc()
    for go, ge in _groups(orig, segs):
        if go and ge:
            if not all(is_ok(segs[i]) for i in ge):
                continue
            ref, hyp = norm_cer(_norm(segs, ge)), norm_cer(_norm(orig, go))
            a, b, mo = min(segs[i]["start"] for i in ge), max(segs[i]["end"] for i in ge), False
            raw_ref, raw_hyp = _norm(segs, ge), _norm(orig, go)
        elif go:
            a, b = min(orig[i]["start"] for i in go), max(orig[i]["end"] for i in go)
            if a < lo - 0.05 or b > hi + 0.05:
                continue
            raw_ref, raw_hyp = "", _norm(orig, go)
            ref, hyp, mo = "", norm_cer(raw_hyp), True
        else:
            if not all(is_ok(segs[i]) for i in ge):
                continue
            a, b = min(segs[i]["start"] for i in ge), max(segs[i]["end"] for i in ge)
            raw_ref, raw_hyp = _norm(segs, ge), ""
            ref, hyp, mo = norm_cer(raw_ref), "", False
        if not ref and not hyp:
            continue
        acc_line(acc, ref, hyp, terms, {"start": round(a, 2), "end": round(b, 2), "ref": raw_ref[:120], "hyp": raw_hyp[:120]}, mo)
    if not acc["groups"]:
        return None
    acc["basis"] = basis
    return acc


def config_key(d):
    """認識の設定ごとに成績を分けて比べるための名前(モデル・用語集の有無・速度優先・再認識を含むか)。"""
    p = d.get("params") or {}
    parts = [str(d.get("model") or "?").split("/")[-1], "用語集あり" if p.get("glossary") else "用語集なし"]
    if p.get("beam") == 1:
        parts.append("速度優先")
    if d.get("retranscribed"):
        parts.append("再認識を含む")
    return " / ".join(parts)


def all_metrics(tid=None, legacy=False, scope="all"):
    terms = metric_terms()
    tids = [tid] if tid else sorted(n[:-5] for n in (os.listdir(TX_DIR) if os.path.isdir(TX_DIR) else []) if n.endswith(".json") and TID_RE.match(n[:-5]))
    total, by_cfg, rows = new_acc(), {}, []
    proofed_lines = docs_proofed = docs = 0
    for t in tids:
        try:
            d = read_transcript(t)
        except ApiError:
            continue
        if not tid and ((scope == "eval") != (d.get("evalSet") is True)) and scope != "all":
            continue
        docs += 1
        n = sum(1 for g in d.get("segments") or [] if isinstance(g, dict) and g.get("proofed"))
        proofed_lines += n
        docs_proofed += 1 if n else 0
        m = doc_metrics(d, legacy, terms)
        if not m:
            continue
        cfg = config_key(d)
        for w in m["worst"]:
            w["doc"] = str(d.get("title") or "")[:40]
        acc_merge(by_cfg.setdefault(cfg, new_acc()), m)
        acc_merge(total, m)
        row = acc_finish(m)
        row.update({"id": t, "title": str(d.get("title") or "")[:60], "config": cfg})
        row.pop("worst", None)
        rows.append(row)
    return {"scope": scope if not tid else "doc", "legacy": bool(legacy), "docs": docs, "docsProofed": docs_proofed, "proofedLines": proofed_lines, "overall": acc_finish(total),
            "byConfig": sorted(({"config": k, **acc_finish(v)} for k, v in by_cfg.items()), key=lambda x: x["config"]), "byDoc": rows, "termCount": len(terms)}


# ---------- 評価用の基準の記録 ----------
EVAL_BASE = os.path.join(DATA_DIR, "eval-baselines.json")
_base_lock = threading.Lock()


def read_baselines():
    try:
        with open(EVAL_BASE, "r", encoding="utf-8-sig") as f:
            d = json.load(f)
        return d if isinstance(d, list) else []
    except (OSError, ValueError):
        return []


def record_baseline(label):
    """評価用の文書の、いまの成績を記録する(施策の前後で比べるため)。評価用が無い・校正済みが無いときは断る。"""
    m = all_metrics(None, False, "eval")
    o = m["overall"]
    if not m["docs"]:
        raise ApiError("no_eval", "評価用の文字起こしがありません(画面の「評価用にする」で印を付けてください)", 400)
    if not o.get("groups"):
        raise ApiError("no_proofed", "評価用に校正済みの行がまだありません", 400)
    rec = {"at": int(time.time() * 1000), "label": str(label or "")[:80], "docs": m["docs"], "cer": o["cer"], "refChars": o["refChars"], "sub": o["sub"], "del": o["del"], "ins": o["ins"],
           "configs": [{"config": c["config"], "cer": c["cer"], "refChars": c["refChars"]} for c in m["byConfig"]][:6],
           "dict": len(parse_replacements(load_settings().get("replacements"))), "glossaryChars": len(str(load_settings().get("glossary") or ""))}
    with _base_lock:
        items = read_baselines()
        items.append(rec)
        atomic_write(EVAL_BASE, json.dumps(items[-100:], ensure_ascii=False, indent=1).encode("utf-8"))
    return rec


# ---------- 修正データの書き出し(音声の範囲 + 直した文章) ----------
MAX_EXPORT_CLIPS = 400
MAX_CLIP_SEC = 20
_export_lock = threading.Lock()
EXPORT_README = """修正データ(文字起こしツールが書き出したもの)
corrections.jsonl … 1行に1件。 doc=文字起こしのID / source=元ファイル名 / start,end=元の動画の中の秒 /
  original=機械の出力(空白なし) / text=人が直した文章(空白なし) / audio=音声ファイル(audio/ の中。無い場合は null)
audio/*.wav       … その範囲の音声(16kHz・モノラル)。音声を含めない設定のときは無い。
校正済みの行すべてを書き出した場合(scope=proofed)は、直していない行も入ります(changed=false。original と text が同じ)。
  original が空の行は、機械の出力が残っていない古い文字起こしの行です(text は人が確認した文章)。
用途: 認識精度の測定(original と text の差)や、将来の追加学習用データとして。
注意: 話者の声・会話の内容が含まれます。他人に渡すときは、相手の同意を得てください。
"""


def export_corrections(tid=None, audio=True, scope="changed"):
    """修正した行(scope="proofed" なら校正済みの行すべて)を zip にまとめ、(パス, 件数, 音声つきの件数, とばした件数) を返す。呼び出し側が消す。"""
    if not _export_lock.acquire(blocking=False):
        raise ApiError("busy", "別の書き出しの最中です", 409)
    try:
        ff = find_ffmpeg() if audio else None
        if scope == "proofed":
            docs = [tid] if tid else sorted(n[:-5] for n in (os.listdir(TX_DIR) if os.path.isdir(TX_DIR) else []) if n.endswith(".json") and TID_RE.match(n[:-5]))
        else:
            docs = [tid] if tid else [t for t, _ in _all_infos()]
        os.makedirs(TMP_DIR, exist_ok=True)
        path = os.path.join(TMP_DIR, "export-%s.zip" % uuid.uuid4().hex[:8])
        try:
            return _export_corrections_zip(path, docs, tid, ff, scope)
        except BaseException:   # 途中で失敗したら(評価用の指定・ディスク不足など)、作りかけの zip を残さない
            try:
                os.unlink(path)
            except OSError:
                pass
            raise
    finally:
        _export_lock.release()


def _export_corrections_zip(path, docs, tid, ff, scope):
    n = na = skipped = 0
    import zipfile
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        lines = []
        for t in docs:
            if n >= MAX_EXPORT_CLIPS:
                break
            try:
                d = read_transcript(t)
            except ApiError:
                continue
            if d.get("evalSet") is True:
                if tid:
                    raise ApiError("eval_set", "評価用の文字起こしは、学習用のデータとして書き出しません(評価用を外すと書き出せますが、その時点から評価には使えなくなります)", 400)
                continue
            groups = learn_groups(d, "proofed") if scope == "proofed" else (learn_groups(d) if d.get("original") else [])
            if not groups:
                continue
            try:
                src = check_source(d.get("sourcePath")) if ff else None
            except ApiError:
                src = None
            for g in groups:
                if n >= MAX_EXPORT_CLIPS:
                    skipped += 1
                    continue
                if g["end"] - g["start"] < 0.3:
                    continue
                n += 1
                name = None
                if ff and src:
                    name = "audio/%s_%07d.wav" % (t, int(g["start"] * 100))
                    tmp = os.path.join(TMP_DIR, "clip-%s.wav" % uuid.uuid4().hex[:8])
                    try:
                        r = subprocess.run([ff, "-hide_banner", "-nostdin", "-y", "-protocol_whitelist", "file", "-ss", "%.3f" % max(0, g["start"] - 0.2), "-i", src,
                                            "-t", "%.3f" % min(MAX_CLIP_SEC, g["end"] - g["start"] + 0.4), "-vn", "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", tmp],
                                           stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=60)
                        if r.returncode == 0 and os.path.isfile(tmp) and os.path.getsize(tmp) > 1000:
                            z.write(tmp, name)
                            na += 1
                        else:
                            name = None
                    except (OSError, subprocess.SubprocessError):
                        name = None
                    finally:
                        try:
                            os.unlink(tmp)
                        except OSError:
                            pass
                lines.append(json.dumps({"doc": t, "source": d.get("sourceName", ""), "start": g["start"], "end": g["end"],
                                         "original": g["original"], "text": g["text"], "audio": name,
                                         **({"changed": g["changed"], "proofed": True} if scope == "proofed" else {})}, ensure_ascii=False))
        z.writestr("corrections.jsonl", "\n".join(lines) + ("\n" if lines else ""))
        z.writestr("README.txt", EXPORT_README)
    return path, n, na, skipped


# ---------- データの保管(将来の学習・声紋登録・再解析に使えるように、校正の成果と音声を残す) ----------
# dataset/docs/<id>/{doc.json, lines.jsonl, manifest.json, full.flac, audio/*.flac} と dataset/index.jsonl。
# 元の動画を移動・削除しても、あとから使えるように、音声も一緒に残す(16kHz・モノラルの FLAC)。
ARCH_MAX_CLIP = 30           # 1行の音声の上限(秒)。Whisper の学習の単位が30秒
ARCH_PAD = 0.2               # 行の前後に足す余裕(秒)
ARCH_MIN_FREE = 1 << 30      # 空きがこれ未満なら保管しない(1GB)
_arch_lock = threading.Lock()
_arch = {"running": False, "tid": "", "done": 0, "total": 0, "errors": [], "finishedAt": 0}
ARCH_README = """保管データ(文字起こしツールが自動で残したもの)  形式の版: 1
index.jsonl          … 全文字起こしの行の一覧(1行に1件)。校正した行・人が消した行(負例)・「聞き取れない」の行が入ります
docs/<ID>/doc.json   … その文字起こしの全体(修正後の行・機械の出力 original・話者・認識の設定)
docs/<ID>/lines.jsonl … その文字起こしの行の一覧(index.jsonl と同じ形式。未校正の行も入ります)
docs/<ID>/audio/*.flac … 行ごとの音声(16kHz・モノラル。前後0.2秒を含む)。校正済みの行と、人が消した行だけ
docs/<ID>/full.flac  … その範囲の全体の音声(設定でオンのとき)。あとから別のモデルで認識し直せます
docs/<ID>/manifest.json … 元ファイル名・サイズ・件数・話者ごとの時間など
settings-snapshot.json … 保管した時点の用語集・置換辞書
各行の項目:
  kind      line=機械の出力と対応する行 / deleted=機械が出したが人が消した行(負例) / added=人が足した行
  role      positive=正解として使える(校正済み・聞き取れないの印なし) / negative=消した行(校正した範囲の中。正解は空)
            / unclear=校正済みだが「聞き取れない」の印つき / unproofed=未校正(学習には使わない)
  text      人が確認した文章 / original=機械の出力(古い文字起こしは null) / start,end=元の動画の中の秒
  speaker,speakerName=話者(声が混ざる行は mixed) / tags=unclear(聞き取れない)・overlap(声が重なる)・bgm(BGMやゲーム音が大きい)
  split     train=学習に使える / eval=評価用(追加学習には使わない。精度を測るためだけに取ってある)
  changed=機械の出力から直したか / flag=自動の「要確認」の理由 / audio=このフォルダからの音声のパス(無ければ null)
  orig_start,orig_end=機械の出力の時刻(人が時刻を直した場合、start,end とずれます)
使い道の例: 追加学習(LoRA)の学習データ、話者の声紋登録、認識精度の測定、別モデルでの再認識。
注意: 話者の声・会話の内容が含まれます。他人に渡す・クラウドへ上げるときは、相手の同意と規約を確認してください。
"""


def _join_text(items):
    out = ""
    for it in items:
        t = str(it.get("text", "")).strip()
        if out and t and re.search(r"[A-Za-z0-9]$", out) and re.match(r"[A-Za-z0-9]", t):
            out += " "
        out += t
    return out


def archive_entries(doc):
    """文字起こし1件を、あとで使い回せる行の一覧にする(機械の出力と修正後を、時刻の重なりで対応づける)。"""
    orig, segs = _prep(doc)
    proofed = [g for g in segs if g.get("proofed")]
    lo = min((g["start"] for g in proofed), default=None)
    hi = max((g["end"] for g in proofed), default=None)
    have_orig = bool(orig)
    groups = _groups(orig, segs) if have_orig else [([], [i]) for i in range(len(segs))]
    names = {s.get("id"): str(s.get("name") or s.get("id")) for s in doc.get("speakers") or [] if isinstance(s, dict)}
    out, used = [], set()
    for go, ge in groups:
        e = {"doc": doc.get("id", ""), "source": doc.get("sourceName", ""), "model": doc.get("model", ""), "language": doc.get("language", "")}
        if ge:
            gs = [segs[i] for i in ge]
            e["kind"] = "line" if go or not have_orig else "added"
            a, b = min(g["start"] for g in gs), max(g["end"] for g in gs)
            e.update({"start": round(a, 2), "end": round(b, 2), "text": _join_text(gs)})
            spk = sorted({g.get("speaker") for g in gs if g.get("speaker")})
            e["speaker"] = spk[0] if len(spk) == 1 else ("mixed" if spk else "")
            e["speakerName"] = names.get(spk[0], "") if len(spk) == 1 else ("" if not spk else "mixed")
            e["tags"] = [t for t in TAGS if any(t in (g.get("tags") or []) for g in gs)]
            e["flag"] = "、".join(dict.fromkeys(g["flag"] for g in gs if g.get("flag")))[:200]
            e["proofed"] = all(g.get("proofed") for g in gs)
            if go:
                e["original"] = _join_text([orig[i] for i in go])
                e["orig_start"], e["orig_end"] = round(min(orig[i]["start"] for i in go), 2), round(max(orig[i]["end"] for i in go), 2)
                e["changed"] = norm_cer(e["text"]) != norm_cer(e["original"])
            else:
                e["original"] = "" if have_orig else None
                e["changed"] = True if have_orig else None
            if not e["proofed"] or not e["text"].strip():
                e["role"] = "unproofed"
            else:
                e["role"] = "unclear" if "unclear" in e["tags"] else "positive"
        else:
            a, b = min(orig[i]["start"] for i in go), max(orig[i]["end"] for i in go)
            inside = lo is not None and a >= lo - 0.05 and b <= hi + 0.05
            e.update({"kind": "deleted", "start": round(a, 2), "end": round(b, 2), "text": "", "original": _join_text([orig[i] for i in go]),
                      "orig_start": round(a, 2), "orig_end": round(b, 2), "speaker": "", "speakerName": "", "tags": [], "flag": "", "proofed": False,
                      "changed": True, "role": "negative" if inside else "unproofed"})
        base = "%07d%s" % (int(e["start"] * 100), e["kind"][0])
        key, n = base, 1
        while key in used:
            n += 1
            key = "%s%d" % (base, n)
        used.add(key)
        e["key"] = key
        e["audioSig"] = "%.2f-%.2f" % (e["start"], e["end"])
        out.append(e)
    return out


def _flac_cut(ff, src, dst, ss, dur):
    tmp = dst + ".part.flac"
    try:
        r = subprocess.run([ff, "-hide_banner", "-nostdin", "-y", "-protocol_whitelist", "file", "-ss", "%.3f" % max(0, ss), "-i", src, "-t", "%.3f" % dur,
                            "-vn", "-ac", "1", "-ar", "16000", "-c:a", "flac", tmp], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=300)
        if r.returncode == 0 and os.path.isfile(tmp) and os.path.getsize(tmp) > 200:
            os.replace(tmp, dst)
            return True
    except (OSError, subprocess.SubprocessError):
        pass
    finally:
        try:
            os.unlink(tmp)
        except OSError:
            pass
    return False


def _dir_bytes(d):
    n = 0
    for root, _dirs, files in os.walk(d):
        for f in files:
            try:
                n += os.path.getsize(os.path.join(root, f))
            except OSError:
                pass
    return n


def archive_doc(tid, full=True):
    """文字起こし1件を dataset/docs/<tid>/ に保管する(音声は、新しい行・時刻が変わった行だけ切り出す)。"""
    doc = read_transcript(tid)
    doc["id"] = tid
    root = os.path.join(DATASET_DIR, "docs", tid)
    adir = os.path.join(root, "audio")
    os.makedirs(adir, exist_ok=True)
    try:
        with open(os.path.join(root, "manifest.json"), "r", encoding="utf-8") as f:
            old = json.load(f)
    except (OSError, ValueError):
        old = {}
    old_sig = old.get("clips") if isinstance(old.get("clips"), dict) else {}
    entries = archive_entries(doc)
    for e in entries:
        e["split"] = "eval" if doc.get("evalSet") is True else "train"   # 追加学習に使うときは、split が eval のものを必ず除く
    want = [e for e in entries if e["role"] in ("positive", "unclear", "negative")]
    ff = find_ffmpeg()
    src, note = None, ""
    try:
        src = check_source(doc.get("sourcePath")) if ff else None
        if not ff:
            note = "ffmpeg が見つからないため、音声は保管していません"
    except ApiError:
        note = "元のファイルが見つからないため、音声を新しく保管できませんでした(すでに保管した音声は残っています)"
    start, end = num(doc.get("start"), 0.0) or 0.0, num(doc.get("end"))
    fpath = os.path.join(root, "full.flac")
    todo = [e for e in want if not (old_sig.get(e["key"]) == e["audioSig"] and os.path.isfile(os.path.join(adir, e["key"] + ".flac")))]
    wav = None
    base = fpath if os.path.isfile(fpath) else None
    if src and ((full and not base) or (todo and not base)):
        os.makedirs(TMP_DIR, exist_ok=True)
        wav = os.path.join(TMP_DIR, "arch-%s.wav" % uuid.uuid4().hex[:8])
        try:
            extract_audio({"cancel": False, "proc": None}, {"sourcePath": src, "start": start, "end": end, "boost": False}, wav)
            if full and _flac_cut(ff, wav, fpath, 0, 1e7):
                base = fpath
            elif not base:
                base = wav
        except ApiError as e:
            note = e.message
    made = 0
    if base and ff:
        for e in todo:
            dur = min(ARCH_MAX_CLIP, e["end"] - e["start"]) + ARCH_PAD * 2
            if e["end"] - e["start"] < 0.1:
                continue
            if _flac_cut(ff, base, os.path.join(adir, e["key"] + ".flac"), e["start"] - start - ARCH_PAD, dur):
                made += 1
    if wav:
        try:
            os.unlink(wav)
        except OSError:
            pass
    keep, sig, spk_sec = set(), {}, {}
    counts = {"lines": len(entries), "positive": 0, "negative": 0, "unclear": 0, "unproofed": 0, "added": 0, "positiveSec": 0.0, "negativeSec": 0.0}
    lines = []
    for e in entries:
        f = os.path.join(adir, e["key"] + ".flac")
        has = e["role"] in ("positive", "unclear", "negative") and os.path.isfile(f)
        if has:
            keep.add(e["key"] + ".flac")
            sig[e["key"]] = e["audioSig"]
        e["audio"] = "docs/%s/audio/%s.flac" % (tid, e["key"]) if has else None
        e.pop("audioSig", None)
        counts[e["role"]] += 1
        if e["kind"] == "added":
            counts["added"] += 1
        d = e["end"] - e["start"]
        if e["role"] == "positive":
            counts["positiveSec"] += d
            k = e["speakerName"] or "(話者なし)"
            spk_sec[k] = round(spk_sec.get(k, 0.0) + d, 1)
        elif e["role"] == "negative":
            counts["negativeSec"] += d
        lines.append(e)
    for n in os.listdir(adir):   # 使わなくなった行(校正を外した・時刻が変わった)の音声は消す
        if n.endswith(".flac") and n not in keep:
            try:
                os.unlink(os.path.join(adir, n))
            except OSError:
                pass
    counts["positiveSec"], counts["negativeSec"] = round(counts["positiveSec"], 1), round(counts["negativeSec"], 1)
    try:
        st = os.stat(doc.get("sourcePath") or "")
        ssize, smt = st.st_size, int(st.st_mtime)
    except OSError:
        ssize, smt = old.get("sourceSize"), old.get("sourceMtime")
    atomic_write(os.path.join(root, "lines.jsonl"), ("\n".join(json.dumps(e, ensure_ascii=False) for e in lines) + "\n").encode("utf-8"))
    atomic_write(os.path.join(root, "doc.json"), json.dumps(doc, ensure_ascii=False, indent=1).encode("utf-8"))
    man = {"version": 1, "tid": tid, "title": str(doc.get("title") or "")[:120], "archivedAt": int(time.time() * 1000), "docUpdatedAt": doc.get("updatedAt", 0),
           "sourceName": doc.get("sourceName", ""), "sourceSize": ssize, "sourceMtime": smt, "start": start, "end": end, "model": doc.get("model", ""), "language": doc.get("language", ""),
           "split": "eval" if doc.get("evalSet") is True else "train", "counts": counts, "speakerSec": spk_sec, "clips": sig, "fullAudio": os.path.isfile(fpath), "audioBytes": _dir_bytes(root), "note": note, "newClips": made}
    atomic_write(os.path.join(root, "manifest.json"), json.dumps(man, ensure_ascii=False, indent=1).encode("utf-8"))
    return man


def archive_rebuild_index():
    """docs/*/lines.jsonl から、全体の一覧 index.jsonl(校正した行・負例・聞き取れない行だけ)と、README・設定の写しを作り直す。"""
    rows = []
    dd = os.path.join(DATASET_DIR, "docs")
    for t in sorted(os.listdir(dd)) if os.path.isdir(dd) else []:
        try:
            with open(os.path.join(dd, t, "lines.jsonl"), "r", encoding="utf-8") as f:
                for ln in f:
                    if ln.strip() and json.loads(ln).get("role") != "unproofed":
                        rows.append(ln.strip())
        except (OSError, ValueError):
            continue
    atomic_write(os.path.join(DATASET_DIR, "index.jsonl"), ("\n".join(rows) + ("\n" if rows else "")).encode("utf-8"))
    atomic_write(os.path.join(DATASET_DIR, "README.txt"), ARCH_README.encode("utf-8"))
    st = load_settings()
    snap = {k: st.get(k) for k in ("glossary", "replacements", "learnIgnore", "model", "language", "vadMode") if k in st}
    snap["savedAt"] = int(time.time() * 1000)
    atomic_write(os.path.join(DATASET_DIR, "settings-snapshot.json"), json.dumps(snap, ensure_ascii=False, indent=1).encode("utf-8"))


def _arch_run(tids, full):
    try:
        for t in tids:
            _arch["tid"] = t
            try:
                archive_doc(t, full)
            except ApiError as e:
                _arch["errors"].append("%s: %s" % (t, e.message))
            except Exception as e:   # 1件の失敗で、残りを止めない
                _arch["errors"].append("%s: %s" % (t, e))
            _arch["done"] += 1
        archive_rebuild_index()
    except Exception as e:
        _arch["errors"].append(str(e))
    finally:
        with _arch_lock:
            _arch.update({"running": False, "tid": "", "finishedAt": int(time.time() * 1000)})


def start_archive(tid=None, full=True, wait=False):
    if tid is not None and not TID_RE.match(str(tid)):
        raise ApiError("bad_request", "文字起こしの指定が正しくありません", 400)
    if tid:
        read_transcript(tid)
        tids = [tid]
    else:
        tids = []
        for n in sorted(os.listdir(TX_DIR) if os.path.isdir(TX_DIR) else []):
            if n.endswith(".json") and TID_RE.match(n[:-5]):
                try:
                    if any(g.get("proofed") for g in read_transcript(n[:-5]).get("segments") or []):
                        tids.append(n[:-5])
                except ApiError:
                    pass
    if not tids:
        raise ApiError("empty", "保管できる文字起こしがありません(校正済みの行がある文字起こしが対象です)", 400)
    os.makedirs(DATASET_DIR, exist_ok=True)
    if shutil.disk_usage(DATASET_DIR).free < ARCH_MIN_FREE:
        raise ApiError("disk", "ディスクの空きが少ないため、保管できません(1GB以上の空きが必要です)", 507)
    with _arch_lock:
        if _arch["running"]:
            raise ApiError("busy", "別の保管の最中です", 409)
        _arch.update({"running": True, "tid": "", "done": 0, "total": len(tids), "errors": []})
    th = threading.Thread(target=_arch_run, args=(tids, bool(full)), daemon=True)
    th.start()
    if wait:
        th.join()
    return len(tids)


def dataset_stats():
    docs, tot = [], {"docs": 0, "positive": 0, "negative": 0, "unclear": 0, "positiveSec": 0.0, "negativeSec": 0.0, "audioBytes": 0, "stale": 0}
    spk = {}
    dd = os.path.join(DATASET_DIR, "docs")
    for t in sorted(os.listdir(dd)) if os.path.isdir(dd) else []:
        try:
            with open(os.path.join(dd, t, "manifest.json"), "r", encoding="utf-8") as f:
                m = json.load(f)
        except (OSError, ValueError):
            continue
        c = m.get("counts") or {}
        cur_eval = False
        try:
            cur = read_transcript(t)
            stale = (cur.get("updatedAt") or 0) > (m.get("docUpdatedAt") or 0)
            orphan = False
            cur_eval = cur.get("evalSet") is True
        except ApiError:
            stale, orphan = False, True
        docs.append({"tid": t, "title": m.get("title", ""), "archivedAt": m.get("archivedAt", 0), "positive": c.get("positive", 0), "negative": c.get("negative", 0),
                     "unclear": c.get("unclear", 0), "positiveSec": c.get("positiveSec", 0), "audioBytes": m.get("audioBytes", 0), "fullAudio": bool(m.get("fullAudio")),
                     "stale": stale, "orphan": orphan, "note": m.get("note", "")})
        is_eval = m.get("split") == "eval" or cur_eval
        docs[-1]["split"] = "eval" if is_eval else "train"
        tot["docs"] += 1
        tot["stale"] += 1 if stale else 0
        tot["audioBytes"] += m.get("audioBytes", 0)
        if is_eval:   # 評価用は、学習に使える量には入れない
            tot["evalSec"] = round(tot.get("evalSec", 0.0) + c.get("positiveSec", 0), 1)
            continue
        for k in ("positive", "negative", "unclear", "positiveSec", "negativeSec"):
            tot[k] += c.get(k, 0)
        for k, v in (m.get("speakerSec") or {}).items():
            spk[k] = spk.get(k, 0.0) + v
    tot["positiveSec"], tot["negativeSec"] = round(tot["positiveSec"], 1), round(tot["negativeSec"], 1)
    with _arch_lock:
        run = dict(_arch)
    return {"running": run["running"], "progress": {"done": run["done"], "total": run["total"], "tid": run["tid"]}, "errors": run["errors"][:5], "finishedAt": run["finishedAt"],
            "totals": tot, "speakers": {k: round(v, 1) for k, v in sorted(spk.items(), key=lambda x: -x[1])}, "docs": docs}


# ---------- 選んだ行の再認識 ----------
SPK_FLAGS = (MIXED_FLAG, WEAK_FLAG, NONE_FLAG)


MAX_RANGE_SEC = 900


def validate_retranscribe(req):
    tid = str(req.get("tid") or "")
    doc = read_transcript(tid)
    if doc.get("evalSet") is True:
        raise ApiError("eval_set", "評価用の文字起こしは再認識できません(機械の出力=比べる基準が書き換わるため)。評価用を外してから行ってください", 400)
    src = check_source(doc.get("sourcePath"))
    valid = {g["id"] for g in (doc.get("segments") or [])}
    ids = [i for i in dict.fromkeys(str(x)[:16] for x in (req.get("ids") or [])[:5000] if isinstance(x, (str, int))) if i in valid][:2000]
    mode = req.get("mode") if req.get("mode") in ("range", "whole") else "each"
    if not ids and mode != "whole":
        raise ApiError("empty", "再認識する行がありません", 400)
    model = str(req.get("model") or "large-v3").strip()
    if not valid_model(model):
        raise ApiError("bad_model", "モデル名が正しくありません", 400)
    lang = str(req.get("language") or doc.get("language") or "ja")
    glossary = [t.strip() for t in re.split(r"[\r\n,、]+", str(req.get("glossary") or "")) if t.strip()][:200]
    gauto = auto_glossary(glossary) if req.get("autoGloss") is not False else []
    ctx = stream_context(doc, req.get("autoContext") is True)
    with _jobs_lock:
        if any(j.get("kind") in ("diarize", "retranscribe") and j["spec"].get("tid") == tid and j["state"] in ("queued", "loading", "extracting", "running") for j in _jobs.values()):
            raise ApiError("busy", "この文字起こしは、すでに別の処理(話者判別・再認識)の最中です", 409)
    rng = None
    if mode == "whole":   # 動画全体(文書の範囲全体)を範囲と同じやり方で認識し直す。校正済みの行は残す(docs/design/whole-retranscribe-design.md の 3)
        segs = sorted((g for g in doc.get("segments") or []), key=lambda g: g["start"])
        a = num(doc.get("start"), 0.0) or 0.0
        b = num(doc.get("end")) or media_duration(src) or max([g["end"] for g in segs] or [0.0])
        if b <= a + 0.5:
            raise ApiError("bad_range", "動画の長さが分かりません", 400)
        if b - a > MAX_SPAN_SEC:
            raise ApiError("too_long", "1回に処理できるのは6時間までです", 400)
        ids = [g["id"] for g in segs if not g.get("proofed")]   # 校正済みでない行を差し替える(画面の選択は使わない)
        rng = [round(a, 3), round(b, 3)]
    elif mode == "range":   # 選んだ行の最初〜最後を、ひとまとまりの音声として認識し直す(間にある選んでいない行も含む)
        segs = sorted((g for g in doc.get("segments") or []), key=lambda g: g["start"])
        chosen = [g for g in segs if g["id"] in set(ids)]
        a, b = min(g["start"] for g in chosen), max(g["end"] for g in chosen)
        ids = [g["id"] for g in segs if a - 1e-6 <= (g["start"] + g["end"]) / 2 <= b + 1e-6]
        if b - a > MAX_RANGE_SEC:
            raise ApiError("too_long", "範囲が長すぎます(最大%d分)。範囲を狭めてください" % (MAX_RANGE_SEC // 60), 400)
        rng = [a, b]
    return {"tid": tid, "ids": ids, "mode": mode, "range": rng, "model": model, "language": lang if lang in LANGS else "ja", "beam": 5,
            # 全体は画面の設定によらず「弱め」から(抜けを拾うのが目的。捨てすぎたら「なし」へ緩める)。明示の「なし」だけは尊重する
            "vadMode": ("off" if req.get("vadMode") == "off" else "weak") if mode == "whole"
            else req.get("vadMode") if mode == "range" and req.get("vadMode") in ("weak", "normal", "off") else "off",
            "wordSplit": mode in ("range", "whole") and req.get("wordSplit") is not False, "splitChars": split_chars_for(req),
            "stripPunct": req.get("stripPunct") is not False,
            "device": req.get("device") if req.get("device") in ("cuda", "cpu") else "auto", "boost": req.get("boost") is True,
            "autoDict": req.get("autoDict") is not False, "glossary": glossary + gauto, "glossAuto": gauto, "context": ctx,
            "title": {"range": "範囲を再認識: ", "whole": "全体を再認識: "}.get(mode, "再認識: ") + (str(doc.get("title") or "") or "無題")[:100]}


AUDIO_MARGIN = 3.0   # 取り出す範囲の前後の余裕(秒)。音量補正(dynaudnorm)の窓が数秒あるので、端で音が変わらないよう広めに


def audio_span(targets, doc_start, doc_end, pad=0.3):
    """再認識・比較で取り出す音声の範囲(元の動画の秒)。対象の行の最初〜最後(+余裕)だけにする。
    以前は文書の範囲全体(最大6時間)を毎回取り出していて、1行の再認識でも数十秒と、1〜2GB のメモリを使っていた。"""
    a = max(doc_start, min(float(t["start"]) for t in targets) - pad - AUDIO_MARGIN)
    b = max(float(t["end"]) for t in targets) + pad + AUDIO_MARGIN
    if doc_end:
        b = min(doc_end, b)
    return round(a, 3), round(max(b, a + 0.5), 3)


def recognize_chunk(model, kw, chunk, seg, sep, terms=()):
    """短い範囲を認識して (文章, 要確認の理由) を返す。何も認識できなければ None。"""
    if len(chunk) < 1600:
        return None
    segs, _info = model.transcribe(chunk, **kw)
    parts, lp, ns, cr = [], [], [], []
    for x in segs:
        t = (x.text or "").strip()
        if t:
            parts.append(t)
            for lst, key in ((lp, "avg_logprob"), (ns, "no_speech_prob"), (cr, "compression_ratio")):
                v = getattr(x, key, None)
                if v is not None:
                    lst.append(v)
    text = sep.join(parts)
    if not text:
        return None
    agg = {"text": text, "start": seg["start"], "end": seg["end"], "avg_logprob": min(lp) if lp else None,
           "no_speech_prob": max(ns) if ns else None, "compression_ratio": max(cr) if cr else None}
    return text, make_flags(agg, [], kw.get("language"), terms)


def replace_original(orig, a, b, text):
    """機械の出力の記録のうち、a〜b にある分を、新しい機械の出力1件に差し替える(再認識の結果を『人が直した』と誤学習しないため)。"""
    keep = [o for o in orig if not (a <= (o["start"] + o["end"]) / 2 <= b)]
    keep.append({"start": a, "end": b, "text": text[:MAX_TEXT]})
    keep.sort(key=lambda o: o["start"])
    return keep


def apply_retranscribe(spec, results):
    with _save_lock:   # 保存と同じロック(apply_diarization と同じ理由)
        return _apply_retranscribe(spec, results)


def _apply_retranscribe(spec, results):
    doc = read_transcript(spec["tid"])
    pairs = parse_replacements(load_settings().get("replacements")) if spec.get("autoDict") else []
    have_orig = isinstance(doc.get("original"), list)
    orig = doc["original"] if have_orig else []
    done = unsure = 0
    for sg in doc.get("segments") or []:
        r = results.get(sg["id"])
        if not r:
            continue
        raw, flag = r
        keep = [x for x in str(sg.get("flag", "")).split("、") if x in SPK_FLAGS]   # 話者の印は残し、文字の印は付け直す
        sg["text"], _ = apply_replacements(raw[:MAX_TEXT], pairs)
        sg.pop("proofed", None)   # 機械が書き換えた行は、人が確認し直すまで校正済みにしない
        sg["flag"] = "、".join(([flag] if flag else []) + keep)[:100]
        unsure += 1 if flag else 0
        done += 1
        if have_orig:
            orig = replace_original(orig, sg["start"], sg["end"], raw)
    if have_orig:
        doc["original"] = orig
    bak = os.path.join(TX_DIR, ".bak")
    os.makedirs(bak, exist_ok=True)
    shutil.copy2(tx_path(spec["tid"]), os.path.join(bak, spec["tid"] + ".pre-retranscribe.json"))
    try:
        hist_snapshot(spec["tid"], force=True)
    except OSError:
        pass
    doc["retranscribed"] = {"model": spec["model"], "lines": done, "at": int(time.time() * 1000)}
    doc["updatedAt"] = int(time.time() * 1000)
    apply_edit_cuts(spec["tid"], doc)
    atomic_write(tx_path(spec["tid"]), json.dumps(doc, ensure_ascii=False, indent=1).encode("utf-8"))
    return done, unsure


def _in_spans(t, spans):
    return any(p0 <= t <= p1 for p0, p1 in spans)


def replace_original_multi(orig, a, b, items, keep=()):
    """機械の出力の記録のうち、a〜b にある分を新しい機械の出力に差し替える。keep の区間(校正済み・元のまま残した行)にある分は古いまま残す"""
    keep_o = [o for o in orig if not (a <= (o["start"] + o["end"]) / 2 <= b) or _in_spans((o["start"] + o["end"]) / 2, keep)]
    keep_o += [{"start": x["start"], "end": x["end"], "text": x["raw"][:MAX_TEXT], **(x.get("conf") or {})} for x in items]
    keep_o.sort(key=lambda o: o["start"])
    return keep_o


# ---------- 範囲・全体の再認識の反映(docs/design/whole-retranscribe-design.md の 3-4・4-2) ----------
PROTECT_PAD = 0.05      # 守る行(校正済み・元のまま残す行)の前後の余白(秒)
MIN_NEW_LINE = 0.3      # 守る区間を避けて切り詰めた行がこれより短ければ捨てる(秒)
EMPTY_COVER = 0.3       # 元の行の時間のうち、新しい行が重なるのがこの割合未満なら「新しい認識でほぼ空」→ 元の行を残す
LOOSE_PAD = 0.5         # ほぼ空だった所を緩い条件で認識し直すときの前後の余白(秒)
EMPTY_FLAG = "再認識で文字が出なかった(元の行のまま)"
LOOSE_FLAG = "声が重なる所などを緩い条件で認識"


def _ov(a0, a1, b0, b1):
    return max(0.0, min(a1, b1) - max(a0, b0))


def merge_spans(spans):
    out = []
    for p0, p1 in sorted(spans):
        if out and p0 <= out[-1][1]:
            out[-1] = (out[-1][0], max(out[-1][1], p1))
        else:
            out.append((p0, p1))
    return out


def fit_lines(lines, protect, strip=True):
    """新しい行が守る区間 protect=[(a,b)] にかからないようにする: 真ん中が守る区間に入る行は捨て、一部だけ重なる行は外側に切り詰める
    (単語の時刻があれば文字も切り詰める)。MIN_NEW_LINE 秒未満になった行は捨てる"""
    out = []
    for x in lines:
        st, en = float(x["start"]), float(x["end"])
        mid = (st + en) / 2
        if _in_spans(mid, protect):
            continue
        for p0, p1 in protect:
            if p1 <= st or p0 >= en:
                continue
            if p0 <= st:
                st = p1
            elif en <= p1:
                en = p0
            elif mid < p0:   # 守る区間が行の中にある: 真ん中のある側を残す
                en = p0
            else:
                st = p1
        if en - st < MIN_NEW_LINE:
            continue
        if (st, en) != (x["start"], x["end"]):
            ws = [w for w in x.get("words") or [] if st - 1e-6 <= (w[0] + w[1]) / 2 <= en + 1e-6]
            y = dict(x, start=st, end=en, words=ws)
            if x.get("words"):
                joined = "".join(w[2] for w in ws).strip()
                y["raw"] = strip_punct(joined) if strip else joined
                if not y["raw"]:
                    continue
            x = y
        out.append(x)
    return out


def plan_range(doc, spec, lines):
    """範囲・全体の再認識の反映の計画(文書は変えない)。
    -> {"protect": 守る区間, "kept": 守った行(範囲にかかる、差し替えない行), "lines": 守る区間を避けた新しい行,
        "empty": 新しい認識でほぼ空だった差し替え対象の行(元のまま残す)}"""
    a, b = spec["range"]
    ids = set(spec["ids"])
    segs = [g for g in doc.get("segments") or [] if isinstance(g, dict)]
    kept = [g for g in segs if g["id"] not in ids and _ov(g["start"], g["end"], a, b) > 0]
    protect = [(g["start"] - PROTECT_PAD, g["end"] + PROTECT_PAD) for g in kept]
    fitted = fit_lines(lines, protect, spec.get("stripPunct", True) is not False)
    empty = []
    for g in segs:
        if g["id"] not in ids or not str(g.get("text") or "").strip():
            continue
        d = g["end"] - g["start"]
        cover = sum(_ov(g["start"], g["end"], x["start"], x["end"]) for x in fitted) / d if d > 0 else 1.0
        if cover < EMPTY_COVER:
            empty.append(g)
    return {"protect": protect, "kept": kept, "lines": fitted, "empty": empty}


def apply_range(spec, lines, loose=()):
    """範囲の行を、新しく認識した行に差し替える。話者は、時間が最も重なっていた元の行から引き継ぐ。
    lines=[{start,end,raw,flag,words?,conf?}]、loose = ほぼ空だった所を緩い条件で認識した行(印を付けて入れる)。
    差し替えない行(spec["ids"] に無い行。全体の再認識では校正済み)にかかる新しい行は避け、新しい認識でほぼ空だった元の行は残す(4-2・3-4)。
    -> {"lines": 入れた新しい行の数, "unsure", "kept": 守った行の数, "emptyKept": 元のまま残した行の数, "loose": 緩い条件の行の数}"""
    with _save_lock:   # 保存と同じロック(apply_diarization と同じ理由)
        return _apply_range(spec, lines, loose)


def _apply_range(spec, lines, loose=()):
    a, b = spec["range"]
    doc = read_transcript(spec["tid"])
    pairs = parse_replacements(load_settings().get("replacements")) if spec.get("autoDict") else []
    loose = [dict(x, flag="、".join(f for f in (LOOSE_FLAG, x.get("flag", "")) if f)) for x in loose]
    plan = plan_range(doc, spec, sorted(list(lines) + loose, key=lambda x: x["start"]))
    empty_ids = {g["id"] for g in plan["empty"]}
    empty_spans = [(g["start"] - PROTECT_PAD, g["end"] + PROTECT_PAD) for g in plan["empty"]]
    keep_spans = plan["protect"] + empty_spans
    new_lines = fit_lines(plan["lines"], empty_spans, spec.get("stripPunct", True) is not False)   # 元のまま残す行にもかけない
    ids = set(spec["ids"])
    old = [g for g in doc.get("segments") or [] if g["id"] in ids]
    rest = [g for g in doc.get("segments") or [] if g["id"] not in ids or g["id"] in empty_ids]
    for g in rest:
        if g["id"] in empty_ids and EMPTY_FLAG not in str(g.get("flag") or ""):
            g["flag"] = "、".join(f for f in (str(g.get("flag") or ""), EMPTY_FLAG) if f)[:100]
    used = {g["id"] for g in rest}
    new, unsure, n = [], 0, 0
    for x in new_lines:
        best, bo = "", 0.0
        for g in old:
            ov = min(g["end"], x["end"]) - max(g["start"], x["start"])
            if ov > bo and g.get("speaker"):
                best, bo = g["speaker"], ov
        text, _ = apply_replacements(x["raw"][:MAX_TEXT], pairs)
        while True:
            n += 1
            sid = "r%d" % n
            if sid not in used:
                used.add(sid)
                break
        new.append({"id": sid, "start": round(x["start"], 2), "end": round(x["end"], 2), "text": text, "speaker": best, "flag": x.get("flag", "")[:100]})
        unsure += 1 if x.get("flag") else 0
    doc["segments"] = sorted(rest + new, key=lambda g: (g["start"], g["end"]))
    if isinstance(doc.get("original"), list):   # 守った行・元のまま残した行の機械の出力は古いまま(人が直した行との対応を壊さない)
        doc["original"] = replace_original_multi(doc["original"], a, b, new_lines, keep_spans)
    bak = os.path.join(TX_DIR, ".bak")
    os.makedirs(bak, exist_ok=True)
    shutil.copy2(tx_path(spec["tid"]), os.path.join(bak, spec["tid"] + ".pre-retranscribe.json"))
    try:
        hist_snapshot(spec["tid"], force=True)
    except OSError:
        pass
    n_loose = sum(1 for x in new_lines if LOOSE_FLAG in str(x.get("flag") or ""))
    doc["retranscribed"] = {"model": spec["model"], "lines": len(new), "range": [a, b], "whole": spec.get("mode") == "whole",
                            "kept": len(plan["kept"]), "emptyKept": len(empty_ids), "loose": n_loose, "at": int(time.time() * 1000)}
    doc["updatedAt"] = int(time.time() * 1000)
    apply_edit_cuts(spec["tid"], doc)   # 差し替えた行の「カット済」は、編集の内容(時刻)から付け直す
    atomic_write(tx_path(spec["tid"]), json.dumps(doc, ensure_ascii=False, indent=1).encode("utf-8"))
    try:   # 単語の時刻も範囲の分を差し替える(守った行の単語は残す。古い文書は、ここで取り直せる = 「今の文書を分け直す」の案内)
        replace_words(spec["tid"], a, b, [w for x in new_lines for w in x.get("words") or []], spec["model"], keep_spans)
    except OSError as e:
        log.warning("単語の時刻を保存できませんでした: %s %s", spec["tid"], e)
    return {"lines": len(new), "unsure": unsure, "kept": len(plan["kept"]), "emptyKept": len(empty_ids), "loose": n_loose}


def range_lines_real(job, model, kw, audio, spec, offset):
    """範囲の音声をひとまとまりで認識し、単語の時刻で整えた行の一覧を返す。"""
    a, b = spec["range"]
    lo, hi = max(0.0, a - offset - 0.3), b - offset + 0.3
    chunk = audio[int(lo * 16000):int(hi * 16000)]
    if len(chunk) < 1600:
        return []
    segs, _info = model.transcribe(chunk, **kw)
    sep = "" if spec["language"] in ("ja", "zh", "ko") else " "
    raw = []
    for s in segs:
        if job["cancel"]:
            raise Cancelled()
        raw.append(seg_to_dict(s))
        job["progress"] = min(0.95, 0.1 + float(s.end) / max(1e-6, hi - lo))
    return finish_range_lines(raw, spec, lo + offset)


def finish_range_lines(raw, spec, shift):
    """認識した行(チャンク内の秒)を、絶対の秒にして、範囲 [a,b] の内側に収め、要確認の印を付ける。"""
    a, b = spec["range"]
    out, prev = [], []
    for s in expand_segments(raw, spec):
        if not s["text"]:
            continue
        st, en = max(a, s["start"] + shift), min(b, s["end"] + shift)
        if en - st < 0.05:
            continue
        flag = make_flags({**s, "start": st, "end": en}, prev, spec["language"], prompt_terms(spec))
        prev.append(s["text"])
        out.append({"start": st, "end": en, "raw": s["text"], "flag": flag, "words": row_words(s, shift), "lp": s.get("avg_logprob"), "conf": machine_conf(s)})
    return out


# ---------- 疑わしい所だけ認識し直す(12 ③-2。ユーザー承認 2026-09-27: 設計どおり) ----------
REDO_PAD = 1.0          # 行の前後に足す余白(秒)。ただし隣の行にはかからない(隣の行を消さないため)
REDO_MAX_ROWS = 30      # 1回で認識し直す行の上限
REDO_MAX_SEC = 600      # 時間の上限(秒)。超えたら残りの行はやめて、そこまでの結果で置き換える
REDO_BAD_FLAGS = (SPARSE_FLAG, "よくある誤認識の文", "同じ文の繰り返し", "繰り返しの可能性", "音声でない可能性", LEAK_FLAG)


def redo_targets(doc, ids=None):
    """認識し直す行: 「長い区間に文字が少ない」の印があり、校正済みでなく、文字が機械の出力のまま(人・辞書が直していない)。
    -> [(行, 範囲の始まり, 終わり)](範囲は前後 REDO_PAD 秒。隣の行・文書の範囲の外にはかからない)"""
    segs = sorted((g for g in doc.get("segments") or [] if isinstance(g, dict)), key=lambda g: (g["start"], g["end"]))
    orig = doc.get("original") if isinstance(doc.get("original"), list) else None
    machine = {(round(float(o["start"]), 2), round(float(o["end"]), 2)): o.get("text") for o in orig or [] if isinstance(o, dict)}
    lo_doc = num(doc.get("start"), 0.0) or 0.0
    hi_doc = num(doc.get("end")) or (lo_doc + (num(doc.get("duration")) or 0.0)) or None
    out = []
    for k, g in enumerate(segs):
        if (ids is not None and g["id"] not in ids) or SPARSE_FLAG not in str(g.get("flag") or "") or g.get("proofed") is True:
            continue
        if machine and machine.get((round(float(g["start"]), 2), round(float(g["end"]), 2))) != g.get("text"):
            continue   # 機械の出力と違う(人・辞書が直した)。機械の出力が無い文書(文字起こしせずに開いた)は見分けない
        a = max(float(g["start"]) - REDO_PAD, lo_doc, float(segs[k - 1]["end"]) if k else lo_doc)
        b = float(g["end"]) + REDO_PAD
        if k + 1 < len(segs):
            b = min(b, float(segs[k + 1]["start"]))
        if hi_doc:
            b = min(b, hi_doc)
        out.append((g, round(min(a, float(g["start"])), 3), round(max(b, float(g["end"])), 3)))
    return out[:REDO_MAX_ROWS]


def redo_spec(tid, req=None):
    """疑わしい所を認識し直すジョブの指定。モデルは文字起こしと同じ(kotoba なら、redoLarge で large-v3)。VAD は普通の強さで短く区切る"""
    req = req or {}
    doc = read_transcript(tid)
    if doc.get("evalSet") is True:
        raise ApiError("eval_set", "評価用の文字起こしは認識し直せません(機械の出力=比べる基準が書き換わるため)", 400)
    check_source(doc.get("sourcePath"))
    targets = redo_targets(doc)
    if not targets:
        raise ApiError("empty", "認識し直す疑わしい行がありません(「長い区間に文字が少ない」の印があり、校正・手直ししていない行が対象です)", 400)
    model = str(doc.get("model") or "large-v3")
    if not valid_model(model):
        model = "large-v3"
    if "kotoba" in model.lower() and req.get("redoLarge") is not False:
        model = "large-v3"   # kotoba は聞き取りにくい音声が苦手なので、重いモデルで試す(設定)
    with _jobs_lock:
        if any(j.get("kind") in EXCLUSIVE["redo"] and j["spec"].get("tid") == tid and j["state"] in ACTIVE_STATES for j in _jobs.values()):
            raise ApiError("busy", "この文字起こしは、すでに別の処理(話者判別・再認識)の最中です", 409)
    pr = doc.get("params") if isinstance(doc.get("params"), dict) else {}
    old_lp = req.get("oldLp") if isinstance(req.get("oldLp"), dict) else {}
    return {"tid": tid, "ids": [g["id"] for g, _a, _b in targets], "model": model, "language": doc.get("language") if doc.get("language") in LANGS else "ja",
            "beam": 5, "vadMode": "normal", "wordSplit": True, "splitChars": split_chars_for({}), "stripPunct": pr.get("stripPunct", True) is not False,
            "device": "auto", "boost": pr.get("boost") is True, "autoDict": False, "glossary": [], "glossAuto": [],
            "oldLp": {k: float(v) for k, v in old_lp.items() if isinstance(v, (int, float)) and not isinstance(v, bool)},
            "title": "疑わしい所を認識し直す: " + (str(doc.get("title") or "") or "無題")[:100]}


def redo_kwargs(spec):
    """疑わしい所を認識し直すときの設定: VAD は普通の強さで、短い無音でも区切る(長い塊に単語1つ・途中を飛ばす、を減らす)"""
    kw = whisper_kwargs(spec)
    kw["vad_filter"] = True
    kw["vad_parameters"] = {"min_silence_duration_ms": 250, "speech_pad_ms": 200}
    kw["chunk_length"] = 10
    return kw


def redo_better(row, lines, old_lp=None):
    """認識し直した結果が良くなったか: 文字が増えた・まだ疑わしい印(文字が少ない・よくある誤認識・繰り返し・BGM)が無い・
    avg_logprob が分かれば上がった。-> (良くなったか, 理由)"""
    if not lines:
        return False, "何も認識されない"
    new_chars, old_chars = sum(text_chars(x["raw"]) for x in lines), text_chars(row.get("text"))
    if new_chars <= old_chars:
        return False, "文字が増えない"
    flags = "、".join(str(x.get("flag") or "") for x in lines)
    if any(f in flags for f in REDO_BAD_FLAGS):
        return False, "まだ疑わしい"
    lps = [float(x["lp"]) for x in lines if isinstance(x.get("lp"), (int, float))]
    if old_lp is not None and lps and sum(lps) / len(lps) <= old_lp:
        return False, "自信が上がらない"
    return True, ""


def apply_redo(spec, results):
    """認識し直して良くなった行をまとめて置き換える(1回の保存。前の版は履歴に残す = 「以前の版に戻す」で戻せる)。
    途中で人が直した・校正した行は置き換えない。-> 置き換えた行の数"""
    if not results:
        return 0
    with _save_lock:
        tid = spec["tid"]
        doc = read_transcript(tid)
        segs = [g for g in doc.get("segments") or [] if isinstance(g, dict)]
        by_id = {g["id"]: g for g in segs}
        used = {g["id"] for g in segs}
        n_rep, new_words, drop = 0, [], set()
        for rid, old_text, a, b, lines in results:
            g = by_id.get(rid)
            if not g or g.get("proofed") is True or g.get("text") != old_text:
                continue
            drop.add(rid)
            n_rep += 1
            k = 0
            for x in lines:
                while True:
                    k += 1
                    sid = "%s-r%d" % (rid, k)
                    if sid not in used:
                        used.add(sid)
                        break
                segs.append({"id": sid, "start": round(x["start"], 2), "end": round(x["end"], 2), "text": x["raw"][:MAX_TEXT],
                             "speaker": g.get("speaker", ""), "flag": str(x.get("flag") or "")[:100]})
            if isinstance(doc.get("original"), list):
                doc["original"] = replace_original_multi(doc["original"], a, b, lines)
            new_words.append((a, b, [w for x in lines for w in x.get("words") or []]))
        if not n_rep:
            return 0
        try:
            hist_snapshot(tid, force=True)
        except OSError:
            pass
        doc["segments"] = sorted((g for g in segs if g["id"] not in drop), key=lambda g: (g["start"], g["end"]))
        doc["updatedAt"] = int(time.time() * 1000)
        doc["redo"] = {"model": spec["model"], "rows": n_rep, "at": doc["updatedAt"]}
        apply_edit_cuts(tid, doc)
        atomic_write(tx_path(tid), json.dumps(doc, ensure_ascii=False, indent=1).encode("utf-8"))
        for a, b, ws in new_words:
            try:
                replace_words(tid, a, b, ws, spec["model"])
            except OSError as e:
                log.warning("単語の時刻を保存できませんでした: %s %s", tid, e)
        return n_rep


def run_redo(job):
    """疑わしい所だけ認識し直す(12 ③-2)。行ごとに、前後の余白を足した範囲を今の範囲の再認識と同じ仕組みで認識し直し、良くなったものだけ最後にまとめて置き換える。
    中止したら何も置き換えない。時間の上限(REDO_MAX_SEC)を超えたら残りの行はやめる"""
    spec = job["spec"]
    wav = os.path.join(TMP_DIR, job["id"] + ".wav")
    try:
        os.makedirs(TMP_DIR, exist_ok=True)
        doc = read_transcript(spec["tid"])
        src = check_source(doc.get("sourcePath"))
        targets = redo_targets(doc, set(spec["ids"]))
        if not targets:
            job["segments"], job["tid"], job["progress"], job["state"], job["phase"] = 0, spec["tid"], 1.0, "done", "完了(認識し直す行がありませんでした)"
            return
        start, end = audio_span([{"start": a, "end": b} for _g, a, b in targets], num(doc.get("start"), 0.0) or 0.0, num(doc.get("end")))
        job["state"], job["phase"] = "extracting", "音声を取り出し中"
        extract_audio(job, {"sourcePath": src, "start": start, "end": end, "boost": spec["boost"]}, wav)
        fake = backend_name() == "fake"
        if not fake:
            if not has_faster_whisper():
                raise ApiError("no_whisper", "faster-whisper が入っていません(README の準備手順を確認してください)", 400)
            job["state"] = "loading"
            model, device = load_model(spec["model"], job, spec["device"])
            job["device"] = device
            audio = read_wav_f32(wav)
            kw = filter_kwargs(model, redo_kwargs(spec))
        else:
            job["device"] = "cpu"
        job["state"] = "running"
        t0, results, tried, timed_out = time.monotonic(), [], 0, False
        for n, (g, a, b) in enumerate(targets):
            if job["cancel"]:
                raise Cancelled()
            if time.monotonic() - t0 > REDO_MAX_SEC:
                timed_out = True
                break
            job["phase"] = "疑わしい所を認識し直し中(%d / %d)" % (n + 1, len(targets))
            sub = dict(spec, range=[a, b])
            if fake:   # テスト用: 行の長さに見合う文字数の文(TRANSCRIBE_FAKE_REDO=worse なら短いまま)
                txt = "あ" if os.environ.get("TRANSCRIBE_FAKE_REDO") == "worse" else "認識し直した文" * max(1, int((b - a) * 2 / 7) + 1)
                lines = finish_range_lines([{"start": 0.0, "end": b - a, "text": txt, "avg_logprob": -0.2, "no_speech_prob": 0.1, "compression_ratio": 1.2}], sub, a)
                time.sleep(float(os.environ.get("TRANSCRIBE_FAKE_DELAY", "0.05")))
            else:
                lines = range_lines_real(job, model, kw, audio, sub, start)
            tried += 1
            ok, _why = redo_better(g, lines, spec.get("oldLp", {}).get(g["id"]))
            if ok:
                results.append((g["id"], g["text"], a, b, lines))
            job["progress"] = min(0.95, (n + 1) / len(targets))
        if job["cancel"]:
            raise Cancelled()
        n_rep = apply_redo(spec, results)
        job["segments"], job["unsure"] = n_rep, max(0, tried - n_rep)
        job["tid"], job["progress"], job["state"] = spec["tid"], 1.0, "done"
        job["phase"] = "完了(%d か所のうち %d か所を置き換えました%s)" % (tried, n_rep, "。時間の上限で残りはやめました" if timed_out else "")
    except Cancelled:
        job["state"], job["phase"] = "cancelled", "中止しました(何も置き換えていません)"
    except ApiError as e:
        job["state"], job["error"], job["phase"] = "error", e.message, "失敗"
    except Exception as e:  # 想定外の失敗でもワーカーは止めない
        log.exception("疑わしい所の認識し直しで例外")
        job["state"], job["error"], job["phase"] = "error", "内部エラー: %s %s" % (e.__class__.__name__, str(e)[:200]), "失敗"
    finally:
        try:
            if os.path.exists(wav):
                os.unlink(wav)
        except OSError:
            pass


def _fake_spans(name):
    """テスト用: 環境変数 name = "a-b,c-d"(秒)の区間の一覧"""
    out = []
    for part in os.environ.get(name, "").split(","):
        try:
            a, b = (float(x) for x in part.split("-"))
            out.append((a, b))
        except ValueError:
            pass
    return out


class RangeRecognizer:
    """範囲・全体の再認識の認識の部分(本物のモデル / 疑似)。音声は run_retranscribe が取り出した wav(先頭 = 元の動画の offset 秒)。
    main(a, b): 範囲をひとまとまりで認識(声の検出が捨てすぎたら緩めてやり直す。4-2 の 1)
    loose(spans): ほぼ空だった所だけ、声の検出なし・捨てる判定なしで認識(4-2 の 3。よくある誤認識の文は捨てる)"""

    def __init__(self, job, spec, wav, offset):
        self.job, self.spec, self.wav, self.offset = job, spec, wav, offset
        self.fake = backend_name() == "fake"
        self.model = self.audio = None
        self.vad = None

    def _load(self):
        if self.fake or self.model is not None:
            return
        if not has_faster_whisper():
            raise ApiError("no_whisper", "faster-whisper が入っていません(README の準備手順を確認してください)", 400)
        self.job["state"] = "loading"
        self.model, device = load_model(self.spec["model"], self.job, self.spec["device"])
        self.job["device"] = device
        self.audio = read_wav_f32(self.wav)
        self.job["state"] = "running"

    def _chunk(self, a, b, pad):
        lo, hi = max(0.0, a - self.offset - pad), b - self.offset + pad
        return self.audio[int(lo * 16000):int(hi * 16000)], lo

    def main(self, a, b):
        if self.fake:
            return self._fake(a, b, False)
        self._load()
        chunk, lo = self._chunk(a, b, 0.3)
        if len(chunk) < 1600:
            return []
        total = max(1e-6, b - a + 0.6)

        def progress(r, _n):
            self.job["progress"] = min(0.9, 0.05 + r["end"] / total * 0.85)

        try:
            raw, self.vad = transcribe_vad_fallback(self.job, self.model, chunk, self.spec, progress)
        except (Cancelled, ApiError):
            raise
        except Exception:
            if self.job.get("device") == "cuda" and self.spec["device"] == "auto":
                self.job["phase"], self.job["device"] = "GPU が使えないため CPU で処理します", "cpu"
                self.model, _ = load_model(self.spec["model"], self.job, force_cpu=True)
                raw, self.vad = transcribe_vad_fallback(self.job, self.model, chunk, self.spec, progress)
            elif self.job.get("device") == "cuda":
                raise ApiError("gpu_failed", "GPU での処理に失敗しました。処理方式を「自動」か「CPU」にしてください", 500)
            else:
                raise
        return finish_range_lines(raw, self.spec, lo + self.offset)

    def loose(self, spans):
        out = []
        if not spans:
            return out
        self.job["phase"] = "文字が出なかった所を、条件を緩めて認識中"
        if self.fake:
            for s0, s1 in spans:
                out += self._fake(s0, s1, True)
            return out
        self._load()
        kw = filter_kwargs(self.model, dict(whisper_kwargs(dict(self.spec, vadMode="off")), no_speech_threshold=None))
        for n, (s0, s1) in enumerate(spans):
            if self.job["cancel"]:
                raise Cancelled()
            chunk, lo = self._chunk(s0, s1, 0.0)
            if len(chunk) < 1600:
                continue
            segs, _info = self.model.transcribe(chunk, **kw)
            raw = []
            for x in segs:
                if self.job["cancel"]:
                    raise Cancelled()
                raw.append(seg_to_dict(x))
            lines = finish_range_lines(raw, dict(self.spec, range=[s0, s1]), lo + self.offset)
            out += [x for x in lines if "よくある誤認識の文" not in str(x.get("flag") or "") and LEAK_FLAG not in str(x.get("flag") or "")]   # 無音から出やすい幻覚・ヒントの書き写しは入れない(元の行が残る)
            self.job["progress"] = min(0.99, 0.9 + 0.09 * (n + 1) / len(spans))
        return out

    def _fake(self, a, b, loose):
        """疑似: 3 秒ごとに「範囲再認識N」。TRANSCRIBE_FAKE_GAP の区間には出さない(声が重なって 0 文字の所の代わり)。
        loose のときは TRANSCRIBE_FAKE_LOOSE が 1 なら 1.5 秒ごとに「緩い条件N」(無ければ何も出ない)"""
        job = self.job
        job["state"], job["device"] = "running", "cpu"
        if loose and os.environ.get("TRANSCRIBE_FAKE_LOOSE") != "1":
            return []
        gaps = [] if loose else _fake_spans("TRANSCRIBE_FAKE_GAP")
        step, label = (1.5, "緩い条件") if loose else (3.0, "範囲再認識")
        lines, t0, k = [], a, 0
        while t0 < b - 0.05:
            if job["cancel"]:
                raise Cancelled()
            e = min(b, t0 + step)
            if not any(_ov(t0, e, g0, g1) > 0 for g0, g1 in gaps):
                k += 1
                lines.append({"start": t0, "end": e, "raw": "%s%d" % (label, k), "flag": "自信が低い" if k % 2 == 0 and not loose else ""})
            t0 = e
            job["progress"] = min(0.95, (t0 - a) / max(1e-6, b - a))
            time.sleep(float(os.environ.get("TRANSCRIBE_FAKE_DELAY", "0.05")))
        return lines


def run_retranscribe(job):
    spec = job["spec"]
    wav = os.path.join(TMP_DIR, job["id"] + ".wav")
    try:
        os.makedirs(TMP_DIR, exist_ok=True)
        doc = read_transcript(spec["tid"])
        src = check_source(doc.get("sourcePath"))
        start, end = num(doc.get("start"), 0.0) or 0.0, num(doc.get("end"))
        by_id = {g["id"]: g for g in doc.get("segments") or []}
        targets = sorted((by_id[i] for i in spec["ids"] if i in by_id), key=lambda g: g["start"])
        whole = spec.get("mode") == "whole"
        if not targets and not whole:
            raise ApiError("empty", "再認識する行が見つかりません(先に削除された可能性があります)", 400)
        span_src = targets + ([{"start": spec["range"][0], "end": spec["range"][1]}] if spec.get("mode") in ("range", "whole") else [])
        start, end = audio_span(span_src, start, end)   # 以下の start は「取り出した音声の先頭が、元の動画の何秒か」
        job["state"], job["phase"] = "extracting", "音声を取り出し中"
        extract_audio(job, {"sourcePath": src, "start": start, "end": end, "boost": spec["boost"]}, wav)
        results = {}
        if spec.get("mode") in ("range", "whole"):
            a, b = spec["range"]
            rec = RangeRecognizer(job, spec, wav, start)
            job["state"], job["phase"] = "running", "全体を認識中" if whole else "範囲を認識中"
            lines = rec.main(a, b)
            if job["cancel"]:
                raise Cancelled()
            # 新しい認識でほぼ空だった所(元の行があった所 = 声があった所)だけ、声の検出なし・捨てる判定なしで認識し直す(4-2 の 3)
            gaps = [(max(a, g["start"] - LOOSE_PAD), min(b, g["end"] + LOOSE_PAD)) for g in plan_range(doc, spec, lines)["empty"]]
            loose = rec.loose(merge_spans(gaps)) if gaps else []
            if job["cancel"]:
                raise Cancelled()
            if not lines and not loose:
                raise ApiError("no_speech", "この%sからは、文字が認識されませんでした(元の行はそのままです)" % ("動画" if whole else "範囲"), 400)
            r = apply_range(spec, lines, loose)
            job["segments"], job["unsure"], job["kept"], job["emptyKept"], job["loose"] = r["lines"], r["unsure"], r["kept"], r["emptyKept"], r["loose"]
            note = vad_note(rec.vad)
            if note:
                job["vadNote"] = note
                job.setdefault("warnings", []).append(note)
            job["tid"], job["progress"], job["state"], job["phase"] = spec["tid"], 1.0, "done", "完了"
            return
        if backend_name() == "fake":
            job["state"], job["phase"], job["device"] = "running", "再認識中", "cpu"
            for n, t in enumerate(targets):
                if job["cancel"]:
                    raise Cancelled()
                results[t["id"]] = (t["text"] + "(再)", "自信が低い" if n % 3 == 0 else "")
                job["progress"] = (n + 1) / len(targets)
                time.sleep(float(os.environ.get("TRANSCRIBE_FAKE_DELAY", "0.05")))
        else:
            if not has_faster_whisper():
                raise ApiError("no_whisper", "faster-whisper が入っていません(README の準備手順を確認してください)", 400)
            job["state"] = "loading"
            model, device = load_model(spec["model"], job, spec["device"])
            job["device"] = device
            audio = read_wav_f32(wav)
            job["state"], job["phase"] = "running", "再認識中"
            kw = filter_kwargs(model, whisper_kwargs(spec))
            sep = "" if spec["language"] in ("ja", "zh", "ko") else " "
            for n, t in enumerate(targets):
                if job["cancel"]:
                    raise Cancelled()
                a, b = max(0.0, t["start"] - start - 0.3), t["end"] - start + 0.3   # 前後に少し余裕を持たせる(語頭・語尾が欠けにくい)
                chunk = audio[int(a * 16000):int(b * 16000)]
                try:
                    r = recognize_chunk(model, kw, chunk, t, sep, prompt_terms(spec))
                except Exception:
                    if n == 0 and device == "cuda" and spec["device"] == "auto":   # 自動のとき、GPU が実行時に失敗したら CPU でやり直す
                        job["phase"], job["device"] = "GPU が使えないため CPU で処理します", "cpu"
                        model, device = load_model(spec["model"], job, force_cpu=True)
                        kw = filter_kwargs(model, whisper_kwargs(spec))
                        r = recognize_chunk(model, kw, chunk, t, sep, prompt_terms(spec))
                    elif device == "cuda" and spec["device"] == "cuda":
                        raise ApiError("gpu_failed", "GPU での処理に失敗しました。処理方式を「自動」か「CPU」にしてください", 500)
                    else:
                        raise
                if r:
                    text, flag = r
                    results[t["id"]] = (strip_punct(text) if spec.get("stripPunct", True) else text, flag)
                job["progress"] = min(0.99, (n + 1) / len(targets))
        if job["cancel"]:
            raise Cancelled()
        job["segments"], job["unsure"] = apply_retranscribe(spec, results)
        job["tid"], job["progress"], job["state"], job["phase"] = spec["tid"], 1.0, "done", "完了"
    except Cancelled:
        job["state"], job["phase"] = "cancelled", "中止しました"
    except ApiError as e:
        job["state"], job["error"], job["phase"] = "error", e.message, "失敗"
    except Exception as e:
        job["state"], job["error"], job["phase"] = "error", "内部エラー: %s %s" % (e.__class__.__name__, str(e)[:200]), "失敗"
    finally:
        try:
            if os.path.exists(wav):
                os.unlink(wav)
        except OSError:
            pass


# ---------- 設定の比較(A/B): 校正済みの行の音声を複数の設定で認識し直し、正解との差を比べる(文字起こしは書き換えない) ----------
MAX_AB_LINES = 300
MAX_AB_VARIANTS = 4
KEEP_EVALS = 60


def ab_label(v):
    own = v.get("terms") or []
    g = ("独自%d語(%s…)" % (len(own), "、".join(own[:2])) if own else "あり") if v["glossary"] else "なし"
    return "%s / 用語集%s" % (str(v["model"]).split("/")[-1], g)


def validate_abtest(req):
    tid = str(req.get("tid") or "")
    doc = read_transcript(tid)
    check_source(doc.get("sourcePath"))
    ids = [g["id"] for g in doc.get("segments") or [] if isinstance(g, dict) and g.get("proofed") and "unclear" not in (g.get("tags") or []) and str(g.get("text", "")).strip()][:MAX_AB_LINES]
    if not ids:
        raise ApiError("empty", "校正済みの行がありません(正しく直した行に「校正済み」を付けてから比べてください)", 400)
    variants = []
    for v in (req.get("variants") or [])[:MAX_AB_VARIANTS]:
        if not isinstance(v, dict):
            continue
        m = str(v.get("model") or "").strip()
        if not valid_model(m):
            raise ApiError("bad_model", "モデル名が正しくありません", 400)
        one = {"model": m, "glossary": v.get("glossary") is not False}
        # 設定ごとの用語集: 空なら共通の用語集(+自動追加)を使う。書いてあればその設定だけ、その語だけを使う(自動追加はしない)
        own = list(dict.fromkeys(t.strip() for t in re.split(r"[\r\n,、]+", str(v.get("terms") or "")) if t.strip()))[:200]
        if one["glossary"] and own:
            one["terms"] = own
        if one not in variants:
            variants.append(one)
    if not variants:
        raise ApiError("empty", "比べる設定がありません", 400)
    lang = str(req.get("language") or doc.get("language") or "ja")
    glossary = [t.strip() for t in re.split(r"[\r\n,、]+", str(req.get("glossary") or "")) if t.strip()][:200]
    gauto = auto_glossary(glossary) if req.get("autoGloss") is not False else []
    with _jobs_lock:
        if any(j.get("kind") == "abtest" and j["spec"].get("tid") == tid and j["state"] in ("queued", "loading", "extracting", "running") for j in _jobs.values()):
            raise ApiError("busy", "この文字起こしは、すでに比較の最中です", 409)
    return {"tid": tid, "ids": ids, "variants": variants, "language": lang if lang in LANGS else "ja", "beam": 5, "vadMode": "off",
            "device": req.get("device") if req.get("device") in ("cuda", "cpu") else "auto", "boost": req.get("boost") is True,
            "glossary": glossary + gauto, "title": "設定の比較: " + (str(doc.get("title") or "") or "無題")[:100]}


def _fake_hyp(text, glossary, n):
    """テスト用の疑似出力。用語集ありは完全一致(ときどき用語を余計に出す)、なしは最後の1文字が抜ける。"""
    if glossary:
        return text + (glossary[0] if n % 3 == 2 else "")
    return text[:-1] if len(text) > 1 else text


def run_abtest(job):
    spec = job["spec"]
    wav = os.path.join(TMP_DIR, job["id"] + ".wav")
    try:
        os.makedirs(TMP_DIR, exist_ok=True)
        doc = read_transcript(spec["tid"])
        src = check_source(doc.get("sourcePath"))
        start, end = num(doc.get("start"), 0.0) or 0.0, num(doc.get("end"))
        by_id = {g["id"]: g for g in doc.get("segments") or []}
        targets = sorted((by_id[i] for i in spec["ids"] if i in by_id), key=lambda g: g["start"])
        if not targets:
            raise ApiError("empty", "比べる校正済みの行が見つかりません", 400)
        start, end = audio_span(targets, start, end)   # 以下の start は「取り出した音声の先頭が、元の動画の何秒か」
        job["state"], job["phase"] = "extracting", "音声を取り出し中"
        extract_audio(job, {"sourcePath": src, "start": start, "end": end, "boost": spec["boost"]}, wav)
        fake = backend_name() == "fake"
        audio = None
        if not fake:
            if not has_faster_whisper():
                raise ApiError("no_whisper", "faster-whisper が入っていません(README の準備手順を確認してください)", 400)
            audio = read_wav_f32(wav)
        pairs = parse_replacements(load_settings().get("replacements"))
        all_terms = list(spec["glossary"]) + [t for v in spec["variants"] for t in v.get("terms", [])]
        terms = list(dict.fromkeys(metric_terms() + [x for x in (norm_cer(g) for g in all_terms) if len(x) >= 2]))
        sep = "" if spec["language"] in ("ja", "zh", "ko") else " "
        steps, n_done, out, nv = max(1, len(spec["variants"]) * len(targets)), 0, [], len(spec["variants"])
        for vi, v in enumerate(spec["variants"]):
            glossary = (v.get("terms") or spec["glossary"]) if v["glossary"] else []
            acc, acc_d, model, device, kw = new_acc(), new_acc(), None, None, None
            if not fake:
                job["state"], job["phase"] = "loading", "モデルを読み込み中(%d/%d)" % (vi + 1, nv)
                model, device = load_model(v["model"], job, spec["device"])
                job["device"] = device
                kw = filter_kwargs(model, whisper_kwargs({**spec, "model": v["model"], "glossary": glossary}))
            job["state"], job["phase"] = "running", "比較中(%d/%d)%s" % (vi + 1, nv, ab_label(v))
            for n, t in enumerate(targets):
                if job["cancel"]:
                    raise Cancelled()
                if fake:
                    raw = _fake_hyp(str(t["text"]), glossary, n)
                    time.sleep(float(os.environ.get("TRANSCRIBE_FAKE_DELAY", "0.05")))
                else:
                    a, b = max(0.0, t["start"] - start - 0.3), t["end"] - start + 0.3
                    chunk = audio[int(a * 16000):int(b * 16000)]
                    try:
                        r = recognize_chunk(model, kw, chunk, t, sep, glossary)
                    except Exception:
                        if n == 0 and device == "cuda" and spec["device"] == "auto":   # 自動のとき、GPU が実行時に失敗したら CPU でやり直す
                            job["phase"], job["device"] = "GPU が使えないため CPU で処理します", "cpu"
                            model, device = load_model(v["model"], job, force_cpu=True)
                            kw = filter_kwargs(model, whisper_kwargs({**spec, "model": v["model"], "glossary": glossary}))
                            r = recognize_chunk(model, kw, chunk, t, sep, glossary)
                        elif device == "cuda" and spec["device"] == "cuda":
                            raise ApiError("gpu_failed", "GPU での処理に失敗しました。処理方式を「自動」か「CPU」にしてください", 500)
                        else:
                            raise
                    raw = r[0] if r else ""
                ref = norm_cer(t["text"])
                acc_line(acc, ref, norm_cer(raw), terms, {"id": t["id"], "start": t["start"], "end": t["end"], "ref": str(t["text"])[:120], "hyp": raw[:120]})
                acc_line(acc_d, ref, norm_cer(apply_replacements(raw, pairs)[0]), terms)
                n_done += 1
                job["progress"] = min(0.99, n_done / steps)
            fin, fin_d = acc_finish(acc), acc_finish(acc_d)
            out.append({"model": v["model"], "glossary": v["glossary"], "terms": v.get("terms", []), "label": ab_label(v), "cer": fin["cer"], "cerDict": fin_d["cer"],
                        "sub": fin["sub"], "del": fin["del"], "ins": fin["ins"], "refChars": fin["refChars"], "lines": fin["groups"],
                        "termRef": fin["termRef"], "termHit": fin["termHit"], "termExtra": fin["termExtra"], "worst": fin["worst"]})
        if job["cancel"]:
            raise Cancelled()
        result = {"id": job["id"], "tid": spec["tid"], "title": str(doc.get("title") or "")[:100], "at": int(time.time() * 1000), "lines": len(targets),
                  "language": spec["language"], "device": job.get("device", ""), "variants": out}
        os.makedirs(EVAL_DIR, exist_ok=True)
        atomic_write(os.path.join(EVAL_DIR, job["id"] + ".json"), json.dumps(result, ensure_ascii=False, indent=1).encode("utf-8"))
        old = sorted((os.path.join(EVAL_DIR, n) for n in os.listdir(EVAL_DIR) if n.endswith(".json")), key=os.path.getmtime)
        for p in old[:-KEEP_EVALS]:
            try:
                os.unlink(p)
            except OSError:
                pass
        job["segments"], job["progress"], job["state"], job["phase"] = len(targets), 1.0, "done", "完了"
    except Cancelled:
        job["state"], job["phase"] = "cancelled", "中止しました"
    except ApiError as e:
        job["state"], job["error"], job["phase"] = "error", e.message, "失敗"
    except Exception as e:
        job["state"], job["error"], job["phase"] = "error", "内部エラー: %s %s" % (e.__class__.__name__, str(e)[:200]), "失敗"
    finally:
        try:
            if os.path.exists(wav):
                os.unlink(wav)
        except OSError:
            pass


def read_eval(eid):
    if not TID_RE.match(eid or "") or not os.path.isfile(os.path.join(EVAL_DIR, eid + ".json")):
        raise ApiError("not_found", "比較の結果が見つかりません", 404)
    try:
        with open(os.path.join(EVAL_DIR, eid + ".json"), "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        raise ApiError("broken", "比較の結果を読み込めません", 500)


def list_evals(tid=None, limit=20):
    out = []
    if os.path.isdir(EVAL_DIR):
        for n in os.listdir(EVAL_DIR):
            if not n.endswith(".json") or not TID_RE.match(n[:-5]):
                continue
            try:
                d = read_eval(n[:-5])
            except ApiError:
                continue
            if tid is None or d.get("tid") == tid:
                out.append(d)
    out.sort(key=lambda d: -int(d.get("at") or 0))
    return out[:limit]


# ---------- clip-marker との連携 ----------
def _read_json_file(path):
    try:
        with open(path, "r", encoding="utf-8-sig") as f:   # 他のツール(スタジオ・旧マーカー)が書くファイル。BOM 付きでも読む
            return json.load(f)
    except (OSError, ValueError):
        return None


def studio_out_dir(data_path):
    """スタジオの書き出し先。明示設定がなければ、スタジオと同じ exports を使う。"""
    for name in ("settings.json", "config.json"):
        s = _read_json_file(os.path.join(os.path.dirname(data_path), name))
        if isinstance(s, dict):
            v = s.get("outDir")
            if not v and isinstance(s.get("settings"), dict):
                v = s["settings"].get("outDir")
            if isinstance(v, str) and v.strip():
                p = v.strip()
                if not os.path.isabs(p):
                    p = os.path.join(os.path.dirname(data_path), p)
                return os.path.abspath(p)
    return os.path.abspath(os.path.join(os.path.dirname(data_path), "exports"))


def transcribed_ranges():
    """全文字起こしの (元ファイル・範囲・全体か・id) の一覧。フォルダ一覧・マーカーのポイントで「文字起こし済み」を判定するのに使う。"""
    out = []
    for tid in _tids():   # 一覧(list_transcripts)は動画・パックの有無も調べるので、ここでは要約だけを読む(キャッシュが効く)
        sm = transcript_summary(tid)
        sp = sm and sm["_sourcePath"]
        if not sp:
            continue
        a, b = num(sm.get("start"), 0.0) or 0.0, num(sm.get("end"))
        out.append({"path": os.path.normcase(os.path.abspath(sp)), "start": a, "end": b, "whole": sm["_whole"], "tid": tid})
    return out


def _covered(ranges, path, start, end):
    """path の [start,end] が、すでにある文字起こしに含まれているか(全体を処理したものは常に含む。部分は9割以上重なれば含む)。"""
    k = os.path.normcase(os.path.abspath(path))
    length = max(0.0001, end - start)
    for r in ranges:
        if r["path"] != k:
            continue
        if r["whole"]:
            return r["tid"]
        ov = min(r["end"] if r["end"] is not None else end, end) - max(r["start"], start)
        if ov > 0 and ov / length >= 0.9:
            return r["tid"]
    return ""


def read_marker():
    """切り抜きスタジオ(優先)と、旧クリップマーカーのマークを読む。どちらも読むだけで、書き換えない。"""
    videos, srcs, seen = [], [], set()
    out_dir = ""
    for kind, path in (("studio", STUDIO_DATA), ("marker", MARKER_DATA)):
        if not os.path.isfile(path):
            continue
        d = _read_json_file(path)
        if d is None:
            continue
        vs = marker_videos(d)
        srcs.append({"kind": kind, "path": path, "videos": len(vs)})
        if kind == "studio":
            out_dir = studio_out_dir(path)
        for v in vs:
            if v["videoId"] in seen:
                continue
            if kind == "studio" and out_dir:   # 書き出し済みの mp4(書き出し先からの相対パス)が実在すれば、その絶対パスを付ける
                base = os.path.realpath(out_dir)
                for c in v["clips"]:
                    if c["file"] and not os.path.isabs(c["file"]):
                        fp = os.path.realpath(os.path.join(base, c["file"]))
                        if os.path.commonpath([base, fp]) == base and os.path.isfile(fp):
                            c["fileAbs"] = fp
            seen.add(v["videoId"])
            videos.append({**v, "from": kind})
    ranges = transcribed_ranges()
    for v in videos:   # すでに文字起こし済みのポイントに印を付ける(書き出し済みの mp4、または元の動画パス+同じ範囲)
        for c in v["clips"]:
            if c.get("fileAbs"):
                c["doneTid"] = _covered(ranges, c["fileAbs"], 0.0, 10 ** 9) or ""
            elif v.get("sourcePath"):
                c["doneTid"] = _covered(ranges, v["sourcePath"], c["start"], c["end"])
            else:
                c["doneTid"] = ""
    return {"found": bool(srcs), "videos": videos, "sources": srcs, "outDir": out_dir}


def marker_videos(d):
    """マークの一覧を取り出す。切り抜きスタジオ/旧クリップマーカーのどちらの形でも読めるようにゆるく解釈する
    (videos は {ID: 動画} でも [動画, ...] でもよい。マークは clips / marks / points のどれか)。"""
    out = []
    vids = d.get("videos") if isinstance(d, dict) else None
    if isinstance(vids, list):
        vids = {str((v or {}).get("videoId") or (v or {}).get("id") or i): v for i, v in enumerate(vids) if isinstance(v, dict)}
    if not isinstance(vids, dict):
        return out
    for vid, v in list(vids.items())[:500]:
        if not isinstance(v, dict) or v.get("demo"):
            continue
        raw = next((v[k] for k in ("clips", "marks", "points") if isinstance(v.get(k), list)), [])
        clips = []
        for c in raw[:500]:
            if not isinstance(c, dict):
                continue
            a, b = num(c.get("start")), num(c.get("end"))
            if a is None or b is None or b <= a:
                continue
            clips.append({"id": str(c.get("id", ""))[:40], "start": a, "end": b, "title": str(c.get("title") or c.get("label") or "")[:120],
                          "status": str(c.get("status") or "")[:12], "rating": int(num(c.get("rating"), 0) or 0), "file": str(c.get("file") or "")[:500],
                          "src": str(c.get("src") or "")[:8], "score": num(c.get("score"))})
        if clips:
            out.append({"videoId": str(vid)[:20], "title": str(v.get("title", ""))[:120], "local": v.get("local") is True or str(v.get("kind", "")) in ("local", "file"),
                        "fileName": str(v.get("fileName", ""))[:200], "sourcePath": str(v.get("sourcePath") or v.get("path") or "")[:500], "clips": clips})
    return out


# ---------- 進行度(校正済みの量) ----------
_prog_cache = {}


def progress_stats():
    """校正済みの量。学習用(評価用でない文書)と評価用を分けて数える。「聞き取れない」の印がある行は、どちらも数えない。"""
    tot = {"proofedSec": 0.0, "proofedLines": 0, "docs": 0, "docsProofed": 0, "totalSec": 0.0, "totalLines": 0,
           "evalDocs": 0, "evalDocsDone": 0, "evalProofedSec": 0.0, "evalProofedLines": 0, "evalPendingLines": 0}
    seen = set()
    if os.path.isdir(TX_DIR):
        for name in os.listdir(TX_DIR):
            tid = name[:-5]
            if not name.endswith(".json") or not TID_RE.match(tid):
                continue
            seen.add(tid)
            try:
                st = os.stat(tx_path(tid))
                key = (st.st_mtime_ns, st.st_size)
                hit = _prog_cache.get(tid)
                if hit and hit[0] == key:
                    r = hit[1]
                else:
                    with open(tx_path(tid), "r", encoding="utf-8") as f:
                        d = json.load(f)
                    segs = [g for g in d.get("segments") or [] if isinstance(g, dict)]
                    dur = lambda g: max(0.0, (num(g.get("end"), 0) or 0) - (num(g.get("start"), 0) or 0))
                    good = [g for g in segs if g.get("proofed") is True and "unclear" not in (g.get("tags") or [])]
                    pend = [g for g in segs if g.get("proofed") is not True and str(g.get("text", "")).strip() and "unclear" not in (g.get("tags") or [])]
                    r = {"eval": d.get("evalSet") is True, "sec": sum(dur(g) for g in good), "lines": len(good), "pend": len(pend),
                         "totalSec": sum(dur(g) for g in segs), "totalLines": len(segs)}
                    _prog_cache[tid] = (key, r)
            except (OSError, ValueError):
                continue
            if r["eval"]:
                tot["evalDocs"] += 1
                tot["evalDocsDone"] += 1 if r["lines"] and not r["pend"] else 0
                tot["evalProofedSec"] += r["sec"]
                tot["evalProofedLines"] += r["lines"]
                tot["evalPendingLines"] += r["pend"]
                continue
            tot["docs"] += 1
            tot["docsProofed"] += 1 if r["lines"] else 0
            tot["proofedSec"] += r["sec"]
            tot["proofedLines"] += r["lines"]
            tot["totalSec"] += r["totalSec"]
            tot["totalLines"] += r["totalLines"]
    for k in [k for k in _prog_cache if k not in seen]:
        _prog_cache.pop(k, None)
    for k in ("proofedSec", "totalSec", "evalProofedSec"):
        tot[k] = round(tot[k], 1)
    return tot


# ---------- フォルダの一括読み込み ----------
MAX_SCAN_FILES = 500


def scan_folder(path, recursive=False):
    """フォルダの中の動画・音声を一覧にする。文字起こし済み(全体を処理したもの)・待機中かも返す。"""
    p = os.path.abspath(str(path or "").strip().strip('"'))
    if not os.path.isdir(p):
        raise ApiError("no_dir", "フォルダが見つかりません(パスを確認してください)", 400)
    found, trunc = [], False
    base_depth = p.rstrip(os.sep).count(os.sep)
    try:
        for root, dirs, files in os.walk(p):
            depth = root.rstrip(os.sep).count(os.sep) - base_depth
            # 途中のファイルの 作業用\(編集用素材 _edit.mp4 など)は拾わない(2026-09-27)
            dirs[:] = sorted(d for d in dirs if not d.startswith(".") and d != _yschemas.WORK_DIR) if recursive and depth < 3 else []
            for name in sorted(files):
                if name.startswith(".") or os.path.splitext(name)[1].lower() not in MEDIA_TYPES:
                    continue
                if len(found) >= MAX_SCAN_FILES:
                    trunc = True
                    break
                fp = os.path.join(root, name)
                try:
                    size = os.path.getsize(fp)
                except OSError:
                    continue
                found.append({"path": fp, "name": name, "rel": os.path.relpath(fp, p), "size": size})
            if trunc:
                break
    except OSError as e:
        raise ApiError("scan_failed", "フォルダを読めませんでした: %s" % e.__class__.__name__, 400)
    done, active = _done_and_active()
    for f in found:
        k = os.path.normcase(os.path.abspath(f["path"]))
        f["doneTid"] = done.get(k, "")
        f["queued"] = k in active
    return {"dir": p, "files": found, "truncated": trunc}


def _done_and_active():
    """({正規化したパス: 全体を文字起こし済みの id}, {待機中・処理中の文字起こしのパス})。"""
    done = {r["path"]: r["tid"] for r in transcribed_ranges() if r["whole"]}
    with _jobs_lock:
        active = {os.path.normcase(os.path.abspath(j["spec"].get("sourcePath", ""))) for j in _jobs.values()
                  if j.get("kind") == "transcribe" and j["state"] in ACTIVE_STATES and j["spec"].get("sourcePath")}
    return done, active


def add_batch(req):
    """複数のファイルを、それぞれ別の文字起こしとして待機列に入れる(設定は共通)。同じファイルが2回あっても1回だけ入れる。"""
    paths = list({os.path.normcase(os.path.abspath(str(x))): str(x) for x in (req.get("paths") or []) if isinstance(x, str) and x.strip()}.values())[:MAX_SCAN_FILES]
    if not paths:
        raise ApiError("empty", "対象のファイルがありません", 400)
    skip_done = req.get("skipDone") is not False
    info = {os.path.normcase(os.path.abspath(f["path"])): f for f in scan_common(paths)} if skip_done else {}
    added, skipped = [], []
    for fp in paths:
        k = os.path.normcase(os.path.abspath(fp))
        f = info.get(k)
        if f and (f["doneTid"] or f["queued"]):
            skipped.append({"path": fp, "reason": "文字起こし済み" if f["doneTid"] else "すでに待機中"})
            continue
        try:
            spec = validate_job({**req, "sourcePath": fp, "title": "", "start": 0, "end": None})
            added.append(public_job(add_job(spec)))
        except ApiError as e:
            skipped.append({"path": fp, "reason": e.message})
            if e.code == "busy":
                break
    return {"added": added, "skipped": skipped}


def scan_common(paths):
    """パスの一覧について、scan_folder と同じ形(doneTid / queued)を返す。
    以前はフォルダごとに scan_folder(=全文書の読み直し)を呼んでいて、サブフォルダが多いと遅く、500件を超えるフォルダでは判定が漏れた。"""
    done, active = _done_and_active()
    out = []
    for p in paths:
        k = os.path.normcase(os.path.abspath(p))
        out.append({"path": p, "doneTid": done.get(k, ""), "queued": k in active})
    return out


# ---------- 受け渡しの API(docs/spec/pipeline.md の 2・4・6) ----------
def _pipeline_error(e):
    return ApiError(e.code, e.message, e.status)


def clip_info(path):
    """GET /api/clip-info?path=。path は動画のパスか、.clip.json のパス(画面の ?clip= 用)。
    戻り値 {"clip": clip/v1 または null, "clipPath", "mediaPath", "warning"}。clip が使えないときは clip=null と理由(warning)。
    path が空・動画でも .clip.json でもないときだけ 400(画面が ?media= で開いたときに、例外にせず表示だけ省けるように)。"""
    pm = pio()
    p = str(path or "").strip().strip('"')
    if not p or "\x00" in p:
        raise ApiError("bad_request", "path(動画のパス)を指定してください", 400)
    out = {"clip": None, "clipPath": None, "mediaPath": None, "warning": None}
    if pm.is_network_path(p):
        # 画面は URL の ?media= を受けて自動でこれを呼ぶ(他のサイトのリンクでも開ける)。ネットワークのパスを調べると
        # Windows がそのサーバーへ資格情報を送るので、ここでは調べない(文字起こしの開始ボタンでは従来どおり使える)
        out["warning"] = "ネットワーク上のパスは、元の配信の情報を自動では調べません"
        return out
    p = os.path.abspath(p)
    if p.lower().endswith(pm.CLIP_SUFFIX):
        if not os.path.isfile(p):
            out["warning"] = ".clip.json が見つかりません"
            return out
        clip, warn = pm.load_clip_file(p)
        out.update({"clip": clip, "clipPath": p if clip else None, "warning": warn})
        if clip:
            out["mediaPath"] = pm.resolve_clip_media(p, clip, MEDIA_TYPES)
            if not out["mediaPath"]:
                out["warning"] = ".clip.json が指す動画が見つかりません(同じフォルダにも見当たりません)"
        return out
    if os.path.splitext(p)[1].lower() not in MEDIA_TYPES:
        raise ApiError("bad_ext", "動画・音声ファイルか .clip.json のパスを指定してください", 400)
    if not os.path.isfile(p):
        out["warning"] = "動画が見つかりません(パスを確認してください)"
        return out
    clip, warn, cp = pm.find_clip(p)   # ここでは長さの照合はしない(ffmpeg を呼ばず、すぐ返す)
    out.update({"clip": clip, "clipPath": cp if clip else None, "mediaPath": p, "warning": warn})
    return out


def transcript_v1(tid):
    return pio().build_transcript_v1(read_transcript(tid), SERVER_VERSION)


def export_file(req):
    """POST /api/export-file {"id", "format": transcript-v1|srt|cut-plan-v1, "baseUpdatedAt"?, "wrap"?, "speakerNames"?}
    → 動画の隣に保存して {"path", "name", "overwritten", "format", "count"}。保存済みの内容を書き出す(画面は先に保存してから呼ぶ)。
    baseUpdatedAt を付けると、保存済みの版と違うとき 409(画面の表示と違う内容を書き出さないため)。"""
    pm = pio()
    tid = str(req.get("id") or "")
    fmt = req.get("format")
    if fmt not in pm.EXPORT_FORMATS:
        raise ApiError("bad_format", "format は transcript-v1 / srt / cut-plan-v1 のどれかにしてください", 400)
    doc = read_transcript(tid)
    b = req.get("baseUpdatedAt")
    if b is not None and doc.get("updatedAt") and b != doc.get("updatedAt"):
        raise ApiError("conflict", "保存されていない変更があるか、別の場所で更新されています。保存してから、もう一度書き出してください", 409)
    src = str(doc.get("sourcePath") or "")
    if not src:
        raise ApiError("no_media", "この文字起こしには元の動画のパスがありません(動画の隣には保存できません。ダウンロードを使ってください)", 400)
    if not os.path.isfile(src):
        raise ApiError("no_media", "元の動画が見つかりません(移動・削除した可能性があります): %s" % src, 400)
    suffix = pm.EXPORT_FORMATS[fmt]
    if fmt == "transcript-v1":
        obj = pm.build_transcript_v1(doc, SERVER_VERSION)
        count, schema = len(obj["segments"]), pm.TRANSCRIPT_SCHEMA
        if not count:
            raise ApiError("empty", "書き出す行がありません(文字のある行がありません)", 400)
        data = (json.dumps(obj, ensure_ascii=False, indent=1) + "\n").encode("utf-8")
    elif fmt == "cut-plan-v1":
        obj = pm.build_cut_plan_v1(doc, SERVER_VERSION)
        ed, _broken = read_edit(tid)
        if ed:   # 「編集」のカットがあれば、残す区間はそのとおり(行の区間ではなく)
            obj["segments"] = [{"id": "segment-%03d" % i, "start": a, "end": b, "status": "adopted", "label": ""}
                               for i, (a, b) in enumerate(edit_keeps_sec(ed), 1)]
        count, schema = len(obj["segments"]), pm.CUT_PLAN_SCHEMA
        if not count:
            raise ApiError("empty", "残す区間がありません(すべての行が「カット済」か、文字のある行がありません)", 400)
        data = (json.dumps(obj, ensure_ascii=False, indent=1) + "\n").encode("utf-8")
    else:
        try:
            wrap = max(0, min(200, int(req.get("wrap") or 0)))
        except (TypeError, ValueError):
            wrap = 0
        text, count = pm.build_srt(doc, wrap, req.get("speakerNames") is True)
        schema = None   # SRT は中身で「前にこのツールが書いたか」を判断できないので、同名があれば常に別名にする
        if not count:
            raise ApiError("empty", "書き出す行がありません(文字のある行がありません)", 400)
        data = text.encode("utf-8")   # BOM なし(docs/spec/pipeline.md の 1)
    try:
        path, overwritten = pm.save_beside(src, suffix, data, schema)
    except pm.PipelineError as e:
        raise _pipeline_error(e)
    log.info("動画の隣に保存: %s %s(%s)", fmt, os.path.basename(path), "上書き" if overwritten else "新規")
    return {"path": path, "name": os.path.basename(path), "overwritten": overwritten, "format": fmt, "count": count}


def runtime_path_dir():
    """<editor の1つ上>/.runtime(環境変数 YTT_RUNTIME_DIR が優先)。pipeline_io.runtime_dir と同じ規則。"""
    return _runtime.runtime_dir(ROOT)


# ---------- HTTP ----------
QUIET_PATHS = ("/api/jobs", "/media", "/api/siblings", "/api/progress", "/api/clip-info", "/api/peaks", "/api/edit", "/api/doc-for")   # 画面が頻繁に呼ぶ・パスを含むので、黒い画面に出さない
PAGE_HEADERS = httpsec.PAGE_HEADERS


class Handler(BaseHTTPRequestHandler):
    server_version = "TranscribeTool/0.1"
    timeout = 120   # 送ると言った長さより短い本文・読まれない応答で、処理のスレッドが永久に止まらないように(秒)

    def log_message(self, fmt, *args):
        if self.path.startswith(QUIET_PATHS):
            return
        super().log_message(fmt, *args)

    def send_response(self, code, message=None):
        self._responded = True
        super().send_response(code, message)

    # 安全検査の規則は ytt_core.httpsec に1か所(スタジオ・文字起こし・入口で共通)
    def _host_ok(self):
        return httpsec.host_ok(self.headers, ALLOWED_HOSTS)

    def _origin_ok(self):
        # 「http://」+ 許可したホスト と完全に一致するものだけ
        return httpsec.origin_ok(self.headers, ALLOWED_HOSTS)

    def _fetch_site_ok(self):
        return httpsec.fetch_site_ok(self.headers)

    def _navigation_ok(self, path):
        """他のツールの画面のリンク(http://localhost:8800 → http://localhost:8775/?media=...)で、この画面を開くのは許す。
        ポートが違うだけでも Sec-Fetch-Site は same-site(127.0.0.1 と localhost なら cross-site)になるため、以前は 403 になっていた。
        画面(index.html)を新しいタブで開くだけで、URL で重い処理は始まらない(docs/spec/pipeline.md の 3)。API は従来どおり同じ画面からだけ。
        埋め込み(iframe)での悪用は X-Frame-Options / frame-ancestors で防ぐ。"""
        return httpsec.navigation_ok(self.headers, path)

    def _send(self, code, body=b"", ctype="text/plain; charset=utf-8", extra=None):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _json(self, code, obj):
        self._send(code, json.dumps(obj, ensure_ascii=False).encode("utf-8"), "application/json")

    def _err(self, e):
        self._json(e.status, dict(e.extra, error=e.code, message=e.message))

    def _fail(self, code, error, message):
        """画面の api() が理由を表示できるよう、エラーも JSON で返す(以前は 403/413/415 が素の文字列で「エラー 403」としか出なかった)。"""
        self._json(code, {"error": error, "message": message})

    def _read_json(self):
        if (self.headers.get("Content-Type") or "").split(";")[0].strip() != "application/json":
            self._fail(415, "bad_type", "Content-Type は application/json にしてください")
            return None
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            self._fail(400, "bad_length", "Content-Length が正しくありません")
            return None
        if length <= 0 or length > MAX_BODY:
            self._fail(413, "too_big", "送る内容が空か、大きすぎます(最大%dMB)" % (MAX_BODY // 1048576))
            return None
        try:
            obj = json.loads(self.rfile.read(length), parse_constant=_reject_json_constant)   # NaN / Infinity は受け付けない(保存すると画面の JSON.parse が壊れる)
        except ValueError:
            self._fail(400, "bad_json", "JSON として読めません")
            return None
        if not isinstance(obj, dict):
            self._fail(400, "bad_json", "JSON のオブジェクトを送ってください")
            return None
        return obj

    def _guard(self, write, path=""):
        if not self._host_ok():
            self._fail(403, "forbidden", "このツールは http://localhost:%d%s から開いてください(Host が違います)" % (PORT, BASE_PATH))
            return False
        if not (self._fetch_site_ok() or (not write and self._navigation_ok(path))) or (write and not self._origin_ok()):
            self._fail(403, "forbidden", "別のサイト・別のツールの画面からの操作は受け付けません")
            return False
        return True

    def _safe(self, fn):
        """想定外の例外でも、黙って接続を切らずに 500 と理由を返し、serve.log に残す。"""
        self._responded = False
        try:
            fn()
        except (BrokenPipeError, ConnectionError, socket.timeout):
            pass
        except Exception as e:
            log.exception("要求の処理で例外: %s %s", self.command, self.path.split("?", 1)[0])
            if not self._responded:
                try:
                    self._fail(500, "internal", "内部エラー: %s %s(serve.log に記録しました)" % (e.__class__.__name__, str(e)[:200]))
                except Exception:
                    pass

    def do_HEAD(self):
        self._safe(self._get)

    def do_GET(self):
        self._safe(self._get)

    def do_POST(self):
        self._safe(self._post)

    def do_PUT(self):
        self._safe(self._put)

    def do_DELETE(self):
        self._safe(self._delete)

    def _get(self):
        u = urllib.parse.urlsplit(self.path)
        if not self._guard(False, u.path):
            return
        q = urllib.parse.parse_qs(u.query)
        try:
            if u.path in ("/", "/index.html"):
                with open(INDEX, "rb") as f:
                    return self._send(200, f.read(), "text/html; charset=utf-8", PAGE_HEADERS)
            if u.path == "/app.js":
                with open(APP_JS, "rb") as f:
                    return self._send(200, f.read(), "text/javascript; charset=utf-8")
            if u.path == "/ui-kit.js":
                with open(UI_KIT_JS, "rb") as f:
                    return self._send(200, f.read(), "text/javascript; charset=utf-8")
            if u.path.lstrip("/") in PAGE_JS and os.path.isfile(os.path.join(ROOT, u.path.lstrip("/"))):
                with open(os.path.join(ROOT, u.path.lstrip("/")), "rb") as f:
                    return self._send(200, f.read(), "text/javascript; charset=utf-8")
            if u.path == "/api/ping":
                w = WORKER   # 認識ワーカーの状態(入口の「調子」が読む。段9 9-1)
                return self._json(200, {"app": APP_ID, "version": SERVER_VERSION,
                                        "worker": {"alive": w.alive(), "pid": (w.proc.pid if w.proc is not None else None), "starts": w.starts,
                                                   "lastUsedAgo": (int(time.time() - w.last_used) if w.last_used else None), "silenceTimeoutSec": WORKER_SILENCE_TIMEOUT}})
            if u.path == "/api/siblings":
                return self._json(200, pio().siblings(runtime_path_dir(), TOOL_ID, PORT, self_path=BASE_PATH))
            if u.path == "/api/clip-info":
                return self._json(200, clip_info((q.get("path") or [""])[0]))
            if u.path == "/api/transcript-v1":
                return self._json(200, transcript_v1((q.get("id") or [""])[0]))
            if u.path == "/api/roster":
                return self._json(200, load_roster())
            if u.path == "/api/tools":
                return self._json(200, {"ffmpeg": bool(find_ffmpeg()), "fasterWhisper": has_faster_whisper(), "cuda": gpu_ready(), "nvidia": nvidia_gpu(),
                                        "backend": backend_name(), "diarize": diar_info(), "models": MODELS, "langs": LANGS, "root": TX_DIR,
                                        "envWarnings": list(_env_warnings)})
            if u.path == "/api/settings":
                try:
                    with open(SETTINGS, "rb") as f:
                        raw = f.read()
                    return self._send(200, raw[3:] if raw.startswith(b"\xef\xbb\xbf") else raw, "application/json")
                except OSError:
                    return self._json(200, {})
            if u.path == "/api/marker":
                return self._json(200, read_marker())
            if u.path == "/api/voices":   # A-3: 覚えている声の一覧(特徴そのものは返さない)
                return self._json(200, {"voices": voices_summary(), "match": VOICE_MATCH})
            if u.path == "/api/voices/preview":   # 段1(監査17・18): 覚える前の確認(読むだけ。話者の名前を返すので、ほかの GET と同じ Host/Origin 検査の下)
                return self._json(200, voice_preview((q.get("tid") or [""])[0], (q.get("embedding") or [""])[0]))
            if u.path == "/api/transcribed-ranges":
                return self._json(200, {"items": transcribed_ranges()})
            if u.path == "/api/jobs":
                with _jobs_lock:
                    return self._json(200, {"jobs": [public_job(_jobs[i]) for i in _order if i in _jobs]})
            if u.path == "/api/transcripts":
                return self._json(200, {"items": list_transcripts()})
            if u.path == "/api/learned":
                mc = (q.get("min") or ["1"])[0]
                return self._json(200, learned_candidates(max(1, min(20, int(mc))) if mc.isdigit() else 1))
            if u.path == "/api/suggest":
                tid = (q.get("id") or [""])[0]
                if not TID_RE.match(tid):
                    raise ApiError("not_found", "文字起こしが見つかりません", 404)
                return self._json(200, suggest_for_doc(tid))
            if u.path == "/api/metrics":
                tid = (q.get("id") or [""])[0]
                if tid and not TID_RE.match(tid):
                    raise ApiError("not_found", "文字起こしが見つかりません", 404)
                sc = (q.get("scope") or ["all"])[0]
                return self._json(200, all_metrics(tid or None, (q.get("legacy") or ["0"])[0] == "1", sc if sc in ("all", "eval", "train") else "all"))
            if u.path == "/api/eval-baselines":
                return self._json(200, {"items": read_baselines()})
            if u.path == "/api/evals":
                tid = (q.get("id") or [""])[0]
                if tid and not TID_RE.match(tid):
                    raise ApiError("not_found", "文字起こしが見つかりません", 404)
                return self._json(200, {"items": list_evals(tid or None)})
            if u.path == "/api/eval":
                return self._json(200, read_eval((q.get("id") or [""])[0]))
            if u.path == "/api/progress":
                return self._json(200, progress_stats())
            if u.path == "/api/dataset":
                return self._json(200, dataset_stats())
            if u.path == "/api/history":
                return self._json(200, {"items": list_history((q.get("id") or [""])[0])})
            if u.path == "/api/transcript":
                return self._json(200, read_transcript((q.get("id") or [""])[0]))
            if u.path == "/api/edit":
                return self._json(200, get_edit((q.get("id") or [""])[0]))
            if u.path == "/api/edit/draft":
                return self._json(200, edit_draft((q.get("id") or [""])[0], (q.get("rows") or [""])[0] == "1"))
            if u.path == "/api/edit/pack-readme":
                return self._json(200, pack_readme((q.get("id") or [""])[0]))
            if u.path == "/api/doc-for":
                return self._json(200, {"doc": find_doc_for_media((q.get("path") or [""])[0])})
            if u.path == "/api/peaks":
                return self._peaks((q.get("id") or [""])[0])
            if u.path == "/media":
                return self._media((q.get("id") or [""])[0])
        except ApiError as e:
            return self._err(e)
        self._fail(404, "not_found", "そのページ・操作はありません")

    def _peaks(self, tid):
        r = get_peaks(tid)
        if r[0] == "busy":   # 作っている最中・順番待ち(画面は少し待って問い合わせ直す)
            return self._send(202, json.dumps(r[1], ensure_ascii=False).encode("utf-8"), "application/json", {"Retry-After": "1"})
        _, data, rate, dur = r
        return self._send(200, data, "application/octet-stream",
                          {"X-Peaks-Rate": str(rate), "X-Peaks-Duration": "%.3f" % dur, "X-Peaks-Scale": "sqrt", "X-Peaks-Audio": "1" if data else "0"})

    def _media(self, tid):
        d = read_transcript(tid)
        try:
            path = check_source(d.get("sourcePath"))
        except ApiError:
            return self._fail(404, "source_missing", "元の動画・音声が見つかりません(移動・削除した可能性があります)")
        size = os.path.getsize(path)
        ctype = MEDIA_TYPES[os.path.splitext(path)[1].lower()]
        a, b = 0, size - 1
        m = re.match(r"^bytes=(\d*)-(\d*)$", self.headers.get("Range") or "")
        code = 200
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
        self.send_header("Content-Type", ctype)
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Length", str(b - a + 1))
        if code == 206:
            self.send_header("Content-Range", "bytes %d-%d/%d" % (a, b, size))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        if self.command == "HEAD":
            return
        try:
            with open(path, "rb") as f:
                f.seek(a)
                left = b - a + 1
                while left > 0:
                    chunk = f.read(min(65536, left))
                    if not chunk:
                        break
                    self.wfile.write(chunk)
                    left -= len(chunk)
        except (BrokenPipeError, ConnectionError, OSError):
            pass

    def _post(self):
        if not self._guard(True):
            return
        path = self.path.split("?", 1)[0]
        obj = self._read_json()
        if obj is None:
            return
        try:
            if path == "/api/transcribe":
                spec = validate_job(obj)
                return self._json(200, public_job(add_job(spec)))
            if path == "/api/diarize":
                return self._json(200, public_job(add_job(validate_diarize(obj), "diarize")))
            if path == "/api/voices/learn":   # A-3: 名前を付けた話者の声を覚える(ジョブ)
                return self._json(200, public_job(add_job(validate_voice_learn(obj), "voice-learn")))
            if path == "/api/voices/delete":
                delete_voice(str(obj.get("embedding") or DIAR_EMB_DEFAULT), str(obj.get("name") or "")[:60])
                return self._json(200, {"ok": True, "voices": voices_summary()})
            if path == "/api/retranscribe":
                return self._json(200, public_job(add_job(validate_retranscribe(obj), "retranscribe")))
            if path == "/api/redo":
                return self._json(200, public_job(add_job(redo_spec(str(obj.get("tid") or ""), obj), "redo")))
            if path == "/api/scan-folder":
                return self._json(200, scan_folder(obj.get("path"), obj.get("recursive") is True))
            if path == "/api/transcribe-batch":
                return self._json(200, add_batch(obj))
            if path == "/api/settings/patch":   # ほかの画面(ホーム・スタジオのまとめて実行の欄)から、決まった項目だけを直す
                return self._json(200, patch_settings(obj))
            if path == "/api/eval-baseline":
                return self._json(200, record_baseline(obj.get("label")))
            if path == "/api/abtest":
                return self._json(200, public_job(add_job(validate_abtest(obj), "abtest")))
            if path == "/api/archive":
                n = start_archive(obj.get("tid") or None, obj.get("full") is not False)
                return self._json(200, {"ok": True, "docs": n})
            if path == "/api/restore":
                tid = str(obj.get("id", ""))
                doc = restore_history(tid, obj.get("ts"))
                return self._json(200, {"ok": True, "updatedAt": doc["updatedAt"]})
            if path == "/api/suggest/feedback":
                return self._json(200, {"ok": True, "n": record_feedback(obj)})
            if path == "/api/export-corrections":
                tid = obj.get("tid")
                if tid is not None and not TID_RE.match(str(tid)):
                    raise ApiError("bad_request", "文字起こしの指定が正しくありません", 400)
                zp, n, na, skipped = export_corrections(str(tid) if tid else None, obj.get("audio") is not False, "proofed" if obj.get("scope") == "proofed" else "changed")
                try:
                    if n == 0:
                        raise ApiError("empty", "書き出せる修正がありません(修正した行が無いか、修正前の出力が残っていない文字起こしです)", 400)
                    self.send_response(200)
                    self.send_header("Content-Type", "application/zip")
                    self.send_header("Content-Length", str(os.path.getsize(zp)))
                    self.send_header("Content-Disposition", 'attachment; filename="corrections.zip"')
                    self.send_header("X-Clips", "%d,%d,%d" % (n, na, skipped))
                    self.send_header("Access-Control-Expose-Headers", "X-Clips")
                    self.send_header("Cache-Control", "no-store")
                    self.send_header("X-Content-Type-Options", "nosniff")
                    self.end_headers()
                    with open(zp, "rb") as f:
                        while True:
                            chunk = f.read(65536)
                            if not chunk:
                                break
                            self.wfile.write(chunk)
                    return
                except (BrokenPipeError, ConnectionError):
                    return
                finally:
                    try:
                        os.unlink(zp)
                    except OSError:
                        pass
            if path == "/api/resolve-package":
                import resolve_export
                tid = str(obj.get("tid") or "")
                if not TID_RE.match(tid):
                    raise ApiError("bad_request", "文字起こしの指定が正しくありません", 400)
                zp = tmp_dir = None
                try:
                    try:   # 配信者の名前 → 字幕の文字の色(ytt_core/colors.py。docs/archive/followup-2026-09-27.md の 4)
                        from ytt_core import colors as _colors
                        who, hex_ = _colors.resolve(obj.get("streamer") if isinstance(obj.get("streamer"), str) else "")
                    except ValueError as e:
                        raise ApiError("bad_streamer", str(e), 400)
                    tdoc = read_transcript(tid)
                    spk_map = _colors.speaker_colors(s.get("name") for s in tdoc.get("speakers") or [] if isinstance(s, dict))[0]                         if obj.get("speakerColors") is not False else {}   # A-2: 話者の名前ごとの字幕の色(既定はオン)
                    ed, _broken = read_edit(tid)   # 「編集」のカットがあれば、そのとおりに(3 パック のタブのパックと同じ区間)
                    zp, tmp_dir, info = resolve_export.create_package(tdoc, str(obj.get("fps") or "30"),
                                                                      str(obj.get("size") or "") or None, SERVER_VERSION,
                                                                      keeps=edit_keeps_sec(ed) if ed and ed["clips"] else None,
                                                                      row_edge=load_settings().get("rowEdge"), backup=obj.get("backup") is True,
                                                                      wrap=wrap_arg(obj.get("wrap"), obj.get("size")),
                                                                      color={"hex": hex_, "who": who} if hex_ else None,
                                                                      speaker_colors=spk_map)
                    self.send_response(200)
                    self.send_header("Content-Type", "application/zip")
                    self.send_header("Content-Length", str(os.path.getsize(zp)))
                    self.send_header("Content-Disposition", 'attachment; filename="resolve-package.zip"')
                    self.send_header("X-Resolve-Cuts", str(info["cuts"]))
                    self.send_header("X-Resolve-Captions", str(info["captions"]))
                    self.send_header("X-Resolve-Handles", "1" if info["media"]["hasEditHandles"] else "0")
                    self.send_header("Access-Control-Expose-Headers", "X-Resolve-Cuts, X-Resolve-Captions, X-Resolve-Handles")
                    self.send_header("Cache-Control", "no-store")
                    self.send_header("X-Content-Type-Options", "nosniff")
                    self.end_headers()
                    with open(zp, "rb") as f:
                        while True:
                            chunk = f.read(65536)
                            if not chunk:
                                break
                            self.wfile.write(chunk)
                    return
                except resolve_export.ResolveExportError as e:
                    raise ApiError("resolve_export", str(e), 400)
                except (BrokenPipeError, ConnectionError):
                    return
                finally:
                    if tmp_dir:
                        shutil.rmtree(tmp_dir, ignore_errors=True)
            if path == "/api/export-file":
                return self._json(200, export_file(obj))
            if path == "/api/open-video":
                return self._json(200, open_video(obj))
            if path == "/api/relink/check":
                return self._json(200, relink_check(obj))
            if path == "/api/relink":
                return self._json(200, relink_doc(obj))
            if path == "/api/relink/missing":
                return self._json(200, relink_missing())
            if path == "/api/relink/find":
                return self._json(200, relink_find(obj))
            if path == "/api/pick":
                return self._json(200, pick_path(obj))
            if path == "/api/resplit":
                return self._json(200, resplit_doc(obj))
            if path == "/api/edit/pack":
                return self._json(200, record_pack(obj))
            if path == "/api/edit/preview":
                return self._json(200, edit_preview(obj))
            if path == "/api/transcribe/cancel":
                cancel_job(obj.get("id"))
                return self._json(200, {"ok": True})
        except ApiError as e:
            return self._err(e)
        self._fail(404, "not_found", "その操作はありません")

    def _put(self):
        if not self._guard(True):
            return
        u = urllib.parse.urlsplit(self.path)
        obj = self._read_json()
        if obj is None:
            return
        try:
            if u.path == "/api/settings":
                if len(json.dumps(obj)) > 200000:
                    raise ApiError("too_big", "設定が大きすぎます", 413)
                if "patch" in obj:   # 画面が最後に保存した内容との差のキーだけ(監査 11)。窓を2つ開いても別々の設定なら消し合わない
                    return self._json(200, merge_settings(obj))
                with _settings_lock:   # ほかの画面から api/settings/patch で直す項目は、丸ごとの保存ではサーバーの値を残す(古い画面が戻さないように)
                    cur = load_settings()
                    obj = {k: v for k, v in obj.items() if k not in SETTINGS_PATCH_KEYS}
                    obj.update({k: cur[k] for k in SETTINGS_PATCH_KEYS if k in cur})
                    atomic_write(SETTINGS, json.dumps(obj, ensure_ascii=False, indent=1).encode("utf-8"))
                return self._json(200, {"ok": True})
            if u.path == "/api/transcript":
                tid = (urllib.parse.parse_qs(u.query).get("id") or [""])[0]
                doc = save_transcript(tid, obj)
                return self._json(200, {"ok": True, "updatedAt": doc["updatedAt"]})
            if u.path == "/api/edit":
                if len(json.dumps(obj)) > MAX_EDIT_BYTES:
                    raise ApiError("too_big", "区間が多すぎて保存できません", 413)
                return self._json(200, save_edit((urllib.parse.parse_qs(u.query).get("id") or [""])[0], obj))
        except ApiError as e:
            return self._err(e)
        except OSError as e:
            return self._fail(500, "write_failed", "保存できませんでした(%s)。ディスクの空き・フォルダの書き込み権限・他のアプリで開いていないかを確認してください" % (e.strerror or e.__class__.__name__))
        self._fail(404, "not_found", "その操作はありません")

    def _delete(self):
        if not self._guard(True):
            return
        u = urllib.parse.urlsplit(self.path)
        if u.path != "/api/transcript":
            return self._fail(404, "not_found", "その操作はありません")
        tid = (urllib.parse.parse_qs(u.query).get("id") or [""])[0]
        try:
            with _save_lock:   # 話者判別・再認識の書き込みと重ならないように(読み直しのあとに消すと、書き込みで生き返っていた)
                read_transcript(tid)
                os.unlink(tx_path(tid))
                for extra in (edit_path(tid), os.path.join(TX_DIR, tid + ".edit.broken.json"), words_path(tid)):   # 編集の内容(カット)・単語の時刻も一緒に
                    try:
                        os.unlink(extra)
                    except FileNotFoundError:
                        pass
                    except OSError as e:
                        log.warning("編集の内容を消せませんでした: %s %s", os.path.basename(extra), e)
                _edit_cache.pop(tid, None)
        except ApiError as e:
            return self._err(e)
        except OSError as e:
            return self._fail(500, "delete_failed", "削除できませんでした(%s)。他のアプリで開いていないか確認してください" % (e.strerror or e.__class__.__name__))
        self._json(200, {"ok": True})


def probe(port):
    """そのポートで動いている文字起こしツールの版(このツールでなければ None)。問い合わせは ytt_core.runtime.ping(プロキシを通さない)。"""
    r = _runtime.ping(port, 1)
    return r["version"] if r and r["app"] == APP_ID else None


def make_server(start_port):
    global PORT, ALLOWED_HOSTS
    for p in range(start_port, start_port + 20):
        ver = probe(p)
        if ver == SERVER_VERSION:
            return None, p
        if ver is not None:
            print("※ ポート%d では古い版のサーバーが動いています。その黒い画面を閉じておくと迷いません。" % p)
            continue
        try:
            srv = ThreadingHTTPServer(("127.0.0.1", p), Handler)
        except OSError:
            continue
        PORT = p
        ALLOWED_HOSTS = httpsec.allowed_hosts(p)
        return srv, p
    raise SystemExit("空いているポートが見つかりません(%d〜%d)" % (start_port, start_port + 19))


MIN_FREE_BYTES = 2 * 1024 ** 3   # 空きがこれ未満なら、起動時に知らせる(音声の取り出し・保管で数百MB〜数GB使う)
_env_warnings = []


def startup_checks():
    """起動時の環境チェック。問題があれば、黒い画面と serve.log に出す文(と、画面向けに /api/tools の envWarnings)を返す。
    どれも起動は止めない(文字の編集だけなら使えるため)。"""
    out = []
    if sys.version_info < (3, 8):
        out.append("Python %s は古すぎます。Python 3.10〜3.12 を入れ直してください" % sys.version.split()[0])
    if not find_ffmpeg():
        out.append("ffmpeg が見つかりません。文字起こし・話者判別ができません(README の ① の 2)。入れたあとは黒い画面を閉じて起動し直してください")
    try:
        os.makedirs(TX_DIR, exist_ok=True)
        probe_path = os.path.join(TX_DIR, ".write-test")
        atomic_write(probe_path, b"ok")
        os.unlink(probe_path)
    except OSError as e:
        out.append("保存先に書き込めません: %s(%s)。フォルダを書き込みできる場所(デスクトップなど)へ移してください" % (TX_DIR, e.strerror or e.__class__.__name__))
    try:
        free = shutil.disk_usage(ROOT).free
        if free < MIN_FREE_BYTES:
            out.append("ディスクの空きが少なくなっています(残り %.1fGB)。長い動画の文字起こし・保管が途中で失敗することがあります" % (free / 1024 ** 3))
    except OSError:
        pass
    if not os.path.exists(INDEX):
        out.append("index.html が見つかりません。フォルダの中身をまとめて置き直してください")
    try:
        with open(APP_JS, "r", encoding="utf-8") as f:   # 版番号は app.js 側にある(index.html はインラインの <script> を外したため)
            m = re.search(r"APP_VERSION\s*=\s*['\"]([^'\"]+)['\"]", f.read())
        if m and m.group(1) != SERVER_VERSION:
            out.append("画面(app.js v%s)とサーバー(serve.py v%s)の版が違います。フォルダの中身をまとめて更新してください" % (m.group(1), SERVER_VERSION))
    except OSError:
        out.append("app.js が見つかりません。フォルダの中身をまとめて置き直してください")
    except UnicodeError:
        out.append("app.js の文字コードが壊れています。フォルダの中身をまとめて置き直してください")
    if pio(required=False) is None:
        out.append("pipeline_io.py / resolve_export.py が見つかりません。「動画の隣に保存」などの受け渡しの機能が使えません。フォルダの中身をまとめて更新してください")
    return out


_started = []


# 以前の場所(このフォルダ)から新しい置き場へ写す名前。ログ・起動中の印・一時ファイル(transcripts/.tmp も)は写さなくてよいが、
# transcripts はフォルダごと写す(.bak・.hist の控えも含めて)
DATA_ITEMS = ("transcripts", "dataset", "evals", "models", "settings.json", "learn-feedback.json", "eval-baselines.json")
DATA_STATE = None


def set_data_dir(d):
    """作業データの置き場所を切り替える(起動時に1回。ジョブが動く前)。ワーカーにも環境変数で伝える"""
    global DATA_DIR, TX_DIR, TMP_DIR, DATASET_DIR, EVAL_DIR, SETTINGS, FEEDBACK, LOG_FILE, CRASH_FILE, RUN_MARK, WORKER_LOG, DIAR_DIR, EVAL_BASE
    DATA_DIR = os.path.abspath(d)
    TX_DIR = os.path.join(DATA_DIR, "transcripts")
    TMP_DIR = os.path.join(TX_DIR, ".tmp")
    DATASET_DIR = os.path.join(DATA_DIR, "dataset")
    EVAL_DIR = os.path.join(DATA_DIR, "evals")
    SETTINGS = os.path.join(DATA_DIR, "settings.json")
    FEEDBACK = os.path.join(DATA_DIR, "learn-feedback.json")
    LOG_FILE = os.path.join(DATA_DIR, "serve.log")
    CRASH_FILE = os.path.join(DATA_DIR, "serve.crash.log")
    RUN_MARK = os.path.join(DATA_DIR, ".running.json")
    WORKER_LOG = os.path.join(DATA_DIR, "worker.log")
    DIAR_DIR = os.path.join(DATA_DIR, "models", "diar")
    EVAL_BASE = os.path.join(DATA_DIR, "eval-baselines.json")
    os.environ["TRANSCRIBE_DATA_DIR"] = DATA_DIR
    _datadir.register(TOOL_ID, DATA_DIR)   # 同じプロセスの他のツール(入口の案件・txindex)が datadir.resolve で同じ場所を読む(置き場所の規則は ytt_core.datadir の1か所。2026-10-01)


def studio_data_path():
    """切り抜きスタジオの data.json(読むだけ)。置き場所の規則は ytt_core.datadir.resolve の1か所(起動したスタジオが登録した場所 → STUDIO_HOME → 新しい置き場)。
    決めた場所に無く、登録も STUDIO_HOME も無ければ以前の場所(スタジオのフォルダ。移す前のデータ)"""
    if os.environ.get("TRANSCRIBE_STUDIO_DATA"):
        return os.environ["TRANSCRIBE_STUDIO_DATA"]
    legacy = _layout.tool_dir("studio", os.path.dirname(ROOT))
    new = os.path.join(_datadir.resolve("studio", os.path.dirname(ROOT), legacy_dir=legacy), "data.json")
    return new if os.path.isfile(new) or _datadir.registered("studio") or _datadir.override("studio") else os.path.join(legacy, "data.json")


def choose_data_dir():
    """起動時: 環境変数 TRANSCRIBE_DATA_DIR があればそれ。無ければ ytt_core.datadir(以前のデータがあれば新しい置き場へコピー)"""
    global DATA_STATE, STUDIO_DATA
    STUDIO_DATA = studio_data_path()
    if os.environ.get("TRANSCRIBE_DATA_DIR"):
        set_data_dir(os.environ["TRANSCRIBE_DATA_DIR"])
        return
    r = _datadir.prepare(TOOL_ID, ROOT, DATA_ITEMS, log=lambda m: print(m, flush=True))
    DATA_STATE = r
    for w in r["warnings"]:
        print("※ " + w, flush=True)
    set_data_dir(r["dir"])


def prepare(port, base_path="/", hooks=False):
    """待ち受け以外の起動の準備(ログ・前回の異常終了の確認・.runtime・環境チェック・ジョブのスレッド)。
    main() と、入口の統合サーバー(home/mount.py)の両方から呼ぶ。戻り値は .runtime の記録のパス(書けなければ None)。
    シグナルの受け取りは main() だけで行う(統合サーバーでは入口が受け取る)。"""
    global PORT, BASE_PATH, ALLOWED_HOSTS
    PORT, BASE_PATH = port, base_path
    if not ALLOWED_HOSTS:
        ALLOWED_HOSTS = httpsec.allowed_hosts(port)
    choose_data_dir()   # ログより先に(ログも置き場所の中に書く)
    setup_cuda_paths()
    setup_logging(hooks)
    prev = check_previous_run()
    if prev is not None:
        job = prev.get("job") or {}
        msg = "前回は正常に終了しませんでした(落ちた・黒い画面を×で閉じた・強制終了のいずれか)。" + (
            "そのとき実行中だったジョブ: %s %s モデル=%s「%s」" % (job.get("kind", ""), job.get("id", ""), job.get("model", ""), job.get("title", "")) if job else "実行中のジョブはありませんでした")
        print("※", msg)
        print("  詳しくは %s の serve.log・serve.crash.log・worker.log を見てください" % DATA_DIR)
        log.warning("前回の異常終了を検出: %s", msg)
    _run_state["started"] = int(time.time())
    write_mark(None)
    pm = pio(required=False)
    rt = pm.write_runtime(runtime_path_dir(), TOOL_ID, port, SERVER_VERSION, base_path) if pm else None   # 他のツールの「他のツール」メニューがこのポートを知るため
    if rt is None:
        log.warning("実行中のポートの記録(.runtime)を書けませんでした: %s", runtime_path_dir())
    log.info("起動 v%s ポート%d%s メモリ %s python %s", SERVER_VERSION, port, "" if base_path == "/" else " 場所" + base_path, _mem(), sys.version.split()[0])
    _env_warnings[:] = startup_checks()
    for w in _env_warnings:
        print("※", w)
        log.warning("環境: %s", w)
    if "onedrive" in DATA_DIR.lower():   # 同期中のファイルは一瞬開けないことがある(保存は数回やり直すが、念のため知らせる)
        print("※ OneDrive の同期フォルダの中で動いています。保存に失敗することがあれば、同期を一時停止するか、同期しないフォルダへ移してください")
    if not _started:
        _started.append(True)
        threading.Thread(target=worker, daemon=True, name="tx-jobs").start()
    if not has_faster_whisper() and backend_name() != "fake":
        print("※ faster-whisper が入っていません。install.bat(Mac は install.command)を実行してください")
    return rt


def busy():
    """ジョブ(文字起こし・話者判別など)が動いているか・待っているか(入口の「すべて終了」の確認用)"""
    with _jobs_lock:
        return any(j["state"] in ACTIVE_STATES for j in _jobs.values())


def finish():
    """終了の後始末: 動いているジョブを取り消し、認識ワーカーを終わらせ、.runtime の記録と起動中の印を消す。"""
    with _jobs_lock:
        active = [j["id"] for j in _jobs.values() if j["state"] in ACTIVE_STATES]
    for jid in active:
        try:
            cancel_job(jid)
        except ApiError:
            pass
    WORKER.close()
    log.info("終了(正常)")
    pm = pio(required=False)
    if pm:
        pm.remove_runtime(runtime_path_dir(), TOOL_ID, PORT)
    clear_mark()


def mounted_elsewhere():
    """入口(start.bat)の統合サーバーの中で文字起こしツールが動いていれば、その URL。
    同じ transcripts/ を2つのサーバーで書き合わない・認識ワーカーを2つ動かさないよう、serve.py を直接起動したときはそちらを開くだけにする。"""
    info = _runtime.read_runtime(runtime_path_dir(), TOOL_ID)
    if info and info["path"] != "/" and _runtime.ping_app(info["port"], 1, info["path"]) == APP_ID:
        return "http://localhost:%d%s" % (info["port"], info["path"])
    return None


def main():
    live = mounted_elsewhere()
    if live:
        print("入口の中ですでに起動しています。ブラウザで開きます:", live)
        if "--no-open" not in sys.argv:
            webbrowser.open(live)
        return
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    srv, port = make_server(int(args[0]) if args else 8775)
    url = "http://localhost:%d" % port
    if srv is None:
        print("すでに起動しています。ブラウザで開きます:", url)
        if "--no-open" not in sys.argv:
            webbrowser.open(url)
        return
    install_stop_signals()
    prepare(port, "/", hooks=True)
    print("文字起こしツール:", url, "(終了は Ctrl+C またはこの画面を閉じる)")
    print("保存先:", TX_DIR)
    if "--no-open" not in sys.argv:
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        finish()


def install_stop_signals():
    """終了の合図(Linux/Mac の SIGTERM、Windows で黒い画面を×で閉じた・Ctrl+Break の SIGBREAK)でも、Ctrl+C と同じ後始末
    (.runtime の記録と起動中の印を消す)をするよう、KeyboardInterrupt に変える。Windows は×で閉じてから約5秒で強制終了されるが、後始末は一瞬で終わる。"""
    import signal

    def stop(_sig, _frame):
        raise KeyboardInterrupt()
    for name in ("SIGTERM", "SIGBREAK"):
        sig = getattr(signal, name, None)
        if sig is not None:
            try:
                signal.signal(sig, stop)
            except (OSError, ValueError, RuntimeError):
                pass


if __name__ == "__main__":
    main()
