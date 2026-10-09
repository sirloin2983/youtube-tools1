#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""文字起こしの認識ワーカー(統合計画の段階3-3)。serve.py が別プロセスとして起動する。人が直接起動するものではない。

    python tx_worker.py            要求を標準入力から読み、結果を標準出力へ書く(serve.py の WorkerClient が使う)
    python tx_worker.py --probe    GPU(CUDA)が使えるかを調べて {"cuda": true|false} を出して終わる

faster-whisper(ctranslate2)と sherpa-onnx はネイティブコードで、メモリ不足・GPU のドライバなどでプロセスごと落ちることがある。
その処理だけをこのプロセスで行い、落ちてもサーバー(入口に取り込んだときはスタジオ・cut2resolve も同じプロセス)は止まらないようにする。
中身の処理は serve.py の関数(_load_model_local・_diarize_local)をそのまま使う(2か所に同じ処理を書かない)。

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
import json
import logging
import os
import queue
import sys
import threading
import time
import wave

HERE = os.path.dirname(os.path.abspath(__file__))
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
    """serve.py の関数に渡す job の代わり。phase・state・device・progress を書くと、サーバーへ途中経過として送る。
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
    import tx_engines
    lo, hi = int(a["from"]), int(a["to"])
    with wave.open(path, "rb") as w:
        if not tx_engines.is_16k_mono(w):
            raise ValueError("音声の形式が想定と違います")
        lo = max(0, min(lo, w.getnframes()))
        w.setpos(lo)
        raw = w.readframes(max(0, hi - lo))
    return np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0


# ---------------------------------------------------------------- テスト用の偽物(TRANSCRIBE_BACKEND=worker-fake)

def install_fakes(S):
    """faster-whisper・sherpa-onnx の代わり。本物の _load_model_local(モデルの使い回し・手放し)の流れはそのまま通す。
    TRANSCRIBE_WORKER_CRASH=<n> なら、認識の n 行目を送ったあとにプロセスごと落ちる(異常終了からの立ち直りの確認用)。"""
    import types
    delay = float(os.environ.get("TRANSCRIBE_FAKE_DELAY", "0.05"))
    crash_at = int(os.environ.get("TRANSCRIBE_WORKER_CRASH", "0") or 0)
    vad_mode_drop = os.environ.get("TRANSCRIBE_FAKE_VAD", "")

    class Seg:
        def __init__(self, a, b, text, lp=-0.3):
            self.start, self.end, self.text = a, b, text
            self.avg_logprob, self.no_speech_prob, self.compression_ratio = lp, 0.1, 1.2
            self.words = [types.SimpleNamespace(start=a, end=(a + b) / 2, word=text[:len(text) // 2]),
                          types.SimpleNamespace(start=(a + b) / 2, end=b, word=text[len(text) // 2:])]

    class FakeWhisper:
        def __init__(self, name, device="cpu", compute_type="int8", local_files_only=False, cpu_threads=0):
            self.name = name
            print("偽のモデルを読み込み: %s" % name)        # ライブラリの print・ネイティブの出力が、やり取りに混ざらないことの確認用
            os.write(1, b"native-like output on fd 1\n")

        def transcribe(self, audio, language=None, beam_size=5, vad_filter=True, vad_parameters=None, word_timestamps=False,
                       condition_on_previous_text=False, no_speech_threshold=0.6, initial_prompt=None, hotwords=None, chunk_length=None):
            if isinstance(audio, str):
                with wave.open(audio, "rb") as w:
                    total = w.getnframes() / float(w.getframerate())
            else:
                total = len(audio) / 16000.0
            # TRANSCRIBE_FAKE_VAD: drop-normal = 声の検出「標準」のとき全部を捨てる / drop-vad = 声の検出をかけると全部を捨てる(「なし」だけ文字が出る)
            weak = bool(vad_parameters) and vad_parameters.get("threshold") == 0.3
            drop = vad_filter and ((vad_mode_drop == "drop-normal" and not weak) or vad_mode_drop == "drop-vad")
            info = types.SimpleNamespace(language=language or "ja", duration=total, duration_after_vad=0.0 if drop else total)
            if drop:
                return iter(()), info

            def gen():
                t, i = 0.0, 0
                while t < total - 0.05:
                    e = min(total, t + 4.0)
                    i += 1
                    yield Seg(t, e, "テスト文%d" % i, -1.4 if i % 5 == 0 else -0.3)
                    if crash_at and i >= crash_at:
                        os._exit(70)
                    time.sleep(delay)
                    t = e
            return gen(), info

    fw = types.ModuleType("faster_whisper")
    fw.WhisperModel = FakeWhisper
    sys.modules["faster_whisper"] = fw
    S._gpu_ready_local = lambda: False

    def fake_diarize(job, wav, num, emb=None, threshold=None, min_on=None, min_off=None):
        """サーバーの疑似の判別(ed_speakers.diarize_fake)と同じ区切りを、wav の長さで作る(偽物どうしが食い違わないよう、本体を共有する)"""
        with wave.open(wav, "rb") as w:
            total = w.getnframes() / float(w.getframerate())
        S.diar_tune(threshold, min_on, min_off)   # 本物と同じく、正しくない値は断る
        return S.diarize_fake(job, total, num, threshold)
    S._diarize_local = fake_diarize
    S._embed_local = lambda job, wav, emb, groups: S.embed_fake(groups)   # 声の特徴(A-3)も偽の話者判別と同じ区切りで
    # whisper.cpp(段2-2)は偽の whisper-cli(tests/fake_whisper_cli.py)を動かす。モデルは取らない
    E = S.tx_engines
    E.WhisperCpp.COMMAND = [sys.executable, os.path.join(HERE, "tests", "fake_whisper_cli.py")]
    E.fetch_file = lambda spec, folder, *a, **k: os.path.join(folder, spec["file"])
    E.SenseVoice.FAKE_TEXT = os.environ.get("TRANSCRIBE_FAKE_FILL", "")   # 2 つ目の読み(ed_fill)は環境変数の文字を 1 行に(空 = 行なし。モデルは取らない)
    E.LlamaText.FAKE_REPLY = os.environ.get("TRANSCRIBE_FAKE_LLM", "")   # 文字の LLM(ed_llm)は環境変数の文字をそのまま答える(server を起動しない)


# ---------------------------------------------------------------- 本体

def _engine(S, m):
    """要求の認識エンジンの名前(一覧に無ければ ApiError。要求の文字列からクラスを探さない)"""
    e = str(m.get("engine") or S.tx_engines.DEFAULT)
    if not S.tx_engines.valid(e):
        raise S.ApiError("bad_engine", "知らない認識エンジンです: %s" % e[:40], 400)
    return e


def _op_load(S, m, rid, job, out, cancels):
    model, dev = S._load_model_local(str(m.get("name")), job, str(m.get("pref") or "auto"), bool(m.get("force_cpu")), _engine(S, m))
    return {"device": dev, "params": list(model.params())}   # エンジンが受け付ける引数の名前(サーバーはこれに無い引数を渡さない)


def _op_transcribe(S, m, rid, job, out, cancels):
    name, dev, eng = str(m.get("name")), str(m.get("device") or "cpu"), _engine(S, m)
    with S._model_lock:
        model = S._models.get((name, dev, eng))
    if model is None:   # 読み込んだあとに手放された(通常は起きない)→ 同じ機器で読み直す
        model, dev = S._load_model_local(name, job, dev, False, eng)
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
    S._model_used[0] = time.time()
    return {"count": n, "cancelled": rid in cancels, "language": getattr(info, "language", None)}


def _op_diarize(S, m, rid, job, out, cancels):
    # 判別の設定(threshold・minOn・minOff)は任意。無い要求は以前と同じ呼び方(既定の値)
    tune = {k: m[w] for k, w in S.DIAR_TUNE if m.get(w) is not None}
    turns = S._diarize_local(job, str(m.get("wav")), int(m.get("num") or 0), str(m.get("emb") or S.DIAR_EMB_DEFAULT), **tune)
    return [[float(a), float(b), int(k)] for a, b, k in turns]


def _op_embed(S, m, rid, job, out, cancels):
    groups = [[(float(a), float(b)) for a, b in g] for g in (m.get("groups") or [])]
    return S._embed_local(job, str(m.get("wav")), str(m.get("emb") or S.DIAR_EMB_DEFAULT), groups)


def _op_complete(S, m, rid, job, out, cancels):
    """文字の LLM に聞く(LLM の後処理 = ed_llm)。messages = [{"role", "content": 文字}](40 件・1 件 8000 字まで)-> {"content": 答え}"""
    name, dev, eng = str(m.get("name")), str(m.get("device") or "vulkan"), _engine(S, m)
    if eng != S.tx_engines.LlamaText.id:
        raise S.ApiError("bad_engine", "文字の問い合わせは文字の LLM だけです", 400)
    msgs = m.get("messages")
    if not isinstance(msgs, list) or not 0 < len(msgs) <= 40 or not all(
            isinstance(x, dict) and x.get("role") in ("system", "user", "assistant") and isinstance(x.get("content"), str) and len(x["content"]) <= 8000 for x in msgs):
        raise S.ApiError("bad_request", "問い合わせの形が違います", 400)
    with S._model_lock:
        model = S._models.get((name, dev, eng))
    if model is None:   # 読み込んだあとに手放された → 同じ機器で読み直す
        model, dev = S._load_model_local(name, job, dev, False, eng)
    model.hooks = {"cancelled": lambda: rid in cancels}
    content = model.complete([{"role": x["role"], "content": x["content"]} for x in msgs], max(1, min(2000, int(m.get("max_tokens") or 400))))
    S._model_used[0] = time.time()
    return {"content": content}


OPS = {"load": _op_load, "transcribe": _op_transcribe, "diarize": _op_diarize, "embed": _op_embed,
       "complete": _op_complete}   # 要求の種類 → 本体(結果 v を返す。途中の知らせは本体が送る)


def handle(S, m, out, cancels):
    rid, op = m.get("rid"), m.get("op")
    job = JobProxy(rid, out, cancels)
    try:
        fn = OPS.get(op) if isinstance(op, str) else None
        if fn is None:
            out.send({"rid": rid, "ev": "error", "code": "bad_op", "message": "不明な要求: %s" % op, "status": 500})
        else:
            out.send({"rid": rid, "ev": "result", "v": fn(S, m, rid, job, out, cancels)})
    except S.Cancelled:
        out.send({"rid": rid, "ev": "error", "code": "cancelled", "message": "中止しました"})
    except (S.tx_engines.EngineError, S.ApiError) as e:
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
    sys.path.insert(0, HERE)
    import serve as S   # 読み込むだけ(サーバーは起動しない)
    S.IN_WORKER = True
    S.setup_cuda_paths()
    if S.worker_fake():
        install_fakes(S)
    out = Out(fp)
    if "--probe" in argv:
        try:
            ok = bool(S._gpu_ready_local())
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
        handle(S, reqs.get(), out, cancels)


if __name__ == "__main__":
    sys.exit(main() or 0)
