"""配信中の候補の文字起こし(線 D の D-11 案 b。plan/line-d-live-clipping.md の 0-11)の子プロセス。**入口のプロセスから import しない**
(編集の tx_engines を読むため)。1 回の起動で 1 本の wav を認識して終わる(常駐しない = whisper-cli はモデルの読み込みが数秒で、候補は 1 時間に数本なので足りる)。

使い方: python live_tx_worker.py <編集の作業データのフォルダ> <モデル名> <wav(16kHz モノラル)> <出力 json> [機器 vulkan|cpu(既定 vulkan)]
  (旧い場所 src/home/live_tx_worker.py の転送は RS5-G で消した)
  編集の tx_engines.WhisperCpp(作業データの bin/whisper.cpp-<版>-vulkan/whisper-cli.exe・Vulkan = GPU)で認識し、出力 json に
  {"ok": true, "text", "rows": [{start, end, text}], "sec", "gpu", "model", "engine"} か {"ok": false, "reason"} を書く。終了コードは ok なら 0。
  モデルとワーカー(whisper-cli)の場所は入口側(src/flow/live_tx.py の LiveTx.ready)が先に確かめる(ここでは取りに行かない = 3GB を黙って取得しない)。
  GPU を頼んで Vulkan で動かなければ、編集と同じく黙って CPU にせず失敗にする(WhisperCpp._check_gpu)。
"""
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.dirname(os.path.dirname(HERE))   # transcribe -> pipeline -> src
if __name__ == "__main__":   # スクリプトとして起動したときだけ: このフォルダを外して src を先頭に(兄弟は絶対 import。層の決まりの例外)
    sys.path[:] = [SRC] + [p for p in sys.path if os.path.normcase(os.path.abspath(p or os.curdir)) not in (os.path.normcase(HERE), os.path.normcase(SRC))]


def _paths():
    if SRC not in sys.path:   # pipeline.transcribe と ytt の置き場所(import したとき = テスト)
        sys.path.insert(0, SRC)


DEVICES = ("vulkan", "cpu")   # whisper.cpp の機器(既定 vulkan。入口の flow/live_tx がこの PC の設定 flow/machine.py から決めて、既定と違うときだけ 5 つ目の引数で渡す。RS7-1 S1)


def recognize(data_dir, model, wav, device="vulkan"):
    """-> 出力 json の中身(dict)"""
    _paths()
    from pipeline.transcribe import tx_engines   # 認識エンジンの口(numpy などはこの子プロセスの中だけ)
    spec = tx_engines.WCPP_MODELS.get(model)
    if spec is None:
        return {"ok": False, "reason": "whisper.cpp で使えないモデルです: %s" % str(model)[:40]}
    exe = os.path.join(tx_engines.wcpp_bin_dir(data_dir), tx_engines.WCPP_EXE)
    mpath = os.path.join(tx_engines.wcpp_model_dir(data_dir), spec["file"])
    vad = os.path.join(tx_engines.wcpp_model_dir(data_dir), tx_engines.WCPP_VAD["file"])
    if not os.path.isfile(exe) or not os.path.isfile(mpath):
        return {"ok": False, "reason": "whisper.cpp かモデルがありません(%s / %s)" % (exe, mpath)}
    eng = tx_engines.WhisperCpp(model, device if device in DEVICES else DEVICES[0], {"cmd": [exe], "model": mpath, "vad": vad})   # create() と同じ形(取得と SHA-256 の確認は飛ばす)
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
    if len(argv) not in (5, 6) or (len(argv) == 6 and argv[5] not in DEVICES):
        print("usage: live_tx_worker.py <data_dir> <model> <wav> <out.json> [vulkan|cpu]", file=sys.stderr)
        return 2
    data_dir, model, wav, out = argv[1:5]
    device = argv[5] if len(argv) == 6 else DEVICES[0]
    _paths()
    from ytt import fsio   # 書きかけを入口に読ませない(一時ファイル → 置き換え)
    try:
        doc = recognize(data_dir, model, wav, device)
    except Exception as e:   # noqa: BLE001  (理由を入口へ返す。何が起きても json を書く)
        doc = {"ok": False, "reason": "%s: %s" % (e.__class__.__name__, str(e)[:300])}
    fsio.write_json(out, doc, indent=None)
    return 0 if doc.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
