# -*- coding: utf-8 -*-
"""配信中の盛り上がりの検出のワーカー(線 D の L2。plan/line-d-detect.md・plan/line-d-live-clipping.md の 0-10)。入口(src/pipeline/analyze/live_detect.py)が起動する子プロセス。

    py -3.10 -u src/pipeline/analyze/live_excite_worker.py --config <入口の作業データ>/live/excite/config.json [--parent <入口の pid>]
    (旧い場所 src/home/live_excite_worker.py は起動中の古い入口のための runpy の転送。RS5 で消す)

録画中の全部の録画を 1 つのワーカーで受け持つ(0-10-4)。**同時に測るのは MAX_ACTIVE(2)本まで**: 3 本目からは「順番待ち」(peaks.json の message・
queued と worker.json の queued)で、受け持っている録画の検出が終わったら古い順に始める(そのときのライブ端 − SKIP_KEEP から。録画の途中から受け持った
録画は、それより前を「飛ばした区間」にしない = 測り直さない。順番待ちのうちに配信が終わった録画は音だけで頭から測る)。
入口とは**ファイルだけ**で話す(stdin/stdout の常駐の約束は作らない。仮決め (bk)):
  config.json    入口が書く。{"v":1, "dir", "recorders": [{"id","url","token"}], "detect": {"sens","perHour"}, "spec": {"length","preRatio","lag","lagAuto",
                 "wAudio","wChat","headSec"}, "ffmpeg", "ytdlp", "chatLimitBytes", "chatStallSec", "lengthHint"?, "provisional"?}。30 秒ごとに更新の時刻を見て読み直す。
                 lengthHint = M10 の人が選んだ長さの目安(入口が length_hint() で src/eval/tools/eval_marks.py --json の結果から作る。enough のときだけ、新しく受け持つ
                 録画の長さ・前の割合に使う。無い・足りない = スタジオの解析の設定)。provisional = 仮の候補(既定オン。false で出さない)
  <録画元>/<録画>/ の state.json(続きから再開する状態)・series.jsonl(1 分 1 行)・peaks.json(候補の正本)・skipped.jsonl(飛ばした区間の測り直し)はここが書く。
  decisions.json(人の採用・見送り・自動の採用)は入口が書き、ここは読んで PeakBook に当てるだけ。worker.json(心拍)もここが書く

流れ(周期 POLL_SEC):
  1. 録画元の GET /live/list → 録画中(active)で firstPdt のある録画ごとに状態(state.json があれば続きから)
  2. GET /live/<録画>/status?since=N で新しいセグメント → 本体(GET /live/<録画>/<uri>。合言葉 Bearer)→ **3 本(約 12 秒)ずつ ffmpeg 1 回**で
     1 秒の RMS(dB)を全帯域と 2kHz 超の 2 系列(src/studio/analyze.py の audio_levels と同じフィルター。asplit で 1 回に)
  3. セグメントの受信時刻(pdt)で「録画の頭(firstPdt)からの秒」の 1 秒の箱へ(数で数えない)。欠けは音を直前の値で埋めて欠けとして覚える
  4. チャット(yt-dlp の live_chat。配信 1 本に 1 つ)を末尾から読み、timestampUsec(絶対時刻)で 1 秒の箱へ。重みは excite.message_weight
  5. 音とチャットがそろった秒から excite.Online → excite.PeakBook。欠け ±GAP_MARGIN 秒は帳簿に 0 を渡す(山を作らない)
     その前に、箱に入った音を秒の順に(チャットを待たずに)通す(RecState.scan): 雰囲気の変わり目(excite.MoodShift。全帯域の 5 分の中央値が前の 5 分より
     6dB 以上動いた)のあと 60 秒は山のしきい値を 1.3 倍(PeakBook.thr_scale)/ 音だけの先回りの Online から仮の候補(PeakBook.fast_push。
     provisional: true・endPending: true = 採用できない・枠に数えない。チャット込みの本番が近くで確定したら同じ id のまま置き換わる)。
     候補が出るまでの遅れ(山から): 本番 ≈ 90 秒(チャットの書き出しの遅れ約 21 秒 + 遅れ lag + Online の fwd 30・step 10 + 確定の 10 秒)/ 仮の候補 ≈ 40〜45 秒
  6. 遅れ(チャットの)は 600 秒を超えたら 300 秒ごとに直近 1800 秒で excite.estimate_lag(1 回 ±3 秒まで)
  7. ライブ端から 120 秒超遅れたら 60 秒分ずつまとめ、600 秒超なら古い所を飛ばす(配信が終わったら飛ばした区間の音だけ測り直す。60 秒分ずつ・
     まとまりごとに心拍・時間切れなら次の周期で続き(進みは state)・1 つの区間で REMEASURE_MAX_SEC まで)
  8. 60 秒ごとに state.json・series.jsonl、候補が変わったら peaks.json、30 秒ごとに worker.json。メモリが 512MB を超えたら状態を保存して終了コード 3
配信が終わった録画: 残りを測る → 上り中・終わり待ちの候補を確定(PeakBook.finish)→ 飛ばした区間の測り直し → 最後の保存 → yt-dlp を止めて生のチャットを消す。そのあとは触らない。

標準ライブラリだけ(numpy は使わない)。優先度は「通常より下」(入口が起動するときに指定。子の ffmpeg・yt-dlp も)。ffmpeg・yt-dlp は KillJob に入れる
(ワーカーが落ちたら子も消える)。yt-dlp を止めるときは子ごと(kill_tree。PyInstaller の 1 ファイルの exe は子を作る)。
重い処理の順番(SLOTS)は取らない(短い ffmpeg 1 回ずつ。0-10-4)。1 本の録画・チャットの思わぬ例外は、その録画の message と心拍の error に出して
ほかは進める(同じエラーのログは 1 回だけ。ログのファイルが LOG_LIMIT を超えたらそれより先は書かない)。
テストは「音を測る」(measure_batch)・「録画元から取る」(client_factory)・「時計」(clock)・yt-dlp の起動(launcher)を差し替えて、12 時間を早送りで回す
(src/home/tests/test_live_detect.py)。
"""
import argparse
import glob
import http.client
import json
import math
import os
import re
import signal
import subprocess
import sys
import time
import traceback
import urllib.parse

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))   # analyze -> pipeline -> src(「root」= src。datadir.resolve の inplace の根)
if __name__ == "__main__":   # スクリプトとして起動したときだけ: このフォルダを外して src を先頭に(兄弟は絶対 import。層の決まりの例外)。import したとき(live_detect・テスト)は触らない
    sys.path[:] = [ROOT] + [p for p in sys.path if os.path.normcase(os.path.abspath(p or os.curdir)) not in (os.path.normcase(HERE), os.path.normcase(ROOT))]
from pipeline.analyze import excite  # noqa: E402
from ytt import datadir, fsio, recproto, schemas, tools  # noqa: E402

WORKER_VERSION = "1"
POLL_SEC = 6.0             # 周期(5〜10 秒)
CONFIG_CHECK_SEC = 30.0    # config.json の更新を見る間隔
SAVE_SEC = 60.0            # state.json・series.jsonl を書く間隔(0-10-5)
HEART_SEC = 30.0           # worker.json の間隔(入口は 120 秒止まったら起動し直す)
MEM_CHECK_SEC = 60.0
MEM_LIMIT_MB = 512
TICK_BUDGET = 20.0         # 1 回の周期で測るのに使う上限(秒。心拍を止めない)
BATCH_SEGS = 3             # ふだんはセグメント 3 本(約 12 秒)ずつ ffmpeg 1 回
BIG_BATCH_SEC = 60.0       # 遅れたときは 60 秒分ずつ
BIG_BATCH_SEGS = 30
BEHIND_BIG = 120.0         # ライブ端からこれだけ遅れたら、まとめる量を増やす
BEHIND_SKIP = 600.0        # これだけ遅れたら、古い所を飛ばして追いつく
SKIP_KEEP = 60.0           # 飛ばしたあと、ライブ端のこれだけ手前から測る
REMEASURE_MAX_SEC = 1800.0  # 飛ばした区間を配信のあとに測り直す長さの上限(1 つの区間ごと。超えた分は測らない = capped)
FILL_MAX = 48 * 3600       # 欠けを埋める上限(秒。これより大きく受信時刻が飛んだら壊れた時刻として続けて置く)
LOG_LIMIT = 4 * 1024 * 1024   # 標準出力(入口の logs/excite.log)がこれを超えたら、それより先は書かない(入口が次の起動で回す)
SEG_TOL = 1.5              # セグメントがつながっているとみなす受信時刻のずれ(秒)
ANCHOR_TOL = 2             # 測った値の箱の位置が、受信時刻からの位置とこれだけずれるまでは続けて置く(丸めのずれ)
GAP_MIN = 5                # これより長い飛びを「欠け」として覚える(短い飛びは埋めるだけ)
GAP_MARGIN = 5             # 欠けの前後この秒数は帳簿に 0 を渡す(山を作らない。仮決め)
CHAT_GRACE = 40.0          # チャットの続きが来なくても、受信時刻からこれだけたった秒は進める(静かなチャットで止まらない。yt-dlp の書き出しは約 21 秒遅れる = L0 の実測)
LAG_FIRST, LAG_EVERY, LAG_SPAN, LAG_STEP = 600, 300, 1800, 3   # 遅れの推定(0-10-3 の 4)
CHAT_LIMIT = 64 * 1024 * 1024    # チャットのファイルがこれを超えたら新しいファイルへ(0-10-5)
CHAT_STALL = 300.0               # 録画が進んでいるのにチャットのファイルがこれだけ増えなければ起動し直す
CHAT_BACKOFF = (30.0, 60.0, 120.0, 240.0, 480.0, 600.0)   # 起動し直す間隔(最大 10 分)
CHAT_MAX_PER_HOUR = 6            # 1 時間にこれを超えて起動し直したら諦める(音だけ)
CHAT_READ_MAX = 16 * 1024 * 1024  # 1 回の周期で読むチャットの上限
TAIL_IDLE = 10.0                 # 止めた yt-dlp のファイルの改行の無い末尾が、これだけ増えなければ読み終えたことにする
FFMPEG_TIMEOUT = 120.0
EXIT_MEM, EXIT_LOCKED = 3, 4
STATE_MAX = 64 * 1024 * 1024
SPEC_DEFAULT = {"length": 45.0, "preRatio": excite.PRE_RATIO_DEFAULT, "lag": 8.0, "lagAuto": True, "wAudio": 1.0, "wChat": 1.0, "headSec": 180.0}
MAX_ACTIVE = 2             # 同時に測る録画の数(0-10-4)。3 本目からは「順番待ち」(前の録画の検出が終わったら、古い順に始める)
QUEUED_EVERY = 60.0        # 順番待ちの録画の peaks.json を書き直す間隔(文が変わったときはすぐ)
# M10: 自動の候補の長さを人の記録から(plan/line-d-auto-pack.md の M10・6 の決定 4)。src/eval/tools/eval_marks.py --json の結果(スタジオの作業データ
# evals/marks/<日時>.json。入口の夜の自動測定 accuracy.py が流す)の clipLength.suggest を入口が読み(length_hint)、config.json の lengthHint に入れる。
# ワーカーは読むだけ(clean_hint)。足りない(enough でない)ときはスタジオの解析の設定のまま。dev/ は import しない(結果のファイルを読むだけ)
LENGTH_HINT_ENV = "YTT_LIVE_LENGTH"        # off = 使わない(スタジオの解析の設定の長さのまま)
LENGTH_HINT_MAX_AGE = 30 * 86400           # 結果のファイルの古さ(ファイル名の日時。src/home/autorun.py の FRIEND_LENGTH_MAX_AGE と同じ)
LENGTH_HINT_MIN_SAMPLES, LENGTH_HINT_MIN_VIDEOS = 20, 5   # enough の条件(src/eval/tools/eval_marks.py の CL_ENOUGH_SAMPLES・CL_ENOUGH_VIDEOS と同じ値。ワーカーでも確かめ直す)
# スタジオの解析の設定(spec)の範囲(src/studio/analyze.py の validate_settings と同じ)。入口の live_detect.clean_spec と、ここの clean_hint が読む
SPEC_RANGES = {"length": (10.0, 120.0), "preRatio": (0.3, 0.9), "lag": (0.0, 30.0), "wAudio": (0.0, 3.0), "wChat": (0.0, 3.0), "headSec": (0.0, 600.0)}
EVAL_MARKS_RE = re.compile(r"^(\d{8}-\d{6})(?:_auto)?\.json\Z")   # src/home/autorun.py の EVAL_MARKS_NAME_RE と同じ形
EVAL_READ_MAX = 16 * 1024 * 1024
# 録画元との約束(録画元・録画・セグメントの id の形、時刻の書き方、動画の id)は ytt_core/recproto.py の 1 か所(入口の live_export と同じ物)
ID_RE, REC_RE, SEG_URI_RE = recproto.RECORDER_ID_RE, recproto.REC_ID_RE, recproto.SEG_URI_RE
iso_epoch, epoch_iso, video_id = recproto.iso_epoch, recproto.epoch_iso, recproto.video_id_of
PEAK_ID_RE = re.compile(r"^p(\d{1,7})-\d{1,8}\Z")    # 候補の id(excite.PeakBook の "p<通し番号>-<山の秒>"。入口の live_detect も同じ形で検査する)
PEAK_AHEAD = 20            # まだ帳簿に無い候補の決定を待つのは、通し番号が今の番号からこれ未満先のときだけ(起動し直して最後の保存より後の候補がまだ出ていない)
LEVEL_KEY = "lavfi.astats.Overall.RMS_level="
LEVEL_MAX = 20.0           # RMS(dB)の上限(壊れた値で式が振り切れないように。ふつうは 0 以下)
STATS = "asetnsamples=n=16000:p=0,astats=metadata=1:reset=1,ametadata=print:key=lavfi.astats.Overall.RMS_level"
NOCHAT_HINTS = ("There are no subtitles", "no subtitles for the requested", "Live chat is disabled", "members-only", "Join this channel", "Private video")
BLOCK_HINTS = ("HTTP Error 403", "HTTP Error 429", "403: Forbidden", "429: Too Many")


class MeasureError(Exception):
    """1 回分を測れなかった(そのセグメントの秒は欠けとして埋めて先へ進む)"""


class NoTool(Exception):
    """ffmpeg が無い(先へ進まず、心拍の error に出す)"""


class RecorderDown(Exception):
    """録画元につながらない(次の周期でやり直す)"""


# ---------------------------------------------------------------- 小道具
def pid_alive(pid):
    """入口(親)がまだ動いているか。分からなければ True(勝手に終わらない)"""
    if not pid:
        return True
    if os.name == "nt":
        try:
            import ctypes
            from ctypes import wintypes
            k = ctypes.WinDLL("kernel32", use_last_error=True)
            k.OpenProcess.restype = wintypes.HANDLE
            k.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
            h = k.OpenProcess(0x00100000, False, int(pid))   # SYNCHRONIZE
            if not h:
                return ctypes.get_last_error() == 5   # 権限が無い = 動いている
            try:
                return k.WaitForSingleObject(h, 0) == 0x102   # WAIT_TIMEOUT = まだ動いている
            finally:
                k.CloseHandle(h)
        except Exception:
            return True
    try:
        os.kill(int(pid), 0)
        return True
    except ProcessLookupError:
        return False
    except OSError:
        return True


def take_lock(path):
    """1 つの作業データに 1 つのワーカー(ファイルの書き手を 1 つにする)。-> 開いたファイル(持っている間だけ有効)か None(ほかのワーカーが持っている)"""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    f = open(path, "a+b")
    try:
        if os.name == "nt":
            import msvcrt
            f.seek(0)
            msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        return f
    except OSError:
        f.close()
        return None


def write_json(path, obj):
    """書きかけを残さずに JSON を書く。NaN・無限大は書かない(ValueError。JSON として読めないファイルを作らない)"""
    fsio.atomic_write(path, json.dumps(obj, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8"))


def append_jsonl(path, rows):
    """1 行 1 JSON のファイル(series.jsonl・skipped.jsonl)に足す"""
    with open(path, "a", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, separators=(",", ":")) + "\n")


def clean_requests(v):
    """config.json の requests(友人のライブ配信の依頼の録画ごとの設定。2-15)-> {"<録画元>/<録画>": {"sens", "perHour", "length"}}(読めない鍵は飛ばす)"""
    out = {}
    for k, s in (v or {}).items() if isinstance(v, dict) else []:
        if not isinstance(k, str) or "/" not in k or not isinstance(s, dict):
            continue
        det = clean_detect(s)
        llo, lhi = SPEC_RANGES["length"]
        length = float(s.get("length")) if schemas.is_num(s.get("length")) and llo <= s["length"] <= lhi else None
        out[k] = {"sens": det["sens"], "perHour": det["perHour"], "length": length}
    return out


def clean_detect(det):
    """感度と 1 時間の本数(入口の設定 live.detect → config.json の detect)-> {"sens", "perHour"}(読めなければ normal・6)。
    入口(live_detect.Detector.config)が書くときとワーカーが読むときの両方で通す"""
    det = det if isinstance(det, dict) else {}
    return {"sens": det.get("sens") if det.get("sens") in excite.SENS else "normal", "perHour": det["perHour"] if schemas.is_int(det.get("perHour")) else 6}


def _level(v):
    """ffmpeg の RMS の値(dB)-> -90〜LEVEL_MAX(読めない・NaN・無限大は -90。大きすぎる値は切る)"""
    try:
        x = float(v)
    except ValueError:
        return -90.0
    if not math.isfinite(x) or x < -90:
        return -90.0
    return min(LEVEL_MAX, x)


def _read_levels(path):
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            return [_level(line.split("=", 1)[1]) for line in f if line.startswith(LEVEL_KEY)]
    except OSError:
        return []


def measure_levels(ffmpeg, path, wdir, job=None, timeout=FFMPEG_TIMEOUT):
    """ffmpeg 1 回で 1 秒ごとの RMS(dB)を全帯域と 2kHz 超の 2 系列 -> (full, band)。
    フィルターは src/studio/analyze.py の audio_levels と同じ(aresample=16000・asetnsamples=n=16000:p=0・astats・ametadata)。asplit で 1 回にし、
    結果は 2 つのファイル(作業用のフォルダの full.txt・band.txt。行が混ざらない)。値が無い・NaN・-90 未満は -90"""
    if not ffmpeg:
        raise NoTool("ffmpeg が見つかりません(setup の install.bat で入れてください)")
    outs = [os.path.join(wdir, n) for n in ("full.txt", "band.txt")]
    for p in outs:
        fsio.unlink_quiet(p)
    fc = "[0:a]aresample=16000,asplit=2[a][b];[a]%s:file=full.txt[oa];[b]highpass=f=2000,%s:file=band.txt[ob]" % (STATS, STATS)
    cmd = [ffmpeg, "-hide_banner", "-nostdin", "-loglevel", "error", "-protocol_whitelist", "file,pipe", "-i", os.path.abspath(path),
           "-filter_complex", fc, "-map", "[oa]", "-f", "null", "-", "-map", "[ob]", "-f", "null", "-"]
    try:
        proc = subprocess.Popen(cmd, cwd=wdir, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, creationflags=tools.no_window_flags(priority="low"))
    except OSError as e:
        raise NoTool("ffmpeg を起動できませんでした: %s" % tools.why(e))
    if job is not None:
        job.add(proc)
    try:
        _out, err = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        tools.kill_quiet(proc)
        proc.communicate()
        raise MeasureError("ffmpeg が %d 秒で終わりませんでした" % int(timeout))
    full, band = _read_levels(outs[0]), _read_levels(outs[1])
    for p in outs:
        fsio.unlink_quiet(p)
    if proc.returncode != 0 or not full:
        tail = (err or b"").decode("utf-8", "replace").strip().splitlines()[-1:] or [""]
        raise MeasureError("音を測れませんでした(ffmpeg %s: %s)" % (proc.returncode, tail[0][:160]))
    band = (band + [band[-1] if band else -90.0] * len(full))[:len(full)]
    return full, band


def parse_chat_line(line):
    """yt-dlp の live_chat の 1 行 -> [(時刻 epoch, 重み)]。時刻は renderer の timestampUsec(絶対時刻)。無いものは数えない(仮決め)"""
    try:
        d = json.loads(line)
    except ValueError:
        return []
    ra = d.get("replayChatItemAction") if isinstance(d, dict) else None
    acts = ra.get("actions") if isinstance(ra, dict) else ([d] if isinstance(d, dict) and "addChatItemAction" in d else None)
    out = []
    for a in acts or []:
        item = ((a.get("addChatItemAction") or {}).get("item")) if isinstance(a, dict) else None
        if not isinstance(item, dict) or not item:
            continue
        kind, r = next(iter(item.items()))
        if not isinstance(r, dict):
            continue
        w, _warm, _paid = excite.message_weight(kind, excite.message_text(r))
        if w is None:
            continue
        try:
            ts = int(r.get("timestampUsec")) / 1e6
        except (TypeError, ValueError):
            continue
        out.append((ts, w))
    return out


# ---------------------------------------------------------------- 候補の長さの目安(M10)
_HINT_CACHE = {}


def length_hint(root=None, env=None, now=None):
    """**入口の側**(src/pipeline/analyze/live_detect.py の Detector.config が呼んで config.json の lengthHint に入れる): 人が選んだ区間の長さの目安
    -> {"length", "preRatio"(無ければ None), "samples", "videos", "enough", "file"} か None(止めてある・結果が無い・古い・壊れている)。
    読むのはスタジオの作業データ evals/marks/ のいちばん新しい src/eval/tools/eval_marks.py --json の結果の clipLength.suggest(置き場所は ytt_core.datadir の
    resolve = 入口のプロセスでスタジオが登録した場所)。同じファイルは読み直さない(名前と更新の時刻で覚える)。enough の判定はワーカーの clean_hint がする"""
    e = os.environ if env is None else env
    if str(e.get(LENGTH_HINT_ENV) or "").strip().lower() in ("off", "0", "false", "no"):
        return None
    folder = os.path.join(datadir.resolve("studio", root or ROOT, env), "evals", "marks")
    try:
        names = sorted(n for n in os.listdir(folder) if EVAL_MARKS_RE.match(n))
    except OSError:
        return None
    if not names:
        return None
    name = names[-1]
    try:
        stamp = time.mktime(time.strptime(EVAL_MARKS_RE.match(name).group(1), "%Y%m%d-%H%M%S"))
    except (ValueError, OverflowError):
        return None
    if (time.time() if now is None else now) - stamp > LENGTH_HINT_MAX_AGE:
        return None
    path = os.path.join(folder, name)
    try:
        st = os.stat(path)
    except OSError:
        return None
    key = (path, st.st_mtime_ns, st.st_size)
    if _HINT_CACHE.get("key") == key:
        return dict(_HINT_CACHE["value"]) if _HINT_CACHE["value"] else None
    out = None
    try:
        s = fsio.read_json_file(path, EVAL_READ_MAX)["clipLength"]["suggest"]
        if isinstance(s, dict) and schemas.is_num(s.get("length")) and schemas.is_int(s.get("samples")) and schemas.is_int(s.get("videos")):
            out = {"length": float(s["length"]), "preRatio": float(s["preRatio"]) if schemas.is_num(s.get("preRatio")) else None,
                   "samples": s["samples"], "videos": s["videos"], "enough": s.get("enough") is True, "file": name}
    except (OSError, ValueError, KeyError, TypeError):
        out = None
    _HINT_CACHE.update(key=key, value=out)
    return dict(out) if out else None


def clean_hint(h):
    """config.json の lengthHint -> 使ってよい目安 {"length", "preRatio"?, "samples", "videos", "file"} か None。
    使うのは enough(見本 LENGTH_HINT_MIN_SAMPLES 以上かつ配信 LENGTH_HINT_MIN_VIDEOS 本以上)のときだけ。長さは 10〜120 秒・前の割合は 0.3〜0.9 に丸める"""
    if not isinstance(h, dict) or h.get("enough") is not True or not schemas.is_num(h.get("length")):
        return None
    n, v = h.get("samples"), h.get("videos")
    if not (schemas.is_int(n) and n >= LENGTH_HINT_MIN_SAMPLES and schemas.is_int(v) and v >= LENGTH_HINT_MIN_VIDEOS):
        return None
    (llo, lhi), (plo, phi) = SPEC_RANGES["length"], SPEC_RANGES["preRatio"]
    out = {"length": float(round(min(lhi, max(llo, float(h["length"]))))), "samples": n, "videos": v, "file": str(h.get("file") or "")[:40]}
    if schemas.is_num(h.get("preRatio")):
        out["preRatio"] = round(min(phi, max(plo, float(h["preRatio"]))), 2)
    return out


def spec_with_hint(spec, hint):
    """新しく受け持つ録画の spec: 目安(clean_hint 済み)があれば長さ・前の割合をそれに(lengthFrom "human")、無ければスタジオの設定のまま("studio")"""
    out = dict(spec)
    if hint:
        out["length"] = hint["length"]
        if "preRatio" in hint:
            out["preRatio"] = hint["preRatio"]
        out["lengthFrom"] = "human"
        out["lengthNote"] = "人が選んだ長さの中央値(見本 %d 個・配信 %d 本)" % (hint["samples"], hint["videos"])
    else:
        out["lengthFrom"] = "studio"
    return out


# ---------------------------------------------------------------- 録画元
class RecorderClient:
    """録画元の API(GET だけ)。合言葉 Bearer と Host を付ける(src/home/live.py の Live.request と同じ形)"""

    def __init__(self, rc, timeout=10.0):
        self.rc, self.timeout = rc, timeout

    def _get(self, path, max_bytes):
        u = urllib.parse.urlsplit(self.rc.get("url") or "")
        if u.scheme != "http" or not u.hostname or not u.port:
            return None, None
        conn = http.client.HTTPConnection(u.hostname, u.port, timeout=self.timeout)
        try:
            conn.request("GET", path, headers={"Host": u.netloc, "Authorization": "Bearer " + (self.rc.get("token") or ""), "Accept": "*/*"})
            r = conn.getresponse()
            return r.status, r.read(max_bytes)
        except (OSError, http.client.HTTPException):
            return None, None
        finally:
            conn.close()

    def get_json(self, path):
        code, raw = self._get(path, 16 * 1024 * 1024)
        if code is None:
            return None, None
        try:
            return code, json.loads(raw.decode("utf-8", "replace"))
        except ValueError:
            return code, None

    def get_bytes(self, path):
        return self._get(path, 64 * 1024 * 1024)


def launch_process(cmd, logf):
    """yt-dlp を起動する(既定の launcher。テストは偽物に替える)。Windows 以外は新しいセッション(kill_tree がプロセスグループごと止める)"""
    extra = {} if os.name == "nt" else {"start_new_session": True}
    return subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=logf, stderr=subprocess.STDOUT, creationflags=tools.no_window_flags(priority="low"), **extra)


# ---------------------------------------------------------------- チャット(配信 1 本に yt-dlp 1 つ)
class ChatFeed:
    """yt-dlp の live_chat を読み続ける(0-10-5)。起動するたびに新しいファイル <videoId>.<通し番号>.live_chat.json(.part)(起動し直しと 64MB の回しで
    前のファイルを上書きさせない)。行は 1 行 1 JSON(isLive・replayChatItemAction・videoOffsetTimeMsec。数えるのは addChatItemAction の CHAT_KINDS だけ)。伸びるファイルを末尾から読み、読んだ位置を覚える。古いファイルは読み切ってから消す。
    止まった(録画が進んでいるのに stall 秒増えない。前は増えていた)・終わった → 間隔(backoff)をあけて起動し直す。1 時間に max_per_hour 回を超えたら諦める
    (state "none" = 音だけ)。403・429 が出たら最大の間隔から。最初の起動で「チャットが無い」と分かれば最初から諦める"""

    def __init__(self, vid, url, folder, ytdlp, launcher=None, job=None, log=None, limit=CHAT_LIMIT, stall=CHAT_STALL,
                 backoff=CHAT_BACKOFF, max_per_hour=CHAT_MAX_PER_HOUR, read_max=CHAT_READ_MAX):
        self.vid, self.url, self.folder, self.ytdlp = vid, url, folder, ytdlp
        self.launcher = launcher or launch_process
        self.job, self.log = job, log or (lambda m: None)
        self.limit, self.stall, self.backoff, self.max_per_hour, self.read_max = limit, stall, tuple(backoff), max_per_hour, read_max
        self.subs = set()
        self.gen = 0               # 起動の通し番号
        self.proc = None
        self.logf = None
        self.files = []            # [[通し番号, 読んだ位置]](古い順)
        self.state = "starting"    # starting | ok | restarting | none
        self.reason = ""
        self.fails = 0             # 続けて失敗した数(間隔の段)
        self.restarts = []         # 失敗で起動し直した時刻(1 時間の数)
        self.total_restarts = 0
        self.next_at = 0.0
        self.grew_at = None
        self.ever_grew = False
        self.max_ts = 0.0          # 読んだメッセージの時刻の最大(epoch)
        self.dedupe_ts = 0.0       # 起動し直したあと、この時刻以下は前のファイルで数えた(重ねない)
        self.launches = 0
        self.tails = {}            # 止めた yt-dlp のファイルの改行の無い末尾: 通し番号 -> (大きさ, その大きさになった時刻)

    # ---- 保存
    def to_json(self):
        return {"gen": self.gen, "files": [list(x) for x in self.files], "state": self.state if self.state == "none" else "starting", "reason": self.reason,
                "fails": self.fails, "restarts": list(self.restarts), "totalRestarts": self.total_restarts, "maxTs": self.max_ts,
                "dedupeTs": self.dedupe_ts, "everGrew": self.ever_grew}

    def load(self, d):
        """前のワーカーの続き(前の yt-dlp はワーカーと一緒に終わっている = 残ったファイルを読み切ってから、新しい番号で起動し直す)"""
        self.gen = int(d.get("gen") or 0)
        self.files = [[int(g), int(p)] for g, p in d.get("files") or []]
        self.state = "none" if d.get("state") == "none" else "starting"
        self.reason = str(d.get("reason") or "")
        self.fails = int(d.get("fails") or 0)
        self.restarts = [float(x) for x in d.get("restarts") or []]
        self.total_restarts = int(d.get("totalRestarts") or 0)
        self.max_ts, self.dedupe_ts = float(d.get("maxTs") or 0.0), float(d.get("dedupeTs") or 0.0)
        self.ever_grew = bool(d.get("everGrew"))
        return self

    def view_state(self):
        """peaks.json の chat: ok | restarting | none"""
        return {"starting": "ok", "ok": "ok", "restarting": "restarting", "none": "none"}.get(self.state, "ok")

    # ---- ファイル
    def stem(self, gen):
        return os.path.join(self.folder, "%s.%d" % (self.vid, gen))

    def path_of(self, gen):
        """yt-dlp が書くチャットのファイル。配信中は <stem>.live_chat.json.part に追記し、終わってから .live_chat.json へ名前を変える(L0 の実測 2026-10-07)。
        隣にできては消える断片 .part-FragNNN は読まない。まだ無ければ None"""
        stem = self.stem(gen)
        for p in (stem + ".live_chat.json.part", stem + ".live_chat.json"):
            if os.path.isfile(p):
                return p
        found = sorted(p for p in glob.glob(glob.escape(stem) + ".*")
                       if "live_chat" in os.path.basename(p) and "-Frag" not in os.path.basename(p) and not p.endswith(".log"))
        return found[0] if found else None

    def _log_tail(self, gen, n=4096):
        try:
            with open(self.stem(gen) + ".log", "rb") as f:
                f.seek(max(0, os.path.getsize(f.name) - n))
                return f.read().decode("utf-8", "replace")
        except OSError:
            return ""

    # ---- 動かす
    def step(self, now, alive=True):
        """周期ごと: 起動・止まりの見張り・読む -> 新しいメッセージ [(時刻 epoch, 重み)]"""
        if self.state == "none":
            self.close(delete=False)
            return self.read(now)
        self._watch(now, alive)
        msgs = self.read(now)
        if alive and self.proc is None and self.state != "none" and now >= self.next_at and not self._old_unread():   # 配信が終わったら起動し直さない
            self._start(now)
            msgs += self.read(now)
        return msgs

    def _old_unread(self):
        """止めた yt-dlp のファイルにまだ読んでいない所があるか(読み切ってから次を起動 = 重ねの見分け dedupe_ts が崩れない)。
        末尾の改行の無い行は、止めたあと TAIL_IDLE 秒増えなければ read が読み終えたことにする(書きかけで止まった行で、二度と起動し直さないことが無いように)"""
        return any(self._size(g) > pos for g, pos in self.files)

    def _live_gen(self, gen):
        """今動いている yt-dlp が書いているファイルか"""
        return gen == self.gen and self.proc is not None

    def _size(self, gen):
        p = self.path_of(gen)
        try:
            return os.path.getsize(p) if p else 0
        except OSError:
            return 0

    def _start(self, now):
        self.gen += 1
        self.dedupe_ts = self.max_ts
        os.makedirs(self.folder, exist_ok=True)
        exe = [sys.executable, self.ytdlp] if self.ytdlp.lower().endswith(".py") else [self.ytdlp]
        cmd = exe + ["--no-playlist", "--no-warnings", "--newline", "--skip-download", "--write-subs", "--sub-langs", "live_chat",
                     "-o", self.stem(self.gen) + ".%(ext)s", "--", self.url]
        try:
            self.logf = open(self.stem(self.gen) + ".log", "ab")
            self.proc = self.launcher(cmd, self.logf)
        except OSError as e:
            self._close_log()
            self.proc = None
            self._failed(now, "", "yt-dlp を起動できませんでした: %s" % tools.why(e))
            return
        if self.job is not None:
            self.job.add(self.proc)
        self.launches += 1
        self.files.append([self.gen, 0])
        self.grew_at = now
        if self.state != "restarting":
            self.state = "starting" if not self.ever_grew else "ok"
        self.log("チャット %s: yt-dlp を起動しました(%d 回目)" % (self.vid, self.gen))

    def _close_log(self):
        if self.logf is not None:
            try:
                self.logf.close()
            except OSError:
                pass
            self.logf = None

    def _kill(self):
        p, self.proc = self.proc, None
        if p is not None:
            tools.kill_tree(p)   # 子ごと(PyInstaller の yt-dlp。System32 の taskkill /T /F・ほかはプロセスグループ)
            try:
                p.wait(5)
            except Exception:
                pass
        self._close_log()

    def _watch(self, now, alive):
        if self.proc is None:
            return
        rc = self.proc.poll()
        if rc is not None:   # 終わった(配信の終わり・エラー)
            self._kill()
            text = self._log_tail(self.gen)
            if not self.ever_grew and self.launches <= 1 and any(h in text for h in NOCHAT_HINTS):
                return self._give_up("この配信はチャットを取れません(チャットがオフ・メンバー限定など)。音だけで候補を出します")
            if alive:
                self._failed(now, text, "yt-dlp が終わりました(終了コード %s)" % rc)
            return
        text = self._log_tail(self.gen, 1024)
        if any(h in text for h in BLOCK_HINTS):   # YouTube に止められた(403・429): 待たずに止めて、最大の間隔から
            self._kill()
            return self._failed(now, text, "YouTube にチャットの読み取りを止められました")
        size = self._size(self.gen)
        if size > self.limit:   # 64MB: 新しいファイルへ(数えない・待たない)
            self._kill()
            self.next_at = now
            self.log("チャット %s: ファイルが %d MB を超えたので新しいファイルにします" % (self.vid, self.limit // 1048576))
            return
        if alive and self.ever_grew and self.grew_at is not None and now - self.grew_at > self.stall:
            self._kill()
            self._failed(now, self._log_tail(self.gen), "チャットが %d 秒増えていません" % int(self.stall))

    def _failed(self, now, text, why):
        self.restarts = [t for t in self.restarts if now - t < 3600.0] + [now]
        self.total_restarts += 1
        if len(self.restarts) > self.max_per_hour:
            return self._give_up("チャットを 1 時間に %d 回起動し直してもつながらないので、音だけで候補を出します(%s)" % (self.max_per_hour, why))
        idx = len(self.backoff) - 1 if any(h in text for h in BLOCK_HINTS) else min(self.fails, len(self.backoff) - 1)
        self.fails += 1
        self.next_at = now + self.backoff[idx]
        self.state = "restarting"
        self.reason = why
        self.log("チャット %s: %s。%d 秒あけて起動し直します" % (self.vid, why, int(self.backoff[idx])))

    def _give_up(self, why):
        self._kill()
        self.state, self.reason = "none", why
        self.log("チャット %s: %s" % (self.vid, why))

    def read(self, now):
        """伸びたぶんを読む(行の終わりまで)。読み切った古いファイルは消す -> [(時刻, 重み)]"""
        out, budget = [], self.read_max
        for ent in list(self.files):
            gen, pos = ent
            p = self.path_of(gen)
            if p is None:
                continue
            try:
                with open(p, "rb") as f:
                    f.seek(pos)
                    raw = f.read(budget)
                    size = os.fstat(f.fileno()).st_size
            except OSError:
                continue
            cut = raw.rfind(b"\n") + 1
            if not self._live_gen(gen) and raw and pos + len(raw) >= size and len(raw) > cut:   # 止めた yt-dlp の、改行の無い末尾
                seen = self.tails.get(gen)
                if seen is None or seen[0] != size:
                    self.tails[gen] = (size, now)
                elif now - seen[1] >= TAIL_IDLE:   # 増えない: 書きかけで止まった行。読めればその行も数え、読み終えたことにする
                    cut = len(raw)
                    self.tails.pop(gen, None)
            if cut:
                budget -= cut
                ent[1] = pos + cut
                for line in raw[:cut].decode("utf-8", "replace").splitlines():
                    for ts, w in parse_chat_line(line):
                        if ts > self.dedupe_ts:
                            out.append((ts, w))
                        self.max_ts = max(self.max_ts, ts)
                if self._live_gen(gen):
                    self.grew_at, self.ever_grew, self.fails = now, True, 0
                    if self.state in ("starting", "restarting"):
                        self.state = "ok"
            if gen != self.gen and ent[1] >= self._size(gen):   # 前の起動のファイル: 読み切ったので消す(生のチャットは残さない)
                self._remove_files(gen)
                self.files.remove(ent)
        return out

    def _remove_files(self, gen):
        for p in glob.glob(glob.escape(self.stem(gen)) + ".*"):
            fsio.unlink_quiet(p)

    def close(self, delete=True):
        """止める。delete なら生のチャットのファイルを全部消す(配信が終わった)"""
        self._kill()
        if delete:
            for p in glob.glob(glob.escape(os.path.join(self.folder, self.vid)) + ".*"):
                fsio.unlink_quiet(p)
            self.files = []


# ---------------------------------------------------------------- 録画 1 本の状態
class RecState:
    """録画 1 本の計算(音とチャットの箱 → Online → PeakBook)と保存。時計・ファイル以外の入出力は Worker が渡す"""

    def __init__(self, folder, rc, rec, url, first, spec, detect, use_chat, grace=CHAT_GRACE, provisional=True):
        self.folder, self.rc, self.rec, self.url, self.first = folder, rc, rec, url or "", float(first)
        self.vid = video_id(url, rec)
        self.spec = dict(spec)
        self.args = {"back": excite.ONLINE_BACK, "fwd": excite.ONLINE_FWD, "window": excite.ONLINE_WINDOW, "lag": self.spec["lag"],
                     "w_audio": self.spec["wAudio"], "w_chat": self.spec["wChat"], "head": self.spec["headSec"]}
        self.use_chat = bool(use_chat)
        self.chat_state = "ok" if use_chat else "off"
        self.online = excite.Online(use_chat=self.use_chat, **self.args)
        det = clean_detect(detect)
        self.book = excite.PeakBook(self.spec["length"], self.spec["preRatio"], det["sens"], det["perHour"])
        # 候補が出るまでの遅れを縮める(仮の候補): チャットを待たずに音だけで先に計算する Online(同じ窓・同じ重み。チャットなしの録画は本番がもう待たないので作らない)
        self.fast = excite.Online(use_chat=False, **self.args) if self.use_chat and provisional else None
        self.mood = excite.MoodShift()   # 雰囲気の変わり目(0-10-5)
        self.mood_shifts = 0
        self.next_scan = 0          # 次に「変わり目」と先回りの計算に通す秒(箱に入った順。チャットを待たない)
        self.grace = grace
        self.seg_since = 0          # 録画元の segmentList の次の番号
        self.next_box = 0           # 次に音の値を置く秒
        self.next_push = 0          # 次に Online へ渡す秒
        self.audio = {}             # 秒 -> [全帯域, 2kHz 超](まだ渡していない分)
        self.last_audio = None
        self.chat_bins = {}         # 秒 -> チャットの重みの和(まだ渡していない分)
        self.chat_wm = -1.0         # 読んだチャットの時刻の最大(録画の頭からの秒)
        self.raw = {}               # 秒 -> [全帯域, 2kHz 超, チャット](Online に渡したが、まだ点数が出ていない分)
        self.gaps = []              # [[から, まで)](欠け。帳簿の前後 GAP_MARGIN 秒に使うので、過ぎたものは数だけ残す)
        self.gap_count = 0
        self.skipped = []           # [{from, to, since, until, done, pos?, sec?, capped?}](遅れて飛ばした区間。配信が終わったら測り直す。pos = 測り直したセグメントの数)
        self.late_from = None       # 録画の途中から受け持ったとき、測り始めた秒(それより前は測らない)
        self.last_error = ""        # 最後にログに書いた内部エラー(同じものは 1 回だけ書く)
        self.minute = None          # series.jsonl の今の 1 分
        self.series_out = []        # まだ書いていない series.jsonl の行
        self.lag_a, self.lag_c = [], []
        self.next_lag_at = LAG_FIRST
        self.dec_n = 0
        self.chat_snap = None       # チャットの読んだ位置(ChatFeed.to_json。state.json に一緒に残す)
        self.late = 0               # 渡したあとに来たチャットの数
        self.errors = 0
        self.ending = self.book_done = self.finished = False
        self.behind = 0.0
        self.last_pdt = None
        self.message = ""
        self.peaks_dirty = True

    # ---- 保存と再開
    def to_json(self):
        return {"v": 1, "recorder": self.rc, "recording": self.rec, "url": self.url, "first": self.first, "spec": self.spec, "args": self.args,
                "useChat": self.use_chat, "chatState": self.chat_state, "online": self.online.to_json(), "book": self.book.to_json(),
                "segSince": self.seg_since, "nextBox": self.next_box, "nextPush": self.next_push, "audio": self.audio, "lastAudio": self.last_audio,
                "chatBins": self.chat_bins, "chatWm": self.chat_wm, "raw": self.raw, "gaps": self.gaps, "gapCount": self.gap_count,
                "skipped": self.skipped, "minute": self.minute, "lagA": self.lag_a, "lagC": self.lag_c, "nextLagAt": self.next_lag_at,
                "decN": self.dec_n, "chat": self.chat_snap, "late": self.late, "errors": self.errors, "ending": self.ending,
                "bookDone": self.book_done, "finished": self.finished, "message": self.message,
                "fast": self.fast.to_json() if self.fast is not None else None, "mood": self.mood.to_json(), "moodShifts": self.mood_shifts,
                "nextScan": self.next_scan, "lateFrom": self.late_from}

    @classmethod
    def from_json(cls, folder, d, detect, grace=CHAT_GRACE):
        st = cls(folder, d["recorder"], d["recording"], d.get("url") or "", d["first"], dict(SPEC_DEFAULT, **(d.get("spec") or {})), detect,
                 d.get("useChat"), grace)
        st.args = dict(d.get("args") or st.args)
        st.online = excite.Online(use_chat=st.use_chat, **st.args).load(d["online"])
        st.book = excite.PeakBook.from_json(d["book"])
        # 先回りの計算(仮の候補)は state.json に無ければ作らない(本番と秒の数え始めがずれるため。その録画は本番の候補だけ)。変わり目は無ければここから数え始める
        st.fast = excite.Online(use_chat=False, **st.args).load(d["fast"]) if st.use_chat and isinstance(d.get("fast"), dict) else None
        st.mood = excite.MoodShift().load(d["mood"]) if isinstance(d.get("mood"), dict) else excite.MoodShift()
        st.mood_shifts = int(d.get("moodShifts") or 0)
        st.late_from = int(d["lateFrom"]) if isinstance(d.get("lateFrom"), int) else None
        st.chat_state = d.get("chatState") or st.chat_state
        st.seg_since, st.next_box, st.next_push = int(d["segSince"]), int(d["nextBox"]), int(d["nextPush"])
        st.next_scan = max(st.next_push, int(d.get("nextScan", st.next_push)))
        st.audio = {int(k): list(v) for k, v in (d.get("audio") or {}).items()}
        st.last_audio = d.get("lastAudio")
        st.chat_bins = {int(k): float(v) for k, v in (d.get("chatBins") or {}).items()}
        st.chat_wm = float(d.get("chatWm", -1.0))
        st.raw = {int(k): list(v) for k, v in (d.get("raw") or {}).items()}
        st.gaps = [list(x) for x in d.get("gaps") or []]
        st.gap_count = int(d.get("gapCount") or 0)
        st.skipped = [dict(x) for x in d.get("skipped") or []]
        st.minute = d.get("minute")
        st.lag_a, st.lag_c = list(d.get("lagA") or []), list(d.get("lagC") or [])
        st.next_lag_at = int(d.get("nextLagAt") or LAG_FIRST)
        st.dec_n = int(d.get("decN") or 0)
        st.chat_snap = d.get("chat")
        st.late, st.errors = int(d.get("late") or 0), int(d.get("errors") or 0)
        st.ending, st.book_done, st.finished = bool(d.get("ending")), bool(d.get("bookDone")), bool(d.get("finished"))
        st.message = str(d.get("message") or "")
        return st

    def set_detect(self, detect):
        """感度・1 時間の本数は配信の途中でも変えられる(これから確定する候補から)"""
        det = clean_detect(detect)
        self.book.thr, self.book.per_hour = excite.SENS[det["sens"]], det["perHour"]

    def disable_chat(self, why):
        """チャットを諦めた: Online を音だけにして続ける(過去の秒はそのまま)"""
        if not self.use_chat:
            return
        d = self.online.to_json()
        self.use_chat = False
        self.online = excite.Online(use_chat=False, **self.args).load(d)
        self.fast = None   # 本番がチャットを待たなくなったので、先回りは要らない(出ている仮の候補は本番が置き換えるか、外す)
        self.chat_state, self.message = "none", why
        self.chat_bins.clear()
        self.lag_a, self.lag_c = [], []

    # ---- チャット
    def add_chat(self, msgs):
        for ts, w in msgs:
            sec = ts - self.first
            if sec < 0:
                continue
            b = int(sec)
            if b < self.next_push:
                self.late += 1
                continue
            self.chat_bins[b] = self.chat_bins.get(b, 0.0) + w
            if sec > self.chat_wm:
                self.chat_wm = sec

    # ---- 音
    def batches(self, segs, ended, big):
        """測る単位に分ける: 同じセッションで受信時刻がつながっている BATCH_SEGS 本(遅れたら 60 秒分まで)。
        つながりが切れた所・録画の終わりでは短くても出す。-> [[セグメント…]](最後のまとまりが足りなければ入れない = 次の周期)"""
        out, cur = [], []
        for s in segs:
            if cur:
                p = cur[-1]
                joined = s["uri"].split("/")[0] == p["uri"].split("/")[0] and abs(s["t"] - (p["t"] + p["dur"])) <= SEG_TOL
                full = (sum(x["dur"] for x in cur) >= BIG_BATCH_SEC or len(cur) >= BIG_BATCH_SEGS) if big else len(cur) >= BATCH_SEGS
                if not joined or full:
                    out.append(cur)
                    cur = []
            cur.append(s)
        if cur and (ended or len(cur) >= BATCH_SEGS):
            out.append(cur)
        return out

    def skip_to(self, segs, last):
        """ライブ端から BEHIND_SKIP 秒より遅れた: 古い所を飛ばす(飛ばした区間は覚えて、配信が終わったら測り直す)。-> 飛ばしたセグメントの数。
        まだ何も測っていない録画(録画の途中で検出をオンにした・順番待ちのあと)は、飛ばした区間を作らない(録画の頭から今までを測り直すと
        数時間分になり、心拍が止まる。その前はアーカイブの解析で見る)"""
        target = last - SKIP_KEEP
        idx = next((i for i, s in enumerate(segs) if s["t"] >= target), len(segs))
        if idx == 0:
            return 0
        end_t = segs[idx]["t"] if idx < len(segs) else segs[-1]["t"] + segs[-1]["dur"]
        if self.next_box == 0 and self.seg_since == 0:
            self.late_from = int(round(end_t - self.first))
            self.message = "録画の途中(頭から %d 分)から測り始めました。それより前は配信中の候補を出しません(配信のあとのアーカイブの解析で見ます)" % (self.late_from // 60)
        else:
            self.skipped.append({"from": self.next_box, "to": int(round(end_t - self.first)), "since": self.seg_since, "until": self.seg_since + idx, "done": False})
            self.message = "遅れが %d 秒になったので、古い所(%d 秒分)を飛ばして追いつきました(配信が終わったら測り直します)" % (int(self.behind), int(end_t - segs[0]["t"]))
        self.seg_since += idx
        return idx

    def place(self, t0, total_dur, full, band):
        """測った 1 秒の値を箱へ。受信時刻からの位置と置く位置のずれを ANCHOR_TOL まで許し、超えたら合わせ直す(飛び = 欠けとして埋める・重なり = 捨てる)"""
        k = max(1, int(round(total_dur)))
        vals = [[f, b] for f, b in zip(full, band)][:k]
        while len(vals) < k:
            vals.append(list(vals[-1]) if vals else [-90.0, -90.0])
        exp = int(round(t0 - self.first))
        d = exp - self.next_box
        if d > FILL_MAX:   # 受信時刻が大きく飛んだ(壊れた時刻): 埋めずに続けて置く(何十時間分の箱を作らない)
            self.message = "録画の受信時刻が %d 時間以上飛んだので、続けて置きました" % (FILL_MAX // 3600)
            d = 0
        if d > ANCHOR_TOL:
            self.fill(exp, mark=d > GAP_MIN, first_val=vals[0])
        elif d < -ANCHOR_TOL:
            vals = vals[-d:]
        for v in vals:
            self.audio[self.next_box] = v
            self.next_box += 1
            self.last_audio = v

    def fill(self, upto, mark=True, first_val=None):
        """欠け: [next_box, upto) を直前の音で埋める(Online は連続した秒を前提にする。0 で埋めると「ふだん」が下がるので音は繰り返す)"""
        upto = min(int(upto), self.next_box + FILL_MAX)   # 上限(壊れた時刻で何十時間分を作らない)
        if upto <= self.next_box:
            return
        v = self.last_audio or first_val or [-90.0, -90.0]
        if mark:
            self.add_gap(self.next_box, upto)
        for b in range(self.next_box, upto):
            self.audio[b] = list(v)
        self.next_box = upto

    def add_gap(self, a, b):
        self.gap_count += 1
        if self.gaps and a <= self.gaps[-1][1]:
            self.gaps[-1][1] = max(self.gaps[-1][1], b)
        else:
            self.gaps.append([a, b])

    def near_gap(self, t):
        return any(a - GAP_MARGIN <= t < b + GAP_MARGIN for a, b in self.gaps)

    # ---- 点数
    def scan(self):
        """箱に入った音を秒の順に(チャットを待たない): 雰囲気の変わり目を見て(あとの MOOD_HOLD 秒は山のしきい値を MOOD_FACTOR 倍)、
        音だけの先回りの計算(self.fast)から仮の候補を出す。本番(push_ready)より先に通す(箱を取り出すのは本番)"""
        while self.next_scan < self.next_box:
            t = self.next_scan
            v = self.audio.get(t)
            self.next_scan = t + 1
            if v is None:
                continue
            if self.mood.push(v[0]):
                self.book.thr_scale(t, excite.MOOD_FACTOR, excite.MOOD_HOLD)
                self.mood_shifts += 1
            if self.fast is not None:
                for tt, total, parts in self.fast.push(v[0], v[1], 0.0):
                    if self.book.fast_push(tt, 0.0 if self.near_gap(tt) else total, parts["audio"]):
                        self.peaks_dirty = True

    def push_ready(self, now, ended=False):
        """音がそろい、チャットも(続きが来た・受信から grace 秒たった)そろった秒を Online へ -> 進めた秒数"""
        self.scan()
        n = 0
        while self.next_push < self.next_box:
            t = self.next_push
            if self.use_chat and not ended and not (self.chat_wm >= t + 1 or now >= self.first + t + self.grace):
                break
            full, band = self.audio.pop(t)
            act = self.chat_bins.pop(t, 0.0) if self.use_chat else 0.0
            self.raw[t] = [full, band, act]
            for tt, total, parts in self.online.push(full, band, act):
                self.emit(tt, total, parts)
            self.next_push = t + 1
            n += 1
        return n

    def emit(self, t, total, parts):
        """Online が確定した秒: 帳簿・series・遅れの推定へ"""
        full, band, act = self.raw.pop(t, [-90.0, -90.0, 0.0])
        level = full
        if self.book.push(t, 0.0 if self.near_gap(t) else total, {"audio": parts["audio"], "chat": parts["chat"]}, level):
            self.peaks_dirty = True
        self._series(t, parts, total, full, band, act)
        if self.gaps and self.gaps[0][1] + GAP_MARGIN < t - 60:
            del self.gaps[0]
        if self.use_chat and self.spec.get("lagAuto") is not False:
            self.lag_a.append(parts["audio"])
            self.lag_c.append(parts["chatRaw"])
            if len(self.lag_a) > LAG_SPAN + 120:
                del self.lag_a[:-LAG_SPAN]
                del self.lag_c[:-LAG_SPAN]
            if t >= LAG_FIRST and t >= self.next_lag_at:
                self.next_lag_at = t + LAG_EVERY
                self._update_lag()

    def _update_lag(self):
        est, _c = excite.estimate_lag(self.lag_a[-LAG_SPAN:], self.lag_c[-LAG_SPAN:])
        if est is None:
            return
        cur = self.online.lag
        new = max(cur - LAG_STEP, min(cur + LAG_STEP, int(est)))
        if new != cur:
            self.online.set_lag(new)
            self.peaks_dirty = True

    def _series(self, t, parts, total, full, band, act):
        m0 = (t // 60) * 60
        if self.minute is not None and self.minute["t0"] != m0:
            self.flush_minute()
        if self.minute is None:
            self.minute = {"t0": m0, "audio": [], "chat": [], "total": [], "full": [], "band": [], "act": []}
        mm = self.minute
        mm["audio"].append(round(parts["audio"], 2))
        mm["chat"].append(round(parts["chat"], 2))
        mm["total"].append(round(total, 2))
        mm["full"].append(round(full, 1))
        mm["band"].append(round(band, 1))
        mm["act"].append(round(act, 2))
        if t % 60 == 59:
            self.flush_minute()

    def flush_minute(self):
        if self.minute is not None and self.minute["total"]:
            self.series_out.append(self.minute)
        self.minute = None

    # ---- 書く
    def peaks_doc(self, now):
        ch = [{"seq": s, "id": i, "state": st} for s, i, st in self.book.changes]
        return {"v": 1, "recorder": self.rc, "recording": self.rec, "seq": self.book.seq, "decN": self.dec_n, "perHour": self.book.per_hour,
                "counts": {str(h): n for h, n in self.book.counts().items()}, "lag": self.online.lag, "chat": self.chat_state,
                "behindSec": round(max(0.0, self.behind), 1), "at": epoch_iso(now), "first": epoch_iso(self.first), "measuredSec": self.next_box,
                "scoredSec": self.online.next_out, "gaps": self.gap_count,
                "skipped": [{"from": s["from"], "to": s["to"], "done": s["done"], "capped": bool(s.get("capped"))} for s in self.skipped],
                "lateChat": self.late, "ended": self.finished, "message": self.message,
                "length": self.book.length, "preRatio": self.book.pre, "lengthFrom": self.spec.get("lengthFrom") or "studio",   # M10: 候補の長さの出どころ
                "moodShifts": self.mood_shifts, "provisional": self.fast is not None,   # 雰囲気の変わり目の数・仮の候補を出しているか
                "lateFrom": self.late_from,   # 録画の途中から測り始めた秒(それより前の候補は無い)
                "peaks": self.book.list(), "changes": ch}

    def save(self, now, peaks=True):
        os.makedirs(self.folder, exist_ok=True)
        if self.series_out:
            append_jsonl(os.path.join(self.folder, "series.jsonl"), self.series_out)
            self.series_out = []
        write_json(os.path.join(self.folder, "state.json"), self.to_json())
        if peaks:
            self.write_peaks(now)

    def write_peaks(self, now):
        write_json(os.path.join(self.folder, "peaks.json"), self.peaks_doc(now))
        self.peaks_dirty = False


def parse_segments(lst):
    """録画元の segmentList -> [{uri, dur, t(受信時刻 epoch)}](形の正しいものだけ。受信時刻が無ければ前からの続き)"""
    out = []
    for s in lst or []:
        if not isinstance(s, dict) or not SEG_URI_RE.match(str(s.get("uri") or "")):
            continue
        try:
            dur = float(s.get("dur"))
        except (TypeError, ValueError):
            continue
        t = iso_epoch(s.get("pdt"))
        if t is None:
            t = out[-1]["t"] + out[-1]["dur"] if out else None
        if t is None or not dur > 0:
            continue
        out.append({"uri": s["uri"], "dur": dur, "t": t})
    return out


# ---------------------------------------------------------------- ワーカー
class Worker:
    def __init__(self, config_path, clock=time.time, client_factory=None, measure_batch=None, launcher=None, log=None,
                 save_sec=SAVE_SEC, heart_sec=HEART_SEC, poll_sec=POLL_SEC, mem_limit_mb=MEM_LIMIT_MB, chat_backoff=CHAT_BACKOFF,
                 chat_grace=CHAT_GRACE, chat_max_per_hour=CHAT_MAX_PER_HOUR, tick_budget=TICK_BUDGET, parent=None, sleep=time.sleep, max_active=MAX_ACTIVE):
        """テストは clock・client_factory(rc) -> 録画元(get_json・get_bytes)・measure_batch(録画元, 録画, セグメント…) -> (full, band)・
        launcher(cmd, logf) -> yt-dlp のプロセス を偽物に替える(12 時間を早送りで回す)。max_active = 同時に測る録画の数"""
        # 差し替えられる口と間隔
        self.config_path = os.path.abspath(config_path)
        self.clock, self.sleep = clock, sleep
        self.client_factory = client_factory or (lambda rc: RecorderClient(rc))
        self._measure = measure_batch
        self.launcher = launcher
        self.log = log or self._print_log
        self.save_sec, self.heart_sec, self.poll_sec, self.mem_limit_mb = save_sec, heart_sec, poll_sec, mem_limit_mb
        self.chat_backoff, self.chat_grace, self.chat_max_per_hour = tuple(chat_backoff), chat_grace, chat_max_per_hour
        self.tick_budget, self.parent = tick_budget, parent
        self.max_active = max(1, int(max_active))
        # 受け持っている録画・チャット
        self.cfg, self.cfg_key, self.cfg_checked = {}, None, -1e18
        self.recs, self.feeds, self.done = {}, {}, set()   # (録画元, 録画) -> RecState・動画の id -> ChatFeed・締めた録画
        self.queued, self.queued_msgs = [], {}             # 順番待ちの録画(心拍に出す)・最後に peaks.json に書いた順番待ちの文と時刻
        self.dec_keys = {}                                 # (録画元, 録画) -> 最後に当てた decisions.json の (更新の時刻, 大きさ, 候補の通し番号)
        self.job = tools.KillJob()
        # 心拍・ログ
        self.started = clock()
        self.saved_at = self.heart_at = self.mem_at = -1e18
        self.mem = 0.0
        self.error = ""
        self._errs = {}           # 録画のない所(受け持つ前・チャット)の、最後にログに書いた内部エラー
        self._log_full = False
        self.stop_flag = False
        self.load_config(force=True)

    def _print_log(self, m):
        """標準出力(入口が logs/excite.log につなぐ)へ 1 行。そのファイルが LOG_LIMIT を超えたら、それより先は書かない(起動のときだけでなく書く前に見る。
        入口が次に起動するときに回す)"""
        if self._log_full:
            return
        try:
            size = os.fstat(sys.stdout.fileno()).st_size
        except (OSError, ValueError, AttributeError):
            size = 0
        if size > LOG_LIMIT:
            self._log_full = True
            m = "ログが %d MB を超えたので、ここから先は書きません(ホームが次にワーカーを起動するときに回します)" % (LOG_LIMIT // 1048576)
        try:
            print("%s %s" % (time.strftime("%Y-%m-%d %H:%M:%S"), m), flush=True)
        except (OSError, ValueError):
            pass

    # ---- 設定
    @property
    def dir(self):
        return self.cfg.get("dir") or os.path.dirname(self.config_path)

    def load_config(self, force=False):
        now = self.clock()
        if not force and now - self.cfg_checked < CONFIG_CHECK_SEC:
            return False
        self.cfg_checked = now
        try:
            st = os.stat(self.config_path)
            key = (st.st_mtime_ns, st.st_size)
        except OSError:
            key = None
        if key == self.cfg_key and not force:
            return False
        d = fsio.read_json_or(self.config_path, None, 1024 * 1024, kind=dict) or {}
        self.cfg_key = key
        rcs = [r for r in d.get("recorders") or [] if isinstance(r, dict) and ID_RE.match(str(r.get("id") or "")) and isinstance(r.get("url"), str)]
        spec, src = dict(SPEC_DEFAULT), d.get("spec") if isinstance(d.get("spec"), dict) else {}
        for k, dv in SPEC_DEFAULT.items():
            v = src.get(k)
            if isinstance(dv, bool):
                if isinstance(v, bool):
                    spec[k] = v
            elif schemas.is_num(v):
                spec[k] = float(v)
        self.cfg = {"dir": d.get("dir") if isinstance(d.get("dir"), str) and d.get("dir") else os.path.dirname(self.config_path), "recorders": rcs,
                    "detect": clean_detect(d.get("detect")), "spec": spec, "ffmpeg": d.get("ffmpeg") or None, "ytdlp": d.get("ytdlp") or None,
                    "chatLimitBytes": int(d.get("chatLimitBytes") or CHAT_LIMIT), "chatStallSec": float(d.get("chatStallSec") or CHAT_STALL),
                    "lengthHint": clean_hint(d.get("lengthHint")),         # M10(入口が書く。無ければスタジオの設定の長さ)
                    "provisional": d.get("provisional") is not False,      # 仮の候補(既定オン。false = 本番の候補だけ)
                    "detectAll": d.get("detectAll") is not False,         # false = 友人の依頼の録画(requests)だけ測る(ホームの検出がオフのとき。2-15)
                    "requests": clean_requests(d.get("requests"))}        # 友人の依頼の録画ごとの設定(感度・枠・長さ)
        for st in self.recs.values():
            st.set_detect(self._detect_for(st.rc, st.rec))
        return True

    # ---- 動かす
    def run(self):
        """常駐: 周期ごとに tick。-> 終了コード(0・メモリ超え EXIT_MEM・ほかのワーカーが動いている EXIT_LOCKED)"""
        lock = take_lock(os.path.join(self.dir, "worker.lock"))
        if lock is None:
            self.log("盛り上がりの検出: ほかのワーカーが動いているので終わります")
            return EXIT_LOCKED
        code = 0
        try:
            self.log("盛り上がりの検出のワーカーを始めました(pid %d・%s)" % (os.getpid(), self.dir))
            while not self.stop_flag:
                t0 = self.clock()
                try:
                    self.tick()
                except Exception as e:   # 1 回の不具合で止めない(心拍に出す。同じエラーが続く間は 1 回だけログ)
                    self._internal("tick", e)
                    self.heartbeat(self.clock(), force=True)
                if self.mem > self.mem_limit_mb:
                    self.log("盛り上がりの検出: メモリが %d MB を超えたので、状態を保存して終わります(ホームが起動し直します)" % self.mem_limit_mb)
                    code = EXIT_MEM
                    break
                if not pid_alive(self.parent):
                    self.log("盛り上がりの検出: ホームが終わったので終わります")
                    break
                self.sleep(max(0.5, self.poll_sec - (self.clock() - t0)))
        finally:
            self.close()
            lock.close()
        return code

    def close(self):
        """状態を保存して、子(yt-dlp)を止める(生のチャットは残す = 次の起動で続きを読む)"""
        now = self.clock()
        for st in list(self.recs.values()):
            self._save_rec(st, now)
        for f in self.feeds.values():
            f.close(delete=False)
        self.heartbeat(now, force=True, message="止まりました")
        self.job.close()

    def tick(self):
        """1 回の周期: 設定 → チャット → 録画元ごとの録画(同時に測るのは max_active 本まで)→ 人の決定 → 保存 → 心拍"""
        self.error = ""
        self.load_config()
        now = self.clock()
        deadline = now + self.tick_budget
        self._chat_step(now)
        seen = self._recordings_step(now, deadline)
        for key in [k for k in self.recs if k not in seen]:   # 録画元の一覧から消えた・録画元を外した: 保存して手放す
            self._save_rec(self.recs[key], now)
            self._release(key)
        self._apply_decisions()
        now = self.clock()
        if now - self.saved_at >= self.save_sec:
            self.saved_at = now
            for st in self.recs.values():
                self._save_rec(st, now)
        fresh = now - self.heart_at >= self.heart_sec   # 心拍と同じ間隔で、遅れ・チャットの状態も peaks.json に出し直す
        for st in self.recs.values():
            if st.peaks_dirty or fresh:
                try:
                    st.write_peaks(now)
                except (OSError, ValueError) as e:
                    self.error = "候補を書けませんでした: %s" % tools.why(e)
        if now - self.mem_at >= MEM_CHECK_SEC:
            self.mem_at = now
            self.mem = tools.process_memory_mb() or 0.0
        self.heartbeat(now)

    def _save_rec(self, st, now):
        if st.use_chat and st.vid in self.feeds:
            st.chat_snap = self.feeds[st.vid].to_json()
        try:
            st.save(now)
        except (OSError, ValueError) as e:
            self.error = "状態を保存できませんでした: %s" % tools.why(e)

    def _release(self, key):
        st = self.recs.pop(key, None)
        if st is None or not st.vid:
            return
        f = self.feeds.get(st.vid)
        if f is not None:
            f.subs.discard(key)
            if not f.subs:
                f.close(delete=st.finished)
                del self.feeds[st.vid]

    # ---- チャット
    def _feed(self, st):
        f = self.feeds.get(st.vid)
        if f is None:
            f = ChatFeed(st.vid, st.url, os.path.join(self.dir, "chat"), self.cfg["ytdlp"], launcher=self.launcher, job=self.job, log=self.log,
                         limit=self.cfg["chatLimitBytes"], stall=self.cfg["chatStallSec"], backoff=self.chat_backoff, max_per_hour=self.chat_max_per_hour)
            if isinstance(st.chat_snap, dict):
                f.load(st.chat_snap)
            self.feeds[st.vid] = f
        f.subs.add((st.rc, st.rec))
        return f

    def _chat_step(self, now):
        for f in list(self.feeds.values()):
            try:
                self._feed_step(f, now)
            except Exception as e:   # チャット 1 本の不具合で周期全体を止めない
                self._internal("chat/" + f.vid, e)

    def _feed_step(self, f, now):
        """チャット 1 本: 起動・見張り・読む → 受け持つ録画の箱へ(諦めたら録画を音だけにする)"""
        subs = [self.recs[k] for k in f.subs if k in self.recs]
        msgs = f.step(now, any(not s.ending for s in subs))
        for s in subs:
            if f.state == "none":
                s.disable_chat(f.reason)
                continue
            s.add_chat(msgs)
            s.chat_state = f.view_state()

    # ---- 録画
    def _recordings_step(self, now, deadline):
        """録画元ごとの一覧 → 受け持っている録画を進める → 空きがあれば新しい録画を受け持つ(古い順。続きの state.json がある録画を先に)。
        同時に測るのは max_active 本まで(0-10-4)。空きが無い録画は「順番待ち」(peaks.json の message・queued と worker.json の queued)で、
        受け持っている録画の検出が終わったら次の周期で始める。-> 見えた録画の鍵(つながらない録画元は、今持っている録画をそのまま)"""
        seen, items = set(), []
        for rc in self.cfg["recorders"]:
            client = self.client_factory(rc)
            code, d = client.get_json("/live/list")
            if code != 200 or not isinstance(d, dict):
                seen |= {k for k in self.recs if k[0] == rc["id"]}
                continue
            for r in d.get("recordings") or []:
                if not isinstance(r, dict) or not REC_RE.match(str(r.get("id") or "")):
                    continue
                key = (rc["id"], r["id"])
                seen.add(key)
                if key not in self.done:
                    items.append((rc, client, r, key))
        for x in items:   # ホームの検出をオフにした(detectAll false): 友人の依頼の録画のほかは、保存して手放す(tick。state.json は残す = オンに戻せば続きから)
            if x[3] in self.recs and not self._allowed(x[3][0], x[3][1]):
                seen.discard(x[3])
        held = [x for x in items if x[3] in self.recs and x[3] in seen]
        new = sorted((x for x in items if x[3] not in self.recs and self._wanted(x[0], x[2])), key=self._new_order)
        wait = []
        for rc, client, r, key in held + new:
            st = self.recs.get(key)
            if st is None:
                if len(self.recs) >= self.max_active:   # 空きが無い(受け持っている録画は、録画元につながらなくても枠を持ったまま)
                    wait.append((rc, r))
                    continue
                try:
                    st = self._open(rc, r)
                except Exception as e:   # 1 本の不具合で周期全体を止めない(同じエラーは 1 回だけログ)
                    self._internal(key, e)
                    continue
                if st is None:
                    continue
            try:
                self._rec_step(st, client, now, deadline)
            except RecorderDown:
                st.message = "録画元につながりません(次の周期でやり直します)"
            except Exception as e:   # 1 本の不具合で周期全体を止めない(ほかの録画は進める。同じエラーは 1 回だけログ)
                st.errors += 1
                st.message = self._internal(key, e, st)
            if st.finished:
                self._save_rec(st, now)
                self.done.add(key)
                self._release(key)
        self._write_queued(wait, now)
        return seen

    def _internal(self, key, e, st=None):
        """録画 1 本・チャット 1 本の思わぬ例外 -> 文(心拍の error・その録画の message)。ログ(traceback つき)は同じ文が続く間は 1 回だけ"""
        txt = "内部エラー: %r" % (e,)
        self.error = txt
        last = st.last_error if st is not None else self._errs.get(key)
        if last != txt:
            self.log("盛り上がりの検出: %s で %s\n%s" % ("/".join(str(k) for k in key) if isinstance(key, tuple) else key, txt, traceback.format_exc()))
        if st is not None:
            st.last_error = txt
        else:
            self._errs[key] = txt
        return txt

    def _folder(self, rc, r):
        return os.path.join(self.dir, rc["id"], r["id"])

    def _was_queued(self, folder):
        """順番待ちにした録画か(peaks.json の queued。順番待ちのうちに配信が終わっても、あとで音だけ測る)"""
        p = os.path.join(folder, "peaks.json")
        return os.path.isfile(p) and (fsio.read_json_or(p, None, 1024 * 1024, kind=dict) or {}).get("queued") is True

    def _request_for(self, rc_id, rec):
        """友人のライブ配信の依頼の録画なら、その設定(2-15)。無ければ None"""
        return self.cfg.get("requests", {}).get("%s/%s" % (rc_id, rec))

    def _detect_for(self, rc_id, rec):
        """録画ごとの感度と枠: 友人の依頼の録画はその設定、ほかはホームの設定"""
        req = self._request_for(rc_id, rec)
        return {"sens": req["sens"], "perHour": req["perHour"]} if req else self.cfg["detect"]

    def _allowed(self, rc_id, rec):
        """測ってよい録画か: ホームの検出がオン(detectAll)か、友人の依頼の録画(requests。2-15)"""
        return self.cfg.get("detectAll", True) or self._request_for(rc_id, rec) is not None

    def _wanted(self, rc, r):
        """受け持つ録画か: 録画中で firstPdt がある・続きの state.json がある・順番待ちにしていた。
        ホームの検出がオフ(detectAll false)のときは、友人の依頼の録画(requests)だけ"""
        if not self._allowed(rc["id"], r["id"]):
            return False
        folder = self._folder(rc, r)
        return (r.get("active") is True and iso_epoch(r.get("firstPdt")) is not None) or os.path.isfile(os.path.join(folder, "state.json")) \
            or self._was_queued(folder)

    def _new_order(self, x):
        """新しく受け持つ順: 続きの state.json がある録画(起動し直す前に測っていた)→ 録画の頭(firstPdt)が古い順 → id"""
        rc, _client, r, _key = x
        first = iso_epoch(r.get("firstPdt"))
        return (0 if os.path.isfile(os.path.join(self._folder(rc, r), "state.json")) else 1, first if first is not None else float("inf"), r["id"])

    def _write_queued(self, wait, now):
        """順番待ちの録画の peaks.json に文と queued を出す(候補はまだ無い。前に測っていた録画なら候補はそのまま)。文が変わったとき・QUEUED_EVERY ごと"""
        self.queued, keep = [], {}
        for i, (rc, r) in enumerate(wait):
            key = (rc["id"], r["id"])
            msg = ("同時に測るのは %d 本までなので、順番待ちです(%d 番目)。前の録画の検出が終わったら、そのときのライブ端から測ります"
                   "(それより前は配信中の候補を出しません。順番待ちのうちに配信が終わったら、あとで音だけで測ります)" % (self.max_active, i + 1))
            self.queued.append({"recorder": rc["id"], "id": r["id"], "pos": i + 1})
            prev = self.queued_msgs.get(key)
            keep[key] = prev
            if prev and prev[0] == msg and now - prev[1] < QUEUED_EVERY:
                continue
            folder = self._folder(rc, r)
            doc = fsio.read_json_or(os.path.join(folder, "peaks.json"), None, STATE_MAX, kind=dict) if os.path.isfile(os.path.join(folder, "state.json")) else None
            if not doc:
                first, last = iso_epoch(r.get("firstPdt")), iso_epoch(r.get("lastPdt"))
                doc = {"v": 1, "recorder": rc["id"], "recording": r["id"], "seq": 0, "decN": 0, "perHour": self._detect_for(rc["id"], r["id"])["perHour"], "counts": {},
                       "lag": None, "chat": "off", "behindSec": round(max(0.0, last - first), 1) if first is not None and last is not None else 0.0,
                       "first": epoch_iso(first) if first is not None else None, "measuredSec": 0, "scoredSec": 0, "gaps": 0, "skipped": [],
                       "lateChat": 0, "ended": False, "peaks": [], "changes": []}
            doc.update(message=msg, queued=True, queuePos=i + 1, at=epoch_iso(now))
            try:
                write_json(os.path.join(folder, "peaks.json"), doc)
                keep[key] = (msg, now)
            except (OSError, ValueError) as e:
                self.error = "順番待ちの文を書けませんでした: %s" % tools.why(e)
        self.queued_msgs = keep

    def _open(self, rc, r):
        """録画を受け持つ: state.json があれば続きから。録画中で firstPdt があれば新しく。終わった録画は state.json があって済んでいないとき・
        順番待ちのうちに終わったとき(音だけ。チャットのリプレイは読まない)だけ"""
        folder = self._folder(rc, r)
        key = (rc["id"], r["id"])
        d = fsio.read_json_or(os.path.join(folder, "state.json"), None, STATE_MAX, kind=dict)
        if d is not None:
            try:
                st = RecState.from_json(folder, d, self._detect_for(rc["id"], r["id"]), self.chat_grace)
            except Exception as e:   # 形の違う・壊れた state.json(版の違いを含む): 初めから
                self.log("盛り上がりの検出: %s の状態を読めないので、初めからやり直します(%r)" % (r["id"], e))
                st = None
            if st is not None and st.finished:
                self.done.add(key)
                return None
        else:
            st = None
        if st is None:
            first = iso_epoch(r.get("firstPdt"))
            queued = self._was_queued(folder)
            live = r.get("active") is True
            if (not live and not queued) or first is None:
                return None
            ytdlp = self.cfg["ytdlp"]
            url = str(r.get("url") or "")
            spec = spec_with_hint(self.cfg["spec"], self.cfg.get("lengthHint"))   # M10: 人が選んだ長さの目安(足りなければスタジオの設定)
            req = self._request_for(rc["id"], r["id"])
            if req and req.get("length"):   # 友人の依頼の録画: 長さは依頼の設定(2-15)
                spec = dict(spec, length=req["length"], lengthFrom="friend", lengthNote="友人の依頼の設定")
            st = RecState(folder, rc["id"], r["id"], url, first, spec, self._detect_for(rc["id"], r["id"]), bool(ytdlp and video_id(url, r["id"])) and live,
                          self.chat_grace, provisional=self.cfg.get("provisional", True))
            self.log("盛り上がりの検出: %s を受け持ちます(チャット %s・候補の長さ %g 秒 = %s%s)" % (
                r["id"], "あり" if st.use_chat else "なし", st.book.length, spec.get("lengthNote") or "スタジオの解析の設定",
                "・順番待ちのあと" if queued else ""))
            try:   # すぐに state.json を置く(順番待ちの印 = peaks.json の queued は最初の候補の書き出しで消えるので、落ちても続きから受け持てるように)
                st.save(self.clock(), peaks=False)
            except (OSError, ValueError):
                pass
        elif not self.cfg.get("provisional", True):
            st.fast = None   # 仮の候補を止めた(config の provisional: false)。出ている仮の候補は本番が置き換えるか外す
        st.set_detect(self._detect_for(rc["id"], r["id"]))   # 友人の依頼の録画は依頼の感度・枠(2-15。ホームの設定で上書きしない)
        self.recs[key] = st
        if st.use_chat:   # 受け持った周期のうちにチャットを読む(続きから: 止まっていた間の秒を、チャットを読む前に grace で進めない)
            self._feed_step(self._feed(st), self.clock())
        return st

    def _rec_step(self, st, client, now, deadline):
        """録画 1 本: 新しいセグメントを測る → そろった秒を点数へ → 終わっていれば締める"""
        code, s = client.get_json("/live/%s/status?since=%d" % (st.rec, st.seg_since))
        if code is None:
            raise RecorderDown()
        if code != 200 or not isinstance(s, dict):
            st.message = "録画元から録画の状態を読めませんでした(HTTP %s)" % code
            return
        segs = parse_segments(s.get("segmentList"))
        ended = s.get("active") is not True
        last = iso_epoch(s.get("lastPdt"))
        st.last_pdt = last
        st.behind = (last - segs[0]["t"]) if segs and last is not None else 0.0   # まだ測っていない一番古いセグメントからライブ端まで
        if ended and not st.ending:
            st.ending = True
        i = 0
        if not ended and st.behind > BEHIND_SKIP:
            i = st.skip_to(segs, last)
        big = i < len(segs) and last is not None and last - segs[i]["t"] > BEHIND_BIG
        for batch in st.batches(segs[i:], ended or len(segs) >= 5000, big):
            if self.clock() > deadline:
                break
            if not self._measure_one(st, client, batch):
                break
        st.behind = (last - (st.first + st.next_box)) if last is not None else 0.0
        st.push_ready(self.clock(), ended)
        if ended and len(segs) < 5000 and st.seg_since >= int(s.get("since") or 0) + len(segs) and self.clock() <= deadline:
            self._finish(st, client, deadline)

    def _measure_one(self, st, client, batch):
        """1 回分を測って箱へ -> 続けてよいか(ffmpeg が無い・録画元が落ちたら False)"""
        dur = sum(x["dur"] for x in batch)
        try:
            full, band = self.measure_batch(client, st.rec, batch)
            st.place(batch[0]["t"], dur, full, band)
        except MeasureError as e:   # その秒は欠けとして埋めて先へ
            st.errors += 1
            st.message = str(e)
            st.fill(int(round(batch[0]["t"] - st.first + dur)), mark=True)
        except NoTool as e:
            self.error = str(e)
            return False
        st.seg_since += len(batch)
        return True

    def measure_batch(self, client, rec, batch):
        """セグメントを録画元から取って 1 つのファイルにつなぎ、ffmpeg 1 回で測る(テストは差し替える)"""
        if self._measure is not None:
            return self._measure(client, rec, batch)
        wdir = os.path.join(self.dir, "work")
        os.makedirs(wdir, exist_ok=True)
        path = os.path.join(wdir, "batch.ts")
        try:
            with open(path, "wb") as f:
                for s in batch:
                    code, body = client.get_bytes("/live/%s/%s" % (rec, s["uri"]))
                    if code is None:
                        raise RecorderDown()
                    if code != 200 or not body:
                        raise MeasureError("録画のデータ %s を取れませんでした(HTTP %s)" % (s["uri"], code))
                    f.write(body)
            return measure_levels(self.cfg["ffmpeg"], path, wdir, job=self.job)
        finally:
            fsio.unlink_quiet(path)

    def _finish(self, st, client, deadline):
        """配信が終わった録画を締める: 帳簿の確定 → 飛ばした区間の測り直し(音だけ)→ 済み"""
        if not st.book_done:
            st.push_ready(self.clock(), True)
            if st.book.finish():
                st.peaks_dirty = True
            st.flush_minute()
            st.book_done = True
        for sk in st.skipped:
            if sk.get("done"):
                continue
            if self.clock() > deadline or not self._remeasure(st, client, sk, deadline):   # 時間切れ: 進みを残して次の周期で続き
                self._save_rec(st, self.clock())
                return
        st.finished = True
        st.message = st.message if st.skipped else ""
        st.peaks_dirty = True
        self.log("盛り上がりの検出: %s が終わりました(候補 %d・欠け %d)" % (st.rec, len(st.book.order), st.gap_count))

    def _remeasure(self, st, client, sk, deadline):
        """飛ばした区間の音を、遅れたときと同じまとまり(RecState.batches の big = 同じセッションでつながった BIG_BATCH_SEC 分)ごとに測り直して
        skipped.jsonl へ(0-10-6。候補は作り直さない)。まとまりごとに 1 行足し、進み(sk の pos = 測り終えたセグメントの数・sec = 測った秒)を残して
        心拍を書く。時間切れなら戻る(次の周期で pos から)。1 つの区間で測るのは REMEASURE_MAX_SEC まで(超えたら capped)。-> 済んだか"""
        total = max(0, sk["until"] - sk["since"])
        pos = int(sk.get("pos") or 0)
        code, s = client.get_json("/live/%s/status?since=%d" % (st.rec, sk["since"] + pos))
        if code is None:
            return False   # 録画元につながらない: 次の周期で
        segs = parse_segments((s or {}).get("segmentList") if code == 200 and isinstance(s, dict) else [])[:max(0, total - pos)]
        os.makedirs(st.folder, exist_ok=True)
        for cur in st.batches(segs, True, True):
            if float(sk.get("sec") or 0.0) >= REMEASURE_MAX_SEC:
                sk["capped"] = True
                break
            t0 = int(round(cur[0]["t"] - st.first))
            try:
                full, band = self.measure_batch(client, st.rec, cur)
                row = {"t0": t0, "full": [round(v, 1) for v in full], "band": [round(v, 1) for v in band]}
            except (MeasureError, NoTool, RecorderDown) as e:
                row = {"t0": t0, "error": str(e)[:160] or e.__class__.__name__}
            append_jsonl(os.path.join(st.folder, "skipped.jsonl"), [row])
            pos += len(cur)
            sk["pos"], sk["sec"] = pos, round(float(sk.get("sec") or 0.0) + sum(y["dur"] for y in cur), 1)
            self.heartbeat(self.clock(), force=True)   # 長い測り直しの間も心拍を止めない(入口が 120 秒で起動し直す)
            if pos < total and self.clock() > deadline:
                return False
        sk["done"] = True   # 測り終えた・上限・録画元にもう無い(消えた)
        return True

    # ---- 人の決定(decisions.json。入口が書く)
    def _apply_decisions(self):
        for key, st in self.recs.items():
            try:
                self._apply_decisions_one(key, st)
            except Exception as e:   # 1 本の不具合で周期全体を止めない
                st.message = self._internal(key, e, st)

    def _apply_decisions_one(self, key, st):
        """decisions.json の新しい決定を帳簿に当てる。まだ帳簿に無い候補(起動し直して、最後の保存より後に確定した候補がまだ出ていない)の決定に
        当たったら、そこで止めて decN を進めない(候補が出たら当てる。進めると人の決定が消える)。id の番号がもう使われた番号なのに無い・
        今の番号から PEAK_AHEAD 以上先 = 形の違う決定は飛ばす(いつまでも止めない)"""
        p = os.path.join(st.folder, "decisions.json")
        try:
            m = os.stat(p)
            k = (m.st_mtime_ns, m.st_size, st.book.n_ids)
        except OSError:
            return
        if self.dec_keys.get(key) == k:
            return
        d = fsio.read_json_or(p, None, 8 * 1024 * 1024, kind=dict) or {}
        items = sorted((x for x in d.get("items") or [] if isinstance(x, dict) and isinstance(x.get("n"), int) and x["n"] > st.dec_n),
                       key=lambda x: x["n"])
        for x in items:
            pid = str(x.get("id") or "")
            if pid not in st.book.peaks:
                mm = PEAK_ID_RE.match(pid)
                if mm and st.book.n_ids <= int(mm.group(1)) < st.book.n_ids + PEAK_AHEAD:
                    break   # まだ出ていない候補(すぐ先の番号): 出てから当てる
            else:
                st.book.decide(pid, x.get("state"), origin=x.get("origin") or "manual", mark_id=x.get("markId"), job_id=x.get("jobId"))
                st.peaks_dirty = True
            st.dec_n = x["n"]
        self.dec_keys[key] = k

    # ---- 心拍
    def heartbeat(self, now, force=False, message=None):
        if not force and now - self.heart_at < self.heart_sec:
            return
        self.heart_at = now
        active = [st for st in self.recs.values() if not st.finished]
        if message is None:
            message = "%d 本の録画を見ています" % len(active) if active else "録画中の配信はありません"
            if self.queued:
                message += "(%d 本は順番待ち。同時に測るのは %d 本まで)" % (len(self.queued), self.max_active)
        doc = {"v": 1, "version": WORKER_VERSION, "pid": os.getpid(), "at": epoch_iso(now), "started": epoch_iso(self.started),
               "behindSec": round(max([st.behind for st in active] or [0.0]), 1), "memMB": round(self.mem, 1),
               "chatRestarts": sum(f.total_restarts for f in self.feeds.values()),
               "recordings": [{"recorder": st.rc, "id": st.rec, "behindSec": round(max(0.0, st.behind), 1), "chat": st.chat_state} for st in active],
               "queued": list(self.queued), "maxActive": self.max_active, "message": message, "error": self.error}
        try:
            write_json(os.path.join(self.dir, "worker.json"), doc)
        except (OSError, ValueError):
            pass


def main(argv=None):
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="replace")
        except Exception:
            pass
    ap = argparse.ArgumentParser(prog="live_excite_worker.py", description="配信中の盛り上がりの検出(線 D の L2)")
    ap.add_argument("--config", required=True)
    ap.add_argument("--parent", type=int, default=0, help="入口の pid(終わったらこのワーカーも終わる)")
    a = ap.parse_args(sys.argv[1:] if argv is None else argv)
    w = Worker(a.config, parent=a.parent or None)

    def stop(_sig, _frame):
        w.stop_flag = True
    for name in ("SIGINT", "SIGTERM", "SIGBREAK"):
        sig = getattr(signal, name, None)
        if sig is not None:
            try:
                signal.signal(sig, stop)
            except (OSError, ValueError):
                pass
    return w.run()


if __name__ == "__main__":
    sys.exit(main() or 0)
