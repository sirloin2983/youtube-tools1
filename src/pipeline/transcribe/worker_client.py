# -*- coding: utf-8 -*-
"""① 認識ワーカー(別プロセス)とのやり取りとモデル: ワーカーの起動・要求・取り消し・強制終了(WorkerClient・WORKER)・モデルの代理(RemoteModel)・
モデルの読み込み(load_model。ワーカーの中では _load_model_local)と使い回し(_models)・しばらく使わなければ手放す(release_idle_models)・
認識エンジンの選び方と確かめ(req_engine・check_engine・engines_info)・faster-whisper の引数(whisper_kwargs・filter_kwargs・cuda_compute)・
GPU で失敗したら CPU でやり直す決まり(cpu_fallback)・wav をサーバーのプロセスで読まずに渡す形(WavRef・WavSlice・read_wav_f32)。

役割で組み直す RS2-6(2026-10-10)に編集の ed_jobs(WavRef・WavSlice・read_wav_f32 は ed_speakers)から移した(中身は同じ)。
標準ライブラリ・ytt・同じパッケージの兄弟(roster・tx_engines・txbase・txenv)だけを読む。
**このモジュールは編集のサーバーのプロセスでも読む**ので、numpy・faster_whisper・ctranslate2・sherpa_onnx は IN_WORKER のときだけ通る関数の中で読む
(src/editor/tests/test_worker.py が検査)。IN_WORKER は認識ワーカー(tx_worker.py の S.IN_WORKER = True)と測る道具(dev/_evalcommon)が入れる。
ワーカーの本体のパス WORKER_SCRIPT と記録 WORKER_LOG は app(編集の serve.py)が読み込みのときと作業データの切り替えで入れる(テストも差し替える)。
入っていなければ呼ぶたびに txenv の ROOT・DATA_DIR から作る。GPU の有無・部品の有無を調べる関数(gpu_ready・has_faster_whisper・worker_python)は
編集の ed_state に残し、txenv の口から呼ぶ(テストと tx_worker が ed_state の名前を差し替えるため)。
差し替えられる名前(IN_WORKER・WORKER・WORKER_*・_load_model_local・check_engine・load_model・read_wav_f32 など)と読み手は同じこのモジュール。
ほかの部品は呼ぶたびに worker_client.名前(か転送の ed_jobs.名前・S.名前)で読む(from … import で読み直さない)。
"""
import contextlib
import gc
import itertools
import json
import os
import queue
import subprocess
import threading
import time
import wave

from ytt import errors as _errors, fsio as _fsio, jobs as _heavy, tools as _tools
from . import roster as _roster, tx_engines, txbase as _txbase, txenv as _txenv


# ---------- 読み込んだモデル ----------
_models = {}
_model_lock = threading.Lock()
_model_used = [0.0]   # 最後にモデルを使った時刻(ジョブの終わりにも更新する)
MODEL_IDLE_SEC = tx_engines.env_num("TRANSCRIBE_MODEL_IDLE_SEC", 3600, lo=0, hi=float("inf"))
# 読み込んだモデル(large-v3 で数GB)は次のジョブのために残すが、この秒数ジョブが無ければ手放す(0 = 手放さない)。
# 画面を開いたまま他の作業(動画編集など)をするときにメモリを返すため。次の文字起こしでは読み込み直し(10〜30秒程度)が入る。
# 既定は 60 分(2026-10-04 に 15 分から延ばした。続けて作業するたびの読み込みを減らす。32GB なら large-v3 + 話者判別を1時間持ってよい。git の履歴(679ff01 以前)の docs/plan/stability-review-2026-10.md)


def models_touched():
    """ジョブが終わったとき(ytt/jobs の work_one の after。serve が登録): 手放すまでの時間は、ジョブが終わった時から数える"""
    _model_used[0] = time.time()


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
        _txbase.log.info("しばらく使っていないモデルを解放: %s(メモリ %s)", ", ".join("/".join(k) for k in _models), _tools.memory_label())
        _models.clear()
    gc.collect()
    return True


# ---------- 認識ワーカー(別プロセス。統合計画の段階3-3) ----------
# faster-whisper(ctranslate2)と sherpa-onnx はネイティブコードで、メモリ不足・GPU のドライバなどで Python ごと落ちることがある。
# 入口の統合サーバーに取り込むと、同じプロセスにスタジオ・cut2resolve もいるので、落ちると全部が止まり編集中の内容が消える。
# そこで、モデルの読み込み・認識・話者判別だけを tx_worker.py(別プロセス)で行う。サーバー側のジョブの流れ(待機列・行の整形・保存)は変えない。
# やり取り: ワーカーの標準入力に要求を1行1件の JSON(ASCII)で送り、標準出力から途中経過・結果を1行1件で受け取る。1度に1つの要求だけ。
# 落ちたら(標準出力が閉じたら)そのジョブを「失敗」にし、次の要求でワーカーを起動し直す。しばらく使わなければワーカーごと終わらせてメモリを返す。
IN_WORKER = False   # tx_worker.py の中で True にする(そのときは load_model などが本体をその場で実行する)
WORKER_SCRIPT = None   # 認識ワーカーの本体(編集の tx_worker.py)。app(serve)が読み込みのときに入れる・テストが差し替える。None なら txenv の ROOT の tx_worker.py
WORKER_LOG = None      # ワーカーの標準エラーの記録。app が入れる(作業データの切り替え set_data_dir も)。None なら txenv の DATA_DIR の worker.log
WORKER_LOG_MAX = 1024 * 1024
WORKER_CANCEL_GRACE = 15   # 取り消してから、この秒数で止まらなければワーカーを強制終了する
WORKER_SILENCE_TIMEOUT = 20 * 60   # ワーカーから何も届かない時間の上限(秒)。超えたら強制終了してそのジョブを失敗にする(黙ったワーカーを待ち続けて SLOTS を持ったまま他のツールを塞がない。夜間の見直し 高。2026-10-01 ユーザー決定)
WORKER_LINE_MAX = 8 * 1024 * 1024


def worker_script():
    """認識ワーカーの本体のパス(WORKER_SCRIPT。入っていなければ txenv の ROOT の tx_worker.py)。呼ぶたびに読む(テストの差し替え)"""
    return WORKER_SCRIPT or os.path.join(_txenv.ROOT, "tx_worker.py")


def worker_log():
    """ワーカーの標準エラーの記録のパス(WORKER_LOG。入っていなければ txenv の DATA_DIR の worker.log)"""
    return WORKER_LOG or os.path.join(_txenv.DATA_DIR, "worker.log")


# Windows: 黒い画面を増やさない・Ctrl+C / Ctrl+Break がワーカーに直接届かないようにする(終わらせるのは親の役目)。
# ed_state(GPU の有無・部品の有無を別プロセスで調べる)が呼ぶ名前だけを残す(写しではなく ytt_core.tools.no_window_flags そのもの。
# ed_state が _tools.no_window_flags(new_group=True) を直接呼ぶようになったら消す)


def _worker_priority():
    """Windows: 認識のワーカーは「通常より下」の優先度で動かす(2026-10-04)。長い文字起こしが CPU を使っている間も、
    画面の操作・スタジオの書き出し・パック作りが先に CPU を取れる(同時実行の上限 SLOTS は 2 のまま。git の履歴(679ff01 以前)の docs/plan/stability-review-2026-10.md)。
    環境変数 TRANSCRIBE_WORKER_PRIORITY=normal で今までどおり。-> tools.no_window_flags の priority("low" か None)"""
    return None if os.environ.get("TRANSCRIBE_WORKER_PRIORITY", "").strip().lower() == "normal" else "low"


def worker_env():
    env = dict(os.environ)
    env["PYTHONUNBUFFERED"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    import ytt as _yc   # ワーカーも同じ ytt(共通部品)を使う(一時フォルダに写したテストでも見つかるように)
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
            raise _errors.ApiError("stopping", "終了処理中のため、文字起こしを始められません", 503)
        script, log = worker_script(), worker_log()
        if not os.path.isfile(script):
            raise _errors.ApiError("missing_module", "文字起こしの部品が見つかりません。ツールのフォルダの中身をまとめて入れ直してください(新しい zip を展開し直す)", 500,
                                    {"detail": "tx_worker.py が見つかりません: %s" % script})
        try:
            if os.path.exists(log) and os.path.getsize(log) > WORKER_LOG_MAX:
                _fsio.replace_retry(log, log + ".old")
        except OSError:
            pass
        try:
            self.log_fp = open(log, "ab")
        except OSError:
            self.log_fp = None
        self.proc = subprocess.Popen([_txenv.worker_python(), "-u", script], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                     stderr=self.log_fp or subprocess.DEVNULL, cwd=_txenv.ROOT, env=worker_env(),
                                     creationflags=_tools.no_window_flags(new_group=True, priority=_worker_priority()))
        self.starts += 1
        self.q = queue.Queue()   # 起動ごとに新しい列(前のプロセスの読み残しを混ぜない)
        threading.Thread(target=self._reader, args=(self.proc, self.q), daemon=True, name="tx-worker-reader").start()
        _txbase.log.info("認識ワーカーを起動 pid=%s(%d回目)", self.proc.pid, self.starts)

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
            _txbase.log.warning("認識ワーカーが終わっていました(終了コード %s)。起動し直します", self.proc.returncode)
            self._reap()
        if self.proc is None:
            self._spawn()

    def _reap(self):
        p, self.proc = self.proc, None
        if p is not None:
            for f in (p.stdin, p.stdout):
                with contextlib.suppress(OSError, ValueError):
                    f.close()
            with contextlib.suppress(subprocess.TimeoutExpired):
                p.wait(5)
        if self.log_fp is not None:
            with contextlib.suppress(OSError):
                self.log_fp.close()
            self.log_fp = None

    def kill(self):
        p = self.proc   # 取り消しのタイマー(別のスレッド)からも呼ばれるので、1 回だけ読む
        if p is not None:
            _tools.kill_quiet(p)

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
            _txbase.log.info("しばらく使っていないので認識ワーカーを終了(モデルのメモリを返す)")
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
                _txbase.log.warning("認識ワーカーが取り消しに応じないため強制終了します")
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
            _txbase.log.error("認識ワーカーから %.0f 秒なにも届かないため強制終了します", WORKER_SILENCE_TIMEOUT)
            self.kill()
            self._reap()
            if self.killed_rid == rid:
                raise _heavy.Cancelled()
            raise _errors.ApiError("worker_hung", "文字起こしの部品(認識を行う別プロセス)が %d 分なにも応答しないため止めました。もう一度実行すると部品を起動し直します"
                                          "(モデルの初回のダウンロード中に出たときは、そのままもう一度実行してください。詳しくは worker.log)" % max(1, round(WORKER_SILENCE_TIMEOUT / 60)), 500)
        if not line:
            code = None
            try:
                code = self.proc.wait(5)
            except subprocess.TimeoutExpired:
                self.kill()
            self._reap()
            if self.killed_rid == rid:
                raise _heavy.Cancelled()
            _txbase.log.error("認識ワーカーが異常終了しました(終了コード %s)", code)
            raise _errors.ApiError("worker_crashed", "文字起こしの部品(認識を行う別プロセス)が途中で止まりました(終了コード %s)。"
                                             "メモリ不足などが考えられます。もう一度実行すると部品を起動し直します(詳しくは worker.log)" % code, 500)
        try:
            m = json.loads(line.decode("utf-8"))
        except (UnicodeDecodeError, ValueError):
            _txbase.log.warning("認識ワーカーの出力を読めません: %r", line[:200])
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
            return _heavy.Cancelled()
        if code == "exception":
            return WorkerError("%s: %s" % (m.get("type") or "Exception", msg))
        try:
            status = int(m.get("status") or 500)
        except (TypeError, ValueError):
            status = 500
        return _errors.ApiError(code or "worker_error", msg or "文字起こしの部品でエラーが起きました", status)

    def stream(self, op, args, job=None):
        """要求を送り、("item", v) を途中で、最後に ("result", v) を返す生成器。エラーは例外(ApiError / Cancelled / WorkerError)。
        途中で使うのをやめた(close された)ときは、ワーカーに取り消しを伝えて結果を読み捨て、やり取りの順番をそろえてから抜ける。"""
        if isinstance(job, dict) and job.get("cancel"):   # 取り消し済みなら、ワーカーの起動も要求もしない
            raise _heavy.Cancelled()
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
        except (_errors.ApiError, _heavy.Cancelled):
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
        raise _errors.ApiError("worker_error", "文字起こしの部品から結果が返りませんでした", 500)


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
        elif isinstance(audio, WavSlice):   # 範囲の音声は、wav のパスとサンプルの範囲だけを渡す(ワーカーが読む)
            a = {"wav": audio.path, "from": audio.a, "to": audio.b}
        elif isinstance(audio, WavRef):
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


def req_engine(req, model):
    """要求の認識エンジン(無ければ faster-whisper)。一覧に無い名前・そのエンジンで使えないモデルは断る。
    画面の「処理方式」の GPU(AMD など・whisper.cpp)は device = "vulkan" で来る → whisper.cpp(機器は auto = Vulkan。黙って CPU にしない)"""
    e = str(req.get("engine") or (tx_engines.WhisperCpp.id if req.get("device") == "vulkan" else tx_engines.DEFAULT))
    if not tx_engines.valid(e):
        raise _errors.ApiError("bad_engine", "知らない認識エンジンです: %s" % e[:40], 400)
    if not tx_engines.get(e).valid_model(model):
        if e == tx_engines.WhisperCpp.id:
            raise _errors.ApiError("bad_model", "GPU(whisper.cpp)で使えるモデルは %s だけです(今は %s)。モデルを変えてください" % ("・".join(tx_engines.WCPP_MODELS), model[:60]), 400)
        raise _errors.ApiError("bad_model", "%s では使えないモデルです: %s" % (e, model[:60]), 400)
    return e


def engines_info():
    """画面に出すエンジンの準備(/api/tools)。whisper.cpp は作ってあるときだけ「処理方式」に出す"""
    ok, why = tx_engines.WhisperCpp.ready(tx_engines.engine_home())
    return {"wcpp": {"ready": bool(ok), "why": why, "models": list(tx_engines.WCPP_MODELS), "version": tx_engines.WHISPER_CPP["version"]}}


def check_engine(spec):
    """認識を始める前に、そのエンジンが使えるか(サーバー側。ネイティブの部品は読まない)"""
    e = tx_engines.engine_of(spec)
    if e == tx_engines.DEFAULT or _txenv.worker_fake():   # worker-fake(テスト)のワーカーは偽の whisper-cli を使う
        if not _txenv.has_faster_whisper():
            raise _errors.ApiError("no_whisper", "faster-whisper が入っていません(README の準備手順を確認してください)", 400)
        return
    ok, why = tx_engines.get(e).ready(tx_engines.engine_home())
    if not ok:
        raise _errors.ApiError("engine_missing", why, 400)


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
        raise _errors.ApiError("bad_engine", str(e), 400)
    env = os.environ.get("TRANSCRIBE_DEVICE")
    if force_cpu:
        pref = "cpu"
    elif env in ("cuda", "cpu"):
        pref = env
    # 試す機器の順はエンジンが決める(faster-whisper = CUDA → CPU、whisper.cpp = Vulkan だけ・CPU は明示のときだけ)。CUDA の有無を調べるのは faster-whisper のときだけ
    order = eng.device_order(pref, eng is tx_engines.FasterWhisper and pref == "auto" and _txenv.gpu_ready())
    hooks = {"cancelled": lambda: bool(job.get("cancel")),
             "download": lambda r: job.__setitem__("phase", "モデルを取得中 %d%%(初回だけ)" % int(r * 100))}
    with _model_lock:
        last = None
        for dev in order:
            key = (name, dev, eng.id)
            _model_used[0] = time.time()
            if key in _models:
                return _models[key], dev
            heavy = [k for k in _models if not tx_engines.get(k[2]).light]   # 小さいモデル(SenseVoice = light)は主のモデルと一緒に持つ(0.60.0)
            if heavy and not eng.light:   # 別の(重い)モデルは手放す(large-v3 と turbo を交互に使ってもメモリが積み上がらない。落ちる原因の1つ)
                _txbase.log.info("モデルを解放: %s(メモリ %s)", ", ".join("/".join(k) for k in heavy), _tools.memory_label())
                for k in heavy:
                    _models.pop(k, None)
                gc.collect()
            job["phase"] = "モデルを読み込み中(初回はダウンロードのため数分かかります)"
            try:
                _txbase.log.info("モデルを読み込み: %s/%s/%s(メモリ %s)", eng.id, name, dev, _tools.memory_label())
                m = eng.create(name, dev, cuda_compute() if dev == "cuda" else "int8", _txbase.log, tx_engines.engine_home(), hooks)
                _txbase.log.info("モデルを読み込み終わり: %s/%s(メモリ %s)", name, dev, _tools.memory_label())
            except tx_engines.EngineError as e:   # エンジンが理由を書いた失敗(実行ファイルが無い・取得の失敗・GPU を使えない)はそのまま出す
                if e.code == "cancelled":
                    raise _heavy.Cancelled()
                raise _errors.ApiError(e.code, e.message, e.status)
            except MemoryError:
                raise _errors.ApiError("no_memory", "メモリが足りずモデルを読み込めませんでした。他のアプリ(動画編集ソフトなど)を閉じてから、もう一度試してください", 500)
            except Exception as e:
                last = e
                if dev == "cuda" and pref == "auto":
                    continue  # 自動のときは、GPU が使えなければ CPU にする
                if dev == "cuda":
                    raise _errors.ApiError("gpu_failed", "GPU で読み込めませんでした。GPU 用ライブラリが未導入の可能性があります。install-gpu.bat を実行するか、処理方式を「自動」か「CPU」にしてください", 500,
                                            {"detail": str(e)[:300]})
                raise _errors.ApiError("model_failed", "モデルを読み込めませんでした。ネットワーク接続とモデル名を確かめて、もう一度始めてください", 500, {"detail": str(e)[:300]})
            _models[key] = m
            return m, dev
        raise _errors.ApiError("model_failed", "モデルを読み込めませんでした。もう一度始めてください", 500, {"detail": str(last)[:300]})


CUDA_COMPUTE_TYPES = ("float16", "int8_float16", "int8", "float32")


def cuda_compute():
    """GPU で使う精度の型。環境変数 TRANSCRIBE_CUDA_COMPUTE(例: int8_float16 = 8GB の GPU に収める)。無い・違えば float16(今まで)"""
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
    terms = _roster.prompt_terms(spec)
    if terms:
        kw["initial_prompt"] = "用語: " + "、".join(terms)
        kw["hotwords"] = ", ".join(_roster.fit(list(spec.get("glossary") or []) + list((spec.get("context") or {}).get("terms") or []), _roster.HOT_LIMIT, 2))
    return kw


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


GPU_FAILED_MSG = "GPU での処理に失敗しました。処理方式を「自動」か「CPU」にしてください"
GPU_FAILED_SETUP_MSG = "GPU での処理に失敗しました。GPU 用ライブラリが未導入の可能性があります(install-gpu.bat を実行するか、処理方式を「自動」か「CPU」にしてください)"
CPU_FALLBACK_PHASE = "GPU が使えないため CPU で処理します"


def cpu_fallback(job, device, pref, run, reload, msg=GPU_FAILED_MSG, retry=True, passthrough=(_heavy.Cancelled, _errors.ApiError)):
    """GPU(CUDA)で実行時に失敗したとき(CUDA のライブラリ不足など)の決まり。新規の文字起こし・行ごとの再認識(ChunkModel)・範囲と全体の再認識で 1 つ。
    run() を実行し、例外が起きたら: GPU で動いていなければ(device が cuda でない)そのまま上げる / 処理方式 pref が GPU 固定(cuda)なら gpu_failed(文 msg)/
    それ以外(自動)は phase と job["device"] を CPU にして、reload()(CPU で読み直す)のあともう一度 run()。
    retry=False なら CPU でやり直さずにそのまま上げる(行ごとの再認識の 2 行目から)。passthrough の例外(取り消し・理由のある失敗)は調べずに上げる"""
    try:
        return run()
    except passthrough:
        raise
    except Exception:
        if device != "cuda":
            raise
        if pref == "cuda":
            raise _errors.ApiError("gpu_failed", msg, 500)
        if not retry:
            raise
        job["phase"], job["device"] = CPU_FALLBACK_PHASE, "cpu"
        reload()
        return run()


# ---------- wav を読まずに渡す形(サーバーのプロセス用。RS2-6 に ed_speakers から移した) ----------
class WavRef:
    """16kHz・モノラル・16bit の wav を「読まずに」表す(サーバーのプロセス用)。audio[a:b] は WavSlice になり、
    認識ワーカーに渡すと、ワーカーがその範囲だけを読む。サーバーのプロセスに numpy(と音声全体のメモリ)を持ち込まないため。"""

    def __init__(self, path):
        with wave.open(path, "rb") as w:
            if not tx_engines.is_16k_mono(w):
                raise _errors.ApiError("diar_failed", "音声の形式が想定と違います", 500)
            self.n = w.getnframes()
        self.path = path

    def __len__(self):
        return self.n

    def __getitem__(self, sl):
        if not isinstance(sl, slice) or sl.step not in (None, 1):
            raise TypeError("WavRef は audio[a:b] の形でだけ使えます")
        a, b, _ = sl.indices(self.n)
        return WavSlice(self.path, a, max(a, b))


class WavSlice:
    def __init__(self, path, a, b):
        self.path, self.a, self.b = path, a, b

    def __len__(self):
        return self.b - self.a


def read_wav_f32(path):
    if not IN_WORKER:
        return WavRef(path)
    import numpy as np
    with wave.open(path, "rb") as w:
        if not tx_engines.is_16k_mono(w):
            raise _errors.ApiError("diar_failed", "音声の形式が想定と違います", 500)
        raw = w.readframes(w.getnframes())
    return np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
