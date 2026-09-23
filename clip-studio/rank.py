"""① 配信ランキング(配信ランキング sr/serve.py 由来): 事務所・所属チャンネルの登録と、YouTube Data API による検索ジョブ。

HTTP は serve.py が受け持つ。ここは素の関数だけを公開する:
  get_registry() / put_registry(obj) / resolve(agency) / import_official_channels(agency)
  start_search(obj) / get_search(id) / cancel_search(id) / quota()
STUDIO_FAKE=1 のときは疑似API(ネットワークなし)で動く。
"""
import hashlib
import json
import os
import re
import threading
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

import common
from common import ApiError, Cancelled, atomic_write, get_api_key

API_BASE = "https://www.googleapis.com/youtube/v3/"
CHID_RE = re.compile(r"^UC[\w-]{22}\Z", re.ASCII)
HANDLE_RE = re.compile(r"^@[\w.\-]{3,60}\Z")
SLUG_RE = re.compile(r"[^a-z0-9_-]")
JST = timezone(timedelta(hours=9))
MAX_AGENCIES, MAX_CHANNELS = 30, 400
MAX_PAGES = 40            # 1チャンネルあたり、アップロード一覧を最大40ページ(=2000本)
WORKERS = 4
CACHE_TTL = 1800
SEED = os.path.join(common.CODE_DIR, "seed.json")

_quota = 0
_quota_lock = threading.Lock()
_reg_lock = threading.Lock()
_cache = {}
_cache_lock = threading.Lock()


def registry_path():
    return common.p("registry.json")


def quota():
    return _quota


def yt_get(path, params):
    """YouTube Data API を1回呼ぶ(すべて1ユニット)。テスト用の疑似モードでは fake_get を使う。"""
    global _quota
    with _quota_lock:
        _quota += 1
    if common.fake():
        return fake_get(path, params)
    key, _ = get_api_key()
    if not key:
        raise ApiError("no_key", "APIキーが未設定です(右上の「APIキー」から設定してください)", 400)
    url = API_BASE + path + "?" + urllib.parse.urlencode({**params, "key": key})
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    last = None
    for attempt in range(2):
        try:
            with urllib.request.urlopen(req, timeout=20) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            try:
                err = json.loads(e.read().decode("utf-8", "replace")).get("error", {})
            except ValueError:
                err = {}
            reason = (err.get("errors") or [{}])[0].get("reason", "")
            msg = str(err.get("message", ""))
            if reason in ("quotaExceeded", "rateLimitExceeded", "dailyLimitExceeded"):
                raise ApiError("quota", "YouTube APIの1日の利用上限に達しました(翌日、太平洋時間の0時にリセットされます)", 429)
            if reason in ("keyInvalid", "badRequest") and "key" in msg.lower():
                raise ApiError("key_invalid", "APIキーが正しくありません", 400)
            if reason in ("accessNotConfigured", "forbidden", "permissionError", "ipRefererBlocked") and e.code == 403:
                raise ApiError(
                    "api_permission",
                    "YouTube Data API の権限で拒否されました。Google Cloud で「YouTube Data API v3」を有効にし、この API キーのアプリケーション制限（IP アドレス・HTTP リファラー）と API 制限を確認してください",
                    403,
                )
            if e.code == 404 or reason in ("playlistNotFound", "channelNotFound"):
                raise ApiError("not_found", "見つかりません", 404)
            if e.code >= 500 and attempt == 0:
                last = ApiError("upstream", "YouTube APIがエラーを返しました(HTTP %d)" % e.code, 502)
                time.sleep(1)
                continue
            raise ApiError("upstream", "YouTube APIがエラーを返しました(HTTP %d)" % e.code, 502)
        except (urllib.error.URLError, TimeoutError, OSError):
            last = ApiError("network", "YouTube APIに接続できません", 502)
            if attempt == 0:
                time.sleep(1)
    raise last or ApiError("network", "YouTube APIに接続できません", 502)


# ---------- 疑似API(テスト用: STUDIO_FAKE=1) ----------
def _h(s, mod=1000003):
    return int(hashlib.sha1(s.encode()).hexdigest()[:8], 16) % mod


def fake_channel_id(ref):
    return "UC" + hashlib.sha1(ref.lower().encode()).hexdigest()[:22].replace("0", "a")[:22].ljust(22, "x")


def fake_video(cid, n):
    """チャンネル cid の n 本目(新しい順)の動画。日付は現在から遡る(2日に1本ぐらい)。"""
    vid = "f" + hashlib.sha1(("%s/%d" % (cid, n)).encode()).hexdigest()[:10]
    when = datetime.now(timezone.utc).replace(hour=12, minute=0, second=0, microsecond=0) - timedelta(days=n * 2 + _h(vid, 2), hours=_h(vid + "h", 5))
    words = ["雑談", "ゲーム", "歌枠", "マイクラ", "コラボ", "ホラー"]
    title = "【%s】%s配信 #%d" % (words[_h(vid, 6)], words[_h(vid + "x", 6)], n)
    live = _h(vid + "l", 10) < 8
    return {"id": vid, "publishedAt": when.strftime("%Y-%m-%dT%H:%M:%SZ"), "title": title, "views": _h(vid + "v", 900000) + 100, "live": live, "channelId": cid,
            "dur": ("PT%dH%dM%dS" % (1 + _h(vid, 3), _h(vid, 50), _h(vid, 50))) if live else "PT%dM%dS" % (_h(vid, 9), _h(vid, 50))}


def fake_get(path, params):
    if path == "channels":
        items = []
        if "forHandle" in params:
            ref = params["forHandle"]
            if "nothere" in ref:
                return {"items": []}
            ids = [fake_channel_id(ref)]
            names = {ids[0]: ref.lstrip("@")}
        else:
            ids = params["id"].split(",")
            names = {i: "ch-" + i[2:8] for i in ids}
        for i in ids:
            items.append({"id": i, "snippet": {"title": names.get(i, i)}, "contentDetails": {"relatedPlaylists": {"uploads": "UU" + i[2:]}}, "statistics": {"subscriberCount": "100000"}})
        return {"items": items}
    if path == "channelSections":
        cid = params["channelId"]
        ids = [fake_channel_id("%s-m%d" % (cid, k)) for k in range(4)]
        return {"items": [{"snippet": {"type": "multipleChannels"}, "contentDetails": {"channels": ids}}, {"snippet": {"type": "allPlaylists"}}]}
    if path == "playlistItems":
        cid = "UC" + params["playlistId"][2:]
        _fake_register(cid)
        start = int(params.get("pageToken") or 0)
        items = []
        for n in range(start, min(start + 50, 150)):
            v = fake_video(cid, n)
            items.append({"contentDetails": {"videoId": v["id"], "videoPublishedAt": v["publishedAt"]}})
        out = {"items": items}
        if start + 50 < 150:
            out["nextPageToken"] = str(start + 50)
        return out
    if path == "videos":
        items = []
        for vid in params["id"].split(","):
            found = None
            # 疑似動画IDからは元のチャンネルが分からないので、全チャンネルの候補を _FAKE_INDEX から引く
            found = _FAKE_INDEX.get(vid)
            if not found:
                continue
            v = found
            det = {"duration": v["dur"]}
            item = {"id": vid, "snippet": {"title": v["title"], "description": "説明文 " + v["title"], "channelId": v["channelId"], "channelTitle": "ch-" + v["channelId"][2:8],
                                           "publishedAt": v["publishedAt"], "thumbnails": {"medium": {"url": "https://i.ytimg.com/vi/%s/mqdefault.jpg" % vid}}},
                    "statistics": {"viewCount": str(v["views"]), "likeCount": str(v["views"] // 30), "commentCount": str(v["views"] // 200)}, "contentDetails": det}
            if v["live"]:
                st = datetime.strptime(v["publishedAt"], "%Y-%m-%dT%H:%M:%SZ")
                item["liveStreamingDetails"] = {"actualStartTime": v["publishedAt"], "actualEndTime": (st + timedelta(hours=2)).strftime("%Y-%m-%dT%H:%M:%SZ")}
            items.append(item)
        return {"items": items}
    raise ApiError("upstream", "fake: unknown " + path, 502)


class _FakeIndex(dict):
    def get(self, vid, default=None):
        if vid in self:
            return dict.get(self, vid)
        return default


_FAKE_INDEX = _FakeIndex()


def _fake_register(cid):
    for n in range(150):
        v = fake_video(cid, n)
        _FAKE_INDEX[v["id"]] = v


# ---------- 登録(事務所・所属チャンネル) ----------
def parse_ref(text):
    """入力(@ハンドル / チャンネルID / YouTubeのURL)→ 正規化した ref。読めなければ None。"""
    t = str(text or "").strip()
    if not t:
        return None
    m = re.match(r"^https?://(?:www\.|m\.)?youtube\.com/(.+)$", t)
    if m:
        p = urllib.parse.urlsplit("https://x/" + m.group(1)).path.strip("/").split("/")
        if p and p[0].startswith("@"):
            t = urllib.parse.unquote(p[0])
        elif len(p) >= 2 and p[0] == "channel":
            t = p[1]
        else:
            return None
    if CHID_RE.match(t):
        return t
    if not t.startswith("@") and re.match(r"^[\w.\-]{3,60}$", t):
        t = "@" + t
    return t if HANDLE_RE.match(t) else None


def sanitize_registry(obj):
    out, seen = [], set()
    for a in (obj.get("agencies") or [])[:MAX_AGENCIES]:
        if not isinstance(a, dict):
            continue
        name = str(a.get("name", "")).strip()[:40]
        aid = SLUG_RE.sub("", str(a.get("id", "")).lower())[:30] or "a" + hashlib.sha1(name.encode()).hexdigest()[:8]
        if not name or aid in seen:
            continue
        seen.add(aid)
        official = [r for r in (parse_ref(x) for x in (a.get("official") or [])[:10]) if r]
        chans, refs = [], set()
        for c in (a.get("channels") or [])[:MAX_CHANNELS]:
            if not isinstance(c, dict):
                continue
            ref = parse_ref(c.get("ref"))
            if not ref or ref.lower() in refs:
                continue
            refs.add(ref.lower())
            cid = c.get("id") if CHID_RE.match(str(c.get("id") or "")) else ""
            if CHID_RE.match(ref):
                cid = ref
            chans.append({"ref": ref, "id": cid, "title": str(c.get("title", ""))[:100] if cid else "",
                          "uploads": ("UU" + cid[2:]) if cid else "", "status": "ok" if cid else ("error" if c.get("status") == "error" else "pending"),
                          "note": str(c.get("note", ""))[:100] if not cid else ""})
        out.append({"id": aid, "name": name, "official": official, "channels": chans})
    return {"agencies": out}


def load_registry():
    for path in (registry_path(), SEED):
        try:
            with open(path, encoding="utf-8") as f:
                return sanitize_registry(json.load(f))
        except (OSError, ValueError):
            continue
    return {"agencies": []}


def save_registry(reg):
    atomic_write(registry_path(), json.dumps(reg, ensure_ascii=False, indent=1).encode("utf-8"))


def _resolve_channels(entries):
    """entries: 解決前の channel dict のリスト(その場で更新)。IDはまとめて50件ずつ、ハンドルは1件ずつ問い合わせる。"""
    by_id = [e for e in entries if CHID_RE.match(e["ref"])]
    for i in range(0, len(by_id), 50):
        part = by_id[i:i + 50]
        got = {it["id"]: it for it in yt_get("channels", {"part": "snippet,contentDetails", "id": ",".join(e["ref"] for e in part), "maxResults": 50}).get("items", [])}
        for e in part:
            it = got.get(e["ref"])
            _apply_channel(e, it)
    for e in entries:
        if CHID_RE.match(e["ref"]):
            continue
        try:
            items = yt_get("channels", {"part": "snippet,contentDetails", "forHandle": e["ref"]}).get("items", [])
        except ApiError as ex:
            if ex.code in ("quota", "no_key", "key_invalid", "api_not_enabled", "api_permission"):
                raise
            items = []
        _apply_channel(e, items[0] if items else None)


def _apply_channel(e, it):
    if not it:
        e.update({"id": "", "title": "", "uploads": "", "status": "error", "note": "見つかりません(ハンドル・IDを確認)"})
        return
    e["id"] = it["id"]
    e["title"] = str(it.get("snippet", {}).get("title", ""))[:100]
    e["uploads"] = it.get("contentDetails", {}).get("relatedPlaylists", {}).get("uploads") or "UU" + it["id"][2:]
    e["status"], e["note"] = "ok", ""


def resolve_registry(agency_id=None):
    with _reg_lock:
        reg = load_registry()
        todo = [c for a in reg["agencies"] if agency_id in (None, a["id"]) for c in a["channels"] if c["status"] != "ok"][:300]
        _resolve_channels(todo)
        save_registry(reg)
        return reg, len(todo), sum(1 for c in todo if c["status"] == "ok")


def import_official(agency_id):
    with _reg_lock:
        reg = load_registry()
        ag = next((a for a in reg["agencies"] if a["id"] == agency_id), None)
        if not ag:
            raise ApiError("not_found", "事務所が見つかりません", 404)
        if not ag["official"]:
            raise ApiError("no_official", "この事務所には公式チャンネルが登録されていません(下の欄に @ハンドルかURLを入れてください)", 400)
        offs = [{"ref": r, "id": "", "title": "", "uploads": "", "status": "pending", "note": ""} for r in ag["official"]]
        _resolve_channels(offs)
        found, notes = [], []
        for o in offs:
            if o["status"] != "ok":
                notes.append("公式チャンネル %s が見つかりません" % o["ref"])
                continue
            try:
                secs = yt_get("channelSections", {"part": "snippet,contentDetails", "channelId": o["id"]}).get("items", [])
            except ApiError as ex:
                if ex.code in ("quota", "no_key", "key_invalid", "api_not_enabled", "api_permission"):
                    raise
                secs = []
            n0 = len(found)
            for s in secs:
                for cid in (s.get("contentDetails", {}).get("channels") or []):
                    if CHID_RE.match(cid) and cid != o["id"] and cid not in found:
                        found.append(cid)
            if len(found) == n0:
                notes.append("%s の「チャンネル」欄に、取り込める所属チャンネルの一覧がありませんでした" % o["ref"])
        have = {c["ref"].lower() for c in ag["channels"]} | {c["id"].lower() for c in ag["channels"] if c["id"]}
        new = [{"ref": cid, "id": "", "title": "", "uploads": "", "status": "pending", "note": ""} for cid in found if cid.lower() not in have][:MAX_CHANNELS - len(ag["channels"])]
        _resolve_channels(new)
        ag["channels"].extend(new)
        save_registry(reg)
        return reg, len(new), notes


# ---------- 検索ジョブ ----------
_jobs = {}
_jobs_lock = threading.Lock()


def norm(s):
    return unicodedata.normalize("NFKC", str(s or "")).lower()


def parse_iso_dur(s):
    m = re.match(r"^P(?:(\d+)D)?T?(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?$", s or "")
    if not m:
        return 0
    d, h, mi, sec = (int(x or 0) for x in m.groups())
    return d * 86400 + h * 3600 + mi * 60 + sec


def parse_dt(s):
    if not s or not isinstance(s, str):
        return None
    try:
        return datetime.strptime(s, "%Y-%m-%dT%H:%M:%S%z" if s.endswith("+00:00") else "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        try:
            return datetime.fromisoformat(str(s).replace("Z", "+00:00"))
        except ValueError:
            return None


def validate_search(req):
    try:
        d0 = datetime.strptime(str(req.get("start")), "%Y-%m-%d").replace(tzinfo=JST)
        d1 = datetime.strptime(str(req.get("end")), "%Y-%m-%d").replace(tzinfo=JST) + timedelta(days=1)
    except ValueError:
        raise ApiError("bad_range", "期間(開始日・終了日)を入力してください", 400)
    if d1 <= d0:
        raise ApiError("bad_range", "終了日は開始日以降にしてください", 400)
    if (d1 - d0).days > 800:
        raise ApiError("bad_range", "期間が長すぎます(800日まで)", 400)
    words = [w for w in re.split(r"[\s,、]+", norm(req.get("words"))) if w][:20]
    reg = load_registry()
    want = req.get("agencies")
    ags = [a for a in reg["agencies"] if not isinstance(want, list) or a["id"] in want]
    if not ags:
        raise ApiError("no_agency", "対象の事務所を選んでください", 400)
    try:
        top = max(1, min(100, int(req.get("top") or 20)))
        min_views = max(0, int(req.get("minViews") or 0))
    except (TypeError, ValueError):
        raise ApiError("bad_request", "数値が正しくありません", 400)
    return {"start": d0, "end": d1, "words": words, "mode": "all" if req.get("mode") == "all" else "any", "inDesc": req.get("inDesc") is not False,
            "archiveOnly": req.get("archiveOnly") is not False, "noShorts": req.get("noShorts") is not False, "top": top, "minViews": min_views,
            "agencies": ags}


def _cached(key, fn):
    now = time.time()
    with _cache_lock:
        hit = _cache.get(key)
        if hit and now - hit[0] < CACHE_TTL:
            return hit[1]
    val = fn()
    with _cache_lock:
        if len(_cache) > 5000:
            _cache.clear()
        _cache[key] = (now, val)
    return val


def list_candidates(job, ch, spec):
    """チャンネルのアップロード一覧を新しい順に読み、期間(前後1日の余裕つき)に入る動画IDを返す。"""
    lo, hi = spec["start"] - timedelta(days=1), spec["end"] + timedelta(days=1)

    def run():
        ids, token = [], None
        for _ in range(MAX_PAGES):
            if job["cancel"]:
                raise Cancelled()
            p = {"part": "contentDetails", "playlistId": ch["uploads"], "maxResults": 50}
            if token:
                p["pageToken"] = token
            r = yt_get("playlistItems", p)
            page_old = 0
            items = r.get("items", [])
            for it in items:
                cd = it.get("contentDetails", {})
                t = parse_dt(cd.get("videoPublishedAt"))
                if t is None:
                    continue
                if t < lo:
                    page_old += 1
                elif t <= hi:
                    ids.append(cd["videoId"])
            token = r.get("nextPageToken")
            if not token or (items and page_old == len(items)):
                break
        return ids
    return _cached(("pl", ch["uploads"], spec["start"].date().isoformat(), spec["end"].date().isoformat()), run)


def fetch_videos(job, ids):
    out, todo = {}, []
    now = time.time()
    with _cache_lock:
        for i in ids:
            hit = _cache.get(("v", i))
            if hit and now - hit[0] < CACHE_TTL:
                out[i] = hit[1]
            else:
                todo.append(i)
    for k in range(0, len(todo), 50):
        if job["cancel"]:
            raise Cancelled()
        part = todo[k:k + 50]
        r = yt_get("videos", {"part": "snippet,statistics,contentDetails,liveStreamingDetails", "id": ",".join(part), "maxResults": 50})
        with _cache_lock:
            for it in r.get("items", []):
                out[it["id"]] = it
                _cache[("v", it["id"])] = (time.time(), it)
        job["progress"] = 0.5 + 0.4 * min(1.0, (k + 50) / max(1, len(todo)))
    return out


def video_row(it):
    sn, st, ld = it.get("snippet", {}), it.get("statistics", {}), it.get("liveStreamingDetails") or {}
    start = parse_dt(ld.get("actualStartTime")) or parse_dt(sn.get("publishedAt"))
    return {"id": it["id"], "title": sn.get("title", ""), "desc": sn.get("description", ""), "channelId": sn.get("channelId", ""), "channel": sn.get("channelTitle", ""),
            "views": int(st.get("viewCount") or 0), "likes": int(st.get("likeCount") or 0), "comments": int(st.get("commentCount") or 0),
            "at": start, "dur": parse_iso_dur(it.get("contentDetails", {}).get("duration")), "archive": bool(ld.get("actualEndTime")),
            "thumb": ((sn.get("thumbnails") or {}).get("medium") or {}).get("url", "")}


def matches(row, spec):
    if not spec["words"]:
        return True
    hay = norm(row["title"] + ("\n" + row["desc"] if spec["inDesc"] else ""))
    hits = [w in hay for w in spec["words"]]
    return all(hits) if spec["mode"] == "all" else any(hits)


def run_search(job, spec):
    q0 = _quota
    try:
        job["state"], job["phase"] = "running", "所属チャンネルを確認中"
        chans, unresolved = [], 0
        for a in spec["agencies"]:
            for c in a["channels"]:
                if c["status"] == "ok" and c["uploads"]:
                    chans.append((a["id"], c))
                else:
                    unresolved += 1
        if not chans:
            raise ApiError("no_channels", "対象の事務所に、解決済みの所属チャンネルがありません(「所属の登録」でチャンネルを登録し、「解決」してください)", 400)
        job["phase"] = "各チャンネルの配信一覧を読み込み中"
        cand, warns, done = {}, [], [0]

        def one(item):
            aid, c = item
            try:
                ids = list_candidates(job, c, spec)
            except Cancelled:
                raise
            except ApiError as ex:
                if ex.code in ("quota", "no_key", "key_invalid", "api_not_enabled", "api_permission"):
                    raise
                warns.append("%s: 一覧を読めませんでした(%s)" % (c["title"] or c["ref"], ex.message))
                ids = []
            done[0] += 1
            job["progress"] = 0.5 * done[0] / len(chans)
            return aid, c, ids
        with ThreadPoolExecutor(WORKERS) as ex:
            results = list(ex.map(one, chans))
        owner = {}
        for aid, c, ids in results:
            for vid in ids:
                owner.setdefault(vid, aid)
        job["phase"] = "動画の再生数などを取得中(%d本)" % len(owner)
        vids = fetch_videos(job, list(owner))
        job["phase"] = "絞り込み中"
        buckets = {a["id"]: [] for a in spec["agencies"]}
        scanned = {a["id"]: 0 for a in spec["agencies"]}
        for vid, aid in owner.items():
            it = vids.get(vid)
            if not it:
                continue
            row = video_row(it)
            if row["at"] is None or not (spec["start"] <= row["at"] < spec["end"]):
                continue
            scanned[aid] += 1
            if spec["archiveOnly"] and not row["archive"]:
                continue
            if spec["noShorts"] and row["dur"] <= 61:
                continue
            if row["views"] < spec["minViews"] or not matches(row, spec):
                continue
            buckets[aid].append(row)
        out = []
        for a in spec["agencies"]:
            rows = sorted(buckets[a["id"]], key=lambda r: -r["views"])
            out.append({"id": a["id"], "name": a["name"], "channels": sum(1 for c in a["channels"] if c["status"] == "ok"), "unresolved": sum(1 for c in a["channels"] if c["status"] != "ok"),
                        "scanned": scanned[a["id"]], "matched": len(rows),
                        "items": [{"id": r["id"], "title": r["title"], "channel": r["channel"], "channelId": r["channelId"], "views": r["views"], "likes": r["likes"], "comments": r["comments"],
                                   "at": r["at"].astimezone(JST).strftime("%Y-%m-%d %H:%M"), "dur": r["dur"], "url": "https://www.youtube.com/watch?v=" + r["id"], "thumb": r["thumb"]}
                                  for r in rows[:spec["top"]]]})
        job["result"] = {"agencies": out, "warnings": warns[:30], "unresolved": unresolved, "quota": _quota - q0, "videos": len(vids)}
        job["state"], job["phase"], job["progress"] = "done", "完了", 1.0
    except Cancelled:
        job["state"], job["phase"] = "cancelled", "中止しました"
    except ApiError as e:
        job["state"], job["error"], job["phase"] = "error", e.message, "失敗"
    except Exception as e:  # 想定外でも落とさない
        job["state"], job["error"], job["phase"] = "error", "内部エラー: %s %s" % (e.__class__.__name__, str(e)[:200]), "失敗"


def _start_search(spec):
    with _jobs_lock:
        if any(j["state"] in ("queued", "running") for j in _jobs.values()):
            raise ApiError("busy", "別の検索が実行中です", 409)
        for k in list(_jobs)[:-5]:
            _jobs.pop(k, None)
        jid = uuid.uuid4().hex[:10]
        job = {"id": jid, "state": "running", "phase": "開始", "progress": 0.0, "cancel": False, "error": "", "result": None}
        _jobs[jid] = job
    threading.Thread(target=run_search, args=(job, spec), daemon=True).start()
    return job


def job_public(j):
    return {k: j[k] for k in ("id", "state", "phase", "progress", "error", "result")}


# ---------- serve.py から呼ぶ公開関数 ----------
def get_registry():
    return load_registry()


def put_registry(obj):
    with _reg_lock:
        reg = sanitize_registry(obj)
        save_registry(reg)
    return reg


def resolve(agency):
    reg, n, ok = resolve_registry(str(agency) if agency else None)
    return {"registry": reg, "tried": n, "resolved": ok}


def import_official_channels(agency):
    reg, n, notes = import_official(str(agency or ""))
    return {"registry": reg, "added": n, "notes": notes}


def start_search(req):
    return job_public(_start_search(validate_search(req)))


def get_search(jid):
    j = _jobs.get(str(jid or ""))
    if not j:
        raise ApiError("not_found", "検索が見つかりません", 404)
    return job_public(j)


def cancel_search(jid):
    j = _jobs.get(str(jid or ""))
    if j:
        j["cancel"] = True
    return True
