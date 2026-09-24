#!/usr/bin/env python3
"""文字起こしツール用のローカルサーバー(標準ライブラリ + faster-whisper)。

    python3 serve.py [開始ポート] [--no-open]

  GET  /                     index.html
  GET  /api/ping             起動確認
  GET  /api/tools            ffmpeg / faster-whisper / GPU の有無
  GET  /api/settings, PUT    用語集・置換辞書・前回の設定
  GET  /api/marker           隣の clip-marker/data.json のポイント一覧(あれば)
  POST /api/transcribe       文字起こしジョブを追加(順番に1つずつ処理)
  GET  /api/jobs             ジョブの一覧と進捗 / POST /api/transcribe/cancel で中止
  POST /api/diarize          話者の自動判別ジョブを追加(sherpa-onnx。文字起こしと同じ待機列)
  POST /api/retranscribe     選んだ行だけを、別のモデルで再認識するジョブを追加
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
  受け渡し(docs/pipeline.md。本体は pipeline_io.py):
  GET  /api/clip-info?path=  動画(または .clip.json)の隣の youtube-tools-clip/v1 → {"clip", "clipPath", "mediaPath", "warning"}
  GET  /api/transcript-v1?id= youtube-tools-transcript/v1 の JSON
  POST /api/export-file      {"id", "format": transcript-v1|srt|cut-plan-v1} 動画の隣に保存 → {"path", "name", "overwritten", "format", "count"}
  GET  /api/siblings         実行中の他のツールのポート {"tools": {"transcribe": 8775, ...}}

127.0.0.1 にのみバインドし、Host / Origin / Sec-Fetch-Site を検査する(画面 / への遷移だけは、他のツールのリンクから開けるよう別扱い)。
"""
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
import tempfile
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


APP_ID = "transcribe-tool"
SERVER_VERSION = "0.10.0"  # index.html 側の APP_VERSION と揃える
ROOT = os.path.dirname(os.path.abspath(__file__))
INDEX = os.path.join(ROOT, "index.html")
TX_DIR = os.path.join(ROOT, "transcripts")
ROSTER = os.path.join(ROOT, "hololive-roster.json")   # ホロライブの名簿(用語集に足すための一覧)
DATASET_DIR = os.path.join(ROOT, "dataset")   # 校正の成果と音声の保管(将来の学習・声紋登録用)
EVAL_DIR = os.path.join(ROOT, "evals")   # 設定の比較(A/B)の結果
TMP_DIR = os.path.join(TX_DIR, ".tmp")
SETTINGS = os.path.join(ROOT, "settings.json")
FEEDBACK = os.path.join(ROOT, "learn-feedback.json")   # 提案の採用・却下の記録(設定ファイルとは別にして、画面側の保存と競合させない)
MARKER_DATA = os.environ.get("TRANSCRIBE_MARKER_DATA") or os.path.join(os.path.dirname(ROOT), "clip-marker", "data.json")
STUDIO_DATA = os.environ.get("TRANSCRIBE_STUDIO_DATA") or os.path.join(os.path.dirname(ROOT), "clip-studio", "data.json")   # 切り抜きスタジオのマーク(読むだけ)
PORT = 8775
ALLOWED_HOSTS = set()
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


def _reject_json_constant(name):
    raise ValueError("NaN / Infinity は受け付けません: %s" % name)


class ApiError(Exception):
    def __init__(self, code, message, status=400):
        super().__init__(message)
        self.code, self.message, self.status = code, message, status


# ---------- ユーティリティ ----------
def replace_retry(src, dst):
    """os.replace。Windows では、ウイルス対策ソフト・検索インデックスが一瞬ファイルを開いていて PermissionError になることがあるので、
    少し待って数回やり直す(自動保存がたまに「保存できません」になるのを防ぐ)。"""
    for i in range(6):
        try:
            os.replace(src, dst)
            return
        except PermissionError:
            if os.name != "nt" or i == 5:
                raise
            time.sleep(0.05 * (i + 1))


def atomic_write(path, data: bytes):
    """一時ファイルに書き、ディスクへ確実に書き出して(fsync)から置き換える。
    fsync は、停電・強制終了のあとに「中身が空の文字起こし」が残るのを防ぐため(校正の成果を失わないことを優先。1回数ミリ秒)。"""
    d = os.path.dirname(path)
    os.makedirs(d, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=d, prefix=".tmp-", suffix=".part")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        replace_retry(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


# ---------- 記録(落ちたときの手がかり) ----------
# serve.log: 起動・終了・ジョブの開始と終了(使っているメモリつき)・例外。serve.crash.log: Python が捕まえられない異常終了(ネイティブの落ち)のときの手がかり。
# .running.json: 起動中の印(実行中のジョブつき)。正常に終了すれば消える。次の起動で残っていれば「前回は異常終了」と表示する。
LOG_FILE = os.path.join(ROOT, "serve.log")
CRASH_FILE = os.path.join(ROOT, "serve.crash.log")
RUN_MARK = os.path.join(ROOT, ".running.json")
TOOL_ID = "transcribe"   # docs/pipeline.md の 4 のツールID(.runtime/transcribe.json)
_pio_mod = []


def pio(required=True):
    """受け渡しの部品 pipeline_io(docs/pipeline.md。clip/v1・transcript/v1・cut-plan/v1・動画の隣への保存・.runtime)。
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


def setup_logging():
    """ログとクラッシュ記録を有効にする(main から1回だけ)。ファイルが作れなくても動く。"""
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
    env = os.environ.get("TRANSCRIBE_FFMPEG")
    if env and os.path.isfile(env):
        return env
    return shutil.which("ffmpeg")


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
    try:
        import importlib.util
        return importlib.util.find_spec("faster_whisper") is not None
    except Exception:
        return False


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


def gpu_ready():
    return cuda_count() > 0 and cuda_libs_ok()


def backend_name():
    return "fake" if os.environ.get("TRANSCRIBE_BACKEND") == "fake" else "faster-whisper"


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
    sm = {"id": tid, "title": d.get("title", ""), "sourceName": d.get("sourceName", ""), "start": d.get("start", 0),
          "end": d.get("end"), "model": d.get("model", ""), "segments": len(d.get("segments") or []),
          "createdAt": d.get("createdAt", 0), "updatedAt": d.get("updatedAt", 0), "evalSet": d.get("evalSet") is True,
          "hasClip": isinstance(d.get("clip"), dict), "_sourcePath": d.get("sourcePath") or "", "_whole": bool(d.get("whole"))}
    _summary_cache[tid] = (key, sm)
    return sm


def _tids():
    return [n[:-5] for n in (os.listdir(TX_DIR) if os.path.isdir(TX_DIR) else []) if n.endswith(".json") and TID_RE.match(n[:-5])]


def list_transcripts():
    items, seen = [], set()
    for tid in _tids():
        seen.add(tid)
        sm = transcript_summary(tid)
        if sm:
            items.append({k: v for k, v in sm.items() if not k.startswith("_")})
    for k in [k for k in _summary_cache if k not in seen]:   # 消した文書の分は捨てる
        _summary_cache.pop(k, None)
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
            atomic_write(tx_path(tid), json.dumps(old, ensure_ascii=False, indent=1).encode("utf-8"))
        except (OSError, ValueError):
            raise ApiError("broken", "履歴を読み込めません", 500)
        return old


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
    """しばらく使っていないモデルを手放す。ワーカー(ジョブを実行するスレッド)がジョブの合間にだけ呼ぶので、使用中のモデルは消さない。"""
    if MODEL_IDLE_SEC <= 0:
        return False
    now = time.time() if now is None else now
    with _model_lock:
        if not _models or now - _model_used[0] < MODEL_IDLE_SEC:
            return False
        log.info("しばらく使っていないモデルを解放: %s(メモリ %s)", ", ".join("%s/%s" % k for k in _models), _mem())
        _models.clear()
    gc.collect()
    return True


class Cancelled(Exception):
    pass


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
    return {"sourcePath": src, "sourceName": os.path.basename(src), "start": round(start, 2), "end": round(end, 2) if end else None,
            "duration": dur, "whole": whole, "model": model, "language": lang, "beam": 1 if req.get("quality") == "fast" else 5,
            "device": req.get("device") if req.get("device") in ("cuda", "cpu") else "auto",
            "vadMode": req.get("vadMode") if req.get("vadMode") in ("weak", "normal", "off") else ("off" if req.get("vad") is False else "weak"),
            "boost": req.get("boost") is True, "autoDict": req.get("autoDict") is not False, "wordSplit": req.get("wordSplit") is not False,
            "stripPunct": req.get("stripPunct") is not False, "glossary": glossary + gauto, "glossAuto": gauto,
            "autoLearned": req.get("autoLearned") is True, "clip": clip, "warnings": warnings,
            "title": str(req.get("title") or "")[:120] or os.path.splitext(os.path.basename(src))[0][:120]}


ACTIVE_STATES = ("queued", "loading", "extracting", "running")
EXCLUSIVE = {"diarize": ("diarize", "retranscribe"), "retranscribe": ("diarize", "retranscribe"), "abtest": ("abtest",)}   # 同じ文字起こしに同時に入れない組み合わせ


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
        job = {"id": jid, "title": spec["title"], "state": "queued", "phase": "順番待ち", "progress": 0.0, "tid": spec["tid"] if kind in ("diarize", "retranscribe") else None, "error": None,
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


def make_flags(seg, prev_texts, lang=None, terms=()):
    """Whisper は BGM・無音・歌で幻覚(でたらめな文)を出しやすいので、要確認の印を付ける。
    lang が "ja" のときは、英字が目立つ行も対象にする(terms=用語集。その中の英字の語は数えない)。"""
    why = []
    lp, ns, cr = seg.get("avg_logprob"), seg.get("no_speech_prob"), seg.get("compression_ratio")
    if lp is not None and lp < -1.0:
        why.append("自信が低い")
    if ns is not None and ns > 0.6:
        why.append("音声でない可能性(BGMなど)")
    if cr is not None and cr > 2.4:
        why.append("繰り返しの可能性")
    text = seg["text"]
    if any(h in text for h in HALLUC) and seg["end"] - seg["start"] < 8:
        why.append("よくある誤認識の文")
    if text and prev_texts[-2:] == [text, text]:
        why.append("同じ文の繰り返し")
    if lang == "ja" and latin_suspect(text, terms):
        why.append("英字が多い(英語の幻覚の可能性)")
    return "、".join(why)


def load_model(name, job, pref="auto", force_cpu=False):
    """(モデル, 使用デバイス) を返す。同じ設定のモデルは使い回す。
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
                m = WhisperModel(name, device=dev, compute_type="float16" if dev == "cuda" else "int8")
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
    if spec["glossary"]:
        kw["initial_prompt"] = "用語: " + "、".join(spec["glossary"])[:150]
        kw["hotwords"] = ", ".join(spec["glossary"])[:300]
    return kw


def filter_kwargs(model, kw):
    """使っている faster-whisper が対応していない引数は渡さない(古い版でも動くように)。"""
    try:
        import inspect
        accepted = set(inspect.signature(model.transcribe).parameters)
        return {k: v for k, v in kw.items() if k in accepted}
    except (TypeError, ValueError):
        return kw


def transcribe_real(job, spec, wav, total):
    model, device = load_model(spec["model"], job, spec.get("device", "auto"))
    job["device"] = device
    if job["cancel"]:
        raise Cancelled()
    job["phase"], job["state"] = "文字起こし中", "running"
    kw = filter_kwargs(model, whisper_kwargs(spec))

    def run(m):
        segs, _info = m.transcribe(wav, **kw)
        for s in segs:
            if job["cancel"]:
                raise Cancelled()
            words = [(float(w.start), float(w.end), str(w.word)) for w in (getattr(s, "words", None) or []) if getattr(w, "start", None) is not None and getattr(w, "end", None) is not None]
            yield {"start": float(s.start), "end": float(s.end), "text": (s.text or "").strip(), "avg_logprob": getattr(s, "avg_logprob", None),
                   "no_speech_prob": getattr(s, "no_speech_prob", None), "compression_ratio": getattr(s, "compression_ratio", None), "words": words}
            job["progress"] = min(0.99, float(s.end) / total) if total else 0.0

    started = False
    try:
        for x in run(model):
            started = True
            yield x
    except (Cancelled, ApiError):
        raise
    except Exception:
        if device == "cuda" and not started and spec.get("device") == "cuda":
            raise ApiError("gpu_failed", "GPU での処理に失敗しました。GPU 用ライブラリが未導入の可能性があります(install-gpu.bat を実行するか、処理方式を「自動」か「CPU」にしてください)", 500)
        if device != "cuda" or started:
            raise
        # 自動のとき、GPU で実行時に失敗(CUDA ライブラリ不足など)したら CPU でやり直す
        job["phase"], job["device"] = "GPU が使えないため CPU で処理します", "cpu"
        model, _ = load_model(spec["model"], job, force_cpu=True)
        for x in run(model):
            yield x


SPLIT_GAP, SPLIT_SEC, SPLIT_CHARS = 1.0, 8.0, 40   # 単語の間がこの秒数以上あいたら行を分ける / 1行の最大の長さ(秒・文字)
STRIP_PUNCT_CHARS = "、。？！?!"   # ショート動画のテロップでは句読点が浮きやすいので、既定で取り除く対象(全角の読点・句点・疑問符・感嘆符と、その半角形)
_strip_punct_re = re.compile("[%s]" % re.escape(STRIP_PUNCT_CHARS))


def strip_punct(text):
    """テロップ表示用に、句読点(、。？！ と半角の ?!)を取り除く。"""
    return _strip_punct_re.sub("", text)


def _cut_words(ws):
    """単語の並び ws=[(開始,終了,文字)] を、長すぎる間は「間が大きい・句読点のあと・真ん中に近い」所で分けていく。"""
    dur = ws[-1][1] - ws[0][0]
    chars = sum(len(t.strip()) for _a, _b, t in ws)
    if len(ws) < 2 or (dur <= SPLIT_SEC and chars <= SPLIT_CHARS):
        return [ws]
    best, bi = None, 1
    for i in range(1, len(ws)):
        gap = max(0.0, ws[i][0] - ws[i - 1][1])
        tail = ws[i - 1][2].rstrip()[-1:]
        punct = 1.0 if tail in "。！？!?" else (0.4 if tail in "、,，" else 0.0)
        balance = 1.0 - abs((ws[i - 1][1] - ws[0][0]) / dur - 0.5) if dur > 0 else 0.5
        score = gap * 2 + punct + balance * 0.5
        if best is None or score > best:
            best, bi = score, i
    return _cut_words(ws[:bi]) + _cut_words(ws[bi:])


def split_segment(s):
    """認識した1行 s を、単語の時刻で整える。①行の始まり・終わりを最初・最後の単語にそろえる(声のない所まで伸びた行を直す)
    ②単語の間が1秒以上あいた所で分ける ③長すぎる行(8秒・40文字超)は区切りのよい所で分ける。
    単語の並びが行の文章と合わないとき、単語の時刻が無いときは、何もせずそのまま返す。"""
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
    parts = [p for g in groups for p in _cut_words(g)]
    out = []
    for p in parts:
        text = "".join(t for _a, _b, t in p).strip()
        if text:
            out.append({**{k: v for k, v in s.items() if k != "words"}, "start": p[0][0], "end": max(p[-1][1], p[0][0]), "text": text})
    return out or [s]


def expand_segments(gen, spec):
    """認識の出力を、split_segment で整えながら流す(wordSplit が無効なら、そのまま)。
    句読点の除去(stripPunct、既定オン)は、単語分割が句読点を判断材料に使い終えたあとの、最後の1回だけにかける
    (分割の精度には影響させず、かつ text と original の両方に必ず同じ結果が入るよう、ここ1か所にまとめる)。"""
    strip = spec.get("stripPunct", True)
    for s in gen:
        for p in (split_segment(s) if spec.get("wordSplit") else [s]):
            yield {**p, "text": strip_punct(p["text"])} if strip and p.get("text") else p


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
    if job.get("kind") == "retranscribe":
        return run_retranscribe(job)
    if job.get("kind") == "abtest":
        return run_abtest(job)
    spec = job["spec"]
    wav = os.path.join(TMP_DIR, job["id"] + ".wav")
    try:
        os.makedirs(TMP_DIR, exist_ok=True)
        job["state"], job["phase"] = "extracting", "音声を取り出し中"
        extract_audio(job, spec, wav)
        total = media_duration(wav) or (spec["end"] - spec["start"] if spec["end"] else 0)
        if backend_name() == "fake":
            gen = transcribe_fake(job, spec, wav, total)
        else:
            if not has_faster_whisper():
                raise ApiError("no_whisper", "faster-whisper が入っていません(README の準備手順を確認してください)", 400)
            job["state"] = "loading"
            gen = transcribe_real(job, spec, wav, total)
        segs, prev, original, pairs, dict_n = [], [], [], (parse_replacements(load_settings().get("replacements")) if spec.get("autoDict") else []), 0
        learn_n = 0
        lrules, lfb = (learn_rules(), load_feedback()) if spec.get("autoLearned") else ({}, None)
        for s in expand_segments(gen, spec):
            if not s["text"]:
                continue
            seg = {"id": "s%d" % (len(segs) + 1), "start": round(s["start"] + spec["start"], 2), "end": round(s["end"] + spec["start"], 2),
                   "text": s["text"][:MAX_TEXT], "speaker": "", "flag": ""}
            seg["flag"] = make_flags({**s, "text": seg["text"], "start": seg["start"], "end": seg["end"]}, prev, spec["language"], spec["glossary"])
            prev.append(seg["text"])
            if lrules:   # 確度が高い学習済みの置換は、機械の出力側にも反映する(そうしないと自分の置換を「人が直した」と数えて自己強化してしまう)
                seg["text"], ln = auto_learned_replace(seg["text"], lrules, lfb)
                learn_n += ln
            original.append({"start": seg["start"], "end": seg["end"], "text": seg["text"]})   # 機械の出力をそのまま残す(修正からの学習に使う)
            seg["text"], n = apply_replacements(seg["text"], pairs)
            dict_n += n
            segs.append(seg)
            job["segments"] = len(segs)
        if job["cancel"]:
            raise Cancelled()
        tid = uuid.uuid4().hex[:12]
        now = int(time.time() * 1000)
        doc = {"schema": "transcribe/v1", "id": tid, "title": spec["title"], "sourcePath": spec["sourcePath"], "sourceName": spec["sourceName"],
               "start": spec["start"], "end": spec["end"], "whole": spec["whole"], "duration": spec["duration"], "model": spec["model"],
               "language": spec["language"], "params": {"beam": spec["beam"], "vadMode": spec["vadMode"], "boost": spec["boost"], "device": job.get("device", ""), "glossary": spec["glossary"][:50],
                          "autoDict": bool(spec.get("autoDict")), "dictApplied": dict_n, "wordSplit": bool(spec.get("wordSplit")),
                          "autoLearned": bool(spec.get("autoLearned")), "learnApplied": learn_n, "glossAuto": spec.get("glossAuto", [])[:20]},
               "speakers": [], "segments": segs, "original": original, "createdAt": now, "updatedAt": now}
        if spec.get("clip"):
            doc["clip"] = spec["clip"]   # youtube-tools-clip/v1 の中身そのもの(transcript/v1 にもそのまま入る)
        atomic_write(tx_path(tid), json.dumps(doc, ensure_ascii=False, indent=1).encode("utf-8"))
        job["tid"], job["progress"], job["state"], job["phase"] = tid, 1.0, "done", "完了"
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
DIAR_DIR = os.path.join(ROOT, "models", "diar")
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
    try:
        import importlib.util
        return importlib.util.find_spec("sherpa_onnx") is not None and importlib.util.find_spec("numpy") is not None
    except Exception:
        return False


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


def read_wav_f32(path):
    import numpy as np
    with wave.open(path, "rb") as w:
        if w.getnchannels() != 1 or w.getsampwidth() != 2 or w.getframerate() != 16000:
            raise ApiError("diar_failed", "音声の形式が想定と違います", 500)
        raw = w.readframes(w.getnframes())
    return np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0


def diarize_real(job, wav, num, emb=DIAR_EMB_DEFAULT):
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
    return {"tid": tid, "numSpeakers": n if 2 <= n <= 10 else 0, "embedding": emb if emb in DIAR_EMBS else DIAR_EMB_DEFAULT, "title": "話者判別: " + (str(doc.get("title") or "") or "無題")[:100]}


def run_diarize(job):
    spec = job["spec"]
    wav = os.path.join(TMP_DIR, job["id"] + ".wav")
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


# ---------- 置換辞書・修正からの学習 ----------
def load_settings():
    try:
        with open(SETTINGS, "r", encoding="utf-8-sig") as f:   # メモ帳の「UTF-8 (BOM 付き)」で直されても読めるように
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


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
EVAL_BASE = os.path.join(ROOT, "eval-baselines.json")
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
    check_source(doc.get("sourcePath"))
    valid = {g["id"] for g in (doc.get("segments") or [])}
    ids = [i for i in dict.fromkeys(str(x)[:16] for x in (req.get("ids") or [])[:5000] if isinstance(x, (str, int))) if i in valid][:2000]
    if not ids:
        raise ApiError("empty", "再認識する行がありません", 400)
    model = str(req.get("model") or "large-v3").strip()
    if not valid_model(model):
        raise ApiError("bad_model", "モデル名が正しくありません", 400)
    lang = str(req.get("language") or doc.get("language") or "ja")
    glossary = [t.strip() for t in re.split(r"[\r\n,、]+", str(req.get("glossary") or "")) if t.strip()][:200]
    gauto = auto_glossary(glossary) if req.get("autoGloss") is not False else []
    with _jobs_lock:
        if any(j.get("kind") in ("diarize", "retranscribe") and j["spec"].get("tid") == tid and j["state"] in ("queued", "loading", "extracting", "running") for j in _jobs.values()):
            raise ApiError("busy", "この文字起こしは、すでに別の処理(話者判別・再認識)の最中です", 409)
    mode = "range" if req.get("mode") == "range" else "each"
    rng = None
    if mode == "range":   # 選んだ行の最初〜最後を、ひとまとまりの音声として認識し直す(間にある選んでいない行も含む)
        segs = sorted((g for g in doc.get("segments") or []), key=lambda g: g["start"])
        chosen = [g for g in segs if g["id"] in set(ids)]
        a, b = min(g["start"] for g in chosen), max(g["end"] for g in chosen)
        ids = [g["id"] for g in segs if a - 1e-6 <= (g["start"] + g["end"]) / 2 <= b + 1e-6]
        if b - a > MAX_RANGE_SEC:
            raise ApiError("too_long", "範囲が長すぎます(最大%d分)。範囲を狭めてください" % (MAX_RANGE_SEC // 60), 400)
        rng = [a, b]
    return {"tid": tid, "ids": ids, "mode": mode, "range": rng, "model": model, "language": lang if lang in LANGS else "ja", "beam": 5,
            "vadMode": req.get("vadMode") if mode == "range" and req.get("vadMode") in ("weak", "normal", "off") else "off",
            "wordSplit": mode == "range" and req.get("wordSplit") is not False,
            "stripPunct": req.get("stripPunct") is not False,
            "device": req.get("device") if req.get("device") in ("cuda", "cpu") else "auto", "boost": req.get("boost") is True,
            "autoDict": req.get("autoDict") is not False, "glossary": glossary + gauto, "glossAuto": gauto,
            "title": ("範囲を再認識: " if mode == "range" else "再認識: ") + (str(doc.get("title") or "") or "無題")[:100]}


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
    atomic_write(tx_path(spec["tid"]), json.dumps(doc, ensure_ascii=False, indent=1).encode("utf-8"))
    return done, unsure


def replace_original_multi(orig, a, b, items):
    keep = [o for o in orig if not (a <= (o["start"] + o["end"]) / 2 <= b)]
    keep += [{"start": x["start"], "end": x["end"], "text": x["raw"][:MAX_TEXT]} for x in items]
    keep.sort(key=lambda o: o["start"])
    return keep


def apply_range(spec, lines):
    """範囲内の行を、新しく認識した行に丸ごと差し替える。話者は、時間が最も重なっていた元の行から引き継ぐ。
    lines=[{start,end,raw,flag}]。校正済み・音の状態のメモは引き継がない(別の文字になっているため)。"""
    with _save_lock:   # 保存と同じロック(apply_diarization と同じ理由)
        return _apply_range(spec, lines)


def _apply_range(spec, lines):
    a, b = spec["range"]
    doc = read_transcript(spec["tid"])
    pairs = parse_replacements(load_settings().get("replacements")) if spec.get("autoDict") else []
    ids = set(spec["ids"])
    old = [g for g in doc.get("segments") or [] if g["id"] in ids]
    rest = [g for g in doc.get("segments") or [] if g["id"] not in ids]
    used = {g["id"] for g in rest}
    new, unsure, n = [], 0, 0
    for x in lines:
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
    if isinstance(doc.get("original"), list):
        doc["original"] = replace_original_multi(doc["original"], a, b, lines)
    bak = os.path.join(TX_DIR, ".bak")
    os.makedirs(bak, exist_ok=True)
    shutil.copy2(tx_path(spec["tid"]), os.path.join(bak, spec["tid"] + ".pre-retranscribe.json"))
    try:
        hist_snapshot(spec["tid"], force=True)
    except OSError:
        pass
    doc["retranscribed"] = {"model": spec["model"], "lines": len(new), "range": [a, b], "at": int(time.time() * 1000)}
    doc["updatedAt"] = int(time.time() * 1000)
    atomic_write(tx_path(spec["tid"]), json.dumps(doc, ensure_ascii=False, indent=1).encode("utf-8"))
    return len(new), unsure


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
        words = [(float(w.start), float(w.end), str(w.word)) for w in (getattr(s, "words", None) or []) if getattr(w, "start", None) is not None and getattr(w, "end", None) is not None]
        raw.append({"start": float(s.start), "end": float(s.end), "text": (s.text or "").strip(), "avg_logprob": getattr(s, "avg_logprob", None),
                    "no_speech_prob": getattr(s, "no_speech_prob", None), "compression_ratio": getattr(s, "compression_ratio", None), "words": words})
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
        flag = make_flags({**s, "start": st, "end": en}, prev, spec["language"], spec["glossary"])
        prev.append(s["text"])
        out.append({"start": st, "end": en, "raw": s["text"], "flag": flag})
    return out


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
        if not targets:
            raise ApiError("empty", "再認識する行が見つかりません(先に削除された可能性があります)", 400)
        span_src = targets + ([{"start": spec["range"][0], "end": spec["range"][1]}] if spec.get("mode") == "range" else [])
        start, end = audio_span(span_src, start, end)   # 以下の start は「取り出した音声の先頭が、元の動画の何秒か」
        job["state"], job["phase"] = "extracting", "音声を取り出し中"
        extract_audio(job, {"sourcePath": src, "start": start, "end": end, "boost": spec["boost"]}, wav)
        results = {}
        if spec.get("mode") == "range":
            a, b = spec["range"]
            if backend_name() == "fake":
                job["state"], job["phase"], job["device"] = "running", "範囲を認識中", "cpu"
                lines, t0, k = [], a, 0
                while t0 < b - 0.05:
                    if job["cancel"]:
                        raise Cancelled()
                    k += 1
                    e = min(b, t0 + 3.0)
                    lines.append({"start": t0, "end": e, "raw": "範囲再認識%d" % k, "flag": "自信が低い" if k % 2 == 0 else ""})
                    t0 = e
                    job["progress"] = min(0.95, (t0 - a) / max(1e-6, b - a))
                    time.sleep(float(os.environ.get("TRANSCRIBE_FAKE_DELAY", "0.05")))
            else:
                if not has_faster_whisper():
                    raise ApiError("no_whisper", "faster-whisper が入っていません(README の準備手順を確認してください)", 400)
                job["state"] = "loading"
                model, device = load_model(spec["model"], job, spec["device"])
                job["device"] = device
                audio = read_wav_f32(wav)
                job["state"], job["phase"] = "running", "範囲を認識中"
                kw = filter_kwargs(model, whisper_kwargs(spec))
                try:
                    lines = range_lines_real(job, model, kw, audio, spec, start)
                except (Cancelled, ApiError):
                    raise
                except Exception:
                    if device == "cuda" and spec["device"] == "auto":
                        job["phase"], job["device"] = "GPU が使えないため CPU で処理します", "cpu"
                        model, device = load_model(spec["model"], job, force_cpu=True)
                        kw = filter_kwargs(model, whisper_kwargs(spec))
                        lines = range_lines_real(job, model, kw, audio, spec, start)
                    elif device == "cuda" and spec["device"] == "cuda":
                        raise ApiError("gpu_failed", "GPU での処理に失敗しました。処理方式を「自動」か「CPU」にしてください", 500)
                    else:
                        raise
            if job["cancel"]:
                raise Cancelled()
            if not lines:
                raise ApiError("no_speech", "この範囲からは、文字が認識されませんでした(元の行はそのままです)", 400)
            job["segments"], job["unsure"] = apply_range(spec, lines)
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
                    r = recognize_chunk(model, kw, chunk, t, sep, spec["glossary"])
                except Exception:
                    if n == 0 and device == "cuda" and spec["device"] == "auto":   # 自動のとき、GPU が実行時に失敗したら CPU でやり直す
                        job["phase"], job["device"] = "GPU が使えないため CPU で処理します", "cpu"
                        model, device = load_model(spec["model"], job, force_cpu=True)
                        kw = filter_kwargs(model, whisper_kwargs(spec))
                        r = recognize_chunk(model, kw, chunk, t, sep, spec["glossary"])
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
    for it in list_transcripts():
        sm = transcript_summary(it["id"])   # list_transcripts で読んだばかりなので、ここはキャッシュから(以前は全文書を2回ずつ読んでいた)
        sp = sm and sm["_sourcePath"]
        if not sp:
            continue
        a, b = num(sm.get("start"), 0.0) or 0.0, num(sm.get("end"))
        out.append({"path": os.path.normcase(os.path.abspath(sp)), "start": a, "end": b, "whole": sm["_whole"], "tid": it["id"]})
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
            dirs[:] = sorted(d for d in dirs if not d.startswith(".")) if recursive and depth < 3 else []
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


# ---------- 受け渡しの API(docs/pipeline.md の 2・4・6) ----------
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
        data = text.encode("utf-8")   # BOM なし(docs/pipeline.md の 1)
    try:
        path, overwritten = pm.save_beside(src, suffix, data, schema)
    except pm.PipelineError as e:
        raise _pipeline_error(e)
    log.info("動画の隣に保存: %s %s(%s)", fmt, os.path.basename(path), "上書き" if overwritten else "新規")
    return {"path": path, "name": os.path.basename(path), "overwritten": overwritten, "format": fmt, "count": count}


def runtime_path_dir():
    """<transcribe-tool の1つ上>/.runtime(環境変数 YTT_RUNTIME_DIR が優先)。pipeline_io.runtime_dir と同じ規則。"""
    return os.environ.get("YTT_RUNTIME_DIR") or os.path.join(os.path.dirname(ROOT), ".runtime")


# ---------- HTTP ----------
QUIET_PATHS = ("/api/jobs", "/media", "/api/siblings", "/api/progress", "/api/clip-info")   # 画面が頻繁に呼ぶ・パスを含むので、黒い画面に出さない
PAGE_HEADERS = {"X-Frame-Options": "DENY", "Content-Security-Policy": "frame-ancestors 'none'", "Referrer-Policy": "same-origin"}


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

    def _host_ok(self):
        return (self.headers.get("Host") or "") in ALLOWED_HOSTS

    def _origin_ok(self):
        # 「http://」+ 許可したホスト と完全に一致するものだけ(以前は "http://" を消してから比べていたので、形の崩れた値も通った)
        o = self.headers.get("Origin")
        return o is None or o in {"http://" + h for h in ALLOWED_HOSTS}

    def _fetch_site_ok(self):
        return self.headers.get("Sec-Fetch-Site") in (None, "same-origin", "none")

    def _navigation_ok(self, path):
        """他のツールの画面のリンク(http://localhost:8800 → http://localhost:8775/?media=...)で、この画面を開くのは許す。
        ポートが違うだけでも Sec-Fetch-Site は same-site(127.0.0.1 と localhost なら cross-site)になるため、以前は 403 になっていた。
        画面(index.html)を新しいタブで開くだけで、URL で重い処理は始まらない(docs/pipeline.md の 3)。API は従来どおり同じ画面からだけ。
        埋め込み(iframe)での悪用は X-Frame-Options / frame-ancestors で防ぐ。"""
        return (path in ("/", "/index.html") and self.headers.get("Sec-Fetch-Mode") == "navigate"
                and self.headers.get("Sec-Fetch-Dest", "document") == "document")

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
        self._json(e.status, {"error": e.code, "message": e.message})

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
            self._fail(403, "forbidden", "このツールは http://localhost:%d から開いてください(Host が違います)" % PORT)
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
            if u.path == "/api/ping":
                return self._json(200, {"app": APP_ID, "version": SERVER_VERSION})
            if u.path == "/api/siblings":
                return self._json(200, pio().siblings(runtime_path_dir(), TOOL_ID, PORT))
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
            if u.path == "/media":
                return self._media((q.get("id") or [""])[0])
        except ApiError as e:
            return self._err(e)
        self._fail(404, "not_found", "そのページ・操作はありません")

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
            if path == "/api/retranscribe":
                return self._json(200, public_job(add_job(validate_retranscribe(obj), "retranscribe")))
            if path == "/api/scan-folder":
                return self._json(200, scan_folder(obj.get("path"), obj.get("recursive") is True))
            if path == "/api/transcribe-batch":
                return self._json(200, add_batch(obj))
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
                    zp, tmp_dir, plan = resolve_export.create_package(read_transcript(tid), str(obj.get("fps") or "30"))
                    self.send_response(200)
                    self.send_header("Content-Type", "application/zip")
                    self.send_header("Content-Length", str(os.path.getsize(zp)))
                    self.send_header("Content-Disposition", 'attachment; filename="resolve-package.zip"')
                    self.send_header("X-Resolve-Cuts", str(len(plan["cuts"])))
                    self.send_header("X-Resolve-Captions", str(len(plan["captions"])))
                    self.send_header("X-Resolve-Handles", "1" if plan["media"]["hasEditHandles"] else "0")
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
                atomic_write(SETTINGS, json.dumps(obj, ensure_ascii=False, indent=1).encode("utf-8"))
                return self._json(200, {"ok": True})
            if u.path == "/api/transcript":
                tid = (urllib.parse.parse_qs(u.query).get("id") or [""])[0]
                doc = save_transcript(tid, obj)
                return self._json(200, {"ok": True, "updatedAt": doc["updatedAt"]})
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
        except ApiError as e:
            return self._err(e)
        except OSError as e:
            return self._fail(500, "delete_failed", "削除できませんでした(%s)。他のアプリで開いていないか確認してください" % (e.strerror or e.__class__.__name__))
        self._json(200, {"ok": True})


_local_opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))   # 127.0.0.1 への問い合わせを、環境変数 HTTP_PROXY などのプロキシに回さない


def probe(port):
    try:
        with _local_opener.open("http://127.0.0.1:%d/api/ping" % port, timeout=1) as r:
            j = json.load(r)
            return str(j.get("version", "")) if j.get("app") == APP_ID else None
    except Exception:
        return None


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
        ALLOWED_HOSTS = {"localhost:%d" % p, "127.0.0.1:%d" % p}
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
    try:
        with open(INDEX, "r", encoding="utf-8") as f:
            m = re.search(r"APP_VERSION\s*=\s*['\"]([^'\"]+)['\"]", f.read())
        if m and m.group(1) != SERVER_VERSION:
            out.append("画面(index.html v%s)とサーバー(serve.py v%s)の版が違います。フォルダの中身をまとめて更新してください" % (m.group(1), SERVER_VERSION))
    except OSError:
        out.append("index.html が見つかりません。フォルダの中身をまとめて置き直してください")
    except UnicodeError:
        out.append("index.html の文字コードが壊れています。フォルダの中身をまとめて置き直してください")
    if pio(required=False) is None:
        out.append("pipeline_io.py / resolve_export.py が見つかりません。「動画の隣に保存」などの受け渡しの機能が使えません。フォルダの中身をまとめて更新してください")
    return out


def main():
    setup_cuda_paths()
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    srv, port = make_server(int(args[0]) if args else 8775)
    url = "http://localhost:%d" % port
    if srv is None:
        print("すでに起動しています。ブラウザで開きます:", url)
        if "--no-open" not in sys.argv:
            webbrowser.open(url)
        return
    setup_logging()
    prev = check_previous_run()
    if prev is not None:
        job = prev.get("job") or {}
        msg = "前回は正常に終了しませんでした(落ちた・黒い画面を×で閉じた・強制終了のいずれか)。" + (
            "そのとき実行中だったジョブ: %s %s モデル=%s「%s」" % (job.get("kind", ""), job.get("id", ""), job.get("model", ""), job.get("title", "")) if job else "実行中のジョブはありませんでした")
        print("※", msg)
        print("  詳しくは serve.log と serve.crash.log を見てください")
        log.warning("前回の異常終了を検出: %s", msg)
    _run_state["started"] = int(time.time())
    write_mark(None)
    pm = pio(required=False)
    rt = pm.write_runtime(runtime_path_dir(), TOOL_ID, port, SERVER_VERSION) if pm else None   # 他のツールの「他のツール」メニューがこのポートを知るため
    if rt is None:
        log.warning("実行中のポートの記録(.runtime)を書けませんでした: %s", runtime_path_dir())
    install_stop_signals()
    log.info("起動 v%s ポート%d メモリ %s python %s", SERVER_VERSION, port, _mem(), sys.version.split()[0])
    _env_warnings[:] = startup_checks()
    for w in _env_warnings:
        print("※", w)
        log.warning("環境: %s", w)
    if "onedrive" in ROOT.lower():   # 同期中のファイルは一瞬開けないことがある(保存は数回やり直すが、念のため知らせる)
        print("※ OneDrive の同期フォルダの中で動いています。保存に失敗することがあれば、同期を一時停止するか、同期しないフォルダへ移してください")
    threading.Thread(target=worker, daemon=True).start()
    print("文字起こしツール:", url, "(終了は Ctrl+C またはこの画面を閉じる)")
    print("保存先:", TX_DIR)
    if not has_faster_whisper() and backend_name() != "fake":
        print("※ faster-whisper が入っていません。install.bat(Mac は install.command)を実行してください")
    if "--no-open" not in sys.argv:
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        log.info("終了(正常)")
        if pm:
            pm.remove_runtime(runtime_path_dir(), TOOL_ID, port)
        clear_mark()


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
