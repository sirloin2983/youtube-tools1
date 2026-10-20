#!/usr/bin/env python3
"""テスト用の偽の whisper-cli(tx_engines.WhisperCpp.COMMAND に [python, このファイル] を入れて使う)。

本物と同じく、ただ1つの引数 @応答ファイル(1行1引数・UTF-8)を読み、-of <名前> の <名前>.json に -ojf の形で結果を書く。
標準エラーには GPU の初期化の行と進み具合を出す(-ng なら CPU)。環境変数:
  FAKE_WCPP_GPU=none   GPU が見つからない(「no GPU found」)
  FAKE_WCPP_SLEEP=秒   終わる前に待つ(取り消しの確認)
  FAKE_WCPP_ARGS=パス  受け取った引数を JSON で書く(引数の確認)
  FAKE_WCPP_FAIL=1     終了コード 3 で失敗する
"""
import json
import os
import sys
import time
import wave


def main():
    if len(sys.argv) != 2 or not sys.argv[1].startswith("@"):
        sys.stderr.write("usage: @args\n")
        return 2
    with open(sys.argv[1][1:], encoding="utf-8") as f:
        args = [x for x in f.read().split("\n") if x != ""]
    if os.environ.get("FAKE_WCPP_ARGS"):
        with open(os.environ["FAKE_WCPP_ARGS"], "w", encoding="utf-8") as f:
            json.dump(args, f, ensure_ascii=False)
    opt = {}
    i = 0
    while i < len(args):
        a = args[i]
        if a in ("-ojf", "-pp", "-ng", "-nf", "-nfa", "--vad"):
            opt[a] = True
            i += 1
        else:
            opt[a] = args[i + 1]
            i += 2
    if "-ng" in opt:
        sys.stderr.write("whisper_backend_init_gpu: no GPU found\n")
    elif os.environ.get("FAKE_WCPP_GPU") == "none":
        sys.stderr.write("whisper_backend_init_gpu: no GPU found\n")
    else:
        sys.stderr.write("ggml_vulkan: Found 1 Vulkan devices:\n")
        sys.stderr.write("ggml_vulkan: 0 = AMD Radeon RX 7800 XT (AMD proprietary driver) | uma: 0 | fp16: 1\n")
        sys.stderr.write("whisper_backend_init_gpu: using Vulkan0 backend\n")
    if "--vad" in opt:   # 本物も、声の検出のモデル(CPU)を読むときに出す(認識のモデルの GPU の行より後)
        sys.stderr.write("whisper_backend_init_gpu: no GPU found\n")
    sys.stderr.flush()
    if os.environ.get("FAKE_WCPP_FAIL") == "1":
        sys.stderr.write("error: failed to read audio\n")
        return 3
    with wave.open(opt["-f"], "rb") as w:
        total_ms = int(w.getnframes() * 1000 / w.getframerate())
    for p in (25, 50, 75, 100):
        sys.stderr.write("whisper_print_progress_callback: progress = %3d%%\n" % p)
        sys.stderr.flush()
    time.sleep(float(os.environ.get("FAKE_WCPP_SLEEP", "0")))
    segs, t, k = [], 0, 0
    while t < total_ms - 50:
        e = min(total_ms, t + 4000)
        k += 1
        mid = (t + e) // 2
        segs.append({"timestamps": {"from": "", "to": ""}, "offsets": {"from": t, "to": e}, "text": "テスト文%d" % k,
                     "tokens": [{"text": "[_BEG_]", "offsets": {"from": t, "to": t}, "id": 50365, "p": 0.9},
                                {"text": "テスト", "offsets": {"from": t, "to": mid}, "id": 1, "p": 0.8},
                                {"text": "文%d" % k, "offsets": {"from": mid, "to": e}, "id": 2, "p": 0.5},
                                {"text": "[_TT_200]", "offsets": {"from": e, "to": e}, "id": 50565, "p": 0.9}]})
        t = e
    out = {"systeminfo": "fake", "model": {}, "params": {"language": opt.get("-l", "")},
           "result": {"language": opt.get("-l", "ja") if opt.get("-l") != "auto" else "ja"}, "transcription": segs}
    with open(opt["-of"] + ".json", "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False)
    return 0


if __name__ == "__main__":
    sys.exit(main())
