"""「編集」のサーバーの部品: 声を伴奏から分けて(Spleeter 2stems・sherpa-onnx・CPU)、分けた声の音量から声のある区間を作る(notes:plan/voice-separation-1022.md)。

使い手: 認識のあとの後処理(fill.fill_drop_silent = 分けた声と 1 割も重ならない行を捨てる。束 transcribe.dropSilent・既定オフ)。
声の区間 = SEP_FRAME 秒ごとの分けた声の音量が、その音声の上位 5% の音量 − SEP_DB より大きい所(SEP_GAP 秒以内のすき間はつなぎ、SEP_MIN 秒未満は捨てる)。
長い音を 1 回で渡すとメモリが大きい(10 分で約 10 GB)ので SEP_CHUNK 秒ずつ渡す(60 秒で約 1.2 GB)。16 kHz の音は sherpa-onnx が中で 44.1 kHz に直す。
口の形: voice_spans(job, wav) -> [(始め, 終わり)](wav の頭からの秒)。部品を足すとき(同時発話の研究の「人ごとに分ける」など)は SEP_MODELS に行を足し、
同じ形(音のパス → 声の区間)で返す。本物と疑似は backend の口 voice_spans(疑似 = eval/fake/fake_asr の TRANSCRIBE_FAKE_VOICED)。
numpy・sherpa_onnx は _voice_spans_local の中で読む(サーバーのプロセスでは読まない = tests/pipeline/transcribe/test_worker.py の検査)。
"""
import os

from ytt import jobs as _heavy, workdata as _workdata
from . import backend as _backend, tx_engines, worker_client

# 型は sherpa-onnx の公式の配布を URL・大きさ・SHA-256 固定で取る。SHA-256 は 10-22 に 2 回取った中身の値(測りに使った物と同じ。
# 同じリリースの checksum.txt の a04f196c… は 2025-05-23 の差し替え前の値で合わない・GitHub の API は digest を出さない)。UVR MDX-Net は遅く劣った(10-22 の測り)
SEP_MODELS = {
    "spleeter-2stems": {"dir": "sherpa-onnx-spleeter-2stems-int8", "file": "sherpa-onnx-spleeter-2stems-int8.tar.bz2",
                        "url": "https://github.com/k2-fsa/sherpa-onnx/releases/download/source-separation-models/sherpa-onnx-spleeter-2stems-int8.tar.bz2",
                        "size": 48623481, "sha256": "c5dc8edfa08cc9a6d82670fcca15cfe671e446385e1a28c9da8c1816d238ea17",
                        "parts": ("vocals.int8.onnx", "accompaniment.int8.onnx")},
}
SEP_MODEL = "spleeter-2stems"
SEP_DB = 40.0      # 上位 5% の音量からこの dB 下までを声とする(−30 は組 B の時刻が動いた・−20 は本当の声を捨てた)
SEP_FRAME = 0.03   # 音量を測る 1 コマの秒
SEP_GAP = 0.3      # これ以下のすき間はつなぐ
SEP_MIN = 0.2      # これ未満の区間は捨てる
SEP_CHUNK = 60     # 1 回に渡す秒


def sep_model_dir(data_dir):
    return os.path.join(data_dir, "models", "sep")


def spans_from_db(db, frame=SEP_FRAME, drop=SEP_DB, gap=SEP_GAP, min_len=SEP_MIN):
    """コマごとの音量(dB)の並び → 声の区間 [(始め, 終わり)](秒)。しきい値 = 上位 5% の値 − drop"""
    if not db:
        return []
    s = sorted(db)
    k = (len(s) - 1) * 0.95   # numpy.percentile(線形)と同じ
    lo = int(k)
    thr = s[lo] + (s[min(lo + 1, len(s) - 1)] - s[lo]) * (k - lo) - drop
    spans, a = [], None
    for i, v in enumerate(db):
        if v > thr and a is None:
            a = i * frame
        elif v <= thr and a is not None:
            spans.append([a, i * frame])
            a = None
    if a is not None:
        spans.append([a, len(db) * frame])
    merged = []
    for a, b in spans:
        if merged and a - merged[-1][1] <= gap:
            merged[-1][1] = b
        else:
            merged.append([a, b])
    return [(a, b) for a, b in merged if b - a >= min_len]


def voice_spans(job, wav):
    """wav(16 kHz・モノラル)の分けた声の区間 [(始め, 終わり)]。本物はワーカーで分ける(型が無ければ取る)"""
    return _backend.select().voice_spans(job, wav, _voice_spans_real)


def _voice_spans_real(job, wav):
    if worker_client.IN_WORKER:
        return _voice_spans_local(job, wav)
    res = worker_client.WORKER.call("voiced", {"wav": wav}, job)
    return [(float(a), float(b)) for a, b in res]


def _voice_spans_local(job, wav):
    """認識ワーカーの中だけで動く(numpy・sherpa-onnx)。SEP_CHUNK 秒ずつ分けて、分けた声の SEP_FRAME 秒ごとの音量から区間を作る"""
    tx_engines._need_sherpa("install-diarize.bat")   # 部品が無い PC では生の ImportError でなく入れ方の案内
    import numpy as np
    import sherpa_onnx as so
    from . import diarize
    spec = SEP_MODELS[SEP_MODEL]
    d = tx_engines._ensure_tar_model(spec, sep_model_dir(_workdata.DATA_DIR), None, {})
    sep = so.OfflineSourceSeparation(so.OfflineSourceSeparationConfig(model=so.OfflineSourceSeparationModelConfig(
        spleeter=so.OfflineSourceSeparationSpleeterModelConfig(vocals=os.path.join(d, spec["parts"][0]), accompaniment=os.path.join(d, spec["parts"][1])),
        num_threads=diarize.diar_threads())))
    x = tx_engines._read_16k(wav, "声の分離")
    step, db = 16000 * SEP_CHUNK, []
    for k in range(0, len(x), step):
        _heavy.check_cancel(job)
        c = x[k:k + step]
        r = sep.process(sample_rate=16000, samples=np.stack([c, c]))
        v = np.asarray(r.stems[0].data, dtype=np.float32).mean(axis=0)
        hop = int(round(r.sample_rate * SEP_FRAME))
        want = len(c) // int(16000 * SEP_FRAME)   # 元の長さのコマ数(出力は数十サンプル短いことがある = 足りない所は無音)
        v = np.pad(v, (0, max(0, want * hop - len(v))))[:want * hop]
        if want:
            db.extend((20 * np.log10(np.sqrt(np.mean(v.reshape(want, hop) ** 2, axis=1) + 1e-12))).tolist())
        job["progress"] = min(0.99, (k + step) / max(1, len(x)))
    return spans_from_db(db)
