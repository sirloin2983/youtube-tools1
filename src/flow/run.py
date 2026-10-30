"""① 自動の流れの経路(RS1-7。計画 notes:plan/done/role-restructure.md の 5-1)。

入力(配信の ID・文書の ID・動画ファイル)を、段(解析 → 採用 → 書き出し → 文字起こし → 話者分離 → パック)の順に、各ツールの公開している API を
client(call・ok)で呼んで進める。Run = 1 回の実行の状態(段・進み具合・待ちの記録の形)、Runner = 段の中身と待つ骨組み、run() = 入口の関数。
どの段も「まだ無いものだけ」作る(済んだ段は飛ばす)。中止は Cancelled、続けられない失敗は StepError。

import してよいのは標準ライブラリ・ytt・同じ flow の spec だけ(層の決まり。tests/dev/test_layering.py。埋めた候補の文 pipeline/analyze/excite.FILL_REASON も)。案件・ホームの設定・届けることを知る所は
Runner の hook(_await_tools・_checkpoint・_studio_video・_friend_length・_docs・_pick_doc・_pref・_live_auto_origin・_auto_streamer・
_after_pack・_remember_styles・_remember_doc_streamer)にして、既定は「何も知らない」安全な値にした。
_friend_length は受付(入口の AutoRunner._accept)が読む(段は束の analyze と Run.friend_plan を読む)。

順番待ちと実行の糸(_loop)・中止・状態と記録(snapshot・history・autorun-runs.jsonl)・起動し直しで戻す(autorun-active.json)・見積もりは
RS7-1 S5 の flow/runqueue.py の Queue(Runner を継ぐ)にある。src/app/autorun.py にあるもの(AutoRunner が Queue を継いで hook を埋める):
restart_info・Dropbox へ届けることと組の溜め・HTTP の ToolClient(案件(cases・txindex)・ホームの設定(prefs)・届ける部品(deliver)を読むので)。
autorun は Queue の名前を同じ名前で読み直している(テストと live.py が autorun.StepError などを使う。例外は同じ物)。

将来 batch や live の流れを移すときは flow/run/ パッケージにせず兄弟モジュールにする(__init__ は import しない決まり)。

RS6 b-0: 段は指定の束(Run.spec。run() が merge・validate して置く)を読む。各ツールの GET /api/settings は読まない
(入口の AutoRunner.build_spec が画面の設定から束を組む = ① は設定ファイルを読まない。束 → 本文は flow/spec.py の export_body・tx_opts・pack_output)。

RS7-1 S4: 束は受けたときに組む(② の口 submit。RV A1 で受付はこの 1 本。flow/runqueue.py の Queue._accept)= 待ちの間に画面の設定を変えても
その実行の中身は変わらない。束に入れない画面の値は持たない(精密・画質の上限なし・fps 30 は固定 = 決定 3-30 Q2。用語集は編集の受付が
自分の設定から読む)。受付で決めた物: 束・知らせ Run.notes(入口が画面の設定を束にするときに直した所。パックの段の文と結果の束に出す)・
友人の区間の長さ Run.friend_plan(束の analyze.length・preRatio に入れ、解析したときに Run.friend_length = 使った印)・配信者(決まれば束の
hints.streamer。決まらなければ実行中に _auto_streamer)・届ける名前の頭(封筒の deliver.tag)。

RS7-1 S3: 依頼 = 封筒(flow/envelope.py。何を入れたか・どの依頼か・届け先)+ 束(何を作るか)。段は束だけを読む。
RV A2: Run を作るのは封筒(版 2)+ 束だけ(Run.from_envelope。欄 → 封筒 + 束の差分は flow/order.py の 1 か所)。
段の並びは束の run.from・run.upto と封筒の kind・依頼の id から(mode_of = 派生の mode。記録の mode・modeLabel・溜めの鍵に使う)+ steps_of。
束から読む欄(top・ranges・weights・cut・video_tracks・speakers・engine・model・force・overwrite・on_fail)は束を読む読み取りだけの属性:
  top = adopt.top / ranges = hints.ranges / weights = analyze.w* + run.requested "weights" / cut = pack.cut + "cut" /
  video_tracks = pack.videoTracks + "videoTracks" / speakers = transcribe.diarize(人数)+ hints.people(名前と色)/
  engine・model = transcribe.engine・model + "engine"・"model" / force = run.force / overwrite = run.repack / on_fail = run.onFail
封筒の側の欄(video_id・doc_id・source_path・title・request_id・deliver_*・pool・fresh・duration・marks)は Run の属性(③ の hook が読む。
Run.envelope() が封筒の形にする)。marks・streamer・doc_id は段と hook が実行中に書く状態でもある。
待ちの記録(saved・restore)は封筒 + 束から戻す。段の始まりと終わりの時刻は steps[].startedAt・finishedAt(ミリ秒)。
ツールの仕事は self.tools(flow/tools.py の HttpTools(client) = 今の API の形・LocalTools = 入口なし)に頼む。

RS6 b-A: 採用は 1 つの段 _step_adopt(規則 F-5 は pipeline/analyze/adopt.py の 1 か所 = 区間 ∪ 人の採用 ∪ 自動の上位で上限まで。RS8 B3-2)。
RS6 b-K2: 文字起こし・パックは成果物の鍵(flow/keys)を読んで飛ばす。文字起こし = 同じ・鍵なしは飛ばす / 違えば飛ばして印 TX_DIFFER /
force(Run.force か束の run.force)なら作り直す。パック = 違えば作り直す / 同じは飛ばす / 鍵なしは触らない。
素の Runner の文書の一覧(_docs・_pick_doc の既定)は tools の docs・doc(HttpTools = GET /api/transcripts・LocalTools = 作業データを直に)。
"""
import copy
import os
import re
import subprocess
import sys
import threading
import time
import uuid

from ytt import colors, fsio as _fsio, jobs as _slots, marks as _marks, schemas as _schemas, tools as _ytools, txwords as _txwords, version as _version
from pipeline.analyze import excite as _excite   # 埋めた候補の理由の文(FILL_REASON)を数えるだけ
from . import batch as _batch   # 解析の順番の断りの種類(queued_already)
from . import url_pick as _url_pick   # URL の自動依頼の並び・縮め・heatmap の山・1 本減らす(10-30)
from . import envelope as _envelope, keys as _keys, order as _order, normalize as _norm, placement as _placement, prio as _prio, spec as _spec, tools as _tools
from .envelope import clean_pool  # noqa: F401  (src/app/autorun.py が同じ名前で読む。RS7-1 S3)
from .spec import (CUTS, LIVE_AUTO_CUT, WEIGHT_KEYS)


MODES = {"full": "解析から全部"}   # まとめて実行の形(10-19 ユーザー決定: 解析から全部だけ。人が採用した配信にも自動の上位で本数まで足す・人の 1 本はマークの行の「この後を」)
STEP_LABELS = {"analyze": "解析", "adopt": "採用(自動)", "export": "書き出し", "transcribe": "文字起こし", "pack": "パック",
               "deliver": "Dropbox へ届ける", "diarize": "話者分離", "analyze_later": "解析(あとで)", "normalize": "30fps にそろえる"}
MODE_STEPS = {"full": ("analyze", "adopt", "export", "transcribe", "pack"), "doc": ("transcribe", "pack"),
              "file": ("normalize", "transcribe"),
              "request_auto": ("analyze", "adopt", "export", "transcribe", "pack"),
              "file_auto": ("normalize", "transcribe", "pack")}
# 段 deliver(友人へ届ける)は届け先(封筒の deliver.dir)があるときだけ steps_of が足す(どの入口も同じ。送るかは注文を作る所が届け先を入れるかで決める = D-SEND 案 B3)
# 段 normalize(動画ファイルの実行の最初。opt-human 9a-1): 作業データへ写した動画を 30fps に置き換える(flow/normalize の replace=True)。
# 置き換えは元を消すので、写しを渡す受付(友人の受付 intake.submit_file = 封筒の input.normalize true)の実行だけ。ほか(ライブの書き出し・CLI)は段を持たない
NORMALIZE_STEP = "normalize"
# 友人からの依頼(src/human/friend/intake.py。notes:docs/spec/friend.md)の形。ホームの画面の「まとめて実行」の選択肢には出さない(MODES に入れない)。
# 友人の依頼はいつも ① 全自動 = パックまで作って Dropbox の 出力\ へ(② 軽く確認 = 手で置いた動画・URL の文字起こしまでの道と形 request は 10-19 に消した)。
# request_auto = 配信の URL(解析 → 上位 N 個を採用 → 書き出し → …)/ file_auto = 友人が切り抜いた動画。
# file(動画ファイルの文字起こしまで)は、② の口 POST /api/flow/submit・CLI の --spec で run.upto transcribe を頼んだときだけ
# (ライブの書き出しのあとの「文字起こしまで」= after check も 10-19 に消した = 保存済みは全自動 file_auto)
REQUEST_MODES = {"request_auto": "依頼 ① 全自動: 解析 → パック",
                 "file_auto": "依頼 ① 全自動: 文字起こし → パック", "file": "動画ファイル: 文字起こしまで"}
# 友人が時刻で指定した区間(notes:docs/spec/friend.md の 2-6): 前後に余白を足してスタジオの手動マーク(採用)にする。
# 区間が切り抜く数(top)に足りない分だけ、自動マークの上位で埋める(スタジオの /api/video/request-marks)。
# 友人の依頼の配信かは Run.friend_url(依頼の番号がある配信の実行)で見る(記録の mode の文字は分かれ目に使わない)
# 文書単位の実行(資料の git:before-1028-cleanup:docs/design/edit-tool-design.md の 12 ⑦(b)): 「編集」の履歴で選んだ文書を、行が無ければ文字起こし → パック。
# カットがある文書はカットのとおり(ユーザー決定。配信単位の実行と同じ)。パックがあるときは既定で飛ばす(overwrite で上書き)
# 状態の言葉(気が利く画面へ 段4。どの入口の画面もこの言葉で出す = snapshot の labels)
STEP_STATE_LABELS = {"wait": "待ち", "run": "実行中", "done": "済み", "skip": "飛ばした", "warn": "一部失敗", "error": "失敗"}
RUN_STATE_LABELS = {"queued": "待ち", "running": "実行中", "done": "済み", "error": "失敗", "cancelled": "中止", "nothing": "やることがありませんでした"}
NOTHING_MESSAGE = "やることがありませんでした"
TX_DIFFER = "設定が違う(force で作り直し)"   # 文字起こし済みの文書の鍵が今の設定と違うときの印(飛ばす。RS6 b-K2・決定 3-29 Q4)
PACK_DIFFER = "字幕か設定が変わったので作り直しました"   # パックの鍵が今と違うときの知らせ(作り直す。同上)
DOC_MODE = "doc"
DOC_LABEL = "文字起こし → パック"
BUSY_WAIT = 5.0        # スタジオの書き出しが別の書き出しで塞がっているときの待ち間隔
EXPORT_MAX = 50        # 1 回の実行で書き出すマークの本数の上限(残りは次の実行で拾う。段の文に残りの本数を出す)
# 流れ作業(10-21)= 書き出しの 1 本が済むたびに、その本の文字起こしを先に頼む(_tx_early_on。スイッチ PIPE_TX は 10-30 の片付けで外した)
# 解析の先回り(10-23。資料の git:before-1028-cleanup:plan/解析の先回り-設計.md): 今の実行が文字起こしの段に入る直前に、次に始まる実行の解析をスタジオの順番に頼む(Queue._prefetch_next)。
# 次の実行の番が来たら、その解析を待つ・済んでいれば飛ばす(印 = 段の prefetched)。スイッチ PREFETCH_ANALYZE は 10-30 の片付けで外した
# 30fps の作り直しと文字起こしを並べる(10-23。資料の git:before-1028-cleanup:plan/人の作業なしの候補-1023.md の 3): 動画ファイルの実行で、作り直しを裏の糸で進めながら
# 元の写しの音で文字起こしを始め、文字起こしが済んだら作り直した動画へ文書を付け替える(付け替えられなければ元の写しのまま)。
# 作り直しは映像の作り直し(GPU のエンコーダー)なので認識と取り合わない(この PC: 作り直し 15 秒 + 認識 37 秒 → 並べて 38.5 秒)。
# 音は作り直しと同じ AAC 192k を先に作って認識に渡す(audioPath。取り出した音が作り直しの動画と同じ = 結果は今と同じ。元の音のままでは評価用 23 本の
# 文書ごとの結果が揺れた = 8 本良く 9 本悪く)。スイッチ NORM_PARALLEL は 10-30 の片付けで外した
# mode post_analyze は無い(区間だけの依頼の最後の段 analyze_later がその役目。OPT-E2)。
# 待ちの記録に mode post_analyze が残っていても、MODE_STEPS に無いので restore が読み飛ばす
CANCEL_WAIT = 30.0                   # 取り消したスタジオの解析が止まるのを待つ秒(次の実行が同じ配信の解析を始められるように)
DONE_STEPS = ("done", "skip", "warn")   # 済んだ段(戻した実行では飛ばす)
RUN_ID_RE = re.compile(r"^[0-9a-f]{10}\Z")

FROM_MODE = {None: "full", "analyze": "full", "export": "full", "transcribe": DOC_MODE}   # run(from_=段) の配信の ID の入力 -> 実行の形(export = 書き出しから全部)
FROM_EXPORT_LABEL = "書き出しから全部"   # mode full で束の run.from export(解析・採用を飛ばす)の実行の札

TOOL_SETTING_KEYS = ("count", "length", "preRatio", "sensitivity", "wAudio", "wChat", "wComments", "headSec", "shape", "fill")   # パックの判定に載せる解析の設定(_pack_source)
_num = _spec.num_ok   # 扱ってよい大きさの数か(src/flow/spec.py)


def _has_captions(doc):
    """文書に残す字幕の行(文字があってカットしていない行)があるか"""
    return any(s.get("text", "").strip() and not s.get("cut") for s in doc.get("segments") or [])


def _check_note(items):
    """書き出しのあとの自動の点検(① export/outcheck)で気になる所があった本の知らせ(段の文に足す。止めない)。無ければ空の文字"""
    hit = [(i.get("file") or "").rsplit("/", 1)[-1] + ": " + "・".join(x["text"] for x in i["check"]["issues"][:2])
           for i in items if isinstance(i.get("check"), dict) and i["check"].get("issues")]
    return "。点検で気になる所 %d 本(%s)" % (len(hit), " / ".join(hit[:3])) if hit else ""


def _clip_span(media):
    """余白つき(LD-2f)で書き出した切り抜きの、動画の中のマークの区間(.clip.json の export.actualStart・range。作業用/ か隣)。
    -> (始まり, 終わり)(秒)か None(余白なし・.clip.json が無い・読めない・ネットワーク上のパス)"""
    if not isinstance(media, str) or not media or _fsio.is_network_path(media):
        return None
    try:
        clip = _schemas.find_clip(media)[0]
    except (OSError, ValueError):
        return None
    return _schemas.clip_mark_span(clip) if clip else None


class Cancelled(Exception):
    """中止(人の中止・入口の終了)"""


class StepError(Exception):
    """段を続けられない失敗(文は画面に出す)"""


JOB_STATE_JA = {"error": "失敗しました", "cancelled": "取り消されました", "skipped": "飛ばされました"}   # ツールの状態名(英語)を画面の言葉に


def _job_why(j):
    """ツールの仕事(文字起こし・パック)が終わらなかった理由の文。ツールの文があればそれ、無ければ状態名を日本語に(cancelled などを出さない)"""
    return str(j.get("error") or JOB_STATE_JA.get(j.get("state"), "理由は不明です"))


# 派生の mode -> (封筒の kind, 束の run.from, 束の run.upto)。mode_of の逆(どれか 1 つの組。テストと道具が mode から封筒 + 束を組むのに使う)
MODE_RUN = {"full": ("url", None, "pack"), "request_auto": ("url", None, "pack"), DOC_MODE: ("docs", None, "pack"),
            "file": ("file", None, "transcribe"), "file_auto": ("file", None, "pack")}
MODE_HINT = {"url": "run.from は null・analyze(頭から)か export(書き出しから)、run.upto は pack", "docs": "run.upto は pack",
             "file": "run.upto は transcribe か pack"}


def mode_of(kind, bundle, request_id=None):
    """封筒の kind + 束の run.from・run.upto + 依頼の id -> 実行の形(MODE_STEPS の鍵。記録の mode・modeLabel・届ける溜めの鍵の元)か None(合わない組)。
    url: from が export = 書き出しから(upto pack だけ → full・依頼の id があれば request_auto。段の並びは steps_of が解析・採用を外す。upto transcribe は None = 断る)/
    頭から(null・analyze)= upto pack だけ(依頼の id で request_auto か full。upto transcribe = 消した ② 軽く確認の request は None = 断る)/
    transcribe(run() の from_ = 配信の文字起こしから)= doc。docs: pack だけ(doc)。file: pack → file_auto・transcribe → file
    (② の口・CLI の束が upto transcribe を頼んだとき)(RV A2)"""
    frm, upto = bundle["run"]["from"], bundle["run"]["upto"]
    if kind == "docs":
        return DOC_MODE if upto == "pack" else None
    if kind == "file":
        return "file_auto" if upto == "pack" else "file"
    if kind != "url":
        return None
    if frm == "export":   # 書き出しから全部(10-19。段の並びは steps_of が解析・採用を外す)。文字起こしまで(transcribe)・採用後を全部(adopted)の形は 10-19 に消した
        if upto != "pack":
            return None
        return "request_auto" if request_id else "full"   # 依頼の id があれば依頼の全自動を書き出しから(届けるのは依頼)・無ければまとめて実行(D-SEND の判定を通る)
    if frm == "transcribe" and upto == "pack":
        return DOC_MODE
    if frm in (None, "analyze") and upto == "pack":
        return "request_auto" if request_id else "full"
    return None


def _gone_shape(env, spec):
    """待ちの記録の封筒 + 束が、束としては読めるのに今は無い形(消した mode)か。
    そういう記録を束なし(= 既定の頭からパックまで)で戻すと、形を変えて動いてしまう(文字起こしまでの実行が全自動になるなど)ので、Run.restore は戻さない"""
    try:
        b = _spec.validate(_spec.merge(spec))
    except (TypeError, ValueError, KeyError):
        return False
    return mode_of(env.get("kind"), b, env.get("requestId")) is None


def steps_of(mode, deliver_dir=None, ranges=0, top=None, diarize=None, normalize=False, from_=None, request=False, origin=None):
    """段の並び(鍵の並び)= MODE_STEPS[mode] + 今の付け足しの決まり(実行の段と見積もりが同じ物を使う。RV A2):
    束の run.from が export(書き出しから全部)なら解析・採用を外す(MODE_STEPS["full"] は変えない) /
    normalize(動画ファイルの最初)は normalize が真のときだけ / 届け先があればパックの後ろに deliver(文書単位は届けない)。
    チェックを外したまとめて実行(出どころ auto・届け先なし・依頼の番号なしの配信)も deliver を付ける = 送らなかった記録 unchecked を残す段(品質のカード 2-8) /
    友人の依頼の配信(request = 依頼の番号がある配信の実行)で区間が切り抜く数に足りていれば、解析なしで最後に analyze_later /
    話す人の人数(diarize)があれば文字起こしの後ろに diarize"""
    keys = list(MODE_STEPS[mode])
    if from_ == "export":
        keys = [k for k in keys if k not in ("analyze", "adopt")]
    if NORMALIZE_STEP in keys and not normalize:
        keys.remove(NORMALIZE_STEP)
    unchecked = origin == "auto" and not request and "adopt" in MODE_STEPS[mode]
    if (deliver_dir or unchecked) and "pack" in keys and mode != DOC_MODE:
        keys.append("deliver")
    if request and ranges and ranges >= (top or 0):
        if "analyze" in keys:   # 書き出しから(from export)は解析の段がもう無い
            keys.remove("analyze")   # 区間が切り抜く数に足りている: 解析なしで、その区間だけを取りに行く
        keys.append("analyze_later")   # 解析は最後(届けたあと)に順番へ入れるだけ = 友人の区間と自動の候補を比べる材料(決定 3-49 Q6。OPT-E2)
    if diarize and "transcribe" in keys:   # 話す人の人数がある(束の transcribe.diarize)
        keys.insert(keys.index("transcribe") + 1, "diarize")
    return keys


def _pins(bundle):
    """依頼が決めた項目(束の run.requested。旧い鍵 run.pinned は spec.merge が読み替える)"""
    return bundle["run"]["requested"]


PUBLIC_MAX = 50        # public に出すパック・文書の数の上限(書き出しの 1 回の上限と同じ)
PEOPLE_NAME_MAX = _order.PEOPLE_NAME_MAX   # 束の hints.people の名前の長さ(変換は flow/order.py の 1 か所。RV A1)
_people_of = _order.people_of   # 友人の「話す人」→ 束の hints.people(変換は flow/order.py)


STEP_TIMES = ("startedAt", "finishedAt")   # 段の始まりと終わりの時刻(ミリ秒。_run_steps が置く。RS7-1 S3 = 速さを測るため。無くても読める)


def _step_saved(s):
    """待ちの記録・結果の束の段の 1 つ(鍵・状態・文と、あれば時刻)"""
    out = {"key": s["key"], "state": s["state"], "detail": s["detail"]}
    out.update({k: s[k] for k in STEP_TIMES if k in s})
    return out

# 段の「飛ばすか」の判定(実行 = Runner の各段と見積もり = Queue.estimate が同じ関数を呼ぶ。RS8 OPT2。ここだけが規則の持ち主)
def analyze_verdict(has_analysis, weights_differ):
    """解析: make = 解析する / skip = 解析済みの結果を使う(依頼の重みが違えば解析し直す)"""
    return "skip" if has_analysis and not weights_differ else "make"


# 頼まれた本数に届かないとき(例: 配信の直後でチャットのリプレイが 0 件・山が 1 つだけ → 5 本のうち 1 本)
CHAT_RETRY_SEC = 3600          # チャットのリプレイを取り直すまでの間(前の解析から)
CHAT_RETRY_MAX = 3             # 見回りで取り直す回数の上限
CHAT_RETRY_FRESH = 48 * 3600   # 終わってからこの秒数までの配信だけ取り直す(48 時間)
WAS_LIVE = ("was_live", "post_live")
REDO_TEXT = {"chat": "前の解析はチャットのリプレイが無かったので解析し直します",
             "short": "前の解析は候補が %d 本に届かなかったので、足りない分を埋めて解析し直します"}


def _dict(v):
    return v if isinstance(v, dict) else {}


def chat_missing(analysis):
    """スタジオの配信の analysis で、チャットを使うつもりだった(spec.useChat)のに使えなかった(signals.chat が偽)か"""
    a = _dict(analysis)
    return _dict(a.get("spec")).get("useChat") is True and _dict(a.get("signals")).get("chat") is False


def chat_retry_ok(analysis, now):
    """チャットを取り直す意味があるか: 使えなかった・配信(was_live)が終わって CHAT_RETRY_FRESH 秒以内(終わった時刻が分からない動画は取り直さない)"""
    if not chat_missing(analysis):
        return False
    ended = stream_ended_at(analysis)
    return ended is not None and now - ended <= CHAT_RETRY_FRESH


def stream_ended_at(analysis):
    """スタジオの配信の行の analysis -> 配信が終わった時刻(epoch 秒)か None(分からない)。
    liveStatus が was_live・post_live で releaseTs(配信の始まり)と duration(長さ。秒)があれば releaseTs + duration。
    ほか(動画・ライブ中・項目なし・壊れた値)は None(① pipeline/analyze/fetch.slim_meta の項目を batch が analysis に写す)"""
    a = _dict(analysis)
    if a.get("liveStatus") not in WAS_LIVE:
        return None
    start, dur = a.get("releaseTs"), a.get("duration")
    if not (_schemas.is_num(start) and _schemas.is_num(dur)) or start <= 0 or dur <= 0:
        return None
    return float(start) + float(dur)


def redo_reason(analysis, top, marks, now):
    """解析済みでも解析し直す理由-> "chat" / "short" / None(使い回す)。
    chat = チャットが使えなかった新しい配信で、前の解析から CHAT_RETRY_SEC 秒たった(リプレイがもう揃っているかもしれない)。
    short = 前の解析は埋める数(spec.fill)が top より少なく、残っている候補(見送り以外のマーク)が top に届かない。
    解析の記録の形(spec・counts)が無い物は見ない(前の形のまま使い回す)"""
    a = _dict(analysis)
    if not isinstance(a.get("spec"), dict) or not isinstance(a.get("counts"), dict):
        return None
    at = a.get("at") / 1000.0 if _schemas.is_num(a.get("at")) else 0.0   # エポックのミリ秒(_num は 1e7 未満だけ)
    if chat_retry_ok(a, now) and now - at >= CHAT_RETRY_SEC:
        return "chat"
    fill = a["spec"].get("fill") if _num(a["spec"].get("fill")) else 0
    left = sum(_marks.pieces_of(m) for m in marks or [] if isinstance(m, dict) and m.get("status") != "rejected")   # つないだマークは元の本数
    if top and fill < top and left < top:
        return "short"
    return None


def short_why(analysis):
    """候補が足りなかった理由の文(採用の段の文と記録に残す)"""
    a = _dict(analysis)
    counts, spec = _dict(a.get("counts")), _dict(a.get("spec"))
    why = []
    if chat_missing(a):
        why.append("チャットのリプレイが使えなかった(%s 件)" % counts.get("chat", 0))
    if _num(counts.get("cands")):
        why.append("盛り上がりの山が %d 個しか見つからなかった%s" % (counts["cands"], "(しきい値の下の山で埋めても)" if spec.get("fill") else ""))
    return "・".join(why)


def adopted_ids(marks):
    """書き出す(採用したままの)マークの id の並び。空なら書き出しの段は飛ばす(書き出し済みがあれば先へ・無ければ止める)"""
    return [m["id"] for m in marks if m.get("status") == "adopted"]


def tx_verdict(has_text, force):
    """文字起こし(切り抜き・動画 1 つ): make = 文書が無いので作る / redo = force で作り直す / skip = 文書がある(鍵が違っても飛ばして印だけ。RS6 b-K2)"""
    if not has_text:
        return "make"
    return "redo" if force else "skip"


def pack_verdict(force, state, pack_exists):
    """パック(切り抜き・動画 1 つ): remake = force か鍵が違うので作り直す / make = 鍵なしでパックが無いので作る / skip = 鍵が同じ・鍵なしで既にある。
    state = 鍵の比べ(same | differ | none。force のときは見ない)。pack_exists = 既定の名前のパックが既にあるか"""
    if force or state == "differ":
        return "remake"
    if state != "same" and not pack_exists:
        return "make"
    return "skip"


def doc_pack_hint(doc):
    """文書 1 本のパック(_doc_pack。依頼の動画・ライブの切り抜き)の届けた先 {"path": 切り抜きの動画, "markId": スタジオのマーク}。
    _step_pack の hint と同じ形(path が無いと、届けたときに案件へ「届けた」が残らない = opt-manage 2a-1)。
    markId は文書に入っている .clip.json のライブの studio.mark(ライブの切り抜きでなければ "" = 友人の動画の依頼はスタジオのマークが無い)"""
    clip = doc.get("clip") if isinstance(doc.get("clip"), dict) else {}
    src = clip.get("source") if isinstance(clip.get("source"), dict) else {}
    live = src.get("live") if isinstance(src.get("live"), dict) else {}
    studio = live.get("studio") if isinstance(live.get("studio"), dict) else {}
    mark = studio.get("mark")
    return {"path": doc.get("sourcePath") or "", "markId": str(mark) if isinstance(mark, str) else ""}


class Run:
    """1 回の実行(配信・文書・動画ファイル 1 つぶん)の状態。作るのは from_envelope(封筒 + 束)だけ(RV A2)。段の並びは steps_of。
    封筒の側(何を入れたか・どの依頼か・届け先)は属性(video_id・doc_id・source_path・title・request_id・deliver_*・pool・fresh・duration・marks)に、
    何を作るかは束 Run.spec に。束から読む欄(top・ranges・cut・weights・video_tracks・speakers・engine・model・force・overwrite・on_fail)は
    束を読む読み取りだけの属性(③ の hook・public・記録の形のため)。配信者 streamer は束の hints.streamer から始まり、実行中に決まる状態でもある"""

    def __init__(self, env, bundle):
        """env = 封筒(検査済み。envelope.read の結果)・bundle = 検査済みの束(全部)。合わない組(kind と run.from・run.upto)は ValueError"""
        kind, inp, dl = env["kind"], env["input"], env["deliver"]
        self.id = env["id"] if RUN_ID_RE.match(env["id"]) else uuid.uuid4().hex[:10]
        self._kind = kind
        self.spec = copy.deepcopy(bundle)   # 指定の束(受付か run() が組んで置く。段が読む = RS6 b-0。待ちの記録には入る・public には出さない)
        self.diff = None                    # run() に別の束を渡されたとき重ね直す、この Run の差分(from_input・from_envelope が置く)
        self.mode = mode_of(kind, bundle, env["requestId"])
        if self.mode is None:
            raise ValueError("束の run.from・run.upto がこの封筒(%s)に合いません(%s)" % (kind, MODE_HINT.get(kind, "")))
        self.video_id = inp.get("videoId")
        self.title = inp["title"] or inp.get("videoId") or inp.get("docId") or os.path.basename(inp.get("path") or "")
        self.doc_id = inp.get("docId")
        self.source_path = inp.get("path")   # 依頼の動画(kind file。作業データへコピーしたもの。段 normalize が 30fps の写しに置き換える)
        self.normalize = inp.get("normalize") is True   # 動画ファイルの実行で、最初に写しを 30fps に置き換える段 normalize を持つか(上の NORMALIZE_STEP)
        self.duration = inp.get("duration")   # 受付のときに調べた配信の長さ(秒。スタジオにまだ無い配信の区間を端で切るのに使う)
        self.fresh = inp.get("fresh")         # ① 探す から: {"title", "channel"}(まだスタジオに無いかもしれない配信。解析のキューに入れるときに渡す)
        self.marks = tuple(inp["marks"]) if inp.get("marks") else None   # このマークだけ(スタジオのマークの行の「この後を」。依頼の URL は採用の段が置く)
        self.request_id = env["requestId"]   # 友人からの依頼の id(src/human/friend/intake.py)
        self.deliver_dir = dl["dir"]         # ① 全自動: パックを zip にして置く所(Dropbox の 出力\)。失敗したら理由の .txt も
        self.pool = dl["pool"]               # ライブの切り抜きの組の溜め {"key", "rid", "title", "meta"}(None = この実行の中で届ける)
        self.deliver_origin = dl["origin"]   # 届けるときの出どころ(request・auto・manual。None = 依頼の id があれば request・無ければ auto。D-SEND)
        self.deliver_tag = dl.get("tag")     # 届ける zip の名前の頭(友人のアプリの名前の形 YYYYMMDD-HHMMSS-xxxxxx。None = 依頼の id か実行の id。D-SEND)
        self.created = env["createdAt"] / 1000.0
        self.streamer = bundle["hints"]["streamer"]   # 字幕の文字の色にする配信者(照らし合わせ済みの名前。None = 決めていない・"" = 色なし)
        self.streamer_from = None  # 配信者を自動で決めたときの出どころ(doc / video / channel = 覚えた名前・auto = チャンネル名から。段5)
        self.friend_length = None          # 解析に使った「友人の区間の実績からの長さ」{"length", "preRatio"?, "file", "samples", "videos"}(使ったときだけ)
        self.friend_plan = None            # 受付で決めた友人の区間の長さ(friend_length の形 + "base" = 重ねる前の束の値。束の analyze に入れてある。RS7-1 S4)
        self.notes = []                    # 受付で束を組んだときの知らせ(入口が画面の設定を直した所。パックの段の文と結果の束に出す。RS7-1 S4)
        self.new_docs = []               # この実行で文字起こしした文書(話者分離はこれだけ。前からある文書の話者は人が直したかもしれない)
        self.norm_bg = None              # 30fps の作り直しを文字起こしと並べている間の {"thread", "res", "src", "dst", "audio"}(メモリだけ)
        self.prefetch = None             # 解析の先回り(runqueue.Queue._prefetch_next): 前の実行の間に頼んだ解析 {"qid", "at", "chat", "settings"}(メモリだけ)
        self.tx_early = {}               # 流れ作業: 書き出しの段で見た本の動画のパスの鍵 -> {"job": 先に頼んだ文字起こしのジョブ か None, "redo"}(メモリだけ)
        self.tx_before = {}              # 文字起こしを頼む直前に、動画ごとに前からあった文書(文字のある物)の id(F2。再開でこの外の文書 = この実行が作った物)
        self.packs = []                  # この実行で作ったパックのフォルダ
        self.kept_packs = []             # 鍵で飛ばして作らなかった、前からあるパックのフォルダ(結果の packs には載せる。届ける対象にはしない = packs とは別)
        self.delivered = []              # 届けたパックのフォルダ(同じものを2回置かない)
        self.pack_marks = {}             # パックのフォルダ -> {"path": 切り抜きの動画, "markId": スタジオのマーク}。友人の「要らない」で片付ける相手
        self.pack_hint = None            # _step_pack が _pack_one の直前に置く {"path", "markId"}(_pack_one が pack_marks へ移す)
        self.nothing = False       # どの段もやることが無かった(「完了」と言わない。段4 S-4)
        self.docs = []             # この実行で文字起こし・パックした文書の id(終わったら「校正を始める」で開く。段4)
        self.state = "queued"
        self.message = "順番待ち"
        self.error = ""
        self.finished = None
        self.cancel = False
        self.logged = False        # 記録のファイルに書いた(1つの実行は1回だけ書く。B-6)
        self.resumed = False       # 入口を起動し直して戻した実行(M5。始める前にツールの準備を待つ)
        self.owned = None          # 今ツールで動かしている仕事 (ツールの ID, [ジョブ・キューの id])(「起動し直す」の確かめ = restart_info。残さない)
        self.result_path = None    # 結果の束 <案件>/作業用/runs/<id>.json(終わったら flow/placement.write_result が置く。記録の 1 行の resultPath = 索引。RS6 b-B0)
        self.run_from = bundle["run"]["from"]   # 束の run.from(書き出しから全部 = export。札と段の並びが使う)
        keys = steps_of(self.mode, self.deliver_dir, len(self.ranges), self.top, bundle["transcribe"]["diarize"], self.normalize,
                        self.run_from, self.friend_url, self.deliver_origin)
        self.steps = [{"key": k, "label": STEP_LABELS[k], "state": "wait", "detail": ""} for k in keys]

    # ------------------------------------------------------------ 束から読む欄(読み取りだけ。RV A2 で Run の欄 → 束)
    def _b(self):
        return self.spec if self.spec is not None else _spec.DEFAULTS

    @property
    def top(self):
        """採用する上限の本数(束の adopt.top。配信の実行だけ)"""
        return self._b()["adopt"]["top"] if self._kind == "url" else None

    @property
    def ranges(self):
        """友人が時刻で指定した区間 [(開始, 終了)](束の hints.ranges。余白の前)"""
        return [tuple(r) for r in self._b()["hints"]["ranges"]]

    @property
    def cut(self):
        """依頼が決めたカットの方法(束の pack.cut + run.requested の cut。None = ホームの設定)"""
        b = self._b()
        return b["pack"]["cut"] if "cut" in _pins(b) and b["pack"]["cut"] in CUTS else None

    @property
    def weights(self):
        """依頼が決めた解析の重み(束の analyze.w* + run.requested の weights。None = スタジオの設定のまま)"""
        b = self._b()
        return {k: b["analyze"][k] for k in WEIGHT_KEYS} if "weights" in _pins(b) else None

    @property
    def video_tracks(self):
        b = self._b()
        return b["pack"]["videoTracks"] if "videoTracks" in _pins(b) else None

    @property
    def speakers(self):
        """友人が入れた「話す人」{"count", "names", "styles"}(束の transcribe.diarize + hints.people。人数が無ければ None)"""
        b = self._b()
        dz = b["transcribe"]["diarize"]
        if not dz:
            return None
        hp = _spec.hint_people(b)
        return {"count": dz, "names": [p["name"] for p in hp["people"]], "styles": {p["name"]: {"color": p["color"]} for p in hp["people"] if p.get("color")}}

    @property
    def engine(self):
        b = self._b()
        return b["transcribe"]["engine"] if "engine" in _pins(b) else None

    @property
    def model(self):
        b = self._b()
        return b["transcribe"]["model"] if "model" in _pins(b) else None

    @property
    def force(self):
        return self._b()["run"]["force"] is True

    @property
    def overwrite(self):
        """パックがあれば作り直す(束の run.repack)"""
        return self._b()["run"]["repack"] is True

    @property
    def on_fail(self):
        """切り抜きの1本が失敗したとき: next = 残りを続ける / stop = そこで止める(束の run.onFail)"""
        return self._b()["run"]["onFail"]

    def kind(self):
        """封筒の種類(url・file・docs)。動画ファイルの実行は文字起こしのあと doc_id も持つが file のまま"""
        return self._kind

    @property
    def friend_url(self):
        """友人の依頼の配信か(依頼の番号がある配信の実行 = 記録の mode request_auto)。区間・採用したマークの扱い・友人の区間の長さの分かれ目"""
        return self._kind == "url" and self.mode != DOC_MODE and bool(self.request_id)

    def delivers(self):
        """段 deliver を持つか(届け先がある実行。どの入口も段の並びで決まる = steps_of)"""
        return any(s["key"] == "deliver" for s in self.steps)

    def envelope(self):
        """この実行の封筒(flow/envelope.py の版 2)"""
        kind = self._kind
        if kind == "url":
            inp = {"videoId": self.video_id, "title": self.title, "duration": self.duration if _num(self.duration) and self.duration > 0 else None,
                   "fresh": {"title": str(self.fresh.get("title") or ""), "channel": str(self.fresh.get("channel") or "")} if self.fresh else None,
                   "marks": list(self.marks) if self.marks else None}
        elif kind == "file":
            inp = {"path": self.source_path, "title": self.title, "normalize": self.normalize}
        else:
            inp = {"docId": self.doc_id, "title": self.title}
        return {"id": self.id, "kind": kind, "input": inp, "requestId": self.request_id,
                "deliver": {"dir": self.deliver_dir, "pool": self.pool, "origin": self.deliver_origin, "tag": self.deliver_tag},
                "createdAt": int(self.created * 1000), "specVersion": _envelope.SPEC_VERSION}

    def _saved_spec(self):
        """待ちの記録・結果の束に残す束(実行中に決まった配信者を hints.streamer に。束が無ければ None)"""
        if self.spec is None:
            return None
        out = copy.deepcopy(self.spec)
        if self.streamer is None or _spec.key_ok("hints", "streamer", self.streamer):
            out["hints"]["streamer"] = self.streamer
        return out

    @classmethod
    def from_envelope(cls, env, spec=None):
        """封筒 + 束(変えたい所だけでもよい。None = 既定)-> 「待ち」の Run(受け口・待ちの記録から)。形が違えば理由つきの ValueError"""
        env, spec = _envelope.read(env, spec)
        kind, inp = env["kind"], env["input"]
        if kind == "live":
            raise ValueError("ライブの依頼は Run にしません(Queue.submit が live の hook へ回す)")
        b = _spec.validate(_spec.merge(spec))
        if kind == "url" and inp.get("marks") and b["run"]["from"] != "export" and not env["requestId"]:
            # 依頼の URL はこの実行で扱うマークを採用の段が置く(待ちの記録の封筒に入る)= 断らない
            raise ValueError("マークを選んだまとめて実行は書き出しから(run.from export)だけです")
        run = cls(env, b)
        run.diff = copy.deepcopy(spec) if isinstance(spec, dict) else None
        return run

    def saved(self):
        """待ちの記録(autorun-active.json)に残す形(M5)。戻すのは封筒 + 束(restore)。欄の鍵は今の形のまま(記録を読む物のため)"""
        return {"id": self.id, "videoId": self.video_id, "title": self.title, "mode": self.mode, "top": self.top, "docId": self.doc_id,
                "overwrite": self.overwrite, "streamer": self.streamer, "streamerFrom": self.streamer_from, "marks": list(self.marks) if self.marks else None,
                "fresh": self.fresh, "onFail": self.on_fail, "sourcePath": self.source_path, "requestId": self.request_id, "deliverDir": self.deliver_dir,
                "speakers": self.speakers, "videoTracks": self.video_tracks, "ranges": [list(r) for r in self.ranges], "cut": self.cut, "weights": self.weights,
                "duration": self.duration, "engine": self.engine, "model": self.model, "friendLength": self.friend_length, "deliverTag": self.deliver_tag, "deliverOrigin": self.deliver_origin,
                "pool": self.pool, "docs": list(self.docs), "newDocs": list(self.new_docs), "txBefore": copy.deepcopy(self.tx_before), "packs": list(self.packs), "keptPacks": list(self.kept_packs), "delivered": list(self.delivered),
                "packMarks": dict(self.pack_marks), "force": self.force, "normalize": self.normalize,
                "friendPlan": copy.deepcopy(self.friend_plan), "notes": list(self.notes),   # 受付で決めた物(RS7-1 S4)
                "created": self.created, "state": self.state, "message": self.message,
                "steps": [_step_saved(s) for s in self.steps],
                "envelope": self.envelope(), "spec": self._saved_spec()}   # 封筒 + 束(RS7-1 S3。起動し直しで束が消えない)

    @classmethod
    def restore(cls, d):
        """saved() の形 -> 「待ち」の Run(同じ id。済んだ段はそのまま・途中の段は待ちに)。形が違えば None(手で直した・壊れた記録は読み飛ばす)。
        戻すのは封筒 + 束だけ(RV A2)。欄から戻すのは動画ファイルの実行が文字起こしで作った文書(docId)だけ。束が合わなければ束なしで戻す(入口が組み直す)。
        封筒の無い・読めない(知らない版など)記録は戻さない"""
        if not isinstance(d, dict) or not RUN_ID_RE.match(str(d.get("id") or "")) or not isinstance(d.get("envelope"), dict):
            return None
        spec = d.get("spec") if isinstance(d.get("spec"), dict) else None
        try:
            env, spec2 = _envelope.read(d["envelope"], spec)
            try:
                run = cls.from_envelope(env, spec2)
            except ValueError:
                if spec is None or _gone_shape(env, spec2):   # 束は読めるのに今は無い形(消した mode)は、束なしで既定の形に戻さない = 戻さない
                    raise
                env2, spec3 = _envelope.read(d["envelope"])   # 束が合わない: 束なし(封筒の段の並びだけ)で戻して、入口が組み直す
                run = cls.from_envelope(dict(env, input=env["input"]), {"run": spec3.get("run", {})} if isinstance(spec3, dict) else None)
                run.spec = None
        except (TypeError, ValueError, KeyError):
            return None
        run.id = d["id"]
        if run.kind() == "file" and isinstance(d.get("docId"), str) and 0 < len(d["docId"]) <= 40:
            run.doc_id = d["docId"]   # 文字起こしで作った文書(封筒の input は動画のパスだけ)
        return cls._restore_state(run, d)

    @staticmethod
    def _restore_state(run, d):
        """saved() の形のうち実行中に決まった状態(作った物・届けた物・段)を戻す"""
        def strs(k, n=200):
            v = d.get(k)
            return [x for x in v if isinstance(x, str) and 0 < len(x) <= 1000][:n] if isinstance(v, list) else []
        if _num(d.get("created")) or (isinstance(d.get("created"), (int, float)) and not isinstance(d.get("created"), bool)):
            run.created = float(d["created"])
        sf = d.get("streamerFrom")
        run.streamer_from = sf if isinstance(sf, str) and 0 < len(sf) <= 20 else None
        run.friend_length = d.get("friendLength") if isinstance(d.get("friendLength"), dict) else None
        fp = d.get("friendPlan")
        run.friend_plan = fp if isinstance(fp, dict) and _num(fp.get("length")) else None   # 受付で決めた友人の区間の長さ(RS7-1 S4)
        run.notes = strs("notes", 20)
        run.docs, run.new_docs = strs("docs"), strs("newDocs")
        tb = d.get("txBefore") if isinstance(d.get("txBefore"), dict) else {}
        run.tx_before = {k: [x for x in v if isinstance(x, str)][:200] for k, v in list(tb.items())[:200] if isinstance(k, str) and isinstance(v, list)}
        run.packs, run.delivered = strs("packs"), strs("delivered")
        run.kept_packs = strs("keptPacks")
        pm = d.get("packMarks") if isinstance(d.get("packMarks"), dict) else {}
        run.pack_marks = {str(k): dict({"path": str(v.get("path") or ""), "markId": str(v.get("markId") or "")},
                                       **({"overlap": v["overlap"]} if isinstance(v.get("overlap"), str) else {})) for k, v in pm.items() if isinstance(v, dict)}
        old = {x.get("key"): x for x in d.get("steps") or [] if isinstance(x, dict)}
        for st in run.steps:
            o = old.get(st["key"]) or {}
            if o.get("state") in DONE_STEPS:   # 済んだ段はそのまま(続きから)。途中だった段(run)・待ちは頭から
                st["state"], st["detail"] = o["state"], str(o.get("detail") or "")[:500]
                st.update({k: o[k] for k in STEP_TIMES if type(o.get(k)) is int})   # 段の時刻(RS7-1 S3)
        run.resumed = True
        run.message = "ホームを起動し直したので、続きから進めます"
        return run

    @classmethod
    def from_input(cls, input, from_=None, spec=None):
        """run() の入力 -> 待ちの Run。{"videoId", "title"?, "top"?}(from_ で形を選ぶ = FROM_MODE)・{"docId", "title"?}(文書 → 文字起こし → パック)・
        {"path", "title"?}(動画ファイル → 文字起こし)。どれも "force"?: true = 鍵が同じ・違っても作り直す。spec = 束(変えたい所だけ。None = 既定)。
        欄 → 封筒 + 束の差分は flow/order.py。形が違えば ValueError"""
        d = input if isinstance(input, dict) else {}
        title = str(d.get("title") or "")[:120]
        force = d.get("force") is True
        if d.get("videoId"):
            if from_ not in FROM_MODE:
                raise ValueError("from は %s のどれかです" % "・".join(k for k in FROM_MODE if k))
            env, diff = _order.order("url", video_id=str(d["videoId"]), title=title, top=_spec.top_arg(d.get("top")), force=force)
            diff["run"]["from"] = from_   # 形は from_ だけで決める(束の run.from は見ない)
        elif d.get("docId"):
            env, diff = _order.order("docs", doc_id=str(d["docId"]), title=title or str(d["docId"]), force=force)
        elif d.get("path"):
            env, diff = _order.order("file", path=str(d["path"]), title=title or os.path.basename(str(d["path"])), upto="transcribe", force=force)
        else:
            raise ValueError("入力は videoId・docId・path のどれかです")
        run = cls.from_envelope(env, _spec.merge_onto(_spec.validate(_spec.merge(spec)), diff))
        run.diff = diff
        return run

    def key(self):
        """配信・文書ごとの前回の結果を引くキー"""
        if self.source_path:
            return ("file", self.source_path)
        return ("doc", self.doc_id) if self.doc_id else ("video", self.video_id)

    def step(self, key):
        return next(s for s in self.steps if s["key"] == key)

    def all_packs(self):
        """結果に載せるパック = この実行で作った物 + 鍵で飛ばした前からある物(重ねない)"""
        return list(dict.fromkeys(list(self.packs) + list(self.kept_packs)))

    def public(self):
        return {"id": self.id, "kind": "file" if self.source_path else "doc" if self.doc_id else "video", "docId": self.doc_id, "overwrite": self.overwrite,
                "force": self.force,
                "sourcePath": self.source_path, "requestId": self.request_id, "ranges": [list(r) for r in self.ranges] or None, "cut": self.cut,
                "engine": self.engine, "model": self.model,
                "friendLength": dict(self.friend_length) if self.friend_length else None,
                "videoId": self.video_id, "title": self.title, "mode": self.mode,
                "modeLabel": (FROM_EXPORT_LABEL if self.mode == "full" and self.run_from == "export" else
                              MODES.get(self.mode) or REQUEST_MODES.get(self.mode) or DOC_LABEL) +("(%d本)" % len(self.marks) if self.marks and not self.friend_url else ""), "top": self.top,
                "streamer": self.streamer, "streamerFrom": self.streamer_from, "marks": list(self.marks) if self.marks else None, "fromSearch": bool(self.fresh),
                "state": self.state, "stateLabel": RUN_STATE_LABELS["nothing" if self.nothing and self.state == "done" else self.state],
                "nothing": self.nothing, "onFail": self.on_fail, "docs": list(self.docs[:20]),
                "packs": self.all_packs()[:PUBLIC_MAX], "keptPacks": list(self.kept_packs[:PUBLIC_MAX]), "newDocs": list(self.new_docs[:PUBLIC_MAX]),   # 作ったパック・この実行で文字起こしした文書(RS7-1 S3)
                "message": self.message, "error": self.error, "created": int(self.created * 1000),
                "finished": int(self.finished * 1000) if self.finished else None, "resultPath": self.result_path,
                "steps": [dict(s, stateLabel=STEP_STATE_LABELS.get(s["state"], s["state"])) for s in self.steps]}


def _vnorm_audio(src, dst):
    """30fps の作り直しと同じ音(AAC 192k・周波数は元のまま = ytt/normalize の encode_args)だけを dst に作る。-> できたか"""
    ff = _ytools.find_ffmpeg()
    if not ff:
        return False
    try:
        r = subprocess.run([ff, "-hide_banner", "-nostdin", "-loglevel", "error", "-y", "-i", src, "-map", "0:a:0", "-vn", "-c:a", "aac", "-b:a", "192k", dst],
                           stdin=subprocess.DEVNULL, capture_output=True, timeout=600, creationflags=_ytools.no_window_flags(priority="low"))
    except (OSError, subprocess.TimeoutExpired):
        return False
    if r.returncode != 0 or not os.path.isfile(dst):
        _fsio.unlink_quiet(dst)
        return False
    return True


class Runner:
    """① の経路: 段の中身(_step_*・_doc_*・_file_*)と、ツールの仕事を待つ骨組み(_check・_wait・_call_when_free・_poll)。
    client = ツールの API(call(ツール, メソッド, パス, body) -> (HTTP の番号, JSON)・ok(同じ) -> JSON か StepError)。
    tools = 段が仕事を頼む先(flow/tools.py。既定は HttpTools(client) = 今の API の形)。
    hook の既定は「何も知らない」安全な値(入口の AutoRunner が案件・ホームの設定・届けることで埋める)"""

    def __init__(self, client, env=None, poll=1.0, sleep=None, log=None, clock=None, find_pack=None, tools=None):
        """poll = ツールの仕事を見に行く間隔(秒)。sleep・clock はテスト用。log = 1 行のログ。find_pack(動画のパス) = パックの有無(既定は「無い」)"""
        self.client, self.env, self.poll = client, env, poll
        self.tools = tools if tools is not None else _tools.HttpTools(client)
        self.sleep = sleep or time.sleep
        self.log = log or (lambda msg: None)
        self.clock = clock or time.time
        self.find_pack = find_pack or (lambda path: None)
        self.closed = False   # 入口の終了(_check が止める)
        self._chat_retry = {}   # 動画 ID -> {"item", "settings", "due", "tries"}: チャットのリプレイを取り直す待ち(メモリだけ。chat_retry_tick)
        self._chat_retry_lock = threading.Lock()
        self.live_chat = None   # hook: live_chat(動画 ID) -> ライブで取ったチャット(リプレイの形)のパス か None(入口がライブ係の chat_for を入れる。決定 3-117)

    # ------------------------------------------------------------ hook(既定 = 何も知らない。src/app/autorun.py の AutoRunner が埋める)
    def _await_tools(self, run):
        """戻した実行(M5)で、使うツールの準備を待つ。既定は待たない"""
        run.resumed = False

    def _checkpoint(self, run):
        """段の始まりと済んだとき(起動し直しで続けるための待ちの記録)。既定は残さない"""

    def _studio_video(self, vid):
        """スタジオの一覧の 1 本(元の動画の場所など)。既定は {}"""
        return {}

    def _friend_length(self):
        """友人の区間の長さの実績(解析の設定に重ねる)。既定は None = 使わない。読むのは受付(RS7-1 S4。段は Run.friend_plan を読む)"""
        return None

    def _docs(self):
        """文字起こしの文書の一覧。既定は道具の一覧(HttpTools = GET /api/transcripts の要約・LocalTools = 作業データの文書を直に。RS6 b-K2)"""
        return self.tools.docs()

    def _full_doc(self, d):
        """一覧の 1 行 -> 動画の場所と行を持つ形(要約だけの行は tools.doc で読む)か None"""
        if d is None or "sourcePath" in d:
            return d
        return self.tools.doc(d["id"])

    def _pick_doc(self, docs, video_id, mark_id, path):
        """切り抜きの文書 1 つか None。既定は道具の一覧から: 動画の名前(か配信)で絞り、新しい順に中身を読んで、動画のパスが同じ・
        か配信とマークが同じ物(manage/cases/txindex の紐づけと同じ考え。30fps の写しへの付け替えの前のパスは見ない)。RS6 b-K2"""
        want = os.path.normcase(os.path.abspath(path)) if path else ""
        name = os.path.basename(path or "")
        cands = sorted((d for d in docs if (d.get("sourceName") or os.path.basename(d.get("sourcePath") or "")) == name
                        or (video_id and d.get("videoId") == video_id)), key=lambda d: d.get("updatedAt") or 0, reverse=True)
        for d in cands:
            full = self._full_doc(d)
            if not full:
                continue
            if want and full.get("sourcePath") and os.path.normcase(os.path.abspath(full["sourcePath"])) == want:
                return full
            clip = full.get("clip") or {}
            src = clip.get("source") if isinstance(clip.get("source"), dict) else {}
            mk = clip.get("mark") if isinstance(clip.get("mark"), dict) else {}
            if video_id and mark_id and src.get("videoId") == video_id and mk.get("id") == mark_id:
                return full
        return None

    def _pref(self, key, default=None):
        """ホームの設定 autorun の値。既定は default"""
        return default

    def _live_auto_origin(self, media):
        """切り抜きがリアルタイム切り抜きの自動の採用か(M8)。既定は False"""
        return False

    def _auto_streamer(self, run, doc=None, v=None):
        """指定の無い実行の配信者を決める(段5)。既定は決めない(字幕の色なし)"""

    def _after_pack(self, run, st, prefix):
        """パックが 1 本できたとき(① 全自動はできるたびに 1 本ずつ届ける)。既定は何もしない"""

    def _pack_source(self, run, hint):
        """パックの元: {"videoId", "range": [始まり, 終わり](元の配信の秒), "cand": {"rank", "score", "origin"}, "tool": {"version", "settings"}}
        (分かる物だけ)。区間は切り抜きの .clip.json・無ければマーク。候補は解析の要約 analysis.cands とマークの自動の区間 auto0 を突き合わせる。
        友人の PC で処理したパックの判定(friendapp の .verdict.json)に、ユーザーの PC の届けた記録と同じ項目を載せるため(10-27)。失敗しても {}"""
        out = {}
        try:
            v = self._video(run)
            vid = str(run.video_id or "")
            if vid and not vid.startswith(("file:", "/")) and len(vid) <= 64:
                out["videoId"] = vid
            mark = next((m for m in v.get("marks") or [] if isinstance(m, dict) and m.get("id") == hint.get("markId")), None) or {}
            clip = _schemas.find_clip(hint["path"])[0] if hint.get("path") else None
            rng = (clip or {}).get("range") or {}
            a, b = _schemas.num(rng.get("start")), _schemas.num(rng.get("end"))
            if a is None and _schemas.num(mark.get("start")) is not None:
                a, b = _schemas.num(mark.get("start")), _schemas.num(mark.get("end"))
            if a is not None and b is not None and b > a:
                out["range"] = [round(a, 2), round(b, 2)]
            an = v.get("analysis") if isinstance(v.get("analysis"), dict) else {}
            a0 = mark.get("auto0") if isinstance(mark.get("auto0"), list) and len(mark.get("auto0")) == 2 else None
            for i, c in enumerate(an.get("cands") or []):
                if a0 and abs(float(c["start"]) - float(a0[0])) < 0.15 and abs(float(c["end"]) - float(a0[1])) < 0.15:
                    out["cand"] = dict({"rank": i + 1, "score": c.get("score")}, **({"origin": c["origin"]} if c.get("origin") else {}))
                    break
            spec = an.get("spec") if isinstance(an.get("spec"), dict) else {}
            out["tool"] = {"version": _version.VERSION,
                           "settings": {k: spec[k] for k in TOOL_SETTING_KEYS if isinstance(spec.get(k), (int, float, str)) and not isinstance(spec.get(k), bool)}}
        except (StepError, OSError, ValueError, TypeError, KeyError) as e:
            self.log("まとめて実行: パックの元を引けませんでした(%s)" % e.__class__.__name__)
        return out

    def _overlap_note(self, run, doc):
        """前の依頼・送り直しで届けた区間とのかぶりの知らせ(flow/deliveries.overlap_note)か ""。既定は届けた記録を持たない = ""(Delivery が埋める)"""
        return ""

    def _remember_styles(self, tid, styles):
        """字幕の色を文書の話者に覚える。-> 覚えたか。既定は False"""
        return False

    def _remember_doc_streamer(self, tid, name):
        """依頼で選んだ配信者を、文書の配信者として覚える。-> 覚えたか。既定は False"""
        return False

    # ------------------------------------------------------------ 待つ骨組み
    def _check(self, run):
        if run.cancel or self.closed:
            raise Cancelled()

    def _wait(self, run, seconds=None):
        self._check(run)
        self.sleep(self.poll if seconds is None else seconds)
        self._check(run)

    def _bundle(self, run):
        """この実行の束(run() が置いた物。置かれていなければ既定の束を置く。どちらも Run の欄から写した差分を重ねた物 = Run.spec)"""
        if run.spec is None:
            run.spec = _spec.merge(None)
        return run.spec

    def _force(self, run):
        """鍵が同じ・違っても作り直すか(束の run.force。Run の欄 force もここへ写っている。RS6 b-K2)"""
        return self._bundle(run)["run"]["force"] is True

    def _repack(self, run):
        """パックがあれば作り直すか(束の run.repack か run.force。Run の欄 overwrite は run.repack へ写っている)"""
        return self._bundle(run)["run"]["repack"] is True or self._force(run)

    @staticmethod
    def _tx_state(doc, path, opts):
        """切り抜き path の文書 doc の transcribe の鍵と、今の要求 opts で認識したときの材料を比べる(flow/keys)-> same | differ | none"""
        return _keys.transcribe_state(doc["id"], path, opts)

    @staticmethod
    def _tx_path_key(path):
        return os.path.normcase(os.path.normpath(str(path)))

    def _tx_mark(self, run, items):
        """文字起こしを頼む直前(F2): items = [(動画のパス, 前からある文書の id の一覧)] を覚えて待ちの記録に残す。
        子が文書を保存した直後・親が結果を見る前に終了しても、再開で「この実行が作った文書」と分かる(前からある文書の話者は変えない)"""
        for path, ids in items:
            run.tx_before[self._tx_path_key(path)] = list(ids)
        self._checkpoint(run)

    def _made_here(self, run, path, doc):
        """再開で見つけた文書 doc が、この実行で頼んだ文字起こしの成果物か(_tx_mark で覚えた外の文書)。頼んでいなければ False"""
        before = run.tx_before.get(self._tx_path_key(path))
        return before is not None and bool(doc) and doc["id"] not in before

    @staticmethod
    def _add_new_doc(run, tid):
        if tid and tid not in run.new_docs:
            run.new_docs.append(tid)

    @staticmethod
    def _keep_pack(run, media, doc=None):
        """鍵・既存で飛ばした段の成果物(前からあるパックのフォルダ・文書)を結果に載せる。作った物(run.packs)ではないので別の欄"""
        d = os.path.normpath(_keys.pack_dir(media))
        if os.path.isdir(d) and d not in run.packs and d not in run.kept_packs:
            run.kept_packs.append(d)
        if doc and doc["id"] not in run.docs:
            run.docs.append(doc["id"])

    def _pack_state(self, run, doc, media, pack_opts, v=None):
        """切り抜き media の既定のパックの鍵と、今作ったときの材料を比べる -> (same | differ | none, _pack_body の結果 か None)。
        鍵が無ければ本文を作らない(鍵の無いパックは触らない)。本文を作れなければ (none, None)。
        比べるだけなので字幕のファイルは書かない(dry。見積もりも同じ関数 = 「何も書き込まない」。指摘 2)。作るときは _pack_one が書いて作り直す"""
        def make():
            self._auto_streamer(run, doc, v)
            return self._pack_body(run, doc, media, pack_opts, dry=True)
        try:
            return _keys.pack_state(media, make)
        except StepError:
            return "none", None

    def _call_when_free(self, run, st, send, waiting, free=None):
        """send() で仕事を頼み、ツールが 409 busy(別の処理の最中)なら BUSY_WAIT 秒ごとにやり直す(待つ間は st に waiting の文)。-> (HTTP の番号, 応答)。
        free(timeout) = 器が空くまで待つ口(入口の FlowTools の export_free・pack_free。同じプロセスの ② の器なら空いたらすぐやり直す。OPT2 後半 J7)。
        None を返す・無いときは今までどおり BUSY_WAIT 秒眠る。どちらも中止は待つ前後で見る"""
        while True:
            status, res = send()
            if not (status == 409 and res.get("error") == "busy"):
                return status, res
            st["detail"] = waiting
            if free is not None:
                self._check(run)
                if free(BUSY_WAIT) is not None:
                    self._check(run)
                    continue
            self._wait(run, BUSY_WAIT)

    def _poll(self, run, owned, read, cancel=None, start=None):
        """ツールの仕事が終わるまで待つ骨組み(解析・書き出し・文字起こし・パック・「編集」のジョブで共通)。-> read() の結果
        owned: 起動し直すときに止めてよいツールの仕事(run.owned。("export", [id]) = 書き出し = 掲示板の親子の印だけ・起動し直しでは止めない)。終わったら外す。
        start(): 待つ前の投入(中止されたら、投入済みの分も cancel で取り消す)。read(): 終わったら None 以外、まだなら None(進み具合は read の中で st へ)。
        中止(Cancelled)なら cancel()(ツールの仕事を取り消す)を呼んでから上げ直す"""
        run.owned = owned
        try:
            if start is not None:
                try:
                    start()
                except Cancelled:
                    raise   # 下の except で取り消す
                except Exception:   # 投入の途中の失敗(StepError など): 投入済みの分を取り消してから上げる(取り消しの失敗で元の理由を隠さない)
                    if cancel is not None:
                        try:
                            cancel()
                        except Exception:   # noqa: BLE001
                            pass
                    raise
            while True:
                self._wait(run)
                r = read()
                if r is not None:
                    return r
        except Cancelled:
            if cancel is not None:
                cancel()
            raise
        finally:
            run.owned = None

    def _video(self, run):
        st, obj = self.tools.video(run.video_id)
        if st == 404 and run.fresh:   # ① 探す から: 解析のキューに入れるまではスタジオに無い(受け取った題名で進める)
            return {"kind": "youtube", "title": run.title}
        if st != 200:
            raise StepError(obj.get("message") or "スタジオがうまく応答しませんでした。少し待って、もう一度実行してください(済んだ段は飛ばします)")
        v = obj.get("video") or {}
        run.title = str(v.get("title") or v.get("fileName") or run.video_id)[:120]
        return v

    # ------------------------------------------------------------ 実行
    def execute(self, run):
        """1 回の実行を段の順に進める(入口の糸 autorun._loop が run() を通して呼ぶ)。中止は Cancelled・失敗は StepError を上げる"""
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
            st["startedAt"] = int(self.clock() * 1000)   # 段の時刻(RS7-1 S3。速さを測るため)
            st.pop("finishedAt", None)
            run.message = st["label"]
            self._checkpoint(run)   # どの段の途中か(M5。起動し直したらこの段から)
            if key == "transcribe":   # 書き出しが済んだ = 枠が 1 つ空く: 次の実行の解析を先に頼む(失敗しても今の実行は続ける)
                try:
                    self._prefetch_next(run)
                except Exception as e:   # noqa: BLE001
                    self.log("まとめて実行: 次の解析の先回りを頼めませんでした(%s)" % e.__class__.__name__)
            try:
                result = call(key, st)
            finally:
                st["finishedAt"] = int(self.clock() * 1000)
            if st["state"] == "run":
                st["state"] = "done"
            self._checkpoint(run)   # 段が済んだ(M5)
            if after:
                after()
            if result == "stop":   # 続けても意味がない(採用するマークが無いなど)
                for s in run.steps:
                    if s["state"] == "wait":
                        s["state"], s["detail"] = "skip", s["detail"] or "前の段で止めました"
                break
        self._finish_message(run)

    def _prefetch_next(self, run):
        """次の実行の解析の先回り(待ち行列 Queue が埋める。素の Runner = 次の実行が無いので何もしない)"""
        return None

    def _finish_message(self, run):
        """どの段も飛ばした = やることが無かった(「完了」と言わない。段4 S-4)"""
        if all(s["state"] == "skip" for s in run.steps):
            run.nothing = True
            run.message = NOTHING_MESSAGE + (": " + run.message if run.message and run.message != "完了" else "")
        elif not run.message or run.message in [s["label"] for s in run.steps]:
            run.message = "完了"

    # 解析 -------------------------------------------------------
    def _weights_differ(self, run, v):
        """依頼が決めた解析の重み(束の analyze.w* と run.pinned の weights)が、今の解析の結果の重みと違うか
        (違えば解析し直す。音量・チャットの取り込み済みのデータは使い回される)"""
        b = self._bundle(run)
        if "weights" not in _pins(b):
            return False
        spec = (v.get("analysis") or {}).get("spec") if isinstance(v.get("analysis"), dict) else None
        spec = spec if isinstance(spec, dict) else {}
        return any(not _num(spec.get(k)) or round(float(spec[k]), 1) != b["analyze"][k] for k in WEIGHT_KEYS)

    def _fill_top(self, run):
        """解析で埋める数 = 採用の上限(束の adopt.top)。採用の段の無い実行は 0(埋めない)"""
        return self._bundle(run)["adopt"]["top"] if any(s["key"] == "adopt" for s in run.steps) else 0

    def _analyze_plan(self, run, v):
        """-> (analyze_verdict の答え, 解析し直す理由 redo_reason か None)。実行の段と見積もり(Queue.estimate)が同じ物を読む"""
        verdict = analyze_verdict(bool(v.get("analysis")), self._weights_differ(run, v))
        redo = redo_reason(v.get("analysis"), self._fill_top(run), v.get("marks"), self.clock()) if verdict == "skip" else None
        return ("make" if redo else verdict), redo

    def _step_analyze(self, run, st, v):
        verdict, redo = self._analyze_plan(run, v)
        pre, run.prefetch = run.prefetch, None
        if verdict == "skip":
            st["state"], st["detail"] = "skip", "解析済み(前の結果を使います)" if run.request_id else "解析済み"
            if pre:
                st["prefetched"], st["detail"] = True, "解析済み(前の実行の間に先に始めました)"
            return None
        item = self._analysis_target(run, v)
        if pre and self._prefetch_alive(pre["qid"]):   # 先回りの解析がまだ順番にある = それを自分の仕事として待つ(済む・失敗は read が見る)
            st["prefetched"] = True
            if pre.get("chat"):
                st["chatReuse"] = True
            st["detail"] = "解析中(前の実行の間に先に始めました)"
            self._await_analysis(run, st, pre["qid"], run.video_id, "")
            settings = pre.get("settings")
        else:   # 先回りが無い・消えた・失敗した = 今の形で頼む
            settings = self._analyze_item(run, st, item, run.video_id)
        if redo:
            st["detail"] = (REDO_TEXT[redo] % self._fill_top(run) if redo == "short" else REDO_TEXT[redo]) + "。" + st["detail"]
        self._after_analysis(run, st, item, settings)
        return None

    def _after_analysis(self, run, st, item, settings):
        """解析のあと: 埋めた数を文に足す・チャットのリプレイが無い新しい配信は、見回り(chat_retry_tick)で取り直す待ちに入れる"""
        if item.get("kind") != "youtube":
            return
        a = self._video(run).get("analysis")
        fills = _dict(_dict(a).get("counts")).get("fills")
        if _num(fills) and fills > 0:
            st["detail"] += "。うち %d 件は本数に届かないので、しきい値の下の山で埋めました" % fills
        if chat_retry_ok(a, self.clock()):
            with self._chat_retry_lock:
                old = self._chat_retry.get(run.video_id) or {"tries": 0}
                self._chat_retry[run.video_id] = {"item": {"kind": "youtube", "videoId": run.video_id}, "settings": dict(settings or {}),
                                                  "due": self.clock() + CHAT_RETRY_SEC, "tries": old["tries"]}
            st["detail"] += "。チャットのリプレイがまだ無いので、%d 分後に解析し直します" % (CHAT_RETRY_SEC // 60)
            self.log("まとめて実行: %s はチャットのリプレイが無かったので、%d 分後に解析し直します" % (run.video_id, CHAT_RETRY_SEC // 60))

    def chat_retry_tick(self):
        """見回り(flow/livesession の _watch_steps。30 秒ごと)から: 時間の来た取り直しの待ちを、スタジオの解析の順番に入れる(後回しの仕事 = 空いているとき)。
        チャットが使えた・配信が古くなった・CHAT_RETRY_MAX 回やった・配信が無くなったら待ちから外す。-> 入れた数"""
        now = self.clock()
        with self._chat_retry_lock:
            due = [(vid, dict(e)) for vid, e in self._chat_retry.items() if e["due"] <= now]
        n = 0
        for vid, e in due:
            code, obj = self.tools.video(vid)
            a = _dict(_dict(obj).get("video")).get("analysis")
            if code == 404:
                why = "配信がスタジオにありません"
            elif code != 200:   # スタジオが答えない = 次の見回りで
                continue
            elif not chat_missing(a):
                why = "チャットが使えました"
            elif not chat_retry_ok(a, now):
                why = "配信が古くなりました"
            elif e["tries"] >= CHAT_RETRY_MAX:
                why = "%d 回取り直しても取れませんでした" % e["tries"]
            else:
                why = None
            if why is None:
                res = self.tools.analyze_add(dict(e["item"], prio="later"), e["settings"])
                if res.get("added"):
                    e["tries"] += 1
                    n += 1
                    self.log("まとめて実行: %s のチャットのリプレイを取り直します(%d 回目)" % (vid, e["tries"]))
            with self._chat_retry_lock:
                if why is not None:
                    self._chat_retry.pop(vid, None)
                    self.log("まとめて実行: %s のチャットの取り直しを終えました(%s)" % (vid, why))
                elif vid in self._chat_retry:
                    self._chat_retry[vid].update(tries=e["tries"], due=now + CHAT_RETRY_SEC)
        return n

    def _step_analyze_later(self, run, st, v):
        """区間だけの依頼(解析の段なし)の最後: 配信の解析をスタジオの順番に入れるだけで、終わりを待たない(友人へ届くのを遅らせない。決定 3-49 Q6)。
        解析が済めば測る道具(eval_marks の friendRanges)が友人の区間と自動の候補を比べられる。
        解析済みなら飛ばす。入れられなくても実行は失敗にしない(飛ばしたと書く)。設定は束の analyze(依頼の重みがあればそれ)"""
        if v.get("analysis"):
            st["state"], st["detail"] = "skip", "解析済み"
            return None
        try:
            res = self.tools.analyze_add({"kind": v.get("kind") or "youtube", "videoId": run.video_id}, dict(self._bundle(run)["analyze"]))
        except Exception as e:   # スタジオが止まっている・断られた = 次の機会に(友人へはもう届いている)
            st["state"], st["detail"] = "skip", "解析を順番に入れられませんでした(%s)" % e.__class__.__name__
            return None
        if res.get("added"):
            st["detail"] = "解析を順番に入れました(終わりは待ちません)"
        else:
            rej = (res.get("rejected") or [{}])[0].get("reason") or "理由不明"
            st["state"], st["detail"] = "skip", ("解析はもう順番に入っています" if _batch.queued_already(res) else "解析を順番に入れられませんでした: %s" % rej)
        return None

    def _analysis_target(self, run, v):
        """解析に渡す配信 item(本番の段と先回りで共通)"""
        item = {"kind": v.get("kind") or "youtube", "videoId": run.video_id}
        if run.fresh and item["kind"] == "youtube":   # ① 探す から: 題名・配信者はスタジオの一覧にそのまま出る(解析の前に分かっている分)
            item.update({k: run.fresh[k] for k in ("title", "channel") if run.fresh.get(k)})
        if item["kind"] == "file":
            path = self._studio_video(run.video_id).get("path")
            if not path:
                raise StepError("元の動画ファイルの場所が分かりません")
            item = {"kind": "file", "path": path}
        return item

    def _prefetch_alive(self, qid):
        """先回りの解析が順番に残っていて、失敗・取り消しでないか"""
        try:
            it = next((i for i in self.tools.analyze_items() if i.get("qid") == qid), None)
        except Exception:   # noqa: BLE001  読めない = 今の形で頼み直す
            return False
        return it is not None and it.get("status") in ("waiting", "running", "done")

    def _analysis_request(self, run, item):
        """解析の設定を組んでスタジオの順番に頼む(本番の段と先回りで共通 = 設定がずれない)。
        -> (analyze_add の答え, 送った設定, ライブのチャットを渡したか, (重みの指定, 画面で変えた設定か, 友人の長さ))"""
        # 解析の設定は束の analyze 節(入口はスタジオの画面で保存したもの = 段階7-1 から組む。RS6 b-0)。
        # 友人が指定した重みも束の analyze.w* に写っている(run.pinned の weights。ほかの解析の設定はスタジオのまま)
        b = self._bundle(run)
        saved = dict(b["analyze"])
        weights = tuple(saved[k] for k in WEIGHT_KEYS) if "weights" in _pins(b) else None
        # 友人の依頼の足りない分を自動で埋める: 自動の候補の長さを、友人が選んだ区間の長さの実績に合わせる(解析し直しの理由にはしない)。
        # 長さは受付で決めて束の analyze.length・preRatio に入れてある(RS7-1 S4。Run.friend_plan)。ここでは使った印と文だけ
        fp = run.friend_plan if run.friend_url and isinstance(run.friend_plan, dict) else None
        fl = {k: v for k, v in fp.items() if k != "base"} if fp else None
        base = dict(saved, **(fp.get("base") or {})) if fp and isinstance(fp.get("base"), dict) else saved
        own = base != _spec.DEFAULTS["analyze"]   # 既定と違う = スタジオの画面で変えた設定(重みの指定が無いときだけ文に出す。友人の長さを重ねる前の値で見る)
        if fl:
            run.friend_length = fl
        if self._fill_top(run):   # 山がしきい値を超える数が採用の上限に届かなければ、しきい値の下の山で埋める(印 fill・pipeline/analyze/excite.pick_clips)
            saved["fill"] = self._fill_top(run)
        chat = self._live_chat_file(item)
        res = self.tools.analyze_add(dict(item, chatFile=chat) if chat else item, saved)
        return res, saved, bool(chat), (weights, own, fl)

    def _analyze_item(self, run, st, item, video_id):
        """スタジオの解析のキューに入れて、終わるまで待つ(配信の解析と、依頼 ③ の動画の解析で共通)"""
        res, saved, chat, (weights, own, fl) = self._analysis_request(run, item)
        if chat:
            st["chatReuse"] = True   # 印: ライブで取ったチャットを渡した(リプレイを取らない)
        added = res.get("added") or []
        qid = added[0]["qid"] if added else None
        if not qid:
            rej = (res.get("rejected") or [{}])[0].get("reason") or ""
            if not _batch.queued_already(res):   # 同じ配信がもう順番にある = その解析を待つ(断りの code で見る。文の一致は文が変わると外れていた)
                raise StepError("解析を始められませんでした: %s" % (rej or "理由不明"))
        st["detail"] = "解析中(%s)" % ("依頼の重み(音声 %s・チャット %s・コメント %s)" % weights if weights
                                    else "スタジオで保存した解析の設定" if own else "解析の設定は既定値。スタジオの ② で設定を変えると次から使います")
        fl_note = ("。長さ %d 秒%s(友人の区間の実績から)" % (fl["length"], "・山の前 %.2f" % fl["preRatio"] if "preRatio" in fl else "")) if fl else ""
        st["detail"] += fl_note
        self._await_analysis(run, st, qid, video_id, fl_note)
        return saved   # 送った設定(チャットの取り直しが同じ設定で解析し直す)

    def _await_analysis(self, run, st, qid, video_id, fl_note):
        """解析(qid。None = 人が入れた同じ配信の解析)が終わるまで待つ。中止なら自分の入れた分だけ取り消す"""
        def read():
            items = self.tools.analyze_items()
            it = next((i for i in items if (i.get("qid") == qid if qid else i.get("videoId") == video_id)), None)
            if it is None:
                raise StepError("解析の順番から外れました(スタジオで取り消したかもしれません)。もう一度実行してください")
            st["detail"] = "%s %d%%" % (it.get("phase") or "", round((it.get("progress") or 0) * 100))
            if it.get("status") == "done":
                st["detail"] = "解析しました(候補 %s 件)" % it.get("marks", "?") + fl_note
                return True
            if it.get("status") in ("error", "cancelled", "skipped"):
                raise StepError("解析が終わりませんでした: %s" % (it.get("error") or JOB_STATE_JA.get(it.get("status"), "理由は不明です")))
            return None
        # 人が入れた解析(qid なし)を待つときは自分の仕事にしない・中止しても止めない(この実行が入れた解析だけ取り消す)
        self._poll(run, ("studio", [qid]) if qid else None, read, (lambda: self._cancel_analysis(qid)) if qid else None)

    def _live_chat_file(self, item):
        """配信の解析に渡すライブで取ったチャット(どれを渡すかはライブ係 = flow/chatreuse・live_archive が決める)。分からない・失敗は None = リプレイを取る今の形"""
        if self.live_chat is None or item.get("kind") != "youtube" or not item.get("videoId"):
            return None
        try:
            return self.live_chat(item["videoId"])
        except Exception as e:   # noqa: BLE001  使い回せなくても解析は今の形で進める
            self.log("ライブのチャットを使えませんでした(%s): %s" % (item["videoId"], e))
            return None

    def _cancel_analysis(self, qid):
        """スタジオの解析のキューの1件を取り消し(POST /api/queue/cancel)、止まるまで待つ(CANCEL_WAIT 秒まで)。
        次の実行が同じ配信の解析をキューに入れられるように・重い処理の枠を空けてから進むため。失敗しても上げない(中止の途中)"""
        try:
            self.tools.analyze_cancel(qid)
            for _ in range(int(CANCEL_WAIT / self.poll) if self.poll > 0 else 30):
                it = next((i for i in self.tools.analyze_items() if i.get("qid") == qid), None)
                if it is None or it.get("status") not in ("waiting", "running"):
                    return
                self.sleep(self.poll)
        except Exception:
            return

    # 採用 -------------------------------------------------------
    def _step_adopt(self, run, st, v):
        """採用(F-5。規則は 1 つ = pipeline/analyze/adopt.py。今は tools.request_marks の先のスタジオの store.adopt_marks が当てて保存する。RS6 b-A・RS8 B3-2):
        友人が時刻で指定した区間(前後に束の adopt.pad 秒の余白)∪ 人が採用したマーク ∪ 自動マークの点数の高い順(上限 = Run の top か束の adopt.top までの残り)。
        不採用と、区間・人の採用に重なる自動マークは除く。人が採用済みの配信の再実行でも、上限までの残りを自動で足す。
        友人の依頼(URL)は、この実行で扱うマークをその集合にする(run.marks。同じ配信の送り直しでは、前に作った切り抜き・文字起こしを使い回す)"""
        b = self._bundle(run)
        ad = b["adopt"]
        top = ad["top"]   # Run の欄 top は束の adopt.top へ写っている(RS7-1 S3)
        dur = v.get("duration") or run.duration
        body = {"id": run.video_id, "ranges": _spec.hint_ranges(b, dur), "top": top}   # 区間 = 束の hints.ranges + adopt.pad の余白
        pick = None
        if run.friend_url and not body["ranges"] and isinstance(top, int):   # 友人の URL の自動依頼(本数だけ): 最終の候補の点・縮め・heatmap の山・1 本減らす(flow/url_pick)
            top, pref, pick = _url_pick.plan(v.get("analysis"), dur, top)
            body["top"] = top
            if pref:
                body["pref"] = pref
            st["urlPick"] = pick
        if run.fresh:
            body.update({k: run.fresh[k] for k in ("title", "channel") if run.fresh.get(k)})
        res = self.tools.request_marks(body)
        rids, hids, aids = res.get("rangeIds") or [], res.get("humanIds") or [], res.get("autoIds") or []
        xids = res.get("extraIds") or []   # heatmap の山を足した 1 本(上限の外。flow/url_pick)
        added = set(res.get("added") or [])
        chosen = tuple(dict.fromkeys(rids + hids + aids + xids))
        if run.friend_url:
            run.marks = chosen
        if not chosen:
            st["state"], st["detail"] = "skip", "採用できる候補がありません"
            run.message = "採用できる候補がありませんでした"
            return "stop"
        after = (res.get("video") or {}).get("marks") if isinstance(res.get("video"), dict) else None   # 採用のあとのマーク(応答の video。無ければ前の v)
        n_of = {m.get("id"): _marks.pieces_of(m) for m in (after or v.get("marks") or []) if isinstance(m, dict)}   # つないだマークは元の本数
        new_auto = sum(n_of.get(i, 1) for i in aids if i in added)
        old_auto = sum(n_of.get(i, 1) for i in aids) - new_auto
        short = top - sum(n_of.get(i, 1) for i in rids) - sum(n_of.get(i, 1) for i in hids) - new_auto - old_auto   # 数え方は adopt.py の room と同じ
        parts = (["指定の区間 %d 個(前後に %g 秒の余白)" % (len(rids), ad["pad"])] if rids else []) + \
            (["人が採用した %d 本" % sum(n_of.get(i, 1) for i in hids)] if hids else []) + \
            (["前に自動で採用した %d 本" % old_auto] if old_auto else []) + \
            (["自動で %d 本を足しました(%s)" % (new_auto, "最終の候補の点の順" if pick and pick["final"] else "点数の高い順")] if new_auto else []) + \
            (["YouTube でよく見られている場面を 1 本足しました"] if xids else []) + \
            (["%sので 1 本減らしました" % ("3 時間以上の配信な" if pick["low"] == "long" else "チャットの無い配信な")] if pick and pick["low"] else [])
        reasons = {m.get("id"): m.get("reasons") or [] for m in v.get("marks") or [] if isinstance(m, dict)}
        fills = sum(1 for i in aids if i in added and _excite.FILL_REASON in reasons.get(i, ()))
        why = short_why(v.get("analysis")) if short > 0 else ""
        st["detail"] = "・".join(parts) + ("(うち %d 本は本数に届かないので、点数の低い山で埋めました)" % fills if fills else "") + \
            ("。候補が足りず %d 本は選べませんでした" % short if short > 0 else "") + ("(%s)" % why if why else "")   # 足りなかった理由(記録 autorun-runs.jsonl に残る)
        if not added and not run.friend_url:   # 新しく採用したものが無い(前の採用をそのまま使う)
            st["state"] = "skip"
            st["detail"] += "(新しく採用したものはありません)"
        return None

    # 書き出し ---------------------------------------------------
    def _mine(self, run, v):
        """この実行で扱うマーク(マークを選んだ実行ならそれだけ)"""
        return [m for m in v.get("marks") or [] if not run.marks or m.get("id") in run.marks]

    def _step_export(self, run, st, v):
        ids = adopted_ids(self._mine(run, v))
        if not ids:
            done = sum(1 for m in self._mine(run, v) if m.get("status") == "exported")
            st["state"], st["detail"] = "skip", ("書き出し済み %d 本(新しく採用したものはありません)" % done if done else "採用したマークがありません")
            return None if done else "stop"
        body = _spec.export_body(self._bundle(run), run.video_id, ids[:EXPORT_MAX])
        status, res = self._call_when_free(run, st, lambda: self.tools.export_start(body), "別の書き出しが終わるのを待っています",
                                           getattr(self.tools, "export_free", None))
        if status != 200:
            raise StepError("書き出しを始められませんでした: %s" % (res.get("message") or "HTTP %d" % status))
        jid = res.get("id")
        early = self._tx_early_on(run)

        def read():
            j = self.tools.export_job(jid)
            items = j.get("items") or []
            st["detail"] = ("他のツールの重い処理を待っています" if j.get("waiting")
                            else "%d / %d 本" % (sum(1 for i in items if i.get("status") == "done"), len(items)))
            if early:
                self._tx_early(run, items)
            return j if j.get("state") != "running" else None
        # owned の "export" は掲示板の親子の印だけ(ex:<jid> を親の run の下に畳む)。起動し直しは段が REDO_STEPS に無いので今までどおり断る
        try:
            items = self._poll(run, ("export", [jid]), read, lambda: self.tools.export_cancel(jid)).get("items") or []
        except BaseException:   # 中止・失敗: 先に頼んだ文字起こしも取り消す(今までどおり、書き出しが通らなければ文字起こしは動かない)
            self._tx_early_drop(run)
            raise
        done = sum(1 for i in items if i.get("status") == "done")
        bad = [i for i in items if i.get("status") == "error"]
        encs = sorted({i["encoder"] for i in items if isinstance(i.get("encoder"), str) and i["encoder"]})   # 作り方の印(友人の診断の段の detail に出る)
        st["detail"] = "%d 本を書き出しました" % done + ("(%d 本失敗)" % len(bad) if bad else "") + ("・%s" % "・".join(encs) if encs else "") + _check_note(items) + \
            ("・残りの %d 本は次の実行で書き出します(1 回 %d 本まで)" % (len(ids) - EXPORT_MAX, EXPORT_MAX) if len(ids) > EXPORT_MAX else "")
        if bad and (not done or run.on_fail == "stop"):
            self._tx_early_drop(run)
            raise StepError("書き出しに失敗しました(%d 本): %s" % (len(bad), bad[0].get("error") or ""))
        if bad:
            st["state"] = "warn"
        return None

    def _tx_early_on(self, run):
        """流れ作業にするか: 配信の実行・この後に文字起こしの段が待っている"""
        return not run.source_path and not run.doc_id and any(
            s["key"] == "transcribe" and s["state"] == "wait" for s in run.steps)

    def _tx_early(self, run, items):
        """流れ作業: 書き出しの済んだ本の文字起こしを、残りの書き出しを待たずに頼む。順番(GPU は同時に 1 つ)は文字起こしの器の糸 1 本と SLOTS が守る。
        頼むかは文字起こしの段と同じ判定(_made_here・tx_verdict)。頼まない本は文字起こしの段がいつもどおり扱う。
        頼めなかったとき(例外)は覚えるだけにして、文字起こしの段が今の形で頼む"""
        new = [i for i in items if i.get("status") == "done" and isinstance(i.get("path"), str) and i["path"]
               and self._tx_path_key(i["path"]) not in run.tx_early and os.path.isfile(i["path"])]
        if not new:
            return
        try:
            docs, opts, tx = self._docs(), self._tx_opts(run), run.step("transcribe")
        except Exception as e:   # noqa: BLE001  一覧を読めなくても書き出しは続ける(この本は文字起こしの段が今の形で頼む)
            for i in new:
                run.tx_early[self._tx_path_key(i["path"])] = {"job": None, "redo": False}
            self.log("流れ作業: 文字起こしを先に頼めませんでした(文書の一覧): %s" % e)
            return
        for i in new:
            path, key = i["path"], self._tx_path_key(i["path"])
            run.tx_early[key] = {"job": None, "redo": False}
            try:
                doc = self._pick_doc(docs, run.video_id, i.get("id"), path)
                verdict = "skip" if self._made_here(run, path, doc) else tx_verdict(bool(doc), self._force(run))
                if verdict not in ("make", "redo"):
                    continue
                self._tx_mark(run, [(path, [doc["id"]] if doc else [])])
                job = self.tools.transcribe_start(dict(opts, sourcePath=path), bundle=self._bundle(run))
            except Exception as e:   # noqa: BLE001  先に頼めなくても、文字起こしの段が今の形で頼む
                self.log("流れ作業: 文字起こしを先に頼めませんでした(%s): %s" % (os.path.basename(path), e))
                continue
            run.tx_early[key] = {"job": job, "redo": verdict == "redo"}
            tx["early"] = tx.get("early", 0) + 1   # 印: 書き出しの最中に先に頼んだ本数と最初の時刻(記録の steps[] に残る)
            tx.setdefault("earlyAt", int(self.clock() * 1000))
            tx["detail"] = "書き出しの済んだ %d 本を先に始めています" % tx["early"]

    def _tx_early_drop(self, run):
        """先に頼んだ文字起こしを取り消す(書き出しの段が中止・失敗で終わったとき)"""
        for e in run.tx_early.values():
            if e.get("job"):
                try:
                    self.tools.transcribe_cancel(e["job"])
                except Exception:   # noqa: BLE001  取り消しの失敗で元の理由を隠さない
                    pass
        run.tx_early.clear()
        try:
            tx = run.step("transcribe")
        except StopIteration:
            return
        if tx.get("early"):
            tx["detail"] = ""

    # 文字起こし -------------------------------------------------
    def _clips(self, v, run=None):
        return [m for m in (self._mine(run, v) if run else v.get("marks") or []) if m.get("status") == "exported" and isinstance(m.get("path"), str) and m["path"]
                and os.path.isfile(m["path"])]

    def _step_transcribe(self, run, st, v):
        clips = self._clips(v, run)
        if not clips:
            st["state"], st["detail"] = "skip", "書き出した切り抜きがありません"
            return "stop"
        docs = self._docs()
        opts = self._tx_opts(run)
        early = [e for e in run.tx_early.values() if e.get("job")]   # 書き出しの最中に先に頼んだ分(流れ作業)は、そのジョブを待つ
        todo, differ, redo, before = [], 0, sum(1 for e in early if e["redo"]), []
        for m in clips:   # 文書のある切り抜きは鍵を見る(RS6 b-K2): 同じ・鍵なし = 飛ばす / 違う = 飛ばして印 / force = 作り直す(新しい文書。人の直しは引き継ぐ)
            if (run.tx_early.get(self._tx_path_key(m["path"])) or {}).get("job"):
                continue
            doc = self._pick_doc(docs, run.video_id, m.get("id"), m["path"])
            made = self._made_here(run, m["path"], doc)   # 再開: 終了の前にこの実行が作った文書(F2)は作り直さず、話者の判別の対象に
            verdict = "skip" if made else tx_verdict(bool(doc), self._force(run))
            if verdict in ("make", "redo"):
                todo.append(m)
                redo += verdict == "redo"
                before.append((m["path"], [doc["id"]] if doc else []))
            else:
                if doc["id"] not in run.docs:
                    run.docs.append(doc["id"])   # 飛ばした文書も結果に載せる
                if made:
                    self._add_new_doc(run, doc["id"])
                else:
                    differ += self._tx_state(doc, m["path"], opts) == "differ"
        note = ("。うち %d 本は%s" % (differ, TX_DIFFER)) if differ else ""
        if not todo and not early:
            st["state"], st["detail"] = "skip", "%d 本とも文字起こし済み" % len(clips) + note
            return None
        jobs = [e["job"] for e in early]   # 入れたジョブ(同じリストに足していく = 起動し直すときに止めてよい仕事 run.owned)
        run.tx_early.clear()
        if todo:
            self._tx_mark(run, before)

        def submit():
            for m in todo:
                self._check(run)
                jobs.append(self.tools.transcribe_start(dict(opts, sourcePath=m["path"]), bundle=self._bundle(run)))

        def read():
            all_jobs = {j.get("id"): j for j in self.tools.jobs()}
            mine = [all_jobs.get(j) or {"state": "error", "error": "文字起こしのジョブが見つかりません"} for j in jobs]
            fin = [j for j in mine if j.get("state") in ("done", "error", "cancelled")]
            cur = next((j for j in mine if j.get("state") not in ("done", "error", "cancelled", "queued")), None)
            st["detail"] = "%d / %d 本" % (len(fin), len(jobs)) + (" ・ %s %d%%" % (cur.get("phase") or "", round((cur.get("progress") or 0) * 100)) if cur else "")
            return mine if len(fin) == len(jobs) else None

        def cancel():
            for j in jobs:
                self.tools.transcribe_cancel(j)
        mine = self._poll(run, ("transcribe", jobs), read, cancel, start=submit)
        ok = [j for j in mine if j.get("state") == "done"]
        bad = [j for j in mine if j.get("state") != "done"]
        run.docs += [j["tid"] for j in ok if j.get("tid") and j["tid"] not in run.docs]
        for j in ok:
            self._add_new_doc(run, j.get("tid"))
        st["detail"] = "%d 本を文字起こししました" % len(ok) + ("(%d 本失敗)" % len(bad) if bad else "") + \
            ("。うち %d 本は作り直し(force)" % redo if redo else "") + note + "。字幕の校正は「編集」の 1 文字起こしで"
        if bad and (not ok or run.on_fail == "stop"):
            raise StepError("文字起こしに失敗しました(%d 本): %s" % (len(bad), _job_why(bad[0])))
        if bad:
            st["state"] = "warn"
        return None

    # パック -----------------------------------------------------
    def _edit_keeps(self, doc):
        """「編集」のカット(残す区間の秒。接している区間 = 分割しただけの所は1つに)と rev。無い・読めなければ (None, 0)"""
        status, res = self.tools.edit(doc["id"])
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

    def _pack_settings(self, run):
        """パックの作り方(束の pack 節 = 入口では編集の設定の 3 パック のタブと同じ値。気が利く画面へ 段4):
        行から作るときの端の広げ方(rowEdge)・Text+ の置き先(fps・大きさ)・1段の文字数(縦横に合わせる)・話者の色・音量・無音で削るときの値(cutSilence)。
        fps は固定の 30(素材は 30fps にそろえる = Q1・決定 3-30 Q2)。知らせ = 受付で入口が設定を束にするときに直した所(Run.notes。
        行からの設定の形が変なら既定で作った、など)。-> (rowEdge, output に足すもの, cutSilence, 知らせ)"""
        row_edge, wrap_out, cut_silence = _spec.pack_output(self._bundle(run))
        return row_edge, wrap_out, cut_silence, list(run.notes)

    def _cut_method(self, run=None):
        """カットを決めていない文書のカットの方法(束の pack.cut。入口はホームの設定 autorun.cut から。既定はカットしない)"""
        return (self._bundle(run) if run is not None else _spec.DEFAULTS)["pack"]["cut"]

    def _speaker_styles(self, run):
        """友人が指定した人ごとの字幕の見た目(束の hints.people の色。Run の欄 speakers の styles もここへ写っている)-> {名前: {"color": "#RRGGBB"}}(無ければ {})。
        色は画面・Lua に入るので、ここでも 16 進 6 桁だけにそろえ直す(束の検査を通ってきたはずだが、実行の作り手がほかにも増えたときのため)"""
        out = {}
        for p in _spec.hint_people(self._bundle(run))["people"]:
            hx = colors.norm_hex(p["color"]) if isinstance(p.get("color"), str) else None
            if p["name"] and hx:
                out[p["name"]] = {"color": hx}
        return out

    def _pack_body(self, run, doc, media, pack_opts, dry=False):
        """1本のパックの要求の本文(cut2resolve の POST /api/build。上書き force は送る直前に足す)。「編集」でカットを決めてあればそのとおり
        (3 パック のタブのパックと同じ中身)、無ければ文字起こしの行だけを残す規則(preset transcript-rows)など。-> (本文, 残す区間 か None, カットの rev)。
        dry=True: 字幕の受け渡しの JSON を書かずに中身だけ作り、本文の "contents" に入れる(spec の transcript は None。鍵の比べ・見積もり用 = 送れない本文)"""
        row_edge, wrap_out, cut_silence = pack_opts[:3]   # fps は固定の 30(画面の packFps は読まない)
        contents = {}

        def transcript():
            if not dry:
                return self.tools.transcript_file(doc["id"]).get("path")
            data = self.tools.transcript_data(doc["id"])
            if data is None:
                raise StepError("パックに渡す文字のある行がありません")
            contents["transcript"] = data
            return None
        keeps, rev = self._edit_keeps(doc)
        if keeps:
            captions = _has_captions(doc)
            tr = {"path": transcript()} if captions else {}
            spec = dict({"video": media, "keeps": keeps}, **({"transcript": tr.get("path")} if captions else {}))
            body = {"spec": spec, "output": dict({"textplus": captions, "copyVideo": True}, **wrap_out)}
        elif not _has_captions(doc):   # 文字のある行が無い(声の無い切り抜き・BGM だけ)= 字幕なしで区間の全体をパックに(行が無いからと 1 本落とさない。10-23)
            span = _clip_span(media) or (0.0, _ytools.media_duration(media) or 0.0)
            body = {"spec": {"video": media, "keeps": [[float(span[0]), float(span[1])]]}, "output": dict({"textplus": True, "copyVideo": True}, **wrap_out)}   # Text+ の字幕を作らずに動画とカットだけ(pack.build_pack。10-23 まとめ役の決定)
        else:   # カットを決めていない文書: カットの方法(ホームの設定。rows = 行から・none = カットしない・silence = 無音で削る)
            tr = {"path": transcript()}
            # 友人が選んだカット(① の依頼)・リアルタイム切り抜きの live.auto.cut(M2)= 束の pack.cut + run.pinned の cut。
            # 無ければ、自動の採用の切り抜きは区間の全体(M8)、ほかはホームの設定(束の pack.cut)
            b = self._bundle(run)
            method = (b["pack"]["cut"] if "cut" in _pins(b) else None) or \
                (LIVE_AUTO_CUT if run.source_path and self._live_auto_origin(media) else self._cut_method(run))
            if method == "none":   # 動画全体(削る区間なし)。カット済の行の字幕も消さない
                spec = {"video": media, "transcript": tr.get("path"), "mode": "list", "listKind": "drop", "listText": "", "dropCutRows": False, "minLen": 0}
            elif method == "silence":   # 無音で削る(値は編集の設定 cutSilence。無ければ cut2resolve の既定)
                spec = {"video": media, "transcript": tr.get("path"), "mode": "silence", "silence": cut_silence}
            elif method == "tidy":   # 無音を詰める(① pipeline/pack/tidy。言葉は削らない。材料 = 文字起こしの単語の時刻。無ければ区間の全体)
                spec = {"video": media, "transcript": tr.get("path"), "mode": "tidy", "words": _txwords.read_words(doc["id"]) or []}
            else:
                spec = {"video": media, "transcript": tr.get("path"), "preset": "transcript-rows"}
                if isinstance(row_edge, (bool, dict)):
                    spec["rowEdge"] = row_edge
            if self._bundle(run)["pack"].get("snapEdges") is True:   # 両端を話の切れ目へ詰める(LD-2c。束の pack.snapEdges = スイッチ。「編集」のカットには付けない)
                spec["snapEdges"] = True
            span = _clip_span(media)
            if span:   # 余白つきの動画(LD-2f): タイムラインはマークの区間から(snapEdges なら余白の中の切れ目へ外へも寄せる)。「編集」のカットには付けない
                spec["clipRange"] = list(span)
            body = {"spec": spec, "output": dict({"textplus": True}, **wrap_out)}
        b = self._bundle(run)
        if "videoTracks" in _pins(b):   # 友人が選んだ映像トラックの数(字幕はその上のトラック。1 でも書く = 今の要求の本文のまま)
            body["output"]["videoTracks"] = b["pack"]["videoTracks"]
        self._auto_streamer(run, doc)
        if run.streamer:   # 字幕の文字を配信者のメンバーカラーに(cut2resolve が同じ規則で照らし合わせる)
            body["output"]["streamer"] = run.streamer
        styles = self._speaker_styles(run)
        if styles:   # 友人が指定した話者ごとの字幕の色(古い cut2resolve は知らない鍵を読み飛ばす。空なら鍵ごと付けない = 今までと同じ要求)
            body["output"]["speakerStyles"] = styles
        if dry:
            body["contents"] = contents
        return body, keeps, rev

    def _pack_one(self, run, st, doc, media, pack_opts, force=False, prefix="", built=None):
        """1本のパックを cut2resolve で作る(本文は _pack_body。built = 鍵を比べるときに作った本文。字幕を書いていない(dry)ので作り直す)。
        -> ("made", カットのとおりか) か ("exists", False)(同じ名前のパックがあり force でない)"""
        body, keeps, rev = built if built and "contents" not in built[0] else self._pack_body(run, doc, media, pack_opts)
        if force:
            body["output"]["force"] = True
        status, res = self._call_when_free(run, st, lambda: self.tools.pack_start(body), prefix + "cut2resolve の別の処理が終わるのを待っています",
                                           getattr(self.tools, "pack_free", None))
        if status == 409 and res.get("error") == "exists":
            return "exists", False
        if status != 200:
            raise StepError("パックを作れませんでした: %s" % (res.get("message") or "HTTP %d" % status))
        jid = (res.get("job") or {}).get("id")

        def read():
            j = self.tools.pack_job(jid)
            if j.get("state") != "running":
                return j
            if j.get("message"):
                st["detail"] = prefix + j["message"]
            return None
        j = self._poll(run, ("cut2resolve", [jid]), read, lambda: self.tools.pack_cancel(jid))
        if j.get("state") != "done":
            err = j.get("error")
            raise StepError("パックを作れませんでした: %s" % ((err.get("message") if isinstance(err, dict) else err) or _job_why(j)))
        r = j.get("result") or {}
        out = os.path.normpath(r["outDir"]) if r.get("outDir") else ""   # 届けた印(run.delivered)と同じ書き方にそろえる
        if out and out not in run.packs:
            run.packs.append(out)   # ① 全自動で Dropbox へ届けるもの
            hint = dict(run.pack_hint or {})
            run.pack_marks[out] = {k: hint[k] for k in ("path", "markId") if k in hint}   # どの切り抜き・どのマークのパックか(_step_pack が hint を置く。友人の「要らない」で引く)
            run.pack_marks[out].update(self._pack_source(run, hint))   # 元の配信・区間・候補の印・版と設定(友人の判定に載せる。10-27)
            note = self._overlap_note(run, doc)
            if note:
                run.pack_marks[out]["overlap"] = note   # 依頼をまたいだ区間のかぶり(段の文・届ける .meta.json の overlapNote)
                run.pack_overlaps = getattr(run, "pack_overlaps", 0) + 1
            run.pack_hint = None
            self._after_pack(run, st, prefix)   # ① 全自動: できるたびに 1 本ずつ届ける(全部を待たない。AutoRunner)
        if keeps:   # 作った記録(packRev)を「編集」に残す(カット・字幕を直したら「作り直し」と知らせるため)。残せなくてもパックはできている
            self.tools.record_pack({"id": doc["id"], "rev": rev, "docUpdatedAt": int(doc.get("updatedAt") or 0),
                                    "dir": r.get("outDir") or "", "files": [f.get("name") for f in r.get("files") or [] if isinstance(f, dict)]})
        return "made", bool(keeps)

    def _step_pack(self, run, st, v):
        clips = self._clips(v, run)
        docs = self._docs()
        opts = self._pack_settings(run)
        force_all = self._repack(run)
        todo, no_tx, made, stale = [], 0, 0, 0
        for m in clips:   # パックの鍵(RS6 b-K2): 違う(字幕が新しい・設定が違う)= 作り直す / 同じ = 飛ばす / 鍵なし = 今のまま(無ければ作る・あれば上書きのときだけ)
            doc = self._pick_doc(docs, run.video_id, m.get("id"), m["path"])
            if not doc:
                no_tx += 1
                continue
            state, built = ("none", None) if force_all else self._pack_state(run, doc, m["path"], opts, v)
            verdict = pack_verdict(force_all, state, bool(self.find_pack(m["path"])))
            if verdict == "remake":
                todo.append((m, doc, True, built))
                stale += state == "differ"
            elif verdict == "make":
                todo.append((m, doc, False, built))
            else:
                self._keep_pack(run, m["path"], doc)   # 飛ばした(パック済み)分も結果に載せる
        if not todo:
            st["state"], st["detail"] = "skip", ("パック済み(「パックがあれば作り直す(上書き)」を選ぶと作り直します)" if clips and not no_tx else "文字起こしのある切り抜きがありません")
            return None
        skipped, failed, by_edit = [], [], 0
        self._auto_streamer(run, todo[0][1] if todo else None, v)
        for i, (m, doc, force, built) in enumerate(todo, 1):
            self._check(run)
            prefix = "%d / %d 本 ・ " % (i - 1, len(todo))
            st["detail"] = prefix.rstrip(" ・ ")
            try:
                run.pack_hint = {"path": m["path"], "markId": str(m.get("id") or "")}
                res, cut = self._pack_one(run, st, doc, m["path"], opts, force=force, prefix=prefix, built=built)
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
            ("。前のパックを上書きしました" if force_all and not run.request_id else "") + \
            ("。うち %d 本は%s" % (stale, PACK_DIFFER) if stale else "") + "。字幕を校正したら「編集」のパックのタブで作り直してください"
        if skipped:
            st["detail"] += "。同じ名前のパックがあるので上書きしなかったもの: %s" % "・".join(skipped[:5])
        if failed:
            st["state"] = "warn"
            st["detail"] += "。失敗した %d 本: %s" % (len(failed), "・".join(failed[:3]))
        for n in opts[3]:
            st["detail"] += "。" + n
        if getattr(run, "pack_overlaps", 0):
            st["detail"] += "。前に届けた切り抜きと区間が重なる %d 本(届ける情報と友人の画面に出します)" % run.pack_overlaps
        if run.streamer_from:   # 自動で入れた配信者は進み具合に出す(コラボで相手の色になることがあるため。段5)
            st["detail"] += "。字幕の色: %s(%s)" % (run.streamer, "自動: チャンネル名から" if run.streamer_from == "auto" else "前回の名前")
        return None

    # 文書単位の実行(⑦(b)) -------------------------------------
    def _doc(self, run):
        d = self._full_doc(next((x for x in self._docs() if x["id"] == run.doc_id), None))
        if not d:
            raise StepError("文書が見つかりません(消した可能性があります)")
        run.title = d["title"] or run.title
        src = d.get("sourcePath") or ""
        if not src or not os.path.isfile(src):
            raise StepError("元の動画が見つかりません(移動・削除した可能性があります)")
        if d["id"] not in run.docs:   # 文書単位の実行も結果に文書を出す(RS7-1 S3。入口に頼んだ CLI の packs・artifacts が空にならないように)
            run.docs.append(d["id"])
        return d

    def _tx_opts(self, run):
        """文字起こしの要求の設定の部分(束から = flow/spec.py の tx_opts。入口では「編集」の設定のうち文字起こしの項目 = 画面から文字起こしするときと同じ値)"""
        return _spec.tx_opts(self._bundle(run))

    def _wait_job(self, run, jid, st=None, what="文字起こし"):
        """「編集」のジョブ 1 つが終わるまで待つ(st があれば進み具合を出す)。中止されたらジョブを取り消して上げる。-> 終わったジョブ"""
        def read():
            j = next((x for x in self.tools.jobs() if x.get("id") == jid),
                     {"state": "error", "error": "%sのジョブが見つかりません" % what})
            if j.get("state") in ("done", "error", "cancelled"):
                return j
            if st is not None:
                st["detail"] = "%s %d%%" % (j.get("phase") or "", round((j.get("progress") or 0) * 100))
            return None
        return self._poll(run, ("transcribe", [jid]), read, lambda: self.tools.transcribe_cancel(jid))

    def _doc_transcribe(self, run, st):
        doc = self._doc(run)
        if tx_verdict(bool(doc["count"]), False) == "skip":   # 文書単位は force でも作り直さない
            if self._made_here(run, doc["sourcePath"], doc):   # 再開: 終了の前にこの実行が文字を入れた(F2)
                self._add_new_doc(run, doc["id"])
            st["state"], st["detail"] = "skip", "文字起こし済み"
            return None
        self._tx_mark(run, [(doc["sourcePath"], [])])   # 空の文書に入れる = 文字が入ればこの実行の成果物
        jid = self.tools.transcribe_start(dict(self._tx_opts(run), sourcePath=doc["sourcePath"], intoDoc=doc["id"]), bundle=self._bundle(run))
        j = self._wait_job(run, jid, st)
        if j.get("state") != "done":
            raise StepError("文字起こしに失敗しました: %s" % _job_why(j))
        self._add_new_doc(run, doc["id"])   # この実行で文字起こしした文書(public の newDocs)
        st["detail"] = "文字起こししました。字幕の校正は「編集」の 1 文字起こしで"
        return None

    def _doc_pack(self, run, st):
        doc = self._doc(run)
        opts = self._pack_settings(run)
        force = self._repack(run)
        state, built = ("none", None) if force else self._pack_state(run, doc, doc["sourcePath"], opts)   # パックの鍵(RS6 b-K2。_step_pack と同じ)
        if pack_verdict(force, state, bool(self.find_pack(doc["sourcePath"]))) == "skip":
            self._keep_pack(run, doc["sourcePath"])
            st["state"], st["detail"] = "skip", "パック済み(「作り直す」を選ぶと上書きします)"
            return None
        run.pack_hint = doc_pack_hint(doc)   # 届けた先(_step_pack と同じ形。無いと届けた印が案件に残らない = opt-manage 2a-1)
        res, cut = self._pack_one(run, st, doc, doc["sourcePath"], opts, force=force or state == "differ", built=built)
        if res == "exists":   # find_pack で見つからない名前違いのパック(以前の版で作ったもの)など
            self._keep_pack(run, doc["sourcePath"])
            st["state"], st["detail"] = "skip", "同じ名前のパックがあるので上書きしませんでした(「作り直す」を選ぶと上書きします)"
            return None
        st["detail"] = "パックを作りました" + ("(「編集」のカットのとおり)" if cut else "(文字起こしの行から)") + \
            ("。前のパックを上書きしました" if force else "。" + PACK_DIFFER if state == "differ" else "") + "".join("。" + n for n in opts[3])
        return None

    # 話者分離(友人の「話す人」) --------------------------------
    def _step_diarize(self, run, st, v=None):
        """この実行で文字起こしした文書を、友人が入れた人数で話者分離し、名前は覚えている声と照らし合わせる(1人なら判別せずその人)。
        失敗しても次の段へ進む(字幕は話者なしのまま。一部失敗)"""
        tids = list(dict.fromkeys(run.new_docs))
        if not tids:
            st["state"], st["detail"] = "skip", "新しく文字起こしした文書がありません"
            return None
        b = self._bundle(run)   # 人数 = 束の transcribe.diarize・名前 = hints.people(Run の欄 speakers はここへ写っている。RS7-1 S3)
        hp = _spec.hint_people(b)
        sp = {"count": b["transcribe"]["diarize"] or hp["count"], "names": [p["name"] for p in hp["people"]]}
        body = {"numSpeakers": sp["count"], "names": list(sp["names"]), "recognize": True,
                "keepRowVoice": True}   # 文字起こしで覚えた声で行の話者を当てた文書(flow/diar.row_voices)は上書きしない(短いコラボは判別が人を分けられない)
        styles = self._speaker_styles(run)   # 友人が指定した字幕の色(あれば話者分離のあと、文書に覚える)
        bad, no_color = [], []
        for i, tid in enumerate(tids, 1):
            self._check(run)
            st["detail"] = "%d / %d 本" % (i - 1, len(tids))
            status, res = self.tools.diarize_start(dict(body, tid=tid))
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

    def _file_diarize(self, run, st):
        return self._step_diarize(run, st)

    # 依頼の動画(mode file) -------------------------------------
    def _step_normalize(self, run, st, v=None):
        """動画ファイルの実行の最初: 作業データへ写した動画が 30fps(H.264・yuv420p・AAC)でなければ、写しを作り直して置き換える
        (flow/normalize の plan(replace=True)・run。友人の元のファイルは触らない。opt-human 9a-1)。
        重い処理の枠 SLOTS はこの段の中で取る(実行ごとの糸なので、受付の見回りは止まらない)。作り直したら run.source_path を新しいパスにして
        待ちの記録(封筒の input.path)を書き直す。30fps 済みなら飛ばす。作れない・失敗・取り消しの文は警告にして、元の写しのまま次の段へ"""
        if run.doc_id or any(s["key"] == "transcribe" and s["state"] in DONE_STEPS for s in run.steps):
            st["state"], st["detail"] = "skip", "文字起こしのあとなので、30fps にそろえません(文書の動画を変えないため)"
            return None
        if not os.path.isfile(run.source_path):
            raise StepError("依頼の動画が見つかりません(移動・削除した可能性があります)")
        p = _norm.plan(run.source_path, replace=True)
        if p is None:
            st["state"], st["detail"] = "skip", "30fps 済み"
            return None
        if p.get("note"):
            st["state"], st["detail"] = "warn", p["note"]
            return None
        if self._norm_parallel_ok(run):
            return self._norm_start_bg(run, st, p)
        return self._step_normalize_inline(run, st, p)

    def _step_normalize_inline(self, run, st, p):
        """段の中で作り直して置き換える(今の形)"""
        st["detail"] = "重い処理の枠が空くのを待っています"
        last = [-1]

        def progress(x):
            pct = int(float(x) * 100)
            if pct != last[0]:
                last[0] = pct
                st["detail"] = "30fps にそろえています(%d%%)" % pct

        def started():
            st["detail"] = "30fps にそろえています(%s)" % " / ".join(p.get("why") or [])[:120]
        stop = lambda: run.cancel or self.closed   # noqa: E731
        self.log("30fps にそろえます: %s(%s)" % (run.title, " / ".join(p.get("why") or [])))
        with _slots.SLOTS.slot("flow", "30fps にそろえる: " + str(run.title)[:60], cancelled=stop, **_prio.slot_kw(_prio.of_run(run))) as ok:
            self._check(run)   # 待っている間に中止 = Cancelled(枠は取れていない)
            if not ok:
                raise Cancelled()
            path, note = _norm.run(p, cancelled=stop, on_progress=progress, on_start=started)
        if path:   # 置き換えた(元の写しはもう無い): 中止の検査より先に新しいパスを待ちの記録へ(再開が消えた写しを探さない)
            run.source_path = path
            self._checkpoint(run)   # 封筒の input.path が新しい写しになる
        self._check(run)   # 作り直しの途中で中止(normalize.run は「取り消しました」で返る)
        if not path:
            self.log("30fps にできませんでした。写しのまま進めます: %s(%s)" % (run.title, note))
            st["state"], st["detail"] = "warn", note or "30fps にそろえられませんでした。元の動画のまま進めます"
            return None
        self.log("30fps にそろえました: %s(%s)" % (run.title, note))   # 作り方(音声だけ・GPU・CPU)も残る
        st["detail"] = "30fps にそろえました(%s)" % " / ".join(p.get("why") or [])[:120]
        return None

    def _norm_parallel_ok(self, run):
        """並べてよいか: 動画ファイルの実行・この後に文字起こしの段がある・文書を付け替える口がある(LocalTools は無い = 今の形)"""
        return bool(run.source_path) and callable(getattr(self.tools, "relink", None)) and any(
            s["key"] == "transcribe" and s["state"] not in DONE_STEPS for s in run.steps)

    def _norm_start_bg(self, run, st, p):
        """作り直しを裏の糸で始める(枠はその糸が取る)。写しは別の名前に作り、元は付け替えが済むまで消さない(文字起こしが元の音を読む)"""
        src = p["src"]
        dst = p["dst"] if os.path.normcase(p["dst"]) != os.path.normcase(src) else "%s-%s.mp4" % (os.path.splitext(src)[0], os.urandom(3).hex())
        audio = "%s-aac-%s.m4a" % (os.path.splitext(src)[0], os.urandom(3).hex())
        if not _vnorm_audio(src, audio):   # 音を作れない = 並べずに今の形(段の中で作り直す)
            return self._step_normalize_inline(run, st, p)
        plan = dict(p, dst=dst, replace=False)
        stop = lambda: run.cancel or self.closed   # noqa: E731
        res = {}

        def work():
            try:
                with _slots.SLOTS.slot("flow", "30fps にそろえる: " + str(run.title)[:60], cancelled=stop, **_prio.slot_kw(_prio.of_run(run))) as ok:
                    res["out"] = _norm.run(plan, cancelled=stop) if ok else (None, "取り消しました")
            except Exception as e:   # noqa: BLE001  作り直せなくても元の写しのまま進む
                res["out"] = (None, "30fps にそろえられませんでした(%s)" % e.__class__.__name__)
        th = threading.Thread(target=work, name="normalize-bg", daemon=True)
        run.norm_bg = {"thread": th, "res": res, "src": src, "dst": dst, "audio": audio, "same": os.path.normcase(p["dst"]) == os.path.normcase(src)}
        th.start()
        self.log("30fps にそろえます(文字起こしと並べて): %s(%s)" % (run.title, " / ".join(p.get("why") or [])))
        st["detail"] = "30fps にそろえています(文字起こしと並べて。%s)" % " / ".join(p.get("why") or [])[:100]
        return None

    def _norm_join(self, run):
        """並べた作り直しの終わりを待ち、作り直した動画へ文書を付け替えて元の写しを消す。付け替えられなければ作った写しを消して元のまま(警告)"""
        bg, run.norm_bg = run.norm_bg, None
        if bg is None:
            return
        try:
            self._norm_join_bg(run, bg)
        finally:
            _fsio.unlink_quiet(bg["audio"])

    def _norm_join_bg(self, run, bg):
        st = run.step(NORMALIZE_STEP)
        while bg["thread"].is_alive():
            bg["thread"].join(0.2)
            if run.cancel or self.closed:   # 糸は stop を見て止まる。待ち終えてから上げる(作りかけの写しを残さない)
                bg["thread"].join()
                _fsio.unlink_quiet(bg["dst"])
                self._check(run)
        path, note = bg["res"].get("out") or (None, "")
        why = None
        if path and bg["same"]:   # 元が同じ名前の .mp4: 元を消して写しを元の名前へ(文書は元のパスのまま = 付け替え不要)
            try:
                os.replace(path, bg["src"])
                path = bg["src"]
            except OSError as e:
                why = "作り直した写しを元の名前にできませんでした(%s)" % e.__class__.__name__
        elif path and run.doc_id:
            why = self.tools.relink(run.doc_id, path)
        if not path or why:
            if path:
                _fsio.unlink_quiet(path)
            st["state"], st["detail"] = "warn", why or note or "30fps にそろえられませんでした。元の動画のまま進めます"
            self.log("30fps にできませんでした。写しのまま進めます: %s(%s)" % (run.title, st["detail"]))
            return
        if not bg["same"]:
            _fsio.unlink_quiet(bg["src"])   # 置き換え = 古い写しを消す(文書はもう付け替えた)
        run.source_path = path
        self._checkpoint(run)
        st["detail"] = "30fps にそろえました(文字起こしと並べて)"
        self.log("30fps にそろえました(文字起こしと並べて): %s" % run.title)

    def _file_normalize(self, run, st):
        return self._step_normalize(run, st)

    def _file_pack(self, run, st):
        if not run.doc_id:
            st["state"], st["detail"] = "skip", "文字起こしの文書がありません"
            return "stop"
        return self._doc_pack(run, st)

    def _file_transcribe(self, run, st):
        """文字起こし(並べた 30fps の作り直しがあれば、文字起こしのあとで待って付け替える)"""
        try:
            return self._file_transcribe_one(run, st)
        finally:
            self._norm_join(run)

    def _file_transcribe_one(self, run, st):
        if not os.path.isfile(run.source_path):
            raise StepError("依頼の動画が見つかりません(移動・削除した可能性があります)")
        doc = self._pick_doc(self._docs(), None, None, run.source_path)
        opts = self._tx_opts(run)
        b = self._bundle(run)   # 実行ごとに選んだエンジン・モデル(リアルタイム切り抜きの live.auto。M2)= 束の transcribe + run.pinned。
        for k in ("engine", "model"):   # 依頼が決めたときは、機器から決まるエンジンと同じでも要求に書く(今の要求の本文のまま)。無ければ編集の設定のまま
            if k in _pins(b):
                opts[k] = b["transcribe"][k]
        from_pack = b["run"]["from"] == "pack"   # 束の run.from = pack(CLI の --from pack): 文字起こし済みの文書でパックだけ(force でも文字起こしは作り直さない。RS7-1 S4)
        if from_pack and not (doc and doc.get("count")):
            raise StepError("この動画の文字起こしの文書がありません(パックからでなく、文字起こしから実行してください)")
        made = self._made_here(run, run.source_path, doc if doc and doc.get("count") else None)   # 再開: 終了の前にこの実行が作った文書(F2)
        verdict = "skip" if made else tx_verdict(bool(doc and doc.get("count")), self._force(run) and not from_pack)   # 鍵(RS6 b-K2): force なら作り直す(新しい文書。人の直しは引き継ぐ)
        redo = verdict == "redo"
        if made:
            self._add_new_doc(run, doc["id"])
            st["state"], st["detail"] = "skip", "文字起こし済み(起動し直す前に済んでいた分)"
            tid = doc["id"]
        elif verdict == "skip":
            differ = self._tx_state(doc, run.source_path, opts) == "differ"   # 違えば飛ばして印・同じ / 鍵なしは飛ばす
            st["state"], st["detail"] = "skip", "文字起こし済み" + ("(%s)" % TX_DIFFER if differ else "")
            tid = doc["id"]
        else:
            self._tx_mark(run, [(run.source_path, [doc["id"]] if doc and doc.get("count") else [])])
            audio = {"audioPath": run.norm_bg["audio"]} if run.norm_bg else {}   # 並べた作り直しと同じ音
            jid = self.tools.transcribe_start(dict(opts, sourcePath=run.source_path, **audio), bundle=self._bundle(run))
            j = self._wait_job(run, jid, st)
            if j.get("state") != "done":
                raise StepError("文字起こしに失敗しました: %s" % _job_why(j))
            tid = j.get("tid")
            self._add_new_doc(run, tid)
            st["state"], st["detail"] = "done", ("文字起こしし直しました(force)" if redo else "文字起こししました") + "。字幕の校正は「編集」で"
        if tid and tid not in run.docs:
            run.docs.append(tid)
        run.doc_id = tid or None   # ① 全自動: この文書でパックを作る
        # 依頼で選んだ配信者を、この文書の配信者として覚える(パックのときの字幕の色。段5 の記憶と同じ)。
        # 受付で推定した配信者(streamer_from あり。RS7-1 S4)は覚えない(今までどおり。推定は実行中に決めていたので、ここでは決まっていなかった)
        if tid and run.streamer and not run.streamer_from and self._remember_doc_streamer(tid, run.streamer):
            st["detail"] += "。配信者: %s" % run.streamer
        return None


def run(client, input, spec=None, from_=None, hooks=None, tools=None):
    """① の入口: 入力(Run か {"videoId"}・{"docId"}・{"path"}。Run.from_input)を段の順に進めて、その Run を返す(中止は Cancelled・失敗は StepError)。
    spec = 指定の束(変えたい所だけ。None = 既定)。flow/spec.py の merge で既定に重ね validate で確かめる(形が違えば ValueError。段は始めない)。
    入力が Run なら、spec が None ならその束のまま・あればその Run の差分(Run.diff)を spec に重ね直す(段の並びは作ったときのまま)。
    hooks = hook を埋めた Runner(入口の AutoRunner)。None = 素の Runner(tools = 仕事を頼む先。None = HttpTools(client)。hooks があれば hooks の物)"""
    if isinstance(input, Run):
        r = input
        if spec is not None:
            r.spec = _spec.validate(_spec.merge_onto(_spec.validate(_spec.merge(spec)), r.diff or {}))
        elif r.spec is None:
            r.spec = _spec.validate(_spec.merge(None))
    else:
        r = Run.from_input(input, from_, spec)
    runner = hooks if hooks is not None else Runner(client, tools=tools)
    try:
        runner.execute(r)
    finally:   # 終わったら(失敗・中止でも)結果の束を案件の 作業用/runs/ へ(書けなくても上げない。RS6 b-B0)
        _placement.write_result(r, sys.exc_info()[1], runner)
    return r
