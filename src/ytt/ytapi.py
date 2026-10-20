"""YouTube Data API を 1 回呼ぶ口(OPT-H2 D。③ 配信の検索の rank.yt_get と ① のコメント欄 fetch_comments が別々に持っていた取得を 1 つに)。

- `get(path, params, count=True)`: キーは URL でなく見出し X-goog-api-key で送る(失敗の文・ログに URL が出ても漏れない)。
  失敗は ApiError の code で返す = quota(上限)・no_key・key_invalid・api_permission・not_found・upstream(5xx は 1 回やり直す)・network(1 回やり直す)。
  upstream の extra には reason(API が返した理由。無ければ空)と detail("HTTP 番号")を入れる
- `used()`: 起動してからの累計(すべて 1 ユニットとして数える)。実際に外へ出るとき(と疑似のとき)だけ数える = キーが無くて呼ばなかったときは数えない
- `set_fake(fn)`: 疑似の差し込み。STUDIO_FAKE=1 のとき fn(path, params) を使う(疑似の本体は ⑤ を読めない ③ の fake_yt。起動時に rank が差し込む)
- 覚え(`cached`・`cache_get`・`CACHE`): 取得の答えを秒数つきで覚える入れ物。検索(③)も「配信中」の見回り(② flow/live_watch)も使う
"""
import json
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone

from . import apikey as _key, studio_env as _env, yturl as _yturl
from .errors import ApiError

OEMBED = "https://www.youtube.com/oembed?format=json&url="   # 題とチャンネル名の取得(公開・キー不要。接続先は固定)
NET_MSG = "YouTube の API に接続できません。インターネットの接続を確かめてから、もう一度試してください"
CHID_RE = re.compile(r"^UC[\w-]{22}\Z", re.ASCII)   # チャンネル ID
CACHE_TTL = 1800
CACHE_MAX = 5000
MISS = object()
FATAL = ("quota", "no_key", "key_invalid", "api_not_enabled", "api_permission")   # 1チャンネルの失敗として続けず、検索・取り込み全体を止める失敗

_used = 0
_used_lock = threading.Lock()
_fake = None
CACHE = {}
CACHE_LOCK = threading.Lock()


def used():
    """YouTube Data API を呼んだ数の累計(起動から)。結果の「API の使用量」は前後の差"""
    return _used


def _count():
    global _used
    with _used_lock:
        _used += 1


def set_fake(fn):
    """STUDIO_FAKE=1 のときの答えの作り手 fn(path, params) を差し込む(None で外す)"""
    global _fake
    _fake = fn


def get(path, params, *, count=True):
    """YouTube Data API を 1 回呼んで JSON を返す。失敗は ApiError(上の説明)。count=False なら数えない"""
    if _fake is not None and _env.fake():
        if count:
            _count()
        return _fake(path, params)
    key, _ = _key.get_api_key()
    if not key:
        raise ApiError("no_key", "API キーが未設定です(設定の「YouTube Data API キー」で入れてください)", 400)
    if count:
        _count()
    url = _yturl.YT_API_BASE + path + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"Accept": "application/json", "X-goog-api-key": key})
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
                raise ApiError("key_invalid", "API キーが正しくありません(設定の「YouTube Data API キー」で入れ直してください)", 400)
            if reason in ("accessNotConfigured", "forbidden", "permissionError", "ipRefererBlocked") and e.code == 403:
                raise ApiError(
                    "api_permission",
                    "YouTube Data API の権限で拒否されました。Google Cloud で「YouTube Data API v3」を有効にし、この API キーのアプリケーション制限（IP アドレス・HTTP リファラー）と API 制限を確認してください",
                    403,
                )
            if e.code == 404 or reason in ("playlistNotFound", "channelNotFound"):
                raise ApiError("not_found", "見つかりません", 404)
            if e.code >= 500 and attempt == 0:   # サーバー側の一時的な失敗は1回だけやり直す
                time.sleep(1)
                continue
            raise ApiError("upstream", "YouTube の API がエラーを返しました。少し待ってから、もう一度試してください", 502, {"detail": "HTTP %d" % e.code, "reason": reason})   # 番号は画面の「元のメッセージ」へ
        except (urllib.error.URLError, TimeoutError, OSError):
            last = ApiError("network", NET_MSG, 502)
            if attempt == 0:
                time.sleep(1)
    raise last or ApiError("network", NET_MSG, 502)


def soft(fn, default, on_err=None):
    """fn() の ApiError のうち、全体を止めるもの(FATAL = 上限・キーなど)は投げ直し、
    それ以外(1 チャンネルの失敗)は on_err(ex) を呼んで default を返す"""
    try:
        return fn()
    except ApiError as ex:
        if ex.code in FATAL:
            raise
        if on_err:
            on_err(ex)
        return default


def parse_dt(s):
    """API の時刻の文字列 → 時刻つきの datetime(読めなければ None)"""
    if not s or not isinstance(s, str):
        return None
    try:
        return datetime.strptime(s, "%Y-%m-%dT%H:%M:%S%z" if s.endswith("+00:00") else "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        try:
            return datetime.fromisoformat(str(s).replace("Z", "+00:00"))
        except ValueError:
            return None


# ---------- 覚え ----------
def cache_get(key, ttl, now=None):
    """CACHE に覚えた値(ttl 秒以内のもの)。無ければ MISS"""
    now = time.time() if now is None else now
    with CACHE_LOCK:
        hit = CACHE.get(key)
    return hit[1] if hit and now - hit[0] < ttl else MISS


def cache_put(key, val, now=None):
    with CACHE_LOCK:
        if len(CACHE) > CACHE_MAX:
            CACHE.clear()
        CACHE[key] = (time.time() if now is None else now, val)


def cached(key, fn, ttl=CACHE_TTL):
    """key の値を ttl 秒覚える。覚えが無ければ fn() の答えを覚えて返す"""
    now = time.time()
    val = cache_get(key, ttl, now)
    if val is not MISS:
        return val
    val = fn()
    cache_put(key, val, now)
    return val


def oembed(vid, timeout=8):
    """oEmbed(公開・キー不要)で題とチャンネル名 -> {"title", "channel"}(取れなければ空。接続先は固定・vid は検査済みの動画 ID)"""
    target = OEMBED + urllib.parse.quote(_yturl.watch_url(vid), safe="")
    try:
        with urllib.request.urlopen(urllib.request.Request(target, headers={"Accept": "application/json"}), timeout=timeout) as r:
            d = json.loads(r.read(200000).decode("utf-8", "replace"))
    except (urllib.error.URLError, TimeoutError, OSError, ValueError):
        return {"title": "", "channel": ""}
    return {"title": str(d.get("title") or "")[:120], "channel": str(d.get("author_name") or "")[:100]}
