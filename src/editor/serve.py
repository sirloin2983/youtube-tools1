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
                             判別の記録 <id>.diar.json の latest から。行を足すのは画面。human/proof/speakers の ovdraft_)
  GET  /api/voices/preview   ?tid=&embedding= 覚える前の確認(読むだけ。覚える人・行・秒・既にある名前・断った名前・使わなかった行の数。段1)
  POST /api/voices/learn     {tid, embedding, names, confirmSame} 名前を付けた話者の声を覚えるジョブを追加(A-3。作業データの voices/ に保存。
                             校正済みの行だけ・評価用は断る・一般的な名前は覚えない・既にある名前は confirmSame に入れたときだけ足す。段1)
  POST /api/voices/delete    覚えている声を消す {embedding, name}
  POST /api/retranscribe     選んだ行だけを、別のモデルで再認識するジョブを追加
  POST /api/redo             {"tid"}疑わしい所(「長い区間に文字が少ない」の行)だけ認識し直すジョブ(12 ③-2。良くなったときだけ置き換える)
  POST /api/resplit          {"id", "orientation"?, "splitChars"?, "baseUpdatedAt"?} 今の文書の長い行を、保存してある単語の時刻(transcripts/<id>.words.json)で分け直す(12 ②)
  POST /api/retime           {"id", "rows": [行の id…]} 行の時刻を単語の時刻(words.json)に合わせる候補(読むだけ。文書は書き換えない。本体は human/proof/retime.py の包み + pipeline/transcribe/retime.py の計算)
  GET  /api/learned          修正から学習した「誤=>正」の候補
  GET  /api/suggest?id=      この文字起こしの各行への「修正の提案」(文脈つきの統計)
  POST /api/suggest/feedback 提案の採用・却下を記録(項目の tier "alt" = 2つ目のエンジンの候補は学習の統計に入れず、数だけ数える)
  POST /api/alt              {"id", "engine"?} 2つ目のエンジンで同じ音声を聞くジョブ(結果は transcripts/<id>.alt.json。文書は書き換えない。
                             食い違う所が GET /api/suggest に tier "alt" の候補として出る。評価用・最初の認識と同じエンジンとモデルは断る。D1-b。本体は human/proof/alt.py)
  POST /api/ytcap            {"id"} 元の配信の YouTube の字幕(配信者の字幕 → 自動字幕)を取って比べるジョブ(字幕だけ・配信ごとに ytcaps/ で使い回す・結果は transcripts/<id>.ytcap.json。
                             文書は書き換えない。食い違う所が GET /api/suggest に tier "yt" の候補として出る。評価用・元の配信が分からない文書は断る。案 A1。本体は human/proof/ytcap.py)
  GET  /api/metrics?id=&legacy=1  校正済みの行を正解とした文字誤り率(CER)。id 省略で全件
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
  受け渡し(docs/spec/pipeline.md。読み・保存・.runtime は manage/cases/pipeline_io.py・JSON と SRT の組み立ては pipeline/pack/resolve_export.py):
  GET  /api/clip-info?path=  動画(または .clip.json)の隣の youtube-tools-clip/v1 → {"clip", "clipPath", "mediaPath", "warning"}
  GET  /api/transcript-v1?id= youtube-tools-transcript/v1 の JSON
  POST /api/export-file      {"id", "format": transcript-v1|srt|cut-plan-v1} 動画の隣に保存 → {"path", "name", "overwritten", "format", "count"}
  GET  /api/siblings         実行中の他のツールのポート {"tools": {"transcribe": 8775, ...}}
  評価ドリル(マスタープラン Q4。git の履歴(679ff01 以前)の docs/plan/q3-q4-design.md の (c)。本体は eval/drill/drill.py(RS4-2 まで _drill.py)。画面は編集の ?doc=<id>&drill=1):
  GET  /api/drill/next?skip=<id,…>  次の評価用の動画 1 本(まだ確かめていない・直近 10 分に更新していない・処理中でない・動画がある)を乱数で
  POST /api/drill/reviewed   {id, baseUpdatedAt, via?} 「全部聞いて直した」印 evalReviewed と残りの行の校正済み(updatedAt が違えば 409)
  POST /api/drill/unreviewed {id, baseUpdatedAt} 確かめ済みの印を外す
  GET  /api/drill/status     定点(確かめ済みの評価用の動画 15 分)の残りと条件(話者・配信・重なり・BGM・呼び名)
  GET  /api/drill/candidates?id=  話者の候補(覚えた声 → メンバーのフォルダ → 配信の文脈)

127.0.0.1 にのみバインドし、Host / Origin / Sec-Fetch-Site を検査する(画面 / への遷移だけは、他のツールのリンクから開けるよう別扱い)。
"""
import json
import os
import shutil
import socket
import sys
import threading
import time
import urllib.parse
import webbrowser
from http.server import BaseHTTPRequestHandler

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))   # 別のフォルダから起動しても、隣の部品(ed_*.py)を読めるように


def _load_core():
    """共通部品 ytt(リポジトリ直下。統合計画の段階2)を読み込めるようにする。
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
from ytt import datadir as _datadir, httpsec, modfwd as _modfwd, runtime as _runtime  # noqa: E402
from flow import placement as _placement  # noqa: E402  (② 置き場所の持ち主。スタジオの data.json の場所 = studio_data_path。RS6 b-B0)
from flow import jobs as _heavy_jobs  # noqa: E402
from ytt import jobs as _slots_jobs  # noqa: E402  重い処理の枠・Cancelled・check_cancel(① の部品も使う物。RS6 a-2 で flow/jobs と分けた)
from flow import wire as _flowwire  # noqa: E402  ② 文字起こしの配線(ジョブの種類の登録・ジョブの表の設定・本物と疑似の選び方・① の口。RS6 a-5b)
from flow import tx as _flowtx  # noqa: E402  ② 文字起こしの動詞(RS6 a-3。旧 ed_jobs の _doc_fields・dict_pairs・redo_kwargs と旧 ed_alt の alt_engine_version はここ)
from pipeline.transcribe import clipjob as _txclipjob  # noqa: E402  ① 文字起こしのジョブの機械の文書の行(RS6 a-3 に doc_jobs.run_job から。旧 ed_jobs の _rows_to_doc はここ)
from ytt import txwords as _txwords  # noqa: E402  単語の時刻 words.json の読み書き(RS6 a-5b に records から。S.read_words・S.words_path はここ)
from ytt import txtext as _txtext  # noqa: E402  文字起こしの文字の語彙(RS6 a-3 に postproc・roster から。S.strip_punct・S.split_segment・S.SPARSE_FLAG・S.split_terms はここ)
from ytt import version as _version  # noqa: E402
from ytt import settings as _settings  # noqa: E402  (編集の設定の読み書きと鍵の検査・評価用のフォルダの判定。RS3-1 に ed_learn・ed_relink から移した = S.load_settings・S.in_eval_dir はここへ届く)
from ytt import docloc as _docloc, studiodata as _studiodata, tools as _tools, workdata as _workdata  # noqa: E402  (スタジオの data.json の読み口・置き場所と版の今の値・動画と音声の小道具。RS3-0A に ed_state・ed_store から移した = S.TX_DIR = …・S.find_ffmpeg = … はここへ届く)
import ed_state, ed_media  # noqa: E402,F401  (分けた部品。段10。RS5-A で転送だけの殻 ed_store・ed_relink・ed_jobs・ed_speakers・ed_learn・ed_misc を消した。評価用の音声 ed_evalaudio は 0.68.0 で消した)
from manage.cases import pipeline_io  # noqa: E402  (受け渡しの読み・保存・.runtime。RS3-E5b に editor から manage/cases へ。RS3-0A まで ed_state.pio() の遅延ロード = serve.py だけ差し替えたときの備えはやめた)
from pipeline.pack import resolve_export  # noqa: E402  (Resolve パッケージ(zip)と受け渡しの JSON・SRT の組み立て。RS3-E5b に editor から pipeline/pack へ)
from ytt import errors as _errors  # noqa: E402
import ed_thumb  # noqa: E402,F401  (サムネの案のジョブ。提案 P5。0.64.0)
from eval.fake import fake_asr  # noqa: E402  (疑似の文字起こし。app だけが ④ を読んで差し込み口に登録する。RS2-2)
from eval.fake import fake_worker  # noqa: E402  (認識ワーカーの中の疑似。ワーカーへはモジュールの名前だけを渡す = worker_client.FAKES_MODULE。RS2-9)
from pipeline.transcribe import backend as _txbackend  # noqa: E402  (本物と疑似の差し込み口。RS2-2)
from pipeline.transcribe import roster as _txroster, tx_engines as _txengines  # noqa: E402  (名簿の prompt_terms・エンジンの engine_of・engine_home を ed_jobs から移した。RS2-4a)
from pipeline.transcribe import postproc as _txpost  # noqa: E402  (行の後処理と要確認の印を ed_jobs から移した。RS2-4b)
from pipeline.transcribe import records as _txrecords  # noqa: E402  (認識の記録・辞書の版・生出力・単語の時刻を ed_jobs から移した。RS2-5)
from pipeline.transcribe import models as _txmodels, worker_client as _txworker  # noqa: E402  (認識ワーカー・モデル・エンジンの確かめを ed_jobs から、wav の形を ed_speakers から移した。RS2-6)
from pipeline.transcribe import recognize as _txrecognize  # noqa: E402  (音声の取り出し・認識・範囲の行・全体の再認識の続きからを ed_jobs から移した。RS2-7)
from pipeline.transcribe import fill as _txfill, llm as _txllm, retime as _txretime  # noqa: E402  (認識のあとの後処理 A・B・C・D と LLM の後処理 E を ed_fill・ed_llm から、読む速さと時刻の候補の計算を ed_retime から移した。fill・llm の殻は作らない。RS2-9)
from human.proof import doc_jobs as _docjobs  # noqa: E402  (文字起こしのジョブの本体・文書づくり・受付。RS2-8b に ed_jobs から移した。ed_jobs は転送だけの殻)
from human.proof import overrides as _overrides  # noqa: E402  (校正の上書き over.json。文書の削除で一緒に消す。RS6 b-O1)
from human.proof import rerun as _rerun  # noqa: E402  (再認識と疑わしい所の認識し直しの本体・反映・記録。RS2-8c に doc_jobs から割った)
from pipeline.transcribe import diarize as _txdiarize  # noqa: E402  (話者判別の計算・判別の記録・声の特徴と照らし合わせ。RS2-9 に ed_speakers から分けた。ed_speakers は転送だけの殻)
from flow import pack as _flowpack  # noqa: E402  (② パックの動詞。RS6 a-5a)
from flow import machine as _machine  # noqa: E402  (② この PC の設定 machine.json。⚙ のデバイスはここへ書く・読む。RS7-1 S6b)
from flow import keys as _flowkeys  # noqa: E402  (② 成果物の鍵。文書の削除で鍵のファイルも消す。RS6 b-K1)
from flow import diar as _flowdiar  # noqa: E402  (② 判別と声の段取り・判別の記録を書く・覚えた声の置き場所 VOICES_DIR・load_voices ほか。RS6 a-4 に speakers・diarize から)
from human.proof import speakers as _speakers  # noqa: E402  (判別の結果を文書へ・判別のジョブ・空の行の下書き・自動の判別・声を覚える・字幕の見た目。RS2-9)
from ytt import dictfmt as _dictfmt  # noqa: E402  (置換辞書の読み方 parse_replacements・wb_split・_bounded。RS6 a-1 に pipeline/transcribe/replace から ytt へ = S.parse_replacements・S._bounded はここへ届く)
from pipeline.transcribe import replace as _txreplace  # noqa: E402  (置換辞書の読み方と当て方。RS3-E5c に ed_learn から移した。ed_learn は転送だけの殻)
from human.proof import learn as _learn  # noqa: E402  (人が直した内容からの学習・提案・採用と却下の記録・名簿。RS3-E5c に ed_learn から)
from eval.drill import metrics as _evmetrics  # noqa: E402  (認識精度の測定・noSub と重なりの数え方・評価用の基準の記録。RS3-E5c に ed_learn から)
from human.proof import alt as _alt  # noqa: E402  (2つ目のエンジンとの食い違いの候補。精度改善 第2版 D1-b。RS3-E6 に ed_alt から移した。ed_alt は転送だけの殻)
from human.proof import ytcap as _ytcap  # noqa: E402  (元の配信の YouTube の字幕との食い違いの候補。案 A1。RS3-E6 に ed_ytcap から移した。ed_ytcap は転送だけの殻)
from human.proof import retime as _proofretime  # noqa: E402  (字幕の読む速さの印・行の時刻を単語の時刻に合わせる候補の API の包み。2026-10-05。RS3-E6 に ed_retime から移した。計算は _txretime)
from human.proof import store as _store  # noqa: E402  (文書の読み書き・履歴・整形・手間・要約のキャッシュ・編集の内容・文字起こしせずに開く。RS3-E5a に ed_store から移した。ed_store は転送だけの殻)
from manage.cases import doclist as _doclist  # noqa: E402  (一覧と元の動画・パックの有無・前回のパックの手順。RS3-E5a に ed_store から切り出した)
from manage.cases import relink as _relink  # noqa: E402  (付け替え・まとめて付け替える・「参照…」・素材を 30fps にそろえる。RS3-E7 に ed_relink から移した。ed_relink は転送だけの殻)
from eval.drill import folders as _evfolders  # noqa: E402  (評価用のフォルダの整理・仮置き・外からの取り込み。RS3-E7 に ed_relink から切り出した)
from manage.cases import handoff_io as _handoff_io  # noqa: E402  (clip-marker との連携・受け渡しの API。RS3-E7 に ed_misc から移した。ed_misc は転送だけの殻)
from human.proof import batch as _batch  # noqa: E402  (フォルダの一括読み込みと文字起こし済みの範囲。RS3-E7 に ed_misc から切り出した。進行度 progress は 0.69.0(段 D2)で消した)
from eval.drill import drill as _drill  # noqa: E402  (評価ドリルと定点の「あと何分」。マスタープラン Q4。RS4-2 に ed_drill から移した = 殻なし)
from eval.drill import evalbatch as _evalbatch  # noqa: E402  (評価用の動画のまとめての文字起こし。マスタープラン Q4。RS4-2 に ed_evalbatch から移した = 殻なし)


APP_ID = _runtime.TOOL_APPS["transcribe"]   # /api/ping の app 名(互換のため値は変えない。正は ytt.runtime.TOOL_APPS)
SERVER_VERSION = _version.VERSION  # 全体の版(ytt/version.py の 1 か所。画面は入口が入れる meta ytt-version から読む。部品は ytt/workdata の SERVER_VERSION で読む)
ed_state.APP_ID = APP_ID
_workdata.SERVER_VERSION = SERVER_VERSION   # 部品が読む版(RS3-0A から持ち主は ytt/workdata)


# ---------- 分けた部品(段10。git の履歴(679ff01 以前)の docs/plan/phase10-code-split.md) ----------
# serve.py の名前の受付: serve.py に無い名前は分けた部品から読み、S.名前 = … の差し替えはその名前を持つ部品へ転送する
# (テスト・認識ワーカー・src/eval/tools/eval_asr.py・入口の取り込みは、今までどおり serve の名前で使える)
_ED_MODULES = (_workdata, _tools, _studiodata, ed_state, _store, _doclist, _relink, _evfolders, ed_media, _heavy_jobs, _slots_jobs, fake_asr, _txroster, _txengines, _txpost, _txrecords, _txworker, _txmodels, _txrecognize, _docjobs, _rerun, _txdiarize, _speakers, _txreplace, _learn, _evmetrics, _handoff_io, _batch, _drill, _evalbatch, _alt, _ytcap)   # _workdata = ytt/workdata(置き場所と版の今の値。ed_state から移した。RS3-0A)・_tools = ytt/tools(動画と音声の小道具 find_ffmpeg・check_source・media_duration・probe_media ほか。ed_state・ed_store から移した。RS3-0A)・_studiodata = ytt/studiodata(スタジオの data.json の読み口 studio_videos・studio_stream。ed_store から移した。RS3-0A)・_heavy_jobs = ytt/jobs(ed_jobs から移したジョブの表。RS2-1b)・fake_asr = 疑似の文字起こし(RS2-2)・_txroster・_txengines = 名簿とエンジン(RS2-4a)・_txpost = 行の後処理(RS2-4b)・_txrecords = 認識の記録(RS2-5)・_txworker = 認識ワーカー(RS2-6)・_txrecognize = 認識(RS2-7)・_docjobs = 文書の側のジョブ(RS2-8b。ed_jobs は転送だけの殻 = 名前を持たない)・_rerun = 再認識の本体と反映(RS2-8c)。移した先は ed_jobs より前。_txdiarize・_speakers = 話者判別の計算と文書の側(RS2-9。ed_speakers のあった所。殻の ed_speakers は ed_jobs の殻と名前が重なるので並べない)・_txreplace・_learn・_evmetrics = 置換辞書・学習と提案・精度と基準(RS3-E5c。ed_learn のあった所。殻の ed_learn も並べない)
_ED_MODULES += (_txretime, _proofretime)   # 読む速さ・時刻の候補(2026-10-05。足すときは上の行を書き換えずにこの形で)。計算は pipeline/transcribe/retime.py(RS2-9。移した先は包みより前)・文書を読む包みが human/proof/retime(RS3-E6。殻の ed_retime は並べない)
_ED_MODULES += (_txfill,)   # 認識のあとの後処理 A・B・C・D(2026-10-08。0.60.0。RS2-9 から pipeline/transcribe/fill.py。ed_fill は無い)
_ED_MODULES += (_txllm,)   # LLM の後処理 E(2026-10-09。0.61.0。RS2-9 から pipeline/transcribe/llm.py。ed_llm は無い)
_ED_MODULES += (ed_thumb,)   # サムネの案(2026-10-09。0.64.0)
_ED_MODULES += (_settings,)   # 編集の設定の読み書き・鍵の検査(load_settings・patch_settings・SETTINGS_PATCH_KEYS ほか)と評価用のフォルダの判定(RS3-1 に ed_learn・ed_relink から ytt/settings へ)
_ED_MODULES += (_dictfmt,)   # 置換辞書の読み方(RS6 a-1。ytt へ移した。S.parse_replacements・S.wb_split・S._bounded の差し替えが届く)
_ED_MODULES += (_flowdiar,)   # 判別と声の段取り(RS6 a-4。speakers の覚えた声の置き場所・diarize の _record_diar を ② へ。S.VOICES_DIR = … はここへ届く)
_ED_MODULES += (_txtext, _txclipjob, _flowtx)   # RS6 a-3: 文字の語彙(ytt/txtext)・① の機械の文書の行(clipjob)・② 文字起こしの動詞(flow/tx)
_ED_MODULES += (_txwords,)   # RS6 a-5b: 単語の時刻の読み書き(records から ytt へ。S.read_words・S.words_path)
_ED_MODULES += (_flowpack,)   # RS6 a-5a: ② パックの動詞(カットのたたき台の枠 DRAFT_SLOT_WAIT・_draft_slot を ed_store の名前として読めるように)
# ↑ _store・_doclist = 文書の置き場と一覧(RS3-E5a。ed_store のあった所。殻の ed_store は ed_jobs の殻と名前が重なるので並べない)
# ↑ _relink・_evfolders = 付け替えと 30fps・評価用のフォルダの整理(RS3-E7。ed_relink のあった所)・_handoff_io・_batch = 受け渡し・フォルダの一括(RS3-E7。ed_misc のあった所。進行度 _progress は 0.69.0 で消した)。殻の ed_relink・ed_misc も並べない


# ---------- 文字起こしの配線(役割で組み直す RS6 a-5b。ジョブの種類の登録・ジョブの表の設定・本物と疑似の選び方・① の口の登録は ② flow/wire.install。表と待機列は flow/jobs) ----------
# 種類ごとの優先度・同時に入れない組・やり直せるかは flow/wire の表が正。本体は lambda の中で呼ぶたびに読む(S.run_job = … などのテストの差し替えが効く)。
# ③ ⑤ の関数(doc_jobs・speakers・rerun・alt・ytcap・relink・ed_thumb・疑似の本体)は ② が読めないので、ここから渡す。
# 置き場所(ytt/workdata)・動画と音声の小道具(ytt/tools)・ワーカーと GPU とモデル名の検査(worker_client)・名簿のファイル(roster.ROSTER)・スタジオの配信の情報(ytt/studiodata)は、
# 下の層の部品が持ち主を呼ぶたびに直に読む(S.TX_DIR = …・patch.object(S, "check_source") は名前の受付が持ち主へ届ける)
_flowwire.install(
    bodies={"transcribe": lambda job: _docjobs.run_job(job), "diarize": lambda job: _speakers.run_diarize(job), "voice-learn": lambda job: _speakers.run_voice_learn(job),
            "retranscribe": lambda job: _rerun.run_retranscribe(job), "redo": lambda job: _rerun.run_redo(job),
            "normalize": lambda job: _relink.run_normalize(job),   # 動画を選び直したあとの 30fps の作り直し(Q1)
            "alt": lambda job: _alt.run_alt(job), "ytcap": lambda job: _ytcap.run_ytcap(job), "thumb": lambda job: ed_thumb.run_thumb(job)},
    tool=ed_state.TOOL_ID, log=ed_state.log, tmp_dir=lambda: _workdata.TMP_DIR, max_queue=lambda: ed_state.MAX_QUEUE,
    mark=lambda info: ed_state.write_mark(info), no_retry=lambda: _docjobs.NO_RETRY,
    backend_name=lambda: ed_state.backend_name(), fake_backend=fake_asr.FAKE,   # 呼ぶたびに決める(テストの S.backend_name の差し替えが効く)。ed_jobs.transcribe_fake などの旧い名前は fake_asr へ転送
    fake_worker_module=fake_worker.__name__,   # worker-fake(テスト)のときワーカーに読ませる疑似の部品の名前(RS2-9)
    dict_learned=lambda: _docjobs.dict_learned())   # 辞書の版の材料の学習の記録は文書の側(doc_jobs が learn を読む)から。呼ぶたびに読む
# 文書の側(doc_jobs)が使う評価用の作り直し(eval の evalbatch。RS4-2 まで ed_evalbatch)と 30fps の作り直し(manage の relink。RS3-E7 まで ed_relink)。② から ③・④ を読まないための口。
# 評価用のフォルダの判定は RS3-1 から ytt/settings(doc_jobs が直に読む = 口は 5 → 3 本)。
# 呼ぶたびに持ち主のモジュールの属性を読む(test_evalbatch の patch.object(EB, "eb_redo_skip_at_start") が届く)。呼ぶ順は run_job のまま(RS2-8d)
_docjobs.set_hooks(redo_skip=lambda job: _evalbatch.eb_redo_skip_at_start(job), redo_fill=lambda job, spec, fields: _evalbatch.eb_redo_fill(job, spec, fields),
                   norm_after=lambda job, spec, tid: _relink.norm_after_transcribe(job, spec, tid))
_docjobs.check_hooks()
# 話者の文書の側(human/proof/speakers)が使う評価用の文書の名前の候補(eval の drill。RS4-2 まで ed_drill)。② から ④ を読まないための口(呼ぶたびに持ち主の属性を読む。RS2-9)
_speakers.set_context_namer(lambda tid: _drill.drill_candidates(tid).get("suggest"))
_speakers.check_context_namer()


_ed_owner = _modfwd.install(globals(), _ED_MODULES, "serve")   # serve.名前 で serve.py に無い名前を分けた部品から読み、
# serve.名前 = …・del(テストの差し替え・mock.patch.object・入口の ALLOWED_HOSTS・ワーカーの IN_WORKER)はその名前を持つ部品へ。仕組みは ytt/modfwd.py(ed_jobs の転送と共通)


# ---------- HTTP ----------
QUIET_PATHS = ("/api/jobs", "/media", "/api/siblings", "/api/clip-info", "/api/peaks", "/api/edit", "/api/doc-for", "/api/effort", "/api/drill/status")   # 画面が頻繁に呼ぶ・パスを含むので、黒い画面に出さない
PAGE_HEADERS = httpsec.PAGE_HEADERS


def _tid_arg(tid, required=True):
    """文書の id の形だけ確かめる(違えば 404)。required=False なら空も通す"""
    if (required or tid) and not ed_state.TID_RE.match(tid):
        raise ed_state.ApiError("not_found", "文字起こしが見つかりません", 404)
    return tid


def _ping():
    w = _txworker.WORKER   # 認識ワーカーの状態(入口の「調子」が読む。段9 9-1)
    return {"app": ed_state.APP_ID, "version": _workdata.SERVER_VERSION,
            "worker": {"alive": w.alive(), "pid": (w.proc.pid if w.proc is not None else None), "starts": w.starts,
                       "lastUsedAgo": (int(time.time() - w.last_used) if w.last_used else None), "silenceTimeoutSec": _txworker.WORKER_SILENCE_TIMEOUT}}


def _tools_info():
    return {"ffmpeg": bool(_tools.find_ffmpeg()), "fasterWhisper": _txworker.has_faster_whisper(), "cuda": _txworker.gpu_ready(), "nvidia": _txworker.nvidia_gpu(),
            "backend": ed_state.backend_name(), "diarize": _txdiarize.diar_info(), "models": ed_state.MODELS, "langs": ed_state.LANGS, "root": _workdata.TX_DIR,
            "envWarnings": list(_env_warnings), "alt": _alt.alt_info(), "ytcap": _ytcap.ytcap_info(), **_txworker.engines_info()}


def _jobs_list():
    with _heavy_jobs._jobs_lock:
        return {"jobs": [_docjobs.public_job(_heavy_jobs._jobs[i]) for i in _heavy_jobs._order if i in _heavy_jobs._jobs]}


def _learned(a):
    mc = a("min", "1")
    return _learn.learned_candidates(max(1, min(20, int(mc))) if mc.isdigit() else 1)


def _metrics(a):
    sc = a("scope", "all")
    return _evmetrics.all_metrics(_tid_arg(a("id"), False) or None, a("legacy", "0") == "1", sc if sc in ("all", "eval", "train") else "all")


def _transcript(tid):
    d = _store.read_transcript(tid)
    return dict(d, evalLocked=_settings.in_eval_dir(d.get("sourcePath")))   # 評価用のフォルダの動画(画面で外せない)


# GET の API: パス → 関数(a(名前, 既定) = URL の引数)→ 応答の JSON。部品の関数は lambda の中で ed_xxx.名前 と呼ぶたびに読む(テストの差し替えが効く)
GET_API = {
    "/api/ping": lambda a: _ping(),
    "/api/siblings": lambda a: pipeline_io.siblings(ed_state.runtime_path_dir(), ed_state.TOOL_ID, ed_state.PORT, self_path=ed_state.BASE_PATH),
    "/api/clip-info": lambda a: _handoff_io.clip_info(a("path")),
    "/api/transcript-v1": lambda a: _handoff_io.transcript_v1(a("id")),
    "/api/roster": lambda a: _learn.load_roster(),
    "/api/tools": lambda a: _tools_info(),
    "/api/marker": lambda a: _handoff_io.read_marker(),
    "/api/voices": lambda a: {"voices": _speakers.voices_summary(), "match": _txdiarize.VOICE_MATCH},   # A-3: 覚えている声の一覧(特徴そのものは返さない)
    "/api/overlap-drafts": lambda a: _speakers.ovdraft_for_doc(a("id"), a("kinds", None)),   # 重なりの所の空の行の候補(読むだけ。判別の記録 diar.json の声の区間から)
    "/api/voices/preview": lambda a: _speakers.voice_preview(a("tid"), a("embedding")),   # 段1: 覚える前の確認(読むだけ。話者の名前を返すので、ほかの GET と同じ Host/Origin 検査の下)
    "/api/transcribed-ranges": lambda a: {"items": _batch.transcribed_ranges()},
    "/api/jobs": lambda a: _jobs_list(),
    "/api/transcripts": lambda a: {"items": _doclist.list_transcripts()},
    "/api/learned": _learned,
    "/api/suggest": lambda a: _learn.suggest_for_doc(_tid_arg(a("id"))),
    "/api/metrics": _metrics,
    "/api/eval-baselines": lambda a: {"items": _evmetrics.read_baselines()},
    "/api/drill/status": lambda a: _drill.drill_status(),   # 評価ドリル(Q4): 定点の「あと何分」と条件
    "/api/drill/next": lambda a: _drill.drill_next(a("skip")),   # 次の評価用の動画 1 本(読むだけ。skip = このドリルで飛ばした文書)
    "/api/drill/candidates": lambda a: _drill.drill_candidates(a("id")),   # 話者の候補(ドリル・話者のカードの「全行をこの人に」)
    "/api/history": lambda a: {"items": _store.list_history(a("id"))},
    "/api/transcript": lambda a: _transcript(a("id")),
    "/api/eval-folders": lambda a: _evfolders.eval_folders_info(),
    "/api/eval-batch": lambda a: _evalbatch.eval_batch_status(),   # 評価用の動画のまとめての文字起こしの状態(Q4)
    "/api/edit": lambda a: _store.get_edit(a("id")),
    "/api/edit/draft": lambda a: _store.edit_draft(a("id"), a("rows") == "1"),
    "/api/thumb-ideas": lambda a: ed_thumb.thumb_info(a("id")),   # サムネの案の有無・作った時刻・案ごとの型と文字(P5)
    "/api/edit/pack-readme": lambda a: _doclist.pack_readme(a("id")),
    "/api/doc-for": lambda a: {"doc": _store.find_doc_for_media(a("path"))},
}


def _job(spec, kind="transcribe"):
    return _docjobs.public_job(_heavy_jobs.add_job(spec, kind))


def _id_of(o):
    return str(o.get("id") or o.get("tid") or "")


def _delete_voice(o):
    _speakers.delete_voice(str(o.get("embedding") or _txdiarize.DIAR_EMB_DEFAULT), str(o.get("name") or "")[:60])
    return {"ok": True, "voices": _speakers.voices_summary()}


def _cancel(o):
    _heavy_jobs.cancel_job(o.get("id"))
    return {"ok": True}


# POST の API: パス → 関数(o = 送られた JSON のオブジェクト)→ 応答の JSON(zip を返す /api/resolve-package は Handler の _resolve_package)
POST_API = {
    "/api/transcribe": lambda o: _job(_docjobs.validate_job(o)),
    "/api/diarize": lambda o: _job(_speakers.validate_diarize(o), "diarize"),
    "/api/voices/learn": lambda o: _job(_speakers.validate_voice_learn(o), "voice-learn"),   # A-3: 名前を付けた話者の声を覚える(ジョブ)
    "/api/speakers/sub": lambda o: _speakers.speakers_sub_apply(o),   # 話者ごとの字幕の見た目(今は色)を名前で入れる(入口のまとめて実行が友人の指定を覚える。2026-10-05)
    "/api/voices/delete": _delete_voice,
    "/api/retranscribe": lambda o: _job(_docjobs.validate_retranscribe(o), "retranscribe"),
    "/api/redo": lambda o: _job(_docjobs.redo_spec(str(o.get("tid") or ""), o), "redo"),
    "/api/alt": lambda o: _job(_alt.alt_spec(_id_of(o), o), "alt"),   # 2つ目のエンジンで聞く(D1-b)。文書は書き換えないので、編集は止めない
    "/api/thumb-ideas": lambda o: _job(ed_thumb.thumb_spec(_id_of(o), o), "thumb"),   # サムネの案を 1 枚に(P5)。文書は読むだけなので、編集は止めない
    "/api/ytcap": lambda o: _job(_ytcap.ytcap_spec(_id_of(o), o), "ytcap"),   # 元の配信の YouTube の字幕を取って比べる(案 A1)。文書は書き換えないので、編集は止めない
    "/api/scan-folder": lambda o: _batch.scan_folder(o.get("path"), o.get("recursive") is True),
    "/api/transcribe-batch": lambda o: _batch.add_batch(o),
    "/api/settings/patch": lambda o: _settings.patch_settings(o),   # ほかの画面(ホーム・スタジオのまとめて実行の欄)から、決まった項目だけを直す
    "/api/eval-baseline": lambda o: _evmetrics.record_baseline(o.get("label")),
    "/api/restore": lambda o: {"ok": True, "updatedAt": _store.restore_history(str(o.get("id", "")), o.get("ts"))["updatedAt"]},
    "/api/suggest/feedback": lambda o: {"ok": True, "n": _learn.record_feedback(o)},
    "/api/export-file": lambda o: _handoff_io.export_file(o),
    "/api/open-video": lambda o: _store.open_video(o),
    "/api/relink/check": lambda o: _relink.relink_check(o),
    "/api/relink": lambda o: _relink.relink_doc(o),
    "/api/relink/missing": lambda o: _relink.relink_missing(),
    "/api/relink/find": lambda o: _relink.relink_find(o),
    "/api/eval-folders/organize": lambda o: _evfolders.eval_organize("button"),
    "/api/eval-folders/settle": lambda o: _evfolders.eval_settle(o),
    "/api/eval-batch/start": lambda o: _evalbatch.eval_batch_start(o),
    "/api/eval-batch/stop": lambda o: _evalbatch.eval_batch_stop(o),
    "/api/eval-batch/redo": lambda o: _evalbatch.eval_batch_redo(o),   # 未確認で手つかずの評価用を作り直す(dryRun = 数えるだけ)
    "/api/eval-batch/redo-one": lambda o: _evalbatch.eval_batch_redo_one(o),   # 開いている評価用の動画 1 本だけを今の設定ですぐ作り直す(人が手を入れていれば force のときだけ)
    "/api/pick": lambda o: _relink.pick_path(o),
    "/api/resplit": lambda o: _docjobs.resplit_doc(o),
    "/api/retime": lambda o: _proofretime.retime_doc(o),   # 行の時刻を単語の時刻に合わせる候補(読むだけ。human/proof/retime)
    "/api/edit/pack": lambda o: _store.record_pack(o),
    "/api/edit/preview": lambda o: _store.edit_preview(o),
    "/api/effort": lambda o: _store.add_effort(o),
    "/api/doc-diarnum": lambda o: _store.set_diar_num(o),   # 文書ごとの話者判別の人数(updatedAt は変えない。段7 E-6)
    "/api/drill/reviewed": lambda o: _drill.drill_reviewed(o),   # 評価ドリル(Q4): 動画を全部聞いて直した印(409 = 別の所で変わった)
    "/api/drill/unreviewed": lambda o: _drill.drill_unreviewed(o),   # 確かめ済みの印を外す
    "/api/transcribe/cancel": _cancel,
    "/api/jobs/retry": lambda o: _docjobs.public_job(_heavy_jobs.retry_job(o.get("id"))),   # 失敗した文字起こしを同じ指定でもう一度(UI の見直し M9)
}


def _settings_read():
    """GET /api/settings: 編集の設定 + この PC の設定(machine.json)のデバイス。画面の形は同じ(device の欄だけ machine の値)。
    settings.json にも machine.json にも device が無ければ device は付けない(今と同じ)"""
    d = _settings.load_settings()
    if "device" in d or "device" in _machine.explicit():
        d["device"] = _machine.get("device")
    return d


def _settings_split(obj):
    """PUT /api/settings の本文から device(この PC の設定)を分ける -> (device の変更 {device: 値|None} または {}, 残りの本文)。
    patch の形は patch の中の device、丸ごとの形は device。丸ごとのとき settings.json の古い device は消さず残す"""
    if "patch" in obj:
        p = obj.get("patch")
        if isinstance(p, dict) and "device" in p:
            return {"device": p["device"]}, dict(obj, patch={k: v for k, v in p.items() if k != "device"})
        return {}, obj
    if "device" in obj:
        old = _settings.load_settings()
        rest = {k: v for k, v in obj.items() if k != "device"}
        if "device" in old:
            rest["device"] = old["device"]
        return {"device": obj["device"]}, rest
    return {}, obj


def _machine_save(change):
    if change:
        try:
            _machine.save(change)
        except ValueError as e:
            raise _errors.ApiError("bad_request", str(e), 400)


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

    # 安全検査の規則は ytt.httpsec に1か所(スタジオ・文字起こし・入口で共通)
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
        httpsec.send(self, code, body, ctype, extra)   # 見出し(no-store・nosniff)は ytt の 1 か所(スタジオ・入口と同じ)

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
        """書き込み系の要求の本文(JSON のオブジェクト)。だめなら理由を返して None(読み方は ytt.httpsec.read_json_body。
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
        ok = self._guard_check(write, path)
        if not ok and write:   # 断る書き込みの本文は読み捨てる(読まずに閉じると Windows では RST で 403 が届かないことがある。httpsec.drain_body)
            httpsec.drain_body(self.headers, self.rfile)
        return ok

    def _guard_check(self, write, path):
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
            if name in ed_state.PAGE_JS and os.path.isfile(os.path.join(_workdata.ROOT, name)):
                return self._send_path(os.path.join(_workdata.ROOT, name), "text/javascript; charset=utf-8")
            fn = GET_API.get(u.path)
            if fn is not None:
                return self._json(200, fn(arg))
            if u.path == "/api/settings":
                return self._json(200, _settings_read())
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
        d = _store.read_transcript(tid)
        try:
            path = _tools.check_source(d.get("sourcePath"))
        except ed_state.ApiError:
            return self._fail(404, "source_missing", "元の動画・音声が見つかりません(移動・削除した可能性があります)")
        return httpsec.send_file(self, path, _tools.MEDIA_TYPES[os.path.splitext(path)[1].lower()])   # Range(シーク)・HEAD・416 は ytt の 1 か所

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
            if path == "/api/resolve-package":
                return self._resolve_package(obj)
        except ed_state.ApiError as e:
            return self._err(e)
        self._fail(404, "not_found", "その操作はありません")

    def _resolve_package(self, obj):
        tid = str(obj.get("tid") or "")
        if not ed_state.TID_RE.match(tid):
            raise ed_state.ApiError("bad_request", "文字起こしの指定が正しくありません", 400)
        tmp_dir = None
        try:
            try:   # 配信者の名前 → 字幕の文字の色(ytt/colors.py。git の履歴(679ff01 以前)の docs/archive/followup-2026-09-27.md の 4)
                from ytt import colors as _colors
                who, hex_ = _colors.resolve(obj.get("streamer") if isinstance(obj.get("streamer"), str) else "")
            except ValueError as e:
                raise ed_state.ApiError("bad_streamer", str(e), 400)
            tdoc = _store.read_transcript(tid)
            spk_map = _colors.speaker_colors(s.get("name") for s in tdoc.get("speakers") or [] if isinstance(s, dict))[0] \
                if obj.get("speakerColors") is not False else {}   # A-2: 話者の名前ごとの字幕の色(既定はオン)
            ed, _broken = _store.read_edit(tid)   # 「編集」のカットがあれば、そのとおりに(3 パック のタブのパックと同じ区間)
            zp, tmp_dir, info = resolve_export.create_package(tdoc, str(obj.get("fps") or "30"), str(obj.get("size") or "") or None, _workdata.SERVER_VERSION,
                                                              keeps=_store.edit_keeps_sec(ed) if ed and ed["clips"] else None,
                                                              row_edge=_settings.load_settings().get("rowEdge"), backup=obj.get("backup") is True,
                                                              wrap=_store.wrap_arg(obj.get("wrap"), obj.get("size")),
                                                              color={"hex": hex_, "who": who} if hex_ else None, speaker_colors=spk_map)
            self._send_zip(zp, "resolve-package.zip", {"X-Resolve-Cuts": str(info["cuts"]), "X-Resolve-Captions": str(info["captions"]),
                                                        "X-Resolve-Handles": "1" if info["media"]["hasEditHandles"] else "0",
                                                        "Access-Control-Expose-Headers": "X-Resolve-Cuts, X-Resolve-Captions, X-Resolve-Handles"})
        except _errors.ResolveExportError as e:
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
                change, obj = _settings_split(obj)   # device はこの PC の設定(machine.json)へ。RS7-1 S6b
                _machine_save(change)
                if "patch" in obj:   # 画面が最後に保存した内容との差のキーだけ(監査 11)。窓を2つ開いても別々の設定なら消し合わない
                    return self._json(200, _settings.merge_settings(obj))
                return self._json(200, _settings.replace_settings(obj))   # 丸ごと(ほかの画面から直す項目はサーバーの値を残す)
            if u.path == "/api/transcript":
                doc = _store.save_transcript(_qid(u), obj)
                return self._json(200, {"ok": True, "updatedAt": doc["updatedAt"], "evalSet": doc.get("evalSet") is True,
                                        "evalReviewed": doc.get("evalReviewed")})   # 確かめ済みの印(評価用を外すと消える。画面の表示を合わせる)
            if u.path == "/api/edit":
                if len(json.dumps(obj)) > _store.MAX_EDIT_BYTES:
                    raise ed_state.ApiError("too_big", "区間が多すぎて保存できません", 413)
                return self._json(200, _store.save_edit(_qid(u), obj))
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
            with _store._save_lock:   # 話者判別・再認識の書き込みと重ならないように(読み直しのあとに消すと、書き込みで生き返っていた)
                _store.read_transcript(tid)
                main = _store.tx_path(tid)
                extras = [_docloc.doc_file(tid, sfx) for sfx in _docloc.DOC_SUFFIXES[1:]]   # 横のファイル(編集の内容・単語の時刻・話者判別の記録・2つ目のエンジンと YouTube の字幕・LLM の提案・上書き・成果物の鍵)も一緒に。置き場所は文書を消す前に引く(消すと索引が使えなくなる)
                os.unlink(main)
                for extra in extras:
                    try:
                        os.unlink(extra)
                    except FileNotFoundError:
                        pass
                    except OSError as e:
                        ed_state.log.warning("編集の内容を消せませんでした: %s %s", os.path.basename(extra), e)
                _docloc.unplace(tid)   # 案件の 作業用 に置いた文書の索引も消す
                _store._edit_cache.pop(tid, None)
        except ed_state.ApiError as e:
            return self._err(e)
        except OSError as e:
            return self._fail(500, "delete_failed", "削除できませんでした(%s)。他のアプリで開いていないか確認してください" % (e.strerror or e.__class__.__name__))
        self._json(200, {"ok": True})


def probe(port):
    """そのポートで動いている文字起こしツールの版(このツールでなければ None)。問い合わせは ytt.runtime.ping(プロキシを通さない)。"""
    r = _runtime.ping(port, 1)
    return r["version"] if r and r["app"] == ed_state.APP_ID else None


def make_server(start_port):
    for p in range(start_port, start_port + 20):
        ver = probe(p)
        if ver == _workdata.SERVER_VERSION:
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
    if not _tools.find_ffmpeg():
        out.append("ffmpeg が見つかりません。文字起こし・話者判別ができません(README の ① の 2)。入れたあとは黒い画面を閉じて起動し直してください")
    try:
        os.makedirs(_workdata.TX_DIR, exist_ok=True)
        probe_path = os.path.join(_workdata.TX_DIR, ".write-test")
        ed_state.atomic_write(probe_path, b"ok")
        os.unlink(probe_path)
    except OSError as e:
        out.append("保存先に書き込めません: %s(%s)。フォルダを書き込みできる場所(デスクトップなど)へ移してください" % (_workdata.TX_DIR, e.strerror or e.__class__.__name__))
    try:
        free = shutil.disk_usage(_workdata.ROOT).free
        if free < MIN_FREE_BYTES:
            out.append("ディスクの空きが少なくなっています(残り %.1fGB)。長い動画の文字起こし・保管が途中で失敗することがあります" % (free / 1024 ** 3))
    except OSError:
        pass
    if not os.path.exists(ed_state.INDEX):
        out.append("index.html が見つかりません。フォルダの中身をまとめて置き直してください")
    if not os.path.exists(ed_state.APP_JS):   # 画面の版は全体の版 1 つ(ytt/version.py)なので食い違いは無い。ファイルの有無だけ見る
        out.append("app.js が見つかりません。フォルダの中身をまとめて置き直してください")
    return out


_started = []


# 以前の場所(このフォルダ)から新しい置き場へ写す名前。ログ・起動中の印・一時ファイル(transcripts/.tmp も)は写さなくてよいが、
# transcripts はフォルダごと写す(.bak・.hist の控えも含めて)
DATA_ITEMS = ("transcripts", "dataset", "evals", "models", "settings.json", "learn-feedback.json", "eval-baselines.json")


def set_data_dir(d):
    """作業データの置き場所を切り替える(起動時に1回。ジョブが動く前)。ワーカーにも環境変数で伝える"""
    _workdata.set_data_dir(os.path.abspath(d))   # 文書・一時・保管・比較・基準・設定・提案の記録のパス(持ち主は ytt/workdata。RS3-0A)
    ed_state.LOG_FILE = os.path.join(_workdata.DATA_DIR, "serve.log")
    ed_state.CRASH_FILE = os.path.join(_workdata.DATA_DIR, "serve.crash.log")
    ed_state.RUN_MARK = os.path.join(_workdata.DATA_DIR, ".running.json")
    _txworker.WORKER_LOG = os.path.join(_workdata.DATA_DIR, "worker.log")   # (判別のモデル models/diar と覚えた声 voices の置き場所は、話者の部品が呼ぶたびに ytt/workdata の DATA_DIR から作る。RS2-9)
    os.environ["TRANSCRIBE_DATA_DIR"] = _workdata.DATA_DIR
    _datadir.register(ed_state.TOOL_ID, _workdata.DATA_DIR)   # 同じプロセスの他のツール(入口の案件・txindex)が datadir.resolve で同じ場所を読む(置き場所の規則は ytt.datadir の1か所。2026-10-01)


def studio_data_path():
    """切り抜きスタジオの data.json(読むだけ)。環境変数 TRANSCRIBE_STUDIO_DATA(テスト用)が無ければ、置き場所の持ち主 flow/placement の
    studio_data(legacy=True)(起動したスタジオが登録した場所 → STUDIO_HOME → 新しい置き場。そこに無く、登録も STUDIO_HOME も無ければ
    以前の場所 = スタジオのフォルダ。RS6 b-B0 でここから移した。値は同じ)"""
    if os.environ.get("TRANSCRIBE_STUDIO_DATA"):
        return os.environ["TRANSCRIBE_STUDIO_DATA"]
    return _placement.studio_data(os.path.dirname(_workdata.ROOT), legacy=True)


def choose_data_dir():
    """起動時: 環境変数 TRANSCRIBE_DATA_DIR があればそれ。無ければ ytt.datadir(以前のデータがあれば新しい置き場へコピー)"""
    _workdata.STUDIO_DATA = studio_data_path()
    if os.environ.get("TRANSCRIBE_DATA_DIR"):
        set_data_dir(os.environ["TRANSCRIBE_DATA_DIR"])
        return
    r = _datadir.prepare(ed_state.TOOL_ID, _workdata.ROOT, DATA_ITEMS, log=lambda m: print(m, flush=True))
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
    _txmodels.setup_cuda_paths()
    ed_state.setup_logging(hooks)
    prev = ed_state.check_previous_run()
    if prev is not None:
        job = prev.get("job") or {}
        msg = "前回は正常に終了しませんでした(落ちた・黒い画面を×で閉じた・強制終了のいずれか)。" + (
            "そのとき実行中だったジョブ: %s %s モデル=%s「%s」" % (job.get("kind", ""), job.get("id", ""), job.get("model", ""), job.get("title", "")) if job else "実行中のジョブはありませんでした")
        print("※", msg)
        print("  詳しくは %s の serve.log・serve.crash.log・worker.log を見てください" % _workdata.DATA_DIR)
        ed_state.log.warning("前回の異常終了を検出: %s", msg)
    ed_state._run_state["started"] = int(time.time())
    ed_state.write_mark(None)
    rt = pipeline_io.write_runtime(ed_state.runtime_path_dir(), ed_state.TOOL_ID, port, _workdata.SERVER_VERSION, base_path)   # 他のツールの「他のツール」メニューがこのポートを知るため
    if rt is None:
        ed_state.log.warning("実行中のポートの記録(.runtime)を書けませんでした: %s", ed_state.runtime_path_dir())
    ed_state.log.info("起動 v%s ポート%d%s メモリ %s python %s", _workdata.SERVER_VERSION, port, "" if base_path == "/" else " 場所" + base_path, ed_state._mem(), sys.version.split()[0])
    _env_warnings[:] = startup_checks()
    for w in _env_warnings:
        print("※", w)
        ed_state.log.warning("環境: %s", w)
    if "onedrive" in _workdata.DATA_DIR.lower():   # 同期中のファイルは一瞬開けないことがある(保存は数回やり直すが、念のため知らせる)
        print("※ OneDrive の同期フォルダの中で動いています。保存に失敗することがあれば、同期を一時停止するか、同期しないフォルダへ移してください")
    if not _started:
        _started.append(True)
        threading.Thread(target=_heavy_jobs.worker, daemon=True, name="tx-jobs").start()
        t = threading.Timer(5.0, lambda: _evfolders._evalorg_startup())   # 評価用のフォルダの整理(起動時に1回。設定が無ければ何もしない)
        t.daemon = True
        t.start()
        _evalbatch.eb_start_background()   # 評価用の動画のまとめての文字起こし(ボタンでオンにしたときだけ動く。オフなら状態を読むだけ。eval の裏のスレッドは serve が起こす = RS4-2)
    if not _txworker.has_faster_whisper() and ed_state.backend_name() != "fake":
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
    pipeline_io.remove_runtime(ed_state.runtime_path_dir(), ed_state.TOOL_ID, ed_state.PORT)
    ed_state.clear_mark()


def mounted_elsewhere():
    """入口(start.bat)の統合サーバーの中で文字起こしツールが動いていれば、その URL。
    同じ transcripts/ を2つのサーバーで書き合わない・認識ワーカーを2つ動かさないよう、serve.py を直接起動したときはそちらを開くだけにする。"""
    info = _runtime.read_runtime(ed_state.runtime_path_dir(), ed_state.TOOL_ID)
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
    print("保存先:", _workdata.TX_DIR)
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
