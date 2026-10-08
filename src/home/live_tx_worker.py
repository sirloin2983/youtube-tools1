"""配信中の候補の文字起こし(線 D の D-11 案 b。plan/line-d-live-clipping.md の 0-11)の子プロセス。**入口のプロセスから import しない**
(編集の tx_engines を読むため)。1 回の起動で 1 本の wav を認識して終わる(常駐しない = whisper-cli はモデルの読み込みが数秒で、候補は 1 時間に数本なので足りる)。

使い方: python live_tx_worker.py <編集の作業データのフォルダ> <モデル名> <wav(16kHz モノラル)> <出力 json>
  編集の tx_engines.WhisperCpp(作業データの bin/whisper.cpp-<版>-vulkan/whisper-cli.exe・Vulkan = GPU)で認識し、出力 json に
  {"ok": true, "text", "rows": [{start, end, text}], "sec", "gpu", "model", "engine"} か {"ok": false, "reason"} を書く。終了コードは ok なら 0。
  モデルとワーカー(whisper-cli)の場所は入口側(src/home/live_tx.py の LiveTx.ready)が先に確かめる(ここでは取りに行かない = 3GB を黙って取得しない)。
  GPU を頼んで Vulkan で動かなければ、編集と同じく黙って CPU にせず失敗にする(WhisperCpp._check_gpu)。
"""
import json
import os
import sys
import time


def _paths():
    here = os.path.dirname(os.path.abspath(__file__))
    src = os.path.dirname(here)
    for p in (os.path.join(src, "editor"), src):
        if p not in sys.path:
            sys.path.insert(0, p)


def recognize(data_dir, model, wav):
    """-> 出力 json の中身(dict)"""
    _paths()
    import tx_engines   # 編集の認識エンジンの口(numpy などはこの子プロセスの中だけ)
    spec = tx_engines.WCPP_MODELS.get(model)
    if spec is None:
        return {"ok": False, "reason": "whisper.cpp で使えないモデルです: %s" % str(model)[:40]}
    exe = os.path.join(tx_engines.wcpp_bin_dir(data_dir), tx_engines.WCPP_EXE)
    mpath = os.path.join(tx_engines.wcpp_model_dir(data_dir), spec["file"])
    vad = os.path.join(tx_engines.wcpp_model_dir(data_dir), tx_engines.WCPP_VAD["file"])
    if not os.path.isfile(exe) or not os.path.isfile(mpath):
        return {"ok": False, "reason": "whisper.cpp かモデルがありません(%s / %s)" % (exe, mpath)}
    eng = tx_engines.WhisperCpp(model, "vulkan", {"cmd": [exe], "model": mpath, "vad": vad})   # create() と同じ形(取得と SHA-256 の確認は飛ばす)
    eng.gpu_name = ""
    t0 = time.time()
    segs, _info = eng.transcribe(wav, language="ja", beam_size=5, condition_on_previous_text=False, vad_filter=False)
    rows = []
    for s in segs:
        text = str(getattr(s, "text", "") or "").strip()
        if text:
            rows.append({"start": round(float(s.start), 2), "end": round(float(s.end), 2), "text": text})
    return {"ok": True, "text": "".join(r["text"] for r in rows), "rows": rows, "sec": round(time.time() - t0, 1),
            "gpu": getattr(eng, "gpu_name", "") or "", "model": model, "engine": "whisper.cpp"}


def main(argv):
    if len(argv) != 5:
        print("usage: live_tx_worker.py <data_dir> <model> <wav> <out.json>", file=sys.stderr)
        return 2
    data_dir, model, wav, out = argv[1:5]
    try:
        doc = recognize(data_dir, model, wav)
    except Exception as e:   # noqa: BLE001  (理由を入口へ返す。何が起きても json を書く)
        doc = {"ok": False, "reason": "%s: %s" % (e.__class__.__name__, str(e)[:300])}
    tmp = out + ".part"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False)
    os.replace(tmp, out)
    return 0 if doc.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
