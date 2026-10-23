# -*- coding: utf-8 -*-
"""yt-dlp の版が古いかを確かめる(10-23 取得の冗長化。表は保管庫 plan/人の作業なしの候補-1023.md の 6 番)。

YouTube の仕様の変更・bot 判定には古い yt-dlp が当たりやすい。友人の PC は 1 日 1 回自動で取り替える(friendapp/ytdlp_update)。
ユーザーの PC は winget の yt-dlp なので取り替えず、ホームの「調子」で最新の版と比べて古ければ知らせる(manage/ops/health)。
最新の版は公式の GitHub の releases/latest の名前(1 日 1 回まで。記録 cache に {checkedAt, latest})。見られなければ前の値のまま。
スイッチ: 環境変数 YTT_YTDLP_LATEST=0 で見ない(ネットにつながない)。
"""
import json
import os
import re
import time
import urllib.request

from . import fsio as _fsio, version as _version

SWITCH_ENV = "YTT_YTDLP_LATEST"
API = "https://api.github.com/repos/yt-dlp/yt-dlp/releases/latest"
EVERY = 24 * 3600
TIMEOUT = 20
TAG_RE = re.compile(r"^\d{4}\.\d{2}\.\d{2}(?:\.\d+)?$")


def ver_key(v):
    return tuple(int(x) for x in re.findall(r"\d+", v or ""))


def _http(url, max_bytes):
    req = urllib.request.Request(url, headers={"User-Agent": "ytt/%s" % _version.VERSION})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:   # noqa: S310  (固定の https)
        return r.read(max_bytes)


def latest_tag(http=_http):
    """公式の最新の版の名前(形が違えば ValueError)"""
    tag = (json.loads(http(API, 1 << 20).decode("utf-8")).get("tag_name") or "").strip()
    if not TAG_RE.match(tag):
        raise ValueError("release の名前の形が違います")
    return tag


def cached_latest(cache, now=None, http=_http, env=None):
    """最新の版の名前か ""(見ない・まだ分からない)。cache = 記録のファイル。EVERY 秒に 1 回まで見に行く"""
    env = os.environ if env is None else env
    if env.get(SWITCH_ENV) == "0" or env.get("YTT_DATA_DIR") == "inplace":   # テスト・見本(作業データを切り離した形)はネットにつながない
        return ""
    now = time.time() if now is None else now
    rec = _fsio.read_json_or(cache, {}, kind=dict)
    if rec.get("checkedAt") is not None and now - float(rec["checkedAt"]) < EVERY:   # 記録が無ければ見に行く
        return str(rec.get("latest") or "")
    try:
        rec["latest"] = latest_tag(http)
    except (OSError, ValueError):   # 見られない: 前の値のまま(次は EVERY 後)
        pass
    rec["checkedAt"] = now
    try:
        _fsio.write_json(cache, rec)
    except OSError:
        pass
    return str(rec.get("latest") or "")


def is_old(version, latest):
    """今の版が最新より古いか(どちらかが分からなければ False)"""
    return bool(version and latest and TAG_RE.match(latest) and ver_key(version) < ver_key(latest))
