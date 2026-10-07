"""まとめて実行(統合計画の段階5。2026-09-26)。入口の「案件」の画面から、配信1本ぶんの作業を順に自動で流す。

形は3つ(ユーザー決定「選べるようにする」):
  full        解析から全部   … (未解析なら)解析 → 自動マークの上位を採用 → 書き出し → 文字起こし → Resolve パック
  adopted     採用後を全部   … 採用したマークの書き出し → 文字起こし → Resolve パック(切り抜きの良し悪しは人が決める)
  transcribe  文字起こしまで … 採用したマークの書き出し → 文字起こし(パックは校正してから人が作る)

作り:
- 各ツールの**公開している API を HTTP で呼ぶ**(入口と同じ 127.0.0.1。取り込んだツールは入口のポートの /studio/ など、子プロセスのツールはそのポート)。
  ツールの中の関数を直接呼ばないのは、画面から使うときと同じ検査・同じジョブ管理(重い処理の順番待ち ytt_core.jobs を含む)を通すため。
- どの段も「まだ無いものだけ」作る(書き出し済み・文字起こし済み・パック済みは飛ばす)。途中で止めても、もう一度押せば続きから進む。
  文字起こしの有無は ytt_core.txindex(案件の画面・スタジオのセリフと同じ規則)、パックの有無は cases.find_pack で見る。
- スタジオの ① 探す で選んだ配信(まだスタジオに無い YouTube の配信)は start_new で「解析から全部」に入れる。解析のキューに入れると
  スタジオに配信ができるので、それまでは受け取った題名で進める(git の履歴(679ff01 以前)の docs/archive/followup-2026-09-27.md の 5)。
- 1本ずつ順に処理する(キュー)。同じ配信を2つ同時には入れない。
- 入口の起動し直しで、順番待ち・実行中の分を戻す(線 D の M5。入口 0.40.0): 待ち・実行中の実行を入口の作業データの logs/autorun-active.json に残し
  (入れたとき・始めたとき・段が済むたび・終わったとき。一時ファイルから置き換える)、起動したときに読んで同じ id のまま「待ち」に戻す。
  済んだ段は飛ばし、途中だった段は頭からやり直す(どの段も「まだ無いものだけ」作るので、続きから進む)。入口の終了(「すべて終了」・黒い画面を閉じる・
  強制終了)で止まった実行は記録(autorun-runs.jsonl)に「中止」と書かない。起動し直してすぐはツールの準備を待つ(RESUME_WAIT 秒まで)。
  RESTORE_MAX_AGE(7 日)より前に入れた実行は戻さず、記録に「中止」と書く。あとから解析(post_analyze)は今までどおり一覧(autorun-deferred.json)で続く
- 終わった実行は、入口の作業データの logs/autorun-runs.jsonl に1行ずつ残す(段2 B-6。入口を起動し直しても、ホームで前回の結果と止まった理由を見られる)。
  書くのは終わったとき(完了・失敗・中止)だけ(入口の終了で止まった実行は、次の起動で続けるので書かない = M5)。
  1MB を超えたら .1 に回す(1世代。画面のエラーの記録 clientlog.py と同じ形)。書けなくても実行は止めない
- 自動で採用したマークは、人の判定ではないので学習の記録(スタジオの feedback)に入れない(スタジオの /api/video/adopt-top)。
- 解析の設定は既定値(解析の画面の設定はブラウザの中にしか無いため)。書き出しはスタジオの ③ の設定(画質・音量のそろえ方)、
  文字起こしは「編集」(文字起こし)の設定(モデルなど)を使う。パックは、「編集」でカットを決めてあればそのとおり(cut2resolve の spec.keeps。
  作った記録も「編集」に残す = 作り直しの知らせ)、無ければ文字起こしの行だけを残す規則(preset transcript-rows)。どちらも Text+(字幕の元の行が無ければ Text+ なし)。
- あとから解析(測るため。2026-10-05 ユーザー決定): 友人の依頼(URL)が区間だけ(解析の段を外した形)で終わったら、その配信を「あとから解析する一覧」
  (入口の作業データの logs/autorun-deferred.json。起動し直しても続く)に足す。まとめて実行の待ち・実行中が無くなったら、一覧から1本ずつ
  スタジオの保存した設定で解析する(mode post_analyze)。友人の区間(人が自動の候補を見ずに選んだ見どころ)と自動の候補を比べて検出の見逃しを測るためだけで、
  友人には何も届けない・依頼の受付の記録も変えない。新しい実行が入ったら、すぐ止めて(スタジオの解析も取り消す)一覧に戻し、新しい実行を先にする。
  14 日たったもの・3 回失敗したものは捨てる(理由は一覧のファイルの dropped に残す)。環境変数 YTT_DEFER_ANALYZE=off で止める(足さない・始めない)
"""
import collections
import http.client
import json
import os
import re
import urllib.parse
import threading
import time
import uuid

from ytt_core import colors, fsio, txindex
import clientlog  # noqa: E402  (記録のファイルに 1 行ずつ書く形は 1 か所)
import deliver as deliver_mod  # noqa: E402  (① 全自動のパックを zip にして届ける。名前の整え方も同じ)

MODES ={"full": "解析から全部", "adopted": "採用後を全部", "transcribe": "文字起こしまで"}
STEP_LABELS = {"analyze": "解析", "adopt": "採用(自動)", "export": "書き出し", "transcribe": "文字起こし", "pack": "パック",
               "deliver": "Dropbox へ届ける", "diarize": "話者分離"}
MODE_STEPS = {"full": ("analyze", "adopt", "export", "transcribe", "pack"), "adopted": ("export", "transcribe", "pack"),
              "transcribe": ("export", "transcribe"), "doc": ("transcribe", "pack"),
              "request": ("analyze", "adopt", "export", "transcribe"), "file": ("transcribe",),
              "request_auto": ("analyze", "adopt", "export", "transcribe", "pack", "deliver"), "request_manual": ("analyze",),
              "file_auto": ("transcribe", "pack", "deliver"), "file_manual": ("analyze",), "post_analyze": ("analyze",)}
# 友人からの依頼(src/home/intake.py。docs/spec/friend-intake.md)の形。ホームの画面の「まとめて実行」の選択肢には出さない(MODES に入れない)。
# 友人が送るときに選ぶ(2026-10-01 ユーザー決定): ① 全自動 auto = パックまで作って Dropbox の 出力\ へ / ② 軽く確認 check = 文字起こしまで /
# ③ 全部人が行う manual = 解析まで。request* = 配信の URL(解析 → 上位 N 個を採用 → 書き出し → …)/ file* = 友人が切り抜いた動画
REQUEST_MODES = {"request_auto": "依頼 ① 全自動: 解析 → パック", "request": "依頼 ② 軽く確認: 解析 → 文字起こし", "request_manual": "依頼 ③: 解析まで",
                 "file_auto": "依頼 ① 全自動: 文字起こし → パック", "file": "依頼 ② 軽く確認: 文字起こし", "file_manual": "依頼 ③: スタジオで解析まで"}
# 友人が時刻で指定した区間(送るアプリ 2.0.0。docs/spec/friend-intake.md の 2-6): 前後に余白を足してスタジオの手動マーク(採用)にする。
# 区間が切り抜く数(top)に足りない分だけ、自動マークの上位で埋める(スタジオの /api/video/request-marks)
REQUEST_URL_MODES = ("request", "request_auto")
RANGE_PAD = 2.0          # 区間の前後に足す秒(ぴったり指定すると頭の一言が欠けやすいため。2026-10-02 ユーザー決定: 自動で付ける)
RANGE_MAX = 10           # 1本の配信の区間の数(スタジオの MAX_REQUEST_RANGES と同じ)
RANGE_MAX_SEC = 3600     # 1つの区間の長さ(スタジオの MAX_MARK_SEC と同じ)
CUTS = ("none", "silence")          # 友人が選べるカットの方法(① 全自動のパック)
TX_ENGINES = ("faster-whisper", "whisper.cpp", "qwen3-asr", "llama.cpp")   # 文字起こしのエンジンを実行ごとに選ぶとき(リアルタイム切り抜きの live.auto。M2)。editor の tx_engines の id
TX_MODEL_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,59}\Z")             # 同じくモデルの名前(src/home/prefs.py の LIVE_MODEL_RE と同じ形)
WEIGHT_KEYS = ("wAudio", "wChat", "wComments")   # 解析の重み(スタジオの解析の設定と同じ名前。0〜3)
FLOW_MODES = {"url": {"auto": "request_auto", "check": "request", "manual": "request_manual"},
              "file": {"auto": "file_auto", "check": "file", "manual": "file_manual"}}
# 文書単位の実行(docs/design/edit-tool-design.md の 12 ⑦(b)): 「編集」の履歴で選んだ文書を、行が無ければ文字起こし → パック。
# カットがある文書はカットのとおり(ユーザー決定 2026-09-27。配信単位の実行と同じ)。パックがあるときは既定で飛ばす(overwrite で上書き)
# 状態の言葉(気が利く画面へ 段4。どの入口の画面もこの言葉で出す = snapshot の labels)
STEP_STATE_LABELS = {"wait": "待ち", "run": "実行中", "done": "済み", "skip": "飛ばした", "warn": "一部失敗", "error": "失敗"}
RUN_STATE_LABELS = {"queued": "待ち", "running": "実行中", "done": "済み", "error": "失敗", "cancelled": "中止", "nothing": "やることがありませんでした"}
NOTHING_MESSAGE = "やることがありませんでした"
DOC_MODE = "doc"
MAX_MARKS = 50   # マークを選んだ実行で選べる数(スタジオの書き出しの1回の上限と同じ)
DOC_LABEL = "文字起こし → パック"
DEFAULT_TOP = 3
MAX_NEW = 10           # ① 探す から一度に入れられる配信の数(① 探す で選べる最大と同じ)
MAX_KEEP = 30          # 終わった記録を残す数(メモリ。ファイルの記録は下の RUNS_LOG)
RUNS_LOG = "autorun-runs.jsonl"   # 終わった実行の記録(入口の作業データの logs の中。段2 B-6)
LOG_VERSION = 1        # 記録の1行の形の版(v)
LOG_MAX_BYTES = 1024 * 1024   # これを超えたら .1 に回す(1件 1〜2KB なので 500〜1000 件ぶん)
LOG_READ_BYTES = 256 * 1024   # 起動時に読む末尾の大きさ(前回の結果 past を作る)
PAST_MAX = 50          # snapshot の past(配信・文書ごとの前回の結果で、メモリに無いもの)の数
PAST_KEEP = 500        # past の元として覚えておく配信・文書の数
HISTORY_DEFAULT, HISTORY_MAX = 50, 200   # /api/autorun/history の limit の既定と上限
PAST_KEYS = ("id", "kind", "docId", "videoId", "title", "mode", "modeLabel", "state", "stateLabel", "nothing", "message", "error",
             "created", "finished", "steps")   # past に入れる項目(2〜15 秒ごとの問い合わせを重くしない。全部は history で)
MAX_WAITING = 20       # 順番待ちの上限
BUSY_WAIT = 5.0        # スタジオの書き出しが別の書き出しで塞がっているときの待ち間隔
TX_KEYS = ("model", "language", "quality", "device", "vadMode", "boost", "autoDict", "wordSplit", "stripPunct", "autoGloss", "autoLearned", "glossary",
           "autoRedo", "redoLarge")   # autoRedo・redoLarge = 疑わしい所を自動で認識し直す(12 ③-2)
# あとから解析(測るため。2026-10-05)。画面の選択肢・依頼の形とは別(MODES・REQUEST_MODES に入れない = API からは始められない)
POST_MODE = "post_analyze"
OTHER_MODES = {POST_MODE: "あとから解析(測るため)"}
DEFER_FILE = "autorun-deferred.json"   # あとから解析する配信の一覧(入口の作業データの logs の中。実行の記録 RUNS_LOG の隣)
DEFER_VERSION = 1
DEFER_ENV = "YTT_DEFER_ANALYZE"        # off = 一覧に足さない・始めない(テスト・困ったとき用)
DEFER_KEEP_SEC = 14 * 24 * 3600        # 足してからこれだけたったら捨てる
DEFER_MAX_TRIES = 3                    # これだけ失敗したら捨てる
DEFER_RETRY_SEC = 30 * 60              # 失敗したあと、次に試すまで(すぐ3回失敗して捨てないため)
DEFER_IDLE_SEC = 60.0                  # 待ち・実行中が無くなってから始めるまで(画面で続けて押している途中に始めて、すぐ止めることを減らす)
DEFER_DROPPED_KEEP = 50                # 捨てたものの記録(理由)を残す数
DEFER_READ_MAX = 1024 * 1024
DEFER_IMPORT_DAYS = 30                # 以前の依頼の取り込み(起動のあと1回): 終わってからこの日数以内
DEFER_IMPORT_MAX = 20                  # 同じく、新しい順にこの本数まで
# 友人の区間の長さを、依頼の自動の候補の長さに使う(2026-10-05 ユーザーの要望。仮の決定 = まとめ役)。
# 測る道具 dev/eval_marks.py --json の結果(スタジオの作業データ evals\marks\<日時>.json。入口の夜の自動測定が流す)の clipLength を読むだけ
FRIEND_LENGTH_ENV = "YTT_FRIEND_LENGTH"   # off = 使わない(ホームの設定 autorun.friendLength が false でも使わない)
FRIEND_LENGTH_MIN_SAMPLES = 20         # 友人の区間の見本の数(外れ値を除く)
FRIEND_LENGTH_MIN_VIDEOS = 5           # その配信の数
FRIEND_PRE_MIN_SAMPLES = 10            # 山の位置(preRatio)を使う見本の数
FRIEND_LENGTH_MAX_AGE = 30 * 86400     # 結果のファイルの古さ(ファイル名の日時)
FRIEND_LENGTH_RANGE, FRIEND_PRE_RANGE = (10, 120), (0.3, 0.9)   # スタジオの解析の設定 length・preRatio の範囲(src/studio/analyze.py の validate_settings)
EVAL_MARKS_NAME_RE = re.compile(r"^(\d{8}-\d{6})(?:_auto)?\.json\Z")   # src/home/accuracy.py の RESULT_NAME_RE と同じ形
EVAL_READ_MAX = 16 * 1024 * 1024
CANCEL_WAIT = 30.0                   # 取り消したスタジオの解析が止まるのを待つ秒(次の実行が同じ配信の解析を始められるように)
# 入口の起動し直しで戻す(線 D の M5。2026-10-07)
ACTIVE_FILE = "autorun-active.json"  # 待ち・実行中の実行(入口の作業データの logs の中。RUNS_LOG の隣)
ACTIVE_VERSION = 1
ACTIVE_READ_MAX = 4 * 1024 * 1024
RESTORE_MAX_AGE = 7 * 86400          # これより前に入れた実行は戻さない(記録に「中止」と書く)
RESUME_WAIT = 120.0                  # 戻した実行は、使うツールが動くまでこれだけ待つ(入口の起動の直後はまだ準備中のことがある)
DONE_STEPS = ("done", "skip", "warn")   # 済んだ段(戻した実行では飛ばす)
STEP_TOOLS = {"analyze": ("studio",), "adopt": ("studio",), "export": ("studio",), "transcribe": ("transcribe",), "diarize": ("transcribe",),
              "pack": ("transcribe", "cut2resolve"), "deliver": ()}
# 画面の「起動し直す」(launch.py の restart_self。入口 0.41.0)で、ツールの仕事を止めてよい段(起動し直したあとに頭からやり直す = M5)。
# 書き出し(export)は入れない: 書き出し中は今までどおり断る
REDO_STEPS = ("analyze", "transcribe", "diarize", "pack")
TX_ACTIVE = ("queued", "loading", "extracting", "running")   # 「編集」のジョブの動いている状態(src/editor/ed_jobs.py の ACTIVE_STATES)
QUEUE_ACTIVE = ("waiting", "running")                       # スタジオの解析のキューの動いている状態(src/studio/batch.py)
RUN_ID_RE = re.compile(r"^[0-9a-f]{10}\Z")



def _media_is_30fps(path):
    """素材がちょうど 30fps か(ytt_core.normalize の probe。ffprobe が無い・読めないときは False = 設定の値を使う)。2026-10-04 Q1"""
    try:
        from ytt_core import normalize
        info = normalize.probe(path)
    except Exception:
        return False
    fps = (info or {}).get("fps")
    return isinstance(fps, (int, float)) and abs(fps - 30) <= 0.01

TOOL_NAMES = {"studio": "切り抜きスタジオ", "transcribe": "編集", "cut2resolve": "cut2resolve(パックを作る部品)"}   # 知らせの文のツール名


class Cancelled(Exception):
    pass


class StepError(Exception):
    pass


class ToolClient:
    """ツールの API を呼ぶ。endpoint(ツールID) -> (ポート, 場所 "/studio/" など) か None(動いていない)"""

    def __init__(self, endpoint, token="", timeout=60):
        self.endpoint, self.token, self.timeout = endpoint, token, timeout

    def call(self, tool, method, path, body=None):
        """-> (HTTP の状態, JSON)。つながらない・動いていないときは StepError"""
        ep = self.endpoint(tool)
        if not ep:
            # 何が起きたか + 次にすること(S-19。入口 0.42.0)。済んだ段は飛ばすので、もう一度実行すると続きから進む
            raise StepError("%sが動いていないので、この段を進められませんでした。ホームの「詳しく(サーバーの管理)」で%sの状態を見て、"
                            "止まっていれば「起動」を押して(ホームに取り込んだツールは「すべて終了」→ start.bat で起動し直して)から、"
                            "もう一度実行してください(済んだ段は飛ばします)" % ((TOOL_NAMES.get(tool, tool),) * 2))
        port, base = ep
        url = base.rstrip("/") + path
        headers = {"Host": "127.0.0.1:%d" % port}
        data = None
        if body is not None:
            data = json.dumps(body, ensure_ascii=False).encode("utf-8")
            headers["Content-Type"] = "application/json"
        if method != "GET" and self.token:
            headers["X-YTT-Token"] = self.token
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=self.timeout)
        try:
            conn.request(method, url, body=data, headers=headers)
            r = conn.getresponse()
            raw = r.read()
        except OSError as e:
            raise StepError("ツールにつながりませんでした(%s)" % (e.strerror or e.__class__.__name__))
        finally:
            conn.close()
        try:
            obj = json.loads(raw.decode("utf-8")) if raw else {}
        except ValueError:
            obj = {}
        return r.status, obj if isinstance(obj, dict) else {}

    def ok(self, tool, method, path, body=None):
        st, obj = self.call(tool, method, path, body)
        if st != 200:
            raise StepError(obj.get("message") or "エラー(HTTP %d)" % st)
        return obj


def _yt_id_ok(v):
    """YouTube の配信 ID(11文字。スタジオの common.VID_RE と同じ)"""
    return isinstance(v, str) and len(v) == 11 and all(c.isascii() and (c.isalnum() or c in "-_") for c in v)


def _doc_id_ok(v):
    return isinstance(v, str) and 1 <= len(v) <= 40 and all(c.isalnum() or c in "-_" for c in v)


def _num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool) and v == v and abs(v) < 1e7


def _ms_ok(v):
    """エポックのミリ秒の時刻(_num は 1e7 までなので使えない)"""
    return isinstance(v, (int, float)) and not isinstance(v, bool) and v == v and 0 < v < 1e14


def clean_ranges(v):
    """区間の一覧 [(開始, 終了), …](秒)を確かめる。-> 整えた一覧(None・空 = 区間なし)。形が違えば ValueError"""
    if v in (None, [], ()):
        return []
    if not isinstance(v, (list, tuple)) or len(v) > RANGE_MAX:
        raise ValueError("区間は %d 個までです" % RANGE_MAX)
    out = []
    for r in v:
        if not isinstance(r, (list, tuple)) or len(r) != 2 or not _num(r[0]) or not _num(r[1]) or not 0 <= r[0] < r[1] or r[1] - r[0] > RANGE_MAX_SEC:
            raise ValueError("区間の指定が正しくありません")
        out.append((round(float(r[0]), 1), round(float(r[1]), 1)))
    return out


def clean_weights(v):
    """解析の重み {"wAudio", "wChat", "wComments"}(0〜3)-> 小数1桁に整えたもの か None(指定なし・形が違う)"""
    if not isinstance(v, dict) or not all(_num(v.get(k)) and 0 <= v[k] <= 3 for k in WEIGHT_KEYS):
        return None
    return {k: round(float(v[k]), 1) for k in WEIGHT_KEYS}


def pad_range(s, e, duration=None):
    """友人が入れた区間の前後に余白を足す(0 より前・動画の長さより後には出さない。長さの上限を超えるときは余白を減らす)"""
    pad = min(RANGE_PAD, max(0.0, (RANGE_MAX_SEC - (e - s)) / 2))
    a, b = max(0.0, s - pad), e + pad
    if duration and duration > 0:
        b = min(b, float(duration))
    return [round(a, 1), round(max(b, a + 0.1), 1)]


def _top_arg(top):
    """採用する数(未指定は DEFAULT_TOP)。1〜30 でなければ ValueError"""
    if top in (None, ""):
        return DEFAULT_TOP
    if not isinstance(top, int) or isinstance(top, bool) or not (1 <= top <= 30):
        raise ValueError("採用する数は1〜30です")
    return top


def _busy_reason(active, same, what=""):
    """順番待ちに入れられない理由(入れられれば None)。same(実行) = 同じ配信・文書・動画か。what = 理由の頭(「この配信は」など)"""
    if any(same(r) for r in active):
        return what + "すでに実行中・順番待ちです"
    if len(active) >= MAX_WAITING:
        return "順番待ちが多すぎます(%d本まで)" % MAX_WAITING
    return None


class Run:
    def __init__(self, video_id, title, mode, top, doc_id=None, overwrite=False, streamer=None, marks=None, fresh=None, on_fail="next",
                 source_path=None, request_id=None, deliver_dir=None, speakers=None, video_tracks=None, ranges=None, cut=None, weights=None, duration=None,
                 engine=None, model=None):
        self.id = uuid.uuid4().hex[:10]
        self.engine = engine if engine in TX_ENGINES else None   # 文字起こしのエンジン(None = 編集の設定のまま。リアルタイム切り抜きの live.auto。M2)
        self.model = model if isinstance(model, str) and TX_MODEL_RE.match(model) else None   # 同じくモデル(None = 編集の設定のまま)
        self.ranges = list(ranges or [])   # 友人が時刻で指定した区間 [(開始, 終了)](余白の前。URL の依頼 ①②。足りない分は自動で埋める)
        self.cut = cut if cut in CUTS else None   # 友人が選んだカットの方法(① のパック。None = ホームの設定)
        self.weights = weights             # 友人が指定した解析の重み(None = スタジオの設定のまま)
        self.friend_length = None          # 解析に使った「友人の区間の実績からの長さ」{"length", "preRatio"?, "file", "samples", "videos"}(使ったときだけ)
        self.duration = duration           # 受付のときに調べた配信の長さ(秒。スタジオにまだ無い配信の区間を端で切るのに使う)
        self.video_tracks = video_tracks   # 友人が選んだ Resolve の映像トラックの数(2〜5。① 全自動のパック。None = 編集の既定 = 1。2026-10-02)
        self.speakers = speakers         # 友人が入れた「配信者」{"count", "names", "styles"?: {名前: {"color": "#RRGGBB"}}}。あれば文字起こしのあとに話者分離(2026-10-01)。styles = 字幕の色(文書に覚え、パックにも渡す)
        self.new_docs = []               # この実行で文字起こしした文書(話者分離はこれだけ。前からある文書の話者は人が直したかもしれない)
        self.deliver_dir = deliver_dir   # ① 全自動: パックを zip にして置く所(Dropbox の 出力\)。失敗したら理由の .txt も
        self.packs = []                  # この実行で作ったパックのフォルダ
        self.delivered = []              # 届けたパックのフォルダ(同じものを2回置かない)
        self.source_path = source_path   # 依頼の動画(mode file。作業データへコピーしたもの)
        self.request_id = request_id     # 友人からの依頼の id(src/home/intake.py)
        self.video_id, self.title, self.mode, self.top = video_id, title, mode, top
        self.doc_id, self.overwrite = doc_id, bool(overwrite)   # overwrite = パックがあれば作り直す(文書単位も配信単位も。段4 S-12)
        self.on_fail = on_fail if on_fail in ("next", "stop") else "next"   # 切り抜きの1本が失敗したとき: next = 残りを続ける / stop = そこで止める
        self.nothing = False       # どの段もやることが無かった(「完了」と言わない。段4 S-4)
        self.docs = []             # この実行で文字起こし・パックした文書の id(終わったら「校正を始める」で開く。段4)
        self.streamer_from = None  # 配信者を自動で決めたときの出どころ(doc / video / channel = 覚えた名前・auto = チャンネル名から。段5)
        self.streamer = streamer   # 字幕の文字の色にする配信者(照らし合わせ済みの名前。手で入れたときだけ。git の履歴(679ff01 以前)の docs/archive/followup-2026-09-27.md の 4)
        self.marks = marks         # このマークだけ(スタジオのマークの行の「この後を」。None = 配信の全部。git の履歴(679ff01 以前)の docs/archive/followup-2026-09-27.md の 3)
        self.fresh = fresh         # ① 探す から: {"title", "channel"}(まだスタジオに無いかもしれない配信。解析のキューに入れるときに渡す)
        self.state = "queued"
        self.message = "順番待ち"
        self.error = ""
        self.created = time.time()
        self.finished = None
        self.cancel = False
        self.preempted = False     # あとから解析を、新しい実行を先にするために止めた(人の中止・失敗と分ける = 試した回数を増やさない)
        self.logged = False        # 記録のファイルに書いた(1つの実行は1回だけ書く。B-6)
        self.resumed = False       # 入口を起動し直して戻した実行(M5。始める前にツールの準備を待つ)
        self.owned = None          # 今ツールで動かしている仕事 (ツールの ID, [ジョブ・キューの id])(「起動し直す」の確かめ = restart_info。残さない)
        keys = list(MODE_STEPS[mode])
        if mode in REQUEST_URL_MODES and self.ranges and len(self.ranges) >= (top or 0):
            keys.remove("analyze")   # 区間が切り抜く数に足りている: 解析なしで、その区間だけを取りに行く
        if speakers and "transcribe" in keys:
            keys.insert(keys.index("transcribe") + 1, "diarize")
        self.steps = [{"key": k, "label": STEP_LABELS[k], "state": "wait", "detail": ""} for k in keys]

    def saved(self):
        """待ちの記録(autorun-active.json)に残す形(M5)。restore で同じ実行に戻せるだけの値"""
        return {"id": self.id, "videoId": self.video_id, "title": self.title, "mode": self.mode, "top": self.top, "docId": self.doc_id,
                "overwrite": self.overwrite, "streamer": self.streamer, "streamerFrom": self.streamer_from, "marks": list(self.marks) if self.marks else None,
                "fresh": self.fresh, "onFail": self.on_fail, "sourcePath": self.source_path, "requestId": self.request_id, "deliverDir": self.deliver_dir,
                "speakers": self.speakers, "videoTracks": self.video_tracks, "ranges": [list(r) for r in self.ranges], "cut": self.cut, "weights": self.weights,
                "duration": self.duration, "engine": self.engine, "model": self.model, "friendLength": self.friend_length,
                "docs": list(self.docs), "newDocs": list(self.new_docs), "packs": list(self.packs), "delivered": list(self.delivered),
                "created": self.created, "state": self.state, "message": self.message,
                "steps": [{"key": s["key"], "state": s["state"], "detail": s["detail"]} for s in self.steps]}

    @classmethod
    def restore(cls, d):
        """saved() の形 -> 「待ち」の Run(同じ id。済んだ段はそのまま・途中の段は待ちに)。形が違えば None(手で直した・壊れた記録は読み飛ばす)"""
        if not isinstance(d, dict) or not RUN_ID_RE.match(str(d.get("id") or "")) or d.get("mode") not in MODE_STEPS or d.get("mode") == POST_MODE:
            return None

        def s(k, n=1000):
            v = d.get(k)
            return v if isinstance(v, str) and 0 < len(v) <= n else None

        def strs(k, n=200):
            v = d.get(k)
            return [x for x in v if isinstance(x, str) and 0 < len(x) <= 1000][:n] if isinstance(v, list) else []
        top = d.get("top")
        vt = d.get("videoTracks")
        try:
            run = cls(s("videoId", 64), str(d.get("title") or "")[:120], d["mode"], top if isinstance(top, int) and not isinstance(top, bool) else None,
                      doc_id=s("docId", 40), overwrite=d.get("overwrite") is True, streamer=s("streamer", 120) if d.get("streamer") != "" else "",
                      marks=tuple(strs("marks", MAX_MARKS)) or None, fresh=d.get("fresh") if isinstance(d.get("fresh"), dict) else None,
                      on_fail=d.get("onFail"), source_path=s("sourcePath"), request_id=s("requestId", 120), deliver_dir=s("deliverDir"),
                      speakers=d.get("speakers") if isinstance(d.get("speakers"), dict) else None,
                      video_tracks=vt if isinstance(vt, int) and not isinstance(vt, bool) else None, ranges=clean_ranges(d.get("ranges")),
                      cut=d.get("cut"), weights=clean_weights(d.get("weights")), duration=d.get("duration") if _num(d.get("duration")) else None,
                      engine=d.get("engine"), model=d.get("model"))
        except (TypeError, ValueError, KeyError):
            return None
        run.id = d["id"]
        if _num(d.get("created")) or (isinstance(d.get("created"), (int, float)) and not isinstance(d.get("created"), bool)):
            run.created = float(d["created"])
        run.streamer_from = s("streamerFrom", 20)
        run.friend_length = d.get("friendLength") if isinstance(d.get("friendLength"), dict) else None
        run.docs, run.new_docs = strs("docs"), strs("newDocs")
        run.packs, run.delivered = strs("packs"), strs("delivered")
        old = {x.get("key"): x for x in d.get("steps") or [] if isinstance(x, dict)}
        for st in run.steps:
            o = old.get(st["key"]) or {}
            if o.get("state") in DONE_STEPS:   # 済んだ段はそのまま(続きから)。途中だった段(run)・待ちは頭から
                st["state"], st["detail"] = o["state"], str(o.get("detail") or "")[:500]
        run.resumed = True
        run.message = "ホームを起動し直したので、続きから進めます"
        return run

    def key(self):
        """配信・文書ごとの前回の結果を引くキー"""
        if self.source_path:
            return ("file", self.source_path)
        return ("doc", self.doc_id) if self.doc_id else ("video", self.video_id)

    def step(self, key):
        return next(s for s in self.steps if s["key"] == key)

    def public(self):
        return {"id": self.id, "kind": "file" if self.source_path else "doc" if self.doc_id else "video", "docId": self.doc_id, "overwrite": self.overwrite,
                "sourcePath": self.source_path, "requestId": self.request_id, "ranges": [list(r) for r in self.ranges] or None, "cut": self.cut,
                "engine": self.engine, "model": self.model,
                "friendLength": dict(self.friend_length) if self.friend_length else None,
                "videoId": self.video_id, "title": self.title, "mode": self.mode,
                "modeLabel": (MODES.get(self.mode) or REQUEST_MODES.get(self.mode) or OTHER_MODES.get(self.mode, DOC_LABEL)) +("(%d本)" % len(self.marks) if self.marks and self.mode not in REQUEST_URL_MODES else ""), "top": self.top,
                "streamer": self.streamer, "streamerFrom": self.streamer_from, "marks": list(self.marks) if self.marks else None, "fromSearch": bool(self.fresh),
                "state": self.state, "stateLabel": RUN_STATE_LABELS["nothing" if self.nothing and self.state == "done" else self.state],
                "nothing": self.nothing, "onFail": self.on_fail, "docs": list(self.docs[:20]),
                "message": self.message, "error": self.error, "created": int(self.created * 1000),
                "finished": int(self.finished * 1000) if self.finished else None,
                "steps": [dict(s, stateLabel=STEP_STATE_LABELS.get(s["state"], s["state"])) for s in self.steps]}


def _rec_key(rec):
    if rec.get("kind") == "file":
        return ("file", rec.get("sourcePath"))
    return ("doc", rec.get("docId")) if rec.get("kind") == "doc" else ("video", rec.get("videoId"))


def _parse_rec(raw):
    """記録の1行 -> 辞書(壊れた行・形の違う行は None。途中で切れた行・手で直した行を飛ばす)"""
    raw = raw.strip()
    if not raw:
        return None
    try:
        rec = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return None
    if not isinstance(rec, dict) or rec.get("v") != LOG_VERSION or not isinstance(rec.get("id"), str):
        return None
    if rec.get("state") not in ("done", "error", "cancelled") or not isinstance(rec.get("steps"), list):
        return None
    kind = rec.get("kind")
    if not ((kind == "doc" and isinstance(rec.get("docId"), str)) or (kind == "video" and isinstance(rec.get("videoId"), str))
            or (kind == "file" and isinstance(rec.get("sourcePath"), str))):
        return None
    return rec


def read_runs_log(path, max_bytes=None):
    """記録(.1 → 今のファイル = 書いた順)の中身のリスト。max_bytes = 末尾からこの大きさだけ読む(途中から読んだ最初の行は捨てる)"""
    chunks, left = [], max_bytes
    for p in (path, path + ".1"):
        if left is not None and left <= 0:
            break
        try:
            with open(p, "rb") as f:
                f.seek(0, os.SEEK_END)
                size = f.tell()
                start = 0 if left is None else max(0, size - left)
                f.seek(start)
                data = f.read()
        except OSError:
            continue
        if start > 0:
            nl = data.find(b"\n")
            data = data[nl + 1:] if nl >= 0 else b""
        if left is not None:
            left -= size - start
        chunks.insert(0, data)
    out = []
    for data in chunks:
        for raw in data.split(b"\n"):
            rec = _parse_rec(raw)
            if rec:
                out.append(rec)
    return out


class AutoRunner:
    def __init__(self, client, repo_root, env=None, poll=1.0, sleep=None, find_pack=None, prefs=None, log_dir=None, log_max=LOG_MAX_BYTES,
                 defer_idle=DEFER_IDLE_SEC, defer_retry=DEFER_RETRY_SEC, clock=None, log=None):
        """log_dir: 終わった実行の記録を書くフォルダ(入口は作業データの logs。None = 記録しない = メモリだけ)。
        あとから解析の一覧・待ちと実行中の記録(M5)も log_dir に置く(None = 残せないので、あとから解析はしない・起動し直しで戻さない)。
        defer_idle・defer_retry・clock はテスト用"""
        self.client, self.root, self.env, self.poll = client, repo_root, env, poll
        self.log_path = os.path.join(log_dir, RUNS_LOG) if log_dir else None
        self.active_path = os.path.join(log_dir, ACTIVE_FILE) if log_dir else None   # 待ち・実行中の記録(M5)
        self.active_error = ""     # 最後に待ちの記録を書けなかった理由(書けたら空に戻す)
        self._active_lock = threading.Lock()   # 待ちの記録のファイル(これを持ったまま self.cv を取る。逆の順では取らない)
        self.defer_path = os.path.join(log_dir, DEFER_FILE) if log_dir else None
        self.defer_idle, self.defer_retry = defer_idle, defer_retry
        self.clock = clock or time.time
        self.log = log or (lambda msg: None)   # 入口のログ(launcher.log)に1行
        self.defer_error = ""      # 最後に一覧を書けなかった理由(書けたら空に戻す)
        self._defer_lock = threading.Lock()   # 一覧(self.cv の中から取ってよい。逆に、これを持ったまま self.cv を取らない)
        self._defer = self._defer_read()      # {"items": [...], "dropped": [...]}
        self._defer_running = None            # いま解析している配信の ID(一覧には残したまま。入口が強制終了されても失わない)
        self._idle_since = self.clock()       # 待ち・実行中が無くなった時刻(起動したときも、少し待ってから始める)
        self._defer_hold_until = 0            # この時刻までは始めない(stop_deferred = 起動し直す前)
        self.log_max = log_max
        self.log_error = ""        # 最後に記録を書けなかった理由(書けたら空に戻す)
        self._log_lock = threading.Lock()   # 記録のファイルと past(self.cv とは別。self.cv を持ったまま _log を呼ばない)
        self._past = collections.OrderedDict()   # (種類, id) -> 最後の記録(書いた順)
        if self.log_path:
            for rec in read_runs_log(self.log_path, LOG_READ_BYTES):
                self._remember(rec)
        self.prefs = prefs   # ホームの設定(src/home/prefs.py)。カットの無い文書のカットの方法 autorun.cut
        self.sleep = sleep or time.sleep
        if find_pack is None:
            import cases   # src/home/cases.py(パックの有無の見方を案件の画面とそろえる)
            find_pack = cases.find_pack
        self.find_pack = find_pack
        self.lock = threading.Lock()
        self.cv = threading.Condition(self.lock)
        self.runs = []
        self.thread = None
        self.closed = False
        self._defer_import()   # この機能が入る前の依頼(1回だけ)
        restored = self._restore_active()   # 前の起動で待ち・実行中だった実行(M5)
        if restored:
            with self.cv:
                self.runs.extend(restored)
                self._wake()
        if self.active_path and os.path.isfile(self.active_path):
            self._save_active()   # 戻さなかった(古い・壊れた)分を記録から外す
        if self._defer["items"] and self._defer_on():   # 前の起動で残った一覧: 手が空いたら続ける
            with self.cv:
                self._wake()

    # ------------------------------------------------------------ 起動し直しで戻す(M5)
    def _save_active(self):
        """待ち・実行中の実行を autorun-active.json に残す(self.cv の外で呼ぶ)。入口の終了のあとは書かない
        (止めた実行を「次の起動で続ける」形のまま残すため)。あとから解析・人が中止した実行は入れない。書けなくても実行は止めない"""
        if not self.active_path:
            return
        with self._active_lock:
            with self.cv:
                if self.closed:
                    return
                items = [r.saved() for r in self.runs if r.state in ("queued", "running") and r.mode != POST_MODE and not r.cancel]
            try:
                fsio.atomic_write(self.active_path, json.dumps({"v": ACTIVE_VERSION, "runs": items}, ensure_ascii=False).encode("utf-8"))
                self.active_error = ""
            except (OSError, TypeError, ValueError) as e:
                self.active_error = "%s %s" % (e.__class__.__name__, getattr(e, "strerror", "") or "")

    def _restore_active(self):
        """前の起動の待ちの記録 -> 戻す Run のリスト(先に入れた順)。古すぎるものは記録に「中止」と書いて戻さない"""
        if not self.active_path:
            return []
        try:
            d = fsio.read_json_file(self.active_path, ACTIVE_READ_MAX)
        except FileNotFoundError:
            return []
        except (OSError, ValueError) as e:
            self.log("まとめて実行: 前の起動の待ちの記録を読めませんでした(%s)。戻さずに続けます" % e.__class__.__name__)
            return []
        items = d.get("runs") if isinstance(d, dict) and d.get("v") == ACTIVE_VERSION else None
        out, seen = [], set()
        for x in items if isinstance(items, list) else []:
            run = Run.restore(x)
            if run is None or run.id in seen:
                continue
            seen.add(run.id)
            if time.time() - run.created > RESTORE_MAX_AGE:
                run.state, run.message, run.finished = "cancelled", "ホームを起動し直したとき、%d 日より前に入れた実行だったので続けませんでした" % (RESTORE_MAX_AGE // 86400), time.time()
                self._log(run)
                continue
            out.append(run)
        if out:
            self.log("まとめて実行: ホームを起動し直したので、待ち・実行中だった %d 件を続けます(%s)" % (len(out), "・".join(r.title or r.id for r in out[:5])))
        return out

    def _await_tools(self, run):
        """戻した実行(M5): 残りの段で使うツールが動くまで待つ(RESUME_WAIT 秒まで。過ぎたらそのまま進めて、動いていなければ段の失敗になる)"""
        run.resumed = False
        ep = getattr(self.client, "endpoint", None)
        if ep is None:
            return
        need = set() if (run.source_path or run.doc_id) else {"studio"}
        for s in run.steps:
            if s["state"] not in DONE_STEPS:
                need.update(STEP_TOOLS.get(s["key"], ()))
        end = time.time() + RESUME_WAIT
        while True:
            try:
                missing = [t for t in sorted(need) if not ep(t)]
            except Exception:
                missing = []
            if not missing or time.time() >= end:
                return
            run.message = "ホームを起動し直したので、ツールの準備を待っています(%s)" % "・".join(missing)
            self._wait(run, 1.0)

    # ------------------------------------------------------------ 受付
    def _streamer(self, name):
        """まとめて実行の画面で入れた配信者の名前 -> 照らし合わせた名前。None(指定なし)= 自動(パックのときに覚えた名前・チャンネル名から。段5)・
        ""(空で送った)= 色なし。見つからなければ始める前に断る(ValueError)"""
        if name is None:
            return None
        if isinstance(name, str) and not name.strip():
            return ""
        who, _hex = colors.resolve(name if isinstance(name, str) else "", env=self.env)
        return who

    def _auto_streamer(self, run, doc=None, v=None):
        """指定の無い実行の配信者を決める(1回だけ。段5): 覚えた名前(文書 → 配信 → チャンネル)→ チャンネル名から。決めた名前は進み具合に出す"""
        if run.streamer is not None:
            return
        import prefs as prefs_mod
        clip = (doc or {}).get("clip") or {}
        vid = run.video_id or ((clip.get("source") or {}).get("videoId") if isinstance(clip.get("source"), dict) else None)
        ch = (v or {}).get("channel") or (run.fresh or {}).get("channel")
        if vid and not ch:
            import cases
            ch = (cases.read_studio(cases.locations(self.root, self.env)["studio"]).get(vid) or {}).get("channel")
        r = prefs_mod.guess_streamer(self.prefs, (doc or {}).get("id") or run.doc_id, vid, ch or None,
                                     from_channel=lambda c: (colors.from_channel(c, env=self.env) or {}).get("name"))
        run.streamer = r["name"] or ""
        run.streamer_from = r["source"] if r["name"] else None

    @staticmethod
    def _marks_arg(marks):
        """スタジオのマークの行から: このマークだけ進める(-> 重ならない id の組 / None = 配信の全部)"""
        if marks in (None, []):
            return None
        if not isinstance(marks, list) or len(marks) > MAX_MARKS or not all(
                isinstance(m, str) and 1 <= len(m) <= 40 and all(c.isascii() and (c.isalnum() or c in "-_") for c in m) for m in marks):
            raise ValueError("マークの指定が正しくありません")
        return tuple(dict.fromkeys(marks))

    def _pref(self, key, default=None):
        """ホームの設定 autorun の値(src/home/prefs.py。読めなければ default)"""
        try:
            v = (self.prefs.get(["autorun"])["autorun"] or {}).get(key) if self.prefs else None
        except (OSError, ValueError, KeyError):
            v = None
        return default if v is None else v

    def _push(self, run):
        """順番待ちに入れる(呼ぶのは self.cv を持っている間)。-> run.public()"""
        self.runs.append(run)
        self._trim()
        self._wake()
        return run.public()

    def _enqueue(self, items, make):
        """items を 1 つずつ make(item, 順番待ち・実行中の一覧) -> Run(入れる)か飛ばした理由 {"id", "title", "reason"}。
        -> {"runs": [作った実行], "skipped": [飛ばしたもの]}"""
        made, skipped = [], []
        with self.cv:
            active = self._active_runs()
            for it in items:
                r = make(it, active)
                if isinstance(r, Run):
                    active.append(r)
                    made.append(self._push(r))
                else:
                    skipped.append(r)
        if made:
            self._save_active()
        return {"runs": made, "skipped": skipped}

    def start(self, video_id, mode, top=None, streamer=None, marks=None, overwrite=False):
        if not isinstance(video_id, str) or not (1 <= len(video_id) <= 64) or not all(c.isalnum() or c in "-_" for c in video_id):
            raise ValueError("配信の指定が正しくありません")
        if mode not in MODES:
            raise ValueError("実行の形が正しくありません")
        top = _top_arg(top)
        who = self._streamer(streamer)
        mk = self._marks_arg(marks)
        if mk and mode == "full":
            raise ValueError("マークを選んだまとめて実行は「採用後を全部」「文字起こしまで」だけです")
        with self.cv:
            why = _busy_reason(self._active_runs(), lambda r: r.video_id == video_id, "この配信は")
            if why:
                raise ValueError(why)
            out = self._push(Run(video_id, "", mode, top, streamer=who, marks=mk, overwrite=overwrite, on_fail=self._pref("onFail", "next")))
        self._save_active()
        return out

    def start_new(self, items, top=None, streamer=None):
        """スタジオの ① 探す で選んだ配信を「解析から全部」で(git の履歴(679ff01 以前)の docs/archive/followup-2026-09-27.md の 5)。まだスタジオに無い配信でもよい。
        items = [{"id": YouTube の配信 ID, "title", "channel"}]。配信ごとに1つの実行。すでに実行中・順番待ちの配信は飛ばす。
        -> {"runs": [作った実行], "skipped": [{"id", "title", "reason"}]}"""
        if not isinstance(items, list) or not items or len(items) > MAX_NEW:
            raise ValueError("配信は 1〜%d 本で選んでください" % MAX_NEW)
        top = _top_arg(top)
        who = self._streamer(streamer)

        def make(it, active):
            it = it if isinstance(it, dict) else {}
            vid, title = it.get("id"), str(it.get("title") or "").strip()[:120]
            channel = str(it.get("channel") or "").strip()[:100]
            if not _yt_id_ok(vid):
                return {"id": str(vid or "")[:40], "title": title, "reason": "配信の指定が正しくありません"}
            why = _busy_reason(active, lambda r: r.video_id == vid)   # 同じ要求の中の重なりも(作った実行は active に入る)
            if why:
                return {"id": vid, "title": title, "reason": why}
            return Run(vid, title or vid, "full", top, streamer=who, fresh={"title": title, "channel": channel}, on_fail=self._pref("onFail", "next"))
        return self._enqueue(items, make)

    def start_docs(self, ids, overwrite=False, streamer=None):
        """「編集」の履歴で選んだ文書をまとめて(⑦(b))。文書ごとに1つの実行(順番待ち・中止・状態は配信単位の実行と同じ)。
        同じ文書がもう実行中・順番待ちなら断る(二重の登録)。-> {"runs": [作った実行], "skipped": [{"id", "title", "reason"}]}"""
        if not isinstance(ids, list) or not ids or len(ids) > MAX_WAITING:
            raise ValueError("文書は 1〜%d 本で選んでください" % MAX_WAITING)
        who = self._streamer(streamer)
        docs = {d["id"]: d for d in txindex.load(txindex.folder(self.root, self.env))}

        def make(tid, active):
            d = docs.get(tid) if _doc_id_ok(tid) else None
            if not d:
                return {"id": str(tid)[:40], "title": "", "reason": "文書が見つかりません"}
            why = _busy_reason(active, lambda r: r.doc_id == tid)
            if why:
                return {"id": tid, "title": d["title"], "reason": why}
            return Run(None, d["title"] or tid, DOC_MODE, None, doc_id=tid, overwrite=overwrite, streamer=who, on_fail=self._pref("onFail", "next"))
        return self._enqueue(dict.fromkeys(i for i in ids if isinstance(i, str)), make)

    def start_request(self, items, request_id=None, flow="check", deliver_dir=None, speakers=None, video_tracks=None, cut=None, weights=None, streamer=None):
        """友人からの依頼(配信の URL。src/home/intake.py)。items = [{"id": 配信 ID, "top": 1〜30, "title", "channel", "ranges"?, "duration"?}]。
        配信ごとに1つの実行(mode request)。ranges = 時刻で指定した区間 [(開始, 終了)](③ では使わない)。top に足りない分は自動で埋める。
        cut = カットの方法(① のパック)・weights = 解析の重み。すでに実行中・順番待ちの配信は飛ばす。-> {"runs", "skipped"}(start_new と同じ形)。
        streamer = 照らし合わせ済みの配信者の名前か None(友人の 1 人目の名前。あれば字幕の色に使い、None・空ならチャンネル名などから自動 = _auto_streamer)"""
        if not isinstance(items, list) or not items or len(items) > MAX_NEW:
            raise ValueError("配信は 1〜%d 本で指定してください" % MAX_NEW)
        mode = FLOW_MODES["url"].get(flow, "request")
        weights = clean_weights(weights)

        def make(it, active):
            it = it if isinstance(it, dict) else {}
            vid, top = it.get("id"), it.get("top")
            title, channel = str(it.get("title") or "").strip()[:120], str(it.get("channel") or "").strip()[:100]
            try:
                ranges = clean_ranges(it.get("ranges")) if mode in REQUEST_URL_MODES else []
            except ValueError as e:
                return {"id": str(vid or "")[:40], "title": title, "reason": str(e)}
            if not _yt_id_ok(vid) or not isinstance(top, int) or isinstance(top, bool) or not 1 <= top <= 30:
                return {"id": str(vid or "")[:40], "title": title, "reason": "配信の指定が正しくありません"}
            why = _busy_reason(active, lambda r: r.video_id == vid)
            if why:
                return {"id": vid, "title": title, "reason": why}
            # ① の送り直しは、前のパックがあっても今回の設定(カット・映像トラック)で作り直して届ける(overwrite)
            return Run(vid, title or vid, mode, top, fresh={"title": title, "channel": channel},
                       on_fail=self._pref("onFail", "next"), request_id=request_id, deliver_dir=deliver_dir, speakers=speakers,
                       video_tracks=video_tracks, ranges=ranges, cut=cut, weights=weights, overwrite=mode == "request_auto", streamer=streamer or None,
                       duration=it.get("duration") if _num(it.get("duration")) else None)
        return self._enqueue(items, make)

    def start_file(self, path, title="", streamer=None, request_id=None, flow="check", deliver_dir=None, speakers=None, video_tracks=None, cut=None,
                   engine=None, model=None):
        """友人が切り抜いた動画の依頼(src/home/intake.py が作業データへコピーしたもの)を文字起こしだけ(mode file)。
        streamer = 照らし合わせ済みの名前か None。文字起こしができたら、その文書の配信者として覚える(あとでパックを作るときの字幕の色)。
        engine・model = 文字起こしのエンジンとモデル(None = 編集の設定のまま。リアルタイム切り抜きの書き出しが live.auto から渡す。M2)"""
        if not isinstance(path, str) or not os.path.isabs(path) or not os.path.isfile(path):
            raise ValueError("動画が見つかりません")
        with self.cv:
            why = _busy_reason(self._active_runs(), lambda r: r.source_path == path, "この動画は")
            if why:
                raise ValueError(why)
            out = self._push(Run(None, str(title or os.path.basename(path))[:120], FLOW_MODES["file"].get(flow, "file"), None, streamer=streamer or None,
                                 on_fail=self._pref("onFail", "next"), source_path=path, request_id=request_id, deliver_dir=deliver_dir, speakers=speakers,
                                 video_tracks=video_tracks, cut=cut, engine=engine, model=model))
        self._save_active()
        return out

    # ------------------------------------------------------------ 見積もり(気が利く画面へ 段4)
    def estimate(self, video_id=None, mode=None, marks=None, top=None, doc_ids=None, overwrite=False):
        """実行と同じ規則で、段ごとの本数と飛ばす理由を返す(何も書き込まない)。実行は実行したときの状態で決めるので、ずれることがある。
        -> {"steps": [{"key", "label", "count" (None = 前の段の結果しだい), "note"}], "total": 分かっている本数の合計, "nothing": bool, "reason"}"""
        docs = txindex.load(txindex.folder(self.root, self.env))
        if doc_ids is not None:   # 文書単位(文字起こし → パック)
            if not isinstance(doc_ids, list) or not doc_ids or len(doc_ids) > MAX_WAITING:
                raise ValueError("文書は 1〜%d 本で選んでください" % MAX_WAITING)
            by = {d["id"]: d for d in docs}
            tx, pk, notes = 0, 0, []
            for tid in dict.fromkeys(i for i in doc_ids if isinstance(i, str)):
                d = by.get(tid) if _doc_id_ok(tid) else None
                if not d:
                    notes.append("見つからない文書があります")
                    continue
                if not d["count"]:
                    tx += 1
                    pk += 1
                elif overwrite or not self.find_pack(d.get("sourcePath") or ""):
                    pk += 1
            steps = [{"key": "transcribe", "label": STEP_LABELS["transcribe"], "count": tx, "note": "" if tx else "文字起こし済み"},
                     {"key": "pack", "label": STEP_LABELS["pack"], "count": pk, "note": "" if pk else "パック済み(「パックがあれば作り直す(上書き)」を選ぶと作り直します)"}]
            return self._estimate_out(steps, notes)
        if mode not in MODES:
            raise ValueError("実行の形が正しくありません")
        st, obj = self.client.call("studio", "GET", "/api/video?id=" + urllib.parse.quote(str(video_id or "")))
        v = (obj.get("video") or {}) if st == 200 and isinstance(obj, dict) else {}
        run = Run(video_id, "", mode, top or DEFAULT_TOP, marks=self._marks_arg(marks))
        mine = self._mine(run, v)
        adopted = [m for m in mine if m.get("status") == "adopted"]
        clips = self._clips(v, run)
        no_tx = [m for m in clips if not txindex.pick(docs, video_id, m.get("id"), m["path"])[0]]
        packable = [m for m in clips if m not in no_tx and (overwrite or not self.find_pack(m["path"]))]
        steps = []
        pending = False   # 前の段の結果しだい(解析・採用のあとで本数が決まる)
        for key in MODE_STEPS[mode]:
            label, count, note = STEP_LABELS[key], 0, ""
            if key == "analyze":
                count, note = (0, "解析済み") if v.get("analysis") else (1, "")
                pending = pending or count > 0
            elif key == "adopt":
                if any(m.get("status") in ("adopted", "exported") for m in mine):
                    note = "採用・書き出し済みのマークを使います"
                elif pending:
                    count, note = None, "解析のあとで、点数の高い %d 件" % (top or DEFAULT_TOP)
                else:
                    cands = [m for m in mine if not m.get("status")]
                    count = min(len(cands), top or DEFAULT_TOP)
                    note = "" if count else "採用できる候補がありません"
                pending = pending or count is None or bool(count)
            elif key == "export":
                count = None if pending and not adopted else len(adopted)
                note = "" if count else ("採用のあとで決まります" if count is None else "採用したマークがありません" if not clips else "書き出し済み %d 本" % len(clips))
                pending = pending or bool(count)
            elif key == "transcribe":
                count = None if pending else len(no_tx)
                note = "書き出しのあとで決まります" if count is None else ("" if count else ("%d 本とも文字起こし済み" % len(clips) if clips else "書き出した切り抜きがありません"))
                pending = pending or bool(count)
            elif key == "pack":
                count = None if pending else len(packable)
                note = "文字起こしのあとで決まります" if count is None else ("" if count else ("パック済み(「パックがあれば作り直す(上書き)」を選ぶと作り直します)" if clips else "文字起こしのある切り抜きがありません"))
            steps.append({"key": key, "label": label, "count": count, "note": note})
        return self._estimate_out(steps, [] if st == 200 else ["配信がスタジオに見つかりません"])

    @staticmethod
    def _estimate_out(steps, notes):
        known = [s["count"] for s in steps if s["count"] is not None]
        nothing = all(s["count"] == 0 for s in steps)
        reason = "・".join([s["note"] for s in steps if s["note"]] + notes) if nothing else ""
        return {"steps": steps, "total": sum(known), "nothing": nothing, "reason": reason, "notes": notes}

    def _active_runs(self):
        """順番待ち・実行中の実行(あとから解析は数えない = 新しい実行を断る理由にしない。入ると止める。呼ぶのは self.cv を持っている間)"""
        return [r for r in self.runs if r.state in ("queued", "running") and r.mode != POST_MODE]

    def _wake(self):
        """順番待ちを動かす(呼ぶのは self.cv を持っている間)。あとから解析の最中に新しい実行が入ったら、それを止めて新しい実行を先にする
        (止めた配信は一覧に残っているので、待ちが無くなったらまた始める。試した回数は増やさない)"""
        if any(r.state == "queued" for r in self.runs):
            for r in self.runs:
                if r.mode == POST_MODE and r.state == "running" and not r.cancel:
                    r.cancel, r.preempted = True, "新しい実行を先にするため"
                    r.message = "新しい実行を先にするため止めています(あとで続けます)"
        self.cv.notify_all()
        if self.thread is None or not self.thread.is_alive():
            self.thread = threading.Thread(target=self._loop, name="autorun", daemon=True)
            self.thread.start()

    def stop_deferred(self, reason="起動し直すため", wait=CANCEL_WAIT + 5, hold=DEFER_IDLE_SEC * 2):
        """動いているあとから解析を止めて(スタジオの解析も取り消す)、止まるまで待つ(「起動し直す」の前。launch.py の restart_self)。
        一覧には残り、試した回数は増やさない。hold 秒は次のあとから解析を始めない。-> 止まったか(動いていなければ True)"""
        with self.cv:
            self._defer_hold_until = self.clock() + hold
            for r in self.runs:
                if r.mode == POST_MODE and r.state == "running" and not r.cancel:
                    r.cancel, r.preempted = True, reason
                    r.message = "%s止めています(あとで続けます)" % reason
            return self.cv.wait_for(lambda: not any(r.mode == POST_MODE and r.state == "running" for r in self.runs), wait)

    def restart_info(self, timeout=5):
        """画面の「起動し直す」(launch.py の restart_self。入口 0.41.0)が断るかを決める材料。待ち・実行中は起動し直したあとに戻る(M5)ので、それだけでは断らない。
        -> {"runs": 待ち・実行中の数(あとから解析は数えない), "redo": restart.can_restart の redo か None}。
        redo は、実行中の段が REDO_STEPS で、その段がツールで動かしている仕事を、ツールの一覧(timeout 秒で読む)で確かめられたときだけ"""
        with self.cv:
            active = self._active_runs()
            run = next((r for r in active if r.state == "running"), None)
            owned = run.owned if run is not None else None
            step = next((s["key"] for s in run.steps if s["state"] == "run"), None) if run is not None else None
        out = {"runs": len(active), "redo": None}
        if not owned or step not in REDO_STEPS:
            return out
        client = ToolClient(self.client.endpoint, self.client.token, timeout) if isinstance(self.client, ToolClient) else self.client
        try:
            out["redo"] = self._redo_work(client, owned[0], list(owned[1]))
        except (StepError, http.client.HTTPException):   # 読めなければ今までどおり(ツールの仕事を数えて断る)
            pass
        return out

    @staticmethod
    def _redo_work(client, tool, ids):
        """ツールの仕事の一覧を読み、この実行の分(ids)の名前(重い処理の枠の名前の元)と、ほかの仕事の名前に分ける -> restart_info の redo"""
        if tool == "cut2resolve":   # パックは 1 つずつ(別の処理の最中は断られる)。この実行のジョブが動いていれば、枠はそのジョブのもの
            j = client.ok(tool, "GET", "/api/job?id=" + urllib.parse.quote(str(ids[0] if ids else "")))
            return {"tool": tool, "labels": None, "others": []} if j.get("state") == "running" else None
        if tool == "transcribe":   # 「編集」のジョブ(枠の名前は題名の頭。src/editor/ed_jobs.py の work_one)
            items = [j for j in client.ok(tool, "GET", "/api/jobs").get("jobs") or [] if isinstance(j, dict) and j.get("state") in TX_ACTIVE]
            key, name = "id", lambda j: str(j.get("title") or "")
        elif tool == "studio":   # スタジオの解析のキュー(枠の名前は題名か配信の ID。src/studio/batch.py)
            items = [i for i in client.ok(tool, "GET", "/api/queue").get("items") or [] if isinstance(i, dict) and i.get("status") in QUEUE_ACTIVE]
            key, name = "qid", lambda i: str(i.get("title") or i.get("videoId") or "")
        else:
            return None
        return {"tool": tool, "labels": [name(i) for i in items if i.get(key) in ids], "others": [name(i) for i in items if i.get(key) not in ids]}

    def cancel(self, run_id):
        ended = False
        with self.cv:
            run = next((r for r in self.runs if r.id == run_id), None)
            if run is None:
                raise ValueError("その実行はありません")
            if run.state == "queued":
                run.state, run.message, run.finished = "cancelled", "中止しました", time.time()
                ended = True
            elif run.state == "running":
                run.cancel = True
                run.message = "中止しています…"
            out = run.public()
        if ended:   # 順番待ちの中止はここで終わる(実行中の分は _loop の終わりで書く)
            self._log(run)
        self._save_active()   # 中止した実行は起動し直しても戻さない
        return out

    def snapshot(self):
        """runs = メモリの実行(新しい順)・past = 配信・文書ごとの前回の結果のうちメモリに無いもの(記録のファイルから。新しい順・PAST_MAX 件まで)"""
        with self.cv:
            runs = [r.public() for r in reversed(self.runs)]
            keys = {r.key() for r in self.runs if r.mode != POST_MODE}   # あとから解析がメモリにあっても、案件の行の「前回」は消さない
        with self._log_lock:
            past = [{k: rec.get(k) for k in PAST_KEYS} for key, rec in reversed(self._past.items()) if key not in keys][:PAST_MAX]
        return {"runs": runs, "past": past, "modes": MODES}

    def history(self, limit=None, offset=0):
        """終わった実行の記録(今のファイルと .1。新しい順)。-> {"runs", "total", "more", "offset"}。limit・offset は範囲に丸める"""
        limit = HISTORY_DEFAULT if not isinstance(limit, int) or isinstance(limit, bool) else min(HISTORY_MAX, max(1, limit))
        offset = 0 if not isinstance(offset, int) or isinstance(offset, bool) else max(0, offset)
        if not self.log_path:
            return {"runs": [], "total": 0, "more": False, "offset": offset}
        with self._log_lock:   # 書き込み(.1 へ回す)と重ねない
            recs = read_runs_log(self.log_path)
        recs.reverse()
        return {"runs": recs[offset:offset + limit], "total": len(recs), "more": offset + limit < len(recs), "offset": offset}

    def _remember(self, rec):
        """past の元に入れる(呼ぶのは self._log_lock を持っている間か、__init__ の中)。
        あとから解析は入れない(案件の行の「前回」は、依頼・まとめて実行の結果のまま。記録のファイル・history には残る)"""
        if rec.get("mode") == POST_MODE:
            return
        k = _rec_key(rec)
        self._past.pop(k, None)
        self._past[k] = rec
        while len(self._past) > PAST_KEEP:
            self._past.popitem(last=False)

    def _log(self, run):
        """終わった実行を記録のファイルに1行で書く(B-6)。1つの実行は1回だけ(run.logged)。self.cv の外で呼ぶ。
        書けなくても実行は止めない(clientlog._write と同じ)。1行 = Run.public() + v"""
        with self._log_lock:
            if run.logged:
                return
            run.logged = True
            rec = dict(run.public(), v=LOG_VERSION)
            self._remember(rec)
            if not self.log_path:
                return
            try:
                clientlog.append_line(self.log_path, json.dumps(rec, ensure_ascii=False) + "\n", self.log_max)
                self.log_error = ""
            except (OSError, TypeError, ValueError) as e:
                self.log_error = "%s %s" % (e.__class__.__name__, getattr(e, "strerror", "") or "")

    def close(self):
        """入口の終了: 実行中の段を止める(self.closed で _check が止める。ツールの側のジョブも取り消す)。
        順番待ち・実行中の実行は、待ちの記録(autorun-active.json)に最後に書いた形のまま残り、次の起動で続く(M5)。記録(autorun-runs.jsonl)には書かない"""
        with self._active_lock:   # 書いている途中の待ちの記録を書き終えてから閉じる(このあとは書かない)
            with self.cv:
                self.closed = True
                for r in self.runs:
                    if r.state == "queued" and r.mode != POST_MODE:
                        r.message = "ホームを終了したので、次の起動で続けます"
                self.cv.notify_all()

    def _trim(self):
        done = [r for r in self.runs if r.state not in ("queued", "running")]
        for r in done[:-MAX_KEEP] if len(done) > MAX_KEEP else []:
            self.runs.remove(r)

    # ------------------------------------------------------------ あとから解析(測るため。2026-10-05)
    # 一覧のファイル(logs/autorun-deferred.json): {"v": 1, "items": [{"videoId", "title", "added", "tries", "reason", "lastTry", "requestId"}],
    #   "dropped": [{…items と同じ…, "dropped": 捨てた時刻, "reason": 捨てた理由}]}。時刻はエポックのミリ秒(実行の記録の created と同じ)
    def _defer_on(self):
        """あとから解析をするか(一覧を置く場所があり、環境変数 YTT_DEFER_ANALYZE が off でない)"""
        return bool(self.defer_path) and not self._env_off(DEFER_ENV)

    def _env_off(self, name):
        """環境変数 name が off・0・false・no か(テストが渡す env と、本物の環境変数の両方を見る)"""
        return any(str(e.get(name) or "").strip().lower() in ("off", "0", "false", "no") for e in (self.env or {}, os.environ))

    def _now_ms(self):
        return int(self.clock() * 1000)

    def _defer_clean(self, it):
        """一覧の1件を整える(手で直した・壊れたファイルでも、決まった形だけを持つ)"""
        ms = lambda x: int(x) if _ms_ok(x) else None
        tries = it.get("tries")
        return {"videoId": it["videoId"], "title": str(it.get("title") or "")[:120], "added": ms(it.get("added")) or self._now_ms(),
                "tries": tries if isinstance(tries, int) and not isinstance(tries, bool) and tries >= 0 else 0,
                "reason": str(it.get("reason") or "")[:300], "lastTry": ms(it.get("lastTry")),
                "requestId": str(it["requestId"])[:80] if isinstance(it.get("requestId"), str) and it["requestId"] else None}

    def _defer_read(self):
        out = {"items": [], "dropped": [], "imported": None}
        if not self.defer_path:
            return out
        try:
            obj = fsio.read_json_file(self.defer_path, DEFER_READ_MAX)
        except FileNotFoundError:
            return out
        except (OSError, ValueError) as e:   # 壊れた・読めない: 空から始める(次に書くときに置き換わる)
            self.defer_error = "一覧を読めませんでした: %s" % e.__class__.__name__
            return out
        if not isinstance(obj, dict) or obj.get("v") != DEFER_VERSION:
            return out
        seen = set()
        for it in obj.get("items") if isinstance(obj.get("items"), list) else []:
            if isinstance(it, dict) and _yt_id_ok(it.get("videoId")) and it["videoId"] not in seen:
                seen.add(it["videoId"])
                out["items"].append(self._defer_clean(it))
        out["dropped"] = [d for d in (obj.get("dropped") if isinstance(obj.get("dropped"), list) else []) if isinstance(d, dict)][-DEFER_DROPPED_KEEP:]
        out["imported"] = int(obj["imported"]) if _ms_ok(obj.get("imported")) else None
        return out

    def _defer_import(self):
        """この機能が入る前に区間だけで終わった依頼を、実行の記録(今のファイルと .1)から一覧に足す(1回だけ。済んだら一覧のファイルの imported に時刻)。
        対象 = 依頼(URL)・区間あり・解析の段なし・区間のマークを作ったあとに終わった(成功・一部失敗)・終わってから 30 日以内。新しい順に 20 本まで。
        スタジオで解析済み・スタジオから消えた配信は、始めるときの確かめで外れる"""
        if not self.log_path or not self._defer_on() or self._defer["imported"]:
            return
        if not os.path.exists(self.log_path) and not os.path.exists(self.log_path + ".1"):
            # 記録がまだ無い = 取り込むものも無い。印はメモリだけ(ファイルは次に一覧を書くときに一緒に書く。ここで空のファイルを作らない)
            self._defer["imported"] = self._now_ms()
            return
        now = self._now_ms()
        try:
            recs = read_runs_log(self.log_path)
        except Exception:   # 読めなくても入口は動かす(次の起動でまた試す)
            return
        picked = []
        for rec in reversed(recs):   # 新しい順
            vid, keys = rec.get("videoId"), {s.get("key"): s.get("state") for s in rec.get("steps") if isinstance(s, dict)}
            fin = rec.get("finished")
            if (rec.get("mode") not in REQUEST_URL_MODES or not rec.get("ranges") or not _yt_id_ok(vid) or "analyze" in keys
                    or rec.get("state") not in ("done", "error") or keys.get("adopt") not in ("done", "warn")
                    or not _ms_ok(fin) or now - fin > DEFER_IMPORT_DAYS * 86400 * 1000 or vid in [p["videoId"] for p in picked]):
                continue
            picked.append({"videoId": vid, "title": str(rec.get("title") or "")[:120], "added": now, "tries": 0, "reason": "",
                           "lastTry": None, "requestId": rec.get("requestId") if isinstance(rec.get("requestId"), str) else None})
            if len(picked) >= DEFER_IMPORT_MAX:
                break
        with self._defer_lock:
            for it in picked:
                if not self._defer_find(it["videoId"]):
                    self._defer["items"].append(self._defer_clean(it))
            self._defer["imported"] = now
            self._defer_write()

    def _defer_write(self):
        """一覧をファイルへ(原子的に。呼ぶのは self._defer_lock を持っている間)。書けなくても実行は止めない"""
        if not self.defer_path:
            return
        try:
            data = {"v": DEFER_VERSION, "items": self._defer["items"], "dropped": self._defer["dropped"][-DEFER_DROPPED_KEEP:],
                    "imported": self._defer.get("imported")}
            fsio.atomic_write(self.defer_path, (json.dumps(data, ensure_ascii=False, indent=1) + "\n").encode("utf-8"))
            self.defer_error = ""
        except (OSError, TypeError, ValueError) as e:
            self.defer_error = "%s %s" % (e.__class__.__name__, getattr(e, "strerror", "") or "")

    def _defer_find(self, vid):
        return next((it for it in self._defer["items"] if it["videoId"] == vid), None)

    def _defer_drop(self, it, reason):
        """一覧から外し、理由を dropped に残す(呼ぶのは self._defer_lock を持っている間)"""
        if it in self._defer["items"]:
            self._defer["items"].remove(it)
        self._defer["dropped"] = (self._defer["dropped"] + [dict(it, dropped=self._now_ms(), reason=str(reason)[:300])])[-DEFER_DROPPED_KEEP:]

    def _defer_prune(self):
        """14 日たったもの・3 回失敗したものを捨てる(呼ぶのは self._defer_lock を持っている間)。-> 変えたか"""
        now, changed = self._now_ms(), False
        for it in list(self._defer["items"]):
            if it["videoId"] == self._defer_running:
                continue
            if now - it["added"] > DEFER_KEEP_SEC * 1000:
                self._defer_drop(it, "足してから %d 日たったので捨てました" % (DEFER_KEEP_SEC // 86400) + ("(最後: %s)" % it["reason"] if it["reason"] else ""))
                changed = True
            elif it["tries"] >= DEFER_MAX_TRIES:
                self._defer_drop(it, "%d 回失敗したので捨てました(最後: %s)" % (it["tries"], it["reason"] or "理由不明"))
                changed = True
        return changed

    def deferred(self):
        """あとから解析する配信の一覧(写し。{"on", "items", "dropped", "error"})。テストと、あとで画面に出すとき用"""
        with self._defer_lock:
            return {"on": self._defer_on(), "items": [dict(x) for x in self._defer["items"]], "dropped": [dict(x) for x in self._defer["dropped"]],
                    "running": self._defer_running, "error": self.defer_error}

    def _defer_candidate(self):
        """待ちが無いときに始める、あとから解析の1件(古い順)。-> (一覧の1件の写し か None, 次に見るまでの秒)。呼ぶのは self.cv を持っている間"""
        if not self._defer_on():
            return None, 5
        now = self.clock()
        if self.defer_idle and now - self._idle_since < self.defer_idle:   # 待ちが無くなってすぐは始めない
            return None, max(0.05, min(5.0, self.defer_idle - (now - self._idle_since)))
        if now < self._defer_hold_until:
            return None, max(0.05, min(5.0, self._defer_hold_until - now))
        with self._defer_lock:
            if self._defer_prune():
                self._defer_write()
            ready = [it for it in self._defer["items"] if not it["lastTry"] or now * 1000 - it["lastTry"] >= self.defer_retry * 1000]
            best = min(ready, key=lambda it: it["added"]) if ready else None
            return (dict(best) if best else None), 5

    def _start_deferred(self, cand):
        """あとから解析を始める(実行を作って実行中にする)。スタジオでもう解析済み・スタジオに無い配信は、始めずに一覧から外す。
        始める直前に新しい実行が入っていたら始めない(新しい実行が先)。-> Run か None"""
        vid = cand["videoId"]
        try:
            st, obj = self.client.call("studio", "GET", "/api/video?id=" + urllib.parse.quote(vid))
            err = ""
        except StepError as e:
            st, obj, err = None, {}, str(e)
        v = (obj.get("video") or {}) if st == 200 else {}
        with self._defer_lock:
            it = self._defer_find(vid)
            if it is None:
                return None
            if st is None or (st != 200 and st != 404):   # スタジオが動いていない・つながらない: 回数は増やさずに、少し待ってから
                it.update(lastTry=self._now_ms(), reason=(err or obj.get("message") or "HTTP %s" % st)[:300])
                self._defer_write()
                return None
            if st == 404:
                self._defer_drop(it, "スタジオに配信がありません(消した可能性があります)")
                self._defer_write()
                return None
            if v.get("analysis"):   # 人・ほかの実行が解析した: 何もせず外す
                self._defer_drop(it, "スタジオで解析済みだったので、解析せずに外しました")
                self._defer_write()
                return None
        with self.cv:
            if self.closed or any(r.state == "queued" for r in self.runs) or not self._defer_on():
                return None
            run = Run(vid, str(v.get("title") or cand.get("title") or vid)[:120], POST_MODE, None)
            run.state = "running"
            self.runs.append(run)
            self._trim()
            self._defer_running = vid
        return run

    def _defer_after(self, run):
        """実行が終わったとき(self.cv の外): 区間だけで終わった依頼(URL)は一覧に足す。あとから解析が終わったら外す・失敗を数える"""
        if run.mode == POST_MODE:
            return self._defer_post_done(run)
        if run.mode not in REQUEST_URL_MODES or not run.ranges or not _yt_id_ok(run.video_id) or run.state == "cancelled":
            return None
        keys = {s["key"]: s["state"] for s in run.steps}
        if "analyze" in keys or keys.get("adopt") not in ("done", "warn"):   # 解析した依頼・区間のマークを作る前に止まった依頼は足さない
            return None
        if not self._defer_on():
            return None
        with self._defer_lock:
            it = self._defer_find(run.video_id)
            if it:   # 同じ配信の依頼がまた来た: 1つのまま(足した時刻・回数はそのまま)
                it.update(title=(run.title or it["title"])[:120], requestId=run.request_id or it["requestId"])
            else:
                self._defer["items"].append({"videoId": run.video_id, "title": str(run.title or "")[:120], "added": self._now_ms(), "tries": 0,
                                             "reason": "", "lastTry": None, "requestId": run.request_id})
            self._defer_write()
        return None

    def _defer_post_done(self, run):
        vid = run.video_id
        with self._defer_lock:
            self._defer_running = None
            it = self._defer_find(vid)
            if run.state == "cancelled" and (run.preempted or self.closed):   # 新しい実行を先に・起動し直す・入口の終了: 一覧に残したまま(回数は増やさない)
                run.message = "%s止めました(あとで続けます)" % run.preempted if run.preempted else "ホームを終了しました(次に起動したときに続けます)"
                return None
            if it is None:
                return None
            if run.state == "done":
                self._defer["items"].remove(it)
                if not run.nothing:
                    run.message = "解析しました(依頼の区間と比べるためだけ。友人には何も届けません)"
            else:   # 失敗・人が中止した: 回数を数えて、少し待ってから試し直す
                why = run.error or run.message or "中止しました"
                it.update(tries=it["tries"] + 1, lastTry=self._now_ms(), reason=why[:300])
                if it["tries"] >= DEFER_MAX_TRIES:
                    self._defer_drop(it, "%d 回失敗したので捨てました(最後: %s)" % (it["tries"], why))
                    run.message += "(%d 回目なので、この配信はもう解析しません)" % it["tries"]
                else:
                    run.message += "(あとでもう一度試します。%d / %d 回目)" % (it["tries"], DEFER_MAX_TRIES)
            self._defer_write()
        return None

    def _loop(self):
        while True:
            run = cand = None
            with self.cv:
                while not self.closed and not any(r.state == "queued" for r in self.runs):
                    cand, wait = self._defer_candidate()   # 待ちが無い: あとから解析する配信があれば始める
                    if cand:
                        break
                    self.cv.wait(wait)
                if self.closed:
                    return
                if not cand:
                    run = next(r for r in self.runs if r.state == "queued")
                    run.state, run.message = "running", ""
            if run is None:
                run = self._start_deferred(cand)
                if run is None:
                    continue
            self._save_active()   # 実行中になった(M5)
            try:
                self._execute(run)
                run.state = "cancelled" if run.cancel else "done"
                run.message = "中止しました" if run.cancel else (run.message or "完了")
            except Cancelled:
                run.state, run.message = "cancelled", "中止しました"
            except StepError as e:
                run.state, run.error, run.message = "error", str(e), "止まりました"
            except Exception as e:   # 想定外でも、次の配信の処理は続ける
                run.state, run.error, run.message = "error", "内部エラー: %s %s" % (e.__class__.__name__, str(e)[:200]), "止まりました"
            if self.closed and not run.cancel and run.mode != POST_MODE and run.state != "done":
                # 入口の終了で止まった(M5): 記録には「中止」と書かず、待ちの記録(最後に書いた段の形)のまま次の起動で続ける
                run.state, run.error, run.message = "queued", "", "ホームを終了したので、次の起動で続けます"
                for s in run.steps:
                    if s["state"] == "run":
                        s["state"] = "wait"
                with self.cv:
                    self.cv.notify_all()
                continue
            run.finished = time.time()
            for s in run.steps:
                if s["state"] == "run":
                    s["state"] = "error" if run.state == "error" else "skip"
            if run.deliver_dir and run.state == "error":   # ① 全自動: 友人の「受け取る」に失敗の理由を出す
                self._deliver_failure(run)
            self._defer_after(run)   # あとから解析の一覧(依頼が区間だけで終わった = 足す・あとから解析が終わった = 外す・回数を数える)
            self._log(run)   # 記録のファイルへ(self.cv の外。B-6)
            with self.cv:
                self._trim()
                if not any(r.state in ("queued", "running") for r in self.runs):
                    self._idle_since = self.clock()
                self.cv.notify_all()   # stop_deferred が止まるのを待っている
            self._save_active()   # 終わった実行を待ちの記録から外す(M5)

    # ------------------------------------------------------------ 実行
    def _check(self, run):
        if run.cancel or self.closed:
            raise Cancelled()

    def _wait(self, run, seconds=None):
        self._check(run)
        self.sleep(self.poll if seconds is None else seconds)
        self._check(run)

    def _video(self, run):
        st, obj = self.client.call("studio", "GET", "/api/video?id=" + run.video_id)
        if st == 404 and run.fresh:   # ① 探す から: 解析のキューに入れるまではスタジオに無い(受け取った題名で進める)
            return {"kind": "youtube", "title": run.title}
        if st != 200:
            raise StepError(obj.get("message") or "エラー(HTTP %d)" % st)
        v = obj.get("video") or {}
        run.title = str(v.get("title") or v.get("fileName") or run.video_id)[:120]
        return v

    def _execute(self, run):
        if run.resumed:   # 入口を起動し直して戻した実行(M5): ツールの準備を待つ
            self._await_tools(run)
        if run.source_path:   # 依頼の動画(mode file): _file_<段>
            return self._run_steps(run, lambda key, st: getattr(self, "_file_" + key)(run, st))
        if run.doc_id:   # 文書単位(⑦(b)): _doc_<段>
            return self._run_steps(run, lambda key, st: getattr(self, "_doc_" + key)(run, st))
        cur = [self._video(run)]   # 配信: _step_<段>。段が済むたびにスタジオの配信を読み直す

        def refresh():
            cur[0] = self._video(run)
        self._run_steps(run, lambda key, st: getattr(self, "_step_" + key)(run, st, cur[0]), refresh)

    def _run_steps(self, run, call, after=None):
        """段を順に進める。call(段の鍵, 段) -> "stop" ならそこで止めて残りを飛ばす。after() = 段が済むたび(記録のあと)"""
        for key in [s["key"] for s in run.steps]:
            self._check(run)
            st = run.step(key)
            if st["state"] in DONE_STEPS:   # 戻した実行(M5)の済んだ段は飛ばす(続きから)
                continue
            st["state"] = "run"
            run.message = st["label"]
            self._save_active()   # どの段の途中か(M5。起動し直したらこの段から)
            result = call(key, st)
            if st["state"] == "run":
                st["state"] = "done"
            self._save_active()   # 段が済んだ(M5)
            if after:
                after()
            if result == "stop":   # 続けても意味がない(採用するマークが無いなど)
                for s in run.steps:
                    if s["state"] == "wait":
                        s["state"], s["detail"] = "skip", s["detail"] or "前の段で止めました"
                break
        self._finish_message(run)

    def _finish_message(self, run):
        """どの段も飛ばした = やることが無かった(「完了」と言わない。段4 S-4)"""
        if all(s["state"] == "skip" for s in run.steps):
            run.nothing = True
            run.message = NOTHING_MESSAGE + (": " + run.message if run.message and run.message != "完了" else "")
        elif not run.message or run.message in [s["label"] for s in run.steps]:
            run.message = "完了"

    # 解析 -------------------------------------------------------
    def _weights_differ(self, run, v):
        """友人が指定した解析の重みが、今の解析の結果の重みと違うか(違えば解析し直す。音量・チャットの取り込み済みのデータは使い回される)"""
        if not run.weights:
            return False
        spec = (v.get("analysis") or {}).get("spec") if isinstance(v.get("analysis"), dict) else None
        spec = spec if isinstance(spec, dict) else {}
        return any(not _num(spec.get(k)) or round(float(spec[k]), 1) != run.weights[k] for k in WEIGHT_KEYS)

    def _step_analyze(self, run, st, v):
        if v.get("analysis") and not self._weights_differ(run, v):
            st["state"], st["detail"] = "skip", "解析済み(前の結果を使います)" if run.request_id else "解析済み"
            return None
        item = {"kind": v.get("kind") or "youtube", "videoId": run.video_id}
        if run.fresh and item["kind"] == "youtube":   # ① 探す から: 題名・配信者はスタジオの一覧にそのまま出る(解析の前に分かっている分)
            item.update({k: run.fresh[k] for k in ("title", "channel") if run.fresh.get(k)})
        if item["kind"] == "file":
            import cases
            path = (cases.read_studio(cases.locations(self.root, self.env)["studio"]).get(run.video_id) or {}).get("path")
            if not path:
                raise StepError("元の動画ファイルの場所が分かりません")
            item = {"kind": "file", "path": path}
        self._analyze_item(run, st, item, run.video_id)
        if run.mode == POST_MODE:
            st["detail"] += "。依頼の区間と比べるためだけの解析です(友人には何も届けません)"
        return None

    def _friend_length(self):
        """友人の区間の長さの実績(dev/eval_marks.py --json の結果のうち、いちばん新しいもの)-> 解析の設定に重ねる {"length", "preRatio"?} と出どころ。
        使わない(止めてある・ファイルが無い・古い・壊れている・見本が足りない)ときは None(ログに1行。依頼は今までどおりスタジオの設定で進む)"""
        if self._env_off(FRIEND_LENGTH_ENV):
            return None
        if self._pref("friendLength", True) is False:
            return None
        import cases
        folder = os.path.join(os.path.dirname(cases.locations(self.root, self.env)["studio"]), "evals", "marks")
        try:
            names = sorted(n for n in os.listdir(folder) if EVAL_MARKS_NAME_RE.match(n))
        except OSError:
            names = []
        if not names:
            self.log("友人の区間の長さ: 測る道具の結果がまだ無いので、スタジオの設定の長さで解析します")
            return None
        name = names[-1]
        try:
            stamp = time.mktime(time.strptime(EVAL_MARKS_NAME_RE.match(name).group(1), "%Y%m%d-%H%M%S"))
        except (ValueError, OverflowError):
            stamp = 0
        if self.clock() - stamp > FRIEND_LENGTH_MAX_AGE:
            self.log("友人の区間の長さ: 測る道具の結果(%s)が %d 日より古いので使いません" % (name, FRIEND_LENGTH_MAX_AGE // 86400))
            return None
        try:
            res = fsio.read_json_file(os.path.join(folder, name), EVAL_READ_MAX)
            cl = res["clipLength"]
            fr, pr = cl["samples"]["friend"], (cl.get("peakRatio") or {}).get("friend") or {}
            n, videos, p50 = fr["n"], fr["videos"], fr["length"]["p50"]
            if not all(isinstance(x, int) and not isinstance(x, bool) for x in (n, videos)) or not _num(p50) or p50 <= 0:
                raise ValueError("数でない")
        except (OSError, ValueError, KeyError, TypeError, AttributeError) as e:
            self.log("友人の区間の長さ: 測る道具の結果(%s)を読めないので使いません(%s)" % (name, e.__class__.__name__))
            return None
        if n < FRIEND_LENGTH_MIN_SAMPLES or videos < FRIEND_LENGTH_MIN_VIDEOS:
            self.log("友人の区間の長さ: 見本がまだ少ないので使いません(%d 個・配信 %d 本。%d 個・%d 本から)"
                     % (n, videos, FRIEND_LENGTH_MIN_SAMPLES, FRIEND_LENGTH_MIN_VIDEOS))
            return None
        lo, hi = FRIEND_LENGTH_RANGE
        out = {"length": int(min(hi, max(lo, int(float(p50) + 0.5)))), "file": name, "samples": n, "videos": videos}
        pn, pm = pr.get("n") if isinstance(pr, dict) else None, pr.get("median") if isinstance(pr, dict) else None
        if isinstance(pn, int) and not isinstance(pn, bool) and pn >= FRIEND_PRE_MIN_SAMPLES and _num(pm):
            lo, hi = FRIEND_PRE_RANGE
            out["preRatio"] = round(min(hi, max(lo, float(pm))), 2)
        return out

    def _analyze_item(self, run, st, item, video_id):
        """スタジオの解析のキューに入れて、終わるまで待つ(配信の解析と、依頼 ③ の動画の解析で共通)"""
        # 解析の設定はスタジオの画面で保存したもの(/api/settings の settings.analyze。段階7-1)。無ければスタジオの既定値
        saved = (self.client.ok("studio", "GET", "/api/settings").get("settings") or {}).get("analyze")
        saved = saved if isinstance(saved, dict) else {}
        if run.weights:   # 友人が指定した重み(ほかの解析の設定はスタジオのまま)
            saved = dict(saved, **run.weights)
        fl = self._friend_length() if run.mode in REQUEST_URL_MODES else None
        if fl:   # 友人の依頼の足りない分を自動で埋める: 自動の候補の長さを、友人が選んだ区間の長さの実績に合わせる(解析し直しの理由にはしない)
            saved = dict(saved, **{k: fl[k] for k in ("length", "preRatio") if k in fl})
            run.friend_length = fl
        res = self.client.ok("studio", "POST", "/api/queue/add", {"items": [item], "settings": saved})
        added = res.get("added") or []
        qid = added[0]["qid"] if added else None
        if not qid:
            rej = (res.get("rejected") or [{}])[0].get("reason") or ""
            if "すでにキュー" not in rej:
                raise StepError("解析を始められませんでした: %s" % (rej or "理由不明"))
        st["detail"] = "解析中(%s)" % ("依頼の重み(音声 %s・チャット %s・コメント %s)" % tuple(run.weights[k] for k in WEIGHT_KEYS) if run.weights
                                    else "スタジオで保存した解析の設定" if saved else "解析の設定は既定値。スタジオの ② で設定を変えると次から使います")
        fl_note = ("。長さ %d 秒%s(友人の区間の実績から)" % (fl["length"], "・山の前 %.2f" % fl["preRatio"] if "preRatio" in fl else "")) if fl else ""
        st["detail"] += fl_note
        run.owned = ("studio", [qid]) if qid else None   # 人が入れた解析(qid なし)を待つときは自分の仕事にしない
        try:
            while True:
                self._wait(run)
                items = self.client.ok("studio", "GET", "/api/queue").get("items") or []
                it = next((i for i in items if (i.get("qid") == qid if qid else i.get("videoId") == video_id)), None)
                if it is None:
                    raise StepError("解析のキューから消えました")
                st["detail"] = "%s %d%%" % (it.get("phase") or "", round((it.get("progress") or 0) * 100))
                if it.get("status") == "done":
                    st["detail"] = "解析しました(候補 %s 件)" % it.get("marks", "?") + fl_note
                    return None
                if it.get("status") in ("error", "cancelled", "skipped"):
                    raise StepError("解析が終わりませんでした: %s" % (it.get("error") or it.get("status")))
        except Cancelled:
            if qid:   # この実行が入れた解析だけ取り消す(人がスタジオで入れた解析 = qid なし は止めない)
                self._cancel_analysis(qid)
            raise
        finally:
            run.owned = None

    def _cancel_analysis(self, qid):
        """スタジオの解析のキューの1件を取り消し(POST /api/queue/cancel)、止まるまで待つ(CANCEL_WAIT 秒まで)。
        次の実行が同じ配信の解析をキューに入れられるように・重い処理の枠を空けてから進むため。失敗しても上げない(中止の途中)"""
        try:
            self.client.call("studio", "POST", "/api/queue/cancel", {"qid": qid})
            for _ in range(int(CANCEL_WAIT / self.poll) if self.poll > 0 else 30):
                st, obj = self.client.call("studio", "GET", "/api/queue")
                it = next((i for i in (obj.get("items") or []) if i.get("qid") == qid), None) if st == 200 else None
                if it is None or it.get("status") not in ("waiting", "running"):
                    return
                self.sleep(self.poll)
        except Exception:
            return

    # 採用 -------------------------------------------------------
    def _step_adopt_request(self, run, st, v):
        """友人からの依頼(URL): 時刻で指定した区間(前後に余白)を採用済みのマークにし、切り抜く数に足りない分を自動の上位で埋める。
        この実行で扱うのは、その区間と自動の分だけ(run.marks)。同じ配信の送り直しでは、前に作った切り抜き・文字起こしを使い回す"""
        dur = v.get("duration") or run.duration
        padded = [pad_range(s, e, dur) for s, e in run.ranges]
        auto = max(0, run.top - len(padded))
        body = {"id": run.video_id, "ranges": padded, "auto": auto}
        if run.fresh:
            body.update({k: run.fresh[k] for k in ("title", "channel") if run.fresh.get(k)})
        res = self.client.ok("studio", "POST", "/api/video/request-marks", body)
        rids, aids = res.get("rangeIds") or [], res.get("autoIds") or []
        run.marks = tuple(dict.fromkeys(rids + aids))
        if not run.marks:
            st["state"], st["detail"] = "skip", "採用できる候補がありません"
            run.message = "採用できる候補がありませんでした"
            return "stop"
        parts = (["指定の区間 %d 個(前後に %g 秒の余白)" % (len(rids), RANGE_PAD)] if rids else []) + \
            (["自動で %d 個(点数の高い順)" % len(aids) + ("。候補が足りず %d 個は選べませんでした" % (auto - len(aids)) if len(aids) < auto else "")] if auto else [])
        st["detail"] = "・".join(parts)
        return None

    def _step_adopt(self, run, st, v):
        if run.mode in REQUEST_URL_MODES:
            return self._step_adopt_request(run, st, v)
        res = self.client.ok("studio", "POST", "/api/video/adopt-top", {"id": run.video_id, "top": run.top})
        ids = res.get("adopted") or []
        marks = (res.get("video") or {}).get("marks") or []
        if ids:
            st["detail"] = "点数の高い %d 件を採用しました" % len(ids)
            return None
        if any(m.get("status") in ("adopted", "exported") for m in marks):
            st["state"], st["detail"] = "skip", "採用・書き出し済みのマークがあるので、それを使います"
            return None
        st["state"], st["detail"] = "skip", "採用できる候補がありません"
        run.message = "採用できる候補がありませんでした"
        return "stop"

    # 書き出し ---------------------------------------------------
    def _export_body(self, run, ids):
        rv = (self.client.ok("studio", "GET", "/api/settings").get("settings") or {}).get("review") or {}
        n = lambda x, lo, hi, d: x if isinstance(x, (int, float)) and not isinstance(x, bool) and lo <= x <= hi else d
        loud = rv.get("exportLoudness", -14)
        return {"id": run.video_id, "markIds": ids, "precision": "fast" if rv.get("precision") == "fast" else "accurate",
                "maxHeight": rv.get("maxHeight") if rv.get("maxHeight") in (0, 720, 1080, 1440, 2160) else 1080,
                "volume": int(n(rv.get("exportVolume"), 1, 200, 75)), "loudness": loud if loud in (-11, -14, -16, -18) else None}

    def _mine(self, run, v):
        """この実行で扱うマーク(マークを選んだ実行ならそれだけ)"""
        return [m for m in v.get("marks") or [] if not run.marks or m.get("id") in run.marks]

    def _step_export(self, run, st, v):
        ids = [m["id"] for m in self._mine(run, v) if m.get("status") == "adopted"]
        if not ids:
            done = sum(1 for m in self._mine(run, v) if m.get("status") == "exported")
            st["state"], st["detail"] = "skip", ("書き出し済み %d 本(新しく採用したものはありません)" % done if done else "採用したマークがありません")
            return None if done else "stop"
        body = self._export_body(run, ids[:50])
        while True:
            status, res = self.client.call("studio", "POST", "/api/export", body)
            if status == 200:
                break
            if status == 409 and res.get("error") == "busy":
                st["detail"] = "別の書き出しが終わるのを待っています"
                self._wait(run, BUSY_WAIT)
                continue
            raise StepError("書き出しを始められませんでした: %s" % (res.get("message") or "HTTP %d" % status))
        jid = res.get("id")
        try:
            while True:
                self._wait(run)
                j = self.client.ok("studio", "GET", "/api/export?id=" + jid)
                items = j.get("items") or []
                done = sum(1 for i in items if i.get("status") == "done")
                st["detail"] = ("他のツールの重い処理を待っています" if j.get("waiting") else "%d / %d 本" % (done, len(items)))
                if j.get("state") != "running":
                    break
        except Cancelled:
            self.client.call("studio", "POST", "/api/export/cancel", {"id": jid})
            raise
        bad = [i for i in items if i.get("status") == "error"]
        st["detail"] = "%d 本を書き出しました" % done + ("(%d 本失敗)" % len(bad) if bad else "")
        if bad and (not done or run.on_fail == "stop"):
            raise StepError("書き出しに失敗しました(%d 本): %s" % (len(bad), bad[0].get("error") or ""))
        if bad:
            st["state"] = "warn"
        return None

    # 文字起こし -------------------------------------------------
    def _clips(self, v, run=None):
        return [m for m in (self._mine(run, v) if run else v.get("marks") or []) if m.get("status") == "exported" and isinstance(m.get("path"), str) and m["path"]
                and os.path.isfile(m["path"])]

    def _step_transcribe(self, run, st, v):
        clips = self._clips(v, run)
        if not clips:
            st["state"], st["detail"] = "skip", "書き出した切り抜きがありません"
            return "stop"
        docs = txindex.load(txindex.folder(self.root, self.env))
        todo = [m for m in clips if not txindex.pick(docs, run.video_id, m.get("id"), m["path"])[0]]
        if not todo:
            st["state"], st["detail"] = "skip", "%d 本とも文字起こし済み" % len(clips)
            return None
        opts = self._tx_opts()
        jobs = []
        run.owned = ("transcribe", jobs)   # 入れたジョブ(同じリストに足していく)
        try:
            for m in todo:
                self._check(run)
                res = self.client.ok("transcribe", "POST", "/api/transcribe", dict(opts, sourcePath=m["path"]))
                jobs.append(res.get("id"))
            while True:
                self._wait(run)
                all_jobs = {j.get("id"): j for j in self.client.ok("transcribe", "GET", "/api/jobs").get("jobs") or []}
                mine = [all_jobs.get(j) or {"state": "error", "error": "文字起こしのジョブが見つかりません"} for j in jobs]
                fin = [j for j in mine if j.get("state") in ("done", "error", "cancelled")]
                cur = next((j for j in mine if j.get("state") not in ("done", "error", "cancelled", "queued")), None)
                st["detail"] = "%d / %d 本" % (len(fin), len(jobs)) + (" ・ %s %d%%" % (cur.get("phase") or "", round((cur.get("progress") or 0) * 100)) if cur else "")
                if len(fin) == len(jobs):
                    break
        except Cancelled:
            for j in jobs:
                self.client.call("transcribe", "POST", "/api/transcribe/cancel", {"id": j})
            raise
        finally:
            run.owned = None
        ok = [j for j in mine if j.get("state") == "done"]
        bad = [j for j in mine if j.get("state") != "done"]
        run.docs += [j["tid"] for j in ok if j.get("tid") and j["tid"] not in run.docs]
        run.new_docs += [j["tid"] for j in ok if j.get("tid")]
        st["detail"] = "%d 本を文字起こししました" % len(ok) + ("(%d 本失敗)" % len(bad) if bad else "") + "。字幕の校正は文字起こしの画面で"
        if bad and (not ok or run.on_fail == "stop"):
            raise StepError("文字起こしに失敗しました(%d 本): %s" % (len(bad), bad[0].get("error") or bad[0].get("state")))
        if bad:
            st["state"] = "warn"
        return None

    # パック -----------------------------------------------------
    def _edit_keeps(self, doc):
        """「編集」のカット(残す区間の秒。接している区間 = 分割しただけの所は1つに)と rev。無い・読めなければ (None, 0)"""
        status, res = self.client.call("transcribe", "GET", "/api/edit?id=" + urllib.parse.quote(str(doc["id"])))
        e = res.get("edit") if status == 200 and isinstance(res, dict) else None
        clips = e.get("clips") if isinstance(e, dict) else None
        if not clips:
            return None, 0
        out = []
        for c in clips:
            a, b = float(c["in"]), float(c["out"])
            if out and a <= out[-1][1] + 1e-9:
                out[-1][1] = max(out[-1][1], b)
            else:
                out.append([a, b])
        return out, int(res.get("rev") or 0)

    def _pack_settings(self):
        """パックの作り方(編集の設定 = 3 パック のタブと同じ値。気が利く画面へ 段4 = 以前は fps・縦横・予備・話者の色を無視していた):
        行から作るときの端の広げ方(rowEdge。形が変なら既定で作って知らせる)・Text+ の置き先(packFps・packSize)・1段の文字数(縦横に合わせる)・
        話者の色・音量・予備(packBackup)・無音で削るときの値(cutSilence)。-> (rowEdge, output に足すもの, cutSilence, 知らせ)"""
        tx_settings = self.client.ok("transcribe", "GET", "/api/settings")
        notes = []
        row_edge = tx_settings.get("rowEdge")
        if row_edge is not None and not _row_edge_ok(row_edge):
            notes.append("「行から」の設定の形が正しくないので、既定の広げ方で作りました(「編集」の 2 カット の「行から ▾」で直せます)")
            row_edge = None
        size = tx_settings.get("packSize") if tx_settings.get("packSize") in ("1080x1920", "1920x1080") else "1080x1920"
        fps = str(tx_settings.get("packFps") or "30")
        # 素材は 30fps にそろえる(2026-10-04 Q1)。素材がちょうど 30fps のときは、設定の packFps(60 など)に関係なく 30 にする
        # (「編集」の 3 パック と同じ。30fps でない古い素材だけ設定の値を使う)。素材の fps は _source_fps が分かるときだけ
        sub = tx_settings.get("subtitle") if isinstance(tx_settings.get("subtitle"), dict) else {}
        wrap = (sub.get("wrapChars") or {}).get("horizontal" if size == "1920x1080" else "vertical") if isinstance(sub.get("wrapChars"), dict) else None
        wrap_out = {"textplusWrap": wrap} if isinstance(wrap, int) and not isinstance(wrap, bool) and 0 <= wrap <= 40 else {}
        wrap_out["textplusSize"] = size
        if re.fullmatch(r"\d{1,3}(\.\d{1,3})?", fps):
            wrap_out["textplusFps"] = fps
        if tx_settings.get("packBackup") is True:
            wrap_out["backup"] = True
        wrap_out["speakerColors"] = tx_settings.get("speakerColors") is not False   # 話者の名前がメンバーと合えばその色(編集の設定と同じ。以前は無視して常にオン)
        cs = tx_settings.get("cutSilence") if isinstance(tx_settings.get("cutSilence"), dict) else {}
        cut_silence = {k: cs[k] for k in ("noise", "min", "pad") if isinstance(cs.get(k), (int, float)) and not isinstance(cs.get(k), bool)}
        loud = tx_settings.get("packLoudness", 0)   # 聞こえ方の音量をそろえる目標(LUFS。編集の設定 = パックのタブと同じ値。0 = そろえない。既定は 0 = 音量 30%。2026-10-01)
        if loud in (-11, -14, -16, -18) and not isinstance(loud, bool):
            wrap_out["loudness"] = loud
        else:   # LUFS でそろえないときは音量(%)。元 = 100
            vol = tx_settings.get("packVolume", 30)
            if isinstance(vol, int) and not isinstance(vol, bool) and 1 <= vol <= 200 and vol != 100:
                wrap_out["volume"] = vol
        return row_edge, wrap_out, cut_silence, notes

    def _cut_method(self):
        """カットを決めていない文書のカットの方法(ホームの設定 autorun.cut。読めなければ none)"""
        m = self._pref("cut")
        return m if m in ("rows", "none", "silence") else "none"   # 既定はカットしない(2026-10-01)

    @staticmethod
    def _speaker_styles(run):
        """友人が指定した人ごとの字幕の見た目 -> {名前: {"color": "#RRGGBB"}}(無ければ {})。
        色は画面・Lua に入るので、ここでも 16 進 6 桁だけにそろえ直す(intake の検査を通ってきたはずだが、実行の作り手がほかにも増えたときのため)"""
        out = {}
        raw = (run.speakers or {}).get("styles")
        for name, sty in (raw.items() if isinstance(raw, dict) else []):
            hx = colors.norm_hex(sty.get("color")) if isinstance(name, str) and name and isinstance(sty, dict) and isinstance(sty.get("color"), str) else None
            if hx:
                out[name] = {"color": hx}
        return out

    def _pack_one(self, run, st, doc, media, pack_opts, force=False, prefix=""):
        """1本のパックを cut2resolve で作る。「編集」でカットを決めてあればそのとおり(3 パック のタブのパックと同じ中身)、
        無ければ文字起こしの行だけを残す規則(preset transcript-rows)。-> ("made", カットのとおりか) か ("exists", False)(同じ名前のパックがあり force でない)"""
        row_edge, wrap_out, cut_silence = pack_opts[:3]
        if wrap_out.get("textplusFps", "30") != "30" and _media_is_30fps(media):
            wrap_out = dict(wrap_out, textplusFps="30")   # 素材がちょうど 30fps なら設定の packFps に関係なく 30(Q1。_pack_settings の説明)
        keeps, rev = self._edit_keeps(doc)
        if keeps:
            captions = any(s.get("text", "").strip() and not s.get("cut") for s in doc.get("segments") or [])
            tr = self.client.ok("transcribe", "POST", "/api/export-file", {"id": doc["id"], "format": "transcript-v1"}) if captions else {}
            spec = dict({"video": media, "keeps": keeps}, **({"transcript": tr.get("path")} if captions else {}))
            body = {"spec": spec, "output": dict({"textplus": captions, "copyVideo": True}, **wrap_out)}
        else:   # カットを決めていない文書: カットの方法(ホームの設定。rows = 行から・none = カットしない・silence = 無音で削る)
            tr = self.client.ok("transcribe", "POST", "/api/export-file", {"id": doc["id"], "format": "transcript-v1"})
            method = run.cut or self._cut_method()   # 友人が選んだカット(① の依頼)。無ければホームの設定
            if method == "none":   # 動画全体(削る区間なし)。カット済の行の字幕も消さない
                spec = {"video": media, "transcript": tr.get("path"), "mode": "list", "listKind": "drop", "listText": "", "dropCutRows": False, "minLen": 0}
            elif method == "silence":   # 無音で削る(値は編集の設定 cutSilence。無ければ cut2resolve の既定)
                spec = {"video": media, "transcript": tr.get("path"), "mode": "silence", "silence": cut_silence}
            else:
                spec = {"video": media, "transcript": tr.get("path"), "preset": "transcript-rows"}
                if isinstance(row_edge, (bool, dict)):
                    spec["rowEdge"] = row_edge
            body = {"spec": spec, "output": dict({"textplus": True}, **wrap_out)}
        if force:
            body["output"]["force"] = True
        if run.video_tracks:   # 友人が選んだ映像トラックの数(字幕はその上のトラック)
            body["output"]["videoTracks"] = run.video_tracks
        self._auto_streamer(run, doc)
        if run.streamer:   # 字幕の文字を配信者のメンバーカラーに(cut2resolve が同じ規則で照らし合わせる)
            body["output"]["streamer"] = run.streamer
        styles = self._speaker_styles(run)
        if styles:   # 友人が指定した話者ごとの字幕の色(古い cut2resolve は知らない鍵を読み飛ばす。空なら鍵ごと付けない = 今までと同じ要求)
            body["output"]["speakerStyles"] = styles
        while True:
            status, res = self.client.call("cut2resolve", "POST", "/api/build", body)
            if not (status == 409 and res.get("error") == "busy"):
                break
            st["detail"] = prefix + "cut2resolve の別の処理が終わるのを待っています"
            self._wait(run, BUSY_WAIT)
        if status == 409 and res.get("error") == "exists":
            return "exists", False
        if status != 200:
            raise StepError("パックを作れませんでした: %s" % (res.get("message") or "HTTP %d" % status))
        jid = (res.get("job") or {}).get("id")
        run.owned = ("cut2resolve", [jid])
        try:
            while True:
                self._wait(run)
                j = self.client.ok("cut2resolve", "GET", "/api/job?id=" + jid)
                if j.get("state") != "running":
                    break
                if j.get("message"):
                    st["detail"] = prefix + j["message"]
        except Cancelled:
            self.client.call("cut2resolve", "POST", "/api/job/cancel", {"id": jid})
            raise
        finally:
            run.owned = None
        if j.get("state") != "done":
            err = j.get("error")
            raise StepError("パックを作れませんでした: %s" % ((err.get("message") if isinstance(err, dict) else err) or j.get("state")))
        r = j.get("result") or {}
        if r.get("outDir") and r["outDir"] not in run.packs:
            run.packs.append(r["outDir"])   # ① 全自動で Dropbox へ届けるもの
            if run.deliver_dir and "deliver" in MODE_STEPS[run.mode]:   # できた順に1本ずつ届ける(全部を待たない。2026-10-01)
                st["detail"] = prefix + "Dropbox へ届けています"
                self._deliver_one(run, r["outDir"])
        if keeps:   # 作った記録(packRev)を「編集」に残す(カット・字幕を直したら「作り直し」と知らせるため)。残せなくてもパックはできている
            self.client.call("transcribe", "POST", "/api/edit/pack", {"id": doc["id"], "rev": rev, "docUpdatedAt": int(doc.get("updatedAt") or 0),
                                                                      "dir": r.get("outDir") or "", "files": [f.get("name") for f in r.get("files") or [] if isinstance(f, dict)]})
        return "made", bool(keeps)

    def _step_pack(self, run, st, v):
        clips = self._clips(v, run)
        docs = txindex.load(txindex.folder(self.root, self.env))
        todo, no_tx, made = [], 0, 0
        for m in clips:
            doc = txindex.pick(docs, run.video_id, m.get("id"), m["path"])[0]
            if not doc:
                no_tx += 1
            elif run.overwrite or not self.find_pack(m["path"]):
                todo.append((m, doc))
        if not todo:
            st["state"], st["detail"] = "skip", ("パック済み(「パックがあれば作り直す(上書き)」を選ぶと作り直します)" if clips and not no_tx else "文字起こしのある切り抜きがありません")
            return None
        skipped, failed, by_edit = [], [], 0
        opts = self._pack_settings()
        self._auto_streamer(run, todo[0][1] if todo else None, v)
        for i, (m, doc) in enumerate(todo, 1):
            self._check(run)
            prefix = "%d / %d 本 ・ " % (i - 1, len(todo))
            st["detail"] = prefix.rstrip(" ・ ")
            try:
                res, cut = self._pack_one(run, st, doc, m["path"], opts, force=run.overwrite, prefix=prefix)
            except StepError as e:
                if run.on_fail == "stop":
                    raise
                failed.append("%s(%s)" % (os.path.basename(m["path"]), str(e)[:120]))   # 次へ進む設定: 残りを続ける
                continue
            if res == "exists":
                skipped.append(os.path.basename(m["path"]))   # 同じ名前のパックがある: 上書きしない(人が作り直したものかもしれない)
                continue
            made += 1
            by_edit += 1 if cut else 0
            if doc["id"] not in run.docs:
                run.docs.append(doc["id"])
        if failed and not made:
            raise StepError("パックを作れませんでした: %s" % failed[0])
        st["detail"] = "%d 本のパックを作りました" % made + ("(うち %d 本は「編集」のカットのとおり)" % by_edit if by_edit else "") + \
            ("。前のパックを上書きしました" if run.overwrite and not run.request_id else "") + "。字幕を校正したら「編集」のパックのタブで作り直してください"
        if skipped:
            st["detail"] += "。同じ名前のパックがあるので上書きしなかったもの: %s" % "・".join(skipped[:5])
        if failed:
            st["state"] = "warn"
            st["detail"] += "。失敗した %d 本: %s" % (len(failed), "・".join(failed[:3]))
        for n in opts[3]:
            st["detail"] += "。" + n
        if run.streamer_from:   # 自動で入れた配信者は進み具合に出す(コラボで相手の色になることがあるため。段5)
            st["detail"] += "。字幕の色: %s(%s)" % (run.streamer, "自動: チャンネル名から" if run.streamer_from == "auto" else "前回の名前")
        return None

    # 文書単位の実行(⑦(b)) -------------------------------------
    def _doc(self, run):
        d = next((x for x in txindex.load(txindex.folder(self.root, self.env)) if x["id"] == run.doc_id), None)
        if not d:
            raise StepError("文書が見つかりません(消した可能性があります)")
        run.title = d["title"] or run.title
        src = d.get("sourcePath") or ""
        if not src or not os.path.isfile(src):
            raise StepError("元の動画が見つかりません(移動・削除した可能性があります)")
        return d

    def _tx_opts(self):
        """文字起こしの設定(「編集」の設定のうち TX_KEYS。画面から文字起こしするときと同じ値)"""
        opts = self.client.ok("transcribe", "GET", "/api/settings")
        return {k: opts[k] for k in TX_KEYS if k in opts and isinstance(opts[k], (str, bool, int, float))}

    def _wait_job(self, run, jid, st=None, what="文字起こし"):
        """「編集」のジョブ 1 つが終わるまで待つ(st があれば進み具合を出す)。中止されたらジョブを取り消して上げる。-> 終わったジョブ"""
        run.owned = ("transcribe", [jid])
        try:
            while True:
                self._wait(run)
                j = next((x for x in self.client.ok("transcribe", "GET", "/api/jobs").get("jobs") or [] if x.get("id") == jid),
                         {"state": "error", "error": "%sのジョブが見つかりません" % what})
                if j.get("state") in ("done", "error", "cancelled"):
                    return j
                if st is not None:
                    st["detail"] = "%s %d%%" % (j.get("phase") or "", round((j.get("progress") or 0) * 100))
        except Cancelled:
            self.client.call("transcribe", "POST", "/api/transcribe/cancel", {"id": jid})
            raise
        finally:
            run.owned = None

    def _doc_transcribe(self, run, st):
        doc = self._doc(run)
        if doc["count"]:
            st["state"], st["detail"] = "skip", "文字起こし済み"
            return None
        jid = self.client.ok("transcribe", "POST", "/api/transcribe", dict(self._tx_opts(), sourcePath=doc["sourcePath"], intoDoc=doc["id"])).get("id")
        j = self._wait_job(run, jid, st)
        if j.get("state") != "done":
            raise StepError("文字起こしに失敗しました: %s" % (j.get("error") or j.get("state")))
        st["detail"] = "文字起こししました。字幕の校正は「編集」で"
        return None

    def _doc_pack(self, run, st):
        doc = self._doc(run)
        if self.find_pack(doc["sourcePath"]) and not run.overwrite:
            st["state"], st["detail"] = "skip", "パック済み(「作り直す」を選ぶと上書きします)"
            return None
        if not any(s.get("text", "").strip() and not s.get("cut") for s in doc.get("segments") or []) and not self._edit_keeps(doc)[0]:
            st["state"], st["detail"] = "skip", "残す字幕の行もカットも無いので、パックを作れません(2 カット のタブで区間を決めると作れます)"
            return None
        opts = self._pack_settings()
        res, cut = self._pack_one(run, st, doc, doc["sourcePath"], opts, force=run.overwrite)
        if res == "exists":   # find_pack で見つからない名前違いのパック(以前の版で作ったもの)など
            st["state"], st["detail"] = "skip", "同じ名前のパックがあるので上書きしませんでした(「作り直す」を選ぶと上書きします)"
            return None
        st["detail"] = "パックを作りました" + ("(「編集」のカットのとおり)" if cut else "(文字起こしの行から)") + \
            ("。前のパックを上書きしました" if run.overwrite else "") + "".join("。" + n for n in opts[3])
        return None


    # 話者分離(友人の「話す人」) --------------------------------
    def _step_diarize(self, run, st, v=None):
        """この実行で文字起こしした文書を、友人が入れた人数で話者分離し、名前は覚えている声と照らし合わせる(1人なら判別せずその人)。
        失敗しても次の段へ進む(字幕は話者なしのまま。一部失敗)"""
        tids = list(dict.fromkeys(run.new_docs))
        if not tids:
            st["state"], st["detail"] = "skip", "新しく文字起こしした文書がありません"
            return None
        sp = run.speakers or {}
        body = {"numSpeakers": sp.get("count"), "names": list(sp.get("names") or []), "recognize": True}
        styles = self._speaker_styles(run)   # 友人が指定した字幕の色(あれば話者分離のあと、文書に覚える)
        bad, no_color = [], []
        for i, tid in enumerate(tids, 1):
            self._check(run)
            st["detail"] = "%d / %d 本" % (i - 1, len(tids))
            status, res = self.client.call("transcribe", "POST", "/api/diarize", dict(body, tid=tid))
            if status != 200:
                bad.append(res.get("message") or "HTTP %d" % status)
                continue
            j = self._wait_job(run, res.get("id"), what="話者分離")
            if j.get("state") != "done":
                bad.append(j.get("error") or j.get("state"))
            elif styles and not self._remember_styles(tid, styles):
                no_color.append(tid)
        n = sp.get("count")
        st["detail"] = "%d 本を %d 人に分けました" % (len(tids) - len(bad), n) + ("(名前: %s)" % "・".join(sp["names"]) if sp.get("names") else "") + \
            "。名前の分からない人は「話者1」などのまま"
        if styles and len(no_color) < len(tids) - len(bad):
            st["detail"] += "。字幕の色を覚えました(%s)" % "・".join(styles)
        if no_color:   # 古い「編集」など。依頼は止めない(一部失敗にもしない。パックには色を渡すので、その分の字幕には効く)
            st["detail"] += "。字幕の色を覚えられませんでした(%d 本)" % len(no_color)
        if bad:
            st["state"] = "warn"
            st["detail"] += "。失敗した %d 本: %s" % (len(bad), str(bad[0])[:120])
        return None

    def _remember_styles(self, tid, styles):
        """指定された字幕の色を、文書の話者(名前が合う人)に「字幕の見た目」として覚える(編集の POST /api/speakers/sub)。-> 成功したか。
        失敗(古い編集の 404・その他)しても依頼は止めない。名前の合う人がいなくても 200(その場合も成功)"""
        try:
            status, res = self.client.call("transcribe", "POST", "/api/speakers/sub", {"id": tid, "styles": styles})
        except Cancelled:
            raise
        except Exception:
            return False
        return status == 200 and isinstance(res, dict) and res.get("ok") is True

    def _file_diarize(self, run, st):
        return self._step_diarize(run, st)

    # 依頼の動画(mode file) -------------------------------------
    def _file_analyze(self, run, st):
        """依頼 ③: 友人の動画をスタジオに入れて盛り上がりの解析まで(切り抜く所は人が決める)"""
        if not os.path.isfile(run.source_path):
            raise StepError("依頼の動画が見つかりません(移動・削除した可能性があります)")
        self._analyze_item(run, st, {"kind": "file", "path": run.source_path, "title": run.title}, None)
        st["detail"] += "。切り抜く所はスタジオで決めてください"
        return None

    def _file_pack(self, run, st):
        if not run.doc_id:
            st["state"], st["detail"] = "skip", "文字起こしの文書がありません"
            return "stop"
        return self._doc_pack(run, st)

    def _file_deliver(self, run, st):
        found = self.find_pack(run.source_path)
        return self._deliver(run, st, list(run.packs) + ([found["dir"]] if found else []))

    def _step_deliver(self, run, st, v):
        dirs = list(run.packs)
        for m in self._clips(v, run):
            found = self.find_pack(m["path"])
            if found:
                dirs.append(found["dir"])
        return self._deliver(run, st, dirs)

    def _deliver_name(self, run, d):
        base = os.path.basename(os.path.normpath(d))
        base = base[:-5] if base.endswith("_pack") else base
        return deliver_mod.safe_name("%s__%s" % (run.request_id or run.id, base or run.title or "pack"))

    def _deliver(self, run, st, dirs):
        """① 全自動: パックのフォルダを zip にして Dropbox の 出力\\ へ置く(友人のアプリの「受け取る」に出る)。
        zip は Dropbox の外(パックの隣)で作ってから移す(書きかけを同期させない・友人の一覧に出さない)"""
        dirs = [d for d in dict.fromkeys(os.path.normpath(x) for x in dirs if x) if os.path.isdir(d)]
        if not run.deliver_dir:
            st["state"], st["detail"] = "skip", "届け先がありません"
            return None
        if not dirs:
            st["state"], st["detail"] = "skip", "届けるパックがありません"
            return None
        todo = [d for d in dirs if d not in run.delivered]
        for i, d in enumerate(todo, 1):
            self._check(run)
            st["detail"] = "%d / %d 本を zip にしています" % (i - 1, len(todo))
            self._deliver_one(run, d)
        st["detail"] = "%d 本のパックを Dropbox の 出力 に置きました(字幕は校正前)" % len(run.delivered)
        return None

    def _deliver_one(self, run, d):
        """1本のパックのフォルダを zip にして 出力\\ へ置く(作り方は src/home/deliver.py。「編集」の「友人へ届ける」と同じ)"""
        d = os.path.normpath(d)
        if d in run.delivered or not os.path.isdir(d):
            return
        try:
            deliver_mod.zip_pack(d, run.deliver_dir, self._deliver_name(run, d), check=lambda: self._check(run))
            run.delivered.append(d)
            self._save_active()   # 届けたことをすぐ残す(段の途中で起動し直しても、同じパックを二度置かない。M5・入口 0.41.0)
        except OSError as e:
            raise StepError("パックを Dropbox へ置けませんでした: %s" % (e.strerror or e.__class__.__name__))

    def _deliver_failure(self, run):
        """① 全自動が止まったとき、友人のアプリの「受け取る」に理由を出す(<依頼 id>__<題名>.失敗.txt)"""
        try:
            os.makedirs(run.deliver_dir, exist_ok=True)
            name = deliver_mod.safe_name("%s__%s" % (run.request_id or run.id, run.title or "依頼")) + ".失敗.txt"
            text = "自動の処理が止まりました。\r\n理由: %s\r\n送り先の人が確かめます。" % (run.error or run.message)
            with open(os.path.join(run.deliver_dir, name), "w", encoding="utf-8-sig", newline="") as f:
                f.write(text + "\r\n")
        except OSError:
            pass

    def _file_transcribe(self, run, st):
        if not os.path.isfile(run.source_path):
            raise StepError("依頼の動画が見つかりません(移動・削除した可能性があります)")
        doc = txindex.pick(txindex.load(txindex.folder(self.root, self.env)), None, None, run.source_path)[0]
        if doc and doc.get("count"):
            st["state"], st["detail"] = "skip", "文字起こし済み"
            tid = doc["id"]
        else:
            opts = self._tx_opts()
            if run.engine:   # 実行ごとに選んだエンジン・モデル(リアルタイム切り抜きの live.auto。M2)。無ければ編集の設定のまま
                opts["engine"] = run.engine
            if run.model:
                opts["model"] = run.model
            jid = self.client.ok("transcribe", "POST", "/api/transcribe", dict(opts, sourcePath=run.source_path)).get("id")
            j = self._wait_job(run, jid, st)
            if j.get("state") != "done":
                raise StepError("文字起こしに失敗しました: %s" % (j.get("error") or j.get("state")))
            tid = j.get("tid")
            if tid:
                run.new_docs.append(tid)
            st["state"], st["detail"] = "done", "文字起こししました。字幕の校正は「編集」で"
        if tid and tid not in run.docs:
            run.docs.append(tid)
        run.doc_id = tid or None   # ① 全自動: この文書でパックを作る
        if tid and run.streamer and self.prefs:   # 依頼で選んだ配信者を、この文書の配信者として覚える(パックのときの字幕の色。段5 の記憶と同じ)
            try:
                self.prefs.remember("docs", tid, run.streamer)
                st["detail"] += "。配信者: %s" % run.streamer
            except (OSError, ValueError):
                pass
        return None


def _row_edge_ok(v):
    """「行から」の設定の形(cut2resolve の pack.row_edge_from と同じ決まり: 真偽か {on?, after?, before?}(0〜2 秒))"""
    if isinstance(v, bool):
        return True
    if not isinstance(v, dict) or ("on" in v and not isinstance(v["on"], bool)):
        return False
    for k in ("after", "before"):
        x = v.get(k)
        if x not in (None, "") and (isinstance(x, bool) or not isinstance(x, (int, float)) or not 0 <= x <= 2.0):
            return False
    return True

