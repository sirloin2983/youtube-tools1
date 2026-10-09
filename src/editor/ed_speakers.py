# -*- coding: utf-8 -*-
"""「編集」のサーバーの部品: 話者の自動判別(sherpa-onnx)・話者の声を覚える(段10 で editor/serve.py から分けた。git の履歴(679ff01 以前)の docs/plan/phase10-code-split.md)。

名前は serve.py からも見える(serve.py が受け付けて、この部品へ転送する。テストの S.名前 = … もここに入る)。
ほかの部品の名前は `ed_xxx.名前` の形で呼ぶたびに読む(差し替えが効くように。from … import はしない)。
"""
import bisect
import contextlib
import hashlib
import json
import math
import os
import re
import shutil
import tarfile
import threading
import time
import unicodedata
import urllib.error
import urllib.request

import ed_drill  # noqa: E402,F401   (評価用の文書の名前の候補 drill_candidates。呼ぶときに読む)
import ed_fill  # noqa: E402,F401   (判別のあと、定型の幻覚で声の無い行を捨てる fill_clean_turns。0.60.0)
import ed_jobs  # noqa: E402,F401
import ed_learn  # noqa: E402,F401
import ed_state  # noqa: E402,F401
import ed_store  # noqa: E402,F401
from pipeline.transcribe import tx_engines  # noqa: E402,F401   環境変数の数 env_num だけ(ネイティブの部品は読み込まない)
from pipeline.transcribe import worker_client  # noqa: E402   認識ワーカー(IN_WORKER・WORKER)と wav を読まずに渡す形 read_wav_f32(RS2-6 にここから移した)
from ytt import fsio as _fsio  # noqa: E402
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
DIAR_CLUSTER_THRESHOLD, DIAR_MIN_ON, DIAR_MIN_OFF = 0.6, 0.1, 0.3   # sherpa-onnx の設定(_diarize_local と、判別の記録 <id>.diar.json の engine に同じ値を使う)
MAX_SPEAKERS = 20
SPK_COLORS = ["#2f62d6", "#d9534f", "#2e9e5b", "#c98a12", "#8a4fd6", "#0f9aa8", "#d6479a", "#6b7280"]


def diar_threads():
    """話者判別(sherpa-onnx)のスレッド数。既定は min(8, CPU)(2026-10-04 に 4 から上げた。P コアの数。環境変数 TRANSCRIBE_DIAR_THREADS で変えられる。
    git の履歴(679ff01 以前)の docs/plan/stability-review-2026-10.md の S2)"""
    n = tx_engines.env_num("TRANSCRIBE_DIAR_THREADS", 0, lo=0, hi=64)   # 0 以下・読めない = CPU の数から決める
    return n if n > 0 else max(1, min(8, os.cpu_count() or 2))


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
            ed_jobs.check_cancel(job)
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
        if _have(item):
            continue
        dest = _diar_path(item)
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
                _fsio.replace_retry(part, dest)
            else:
                _fsio.replace_retry(tmp, dest)
        except (urllib.error.URLError, OSError, tarfile.TarError, KeyError) as e:
            raise ed_state.ApiError("model_download", "話者判別のモデルをダウンロードできませんでした(初回はインターネット接続が必要です): %s" % str(e)[:150], 500)
        finally:
            for x in (tmp, part):
                _fsio.unlink_quiet(x)


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
    if worker_client.IN_WORKER:
        return _diarize_local(job, wav, num, emb, **tune)
    args = {"wav": wav, "num": int(num), "emb": emb}
    args.update({w: tune[k] for k, w in DIAR_TUNE if k in tune})
    turns = worker_client.WORKER.call("diarize", args, job)
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
    samples = worker_client.read_wav_f32(wav)

    def cb(done, total, *_):
        if total:
            job["progress"] = min(0.99, done / total)
        return 1 if job["cancel"] else 0   # 0 以外を返すと中断する

    res = sd.process(samples, callback=cb).sort_by_start_time()
    ed_jobs.check_cancel(job)
    return [(float(r.start), float(r.end), int(r.speaker)) for r in res]


def diarize_fake(job, total, num, threshold=None):
    """テスト用: 10秒ごとに話者が入れ替わる(行の途中で切り替わる場面も作る)。
    threshold(判別の設定を変えて測るとき)が 1.0 以上で人数が自動なら、全部を 1 人にまとめる(本物も、しきい値を上げるとまとまる)。渡さなければ以前と同じ"""
    n, t, k, turns = (num or (1 if threshold is not None and threshold >= 1.0 else 2)), 0.0, 0, []
    while t < total:
        ed_jobs.check_cancel(job)
        e = min(total, t + 10.0)
        turns.append((t, e, k % n))
        job["progress"] = min(0.99, e / total)
        ed_state.fake_sleep()
        t, k = e, k + 1
    return turns


def assign_speakers(segs, turns, offset):
    """各行に、重なりがいちばん長い話者を割り当てる。戻り値: [(話者番号 or None, 声が混ざっているか, 話者が不確か)]。
    不確か = 短い行(0.8秒未満。声の特徴が取りにくい)、行の半分以上が話者区間の外、または最寄りの区間で代用した行。
    turns は [(開始, 終了, 話者番号)](音声先頭からの秒)、offset を足すと元動画の時刻になる。"""
    return [r[:3] for r in _assign(segs, sorted((a + offset, b + offset, s) for a, b, s in turns))]


def _assign(segs, ts):
    """assign_speakers の本体。ts = [(開始, 終了, 話者番号)](元の動画の秒・開始の順)。
    -> [(話者番号 or None, 声が混ざっているか, 不確か, ratio)]。ratio = 行のうち、その話者の区間に入っている割合(label_ratio と同じ値。
    重なりを数えるときに出ているので、判別の記録・細切れのならしが全区間を数え直さない。最寄りの区間で代用した行は 0)"""
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
            out.append((ranked[0][0], second >= max(1.0, 0.3 * dur), dur < 0.8 or ranked[0][1] / dur < 0.5, min(1.0, ranked[0][1] / dur)))
            continue
        near, best = None, 1.5   # 重なりがなければ、前後1.5秒以内でいちばん近い区間
        for x, y, s in ts[lo:hi + 20]:
            gap = max(x - b, a - y, 0.0)
            if gap < best:
                near, best = s, gap
        out.append((near, False, True, 0.0))
    return out


# ---------- 話者の細切れをならす(S2。2026-10-05。試験中・既定オフ = 設定 diarSmooth・判別の要求の smooth) ----------
# 1 人の話の途中の短い 1 行だけが別の人になり、字幕の色が 1 行だけ変わる(判別の短い区間の揺れ)。行の話者を決めるときだけ、前後と同じ人にする。
# 判別の生の結果(turns・overlaps)は変えない(空の行の下書きが読むため)。記録は diar.json の rows[行 id] に smoothed: true(label は機械の元のラベルのまま)。
# ならす条件(全部): その行が短い(DIAR_SMOOTH_SHORT 未満)・前後の行が同じラベルで、その行だけ違う・前後とのすき間が DIAR_SMOOTH_GAP 以下・
#   根拠が弱い(自分のラベルの区間に入っている割合 ratio が DIAR_SMOOTH_RATIO 未満。最寄りの区間で代用した行は 0)・その行に別の話者の区間の重なり(overlaps)が無い。
# 根拠の弱さに「不確か」(weak)の印そのものは使わない: weak は 0.8 秒未満の行を全部含むので、短い本物の相づち(その人の区間にしっかり入っている)までならしてしまう。
# 前後に数えない行 = 守る行(diar_keep_row = 字幕に出さない・ゲーム音声など・重なりのメモつき・空の下書き)と文字の無い行(どちらも、ならさない)。
# 連続する短い行が 2 行(以上)別の人のときはならさない(まず 1 行だけ。2 行続けば本物の受け答えのことが多い)。ならした行も「話者が不確か」の印を残す(人が見られるように)
DIAR_SMOOTH_SHORT = 1.2   # これより短い行だけ(秒)
DIAR_SMOOTH_GAP = 0.6     # 前後の行とのすき間がこれ以下(秒)
DIAR_SMOOTH_RATIO = 0.6   # 自分のラベルの区間に入っている割合がこれ未満なら根拠が弱い
DIAR_SMOOTH_OVL = 0.1     # 行と overlaps の重なりがこれ以上(秒)なら、同時にしゃべっているのでならさない


def label_ratio(a, b, label, ts):
    """行 [a, b] のうち、ラベル label の区間(ts = [(開始, 終了, ラベル)])に入っている割合(0〜1)。label が None なら 0"""
    if label is None:
        return 0.0
    cover = sum(max(0.0, min(b, y) - max(a, x)) for x, y, s in ts if s == label and x < b and y > a)
    return min(1.0, cover / max(1e-6, b - a))


def smooth_labels(rows, overlaps):
    """ならす行を決める(純粋な関数)。rows = [{"start", "end", "label": 機械のラベル or None, "ratio", "skip": 前後に数えない・ならさない}](文書の行の順)・
    overlaps = [(開始, 終了)](別の話者の区間が重なる所)。-> {行の番号: 前後のラベル}"""
    order = sorted((i for i, r in enumerate(rows) if not r.get("skip")), key=lambda i: (rows[i]["start"], rows[i]["end"]))
    out = {}
    for k in range(1, len(order) - 1):
        p, i, n = rows[order[k - 1]], rows[order[k]], rows[order[k + 1]]
        lb, nb = i.get("label"), p.get("label")
        if lb is None or nb is None or nb != n.get("label") or lb == nb:
            continue
        a, b = i["start"], i["end"]
        if b - a >= DIAR_SMOOTH_SHORT or a - p["end"] > DIAR_SMOOTH_GAP or n["start"] - b > DIAR_SMOOTH_GAP:
            continue
        if (i.get("ratio") or 0.0) >= DIAR_SMOOTH_RATIO:
            continue
        if sum(max(0.0, min(b, y) - max(a, x)) for x, y in overlaps if x < b and y > a) >= DIAR_SMOOTH_OVL:
            continue
        out[order[k]] = nb
    return out


def smooth_speakers(segs, res, ts, keep, ratios=None):
    """判別のあとの行(segs)と assign_speakers の結果(res)から、ならす行 -> {行の番号: ラベル}。ts = [(開始, 終了, ラベル)](元の動画の秒)・keep = 守る行の印。
    ratios = 行ごとの割合(_assign の 4 つ目。無ければ label_ratio で数える)"""
    ratios = ratios or [label_ratio(sg["start"], sg["end"], sp, ts) for sg, (sp, _, _) in zip(segs, res)]
    rows = [{"start": sg["start"], "end": sg["end"], "label": sp, "ratio": r,
             "skip": bool(k) or not str(sg.get("text") or "").strip()} for sg, (sp, _, _), k, r in zip(segs, res, keep, ratios)]
    return smooth_labels(rows, [tuple(x) for x in _turn_overlaps(ts)])


def diar_smooth_setting():
    """設定 diarSmooth(既定オフ)"""
    return ed_learn.load_settings().get("diarSmooth") is True


# ---------- 判別の記録(transcripts/<id>.diar.json。Q2。plan/line-bc-master-plan.md) ----------
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
    return ed_state.read_schema_json(diar_path(tid), MAX_DIAR_BYTES, DIAR_SCHEMA, "latest", dict)


def _diar_put(tid, d):
    ed_state.atomic_write(diar_path(tid), json.dumps(d, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))


def write_diar(tid, run):
    """run を最新として書く。前の最新は history の先頭へ(DIAR_KEEP 回まで)"""
    with _diar_lock:
        old = read_diar(tid)
        hist = ([old["latest"]] + [h for h in old.get("history") or [] if isinstance(h, dict)]) if old else []
        _diar_put(tid, {"schema": DIAR_SCHEMA, "latest": run, "history": hist[:DIAR_KEEP - 1]})


@contextlib.contextmanager
def _diar_edit(tid):
    """判別の記録を読んで(無い・壊れていれば None)、書き換えさせてから書く(_diar_lock の中。None なら書かない・途中で例外なら書かない)"""
    with _diar_lock:
        d = read_diar(tid)
        yield d
        if d:
            _diar_put(tid, d)


def _label_of(latest):
    """labelMap の逆引き {話者の id: 機械のラベル(数なら int)}"""
    return {v: (int(k) if str(k).isdigit() else k) for k, v in (latest.get("labelMap") or {}).items()}


def update_diar_voices(tid, voices):
    """最新の回の「覚えた声との照合」を書く(話者のラベルは labelMap から付ける)。判別の記録が無ければ何もしない"""
    with _diar_edit(tid) as d:
        if not d:
            return False
        inv = _label_of(d["latest"])
        for sid, one in (voices.get("speakers") or {}).items():
            one["label"] = inv.get(sid)
        d["latest"]["voices"] = voices
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
    return [[round(a, 2), round(b, 2)] for a, b in ed_state.union_spans(raw)[:MAX_DIAR_OVERLAPS] if b - a > 0.01]


def build_diar_run(segs, res, turns, offset, requested, emb, idmap, auto=None, smoothed=None, ratios=None):
    """判別の1回分の記録。時刻は元動画の秒(行と同じ)。rows[行の id] = {"label": 機械が割り当てたラベル, "speaker": 付けた話者の id,
    "ratio": その行のうち、そのラベルの区間に入っている割合, "mixed": 声が混ざっている印, "weak": 不確かの印}。
    auto = 文字起こしのあとの自動の判別のとき {"eval": 評価用か, "contextName": 名前の候補 or None}(v0.50.0。人が始めた判別では書かない)。
    smoothed = 細切れをならしたとき {行の番号: ならしたあとのラベル}(S2。None = ならしていない)。ならした行は "smoothed": true・"weak": true・
    label は元のラベルのまま・speaker はならしたあと。ならした回は latest.smooth = {"on", "rows", "short", "gap", "ratio"}(ならしていない回は持たない)。
    ratios = 行ごとの割合(_assign の 4 つ目。無ければ label_ratio で数える)"""
    ts = sorted((a + offset, b + offset, s) for a, b, s in turns)
    rows = {}
    for i, (sg, (sp, mixed, weak)) in enumerate(zip(segs, res)):
        r = ratios[i] if ratios is not None else label_ratio(sg["start"], sg["end"], sp, ts)
        one = {"label": sp, "speaker": idmap.get(sp, ""), "ratio": round(r, 3), "mixed": bool(mixed), "weak": bool(weak)}
        if smoothed and i in smoothed:
            one.update({"speaker": idmap.get(smoothed[i], ""), "smoothed": True, "weak": True})
        rows[str(sg.get("id"))] = one
    return {"at": int(time.time() * 1000), "engine": _diar_engine(emb, requested), "offset": round(float(offset), 3),
            "turns": [{"start": round(a, 2), "end": round(b, 2), "label": s} for a, b, s in ts],
            "overlaps": _turn_overlaps(ts), "labelMap": {str(k): v for k, v in idmap.items()}, "speakers": len(idmap), "rows": rows,
            "voices": {"checked": False}, **({"auto": auto} if auto else {}),
            **({"smooth": {"on": True, "rows": len(smoothed), "short": DIAR_SMOOTH_SHORT, "gap": DIAR_SMOOTH_GAP, "ratio": DIAR_SMOOTH_RATIO}} if smoothed is not None else {})}


def _record_diar(tid, run):
    try:
        write_diar(tid, run)
    except Exception as e:   # 記録が書けなくても判別の結果は残す
        ed_state.log.warning("判別の記録を書けませんでした: %s %s", e.__class__.__name__, str(e)[:150])


def apply_diarization(tid, turns, offset, requested, emb=DIAR_EMB_DEFAULT, auto=None, smooth=False):
    """最新の文字起こしを読み直して話者を書き込む(判別中に行を編集されていても、時刻で割り当てるので矛盾しない)。
    読み直し〜書き込みは保存と同じロックの中で行う(間に画面の保存が挟まると、その保存が黙って上書きされるため)。
    auto(文字起こしのあとの自動の判別。v0.50.0)なら文書の diarization と diar.json に印を残す(画面の「自動で付けた」の案内・人の最終との比べ)。
    smooth = 短い 1 行だけ別の人になるのをならす(S2。smooth_speakers。行の話者だけ。turns・overlaps はそのまま記録する)"""
    with ed_store._save_lock:
        return _apply_diarization(tid, turns, offset, requested, emb, auto, smooth)


def _spk_ids(doc):
    """文書の話者の id の集まり(文字列)"""
    return {str(s.get("id")) for s in doc.get("speakers") or [] if isinstance(s, dict) and s.get("id")}


def diar_keep_row(g, ids):
    """話者判別のやり直し・1人指定・「全行をこの人に」で話者を変えない行(2026-10-05): 字幕に出さない行(noSub)・
    組み込みの話者「ゲーム音声など」の行・音のメモ「声が重なる」(overlap)が付いていて話者のある行(手で作った重なる行を守る)・
    機械の下書きのままの空の行(重なりの所に置いた行。判別は行を作り直さないので、そのまま残して話者も変えない。話者なしの下書きを主の話者で埋めない)。
    ids = 文書の話者の id の集まり(無い id の話者は守らない)"""
    if not isinstance(g, dict):
        return False
    sp = str(g.get("speaker") or "")
    if ed_state.no_sub_row(g) or sp == ed_state.OTHER_SPK_ID or ed_state.blank_draft_row(g):
        return True
    return bool(sp) and sp in ids and "overlap" in (g.get("tags") if isinstance(g.get("tags"), list) else [])


def _diar_kept_speakers(doc, segs, keep, taken):
    """守った行の話者を、判別のあとの話者の一覧に残す。taken = 新しい話者の id(重なれば守った方の id を付け替える)。
    -> ([残す話者], {古い id: 新しい id})。組み込みの話者は id を変えない(決まった id)"""
    old = [s for s in doc.get("speakers") or [] if isinstance(s, dict) and s.get("id")]
    used = {str(g.get("speaker") or "") for g, k in zip(segs, keep) if k and g.get("speaker")}
    out, remap, have = [], {}, set(taken)
    for s in old:
        sid = str(s["id"])
        if sid not in used:
            continue
        nid, n = sid, 0
        if sid != ed_state.OTHER_SPK_ID:
            while nid in have or nid == ed_state.OTHER_SPK_ID:   # 例: 守った行の「S2」→「S2p」(新しい判別の S2 とは別の人)
                n += 1
                nid = sid[:8] + "p" + (str(n) if n > 1 else "")
        have.add(nid)
        remap[sid] = nid
        out.append(dict(s, id=nid))
    out.sort(key=lambda s: s.get("id") == ed_state.OTHER_SPK_ID)   # 組み込みの話者は最後(Alt+数字の番号に入らない)
    return out, remap


def _apply_diarization(tid, turns, offset, requested, emb, auto=None, smooth=False):
    doc = ed_store.read_transcript(tid)
    dropped = ed_fill.fill_clean_turns(doc, turns, offset)   # 定型の幻覚で声の区間と重ならない行を捨てる(autoFill の文書だけ。0.60.0)
    segs = doc.get("segments") or []
    ids = _spk_ids(doc)
    keep = [diar_keep_row(g, ids) for g in segs]   # 手で決めた行(字幕に出さない・ゲーム音声など・重なりのメモつき)は話者を変えない
    ts = sorted((a + offset, b + offset, s) for a, b, s in turns)   # 元の動画の秒(割り当て・ならし・記録で同じ並び)
    full = _assign(segs, ts)
    raw, ratios = [r[:3] for r in full], [r[3] for r in full]
    smoothed = smooth_speakers(segs, raw, ts, keep, ratios) if smooth else None
    res = [(smoothed[i], r[1], True) if smoothed and i in smoothed else r for i, r in enumerate(raw)]   # ならした行は「不確か」の印を残す
    spent = {}
    for sg, (sp, _, _), k in zip(segs, res, keep):
        if sp is not None and not k:
            spent[sp] = spent.get(sp, 0.0) + max(0.0, sg["end"] - sg["start"])
    order = sorted(spent, key=lambda k: -spent[k])[:MAX_SPEAKERS]   # 話した時間が長い人から「話者1」「話者2」…
    idmap = {raw: "S%d" % (i + 1) for i, raw in enumerate(order)}
    speakers = [{"id": "S%d" % (i + 1), "name": "話者%d" % (i + 1), "color": SPK_COLORS[i % len(SPK_COLORS)]} for i in range(len(order))]
    kept_sps, remap = _diar_kept_speakers(doc, segs, keep, set(idmap.values()))
    speakers += kept_sps
    unsure = 0
    for sg, (sp, mixed, weak), k in zip(segs, res, keep):
        if k:   # 守った行: 話者(付け替えた id)も印もそのまま
            if sg.get("speaker"):
                sg["speaker"] = remap.get(str(sg["speaker"]), sg["speaker"])
            continue
        sg["speaker"] = idmap.get(sp, "")
        parts = [x for x in str(sg.get("flag", "")).split("、") if x and x not in ed_jobs.SPK_FLAGS]
        mark = ed_state.NONE_FLAG if not sg["speaker"] else ed_state.MIXED_FLAG if mixed else ed_state.WEAK_FLAG if weak else ""
        if mark:
            parts.append(mark)
            unsure += 1
        sg["flag"] = "、".join(parts)[:100]
    ed_store.backup_doc(tid, "diarize")   # 直前の状態を1世代だけ残す・履歴にも残す(画面の「履歴」から戻せる)
    doc.update({"speakers": speakers, "segments": segs, "updatedAt": int(time.time() * 1000),
                "diarization": dict({"engine": "sherpa-onnx", "embedding": emb, "requested": requested, "found": len(order), "unsure": unsure, "at": int(time.time() * 1000)},
                                    **({"auto": True} if auto else {}), **({"smoothed": len(smoothed)} if smoothed is not None else {}),
                                    **({"fillDropped": dropped} if dropped else {}))})
    ed_store.write_doc(tid, doc)
    _record_diar(tid, build_diar_run(segs, raw, turns, offset, requested, emb, idmap, auto, smoothed, ratios))   # 機械の最初の結果(人が直す前)を <id>.diar.json に
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
    if ed_jobs.tid_busy(tid, ed_jobs.EXCLUSIVE["diarize"]):
        raise ed_state.ApiError("busy", "この文字起こしは、すでに別の処理(話者判別・再認識)の最中です", 409)
    emb = str(req.get("embedding") or DIAR_EMB_DEFAULT)
    names = []   # 出てくる人の名前(友人からの依頼の「話す人」。2026-10-01)
    for x in req.get("names") if isinstance(req.get("names"), list) else []:
        s = str(x or "").strip()[:60] if isinstance(x, str) else ""
        if s and not any(ord(ch) < 32 for ch in s) and s not in names and not DEFAULT_SPK_NAME.match(s):
            names.append(s)
    return {"tid": tid, "numSpeakers": n if 1 <= n <= 10 else 0, "names": names[:10], "embedding": emb if emb in DIAR_EMBS else DIAR_EMB_DEFAULT, "title": ed_jobs.job_title("話者判別: ", doc),
            "recognize": req.get("recognize") is not False,   # A-3: 覚えている声と照らし合わせる(既定オン)
            "smooth": req["smooth"] if isinstance(req.get("smooth"), bool) else diar_smooth_setting()}   # S2: 細切れをならす(要求に無ければ設定 diarSmooth。既定オフ)


def single_speaker(tid, name):
    """話す人が1人: 判別せずに全部の行をその人に(名前が無ければ「話者1」)。-> 行の数。
    手で決めた行(diar_keep_row = 字幕に出さない・ゲーム音声など・重なりのメモつき)は話者を変えない(2026-10-05)"""
    with ed_store._save_lock:
        doc = ed_store.read_transcript(tid)
        segs = doc.get("segments") or []
        ids = _spk_ids(doc)
        keep = [diar_keep_row(g, ids) for g in segs]
        kept_sps, remap = _diar_kept_speakers(doc, segs, keep, {"S1"})
        same = _spk_name_key(name or "話者1")
        for s in [s for s in kept_sps if s.get("id") != ed_state.OTHER_SPK_ID and _spk_name_key(s.get("name")) == same]:   # 同じ名前の人は 1 人にまとめる
            remap.update({k: "S1" for k, v in remap.items() if v == s["id"]})
            kept_sps.remove(s)
        for sg, k in zip(segs, keep):
            if k:
                if sg.get("speaker"):
                    sg["speaker"] = remap.get(str(sg["speaker"]), sg["speaker"])
                continue
            sg["speaker"] = "S1"
            sg["flag"] = "、".join(x for x in str(sg.get("flag", "")).split("、") if x and x not in ed_jobs.SPK_FLAGS)[:100]
        ed_store.backup_doc(tid, "diarize")
        doc.update({"speakers": [{"id": "S1", "name": name or "話者1", "color": SPK_COLORS[0]}] + kept_sps, "segments": segs, "updatedAt": int(time.time() * 1000),
                    "diarization": {"engine": "single", "requested": 1, "found": 1, "unsure": 0, "at": int(time.time() * 1000)}})
        ed_store.write_doc(tid, doc)
        _record_diar(tid, {"at": int(time.time() * 1000), "engine": {"name": "single", "requested": 1}, "offset": 0.0, "turns": [], "overlaps": [],
                           "labelMap": {"0": "S1"}, "speakers": 1,
                           "rows": {str(sg.get("id")): {"label": 0, "speaker": "S1", "ratio": 1.0, "mixed": False, "weak": False} for sg in segs},
                           "voices": {"checked": False, "speakers": {"S1": {"label": 0, "decided": name, "by": "request", "reason": None}} if name else {}}})
        return len(segs)


def run_diarize(job):
    spec = job["spec"]
    if spec.get("auto") and autodiar_skip_at_start(job):   # 自動の判別: 待っている間に人が話者を付けた・確かめ済みにしたなら何もしない(v0.50.0)
        return
    if spec.get("numSpeakers") == 1:   # 1人なら判別しない(音声も取り出さない)
        try:
            single_speaker(spec["tid"], (spec.get("names") or [""])[0])
            job["speakers"], job["unsure"] = 1, 0
            job["named"] = [{"speaker": "S1", "name": spec["names"][0], "score": None}] if spec.get("names") else []
            ed_jobs.job_done(job, spec["tid"])
        except Exception as e:
            job["state"], job["error"], job["phase"] = "error", "話者を付けられませんでした: %s %s" % (e.__class__.__name__, str(e)[:150]), "失敗"
        return
    with ed_jobs.job_temp_wav(job) as wav:
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
        ed_jobs.check_cancel(job)
        auto = {"eval": bool(spec.get("autoEval")), "contextName": spec.get("contextName") or None} if spec.get("auto") else None
        job["speakers"], job["unsure"] = apply_diarization(spec["tid"], turns, start, spec["numSpeakers"], spec["embedding"], auto, bool(spec.get("smooth")))
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
        ed_jobs.job_done(job, spec["tid"])


# ---------- 重なりの所の空の行の下書き(2026-10-05。plan/line-b-overlap.md の 5-3 の C・6-2 の 1・2) ----------
# 同時にしゃべっている所は、認識が片方しか書かない。判別の記録(diar.json の latest)には、声があったのに行が付かなかった区間が残るので、
# そこを「時刻(と分かれば話者)を入れた空の行」の候補にする。ここは候補を数えるだけ(文書も diar.json も書かない)。行を足すのは画面(元に戻すが効く・保存はいつもの道)。
# 候補 = 判別の声の区間(同じラベルの区間はすき間 OVDRAFT_JOIN 以下でつなぐ)のうち、主の話者(区間の合計がいちばん長いラベル)でないもの:
#   (a) labelMap に無いラベル(行が 1 つも付かなかった声)→ speaker ""(誰か分からない)・why "unassigned"
#   (b) labelMap にあるラベルで、ほかの話者の区間と重なる(overlaps に入る部分がある)→ speaker = その話者の id・why "overlap"
# 区間の半分以上が「書いてある」(下の _ovdraft_cover_rows)なら出さない = 2 回押しても増えない。出す区間は、両端の書いてある所を削る(同じ話者の行と重ねて赤くしない)。
# 時刻は元の動画の秒(build_diar_run が offset を足して書く)= 行を直したあとの文書にもそのまま使える
OVDRAFT_JOIN = 0.3    # 同じラベルの区間をつなぐすき間(秒)
OVDRAFT_MIN = 0.5     # これより短い区間は出さない(短い相づちは数が多く当たりも悪いので、最初は出さない)
OVDRAFT_MAX = 40      # 1 回に出す数(開始の順。超えた数は more)
OVDRAFT_COVER = 0.5   # 区間のこの割合以上が書いてあれば出さない
OVDRAFT_KIND = "overlap"   # 置いた行の印 draft の値(ed_state.ROW_DRAFT_KINDS の 1 つ)
# 抜け(why "missing"。計画 第2版 E2 の前倒し): 主の話者も含めて、どのラベルの声の区間でも、書いてある所(文字のある行は話者によらず・空の下書き・字幕に出さない行・
# ゲーム音声などの行)と、先に出した重なりの候補を除いた残り。区間の中のすき間(1 人の話の途中で認識が落とした所)も拾うため、区間ごとの「半分以上」ではなく、
# 書いてある所を引いた残りの切れ端ごとに見る。違うラベルの切れ端が重なればつなぐ(話者は長い方)。置いた行の印は OVDRAFT_MISS_KIND(音のメモ overlap は付けない)
OVDRAFT_MISS_MIN = 0.8     # 抜けの切れ端の最短(秒)。息・相づち・行の端の余りを出さない(本物のデータで 0.5・0.8・1.2 を数えて決めた。docs は WORKLOG)
OVDRAFT_MISS_KIND = "missing"
OVDRAFT_GROUPS = ("overlap", "missing")   # 画面で選べるまとまり: overlap = 重なり(why overlap・unassigned)・missing = 抜け
OVDRAFT_REASONS = {
    "no_diar": "話者の判別の記録がありません(「話者を自動で判別」のあとで使えます)",
    "single": "1 人として付けた判別なので、声の区間の記録がありません(人数を「自動」か 2 人以上で判別すると使えます)",
    "no_turns": "判別の記録に声の区間がありません",
}


def _ovdraft_union(spans):
    """[(開始, 終了)] をつなげて開始の順に(重なる・接するものは 1 つに。長さの無い区間は捨てる)"""
    return ed_state.union_spans((a, b) for a, b in spans if b > a)


def _ovdraft_covered(a, b, union):
    return sum(max(0.0, min(b, y) - max(a, x)) for x, y in union if x < b and y > a)


def _ovdraft_trim(a, b, union):
    """両端が書いてある所に入っていれば、その外まで縮める(真ん中の書いてある所はそのまま)"""
    for x, y in union:
        if x <= a < y:
            a = y
    for x, y in reversed(union):
        if x < b <= y:
            b = x
    return a, b


def _ovdraft_cover_rows(segs, ids, speaker):
    """候補の区間を「書いてある」とみなす行の時間(つなげたもの)。speaker = None なら行の付かなかった声(a)、id ならその話者(b)。
    どちらも: 機械の下書きのままの空の行(話者によらず。置いた所)・字幕に出さない行・「ゲーム音声など」の行(別の声として書いてある)。
    (a): 文字のある行のうち、話者の無い行(文書に無い id を含む)と、判別のやり直しで守る行(diar_keep_row = 声が重なるのメモつきの話者のある行)。
    (b): 文字のある行のうち、その話者の行"""
    spans = []
    for g in segs:
        if not isinstance(g, dict):
            continue
        a, b = ed_state.num(g.get("start")), ed_state.num(g.get("end"))
        if a is None or b is None or b <= a:
            continue
        if ed_state.blank_draft_row(g):
            spans.append((a, b))
            continue
        if not str(g.get("text") or "").strip():
            continue
        sp = str(g.get("speaker") or "")
        if ed_state.no_sub_row(g) or sp == ed_state.OTHER_SPK_ID:
            spans.append((a, b))
        elif speaker is None:
            if sp not in ids or diar_keep_row(g, ids):
                spans.append((a, b))
        elif sp == speaker:
            spans.append((a, b))
    return _ovdraft_union(spans)


def ovdraft_candidates(doc, latest, kinds=None):
    """文書(今の行・話者)と diar.json の latest から、空の行の候補。読むだけ。kinds = 出すまとまり(OVDRAFT_GROUPS の部分。None は全部)。
    -> {"items": [{start, end, speaker: 話者の id か "", label, why: "unassigned" | "overlap" | "missing", draft: 置く行の印}](開始の順・選んだまとまりで OVDRAFT_MAX まで),
        "more": 超えた数, "counts": {"overlap": 重なり(why overlap・unassigned)の数, "missing": 抜けの数}(kinds によらず全部・上限の前),
        "reason": 出せない理由(文) か None, "reasonCode": no_diar | single | no_turns | None}。
    同じ所は二重に出さない(重なり overlap → unassigned → 抜け missing の順に決める)"""
    def empty(code):
        return {"items": [], "more": 0, "counts": {g: 0 for g in OVDRAFT_GROUPS}, "reason": OVDRAFT_REASONS[code], "reasonCode": code}
    if not isinstance(latest, dict):
        return empty("no_diar")
    eng = latest.get("engine") if isinstance(latest.get("engine"), dict) else {}
    if eng.get("name") == "single":
        return empty("single")
    turns = []
    for t in latest.get("turns") or []:
        if not isinstance(t, dict) or t.get("label") is None:
            continue
        a, b = ed_state.num(t.get("start")), ed_state.num(t.get("end"))
        if a is not None and b is not None and b > a:
            turns.append((a, b, t["label"]))
    if not turns:
        return empty("no_turns")
    lmap = {str(k): str(v) for k, v in (latest.get("labelMap") or {}).items() if v} if isinstance(latest.get("labelMap"), dict) else {}
    ovl = _ovdraft_union((ed_state.num(x[0]), ed_state.num(x[1])) for x in latest.get("overlaps") or []
                         if isinstance(x, (list, tuple)) and len(x) >= 2 and ed_state.num(x[0]) is not None and ed_state.num(x[1]) is not None)
    total = {}
    for a, b, lb in turns:
        total[str(lb)] = total.get(str(lb), 0.0) + (b - a)
    main = max(total, key=lambda k: total[k])   # 主の話者(ほかの声が乗っているだけの側。書かれている側なので出さない)
    joined = []   # [(開始, 終了, ラベル)] 同じラベルの区間をつないだもの
    for lb in total:
        if lb != main:
            joined += [tuple(j) for j in _join_label_spans(sorted(t for t in turns if str(t[2]) == lb))]
    lo = ed_state.num(doc.get("start"), 0.0) or 0.0
    hi = ed_state.num(doc.get("end"))
    dur = ed_state.num(doc.get("duration"))
    hi = min(x for x in (hi, dur, float("inf")) if x is not None and x > 0)
    segs = [g for g in doc.get("segments") or [] if isinstance(g, dict)]
    ids = _spk_ids(doc)
    covers = {}
    items = []
    for a, b, lb in sorted(joined):
        a, b = max(a, lo), min(b, hi)
        if b - a < OVDRAFT_MIN:
            continue
        sp = lmap.get(str(lb))
        if sp is not None and _ovdraft_covered(a, b, ovl) <= 0.01:   # (b) は、ほかの話者の区間と重なっている声だけ
            continue
        if sp not in covers:   # (a) は None
            covers[sp] = _ovdraft_cover_rows(segs, ids, sp)
        union = covers[sp]
        if _ovdraft_covered(a, b, union) >= OVDRAFT_COVER * (b - a):
            continue
        a2, b2 = _ovdraft_trim(a, b, union)
        if b2 - a2 < OVDRAFT_MIN:
            continue
        items.append({"start": round(a2, 2), "end": round(b2, 2), "speaker": sp if sp in ids else "", "label": lb,
                      "why": "unassigned" if sp is None else "overlap", "draft": OVDRAFT_KIND})
    items += _ovdraft_missing(turns, lmap, ids, segs, items, lo, hi)
    counts = {g: sum(1 for x in items if _ovdraft_group(x) == g) for g in OVDRAFT_GROUPS}
    want = set(OVDRAFT_GROUPS if kinds is None else [k for k in kinds if k in OVDRAFT_GROUPS])
    items = sorted((x for x in items if _ovdraft_group(x) in want), key=lambda x: (x["start"], x["end"]))
    return {"items": items[:OVDRAFT_MAX], "more": max(0, len(items) - OVDRAFT_MAX), "counts": counts, "reason": None, "reasonCode": None}


def _join_label_spans(ts):
    """同じラベルの区間 ts = [(開始, 終了, ラベル)](開始の順)を、すき間 OVDRAFT_JOIN 以下でつなぐ -> [[開始, 終了, 最初のラベル]]。
    重なりの候補(ovdraft_candidates)と抜けの候補(_ovdraft_missing)が同じつなぎ方を使う"""
    out = []
    for a, b, x in ts:
        if out and a - out[-1][1] <= OVDRAFT_JOIN:
            out[-1][1] = max(out[-1][1], b)
        else:
            out.append([a, b, x])
    return out


def _ovdraft_group(x):
    return "missing" if x.get("why") == "missing" else "overlap"


def _ovdraft_cover_any(segs):
    """抜けの覆い: 文字のある行(話者によらない)・機械の下書きのままの空の行・字幕に出さない行・ゲーム音声などの行"""
    spans = []
    for g in segs:
        a, b = ed_state.num(g.get("start")), ed_state.num(g.get("end"))
        if a is None or b is None or b <= a:
            continue
        if (str(g.get("text") or "").strip() or ed_state.blank_draft_row(g) or ed_state.no_sub_row(g)
                or str(g.get("speaker") or "") == ed_state.OTHER_SPK_ID):
            spans.append((a, b))
    return _ovdraft_union(spans)


def _ovdraft_cut(a, b, union, ends=None):
    """[a, b] から union(開始の順・重ならない)を引いた残り [(開始, 終了)]。ends = union の終わりの並び(渡せば二分探索で始める。長い文書でも重くしない)"""
    out, cur = [], a
    for k in range(bisect.bisect_right(ends, a) if ends is not None else 0, len(union)):
        x, y = union[k]
        if x >= b:
            break
        if y <= cur:
            continue
        if x > cur:
            out.append((cur, x))
        cur = max(cur, y)
        if cur >= b:
            break
    if cur < b:
        out.append((cur, b))
    return out


def _ovdraft_missing(turns, lmap, ids, segs, prior, lo, hi):
    """抜けの候補(why missing)。turns = [(開始, 終了, ラベル)]・prior = 先に決めた重なりの候補(同じ所は二重に出さない)。
    ラベルごとに区間をつなぎ(OVDRAFT_JOIN)、書いてある所と prior を引いた切れ端を、違うラベルどうしで重なればつないで、OVDRAFT_MISS_MIN 以上を出す"""
    cover = _ovdraft_union(_ovdraft_cover_any(segs) + [(x["start"], x["end"]) for x in prior])
    ends = [y for _, y in cover]
    by_label = {}
    for t in sorted(turns):
        by_label.setdefault(str(t[2]), []).append(t)
    pieces = []   # [(開始, 終了, ラベル)]
    for ts in by_label.values():
        for a, b, x in _join_label_spans(ts):
            pieces += [(p, q, x) for p, q in _ovdraft_cut(max(a, lo), min(b, hi), cover, ends)]
    groups = []   # [[開始, 終了, {ラベル: 秒}]]
    for a, b, lb in sorted((p for p in pieces if p[1] > p[0]), key=lambda p: (p[0], p[1], str(p[2]))):
        if groups and a < groups[-1][1]:
            g = groups[-1]
            g[1] = max(g[1], b)
            g[2][lb] = g[2].get(lb, 0.0) + (b - a)
        else:
            groups.append([a, b, {lb: b - a}])
    out = []
    for a, b, secs in groups:
        if b - a < OVDRAFT_MISS_MIN:
            continue
        best = max(secs, key=lambda k: (secs[k], str(k)))
        sp = lmap.get(str(best))
        out.append({"start": round(a, 2), "end": round(b, 2), "speaker": sp if sp in ids else "", "label": best, "why": "missing", "draft": OVDRAFT_MISS_KIND})
    return out


def ovdraft_for_doc(tid, kinds=None):
    """GET /api/overlap-drafts?id=&kinds= : 保存済みの文書と判別の記録で候補を数える(読むだけ)。文書が無ければ 404。
    kinds = 「,」区切りのまとまり(overlap・missing。無い・空なら全部。知らない名前は捨てる)。
    -> ovdraft_candidates の結果 + "diarAt"(判別の時刻。記録が無ければ None)"""
    doc = ed_store.read_transcript(tid)
    d = read_diar(tid)
    latest = d["latest"] if d else None
    ks = None if kinds is None or not str(kinds).strip() else [k.strip() for k in str(kinds)[:100].split(",")]
    out = ovdraft_candidates(doc, latest, ks)
    out["diarAt"] = latest.get("at") if latest else None
    return out


# ---------- 文字起こしのあと、話者を自動で判別する(v0.50.0。評価用は常に・それ以外は設定 autoDiarize) ----------
# 評価ドリルでは全行に話者が要る(評価用のフォルダの「メンバーのフォルダへ移す」条件)ので、評価用の文字起こしのあとは必ず判別のジョブを足し、
# 覚えた声で名前が付かなかった(仮の名前 話者n の)話者のうち、話した秒がいちばん長い人に「動画の手がかり」の名前
# (ed_drill.drill_candidates の suggest = 覚えた声 → 動画の入ったメンバーのフォルダ → 配信の文脈)を付ける。新しい認識の道は作らない(今の diarize のジョブ)。
# 人が付けたものは置き換えない: 文字のある行に1つでも話者があれば何もしない(足すときと、ジョブが動き出すときの両方で確かめる)。
# 判別の部品(sherpa-onnx)が無いときは黙って飛ばす(ログだけ。文字起こしは失敗にしない)。名前は serve.py からも見える(autodiar_ / AUTODIAR_ で始める)
AUTODIAR_BY = "context"   # diar.json の voices の by(動画の手がかりで付けた。覚えた声 = threshold・消去法 = elimination・依頼 = request と並べる)


def autodiar_enabled():
    """環境変数 TRANSCRIBE_AUTO_DIARIZE=off で自動の判別をしない(テスト・困ったとき用。評価用の決まりは変えない)"""
    return not ed_state.env_off("TRANSCRIBE_AUTO_DIARIZE")


def autodiar_ready():
    """判別の部品があるか(疑似のときは常に)。サーバー側では sherpa-onnx を読み込まない(has_sherpa はワーカー側で調べる)。
    テスト用の worker-fake(ワーカーの中だけ偽のモデル)では使わない(判別は本物の経路 = モデルの取得になるため)"""
    if ed_state.backend_name() == "fake":
        return True
    return not ed_state.worker_fake() and has_sherpa()


def autodiar_why_not(doc):
    """自動で判別しない理由(None = 判別してよい): empty(文字のある行が無い)・reviewed(評価用で確かめ済み)・
    has_speakers(文字のある行に話者がある = 人か前の判別が付けた。置き換えない)"""
    ids = {s.get("id") for s in doc.get("speakers") or [] if isinstance(s, dict) and s.get("id")}
    rows = [g for g in doc.get("segments") or [] if isinstance(g, dict) and str(g.get("text") or "").strip()]
    if not rows:
        return "empty"
    if doc.get("evalSet") is True and isinstance(doc.get("evalReviewed"), dict):
        return "reviewed"
    if any(g.get("speaker") in ids and not diar_keep_row(g, ids) for g in rows):   # 守る行(ゲーム音声など・字幕に出さない・重なりのメモ)は判別で変わらないので数えない
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
    st = ed_learn.load_settings()   # 判別モデルと「細切れをならす」(diarSmooth)を 1 回で読む
    spec = validate_diarize({"tid": tid, "numSpeakers": 0, "recognize": True, "embedding": st.get("diarEmb"), "smooth": st.get("diarSmooth") is True})
    spec.update({"auto": True, "autoEval": ev, "contextName": name,
                 "title": ed_jobs.job_title("話者判別(自動): ", doc)})
    if batch:
        spec["evalBatch"] = True
    return {"job": ed_jobs.add_job(spec, "diarize"), "name": name}


def autodiar_after_transcribe(job, spec, tid):
    """文字起こしのジョブ(ed_jobs.run_job)の終わり。文書を書いたあと・「完了」にする前に呼ぶ(ドリルが判別の前の文書を開かないよう、間を空けない)。
    評価用は常に・それ以外は設定 autoDiarize。始められなくても文字起こしは成功のまま(job["warnings"])"""
    if not (spec.get("evalSet") or spec.get("autoDiarize")):
        return
    try:
        r = autodiar_enqueue(tid, batch=bool(spec.get("evalBatch")))
        if r.get("skipped") == "no_sherpa" and not spec.get("evalSet"):   # 設定でオンにした人には知らせる(評価用は黙って飛ばす = 人が「全行をこの人に」)
            ed_state.add_warning(job, "話者の判別の部品(sherpa-onnx)が入っていないため、話者は自動で判別しませんでした")
    except ed_state.ApiError as e:
        ed_state.add_warning(job, "話者の自動判別を始められませんでした: " + e.message)
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
    ed_jobs.job_done(job, spec["tid"], "判別しませんでした(" + {"has_speakers": "話者が付いていました", "reviewed": "確かめ済みです", "empty": "文字のある行がありません"}.get(why, why) + ")")
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
            if isinstance(g, dict) and g.get("speaker") and str(g.get("text") or "").strip() and not ed_state.no_sub_row(g):   # 字幕に出さない行(ゲームの声など)は話した秒に数えない
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
            ed_store.write_doc(tid, doc)
    _autodiar_record(tid, nm, hit, reason)
    return hit


def _autodiar_record(tid, name, hit, reason):
    """diar.json の最新の voices に、動画の手がかりで付けた名前(speakers[id].by = context)と経過 context = {name, speaker, reason} を書く。
    人の最終(行の speaker・speakers[].name)と、機械が付けた名前を後で比べられるように。書けなくても名前付けは続ける"""
    try:
        with _diar_edit(tid) as d:
            if not d:
                return
            latest = d["latest"]
            v = latest.get("voices") if isinstance(latest.get("voices"), dict) else {"checked": False}
            sp = v.get("speakers") if isinstance(v.get("speakers"), dict) else {}
            if hit:
                one = sp.get(hit["speaker"]) if isinstance(sp.get(hit["speaker"]), dict) else dict(_VOICE_EMPTY, label=_label_of(latest).get(hit["speaker"]))
                one.update({"decided": hit["name"], "by": AUTODIAR_BY, "reason": None})
                sp[hit["speaker"]] = one
            v["speakers"] = sp
            v["context"] = {"name": name, "speaker": hit["speaker"] if hit else None, "reason": reason}
            latest["voices"] = v
    except Exception as e:
        ed_state.log.warning("動画の手がかりの名前の記録を書けませんでした: %s %s", e.__class__.__name__, str(e)[:150])


# ---------- 話者の声を覚える(A-3。git の履歴(679ff01 以前)の docs/archive/backlog-ui-2026-09-27.md) ----------
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
                               "話者", "speaker", "スピーカー", ed_state.OTHER_SPK_NAME))   # 組み込みの「ゲーム音声など」も人の名前ではない(覚えない・照らし合わせない)
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
    d = _fsio.read_json_or(voices_path(emb), None, kind=dict)
    v = d.get("voices") if d is not None else None
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
    if worker_client.IN_WORKER:
        return _embed_local(job, wav, emb, rel)
    res = worker_client.WORKER.call("embed", {"wav": wav, "emb": emb, "groups": rel}, job)
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
    samples, sr = worker_client.read_wav_f32(wav), 16000
    total, done, out = max(1, sum(len(g) for g in groups)), 0, []
    for g in groups:
        vecs, weights = [], []
        for a, b in g:
            ed_jobs.check_cancel(job)
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


_VOICE_EMPTY = {"top": None, "score": None, "second": None, "secondScore": None, "decided": None, "by": None, "reason": None}   # 話者ごとの照合の経過の空の形(使うときは dict(...) で写す)


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
        d = info[sid] = dict(_VOICE_EMPTY)
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
        grp = voice_groups(doc.get("segments") or [], lambda g: "" if ed_state.no_sub_row(g) or g.get("speaker") == ed_state.OTHER_SPK_ID else (g.get("speaker") or ""))   # ゲーム音声など・字幕に出さない行は照らし合わせない
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
                d = dict(detail.get(s.get("id")) or dict(_VOICE_EMPTY, reason="no_voices" if not voices else "no_rows"))
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
            ed_store.write_doc(tid, doc)
    record(doc, named)
    return named


VOICE_LEARN_TAGS = ("overlap", "bgm", "unclear")   # この印の行は覚えない(声が重なる・BGM が大きい・聞き取れない。監査17)
EVAL_SET_VOICE_MSG = "評価用の文字起こしでは声を覚えません(評価用のデータを、ほかの文書の話者の名前付けに使わないため)。評価用を外してから行ってください"


def voice_learn_plan(doc):
    """声を覚えるときに使う行(監査17。段1): voice_groups の条件(1秒以上・声が混ざっていない)に加えて、校正済みで、音のメモ(重なり・BGM・聞き取れない)が無い行だけ。
    話者判別のときの照らし合わせ(recognize_voices)は voice_groups のまま(校正前の文書でも名前が付くように。変えない決定)。
    -> {"groups": {名前: ([(開始, 終了)...], 秒)}, "speakers": {名前: [話者の id]}, "refused": [{"name", "speakers", "reason": "generic"|"no_rows"}],
        "skipped": {"unproofed", "tagged", "mixed", "short"}(覚える人の行のうち使わなかった数。理由は 1秒未満 → 混ざる → 音のメモ → 未校正 の順に1つ)}"""
    names = {s.get("id"): str(s.get("name") or "").strip()[:60] for s in doc.get("speakers") or [] if isinstance(s, dict) and not ed_state.other_speaker(s)}   # 組み込みの「ゲーム音声など」は覚えない(断った扱いにもしない)
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
    if ed_jobs.tid_busy(tid, ed_jobs.EXCLUSIVE["voice-learn"]):
        raise ed_state.ApiError("busy", "この文字起こしは、すでに別の処理(話者判別・再認識・声を覚える)の最中です", 409)
    return {"tid": tid, "embedding": emb, "names": names, "confirmSame": sorted(same & set(names)),
            "title": ed_jobs.job_title("声を覚える: ", doc)}


def run_voice_learn(job):
    spec = job["spec"]
    with ed_jobs.job_temp_wav(job) as wav:
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
        ed_jobs.check_cancel(job)
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
                    ed_state.add_warning(job, "「%s」の声は、待っている間にほかで覚えられたので足しませんでした(同じ人なら、もう一度「声を覚える」を押してください)" % n)
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
        ed_jobs.job_done(job, spec["tid"])


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


# ---------- 話者ごとの字幕の見た目を外から入れる(入口のまとめて実行。2026-10-05。docs/spec/friend-intake.md の 3・6) ----------
# POST /api/speakers/sub {"id": 文書の id, "styles": {"名前": {"color": "#RRGGBB" か "RRGGBB"}}} -> {"ok": true, "applied": [名前…]}
# 友人の依頼で指定した色を、話者分離のあとに文書の話者へ覚える(PC の「自分の色」には入れない)。名前がちょうど合った人(NFKC・空白を寄せて比べる)だけ。
# 合う人がいなくても 200(applied が空)。履歴の控えは recognize_voices が名前を付けるときと同じく残さない(話者の見た目だけの書き込み)
SPKSUB_SKIP_KINDS = ("alt", "normalize")   # この文書を書き換えないジョブ(2つ目のエンジン・30fps の作り直し)は「最中」に数えない


def _spksub_key(name):
    return re.sub(r"\s+", " ", unicodedata.normalize("NFKC", str(name or ""))).strip()


def _spksub_busy(tid):
    with ed_jobs._jobs_lock:
        return any(j.get("state") in ed_jobs.ACTIVE_STATES and j.get("kind") not in SPKSUB_SKIP_KINDS
                   and tid in (j.get("tid"), (j.get("spec") or {}).get("tid"), (j.get("spec") or {}).get("intoDoc")) for j in ed_jobs._jobs.values())


def speakers_sub_apply(obj):
    tid = str(obj.get("id") or "") if isinstance(obj, dict) else ""
    if not ed_state.TID_RE.match(tid):
        raise ed_state.ApiError("bad_request", "文書の指定が正しくありません", 400)
    styles = obj.get("styles")
    if not isinstance(styles, dict) or len(styles) > 50:
        raise ed_state.ApiError("bad_request", "styles は {名前: {color}} の形で送ってください(50 人まで)", 400)
    want = {}
    for name, st in styles.items():
        if not isinstance(name, str) or not isinstance(st, dict) or len(name) > 200 or any(ord(ch) < 32 for ch in name):
            raise ed_state.ApiError("bad_request", "styles の名前・中身の形が正しくありません", 400)
        if "color" in st and ed_store._sub_color(st["color"]) is None:
            raise ed_state.ApiError("bad_request", "字幕の色は 16 進 6 桁(#RRGGBB)で送ってください: %s" % str(st["color"])[:20], 400)
        one = ed_store.sanitize_sub_style(st)   # 知らない鍵は黙って捨てる(新しい入口が古い編集へ送っても、色までは効く)
        key = _spksub_key(name)
        if one and key:
            want[key] = one
    with ed_store._save_lock:   # 読み直し〜書き込みは保存と同じロックの中(recognize_voices と同じ)
        doc = ed_store.read_transcript(tid)
        if _spksub_busy(tid):
            raise ed_state.ApiError("busy", "この文字起こしは処理中です(話者判別などが終わってから、もう一度送ってください)", 409)
        applied = []
        for s in doc.get("speakers") or []:
            if not isinstance(s, dict) or ed_state.other_speaker(s):
                continue
            one = want.get(_spksub_key(s.get("name")))
            if one:
                s["sub"] = dict(ed_store.sanitize_sub_style(s.get("sub")) or {}, **one)
                applied.append(str(s.get("name") or ""))
        if applied:
            doc["updatedAt"] = max(int(time.time() * 1000), int(ed_state.num(doc.get("updatedAt"), 0) or 0) + 1)
            ed_store.write_doc(tid, doc)
    return {"ok": True, "applied": applied}
