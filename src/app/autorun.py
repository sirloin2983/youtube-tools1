"""まとめて実行(統合計画の段階5。2026-09-26)。入口の「案件」の画面から、配信1本ぶんの作業を順に自動で流す。

形は3つ(ユーザー決定「選べるようにする」):
  full        解析から全部   … (未解析なら)解析 → 自動マークの上位を採用 → 書き出し → 文字起こし → Resolve パック
  adopted     採用後を全部   … 採用したマークの書き出し → 文字起こし → Resolve パック(切り抜きの良し悪しは人が決める)
  transcribe  文字起こしまで … 採用したマークの書き出し → 文字起こし(パックは校正してから人が作る)

作り:
- ① の経路(Run・段の表・段の中身・待つ骨組み)は RS1-7 で src/flow/run.py へ移した(役割で組み直す計画 notes:plan/done/role-restructure.md の 5-1)。
  順番待ちと糸・中止・状態と記録・起動し直しで戻す・見積もりは RS7-1 S5 で src/flow/runqueue.py の Queue へ移した(② が画面なしでも動くように。
  AutoRunner は Queue を継ぐ)。ここに残すのは、ToolClient・画面の設定から束を組む build_spec・起動し直すの確かめ restart_info と、
  Runner・Queue の hook(案件・ホームの設定・届けることを読む所)の中身。移した名前は同じ名前で読み直している。
  受付は ② の口 Queue.submit(封筒, 束の差分)の 1 本だけ(RV A1。HTTP は POST /api/flow/submit。以前の start* と /api/autorun/* は消した)。
  欄 → 封筒 + 束の差分の変換は flow/order.py(画面は UIKit.flow.order)の 1 か所。
  RS7-1 S4: 受付で束を組む(_accept = build_spec + 友人の区間の長さ・配信者・届ける名前の頭)。待ちの間に画面の設定を変えても、その実行の中身は変わらない。
  切り出しの精密・画質の上限・パックの fps は固定(決定 3-30 Q2)・用語集は編集の受付が自分の設定から読む。
  届けることと組の溜めは RS3-3 で Delivery(mixin)へ切り出した(AutoRunner が継ぐ。ds1 で ② src/flow/delivery.py へ)
- 各ツールの**公開している API を HTTP で呼ぶ**(入口と同じ 127.0.0.1。取り込んだツールは入口のポートの /studio/ など、子プロセスのツールはそのポート)。
  ツールの中の関数を直接呼ばないのは、画面から使うときと同じ検査・同じジョブ管理(重い処理の順番待ち ytt.jobs を含む)を通すため。
- どの段も「まだ無いものだけ」作る(書き出し済み・文字起こし済み・パック済みは飛ばす)。途中で止めても、もう一度押せば続きから進む。
  文字起こしの有無は manage.cases.txindex(案件の画面・スタジオのセリフと同じ規則)、パックの有無は cases.find_pack で見る。
- スタジオの ① 探す で選んだ配信(まだスタジオに無い YouTube の配信)は封筒の input.fresh つきで「解析から全部」に入れる。解析のキューに入れると
  スタジオに配信ができるので、それまでは受け取った題名で進める(git の履歴(679ff01 以前)の docs/archive/followup-2026-09-27.md の 5)。
- 1本ずつ順に処理する(キュー。src/flow/runqueue.py)。同じ配信を2つ同時には入れない。
- 入口の起動し直しで、順番待ち・実行中の分を戻す(線 D の M5。入口 0.40.0。src/flow/runqueue.py): 待ち・実行中の実行を入口の作業データの logs/autorun-active.json に残し
  (入れたとき・始めたとき・段が済むたび・終わったとき。一時ファイルから置き換える)、起動したときに読んで同じ id のまま「待ち」に戻す。
  済んだ段は飛ばし、途中だった段は頭からやり直す(どの段も「まだ無いものだけ」作るので、続きから進む)。入口の終了(「すべて終了」・黒い画面を閉じる・
  強制終了)で止まった実行は記録(autorun-runs.jsonl)に「中止」と書かない。起動し直してすぐはツールの準備を待つ(RESUME_WAIT 秒まで)。
  RESTORE_MAX_AGE(3 日)より前に入れた実行は戻さず、記録に「中止」と書く
- 終わった実行は、入口の作業データの logs/autorun-runs.jsonl に1行ずつ残す(段2 B-6。入口を起動し直しても、ホームで前回の結果と止まった理由を見られる)。
  書くのは終わったとき(完了・失敗・中止)だけ(入口の終了で止まった実行は、次の起動で続けるので書かない = M5)。
  1MB を超えたら .1 に回す(1世代。画面のエラーの記録 clientlog.py と同じ形)。書けなくても実行は止めない
- 自動で採用したマークは、人の判定ではないので学習の記録(スタジオの feedback)に入れない(まとめての採用は区間なしの adopt_marks で、学習の記録は書かない)。
- 解析の設定は既定値(解析の画面の設定はブラウザの中にしか無いため)。書き出しはスタジオの ③ の設定(音量のそろえ方。画質は上限なし・精密で固定 = RS7-1 S4)、
  文字起こしは「編集」(文字起こし)の設定(モデルなど)を使う。パックは、「編集」でカットを決めてあればそのとおり(cut2resolve の spec.keeps。
  作った記録も「編集」に残す = 作り直しの知らせ)、無ければ文字起こしの行だけを残す規則(preset transcript-rows)。どちらも Text+(字幕の元の行が無ければ Text+ なし)。
  リアルタイム切り抜きの自動の採用(.clip.json の source.live.origin が auto・archive)の切り抜きは、カットを指定していなければ区間の全体
  (LIVE_AUTO_CUT。線 D の M8。区間は検出が静かな所に合わせて絞ってある)。ホームの設定 live.auto.cut(none・silence)を選べばそれ(M2)。
- ① 全自動の Dropbox へ届ける段: パックができるたびに 1 本ずつ(1 本の zip + 480p の確認用の動画 <同じ名前>.preview.mp4 + .meta.json)Dropbox の 出力 へ置く
  (F3-6。notes:plan/f1-friend-requirements.md の C-6。5 本ずつの組・まとめ動画・届け方の設定はやめた)。作り方・名前は src/flow/deliver.py(確認用の動画は
  ① src/pipeline/pack/preview.py)、届ける段と置けなかった分の溜めの中身は src/flow/delivery.py(RS3-3 で human/friend へ出し、ds1 で ② へ移した)
- 友人へ自動で送る(D-SEND。notes:plan/done/d-send-requirements.md): 画面の「友人へ自動で送る」(既定 = 解析から全部のときだけオン・保存しない)。
  画面は、依頼の受付の Dropbox のフォルダが決まっていれば(GET /api/intake の outDir)封筒の deliver に出どころ auto を置き、
  チェックが入っていれば届け先(出力)も置く(段 deliver が付く)。受付(_accept)が名前の頭 deliver.tag(友人のアプリの依頼 id の形)を決める。
  チェックを外した実行も段 deliver を付けて(flow/run.py の steps_of = 出どころ auto の full)、
  そこで「チェックを外したので送りません」と切り抜きごとの送らなかった記録(② logs/not-sent.jsonl)を残す(品質のカードに出す = 2-8)。送るかの判定・溜め・送り直しは src/flow/delivery.py。
  まとめて実行の文書単位・full 以外・CLI は届けない
- 「あとから解析(測るため)」(友人の依頼が区間だけで終わった配信を、手が空いたときに解析する mode post_analyze)は RS4 で消した(入口 0.55.0)。
  代わりは区間だけの依頼の最後の段「解析(あとで)」(flow/run の analyze_later。届けたあとに解析を順番へ入れるだけで待たない。OPT-E2 = 決定 3-49 Q6。
  それまでの測る道具 eval_marks.py --analyze-missing は消した)。
  以前の一覧 logs/autorun-deferred.json は読まない(残っていても害はない)
"""
import http.client
import json
import os
import urllib.parse
import time

from manage.cases import txindex
from ytt import colors, datadir, settings as _settings
from flow import spec as _spec  # noqa: E402  (指定の束の検査・既定値。RS1-6 で RANGE_MAX・clean_ranges・top_arg などをここへ移した。下で同じ名前で読み直す)
from flow.spec import (CUTS, DEFAULT_TOP, LIVE_AUTO_CUT, MAX_MARKS, RANGE_MAX, RANGE_PAD, TX_ENGINES, TX_MODEL_RE,  # noqa: E402,F401
                           WEIGHT_KEYS, clean_ranges, clean_weights, pad_range)
from flow import machine as _machine  # noqa: E402  (この PC の設定 = 束に重ねる機械の都合。RS7-1 S1)
from flow import lengthhint as _lengthhint  # noqa: E402  (友人の区間の長さの目安をその場で数える。OPT-E2 7f-1)
from flow import run as run_mod  # noqa: E402  (① の経路 = Run・Runner・段の表。RS1-7 で移した。AutoRunner は Runner を継いで hook を埋める。下で同じ名前で読み直す)
from flow.run import (BUSY_WAIT, CANCEL_WAIT, DOC_LABEL, DOC_MODE, DONE_STEPS, JOB_STATE_JA, MODE_STEPS, MODES, NOTHING_MESSAGE,  # noqa: E402,F401
                          REQUEST_MODES, REQUEST_URL_MODES, RUN_ID_RE, RUN_STATE_LABELS, STEP_LABELS, STEP_STATE_LABELS,
                          Cancelled, Run, StepError, _has_captions, _job_why, clean_pool)
from flow import runqueue as queue_mod  # noqa: E402  (② の待ち行列と糸 = AutoRunner が継ぐ Queue。RS7-1 S5 で移した。下で同じ名前で読み直す)
from flow.runqueue import (ACTIVE_FILE, ACTIVE_VERSION, HISTORY_DEFAULT, HISTORY_MAX, LOG_MAX_BYTES, LOG_READ_BYTES, MAX_WAITING, PAST_MAX,  # noqa: E402,F401
                        RESTORE_MAX_AGE, busy_reason as _busy_reason, doc_id_ok as _doc_id_ok)
from manage.cases import cases  # noqa: E402  (src/manage/cases/cases.py: パックの有無・.clip.json の読み方・スタジオの一覧を案件の画面とそろえる。friend_feedback も先頭で読む = 循環しない)
from flow import delivery as delivery_mod  # noqa: E402  (友人へ届ける段と組の溜め = AutoRunner が継ぐ Delivery。RS3-3 で切り出し、ds1 で ② へ)
from flow import deliver as deliver_mod  # noqa: E402  (自動で送る分の名前の頭 = 友人のアプリの依頼 id の形。D-SEND)
from human.friend import intake as intake_mod  # noqa: E402  (受付のフォルダの読み方の 1 か所。D-SEND の届け先)
from human.friend import returns as returns_mod  # noqa: E402  (友人の PC で処理した依頼の配信 = 依頼済みの 3 つ目の引き方。D-SEND 2-9)
from app import prefs as prefs_mod  # noqa: E402  (ホームの設定の既定値と範囲。読み書きは渡された Prefs で)

# RANGE_MAX・RANGE_PAD・pad_range・CUTS・TX_ENGINES・TX_MODEL_RE・WEIGHT_KEYS は src/flow/spec.py へ、
# MODES・MODE_STEPS・STEP_LABELS・Run・StepError など ① の経路は src/flow/run.py へ移した(上で読み直している)
# 受付は ② の口 Queue.submit の 1 本だけ(RV A1。画面・友人の受付・CLI は欄を flow/order.py(画面は UIKit.flow.order)で封筒 + 束の差分にして submit)。
# 一度に入れられる数は玄関の側(① 探す の 10 本・友人の受付の intake.MAX_URLS)
MEMO_SEC = 3.0         # 1 回の受付の間だけ覚える秒(_memo。画面が 1 本ずつ submit しても設定ファイル・スタジオの一覧を 1 回だけ読む)
# 待ち行列と記録の数(MAX_KEEP・LOG_*・PAST_*・HISTORY_*・MAX_WAITING)は src/flow/runqueue.py(RS7-1 S5。上で読み直している)
# 友人の区間の長さを、依頼の自動の候補の長さに使う(2026-10-05 ユーザーの要望。仮の決定 = まとめ役)。
# 数えるのは ② flow/lengthhint(使うときにその場で。OPT-E2 7f-1。10-15 まで測る道具 eval_marks の夜の結果のファイルを読んでいた)
FRIEND_LENGTH_ENV = "YTT_FRIEND_LENGTH"   # off = 使わない(ホームの設定 autorun.friendLength が false でも使わない)
# 入口の起動し直しで戻す(線 D の M5。2026-10-07)。待ちの記録 ACTIVE_FILE・RESTORE_MAX_AGE は src/flow/runqueue.py(RS7-1 S5)
RESUME_WAIT = 120.0                  # 戻した実行は、使うツールが動くまでこれだけ待つ(入口の起動の直後はまだ準備中のことがある)
# 指定の束を画面の設定から組む(RS6 b-0。build_spec)。段は GET /api/settings を読まず、実行を始めるときに組んだ束を読む
STUDIO_UI_FILE = "settings-ui.json"   # スタジオの画面の設定(スタジオの作業データ。human/review/store の ui_file と同じ名前)
EDIT_SETTINGS_FILE = "settings.json"  # 編集の設定(編集の作業データ。ytt/workdata の SETTINGS と同じ名前)
LUFS = (-11, -14, -16, -18)           # 聞こえ方をそろえる目標(スタジオの書き出し・編集のパックの選択肢)
ROW_EDGE_NOTE = "「行から」の設定の形が正しくないので、既定の広げ方で作りました(「編集」の 2 カット の「行から」で直せます)"
STEP_TOOLS = {"analyze": ("studio",), "adopt": ("studio",), "export": ("studio",), "transcribe": ("transcribe",), "diarize": ("transcribe",),
              "pack": ("transcribe", "cut2resolve"), "deliver": ()}
# 画面の「起動し直す」(server.py の restart_self。入口 0.41.0)で、ツールの仕事を止めてよい段(起動し直したあとに頭からやり直す = M5)。
# 書き出し(export)は入れない: 書き出し中は今までどおり断る
REDO_STEPS = ("analyze", "transcribe", "diarize", "pack")
TX_ACTIVE = ("queued", "loading", "extracting", "running")   # 「編集」のジョブの動いている状態(src/ytt/jobs.py の ACTIVE_STATES)
QUEUE_ACTIVE = ("waiting", "running")                       # スタジオの解析のキューの動いている状態(src/flow/batch.py)


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


def _lufs(v):
    return v in LUFS and not isinstance(v, bool)


def _settings_want(studio, editor, autorun):
    """画面の設定 -> 束の節ごとの値(検査の前)と、直した所の知らせ。読み方は RS6 b-0 の前に段が GET /api/settings から本文を作っていた書き方のまま。
    切り出しの精密・画質の上限・パックの fps は読まない(固定 = 決定 3-30 Q2。RS7-1 S4)・用語集も読まない(編集の受付が自分の設定から読む)"""
    an = studio.get("analyze") if isinstance(studio.get("analyze"), dict) else {}
    rv = studio.get("review") if isinstance(studio.get("review"), dict) else {}
    tx = editor
    sub = tx.get("subtitle") if isinstance(tx.get("subtitle"), dict) else {}
    wrap = sub.get("wrapChars") if isinstance(sub.get("wrapChars"), dict) else {}
    cs = tx.get("cutSilence") if isinstance(tx.get("cutSilence"), dict) else {}
    vol, loud, pack_loud = rv.get("exportVolume"), rv.get("exportLoudness", -14), tx.get("packLoudness", 0)
    post_keys = _spec.TX_POST_KEYS + ("autoFill", "stripNames", "autoLlm", "autoContext", "diarSmooth")
    want = {
        "analyze": {k: an[k] for k in _spec.DEFAULTS["analyze"] if k in an},   # スタジオの画面で保存した解析の設定(段階7-1)
        "export": dict({"loudness": loud if _lufs(loud) else None},             # スタジオの ③ の書き出しの設定
                       **({"volume": int(vol)} if _num(vol) and 1 <= vol <= 200 else {})),
        "transcribe": dict({k: tx[k] for k in _spec.TX_TRANSCRIBE_KEYS if k in tx}, engine=_spec.implied_engine(tx.get("device"))),
        "post": dict({k: tx[k] for k in post_keys if k in tx}, **({"splitChars": sub["splitChars"]} if "splitChars" in sub else {})),
        "pack": {"size": tx.get("packSize"), "loudness": pack_loud if _lufs(pack_loud) else 0, "volume": tx.get("packVolume", 30),
                 "speakerColors": tx.get("speakerColors") is not False,
                 "wrapChars": {k: wrap[k] for k in ("vertical", "horizontal") if k in wrap},
                 "cutSilence": {k: cs[k] for k in ("noise", "min", "pad") if _num(cs.get(k))}, "cut": autorun.get("cut")},
    }
    notes = []
    if tx.get("rowEdge") is not None:
        if _spec.row_edge_ok(tx["rowEdge"]):
            want["pack"]["rowEdge"] = tx["rowEdge"]
        else:
            notes.append(ROW_EDGE_NOTE)
    return want, notes


def spec_from_settings(studio=None, editor=None, autorun=None):
    """画面の設定から指定の束を組む(RS6 b-0。5-4 = ① は設定ファイルを読まず、app が画面の値から束を組む)。
    studio = スタジオの画面の設定(settings-ui.json の analyze・review)・editor = 編集の設定(settings.json)・autorun = ホームの設定の autorun 節(cut)。
    -> (束 = flow/spec.py の merge・validate を通した物, 知らせ = 直した所の文のリスト(パックの段の文と結果の束に出す。Run.notes))。
    合わない値・無い値は束の既定(= 各ツールの既定と同じ値)。精密・画質の上限・fps は固定(RS7-1 S4 で画面だけの値 screen を消した)"""
    want, notes = _settings_want(studio if isinstance(studio, dict) else {}, editor if isinstance(editor, dict) else {},
                                 autorun if isinstance(autorun, dict) else {})
    given = {}
    for sec, items in want.items():
        for k, v in items.items():
            if _spec.key_ok(sec, k, v):
                given.setdefault(sec, {})[k] = v
    return _spec.validate(_spec.merge(given)), notes


_num = _spec.num_ok   # 扱ってよい大きさの数か(src/flow/spec.py。ここの検査もこれを使う)


def live_auto_origin(media):
    """M8: 切り抜きが、リアルタイム切り抜きの自動の採用(.clip.json の source.live.origin が auto・archive)か。
    .clip.json の読み方と自動の出どころの一覧は src/manage/cases/cases.py の clip_live・AUTO_ORIGINS(案件の画面の札と同じ)。
    読めない・無い・人の採用(manual)・ライブでない → False"""
    live, _mark = cases.clip_live(media)
    return bool(live) and live.get("origin") in cases.AUTO_ORIGINS


_top_arg = _spec.top_arg   # 採用する数(src/flow/spec.py)


class AutoRunner(delivery_mod.Delivery, queue_mod.Queue):
    """入口のまとめて実行: ② の待ち行列(受付は submit の 1 本 = RV A1)の hook(案件・ホームの設定・友人へ届ける)。
    待ち行列・糸・中止・状態と記録・起動し直しで戻す・見積もりは src/flow/runqueue.py の Queue(RS7-1 S5)、段の中身は src/flow/run.py の Runner。
    友人へ届ける段と組の溜めは src/flow/delivery.py の Delivery(RS3-3・ds1)を継ぎ、そこが要る入口と ③ の物
    (送り返しの依頼)は下の _returned_request で渡す。
    届けた・送らなかったは案件に写さない(② flow/deliveries の届けた記録・送らなかった記録を案件が読む。MARKS-3・ds1)"""

    def __init__(self, client, repo_root, env=None, poll=1.0, sleep=None, find_pack=None, prefs=None, log_dir=None, log_max=LOG_MAX_BYTES,
                 clock=None, log=None, tools=None):
        """log_dir: 終わった実行の記録を書くフォルダ(入口は作業データの logs。None = 記録しない = メモリだけ)。
        tools: 段が仕事を頼む先(入口は flow/tools.FlowTools = ① の動詞は同じプロセスの ② の器を直に。OPT2 後半 J7。None = HttpTools(client))。
        待ちと実行中の記録(M5)も log_dir に置く(None = 残せないので、起動し直しで戻さない)。clock はテスト用"""
        # hook が使う値は Queue の __init__ の前に置く(前の起動の待ちを戻すと、すぐに糸が段を進める)
        self.root = repo_root
        self.prefs = prefs   # ホームの設定(src/app/prefs.py)。カットの無い文書のカットの方法 autorun.cut
        self.memo_sec = MEMO_SEC   # 1 回の受付の間だけ覚える秒(_memo。テストは 0 にできる)
        self._memo_items = {}
        self._delivery_init(log_dir)   # ライブの切り抜きの組の溜めの置き場所とロック(src/flow/delivery.py の Delivery)
        # パックの有無の見方は案件の画面とそろえる(cases.find_pack)。client・env・poll・sleep・log(入口のログ launcher.log に1行)・clock・closed は Runner、
        # 待ち行列・記録・待ちの記録(log_dir の autorun-runs.jsonl・autorun-active.json)は Queue が持つ
        super().__init__(client, env=env, poll=poll, sleep=sleep, log=log, clock=clock, find_pack=cases.find_pack if find_pack is None else find_pack,
                         log_dir=log_dir, log_max=log_max, tools=tools)

    # ------------------------------------------------------------ 起動し直しで戻す(M5。ツールの準備を待つ hook)
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

    # ------------------------------------------------------------ 受付で決める配信者(段5)・ホームの設定
    def _guess_streamer(self, run, doc=None, v=None):
        """配信者の推定(段5): 覚えた名前(文書 → 配信 → チャンネル)→ チャンネル名から。-> prefs.guess_streamer の結果 {"name", "source"}"""
        clip = (doc or {}).get("clip") or {}
        vid = run.video_id or ((clip.get("source") or {}).get("videoId") if isinstance(clip.get("source"), dict) else None)
        ch = (v or {}).get("channel") or (run.fresh or {}).get("channel")
        if vid and not ch:
            ch = self._studio_video(vid).get("channel")
        return prefs_mod.guess_streamer(self.prefs, (doc or {}).get("id") or run.doc_id, vid, ch or None,
                                        from_channel=lambda c: (colors.from_channel(c, env=self.env) or {}).get("name"))

    def _auto_streamer(self, run, doc=None, v=None):
        """指定の無い実行の配信者を決める(1回だけ。段5)。受付(_accept_streamer)で決まらなかった実行だけ、実行中にここで。
        決まらなければ「色なし」。決めた名前は進み具合に出す"""
        if run.streamer is not None:
            return
        r = self._guess_streamer(run, doc, v)
        run.streamer = r["name"] or ""
        run.streamer_from = r["source"] if r["name"] else None

    def _pref(self, key, default=None):
        """ホームの設定 autorun の値(src/app/prefs.py。読めなければ default)"""
        try:
            v = (self.prefs.get(["autorun"])["autorun"] or {}).get(key) if self.prefs else None
        except (OSError, ValueError, KeyError):
            v = None
        return default if v is None else v

    def send_folder(self):
        """友人へ自動で送る届け先の元 = 依頼の受付の Dropbox のフォルダ(ホームの設定 intake.folder。読み方は受付と同じ 1 か所)。決まっていなければ空の文字"""
        return intake_mod.configured_folder(self.prefs, prefs_mod.DEFAULTS["intake"]) if self.prefs else ""

    def _memo(self, key, fn):
        """1 回の受付(画面が配信・文書を 1 本ずつ submit する)の間だけ覚える(MEMO_SEC 秒。束の土台・スタジオの一覧・友人の区間の長さ)"""
        now = time.time()
        hit = self._memo_items.get(key)
        if hit is not None and 0 <= now - hit[0] < self.memo_sec:
            return hit[1]
        v = fn()
        self._memo_items[key] = (now, v)
        return v

    def _base(self):
        """受付の束の土台(Queue の hook。build_spec を 1 回の受付の間だけ覚える)"""
        return self._memo("base", self.build_spec)

    def _check_input(self, run):
        """submit の入力の検査(Queue の hook): 動画ファイル(Queue)+ 文書の実行は文書があるか(無ければ ValueError「文書が見つかりません」)。
        題が封筒に無ければ(文書の id のまま)文書の題にする"""
        super()._check_input(run)
        if run.kind() == "docs":
            d = next((x for x in self._docs() if x.get("id") == run.doc_id), None)   # txindex は更新時刻で覚えている(何度読んでもよい)
            if not d:
                raise ValueError("文書が見つかりません")
            if (not run.title or run.title == run.doc_id) and d.get("title"):
                run.title = str(d["title"])[:120]

    # ------------------------------------------------------------ 起動し直す(画面の「起動し直す」の確かめ。ToolClient を使うので入口に残す)
    def restart_info(self, timeout=5):
        """画面の「起動し直す」(server.py の restart_self。入口 0.41.0)が断るかを決める材料。待ち・実行中は起動し直したあとに戻る(M5)ので、それだけでは断らない。
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
        elif tool == "studio":   # スタジオの解析のキュー(枠の名前は題名か配信の ID。src/flow/batch.py)
            items = [i for i in client.ok(tool, "GET", "/api/queue").get("items") or [] if isinstance(i, dict) and i.get("status") in QUEUE_ACTIVE]
            key, name = "qid", lambda i: str(i.get("title") or i.get("videoId") or "")
        else:
            return None
        return {"tool": tool, "labels": [name(i) for i in items if i.get(key) in ids], "others": [name(i) for i in items if i.get(key) not in ids]}

    def _env_off(self, name):
        """環境変数 name が off・0・false・no か(テストが渡す env と、本物の環境変数の両方を見る)"""
        return any(str(e.get(name) or "").strip().lower() in ("off", "0", "false", "no") for e in (self.env or {}, os.environ))

    # ------------------------------------------------------------ 実行
    def _docs(self):
        """文字起こしの文書の一覧(txindex。更新時刻で覚えているので何度呼んでも読み直さない)"""
        return txindex.load(txindex.folder(self.root, self.env))

    def _studio_list(self):
        """スタジオの一覧 {配信の ID: 配信}(cases.read_studio。読めなければ {})"""
        return cases.read_studio(cases.locations(self.root, self.env)["studio"])

    def _studio_video(self, vid):
        """スタジオの一覧の 1 本(cases.read_studio。無ければ {})"""
        return self._studio_list().get(vid) or {}

    def _tool_settings(self):
        """スタジオの画面の設定(settings-ui.json)と編集の設定(settings.json)-> (スタジオ, 編集)。置き場所は各ツールの作業データ
        (ytt.datadir。案件の画面と同じ規則)。無い・読めない・壊れていれば {}(束の既定 = 各ツールの既定)"""
        out = []
        for tool, name in (("studio", STUDIO_UI_FILE), ("transcribe", EDIT_SETTINGS_FILE)):
            try:
                path = os.path.join(datadir.resolve(tool, self.root, self.env), name)
                out.append(_settings.SettingsFile(path, max_bytes=_settings.SETTINGS_MAX).read())
            except (OSError, ValueError):
                out.append({})
        return out[0], out[1]

    def build_spec(self):
        """画面の設定(スタジオ・編集の設定ファイルとホームの設定 autorun)から指定の束を組む -> (束, 知らせ)。
        Queue の hook: 受付(_accept)で読む = 受けたときの束のまま流す(待ちの間・段の途中で設定を変えても、その実行の中身は変わらない。RS7-1 S4)。
        この PC の設定(flow/machine.py の machine.json・環境変数)で決めたエンジン・機器・LLM のモデルを重ねる(無ければ束は今と同じ。RS7-1 S1)"""
        studio, editor = self._tool_settings()
        try:
            ar = (self.prefs.get(["autorun"])["autorun"] or {}) if self.prefs else {}
        except (OSError, ValueError, KeyError):
            ar = {}
        bundle, notes = spec_from_settings(studio, editor, ar)
        if ar.get("onFail") in _spec.ON_FAIL:   # 1 本が失敗したとき(ホームの設定 autorun.onFail。RV A1 で受付の欄から束の run.onFail へ)
            bundle = dict(bundle, run=dict(bundle["run"], onFail=ar["onFail"]))
        return _machine.overlay(bundle, env=self.env), notes

    # ------------------------------------------------------------ 受付で決める(RS7-1 S4。Queue の hook)
    def _accept(self, run, convert=False):
        """受けたときに決める物を Run に置く(Queue の hook。submit が必ず通す = RV A1。待ちの間に設定を変えても、その実行の中身は変わらない):
        - 束が無ければ組む(_base = build_spec)と知らせ run.notes・配信者が無ければ束の hints.people の先頭(Queue._accept)
        - 友人の区間の長さ(依頼の URL で解析の段があるとき。_friend_length を 1 回の受付の間だけ覚える)。束の analyze.length・preRatio に入れ、
          run.friend_plan に出どころと重ねる前の値(解析の段が使った印 run.friend_length と文を出す)
        - 配信者(まだ無いとき。覚えた名前 → チャンネル名から。決まらなければ実行中に _auto_streamer = 今までどおり)= 束の hints.streamer
        - 届ける名前の頭(まとめて実行の自動で送る形 = mode full・出どころ auto で無ければ。友人のアプリの依頼 id の形。D-SEND)= 封筒の deliver.tag
        convert = 束の無い待ちの記録を戻すとき: 束が無ければ組む・まだ決めていない物だけ決める(始めていた実行の配信者は実行中に決めるまま)"""
        new = run.spec is None
        super()._accept(run, convert)
        pending = any(s["key"] == "analyze" and s["state"] not in DONE_STEPS for s in run.steps)
        if run.friend_plan is None and run.mode in REQUEST_URL_MODES and pending:
            fl = self._memo("friend", self._friend_length)
            if fl:
                keys = [k for k in ("length", "preRatio") if k in fl]
                b = run.spec
                run.friend_plan = dict(fl, base={k: b["analyze"][k] for k in keys})
                run.spec = dict(b, analyze=dict(b["analyze"], **{k: fl[k] for k in keys}))
        if run.streamer is None and (new or not convert):
            self._accept_streamer(run, self._memo("studio", self._studio_list))
        if run.mode == "full" and run.deliver_origin == "auto" and not run.deliver_tag:
            run.deliver_tag = deliver_mod.request_id(self.clock())

    def _accept_streamer(self, run, studio=None):
        """受付で配信者を決める(_auto_streamer と同じ規則 = prefs.guess_streamer)。実行中と同じ答えになるときだけ決める:
        文書単位 = その文書・動画ファイル = 前からある文書(作り直す force のときは新しい文書になるので見ない)・配信 = この実行で扱う書き出し済みの
        切り抜きの文書(あれば)と配信・チャンネル。決まらなければ(覚えた名前もチャンネル名からも無い)None のまま = 実行中に決める"""
        vid, doc, v = run.video_id, None, {}
        if run.doc_id:
            doc = next((d for d in self._docs() if d["id"] == run.doc_id), None)
        elif run.source_path:
            if run.force:
                return
            doc = self._pick_doc(self._docs(), None, None, run.source_path)
            if not doc:
                return   # 新しい文書の .clip.json から配信が分かる(実行中に決める)
        elif vid:
            v = (studio.get(vid) if studio is not None else self._studio_video(vid)) or {}
            marks = [m for m in v.get("marks") or [] if isinstance(m, dict) and (not run.marks or m.get("id") in run.marks)
                     and m.get("status") == "exported" and isinstance(m.get("path"), str) and m["path"]]
            if marks:
                docs = self._docs()
                doc = next((d for d in (self._pick_doc(docs, vid, m.get("id"), m["path"]) for m in marks) if d), None)
        r = self._guess_streamer(run, doc, v)
        if r["name"] is not None:
            run.streamer, run.streamer_from = r["name"], (r["source"] if r["name"] else None)

    # hook(src/flow/run.py の Runner・src/flow/runqueue.py の Queue の既定を、案件・ホームの設定・届けることで埋める) ----------
    def _on_error(self, run):
        """失敗で終わった実行(Queue の hook): ① 全自動なら、できていたパックを届けてから、友人の「受け取る」に失敗の理由を出す"""
        if run.deliver_dir:
            self._deliver_rest_quietly(run)
            self._deliver_failure(run)

    def _pick_doc(self, docs, video_id, mark_id, path):
        """切り抜きの文書(txindex.pick。案件の画面・スタジオのセリフと同じ規則)か None"""
        return txindex.pick(docs, video_id, mark_id, path)[0]

    def _live_auto_origin(self, media):
        return live_auto_origin(media)

    def _returned_request(self, video_id):
        """Delivery の依頼済みの 3 つ目の引き方: 友人の PC で処理した依頼の配信か(③ 送り返し。D-SEND 2-9)。読めなければ OSError"""
        if not self.log_path:
            return False
        return video_id in returns_mod.requested_videos(os.path.dirname(os.path.dirname(self.log_path)))

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
        """友人の区間の長さの目安(② flow/lengthhint がその場で数える = 入口の実行記録の友人が指定した区間)-> 解析の設定に重ねる
        {"length", "preRatio"?} と出どころ・数。使わない(止めてある・見本が足りない・数えられない)ときは None(依頼は今までどおりスタジオの設定で進む)。
        最初と、使う ⇄ 使わない・長さが変わったときにログに 1 行(切り替わりを見えるように。7f-2)"""
        if self._env_off(FRIEND_LENGTH_ENV):
            return None
        if self._pref("friendLength", True) is False:
            return None
        loc = cases.locations(self.root, self.env)
        try:
            h = _lengthhint.compute(os.path.dirname(loc["studio"]), os.path.dirname(os.path.dirname(loc["runs"])))
        except Exception as e:   # 数えられなくても依頼は止めない
            self.log("友人の区間の長さ: 数えられないので使いません(%s)" % e.__class__.__name__)
            return None
        prev = getattr(self, "_friend_hint", self)   # self = まだ一度も数えていない(最初は必ずログに出す)
        changed, used = _lengthhint.change(None if prev is self else prev, h)
        if changed or prev is self:
            self._friend_hint = used
            self.log("友人の区間の長さ: " + _lengthhint.describe(h))
        return dict(used, file="flow/lengthhint", samples=h["samples"], videos=h["videos"]) if used else None

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
