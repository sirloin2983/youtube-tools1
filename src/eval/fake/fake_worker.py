# -*- coding: utf-8 -*-
"""認識ワーカーの中の疑似(環境変数 TRANSCRIBE_BACKEND=worker-fake のテスト用。役割で組み直す RS2-9 に、認識ワーカー(旧 src/editor/tx_worker.py)の
install_fakes から移した。中身は同じ)。

サーバー(編集の serve)は本物の経路(認識ワーカーとのやり取り・RemoteModel)を通り、ワーカーの中だけ偽のモデルを使う。差し込み方:
serve が pipeline/transcribe/worker_client.FAKES_MODULE にこのモジュールの名前を入れる → worker_client.worker_env() が worker-fake のときだけ
環境変数(worker_client.FAKES_ENV)でワーカーへ渡す → ワーカー(pipeline/transcribe/worker.py)の main が importlib で読んで install() を呼ぶ
(① は ④ を import しない = 名前の文字だけを受け取る)。
faster-whisper・sherpa-onnx・whisper.cpp・SenseVoice・文字の LLM の代わり。本物の _load_model_local(モデルの使い回し・手放し)の流れはそのまま通す。
TRANSCRIBE_WORKER_CRASH=<n> なら、認識の n 行目を送ったあとにプロセスごと落ちる(異常終了からの立ち直りの確認用)。
話者判別と声の特徴は、サーバーの疑似(fake_asr の diarize_fake・embed_fake)と同じ区切り(偽物どうしが食い違わないよう、本体を共有する)。
差し替えるのはモジュールの名前(worker_client._gpu_ready_local・diarize._diarize_local・_embed_local・tx_engines)= 読み手は呼ぶたびに読む。
"""
import os
import sys
import time
import types
import wave

from pipeline.transcribe import diarize, tx_engines, worker_client
from ytt import layout
from . import fake_asr


def install():
    """認識ワーカーの main が読み込みの直後に 1 回呼ぶ(サーバーのプロセスでは呼ばない)"""
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
    worker_client._gpu_ready_local = lambda: False

    def fake_diarize(job, wav, num, emb=None, threshold=None, min_on=None, min_off=None):
        """サーバーの疑似の判別(fake_asr.diarize_fake)と同じ区切りを、wav の長さで作る(偽物どうしが食い違わないよう、本体を共有する)"""
        with wave.open(wav, "rb") as w:
            total = w.getnframes() / float(w.getframerate())
        diarize.diar_tune(threshold, min_on, min_off)   # 本物と同じく、正しくない値は断る
        return fake_asr.diarize_fake(job, total, num, threshold)
    diarize._diarize_local = fake_diarize
    diarize._embed_local = lambda job, wav, emb, groups: fake_asr.embed_fake(groups)   # 声の特徴(A-3)も偽の話者判別と同じ区切りで
    # whisper.cpp(段2-2)は偽の whisper-cli(編集の tests/fake_whisper_cli.py。編集のフォルダは ytt.layout で探す)を動かす。モデルは取らない
    E = tx_engines
    E.WhisperCpp.COMMAND = [sys.executable, os.path.join(layout.tool_dir("transcribe"), "tests", "fake_whisper_cli.py")]
    E.fetch_file = lambda spec, folder, *a, **k: os.path.join(folder, spec["file"])
    E.SenseVoice.FAKE_TEXT = os.environ.get("TRANSCRIBE_FAKE_FILL", "")   # 2 つ目の読み(後処理 A)は環境変数の文字を 1 行に(空 = 行なし。モデルは取らない)
    E.LlamaText.FAKE_REPLY = os.environ.get("TRANSCRIBE_FAKE_LLM", "")   # 文字の LLM(後処理 E)は環境変数の文字をそのまま答える(server を起動しない)
