# -*- coding: utf-8 -*-
"""「編集」のサーバーの部品: 置き場所・設定の値・共通の小道具・記録(落ちたときの手がかり)・作業データの切り替え。

ほかの部品の名前は `ed_xxx.名前` の形で呼ぶたびに読む(差し替えが効くように。from … import はしない)。
"""
import faulthandler
import json
import logging
import logging.handlers
import os
import sys
import threading

from ytt import errors as _errors, fsio as _fsio, runtime as _runtime, schemas as _yschemas, tools as _tools, workdata as _workdata  # noqa: E402
from flow import wire as _flowwire  # noqa: E402   置き場所と名簿の準備 setup_places(OPT-E2 1c-1)
from ytt import txbase as _txbase  # noqa: E402
from pipeline.transcribe import backend as _txbackend  # noqa: E402   疑似の切り替えの環境変数の読み mode()(RS5-D)


APP_ID = _runtime.TOOL_APPS["transcribe"]   # /api/ping の app 名(互換のため値は変えない。正は ytt.runtime.TOOL_APPS)
# 版(SERVER_VERSION)・このフォルダ(ROOT)・作業データの置き場所(段階4。DATA_DIR・TX_DIR・TMP_DIR・SETTINGS・FEEDBACK)・
# スタジオと clip-marker の data.json(STUDIO_DATA・MARKER_DATA)の今の値の持ち主は ytt/workdata(下の層の部品も同じ名前を直に読むため。
# ここに同じ名前を残さない)。起動時に prepare() が ytt.datadir で決めて
# serve.set_data_dir() で切り替え、認識ワーカーにも環境変数 TRANSCRIBE_DATA_DIR で渡す。import した直後はこのフォルダ(テスト用)= 下の set_root
_flowwire.setup_places(root=os.path.dirname(os.path.abspath(__file__)))   # 置き場所の既定(ytt/workdata の set_root)と名簿のファイル(① roster.ROSTER)を ② の準備 1 か所で(OPT-E2 1c-1)
UI_DIR = os.environ.get("YTT_EDITOR_UI_DIR") or os.path.join(os.path.dirname(_workdata.ROOT), "app", "ui", "editor")   # 画面の部品(app*.js・cut.js・pack-tab.js・proof.css)の置き場所。RV C2 で src/editor から src/app/ui/editor へ(URL は /transcribe/app.js のまま)。環境変数はテスト用(serve.py を一時フォルダに写して動かすため)
APP_JS = os.path.join(UI_DIR, "app.js")     # 画面の部品の JS(案件の画面の校正のパネルが読む)
PROOF_CSS = os.path.join(UI_DIR, "proof.css")     # 校正のパネルの CSS
PAGE_JS = ("doc-kit.js", "cut.js", "pack-tab.js", "app-tpl.js", "app-core.js", "app-jobs.js", "app-list.js", "app-learn.js", "app-rows.js", "app-tools.js")          # 「編集」のタブの JS(notes:docs/design/edit-tool-design.md の 7。app.js より先に読む。無いものは 404)
PORT = 8775
ALLOWED_HOSTS = set()
BASE_PATH = "/"   # 画面の場所。入口の統合サーバーに取り込まれたときは "/transcribe/"(app/mount.py が prepare() で入れる)
MAX_BODY = 32 * 1024 * 1024
# 組み込みの話者「ゲーム音声など」・文書の id の形の正は ytt/schemas.py。差し替えない名前なので別名(同じ物。テストが読む)
OTHER_SPK_ID, OTHER_SPK_NAME, OTHER_SPK_COLOR = _yschemas.OTHER_SPK_ID, _yschemas.OTHER_SPK_NAME, _yschemas.OTHER_SPK_COLOR
MAX_QUEUE = 200   # フォルダ一括で入れる分も含めた、待機できる最大件数
TID_RE = _yschemas.TID_RE   # lint: keep 別名 = 文書の id の形
# モデル名の検査 valid_model・MODEL_RE の正は pipeline/transcribe/worker_client(ワーカーの cwd = ROOT と対の決まり)
# 画面のモデルの選択肢(欄は残す)。large-v3 だけ(ユーザー決定「普段よく使っているモデル以外は要らない」)
# (保存済みの設定に選択肢に無い値が残っていても、画面は large-v3 に読み替える)
MODELS = [
    ("large-v3", "large-v3"),
]
LANGS = _txbase.LANGS
LEAK_FLAG = _txbase.LEAK_FLAG   # 要確認の印の文(正は ytt/txbase.py。RS2-1a)


ApiError = _errors.ApiError   # 別名(正は ytt/errors.py。RS2-1a。同じクラス = except ed_state.ApiError も ytt の物を捕まえる)


# ---------- ユーティリティ ----------
def atomic_write(path, data: bytes):
    """一時ファイルに書き、ディスクへ確実に書き出して(fsync)から置き換える(ytt.fsio.atomic_write)。
    fsync に失敗したら保存も失敗にする: 停電・強制終了のあとに「中身が空の文字起こし」が残るのを防ぐため(校正の成果を失わないことを優先)。"""
    _fsio.atomic_write(path, data, fsync_required=True)


unlink_quiet = _fsio.unlink_quiet   # lint: keep 別名(正は ytt/fsio)= 消せなくても(無い・使用中)止めない(一時ファイル・付き物の後片付け)


# ---------- 記録(落ちたときの手がかり) ----------
# serve.log: 起動・終了・ジョブの開始と終了(使っているメモリつき)・例外。serve.crash.log: Python が捕まえられない異常終了(ネイティブの落ち)のときの手がかり。
# .running.json: 起動中の印(実行中のジョブつき)。正常に終了すれば消える。次の起動で残っていれば「前回は異常終了」と表示する。
LOG_FILE = os.path.join(_workdata.DATA_DIR, "serve.log")
CRASH_FILE = os.path.join(_workdata.DATA_DIR, "serve.crash.log")
RUN_MARK = os.path.join(_workdata.DATA_DIR, ".running.json")
TOOL_ID = "transcribe"   # notes:docs/spec/pipeline.md の 4 のツールID(.runtime/transcribe.json)
log = _txbase.log   # 別名(RS2-1a)= logging.getLogger("tx")
_run_state = {"pid": os.getpid(), "started": 0, "job": None}
_crash_fp = None


_mem = _tools.memory_label   # lint: keep 別名(RS2-1a)= 記録用のメモリの文字


def runtime_path_dir():
    """<editor の1つ上>/.runtime(環境変数 YTT_RUNTIME_DIR が優先)。ytt/runtime.runtime_dir と同じ規則(起動の約束 = app の物)"""
    return _runtime.runtime_dir(_workdata.ROOT)


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


# GPU と部品の有無(nvidia_gpu・has_faster_whisper・worker_has・gpu_ready・_probe_gpu)・ワーカーの Python(worker_python)・
# 疑似のワーカーの判定(worker_fake)の正は pipeline/transcribe/worker_client


def backend_name():
    """serve の selector が読む疑似かどうか(テストは S.backend_name を差し替える)。環境変数の読みは持ち主 backend.mode()(RS5-D)"""
    return "fake" if _txbackend.mode() == "fake" else "faster-whisper"


MIXED_FLAG, WEAK_FLAG, NONE_FLAG = _txbase.MIXED_FLAG, _txbase.WEAK_FLAG, _txbase.NONE_FLAG   # 別名(RS2-1a)
SPK_FLAGS = _txbase.SPK_FLAGS   # 別名(正は txbase。dev/eval_asr が S.SPK_FLAGS を読む・差し替えない名前)

