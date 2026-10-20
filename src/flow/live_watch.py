"""② 配信の見回り: 登録した事務所のチャンネルから「配信中」と「これからの予定」を探す(いつ探すか・どれだけ覚えるか)。OPT-H2 D。

取得元は検索と同じ YouTube Data API(ytt/ytapi)と、渡された事務所の登録(登録簿そのものは ③ のもの。引数 ags で受ける)。
search(eventType=live)は 1 回 100 ユニットと高いので使わない。代わりに:
  見回り: 各チャンネルのアップロード一覧の先頭 LIVE_PAGE 本(playlistItems。1 チャンネル 1 ユニット)。配信中・予定の枠もアップロード一覧に入る。
          LIVE_SCAN_TTL(20 分)覚える = 新しく立った枠(ゲリラ配信など)が一覧に出るまで最大 20 分かかる
  状態:   見回りで見つけた動画を videos.list(50 本で 1 ユニット)で聞く。一度「配信でない」と分かった動画は聞き直さない
          (アーカイブ・投稿動画が配信中に戻ることはない)ので、2 回目からは配信中・予定の分だけ = ふつう 1 ユニット
  結果は LIVE_TTL(60 秒)覚える(画面の「更新」・2 分ごとの読み直しで外へ聞きすぎない)
取得の関数 get(path, params) と、事務所から解決済みのチャンネルを選ぶ関数 pick(ags) は呼び手が渡す(③ の rank は自分の yt_get を渡す = テストが差し替えられる)。
"""
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor

from pipeline.transcribe import roster as _roster
from ytt import ytapi as _api
from ytt import yturl as _yturl
from ytt.errors import ApiError

REGIONS = _roster.REGIONS   # 地域の種類(JP・EN・ID。名簿の members の region)

LIVE_TTL = 60
LIVE_SCAN_TTL = 1200
LIVE_PAGE = 15            # アップロード一覧の先頭から見る本数(枠を立ててから投稿が続いても拾えるように少し多め。何本でも 1 ユニット)
LIVE_AHEAD = 24 * 3600    # これからの予定は、24 時間以内に始まるものだけ
LIVE_LATE = 6 * 3600      # 予定の時刻を過ぎても始まらない枠は、6 時間で出さなくする(立てたまま使わなかった枠)
LIVE_TITLE_MAX, LIVE_NAME_MAX = 200, 100
WORKERS = 8               # 1 チャンネル 1 回の軽い問い合わせなので、検索(4)より多く並べる(最初の1回の待ち時間を短く)
# 録画できない印: メンバー限定は API に項目が無いので題から(録画の部品はログインしないので取れない)。年齢制限は contentRating から
MEMBERS_RE = re.compile(r"メン限|メンシ限|メンバー(?:シップ)?限定|members?[\s_-]*only|members?[\s_-]*limited", re.I)
none_ids = {}             # 配信でないと分かった動画 ID(聞き直さない)
_lock = threading.Lock()


def channel_regions():
    """チャンネル ID → 地域(JP・EN・ID)。名簿(① roster.ROSTER。無ければ同梱の名簿)の members の region から。名簿に無い・欄が無いチャンネルは入らない = 不明。
    検索(③ human/find/rank)も「配信中」も、地域の絞り込みはこの表を引く(登録簿には地域を二重に持たない)"""
    return _roster.channel_regions(_roster.ROSTER or _roster.BUNDLED)


def _scan(ch, get):
    """チャンネルのアップロード一覧の先頭 LIVE_PAGE 本の動画 ID(LIVE_SCAN_TTL 覚える)"""
    def run():
        r = get("playlistItems", {"part": "contentDetails", "playlistId": ch["uploads"], "maxResults": LIVE_PAGE})
        return [str(it.get("contentDetails", {}).get("videoId") or "") for it in r.get("items", [])][:LIVE_PAGE]
    return _api.cached(("lv-pl", ch["uploads"]), run, LIVE_SCAN_TTL)


def _ms(dt):
    return int(dt.timestamp() * 1000) if dt else 0


def live_row(it, now):
    """videos.list の1件 → 一覧の1行(配信中・24 時間以内の予定でなければ None)。外から来る文字は長さを切る"""
    vid = str(it.get("id") or "")
    if not _yturl.VID_RE.match(vid):
        return None
    sn, ld = it.get("snippet") or {}, it.get("liveStreamingDetails") or {}
    kind = sn.get("liveBroadcastContent")
    if kind == "live" and not ld.get("actualEndTime"):
        start = _api.parse_dt(ld.get("actualStartTime")) or _api.parse_dt(ld.get("scheduledStartTime"))
        try:
            viewers = max(0, int(ld.get("concurrentViewers")))
        except (TypeError, ValueError):
            viewers = None   # 視聴者数を隠している配信
    elif kind == "upcoming":
        start = _api.parse_dt(ld.get("scheduledStartTime"))
        if start is None or not (now - LIVE_LATE <= start.timestamp() <= now + LIVE_AHEAD):
            return None
        viewers = None
    else:
        return None
    title = str(sn.get("title") or "")[:LIVE_TITLE_MAX]
    thumbs = sn.get("thumbnails") or {}
    thumb = str((thumbs.get("medium") or thumbs.get("default") or {}).get("url") or "")
    if not re.match(r"^https://([\w-]+\.)?ytimg\.com/[\w./%-]{1,300}\Z", thumb):   # 画面の CSP(img-src)に合うものだけ
        thumb = ""
    cid = str(sn.get("channelId") or "")
    blocked = ""
    if MEMBERS_RE.search(title):
        blocked = "members"
    elif ((it.get("contentDetails") or {}).get("contentRating") or {}).get("ytRating") == "ytAgeRestricted":
        blocked = "age"
    return {"id": vid, "title": title, "channel": str(sn.get("channelTitle") or "")[:LIVE_NAME_MAX], "channelId": cid if _api.CHID_RE.match(cid) else "",
            "state": "live" if kind == "live" else "upcoming", "start": _ms(start), "viewers": viewers, "thumb": thumb,
            "url": _yturl.watch_url(vid), "blocked": blocked}


def _fetch(ids, get):
    """videos.list で状態を聞く(50 本ずつ)。配信でないと分かったものは none_ids に覚える"""
    out = {}
    for k in range(0, len(ids), 50):
        part = ids[k:k + 50]
        r = get("videos", {"part": "snippet,contentDetails,liveStreamingDetails", "id": ",".join(part), "maxResults": 50})
        got = set()
        for it in r.get("items", []):
            vid = str(it.get("id") or "")
            got.add(vid)
            ended = bool((it.get("liveStreamingDetails") or {}).get("actualEndTime"))
            if (it.get("snippet") or {}).get("liveBroadcastContent") in ("live", "upcoming") and not ended:
                out[vid] = it
            else:
                none_ids[vid] = True
        for vid in part:
            if vid not in got:   # 消えた・非公開になった動画も聞き直さない
                none_ids[vid] = True
    if len(none_ids) > 20000:
        none_ids.clear()
    return out


def _build(ags, now, get, pick):
    q0 = _api.used()
    chans, unresolved = pick(ags)
    warns, fails = [], []

    def one(item):
        a, c = item

        def failed(ex):
            warns.append("%s: 一覧を読めませんでした(%s)" % (c["title"] or c["ref"], ex.message))
            fails.append(ex)
        return a, _api.soft(lambda: _scan(c, get), [], failed)
    with ThreadPoolExecutor(WORKERS) as ex:
        results = list(ex.map(one, chans))
    if fails and len(fails) == len(chans):   # 1つも読めない(つながらないなど)は、空の一覧ではなく失敗として返す
        raise fails[0]
    owner = {}
    for a, ids in results:
        for vid in ids:
            if vid and vid not in none_ids:
                owner.setdefault(vid, a)
    got = _fetch(list(owner), get)
    live, upcoming = [], []
    for vid, it in got.items():
        row = live_row(it, now)
        if not row:
            continue
        a = owner[vid]
        row["agency"], row["agencyName"] = a["id"], a["name"]
        (live if row["state"] == "live" else upcoming).append(row)
    live.sort(key=lambda r: (-(r["viewers"] or 0), -r["start"], r["id"]))   # 視聴者数の多い順(隠している配信は後ろ)
    upcoming.sort(key=lambda r: (r["start"], r["id"]))                     # 始まる時刻の早い順
    return {"live": live, "upcoming": upcoming, "agencies": [{"id": a["id"], "name": a["name"]} for a in ags],
            "warnings": warns[:30], "unresolved": unresolved, "channels": len(chans), "quota": _api.used() - q0, "checkedAt": int(now * 1000)}


def live_list(ags, get, pick, now=None, scope=()):
    """配信中(視聴者数の多い順)と、24 時間以内に始まる予定(早い順)。ags: 対象の事務所の登録(1 つ以上。地域で絞った後のチャンネルを持つ)。
    LIVE_TTL 秒は同じ事務所・同じ絞り方(scope = 選んだ地域)の結果を返す(外へ聞かない)。同時に来たら1つずつ(2つの窓から開いても二重に聞かない)"""
    if not ags:
        raise ApiError("no_agency", "対象の事務所を選んでください", 400)
    key = ("lv", tuple(sorted(a["id"] for a in ags)), tuple(scope))
    with _lock:
        t = time.time() if now is None else now
        hit = _api.cache_get(key, LIVE_TTL, t)
        if hit is not _api.MISS:
            return dict(hit, cached=True)
        out = _build(ags, t, get, pick)
        _api.cache_put(key, out, t)
        return dict(out, cached=False)
