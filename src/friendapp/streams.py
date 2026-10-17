# -*- coding: utf-8 -*-
"""友人のアプリの「送る」画面の左に並べる、ホロライブ JP(と DEV_IS)の配信の一覧(F3-2)。API キー無し。

- 名簿 = ytt.colors.members_path() の members.json。branch が JP か DEV_IS の人のうち、channel(UC で始まる 24 文字)がある人だけ
- 新着 = 各チャンネルの RSS(Atom)。5 分おき・同時 4 本まで
- 確かめ = RSS で初めて見た動画と、ライブ中・予定・終わったばかりの物だけ、動画のページを読む(ytInitialPlayerResponse の JSON)。
  読み直しは画面が開いている間(view() が 2 分以内に呼ばれた)は 90 秒おき、閉じていれば 5 分おきの回だけ
- 段 = ライブ中・これから(live) / 今日(today) / 昨日(yesterday)。範囲は前日の 0 時より後に始まった・終わった配信と、これからの予定(今から 12 時間と今日の 24 時の遅いほう)
- 取れないとき = 429 か 403 が来たら 10 分は何も取りに行かない。全部取れなければ error(前の一覧は残す)。覚えた一覧は cache_path の JSON

画面は view() を 3 秒おきに読むだけ。取る処理は tick()(start() の裏の糸が 1 秒おきに呼ぶ)。
"""
import concurrent.futures
import json
import math
import os
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta

from ytt import colors, fsio

BRANCHES = ("JP", "DEV_IS")
CHANNEL_RE = re.compile(r"^UC[A-Za-z0-9_-]{22}$")
VIDEO_RE = re.compile(r"^[A-Za-z0-9_-]{11}$")
RSS_URL = "https://www.youtube.com/feeds/videos.xml?channel_id=%s"
WATCH_URL = "https://www.youtube.com/watch?v=%s"
THUMB_URL = "https://i.ytimg.com/vi/%s/mqdefault.jpg"
HOSTS = ("youtube.com", "www.youtube.com")
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
POLL_SEC = 300          # 新着を見回る間隔
BLOCK_SEC = 600         # 429 / 403 で断られたあと取りに行かない時間
OPEN_SEC = 120          # view() がこの秒数以内に呼ばれていれば画面が開いている
REREAD_SEC = 90         # 画面が開いているときの読み直し
RETRY_SEC = 60          # 「確かめ中」の物を取り直す間隔(見回りの間)
SOON_SEC = 600          # 予定の物は開始の 10 分前から読み直す
HORIZON_SEC = 12 * 3600 # これからの予定は今から 12 時間まで(今日の 24 時の遅いほうまで)
OLD_SEC = 2 * 86400     # 前日の 0 時より 2 日以上前に出た新着は範囲の外として読まない
KEEP_SEC = 48 * 3600    # 出さない物・ライブの覚えを残す時間
TRIES_MAX = 3           # 動画のページが読めない(200 だが JSON が無い)回数。超えたら出さない物
WORKERS = 4
TIMEOUT = 15
READ_MAX = 4 * 1024 * 1024
TITLE_MAX = 200
CACHE_MAX = 8 * 1024 * 1024
STATES = ("checking", "live", "upcoming", "justEnded", "ended", "skip")
RSS_NS = "{http://www.w3.org/2005/Atom}"
YT_NS = "{http://www.youtube.com/xml/schemas/2015}"
PR_RE = re.compile(r"ytInitialPlayerResponse\s*=\s*")
MEMBER_WORDS = ("members", "メンバー限定", "メンバーシップ", "membership", "sponsors_only", "join this channel")
FIRST_MSG = "配信の一覧を取れませんでした。ネットを確かめて [もう一度] を押してください"
LIST_MSG = "新しい一覧を取れませんでした(%s の一覧を表示中)"
SECTION_LABELS = {"live": "ライブ中・これから", "today": "今日", "yesterday": "昨日"}


def _d(x):
    return x if isinstance(x, dict) else {}


def _int(x):
    """数(数の文字列も可)-> int か None"""
    if isinstance(x, bool) or not isinstance(x, (int, float, str)):
        return None
    try:
        v = float(x)
    except ValueError:
        return None
    return int(v) if math.isfinite(v) else None


def _iso_ms(s):
    """ISO の日時の文字列 -> ミリ秒 か None"""
    if not isinstance(s, str) or not s.strip():
        return None
    try:
        dt = datetime.fromisoformat(s.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    return int(dt.timestamp() * 1000)


def _chan_ok(c):
    return isinstance(c, str) and CHANNEL_RE.match(c) is not None


def _day_bounds(now):
    """今の時刻 -> (今日の 0 時, 昨日の 0 時, 今日の 24 時) のミリ秒(PC の現地時刻)"""
    t0 = datetime.fromtimestamp(now).replace(hour=0, minute=0, second=0, microsecond=0)

    def ms(d):
        return int(d.timestamp() * 1000)
    return ms(t0), ms(t0 - timedelta(days=1)), ms(t0 + timedelta(days=1))


def _hhmm(ms):
    return time.strftime("%H:%M", time.localtime(ms / 1000.0))


def _find(obj, key, depth=0):
    """入れ子の JSON から key の最初の値(無ければ None)"""
    if depth > 12:
        return None
    if isinstance(obj, dict):
        if key in obj:
            return obj[key]
        vals = obj.values()
    elif isinstance(obj, list):
        vals = obj
    else:
        return None
    for v in vals:
        r = _find(v, key, depth + 1)
        if r is not None:
            return r
    return None


def _url_ok(url):
    p = urllib.parse.urlsplit(url)
    return p.scheme == "https" and (p.hostname or "") in HOSTS


class _SameHostsOnly(urllib.request.HTTPRedirectHandler):
    """転送は https の youtube.com / www.youtube.com だけ許す(ほかへは転送しない = 302 のまま返す)"""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if not _url_ok(newurl):
            return None
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _default_fetch(url, timeout):
    """(状態, 本文) を返す。ネットの失敗は (0, 空)。読む上限は READ_MAX"""
    if not _url_ok(url):
        raise ValueError("許されていない場所です")
    opener = urllib.request.build_opener(_SameHostsOnly)
    req = urllib.request.Request(url, headers={"Accept-Language": "ja", "User-Agent": UA})
    try:
        with opener.open(req, timeout=timeout) as r:
            return r.status, r.read(READ_MAX)
    except urllib.error.HTTPError as e:
        try:
            body = e.read(READ_MAX)
        except OSError:
            body = b""
        return e.code, body
    except (OSError, ValueError):
        return 0, b""


def parse_rss(body):
    """RSS(Atom)の本文 -> [{"videoId", "title", "published"}](形の違う項目は飛ばす)。読めなければ None"""
    try:
        root = ET.fromstring(body)
    except (ET.ParseError, ValueError):
        return None
    out = []
    for e in root.iter(RSS_NS + "entry"):
        vid = (e.findtext(YT_NS + "videoId") or "").strip()
        if not VIDEO_RE.match(vid):
            continue
        pub = _iso_ms(e.findtext(RSS_NS + "published")) or _iso_ms(e.findtext(RSS_NS + "updated"))
        if pub is None:
            continue
        title = (e.findtext(RSS_NS + "title") or "").strip()[:TITLE_MAX]
        out.append({"videoId": vid, "title": title, "published": pub})
    return out


def _player(html):
    """動画のページの ytInitialPlayerResponse = {...}; の JSON -> dict か None"""
    m = PR_RE.search(html)
    if not m:
        return None
    try:
        obj, _ = json.JSONDecoder().raw_decode(html, m.end())
    except ValueError:
        return None
    return obj if isinstance(obj, dict) else None


def classify(html, nowms):
    """動画のページ(HTML)-> {"state", "startAt", "endAt", "duration", "title"}。
    state は live・upcoming・justEnded・ended・skip(出さない)。読めなければ None(取り直す)"""
    pr = _player(html)
    if pr is None:
        return None
    vd, ps = _d(pr.get("videoDetails")), _d(pr.get("playabilityStatus"))
    mf = _d(_d(pr.get("microformat")).get("playerMicroformatRenderer"))
    lbd = _d(mf.get("liveBroadcastDetails"))
    title = str(vd.get("title") or "")[:TITLE_MAX]
    skip = {"state": "skip", "startAt": None, "endAt": None, "duration": None, "title": title}
    blob = json.dumps(ps, ensure_ascii=False).lower()
    if any(w in blob for w in MEMBER_WORDS) or not vd.get("isLiveContent") or mf.get("isShortsEligible"):
        return skip   # メンバー限定・投稿動画(プレミア公開を含む)・ショート。削除・非公開は vd が空なのでここ
    status = str(ps.get("status") or "")
    length = _int(vd.get("lengthSeconds")) or 0
    start = _iso_ms(lbd.get("startTimestamp"))
    end = _iso_ms(lbd.get("endTimestamp"))
    sched = _int(_find(ps, "scheduledStartTime"))   # 予定の開始(秒)。枠の案内(liveStreamOfflineSlateRenderer)の中
    sched_ms = sched * 1000 if sched else None
    if vd.get("isLive") or lbd.get("isLiveNow"):
        return {"state": "live", "startAt": start or nowms, "endAt": None, "duration": None, "title": title}
    if vd.get("isUpcoming") or (status == "LIVE_STREAM_OFFLINE" and sched_ms and sched_ms > nowms):
        s = sched_ms or start
        if s is None:
            return skip
        return {"state": "upcoming", "startAt": s, "endAt": None, "duration": None, "title": title}
    if end is None:
        return skip
    if start is None:
        start = end - length * 1000 if length > 0 else end
    playable = status == "OK" and length > 0
    return {"state": "ended" if playable else "justEnded", "startAt": start, "endAt": end,
            "duration": length if playable else None, "title": title}


def _clean_rec(x):
    """覚えの 1 件を読む(形が違えば None)"""
    if not isinstance(x, dict):
        return None
    vid, st, cid = x.get("videoId"), x.get("state"), x.get("channelId")
    if not isinstance(vid, str) or not VIDEO_RE.match(vid) or st not in STATES:
        return None
    if st != "skip" and (not _chan_ok(cid) or _int(x.get("startAt")) is None):
        return None
    return {"videoId": vid, "channelId": cid if _chan_ok(cid) else None, "title": str(x.get("title") or "")[:TITLE_MAX],
            "state": st, "startAt": _int(x.get("startAt")), "endAt": _int(x.get("endAt")), "duration": _int(x.get("duration")),
            "checkedAt": _int(x.get("checkedAt")), "tries": _int(x.get("tries")) or 0}


def _place(rec, nowms, yest0, t0, horizon):
    """1 件を段へ入れる -> "live" / "today" / "yesterday" か None(範囲の外)"""
    st, start, end = rec["state"], rec["startAt"], rec["endAt"]
    if st == "live":
        return "live"
    if st == "upcoming" or (st == "checking" and start > nowms):
        return "live" if yest0 <= start <= horizon else None
    if start >= yest0 or (end is not None and end >= yest0):
        return "today" if start >= t0 else "yesterday"
    return None


def _item(rec, roster):
    m = roster.get(rec["channelId"], {})
    vid = rec["videoId"]
    return {"videoId": vid, "url": WATCH_URL % vid, "title": rec["title"], "channelId": rec["channelId"],
            "streamer": m.get("name", ""), "hex": m.get("hex"), "thumb": THUMB_URL % vid, "state": rec["state"],
            "startAt": rec["startAt"], "endAt": rec["endAt"], "duration": rec["duration"]}


class Streams:
    def __init__(self, cache_path, members_path=None, fetch=None, clock=time.time, log=None):
        self._cache_path = cache_path
        self._members_path = members_path or colors.members_path()
        self._fetch = fetch or _default_fetch
        self._clock = clock
        self._log = log or (lambda msg: None)
        self._lock = threading.RLock()
        self._halt = threading.Event()     # この回の中で 429 / 403 が来た(以後この回は取りに行かない)
        self._stop = threading.Event()
        self._thread = None
        self._busy = False
        self._force = False
        self._first = False
        self._error = None
        self._blocked_until = 0.0
        self._last_poll = None
        self._last_view = None
        self._items = {}
        self._updated_ms = None
        self._roster = self._read_roster()
        self._load()

    # ---------- 裏の糸と合図 ----------
    def start(self):
        if self._thread is not None:
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="friend-streams", daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()

    def _loop(self):
        while not self._stop.is_set():
            try:
                self.tick()
            except Exception as e:   # 糸を止めない(次の回にまた取る)
                self._log("配信の一覧: %s" % e)
            self._stop.wait(1.0)

    def tick(self):
        """時刻を見て、やるべき取りに行きをする(テストは start せず tick を直接呼ぶ)"""
        with self._lock:
            if self._busy:
                return
            now = self._clock()
            if self._blocked_until > now:
                return
            nowms = int(now * 1000)
            poll = self._force or self._last_poll is None or now - self._last_poll >= POLL_SEC
            if poll:
                ids = self._detail_ids(nowms, True)
            else:
                opened = self._last_view is not None and now - self._last_view <= OPEN_SEC
                ids = self._detail_ids(nowms, False, opened)
                if not ids:
                    return
            self._busy = True
            if poll:
                self._force = False
                self._last_poll = now
        try:
            self._run(now, poll, ids)
        except Exception as e:
            self._log("配信の一覧: %s" % e)
        finally:
            with self._lock:
                self._busy = False

    def refresh(self):
        """[更新]: 次の見回りを今すぐ(断られて待っている間は待ちの残りを返す)"""
        with self._lock:
            now = self._clock()
            if self._blocked_until > now:
                return {"ok": False, "waitSec": int(math.ceil(self._blocked_until - now))}
            self._force = True
        return {"ok": True}

    def view(self):
        """画面が読む一覧(3 秒おき)。読まれた時刻で「画面が開いている」を決める"""
        now = self._clock()
        with self._lock:
            self._last_view = now
            return {"updatedAt": self._updated_ms, "busy": self._busy, "first": self._first,
                    "error": dict(self._error) if self._error else None, "sections": self._sections(now)}

    def lookup(self, video_id):
        """一覧の 1 件(URL を貼ったとき)。一覧に出ていなければ None"""
        if not isinstance(video_id, str) or not VIDEO_RE.match(video_id):
            return None
        now = self._clock()
        with self._lock:
            for sec in self._sections(now):
                for it in sec["items"]:
                    if it["videoId"] == video_id:
                        return dict(it)
        return None

    # ---------- 取る ----------
    def _run(self, now, poll, ids):
        nowms = int(now * 1000)
        _t0, yest0, _t24 = _day_bounds(now)
        self._halt.clear()
        failed = listed = False
        with concurrent.futures.ThreadPoolExecutor(max_workers=WORKERS) as pool:
            if poll:
                roster = self._read_roster()
                with self._lock:
                    self._roster = roster
                got = list(pool.map(self._rss, sorted(roster)))
                oks = [(cid, es) for cid, st, es in got if st == 200 and es is not None]
                if self._halt.is_set():
                    ids, failed = [], True
                elif roster and not oks:
                    failed = True
                else:
                    with self._lock:
                        ids = ids + self._merge(oks, nowms, yest0)
                        self._updated_ms = nowms
                        self._error = None
                        self._first = False
                    listed = True
            details = list(pool.map(lambda v: self._detail(v, nowms), ids))
        with self._lock:
            for vid, st, res in details:
                self._apply(vid, st, res, nowms)
            if failed or (self._halt.is_set() and not listed):
                self._failed()
            self._prune(nowms, yest0)
            self._save()

    def _get(self, url):
        """取りに行く -> (状態。取りに行かなかった = None, 本文)。429 / 403 は 10 分止める"""
        if self._halt.is_set():
            return None, b""
        try:
            st, body = self._fetch(url, TIMEOUT)
        except Exception:
            return 0, b""
        if st in (429, 403):
            self._halt.set()
            with self._lock:
                self._blocked_until = self._clock() + BLOCK_SEC
            self._log("配信の一覧: %s で断られた。10 分は取りに行かない" % st)
        return st, body

    def _rss(self, cid):
        st, body = self._get(RSS_URL % cid)
        return cid, st, (parse_rss(body) if st == 200 else None)

    def _detail(self, vid, nowms):
        st, body = self._get(WATCH_URL % vid)
        if st != 200:
            return vid, st, None
        return vid, st, classify(body.decode("utf-8", "replace"), nowms)

    def _merge(self, oks, nowms, yest0):
        """RSS の結果を覚えへ入れる(lock の中)。-> 新しく確かめる動画の ID"""
        new = []
        for cid, entries in oks:
            for e in entries:
                vid = e["videoId"]
                rec = self._items.get(vid)
                if rec is None:
                    if e["published"] < yest0 - OLD_SEC * 1000:
                        self._items[vid] = {"videoId": vid, "channelId": cid, "title": e["title"], "state": "skip",
                                            "startAt": None, "endAt": None, "duration": None, "checkedAt": nowms, "tries": 0}
                    else:
                        self._items[vid] = {"videoId": vid, "channelId": cid, "title": e["title"], "state": "checking",
                                            "startAt": e["published"], "endAt": None, "duration": None, "checkedAt": None, "tries": 0}
                        new.append(vid)
                elif rec["state"] != "skip" and not rec["title"]:
                    rec["title"] = e["title"]
        return new

    def _apply(self, vid, st, res, nowms):
        """動画のページの結果を覚えへ(lock の中)。取りに行かなかった(st None)物は触らない"""
        rec = self._items.get(vid)
        if rec is None or st is None:
            return
        rec["checkedAt"] = nowms
        if st != 200:
            return
        if res is None:
            rec["tries"] = rec["tries"] + 1
            if rec["state"] == "checking" and rec["tries"] >= TRIES_MAX:
                rec["state"] = "skip"
            return
        rec.update(state=res["state"], startAt=res["startAt"], endAt=res["endAt"], duration=res["duration"], tries=0)
        if res["title"]:
            rec["title"] = res["title"]

    def _detail_ids(self, nowms, poll, opened=False):
        """今回読む動画(lock の中)。見回りの回は出さない物以外すべて。間の回は確かめ中の再試行と画面が開いている間の読み直し"""
        out = []
        for rec in self._items.values():
            st = rec["state"]
            if st in ("ended", "skip"):
                continue
            age = nowms - (rec["checkedAt"] or 0)
            if poll:
                out.append(rec["videoId"])
            elif st == "checking" and age >= RETRY_SEC * 1000:
                out.append(rec["videoId"])
            elif opened and age >= REREAD_SEC * 1000 and (
                    st in ("live", "justEnded") or (st == "upcoming" and rec["startAt"] - nowms <= SOON_SEC * 1000)):
                out.append(rec["videoId"])
        return out

    def _failed(self):
        """全部取れなかった(lock の中)。初めてで前の一覧が無ければ first"""
        if self._updated_ms is None:
            self._first = True
            self._error = {"message": FIRST_MSG, "listAt": None}
        else:
            self._first = False
            self._error = {"message": LIST_MSG % _hhmm(self._updated_ms), "listAt": self._updated_ms}

    def _prune(self, nowms, yest0):
        """書くときに古い物を捨てる(lock の中)。前日の 0 時より前に終わった物・48 時間より前の出さない物"""
        keep_ms = nowms - KEEP_SEC * 1000
        for vid in list(self._items):
            rec = self._items[vid]
            st = rec["state"]
            if st in ("skip", "live"):
                ok = (rec["checkedAt"] or 0) >= keep_ms
            elif st == "upcoming":
                ok = rec["startAt"] >= yest0
            else:
                ok = (rec["endAt"] or rec["startAt"]) >= yest0
            if not ok:
                del self._items[vid]

    def _save(self):
        try:
            os.makedirs(os.path.dirname(os.path.abspath(self._cache_path)), exist_ok=True)
            fsio.write_json(self._cache_path, {"version": 1, "updatedAt": self._updated_ms, "items": list(self._items.values())})
        except (OSError, ValueError) as e:
            self._log("配信の一覧を覚えられませんでした: %s" % e)

    def _load(self):
        d = fsio.read_json_or(self._cache_path, None, max_bytes=CACHE_MAX, kind=dict)
        if not isinstance(d, dict):
            return
        self._updated_ms = _int(d.get("updatedAt"))
        for x in d.get("items") if isinstance(d.get("items"), list) else []:
            rec = _clean_rec(x)
            if rec is not None:
                self._items[rec["videoId"]] = rec

    def _read_roster(self):
        """members.json -> {チャンネル ID: {"name", "hex"}}(JP と DEV_IS の人で channel のある人だけ)。字幕の色は ytt.colors から"""
        d = fsio.read_json_or(self._members_path, None, max_bytes=colors.MAX_BYTES, kind=dict)
        if not isinstance(d, dict):
            return {}
        hexes = {e["id"]: e["hex"] for e in colors.load(members=self._members_path) if not e.get("mine")}
        out = {}
        for g in d.get("groups") if isinstance(d.get("groups"), list) else []:
            if not isinstance(g, dict) or g.get("branch") not in BRANCHES:
                continue
            for m in g.get("members") if isinstance(g.get("members"), list) else []:
                if not isinstance(m, dict):
                    continue
                cid, name = m.get("channel"), str(m.get("name") or "").strip()[:60]
                if not _chan_ok(cid) or not name:
                    continue
                h = hexes.get(str(m.get("id") or "")) or colors.norm_hex(m.get("hex"))
                out[cid] = {"name": name, "hex": h}
        return out

    # ---------- 一覧 ----------
    def _sections(self, now):
        """段ごとの一覧(lock の中)"""
        nowms = int(now * 1000)
        t0, yest0, t24 = _day_bounds(now)
        horizon = max(nowms + HORIZON_SEC * 1000, t24)
        buckets = {"live": [], "today": [], "yesterday": []}
        for rec in self._items.values():
            if rec["state"] == "skip" or rec["channelId"] not in self._roster:
                continue
            key = _place(rec, nowms, yest0, t0, horizon)
            if key:
                buckets[key].append(rec)
        buckets["live"].sort(key=lambda r: (0 if r["state"] == "live" else 1, r["startAt"]))
        buckets["today"].sort(key=lambda r: r["startAt"], reverse=True)
        buckets["yesterday"].sort(key=lambda r: r["startAt"], reverse=True)
        out = []
        for key in ("live", "today", "yesterday"):
            if buckets[key]:
                items = [_item(r, self._roster) for r in buckets[key]]
                out.append({"key": key, "label": SECTION_LABELS[key], "count": len(items), "items": items})
        return out
