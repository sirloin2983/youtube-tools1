"""YouTube の URL・動画 ID の形(語彙。標準ライブラリだけ・状態を持たない)。役割で組み直す RS6 a-1(2026-10-10)に pipeline/ingest/sources から移した。

③ 人・④ データが ① を読まずに済むよう ytt に置く。読む側は `from ytt import yturl` の形で、別名で再公開しない。
- 形: `VID_RE`(YouTube の動画 ID)・`YT_HOSTS`・`MEDIA_EXT`(動画・音声の拡張子)・`YT_API_BASE`(YouTube Data API)
- 関数: `parse_video_id`(URL か 11 文字の ID → 動画 ID)・`watch_url`(動画 ID → 動画のページ)
- ライブの録画(RS6 a-5a に sources から): `check_live`(録画 1 本の記述の検査)・`LIVE_ID_RE`・`LIVE_RECORDER_RE`・`LIVE_NO_ANALYZE`
"""
import re
import urllib.parse

from . import errors

VID_RE = re.compile(r"^[\w-]{11}\Z", re.ASCII)   # ASCII のみ・末尾の改行も不可
YT_API_BASE = "https://www.googleapis.com/youtube/v3/"   # YouTube Data API(① 探す・② のコメント欄)
MEDIA_EXT = {".mp4", ".mkv", ".webm", ".mov", ".m4a", ".mp3", ".wav", ".flac", ".ogg", ".opus", ".aac", ".ts", ".flv"}
YT_HOSTS = ("youtube.com", "www.youtube.com", "m.youtube.com", "music.youtube.com", "youtu.be")


def parse_video_id(text):
    """YouTube の URL(watch / youtu.be / live / shorts / embed)または11文字のID → 動画ID。"""
    raw = str(text or "")
    if VID_RE.match(raw.strip(" \t")):   # 素のID(改行などは不可)
        return raw.strip(" \t")
    t = raw.strip()
    try:
        u = urllib.parse.urlsplit(t if "://" in t else "https://" + t)
    except ValueError:
        return None
    host = (u.hostname or "").lower()
    if host in ("youtu.be",):
        cand = u.path.strip("/").split("/")[0]
    elif host in ("youtube.com", "www.youtube.com", "m.youtube.com", "music.youtube.com"):
        parts = [x for x in u.path.split("/") if x]
        if u.path.startswith("/watch"):
            cand = (urllib.parse.parse_qs(u.query).get("v") or [""])[0]
        elif len(parts) >= 2 and parts[0] in ("live", "shorts", "embed", "v"):
            cand = parts[1]
        else:
            return None
    else:
        return None
    return cand if VID_RE.match(cand) else None


def watch_url(vid):
    """YouTube の動画のページ(yt-dlp・oEmbed に渡す。vid は検査済みの動画 ID)"""
    return "https://www.youtube.com/watch?v=" + vid


LIVE_NO_ANALYZE = "ライブの録画は解析できません(配信が終わってから、アーカイブのURLを入れてください)"   # RS6 a-5a に pipeline/analyze/analyze から

# ライブの録画(kind "live")。録画の部品(pipeline/ingest/recorder.py)の録画 id の形。YouTube の 11 文字・file の "f…" とは重ならない
LIVE_ID_RE = re.compile(r"^\d{8}-\d{6}(?:-[A-Za-z0-9_-]{1,24})?\Z", re.ASCII)
LIVE_RECORDER_RE = re.compile(r"^[a-z][a-z0-9-]{0,15}\Z", re.ASCII)


def check_live(o):
    """録画1本の記述({recorder, recording, url}) → {recorder, recording, url, videoId}。不正は ApiError 400。
    url は YouTube の https だけ(チャンネルの /live など動画の ID が取れない URL も可。そのとき videoId は "")。"""
    bad = lambda m: errors.ApiError("bad_source", m, 400)
    if not isinstance(o, dict):
        raise bad("入力が正しくありません")
    rec, rid, url = o.get("recorder"), o.get("recording"), o.get("url")
    if not isinstance(rec, str) or not LIVE_RECORDER_RE.match(rec):
        raise bad("録画元(recorder)の形が正しくありません")
    if not isinstance(rid, str) or not LIVE_ID_RE.match(rid):
        raise bad("録画の ID(recording)の形が正しくありません")
    if not isinstance(url, str) or not url or len(url) > 300 or any(ord(c) < 32 or ord(c) == 127 for c in url):
        raise bad("配信の URL が正しくありません")
    try:
        u = urllib.parse.urlsplit(url.strip())
        host = (u.hostname or "").lower()
    except ValueError:
        raise bad("配信の URL が正しくありません")
    if u.scheme != "https" or host not in YT_HOSTS:
        raise bad("配信の URL は YouTube の https の URL だけです")
    return {"recorder": rec, "recording": rid, "url": url.strip(), "videoId": parse_video_id(url.strip()) or ""}
