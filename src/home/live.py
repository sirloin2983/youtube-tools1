# -*- coding: utf-8 -*-
"""リアルタイム切り抜き(線 D。plan/line-d-live-clipping.md の 0)の入口の側。**既定はオフ**(ホームの設定の節 live.enabled)。
オフの間は何もしない: /live/… は今までどおり 404(handle が False を返し、入口の 404 になる)・録画の部品も起動しない・「調子」にも出さない。
api/ytt/live の status だけはオフでも {enabled: false} を返す(録画元に問い合わせない)。

P3(2026-10-05。計画の 0-8): 録画と再生・マークは**スタジオの中**(② 確認・書き出し)。別ページ /live/(live.html・live.js・live.css)はやめた。
スタジオのサーバーは録画の部品と話さず、スタジオの**画面が**ここの API を呼ぶ(同じオリジン・入口の合言葉)。

オンのとき:
  GET  /live/・/live/index.html・/live    スタジオ /studio/ へ 302(以前の録画の画面のブックマーク)
  GET  /live/hls.min.js                   hls.js(src/home/vendor/ に同梱 = CSP script-src 'self' のまま。スタジオの画面が ../live/hls.min.js で読む)
  GET  /live/api/info                     録画元の一覧(名前・URL。合言葉は出さない)・録画の置き場所の設定・書き出しの音量(スタジオの設定の引き出しが読む)
  POST /live/api/begin  {url}             配信の状態を yt-dlp で調べ(live_status)、配信中・配信前なら既定の録画元(一覧の先頭)で録画を始める
                                          → {live: true, recorder, recording: {id, url, title, state}, existing}(同じ配信を録画中ならそれ = existing: true)
                                          / 配信中でない・調べられない → {live: false, status: was_live|not_live|post_live|unknown, message?}(画面は今までどおりの解析へ)
  GET|POST /live/r/<録画元>/<残り>        録画元(src/pipeline/ingest/recorder.py)の /live/<残り> へ中継する(同じオリジンのまま。合言葉は入口が付ける)
                                          例: /live/r/local/<録画>/index.m3u8・…/status・…/stop・…/session_001/seg_000000.ts
                                          POST は <録画>/stop だけ(録画を消す …/delete・終わる quit などは中継しない = 入口の中の処理だけが呼ぶ。P4)
  GET  /live/api/marks?recorder=&recording=   録画1本のマークの正本と書き出し(P2。中身は src/flow/live_export.py)
  (POST /live/api/marks は RS8 B3-5 で消した = 画面から呼ぶ所が 0 件。マークの正本は書き出しのジョブの入力と、スタジオなしの採用の書き出しまでの置き場
   = flow/live_export.py の MarkStore・flow/live_adopt.py の LocalMarks)
  GET  /live/api/exports?recorder=&recording=  書き出しのジョブの一覧(状態: 録画待ち・取得中・作り直し中・済み・失敗と理由・取り消し。studio を含む)
  POST /live/api/export  {recorder, recording, title, url, transcribe, studio: {video, mark, n, label, start, end}}
                                          スタジオのマークから書き出す(start・end は録画の最初のセグメントの受信時刻からの秒。入口が録画元の status の
                                          firstPdt で絶対時刻にしてマークの正本へ入れる)。P2 の形 {recorder, recording, markId, transcribe} も残す
  POST /live/api/export/cancel  {id}     取り消し
  POST /live/api/adopt  {recorder, recording, start, end, label?, origin?, after?, streamer?}   サーバー側の「マーク + 書き出し」(線 D の M1。入口 0.39.0。
                                          中身は src/flow/live_adopt.py の Adopter。マークの置き場はスタジオ = StudioMarks。RS7-2 G1b)。
                                          画面を閉じていても API だけで書き出しまで通る: スタジオの配信(kind live)を(無ければ)登録して採用のマークを足し
                                          (同じ区間 ±0.5 秒のマークがあれば使い回す)、マークの正本に入れて書き出しのジョブを作る。済んだら入口がスタジオのマークを「書き出し済み」にする。
                                          start・end = 録画の最初のセグメントの受信時刻からの秒(数)か、絶対時刻(UTC の文字列)。origin = manual(既定)・auto・archive
                                          (ジョブ・.clip.json・live_feedback.jsonl に残す。自動の採用は「良い」に数えない)。after が無ければホームの設定 live.auto.after
                                          → {job, video, mark, origin, existing}(existing = 同じマークの書き出しが途中か済みなので、新しく作らなかった)
  POST /live/api/archive  {recorder, recording}   アーカイブで本番版に作り直す(P4。中身は src/flow/live_archive.py)。対象の全部を順番に入れる → {ok, queued, message}。
                                          対象が無い・アーカイブがまだ使えない → 409 と文(アーカイブの用意は yt-dlp で確かめる。10 分は前の結果を使う)
  POST /live/api/archive/cancel  {recorder, recording}  作り直しの取り消し → {ok, cancelled}(済んでいない分は速報版のまま)
  GET  /live/api/exports の各ジョブの failure {kind, kindLabel, text}(失敗したときだけ。書き出し・まとめて実行へ渡す・文字起こし・パック。M3。
       文は src/flow/live_failures.py の failure_of だけが作り、「調子」の live.failures と同じ)・
  GET  /live/api/exports の各ジョブの archive {state, label, message, progress, offset, residual, at, auto, …}・
       ?recorder=&recording= を付けたときは応答に archiveInfo {ready: true|false|null, checkedAt, message}(その録画のアーカイブの用意)
  録画を自動で消す(P4。中身は src/manage/keep/live_cleanup.py。設定 live.autoDelete・既定オン): 見回り(tick)と、本番版への作り直しが1本済んだとき。
       消した録画のジョブには recordingDeleted(スタジオの画面が「録画は消しました」と出す)。録画元の …/delete は入口のこの処理だけが呼ぶ
  ディスクの見張り(線 D の M4。入口 0.40.0): 「調子」の live.disk {state: ok|warn|low, rows, message}(書き出し先・パック・live\\work の空き。
       20 GB 未満で注意・5 GB 未満で新しい書き出し・文字起こしを「空き待ち」。中身は src/flow/live_export.py の Exporter.disk)
  配信後の全自動(線 D の M7。入口 0.40.0。設定 live.autoAfterStream 既定オフ・live.afterStreamPerHour 既定 6。中身は src/flow/live_archive.py):
       録画が終わってアーカイブを使えるようになったら、アーカイブを解析して上位 N を M1 の採用(origin archive)→ 書き出し → 本番版 → 文字起こし → パック。
       進み具合は GET /live/api/exports?recorder=&recording= の archiveInfo.afterStream {state, label, message, at, n, jobs}・失敗は「調子」の live.failures
  GET  /live/api/peaks?recorder=&recording=&since=  ・ POST /live/api/peaks {op: adopt|dismiss|restore, recorder, recording, id}
                                          配信中の盛り上がりの候補(線 D の L2・M11。設定 live.detect・live.autoAdopt 既定オン(0.46.3 から)。中身と形は src/flow/live_detect.py)
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

役割で組み直す RS7-2 G2b(2026-10-11): app でない部分(録画元のクライアント・録画を始める begin/begin_request・受付 submit・見回りの列・子プロセス・「調子」・採用の口)は
src/flow/livesession.py の LiveSession(ライブ係)へ移した。Live はそれを継ぎ、ここに残すのは app の物だけ: HTTP の受け口(handle_get・handle_post)・
中継(_relay)・札(ytt)・スタジオ(studio_call・StudioMarks・書き出しの音量の settings-ui.json)・友人へ届ける(_auto_deliver_for)・D-13(stop_long_requests・
unconfirmed)・組の溜め(flush_pools)・見ていない自動の切り抜きの片付け(expire_unseen)・ホームの設定(prefs)・片付けの部品(Cleaner)・依頼の録画の束(live_bundle)。
自分の配信(スタジオの URL の欄 POST /live/api/begin)も RS8 から録画を始めたときに束を組む(livesession.begin_own。封筒 kind live + own_bundle =
画面の設定の束 + ホームの設定 live + 今のスタジオの解析の設定・書き出しの音量)。録画中に設定を変えても、その録画の検出の感度・枠・採用の待ち・余白・
配信後の解析・書き出しの音量・書き出したあとのエンジン・モデル・カットには効かない(決定 3-31 の b1・b2)。封筒にできない URL(テストの手元の録画元)は束なし。
画面なし(--headless)は use_headless: スタジオなしの採用(LocalMarks)・届けない・D-13 なし・上限は束の adopt.top・空き容量の下限(machine.json の diskMinGB)。
"""
import http.client
import os
import re
import time
import urllib.parse

from manage.cases import txindex
from ytt import datadir, fsio
from flow import live_adopt   # 採用 = マーク + 書き出し(M1)の本体とマークの置き場(RS7-2 G1b。ここはスタジオの置き場 StudioMarks と友人へ届ける hook を渡すだけ)
from flow import live_export   # マークと書き出し。P2
from flow import livesession   # ライブ係(RS7-2 G2b。Live はこれを継ぐ app の殻)
from manage.keep import live_cleanup   # 録画を自動で消す。P4
from human.friend import live_requests  # noqa: E402  (友人のライブ配信の依頼と録画の結びつき。docs/spec/friend-intake.md の 2-15)
from human.friend import deliver as deliver_mod  # noqa: E402  (自動の切り抜きを友人へ届けるときの依頼 id の形)
from human.friend.intake import OUT_DIR  # noqa: E402  # lint: keep 別名(RS3-3。差し替えない定数)= (見張るフォルダの 出力\ = 友人のアプリの「受け取る」が読む)

CODE_DIR = os.path.dirname(os.path.abspath(__file__))
VENDOR_DIR = os.path.join(CODE_DIR, "vendor")
PAGES = {"/live/hls.min.js": ("hls.min.js", VENDOR_DIR)}   # 部品だけ(画面はスタジオ。P3)
TYPES = {".js": "application/javascript; charset=utf-8"}
TO_STUDIO = ("/live", "/live/", "/live/index.html")       # 以前の録画の画面 → スタジオ
STUDIO_PATH = "/studio/"
RELAY_RE = re.compile(r"^/live/r/([a-z][a-z0-9-]{0,15})/([A-Za-z0-9._/-]{1,200})\Z")
RELAY_POST_RE = re.compile(r"^\d{8}-\d{6}(?:-[A-Za-z0-9_-]{1,24})?/stop\Z")   # POST で中継してよい残り(録画の id/stop だけ。P4 で録画の部品に delete を足したため)
PASS_TYPES = ("application/json", "application/vnd.apple.mpegurl", "video/mp2t")   # 中継で返してよい種類
POOL_EVERY = 60.0      # ライブの切り抜きの組の溜め(まとめて実行の flush_pools)を見る間隔
EXPIRE_EVERY = 600.0   # 見ていない自動の切り抜きの片付け(cases.expire_unseen)を見る間隔(案件の一覧を組み立て直すので、見回りのたびには見ない)


# スタジオの「書き出しの設定」の既定(src/studio/review.js の DEFAULT_SETTINGS の exportVolume・exportLoudness・lag と同じ値。ツールをまたいで import しない)
STUDIO_EXPORT_VOLUME, STUDIO_EXPORT_LOUDNESS, STUDIO_LAG = 75, -14.0, 0
STUDIO_LOUDNESS_CHOICES = (0, -11, -14, -16, -18)   # 0 = そろえない(音量(%)を使う)
STUDIO_LAGS = (0, 2, 3, 5)


def studio_review(root):
    """スタジオが覚えている画面の設定の節 review(スタジオの作業データの settings-ui.json。読むだけ)。読めなければ {}"""
    d = fsio.read_json_or(os.path.join(datadir.resolve("studio", root), "settings-ui.json"), None, kind=dict)
    r = d.get("review") if d else None
    return r if isinstance(r, dict) else {}


def studio_audio(root):
    """書き出しの音量の設定(スタジオの書き出しの設定と同じ値を使う。sanitizeSettings(src/studio/review.js)と同じ丸め方):
    -> {"volume": 1〜200(%。既定 75), "loudness": -11|-14|-16|-18(LUFS)か None(そろえない)}。loudness があるときは音量(%)は使わない。
    束の無い録画の書き出し・自分の配信の束(livesession.own_bundle が録画を始めたときに写す)・/live/api/info が使う(束のある録画は束の export。決定 3-31 の b2)"""
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


class Live(livesession.LiveSession):
    def __init__(self, prefs, root, logs_dir, log=None, python=None, data_dir=None, watch_sec=livesession.WATCH_SEC, spawn=True,
                 store_dir=None, out_dir=None, runner=None, audio=None, server=None, archive_opts=None, cleanup_opts=None):
        """prefs: src/home/prefs.py の Prefs。data_dir: 手元の録画の部品の作業データ(テスト用。既定 recorder_data_dir)。
        store_dir: マークと書き出しの記録(既定 入口の作業データの live)。out_dir(): 書き出し先(既定 スタジオの書き出し先)。
        runner(): 文字起こしへ渡す まとめて実行(既定 入口の server.autorun。画面の要求が来たときに覚える)。
        audio(): 束の無い録画の書き出しの音量の設定 {"volume", "loudness"}(既定 スタジオの書き出しの設定 = studio_audio)。
        server: 入口のサーバー(取り込んだスタジオの API を呼ぶ = P4 の作り直し。画面の要求が来る前の自動の作り直しでも使えるように、入口が渡す)。
        archive_opts: src/flow/live_archive.py の Archiver へ渡す引数(テスト用: studio・probe・fetch・間隔)。
        cleanup_opts: src/manage/keep/live_cleanup.py の Cleaner へ渡す引数(テスト用: 24 時間・7 日・見回りの間隔を縮める)"""
        self.prefs = prefs
        self._server = server
        self.headless = False              # 画面なし(use_headless)
        log = log or (lambda m: None)
        store_dir = store_dir or os.path.join(os.path.dirname(logs_dir), "live")
        super().__init__(root, logs_dir, requests=live_requests.Store(os.path.join(store_dir, "requests.json"), log=log), log=log, python=python,
                         data_dir=data_dir, watch_sec=watch_sec, spawn=spawn, store_dir=store_dir, out_dir=out_dir,
                         runner=runner or (lambda: getattr(self._server, "autorun", None) if self._server is not None else None),
                         audio=audio or (lambda: studio_audio(self.root)), archive_opts=archive_opts, cleanup_opts=cleanup_opts,
                         # 採用(M1)のマークの置き場 = 取り込んだスタジオ(呼ぶときに self.studio_call を読む = テストの差し替えが効く)。画面なしは LocalMarks(use_headless)
                         marks=live_adopt.StudioMarks(lambda method, path, body=None: self.studio_call(method, path, body)),
                         deliver_for=self._auto_deliver_for)
        self._stop_said = set()            # D-13: 6 時間で止められなかった録画(記録に 1 回だけ)
        self._expire_at = 0.0              # 見ていない自動の切り抜きの片付けを最後に見た時刻(EXPIRE_EVERY ごと)
        self._pool_at = 0.0                # 組の溜めの残りを最後に見た時刻(POOL_EVERY ごと)

    def use_headless(self, disk_min_gb=None):
        """画面なし(launch.py --headless。plan/f1-friend-pc.md の決めたこと 6・7): 設定に関わらずオン・どの封筒も依頼の決まりで(検出・採用・パックまで)・
        スタジオなしの採用(LocalMarks)・友人へ届けない・D-13 なし(未確認で休まない・6 時間で止めない・同時の上限なし)・自動の採用の上限は束の adopt.top・
        空き容量が disk_min_gb(GB)より少なければ新しい録画を始めない"""
        self.headless = True
        self.always_on = self.request_all = True
        self.disk_min_gb = disk_min_gb
        self.marks = live_adopt.LocalMarks(lambda: self.exporter)
        self.adopter.deliver_for = None
        self.unconfirmed = None
        self.auto_max = self.bundle_top

    # --- 設定 ---
    def _load_cfg(self):
        """ホームの設定の節 live"""
        return self.prefs.get(["live"])["live"]

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

    def _make_cleaner(self):
        """録画を自動で消す(src/manage/keep/live_cleanup.py。P4。設定 live.autoDelete)"""
        kw = dict({"enabled": self.auto_delete, "studio": self.studio_call, "log": self.log,
                   "hold": lambda rc, r: self.archiver.after_stream_hold(rc, r)}, **self.cleanup_opts)   # 配信後の全自動(M7)がまだの録画は消さない
        return live_cleanup.Cleaner(self, **kw)

    def _pack_info(self, path):
        return txindex.pack_info(path)   # パックの有無の規則は txindex だけ(live_archive は読まない)

    def _request_limit(self):
        return None if self.headless else live_requests.MAX_ACTIVE   # 友人の PC は同時の上限なし(決めたこと 7)

    def _request_label(self, item):
        return live_requests.settings_label(item["settings"])

    def _request_watch(self):
        return [] if self.headless else [("友人の依頼の録画の上限の見回りでエラー", self.stop_long_requests)]   # D-13: 友人の依頼の録画は 1 依頼 6 時間まで

    def _app_watch(self):
        if self.headless:   # 友人の PC は届けない・③④ の片付けは画面なしでは動かさない
            return []
        return [("届け方の組の見回りでエラー", self.flush_pools),   # n 本の組で届けるライブの切り抜き: 録画が終わったら残りも届ける(10-09 ユーザー決定)
                ("見ていない自動の切り抜きの片付けでエラー", self.expire_unseen)]   # 3 日見ない自動の切り抜きはごみ箱へ(10-09 ユーザー決定。オフでも前の分は片付ける)

    # --- 束(RS7-2 G2b) ---
    def _bundle_base(self):
        """録画を始めるときの束の土台 = 画面の設定から組む束(まとめて実行の build_spec = スタジオ・編集の設定ファイル + この PC の設定)。組めなければ None(束の既定)"""
        r = self.runner()
        if r is not None and hasattr(r, "build_spec"):
            try:
                return r.build_spec()[0]
            except Exception as e:   # noqa: BLE001  (組めなければ束の既定 = 各ツールの既定)
                self.note("リアルタイム切り抜き: 録画の束を画面の設定から組めませんでした(既定で続けます): %r" % (e,))
        return None

    def live_bundle(self):
        """友人の依頼の録画を始めるときの束の土台 = _bundle_base + ホームの設定 live の
        検出・採用の待ち・余白・書き出したあとのエンジン・モデル・カット(決定 3-31 の仮 b1・b3。livesession.cfg_bundle)。
        自分の配信の束は livesession の own_bundle(これに今のスタジオの解析の設定・書き出しの音量を重ねる。RS8)"""
        return livesession.cfg_bundle(self._bundle_base(), self.cfg())

    def submit_request(self, url, ctx):
        """友人のライブ配信の依頼(src/human/friend/intake.py の live_begin。2-15): 欄 ctx から封筒 + 束(自分の配信と同じ束に依頼の設定・
        自動の採用の上限 live_requests.TOP_DEFAULT を明示)を組んで submit へ。requests.json は ctx のまま。-> {"recorder", "recording", "existing"}"""
        try:
            env = livesession.live_envelope(url, ctx.get("title"), request_id=ctx.get("rid"), deliver_dir=ctx.get("deliverDir"), batch=ctx.get("deliverBatch"),
                                            streamer=ctx.get("streamer"), note=ctx.get("memo"), eid=ctx.get("rid"))
        except ValueError:   # 封筒にできない URL(テストの手元の録画元など): 束なしで今までどおり
            return self.begin_request(url, ctx)
        out = self.submit(env, livesession.request_bundle(ctx, self.live_bundle(), top=live_requests.TOP_DEFAULT), ctx=ctx)
        return {k: out[k] for k in ("recorder", "recording", "existing")}

    # --- 画面と中継(launch.py の PortalHandler から) ---
    def handle_get(self, h, u):
        """GET /live…。オフなら False(入口の今までどおりの 404 になる)"""
        with self.cfg_scope():
            return self._handle_get(h, u)

    def _handle_get(self, h, u):
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
        if u.path == "/live/api/peaks":   # 配信中の候補(L2。src/flow/live_detect.py)
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
            h._json(200, {"enabled": True, "folder": cfg.get("folder") or "", "defaultFolder": livesession.DEFAULT_FOLDER,
                          "audio": self.audio(), "lag": studio_lag(self.root),   # 書き出しの音量(スタジオと同じ)・反応の遅れ補正の最初の選び方(スタジオの値)
                          "recorders": [{"id": r["id"], "name": r["name"], "url": r["url"], "local": livesession.is_local_url(r["url"])}
                                        for r in self.recorders(cfg)]})
            return True
        m = RELAY_RE.match(u.path)
        if m and ".." not in m.group(2) and "//" not in m.group(2):
            self._relay(h, "GET", m.group(1), m.group(2), u.query)
            return True
        h._fail(404, "not_found", "その場所はありません")
        return True

    def handle_post(self, h, u, body):
        """POST /live…(入口の合言葉・Origin の検査と本文の読み取りは launch.py が済ませてある)。オフなら False"""
        with self.cfg_scope():
            return self._handle_post(h, u, body)

    def _handle_post(self, h, u, body):
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
        """録画を始める(P3)・書き出し(P2・P3)・採用(M1)"""
        try:
            if path == "/live/api/begin":
                return h._json(200, self.begin_own(body.get("url")))   # 自分の配信も録画を始めたときに束を組む(RS8。flow/livesession.py の begin_own)
            ex = self.exporter
            if path == "/live/api/export":
                if "studio" in body:   # スタジオのマークから(P3)
                    return h._json(200, {"job": self.export_studio(body)})
                auto = self.auto_cfg(body.get("recorder"), body.get("recording"))
                after, streamer = live_export.check_after(body, auto["after"]), live_export.check_streamer(body.get("streamer"))
                return h._json(200, {"job": ex.add(body.get("recorder"), body.get("recording"), body.get("markId"), after != "none",
                                                   after=after, streamer=streamer, origin=live_export.check_origin(body.get("origin")), auto=auto)})
            if path == "/live/api/adopt":   # サーバー側の「マーク + 書き出し」(M1)
                return h._json(200, self.adopt(body))
            if path == "/live/api/peaks":   # 配信中の候補の採用・見送り・戻す(L2。src/flow/live_detect.py)
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

    # --- 友人へ届ける・D-13・片付け(入口の物) ---
    def flush_pools(self, force=False):
        """まとめて実行の組の溜め(src/home/autorun.py の flush_pools)の残りを届ける見回り。その録画が終わり、書き出しの途中・受け渡し待ちが無ければ「もう作らない」。
        -> 届けた本数"""
        now = time.time()
        if not force and now - self._pool_at < POOL_EVERY:
            return 0
        self._pool_at = now
        ar = self.runner()
        if ar is None or not hasattr(ar, "flush_pools") or not ar.pools():
            return 0
        active = {(r["recorder"], r["id"]) for r in self.list_recordings() if r.get("active")}
        ex = self.exporter
        with ex.lock:
            busy = {(j.get("recorder"), j.get("recording")) for j in ex.jobs if j.get("state") in live_export.ACTIVE or j.get("handoffWait")}

        def done(meta):
            key = (meta.get("recorder"), meta.get("recording"))
            return key not in active and key not in busy
        return ar.flush_pools(done)

    def expire_unseen(self, force=False):
        """見ても届けてもいない自動の切り抜きを、作ってから cases.EXPIRE_SEC(3 日)で片付ける(src/manage/cases/cases.py の expire_unseen。EXPIRE_EVERY ごと)。
        部品(ごみ箱フォルダ・届ける仕組み・非表示)は入口のサーバーから。入口から作られていないとき(テスト)は何もしない。-> 片付けた [(案件, マーク)]"""
        srv, now = self._server, time.time()
        if srv is None or (not force and now - self._expire_at < EXPIRE_EVERY):
            return []
        self._expire_at = now
        from manage.cases import cases as cases_mod   # 呼ぶときに読む(cases は入口の部品。live を読み込むテストを重くしない)
        prefs = getattr(srv, "prefs", None)
        done = cases_mod.expire_unseen(self.root, self.studio_call, self.exporter.feedback, getattr(srv, "cleanup", None),
                                       (lambda tid: prefs.hide("transcripts", [tid], True)) if prefs is not None else None, getattr(srv, "deliveries", None),
                                       is_request=lambda rc_id, rec: self.requests.get(rc_id, rec) is not None)
        if done:
            self.log("リアルタイム切り抜き: 見ないまま %d 日たった自動の切り抜き %d 本をごみ箱フォルダへ移しました(%s)" % (
                int(cases_mod.EXPIRE_SEC // 86400), len(done), "・".join("%s/%s" % k for k in done[:5])))
        return done

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
            code, d = self.call(rc, "POST", "/live/%s/stop" % rec, {}, timeout=livesession.STOP_TIMEOUT)
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

    def deliver_dir(self):
        """友人へ届ける所(依頼の受付の Dropbox のフォルダの 出力 の中)。決まっていなければ None"""
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

    # --- P3: スタジオから ---
    def export_studio(self, body):
        """POST /live/api/export の studio の形(P3)。-> ジョブ"""
        studio = live_export.check_studio(body.get("studio"))
        rc_id, rec = body.get("recorder"), body.get("recording")
        auto = self.auto_cfg(rc_id, rec)
        after, streamer = live_export.check_after(body, auto["after"]), live_export.check_streamer(body.get("streamer"))   # 録画元に聞く前に検査する
        origin = live_export.check_origin(body.get("origin"))
        rc = self._ids(rc_id, rec)
        req, after, streamer = self._request_for(rc_id, rec, origin, after, streamer)   # 友人の依頼の録画なら、人のマークも届ける(2-15)
        _d, first = self._rec_status(rc, rc_id, rec)
        return self.exporter.add_studio(rc_id, rec, studio, first, body.get("transcribe") is not False,
                                        url=body.get("url") if isinstance(body.get("url"), str) else None,
                                        title=body.get("title") if isinstance(body.get("title"), str) else None,
                                        after=after, streamer=streamer, origin=origin, auto=auto, request=req)

    # --- 画面の共通の API api/ytt/live(launch.py の PortalServer.ytt_api から。全ツールのヘッダーの札) ---
    def ytt(self, body):
        """-> (HTTP の番号, JSON)"""
        with self.cfg_scope():
            return self._ytt(body)

    def _ytt(self, body):
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
            code, d = self.call(rc, "POST", "/live/%s/stop" % body["recording"], {}, timeout=livesession.STOP_TIMEOUT)
            self._recent = None
            if code == 200 and isinstance(d, dict):
                self.log("リアルタイム切り抜き: 録画を止めました %s" % body["recording"])
                return 200, {"ok": True, "recording": livesession.rec_view(d.get("recording") or {})}
            if code is None:
                return 502, {"error": "recorder_down", "message": str(self._down(rc))}
            msg = (d or {}).get("message") if isinstance(d, dict) else ""
            return (404 if code == 404 else 502), {"error": "not_found" if code == 404 else "recorder_bad", "message": msg or "止められませんでした(HTTP %s)" % code}
        return 400, {"error": "bad_request", "message": "op は status か stop です"}

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
