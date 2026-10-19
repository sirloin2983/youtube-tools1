# -*- coding: utf-8 -*-
"""入口(ランチャー)— 3つのツールのサーバーをまとめて起動・終了し、入口の画面を出す。

    python src/app/server.py [--no-open] [--port 8700] [--only studio,transcribe,cut2resolve]
    python src/app/server.py --headless [--port 8700]   画面なし(ほかのアプリが子プロセスとして起こす ②。RS7-2 G5a。下の「画面なし」)

統合計画の段階1(notes:docs/design/integration-plan.md)。ツールのコードは変えず、各ツールのフォルダで
`serve.py <既定のポート> --no-open` を子プロセスとして起動する。ツール間の受け渡し・ポートの共有は従来どおり(notes:docs/spec/pipeline.md)。

  GET  /                                  入口の画面(portal.html)
  GET  /api/ping                          {"app": "ytt-launcher", "version"}
  GET  /api/cases                         案件(配信1本)ごとの切り抜き・文字起こし・パック(src/manage/cases/cases.py)
  POST /api/cases/auto                   {op: deliver|discard, id, markId} 自動でできた切り抜き(線 D の M9・M12)を 採用 = 友人へ届ける・
                                          要らない = ごみ箱フォルダへ(src/manage/cases/cases.py の auto_review。deliver の応答の job は api/ytt/deliver の status で聞き直す)。  GET  /api/flow/runs                     まとめて実行の状態(src/flow/runqueue.py の snapshot)。runs = この起動の実行(public。mode・modeLabel・docs…)・
                                          past = 配信・文書ごとの前回の結果(記録のファイルから)・modes
  POST /api/flow/submit                   {envelope, spec?} ② の口 = 受付はこれ 1 本(RS7-1 S4・RV A1): 封筒(src/flow/envelope.py)+ 束の差分(src/flow/spec.py)を
                                          待ち行列に積む → {run}。欄から封筒と差分を作るのは src/flow/order.py(画面は UIKit.flow.order)。束の土台は画面の設定(build_spec)。
                                          形が違う・同じ入力が待ち・実行中は 400 と理由。動画ファイルの封筒は実在するパス・動画か音声の拡張子だけ。届け先が無ければ届けない。
                                          F1 F0-1: 束の版(封筒.specVersion)が違えば 400 error spec_version・束に知らない節・項目・合わない値があれば 400 error bad_spec
                                          (呼ぶアプリは「更新してください」と出せる)。ほかの理由は bad_request
  GET  /api/flow/status                   ② の待ち・実行中の数と進み具合 {queued, running, done, idle, closed, live, runs}(src/flow/runqueue.py の status。CLI・起こしたアプリが聞く)。
                                          live = {recording, detecting, exporting}(ライブの録画中・検出中・書き出しの途中の数。PortalServer.live_activity)。
                                          idle は待ち・実行中が 0 かつ live の数がどれも 0 のときだけ真(起こしたアプリの「終わったら閉じる」。RS7-2 G5a)。
                                          RS8: + rev(変わるたびに増える)・jobs(掲示板 src/flow/board.py の Job。待ち・実行中 + 終わった直近 30 件・入れた順)・
                                          cases({案件の根: {active, lastState, lastFinished}})。?case=<案件の根> で jobs だけ絞る(ほかの項目は絞らない)。notes:docs/spec/pipeline.md 2.9
                                          F1 F0-1: + blocked(null か {reason: "disk", freeGB, minGB} = 空き容量が下限を切って次の実行を始めていない)・
                                          machine({engine, device, llmModel, gpu: {name, vramGB, ...} か null}。src/flow/runqueue.py の machine_status)
  GET  /api/flow/machine                  この PC の設定(src/flow/machine.py の load。{engine, device, llmModel, caseRoot, diskMinGB, learningDir, sources})
  PUT  /api/flow/machine                  {device?, llmModel?, caseRoot?, diskMinGB?, learningDir?}(null = 既定へ戻す)を machine.json に書く(合言葉が要る)→
                                          {machine: 書いたあとの load, file: ファイルの中身}。知らない項目・合わない値は 400 bad_request と理由(F1 F0-1)。
                                          caseRoot はスタジオの書き出し先にもそろえる(処理の実行中は 409 busy)
  POST /api/flow/cancel                   {id} 掲示板の id(「頭:id」)のジョブを止める → {job}。無い id は 404・止められない物は 409 cannot_cancel・形が違えば 400
  POST /api/flow/retry                    {id} 失敗・中止したジョブを同じ指定で入れ直す → {job}(新しい id)。無い id は 404・できない物は 409 cannot_retry
  GET  /api/flow/outbox                   送り返す zip の一覧 {files: [{id, requestId, runId, size, at}]}(src/flow/outbox.py の list_outbox。画面なしで
                                          依頼(requestId のある実行)が終わるたびに <app>/outbox に組む。F1 F6a)
  POST /api/flow/outbox/done              {id} 上げ終えた zip を outbox/済み へ → {ok: true}。無い・名前の形が違う id は 404(F1 F6a)
  GET  /api/flow/history?case=&limit=&offset=  終わった実行の記録(<作業データ>/app/logs/autorun-runs.jsonl と .1。新しい順。limit は既定 50・最大 200。case = 結果の束の案件で絞る)
  POST /api/flow/estimate                 {envelope, spec?}(submit と同じ本文)実行と同じ規則の見積もり → {steps, total, nothing, reason, notes}(段ごとの本数と飛ばす理由。書き込まない)
  GET  /api/intake                        友人からの依頼の受付の状態・設定・最近の依頼(src/human/friend/intake.py。notes:docs/spec/friend.md)
  POST /api/intake/scan                   {} 今すぐフォルダを見る(裏で。応答は今の状態)
  GET  /api/backup                        作業データのバックアップの状態・設定(src/manage/keep/backup.py。notes:docs/spec/data.md の「バックアップ」)
  POST /api/backup/run                    {} 今すぐ写す(裏で。応答は今の状態)
  GET  /api/accuracy                      精度の自動測定の状態・領域ごとの直近と前回・入口の条件 goals(今 / 目標 / あと)(src/eval/drill/accuracy.py)
  POST /api/accuracy/run                  {} 今すぐ測る(裏で。手が空くまで待つ。オフなら 409。応答は今の状態)
  GET  /api/check/next?c=&kind=&n=&skip=  「確かめる」(V1)の待ち行列(src/app/check/deck.py。読むだけ)。c = 案件の id・kind = value|read|voice|time・
                                          n = 0〜50(既定 10。0 = 数だけ)・skip = 画面が持っているカードの id(カンマ区切り。外す)
                                          → {rev, cards, counts: {today, perKind, failed}, goal, goals, total, held, failed, errors}
  POST /api/check/answer                  {card, answer, ms?, skip?} カードに答える(カードはサーバーが引き直す。反映は src/human/check/apply.py に登録した部品)
                                          → {ok, answer, card, applied, held, flushed, next} / {undo: 答えの id} Z で戻す → {ok, answer, card, reverted}
  POST /api/check/skip                    {card} 今日の間だけ後ろへ(保留を先に確定)・POST /api/check/flush {} 保留(1 枚遅れの [送る])を確定(画面を離れたとき)
  GET  /api/status                        {"app", "version", "tools": [...], "dataDir"}(ツールごとの状態・作業データの置き場所)
  GET  /api/health[?refresh=1]            「調子」(段9 9-1。src/manage/ops/health.py): 版の期待と実際・認識ワーカー・ffmpeg/ffprobe/yt-dlp・空き容量・作業データの大きさ・エラーの件数
  GET  /api/cleanup                       片付けの候補(段9 9-2。src/manage/keep/cleanup.py)。POST /api/cleanup {ids} で候補に出した物だけをごみ箱フォルダへ移す(TRASH_DAYS 日で起動時に消える)
  GET  /api/log?tool=<ID>&lines=N         ツールの出力(<作業データ>/app/logs/<ID>.log)の末尾
  POST /api/tools/<ID>/start|stop|restart {} → {"tool": {...}}
  POST /api/shutdown                      {} → この入口から起動したツールを止めて、入口も終わる。録画中でなければ録画の部品も止める
                                          (録画中なら残して、応答に recorderKept・notice)
  POST /api/window                        {mode: browser|app} 画面を窓(Edge のアプリモード)で開くか(段階7-3。src/ytt/appwindow.py)
  POST api/ytt/client-log|open-window|open-external|focus-portal|streamer-colors   画面の共通の API(focus-portal: 入口の窓を前に出す・
                                          streamer-colors: 配信者の名前 → メンバーカラーの候補)。入口の画面(/api/ytt/…)と、取り込んだツールの画面
                                          (/studio/api/ytt/… など。src/app/mount.py が入口へ回す)のどちらからも同じ(段階7。PortalServer.ytt_request)
  POST api/ytt/restart-self               {} → 入口ごと起動し直す(段9 9-3。src/manage/ops/restart.py)。重い処理・人が始めた処理・書き出しの最中は 409 と理由の文。
                                          まとめて実行の待ち・実行中は断らずに、応答に notice(何件が起動し直したあとに続くか)
  GET  /live/…・POST /live/…              リアルタイム切り抜き(線 D。src/app/live.py)。**設定 live.enabled がオンのときだけ**(オフなら 404):
                                          録画を始める /live/api/begin・録画元(src/pipeline/ingest/recorder.py)への中継 /live/r/<録画元>/<残り>・マークと書き出し・
                                          サーバー側の「マーク + 書き出し」/live/api/adopt(線 D の M1)。
                                          画面はスタジオの中(P3。/live/ はスタジオへ 302)。線 D の M4〜M7: 「調子」の live.disk(空き容量)・
                                          archiveInfo.afterStream(配信後の全自動 = 設定 live.autoAfterStream)。まとめて実行の待ち・実行中は起動し直しで戻る
  POST api/ytt/live                       {op: "status"} → 録画中の録画(全ツールのヘッダーの札。オフなら {enabled: false})/ {op: "stop", recorder, recording}
  POST api/ytt/deliver                    {op: "start", dir, title} → {"job"} / {op: "status", job} → {"job"}。パックを友人へ届ける
                                          (Dropbox の見張るフォルダの 出力 に zip で置く。src/flow/deliver.py)

設計の要点
- 子プロセスの出力は <作業データ>/app/logs/<ID>.log に書く(1つの黒い画面に3つのツールの出力が混ざらないように)
- ツールが準備できたかは、ツールが書く .runtime/<ID>.json のポートに /api/ping を問い合わせて確かめる。
  pid では確かめない(Windows の os.kill(pid, 0) はプロセスを終了させてしまう。notes:docs/spec/pipeline.md の 4)
- すでに別の黒い画面で動いているツールは「別の画面で起動済み」として扱い、起動も停止もしない(二重起動で data.json を取り合わないため)
- 止めるときは、Windows は Ctrl+Break(子を別のプロセスグループで起動しておく)、Mac/Linux は SIGTERM を送る。
  どちらも各ツールが .runtime を消してから終わる合図。一定時間で終わらなければ強制終了する

画面なし(--headless。RS7-2 G5a・notes:plan/done/f1-friend-pc.md の 2〜4)
- ほかのアプリが ② を子プロセスとして起こす形。ブラウザ・窓を開かない。取り込み(3 ツール)と ②(まとめて実行 = flow の Queue・ライブ)は載せる。
  ③④⑤ の常駐(依頼の受付の見張り・バックアップ・精度の自動測定・分析と日報・ごみ箱フォルダの片付け)は起こさない(部品は作るので API は今までどおり答える)。
  「起動し直す」(api/ytt/restart-self)は 409 で断る(新しい入口は起こしたアプリの子にならないため。起こし直すのは起こしたアプリ)
- 標準出力・標準エラーは UTF-8。標準出力は 1 行の JSON だけ: 待ち受けて ② を準備できたら {"event": "ready", "port", "token"(書き込み系の X-YTT-Token), "pid"}(HEADLESS_READY)。
  黒い画面への記録・取り込んだツールの print は標準エラーへ
- 入口がすでに動いている(そのポート範囲の入口・同じ作業データの .flow.lock)ときは、読める文を標準エラーへ出して EXIT_RUNNING で終わる(ブラウザは開かない)
- 親の見張り(--parent-pid <pid>。F1 F0-1・notes:docs/design/f1-build.md (f1j)): 起こしたアプリのプロセスが終わるか、標準入力が閉じられたら(EOF)、
  「すべて終了」と同じ後始末で終わる(終了コード 0。実行中・待ちの実行は autorun-active.json に残り、次の起動で続く)。
  標準入力を見るのは --parent-pid を付けたときだけ(付けないときは今までどおり)
"""
import argparse
import http.client
import json
import os
import queue
import re
import secrets
import signal
import socket
import subprocess
import sys
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # src(このファイルは src/app/server.py)
CODE_DIR = os.path.join(ROOT, "app")   # 入口の部品(mount・autorun・prefs・live・appwindow)の置き場所(画面は ui/home・ui/settings・ui/cases・ui/check)。layout.TOOL_DIRS["app"] と同じフォルダ(コードだけ。inplace の作業データは <リポジトリ直下>/.data/app)
HOME_UI_DIR = os.path.join(CODE_DIR, "ui", "home")   # ホームの画面(portal.html・portal.js・portal.css・portal-edit.js)
if ROOT not in sys.path:   # 役割の層・共通部品 ytt(src)
    sys.path.append(ROOT)
if CODE_DIR not in sys.path:   # 入口の部品を裸の名前で読む(import mount など)
    sys.path.insert(0, CODE_DIR)
from manage.cases import txindex  # noqa: E402
from flow import placement  # noqa: E402  (② の .flow.lock。RS6 b-B0)
from flow import tools as flowtools_mod  # noqa: E402  (まとめて実行の段が仕事を頼む先 FlowTools = ① の動詞は取り込んだツールの ② の器を直に。OPT2 後半 J7)
from flow import board as board_mod  # noqa: E402  (② のジョブの掲示板 = GET /api/flow/status の jobs・cases・rev と cancel・retry。RS8 の ② の口)
from flow import live_export  # noqa: E402  (書き出しの途中の数 = ② の status の live 欄。RS7-2 G5a)
from flow import livesession  # noqa: E402  (ライブ係。録画の部品を残したときの文 KEPT_NOTE。RS7-2 G2b)
from flow import machine as machine_mod  # noqa: E402  (この PC の設定。画面なしの空き容量の下限 diskMinGB。RS7-2 G2b・GET/PUT /api/flow/machine。F1 F0-1)
from flow import runqueue as queue_mod  # noqa: E402  (② の待ち行列。submit の版違い・束の形の例外 = 400 spec_version・bad_spec。F1 F0-1)
from flow import learning as learning_mod  # noqa: E402  (学習データの読み手。machine の learningDir があるとき入口の文字起こしもそこから読む。F1 F6a)
from flow import outbox as outbox_mod  # noqa: E402  (送り返しの zip。画面なしで依頼の実行が終わるたびに組む・GET /api/flow/outbox。F1 F6a)
from flow import prio as prio_mod  # noqa: E402  (処理の優先度の表。後回しの仕事を始めてよいかを重い処理の枠へ。PRIO)
from manage.keep import learnpack as learnpack_mod  # noqa: E402  (学習の束を <依頼の受付のフォルダ>/学習 に置く。起動時と 1 日ごと。F1 F6a)
from ytt import colors as colors_mod, datadir, docloc, fsio, httpsec, jobs, layout, runtime, tools, version as _version  # noqa: E402
from ytt import errors as _yerrors  # noqa: E402  (確かめるの部品が上げる ApiError を状態の番号で返す)
from ytt import studio_env  # noqa: E402  (PUT /api/flow/machine の caseRoot をスタジオの書き出し先にもそろえる)
from app import mount as mount_mod  # noqa: E402  (src/app/mount.py: 統合サーバーへのツールの取り込み)
from app import autorun as autorun_mod
from human.friend import intake as intake_mod  # noqa: E402  (src/human/friend/intake.py: 友人からの依頼の受付)
from manage.keep import backup as backup_mod  # noqa: E402  (src/manage/keep/backup.py: 作業データのバックアップ)
from eval.drill import accuracy as accuracy_mod  # noqa: E402  (src/eval/drill/accuracy.py: 精度の自動測定 = src/eval/tools/eval_*.py を手が空いた夜に子プロセスで)
from app.check import deck as check_deck, lineup as check_lineup  # noqa: E402  (src/app/check: 「確かめる」の待ち行列。V1)
from human.check import apply as check_apply  # noqa: E402  (src/human/check/apply.py: 「確かめる」の答えの記録と反映。V1)
from human.check import read as check_read  # noqa: E402,F401  (読みのカードの反映を apply に登録する。V2b)
from human.check import timerow as _check_timerow  # noqa: E402,F401  (時刻のカードの反映を apply に登録する。V2d)
from human.check import value as check_value  # noqa: E402, F401  (src/human/check/value.py: 価値のカードの反映を apply に登録する。V2a)
from human.check import speech as _check_speech  # noqa: E402,F401  (「この行は声ですか?」の反映を apply に登録する。C-EVAL)
from human.check import cutcard as _check_cutcard  # noqa: E402,F401  (自動カットのカードの答えを apply に登録する。CUT-CARD)
from human.check import section as _check_section  # noqa: E402,F401  (評価のレーンの区間カードの反映を apply に登録する。C-EVAL)
from human.check import voice as _check_voice  # noqa: E402,F401  (誰の声のカードの反映と声の覚え直し。読み込みで apply に登録する。V2c)
from flow import deliver as deliver_mod  # noqa: E402 (src/flow/deliver.py: パックを友人へ届ける = Dropbox の 出力 に zip で置く。ds1 で ② へ)
from manage.cases import cases as cases_mod  # noqa: E402  (src/manage/cases/cases.py: 案件(配信1本)ごとの紐づけ)
from manage.cases import outdirs as outdirs_mod  # noqa: E402  (src/manage/cases/outdirs.py: 書き出し先を変えたあとの案件の繋ぎ直し・「調子」の置き場所の行。RS8 B3-8 の残り)
from human.friend import friend_feedback as friend_feedback_mod  # noqa: E402  (src/human/friend/friend_feedback.py: 友人の「要らない」= 切り抜きとパックを ごみ箱 へ・記録を残す。マークは変えない)
from ytt import appwindow as appwindow_mod  # noqa: E402  (src/ytt/appwindow.py: 窓(Edge のアプリモード)で開く。段階7-3)
from manage.ops import clientlog as clientlog_mod  # noqa: E402  (src/manage/ops/clientlog.py: 画面のエラーの記録。段階7-0)
from manage.ops import health as health_mod  # noqa: E402  (src/manage/ops/health.py: 「調子」。段9 9-1)
from manage.keep import cleanup as cleanup_mod  # noqa: E402  (src/manage/keep/cleanup.py: 片付け。段9 9-2)
from manage.ops import restart as restart_mod  # noqa: E402  (src/manage/ops/restart.py: 入口ごと起動し直す。段9 9-3)
from app import prefs as prefs_mod  # noqa: E402  (src/app/prefs.py: ホームの設定。まとめて実行の既定・配信者の記憶・共通の再生キー)
from app import live as live_mod  # noqa: E402  (src/app/live.py: リアルタイム切り抜き(線 D)。既定はオフ)
try:   # src/manage/ops/analytics: 分析と日報(/analytics/ を受け持つ。notes:plan/done/analytics-daily-report.md)。入口を一時フォルダに写すテストでは無いことがある
    from manage.ops.analytics import service as analytics_mod  # noqa: E402
except ImportError:
    analytics_mod = None

APP_ID = "ytt-launcher"
VERSION = _version.VERSION   # 全体の版(ytt/version.py の 1 か所。RS5-E。画面は /api/status の version を表示する)
TOOL_ID = "portal"         # .runtime/portal.json。各ツールの /api/siblings は3つのツールIDしか読まないので影響しない
DEFAULT_PORT = 8700        # 8700〜8719。文字起こし(8775〜8794)・スタジオ(8800〜)・cut2resolve(8810〜)の範囲と重ならない
PORT_RANGE = 20
UI_KIT_DIR = os.path.join(ROOT, layout.UI_KIT_DIR)   # 共通の見た目は正本をそのまま配る(写しを作らない)
LOG_MAX = 1024 * 1024     # ログ(*.log。.gitignore 済み)はこれを超えたら <名前>.old.log に回す(fsio.rotate。回せなければそのまま追記)
PING_TIMEOUT = 0.5
MAX_BODY = 4096
SUBMIT_START_WAIT = 120  # 起動直後の POST /api/flow/submit がツールの取り込みを待つ最長の秒(_post_flow_submit)
PORTAL_TITLE = "動画編集ツール — ホーム"   # ホームの画面(portal.html)の <title>。窓を前に出すときに題名で探す(test_launch が portal.html と比べる)
YTT_API = mount_mod.YTT_API   # 画面の共通の API の場所(入口の画面・取り込んだツールの画面の両方から。PortalServer.ytt_request)
YTT_BODY_MAX = 16 * 1024   # エラーのスタックが入るので、他の API より大きめ
HEADLESS_READY = "ready"   # 画面なしの入口が標準出力に出す 1 行の event(起こしたアプリ・CLI が読む)
EXIT_RUNNING = 3           # 画面なし: 入口がすでに動いている(ポート・.flow.lock)ので起動しない
HEADLESS_RUNNING = "ホームはすでに起動しています(ポート %d)。画面なしでは起動しません。動いているホームを「すべて終了」してから起動してください"
HEADLESS_NO_RESTART = "画面なしのホームは起動し直せません(起こしたアプリから起動し直してください)"
PARENT_POLL = 2.0          # 親の見張り: Windows 以外で親の生死を見る間隔(秒。Windows は WaitForSingleObject で待つ)
MACHINE_PUT_FIELDS = ("device", "llmModel", "caseRoot", "diskMinGB", "learningDir")   # PUT /api/flow/machine で変えられる項目(F1 の 1-2 の口)
LEARNPACK_DIR = "学習"          # 学習の束の置き場所 <依頼の受付のフォルダ>/学習(F1 の 3 の (f1c))
LEARNPACK_FIRST, LEARNPACK_EVERY = 60.0, 86400.0   # 起動のあと最初に置くまでの秒・置き直しを見る間隔(1 日。ユーザー「そんなに頻繁に送らなくていい」。中身が変わらなければ作らない)


def _human_learn():
    """③ の学習の部品(flow/learning.Learning の human_loader。作業データの置き方のときだけ・文書があるときだけ呼ばれる)。
    doc_jobs の代わりに学習の読み手を通さない物を渡す(doc_jobs.dict_learned は set_learning の読み手へ戻ってくるので)"""
    import types
    from human.proof import doc_jobs, learn
    return learn, types.SimpleNamespace(dict_learned=learn.dict_learned_text, learned_finder=doc_jobs.learned_finder)

def _spec(tid, name, sub, port, **kw):
    """ツールの表の 1 行。app(/api/ping の名前。互換のため変えない)と dir(src/ の中のフォルダ)は ytt の正(runtime.TOOL_APPS・layout.TOOL_DIRS)から。
    期待する版は全体の版(ytt/version.py。expected_version)なので、ツールごとの版のファイルは持たない"""
    d = layout.TOOL_DIRS[tid]
    return dict({"id": tid, "app": runtime.TOOL_APPS[tid], "name": name, "sub": sub, "dir": d, "port": port}, **kw)


# 作業の順番どおり。port は各ツールの既定(使用中ならツール自身が次の番号を選ぶ)
TOOLS = (
    _spec("studio", "切り抜きスタジオ", "配信を探す・切り抜く区間を選ぶ・書き出す", 8800),
    _spec("transcribe", "編集", "文字起こし・カット・Resolve へのパック", 8775, venv=True),
    # cut2resolve: 「編集」がパックを作るのに使う(/cut2resolve/api/...)。画面のカードは出さない(hidden。止まっている・落ちたときだけ出す。notes:docs/design/edit-tool-design.md の 6)
    _spec("cut2resolve", "cut2resolve", "「編集」がパックを作るのに使う部品(Resolve へ渡すカットと字幕)", 8810, hidden=True),
)
TOOL_IDS = tuple(t["id"] for t in TOOLS)


# ---------- 小さな道具 ----------
def runtime_dir(root):
    """<リポジトリ直下>/.runtime。環境変数 YTT_RUNTIME_DIR があればそちら(各ツールと同じ規則。ytt.runtime)。"""
    return runtime.runtime_dir(layout.tool_dir("app", root))


# .runtime の読み書き・/api/ping・接続の確認は ytt.runtime(各ツールと同じ規則)
valid_port = runtime.valid_port
read_runtime = runtime.read_runtime     # (rdir, tool) → {"port", "version", "pid", "mtime"} / None。誰でも書けるファイルなので検証して読む


def ping(port, timeout=PING_TIMEOUT, path="/"):
    """127.0.0.1:port の <path>api/ping → {"app", "version"} / None(プロキシを通さない)。"""
    return runtime.ping(port, timeout, path)


def port_open(port, timeout=0.3):
    """そのポートで何かが待ち受けているか(つないですぐ切る)。動作中の確認はこれで行う:
    /api/ping を数秒ごとに送ると、アクセスを記録するツール(文字起こし)の黒い画面・ログが埋まるため。"""
    return runtime.port_open(port, timeout)


def tail(path, lines=200, max_bytes=256 * 1024):
    """ファイルの末尾 lines 行(読めなければ None)。大きなログでも末尾 max_bytes だけ読む。文字コードが崩れた所は置き換える。"""
    try:
        with open(path, "rb") as f:
            f.seek(0, os.SEEK_END)
            size = f.tell()
            start = max(0, size - max_bytes)
            f.seek(start)
            data = f.read()
    except OSError:
        return None
    if start > 0:   # 途中から読んだ最初の行は欠けているので捨てる
        nl = data.find(b"\n")
        data = data[nl + 1:] if nl >= 0 else b""
    text = data.decode("utf-8", "replace").replace("\r\n", "\n").replace("\r", "\n")
    out = text.split("\n")
    if out and out[-1] == "":
        out.pop()
    return out[-lines:] if lines > 0 else []


def expected_version(spec, root):
    """フォルダの中のコードの版 = 全体の版(ytt/version.py をディスクから読み直した値。読めなければ None)。別の画面で古い版が動いているのを見分けるため。
    spec は今は使わない(全ツール同じ版)が、呼び出しの形は残す"""
    return _version.on_disk(root) or None


def tool_python(tool_dir, spec):
    """子を起動する Python(取り込めなかったツールを子プロセスで動かすとき):
    Windows は入口と同じ(py -3 / python)、Mac/Linux の文字起こしは .venv があればそちら。"""
    if os.name != "nt" and spec.get("venv"):
        v = os.path.join(tool_dir, ".venv", "bin", "python")
        if os.access(v, os.X_OK):
            return v
    return sys.executable


def rel_or_abs(path, root):
    """root からの相対(表示用)。別のドライブ(アプリは E:・作業データは C: など)で相対にできなければ絶対パスのまま"""
    try:
        return os.path.relpath(path, root)
    except ValueError:
        return os.path.abspath(path)


def signal_stop(proc):
    """終わってほしい合図を送る(強制終了はしない)。Windows は子のプロセスグループへの Ctrl+Break(SIGBREAK)、
    それ以外は SIGTERM。どちらも各ツールが .runtime を消してから終わる処理につながっている。"""
    try:
        if os.name == "nt":
            os.kill(proc.pid, signal.CTRL_BREAK_EVENT)
        else:
            proc.send_signal(signal.SIGTERM)
    except (OSError, ValueError):
        pass


# ---------- ツール1つの状態 ----------
class Tool:
    """1つのツールのサーバー(子プロセス)の状態。値の変更は lock の中で行う。
    state: stopped 停止 / starting 起動中 / running 動作中 / external 別の画面で起動済み / stopping 停止中 /
           crashed 異常終了 / missing フォルダ・serve.py が無い
    mounted = True は、子プロセスではなく入口のサーバーの中に取り込んで動かしているもの(段階3。src/app/mount.py)"""

    def __init__(self, spec, root, logs_dir):
        self.spec = spec
        self.id = spec["id"]
        self.app = spec["app"]
        self.root = root
        self.dir = os.path.join(root, spec["dir"])
        self.script = os.path.join(self.dir, "serve.py")
        self.log_path = os.path.join(logs_dir, self.id + ".log")
        self.default_port = spec["port"]
        self.lock = threading.RLock()
        self.state = "stopped"
        self.message = ""
        self.since = time.time()
        self.proc = None
        self.managed = False      # この入口が起動した子プロセスか(別の画面で起動したものは止めない)
        self.port = None
        self.version = ""
        self.expected = None
        self.exit_code = None
        self.spawned_at = 0.0
        self.starts = 0
        self.last_ping = 0.0
        self.fail_pings = 0
        self.mounted = False
        self.mount = None
        self.path = "/"

    def set_state(self, state, message=""):
        self.state = state
        self.message = message
        self.since = time.time()

    def snapshot(self):
        with self.lock:
            return {
                "id": self.id, "name": self.spec["name"], "sub": self.spec["sub"], "state": self.state, "message": self.message,
                "since": round(self.since, 3), "port": self.port, "version": self.version, "expectedVersion": self.expected,
                "managed": self.managed, "exitCode": self.exit_code, "starts": self.starts, "mounted": self.mounted, "path": self.path,
                "hidden": bool(self.spec.get("hidden")),
                "log": rel_or_abs(self.log_path, self.root), "hasLog": os.path.exists(self.log_path),
            }


# ---------- まとめて管理 ----------
def app_data_dir(root):
    """入口の作業データの置き場所(%LOCALAPPDATA%\\youtube-tools\\app。inplace ならリポジトリ直下の .data/app)。設定(settings.json)・窓の専用のプロファイル・記録。
    入口自身が決める側なので、登録(datadir.register)は見ない(規則は ytt.datadir.locate の1か所。main() が登録し、案件などは resolve で読む)"""
    return datadir.locate("app", root)


def logs_dir_for(root):
    """入口とツールの出力の記録の置き場所: 作業データの置き場所(ytt.datadir。%LOCALAPPDATA%\\youtube-tools\\app\\logs)。
    YTT_DATA_DIR=inplace(テスト)なら .data/app/logs。記録だけなので、写しは作らない"""
    return os.path.join(app_data_dir(root), "logs")


class Supervisor:
    def __init__(self, root=ROOT, only=None, ready_timeout=90.0, stop_timeout=8.0, poll=0.5, log=None, ports=None, mounts=()):
        """ports: {"studio": 18800, ...} 既定のポートを変える(テスト用。本物のツールとぶつからないように)
        mounts: 入口のサーバーに取り込むツール("studio" など。src/app/mount.py の MOUNTS にあるもの)。attach() でサーバーを渡してから start する"""
        self.root = os.path.abspath(root)
        self.rdir = runtime_dir(self.root)
        self.logs_dir = logs_dir_for(self.root)
        self.tools = [Tool(s, self.root, self.logs_dir) for s in TOOLS if not only or s["id"] in only]
        for t in self.tools:
            t.default_port = int((ports or {}).get(t.id) or t.default_port)
        self.by_id = {t.id: t for t in self.tools}
        self.ready_timeout = ready_timeout
        self.stop_timeout = stop_timeout
        self.poll = poll
        self.log = log or (lambda msg: None)
        self._halt = threading.Event()
        self._thread = None
        self.mounts = tuple(m for m in mounts if m in mount_mod.MOUNTS)
        self.server = None

    def attach(self, server):
        """入口のサーバー(PortalServer)を渡す。取り込むツールはこのサーバーの中で動く。"""
        self.server = server

    # --- 状態 ---
    def status(self):
        return {"app": APP_ID, "version": VERSION, "tools": [t.snapshot() for t in self.tools],
                "dataDir": datadir.data_root(),   # 作業データの置き場所(画面に出す。inplace のときは null)
                "heavy": jobs.SLOTS.snapshot()}   # 重い処理の実行中・順番待ち(入口の中に取り込んだツールの分)

    def _find_external(self, t, scan=False):
        """別の画面で動いている同じツール (port, version)。.runtime のポートと既定のポートを問い合わせる
        (scan=True なら既定から20個。子が「すでに起動しています」で終わったとき用)。"""
        cands = []
        info = read_runtime(self.rdir, t.id)
        if info and not (self.server and info["port"] == self.server.server_address[1]):   # 自分(この入口)の記録は問い合わせない
            cands.append((info["port"], info["path"]))
        base = t.default_port
        cands += [(p, "/") for p in (range(base, base + PORT_RANGE) if scan else [base])]
        for p, path in dict.fromkeys(cands):   # 同じ所は 1 回だけ問い合わせる(順番はそのまま)
            r = ping(p, 0.3 if scan else PING_TIMEOUT, path)
            if r and r["app"] == t.app:
                return p, r["version"]
        return None

    # --- 起動 ---
    def start(self, tid):
        t = self.by_id[tid]
        with t.lock:
            if t.state in ("starting", "running", "stopping", "external"):
                return t.snapshot()
            t.expected = expected_version(t.spec, self.root)
            if not os.path.isfile(t.script):
                t.proc, t.managed, t.port = None, False, None
                t.set_state("missing", "%s が見つかりません" % rel_or_abs(t.script, self.root))
                self.log("× %s: %s" % (t.spec["name"], t.message))
                return t.snapshot()
            ext = self._find_external(t)
            if ext:
                self._mark_external(t, *ext)
                return t.snapshot()
            if t.id in self.mounts and self.server is not None and self._mount(t):
                return t.snapshot()
            self._spawn(t)
            return t.snapshot()

    def _mount(self, t):
        """入口のサーバーの中に取り込んで動かす。できなければ False(従来どおり子プロセスで起動する)。"""
        m = mount_mod.Mount(self.root, t.id, self.logs_dir)
        try:
            handler = m.start(self.server.server_address[1], self.server.allowed_hosts, self.server.token)
        except Exception as e:   # 取り込めなくても使えるように、子プロセスに切り替える
            self.log("※ %s をホームに取り込めませんでした(%s: %s)。別のプログラムとして起動します" % (t.spec["name"], e.__class__.__name__, e))
            return False
        self.server.mounts[m.prefix] = handler
        t.proc, t.managed, t.mounted, t.mount, t.fail_pings = None, True, True, m, 0
        t.port, t.path, t.version = self.server.server_address[1], m.path, m.version()
        t.starts += 1
        t.set_state("running")
        self.log("○ %s: http://localhost:%d%s (v%s・ホームに取り込み)" % (t.spec["name"], t.port, t.path, t.version))
        return True

    def unmount_all(self):
        """終了の後始末(取り込んだツールの .runtime を消す)。"""
        for t in self.tools:
            if t.mounted and t.mount:
                t.mount.stop()

    def _mark_external(self, t, port, version):
        t.proc, t.managed, t.port, t.version, t.fail_pings = None, False, port, version, 0
        msg = ""
        if t.expected and version and version != t.expected:
            msg = "古い版(v%s)が別の黒い画面で動いています。その画面を閉じてから「起動」を押すと、v%s で起動します" % (version, t.expected)
        t.set_state("external", msg)
        self.log("○ %s: 別の画面で起動済み http://localhost:%d/ (v%s)%s" % (t.spec["name"], port, version, "  ※" + msg if msg else ""))

    def _spawn(self, t):
        os.makedirs(self.logs_dir, exist_ok=True)
        fsio.rotate(t.log_path, LOG_MAX)
        env = dict(os.environ)
        env.setdefault("PYTHONIOENCODING", "utf-8:backslashreplace")   # ファイルへの出力で cp932 に無い文字(絵文字の題名など)で落ちないように
        env["PYTHONUNBUFFERED"] = "1"
        cmd = [tool_python(t.dir, t.spec), "-u", t.script, str(t.default_port), "--no-open"]
        kw = {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP} if os.name == "nt" else {}
        try:
            with open(t.log_path, "ab") as logf:
                logf.write(("\n==== %s ホームから起動 ====\n" % time.strftime("%Y-%m-%d %H:%M:%S")).encode("utf-8"))
                logf.flush()
                proc = subprocess.Popen(cmd, cwd=t.dir, env=env, stdin=subprocess.DEVNULL, stdout=logf, stderr=subprocess.STDOUT, **kw)
        except OSError as e:
            t.proc, t.managed = None, False
            t.set_state("crashed", "起動できませんでした(%s)" % tools.why(e))
            self.log("× %s: %s" % (t.spec["name"], t.message))
            return
        t.proc, t.managed, t.port, t.version, t.exit_code, t.fail_pings = proc, True, None, "", None, 0
        t.spawned_at = time.time()
        t.starts += 1
        t.set_state("starting")
        self.log("… %s を起動しています" % t.spec["name"])

    def start_all(self):
        for t in self.tools:
            self.start(t.id)

    # --- 停止 ---
    def stop(self, tid):
        t = self.by_id[tid]
        with t.lock:
            if t.state == "external":   # 別の画面で起動したものは止めない(その画面で作業中かもしれない)
                return t.snapshot()
            if t.mounted:   # 入口のサーバーの中で動いているので、単独では止めない(入口と一緒に終わる)
                return t.snapshot()
            proc = t.proc
            if proc is None:
                if t.state not in ("crashed", "missing"):
                    t.set_state("stopped")
                return t.snapshot()
            t.set_state("stopping")
            signal_stop(proc)
        try:   # 待つ間は lock を持たない(画面の状態表示を止めないため)
            proc.wait(self.stop_timeout)
        except subprocess.TimeoutExpired:
            self.log("※ %s が %d 秒で終わらないので強制終了します" % (t.spec["name"], self.stop_timeout))
            tools.kill_quiet(proc)
            try:
                proc.wait(5)
            except subprocess.TimeoutExpired:
                pass
        with t.lock:
            if t.proc is proc:
                self._finish(t, proc.returncode, "stopped", "")
                self.log("■ %s を止めました" % t.spec["name"])
            return t.snapshot()

    def restart(self, tid):
        self.stop(tid)
        return self.start(tid)

    def stop_all(self):
        ths = [threading.Thread(target=self.stop, args=(t.id,), daemon=True) for t in self.tools if t.proc is not None]
        for th in ths:
            th.start()
        for th in ths:
            th.join(self.stop_timeout + 7)

    def _finish(self, t, code, state, message):
        t.proc, t.exit_code = None, code
        t.set_state(state, message)
        self._cleanup_runtime(t)
        t.port = None

    def _cleanup_runtime(self, t):
        """強制終了などで子が消せなかった .runtime/<ID>.json を消す。今回起動した子が書いたもの(起動より後の更新時刻)で、
        そのポートが応答しないときだけ(別の画面で起動したツールの記録は消さない)。"""
        if not t.managed:
            return
        info = read_runtime(self.rdir, t.id)
        if not info or info["mtime"] < t.spawned_at - 2:
            return
        r = ping(info["port"], 0.3)
        if r and r["app"] == t.app:
            return
        fsio.unlink_quiet(os.path.join(self.rdir, t.id + ".json"))

    # --- 監視 ---
    def _tick(self, t):
        with t.lock:
            if t.mounted:   # 入口のサーバーの中で動いている(見張る子プロセスは無い)
                return
            now = time.time()
            if t.proc is not None:
                code = t.proc.poll()
                if code is not None:
                    return self._on_exit(t, code)
            if t.state == "starting":
                info = read_runtime(self.rdir, t.id)
                if info and info["mtime"] >= t.spawned_at - 2:   # 前回の古い記録は使わない
                    r = ping(info["port"])
                    if r and r["app"] == t.app:
                        t.port, t.version = info["port"], r["version"]
                        t.set_state("running")
                        t.last_ping = now
                        self.log("○ %s: http://localhost:%d/ (v%s)" % (t.spec["name"], t.port, t.version))
                        return
                if now - t.spawned_at > self.ready_timeout and not t.message:
                    t.message = "起動に時間がかかっています。下のログを確認してください"
            elif t.state in ("running", "external") and now - t.last_ping >= 3:
                t.last_ping = now
                if port_open(t.port):   # 誰のサーバーかは起動・検出のときに /api/ping で確かめ済み
                    t.fail_pings = 0
                    if t.state == "running" and t.message.startswith("応答"):
                        t.message = ""
                    return
                t.fail_pings += 1
                if t.state == "external" and t.fail_pings >= 2:
                    t.port = None
                    t.set_state("stopped", "別の画面で動いていたサーバーが終了しました")
                    self.log("■ %s: 別の画面のサーバーが終了しました" % t.spec["name"])
                elif t.state == "running" and t.fail_pings >= 3 and not t.message:
                    t.message = "応答がありません(重い処理の途中の可能性があります)"

    def _on_exit(self, t, code):
        """子プロセスが終わっていた。止めた最中なら停止、そうでなければ異常終了(または別の画面で起動済みだった)。"""
        if t.state == "stopping":   # 停止の合図で終わった(stop() の待ちより先に監視が気づいた)
            self._finish(t, code, "stopped", "")
            self.log("■ %s を止めました" % t.spec["name"])
            return
        if code == 0:   # 「すでに起動しています」で終わった(起動直前に別の画面で起動された)など
            ext = self._find_external(t, scan=True)
            if ext:
                t.proc, t.exit_code = None, code
                self._mark_external(t, *ext)
                return
            self._finish(t, code, "stopped", "終了しました")
            self.log("■ %s が終了しました" % t.spec["name"])
            return
        self._finish(t, code, "crashed", "異常終了しました(終了コード %s)。下のログを確認して、「起動」で起動し直せます" % code)
        last = tail(t.log_path, 5) or []
        self.log("× %s が異常終了しました(終了コード %s)。ログ: %s" % (t.spec["name"], code, rel_or_abs(t.log_path, self.root))
                 + "".join("\n    " + ln for ln in last))

    def _monitor(self):
        while not self._halt.wait(self.poll):
            for t in self.tools:
                try:
                    self._tick(t)
                except Exception as e:   # 監視は止めない
                    self.log("※ 監視中のエラー(%s): %s" % (t.id, e.__class__.__name__))

    def start_monitor(self):
        self._thread = threading.Thread(target=self._monitor, daemon=True, name="launcher-monitor")
        self._thread.start()

    def close(self):
        self._halt.set()
        if self._thread:
            self._thread.join(2)


# ---------- 入口の画面(HTTP) ----------
SETTINGS_DIR = os.path.join(CODE_DIR, "ui", "settings")   # 設定の画面(/settings。設定を 1 つに S5。スキーマ schema.json から UIKit.settingsForm が描く。
# 入口の直下の 1 枚にする = 画面の相対パス api/ytt/… が入口の API を指す(ui-kit の決まり。/settings/ のフォルダにすると /settings/api/… になる)
STATIC = {"/": ("portal.html", HOME_UI_DIR), "/index.html": ("portal.html", HOME_UI_DIR), "/portal.js": ("portal.js", HOME_UI_DIR),
          "/portal.css": ("portal.css", HOME_UI_DIR), "/ui-kit.css": ("ui-kit.css", UI_KIT_DIR), "/ui-kit.js": ("ui-kit.js", UI_KIT_DIR),
          "/settings": ("index.html", SETTINGS_DIR), "/settings.js": ("settings.js", SETTINGS_DIR),
          "/settings.css": ("settings.css", SETTINGS_DIR), "/settings-schema.json": ("schema.json", SETTINGS_DIR)}
# 案件の画面(/cases。RS8 C1。notes:docs/design/rs8-cases-build.md)。/settings と同じく入口の直下の 1 枚(相対パス api/… が入口・studio/api/… が取り込んだスタジオ)。
# パネルは /cases-panels/<名前>.js(/cases/ で始めない = 画面の相対パスがずれない)。URL は完全一致の表だけ(フォルダを丸ごと配らない)
CASES_DIR = os.path.join(ROOT, "app", "ui", "cases")
CASES_PANELS = ("cand", "proof", "cut")   # 候補・校正・カットとパック(C2 で中身を移す)
STATIC.update({"/cases": ("index.html", CASES_DIR), "/cases.js": ("cases.js", CASES_DIR), "/cases.css": ("cases.css", CASES_DIR),
               "/cases-caselink.js": ("caselink.js", CASES_DIR)})   # 案件の画面へのリンクと校正の進み(ホームと案件の画面の両方が読む)
STATIC.update({"/cases-panels/%s.js" % n: (os.path.join("panels", n + ".js"), CASES_DIR) for n in CASES_PANELS})
STATIC["/cases-panels/cand.css"] = (os.path.join("panels", "cand.css"), CASES_DIR)   # 候補のパネルの見た目(スタジオ ② の review.css の写し。C2a)
# 新しい案件のパネル(ホームの引き出しで開く。スタジオ ① の rank.js + queue.js のつなぎ。RS8 C3)。ホームが読む(/cases の画面では使わない)
STATIC["/cases-panels/new.js"] = (os.path.join("panels", "new.js"), CASES_DIR)
STATIC["/cases-panels/new.css"] = (os.path.join("panels", "new.css"), CASES_DIR)
STATIC["/portal-edit.js"] = ("portal-edit.js", HOME_UI_DIR)   # ホームの運用の中の「精度」「学習」(編集の左メニューにあった物。RS8 C3)
STATIC.update({"/cases-panels/proof.css": (os.path.join("panels", "proof.css"), CASES_DIR),   # 校正のパネル(C2b): 見た目・3 択の部品・編集を載せる台(編集の app-*.js は transcribe/ から読む)
               "/cases-panels/machpick.js": (os.path.join("panels", "machpick.js"), CASES_DIR), "/cases-edhost.js": ("edhost.js", CASES_DIR)})
# 確かめる(/check。RS8 V1。notes:docs/design/v1-check-build.md)。案件をまたぐ軽い確認のカード。/cases と同じく入口の直下の 1 枚・完全一致の表だけ。
# カードの描き方は /check-cards/<種類>.js(V2 の 4 本が中身を足す)・カード用の軽い再生部品は /check-player.js
CHECK_DIR = os.path.join(ROOT, "app", "ui", "check")
CHECK_CARDS = ("value", "read", "voice", "time", "speech", "cut", "section")   # 切り抜く価値・どちらの読み・誰の声・行の時刻・この行は声ですか(C-EVAL)・評価の区間(C-EVAL)
STATIC.update({"/check": ("index.html", CHECK_DIR), "/check.js": ("check.js", CHECK_DIR), "/check.css": ("check.css", CHECK_DIR),
               "/check-player.js": ("player.js", CHECK_DIR)})
STATIC.update({"/check-cards/%s.js" % n: (os.path.join("cards", n + ".js"), CHECK_DIR) for n in CHECK_CARDS})
STATIC_TYPES = {".html":"text/html; charset=utf-8", ".css": "text/css; charset=utf-8", ".js": "application/javascript; charset=utf-8", ".json": "application/json; charset=utf-8"}
NAV_PAGES = httpsec.PAGES + ("/settings", "/cases", "/check")   # ほかの画面のリンクで開ける画面(httpsec.navigation_ok)
CSP = ("default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; "
       "object-src 'none'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'")
# 案件の画面はスタジオ ② の候補(YouTube の埋め込みのプレイヤー)と編集を載せるので、取り込んだスタジオの CSP と同じ(app/mount.py の MOUNTS["studio"]。
# スタイルの属性は移すパネルが使うので制限しない)。インラインのスクリプトは動かない・ほかのサイトの枠には入らない
PAGE_CSP = {"/cases": "script-src 'self' https://www.youtube.com https://s.ytimg.com; object-src 'none'; base-uri 'none'; "
                      "form-action 'none'; frame-ancestors 'none'"}
PAGE_CSP["/check"] = PAGE_CSP["/cases"]   # 確かめる: 候補のままのカードが配信の区間を YouTube の埋め込みで再生する(案件の画面と同じ)
# ホームは「新しい案件」の引き出し(スタジオ ① の配信を探す。サムネイルは ytimg。画面の部品が style 属性を使う)を載せるので、画像とスタイルの属性だけ足す。
# スクリプトは 'self' のまま(YouTube のプレイヤーはホームに無い)
HOME_CSP = CSP.replace("style-src 'self'", "style-src 'self' 'unsafe-inline'").replace("img-src 'self' data:", "img-src 'self' data: https://*.ytimg.com https://*.ggpht.com")
PAGE_CSP["/"] = PAGE_CSP["/index.html"] = HOME_CSP
ACTION_RE = re.compile(r"/api/tools/([a-z0-9]{1,20})/(start|stop|restart)")
# GET: 部品の今の状態をそのまま返す API(場所 → PortalServer の属性。どれも .snapshot())
GET_SNAPSHOTS = {"/api/intake": "intake",       # 友人からの依頼の受付(src/human/friend/intake.py)
                 "/api/backup": "backup",       # 作業データのバックアップの状態と設定(src/manage/keep/backup.py)
                 "/api/accuracy": "accuracy",   # 精度の自動測定の状態(src/eval/drill/accuracy.py)
                 "/api/flow/runs": "autorun"}   # まとめて実行の状態(src/flow/runqueue.py の snapshot。RV A1 で /api/autorun から)
# POST: 場所 → (PortalHandler のメソッド, 終了の途中なら 409 で断るか)。合言葉・Origin などの検査と本文の読み取りは do_POST が先に済ませる
POST_ROUTES = {"/api/cases/auto": ("_post_case_auto", True),
               "/api/flow/submit": ("_post_flow_submit", True), "/api/flow/estimate": ("_post_flow_submit", True),
               "/api/flow/cancel": ("_post_flow_job", True), "/api/flow/retry": ("_post_flow_job", True),
               "/api/flow/outbox/done": ("_post_outbox_done", False),
               "/api/intake/scan": ("_post_intake_scan", True), "/api/backup/run": ("_post_backup_run", True),
               "/api/accuracy/run": ("_post_accuracy_run", True), "/api/window": ("_post_window", False),
               "/api/check/answer": ("_post_check", True), "/api/check/skip": ("_post_check", True), "/api/check/flush": ("_post_check", True),
               "/api/cleanup": ("_post_cleanup", False), "/api/shutdown": ("_post_shutdown", False)}


def query_int(q, key, default):
    """parse_qs の結果から整数の値(無い・数でなければ default)"""
    try:
        return int((q.get(key) or [str(default)])[0])
    except ValueError:
        return default


# 本文を断った理由(httpsec.BodyError の kind)→ (HTTP の番号, error, 画面の文)。ここに無いもの(read・short・json)は (400, "json", "JSON が読めません")
BODY_ERRORS = {"type": (415, "content_type", "application/json だけを受け付けます"),
               "length": (413, "size", "本文の大きさが正しくありません"), "size": (413, "size", "本文の大きさが正しくありません"),
               "object": (400, "json", "JSON のオブジェクトを送ってください")}
FORBIDDEN = {"error": "forbidden", "message": "この画面からは使えません"}
TOKEN_FAIL = mount_mod.TOKEN_FAIL


def read_json_body(h, limit=MAX_BODY):
    """要求 h の本文(JSON のオブジェクト)。-> (辞書, None) か (None, (HTTP の番号, エラーの JSON))。
    読み方は ytt.httpsec.read_json_body(application/json だけ = 他サイトのフォームはこの形を作れない・断るときは本文を読み捨てる)。
    入口は前から空の本文を {} として読み、NaN も通している(empty_ok・allow_nan)"""
    try:
        return httpsec.read_json_body(h, limit, empty_ok=True, allow_nan=True), None
    except httpsec.BodyError as e:
        code, err, msg = BODY_ERRORS.get(e.kind, (400, "json", "JSON が読めません"))
        return None, (code, {"error": err, "message": msg})


def site_ok(headers, allowed):
    """書き込み系の要求の出どころ: Host(DNS rebinding 対策)・Origin・Sec-Fetch-Site(他サイトからの操作 = CSRF 対策)。規則は ytt.httpsec"""
    return httpsec.host_ok(headers, allowed) and httpsec.origin_ok(headers, allowed) and httpsec.fetch_site_ok(headers)


def guarded_body(h, token, limit):
    """出どころ(site_ok)を確かめたあとの書き込み系の要求: 合言葉 → 本文。-> 本文の辞書か None(断りの応答を送った)。
    断るときは本文を読み捨てる(読まずに閉じると Windows では 403 が届かないことがある。httpsec.drain_body)"""
    if not httpsec.token_ok(h.headers, token, mount_mod.TOKEN_HEADER):
        httpsec.drain_body(h.headers, h.rfile)
        h._json(403, TOKEN_FAIL)
        return None
    body, err = read_json_body(h, limit)
    if err:
        h._json(*err)
    return body


class PortalHandler(BaseHTTPRequestHandler):
    server_version = "ytt-launcher"
    timeout = 30

    def log_message(self, fmt, *args):   # アクセスのたびに黒い画面へ出さない(状態の変化だけを出す)
        pass

    def _host_ok(self):          # DNS rebinding 対策
        return httpsec.host_ok(self.headers, self.server.allowed_hosts)

    def _site_ok(self):
        return httpsec.fetch_site_ok(self.headers)

    def _navigation_ok(self, path):
        """他のツールの画面のリンクで入口を開くのは許す(画面を開くだけで、URL で処理は始まらない)。API は同じ画面からだけ"""
        return httpsec.navigation_ok(self.headers, path, NAV_PAGES)

    def _send(self, code, body=b"", ctype="text/plain; charset=utf-8", extra=None):
        httpsec.send(self, code, body, ctype, extra)   # 見出し(no-store・nosniff)は ytt の 1 か所(取り込んだツールと同じ)

    def _json(self, code, obj):
        self._send(code, json.dumps(obj, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8")

    def _fail(self, code, err, message):
        self._json(code, {"error": err, "message": message})

    def do_GET(self):
        u = urllib.parse.urlsplit(self.path)
        if not (self._host_ok() and (self._site_ok() or self._navigation_ok(u.path))):
            return self._send(403, b"forbidden")
        if (u.path == "/live" or u.path.startswith("/live/")) and self.server.live.handle_get(self, u):   # リアルタイム切り抜き(オフなら下の 404 のまま)
            return
        if (u.path == "/analytics" or u.path.startswith("/analytics/")) and self.server.analytics and self.server.analytics.handle_get(self, u):
            return
        if u.path in ("/settings/", "/settings/index.html"):   # 設定の画面は /settings(入口の直下。相対パスが入口の API を指すように)
            return self._send(302, b"", "text/plain; charset=utf-8", {"Location": "/settings"})
        if u.path in ("/cases/", "/cases/index.html"):   # 案件の画面も入口の直下の 1 枚(引数 ?c=&d= はそのまま渡す)
            return self._send(302, b"", "text/plain; charset=utf-8", {"Location": "/cases" + ("?" + u.query if u.query else "")})
        if u.path in ("/check/", "/check/index.html"):   # 確かめるも入口の直下の 1 枚(?c=&kind=&back= はそのまま渡す)
            return self._send(302, b"", "text/plain; charset=utf-8", {"Location": "/check" + ("?" + u.query if u.query else "")})
        if u.path in STATIC:
            name, base = STATIC[u.path]
            try:
                with open(os.path.join(base, name), "rb") as f:
                    body = f.read()
            except OSError:
                return self._send(404, b"not found")
            page = name.endswith(".html")
            if page:   # 書き込み系の API の合言葉(CSRF トークン)を画面に渡す。取り込んだツールと同じ合言葉
                body = mount_mod.inject_token(body, self.server.token)
            return self._send(200, body, STATIC_TYPES[os.path.splitext(name)[1]],
                              {"Content-Security-Policy": PAGE_CSP.get(u.path, CSP), "X-Frame-Options": "DENY", "Referrer-Policy": "no-referrer"} if page else None)
        sup, q = self.server.sup, urllib.parse.parse_qs(u.query)
        if u.path == "/api/ping":
            return self._json(200, {"app": APP_ID, "version": VERSION})
        if u.path == "/api/status":
            st = sup.status()
            st["window"] = self.server.window.status()   # 画面を窓で開くか(段階7-3)
            return self._json(200, st)
        if u.path == "/api/health":   # 「調子」(段9 9-1。重い物は別のスレッドで数え、10 分は前の値。?refresh=1 で数え直す)
            return self._json(200, self.server.health.snapshot(refresh=(q.get("refresh") or ["0"])[0] == "1"))
        if u.path == "/api/cleanup":   # 片付けの候補(段9 9-2。候補の一覧は入口が持ち、POST は候補に出した物だけ)
            return self._json(200, self.server.cleanup_candidates())
        if u.path == "/api/log":
            tid = (q.get("tool") or [""])[0]
            if tid == "client":   # 画面のエラーの記録(段階7-0。1行 = 1件の JSON)
                path = self.server.client_log.path
            elif tid in sup.by_id:   # 決まったIDだけ。パスは受け取らない
                path = sup.by_id[tid].log_path
            else:
                return self._fail(404, "unknown_tool", "そのツールはありません")
            lines = tail(path, min(1000, max(1, query_int(q, "lines", 200))))
            return self._json(200, {"tool": tid, "exists": lines is not None, "lines": lines or [], "log": path})
        if u.path in GET_SNAPSHOTS:
            return self._json(200, getattr(self.server, GET_SNAPSHOTS[u.path]).snapshot())
        case = (q.get("case") or [None])[0] if u.path in ("/api/flow/status", "/api/flow/history") else None   # 案件の根の絶対パス(RS8)
        if case is not None and board_mod.norm_case(case) is None:
            return self._fail(400, "bad_request", "case は案件のフォルダの絶対パスにしてください")
        if u.path == "/api/flow/machine":   # この PC の設定(F1 F0-1)
            try:
                return self._json(200, machine_mod.load())
            except (OSError, ValueError) as e:
                return self._fail(500, "machine", "この PC の設定を読めませんでした: %s" % e.__class__.__name__)
        if u.path == "/api/flow/outbox":   # 送り返す zip の一覧(F1 F6a)
            return self._json(200, {"files": outbox_mod.list_outbox(self.server.app_dir)})
        if u.path == "/api/flow/status":   # ② の待ち・実行中の数と進み具合(RS7-1 S4。CLI・起こしたアプリの「終わったら閉じる」)+ 掲示板(RS8)
            st = self.server.autorun.status()   # autorun を作る = 掲示板に Run を載せる(PortalServer.autorun)
            st.update(self.server.board.snapshot(case=case))
            return self._json(200, st)
        if u.path == "/api/flow/history":   # 終わった実行の記録(段2 B-6。ホームの「まとめて実行の記録」を開いたときだけ読む)
            return self._json(200, self.server.autorun.history(query_int(q, "limit", autorun_mod.HISTORY_DEFAULT), query_int(q, "offset", 0),
                                                               case=case))
        if u.path == "/api/check/next":   # 「確かめる」の待ち行列(V1。src/app/check/deck.py。読むだけ = 開いただけでは何も書かない)
            c, kind, n, skip, lane = ((q.get(k) or [None])[0] for k in ("c", "kind", "n", "skip", "lane"))   # lane = normal | eval(評価のレーン。C-EVAL)
            try:
                return self._json(200, check_deck.next_cards(self.server.check_ctx(), c, kind, n, skip, lane))
            except ValueError as e:
                return self._fail(400, "bad_request", str(e))
        if u.path == "/api/cases":   # 案件の一覧(各ツールのデータを読んで組み立て直す。src/manage/cases/cases.py)
            if "doc" in q:   # 文書 1 本から案件を引く(案件の画面が d だけの URL を開いたとき。無ければ 404)
                try:
                    got = cases_mod.find_doc(sup.root, q["doc"][0])
                except ValueError as e:
                    return self._fail(400, "bad_request", str(e))
                except Exception as e:
                    return self._fail(500, "cases", "案件を引けませんでした: %s" % e.__class__.__name__)
                return self._json(200, got) if got else self._fail(404, "not_found", "その文書の案件はありません")
            try:
                return self._json(200, cases_mod.snapshot(sup.root))
            except Exception as e:   # 読めないデータがあっても入口は落とさない
                return self._fail(500, "cases", "案件の一覧を作れませんでした: %s" % e.__class__.__name__)
        return self._fail(404, "not_found", "その操作はありません")

    def do_POST(self):
        u = urllib.parse.urlsplit(self.path)
        if not site_ok(self.headers, self.server.allowed_hosts):
            httpsec.drain_body(self.headers, self.rfile)
            return self._send(403, b"forbidden")
        if u.path.startswith(YTT_API):   # 画面の共通の API(取り込んだツールの画面からも同じ所へ来る。合言葉・本文の検査も ytt_request で)
            return self.server.ytt_request(self, "portal", VERSION)
        body = guarded_body(self, self.server.token, MAX_BODY)   # 合言葉 → 本文(断ったら応答は送ってある)
        if body is None:
            return
        if u.path.startswith("/live/") and self.server.live.enabled():   # リアルタイム切り抜き: 録画元へ中継(オフなら下の 404 のまま)
            return self.server.live.handle_post(self, u, body)
        if u.path.startswith("/analytics/") and self.server.analytics:   # 分析と日報(src/manage/ops/analytics/service.py)
            return self.server.analytics.handle_post(self, u, body)
        m = ACTION_RE.fullmatch(u.path)
        if m:
            tid, action = m.groups()
            if tid not in self.server.sup.by_id:
                return self._fail(404, "unknown_tool", "そのツールはありません")
            if self.server.closing.is_set():
                return self._fail(409, "closing", "終了の途中です")
            return self._json(200, {"tool": getattr(self.server.sup, action)(tid)})
        route = POST_ROUTES.get(u.path)
        if route is None:
            return self._fail(404, "not_found", "その操作はありません")
        if route[1] and self.server.closing.is_set():
            return self._fail(409, "closing", "終了の途中です")
        return getattr(self, route[0])(u.path, body)

    def do_PUT(self):
        """書き込み系の PUT(今は PUT /api/flow/machine だけ。F1 F0-1)。出どころ・合言葉・本文の検査は do_POST と同じ"""
        u = urllib.parse.urlsplit(self.path)
        if not site_ok(self.headers, self.server.allowed_hosts):
            httpsec.drain_body(self.headers, self.rfile)
            return self._send(403, b"forbidden")
        body = guarded_body(self, self.server.token, MAX_BODY)
        if body is None:
            return
        if u.path != "/api/flow/machine":
            return self._fail(404, "not_found", "その操作はありません")
        if self.server.closing.is_set():
            return self._fail(409, "closing", "終了の途中です")
        return self._put_machine(body)

    def _put_machine(self, body):
        """この PC の設定を machine.json に書く(flow/machine.py の save。変えられるのは MACHINE_PUT_FIELDS だけ・null = 既定へ戻す)。
        画面なしなら、録画の開始の空き容量の下限も新しい diskMinGB にそろえる(処理の開始は Queue が始めるたびに読む)。
        caseRoot を決めたときはスタジオの書き出し先 outDir も同じ所へ(出来上がる場所 = 書き出し先。友人のアプリの一時保管と同じそろえ方。処理の実行中は 409)"""
        bad = [k for k in body if k not in MACHINE_PUT_FIELDS]
        if bad:
            return self._fail(400, "bad_request", "知らない項目です: %s(使えるのは %s)" % ("・".join(map(str, bad)), "・".join(MACHINE_PUT_FIELDS)))
        try:
            if body.get("caseRoot") is not None:
                studio_env.set_out_dir(machine_mod.check("caseRoot", body["caseRoot"]), self.server.tools_busy)
            saved = machine_mod.save(body)
            now = machine_mod.load()
        except ValueError as e:
            return self._fail(400, "bad_request", str(e))
        except _yerrors.ApiError as e:   # 書き出し先にできない(400 bad_dir)・処理の実行中(409 busy)
            return self._fail(e.status, e.code, e.message)
        except OSError as e:
            return self._fail(500, "write", "この PC の設定を書けませんでした: %s" % tools.why(e))
        if self.server.headless and "diskMinGB" in body:
            self.server.live.disk_min_gb = now["diskMinGB"]
        return self._json(200, {"machine": now, "file": saved})

    def _post_case_auto(self, path, body):
        """自動でできた切り抜きの操作(線 D の M9・M12): 採用 = 友人へ届ける・要らない。中身は src/manage/cases/cases.py の auto_review"""
        return self._json(*self.server.auto_review(body))

    def _post_check(self, path, body):
        """「確かめる」(V1): answer {card, answer, ms?, skip?, page?} か {undo} / skip {card, page?} / flush {page?}。カードは src/app/check/deck.py で引き直し、
        記録と反映は src/human/check/apply.py(種類ごとの反映の部品が登録する。無い種類は 409 not_ready)。page = 画面の印(確定はその画面の保留だけ)"""
        op, ctx = path.rsplit("/", 1)[1], self.server.check_ctx()
        try:
            if op == "flush":
                out = check_apply.flush(ctx, body.get("page"))
            elif op == "skip":
                if not check_lineup.parse_id(body.get("card")):
                    return self._fail(400, "bad_request", "飛ばすカード(card)の指定が正しくありません")
                out = check_apply.skip(ctx, body["card"], body.get("page"))
            elif "undo" in body:
                out = check_apply.undo(ctx, body.get("undo"))
            else:
                if not check_lineup.parse_id(body.get("card")):
                    return self._fail(400, "bad_request", "カード(card)の指定が正しくありません")
                why = []
                card = check_deck.find(ctx, body["card"], why)
                if card is None:
                    if why:   # 集めたときの失敗(出どころ・文書の読み)。見つからない理由を後で追えるように記録へ
                        self.server.sup.log("確かめる: %s が見つかりません(集めたときの失敗: %s)" % (body["card"], "・".join(why[:5])))
                    return self._fail(404, "gone", "そのカードはもう確かめる物ではありません(読み込み直してください)" + ("(読めなかった物: %s)" % "・".join(why[:3]) if why else ""))
                out = check_apply.answer(ctx, card, body)
                check_deck.invalidate()
                held = body.get("skip") if isinstance(body.get("skip"), list) else []
                lane = "eval" if card.get("kind") in check_lineup.EVAL_KINDS else "normal"   # 次の 1 枚は答えたカードと同じレーンから
                nxt = check_deck.next_cards(ctx, n=1, skip=[x for x in held if isinstance(x, str)][:check_deck.MAX_SKIP_PARAM - 1] + [card["id"]], lane=lane)
                out["next"] = nxt["cards"][0] if nxt["cards"] else None
        except check_apply.Refused as e:
            return self._fail(e.code, e.error, e.message)
        except _yerrors.ApiError as e:   # 部品の中の文書・学習の記録の失敗(状態の番号をそのまま)
            return self._fail(e.status if isinstance(e.status, int) and 400 <= e.status <= 599 else 500, e.code, e.message)
        except ValueError as e:
            return self._fail(400, "bad_request", str(e))
        except OSError as e:   # 部品の文書の書き込みか、確かめるの記録(answers.jsonl)
            return self._fail(500, "write", "書けませんでした(文書か確かめるの記録): %s" % tools.why(e))
        finally:
            check_deck.invalidate()
        return self._json(200, out)

    def _post_flow_submit(self, path, body):
        """② の口(RS7-1 S4・RV A1): {envelope, spec?} を待ち行列に積む(src/flow/runqueue.py の Queue.submit)か、同じ本文で見積もる
        (/api/flow/estimate = Queue.estimate。書き込まない)。形が違う・積めない理由は 400。
        入口の起動直後(ツールの取り込みの途中)は済むまで SUBMIT_START_WAIT 秒まで待つ(待ちきれなければ 503 starting。見積もりは待たない)"""
        estimate = path.endswith("/estimate")
        started = getattr(self.server, "tools_started", None)
        if not estimate and started is not None and not started.wait(SUBMIT_START_WAIT):
            return self._fail(503, "starting", "入口がまだツールを準備しています。少し待ってからもう一度頼んでください")
        try:
            if estimate:
                return self._json(200, self.server.autorun.estimate(body.get("envelope"), body.get("spec")))
            return self._json(200, {"run": self.server.autorun.submit(body.get("envelope"), body.get("spec"))})
        except queue_mod.SpecVersionError as e:   # 送る側と ② の束の版が違う(アプリは「更新してください」。F1 F0-1)
            return self._fail(400, "spec_version", str(e))
        except queue_mod.BadSpecError as e:   # 束に知らない節・項目・合わない値
            return self._fail(400, "bad_spec", str(e))
        except ValueError as e:
            return self._fail(400, "bad_request", str(e))
        except (TypeError, KeyError, AttributeError) as e:   # 検査を抜けた形の違い(外から来る本文なので 500 にしない)
            return self._fail(400, "bad_request", "封筒・束の形が正しくありません(%s)" % e.__class__.__name__)

    def _post_flow_job(self, path, body):
        """掲示板のジョブ 1 つを止める・やり直す(RS8。/api/flow/<cancel|retry> {id})。振り分けは src/flow/board.py(id の頭 → 器の関数)"""
        op = path.rsplit("/", 1)[1]
        self.server.autorun   # ② の Run を掲示板に載せておく(初めて読むとき PortalServer.autorun が attach_board する)
        try:
            return self._json(200, {"job": getattr(self.server.board, op)(body.get("id"))})
        except board_mod.NotFound as e:
            return self._fail(404, "not_found", str(e))
        except board_mod.Refused as e:
            return self._fail(409, e.error, e.message)
        except ValueError as e:
            return self._fail(400, "bad_request", str(e))

    def _post_outbox_done(self, path, body):
        """上げ終えた送り返しの zip を outbox/済み へ(F1 F6a。src/flow/outbox.py の mark_done。名前の形が違う・無い id は 404)"""
        try:
            moved = outbox_mod.mark_done(self.server.app_dir, body.get("id"))
        except OSError as e:
            return self._fail(500, "write", "送り返しの zip を移せませんでした: %s" % tools.why(e))
        if not moved:
            return self._fail(404, "not_found", "その zip はありません")
        return self._json(200, {"ok": True})

    def _post_intake_scan(self, path, body):
        """今すぐフォルダを見る(時間がかかることがあるので裏で。応答は今の状態)"""
        self.server.intake.wake.set()
        return self._json(200, self.server.intake.snapshot())

    def _post_backup_run(self, path, body):
        """今すぐ写す(裏で。応答は今の状態)"""
        self.server.backup.run_now()
        return self._json(200, self.server.backup.snapshot())

    def _post_accuracy_run(self, path, body):
        """今すぐ測る(裏で。手が空くまで待つ。応答は今の状態)"""
        if not self.server.accuracy.run_now():
            return self._fail(409, "off", "精度の自動測定がオフです")
        return self._json(200, self.server.accuracy.snapshot())

    def _post_window(self, path, body):
        """画面を窓で開くか(次に起動したときから。段階7-3)"""
        try:
            self.server.window.set_mode(body.get("mode"))
        except ValueError as e:
            return self._fail(400, "bad_request", str(e))
        except OSError as e:
            return self._fail(500, "write", "設定を書けませんでした: %s" % tools.why(e))
        return self._json(200, {"window": self.server.window.status()})

    def _post_cleanup(self, path, body):
        """候補に出した物を ごみ箱フォルダ へ移す(すぐには消さない。cleanup.TRASH_DAYS で起動時に消える)"""
        ids = body.get("ids")
        if not isinstance(ids, list) or not ids or len(ids) > cleanup_mod.MAX_ITEMS * 5:
            return self._fail(400, "bad_request", "移す物を選んでください")
        with self.server.cleanup_lock:
            return self._json(200, self.server.cleanup.move(ids))

    def _post_shutdown(self, path, body):
        """すべて終了(応答を返してから後始末)"""
        out = {"ok": True}
        try:   # 録画中なら録画の部品は止めずに残す(src/app/live.py の stop_recorder)。画面の「すべて終了しました」に知らせる
            if self.server.live.local_recording() is True:
                out.update(recorderKept=True, notice=livesession.KEPT_NOTE)
        except Exception:
            pass
        self._json(200, out)
        threading.Thread(target=self.server.request_shutdown, daemon=True).start()


def _color_entry(e):
    return {k: e[k] for k in ("name", "en", "hex", "group", "mine")}


def streamer_colors(body):
    """api/ytt/streamer-colors の中身: {q, all?} → 入れた名前に合う人・候補(all なら全員も)/ {names: [...]} → 名前ごとに合う人
    (話者の名前をまとめて。画面が行ごとに通信しないように。気が利く画面へ 段2)。規則は src/ytt/colors.py"""
    entries = colors_mod.load()
    if isinstance(body.get("names"), list):
        names = list(dict.fromkeys(n.strip()[:colors_mod.NAME_MAX] for n in body["names"][:60] if isinstance(n, str) and n.strip()))
        matches = {n: colors_mod.lookup(n, entries)["match"] for n in names}
        return {"ok": True, "matches": {n: _color_entry(m) if m else None for n, m in matches.items()}}
    q = body.get("q") if isinstance(body.get("q"), str) else ""
    r = colors_mod.lookup(q[:colors_mod.NAME_MAX], entries)
    return {"ok": True, "match": _color_entry(r["match"]) if r["match"] else None, "candidates": [_color_entry(e) for e in r["candidates"]],
            "items": [_color_entry(e) for e in entries] if body.get("all") is True else []}


def hide_tokens(live_cfg):
    """設定の節 live を画面へ返す形に: 録画元の合言葉は渡さない(あるかどうかだけ)"""
    return dict(live_cfg, recorders=[dict(r, token="", hasToken=bool(r.get("token"))) for r in live_cfg.get("recorders") or []])


def peek_path(sock, timeout=10.0):
    """接続の最初の行(GET /studio/... HTTP/1.1)を、読み取らずに覗いてパスを返す(無い・壊れていれば None)。
    どのツールの Handler に渡すかを、要求を読み始める前に決めるため。つないですぐ切る接続(入口の動作確認)は None。"""
    end = time.monotonic() + timeout
    data = b""
    try:
        sock.settimeout(timeout)
        while True:
            data = sock.recv(8192, socket.MSG_PEEK)
            if not data or b"\r\n" in data or len(data) >= 8192 or time.monotonic() > end:
                break
            time.sleep(0.01)   # 続きがまだ届いていない(覗くだけなので同じ内容がすぐ返る)
    except OSError:
        return None
    line = data.split(b"\r\n", 1)[0].decode("latin-1", "replace")
    parts = line.split(" ")
    return parts[1] if len(parts) >= 3 else None


class PortalServer(httpsec.ExclusiveServer):
    """入口のサーバー。取り込んだツール(mounts: {"/studio": Handler})の要求は、そのツールの Handler に渡す。
    Windows では SO_REUSEADDR だと使用中のポートにも bind できてしまうので、代わりに SO_EXCLUSIVEADDRUSE で独占する(httpsec.ExclusiveServer。各ツールと同じ)。"""

    def __init__(self, addr, sup):
        super().__init__(addr, PortalHandler)
        self.sup = sup
        p = self.server_address[1]
        self.allowed_hosts = httpsec.allowed_hosts(p)
        self.closing = threading.Event()
        self.token = secrets.token_urlsafe(24)   # 書き込み系の API の合言葉(CSRF トークン)。起動ごとに変わる
        self.headless = False   # 画面なし(--headless。main が決める。起動し直しを断る)
        self.mounts = {}
        self._autorun = None
        self._autorun_lock = threading.Lock()
        # ② のジョブの掲示板(プロセスに 1 つ = 器を包む所と同じ物。RS8 の ② の口)。案件の根を知らない器の Job は target から引く(既定の guess_case)
        self.board = board_mod.default()
        self.board.log = sup.log
        self.board.set_case_hook(board_mod.guess_case)
        self._torn_down = False
        self._teardown_lock = threading.Lock()
        app_dir = os.path.dirname(sup.logs_dir)   # 入口の作業データ(settings.json・prefs.json・依頼の受付などの記録)
        self.app_dir = app_dir   # 送り返しの zip の置き場所 <app>/outbox(F1 F6a)
        self.learning = None     # 学習データの読み手(wire_learning。machine の learningDir があるときだけ。F1 F6a)
        self.learnpack_last = None   # 最後に学習の束を置いた結果か理由(build_learnpack。F1 F6a)
        self.client_log = clientlog_mod.ClientLog(sup.logs_dir)   # 画面のエラーの記録(段階7-0)
        self.window = appwindow_mod.Opener(app_dir, fsio.atomic_write, log=sup.log)   # 窓で開く(段階7-3)
        self.prefs = prefs_mod.Prefs(os.path.join(app_dir, "prefs.json"), fsio.atomic_write)   # ホームの設定(気が利く画面へ 段1)
        # 友人からの依頼の受付(見張りは main で start。テストで作る入口では動かさない)
        self.intake = intake_mod.Intake(self.prefs, lambda: self.autorun, app_dir, log=sup.log,
                                        feedback=lambda fb: friend_feedback_mod.apply(sup.logs_dir, fb, trash=self.cleanup, log=sup.log,
                                                                                      discard=cases_mod.discard_clip),   # 片付ける部品は入口が渡す(friend_feedback は cases を読まない)
                                        live_begin=lambda url, ctx: self.live.submit_request(url, ctx),   # ライブ配信の依頼(2-15。封筒 + 束でライブ係の submit へ 。live は下で作る)
                                        defaults=prefs_mod.DEFAULTS["intake"],   # 設定が読めないときの既定は入口が渡す(intake は prefs を読まない)
                                        flush=self.flush_sends)   # 見回りの終わりに、届けられなかった自動の分を送り直す(D-SEND 2-6)
        # 作業データのバックアップ(見張りは main で start。inplace = テストなどでは写さない)
        self.backup = backup_mod.Backup(self.prefs, datadir.data_root(), app_dir, log=sup.log, defaults=prefs_mod.DEFAULTS["backup"],
                                     out_dir=lambda: datadir.studio_out_dir(sup.root), media_dirs=backup_mod.default_media_dirs)   # 評価用・学習用の動画も
        # 精度の自動測定(見張りは main で start。テストで作る入口では動かさない)。手が空いた判定は _accuracy_busy・_accuracy_last_edit
        self.accuracy = accuracy_mod.Accuracy(self.prefs, app_dir, sup.root, busy=self._accuracy_busy,
                                              last_edit=self._accuracy_last_edit, log=sup.log, defaults=prefs_mod.DEFAULTS["accuracy"])
        self.deliveries = deliver_mod.Deliveries(self.intake.folder, txindex.is_pack_dir, log=sup.log,
                                                 log_dir=sup.logs_dir)   # 手で「友人へ届ける」(api/ytt/deliver・案件の採用)。届けた記録は全自動と同じ logs/deliveries.jsonl
        self.deliveries.attach_board(self.board)   # 届ける(頭 dl)を掲示板へ(RS8 の ② の口 S2)
        # リアルタイム切り抜き(線 D。既定はオフ。見回り = 録画の部品を起こすのは main で start。テストで作る入口では動かさない)
        self.live = live_mod.Live(self.prefs, sup.root, sup.logs_dir, log=sup.log, server=self)   # server: P4 の作り直しがスタジオの API を呼ぶ
        self.health = health_mod.Health(sup, sup.logs_dir, sup.root, worker_probe=self._worker_probe, extra_dirs=self._extra_dirs,
                                        live_probe=self.live.health, accuracy_probe=self.accuracy.snapshot,
                                        places_probe=self._places_probe)   # 「調子」(段9 9-1。録画の行はオンのときだけ・精度の行・置き場所の行)
        # 片付け(段9 9-2)。ごみ箱フォルダは動画と同じドライブ(書き出し先\ごみ箱。ユーザー決定)
        self.cleanup = cleanup_mod.Cleanup(app_dir, repo_root=sup.root, log=sup.log, out_dirs=self._extra_dirs)
        self.cleanup_lock = threading.Lock()
        # 分析と日報(見張りは main で start。テストで作る入口では動かさない。連携の設定が無ければ何もしない)
        self.analytics = analytics_mod.Service(log=sup.log, token=self.token) if analytics_mod else None

    def auto_review(self, body):
        """自動でできた切り抜きの操作(POST /api/cases/auto と「確かめる」の価値のカード)。-> (HTTP の番号, JSON)。部品は入口が渡す
        (人の判断は cases が ③ human/judgments に書く。live_feedback.jsonl には書かない = MARKS-3)"""
        return cases_mod.auto_review(self.sup.root, body, deliveries=self.deliveries, studio=self.live.studio_call, trash=self.cleanup,
                                     hide=lambda tid: self.prefs.hide("transcripts", [tid], True))

    def check_ctx(self):
        """「確かめる」(V1)の部品に渡す物(src/human/check/apply.py の Context)。③ が読めない層の操作(案件の確認・スタジオの API)は hooks で渡す。
        goals = 入口の条件(帯の「あと何本」と待ち行列の順。答えの数を足した物)"""
        return check_apply.Context(os.path.dirname(self.sup.logs_dir), self.sup.root,
                                   hooks={"auto_review": self.auto_review, "studio": self.live.studio_call},
                                   goals=lambda: self.accuracy.snapshot()["goals"])

    def _accuracy_busy(self):
        """精度の自動測定の「手が空いているか」。空いていなければ理由の文、空いていれば None。
        入口の重い処理の順番(SLOTS)・まとめて実行・「編集」のジョブ(入口から loopback で /api/jobs を読む。編集が動いていなければ動いているジョブも無い)"""
        hv = jobs.SLOTS.snapshot()
        if hv.get("active") or hv.get("waiting"):
            return "重い処理"
        if self._autorun is not None and any(r.get("state") in ("queued", "running") for r in self._autorun.snapshot().get("runs") or []):
            return "まとめて実行"
        try:
            st, obj = autorun_mod.ToolClient(self.tool_endpoint, self.token, timeout=5).call("transcribe", "GET", "/api/jobs")
        except autorun_mod.StepError:
            return None
        if st == 200 and any(j.get("state") in ("queued", "loading", "extracting", "running") for j in obj.get("jobs") or [] if isinstance(j, dict)):
            return "文字起こしのジョブ"
        return None

    def _accuracy_last_edit(self):
        """文字起こしの文書(transcripts の直下のファイル)の最後の更新(エポック秒。無ければ None)"""
        d = cases_mod.locations(self.sup.root)["transcripts"]
        newest = None
        folders = [d]
        try:
            # 案件の 作業用 に置いた文書(索引があるもの)の置き場所も見る
            folders += sorted({docloc.doc_dir(t, os.path.dirname(d)) for t in docloc.iter_tids(os.path.dirname(d))} - {d})
        except (OSError, ValueError):
            pass
        for i, folder in enumerate(folders):
            try:
                with os.scandir(folder) as it:
                    for e in it:
                        try:
                            if e.is_file():
                                m = e.stat().st_mtime
                                if newest is None or m > newest:
                                    newest = m
                        except OSError:
                            continue
            except OSError:
                if i == 0:
                    return None
        return newest

    def cleanup_candidates(self):
        """片付けの候補(案件 = スタジオと文字起こしの紐づけ・依頼の受付のフォルダから)"""
        try:
            cases = cases_mod.snapshot(self.sup.root).get("cases") or []
        except Exception as e:   # 案件を読めなくても、キャッシュ・ログの候補は出す
            self.sup.log("片付け: 案件を読めませんでした: %r" % (e,))
            cases = []
        folder = self.intake.folder() or None
        with self.cleanup_lock:
            return self.cleanup.candidates(cases, intake_dir=folder)

    def _busy_tools(self):
        """取り込んだツールのうち処理の途中の物 -> [(id, 名前)]"""
        return [(t.id, t.spec["name"]) for t in self.sup.tools if t.mounted and t.mount and t.mount.busy()]

    def tools_busy(self):
        """取り込んだツールのどれかが処理の途中か(書き出し先を変えられるかの判定)"""
        return bool(self._busy_tools())

    def restart_self(self):
        """新しい入口(同じポートが空くのを待つ)を起こしてから、この入口は「すべて終了」と同じ後始末をして終わる。
        重い処理・取り込んだツールの処理(人が始めたもの・まとめて実行の書き出し)が動いていれば 409 で断る(理由の文)。
        まとめて実行の待ち・実行中は断らない(M5 で起動し直したあとに続きから進む): 応答の notice と記録で何件続くかを知らせる。
        -> (HTTP の番号, JSON)"""
        if self.closing.is_set():
            return 409, {"ok": False, "error": "closing", "message": "終了の途中です"}
        if self.headless:   # 新しい入口は起こしたアプリの子にならない(画面ありの形で起きてしまう)= 起こし直すのは起こしたアプリ
            return 409, {"ok": False, "error": "headless", "message": HEADLESS_NO_RESTART}
        ar = self._autorun
        info = ar.restart_info() if ar is not None else {}
        busy = self._busy_tools()
        why = restart_mod.can_restart(self.sup.status(), busy, info.get("redo"))
        if why:
            return 409, {"ok": False, "error": "busy", "message": why}
        notice = restart_mod.RESUME_NOTICE % info["runs"] if info.get("runs") else ""
        only = [t.id for t in self.sup.tools] if len(self.sup.tools) < len(TOOLS) else ()
        try:
            restart_mod.spawn_new_launcher(self.sup.root, args=restart_mod.restart_args(self.server_address[1], only, not self.sup.mounts, wait_pid=os.getpid()),
                                           log=self.sup.log)
        except OSError as e:
            return 500, {"ok": False, "error": "spawn", "message": "ホームを起動し直せませんでした(新しいホームを起動できません): %s" % tools.why(e)}
        self.sup.log("画面から「起動し直す」が押されました" + ("(%s)" % notice if notice else ""))
        threading.Timer(0.3, self.request_shutdown).start()   # 応答を返してから後始末(新しい入口はポートが空くのを待っている)
        return 200, dict({"ok": True}, **({"notice": notice} if notice else {}))

    def purge_trash(self):
        """起動時: 日数(cleanup.TRASH_DAYS)を過ぎたごみ箱フォルダの日付を消す(裏で)"""
        try:
            n = self.cleanup.purge()
            if n:
                self.sup.log("ごみ箱フォルダから %d 日ぶんを消しました(%d 日を過ぎた)" % (n, self.cleanup.trash_days))
        except Exception as e:
            self.sup.log("ごみ箱フォルダを片付けられませんでした: %r" % (e,))

    def _worker_probe(self):
        """「編集」の /api/ping の worker(認識ワーカーの状態)。動いていなければ None"""
        try:
            st, d = autorun_mod.ToolClient(self.tool_endpoint, self.token, timeout=1.5).call("transcribe", "GET", "/api/ping")
        except (autorun_mod.StepError, http.client.HTTPException):
            return None
        w = d.get("worker") if st == 200 else None
        return w if isinstance(w, dict) else None

    def _places_probe(self):
        """「調子」の置き場所の 1 行(見えない文書・見えない案件・繋ぎ直した本数。src/manage/cases/outdirs.py の status)。inplace・何も無ければ None"""
        if datadir.data_root() is None:
            return None
        return outdirs_mod.status(placement.studio_data(self.sup.root), os.path.dirname(txindex.folder(self.sup.root)))

    def _extra_dirs(self):
        """空き容量を見る追加の場所・ごみ箱フォルダを置く書き出し先: スタジオの書き出し先(datadir.studio_out_dir。outDir が無ければ作業データの exports)。
        スタジオの settings.json がまだ無いとき(スタジオを一度も保存していない)は [](今までどおり。studio_out_dir は exports を返す)"""
        if not os.path.isfile(os.path.join(datadir.resolve("studio", self.sup.root), "settings.json")):
            return []
        return [datadir.studio_out_dir(self.sup.root)]

    def tool_ports(self):
        """別のプログラムとして動いているツールのポート(窓で開いてよい先。取り込んだツールは入口と同じポートなので含めない)"""
        own = self.server_address[1]
        out = []
        for t in self.sup.tools:
            snap = t.snapshot()
            if snap["state"] in ("running", "external") and snap["port"] and snap["port"] != own:
                out.append(snap["port"])
        return out

    def ytt_api(self, sub, body, tool="portal", version=""):
        """画面の共通の API の中身。-> (HTTP の番号, JSON)"""
        try:
            if sub == "client-log":
                return 200, {"ok": True, "kept": self.client_log.record(tool, body, version)}
            if sub == "open-window":
                return 200, {"ok": True, "url": self.window.open_url(body.get("url"), self.server_address[1], self.tool_ports(), tuple(self.mounts))}
            if sub == "open-external":
                return 200, {"ok": True, "url": self.window.open_external(body.get("url"))}
            if sub == "restart-self":   # 版の赤い帯の「起動し直す」(段9 9-3。ui-kit の UIKit.restart)
                return self.restart_self()
            if sub == "focus-portal":   # ツールの窓の「入口」: 入口の窓がほかにあれば前に出す(入口を二つにしない)
                return 200, {"ok": True, "focused": self.window.focus(PORTAL_TITLE)}
            if sub == "streamer-guess":   # 配信者の名前を自動で(覚えた名前 → チャンネル名から。段5)。{docId?, videoId?, channel?}
                return 200, self.streamer_guess(body.get("docId"), body.get("videoId"), body.get("channel"))
            if sub == "deliver":   # 「編集」の ③ パックの「友人へ届ける」。{op: "start", dir, title} → 裏で zip / {op: "status", job}
                if body.get("op") == "status":
                    j = self.deliveries.status(body.get("job"))
                    return (200, {"ok": True, "job": j}) if j else (404, {"error": "not_found", "message": "その仕事はありません(ホームを起動し直しましたか)"})
                return 200, {"ok": True, "job": self.deliveries.start(body.get("dir"), body.get("title"))}
            if sub == "live":   # リアルタイム切り抜き(線 D の P3): 全ツールのヘッダーの録画の札 {op: "status"} / 札の「停止」{op: "stop", recorder, recording}(src/app/live.py)
                return self.live.ytt(body)
            if sub == "prefs":   # ホームの設定(src/app/prefs.py。節ごとに読む・直す。全体を上書きしない)
                return 200, self.prefs_api(body)
            if sub == "streamer-colors":   # 配信者の名前の欄(字幕の色): 候補の一覧と、入れた名前に合う人(規則は src/ytt/colors.py)
                return 200, streamer_colors(body)
        except ValueError as e:
            return 400, {"error": "bad_request", "message": str(e)}
        except appwindow_mod.TooMany as e:
            return 429, {"error": "too_many", "message": str(e)}
        except appwindow_mod.Unavailable as e:
            return 409, {"error": "unavailable", "message": str(e)}
        except OSError as e:
            return 500, {"error": "open", "message": "開けませんでした: %s" % tools.why(e)}
        return 404, {"error": "not_found", "message": "その操作はありません"}

    def streamer_guess(self, doc_id=None, video_id=None, channel=None):
        """-> {"ok", "name", "source", "hex", "channel"}。文書だけ分かれば、その文書の元の配信(.clip.json)・チャンネル(スタジオ)を調べる"""
        doc_id = doc_id if isinstance(doc_id, str) and len(doc_id) <= 64 else None
        video_id = video_id if isinstance(video_id, str) and len(video_id) <= 64 else None
        channel = channel.strip()[:120] if isinstance(channel, str) and channel.strip() else None
        if doc_id and not video_id:
            d = next((x for x in cases_mod.txindex.load(cases_mod.locations(self.sup.root)["transcripts"]) if x["id"] == doc_id), None)
            src = ((d or {}).get("clip") or {}).get("source") or {}
            video_id = src.get("videoId") if isinstance(src.get("videoId"), str) else None
        if video_id and not channel:
            v = cases_mod.read_studio(cases_mod.locations(self.sup.root)["studio"]).get(video_id) or {}
            channel = str(v.get("channel") or "").strip()[:120] or None
        r = prefs_mod.guess_streamer(self.prefs, doc_id, video_id, channel,
                                     from_channel=lambda ch: (colors_mod.from_channel(ch) or {}).get("name"))
        hit = colors_mod.lookup(r["name"])["match"] if r["name"] else None
        return dict(r, ok=True, hex=hit["hex"] if hit else None, channel=channel)

    def prefs_api(self, body):
        op = body.get("op")
        try:
            if op == "get":
                secs = body.get("sections")
                got = self.prefs.get([x for x in secs if isinstance(x, str)] if isinstance(secs, list) else None)
                if "live" in got:
                    got["live"] = hide_tokens(got["live"])
                return {"ok": True, "prefs": got}
            if op == "patch":
                value = self.prefs.patch(body.get("section"), body.get("value"))
                # 設定を変えたら、その部品がすぐ見直す: 受付(オン・フォルダ)・バックアップ(オンにした・先を変えた → 最初の1回を写す)・
                # 精度の自動測定(オフにした → 待っていた「今すぐ」を取り下げる)
                watcher = {"intake": self.intake, "backup": self.backup, "accuracy": self.accuracy}.get(body.get("section"))
                if watcher is not None:
                    watcher.wake.set()
                if body.get("section") == "live":   # リアルタイム切り抜き: オンにした・置き場所を変えた → 見回りをすぐ(録画の部品を起こす・置き場所を伝える)
                    self.live.on_patch(None, value)
                    value = hide_tokens(value)
                return {"ok": True, "value": value}
            if op == "remember":
                return {"ok": True, "streamer": self.prefs.remember(body.get("kind"), body.get("key"), body.get("name"))}
            if op == "hide":   # 一覧の項目を非表示にする・戻す(UIKit.hide。1件ずつ足す・外す)
                lst = body.get("list")
                return {"ok": True, "list": lst, "hidden": self.prefs.hide(lst, body.get("ids"), body.get("hidden") is not False)}
        except OSError as e:
            raise ValueError("設定を保存できませんでした(%s)" % tools.why(e))
        raise ValueError("その操作はありません: %s" % str(op)[:20])

    def ytt_request(self, h, tool, version=""):
        """画面の共通の API(api/ytt/<名前>)の要求を受け持つ。h は入口か、取り込んだツールの Handler(_json を持つ)。
        取り込んだツールの画面の /studio/api/ytt/… も src/app/mount.py がここへ回す(ツールごとに同じものを書かないため)。
        検査は入口の API と同じ: POST だけ・Host・Origin・Sec-Fetch-Site・合言葉・本文は application/json で 16KB まで。
        断るときは本文を読み捨てる(読まずに閉じると Windows で 403 が届かないことがある)"""
        path = urllib.parse.urlsplit(h.path).path
        if h.command != "POST":
            return h._json(405, {"error": "method", "message": "POST で送ってください"})
        if not site_ok(h.headers, self.allowed_hosts):
            httpsec.drain_body(h.headers, h.rfile)
            return h._json(403, FORBIDDEN)
        body = guarded_body(h, self.token, YTT_BODY_MAX)
        if body is None:
            return None
        code, obj = self.ytt_api(path[len(YTT_API):] if path.startswith(YTT_API) else "", body, tool, version)
        return h._json(code, obj)

    def tool_endpoint(self, tid):
        """まとめて実行(src/app/autorun.py)がツールの API を呼ぶ先 (ポート, 場所)。動いていなければ None"""
        t = self.sup.by_id.get(tid)
        if t is None:
            return None
        snap = t.snapshot()
        if snap["state"] not in ("running", "external") or not snap["port"]:
            return None
        return snap["port"], snap["path"] or "/"

    def flow_host(self, tid):
        """まとめて実行が ① の動詞を直に呼ぶ口(flow/tools.FlowTools。OPT2 後半 J7): 入口に取り込んで動いているツールの serve の flow_host()
        (スタジオ = 解析・書き出しの LocalStudio・cut2resolve = パックの PackHost)。取り込んでいない・動いていない・口が無いときは None(HTTP の道)"""
        t = self.sup.by_id.get(tid)
        if t is None or not t.mounted or t.mount is None or t.snapshot()["state"] != "running":
            return None
        fn = getattr(t.mount.mod, "flow_host", None)
        return fn() if fn is not None else None

    @property
    def autorun(self):
        with self._autorun_lock:
            if self._autorun is None:
                client = autorun_mod.ToolClient(self.tool_endpoint, self.token)
                self._autorun = autorun_mod.AutoRunner(client, self.sup.root, prefs=self.prefs,
                                                       log_dir=self.sup.logs_dir,   # 終わった実行の記録(画面のエラーの記録と同じ logs。B-6)
                                                       log=self.sup.log,   # 友人の区間の長さを使わなかった理由など(launcher.log に1行)
                                                       tools=flowtools_mod.FlowTools(client, self.flow_host))   # ① の動詞は ② の器を直に(J7)
                self._autorun.set_status_hook(self.live_activity)   # GET /api/flow/status の live 欄と idle(Queue はライブを知らない。RS7-2 G5a)
                self._autorun.set_live_hook(lambda env, spec: self.live.submit(env, spec))   # 封筒 kind live はライブ係が受ける(録画を始めて録画の束を残す。画面なしでも。RS7-2 G2b)
                self._autorun.attach_board(self.board)   # ② の Run を掲示板へ(引く形・頭 run。取り消し・やり直しも。RS8 の ② の口 S3)
                self._autorun.learning = self.learning   # 学習の束の版を束の post.learning.version に(F1 F6a)
                self._autorun.set_finished_hook(self.after_run)   # 画面なしの送り返しの zip(F1 F6a)
                prio_mod.watch(self._autorun)   # 後回しの仕事(評価用の一括など)は、まとめて実行と録画が無いときだけ重い処理の枠を取る(PRIO)
            return self._autorun

    def flush_sends(self):
        """届けられなかった自動の分を送り直す(受付の見回りの終わり = Intake の flush。D-SEND 2-6)。画面なしでは届けない。-> 届けた本数"""
        if self.headless:
            return 0
        ar = self.autorun
        if not ar.pools():
            return 0
        return ar.flush_pools(lambda meta: False)   # ライブの組の溜めは録画が終わったかを live の見回りが決める(ここでは古すぎる物だけ)

    def wire_learning(self):
        """machine の learningDir があれば、入口の文字起こし(編集のジョブ = human/proof/doc_jobs)も学習データを flow/learning で読む(F1 F6a。
        CLI の prepare と同じ: 置き場所を ytt/workdata・名簿・声・色に入れ、学習した用語・置換・辞書の版はその読み手から)。
        取り込みのあと(編集の set_data_dir が置き場所を決めたあと)・まとめて実行を作る前に 1 回。既定(learningDir = 作業データの根)なら何もしない。
        学習の束を作る側の PC(flow/learning.maker_pc)では束を読まずにログに 1 行(友人のアプリが向けても効かない。6d-1)
        -> 学習データの読み手か None"""
        ld, skipped = learning_mod.learning_dir_checked()
        if skipped:
            self.sup.log(skipped)
        if not ld:
            return None
        learning_mod.apply_places(ld)
        lr = learning_mod.Learning(ld, human_loader=_human_learn)
        from human.proof import doc_jobs   # 呼ぶときだけ(既定の入口では読まない)
        doc_jobs.set_learning(lr)
        self.learning = lr
        if self._autorun is not None:
            self._autorun.learning = lr
        return lr

    def after_run(self, run):
        """実行が 1 本終わって結果の束が書かれたあと(Queue の finished_hook)。画面なし(友人の PC の ②)で依頼の実行(requestId)だけ、
        送り返しの zip を <app>/outbox に組む(F1 F6a。ユーザーの PC の入口では組まない = 受け取る側)"""
        if not self.headless or not getattr(run, "request_id", None) or not getattr(run, "result_path", None):
            return None
        path = outbox_mod.build(run.result_path, self.app_dir, request_id=run.request_id,
                                log_path=os.path.join(self.sup.logs_dir, "launcher.log"))
        if path:
            self.sup.log("送り返しの zip を作りました: %s" % os.path.basename(path))
        return path

    def build_learnpack(self):
        """依頼の受付のフォルダ(intake.folder)が設定されていれば、学習の束を <フォルダ>/学習 に置く(F1 F6a。中身が変わらなければ作らない)。
        -> learnpack.build の結果か None(フォルダが無い・失敗 = ログだけ)"""
        folder = self.intake.folder()
        if not folder or not os.path.isdir(folder):
            return None
        try:
            got = learnpack_mod.build(os.path.join(folder, LEARNPACK_DIR))
        except Exception as e:   # 学習の束が作れなくても入口は止めない
            self.learnpack_last = {"error": "%s: %s" % (e.__class__.__name__, str(e)[:200])}
            self.sup.log("学習の束を置けませんでした: %s" % self.learnpack_last["error"])
            return None
        self.learnpack_last = got
        if got.get("created"):
            self.sup.log("学習の束を置きました: %s" % got.get("version"))
        return got

    def learnpack_loop(self):
        """起動の少しあとに 1 回、そのあと LEARNPACK_EVERY 秒ごとに build_learnpack(終了で止まる。画面なしでは起こさない)"""
        if self.closing.wait(LEARNPACK_FIRST):
            return
        while True:
            self.build_learnpack()
            if self.closing.wait(LEARNPACK_EVERY):
                return

    def live_activity(self):
        """② の status の live 欄: ライブ(線 D)の録画中・検出中・書き出しの途中の数(起こしたアプリの「終わったら閉じる」= どれかが 0 でなければ閉じない)。
        recording = 録画元の録画中の録画(Live.recent。数秒のキャッシュ)/ detecting = 盛り上がりの検出のワーカーが測っている録画(worker.json)/
        exporting = 書き出しの途中・まとめて実行へ渡すのを待っている書き出し(作ってあるときだけ。オフの間は作業データに何も作らない)。
        リアルタイム切り抜きがオフなら全部 0(録画元に問い合わせない)。G2b でライブが ② へ移ったら、そちらが持つ"""
        live = self.live
        out = {"recording": 0, "detecting": 0, "exporting": 0}
        if not live.enabled():
            return out
        out["recording"] = sum(1 for r in live.recent() if r.get("active") is True)
        det = live.detector
        if det.enabled():
            hb = det.heartbeat()
            if det.running(hb):
                out["detecting"] = sum(1 for x in (hb or {}).get("recordings") or [] if isinstance(x, dict))
        ex = getattr(live, "_exporter", None)
        if ex is not None:
            with ex.lock:
                out["exporting"] = sum(1 for j in ex.jobs if j.get("state") in live_export.ACTIVE or j.get("handoffWait") == "disk")   # Exporter.pending と同じ規則
        return out

    def handler_for(self, path):
        if path and self.mounts:
            p = urllib.parse.urlsplit(path).path
            for prefix, handler in self.mounts.items():
                if p == prefix or p.startswith(prefix + "/"):
                    return handler
        return PortalHandler

    def finish_request(self, request, client_address):
        # 覗けなかった(何も送らずに切った接続・壊れた要求の行)ときは入口の Handler に任せる(読んで静かに終わる)
        self.handler_for(peek_path(request))(request, client_address, self)

    def close_watchers(self):
        """裏の見張りを止める(すべて終了・入口の終了の両方から。2 回呼んでもよい)"""
        self.intake.close()   # 依頼の受付の見張りを止める(まとめて実行に入れる前に)
        self.backup.close()
        self.accuracy.close()   # 測っている子プロセスも止める
        self.live.close()     # 録画の部品の見回りを止め、録画中でなければ録画の部品も止める(録画中なら残す = 録画は続く)
        if self.analytics:
            self.analytics.close()

    def teardown(self):
        """終了の後始末(1 回だけ。2 回目からは何もしない)。画面の「すべて終了」(request_shutdown)と main の終わり(Ctrl+C・黒い画面の×も)の両方から呼ぶ。
        順番: 裏の見張り → まとめて実行(実行中の段を止める。順番待ち・実行中の実行は次の起動で続く。M5)→ 監視 → ツールを止める → 取り込んだツールの後始末。"""
        with self._teardown_lock:   # 途中で 2 つ目が来たら(「すべて終了」の後始末の最中の Ctrl+C)、終わるのを待ってから戻る
            if self._torn_down:
                return
            self._torn_down = True
            self.closing.set()
            self.close_watchers()
            if self._autorun is not None:
                self._autorun.close()
            self.sup.close()
            self.sup.stop_all()
            self.sup.unmount_all()

    def request_shutdown(self):
        """画面の「すべて終了」。この入口から起動したツールを止めてから、待ち受けを終える(serve_forever が戻る)。"""
        if self.closing.is_set():
            return
        self.closing.set()
        self.sup.log("画面から「すべて終了」が押されました")
        self.teardown()
        self.shutdown()


def make_server(start_port, sup):
    """start_port から20個のうち空いているポートで待ち受ける。入口がすでに動いていれば (None, そのポート)。
    start_port=0 は OS に空きポートを選ばせる(テスト用)。"""
    if start_port == 0:
        srv = PortalServer(("127.0.0.1", 0), sup)
        return srv, srv.server_address[1]
    for p in range(start_port, start_port + PORT_RANGE):
        r = ping(p)
        if r and r["app"] == APP_ID:
            return None, p
        if r is not None:   # 他のツールが使っている
            continue
        try:
            srv = PortalServer(("127.0.0.1", p), sup)
        except OSError:
            continue
        return srv, p
    raise SystemExit("空いているポートが見つかりません(%d〜%d)" % (start_port, start_port + PORT_RANGE - 1))


# ---------- 起動 ----------
def make_logger(path):
    """黒い画面と <作業データ>/app/logs/launcher.log に1行ずつ出す。
    黒い画面への表示は専用のスレッドに任せる: Windows の黒い画面は、文字を選択している間(簡易編集モード)は表示の書き込みが止まるので、
    監視や画面の API がその待ちに巻き込まれて固まらないように。"""
    lock = threading.Lock()
    q = queue.Queue(maxsize=1000)
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        fsio.rotate(path, LOG_MAX)
    except OSError:
        pass

    def printer():
        while True:
            msg = q.get()
            try:
                print(msg, flush=True)
            except (OSError, ValueError):
                pass
    threading.Thread(target=printer, daemon=True, name="launcher-console").start()

    def log(msg, console=True):
        """console=False: ファイルにだけ書く(同じ文を自分で標準エラーへ出すとき。画面なしで 2 回出さない)"""
        try:
            if console:
                q.put_nowait(msg)
        except queue.Full:   # 表示が長く止まっている。ファイルには残す
            pass
        with lock:
            try:
                with open(path, "a", encoding="utf-8") as f:
                    f.write("%s %s\n" % (time.strftime("%Y-%m-%d %H:%M:%S"), msg))
            except OSError:
                pass

    def flush(timeout=1.0):
        """終了の直前に、表示待ちの行を出し切る(黒い画面が止まっていれば待たない)"""
        end = time.time() + timeout
        while not q.empty() and time.time() < end:
            time.sleep(0.02)
    log.flush = flush
    return log


STOP_SIGNALS = ("SIGINT", "SIGTERM", "SIGBREAK", "SIGHUP")
_stop_requested = threading.Event()


def _set_stop_handlers(handler):
    for name in STOP_SIGNALS:
        sig = getattr(signal, name, None)
        if sig is not None:
            try:
                signal.signal(sig, handler)
            except (OSError, ValueError, RuntimeError):
                pass


def install_stop_signals():
    """Ctrl+C・黒い画面の×(Windows は SIGBREAK)・SIGTERM・SIGHUP で、子を止めて portal.json を消してから終わる。
    合図は1回だけ受け取る: 2回目(Ctrl+C の連打・×と同時の合図など)で後始末の途中に止まり、子が残るのを防ぐ。
    Windows は×で閉じてから約5秒で強制終了されるが、同じ画面の子にも同じ合図が届くので、子は自分で後始末する。"""
    def stop(_sig, _frame):
        if _stop_requested.is_set():
            return
        _stop_requested.set()
        raise KeyboardInterrupt()
    _set_stop_handlers(stop)


def ignore_stop_signals():
    """後始末の間は、追加の合図で中断されないようにする。"""
    _stop_requested.set()
    _set_stop_handlers(signal.SIG_IGN)


def parse_args(argv):
    ap = argparse.ArgumentParser(prog="server.py", description="3つのツールをまとめて起動し、入口の画面を開く")
    ap.add_argument("--port", type=int, default=DEFAULT_PORT, help="入口の画面のポート(既定 %d。使用中なら次の番号)" % DEFAULT_PORT)
    ap.add_argument("--no-open", action="store_true", help="ブラウザを開かない")
    ap.add_argument("--only", default="", help="起動するツールを絞る(例: studio,transcribe)")
    ap.add_argument("--wait-port", action="store_true", help="「起動し直す」用: --port が空くまで(最大 30 秒)待ってから待ち受ける")
    ap.add_argument("--wait-pid", type=int, default=0, help="「起動し直す」用: 前のホームの pid。これが終わるまで(最大 90 秒)待ってからポートを待つ")
    ap.add_argument("--open-path", default="/", help="最初に開く画面の場所(例: /transcribe/ = 編集)")
    ap.add_argument("--app-window", action="store_true", help="設定にかかわらず Edge のアプリの窓で開く(無ければいつものブラウザ)")
    ap.add_argument("--no-mount", action="store_true",
                    help="ツールを入口に取り込まず、以前と同じく別のプログラムとして起動する(取り込みで問題が出たときの戻し方)")
    ap.add_argument("--headless", action="store_true",
                    help="画面なし: ブラウザ・窓を開かず、依頼の受付・バックアップ・精度の自動測定などの見張りを起こさない。"
                         "準備できたら標準出力に 1 行の JSON {event: ready, port, token, pid}(ほかのアプリが子プロセスとして起こす形)")
    ap.add_argument("--parent-pid", type=int, default=0,
                    help="画面なしだけ: 起こしたアプリの pid。そのプロセスが終わるか標準入力が閉じられたら、後始末をして終わる(F1 F0-1)")
    a = ap.parse_args(argv)
    if a.parent_pid and not a.headless:
        ap.error("--parent-pid は --headless と一緒に使ってください")
    if a.parent_pid < 0:
        ap.error("--parent-pid は正の数にしてください")
    if a.headless and a.app_window:
        ap.error("--headless には --app-window を付けられません(画面を開かないため)")
    only = [x.strip() for x in a.only.split(",") if x.strip()]
    bad = [x for x in only if x not in TOOL_IDS]
    if bad:
        ap.error("--only に使えるのは %s です(%s は不明)" % (", ".join(TOOL_IDS), ", ".join(bad)))
    a.only = only
    if not re.fullmatch(r"/[A-Za-z0-9._/\-]{0,120}", a.open_path) or ".." in a.open_path or "//" in a.open_path:
        ap.error("--open-path は / で始まる英数字の場所にしてください(例: /transcribe/)")
    return a


def headless_disk_min(log):
    """画面なしの空き容量の下限(GB。この PC の設定 machine.json の diskMinGB。読めなければ既定 = flow/machine.py の DISK_MIN_GB。RS7-2 G2b)"""
    try:
        return machine_mod.get("diskMinGB")
    except (OSError, ValueError) as e:
        log("この PC の設定の diskMinGB を読めませんでした(既定の %s GB で続けます): %s" % (machine_mod.DISK_MIN_GB, e), console=False)
        return machine_mod.DISK_MIN_GB


def say_error(log, msg, headless):
    """起動しないときの読める文: launcher.log と標準エラーへ。画面なしは黒い画面への記録も標準エラーなので、表示は 1 回だけ"""
    log(msg, console=not headless)
    log.flush()
    print(msg, file=sys.stderr)


def emit_ready(out, port, token):
    """画面なしの入口: 準備できたことを標準出力に 1 行の JSON で(起こしたアプリ・CLI が読む。ASCII だけ)"""
    out.write(json.dumps({"event": HEADLESS_READY, "port": port, "token": token, "pid": os.getpid()}) + "\n")
    out.flush()


def _wait_pid_windows(pid):
    """Windows: pid のプロセスが終わるまで待つ(OpenProcess(SYNCHRONIZE) + WaitForSingleObject。psutil は使わない)。
    開けない(もう無い・別の利用者の物)ときはすぐ戻る = 親はもういないと見る"""
    import ctypes
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.OpenProcess.restype = ctypes.c_void_p
    k32.OpenProcess.argtypes = (ctypes.c_uint32, ctypes.c_int, ctypes.c_uint32)
    k32.WaitForSingleObject.argtypes = (ctypes.c_void_p, ctypes.c_uint32)
    k32.CloseHandle.argtypes = (ctypes.c_void_p,)
    h = k32.OpenProcess(0x00100000, 0, pid)   # SYNCHRONIZE
    if not h:
        return
    try:
        k32.WaitForSingleObject(h, 0xFFFFFFFF)   # INFINITE
    finally:
        k32.CloseHandle(h)


def _wait_pid_poll(pid, poll=PARENT_POLL):
    """Windows 以外: poll 秒ごとに pid の生死を見て、いなくなったら戻る"""
    while True:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return
        except OSError:   # 権限が無いだけ = まだいる
            pass
        time.sleep(poll)


def _wait_eof(stream):
    """標準入力が閉じられる(EOF)まで読み捨てる。読めなくなったときも戻る"""
    raw = getattr(stream, "buffer", stream)
    try:
        while raw.read(1):
            pass
    except (OSError, ValueError):
        pass


def watch_parent(pid, stdin, on_gone, log=None):
    """親の見張り(--parent-pid。F1 F0-1・notes:docs/design/f1-build.md (f1j)): 親のプロセスが終わるか、標準入力が閉じられたら on_gone(理由の文) を 1 回呼ぶ。
    糸を 2 本(親の待ち・標準入力)起こす(どちらも daemon)。stdin が None なら標準入力は見ない。-> 起こした糸のリスト"""
    fired = threading.Lock()

    def fire(why):
        if not fired.acquire(blocking=False):
            return
        if log:
            log(why)
        on_gone(why)

    def parent():
        (_wait_pid_windows if os.name == "nt" else _wait_pid_poll)(pid)
        fire("起こしたアプリ(pid %d)が終わったので、ホームも終了します" % pid)

    def eof():
        _wait_eof(stdin)
        fire("標準入力が閉じられたので、ホームを終了します")
    threads = [threading.Thread(target=parent, daemon=True, name="parent-watch")]
    if stdin is not None:
        threads.append(threading.Thread(target=eof, daemon=True, name="stdin-watch"))
    for t in threads:
        t.start()
    return threads


def relink_out_dirs(srv, log):
    """起動のとき 1 回: 書き出し先を変えたあとの案件の繋ぎ直し(src/manage/cases/outdirs.py の relink_out_dir。決定 3-37 の (r8o)。題では探さない)。
    .flow.lock を取ったあと・待ち受けの前・スタジオの取り込みの前に呼ぶ(スタジオの Store と同時に data.json を書かない)。
    作業データがツールの中(inplace = テスト)なら何もしない。失敗しても入口は起動する。-> 繋ぎ直した本数か None"""
    if datadir.data_root() is None:
        return None
    try:
        return outdirs_mod.relink_out_dir(placement.studio_data(srv.sup.root), datadir.studio_out_dir(srv.sup.root), log=log)
    except Exception as e:
        log("書き出し先を変えたときの案件の繋ぎ直しができませんでした: %r" % (e,))
        return None


def main(argv=None):
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="replace")
        except Exception:
            pass
    opts = parse_args(sys.argv[1:] if argv is None else argv)
    if not opts.headless:
        return _main(opts)
    for stream in (sys.stdout, sys.stderr):   # 画面なし: 読む側(起こしたアプリ)が決めた文字コードで読めるように UTF-8 に固定(既定は cp932 になる)
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    out = sys.stdout   # 画面なし: 標準出力は ready の 1 行だけ。黒い画面への記録(make_logger の print)・取り込んだツールの print は標準エラーへ
    sys.stdout = sys.stderr
    try:
        return _main(opts, ready_out=out)
    finally:
        sys.stdout = out


def _main(opts, ready_out=None):
    """起動の本体。ready_out: 画面なし(--headless)のとき ready の 1 行を書く先(元の標準出力)"""
    headless = opts.headless
    datadir.register("app", app_data_dir(ROOT))   # 同じプロセスの案件など(datadir.resolve)が同じ場所を読む
    log = make_logger(os.path.join(logs_dir_for(ROOT), "launcher.log"))
    sup = Supervisor(ROOT, only=opts.only, log=log, mounts=() if opts.no_mount else tuple(mount_mod.MOUNTS))
    if opts.wait_port:   # 「起動し直す」で起こされた: 古い入口が終わり・ポートを離すまで待つ。期限が来ても次の番号には逃げない(RS7-1 1d)
        stuck = restart_mod.wait_old_launcher(opts.port, opts.wait_pid or None)
        if stuck:
            say_error(log, stuck, headless)
            return 1
    srv, port = make_server(opts.port, sup)
    url = "http://localhost:%d%s" % (port, opts.open_path)
    if srv is None and headless:   # 画面を開かない・読める文で非 0(起こしたアプリが標準エラーを読む)
        say_error(log, HEADLESS_RUNNING % port, headless)
        return EXIT_RUNNING
    if srv is None:
        print("ホームはすでに起動しています。画面を開きます:", url)
        if not opts.no_open:
            op = appwindow_mod.Opener(app_data_dir(ROOT), fsio.atomic_write, log=log)
            if opts.app_window:
                op.force_mode = "app"
            op.open_start(url)
        return 0
    http_thread = None
    try:
        flow_lock = placement.acquire(port)   # 1 つの作業データに ② は 1 つ(.flow.lock。ほかの ② が動いていれば LockBusy で起動しない。RS6 b-B0)
    except placement.LockBusy as e:   # トレースバックにしない(読める文で非 0)。待ち受けたソケットだけ閉じる
        msg = restart_mod.BUSY_LOCK_MESSAGE % (e.info.get("pid"), e.info.get("port") or "なし")
        say_error(log, msg, headless)
        srv.server_close()
        return EXIT_RUNNING if headless else 1
    srv.headless = headless
    if headless:   # ライブ係を友人の PC の形に(スタジオなしの採用・届けない・6 時間の見回りなし・束の adopt.top・空き容量の下限。RS7-2 G2b)
        srv.live.use_headless(headless_disk_min(log))
    try:
        install_stop_signals()
        runtime.write_runtime(sup.rdir, TOOL_ID, port, VERSION)   # 書けなくても続ける(使う人はまだいない)
        log("ホーム v%s: %s (終了は画面の「すべて終了」・Ctrl+C・この黒い画面を閉じる)%s" % (VERSION, url, "(画面なし)" if headless else ""))
        log("各ツールの出力: %s" % sup.logs_dir)
        relink_out_dirs(srv, log)   # 書き出し先を変えたあとの案件の繋ぎ直し(.flow.lock の後・待ち受けの前・スタジオの取り込みの前。(r8o))
        sup.attach(srv)
        served = threading.Event()

        def serve():
            try:
                srv.serve_forever()
            finally:
                served.set()
        srv.tools_started = threading.Event()   # 取り込みが済んだ印(済む前の submit は待つ = 起動直後の CLI が「編集が動いていない」で落ちない)
        http_thread = threading.Thread(target=serve, daemon=True, name="portal-http")
        http_thread.start()   # 取り込みの準備中も画面を開けるように、先に待ち受ける
        try:
            sup.start_all()
        finally:
            srv.tools_started.set()
        sup.start_monitor()
        try:   # 学習データの置き場所(machine の learningDir。F1 F6a)。取り込みのあと・まとめて実行を作る前
            if srv.wire_learning() is not None:
                log("学習データ: %s から読みます(版 %s)" % (learning_mod.learning_dir(), srv.learning.version or "-"))
        except Exception as e:   # 読めなくても入口は動かす(今の置き場所のまま)
            log("学習データの置き場所を使えませんでした(今の置き場所のまま): %r" % (e,))
        try:   # まとめて実行を起動のときに作る: 前の起動で待ち・実行中だった実行(M5)を、ホームを開かなくても続ける
            srv.autorun
        except Exception as e:   # 作れなくても入口は動かす(画面から使うときにもう一度作る)
            log("まとめて実行を準備できませんでした: %r" % (e,))
        if not headless:   # ③④⑤ の常駐の見張りは画面なしでは起こさない(RS7-2 G5a。部品は作ってあるので API は答える)
            srv.intake.start()   # 友人からの依頼の受付(設定がオフなら何もしない。止まっていた間に届いた依頼もここで流れる)
            srv.backup.start()   # 作業データのバックアップ(設定がオフなら何もしない。起動の少しあとに、時間が来ていれば写す)
            srv.accuracy.start() # 精度の自動測定(設定がオフなら何もしない。夜の窓に手が空いていれば1日1回、src/eval/tools/eval_*.py を子プロセスで)
        srv.live.start()     # リアルタイム切り抜きの見回り(設定がオフなら何もしない。オンなら録画の部品を起こす。G2b で ② へ移るまでは入口が載せる)
        if srv.analytics and not headless:
            srv.analytics.start()   # 分析と日報(連携の設定が無ければ何もしない。新しいデータが来たら日報を作って LINE へ)
        if not headless:
            threading.Thread(target=srv.purge_trash, daemon=True, name="trash-purge").start()   # 日数を過ぎたごみ箱フォルダ(段9 9-2)
            threading.Thread(target=srv.learnpack_loop, daemon=True, name="learnpack").start()   # 学習の束を <依頼の受付のフォルダ>/学習 へ(起動の少しあとと 1 日ごと。F1 F6a)
        if opts.parent_pid:   # 親の見張り(F1 F0-1): 親が終わる・標準入力が閉じられたら「すべて終了」と同じ後始末(待ちは次の起動で続く)
            watch_parent(opts.parent_pid, sys.stdin, lambda why: threading.Thread(target=srv.request_shutdown, daemon=True).start(), log)
        if headless:   # 待ち受けて ② を準備できた = 起こしたアプリに合言葉とポートを渡す(画面は開かない)
            emit_ready(ready_out, port, srv.token)
        elif opts.app_window:   # 設定にかかわらず窓で開く(設定には保存しない)
            srv.window.force_mode = "app"
        if not opts.no_open and not headless:   # 設定が「窓」なら Edge のアプリモード、それ以外・Edge が無いときはいつものブラウザ(段階7-3)
            threading.Timer(0.8, lambda: log("画面を開きました(%s)" % {"app": "窓", "browser": "ブラウザ"}[srv.window.open_start(url)])).start()
        while not served.wait(0.5):   # 待ち受けは別のスレッド。ここは Ctrl+C などの合図を受け取るために待つ
            pass
    except KeyboardInterrupt:
        ignore_stop_signals()
        log("終了の合図を受け取りました。このホームから起動したツールを止めています…")
    finally:
        ignore_stop_signals()
        srv.teardown()   # 「すべて終了」で済んでいれば何もしない
        if http_thread is not None and http_thread.is_alive():
            srv.shutdown()
        runtime.remove_runtime(sup.rdir, TOOL_ID, port)   # 自分が書いた記録のときだけ消す(別の入口が書き直したものは残す)
        placement.release(flow_lock)   # .flow.lock を返す(自分の印のときだけ消す)
        srv.server_close()
        log("ホームを終了しました")
        log.flush()
    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
