# -*- coding: utf-8 -*-
"""① 自動の流れの層 pipeline/transcribe: 話者判別の計算(Nemotron 3 Diarization・speech.cpp)と判別の記録・声の特徴(sherpa-onnx)と覚えた声との照らし合わせ。

ここに無い物(文書へ反映する側・判別のジョブ・空の行の下書き・
自動の判別・声を覚える・字幕の見た目は human/proof/speakers.py)。③ の speakers はここを直に読まず、② flow/diar.py(判別のジョブの段取り・
判別の記録を書く _record_diar・覚えた声の置き場所)を通す。
serve.名前 は serve の名前の受付がここへ回す(テストの S.名前 = …・patch.object(S, "has_sherpa") もここに届く)。
- 判別のモデル: DIAR_NEMO(固定の URL・大きさ・SHA-256)を作業データの models/diar に取る(ensure_diar_model)。声の特徴のモデル DIAR_EMBS も同じ所(ensure_diar_models)。置き場所は呼ぶたびに ytt/workdata の DATA_DIR から
  (diar_models_dir。DIAR_DIR は上書き用 = src/eval/tools/eval_speakers が本物の作業データの場所を入れる)
- 判別: diarize_real(サーバーは認識ワーカーに頼む)→ ワーカーの中の _diarize_local(speech diarize を子プロセスで)。行への割り当て assign_speakers・細切れのならし smooth_labels
- 判別の記録 transcripts/<id>.diar.json(build_diar_run・write_diar・read_diar・update_diar_voices)
- 声の特徴: embed_groups(ワーカーの中の _embed_local)と照らし合わせ match_voices_explain。本物と疑似は backend の口(疑似は eval/fake/fake_asr の diarize_fake・embed_fake)
numpy・sherpa_onnx は _embed_local の関数の中で読む(サーバーのプロセスでは読まない = tests/pipeline/transcribe/test_worker.py の検査)。
読むのは標準ライブラリ・ytt・兄弟(backend・tx_engines・txbase・worker_client)だけ(editor の ed_*・serve・eval は読まない)。
"""
import bisect
import contextlib
import hashlib
import json
import math
import os
import threading
import time
import urllib.error
import urllib.request

from ytt import docloc as _docloc, errors as _errors, fsio as _fsio, jobs as _heavy, schemas as _yschemas, tools as _ytools, workdata as _workdata
from . import backend as _backend, tx_engines, worker_client
from ytt import txbase as _txbase

# ---------- 話者分離(Nemotron 3 Diarization・speech.cpp の speech diarize) ----------
# 流れ: 音声を取り出す → 「誰がいつ話したか」の区間を求める(diarization) → 文字起こしの各行に、重なりが最も長い人を割り当てる。
# 文字起こしモデルとは独立に動くので、どのモデルで作った文字起こしにも使える。11-01 に pyannote(sherpa-onnx の segmentation 3.0 + voxceleb の
# かたまり分け)から入れ替えた(ユーザー「完全に入れ替えていい」・保管庫 plan/Nemotron入れ替えの一覧.md)。名前は付けない(話者 0・1… の番号だけ。最大 8 人)。
# speech.cpp の `speech worker` は diarize を受けないので、`speech diarize <gguf> --format json` を認識ワーカーの中から子プロセスで呼ぶ(黒い窓なし・優先度「低」)。
# 実行ファイルは Haas と同じ手元の直しの版(ytt/txbase.speech_exe)。機器は auto(GPU が使えれば Vulkan)で、だめなら 1 回だけ CPU で取り直す。
# モデルの置き場所は呼ぶたびに作業データ(ytt/workdata の DATA_DIR)の models/diar。
# DIAR_DIR は上書き用(src/eval/tools/eval_speakers が本物の作業データの models/diar を入れる)。None なら作業データの中
DIAR_DIR = None
_NEMO_HF = "https://huggingface.co/sakasegawa/Nemotron-3-Diarization-GGUF/resolve/9096d41cb78bba7ac882b96d453e25239eac692b/"   # speech.cpp 0.10.0 の catalog.json の revision
DIAR_NEMO = {"file": "Nemotron-3-Diarization-99M-Q8_0.gguf", "url": _NEMO_HF + "Nemotron-3-Diarization-99M-Q8_0.gguf", "size": 106179488,
             "sha256": "336df6350dce2ea5ff06aa6e2b249d331a859ced13305fbb45c44bdb3c0abe20", "label": "話者分離(Nemotron 3 Diarization)"}   # 大きさと SHA-256 は catalog.json の値(手元で取った物も同じ)
DIAR_ENGINE = "nemotron-3-diarization"
DIAR_COMMAND = None   # テスト用: 偽の speech の起動の引数(この後ろに diarize・モデル・--format などを足す)
DIAR_TIMEOUT = 1800   # 1 回の判別の上限(秒。3 時間の音で GPU 15 秒・CPU 4 スレッド 6 分ほど)
_GH = "https://github.com/k2-fsa/sherpa-onnx/releases/download/speaker-recongition-models/"
# 声の特徴を取り出すモデル(声の名前付け = 覚える・照らし合わせる。sherpa-onnx・認識ワーカーの中)。人を分ける判別には使わない(11-01 から Nemotron)。
# campplus は 10-22 から声の名前付けのモデル(評価用のソロの文書 83 本の一つ抜きで、本人が 1 位 9 → 44 / 75)。
# voxceleb は 11-01 まで判別の声の特徴に使っていた。古い文書・設定の名前と、10-22 より前に voxceleb で覚えた声を読むために表に残す(頼まれた時だけ取る)
DIAR_EMBS = {
    "voxceleb": {"file": "embedding-voxceleb.onnx", "member": None, "label": "VoxCeleb ResNet34(多言語の声で学習)", "mb": 27, "max": 80 * 1024 * 1024,
                 "url": _GH + "wespeaker_en_voxceleb_resnet34_LM.onnx", "sha256": "e9848563da86f263117134dfd7ad63c92355b37de492b55e325400c9d9c39012"},
    "campplus": {"file": "embedding-campplus.onnx", "member": None, "label": "3D-Speaker CAM++(中国語+英語)", "mb": 28, "max": 80 * 1024 * 1024,
                 "url": _GH + "3dspeaker_speech_campplus_sv_zh_en_16k-common_advanced.onnx", "sha256": "aa3cfc16963a10586a9393f5035d6d6b57e98d358b347f80c2a30bf4f00ceba2"},
}
VOICE_EMB = "campplus"   # 声の名前付けに使うモデル(覚えた声は voices/<モデル>.json でモデルごとに別)
DIAR_EMB_DEFAULT = VOICE_EMB   # 判別のジョブの指定の embedding の既定(= 照らし合わせる声のモデル。11-01 まで判別の声の特徴の voxceleb)
MAX_DIAR_SEC = 3 * 3600


def diar_threads():
    """CPU で判別するときと声の特徴(sherpa-onnx)のスレッド数。既定は 4(PC の決まり = 合わせて 6 本まで。環境変数 TRANSCRIBE_DIAR_THREADS で変えられる)"""
    n = tx_engines.env_num("TRANSCRIBE_DIAR_THREADS", 0, lo=0, hi=64)   # 0 以下・読めない = 既定
    return n if n > 0 else max(1, min(4, os.cpu_count() or 2))


def has_sherpa():
    """声の特徴(sherpa-onnx)が使えるか(声を覚える・照らし合わせる)"""
    if worker_client.worker_fake():
        return True
    return worker_client.worker_has("sherpa_onnx", "numpy")


def speech_exe():
    """判別に使う speech.cpp の実行ファイル(Haas と同じ置き場所 = エンジンの置き場所の bin。置き場所が決まっていなければ "")"""
    d = tx_engines.engine_home()
    return _txbase.speech_exe(d) if d else ""


def has_diar():
    """話者分離が使えるか(speech.cpp の実行ファイルが置いてあるか。モデルは最初の判別で取る)"""
    if worker_client.worker_fake() or DIAR_COMMAND:
        return True
    exe = speech_exe()
    return bool(exe) and os.path.isfile(exe)


def diar_models_dir():
    """判別のモデルの置き場所(上書きの DIAR_DIR があればそれ、無ければ作業データの models/diar。呼ぶたびに決める)"""
    return DIAR_DIR or os.path.join(_workdata.DATA_DIR, "models", "diar")


def _diar_path(item):
    return os.path.join(diar_models_dir(), item["file"])


def _have(item):
    return os.path.isfile(_diar_path(item)) and os.path.getsize(_diar_path(item)) > 1000


def diar_info():
    return {"ready": _backend.is_fake() or has_diar(), "engine": DIAR_ENGINE, "modelReady": _have(DIAR_NEMO), "voiceReady": _backend.is_fake() or has_sherpa(),
            "default": DIAR_EMB_DEFAULT, "embeddings": [{"key": k, "label": v["label"], "mb": v["mb"], "ready": _have(v)} for k, v in DIAR_EMBS.items()]}


def _download_verified(job, item, tmp):
    """固定の URL からダウンロードし、SHA-256 が想定と一致したものだけを受け入れる(改ざん・別ファイルの混入を防ぐ)。
    取得を止めているとき(tx_engines.no_fetch)は取らない"""
    if tx_engines.no_fetch():
        raise _errors.ApiError("fetch_blocked", "取得を止めているので話者判別のモデルを取りません(%s)" % tx_engines.NO_FETCH_ENV, 409)
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
        raise _errors.ApiError("model_hash", "ダウンロードしたモデルが想定と一致しません(配布元で差し替えられた可能性があります)。ツールの更新を確かめてください", 500)


def ensure_diar_model(job):
    """話者分離のモデル(DIAR_NEMO)を用意する(あれば大きさと SHA-256 を確かめるだけ = tx_engines.fetch_file)"""
    if worker_client.worker_fake():   # テスト用(ワーカーの中の偽の判別を使う。モデルはダウンロードしない)
        return
    def progress(f):
        job["phase"] = "話者判別のモデルをダウンロード中(%s %d%%)" % (DIAR_NEMO["label"], min(100, int(f * 100)))
    try:
        tx_engines.fetch_file(DIAR_NEMO, diar_models_dir(), None, lambda: bool(job.get("cancel")), progress)
    except tx_engines.EngineError as e:
        if e.code == "cancelled":
            _heavy.check_cancel(job)
        raise _errors.ApiError("fetch_blocked" if e.code == "fetch_blocked" else "model_download",
                               "話者判別のモデルを用意できませんでした(初回はインターネット接続が必要です): %s" % e.message, 409 if e.code == "fetch_blocked" else 500)


def ensure_diar_models(job, emb=DIAR_EMB_DEFAULT):
    """声の特徴のモデル(DIAR_EMBS[emb])を用意する(声を覚える・照らし合わせる前)"""
    if worker_client.worker_fake():   # テスト用(ワーカーの中の偽の判別を使う。モデルはダウンロードしない)
        return
    os.makedirs(diar_models_dir(), exist_ok=True)
    item = DIAR_EMBS[emb]
    if _have(item):
        return
    dest = _diar_path(item)
    tmp = dest + ".download"
    try:
        _download_verified(job, item, tmp)
        _fsio.replace_retry(tmp, dest)
    except (urllib.error.URLError, OSError) as e:
        raise _errors.ApiError("model_download", "声の特徴のモデルをダウンロードできませんでした(初回はインターネット接続が必要です): %s" % str(e)[:150], 500)
    finally:
        _fsio.unlink_quiet(tmp)


def diarize_real(job, wav, num):
    """話者の判別。speech.cpp は認識ワーカー(別プロセス)の中から子プロセスで呼ぶ。戻り値は [(開始, 終了, 話者番号)]。
    num = 人数の指定(Nemotron には渡せない = 記録の requested に残るだけ。0 = 自動)"""
    if worker_client.IN_WORKER:
        return _diarize_local(job, wav, num)
    turns = worker_client.WORKER.call("diarize", {"wav": wav, "num": int(num)}, job)
    return [(float(a), float(b), int(k)) for a, b, k in turns]


def _diar_cmd(device):
    base = list(DIAR_COMMAND) if DIAR_COMMAND else [speech_exe()]
    return base + ["diarize", _diar_path(DIAR_NEMO), "--format", "json", "--device", device, "--threads", str(diar_threads())]


def parse_diar_json(out):
    """speech diarize --format json の出力(1 ファイル 1 行の {"file", "segments": [{"start", "end", "speaker"}]})-> [(開始, 終了, 話者番号)](開始の順)"""
    turns = []
    for line in out.splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        d = json.loads(line)
        for s in d.get("segments") or ():
            a, b, k = float(s["start"]), float(s["end"]), int(s["speaker"])
            if b > a and k >= 0:
                turns.append((a, b, k))
    return sorted(turns)


def _diarize_local(job, wav, num=0, emb=None):
    """認識ワーカーの中で動く: speech diarize を子プロセスで(機器 auto → だめなら CPU で 1 回)。中止は孫ごと止める(tools.run)"""
    home = tx_engines.engine_home()
    choice = (_txbase.speech_choice(home) if home else None) or {}
    devices = ["cpu"] if choice.get("device") == "cpu" else ["auto", "cpu"]
    flags = _ytools.no_window_flags(priority="low")
    last = ""
    for dev in devices:
        job["phase"] = "話者を判別中(%s)" % ("CPU" if dev == "cpu" else "GPU")
        try:
            r = _ytools.run(_diar_cmd(dev) + [wav], timeout=DIAR_TIMEOUT, cancelled=lambda: bool(job.get("cancel")), flags=flags, err_tail=40)
        except OSError as e:
            raise _errors.ApiError("diar_failed", "話者判別の speech.cpp を起動できませんでした: %s" % _ytools.why(e), 500)
        _heavy.check_cancel(job)
        if r.code == 0 and r.why is None:
            return parse_diar_json(r.out.decode("utf-8", "replace"))
        last = "時間切れ" if r.why == "timeout" else " / ".join(r.err_lines(3)) or "終了コード %s" % r.code
        _txbase.log.warning("話者判別(%s)が失敗しました: %s", dev, last[:200])
    raise _errors.ApiError("diar_failed", "話者の判別に失敗しました: %s" % last[:200], 500)


DIAR_NEAR_SEC = 5.0   # 話者の区間と重ならない行は、前後この秒以内でいちばん近い区間の話者に(不確か)。10-23 に 1.5 → 5(評価用 23 本で組 B の行の正しさ 79.6 → 81.0%・組 A と人数は同じ。1.5 で前のまま)


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
        near, best = None, DIAR_NEAR_SEC   # 重なりがなければ、前後 DIAR_NEAR_SEC 秒以内でいちばん近い区間
        for x, y, s in ts[bisect.bisect_left(starts, a - dmax - best):bisect.bisect_right(starts, b + best)]:
            gap = max(x - b, a - y, 0.0)
            if gap < best:
                near, best = s, gap
        out.append((near, False, True, 0.0))
    return out


# ---------- 話者の細切れをならす(S2。試験中・既定オフ = 設定 diarSmooth・判別の要求の smooth) ----------
# 1 人の話の途中の短い 1 行だけが別の人になり、字幕の色が 1 行だけ変わる(判別の短い区間の揺れ)。行の話者を決めるときだけ、前後と同じ人にする。
# 判別の生の結果(turns・overlaps)は変えない(あとの判別が読むため)。記録は diar.json の rows[行 id] に smoothed: true(label は機械の元のラベルのまま)。
# ならす条件(全部): その行が短い(DIAR_SMOOTH_SHORT 未満)・前後の行が同じラベルで、その行だけ違う・前後とのすき間が DIAR_SMOOTH_GAP 以下・
#   根拠が弱い(自分のラベルの区間に入っている割合 ratio が DIAR_SMOOTH_RATIO 未満。最寄りの区間で代用した行は 0)・その行に別の話者の区間の重なり(overlaps)が無い。
# 根拠の弱さに「不確か」(weak)の印そのものは使わない: weak は 0.8 秒未満の行を全部含むので、短い本物の相づち(その人の区間にしっかり入っている)までならしてしまう。
# 前後に数えない行 = 守る行(diar_keep_row = 字幕に出さない・ゲーム音声など・重なりのメモつき)と文字の無い行(どちらも、ならさない)。
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
        eps = 1e-6   # 境目ちょうどの値が小数の誤差で外れない
        if b - a >= DIAR_SMOOTH_SHORT or a - p["end"] > DIAR_SMOOTH_GAP + eps or n["start"] - b > DIAR_SMOOTH_GAP + eps:
            continue
        if (i.get("ratio") or 0.0) >= DIAR_SMOOTH_RATIO:
            continue
        if sum(max(0.0, min(b, y) - max(a, x)) for x, y in overlaps if x < b and y > a) >= DIAR_SMOOTH_OVL - eps:
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


# ---------- 判別の記録(transcripts/<id>.diar.json。Q2。資料の git:before-1028-cleanup:plan/line-bc-master-plan.md) ----------
# 機械の最初の結果を残す(行の speaker・名前は人が直すので、あとから「機械はこう割り当てた」を比べられるように)。判別・声の照合のたびに書き、
# し直したら前の回は同じファイルの history に残す(最新を含めて DIAR_KEEP 回まで。付き物を1つのファイルにして、削除・付け替えの扱いを1か所で済ませるため)。
# 埋め込みのベクトルそのものは書かない(大きい・個人を見分けられる情報)。書けなくても判別は失敗にしない(② flow/diar の _record_diar)
DIAR_SCHEMA = "youtube-tools-diar/v1"
DIAR_KEEP = 5
MAX_DIAR_BYTES = 32 * 1024 * 1024
MAX_DIAR_OVERLAPS = 5000
_diar_lock = threading.Lock()


def diar_path(tid, for_write=False):
    """<id>.diar.json のパス(for_write = 書く所。索引があるのに置き場所が見えなければ断る = docloc.doc_dir)"""
    return _docloc.doc_file(tid, ".diar.json", for_write=for_write)


def read_diar(tid):
    """{"schema", "latest": {…}, "history": [前の回(新しい順)]}。無い・壊れていれば None"""
    return _fsio.read_schema_json(diar_path(tid), MAX_DIAR_BYTES, DIAR_SCHEMA, "latest", dict)


def _diar_put(tid, d):
    _fsio.atomic_write(diar_path(tid, for_write=True), json.dumps(d, ensure_ascii=False, separators=(",", ":")).encode("utf-8"), fsync_required=True)


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
    """11-01 まで(sherpa-onnx)の回は name・segmentation・clusterThreshold などを持つ(読む側は engine の中身を見ない = 古い記録もそのまま)"""
    return {"name": DIAR_ENGINE, "model": DIAR_NEMO["file"], "speechCpp": "%s-%s" % (_txbase.SPEECH_CPP_VERSION, _txbase.SPEECH_CPP_FLAVOR),
            "embedding": emb, "requested": requested or "auto", "nearGapSec": DIAR_NEAR_SEC, "voiceMatch": VOICE_MATCH, "voiceMargin": VOICE_MARGIN}


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
    auto = 文字起こしのあとの自動の判別のとき {"eval": 評価用か, "contextName": 名前の候補 or None}(人が始めた判別では書かない)。
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


# ---------- 声の特徴と、覚えた声との照らし合わせ(A-3。覚えた声の置き場所と段取りは flow/diar(RS6 a-4)・覚えるジョブは human/proof/speakers) ----------
# 名前を付けた話者の行の音声から「声の特徴」(sherpa-onnx の話者の埋め込み。声のモデルごとに別)を取り、覚えている声とコサイン類似度で比べる。
# 計算(numpy・sherpa-onnx)は認識ワーカーの中だけ(_embed_local)。サーバーでは読み込まない
VOICE_MATCH = 0.60       # 覚えている声とのコサイン類似度がこれ以上なら同じ人とみなす
VOICE_MARGIN = 0.08       # 2番目に近い声との差がこれより小さければ決めない(似た声を取り違えるより、名前を付けない方が安全)
VOICE_MIN_ROW = 1.0       # 声の特徴を取る行の最短(秒)。短い行(相づち)は特徴が安定しない
VOICE_MAX_ROWS = 40       # 1人あたり使う行の数の上限(長い行から)
VOICE_MAX_SEC = 240.0     # 1人あたり使う長さの上限(秒)


def _unit(v):
    s = math.sqrt(sum(x * x for x in v)) if v else 0.0
    return [x / s for x in v] if s > 0 else None


BLEND_MAX_SEC = 3600.0   # 前に覚えた声の重みに数える長さの上限(秒。1 時間まで)


def blend_voice(old_vec, old_sec, vec, sec):
    """覚えた声の混ぜ方の計算だけ。前の声 old_vec(長さ old_sec 秒ぶん)と新しい声 vec(sec 秒ぶん)を、長さで重みを付けて平均し長さ 1 にする。
    -> (混ぜた特徴, 合計の秒)。前の声が無いか次元が違えば (vec, sec) のまま。混ぜた結果が 0 になれば新しい vec を使う。
    前の重みは BLEND_MAX_SEC まで(配信ごとの揺れをならす)。どの文書から覚えたか・行の控えは ② の flow/diar が持つ"""
    if not old_vec or len(old_vec) != len(vec):
        return vec, sec
    w0 = min(float(old_sec or 0.0), BLEND_MAX_SEC)
    return _unit([a * w0 + b * sec for a, b in zip(old_vec, vec)]) or vec, sec + w0


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


def match_voices_explain(found, voices):
    """found: {話者の id: 特徴}、voices: 覚えている声。-> (結果, 経過)。結果は {話者の id: (名前, 似ている度合い)}。
    VOICE_MATCH 以上・2番目との差が VOICE_MARGIN 以上のときだけ。1つの名前は1人にだけ(似ている順に決める)。
    経過は判別の記録 <id>.diar.json 用 -> {話者の id: {"top", "score", "second", "secondScore", "decided", "by", "reason"}}。
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
