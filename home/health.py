"""「調子」(全体の計画 段9 9-1。docs/plan/phase9-ops-stability.md)。

入口の GET /api/health が返す中身を集める部品。版(期待と実際)・認識ワーカー・外部プログラム(ffmpeg・ffprobe・yt-dlp)・
空き容量・作業データの大きさ・エラーの件数(画面のエラー・まとめて実行の失敗)を1つにまとめる。
重い物(フォルダを歩く・外部プログラムの版・異常終了の件数)は別のスレッドで数えて CACHE_SEC の間は前の値を返す(HTTP のスレッドを止めない)。
判定(良い/注意/悪い)は画面(portal.js)が行い、ここは数字と事実だけを返す。
"""
import json
import os
import re
import shutil
import subprocess
import threading
import time
import xml.etree.ElementTree as ET

from ytt_core import datadir, layout, tools as ytools

CACHE_SEC = 600          # 作業データの大きさ・外部プログラムの版を数え直す間隔(秒)。「数え直す」で即
TOP_ITEMS = 12           # ツールごとに出す直下の項目の数
CLIENT_ERR_WINDOW = 24 * 3600
AUTORUN_FAIL_WINDOW = 7 * 24 * 3600
TOOL_TIMEOUT = 5.0
CRASH_WINDOW = 7 * 24 * 3600     # 異常終了を数える期間(秒。見張り役。docs/plan/stability-review-2026-10.md)
CRASH_TIMEOUT = 15.0             # wevtutil を待つ秒数
CRASH_MAX_EVENTS = 500           # ログごとに読む件数の上限(新しい順)
# アプリの異常終了(Application Error 1000)を個別に数える exe(小文字)。それ以外は "other" に合算
CRASH_APPS = ("python.exe", "pythonw.exe", "ffmpeg.exe", "ffprobe.exe", "msedge.exe", "chrome.exe", "whisper-cli.exe", "llama-server.exe")
_EVT_NS = "{http://schemas.microsoft.com/win/2004/08/events/event}"
DATA_TOOLS = (("app", "ホーム"), ("studio", "スタジオ"), ("transcribe", "編集"), ("cut2resolve", "cut2resolve"), ("holo-colors", "ホロカラー"))


# ---------- フォルダの大きさ ----------
def dir_size(path):
    """(バイト数, ファイル数)。リンクはたどらない。無ければ (0, 0)"""
    if os.path.isfile(path):
        try:
            return os.path.getsize(path), 1
        except OSError:
            return 0, 0
    total = count = 0
    for dirpath, dirnames, filenames in os.walk(path):
        dirnames[:] = [d for d in dirnames if not os.path.islink(os.path.join(dirpath, d))]
        for n in filenames:
            fp = os.path.join(dirpath, n)
            try:
                if not os.path.islink(fp):
                    total += os.path.getsize(fp)
                    count += 1
            except OSError:
                pass
    return total, count


def top_items(path, limit=TOP_ITEMS):
    """フォルダ直下の項目を大きい順に [{name, bytes, files, dir}]"""
    out = []
    try:
        names = os.listdir(path)
    except OSError:
        return out
    for n in names:
        p = os.path.join(path, n)
        b, c = dir_size(p)
        out.append({"name": n, "bytes": b, "files": c, "dir": os.path.isdir(p)})
    out.sort(key=lambda x: -x["bytes"])
    return out[:limit]


def data_sizes(repo_root=None, env=None):
    """作業データの置き場所ごとの大きさ。-> {"root", "dirs": [{tool, label, path, bytes, files, items}], "bytes"}"""
    root = datadir.data_root(env)
    dirs, total = [], 0
    for tool, label in DATA_TOOLS:
        try:
            path = datadir.resolve(tool, repo_root, env)
        except Exception:
            continue
        if not os.path.isdir(path):
            continue
        b, c = dir_size(path)
        total += b
        dirs.append({"tool": tool, "label": label, "path": path, "bytes": b, "files": c, "items": top_items(path)})
    return {"root": root, "dirs": dirs, "bytes": total}


# ---------- 空き容量 ----------
def disk_free(paths):
    """パスのドライブごとの空き容量(同じドライブは1つに)。-> [{"path", "freeBytes", "totalBytes"}]"""
    out, seen = [], set()
    for p in paths:
        if not p:
            continue
        probe = p
        while probe and not os.path.exists(probe):   # まだ無いフォルダは、ある所まで上へ
            parent = os.path.dirname(probe)
            if parent == probe:
                break
            probe = parent
        try:
            u = shutil.disk_usage(probe)
        except OSError:
            continue
        key = os.path.splitdrive(os.path.abspath(probe))[0].lower() or os.path.abspath(probe)
        if key in seen:
            continue
        seen.add(key)
        out.append({"path": p, "drive": key or p, "freeBytes": u.free, "totalBytes": u.total})
    return out


# ---------- 外部プログラム ----------
def parse_version_line(name, text):
    """`ffmpeg -version` などの1行目から版の文字を抜く(見つからなければ先頭の 60 字)"""
    line = (text or "").strip().splitlines()[0] if (text or "").strip() else ""
    m = re.search(r"version\s+([^\s]+)", line)
    if m:
        return m.group(1)[:40]
    return line[:60]


def tool_version(name, env_var=None, args=("-version",), timeout=TOOL_TIMEOUT):
    """{"path", "version"}(無ければ path None)"""
    path = ytools.find_tool(name, env_var)
    if not path:
        return {"path": None, "version": ""}
    try:
        p = subprocess.run([path] + list(args), stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=timeout,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        text = p.stdout.decode("utf-8", "replace")
    except (OSError, subprocess.SubprocessError):
        text = ""
    return {"path": path, "version": parse_version_line(name, text)}


def tool_versions():
    return {"ffmpeg": tool_version("ffmpeg", "YTT_FFMPEG"), "ffprobe": tool_version("ffprobe", "YTT_FFPROBE"),
            "ytdlp": tool_version("yt-dlp", "YTT_YTDLP", ("--version",))}


# ---------- エラーの件数 ----------
def _stamp_to_epoch(v):
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return v / 1000.0 if v > 1e11 else float(v)
    if isinstance(v, str):
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S"):
            try:
                return time.mktime(time.strptime(v[:19], fmt))
            except ValueError:
                pass
    return None


def count_jsonl(path, since, now, pred=None, stamp_keys=("at", "time", "ts", "created")):
    """jsonl(と .1)の中で、since 秒以内・pred に合う行の数(読めない行は飛ばす)"""
    n = 0
    for p in (path, path + ".1"):
        try:
            with open(p, "rb") as f:
                data = f.read()
        except OSError:
            continue
        for raw in data.split(b"\n"):
            raw = raw.strip()
            if not raw:
                continue
            try:
                rec = json.loads(raw.decode("utf-8", "replace"))
            except ValueError:
                continue
            if not isinstance(rec, dict):
                continue
            t = None
            for k in stamp_keys:
                if k in rec:
                    t = _stamp_to_epoch(rec[k])
                    if t is not None:
                        break
            if t is None or now - t > since:
                continue
            if pred and not pred(rec):
                continue
            n += 1
    return n


def count_client_errors(path, now=None):
    now = time.time() if now is None else now
    return count_jsonl(path, CLIENT_ERR_WINDOW, now)


def count_autorun_failed(path, now=None):
    """まとめて実行の失敗の数。あとから解析(mode post_analyze。測るためだけ・失敗しても試し直す)は数えない(依頼の失敗に見せない。2026-10-05)"""
    now = time.time() if now is None else now
    return count_jsonl(path, AUTORUN_FAIL_WINDOW, now, pred=lambda r: r.get("state") == "error" and r.get("mode") != "post_analyze",
                       stamp_keys=("created",))


# ---------- 異常終了の件数(見張り役) ----------
def _wevtutil_events(log, xpath, runner):
    """wevtutil で log を読んで Event 要素のリストを返す。読めなければ None(wevtutil が無い・時間切れ・権限・解析できない)"""
    run = runner or subprocess.run
    cmd = ["wevtutil", "qe", log, "/q:" + xpath, "/f:xml", "/c:%d" % CRASH_MAX_EVENTS, "/rd:true"]
    try:
        p = run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=CRASH_TIMEOUT,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except (OSError, subprocess.SubprocessError):
        return None
    if getattr(p, "returncode", 1) != 0:
        return None
    out = p.stdout
    if isinstance(out, bytes):
        out = out.decode("utf-8", "replace")
    out = re.sub(r"<\?xml[^>]*\?>", "", out or "")   # wevtutil は Event を並べるだけ(根が無い)。根を付けて1つの XML にする
    try:
        return list(ET.fromstring("<Events>" + out + "</Events>"))
    except ET.ParseError:
        return None


def _evt_field(ev, tag, attr=None):
    node = ev.find("%sSystem/%s%s" % (_EVT_NS, _EVT_NS, tag))
    if node is None:
        return ""
    return (node.get(attr) if attr else (node.text or "")) or ""


def crash_counts(now=None, runner=None):
    """直近 CRASH_WINDOW 秒の異常終了の件数。読めなければ None。
    -> {"windowSec", "os": {"kernelPower41", "unexpectedShutdown6008", "whea", "total"}, "apps": {exe 名または "other": 件数, ..., "total"}}
    期間は wevtutil の timediff(PC の今の時刻基準)で絞るので now は使わない(他の count_* と呼び出しの形をそろえてある)。
    runner は subprocess.run の代わり(テスト用)。"""
    if runner is None and os.name != "nt":
        return None
    win = "TimeCreated[timediff(@SystemTime) <= %d]" % (CRASH_WINDOW * 1000)
    sys_q = ("*[System[((Provider[@Name='Microsoft-Windows-Kernel-Power'] and EventID=41) or (Provider[@Name='EventLog'] and EventID=6008)"
             " or Provider[@Name='Microsoft-Windows-WHEA-Logger']) and %s]]" % win)
    app_q = "*[System[Provider[@Name='Application Error'] and EventID=1000 and %s]]" % win
    sys_ev = _wevtutil_events("System", sys_q, runner)
    if sys_ev is None:
        return None
    app_ev = _wevtutil_events("Application", app_q, runner)
    if app_ev is None:
        return None
    osc = {"kernelPower41": 0, "unexpectedShutdown6008": 0, "whea": 0}
    for ev in sys_ev:
        prov, eid = _evt_field(ev, "Provider", "Name"), _evt_field(ev, "EventID").strip()
        if prov == "Microsoft-Windows-Kernel-Power" and eid == "41":
            osc["kernelPower41"] += 1
        elif prov == "EventLog" and eid == "6008":
            osc["unexpectedShutdown6008"] += 1
        elif prov == "Microsoft-Windows-WHEA-Logger":
            osc["whea"] += 1
    osc["total"] = osc["kernelPower41"] + osc["unexpectedShutdown6008"] + osc["whea"]
    apps = dict((n, 0) for n in CRASH_APPS)
    apps["other"] = 0
    for ev in app_ev:
        if _evt_field(ev, "Provider", "Name") != "Application Error" or _evt_field(ev, "EventID").strip() != "1000":
            continue
        d = ev.find("%sEventData/%sData" % (_EVT_NS, _EVT_NS))   # 最初の Data = 落ちたアプリの名前
        name = ((d.text or "") if d is not None else "").strip().lower()
        apps[name if name in CRASH_APPS else "other"] += 1
    apps["total"] = sum(apps.values())
    return {"windowSec": CRASH_WINDOW, "os": osc, "apps": apps}


# このツール側: 「編集」の serve.log に、認識ワーカーの落ち・黙って強制終了したときの印(editor/ed_jobs.py の ed_state.log.error の文言)が残る。
# 行頭は "%(asctime)s " = "2026-10-04 12:34:56,789 "(editor/ed_state.py)。文言を変えるときはここも
WORKER_CRASH_MARK = "認識ワーカーが異常終了しました"
WORKER_HUNG_MARK = "なにも届かないため強制終了します"


def count_worker_incidents(path, now=None):
    """serve.log(と .1・.2)の中で、直近 CRASH_WINDOW 秒の認識ワーカーの異常終了・黙って強制終了の回数 -> {"crashed", "hung"}"""
    now = time.time() if now is None else now
    out = {"crashed": 0, "hung": 0}
    for p in (path, path + ".1", path + ".2"):
        try:
            with open(p, "rb") as f:
                text = f.read().decode("utf-8", "replace")
        except OSError:
            continue
        for line in text.splitlines():
            key = "crashed" if WORKER_CRASH_MARK in line else "hung" if WORKER_HUNG_MARK in line else None
            if not key:
                continue
            t = _stamp_to_epoch(line[:19])
            if t is not None and now - t <= CRASH_WINDOW:
                out[key] += 1
    return out


# ---------- まとめ ----------
class Health:
    """入口の「調子」。sup = Supervisor(status() を使う)。worker_probe() = 「編集」の /api/ping の worker(無ければ None)。
    extra_dirs() = 空き容量を見る追加の場所(スタジオの書き出し先など)"""

    def __init__(self, sup, logs_dir, repo_root=None, worker_probe=None, extra_dirs=None, clock=time.time, cache_sec=CACHE_SEC, crash_fn=None,
                 live_probe=None, accuracy_probe=None):
        """live_probe() = リアルタイム切り抜きの録画元ごとの状態と空き容量(home/live.py の Live.health)。オフなら None を返す = 「調子」に出さない。
        accuracy_probe() = 精度の自動測定の状態と領域ごとの直近・前回(home/accuracy.py の Accuracy.snapshot。軽い。無ければ「調子」に出さない)"""
        self.sup, self.logs_dir, self.repo_root = sup, logs_dir, repo_root
        self.live_probe = live_probe
        self.accuracy_probe = accuracy_probe
        self.crash_fn = crash_fn or crash_counts
        self.worker_probe = worker_probe or (lambda: None)
        self.extra_dirs = extra_dirs or (lambda: [])
        self.clock, self.cache_sec = clock, cache_sec
        self._lock = threading.Lock()
        self._slow = None            # {"data", "tools", "crashes", "at"}。crashes は wevtutil が遅いので data・tools のあとで入る(それまで None)
        self._computing = False

    def _compute_crashes(self):
        """異常終了の件数。{"events": OS・アプリ(wevtutil。読めなければ None), "tool": 「編集」の serve.log(認識ワーカー。読めなければ None), "windowSec"}"""
        try:
            events = self.crash_fn()
        except Exception:
            events = None
        tool = None
        try:
            tool = count_worker_incidents(os.path.join(datadir.resolve("transcribe", self.repo_root), "serve.log"), self.clock())
        except Exception:
            pass
        return {"events": events, "tool": tool, "windowSec": CRASH_WINDOW}

    def _compute_slow(self):
        try:
            data = data_sizes(self.repo_root)
            tools = tool_versions()
            with self._lock:
                self._slow = {"data": data, "tools": tools, "crashes": None, "at": self.clock()}   # 先に出せる物を出す
        except Exception as e:   # 数えられなくても画面は出す
            with self._lock:
                self._slow = {"data": {"root": None, "dirs": [], "bytes": 0, "error": str(e)[:200]}, "tools": {}, "crashes": None, "at": self.clock()}
        try:
            crashes = self._compute_crashes()
            with self._lock:
                self._slow["crashes"] = crashes
        except Exception:
            pass
        finally:
            with self._lock:
                self._computing = False

    def _ensure_slow(self, refresh):
        with self._lock:
            stale = self._slow is None or refresh or self.clock() - self._slow["at"] > self.cache_sec
            if stale and not self._computing:
                self._computing = True
                start = True
            else:
                start = False
        if start:
            th = threading.Thread(target=self._compute_slow, daemon=True, name="ytt-health")
            th.start()
            th.join(1.5)   # 速く終わるなら待つ(初回の空の応答を減らす)。終わらなければ次の問い合わせで

    def snapshot(self, refresh=False):
        self._ensure_slow(refresh)
        st = self.sup.status() if self.sup else {"tools": [], "heavy": None}
        with self._lock:
            slow, computing = self._slow, self._computing
        versions = [{"tool": t["id"], "name": t.get("name", t["id"]), "state": t.get("state"), "version": t.get("version") or "",
                     "expected": t.get("expectedVersion") or "", "ok": (not t.get("expectedVersion") or not t.get("version") or t["expectedVersion"] == t["version"])}
                    for t in st.get("tools", [])]
        try:
            worker = self.worker_probe()
        except Exception:
            worker = None
        client_log = os.path.join(self.logs_dir, "client-errors.jsonl")
        runs_log = os.path.join(self.logs_dir, "autorun-runs.jsonl")
        now = self.clock()
        paths = [os.path.dirname(self.logs_dir)] + [p for p in self.extra_dirs() if p]
        out = {
            "at": int(now * 1000),
            "versions": versions,
            "worker": worker,
            "disk": disk_free(paths),
            "errors": {"clientLast24h": count_client_errors(client_log, now), "clientLog": client_log,
                       "autorunFailedLast7d": count_autorun_failed(runs_log, now), "autorunLog": runs_log},
            "heavy": st.get("heavy"),
            "computing": computing,
        }
        if self.live_probe is not None:   # リアルタイム切り抜き(線 D): オンのときだけ "live" を足す(オフなら今までと同じ形)
            try:
                lv = self.live_probe()
            except Exception:
                lv = None
            if lv is not None:
                out["live"] = lv
        if self.accuracy_probe is not None:   # 精度(Q3): 領域ごとの直近・前回と、いつ測るか。軽い(記録を返すだけ)
            try:
                out["accuracy"] = self.accuracy_probe()
            except Exception:
                pass
        if slow:
            out["data"] = slow["data"]
            out["tools"] = slow["tools"]
            out["crashes"] = slow.get("crashes")
            out["countedAt"] = int(slow["at"] * 1000)
        else:
            out["data"] = None
            out["tools"] = None
            out["crashes"] = None
        return out
