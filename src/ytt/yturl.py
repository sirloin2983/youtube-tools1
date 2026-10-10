"""YouTube の URL・動画 ID の形(語彙。標準ライブラリだけ・状態を持たない)。役割で組み直す RS6 a-1(2026-10-10)に pipeline/ingest/sources から移した。

③ 人・④ データが ① を読まずに済むよう ytt に置く。読む側は `from ytt import yturl` の形で、別名で再公開しない。
- 形: `VID_RE`(YouTube の動画 ID)・`YT_HOSTS`・`MEDIA_EXT`(動画・音声の拡張子)・`YT_API_BASE`(YouTube Data API)
- 関数: `parse_video_id`(URL か 11 文字の ID → 動画 ID)・`watch_url`(動画 ID → 動画のページ)
"""
import re
import urllib.parse

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
