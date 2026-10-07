# -*- coding: utf-8 -*-
"""配信中の盛り上がりの検出のワーカー(線 D の L2。plan/line-d-detect.md・plan/line-d-live-clipping.md の 0-10)。入口(src/home/live_detect.py)が起動する子プロセス。

    py -3.10 -u src/home/live_excite_worker.py --config <入口の作業データ>/live/excite/config.json [--parent <入口の pid>]

録画中の全部の録画を 1 つのワーカーで受け持つ(0-10-4)。入口とは**ファイルだけ**で話す(stdin/stdout の常駐の約束は作らない。仮決め (bk)):
  config.json    入口が書く。{"v":1, "dir", "recorders": [{"id","url","token"}], "detect": {"sens","perHour"}, "spec": {"length","preRatio","lag","lagAuto",
                 "wAudio","wChat","headSec"}, "ffmpeg", "ytdlp", "chatLimitBytes", "chatStallSec"}。30 秒ごとに更新の時刻を見て読み直す
  <録画元>/<録画>/ の state.json(続きから再開する状態)・series.jsonl(1 分 1 行)・peaks.json(候補の正本)・skipped.jsonl(飛ばした区間の測り直し)はここが書く。
  decisions.json(人の採用・見送り・自動の採用)は入口が書き、ここは読んで PeakBook に当てるだけ。worker.json(心拍)もここが書く

流れ(周期 POLL_SEC):
  1. 録画元の GET /live/list → 録画中(active)で firstPdt のある録画ごとに状態(state.json があれば続きから)
  2. GET /live/<録画>/status?since=N で新しいセグメント → 本体(GET /live/<録画>/<uri>。合言葉 Bearer)→ **3 本(約 12 秒)ずつ ffmpeg 1 回**で
     1 秒の RMS(dB)を全帯域と 2kHz 超の 2 系列(src/studio/analyze.py の audio_levels と同じフィルター。asplit で 1 回に)
  3. セグメントの受信時刻(pdt)で「録画の頭(firstPdt)からの秒」の 1 秒の箱へ(数で数えない)。欠けは音を直前の値で埋めて欠けとして覚える
  4. チャット(yt-dlp の live_chat。配信 1 本に 1 つ)を末尾から読み、timestampUsec(絶対時刻)で 1 秒の箱へ。重みは excite.message_weight
  5. 音とチャットがそろった秒から excite.Online → excite.PeakBook。欠け ±GAP_MARGIN 秒は帳簿に 0 を渡す(山を作らない)
  6. 遅れ(チャットの)は 600 秒を超えたら 300 秒ごとに直近 1800 秒で excite.estimate_lag(1 回 ±3 秒まで)
  7. ライブ端から 120 秒超遅れたら 60 秒分ずつまとめ、600 秒超なら古い所を飛ばす(配信が終わったら飛ばした区間の音だけ測り直す)
  8. 60 秒ごとに state.json・series.jsonl、候補が変わったら peaks.json、30 秒ごとに worker.json。メモリが 512MB を超えたら状態を保存して終了コード 3
配信が終わった録画: 残りを測る → 上り中・終わり待ちの候補を確定(PeakBook.finish)→ 飛ばした区間の測り直し → 最後の保存 → yt-dlp を止めて生のチャットを消す。そのあとは触らない。

標準ライブラリだけ(numpy は使わない)。優先度は「通常より下」(入口が起動するときに指定。子の ffmpeg・yt-dlp も)。ffmpeg・yt-dlp は KillJob に入れる
(ワーカーが落ちたら子も消える)。重い処理の順番(SLOTS)は取らない(短い ffmpeg 1 回ずつ。0-10-4)。
テストは「音を測る」(measure_batch)・「録画元から取る」(client_factory)・「時計」(clock)・yt-dlp の起動(launcher)を差し替えて、12 時間を早送りで回す
(src/home/tests/test_live_detect.py)。
"""
import argparse
import datetime
import glob
import http.client
import json
import os
import re
import signal
import subprocess
import sys
import time
import traceback
import urllib.parse

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
if ROOT not in sys.path:
    sys.path.append(ROOT)
from ytt_core import excite, fsio, tools  # noqa: E402

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
FFMPEG_TIMEOUT = 120.0
EXIT_MEM, EXIT_LOCKED = 3, 4
STATE_MAX = 64 * 1024 * 1024
SPEC_DEFAULT = {"length": 45.0, "preRatio": excite.PRE_RATIO_DEFAULT, "lag": 8.0, "lagAuto": True, "wAudio": 1.0, "wChat": 1.0, "headSec": 180.0}
ID_RE = re.compile(r"^[a-z][a-z0-9-]{0,15}\Z")                       # 録画元の id(src/home/live_export.py の ID_RE と同じ)
REC_RE = re.compile(r"^\d{8}-\d{6}(?:-[A-Za-z0-9_-]{1,24})?\Z")      # 録画の id(同じく REC_RE)
SEG_URI_RE = re.compile(r"^session_\d{3,6}/seg_\d{6,9}\.ts\Z")
YT_ID_RE = re.compile(r"(?:[?&]v=|youtu\.be/|/live/)([A-Za-z0-9_-]{11})(?=[?&#/]|\Z)")
VID_RE = re.compile(r"^[A-Za-z0-9_-]{11}\Z")
LEVEL_KEY = "lavfi.astats.Overall.RMS_level="
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
def iso_epoch(s):
    """UTC の時刻の文字列("…Z"・ミリ秒あり/なし)→ epoch 秒。読めなければ None"""
    if not isinstance(s, str) or len(s) > 40:
        return None
    t = s.strip().replace("+00:00", "Z")
    fmt = "%Y-%m-%dT%H:%M:%S.%fZ" if "." in t else "%Y-%m-%dT%H:%M:%SZ"
    try:
        return datetime.datetime.strptime(t, fmt).replace(tzinfo=datetime.timezone.utc).timestamp()
    except ValueError:
        return None


def iso_now(t):
    return datetime.datetime.fromtimestamp(t, datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def video_id(url, rec_id=""):
    """YouTube の動画の id(11 文字)。URL に無ければ録画の id の後ろ(録画の部品が URL から付けたもの)。分からなければ "" """
    m = YT_ID_RE.search(url or "")
    if m:
        return m.group(1)
    tail = (rec_id or "").split("-", 2)[2:]
    return tail[0] if tail and VID_RE.match(tail[0]) else ""


def child_flags():
    """ffmpeg・yt-dlp の creationflags: 窓を出さない・通常より下の優先度(src/home/live_export.py の low_flags と同じ値)"""
    return tools.no_window_flags() | (getattr(subprocess, "BELOW_NORMAL_PRIORITY_CLASS", 0) if os.name == "nt" else 0)


def memory_mb():
    """このプロセスのメモリ(MB。Windows は WorkingSetSize、ほかは /proc/self/statm の RSS)。測れなければ 0"""
    try:
        if os.name == "nt":
            import ctypes
            from ctypes import wintypes

            class PMC(ctypes.Structure):
                _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD), ("PeakWorkingSetSize", ctypes.c_size_t),
                            ("WorkingSetSize", ctypes.c_size_t), ("QuotaPeakPagedPoolUsage", ctypes.c_size_t), ("QuotaPagedPoolUsage", ctypes.c_size_t),
                            ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t), ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                            ("PagefileUsage", ctypes.c_size_t), ("PeakPagefileUsage", ctypes.c_size_t)]
            c = PMC()
            c.cb = ctypes.sizeof(c)
            psapi = ctypes.WinDLL("psapi")
            k = ctypes.WinDLL("kernel32")
            k.GetCurrentProcess.restype = wintypes.HANDLE
            psapi.GetProcessMemoryInfo.argtypes = (wintypes.HANDLE, ctypes.c_void_p, wintypes.DWORD)
            if psapi.GetProcessMemoryInfo(k.GetCurrentProcess(), ctypes.byref(c), c.cb):
                return c.WorkingSetSize / 1048576.0
            return 0.0
        with open("/proc/self/statm", "r") as f:
            return int(f.read().split()[1]) * os.sysconf("SC_PAGE_SIZE") / 1048576.0
    except Exception:
        return 0.0


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


def read_json(path, max_bytes=STATE_MAX):
    try:
        d = fsio.read_json_file(path, max_bytes)
    except (OSError, ValueError):
        return None
    return d if isinstance(d, dict) else None


def write_json(path, obj):
    fsio.atomic_write(path, json.dumps(obj, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))


def _level(v):
    try:
        x = float(v)
    except ValueError:
        return -90.0
    return -90.0 if x != x or x < -90 else x


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
        proc = subprocess.Popen(cmd, cwd=wdir, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, creationflags=child_flags())
    except OSError as e:
        raise NoTool("ffmpeg を起動できませんでした: %s" % (e.strerror or e.__class__.__name__))
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
    """yt-dlp を起動する(既定の launcher。テストは偽物に替える)"""
    return subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=logf, stderr=subprocess.STDOUT, creationflags=child_flags())


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
        """止めた yt-dlp のファイルにまだ読んでいない所があるか(読み切ってから次を起動 = 重ねの見分け dedupe_ts が崩れない)"""
        return any(self._size(g) > pos for g, pos in self.files)

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
            self._failed(now, "", "yt-dlp を起動できませんでした: %s" % (e.strerror or e.__class__.__name__))
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
            tools.kill_quiet(p)
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
            except OSError:
                continue
            cut = raw.rfind(b"\n") + 1
            if cut:
                budget -= cut
                ent[1] = pos + cut
                for line in raw[:cut].decode("utf-8", "replace").splitlines():
                    for ts, w in parse_chat_line(line):
                        if ts > self.dedupe_ts:
                            out.append((ts, w))
                        self.max_ts = max(self.max_ts, ts)
                if gen == self.gen and self.proc is not None:
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

    def __init__(self, folder, rc, rec, url, first, spec, detect, use_chat, grace=CHAT_GRACE):
        self.folder, self.rc, self.rec, self.url, self.first = folder, rc, rec, url or "", float(first)
        self.vid = video_id(url, rec)
        self.spec = dict(spec)
        self.args = {"back": excite.ONLINE_BACK, "fwd": excite.ONLINE_FWD, "window": excite.ONLINE_WINDOW, "lag": self.spec["lag"],
                     "w_audio": self.spec["wAudio"], "w_chat": self.spec["wChat"], "head": self.spec["headSec"]}
        self.use_chat = bool(use_chat)
        self.chat_state = "ok" if use_chat else "off"
        self.online = excite.Online(use_chat=self.use_chat, **self.args)
        self.book = excite.PeakBook(self.spec["length"], self.spec["preRatio"], detect.get("sens") or "normal", detect.get("perHour") or 6)
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
        self.skipped = []           # [{from, to, since, until, done}](遅れて飛ばした区間。配信が終わったら測り直す)
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
                "bookDone": self.book_done, "finished": self.finished, "message": self.message}

    @classmethod
    def from_json(cls, folder, d, detect, grace=CHAT_GRACE):
        st = cls(folder, d["recorder"], d["recording"], d.get("url") or "", d["first"], dict(SPEC_DEFAULT, **(d.get("spec") or {})), detect,
                 d.get("useChat"), grace)
        st.args = dict(d.get("args") or st.args)
        st.online = excite.Online(use_chat=st.use_chat, **st.args).load(d["online"])
        st.book = excite.PeakBook.from_json(d["book"])
        st.chat_state = d.get("chatState") or st.chat_state
        st.seg_since, st.next_box, st.next_push = int(d["segSince"]), int(d["nextBox"]), int(d["nextPush"])
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
        sens = detect.get("sens") if detect.get("sens") in excite.SENS else "normal"
        self.book.thr = excite.SENS[sens]
        if isinstance(detect.get("perHour"), int):
            self.book.per_hour = detect["perHour"]

    def disable_chat(self, why):
        """チャットを諦めた: Online を音だけにして続ける(過去の秒はそのまま)"""
        if not self.use_chat:
            return
        d = self.online.to_json()
        self.use_chat = False
        self.online = excite.Online(use_chat=False, **self.args).load(d)
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
        """ライブ端から BEHIND_SKIP 秒より遅れた: 古い所を飛ばす(飛ばした区間は覚えて、配信が終わったら測り直す)。-> 飛ばしたセグメントの数"""
        target = last - SKIP_KEEP
        idx = next((i for i, s in enumerate(segs) if s["t"] >= target), len(segs))
        if idx == 0:
            return 0
        end_t = segs[idx]["t"] if idx < len(segs) else segs[-1]["t"] + segs[-1]["dur"]
        self.skipped.append({"from": self.next_box, "to": int(round(end_t - self.first)), "since": self.seg_since, "until": self.seg_since + idx, "done": False})
        self.seg_since += idx
        self.message = "遅れが %d 秒になったので、古い所(%d 秒分)を飛ばして追いつきました(配信が終わったら測り直します)" % (int(self.behind), int(end_t - segs[0]["t"]))
        return idx

    def place(self, t0, total_dur, full, band):
        """測った 1 秒の値を箱へ。受信時刻からの位置と置く位置のずれを ANCHOR_TOL まで許し、超えたら合わせ直す(飛び = 欠けとして埋める・重なり = 捨てる)"""
        k = max(1, int(round(total_dur)))
        vals = [[f, b] for f, b in zip(full, band)][:k]
        while len(vals) < k:
            vals.append(list(vals[-1]) if vals else [-90.0, -90.0])
        exp = int(round(t0 - self.first))
        d = exp - self.next_box
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
    def push_ready(self, now, ended=False):
        """音がそろい、チャットも(続きが来た・受信から grace 秒たった)そろった秒を Online へ -> 進めた秒数"""
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
                "behindSec": round(max(0.0, self.behind), 1), "at": iso_now(now), "first": iso_now(self.first), "measuredSec": self.next_box,
                "scoredSec": self.online.next_out, "gaps": self.gap_count, "skipped": [{"from": s["from"], "to": s["to"], "done": s["done"]} for s in self.skipped],
                "lateChat": self.late, "ended": self.finished, "message": self.message, "peaks": self.book.list(), "changes": ch}

    def save(self, now, peaks=True):
        os.makedirs(self.folder, exist_ok=True)
        if self.series_out:
            with open(os.path.join(self.folder, "series.jsonl"), "a", encoding="utf-8") as f:
                for row in self.series_out:
                    f.write(json.dumps(row, separators=(",", ":")) + "\n")
            self.series_out = []
        write_json(os.path.join(self.folder, "state.json"), self.to_json())
        if peaks:
            self.write_peaks(now)

    def write_peaks(self, now):
        os.makedirs(self.folder, exist_ok=True)
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
                 chat_grace=CHAT_GRACE, chat_max_per_hour=CHAT_MAX_PER_HOUR, tick_budget=TICK_BUDGET, parent=None, sleep=time.sleep):
        """テストは clock・client_factory(rc) -> 録画元(get_json・get_bytes)・measure_batch(録画元, 録画, セグメント…) -> (full, band)・
        launcher(cmd, logf) -> yt-dlp のプロセス を偽物に替える(12 時間を早送りで回す)"""
        self.config_path = os.path.abspath(config_path)
        self.clock, self.sleep = clock, sleep
        self.client_factory = client_factory or (lambda rc: RecorderClient(rc))
        self._measure = measure_batch
        self.launcher = launcher
        self.log = log or (lambda m: print("%s %s" % (time.strftime("%Y-%m-%d %H:%M:%S"), m), flush=True))
        self.save_sec, self.heart_sec, self.poll_sec, self.mem_limit_mb = save_sec, heart_sec, poll_sec, mem_limit_mb
        self.chat_backoff, self.chat_grace, self.chat_max_per_hour = tuple(chat_backoff), chat_grace, chat_max_per_hour
        self.tick_budget, self.parent = tick_budget, parent
        self.cfg, self.cfg_key, self.cfg_checked = {}, None, -1e18
        self.recs, self.feeds, self.done = {}, {}, set()
        self.dec_keys = {}
        self.job = tools.KillJob()
        self.started = clock()
        self.saved_at = self.heart_at = self.mem_at = -1e18
        self.mem = 0.0
        self.error = ""
        self.stop_flag = False
        self.load_config(force=True)

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
        d = read_json(self.config_path, 1024 * 1024) or {}
        self.cfg_key = key
        rcs = [r for r in d.get("recorders") or [] if isinstance(r, dict) and ID_RE.match(str(r.get("id") or "")) and isinstance(r.get("url"), str)]
        det = d.get("detect") if isinstance(d.get("detect"), dict) else {}
        spec, src = dict(SPEC_DEFAULT), d.get("spec") if isinstance(d.get("spec"), dict) else {}
        for k, dv in SPEC_DEFAULT.items():
            v = src.get(k)
            if isinstance(dv, bool):
                if isinstance(v, bool):
                    spec[k] = v
            elif isinstance(v, (int, float)) and not isinstance(v, bool) and v == v:
                spec[k] = float(v)
        self.cfg = {"dir": d.get("dir") if isinstance(d.get("dir"), str) and d.get("dir") else os.path.dirname(self.config_path), "recorders": rcs,
                    "detect": {"sens": det.get("sens") if det.get("sens") in excite.SENS else "normal",
                               "perHour": det.get("perHour") if isinstance(det.get("perHour"), int) and not isinstance(det.get("perHour"), bool) else 6},
                    "spec": spec, "ffmpeg": d.get("ffmpeg") or None, "ytdlp": d.get("ytdlp") or None,
                    "chatLimitBytes": int(d.get("chatLimitBytes") or CHAT_LIMIT), "chatStallSec": float(d.get("chatStallSec") or CHAT_STALL)}
        for st in self.recs.values():
            st.set_detect(self.cfg["detect"])
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
                except Exception as e:   # 1 回の不具合で止めない(心拍に出す)
                    self.error = "内部エラー: %r" % (e,)
                    self.log("盛り上がりの検出: %s\n%s" % (self.error, traceback.format_exc()))
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
        """1 回の周期: 設定 → チャット → 録画元ごとの録画 → 人の決定 → 保存 → 心拍"""
        self.error = ""
        self.load_config()
        now = self.clock()
        deadline = now + self.tick_budget
        self._chat_step(now)
        seen = set()
        for rc in self.cfg["recorders"]:
            seen |= self._recorder_step(rc, now, deadline)
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
                except OSError as e:
                    self.error = "候補を書けませんでした: %s" % (e.strerror or e.__class__.__name__)
        if now - self.mem_at >= MEM_CHECK_SEC:
            self.mem_at = now
            self.mem = memory_mb()
        self.heartbeat(now)

    def _save_rec(self, st, now):
        if st.use_chat and st.vid in self.feeds:
            st.chat_snap = self.feeds[st.vid].to_json()
        try:
            st.save(now)
        except OSError as e:
            self.error = "状態を保存できませんでした: %s" % (e.strerror or e.__class__.__name__)

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
            self._feed_step(f, now)

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
    def _recorder_step(self, rc, now, deadline):
        """録画元 1 つ: 一覧 → 録画ごとに進める。-> 見えた録画の鍵(つながらなければ、今持っている録画をそのまま)"""
        client = self.client_factory(rc)
        code, d = client.get_json("/live/list")
        if code != 200 or not isinstance(d, dict):
            return {k for k in self.recs if k[0] == rc["id"]}
        seen = set()
        for r in d.get("recordings") or []:
            if not isinstance(r, dict) or not REC_RE.match(str(r.get("id") or "")):
                continue
            key = (rc["id"], r["id"])
            seen.add(key)
            if key in self.done:
                continue
            st = self.recs.get(key) or self._open(rc, r)
            if st is None:
                continue
            try:
                self._rec_step(st, client, now, deadline)
            except RecorderDown:
                st.message = "録画元につながりません(次の周期でやり直します)"
            if st.finished:
                self._save_rec(st, now)
                self.done.add(key)
                self._release(key)
        return seen

    def _open(self, rc, r):
        """録画を受け持つ: state.json があれば続きから。録画中で firstPdt があれば新しく。終わった録画は state.json があって済んでいないときだけ"""
        folder = os.path.join(self.dir, rc["id"], r["id"])
        key = (rc["id"], r["id"])
        d = read_json(os.path.join(folder, "state.json"))
        if d is not None:
            try:
                st = RecState.from_json(folder, d, self.cfg["detect"], self.chat_grace)
            except (KeyError, TypeError, ValueError) as e:
                self.log("盛り上がりの検出: %s の状態を読めないので、初めからやり直します(%r)" % (r["id"], e))
                st = None
            if st is not None and st.finished:
                self.done.add(key)
                return None
        else:
            st = None
        if st is None:
            first = iso_epoch(r.get("firstPdt"))
            if r.get("active") is not True or first is None:
                return None
            ytdlp = self.cfg["ytdlp"]
            url = str(r.get("url") or "")
            st = RecState(folder, rc["id"], r["id"], url, first, self.cfg["spec"], self.cfg["detect"], bool(ytdlp and video_id(url, r["id"])), self.chat_grace)
            self.log("盛り上がりの検出: %s を受け持ちます(チャット %s)" % (r["id"], "あり" if st.use_chat else "なし"))
        st.set_detect(self.cfg["detect"])
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
            if self.clock() > deadline:
                return
            self._remeasure(st, client, sk)
        st.finished = True
        st.message = st.message if st.skipped else ""
        st.peaks_dirty = True
        self.log("盛り上がりの検出: %s が終わりました(候補 %d・欠け %d)" % (st.rec, len(st.book.order), st.gap_count))

    def _remeasure(self, st, client, sk):
        """飛ばした区間の音を測り直して skipped.jsonl へ(0-10-6。候補は作り直さない)"""
        code, s = client.get_json("/live/%s/status?since=%d" % (st.rec, sk["since"]))
        segs = parse_segments((s or {}).get("segmentList") if code == 200 and isinstance(s, dict) else [])[:max(0, sk["until"] - sk["since"])]
        rows = []
        cur = []
        for x in segs + [None]:
            if x is not None and (not cur or (sum(y["dur"] for y in cur) < BIG_BATCH_SEC and x["uri"].split("/")[0] == cur[0]["uri"].split("/")[0])):
                cur.append(x)
                continue
            if cur:
                try:
                    full, band = self.measure_batch(client, st.rec, cur)
                    rows.append({"t0": int(round(cur[0]["t"] - st.first)), "full": [round(v, 1) for v in full], "band": [round(v, 1) for v in band]})
                except (MeasureError, NoTool, RecorderDown) as e:
                    rows.append({"t0": int(round(cur[0]["t"] - st.first)), "error": str(e)[:160] or e.__class__.__name__})
            cur = [x] if x is not None else []
        os.makedirs(st.folder, exist_ok=True)
        with open(os.path.join(st.folder, "skipped.jsonl"), "a", encoding="utf-8") as f:
            for row in rows:
                f.write(json.dumps(row, separators=(",", ":")) + "\n")
        sk["done"] = True

    # ---- 人の決定(decisions.json。入口が書く)
    def _apply_decisions(self):
        for key, st in self.recs.items():
            p = os.path.join(st.folder, "decisions.json")
            try:
                m = os.stat(p)
                k = (m.st_mtime_ns, m.st_size)
            except OSError:
                continue
            if self.dec_keys.get(key) == k:
                continue
            d = read_json(p, 8 * 1024 * 1024) or {}
            items = sorted((x for x in d.get("items") or [] if isinstance(x, dict) and isinstance(x.get("n"), int) and x["n"] > st.dec_n),
                           key=lambda x: x["n"])
            for x in items:
                st.book.decide(str(x.get("id") or ""), x.get("state"), origin=x.get("origin") or "manual", mark_id=x.get("markId"), job_id=x.get("jobId"))
                st.dec_n = x["n"]
                st.peaks_dirty = True
            self.dec_keys[key] = k

    # ---- 心拍
    def heartbeat(self, now, force=False, message=None):
        if not force and now - self.heart_at < self.heart_sec:
            return
        self.heart_at = now
        active = [st for st in self.recs.values() if not st.finished]
        doc = {"v": 1, "version": WORKER_VERSION, "pid": os.getpid(), "at": iso_now(now), "started": iso_now(self.started),
               "behindSec": round(max([st.behind for st in active] or [0.0]), 1), "memMB": round(self.mem, 1),
               "chatRestarts": sum(f.total_restarts for f in self.feeds.values()),
               "recordings": [{"recorder": st.rc, "id": st.rec, "behindSec": round(max(0.0, st.behind), 1), "chat": st.chat_state} for st in active],
               "message": message if message is not None else ("%d 本の録画を見ています" % len(active) if active else "録画中の配信はありません"),
               "error": self.error}
        try:
            write_json(os.path.join(self.dir, "worker.json"), doc)
        except OSError:
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
