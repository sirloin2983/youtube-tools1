#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""① 文字起こしの認識ワーカー(統合計画の段階3-3)。編集のサーバーが別プロセスとして起動する(worker_client.WorkerClient)。人が直接起動するものではない。

    python worker.py            要求を標準入力から読み、結果を標準出力へ書く(pipeline/transcribe/worker_client.py の WorkerClient が使う)
    python worker.py --probe    GPU(CUDA)が使えるかを調べて {"cuda": true|false} を出して終わる

faster-whisper(ctranslate2)と sherpa-onnx はネイティブコードで、メモリ不足・GPU のドライバなどでプロセスごと落ちることがある。
その処理だけをこのプロセスで行い、落ちてもサーバー(入口に取り込んだときはスタジオ・cut2resolve も同じプロセス)は止まらないようにする。
中身の処理は ① の部品の関数(worker_client._load_model_local・diarize._diarize_local・_embed_local)をそのまま使う(2か所に同じ処理を書かない)。

役割で組み直す RS2-9(2026-10-10)に src/editor/tx_worker.py から移した(旧い場所は起動用の転送だけ。RS5 で消す)。編集の serve を読まない:
- 起動はスクリプトのパスのまま(python -u <src>/pipeline/transcribe/worker.py。cwd は編集のフォルダ)なので相対 import を使えない。
  スクリプトとして起動したときだけ、sys.path からこのフォルダを外して src を先頭に置き、兄弟は絶対 import(from pipeline.transcribe import …)で読む(層の決まりの例外)。
  import したとき(テスト・dev/_evalcommon の _audio)は sys.path に触らない
- 置き場所と外の道具の口(txenv)はこのプロセスで登録する(_setup_env): DATA_DIR = 環境変数 TRANSCRIBE_DATA_DIR(サーバーの worker_env が必ず渡す。
  無ければ以前の既定 = 編集のフォルダ)・gpu_ready = worker_client._gpu_ready_local(呼ぶたびに読む = 疑似の差し替えが効く)・worker_fake = 環境変数 TRANSCRIBE_BACKEND
- 疑似(TRANSCRIBE_BACKEND=worker-fake のテスト)は ④ の eval/fake/fake_worker.install()。① は ④ を import しないので、サーバーが渡す環境変数
  YTT_WORKER_FAKES(モジュール名の文字。app = 編集の serve が worker_client.FAKES_MODULE に入れる)を importlib で読む
- 読むのは標準ライブラリ・ytt・pipeline/transcribe だけ(編集の ed_*・serve は読まない)。numpy などは要求を処理する部品の関数の中で

やり取り(1行1件の JSON。ASCII):
  要求  {"rid": 1, "op": "load", "name": "large-v3", "pref": "auto", "force_cpu": false, "engine": "faster-whisper"}
        {"rid": 2, "op": "transcribe", "name", "device", "engine", "audio": {"wav": パス} | {"wav", "from", "to"}, "kw": {...}}
        engine = 認識エンジン(tx_engines.py の名前。無ければ faster-whisper。計画 段2-1)
        {"rid": 3, "op": "diarize", "wav": パス, "num": 0, "emb": "voxceleb"}   (任意で "threshold"・"minOn"・"minOff" = 判別の設定を変えて測るとき)
        {"rid": 4, "op": "embed", "wav": パス, "emb": "voxceleb", "groups": [[[開始, 終了], ...], ...]}   声の特徴(A-3。音声の先頭からの秒)
        {"rid": 5, "op": "complete", "name": "qwen3-8b", "device": "vulkan", "engine": "llama-text", "messages": [...], "max_tokens": 400}   文字の LLM(P18。結果 {"content"})
        {"op": "cancel", "rid": 2}   /   {"op": "quit"}
  応答  {"rid", "ev": "set", "k": "phase"|"state"|"device"|"progress", "v"}   途中経過(サーバーのジョブに写す)
        {"rid", "ev": "item", "v": 行}                                          認識した1行(transcribe)
        {"rid", "ev": "result", "v": ...}   /   {"rid", "ev": "error", "code", "message", "status"}
標準出力はやり取り専用にする(ライブラリの print・ネイティブの出力は標準エラー = worker.log へ回す)。
標準入力が閉じた(サーバーが終わった・落ちた)ら、すぐに終わる(取り残されたプロセスがメモリを持ち続けないように)。
"""
import faulthandler
import importlib
import json
import logging
import os
import queue
import re
import sys
import threading
import time
import wave

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.dirname(os.path.dirname(HERE))   # transcribe -> pipeline -> src
if not __package__:   # スクリプトとして起動したとき(python worker.py・旧い場所の転送の runpy)だけ。兄弟を裸の名前で読まないように、このフォルダを外して src を先頭に
    sys.path[:] = [SRC] + [p for p in sys.path if os.path.normcase(os.path.abspath(p or os.curdir)) not in (os.path.normcase(HERE), os.path.normcase(SRC))]
from pipeline.transcribe import diarize, tx_engines, txenv, worker_client  # noqa: E402  (スクリプトとして動くので相対 import は使えない = 絶対 import。RS2-9)
from ytt import errors as _errors, jobs as _heavy, layout as _layout  # noqa: E402

PROGRESS_EVERY = 0.25   # 進み具合を送る間隔(秒)。行ごとに送ると、長い音声で無駄に多くなる


def _protocol_stream():
    """標準出力をやり取り専用にする: 元の標準出力(fd 1)を複製して使い、fd 1 は標準エラーにつなぎ直す
    (faster-whisper・ダウンロードの進み具合・ネイティブコードの printf がやり取りに混ざらないように)。"""
    fd = os.dup(1)
    os.dup2(2, 1)
    sys.stdout = sys.stderr
    return os.fdopen(fd, "wb", buffering=0)


def _protocol_input():
    """標準入力もやり取り専用にする: 元の標準入力(fd 0)を複製して読み、fd 0 は NUL につなぎ直す。
    Windows では、別のスレッドが標準入力のパイプを読んで待っている間に、ネイティブの部品(numpy・ctranslate2・onnxruntime の DLL)を
    読み込むと、その初期化が標準入力に触れて、次の要求が届くまで止まる(2026-09-26 に PC で再現。範囲の再認識のテストが止まっていた・
    最初の文字起こしが遅かった件の原因と思われる)。os.dup2 は fd 0〜2 なら Windows の標準ハンドルも付け替える"""
    fd = os.dup(0)
    try:
        nul = os.open(os.devnull, os.O_RDONLY)
        os.dup2(nul, 0)
        os.close(nul)
    except OSError:
        pass
    sys.stdin = open(os.devnull, "r")
    return os.fdopen(fd, "rb")   # 元の sys.stdin.buffer と同じくバッファつき(届いた分だけで1行を返す)


class Out:
    def __init__(self, fp):
        self.fp, self.lock = fp, threading.Lock()

    def send(self, obj):
        data = (json.dumps(obj, ensure_ascii=True, separators=(",", ":"), default=str) + "\n").encode("ascii")
        with self.lock:
            self.fp.write(data)


class JobProxy(dict):
    """部品の関数(_load_model_local・_diarize_local など)に渡す job の代わり。phase・state・device・progress を書くと、サーバーへ途中経過として送る。
    job["cancel"] は、サーバーから取り消しが届いていれば True。"""

    def __init__(self, rid, out, cancels):
        super().__init__(phase="", state="", device="", progress=0.0, proc=None)
        self._rid, self._out, self._cancels, self._last = rid, out, cancels, 0.0

    def __getitem__(self, k):
        if k == "cancel":
            return self._rid in self._cancels
        return super().__getitem__(k)

    def get(self, k, default=None):
        if k == "cancel":
            return self._rid in self._cancels
        return super().get(k, default)

    def __setitem__(self, k, v):
        super().__setitem__(k, v)
        if k in ("phase", "state", "device"):
            self._out.send({"rid": self._rid, "ev": "set", "k": k, "v": v})
        elif k == "progress":
            now = time.monotonic()
            if now - self._last >= PROGRESS_EVERY:
                self._last = now
                self._out.send({"rid": self._rid, "ev": "set", "k": k, "v": v})


def _seg_dict(s):
    words = []
    for w in getattr(s, "words", None) or []:
        a, b = getattr(w, "start", None), getattr(w, "end", None)
        if a is not None and b is not None:
            p = getattr(w, "probability", None)   # 単語の確信度(生出力 <id>.asr.json に残す)
            words.append({"start": float(a), "end": float(b), "word": str(getattr(w, "word", "")), "probability": float(p) if p is not None else None})
    d = {"start": float(s.start), "end": float(s.end), "text": s.text or "", "words": words}
    for k in ("avg_logprob", "no_speech_prob", "compression_ratio"):
        v = getattr(s, k, None)
        d[k] = float(v) if v is not None else None
    return d


def _audio(a):
    """{"wav": パス} → パスのまま(faster-whisper が読む)。{"wav", "from", "to"} → その範囲のサンプル(float32。16kHz・モノラル)。"""
    path = str(a.get("wav") or "")
    if "from" not in a:
        return path
    import numpy as np
    lo, hi = int(a["from"]), int(a["to"])
    with wave.open(path, "rb") as w:
        if not tx_engines.is_16k_mono(w):
            raise ValueError("音声の形式が想定と違います")
        lo = max(0, min(lo, w.getnframes()))
        w.setpos(lo)
        raw = w.readframes(max(0, hi - lo))
    return np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0


# ---------------------------------------------------------------- このプロセスの口(txenv)と疑似(RS2-9)

def _fake_mode():
    """テスト用の TRANSCRIBE_BACKEND=worker-fake か(サーバーの ed_state.worker_fake と同じ決まり。ワーカーは serve を読まないのでここで見る)"""
    return os.environ.get("TRANSCRIBE_BACKEND") == "worker-fake"


def _data_dir():
    """作業データ(判別のモデル models/diar・エンジンの実行ファイルとモデル)。サーバーの worker_client.worker_env が環境変数 TRANSCRIBE_DATA_DIR で必ず渡す。
    無ければ以前の既定(編集の ed_state.DATA_DIR の既定 = 編集のフォルダ)"""
    return os.environ.get("TRANSCRIBE_DATA_DIR") or _layout.tool_dir("transcribe")


def _setup_env():
    """このプロセスの txenv の口(ワーカーの中で読む鍵だけ = DATA_DIR・gpu_ready・worker_fake)。どれも呼ぶたびに読む(疑似の差し替えが効く)"""
    txenv.register(DATA_DIR=_data_dir, gpu_ready=lambda: worker_client._gpu_ready_local, worker_fake=lambda: _fake_mode)


_MODULE_NAME = re.compile(r"[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*")


def _install_fakes():
    """worker-fake(テスト)のとき、サーバーが渡したモジュール(環境変数 worker_client.FAKES_ENV。④ の eval/fake/fake_worker)の install() を呼ぶ
    (faster-whisper・sherpa-onnx・whisper.cpp などを偽物に。本物の _load_model_local の流れはそのまま通す)。
    ① は ④ を import しない = 名前の文字を app から受け取って importlib で読む。worker-fake でなければ、環境変数があっても読まない"""
    if not _fake_mode():
        return
    name = os.environ.get(worker_client.FAKES_ENV, "")
    if not _MODULE_NAME.fullmatch(name):
        logging.getLogger("tx").warning("worker-fake ですが疑似の部品の名前(%s)がありません: %r", worker_client.FAKES_ENV, name[:80])
        return
    importlib.import_module(name).install()


# ---------------------------------------------------------------- 本体

def _engine(m):
    """要求の認識エンジンの名前(一覧に無ければ ApiError。要求の文字列からクラスを探さない)"""
    e = str(m.get("engine") or tx_engines.DEFAULT)
    if not tx_engines.valid(e):
        raise _errors.ApiError("bad_engine", "知らない認識エンジンです: %s" % e[:40], 400)
    return e


def _op_load(m, rid, job, out, cancels):
    model, dev = worker_client._load_model_local(str(m.get("name")), job, str(m.get("pref") or "auto"), bool(m.get("force_cpu")), _engine(m))
    return {"device": dev, "params": list(model.params())}   # エンジンが受け付ける引数の名前(サーバーはこれに無い引数を渡さない)


def _op_transcribe(m, rid, job, out, cancels):
    name, dev, eng = str(m.get("name")), str(m.get("device") or "cpu"), _engine(m)
    with worker_client._model_lock:
        model = worker_client._models.get((name, dev, eng))
    if model is None:   # 読み込んだあとに手放された(通常は起きない)→ 同じ機器で読み直す
        model, dev = worker_client._load_model_local(name, job, dev, False, eng)
    audio = _audio(m.get("audio") or {})
    kw = m.get("kw") or {}
    # 子プロセスで動くエンジン(whisper.cpp)は、終わるまで行が出ないので、取り消しと進み具合をエンジンに渡す
    model.hooks = {"cancelled": lambda: rid in cancels, "progress": lambda v: job.__setitem__("progress", v)}
    segs, info = model.transcribe(audio, **kw)
    # 声の検出(VAD)の結果は、行を読み始める前に分かる(faster-whisper は transcribe() の中で先に VAD をかける)。
    # 先に送ると、サーバーは「ほとんど捨てた」ときに行を読まずにやり直せる(docs/design/whole-retranscribe-design.md の 4-2)
    out.send({"rid": rid, "ev": "info", "v": {k: (float(getattr(info, k)) if isinstance(getattr(info, k, None), (int, float)) else None)
                                               for k in ("duration", "duration_after_vad")}})
    n = 0
    for s in segs:
        if rid in cancels:
            break
        out.send({"rid": rid, "ev": "item", "v": _seg_dict(s)})
        n += 1
    worker_client._model_used[0] = time.time()
    return {"count": n, "cancelled": rid in cancels, "language": getattr(info, "language", None)}


def _op_diarize(m, rid, job, out, cancels):
    # 判別の設定(threshold・minOn・minOff)は任意。無い要求は以前と同じ呼び方(既定の値)
    tune = {k: m[w] for k, w in diarize.DIAR_TUNE if m.get(w) is not None}
    turns = diarize._diarize_local(job, str(m.get("wav")), int(m.get("num") or 0), str(m.get("emb") or diarize.DIAR_EMB_DEFAULT), **tune)
    return [[float(a), float(b), int(k)] for a, b, k in turns]


def _op_embed(m, rid, job, out, cancels):
    groups = [[(float(a), float(b)) for a, b in g] for g in (m.get("groups") or [])]
    return diarize._embed_local(job, str(m.get("wav")), str(m.get("emb") or diarize.DIAR_EMB_DEFAULT), groups)


def _op_complete(m, rid, job, out, cancels):
    """文字の LLM に聞く(LLM の後処理 = ed_llm)。messages = [{"role", "content": 文字}](40 件・1 件 8000 字まで)-> {"content": 答え}"""
    name, dev, eng = str(m.get("name")), str(m.get("device") or "vulkan"), _engine(m)
    if eng != tx_engines.LlamaText.id:
        raise _errors.ApiError("bad_engine", "文字の問い合わせは文字の LLM だけです", 400)
    msgs = m.get("messages")
    if not isinstance(msgs, list) or not 0 < len(msgs) <= 40 or not all(
            isinstance(x, dict) and x.get("role") in ("system", "user", "assistant") and isinstance(x.get("content"), str) and len(x["content"]) <= 8000 for x in msgs):
        raise _errors.ApiError("bad_request", "問い合わせの形が違います", 400)
    with worker_client._model_lock:
        model = worker_client._models.get((name, dev, eng))
    if model is None:   # 読み込んだあとに手放された → 同じ機器で読み直す
        model, dev = worker_client._load_model_local(name, job, dev, False, eng)
    model.hooks = {"cancelled": lambda: rid in cancels}
    content = model.complete([{"role": x["role"], "content": x["content"]} for x in msgs], max(1, min(2000, int(m.get("max_tokens") or 400))))
    worker_client._model_used[0] = time.time()
    return {"content": content}


OPS = {"load": _op_load, "transcribe": _op_transcribe, "diarize": _op_diarize, "embed": _op_embed,
       "complete": _op_complete}   # 要求の種類 → 本体(結果 v を返す。途中の知らせは本体が送る)


def handle(m, out, cancels):
    """要求 1 つを処理して、結果かエラーを送る(部品の名前は呼ぶたびにモジュールから読む = テストの差し替えが効く)"""
    rid, op = m.get("rid"), m.get("op")
    job = JobProxy(rid, out, cancels)
    try:
        fn = OPS.get(op) if isinstance(op, str) else None
        if fn is None:
            out.send({"rid": rid, "ev": "error", "code": "bad_op", "message": "不明な要求: %s" % op, "status": 500})
        else:
            out.send({"rid": rid, "ev": "result", "v": fn(m, rid, job, out, cancels)})
    except _heavy.Cancelled:
        out.send({"rid": rid, "ev": "error", "code": "cancelled", "message": "中止しました"})
    except (tx_engines.EngineError, _errors.ApiError) as e:
        out.send({"rid": rid, "ev": "error", "code": e.code, "message": e.message, "status": e.status})
    except MemoryError:
        out.send({"rid": rid, "ev": "error", "code": "no_memory", "status": 500,
                  "message": "メモリが足りませんでした。他のアプリ(動画編集ソフトなど)を閉じてから、もう一度試してください"})
    except Exception as e:
        logging.getLogger("tx").exception("ワーカーで例外 %s", op)
        out.send({"rid": rid, "ev": "error", "code": "exception", "type": e.__class__.__name__, "message": str(e)[:300]})
    finally:
        cancels.discard(rid)


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    fp = _protocol_stream()
    inp = _protocol_input()
    faulthandler.enable(file=sys.stderr, all_threads=True)   # ネイティブコードで落ちたときの場所を worker.log に残す
    logging.basicConfig(stream=sys.stderr, level=logging.INFO, format="%(asctime)s [worker %(process)d] %(message)s")
    _setup_env()   # 編集の serve は読まない(RS2-9)。置き場所などの口はここで
    worker_client.IN_WORKER = True
    worker_client.setup_cuda_paths()
    _install_fakes()
    out = Out(fp)
    if "--probe" in argv:
        try:
            ok = bool(worker_client._gpu_ready_local())
        except Exception:
            ok = False
        out.send({"cuda": ok})
        return 0
    logging.getLogger("tx").info("認識ワーカーを開始 pid=%d python=%s", os.getpid(), sys.version.split()[0])
    reqs, cancels = queue.Queue(), set()

    def reader():
        """標準入力を読む(処理中でも取り消しを受け取れるよう、別のスレッドで)。閉じたら終わる。"""
        for line in inp:
            try:
                m = json.loads(line.decode("utf-8"))
            except (UnicodeDecodeError, ValueError):
                continue
            if not isinstance(m, dict):
                continue
            if m.get("op") == "cancel":
                cancels.add(m.get("rid"))
            elif m.get("op") == "quit":
                break
            else:
                reqs.put(m)
        logging.getLogger("tx").info("認識ワーカーを終了")
        os._exit(0)   # 処理の途中でも終わる(サーバーがいなくなった・終了の指示)
    threading.Thread(target=reader, daemon=True, name="stdin").start()
    while True:
        handle(reqs.get(), out, cancels)


if __name__ == "__main__":
    sys.exit(main() or 0)
