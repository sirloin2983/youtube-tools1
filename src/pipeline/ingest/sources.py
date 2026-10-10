"""① 取り込み: 入力の判定(YouTube の URL・動画 ID・手元の動画ファイル・ライブの録画)と、yt-dlp に渡す形(役割で組み直す RS3-4。2026-10-10 にスタジオの common.py から移した)。

標準ライブラリと ytt(errors・yturl)だけ。状態を持たない(定数と純粋な関数)。
URL・動画 ID の形(`VID_RE`・`YT_HOSTS`・`MEDIA_EXT`・`YT_API_BASE`・`parse_video_id`・`watch_url`)は RS6 a-1 で `ytt/yturl.py` へ移した(読む側は `from ytt import yturl`。ここでは再公開しない)。
- `ytdlp_out`(yt-dlp の -o)
- `check_media_path`(手元のファイルの検査)・`file_video_id`(手元のファイルの id)
- ライブの録画の検査 `check_live` と形 `LIVE_ID_RE`・`LIVE_RECORDER_RE` は RS6 a-5a で `ytt/yturl.py` へ移した
不正な入力は ApiError 400(code "bad_source")。
"""
import hashlib
import os

from ytt import errors, yturl

def check_media_path(raw):
    """手元の動画・音声ファイルのパスを検査して絶対パスを返す。"""
    s = str(raw or "").strip().strip('"')
    if not s or "\x00" in s or len(s) > 1000 or not os.path.isfile(s) or os.path.splitext(s)[1].lower() not in yturl.MEDIA_EXT:
        raise errors.ApiError("bad_source", "ファイルが見つかりません(動画・音声ファイルのパスを指定してください)", 400)
    return os.path.abspath(s)


def file_video_id(path):
    """file 動画の id: "f" + sha1(絶対パス) の先頭10桁(11文字)。"""
    return "f" + hashlib.sha1(os.path.abspath(path).encode("utf-8", "surrogatepass")).hexdigest()[:10]


def ytdlp_out(folder, name_tmpl):
    """yt-dlp の -o(出力テンプレート)。テンプレートは % 書式なので、フォルダ側の % は %% にする
    (出力先の設定では % を断っているが、既定の exports/ や work/ はこのフォルダの場所しだいで % を含みうる)。
    name_tmpl はこちらで決めた名前(%(ext)s など)で、利用者の文字列は入れない(safe_name で % を除いている)。"""
    return os.path.join(str(folder).replace("%", "%%"), name_tmpl)
