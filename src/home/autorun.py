"""まとめて実行(統合計画の段階5。2026-09-26)。入口の「案件」の画面から、配信1本ぶんの作業を順に自動で流す。

形は3つ(ユーザー決定「選べるようにする」):
  full        解析から全部   … (未解析なら)解析 → 自動マークの上位を採用 → 書き出し → 文字起こし → Resolve パック
  adopted     採用後を全部   … 採用したマークの書き出し → 文字起こし → Resolve パック(切り抜きの良し悪しは人が決める)
  transcribe  文字起こしまで … 採用したマークの書き出し → 文字起こし(パックは校正してから人が作る)

作り:
- ① の経路(Run・段の表・段の中身・待つ骨組み)は RS1-7 で src/pipeline/run.py へ移した(役割で組み直す計画 plan/role-restructure.md の 5-1)。
  ここに残すのは、順番待ちと糸・受付・中止・記録・起動し直しで戻す・見積もり・ToolClient と、
  Runner の hook(案件・ホームの設定を読む所)の中身。移した名前は同じ名前で読み直している。
  届けることと組の溜めは RS3-3 で src/human/friend/delivery.py の Delivery(mixin)へ切り出した(AutoRunner が継ぐ)
- 各ツールの**公開している API を HTTP で呼ぶ**(入口と同じ 127.0.0.1。取り込んだツールは入口のポートの /studio/ など、子プロセスのツールはそのポート)。
  ツールの中の関数を直接呼ばないのは、画面から使うときと同じ検査・同じジョブ管理(重い処理の順番待ち ytt.jobs を含む)を通すため。
- どの段も「まだ無いものだけ」作る(書き出し済み・文字起こし済み・パック済みは飛ばす)。途中で止めても、もう一度押せば続きから進む。
  文字起こしの有無は manage.cases.txindex(案件の画面・スタジオのセリフと同じ規則)、パックの有無は cases.find_pack で見る。
- スタジオの ① 探す で選んだ配信(まだスタジオに無い YouTube の配信)は start_new で「解析から全部」に入れる。解析のキューに入れると
  スタジオに配信ができるので、それまでは受け取った題名で進める(git の履歴(679ff01 以前)の docs/archive/followup-2026-09-27.md の 5)。
- 1本ずつ順に処理する(キュー)。同じ配信を2つ同時には入れない。
- 入口の起動し直しで、順番待ち・実行中の分を戻す(線 D の M5。入口 0.40.0): 待ち・実行中の実行を入口の作業データの logs/autorun-active.json に残し
  (入れたとき・始めたとき・段が済むたび・終わったとき。一時ファイルから置き換える)、起動したときに読んで同じ id のまま「待ち」に戻す。
  済んだ段は飛ばし、途中だった段は頭からやり直す(どの段も「まだ無いものだけ」作るので、続きから進む)。入口の終了(「すべて終了」・黒い画面を閉じる・
  強制終了)で止まった実行は記録(autorun-runs.jsonl)に「中止」と書かない。起動し直してすぐはツールの準備を待つ(RESUME_WAIT 秒まで)。
  RESTORE_MAX_AGE(3 日)より前に入れた実行は戻さず、記録に「中止」と書く
- 終わった実行は、入口の作業データの logs/autorun-runs.jsonl に1行ずつ残す(段2 B-6。入口を起動し直しても、ホームで前回の結果と止まった理由を見られる)。
  書くのは終わったとき(完了・失敗・中止)だけ(入口の終了で止まった実行は、次の起動で続けるので書かない = M5)。
  1MB を超えたら .1 に回す(1世代。画面のエラーの記録 clientlog.py と同じ形)。書けなくても実行は止めない
- 自動で採用したマークは、人の判定ではないので学習の記録(スタジオの feedback)に入れない(スタジオの /api/video/adopt-top)。
- 解析の設定は既定値(解析の画面の設定はブラウザの中にしか無いため)。書き出しはスタジオの ③ の設定(画質・音量のそろえ方)、
  文字起こしは「編集」(文字起こし)の設定(モデルなど)を使う。パックは、「編集」でカットを決めてあればそのとおり(cut2resolve の spec.keeps。
  作った記録も「編集」に残す = 作り直しの知らせ)、無ければ文字起こしの行だけを残す規則(preset transcript-rows)。どちらも Text+(字幕の元の行が無ければ Text+ なし)。
  リアルタイム切り抜きの自動の採用(.clip.json の source.live.origin が auto・archive)の切り抜きは、カットを指定していなければ区間の全体
  (LIVE_AUTO_CUT。線 D の M8。区間は検出が静かな所に合わせて絞ってある)。ホームの設定 live.auto.cut(none・silence)を選べばそれ(M2)。
- ① 全自動の Dropbox へ届ける段: パックを n 本(依頼ごとの deliver_batch。無ければホームの設定 intake.deliverBatch)たまるごとに、組 = まとめ動画 1 本 +
  1 本ずつの zip + 組の一覧(.group.json)で Dropbox の 出力 へ置く(実行の終わりには n 本に満たない残りも)。n=1 か 1 本だけのときは
  1 本の zip + その隣のまとめ動画(<同じ名前>.preview.mp4)。友人は 1 本ずつ受け取る・要らないを選べる(docs/spec/friend-intake.md の 2-16)。作り方・名前は src/human/friend/deliver.py、
  届ける段と組の溜めの中身は src/human/friend/delivery.py(RS3-3)
  ライブの切り抜き(友人のライブ配信の依頼・live.autoDeliver)は 1 本ごとに別の実行なので、実行をまたいで「組の溜め」(run.pool。依頼 × 配信中 / 配信後の追加)に預け、
  n 本たまったら組で届ける。録画が終わって書き出しも実行も残っていなければ、最後に預けてから POOL_IDLE_SEC で残りを届ける(flush_pools。入口の src/home/live.py が見回りで呼ぶ)。
  溜めは logs/deliver-pool.json に残す(起動し直しても続く)。10-09 ユーザー決定 = decisions 3-20
- 「あとから解析(測るため)」(友人の依頼が区間だけで終わった配信を、手が空いたときに解析する mode post_analyze)は RS4 で消した(入口 0.55.0)。
  代わりは測る道具 `py -3.10 src/eval/tools/eval_marks.py --analyze-missing --wait`(未解析の友人の配信の解析をスタジオに頼む)。
  以前の一覧 logs/autorun-deferred.json は読まない(残っていても害はない)
"""
import collections
import http.client
import json
import os
import re
import urllib.parse
import threading
import time

from manage.cases import txindex
from ytt import colors, fsio
from pipeline import spec as _spec  # noqa: E402  (指定の束の検査・既定値。RS1-6 で RANGE_MAX・clean_ranges・top_arg などをここへ移した。下で同じ名前で読み直す)
from pipeline.spec import (CUTS, DEFAULT_TOP, LIVE_AUTO_CUT, MAX_MARKS, RANGE_MAX, RANGE_MAX_SEC, RANGE_PAD, TX_ENGINES, TX_MODEL_RE,  # noqa: E402,F401
                           WEIGHT_KEYS, clean_ranges, clean_weights, pad_range)
from pipeline import runlog  # noqa: E402  (終わった実行の記録の形と読み方。RS3-0B で read_runs_log などをここへ出した)
from pipeline import run as run_mod  # noqa: E402  (① の経路 = Run・Runner・段の表。RS1-7 で移した。AutoRunner は Runner を継いで hook を埋める。下で同じ名前で読み直す)
from pipeline.run import (BUSY_WAIT, CANCEL_WAIT, DOC_LABEL, DOC_MODE, DONE_STEPS, JOB_STATE_JA, MODE_STEPS, MODES, NOTHING_MESSAGE,  # noqa: E402,F401
                          REQUEST_MODES, REQUEST_URL_MODES, RUN_ID_RE, RUN_STATE_LABELS, STEP_LABELS, STEP_STATE_LABELS,
                          TX_KEYS, Cancelled, Run, StepError, _has_captions, _job_why, _media_is_30fps, _row_edge_ok, clean_pool)
from manage.cases import cases  # noqa: E402  (src/manage/cases/cases.py: パックの有無・.clip.json の読み方・スタジオの一覧を案件の画面とそろえる。friend_feedback も先頭で読む = 循環しない)
from human.friend import delivery as delivery_mod  # noqa: E402  (友人へ届ける段と組の溜め = AutoRunner が継ぐ Delivery。RS3-3 で切り出した)
import prefs as prefs_mod  # noqa: E402  (ホームの設定の既定値と範囲。読み書きは渡された Prefs で)

# RANGE_MAX・RANGE_MAX_SEC・RANGE_PAD・pad_range・CUTS・TX_ENGINES・TX_MODEL_RE・WEIGHT_KEYS は src/pipeline/spec.py へ、
# MODES・MODE_STEPS・STEP_LABELS・Run・StepError など ① の経路は src/pipeline/run.py へ移した(上で読み直している)
FLOW_MODES = {"url": {"auto": "request_auto", "check": "request"},
              "file": {"auto": "file_auto", "check": "file"}}
MAX_NEW = 10           # ① 探す から一度に入れられる配信の数(① 探す で選べる最大と同じ)
MAX_KEEP = 30          # 終わった記録を残す数(メモリ。ファイルの記録は runlog.RUNS_LOG)
# 終わった実行の記録のファイル名 RUNS_LOG と1行の形の版 LOG_VERSION・読み方 read_runs_log は src/pipeline/runlog.py(RS3-0B。入口の外の部品も読むため)
LOG_MAX_BYTES = 1024 * 1024   # これを超えたら .1 に回す(1件 1〜2KB なので 500〜1000 件ぶん)
LOG_READ_BYTES = 256 * 1024   # 起動時に読む末尾の大きさ(前回の結果 past を作る)
PAST_MAX = 50          # snapshot の past(配信・文書ごとの前回の結果で、メモリに無いもの)の数
PAST_KEEP = 500        # past の元として覚えておく配信・文書の数
HISTORY_DEFAULT, HISTORY_MAX = 50, 200   # /api/autorun/history の limit の既定と上限
PAST_KEYS = ("id", "kind", "docId", "videoId", "title", "mode", "modeLabel", "state", "stateLabel", "nothing", "message", "error",
             "created", "finished", "steps")   # past に入れる項目(2〜15 秒ごとの問い合わせを重くしない。全部は history で)
MAX_WAITING = 20       # 順番待ちの上限
# 友人の区間の長さを、依頼の自動の候補の長さに使う(2026-10-05 ユーザーの要望。仮の決定 = まとめ役)。
# 測る道具 src/eval/tools/eval_marks.py --json の結果(スタジオの作業データ evals\marks\<日時>.json。入口の夜の自動測定が流す)の clipLength を読むだけ
FRIEND_LENGTH_ENV = "YTT_FRIEND_LENGTH"   # off = 使わない(ホームの設定 autorun.friendLength が false でも使わない)
FRIEND_LENGTH_MIN_SAMPLES = 20         # 友人の区間の見本の数(外れ値を除く)
FRIEND_LENGTH_MIN_VIDEOS = 5           # その配信の数
FRIEND_PRE_MIN_SAMPLES = 10            # 山の位置(preRatio)を使う見本の数
FRIEND_LENGTH_MAX_AGE = 30 * 86400     # 結果のファイルの古さ(ファイル名の日時)
FRIEND_LENGTH_RANGE, FRIEND_PRE_RANGE = (10, 120), (0.3, 0.9)   # スタジオの解析の設定 length・preRatio の範囲(src/pipeline/analyze/analyze.py の validate_settings)
EVAL_MARKS_NAME_RE = re.compile(r"^(\d{8}-\d{6})(?:_auto)?\.json\Z")   # src/eval/drill/accuracy.py の RESULT_NAME_RE と同じ形
EVAL_READ_MAX = 16 * 1024 * 1024
# 入口の起動し直しで戻す(線 D の M5。2026-10-07)
ACTIVE_FILE = "autorun-active.json"  # 待ち・実行中の実行(入口の作業データの logs の中。runlog.RUNS_LOG の隣)
ACTIVE_VERSION = 1
ACTIVE_READ_MAX = 4 * 1024 * 1024
RESTORE_MAX_AGE = 3 * 86400          # これより前に入れた実行は戻さない(記録に「中止」と書く)
RESUME_WAIT = 120.0                  # 戻した実行は、使うツールが動くまでこれだけ待つ(入口の起動の直後はまだ準備中のことがある)
STEP_TOOLS = {"analyze": ("studio",), "adopt": ("studio",), "export": ("studio",), "transcribe": ("transcribe",), "diarize": ("transcribe",),
              "pack": ("transcribe", "cut2resolve"), "deliver": ()}
# 画面の「起動し直す」(launch.py の restart_self。入口 0.41.0)で、ツールの仕事を止めてよい段(起動し直したあとに頭からやり直す = M5)。
# 書き出し(export)は入れない: 書き出し中は今までどおり断る
REDO_STEPS = ("analyze", "transcribe", "diarize", "pack")
TX_ACTIVE = ("queued", "loading", "extracting", "running")   # 「編集」のジョブの動いている状態(src/ytt/jobs.py の ACTIVE_STATES)
QUEUE_ACTIVE = ("waiting", "running")                       # スタジオの解析のキューの動いている状態(src/pipeline/batch.py)


TOOL_NAMES = {"studio": "切り抜きスタジオ", "transcribe": "編集", "cut2resolve": "cut2resolve(パックを作る部品)"}   # 知らせの文のツール名


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
            raise StepError("ツールにつながりませんでした。動いていないか、止まっているかもしれません。ホームの「詳しく(サーバーの管理)」で状態を見てから、"
                            "もう一度実行してください(済んだ段は飛ばします)")
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
            raise StepError(obj.get("message") or "ツールがうまく応答しませんでした。少し待って、もう一度実行してください(済んだ段は飛ばします)")
        return obj


def _yt_id_ok(v):
    """YouTube の配信 ID(11文字。スタジオの common.VID_RE と同じ)"""
    return isinstance(v, str) and len(v) == 11 and all(c.isascii() and (c.isalnum() or c in "-_") for c in v)


def _doc_id_ok(v):
    return isinstance(v, str) and 1 <= len(v) <= 40 and all(c.isalnum() or c in "-_" for c in v)


_num = _spec.num_ok   # 扱ってよい大きさの数か(src/pipeline/spec.py。ここの検査もこれを使う)


def live_auto_origin(media):
    """M8: 切り抜きが、リアルタイム切り抜きの自動の採用(.clip.json の source.live.origin が auto・archive)か。
    .clip.json の読み方と自動の出どころの一覧は src/manage/cases/cases.py の clip_live・AUTO_ORIGINS(案件の画面の札と同じ)。
    読めない・無い・人の採用(manual)・ライブでない → False"""
    live, _mark = cases.clip_live(media)
    return bool(live) and live.get("origin") in cases.AUTO_ORIGINS


_top_arg = _spec.top_arg   # 採用する数(src/pipeline/spec.py)


def _busy_reason(active, same, what=""):
    """順番待ちに入れられない理由(入れられれば None)。same(実行) = 同じ配信・文書・動画か。what = 理由の頭(「この配信は」など)"""
    if any(same(r) for r in active):
        return what + "すでに実行中・順番待ちです"
    if len(active) >= MAX_WAITING:
        return "順番待ちが多すぎます(%d本まで)" % MAX_WAITING
    return None


def _rec_key(rec):
    if rec.get("kind") == "file":
        return ("file", rec.get("sourcePath"))
    return ("doc", rec.get("docId")) if rec.get("kind") == "doc" else ("video", rec.get("videoId"))


class AutoRunner(delivery_mod.Delivery, run_mod.Runner):
    """入口のまとめて実行: 順番待ち・糸・受付・記録・起動し直しで戻す。段の中身は src/pipeline/run.py の Runner
    (ここでは hook を案件・ホームの設定で埋める)。友人へ届ける段と組の溜めは src/human/friend/delivery.py の Delivery(RS3-3)を継ぎ、
    そこが要る入口と案件の物(届ける本数の既定と範囲・案件に届けた印)は下の _deliver_batch_limits・_remember_delivered で渡す"""

    def __init__(self, client, repo_root, env=None, poll=1.0, sleep=None, find_pack=None, prefs=None, log_dir=None, log_max=LOG_MAX_BYTES,
                 clock=None, log=None):
        """log_dir: 終わった実行の記録を書くフォルダ(入口は作業データの logs。None = 記録しない = メモリだけ)。
        待ちと実行中の記録(M5)も log_dir に置く(None = 残せないので、起動し直しで戻さない)。clock はテスト用"""
        # パックの有無の見方は案件の画面とそろえる(cases.find_pack)。client・env・poll・sleep・log(入口のログ launcher.log に1行)・clock・closed は Runner が持つ
        super().__init__(client, env=env, poll=poll, sleep=sleep, log=log, clock=clock, find_pack=cases.find_pack if find_pack is None else find_pack)
        self.root = repo_root
        self.log_path = os.path.join(log_dir, runlog.RUNS_LOG) if log_dir else None
        self.active_path = os.path.join(log_dir, ACTIVE_FILE) if log_dir else None   # 待ち・実行中の記録(M5)
        self.active_error = ""     # 最後に待ちの記録を書けなかった理由(書けたら空に戻す)
        self._active_lock = threading.Lock()   # 待ちの記録のファイル(これを持ったまま self.cv を取る。逆の順では取らない)
        self._delivery_init(log_dir)   # ライブの切り抜きの組の溜めの置き場所とロック(src/human/friend/delivery.py の Delivery)
        self.log_max = log_max
        self.log_error = ""        # 最後に記録を書けなかった理由(書けたら空に戻す)
        self._log_lock = threading.Lock()   # 記録のファイルと past(self.cv とは別。self.cv を持ったまま _log を呼ばない)
        self._past = collections.OrderedDict()   # (種類, id) -> 最後の記録(書いた順)
        if self.log_path:
            for rec in runlog.read_runs_log(self.log_path, LOG_READ_BYTES):
                self._remember(rec)
        self.prefs = prefs   # ホームの設定(src/home/prefs.py)。カットの無い文書のカットの方法 autorun.cut
        self.lock = threading.Lock()
        self.cv = threading.Condition(self.lock)
        self.runs = []
        self.thread = None
        restored = self._restore_active()   # 前の起動で待ち・実行中だった実行(M5)
        if restored:
            with self.cv:
                self.runs.extend(restored)
                self._wake()
        if self.active_path and os.path.isfile(self.active_path):
            self._save_active()   # 戻さなかった(古い・壊れた)分を記録から外す

    # ------------------------------------------------------------ 起動し直しで戻す(M5)
    def _save_active(self):
        """待ち・実行中の実行を autorun-active.json に残す(self.cv の外で呼ぶ)。入口の終了のあとは書かない
        (止めた実行を「次の起動で続ける」形のまま残すため)。人が中止した実行は入れない。書けなくても実行は止めない"""
        if not self.active_path:
            return
        with self._active_lock:
            with self.cv:
                if self.closed:
                    return
                items = [r.saved() for r in self.runs if r.state in ("queued", "running") and not r.cancel]
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
        clip = (doc or {}).get("clip") or {}
        vid = run.video_id or ((clip.get("source") or {}).get("videoId") if isinstance(clip.get("source"), dict) else None)
        ch = (v or {}).get("channel") or (run.fresh or {}).get("channel")
        if vid and not ch:
            ch = self._studio_video(vid).get("channel")
        r = prefs_mod.guess_streamer(self.prefs, (doc or {}).get("id") or run.doc_id, vid, ch or None,
                                     from_channel=lambda c: (colors.from_channel(c, env=self.env) or {}).get("name"))
        run.streamer = r["name"] or ""
        run.streamer_from = r["source"] if r["name"] else None

    @staticmethod
    def _marks_arg(marks):
        """スタジオのマークの行から: このマークだけ進める(-> 重ならない id の組 / None = 配信の全部。検査は src/pipeline/spec.py の marks_arg)"""
        return _spec.marks_arg(marks)

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
        docs = {d["id"]: d for d in self._docs()}

        def make(tid, active):
            d = docs.get(tid) if _doc_id_ok(tid) else None
            if not d:
                return {"id": str(tid)[:40], "title": "", "reason": "文書が見つかりません"}
            why = _busy_reason(active, lambda r: r.doc_id == tid)
            if why:
                return {"id": tid, "title": d["title"], "reason": why}
            return Run(None, d["title"] or tid, DOC_MODE, None, doc_id=tid, overwrite=overwrite, streamer=who, on_fail=self._pref("onFail", "next"))
        return self._enqueue(dict.fromkeys(i for i in ids if isinstance(i, str)), make)

    def start_request(self, items, request_id=None, flow="check", deliver_dir=None, speakers=None, video_tracks=None, cut=None, weights=None, streamer=None,
                      deliver_batch=None):
        """友人からの依頼(配信の URL。src/human/friend/intake.py)。items = [{"id": 配信 ID, "top": 1〜30, "title", "channel", "ranges"?, "duration"?}]。
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
                       duration=it.get("duration") if _num(it.get("duration")) else None, deliver_batch=deliver_batch)
        return self._enqueue(items, make)

    def start_file(self, path, title="", streamer=None, request_id=None, flow="check", deliver_dir=None, speakers=None, video_tracks=None, cut=None,
                   engine=None, model=None, deliver_batch=None, pool=None):
        """友人が切り抜いた動画の依頼(src/human/friend/intake.py が作業データへコピーしたもの)を文字起こしだけ(mode file)。
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
                                 video_tracks=video_tracks, cut=cut, engine=engine, model=model, deliver_batch=deliver_batch, pool=pool))
        self._save_active()
        return out

    # ------------------------------------------------------------ 見積もり(気が利く画面へ 段4)
    def estimate(self, video_id=None, mode=None, marks=None, top=None, doc_ids=None, overwrite=False):
        """実行と同じ規則で、段ごとの本数と飛ばす理由を返す(何も書き込まない)。実行は実行したときの状態で決めるので、ずれることがある。
        -> {"steps": [{"key", "label", "count" (None = 前の段の結果しだい), "note"}], "total": 分かっている本数の合計, "nothing": bool, "reason"}"""
        docs = self._docs()
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
        """順番待ち・実行中の実行(呼ぶのは self.cv を持っている間)"""
        return [r for r in self.runs if r.state in ("queued", "running")]

    def _wake(self):
        """順番待ちを動かす(呼ぶのは self.cv を持っている間)"""
        self.cv.notify_all()
        if self.thread is None or not self.thread.is_alive():
            self.thread = threading.Thread(target=self._loop, name="autorun", daemon=True)
            self.thread.start()

    def restart_info(self, timeout=5):
        """画面の「起動し直す」(launch.py の restart_self。入口 0.41.0)が断るかを決める材料。待ち・実行中は起動し直したあとに戻る(M5)ので、それだけでは断らない。
        -> {"runs": 待ち・実行中の数, "redo": restart.can_restart の redo か None}。
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
        if tool == "transcribe":   # 「編集」のジョブ(枠の名前は題名の頭。src/ytt/jobs.py の work_one)
            items = [j for j in client.ok(tool, "GET", "/api/jobs").get("jobs") or [] if isinstance(j, dict) and j.get("state") in TX_ACTIVE]
            key, name = "id", lambda j: str(j.get("title") or "")
        elif tool == "studio":   # スタジオの解析のキュー(枠の名前は題名か配信の ID。src/pipeline/batch.py)
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
            keys = {r.key() for r in self.runs}
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
            recs = runlog.read_runs_log(self.log_path)
        recs.reverse()
        return {"runs": recs[offset:offset + limit], "total": len(recs), "more": offset + limit < len(recs), "offset": offset}

    def _remember(self, rec):
        """past の元に入れる(呼ぶのは self._log_lock を持っている間か、__init__ の中)。
        以前の記録に残っている消した「あとから解析」(mode post_analyze。RS4 で消した)は入れない(案件の行の「前回」は、依頼・まとめて実行の結果のまま。history には残る)"""
        if rec.get("mode") == "post_analyze":
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
            rec = dict(run.public(), v=runlog.LOG_VERSION)
            self._remember(rec)
            if not self.log_path:
                return
            try:
                fsio.append_line(self.log_path, json.dumps(rec, ensure_ascii=False) + "\n", self.log_max)   # 記録のファイルに 1 行ずつ書く形は 1 か所(ytt/fsio)
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
                    if r.state == "queued":
                        r.message = "ホームを終了したので、次の起動で続けます"
                self.cv.notify_all()

    def _trim(self):
        done = [r for r in self.runs if r.state not in ("queued", "running")]
        for r in done[:-MAX_KEEP] if len(done) > MAX_KEEP else []:
            self.runs.remove(r)

    def _env_off(self, name):
        """環境変数 name が off・0・false・no か(テストが渡す env と、本物の環境変数の両方を見る)"""
        return any(str(e.get(name) or "").strip().lower() in ("off", "0", "false", "no") for e in (self.env or {}, os.environ))

    def _loop(self):
        while True:
            with self.cv:
                while not self.closed and not any(r.state == "queued" for r in self.runs):
                    self.cv.wait()
                if self.closed:
                    return
                run = next(r for r in self.runs if r.state == "queued")
                run.state, run.message = "running", ""
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
                self.log("まとめて実行: 内部エラー: %s %s" % (e.__class__.__name__, str(e)[:200]))   # 例外の名前・原文はログへ(UI の見直し M9)
                run.state, run.error, run.message = "error", "ホームの想定外の不具合で止まりました。もう一度「実行」を押してください(済んだ段は飛ばします)。続くときは、詳しくの「ログ」を見てください", "止まりました"
            if self.closed and not run.cancel and run.state != "done":
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
            if run.deliver_dir and run.state == "error":   # ① 全自動: できていたパックを届けてから、友人の「受け取る」に失敗の理由を出す
                self._deliver_rest_quietly(run)
                self._deliver_failure(run)
            self._log(run)   # 記録のファイルへ(self.cv の外。B-6)
            with self.cv:
                self._trim()
                self.cv.notify_all()
            self._save_active()   # 終わった実行を待ちの記録から外す(M5)

    # ------------------------------------------------------------ 実行
    def _docs(self):
        """文字起こしの文書の一覧(txindex。更新時刻で覚えているので何度呼んでも読み直さない)"""
        return txindex.load(txindex.folder(self.root, self.env))

    def _studio_video(self, vid):
        """スタジオの一覧の 1 本(cases.read_studio。無ければ {})"""
        return cases.read_studio(cases.locations(self.root, self.env)["studio"]).get(vid) or {}

    def _execute(self, run):
        """1 回の実行(_loop の糸から)。段の中身は src/pipeline/run.py(hook = この AutoRunner)"""
        return run_mod.run(self.client, run, hooks=self)

    # hook(src/pipeline/run.py の Runner の既定を、案件・ホームの設定・届けることで埋める) ----------
    def _checkpoint(self, run):
        """段の始まりと済んだとき: 待ちの記録に残す(M5。起動し直したらこの段から)"""
        self._save_active()

    def _pick_doc(self, docs, video_id, mark_id, path):
        """切り抜きの文書(txindex.pick。案件の画面・スタジオのセリフと同じ規則)か None"""
        return txindex.pick(docs, video_id, mark_id, path)[0]

    def _live_auto_origin(self, media):
        return live_auto_origin(media)

    def _deliver_batch_limits(self):
        """Delivery が n 本ごとに組にして届ける数の既定と範囲(ホームの設定 intake.deliverBatch。既定と範囲は prefs.py)。-> (既定, 下限, 上限)"""
        lo, hi, _label = prefs_mod.INTAKE_RANGES["deliverBatch"]
        return prefs_mod.DEFAULTS["intake"]["deliverBatch"], lo, hi

    def _remember_delivered(self, clip_path, zip_name):
        """Delivery が届けたライブの自動の切り抜きを、案件の一覧に「届けた」と残す(二重に届けない。cases.remember_delivered)"""
        cases.remember_delivered(self.root, clip_path, zip_name, self.env)

    def _remember_doc_streamer(self, tid, name):
        """依頼で選んだ配信者を、この文書の配信者として覚える(パックのときの字幕の色。段5 の記憶と同じ)。-> 覚えたか"""
        if not self.prefs:
            return False
        try:
            self.prefs.remember("docs", tid, name)
            return True
        except (OSError, ValueError):
            return False

    def _friend_length(self):
        """友人の区間の長さの実績(src/eval/tools/eval_marks.py --json の結果のうち、いちばん新しいもの)-> 解析の設定に重ねる {"length", "preRatio"?} と出どころ。
        使わない(止めてある・ファイルが無い・古い・壊れている・見本が足りない)ときは None(ログに1行。依頼は今までどおりスタジオの設定で進む)"""
        if self._env_off(FRIEND_LENGTH_ENV):
            return None
        if self._pref("friendLength", True) is False:
            return None
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
