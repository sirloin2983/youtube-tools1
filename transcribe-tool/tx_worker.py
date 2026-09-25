#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""文字起こしの認識ワーカー(統合計画の段階3-3)。serve.py が別プロセスとして起動する。人が直接起動するものではない。

    python tx_worker.py            要求を標準入力から読み、結果を標準出力へ書く(serve.py の WorkerClient が使う)
    python tx_worker.py --probe    GPU(CUDA)が使えるかを調べて {"cuda": true|false} を出して終わる

faster-whisper(ctranslate2)と sherpa-onnx はネイティブコードで、メモリ不足・GPU のドライバなどでプロセスごと落ちることがある。
その処理だけをこのプロセスで行い、落ちてもサーバー(入口に取り込んだときはスタジオ・cut2resolve も同じプロセス)は止まらないようにする。
中身の処理は serve.py の関数(_load_model_local・_diarize_local)をそのまま使う(2か所に同じ処理を書かない)。

やり取り(1行1件の JSON。ASCII):
  要求  {"rid": 1, "op": "load", "name": "large-v3", "pref": "auto", "force_cpu": false}
        {"rid": 2, "op": "transcribe", "name", "device", "audio": {"wav": パス} | {"f32": パス}, "kw": {...}}
        {"rid": 3, "op": "diarize", "wav": パス, "num": 0, "emb": "voxceleb"}
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
            words.append({"start": float(a), "end": float(b), "word": str(getattr(w, "word", ""))})
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
        if w.getnchannels() != 1 or w.getsampwidth() != 2 or w.getframerate() != 16000:
            raise ValueError("音声の形式が想定と違います")
        lo = max(0, min(lo, w.getnframes()))
        w.setpos(lo)
        raw = w.readframes(max(0, hi - lo))
    return np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0


def _accepted_params(model):
    try:
        import inspect
        return sorted(inspect.signature(model.transcribe).parameters)
    except (TypeError, ValueError):
        return []


# ---------------------------------------------------------------- テスト用の偽物(TRANSCRIBE_BACKEND=worker-fake)

def install_fakes(S):
    """faster-whisper・sherpa-onnx の代わり。本物の _load_model_local(モデルの使い回し・手放し)の流れはそのまま通す。
    TRANSCRIBE_WORKER_CRASH=<n> なら、認識の n 行目を送ったあとにプロセスごと落ちる(異常終了からの立ち直りの確認用)。"""
    import types
    delay = float(os.environ.get("TRANSCRIBE_FAKE_DELAY", "0.05"))
    crash_at = int(os.environ.get("TRANSCRIBE_WORKER_CRASH", "0") or 0)

    class Seg:
        def __init__(self, a, b, text, lp=-0.3):
            self.start, self.end, self.text = a, b, text
            self.avg_logprob, self.no_speech_prob, self.compression_ratio = lp, 0.1, 1.2
            self.words = [types.SimpleNamespace(start=a, end=(a + b) / 2, word=text[:len(text) // 2]),
                          types.SimpleNamespace(start=(a + b) / 2, end=b, word=text[len(text) // 2:])]

    class FakeWhisper:
        def __init__(self, name, device="cpu", compute_type="int8"):
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
            return gen(), types.SimpleNamespace(language=language or "ja", duration=total)

    fw = types.ModuleType("faster_whisper")
    fw.WhisperModel = FakeWhisper
    sys.modules["faster_whisper"] = fw
    S._gpu_ready_local = lambda: False

    def fake_diarize(job, wav, num, emb=None):
        with wave.open(wav, "rb") as w:
            total = w.getnframes() / float(w.getframerate())
        n, t, k, turns = (num or 2), 0.0, 0, []
        while t < total:
            if job["cancel"]:
                raise S.Cancelled()
            e = min(total, t + 10.0)
            turns.append((t, e, k % n))
            k += 1
            t = e
            job["progress"] = min(0.99, t / max(total, 1e-6))
            time.sleep(delay)
        return turns
    S._diarize_local = fake_diarize


# ---------------------------------------------------------------- 本体

def handle(S, m, out, cancels):
    rid, op = m.get("rid"), m.get("op")
    job = JobProxy(rid, out, cancels)
    try:
        if op == "load":
            model, dev = S._load_model_local(str(m.get("name")), job, str(m.get("pref") or "auto"), bool(m.get("force_cpu")))
            out.send({"rid": rid, "ev": "result", "v": {"device": dev, "params": _accepted_params(model)}})
        elif op == "transcribe":
            name, dev = str(m.get("name")), str(m.get("device") or "cpu")
            with S._model_lock:
                model = S._models.get((name, dev))
            if model is None:   # 読み込んだあとに手放された(通常は起きない)→ 同じ機器で読み直す
                model, dev = S._load_model_local(name, job, dev)
            audio = _audio(m.get("audio") or {})
            kw = m.get("kw") or {}
            segs, info = model.transcribe(audio, **kw)
            n = 0
            for s in segs:
                if rid in cancels:
                    break
                out.send({"rid": rid, "ev": "item", "v": _seg_dict(s)})
                n += 1
            S._model_used[0] = time.time()
            out.send({"rid": rid, "ev": "result", "v": {"count": n, "cancelled": rid in cancels,
                                                         "language": getattr(info, "language", None)}})
        elif op == "diarize":
            turns = S._diarize_local(job, str(m.get("wav")), int(m.get("num") or 0), str(m.get("emb") or S.DIAR_EMB_DEFAULT))
            out.send({"rid": rid, "ev": "result", "v": [[float(a), float(b), int(k)] for a, b, k in turns]})
        else:
            out.send({"rid": rid, "ev": "error", "code": "bad_op", "message": "不明な要求: %s" % op, "status": 500})
    except S.Cancelled:
        out.send({"rid": rid, "ev": "error", "code": "cancelled", "message": "中止しました"})
    except S.ApiError as e:
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
        for line in sys.stdin.buffer:
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
