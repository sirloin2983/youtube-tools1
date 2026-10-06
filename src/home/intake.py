"""友人からの依頼の受付(docs/spec/friend-intake.md。2026-09-30)。

友人のプログラム(friend-apps/request-sender/)か Dropbox のファイルリクエストで届いた依頼を、Dropbox が同期したフォルダで見張り、
まとめて実行(src/home/autorun.py)に入れて文字起こしまで流す。ホームの起動と一緒に動き、「すべて終了」で止まる。

届くもの(見張るフォルダの直下だけ。受付済み\・失敗\ などの下のフォルダは見ない):
  <id>.request.json   友人のプログラムが最後に送る依頼(kind video = 同じ id の動画を文字起こし / url = 配信を解析 → 上位 N 個 → 書き出し → 文字起こし)
  <id>__<名前>.mp4 など 友人のプログラムが送った動画(JSON の files に名前がある)
  動画(.mp4 .mov .mkv .webm .m4v)  手で送った動画。ファイル名の頭の【名前】を配信者として読む
  .txt / .url         手で送った配信の URL(.txt は1行に「URL [数]」。# の行・空の行は無視)

決まり:
- 同期の途中を読まない: 大きさと更新時刻が SETTLE 秒以上変わらないファイルだけ。友人のプログラムの動画は JSON がそろってから
- 受け付けた元のファイルは 受付済み\YYYY-MM-DD\ へ、断ったものは 失敗\ へ移し「<名前>.理由.txt」を添える(消さない)
- 動画は作業データの intake\YYYY-MM-DD\ へコピーしてから文字起こしする(Dropbox の「オンラインのみ」や片付けで元が消えても、文書の元のパスが切れない)
  コピーが 30fps(H.264・AAC)でなければ、コピーを ytt_core.normalize で作り直して置き換える(SLOTS を通す。元は触らない。失敗してもコピーのまま続ける)
- 同じ動画・同じ配信も断らない(2026-10-02 ユーザー: 送り直せるように。配信は解析・切り抜き・文字起こしを使い回す。受け付けた配信は intake-state.json に覚えるだけ)
- 友人が時刻で指定した区間(items[].ranges)・カット(cut)・解析の重み(weights)は、形を確かめてまとめて実行へ渡す(送るアプリ 2.0.0。friend-intake.md の 2-6)
- 1日の上限を超えた分は断らずにフォルダに残し、次の日に回す
- URL は YouTube の配信・動画だけ。11 文字の ID を取り出し、それだけを yt-dlp に渡す(任意の URL を渡さない)
- 動画は拡張子と ffprobe で形を確かめてから(他人が作ったファイルを ffmpeg で読むこと自体が攻撃の入口になり得るため)
"""
import datetime
import json
import os
import re
import shutil
import subprocess
import threading
import time
import uuid

from ytt_core import colors, fsio, jobs, normalize, tools

VIDEO_EXT = (".mp4", ".mov", ".mkv", ".webm", ".m4v")
TEXT_EXT = (".txt", ".url")
REQ_SUFFIX = ".request.json"
DONE_DIR, FAIL_DIR, OUT_DIR = "受付済み", "失敗", "出力"   # 出力\ = ① 全自動のパック(友人のアプリの「受け取る」が読む)
FLOW_LABELS = {"auto": "① 全自動", "check": "② 軽く確認", "manual": "③ 全部人が行う"}   # 友人が送るときに選ぶ(2026-10-01)。無ければ ②
REQ_ID_RE = re.compile(r"^\d{8}-\d{6}-[0-9a-f]{6}$")
APP_FILE_RE = re.compile(r"^(\d{8}-\d{6}-[0-9a-f]{6})__(.+)$")   # 友人のプログラムが送った動画の名前
NAME_PREFIX_RE = re.compile(r"^((?:【[^】]{1,60}】)+)\s*(.*)$")        # 手で送った動画の【名前】
TEXT_MAX = 64 * 1024
MEMO_MAX = 500
TOP_MAX = 10
MAX_URLS = 10            # 1つの依頼に書ける配信の数(まとめて実行の start_request の上限と同じ)
SETTLE = 20.0            # 大きさと更新時刻がこの秒数変わらなければ、同期が終わったとみなす
INTERVAL = 30.0          # 見る間隔
WAIT_FILES = 3600.0      # JSON があるのに動画がそろわないとき、断るまで待つ秒数
KEEP_REQUESTS = 50       # 画面に出す最近の依頼の数
KEEP_SEEN = 5000         # 覚えておく配信・動画の数
STATE_FILE = "intake-state.json"
# OS・同期のアプリが勝手に置くファイル(依頼ではない)。断って 失敗\ へ移すと、すぐまた作られて「断った」が毎回増えるので、見ない
OS_FILES = ("desktop.ini", "thumbs.db", "ehthumbs.db", ".ds_store", "icon\r", ".dropbox", ".dropbox.attr")
_HIDDEN = 0x2 | 0x4   # FILE_ATTRIBUTE_HIDDEN | FILE_ATTRIBUTE_SYSTEM
STATE_LABELS = {"off": "オフ", "watching": "見張り中", "error": "止まっています"}
REQ_LABELS = {"accepted": "受け付けた", "rejected": "断った"}
_YT_HOSTS = ("youtube.com", "www.youtube.com", "m.youtube.com", "music.youtube.com")
_ID = r"([A-Za-z0-9_-]{11})"


def youtube_id(url):
    """YouTube の配信・動画の URL -> 11 文字の ID(ほかは None)。watch?v= / youtu.be/ / live/ / shorts/ / embed/"""
    s = str(url or "").strip()
    m = re.match(r"^(?:https?://)?([^/?#]+)(/[^?#]*)?(\?[^#]*)?(#.*)?$", s)
    if not m:
        return None
    host, path, query = m.group(1).lower(), m.group(2) or "", m.group(3) or ""
    if host in ("youtu.be", "www.youtu.be"):
        mm = re.match(r"^/" + _ID + r"/?$", path)
        return mm.group(1) if mm else None
    if host not in _YT_HOSTS:
        return None
    if path in ("/watch", "/watch/"):
        mm = re.search(r"(?:^\?|&)v=" + _ID + r"(?:&|$)", query)
        return mm.group(1) if mm else None
    mm = re.match(r"^/(?:live|shorts|embed)/" + _ID + r"/?$", path)
    return mm.group(1) if mm else None


def parse_lines(text, default_top):
    """.txt の中身 -> ([{"id", "top", "line"}], [{"line", "reason"}])。1行に「URL [数]」。空の行・# の行は無視"""
    ok, bad = [], []
    for raw in text.splitlines():
        line = raw.strip().lstrip("﻿")
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        vid = youtube_id(parts[0])
        top = default_top
        if len(parts) >= 2 and re.fullmatch(r"\d{1,3}", parts[1]):
            top = int(parts[1])
            rest = parts[2:]
        else:
            rest = parts[1:]
        if not vid:
            bad.append({"line": line[:200], "reason": "YouTube の配信・動画の URL ではありません"})
        elif not 1 <= top <= TOP_MAX:
            bad.append({"line": line[:200], "reason": "切り抜く数は 1〜%d です" % TOP_MAX})
        elif rest and not rest[0].startswith("#"):
            bad.append({"line": line[:200], "reason": "URL と数のあとに余計な文字があります(メモは # のあとに書いてください)"})
        else:
            ok.append({"id": vid, "top": top, "line": line[:200]})
    return ok, bad


def parse_url_file(text):
    """.url(インターネットのショートカット)の URL= の行"""
    for line in text.splitlines():
        if line.strip().lower().startswith("url="):
            return line.strip()[4:].strip()
    return ""


def decode_text(raw):
    for enc in ("utf-8-sig", "cp932"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", "replace")


def _no_window():
    return {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}


def probe_video(path):
    """ffprobe で動画の形を確かめる -> {"ok", "duration" (秒 か None), "reason"}"""
    fp = tools.find_tool("ffprobe")
    if not fp:
        return {"ok": False, "duration": None, "reason": "ffprobe が見つからないので、動画を確かめられません"}
    try:
        r = subprocess.run([fp, "-v", "error", "-show_entries", "format=duration:stream=codec_type", "-of", "json", path],
                           capture_output=True, timeout=60, **_no_window())
        d = json.loads(r.stdout.decode("utf-8", "replace") or "{}")
    except (OSError, subprocess.TimeoutExpired, ValueError):
        return {"ok": False, "duration": None, "reason": "動画として読めませんでした"}
    if r.returncode != 0 or not any(s.get("codec_type") == "audio" for s in d.get("streams") or []):
        return {"ok": False, "duration": None, "reason": "音声のある動画として読めませんでした"}
    try:
        dur = float((d.get("format") or {}).get("duration"))
    except (TypeError, ValueError):
        dur = None
    return {"ok": True, "duration": dur, "reason": ""}


def youtube_info(vid):
    """yt-dlp で配信の長さ・状態・題名・チャンネルを調べる(ダウンロードしない)。-> dict か None(調べられない)"""
    if os.environ.get("STUDIO_FAKE") == "1":
        return {"duration": 600.0, "live": "not_live", "title": "疑似タイトル(%s)" % vid, "channel": ""}
    yd = tools.find_tool("yt-dlp")
    if not yd or not re.fullmatch(_ID, vid or ""):
        return None
    try:
        r = subprocess.run([yd, "--encoding", "utf-8", "--skip-download", "--no-warnings", "--no-playlist", "--print",   # --encoding: 付けないと Windows の文字コード(cp932)で出して題名が化ける
                            "%(duration)s\t%(live_status)s\t%(channel)s\t%(title)s", "--", "https://www.youtube.com/watch?v=" + vid],
                           capture_output=True, timeout=90, **_no_window())
    except (OSError, subprocess.TimeoutExpired):
        return None
    if r.returncode != 0:
        return None
    parts = (r.stdout.decode("utf-8", "replace").strip().splitlines() or [""])[-1].split("\t")
    if len(parts) < 4:
        return None
    try:
        dur = float(parts[0])
    except ValueError:
        dur = None
    return {"duration": dur, "live": parts[1], "channel": parts[2][:100] if parts[2] != "NA" else "", "title": parts[3][:120] if parts[3] != "NA" else ""}


def is_os_file(name, path=None):
    """依頼として扱わないファイル: OS・同期のアプリが置くもの・隠しファイル・システムのファイル(Windows の属性)"""
    if name.lower() in OS_FILES:
        return True
    if path and os.name == "nt":
        try:
            return bool(getattr(os.stat(path), "st_file_attributes", 0) & _HIDDEN)
        except OSError:
            return False
    return False


def _speaker_name(x):
    """依頼に書かれた人の名前 -> 整えた名前(空・制御文字を含む・文字列でない = "")。names と people で同じ整え方にする"""
    s = x.strip()[:60] if isinstance(x, str) else ""
    return s if s and not any(ord(c) < 32 for c in s) else ""


# 字幕の見た目(people[].style)の許可の一覧: 鍵 -> 値を検査して整える関数(通らなければ None = その項目だけ捨てる)。
# 鍵を増やすとき(font・size など)はここに足す。知らない鍵は黙って捨てる(新しいアプリ + 古い PC でも色までは効く)。
# 色は外から来る文字で画面・Lua に入るので、必ず 16 進 6 桁だけにそろえる(src/ytt_core/colors.py の HEX_RE と同じ形。# は付けても付けなくてもよい)
STYLE_KEYS = {"color": lambda v: colors.norm_hex(v) if isinstance(v, str) else None}


def parse_style(v):
    """人ごとの字幕の見た目 {"color": "FF00AA"} -> 許可した鍵だけを整えた dict({"color": "#FF00AA"})。形が違う・何も残らない = {}"""
    out = {}
    if isinstance(v, dict):
        for k, check in STYLE_KEYS.items():
            if k in v:
                x = check(v[k])
                if x is not None:
                    out[k] = x
    return out


def parse_speakers(v):
    """依頼の「配信者」{"count": 1〜10, "names": [...], "people": [{"name", "style"}]?} ->
    {"count", "names", "styles": {名前: {"color": "#RRGGBB"}}}(styles は見た目を指定した人だけ。無ければ {})か None(無い・形が違う = 話者分離しない)。
    people は 2.1.0 のアプリから(任意)。styles の名前は count で切ったあとの names に入っている人だけ。同じ名前が2回あれば先のもの"""
    if not isinstance(v, dict):
        return None
    n = v.get("count")
    if not isinstance(n, int) or isinstance(n, bool) or not 1 <= n <= 10:
        return None
    names = []
    for x in v.get("names") if isinstance(v.get("names"), list) else []:
        s = _speaker_name(x)
        if s and s not in names:
            names.append(s)
    names = names[:n]
    styles = {}
    for p in v.get("people") if isinstance(v.get("people"), list) else []:
        if not isinstance(p, dict):
            continue
        s = _speaker_name(p.get("name"))
        st = parse_style(p.get("style"))
        if s in names and st and s not in styles:
            styles[s] = st
    return {"count": n, "names": names, "styles": styles}


VIDEO_TRACKS_DEFAULT, VIDEO_TRACKS_MAX = 1, 5
RANGE_MAX, RANGE_MAX_SEC = 10, 3600   # 1本の配信の区間の数・1つの区間の長さ(まとめて実行・スタジオと同じ)
CUT_LABELS = {"none": "カットしない", "silence": "無音を削る"}


def hms(sec):
    sec = int(sec)
    return "%d:%02d:%02d" % (sec // 3600, sec % 3600 // 60, sec % 60)


def parse_ranges(v):
    """依頼の区間 [{"start": 秒, "end": 秒}, …](2.0.0 のアプリ)-> ([(開始, 終了)], [断った理由])。
    0 ≤ 開始 < 終了・長さ 3600 秒まで・10 個まで。形が違うものだけ断る(ほかは進める)"""
    ok, bad = [], []
    if v is None:
        return ok, bad
    if not isinstance(v, list):
        return ok, ["区間の形が正しくありません"]
    for r in v[:50]:
        s, e = (r.get("start"), r.get("end")) if isinstance(r, dict) else (None, None)
        if not all(isinstance(x, (int, float)) and not isinstance(x, bool) and x == x and 0 <= x <= 360000 for x in (s, e)):
            bad.append("区間の形が正しくありません")
        elif e <= s:
            bad.append("区間 %s〜%s: 終了が開始より前です" % (hms(s), hms(e)))
        elif e - s > RANGE_MAX_SEC:
            bad.append("区間 %s〜%s: 1つの区間は 60 分までです" % (hms(s), hms(e)))
        elif len(ok) >= RANGE_MAX:
            bad.append("区間 %s〜%s: 1本の配信の区間は %d 個までです" % (hms(s), hms(e), RANGE_MAX))
        elif (s, e) not in ok:
            ok.append((s, e))
    return ok, bad


def parse_cut(v):
    """依頼のカット(① のパック)-> "none" / "silence" か None(無い・知らない値 = ホームの設定)"""
    return v if v in CUT_LABELS else None


def parse_weights(v):
    """依頼の解析の重み {"audio", "chat", "comments"}(0〜3)-> スタジオの解析の設定の名前 {"wAudio", "wChat", "wComments"} か None(無い・形が違う)"""
    if not isinstance(v, dict):
        return None
    out = {}
    for src, dst in (("audio", "wAudio"), ("chat", "wChat"), ("comments", "wComments")):
        x = v.get(src)
        if isinstance(x, bool) or not isinstance(x, (int, float)) or x != x or not 0 <= x <= 3:
            return None
        out[dst] = round(float(x), 1)
    return out


def parse_video_tracks(v):
    """依頼の「映像トラックの数」(1〜5。1.4.0 のアプリが ① 全自動のときに送る)-> 1〜5 の整数(無い・形が違う = 既定の 1)"""
    return v if isinstance(v, int) and not isinstance(v, bool) and 1 <= v <= VIDEO_TRACKS_MAX else VIDEO_TRACKS_DEFAULT


def _safe_name(name):
    """JSON に書かれたファイル名がフォルダの直下の名前か(区切り・..・ドライブを含まない)"""
    return (isinstance(name, str) and 0 < len(name) <= 240 and name not in (".", "..") and not any(c in name for c in '/\\:*?"<>|')
            and not any(ord(c) < 32 for c in name))


def _streamer(name):
    """配信者の名前 -> (照らし合わせた名前 か None, 知らせ)"""
    s = str(name or "").strip()
    if not s:
        return None, ""
    try:
        who, _hex = colors.resolve(s)
        return who, ""
    except ValueError:
        return None, "配信者「%s」がメンバーと合わないので、字幕の色なしで進めます" % s[:60]


class Intake:
    def __init__(self, prefs, runner, data_dir, log=None, clock=None, probe=None, info=None, interval=INTERVAL, settle=SETTLE,
                 norm_probe=None, norm_run=None):
        """prefs: src/home/prefs.py の Prefs(節 intake)。runner: まとめて実行を返す関数(AutoRunner)。data_dir: ホームの作業データ(app)。
        probe・info: 動画・配信を調べる関数(テストで差し替える)。norm_probe・norm_run: 30fps の判定・作り直し(既定は ytt_core.normalize)"""
        self.prefs, self.runner, self.data_dir = prefs, runner, data_dir
        self.log = log or (lambda msg: None)
        self.clock = clock or time.time
        self.probe = probe or probe_video
        self.norm_probe = norm_probe or normalize.probe
        self.norm_run = norm_run or normalize.normalize
        self.info = info or youtube_info
        self.interval, self.settle = interval, settle
        self.state_path = os.path.join(data_dir, STATE_FILE)
        self.lock = threading.Lock()        # 見る処理(scan)を1つずつ
        self.wake = threading.Event()
        self.closed = False
        self.thread = None
        self._seen_size = {}                # パス -> (大きさ, 更新時刻, 最初に今の形で見た時刻)
        self.state = "off"
        self.message = ""
        self.last_scan = None
        self.held = 0                       # 1日の上限で次の日に回した数
        self.st = self._load_state()

    # ------------------------------------------------------------ 覚えておく中身
    def _load_state(self):
        try:
            d = fsio.read_json_file(self.state_path, 2 * 1024 * 1024)
        except (OSError, ValueError):
            d = None
        d = d if isinstance(d, dict) else {}
        return {"videos": d.get("videos") if isinstance(d.get("videos"), dict) else {},
                "files": d.get("files") if isinstance(d.get("files"), dict) else {},
                "daily": d.get("daily") if isinstance(d.get("daily"), dict) else {},
                "requests": [r for r in d.get("requests") or [] if isinstance(r, dict)   # 0.15.0 で desktop.ini などを断った記録は消す
                             and not is_os_file(str(r.get("title") or ""))][:KEEP_REQUESTS]}

    def _save_state(self):
        for k in ("videos", "files"):
            m = self.st[k]
            while len(m) > KEEP_SEEN:
                m.pop(next(iter(m)))
        today = self._today()
        self.st["daily"] = {k: v for k, v in self.st["daily"].items() if k >= (datetime.date.fromisoformat(today) - datetime.timedelta(days=7)).isoformat()}
        try:
            os.makedirs(self.data_dir, exist_ok=True)
            fsio.atomic_write(self.state_path, json.dumps(dict(self.st, v=1), ensure_ascii=False).encode("utf-8"))
        except OSError as e:
            self.log("依頼の受付: 記録を書けませんでした(%s)" % (e.strerror or e.__class__.__name__))

    def _today(self):
        return datetime.datetime.fromtimestamp(self.clock()).date().isoformat()

    # ------------------------------------------------------------ 動かす・止める
    def start(self):
        if self.thread is None:
            self.thread = threading.Thread(target=self._loop, name="intake", daemon=True)
            self.thread.start()

    def close(self):
        self.closed = True
        self.wake.set()

    def _loop(self):
        while not self.closed:
            try:
                self.scan()
            except Exception as e:   # 想定外でも見張りは続ける(次の回でやり直す)
                self.state, self.message = "error", "内部エラー: %s %s" % (e.__class__.__name__, str(e)[:200])
                self.log("依頼の受付: " + self.message)
            # 見る間隔: 設定の interval(段9 9-4。ホームの「依頼の受付」で変える)。テストで interval を渡したときはそれ
            self.wake.wait(self.interval if self.interval != INTERVAL else float(self._cfg().get("interval") or INTERVAL))
            self.wake.clear()

    def snapshot(self):
        cfg = self._cfg()
        # 見る処理が長い(動画を 30fps にそろえている間は数分〜)ときに画面の表示を止めないよう、ロックは短く待つだけ(取れなくても読むだけなので安全)
        got = self.lock.acquire(timeout=0.3)
        try:
            return dict(cfg, state=self.state, stateLabel=STATE_LABELS[self.state], message=self.message,
                        lastScan=int(self.last_scan * 1000) if self.last_scan else None,
                        today=int(self.st["daily"].get(self._today(), 0)), held=self.held,
                        requests=[dict(r) for r in list(self.st["requests"])])
        finally:
            if got:
                self.lock.release()

    def _cfg(self):
        try:
            return dict(self.prefs.get(["intake"])["intake"])
        except (OSError, ValueError, KeyError):
            import prefs as prefs_mod
            return dict(prefs_mod.DEFAULTS["intake"])

    # ------------------------------------------------------------ 見る
    def scan(self):
        with self.lock:
            cfg = self._cfg()
            self.last_scan = self.clock()
            if not cfg.get("enabled"):
                self.state, self.message = "off", "オフです(設定でオンにすると、フォルダを見張ります)"
                return
            folder = cfg.get("folder") or ""
            if not folder:
                self.state, self.message = "error", "見張るフォルダが決まっていません(設定で Dropbox のフォルダを指定してください)"
                return
            if fsio.is_network_path(folder) or not os.path.isdir(folder):
                self.state, self.message = "error", "見張るフォルダが見つかりません: %s" % folder
                return
            self.state, self.message = "watching", ""
            self.held = 0
            try:
                names = sorted(os.listdir(folder))
            except OSError as e:
                self.state, self.message = "error", "フォルダを読めませんでした(%s)" % (e.strerror or e.__class__.__name__)
                return
            files = {}
            for n in names:
                p = os.path.join(folder, n)
                if (n.startswith((".", "~")) or n.lower().endswith((".tmp", ".part", ".crdownload", ".download", ".partial")) or is_os_file(n, p)
                        or not os.path.isfile(p)):
                    continue
                files[n] = p
            ready = {n: p for n, p in files.items() if self._settled(p)}
            self._seen_size = {p: v for p, v in self._seen_size.items() if p in files.values()}
            items = sorted(ready.items(), key=lambda kv: os.path.getmtime(kv[1]) if os.path.exists(kv[1]) else 0)
            claimed = set()
            for n, p in items:   # 友人のプログラムの依頼を先に(その動画を手で送ったものと取り違えない)
                if n.endswith(REQ_SUFFIX):
                    claimed |= self._handle_request_json(folder, n, p, files, ready, cfg)
            for n, p in items:
                if n in claimed or n.endswith(REQ_SUFFIX) or not os.path.exists(p):
                    continue
                m = APP_FILE_RE.match(n)
                if m and (m.group(1) + REQ_SUFFIX) in files:
                    continue   # JSON はあるが、まだそろっていない(同期の途中)
                if m and self.clock() - os.path.getmtime(p) < WAIT_FILES:
                    continue   # 友人のプログラムの動画で、JSON がまだ届いていない
                ext = os.path.splitext(n)[1].lower()
                if ext in VIDEO_EXT:
                    self._handle_manual_video(folder, n, p, cfg)
                elif ext in TEXT_EXT:
                    self._handle_text(folder, n, p, cfg)
                else:
                    self._record(folder, "video", "manual", n, [n], "", "", [], [{"label": n, "state": "rejected",
                                 "reason": "受け付けない種類のファイルです(動画 %s か、URL を書いた .txt)" % " ".join(VIDEO_EXT)}])
            if self.held:
                self.message = "今日の上限(%d 件)に達したので、%d 件を明日に回します" % (cfg["dailyMax"], self.held)

    def _settled(self, p):
        try:
            s = os.stat(p)
        except OSError:
            return False
        now = self.clock()
        cur = (s.st_size, s.st_mtime)
        prev = self._seen_size.get(p)
        if prev is None or prev[:2] != cur:
            self._seen_size[p] = cur + (now,)
            return False
        return now - prev[2] >= self.settle and now - s.st_mtime >= self.settle

    def _room(self, cfg):
        """今日あと何件受け付けられるか"""
        return max(0, int(cfg["dailyMax"]) - int(self.st["daily"].get(self._today(), 0)))

    def _count(self, n=1):
        t = self._today()
        self.st["daily"][t] = int(self.st["daily"].get(t, 0)) + n

    # ------------------------------------------------------------ 依頼の種類ごと
    def _read_text(self, p):
        if os.path.getsize(p) > TEXT_MAX:
            raise ValueError("ファイルが大きすぎます(%d KB まで)" % (TEXT_MAX // 1024))
        with open(p, "rb") as f:
            return decode_text(f.read(TEXT_MAX + 1))

    def _handle_request_json(self, folder, n, p, files, ready, cfg):
        """友人のプログラムの依頼。-> この依頼が使ったファイルの名前の集まり"""
        rid = n[:-len(REQ_SUFFIX)]
        try:
            d = json.loads(self._read_text(p))
        except (ValueError, OSError) as e:
            self._record(folder, "url", "app", n, [n], "", "", [], [{"label": n, "state": "rejected", "reason": "依頼の形が読めません(%s)" % str(e)[:80]}])
            return {n}
        if not isinstance(d, dict) or d.get("v") != 1 or d.get("kind") not in ("video", "url") or not REQ_ID_RE.match(rid):
            self._record(folder, "url", "app", n, [n], "", "", [], [{"label": n, "state": "rejected", "reason": "依頼の形が正しくありません"}], rid=rid)
            return {n}
        memo = str(d.get("memo") or "")[:MEMO_MAX]
        flow = d.get("flow") if d.get("flow") in FLOW_LABELS else "check"   # 1.0.0 のアプリは flow を送らない = 今までどおり ②
        speakers = parse_speakers(d.get("speakers"))   # 話す人(1.3.0 のアプリ。無ければ話者分離しない)
        tracks = parse_video_tracks(d.get("videoTracks")) if flow == "auto" else None   # 映像トラックの数 1〜5・既定 1(パックを作る ① だけ)
        cut = parse_cut(d.get("cut")) if flow == "auto" else None   # カットの方法(パックを作る ① だけ。無ければホームの設定)
        if d["kind"] == "url":
            raw = [it for it in (d.get("items") if isinstance(d.get("items"), list) else [])[:MAX_URLS] if isinstance(it, dict)]
            lines = "\n".join("%s %s" % (str(it.get("url") or "")[:300], it.get("top", cfg["top"])) for it in raw)
            # 時刻で指定した区間(配信の ID ごと。③ = 解析までの依頼では使わない)
            ranges = {youtube_id(str(it.get("url") or "")[:300]): parse_ranges(it.get("ranges")) for it in raw} if flow != "manual" else {}
            if self._room(cfg) <= 0:
                self.held += 1
                return {n}
            who, note = _streamer(d.get("streamer"))   # 2.1.0 のアプリは URL の依頼にも 1 人目の名前を付ける。無い・合わない = 今までどおりチャンネル名から
            self._process_urls(folder, n, [n], lines, cfg, "app", memo, rid, flow, speakers, tracks, ranges=ranges, cut=cut,
                               weights=parse_weights(d.get("weights")), streamer=who, streamer_note=note)
            return {n}
        names = d.get("files") if isinstance(d.get("files"), list) else []
        names = [x for x in names if _safe_name(x)][:20]
        if not names:
            self._record(folder, "video", "app", n, [n], "", memo, [], [{"label": n, "state": "rejected", "reason": "動画の名前が書かれていません"}], rid=rid)
            return {n}
        missing = [x for x in names if x not in ready]
        if missing:
            if self.clock() - os.path.getmtime(p) > WAIT_FILES:
                self._record(folder, "video", "app", names[0], [n] + [x for x in names if x in files], d.get("streamer") or "", memo, [],
                             [{"label": x, "state": "rejected", "reason": "動画が届きませんでした(送り直してください)"} for x in missing], rid=rid)
            return {n} | set(names)
        if self._room(cfg) <= 0:
            self.held += 1
            return {n} | set(names)
        who, note = _streamer(d.get("streamer"))
        results, runs = [], []
        for x in names:
            label = APP_FILE_RE.match(x).group(2) if APP_FILE_RE.match(x) else x
            res = self._accept_video(files[x], label, who, cfg, rid, flow, folder, speakers, tracks, cut)
            results.append(dict(res, label=label))
            runs += [res["runId"]] if res.get("runId") else []
        if note:
            results.append({"label": "配信者", "state": "accepted", "reason": note})
        self._record(folder, "video", "app", results[0]["label"], [n] + names, who or "", memo, runs, results, flow, speakers, rid=rid, tracks=tracks, cut=cut)
        return {n} | set(names)

    def _handle_manual_video(self, folder, n, p, cfg):
        if self._room(cfg) <= 0:
            self.held += 1
            return
        m = NAME_PREFIX_RE.match(os.path.splitext(n)[0])
        who, note = (None, "")
        if m:
            who, note = _streamer(re.findall(r"【([^】]+)】", m.group(1))[0])
        res = self._accept_video(p, n, who, cfg, None, "check", folder)
        results = [dict(res, label=n)] + ([{"label": "配信者", "state": "accepted", "reason": note}] if note else [])
        self._record(folder, "video", "manual", n, [n], who or "", "", [res["runId"]] if res.get("runId") else [], results)

    def _handle_text(self, folder, n, p, cfg):
        try:
            text = self._read_text(p)
        except (ValueError, OSError) as e:
            self._record(folder, "url", "manual", n, [n], "", "", [], [{"label": n, "state": "rejected", "reason": str(e)[:120]}])
            return
        if n.lower().endswith(".url"):
            text = parse_url_file(text)
        if self._room(cfg) <= 0:
            self.held += 1
            return
        self._process_urls(folder, n, [n], text, cfg, "manual", "", None, "check")

    def _process_urls(self, folder, title, moved, text, cfg, source, memo, rid, flow="check", speakers=None, tracks=None, ranges=None, cut=None, weights=None,
                      streamer=None, streamer_note=""):
        """ranges = {配信の ID: (区間の一覧, 断った理由)}(友人が時刻で指定した区間)。同じ配信を前に受け付けていても断らない(解析などは使い回す)。
        streamer = 照らし合わせ済みの配信者の名前か None(None = まとめて実行がチャンネル名などから決める)・streamer_note = 合わなかったときの知らせ"""
        ok, bad = parse_lines(text, int(cfg["top"]))
        results = [{"label": b["line"], "state": "rejected", "reason": b["reason"]} for b in bad]
        todo, seen, known = [], set(), []
        room = self._room(cfg)
        for it in ok[:MAX_URLS]:
            rs, rbad = (ranges or {}).get(it["id"]) or ([], [])
            it["top"] = min(TOP_MAX, max(it["top"], len(rs)))   # 切り抜く数は区間の数より小さくしない
            how = "指定 %d + 自動 %d" % (len(rs), it["top"] - len(rs)) if rs else "%d 個" % it["top"]
            label = "https://www.youtube.com/watch?v=%s(%s)" % (it["id"], how)
            results += [{"label": label, "state": "rejected", "reason": r} for r in rbad]
            if it["id"] in seen:
                results.append({"label": label, "state": "rejected", "reason": "同じ配信が2回書かれています(1回だけ受け付けました)"})
                continue
            if len(todo) >= room:
                results.append({"label": label, "state": "rejected", "reason": "今日の上限(%d 件)を超えたので受け付けませんでした(明日送り直してください)" % cfg["dailyMax"]})
                continue
            info = self.info(it["id"]) or {}
            if info.get("title"):   # 題名が分かれば、断った理由の行も URL ではなく題名で出す(一覧で読めるように。2026-10-04)
                label = "%s(%s)" % (info["title"], how)
                known.append(info["title"])
            if info.get("live") in ("is_live", "is_upcoming", "post_live"):
                results.append({"label": label, "state": "rejected", "reason": "配信中・配信前の配信です(終わって見られるようになってから送ってください)"})
                continue
            if info.get("duration") and info["duration"] > float(cfg["maxHours"]) * 3600:
                results.append({"label": label, "state": "rejected", "reason": "配信が長すぎます(%.1f 時間。上限 %s 時間)" % (info["duration"] / 3600, cfg["maxHours"])})
                continue
            if rs and info.get("duration"):   # 配信の長さの外の区間: 終わりで切る。長さより後から始まるものは断る
                late = [(s, e) for s, e in rs if s >= info["duration"]]
                results += [{"label": label, "state": "rejected", "reason": "区間 %s〜%s: 配信の長さ(%s)より後です" % (hms(s), hms(e), hms(info["duration"]))} for s, e in late]
                rs = [(s, min(e, info["duration"])) for s, e in rs if s < info["duration"]]
                it["top"] -= len(late)   # 断った区間の分は、自動で埋めない
                if it["top"] <= 0:
                    continue   # 指定した区間が全部だめ(自動の分も無い): この配信は流さない
            seen.add(it["id"])
            todo.append(dict(it, title=info.get("title") or "", channel=info.get("channel") or "", label=label, checked=bool(info), ranges=rs,
                             duration=info.get("duration")))
        for it in ok[MAX_URLS:]:
            results.append({"label": it["line"], "state": "rejected", "reason": "1つの依頼に書けるのは %d 本までです" % MAX_URLS})
        runs = []
        if todo:
            try:
                out = self.runner().start_request([{k: it[k] for k in ("id", "top", "title", "channel", "ranges", "duration")} for it in todo], request_id=rid,
                                                  flow=flow, deliver_dir=os.path.join(folder, OUT_DIR), speakers=speakers,
                                                  video_tracks=tracks, cut=cut, weights=weights, streamer=streamer)
            except ValueError as e:
                out = {"runs": [], "skipped": [{"id": it["id"], "reason": str(e)} for it in todo]}
            by_vid = {r["videoId"]: r for r in out.get("runs") or []}
            skip = {s.get("id"): s.get("reason") for s in out.get("skipped") or []}
            for it in todo:
                r = by_vid.get(it["id"])
                if r:
                    runs.append(r["id"])
                    self.st["videos"][it["id"]] = int(self.clock())
                    self._count()
                    note = "" if it["checked"] else "配信の長さを確かめられませんでした(そのまま進めます)"
                    results.append({"label": (it["title"] or it["label"]), "state": "accepted", "reason": note, "runId": r["id"]})
                else:
                    results.append({"label": it["label"], "state": "rejected", "reason": skip.get(it["id"]) or "まとめて実行に入れられませんでした"})
        if not results:
            results.append({"label": title, "state": "rejected", "reason": "URL が書かれていません"})
        first = next((r["label"] for r in results if r["state"] == "accepted"), known[0] if known else title)   # 受け付けた配信 → 題名の分かった配信 → ファイル名
        n_ranges = sum(len(it["ranges"]) for it in todo)
        if streamer_note:   # 動画の依頼と同じ形の知らせ(受け付けた・断ったの数には入れない)
            results.append({"label": "配信者", "state": "accepted", "reason": streamer_note})
        self._record(folder, "url", source, first, moved, streamer or "", memo, runs, results, flow, speakers, rid=rid, tracks=tracks, cut=cut, weights=weights,
                     ranges_label="区間: %s" % "・".join(["%s〜%s" % (hms(s), hms(e)) for it in todo for s, e in it["ranges"]][:3]) +
                     (" ほか %d" % (n_ranges - 3) if n_ranges > 3 else "") if n_ranges else "")

    def _accept_video(self, p, label, who, cfg, rid, flow="check", folder=None, speakers=None, tracks=None, cut=None):
        """1本の動画を確かめて、作業データへコピーし、文字起こしに入れる。-> {"state", "reason", "runId"?}。
        前に受け付けた動画と同じでも断らない(映像トラックの数などを変えて送り直せるように。2026-10-02 ユーザー)"""
        ext = os.path.splitext(p)[1].lower()
        if ext not in VIDEO_EXT:
            return {"state": "rejected", "reason": "受け付けない種類のファイルです"}
        try:
            size = os.path.getsize(p)
            if size > float(cfg["maxGB"]) * 1024 ** 3:
                return {"state": "rejected", "reason": "動画が大きすぎます(%.1f GB。上限 %s GB)" % (size / 1024 ** 3, cfg["maxGB"])}
        except OSError as e:
            return {"state": "rejected", "reason": "動画を読めませんでした(%s)" % (e.strerror or e.__class__.__name__)}
        pr = self.probe(p)
        if not pr.get("ok"):
            return {"state": "rejected", "reason": pr.get("reason") or "動画として読めませんでした"}
        if pr.get("duration") and pr["duration"] > float(cfg["maxHours"]) * 3600:
            return {"state": "rejected", "reason": "動画が長すぎます(%.1f 時間。上限 %s 時間)" % (pr["duration"] / 3600, cfg["maxHours"])}
        day = self._today()
        dest_dir = os.path.join(self.data_dir, "intake", day)
        base = re.sub(r'[\\/:*?"<>|\x00-\x1f]', "_", label)[:150] or ("video" + ext)
        if not base.lower().endswith(ext):
            base += ext
        try:
            os.makedirs(dest_dir, exist_ok=True)
            dest = os.path.join(dest_dir, base)
            if os.path.exists(dest):
                dest = os.path.join(dest_dir, "%s-%s%s" % (os.path.splitext(base)[0], uuid.uuid4().hex[:6], ext))
            tmp = dest + ".copying"
            shutil.copyfile(p, tmp)
            os.replace(tmp, dest)
        except OSError as e:
            return {"state": "rejected", "reason": "作業データへコピーできませんでした(%s)" % (e.strerror or e.__class__.__name__)}
        dest, note = self._normalize_copy(dest, label)   # 30fps でなければ写しを作り直す(元の動画は触らない。失敗しても写しのまま続ける)
        try:
            run = self.runner().start_file(dest, title=os.path.splitext(label)[0], streamer=who, request_id=rid, flow=flow,
                                           deliver_dir=os.path.join(folder, OUT_DIR) if folder else None, speakers=speakers,
                                           video_tracks=tracks, cut=cut)
        except ValueError as e:
            try:
                os.remove(dest)
            except OSError:
                pass
            return {"state": "rejected", "reason": "文字起こしに入れられませんでした(%s)" % e}
        self._count()
        return {"state": "accepted", "reason": note, "runId": run["id"]}

    def _normalize_copy(self, dest, label):
        """作業データへコピーした動画 dest が 30fps(H.264・yuv420p・AAC)でなければ、写しを作り直して置き換える(Q1。2026-10-04 ユーザー決定)。
        友人の元のファイル(Dropbox 側)は触らない。-> (使うパス, 知らせ)。知らせは作り直せなかったときだけ(受付済みの「理由.txt」・依頼の一覧に残る)。
        作り直せなくても依頼は止めない(写しのまま続ける)。出力は mp4 なので、拡張子が違えば .mp4 の名前にして古い写しを消す"""
        try:
            need, why = normalize.needs_normalize(self.norm_probe(dest))
        except Exception as e:   # 調べられなくても依頼は進める
            need, why = False, []
            self.log("依頼の受付: %s の形を調べられませんでした(%s)" % (label, e.__class__.__name__))
        if not need:
            return dest, ""
        target = os.path.splitext(dest)[0] + ".mp4"
        if target != dest and os.path.exists(target):
            target = "%s-%s.mp4" % (os.path.splitext(dest)[0], uuid.uuid4().hex[:6])
        last = [-1]

        def progress(x):
            pct = int(x * 100)
            if pct != last[0]:
                last[0] = pct
                self.message = "30fps にそろえています: %s(%d%%)" % (label[:60], pct)
        self.message = "30fps にそろえています: %s" % label[:60]
        self.log("依頼の受付: %s を 30fps にそろえます(%s)" % (label, " / ".join(why)))
        try:
            with jobs.SLOTS.slot("intake", "30fps にそろえる: " + label, cancelled=lambda: self.closed) as ok:
                if not ok:
                    raise normalize.Cancelled("取り消しました")
                self.norm_run(dest, target, cancelled=lambda: self.closed, on_progress=progress)
        except normalize.NormalizeError as e:
            self.log("依頼の受付: %s を 30fps にできませんでした。写しのまま進めます(%s)" % (label, e))
            return dest, "30fps にそろえられませんでした。元の動画のまま進めます(%s)" % str(e)[:150]
        except Exception as e:
            self.log("依頼の受付: %s を 30fps にできませんでした。写しのまま進めます(%s %s)" % (label, e.__class__.__name__, e))
            return dest, "30fps にそろえられませんでした。元の動画のまま進めます(%s)" % e.__class__.__name__
        finally:
            self.message = ""
        if target != dest:
            try:
                os.remove(dest)
            except OSError:
                pass
        return target, ""

    # ------------------------------------------------------------ 後始末と記録
    def _record(self, folder, kind, source, title, moved, streamer, memo, runs, items, flow="check", speakers=None, rid=None, tracks=None, cut=None,
                weights=None, ranges_label=""):
        accepted = any(i["state"] == "accepted" and i.get("label") != "配信者" for i in items)
        state = "accepted" if accepted else "rejected"
        reason = "" if accepted else next((i["reason"] for i in items if i["state"] == "rejected"), "")
        rec = {"id": uuid.uuid4().hex[:10], "kind": kind, "source": source, "title": str(title)[:200], "streamer": streamer or "",
               "memo": memo or "", "received": int(self.clock() * 1000), "state": state, "stateLabel": REQ_LABELS[state], "reason": reason,
               "flow": flow, "flowLabel": FLOW_LABELS.get(flow, ""),
               "speakersLabel": ("配信者: %d人" % speakers["count"] + ("(%s)" % "・".join(speakers["names"]) if speakers["names"] else "") +
                                 ("・色の指定 %d人" % len(speakers["styles"]) if speakers.get("styles") else "")) if speakers else "",
               "tracksLabel": "映像トラック: %d本" % tracks if tracks else "",
               "rangesLabel": ranges_label, "cutLabel": "カット: %s" % CUT_LABELS[cut] if cut in CUT_LABELS else "",
               "weightsLabel": "重み: 音声 %s・チャット %s・コメント %s" % (weights["wAudio"], weights["wChat"], weights["wComments"]) if weights else "",
               "runIds": runs, "items": [{k: i.get(k, "") for k in ("label", "state", "reason")} for i in items][:30]}
        self.st["requests"] = ([rec] + self.st["requests"])[:KEEP_REQUESTS]
        self._move(folder, moved, state, items)
        self._notify_rejected(folder, rid, rec["title"], items)
        self._save_state()
        self.log("依頼の受付: %s %s(%s)" % (REQ_LABELS[state], rec["title"], reason or "%d 件" % len(runs)))

    def _notify_rejected(self, folder, rid, title, items):
        """友人のアプリの依頼で、受け付けなかった物があれば 出力/<依頼 id>__<題>.失敗.txt に理由を置く(アプリの「受け取る」に出る。段9 9-4)。
        処理が始まってから止まったときは autorun の _deliver_failure が同じ形で置く"""
        bad = [i for i in items if i["state"] == "rejected"]
        if not bad or not rid or not REQ_ID_RE.match(str(rid)):
            return
        whole = not any(i["state"] == "accepted" and i.get("label") != "配信者" for i in items)
        name = re.sub(r'[\\/:*?"<>|\x00-\x1f]', "_", "%s__%s" % (rid, title or "依頼"))[:180] + ".失敗.txt"
        text = ("依頼を受け付けられませんでした。" if whole else "依頼の一部を受け付けられませんでした(ほかは処理します)。") + "\r\n" + \
            "\r\n".join("%s: %s" % (i["label"], i.get("reason") or "受け付けられませんでした") for i in bad)
        try:
            out = os.path.join(folder, OUT_DIR)
            os.makedirs(out, exist_ok=True)
            with open(os.path.join(out, name), "w", encoding="utf-8-sig", newline="") as f:
                f.write(text + "\r\n")
        except OSError as e:
            self.log("依頼の受付: 断った理由を 出力 に置けませんでした(%s)" % (e.strerror or e.__class__.__name__))

    def _move(self, folder, names, state, items):
        """元のファイルを 受付済み\\日付\\ か 失敗\\ へ(消さない)。断ったものには理由の .txt を添える"""
        sub = os.path.join(folder, DONE_DIR, self._today()) if state == "accepted" else os.path.join(folder, FAIL_DIR)
        try:
            os.makedirs(sub, exist_ok=True)
        except OSError:
            return
        for n in names:
            src = os.path.join(folder, n)
            if not os.path.isfile(src):
                continue
            dst = os.path.join(sub, n)
            if os.path.exists(dst):
                stem, ext = os.path.splitext(n)
                dst = os.path.join(sub, "%s-%s%s" % (stem, uuid.uuid4().hex[:6], ext))
            try:
                fsio.replace_retry(src, dst)
            except OSError as e:
                self.log("依頼の受付: %s を移せませんでした(%s)" % (n, e.strerror or e.__class__.__name__))
            self._seen_size.pop(src, None)
        bad = [i for i in items if i["state"] == "rejected" or i.get("reason")]
        if bad and names:
            text = "\r\n".join("%s: %s%s" % (i["label"], REQ_LABELS.get(i["state"], i["state"]), "(%s)" % i["reason"] if i.get("reason") else "") for i in items)
            try:
                with open(os.path.join(sub, os.path.splitext(names[0])[0] + ".理由.txt"), "w", encoding="utf-8-sig", newline="") as f:
                    f.write(text + "\r\n")
            except OSError:
                pass
