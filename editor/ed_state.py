# -*- coding: utf-8 -*-
"""「編集」のサーバーの部品: 置き場所・設定の値・共通の小道具・記録(落ちたときの手がかり)・作業データの切り替え(段10 で editor/serve.py から分けた。docs/plan/phase10-code-split.md)。

名前は serve.py からも見える(serve.py が受け付けて、この部品へ転送する。テストの S.名前 = … もここに入る)。
ほかの部品の名前は `ed_xxx.名前` の形で呼ぶたびに読む(差し替えが効くように。from … import はしない)。
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

from ytt_core import datadir as _datadir, fsio as _fsio, httpsec, layout as _layout, jobs as _heavy, runtime as _runtime, schemas as _yschemas, tools as _tools  # noqa: E402,F401
import roster as _roster  # noqa: E402,F401


APP_ID = "transcribe-tool"
SERVER_VERSION = None   # serve.py が読み込みのときに入れる(版の正は serve.py の SERVER_VERSION。入口がその行を読むため)
ROOT = os.path.dirname(os.path.abspath(__file__))
INDEX = os.path.join(ROOT, "index.html")
APP_JS = os.path.join(ROOT, "app.js")      # 画面の JS(CSP で index.html からインラインの <script> を外したため、静的配信する)
UI_KIT_JS = os.path.join(ROOT, "ui-kit.js")  # ui-kit/ui-kit.js の写し(dev/sync_ui_kit.py。同上)
PAGE_JS = ("cut.js", "pack-tab.js", "app-core.js", "app-jobs.js", "app-list.js", "app-learn.js", "app-rows.js", "app-tools.js")          # 「編集」のタブの JS(docs/design/edit-tool-design.md の 7。app.js より先に読む。無いものは 404)
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
                                timeout=60, creationflags=ed_jobs._worker_flags()).returncode == 0
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
    if ed_jobs.IN_WORKER:
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
        p = subprocess.run([worker_python(), ed_jobs.WORKER_SCRIPT, "--probe"], stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                           timeout=120, env=ed_jobs.worker_env(), cwd=ROOT, creationflags=ed_jobs._worker_flags())
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


MIXED_FLAG = "声が混ざっている可能性"
WEAK_FLAG = "話者が不確か"
NONE_FLAG = "話者を判別できなかった"


# ほかの部品(呼ぶたびに読む。ここで読むのは、上の値を全部作ってからにするため)
import ed_jobs  # noqa: E402,F401
