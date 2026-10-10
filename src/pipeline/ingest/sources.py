"""① 取り込み: 入力の判定(YouTube の URL・動画 ID・手元の動画ファイル・ライブの録画)と、yt-dlp に渡す形(役割で組み直す RS3-4。2026-10-10 にスタジオの common.py から移した)。

標準ライブラリと ytt.errors だけ。状態を持たない(定数と純粋な関数)ので、読む側は `from pipeline.ingest.sources import VID_RE` の形で読んでよい。
- `parse_video_id`(URL か 11 文字の ID → 動画 ID)・`watch_url`(動画 ID → 動画のページ)・`ytdlp_out`(yt-dlp の -o)
- `check_live`(録画の部品で録っている配信の記述の検査)・`check_media_path`(手元のファイルの検査)・`file_video_id`(手元のファイルの id)
- 形: `VID_RE`(YouTube の動画 ID)・`LIVE_ID_RE`(録画の id)・`LIVE_RECORDER_RE`(録画元の名前)・`YT_HOSTS`・`MEDIA_EXT`・`YT_API_BASE`
不正な入力は ApiError 400(code "bad_source")。
"""
import hashlib
import os
import re
import urllib.parse

from ytt import errors

VID_RE = re.compile(r"^[\w-]{11}\Z", re.ASCII)   # ASCII のみ・末尾の改行も不可
YT_API_BASE = "https://www.googleapis.com/youtube/v3/"   # YouTube Data API(① 探す・② のコメント欄)
MEDIA_EXT = {".mp4", ".mkv", ".webm", ".mov", ".m4a", ".mp3", ".wav", ".flac", ".ogg", ".opus", ".aac", ".ts", ".flv"}
# ライブの録画(kind "live")。録画の部品(pipeline/ingest/recorder.py)の録画 id の形。YouTube の 11 文字・file の "f…" とは重ならない
LIVE_ID_RE = re.compile(r"^\d{8}-\d{6}(?:-[A-Za-z0-9_-]{1,24})?\Z", re.ASCII)
LIVE_RECORDER_RE = re.compile(r"^[a-z][a-z0-9-]{0,15}\Z", re.ASCII)
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


def check_media_path(raw):
    """手元の動画・音声ファイルのパスを検査して絶対パスを返す。"""
    s = str(raw or "").strip().strip('"')
    if not s or "\x00" in s or len(s) > 1000 or not os.path.isfile(s) or os.path.splitext(s)[1].lower() not in MEDIA_EXT:
        raise errors.ApiError("bad_source", "ファイルが見つかりません(動画・音声ファイルのパスを指定してください)", 400)
    return os.path.abspath(s)


def file_video_id(path):
    """file 動画の id: "f" + sha1(絶対パス) の先頭10桁(11文字)。"""
    return "f" + hashlib.sha1(os.path.abspath(path).encode("utf-8", "surrogatepass")).hexdigest()[:10]


def watch_url(vid):
    """YouTube の動画のページ(yt-dlp・oEmbed に渡す。vid は検査済みの動画 ID)"""
    return "https://www.youtube.com/watch?v=" + vid


def ytdlp_out(folder, name_tmpl):
    """yt-dlp の -o(出力テンプレート)。テンプレートは % 書式なので、フォルダ側の % は %% にする
    (出力先の設定では % を断っているが、既定の exports/ や work/ はこのフォルダの場所しだいで % を含みうる)。
    name_tmpl はこちらで決めた名前(%(ext)s など)で、利用者の文字列は入れない(safe_name で % を除いている)。"""
    return os.path.join(str(folder).replace("%", "%%"), name_tmpl)
