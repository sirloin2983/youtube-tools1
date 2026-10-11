# -*- coding: utf-8 -*-
"""① 認識ワーカーの中で動く物: 読み込んだモデルの使い回し(_models)と読み込み(_load_model_local)・しばらく使わなければ手放す(release_idle_local)・
GPU(CUDA)の部品の場所と有無をこのプロセスで調べる関数(setup_cuda_paths・cuda_count・cuda_libs_ok・_gpu_ready_local)・GPU で使う精度の型(cuda_compute)。

役割で組み直す OPT(2026-10-11)に worker_client から移した(中身は同じ。worker_client にはサーバー側の物 = WorkerClient・RemoteModel・GPU の有無の別プロセス調べだけを残した)。
**このモジュールのモデルの読み込み・CUDA の調べはワーカーのプロセス(と IN_WORKER の測る道具)だけが呼ぶ**。サーバーのプロセスが読んでも、numpy・faster_whisper・
ctranslate2・sherpa_onnx は呼ばれた関数の中(cuda_count の ctranslate2)でしか読まない(src/editor/tests/test_worker.py が検査)。
ワーカーの本体(worker.py)・測る道具(eval/tools/_evalcommon)・疑似のワーカー(eval/fake/fake_worker が _gpu_ready_local を差し替える)が、名前を呼ぶたびに読む。
標準ライブラリ・ytt・同じパッケージの tx_engines だけを読む(worker_client は読まない = 向きは worker_client → models)。
"""
import gc
import os
import threading
import time

from ytt import errors as _errors, jobs as _heavy, tools as _tools
from ytt import txbase as _txbase
from . import tx_engines


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


def release_idle_local(now):
    """読み込んだモデルのうち、MODEL_IDLE_SEC 秒使っていないものを手放す(認識ワーカーの中。サーバー側の呼び分けは worker_client.release_idle_models)。
    手放したら True"""
    with _model_lock:
        if not _models or now - _model_used[0] < MODEL_IDLE_SEC:
            return False
        _txbase.log.info("しばらく使っていないモデルを解放: %s(メモリ %s)", ", ".join("/".join(k) for k in _models), _tools.memory_label())
        _models.clear()
    gc.collect()
    return True


def _load_model_local(name, job, pref="auto", force_cpu=False, engine=tx_engines.DEFAULT):
    """(モデル, 使用デバイス) を返す(認識ワーカーの中で動く本体)。同じエンジン・モデル・機器のものは使い回す。モデルは tx_engines のエンジン。
    pref: auto=GPU があれば GPU(失敗したら CPU) / cuda=GPU 固定(失敗したらエラー) / cpu=CPU 固定"""
    try:
        eng = tx_engines.get(engine)
    except ValueError as e:
        raise _errors.ApiError("bad_engine", str(e), 400)
    # 機器は要求の本文(pref)が先(② がこの PC の設定 flow/machine.py から入れて渡す。RS7-1 S1)。環境変数 TRANSCRIBE_DEVICE は本文が auto のときだけ
    # (② を通らない呼び出し = 再認識・LLM などの互換。machine の環境変数の層でも同じ名前を device として読む)
    env = os.environ.get("TRANSCRIBE_DEVICE")
    if force_cpu:
        pref = "cpu"
    elif pref in (None, "", "auto") and env in ("cuda", "cpu"):
        pref = env
    # 試す機器の順はエンジンが決める(faster-whisper = CUDA → CPU、whisper.cpp = Vulkan だけ・CPU は明示のときだけ)。CUDA の有無を調べるのは faster-whisper のときだけ
    order = eng.device_order(pref, eng is tx_engines.FasterWhisper and pref == "auto" and _gpu_ready_local())
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
            if heavy and not eng.light:   # 別の(重い)モデルは手放す(別の重いモデルを交互に使ってもメモリが積み上がらない。落ちる原因の1つ)
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


# ---------- GPU(CUDA)の部品の場所と有無(このプロセスで調べる = 認識ワーカーの中と測る道具。RS2-9 に編集の ed_state から移した) ----------
# サーバーのプロセスは ctranslate2 を読まない: 画面に出す GPU の有無は下の gpu_ready が別プロセス(worker.py --probe)で 1 回だけ調べる
def setup_cuda_paths():
    """pip の nvidia-cublas-cu12 / nvidia-cudnn-cu12 が入れた DLL / .so を、ctranslate2 が見つけられるようにする。"""
    try:
        import importlib.util
        spec = importlib.util.find_spec("nvidia")
        roots = list(spec.submodule_search_locations or []) if spec else []
    except Exception:
        roots = []
    for root in roots:
        try:
            names = os.listdir(root)
        except OSError:
            continue
        for n in names:
            for sub in ("bin", "lib"):
                d = os.path.join(root, n, sub)
                if os.path.isdir(d):
                    if hasattr(os, "add_dll_directory"):
                        try:
                            os.add_dll_directory(d)
                        except OSError:
                            pass
                    os.environ["PATH"] = d + os.pathsep + os.environ.get("PATH", "")


def cuda_count():
    try:
        import ctranslate2
        return int(ctranslate2.get_cuda_device_count())
    except Exception:
        return 0


def cuda_libs_ok():
    """GPU 処理に必要な cuBLAS(CUDA 12) と cuDNN(9) が読み込めるか。ドライバだけでは GPU 処理はできない。"""
    import ctypes
    names = (("cublas64_12.dll", "cudnn64_9.dll") if os.name == "nt" else ("libcublas.so.12", "libcudnn.so.9"))
    try:
        for n in names:
            ctypes.CDLL(n)
        return True
    except OSError:
        return False


def _gpu_ready_local():
    """このプロセスで GPU(CUDA)が使えるか。ctranslate2 を読み込むので、認識ワーカーの中(と IN_WORKER の測る道具)でだけ呼ぶ。
    ワーカーの疑似(eval/fake/fake_worker)はこの名前を差し替える(ワーカーの中の gpu_ready は IN_WORKER なので呼ぶたびにこの名前を読む)"""
    return cuda_count() > 0 and cuda_libs_ok()



CUDA_COMPUTE_TYPES = ("float16", "int8_float16", "int8", "float32")


def cuda_compute():
    """GPU で使う精度の型。環境変数 TRANSCRIBE_CUDA_COMPUTE(例: int8_float16 = 8GB の GPU に収める)。無い・違えば float16(今まで)"""
    v = os.environ.get("TRANSCRIBE_CUDA_COMPUTE", "").strip()
    return v if v in CUDA_COMPUTE_TYPES else "float16"
