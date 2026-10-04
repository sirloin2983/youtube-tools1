# -*- coding: utf-8 -*-
"""「編集」のサーバーの部品: 話者の自動判別(sherpa-onnx)・話者の声を覚える(段10 で editor/serve.py から分けた。docs/plan/phase10-code-split.md)。

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
import ed_drill  # noqa: E402,F401   (評価用の文書の名前の候補 drill_candidates。呼ぶときに読む)
import ed_jobs  # noqa: E402,F401
import ed_learn  # noqa: E402,F401
import ed_state  # noqa: E402,F401
import ed_store  # noqa: E402,F401
# ---------- 話者の自動判別(sherpa-onnx) ----------
# 流れ: 音声を取り出す → 「誰がいつ話したか」の区間を求める(diarization) → 文字起こしの各行に、重なりが最も長い人を割り当てる。
# 文字起こしモデルとは独立に動くので、どのモデルで作った文字起こしにも使える。CPU で動く(PyTorch 不要)。
DIAR_DIR = os.path.join(ed_state.DATA_DIR, "models", "diar")
DIAR_SEG = {"file": "segmentation.onnx", "member": "sherpa-onnx-pyannote-segmentation-3-0/model.onnx", "label": "話者の切り替わり検出",
            "url": "https://github.com/k2-fsa/sherpa-onnx/releases/download/speaker-segmentation-models/sherpa-onnx-pyannote-segmentation-3-0.tar.bz2",
            "sha256": "24615ee884c897d9d2ba09bb4d30da6bb1b15e685065962db5b02e76e4996488", "max": 40 * 1024 * 1024}
_GH = "https://github.com/k2-fsa/sherpa-onnx/releases/download/speaker-recongition-models/"
# 声の特徴を取り出すモデル(どれが日本語の音声に合うかは、実際の音声で比べないと分からないので、選べるようにしてある)
DIAR_EMBS = {
    "voxceleb": {"file": "embedding-voxceleb.onnx", "member": None, "label": "VoxCeleb ResNet34(多言語の声で学習・おすすめ)", "mb": 27, "max": 80 * 1024 * 1024,
                 "url": _GH + "wespeaker_en_voxceleb_resnet34_LM.onnx", "sha256": "e9848563da86f263117134dfd7ad63c92355b37de492b55e325400c9d9c39012"},
    "campplus": {"file": "embedding-campplus.onnx", "member": None, "label": "3D-Speaker CAM++(中国語+英語)", "mb": 28, "max": 80 * 1024 * 1024,
                 "url": _GH + "3dspeaker_speech_campplus_sv_zh_en_16k-common_advanced.onnx", "sha256": "aa3cfc16963a10586a9393f5035d6d6b57e98d358b347f80c2a30bf4f00ceba2"},
    "standard": {"file": "embedding.onnx", "member": None, "label": "3D-Speaker ERes2Net(中国語。v0.3 の標準)", "mb": 40, "max": 120 * 1024 * 1024,
                 "url": _GH + "3dspeaker_speech_eres2net_base_sv_zh-cn_3dspeaker_16k.onnx", "sha256": "1a331345f04805badbb495c775a6ddffcdd1a732567d5ec8b3d5749e3c7a5e4b"},
}
DIAR_EMB_DEFAULT = "voxceleb"
MAX_DIAR_SEC = 3 * 3600
DIAR_CLUSTER_THRESHOLD, DIAR_MIN_ON, DIAR_MIN_OFF = 0.5, 0.1, 0.3   # sherpa-onnx の設定(_diarize_local と、判別の記録 <id>.diar.json の engine に同じ値を使う)
MAX_SPEAKERS = 20
SPK_COLORS = ["#2f62d6", "#d9534f", "#2e9e5b", "#c98a12", "#8a4fd6", "#0f9aa8", "#d6479a", "#6b7280"]


def diar_threads():
    """話者判別(sherpa-onnx)のスレッド数。既定は min(8, CPU)(2026-10-04 に 4 から上げた。P コアの数。環境変数 TRANSCRIBE_DIAR_THREADS で変えられる。
    docs/plan/stability-review-2026-10.md の S2)"""
    try:
        n = int(str(os.environ.get("TRANSCRIBE_DIAR_THREADS") or 0).strip())
    except ValueError:
        n = 0
    return max(1, min(64, n)) if n > 0 else max(1, min(8, os.cpu_count() or 2))


def has_sherpa():
    if ed_state.worker_fake():
        return True
    return ed_state.worker_has("sherpa_onnx", "numpy")


def _diar_path(item):
    return os.path.join(DIAR_DIR, item["file"])


def _have(item):
    return os.path.isfile(_diar_path(item)) and os.path.getsize(_diar_path(item)) > 1000


def diar_info():
    return {"ready": ed_state.backend_name() == "fake" or has_sherpa(), "segReady": _have(DIAR_SEG), "default": DIAR_EMB_DEFAULT,
            "embeddings": [{"key": k, "label": v["label"], "mb": v["mb"], "ready": _have(v)} for k, v in DIAR_EMBS.items()]}


def _download_verified(job, item, tmp):
    """固定の URL からダウンロードし、SHA-256 が想定と一致したものだけを受け入れる(改ざん・別ファイルの混入を防ぐ)。"""
    req = urllib.request.Request(item["url"], headers={"User-Agent": "transcribe-tool"})
    h, done = hashlib.sha256(), 0
    with urllib.request.urlopen(req, timeout=30) as r, open(tmp, "wb") as f:
        total = int(r.headers.get("Content-Length") or 0)
        while True:
            if job["cancel"]:
                raise ed_jobs.Cancelled()
            chunk = r.read(256 * 1024)
            if not chunk:
                break
            done += len(chunk)
            if done > item["max"]:
                raise ed_state.ApiError("model_download", "モデルのサイズが想定より大きいため中止しました", 500)
            h.update(chunk)
            f.write(chunk)
            if total:
                job["phase"] = "話者判別のモデルをダウンロード中(%s %d%%)" % (item["label"], min(100, done * 100 // total))
    if h.hexdigest() != item["sha256"]:
        raise ed_state.ApiError("model_hash", "ダウンロードしたモデルが想定と一致しません(配布元で差し替えられた可能性があります)。ツールの更新を確認してください", 500)


def ensure_diar_models(job, emb=DIAR_EMB_DEFAULT):
    if ed_state.worker_fake():   # テスト用(ワーカーの中の偽の判別を使う。モデルはダウンロードしない)
        return
    os.makedirs(DIAR_DIR, exist_ok=True)
    for item in (DIAR_SEG, DIAR_EMBS[emb]):
        dest = _diar_path(item)
        if os.path.isfile(dest) and os.path.getsize(dest) > 1000:
            continue
        tmp, part = dest + ".download", dest + ".part"
        try:
            _download_verified(job, item, tmp)
            if item["member"]:  # tar.bz2 から model.onnx だけを取り出す(展開先のパスは tar の中身に依存させない)
                with tarfile.open(tmp, "r:bz2") as tf:
                    m = tf.getmember(item["member"])
                    if not m.isfile() or m.size > item["max"]:
                        raise ed_state.ApiError("model_download", "モデルの形式が想定と違います", 500)
                    with tf.extractfile(m) as src, open(part, "wb") as out:
                        shutil.copyfileobj(src, out)
                os.replace(part, dest)
            else:
                os.replace(tmp, dest)
        except (urllib.error.URLError, OSError, tarfile.TarError, KeyError) as e:
            raise ed_state.ApiError("model_download", "話者判別のモデルをダウンロードできませんでした(初回はインターネット接続が必要です): %s" % str(e)[:150], 500)
        finally:
            for x in (tmp, part):
                try:
                    if os.path.exists(x):
                        os.unlink(x)
                except OSError:
                    pass


class WavRef:
    """16kHz・モノラル・16bit の wav を「読まずに」表す(サーバーのプロセス用)。audio[a:b] は WavSlice になり、
    認識ワーカーに渡すと、ワーカーがその範囲だけを読む。サーバーのプロセスに numpy(と音声全体のメモリ)を持ち込まないため。"""

    def __init__(self, path):
        with wave.open(path, "rb") as w:
            if w.getnchannels() != 1 or w.getsampwidth() != 2 or w.getframerate() != 16000:
                raise ed_state.ApiError("diar_failed", "音声の形式が想定と違います", 500)
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
    if not ed_jobs.IN_WORKER:
        return WavRef(path)
    import numpy as np
    with wave.open(path, "rb") as w:
        if w.getnchannels() != 1 or w.getsampwidth() != 2 or w.getframerate() != 16000:
            raise ed_state.ApiError("diar_failed", "音声の形式が想定と違います", 500)
        raw = w.readframes(w.getnframes())
    return np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0


DIAR_TUNE = (("threshold", "threshold"), ("min_on", "minOn"), ("min_off", "minOff"))   # 判別の設定を変えて測るときの任意の引数(引数の名前, ワーカーの要求の鍵)


def diar_tune(threshold=None, min_on=None, min_off=None):
    """判別の設定の任意の引数を確かめる -> {引数の名前: 値}(渡したものだけ。どれも 0 以上 10 未満の数)。dev/eval_speakers.py の run が使う"""
    out = {}
    for (k, _w), v in zip(DIAR_TUNE, (threshold, min_on, min_off)):
        if v is None:
            continue
        try:
            x = float(v)
        except (TypeError, ValueError):
            x = -1.0
        if not 0.0 <= x < 10.0:   # NaN もここで断る
            raise ed_state.ApiError("bad_request", "話者判別の設定(%s)が正しくありません" % k, 400)
        out[k] = x
    return out


def diarize_real(job, wav, num, emb=DIAR_EMB_DEFAULT, threshold=None, min_on=None, min_off=None):
    """話者の判別。sherpa-onnx(ネイティブコード)は認識ワーカー(別プロセス)の中で動かす。戻り値は [(開始, 終了, 話者番号)]。
    threshold・min_on・min_off は判別の設定を変えて測るとき(dev/eval_speakers.py の run)だけ。渡さなければ既定の値で、ワーカーへの要求も以前と同じ形"""
    tune = diar_tune(threshold, min_on, min_off)
    if ed_jobs.IN_WORKER:
        return _diarize_local(job, wav, num, emb, **tune)
    args = {"wav": wav, "num": int(num), "emb": emb}
    args.update({w: tune[k] for k, w in DIAR_TUNE if k in tune})
    turns = ed_jobs.WORKER.call("diarize", args, job)
    return [(float(a), float(b), int(k)) for a, b, k in turns]


def _diarize_local(job, wav, num, emb=DIAR_EMB_DEFAULT, threshold=None, min_on=None, min_off=None):
    import sherpa_onnx as so
    threads = diar_threads()
    tune = diar_tune(threshold, min_on, min_off)
    cfg = so.OfflineSpeakerDiarizationConfig(
        segmentation=so.OfflineSpeakerSegmentationModelConfig(
            pyannote=so.OfflineSpeakerSegmentationPyannoteModelConfig(model=_diar_path(DIAR_SEG)), num_threads=threads),
        embedding=so.SpeakerEmbeddingExtractorConfig(model=_diar_path(DIAR_EMBS[emb]), num_threads=threads),
        clustering=so.FastClusteringConfig(num_clusters=num if num > 0 else -1, threshold=tune.get("threshold", DIAR_CLUSTER_THRESHOLD)),
        min_duration_on=tune.get("min_on", DIAR_MIN_ON), min_duration_off=tune.get("min_off", DIAR_MIN_OFF))   # 短い相づちを落としにくくする
    if not cfg.validate():
        raise ed_state.ApiError("diar_failed", "話者判別の設定を読み込めませんでした(モデルファイルが壊れている可能性があります。models フォルダを削除して、もう一度試してください)", 500)
    sd = so.OfflineSpeakerDiarization(cfg)
    if sd.sample_rate != 16000:
        raise ed_state.ApiError("diar_failed", "話者判別のモデルの形式が想定と違います", 500)
    samples = read_wav_f32(wav)

    def cb(done, total, *_):
        if total:
            job["progress"] = min(0.99, done / total)
        return 1 if job["cancel"] else 0   # 0 以外を返すと中断する

    res = sd.process(samples, callback=cb).sort_by_start_time()
    if job["cancel"]:
        raise ed_jobs.Cancelled()
    return [(float(r.start), float(r.end), int(r.speaker)) for r in res]


def diarize_fake(job, total, num, threshold=None):
    """テスト用: 10秒ごとに話者が入れ替わる(行の途中で切り替わる場面も作る)。
    threshold(判別の設定を変えて測るとき)が 1.0 以上で人数が自動なら、全部を 1 人にまとめる(本物も、しきい値を上げるとまとまる)。渡さなければ以前と同じ"""
    n, t, k, turns = (num or (1 if threshold is not None and threshold >= 1.0 else 2)), 0.0, 0, []
    while t < total:
        if job["cancel"]:
            raise ed_jobs.Cancelled()
        e = min(total, t + 10.0)
        turns.append((t, e, k % n))
        job["progress"] = min(0.99, e / total)
        time.sleep(float(os.environ.get("TRANSCRIBE_FAKE_DELAY", "0.05")))
        t, k = e, k + 1
    return turns


def assign_speakers(segs, turns, offset):
    """各行に、重なりがいちばん長い話者を割り当てる。戻り値: [(話者番号 or None, 声が混ざっているか, 話者が不確か)]。
    不確か = 短い行(0.8秒未満。声の特徴が取りにくい)、行の半分以上が話者区間の外、または最寄りの区間で代用した行。
    turns は [(開始, 終了, 話者番号)](音声先頭からの秒)、offset を足すと元動画の時刻になる。"""
    ts = sorted((a + offset, b + offset, s) for a, b, s in turns)
    starts = [t[0] for t in ts]
    dmax = max((t[1] - t[0] for t in ts), default=0.0)
    out = []
    for sg in segs:
        a, b = sg["start"], sg["end"]
        dur = max(1e-6, b - a)
        lo, hi = bisect.bisect_left(starts, a - dmax), bisect.bisect_right(starts, b)
        ov = {}
        for x, y, s in ts[lo:hi]:
            d = min(b, y) - max(a, x)
            if d > 0:
                ov[s] = ov.get(s, 0.0) + d
        if ov:
            ranked = sorted(ov.items(), key=lambda kv: -kv[1])
            second = ranked[1][1] if len(ranked) > 1 else 0.0
            out.append((ranked[0][0], second >= max(1.0, 0.3 * dur), dur < 0.8 or ranked[0][1] / dur < 0.5))
            continue
        near, best = None, 1.5   # 重なりがなければ、前後1.5秒以内でいちばん近い区間
        for x, y, s in ts[lo:hi + 20]:
            gap = max(x - b, a - y, 0.0)
            if gap < best:
                near, best = s, gap
        out.append((near, False, True))
    return out


# ---------- 判別の記録(transcripts/<id>.diar.json。Q2。docs/plan/master-plan-2026-10.md) ----------
# 機械の最初の結果を残す(行の speaker・名前は人が直すので、あとから「機械はこう割り当てた」を比べられるように)。判別・声の照合のたびに書き、
# し直したら前の回は同じファイルの history に残す(最新を含めて DIAR_KEEP 回まで。付き物を1つのファイルにして、削除・付け替えの扱いを1か所で済ませるため)。
# 埋め込みのベクトルそのものは書かない(大きい・個人を見分けられる情報)。書けなくても判別は失敗にしない(_record_diar)
DIAR_SCHEMA = "youtube-tools-diar/v1"
DIAR_KEEP = 5
MAX_DIAR_BYTES = 32 * 1024 * 1024
MAX_DIAR_OVERLAPS = 5000
_diar_lock = threading.Lock()


def diar_path(tid):
    return os.path.join(ed_state.TX_DIR, tid + ".diar.json")


def read_diar(tid):
    """{"schema", "latest": {…}, "history": [前の回(新しい順)]}。無い・壊れていれば None"""
    try:
        d = _fsio.read_json_file(diar_path(tid), MAX_DIAR_BYTES)
    except (OSError, UnicodeError, ValueError):
        return None
    if not isinstance(d, dict) or d.get("schema") != DIAR_SCHEMA or not isinstance(d.get("latest"), dict):
        return None
    return d


def write_diar(tid, run):
    """run を最新として書く。前の最新は history の先頭へ(DIAR_KEEP 回まで)"""
    with _diar_lock:
        old = read_diar(tid)
        hist = ([old["latest"]] + [h for h in old.get("history") or [] if isinstance(h, dict)]) if old else []
        body = {"schema": DIAR_SCHEMA, "latest": run, "history": hist[:DIAR_KEEP - 1]}
        ed_state.atomic_write(diar_path(tid), json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))


def update_diar_voices(tid, voices):
    """最新の回の「覚えた声との照合」を書く(話者のラベルは labelMap から付ける)。判別の記録が無ければ何もしない"""
    with _diar_lock:
        d = read_diar(tid)
        if not d:
            return False
        latest = d["latest"]
        inv = {v: (int(k) if str(k).isdigit() else k) for k, v in (latest.get("labelMap") or {}).items()}
        for sid, one in (voices.get("speakers") or {}).items():
            one["label"] = inv.get(sid)
        latest["voices"] = voices
        ed_state.atomic_write(diar_path(tid), json.dumps(d, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
        return True


def _diar_engine(emb, requested):
    if ed_state.backend_name() == "fake":
        return {"name": "fake", "requested": requested or "auto"}
    return {"name": "sherpa-onnx", "segmentation": "pyannote-segmentation-3-0", "embedding": emb, "embeddingFile": DIAR_EMBS[emb]["file"],
            "requested": requested or "auto", "clusterThreshold": DIAR_CLUSTER_THRESHOLD, "minDurationOn": DIAR_MIN_ON, "minDurationOff": DIAR_MIN_OFF,
            "threads": diar_threads(), "nearGapSec": 1.5, "voiceMatch": VOICE_MATCH, "voiceMargin": VOICE_MARGIN}


def _turn_overlaps(ts):
    """別の話者の区間が重なる所 [[開始, 終了]](つなげたもの)。ts = [(開始, 終了, ラベル)](開始の順)"""
    raw, active = [], []
    for a, b, s in ts:
        active = [x for x in active if x[1] > a]
        for _, y, t in active:
            if t != s:
                raw.append((a, min(b, y)))
        active.append((a, b, s))
    merged = []
    for a, b in sorted(raw):
        if merged and a <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], b)
        else:
            merged.append([a, b])
    return [[round(a, 2), round(b, 2)] for a, b in merged[:MAX_DIAR_OVERLAPS] if b - a > 0.01]


def build_diar_run(segs, res, turns, offset, requested, emb, idmap, auto=None):
    """判別の1回分の記録。時刻は元動画の秒(行と同じ)。rows[行の id] = {"label": 機械が割り当てたラベル, "speaker": 付けた話者の id,
    "ratio": その行のうち、そのラベルの区間に入っている割合, "mixed": 声が混ざっている印, "weak": 不確かの印}。
    auto = 文字起こしのあとの自動の判別のとき {"eval": 評価用か, "contextName": 名前の候補 or None}(v0.50.0。人が始めた判別では書かない)"""
    ts = sorted((a + offset, b + offset, s) for a, b, s in turns)
    rows = {}
    for sg, (sp, mixed, weak) in zip(segs, res):
        a, b = sg["start"], sg["end"]
        cover = sum(max(0.0, min(b, y) - max(a, x)) for x, y, s in ts if s == sp and x < b and y > a) if sp is not None else 0.0
        rows[str(sg.get("id"))] = {"label": sp, "speaker": idmap.get(sp, ""), "ratio": round(min(1.0, cover / max(1e-6, b - a)), 3), "mixed": bool(mixed), "weak": bool(weak)}
    return {"at": int(time.time() * 1000), "engine": _diar_engine(emb, requested), "offset": round(float(offset), 3),
            "turns": [{"start": round(a, 2), "end": round(b, 2), "label": s} for a, b, s in ts],
            "overlaps": _turn_overlaps(ts), "labelMap": {str(k): v for k, v in idmap.items()}, "speakers": len(idmap), "rows": rows,
            "voices": {"checked": False}, **({"auto": auto} if auto else {})}


def _record_diar(tid, run):
    try:
        write_diar(tid, run)
    except Exception as e:   # 記録が書けなくても判別の結果は残す
        ed_state.log.warning("判別の記録を書けませんでした: %s %s", e.__class__.__name__, str(e)[:150])


def apply_diarization(tid, turns, offset, requested, emb=DIAR_EMB_DEFAULT, auto=None):
    """最新の文字起こしを読み直して話者を書き込む(判別中に行を編集されていても、時刻で割り当てるので矛盾しない)。
    読み直し〜書き込みは保存と同じロックの中で行う(間に画面の保存が挟まると、その保存が黙って上書きされるため)。
    auto(文字起こしのあとの自動の判別。v0.50.0)なら文書の diarization と diar.json に印を残す(画面の「自動で付けた」の案内・人の最終との比べ)"""
    with ed_store._save_lock:
        return _apply_diarization(tid, turns, offset, requested, emb, auto)


def _apply_diarization(tid, turns, offset, requested, emb, auto=None):
    doc = ed_store.read_transcript(tid)
    segs = doc.get("segments") or []
    res = assign_speakers(segs, turns, offset)
    spent = {}
    for sg, (sp, _, _) in zip(segs, res):
        if sp is not None:
            spent[sp] = spent.get(sp, 0.0) + max(0.0, sg["end"] - sg["start"])
    order = sorted(spent, key=lambda k: -spent[k])[:MAX_SPEAKERS]   # 話した時間が長い人から「話者1」「話者2」…
    idmap = {raw: "S%d" % (i + 1) for i, raw in enumerate(order)}
    speakers = [{"id": "S%d" % (i + 1), "name": "話者%d" % (i + 1), "color": SPK_COLORS[i % len(SPK_COLORS)]} for i in range(len(order))]
    unsure = 0
    for sg, (sp, mixed, weak) in zip(segs, res):
        sg["speaker"] = idmap.get(sp, "")
        parts = [x for x in str(sg.get("flag", "")).split("、") if x and x not in (ed_state.MIXED_FLAG, ed_state.WEAK_FLAG, ed_state.NONE_FLAG)]
        mark = ed_state.NONE_FLAG if not sg["speaker"] else ed_state.MIXED_FLAG if mixed else ed_state.WEAK_FLAG if weak else ""
        if mark:
            parts.append(mark)
            unsure += 1
        sg["flag"] = "、".join(parts)[:100]
    bak = os.path.join(ed_state.TX_DIR, ".bak")
    os.makedirs(bak, exist_ok=True)
    shutil.copy2(ed_store.tx_path(tid), os.path.join(bak, tid + ".pre-diarize.json"))   # 直前の状態を1世代だけ残す
    try:
        ed_store.hist_snapshot(tid, force=True)      # 履歴にも残す(画面の「履歴」から戻せる)
    except OSError:
        pass
    doc.update({"speakers": speakers, "segments": segs, "updatedAt": int(time.time() * 1000),
                "diarization": dict({"engine": "sherpa-onnx", "embedding": emb, "requested": requested, "found": len(order), "unsure": unsure, "at": int(time.time() * 1000)},
                                    **({"auto": True} if auto else {}))})
    ed_state.atomic_write(ed_store.tx_path(tid), json.dumps(doc, ensure_ascii=False, indent=1).encode("utf-8"))
    _record_diar(tid, build_diar_run(segs, res, turns, offset, requested, emb, idmap, auto))   # 機械の最初の結果(人が直す前)を <id>.diar.json に
    return len(order), unsure


def validate_diarize(req):
    tid = str(req.get("tid") or "")
    doc = ed_store.read_transcript(tid)
    if not doc.get("segments"):
        raise ed_state.ApiError("empty", "行がないため、話者を判別できません", 400)
    ed_state.check_source(doc.get("sourcePath"))
    try:
        n = int(req.get("numSpeakers") or 0)
    except (TypeError, ValueError):
        n = 0
    with ed_jobs._jobs_lock:
        if any(j.get("kind") in ("diarize", "retranscribe") and j["spec"].get("tid") == tid and j["state"] in ("queued", "loading", "extracting", "running") for j in ed_jobs._jobs.values()):
            raise ed_state.ApiError("busy", "この文字起こしは、すでに別の処理(話者判別・再認識)の最中です", 409)
    emb = str(req.get("embedding") or DIAR_EMB_DEFAULT)
    names = []   # 出てくる人の名前(友人からの依頼の「話す人」。2026-10-01)
    for x in req.get("names") if isinstance(req.get("names"), list) else []:
        s = str(x or "").strip()[:60] if isinstance(x, str) else ""
        if s and not any(ord(ch) < 32 for ch in s) and s not in names and not DEFAULT_SPK_NAME.match(s):
            names.append(s)
    return {"tid": tid, "numSpeakers": n if 1 <= n <= 10 else 0, "names": names[:10], "embedding": emb if emb in DIAR_EMBS else DIAR_EMB_DEFAULT, "title": "話者判別: " + (str(doc.get("title") or "") or "無題")[:100],
            "recognize": req.get("recognize") is not False}   # A-3: 覚えている声と照らし合わせる(既定オン)


def single_speaker(tid, name):
    """話す人が1人: 判別せずに全部の行をその人に(名前が無ければ「話者1」)。-> 行の数"""
    with ed_store._save_lock:
        doc = ed_store.read_transcript(tid)
        segs = doc.get("segments") or []
        for sg in segs:
            sg["speaker"] = "S1"
            sg["flag"] = "、".join(x for x in str(sg.get("flag", "")).split("、") if x and x not in (ed_state.MIXED_FLAG, ed_state.WEAK_FLAG, ed_state.NONE_FLAG))[:100]
        bak = os.path.join(ed_state.TX_DIR, ".bak")
        os.makedirs(bak, exist_ok=True)
        shutil.copy2(ed_store.tx_path(tid), os.path.join(bak, tid + ".pre-diarize.json"))
        try:
            ed_store.hist_snapshot(tid, force=True)
        except OSError:
            pass
        doc.update({"speakers": [{"id": "S1", "name": name or "話者1", "color": SPK_COLORS[0]}], "segments": segs, "updatedAt": int(time.time() * 1000),
                    "diarization": {"engine": "single", "requested": 1, "found": 1, "unsure": 0, "at": int(time.time() * 1000)}})
        ed_state.atomic_write(ed_store.tx_path(tid), json.dumps(doc, ensure_ascii=False, indent=1).encode("utf-8"))
        _record_diar(tid, {"at": int(time.time() * 1000), "engine": {"name": "single", "requested": 1}, "offset": 0.0, "turns": [], "overlaps": [],
                           "labelMap": {"0": "S1"}, "speakers": 1,
                           "rows": {str(sg.get("id")): {"label": 0, "speaker": "S1", "ratio": 1.0, "mixed": False, "weak": False} for sg in segs},
                           "voices": {"checked": False, "speakers": {"S1": {"label": 0, "decided": name, "by": "request", "reason": None}} if name else {}}})
        return len(segs)


def run_diarize(job):
    spec = job["spec"]
    wav = os.path.join(ed_state.TMP_DIR, job["id"] + ".wav")
    if spec.get("auto") and autodiar_skip_at_start(job):   # 自動の判別: 待っている間に人が話者を付けた・確かめ済みにしたなら何もしない(v0.50.0)
        return
    if spec.get("numSpeakers") == 1:   # 1人なら判別しない(音声も取り出さない)
        try:
            single_speaker(spec["tid"], (spec.get("names") or [""])[0])
            job["speakers"], job["unsure"] = 1, 0
            job["named"] = [{"speaker": "S1", "name": spec["names"][0], "score": None}] if spec.get("names") else []
            job["tid"], job["progress"], job["state"], job["phase"] = spec["tid"], 1.0, "done", "完了"
        except Exception as e:
            job["state"], job["error"], job["phase"] = "error", "話者を付けられませんでした: %s %s" % (e.__class__.__name__, str(e)[:150]), "失敗"
        return
    try:
        os.makedirs(ed_state.TMP_DIR, exist_ok=True)
        doc = ed_store.read_transcript(spec["tid"])
        src = ed_state.check_source(doc.get("sourcePath"))
        start, end = ed_state.num(doc.get("start"), 0.0) or 0.0, ed_state.num(doc.get("end"))
        span = (end if end else (ed_state.media_duration(src) or 0.0)) - start
        if span > MAX_DIAR_SEC:
            raise ed_state.ApiError("too_long", "話者判別は3時間までの範囲で使えます。範囲を分けて文字起こししてください", 400)
        job["state"], job["phase"], job["device"] = "extracting", "音声を取り出し中", "cpu"
        ed_jobs.extract_audio(job, {"sourcePath": src, "start": start, "end": end}, wav)
        total = ed_state.media_duration(wav) or span
        if ed_state.backend_name() == "fake":
            job["state"], job["phase"] = "running", "話者を判別中"
            turns = diarize_fake(job, total, spec["numSpeakers"])
        else:
            if not has_sherpa():
                raise ed_state.ApiError("no_sherpa", "話者判別の部品(sherpa-onnx)が入っていません。フォルダ内の install-diarize.bat(Mac は install-diarize.command)を実行してください", 400)
            job["state"] = "loading"
            ensure_diar_models(job, spec["embedding"])
            job["state"], job["phase"], job["progress"] = "running", "話者を判別中(CPU。長い音声は時間がかかります)", 0.0
            try:
                turns = diarize_real(job, wav, spec["numSpeakers"], spec["embedding"])
            except (ed_jobs.Cancelled, ed_state.ApiError):
                raise
            except Exception as e:
                raise ed_state.ApiError("diar_failed", "話者の判別に失敗しました: %s %s" % (e.__class__.__name__, str(e)[:150]), 500)
        if job["cancel"]:
            raise ed_jobs.Cancelled()
        auto = {"eval": bool(spec.get("autoEval")), "contextName": spec.get("contextName") or None} if spec.get("auto") else None
        job["speakers"], job["unsure"] = apply_diarization(spec["tid"], turns, start, spec["numSpeakers"], spec["embedding"], auto)
        if spec.get("recognize", True):   # A-3: 覚えている声と照らし合わせて、仮の名前(話者n)に名前を付ける。失敗しても判別の結果は残す
            try:
                job["named"] = recognize_voices(job, spec["tid"], wav, start, spec["embedding"], spec.get("names") or None)
            except ed_jobs.Cancelled:
                raise
            except Exception as e:
                ed_state.log.warning("声の照らし合わせに失敗: %s %s", e.__class__.__name__, str(e)[:200])
                job["voiceError"] = "覚えている声との照らし合わせに失敗しました(話者の判別の結果はそのまま): %s" % str(e)[:120]
                try:
                    update_diar_voices(spec["tid"], {"checked": False, "error": "%s %s" % (e.__class__.__name__, str(e)[:150]), "speakers": {}})
                except Exception:
                    pass
        if spec.get("contextName"):   # 評価用の自動の判別: 声で名前が付かなかった人のうち、いちばん長く話した人に動画の手がかりの名前(v0.50.0)
            try:
                hit = autodiar_name_by_context(spec["tid"], spec["contextName"])
                if hit:
                    job["named"] = list(job.get("named") or []) + [hit]
            except Exception as e:   # 名前が付けられなくても判別の結果は残す
                ed_state.log.warning("動画の手がかりで名前を付けられませんでした: %s %s", e.__class__.__name__, str(e)[:200])
        job["tid"], job["progress"], job["state"], job["phase"] = spec["tid"], 1.0, "done", "完了"
    except ed_jobs.Cancelled:
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


# ---------- 文字起こしのあと、話者を自動で判別する(v0.50.0。評価用は常に・それ以外は設定 autoDiarize) ----------
# 評価ドリルでは全行に話者が要る(評価用のフォルダの「メンバーのフォルダへ移す」条件)ので、評価用の文字起こしのあとは必ず判別のジョブを足し、
# 覚えた声で名前が付かなかった(仮の名前 話者n の)話者のうち、話した秒がいちばん長い人に「動画の手がかり」の名前
# (ed_drill.drill_candidates の suggest = 覚えた声 → 動画の入ったメンバーのフォルダ → 配信の文脈)を付ける。新しい認識の道は作らない(今の diarize のジョブ)。
# 人が付けたものは置き換えない: 文字のある行に1つでも話者があれば何もしない(足すときと、ジョブが動き出すときの両方で確かめる)。
# 判別の部品(sherpa-onnx)が無いときは黙って飛ばす(ログだけ。文字起こしは失敗にしない)。名前は serve.py からも見える(autodiar_ / AUTODIAR_ で始める)
AUTODIAR_BY = "context"   # diar.json の voices の by(動画の手がかりで付けた。覚えた声 = threshold・消去法 = elimination・依頼 = request と並べる)


def autodiar_enabled():
    """環境変数 TRANSCRIBE_AUTO_DIARIZE=off で自動の判別をしない(テスト・困ったとき用。評価用の決まりは変えない)"""
    return os.environ.get("TRANSCRIBE_AUTO_DIARIZE", "").strip().lower() not in ("off", "0", "no", "false")


def autodiar_ready():
    """判別の部品があるか(疑似のときは常に)。サーバー側では sherpa-onnx を読み込まない(has_sherpa はワーカー側で調べる)。
    テスト用の worker-fake(ワーカーの中だけ偽のモデル)では使わない(判別は本物の経路 = モデルの取得になるため)"""
    if ed_state.backend_name() == "fake":
        return True
    return not ed_state.worker_fake() and has_sherpa()


def autodiar_why_not(doc):
    """自動で判別しない理由(None = 判別してよい): lite(友人用簡易版)・empty(文字のある行が無い)・reviewed(評価用で確かめ済み)・
    has_speakers(文字のある行に話者がある = 人か前の判別が付けた。置き換えない)"""
    if doc.get("lite"):
        return "lite"
    ids = {s.get("id") for s in doc.get("speakers") or [] if isinstance(s, dict) and s.get("id")}
    rows = [g for g in doc.get("segments") or [] if isinstance(g, dict) and str(g.get("text") or "").strip()]
    if not rows:
        return "empty"
    if doc.get("evalSet") is True and isinstance(doc.get("evalReviewed"), dict):
        return "reviewed"
    if any(g.get("speaker") in ids for g in rows):
        return "has_speakers"
    return None


def autodiar_enqueue(tid, batch=False):
    """自動の判別のジョブを足す(人数 自動・覚えた声との照合あり)。評価用なら名前の候補(suggest)も渡す。
    -> {"job": ジョブ, "name": 名前の候補 or None} か {"skipped": 理由}。足せない(待機列がいっぱい・処理中など)は ApiError。
    batch = 評価用のまとめての文字起こし(ed_evalbatch)が入れた印(spec["evalBatch"]。そちらの待ちの数に入る)"""
    if not autodiar_enabled():
        return {"skipped": "off"}
    if not autodiar_ready():
        ed_state.log.info("話者の自動判別を飛ばしました(判別の部品 sherpa-onnx が無い): %s", tid)
        return {"skipped": "no_sherpa"}
    doc = ed_store.read_transcript(tid)
    why = autodiar_why_not(doc)
    if why:
        return {"skipped": why}
    ev = doc.get("evalSet") is True
    name = None
    if ev:
        try:
            name = str(ed_drill.drill_candidates(tid).get("suggest") or "").strip()[:30] or None
        except Exception as e:   # 名簿・ほかのツールのデータが読めなくても判別は始める(名前は付けない)
            ed_state.log.info("話者の名前の候補を決められませんでした: %s %s", tid, str(e)[:150])
        if name and (DEFAULT_SPK_NAME.match(name) or is_generic_speaker_name(name)):
            name = None
    spec = validate_diarize({"tid": tid, "numSpeakers": 0, "recognize": True, "embedding": ed_learn.load_settings().get("diarEmb")})
    spec.update({"auto": True, "autoEval": ev, "contextName": name,
                 "title": "話者判別(自動): " + (str(doc.get("title") or "") or "無題")[:100]})
    if batch:
        spec["evalBatch"] = True
    return {"job": ed_jobs.add_job(spec, "diarize"), "name": name}


def autodiar_after_transcribe(job, spec, tid):
    """文字起こしのジョブ(ed_jobs.run_job)の終わり。文書を書いたあと・「完了」にする前に呼ぶ(ドリルが判別の前の文書を開かないよう、間を空けない)。
    評価用は常に・それ以外は設定 autoDiarize。友人用簡易版は除く。始められなくても文字起こしは成功のまま(job["warnings"])"""
    if spec.get("lite") or not (spec.get("evalSet") or spec.get("autoDiarize")):
        return
    try:
        r = autodiar_enqueue(tid, batch=bool(spec.get("evalBatch")))
        if r.get("skipped") == "no_sherpa" and not spec.get("evalSet"):   # 設定でオンにした人には知らせる(評価用は黙って飛ばす = 人が「全行をこの人に」)
            job["warnings"] = list(job.get("warnings") or []) + ["話者の判別の部品(sherpa-onnx)が入っていないため、話者は自動で判別しませんでした"]
    except ed_state.ApiError as e:
        job["warnings"] = list(job.get("warnings") or []) + ["話者の自動判別を始められませんでした: " + e.message]
    except Exception as e:   # 想定外でも、書き終えた文字起こしのジョブを失敗にしない
        ed_state.log.warning("話者の自動判別を始められませんでした: %s %s %s", tid, e.__class__.__name__, str(e)[:150])


def autodiar_skip_at_start(job):
    """自動の判別のジョブが動き出すとき、もう一度確かめる(待っている間に人が話者を付けた・確かめ済みにした・行が消えた)。
    判別しないなら「完了(判別しませんでした)」にして True"""
    spec = job["spec"]
    try:
        why = autodiar_why_not(ed_store.read_transcript(spec["tid"]))
    except ed_state.ApiError as e:
        why = e.code
    if not why:
        return False
    job["autoSkipped"] = why
    job["tid"], job["progress"], job["state"] = spec["tid"], 1.0, "done"
    job["phase"] = "判別しませんでした(" + {"has_speakers": "話者が付いていました", "reviewed": "確かめ済みです", "empty": "文字のある行がありません"}.get(why, why) + ")"
    return True


def autodiar_name_by_context(tid, name):
    """覚えた声で名前が付かなかった(仮の名前 話者n の)話者のうち、話した秒がいちばん長い人に name を付ける(1 人だけならその人)。
    name がもうほかの話者に使われていれば付けない(覚えた声の名前を優先)。読み直し〜書き込みは保存と同じロックの中(recognize_voices と同じ)。
    -> {"speaker", "name", "score": None, "by": "context"} か None。経過は diar.json の voices(_autodiar_record)"""
    nm = str(name or "").strip()[:30]
    key = _spk_name_key(nm)
    hit, reason = None, None
    with ed_store._save_lock:
        doc = ed_store.read_transcript(tid)
        sps = [s for s in doc.get("speakers") or [] if isinstance(s, dict)]
        spent = {}
        for g in doc.get("segments") or []:
            if isinstance(g, dict) and g.get("speaker") and str(g.get("text") or "").strip():
                a, b = ed_state.num(g.get("start"), 0.0) or 0.0, ed_state.num(g.get("end"), 0.0) or 0.0
                spent[g["speaker"]] = spent.get(g["speaker"], 0.0) + max(0.0, b - a)
        left = [s for s in sps if DEFAULT_SPK_NAME.match(str(s.get("name") or "")) and spent.get(s.get("id"), 0.0) > 0]
        if not nm or not sps:
            reason = "no_speakers" if nm else "no_name"
        elif any(_spk_name_key(str(s.get("name") or "")) == key for s in sps):
            reason = "name_in_use"
        elif not left:
            reason = "all_named"
        else:
            pick = max(left, key=lambda s: spent.get(s.get("id"), 0.0))   # 同じ秒なら先の人(話者1 = 判別が長い順に付けた番号)
            pick["name"] = nm
            hit = {"speaker": pick["id"], "name": nm, "score": None, "by": AUTODIAR_BY}
            if isinstance(doc.get("diarization"), dict):
                doc["diarization"]["contextName"] = nm
            doc["updatedAt"] = int(time.time() * 1000)
            ed_state.atomic_write(ed_store.tx_path(tid), json.dumps(doc, ensure_ascii=False, indent=1).encode("utf-8"))
    _autodiar_record(tid, nm, hit, reason)
    return hit


def _autodiar_record(tid, name, hit, reason):
    """diar.json の最新の voices に、動画の手がかりで付けた名前(speakers[id].by = context)と経過 context = {name, speaker, reason} を書く。
    人の最終(行の speaker・speakers[].name)と、機械が付けた名前を後で比べられるように。書けなくても名前付けは続ける"""
    try:
        with _diar_lock:
            d = read_diar(tid)
            if not d:
                return
            latest = d["latest"]
            v = latest.get("voices") if isinstance(latest.get("voices"), dict) else {"checked": False}
            sp = v.get("speakers") if isinstance(v.get("speakers"), dict) else {}
            if hit:
                inv = {x: (int(k) if str(k).isdigit() else k) for k, x in (latest.get("labelMap") or {}).items()}
                one = sp.get(hit["speaker"]) if isinstance(sp.get(hit["speaker"]), dict) else {
                    "top": None, "score": None, "second": None, "secondScore": None, "label": inv.get(hit["speaker"])}
                one.update({"decided": hit["name"], "by": AUTODIAR_BY, "reason": None})
                sp[hit["speaker"]] = one
            v["speakers"] = sp
            v["context"] = {"name": name, "speaker": hit["speaker"] if hit else None, "reason": reason}
            latest["voices"] = v
            ed_state.atomic_write(diar_path(tid), json.dumps(d, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
    except Exception as e:
        ed_state.log.warning("動画の手がかりの名前の記録を書けませんでした: %s %s", e.__class__.__name__, str(e)[:150])


# ---------- 話者の声を覚える(A-3。docs/archive/backlog-ui-2026-09-27.md) ----------
# 名前を付けた話者の行の音声から「声の特徴」(sherpa-onnx の話者の埋め込み。判別モデルごとに別)を作って覚え、
# 次からの話者判別のあとで、見つかった話者を覚えている声と比べて名前を付ける。
# 声の特徴は個人を見分けられる情報なので、作業データ(voices/)にだけ置く(リポジトリ・パックには入れない)。
# 計算(numpy・sherpa-onnx)は認識ワーカーの中だけ(_embed_local)。サーバーでは読み込まない
VOICES_DIR = os.path.join(ed_state.DATA_DIR, "voices")
VOICE_MATCH = 0.60        # 覚えている声とのコサイン類似度がこれ以上なら同じ人とみなす
VOICE_MARGIN = 0.08       # 2番目に近い声との差がこれより小さければ決めない(似た声を取り違えるより、名前を付けない方が安全)
VOICE_MIN_ROW = 1.0       # 声の特徴を取る行の最短(秒)。短い行(相づち)は特徴が安定しない
VOICE_MAX_ROWS = 40       # 1人あたり使う行の数の上限(長い行から)
VOICE_MAX_SEC = 240.0     # 1人あたり使う長さの上限(秒)
VOICE_MAX_PEOPLE = 300
DEFAULT_SPK_NAME = re.compile(r"^話者\d+$")   # 話者判別が付けた仮の名前(覚えない・声で付けた名前で置き換えてよい)
_voices_lock = threading.Lock()
# 一般的な名前(監査18。段1・2026-09-29 ユーザー決定): 声を覚えると、別の配信の「本人」「ゲスト」に同じ名前が付いてしまう(人ではなく役の名前)ので覚えない。
# 判定は is_generic_speaker_name の1か所(画面は preview の結果を出すだけ)。比べる前に NFKC・小文字・空白を寄せる(全角の「ＭＣ」・「Speaker 1」も同じに)
GENERIC_SPK_NAMES = frozenset(("本人", "ゲスト", "配信者", "私", "自分", "相手", "司会", "mc", "男性", "女性", "不明", "その他", "視聴者", "ナレーション",
                               "話者", "speaker", "スピーカー"))
GENERIC_SPK_FORM = re.compile(r"^(?:話者|speaker|spk|スピーカー)?(?:\d+|[a-z])$")   # 話者A・話者1・Speaker 1・英字1文字・数字だけ


def _spk_name_key(name):
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", str(name or "")).lower())


def is_generic_speaker_name(name):
    k = _spk_name_key(name)
    return bool(k) and (k in GENERIC_SPK_NAMES or bool(GENERIC_SPK_FORM.match(k)))


def voices_path(emb):
    return os.path.join(VOICES_DIR, emb + ".json")


def load_voices(emb):
    """{名前: {"vec": [...], "rows": 使った行の数, "sec": 使った秒, "updatedAt": ms}}(判別モデル emb ごと)"""
    try:
        with open(voices_path(emb), encoding="utf-8") as f:
            d = json.load(f)
    except (OSError, ValueError):
        return {}
    v = d.get("voices") if isinstance(d, dict) else None
    if not isinstance(v, dict):
        return {}
    return {str(k)[:60]: x for k, x in v.items() if isinstance(x, dict) and isinstance(x.get("vec"), list) and x["vec"]}


def save_voices(emb, voices):
    os.makedirs(VOICES_DIR, exist_ok=True)
    ed_state.atomic_write(voices_path(emb), json.dumps({"schema": "ytt-voices/v1", "embedding": emb, "voices": voices}, ensure_ascii=False).encode("utf-8"))


def _unit(v):
    s = math.sqrt(sum(x * x for x in v)) if v else 0.0
    return [x / s for x in v] if s > 0 else None


def _cos(a, b):
    """どちらも長さ 1 の特徴どうしのコサイン類似度(次元が違えば -1 = 比べられない)"""
    return sum(x * y for x, y in zip(a, b)) if a and b and len(a) == len(b) else -1.0


def voice_groups(segs, key):
    """行 → {キー: ([(開始, 終了)...], 合計秒)}。key(行) が空の行は使わない。
    短い行・「声が混ざっている」行は使わない。長い行から VOICE_MAX_ROWS 行・VOICE_MAX_SEC 秒まで"""
    by = {}
    for g in segs:
        k = key(g)
        if not k:
            continue
        a, b = ed_state.num(g.get("start")), ed_state.num(g.get("end"))
        if a is None or b is None or b - a < VOICE_MIN_ROW or ed_state.MIXED_FLAG in str(g.get("flag") or ""):
            continue
        by.setdefault(k, []).append((a, b))
    out = {}
    for k, rs in by.items():
        rs.sort(key=lambda r: -(r[1] - r[0]))
        pick, tot = [], 0.0
        for a, b in rs[:VOICE_MAX_ROWS]:
            if tot >= VOICE_MAX_SEC:
                break
            pick.append((a, b))
            tot += b - a
        out[k] = (sorted(pick), tot)
    return out


def embed_groups(job, wav, emb, groups, offset):
    """groups: [[(開始, 終了)...]](元の動画の時刻)。wav は offset 秒から始まる音声。-> [長さ 1 の特徴 or None](groups と同じ並び)"""
    rel = [[[max(0.0, a - offset), max(0.0, b - offset)] for a, b in g] for g in groups]
    if ed_state.backend_name() == "fake":
        return embed_fake(rel)
    if ed_jobs.IN_WORKER:
        return _embed_local(job, wav, emb, rel)
    res = ed_jobs.WORKER.call("embed", {"wav": wav, "emb": emb, "groups": rel}, job)
    return [[float(x) for x in v] if isinstance(v, list) and v else None for v in res]


def embed_fake(groups):
    """テスト用: 偽の話者判別(diarize_fake: 10秒ごとに入れ替わる)と同じ区切りの番号ごとに、向きの違う特徴"""
    out = []
    for g in groups:
        votes = {}
        for a, b in g:
            k = int(((a + b) / 2.0) // 10) % 2   # diarize_fake の既定(2人)と同じ入れ替わり
            votes[k] = votes.get(k, 0.0) + (b - a)
        if not votes:
            out.append(None)
            continue
        v = [0.1] * 8
        v[max(votes, key=votes.get)] = 1.0
        out.append(_unit(v))
    return out


def _embed_local(job, wav, emb, groups):
    """認識ワーカーの中だけで動く(numpy・sherpa-onnx)。区間ごとの特徴を長さで重みを付けて平均し、長さ 1 に"""
    import numpy as np
    import sherpa_onnx as so
    threads = diar_threads()
    cfg = so.SpeakerEmbeddingExtractorConfig(model=_diar_path(DIAR_EMBS[emb]), num_threads=threads)
    if not cfg.validate():
        raise ed_state.ApiError("diar_failed", "声の特徴のモデルを読み込めませんでした(models フォルダを削除して、もう一度試してください)", 500)
    ex = so.SpeakerEmbeddingExtractor(cfg)
    samples, sr = read_wav_f32(wav), 16000
    total, done, out = max(1, sum(len(g) for g in groups)), 0, []
    for g in groups:
        vecs, weights = [], []
        for a, b in g:
            if job["cancel"]:
                raise ed_jobs.Cancelled()
            done += 1
            job["progress"] = min(0.99, done / total)
            seg = samples[int(a * sr):int(b * sr)]
            if len(seg) < sr // 2:
                continue
            st = ex.create_stream()
            st.accept_waveform(sample_rate=sr, waveform=seg)
            st.input_finished()
            if not ex.is_ready(st):
                continue
            e = np.array(ex.compute(st), dtype=np.float32)
            n = float(np.linalg.norm(e))
            if n > 0:
                vecs.append(e / n)
                weights.append(b - a)
        if not vecs:
            out.append(None)
            continue
        m = np.average(np.stack(vecs), axis=0, weights=np.array(weights))
        n = float(np.linalg.norm(m))
        out.append([float(x) for x in (m / n)] if n > 0 else None)
    return out


def match_voices(found, voices):
    """found: {話者の id: 特徴}、voices: 覚えている声。-> {話者の id: (名前, 似ている度合い)}。
    VOICE_MATCH 以上・2番目との差が VOICE_MARGIN 以上のときだけ。1つの名前は1人にだけ(似ている順に決める)"""
    return match_voices_explain(found, voices)[0]


def match_voices_explain(found, voices):
    """match_voices と同じ決め方で、決まった結果に加えて話者ごとの経過も返す(判別の記録 <id>.diar.json 用)。
    -> (match_voices と同じ, {話者の id: {"top", "score", "second", "secondScore", "decided", "by", "reason"}})。
    reason = 付けなかった理由: no_feature(特徴が取れない)・no_voices(比べる声が無い)・below_match(しきい値に届かない)・margin(2位との差が足りない)・name_taken(同じ名前を別の人が先に取った)"""
    names = list(voices)
    cands, info = [], {}
    for sid, v in found.items():
        d = info[sid] = {"top": None, "score": None, "second": None, "secondScore": None, "decided": None, "by": None, "reason": None}
        if not v:
            d["reason"] = "no_feature"
            continue
        sc = sorted(((_cos(v, voices[n]["vec"]), n) for n in names), reverse=True)
        if not sc:
            d["reason"] = "no_voices"
            continue
        d["top"], d["score"] = sc[0][1], round(sc[0][0], 3)
        if len(sc) > 1:
            d["second"], d["secondScore"] = sc[1][1], round(sc[1][0], 3)
        if sc[0][0] < VOICE_MATCH:
            d["reason"] = "below_match"
            continue
        if len(sc) > 1 and sc[0][0] - sc[1][0] < VOICE_MARGIN:
            d["reason"] = "margin"
            continue
        cands.append((sc[0][0], sid, sc[0][1]))
    out, used = {}, set()
    for score, sid, name in sorted(cands, reverse=True):
        if sid in out:
            continue
        if name in used:
            info[sid]["reason"] = "name_taken"
            continue
        out[sid] = (name, round(score, 3))
        used.add(name)
        info[sid]["decided"], info[sid]["by"] = name, "threshold"
    return out, info


def recognize_voices(job, tid, wav, offset, emb, names=None):
    """話者判別のあと: 見つかった話者を覚えている声と比べ、仮の名前(話者n)のままの話者に名前を付ける。-> [{"speaker", "name", "score"}]。
    names(出てくる人の名前。友人からの依頼)があれば、照らし合わせをその名前だけにし、最後に仮の名前の話者と使っていない名前が1つずつ残れば消去法で付ける(score None)。
    照合の経過(点数・2位との差・決まり方・付けなかった理由)は <id>.diar.json の voices に残す(update_diar_voices。書けなくても名前付けは続ける)"""
    all_voices = load_voices(emb)
    voices = {n: v for n, v in all_voices.items() if n in names} if names else all_voices
    got, detail = {}, {}
    if voices:
        doc = ed_store.read_transcript(tid)
        grp = voice_groups(doc.get("segments") or [], lambda g: g.get("speaker") or "")
        ids = list(grp)
        if ids:
            job["phase"] = "覚えている声と照らし合わせ中"
            vecs = embed_groups(job, wav, emb, [grp[i][0] for i in ids], offset)
            got, detail = match_voices_explain(dict(zip(ids, vecs)), voices)

    def record(doc, named):
        """diar.json の voices(話者ごとの経過 + 名前を付けた結果)。失敗しても名前付けには響かせない"""
        try:
            rec = {}
            for s in doc.get("speakers") or []:
                if not isinstance(s, dict):
                    continue
                d = dict(detail.get(s.get("id")) or {"top": None, "score": None, "second": None, "secondScore": None, "decided": None, "by": None,
                                                     "reason": "no_voices" if not voices else "no_rows"})
                hit = next((n for n in named if n["speaker"] == s.get("id")), None)
                if hit:
                    d["decided"], d["by"], d["reason"] = hit["name"], hit.get("by") or ("elimination" if hit["score"] is None else "threshold"), None
                elif d.get("decided"):   # しきい値は通ったが、名前が付かなかった(自分で付けた名前・別の人が使っている名前)
                    d["reason"] = "already_named" if not DEFAULT_SPK_NAME.match(str(s.get("name") or "")) else "name_in_use"
                    d["decided"], d["by"] = None, None
                rec[str(s.get("id"))] = d
            update_diar_voices(tid, {"checked": True, "embedding": emb, "registered": len(all_voices), "restrictedNames": list(names) if names else None,
                                     "match": VOICE_MATCH, "margin": VOICE_MARGIN, "speakers": rec})
        except Exception as e:
            ed_state.log.warning("声の照合の記録を書けませんでした: %s %s", e.__class__.__name__, str(e)[:150])

    if not got and not names:
        record(ed_store.read_transcript(tid), [])
        return []
    named = []
    with ed_store._save_lock:   # 読み直し〜書き込みは保存と同じロックの中(話者判別の書き込みと同じ)
        doc = ed_store.read_transcript(tid)
        taken = {str(s.get("name") or "") for s in doc.get("speakers") or [] if isinstance(s, dict)}
        for s in doc.get("speakers") or []:
            hit = got.get(s.get("id")) if isinstance(s, dict) else None
            if hit and DEFAULT_SPK_NAME.match(str(s.get("name") or "")) and hit[0] not in taken:
                s["name"] = hit[0]
                taken.add(hit[0])
                named.append({"speaker": s["id"], "name": hit[0], "score": hit[1], "by": "threshold"})
        if names:   # 消去法: 名前の無い話者と使っていない名前が1つずつなら、その人
            left = [s for s in doc.get("speakers") or [] if isinstance(s, dict) and DEFAULT_SPK_NAME.match(str(s.get("name") or ""))]
            unused = [n for n in names if n not in taken]
            if len(left) == 1 and len(unused) == 1:
                left[0]["name"] = unused[0]
                named.append({"speaker": left[0]["id"], "name": unused[0], "score": None, "by": "elimination"})
        if named:
            doc["updatedAt"] = int(time.time() * 1000)
            ed_state.atomic_write(ed_store.tx_path(tid), json.dumps(doc, ensure_ascii=False, indent=1).encode("utf-8"))
    record(doc, named)
    return named


VOICE_LEARN_TAGS = ("overlap", "bgm", "unclear")   # この印の行は覚えない(声が重なる・BGM が大きい・聞き取れない。監査17)
EVAL_SET_VOICE_MSG = "評価用の文字起こしでは声を覚えません(評価用のデータを、ほかの文書の話者の名前付けに使わないため)。評価用を外してから行ってください"


def voice_learn_plan(doc):
    """声を覚えるときに使う行(監査17。段1): voice_groups の条件(1秒以上・声が混ざっていない)に加えて、校正済みで、音のメモ(重なり・BGM・聞き取れない)が無い行だけ。
    話者判別のときの照らし合わせ(recognize_voices)は voice_groups のまま(校正前の文書でも名前が付くように。変えない決定)。
    -> {"groups": {名前: ([(開始, 終了)...], 秒)}, "speakers": {名前: [話者の id]}, "refused": [{"name", "speakers", "reason": "generic"|"no_rows"}],
        "skipped": {"unproofed", "tagged", "mixed", "short"}(覚える人の行のうち使わなかった数。理由は 1秒未満 → 混ざる → 音のメモ → 未校正 の順に1つ)}"""
    names = {s.get("id"): str(s.get("name") or "").strip()[:60] for s in doc.get("speakers") or [] if isinstance(s, dict)}
    by_name, refused = {}, {}
    for sid, n in names.items():
        if not n or DEFAULT_SPK_NAME.match(n):
            continue   # 仮の名前 = 名前を付けていない(断った扱いにもしない)
        if is_generic_speaker_name(n):
            refused.setdefault(n, {"name": n, "speakers": [], "reason": "generic"})["speakers"].append(sid)
            continue
        by_name.setdefault(n, []).append(sid)
    who = {sid: n for n, sids in by_name.items() for sid in sids}
    skipped = {"unproofed": 0, "tagged": 0, "mixed": 0, "short": 0}
    ok = []
    for g in doc.get("segments") or []:
        if not isinstance(g, dict) or g.get("speaker") not in who:
            continue
        a, b = ed_state.num(g.get("start")), ed_state.num(g.get("end"))
        tags = g.get("tags") if isinstance(g.get("tags"), list) else []
        if a is None or b is None or b - a < VOICE_MIN_ROW:
            skipped["short"] += 1
        elif ed_state.MIXED_FLAG in str(g.get("flag") or ""):
            skipped["mixed"] += 1
        elif any(t in tags for t in VOICE_LEARN_TAGS):
            skipped["tagged"] += 1
        elif g.get("proofed") is not True:
            skipped["unproofed"] += 1
        else:
            ok.append(g)
    groups = voice_groups(ok, lambda g: who.get(g.get("speaker")) or "")
    for n, sids in by_name.items():
        if n not in groups:
            refused[n] = {"name": n, "speakers": sids, "reason": "no_rows"}
    return {"groups": groups, "speakers": {n: sids for n, sids in by_name.items() if n in groups},
            "refused": sorted(refused.values(), key=lambda r: r["name"]), "skipped": skipped}


def _voice_emb(req, doc):
    emb = str(req.get("embedding") or (doc.get("diarization") or {}).get("embedding") or DIAR_EMB_DEFAULT)
    return emb if emb in DIAR_EMBS else DIAR_EMB_DEFAULT


def voice_preview(tid, emb):
    """覚える前の確認(GET /api/voices/preview。読むだけ・ジョブを作らない。監査17・18)"""
    doc = ed_store.read_transcript(str(tid or ""))
    emb = _voice_emb({"embedding": emb}, doc)
    plan = voice_learn_plan(doc)
    voices = load_voices(emb)
    people = []
    for n in sorted(plan["groups"]):
        rs, sec = plan["groups"][n]
        old = voices.get(n)
        people.append({"name": n, "speaker": plan["speakers"][n][0], "speakers": plan["speakers"][n], "rows": len(rs), "sec": round(sec, 1), "exists": bool(old),
                       "old": {"rows": int(old.get("rows") or 0), "sec": float(old.get("sec") or 0.0), "updatedAt": int(old.get("updatedAt") or 0)} if old else None})
    return {"tid": tid, "embedding": emb, "evalSet": doc.get("evalSet") is True, "people": people, "refused": plan["refused"], "skipped": plan["skipped"]}


def validate_voice_learn(req):
    tid = str(req.get("tid") or "")
    doc = ed_store.read_transcript(tid)
    if doc.get("evalSet") is True:   # 監査02: 評価用の声を覚えると、評価用のデータがほかの文書の名前付けに使われる
        raise ed_state.ApiError("eval_set", EVAL_SET_VOICE_MSG, 400)
    want = req.get("names")
    if not isinstance(want, list) or not all(isinstance(n, str) for n in want):   # 画面と API の版はそろえて上げる(古い形は受けない = 確認を飛ばして覚えない)
        raise ed_state.ApiError("bad_request", "覚える人の指定(names)がありません。画面を読み込み直してから、もう一度押してください", 400)
    plan = voice_learn_plan(doc)
    names = [n for n in dict.fromkeys(str(x).strip()[:60] for x in want) if n in plan["groups"]]
    if not names:
        gen = [r["name"] for r in plan["refused"] if r["reason"] == "generic"]
        raise ed_state.ApiError("no_names", "覚えられる話者がいません。校正済みの行(1秒以上・音のメモなし)がある、名前を付けた話者の声だけを覚えます"
                       "(「話者1」のような仮の名前%sは覚えません)" % ("・「%s」のような一般的な名前" % "」「".join(gen[:3]) if gen else ""), 400)
    ed_state.check_source(doc.get("sourcePath"))
    emb = _voice_emb(req, doc)
    same = {str(x) for x in req.get("confirmSame") or [] if isinstance(x, str)}
    voices = load_voices(emb)
    ask = [n for n in names if n in voices and n not in same]
    if ask:   # 監査18: 既にある名前に足すのは「同じ人」と確かめたときだけ(別人の声が混ざると、その名前の照らし合わせが外れる)
        raise ed_state.ApiError("confirm_same", "「%s」の声はもう覚えています。同じ人か確かめてから、もう一度押してください" % "」「".join(ask), 409, extra={"names": ask})
    with ed_jobs._jobs_lock:
        if any(j.get("kind") in ("diarize", "retranscribe", "redo", "voice-learn") and j["spec"].get("tid") == tid and j["state"] in ed_jobs.ACTIVE_STATES for j in ed_jobs._jobs.values()):
            raise ed_state.ApiError("busy", "この文字起こしは、すでに別の処理(話者判別・再認識・声を覚える)の最中です", 409)
    return {"tid": tid, "embedding": emb, "names": names, "confirmSame": sorted(same & set(names)),
            "title": "声を覚える: " + (str(doc.get("title") or "") or "無題")[:100]}


def run_voice_learn(job):
    spec = job["spec"]
    wav = os.path.join(ed_state.TMP_DIR, job["id"] + ".wav")
    try:
        os.makedirs(ed_state.TMP_DIR, exist_ok=True)
        doc = ed_store.read_transcript(spec["tid"])
        if doc.get("evalSet") is True:   # 待っている間に評価用へ変えた場合も断る(監査02)
            raise ed_state.ApiError("eval_set", EVAL_SET_VOICE_MSG, 400)
        src = ed_state.check_source(doc.get("sourcePath"))
        start, end = ed_state.num(doc.get("start"), 0.0) or 0.0, ed_state.num(doc.get("end"))
        plan = voice_learn_plan(doc)   # 読み直した文書で決め直し、確認した人(spec["names"])との積だけを覚える(確認のあとで名前を付けた人を黙って覚えない)
        grp = {n: plan["groups"][n] for n in spec.get("names") or [] if n in plan["groups"]}
        if not grp:
            raise ed_state.ApiError("no_names", "覚えられる話者の行がありません(待っている間に名前・校正済みの印が変わった可能性があります)", 400)
        if ed_state.backend_name() != "fake" and not has_sherpa():
            raise ed_state.ApiError("no_sherpa", "声を覚えるには話者判別の部品(sherpa-onnx)が要ります。フォルダ内の install-diarize.bat を実行してください", 400)
        job["state"], job["phase"], job["device"] = "extracting", "音声を取り出し中", "cpu"
        ed_jobs.extract_audio(job, {"sourcePath": src, "start": start, "end": end}, wav)
        if ed_state.backend_name() != "fake":
            job["state"] = "loading"
            ensure_diar_models(job, spec["embedding"])
        job["state"], job["phase"], job["progress"] = "running", "声の特徴を取り出し中(CPU)", 0.0
        people = sorted(grp)
        vecs = embed_groups(job, wav, spec["embedding"], [grp[n][0] for n in people], start)
        if job["cancel"]:
            raise ed_jobs.Cancelled()
        learned = []
        with _voices_lock:
            voices = load_voices(spec["embedding"])
            same = set(spec.get("confirmSame") or [])
            for n, v in zip(people, vecs):
                if not v:
                    continue
                rows, sec = len(grp[n][0]), grp[n][1]
                old = voices.get(n)
                if old and n not in same:   # 待っている間にほかで同じ名前を覚えた(確かめていない人の声には足さない)
                    job.setdefault("warnings", []).append("「%s」の声は、待っている間にほかで覚えられたので足しませんでした(同じ人なら、もう一度「声を覚える」を押してください)" % n)
                    continue
                if old and len(old["vec"]) == len(v):   # 前に覚えた声と、使った長さで重みを付けて混ぜる(配信ごとの声の揺れをならす)
                    w0 = min(float(old.get("sec") or 0.0), 3600.0)
                    v = _unit([a * w0 + b * sec for a, b in zip(old["vec"], v)]) or v
                    rows, sec = rows + int(old.get("rows") or 0), sec + w0
                voices[n] = {"vec": [round(x, 6) for x in v], "rows": rows, "sec": round(sec, 1), "updatedAt": int(time.time() * 1000)}
                learned.append(n)
            if len(voices) > VOICE_MAX_PEOPLE:
                raise ed_state.ApiError("too_many", "覚えられる声は %d 人までです(使わない声を消してください)" % VOICE_MAX_PEOPLE, 400)
            if learned:
                save_voices(spec["embedding"], voices)
        if not learned:
            raise ed_state.ApiError("no_voice", "声の特徴を取り出せませんでした(行が短すぎる・音声が無い可能性があります)", 400)
        job["learned"] = learned
        job["speakers"] = len(learned)
        job["tid"], job["progress"], job["state"], job["phase"] = spec["tid"], 1.0, "done", "完了"
    except ed_jobs.Cancelled:
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


def voices_summary():
    """覚えている声の一覧(特徴そのものは返さない)。{判別モデル: [{"name", "rows", "sec", "updatedAt"}]}"""
    out = {}
    for emb in DIAR_EMBS:
        v = load_voices(emb)
        if v:
            out[emb] = sorted(({"name": n, "rows": int(x.get("rows") or 0), "sec": float(x.get("sec") or 0.0), "updatedAt": int(x.get("updatedAt") or 0),
                                "generic": is_generic_speaker_name(n)}   # 一般的な名前で前に覚えた声(消さない。一覧で「忘れることをおすすめします」と出す)
                               for n, x in v.items()), key=lambda r: r["name"])
    return out


def delete_voice(emb, name):
    if emb not in DIAR_EMBS:
        raise ed_state.ApiError("bad_request", "判別モデルの指定が正しくありません", 400)
    with _voices_lock:
        voices = load_voices(emb)
        if name not in voices:
            raise ed_state.ApiError("not_found", "その声は覚えていません", 404)
        del voices[name]
        save_voices(emb, voices)
