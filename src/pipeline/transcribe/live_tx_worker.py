"""配信中の候補の文字起こし(線 D の D-11 案 b。資料の git:before-1028-cleanup:plan/line-d-live-clipping.md の 0-11)の子プロセス。**入口のプロセスから import しない**
(編集の tx_engines を読むため)。1 回の起動で 1 本の wav を認識して終わる(常駐しない = whisper-cli はモデルの読み込みが数秒で、候補は 1 時間に数本なので足りる)。

使い方: python live_tx_worker.py <編集の作業データのフォルダ> <モデル名> <wav(16kHz モノラル)> <出力 json> [機器 vulkan|cpu|cuda(既定 vulkan)] [エンジン]
  エンジン(既定 whisper.cpp):
  - whisper.cpp: 編集の tx_engines.WhisperCpp(作業データの bin/whisper.cpp-<版>-vulkan/whisper-cli.exe・Vulkan = GPU)
  - haas-speechcpp: 編集の tx_engines.HaasSpeechCpp(speech.cpp の `speech worker`・Vulkan か CPU・11-01 段 4)。候補 1 本ごとに起こす(保管庫の Haas-ja の比べ P53 =
    起動 0.5〜0.7 秒 + 読み 1 秒ほど。残しておくと GPU のメモリ 0.9 GB を持ち続けるので起こし直す)。行は編集と同じ行の作り(postproc.expand_segments)。
    Haas が動かなければ(EngineError)、whisper.cpp とモデルがあれば whisper.cpp で読み直す(fallback に Haas の理由を残す。whisper を消すまで = 段 7)
  で認識し、出力 json に {"ok": true, "text", "rows": [{start, end, text}], "sec", "gpu", "model", "engine"(, "fallback")} か {"ok": false, "reason"} を書く。終了コードは ok なら 0。
  モデルとワーカー(whisper-cli・speech.exe)の場所は入口側(src/flow/live_tx.py の LiveTx.ready)が先に確かめる(ここでは取りに行かない = 黙って取得しない。
  Haas は取得を止めて起こす = tx_engines.NO_FETCH_ENV)。GPU を頼んで Vulkan で動かなければ、編集と同じく黙って CPU にせず失敗にする(_check_gpu)。
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


DEVICES = ("vulkan", "cpu", "cuda")   # whisper.cpp の機器(既定 vulkan。cuda は F1 F0-2 の CUDA 版 = 実行ファイルのフォルダも cuda。入口の flow/live_tx がこの PC の設定 flow/machine.py から決めて、既定と違うときだけ 5 つ目の引数で渡す。RS7-1 S1)
WHISPER, HAAS = "whisper.cpp", "haas-speechcpp"
ENGINES = (WHISPER, HAAS)   # 6 つ目の引数(既定 whisper.cpp。入口が Haas のときだけ渡す)
WHISPER_MODEL = "large-v3"   # Haas が動かない時に読み直す whisper.cpp のモデル(入口の live_tx.DEFAULT_MODEL と同じ)
HAAS_ROWS = {"engine": HAAS, "wordSplit": True, "splitChars": 24, "stripPunct": True}   # Haas の区切り(12〜28 秒で 1 行)を編集と同じ行の作りで分ける


def recognize(data_dir, model, wav, device="vulkan", engine=WHISPER):
    """-> 出力 json の中身(dict)。engine = haas-speechcpp なら Haas(動かなければ whisper.cpp で読み直す)"""
    if engine == HAAS:
        return recognize_haas(data_dir, model, wav, device)
    _paths()
    from pipeline.transcribe import tx_engines   # 認識エンジンの口(numpy などはこの子プロセスの中だけ)
    spec = tx_engines.WCPP_MODELS.get(model)
    if spec is None:
        return {"ok": False, "reason": "whisper.cpp で使えないモデルです: %s" % str(model)[:40]}
    exe = os.path.join(tx_engines.wcpp_bin_dir(data_dir, device), tx_engines.WCPP_EXE)
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
            "gpu": getattr(eng, "gpu_name", "") or "", "model": model, "engine": WHISPER}


def recognize_haas(data_dir, model, wav, device="vulkan"):
    """Haas(speech.cpp)で読む -> 出力 json の中身。動かなければ whisper.cpp(large-v3)で読み直し、fallback に Haas の理由を残す"""
    _paths()
    from pipeline.transcribe import tx_engines, postproc, recognize as rc
    from ytt import txbase
    spec = tx_engines.HAAS_GGUF_MODELS.get(model)
    if spec is None:
        return {"ok": False, "reason": "Haas(speech.cpp)で使えないモデルです: %s" % str(model)[:40]}
    if not tx_engines.HaasSpeechCpp.COMMAND and not os.path.isfile(txbase.speech_exe(data_dir)):
        why = "speech.cpp がありません(%s)" % txbase.speech_exe(data_dir)
    elif not os.path.isfile(os.path.join(tx_engines.haas_gguf_dir(data_dir), spec["file"])):
        why = "Haas のモデルがありません(%s)" % spec["file"]
    else:
        why = None
    if why is None:
        os.environ[tx_engines.NO_FETCH_ENV] = "1"   # 入口が確かめたモデルだけ使う(ここでは取りに行かない)
        t0 = time.time()
        eng = None
        try:
            eng = tx_engines.HaasSpeechCpp.create(model, "cpu" if device == "cpu" else "vulkan", data_dir=data_dir)
            segs, info = eng.transcribe(wav, language="ja")
            segs = [rc.seg_to_dict(s) for s in segs]
            rows = [{"start": round(float(r["start"]), 2), "end": round(float(r["end"]), 2), "text": str(r.get("text") or "").strip()}
                    for r in postproc.expand_segments(iter(segs), HAAS_ROWS, info.duration)]
            rows = [r for r in rows if r["text"]]
            return {"ok": True, "text": "".join(r["text"] for r in rows), "rows": rows, "sec": round(time.time() - t0, 1),
                    "gpu": getattr(eng, "gpu_name", "") or "", "model": model, "engine": HAAS}
        except tx_engines.EngineError as e:
            why = "%s: %s" % (e.code, e.message[:200])
        finally:
            if eng is not None:
                eng.close()
    back = recognize(data_dir, WHISPER_MODEL, wav, "cuda" if device == "cuda" else "vulkan")   # Haas が動かない: whisper.cpp で(whisper を消すまで)
    if back.get("ok"):
        back["fallback"] = why
        return back
    return {"ok": False, "reason": "Haas: %s / whisper.cpp: %s" % (why, back.get("reason") or "")}


def main(argv):
    if len(argv) not in (5, 6, 7) or (len(argv) >= 6 and argv[5] not in DEVICES) or (len(argv) == 7 and argv[6] not in ENGINES):
        print("usage: live_tx_worker.py <data_dir> <model> <wav> <out.json> [vulkan|cpu|cuda] [whisper.cpp|haas-speechcpp]", file=sys.stderr)
        return 2
    data_dir, model, wav, out = argv[1:5]
    device = argv[5] if len(argv) >= 6 else DEVICES[0]
    engine = argv[6] if len(argv) == 7 else WHISPER
    _paths()
    from ytt import fsio   # 書きかけを入口に読ませない(一時ファイル → 置き換え)
    try:
        doc = recognize(data_dir, model, wav, device, engine)
    except Exception as e:   # noqa: BLE001  (理由を入口へ返す。何が起きても json を書く)
        doc = {"ok": False, "reason": "%s: %s" % (e.__class__.__name__, str(e)[:300])}
    fsio.write_json(out, doc, indent=None)
    return 0 if doc.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
