"""録画元との約束(線 D。2026-10-09 見直し T8): 録画元・録画・セグメントの id の形、時刻の書き方(UTC の "…Z")、YouTube の動画の id の読み方。
録画の部品(src/pipeline/ingest/rec_core.py。入口と別のプロセス)・入口の書き出し(src/flow/live_export.py)・配信中の検出のワーカー
(src/pipeline/analyze/live_excite_worker.py。別のプロセス)が同じ物を読む(以前は 3 か所に写しがあり、片方だけ直す事故をテストで見張っていた)。
標準ライブラリだけ(ワーカーは numpy を読まない決まり)。
"""
import datetime
import re
import time
import urllib.parse

RECORDER_ID_RE = re.compile(r"^[a-z][a-z0-9-]{0,15}\Z")                 # 録画元の id(入口の設定 live.recorders の id)
REC_ID_RE = re.compile(r"^\d{8}-\d{6}(?:-[A-Za-z0-9_-]{1,24})?\Z")      # 録画の id(日時 + 動画の id か乱数。rec_core.new_rec_id が作る)
SESSION_RE = re.compile(r"^session_(\d{3,6})\Z")                        # 録画の中のセッション(繋ぎ直すたびに増える)のフォルダ
SEG_RE = re.compile(r"^seg_\d{6,9}\.ts\Z")                               # セグメントのファイル
SEG_URI_RE = re.compile(r"^session_\d{3,6}/seg_\d{6,9}\.ts\Z")          # /segments が返す uri(<セッション>/<セグメント>)
YT_VID_RE = re.compile(r"^[A-Za-z0-9_-]{11}\Z")                          # YouTube の動画の id
_FORMATS = ("%Y-%m-%dT%H:%M:%S.%fZ", "%Y-%m-%dT%H:%M:%SZ")


def utc_text(d):
    """datetime → UTC の "2026-10-04T06:30:12.345Z"(ミリ秒まで。録画の記録・API の時刻はすべてこの形)"""
    return d.astimezone(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def epoch_iso(e):
    """epoch 秒 → UTC の "…Z"(ミリ秒まで。切り捨て)"""
    return utc_text(datetime.datetime.fromtimestamp(e, datetime.timezone.utc))


def now_iso():
    return epoch_iso(time.time())


def iso_epoch(s):
    """UTC の時刻の文字列("…Z"・ミリ秒あり/なし・+00:00。前後の空白は可)→ epoch 秒。読めなければ None"""
    if not isinstance(s, str) or len(s) > 40:
        return None
    t = s.strip().replace("+00:00", "Z")
    for fmt in _FORMATS:
        try:
            return datetime.datetime.strptime(t, fmt).replace(tzinfo=datetime.timezone.utc).timestamp()
        except ValueError:
            continue
    return None


def video_id_of(url, rec_id=""):
    """YouTube の動画の id(11 文字)。URL の ?v=・youtu.be/<id>・/live/<id>(最後の部分)から。
    URL に無ければ録画の id の後ろ(録画の部品の new_rec_id が URL から取った物)。分からなければ "" """
    try:
        u = urllib.parse.urlsplit(url or "")
        q = urllib.parse.parse_qs(u.query)
        v = (q.get("v") or [""])[0]
        if not v and (u.hostname == "youtu.be" or u.path.startswith("/live/")):
            v = u.path.rstrip("/").rsplit("/", 1)[-1]
    except ValueError:
        v = ""
    if YT_VID_RE.match(v or ""):
        return v
    tail = (rec_id or "").split("-", 2)[2:] if rec_id else []
    return tail[0] if tail and YT_VID_RE.match(tail[0]) else ""
