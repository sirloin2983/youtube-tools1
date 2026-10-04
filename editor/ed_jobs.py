# -*- coding: utf-8 -*-
"""「編集」のサーバーの部品: ジョブの列・認識ワーカー・声の検出のやり直し・単語の時刻・選んだ行/範囲/全体の再認識・疑わしい所の認識し直し(段10 で editor/serve.py から分けた。docs/plan/phase10-code-split.md)。

名前は serve.py からも見える(serve.py が受け付けて、この部品へ転送する。テストの S.名前 = … もここに入る)。
ほかの部品の名前は `ed_xxx.名前` の形で呼ぶたびに読む(差し替えが効くように。from … import はしない)。
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

from ytt_core import datadir as _datadir, fsio as _fsio, httpsec, layout as _layout, jobs as _heavy, runtime as _runtime, schemas as _yschemas, tools as _tools  # noqa: E402,F401
import roster as _roster  # noqa: E402,F401
import ed_alt  # noqa: E402,F401
import ed_learn  # noqa: E402,F401
import ed_lite  # noqa: E402,F401
import ed_misc  # noqa: E402,F401
import ed_relink  # noqa: E402,F401
import ed_speakers  # noqa: E402,F401
import ed_state  # noqa: E402,F401
import ed_store  # noqa: E402,F401
import tx_engines  # noqa: E402,F401   名前と版だけ(ネイティブの部品は読み込まない)
# ---------- ジョブ ----------
_jobs = {}
_order = []
_jobs_lock = threading.Lock()
_queue = queue.PriorityQueue()   # (優先度, 通し番号, jid)。話者判別は文字起こしの待機列を追い越せるよう優先度を分ける(実行中のジョブを中断はしない。次の空きで割り込む)
_seq_counter = itertools.count()
JOB_PRIORITY = {"diarize": 0, "alt": 2}   # 未指定(transcribe/retranscribe/abtest 等)は既定の1。数値が小さいほど先に実行(alt = 2つ目のエンジンで聞く = 普通の文字起こしより後。D1-b)
_models = {}
_model_lock = threading.Lock()
_model_used = [0.0]   # 最後にモデルを使った時刻(ジョブの終わりにも更新する)
try:
    MODEL_IDLE_SEC = max(0, int(os.environ.get("TRANSCRIBE_MODEL_IDLE_SEC", "3600")))
except ValueError:
    MODEL_IDLE_SEC = 3600
# 読み込んだモデル(large-v3 で数GB)は次のジョブのために残すが、この秒数ジョブが無ければ手放す(0 = 手放さない)。
# 画面を開いたまま他の作業(動画編集など)をするときにメモリを返すため。次の文字起こしでは読み込み直し(10〜30秒程度)が入る。
# 既定は 60 分(2026-10-04 に 15 分から延ばした。続けて作業するたびの読み込みを減らす。32GB なら large-v3 + 話者判別を1時間持ってよい。docs/plan/stability-review-2026-10.md)


def release_idle_models(now=None):
    """しばらく使っていないモデルを手放す。ワーカー(ジョブを実行するスレッド)がジョブの合間にだけ呼ぶので、使用中のモデルは消さない。
    サーバーのプロセスでは、認識ワーカー(別プロセス)ごと終わらせる(モデルのメモリを OS に確実に返す)。次のジョブで起動し直す。"""
    if MODEL_IDLE_SEC <= 0:
        return False
    now = time.time() if now is None else now
    if not IN_WORKER:
        return WORKER.stop_if_idle(MODEL_IDLE_SEC, now)
    with _model_lock:
        if not _models or now - _model_used[0] < MODEL_IDLE_SEC:
            return False
        ed_state.log.info("しばらく使っていないモデルを解放: %s(メモリ %s)", ", ".join("/".join(k) for k in _models), ed_state._mem())
        _models.clear()
    gc.collect()
    return True


class Cancelled(Exception):
    pass


# ---------- 認識ワーカー(別プロセス。統合計画の段階3-3) ----------
# faster-whisper(ctranslate2)と sherpa-onnx はネイティブコードで、メモリ不足・GPU のドライバなどで Python ごと落ちることがある。
# 入口の統合サーバーに取り込むと、同じプロセスにスタジオ・cut2resolve もいるので、落ちると全部が止まり編集中の内容が消える。
# そこで、モデルの読み込み・認識・話者判別だけを tx_worker.py(別プロセス)で行う。サーバー側のジョブの流れ(待機列・行の整形・保存)は変えない。
# やり取り: ワーカーの標準入力に要求を1行1件の JSON(ASCII)で送り、標準出力から途中経過・結果を1行1件で受け取る。1度に1つの要求だけ。
# 落ちたら(標準出力が閉じたら)そのジョブを「失敗」にし、次の要求でワーカーを起動し直す。しばらく使わなければワーカーごと終わらせてメモリを返す。
IN_WORKER = False   # tx_worker.py の中で True にする(そのときは load_model などが本体をその場で実行する)
WORKER_SCRIPT = os.path.join(ed_state.ROOT, "tx_worker.py")
WORKER_LOG = os.path.join(ed_state.DATA_DIR, "worker.log")
WORKER_LOG_MAX = 1024 * 1024
WORKER_CANCEL_GRACE = 15   # 取り消してから、この秒数で止まらなければワーカーを強制終了する
WORKER_SILENCE_TIMEOUT = 20 * 60   # ワーカーから何も届かない時間の上限(秒)。超えたら強制終了してそのジョブを失敗にする(黙ったワーカーを待ち続けて SLOTS を持ったまま他のツールを塞がない。夜間の見直し 高。2026-10-01 ユーザー決定)
WORKER_LINE_MAX = 8 * 1024 * 1024


def _worker_flags():
    """Windows: 黒い画面を増やさない・Ctrl+C / Ctrl+Break がワーカーに直接届かないようにする(終わらせるのは親の役目)。"""
    if os.name != "nt":
        return 0
    return getattr(subprocess, "CREATE_NO_WINDOW", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)


def _worker_priority():
    """Windows: 認識のワーカーは「通常より下」の優先度で動かす(2026-10-04)。長い文字起こしが CPU を使っている間も、
    画面の操作・スタジオの書き出し・パック作りが先に CPU を取れる(同時実行の上限 SLOTS は 2 のまま。docs/plan/stability-review-2026-10.md)。
    環境変数 TRANSCRIBE_WORKER_PRIORITY=normal で今までどおり"""
    if os.name != "nt" or os.environ.get("TRANSCRIBE_WORKER_PRIORITY", "").strip().lower() == "normal":
        return 0
    return getattr(subprocess, "BELOW_NORMAL_PRIORITY_CLASS", 0)


def worker_env():
    env = dict(os.environ)
    env["PYTHONUNBUFFERED"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    import ytt_core as _yc   # ワーカーも同じ ytt_core を使う(一時フォルダに写したテストでも見つかるように)
    env["YTT_CORE_DIR"] = os.path.dirname(os.path.dirname(os.path.abspath(_yc.__file__)))
    return env


class WorkerError(Exception):
    """ワーカーの中で起きた想定外の例外(元の型の名前を message に含める)。"""


class _CancelHandle:
    """job["proc"] に入れる、取り消し用の窓口。cancel_job() は proc.poll() / proc.terminate() を呼ぶので、同じ形にする
    (ffmpeg の子プロセスを止めるのと同じ仕組みで、ワーカーの処理も止められる)。"""

    def __init__(self, client, rid):
        self.client, self.rid, self.done = client, rid, False

    def poll(self):
        return 0 if self.done else None

    def terminate(self):
        if not self.done:
            self.client.cancel(self.rid)

    kill = terminate


class WorkerClient:
    """認識ワーカー(tx_worker.py)の起動・要求・取り消し・強制終了。要求は1度に1つ(ジョブを実行するスレッドは1本)。"""

    def __init__(self):
        self.lock = threading.RLock()     # 要求の直列化
        self.wlock = threading.Lock()     # 標準入力への書き込み(取り消しは HTTP のスレッドからも来る)
        self.proc = None
        self.log_fp = None
        self.rids = itertools.count(1)
        self.last_used = 0.0
        self.starts = 0
        self.killed_rid = None            # 取り消しで強制終了した要求(その要求は「中止」にする)
        self.closed = False
        self.q = queue.Queue()            # ワーカーの標準出力の行(読み取り専用のスレッドが入れる。待つ側は get(timeout) で時限を付ける)

    # ---- 起動・終了
    def alive(self):
        return self.proc is not None and self.proc.poll() is None

    def _spawn(self):
        if self.closed:
            raise ed_state.ApiError("stopping", "終了処理中のため、文字起こしを始められません", 503)
        if not os.path.isfile(WORKER_SCRIPT):
            raise ed_state.ApiError("missing_module", "tx_worker.py が見つかりません。ツールのフォルダの中身をまとめて更新してください", 500)
        try:
            if os.path.exists(WORKER_LOG) and os.path.getsize(WORKER_LOG) > WORKER_LOG_MAX:
                ed_state.replace_retry(WORKER_LOG, WORKER_LOG + ".old")
        except OSError:
            pass
        try:
            self.log_fp = open(WORKER_LOG, "ab")
        except OSError:
            self.log_fp = None
        self.proc = subprocess.Popen([ed_state.worker_python(), "-u", WORKER_SCRIPT], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                     stderr=self.log_fp or subprocess.DEVNULL, cwd=ed_state.ROOT, env=worker_env(), creationflags=_worker_flags() | _worker_priority())
        self.starts += 1
        self.q = queue.Queue()   # 起動ごとに新しい列(前のプロセスの読み残しを混ぜない)
        threading.Thread(target=self._reader, args=(self.proc, self.q), daemon=True, name="tx-worker-reader").start()
        ed_state.log.info("認識ワーカーを起動 pid=%s(%d回目)", self.proc.pid, self.starts)

    @staticmethod
    def _reader(p, q):
        """ワーカーの標準出力を読む専用のスレッド。readline 自体は止められないので、待つ側(_read)を queue.get(timeout) にして時限を付ける。
        EOF(b"")か、閉じられて読めなくなったら b"" を入れて終わる"""
        try:
            while True:
                line = p.stdout.readline(WORKER_LINE_MAX)
                q.put(line)
                if not line:
                    return
        except (OSError, ValueError):
            q.put(b"")

    def _ensure(self):
        if self.proc is not None and self.proc.poll() is not None:
            ed_state.log.warning("認識ワーカーが終わっていました(終了コード %s)。起動し直します", self.proc.returncode)
            self._reap()
        if self.proc is None:
            self._spawn()

    def _reap(self):
        p, self.proc = self.proc, None
        if p is not None:
            for f in (p.stdin, p.stdout):
                try:
                    f.close()
                except (OSError, ValueError):
                    pass
            try:
                p.wait(5)
            except subprocess.TimeoutExpired:
                pass
        if self.log_fp is not None:
            try:
                self.log_fp.close()
            except OSError:
                pass
            self.log_fp = None

    def kill(self):
        p = self.proc
        if p is not None and p.poll() is None:
            try:
                p.kill()
            except OSError:
                pass

    def stop(self, timeout=5):
        """ワーカーを終わらせる(次の要求で起動し直す)。要求の途中なら、その要求は失敗・中止になる。"""
        p = self.proc
        if p is None:
            return
        if p.poll() is None:
            try:
                with self.wlock:
                    p.stdin.write(b'{"op":"quit"}\n')
                    p.stdin.flush()
            except (OSError, ValueError):
                pass
            try:
                p.wait(timeout)
            except subprocess.TimeoutExpired:
                self.kill()
        if self.lock.acquire(timeout=timeout):
            try:
                if self.proc is p:
                    self._reap()
            finally:
                self.lock.release()

    def close(self):
        """サーバーの終了時。以後は起動しない。"""
        self.closed = True
        self.stop(3)

    def stop_if_idle(self, idle_sec, now=None):
        now = time.time() if now is None else now
        if not self.alive() or now - self.last_used < idle_sec:
            return False
        if not self.lock.acquire(blocking=False):   # 要求の途中(使用中)
            return False
        try:
            ed_state.log.info("しばらく使っていないので認識ワーカーを終了(モデルのメモリを返す)")
            self.stop()
            return True
        finally:
            self.lock.release()

    # ---- やり取り
    def _write(self, obj):
        data = (json.dumps(obj, ensure_ascii=True, separators=(",", ":")) + "\n").encode("ascii")
        with self.wlock:
            self.proc.stdin.write(data)
            self.proc.stdin.flush()

    def cancel(self, rid):
        """取り消し(HTTP のスレッドから)。ワーカーに伝え、WORKER_CANCEL_GRACE 秒で止まらなければ強制終了する。"""
        p = self.proc
        if p is None or p.poll() is not None:
            return
        try:
            self._write({"op": "cancel", "rid": rid})
        except (OSError, ValueError):
            pass

        def force():
            if self.proc is p and p.poll() is None and self._busy_rid == rid:
                ed_state.log.warning("認識ワーカーが取り消しに応じないため強制終了します")
                self.killed_rid = rid
                self.kill()
        t = threading.Timer(WORKER_CANCEL_GRACE, force)
        t.daemon = True
        t.start()

    _busy_rid = None

    def _read(self, rid):
        try:
            line = self.q.get(timeout=WORKER_SILENCE_TIMEOUT)
        except queue.Empty:   # 黙ったワーカー(ネイティブの部品で止まった・デッドロック)。待ち続けると SLOTS を持ったまま他のツールの重い処理まで塞ぐので、強制終了して失敗にする
            ed_state.log.error("認識ワーカーから %.0f 秒なにも届かないため強制終了します", WORKER_SILENCE_TIMEOUT)
            self.kill()
            self._reap()
            if self.killed_rid == rid:
                raise Cancelled()
            raise ed_state.ApiError("worker_hung", "文字起こしの部品(認識を行う別プロセス)が %d 分なにも応答しないため止めました。もう一度実行すると部品を起動し直します"
                                          "(モデルの初回のダウンロード中に出たときは、そのままもう一度実行してください。詳しくは worker.log)" % max(1, round(WORKER_SILENCE_TIMEOUT / 60)), 500)
        if not line:
            code = None
            try:
                code = self.proc.wait(5)
            except subprocess.TimeoutExpired:
                self.kill()
            self._reap()
            if self.killed_rid == rid:
                raise Cancelled()
            ed_state.log.error("認識ワーカーが異常終了しました(終了コード %s)", code)
            raise ed_state.ApiError("worker_crashed", "文字起こしの部品(認識を行う別プロセス)が途中で止まりました(終了コード %s)。"
                                             "メモリ不足などが考えられます。もう一度実行すると部品を起動し直します(詳しくは worker.log)" % code, 500)
        try:
            m = json.loads(line.decode("utf-8"))
        except (UnicodeDecodeError, ValueError):
            ed_state.log.warning("認識ワーカーの出力を読めません: %r", line[:200])
            return None
        return m if isinstance(m, dict) else None

    @staticmethod
    def _apply(job, m):
        k = m.get("k")
        if isinstance(job, dict) and k in ("phase", "state", "device", "progress"):
            v = m.get("v")
            if k == "progress":
                try:
                    v = max(0.0, min(0.99, float(v)))
                except (TypeError, ValueError):
                    return
            elif not isinstance(v, str):
                return
            job[k] = v[:200] if isinstance(v, str) else v

    @staticmethod
    def _error(m):
        code, msg = str(m.get("code") or ""), str(m.get("message") or "")[:500]
        if code == "cancelled":
            return Cancelled()
        if code == "exception":
            return WorkerError("%s: %s" % (m.get("type") or "Exception", msg))
        try:
            status = int(m.get("status") or 500)
        except (TypeError, ValueError):
            status = 500
        return ed_state.ApiError(code or "worker_error", msg or "文字起こしの部品でエラーが起きました", status)

    def stream(self, op, args, job=None):
        """要求を送り、("item", v) を途中で、最後に ("result", v) を返す生成器。エラーは例外(ApiError / Cancelled / WorkerError)。
        途中で使うのをやめた(close された)ときは、ワーカーに取り消しを伝えて結果を読み捨て、やり取りの順番をそろえてから抜ける。"""
        if isinstance(job, dict) and job.get("cancel"):   # 取り消し済みなら、ワーカーの起動も要求もしない
            raise Cancelled()
        with self.lock:
            self._ensure()
            rid = next(self.rids)
            handle = _CancelHandle(self, rid)
            self._busy_rid, self.killed_rid = rid, None
            if isinstance(job, dict):
                job["proc"] = handle
            finished = False
            try:
                try:
                    self._write(dict(args, op=op, rid=rid))
                except (OSError, ValueError):
                    self.kill()
                    self._read(rid)   # 閉じている → 異常終了として扱う
                while True:
                    m = self._read(rid)
                    if m is None or m.get("rid") != rid:
                        continue   # 以前の要求の読み残し・読めない行
                    ev = m.get("ev")
                    if ev == "set":
                        self._apply(job, m)
                    elif ev in ("item", "info"):   # info = 声の検出の結果(行より先に届く)
                        yield ev, m.get("v")
                    elif ev == "result":
                        finished = True
                        yield "result", m.get("v")
                        return
                    elif ev == "error":
                        finished = True
                        raise self._error(m)
            finally:
                handle.done = True
                if isinstance(job, dict) and job.get("proc") is handle:
                    job["proc"] = None
                if not finished and self.alive():
                    self._drain(rid)
                self._busy_rid = None
                self.last_used = time.time()

    def _drain(self, rid):
        """途中でやめた要求の残りを読み捨てる(止まらなければ強制終了)。"""
        self.cancel(rid)
        try:
            while self.proc is not None:
                m = self._read(rid)
                if m and m.get("rid") == rid and m.get("ev") in ("result", "error"):
                    return
        except (ed_state.ApiError, Cancelled):
            pass

    def call(self, op, args, job=None):
        """結果だけを返す要求(モデルの読み込み・話者判別)。"""
        g = self.stream(op, args, job)
        try:
            for kind, v in g:
                if kind == "result":
                    return v
        finally:
            g.close()
        raise ed_state.ApiError("worker_error", "文字起こしの部品から結果が返りませんでした", 500)


WORKER = WorkerClient()


class _Obj:
    def __init__(self, d):
        self.__dict__.update(d)


class _Segs:
    """RemoteModel.transcribe の行の生成器。読まずに close() しても、ワーカーとのやり取り(stream)を閉じる
    (始まっていない生成器の close() は finally を通らないため。声の検出が捨てすぎたときに、行を読まずにやり直す)"""

    def __init__(self, gen, stream):
        self.gen, self.stream = gen, stream

    def __iter__(self):
        return self

    def __next__(self):
        return next(self.gen)

    def close(self):
        self.gen.close()
        self.stream.close()


class RemoteModel:
    """ワーカーの中のモデルの代理。transcribe() は faster-whisper の WhisperModel.transcribe と同じ形 (行の生成器, 情報) を返す。
    行は属性(start・end・text・avg_logprob・no_speech_prob・compression_ratio・words)で読めるので、呼び出し側のコードは変えなくてよい。"""

    def __init__(self, client, name, device, params, job, engine=tx_engines.DEFAULT):
        self.client, self.name, self.device, self.job, self.engine = client, name, device, job, engine
        self.params = set(params or ())

    def transcribe(self, audio, **kw):
        if isinstance(audio, str):
            a = {"wav": audio}
        elif isinstance(audio, ed_speakers.WavSlice):   # 範囲の音声は、wav のパスとサンプルの範囲だけを渡す(ワーカーが読む)
            a = {"wav": audio.path, "from": audio.a, "to": audio.b}
        elif isinstance(audio, ed_speakers.WavRef):
            a = {"wav": audio.path}
        else:
            raise TypeError("認識する音声は wav のパスか WavRef / WavSlice で渡してください")
        args = {"name": self.name, "device": self.device, "audio": a, "kw": kw}
        if self.engine != tx_engines.DEFAULT:
            args["engine"] = self.engine
        g = self.client.stream("transcribe", args, self.job)
        info = _Obj({"language": kw.get("language"), "duration": None, "duration_after_vad": None})
        first = None
        try:   # faster-whisper と同じく、声の検出の結果(info)は行を読む前に分かるようにする(最初の知らせを先に読む)
            first = next(g)
        except StopIteration:
            pass
        except BaseException:
            g.close()
            raise
        if first and first[0] == "info" and isinstance(first[1], dict):
            info.__dict__.update({k: first[1].get(k) for k in ("duration", "duration_after_vad")})
            first = None

        def conv(v):
            return _Obj(dict(v, words=[_Obj(w) for w in v.get("words") or [] if isinstance(w, dict)]))

        def segs():
            try:
                if first and first[0] == "item" and isinstance(first[1], dict):
                    yield conv(first[1])
                for kind, v in g:
                    if kind == "item" and isinstance(v, dict):
                        yield conv(v)
            finally:
                g.close()
        return _Segs(segs(), g), info


def validate_job(req):
    src = ed_state.check_source(req.get("sourcePath"))
    dur = ed_state.media_duration(src)
    start = ed_state.num(req.get("start"), 0.0) or 0.0
    end = ed_state.num(req.get("end"))
    if start < 0:
        raise ed_state.ApiError("bad_range", "開始時刻が正しくありません", 400)
    if dur is not None and start >= dur - 0.5:
        raise ed_state.ApiError("bad_range", "開始時刻がファイルの長さ(%s)を超えています" % ed_state.fmt_hms(dur), 400)
    if end is None or (dur is not None and end > dur):
        end = dur
    if end is not None and end <= start + 0.5:
        raise ed_state.ApiError("bad_range", "終了は開始より後にしてください", 400)
    if end is not None and end - start > ed_state.MAX_SPAN_SEC:
        raise ed_state.ApiError("too_long", "1回に処理できるのは6時間までです。範囲を分けてください", 400)
    whole = start == 0 and (end is None or dur is None or abs(end - dur) < 0.5)
    # 切り抜きスタジオが書き出した mp4 なら、隣の .clip.json(youtube-tools-clip/v1)を読んで文書に残す(元の配信のどこかが分かる)。
    # 不正・別の版なら使わずに警告だけ(文字起こし自体は続ける)。範囲指定でも clip はそのまま残す:
    # 文書の時刻は「動画ファイルの先頭 = 0 秒」のままなので、元の配信の時刻は常に clip_offset(clip) + 行の時刻になる(範囲の開始で補正しない)
    pm = ed_state.pio(required=False)
    clip, clip_warn, _clip_path = pm.find_clip(src, dur) if pm else (None, None, None)
    warnings = [clip_warn] if clip_warn else []
    model = str(req.get("model") or "small").strip()
    if not ed_state.valid_model(model):
        raise ed_state.ApiError("bad_model", "モデル名が正しくありません", 400)
    lang = str(req.get("language") or "ja")
    if lang not in ed_state.LANGS:
        lang = "ja"
    glossary = [t.strip() for t in re.split(r"[\r\n,、]+", str(req.get("glossary") or "")) if t.strip()][:200]
    gauto = ed_learn.auto_glossary(glossary) if req.get("autoGloss") is not False else []
    ev = req.get("evalSet") is True   # 評価用として文字起こしする: 用語集・呼び名・置換辞書・学習した置換を使わない(docs/archive/project/eval-set-procedure.md の 2)
    into = None
    if req.get("intoDoc") not in (None, ""):
        # 「編集」の文字起こしの無い文書(文字起こしせずに開いた動画)に行を入れる。id・題名・作った日・clip・編集の内容はそのまま
        into = str(req.get("intoDoc"))
        target = ed_store.read_transcript(into)
        if os.path.normcase(os.path.abspath(str(target.get("sourcePath") or ""))) != os.path.normcase(src):
            raise ed_state.ApiError("bad_request", "文字起こしを入れる文書の動画と、選んだ動画が違います", 400)
        if ed_store.doc_has_rows(target):
            raise ed_state.ApiError("not_empty", "この文書にはもう行があります(新しい文字起こしとして作ってください)", 409)
        if not str(req.get("title") or "").strip():
            req = dict(req, title=target.get("title") or "")
        ev = ev or target.get("evalSet") is True
    ed_relink.eval_name_guard(src, ev)   # 評価用のフォルダの設定が消えているのに「評価用」のフォルダの動画なら止める(学習用に混ざらないように。master-plan Q0)
    ev = ev or ed_relink.in_eval_dir(src)   # 評価用のフォルダの動画は、画面のチェックが無くても評価用(2026-10-01)
    if ev:
        glossary, gauto = [], []
    title = str(req.get("title") or "")[:120] or os.path.splitext(os.path.basename(src))[0][:120]
    ctx = stream_context({"clip": clip, "title": title, "sourceName": os.path.basename(src), "sourcePath": src}, req.get("autoContext") is True and not ev)
    return {"sourcePath": src, "sourceName": os.path.basename(src), "start": round(start, 2), "end": round(end, 2) if end else None, "intoDoc": into,
            "duration": dur, "whole": whole, "model": model, "engine": req_engine(req, model), "language": lang, "beam": 1 if req.get("quality") == "fast" else 5,
            "device": req.get("device") if req.get("device") in ("cuda", "cpu") else "auto",
            "vadMode": req.get("vadMode") if req.get("vadMode") in ("weak", "normal", "off") else ("off" if req.get("vad") is False else "weak"),
            "boost": req.get("boost") is True, "autoDict": req.get("autoDict") is not False and not ev, "wordSplit": req.get("wordSplit") is not False,
            "splitChars": split_chars_for(req),
            "autoRedo": req.get("autoRedo") is True, "redoLarge": req.get("redoLarge") is not False,
            # 終わったら 2つ目のエンジンでも聞く(D1-b)。要求に無ければ(まとめて実行・古い画面)保存した設定 autoAlt
            "autoAlt": (req["autoAlt"] if isinstance(req.get("autoAlt"), bool) else ed_learn.load_settings().get("autoAlt") is True) and not ev,
            # 終わったら話者を自動で判別する(v0.50.0)。要求に無ければ保存した設定 autoDiarize。評価用はこの値によらず常に(ed_speakers.autodiar_after_transcribe)
            "autoDiarize": req["autoDiarize"] if isinstance(req.get("autoDiarize"), bool) else ed_learn.load_settings().get("autoDiarize") is True,
            "stripPunct": req.get("stripPunct") is not False, "glossary": glossary + gauto, "glossAuto": gauto, "context": ctx, "evalSet": ev,
            "autoLearned": req.get("autoLearned") is True and not ev, "clip": clip, "warnings": warnings,
            "title": title}


ACTIVE_STATES = ("queued", "loading", "extracting", "running")
EXCLUSIVE = {"diarize": ("diarize", "retranscribe", "redo", "voice-learn"), "voice-learn": ("diarize", "voice-learn"),
             "retranscribe": ("diarize", "retranscribe", "redo"),
             "redo": ("diarize", "retranscribe", "redo"), "abtest": ("abtest",), "alt": ("alt",)}   # 同じ文字起こしに同時に入れない組み合わせ


def add_job(spec, kind="transcribe"):
    with _jobs_lock:
        waiting = sum(1 for j in _jobs.values() if j["state"] in ACTIVE_STATES)
        if waiting >= ed_state.MAX_QUEUE:
            raise ed_state.ApiError("busy", "待機中のジョブが多すぎます(最大%d件)" % ed_state.MAX_QUEUE, 429)
        excl = EXCLUSIVE.get(kind)
        if excl and spec.get("tid") and any(j.get("kind") in excl and j["spec"].get("tid") == spec["tid"] and j["state"] in ACTIVE_STATES for j in _jobs.values()):
            # validate_* でも確かめているが、確認と登録の間に同じ要求が割り込めたので、登録と同じロックの中でもう一度確かめる
            raise ed_state.ApiError("busy", "この文字起こしは、すでに別の処理(話者判別・再認識・比較)の最中です", 409)
        jid = uuid.uuid4().hex[:12]
        job = {"id": jid, "title": spec["title"], "state": "queued", "phase": "順番待ち", "progress": 0.0, "tid": spec["tid"] if kind in ("diarize", "retranscribe", "redo", "voice-learn", "normalize", "alt") else None, "error": None,
               "segments": 0, "speakers": 0, "unsure": 0, "kind": kind, "device": "", "createdAt": int(time.time() * 1000), "cancel": False, "proc": None, "spec": spec}
        _jobs[jid] = job
        _order.append(jid)
        while len(_order) > 100:
            old = _order.pop(0)
            if _jobs.get(old, {}).get("state") not in ("queued", "loading", "extracting", "running"):
                _jobs.pop(old, None)
            else:
                _order.insert(0, old)
                break
        _queue.put((JOB_PRIORITY.get(kind, 1), next(_seq_counter), jid))
    return job


def public_job(j):
    out = {k: j[k] for k in ("id", "title", "state", "phase", "progress", "tid", "error", "segments", "speakers", "unsure", "kind", "device", "createdAt")}
    out["warnings"] = list((j.get("spec") or {}).get("warnings") or [])   # 例: 隣の .clip.json が壊れている・別の版(文字起こしは続ける)
    out["hasClip"] = bool((j.get("spec") or {}).get("clip"))
    out["into"] = (j.get("spec") or {}).get("intoDoc") or None   # 「編集」: 文字起こしの無い文書に入れる文字起こし(画面の「この動画を文字起こしする」)
    out["named"] = list(j.get("named") or [])       # A-3: 話者判別のあと、覚えている声で名前を付けた話者 [{"speaker", "name", "score"}]
    out["learned"] = list(j.get("learned") or [])   # A-3: 声を覚えた人の名前
    out["auto"] = bool((j.get("spec") or {}).get("auto"))   # 文字起こしのあとの自動の話者判別(v0.50.0)
    out["autoSkipped"] = j.get("autoSkipped") or ""   # 自動の判別を動き出すときにやめた理由(has_speakers・reviewed・empty)
    if j.get("voiceError"):
        out["warnings"].append(j["voiceError"])
    out["warnings"] += [w for w in (j.get("warnings") or []) if w not in out["warnings"]]   # ジョブの中で足した注意(以前は画面に届いていなかった)
    out["vadNote"] = j.get("vadNote") or ""          # 声の検出を緩めてやり直した(4-2)
    out["normNote"] = j.get("normNote") or ""        # 30fps にそろえた・そろえられなかった理由(Q1。ed_relink.norm_run)
    out["normOk"] = bool(j.get("normOk"))
    out["kept"], out["emptyKept"], out["loose"] = j.get("kept", 0), j.get("emptyKept", 0), j.get("loose", 0)   # 全体の再認識で残した行(3-4)
    return out


def extract_audio(job, spec, wav):
    ff = ed_state.find_ffmpeg()
    if not ff:
        raise ed_state.ApiError("no_ffmpeg", "ffmpeg が見つかりません(README の準備手順を確認してください)", 400)
    cmd = [ff, "-hide_banner", "-nostdin", "-y", "-protocol_whitelist", "file"]
    if spec["start"] > 0:
        cmd += ["-ss", "%.3f" % spec["start"]]
    cmd += ["-i", spec["sourcePath"]]
    if spec["end"]:
        cmd += ["-t", "%.3f" % (spec["end"] - spec["start"])]
    cmd += ["-vn"]
    if spec.get("boost"):  # 小さい声を持ち上げる(低域のこもりを削り、音量のばらつきをならす)
        cmd += ["-af", "highpass=f=70,dynaudnorm=f=200:g=15:m=15"]
    cmd += ["-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", wav]
    p = subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True,
                         encoding="utf-8", errors="replace")
    job["proc"] = p
    try:
        err = p.stderr.read()
        p.wait()
    finally:
        job["proc"] = None
        if p.poll() is None:
            p.kill()
        p.stderr.close()   # 読み終えたパイプを閉じる(閉じないと GC まで残る)
    if job["cancel"]:
        raise Cancelled()
    if p.returncode != 0 or not os.path.isfile(wav) or os.path.getsize(wav) < 1000:
        tail = " / ".join([l.strip() for l in (err or "").splitlines() if l.strip()][-2:])
        raise ed_state.ApiError("extract_failed", "音声を取り出せませんでした(音声トラックがないか、壊れたファイルの可能性): " + tail[:200], 400)


LATIN_MIN_LETTERS = 4   # 英字がこの数以上で、文字全体の LATIN_RATIO 以上を占め、
LATIN_RATIO = 0.3       # かつ「英字が LATIN_LONG 文字以上」か「英字の語が2つ以上」の行、
LATIN_LONG = 6          # または、英字と空白が LATIN_RUN 文字以上続く行を「英語の幻覚かも」とする(初期値。実データで調整する)
LATIN_RUN = 8
_LATIN_RUN_RE = re.compile(r"[A-Za-z][A-Za-z' ]{%d,}" % (LATIN_RUN - 1))


def latin_suspect(text, terms=()):
    """日本語の音声なのに英字が目立つ行か(英語のでたらめな文の幻覚に多い)。用語集にある英字の語(Apex など)は数えない。
    Apex・GG のような短い英単語が1つだけ混じる行は対象外(要確認だらけになるのを避ける)。"""
    t = str(text or "")
    for w in sorted({x for x in terms if x and re.search(r"[A-Za-z]", x)}, key=len, reverse=True):
        t = t.replace(w, "")
    t = re.sub(r"(?i)w{2,}|\b(?:lol|lmao|gg|wp|ok)\b", "", t)   # 笑いの「wwww」や定番の略語は数えない
    letters = len(re.findall(r"[A-Za-z]", t))
    if letters < LATIN_MIN_LETTERS:
        return False
    body = len(re.sub(r"[\W_]+", "", t))   # 記号・空白を除いた文字数(日本語も数える)
    if body and letters / body >= LATIN_RATIO and (letters >= LATIN_LONG or len(re.findall(r"[A-Za-z']+", t)) >= 2):
        return True
    return bool(_LATIN_RUN_RE.search(t))


SPARSE_MIN_SEC = 4.0    # 「長い区間に文字が少ない」行(docs/design/edit-tool-design.md の 12 ③-1): この長さより長くて
                        # (ちょうど 4.0 秒は含めない。疑似の文字起こしの行(4.0 秒に「テスト文N」)を対象にしないため。本物の行への影響は境目だけ)
SPARSE_MAX_CPS = 1.5    # 記号・空白を除いた文字数が 1 秒あたりこれ未満
SPARSE_FLAG = "長い区間に文字が少ない(抜けの可能性)"


def text_chars(text):
    """記号・空白を除いた文字数(文字と数字だけ。かな・漢字・英数字)"""
    return sum(1 for ch in str(text or "") if unicodedata.category(ch)[0] in "LN")


def sparse_row(start, end, text):
    """長い区間に文字が少ない行か(③-1)。取りこぼしを減らすために VAD を甘くしている(vadMode weak)ので、BGM やゲーム音が声として通り、
    Whisper が長い塊に単語1つを出したり、途中を飛ばしたりする(区間ごとの抜け)。その形をつかまえる"""
    try:
        dur = float(end) - float(start)
    except (TypeError, ValueError):
        return False
    return dur > SPARSE_MIN_SEC and text_chars(text) < SPARSE_MAX_CPS * dur


def _letters(text):
    """比べる用: NFKC・小文字・文字と数字だけ"""
    return "".join(ch for ch in unicodedata.normalize("NFKC", str(text or "")).lower() if unicodedata.category(ch)[0] in "LN")


def stock_phrase(text):
    """よくある誤認識の文か(時間は見ない): 以前からの HALLUC が含まれる・行のほとんどが HALLUC_LINE の文・音楽の表記だけ(♪・(音楽))"""
    t = str(text or "")
    if any(h in t for h in ed_state.HALLUC):
        return True
    if t.strip() and ed_state.MUSIC_ONLY.match(t) and ("♪" in t or "♫" in t or "♬" in t or "(" in t or "（" in t or "[" in t or "【" in t or "［" in t):
        return True
    n = _letters(t)
    for h in ed_state.HALLUC_LINE:
        k = _letters(h)
        if k and k in n and len(n) - len(k) <= ed_state.HALLUC_LINE_REST:
            return True
    return False


def repeats_in_line(text):
    """行の中で同じ語(2〜10 文字)が REP_MIN 回以上続くか(「ぱんぱんぱんぱんぱん…」。1 文字の繰り返し = 笑い・叫びは除く)"""
    m = ed_state.REP_RE.search(_letters(text))
    while m:
        if len(set(m.group(1))) > 1:
            return True
        m = ed_state.REP_RE.search(_letters(text), m.start() + 1)
    return False


def make_flags(seg, prev_texts, lang=None, terms=()):
    """Whisper は BGM・無音・歌で幻覚(でたらめな文)を出しやすいので、要確認の印を付ける。
    lang が "ja" のときは、英字が目立つ行も対象にする(terms = 認識のヒントに渡した語(prompt_terms)。その中の英字の語は数えない)。
    長い区間に文字が少ない行(抜けの可能性。sparse_row)にも付ける(2026-09-26 ③-1)。
    S-3(2026-09-29): よくある誤認識の文を増やした(stock_phrase)・行の中の繰り返し(repeats_in_line)・近くの行に同じ文が3回・
    短い区間でヒントの語だけが出た行(LEAK_FLAG。roster.leak_only)"""
    why = []
    lp, ns, cr = seg.get("avg_logprob"), seg.get("no_speech_prob"), seg.get("compression_ratio")
    if lp is not None and lp < -1.0:
        why.append("自信が低い")
    if ns is not None and ns > 0.6:
        why.append("音声でない可能性(BGMなど)")
    text = seg["text"]
    if (cr is not None and cr > 2.4) or repeats_in_line(text):
        why.append("繰り返しの可能性")
    dur = seg["end"] - seg["start"]
    if stock_phrase(text) and dur < 8:
        why.append("よくある誤認識の文")
    key = _letters(text)
    if text and (prev_texts[-2:] == [text, text] or (len(key) >= 4 and sum(1 for p in prev_texts[-5:] if _letters(p) == key) >= 2)):
        why.append("同じ文の繰り返し")   # 続けて3回、または近く(前の5行)に同じ文が2回あって3回目
    if terms and (("用語" in text and ":" in unicodedata.normalize("NFKC", text)) or (dur <= ed_state.LEAK_MAX_SEC and _roster.leak_only(text, terms))):
        why.append(ed_state.LEAK_FLAG)
    if lang == "ja" and latin_suspect(text, terms):
        why.append("英字が多い(英語の幻覚の可能性)")
    if sparse_row(seg.get("start"), seg.get("end"), text):
        why.append(SPARSE_FLAG)
    return "、".join(why)


ENGINE_DIR = None   # エンジンの実行ファイル・モデルの置き場所(既定 = 作業データ)


def engine_home():
    """精度を測る道具は serve の DATA_DIR を一時フォルダにするので、本物の作業データを環境変数 TRANSCRIBE_ENGINE_DIR で渡す(認識ワーカーにも届く)"""
    return ENGINE_DIR or os.environ.get("TRANSCRIBE_ENGINE_DIR") or ed_state.DATA_DIR


def engine_of(spec):
    return str(spec.get("engine") or tx_engines.DEFAULT)


def req_engine(req, model):
    """要求の認識エンジン(無ければ faster-whisper)。一覧に無い名前・そのエンジンで使えないモデルは断る。
    画面の「処理方式」の GPU(AMD など・whisper.cpp)は device = "vulkan" で来る → whisper.cpp(機器は auto = Vulkan。黙って CPU にしない)"""
    e = str(req.get("engine") or (tx_engines.WhisperCpp.id if req.get("device") == "vulkan" else tx_engines.DEFAULT))
    if not tx_engines.valid(e):
        raise ed_state.ApiError("bad_engine", "知らない認識エンジンです: %s" % e[:40], 400)
    if not tx_engines.get(e).valid_model(model):
        if e == tx_engines.WhisperCpp.id:
            raise ed_state.ApiError("bad_model", "GPU(whisper.cpp)で使えるモデルは %s だけです(今は %s)。モデルを変えてください" % ("・".join(tx_engines.WCPP_MODELS), model[:60]), 400)
        raise ed_state.ApiError("bad_model", "%s では使えないモデルです: %s" % (e, model[:60]), 400)
    return e


def engines_info():
    """画面に出すエンジンの準備(/api/tools)。whisper.cpp は作ってあるときだけ「処理方式」に出す"""
    ok, why = tx_engines.WhisperCpp.ready(engine_home())
    return {"wcpp": {"ready": bool(ok), "why": why, "models": list(tx_engines.WCPP_MODELS), "version": tx_engines.WHISPER_CPP["version"]}}


def check_engine(spec):
    """認識を始める前に、そのエンジンが使えるか(サーバー側。ネイティブの部品は読まない)"""
    e = engine_of(spec)
    if e == tx_engines.DEFAULT or ed_state.worker_fake():   # worker-fake(テスト)のワーカーは偽の whisper-cli を使う
        if not ed_state.has_faster_whisper():
            raise ed_state.ApiError("no_whisper", "faster-whisper が入っていません(README の準備手順を確認してください)", 400)
        return
    ok, why = tx_engines.get(e).ready(engine_home())
    if not ok:
        raise ed_state.ApiError("engine_missing", why, 400)


def load_model(name, job, pref="auto", force_cpu=False, engine=tx_engines.DEFAULT):
    """(モデル, 使用デバイス) を返す。サーバーのプロセスでは、モデルは認識ワーカー(別プロセス)の中に読み込み、
    ここではその代理(RemoteModel。transcribe() を呼ぶとワーカーで認識する)を返す。faster-whisper のネイティブコードが落ちても、
    落ちるのはワーカーだけになる(統合計画の段階3-3)。engine = 認識エンジン(tx_engines の名前。計画 段2-1)"""
    if IN_WORKER:
        return _load_model_local(name, job, pref, force_cpu, engine)
    args = {"name": name, "pref": pref, "force_cpu": bool(force_cpu)}
    if engine != tx_engines.DEFAULT:   # 既定のエンジンは今までと同じ要求(古いワーカーとも同じやり取り)
        args["engine"] = engine
    v = WORKER.call("load", args, job)
    return RemoteModel(WORKER, name, v["device"], v.get("params"), job, engine), v["device"]


def _load_model_local(name, job, pref="auto", force_cpu=False, engine=tx_engines.DEFAULT):
    """(モデル, 使用デバイス) を返す(認識ワーカーの中で動く本体)。同じエンジン・モデル・機器のものは使い回す。モデルは tx_engines のエンジン。
    pref: auto=GPU があれば GPU(失敗したら CPU) / cuda=GPU 固定(失敗したらエラー) / cpu=CPU 固定"""
    try:
        eng = tx_engines.get(engine)
    except ValueError as e:
        raise ed_state.ApiError("bad_engine", str(e), 400)
    env = os.environ.get("TRANSCRIBE_DEVICE")
    if force_cpu:
        pref = "cpu"
    elif env in ("cuda", "cpu"):
        pref = env
    # 試す機器の順はエンジンが決める(faster-whisper = CUDA → CPU、whisper.cpp = Vulkan だけ・CPU は明示のときだけ)。CUDA の有無を調べるのは faster-whisper のときだけ
    order = eng.device_order(pref, eng is tx_engines.FasterWhisper and pref == "auto" and ed_state.gpu_ready())
    hooks = {"cancelled": lambda: bool(job.get("cancel")),
             "download": lambda r: job.__setitem__("phase", "モデルを取得中 %d%%(初回だけ)" % int(r * 100))}
    with _model_lock:
        last = None
        for dev in order:
            key = (name, dev, eng.id)
            _model_used[0] = time.time()
            if key in _models:
                return _models[key], dev
            if _models:   # 別のモデルは手放す(large-v3 と turbo を交互に使ってもメモリが積み上がらない。落ちる原因の1つ)
                ed_state.log.info("モデルを解放: %s(メモリ %s)", ", ".join("/".join(k) for k in _models), ed_state._mem())
                _models.clear()
                gc.collect()
            job["phase"] = "モデルを読み込み中(初回はダウンロードのため数分かかります)"
            try:
                ed_state.log.info("モデルを読み込み: %s/%s/%s(メモリ %s)", eng.id, name, dev, ed_state._mem())
                m = eng.create(name, dev, cuda_compute() if dev == "cuda" else "int8", ed_state.log, engine_home(), hooks)
                ed_state.log.info("モデルを読み込み終わり: %s/%s(メモリ %s)", name, dev, ed_state._mem())
            except tx_engines.EngineError as e:   # エンジンが理由を書いた失敗(実行ファイルが無い・取得の失敗・GPU を使えない)はそのまま出す
                if e.code == "cancelled":
                    raise Cancelled()
                raise ed_state.ApiError(e.code, e.message, e.status)
            except MemoryError:
                raise ed_state.ApiError("no_memory", "メモリが足りずモデルを読み込めませんでした。他のアプリ(動画編集ソフトなど)を閉じてから、もう一度試してください", 500)
            except Exception as e:
                last = e
                if dev == "cuda" and pref == "auto":
                    continue  # 自動のときは、GPU が使えなければ CPU にする
                if dev == "cuda":
                    raise ed_state.ApiError("gpu_failed", "GPU で読み込めませんでした: %s(GPU 用ライブラリが未導入の可能性があります。install-gpu.bat を実行するか、処理方式を「自動」か「CPU」にしてください)" % str(e)[:160], 500)
                raise ed_state.ApiError("model_failed", "モデルを読み込めませんでした: %s(ネットワーク接続とモデル名を確認してください)" % str(e)[:200], 500)
            _models[key] = m
            return m, dev
        raise ed_state.ApiError("model_failed", "モデルを読み込めませんでした: %s" % str(last)[:200], 500)


CUDA_COMPUTE_TYPES = ("float16", "int8_float16", "int8", "float32")


def cuda_compute():
    """GPU で使う精度の型。環境変数 TRANSCRIBE_CUDA_COMPUTE(友人用簡易版の起動が int8_float16 = 8GB の GPU に収める)。無い・違えば float16(今まで)"""
    v = os.environ.get("TRANSCRIBE_CUDA_COMPUTE", "").strip()
    return v if v in CUDA_COMPUTE_TYPES else "float16"


def whisper_kwargs(spec):
    kw = dict(language=None if spec["language"] == "auto" else spec["language"], beam_size=spec["beam"], condition_on_previous_text=False)
    mode = spec.get("vadMode", "weak")
    if mode == "off":
        kw["vad_filter"] = False
    elif mode == "weak":   # 声が重なる・BGMがある配信で、話している部分を落としにくくする
        kw["vad_filter"] = True
        kw["vad_parameters"] = {"threshold": 0.3, "min_silence_duration_ms": 1000, "speech_pad_ms": 600}
        kw["no_speech_threshold"] = 0.9
    else:
        kw["vad_filter"] = True
        kw["vad_parameters"] = {"min_silence_duration_ms": 500}
    if spec.get("wordSplit"):
        kw["word_timestamps"] = True   # 単語の時刻。長い行を分け、行の始まり・終わりを声のある所にそろえる(対応していない版では filter_kwargs が外す)
    if "kotoba" in spec["model"].lower():
        kw["chunk_length"] = 15   # kotoba-whisper が推奨する設定
    if spec.get("temp0"):
        kw["temperature"] = 0.0   # 温度のやり直し(乱数を使う)をしない。精度を比べる道具(dev/eval_asr.py --temp0)だけが使う
    terms = prompt_terms(spec)
    if terms:
        kw["initial_prompt"] = "用語: " + "、".join(terms)
        kw["hotwords"] = ", ".join(_roster.fit(list(spec.get("glossary") or []) + list((spec.get("context") or {}).get("terms") or []), _roster.HOT_LIMIT, 2))
    return kw


def prompt_terms(spec):
    """認識のヒント(initial_prompt)に渡す語: 用語集(自動で足した語を含む)→ 配信ごとの文脈(出る人の名前と呼び名。段1-2)。
    先頭 150 字に収まるだけ(語の途中で切らない)。プロンプトの漏れ出しの印(S-3)も、この語で調べる"""
    return _roster.fit(list(spec.get("glossary") or []) + list((spec.get("context") or {}).get("terms") or []))


def stream_context(doc, enabled=True):
    """配信ごとの文脈(段1-2): その配信に出る人を、配信のチャンネル名・コラボ相手(スタジオの data.json を読むだけ)・話者の名前・題名から決め、
    その人の名前と呼び名だけをヒントの語にする。**題名の文字列そのものは渡さない**。
    doc: clip・title・sourceName・sourcePath・speakers を持つ辞書。-> {"members": [{"name", "from"}], "terms": [語]}"""
    if not enabled:
        return {"members": [], "terms": []}
    r = _roster.load(ed_state.ROSTER)
    clip = doc.get("clip") if isinstance(doc.get("clip"), dict) else {}
    src = clip.get("source") if isinstance(clip.get("source"), dict) else {}
    try:
        info = ed_store.studio_stream(src.get("videoId")) if src.get("videoId") else None
    except Exception as e:   # 他のツールのデータが読めなくても、文脈なしで続ける
        ed_state.log.info("スタジオの配信の情報を読めませんでした: %s", str(e)[:120])
        info = None
    path = str(doc.get("sourcePath") or "")
    titles = [src.get("title"), (info or {}).get("title"), doc.get("title"), doc.get("sourceName"),
              os.path.basename(os.path.dirname(path)) if path else ""]   # 動画の入ったフォルダ(スタジオは配信の題名のフォルダに書き出す)
    ctx = _roster.build_context(r, (info or {}).get("channel", ""), [c["channel"] for c in (info or {}).get("collab") or []],
                                [s.get("name") for s in doc.get("speakers") or [] if isinstance(s, dict)], [str(t or "")[:300] for t in titles])
    ctx["terms"] = _roster.member_terms([m["name"] for m in ctx["members"]], r)
    return ctx


def filter_kwargs(model, kw):
    """使っている faster-whisper が対応していない引数は渡さない(古い版でも動くように)。
    認識ワーカーの代理(RemoteModel)は、ワーカーが調べた引数の一覧(params)を持っている。"""
    params = getattr(model, "params", None)
    if callable(params):   # エンジン(tx_engines)をその場で使うとき(認識ワーカーの中・道具)。代理(RemoteModel)は一覧を持っている
        params = set(params())
    if params:
        return {k: v for k, v in kw.items() if k in params}
    try:
        import inspect
        accepted = set(inspect.signature(model.transcribe).parameters)
        return {k: v for k, v in kw.items() if k in accepted}
    except (TypeError, ValueError):
        return kw


# ---------- 声の検出(VAD)が捨てすぎたときのやり直し(docs/design/whole-retranscribe-design.md の 4-2) ----------
# 声が重なる所・BGM のある所を、Silero VAD が「声ではない」と判断して全部捨て、モデルに何も渡らないことがある(2026-09-28。40 秒が 0 文字)。
# 残った割合が VAD_MIN_KEEP 未満か、文字が 1 つも出なかったら、「弱め」→「なし」の順に緩めてやり直す
VAD_MIN_KEEP = 0.2
VAD_LADDER = {"normal": ("normal", "weak", "off"), "weak": ("weak", "off"), "off": ("off",)}
VAD_NAMES = {"normal": "標準", "weak": "弱め", "off": "なし"}


def seg_to_dict(s, shift=0.0):
    """認識の1行(faster-whisper の行・ワーカーの代理)→ 辞書(秒は shift を足す)"""
    ws = [w for w in (getattr(s, "words", None) or []) if getattr(w, "start", None) is not None and getattr(w, "end", None) is not None]
    words = [(float(w.start) + shift, float(w.end) + shift, str(w.word)) for w in ws]
    probs = [_prob(getattr(w, "probability", None)) for w in ws]   # words と同じ並びの確信度(3つ組は変えない。生出力 <id>.asr.json 用)
    return {"start": float(s.start) + shift, "end": float(s.end) + shift, "text": (s.text or "").strip(), "avg_logprob": getattr(s, "avg_logprob", None),
            "no_speech_prob": getattr(s, "no_speech_prob", None), "compression_ratio": getattr(s, "compression_ratio", None), "words": words,
            "wordProbs": probs}


def _prob(v):
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return round(f, 4) if f == f else None


def vad_kept(info, mode):
    """(声の検出のあとに残った割合, 捨てた秒)。声の検出をかけていない・分からないときは (None, 0.0)"""
    d, k = getattr(info, "duration", None), getattr(info, "duration_after_vad", None)
    if mode == "off" or not isinstance(d, (int, float)) or not isinstance(k, (int, float)) or d <= 0:
        return None, 0.0
    return max(0.0, min(1.0, k / d)), round(max(0.0, d - k), 2)


def vad_note(vad):
    """やり直したときに画面に出す文(やり直していなければ '')"""
    if not vad or not vad.get("retries"):
        return ""
    steps = "→".join([VAD_NAMES.get(r["mode"], r["mode"]) for r in vad["retries"]] + [VAD_NAMES.get(vad["used"], vad["used"])])
    return "声の検出で大部分が「声ではない」と判断されたので、検出を緩めて認識しました(声の検出: %s)" % steps


def transcribe_vad_fallback(job, model, audio, spec, on_seg=None):
    """声の検出を spec["vadMode"] から始め、捨てすぎ・文字が 0 なら緩めてやり直す。-> (行の辞書の一覧, 声の検出の記録)。
    記録 = {"requested", "used", "removedSec"(使った設定で捨てた秒), "retries": [{"mode", "kept", "removedSec", "why": "kept"|"empty"}]}。
    よくある誤認識の文(HALLUC)しか出なかったときも「文字が 0」とみなす(2026-09-28 白上フブキ03: 標準で 22 秒捨て、残りから「ご視聴ありがとうございました」だけ)"""
    mode0 = spec.get("vadMode", "weak")
    ladder = VAD_LADDER.get(mode0, (mode0,))
    retries = []
    for i, mode in enumerate(ladder):
        last = i == len(ladder) - 1
        kw = filter_kwargs(model, whisper_kwargs(dict(spec, vadMode=mode)))
        segs, info = model.transcribe(audio, **kw)
        kept, removed = vad_kept(info, mode)
        if kept is not None and kept < VAD_MIN_KEEP and not last:
            close = getattr(segs, "close", None)
            if close:
                close()   # 行は読まない(ほとんど捨てた結果なので)
            retries.append({"mode": mode, "kept": round(kept, 3), "removedSec": removed, "why": "kept"})
            ed_state.log.info("声の検出が %.0f%% を捨てたので、緩めてやり直します(%s)", (1 - kept) * 100, mode)
            continue
        raw = []
        for s in segs:
            if job["cancel"]:
                raise Cancelled()
            raw.append(seg_to_dict(s))
            if on_seg:
                on_seg(raw[-1], len(raw))   # この回(やり直しごと)の行の数
        terms = prompt_terms(spec)
        if not any(r["text"] and not stock_phrase(r["text"]) and not _roster.leak_only(r["text"], terms) for r in raw) and not last:
            # 「ご視聴ありがとうございました」だけ・ヒントの語だけ = 文字が 0 と同じ
            retries.append({"mode": mode, "kept": None if kept is None else round(kept, 3), "removedSec": removed, "why": "empty"})
            ed_state.log.info("文字が出なかったので、声の検出を緩めてやり直します(%s)", mode)
            continue
        return raw, {"requested": mode0, "used": mode, "removedSec": removed, "retries": retries}
    return [], {"requested": mode0, "used": ladder[-1], "removedSec": 0.0, "retries": retries}


def transcribe_real(job, spec, wav, total):
    model, device = load_model(spec["model"], job, spec.get("device", "auto"), engine=engine_of(spec))
    job["device"] = device
    if job["cancel"]:
        raise Cancelled()
    job["phase"], job["state"] = "文字起こし中", "running"

    def progress(r, n):
        job["progress"] = min(0.99, r["end"] / total) if total else 0.0
        job["segments"] = n   # 処理状況の「n 行」(行は最後まで読んでから流すので、ここで数える)

    # やり直しに備えて、行は最後まで読んでから流す(やり直す前の行を文書に入れないため)
    try:
        raw, vad = transcribe_vad_fallback(job, model, wav, spec, progress)
    except (Cancelled, ed_state.ApiError):
        raise
    except Exception:
        if device == "cuda" and spec.get("device") == "cuda":
            raise ed_state.ApiError("gpu_failed", "GPU での処理に失敗しました。GPU 用ライブラリが未導入の可能性があります(install-gpu.bat を実行するか、処理方式を「自動」か「CPU」にしてください)", 500)
        if device != "cuda":
            raise
        # 自動のとき、GPU で実行時に失敗(CUDA ライブラリ不足など)したら CPU でやり直す
        job["phase"], job["device"] = "GPU が使えないため CPU で処理します", "cpu"
        model, _ = load_model(spec["model"], job, force_cpu=True)
        raw, vad = transcribe_vad_fallback(job, model, wav, spec, progress)
    job["vad"] = vad
    for x in raw:
        yield x


SPLIT_GAP, SPLIT_SEC, SPLIT_CHARS = 1.0, 8.0, 40   # 単語の間がこの秒数以上あいたら行を分ける / 1行の最大の長さ(秒・文字。文字は設定の「1つの字幕の最大文字数」が優先)
SPLIT_SLACK = 2          # 最大文字数を 2 文字まで超えるのは許す(無理に分けて変な所で切らない。docs/design/edit-tool-design.md の 12 ②)
# 字幕の文字数(12 ②。ユーザー決定 2026-09-26: 縦 16・横 28、パックの字幕は2段 = 縦 8・横 14 文字前後で改行)。設定の "subtitle" に保存する
SUBTITLE_DEFAULT = {"orientation": "vertical", "maxChars": {"vertical": 16, "horizontal": 28}, "wrapChars": {"vertical": 8, "horizontal": 14}}
ORIENTATIONS = ("vertical", "horizontal")


def subtitle_settings(st=None):
    """設定の subtitle(字幕の向き・1つの字幕の最大文字数・パックの字幕の改行の文字数)を、範囲を確かめて返す(無い・おかしい値は既定)"""
    v = (st if st is not None else ed_learn.load_settings()).get("subtitle")
    v = v if isinstance(v, dict) else {}
    out = {"orientation": v.get("orientation") if v.get("orientation") in ORIENTATIONS else SUBTITLE_DEFAULT["orientation"]}
    for key, lo, hi in (("maxChars", 4, 80), ("wrapChars", 2, 40)):
        src = v.get(key) if isinstance(v.get(key), dict) else {}
        out[key] = {}
        for o in ORIENTATIONS:
            n = src.get(o)
            out[key][o] = int(n) if isinstance(n, (int, float)) and not isinstance(n, bool) and lo <= n <= hi else SUBTITLE_DEFAULT[key][o]
    return out


def split_chars_for(req=None, st=None):
    """行を分けるときの最大文字数(要求の splitChars → 要求の subtitleOrientation → 設定の字幕の向き)。
    画面は今の欄の値を splitChars で渡す(設定の保存は少し遅れて送られるため)。まとめて実行は設定を使う"""
    req = req or {}
    n = req.get("splitChars")
    if isinstance(n, (int, float)) and not isinstance(n, bool) and 4 <= n <= 80:
        return int(n)
    sub = subtitle_settings(st)
    o = req.get("subtitleOrientation")
    return sub["maxChars"][o if o in ORIENTATIONS else sub["orientation"]]
STRIP_PUNCT_CHARS = "、。？！?!"   # ショート動画のテロップでは句読点が浮きやすいので、既定で取り除く対象(全角の読点・句点・疑問符・感嘆符と、その半角形)
_strip_punct_re = re.compile("[%s]" % re.escape(STRIP_PUNCT_CHARS))


def strip_punct(text):
    """テロップ表示用に、句読点(、。？！ と半角の ?!)を取り除く。"""
    return _strip_punct_re.sub("", text)


def _cut_words(ws, max_chars=SPLIT_CHARS):
    """単語の並び ws=[(開始,終了,文字)] を、長すぎる間は「間が大きい・句読点のあと・真ん中に近い」所で分けていく。
    文字数は max_chars + SPLIT_SLACK まで許す。同じ種類の文字(カタカナ・漢字・英数字)の並びの途中では、なるべく切らない(12 ②)"""
    dur = ws[-1][1] - ws[0][0]
    chars = sum(len(t.strip()) for _a, _b, t in ws)
    if len(ws) < 2 or (dur <= SPLIT_SEC and chars <= max_chars + SPLIT_SLACK):
        return [ws]
    best, bi = None, 1
    for i in range(1, len(ws)):
        gap = max(0.0, ws[i][0] - ws[i - 1][1])
        prev_t, next_t = ws[i - 1][2].rstrip(), ws[i][2].lstrip()
        tail = prev_t[-1:]
        punct = 1.0 if tail in "。！？!?" else (0.4 if tail in "、,，" else 0.0)
        balance = 1.0 - abs((ws[i - 1][1] - ws[0][0]) / dur - 0.5) if dur > 0 else 0.5
        same = 1.0 if prev_t and next_t and ed_learn._cc(prev_t[-1]) and ed_learn._cc(prev_t[-1]) == ed_learn._cc(next_t[0]) else 0.0   # 語の途中
        score = gap * 2 + punct + balance * 0.5 - same
        if best is None or score > best:
            best, bi = score, i
    return _cut_words(ws[:bi], max_chars) + _cut_words(ws[bi:], max_chars)


def split_segment(s, max_chars=SPLIT_CHARS):
    """認識した1行 s を、単語の時刻で整える。①行の始まり・終わりを最初・最後の単語にそろえる(声のない所まで伸びた行を直す)
    ②単語の間が1秒以上あいた所で分ける ③長すぎる行(8秒・max_chars 文字 + 2 超)は区切りのよい所で分ける。
    単語の並びが行の文章と合わないとき、単語の時刻が無いときは、何もせずそのまま返す。
    分けた行には、その行の単語を "_words" に付ける(文書の words.json に保存する用。行のデータには入れない)"""
    words = s.get("words") or []
    if not words:
        return [s]
    ws = [(a, b, t) for a, b, t in words if b >= a]
    squash = lambda x: re.sub(r"\s+", "", x)
    if not ws or squash("".join(t for _a, _b, t in ws)) != squash(s.get("text", "")):
        return [s]
    groups, cur = [], [ws[0]]
    for w in ws[1:]:
        if w[0] - cur[-1][1] >= SPLIT_GAP:
            groups.append(cur)
            cur = []
        cur.append(w)
    groups.append(cur)
    parts = [p for g in groups for p in _cut_words(g, max_chars)]
    out = []
    for p in parts:
        text = "".join(t for _a, _b, t in p).strip()
        if text:
            out.append({**{k: v for k, v in s.items() if k != "words"}, "start": p[0][0], "end": max(p[-1][1], p[0][0]), "text": text, "_words": p})
    return out or [s]


def expand_segments(gen, spec):
    """認識の出力を、split_segment で整えながら流す(wordSplit が無効なら、そのまま)。
    句読点の除去(stripPunct、既定オン)は、単語分割が句読点を判断材料に使い終えたあとの、最後の1回だけにかける
    (分割の精度には影響させず、かつ text と original の両方に必ず同じ結果が入るよう、ここ1か所にまとめる)。"""
    strip = spec.get("stripPunct", True)
    mc = spec.get("splitChars") or SPLIT_CHARS
    for s in gen:
        for p in (split_segment(s, mc) if spec.get("wordSplit") else [s]):
            yield {**p, "text": strip_punct(p["text"])} if strip and p.get("text") else p


CONF_KEYS = ("avg_logprob", "no_speech_prob", "compression_ratio")   # 機械の出力 original の各行に残す、認識の自信の度合い(文字起こしの改善の計画 段0-1)


def machine_conf(s):
    """認識の1行の自信の度合い {avg_logprob, no_speech_prob, compression_ratio}(分かるものだけ。小数4桁)。
    original に残して、どの値のときに誤りが多いか(怪しい所だけ別の方法で聞き直す判断の材料)を測れるようにする"""
    out = {}
    for k in CONF_KEYS:
        v = s.get(k)
        if isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v):
            out[k] = round(float(v), 4)
    return out


_pkg_versions = {}


def pkg_version(name):
    """入っているパッケージの版(読み込まずに dist-info から読む = サーバー側で faster_whisper などのネイティブの部品を import しない)。無ければ ''"""
    if name not in _pkg_versions:
        try:
            import importlib.metadata as _md
            _pkg_versions[name] = str(_md.version(name))
        except Exception:
            _pkg_versions[name] = ""
    return _pkg_versions[name]


def recognition_run(spec, job, audio_sec, wall_sec):
    """文書の recognition.runs に残す、この認識の出どころ(エンジン・版・モデル・機器・かかった時間)。精度と速さを後から比べるため(計画 段0-1)"""
    fake = ed_state.backend_name() == "fake"
    eng = tx_engines.get(spec.get("engine"))
    return {"engine": "fake" if fake else eng.id, "engineVersion": "" if fake else (pkg_version(eng.package) if eng.package else eng.version(engine_home())),
            "model": spec["model"], "device": job.get("device", ""), "language": spec["language"],
            "settings": {"beam": spec["beam"], "vadMode": spec["vadMode"], "boost": bool(spec.get("boost")), "wordSplit": bool(spec.get("wordSplit")),
                         "glossaryChars": len("、".join(spec.get("glossary") or [])), "promptChars": len("、".join(prompt_terms(spec))),
                         "context": [m["name"] for m in (spec.get("context") or {}).get("members") or []], "dict": dict_version(spec)},
            "audioSec": round(float(audio_sec or 0), 2), "wallSec": round(float(wall_sec), 2), "at": int(time.time() * 1000),
            **vad_record(job.get("vad"))}


def short_hash(text):
    """辞書などの中身の版(SHA-256 の先頭 10 文字)。中身そのものは残さず、同じ版かどうかだけ分かるようにする"""
    return hashlib.sha256(str(text).encode("utf-8")).hexdigest()[:10]


_roster_hash = {"key": None, "val": ""}


def roster_hash():
    """名簿のファイル(配信ごとの文脈・用語の自動追加の材料)の版。ファイルの更新日時と大きさが同じなら前の結果。読めなければ ''"""
    try:
        st = os.stat(ed_state.ROSTER)
        key = (ed_state.ROSTER, st.st_mtime_ns, st.st_size)
        if _roster_hash["key"] != key:
            with open(ed_state.ROSTER, "rb") as f:
                _roster_hash.update({"key": key, "val": hashlib.sha256(f.read()).hexdigest()[:10]})
        return _roster_hash["val"]
    except OSError:
        return ""


def dict_version(spec):
    """この認識に使った辞書の版(マスタープラン Q2。recognition.runs の settings.dict と文書の params.dict)。
    glossary = 用語集(自動で足した語を含む。ヒントに入った語)・replacements = 置換辞書(autoDict のとき)・
    learned = 学習済みの置換と採用・却下の記録(autoLearned のとき)・roster = 名簿のファイル。
    辞書を変えた前後で成績を分ける・同じ版どうしで比べるために、中身ではなく短いハッシュだけを残す。使っていない・読めないものは入れない"""
    out = {}
    try:
        gl = [str(t) for t in spec.get("glossary") or []]
        if gl:
            out["glossary"] = short_hash("\n".join(gl))
        if spec.get("autoDict"):
            out["replacements"] = short_hash("\n".join("%s=>%s" % p for p in ed_learn.parse_replacements(ed_learn.load_settings().get("replacements"))))
        if spec.get("autoLearned"):
            rules = ed_learn.learn_rules()
            out["learned"] = short_hash(json.dumps({"rules": sorted([w, r, x["pos"], len(x["docs"])] for (w, r), x in rules.items()), "fb": {k: v for k, v in ed_learn.load_feedback().items() if k != "alt"}},
                                                   ensure_ascii=False, sort_keys=True))
    except (OSError, ValueError, TypeError, KeyError) as e:   # 記録のための値なので、作れなくても認識は止めない
        ed_state.log.warning("辞書の版を作れませんでした: %s", e)
    rh = roster_hash()
    if rh:
        out["roster"] = rh
    return out


# ---------- 再認識で差し替えた機械の出力の記録(マスタープラン Q2。original を差し替える前の分を recognition.runs に残す) ----------
MAX_RERUNS = 30             # recognition.runs に残す再認識の記録の件数(古いものから捨てる。最初の認識の記録 = kind の無いものは捨てない)
MAX_REPLACED_ROWS = 20000   # 再認識の記録の replaced の行の合計の上限(超えたら古い記録から捨てる。文書が大きくなりすぎないように)


def replaced_rows(orig, spans, keep=()):
    """original のうち、spans のどれかに真ん中が入り、keep に入らない行(= これから差し替えられる機械の出力)。
    replace_original・replace_original_multi と同じ決まり(真ん中で決める)"""
    out = []
    for o in orig or []:
        if not isinstance(o, dict):
            continue
        try:
            m = (float(o["start"]) + float(o["end"])) / 2
        except (KeyError, TypeError, ValueError):
            continue
        if any(a <= m <= b for a, b in spans) and not _in_spans(m, keep):
            out.append(dict(o))
    return out


def record_rerun(doc, spec, kind, spans, replaced):
    """再認識で original を差し替える前に、差し替えられる機械の出力を recognition.runs に1件足す(文書を書くのは呼び出し側。_save_lock の中)。
    1件 = {"kind": "each" | "range" | "whole" | "redo", 新しい結果を出したエンジン・版・モデル・言語・設定(settings.dict = 辞書の版),
           "range": [最初, 最後], "spans"?: 行ごとの範囲(each・redo で2つ以上のとき), "replaced": [差し替えられた original の行], "at"}。
    original の無い文書(文字起こしせずに開いた)でも、いつ・何で認識し直したかは残す(replaced は空)"""
    spans = [[round(float(a), 3), round(float(b), 3)] for a, b in spans]
    if not spans:
        return
    # 機械が行を書き換えるので、「動画を全部聞いて確かめた」印(評価ドリル。ed_drill)も外す。行の proofed を外すのと同じ時に。
    # 再認識(each・range・whole)と疑わしい所の認識し直し(redo)は、どれも差し替える前にここを通る
    doc.pop("evalReviewed", None)
    fake = ed_state.backend_name() == "fake"
    try:
        eng = tx_engines.get(engine_of(spec))
        eid, ever = ("fake", "") if fake else (eng.id, pkg_version(eng.package) if eng.package else eng.version(engine_home()))
    except Exception:   # 記録のための値なので、エンジンの版が分からなくても差し替えは止めない
        eid, ever = ("fake" if fake else engine_of(spec)), ""
    rep = replaced[:MAX_REPLACED_ROWS]
    run = {"kind": kind, "engine": eid, "engineVersion": ever, "model": str(spec.get("model") or ""), "device": str(spec.get("device") or ""),
           "language": str(spec.get("language") or ""),
           "settings": {"beam": spec.get("beam"), "vadMode": spec.get("vadMode"), "boost": bool(spec.get("boost")), "wordSplit": bool(spec.get("wordSplit")),
                        "autoDict": bool(spec.get("autoDict")), "dict": dict_version(spec)},
           "range": [min(a for a, _ in spans), max(b for _, b in spans)], "replaced": rep, "at": int(time.time() * 1000)}
    if len(spans) > 1:
        run["spans"] = spans[:MAX_REPLACED_ROWS]
    if len(replaced) > len(rep):
        run["replacedOmitted"] = len(replaced) - len(rep)
    rec = doc.get("recognition") if isinstance(doc.get("recognition"), dict) else {}
    runs = [r for r in rec.get("runs") or [] if isinstance(r, dict)] + [run]
    reruns = [r for r in runs if r.get("kind")]
    total = sum(len(r.get("replaced") or []) for r in reruns)
    drop = set()
    for r in reruns[:-1]:   # 古い記録から捨てる(今回の分は残す)
        if len(reruns) - len(drop) <= MAX_RERUNS and total <= MAX_REPLACED_ROWS:
            break
        drop.add(id(r))
        total -= len(r.get("replaced") or [])
    doc["recognition"] = dict(rec, runs=[r for r in runs if id(r) not in drop])


def context_record(spec):
    """文書の params に残す配信ごとの文脈(出る人と材料・ヒントに入った語の数)。使っていなければ None"""
    ctx = spec.get("context") or {}
    if not ctx.get("members"):
        return None
    return {"members": [{"name": m["name"], "from": list(m.get("from") or [])} for m in ctx["members"]][:10], "terms": len(ctx.get("terms") or [])}


def vad_record(vad):
    """recognition.runs に残す声の検出の記録(使った設定・捨てた秒・やり直し)。分からなければ {}"""
    if not vad:
        return {}
    return {"vadUsed": vad.get("used"), "vadRemovedSec": vad.get("removedSec", 0.0), "vadRetries": list(vad.get("retries") or [])}


def row_words(p, shift=0.0):
    """expand_segments が出した行の単語(split_segment の "_words" か、分けなかった行の "words")→ [[開始, 終了, 文字]](絶対の秒)"""
    return [[round(a + shift, 3), round(b + shift, 3), t] for a, b, t in (p.get("_words") or p.get("words") or [])]


# ---------- 生出力(transcripts/<id>.asr.json。分ける前・置換の前の認識の結果。単語ごとの時刻と確信度。友人用簡易版の評価データの asr_raw.json の元) ----------
ASR_SCHEMA = "youtube-tools-asr-raw/v1"
MAX_ASR_BYTES = 64 * 1024 * 1024


def asr_path(tid):
    return os.path.join(ed_state.TX_DIR, tid + ".asr.json")


def capture_raw(gen, raw, shift=0.0):
    """認識の行の流れ gen をそのまま流しながら、生出力を raw に足す(文字・時刻・自信の度合い・単語 [[開始, 終了, 文字, 確信度]])"""
    for s in gen:
        try:
            ws, ps = s.get("words") or [], s.get("wordProbs") or []
            raw.append({"start": round(float(s["start"]) + shift, 3), "end": round(float(s["end"]) + shift, 3), "text": str(s.get("text") or ""),
                        **machine_conf(s), "words": [[round(a + shift, 3), round(b + shift, 3), t, ps[i] if i < len(ps) else None]
                                                     for i, (a, b, t) in enumerate(ws)]})
        except (KeyError, TypeError, ValueError):
            pass   # 生出力が残せなくても文字起こしは止めない
        yield s


def write_asr(tid, segments, run):
    """生出力を保存する(run = recognition.runs の1件 = モデル・設定・版)。書けなくても文字起こしは失敗にしない(呼び出し側)"""
    body = {"schema": ASR_SCHEMA, "run": run, "segments": segments, "updatedAt": int(time.time() * 1000)}
    ed_state.atomic_write(asr_path(tid), json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))


def read_asr(tid):
    """生出力 {"schema", "run", "segments"}。無い・壊れていれば None"""
    try:
        d = _fsio.read_json_file(asr_path(tid), MAX_ASR_BYTES)
    except (OSError, UnicodeError, ValueError):
        return None
    if not isinstance(d, dict) or d.get("schema") != ASR_SCHEMA or not isinstance(d.get("segments"), list):
        return None
    return d


# ---------- 単語の時刻(12 ②。transcripts/<id>.words.json。行のデータには入れない = 画面の保存で落ちたり古くなったりしないように) ----------
WORDS_SCHEMA = "youtube-tools-words/v1"
MAX_WORDS_BYTES = 32 * 1024 * 1024


def words_path(tid):
    return os.path.join(ed_state.TX_DIR, tid + ".words.json")


def read_words(tid):
    """文書の単語の時刻 [[開始, 終了, 文字], ...](時刻の順)。無い・壊れていれば None"""
    try:
        d = _fsio.read_json_file(words_path(tid), MAX_WORDS_BYTES)
    except (OSError, UnicodeError, ValueError):
        return None
    if not isinstance(d, dict) or d.get("schema") != WORDS_SCHEMA or not isinstance(d.get("words"), list):
        return None
    out = []
    for w in d["words"]:
        if isinstance(w, list) and len(w) == 3 and all(isinstance(x, (int, float)) and not isinstance(x, bool) for x in w[:2]) and isinstance(w[2], str):
            out.append([float(w[0]), float(w[1]), w[2]])
    return sorted(out, key=lambda w: (w[0], w[1]))


def write_words(tid, words, model=""):
    """単語の時刻を保存する(空なら消す)。書けなくても文字起こしは失敗にしない(呼び出し側で記録だけ)"""
    if not words:
        try:
            os.unlink(words_path(tid))
        except FileNotFoundError:
            pass
        return
    body = {"schema": WORDS_SCHEMA, "model": str(model or ""), "updatedAt": int(time.time() * 1000),
            "words": sorted(words, key=lambda w: (w[0], w[1]))}
    ed_state.atomic_write(words_path(tid), json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))


def replace_words(tid, a, b, new_words, model="", keep_spans=()):
    """範囲 [a, b] の単語を、認識し直した単語に差し替える(真ん中が範囲に入る単語を消す。keep_spans の区間の単語は残す)。
    以前の単語が無い文書は、新しい単語だけにしない(範囲の外の単語が無いまま一部だけあると、分け直すときに紛らわしいため、範囲の単語だけで作る)"""
    old = read_words(tid) or []
    keep = [w for w in old if not (a - 1e-6 <= (w[0] + w[1]) / 2 <= b + 1e-6) or _in_spans((w[0] + w[1]) / 2, keep_spans)]
    write_words(tid, keep + [list(w) for w in new_words], model)


def _squash(text):
    return re.sub(r"\s+", "", str(text or ""))


def resplit_doc(obj):
    """POST /api/resplit {"id", "orientation"?, "baseUpdatedAt"?}: 今の文書の長い行を、保存してある単語の時刻で分け直す(12 ②)。
    分けるのは: 校正済みでない・文字が単語と一致する(人が直していない)・最大文字数 + 2 を超える行だけ。分けた行は話者・印・タグ・メモを引き継ぐ。
    分ける前の文書は履歴に残す(「以前の版に戻す」で戻せる)。-> {"changed": 分けた行の数, "added": 増えた行, "skipped": 単語と一致しない長い行, "rows", "updatedAt"}"""
    tid = str(obj.get("id") or "")
    o = obj.get("orientation")
    max_chars = split_chars_for({"subtitleOrientation": o, "splitChars": obj.get("splitChars")})
    with ed_store._save_lock:
        doc = ed_store.read_transcript(tid)
        base = obj.get("baseUpdatedAt")
        if isinstance(base, int) and not isinstance(base, bool) and base != int(doc.get("updatedAt") or 0):
            raise ed_state.ApiError("conflict", "別の画面で先に保存されています。読み直してから、もう一度押してください", 409)
        words = read_words(tid)
        if not words:
            raise ed_state.ApiError("no_words", "この文字起こしには単語の時刻がありません(v0.17.0 より前の文字起こし・単語の時刻を使わない設定)。"
                                       "行を選んで「範囲を再認識」すると、その範囲の単語の時刻を取り直せます", 400)
        mids = [(w[0] + w[1]) / 2 for w in words]
        segs = [g for g in doc.get("segments") or [] if isinstance(g, dict)]
        used = {str(g.get("id")) for g in segs}
        out, changed, added, skipped = [], 0, 0, 0
        for g in segs:
            text = str(g.get("text") or "")
            if g.get("proofed") is True or len(_squash(text)) <= max_chars + SPLIT_SLACK:
                out.append(g)
                continue
            a, b = float(g.get("start") or 0), float(g.get("end") or 0)
            lo, hi = bisect.bisect_left(mids, a - 0.05), bisect.bisect_right(mids, b + 0.05)
            ws = [tuple(w) for w in words[lo:hi]]
            joined = "".join(t for _a, _b, t in ws)
            if ws and _squash(joined) == _squash(text):
                strip = False
            elif ws and _squash(strip_punct(joined)) == _squash(text):
                strip = True        # 句読点を取り除いた行(stripPunct)
            else:
                skipped += 1        # 人が直した行・辞書で置き換えた行・単語の無い行は分けない
                out.append(g)
                continue
            parts = split_segment({"start": a, "end": b, "text": joined, "words": ws}, max_chars)
            if len(parts) < 2:
                out.append(g)
                continue
            changed += 1
            added += len(parts) - 1
            for k, p in enumerate(parts):
                t = strip_punct(p["text"]) if strip else p["text"]
                sid = base = str(g.get("id"))
                if k:   # 2つめからは <元の id>-2, -3 …(ほかの行と重ならない番号)
                    n = k + 1
                    sid = "%s-%d" % (base, n)
                    while sid in used:
                        n += 1
                        sid = "%s-%d" % (base, n)
                    used.add(sid)
                out.append(dict(g, id=sid, start=round(p["start"], 2), end=round(p["end"], 2), text=t[:ed_state.MAX_TEXT]))
        if not changed:
            return {"changed": 0, "added": 0, "skipped": skipped, "rows": len(segs), "updatedAt": int(doc.get("updatedAt") or 0)}
        try:
            ed_store.hist_snapshot(tid, force=True)   # 分ける前を「以前の版に戻す」に残す
        except OSError:
            pass
        doc["segments"] = sorted(out, key=lambda g: (g["start"], g["end"]))
        doc["updatedAt"] = int(time.time() * 1000)
        doc["resplit"] = {"maxChars": max_chars, "rows": changed, "at": doc["updatedAt"]}
        ed_store.apply_edit_cuts(tid, doc)
        ed_state.atomic_write(ed_store.tx_path(tid), json.dumps(doc, ensure_ascii=False, indent=1).encode("utf-8"))
        return {"changed": changed, "added": added, "skipped": skipped, "rows": len(doc["segments"]), "updatedAt": doc["updatedAt"]}


def transcribe_fake(job, spec, wav, total):
    """テスト用(環境変数 TRANSCRIBE_BACKEND=fake)。実際の音声認識は行わない。"""
    job["phase"], job["state"], job["device"] = "文字起こし中", "running", "cpu"
    t, i = 0.0, 0
    while t < total:
        if job["cancel"]:
            raise Cancelled()
        e = min(total, t + 4.0)
        i += 1
        yield {"start": t, "end": e, "text": "テスト文%d" % i, "avg_logprob": -1.4 if i % 5 == 0 else -0.3,
               "no_speech_prob": 0.1, "compression_ratio": 1.2}
        job["progress"] = min(0.99, e / total)
        time.sleep(float(os.environ.get("TRANSCRIBE_FAKE_DELAY", "0.05")))
        t = e


def run_job(job):
    if job.get("kind") == "diarize":
        return ed_speakers.run_diarize(job)
    if job.get("kind") == "voice-learn":
        return ed_speakers.run_voice_learn(job)
    if job.get("kind") == "retranscribe":
        return run_retranscribe(job)
    if job.get("kind") == "redo":
        return run_redo(job)
    if job.get("kind") == "abtest":
        return ed_misc.run_abtest(job)
    if job.get("kind") == "normalize":   # 動画を選び直したあとの 30fps の作り直し(Q1。ed_relink)
        return ed_relink.run_normalize(job)
    if job.get("kind") == "alt":   # 2つ目のエンジンで聞いて <id>.alt.json に(文書は書き換えない。D1-b。ed_alt)
        return ed_alt.run_alt(job)
    spec = job["spec"]
    wav = os.path.join(ed_state.TMP_DIR, job["id"] + ".wav")
    try:
        os.makedirs(ed_state.TMP_DIR, exist_ok=True)
        job["state"], job["phase"] = "extracting", "音声を取り出し中"
        extract_audio(job, spec, wav)
        total = ed_state.media_duration(wav) or (spec["end"] - spec["start"] if spec["end"] else 0)
        t_rec = time.monotonic()   # 認識にかかった時間(モデルの読み込みを含む)。recognition.runs に残す
        if ed_state.backend_name() == "fake":
            gen = transcribe_fake(job, spec, wav, total)
        else:
            check_engine(spec)
            job["state"] = "loading"
            gen = transcribe_real(job, spec, wav, total)
        raw_asr = []   # 生出力(<id>.asr.json)
        gen = capture_raw(gen, raw_asr, spec["start"])
        segs, prev, original, pairs, dict_n, all_words = [], [], [], (ed_learn.parse_replacements(ed_learn.load_settings().get("replacements")) if spec.get("autoDict") else []), 0, []
        sparse_lp = {}   # 「長い区間に文字が少ない」行の avg_logprob(認識し直したときに、良くなったかを比べる。③-2)
        learn_n = 0
        lrules, lfb = (ed_learn.learn_rules(), ed_learn.load_feedback()) if spec.get("autoLearned") else ({}, None)
        for s in expand_segments(gen, spec):
            if not s["text"]:
                continue
            seg = {"id": "s%d" % (len(segs) + 1), "start": round(s["start"] + spec["start"], 2), "end": round(s["end"] + spec["start"], 2),
                   "text": s["text"][:ed_state.MAX_TEXT], "speaker": "", "flag": ""}
            seg["flag"] = make_flags({**s, "text": seg["text"], "start": seg["start"], "end": seg["end"]}, prev, spec["language"], prompt_terms(spec))
            prev.append(seg["text"])
            if SPARSE_FLAG in seg["flag"] and s.get("avg_logprob") is not None:
                sparse_lp[seg["id"]] = float(s["avg_logprob"])
            if lrules:   # 確度が高い学習済みの置換は、機械の出力側にも反映する(そうしないと自分の置換を「人が直した」と数えて自己強化してしまう)
                seg["text"], ln = ed_learn.auto_learned_replace(seg["text"], lrules, lfb)
                learn_n += ln
            original.append({"start": seg["start"], "end": seg["end"], "text": seg["text"], **machine_conf(s)})   # 機械の出力をそのまま残す(修正からの学習・精度の測定に使う)
            all_words.extend(row_words(s, spec["start"]))
            seg["text"], n = ed_learn.apply_replacements(seg["text"], pairs)
            dict_n += n
            segs.append(seg)
            job["segments"] = len(segs)
        if job["cancel"]:
            raise Cancelled()
        now = int(time.time() * 1000)
        fields = {"start": spec["start"], "end": spec["end"], "whole": spec["whole"], "duration": spec["duration"], "model": spec["model"],
                  "language": spec["language"], "params": {"beam": spec["beam"], "vadMode": spec["vadMode"], "boost": spec["boost"], "device": job.get("device", ""), "glossary": spec["glossary"][:50],
                                                           "autoDict": bool(spec.get("autoDict")), "dictApplied": dict_n, "wordSplit": bool(spec.get("wordSplit")),
                                                           "splitChars": spec.get("splitChars"), "stripPunct": spec.get("stripPunct", True) is not False,
                                                           "autoLearned": bool(spec.get("autoLearned")), "learnApplied": learn_n, "glossAuto": spec.get("glossAuto", [])[:20],
                                                           "context": context_record(spec)},
                  "speakers": [], "segments": segs, "original": original, "updatedAt": now,
                  "recognition": {"runs": [recognition_run(spec, job, total, time.monotonic() - t_rec)]}}
        fields["params"]["dict"] = fields["recognition"]["runs"][0]["settings"]["dict"]   # その時の辞書の版(マスタープラン Q2)
        if job.get("vad"):
            fields["params"]["vadUsed"] = job["vad"].get("used")
            note = vad_note(job["vad"])
            if note:
                spec.setdefault("warnings", []).append(note)
                job["vadNote"] = note
        tid = ed_store.fill_doc(spec, fields) if spec.get("intoDoc") else None
        if tid is None:
            tid = uuid.uuid4().hex[:12]
            doc = dict({"schema": "transcribe/v1", "id": tid, "title": spec["title"], "sourcePath": spec["sourcePath"], "sourceName": spec["sourceName"]},
                       **fields, createdAt=now)
            if spec.get("clip"):
                doc["clip"] = spec["clip"]   # youtube-tools-clip/v1 の中身そのもの(transcript/v1 にもそのまま入る)
            if spec.get("evalSet"):
                doc["evalSet"] = True
            ed_lite.on_new_doc(spec, doc)   # 友人用簡易版: 印(doc["lite"])と既定の話者(簡易版でなければ何もしない)
            ed_state.atomic_write(ed_store.tx_path(tid), json.dumps(doc, ensure_ascii=False, indent=1).encode("utf-8"))
        try:
            write_words(tid, all_words, spec["model"])
        except OSError as e:
            ed_state.log.warning("単語の時刻を保存できませんでした: %s %s", tid, e)
        try:
            write_asr(tid, raw_asr, fields["recognition"]["runs"][-1])
        except (OSError, TypeError, ValueError) as e:
            ed_state.log.warning("生出力を保存できませんでした: %s %s", tid, e)
        # 30fps でなければ、同じジョブの続きで <名前>_30fps.mp4 を作って付け替える(Q1。SLOTS はこのジョブが持っている。
        # 文書はもう書いてあるので、失敗・取り消しでも元の動画のまま残る = 文字起こしの結果は失わない。評価用は作らない)
        ed_relink.norm_after_transcribe(job, spec, tid)
        # 話者の自動判別(評価用は常に・それ以外は設定 autoDiarize。v0.50.0)。「完了」にする前に足す = 判別の待ちの文書をドリルが開く間を作らない
        ed_speakers.autodiar_after_transcribe(job, spec, tid)
        job["tid"], job["progress"], job["state"], job["phase"] = tid, 1.0, "done", "完了"
        if spec.get("autoRedo") and any(SPARSE_FLAG in g["flag"] for g in segs):   # 疑わしい所を自動で認識し直す(設定。既定オフ。③-2)
            try:
                add_job(redo_spec(tid, {"redoLarge": spec.get("redoLarge", True), "oldLp": sparse_lp}), "redo")
            except ed_state.ApiError as e:
                job["warnings"] = list(job.get("warnings") or []) + ["疑わしい所の認識し直しを始められませんでした: " + e.message]
        ed_alt.alt_after_transcribe(job, spec, tid)   # 設定 autoAlt: 2つ目のエンジンでも聞いて、食い違う所に候補を出す(既定オフ・評価用は除く。D1-b)
    except Cancelled:
        job["state"], job["phase"] = "cancelled", "中止しました"
    except ed_state.ApiError as e:
        job["state"], job["error"], job["phase"] = "error", e.message, "失敗"
    except Exception as e:  # 想定外の失敗でもワーカーは止めない
        job["state"], job["error"], job["phase"] = "error", "内部エラー: %s %s" % (e.__class__.__name__, str(e)[:200]), "失敗"
    finally:
        try:
            if os.path.exists(wav):
                os.unlink(wav)
        except OSError:
            pass


def worker():
    while True:
        try:
            _priority, _seq, jid = _queue.get(timeout=60)
        except queue.Empty:
            release_idle_models()   # ジョブが無い間に、長く使っていないモデルを手放す
            continue
        work_one(jid)


def work_one(jid):
    job = _jobs.get(jid)
    try:
        if job and job["state"] == "queued" and not job["cancel"]:
            sp = job.get("spec") or {}
            info = {"id": job["id"], "kind": job.get("kind", "transcribe"), "model": sp.get("model", ""), "title": str(sp.get("title", ""))[:60], "at": int(time.time())}
            ed_state.write_mark(info)
            t0 = time.time()
            # 重い処理の同時実行数の上限(入口の中では他のツールの解析・書き出しと順番を待つ。ytt_core.jobs)
            with _heavy.SLOTS.slot(ed_state.TOOL_ID, info["title"], cancelled=lambda: job["cancel"],
                                   on_wait=lambda: job.update(phase=_heavy.WAIT_MESSAGE)) as ok:
                if not ok:
                    job["state"], job["phase"] = "cancelled", "中止しました"
                    return
                ed_state.log.info("ジョブ開始 %s %s モデル=%s(メモリ %s)", info["kind"], info["id"], info["model"], ed_state._mem())
                run_job(job)
            ed_state.log.info("ジョブ終了 %s %s 状態=%s %.0f秒(メモリ %s)%s", info["kind"], info["id"], job["state"], time.time() - t0, ed_state._mem(), (" エラー: " + str(job.get("error"))) if job.get("error") else "")
        elif job and job["state"] == "queued":
            job["state"], job["phase"] = "cancelled", "中止しました"
    except Exception as e:   # 想定外でもワーカーを止めない(止まると、以後のジョブが動かないまま待機列に残る)
        ed_state.log.exception("ワーカーで例外")
        if job:
            job["state"], job["error"], job["phase"] = "error", "内部エラー: %s %s" % (e.__class__.__name__, str(e)[:200]), "失敗"
    finally:
        _model_used[0] = time.time()   # 手放すまでの時間は、ジョブが終わった時から数える
        ed_state.write_mark(None)


def cancel_job(jid):
    job = _jobs.get(str(jid))
    if not job:
        raise ed_state.ApiError("not_found", "ジョブが見つかりません", 404)
    job["cancel"] = True
    if job["state"] == "queued":
        job["state"], job["phase"] = "cancelled", "中止しました"
    p = job.get("proc")
    if p and p.poll() is None:
        try:
            p.terminate()
        except OSError:
            pass


# ---------- 選んだ行の再認識 ----------
SPK_FLAGS = (ed_state.MIXED_FLAG, ed_state.WEAK_FLAG, ed_state.NONE_FLAG)


MAX_RANGE_SEC = 900


def validate_retranscribe(req):
    tid = str(req.get("tid") or "")
    doc = ed_store.read_transcript(tid)
    if doc.get("evalSet") is True:
        raise ed_state.ApiError("eval_set", "評価用の文字起こしは再認識できません(機械の出力=比べる基準が書き換わるため)。評価用を外してから行ってください", 400)
    src = ed_state.check_source(doc.get("sourcePath"))
    valid = {g["id"] for g in (doc.get("segments") or [])}
    ids = [i for i in dict.fromkeys(str(x)[:16] for x in (req.get("ids") or [])[:5000] if isinstance(x, (str, int))) if i in valid][:2000]
    mode = req.get("mode") if req.get("mode") in ("range", "whole") else "each"
    if not ids and mode != "whole":
        raise ed_state.ApiError("empty", "再認識する行がありません", 400)
    model = str(req.get("model") or "large-v3").strip()
    if not ed_state.valid_model(model):
        raise ed_state.ApiError("bad_model", "モデル名が正しくありません", 400)
    lang = str(req.get("language") or doc.get("language") or "ja")
    glossary = [t.strip() for t in re.split(r"[\r\n,、]+", str(req.get("glossary") or "")) if t.strip()][:200]
    gauto = ed_learn.auto_glossary(glossary) if req.get("autoGloss") is not False else []
    ctx = stream_context(doc, req.get("autoContext") is True)
    with _jobs_lock:
        if any(j.get("kind") in ("diarize", "retranscribe") and j["spec"].get("tid") == tid and j["state"] in ("queued", "loading", "extracting", "running") for j in _jobs.values()):
            raise ed_state.ApiError("busy", "この文字起こしは、すでに別の処理(話者判別・再認識)の最中です", 409)
    rng = None
    if mode == "whole":   # 動画全体(文書の範囲全体)を範囲と同じやり方で認識し直す。校正済みの行は残す(docs/design/whole-retranscribe-design.md の 3)
        segs = sorted((g for g in doc.get("segments") or []), key=lambda g: g["start"])
        a = ed_state.num(doc.get("start"), 0.0) or 0.0
        b = ed_state.num(doc.get("end")) or ed_state.media_duration(src) or max([g["end"] for g in segs] or [0.0])
        if b <= a + 0.5:
            raise ed_state.ApiError("bad_range", "動画の長さが分かりません", 400)
        if b - a > ed_state.MAX_SPAN_SEC:
            raise ed_state.ApiError("too_long", "1回に処理できるのは6時間までです", 400)
        ids = [g["id"] for g in segs if not g.get("proofed")]   # 校正済みでない行を差し替える(画面の選択は使わない)
        rng = [round(a, 3), round(b, 3)]
    elif mode == "range":   # 選んだ行の最初〜最後を、ひとまとまりの音声として認識し直す(間にある選んでいない行も含む)
        segs = sorted((g for g in doc.get("segments") or []), key=lambda g: g["start"])
        chosen = [g for g in segs if g["id"] in set(ids)]
        a, b = min(g["start"] for g in chosen), max(g["end"] for g in chosen)
        ids = [g["id"] for g in segs if a - 1e-6 <= (g["start"] + g["end"]) / 2 <= b + 1e-6]
        if b - a > MAX_RANGE_SEC:
            raise ed_state.ApiError("too_long", "範囲が長すぎます(最大%d分)。範囲を狭めてください" % (MAX_RANGE_SEC // 60), 400)
        rng = [a, b]
    return {"tid": tid, "ids": ids, "mode": mode, "range": rng, "model": model, "engine": req_engine(req, model), "language": lang if lang in ed_state.LANGS else "ja", "beam": 5,
            # 全体は画面の設定によらず「弱め」から(抜けを拾うのが目的。捨てすぎたら「なし」へ緩める)。明示の「なし」だけは尊重する
            "vadMode": ("off" if req.get("vadMode") == "off" else "weak") if mode == "whole"
            else req.get("vadMode") if mode == "range" and req.get("vadMode") in ("weak", "normal", "off") else "off",
            "wordSplit": mode in ("range", "whole") and req.get("wordSplit") is not False, "splitChars": split_chars_for(req),
            "stripPunct": req.get("stripPunct") is not False,
            "device": req.get("device") if req.get("device") in ("cuda", "cpu") else "auto", "boost": req.get("boost") is True,
            "autoDict": req.get("autoDict") is not False, "glossary": glossary + gauto, "glossAuto": gauto, "context": ctx,
            "title": {"range": "範囲を再認識: ", "whole": "全体を再認識: "}.get(mode, "再認識: ") + (str(doc.get("title") or "") or "無題")[:100]}


AUDIO_MARGIN = 3.0   # 取り出す範囲の前後の余裕(秒)。音量補正(dynaudnorm)の窓が数秒あるので、端で音が変わらないよう広めに


def audio_span(targets, doc_start, doc_end, pad=0.3):
    """再認識・比較で取り出す音声の範囲(元の動画の秒)。対象の行の最初〜最後(+余裕)だけにする。
    以前は文書の範囲全体(最大6時間)を毎回取り出していて、1行の再認識でも数十秒と、1〜2GB のメモリを使っていた。"""
    a = max(doc_start, min(float(t["start"]) for t in targets) - pad - AUDIO_MARGIN)
    b = max(float(t["end"]) for t in targets) + pad + AUDIO_MARGIN
    if doc_end:
        b = min(doc_end, b)
    return round(a, 3), round(max(b, a + 0.5), 3)


def recognize_chunk(model, kw, chunk, seg, sep, terms=()):
    """短い範囲を認識して (文章, 要確認の理由) を返す。何も認識できなければ None。"""
    if len(chunk) < 1600:
        return None
    segs, _info = model.transcribe(chunk, **kw)
    parts, lp, ns, cr = [], [], [], []
    for x in segs:
        t = (x.text or "").strip()
        if t:
            parts.append(t)
            for lst, key in ((lp, "avg_logprob"), (ns, "no_speech_prob"), (cr, "compression_ratio")):
                v = getattr(x, key, None)
                if v is not None:
                    lst.append(v)
    text = sep.join(parts)
    if not text:
        return None
    agg = {"text": text, "start": seg["start"], "end": seg["end"], "avg_logprob": min(lp) if lp else None,
           "no_speech_prob": max(ns) if ns else None, "compression_ratio": max(cr) if cr else None}
    return text, make_flags(agg, [], kw.get("language"), terms)


def replace_original(orig, a, b, text):
    """機械の出力の記録のうち、a〜b にある分を、新しい機械の出力1件に差し替える(再認識の結果を『人が直した』と誤学習しないため)。"""
    keep = [o for o in orig if not (a <= (o["start"] + o["end"]) / 2 <= b)]
    keep.append({"start": a, "end": b, "text": text[:ed_state.MAX_TEXT]})
    keep.sort(key=lambda o: o["start"])
    return keep


def apply_retranscribe(spec, results):
    with ed_store._save_lock:   # 保存と同じロック(apply_diarization と同じ理由)
        return _apply_retranscribe(spec, results)


def _apply_retranscribe(spec, results):
    doc = ed_store.read_transcript(spec["tid"])
    pairs = ed_learn.parse_replacements(ed_learn.load_settings().get("replacements")) if spec.get("autoDict") else []
    have_orig = isinstance(doc.get("original"), list)
    orig = doc["original"] if have_orig else []
    spans = [(sg["start"], sg["end"]) for sg in doc.get("segments") or [] if results.get(sg["id"])]
    record_rerun(doc, spec, "each", spans, replaced_rows(orig, spans))   # 差し替える前の機械の出力を残す(マスタープラン Q2)
    done = unsure = 0
    for sg in doc.get("segments") or []:
        r = results.get(sg["id"])
        if not r:
            continue
        raw, flag = r
        keep = [x for x in str(sg.get("flag", "")).split("、") if x in SPK_FLAGS]   # 話者の印は残し、文字の印は付け直す
        sg["text"], _ = ed_learn.apply_replacements(raw[:ed_state.MAX_TEXT], pairs)
        sg.pop("proofed", None)   # 機械が書き換えた行は、人が確認し直すまで校正済みにしない
        sg.pop("proofedAt", None)   # 校正した時刻も一緒に外す(次に校正済みにした時刻から数え直す)
        sg["flag"] = "、".join(([flag] if flag else []) + keep)[:100]
        unsure += 1 if flag else 0
        done += 1
        if have_orig:
            orig = replace_original(orig, sg["start"], sg["end"], raw)
    if have_orig:
        doc["original"] = orig
    bak = os.path.join(ed_state.TX_DIR, ".bak")
    os.makedirs(bak, exist_ok=True)
    shutil.copy2(ed_store.tx_path(spec["tid"]), os.path.join(bak, spec["tid"] + ".pre-retranscribe.json"))
    try:
        ed_store.hist_snapshot(spec["tid"], force=True)
    except OSError:
        pass
    doc["retranscribed"] = {"model": spec["model"], "lines": done, "at": int(time.time() * 1000)}
    doc["updatedAt"] = int(time.time() * 1000)
    ed_store.apply_edit_cuts(spec["tid"], doc)
    ed_state.atomic_write(ed_store.tx_path(spec["tid"]), json.dumps(doc, ensure_ascii=False, indent=1).encode("utf-8"))
    return done, unsure


def _in_spans(t, spans):
    return any(p0 <= t <= p1 for p0, p1 in spans)


def replace_original_multi(orig, a, b, items, keep=()):
    """機械の出力の記録のうち、a〜b にある分を新しい機械の出力に差し替える。keep の区間(校正済み・元のまま残した行)にある分は古いまま残す"""
    keep_o = [o for o in orig if not (a <= (o["start"] + o["end"]) / 2 <= b) or _in_spans((o["start"] + o["end"]) / 2, keep)]
    keep_o += [{"start": x["start"], "end": x["end"], "text": x["raw"][:ed_state.MAX_TEXT], **(x.get("conf") or {})} for x in items]
    keep_o.sort(key=lambda o: o["start"])
    return keep_o


# ---------- 範囲・全体の再認識の反映(docs/design/whole-retranscribe-design.md の 3-4・4-2) ----------
PROTECT_PAD = 0.05      # 守る行(校正済み・元のまま残す行)の前後の余白(秒)
MIN_NEW_LINE = 0.3      # 守る区間を避けて切り詰めた行がこれより短ければ捨てる(秒)
EMPTY_COVER = 0.3       # 元の行の時間のうち、新しい行が重なるのがこの割合未満なら「新しい認識でほぼ空」→ 元の行を残す
LOOSE_PAD = 0.5         # ほぼ空だった所を緩い条件で認識し直すときの前後の余白(秒)
EMPTY_FLAG = "再認識で文字が出なかった(元の行のまま)"
LOOSE_FLAG = "声が重なる所などを緩い条件で認識"


def _ov(a0, a1, b0, b1):
    return max(0.0, min(a1, b1) - max(a0, b0))


def merge_spans(spans):
    out = []
    for p0, p1 in sorted(spans):
        if out and p0 <= out[-1][1]:
            out[-1] = (out[-1][0], max(out[-1][1], p1))
        else:
            out.append((p0, p1))
    return out


def fit_lines(lines, protect, strip=True):
    """新しい行が守る区間 protect=[(a,b)] にかからないようにする: 真ん中が守る区間に入る行は捨て、一部だけ重なる行は外側に切り詰める
    (単語の時刻があれば文字も切り詰める)。MIN_NEW_LINE 秒未満になった行は捨てる"""
    out = []
    for x in lines:
        st, en = float(x["start"]), float(x["end"])
        mid = (st + en) / 2
        if _in_spans(mid, protect):
            continue
        for p0, p1 in protect:
            if p1 <= st or p0 >= en:
                continue
            if p0 <= st:
                st = p1
            elif en <= p1:
                en = p0
            elif mid < p0:   # 守る区間が行の中にある: 真ん中のある側を残す
                en = p0
            else:
                st = p1
        if en - st < MIN_NEW_LINE:
            continue
        if (st, en) != (x["start"], x["end"]):
            ws = [w for w in x.get("words") or [] if st - 1e-6 <= (w[0] + w[1]) / 2 <= en + 1e-6]
            y = dict(x, start=st, end=en, words=ws)
            if x.get("words"):
                joined = "".join(w[2] for w in ws).strip()
                y["raw"] = strip_punct(joined) if strip else joined
                if not y["raw"]:
                    continue
            x = y
        out.append(x)
    return out


def plan_range(doc, spec, lines):
    """範囲・全体の再認識の反映の計画(文書は変えない)。
    -> {"protect": 守る区間, "kept": 守った行(範囲にかかる、差し替えない行), "lines": 守る区間を避けた新しい行,
        "empty": 新しい認識でほぼ空だった差し替え対象の行(元のまま残す)}"""
    a, b = spec["range"]
    ids = set(spec["ids"])
    segs = [g for g in doc.get("segments") or [] if isinstance(g, dict)]
    kept = [g for g in segs if g["id"] not in ids and _ov(g["start"], g["end"], a, b) > 0]
    protect = [(g["start"] - PROTECT_PAD, g["end"] + PROTECT_PAD) for g in kept]
    fitted = fit_lines(lines, protect, spec.get("stripPunct", True) is not False)
    empty = []
    for g in segs:
        if g["id"] not in ids or not str(g.get("text") or "").strip():
            continue
        d = g["end"] - g["start"]
        cover = sum(_ov(g["start"], g["end"], x["start"], x["end"]) for x in fitted) / d if d > 0 else 1.0
        if cover < EMPTY_COVER:
            empty.append(g)
    return {"protect": protect, "kept": kept, "lines": fitted, "empty": empty}


def apply_range(spec, lines, loose=()):
    """範囲の行を、新しく認識した行に差し替える。話者は、時間が最も重なっていた元の行から引き継ぐ。
    lines=[{start,end,raw,flag,words?,conf?}]、loose = ほぼ空だった所を緩い条件で認識した行(印を付けて入れる)。
    差し替えない行(spec["ids"] に無い行。全体の再認識では校正済み)にかかる新しい行は避け、新しい認識でほぼ空だった元の行は残す(4-2・3-4)。
    -> {"lines": 入れた新しい行の数, "unsure", "kept": 守った行の数, "emptyKept": 元のまま残した行の数, "loose": 緩い条件の行の数}"""
    with ed_store._save_lock:   # 保存と同じロック(apply_diarization と同じ理由)
        return _apply_range(spec, lines, loose)


def _apply_range(spec, lines, loose=()):
    a, b = spec["range"]
    doc = ed_store.read_transcript(spec["tid"])
    pairs = ed_learn.parse_replacements(ed_learn.load_settings().get("replacements")) if spec.get("autoDict") else []
    loose = [dict(x, flag="、".join(f for f in (LOOSE_FLAG, x.get("flag", "")) if f)) for x in loose]
    plan = plan_range(doc, spec, sorted(list(lines) + loose, key=lambda x: x["start"]))
    empty_ids = {g["id"] for g in plan["empty"]}
    empty_spans = [(g["start"] - PROTECT_PAD, g["end"] + PROTECT_PAD) for g in plan["empty"]]
    keep_spans = plan["protect"] + empty_spans
    new_lines = fit_lines(plan["lines"], empty_spans, spec.get("stripPunct", True) is not False)   # 元のまま残す行にもかけない
    ids = set(spec["ids"])
    old = [g for g in doc.get("segments") or [] if g["id"] in ids]
    rest = [g for g in doc.get("segments") or [] if g["id"] not in ids or g["id"] in empty_ids]
    for g in rest:
        if g["id"] in empty_ids and EMPTY_FLAG not in str(g.get("flag") or ""):
            g["flag"] = "、".join(f for f in (str(g.get("flag") or ""), EMPTY_FLAG) if f)[:100]
    used = {g["id"] for g in rest}
    new, unsure, n = [], 0, 0
    for x in new_lines:
        best, bo = "", 0.0
        for g in old:
            ov = min(g["end"], x["end"]) - max(g["start"], x["start"])
            if ov > bo and g.get("speaker"):
                best, bo = g["speaker"], ov
        text, _ = ed_learn.apply_replacements(x["raw"][:ed_state.MAX_TEXT], pairs)
        while True:
            n += 1
            sid = "r%d" % n
            if sid not in used:
                used.add(sid)
                break
        new.append({"id": sid, "start": round(x["start"], 2), "end": round(x["end"], 2), "text": text, "speaker": best, "flag": x.get("flag", "")[:100]})
        unsure += 1 if x.get("flag") else 0
    doc["segments"] = sorted(rest + new, key=lambda g: (g["start"], g["end"]))
    record_rerun(doc, spec, "whole" if spec.get("mode") == "whole" else "range", [(a, b)],
                 replaced_rows(doc.get("original") if isinstance(doc.get("original"), list) else [], [(a, b)], keep_spans))   # 差し替える前の機械の出力を残す(Q2)
    if isinstance(doc.get("original"), list):   # 守った行・元のまま残した行の機械の出力は古いまま(人が直した行との対応を壊さない)
        doc["original"] = replace_original_multi(doc["original"], a, b, new_lines, keep_spans)
    bak = os.path.join(ed_state.TX_DIR, ".bak")
    os.makedirs(bak, exist_ok=True)
    shutil.copy2(ed_store.tx_path(spec["tid"]), os.path.join(bak, spec["tid"] + ".pre-retranscribe.json"))
    try:
        ed_store.hist_snapshot(spec["tid"], force=True)
    except OSError:
        pass
    n_loose = sum(1 for x in new_lines if LOOSE_FLAG in str(x.get("flag") or ""))
    doc["retranscribed"] = {"model": spec["model"], "lines": len(new), "range": [a, b], "whole": spec.get("mode") == "whole",
                            "kept": len(plan["kept"]), "emptyKept": len(empty_ids), "loose": n_loose, "at": int(time.time() * 1000)}
    doc["updatedAt"] = int(time.time() * 1000)
    ed_store.apply_edit_cuts(spec["tid"], doc)   # 差し替えた行の「カット済」は、編集の内容(時刻)から付け直す
    ed_state.atomic_write(ed_store.tx_path(spec["tid"]), json.dumps(doc, ensure_ascii=False, indent=1).encode("utf-8"))
    try:   # 単語の時刻も範囲の分を差し替える(守った行の単語は残す。古い文書は、ここで取り直せる = 「今の文書を分け直す」の案内)
        replace_words(spec["tid"], a, b, [w for x in new_lines for w in x.get("words") or []], spec["model"], keep_spans)
    except OSError as e:
        ed_state.log.warning("単語の時刻を保存できませんでした: %s %s", spec["tid"], e)
    return {"lines": len(new), "unsure": unsure, "kept": len(plan["kept"]), "emptyKept": len(empty_ids), "loose": n_loose}


def range_lines_real(job, model, kw, audio, spec, offset):
    """範囲の音声をひとまとまりで認識し、単語の時刻で整えた行の一覧を返す。"""
    a, b = spec["range"]
    lo, hi = max(0.0, a - offset - 0.3), b - offset + 0.3
    chunk = audio[int(lo * 16000):int(hi * 16000)]
    if len(chunk) < 1600:
        return []
    segs, _info = model.transcribe(chunk, **kw)
    sep = "" if spec["language"] in ("ja", "zh", "ko") else " "
    raw = []
    for s in segs:
        if job["cancel"]:
            raise Cancelled()
        raw.append(seg_to_dict(s))
        job["progress"] = min(0.95, 0.1 + float(s.end) / max(1e-6, hi - lo))
    return finish_range_lines(raw, spec, lo + offset)


def finish_range_lines(raw, spec, shift):
    """認識した行(チャンク内の秒)を、絶対の秒にして、範囲 [a,b] の内側に収め、要確認の印を付ける。"""
    a, b = spec["range"]
    out, prev = [], []
    for s in expand_segments(raw, spec):
        if not s["text"]:
            continue
        st, en = max(a, s["start"] + shift), min(b, s["end"] + shift)
        if en - st < 0.05:
            continue
        flag = make_flags({**s, "start": st, "end": en}, prev, spec["language"], prompt_terms(spec))
        prev.append(s["text"])
        out.append({"start": st, "end": en, "raw": s["text"], "flag": flag, "words": row_words(s, shift), "lp": s.get("avg_logprob"), "conf": machine_conf(s)})
    return out


# ---------- 疑わしい所だけ認識し直す(12 ③-2。ユーザー承認 2026-09-27: 設計どおり) ----------
REDO_PAD = 1.0          # 行の前後に足す余白(秒)。ただし隣の行にはかからない(隣の行を消さないため)
REDO_MAX_ROWS = 30      # 1回で認識し直す行の上限
REDO_MAX_SEC = 600      # 時間の上限(秒)。超えたら残りの行はやめて、そこまでの結果で置き換える
REDO_BAD_FLAGS = (SPARSE_FLAG, "よくある誤認識の文", "同じ文の繰り返し", "繰り返しの可能性", "音声でない可能性", ed_state.LEAK_FLAG)


def redo_targets(doc, ids=None):
    """認識し直す行: 「長い区間に文字が少ない」の印があり、校正済みでなく、文字が機械の出力のまま(人・辞書が直していない)。
    -> [(行, 範囲の始まり, 終わり)](範囲は前後 REDO_PAD 秒。隣の行・文書の範囲の外にはかからない)"""
    segs = sorted((g for g in doc.get("segments") or [] if isinstance(g, dict)), key=lambda g: (g["start"], g["end"]))
    orig = doc.get("original") if isinstance(doc.get("original"), list) else None
    machine = {(round(float(o["start"]), 2), round(float(o["end"]), 2)): o.get("text") for o in orig or [] if isinstance(o, dict)}
    lo_doc = ed_state.num(doc.get("start"), 0.0) or 0.0
    hi_doc = ed_state.num(doc.get("end")) or (lo_doc + (ed_state.num(doc.get("duration")) or 0.0)) or None
    out = []
    for k, g in enumerate(segs):
        if (ids is not None and g["id"] not in ids) or SPARSE_FLAG not in str(g.get("flag") or "") or g.get("proofed") is True:
            continue
        if machine and machine.get((round(float(g["start"]), 2), round(float(g["end"]), 2))) != g.get("text"):
            continue   # 機械の出力と違う(人・辞書が直した)。機械の出力が無い文書(文字起こしせずに開いた)は見分けない
        a = max(float(g["start"]) - REDO_PAD, lo_doc, float(segs[k - 1]["end"]) if k else lo_doc)
        b = float(g["end"]) + REDO_PAD
        if k + 1 < len(segs):
            b = min(b, float(segs[k + 1]["start"]))
        if hi_doc:
            b = min(b, hi_doc)
        out.append((g, round(min(a, float(g["start"])), 3), round(max(b, float(g["end"])), 3)))
    return out[:REDO_MAX_ROWS]


def redo_spec(tid, req=None):
    """疑わしい所を認識し直すジョブの指定。モデルは文字起こしと同じ(kotoba なら、redoLarge で large-v3)。VAD は普通の強さで短く区切る"""
    req = req or {}
    doc = ed_store.read_transcript(tid)
    if doc.get("evalSet") is True:
        raise ed_state.ApiError("eval_set", "評価用の文字起こしは認識し直せません(機械の出力=比べる基準が書き換わるため)", 400)
    ed_state.check_source(doc.get("sourcePath"))
    targets = redo_targets(doc)
    if not targets:
        raise ed_state.ApiError("empty", "認識し直す疑わしい行がありません(「長い区間に文字が少ない」の印があり、校正・手直ししていない行が対象です)", 400)
    model = str(doc.get("model") or "large-v3")
    if not ed_state.valid_model(model):
        model = "large-v3"
    if "kotoba" in model.lower() and req.get("redoLarge") is not False:
        model = "large-v3"   # kotoba は聞き取りにくい音声が苦手なので、重いモデルで試す(設定)
    with _jobs_lock:
        if any(j.get("kind") in EXCLUSIVE["redo"] and j["spec"].get("tid") == tid and j["state"] in ACTIVE_STATES for j in _jobs.values()):
            raise ed_state.ApiError("busy", "この文字起こしは、すでに別の処理(話者判別・再認識)の最中です", 409)
    pr = doc.get("params") if isinstance(doc.get("params"), dict) else {}
    old_lp = req.get("oldLp") if isinstance(req.get("oldLp"), dict) else {}
    return {"tid": tid, "ids": [g["id"] for g, _a, _b in targets], "model": model, "language": doc.get("language") if doc.get("language") in ed_state.LANGS else "ja",
            "beam": 5, "vadMode": "normal", "wordSplit": True, "splitChars": split_chars_for({}), "stripPunct": pr.get("stripPunct", True) is not False,
            "device": "auto", "boost": pr.get("boost") is True, "autoDict": False, "glossary": [], "glossAuto": [],
            "oldLp": {k: float(v) for k, v in old_lp.items() if isinstance(v, (int, float)) and not isinstance(v, bool)},
            "title": "疑わしい所を認識し直す: " + (str(doc.get("title") or "") or "無題")[:100]}


def redo_kwargs(spec):
    """疑わしい所を認識し直すときの設定: VAD は普通の強さで、短い無音でも区切る(長い塊に単語1つ・途中を飛ばす、を減らす)"""
    kw = whisper_kwargs(spec)
    kw["vad_filter"] = True
    kw["vad_parameters"] = {"min_silence_duration_ms": 250, "speech_pad_ms": 200}
    kw["chunk_length"] = 10
    return kw


def redo_better(row, lines, old_lp=None):
    """認識し直した結果が良くなったか: 文字が増えた・まだ疑わしい印(文字が少ない・よくある誤認識・繰り返し・BGM)が無い・
    avg_logprob が分かれば上がった。-> (良くなったか, 理由)"""
    if not lines:
        return False, "何も認識されない"
    new_chars, old_chars = sum(text_chars(x["raw"]) for x in lines), text_chars(row.get("text"))
    if new_chars <= old_chars:
        return False, "文字が増えない"
    flags = "、".join(str(x.get("flag") or "") for x in lines)
    if any(f in flags for f in REDO_BAD_FLAGS):
        return False, "まだ疑わしい"
    lps = [float(x["lp"]) for x in lines if isinstance(x.get("lp"), (int, float))]
    if old_lp is not None and lps and sum(lps) / len(lps) <= old_lp:
        return False, "自信が上がらない"
    return True, ""


def apply_redo(spec, results):
    """認識し直して良くなった行をまとめて置き換える(1回の保存。前の版は履歴に残す = 「以前の版に戻す」で戻せる)。
    途中で人が直した・校正した行は置き換えない。-> 置き換えた行の数"""
    if not results:
        return 0
    with ed_store._save_lock:
        tid = spec["tid"]
        doc = ed_store.read_transcript(tid)
        segs = [g for g in doc.get("segments") or [] if isinstance(g, dict)]
        by_id = {g["id"]: g for g in segs}
        used = {g["id"] for g in segs}
        n_rep, new_words, drop, spans, replaced = 0, [], set(), [], []
        for rid, old_text, a, b, lines in results:
            g = by_id.get(rid)
            if not g or g.get("proofed") is True or g.get("text") != old_text:
                continue
            drop.add(rid)
            n_rep += 1
            k = 0
            for x in lines:
                while True:
                    k += 1
                    sid = "%s-r%d" % (rid, k)
                    if sid not in used:
                        used.add(sid)
                        break
                segs.append({"id": sid, "start": round(x["start"], 2), "end": round(x["end"], 2), "text": x["raw"][:ed_state.MAX_TEXT],
                             "speaker": g.get("speaker", ""), "flag": str(x.get("flag") or "")[:100]})
            spans.append((a, b))
            if isinstance(doc.get("original"), list):
                replaced += replaced_rows(doc["original"], [(a, b)])   # 差し替える前の機械の出力(下で recognition.runs に残す。Q2)
                doc["original"] = replace_original_multi(doc["original"], a, b, lines)
            new_words.append((a, b, [w for x in lines for w in x.get("words") or []]))
        if not n_rep:
            return 0
        record_rerun(doc, spec, "redo", spans, replaced)
        try:
            ed_store.hist_snapshot(tid, force=True)
        except OSError:
            pass
        doc["segments"] = sorted((g for g in segs if g["id"] not in drop), key=lambda g: (g["start"], g["end"]))
        doc["updatedAt"] = int(time.time() * 1000)
        doc["redo"] = {"model": spec["model"], "rows": n_rep, "at": doc["updatedAt"]}
        ed_store.apply_edit_cuts(tid, doc)
        ed_state.atomic_write(ed_store.tx_path(tid), json.dumps(doc, ensure_ascii=False, indent=1).encode("utf-8"))
        for a, b, ws in new_words:
            try:
                replace_words(tid, a, b, ws, spec["model"])
            except OSError as e:
                ed_state.log.warning("単語の時刻を保存できませんでした: %s %s", tid, e)
        return n_rep


def run_redo(job):
    """疑わしい所だけ認識し直す(12 ③-2)。行ごとに、前後の余白を足した範囲を今の範囲の再認識と同じ仕組みで認識し直し、良くなったものだけ最後にまとめて置き換える。
    中止したら何も置き換えない。時間の上限(REDO_MAX_SEC)を超えたら残りの行はやめる"""
    spec = job["spec"]
    wav = os.path.join(ed_state.TMP_DIR, job["id"] + ".wav")
    try:
        os.makedirs(ed_state.TMP_DIR, exist_ok=True)
        doc = ed_store.read_transcript(spec["tid"])
        src = ed_state.check_source(doc.get("sourcePath"))
        targets = redo_targets(doc, set(spec["ids"]))
        if not targets:
            job["segments"], job["tid"], job["progress"], job["state"], job["phase"] = 0, spec["tid"], 1.0, "done", "完了(認識し直す行がありませんでした)"
            return
        start, end = audio_span([{"start": a, "end": b} for _g, a, b in targets], ed_state.num(doc.get("start"), 0.0) or 0.0, ed_state.num(doc.get("end")))
        job["state"], job["phase"] = "extracting", "音声を取り出し中"
        extract_audio(job, {"sourcePath": src, "start": start, "end": end, "boost": spec["boost"]}, wav)
        fake = ed_state.backend_name() == "fake"
        if not fake:
            check_engine(spec)
            job["state"] = "loading"
            model, device = load_model(spec["model"], job, spec["device"], engine=engine_of(spec))
            job["device"] = device
            audio = ed_speakers.read_wav_f32(wav)
            kw = filter_kwargs(model, redo_kwargs(spec))
        else:
            job["device"] = "cpu"
        job["state"] = "running"
        t0, results, tried, timed_out = time.monotonic(), [], 0, False
        for n, (g, a, b) in enumerate(targets):
            if job["cancel"]:
                raise Cancelled()
            if time.monotonic() - t0 > REDO_MAX_SEC:
                timed_out = True
                break
            job["phase"] = "疑わしい所を認識し直し中(%d / %d)" % (n + 1, len(targets))
            sub = dict(spec, range=[a, b])
            if fake:   # テスト用: 行の長さに見合う文字数の文(TRANSCRIBE_FAKE_REDO=worse なら短いまま)
                txt = "あ" if os.environ.get("TRANSCRIBE_FAKE_REDO") == "worse" else "認識し直した文" * max(1, int((b - a) * 2 / 7) + 1)
                lines = finish_range_lines([{"start": 0.0, "end": b - a, "text": txt, "avg_logprob": -0.2, "no_speech_prob": 0.1, "compression_ratio": 1.2}], sub, a)
                time.sleep(float(os.environ.get("TRANSCRIBE_FAKE_DELAY", "0.05")))
            else:
                lines = range_lines_real(job, model, kw, audio, sub, start)
            tried += 1
            ok, _why = redo_better(g, lines, spec.get("oldLp", {}).get(g["id"]))
            if ok:
                results.append((g["id"], g["text"], a, b, lines))
            job["progress"] = min(0.95, (n + 1) / len(targets))
        if job["cancel"]:
            raise Cancelled()
        n_rep = apply_redo(spec, results)
        job["segments"], job["unsure"] = n_rep, max(0, tried - n_rep)
        job["tid"], job["progress"], job["state"] = spec["tid"], 1.0, "done"
        job["phase"] = "完了(%d か所のうち %d か所を置き換えました%s)" % (tried, n_rep, "。時間の上限で残りはやめました" if timed_out else "")
    except Cancelled:
        job["state"], job["phase"] = "cancelled", "中止しました(何も置き換えていません)"
    except ed_state.ApiError as e:
        job["state"], job["error"], job["phase"] = "error", e.message, "失敗"
    except Exception as e:  # 想定外の失敗でもワーカーは止めない
        ed_state.log.exception("疑わしい所の認識し直しで例外")
        job["state"], job["error"], job["phase"] = "error", "内部エラー: %s %s" % (e.__class__.__name__, str(e)[:200]), "失敗"
    finally:
        try:
            if os.path.exists(wav):
                os.unlink(wav)
        except OSError:
            pass


def _fake_spans(name):
    """テスト用: 環境変数 name = "a-b,c-d"(秒)の区間の一覧"""
    out = []
    for part in os.environ.get(name, "").split(","):
        try:
            a, b = (float(x) for x in part.split("-"))
            out.append((a, b))
        except ValueError:
            pass
    return out


class RangeRecognizer:
    """範囲・全体の再認識の認識の部分(本物のモデル / 疑似)。音声は run_retranscribe が取り出した wav(先頭 = 元の動画の offset 秒)。
    main(a, b): 範囲をひとまとまりで認識(声の検出が捨てすぎたら緩めてやり直す。4-2 の 1)
    loose(spans): ほぼ空だった所だけ、声の検出なし・捨てる判定なしで認識(4-2 の 3。よくある誤認識の文は捨てる)"""

    def __init__(self, job, spec, wav, offset):
        self.job, self.spec, self.wav, self.offset = job, spec, wav, offset
        self.fake = ed_state.backend_name() == "fake"
        self.model = self.audio = None
        self.vad = None

    def _load(self):
        if self.fake or self.model is not None:
            return
        check_engine(self.spec)
        self.job["state"] = "loading"
        self.model, device = load_model(self.spec["model"], self.job, self.spec["device"], engine=engine_of(self.spec))
        self.job["device"] = device
        self.audio = ed_speakers.read_wav_f32(self.wav)
        self.job["state"] = "running"

    def _chunk(self, a, b, pad):
        lo, hi = max(0.0, a - self.offset - pad), b - self.offset + pad
        return self.audio[int(lo * 16000):int(hi * 16000)], lo

    def main(self, a, b, share=(0.0, 1.0)):
        """[a, b](元の動画の秒)を認識した行。行は [a, b] の内側に収める(全体を区間に分けたとき、隣の区間と重ならない)。
        share = 進み具合のうち、この区間が受け持つ割合(全体を区間に分けたとき)"""
        if self.fake:
            return self._fake(a, b, False, share)
        self._load()
        chunk, lo = self._chunk(a, b, 0.3)
        if len(chunk) < 1600:
            return []
        total = max(1e-6, b - a + 0.6)
        s0, s1 = share

        def progress(r, _n):
            self.job["progress"] = s0 + (s1 - s0) * min(0.9, 0.05 + r["end"] / total * 0.85)

        try:
            raw, self.vad = transcribe_vad_fallback(self.job, self.model, chunk, self.spec, progress)
        except (Cancelled, ed_state.ApiError):
            raise
        except Exception:
            if self.job.get("device") == "cuda" and self.spec["device"] == "auto":
                self.job["phase"], self.job["device"] = "GPU が使えないため CPU で処理します", "cpu"
                self.model, _ = load_model(self.spec["model"], self.job, force_cpu=True)
                raw, self.vad = transcribe_vad_fallback(self.job, self.model, chunk, self.spec, progress)
            elif self.job.get("device") == "cuda":
                raise ed_state.ApiError("gpu_failed", "GPU での処理に失敗しました。処理方式を「自動」か「CPU」にしてください", 500)
            else:
                raise
        return finish_range_lines(raw, dict(self.spec, range=[a, b]), lo + self.offset)

    def loose(self, spans):
        out = []
        if not spans:
            return out
        self.job["phase"] = "文字が出なかった所を、条件を緩めて認識中"
        if self.fake:
            for s0, s1 in spans:
                out += self._fake(s0, s1, True)
            return out
        self._load()
        kw = filter_kwargs(self.model, dict(whisper_kwargs(dict(self.spec, vadMode="off")), no_speech_threshold=None))
        for n, (s0, s1) in enumerate(spans):
            if self.job["cancel"]:
                raise Cancelled()
            chunk, lo = self._chunk(s0, s1, 0.0)
            if len(chunk) < 1600:
                continue
            segs, _info = self.model.transcribe(chunk, **kw)
            raw = []
            for x in segs:
                if self.job["cancel"]:
                    raise Cancelled()
                raw.append(seg_to_dict(x))
            lines = finish_range_lines(raw, dict(self.spec, range=[s0, s1]), lo + self.offset)
            out += [x for x in lines if "よくある誤認識の文" not in str(x.get("flag") or "") and ed_state.LEAK_FLAG not in str(x.get("flag") or "")]   # 無音から出やすい幻覚・ヒントの書き写しは入れない(元の行が残る)
            self.job["progress"] = min(0.99, 0.9 + 0.09 * (n + 1) / len(spans))
        return out

    def _fake(self, a, b, loose, share=(0.0, 1.0)):
        """疑似: 3 秒ごとに「範囲再認識N」。TRANSCRIBE_FAKE_GAP の区間には出さない(声が重なって 0 文字の所の代わり)。
        loose のときは TRANSCRIBE_FAKE_LOOSE が 1 なら 1.5 秒ごとに「緩い条件N」(無ければ何も出ない)"""
        job = self.job
        job["state"], job["device"] = "running", "cpu"
        if loose and os.environ.get("TRANSCRIBE_FAKE_LOOSE") != "1":
            return []
        gaps = [] if loose else _fake_spans("TRANSCRIBE_FAKE_GAP")
        step, label = (1.5, "緩い条件") if loose else (3.0, "範囲再認識")
        lines, t0, k = [], a, 0
        while t0 < b - 0.05:
            if job["cancel"]:
                raise Cancelled()
            e = min(b, t0 + step)
            if not any(_ov(t0, e, g0, g1) > 0 for g0, g1 in gaps):
                k += 1
                lines.append({"start": t0, "end": e, "raw": "%s%d" % (label, k), "flag": "自信が低い" if k % 2 == 0 and not loose else ""})
            t0 = e
            job["progress"] = share[0] + (share[1] - share[0]) * min(0.95, (t0 - a) / max(1e-6, b - a))
            time.sleep(float(os.environ.get("TRANSCRIBE_FAKE_DELAY", "0.05")))
        return lines


# ---------- 全体の再認識を区間ごとに保存して、続きから(計画の 9 の S-1) ----------
# 全体の再認識は最大 6 時間。途中で落ちる・中止すると、それまでの認識が全部むだになっていた。
# 長い動画は WHOLE_PART_SEC ごとの区間に分けて1つずつ認識し、終わった区間の行を transcripts/.resume/<id>.whole.json に書く。
# 同じ文書・同じ設定・同じ動画でもう一度始めたら、書いてある区間は認識せずに使う。全部終わって文書に反映したら消す。
# 短い動画(WHOLE_PART_SEC の 1.5 倍まで)は今までどおり1回で認識する(分けない = 結果は変わらない・書かない)
WHOLE_PART_SEC = 600
WHOLE_SPLIT_WINDOW = 90      # 区切りは、目安の前後この秒の中で、行の無いすき間の真ん中(話している途中で切らない)
RESUME_KEEP_SEC = 7 * 86400  # 使われなかった続きの記録は、この秒数で消す
RESUME_VERSION = 1


def whole_parts(doc, a, b, part=None):
    """[a, b] を、目安 part 秒ごとの区間 [[p0, p1], …] に分ける。区切りは、今の文書の行(どれでも)の無いすき間を選ぶ。無ければ目安の所"""
    part = float(part or WHOLE_PART_SEC)
    if b - a <= part * 1.5:
        return [[a, b]]
    rows = merge_spans([(float(g["start"]), float(g["end"])) for g in doc.get("segments") or []
                        if isinstance(g, dict) and isinstance(g.get("start"), (int, float)) and isinstance(g.get("end"), (int, float))])
    gaps = [(rows[i][1], rows[i + 1][0]) for i in range(len(rows) - 1)]
    out, t = [], a
    while b - t > part * 1.5:
        target = t + part
        lo, hi = max(t + part / 2, target - WHOLE_SPLIT_WINDOW), target + WHOLE_SPLIT_WINDOW
        best = None
        for g0, g1 in gaps:
            x0, x1 = max(g0, lo), min(g1, hi)
            if x1 > x0 and (best is None or x1 - x0 > best[1] - best[0]):
                best = (x0, x1)
        cut = round((best[0] + best[1]) / 2 if best else target, 3)
        out.append([t, cut])
        t = cut
    out.append([t, b])
    return out


def resume_path(tid):
    return os.path.join(ed_state.TX_DIR, ".resume", tid + ".whole.json")


def whole_key(spec, doc):
    """続きを使ってよいかの目印: 文書・範囲・行を作る設定・ヒントの語・エンジンとモデル・元の動画(大きさと更新日時)が同じ"""
    try:
        st = os.stat(str(doc.get("sourcePath") or ""))
        src = [st.st_size, int(st.st_mtime)]
    except OSError:
        src = None
    k = {"v": RESUME_VERSION, "tid": spec["tid"], "range": spec["range"], "engine": spec.get("engine") or tx_engines.DEFAULT, "model": spec["model"],
         "backend": ed_state.backend_name(), "language": spec["language"], "beam": spec["beam"], "vadMode": spec["vadMode"], "boost": bool(spec.get("boost")),
         "wordSplit": bool(spec.get("wordSplit")), "splitChars": spec.get("splitChars"), "stripPunct": spec.get("stripPunct", True) is not False,
         "terms": prompt_terms(spec), "source": src, "part": WHOLE_PART_SEC}
    return hashlib.sha256(json.dumps(k, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")).hexdigest()


def read_resume(tid, key):
    """続きの記録 {"parts", "done": {番号: {"lines", "vad"}}}。無い・目印が違う・壊れているときは None"""
    try:
        with open(resume_path(tid), encoding="utf-8") as f:
            d = json.load(f)
    except (OSError, ValueError):
        return None
    if not isinstance(d, dict) or d.get("key") != key or not isinstance(d.get("parts"), list) or not isinstance(d.get("done"), dict):
        return None
    return d


def write_resume(tid, d):
    path = resume_path(tid)
    folder = os.path.dirname(path)
    os.makedirs(folder, exist_ok=True)
    ed_state.atomic_write(path, json.dumps(dict(d, at=int(time.time() * 1000)), ensure_ascii=False).encode("utf-8"))
    now = time.time()
    for n in os.listdir(folder):   # 使われなかった古い続きの記録を消す
        q = os.path.join(folder, n)
        try:
            if n.endswith(".whole.json") and q != path and now - os.path.getmtime(q) > RESUME_KEEP_SEC:
                os.unlink(q)
        except OSError:
            pass


def drop_resume(tid):
    try:
        os.unlink(resume_path(tid))
    except OSError:
        pass


def whole_lines(job, spec, doc, rec):
    """全体の再認識の認識の部分。長ければ区間に分けて1つずつ認識し、終わった区間を書いておく(続きから再開できる)。-> 行の一覧。
    rec.vad には、声の検出をやり直した区間があればその記録を入れる(画面の知らせ)"""
    a, b = spec["range"]
    key = whole_key(spec, doc)
    cp = read_resume(spec["tid"], key)
    parts = cp["parts"] if cp else whole_parts(doc, a, b)
    done = cp["done"] if cp else {}
    n = len(parts)
    reused = sum(1 for i in range(n) if str(i) in done)
    if reused:
        job["resumed"] = [reused, n]
        job.setdefault("warnings", []).append("前回の途中から続けました(%d 区間のうち %d 区間は前回の認識を使いました)" % (n, reused))
        ed_state.log.info("全体の再認識を前回の途中から続けます: %s %d/%d 区間", spec["tid"], reused, n)
    lines, vads = [], []
    for i, (p0, p1) in enumerate(parts):
        if job["cancel"]:
            raise Cancelled()
        if str(i) in done:
            lines += done[str(i)].get("lines") or []
            vads.append(done[str(i)].get("vad"))
            continue
        job["phase"] = "全体を認識中(%d / %d 区間)" % (i + 1, n) if n > 1 else "全体を認識中"
        got = rec.main(p0, p1, (i / n, (i + 1) / n))
        if job["cancel"]:
            raise Cancelled()   # 途中で止めた区間は書かない(行が欠けている)
        lines += got
        vads.append(rec.vad)
        if n > 1:
            done[str(i)] = {"lines": got, "vad": rec.vad}
            try:
                write_resume(spec["tid"], {"v": RESUME_VERSION, "key": key, "parts": parts, "done": done})
            except (OSError, TypeError, ValueError) as e:   # 書けなくても認識は続ける(続きから再開できないだけ)
                ed_state.log.warning("全体の再認識の続きの記録を書けませんでした: %s %s", spec["tid"], e)
    rec.vad = next((v for v in vads if v and v.get("retries")), None) or (vads[-1] if vads else None)
    return lines


def run_retranscribe(job):
    spec = job["spec"]
    wav = os.path.join(ed_state.TMP_DIR, job["id"] + ".wav")
    try:
        os.makedirs(ed_state.TMP_DIR, exist_ok=True)
        doc = ed_store.read_transcript(spec["tid"])
        src = ed_state.check_source(doc.get("sourcePath"))
        start, end = ed_state.num(doc.get("start"), 0.0) or 0.0, ed_state.num(doc.get("end"))
        by_id = {g["id"]: g for g in doc.get("segments") or []}
        targets = sorted((by_id[i] for i in spec["ids"] if i in by_id), key=lambda g: g["start"])
        whole = spec.get("mode") == "whole"
        if not targets and not whole:
            raise ed_state.ApiError("empty", "再認識する行が見つかりません(先に削除された可能性があります)", 400)
        span_src = targets + ([{"start": spec["range"][0], "end": spec["range"][1]}] if spec.get("mode") in ("range", "whole") else [])
        start, end = audio_span(span_src, start, end)   # 以下の start は「取り出した音声の先頭が、元の動画の何秒か」
        job["state"], job["phase"] = "extracting", "音声を取り出し中"
        extract_audio(job, {"sourcePath": src, "start": start, "end": end, "boost": spec["boost"]}, wav)
        results = {}
        if spec.get("mode") in ("range", "whole"):
            a, b = spec["range"]
            rec = RangeRecognizer(job, spec, wav, start)
            job["state"], job["phase"] = "running", "全体を認識中" if whole else "範囲を認識中"
            lines = whole_lines(job, spec, doc, rec) if whole else rec.main(a, b)
            if job["cancel"]:
                raise Cancelled()
            # 新しい認識でほぼ空だった所(元の行があった所 = 声があった所)だけ、声の検出なし・捨てる判定なしで認識し直す(4-2 の 3)
            gaps = [(max(a, g["start"] - LOOSE_PAD), min(b, g["end"] + LOOSE_PAD)) for g in plan_range(doc, spec, lines)["empty"]]
            loose = rec.loose(merge_spans(gaps)) if gaps else []
            if job["cancel"]:
                raise Cancelled()
            if not lines and not loose:
                if whole:
                    drop_resume(spec["tid"])   # 認識は終わった(続きから再開するものが無い)
                raise ed_state.ApiError("no_speech", "この%sからは、文字が認識されませんでした(元の行はそのままです)" % ("動画" if whole else "範囲"), 400)
            r = apply_range(spec, lines, loose)
            if whole:
                drop_resume(spec["tid"])
            job["segments"], job["unsure"], job["kept"], job["emptyKept"], job["loose"] = r["lines"], r["unsure"], r["kept"], r["emptyKept"], r["loose"]
            note = vad_note(rec.vad)
            if note:
                job["vadNote"] = note
                job.setdefault("warnings", []).append(note)
            job["tid"], job["progress"], job["state"], job["phase"] = spec["tid"], 1.0, "done", "完了"
            return
        if ed_state.backend_name() == "fake":
            job["state"], job["phase"], job["device"] = "running", "再認識中", "cpu"
            for n, t in enumerate(targets):
                if job["cancel"]:
                    raise Cancelled()
                results[t["id"]] = (t["text"] + "(再)", "自信が低い" if n % 3 == 0 else "")
                job["progress"] = (n + 1) / len(targets)
                time.sleep(float(os.environ.get("TRANSCRIBE_FAKE_DELAY", "0.05")))
        else:
            check_engine(spec)
            job["state"] = "loading"
            model, device = load_model(spec["model"], job, spec["device"], engine=engine_of(spec))
            job["device"] = device
            audio = ed_speakers.read_wav_f32(wav)
            job["state"], job["phase"] = "running", "再認識中"
            kw = filter_kwargs(model, whisper_kwargs(spec))
            sep = "" if spec["language"] in ("ja", "zh", "ko") else " "
            for n, t in enumerate(targets):
                if job["cancel"]:
                    raise Cancelled()
                a, b = max(0.0, t["start"] - start - 0.3), t["end"] - start + 0.3   # 前後に少し余裕を持たせる(語頭・語尾が欠けにくい)
                chunk = audio[int(a * 16000):int(b * 16000)]
                try:
                    r = recognize_chunk(model, kw, chunk, t, sep, prompt_terms(spec))
                except Exception:
                    if n == 0 and device == "cuda" and spec["device"] == "auto":   # 自動のとき、GPU が実行時に失敗したら CPU でやり直す
                        job["phase"], job["device"] = "GPU が使えないため CPU で処理します", "cpu"
                        model, device = load_model(spec["model"], job, force_cpu=True)
                        kw = filter_kwargs(model, whisper_kwargs(spec))
                        r = recognize_chunk(model, kw, chunk, t, sep, prompt_terms(spec))
                    elif device == "cuda" and spec["device"] == "cuda":
                        raise ed_state.ApiError("gpu_failed", "GPU での処理に失敗しました。処理方式を「自動」か「CPU」にしてください", 500)
                    else:
                        raise
                if r:
                    text, flag = r
                    results[t["id"]] = (strip_punct(text) if spec.get("stripPunct", True) else text, flag)
                job["progress"] = min(0.99, (n + 1) / len(targets))
        if job["cancel"]:
            raise Cancelled()
        job["segments"], job["unsure"] = apply_retranscribe(spec, results)
        job["tid"], job["progress"], job["state"], job["phase"] = spec["tid"], 1.0, "done", "完了"
    except Cancelled:
        job["state"], job["phase"] = "cancelled", "中止しました"
    except ed_state.ApiError as e:
        job["state"], job["error"], job["phase"] = "error", e.message, "失敗"
    except Exception as e:
        job["state"], job["error"], job["phase"] = "error", "内部エラー: %s %s" % (e.__class__.__name__, str(e)[:200]), "失敗"
    finally:
        try:
            if os.path.exists(wav):
                os.unlink(wav)
        except OSError:
            pass
