"""③ 配信の検索: 事務所・所属チャンネルの登録と、YouTube Data API による検索ジョブ。

HTTP は serve.py が受け持つ。ここは素の関数だけを公開する:
  get_registry() / put_registry(obj) / resolve(agency) / import_official_channels(agency)
  start_search(obj) / get_search(id) / cancel_search(id)
  live_list(agencies, now, regions)(配信中・これからの予定。画面の「配信中」のタブ。いつ探すか・覚える長さは ② flow/live_watch。ここは登録簿から事務所と地域を選んで渡す)
  attach_board(board)(掲示板に検索のジョブを出す。board_jobs・board_cancel は掲示板が呼ぶ引く形・取り消し)
STUDIO_FAKE=1 のときは疑似API(fake_yt.py。ネットワークなし。起動時に ytt/ytapi へ差し込む)で動く。
YouTube Data API を呼ぶ口は ytt/ytapi.get の 1 つ(失敗の対応表・数え・覚え)。ここの yt_get はその呼び手の名前(テストの差し替えの的)。
中の部品は _ を付けた名前。_ なしで残すのは、外から呼ぶ上の口と、テストが使う load_registry・sanitize_registry・validate_search・run_search・
parse_live_agencies・parse_regions・live_row・yt_get。
事務所の選び方は「ホロライブ / その他」の 2 つ(登録簿の事務所は消さず、ホロライブ以外を使うときに「その他」にまとめる)。
地域(JP・EN・ID・不明)の選び方: 名簿(hololive-roster.json の members の region)をチャンネル ID で引く。名簿に無い・欄が無い物は不明。
登録簿のチャンネルの 1 行に region を持てば(画面で人が選ぶ)それが先。YouTube のチャンネルの国は使わない。既定は JP と不明(不明は印つきで出す)。
"""
import hashlib
import json
import os
import re
import threading
import time
import unicodedata
import urllib.parse
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

from ytt import yturl as _yturl  # noqa: E402  動画 ID の形・動画のページ
from ytt import fsio as _fsio, studio_env as _env, ytapi as _ytapi  # noqa: E402  (src は studio/startup.py が sys.path に足してある)
from ytt.errors import ApiError, Cancelled  # noqa: E402
from flow import live_watch as _live  # noqa: E402  ② 配信の見回り(いつ探すか)

from . import fake_yt as _fake  # noqa: E402  疑似 API(STUDIO_FAKE=1)

NET_MSG = _ytapi.NET_MSG
CHID_RE = _ytapi.CHID_RE
HANDLE_RE = re.compile(r"^@[\w.\-]{3,60}\Z")
SLUG_RE = re.compile(r"[^a-z0-9_-]")
JST = timezone(timedelta(hours=9))
MAX_AGENCIES, MAX_CHANNELS = 30, 400
MAX_PAGES = 40            # 1チャンネルあたり、アップロード一覧を最大40ページ(=2000本)
WORKERS = 4
CACHE_TTL = _ytapi.CACHE_TTL
SEED = os.path.join(os.path.dirname(os.path.abspath(__file__)), "seed.json")   # 事務所の初期の登録(このファイルの隣)
GROUPS = (("hololive", "ホロライブ"), ("other", "その他"))   # 検索・配信中の事務所の選び方(登録簿のホロライブ以外は「その他」)
DEFAULT_GROUPS = ["hololive"]   # 事務所を省いたときに探すのはホロライブだけ(「その他」は手で選んだときだけ。ユーザー)
REGIONS = _live.REGIONS            # ("JP", "EN", "ID")
UNKNOWN = "unknown"                # 地域が決まらない物(名簿に無い・手の指定が無い)
DEFAULT_REGIONS = ("JP", UNKNOWN)  # 既定の地域(不明も探して、画面で印を付ける)
FATAL = _ytapi.FATAL   # 1チャンネルの失敗として続けず、検索・取り込み全体を止める失敗
LIVE_PAGE, LIVE_AHEAD, LIVE_TITLE_MAX = _live.LIVE_PAGE, _live.LIVE_AHEAD, _live.LIVE_TITLE_MAX   # テストが読む名前(本体は ② flow/live_watch)

_reg_lock = threading.Lock()
_cache = _ytapi.CACHE   # 覚えは ytt/ytapi の 1 か所(検索も「配信中」の見回りも使う)。テストが clear する名前
_cache_lock = _ytapi.CACHE_LOCK
_live_none = _live.none_ids   # テストが clear する名前
_MISS = _ytapi.MISS


def _registry_path():
    return _env.p("registry.json")


def yt_get(path, params):
    """YouTube Data API を1回呼ぶ(本体は ytt/ytapi.get。失敗の対応表・数え・疑似はそちら)。検索・解決・「配信中」の呼び手はこの名前を通す = テストが差し替えられる"""
    return _ytapi.get(path, params)


# 疑似の差し込み(疑似の本体 fake_yt は ③ にあり、ytt は読めないので起動時にここから渡す。STUDIO_FAKE=1 のときだけ使われる)
_ytapi.set_fake(lambda path, params: _fake.fake_get(path, params, _live.LIVE_PAGE))


# ---------- 登録(事務所・所属チャンネル) ----------
def parse_ref(text):
    """入力(@ハンドル / チャンネルID / YouTubeのURL)→ 正規化した ref。読めなければ None。
    読める URL は https://(www.|m.)youtube.com/@ハンドル と /channel/UC…(https なし・/c/名前・/user/名前・music. は読めない)。素の名前は頭に @ を足す"""
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


def _list(x):
    return x if isinstance(x, list) else []   # 形の違う入力(辞書・文字列)で 500 にしない


def sanitize_registry(obj):
    """画面から来た登録簿を整える -> {"agencies": [{id, name, official, channels}]}(知っている欄だけ写す。チャンネルの region は JP・EN・ID のときだけ。事務所 30・公式 10・所属チャンネル 400 まで)。
    チャンネルの ID が正しい形のときだけ解決済み(ok)にし、アップロード一覧の ID は ID から作る。画面から来た ID・名前は信じる(手元だけの道具)"""
    out, seen = [], set()
    for a in _list(obj.get("agencies") if isinstance(obj, dict) else None)[:MAX_AGENCIES]:
        if not isinstance(a, dict):
            continue
        name = str(a.get("name", "")).strip()[:40]
        aid = SLUG_RE.sub("", str(a.get("id", "")).lower())[:30] or "a" + hashlib.sha1(name.encode()).hexdigest()[:8]
        if not name or aid in seen:
            continue
        seen.add(aid)
        official = [r for r in (parse_ref(x) for x in _list(a.get("official"))[:10]) if r]
        chans, refs = [], set()
        for c in _list(a.get("channels"))[:MAX_CHANNELS]:
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
            if c.get("region") in REGIONS:   # 地域の手の指定(画面で人が選んだ物)。名簿より先に使う
                chans[-1]["region"] = c["region"]
        out.append({"id": aid, "name": name, "official": official, "channels": chans})
    return {"agencies": out}


def load_registry():
    """registry.json(無ければ seed.json)。registry.json が壊れていたら、退避してから seed.json で始める"""
    path = _registry_path()
    try:
        with open(path, encoding="utf-8-sig") as f:
            d = json.load(f)
        if not isinstance(d, dict):
            raise ValueError("形式が違います")
        return sanitize_registry(d)
    except FileNotFoundError:
        pass
    except ValueError as e:   # 読めたが中身が壊れている(UnicodeDecodeError も含む)
        _quarantine_registry(path, e)
    except OSError as e:
        # 一時的に開けない(Windows のウイルス対策のロックなど)ときは退避も seed への切り替えもしない
        # (seed で続けると、解決・取り込みの保存で登録が上書きされるため)
        _env.log_failure("registry.json の読み込み", e)
        raise ApiError("registry_read", "事務所の登録を読み込めませんでした。少し待ってからもう一度試してください", 500, {"detail": "registry.json: %s" % (e.strerror or e.__class__.__name__)})   # ファイル名は「元のメッセージ」へ
    return sanitize_registry(_fsio.read_json_or(SEED, {}))   # 読めなければ事務所なし


def _quarantine_registry(path, error):
    # 名前の末尾を .bak にするのは、.gitignore の *.bak に掛けるため(登録簿の置き場所がリポジトリの中のときに、push.bat の git add -A で公開リポジトリに載せない。
    # 今の置き場所は %LOCALAPPDATA% の studio フォルダでリポジトリの外)
    ts, n = time.strftime("%Y%m%d-%H%M%S"), 0
    dst = "%s.corrupt-%s.bak" % (path, ts)
    while os.path.exists(dst):   # 同じ秒に 2 回壊れても前の退避を上書きせず、壊れたファイルも置いたままにしない(review/store.py の _quarantine と同じ)
        n += 1
        dst = "%s.corrupt-%s-%d.bak" % (path, ts, n)
    try:
        os.replace(path, dst)
        _env.log_failure("registry.json が壊れていたため %s に退避しました" % os.path.basename(dst), error)
    except OSError as e:
        _env.log_failure("壊れた registry.json を退避できませんでした", e)


def _save_registry(reg):
    _fsio.atomic_write(_registry_path(), json.dumps(reg, ensure_ascii=False, indent=1).encode("utf-8"))


_soft = _ytapi.soft   # 1 チャンネルの失敗は続け、FATAL は投げ直す


def _pending(ref):
    """まだ解決していない所属チャンネル(_resolve_channels に渡す)"""
    return {"ref": ref, "id": "", "title": "", "uploads": "", "status": "pending", "note": ""}


def _resolve_channels(entries):
    """entries: 解決前の channel dict のリスト(その場で更新)。IDはまとめて50件ずつ、ハンドルは1件ずつ問い合わせる。"""
    by_id = [e for e in entries if CHID_RE.match(e["ref"])]
    for i in range(0, len(by_id), 50):
        part = by_id[i:i + 50]
        got = {it["id"]: it for it in yt_get("channels", {"part": "snippet,contentDetails", "id": ",".join(e["ref"] for e in part), "maxResults": 50}).get("items", [])}
        for e in part:
            _apply_channel(e, got.get(e["ref"]))
    for e in entries:
        if CHID_RE.match(e["ref"]):
            continue
        failed = []
        items = _soft(lambda: yt_get("channels", {"part": "snippet,contentDetails", "forHandle": e["ref"]}).get("items", []), [], failed.append)
        if failed:   # 問い合わせ自体の失敗(通信・サーバー)は「見つかりません」ではない: 未解決のまま残して次の「解決」でもう一度引く
            why = "通信" if failed[0].code == "network" else failed[0].message[:40]
            e.update({"id": "", "title": "", "uploads": "", "status": "pending", "note": "確かめられませんでした(%s)" % why})
            continue
        _apply_channel(e, items[0] if items else None)


def _apply_channel(e, it):
    if not it:
        e.update({"id": "", "title": "", "uploads": "", "status": "error", "note": "見つかりません(ハンドル・IDを確認)"})
        return
    e["id"] = it["id"]
    e["title"] = str(it.get("snippet", {}).get("title", ""))[:100]
    e["uploads"] = it.get("contentDetails", {}).get("relatedPlaylists", {}).get("uploads") or "UU" + it["id"][2:]
    e["status"], e["note"] = "ok", ""


def _resolve_registry(agency_id=None):
    """未解決の所属チャンネル(agency_id の事務所、None = 全部。300 まで)を引いて登録簿に保存する -> (登録簿, 試した数, 解決した数)"""
    with _reg_lock:
        reg = load_registry()
        todo = [c for a in reg["agencies"] if agency_id in (None, a["id"]) for c in a["channels"] if c["status"] != "ok"][:300]
        _resolve_channels(todo)
        _save_registry(reg)
        return reg, len(todo), sum(1 for c in todo if c["status"] == "ok")


def _import_official(agency_id):
    """事務所の公式チャンネルの「チャンネル」欄から所属チャンネルを取り込み、まだ無い物を足して解決する -> (登録簿, 足した数, メモ)。
    公式チャンネルが未登録なら 400(no_official)・事務所が無ければ 404"""
    with _reg_lock:
        reg = load_registry()
        ag = next((a for a in reg["agencies"] if a["id"] == agency_id), None)
        if not ag:
            raise ApiError("not_found", "事務所が見つかりません", 404)
        if not ag["official"]:
            raise ApiError("no_official", "この事務所には公式チャンネルが登録されていません(下の欄に @ハンドルかURLを入れてください)", 400)
        offs = [_pending(r) for r in ag["official"]]
        _resolve_channels(offs)
        found, notes = [], []
        for o in offs:
            if o["status"] != "ok":
                notes.append("公式チャンネル %s が見つかりません" % o["ref"])
                continue
            secs = _soft(lambda: yt_get("channelSections", {"part": "snippet,contentDetails", "channelId": o["id"]}).get("items", []), [])
            n0 = len(found)
            for s in secs:
                for cid in (s.get("contentDetails", {}).get("channels") or []):
                    if CHID_RE.match(cid) and cid != o["id"] and cid not in found:
                        found.append(cid)
            if len(found) == n0:
                notes.append("%s の「チャンネル」欄に、取り込める所属チャンネルの一覧がありませんでした" % o["ref"])
        have = {c["ref"].lower() for c in ag["channels"]} | {c["id"].lower() for c in ag["channels"] if c["id"]}
        new = [_pending(cid) for cid in found if cid.lower() not in have][:MAX_CHANNELS - len(ag["channels"])]
        _resolve_channels(new)
        ag["channels"].extend(new)
        _save_registry(reg)
        return reg, len(new), notes


# ---------- 検索ジョブ ----------
_jobs = {}
_jobs_lock = threading.Lock()


def _norm(s):
    return unicodedata.normalize("NFKC", str(s or "")).lower()


def _parse_iso_dur(s):
    m = re.match(r"^P(?:(\d+)D)?T?(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?$", s or "")
    if not m:
        return 0
    d, h, mi, sec = (int(x or 0) for x in m.groups())
    return d * 86400 + h * 3600 + mi * 60 + sec


_parse_dt = _ytapi.parse_dt


def parse_regions(arg):
    """?regions=JP,unknown(カンマ区切り。配列でもよい)→ 地域のリスト(JP・EN・ID・unknown。ほかの文字は捨てる)。None(引数なし)= 既定(JP と unknown)。空のリストは「1 つも選ばない」"""
    if arg is None:
        return list(DEFAULT_REGIONS)
    items = arg if isinstance(arg, list) else str(arg)[:100].split(",")
    out = []
    for x in items:
        x = str(x).strip()
        k = UNKNOWN if x.lower() == UNKNOWN else x.upper()
        if k in REGIONS + (UNKNOWN,) and k not in out:
            out.append(k)
    return out


def _channel_region(c, table):
    """所属チャンネルの地域: 手の指定 → 名簿(チャンネル ID で引く)→ 決まらなければ ""(不明)"""
    if c.get("region") in REGIONS:
        return c["region"]
    return table.get(c.get("id") or "", "")


def _scope(ags, want, regions):
    """登録簿の事務所 → 検索・配信中の対象 [{id, name, channels}](「ホロライブ」「その他」の順。ホロライブ以外の事務所は「その他」にまとめる)。
    want = 選んだ id の一覧(事務所の id でも hololive・other でもよい。リストでなければ DEFAULT_GROUPS = ホロライブだけ)。channels は選んだ地域に入る物だけで、各チャンネルに region(不明は "")を足した写し。
    解決済みのチャンネルがあるのに地域の選びで全部外れたら 400(no_region)"""
    table = _live.channel_regions()
    keys = set(regions)
    groups = {gid: {"id": gid, "name": name, "channels": []} for gid, name in GROUPS}
    seen = set()
    before = after = 0
    if not isinstance(want, list):
        want = DEFAULT_GROUPS
    for a in ags:
        gid = "hololive" if a["id"] == "hololive" else "other"
        if gid not in want and a["id"] not in want:
            continue
        seen.add(gid)
        for c in a["channels"]:
            ok = c["status"] == "ok" and bool(c["uploads"])
            r = _channel_region(c, table)
            before += ok
            if (r or UNKNOWN) in keys:
                after += ok
                groups[gid]["channels"].append(dict(c, region=r))
    if before and not after:
        raise ApiError("no_region", "選んだ地域に当てはまるチャンネルがありません(地域を増やすか、事務所の登録で地域を選んでください)", 400)
    return [groups[gid] for gid, _n in GROUPS if gid in seen]


def validate_search(req):
    """検索の指定(画面の JSON)を検査して整える -> spec。期間は日本時間の開始日 0 時〜終了日の次の日 0 時(800 日まで)・ワードは NFKC と小文字で 20 個まで・
    top は事務所ごとの上位の数(1〜100)・minViews は最低の再生数・minDur は最低の再生時間(秒。画面の「10分以上だけ」= 600)・agencies は「ホロライブ」「その他」の選び(hololive・other。登録簿の事務所の id でもよい。省くとホロライブだけ)・
    regions は探す地域(JP・EN・ID・unknown。省くと JP と unknown)。
    spec["req"] に元の指定を持つ(掲示板のやり直しが今の登録簿でもう一度検査するため)。だめなら ApiError 400"""
    try:
        d0 = datetime.strptime(str(req.get("start")), "%Y-%m-%d").replace(tzinfo=JST)
        d1 = datetime.strptime(str(req.get("end")), "%Y-%m-%d").replace(tzinfo=JST) + timedelta(days=1)
    except ValueError:
        raise ApiError("bad_range", "期間(開始日・終了日)を入力してください", 400)
    if d1 <= d0:
        raise ApiError("bad_range", "終了日は開始日以降にしてください", 400)
    if (d1 - d0).days > 800:
        raise ApiError("bad_range", "期間が長すぎます(800日まで)", 400)
    words = [w for w in re.split(r"[\s,、]+", _norm(req.get("words"))) if w][:20]
    reg = load_registry()
    regions = parse_regions(req.get("regions"))
    if not regions:
        raise ApiError("no_region", "探す地域を 1 つ以上選んでください", 400)
    ags = _scope(reg["agencies"], req.get("agencies"), regions)
    if not ags:
        raise ApiError("no_agency", "対象の事務所を選んでください", 400)
    try:
        top = max(1, min(100, int(req.get("top") or 20)))
        min_views = max(0, int(req.get("minViews") or 0))
        # 最低の再生時間(秒)。画面の「10分以上だけ」= 600。送られなければ 0 = 絞らない
        min_dur = int(req.get("minDur") or 0)
    except (TypeError, ValueError):
        raise ApiError("bad_request", "数値が正しくありません", 400)
    if not 0 <= min_dur <= 86400:
        raise ApiError("bad_request", "最低の再生時間が正しくありません(0〜86400秒)", 400)
    return {"start": d0, "end": d1, "words": words, "mode": "all" if req.get("mode") == "all" else "any", "inDesc": req.get("inDesc") is not False,
            "archiveOnly": req.get("archiveOnly") is not False, "noShorts": req.get("noShorts") is not False, "top": top, "minViews": min_views,
            "minDur": min_dur, "agencies": ags, "regions": regions, "req": dict(req)}


_cache_get = _ytapi.cache_get
_cached = _ytapi.cached


def _list_candidates(job, ch, spec):
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
                t = _parse_dt(cd.get("videoPublishedAt"))
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


def _fetch_videos(job, ids):
    out, todo = {}, []
    now = time.time()
    for i in ids:
        hit = _cache_get(("v", i), CACHE_TTL, now)
        if hit is _MISS:
            todo.append(i)
        else:
            out[i] = hit
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


def _video_row(it):
    """videos.list の 1 件 -> 検索の 1 行(at = 配信を始めた時刻、無ければ公開日時。archive = 配信が終わった時刻がある)"""
    sn, st, ld = it.get("snippet", {}), it.get("statistics", {}), it.get("liveStreamingDetails") or {}
    start = _parse_dt(ld.get("actualStartTime")) or _parse_dt(sn.get("publishedAt"))
    return {"id": it["id"], "title": sn.get("title", ""), "desc": sn.get("description", ""), "channelId": sn.get("channelId", ""), "channel": sn.get("channelTitle", ""),
            "views": int(st.get("viewCount") or 0), "likes": int(st.get("likeCount") or 0), "comments": int(st.get("commentCount") or 0),
            "at": start, "dur": _parse_iso_dur(it.get("contentDetails", {}).get("duration")), "archive": bool(ld.get("actualEndTime")),
            "thumb": ((sn.get("thumbnails") or {}).get("medium") or {}).get("url", "")}


def _matches(row, spec):
    """題名(と、inDesc なら概要欄)にワードが入っているか(mode all = 全部・any = どれか。ワードなしは常に真)"""
    if not spec["words"]:
        return True
    hay = _norm(row["title"] + ("\n" + row["desc"] if spec["inDesc"] else ""))
    hits = [w in hay for w in spec["words"]]
    return all(hits) if spec["mode"] == "all" else any(hits)


def _ok_channels(ags):
    """解決済みの所属チャンネル [(事務所, チャンネル)] と、解決していないチャンネルの数。1つも無ければ ApiError"""
    chans, unresolved = [], 0
    for a in ags:
        for c in a["channels"]:
            if c["status"] == "ok" and c["uploads"]:
                chans.append((a, c))
            else:
                unresolved += 1
    if not chans:
        raise ApiError("no_channels", "対象の事務所に、解決済みのチャンネルがありません(設定の「事務所の登録」でチャンネルを登録し、「解決」してください)", 400)
    return chans, unresolved


def run_search(job, spec):
    """検索ジョブの本体(糸の中。結果・失敗は job に書く): 解決済みのチャンネルごとにアップロード一覧から期間に入る動画 ID を集める(0〜0.5)→
    動画の詳しい情報を引く(0.5〜0.9)→ 配信を始めた時刻が期間に入る・アーカイブだけ・ショートを除く(61 秒以下。2024-10 からのショートは 3 分までだが、
    画面の既定「10分以上だけ」で落ちる)・最低の再生時間・再生数・ワードで絞り、事務所ごとに再生数の多い順の上位 N 本。
    scanned = 期間に入った数(絞る前)。1 チャンネルの失敗は警告に積んで続け、上限・キーの失敗(FATAL)は全体を止める"""
    q0 = _ytapi.used()
    try:
        job["state"], job["phase"] = "running", "所属チャンネルを確認中"
        chans, unresolved = _ok_channels(spec["agencies"])
        job["phase"] = "各チャンネルの配信一覧を読み込み中"
        warns, done = [], [0]

        def one(item):
            a, c = item
            ids = _soft(lambda: _list_candidates(job, c, spec), [],
                        lambda ex: warns.append("%s: 一覧を読めませんでした(%s)" % (c["title"] or c["ref"], ex.message)))
            done[0] += 1
            job["progress"] = 0.5 * done[0] / len(chans)
            return a["id"], c, ids
        with ThreadPoolExecutor(WORKERS) as ex:
            results = list(ex.map(one, chans))
        owner, vreg = {}, {}
        for aid, c, ids in results:
            for vid in ids:
                owner.setdefault(vid, aid)
                vreg.setdefault(vid, c.get("region", ""))
        job["phase"] = "動画の再生数などを取得中(%d本)" % len(owner)
        vids = _fetch_videos(job, list(owner))
        job["phase"] = "絞り込み中"
        buckets = {a["id"]: [] for a in spec["agencies"]}
        scanned = {a["id"]: 0 for a in spec["agencies"]}
        for vid, aid in owner.items():
            it = vids.get(vid)
            if not it:
                continue
            row = _video_row(it)
            row["region"] = vreg.get(vid, "")
            if row["at"] is None or not (spec["start"] <= row["at"] < spec["end"]):
                continue
            scanned[aid] += 1
            if spec["archiveOnly"] and not row["archive"]:
                continue
            if spec["noShorts"] and row["dur"] <= 61:
                continue
            # 再生時間が分からない動画(dur 0 = 配信中・予定。アーカイブではない)も、最低の再生時間を決めたときは除く(ショートを除くのと同じ扱い)
            if row["dur"] < spec.get("minDur", 0):
                continue
            if row["views"] < spec["minViews"] or not _matches(row, spec):
                continue
            buckets[aid].append(row)
        out = []
        for a in spec["agencies"]:
            rows = sorted(buckets[a["id"]], key=lambda r: -r["views"])
            out.append({"id": a["id"], "name": a["name"], "channels": sum(1 for c in a["channels"] if c["status"] == "ok"), "unresolved": sum(1 for c in a["channels"] if c["status"] != "ok"),
                        "scanned": scanned[a["id"]], "matched": len(rows),
                        "items": [{"id": r["id"], "title": r["title"], "channel": r["channel"], "channelId": r["channelId"], "views": r["views"], "likes": r["likes"], "comments": r["comments"],
                                   "at": r["at"].astimezone(JST).strftime("%Y-%m-%d %H:%M"), "dur": r["dur"], "url": _yturl.watch_url(r["id"]), "thumb": r["thumb"], "region": r["region"]}
                                  for r in rows[:spec["top"]]]})
        job["result"] = {"agencies": out, "warnings": warns[:30], "unresolved": unresolved, "quota": _ytapi.used() - q0, "videos": len(vids)}
        job["state"], job["phase"], job["progress"] = "done", "完了", 1.0
    except Cancelled:
        job["state"], job["phase"] = "cancelled", "中止しました"
    except ApiError as e:   # code は画面が次の一手のボタン(設定を開く・事務所の登録を開く・もう一度)を選ぶのに使う。detail は畳んだ「元のメッセージ」へ
        job["state"], job["error"], job["phase"], job["code"], job["detail"] = "error", e.message, "失敗", e.code, (e.extra or {}).get("detail", "")
    except Exception as e:  # 想定外でも落とさない
        job["state"], job["error"], job["phase"], job["code"] = "error", "検索の途中で問題が起きました。もう一度検索してください", "失敗", "internal"
        job["detail"] = "%s %s" % (e.__class__.__name__, str(e)[:200])


def _start_search(spec):
    """検索ジョブを作って糸を立てる。同時に 1 本だけ(動いていれば 409 busy)・古いジョブは 5 個残して捨てる"""
    with _jobs_lock:
        if any(j["state"] in ("queued", "running") for j in _jobs.values()):
            raise ApiError("busy", "別の検索が実行中です", 409)
        for k in list(_jobs)[:-5]:
            _jobs.pop(k, None)
        jid = uuid.uuid4().hex[:10]
        job = {"id": jid, "state": "running", "phase": "開始", "progress": 0.0, "cancel": False, "error": "", "result": None,
               "created": int(time.time() * 1000), "spec": spec}   # created・spec は掲示板が読む(_job_public には出さない)
        _jobs[jid] = job
    threading.Thread(target=run_search, args=(job, spec), daemon=True).start()
    return job


def _job_public(j):
    """画面に返すジョブの形(spec・created は出さない = 掲示板が job を直に読む)"""
    return dict({k: j[k] for k in ("id", "state", "phase", "progress", "error", "result")}, code=j.get("code", ""), detail=j.get("detail", ""))


# ---------- 配信中・これからの予定(画面の「配信中」のタブ。探し方・覚える長さは ② flow/live_watch) ----------
live_row = _live.live_row   # テストが読む名前


def parse_live_agencies(arg):
    """?agencies=a,b(事務所 ID のカンマ区切り)→ ID のリスト。None(引数なし)= 全部"""
    if arg is None:
        return None
    s = str(arg)[:1000]
    out = []
    for x in s.split(","):
        x = SLUG_RE.sub("", x.strip().lower())[:30]
        if x and x not in out:
            out.append(x)
    return out[:MAX_AGENCIES]


def live_list(agencies=None, now=None, regions=None):
    """配信中(視聴者数の多い順)と、24 時間以内に始まる予定(早い順)。agencies: 「ホロライブ」「その他」の選び(hololive・other か登録簿の事務所の id のリスト。None = ホロライブだけ)。
    regions: 探す地域(JP・EN・ID・unknown のリストか、カンマ区切りの文字。None = JP と unknown)。各行に region(不明は "")を足す。
    登録簿から対象を選び、② flow/live_watch に渡す(この yt_get と _ok_channels も渡す)。事務所が 1 つも無ければ 400(no_agency)・地域が 1 つも無ければ 400(no_region)"""
    want = parse_live_agencies(agencies) if not isinstance(agencies, list) else parse_live_agencies(",".join(str(x) for x in agencies))
    keys = parse_regions(regions)
    if not keys:
        raise ApiError("no_region", "探す地域を 1 つ以上選んでください", 400)
    ags = _scope(load_registry()["agencies"], want, keys)
    out = _live.live_list(ags, yt_get, _ok_channels, now, scope=tuple(sorted(keys)))
    table = {c["id"]: c["region"] for a in ags for c in a["channels"] if c.get("id")}
    return dict(out, live=[dict(r, region=table.get(r["channelId"], "")) for r in out["live"]],
                upcoming=[dict(r, region=table.get(r["channelId"], "")) for r in out["upcoming"]])


# ---------- serve.py から呼ぶ公開関数 ----------
def _view(reg):
    """画面に返す登録簿: 保存した形に、名簿から引いた地域 auto(名簿に載るチャンネルだけ。保存はしない = sanitize_registry が落とす)を足す。
    画面の地域の選び(自動 / JP / EN / ID)が「自動だといま何になるか」を出すのに使う"""
    table = _live.channel_regions()
    return {"agencies": [dict(a, channels=[dict(c, auto=table[c["id"]]) if c.get("id") in table else c for c in a["channels"]]) for a in reg["agencies"]]}


def get_registry():
    return _view(load_registry())


def put_registry(obj):
    with _reg_lock:
        reg = sanitize_registry(obj)
        _save_registry(reg)
    return _view(reg)


def resolve(agency):
    reg, n, ok = _resolve_registry(str(agency) if agency else None)
    return {"registry": _view(reg), "tried": n, "resolved": ok}


def import_official_channels(agency):
    reg, n, notes = _import_official(str(agency or ""))
    return {"registry": _view(reg), "added": n, "notes": notes}


def start_search(req):
    return _job_public(_start_search(validate_search(req)))


def get_search(jid):
    j = _jobs.get(str(jid or ""))
    if not j:
        raise ApiError("not_found", "検索が見つかりません", 404)
    return _job_public(j)


# 掲示板(flow/board.py。頭 se・id = se:<検索の id>)。入口の側(スタジオの serve)が board を渡して 1 回呼ぶ
def attach_board(board):
    board.register("se", source=board_jobs, cancel=board_cancel)


def _board_job(j):
    state = j["state"] if j["state"] in ("running", "done", "error", "cancelled") else "error"
    return {"id": "se:" + j["id"], "kind": "search", "title": "配信の検索", "state": state, "phase": j["phase"], "progress": j["progress"],
            "createdAt": j.get("created"), "error": {"code": j.get("code") or None, "text": j["error"], "detail": j.get("detail") or None} if state == "error" else None,
            "canCancel": state == "running" and not j["cancel"], "canRetry": state in ("error", "cancelled")}


def board_jobs():
    """掲示板の引く形: 検索のジョブ(入れた順)-> [Job の辞書]"""
    with _jobs_lock:
        return [_board_job(j) for j in _jobs.values()]


def board_cancel(jid):
    """掲示板の取り消し: cancel_search と同じ。無い id は LookupError"""
    if str(jid or "") not in _jobs:
        raise LookupError("その検索はありません")
    cancel_search(jid)


def cancel_search(jid):
    j = _jobs.get(str(jid or ""))
    if j:
        j["cancel"] = True
    return True
