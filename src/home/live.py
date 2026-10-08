# -*- coding: utf-8 -*-
"""リアルタイム切り抜き(線 D。plan/line-d-live-clipping.md の 0)の入口の側。**既定はオフ**(ホームの設定の節 live.enabled)。
オフの間は何もしない: /live/… は今までどおり 404(handle が False を返し、入口の 404 になる)・録画の部品も起動しない・「調子」にも出さない。
api/ytt/live の status だけはオフでも {enabled: false} を返す(録画元に問い合わせない)。

P3(2026-10-05。計画の 0-8): 録画と再生・マークは**スタジオの中**(③ 確認・書き出し)。別ページ /live/(live.html・live.js・live.css)はやめた。
スタジオのサーバーは録画の部品と話さず、スタジオの**画面が**ここの API を呼ぶ(同じオリジン・入口の合言葉)。

オンのとき:
  GET  /live/・/live/index.html・/live    スタジオ /studio/ へ 302(以前の録画の画面のブックマーク)
  GET  /live/hls.min.js                   hls.js(src/home/vendor/ に同梱 = CSP script-src 'self' のまま。スタジオの画面が ../live/hls.min.js で読む)
  GET  /live/api/info                     録画元の一覧(名前・URL。合言葉は出さない)・録画の置き場所の設定・書き出しの音量(スタジオの設定の引き出しが読む)
  POST /live/api/begin  {url}             配信の状態を yt-dlp で調べ(live_status)、配信中・配信前なら既定の録画元(一覧の先頭)で録画を始める
                                          → {live: true, recorder, recording: {id, url, title, state}, existing}(同じ配信を録画中ならそれ = existing: true)
                                          / 配信中でない・調べられない → {live: false, status: was_live|not_live|post_live|unknown, message?}(画面は今までどおりの解析へ)
  GET|POST /live/r/<録画元>/<残り>        録画元(src/recorder/recorder.py)の /live/<残り> へ中継する(同じオリジンのまま。合言葉は入口が付ける)
                                          例: /live/r/local/<録画>/index.m3u8・…/status・…/stop・…/session_001/seg_000000.ts
                                          POST は <録画>/stop だけ(録画を消す …/delete・終わる quit などは中継しない = 入口の中の処理だけが呼ぶ。P4)
  GET  /live/api/marks?recorder=&recording=   録画1本のマークの正本と書き出し(P2。中身は src/home/live_export.py)
  POST /live/api/marks   {op: add|update|delete, recorder, recording, id?, start?, end?, label?, url?, title?}  マーク(押すたびに fsync。P2 の形)
  GET  /live/api/exports?recorder=&recording=  書き出しのジョブの一覧(状態: 録画待ち・取得中・作り直し中・済み・失敗と理由・取り消し。studio を含む)
  POST /live/api/export  {recorder, recording, title, url, transcribe, studio: {video, mark, n, label, start, end}}
                                          スタジオのマークから書き出す(start・end は録画の最初のセグメントの受信時刻からの秒。入口が録画元の status の
                                          firstPdt で絶対時刻にしてマークの正本へ入れる)。P2 の形 {recorder, recording, markId, transcribe} も残す
  POST /live/api/export/cancel  {id}     取り消し
  POST /live/api/adopt  {recorder, recording, start, end, label?, origin?, after?, streamer?}   サーバー側の「マーク + 書き出し」(線 D の M1。入口 0.39.0)。
                                          画面を閉じていても API だけで書き出しまで通る: スタジオの配信(kind live)を(無ければ)登録して採用のマークを足し
                                          (同じ区間 ±0.5 秒のマークがあれば使い回す)、マークの正本に入れて書き出しのジョブを作る。済んだら入口がスタジオのマークを「書き出し済み」にする。
                                          start・end = 録画の最初のセグメントの受信時刻からの秒(数)か、絶対時刻(UTC の文字列)。origin = manual(既定)・auto・archive
                                          (ジョブ・.clip.json・live_feedback.jsonl に残す。自動の採用は「良い」に数えない)。after が無ければホームの設定 live.auto.after
                                          → {job, video, mark, origin, existing}(existing = 同じマークの書き出しが途中か済みなので、新しく作らなかった)
  POST /live/api/archive  {recorder, recording}   アーカイブで本番版に作り直す(P4。中身は src/home/live_archive.py)。対象の全部を順番に入れる → {ok, queued, message}。
                                          対象が無い・アーカイブがまだ使えない → 409 と文(アーカイブの用意は yt-dlp で確かめる。10 分は前の結果を使う)
  POST /live/api/archive/cancel  {recorder, recording}  作り直しの取り消し → {ok, cancelled}(済んでいない分は速報版のまま)
  GET  /live/api/exports の各ジョブの failure {kind, kindLabel, text}(失敗したときだけ。書き出し・まとめて実行へ渡す・文字起こし・パック。M3。
       文は src/home/live_failures.py の failure_of だけが作り、「調子」の live.failures と同じ)・
  GET  /live/api/exports の各ジョブの archive {state, label, message, progress, offset, residual, at, auto, …}・
       ?recorder=&recording= を付けたときは応答に archiveInfo {ready: true|false|null, checkedAt, message}(その録画のアーカイブの用意)
  録画を自動で消す(P4。中身は src/home/live_cleanup.py。設定 live.autoDelete・既定オン): 見回り(tick)と、本番版への作り直しが1本済んだとき。
       消した録画のジョブには recordingDeleted(スタジオの画面が「録画は消しました」と出す)。録画元の …/delete は入口のこの処理だけが呼ぶ
  ディスクの見張り(線 D の M4。入口 0.40.0): 「調子」の live.disk {state: ok|warn|low, rows, message}(書き出し先・パック・live\\work の空き。
       20 GB 未満で注意・5 GB 未満で新しい書き出し・文字起こしを「空き待ち」。中身は src/home/live_export.py の Exporter.disk)
  配信後の全自動(線 D の M7。入口 0.40.0。設定 live.autoAfterStream 既定オフ・live.afterStreamPerHour 既定 6。中身は src/home/live_archive.py):
       録画が終わってアーカイブを使えるようになったら、アーカイブを解析して上位 N を M1 の採用(origin archive)→ 書き出し → 本番版 → 文字起こし → パック。
       進み具合は GET /live/api/exports?recorder=&recording= の archiveInfo.afterStream {state, label, message, at, n, jobs}・失敗は「調子」の live.failures
  GET  /live/api/peaks?recorder=&recording=&since=  ・ POST /live/api/peaks {op: adopt|dismiss|restore, recorder, recording, id}
                                          配信中の盛り上がりの候補(線 D の L2・M11。設定 live.detect・live.autoAdopt 既定オン(0.46.3 から)。中身と形は src/home/live_detect.py)
  POST api/ytt/live  {op: "status"} → {enabled, recordings: [{recorder, id, title, state, active, seconds, endedAt, url}]}(録画中 + 終わって 10 分以内。
                     全ツールのヘッダーの札が 10 秒ごとに呼ぶので、録画元への問い合わせは短い時間切れで、結果を 3 秒覚える)
                     {op: "stop", recorder, recording} → {ok: true, recording}(launch.py の ytt_api から。合言葉・Origin の検査は ytt_request が済ませる)
  検査は入口の API と同じ(Host・Sec-Fetch-Site。POST は Origin と入口の合言葉 X-YTT-Token も。launch.py の do_GET / do_POST が先に通す)

録画元の一覧(設定 live.recorders。空 = 手元の1つ「この PC」http://127.0.0.1:8730)を通して読む: 2台(P5)のときは一覧に1行足すだけ。
手元の録画元の合言葉は、録画の部品の作業データの token.txt を読む(設定に書かない)。

録画の部品の起動(計画の 0-3 から選んだ形): オンの間、入口が 30 秒ごとに手元の録画元に問い合わせ、動いていなければ入口と切り離して起動する
(別のプロセスグループ・隠れた黒い画面 = 黒い画面を閉じる・Ctrl+C の合図は届かない。落ちても次の見回りで起こし直す)。
入口の終了(「すべて終了」・SIGTERM・SIGBREAK・Ctrl+C = close)では、**録画中でなければ録画の部品も止める**(入口 0.38.1。2026-10-07 ユーザー指示:
残った録画の部品がフォルダを掴んで移動できなかった): POST /live/quit で静かに終わらせ、応答が無い・終わらないときは、この入口が起動したものだけ孫ごと止める
(スタジオの ffmpeg・yt-dlp と同じ taskkill /T /F)。**録画中(quit が 409)なら止めずに残し**、記録と「すべて終了」の画面に知らせる(録画は続き、次の入口が見回りでつなぐ)。
スタートアップのショートカットにしない理由: 既定オフ(オンにするまで自動で起動しない)を、ショートカットを置く・消す手作業なしで守れるため。
ログインしたら録画も上げたいときは、今までどおり入口を裏で起動するショートカット(src\\home\\start_hidden.vbs)を置けば、入口が録画の部品も起こす。
"""
import http.client
import json
import math
import os
import re
import subprocess
import sys
import threading
import time
import urllib.parse

from ytt_core import datadir, layout, tools
import live_export  # noqa: E402  (マークと書き出し。P2)
import live_archive  # noqa: E402  (アーカイブで本番版に作り直す。P4)
import live_cleanup  # noqa: E402  (録画を自動で消す。P4)
import live_failures  # noqa: E402  (失敗の集約。M3・M7)
import live_detect  # noqa: E402  (配信中の盛り上がりの検出と自動の採用。線 D の L2・M11)
import live_requests  # noqa: E402  (友人のライブ配信の依頼と録画の結びつき。docs/spec/friend-intake.md の 2-15)
import live_tx  # noqa: E402  (配信中の候補の文字起こし。線 D の D-11 案 b)
import live_report  # noqa: E402  (配信ごとの結果の記録。線 D の D-12)
import deliver as deliver_mod  # noqa: E402  (自動の切り抜きを友人へ届けるときの依頼 id の形)
from intake import OUT_DIR  # noqa: E402  (見張るフォルダの 出力\ = 友人のアプリの「受け取る」が読む)

CODE_DIR = os.path.dirname(os.path.abspath(__file__))
VENDOR_DIR = os.path.join(CODE_DIR, "vendor")
DEFAULT_FOLDER = r"E:\Video\live-rec"     # src/recorder/rec_core.py の DEFAULT_FOLDER と同じ(2026-10-04 ユーザー決定)
RECORDER_PORT = 8730                      # src/recorder/recorder.py の DEFAULT_PORT と同じ
LOCAL = {"id": "local", "name": "この PC", "url": "http://127.0.0.1:%d" % RECORDER_PORT, "token": ""}
PAGES = {"/live/hls.min.js": ("hls.min.js", VENDOR_DIR)}   # 部品だけ(画面はスタジオ。P3)
TYPES = {".js": "application/javascript; charset=utf-8"}
TO_STUDIO = ("/live", "/live/", "/live/index.html")       # 以前の録画の画面 → スタジオ
STUDIO_PATH = "/studio/"
RELAY_RE = re.compile(r"^/live/r/([a-z][a-z0-9-]{0,15})/([A-Za-z0-9._/-]{1,200})\Z")
RELAY_POST_RE = re.compile(r"^\d{8}-\d{6}(?:-[A-Za-z0-9_-]{1,24})?/stop\Z")   # POST で中継してよい残り(録画の id/stop だけ。P4 で録画の部品に delete を足したため)
PASS_TYPES = ("application/json", "application/vnd.apple.mpegurl", "video/mp2t")   # 中継で返してよい種類
RELAY_TIMEOUT = 15.0
WATCH_SEC = 30.0
SPAWN_GAP = 30.0
VERSION_RE = re.compile(r'^VERSION\s*=\s*"([^"]+)"', re.M)
QUALITIES = ("best", "1080p", "720p")     # src/recorder/rec_core.py の QUALITIES と同じ名前(src/home/prefs.py の LIVE_QUALITIES)
DEFAULT_QUALITY = "1080p"
YT_HOSTS = ("youtube.com", "www.youtube.com", "m.youtube.com", "youtu.be")   # src/recorder/rec_core.py の YT_HOSTS と同じ
URL_MAX = 500
LIVE_STATUSES = ("is_live", "is_upcoming", "was_live", "not_live", "post_live")   # yt-dlp の live_status
PROBE_TIMEOUT = 25.0     # yt-dlp で配信の状態を調べる時間切れ(秒)
CHANNEL_MAX = 100        # チャンネル名の長さ(スタジオの配信の channel と同じ)
STATUS_TIMEOUT = 1.5     # api/ytt/live の status: 録画元への問い合わせの時間切れ(全ツールのヘッダーが 10 秒ごとに呼ぶので短く)
STATUS_CACHE = 3.0       # 同じ結果を返す秒数
RECENT_SEC = 600         # 終わった録画を札に出す秒数(10 分)
STOP_TIMEOUT = 45.0      # 録画元の stop は録画のスレッドの終わりを 30 秒まで待つ
ADOPT_SAME = 0.5         # POST /live/api/adopt: スタジオのマークを使い回す区間の差(秒。スタジオの DUP_TOL と同じ)
QUIT_TIMEOUT = 3.0       # 入口の終了: 録画の部品の quit の応答を待つ秒
QUIT_WAIT = 8.0          # quit を受けた録画の部品が終わるのを待つ秒(過ぎたら、この入口が起動したものだけ孫ごと止める)
KEPT_NOTE = "録画中なので録画の部品は残しました(録画は続きます。部品も終わらせるときは、スタジオで録画を止めてからもう一度「すべて終了」)"


def validate_url(url, allow_local=False):
    """スタジオの URL の欄から録画を始める URL(src/recorder/rec_core.py の validate_url と同じ規則)。YouTube の https だけ。
    allow_local=True(テストの録画元 --source direct)は http(s)://127.0.0.1|localhost も。-> 整えた URL。だめなら LiveError"""
    if not isinstance(url, str):
        raise live_export.LiveError("配信の URL を入れてください")
    url = url.strip()
    if not url or len(url) > URL_MAX or any(ord(c) < 33 for c in url):
        raise live_export.LiveError("配信の URL が正しくありません")
    try:
        u = urllib.parse.urlsplit(url)
        port = u.port
    except ValueError:
        raise live_export.LiveError("配信の URL が正しくありません")
    host = (u.hostname or "").lower()
    if allow_local and u.scheme in ("http", "https") and host in ("127.0.0.1", "localhost") and not u.username:
        return url
    if u.scheme != "https" or host not in YT_HOSTS or u.username or u.password or port not in (None, 443):
        raise live_export.LiveError("YouTube の配信の URL(https://www.youtube.com/watch?v=… など)を入れてください")
    vid = live_export.video_id_of(url)
    return "https://www.youtube.com/watch?v=" + vid if vid else url   # 動画の id が分かる形はそろえる(同じ配信を別の書き方で二重に録らない)


def kill_tree(proc, wait=5.0):
    """子プロセスを孫ごと止める(スタジオの common.hard_kill と同じ形: Windows は taskkill /T /F・それ以外は kill)"""
    if proc is None or proc.poll() is not None:
        return
    if os.name == "nt":
        try:
            subprocess.run(["taskkill", "/T", "/F", "/PID", str(proc.pid)], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                           stderr=subprocess.DEVNULL, timeout=10, creationflags=tools.no_window_flags())
        except (OSError, subprocess.SubprocessError):
            pass
    try:
        proc.kill()
    except OSError:
        pass
    try:
        proc.wait(wait)
    except subprocess.TimeoutExpired:
        pass


def _clean(s, n):
    """yt-dlp の出した値 → 画面へ返す文字(制御文字を落とす・NA は空・長さを切る)"""
    s = "".join(c for c in str(s or "") if ord(c) >= 32 and ord(c) != 127).strip()
    return "" if s == "NA" else s[:n].strip()


def probe_live(url, timeout=PROBE_TIMEOUT):
    """yt-dlp で配信の状態・チャンネル名・題を調べる(ダウンロードしない・シェルを通さない・窓を出さない)。
    -> {"status": LIVE_STATUSES のどれか か "unknown", "title": 題, "channel": チャンネル名(無ければ投稿者。分からなければ ""), "message": 調べられなかった理由}"""
    yd = tools.find_tool("yt-dlp")
    if not yd:
        return {"status": "unknown", "title": "", "channel": "", "message": "yt-dlp が見つからないので、配信中か調べられませんでした"}
    try:   # --ignore-no-formats-error: 配信の前(予約)は形式が無いのでエラーになるが、live_status は出してほしい。
        # 題は最後(題にタブが入っても崩れない)。%(channel,uploader)s = チャンネル名が無ければ投稿者(yt-dlp の書式の「代わり」)
        r = subprocess.run([yd, "--encoding", "utf-8", "--skip-download", "--no-warnings", "--no-playlist", "--ignore-no-formats-error",
                            "--print", "%(live_status)s\t%(channel,uploader)s\t%(title)s", "--", url],
                           stdin=subprocess.DEVNULL, capture_output=True, timeout=timeout, creationflags=tools.no_window_flags())
    except subprocess.TimeoutExpired:
        return {"status": "unknown", "title": "", "channel": "", "message": "配信の状態を %d 秒で調べられませんでした" % int(timeout)}
    except OSError as e:
        return {"status": "unknown", "title": "", "channel": "", "message": "yt-dlp を起動できませんでした: %s" % (e.strerror or e.__class__.__name__)}
    lines = r.stdout.decode("utf-8", "replace").strip().splitlines()
    parts = (lines[-1] if lines else "").split("\t", 2)
    st = parts[0].strip()
    channel = _clean(parts[1], CHANNEL_MAX) if len(parts) > 2 else ""
    title = _clean(parts[-1], live_export.TITLE_MAX) if len(parts) > 1 else ""
    if st in LIVE_STATUSES:
        return {"status": st, "title": title, "channel": channel, "message": ""}
    err = r.stderr.decode("utf-8", "replace")
    if "will begin" in err or "Premieres in" in err:   # 古い yt-dlp は配信の前をエラーで返す
        return {"status": "is_upcoming", "title": title, "channel": channel, "message": ""}
    last = (err.strip().splitlines() or [""])[-1][:160]
    return {"status": "unknown", "title": "", "channel": "", "message": "配信の状態を調べられませんでした" + ("(%s)" % last if last else "")}


def _rec_view(r, channel=None):
    """録画元の録画の要約 → 画面へ返す形。channel = begin で yt-dlp から取ったチャンネル名(begin だけが付ける。分からなければ "")"""
    out = {"id": r.get("id"), "url": r.get("url") or "", "title": r.get("title") or "", "state": r.get("state") or ""}
    if channel is not None:
        out["channel"] = channel
    return out


def _same_stream(a_url, b_url, b_id=""):
    """同じ配信か(URL が同じ・YouTube の動画の id が同じ)"""
    if a_url and a_url == b_url:
        return True
    v = live_export.video_id_of(a_url)
    return bool(v) and v == live_export.video_id_of(b_url or "", b_id or "")


def recorder_data_dir(root):
    """録画の部品の作業データ(token.txt)。src/recorder/recorder.py の data_dir() と同じ規則"""
    return datadir.locate("recorder", legacy_dir=os.path.join(root, layout.RECORDER_DIR, "data"))


def is_local_url(url):
    try:
        return (urllib.parse.urlsplit(url).hostname or "") in ("127.0.0.1", "localhost")
    except ValueError:
        return False


def studio_out_dir(root):
    """スタジオの書き出し先(スタジオの settings.json の outDir。無ければスタジオの作業データの exports。読むだけ。launch.py の _extra_dirs と同じ)"""
    sdir = datadir.resolve("studio", root)
    try:
        with open(os.path.join(sdir, "settings.json"), "r", encoding="utf-8") as f:
            st = json.load(f)
        out = st.get("outDir") if isinstance(st, dict) else None
        if isinstance(out, str) and out and os.path.isabs(out):
            return out
    except (OSError, ValueError):
        pass
    return os.path.join(sdir, "exports")


# スタジオの「書き出しの設定」の既定(src/studio/review.js の DEFAULT_SETTINGS の exportVolume・exportLoudness・lag と同じ値。ツールをまたいで import しない)
STUDIO_EXPORT_VOLUME, STUDIO_EXPORT_LOUDNESS, STUDIO_LAG = 75, -14.0, 0
STUDIO_LOUDNESS_CHOICES = (0, -11, -14, -16, -18)   # 0 = そろえない(音量(%)を使う)
STUDIO_LAGS = (0, 2, 3, 5)


def studio_review(root):
    """スタジオが覚えている画面の設定の節 review(スタジオの作業データの settings-ui.json。読むだけ)。読めなければ {}"""
    try:
        with open(os.path.join(datadir.resolve("studio", root), "settings-ui.json"), "r", encoding="utf-8") as f:
            d = json.load(f)
        r = d.get("review") if isinstance(d, dict) else None
        return r if isinstance(r, dict) else {}
    except (OSError, ValueError):
        return {}


def studio_audio(root):
    """書き出しの音量の設定(スタジオの書き出しの設定と同じ値を使う。sanitizeSettings(src/studio/review.js)と同じ丸め方):
    -> {"volume": 1〜200(%。既定 75), "loudness": -11|-14|-16|-18(LUFS)か None(そろえない)}。loudness があるときは音量(%)は使わない"""
    r = studio_review(root)
    try:
        vol = min(200, max(1, int(round(float(r.get("exportVolume", STUDIO_EXPORT_VOLUME))))))
    except (TypeError, ValueError, OverflowError):
        vol = STUDIO_EXPORT_VOLUME
    try:
        loud = float(r.get("exportLoudness", STUDIO_EXPORT_LOUDNESS))
    except (TypeError, ValueError):
        loud = STUDIO_EXPORT_LOUDNESS
    if loud not in STUDIO_LOUDNESS_CHOICES:
        loud = STUDIO_EXPORT_LOUDNESS
    return {"volume": vol, "loudness": loud or None}


def studio_lag(root):
    """スタジオの「反応の遅れ補正」(秒。なし 0 / 2 / 3 / 5)。録画の画面の I(開始)の最初の選び方に使う"""
    try:
        v = int(float(studio_review(root).get("lag", STUDIO_LAG)))
    except (TypeError, ValueError, OverflowError):
        return STUDIO_LAG
    return v if v in STUDIO_LAGS else STUDIO_LAG


class Live:
    def __init__(self, prefs, root, logs_dir, log=None, python=None, data_dir=None, watch_sec=WATCH_SEC, spawn=True,
                 store_dir=None, out_dir=None, runner=None, audio=None, server=None, archive_opts=None, cleanup_opts=None):
        """prefs: src/home/prefs.py の Prefs。data_dir: 手元の録画の部品の作業データ(テスト用。既定 recorder_data_dir)。
        store_dir: マークと書き出しの記録(既定 入口の作業データの live)。out_dir(): 書き出し先(既定 スタジオの書き出し先)。
        runner(): 文字起こしへ渡す まとめて実行(既定 入口の server.autorun。画面の要求が来たときに覚える)。
        audio(): 書き出しの音量の設定 {"volume", "loudness"}(既定 スタジオの書き出しの設定 = studio_audio)。
        server: 入口のサーバー(取り込んだスタジオの API を呼ぶ = P4 の作り直し。画面の要求が来る前の自動の作り直しでも使えるように、入口が渡す)。
        archive_opts: src/home/live_archive.py の Archiver へ渡す引数(テスト用: studio・probe・fetch・間隔)。
        cleanup_opts: src/home/live_cleanup.py の Cleaner へ渡す引数(テスト用: 24 時間・7 日・見回りの間隔を縮める)"""
        self.prefs, self.root, self.logs_dir = prefs, root, logs_dir
        self.store_dir = store_dir or os.path.join(os.path.dirname(logs_dir), "live")
        self.out_dir = out_dir or (lambda: studio_out_dir(self.root))
        self.audio = audio or (lambda: studio_audio(self.root))
        self.runner = runner or (lambda: getattr(self._server, "autorun", None) if self._server is not None else None)
        self._server = server
        self._exporter = None
        self._archiver = None
        self.archive_opts = dict(archive_opts or {})
        self._cleaner = None
        self.cleanup_opts = dict(cleanup_opts or {})
        self._ex_lock = threading.Lock()
        self.log = log or (lambda m: None)
        self.python = python or sys.executable
        self.data_dir = data_dir or recorder_data_dir(root)
        self.watch_sec, self.spawn_ok = watch_sec, spawn
        self.wake = threading.Event()
        self._halt = threading.Event()
        self._thread = None
        self._last_spawn = 0.0
        self.proc = None
        self.probe = probe_live           # 配信の状態を調べる(begin。テストは偽物に差し替える = 本物の YouTube へ繋がない)
        self.allow_local_urls = False     # begin で手元の URL も通す(テストの録画元 --source direct だけ。画面からは変えられない)
        self._recent = None               # api/ytt/live の status の結果 (時刻, 一覧)
        self._recent_lock = threading.Lock()
        self._adopt_lock = threading.Lock()
        self._stop_lock = threading.Lock()
        self._stopped = None              # 入口の終了で録画の部品を止めた結果(stop_recorder。2 回目からはこれを返す)
        self.detector = live_detect.Detector(self, python=self.python, spawn=spawn)   # 配信中の盛り上がりの検出(L2)と自動の採用(M11)
        self.requests = live_requests.Store(os.path.join(self.store_dir, "requests.json"), log=self.log)   # 友人のライブ配信の依頼と録画の結びつき(2-15)
        self.livetx = live_tx.LiveTx(self, log=self.log, python=self.python)   # 配信中の候補の文字起こし(D-11 案 b。whisper.cpp の GPU)
        self.reporter = live_report.Reporter(self)   # 配信ごとの結果の記録(D-12。live/reports/)
        self.unconfirmed = None            # () -> ホームの「自動の切り抜き: 未確認」の数(入口 launch.py が cases の数を渡す。D-13 の休む判断)
        self._stop_said = set()            # D-13: 6 時間で止められなかった録画(記録に 1 回だけ)

    # --- 設定 ---
    def cfg(self):
        try:
            return self.prefs.get(["live"])["live"]
        except Exception:
            return {"enabled": False, "folder": "", "recorders": [], "quality": DEFAULT_QUALITY}

    def enabled(self):
        return self.cfg().get("enabled") is True

    def recorders(self, cfg=None):
        """録画元の一覧(合言葉つき。画面には出さない)。空 = 手元の1つ"""
        cfg = cfg or self.cfg()
        out = []
        for r in (cfg.get("recorders") or [dict(LOCAL)]):
            r = dict(r)
            if not r.get("token") and is_local_url(r.get("url") or ""):
                r["token"] = self.local_token()
            out.append(r)
        return out

    def find(self, rid):
        return next((r for r in self.recorders() if r.get("id") == rid), None)

    def auto_cfg(self):
        """書き出したあとの自動の流れ(ホームの設定 live.auto。M2)-> {after, cut, engine, model, pad}(prefs が検査済み。読めなければ既定)。pad = 自動・アーカイブの採用の前後の余白(秒。M8)"""
        a = self.cfg().get("auto")
        a = a if isinstance(a, dict) else {}
        pad = a.get("pad")
        return {"after": a.get("after") if a.get("after") in live_export.AFTERS else "check",
                "cut": a.get("cut") or "", "engine": a.get("engine") or "", "model": a.get("model") or "",
                "pad": float(pad) if isinstance(pad, (int, float)) and not isinstance(pad, bool) and 0 <= pad <= 5 else 2.0}

    @property
    def exporter(self):
        """マークと書き出し(src/home/live_export.py)。オンにして初めて使うときに作る(オフの間は作業データに何も作らない)"""
        with self._ex_lock:
            if self._exporter is None:
                self._exporter = live_export.Exporter(self, self.store_dir, lambda: self.out_dir(), runner=lambda: self.runner(), log=self.log, audio=lambda: self.audio(),
                                                      runs_log=os.path.join(self.logs_dir, "autorun-runs.jsonl"))   # 失敗の集約(M3)が読む まとめて実行の記録
            return self._exporter

    @property
    def archiver(self):
        """アーカイブで本番版に作り直す(src/home/live_archive.py。P4)。書き出しのジョブを単位にするので、書き出しと同じく初めて使うときに作る"""
        ex = self.exporter
        with self._ex_lock:
            if self._archiver is None:
                kw = dict({"studio": self.studio_call, "enabled": self.enabled, "auto": lambda: self.cfg().get("autoArchive") is not False,
                           "recording_state": self.recording_state, "python": self.python, "log": self.log,
                           "after": lambda rc, rec: self.cleaner.check(rc, rec),   # 1本終えたら: 全部入れ替わった録画を消す
                           "after_stream": lambda: self.cfg().get("autoAfterStream") is True,   # 配信後の全自動(M7)
                           "per_hour": lambda: self.cfg().get("afterStreamPerHour") or 6,
                           "recordings": self.list_recordings, "adopt": self.adopt, "request": self.requests.get,   # 友人の依頼の録画は afterStream の設定で(2-15)
                           "compare": self.detector.compare}, **self.archive_opts)   # 配信中の候補とアーカイブの候補を比べる(0-10-6)
                self._archiver = live_archive.Archiver(ex, **kw)
            return self._archiver

    @property
    def cleaner(self):
        """録画を自動で消す(src/home/live_cleanup.py。P4。設定 live.autoDelete)"""
        with self._ex_lock:
            if self._cleaner is None:
                kw = dict({"enabled": self.auto_delete, "studio": self.studio_call, "log": self.log,
                           "hold": lambda rc, r: self.archiver.after_stream_hold(rc, r)}, **self.cleanup_opts)   # 配信後の全自動(M7)がまだの録画は消さない
                self._cleaner = live_cleanup.Cleaner(self, **kw)
            return self._cleaner

    def auto_delete(self):
        """録画を自動で消してよいか(リアルタイム切り抜きがオンで、設定 live.autoDelete がオン。既定オン)"""
        cfg = self.cfg()
        return cfg.get("enabled") is True and cfg.get("autoDelete") is True   # 消すのは戻せないので、明示的に true のときだけ(既定の値は src/home/prefs.py の DEFAULTS)

    def studio_call(self, method, path, body=None):
        """取り込んだスタジオの API を呼ぶ(まとめて実行 src/home/autorun.py の ToolClient と同じ形 = 画面と同じ検査・合言葉)。
        -> (HTTP の番号, JSON)。スタジオが動いていない・つながらないときは (None, {"message"})"""
        srv = self._server
        if srv is None or not hasattr(srv, "tool_endpoint"):
            return None, {"message": "ホームのサーバーがまだ準備できていません"}
        import autorun   # 入口のプロセスの中だけ(ここで読むのは、テストで live だけを読むときに要らないため)
        try:
            return autorun.ToolClient(srv.tool_endpoint, srv.token, timeout=30).call("studio", method, path, body)
        except autorun.StepError as e:
            return None, {"message": str(e)}

    def list_recordings(self):
        """録画元ごとの録画の一覧(配信後の全自動 M7 の見回り)-> [{recorder, id, url, title, active, endedAt, firstPdt, lastPdt}](時刻は epoch か None)。
        つながらない録画元は飛ばす"""
        out = []
        for rc in self.recorders():
            for r in live_export.rec_list(self.call, rc) or []:
                out.append({"recorder": rc["id"], "id": r["id"], "url": str(r.get("url") or "")[:URL_MAX], "title": str(r.get("title") or "")[:live_export.TITLE_MAX],
                            "active": r.get("active") is True or r.get("state") in live_cleanup.REC_ACTIVE,
                            "endedAt": live_export.iso_epoch(r.get("endedAt")), "firstPdt": live_export.iso_epoch(r.get("firstPdt")),
                            "lastPdt": live_export.iso_epoch(r.get("lastPdt"))})
        return out

    def recording_state(self, rc_id, rec):
        """録画元での録画の状態 {"active", "endedAt"(epoch か None)}。つながらない・見つからないときは None(P4 の自動: 録画が終わったか)"""
        rc = self.find(rc_id)
        for r in (live_export.rec_list(self.call, rc) or []) if rc is not None else []:
            if r.get("id") == rec:
                return {"active": r.get("active") is True,
                        "endedAt": live_export.iso_epoch(r.get("endedAt")) or live_export.iso_epoch(r.get("lastPdt"))}
        return None

    def local_token(self):
        try:
            with open(os.path.join(self.data_dir, "token.txt"), "r", encoding="ascii") as f:
                return f.read().strip()[:200]
        except (OSError, UnicodeError):
            return ""

    def expected_version(self):
        try:
            with open(os.path.join(self.root, layout.RECORDER_DIR, "recorder.py"), "r", encoding="utf-8") as f:
                m = VERSION_RE.search(f.read())
            return m.group(1) if m else ""
        except (OSError, UnicodeError):
            return ""

    # --- 録画元への要求 ---
    def request(self, rc, method, path, body=None, timeout=RELAY_TIMEOUT):
        """-> (HTTPConnection, HTTPResponse)。呼んだ側が読んで conn.close() する。つながらなければ OSError"""
        u = urllib.parse.urlsplit(rc.get("url") or "")
        if u.scheme != "http" or not u.hostname or not u.port:
            raise OSError("録画元の URL が正しくありません")
        conn = http.client.HTTPConnection(u.hostname, u.port, timeout=timeout)
        headers = {"Host": u.netloc, "Authorization": "Bearer " + (rc.get("token") or ""), "Accept": "*/*"}
        data = None
        if body is not None:
            data = json.dumps(body, ensure_ascii=False).encode("utf-8")
            headers["Content-Type"] = "application/json"
        try:
            conn.request(method, path, body=data, headers=headers)
            return conn, conn.getresponse()
        except (OSError, http.client.HTTPException) as e:
            conn.close()
            raise OSError(str(e) or e.__class__.__name__)

    def call(self, rc, method, path, body=None, timeout=3.0):
        """JSON の API を呼ぶ -> (HTTP の番号, JSON)。つながらなければ (None, None)"""
        try:
            conn, r = self.request(rc, method, path, body, timeout)
        except OSError:
            return None, None
        try:
            raw = r.read(4 * 1024 * 1024)
            try:
                return r.status, json.loads(raw.decode("utf-8", "replace"))
            except ValueError:
                return r.status, None
        except (OSError, http.client.HTTPException):
            return None, None
        finally:
            conn.close()

    def ping(self, rc, timeout=1.5):
        code, d = self.call(rc, "GET", "/api/ping", timeout=timeout)
        return d if code == 200 and isinstance(d, dict) and d.get("app") == "ytt-recorder" else None

    # --- 画面と中継(launch.py の PortalHandler から) ---
    def handle_get(self, h, u):
        """GET /live…。オフなら False(入口の今までどおりの 404 になる)"""
        if not self.enabled():
            return False
        if u.path in TO_STUDIO:   # 以前の録画の画面(P3 でスタジオへ統合した)
            h._send(302, b"", "text/plain; charset=utf-8", {"Location": STUDIO_PATH})
            return True
        if u.path in PAGES:
            name, base = PAGES[u.path]
            try:
                with open(os.path.join(base, name), "rb") as f:
                    body = f.read()
            except OSError:
                h._fail(404, "not_found", "その場所はありません")
                return True
            h._send(200, body, TYPES[os.path.splitext(name)[1]])
            return True
        if u.path == "/live/api/peaks":   # 配信中の候補(L2。src/home/live_detect.py)
            self._server = h.server
            try:
                h._json(200, self.detector.api_get(urllib.parse.parse_qs(u.query)))
            except live_export.LiveError as e:
                h._fail(e.code, "bad_request" if e.code == 400 else "not_found", str(e))
            return True
        if u.path in ("/live/api/marks", "/live/api/exports"):
            self._server = h.server
            q = urllib.parse.parse_qs(u.query)
            try:
                if u.path == "/live/api/exports":   # ?recorder=&recording= で録画1本に絞る(空 = 全部)
                    rc, rec = (q.get("recorder") or [""])[0][:40], (q.get("recording") or [""])[0][:60]
                    out = {"jobs": self.exporter.snapshot(rc or None, rec or None)}
                    if rc and rec and live_export.ID_RE.match(rc) and live_export.REC_RE.match(rec):   # その録画のアーカイブの用意(P4)
                        out["archiveInfo"] = self.archiver.info_view(rc, rec, out["jobs"])   # afterStream の進み具合はこの jobs から(M7。0.41.0)
                    return h._json(200, out) or True
                rc, rec = (q.get("recorder") or [""])[0], (q.get("recording") or [""])[0]
                d = self.exporter.marks.load(rc, rec)
                h._json(200, {"marks": d["marks"], "title": d.get("title") or "", "url": d.get("url") or "",
                              "exports": self.exporter.snapshot(rc, rec)})
            except live_export.LiveError as e:
                h._fail(e.code, "bad_request" if e.code == 400 else "not_found" if e.code == 404 else "error", str(e))
            return True
        if u.path == "/live/api/info":
            cfg = self.cfg()
            h._json(200, {"enabled": True, "folder": cfg.get("folder") or "", "defaultFolder": DEFAULT_FOLDER,
                          "audio": self.audio(), "lag": studio_lag(self.root),   # 書き出しの音量(スタジオと同じ)・反応の遅れ補正の最初の選び方(スタジオの値)
                          "recorders": [{"id": r["id"], "name": r["name"], "url": r["url"], "local": is_local_url(r["url"])} for r in self.recorders(cfg)]})
            return True
        m = RELAY_RE.match(u.path)
        if m and ".." not in m.group(2) and "//" not in m.group(2):
            self._relay(h, "GET", m.group(1), m.group(2), u.query)
            return True
        h._fail(404, "not_found", "その場所はありません")
        return True

    def handle_post(self, h, u, body):
        """POST /live…(入口の合言葉・Origin の検査と本文の読み取りは launch.py が済ませてある)。オフなら False"""
        if not self.enabled():
            return False
        if u.path.startswith("/live/api/"):
            self._server = h.server
            self._api_post(h, u.path, body)
            return True
        m = RELAY_RE.match(u.path)
        if m and RELAY_POST_RE.match(m.group(2)):   # 画面から中継する書き込みは「停止」だけ(消す delete・終わる quit などは入口の中の処理だけが呼ぶ)
            self._relay(h, "POST", m.group(1), m.group(2), "", body)
            return True
        h._fail(404, "not_found", "その操作はありません")
        return True

    def _api_post(self, h, path, body):
        """録画を始める(P3)・マークと書き出し(P2・P3)"""
        try:
            if path == "/live/api/begin":
                return h._json(200, self.begin(body.get("url")))
            ex = self.exporter
            if path == "/live/api/marks":
                rc, rec = body.get("recorder"), body.get("recording")
                if self.find(rc) is None:
                    raise live_export.LiveError("その録画元はありません", 404)
                m, marks = ex.marks.apply(rc, rec, body)
                return h._json(200, {"mark": m, "marks": marks})
            if path == "/live/api/export":
                if "studio" in body:   # スタジオのマークから(P3)
                    return h._json(200, {"job": self.export_studio(body)})
                auto = self.auto_cfg()
                after, streamer = live_export.check_after(body, auto["after"]), live_export.check_streamer(body.get("streamer"))
                return h._json(200, {"job": ex.add(body.get("recorder"), body.get("recording"), body.get("markId"), after != "none",
                                                   after=after, streamer=streamer, origin=live_export.check_origin(body.get("origin")), auto=auto)})
            if path == "/live/api/adopt":   # サーバー側の「マーク + 書き出し」(M1)
                return h._json(200, self.adopt(body))
            if path == "/live/api/peaks":   # 配信中の候補の採用・見送り・戻す(L2。src/home/live_detect.py)
                return h._json(200, self.detector.api_post(body))
            if path == "/live/api/export/cancel":
                return h._json(200, {"job": ex.cancel(body.get("id"))})
            if path in ("/live/api/archive", "/live/api/archive/cancel"):   # P4: アーカイブで本番版に作り直す・取り消す
                rc_id, rec = body.get("recorder"), body.get("recording")
                self._ids(rc_id, rec)
                if path == "/live/api/archive":
                    return h._json(200, self.archiver.request(rc_id, rec))
                return h._json(200, {"ok": True, "cancelled": self.archiver.cancel(rc_id, rec)})
        except live_export.LiveError as e:
            return h._fail(e.code, {400: "bad_request", 404: "not_found", 409: "conflict", 502: "recorder_down"}.get(e.code, "error"), str(e))
        h._fail(404, "not_found", "その操作はありません")

    # --- P3: スタジオから ---
    def _ids(self, rc_id, rec):
        """録画元と録画の id を確かめる -> 録画元(合言葉つき)。だめなら LiveError"""
        if not isinstance(rc_id, str) or not live_export.ID_RE.match(rc_id) or not isinstance(rec, str) or not live_export.REC_RE.match(rec):
            raise live_export.LiveError("録画元か録画の指定が正しくありません")
        rc = self.find(rc_id)
        if rc is None:
            raise live_export.LiveError("その録画元はありません", 404)
        return rc

    def _down(self, rc):
        return live_export.LiveError("録画元「%s」につながりません。録画の部品が起動するまで少し待ってください(%s)" % (rc.get("name"), rc.get("url")), 502)

    def _find_active(self, rc, url):
        """録画元で同じ配信を録画中の録画(要約)か None"""
        return next((r for r in live_export.rec_list(self.call, rc) or [] if r.get("active") and _same_stream(url, r.get("url"), r.get("id"))), None)

    def begin(self, url):
        """スタジオの URL の欄(POST /live/api/begin)。配信中・配信前なら録画を始める(同じ配信を録画中ならそれを返す)。-> 返す JSON"""
        url = validate_url(url, self.allow_local_urls)
        try:
            info = self.probe(url) or {}
        except Exception as e:   # 調べる部品の不具合でも、画面は今までどおりの解析へ進める
            self.log("リアルタイム切り抜き: 配信の状態を調べられませんでした %r" % (e,))
            info = {}
        status = info.get("status") if info.get("status") in LIVE_STATUSES else "unknown"
        if status not in ("is_live", "is_upcoming"):
            out = {"live": False, "status": status}
            if info.get("message"):
                out["message"] = str(info["message"])[:300]
            return out
        rcs = self.recorders()
        if not rcs:
            raise live_export.LiveError("録画元がありません", 409)
        rc = rcs[0]   # 既定の録画元 = 一覧の先頭(2台(P5)で二重録画するときは、ここで全部に頼む)
        ch = _clean(info.get("channel"), CHANNEL_MAX) if isinstance(info.get("channel"), str) else ""   # 録画中だった(existing)ときも付ける
        found = self._find_active(rc, url)
        if found:
            return {"live": True, "recorder": rc["id"], "recording": _rec_view(found, ch), "existing": True}
        q = self.cfg().get("quality")
        title = info.get("title") if isinstance(info.get("title"), str) else ""
        code, d = self.call(rc, "POST", "/live/start", {"url": url, "quality": q if q in QUALITIES else DEFAULT_QUALITY, "title": title[:live_export.TITLE_MAX]},
                            timeout=15.0)
        if code == 200 and isinstance(d, dict) and isinstance(d.get("recording"), dict):
            self._recent = None   # ヘッダーの札にすぐ出す
            self.log("リアルタイム切り抜き: 録画を始めました %s(%s)" % (d["recording"].get("id"), url))
            return {"live": True, "recorder": rc["id"], "recording": _rec_view(d["recording"], ch), "existing": False}
        if code == 409:   # 「その配信はもう録画しています」(ほかは streamlink が無い・置き場所が無いなど)
            found = self._find_active(rc, url)
            if found:
                return {"live": True, "recorder": rc["id"], "recording": _rec_view(found, ch), "existing": True}
        if code is None:
            raise self._down(rc)
        msg = (d or {}).get("message") if isinstance(d, dict) else ""
        raise live_export.LiveError("録画を始められませんでした: %s" % (msg or "HTTP %s" % code), code if code in (400, 409) else 502)

    def begin_request(self, url, ctx):
        """友人のライブ配信の依頼(src/home/intake.py の _handle_live_request。docs/spec/friend-intake.md の 2-15): 録画を始めて(begin)、その録画を依頼に結びつける。
        ctx = {rid, deliverDir, url, title, streamer, speakers, videoTracks, cut, memo, settings}。-> {"recorder", "recording", "existing"}。だめなら LiveError"""
        if not self.enabled():
            raise live_export.LiveError("リアルタイム切り抜きがオフです", 409)
        busy = self.active_request(url)   # D-13: 友人のライブ配信の依頼は同時に 1 本まで(同じ配信なら今の録画に結びつける = existing)
        if busy is not None:
            raise live_export.LiveError("友人のライブ配信の依頼は同時に 1 本までです(「%s」を録画中。終わってからもう一度送ってください)"
                                        % (busy.get("title") or busy.get("url") or busy["id"])[:80], 409)
        out = self.begin(url)
        if not out.get("live"):
            raise live_export.LiveError("配信中・配信前の配信ではありません(%s)" % (out.get("status") or "unknown"), 409)
        rc, rec = out["recorder"], out["recording"]["id"]
        item = self.requests.put(rc, rec, ctx)
        self.log("リアルタイム切り抜き: 友人の依頼 %s を録画 %s に結びつけました(%s)" % (item["rid"], rec, live_requests.settings_label(item["settings"])))
        self.detector.wake()   # 検出がオフでも、この録画はすぐ測り始める
        return {"recorder": rc, "recording": rec, "existing": bool(out.get("existing"))}

    def active_request(self, url):
        """D-13: 友人のライブ配信の依頼に結びついた録画で、まだ録画中のもの(url と同じ配信は除く)-> 録画元の一覧の 1 行か None"""
        items = self.requests.all()
        if not items:
            return None
        for r in self.list_recordings():
            if r.get("active") and live_requests.key_of(r["recorder"], r["id"]) in items and not _same_stream(url, r.get("url") or "", r["id"]):
                return r
        return None

    def stop_long_requests(self):
        """D-13: 友人のライブ配信の依頼に結びついた録画が、依頼から live_requests.MAX_SEC(6 時間)を超えて録画中なら止める(録画元の stop。
        録画の部品が録画を閉じる = 配信後の処理は今までどおり)。-> 止めた録画の id の一覧"""
        items = self.requests.all()
        if not items or not self.enabled():
            return []
        now, out = time.time(), []
        active = {(r["recorder"], r["id"]) for r in self.list_recordings() if r.get("active")}
        for key, item in items.items():
            rc_id, _sep, rec = key.partition("/")
            if (rc_id, rec) not in active or now - float(item.get("createdAt") or now) < live_requests.MAX_SEC:
                continue
            rc = self.find(rc_id)
            if rc is None:
                continue
            code, d = self.call(rc, "POST", "/live/%s/stop" % rec, {}, timeout=STOP_TIMEOUT)
            if code == 200:
                self._recent = None
                self._stop_said.discard(rec)
                self.log("リアルタイム切り抜き: 友人の依頼 %s の録画 %s は %d 時間を超えたので止めました(1 依頼の上限)" % (item.get("rid"), rec, int(live_requests.MAX_SEC // 3600)))
                out.append(rec)
            elif rec not in self._stop_said:
                self._stop_said.add(rec)
                self.note("リアルタイム切り抜き: 友人の依頼の録画 %s を %d 時間で止められませんでした(HTTP %s: %s)" % (
                    rec, int(live_requests.MAX_SEC // 3600), code, ((d or {}).get("message") if isinstance(d, dict) else "") or ""))
        return out

    def _request_for(self, rc_id, rec, origin, after, streamer):
        """録画が友人のライブ配信の依頼に結びついていれば (依頼, after=auto, 配信者) を返す(2-15: 採用した切り抜きは全部 文字起こし → パック → 届ける)。
        配信後のアーカイブからの追加(origin archive)は依頼の afterStream が真のときだけ。結びついていなければ (None, after, streamer) のまま"""
        req = self.requests.get(rc_id, rec)
        if req is None:
            return self._auto_deliver_for(origin, after, streamer)
        if origin == "archive" and req["settings"].get("afterStream") is not True:
            return None, after, streamer
        return req, "auto", streamer or req.get("streamer") or ""

    def deliver_dir(self):
        """友人へ届ける所(依頼の受付の Dropbox のフォルダの 出力\)。決まっていなければ None"""
        try:
            folder = (self.prefs.get(["intake"])["intake"] or {}).get("folder") or ""
        except Exception:   # noqa: BLE001
            folder = ""
        return os.path.join(folder, OUT_DIR) if folder else None

    def _auto_deliver_for(self, origin, after, streamer):
        """自分の配信の自動の切り抜き(配信中の自動採用 auto・配信後の追加 archive)を確認なしで友人へ届ける(設定 live.autoDeliver。10-08 ユーザー決定 = 10-06 の
        「全自動で届けるスイッチは作らない」を変えた)。人のマーク(manual)は今までどおり案件の [採用(友人へ届ける)] で。届ける先(依頼の受付のフォルダ)が無ければ届けない。
        -> (届ける依頼の形 {rid, deliverDir, autoDeliver: True} か None, after, streamer)"""
        if origin == "manual" or self.cfg().get("autoDeliver") is not True:
            return None, after, streamer
        out = self.deliver_dir()
        if not out:
            return None, after, streamer
        return {"rid": deliver_mod.request_id(), "deliverDir": out, "autoDeliver": True}, "auto", streamer

    def _rec_status(self, rc, rc_id, rec):
        """録画元の録画の状態(書き出しの基準 firstPdt・URL・題)。-> (状態の JSON, 最初のセグメントの受信時刻 epoch)。だめなら LiveError"""
        code, d = self.call(rc, "GET", "/live/%s/status?since=999999999" % rec, timeout=5.0)   # since: セグメントの一覧は要らない
        if code is None:
            raise self._down(rc)
        if code == 404:
            if any(j.get("recordingDeleted") for j in self.exporter.snapshot(rc_id, rec)):   # 本番版に入れ替えて、録画を自動で消した(P4)
                raise live_export.LiveError("録画は消しました(本番版に入れ替え済み)。区間を変えた切り抜きは、録画が無いので作れません", 404)
            raise live_export.LiveError("その録画はありません(録画元で消されたか、置き場所を変えたかもしれません)", 404)
        if code != 200 or not isinstance(d, dict):
            raise live_export.LiveError("録画元から思わぬ応答がありました(HTTP %s)" % code, 502)
        first = live_export.iso_epoch(d.get("firstPdt"))   # 秒の 0 = 最初のセグメントの受信時刻(live_export.Exporter._base と同じ基準)
        if first is None:
            raise live_export.LiveError("録画がまだ始まっていません(録画のデータが最初に届いてから書き出せます)", 409)
        return d, first

    def export_studio(self, body):
        """POST /live/api/export の studio の形(P3)。-> ジョブ"""
        studio = live_export.check_studio(body.get("studio"))
        auto = self.auto_cfg()
        after, streamer = live_export.check_after(body, auto["after"]), live_export.check_streamer(body.get("streamer"))   # 録画元に聞く前に検査する
        origin = live_export.check_origin(body.get("origin"))
        rc_id, rec = body.get("recorder"), body.get("recording")
        rc = self._ids(rc_id, rec)
        req, after, streamer = self._request_for(rc_id, rec, origin, after, streamer)   # 友人の依頼の録画なら、人のマークも届ける(2-15)
        _d, first = self._rec_status(rc, rc_id, rec)
        return self.exporter.add_studio(rc_id, rec, studio, first, body.get("transcribe") is not False,
                                        url=body.get("url") if isinstance(body.get("url"), str) else None,
                                        title=body.get("title") if isinstance(body.get("title"), str) else None,
                                        after=after, streamer=streamer, origin=origin, auto=auto, request=req)

    # --- M1: サーバー側の「マーク + 書き出し」(画面を閉じていても。自動の採用 M7・M11 もここを通る) ---
    def _adopt_secs(self, body, first):
        """POST /live/api/adopt の start・end -> 録画の頭からの秒 (a, b)。数 = 秒・文字列 = 絶対時刻(UTC)"""
        out = []
        for k in ("start", "end"):
            v = body.get(k)
            if isinstance(v, str):
                e = live_export.iso_epoch(v)
                if e is None:
                    raise live_export.LiveError("%s の時刻が正しくありません(UTC の …Z か、録画の頭からの秒)" % k)
                v = e - first
            if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v):
                raise live_export.LiveError("%s は録画の頭からの秒(数)か、絶対時刻(UTC の文字列)で指定してください" % k)
            out.append(round(float(v), 3))
        a, b = out
        if not 0 <= a or b - a < 0.5:
            raise live_export.LiveError("区間は 0 ≤ 開始 で、終了は開始より 0.5 秒以上あとにしてください")
        if b - a > live_export.MAX_MARK_SEC:
            raise live_export.LiveError("1つのマークは %d 分までです" % (live_export.MAX_MARK_SEC // 60))
        return a, b

    @staticmethod
    def _pad_secs(a, b, pad, st, first):
        """自動・アーカイブの採用の区間 (a, b) を前後 pad 秒だけ広げる(M8。plan/improvements.md の M8)。
        0 より前と、録れている範囲(録画元の状態の lastPdt)の外へは広げない(終わりが録れていなければ後ろは足さない)。1 つのマークの上限も守る"""
        pad = float(pad)
        a2, b2 = max(0.0, a - pad), b + pad
        last = live_export.iso_epoch(st.get("lastPdt")) if isinstance(st, dict) else None
        if last is not None and first is not None:
            b2 = min(b2, max(b, last - first))
        b2 = min(b2, a2 + live_export.MAX_MARK_SEC)
        return round(a2, 3), round(b2, 3)

    def _studio_ok(self, method, path, body=None):
        """取り込んだスタジオの API -> JSON。だめなら LiveError(スタジオが動いていない = 502)"""
        code, d = self.studio_call(method, path, body)
        if code is None:
            raise live_export.LiveError("切り抜きスタジオにつながりません: %s" % ((d or {}).get("message") or ""), 502)
        if code != 200 or not isinstance(d, dict):
            raise live_export.LiveError("切り抜きスタジオが断りました: %s" % ((d or {}).get("message") or "HTTP %s" % code), code if code in (400, 404, 409) else 502)
        return d

    def _studio_adopt_mark(self, rc_id, rec, st, a, b, label):
        """スタジオの配信(kind live。id = 録画の id)を(無ければ)登録し、採用のマーク [a, b] を足す(同じ区間 ±0.5 秒があれば使い回し、候補・不採用なら採用に)。
        画面と同じ PUT /api/video(baseRev つき。画面の保存とぶつかったら読み直して 3 回まで)。-> (配信の id, マーク, 番号 n)"""
        v = self._studio_ok("POST", "/api/videos/open", {"kind": "live", "recorder": rc_id, "recording": rec, "url": st.get("url") or "",
                                                         "title": (st.get("title") or "")[:live_export.TITLE_MAX], "channel": ""}).get("video") or {}
        vid = v.get("id")
        if not isinstance(vid, str) or not vid:
            raise live_export.LiveError("切り抜きスタジオに録画を登録できませんでした", 502)
        for _try in range(3):
            v = self._studio_ok("GET", "/api/video?id=" + urllib.parse.quote(vid)).get("video") or {}
            marks = [m for m in v.get("marks") or [] if isinstance(m, dict)]
            hit = next((m for m in marks if abs((m.get("start") or 0) - a) <= ADOPT_SAME and abs((m.get("end") or 0) - b) <= ADOPT_SAME), None)
            if hit is not None and hit.get("status") in ("adopted", "exported"):
                mark = hit
                break
            if hit is not None:
                new = [dict(m, status="adopted") if m.get("id") == hit.get("id") else m for m in marks]
            else:
                new = marks + [{"start": a, "end": b, "label": label, "status": "adopted"}]
            code, d = self.studio_call("PUT", "/api/video", {"id": vid, "marks": new, "baseRev": v.get("rev")})
            if code == 409:   # 画面の保存・解析とぶつかった: 読み直してもう一度
                continue
            if code != 200 or not isinstance(d, dict):
                raise live_export.LiveError("切り抜きスタジオにマークを足せませんでした: %s" % ((d or {}).get("message") or "HTTP %s" % code), 502)
            v = d.get("video") or {}
            old_ids = {m.get("id") for m in marks}
            got = [m for m in v.get("marks") or [] if isinstance(m, dict)]
            mark = next((m for m in got if m.get("id") == (hit or {}).get("id")), None) if hit is not None else \
                next((m for m in got if m.get("id") not in old_ids and abs((m.get("start") or 0) - a) <= ADOPT_SAME), None)
            if mark is None:
                raise live_export.LiveError("切り抜きスタジオに足したマークが見つかりません", 502)
            marks = got
            break
        else:
            raise live_export.LiveError("切り抜きスタジオの配信が続けて書き換えられているので、マークを足せませんでした(少し待ってもう一度)", 409)
        order = sorted(marks, key=lambda m: (m.get("start") or 0, m.get("end") or 0))
        n = next((i + 1 for i, m in enumerate(order) if m.get("id") == mark.get("id")), 0)
        return vid, mark, n

    def adopt(self, body, hold=None):
        """POST /live/api/adopt(M1)。-> {job, video, mark, origin, existing}。
        hold: "archive" = 書き出したあと、本番版に入れ替えてから まとめて実行へ渡す(配信後の全自動 M7 が入口の中から渡す。API の本文からは渡せない)"""
        origin = live_export.check_origin(body.get("origin"))
        auto = self.auto_cfg()
        after, streamer = live_export.check_after(body, auto["after"]), live_export.check_streamer(body.get("streamer"))
        label = live_export._text(body.get("label"), live_export.LABEL_MAX)
        text = live_export._text(body.get("text"), live_tx.TEXT_MAX)   # 配信中の文字起こし(D-11 案 b)の文字(採用の記録に残す = C2 の材料。任意)
        score = body.get("score") if isinstance(body.get("score"), (int, float)) and not isinstance(body.get("score"), bool) else None   # 候補の点数(配信中の検出・アーカイブの解析。任意)
        rc_id, rec = body.get("recorder"), body.get("recording")
        rc = self._ids(rc_id, rec)
        req, after, streamer = self._request_for(rc_id, rec, origin, after, streamer)   # 友人の依頼の録画(2-15): after は auto・余白は依頼の設定
        pad = req["settings"]["pad"] if req and isinstance(req.get("settings"), dict) else auto["pad"]
        st, first = self._rec_status(rc, rc_id, rec)
        a, b = self._adopt_secs(body, first)
        if origin != "manual" and pad > 0:   # M8: 自動・アーカイブの採用は前後に余白を足す(人が決めた区間はそのまま)
            a, b = self._pad_secs(a, b, pad, st, first)
        ex = self.exporter
        with self._adopt_lock:   # 同じ区間を続けて頼まれても、スタジオのマーク・ジョブを二重に作らない
            vid, mark, n = self._studio_adopt_mark(rc_id, rec, st, a, b, label)
            mid = live_export.studio_mark_id(mark["id"])
            prev = [j for j in ex.snapshot(rc_id, rec) if j.get("markId") == mid and (j.get("state") in live_export.ACTIVE or j.get("state") == "done")]
            if mark.get("status") == "exported" or (prev and prev[0].get("state") in live_export.ACTIVE):   # 書き出しの途中か済み: 新しく作らない(同じ切り抜きを二重に作らない)
                return {"job": prev[0] if prev else None, "video": vid, "mark": mark["id"], "origin": (prev[0].get("origin") if prev else None) or "manual",
                        "existing": True}
            studio = {"video": vid, "mark": mark["id"], "n": n, "label": mark.get("label") or label,
                      "start": float(mark.get("start", a)), "end": float(mark.get("end", b))}   # スタジオが丸めた区間(画面の書き出しと同じ値で突き合わせる)
            job = ex.add_studio(rc_id, rec, studio, first, after != "none", url=st.get("url") if isinstance(st.get("url"), str) else None,
                                title=st.get("title") if isinstance(st.get("title"), str) else None, after=after, streamer=streamer, origin=origin, auto=auto,
                                hold=hold if hold in live_export.HOLDS else None, score=score, request=req)
        ex.feedback({"event": "adopt", "origin": origin, "human": origin == "manual", "verdict": "good" if origin == "manual" else None,
                     "recorder": rc_id, "recording": rec, "markId": mid, "jobId": job.get("id"), "studio": {"video": vid, "mark": mark["id"]},
                     "start": round(studio["start"], 3), "end": round(studio["end"], 3), "label": studio["label"], **({"text": text} if text else {})})
        self.log("リアルタイム切り抜き: %s のマークを採用して書き出しを頼みました(%s %.1f〜%.1f 秒)" % ({"manual": "人", "auto": "自動", "archive": "アーカイブ"}[origin], rec,
                                                                                         studio["start"], studio["end"]))
        return {"job": job, "video": vid, "mark": mark["id"], "origin": origin, "existing": False}

    # --- 画面の共通の API api/ytt/live(launch.py の PortalServer.ytt_api から。全ツールのヘッダーの札) ---
    def ytt(self, body):
        """-> (HTTP の番号, JSON)"""
        op = body.get("op")
        if op == "status":
            if not self.enabled():   # オフ: 録画元に問い合わせない
                return 200, {"enabled": False}
            return 200, {"enabled": True, "recordings": self.recent()}
        if op == "stop":
            if not self.enabled():
                return 409, {"error": "off", "message": "リアルタイム切り抜きはオフです(ホームの「詳しく」の「試験中の機能」)"}
            try:
                rc = self._ids(body.get("recorder"), body.get("recording"))
            except live_export.LiveError as e:
                return e.code, {"error": "bad_request" if e.code == 400 else "not_found", "message": str(e)}
            code, d = self.call(rc, "POST", "/live/%s/stop" % body["recording"], {}, timeout=STOP_TIMEOUT)
            self._recent = None
            if code == 200 and isinstance(d, dict):
                self.log("リアルタイム切り抜き: 録画を止めました %s" % body["recording"])
                return 200, {"ok": True, "recording": _rec_view(d.get("recording") or {})}
            if code is None:
                return 502, {"error": "recorder_down", "message": str(self._down(rc))}
            msg = (d or {}).get("message") if isinstance(d, dict) else ""
            return (404 if code == 404 else 502), {"error": "not_found" if code == 404 else "recorder_bad", "message": msg or "止められませんでした(HTTP %s)" % code}
        return 400, {"error": "bad_request", "message": "op は status か stop です"}

    def recent(self):
        """録画中 + 終わって RECENT_SEC 秒以内の録画(録画元ごと)。STATUS_CACHE 秒は前の結果を返す(ロックの中で問い合わせる = 同時に来ても1回)"""
        with self._recent_lock:
            if self._recent is not None and time.time() - self._recent[0] < STATUS_CACHE:
                return self._recent[1]
            out, now = [], time.time()
            for rc in self.recorders():
                for r in live_export.rec_list(self.call, rc, STATUS_TIMEOUT) or []:
                    ended = live_export.iso_epoch(r.get("endedAt"))
                    if not r.get("active") and (ended is None or now - ended > RECENT_SEC):
                        continue
                    secs = r.get("seconds")
                    a, b = live_export.iso_epoch(r.get("firstPdt")), live_export.iso_epoch(r.get("lastPdt"))
                    if a is not None and b is not None and isinstance(secs, (int, float)) and not isinstance(secs, bool):
                        secs = round(max(secs, b - a), 3)   # スタジオの録画の長さと同じ(受信時刻の幅。繋ぎ直しの欠けの間も時間は進む)
                    out.append({"recorder": rc["id"], "id": r["id"], "title": str(r.get("title") or "")[:live_export.TITLE_MAX],
                                "state": str(r.get("state") or ""), "active": r.get("active") is True,
                                "seconds": secs if isinstance(secs, (int, float)) and not isinstance(secs, bool) else 0,
                                "endedAt": r.get("endedAt") if ended is not None else None, "url": str(r.get("url") or "")[:URL_MAX]})
            self._recent = (time.time(), out)
            return out

    def _relay(self, h, method, rid, rest, query="", body=None):
        rc = self.find(rid)
        if rc is None:
            return h._fail(404, "unknown_recorder", "その録画元はありません")
        path = "/live/" + rest + ("?" + query[:200] if query else "")
        try:
            conn, r = self.request(rc, method, path, body)
        except OSError:
            return h._fail(502, "recorder_down", "録画元「%s」につながりません。録画の部品が起動するまで少し待ってください(%s)" % (rc["name"], rc["url"]))
        try:
            ctype = (r.getheader("Content-Type") or "").split(";")[0].strip().lower()
            if ctype not in PASS_TYPES:
                return h._fail(502, "recorder_bad", "録画元から思わぬ応答がありました")
            length = r.getheader("Content-Length")
            h.send_response(r.status)
            h.send_header("Content-Type", r.getheader("Content-Type"))
            if length and length.isdigit():
                h.send_header("Content-Length", length)
            else:
                h.close_connection = True
            h.send_header("Cache-Control", r.getheader("Cache-Control") or "no-store")
            h.send_header("X-Content-Type-Options", "nosniff")
            h.end_headers()
            if h.command == "HEAD":
                return
            while True:
                chunk = r.read(256 * 1024)
                if not chunk:
                    break
                h.wfile.write(chunk)
        except (OSError, http.client.HTTPException):
            h.close_connection = True   # 途中で切れた(再生を止めた・録画元が落ちた)
        finally:
            conn.close()

    # --- 設定を変えたとき ---
    def on_patch(self, old, new):
        """設定の節 live を変えた。オンにした・置き場所を変えた → 見回りをすぐ。オンにしたときは画面を待たせない(起動は裏で)"""
        self.wake.set()

    def note(self, msg):
        """同じ知らせを見回りのたびに記録しない"""
        if msg != getattr(self, "_last_note", None):
            self._last_note = msg
            self.log(msg)

    # --- 見回り(手元の録画の部品を起こす) ---
    def start(self):
        if self._thread is None:
            self._thread = threading.Thread(target=self._watch, daemon=True, name="live-watch")
            self._thread.start()

    def close(self):
        """入口の終了: 見回りを止め、録画中でなければ録画の部品も止める(stop_recorder。録画中なら残す = 録画は続く。計画の 0-3 と 2026-10-07 ユーザー指示)"""
        self._halt.set()
        self.wake.set()
        self.detector.stop()   # 盛り上がりの検出のワーカー(状態は 1 分ごとに保存済み。次の起動で続きから)
        self.livetx.close()    # 配信中の文字起こしの子プロセス(途中の候補は次の見回りでやり直す)
        if self._archiver is not None:   # 本番版への作り直しの途中なら止める(順番待ちに戻り、次の起動で続ける)
            self._archiver.close()
        if self._exporter is not None:   # 書き出しの途中なら ffmpeg を止める(ジョブは「録画待ち」に戻り、次の起動でやり直す)
            self._exporter.close()
        try:
            self.stop_recorder()
        except Exception as e:   # 後始末の途中の不具合で入口の終了を止めない
            self.log("録画の部品を止める途中でエラー: %r" % (e,))

    # --- 入口の終了で録画の部品も止める(入口 0.38.1) ---
    def _own_proc(self):
        """この入口が起動して、まだ動いている録画の部品のプロセス(無ければ None)"""
        p = self.proc
        return p if p is not None and p.poll() is None else None

    def _stop_target(self):
        """入口の終了で止める手元の録画元。リアルタイム切り抜きがオンか、この入口が起動した録画の部品が動いているときだけ(オフで人が別に起動したものは触らない)"""
        if self._own_proc() is None and not self.enabled():
            return None
        return next((r for r in self.recorders() if is_local_url(r.get("url") or "")), None)

    def local_recording(self, timeout=1.5):
        """入口の終了で止める手元の録画元が録画中か: True / False(録画していない・止める相手が無い)/ None(つながらない)。「すべて終了」の応答の知らせに使う"""
        rc = self._stop_target()
        if rc is None:
            return False
        code, d = self.call(rc, "GET", "/live/list", timeout=timeout)
        if code != 200 or not isinstance(d, dict):
            return None
        return bool(d.get("active")) or any(isinstance(r, dict) and r.get("active") is True for r in d.get("recordings") or [])

    def stop_recorder(self):
        """入口の終了で手元の録画の部品を止める。-> "none"(止める相手が無い・動いていない)|"quit"(静かに終わった)|
        "killed"(応答が無い・終わらないので孫ごと止めた)|"kept"(録画中なので残した)|"failed"(断られた。残した)。2 回目からは前の結果"""
        with self._stop_lock:
            if self._stopped is None:
                self._stopped = self._stop_recorder()
            return self._stopped

    def _stop_recorder(self):
        rc, own = self._stop_target(), self._own_proc()
        if rc is None:
            return "none"
        code, d = self.call(rc, "POST", "/live/quit", {}, timeout=QUIT_TIMEOUT)
        if code == 409:   # 録画中(録画の部品が断る)= 止めない
            self.log("録画の部品: " + KEPT_NOTE)
            return "kept"
        if code == 200:
            end = time.time() + QUIT_WAIT
            while time.time() < end:   # この入口が起動したものはプロセスの終わり、それ以外は待ち受けの終わりを待つ
                if (own.poll() is not None) if own is not None else not self.ping(rc, 0.5):
                    self.log("録画の部品を終わらせました(ホームの終了)")
                    return "quit"
                time.sleep(0.2)
            if own is not None:
                kill_tree(own)
                self.log("録画の部品が %d 秒で終わらないので、止めました(ホームの終了)" % int(QUIT_WAIT))
                return "killed"
            self.log("録画の部品に終わるよう伝えました(終わるのを待ちきれませんでした)")
            return "quit"
        if code is None:   # 応答が無い: この入口が起動したものなら孫ごと止める。それ以外は動いていない
            if own is not None:
                kill_tree(own)
                self.log("録画の部品が応答しないので、止めました(ホームの終了)")
                return "killed"
            return "none"
        msg = (d or {}).get("message") if isinstance(d, dict) else ""
        self.log("録画の部品を止められませんでした(HTTP %s%s)。録画の部品は残しています" % (code, ": " + msg if msg else ""))
        return "failed"

    def _watch(self):
        while not self._halt.is_set():
            try:
                self.tick()
            except Exception as e:   # 見回りは止めない
                self.log("録画の部品の見回りでエラー: %r" % (e,))
            self.wake.wait(self.watch_sec)
            self.wake.clear()

    def tick(self):
        """オンなら: 手元の録画元が動いていなければ起動する・古い版なら(録画中でなければ)起動し直す・置き場所の設定が違えば伝える。
        -> "off"|"running"|"spawned"|"waiting"|"failed\""""
        try:   # 盛り上がりの検出(L2・M11): オンならワーカーを見張り・自動の採用、オフなら止める
            self.detector.tick()
        except Exception as e:
            self.note("リアルタイム切り抜き: 盛り上がりの検出の見回りでエラー: %r" % (e,))
        try:
            self.livetx.tick()   # 配信中の候補の文字起こし(D-11 案 b): 確定した候補を列に入れる(準備が無ければ何もしない)
        except Exception as e:
            self.note("リアルタイム切り抜き: 配信中の文字起こしの見回りでエラー: %r" % (e,))
        try:
            self.requests.prune()   # 友人の依頼の古い結びつきを消す(2-15。消すものがあるときだけ書く)
        except Exception as e:
            self.note("リアルタイム切り抜き: 友人の依頼の結びつきの片付けでエラー: %r" % (e,))
        try:
            self.stop_long_requests()   # D-13: 友人の依頼の録画は 1 依頼 6 時間まで
        except Exception as e:
            self.note("リアルタイム切り抜き: 友人の依頼の録画の上限の見回りでエラー: %r" % (e,))
        try:
            self.reporter.tick()   # D-12: 配信ごとの結果の記録(録画中は 1 分ごと・終わったら最後に 1 回)
        except Exception as e:
            self.note("リアルタイム切り抜き: 配信の記録の見回りでエラー: %r" % (e,))
        cfg = self.cfg()
        if cfg.get("enabled") is not True:
            return "off"
        if os.path.isfile(os.path.join(self.store_dir, "exports.json")) or cfg.get("autoAfterStream") is True or self.requests.all():   # 友人の依頼の録画(2-15)は M7 がオフでも
            if self.exporter.pending():   # 入口を起動し直した: 途中の書き出しを続ける(空き待ちの受け渡しも。M4)
                self.exporter.start()
            self.archiver.start()   # 本番版への作り直し(P4): 途中のものを続ける・自動の見回り(設定 live.autoArchive)・配信後の全自動(M7)
        if self.auto_delete():   # 録画を自動で消す(P4。設定 live.autoDelete。中で間隔を見る = 10 分ごと)
            try:
                self.cleaner.tick()
            except Exception as e:   # 消す見回りの不具合でも、録画の部品の見回りは続ける
                self.note("リアルタイム切り抜き: 録画を消す見回りでエラー: %r" % (e,))
        local = next((r for r in self.recorders(cfg) if is_local_url(r.get("url") or "")), None)
        if local is None:
            return "off"
        info = self.ping(local)
        if info:
            exp = self.expected_version()
            if exp and info.get("version") != exp:   # コードを直した(版が上がった): 録画中でなければ終わってもらって、新しい版で起こし直す
                code, _d = self.call(local, "POST", "/live/quit", {})
                if code == 200:
                    self.note("録画の部品が古い版(v%s)なので、v%s で起動し直します" % (info.get("version"), exp))
                    end = time.time() + 15
                    while time.time() < end and self.ping(local, 0.5):
                        time.sleep(0.3)
                    self._last_spawn = 0.0
                    return "spawned" if self.spawn_ok and self.spawn(local, cfg.get("folder") or "") else "waiting"
                self.note("録画の部品が古い版(v%s)ですが、録画中なので録画が終わってから起動し直します" % info.get("version"))
            folder = cfg.get("folder") or ""
            if folder:
                code, d = self.call(local, "GET", "/live/config")
                if code == 200 and isinstance(d, dict) and os.path.normcase(d.get("folder") or "") != os.path.normcase(os.path.normpath(folder)):
                    code, d = self.call(local, "POST", "/live/config", {"folder": folder})
                    self.note("録画の置き場所を %s にしました" % folder if code == 200 else
                              "録画の置き場所を変えられませんでした: %s" % ((d or {}).get("message") or code))
            return "running"
        if not self.spawn_ok:
            return "waiting"
        if time.time() - self._last_spawn < SPAWN_GAP:   # 起動したばかり(待ち受けの準備中)
            return "waiting"
        return "spawned" if self.spawn(local, cfg.get("folder") or "") else "failed"

    def spawn(self, rc, folder=""):
        """手元の録画の部品を、入口と切り離して起動する(入口と同じ Python = start.bat と同じ選び方で選ばれたもの)"""
        if self._halt.is_set():   # 入口の終了の途中(止めたあとに見回りが起こし直さない)
            return False
        self._last_spawn = time.time()
        script = os.path.join(self.root, layout.RECORDER_DIR, "recorder.py")
        if not os.path.isfile(script):
            self.log("録画の部品が見つかりません: %s" % script)
            return False
        port = urllib.parse.urlsplit(rc["url"]).port or RECORDER_PORT
        cmd = [self.python, "-u", script, "--port", str(port), "--quiet", "--data-dir", self.data_dir]
        if folder:
            cmd += ["--folder", folder]
        env = dict(os.environ)
        env.setdefault("PYTHONIOENCODING", "utf-8:backslashreplace")
        env["PYTHONUNBUFFERED"] = "1"
        flags = 0
        if os.name == "nt":   # 別のプロセスグループ(入口への Ctrl+Break が届かない)・隠れた黒い画面(入口の黒い画面を閉じても止まらない)
            flags = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW | getattr(subprocess, "ABOVE_NORMAL_PRIORITY_CLASS", 0)
        os.makedirs(self.logs_dir, exist_ok=True)
        try:
            with open(os.path.join(self.logs_dir, "recorder.log"), "ab") as logf:
                logf.write(("\n==== %s ホームから起動 ====\n" % time.strftime("%Y-%m-%d %H:%M:%S")).encode("utf-8"))
                logf.flush()
                kw = dict(cwd=os.path.dirname(script), env=env, stdin=subprocess.DEVNULL, stdout=logf, stderr=subprocess.STDOUT)
                try:   # 入口がジョブ(閉じると子も消える)の中で動いていても、録画の部品は外へ出す。出られないジョブならそのまま
                    self.proc = subprocess.Popen(cmd, creationflags=flags | getattr(subprocess, "CREATE_BREAKAWAY_FROM_JOB", 0), **kw)
                except OSError:
                    self.proc = subprocess.Popen(cmd, creationflags=flags, **kw)
        except OSError as e:
            self.log("録画の部品を起動できませんでした: %s" % (e.strerror or e.__class__.__name__))
            return False
        self.log("録画の部品を起動しました(%s。置き場所 %s)" % (rc["url"], folder or "前回の設定か既定 " + DEFAULT_FOLDER))
        return True

    # --- 「調子」 ---
    def health(self):
        """オフなら None(「調子」に出さない)。オンなら録画元ごとの状態と空き容量"""
        cfg = self.cfg()
        if cfg.get("enabled") is not True:
            return None
        expected = self.expected_version()
        out = []
        for rc in self.recorders(cfg):
            row = {"id": rc["id"], "name": rc["name"], "url": rc["url"], "ok": False, "version": "", "expected": expected if is_local_url(rc["url"]) else "",
                   "folder": None, "folderOk": None, "folderMessage": "", "freeBytes": None, "totalBytes": None, "streamlink": None,
                   "active": 0, "recordings": [], "message": ""}
            code, d = self.call(rc, "GET", "/live/list", timeout=2.0)
            if code == 200 and isinstance(d, dict):
                row.update(ok=True, version=str(d.get("version") or ""), folder=d.get("folder"), folderOk=d.get("folderOk"),
                           folderMessage=d.get("folderMessage") or "", freeBytes=d.get("freeBytes"), totalBytes=d.get("totalBytes"),
                           streamlink=d.get("streamlink"), active=d.get("active") or 0,
                           recordings=[{k: x.get(k) for k in ("id", "title", "state", "message", "segments", "lastPdt")}
                                       for x in (d.get("recordings") or []) if x.get("active")][:5])
            elif code is None:
                row["message"] = "つながりません(録画の部品が起動していません)"
            else:
                row["message"] = ((d or {}).get("message") if isinstance(d, dict) else "") or "応答が正しくありません(HTTP %s)" % code
            out.append(row)
        failures = []
        if os.path.isfile(os.path.join(self.store_dir, "exports.json")):   # 失敗の集約(M3。文は LIVE の帯と同じ = live_failures.failure_of)
            try:
                failures = self.exporter.failures()
            except Exception as e:
                self.note("リアルタイム切り抜き: 失敗の一覧を作れませんでした: %r" % (e,))
        if self._archiver is not None:   # 配信後の全自動(M7)が止まった録画(文は live_failures.after_stream_failure)
            try:
                failures = sorted(failures + self._archiver.after_failures(), key=lambda x: x.get("at") or "", reverse=True)[:live_failures.MAX_LIST]
            except Exception as e:
                self.note("リアルタイム切り抜き: 配信後の自動の失敗を読めませんでした: %r" % (e,))
        try:   # 盛り上がりの検出(L2・M11)の失敗
            failures = sorted(failures + self.detector.failures(), key=lambda x: x.get("at") or "", reverse=True)[:live_failures.MAX_LIST]
        except Exception as e:
            self.note("リアルタイム切り抜き: 盛り上がりの検出の失敗を読めませんでした: %r" % (e,))
        if self._cleaner is not None:   # D-14: 本番版に置き換わらないまま残っている録画の知らせ(文は live_failures.keep_failure)
            try:
                failures = sorted(failures + self._cleaner.kept_failures(), key=lambda x: x.get("at") or "", reverse=True)[:live_failures.MAX_LIST]
            except Exception as e:
                self.note("リアルタイム切り抜き: 残っている録画の一覧を作れませんでした: %r" % (e,))
        try:   # 書き出し先・パック・live\work の空き(M4)
            disk = self.exporter.disk()
        except Exception as e:
            self.note("リアルタイム切り抜き: 空き容量を調べられませんでした: %r" % (e,))
            disk = None
        try:   # 配信中の検出(L2。worker.json・peaks.json を読む)
            detect = self.detector.health()
        except Exception as e:
            self.note("リアルタイム切り抜き: 検出の状態を読めませんでした: %r" % (e,))
            detect = {"running": False, "error": "状態を読めませんでした", "restarts": self.detector.restarts}
        return {"recorders": out, "failures": failures, "disk": disk, "detect": detect}

