# -*- coding: utf-8 -*-
"""① 自動の流れの層 pipeline/transcribe: 話者判別の計算(sherpa-onnx)と判別の記録・声の特徴と覚えた声との照らし合わせ。

役割で組み直す RS2-9(2026-10-10)に編集の src/editor/ed_speakers.py から移した(中身は同じ。文書へ反映する側・判別のジョブ・空の行の下書き・
自動の判別・声を覚える・字幕の見た目は human/proof/speakers.py)。旧い名前 ed_speakers.名前 は editor/ed_speakers.py(転送だけの殻。RS5 で消す)が、
serve.名前 は serve の名前の受付がここへ回す(テストの S.名前 = …・patch.object(S, "has_sherpa") もここに届く)。
- 判別のモデル: DIAR_SEG・DIAR_EMBS(固定の URL と SHA-256)を作業データの models/diar に取る(ensure_diar_models)。置き場所は呼ぶたびに ytt/workdata の DATA_DIR から
  (diar_models_dir。DIAR_DIR は上書き用 = src/eval/tools/eval_speakers が本物の作業データの場所を入れる)
- 判別: diarize_real(サーバーは認識ワーカーに頼む)→ ワーカーの中の _diarize_local(sherpa-onnx)。行への割り当て assign_speakers・細切れのならし smooth_labels
- 判別の記録 transcripts/<id>.diar.json(build_diar_run・write_diar・read_diar・update_diar_voices)
- 声の特徴: embed_groups(ワーカーの中の _embed_local)と照らし合わせ match_voices。本物と疑似は backend の口(疑似は eval/fake/fake_asr の diarize_fake・embed_fake)
numpy・sherpa_onnx は _diarize_local・_embed_local の関数の中で読む(サーバーのプロセスでは読まない = src/editor/tests/test_worker.py の検査)。
読むのは標準ライブラリ・ytt・兄弟(backend・tx_engines・txbase・worker_client)だけ(editor の ed_*・serve・eval は読まない)。
"""
import bisect
import contextlib
import hashlib
import json
import math
import os
import shutil
import tarfile
import threading
import time
import urllib.error
import urllib.request

from ytt import errors as _errors, fsio as _fsio, jobs as _heavy, schemas as _yschemas, workdata as _workdata
from . import backend as _backend, tx_engines, txbase as _txbase, worker_client

# ---------- 話者の自動判別(sherpa-onnx) ----------
# 流れ: 音声を取り出す → 「誰がいつ話したか」の区間を求める(diarization) → 文字起こしの各行に、重なりが最も長い人を割り当てる。
# 文字起こしモデルとは独立に動くので、どのモデルで作った文字起こしにも使える。CPU で動く(PyTorch 不要)。
# モデルの置き場所は呼ぶたびに作業データ(ytt/workdata の DATA_DIR)の models/diar(以前は読み込みのときに作り、serve の set_data_dir が直していた = 同じ場所。RS2-9)。
# DIAR_DIR は上書き用(src/eval/tools/eval_speakers が本物の作業データの models/diar を入れる)。None なら作業データの中
DIAR_DIR = None
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


def diar_threads():
    """話者判別(sherpa-onnx)のスレッド数。既定は min(8, CPU)(2026-10-04 に 4 から上げた。P コアの数。環境変数 TRANSCRIBE_DIAR_THREADS で変えられる。
    git の履歴(679ff01 以前)の docs/plan/stability-review-2026-10.md の S2)"""
    n = tx_engines.env_num("TRANSCRIBE_DIAR_THREADS", 0, lo=0, hi=64)   # 0 以下・読めない = CPU の数から決める
    return n if n > 0 else max(1, min(8, os.cpu_count() or 2))


def has_sherpa():
    if worker_client.worker_fake():
        return True
    return worker_client.worker_has("sherpa_onnx", "numpy")


def diar_models_dir():
    """判別のモデルの置き場所(上書きの DIAR_DIR があればそれ、無ければ作業データの models/diar。呼ぶたびに決める)"""
    return DIAR_DIR or os.path.join(_workdata.DATA_DIR, "models", "diar")


def _diar_path(item):
    return os.path.join(diar_models_dir(), item["file"])


def _have(item):
    return os.path.isfile(_diar_path(item)) and os.path.getsize(_diar_path(item)) > 1000


def diar_info():
    return {"ready": _backend.is_fake() or has_sherpa(), "segReady": _have(DIAR_SEG), "default": DIAR_EMB_DEFAULT,
            "embeddings": [{"key": k, "label": v["label"], "mb": v["mb"], "ready": _have(v)} for k, v in DIAR_EMBS.items()]}


def _download_verified(job, item, tmp):
    """固定の URL からダウンロードし、SHA-256 が想定と一致したものだけを受け入れる(改ざん・別ファイルの混入を防ぐ)。"""
    req = urllib.request.Request(item["url"], headers={"User-Agent": "transcribe-tool"})
    h, done = hashlib.sha256(), 0
    with urllib.request.urlopen(req, timeout=30) as r, open(tmp, "wb") as f:
        total = int(r.headers.get("Content-Length") or 0)
        while True:
            _heavy.check_cancel(job)
            chunk = r.read(256 * 1024)
            if not chunk:
                break
            done += len(chunk)
            if done > item["max"]:
                raise _errors.ApiError("model_download", "モデルのサイズが想定より大きいため中止しました", 500)
            h.update(chunk)
            f.write(chunk)
            if total:
                job["phase"] = "話者判別のモデルをダウンロード中(%s %d%%)" % (item["label"], min(100, done * 100 // total))
    if h.hexdigest() != item["sha256"]:
        raise _errors.ApiError("model_hash", "ダウンロードしたモデルが想定と一致しません(配布元で差し替えられた可能性があります)。ツールの更新を確認してください", 500)


def ensure_diar_models(job, emb=DIAR_EMB_DEFAULT):
    if worker_client.worker_fake():   # テスト用(ワーカーの中の偽の判別を使う。モデルはダウンロードしない)
        return
    os.makedirs(diar_models_dir(), exist_ok=True)
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
                        raise _errors.ApiError("model_download", "モデルの形式が想定と違います", 500)
                    with tf.extractfile(m) as src, open(part, "wb") as out:
                        shutil.copyfileobj(src, out)
                _fsio.replace_retry(part, dest)
            else:
                _fsio.replace_retry(tmp, dest)
        except (urllib.error.URLError, OSError, tarfile.TarError, KeyError) as e:
            raise _errors.ApiError("model_download", "話者判別のモデルをダウンロードできませんでした(初回はインターネット接続が必要です): %s" % str(e)[:150], 500)
        finally:
            for x in (tmp, part):
                _fsio.unlink_quiet(x)


DIAR_TUNE = (("threshold", "threshold"), ("min_on", "minOn"), ("min_off", "minOff"))   # 判別の設定を変えて測るときの任意の引数(引数の名前, ワーカーの要求の鍵)


def diar_tune(threshold=None, min_on=None, min_off=None):
    """判別の設定の任意の引数を確かめる -> {引数の名前: 値}(渡したものだけ。どれも 0 以上 10 未満の数)。src/eval/tools/eval_speakers.py の run が使う"""
    out = {}
    for (k, _w), v in zip(DIAR_TUNE, (threshold, min_on, min_off)):
        if v is None:
            continue
        try:
            x = float(v)
        except (TypeError, ValueError):
            x = -1.0
        if not 0.0 <= x < 10.0:   # NaN もここで断る
            raise _errors.ApiError("bad_request", "話者判別の設定(%s)が正しくありません" % k, 400)
        out[k] = x
    return out


def diarize_real(job, wav, num, emb=DIAR_EMB_DEFAULT, threshold=None, min_on=None, min_off=None):
    """話者の判別。sherpa-onnx(ネイティブコード)は認識ワーカー(別プロセス)の中で動かす。戻り値は [(開始, 終了, 話者番号)]。
    threshold・min_on・min_off は判別の設定を変えて測るとき(src/eval/tools/eval_speakers.py の run)だけ。渡さなければ既定の値で、ワーカーへの要求も以前と同じ形"""
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
        raise _errors.ApiError("diar_failed", "話者判別の設定を読み込めませんでした(モデルファイルが壊れている可能性があります。models フォルダを削除して、もう一度試してください)", 500)
    sd = so.OfflineSpeakerDiarization(cfg)
    if sd.sample_rate != 16000:
        raise _errors.ApiError("diar_failed", "話者判別のモデルの形式が想定と違います", 500)
    samples = worker_client.read_wav_f32(wav)

    def cb(done, total, *_):
        if total:
            job["progress"] = min(0.99, done / total)
        return 1 if job["cancel"] else 0   # 0 以外を返すと中断する

    res = sd.process(samples, callback=cb).sort_by_start_time()
    _heavy.check_cancel(job)
    return [(float(r.start), float(r.end), int(r.speaker)) for r in res]


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
    return os.path.join(_workdata.TX_DIR, tid + ".diar.json")


def read_diar(tid):
    """{"schema", "latest": {…}, "history": [前の回(新しい順)]}。無い・壊れていれば None"""
    return _fsio.read_schema_json(diar_path(tid), MAX_DIAR_BYTES, DIAR_SCHEMA, "latest", dict)


def _diar_put(tid, d):
    _fsio.atomic_write(diar_path(tid), json.dumps(d, ensure_ascii=False, separators=(",", ":")).encode("utf-8"), fsync_required=True)


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
    """判別の記録の engine。本物と疑似は backend の口 diar_engine(RS5-D。疑似 = eval/fake/fake_asr は {"name": "fake", …})"""
    return _backend.select().diar_engine(emb, requested, _diar_engine_real)


def _diar_engine_real(emb, requested):
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
    return [[round(a, 2), round(b, 2)] for a, b in _yschemas.union_spans(raw)[:MAX_DIAR_OVERLAPS] if b - a > 0.01]


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
        _txbase.log.warning("判別の記録を書けませんでした: %s %s", e.__class__.__name__, str(e)[:150])


# ---------- 声の特徴と、覚えた声との照らし合わせ(A-3。覚えた声の置き場所・覚えるジョブは human/proof/speakers) ----------
# 名前を付けた話者の行の音声から「声の特徴」(sherpa-onnx の話者の埋め込み。判別モデルごとに別)を取り、覚えている声とコサイン類似度で比べる。
# 計算(numpy・sherpa-onnx)は認識ワーカーの中だけ(_embed_local)。サーバーでは読み込まない
VOICE_MATCH = 0.60       # 覚えている声とのコサイン類似度がこれ以上なら同じ人とみなす
VOICE_MARGIN = 0.08       # 2番目に近い声との差がこれより小さければ決めない(似た声を取り違えるより、名前を付けない方が安全)
VOICE_MIN_ROW = 1.0       # 声の特徴を取る行の最短(秒)。短い行(相づち)は特徴が安定しない
VOICE_MAX_ROWS = 40       # 1人あたり使う行の数の上限(長い行から)
VOICE_MAX_SEC = 240.0     # 1人あたり使う長さの上限(秒)


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
        a, b = _yschemas.num_or(g.get("start")), _yschemas.num_or(g.get("end"))
        if a is None or b is None or b - a < VOICE_MIN_ROW or _txbase.MIXED_FLAG in str(g.get("flag") or ""):
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
    """groups: [[(開始, 終了)...]](元の動画の時刻)。wav は offset 秒から始まる音声。-> [長さ 1 の特徴 or None](groups と同じ並び)。
    疑似は eval/fake/fake_asr の embed_fake(backend の口。RS2-9)"""
    rel = [[[max(0.0, a - offset), max(0.0, b - offset)] for a, b in g] for g in groups]
    return _backend.select().embed(job, wav, emb, rel, _embed_real)


def _embed_real(job, wav, emb, groups):
    """声の特徴の本物の道(backend の口の real): ワーカーの中なら _embed_local、サーバーならワーカーに頼む"""
    if worker_client.IN_WORKER:
        return _embed_local(job, wav, emb, groups)
    res = worker_client.WORKER.call("embed", {"wav": wav, "emb": emb, "groups": groups}, job)
    return [[float(x) for x in v] if isinstance(v, list) and v else None for v in res]


def _embed_local(job, wav, emb, groups):
    """認識ワーカーの中だけで動く(numpy・sherpa-onnx)。区間ごとの特徴を長さで重みを付けて平均し、長さ 1 に"""
    import numpy as np
    import sherpa_onnx as so
    threads = diar_threads()
    cfg = so.SpeakerEmbeddingExtractorConfig(model=_diar_path(DIAR_EMBS[emb]), num_threads=threads)
    if not cfg.validate():
        raise _errors.ApiError("diar_failed", "声の特徴のモデルを読み込めませんでした(models フォルダを削除して、もう一度試してください)", 500)
    ex = so.SpeakerEmbeddingExtractor(cfg)
    samples, sr = worker_client.read_wav_f32(wav), 16000
    total, done, out = max(1, sum(len(g) for g in groups)), 0, []
    for g in groups:
        vecs, weights = [], []
        for a, b in g:
            _heavy.check_cancel(job)
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
