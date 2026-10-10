# -*- coding: utf-8 -*-
"""アーカイブで本番版に作り直す(線 D の P4。plan/line-d-live-clipping.md の 0-9)の入口の側の中身。API は src/home/live.py(設定 live.enabled がオンのときだけ)。

単位は入口の書き出しのジョブ(src/flow/live_export.py の Exporter。live/exports.json)。ジョブに archive を足して残す(入口を起動し直しても続く):
  archive {state: wait|probe|align|fetch|verify|done|error|cancelled, label(日本語), message(失敗のときは理由), progress(0〜1),
           offset(マークの絶対時刻 − 配信の開始時刻 の見当から、照合で求めたアーカイブの秒までの差), residual(本番版と速報版の音のずれ。秒),
           archiveStart・archiveEnd(アーカイブの秒), at(済んだ時刻), auto(自動で始めた), aligned(照合が済んだ = ほかのマークの見当に使える),
           built(入れ替え待ちの本番版。使用中で入れ替えられなかったとき), keep(退避した速報版), retryAt}
  対象 = 録画1本の、マークごとの最新のジョブで、done(速報版と入れ替える)か error + needsArchive(欠けで書き出せなかった。新しく作る)。

流れ(1本ずつ順に):
  1. probe  … yt-dlp で live_status(was_live = 用意できた / post_live・is_live = まだ)・配信の開始時刻 release_timestamp を取る
              (timestamp は配信の終わりごろの時刻で数時間ずれるので使わない。release_timestamp が無ければ照合できない)。
              録画1本ごとの結果は live/archive.json(画面の archiveInfo {ready, checkedAt, message})
  2. align  … 配信の音を丸ごと1回だけ yt-dlp で取り(-f ba = スタジオの書き出し bv*+ba と同じ音。2.5 時間の配信でも数秒)、入口の作業用
              live\\work\\audio-<videoId>\\ に置く(同じ配信のジョブで使い回す。その配信のジョブが無くなったら消す)。
              見当 = マークの絶対時刻 − 開始時刻。その前後の窓(最初は ±300 秒、確かさが低ければ ±900 秒で1回だけやり直す。2 本目からは前のずれの ±20 秒。
              だめなら広げる)を丸ごとの音から ffmpeg で切り(10 秒手前まで入力側の -ss、残りはデコードして切る = サンプル単位で正確。入力側だけだと AAC で 13ms ずれた)、速報版の音(頭の1秒ほどを除いた最大 60 秒)と相互相関
              (8kHz・モノラル。numpy を使うので別プロセス src/pipeline/ingest/live_align_worker.py = 入口のプロセスでは numpy を import しない。配信全体は相関にかけない = 窓だけ)
              2 本目からの見当は、同じ録画のほか、同じ配信(videoId)の別の録画の照合も使う(同じ配信の 2 本の録画の差は 1 秒ほど = ±20 秒に収まる)。
              欠けのマーク(速報版が無い)は、同じ録画の照合できたマークのずれのうち、前にある・時刻が近いものを使う(1 本も無ければできない)。
              2026-10-05 に本物の配信で確かめて変えた: yt-dlp の区間取得(--download-sections)は遅く(±600 秒で 570 秒)、m4a と opus で頭が 35ms ずれて
              本番版の作り直しが毎回やり直しになっていた / 合わない区間で ratio 1.58 が出た(MIN_RATIO 3.0)/ yt-dlp の一時的な 403 は 30 秒あけて 2 回までやり直す
  3. fetch  … スタジオの POST /studio/api/live/section {videoId, start, end, path, volume, loudness, maxHeight, precision}(YouTube の書き出しの中身を使う。
              二重に書かない)→ GET api/export?id= で進み具合。path は書き出し先の中の、まだ無い .mp4(<配信のフォルダ>\\作業用\\本番版の作りかけ\\<ジョブ>\\)
  4. verify … 30fps・長さ(区間 ±0.2 秒)・速報版との音のずれが 1 コマ(FRAME_TOL = 0.034 秒)以内。超えたら1回だけずれを足して作り直す。それでもだめなら入れ替えない
  5. 入れ替え … 速報版を <配信のフォルダ>\\作業用\\速報版\\<元の名前>(重なれば _2…)へ移し、本番版を元の名前へ(fsio.replace_retry)。
              速報版は消さない。使用中で動かせなければ archive.state を wait に戻し(本番版は built に残す)、RETRY_SEC 後の見回りでやり直す
              → .clip.json の source.live.archive {videoId, start, end, offset, residual, at}。欠けのマークは新しい名前で書き出して job.state を done・path を入れる
              (スタジオの画面の今の突き合わせが「書き出し済み」にする。本番版の札は archive.state done を見て画面が付ける)

重い処理の順番(ytt.jobs.SLOTS)を入口の側では取らない: 作り直し(いちばん重い)はスタジオの書き出しが自分で SLOTS を取る。入口がその間 SLOT を
持って待つと、上限 1(YTT_MAX_HEAVY_JOBS=1)では互いに待って止まり、上限 2 でも1つをむだに塞ぐ。入口の側の仕事は yt-dlp の取得(通信)・
ffmpeg で 8kHz の音にする(数秒)・照合(子プロセスで 1〜2 秒)だけで軽い。その代わり、自動で始めるのは SLOTS に実行中・順番待ちが無く、
書き出しのジョブも無いときだけにする。

自動(設定 live.autoArchive。既定オン): 録画が終わって FIRST_DELAY(30 分)後から INTERVAL(1 時間)ごとに用意を確かめ、GIVE_UP(7 日)でやめる。
録画が終わったかは録画元の /live/list(つながらなければジョブの時刻)。自動は、まだ一度も試していないマークだけ(失敗・取り消しは人が押して始める)。

できないもの: アーカイブが残らない・メンバー限定・非公開・配信者がアーカイブを切り貼りして音が合わない区間 → 速報版のまま(理由を archive.message に出す)。

空き容量(線 D の M4): 書き出し先・live\\work の空きが 5 GB 未満(src/flow/live_export.py の DISK_LOW)なら、作り直しを始めずに待ちに戻す(Later)。
本番版を待っていた受け渡し(M7。ジョブの handoffWait "archive")は、入れ替えたら(作り直せなければ速報版のまま)Exporter.release_hold で まとめて実行へ渡す。

配信後の全自動(線 D の M7。入口 0.40.0。設定 live.autoAfterStream 既定オフ・live.afterStreamPerHour 既定 6): 人が触らずにパックまで。
録画ごとの状態は archive.json の afterStream {state, label, message, at, vid, t0, offset, first, last, n, qid, jobs, picked, skipped, title}。
  wait     … 録画元の一覧(GET /live/list)で終わった録画のうち、終わって FIRST_DELAY(30 分)たち・AFTER_MAX_AGE(2 日)以内・YouTube の動画が分かるもの。
             アーカイブの用意(P4 と同じ確かめ方・同じ覚え方)を待つ
  (時刻)   … 録画の受信時刻とアーカイブの秒のずれ(offset。P4 と同じ向き)を決める: 同じ録画(無ければ同じ配信)の照合済みのマークがあればそのずれ、
             無ければ録画の真ん中あたりの REF_SEC(60 秒)の音を録画元から取って、アーカイブの丸ごとの音と照合する(P4 と同じ窓・同じしきい値・同じ子プロセス)
  analyze  … アーカイブ(kind youtube・videoId)をスタジオの今の解析にかける(POST /studio/api/queue/add。設定はスタジオで保存した解析の設定、
             候補の数 count は N の 2 倍まで増やす)。スタジオで解析済みならそれを使う。進み具合は GET /studio/api/queue
  (採用)   … 候補(自動のマーク・判定前)を点数の高い順に、録画の範囲に入る(半分以上入るものは録画の範囲に切り詰める)・人のマークと重ならない上位 N を選び
             (N = 録画の長さ(時間)× 1 時間あたりの数。1〜30)、M1 の採用(src/home/live.py の Live.adopt。origin archive・after auto = 文字起こし → パック・
             hold archive)を 1 本ずつ呼ぶ = スタジオの録画の配信に採用のマーク・live_feedback.jsonl(自動は「良い」に数えない)・書き出しのジョブ(速報版)
  export   … 書き出しが済んだ(・欠けで書き出せなかった)ジョブを本番版への作り直しに入れ(P4。設定 live.autoArchive がオフでも)、入れ替えたら
             まとめて実行へ渡す(文字起こし → パック)。全部が済む(渡した・失敗した)と done(n 本のうち渡した数・失敗の数)
  done・none(採用する候補が無かった)・error(理由。「調子」の失敗に出す = src/flow/live_failures.py の after_stream_failure)
録画を自動で消す(src/manage/keep/live_cleanup.py)は、オンの間 afterStream が済むまで(AFTER_MAX_AGE まで)その録画を消さない(after_stream_hold)。
"""
import json
import os
import shutil
import threading
import time
import urllib.parse

from ytt import fsio, jobs, normalize, schemas, tools
from . import keys as _keys   # 成果物の鍵(RS6 b-K1)
from . import live_failures   # 失敗の文は 1 か所。M3・M7
from . import live_export as LX

CODE_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "pipeline", "ingest")   # 子プロセスの道具は ① の置き場(pipeline/ingest)
WORKER = os.path.join(CODE_DIR, "live_align_worker.py")
SCHEMA = "ytt-live-archive/v1"
RUN = LX.ARCHIVE_RUN
ACTIVE = LX.ARCHIVE_ACTIVE
LABELS = {"wait": "待ち", "probe": "アーカイブを確かめ中", "align": "照合中", "fetch": "取得中", "verify": "検証中",
          "done": "本番版", "error": "失敗", "cancelled": "取り消し"}
# 確かさのしきい値(src/home/tests/test_live_archive.py の合成の音で決めた。2026-10-05):
#   同じ音(AAC で作り直し・音量 60%・数十 ms ずらし)… score 0.99・ratio 17(60 秒の参照なら ratio は上限の 99)
#   別の音(周波数の動きとノイズの違う合成の音)… score 0.18・ratio 1.3
# 本物の配信はアーカイブ・速報版の両方で作り直しが重なり、BGM の繰り返しで 2 番目の山も高くなりやすいので、score は真ん中より下の 0.5、
# ratio は「別の音」の 1.3 より上の 1.5 にした(両方を満たしたときだけ使う)。
# 2026-10-05 に本物の配信 4 本で測った: 正しい区間は score 0.97〜0.999・ratio 4.7〜58、合わない区間で ratio 1.58 が出た(止めたのは score だけ)→ ratio は 3.0
MIN_SCORE = 0.5
MIN_RATIO = 3.0
FRAME_TOL = 0.034            # 本番版と速報版の音のずれの上限(30fps の 1 コマ)
REF_MAX = 60.0               # 照合に使う速報版の音の長さ(秒)
WINDOWS_FIRST = (300.0, 900.0)        # 配信で最初の照合: ±300 秒 → だめなら ±900 秒で1回だけ(release_timestamp と本当の 0 秒の差が −220 秒の配信があった)
WINDOWS_NEXT = (20.0, 120.0, 900.0)   # 2 本目から: 前のずれの ±20 秒 → だめなら広げる
YTDLP_RETRIES = 2            # yt-dlp の一時的な失敗(HTTP 403 など)は、あけてやり直す回数(用意の確認と音の取得)
YTDLP_RETRY_WAIT = 30.0      # やり直すまでの秒
PRE_SEEK = 10.0             # 音を切るとき、入力側で飛ぶのはこれだけ手前まで(残りはデコードして切る)
AUDIO_DIR = "audio-"       # 入口の作業用 live\work\audio-<videoId>\(配信の丸ごとの音)
FIRST_DELAY = 30 * 60.0      # 録画が終わってから、自動で確かめ始めるまで
INTERVAL = 3600.0            # 自動で確かめる間隔
GIVE_UP = 7 * 86400.0        # 録画が終わってからこれだけたったら、自動ではやめる
READY_CACHE = 600.0          # 「用意できた」を確かめ直さずに使う秒(画面のボタン)
POLL = 60.0                  # 見回りの間隔
RETRY_SEC = 15 * 60.0        # 使用中で入れ替えられなかったとき、次に試すまで
STEP = 1.0                   # スタジオの書き出しの進み具合を見る間隔
STUDIO_DOWN = 120.0          # スタジオにこれだけつながらなければ失敗
PROBE_TIMEOUT = 60.0
FETCH_TIMEOUT = 300.0        # 配信の丸ごとの音の取得(2.5 時間の配信で 7 秒だった)
FFMPEG_TIMEOUT = 300.0
WORKER_TIMEOUT = 300.0
HEIGHTS = (480, 720, 1080, 1440, 2160)   # スタジオの書き出しの maxHeight(src/pipeline/export/exporter.py の build_spec)
AFTER_MAX_AGE = 2 * 86400.0  # 配信後の全自動(M7)は、録画が終わってからこれだけの間(古い録画は自動で切り抜かない・消すのも止めない)
AFTER_TOP_MAX = 30           # 1 本の録画で自動で採用する数の上限(スタジオの解析の候補の数 count の上限と同じ)
AFTER_MIN_SEC = 3.0          # 録画の範囲に切り詰めた候補がこれより短ければ使わない
AFTER_INSIDE = 0.5           # 候補の区間のうち、これだけ(割合)が録画の中にあれば、録画の範囲に切り詰めて使う
AFTER_FLOW = "auto"          # 自動で採用した切り抜きの書き出したあと = 文字起こし → パック(M7 の決まり。live.auto.after に関係なく)
REF_SEC = 60.0               # 録画とアーカイブの時刻を合わせるときに、録画から取る音の長さ(秒)
AFTER_LABELS = {"wait": "アーカイブの用意を待っています", "analyze": "アーカイブを解析しています", "export": "書き出し → 本番版 → パック",
                "done": "済み", "none": "採用する候補がありませんでした", "error": "失敗"}
AFTER_END = ("done", "none", "error")
SPEED_DIR = "速報版"                      # 作業用\速報版\(退避した速報版)
BUILD_DIR = "本番版の作りかけ"            # 作業用\本番版の作りかけ\<ジョブ>\(スタジオが書く先。済んだら消す)
UNAVAILABLE = ("subscriber_only", "premium_only", "needs_auth", "private")


class ArchiveError(LX.LiveError):
    """作り直せない理由(archive.state = error・archive.message に出す)"""


class Later(Exception):
    """今はできない(使用中・用意がまだ)。archive.state を wait に戻して、あとでやり直す"""
    def __init__(self, message, after=None):
        super().__init__(message)
        self.after = after


# ---------- 外のプログラム(yt-dlp・ffmpeg・照合の子プロセス) ----------

def run_proc(cmd, timeout, cancelled=None):
    """外のプログラムを1回(シェルを通さない・窓を出さない・通常より下の優先度)。取り消し・時間切れで止める。
    -> (終了コード, 標準出力, エラーの行の最後の数行)。取り消しは LX.Cancelled、時間切れ・起動できないは ArchiveError。
    中身は ytt.tools.run(標準エラーは最後の 20 行だけ持つ)。名前はテストが差し替えるので残す"""
    try:
        r = tools.run(cmd, timeout=timeout, cancelled=cancelled, flags=tools.no_window_flags(priority="low"), err_tail=20)
    except OSError as e:
        raise ArchiveError("%s を起動できませんでした: %s" % (os.path.basename(cmd[0]), tools.why(e)))
    if r.why == "cancel":
        raise LX.Cancelled()
    if r.why == "timeout":
        raise ArchiveError("%s が %d 秒で終わりませんでした" % (os.path.basename(cmd[0]), int(timeout)))
    return r.code, r.out.decode("utf-8", "replace"), r.err_lines(3)


def _num(s):
    try:
        v = float(s)
    except (TypeError, ValueError):
        return None
    return v if v == v and v > 0 else None


def _pause(sec, cancelled=None):
    """やり直す前に待つ(取り消し・入口の終了で止める)"""
    end = time.time() + sec
    while time.time() < end:
        if cancelled and cancelled():
            raise LX.Cancelled()
        time.sleep(min(0.5, max(0.0, end - time.time())))


def probe_archive(video_id, timeout=PROBE_TIMEOUT, retries=None, wait=None, cancelled=None):
    """yt-dlp でアーカイブの状態を調べる(ダウンロードしない)。video_id は検査済みの 11 文字だけ(URL はここで組み立てる)。
    調べられなかった(HTTP 403 などの一時的な失敗。メンバー限定・非公開は除く)ときは wait 秒あけて retries 回までやり直す。
    -> {"status": live_status か "unknown", "release", "timestamp", "duration"(数か None), "availability", "message"}"""
    retries = YTDLP_RETRIES if retries is None else retries
    for n in range(retries + 1):
        p = _probe_once(video_id, timeout)
        final = p.pop("final", False)   # やり直しても変わらない失敗(id が正しくない・yt-dlp が無い)。画面の文の中身では決めない
        if p.get("status") != "unknown" or p.get("availability") or n == retries or final:
            return p
        _pause(YTDLP_RETRY_WAIT if wait is None else wait, cancelled)
    return p


def _probe_once(video_id, timeout):
    """yt-dlp で 1 回だけ調べる(probe_archive の中身)。やり直しても無駄な失敗には "final": True を付ける(probe_archive が外す)"""
    if not LX.YT_ID_RE.match(video_id or ""):
        return {"status": "unknown", "message": "YouTube の動画の id が正しくありません", "final": True}
    yd = tools.find_tool("yt-dlp")
    if not yd:
        return {"status": "unknown", "message": "yt-dlp が見つからないので、アーカイブを確かめられませんでした", "final": True}
    cmd = [yd, "--encoding", "utf-8", "--skip-download", "--no-warnings", "--no-playlist", "--ignore-no-formats-error",
           "--print", "%(live_status)s\t%(release_timestamp)s\t%(timestamp)s\t%(duration)s\t%(availability)s",
           "--", "https://www.youtube.com/watch?v=" + video_id]
    try:
        code, out, tail = run_proc(cmd, timeout)
    except ArchiveError as e:
        return {"status": "unknown", "message": str(e)}
    lines = [x for x in out.strip().splitlines() if "\t" in x]
    if not lines:
        last = " ".join(tail)
        if "members" in last.lower() or "join this channel" in last.lower():
            return {"status": "unknown", "availability": "subscriber_only", "message": "メンバー限定の配信なので、アーカイブを取れません"}
        if "private" in last.lower():
            return {"status": "unknown", "availability": "private", "message": "非公開の配信なので、アーカイブを取れません"}
        return {"status": "unknown", "message": "アーカイブを確かめられませんでした" + ("(%s)" % last[:160] if last else "")}
    p = lines[-1].split("\t")
    p += [""] * (5 - len(p))
    st = p[0].strip()
    return {"status": st if st in ("is_live", "is_upcoming", "was_live", "not_live", "post_live") else "unknown",
            "release": _num(p[1]), "timestamp": _num(p[2]), "duration": _num(p[3]), "availability": p[4].strip(), "message": ""}


def readiness(p):
    """probe_archive の結果 → (ready: True|False|None, 画面に出す文)"""
    st, av = p.get("status"), p.get("availability") or ""
    if av in UNAVAILABLE:
        return False, p.get("message") or "メンバー限定か非公開の配信なので、アーカイブを取れません(速報版のままです)"
    if st == "was_live":
        return True, "アーカイブを使えます"
    if st == "post_live":
        return False, "配信は終わりましたが、アーカイブはまだ YouTube で処理中です"
    if st == "is_live":
        return False, "配信がまだ続いています"
    if st == "is_upcoming":
        return False, "配信がまだ始まっていません"
    if st == "not_live":
        return False, "配信のアーカイブではないようです"
    return None, p.get("message") or "アーカイブを確かめられませんでした"


def fetch_full_audio(video_id, folder, cancelled=None, timeout=FETCH_TIMEOUT, retries=None, wait=None):
    """配信の音を丸ごと yt-dlp で取る(-f ba = スタジオの書き出し bv*+ba と同じ音。区間の取得 --download-sections は遅く、形式で頭がずれるので使わない)。
    一時的な失敗(HTTP 403 など)は wait 秒あけて retries 回までやり直す。-> 取ったファイルのパス(folder の中の full.<拡張子>)"""
    if not LX.YT_ID_RE.match(video_id or ""):
        raise ArchiveError("YouTube の動画の id が正しくありません")
    yd = tools.find_tool("yt-dlp")
    if not yd:
        raise ArchiveError("yt-dlp が見つかりません")
    os.makedirs(folder, exist_ok=True)
    cmd = [yd, "--encoding", "utf-8", "--no-warnings", "--no-playlist", "--no-part", "--force-overwrites", "--no-progress",
           "-f", "ba", "-o", os.path.join(folder, "full.%(ext)s")]
    ff = tools.find_tool("ffmpeg", "YTT_FFMPEG")
    if ff:
        cmd += ["--ffmpeg-location", ff]
    cmd += ["--", "https://www.youtube.com/watch?v=" + video_id]
    retries = YTDLP_RETRIES if retries is None else retries
    why = ""
    for n in range(retries + 1):
        code, _out, tail = run_proc(cmd, timeout, cancelled)
        got = [os.path.join(folder, x) for x in os.listdir(folder) if x.startswith("full.") and not x.endswith((".part", ".ytdl"))]
        if code == 0 and got:
            return max(got, key=os.path.getsize)
        why = " / ".join(tail) or "終了コード %s" % code
        for x in got:
            fsio.unlink_quiet(x)
        if n < retries:
            _pause(YTDLP_RETRY_WAIT if wait is None else wait, cancelled)
    raise ArchiveError("アーカイブの音を取れませんでした(%s)" % why)


def worker_python(python=None):
    """照合の子プロセスの Python(入口と同じ = numpy が入っている 3.10)。窓の無い pythonw は標準出力を返せないことがあるので python.exe にする"""
    return tools.python_exe(python)


def run_align(ref, win, python=None, timeout=WORKER_TIMEOUT):
    """src/pipeline/ingest/live_align_worker.py を子プロセスで動かす -> その JSON({ok, offset, score, ratio, …} か {ok: false, reason})"""
    code, out, tail = run_proc([worker_python(python), WORKER, ref, win], timeout)
    lines = [x for x in out.strip().splitlines() if x.startswith("{")]
    try:
        d = json.loads(lines[-1]) if lines else None
    except ValueError:
        d = None
    if not isinstance(d, dict):
        return {"ok": False, "reason": "照合の子プロセスが答えを返しませんでした(%s)" % (" / ".join(tail) or "終了コード %s" % code)}
    return d


# ---------- ファイルの置き場所 ----------
def inside(path, root):
    """path が root の中か(root そのものは含めない。realpath で比べる = シンボリックリンク・.. で外へ出ない。ネットワーク上のパスは False)"""
    return fsio.is_inside(path, root, strict=True)


def free_name(folder, name):
    """folder の中で使われていない名前(重なれば <名前>_2.mp4 …)"""
    stem, ext = os.path.splitext(name)
    cand, i = name, 2
    while os.path.lexists(os.path.join(folder, cand)):
        cand = "%s_%d%s" % (stem, i, ext)
        i += 1
    return os.path.join(folder, cand)


# ---------- 配信後の全自動(M7)の決め方 ----------
def ended_at(r):
    """録画の一覧の行 r の「終わった時刻」(epoch 秒): endedAt、無ければ lastPdt(最後のセグメントの時刻)。分からなければ None。
    行の時刻の型は呼ぶ側で違う: after_tick は epoch(src/home/live.py の list_recordings)、after_stream_hold は録画の部品の生の行 = ISO の文字列
    (src/manage/keep/live_cleanup.py)。どちらでも同じ値にする(3 か所で別々に求めていたのを 1 つに。2026-10-09)"""
    for k in ("endedAt", "lastPdt"):
        v = r.get(k)
        t = float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else LX.iso_epoch(v)
        if t is not None:
            return t
    return None


def _checked_within(i, ttl, now=None):
    """記録 i の用意の確認(checkedAt)が ttl 秒以内か(確かめたばかりなら確かめ直さない)。checkedAt が無い・読めなければ False"""
    checked = LX.iso_epoch(i.get("checkedAt"))
    return bool(checked) and (time.time() if now is None else now) - checked < ttl


def after_count(rec_sec, per_hour):
    """自動で採用する数 N = 録画の長さ(時間)× 1 時間あたりの数(四捨五入。1〜AFTER_TOP_MAX)"""
    try:
        n = int(round(max(0.0, float(rec_sec)) / 3600.0 * float(per_hour)))
    except (TypeError, ValueError):
        n = 1
    return max(1, min(AFTER_TOP_MAX, n))


def pick_candidates(marks, n, t0, offset, first, last, taken=()):
    """アーカイブの解析の候補(スタジオのアーカイブの配信のマーク。秒 = アーカイブの秒)から、録画の範囲に入る上位 n 個を選ぶ。
    アーカイブの秒 s → 絶対時刻 = t0 + s − offset(P4 の offset と同じ向き: アーカイブの秒 = 絶対時刻 − t0 + offset)。
    候補 = 自動のマーク(src auto)で判定前(status が空)。点数の高い順に、録画 [first, last] に半分以上入るものを録画の範囲に切り詰め、
    taken(もう採用・書き出し済みの区間 [(絶対時刻, 絶対時刻)])と選んだものに重なる候補は飛ばす。-> [(a, b, マーク)](時刻の順)"""
    num = lambda v: isinstance(v, (int, float)) and not isinstance(v, bool)   # noqa: E731
    cands = sorted((m for m in marks or [] if isinstance(m, dict) and m.get("src") == "auto" and not m.get("status")
                    and num(m.get("start")) and num(m.get("end")) and m["end"] > m["start"]), key=lambda m: -(m.get("score") or 0))
    out, used = [], [tuple(x) for x in taken]
    for m in cands:
        if len(out) >= n:
            break
        a0, b0 = t0 + m["start"] - offset, t0 + m["end"] - offset
        a, b = max(a0, first), min(b0, last)
        if b - a < max(AFTER_MIN_SEC, (b0 - a0) * AFTER_INSIDE):
            continue
        if any(a < y and x < b for x, y in used):
            continue
        out.append((a, b, m))
        used.append((a, b))
    return sorted(out, key=lambda x: x[0])


def after_progress(a, jobs):
    """配信後の全自動(M7)で採用したジョブの進み具合(スタジオの LIVE の帯に出す数。入口 0.41.0)。
    a = afterStream・jobs = その録画のジョブ(GET /live/api/exports の jobs の形 = tx・failure つき)。一覧から消えた古いジョブは total にだけ入る。
    -> {"total": 採用した本数, "exported": 書き出し済み, "archived": 本番版にした, "handed": まとめて実行へ渡した,
        "finished": まとめて実行(文字起こし → パック)まで済んだ, "failed": 失敗の文があるもの(live_failures.failure_of)}"""
    ids = [x for x in a.get("jobs") or [] if isinstance(x, str)]
    mine = [j for j in jobs or [] if isinstance(j, dict) and j.get("id") in ids]
    return {"total": len(ids),
            "exported": sum(1 for j in mine if j.get("state") == "done"),
            "archived": sum(1 for j in mine if (j.get("archive") or {}).get("state") == "done"),
            "handed": sum(1 for j in mine if j.get("runId")),
            "finished": sum(1 for j in mine if (j.get("tx") or {}).get("state") == "done"),
            "failed": sum(1 for j in mine if j.get("failure"))}


def after_text(a, p):
    """スタジオの LIVE の帯に出す 1 行(afterStream の label と、採用したあとは after_progress の数。無ければ message)"""
    head = "配信後の自動の切り抜き: %s" % (a.get("label") or a.get("state") or "")
    if a.get("state") in ("export", "done") and p["total"]:
        return head + "(%d 本のうち 書き出し %d・本番版 %d・文字起こし → パックへ %d・パックまで済み %d%s)" % (
            p["total"], p["exported"], p["archived"], p["handed"], p["finished"], "・失敗 %d" % p["failed"] if p["failed"] else "")
    msg = str(a.get("message") or "")
    return head + ("(%s)" % msg if msg else "")


# ---------- 本体 ----------
class Archiver:
    def __init__(self, exporter, studio, enabled=None, auto=None, recording_state=None, probe=None, audio=None, align=None,
                 slots=None, python=None, ffmpeg=None, ffprobe=None, log=None, first_delay=FIRST_DELAY, interval=INTERVAL,
                 give_up=GIVE_UP, poll=POLL, retry_sec=RETRY_SEC, step=STEP, after=None,
                 after_stream=None, per_hour=None, recordings=None, adopt=None, after_max_age=AFTER_MAX_AGE, compare=None, request=None,
                 pack_info=None, settings_for=None):
        """exporter: src/flow/live_export.py の Exporter(ジョブ・マーク・書き出し先・音量)。
        studio(method, path, body) -> (HTTP の番号 か None(つながらない), JSON): 取り込んだスタジオの API(src/home/live.py が autorun と同じ形で呼ぶ)。
        enabled()・auto(): リアルタイム切り抜きがオンか・設定 live.autoArchive。recording_state(録画元, 録画) -> {"active", "endedAt"(epoch)} か None。
        probe(videoId) -> probe_archive の形。audio(videoId, folder, cancelled) -> 配信の丸ごとの音のファイル(fetch_full_audio)。align(ref.wav, window.wav) -> 照合の JSON。
        after(録画元, 録画): 1本を終えたとき(済み・失敗・取り消し)に呼ぶ(src/manage/keep/live_cleanup.py の Cleaner.check = 全部入れ替わった録画を消す)。
        配信後の全自動(M7): after_stream() = 設定 live.autoAfterStream・per_hour() = live.afterStreamPerHour・
        recordings() -> 録画元の録画の一覧 [{recorder, id, url, title, active, endedAt, firstPdt, lastPdt}](時刻は epoch。src/home/live.py の list_recordings)・
        adopt(body, hold=) = M1 の採用(Live.adopt)。
        pack_info(動画のパス) -> その動画の Resolve パックの情報か None(速報版を本番版にしたとき、前に作ったパックが速報版のままだと知らせるため。
        パックの有無の規則は manage/cases/txindex.pack_info だけが持つので、入口(Live)が渡す。None = 知らせない)。
        settings_for(録画元, 録画) -> 配信後の全自動のアーカイブの解析の設定(録画の束の analyze 節。flow/livesession.py。RS7-2 G2b)か None
        (束の無い録画 = 今までどおりスタジオの GET /api/settings)。
        テストは probe・audio・studio を偽物に、間隔を短くする(本物の YouTube へ繋がない)"""
        self.ex, self.studio = exporter, studio
        self.after = after
        self.after_stream = after_stream or (lambda: False)
        self.per_hour = per_hour or (lambda: 6)
        self.friend_request = request or (lambda rc, rec: None)   # 引数 request(録画元, 録画) = 友人のライブ配信の依頼(live_requests.Store.get。2-15)。無ければ None。
        # 名前は friend_request(self.request は「作り直しを頼む」メソッド = POST /live/api/archive。上書きしない)
        self.recordings = recordings or (lambda: [])
        self.adopt = adopt
        self.after_max_age = after_max_age
        self.compare = compare   # compare(録画元, 録画, afterStream, アーカイブの候補): 配信中の候補と比べて記録する(0-10-6。src/flow/live_detect.py)
        self.pack_info = pack_info or (lambda path: None)
        self.settings_for = settings_for or (lambda rc, rec: None)
        self.enabled = enabled or (lambda: True)
        self.auto = auto or (lambda: True)
        self.recording_state = recording_state or (lambda rc, rec: None)
        self.probe = probe or probe_archive
        self.audio = audio or fetch_full_audio
        self.python = python
        self.align = align or (lambda ref, win: run_align(ref, win, self.python))
        self.slots = slots or jobs.SLOTS
        self.ffmpeg, self.ffprobe = ffmpeg, ffprobe
        self._probes = fsio.StampCache()   # 速報版の ffprobe の結果(1 本の作り直しで照合・高さ・ずれの確かめに使う。ファイルが変われば調べ直す)
        self.log = log or (lambda m: None)
        self.first_delay, self.interval, self.give_up = first_delay, interval, give_up
        self.poll, self.retry_sec, self.step = poll, retry_sec, step
        self.path = os.path.join(exporter.folder, "archive.json")
        self.lock = threading.RLock()
        self.wake = threading.Event()
        self._halt = threading.Event()
        self._thread = None
        self._cancel = set()      # 取り消しを頼まれたジョブの id(動いている途中のもの)
        self.info = {}
        self._load()

    # --- 録画ごとの記録(archive.json) ---
    @staticmethod
    def key(rc, rec):
        return "%s__%s" % (rc, rec)

    def _load(self):
        try:
            d = fsio.read_json_file(self.path, 2 * 1024 * 1024)
        except (OSError, ValueError):
            d = None
        rs = d.get("recordings") if isinstance(d, dict) and d.get("schema") == SCHEMA else None
        self.info = {k: v for k, v in (rs or {}).items() if isinstance(v, dict)} if isinstance(rs, dict) else {}

    def _save_info(self):
        with self.lock:
            data = json.dumps({"schema": SCHEMA, "recordings": self.info}, ensure_ascii=False, indent=1).encode("utf-8")
        try:
            fsio.atomic_write(self.path, data)
        except OSError as e:
            self.log("リアルタイム切り抜き: アーカイブの記録を書けませんでした: %s" % e)

    def info_view(self, rc, rec, jobs=None):
        """GET /live/api/exports の archiveInfo {ready: true|false|null, checkedAt, message}。
        配信後の全自動(M7)があれば afterStream {state, label, message, at, n, jobs(採用した本数), progress(after_progress), text(after_text)}。
        jobs = その録画のジョブ(応答の jobs。None なら書き出しの一覧から読む)。帯への表示はスタジオの側(src/studio/review.js)"""
        with self.lock:
            i = dict(self.info.get(self.key(rc, rec)) or {})
        out = {"ready": i.get("ready") if i.get("ready") in (True, False) else None, "checkedAt": i.get("checkedAt"),
               "message": i.get("message") or ""}
        a = i.get("afterStream")
        if isinstance(a, dict):   # 配信後の全自動(M7)の進み具合
            out["afterStream"] = {k: a.get(k) for k in ("state", "label", "message", "at", "n")}
            out["afterStream"]["jobs"] = len(a.get("jobs") or [])
            p = after_progress(a, self.ex.snapshot(rc, rec) if jobs is None else jobs)
            out["afterStream"].update(progress=p, text=after_text(a, p))
        return out

    # --- ジョブ ---
    def _aset(self, job, save=True, **kw):
        """job["archive"] を新しい辞書に置き換える(画面へ返す写しと同時に書き換えない)"""
        with self.ex.lock:
            a = dict(job.get("archive") or {}, **kw)
            if "state" in kw and "label" not in kw:
                a["label"] = LABELS.get(kw["state"], kw["state"])
            job["archive"] = a
            job["updated"] = LX.now_iso()
        if save:
            self.ex._save()

    def _rec_jobs(self, rc, rec):
        with self.ex.lock:
            return [j for j in self.ex.jobs if j.get("recorder") == rc and j.get("recording") == rec]

    def targets(self, rc, rec):
        """対象: マークごとの最新のジョブで、done(入れ替え)か error + needsArchive(新しく作る)"""
        return sorted([j for j in LX.latest_per_mark(self._rec_jobs(rc, rec)) if j.get("state") == "done" or (j.get("state") == "error" and j.get("needsArchive"))],
                      key=lambda j: j.get("start") or "")

    def _queue(self, js, auto):
        for j in js:
            self._cancel.discard(j["id"])
            self._aset(j, save=False, state="wait", message="順番を待っています", progress=0, auto=bool(auto), retryAt=None)
        self.ex._save()
        self.start()
        self.wake.set()

    def request(self, rc, rec):
        """POST /live/api/archive(画面のボタン)。対象の全部を始める。-> {ok, queued, message}。対象が無い・用意がまだ → LiveError(409)"""
        ts = self.targets(rc, rec)
        todo = [j for j in ts if (j.get("archive") or {}).get("state") not in ACTIVE + ("done",)]
        if not todo:
            if any((j.get("archive") or {}).get("state") in ACTIVE for j in ts):
                return {"ok": True, "queued": 0, "message": "もう作り直しています"}
            if ts:
                raise ArchiveError("どのマークも本番版になっています", 409)
            raise ArchiveError("本番版に作り直すものがありません(書き出したマークと、欠けで書き出せなかったマークが対象です)", 409)
        i = self.info_view(rc, rec)
        fresh = i["ready"] is True and _checked_within(i, READY_CACHE)
        if not fresh:
            i = self.check(rc, rec, quick=True)   # 画面のボタン: やり直して待たせない(断られたら、もう一度押せる)
        if i.get("ready") is not True:
            raise ArchiveError(i.get("message") or "アーカイブがまだ用意できていません", 409)
        self._queue(todo, auto=False)
        return {"ok": True, "queued": len(todo), "message": "%d 本を本番版に作り直します" % len(todo)}

    def cancel(self, rc, rec):
        """POST /live/api/archive/cancel。-> 取り消した数(待ちはすぐ、途中のものは今の段を止めてから)"""
        n = 0
        for j in self._rec_jobs(rc, rec):
            st = (j.get("archive") or {}).get("state")
            if st == "wait":
                built = (j.get("archive") or {}).get("built")
                if isinstance(built, str) and inside(built, self.ex.out_dir()) and os.path.basename(os.path.dirname(built)) == j["id"]:
                    shutil.rmtree(os.path.dirname(built), ignore_errors=True)   # 使用中で入れ替え待ちだった本番版(自分で作った作りかけのフォルダだけ)
                self._aset(j, save=False, state="cancelled", message="取り消しました(速報版のままです)", progress=0, built=None)
                n += 1
            elif st in RUN:
                self._cancel.add(j["id"])
                n += 1
        self.ex._save()
        self.wake.set()
        return n

    # --- アーカイブの用意 ---
    def video_id(self, rc, rec):
        """録画の YouTube の動画の id(マークの正本の URL → 書き出した .clip.json → 録画の id の後ろ)。分からなければ ""(11 文字の形だけ返す)"""
        try:
            url = self.ex.marks.load(rc, rec).get("url") or ""
        except LX.LiveError:
            url = ""
        vid = LX.video_id_of(url)
        if vid:
            return vid
        for j in self._rec_jobs(rc, rec):
            p = j.get("manifest")
            if isinstance(p, str) and p and inside(p, self.ex.out_dir()):
                c, _w = schemas.load_clip_file(p)
                v = str(((c or {}).get("source") or {}).get("videoId") or "")
                if LX.YT_ID_RE.match(v):
                    return v
        return LX.video_id_of("", rec)

    def check(self, rc, rec, quick=False, vid=None):
        """アーカイブの用意を確かめて覚える -> 覚えた辞書。vid: 分かっていれば YouTube の動画の id(配信後の全自動 = マークがまだ無い録画。M7)"""
        vid = vid if LX.YT_ID_RE.match(vid or "") else self.video_id(rc, rec)
        if not vid:
            ready, msg, p = False, "YouTube の動画が分からない録画なので、アーカイブで作り直せません", {}
        else:
            try:
                p = (probe_archive(vid, retries=0) if quick and self.probe is probe_archive else self.probe(vid)) or {}
            except Exception as e:   # 調べる部品の不具合でも見回りは止めない
                p = {"status": "unknown", "message": "アーカイブを確かめられませんでした(%s)" % e.__class__.__name__}
            ready, msg = readiness(p)
        return self._info_put(rc, rec, videoId=vid, ready=ready, message=msg, checkedAt=LX.now_iso(), release=p.get("release"), timestamp=p.get("timestamp"))

    def _info_put(self, rc, rec, **kw):
        """録画ごとの記録に kw を足して archive.json に残す -> 足したあとの記録の写し"""
        with self.lock:
            i = dict(self.info.get(self.key(rc, rec)) or {}, recorder=rc, recording=rec, **kw)
            self.info[self.key(rc, rec)] = i
        self._save_info()
        return dict(i)

    def _ready_info(self, rc, rec):
        with self.lock:
            i = dict(self.info.get(self.key(rc, rec)) or {})
        if i.get("ready") is True and _checked_within(i, self.interval):
            return i
        return self.check(rc, rec)

    # --- 動かす ---
    def start(self):
        with self.lock:
            if self._thread is None or not self._thread.is_alive():
                self._halt.clear()
                self._thread = threading.Thread(target=self._loop, daemon=True, name="live-archive")
                self._thread.start()

    def close(self):
        self._halt.set()
        self.wake.set()
        t = self._thread
        if t is not None:
            t.join(15)

    def _loop(self):
        while not self._halt.is_set():
            try:
                job = self._next()
                if job is not None:
                    self._process(job)
                    self._clean_audio()
                    if self.after and (job.get("archive") or {}).get("state") == "done" and not self._next_of(job):
                        self.after(job["recorder"], job["recording"])   # その録画の最後の1本が済んだ: 全部入れ替わっていれば録画を消す(P4)
                    continue
                self._clean_audio()
                self.auto_tick()
                self.after_tick()   # 配信後の全自動(M7。設定 live.autoAfterStream)
            except Exception as e:   # 見回りは止めない
                self.log("リアルタイム切り抜き: 本番版の見回りでエラー: %r" % (e,))
            self.wake.wait(self.poll)
            self.wake.clear()

    def _next(self):
        """順番待ちのうち次の1本: 録画ごとに、速報版のある(照合できる)ものを先に・時刻の順(欠けのマークは照合のずれを使うので後)"""
        now = time.time()
        with self.ex.lock:
            w = [j for j in self.ex.jobs if (j.get("archive") or {}).get("state") == "wait"
                 and (j["archive"].get("retryAt") or 0) <= now and j["id"] not in self._cancel]
        w.sort(key=lambda j: (j.get("recorder") or "", j.get("recording") or "", 0 if j.get("state") == "done" else 1, j.get("start") or ""))
        return w[0] if w else None

    def _vid_of(self, job):
        """ジョブの配信の YouTube の動画の id(用意を確かめたときに覚えた値)。分からなければ "\""""
        with self.lock:
            return (self.info.get(self.key(job.get("recorder"), job.get("recording"))) or {}).get("videoId") or ""

    def _audio_dir(self, vid):
        return os.path.join(self.ex.work, AUDIO_DIR + vid)

    def _clean_audio(self):
        """配信の丸ごとの音(live\\work\\audio-<videoId>\\)は、その配信の作り直しが待ち・途中で無くなったら消す(古い物も見回りで消える)"""
        try:
            names = [n for n in os.listdir(self.ex.work) if n.startswith(AUDIO_DIR)]
        except OSError:
            return
        if not names:
            return
        with self.ex.lock:
            busy = [j for j in self.ex.jobs if (j.get("archive") or {}).get("state") in ACTIVE]
        keep = {self._vid_of(j) for j in busy}
        for n in names:
            if n[len(AUDIO_DIR):] not in keep:
                shutil.rmtree(os.path.join(self.ex.work, n), ignore_errors=True)

    def _full_audio(self, job, vid):
        """配信の丸ごとの音(同じ配信のジョブで使い回す。取り終えた印 done があるものだけ)-> パス"""
        d = self._audio_dir(vid)
        try:
            with open(os.path.join(d, "done"), "r", encoding="utf-8") as f:
                p = os.path.join(d, os.path.basename(f.read().strip()))
            if os.path.isfile(p):
                return p
        except OSError:
            pass
        shutil.rmtree(d, ignore_errors=True)
        self._aset(job, message="配信の音を取っています(yt-dlp)")
        p = self.audio(vid, d, lambda: job["id"] in self._cancel or self._halt.is_set())
        if not p or not os.path.isfile(p):
            raise ArchiveError("アーカイブの音を取れませんでした")
        if os.path.normcase(os.path.dirname(os.path.abspath(p))) == os.path.normcase(os.path.abspath(d)):   # 作業用に取ったものだけ使い回す印を付ける
            fsio.atomic_write(os.path.join(d, "done"), os.path.basename(p).encode("utf-8"))
        return p

    def _next_of(self, job):
        """同じ録画に、まだ順番待ち・途中のものがあるか"""
        with self.ex.lock:
            return any(j is not job and j.get("recorder") == job.get("recorder") and j.get("recording") == job.get("recording")
                       and (j.get("archive") or {}).get("state") in ACTIVE for j in self.ex.jobs)

    def busy(self):
        """ほかの重い処理(SLOTS の実行中・順番待ち)か、書き出しのジョブがある"""
        s = self.slots.snapshot()
        return bool(s.get("active") or s.get("waiting")) or self.ex.pending()

    def _ended_at(self, rc, rec, js):
        """録画が終わった時刻(epoch)。録画中なら None。録画元につながらない・見つからないときはジョブの時刻(マークの終わりのいちばん後)"""
        with self.lock:
            known = (self.info.get(self.key(rc, rec)) or {}).get("endedAt")
        if isinstance(known, (int, float)):
            return known
        try:
            st = self.recording_state(rc, rec)
        except Exception:
            st = None
        if isinstance(st, dict):
            if st.get("active"):
                return None
            e = st.get("endedAt")
            if isinstance(e, (int, float)):
                self._info_put(rc, rec, endedAt=e)
                return e
        ends = [LX.iso_epoch(j.get("end")) for j in js]
        ends = [e for e in ends if e is not None]
        return max(ends) if ends else None

    def auto_tick(self):
        """自動(設定 live.autoArchive): 終わった録画で、まだ試していないマークがあれば、時間が来たら用意を確かめ、用意できていて手が空いていれば始める。
        -> 始めた本数"""
        if not self.enabled() or not self.auto():
            return 0
        now = time.time()
        recs = {}
        with self.ex.lock:
            for j in self.ex.jobs:
                recs.setdefault((j.get("recorder"), j.get("recording")), []).append(j)
        started = 0
        for (rc, rec), js in recs.items():
            if not LX.ID_RE.match(rc or "") or not LX.REC_RE.match(rec or ""):
                continue
            cand = [j for j in self.targets(rc, rec) if not j.get("archive")]   # 一度も試していないもの(失敗・取り消しは人が押す)
            if not cand:
                continue
            k = self.key(rc, rec)
            with self.lock:
                i = dict(self.info.get(k) or {})
            if i.get("gaveUp"):
                continue
            ended = self._ended_at(rc, rec, js)
            if ended is None or now < ended + self.first_delay:
                continue
            recent = _checked_within(i, self.interval, now)
            if not (i.get("ready") is True and recent):
                if now - ended > self.give_up:
                    self._info_put(rc, rec, gaveUp=True, message="録画が終わって %d 日たってもアーカイブを使えなかったので、自動で作り直すのをやめました(%s)"
                                   % (int(self.give_up // 86400) or 1, i.get("message") or "理由は分かりません"))
                    continue
                if recent:
                    continue
                i = self.check(rc, rec)
            if i.get("ready") is not True:
                continue
            if self.busy():
                return started   # 手が空いてから(次の見回りで。用意の確認は INTERVAL のあいだ使い回す)
            self._queue(cand, auto=True)
            self.log("リアルタイム切り抜き: アーカイブで本番版に作り直します(自動。%s の %d 本)" % (rec, len(cand)))
            started += len(cand)
        return started

    # --- 配信後の全自動(M7) ---
    def _after_get(self, rc, rec):
        with self.lock:
            return dict((self.info.get(self.key(rc, rec)) or {}).get("afterStream") or {})

    def _after_set(self, rc, rec, **kw):
        """afterStream を書き換えて archive.json に残す(state を変えたら label と at も)"""
        with self.lock:
            i = dict(self.info.get(self.key(rc, rec)) or {}, recorder=rc, recording=rec)
            a = dict(i.get("afterStream") or {}, **kw)
            if "state" in kw:
                a["label"] = AFTER_LABELS.get(kw["state"], kw["state"])
                a["at"] = LX.now_iso()
            i["afterStream"] = a
            self.info[self.key(rc, rec)] = i
        self._save_info()
        if kw.get("state") == "error":
            self.log("リアルタイム切り抜き: 配信後の自動の切り抜きに失敗しました(%s): %s" % (rec, a.get("message")))
        return a

    def after_tick(self):
        """配信後の全自動(M7。設定 live.autoAfterStream): 終わった録画を 1 段ずつ進める(見回りのたび。重い所 = 照合だけはこの中で待つ)。-> 進めた録画の数"""
        if not self.enabled():
            return 0
        every = self.after_stream()   # ホームのスイッチ(友人の依頼の録画は依頼の afterStream で決める = _after_on。2-15)
        now = time.time()
        moved = 0
        try:
            recs = self.recordings() or []
        except Exception:
            recs = []
        seen = set()
        for r in recs:
            rc, rec = r.get("recorder"), r.get("id")
            if not isinstance(rc, str) or not isinstance(rec, str) or not LX.ID_RE.match(rc) or not LX.REC_RE.match(rec) or r.get("active"):
                continue
            seen.add((rc, rec))
            if not self._after_on(rc, rec, every):
                continue
            a = self._after_get(rc, rec)
            if a.get("state") in AFTER_END:
                continue
            ended = ended_at(r)
            if ended is None or now < ended + self.first_delay:
                continue
            if not a and now - ended > self.after_max_age:   # 機能を入れる前・オンにする前の古い録画は始めない
                continue
            if self._after_step(rc, rec, r, a, now):
                moved += 1
        with self.lock:   # 録画元の一覧から消えた録画(消した・置き場所を変えた)でも、書き出しのあとは見届ける
            rest = [(i.get("recorder"), i.get("recording")) for i in self.info.values()
                    if (i.get("afterStream") or {}).get("state") == "export" and (i.get("recorder"), i.get("recording")) not in seen]
        for rc, rec in rest:
            if self._after_step(rc, rec, None, self._after_get(rc, rec), now):
                moved += 1
        return moved

    def _after_step(self, rc, rec, r, a, now):
        """録画 1 本を 1 段進める。-> 進めたか"""
        st = a.get("state")
        try:
            if st in (None, "wait"):
                return self._after_begin(rc, rec, r, a, now)
            if st == "analyze":
                return self._after_analyze(rc, rec, a)
            if st == "export":
                return self._after_follow(rc, rec, a)
        except (LX.Cancelled, LX.Halted):
            return False   # 入口の終了: 次の起動で同じ段からやり直す
        except Later as e:
            self._after_set(rc, rec, message=str(e), retryAt=time.time() + (e.after if e.after is not None else self.interval))
        except (LX.LiveError, normalize.NormalizeError, OSError) as e:
            self._after_set(rc, rec, state="error", message=str(e) if not isinstance(e, OSError) else "書けませんでした: %s" % tools.why(e))
        except Exception as e:
            self.log("リアルタイム切り抜き: 配信後の自動の切り抜きでエラー %r" % (e,))
            self._after_set(rc, rec, state="error", message="内部エラー: %s" % e.__class__.__name__)
        return False

    def _request_after(self, rc, rec):
        """友人の依頼の録画で、配信後のアーカイブからの追加(afterStream)を頼まれているか"""
        req = self.friend_request(rc, rec)
        return bool(req) and (req.get("settings") or {}).get("afterStream") is True

    def _after_on(self, rc, rec, every=None):
        """この録画で配信後の全自動(M7)を動かすか: 友人の依頼の録画は依頼の afterStream だけで決める(偽ならホームの M7 がオンでも動かさない。2-15)、
        ほかの録画はホームのスイッチ every(None = 今の設定)"""
        if self.friend_request(rc, rec):
            return self._request_after(rc, rec)
        return self.after_stream() if every is None else bool(every)

    def _per_hour_for(self, rc, rec):
        """配信後の 1 時間あたりの本数: 友人の依頼の録画は依頼の設定、ほかはホームの設定"""
        req = self.friend_request(rc, rec)
        v = (req.get("settings") or {}).get("perHour") if req else None
        return v if isinstance(v, int) and not isinstance(v, bool) and v > 0 else self.per_hour()

    def _after_begin(self, rc, rec, r, a, now):
        """用意の確認 → 時刻を合わせる → 解析を頼む(スタジオで解析済みなら、すぐ採用へ)"""
        if (a.get("retryAt") or 0) > now:
            return False
        r = r or {}
        vid = LX.video_id_of(r.get("url") or "", rec)
        if not vid:
            self._after_set(rc, rec, state="error", message="YouTube の動画が分からない録画なので、アーカイブで切り抜けません")
            return True
        ended = ended_at(r)
        if ended is not None and now - ended > self.after_max_age:
            self._after_set(rc, rec, state="error", message="録画が終わって %d 日たってもアーカイブを使えなかったので、自動で切り抜くのをやめました(%s)"
                            % (int(self.after_max_age // 86400) or 1, a.get("message") or "理由は分かりません"))
            return True
        with self.lock:
            i = dict(self.info.get(self.key(rc, rec)) or {})
        recent = _checked_within(i, self.interval, now)
        if not (i.get("ready") is True and recent):
            if recent:   # 確かめたばかり(P4 と同じ間隔で。用意できていない)
                if not a:
                    self._after_set(rc, rec, state="wait", message=i.get("message") or "アーカイブの用意を待っています", title=str(r.get("title") or "")[:LX.TITLE_MAX])
                return False
            i = self.check(rc, rec, vid=vid)
        if i.get("ready") is not True:
            self._after_set(rc, rec, state="wait", message=i.get("message") or "アーカイブの用意を待っています", title=str(r.get("title") or "")[:LX.TITLE_MAX])
            return False
        if self.ex._disk_low():
            raise Later(self.ex.disk()["message"], LX.DISK_POLL)
        t0 = i.get("release")
        if not isinstance(t0, (int, float)):
            raise ArchiveError("配信の開始時刻が分からないので、アーカイブの候補を録画の時刻に直せません")
        first, last = r.get("firstPdt"), r.get("lastPdt")
        if not isinstance(first, (int, float)) or not isinstance(last, (int, float)) or last - first < 5.0:
            raise ArchiveError("録画が短すぎるか、録画の時刻が分からないので、自動で切り抜けません")
        offset, how = self._after_offset(rc, rec, vid, t0, first, last)
        n = after_count(last - first, self._per_hour_for(rc, rec))
        base = dict(vid=vid, t0=t0, offset=round(offset, 3), offsetFrom=how, first=first, last=last, n=n, title=str(r.get("title") or "")[:LX.TITLE_MAX],
                    retryAt=None)
        _code, v = self._studio_video(vid)
        if v is not None and v.get("analysis"):   # 人がもう解析した: それを使う
            a = self._after_set(rc, rec, state="analyze", qid=None, message="スタジオで解析済みの結果を使います", **base)
            return self._after_adopt(rc, rec, a)
        saved = self.settings_for(rc, rec)   # 録画の束の解析の設定(録画を始めたときの値。決定 3-31 の仮 b1)
        if not isinstance(saved, dict):   # 束の無い録画: スタジオの画面の解析の設定
            code, d = self.studio("GET", "/api/settings", None)
            saved = ((d or {}).get("settings") or {}).get("analyze") if code == 200 and isinstance(d, dict) else None
        saved = dict(saved) if isinstance(saved, dict) else {}
        cnt = saved.get("count") if isinstance(saved.get("count"), int) and not isinstance(saved.get("count"), bool) else 8
        saved["count"] = max(1, min(AFTER_TOP_MAX, max(cnt, n * 2)))   # 録画の外・人のマークと重なる候補を飛ばす分の余り
        code, d = self.studio("POST", "/api/queue/add", {"items": [{"kind": "youtube", "videoId": vid, "title": base["title"]}], "settings": saved})
        if code is None:
            raise Later("スタジオにつながりません(%s)" % ((d or {}).get("message") or ""), self.retry_sec)
        d = d if isinstance(d, dict) else {}
        added = d.get("added") or []
        rej = str((((d.get("rejected") or [{}])[0]) or {}).get("reason") or "")
        if code != 200 or (not added and "すでにキュー" not in rej):
            raise ArchiveError("アーカイブの解析を始められませんでした: %s" % (rej or d.get("message") or "HTTP %s" % code))
        self._after_set(rc, rec, state="analyze", qid=added[0].get("qid") if added else None,
                        message="アーカイブを解析しています(上位 %d 本を採用します。ずれ %.1f 秒・%s)" % (n, offset, how), **base)
        self.log("リアルタイム切り抜き: 配信後の自動の切り抜き: %s のアーカイブ(%s)を解析します(上位 %d 本)" % (rec, vid, n))
        return True

    def _known_offset(self, rc, rec, vid):
        """照合済みのマーク(P4)のずれ: 同じ録画を先に・無ければ同じ配信の別の録画(差は 1 秒ほど = 候補の置き場所には足りる)。中央の値。無ければ None"""
        with self.ex.lock:
            js = [j for j in self.ex.jobs if (j.get("archive") or {}).get("aligned") and isinstance((j.get("archive") or {}).get("offset"), (int, float))]
        same = [j["archive"]["offset"] for j in js if j.get("recorder") == rc and j.get("recording") == rec]
        pool = same or [j["archive"]["offset"] for j in js if vid and self._vid_of(j) == vid]
        if not pool:
            return None
        pool.sort()
        return pool[len(pool) // 2]

    def _after_offset(self, rc, rec, vid, t0, first, last):
        """録画の受信時刻とアーカイブの秒のずれ -> (offset, 出どころの文)。照合済みのマークが無ければ、録画の真ん中あたりの音をアーカイブと照合する"""
        known = self._known_offset(rc, rec, vid)
        if known is not None:
            return known, "照合済みのマークから"
        rco = self.ex.host.find(rc)
        if rco is None:
            raise ArchiveError("その録画元はありません")
        span = min(REF_SEC, last - first - 2.0)
        ra = first + max(1.0, (last - first - span) / 2.0)
        rb = ra + span
        job = {"id": "after-" + rec, "recorder": rc, "recording": rec}   # 照合のための仮のジョブ(書き出しのジョブには入れない)
        wdir = os.path.join(self.ex.work, "after-" + rec)
        try:
            code, d = self.ex._query(rc, rec, ra, rb)
            if code is None:
                raise Later("録画元につながらないので、録画とアーカイブの時刻を合わせられません", self.retry_sec)
            if code != 200 or not isinstance(d, dict):
                raise ArchiveError("録画が見つかりません(録画元で消されたか、置き場所を変えたかもしれません)" if code == 404 else
                                   "録画元から思わぬ応答がありました(HTTP %s)" % code)
            segs = [s for s in d.get("segments") or [] if LX.SEG_URI_RE.match(str(s.get("uri") or ""))]
            if not segs:
                raise ArchiveError("録画に音を取れる所がないので、アーカイブと時刻を合わせられません")
            sess = segs[0]["session"]
            segs = [s for s in segs if s.get("session") == sess]   # つなぎ直しをまたがない(最初のセッションの分だけ)
            files = self.ex._fetch(job, rco, rec, segs, wdir)
            s0 = LX.iso_epoch(segs[0].get("pdt"))
            have = sum(float(s.get("dur") or 0) for s in segs)
            ss = max(0.0, ra - s0) if s0 is not None else 0.0
            use = min(span, have - ss)
            if use < 5.0:
                raise ArchiveError("録画に続けて取れる音が短すぎるので、アーカイブと時刻を合わせられません")
            ref = self._wav(files[0][0], os.path.join(wdir, "ref.wav"), ss, use, job)
            full = self._full_audio(job, vid)
            est = (s0 + ss if s0 is not None else ra) - t0
            w0, _w1, r = self._search(job, ref, full, est, use, WINDOWS_FIRST, wdir)
            if w0 is None:
                raise ArchiveError("録画の音とアーカイブの音が合いませんでした(%s)。アーカイブが切り貼りされたか、別の配信かもしれません" % r)
            return w0 + float(r["offset"]) - est, "録画の音をアーカイブと照合"
        finally:
            shutil.rmtree(wdir, ignore_errors=True)

    def _after_analyze(self, rc, rec, a):
        """スタジオの解析の進み具合を見る。済めば採用へ"""
        code, d = self.studio("GET", "/api/queue", None)
        if code is None:
            return False   # スタジオが止まっている: 次の見回りで
        items = (d or {}).get("items") or [] if code == 200 and isinstance(d, dict) else []
        it = next((x for x in items if isinstance(x, dict) and (x.get("qid") == a.get("qid") if a.get("qid") else x.get("videoId") == a.get("vid"))), None)
        if it is None:
            _code, v = self._studio_video(a.get("vid") or "")
            if v is not None and v.get("analysis"):
                return self._after_adopt(rc, rec, a)
            raise ArchiveError("アーカイブの解析がスタジオの順番から消えました(スタジオを起動し直したかもしれません)")
        if it.get("status") == "done":
            return self._after_adopt(rc, rec, a)
        if it.get("status") in ("error", "cancelled", "skipped"):
            raise ArchiveError("アーカイブの解析が終わりませんでした: %s" % (it.get("error") or it.get("status")))
        msg = "アーカイブを解析しています(%s %d%%)" % (it.get("phase") or "", round((it.get("progress") or 0) * 100))
        if msg != a.get("message"):
            with self.lock:   # 進み具合は archive.json に書かない(見回りのたびに変わる)
                i = self.info.get(self.key(rc, rec)) or {}
                if isinstance(i.get("afterStream"), dict):
                    i["afterStream"] = dict(i["afterStream"], message=msg)
        return False

    def _studio_video(self, vid):
        """スタジオの GET /api/video?id=<vid> -> (HTTP の状態, video の dict か None(つながらない・無い・形が違う))"""
        code, d = self.studio("GET", "/api/video?id=" + urllib.parse.quote(vid), None)
        v = d.get("video") if code == 200 and isinstance(d, dict) else None
        return code, v if isinstance(v, dict) else None

    def _after_adopt(self, rc, rec, a):
        """候補から上位 N を選び、M1 の採用(origin archive)を 1 本ずつ頼む"""
        if self.adopt is None:
            raise ArchiveError("採用の仕組み(M1)が使えません")
        code, v = self._studio_video(a["vid"])
        if v is None:
            raise Later("スタジオからアーカイブの解析の結果を読めませんでした(HTTP %s)" % code, self.retry_sec)
        marks = v.get("marks") or []
        if self.compare is not None:   # 配信中の候補(L2)とアーカイブの候補を比べて live_feedback.jsonl へ(0-10-6。失敗しても採用は続ける)
            try:
                self.compare(rc, rec, a, marks)
            except Exception as e:
                self.log("リアルタイム切り抜き: 配信中の候補とアーカイブの候補を比べられませんでした: %r" % (e,))
        _code, lv = self._studio_video(rec)
        taken = []
        if lv is not None:   # 録画の配信の、もう採用・書き出し済みのマーク(人が付けたもの)と重ねない
            for m in lv.get("marks") or []:
                if isinstance(m, dict) and m.get("status") in ("adopted", "exported") and isinstance(m.get("start"), (int, float)) and isinstance(m.get("end"), (int, float)):
                    taken.append((a["first"] + m["start"], a["first"] + m["end"]))
        picked = pick_candidates(marks, a["n"], a["t0"], a["offset"], a["first"], a["last"] - LX.READY_PAD, taken)
        cands = sum(1 for m in marks if isinstance(m, dict) and m.get("src") == "auto")
        if not picked:
            self._after_set(rc, rec, state="none", jobs=[], picked=[],
                            message="録画の範囲に採用できる候補がありませんでした(アーカイブの候補 %d 件・録画の範囲 %d 秒)" % (cands, int(a["last"] - a["first"])))
            return True
        jobs_, done, errs = [], [], []
        for k, (x, y, m) in enumerate(picked, 1):
            label = (m.get("label") or "").strip() or "アーカイブの山 %d" % k
            body = {"recorder": rc, "recording": rec, "start": LX.epoch_iso(x), "end": LX.epoch_iso(y), "label": label[:LX.LABEL_MAX],
                    "origin": "archive", "after": AFTER_FLOW}
            try:
                res = self.adopt(body, hold="archive")
            except LX.LiveError as e:
                errs.append(str(e)[:160])
                continue
            j = (res or {}).get("job") or {}
            if j.get("id"):
                jobs_.append(j["id"])
            done.append({"start": round(x - a["first"], 3), "end": round(y - a["first"], 3), "score": m.get("score"), "archiveStart": m.get("start"),
                         "existing": bool((res or {}).get("existing"))})
        if not jobs_:
            raise ArchiveError("自動で採用できませんでした: %s" % (errs[0] if errs else "理由は分かりません"))
        self._after_set(rc, rec, state="export", jobs=jobs_, picked=done, skipped=errs,
                        message="%d 本を採用しました(アーカイブの解析の上位)。書き出し → 本番版 → 文字起こし → パック" % len(jobs_) +
                        ("(%d 本は採用できませんでした: %s)" % (len(errs), errs[0]) if errs else ""))
        self.log("リアルタイム切り抜き: 配信後の自動の切り抜き: %s で %d 本を採用しました(origin archive)" % (rec, len(jobs_)))
        return True

    def _after_follow(self, rc, rec, a):
        """採用したジョブを見届ける: 書き出せたら本番版への作り直しに入れる(設定 live.autoArchive がオフでも)・全部が済んだら done"""
        with self.ex.lock:
            js = {j["id"]: j for j in self.ex.jobs if j.get("id") in (a.get("jobs") or [])}
        todo, waiting = [], 0
        for jid in a.get("jobs") or []:
            j = js.get(jid)
            if j is None:
                continue
            arc = j.get("archive") or {}
            if j.get("state") in LX.ACTIVE or arc.get("state") in ACTIVE:
                waiting += 1
            elif (j.get("state") == "done" or (j.get("state") == "error" and j.get("needsArchive"))) and not arc:
                todo.append(j)
                waiting += 1
            elif j.get("state") == "done" and j.get("handoffWait") == "archive" and arc.get("state") in ("error", "cancelled"):
                self.ex.release_hold(j, "本番版にできなかったので、速報版のまま文字起こし・パックへ渡しました(%s)" % str(arc.get("message") or "")[:160])
                waiting += 1 if j.get("handoffWait") else 0
            elif j.get("state") == "done" and j.get("handoffWait"):
                waiting += 1   # 空き待ち(M4)
        if todo:
            self._queue(todo, auto=True)
        if waiting:
            return bool(todo)
        handed = sum(1 for jid in a.get("jobs") or [] if (js.get(jid) or {}).get("runId"))
        bad = [live_failures.failure_of(js[jid]) for jid in a.get("jobs") or [] if jid in js]
        bad = [f for f in bad if f]
        self._after_set(rc, rec, state="done", message="%d 本のうち %d 本を文字起こし → パックへ渡しました" % (len(a.get("jobs") or []), handed) +
                        ("(失敗 %d 本。「調子」の失敗の一覧に出ます)" % len(bad) if bad else ""))
        self.log("リアルタイム切り抜き: 配信後の自動の切り抜きが済みました %s(%d 本を渡しました)" % (rec, handed))
        if self.after:
            try:
                self.after(rc, rec)   # 全部入れ替わっていれば録画を消す(P4。消すのを待っていた = after_stream_hold)
            except Exception:
                pass
        return True

    def after_stream_hold(self, rc, r):
        """録画を自動で消すのを待つ理由(src/manage/keep/live_cleanup.py から。r = 録画元の一覧の 1 行)。待たなくてよければ ""。
        配信後の全自動がオン(友人の依頼の録画は依頼の afterStream。2-15)で、その録画がまだ済んでいない(終わって AFTER_MAX_AGE 以内・YouTube の動画が分かる)間は消さない"""
        if not self.enabled() or not isinstance(r, dict):
            return ""
        rec = str(r.get("id") or "")
        if not self._after_on(rc, rec):
            return ""
        if self._after_get(rc, rec).get("state") in AFTER_END:
            return ""
        ended = ended_at(r)
        if ended is not None and time.time() - ended > self.after_max_age:
            return ""
        if not LX.video_id_of(str(r.get("url") or ""), rec):
            return ""
        return "配信後の自動の切り抜き(アーカイブの解析)がまだです"

    def after_failures(self, now=None):
        """配信後の全自動の失敗(「調子」の失敗の一覧に足す。文は src/flow/live_failures.py の after_stream_failure)"""
        now = time.time() if now is None else now
        with self.lock:
            items = [dict(i) for i in self.info.values()]
        out = []
        for i in items:
            f = live_failures.after_stream_failure(i)
            at = (i.get("afterStream") or {}).get("at") or ""
            t = LX.iso_epoch(at)
            if f is None or (t is not None and now - t > live_failures.WINDOW_SEC):
                continue
            out.append(dict(f, jobId="", recorder=i.get("recorder"), recording=i.get("recording"), markId="", runId="", at=at))
        return out

    # --- 1本 ---
    def _stop(self, job):
        if self._halt.is_set():
            raise LX.Halted()
        if job["id"] in self._cancel:
            raise LX.Cancelled()

    def _process(self, job):
        rc, rec = job["recorder"], job["recording"]
        wdir = os.path.join(self.ex.work, "archive-" + job["id"])
        tdir = None
        keep_build = False
        try:
            if self.ex._disk_low():   # 空きが少ない(M4): 作り直し(書き出し先へ書く・アーカイブの丸ごとの音)も空くまで待つ
                raise Later(self.ex.disk()["message"], LX.DISK_POLL)
            self._aset(job, state="probe", message="アーカイブを確かめています", progress=0.02, retryAt=None)
            info = self._ready_info(rc, rec)
            if info.get("ready") is not True:
                raise Later(info.get("message") or "アーカイブがまだ用意できていません", self.interval)
            vid = info.get("videoId") or ""
            if not LX.YT_ID_RE.match(vid):
                raise ArchiveError("YouTube の動画が分からない録画なので、アーカイブで作り直せません")
            t0 = info.get("release")   # timestamp は配信の終わりごろ(数時間ずれる)なので使わない
            if not isinstance(t0, (int, float)):
                raise ArchiveError("開始時刻が分からないので照合できません")
            a, b = LX.iso_epoch(job.get("start")), LX.iso_epoch(job.get("end"))
            if a is None or b is None or b <= a:
                raise ArchiveError("マークの時刻が正しくありません")
            est, dur = a - t0, b - a
            speed = self._speed_file(job)
            root = self.ex.out_dir()
            if speed:
                folder, base, title = os.path.dirname(speed), os.path.splitext(os.path.basename(speed))[0], None
            else:
                d = self._rec_meta(job)
                folder, base, title = self.ex.target(job, d, rec, a, b)
            tdir = os.path.join(folder, schemas.WORK_DIR, BUILD_DIR, job["id"])
            if not inside(tdir, root):
                raise ArchiveError("書き出し先の外には書けません")
            tmp = os.path.join(tdir, base + ".mp4")
            arc = job.get("archive") or {}
            built = arc.get("built")
            if built and os.path.normcase(built) == os.path.normcase(tmp) and os.path.isfile(tmp) and isinstance(arc.get("archiveStart"), (int, float)):
                ast, res = arc["archiveStart"], arc.get("residual")   # 前に作って、使用中で入れ替えられなかった本番版
                out = self._check_media(tmp, dur)
            else:
                shutil.rmtree(tdir, ignore_errors=True)
                os.makedirs(tdir, exist_ok=True)
                if speed:
                    self._aset(job, state="align", message="アーカイブの音と速報版の音を照合しています", progress=0.05)
                    ast = self._align(job, speed, vid, est, wdir)
                else:
                    off = self._nearest_offset(job)
                    ast = est + off
                    self._aset(job, offset=round(off, 3))
                ast, res, out = self._build(job, vid, ast, dur, speed, tmp, wdir)
            self._aset(job, built=tmp, archiveStart=round(ast, 3), archiveEnd=round(ast + dur, 3), residual=res)
            meta = {"videoId": vid, "start": round(ast, 3), "end": round(ast + dur, 3), "offset": (job.get("archive") or {}).get("offset"),
                    "residual": res, "at": LX.now_iso()}
            keep_build = True   # ここから先で使用中なら、作った本番版を残して入れ替えだけやり直す
            if speed:
                kept = self._swap(job, speed, tmp, folder)
                self._update_clip(speed, out, meta)
                try:   # 前に作った Resolve のパック(動画の写しを入れる)は速報版のまま。作り直すと本番版になることを知らせる
                    pack = self.pack_info(speed)
                except Exception:
                    pack = None
                self._aset(job, state="done", progress=1.0, at=meta["at"], built=None, keep=kept, packOld=bool(pack),
                           message="本番版にしました(速報版は 作業用\\%s へ)" % SPEED_DIR +
                           ("。前に作ったパックは速報版のままなので、「編集」の 3 パック のタブで作り直してください" if pack else ""))
                self.ex.release_hold(job)   # 本番版を待っていた受け渡し(M7): 本番版で文字起こし → パックへ
            else:
                final = os.path.join(folder, LX.unique_base(base, folder) + ".mp4")
                self._aset(job, state="verify", message="本番版を置いています")
                fsio.replace_retry(tmp, final)
                d = self._rec_meta(job)
                self.ex._finish(job, {"id": rc}, rec, d, dict(out, path=final, title=title or self.ex._title(job, d)), a, b,
                                archive=meta, message="アーカイブから書き出しました")
                with self.ex.lock:
                    job.update(needsArchive=False, error="")
                self._aset(job, state="done", message="アーカイブから本番版を書き出しました", progress=1.0, at=meta["at"], built=None)
            keep_build = False
            self.log("リアルタイム切り抜き: 本番版にしました %s(アーカイブの %.3f〜%.3f 秒・ずれ %s)" % (job.get("path"), ast, ast + dur, res))
        except LX.Cancelled:
            keep_build = False
            self._aset(job, state="cancelled", message="取り消しました(速報版のままです)", progress=0, built=None)
        except LX.Halted:
            self._aset(job, state="wait", message="ホームを終えたので、次の起動で続けます", progress=0)
        except Later as e:
            after = e.after if e.after is not None else self.retry_sec
            self._aset(job, state="wait", message=str(e), progress=0, retryAt=time.time() + after)
        except (LX.LiveError, normalize.NormalizeError) as e:
            keep_build = False
            self._aset(job, state="error", message=str(e), progress=0, built=None)
        except OSError as e:
            keep_build = False
            self._aset(job, state="error", message="書けませんでした: %s" % tools.why(e), progress=0, built=None)
        except Exception as e:
            keep_build = False
            self.log("リアルタイム切り抜き: 本番版への作り直しでエラー %r" % (e,))
            self._aset(job, state="error", message="内部エラー: %s" % e.__class__.__name__, progress=0, built=None)
        finally:
            self._cancel.discard(job["id"])
            self._probes.clear()   # 速報版は入れ替えたかもしれない・次の作り直しは別の速報版
            arc = job.get("archive") or {}
            if job.get("handoffWait") == "archive" and arc.get("state") in ("error", "cancelled"):   # 本番版にできなかった(M7): 速報版のまま渡す
                self.ex.release_hold(job, "本番版にできなかったので、速報版のまま文字起こし・パックへ渡しました(%s)" % str(arc.get("message") or "")[:160])
            shutil.rmtree(wdir, ignore_errors=True)
            if tdir and not keep_build:
                shutil.rmtree(tdir, ignore_errors=True)
                for p in (os.path.dirname(tdir), os.path.dirname(os.path.dirname(tdir))):   # 空になった 本番版の作りかけ・作業用 は消す(中身があれば消えない)
                    try:
                        os.rmdir(p)
                    except OSError:
                        break

    def _speed_file(self, job):
        """入れ替える相手 = このジョブが自分で書き出した path だけ(書き出し先の中・.mp4・実在)。欠けのマークは None"""
        if job.get("state") != "done":
            return None
        p = job.get("path")
        if not isinstance(p, str) or not p.lower().endswith(".mp4") or not os.path.isabs(p) or not inside(p, self.ex.out_dir()):
            raise ArchiveError("速報版の場所が書き出し先の中ではないので、入れ替えません")
        if not os.path.isfile(p):
            raise ArchiveError("速報版のファイルが見つかりません(動かしたか消したかもしれません)")
        return p

    def _rec_meta(self, job):
        """欠けのマークを新しく作るときの録画の情報 {url, title, firstPdt}(名前と .clip.json の range の 0 秒)。
        録画の頭の時刻は ジョブの recBase → スタジオのマークの秒から逆算 → マークの開始(range が 0 から)"""
        try:
            mk = self.ex.marks.load(job["recorder"], job["recording"])
        except LX.LiveError:
            mk = {}
        base = LX.iso_epoch(job.get("recBase"))
        st = job.get("studio") if isinstance(job.get("studio"), dict) else {}
        a = LX.iso_epoch(job.get("start"))
        if base is None and isinstance(st.get("start"), (int, float)) and a is not None:
            base = a - st["start"]
        return {"url": mk.get("url") or "", "title": mk.get("title") or "", "firstPdt": LX.epoch_iso(base) if base is not None else None}

    def _nearest_offset(self, job, need=True, same_video=False):
        """同じ録画の、照合が済んだマークのずれのうち、時刻がいちばん近いもの(前にあるものを先に = 欠けをまたぐマークの頭は欠けの前の
        セッションにあり、つなぎ直すとずれが 1 秒ほど変わるため。2026-10-05 の通しの確認で 0.73 秒)。無ければ need なら ArchiveError(照合を待つものがあれば Later)。
        same_video: 同じ録画に無ければ、同じ配信(videoId)の別の録画のジョブからも探す(照合の窓の見当だけに使う。本物の配信で 2 本の録画の差は 1.24 秒 =
        ±20 秒の窓に収まる。欠けのマークの時刻そのものには使わない = 録画が違うと 1 秒ほどずれる)"""
        a = LX.iso_epoch(job.get("start")) or 0
        best = None
        pending = False
        vid = self._vid_of(job) if same_video else ""
        with self.ex.lock:
            pool = [j for j in self.ex.jobs if j is not job and (
                (j.get("recorder") == job.get("recorder") and j.get("recording") == job.get("recording"))
                or (vid and (j.get("archive") or {}).get("aligned") and self._vid_of(j) == vid))]
        for j in pool:
            arc = j.get("archive") or {}
            same = j.get("recorder") == job.get("recorder") and j.get("recording") == job.get("recording")
            if arc.get("aligned") and isinstance(arc.get("offset"), (int, float)):
                s = LX.iso_epoch(j.get("start")) or 0
                d = (0 if same else 1, 0 if s <= a + 0.001 else 1, abs(s - a))   # 同じ録画 → 前にあるもの → 近いもの
                if best is None or d < best[0]:
                    best = (d, arc["offset"])
            elif same and j.get("state") == "done" and arc.get("state") in ACTIVE:
                pending = True
        if best is not None:
            return best[1]
        if not need:
            return None
        if pending:
            raise Later("同じ録画のほかのマークの照合を待っています", self.poll)
        raise ArchiveError("速報版が無く、同じ録画に照合できたマークも無いので、アーカイブの時刻を合わせられません")

    def _wav(self, src, dst, ss=None, t=None, job=None):
        """ffmpeg で 8kHz・モノラル・16bit の WAV にする(照合の子プロセスが読む形)"""
        ff = self.ffmpeg or tools.find_tool("ffmpeg", "YTT_FFMPEG")
        if not ff:
            raise ArchiveError("ffmpeg が見つかりません")
        cmd = [ff, "-hide_banner", "-nostdin", "-y", "-v", "error"]
        # 入力側の -ss だけだと、AAC(m4a・mp4)は 13ms ほどずれ、頭の音も崩れる(2026-10-05 に測った。opus は 1ms)。
        # PRE_SEEK 秒手前まで入力側で飛び、残りは出力側で(デコードして)切る = サンプル単位で正確
        pre = max(0.0, (ss or 0.0) - PRE_SEEK)
        if pre > 0:
            cmd += ["-ss", "%.3f" % pre]
        cmd += ["-i", src]
        if ss and ss - pre > 0:
            cmd += ["-ss", "%.3f" % (ss - pre)]
        if t:
            cmd += ["-t", "%.3f" % t]
        cmd += ["-vn", "-sn", "-dn", "-ac", "1", "-ar", "8000", "-c:a", "pcm_s16le", "-f", "wav", dst]
        code, _o, tail = run_proc(cmd, FFMPEG_TIMEOUT, (lambda: job["id"] in self._cancel or self._halt.is_set()) if job else None)
        if code != 0 or not os.path.isfile(dst):
            raise ArchiveError("音を取り出せませんでした(%s)" % (" / ".join(tail) or "終了コード %s" % code))
        return dst

    def _probe_speed(self, speed):
        """速報版の ffprobe の結果(読めなければ {})。同じ作り直しの中で何度も呼ぶので、更新日時と大きさが同じなら前の結果を使う"""
        return self._probes.get(speed, lambda p: normalize.probe(p, self.ffprobe)) or {}

    def _ref_span(self, dur):
        """照合に使う速報版の区間 (頭から除く秒, 長さ)。頭と終わりの端(作り直しの端の揺れ)を少し外す"""
        trim = min(1.0, dur * 0.2)
        return trim, max(0.3, min(REF_MAX, dur - 2 * trim))

    def _align(self, job, speed, vid, est, wdir):
        """速報版の音をアーカイブの窓の音と照合する -> 速報版の頭のアーカイブの秒。ずれ(offset)と aligned を archive に残す"""
        os.makedirs(wdir, exist_ok=True)
        info = self._probe_speed(speed)
        a, b = LX.iso_epoch(job["start"]), LX.iso_epoch(job["end"])
        dur = info.get("duration") or (b - a)
        trim, span = self._ref_span(dur)
        ref = self._wav(speed, os.path.join(wdir, "ref.wav"), trim, span, job)
        prev = self._nearest_offset(job, need=False, same_video=True)   # 同じ配信の別の録画の照合も見当に使う
        center = est + (prev or 0.0)
        full = self._full_audio(job, vid)
        w0, w1, r = self._search(job, ref, full, center, trim + span, WINDOWS_NEXT if prev is not None else WINDOWS_FIRST, wdir, talk=True)
        if w0 is None:
            raise ArchiveError("アーカイブの音と速報版の音が合いませんでした(%s)。アーカイブが切り貼りされたか、別の配信かもしれないので、速報版のままにします" % r)
        ast = w0 + float(r["offset"]) - trim
        self._aset(job, offset=round(ast - est, 3), aligned=True, score=r.get("score"), ratio=r.get("ratio"), window=[round(w0, 3), round(w1, 3)])
        return ast

    def _search(self, job, ref, full, center, span, windows, wdir, talk=False):
        """アーカイブの丸ごとの音 full から、見当 center の前後 w 秒(windows の順に広げる)の窓を切り出して ref と照合する
        (窓の決め方・しきい値は P4 の作り直しと M7 の時刻合わせで同じ)。talk = 進み具合をジョブの archive に出す(P4)。
        -> (窓の頭の秒, 窓の終わりの秒, 照合の結果)。どの窓でも合わなければ (None, None, 最後の理由の文)"""
        why = ""
        for n, w in enumerate(windows):
            self._stop(job)
            w0, w1 = max(0.0, center - w), center + span + w
            if talk:
                self._aset(job, message="アーカイブの音を切り出しています(見当の前後 %d 秒)" % int(w), progress=0.05 + 0.05 * n)
            win = self._wav(full, os.path.join(wdir, "window.wav"), w0, w1 - w0, job=job)   # 手前まで入力側の -ss・残りはデコードして切る(_wav。サンプル単位で正確)
            self._stop(job)
            if talk:
                self._aset(job, message="照合しています(見当の前後 %d 秒)" % int(w))
            r = self.align(ref, win) or {}
            fsio.unlink_quiet(win)
            if r.get("ok") and (r.get("score") or 0) >= MIN_SCORE and (r.get("ratio") or 0) >= MIN_RATIO:
                return w0, w1, r
            why = r.get("reason") if not r.get("ok") else "確かさ %.2f・%.1f 倍" % (r.get("score") or 0, r.get("ratio") or 0)
        return None, None, why

    def _audio(self, speed, job=None):
        """スタジオに頼む音量(速報版と同じ扱い): 速報版の .clip.json の export に残した値 → 無ければ今の書き出しの設定(studio_audio)"""
        vol, loud = self.ex._audio_cfg(job)   # 速報版のジョブの録画に束があれば束の音量(RS7-2 G2b)
        if speed:
            p = schemas.find_clip_path(speed)
            c, _w = schemas.load_clip_file(p) if p else (None, None)
            ex = (c or {}).get("export") or {}
            lo = ex.get("loudness") if isinstance(ex.get("loudness"), dict) else None
            if lo and isinstance(lo.get("target"), (int, float)):
                return 100, float(lo["target"])
            if isinstance(ex.get("volume"), (int, float)) and not isinstance(ex.get("volume"), bool):
                return int(ex["volume"]), None
        return vol, loud

    def _check_media(self, path, dur):
        """作り直した本番版が 30fps で、長さが区間と LEN_TOL 以内か(ytt.normalize.verify)。-> probe の結果"""
        return normalize.verify(path, dur, LX.LEN_TOL, self.ffprobe, what="作り直した本番版", ref="区間", got="動画", error=ArchiveError)

    def _build(self, job, vid, ast, dur, speed, tmp, wdir):
        """スタジオで作り直して確かめる(速報版との音のずれが 1 コマを超えたら、1回だけずれを足して作り直す)。-> (アーカイブの秒, ずれ, probe の結果)"""
        height = 0
        if speed:
            h = self._probe_speed(speed).get("height")
            height = h if h in HEIGHTS else 0   # 速報版と同じ高さ(文字起こし・カット・パックの見た目を変えない)
        vol, loud = self._audio(speed, job)
        for attempt in (0, 1):
            self._stop(job)
            fsio.unlink_quiet(tmp)
            self._aset(job, state="fetch", message="アーカイブから取って 30fps に作り直しています(スタジオの書き出し)", progress=0.15, archiveStart=round(ast, 3))
            item = self._section(job, vid, ast, ast + dur, tmp, height, vol, loud)
            self._aset(job, state="verify", message="作り直した本番版を確かめています", progress=0.9)
            if not os.path.isfile(tmp):
                raise ArchiveError("スタジオの書き出しが済んだのに、本番版のファイルがありません")
            out = self._check_media(tmp, dur)
            out["audio"] = {"loudness": item.get("loudness")} if loud and isinstance(item.get("loudness"), dict) else \
                {"loudness": {"target": loud}} if loud else {"volume": vol}
            if not speed:
                return ast, None, out
            res = self._residual(job, speed, tmp, wdir)
            if abs(res) <= FRAME_TOL:
                return ast, round(res, 4), out
            if attempt == 0:
                self.log("リアルタイム切り抜き: 本番版と速報版の音が %.3f 秒ずれたので、足して作り直します" % res)
                ast += res
                continue
            raise ArchiveError("作り直した本番版と速報版の音が %.3f 秒ずれています(1 コマ %.3f 秒より大きい)。速報版のままにします" % (res, FRAME_TOL))
        raise AssertionError("not reached")

    def _residual(self, job, speed, new, wdir):
        """本番版と速報版の音のずれ(秒。正 = 本番版の頭が早すぎる = アーカイブの開始を足す)"""
        os.makedirs(wdir, exist_ok=True)
        dur = self._probe_speed(speed).get("duration") or 1.0
        trim, span = self._ref_span(dur)
        ref = self._wav(speed, os.path.join(wdir, "vref.wav"), trim, span, job)
        win = self._wav(new, os.path.join(wdir, "vnew.wav"), job=job)
        r = self.align(ref, win) or {}
        if not r.get("ok") or (r.get("score") or 0) < MIN_SCORE:
            raise ArchiveError("作り直した本番版の音を速報版と照合できませんでした(%s)。速報版のままにします"
                               % (r.get("reason") or "確かさ %.2f" % (r.get("score") or 0)))
        return float(r["offset"]) - trim

    def _section(self, job, vid, start, end, path, height, vol, loud):
        """スタジオの POST api/live/section で作り直してもらい、済むまで待つ。-> スタジオの書き出しの item"""
        body = {"videoId": vid, "start": round(start, 3), "end": round(end, 3), "path": path, "volume": vol, "loudness": loud,
                "maxHeight": height, "precision": "accurate"}
        down = None
        while True:   # スタジオの書き出しは同時に 1 本だけ: ほかが動いていれば 409 busy → 失敗にせず、待ってやり直す
            self._stop(job)
            code, d = self.studio("POST", "/api/live/section", body)
            if code == 409 and isinstance(d, dict) and d.get("error") == "busy":
                self._aset(job, save=False, message="スタジオの書き出しが終わるのを待っています")
                self._halt.wait(max(self.step, 1.0) * 3)
                continue
            if code is None:
                down = down or time.time()
                if time.time() - down > STUDIO_DOWN:
                    raise ArchiveError("スタジオに %d 秒つながりませんでした(%s)" % (int(STUDIO_DOWN), (d or {}).get("message") or ""))
                self._halt.wait(max(self.step, 1.0) * 3)
                continue
            break
        if code != 200 or not isinstance(d, dict) or not isinstance(d.get("id"), str):
            msg = d.get("message") if isinstance(d, dict) else ""
            raise ArchiveError("スタジオで作り直しを始められませんでした: %s" % (msg or "HTTP %s" % code))
        sid, down = d["id"], None
        while True:
            try:
                self._stop(job)
            except (LX.Cancelled, LX.Halted):
                try:
                    self.studio("POST", "/api/export/cancel", {"id": sid})
                except Exception:
                    pass
                raise
            code, d = self.studio("GET", "/api/export?id=" + urllib.parse.quote(sid), None)
            if code is None:
                down = down or time.time()
                if time.time() - down > STUDIO_DOWN:
                    raise ArchiveError("スタジオに %d 秒つながりませんでした" % int(STUDIO_DOWN))
            elif code == 404:
                raise ArchiveError("スタジオの書き出しが見つかりません(スタジオを起動し直したかもしれません)")
            elif code == 200 and isinstance(d, dict):
                down = None
                items = d.get("items") or [{}]
                it = items[0] if isinstance(items[0], dict) else {}
                p = it.get("progress")
                if isinstance(p, (int, float)) and not isinstance(p, bool):
                    self._aset(job, save=False, progress=round(0.15 + 0.7 * max(0.0, min(1.0, p)), 3))
                if d.get("waiting"):
                    self._aset(job, save=False, message="ほかの重い処理が終わるのを待っています(スタジオの書き出し)")
                st = d.get("state")
                if st == "done":
                    if it.get("status") not in (None, "done"):
                        raise ArchiveError("スタジオの書き出しに失敗しました: %s" % (it.get("error") or it.get("status")))
                    return it
                if st in ("error", "cancelled"):
                    raise ArchiveError("スタジオの書き出しに失敗しました: %s" % (it.get("error") or ("取り消されました" if st == "cancelled" else "理由は分かりません")))
            else:
                raise ArchiveError("スタジオから思わぬ応答がありました(HTTP %s)" % code)
            self._halt.wait(self.step)

    def _swap(self, job, speed, built, folder):
        """速報版を 作業用\\速報版\\ へ移し、本番版を元の名前へ。使用中なら Later(作った本番版は残す)。-> 退避した速報版のパス"""
        self._aset(job, state="verify", message="速報版と入れ替えています", progress=0.95)
        if job.get("path") != speed or not os.path.isfile(speed):   # 念のため: 入れ替える相手はこのジョブが書き出した path だけ
            raise ArchiveError("速報版のファイルが見つかりません(動かしたか消したかもしれません)")
        kdir = os.path.join(folder, schemas.WORK_DIR, SPEED_DIR)
        if not inside(kdir, self.ex.out_dir()):
            raise ArchiveError("書き出し先の外には書けません")
        os.makedirs(kdir, exist_ok=True)
        kept = free_name(kdir, os.path.basename(speed))
        try:
            fsio.replace_retry(speed, kept)
        except PermissionError:
            raise Later("速報版の動画がほかのソフトで開かれているので、入れ替えられませんでした。閉じたあとの見回りで入れ替えます")
        try:
            fsio.replace_retry(built, speed)
        except OSError:
            try:
                fsio.replace_retry(kept, speed)   # 元へ戻す
            except OSError as e:
                self.log("リアルタイム切り抜き: 速報版を元の場所へ戻せませんでした(%s → %s): %s" % (kept, speed, e))
                raise ArchiveError("本番版を置けず、速報版も元へ戻せませんでした(速報版は %s にあります)" % kept)
            raise Later("動画を入れ替えられませんでした(ほかのソフトが使っているかもしれません)。あとの見回りでやり直します")
        return kept

    @staticmethod
    def _archive_key(media, meta):
        """F-1: 速報版を本番版に入れ替えたので、export の鍵を媒体 = archive(videoId)・区間 = アーカイブの秒で書き直す。書けなければ古い鍵(録画のまま)を消す"""
        kp = _keys.media_key_path(media, "export")
        old = _keys.read(kp, "export")
        settings = ((old or {}).get("inputs") or {}).get("settings") or {}
        try:
            ok = _keys.write_export(media, schemas.media_identity("archive", videoId=str(meta.get("videoId") or "")), meta["start"], meta["end"], settings)
        except (KeyError, TypeError, ValueError):
            ok = False
        if not ok:
            _keys.remove(kp)

    def _update_clip(self, media, out, meta):
        """.clip.json の source.live.archive・長さ・export.from を直す(range はそのまま = 録画の頭からの秒。文字起こし・カットの時刻は変わらない)"""
        self._archive_key(media, meta)
        p = schemas.find_clip_path(media)
        if not p:
            return
        try:
            c = fsio.read_json_file(p, schemas.MAX_CLIP_BYTES)
            if not isinstance(c, dict):
                return
            if not isinstance(c.get("source"), dict):
                c["source"] = {}
            src = c["source"]
            live = src.get("live") if isinstance(src.get("live"), dict) else {}
            src["live"] = dict(live, archive=dict(meta))
            if isinstance(c.get("media"), dict) and out.get("duration") is not None:
                c["media"]["durationSec"] = round(float(out["duration"]), 3)
            if isinstance(c.get("export"), dict):
                c["export"]["from"] = "youtube-archive"
            fsio.write_json(p, c)
        except (OSError, ValueError) as e:
            self.log("リアルタイム切り抜き: .clip.json に本番版のことを書けませんでした %s: %s" % (p, e))
