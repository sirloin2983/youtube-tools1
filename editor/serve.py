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
  評価ドリル(マスタープラン Q4。docs/plan/q3-q4-design.md の (c)。本体は ed_drill.py。画面は編集の ?doc=<id>&drill=1):
  GET  /api/drill/next?skip=<id,…>  次の評価用の動画 1 本(まだ確かめていない・直近 10 分に更新していない・処理中でない・動画がある)を乱数で
  POST /api/drill/reviewed   {id, baseUpdatedAt, via?} 「全部聞いて直した」印 evalReviewed と残りの行の校正済み(updatedAt が違えば 409)
  POST /api/drill/unreviewed {id, baseUpdatedAt} 確かめ済みの印を外す
  GET  /api/drill/status     定点(確かめ済みの評価用の動画 15 分)の残りと条件(話者・配信・重なり・BGM・呼び名)
  GET  /api/drill/candidates?id=  話者の候補(覚えた声 → メンバーのフォルダ → 配信の文脈)

127.0.0.1 にのみバインドし、Host / Origin / Sec-Fetch-Site を検査する(画面 / への遷移だけは、他のツールのリンクから開けるよう別扱い)。
"""
import array
import bisect
import difflib
import faulthandler
import gc
import hashlib
import itertools
import json
import logging
import logging.handlers
import math
import os
import queue
import re
import shutil
import socket
import subprocess
import sys
import tarfile
import threading
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
import uuid
import wave
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))   # 別のフォルダから起動しても、隣の部品(pipeline_io.py・resolve_export.py)を読めるように


def _load_core():
    """共通部品 ytt_core(リポジトリ直下。統合計画の段階2)を読み込めるようにする。
    探す場所: 環境変数 YTT_CORE_DIR(一時フォルダに写して動かすテスト用)→ このフォルダの1つ上。sys.path の末尾に足す(隣の部品を隠さないため)。"""
    here = os.path.dirname(os.path.abspath(__file__))
    for d in (os.environ.get("YTT_CORE_DIR"), os.path.dirname(here)):
        if d and os.path.isfile(os.path.join(d, "ytt_core", "__init__.py")):
            if d not in sys.path:
                sys.path.append(d)
            return
    raise SystemExit("共通部品 ytt_core が見つかりません(%s の隣に ytt_core フォルダが必要です)。"
                     "リポジトリのフォルダの中身をまとめて置き直してください" % here)


_load_core()
from ytt_core import datadir as _datadir, fsio as _fsio, httpsec, layout as _layout, jobs as _heavy, runtime as _runtime, schemas as _yschemas, tools as _tools  # noqa: E402
import roster as _roster  # noqa: E402  (名簿の呼び名・配信ごとの文脈。隣の部品)
import ed_state, ed_store, ed_relink, ed_media, ed_jobs, ed_speakers, ed_learn, ed_misc, ed_evalaudio  # noqa: E402,F401  (分けた部品。段10。ed_evalaudio = 評価用の音声)
import ed_drill  # noqa: E402,F401  (評価ドリルと定点の「あと何分」。マスタープラン Q4)
import ed_evalbatch  # noqa: E402,F401  (評価用の動画のまとめての文字起こし。マスタープラン Q4)
import ed_alt  # noqa: E402,F401  (2つ目のエンジンとの食い違いの候補。精度改善 第2版 D1-b)
import ed_ytcap  # noqa: E402,F401  (元の配信の YouTube の字幕との食い違いの候補。案 A1)
import ed_retime  # noqa: E402,F401  (字幕の読む速さの印・行の時刻を単語の時刻に合わせる候補。2026-10-05)


APP_ID = "transcribe-tool"
SERVER_VERSION = "0.57.0"  # app.js 側の APP_VERSION と揃える(版の正はここ。入口 home/launch.py がこの行を読む。部品は ed_state.SERVER_VERSION で読む)
ed_state.APP_ID, ed_state.SERVER_VERSION = APP_ID, SERVER_VERSION


# ---------- 分けた部品(段10。docs/plan/phase10-code-split.md) ----------
# serve.py の名前の受付: serve.py に無い名前は分けた部品から読み、S.名前 = … の差し替えはその名前を持つ部品へ転送する
# (テスト・認識ワーカー・dev/eval_asr.py・入口の取り込みは、今までどおり serve の名前で使える)
_ED_MODULES = (ed_state, ed_store, ed_relink, ed_media, ed_jobs, ed_speakers, ed_learn, ed_misc, ed_evalaudio, ed_drill, ed_evalbatch, ed_alt, ed_ytcap)
_ED_MODULES += (ed_retime,)   # 読む速さ・時刻の候補(2026-10-05。足すときは上の行を書き換えずにこの形で)


_ED_OWNER = {}   # 名前 → 持ち主の部品(読み込んだ時点の表。mock が一度消してから戻すときも、持ち主が分かるように)
for _m in reversed(_ED_MODULES):
    _ED_OWNER.update({_k: _m for _k in _m.__dict__ if not _k.startswith("__")})


def _ed_owner(name):
    m = _ED_OWNER.get(name)
    if m is not None:
        return m
    for m in _ED_MODULES:
        if name in m.__dict__:
            return m
    return None


def __getattr__(name):   # serve.名前 で、serve.py に無い名前を分けた部品から読む(PEP 562。sys.modules に登録せずに読み込んだときも働く)
    m = _ed_owner(name)
    if m is None:
        raise AttributeError("serve に %s はありません" % name)
    return getattr(m, name)


class _ServeModule(type(sys)):
    def __setattr__(self, name, value):   # serve.名前 = … を、その名前を持つ部品へ(テストの差し替え・入口の ALLOWED_HOSTS・ワーカーの IN_WORKER)
        m = None if name in self.__dict__ else _ed_owner(name)
        if m is None:
            super().__setattr__(name, value)
        else:
            setattr(m, name, value)

    def __delattr__(self, name):   # unittest.mock の patch.object は戻すときに「消す → 無ければ元の値を入れ直す」ので、消すのも部品へ
        m = None if name in self.__dict__ else _ed_owner(name)
        if m is None:
            super().__delattr__(name)
        else:
            delattr(m, name)


_me = sys.modules.get(__name__)
if _me is not None and _me.__dict__ is globals():   # 登録されて読み込まれたとき(普通の import・入口の取り込み)だけ。契約テストのように登録しない読み込みは読むだけ
    _me.__class__ = _ServeModule


# ---------- HTTP ----------
QUIET_PATHS = ("/api/jobs", "/media", "/api/siblings", "/api/progress", "/api/clip-info", "/api/peaks", "/api/edit", "/api/doc-for", "/api/effort", "/api/drill/status")   # 画面が頻繁に呼ぶ・パスを含むので、黒い画面に出さない
PAGE_HEADERS = httpsec.PAGE_HEADERS


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
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _json(self, code, obj):
        self._send(code, json.dumps(obj, ensure_ascii=False).encode("utf-8"), "application/json")

    def _err(self, e):
        self._json(e.status, dict(e.extra, error=e.code, message=e.message))

    def _fail(self, code, error, message):
        """画面の api() が理由を表示できるよう、エラーも JSON で返す(以前は 403/413/415 が素の文字列で「エラー 403」としか出なかった)。"""
        self._json(code, {"error": error, "message": message})

    def _read_json(self):
        if (self.headers.get("Content-Type") or "").split(";")[0].strip() != "application/json":
            self._fail(415, "bad_type", "Content-Type は application/json にしてください")
            return None
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            self._fail(400, "bad_length", "Content-Length が正しくありません")
            return None
        if length <= 0 or length > ed_state.MAX_BODY:
            self._fail(413, "too_big", "送る内容が空か、大きすぎます(最大%dMB)" % (ed_state.MAX_BODY // 1048576))
            return None
        try:
            obj = json.loads(self.rfile.read(length), parse_constant=ed_state._reject_json_constant)   # NaN / Infinity は受け付けない(保存すると画面の JSON.parse が壊れる)
        except ValueError:
            self._fail(400, "bad_json", "JSON として読めません")
            return None
        if not isinstance(obj, dict):
            self._fail(400, "bad_json", "JSON のオブジェクトを送ってください")
            return None
        return obj

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
        try:
            if u.path in ("/", "/index.html"):
                with open(ed_state.INDEX, "rb") as f:
                    return self._send(200, f.read(), "text/html; charset=utf-8", PAGE_HEADERS)
            if u.path == "/app.js":
                with open(ed_state.APP_JS, "rb") as f:
                    return self._send(200, f.read(), "text/javascript; charset=utf-8")
            if u.path == "/ui-kit.js":
                with open(ed_state.UI_KIT_JS, "rb") as f:
                    return self._send(200, f.read(), "text/javascript; charset=utf-8")
            if u.path.lstrip("/") in ed_state.PAGE_JS and os.path.isfile(os.path.join(ed_state.ROOT, u.path.lstrip("/"))):
                with open(os.path.join(ed_state.ROOT, u.path.lstrip("/")), "rb") as f:
                    return self._send(200, f.read(), "text/javascript; charset=utf-8")
            if u.path == "/api/ping":
                w = ed_jobs.WORKER   # 認識ワーカーの状態(入口の「調子」が読む。段9 9-1)
                return self._json(200, {"app": ed_state.APP_ID, "version": ed_state.SERVER_VERSION,
                                        "worker": {"alive": w.alive(), "pid": (w.proc.pid if w.proc is not None else None), "starts": w.starts,
                                                   "lastUsedAgo": (int(time.time() - w.last_used) if w.last_used else None), "silenceTimeoutSec": ed_jobs.WORKER_SILENCE_TIMEOUT}})
            if u.path == "/api/siblings":
                return self._json(200, ed_state.pio().siblings(ed_misc.runtime_path_dir(), ed_state.TOOL_ID, ed_state.PORT, self_path=ed_state.BASE_PATH))
            if u.path == "/api/clip-info":
                return self._json(200, ed_misc.clip_info((q.get("path") or [""])[0]))
            if u.path == "/api/transcript-v1":
                return self._json(200, ed_misc.transcript_v1((q.get("id") or [""])[0]))
            if u.path == "/api/roster":
                return self._json(200, ed_learn.load_roster())
            if u.path == "/api/tools":
                return self._json(200, {"ffmpeg": bool(ed_state.find_ffmpeg()), "fasterWhisper": ed_state.has_faster_whisper(), "cuda": ed_state.gpu_ready(), "nvidia": ed_state.nvidia_gpu(),
                                        "backend": ed_state.backend_name(), "diarize": ed_speakers.diar_info(), "models": ed_state.MODELS, "langs": ed_state.LANGS, "root": ed_state.TX_DIR,
                                        "envWarnings": list(_env_warnings), "alt": ed_alt.alt_info(), "ytcap": ed_ytcap.ytcap_info(), **ed_jobs.engines_info()})
            if u.path == "/api/settings":
                try:
                    with open(ed_state.SETTINGS, "rb") as f:
                        raw = f.read()
                    return self._send(200, raw[3:] if raw.startswith(b"\xef\xbb\xbf") else raw, "application/json")
                except OSError:
                    return self._json(200, {})
            if u.path == "/api/marker":
                return self._json(200, ed_misc.read_marker())
            if u.path == "/api/voices":   # A-3: 覚えている声の一覧(特徴そのものは返さない)
                return self._json(200, {"voices": ed_speakers.voices_summary(), "match": ed_speakers.VOICE_MATCH})
            if u.path == "/api/overlap-drafts":   # 重なりの所の空の行の候補(読むだけ。判別の記録 diar.json の声の区間から。2026-10-05)
                return self._json(200, ed_speakers.ovdraft_for_doc((q.get("id") or [""])[0], (q.get("kinds") or [None])[0]))
            if u.path == "/api/voices/preview":   # 段1(監査17・18): 覚える前の確認(読むだけ。話者の名前を返すので、ほかの GET と同じ Host/Origin 検査の下)
                return self._json(200, ed_speakers.voice_preview((q.get("tid") or [""])[0], (q.get("embedding") or [""])[0]))
            if u.path == "/api/transcribed-ranges":
                return self._json(200, {"items": ed_misc.transcribed_ranges()})
            if u.path == "/api/jobs":
                with ed_jobs._jobs_lock:
                    return self._json(200, {"jobs": [ed_jobs.public_job(ed_jobs._jobs[i]) for i in ed_jobs._order if i in ed_jobs._jobs]})
            if u.path == "/api/transcripts":
                return self._json(200, {"items": ed_store.list_transcripts()})
            if u.path == "/api/learned":
                mc = (q.get("min") or ["1"])[0]
                return self._json(200, ed_learn.learned_candidates(max(1, min(20, int(mc))) if mc.isdigit() else 1))
            if u.path == "/api/suggest":
                tid = (q.get("id") or [""])[0]
                if not ed_state.TID_RE.match(tid):
                    raise ed_state.ApiError("not_found", "文字起こしが見つかりません", 404)
                return self._json(200, ed_learn.suggest_for_doc(tid))
            if u.path == "/api/metrics":
                tid = (q.get("id") or [""])[0]
                if tid and not ed_state.TID_RE.match(tid):
                    raise ed_state.ApiError("not_found", "文字起こしが見つかりません", 404)
                sc = (q.get("scope") or ["all"])[0]
                return self._json(200, ed_learn.all_metrics(tid or None, (q.get("legacy") or ["0"])[0] == "1", sc if sc in ("all", "eval", "train") else "all"))
            if u.path == "/api/eval-baselines":
                return self._json(200, {"items": ed_learn.read_baselines()})
            if u.path == "/api/evals":
                tid = (q.get("id") or [""])[0]
                if tid and not ed_state.TID_RE.match(tid):
                    raise ed_state.ApiError("not_found", "文字起こしが見つかりません", 404)
                return self._json(200, {"items": ed_misc.list_evals(tid or None)})
            if u.path == "/api/eval":
                return self._json(200, ed_misc.read_eval((q.get("id") or [""])[0]))
            if u.path == "/api/progress":
                return self._json(200, ed_misc.progress_stats())
            if u.path == "/api/drill/status":   # 評価ドリル(Q4): 定点の「あと何分」と条件
                return self._json(200, ed_drill.drill_status())
            if u.path == "/api/drill/next":     # 次の評価用の動画 1 本(読むだけ。skip = このドリルで飛ばした文書)
                return self._json(200, ed_drill.drill_next((q.get("skip") or [""])[0]))
            if u.path == "/api/drill/candidates":   # 話者の候補(ドリル・話者のカードの「全行をこの人に」)
                return self._json(200, ed_drill.drill_candidates((q.get("id") or [""])[0]))
            if u.path == "/api/dataset":
                return self._json(200, ed_learn.dataset_stats())
            if u.path == "/api/history":
                return self._json(200, {"items": ed_store.list_history((q.get("id") or [""])[0])})
            if u.path == "/api/transcript":
                d = ed_store.read_transcript((q.get("id") or [""])[0])
                return self._json(200, dict(d, evalLocked=ed_relink.in_eval_dir(d.get("sourcePath"))))   # 評価用のフォルダの動画(画面で外せない)
            if u.path == "/api/eval-folders":
                return self._json(200, ed_relink.eval_folders_info())
            if u.path == "/api/eval-audio":   # 評価用の音声(flac)の作成の状態(本数・作った数・残り・大きさ・最後のエラー)
                return self._json(200, ed_evalaudio.status())
            if u.path == "/api/eval-batch":   # 評価用の動画のまとめての文字起こしの状態(Q4)
                return self._json(200, ed_evalbatch.eval_batch_status())
            if u.path == "/api/edit":
                return self._json(200, ed_store.get_edit((q.get("id") or [""])[0]))
            if u.path == "/api/edit/draft":
                return self._json(200, ed_store.edit_draft((q.get("id") or [""])[0], (q.get("rows") or [""])[0] == "1"))
            if u.path == "/api/edit/pack-readme":
                return self._json(200, ed_store.pack_readme((q.get("id") or [""])[0]))
            if u.path == "/api/doc-for":
                return self._json(200, {"doc": ed_store.find_doc_for_media((q.get("path") or [""])[0])})
            if u.path == "/api/peaks":
                return self._peaks((q.get("id") or [""])[0])
            if u.path == "/media":
                return self._media((q.get("id") or [""])[0])
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
        size = os.path.getsize(path)
        ctype = ed_state.MEDIA_TYPES[os.path.splitext(path)[1].lower()]
        a, b = 0, size - 1
        m = re.match(r"^bytes=(\d*)-(\d*)$", self.headers.get("Range") or "")
        code = 200
        if m and (m.group(1) or m.group(2)):
            if m.group(1):
                a = int(m.group(1))
                b = int(m.group(2)) if m.group(2) else size - 1
            else:
                a = max(0, size - int(m.group(2)))
            b = min(b, size - 1)
            if a > b or a >= size:
                return self._send(416, b"", extra={"Content-Range": "bytes */%d" % size})
            code = 206
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Length", str(b - a + 1))
        if code == 206:
            self.send_header("Content-Range", "bytes %d-%d/%d" % (a, b, size))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        if self.command == "HEAD":
            return
        try:
            with open(path, "rb") as f:
                f.seek(a)
                left = b - a + 1
                while left > 0:
                    chunk = f.read(min(65536, left))
                    if not chunk:
                        break
                    self.wfile.write(chunk)
                    left -= len(chunk)
        except (BrokenPipeError, ConnectionError, OSError):
            pass

    def _post(self):
        if not self._guard(True):
            return
        path = self.path.split("?", 1)[0]
        obj = self._read_json()
        if obj is None:
            return
        try:
            if path == "/api/transcribe":
                spec = ed_jobs.validate_job(obj)
                return self._json(200, ed_jobs.public_job(ed_jobs.add_job(spec)))
            if path == "/api/diarize":
                return self._json(200, ed_jobs.public_job(ed_jobs.add_job(ed_speakers.validate_diarize(obj), "diarize")))
            if path == "/api/voices/learn":   # A-3: 名前を付けた話者の声を覚える(ジョブ)
                return self._json(200, ed_jobs.public_job(ed_jobs.add_job(ed_speakers.validate_voice_learn(obj), "voice-learn")))
            if path == "/api/speakers/sub":   # 話者ごとの字幕の見た目(今は色)を名前で入れる(入口のまとめて実行が友人の指定を覚える。2026-10-05)
                return self._json(200, ed_speakers.speakers_sub_apply(obj))
            if path == "/api/voices/delete":
                ed_speakers.delete_voice(str(obj.get("embedding") or ed_speakers.DIAR_EMB_DEFAULT), str(obj.get("name") or "")[:60])
                return self._json(200, {"ok": True, "voices": ed_speakers.voices_summary()})
            if path == "/api/retranscribe":
                return self._json(200, ed_jobs.public_job(ed_jobs.add_job(ed_jobs.validate_retranscribe(obj), "retranscribe")))
            if path == "/api/redo":
                return self._json(200, ed_jobs.public_job(ed_jobs.add_job(ed_jobs.redo_spec(str(obj.get("tid") or ""), obj), "redo")))
            if path == "/api/alt":   # 2つ目のエンジンで聞く(D1-b)。文書は書き換えないので、編集は止めない
                return self._json(200, ed_jobs.public_job(ed_jobs.add_job(ed_alt.alt_spec(str(obj.get("id") or obj.get("tid") or ""), obj), "alt")))
            if path == "/api/ytcap":   # 元の配信の YouTube の字幕を取って比べる(案 A1)。文書は書き換えないので、編集は止めない
                return self._json(200, ed_jobs.public_job(ed_jobs.add_job(ed_ytcap.ytcap_spec(str(obj.get("id") or obj.get("tid") or ""), obj), "ytcap")))
            if path == "/api/scan-folder":
                return self._json(200, ed_misc.scan_folder(obj.get("path"), obj.get("recursive") is True))
            if path == "/api/transcribe-batch":
                return self._json(200, ed_misc.add_batch(obj))
            if path == "/api/settings/patch":   # ほかの画面(ホーム・スタジオのまとめて実行の欄)から、決まった項目だけを直す
                return self._json(200, ed_learn.patch_settings(obj))
            if path == "/api/eval-baseline":
                return self._json(200, ed_learn.record_baseline(obj.get("label")))
            if path == "/api/abtest":
                return self._json(200, ed_jobs.public_job(ed_jobs.add_job(ed_misc.validate_abtest(obj), "abtest")))
            if path == "/api/archive":
                n = ed_learn.start_archive(obj.get("tid") or None, obj.get("full") is not False)
                return self._json(200, {"ok": True, "docs": n})
            if path == "/api/restore":
                tid = str(obj.get("id", ""))
                doc = ed_store.restore_history(tid, obj.get("ts"))
                return self._json(200, {"ok": True, "updatedAt": doc["updatedAt"]})
            if path == "/api/suggest/feedback":
                return self._json(200, {"ok": True, "n": ed_learn.record_feedback(obj)})
            if path == "/api/export-corrections":
                tid = obj.get("tid")
                if tid is not None and not ed_state.TID_RE.match(str(tid)):
                    raise ed_state.ApiError("bad_request", "文字起こしの指定が正しくありません", 400)
                zp, n, na, skipped = ed_learn.export_corrections(str(tid) if tid else None, obj.get("audio") is not False, "proofed" if obj.get("scope") == "proofed" else "changed")
                try:
                    if n == 0:
                        raise ed_state.ApiError("empty", "書き出せる修正がありません(修正した行が無いか、修正前の出力が残っていない文字起こしです)", 400)
                    self.send_response(200)
                    self.send_header("Content-Type", "application/zip")
                    self.send_header("Content-Length", str(os.path.getsize(zp)))
                    self.send_header("Content-Disposition", 'attachment; filename="corrections.zip"')
                    self.send_header("X-Clips", "%d,%d,%d" % (n, na, skipped))
                    self.send_header("Access-Control-Expose-Headers", "X-Clips")
                    self.send_header("Cache-Control", "no-store")
                    self.send_header("X-Content-Type-Options", "nosniff")
                    self.end_headers()
                    with open(zp, "rb") as f:
                        while True:
                            chunk = f.read(65536)
                            if not chunk:
                                break
                            self.wfile.write(chunk)
                    return
                except (BrokenPipeError, ConnectionError):
                    return
                finally:
                    try:
                        os.unlink(zp)
                    except OSError:
                        pass
            if path == "/api/resolve-package":
                import resolve_export
                tid = str(obj.get("tid") or "")
                if not ed_state.TID_RE.match(tid):
                    raise ed_state.ApiError("bad_request", "文字起こしの指定が正しくありません", 400)
                zp = tmp_dir = None
                try:
                    try:   # 配信者の名前 → 字幕の文字の色(ytt_core/colors.py。docs/archive/followup-2026-09-27.md の 4)
                        from ytt_core import colors as _colors
                        who, hex_ = _colors.resolve(obj.get("streamer") if isinstance(obj.get("streamer"), str) else "")
                    except ValueError as e:
                        raise ed_state.ApiError("bad_streamer", str(e), 400)
                    tdoc = ed_store.read_transcript(tid)
                    spk_map = _colors.speaker_colors(s.get("name") for s in tdoc.get("speakers") or [] if isinstance(s, dict))[0]                         if obj.get("speakerColors") is not False else {}   # A-2: 話者の名前ごとの字幕の色(既定はオン)
                    ed, _broken = ed_store.read_edit(tid)   # 「編集」のカットがあれば、そのとおりに(3 パック のタブのパックと同じ区間)
                    zp, tmp_dir, info = resolve_export.create_package(tdoc, str(obj.get("fps") or "30"),
                                                                      str(obj.get("size") or "") or None, ed_state.SERVER_VERSION,
                                                                      keeps=ed_store.edit_keeps_sec(ed) if ed and ed["clips"] else None,
                                                                      row_edge=ed_learn.load_settings().get("rowEdge"), backup=obj.get("backup") is True,
                                                                      wrap=ed_store.wrap_arg(obj.get("wrap"), obj.get("size")),
                                                                      color={"hex": hex_, "who": who} if hex_ else None,
                                                                      speaker_colors=spk_map)
                    self.send_response(200)
                    self.send_header("Content-Type", "application/zip")
                    self.send_header("Content-Length", str(os.path.getsize(zp)))
                    self.send_header("Content-Disposition", 'attachment; filename="resolve-package.zip"')
                    self.send_header("X-Resolve-Cuts", str(info["cuts"]))
                    self.send_header("X-Resolve-Captions", str(info["captions"]))
                    self.send_header("X-Resolve-Handles", "1" if info["media"]["hasEditHandles"] else "0")
                    self.send_header("Access-Control-Expose-Headers", "X-Resolve-Cuts, X-Resolve-Captions, X-Resolve-Handles")
                    self.send_header("Cache-Control", "no-store")
                    self.send_header("X-Content-Type-Options", "nosniff")
                    self.end_headers()
                    with open(zp, "rb") as f:
                        while True:
                            chunk = f.read(65536)
                            if not chunk:
                                break
                            self.wfile.write(chunk)
                    return
                except resolve_export.ResolveExportError as e:
                    raise ed_state.ApiError("resolve_export", str(e), 400)
                except (BrokenPipeError, ConnectionError):
                    return
                finally:
                    if tmp_dir:
                        shutil.rmtree(tmp_dir, ignore_errors=True)
            if path == "/api/export-file":
                return self._json(200, ed_misc.export_file(obj))
            if path == "/api/open-video":
                return self._json(200, ed_store.open_video(obj))
            if path == "/api/relink/check":
                return self._json(200, ed_relink.relink_check(obj))
            if path == "/api/relink":
                return self._json(200, ed_relink.relink_doc(obj))
            if path == "/api/relink/missing":
                return self._json(200, ed_relink.relink_missing())
            if path == "/api/relink/find":
                return self._json(200, ed_relink.relink_find(obj))
            if path == "/api/eval-folders/organize":
                return self._json(200, ed_relink.eval_organize("button"))
            if path == "/api/eval-folders/settle":
                return self._json(200, ed_relink.eval_settle(obj))
            if path == "/api/eval-batch/start":
                return self._json(200, ed_evalbatch.eval_batch_start(obj))
            if path == "/api/eval-batch/stop":
                return self._json(200, ed_evalbatch.eval_batch_stop(obj))
            if path == "/api/eval-batch/redo":   # 未確認で手つかずの評価用を作り直す(dryRun = 数えるだけ)
                return self._json(200, ed_evalbatch.eval_batch_redo(obj))
            if path == "/api/eval-batch/redo-one":   # 開いている評価用の動画 1 本だけを今の設定ですぐ作り直す(人が手を入れていれば force のときだけ)
                return self._json(200, ed_evalbatch.eval_batch_redo_one(obj))
            if path == "/api/pick":
                return self._json(200, ed_relink.pick_path(obj))
            if path == "/api/resplit":
                return self._json(200, ed_jobs.resplit_doc(obj))
            if path == "/api/retime":   # 行の時刻を単語の時刻に合わせる候補(読むだけ。ed_retime)
                return self._json(200, ed_retime.retime_doc(obj))
            if path == "/api/edit/pack":
                return self._json(200, ed_store.record_pack(obj))
            if path == "/api/edit/preview":
                return self._json(200, ed_store.edit_preview(obj))
            if path == "/api/effort":
                return self._json(200, ed_store.add_effort(obj))
            if path == "/api/drill/reviewed":     # 評価ドリル(Q4): 動画を全部聞いて直した印(409 = 別の所で変わった)
                return self._json(200, ed_drill.drill_reviewed(obj))
            if path == "/api/drill/unreviewed":   # 確かめ済みの印を外す
                return self._json(200, ed_drill.drill_unreviewed(obj))
            if path == "/api/transcribe/cancel":
                ed_jobs.cancel_job(obj.get("id"))
                return self._json(200, {"ok": True})
        except ed_state.ApiError as e:
            return self._err(e)
        self._fail(404, "not_found", "その操作はありません")

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
                with ed_learn._settings_lock:   # ほかの画面から api/settings/patch で直す項目は、丸ごとの保存ではサーバーの値を残す(古い画面が戻さないように)
                    cur = ed_learn.load_settings()
                    obj = {k: v for k, v in obj.items() if k not in ed_learn.SETTINGS_PATCH_KEYS}
                    obj.update({k: cur[k] for k in ed_learn.SETTINGS_PATCH_KEYS if k in cur})
                    ed_state.atomic_write(ed_state.SETTINGS, json.dumps(obj, ensure_ascii=False, indent=1).encode("utf-8"))
                return self._json(200, {"ok": True})
            if u.path == "/api/transcript":
                tid = (urllib.parse.parse_qs(u.query).get("id") or [""])[0]
                doc = ed_store.save_transcript(tid, obj)
                return self._json(200, {"ok": True, "updatedAt": doc["updatedAt"], "evalSet": doc.get("evalSet") is True,
                                        "evalReviewed": doc.get("evalReviewed")})   # 確かめ済みの印(評価用を外すと消える。画面の表示を合わせる)
            if u.path == "/api/edit":
                if len(json.dumps(obj)) > ed_store.MAX_EDIT_BYTES:
                    raise ed_state.ApiError("too_big", "区間が多すぎて保存できません", 413)
                return self._json(200, ed_store.save_edit((urllib.parse.parse_qs(u.query).get("id") or [""])[0], obj))
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
        tid = (urllib.parse.parse_qs(u.query).get("id") or [""])[0]
        try:
            with ed_store._save_lock:   # 話者判別・再認識の書き込みと重ならないように(読み直しのあとに消すと、書き込みで生き返っていた)
                ed_store.read_transcript(tid)
                os.unlink(ed_store.tx_path(tid))
                for extra in (ed_store.edit_path(tid), os.path.join(ed_state.TX_DIR, tid + ".edit.broken.json"), ed_jobs.words_path(tid),
                              ed_jobs.asr_path(tid), ed_speakers.diar_path(tid),
                              ed_alt.alt_path(tid), ed_ytcap.ytcap_path(tid)):   # 編集の内容(カット)・単語の時刻・話者判別の記録・2つ目のエンジンと YouTube の字幕の結果も一緒に
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
    pass  # (global は分割で外した)
    for p in range(start_port, start_port + 20):
        ver = probe(p)
        if ver == ed_state.SERVER_VERSION:
            return None, p
        if ver is not None:
            print("※ ポート%d では古い版のサーバーが動いています。その黒い画面を閉じておくと迷いません。" % p)
            continue
        try:
            srv = ThreadingHTTPServer(("127.0.0.1", p), Handler)
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
DATA_STATE = None


def set_data_dir(d):
    """作業データの置き場所を切り替える(起動時に1回。ジョブが動く前)。ワーカーにも環境変数で伝える"""
    pass  # (global は分割で外した)
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
    ed_jobs.WORKER_LOG = os.path.join(ed_state.DATA_DIR, "worker.log")
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
    global DATA_STATE
    ed_state.STUDIO_DATA = studio_data_path()
    if os.environ.get("TRANSCRIBE_DATA_DIR"):
        set_data_dir(os.environ["TRANSCRIBE_DATA_DIR"])
        return
    r = _datadir.prepare(ed_state.TOOL_ID, ed_state.ROOT, DATA_ITEMS, log=lambda m: print(m, flush=True))
    DATA_STATE = r
    for w in r["warnings"]:
        print("※ " + w, flush=True)
    set_data_dir(r["dir"])


def prepare(port, base_path="/", hooks=False):
    """待ち受け以外の起動の準備(ログ・前回の異常終了の確認・.runtime・環境チェック・ジョブのスレッド)。
    main() と、入口の統合サーバー(home/mount.py)の両方から呼ぶ。戻り値は .runtime の記録のパス(書けなければ None)。
    シグナルの受け取りは main() だけで行う(統合サーバーでは入口が受け取る)。"""
    pass  # (global は分割で外した)
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
        threading.Thread(target=ed_jobs.worker, daemon=True, name="tx-jobs").start()
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
    with ed_jobs._jobs_lock:
        return any(j["state"] in ed_jobs.ACTIVE_STATES for j in ed_jobs._jobs.values())


def finish():
    """終了の後始末: 動いているジョブを取り消し、認識ワーカーを終わらせ、.runtime の記録と起動中の印を消す。"""
    with ed_jobs._jobs_lock:
        active = [j["id"] for j in ed_jobs._jobs.values() if j["state"] in ed_jobs.ACTIVE_STATES]
    for jid in active:
        try:
            ed_jobs.cancel_job(jid)
        except ed_state.ApiError:
            pass
    ed_jobs.WORKER.close()
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
        print("入口の中ですでに起動しています。ブラウザで開きます:", live)
        if "--no-open" not in sys.argv:
            webbrowser.open(live)
        return
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    srv, port = make_server(int(args[0]) if args else 8775)
    url = "http://localhost:%d" % port
    if srv is None:
        print("すでに起動しています。ブラウザで開きます:", url)
        if "--no-open" not in sys.argv:
            webbrowser.open(url)
        return
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
