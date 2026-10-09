# -*- coding: utf-8 -*-
"""録画の中身(線 D の P1。plan/line-d-live-clipping.md の 0・2〜4)。HTTP は recorder.py。

1つの録画 = 配信1本(フォルダ <録画の置き場所>/<録画の id>/)。切れて繋ぎ直すたびに「セッション」(session_001/…)を増やす:
  <id>/recording.json            録画の記録(URL・状態・セッションの一覧。一時ファイルに書いてから置き換える)
  <id>/session_001/index.m3u8     ffmpeg が書く HLS の再生リスト(-hls_playlist_type event・program_date_time = 受信した時刻)
  <id>/session_001/seg_000000.ts  セグメント(-c copy の写し。作り直さない)
画面に出す再生リストは、全部のセッションを #EXT-X-DISCONTINUITY でつないで、ここで作る(build_playlist)。

取得のしかた(source):
  streamlink … 本番。`python -m streamlink --stdout <URL> <画質>` の出力を ffmpeg の標準入力へ(シェルを通さない引数のリスト)
  direct     … テスト用。HLS の URL を直接 ffmpeg に渡す(手元の 127.0.0.1 の URL だけ。起動の引数 --source direct)

切れたら: 5 → 10 → 30 秒(以後 30 秒)の間を空けて繋ぎ直す。データの来ない時間が続いたら「終了」:
  配信の前(まだ1つも取れていない)… WAIT_START 秒、途中で切れた … IDLE_END 秒。
  取得がきれいに終わった(Recording._source_ended)ときは、配信が終わったとして、繋ぎ直さずに「終了」にする
起動時の復旧(recover): 書きかけ(*.tmp)を消す → 読めない再生リストは「使えないセッション」→ 録画中だった物は前のセッションを
「中断」にして、新しいセッションで録画を続ける。

重い処理の同時実行の上限(ytt_core/jobs.py の SLOTS)は通さない: 録画は作り直さない写し(-c copy。CPU 数%)で軽く、
配信中は順番待ちで止められない(待つと欠ける)ため。代わりに録画のプロセスの優先度を「通常より上」にする(計画の 0-3)。
"""
import contextlib
import datetime
import json
import os
import re
import secrets
import shutil
import stat
import subprocess
import sys
import threading
import time
import unicodedata
import urllib.parse
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))   # src/(この ingest の2つ上)
if ROOT not in sys.path:   # 共通部品 ytt(src/ の中)
    sys.path.append(ROOT)
from ytt import fsio, recproto, tools as ytools  # noqa: E402

SCHEMA = "ytt-recorder/v1"
DEFAULT_FOLDER = r"E:\Video\live-rec"      # 録画の置き場所の既定(2026-10-04 ユーザー決定。ホームの設定で変えられる)
# 録画の id・セッション・セグメントの形と時刻の書き方は ytt_core/recproto.py の 1 か所(入口の live_export・配信中の検出のワーカーと同じ物。2026-10-09 見直し T8)
REC_ID_RE, SESSION_RE, SEG_RE = recproto.REC_ID_RE, recproto.SESSION_RE, recproto.SEG_RE
ACTIVE = ("waiting", "recording", "reconnecting")   # ほかの状態: stopped(手で止めた)・ended(配信が終わった)・error
QUALITIES = {"best": "best", "1080p": "1080p60,1080p,best", "720p": "720p60,720p,best"}   # streamlink の画質(左から順に試す)
DEFAULT_QUALITY = "1080p"   # 既定(2026-10-04 ユーザー決定): 4K の配信で容量が膨らむのを避けつつ、速報版の見た目を保つ。720p・best も選べる
YT_HOSTS = ("youtube.com", "www.youtube.com", "m.youtube.com", "youtu.be")
BACKOFF = (5, 10, 30)          # 繋ぎ直すまでの秒(最後の値を繰り返す)
IDLE_END = 600                 # 途中で切れて、この秒数データが来なければ「終了」(終わった配信は --stream-types hls で取れなくなる)
WAIT_START = 6 * 3600          # 配信の前から待つ上限(秒)
STALL_SEC = 60                 # 録画中にこの秒数新しいセグメントが出なければ、止まったとみなして繋ぎ直す
FIRST_SEG_SEC = 120            # セッションを始めてから最初のセグメントまで待つ上限(秒)
MIN_FREE = 1024 ** 3           # 空きがこれより少なくなったら録画を止める(ディスクを埋め切らない)
LOW_FREE = 20 * 1024 ** 3      # これより少なければ注意(1時間あたり約 3〜4GB)
HLS_TIME = 4
SOURCE_TROUBLE = ("No new segments", "Reloading failed", "[error]", "Read timeout")   # streamlink の記録に出たら「切れた」(終わりではない)
ARCHIVE = "archive"
ENDED = "配信が終わったので録画を終えました"
ARCHIVE_MIN_SEC = 90           # 取れた長さがこれを超えて、
ARCHIVE_SPEED = 3.0            # 実際の時間のこれ倍より速く取れたら、配信ではなくアーカイブを頭から取っている(止める)
TITLE_MAX = 200
OEMBED = "https://www.youtube.com/oembed"   # 題の取得(fetch_title)
TITLE_TRIES = (0, 20, 60)      # 題を取りに行くまでの秒(取れなければ次。全部だめなら題なしのまま)
URL_MAX = 500
PLAYLIST_MAX = 16 * 1024 * 1024
GAP_TOL = 1.0                  # 区間のセグメントの間がこれより空いていたら「欠け」(P2 の書き出し。PDT の揺れは 0.1 秒ほど)
RANGE_MAX_SEC = 3 * 3600       # /segments で一度に聞ける区間の長さ
SEGMENTS_MAX = 5000
PRIORITY = getattr(subprocess, "ABOVE_NORMAL_PRIORITY_CLASS", 0)   # 録画は「通常より上」(書き出し・文字起こしは「通常より下」)


class RecError(ValueError):
    """画面に出せる理由(400・404・409)。kind は HTTP の応答の error"""
    def __init__(self, message, code=400):
        super().__init__(message)
        self.code = code
        self.kind = {400: "bad_request", 409: "conflict"}.get(code, "not_found")


# ---------- 小さな道具 ----------
_utc_text, now_iso, epoch_iso, iso_epoch = recproto.utc_text, recproto.now_iso, recproto.epoch_iso, recproto.iso_epoch


def to_utc(pdt):
    """ffmpeg の #EXT-X-PROGRAM-DATE-TIME(2026-10-04T15:30:12.345+0900)→ UTC の "…Z"。読めなければ元のまま"""
    s = (pdt or "").strip()
    for fmt in ("%Y-%m-%dT%H:%M:%S.%f%z", "%Y-%m-%dT%H:%M:%S%z"):
        try:
            return _utc_text(datetime.datetime.strptime(s.replace("Z", "+0000"), fmt))
        except ValueError:
            continue
    return s


def pick_segments(flat, start, end, tol=GAP_TOL):
    """区間 [start, end)(epoch 秒)にかかるセグメントと欠け(P2 の書き出しの「取得」。計画の 6 の segments_for)。
    flat: [{"uri", "pdt", "dur", …}](pdt は UTC の "…Z")。-> (時刻順のセグメント, 欠け [(from, to)])。
    欠け = 区間の中で、どのセグメントにも入っていない tol 秒より長い所(繋ぎ直しの間・まだ録れていない終わり・録画の前の頭)"""
    segs = []
    for s in flat:
        e = iso_epoch(s.get("pdt"))
        if e is not None and e < end and e + s["dur"] > start:
            segs.append((e, s))
    segs.sort(key=lambda x: x[0])
    gaps, cursor = [], start
    for e, s in segs:
        if e - cursor > tol:
            gaps.append((cursor, e))
        cursor = max(cursor, e + s["dur"])
    if end - cursor > tol:
        gaps.append((cursor, end))
    return [s for _, s in segs], gaps


def validate_url(url, allow_local=False):
    """録画する URL。YouTube(https)だけ。allow_local=True(テストの direct)は http(s)://127.0.0.1|localhost だけ。-> 整えた URL"""
    if not isinstance(url, str):
        raise RecError("配信の URL を入れてください")
    url = url.strip()
    if not url or len(url) > URL_MAX or any(ord(c) < 33 for c in url):
        raise RecError("配信の URL が正しくありません")
    try:
        u = urllib.parse.urlsplit(url)
        port = u.port
    except ValueError:
        raise RecError("配信の URL が正しくありません")
    host = (u.hostname or "").lower()
    if allow_local:
        if u.scheme in ("http", "https") and host in ("127.0.0.1", "localhost") and not u.username:
            return url
        raise RecError("テストの取得(direct)は手元(127.0.0.1)の URL だけです")
    if u.scheme != "https" or host not in YT_HOSTS or u.username or u.password or port not in (None, 443):
        raise RecError("YouTube の配信の URL(https://www.youtube.com/watch?v=… など)を入れてください")
    return url


def fetch_title(url, endpoint=OEMBED, timeout=8):
    """配信の題(名前を入れずに始めた録画に付ける)。YouTube の oEmbed(鍵なし・題と配信者名だけの小さな JSON)に聞く。
    配信の前(予約)でも返る。取れなければ ""(録画は題なしで続ける)。yt-dlp を使わないのは、録画の部品を軽いままにするため"""
    try:
        req = urllib.request.Request(endpoint + "?" + urllib.parse.urlencode({"url": url, "format": "json"}),
                                     headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            d = json.loads(r.read(256 * 1024).decode("utf-8", "replace"))
    except Exception:
        return ""
    t = d.get("title") if isinstance(d, dict) else None
    if not isinstance(t, str):
        return ""
    # 制御文字と、文字の向きを変える印(題で表示を入れ替えられないように)は落とす
    # (絵文字をつなぐ印 U+200D は残す)
    bidi = "‎‏؜‪‫‬‭‮⁦⁧⁨⁩"
    return "".join(c for c in t if unicodedata.category(c) != "Cc" and c not in bidi).strip()[:TITLE_MAX]


def folder_state(folder):
    """録画の置き場所の様子 -> {"folder", "ok", "message", "freeBytes", "totalBytes"}。
    ドライブが無ければ ok=False(作業データの中へ勝手に逃がさない。画面で置き場所を変えてもらう)"""
    out = {"folder": folder, "ok": False, "message": "", "freeBytes": None, "totalBytes": None}
    if not folder or not os.path.isabs(folder):
        out["message"] = "録画の置き場所が決まっていません(ホームの設定で、ドライブ名からのフォルダを指定してください)"
        return out
    drive = os.path.splitdrive(folder)[0]
    if drive and not os.path.exists(drive + os.sep):
        out["message"] = "録画の置き場所 %s のドライブ %s が見つかりません。ドライブをつなぐか、ホームの「リアルタイム切り抜き」の画面で置き場所を変えてください" % (folder, drive)
        return out
    probe = folder
    while probe and not os.path.exists(probe):
        parent = os.path.dirname(probe)
        if parent == probe:
            break
        probe = parent
    try:
        u = shutil.disk_usage(probe)
    except OSError as e:
        out["message"] = "録画の置き場所を読めません(%s)" % (e.strerror or e.__class__.__name__)
        return out
    out.update(ok=True, freeBytes=u.free, totalBytes=u.total)
    if u.free < MIN_FREE:
        out.update(ok=False, message="録画の置き場所の空きが %d MB しかありません。片付けるか、置き場所を変えてください" % (u.free // 2 ** 20))
    elif u.free < LOW_FREE:
        out["message"] = "空きが少なくなっています(%.1f GB。1時間あたり約 3〜4GB 使います)" % (u.free / 1024 ** 3)
    return out


def parse_playlist(text):
    """ffmpeg の再生リスト -> ([{"uri", "dur", "pdt"}], 終わりの印があるか)。pdt は UTC の "…Z"(無ければ None)"""
    segs, pdt, dur, ended = [], None, None, False
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.startswith("#EXT-X-PROGRAM-DATE-TIME:"):
            pdt = to_utc(line.split(":", 1)[1])
        elif line.startswith("#EXTINF:"):
            try:
                dur = float(line[8:].split(",", 1)[0])
            except ValueError:
                dur = None
        elif line == "#EXT-X-ENDLIST":
            ended = True
        elif not line.startswith("#"):
            if dur is not None and SEG_RE.match(line):
                segs.append({"uri": line, "dur": dur, "pdt": pdt})
            pdt, dur = None, None
    return segs, ended


def build_playlist(sessions, finished, hls_time=HLS_TIME):
    """全セッションをつないだ再生リスト。sessions = [(セッションのフォルダ名, [セグメント])]。finished なら #EXT-X-ENDLIST"""
    durs = [s["dur"] for _, segs in sessions for s in segs]
    target = max([hls_time] + [int(d + 0.999) for d in durs])
    out = ["#EXTM3U", "#EXT-X-VERSION:3", "#EXT-X-PLAYLIST-TYPE:EVENT", "#EXT-X-TARGETDURATION:%d" % target, "#EXT-X-MEDIA-SEQUENCE:0"]
    first = True
    for name, segs in sessions:
        if not segs:
            continue
        if not first:
            out.append("#EXT-X-DISCONTINUITY")   # 繋ぎ直した所(時刻・タイムスタンプが飛ぶ)
        first = False
        for s in segs:
            if s.get("pdt"):
                out.append("#EXT-X-PROGRAM-DATE-TIME:" + s["pdt"])
            out.append("#EXTINF:%.6f," % s["dur"])
            out.append("%s/%s" % (name, s["uri"]))
    if finished:
        out.append("#EXT-X-ENDLIST")
    return "\n".join(out) + "\n"


def read_text(path, limit=PLAYLIST_MAX, attempts=3):
    """小さなテキストを読む。ffmpeg が置き換えている一瞬(Windows の共有違反)は少し待って読み直す。無ければ None"""
    for i in range(attempts):
        try:
            with open(path, "rb") as f:
                data = f.read(limit + 1)
            if len(data) > limit:
                raise ValueError("大きすぎます")
            return data.decode("utf-8", "replace")
        except FileNotFoundError:
            return None
        except PermissionError:
            if i == attempts - 1:
                raise
            time.sleep(0.05 * (i + 1))
    return None


def _is_link(p):
    """シンボリックリンクか、Windows のジャンクション(リパースポイント)か。消すときに先をたどらないため"""
    try:
        st = os.lstat(p)
    except OSError:
        return False
    if stat.S_ISLNK(st.st_mode):
        return True
    return bool(getattr(st, "st_file_attributes", 0) & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400))


def clean_tmp(session_dir):
    """書きかけ(ffmpeg の temp_file の *.tmp)を消す -> 消した数"""
    n = 0
    try:
        names = os.listdir(session_dir)
    except OSError:
        return 0
    for name in names:
        if name.endswith(".tmp"):
            with contextlib.suppress(OSError):
                os.remove(os.path.join(session_dir, name))
                n += 1
    return n


def new_rec_id(url, clock=time.time):
    """録画の id: 日時 + YouTube の動画の id(分かれば)。例 20261004-153012-dQw4w9WgXcQ"""
    stamp = time.strftime("%Y%m%d-%H%M%S", time.localtime(clock()))
    vid = ""
    try:
        u = urllib.parse.urlsplit(url)
        q = urllib.parse.parse_qs(u.query)
        if q.get("v"):
            vid = q["v"][0]
        elif u.hostname == "youtu.be" or u.path.startswith("/live/"):
            vid = u.path.rstrip("/").rsplit("/", 1)[-1]
    except ValueError:
        pass
    vid = re.sub(r"[^A-Za-z0-9_-]", "", vid)[:24]
    return stamp + ("-" + vid if vid else "-" + secrets.token_hex(3))


# ---------- 録画1本 ----------
class Recording:
    """配信1本の録画。状態は self.meta(recording.json と同じ形)。値の変更は self.lock の中で行い、変えたら保存する"""

    def __init__(self, mgr, rid, path, meta):
        self.mgr, self.id, self.dir = mgr, rid, path
        self.meta = meta
        self.lock = threading.RLock()
        self._stop = threading.Event()      # 画面の「停止」
        self._halt = threading.Event()      # 録画の部品の終了(状態は録画中のまま残し、次の起動で続ける)
        self.thread = None
        self.procs = []
        self._cache = {}                    # セッション -> (mtime, size, segs, ended)

    # --- 記録 ---
    def save(self):
        with self.lock:
            data = json.dumps(self.meta, ensure_ascii=False, indent=1).encode("utf-8")
        fsio.atomic_write(os.path.join(self.dir, "recording.json"), data)

    def set(self, **kw):
        with self.lock:
            self.meta.update(kw)
            try:
                self.save()
            except OSError as e:
                self.mgr.log("録画 %s の記録を書けませんでした: %s" % (self.id, e))

    @property
    def active(self):
        return self.meta.get("state") in ACTIVE

    # --- セグメント ---
    def session_names(self):
        try:
            names = [n for n in os.listdir(self.dir) if SESSION_RE.match(n) and os.path.isdir(os.path.join(self.dir, n))]
        except OSError:
            return []
        return sorted(names, key=lambda n: int(SESSION_RE.match(n).group(1)))

    def session_segments(self, name):
        """-> (セグメント, 終わりの印)。読めない再生リストは ([], False)。終わった物は覚えておく"""
        p = os.path.join(self.dir, name, "index.m3u8")
        try:
            st = os.stat(p)
        except OSError:
            return [], False
        c = self._cache.get(name)
        if c and c[0] == st.st_mtime and c[1] == st.st_size:
            return c[2], c[3]
        try:
            text = read_text(p)
        except (OSError, ValueError):
            return [], False
        if text is None:
            return [], False
        segs, ended = parse_playlist(text)
        seen = {s["uri"] for s in c[2]} if c else ()   # 録画中は数秒ごとに書き換わる: 前に確かめたセグメントは調べ直さない
        segs = [s for s in segs if s["uri"] in seen or os.path.isfile(os.path.join(self.dir, name, s["uri"]))]   # 消えたセグメント(手で消した)は出さない
        self._cache[name] = (st.st_mtime, st.st_size, segs, ended)
        return segs, ended

    def all_segments(self):
        return [(n, self.session_segments(n)[0]) for n in self.session_names()]

    def playlist(self):
        return build_playlist(self.all_segments(), not self.active, self.mgr.hls_time)

    def summary(self, detail=False, since=0, sess=None):
        """録画の状態(一覧・status)。sess: all_segments() の結果(呼んだ側が持っていれば渡す)"""
        with self.lock:
            m = dict(self.meta)
        sess = self.all_segments() if sess is None else sess
        segs = [x for _, s in sess for x in s]
        e = iso_epoch(segs[-1].get("pdt")) if segs else None   # 録画済みの最後 = 最後のセグメントの終わり
        out = {"id": self.id, "url": m.get("url"), "title": m.get("title") or "", "quality": m.get("quality"), "state": m.get("state"),
               "message": m.get("message") or "", "created": m.get("created"), "endedAt": m.get("endedAt"),
               "segments": len(segs), "seconds": round(sum(x["dur"] for x in segs), 3),
               "firstPdt": next((x["pdt"] for x in segs if x.get("pdt")), None), "lastPdt": epoch_iso(e + segs[-1]["dur"]) if e else None,
               "active": m.get("state") in ACTIVE, "sessions": sum(1 for _, s in sess if s)}
        if detail:
            info = {x.get("name"): x for x in (m.get("sessions") or []) if isinstance(x, dict)}
            out["sessionList"] = [{"name": n, "segments": len(s), "seconds": round(sum(x["dur"] for x in s), 3),
                                   "state": info.get(n, {}).get("state", ""), "started": info.get(n, {}).get("started"),
                                   "firstPdt": s[0]["pdt"] if s else None} for n, s in sess]
            try:
                since = max(0, int(since))
            except (TypeError, ValueError):
                since = 0
            out["since"] = since
            page = [(n, x) for n, s in sess for x in s][since:since + 5000]   # 写すのは返す分だけ
            out["segmentList"] = [dict(x, uri="%s/%s" % (n, x["uri"])) for n, x in page]
        return out

    def segments_in(self, start, end):
        """区間の取得(P2 の書き出し。GET /live/<id>/segments)。start・end は UTC の文字列。
        -> {"id", "url", "title", "state", "active", "firstPdt", "lastPdt", "start", "end", "segments": [{"uri", "session", "pdt", "dur"}], "gaps": […]}"""
        a, b = iso_epoch(start), iso_epoch(end)
        if a is None or b is None or b <= a:
            raise RecError("区間(start・end)の時刻が正しくありません")
        if b - a > RANGE_MAX_SEC:
            raise RecError("区間が長すぎます(%d 時間まで)" % (RANGE_MAX_SEC // 3600))
        sess = self.all_segments()
        s = self.summary(sess=sess)
        flat = [dict(x, uri="%s/%s" % (n, x["uri"]), session=n) for n, segs in sess for x in segs]
        picked, gaps = pick_segments(flat, a, b)
        if len(picked) > SEGMENTS_MAX:
            raise RecError("セグメントが多すぎます")
        return dict({"id": self.id}, **{k: s[k] for k in ("url", "title", "state", "active", "message", "firstPdt", "lastPdt")},
                    start=epoch_iso(a), end=epoch_iso(b),
                    segments=[{"uri": x["uri"], "session": x["session"], "pdt": x["pdt"], "dur": x["dur"]} for x in picked],
                    gaps=[{"from": epoch_iso(f), "to": epoch_iso(t), "sec": round(t - f, 3)} for f, t in gaps])

    def segment_path(self, session, name):
        if not SESSION_RE.match(session or "") or not SEG_RE.match(name or ""):
            return None
        p = os.path.join(self.dir, session, name)
        return p if os.path.isfile(p) else None

    # --- 動かす ---
    def start_thread(self):
        self._stop.clear()
        self._halt.clear()
        self.thread = threading.Thread(target=self._run, daemon=True, name="rec-" + self.id)
        self.thread.start()

    def request_stop(self):
        self._stop.set()
        self._kill_procs(graceful=True)

    def halt(self):
        self._halt.set()
        self._kill_procs(graceful=True)

    def _stopping(self):
        return self._stop.is_set() or self._halt.is_set()

    def _wait(self, sec):
        end = time.time() + sec
        while not self._stopping() and time.time() < end:
            time.sleep(min(0.25, max(0.0, end - time.time())))

    def _next_session(self):
        nums = [int(SESSION_RE.match(n).group(1)) for n in self.session_names()]
        name = "session_%03d" % ((max(nums) if nums else 0) + 1)
        os.makedirs(os.path.join(self.dir, name), exist_ok=True)
        with self.lock:
            self.meta.setdefault("sessions", []).append({"name": name, "state": "recording", "started": now_iso()})
        return name

    def _session_mark(self, name, **kw):
        with self.lock:
            for s in self.meta.get("sessions") or []:
                if s.get("name") == name:
                    s.update(kw)

    def _drop_session(self, name):
        """セッションを記録とフォルダから消す(取れなかった・アーカイブを取り始めた)"""
        with self.lock:
            self.meta["sessions"] = [s for s in self.meta.get("sessions") or [] if s.get("name") != name]
        shutil.rmtree(os.path.join(self.dir, name), ignore_errors=True)
        self._cache.pop(name, None)

    def _finish(self, state, message, note):
        """録画を終えた状態(stopped・ended・error)にして記録に残す"""
        self.set(state=state, message=message, endedAt=now_iso())
        self.mgr.log("録画 %s: %s" % (self.id, note))

    def _count(self, name):
        return len(self.session_segments(name)[0])

    def _run(self):
        mgr = self.mgr
        backoff_i = 0
        last_data = time.time()
        try:
            while not self._stopping():
                fs = folder_state(os.path.dirname(self.dir))
                if fs["freeBytes"] is not None and fs["freeBytes"] < MIN_FREE:
                    return self._finish("error", "空き容量が足りないので録画を止めました(%s)" % fs["message"], "空き容量が足りないので止めました")
                got_any = any(s for _, s in self.all_segments())
                name = self._next_session()
                self.set(state="reconnecting" if got_any else "waiting",
                         message="つないでいます…" if got_any else "配信を待っています(始まると自動で録画します)")
                n, code, why = self._run_session(name)
                if why == ARCHIVE:   # 終わった配信(アーカイブ)を頭から取りに行った: そのセッションは消して(時刻が受信時刻と合わない)「終了」。本番画質は P4 のアーカイブの取得で
                    self._drop_session(name)
                    return self._finish("ended", ENDED + "(アーカイブを取り始めたので止めました)", "アーカイブを取り始めたので止めました")
                if n > 0:
                    backoff_i, last_data = 0, time.time()
                    self._session_mark(name, state="done", ended=now_iso(), segments=n)
                else:   # 取れなかったセッションは消す(繋ぎ直しのたびに空のフォルダを増やさない)
                    self._drop_session(name)
                if self._stopping():
                    break
                got_any = got_any or n > 0
                if n > 0 and self._source_ended(code, name):   # 取得がきれいに終わった = 配信が終わった
                    return self._finish("ended", ENDED, "配信が終わりました")
                if time.time() - last_data > (mgr.idle_end if got_any else mgr.wait_start):
                    msg = ENDED if got_any else "配信が始まらないので待つのをやめました"
                    return self._finish("ended", msg, "終了(%s)" % msg)
                delay = mgr.backoff[min(backoff_i, len(mgr.backoff) - 1)]
                backoff_i += 1
                msg = ("切れました(%s)。%d 秒後につなぎ直します" if got_any else "配信を待っています(%s)。%d 秒後にもう一度見ます") % (why, delay)
                self.set(state="reconnecting" if got_any else "waiting", message=msg)
                if got_any:
                    mgr.log("録画 %s: %s" % (self.id, msg))
                self._wait(delay)
        except Exception as e:   # 思わぬエラーでも記録を残す(録画の部品は落とさない)
            return self._finish("error", "録画中にエラーが起きました: %s" % str(e)[:200], "エラー %r" % e)
        finally:
            self._kill_procs(graceful=True)
        if self._stop.is_set():
            self._finish("stopped", "停止しました", "停止しました")
        # _halt(録画の部品の終了)だけのときは状態を録画中のまま残す → 次の起動で recover が新しいセッションで続ける

    def _source_ended(self, code, name):
        """取得が「配信が終わった」で終わったか。streamlink は配信の再生リストに終わりの印(#EXT-X-ENDLIST)が付くと、何も言わずに 0 で終わる。
        切断・止まったときも 0 で終わるが、そのときは記録に「No new segments … Stopping」「Reloading failed」が残る(2026-10-04 に 8.6.1 で確かめた)ので、
        それが無いときだけ終わりとみなす。direct(テスト)の ffmpeg は切断でも 0 で終わるので、元の再生リストに終わりの印があるかを見る"""
        if code != 0:
            return False
        if self.mgr.source != "direct":
            try:
                text = read_text(os.path.join(self.dir, name, "source.log"), 4 * 1024 * 1024) or ""
            except (OSError, ValueError):
                return False
            return not any(m in text for m in SOURCE_TROUBLE)
        try:
            with urllib.request.urlopen(self.meta["url"], timeout=3) as r:
                return b"#EXT-X-ENDLIST" in r.read(PLAYLIST_MAX)
        except (OSError, ValueError):
            return False

    def _commands(self, name):
        mgr = self.mgr
        sdir = os.path.join(self.dir, name)
        out = [mgr.ffmpeg, "-hide_banner", "-loglevel", "warning", "-nostats"]
        if mgr.source == "direct":
            out += ["-i", self.meta["url"]]
            src = None
        else:
            out += ["-i", "pipe:0"]
            src = [mgr.python, "-m", "streamlink", "--stdout", "--loglevel", "warning", "--stream-types", "hls",   # hls だけ = 終わった配信(アーカイブ)を取りに行かない
                   self.meta["url"], QUALITIES.get(self.meta.get("quality"), "best")]
        out += ["-map", "0", "-c", "copy", "-f", "hls", "-hls_time", str(mgr.hls_time), "-hls_list_size", "0",
                "-hls_playlist_type", "event", "-hls_flags", "temp_file+program_date_time",
                "-hls_segment_filename", os.path.join(sdir, "seg_%06d.ts"), os.path.join(sdir, "index.m3u8")]
        return src, out

    def _popen(self, cmd, log_path, **kw):
        logf = open(log_path, "ab")
        try:
            p = subprocess.Popen(cmd, stderr=logf, creationflags=PRIORITY | ytools.no_window_flags(), **kw)
            self.mgr.job.add(p)
            return p
        finally:
            logf.close()   # 子が自分の写しを持っている

    def _run_session(self, name):
        """1つのセッションを録る。-> (セグメントの数, 取得の終了コード, 理由)"""
        mgr = self.mgr
        sdir = os.path.join(self.dir, name)
        src_cmd, ff_cmd = self._commands(name)
        src = ff = None
        try:
            if src_cmd:
                src = self._popen(src_cmd, os.path.join(sdir, "source.log"), stdin=subprocess.DEVNULL, stdout=subprocess.PIPE)
                ff = self._popen(ff_cmd, os.path.join(sdir, "ffmpeg.log"), stdin=src.stdout, stdout=subprocess.DEVNULL)
                src.stdout.close()   # ffmpeg が持つ。こちらは閉じる(streamlink が終われば ffmpeg に EOF が届く)
            else:
                ff = self._popen(ff_cmd, os.path.join(sdir, "ffmpeg.log"), stdin=subprocess.PIPE, stdout=subprocess.DEVNULL)
        except OSError as e:
            self._kill(src)
            self._kill(ff)
            return 0, None, "起動できません: %s" % (e.strerror or e.__class__.__name__)
        with self.lock:
            self.procs = [p for p in (src, ff) if p]
        started = time.time()
        last_n, last_change, why, first_at = 0, started, "", None
        while not self._stopping():
            if ff.poll() is not None:
                why = "ffmpeg が終わりました(終了コード %s)" % ff.returncode
                break
            if src is not None and src.poll() is not None:
                why = "取得が終わりました(終了コード %s)" % src.returncode
                break
            n = self._count(name)
            t = time.time()
            if n != last_n:
                if last_n == 0:
                    first_at = t
                    self.set(state="recording", message="")
                    mgr.log("録画 %s: %s を録画しています" % (self.id, name))
                last_n, last_change = n, t
                if self._too_fast(name, t - first_at):
                    why = ARCHIVE
                    break
            elif n == 0 and t - started > mgr.first_seg_sec:
                why = "%d 秒たっても映像が来ません" % mgr.first_seg_sec
                break
            elif n > 0 and t - last_change > mgr.stall_sec:
                why = "%d 秒新しい映像が来ません" % mgr.stall_sec
                break
            time.sleep(mgr.poll)
        self._kill_procs(graceful=True)
        if why != ARCHIVE and not self._stopping() and self._too_fast(name, time.time() - (first_at or started)):   # 速く取り終えてしまった
            why = ARCHIVE
        if ff.stdin:   # ffmpeg が自分で終わったとき(direct)の q 用の口を閉じる(閉じてあれば何もしない)
            with contextlib.suppress(OSError):
                ff.stdin.close()
        code = src.returncode if src is not None else ff.returncode
        clean_tmp(sdir)
        self._cache.pop(name, None)
        return self._count(name), code, why or "止めました"

    def _too_fast(self, name, elapsed):
        """実際の時間の ARCHIVE_SPEED 倍より速く取れている = 配信ではなくアーカイブを頭から取っている"""
        media = sum(x["dur"] for x in self.session_segments(name)[0])
        return media > ARCHIVE_MIN_SEC and media > ARCHIVE_SPEED * max(0.0, elapsed) + 4 * self.mgr.hls_time

    def _kill(self, p, graceful=False, wait=10.0):
        """子を止める(終わっていれば何もしない)。graceful で口があれば(direct の ffmpeg)q を送って待つ。終わらなければ強制終了"""
        if p is None or p.poll() is not None:
            return
        if graceful and p.stdin and not p.stdin.closed:   # ffmpeg(direct)には q を送る = 最後のセグメントと再生リストを書いて終わる
            with contextlib.suppress(OSError):
                p.stdin.write(b"q")
                p.stdin.flush()
                p.stdin.close()
            with contextlib.suppress(subprocess.TimeoutExpired):
                p.wait(wait)
                return
        ytools.kill_quiet(p)
        with contextlib.suppress(subprocess.TimeoutExpired):
            p.wait(5)

    def _kill_procs(self, graceful=False):
        """取得(streamlink)を先に止める → ffmpeg に EOF が届いて、最後のセグメントを書いて終わる。待っても終わらなければ強制終了"""
        with self.lock:
            procs, self.procs = list(self.procs), []
        if len(procs) == 2:
            src, ff = procs
            self._kill(src)
            with contextlib.suppress(subprocess.TimeoutExpired):
                ff.wait(10)
            self._kill(ff)
        elif procs:
            self._kill(procs[0], graceful=graceful)


# ---------- 録画の全体 ----------
class Recorder:
    def __init__(self, folder, source="streamlink", ffmpeg=None, python=None, hls_time=HLS_TIME, backoff=BACKOFF,
                 idle_end=IDLE_END, wait_start=WAIT_START, stall_sec=STALL_SEC, first_seg_sec=FIRST_SEG_SEC, poll=1.0, log=None):
        self.folder = folder
        self.source = source if source in ("streamlink", "direct") else "streamlink"
        self.title_lookup = fetch_title if self.source == "streamlink" else None   # 名前なしの録画に題を付ける(テストは差し替える・None で聞かない)
        self.ffmpeg = ffmpeg or ytools.find_tool("ffmpeg", "YTT_FFMPEG") or "ffmpeg"
        self.python = python or sys.executable
        self.hls_time = hls_time
        self.backoff = tuple(backoff) or BACKOFF
        self.idle_end, self.wait_start, self.stall_sec, self.first_seg_sec, self.poll = idle_end, wait_start, stall_sec, first_seg_sec, poll
        self.log = log or (lambda m: None)
        self.lock = threading.RLock()
        self.recs = {}
        self.closing = False
        self.job = ytools.KillJob()   # 子(ffmpeg・streamlink)は、録画の部品が落ちても残らない(同じフォルダへ書き続けて、起き直した部品の録画と重ならないように)

    # --- 状態 ---
    def streamlink_ok(self):
        if self.source == "direct":
            return True
        import importlib.util
        return importlib.util.find_spec("streamlink") is not None

    def overview(self):
        with self.lock:
            recs = sorted(self.recs.values(), key=lambda r: r.id, reverse=True)
        fs = folder_state(self.folder)
        return {"folder": self.folder, "folderOk": fs["ok"], "folderMessage": fs["message"], "freeBytes": fs["freeBytes"], "totalBytes": fs["totalBytes"],
                "source": self.source, "streamlink": self.streamlink_ok(), "ffmpeg": bool(self.ffmpeg and (os.path.isfile(self.ffmpeg) or shutil.which(self.ffmpeg))),
                "recordings": [r.summary() for r in recs], "active": sum(1 for r in recs if r.active)}

    def busy(self):
        """録画中・配信待ち・つなぎ直し中の録画があるか"""
        with self.lock:
            return any(r.active for r in self.recs.values())

    def get(self, rid):
        with self.lock:
            r = self.recs.get(rid) if isinstance(rid, str) else None
        if r is None:
            raise RecError("その録画はありません", 404)
        return r

    # --- 起動時 ---
    def load(self):
        """置き場所の録画を読み込み、録画中だった物は続ける(起動時の復旧)。-> 続けた録画の id"""
        resumed = []
        try:
            names = os.listdir(self.folder)
        except OSError:
            return resumed
        for rid in sorted(names):
            path = os.path.join(self.folder, rid)
            if not REC_ID_RE.match(rid) or not os.path.isdir(path):
                continue
            try:
                meta = json.loads(read_text(os.path.join(path, "recording.json"), 1024 * 1024) or "null")
            except (OSError, ValueError):
                meta = None
            if not isinstance(meta, dict) or meta.get("schema") != SCHEMA:
                continue
            sessions = meta.get("sessions")   # 手で書き換えた記録(null・リストでない・中に dict でない物)でも、復旧と録画の続きで落ちないように
            meta["sessions"] = [s for s in sessions if isinstance(s, dict)] if isinstance(sessions, list) else []
            rec = Recording(self, rid, path, meta)
            with self.lock:
                self.recs[rid] = rec
            # 1. 書きかけ(*.tmp)を消す 2. 読めない再生リストは「使えないセッション」
            info = {s.get("name"): s for s in meta["sessions"]}
            for n in rec.session_names():
                clean_tmp(os.path.join(path, n))
                s = info.get(n)
                if s is None:
                    s = {"name": n, "started": None}
                    meta["sessions"].append(s)   # 上で必ず list にしてある
                if not rec.session_segments(n)[0]:
                    if s.get("state") != "broken":
                        s["state"] = "broken"
                        self.log("録画 %s: %s は読めないので使えないセッションにしました" % (rid, n))
                elif s.get("state") == "recording":
                    s["state"] = "interrupted"   # 3. 前回のセッションは「中断」
            if meta.get("state") in ACTIVE:
                if not self.streamlink_ok() or not folder_state(self.folder)["ok"]:
                    rec.set(state="error", message="前回の録画を続けられません(streamlink か録画の置き場所を確かめてください)")
                    continue
                rec.set(state="reconnecting", message="録画の部品を起動し直したので、新しいセッションで続けます")
                rec.start_thread()
                resumed.append(rid)
                self.log("録画 %s: 前回の録画を新しいセッションで続けます" % rid)
            else:
                rec.save()
        return resumed

    # --- 操作 ---
    def start(self, url, quality=DEFAULT_QUALITY, title=""):
        if self.closing:
            raise RecError("録画の部品は終了の途中です", 409)
        url = validate_url(url, allow_local=(self.source == "direct"))
        if quality not in QUALITIES:
            raise RecError("画質は %s のどれかにしてください" % "・".join(QUALITIES))
        title = (title if isinstance(title, str) else "").strip()[:TITLE_MAX]
        if not self.streamlink_ok():
            raise RecError("streamlink が入っていません。setup\\install.bat を実行してください(入れ終われば、そのまま始められます)", 409)
        fs = folder_state(self.folder)
        if not fs["ok"]:
            raise RecError(fs["message"], 409)
        with self.lock:
            for r in self.recs.values():
                if r.active and r.meta.get("url") == url:
                    raise RecError("その配信はもう録画しています(%s)" % r.id, 409)
            rid = new_rec_id(url)
            while rid in self.recs or os.path.exists(os.path.join(self.folder, rid)):   # 同じ秒に同じ配信: 日時 + 乱数
                rid = new_rec_id(url)[:15] + "-" + secrets.token_hex(4)
            path = os.path.join(self.folder, rid)
            try:
                os.makedirs(path)
            except OSError as e:
                raise RecError("録画のフォルダを作れません: %s" % (e.strerror or e.__class__.__name__), 409)
            meta = {"schema": SCHEMA, "id": rid, "url": url, "quality": quality, "title": title, "state": "waiting",
                    "message": "", "created": now_iso(), "endedAt": None, "sessions": []}
            rec = Recording(self, rid, path, meta)
            rec.save()
            self.recs[rid] = rec
        rec.start_thread()
        self.log("録画 %s: 開始 %s(%s)" % (rid, url, quality))
        if not title and self.title_lookup and urllib.parse.urlsplit(url).scheme == "https":   # 手元の URL(テスト)では聞かない
            threading.Thread(target=self._fill_title, args=(rec,), daemon=True, name="title-" + rid).start()
        return rec.summary()

    def _fill_title(self, rec):
        """名前なしで始めた録画に、配信の題を付ける(録画とは別のスレッド。取れなくても録画は続く)"""
        for wait in TITLE_TRIES:
            end = time.time() + wait
            while time.time() < end and rec.active and not self.closing:
                time.sleep(0.5)
            if not rec.active or self.closing or rec.meta.get("title"):
                return
            t = self.title_lookup(rec.meta["url"])
            if t:
                with rec.lock:
                    if not rec.meta.get("title"):
                        rec.set(title=t)
                self.log("録画 %s: 題 %s" % (rec.id, t))
                return

    def stop(self, rid):
        rec = self.get(rid)
        if not rec.active:
            return rec.summary()
        rec.request_stop()
        if rec.thread:
            rec.thread.join(30)
        return rec.summary()

    def delete(self, rid):
        """録画を消す(線 D の P4「録画を自動で消す」。入口の home/live_cleanup.py だけが呼ぶ。入口の中継 /live/r/… は delete を通さない)。
        消すのは置き場所の直下の <録画の id>\\ で、recording.json があるものだけ(id は REC_ID_RE の形・realpath で置き場所の直下か確かめる・
        リンク / ジャンクションの先はたどらない)。録画中・配信待ち・つなぎ直し中は 409。
        使用中で消せないファイルが残ったら 409(recording.json は最後に消すので、同じ要求をあとでまた呼べる)。-> 消した録画の id"""
        if not isinstance(rid, str) or not REC_ID_RE.match(rid):
            raise RecError("録画の id が正しくありません")
        with self.lock:
            r = self.recs.get(rid)
            if r is not None and r.active:
                raise RecError("録画中・配信待ち・つなぎ直し中の録画は消せません(止めてから消します)", 409)
            root = self.folder
        path = os.path.join(root, rid)
        meta = os.path.join(path, "recording.json")
        if _is_link(path) or _is_link(meta):
            raise RecError("リンクになっている録画のフォルダは消しません(手で確かめてください)", 409)
        if not os.path.isdir(path) or not os.path.isfile(meta):
            raise RecError("その録画はありません", 404)
        try:
            inside = os.path.normcase(os.path.dirname(os.path.realpath(path))) == os.path.normcase(os.path.realpath(root))
        except (OSError, ValueError):
            inside = False
        if not inside:
            raise RecError("録画の置き場所の外は消せません", 400)
        left = []
        try:
            entries = list(os.scandir(path))
        except OSError as e:
            raise RecError("録画のフォルダを読めません: %s" % (e.strerror or e.__class__.__name__), 409)
        for ent in entries:
            if ent.name == "recording.json":
                continue
            try:
                if _is_link(ent.path):   # リンク・ジャンクションはそれ自体だけ外す(先は消さない)
                    try:
                        os.unlink(ent.path)
                    except OSError:
                        os.rmdir(ent.path)
                elif ent.is_dir(follow_symlinks=False):
                    shutil.rmtree(ent.path, onerror=lambda fn, p, exc: left.append(p))
                else:
                    os.unlink(ent.path)
            except OSError:
                left.append(ent.path)
        try:
            rest = [n for n in os.listdir(path) if n != "recording.json"]
        except OSError:
            rest = ["?"]
        if left or rest:   # 残りがある間は recording.json を残す(次にまた呼べる)
            n = len(left) or len(rest)
            self.log("録画 %s: 消しきれませんでした(使用中のファイルが %d 個)" % (rid, n))
            raise RecError("使用中のファイルがあるので、録画を消しきれませんでした(残り %d 個。再生中の画面やほかのソフトを閉じてから、もう一度消します)" % n, 409)
        try:
            os.unlink(meta)
        except FileNotFoundError:
            pass
        except OSError as e:
            raise RecError("録画の記録(recording.json)を消せませんでした: %s。あとでもう一度消します" % (e.strerror or e.__class__.__name__), 409)
        try:
            os.rmdir(path)
        except OSError as e:   # 記録はもう無い(録画ではない)ので、空のフォルダが残っても消したことにする
            self.log("録画 %s: 空のフォルダを消せませんでした: %s" % (rid, e))
        with self.lock:
            if self.recs.get(rid) is r:
                self.recs.pop(rid, None)
        self.log("録画 %s: 消しました" % rid)
        return rid

    def set_folder(self, folder):
        with self.lock:
            if self.busy():
                raise RecError("録画中は置き場所を変えられません(止めてから変えてください)", 409)
            self.folder = folder
            self.recs = {}
        self.load()

    def close(self):
        """録画の部品の終了: 録画中の物は状態をそのままに止める(次の起動で新しいセッションとして続ける)"""
        self.closing = True
        with self.lock:
            recs = list(self.recs.values())
        for r in recs:
            r.halt()
        for r in recs:
            if r.thread:
                r.thread.join(15)
