#!/usr/bin/env python3
"""文字起こしツール用のローカルサーバー(標準ライブラリ + faster-whisper)。

    python3 serve.py [開始ポート] [--no-open]

  GET  /                     index.html
  GET  /app.js, /ui-kit.js, /cut.js, /pack-tab.js   画面の JS(CSP script-src 'self' のため外部ファイルで配信)
  GET  /api/ping             起動確認
  GET  /api/tools            ffmpeg / faster-whisper / GPU の有無
  GET  /api/settings, PUT    用語集・置換辞書・前回の設定
  GET  /api/marker           隣の clip-marker/data.json のポイント一覧(あれば)
  POST /api/transcribe       文字起こしジョブを追加(順番に1つずつ処理)
  GET  /api/jobs             ジョブの一覧と進捗 / POST /api/transcribe/cancel で中止
  POST /api/diarize          話者の自動判別ジョブを追加(sherpa-onnx。文字起こしと同じ待機列。recognize: 覚えている声で名前を付ける。既定オン)。
                             numSpeakers 1 = 判別せず全部の行をその1人に / names = 出てくる人の名前(照らし合わせをこの名前だけに・1人だけ残れば消去法で付ける。友人からの依頼)
  GET  /api/voices           覚えている声の一覧(A-3。判別モデルごと。特徴そのものは返さない。generic = 一般的な名前)
  GET  /api/overlap-drafts?id=&kinds=overlap,missing  声があるのに行の無い所(重なり・抜け)の空の行の候補 {items, more, counts, reason, reasonCode, diarAt}(読むだけ。
                             判別の記録 <id>.diar.json の latest から。行を足すのは画面。ed_speakers の ovdraft_)
  GET  /api/voices/preview   ?tid=&embedding= 覚える前の確認(読むだけ。覚える人・行・秒・既にある名前・断った名前・使わなかった行の数。段1)
  POST /api/voices/learn     {tid, embedding, names, confirmSame} 名前を付けた話者の声を覚えるジョブを追加(A-3。作業データの voices/ に保存。
                             校正済みの行だけ・評価用は断る・一般的な名前は覚えない・既にある名前は confirmSame に入れたときだけ足す。段1)
  POST /api/voices/delete    覚えている声を消す {embedding, name}
  POST /api/retranscribe     選んだ行だけを、別のモデルで再認識するジョブを追加
  POST /api/redo             {"tid", "redoLarge"?} 疑わしい所(「長い区間に文字が少ない」の行)だけ認識し直すジョブ(12 ③-2。良くなったときだけ置き換える)
  POST /api/resplit          {"id", "orientation"?, "splitChars"?, "baseUpdatedAt"?} 今の文書の長い行を、保存してある単語の時刻(transcripts/<id>.words.json)で分け直す(12 ②)
  POST /api/retime           {"id", "rows": [行の id…]} 行の時刻を単語の時刻(words.json)に合わせる候補(読むだけ。文書は書き換えない。本体は ed_retime.py)
  GET  /api/learned          修正から学習した「誤=>正」の候補
  GET  /api/suggest?id=      この文字起こしの各行への「修正の提案」(文脈つきの統計)
  POST /api/suggest/feedback 提案の採用・却下を記録(項目の tier "alt" = 2つ目のエンジンの候補は学習の統計に入れず、数だけ数える)
  POST /api/alt              {"id", "engine"?} 2つ目のエンジンで同じ音声を聞くジョブ(結果は transcripts/<id>.alt.json。文書は書き換えない。
                             食い違う所が GET /api/suggest に tier "alt" の候補として出る。評価用・最初の認識と同じエンジンとモデルは断る。D1-b。本体は ed_alt.py)
  POST /api/ytcap            {"id"} 元の配信の YouTube の字幕(配信者の字幕 → 自動字幕)を取って比べるジョブ(字幕だけ・配信ごとに ytcaps/ で使い回す・結果は transcripts/<id>.ytcap.json。
                             文書は書き換えない。食い違う所が GET /api/suggest に tier "yt" の候補として出る。評価用・元の配信が分からない文書は断る。案 A1。本体は ed_ytcap.py)
  POST /api/export-corrections  修正データ(音声の範囲+直した文章)をzipで書き出す(scope=proofed で校正済みの行すべて)
  GET  /api/metrics?id=&legacy=1  校正済みの行を正解とした文字誤り率(CER)。id 省略で全件
  POST /api/abtest           校正済みの行の音声を複数の設定で認識し直し、正解との差を比べるジョブ(文字起こしは書き換えない)
  GET  /api/evals?id=        比較の結果の一覧(id=文字起こし。省略で全件) / GET /api/eval?id= で1件
  GET  /api/transcripts      保存済みの文字起こし一覧
  GET/PUT/DELETE /api/transcript?id=   1件の取得・保存・削除
  GET  /media?id=            文字起こしの元ファイルを再生用に配信(Range対応)
  「編集」(docs/design/edit-tool-design.md の 5):
  GET/PUT /api/edit?id=      編集の内容(残す区間)。PUT {"edit", "baseRev", "draft"?} → {"rev", "cutRows"}(rev が違えば 409。行の cutState も合わせる。
                             draft = 始めたたき台。初めての保存のときだけ edit.json に一度書く = マスタープラン Q2)
  POST /api/effort           {"id", "activeSec", "cutSec"?, "newSession"?} 校正の手間(操作していた秒)を文書の effort に足す(updatedAt は変えない。
                             校正済みにした行の数は保存のときにサーバーが数える。Q2)
  POST /api/doc-diarnum      {"id", "diarNum"} 文書ごとの話者判別の人数(0 = 自動・1〜8。updatedAt は変えない。段7 E-6)
  POST /api/thumb-ideas      {"id", "crop"?: alt|center|right} サムネの案(6 案を 1 枚の PNG に。作業用/<名前>_thumb-ideas.png。ジョブ kind thumb。文書は読むだけ。P5。本体は ed_thumb.py → thumb_ideas.py)
  GET  /api/thumb-ideas?id=   その文書のサムネの案の有無・作った時刻・案ごとの型と文字 / GET /api/thumb-ideas/image?id= で PNG
  GET  /api/edit/draft?id=&rows=1  動画の fps・長さと、たたき台「行から」(pack.TRANSCRIPT_ROWS。残す行が無ければ全部)・隣の .cut-plan.json。
                             「行から」はカットが無い文書か rows=1 のときだけ計算する(設定の rowEdge = 行の端を声の止まる所まで広げるか)
  POST /api/edit/pack        {"id", "rev", "docUpdatedAt", "dir", "files", "output"?} パックを作り終えた記録(packRev)。output = 作ったときの出力の設定(壊れていれば保存しない)
  POST /api/edit/preview     {"id", "keeps"} カットのとおりに作ったときのパックの見積もり(ファイルは作らない)
  GET  /api/edit/pack-readme?id=  前回のパックの手順書(友人へ.txt)
  POST /api/open-video       {"path", "title"?} 文字起こしせずに開く → {"id", "created"}(同じ動画の文書があればそれ)
  GET  /api/doc-for?path=    その動画の文書 → {"doc": {"id", "rows"} | null}(?media= で開いたとき。パスを比べるだけ)
  GET  /api/peaks?id=        音の波形(0〜255 の1バイトの並び。X-Peaks-Rate・X-Peaks-Duration)。作っている間は 202
  受け渡し(docs/spec/pipeline.md。本体は pipeline_io.py):
  GET  /api/clip-info?path=  動画(または .clip.json)の隣の youtube-tools-clip/v1 → {"clip", "clipPath", "mediaPath", "warning"}
  GET  /api/transcript-v1?id= youtube-tools-transcript/v1 の JSON
  POST /api/export-file      {"id", "format": transcript-v1|srt|cut-plan-v1} 動画の隣に保存 → {"path", "name", "overwritten", "format", "count"}
  GET  /api/siblings         実行中の他のツールのポート {"tools": {"transcribe": 8775, ...}}
  評価ドリル(マスタープラン Q4。git の履歴(679ff01 以前)の docs/plan/q3-q4-design.md の (c)。本体は ed_drill.py。画面は編集の ?doc=<id>&drill=1):
  GET  /api/drill/next?skip=<id,…>  次の評価用の動画 1 本(まだ確かめていない・直近 10 分に更新していない・処理中でない・動画がある)を乱数で
  POST /api/drill/reviewed   {id, baseUpdatedAt, via?} 「全部聞いて直した」印 evalReviewed と残りの行の校正済み(updatedAt が違えば 409)
  POST /api/drill/unreviewed {id, baseUpdatedAt} 確かめ済みの印を外す
  GET  /api/drill/status     定点(確かめ済みの評価用の動画 15 分)の残りと条件(話者・配信・重なり・BGM・呼び名)
  GET  /api/drill/candidates?id=  話者の候補(覚えた声 → メンバーのフォルダ → 配信の文脈)

127.0.0.1 にのみバインドし、Host / Origin / Sec-Fetch-Site を検査する(画面 / への遷移だけは、他のツールのリンクから開けるよう別扱い)。
"""
import json
import os
import re
import shutil
import socket
import sys
import threading
import time
import urllib.parse
import webbrowser
from http.server import BaseHTTPRequestHandler

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))   # 別のフォルダから起動しても、隣の部品(pipeline_io.py・resolve_export.py)を読めるように


def _load_core():
    """共通部品 ytt_core(リポジトリ直下。統合計画の段階2)を読み込めるようにする。
    探す場所: 環境変数 YTT_CORE_DIR(一時フォルダに写して動かすテスト用)→ このフォルダの1つ上。sys.path の末尾に足す(隣の部品を隠さないため)。"""
    here = os.path.dirname(os.path.abspath(__file__))
    for d in (os.environ.get("YTT_CORE_DIR"), os.path.dirname(here)):
        if d and os.path.isfile(os.path.join(d, "ytt", "__init__.py")):
            if d not in sys.path:
                sys.path.append(d)
            return
    raise SystemExit("共通部品 ytt が見つかりません(%s の隣に ytt フォルダが必要です)。"
                     "リポジトリのフォルダの中身をまとめて置き直してください" % here)


_load_core()
from ytt import datadir as _datadir, httpsec, jobs as _heavy_jobs, layout as _layout, modfwd as _modfwd, runtime as _runtime  # noqa: E402
import ed_state, ed_store, ed_relink, ed_media, ed_jobs, ed_speakers, ed_learn, ed_misc, ed_evalaudio  # noqa: E402,F401  (分けた部品。段10。ed_evalaudio = 評価用の音声)
import ed_drill  # noqa: E402,F401  (評価ドリルと定点の「あと何分」。マスタープラン Q4)
import ed_evalbatch  # noqa: E402,F401  (評価用の動画のまとめての文字起こし。マスタープラン Q4)
import ed_alt  # noqa: E402,F401  (2つ目のエンジンとの食い違いの候補。精度改善 第2版 D1-b)
import ed_ytcap  # noqa: E402,F401  (元の配信の YouTube の字幕との食い違いの候補。案 A1)
import ed_retime  # noqa: E402,F401  (字幕の読む速さの印・行の時刻を単語の時刻に合わせる候補。2026-10-05)
import ed_fill  # noqa: E402,F401  (認識のあとの後処理 A・C・D = 文字の少ない行を別の読みで埋める・定型の幻覚と重複の掃除・名簿の呼び名の 1 字違い。10-08 の実験ループ。0.60.0)
import ed_thumb  # noqa: E402,F401  (サムネの案のジョブ。提案 P5。0.64.0)
import ed_llm  # noqa: E402,F401  (LLM の後処理 E = 名簿の呼び名の聞き違いらしい所だけを文字の LLM で直す。提案 P18。0.61.0)
from eval.fake import fake_asr  # noqa: E402  (疑似の文字起こし。app だけが ④ を読んで差し込み口に登録する。RS2-2)
from pipeline.transcribe import backend as _txbackend, txenv as _txenv  # noqa: E402  (本物と疑似の差し込み口・置き場所と外の道具の口。RS2-2)
from pipeline.transcribe import roster as _txroster, tx_engines as _txengines  # noqa: E402  (名簿の prompt_terms・エンジンの engine_of・engine_home を ed_jobs から移した。RS2-4a)
from pipeline.transcribe import postproc as _txpost  # noqa: E402  (行の後処理と要確認の印を ed_jobs から移した。RS2-4b)
from pipeline.transcribe import records as _txrecords  # noqa: E402  (認識の記録・辞書の版・生出力・単語の時刻を ed_jobs から移した。RS2-5)
from pipeline.transcribe import worker_client as _txworker  # noqa: E402  (認識ワーカー・モデル・エンジンの確かめを ed_jobs から、wav の形を ed_speakers から移した。RS2-6)
from pipeline.transcribe import recognize as _txrecognize  # noqa: E402  (音声の取り出し・認識・範囲の行・全体の再認識の続きからを ed_jobs から移した。RS2-7)
from human.proof import doc_jobs as _docjobs  # noqa: E402  (文字起こしのジョブの本体・文書づくり・受付・再認識の反映。RS2-8b に ed_jobs から移した。ed_jobs は転送だけの殻)


APP_ID = _runtime.TOOL_APPS["transcribe"]   # /api/ping の app 名(互換のため値は変えない。正は ytt_core.runtime.TOOL_APPS)
SERVER_VERSION = "0.67.0"  # app.js 側の APP_VERSION と揃える(版の正はここ。入口 home/launch.py がこの行を読む。部品は ed_state.SERVER_VERSION で読む)
ed_state.APP_ID, ed_state.SERVER_VERSION = APP_ID, SERVER_VERSION


# ---------- 分けた部品(段10。git の履歴(679ff01 以前)の docs/plan/phase10-code-split.md) ----------
# serve.py の名前の受付: serve.py に無い名前は分けた部品から読み、S.名前 = … の差し替えはその名前を持つ部品へ転送する
# (テスト・認識ワーカー・dev/eval_asr.py・入口の取り込みは、今までどおり serve の名前で使える)
_ED_MODULES = (ed_state, ed_store, ed_relink, ed_media, _heavy_jobs, fake_asr, _txroster, _txengines, _txpost, _txrecords, _txworker, _txrecognize, _docjobs, ed_jobs, ed_speakers, ed_learn, ed_misc, ed_evalaudio, ed_drill, ed_evalbatch, ed_alt, ed_ytcap)   # _heavy_jobs = ytt/jobs(ed_jobs から移したジョブの表。RS2-1b)・fake_asr = 疑似の文字起こし(RS2-2)・_txroster・_txengines = 名簿とエンジン(RS2-4a)・_txpost = 行の後処理(RS2-4b)・_txrecords = 認識の記録(RS2-5)・_txworker = 認識ワーカー(RS2-6)・_txrecognize = 認識(RS2-7)・_docjobs = 文書の側のジョブ(RS2-8b。ed_jobs は転送だけの殻 = 名前を持たない)。移した先は ed_jobs より前
_ED_MODULES += (ed_retime,)   # 読む速さ・時刻の候補(2026-10-05。足すときは上の行を書き換えずにこの形で)
_ED_MODULES += (ed_fill,)   # 認識のあとの後処理 A・C・D(2026-10-08。0.60.0)
_ED_MODULES += (ed_llm,)   # LLM の後処理 E(2026-10-09。0.61.0)
_ED_MODULES += (ed_thumb,)   # サムネの案(2026-10-09。0.64.0)


# ---------- ジョブの種類の登録と、ジョブの表に渡す編集の値(役割で組み直す RS2-1b。表と待機列は ytt/jobs) ----------
# 本体は lambda の中で呼ぶたびに読む(S.run_job = … などのテストの差し替えが効く)。下の層の部品は自分で登録しない(app のここだけ)。
# 同じ文字起こしに同時に入れない組み合わせ(exclusive)は、入口の検査(validate_*・redo_spec の tid_busy)と登録(add_job)の両方がこの表を使う(正はここ 1 つ。
# 10-09: 声を覚える(voice-learn)は入口だけが再認識・疑わしい所の最中を断り、判別・再認識は入口と登録で見る組が違っていたのをそろえた。
# 0.65.0(10-09): 表を対称に(a が b を断るなら b も a を断る)= 再認識・疑わしい所も声を覚えるの最中は断る(声を覚える途中で行の時刻が変わると、覚える区間がずれる)。
# ほかの種類(abtest・alt・ytcap・thumb)は同じ種類どうしだけ(thumb は文書を読むだけ = ほかと同時でよい)。test_voices.TestExclusive が対称を確かめる)
# 優先度は数値が小さいほど先(話者判別 0 = 待っている文字起こしを追い越す・alt と ytcap 2 = 普通の文字起こしより後。D1-b)。
# retry = [やり直す] で同じ指定のまま入れ直せる(文書を書き換える処理は、文書の画面のボタンから始め直す)
_DOC_LOCK = ("diarize", "retranscribe", "redo", "voice-learn")
_heavy_jobs.register("transcribe", lambda job: _docjobs.run_job(job), retry=True)
_heavy_jobs.register("diarize", lambda job: ed_speakers.run_diarize(job), priority=0, exclusive=_DOC_LOCK, has_tid=True)
_heavy_jobs.register("voice-learn", lambda job: ed_speakers.run_voice_learn(job), exclusive=_DOC_LOCK, has_tid=True)
_heavy_jobs.register("retranscribe", lambda job: _docjobs.run_retranscribe(job), exclusive=_DOC_LOCK, has_tid=True)
_heavy_jobs.register("redo", lambda job: _docjobs.run_redo(job), exclusive=_DOC_LOCK, has_tid=True)
_heavy_jobs.register("abtest", lambda job: ed_misc.run_abtest(job), exclusive=("abtest",))
_heavy_jobs.register("normalize", lambda job: ed_relink.run_normalize(job), has_tid=True)   # 動画を選び直したあとの 30fps の作り直し(Q1)
_heavy_jobs.register("alt", lambda job: ed_alt.run_alt(job), priority=2, exclusive=("alt",), has_tid=True)   # 2つ目のエンジンで聞いて <id>.alt.json に(文書は書き換えない。D1-b)
_heavy_jobs.register("ytcap", lambda job: ed_ytcap.run_ytcap(job), priority=2, exclusive=("ytcap",), has_tid=True)   # 元の配信の YouTube の字幕(案 A1)
_heavy_jobs.register("thumb", lambda job: ed_thumb.run_thumb(job), exclusive=("thumb",), has_tid=True)   # サムネの案を 1 枚に(文書は読むだけ。P5)
_heavy_jobs.configure(tool=ed_state.TOOL_ID, log=ed_state.log, tmp_dir=lambda: ed_state.TMP_DIR, max_queue=lambda: ed_state.MAX_QUEUE,
                      mark=lambda info: ed_state.write_mark(info), after=lambda: _txworker.models_touched(),
                      idle=lambda: _txworker.release_idle_models(), no_retry=lambda: _docjobs.NO_RETRY)


# ---------- 認識の部品の口(役割で組み直す RS2-2)----------
# 置き場所と外の道具: 呼ぶたびに ed_state の今の値を返す(set_data_dir・テストの S.TX_DIR = …・patch.object(S, "check_source") が効く。RS3 で ytt/settings に置き換える)
_txenv.register(DATA_DIR=lambda: ed_state.DATA_DIR, TX_DIR=lambda: ed_state.TX_DIR, TMP_DIR=lambda: ed_state.TMP_DIR, ROOT=lambda: ed_state.ROOT,
                ROSTER=lambda: ed_state.ROSTER, SERVER_VERSION=lambda: ed_state.SERVER_VERSION,
                find_ffmpeg=lambda: ed_state.find_ffmpeg, worker_python=lambda: ed_state.worker_python, worker_fake=lambda: ed_state.worker_fake,
                gpu_ready=lambda: ed_state.gpu_ready, has_faster_whisper=lambda: ed_state.has_faster_whisper,
                media_duration=lambda: ed_state.media_duration, check_source=lambda: ed_state.check_source,
                # RS2-8a: スタジオの配信の情報(roster.stream_context)・モデル名の検査と受け渡しの部品(文書の側の doc_jobs が ed_state を読まずに済むように)
                studio_stream=lambda: ed_store.studio_stream, valid_model=lambda: ed_state.valid_model, pio=lambda: ed_state.pio)
_txenv.check()
# 本物と疑似: 呼ぶたびに決める(テストの S.backend_name の差し替えが効く)。ed_jobs.transcribe_fake などの旧い名前は fake_asr へ転送
_txbackend.set_selector(lambda: fake_asr.FAKE if ed_state.backend_name() == "fake" else _txbackend.REAL)
ed_jobs._add_moved(fake_asr)
# 辞書の版(records.dict_version)の材料: 置換辞書の組と学習の記録は文書の側(doc_jobs が ed_learn を読む)から。呼ぶたびに読む(S.dict_pairs の差し替えが効く。RS2-5)
_txrecords.set_dict_inputs(pairs=lambda spec: _docjobs.dict_pairs(spec), learned=lambda: _docjobs.dict_learned())
# 認識ワーカーの本体と記録のパス(以前は ed_jobs の読み込みのときに ed_state から作っていた。set_data_dir が記録を入れ直す。RS2-6)
_txworker.WORKER_SCRIPT = os.path.join(ed_state.ROOT, "tx_worker.py")
_txworker.WORKER_LOG = os.path.join(ed_state.DATA_DIR, "worker.log")
# 範囲・全体の再認識と疑わしい所の行の頭の「名前:」を外す決まり(ed_fill の B を ① の recognize へ。呼ぶたびに読む。RS2-7)
_txrecognize.set_head_stripper(lambda spec: _docjobs.head_stripper(spec))


_ed_owner = _modfwd.install(globals(), _ED_MODULES, "serve")   # serve.名前 で serve.py に無い名前を分けた部品から読み、
# serve.名前 = …・del(テストの差し替え・mock.patch.object・入口の ALLOWED_HOSTS・ワーカーの IN_WORKER)はその名前を持つ部品へ。仕組みは ytt/modfwd.py(ed_jobs の転送と共通)


# ---------- HTTP ----------
QUIET_PATHS = ("/api/jobs", "/media", "/api/siblings", "/api/progress", "/api/clip-info", "/api/peaks", "/api/edit", "/api/doc-for", "/api/effort", "/api/drill/status")   # 画面が頻繁に呼ぶ・パスを含むので、黒い画面に出さない
PAGE_HEADERS = httpsec.PAGE_HEADERS


def _tid_arg(tid, required=True):
    """文書の id の形だけ確かめる(違えば 404)。required=False なら空も通す"""
    if (required or tid) and not ed_state.TID_RE.match(tid):
        raise ed_state.ApiError("not_found", "文字起こしが見つかりません", 404)
    return tid


def _ping():
    w = _txworker.WORKER   # 認識ワーカーの状態(入口の「調子」が読む。段9 9-1)
    return {"app": ed_state.APP_ID, "version": ed_state.SERVER_VERSION,
            "worker": {"alive": w.alive(), "pid": (w.proc.pid if w.proc is not None else None), "starts": w.starts,
                       "lastUsedAgo": (int(time.time() - w.last_used) if w.last_used else None), "silenceTimeoutSec": _txworker.WORKER_SILENCE_TIMEOUT}}


def _tools_info():
    return {"ffmpeg": bool(ed_state.find_ffmpeg()), "fasterWhisper": ed_state.has_faster_whisper(), "cuda": ed_state.gpu_ready(), "nvidia": ed_state.nvidia_gpu(),
            "backend": ed_state.backend_name(), "diarize": ed_speakers.diar_info(), "models": ed_state.MODELS, "langs": ed_state.LANGS, "root": ed_state.TX_DIR,
            "envWarnings": list(_env_warnings), "alt": ed_alt.alt_info(), "ytcap": ed_ytcap.ytcap_info(), **_txworker.engines_info()}


def _jobs_list():
    with _heavy_jobs._jobs_lock:
        return {"jobs": [_docjobs.public_job(_heavy_jobs._jobs[i]) for i in _heavy_jobs._order if i in _heavy_jobs._jobs]}


def _learned(a):
    mc = a("min", "1")
    return ed_learn.learned_candidates(max(1, min(20, int(mc))) if mc.isdigit() else 1)


def _metrics(a):
    sc = a("scope", "all")
    return ed_learn.all_metrics(_tid_arg(a("id"), False) or None, a("legacy", "0") == "1", sc if sc in ("all", "eval", "train") else "all")


def _transcript(tid):
    d = ed_store.read_transcript(tid)
    return dict(d, evalLocked=ed_relink.in_eval_dir(d.get("sourcePath")))   # 評価用のフォルダの動画(画面で外せない)


# GET の API: パス → 関数(a(名前, 既定) = URL の引数)→ 応答の JSON。部品の関数は lambda の中で ed_xxx.名前 と呼ぶたびに読む(テストの差し替えが効く)
GET_API = {
    "/api/ping": lambda a: _ping(),
    "/api/siblings": lambda a: ed_state.pio().siblings(ed_misc.runtime_path_dir(), ed_state.TOOL_ID, ed_state.PORT, self_path=ed_state.BASE_PATH),
    "/api/clip-info": lambda a: ed_misc.clip_info(a("path")),
    "/api/transcript-v1": lambda a: ed_misc.transcript_v1(a("id")),
    "/api/roster": lambda a: ed_learn.load_roster(),
    "/api/tools": lambda a: _tools_info(),
    "/api/marker": lambda a: ed_misc.read_marker(),
    "/api/voices": lambda a: {"voices": ed_speakers.voices_summary(), "match": ed_speakers.VOICE_MATCH},   # A-3: 覚えている声の一覧(特徴そのものは返さない)
    "/api/overlap-drafts": lambda a: ed_speakers.ovdraft_for_doc(a("id"), a("kinds", None)),   # 重なりの所の空の行の候補(読むだけ。判別の記録 diar.json の声の区間から)
    "/api/voices/preview": lambda a: ed_speakers.voice_preview(a("tid"), a("embedding")),   # 段1: 覚える前の確認(読むだけ。話者の名前を返すので、ほかの GET と同じ Host/Origin 検査の下)
    "/api/transcribed-ranges": lambda a: {"items": ed_misc.transcribed_ranges()},
    "/api/jobs": lambda a: _jobs_list(),
    "/api/transcripts": lambda a: {"items": ed_store.list_transcripts()},
    "/api/learned": _learned,
    "/api/suggest": lambda a: ed_learn.suggest_for_doc(_tid_arg(a("id"))),
    "/api/metrics": _metrics,
    "/api/eval-baselines": lambda a: {"items": ed_learn.read_baselines()},
    "/api/evals": lambda a: {"items": ed_misc.list_evals(_tid_arg(a("id"), False) or None)},
    "/api/eval": lambda a: ed_misc.read_eval(a("id")),
    "/api/progress": lambda a: ed_misc.progress_stats(),
    "/api/drill/status": lambda a: ed_drill.drill_status(),   # 評価ドリル(Q4): 定点の「あと何分」と条件
    "/api/drill/next": lambda a: ed_drill.drill_next(a("skip")),   # 次の評価用の動画 1 本(読むだけ。skip = このドリルで飛ばした文書)
    "/api/drill/candidates": lambda a: ed_drill.drill_candidates(a("id")),   # 話者の候補(ドリル・話者のカードの「全行をこの人に」)
    "/api/dataset": lambda a: ed_learn.dataset_stats(),
    "/api/history": lambda a: {"items": ed_store.list_history(a("id"))},
    "/api/transcript": lambda a: _transcript(a("id")),
    "/api/eval-folders": lambda a: ed_relink.eval_folders_info(),
    "/api/eval-audio": lambda a: ed_evalaudio.status(),   # 評価用の音声(flac)の作成の状態(本数・作った数・残り・大きさ・最後のエラー)
    "/api/eval-batch": lambda a: ed_evalbatch.eval_batch_status(),   # 評価用の動画のまとめての文字起こしの状態(Q4)
    "/api/edit": lambda a: ed_store.get_edit(a("id")),
    "/api/edit/draft": lambda a: ed_store.edit_draft(a("id"), a("rows") == "1"),
    "/api/thumb-ideas": lambda a: ed_thumb.thumb_info(a("id")),   # サムネの案の有無・作った時刻・案ごとの型と文字(P5)
    "/api/edit/pack-readme": lambda a: ed_store.pack_readme(a("id")),
    "/api/doc-for": lambda a: {"doc": ed_store.find_doc_for_media(a("path"))},
}


def _job(spec, kind="transcribe"):
    return _docjobs.public_job(_heavy_jobs.add_job(spec, kind))


def _id_of(o):
    return str(o.get("id") or o.get("tid") or "")


def _delete_voice(o):
    ed_speakers.delete_voice(str(o.get("embedding") or ed_speakers.DIAR_EMB_DEFAULT), str(o.get("name") or "")[:60])
    return {"ok": True, "voices": ed_speakers.voices_summary()}


def _cancel(o):
    _heavy_jobs.cancel_job(o.get("id"))
    return {"ok": True}


# POST の API: パス → 関数(o = 送られた JSON のオブジェクト)→ 応答の JSON(zip を返す 2 つは Handler の _export_corrections・_resolve_package)
POST_API = {
    "/api/transcribe": lambda o: _job(_docjobs.validate_job(o)),
    "/api/diarize": lambda o: _job(ed_speakers.validate_diarize(o), "diarize"),
    "/api/voices/learn": lambda o: _job(ed_speakers.validate_voice_learn(o), "voice-learn"),   # A-3: 名前を付けた話者の声を覚える(ジョブ)
    "/api/speakers/sub": lambda o: ed_speakers.speakers_sub_apply(o),   # 話者ごとの字幕の見た目(今は色)を名前で入れる(入口のまとめて実行が友人の指定を覚える。2026-10-05)
    "/api/voices/delete": _delete_voice,
    "/api/retranscribe": lambda o: _job(_docjobs.validate_retranscribe(o), "retranscribe"),
    "/api/redo": lambda o: _job(_docjobs.redo_spec(str(o.get("tid") or ""), o), "redo"),
    "/api/alt": lambda o: _job(ed_alt.alt_spec(_id_of(o), o), "alt"),   # 2つ目のエンジンで聞く(D1-b)。文書は書き換えないので、編集は止めない
    "/api/thumb-ideas": lambda o: _job(ed_thumb.thumb_spec(_id_of(o), o), "thumb"),   # サムネの案を 1 枚に(P5)。文書は読むだけなので、編集は止めない
    "/api/ytcap": lambda o: _job(ed_ytcap.ytcap_spec(_id_of(o), o), "ytcap"),   # 元の配信の YouTube の字幕を取って比べる(案 A1)。文書は書き換えないので、編集は止めない
    "/api/scan-folder": lambda o: ed_misc.scan_folder(o.get("path"), o.get("recursive") is True),
    "/api/transcribe-batch": lambda o: ed_misc.add_batch(o),
    "/api/settings/patch": lambda o: ed_learn.patch_settings(o),   # ほかの画面(ホーム・スタジオのまとめて実行の欄)から、決まった項目だけを直す
    "/api/eval-baseline": lambda o: ed_learn.record_baseline(o.get("label")),
    "/api/abtest": lambda o: _job(ed_misc.validate_abtest(o), "abtest"),
    "/api/archive": lambda o: {"ok": True, "docs": ed_learn.start_archive(o.get("tid") or None, o.get("full") is not False)},
    "/api/restore": lambda o: {"ok": True, "updatedAt": ed_store.restore_history(str(o.get("id", "")), o.get("ts"))["updatedAt"]},
    "/api/suggest/feedback": lambda o: {"ok": True, "n": ed_learn.record_feedback(o)},
    "/api/export-file": lambda o: ed_misc.export_file(o),
    "/api/open-video": lambda o: ed_store.open_video(o),
    "/api/relink/check": lambda o: ed_relink.relink_check(o),
    "/api/relink": lambda o: ed_relink.relink_doc(o),
    "/api/relink/missing": lambda o: ed_relink.relink_missing(),
    "/api/relink/find": lambda o: ed_relink.relink_find(o),
    "/api/eval-folders/organize": lambda o: ed_relink.eval_organize("button"),
    "/api/eval-folders/settle": lambda o: ed_relink.eval_settle(o),
    "/api/eval-batch/start": lambda o: ed_evalbatch.eval_batch_start(o),
    "/api/eval-batch/stop": lambda o: ed_evalbatch.eval_batch_stop(o),
    "/api/eval-batch/redo": lambda o: ed_evalbatch.eval_batch_redo(o),   # 未確認で手つかずの評価用を作り直す(dryRun = 数えるだけ)
    "/api/eval-batch/redo-one": lambda o: ed_evalbatch.eval_batch_redo_one(o),   # 開いている評価用の動画 1 本だけを今の設定ですぐ作り直す(人が手を入れていれば force のときだけ)
    "/api/pick": lambda o: ed_relink.pick_path(o),
    "/api/resplit": lambda o: _docjobs.resplit_doc(o),
    "/api/retime": lambda o: ed_retime.retime_doc(o),   # 行の時刻を単語の時刻に合わせる候補(読むだけ。ed_retime)
    "/api/edit/pack": lambda o: ed_store.record_pack(o),
    "/api/edit/preview": lambda o: ed_store.edit_preview(o),
    "/api/effort": lambda o: ed_store.add_effort(o),
    "/api/doc-diarnum": lambda o: ed_store.set_diar_num(o),   # 文書ごとの話者判別の人数(updatedAt は変えない。段7 E-6)
    "/api/drill/reviewed": lambda o: ed_drill.drill_reviewed(o),   # 評価ドリル(Q4): 動画を全部聞いて直した印(409 = 別の所で変わった)
    "/api/drill/unreviewed": lambda o: ed_drill.drill_unreviewed(o),   # 確かめ済みの印を外す
    "/api/transcribe/cancel": _cancel,
    "/api/jobs/retry": lambda o: _docjobs.public_job(_heavy_jobs.retry_job(o.get("id"))),   # 失敗した文字起こしを同じ指定でもう一度(UI の見直し M9)
}


def _qid(u):
    """URL の ?id=(無ければ "")"""
    return (urllib.parse.parse_qs(u.query).get("id") or [""])[0]


# 本文を断る理由(httpsec.BodyError の kind)→ (error, 画面の文)。文は以前の _read_json と同じ({mb} = 上限の MB)
_BODY_ERRORS = {"type": ("bad_type", "Content-Type は application/json にしてください"),
                "length": ("bad_length", "Content-Length が正しくありません"),
                "size": ("too_big", "送る内容が空か、大きすぎます(最大{mb}MB)"),
                "short": ("bad_json", "JSON として読めません"),
                "json": ("bad_json", "JSON として読めません"),
                "object": ("bad_json", "JSON のオブジェクトを送ってください")}


class Handler(BaseHTTPRequestHandler):
    server_version = "TranscribeTool/0.1"
    timeout = 120   # 送ると言った長さより短い本文・読まれない応答で、処理のスレッドが永久に止まらないように(秒)

    def log_message(self, fmt, *args):
        if self.path.startswith(QUIET_PATHS):
            return
        super().log_message(fmt, *args)

    def send_response(self, code, message=None):
        self._responded = True
        super().send_response(code, message)

    # 安全検査の規則は ytt_core.httpsec に1か所(スタジオ・文字起こし・入口で共通)
    def _host_ok(self):
        return httpsec.host_ok(self.headers, ed_state.ALLOWED_HOSTS)

    def _origin_ok(self):
        # 「http://」+ 許可したホスト と完全に一致するものだけ
        return httpsec.origin_ok(self.headers, ed_state.ALLOWED_HOSTS)

    def _fetch_site_ok(self):
        return httpsec.fetch_site_ok(self.headers)

    def _navigation_ok(self, path):
        """他のツールの画面のリンク(http://localhost:8800 → http://localhost:8775/?media=...)で、この画面を開くのは許す。
        ポートが違うだけでも Sec-Fetch-Site は same-site(127.0.0.1 と localhost なら cross-site)になるため、以前は 403 になっていた。
        画面(index.html)を新しいタブで開くだけで、URL で重い処理は始まらない(docs/spec/pipeline.md の 3)。API は従来どおり同じ画面からだけ。
        埋め込み(iframe)での悪用は X-Frame-Options / frame-ancestors で防ぐ。"""
        return httpsec.navigation_ok(self.headers, path)

    def _send(self, code, body=b"", ctype="text/plain; charset=utf-8", extra=None):
        httpsec.send(self, code, body, ctype, extra)   # 見出し(no-store・nosniff)は ytt_core の 1 か所(スタジオ・入口と同じ)

    def _send_path(self, path, ctype, extra=None):
        with open(path, "rb") as f:
            return self._send(200, f.read(), ctype, extra)

    def _send_zip(self, path, name, extra):
        """作った zip を添付で返す(ファイルを消すのは呼び出し側。見出しは httpsec.send_head)"""
        httpsec.send_head(self, 200, "application/zip", os.path.getsize(path), dict({"Content-Disposition": 'attachment; filename="%s"' % name}, **extra))
        with open(path, "rb") as f:
            shutil.copyfileobj(f, self.wfile, 65536)

    def _json(self, code, obj):
        self._send(code, json.dumps(obj, ensure_ascii=False).encode("utf-8"), "application/json")

    def _err(self, e):
        self._json(e.status, dict(e.extra, error=e.code, message=e.message))

    def _fail(self, code, error, message):
        """画面の api() が理由を表示できるよう、エラーも JSON で返す(以前は 403/413/415 が素の文字列で「エラー 403」としか出なかった)。"""
        self._json(code, {"error": error, "message": message})

    def _read_json(self):
        """書き込み系の要求の本文(JSON のオブジェクト)。だめなら理由を返して None(読み方は ytt_core.httpsec.read_json_body。
        NaN / Infinity は受け付けない = 保存すると画面の JSON.parse が壊れる)。途中で切れた接続(read)には応答しない"""
        try:
            return httpsec.read_json_body(self, ed_state.MAX_BODY)
        except httpsec.BodyError as e:
            if e.kind == "read":
                return None
            code, msg = _BODY_ERRORS.get(e.kind) or ("bad_json", "JSON として読めません")
            self._fail(e.status, code, msg.replace("{mb}", str(ed_state.MAX_BODY // 1048576)))
            return None

    def _guard(self, write, path=""):
        if not self._host_ok():
            self._fail(403, "forbidden", "このツールは http://localhost:%d%s から開いてください(Host が違います)" % (ed_state.PORT, ed_state.BASE_PATH))
            return False
        if not (self._fetch_site_ok() or (not write and self._navigation_ok(path))) or (write and not self._origin_ok()):
            self._fail(403, "forbidden", "別のサイト・別のツールの画面からの操作は受け付けません")
            return False
        return True

    def _safe(self, fn):
        """想定外の例外でも、黙って接続を切らずに 500 と理由を返し、serve.log に残す。"""
        self._responded = False
        try:
            fn()
        except (BrokenPipeError, ConnectionError, socket.timeout):
            pass
        except Exception as e:
            ed_state.log.exception("要求の処理で例外: %s %s", self.command, self.path.split("?", 1)[0])
            if not self._responded:
                try:
                    self._fail(500, "internal", "内部エラー: %s %s(serve.log に記録しました)" % (e.__class__.__name__, str(e)[:200]))
                except Exception:
                    pass

    def do_HEAD(self):
        self._safe(self._get)

    def do_GET(self):
        self._safe(self._get)

    def do_POST(self):
        self._safe(self._post)

    def do_PUT(self):
        self._safe(self._put)

    def do_DELETE(self):
        self._safe(self._delete)

    def _get(self):
        u = urllib.parse.urlsplit(self.path)
        if not self._guard(False, u.path):
            return
        q = urllib.parse.parse_qs(u.query)

        def arg(k, default=""):
            return (q.get(k) or [default])[0]
        name = u.path.lstrip("/")
        try:
            if u.path in ("/", "/index.html"):
                return self._send_path(ed_state.INDEX, "text/html; charset=utf-8", PAGE_HEADERS)
            if u.path in ("/app.js", "/ui-kit.js"):
                return self._send_path(ed_state.APP_JS if u.path == "/app.js" else ed_state.UI_KIT_JS, "text/javascript; charset=utf-8")
            if name in ed_state.PAGE_JS and os.path.isfile(os.path.join(ed_state.ROOT, name)):
                return self._send_path(os.path.join(ed_state.ROOT, name), "text/javascript; charset=utf-8")
            fn = GET_API.get(u.path)
            if fn is not None:
                return self._json(200, fn(arg))
            if u.path == "/api/settings":
                try:
                    with open(ed_state.SETTINGS, "rb") as f:
                        raw = f.read()
                    return self._send(200, raw[3:] if raw.startswith(b"\xef\xbb\xbf") else raw, "application/json")
                except OSError:
                    return self._json(200, {})
            if u.path == "/api/peaks":
                return self._peaks(arg("id"))
            if u.path == "/media":
                return self._media(arg("id"))
            if u.path == "/api/thumb-ideas/image":   # サムネの案の PNG(パスは文書の動画から作る。P5)
                return httpsec.send_file(self, ed_thumb.thumb_image_path(arg("id")), "image/png")
        except ed_state.ApiError as e:
            return self._err(e)
        self._fail(404, "not_found", "そのページ・操作はありません")

    def _peaks(self, tid):
        r = ed_media.get_peaks(tid)
        if r[0] == "busy":   # 作っている最中・順番待ち(画面は少し待って問い合わせ直す)
            return self._send(202, json.dumps(r[1], ensure_ascii=False).encode("utf-8"), "application/json", {"Retry-After": "1"})
        _, data, rate, dur = r
        return self._send(200, data, "application/octet-stream",
                          {"X-Peaks-Rate": str(rate), "X-Peaks-Duration": "%.3f" % dur, "X-Peaks-Scale": "sqrt", "X-Peaks-Audio": "1" if data else "0"})

    def _media(self, tid):
        d = ed_store.read_transcript(tid)
        try:
            path = ed_state.check_source(d.get("sourcePath"))
        except ed_state.ApiError:
            return self._fail(404, "source_missing", "元の動画・音声が見つかりません(移動・削除した可能性があります)")
        return httpsec.send_file(self, path, ed_state.MEDIA_TYPES[os.path.splitext(path)[1].lower()])   # Range(シーク)・HEAD・416 は ytt_core の 1 か所

    def _post(self):
        if not self._guard(True):
            return
        path = self.path.split("?", 1)[0]
        obj = self._read_json()
        if obj is None:
            return
        try:
            fn = POST_API.get(path)
            if fn is not None:
                return self._json(200, fn(obj))
            if path == "/api/export-corrections":
                return self._export_corrections(obj)
            if path == "/api/resolve-package":
                return self._resolve_package(obj)
        except ed_state.ApiError as e:
            return self._err(e)
        self._fail(404, "not_found", "その操作はありません")

    def _export_corrections(self, obj):
        tid = obj.get("tid")
        if tid is not None and not ed_state.TID_RE.match(str(tid)):
            raise ed_state.ApiError("bad_request", "文字起こしの指定が正しくありません", 400)
        zp, n, na, skipped = ed_learn.export_corrections(str(tid) if tid else None, obj.get("audio") is not False, "proofed" if obj.get("scope") == "proofed" else "changed")
        try:
            if n == 0:
                raise ed_state.ApiError("empty", "書き出せる修正がありません(修正した行が無いか、修正前の出力が残っていない文字起こしです)", 400)
            self._send_zip(zp, "corrections.zip", {"X-Clips": "%d,%d,%d" % (n, na, skipped), "Access-Control-Expose-Headers": "X-Clips"})
        except (BrokenPipeError, ConnectionError):
            pass
        finally:
            ed_state.unlink_quiet(zp)

    def _resolve_package(self, obj):
        import resolve_export
        tid = str(obj.get("tid") or "")
        if not ed_state.TID_RE.match(tid):
            raise ed_state.ApiError("bad_request", "文字起こしの指定が正しくありません", 400)
        tmp_dir = None
        try:
            try:   # 配信者の名前 → 字幕の文字の色(ytt_core/colors.py。git の履歴(679ff01 以前)の docs/archive/followup-2026-09-27.md の 4)
                from ytt import colors as _colors
                who, hex_ = _colors.resolve(obj.get("streamer") if isinstance(obj.get("streamer"), str) else "")
            except ValueError as e:
                raise ed_state.ApiError("bad_streamer", str(e), 400)
            tdoc = ed_store.read_transcript(tid)
            spk_map = _colors.speaker_colors(s.get("name") for s in tdoc.get("speakers") or [] if isinstance(s, dict))[0] \
                if obj.get("speakerColors") is not False else {}   # A-2: 話者の名前ごとの字幕の色(既定はオン)
            ed, _broken = ed_store.read_edit(tid)   # 「編集」のカットがあれば、そのとおりに(3 パック のタブのパックと同じ区間)
            zp, tmp_dir, info = resolve_export.create_package(tdoc, str(obj.get("fps") or "30"), str(obj.get("size") or "") or None, ed_state.SERVER_VERSION,
                                                              keeps=ed_store.edit_keeps_sec(ed) if ed and ed["clips"] else None,
                                                              row_edge=ed_learn.load_settings().get("rowEdge"), backup=obj.get("backup") is True,
                                                              wrap=ed_store.wrap_arg(obj.get("wrap"), obj.get("size")),
                                                              color={"hex": hex_, "who": who} if hex_ else None, speaker_colors=spk_map)
            self._send_zip(zp, "resolve-package.zip", {"X-Resolve-Cuts": str(info["cuts"]), "X-Resolve-Captions": str(info["captions"]),
                                                        "X-Resolve-Handles": "1" if info["media"]["hasEditHandles"] else "0",
                                                        "Access-Control-Expose-Headers": "X-Resolve-Cuts, X-Resolve-Captions, X-Resolve-Handles"})
        except resolve_export.ResolveExportError as e:
            raise ed_state.ApiError("resolve_export", str(e), 400)
        except (BrokenPipeError, ConnectionError):
            pass
        finally:
            if tmp_dir:
                shutil.rmtree(tmp_dir, ignore_errors=True)

    def _put(self):
        if not self._guard(True):
            return
        u = urllib.parse.urlsplit(self.path)
        obj = self._read_json()
        if obj is None:
            return
        try:
            if u.path == "/api/settings":
                if len(json.dumps(obj)) > 200000:
                    raise ed_state.ApiError("too_big", "設定が大きすぎます", 413)
                if "patch" in obj:   # 画面が最後に保存した内容との差のキーだけ(監査 11)。窓を2つ開いても別々の設定なら消し合わない
                    return self._json(200, ed_learn.merge_settings(obj))
                return self._json(200, ed_learn.replace_settings(obj))   # 丸ごと(ほかの画面から直す項目はサーバーの値を残す)
            if u.path == "/api/transcript":
                doc = ed_store.save_transcript(_qid(u), obj)
                return self._json(200, {"ok": True, "updatedAt": doc["updatedAt"], "evalSet": doc.get("evalSet") is True,
                                        "evalReviewed": doc.get("evalReviewed")})   # 確かめ済みの印(評価用を外すと消える。画面の表示を合わせる)
            if u.path == "/api/edit":
                if len(json.dumps(obj)) > ed_store.MAX_EDIT_BYTES:
                    raise ed_state.ApiError("too_big", "区間が多すぎて保存できません", 413)
                return self._json(200, ed_store.save_edit(_qid(u), obj))
        except ed_state.ApiError as e:
            return self._err(e)
        except OSError as e:
            return self._fail(500, "write_failed", "保存できませんでした(%s)。ディスクの空き・フォルダの書き込み権限・他のアプリで開いていないかを確認してください" % (e.strerror or e.__class__.__name__))
        self._fail(404, "not_found", "その操作はありません")

    def _delete(self):
        if not self._guard(True):
            return
        u = urllib.parse.urlsplit(self.path)
        if u.path != "/api/transcript":
            return self._fail(404, "not_found", "その操作はありません")
        tid = _qid(u)
        try:
            with ed_store._save_lock:   # 話者判別・再認識の書き込みと重ならないように(読み直しのあとに消すと、書き込みで生き返っていた)
                ed_store.read_transcript(tid)
                os.unlink(ed_store.tx_path(tid))
                for extra in (ed_store.edit_path(tid), os.path.join(ed_state.TX_DIR, tid + ".edit.broken.json"), _txrecords.words_path(tid),
                              _txrecords.asr_path(tid), ed_speakers.diar_path(tid),
                              ed_alt.alt_path(tid), ed_ytcap.ytcap_path(tid), ed_llm.llm_path(tid)):   # 編集の内容(カット)・単語の時刻・話者判別の記録・2つ目のエンジンと YouTube の字幕・LLM の提案も一緒に
                    try:
                        os.unlink(extra)
                    except FileNotFoundError:
                        pass
                    except OSError as e:
                        ed_state.log.warning("編集の内容を消せませんでした: %s %s", os.path.basename(extra), e)
                ed_store._edit_cache.pop(tid, None)
        except ed_state.ApiError as e:
            return self._err(e)
        except OSError as e:
            return self._fail(500, "delete_failed", "削除できませんでした(%s)。他のアプリで開いていないか確認してください" % (e.strerror or e.__class__.__name__))
        self._json(200, {"ok": True})


def probe(port):
    """そのポートで動いている文字起こしツールの版(このツールでなければ None)。問い合わせは ytt_core.runtime.ping(プロキシを通さない)。"""
    r = _runtime.ping(port, 1)
    return r["version"] if r and r["app"] == ed_state.APP_ID else None


def make_server(start_port):
    for p in range(start_port, start_port + 20):
        ver = probe(p)
        if ver == ed_state.SERVER_VERSION:
            return None, p
        if ver is not None:
            print("※ ポート%d では古い版のサーバーが動いています。その黒い画面を閉じておくと迷いません。" % p)
            continue
        try:
            srv = httpsec.ExclusiveServer(("127.0.0.1", p), Handler)
        except OSError:
            continue
        ed_state.PORT = p
        ed_state.ALLOWED_HOSTS = httpsec.allowed_hosts(p)
        return srv, p
    raise SystemExit("空いているポートが見つかりません(%d〜%d)" % (start_port, start_port + 19))


MIN_FREE_BYTES = 2 * 1024 ** 3   # 空きがこれ未満なら、起動時に知らせる(音声の取り出し・保管で数百MB〜数GB使う)
_env_warnings = []


def startup_checks():
    """起動時の環境チェック。問題があれば、黒い画面と serve.log に出す文(と、画面向けに /api/tools の envWarnings)を返す。
    どれも起動は止めない(文字の編集だけなら使えるため)。"""
    out = []
    if sys.version_info < (3, 8):
        out.append("Python %s は古すぎます。Python 3.10〜3.12 を入れ直してください" % sys.version.split()[0])
    if not ed_state.find_ffmpeg():
        out.append("ffmpeg が見つかりません。文字起こし・話者判別ができません(README の ① の 2)。入れたあとは黒い画面を閉じて起動し直してください")
    try:
        os.makedirs(ed_state.TX_DIR, exist_ok=True)
        probe_path = os.path.join(ed_state.TX_DIR, ".write-test")
        ed_state.atomic_write(probe_path, b"ok")
        os.unlink(probe_path)
    except OSError as e:
        out.append("保存先に書き込めません: %s(%s)。フォルダを書き込みできる場所(デスクトップなど)へ移してください" % (ed_state.TX_DIR, e.strerror or e.__class__.__name__))
    try:
        free = shutil.disk_usage(ed_state.ROOT).free
        if free < MIN_FREE_BYTES:
            out.append("ディスクの空きが少なくなっています(残り %.1fGB)。長い動画の文字起こし・保管が途中で失敗することがあります" % (free / 1024 ** 3))
    except OSError:
        pass
    if not os.path.exists(ed_state.INDEX):
        out.append("index.html が見つかりません。フォルダの中身をまとめて置き直してください")
    try:
        with open(ed_state.APP_JS, "r", encoding="utf-8") as f:   # 版番号は app.js 側にある(index.html はインラインの <script> を外したため)
            m = re.search(r"APP_VERSION\s*=\s*['\"]([^'\"]+)['\"]", f.read())
        if m and m.group(1) != ed_state.SERVER_VERSION:
            out.append("画面(app.js v%s)とサーバー(serve.py v%s)の版が違います。フォルダの中身をまとめて更新してください" % (m.group(1), ed_state.SERVER_VERSION))
    except OSError:
        out.append("app.js が見つかりません。フォルダの中身をまとめて置き直してください")
    except UnicodeError:
        out.append("app.js の文字コードが壊れています。フォルダの中身をまとめて置き直してください")
    if ed_state.pio(required=False) is None:
        out.append("pipeline_io.py / resolve_export.py が見つかりません。「動画の隣に保存」などの受け渡しの機能が使えません。フォルダの中身をまとめて更新してください")
    return out


_started = []


# 以前の場所(このフォルダ)から新しい置き場へ写す名前。ログ・起動中の印・一時ファイル(transcripts/.tmp も)は写さなくてよいが、
# transcripts はフォルダごと写す(.bak・.hist の控えも含めて)
DATA_ITEMS = ("transcripts", "dataset", "evals", "models", "settings.json", "learn-feedback.json", "eval-baselines.json")


def set_data_dir(d):
    """作業データの置き場所を切り替える(起動時に1回。ジョブが動く前)。ワーカーにも環境変数で伝える"""
    ed_state.DATA_DIR = os.path.abspath(d)
    ed_state.TX_DIR = os.path.join(ed_state.DATA_DIR, "transcripts")
    ed_state.TMP_DIR = os.path.join(ed_state.TX_DIR, ".tmp")
    ed_state.DATASET_DIR = os.path.join(ed_state.DATA_DIR, "dataset")
    ed_state.EVAL_DIR = os.path.join(ed_state.DATA_DIR, "evals")
    ed_state.SETTINGS = os.path.join(ed_state.DATA_DIR, "settings.json")
    ed_state.FEEDBACK = os.path.join(ed_state.DATA_DIR, "learn-feedback.json")
    ed_state.LOG_FILE = os.path.join(ed_state.DATA_DIR, "serve.log")
    ed_state.CRASH_FILE = os.path.join(ed_state.DATA_DIR, "serve.crash.log")
    ed_state.RUN_MARK = os.path.join(ed_state.DATA_DIR, ".running.json")
    _txworker.WORKER_LOG = os.path.join(ed_state.DATA_DIR, "worker.log")
    ed_speakers.DIAR_DIR = os.path.join(ed_state.DATA_DIR, "models", "diar")
    ed_learn.EVAL_BASE = os.path.join(ed_state.DATA_DIR, "eval-baselines.json")
    os.environ["TRANSCRIBE_DATA_DIR"] = ed_state.DATA_DIR
    _datadir.register(ed_state.TOOL_ID, ed_state.DATA_DIR)   # 同じプロセスの他のツール(入口の案件・txindex)が datadir.resolve で同じ場所を読む(置き場所の規則は ytt_core.datadir の1か所。2026-10-01)


def studio_data_path():
    """切り抜きスタジオの data.json(読むだけ)。置き場所の規則は ytt_core.datadir.resolve の1か所(起動したスタジオが登録した場所 → STUDIO_HOME → 新しい置き場)。
    決めた場所に無く、登録も STUDIO_HOME も無ければ以前の場所(スタジオのフォルダ。移す前のデータ)"""
    if os.environ.get("TRANSCRIBE_STUDIO_DATA"):
        return os.environ["TRANSCRIBE_STUDIO_DATA"]
    legacy = _layout.tool_dir("studio", os.path.dirname(ed_state.ROOT))
    new = os.path.join(_datadir.resolve("studio", os.path.dirname(ed_state.ROOT), legacy_dir=legacy), "data.json")
    return new if os.path.isfile(new) or _datadir.registered("studio") or _datadir.override("studio") else os.path.join(legacy, "data.json")


def choose_data_dir():
    """起動時: 環境変数 TRANSCRIBE_DATA_DIR があればそれ。無ければ ytt_core.datadir(以前のデータがあれば新しい置き場へコピー)"""
    ed_state.STUDIO_DATA = studio_data_path()
    if os.environ.get("TRANSCRIBE_DATA_DIR"):
        set_data_dir(os.environ["TRANSCRIBE_DATA_DIR"])
        return
    r = _datadir.prepare(ed_state.TOOL_ID, ed_state.ROOT, DATA_ITEMS, log=lambda m: print(m, flush=True))
    for w in r["warnings"]:
        print("※ " + w, flush=True)
    set_data_dir(r["dir"])


def prepare(port, base_path="/", hooks=False):
    """待ち受け以外の起動の準備(ログ・前回の異常終了の確認・.runtime・環境チェック・ジョブのスレッド)。
    main() と、入口の統合サーバー(home/mount.py)の両方から呼ぶ。戻り値は .runtime の記録のパス(書けなければ None)。
    シグナルの受け取りは main() だけで行う(統合サーバーでは入口が受け取る)。"""
    ed_state.PORT, ed_state.BASE_PATH = port, base_path
    if not ed_state.ALLOWED_HOSTS:
        ed_state.ALLOWED_HOSTS = httpsec.allowed_hosts(port)
    choose_data_dir()   # ログより先に(ログも置き場所の中に書く)
    ed_state.setup_cuda_paths()
    ed_state.setup_logging(hooks)
    prev = ed_state.check_previous_run()
    if prev is not None:
        job = prev.get("job") or {}
        msg = "前回は正常に終了しませんでした(落ちた・黒い画面を×で閉じた・強制終了のいずれか)。" + (
            "そのとき実行中だったジョブ: %s %s モデル=%s「%s」" % (job.get("kind", ""), job.get("id", ""), job.get("model", ""), job.get("title", "")) if job else "実行中のジョブはありませんでした")
        print("※", msg)
        print("  詳しくは %s の serve.log・serve.crash.log・worker.log を見てください" % ed_state.DATA_DIR)
        ed_state.log.warning("前回の異常終了を検出: %s", msg)
    ed_state._run_state["started"] = int(time.time())
    ed_state.write_mark(None)
    pm = ed_state.pio(required=False)
    rt = pm.write_runtime(ed_misc.runtime_path_dir(), ed_state.TOOL_ID, port, ed_state.SERVER_VERSION, base_path) if pm else None   # 他のツールの「他のツール」メニューがこのポートを知るため
    if rt is None:
        ed_state.log.warning("実行中のポートの記録(.runtime)を書けませんでした: %s", ed_misc.runtime_path_dir())
    ed_state.log.info("起動 v%s ポート%d%s メモリ %s python %s", ed_state.SERVER_VERSION, port, "" if base_path == "/" else " 場所" + base_path, ed_state._mem(), sys.version.split()[0])
    _env_warnings[:] = startup_checks()
    for w in _env_warnings:
        print("※", w)
        ed_state.log.warning("環境: %s", w)
    if "onedrive" in ed_state.DATA_DIR.lower():   # 同期中のファイルは一瞬開けないことがある(保存は数回やり直すが、念のため知らせる)
        print("※ OneDrive の同期フォルダの中で動いています。保存に失敗することがあれば、同期を一時停止するか、同期しないフォルダへ移してください")
    if not _started:
        _started.append(True)
        threading.Thread(target=_heavy_jobs.worker, daemon=True, name="tx-jobs").start()
        t = threading.Timer(5.0, ed_relink._evalorg_startup)   # 評価用のフォルダの整理(起動時に1回。設定が無ければ何もしない)
        t.daemon = True
        t.start()
        ed_evalbatch.eb_start_background()   # 評価用の動画のまとめての文字起こし(ボタンでオンにしたときだけ動く。オフなら状態を読むだけ)
        ed_evalaudio.start_background()   # 評価用の音声(flac)の作成(起動の5分後と6時間ごと。評価用のフォルダが無ければ何もしない)
    if not ed_state.has_faster_whisper() and ed_state.backend_name() != "fake":
        print("※ faster-whisper が入っていません。install.bat(Mac は install.command)を実行してください")
    return rt


def busy():
    """ジョブ(文字起こし・話者判別など)が動いているか・待っているか(入口の「すべて終了」の確認用)"""
    with _heavy_jobs._jobs_lock:
        return any(j["state"] in _heavy_jobs.ACTIVE_STATES for j in _heavy_jobs._jobs.values())


def finish():
    """終了の後始末: 動いているジョブを取り消し、認識ワーカーを終わらせ、.runtime の記録と起動中の印を消す。"""
    with _heavy_jobs._jobs_lock:
        active = [j["id"] for j in _heavy_jobs._jobs.values() if j["state"] in _heavy_jobs.ACTIVE_STATES]
    for jid in active:
        try:
            _heavy_jobs.cancel_job(jid)
        except ed_state.ApiError:
            pass
    _txworker.WORKER.close()
    ed_state.log.info("終了(正常)")
    pm = ed_state.pio(required=False)
    if pm:
        pm.remove_runtime(ed_misc.runtime_path_dir(), ed_state.TOOL_ID, ed_state.PORT)
    ed_state.clear_mark()


def mounted_elsewhere():
    """入口(start.bat)の統合サーバーの中で文字起こしツールが動いていれば、その URL。
    同じ transcripts/ を2つのサーバーで書き合わない・認識ワーカーを2つ動かさないよう、serve.py を直接起動したときはそちらを開くだけにする。"""
    info = _runtime.read_runtime(ed_misc.runtime_path_dir(), ed_state.TOOL_ID)
    if info and info["path"] != "/" and _runtime.ping_app(info["port"], 1, info["path"]) == ed_state.APP_ID:
        return "http://localhost:%d%s" % (info["port"], info["path"])
    return None


def main():
    live = mounted_elsewhere()
    if live:
        return _open_running("入口の中ですでに起動しています。ブラウザで開きます:", live)
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    srv, port = make_server(int(args[0]) if args else 8775)
    url = "http://localhost:%d" % port
    if srv is None:
        return _open_running("すでに起動しています。ブラウザで開きます:", url)
    install_stop_signals()
    prepare(port, "/", hooks=True)
    print("文字起こしツール:", url, "(終了は Ctrl+C またはこの画面を閉じる)")
    print("保存先:", ed_state.TX_DIR)
    if "--no-open" not in sys.argv:
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        finish()


def _open_running(msg, url):
    """もう動いているサーバーをブラウザで開く(--no-open なら知らせるだけ)"""
    print(msg, url)
    if "--no-open" not in sys.argv:
        webbrowser.open(url)


def install_stop_signals():
    """終了の合図(Linux/Mac の SIGTERM、Windows で黒い画面を×で閉じた・Ctrl+Break の SIGBREAK)でも、Ctrl+C と同じ後始末
    (.runtime の記録と起動中の印を消す)をするよう、KeyboardInterrupt に変える。Windows は×で閉じてから約5秒で強制終了されるが、後始末は一瞬で終わる。"""
    import signal

    def stop(_sig, _frame):
        raise KeyboardInterrupt()
    for name in ("SIGTERM", "SIGBREAK"):
        sig = getattr(signal, name, None)
        if sig is not None:
            try:
                signal.signal(sig, stop)
            except (OSError, ValueError, RuntimeError):
                pass


if __name__ == "__main__":
    main()
