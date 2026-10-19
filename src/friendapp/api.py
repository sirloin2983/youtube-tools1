# -*- coding: utf-8 -*-
"""友人の玄関の口の中身(F3-3。HTTP の形は server.py。ここは欄の検査・② への受付・送った物の進み具合と取り消し・失敗のやり直し・前回の値)。

送る欄(F3-3。notes:plan/f1-friend-requirements.md の C-2-6〜C-2-19):
    source         "url"(配信 1 本)/ "files"(動画ファイル。files = [{fileId, streamer}] を 20 まで。1 本 = 1 依頼の行)
    kind           url のとき "url"(アーカイブ)/ "live"(ライブ中・予定 = 録画を頼む・予約する)/ "wait"(終わったばかり = アーカイブ待ち。C-2-12)
    ranges         区間 [[開始, 終了], …](秒。5 つまで・1 つの長さの上限なし。url・wait だけ)。区間があれば本数は区間の数
    top            本数(区間が無いときだけ。1〜20。初め 5・前回の値 = C-2-8)
    streamer       配信者の札(名簿・打った名前。"" = 色なし)・people = [+ 人] で足したコラボの相手(字幕の色だけ)
    videoTracks    映像トラックの数 1〜5(送る欄・前回の値 = C-2-10)
    live           ライブの送る欄の 3 つ {perHour, lengthMode: auto|fixed, length, afterStream}。感度・待ち・余白は ⚙ の値(C-2-11)
⚙ の値(C-2-19。prefs で変える): pc(この PC で処理する "this" / 依頼する "user")・解析の重み(useWeights・weights)・ライブの感度・待ち・余白・カットの既定。
前回の値は <玄関>/form.json。パックは 1 本ずつ届く(C-3-1)。

送った物(C-2-14〜C-2-16): どの行にも [取り消す](cancel)。失敗は friendapp/progress.classify で友人の言葉に直し、直る見込みのある物は
RETRY_EVERY 秒おきに RETRY_MAX 回まで自動でやり直す(tick)。同じ失敗が 2 回目なら [作る人に知らせる](report = 送り返しに .notice.json。形は
notes:docs/spec/friend.md の 12-4)。アーカイブ待ちの行は tick が数分おきに配信を調べ、アーカイブが出たら作り始める(1 日出なければ失敗)。
ユーザーの PC に頼む行は、同期(friendapp/sync.py。api.sync)が依頼の JSON を Dropbox の直下へ上げる。受付が 1 時間読まなければ [この PC でやり直す](local)。
"""
import datetime
import json
import os
import re
import shutil
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid

from flow import deliver as _deliver, order as _order, placement as _placement, spec as _spec
from ytt import colors as _colors, fsio as _fsio, tools as _tools, version as _version, yturl as _yturl

from . import inbox as _inbox, live as _live, progress as _progress

FORM_NAME = "form.json"
TOP_MAX = 20                        # 本数の上限(C-5-5)
TOP_DEFAULT = 5                     # 本数の初め(C-2-8)
RANGES_MAX = 5                      # 区間の数の上限(C-5-5)
FILES_MAX_SEND = 20                 # 動画ファイルを 1 回に送る数(C-2-13)
LENGTH_MODES = ("auto", "fixed")    # ライブの長さ: 自動(場面ごと)/ 固定の秒数(C-2-11)
FORM_DEFAULTS = {"top": TOP_DEFAULT, "videoTracks": 1, "useWeights": False, "weights": {"wAudio": 1, "wChat": 1, "wComments": 1},
                 "pc": "this", "live": dict(_live.SETTINGS_DEFAULT, lengthMode="auto"), "cut": "none"}   # cut = ⚙ のカットの既定(A-8)
PCS = ("this", "user")
PEOPLE_MAX = 6
OEMBED = "https://www.youtube.com/oembed?format=json&url="
PEEK_TIMEOUT = 8
LIVE_PEEK_CACHE = 60                # 配信中か調べた結果を覚える秒(配信前 → 配信中と変わるので短く)
LIVE_STATES = ("is_live", "is_upcoming")
FILES_MAX = 60                      # 覚えておく選んだファイルの数
VIDEO_TYPES = tuple(k for k, v in _tools.MEDIA_TYPES.items() if v.startswith("video/"))
NAME_PREFIX_RE = re.compile(r"^【([^】]{1,60})】")   # 動画の名前の頭の【配信者】
COPY_CHUNK = 8 * 1024 * 1024
COPY_ROOM = 512 * 1024 * 1024       # 写すときに残す空き
WAIT_EVERY = 300                    # アーカイブ待ち: 配信を調べ直す間隔(秒)
WAIT_GIVE_UP = 86400                # アーカイブ待ち: これだけ待って出なければ失敗(C-2-12 の「1 日など」)
ARCHIVE_OK = ("was_live", "not_live")   # 調べた結果がこれならアーカイブが見られる(post_live = まだ)
RETRY_MAX = _inbox.RETRY_MAX         # 直る見込みのある失敗の自動のやり直しの回数(C-2-16)
RETRY_EVERY = 180                   # 自動のやり直しの間隔(秒 = 数分おき)
NOTICE_MAX = 250 * 1024             # [作る人に知らせる] の 1 つの大きさ(12-4 = 256KB 未満)
NOTICE_LOG_MAX = 120 * 1024         # その中のログ(12-4 = 128KB まで)
UPLOAD_DIR = "受け取った動画"       # 画面に落とした動画の置き場所(一時保管の中。送らなければ 1 日で消す)
UPLOAD_KEEP = 86400


class FormError(ValueError):
    """送る欄が違う(文は画面にそのまま出す)"""


def _int_in(v, lo, hi):
    return isinstance(v, int) and not isinstance(v, bool) and lo <= v <= hi


def check_weights(w):
    """⚙ の解析の重み {wAudio・wChat・wComments} -> 整えた辞書。どれかが 0〜3 の整数でなければ FormError(⚙ の 2 つの口が使う 1 か所)"""
    if not (isinstance(w, dict) and all(_int_in(w.get(k), 0, 3) for k in _spec.WEIGHT_KEYS)):
        raise FormError("解析の重みは 0〜3 の整数にしてください(音量・チャット・コメント)")
    return {k: w[k] for k in _spec.WEIGHT_KEYS}


def merge_live(cur, change):
    """⚙ のライブの値(change の sens・waitMin・pad)を今の設定 cur に重ねて検べる -> 新しい設定(lengthMode は今のまま)。
    違えば FormError(文は live.check_settings。⚙ の 2 つの口が使う 1 か所)"""
    lv = dict(cur, **{k: change[k] for k in ("sens", "waitMin", "pad") if k in change})
    try:
        checked = _live.check_settings(lv)
    except ValueError as e:
        raise FormError("ライブの" + str(e))
    return dict(checked, lengthMode=cur.get("lengthMode", "auto"))


def oembed(vid, timeout=PEEK_TIMEOUT):
    """oEmbed(公開・キー不要)で題とチャンネル名 -> {"title", "channel"}(取れなければ空。接続先は固定・id は検査済み)"""
    target = OEMBED + urllib.parse.quote(_yturl.watch_url(vid), safe="")
    try:
        with urllib.request.urlopen(urllib.request.Request(target, headers={"Accept": "application/json"}), timeout=timeout) as r:
            d = json.loads(r.read(200000).decode("utf-8", "replace"))
    except (urllib.error.URLError, TimeoutError, OSError, ValueError):
        return {"title": "", "channel": ""}
    return {"title": str(d.get("title") or "")[:120], "channel": str(d.get("author_name") or "")[:100]}


def probe_live(url):
    """配信中・配信前か(② の flow/livesession.probe_live = yt-dlp の live_status。読むのは呼んだときだけ = 画面を先に出す)"""
    from flow import livesession
    return livesession.probe_live(url)


def guess_streamer(name, entries=None):
    """動画の名前の頭の【名前】-> 名簿の 1 人 {"name", "hex"} か None(合わなければ推さない)"""
    m = NAME_PREFIX_RE.match(str(name or "").strip())
    if not m:
        return None
    hit = _colors.lookup(m.group(1).strip(), entries)["match"]
    return {"name": hit["name"], "hex": hit["hex"]} if hit else None


def file_title(name):
    """動画ファイルの名前 -> 題の元(拡張子と頭の【】を除く。C-2-13)"""
    stem = os.path.splitext(os.path.basename(str(name or "")))[0]
    return (NAME_PREFIX_RE.sub("", stem).strip() or stem)[:120]


def clean_ranges(v):
    """区間 [[開始, 終了], …] -> 整えた一覧(5 つまで。1 つの長さの上限なし = C-2-7・C-5-5)。違えば FormError(どの区間がなぜ違うか)。
    1 つずつの検査は ② flow/spec.check_range(時刻は 0〜100 時間・開始 < 終了・丸めて長さ 0 は断る)"""
    if v in (None, [], ()):
        return []
    if not isinstance(v, (list, tuple)) or len(v) > RANGES_MAX:
        raise FormError("区間は %d つまでです" % RANGES_MAX)
    out = []
    for r in v:
        got, why = _spec.check_range(r)
        if got is None:
            raise FormError(why)
        out.append(got)
    return out


class Api:
    """玄関の口(server.py の Handler が呼ぶ)。engine = friendapp.engine.Engine(準備中は None)。
    fetch = oEmbed・probe = 配信中か調べる(テストは偽物)"""

    def __init__(self, places, inbox, engine_fn, fetch=oembed, clock=time.time, probe=probe_live):
        self.places, self.inbox, self.engine_fn = places, inbox, engine_fn
        self.fetch, self.clock, self.probe = fetch, clock, probe
        self.form_path = os.path.join(places["friend"], FORM_NAME)
        self._peek = {}
        self._live_peek = {}
        self._files = {}                 # 選んだ・落とした動画 {id: {path, name, size, copy?}}(パスは画面に出さない)
        self._copies = {}                # 写している動画 {依頼 id: [写した, 全部]}
        self._stages = {}                # 作っている行の今の段 {依頼 id: [段の名前, 始まった ms, detail, 最後に変わった ms]}(進み具合・残り時間)
        self._lock = threading.Lock()
        self.stopping = lambda: False    # 玄関が終わる途中か(写すのを止める。玄関が入れる)
        self.sync = None   # Dropbox の同期(friendapp/sync.Sync。玄関が入れる。無ければ依頼できない)
        self.parts_missing = lambda: None   # 初回の取得の部品が足りない理由か None(この PC で作る依頼を断る。玄関が setup.Setup.block_reason を入れる)
        self.log_path = os.path.join(places["friend"], "logs", "friendapp.log")   # [作る人に知らせる] に付けるログ
        self.login_at = _tools.ytdlp_login_at   # YouTube にログインした時刻(ミリ秒)か 0(notes:docs/spec/friend.md の 13-13。テストが差し替える)

    def classify(self, r):
        """失敗の行 -> progress.classify(bot の言葉はログインしてあるかで変わる)"""
        return _progress.classify(r.get("error") or "", r.get("kind") or "url", login=bool(self.login_at()))

    def _need_parts(self):
        why = self.parts_missing()
        if why:
            raise FormError(why)

    # ------------------------------------------------------------ 前回の値と ⚙
    def form(self):
        d = _fsio.read_json_or(self.form_path, {}, kind=dict)
        out = json.loads(json.dumps(FORM_DEFAULTS))
        if _int_in(d.get("top"), 1, TOP_MAX):
            out["top"] = d["top"]
        if _int_in(d.get("videoTracks"), 1, 5):
            out["videoTracks"] = d["videoTracks"]
        if isinstance(d.get("useWeights"), bool):
            out["useWeights"] = d["useWeights"]
        if d.get("pc") in PCS:
            out["pc"] = d["pc"]
        w = d.get("weights")
        if isinstance(w, dict) and all(_int_in(w.get(k), 0, 3) for k in _spec.WEIGHT_KEYS):
            out["weights"] = {k: w[k] for k in _spec.WEIGHT_KEYS}
        lv = d.get("live") if isinstance(d.get("live"), dict) else {}
        out["live"] = dict(_live.clean_settings(lv), lengthMode=lv.get("lengthMode") if lv.get("lengthMode") in LENGTH_MODES else "auto")
        if d.get("cut") in _spec.CUTS:
            out["cut"] = d["cut"]
        return out

    def _write_form(self, cur):
        _fsio.write_json(self.form_path, cur, indent=None)

    def set_cut(self, cut):
        """⚙ のカットの既定(none・silence)を form.json に"""
        if cut not in _spec.CUTS:
            raise FormError("カットは「しない」か「無音を削る」を選んでください")
        cur = self.form()
        cur["cut"] = cut
        self._write_form(cur)

    def set_prefs(self, body):
        """⚙ の値(C-2-19・C-2-11): pc・useWeights・weights・liveSens・liveWait・livePad -> 変えた物の文のリスト。違えば FormError(どれも書かない)"""
        cur = self.form()
        msgs = []
        if "pc" in body:
            if body["pc"] not in PCS:
                raise FormError("処理する PC が正しくありません")
            if body["pc"] == "user":
                self._need_key()
            cur["pc"] = body["pc"]
            msgs.append("依頼するにしました(この PC では処理しません)" if body["pc"] == "user" else "この PC で処理するにしました")
        if "useWeights" in body:
            if not isinstance(body["useWeights"], bool):
                raise FormError("解析の重みはオンかオフにしてください")
            cur["useWeights"] = body["useWeights"]
            msgs.append("解析の重みを%s" % ("使うにしました" if body["useWeights"] else "使わないにしました"))
        if "weights" in body:
            cur["weights"] = check_weights(body["weights"])
            msgs.append("解析の重みを変えました")
        change = {name: body[key] for key, name in (("liveSens", "sens"), ("liveWait", "waitMin"), ("livePad", "pad")) if key in body}
        if dict(cur["live"], **change) != cur["live"]:
            cur["live"] = merge_live(cur["live"], change)
            msgs.append("ライブの設定を変えました(次に頼む録画から)")
        if msgs:
            self._write_form(cur)
        return msgs

    def _remember(self, f):
        cur = self.form()
        cur["videoTracks"] = f["videoTracks"]
        if f.get("top") is not None and f["kind"] in ("url", "wait"):
            cur["top"] = f["top"]
        if f.get("live"):
            cur["live"] = dict(cur["live"], **{k: f["live"][k] for k in ("perHour", "length", "afterStream", "lengthMode") if k in f["live"]})
        self._write_form(cur)

    # ------------------------------------------------------------ 送る
    def peek(self, url):
        """URL を貼ったとき: 配信の id・題・チャンネル名と配信者の推し -> {"videoId", "title", "channel", "streamer", "hex"}"""
        vid = _yturl.parse_video_id(url)
        if not vid:
            raise FormError("YouTube の配信の URL を貼ってください")
        with self._lock:
            got = self._peek.get(vid)
        if got is None:
            meta = self.fetch(vid)
            hit = _colors.from_channel(meta["channel"]) if meta["channel"] else None
            got = {"videoId": vid, "title": meta["title"], "channel": meta["channel"], "streamer": hit["name"] if hit else "",
                   "hex": hit["hex"] if hit else None}
            with self._lock:
                self._peek[vid] = got
        return dict(got)

    def peek_live(self, url):
        """配信中・配信前か(yt-dlp の live_status = ② の probe_live。数秒かかる)-> {"videoId", "status", "live", "message"}。
        live = 配信中・配信前(ライブの送る欄)。post_live = 終わった直後(アーカイブ待ちで送れる = C-2-12)。members = メンバー限定(送れない)"""
        vid = _yturl.parse_video_id(url)
        if not vid:
            raise FormError("YouTube の配信の URL を貼ってください")
        now = self.clock()
        with self._lock:
            hit = self._live_peek.get(vid)
        if hit is None or now - hit[0] > LIVE_PEEK_CACHE:
            try:
                info = self.probe(_yturl.watch_url(vid)) or {}
            except Exception as e:   # 調べる部品の不具合でも送る欄は使える(普通の URL として)
                info = {"status": "unknown", "message": "配信中か調べられませんでした(%s)" % e.__class__.__name__}
            st = info.get("status") if isinstance(info.get("status"), str) else "unknown"
            msg = str(info.get("message") or "")[:200]
            if st == "post_live":
                msg = "配信が終わったばかりです。送ると、アーカイブが出たら自動で作り始めます"
            if _progress.classify(msg)["code"] == "members":
                st, msg = "members", "メンバー限定の配信は切り抜けません"
            hit = (now, {"videoId": vid, "status": st, "live": st in LIVE_STATES, "message": msg})
            with self._lock:
                self._live_peek[vid] = hit
        return dict(hit[1])

    def _keep_file(self, entry):
        fid = uuid.uuid4().hex[:12]
        with self._lock:
            self._files[fid] = entry
            while len(self._files) > FILES_MAX:
                self._files.pop(next(iter(self._files)))
        who = guess_streamer(entry["name"])
        return {"id": fid, "name": entry["name"], "size": entry["size"], "title": file_title(entry["name"]),
                "streamer": who["name"] if who else "", "hex": who["hex"] if who else None}

    def remember_file(self, path):
        """[ファイルを選ぶ] で選んだ動画を覚える -> {"id", "name", "size", "title", "streamer", "hex"}(パスは返さない)。動画でなければ FormError"""
        if not isinstance(path, str) or not os.path.isabs(path) or not os.path.isfile(path):
            raise FormError("動画ファイルが見つかりません")
        name = os.path.basename(path)
        if os.path.splitext(name)[1].lower() not in VIDEO_TYPES:
            raise FormError("動画ファイル(%s)ではありません" % " ".join(sorted(VIDEO_TYPES)))
        size = os.path.getsize(path)
        key = (os.path.normcase(os.path.abspath(path)), size, os.path.getmtime(path))
        with self._lock:   # 同じ物(同じパス・大きさ・更新時刻)をもう一度覚えさせても 1 つのまま = 同じ id を返す
            for fid, e in self._files.items():
                if e.get("key") == key:
                    who = guess_streamer(e["name"])
                    return {"id": fid, "name": e["name"], "size": e["size"], "title": file_title(e["name"]),
                            "streamer": who["name"] if who else "", "hex": who["hex"] if who else None}
        return self._keep_file({"path": path, "name": name[:200], "size": size, "key": key})

    def upload_dir(self):
        return os.path.join(self.places["cases"], UPLOAD_DIR)

    def upload_file(self, name, size, read):
        """画面に落とした動画を受け取る(C-2-13。ブラウザはパスを渡せないので中身を受ける)。read(n) = 本文を読む口 -> remember_file と同じ形。
        置き場所は一時保管の 受け取った動画\\(写しを兼ねる = 送るときにもう一度写さない)"""
        name = _inbox.BAD_NAME.sub("_", os.path.basename(str(name or ""))).strip()[:200]
        if not name or os.path.splitext(name)[1].lower() not in VIDEO_TYPES:
            raise FormError("動画ファイル(%s)ではありません" % " ".join(sorted(VIDEO_TYPES)))
        if not _int_in(size, 1, 1 << 46):
            raise FormError("動画ファイルの大きさが分かりません")
        folder = self.upload_dir()
        os.makedirs(folder, exist_ok=True)
        try:
            free = shutil.disk_usage(folder).free
        except OSError:
            free = None
        if free is not None and free < size + COPY_ROOM:
            raise FormError("パソコンの空きが足りません(あと %d MB ほど空けてください)" % ((size + COPY_ROOM - free) // (1024 * 1024) + 1))
        dest = os.path.join(folder, "%s_%s" % (uuid.uuid4().hex[:8], name))
        tmp = dest + ".part"
        try:
            with open(tmp, "wb") as f:
                left = size
                while left > 0:
                    buf = read(min(COPY_CHUNK, left))
                    if not buf:
                        raise FormError("動画を受け取る途中で止まりました。もう一度落としてください")
                    f.write(buf)
                    left -= len(buf)
            os.replace(tmp, dest)
        except BaseException:
            _fsio.unlink_quiet(tmp)
            raise
        return self._keep_file({"path": dest, "name": name, "size": size, "copy": dest})

    def sweep_uploads(self):
        """落としたまま送らなかった動画を 1 日で消す(送った物は依頼のフォルダへ移している)"""
        folder = self.upload_dir()
        if not os.path.isdir(folder):
            return
        with self._lock:
            held = {os.path.normcase(e["path"]) for e in self._files.values()}
        for n in os.listdir(folder):
            p = os.path.join(folder, n)
            try:
                if os.path.isfile(p) and os.path.normcase(p) not in held and self.clock() - os.path.getmtime(p) >= UPLOAD_KEEP:
                    os.remove(p)
            except OSError:
                pass

    def _common(self, body):
        streamer = body.get("streamer")
        streamer = streamer.strip()[:_colors.NAME_MAX] if isinstance(streamer, str) else ""
        people = [p.strip()[:_order.PEOPLE_NAME_MAX] for p in body.get("people") or [] if isinstance(p, str) and p.strip()][:PEOPLE_MAX]
        vt = body.get("videoTracks", 1)
        if not _int_in(vt, 1, 5):
            raise FormError("映像トラックの数は 1〜5 にしてください")
        return streamer, people, vt

    def check_form(self, body):
        """配信 1 本の送る欄 -> 整えた欄(上の説明)。違えば FormError。処理する PC・重み・カットは ⚙ の値"""
        prefs = self.form()
        vid = _yturl.parse_video_id(body.get("url"))
        if not vid:
            raise FormError("YouTube の配信の URL を貼ってください")
        kind = body.get("kind") if body.get("kind") in ("url", "live", "wait") else "url"
        ranges = clean_ranges(body.get("ranges")) if kind != "live" else []
        top = None
        if kind != "live" and not ranges:
            top = body.get("top")
            if not _int_in(top, 1, TOP_MAX):
                raise FormError("本数は 1〜%d にしてください" % TOP_MAX)
        live = None
        if kind == "live":
            got = body.get("live") if isinstance(body.get("live"), dict) else {}
            mode = got.get("lengthMode") if got.get("lengthMode") in LENGTH_MODES else "auto"
            s = dict(prefs["live"])   # 感度・待ち・余白は ⚙ の値
            for k in ("perHour", "afterStream"):
                if k in got:
                    s[k] = got[k]
            if mode == "fixed":
                s["length"] = got.get("length")
            s.pop("lengthMode", None)
            try:
                live = dict(_live.check_settings(s), lengthMode=mode)
            except ValueError as e:
                raise FormError(str(e))
        streamer, people, vt = self._common(body)
        use_w = prefs["useWeights"] and not ranges and kind != "live"
        return {"kind": kind, "url": _yturl.watch_url(vid), "videoId": vid, "ranges": ranges, "top": top, "streamer": streamer, "people": people,
                "videoTracks": vt, "useWeights": use_w, "weights": prefs["weights"] if use_w else None,
                "title": str(body.get("title") or "")[:120], "channel": str(body.get("channel") or "")[:100], "pc": prefs["pc"],
                "cut": prefs["cut"], "live": live, "startAt": body.get("startAt") if _int_in(body.get("startAt"), 0, 1 << 50) else None}

    def check_file(self, item, body):
        """動画ファイル 1 本の欄 -> 整えた欄。選び直しが要れば FormError"""
        with self._lock:
            picked = self._files.get(str((item or {}).get("fileId") or ""))
        if picked is None or not os.path.isfile(picked["path"]):
            raise FormError("動画ファイルを選び直してください")
        prefs = self.form()
        streamer, people, vt = self._common(dict(body, streamer=(item or {}).get("streamer", "")))
        return {"kind": "file", "url": "", "videoId": None, "ranges": [], "top": None, "streamer": streamer, "people": people, "videoTracks": vt,
                "useWeights": False, "weights": None, "title": file_title(picked["name"]), "channel": "", "pc": prefs["pc"], "cut": prefs["cut"],
                "live": None, "file": dict(picked)}

    def _people(self, f):
        names = ([f["streamer"]] if f["streamer"] else []) + [p for p in f["people"] if p != f["streamer"]]
        people = [{"name": n} for n in dict.fromkeys(names)]
        return people if len(people) > 1 and _spec.key_ok("hints", "people", people) else None

    def order(self, f, rid):
        """整えた欄 -> (封筒, 束の差分)(flow/order.py の 1 か所 + 人の名前)。kind ごと(url・file・live)"""
        kind = f.get("kind") or "url"
        if kind == "live":   # ライブ: 封筒 kind live + 依頼の束(感度・枠・待ち・余白・配信後の追加。長さは束に入れない = engine が行の欄から)
            from flow import livesession   # 読むのは送るときだけ(画面を先に出す)
            env, _diff = _order.order("live", video_id=f["videoId"], title=f["title"] or f["videoId"], request_id=rid)
            ctx = {"settings": {k: v for k, v in f["live"].items() if k != "lengthMode"}, "videoTracks": f["videoTracks"], "streamer": f["streamer"]}
            bundle = livesession.request_bundle(ctx, None)
            people = self._people(f)
            if people:
                bundle["hints"]["people"] = people
            return env, bundle
        if kind == "file":   # 動画ファイル: 一時保管の写し(form.file.copy)を 30fps にそろえてから(写しだけ置き換える)パックまで
            env, diff = _order.order("file", path=f["file"].get("copy") or f["file"]["path"], title=f["title"] or f["file"]["name"], normalize=True,
                                     upto="pack", video_tracks=f["videoTracks"], streamer=f["streamer"], repack=True, request_id=rid, cut=_cut(f))
        else:
            env, diff = _order.order("url", video_id=f["videoId"], title=f["title"] or f["videoId"], fresh={"title": f["title"], "channel": f["channel"]},
                                     upto="pack", top=len(f["ranges"]) if f["ranges"] else f["top"], ranges=f["ranges"] or None,
                                     weights=f["weights"], video_tracks=f["videoTracks"], streamer=f["streamer"], repack=True, request_id=rid, cut=_cut(f))
        people = self._people(f)
        if people:
            diff.setdefault("hints", {})["people"] = people
        return env, diff

    def _need_key(self):
        if self.sync is None or not self.sync.has_key():
            raise FormError("Dropbox の鍵が無いので依頼できません(⚙ の処理する PC を「この PC で処理する」にしてください)")

    @staticmethod
    def _source(f):
        if f["kind"] == "file":
            return {"url": "", "videoId": "", "title": f["title"], "channel": "", "fileName": f["file"]["name"], "fileSize": f["file"]["size"]}
        return {"url": f["url"], "videoId": f["videoId"], "title": f["title"], "channel": f["channel"]}

    def send(self, body):
        """[送る] -> {"rows": [行]}。動画ファイルは 1 本ずつの行(動画でない物は理由つきで外す = skipped)。② が断れば FormError(理由)"""
        if body.get("source") == "files":
            items = body.get("files") if isinstance(body.get("files"), list) else []
            if not items:
                raise FormError("動画ファイルを選んでください")
            if len(items) > FILES_MAX_SEND:
                raise FormError("動画ファイルは 1 回に %d 本までです" % FILES_MAX_SEND)
            forms, skipped = [], []
            for it in items:
                try:
                    forms.append(self.check_file(it, body))
                except FormError as e:
                    skipped.append({"fileId": (it or {}).get("fileId"), "message": str(e)})
            if not forms:
                raise FormError(skipped[0]["message"] if skipped else "動画ファイルを選んでください")
            rows = [self._send_one(f) for f in forms]
            with self._lock:   # 送った物は覚えから外す(同じ物を 2 回送らない)
                for it in items:
                    self._files.pop(str((it or {}).get("fileId") or ""), None)
            return {"rows": rows, "skipped": skipped}
        return {"rows": [self._send_one(self.check_form(body))], "skipped": []}

    def _send_one(self, f):
        rid = _deliver.request_id(self.clock())
        if f["kind"] == "wait":   # アーカイブ待ち: 受け付けるだけ(tick が出たのを見て作り始める)
            row = self.inbox.add(rid, f, self._source(f), kind="url", pc=f["pc"], state="waiting")
            self._remember(f)
            return row
        if f["pc"] == "user":
            self._need_key()
            row = self.inbox.add(rid, f, self._source(f), pc="user", kind=f["kind"])
            self._remember(f)
            self.sync.kick()
            return row
        eng = self.engine_fn()
        if eng is None:
            raise FormError("準備中です。少し待ってから、もう一度押してください")
        self._need_parts()
        row = self.inbox.add(rid, f, self._source(f), kind=f["kind"])
        try:
            row = self._submit_this(eng, row)
        except FormError:
            self.inbox.drop(rid)
            raise
        self._remember(f)
        return row

    def _submit_this(self, eng, row):
        """この PC の ② へ(kind ごと)-> 行。断られたら FormError(行は呼ぶ側が始末する)"""
        f, rid = row["form"], row["id"]
        if f.get("kind") == "file":   # 写すのは裏の糸(大きな動画でも画面を待たせない)。写し終えたら ② へ
            self._start_copy(rid)
            return self.inbox.row(rid)
        env, diff = self.order(f, rid)
        if f.get("kind") == "live":
            if getattr(eng, "live", None) is None:
                raise FormError("この PC ではライブを録画できません(録画の部品がありません)")
            try:
                out = eng.queue.submit(env, diff) or {}
            except ValueError as e:   # 配信中でなかった・録画を始められない・空き容量 など(LiveError も ValueError)
                raise FormError(str(e))
            return self.inbox.live_started(rid, out.get("recorder"), out.get("recording"), out.get("existing"))
        self.inbox.set_run(rid, env["id"])
        try:
            eng.queue.submit(env, diff)
        except ValueError as e:
            raise FormError(str(e))
        return self.inbox.row(rid)

    # ------------------------------------------------------------ 動画ファイルを写す(この PC。7-2)
    def copying(self):
        with self._lock:
            return bool(self._copies)

    def copy_progress(self, rid):
        with self._lock:
            c = self._copies.get(rid)
            return {"done": c[0], "total": c[1]} if c else None

    def _start_copy(self, rid):
        with self._lock:
            if rid in self._copies:
                return
            self._copies[rid] = [0, 0]
        threading.Thread(target=self._copy_job, args=(rid,), name="friend-copy", daemon=True).start()

    def _copy_job(self, rid):
        try:
            self._copy_and_submit(rid)
        except FormError as e:
            self.inbox.fail(rid, str(e))
        except Exception as e:   # noqa: BLE001  (写せない・② が断った = 行を失敗に。[もう一度送る] で写し直す)
            self.inbox.fail(rid, "動画を送れませんでした(%s)" % (str(e)[:160] or e.__class__.__name__))
        finally:
            with self._lock:
                self._copies.pop(rid, None)

    def _copy_and_submit(self, rid):
        r = self.inbox.row(rid)
        if r is None:
            return
        f = json.loads(json.dumps(r["form"]))
        fi = f["file"]
        dest = fi.get("copy")
        if dest and os.path.isfile(dest) and fsio_inside(dest, self.upload_dir()):   # 落とした動画 = もう一時保管にある → 依頼のフォルダへ移すだけ
            dest = self._move_upload(rid, f["title"], dest)
        elif not (dest and os.path.isfile(dest) and os.path.getsize(dest) > 0):
            dest = self._copy_video(rid, f["title"], fi["path"])
        fi["copy"] = dest
        _placement.ensure_case({"kind": "file", "path": dest}, channel=f.get("streamer") or "", root=os.path.dirname(dest), request_id=rid)
        if self.stopping():
            return   # 終わる途中 = 行は「送った」のまま(次に開いたとき失敗の行 = [もう一度送る] で写しを使う)
        eng = self.engine_fn()
        if eng is None:
            raise FormError("処理の部品が止まっています。アプリを開き直してから [もう一度送る] を押してください")
        env, diff = self.order(f, rid)
        self.inbox.set_run(rid, env["id"], copy=dest)
        try:
            eng.queue.submit(env, diff)
        except ValueError as e:
            raise FormError(str(e))

    def _request_folder(self, rid, title):
        cases = self.places["cases"]
        day = datetime.date.fromtimestamp(self.clock()).isoformat()
        folder = _placement.request_folder(rid, title, day, out_dir=cases, fallback=os.path.join(cases, _placement.REQUEST_DIR, rid))[0]
        os.makedirs(folder, exist_ok=True)
        return folder

    def _move_upload(self, rid, title, src):
        folder = self._request_folder(rid, title)
        name = os.path.basename(src).split("_", 1)[-1]
        dest = _inbox.unique_dest(folder, name)
        shutil.move(src, dest)
        return dest

    def _copy_video(self, rid, title, src):
        """元の動画を一時保管の <作業>/依頼/<日付>_<題>_<id6>/ へ写す(元は読むだけ)-> 写しのパス"""
        if not os.path.isfile(src):
            raise FormError("動画ファイルが見つかりません(移動・削除した可能性があります)。選び直して送ってください")
        folder = self._request_folder(rid, title)
        size = os.path.getsize(src)
        try:
            free = shutil.disk_usage(folder).free
        except OSError:
            free = None
        if free is not None and free < size + COPY_ROOM:
            raise FormError("パソコンの空きが足りません(あと %d MB ほど空けてから [もう一度送る])" % ((size + COPY_ROOM - free) // (1024 * 1024) + 1))
        stem, ext = os.path.splitext(_inbox.BAD_NAME.sub("_", os.path.basename(src)))
        dest = os.path.join(folder, stem + ext)
        while os.path.exists(dest):
            dest = os.path.join(folder, "%s-%s%s" % (stem, uuid.uuid4().hex[:4], ext))
        tmp = dest + ".copying"
        with self._lock:
            self._copies[rid] = [0, size]
        try:
            with open(src, "rb") as a, open(tmp, "wb") as b:
                done = 0
                while True:
                    if self.stopping():
                        raise FormError("アプリを閉じたので写すのを止めました。[もう一度送る] で写し直します")
                    buf = a.read(COPY_CHUNK)
                    if not buf:
                        break
                    b.write(buf)
                    done += len(buf)
                    with self._lock:
                        self._copies[rid] = [done, size]
            os.replace(tmp, dest)
        except BaseException:
            _fsio.unlink_quiet(tmp)
            raise
        return dest

    # ------------------------------------------------------------ やり直す・取り消す・知らせる
    def retry(self, rid, auto=False):
        """失敗の行の [もう一度送る](同じ欄で。済んだ段は ② が飛ばす)。auto = 自動のやり直し(回数を数える)"""
        eng = self.engine_fn()
        r = self.inbox.row(rid)
        if r is None or r["state"] != "failed" or not r.get("form"):
            raise FormError("もう一度送れる行ではありません")
        if r.get("pc") == "user":   # 依頼した行は、同じ id の依頼を上げ直す
            self._need_key()
            row = self.inbox.resent(rid, None, auto=auto)
            self.sync.kick()
            return row
        if eng is None:
            raise FormError("準備中です。少し待ってから、もう一度押してください")
        self._need_parts()
        self.inbox.resent(rid, None, auto=auto)
        try:
            return self._submit_this(eng, self.inbox.row(rid))
        except FormError as e:
            self.inbox.fail(rid, str(e))
            raise

    def local(self, rid):
        """[この PC でやり直す]: ユーザーの PC の受付が 1 時間読まない依頼を、直下から消してから同じ欄でこの PC の ② へ"""
        eng = self.engine_fn()
        r = self.inbox.row(rid)
        if r is None or r.get("pc") != "user" or not r.get("form"):
            raise FormError("この PC でやり直せる行ではありません")
        if eng is None:
            raise FormError("準備中です。少し待ってから、もう一度押してください")
        self._need_parts()
        if self.sync is None:
            raise FormError("Dropbox の鍵が無いので、依頼を取り消せません")
        try:
            gone = self.sync.withdraw(rid)
        except Exception as e:   # 鍵が無い・つながらない = 二重に作らないよう、取り消せるまでやり直さない
            raise FormError("依頼を取り消せませんでした(%s)。少し待ってから、もう一度押してください" % e)
        if not gone:
            raise FormError("作る人の PC がちょうど受け付けました。このまま届くのを待ってください")
        row = self.inbox.to_local(rid, None)
        try:
            return self._submit_this(eng, row)
        except FormError as e:
            self.inbox.fail(rid, str(e))
            raise

    def cancel(self, rid):
        """[取り消す](C-2-14。時間の制限なし): 待ち・アーカイブ待ち・予約は依頼ごと消す / 作っている途中は止めて届いた物は残す /
        録画中は録画と先の切り抜きを止め、届いた物は残す・作りかけは捨てる。依頼した行は Dropbox の直下から消せれば消し、
        もう受け付けられていれば、この画面から外すだけ(届いた物は受け取るに並ぶ)。-> {"id", "state": "cancelled"}"""
        eng = self.engine_fn()
        r = self.inbox.row(rid)
        if r is None:
            raise KeyError(rid)
        if r["state"] == "failed":
            self.inbox.remove(rid)
            return {"id": rid, "state": "cancelled"}
        if r["state"] == "waiting":
            self.inbox.drop(rid)
            return {"id": rid, "state": "cancelled"}
        if r.get("pc") == "user":
            gone = False
            if self.sync is not None and r["state"] == "sent":
                try:
                    gone = self.sync.withdraw(rid)
                except Exception:   # noqa: BLE001  (つながらない = 画面から外すだけ。届いた物は受け取るへ)
                    gone = False
            self.inbox.cancelled(rid, drop=gone)
            return {"id": rid, "state": "cancelled"}
        if r["state"] == "recording":
            lv = r.get("live") or {}
            if eng is not None and getattr(eng, "live", None) is not None:
                try:
                    eng.live.stop_recording(lv.get("recorder"), lv.get("recording"))
                except ValueError as e:
                    raise FormError(str(e))
                self._cancel_runs(eng, lambda x: x.get("requestId") == rid)   # 作りかけの切り抜きは捨てる
            self.inbox.cancelled(rid)
            return {"id": rid, "state": "cancelled"}
        if r["state"] in ("sent", "making"):
            if r.get("kind") == "file" and not r.get("runId"):   # 写している途中 = 写すのは糸が見て止まらないので、行を消す(写しは片付けが消す)
                self.inbox.cancelled(rid, drop=True)
                return {"id": rid, "state": "cancelled"}
            if eng is not None and r.get("runId"):
                self._cancel_runs(eng, lambda x: x.get("id") == r["runId"])
            self.inbox.cancelled(rid, drop=r["state"] == "sent" or not r["packs"])
            return {"id": rid, "state": "cancelled"}
        raise FormError("取り消せる行ではありません")

    def update_live(self, rid, body):
        """録画中のライブの行の設定を途中で変える(C-2-11。POST /api/friend/live-settings)。body = {perHour?, lengthMode?: auto|fixed, length?, afterStream?}
        (無い鍵は今の値のまま・length は fixed のときだけ読む・範囲は送る欄と同じ check_settings)。② のライブ係の結びつきを差し替え、行の form.live も
        書き換える = これから採用・切り出す物から効く(もう切った物は作り直さない)。-> 行。ユーザーの PC に頼んだ行・録画中でない行・値の違いは FormError"""
        r = self.inbox.row(rid)
        if r is None:
            raise KeyError(rid)
        if r.get("kind") != "live":
            raise FormError("ライブの行ではありません")
        if r.get("pc") == "user":
            raise FormError("作る人の PC で録画している依頼は、ここから変えられません")
        lv = r.get("live") if isinstance(r.get("live"), dict) else {}
        if r["state"] != "recording" or not lv.get("recording") or lv.get("endedAt"):
            raise FormError("録画中の行だけ設定を変えられます")
        cur = (r.get("form") or {}).get("live") or {}
        mode = body.get("lengthMode", cur.get("lengthMode") if cur.get("lengthMode") in LENGTH_MODES else "fixed")   # 無い = 前の形の行 = 固定
        if mode not in LENGTH_MODES:
            raise FormError("長さは「自動(場面ごと)」か「固定」を選んでください")
        s = {k: v for k, v in _live.clean_settings(cur).items() if k != "lengthMode"}
        for k in ("perHour", "afterStream"):
            if k in body:
                s[k] = body[k]
        if mode == "fixed" and "length" in body:
            s["length"] = body["length"]
        try:
            new = dict(_live.check_settings(s), lengthMode=mode)
        except ValueError as e:
            raise FormError(str(e))
        eng = self.engine_fn()
        if eng is None or getattr(eng, "live", None) is None:
            raise FormError("準備中です。少し待ってから、もう一度押してください")
        try:
            eng.live.change_request(lv.get("recorder"), lv.get("recording"), rid, new)
        except ValueError as e:   # 結びつきが無い(LiveError も ValueError)
            raise FormError(str(e))
        return self.inbox.set_live_form(rid, new)

    @staticmethod
    def _cancel_runs(eng, pick):
        for x in eng.queue.status().get("runs") or []:
            if x.get("state") in ("queued", "running") and pick(x):
                try:
                    eng.queue.cancel(x["id"])
                except Exception:   # noqa: BLE001  (もう終わった = 取り消す物が無い)
                    pass

    def report(self, rid):
        """[作る人に知らせる](C-2-16): 送り返しへ <依頼 id>__notice-<at>.notice.json(notes:docs/spec/friend.md の 12-4)-> 行"""
        r = self.inbox.row(rid)
        if r is None:
            raise KeyError(rid)
        cls = self.classify(r)
        now = int(self.clock() * 1000)
        doc = {"v": 1, "kind": "failure", "requestId": rid, "title": rowtitle(r), "code": cls["code"], "message": cls["message"],
               "detail": (r.get("error") or "")[:2000], "appVersion": _version.VERSION, "at": now, "log": _log_tail(self.log_path, NOTICE_LOG_MAX)}
        data = json.dumps(doc, ensure_ascii=False).encode("utf-8")
        while len(data) >= NOTICE_MAX and doc["log"]:
            doc["log"] = doc["log"][len(doc["log"]) // 4:]
            data = json.dumps(doc, ensure_ascii=False).encode("utf-8")
        box = self.places["outbox"]
        os.makedirs(box, exist_ok=True)
        path = os.path.join(box, "%s__notice-%013d.notice.json" % (rid, now))
        with open(path + ".tmp", "wb") as f:
            f.write(data)
        os.replace(path + ".tmp", path)
        if self.sync is not None:
            self.sync.kick()
        return self.inbox.reported(rid)

    # ------------------------------------------------------------ 見回り(玄関の watch が呼ぶ)
    def tick(self):
        """アーカイブ待ちの行を調べる・直る見込みのある失敗を自動でやり直す・落としたまま送らなかった動画を片付ける"""
        now = self.clock()
        for r in self.inbox.waiting_rows():
            if now - r["createdAt"] / 1000.0 >= WAIT_GIVE_UP:
                self.inbox.wait_failed(r["id"], "アーカイブが出ませんでした(1 日待ちました)")
                continue
            if now - (r.get("checkedAt") or 0) / 1000.0 < WAIT_EVERY:
                continue
            try:
                info = self.probe(r["form"]["url"]) or {}
            except Exception:   # noqa: BLE001  (調べられない = 次の回にもう一度)
                info = {}
            self.inbox.wait_checked(r["id"])
            if info.get("status") in ARCHIVE_OK:
                self._start_waited(r["id"])
        login = self.login_at()
        for r in self.inbox.view():
            if r["state"] != "failed" or r.get("cancelled") or not r.get("form"):
                continue
            cls = self.classify(r)
            if login and cls["code"] in _progress.LOGIN_CODES and r.get("pc") != "user" and (r.get("failedAt") or 0) < login:
                try:   # ログインし直した: 前に bot・年齢で止まった行をやり直す(1 回。また落ちれば failedAt がログインより後になる)
                    self.retry(r["id"])
                except (FormError, KeyError):
                    pass
                continue
            if cls["retry"] and (r.get("autoRetries") or 0) < cls.get("retryMax", RETRY_MAX) and \
                    now - (r.get("failedAt") or 0) / 1000.0 >= cls.get("retryEvery", RETRY_EVERY):
                try:
                    self.retry(r["id"], auto=True)
                except (FormError, KeyError):
                    pass
        self.sweep_uploads()

    def _start_waited(self, rid):
        """アーカイブが出た: 普通の URL の依頼として作り始める(区間の長さの検査はここ = ② が配信の長さで断る)"""
        r = self.inbox.row(rid)
        if r is None:
            return
        self.inbox.wait_done(rid)
        r = self.inbox.row(rid)
        try:
            if r.get("pc") == "user":
                self._need_key()
                self.inbox.to_remote(rid)
                self.sync.kick()
                return
            eng = self.engine_fn()
            if eng is None:
                raise FormError("処理の部品が止まっています")
            self._need_parts()
            self._submit_this(eng, r)
        except FormError as e:
            self.inbox.fail(rid, str(e))

    # ------------------------------------------------------------ 画面へ
    def _progress(self, r, runs, blocked, stats, eng=None):
        """作っている行の進み具合の 1 行(C-2-15)-> {"text", "index", "total", "label"} か None"""
        run = r.get("run")
        f = r.get("form") or {}
        kind, ranged = r.get("kind") or "url", bool(f.get("ranges"))
        if r["state"] == "sent" and (not run or run.get("state") == "queued"):
            queued = [x.get("id") for x in runs if x.get("state") == "queued"]
            pos = queued.index(r["runId"]) + 1 if r.get("runId") in queued else None
            if blocked:
                return {"text": _progress.text(None, None, False, blocked=blocked), "index": 0, "total": 0, "label": ""}
            return {"text": _progress.text(None, None, False, queue_pos=pos) if pos else "順番を待っています", "index": 0, "total": 0, "label": ""}
        st = _progress.stage((run or {}).get("steps") or [], kind, ranged, with_raw=True)
        if st is not None and st["label"] == "文字起こし" and eng is not None:
            # 文字起こしは ② の段の中で止まったまま回る(ツールの transcribe_start が同じ糸で終わらせる)ので、段の detail は動かない。
            # 認識のジョブの進み(認識 42%)を玄関から直に読む
            live = getattr(eng, "transcribe_progress", lambda: None)()
            if live:
                st["detail"], st["raw"] = live, live
        if st is None:
            return {"text": "仕上げています", "index": 0, "total": 0, "label": ""}
        now = int(self.clock() * 1000)
        with self._lock:
            seen = self._stages.get(r["id"])
            if seen is None or seen[0] != st["label"]:
                if seen is not None:
                    self.inbox.record_stage(seen[0], (now - seen[1]) / 1000.0)
                seen = self._stages[r["id"]] = [st["label"], now, st["raw"], now]
            elif seen[2] != st["raw"]:
                seen[2], seen[3] = st["raw"], now
        left = _progress.eta(stats, kind, ranged, st["label"], (now - seen[1]) / 1000.0)
        return {"text": _progress.text(st, left, _progress.slow(seen[1], seen[3], now)), "index": st["index"], "total": st["total"], "label": st["label"]}

    def view(self):
        eng = self.engine_fn()
        st, flow = (eng.status_map() if eng else ({}, None))
        runs = list(st.values()) if isinstance(st, dict) else []
        blocked = (flow or {}).get("blocked")
        rows = self.inbox.view(status_of=lambda run_id: _public_run(st.get(run_id)))
        stats = self.inbox.stage_stats()
        sync = self.sync
        live_ids = set()
        for r in rows:
            run = r.get("run")
            if r["state"] == "sent" and run and run.get("state") == "running":
                r["state"] = "making"
            if r["state"] == "sent" and r.get("kind") == "file":   # 動画を写している(この PC)・Dropbox へ上げている(依頼)の進み具合
                prog = self.copy_progress(r["id"]) if r.get("pc") != "user" else (sync.upload_progress(r["id"]) if sync is not None else None)
                if prog:
                    r["progress"] = prog
            if r["state"] in ("sent", "making") and r.get("pc") != "user" and r.get("runId"):
                live_ids.add(r["id"])
                r["steps"] = self._progress(r, runs, blocked, stats, eng)
            if r["state"] == "failed":
                cls = self.classify(r)
                retrying = cls["retry"] and (r.get("autoRetries") or 0) < cls.get("retryMax", RETRY_MAX) and not r.get("cancelled")
                r["fail"] = {"code": cls["code"], "message": cls["message"], "detail": cls["detail"], "retrying": retrying,
                             "repeat": not retrying and (r.get("failCodes") or []).count(cls["code"]) >= 2, "reported": bool(r.get("reportedAt"))}
        with self._lock:   # 作っていない行の段の覚えを捨てる
            for k in [k for k in self._stages if k not in live_ids]:
                self._stages.pop(k, None)
        return {"rows": rows, "form": self.form(), "saveDir": self.places["save"](), "blocked": blocked, "ready": eng is not None}


def fsio_inside(path, root):
    try:
        return _fsio.is_inside(path, root)
    except (OSError, ValueError):
        return False


def rowtitle(r):
    s = r.get("source") or {}
    return str(s.get("title") or s.get("fileName") or s.get("videoId") or r.get("id") or "")[:200]


def _log_tail(path, cap):
    """ログの末尾 cap バイト(行の途中から始めない)"""
    try:
        with open(path, "rb") as f:
            f.seek(0, os.SEEK_END)
            size = f.tell()
            f.seek(max(0, size - cap))
            data = f.read(cap)
    except OSError:
        return ""
    text = data.decode("utf-8", "replace")
    if size > cap and "\n" in text:
        text = text.split("\n", 1)[1]
    return text


def _cut(f):
    """束に入れるカット(⚙ の既定が「しない」なら入れない = 束の既定のまま = 今までと同じ束)"""
    c = f.get("cut")
    return c if c in _spec.CUTS and c != "none" else None


def _public_run(r):
    if not r:
        return None
    return {k: r.get(k) for k in ("state", "stateLabel", "message", "step", "steps", "startedAt")}
