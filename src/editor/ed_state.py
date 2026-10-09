# -*- coding: utf-8 -*-
"""「編集」のサーバーの部品: 置き場所・設定の値・共通の小道具・記録(落ちたときの手がかり)・作業データの切り替え(段10 で editor/serve.py から分けた。git の履歴(679ff01 以前)の docs/plan/phase10-code-split.md)。

名前は serve.py からも見える(serve.py が受け付けて、この部品へ転送する。テストの S.名前 = … もここに入る)。
ほかの部品の名前は `ed_xxx.名前` の形で呼ぶたびに読む(差し替えが効くように。from … import はしない)。
"""
import faulthandler
import json
import logging
import logging.handlers
import os
import re
import shutil
import subprocess
import sys
import threading
import time

from ytt import errors as _errors, fsio as _fsio, runtime as _runtime, schemas as _yschemas, tools as _tools, workdata as _workdata  # noqa: E402
from pipeline.transcribe import txbase as _txbase  # noqa: E402
from eval.fake import fake_asr as _fake_asr  # noqa: E402   (疑似の待ち fake_sleep の正。RS2-2)
from pipeline.transcribe import worker_client as _txworker  # noqa: E402   (IN_WORKER・ワーカーの本体のパスと環境。RS2-6 に ed_jobs から移した)


APP_ID = _runtime.TOOL_APPS["transcribe"]   # /api/ping の app 名(互換のため値は変えない。正は ytt_core.runtime.TOOL_APPS)
# 版(SERVER_VERSION)・このフォルダ(ROOT)・作業データの置き場所(段階4。DATA_DIR・TX_DIR・TMP_DIR・DATASET_DIR・EVAL_DIR・EVAL_BASE・SETTINGS・FEEDBACK)・
# スタジオと clip-marker の data.json(STUDIO_DATA・MARKER_DATA)の今の値の持ち主は ytt/workdata(RS3-0A。下の層の部品も同じ名前を直に読むため。
# ここに同じ名前を残さない = S.TX_DIR = … は serve の名前の受付が workdata へ届ける)。起動時に prepare() が ytt_core.datadir で決めて
# serve.set_data_dir() で切り替え、認識ワーカーにも環境変数 TRANSCRIBE_DATA_DIR で渡す。import した直後はこのフォルダ(テスト用)= 下の set_root
_workdata.set_root(os.path.dirname(os.path.abspath(__file__)))
INDEX = os.path.join(_workdata.ROOT, "index.html")
APP_JS = os.path.join(_workdata.ROOT, "app.js")      # 画面の JS(CSP で index.html からインラインの <script> を外したため、静的配信する)
UI_KIT_JS = os.path.join(_workdata.ROOT, "ui-kit.js")  # ui-kit/ui-kit.js の写し(dev/sync_ui_kit.py。同上)
PAGE_JS = ("cut.js", "pack-tab.js", "app-core.js", "app-jobs.js", "app-list.js", "app-learn.js", "app-rows.js", "app-tools.js")          # 「編集」のタブの JS(docs/design/edit-tool-design.md の 7。app.js より先に読む。無いものは 404)
ROSTER = os.path.join(_workdata.ROOT, "hololive-roster.json")   # ホロライブの名簿(用語集に足すための一覧)
PORT = 8775
ALLOWED_HOSTS = set()
BASE_PATH = "/"   # 画面の場所。入口の統合サーバーに取り込まれたときは "/transcribe/"(home/mount.py が prepare() で入れる)
MAX_BODY = 32 * 1024 * 1024
MAX_SEGMENTS = 20000
TAGS = ("unclear", "overlap", "bgm")   # 行に付けるメモ。unclear(聞き取れない)の行は、精度測定・学習の正解に使わない
MAX_TEXT = _txbase.MAX_TEXT   # 別名(RS2-1a。下の別名も同じ: 差し替えない名前なので、認識の部品が読む正へ移して同じ物を残した)
# 組み込みの話者「ゲーム音声など」・行の印 noSub(字幕に出さない)・draft(機械の下書き)・文書の id の形の正は ytt/schemas.py(RS2-9 に移した。
# 話者の部品(pipeline/transcribe/diarize・human/proof/speakers)が ed_state を読まずに済むように)。どれも差し替えない名前なので別名(同じ物)
OTHER_SPK_ID, OTHER_SPK_NAME, OTHER_SPK_BUILTIN, OTHER_SPK_COLOR = _yschemas.OTHER_SPK_ID, _yschemas.OTHER_SPK_NAME, _yschemas.OTHER_SPK_BUILTIN, _yschemas.OTHER_SPK_COLOR
other_speaker = _yschemas.other_speaker       # lint: keep 別名(RS2-9)= 文書の話者が組み込みの「ゲーム音声など」か
no_sub_row = _yschemas.no_sub_row             # lint: keep 別名(RS2-9)= 行の印 noSub(字幕に出さない)
ROW_DRAFT_KINDS = _yschemas.ROW_DRAFT_KINDS   # lint: keep 別名(RS2-9)= 行の印 draft の値(overlap・missing)
blank_draft_row = _yschemas.blank_draft_row   # lint: keep 別名(RS2-9)= 機械の下書きのまま(印 draft があって文字が空)の行か


MAX_SPAN_SEC = _txbase.MAX_SPAN_SEC
MAX_QUEUE = 200   # フォルダ一括で入れる分も含めた、待機できる最大件数
TID_RE = _yschemas.TID_RE   # lint: keep 別名(RS2-9)= 文書の id の形
MODEL_RE = re.compile(r"^(?!\.)[A-Za-z0-9_.-]+(/(?!\.)[A-Za-z0-9_.-]+)?$")   # 「..」で始まる名前(親フォルダの指定)は受け付けない


def valid_model(name):
    """モデル名として受け付けるか。faster-whisper は、名前と同じフォルダが(起動したフォルダからの相対で)あれば、
    それをモデルとして読み込むので、手元に実在するパスになる名前は断る(例: 「transcripts」「models/diar」)。
    Hugging Face の「組織/名前」と、small・large-v3 などの名前だけを通す。"""
    if not isinstance(name, str) or len(name) > 100 or not MODEL_RE.match(name):
        return False
    try:
        return not (os.path.exists(name) or os.path.exists(os.path.join(_workdata.ROOT, name)))
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
LANGS = _txbase.LANGS
# 幻覚の決まり文句・要確認の印の文(正は pipeline/transcribe/txbase.py。RS2-1a)
HALLUC, HALLUC_LINE, HALLUC_LINE_REST, MUSIC_ONLY = _txbase.HALLUC, _txbase.HALLUC_LINE, _txbase.HALLUC_LINE_REST, _txbase.MUSIC_ONLY
LEAK_FLAG, LEAK_MAX_SEC, REP_MIN, REP_RE = _txbase.LEAK_FLAG, _txbase.LEAK_MAX_SEC, _txbase.REP_MIN, _txbase.REP_RE


ApiError = _errors.ApiError   # 別名(正は ytt/errors.py。RS2-1a。同じクラス = except ed_state.ApiError も ytt の物を捕まえる)


# ---------- ユーティリティ ----------
def replace_retry(src, dst):
    """os.replace。Windows でウイルス対策ソフト・検索インデックスが一瞬ファイルを開いていて失敗したときは、少し待ってやり直す
    (自動保存がたまに「保存できません」になるのを防ぐ。規則は ytt_core.fsio.replace_retry)。"""
    _fsio.replace_retry(src, dst)


def atomic_write(path, data: bytes):
    """一時ファイルに書き、ディスクへ確実に書き出して(fsync)から置き換える(ytt_core.fsio.atomic_write)。
    fsync に失敗したら保存も失敗にする: 停電・強制終了のあとに「中身が空の文字起こし」が残るのを防ぐため(校正の成果を失わないことを優先)。"""
    _fsio.atomic_write(path, data, fsync_required=True)


# 共通の小道具は ytt_core の物(2026-10-09。名前は今までどおり ed_state.名前 で呼べる = 呼ぶ側は変えない)
# (下の 4 つは写しではなく別名。lint の dup-helper には `lint: keep` で印を付けた)
unlink_quiet = _fsio.unlink_quiet   # lint: keep 別名 = 消せなくても(無い・使用中)止めない(一時ファイル・付き物の後片付け)
file_stamp = _fsio.stamp            # lint: keep 別名 = (更新日時ns, 大きさ)。無い・読めなければ None(読み直しを省くキャッシュの鍵)
plain_int = _yschemas.plain_int     # lint: keep 別名 = JSON の整数(真偽値は数えない)か None
rss_mb = _tools.process_memory_mb   # lint: keep 別名 = このプロセスが使っているメモリ(MB)。取れなければ None


read_schema_json = _fsio.read_schema_json   # lint: keep 別名(RS2-1a)= 付き物の JSON(words・asr・diar・alt・ytcap)を読む。形が違えば None
union_spans = _yschemas.union_spans         # lint: keep 別名(RS2-1a)= 区間をつなぐ
add_warning = _txbase.add_warning           # lint: keep 別名(RS2-1a)= ジョブの注意を付け直す


def norm_path(p):
    """同じ動画かを比べる鍵: 絶対パスにして大文字小文字・区切りをそろえる(normcase(abspath))。ファイルには触らない"""
    return os.path.normcase(os.path.abspath(p))


def now_ms():
    """今の時刻(ミリ秒の整数。文書・記録の at・updatedAt と同じ単位)"""
    return int(time.time() * 1000)


env_off = _txbase.env_off   # lint: keep 別名(RS2-9)= 環境変数が「止める」の値(off・0・no・false)か(裏の処理を止めるスイッチ)


fake_sleep = _fake_asr.fake_wait   # lint: keep 別名(RS2-2)= 疑似のバックエンド(テスト)の 1 行ごとの待ち(環境変数 TRANSCRIBE_FAKE_DELAY 秒)


# ---------- 記録(落ちたときの手がかり) ----------
# serve.log: 起動・終了・ジョブの開始と終了(使っているメモリつき)・例外。serve.crash.log: Python が捕まえられない異常終了(ネイティブの落ち)のときの手がかり。
# .running.json: 起動中の印(実行中のジョブつき)。正常に終了すれば消える。次の起動で残っていれば「前回は異常終了」と表示する。
LOG_FILE = os.path.join(_workdata.DATA_DIR, "serve.log")
CRASH_FILE = os.path.join(_workdata.DATA_DIR, "serve.crash.log")
RUN_MARK = os.path.join(_workdata.DATA_DIR, ".running.json")
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
            raise ApiError("missing_module", "受け渡しの部品が見つかりません。ツールのフォルダの中身をまとめて入れ直してください(新しい zip を展開し直す)", 500,
                           {"detail": "pipeline_io.py / resolve_export.py: %s" % e})   # 内部の名前は detail(UI の見直し S12)
    return _pio_mod[0]
log = _txbase.log   # 別名(RS2-1a)= logging.getLogger("tx")
_run_state = {"pid": os.getpid(), "started": 0, "job": None}
_crash_fp = None


_mem = _tools.memory_label   # lint: keep 別名(RS2-1a)= 記録用のメモリの文字


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
    d = _fsio.read_json_or(RUN_MARK, _NO_MARK)
    if d is _NO_MARK:
        return None
    return d if isinstance(d, dict) else {"pid": "?"}


_NO_MARK = object()   # check_previous_run: 印が無い・読めない


def clear_mark():
    unlink_quiet(RUN_MARK)


def find_ffmpeg():
    """環境変数 TRANSCRIBE_FFMPEG があればそれ、無ければ PATH から。"""
    return _tools.find_tool("ffmpeg", "TRANSCRIBE_FFMPEG")


def ffmpeg_info(path, ff=None):
    """ffmpeg -i の出力(長さ・ストリームの行。ed_store.probe_media も読む)。ffmpeg が無い・動かせなければ None"""
    ff = ff or find_ffmpeg()
    if not ff:
        return None
    try:
        p = subprocess.run([ff, "-hide_banner", "-nostdin", "-i", path], stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                           stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace", timeout=30)
    except (OSError, subprocess.SubprocessError):
        return None
    return p.stdout or ""


def duration_in(text):
    """ffmpeg -i の出力の Duration(秒)。無ければ None"""
    m = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", text or "")
    return int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3)) if m else None


def media_duration(path):
    out = ffmpeg_info(path)
    return duration_in(out) if out is not None else None


num = _yschemas.num_or        # lint: keep 別名(RS2-1a)= 数にできれば float、違えば default
fmt_hms = _yschemas.fmt_hms   # lint: keep 別名(RS2-1a)= 秒 → 時:分:秒


def check_source(path):
    p = os.path.abspath(str(path or "").strip().strip('"'))
    if not os.path.isfile(p):
        raise ApiError("no_file", "ファイルが見つかりません(パスを確認してください)", 400)
    if os.path.splitext(p)[1].lower() not in MEDIA_TYPES:
        raise ApiError("bad_ext", "動画・音声ファイルではないようです(対応: %s)" % " ".join(sorted(MEDIA_TYPES)), 400)
    return p


# GPU(CUDA)の部品の場所と有無をこのプロセスで調べる関数(setup_cuda_paths・cuda_count・cuda_libs_ok・_gpu_ready_local)は RS2-9 に
# pipeline/transcribe/worker_client へ移した(認識ワーカーが serve を読まずに使う。S.名前 は serve の受付で読める)
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
        v = os.path.join(_workdata.ROOT, ".venv", "bin", "python")
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
                                timeout=60, creationflags=_tools.no_window_flags(new_group=True)).returncode == 0
    except Exception:
        ok = False
    _has_cache[key] = ok
    return ok


_gpu_cache = {}


def gpu_ready():
    """GPU で文字起こしできるか(画面の表示用)。サーバーのプロセスでは ctranslate2(ネイティブのライブラリ)を読み込まないよう、
    1回だけ別プロセス(認識ワーカー pipeline/transcribe/worker.py --probe)で調べて覚えておく。調べ終わるまでは False。
    このプロセスの中で認識する測る道具(IN_WORKER)は、その場で調べる(worker_client._gpu_ready_local)"""
    if _txworker.IN_WORKER:
        return _txworker._gpu_ready_local()
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
        p = subprocess.run([worker_python(), _txworker.worker_script(), "--probe"], stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                           timeout=120, env=_txworker.worker_env(), cwd=_workdata.ROOT, creationflags=_tools.no_window_flags(new_group=True))
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


MIXED_FLAG, WEAK_FLAG, NONE_FLAG = _txbase.MIXED_FLAG, _txbase.WEAK_FLAG, _txbase.NONE_FLAG   # 別名(RS2-1a)
SPK_FLAGS = _txbase.SPK_FLAGS   # 別名(RS2-8a。ed_jobs から txbase へ移した。dev/eval_asr が S.SPK_FLAGS を読む・差し替えない名前)

