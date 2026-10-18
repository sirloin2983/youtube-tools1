# -*- coding: utf-8 -*-
"""録画に無い区間をアーカイブ(YouTube)から書き出す(線 D の P4 の残り。notes:plan/line-d-live-clipping.md の 0-9)と、配信後の全自動(M7)の入口の側の中身。
API は src/app/live.py(設定 live.enabled がオンのときだけ)。

2026-10-16 の見直し(決定 3-73・notes:docs/design/friend-history.md の 7 章)で、録画から作った速報版を本番版に入れ替える(P4 の入れ替え)は廃止した。
材料: 10-05〜10-15 の 140 本で音のずれはほぼ 0 秒・友人へは配信中に速報版のパックで届いていて入れ替えても何も届かない。
P4 の本当の役目は「録画を消してよい合図」だったので、それは archived(アーカイブ化したかの確かめ)に置き換えた(録画を消すのは
src/manage/keep/live_cleanup.py。判断は src/flow/live_retire.py)。設定 live.autoArchive も消した(欠けのジョブは自動で必ずアーカイブから)。

単位は入口の書き出しのジョブ(src/flow/live_export.py の Exporter。live/exports.json)。ジョブに archive を足して残す(入口を起動し直しても続く):
  archive {state: wait|probe|align|fetch|verify|done|error|cancelled, label(日本語), message(失敗のときは理由), progress(0〜1),
           offset(マークの絶対時刻 − 配信の開始時刻 の見当から、照合で求めたアーカイブの秒までの差), offsetFrom(ずれの出どころ),
           archiveStart・archiveEnd(アーカイブの秒), at(済んだ時刻), auto(自動で始めた), aligned(録画の音で照合した = ほかのマークの見当に使える), retryAt}
  対象 = 録画1本の、マークごとの最新のジョブで、録画に無い区間のもの:
    error + needsArchive(欠け・止めていた間・録画が区間まで届かなかった)と、wait + from "archive"(M7 が採用した候補 = 最初からアーカイブから書き出す)。
  録画から書き出せたジョブ(done)は対象にしない(前の版で退避した速報版の片付けは live_cleanup が続ける)。

流れ(1本ずつ順に):
  1. probe  … yt-dlp で live_status(was_live = 用意できた / post_live・is_live = まだ)・配信の開始時刻 release_timestamp・長さ duration を取る
              (timestamp は配信の終わりごろの時刻で数時間ずれるので使わない。release_timestamp が無ければ照合できない)。
              録画1本ごとの結果は live/archive.json(画面の archiveInfo {ready, checkedAt, message})
  2. align  … 配信の音を丸ごと1回だけ yt-dlp で取り(-f ba = スタジオの書き出し bv*+ba と同じ音。2.5 時間の配信でも数秒)、入口の作業用
              live\\work\\audio-<videoId>\\ に置く(同じ配信のジョブで使い回す。その配信のジョブが無くなったら消す)。
              ずれ(録画の受信時刻 → アーカイブの秒)は、マークの頭の手前(同じセッション)の録画の音を最大 REF_SEC(60 秒)録画元から取って、
              丸ごとの音の窓と照合して求める(_rec_offset。録画を消したあとは使えない)。見当 = マークの絶対時刻 − 開始時刻。
              窓は最初 ±300 秒、確かさが低ければ ±900 秒で1回だけやり直す。2 本目からは前のずれの ±20 秒(だめなら広げる)。
              窓は丸ごとの音から ffmpeg で切り(10 秒手前まで入力側の -ss、残りはデコードして切る = サンプル単位で正確。入力側だけだと AAC で 13ms ずれた)、
              相互相関(8kHz・モノラル。numpy を使うので別プロセス src/pipeline/ingest/live_align_worker.py = 入口のプロセスでは numpy を import しない)。
              録画の音が取れない(マークが録画の終わりより後・録画が無い)ときは、同じ録画の照合できたマークのずれのうち前にある・近いもの、
              無ければ配信後の全自動(M7)が求めた録画のずれ(afterStream.offset)を使う。どれも無ければできない。
              2026-10-05 に本物の配信で確かめて変えた: yt-dlp の区間取得(--download-sections)は遅く(±600 秒で 570 秒)、m4a と opus で頭が 35ms ずれる /
              合わない区間で ratio 1.58 が出た(MIN_RATIO 3.0)/ yt-dlp の一時的な 403 は 30 秒あけて 2 回までやり直す
  3. fetch  … ② の書き出しの器 flow/export(区間の書き出し(部品)と同じ束 {videoId, start, end, path, volume, loudness, maxHeight,
              precision} = ① の build_section_spec。YouTube の書き出しの中身を使う。二重に書かない)を直に呼んで待つ。
              path は書き出し先の中の、まだ無い .mp4(<配信のフォルダ>\\作業用\\本番版の作りかけ\\<ジョブ>\\)
  4. verify … 30fps・長さ(区間 ±0.2 秒)
  5. 置く   … 新しい名前で書き出し先へ置き、job.state を done・path を入れる(Exporter._finish。.clip.json の source.live.archive {videoId, start, end, offset, at}・
              export.from "youtube-archive")。書き出したあとの流れ(文字起こし → パック)へはすぐ渡す。スタジオのマークは「書き出し済み」+ archived の札

重い処理の順番(ytt.jobs.SLOTS)を入口の側では取らない: 書き出し(いちばん重い)はスタジオの書き出しが自分で SLOTS を取る。入口がその間 SLOT を
持って待つと、上限 1(YTT_MAX_HEAVY_JOBS=1)では互いに待って止まり、上限 2 でも1つをむだに塞ぐ。入口の側の仕事は yt-dlp の取得(通信)・
ffmpeg で 8kHz の音にする(数秒)・照合(子プロセスで 1〜2 秒)だけで軽い。その代わり、自動で始めるのは SLOTS に実行中・順番待ちが無く、
書き出しのジョブも無いときだけにする。

自動(いつも): 録画が終わって FIRST_DELAY(30 分)後から INTERVAL(1 時間)ごとに用意を確かめ、GIVE_UP(7 日)でやめる。
録画が終わったかは録画元の /live/list(つながらなければジョブの時刻)。自動は、まだ一度も試していないマークだけ(失敗・取り消しは人が押して始める)。

アーカイブ化したか(archived。録画を消す判断 = src/flow/live_retire.py の Retire.verdict が聞く): 用意を確かめた結果が was_live・限定でない・
開始時刻と長さが分かり、アーカイブの終わり(開始 + 長さ)が録画の終わり − ARCHIVED_SLACK(900 秒)より後。確かめたのが INTERVAL より前なら確かめ直す。

できないもの: アーカイブが残らない・メンバー限定・非公開・配信者がアーカイブを切り貼りして音が合わない区間 → 書き出せない(理由を archive.message に出す)。

空き容量(線 D の M4): 書き出し先・live\\work の空きが 5 GB 未満(src/flow/live_export.py の DISK_LOW)なら、書き出しを始めずに待ちに戻す(Later)。

配信後の全自動(線 D の M7。設定 live.autoAfterStream 既定オフ・live.afterStreamPerHour 既定 6): 人が触らずにパックまで。
録画ごとの状態は archive.json の afterStream {state, label, message, at, vid, t0, offset, first, last, end, n, qid, jobs, picked, skipped, title}。
  wait     … 録画元の一覧(GET /live/list)で終わった録画のうち、終わって FIRST_DELAY(30 分)たち・AFTER_MAX_AGE(2 日)以内・YouTube の動画が分かるもの。
             アーカイブの用意(P4 と同じ確かめ方・同じ覚え方)を待つ
  (時刻)   … 録画の受信時刻とアーカイブの秒のずれ(offset。P4 と同じ向き)を決める: 同じ録画(無ければ同じ配信)の照合済みのマークがあればそのずれ、
             無ければ録画の真ん中あたりの REF_SEC(60 秒)の音を録画元から取って、アーカイブの丸ごとの音と照合する(P4 と同じ窓・同じしきい値・同じ子プロセス)
  analyze  … アーカイブ(kind youtube・videoId)をスタジオの今の解析にかける(POST /studio/api/queue/add。設定はスタジオで保存した解析の設定、
             候補の数 count は N の 2 倍まで増やす)。スタジオで解析済みならそれを使う。進み具合は GET /studio/api/queue
  (比べる) … 配信中の候補とアーカイブの候補を比べて live_feedback.jsonl へ(compare。src/flow/live_detect.py。EV-1: 録画の欠け(録画元の /segments の gaps)と
             検出が測っていない所は外して数える = _rec_holes が欠けを渡す)
  (採用)   … 候補(自動のマーク・判定前)を点数の高い順に、録画の頭から配信の終わり(end = アーカイブの終わり。2026-10-16 に録画の終わりから広げた)に
             入る(半分以上入るものは範囲に切り詰める)・録画の採用済みのマーク(マークの置き場から = taken)と重ならない上位 N を選び
             (N = 録画の長さ(時間)× 1 時間あたりの数。1〜30)、M1 の採用(src/app/live.py の Live.adopt。origin archive・after auto = 文字起こし → パック・
             hold archive = 録画からは書き出さず、最初からアーカイブから書き出す)を 1 本ずつ呼ぶ
  export   … 採用したジョブをアーカイブからの書き出しに入れ、全部が済む(渡した・失敗した)と done(n 本のうち渡した数・失敗の数)
  done・none(採用する候補が無かった)・measured(測るだけ = 下)・error(理由。「調子」の失敗に出す = src/flow/live_failures.py の after_stream_failure)
測るだけ(EV-1。2026-10-16。afterStream.mode "measure"): 配信後の全自動がオフの録画(友人の依頼の afterStream が偽も)でも、配信中の検出の記録
(peaks.json)がある録画は、アーカイブを解析して比べるところまで進めて measured にする(採用しない)。配信中の検出の精度を、配信後の追加が
オフの依頼でも測るため。止めるスイッチは環境変数 YTT_LIVE_MEASURE=off(解析の重さを避けたいとき)。
録画を自動で消す(src/manage/keep/live_cleanup.py)は、afterStream(測るだけも = 配信中の候補のファイルは録画と一緒に消える)が済むまで(AFTER_MAX_AGE まで)その録画を消さない(after_stream_hold)。
"""
import json
import os
import shutil
import threading
import time
import urllib.parse

from pipeline.export import exporter as _exporter   # 区間の書き出しの束を組む所は ① の 1 か所(OPT2 の J5)
from pipeline.transcribe import recognize as _recognize   # wav の引数を組む所は ① の 1 か所(OPT2)
from ytt import fsio, jobs, normalize, schemas, tools
from ytt.errors import ApiError
from . import export as _export   # 書き出しの器(プロセスに 1 つ。OPT2 の J5)
from . import live_failures   # 失敗の文は 1 か所。M3・M7
from . import live_export as LX

CODE_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "pipeline", "ingest")   # 子プロセスの道具は ① の置き場(pipeline/ingest)
WORKER = os.path.join(CODE_DIR, "live_align_worker.py")
SCHEMA = "ytt-live-archive/v1"
RUN = LX.ARCHIVE_RUN
ACTIVE = LX.ARCHIVE_ACTIVE
LABELS = {"wait": "待ち", "probe": "アーカイブを確かめ中", "align": "照合中", "fetch": "取得中", "verify": "検証中",
          "done": "本番版", "error": "失敗", "cancelled": "取り消し"}
# 確かさのしきい値(src/flow/tests/test_live_archive.py の合成の音で決めた。2026-10-05):
#   同じ音(AAC で作り直し・音量 60%・数十 ms ずらし)… score 0.99・ratio 17(60 秒の参照なら ratio は上限の 99)
#   別の音(周波数の動きとノイズの違う合成の音)… score 0.18・ratio 1.3
# 本物の配信はアーカイブ・速報版の両方で作り直しが重なり、BGM の繰り返しで 2 番目の山も高くなりやすいので、score は真ん中より下の 0.5、
# ratio は「別の音」の 1.3 より上の 1.5 にした(両方を満たしたときだけ使う)。
# 2026-10-05 に本物の配信 4 本で測った: 正しい区間は score 0.97〜0.999・ratio 4.7〜58、合わない区間で ratio 1.58 が出た(止めたのは score だけ)→ ratio は 3.0
MIN_SCORE = 0.5
MIN_RATIO = 3.0
ARCHIVED_SLACK = 900.0       # アーカイブ化したか: アーカイブの終わり(開始 + 長さ)がこれだけ録画の終わりより前でもよい(release_timestamp は数分ずれる)
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
AFTER_LABELS = {"wait": "アーカイブの用意を待っています", "analyze": "アーカイブを解析しています", "export": "アーカイブから書き出し → パック",
                "done": "済み", "none": "採用する候補がありませんでした", "measured": "配信中の検出を測りました", "error": "失敗"}
AFTER_END = ("done", "none", "measured", "error")
HOLE_CHUNK = 2 * 3600.0     # 録画の欠けを録画元に聞くときの 1 回の幅(録画の部品の /segments は 3 時間・5000 本まで)
# 掲示板(flow/board.py。RS8 の ② の口 S2): アーカイブからの書き出し・配信後の全自動の state -> 掲示板の state
BOARD_STATES = dict({s: "running" for s in RUN}, wait="queued", done="done", error="error", cancelled="cancelled")
AFTER_BOARD = {"wait": "queued", "analyze": "running", "export": "running", "done": "done", "none": "skipped", "measured": "done", "error": "error"}
AFTER_PREFIX = "as-"   # 掲示板の id「la:as-<録画元>.<録画>」= 配信後の全自動(録画 1 本)。それ以外の la: は書き出しのジョブの id
SPEED_DIR = "速報版"                      # 作業用/速報版/(前の版で入れ替えのときに退避した速報版。片付けは live_cleanup)
BUILD_DIR = "本番版の作りかけ"            # 作業用/本番版の作りかけ/<ジョブ>/(スタジオが書く先。済んだら消す。名前は前の版のまま)
UNAVAILABLE = ("subscriber_only", "premium_only", "needs_auth", "private")


CANCELLED_MSG = "取り消しました(アーカイブから書き出していません)"
NOT_ARCHIVED = "アーカイブ化をまだ確かめられていない"   # archived が返す理由の頭(src/flow/live_retire.py が 3 日の期限で消してよい理由に数える)


def from_archive(job):
    """M7 が採用した候補(録画からは書き出さず、最初からアーカイブから書き出す。live_export の Exporter.add の hold "archive")"""
    return job.get("from") == "archive"


def needs_archive(job):
    """アーカイブから書き出す対象か: 録画に無い区間で書き出せなかった(error + needsArchive)か、M7 の採用で待っている(wait + from archive)"""
    st = job.get("state")
    return (st == "error" and bool(job.get("needsArchive"))) or (st == "wait" and from_archive(job))


class ArchiveError(LX.LiveError):
    """アーカイブから書き出せない理由(archive.state = error・archive.message に出す)"""


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
    cmd = tools.ytdlp_print_cmd(yd, "https://www.youtube.com/watch?v=" + video_id,   # 調べ方は配信中か(livesession.probe_live)と同じ
                                "%(live_status)s\t%(release_timestamp)s\t%(timestamp)s\t%(duration)s\t%(availability)s")
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
    cmd = [yd, "--encoding", "utf-8"] + tools.ytdlp_auth_args() + ["--no-warnings", "--no-playlist", "--no-part", "--force-overwrites", "--no-progress",
           "-f", "ba", "-o", os.path.join(folder, "full.%(ext)s")]
    ff = tools.find_tool("ffmpeg")
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
    """照合の子プロセスの Python(入口と同じ = numpy が入っている Python)。窓の無い pythonw は標準出力を返せないことがあるので python.exe にする"""
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


# ---------- 配信後の全自動(M7)の決め方 ----------
def ended_at(r):
    """録画の一覧の行 r の「終わった時刻」(epoch 秒): endedAt、無ければ lastPdt(最後のセグメントの時刻)。分からなければ None。
    行の時刻の型は呼ぶ側で違う: after_tick は epoch(src/app/live.py の list_recordings)、after_stream_hold は録画の部品の生の行 = ISO の文字列
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
    候補 = 自動のマーク(src auto)で判定前(status が空)。点数の高い順に、範囲 [first, last](M7 は録画の頭から配信の終わり)に半分以上入るものを範囲に切り詰め、
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
    -> {"total": 採用した本数, "exported": 書き出し済み, "archived": アーカイブから書き出した, "handed": まとめて実行へ渡した,
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
        return head + "(%d 本のうち アーカイブから書き出し %d・文字起こし → パックへ %d・パックまで済み %d%s)" % (
            p["total"], p["exported"], p["handed"], p["finished"], "・失敗 %d" % p["failed"] if p["failed"] else "")
    msg = str(a.get("message") or "")
    return head + ("(%s)" % msg if msg else "")


# ---------- 本体 ----------
class Archiver(LX.Patrol):
    NAME, LOOP_ERROR = "live-archive", "リアルタイム切り抜き: 本番版の見回りでエラー: %r"

    def __init__(self, exporter, studio, enabled=None, recording_state=None, probe=None, audio=None, align=None,
                 slots=None, python=None, ffmpeg=None, ffprobe=None, log=None, first_delay=FIRST_DELAY, interval=INTERVAL,
                 give_up=GIVE_UP, poll=POLL, retry_sec=RETRY_SEC, step=STEP, after=None,
                 after_stream=None, per_hour=None, recordings=None, adopt=None, after_max_age=AFTER_MAX_AGE, compare=None, request=None,
                 settings_for=None, taken=None, exports=None, section_spec=None, queue=None, measure=None):
        """exporter: src/flow/live_export.py の Exporter(ジョブ・マーク・書き出し先・音量)。
        studio(method, path, body) -> (HTTP の番号 か None(つながらない), JSON): 取り込んだスタジオの API(src/app/live.py が autorun と同じ形で呼ぶ)。
        enabled(): リアルタイム切り抜きがオンか。recording_state(録画元, 録画) -> {"active", "endedAt"(epoch)} か None。
        probe(videoId) -> probe_archive の形。audio(videoId, folder, cancelled) -> 配信の丸ごとの音のファイル(fetch_full_audio)。align(ref.wav, window.wav) -> 照合の JSON。
        after(録画元, 録画): その録画の最後の1本が済んだときに呼ぶ(src/manage/keep/live_cleanup.py の Cleaner.check = 消してよい録画を消す)。
        配信後の全自動(M7): after_stream() = 設定 live.autoAfterStream・per_hour() = live.afterStreamPerHour・
        recordings() -> 録画元の録画の一覧 [{recorder, id, url, title, active, endedAt, firstPdt, lastPdt}](時刻は epoch。src/app/live.py の list_recordings)・
        adopt(body, hold=) = M1 の採用(Live.adopt)。
        settings_for(録画元, 録画) -> 配信後の全自動のアーカイブの解析の設定(録画の束の analyze 節。flow/livesession.py。RS7-2 G2b)か None
        (束の無い録画 = 今までどおりスタジオの GET /api/settings)。
        taken(録画元, 録画) -> その録画の採用・書き出し済みのマーク [{start, end, …}](秒 = 録画の頭から)か None(読めない):
        配信後の全自動が重ねない区間(RS8 B3-5 の G3。ライブ係はマークの置き場 marks.adopted = スタジオか、スタジオなしは案件・正本)。
        無ければ今までどおりスタジオの GET /api/video?id=<録画>。
        exports: 本番版の書き出しを頼む器(既定 flow/export.default() = スタジオの書き出しと同じ物 = 同時 1 本)。section_spec(依頼) -> 書き出しの束
        (既定 ① の exporter.build_section_spec)。queue() -> 解析の順番待ち(flow/batch の Batch.snapshot の形)か None(直に読めない =
        スタジオの GET /api/queue。入口の Live が取り込んだスタジオの Batch を渡す。OPT2 の J5)。
        measure(録画元, 録画) -> 配信後の全自動がオフでも、配信中の検出を測るか(EV-1。livesession: 検出の記録 peaks.json がある録画)。
        テストは probe・audio・studio を偽物に、間隔を短くする(本物の YouTube へ繋がない)"""
        super().__init__()
        self.ex, self.studio = exporter, studio
        self._exports = exports
        self.section_spec = section_spec or _exporter.build_section_spec
        self.queue = queue or (lambda: None)
        self.taken = taken or self._studio_taken
        self.after = after
        self.after_stream = after_stream or (lambda: False)
        self.per_hour = per_hour or (lambda: 6)
        self.friend_request = request or (lambda rc, rec: None)   # 引数 request(録画元, 録画) = 友人のライブ配信の依頼(live_requests.Store.get。2-15)。無ければ None。
        # 名前は friend_request(self.request は「アーカイブからの書き出しを頼む」メソッド = POST /live/api/archive。上書きしない)
        self.recordings = recordings or (lambda: [])
        self.adopt = adopt
        self.after_max_age = after_max_age
        self.compare = compare   # compare(録画元, 録画, afterStream, アーカイブの候補, holes=録画の欠け): 配信中の候補と比べて記録する(0-10-6・EV-1。src/flow/live_detect.py)
        self.measure = measure or (lambda rc, rec: False)
        self.settings_for = settings_for or (lambda rc, rec: None)
        self.enabled = enabled or (lambda: True)
        self.recording_state = recording_state or (lambda rc, rec: None)
        self.probe = probe or probe_archive
        self.audio = audio or fetch_full_audio
        self.python = python
        self.align = align or (lambda ref, win: run_align(ref, win, self.python))
        self.slots = slots or jobs.SLOTS
        self.ffmpeg, self.ffprobe = ffmpeg, ffprobe
        self.log = log or (lambda m: None)
        self.first_delay, self.interval, self.give_up = first_delay, interval, give_up
        self.poll, self.retry_sec, self.step = poll, retry_sec, step
        self.path = os.path.join(exporter.folder, "archive.json")
        self.lock = threading.RLock()
        self._cancel = set()      # 取り消しを頼まれたジョブの id(動いている途中のもの)
        self.info = {}
        self.board = None         # 掲示板(attach_board。RS8 の ② の口 S2)
        self._load()

    @property
    def exports(self):
        """書き出しの器(使うときに決める = テストや入口が default を差し替えても、作ったときの物に固まらない)"""
        return self._exports if self._exports is not None else _export.default()

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
        try:
            with self.lock:
                fsio.write_json(self.path, {"schema": SCHEMA, "recordings": self.info}, indent=1)
        except OSError as e:
            self.log("リアルタイム切り抜き: アーカイブの記録を書けませんでした: %s" % e)

    def info_view(self, rc, rec, jobs=None):
        """GET /live/api/exports の archiveInfo {ready: true|false|null, checkedAt, message}。
        配信後の全自動(M7)があれば afterStream {state, label, message, at, n, jobs(採用した本数), progress(after_progress), text(after_text)}。
        jobs = その録画のジョブ(応答の jobs。None なら書き出しの一覧から読む)。帯への表示はスタジオの側(src/app/ui/studio/review.js)"""
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
        self._publish(self.board_job(job))

    def _rec_jobs(self, rc, rec):
        with self.ex.lock:
            return [j for j in self.ex.jobs if j.get("recorder") == rc and j.get("recording") == rec]

    def targets(self, rc, rec):
        """対象: マークごとの最新のジョブで、録画に無い区間のもの(error + needsArchive か、M7 が採用した wait + from "archive")"""
        return sorted([j for j in LX.latest_per_mark(self._rec_jobs(rc, rec)) if needs_archive(j)], key=lambda j: j.get("start") or "")

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
                return {"ok": True, "queued": 0, "message": "もうアーカイブから書き出しています"}
            raise ArchiveError("アーカイブから書き出すものがありません(録画の欠け・止めていた間など、録画に無い区間のマークが対象です)", 409)
        i = self.info_view(rc, rec)
        fresh = i["ready"] is True and _checked_within(i, READY_CACHE)
        if not fresh:
            i = self.check(rc, rec, quick=True)   # 画面のボタン: やり直して待たせない(断られたら、もう一度押せる)
        if i.get("ready") is not True:
            raise ArchiveError(i.get("message") or "アーカイブがまだ用意できていません", 409)
        self._queue(todo, auto=False)
        return {"ok": True, "queued": len(todo), "message": "%d 本をアーカイブから書き出します" % len(todo)}

    def cancel(self, rc, rec):
        """POST /live/api/archive/cancel。-> 取り消した数(待ちはすぐ、途中のものは今の段を止めてから)"""
        n = sum(1 for j in self._rec_jobs(rc, rec) if self._cancel_one(j))
        self.ex._save()
        self.wake.set()
        return n

    def _cancel_one(self, j):
        """1 本を取り消す(待ちはすぐ、途中のものは今の段を止めてから)。-> 取り消したか"""
        st = (j.get("archive") or {}).get("state")
        if st == "wait" or (not st and from_archive(j) and j.get("state") == "wait"):
            self._aset(j, save=False, state="cancelled", message=CANCELLED_MSG, progress=0)
            self._end_job(j, "cancelled")
            return True
        if st in RUN:
            self._cancel.add(j["id"])
            self._publish(self.board_job(j))
            return True
        return False

    # --- 掲示板(flow/board.py。RS8 の ② の口 S2。押す形 = 状態を変えた所で載せる。器の本体と今の API はそのまま) ---
    def attach_board(self, board):
        """掲示板にアーカイブからの書き出し(ジョブごと)と配信後の全自動(録画ごと)を載せる(頭 la。取り消しも掲示板の id で)。
        ライブ係(flow/livesession.py)が作ったときに 1 回呼ぶ。今ある物も載せる"""
        self.board = board
        board.register("la", cancel=self.board_cancel)
        with self.ex.lock:
            js = [j for j in self.ex.jobs if isinstance(j.get("archive"), dict) and j["archive"].get("state")]
        for j in js:
            self._publish(self.board_job(j))
        with self.lock:
            afters = [(i.get("recorder"), i.get("recording"), dict(i["afterStream"])) for i in self.info.values()
                      if isinstance(i.get("afterStream"), dict) and i["afterStream"].get("state")]
        for rc, rec, a in afters:
            if isinstance(rc, str) and isinstance(rec, str):
                self._publish(self.after_board_job(rc, rec, a))

    def board_job(self, job):
        """書き出しのジョブのアーカイブからの書き出し(job["archive"])-> 掲示板の Job"""
        a = job.get("archive") or {}
        st = BOARD_STATES.get(a.get("state"), "error")
        end = st not in ("queued", "running")
        updated = LX.iso_epoch(job.get("updated"))
        return {"id": "la:" + job["id"], "kind": "live_archive", "case": self.ex.case_of(job.get("recorder"), job.get("recording")),
                "target": {"markId": job.get("markId"), "recording": job.get("recording"), "path": job.get("path") or None},
                "title": "アーカイブから書き出し: %s" % (job.get("label") or "マーク %s" % (job.get("n") or "")),
                "state": st, "phase": a.get("message") or a.get("label") or "", "progress": a.get("progress"),
                "finishedAt": int(updated * 1000) if end and updated is not None else None,
                "error": (a.get("message") or "失敗しました") if st == "error" else None,
                "canCancel": not end and job["id"] not in self._cancel, "canRetry": False}

    def after_board_job(self, rc, rec, a):
        """配信後の全自動(録画 1 本の afterStream)-> 掲示板の Job(取り消しは無い = canCancel は偽)"""
        st = AFTER_BOARD.get(a.get("state"), "error")
        at = LX.iso_epoch(a.get("at"))
        return {"id": "la:%s%s.%s" % (AFTER_PREFIX, rc, rec), "kind": "live_archive", "case": self.ex.case_of(rc, rec),
                "target": {"recording": rec}, "title": "配信後の自動の切り抜き: %s" % rec, "state": st,
                "phase": a.get("message") or a.get("label") or "",
                "finishedAt": int(at * 1000) if st not in ("queued", "running") and at is not None else None,
                "error": (a.get("message") or "失敗しました") if st == "error" else None, "canCancel": False, "canRetry": False}

    def _publish(self, job):
        b = self.board
        if b is None:
            return
        try:
            b.upsert(job)
        except ValueError as e:   # 載せられなくても書き出しは止めない
            self.log("リアルタイム切り抜き: アーカイブからの書き出しを掲示板に載せられませんでした(%s)" % e)

    def board_cancel(self, jid):
        """掲示板の取り消し(ジョブ 1 本。POST /live/api/archive/cancel の 1 本分)。配信後の全自動は ValueError・無い id は LookupError"""
        if jid.startswith(AFTER_PREFIX):
            raise ValueError("配信後の自動の切り抜きは止められません")
        with self.ex.lock:
            job = next((j for j in self.ex.jobs if j.get("id") == jid and isinstance(j.get("archive"), dict)), None)
        if job is None:
            raise LookupError("そのアーカイブからの書き出しはありません")
        if not self._cancel_one(job):
            raise ValueError("このアーカイブからの書き出しは今は止められません")
        self.ex._save()
        self.wake.set()
        return self.board_job(job)

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
            ready, msg, p = False, "YouTube の動画が分からない録画なので、アーカイブから書き出せません", {}
        else:
            try:
                p = (probe_archive(vid, retries=0) if quick and self.probe is probe_archive else self.probe(vid)) or {}
            except Exception as e:   # 調べる部品の不具合でも見回りは止めない
                p = {"status": "unknown", "message": "アーカイブを確かめられませんでした(%s)" % e.__class__.__name__}
            ready, msg = readiness(p)
        return self._info_put(rc, rec, videoId=vid, ready=ready, message=msg, checkedAt=LX.now_iso(), release=p.get("release"), timestamp=p.get("timestamp"),
                              duration=p.get("duration"), availability=p.get("availability") or "")

    def archived(self, rc, r):
        """アーカイブ化したか(録画を消してよい合図。src/flow/live_retire.py の Retire.verdict が聞く)。r = 録画元の一覧の 1 行(終わった録画)。
        -> "" = 確かめた / 消さない理由(NOT_ARCHIVED で始まる文)。
        消す直前に必ず確かめ直す(前の結果が「用意できた」でも probe し直す。数秒)。用意がまだと分かったばかり(INTERVAL 以内)なら確かめ直さない。
        条件: was_live・限定でない・開始時刻と長さが分かる・アーカイブの終わり(開始 + 長さ)が録画の終わり − ARCHIVED_SLACK より後"""
        rec = str((r or {}).get("id") or "")
        if not self.enabled() or not LX.REC_RE.match(rec):
            return NOT_ARCHIVED
        vid = LX.video_id_of(str(r.get("url") or ""), rec)
        if not vid:
            return NOT_ARCHIVED + "(YouTube の動画が分からない録画)"
        with self.lock:
            i = dict(self.info.get(self.key(rc, rec)) or {})
        if i.get("ready") is not True and _checked_within(i, self.interval):
            return NOT_ARCHIVED + "(%s)" % (i.get("message") or "アーカイブがまだ用意できていません")
        i = self.check(rc, rec, vid=vid)
        if i.get("ready") is not True:
            return NOT_ARCHIVED + "(%s)" % (i.get("message") or "アーカイブがまだ用意できていません")
        t0, dur = i.get("release"), i.get("duration")
        if not schemas.is_num(t0) or not schemas.is_num(dur):
            return NOT_ARCHIVED + "(アーカイブの開始時刻か長さが分からない)"
        ended = ended_at(r)
        if ended is None:
            return NOT_ARCHIVED + "(録画の終わりの時刻が分からない)"
        if t0 + dur < ended - ARCHIVED_SLACK:
            return NOT_ARCHIVED + "(アーカイブが録画の終わりまで無い。%d 秒足りない)" % int(ended - t0 - dur)
        return ""

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

    # --- 動かす(糸の start・close・見回りは flow/live_patrol の Patrol) ---
    def _step(self):
        job = self._next()
        if job is not None:
            self._process(job)
            self._clean_audio()
            if self.after and (job.get("archive") or {}).get("state") == "done" and not self._next_of(job):
                self.after(job["recorder"], job["recording"])   # その録画の最後の1本が済んだ: 消してよければ録画を消す
            return True
        self._clean_audio()
        self.auto_tick()
        self.after_tick()   # 配信後の全自動(M7。設定 live.autoAfterStream)
        return False

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
        """配信の丸ごとの音(live\\work\\audio-<videoId>\\)は、その配信のアーカイブからの書き出しが待ち・途中で無くなったら消す(古い物も見回りで消える)"""
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
        p = self.audio(vid, d, self._stopper(job))
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
        """自動(いつも): 終わった録画で、アーカイブから書き出すマークのうち まだ試していないものがあれば、時間が来たら用意を確かめ、
        用意できていて手が空いていれば始める。-> 始めた本数"""
        if not self.enabled():
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
                    self._info_put(rc, rec, gaveUp=True, message="録画が終わって %d 日たってもアーカイブを使えなかったので、自動で書き出すのをやめました(%s)"
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
            self.log("リアルタイム切り抜き: 録画に無い区間をアーカイブから書き出します(自動。%s の %d 本)" % (rec, len(cand)))
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
        self._publish(self.after_board_job(rc, rec, a))
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
            a = self._after_get(rc, rec)
            if not a and not self._after_on(rc, rec, every) and not self._measure_on(rc, rec):   # 始めたあとは切り替えても続ける(mode は始めたときの物)
                continue
            if a and a.get("mode") != "measure" and not self._after_on(rc, rec, every):
                continue
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

    def _measure_on(self, rc, rec):
        """配信後の全自動がオフでも、配信中の検出を測るか(EV-1): 環境変数 YTT_LIVE_MEASURE が off でなく、measure(録画元, 録画) が真。確かめられなければ偽"""
        if os.environ.get("YTT_LIVE_MEASURE", "").strip().lower() == "off":
            return False
        try:
            return bool(self.measure(rc, rec))
        except Exception:   # noqa: BLE001
            return False

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
        dur = i.get("duration")
        end = max(last, t0 + dur - offset) if schemas.is_num(dur) else last   # 採用の範囲の終わり = 配信の終わり(アーカイブの終わり。録画の後で止めた分も)
        mode = a.get("mode") or ("after" if self._after_on(rc, rec) else "measure")   # 測るだけ(EV-1)は採用しない
        base = dict(vid=vid, t0=t0, offset=round(offset, 3), offsetFrom=how, first=first, last=last, end=round(end, 3), n=n,
                    title=str(r.get("title") or "")[:LX.TITLE_MAX], retryAt=None, mode=mode)
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
                        message=("アーカイブを解析しています(配信中の検出を測ります。ずれ %.1f 秒・%s)" % (offset, how)) if mode == "measure" else
                        "アーカイブを解析しています(上位 %d 本を採用します。ずれ %.1f 秒・%s)" % (n, offset, how), **base)
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
        span = min(REF_SEC, last - first - 2.0)
        ra = first + max(1.0, (last - first - span) / 2.0)
        job = {"id": "after-" + rec, "recorder": rc, "recording": rec}   # 照合のための仮のジョブ(書き出しのジョブには入れない)
        return self._rec_offset(job, vid, t0, ra, ra + span), "録画の音をアーカイブと照合"

    def _rec_offset(self, job, vid, t0, ra, rb, last_session=False, center=None, windows=WINDOWS_FIRST):
        """録画の [ra, rb](受信時刻)の音を録画元から取り、アーカイブの丸ごとの音と照合して ずれ(アーカイブの秒 − (受信時刻 − 開始時刻))を求める。
        つなぎ直しをまたがない(last_session なら区間の最後のセッション = マークの頭に近い方、無ければ最初のセッションの分だけ)。
        center: 見当のずれ(分かっていれば。窓の真ん中を動かす)。-> ずれ。取れない・合わなければ ArchiveError(つながらなければ Later)"""
        rc, rec = job["recorder"], job["recording"]
        rco = self.ex.host.find(rc)
        if rco is None:
            raise ArchiveError("その録画元はありません")
        wdir = os.path.join(self.ex.work, "offset-" + job["id"])
        try:
            code, d = self.ex._query(rc, rec, ra, rb)
            if code is None:
                raise Later("録画元につながらないので、録画とアーカイブの時刻を合わせられません", self.retry_sec)
            if code != 200 or not isinstance(d, dict):
                raise ArchiveError("録画が見つかりません(録画元で消されたか、置き場所を変えたかもしれません)" if code == 404 else
                                   "録画元から思わぬ応答がありました(HTTP %s)" % code)
            segs = [x for x in d.get("segments") or [] if LX.SEG_URI_RE.match(str(x.get("uri") or ""))]
            if not segs:
                raise ArchiveError("録画に音を取れる所がないので、アーカイブと時刻を合わせられません")
            sess = segs[-1 if last_session else 0].get("session")
            segs = [x for x in segs if x.get("session") == sess]   # つなぎ直しをまたがない
            files = self.ex._fetch(job, rco, rec, segs, wdir)
            s0 = LX.iso_epoch(segs[0].get("pdt"))
            have = sum(float(x.get("dur") or 0) for x in segs)
            ss = max(0.0, ra - s0) if s0 is not None else 0.0
            use = min(rb - ra, have - ss)
            if use < 5.0:
                raise ArchiveError("録画に続けて取れる音が短すぎるので、アーカイブと時刻を合わせられません")
            ref = self._wav(files[0][0], os.path.join(wdir, "ref.wav"), ss, use, job)
            full = self._full_audio(job, vid)
            est = (s0 + ss if s0 is not None else ra) - t0
            w0, _w1, r = self._search(job, ref, full, est + (center or 0.0), use, windows, wdir)
            if w0 is None:
                raise ArchiveError("録画の音とアーカイブの音が合いませんでした(%s)。アーカイブが切り貼りされたか、別の配信かもしれません" % r)
            return w0 + float(r["offset"]) - est
        finally:
            shutil.rmtree(wdir, ignore_errors=True)

    def _after_analyze(self, rc, rec, a):
        """スタジオの解析の進み具合を見る(取り込んだスタジオの Batch を直に読めればそれ、無ければ GET /api/queue)。済めば採用へ"""
        d = self.queue()
        code = 200 if isinstance(d, dict) else None
        if code is None:
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

    def _studio_taken(self, rc, rec):
        """taken の既定: スタジオの録画の配信のマーク(GET /api/video?id=<録画>)。つながらない・無ければ None"""
        _code, lv = self._studio_video(rec)
        return lv.get("marks") if lv is not None else None

    def _after_adopt(self, rc, rec, a):
        """候補から上位 N を選び、M1 の採用(origin archive)を 1 本ずつ頼む"""
        measure = a.get("mode") == "measure"
        if self.adopt is None and not measure:
            raise ArchiveError("採用の仕組み(M1)が使えません")
        code, v = self._studio_video(a["vid"])
        if v is None:
            raise Later("スタジオからアーカイブの解析の結果を読めませんでした(HTTP %s)" % code, self.retry_sec)
        marks = v.get("marks") or []
        row = None
        if self.compare is not None:   # 配信中の候補(L2)とアーカイブの候補を比べて live_feedback.jsonl へ(0-10-6・EV-1。失敗しても採用は続ける)
            try:
                row = self.compare(rc, rec, a, marks, holes=self._rec_holes(rc, rec, a))
            except Exception as e:
                self.log("リアルタイム切り抜き: 配信中の候補とアーカイブの候補を比べられませんでした: %r" % (e,))
        if measure:   # 測るだけ(EV-1): 採用しない
            got = ("アーカイブの候補 %d 件のうち配信中にも出た %d 件(穴で外した %d 件)" % (row.get("archive") or 0, row.get("hit") or 0, row.get("excluded") or 0)
                   if isinstance(row, dict) else "配信中の候補が無かったので比べませんでした")
            self._after_set(rc, rec, state="measured", jobs=[], picked=[], message=got)
            self.log("リアルタイム切り抜き: 配信中の検出を測りました %s(%s)" % (rec, got))
            if self.after:
                try:
                    self.after(rc, rec)   # 消してよければ録画を消す(測り終えるのを待っていた)
                except Exception:
                    pass
            return True
        try:   # 録画の、もう採用・書き出し済みのマーク(人が付けたもの・配信中の自動)と重ねない。置き場から読む(G3。読めなければ重ねる物なし = 今までどおり)
            got = self.taken(rc, rec)
        except Exception as e:   # noqa: BLE001
            self.log("リアルタイム切り抜き: 録画の採用を読めませんでした(重ねない区間なしで続けます): %r" % (e,))
            got = None
        taken = [(a["first"] + m["start"], a["first"] + m["end"]) for m in got or []
                 if isinstance(m, dict) and m.get("status") in ("adopted", "exported") and schemas.is_num(m.get("start")) and schemas.is_num(m.get("end"))]
        end = a["end"] if schemas.is_num(a.get("end")) else a["last"] - LX.READY_PAD   # 前の版の記録(end なし)は録画の終わりまで
        picked = pick_candidates(marks, a["n"], a["t0"], a["offset"], a["first"], end, taken)
        cands = sum(1 for m in marks if isinstance(m, dict) and m.get("src") == "auto")
        if not picked:
            self._after_set(rc, rec, state="none", jobs=[], picked=[],
                            message="録画の頭から配信の終わりまでに採用できる候補がありませんでした(アーカイブの候補 %d 件・範囲 %d 秒)" % (cands, int(end - a["first"])))
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
                        message="%d 本を採用しました(アーカイブの解析の上位)。アーカイブから書き出し → 文字起こし → パック" % len(jobs_) +
                        ("(%d 本は採用できませんでした: %s)" % (len(errs), errs[0]) if errs else ""))
        self.log("リアルタイム切り抜き: 配信後の自動の切り抜き: %s で %d 本を採用しました(origin archive)" % (rec, len(jobs_)))
        return True

    def _after_follow(self, rc, rec, a):
        """採用したジョブを見届ける: アーカイブからの書き出しに入れる・全部が済んだら done"""
        with self.ex.lock:
            js = {j["id"]: j for j in self.ex.jobs if j.get("id") in (a.get("jobs") or [])}
        todo, waiting = [], 0
        for jid in a.get("jobs") or []:
            j = js.get(jid)
            if j is None:
                continue
            arc = j.get("archive") or {}
            if needs_archive(j) and not arc:
                todo.append(j)
                waiting += 1
            elif j.get("state") in LX.ACTIVE or arc.get("state") in ACTIVE:
                waiting += 1
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
                self.after(rc, rec)   # 消してよければ録画を消す(消すのを待っていた = after_stream_hold)
            except Exception:
                pass
        return True

    def after_stream_hold(self, rc, r):
        """録画を自動で消すのを待つ理由(src/manage/keep/live_cleanup.py から。r = 録画元の一覧の 1 行)。待たなくてよければ ""。
        配信後の全自動がオン(友人の依頼の録画は依頼の afterStream。2-15)で、その録画がまだ済んでいない(終わって AFTER_MAX_AGE 以内・YouTube の動画が分かる)間は消さない"""
        if not self.enabled() or not isinstance(r, dict):
            return ""
        rec = str(r.get("id") or "")
        a = self._after_get(rc, rec)
        if not self._after_on(rc, rec) and not (self._measure_on(rc, rec) or a.get("mode") == "measure"):
            return ""
        if a.get("state") in AFTER_END:
            return ""
        ended = ended_at(r)
        if ended is not None and time.time() - ended > self.after_max_age:
            return ""
        if not LX.video_id_of(str(r.get("url") or ""), rec):
            return ""
        if not self._after_on(rc, rec):
            return "配信中の検出の測り直し(アーカイブの解析)がまだです"
        return "配信後の自動の切り抜き(アーカイブの解析)がまだです"

    def _rec_holes(self, rc, rec, a):
        """録画の欠け(つなぎ直しの間・止めていた間)-> [(から, まで)](録画の頭からの秒。EV-1 の compare が外して数える)。
        録画元の /segments を HOLE_CHUNK ずつ聞いて gaps を集める。つながらない・読めない・録画が無ければ None(compare は欠けを知らないまま数える)"""
        first, last = a.get("first"), a.get("last")
        if not schemas.is_num(first) or not schemas.is_num(last) or last <= first:
            return None
        out, t = [], first
        while t < last:
            u = min(last, t + HOLE_CHUNK)
            try:
                code, d = self.ex._query(rc, rec, t, u)
            except Exception:   # noqa: BLE001
                return None
            if code != 200 or not isinstance(d, dict):
                return None
            for g in d.get("gaps") or []:
                x, y = LX.iso_epoch((g or {}).get("from")), LX.iso_epoch((g or {}).get("to"))
                if x is not None and y is not None and y > x:
                    out.append((round(max(0.0, x - first), 3), round(min(last, y) - first, 3)))
            t = u
        return out

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
    def _job_cancelled(self, job):
        return job["id"] in self._cancel

    def _end_job(self, job, state, message=""):
        """M7 の採用で待っていたジョブ(wait + from archive)を、書き出せなかった・取り消したときに閉じる(録画の書き出しの印 wait のまま残さない =
        録画を消す判断・書き出しの順番が「書き出しの途中」と見ない)。失敗は error + needsArchive(人が押せばやり直せる)"""
        if not (from_archive(job) and job.get("state") == "wait"):
            return
        with self.ex.lock:
            if state == "error":
                job.update(state="error", needsArchive=True, error=message or "アーカイブから書き出せませんでした", message="")
            else:
                job.update(state="cancelled", message=message or CANCELLED_MSG)
            job["updated"] = LX.now_iso()
        self.ex._save()
        self.ex._publish(job)

    def _process(self, job):
        rc, rec = job["recorder"], job["recording"]
        wdir = os.path.join(self.ex.work, "archive-" + job["id"])
        tdir = None
        try:
            if not needs_archive(job):   # 前の版で入れ替え(速報版 → 本番版)を待っていたジョブ: 入れ替えは廃止したので何もしない
                self._aset(job, state="cancelled", message="本番版への入れ替えはやめました(録画から書き出した切り抜きのままです)", progress=0, retryAt=None)
                return
            if self.ex._disk_low():   # 空きが少ない(M4): アーカイブからの書き出し(書き出し先へ書く・丸ごとの音)も空くまで待つ
                raise Later(self.ex.disk()["message"], LX.DISK_POLL)
            self._aset(job, state="probe", message="アーカイブを確かめています", progress=0.02, retryAt=None)
            info = self._ready_info(rc, rec)
            if info.get("ready") is not True:
                raise Later(info.get("message") or "アーカイブがまだ用意できていません", self.interval)
            vid = info.get("videoId") or ""
            if not LX.YT_ID_RE.match(vid):
                raise ArchiveError("YouTube の動画が分からない録画なので、アーカイブから書き出せません")
            t0 = info.get("release")   # timestamp は配信の終わりごろ(数時間ずれる)なので使わない
            if not isinstance(t0, (int, float)):
                raise ArchiveError("開始時刻が分からないので照合できません")
            a, b = LX.iso_epoch(job.get("start")), LX.iso_epoch(job.get("end"))
            if a is None or b is None or b <= a:
                raise ArchiveError("マークの時刻が正しくありません")
            est, dur = a - t0, b - a
            root = self.ex.out_dir()
            d = self._rec_meta(job)
            folder, base, title = self.ex.target(job, d, rec, a, b)
            tdir = os.path.join(folder, schemas.WORK_DIR, BUILD_DIR, job["id"])
            if not inside(tdir, root):
                raise ArchiveError("書き出し先の外には書けません")
            tmp = os.path.join(tdir, base + ".mp4")
            shutil.rmtree(tdir, ignore_errors=True)
            os.makedirs(tdir, exist_ok=True)
            self._aset(job, state="align", message="録画の音とアーカイブの音を照合しています", progress=0.05)
            off, how = self._job_offset(job, vid, t0, a, b)
            ast = est + off
            self._aset(job, offset=round(off, 3), offsetFrom=how)
            m = self.ex.margin(job)   # 余白(LD-2f。録画から書き出すときと同じ束の export.margin)。アーカイブの 0 秒より前へは出さない
            rb = self.ex._base(d, a)   # .clip.json の秒の 0 = 録画の頭。余白はそれより前へは出さない(actualStart が負になる)
            before = min(m, max(0.0, ast), max(0.0, a - rb))
            vlen = info.get("duration")   # アーカイブの長さ(分かれば)より後へも出さない(長さの確かめで落ちないように)
            after = min(m, max(0.0, vlen - ast - dur)) if isinstance(vlen, (int, float)) and vlen > 0 else m
            out = self._build(job, vid, ast - before, dur + before + after, tmp)
            span = (a - before, a - before + (out.get("duration") or dur + before + after)) if before + after > 0 else None
            meta = {"videoId": vid, "start": round(ast, 3), "end": round(ast + dur, 3), "offset": round(off, 3), "at": LX.now_iso()}
            self._aset(job, archiveStart=meta["start"], archiveEnd=meta["end"])
            final = os.path.join(folder, LX.unique_base(base, folder) + ".mp4")
            self._aset(job, state="verify", message="書き出した動画を置いています")
            fsio.replace_retry(tmp, final)
            self.ex._finish(job, {"id": rc}, rec, d, dict(out, path=final, title=title or self.ex._title(job, d)), a, b,
                            archive=meta, message="アーカイブから書き出しました", clip_span=span)
            with self.ex.lock:
                job.update(needsArchive=False, error="")
            self._aset(job, state="done", message="アーカイブから書き出しました", progress=1.0, at=meta["at"])
            self.log("リアルタイム切り抜き: アーカイブから書き出しました %s(アーカイブの %.3f〜%.3f 秒・ずれ %.3f 秒・%s)" % (job.get("path"), ast, ast + dur, off, how))
        except LX.Cancelled:
            self._aset(job, state="cancelled", message=CANCELLED_MSG, progress=0)
            self._end_job(job, "cancelled")
        except LX.Halted:
            self._aset(job, state="wait", message="ホームを終えたので、次の起動で続けます", progress=0)
        except Later as e:
            after = e.after if e.after is not None else self.retry_sec
            self._aset(job, state="wait", message=str(e), progress=0, retryAt=time.time() + after)
        except (LX.LiveError, normalize.NormalizeError) as e:
            self._aset(job, state="error", message=str(e), progress=0)
            self._end_job(job, "error", str(e))
        except OSError as e:
            self._aset(job, state="error", message="書けませんでした: %s" % tools.why(e), progress=0)
            self._end_job(job, "error", "書けませんでした: %s" % tools.why(e))
        except Exception as e:
            self.log("リアルタイム切り抜き: アーカイブからの書き出しでエラー %r" % (e,))
            self._aset(job, state="error", message="内部エラー: %s" % e.__class__.__name__, progress=0)
            self._end_job(job, "error", "内部エラー: %s" % e.__class__.__name__)
        finally:
            self._cancel.discard(job["id"])
            shutil.rmtree(wdir, ignore_errors=True)
            if tdir:
                shutil.rmtree(tdir, ignore_errors=True)
                for p in (os.path.dirname(tdir), os.path.dirname(os.path.dirname(tdir))):   # 空になった 本番版の作りかけ・作業用 は消す(中身があれば消えない)
                    try:
                        os.rmdir(p)
                    except OSError:
                        break

    def _job_offset(self, job, vid, t0, a, b):
        """ジョブのずれ -> (ずれ, 出どころの文)。
        1. マークの頭の手前(無ければ頭から)の録画の音を照合する(同じセッション。照合できたら aligned = ほかのマークの見当にも使う)
        2. だめなら同じ録画の照合できたマーク(前にある・近いもの)/ 3. 配信後の全自動(M7)が求めた録画のずれ。どれも無ければ最初の理由で ArchiveError"""
        rc, rec = job["recorder"], job["recording"]
        with self.lock:
            i = dict(self.info.get(self.key(rc, rec)) or {})
        prev = self._nearest_offset(job, need=False, same_video=True)
        hint = prev if prev is not None else (i.get("afterStream") or {}).get("offset")
        hint = hint if schemas.is_num(hint) else None
        why = ""
        try:
            got = self._rec_offset(job, vid, t0, a - REF_SEC, a, last_session=True, center=hint, windows=WINDOWS_NEXT if hint is not None else WINDOWS_FIRST)
            self._aset(job, aligned=True)
            return got, "マークの手前の録画の音を照合"
        except ArchiveError as e:
            why = str(e)
        try:   # 手前に録画が無い(マークが録画の頭より前・欠けの直後)ときは、マークの中の録れている所
            got = self._rec_offset(job, vid, t0, a, min(b, a + REF_SEC), center=hint, windows=WINDOWS_NEXT if hint is not None else WINDOWS_FIRST)
            self._aset(job, aligned=True)
            return got, "マークの中の録画の音を照合"
        except ArchiveError:
            pass
        near = self._nearest_offset(job, need=False)
        if near is not None:
            return near, "同じ録画の照合できたマークから"
        after = (i.get("afterStream") or {}).get("offset")
        if schemas.is_num(after):
            return float(after), "配信後の自動の切り抜きの時刻合わせから"
        raise ArchiveError("録画の音でアーカイブの時刻を合わせられませんでした(%s)" % why)

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
        セッションにあり、つなぎ直すとずれが 1 秒ほど変わるため。2026-10-05 の通しの確認で 0.73 秒)。無ければ need なら ArchiveError、でなければ None。
        same_video: 同じ録画に無ければ、同じ配信(videoId)の別の録画のジョブからも探す(照合の窓の見当だけに使う。本物の配信で 2 本の録画の差は 1.24 秒 =
        ±20 秒の窓に収まる。マークの時刻そのものには使わない = 録画が違うと 1 秒ほどずれる)"""
        a = LX.iso_epoch(job.get("start")) or 0
        best = None
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
        if best is not None:
            return best[1]
        if not need:
            return None
        raise ArchiveError("同じ録画に照合できたマークが無いので、アーカイブの時刻を合わせられません")

    def _wav(self, src, dst, ss=None, t=None, job=None):
        """ffmpeg で 8kHz・モノラル・16bit の WAV にする(照合の子プロセスが読む形)"""
        ff = self.ffmpeg or tools.find_tool("ffmpeg")
        if not ff:
            raise ArchiveError("ffmpeg が見つかりません")
        # 精密な切り方: PRE_SEEK 秒手前まで入力側で飛び、残りは出力側で(デコードして)切る = サンプル単位で正確(AAC の入力側の -ss は 13ms ほどずれる)。
        # 引数を組むのは ① の recognize.wav_args(OPT2)
        cmd = _recognize.wav_args(ff, src, dst, ss, t or None, rate=8000, opts=("-nostdin", "-y", "-v", "error"), pre_seek=PRE_SEEK,
                                  drop=("-vn", "-sn", "-dn"), fmt="wav")
        code, _o, tail = run_proc(cmd, FFMPEG_TIMEOUT, self._stopper(job) if job else None)
        if code != 0 or not os.path.isfile(dst):
            raise ArchiveError("音を取り出せませんでした(%s)" % (" / ".join(tail) or "終了コード %s" % code))
        return dst

    def _search(self, job, ref, full, center, span, windows, wdir, talk=False):
        """アーカイブの丸ごとの音 full から、見当 center の前後 w 秒(windows の順に広げる)の窓を切り出して ref と照合する
        (窓の決め方・しきい値はジョブのずれと M7 の時刻合わせで同じ)。talk = 進み具合をジョブの archive に出す。
        -> (窓の頭の秒, 窓の終わりの秒, 照合の結果)。どの窓でも合わなければ (None, None, 最後の理由の文)"""
        why = ""
        for n, w in enumerate(windows):
            self._check(job)
            w0, w1 = max(0.0, center - w), center + span + w
            if talk:
                self._aset(job, message="アーカイブの音を切り出しています(見当の前後 %d 秒)" % int(w), progress=0.05 + 0.05 * n)
            win = self._wav(full, os.path.join(wdir, "window.wav"), w0, w1 - w0, job=job)   # 手前まで入力側の -ss・残りはデコードして切る(_wav。サンプル単位で正確)
            self._check(job)
            if talk:
                self._aset(job, message="照合しています(見当の前後 %d 秒)" % int(w))
            r = self.align(ref, win) or {}
            fsio.unlink_quiet(win)
            if r.get("ok") and (r.get("score") or 0) >= MIN_SCORE and (r.get("ratio") or 0) >= MIN_RATIO:
                return w0, w1, r
            why = r.get("reason") if not r.get("ok") else "確かさ %.2f・%.1f 倍" % (r.get("score") or 0, r.get("ratio") or 0)
        return None, None, why

    def _check_media(self, path, dur):
        """アーカイブから書き出した動画が 30fps で、長さが区間と LEN_TOL 以内か(ytt.normalize.verify)。-> probe の結果"""
        return normalize.verify(path, dur, LX.LEN_TOL, self.ffprobe, what="アーカイブから書き出した動画", ref="区間", got="動画", error=ArchiveError)

    def _build(self, job, vid, ast, dur, tmp):
        """スタジオの書き出しでアーカイブの区間を 30fps に書き出して確かめる。音量は録画から書き出すときと同じ(録画の束か今の書き出しの設定)。
        高さは指定なし(スタジオの既定)。-> probe の結果(+ audio)"""
        vol, loud = self.ex._audio_cfg(job)
        self._check(job)
        fsio.unlink_quiet(tmp)
        self._aset(job, state="fetch", message="アーカイブから取って 30fps に書き出しています(スタジオの書き出し)", progress=0.15, archiveStart=round(ast, 3))
        item = self._section(job, vid, ast, ast + dur, tmp, 0, vol, loud)
        self._aset(job, state="verify", message="書き出した動画を確かめています", progress=0.9)
        if not os.path.isfile(tmp):
            raise ArchiveError("スタジオの書き出しが済んだのに、動画のファイルがありません")
        out = self._check_media(tmp, dur)
        out["audio"] = {"loudness": item.get("loudness")} if loud and isinstance(item.get("loudness"), dict) else \
            {"loudness": {"target": loud}} if loud else {"volume": vol}
        return out

    def _section(self, job, vid, start, end, path, height, vol, loud):
        """② の書き出しの器(flow/export の ExportJobs。プロセスに 1 つ = スタジオの書き出しと同時 1 本を分け合う)に区間を頼み、済むまで待つ。
        スタジオの HTTP を通さない(スタジオなしの入口でも動く。OPT2 の J5)。-> 書き出しの item(GET /api/export の items[0] の形)"""
        req = {"videoId": vid, "start": round(start, 3), "end": round(end, 3), "path": path, "volume": vol, "loudness": loud,
               "maxHeight": height, "precision": "accurate"}
        try:
            spec = self.section_spec(req)   # 検査(書き出し先の中・まだ無い .mp4・ffmpeg と yt-dlp)は ① の build_section_spec
        except ApiError as e:
            raise ArchiveError("アーカイブからの書き出しを始められませんでした: %s" % e.message)
        while True:   # 書き出しは同時に 1 本だけ: ほかが動いていれば busy → 失敗にせず、待ってやり直す
            self._check(job)
            try:
                rec = self.exports.start(spec)
            except ApiError as e:
                if e.code != "busy":
                    raise ArchiveError("アーカイブからの書き出しを始められませんでした: %s" % e.message)
                self._aset(job, save=False, message="スタジオの書き出しが終わるのを待っています")
                self._halt.wait(max(self.step, 1.0) * 3)
                continue
            break
        while True:
            try:
                self._check(job)
            except (LX.Cancelled, LX.Halted):
                rec["ctl"].cancel()
                raise
            d = self.exports.public_of(rec)
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
            self._halt.wait(self.step)
