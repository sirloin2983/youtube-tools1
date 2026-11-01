# -*- coding: utf-8 -*-
"""偽の `speech diarize`(diarize.DIAR_COMMAND に [python, このファイル] を入れて使う)。音は読まない。
引数: diarize <モデル> --format json --device <機器> --threads N <wav>。
環境変数 FAKE_DIAR_FAIL = 失敗させる機器(auto など。その機器のときは終了コード 1)。標準出力に 1 行の JSON(区間 2 つ)"""
import json
import os
import sys

args = sys.argv[1:]
dev = args[args.index("--device") + 1]
if os.environ.get("FAKE_DIAR_FAIL") == dev:
    sys.stderr.write("ggml_vulkan: no device\n")
    sys.exit(1)
print(json.dumps({"file": args[-1], "segments": [{"start": 1.5, "end": 3.0, "speaker": 1}, {"start": 0.0, "end": 2.0, "speaker": 0}],
                  "device": dev}))
