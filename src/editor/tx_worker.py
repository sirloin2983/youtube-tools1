# -*- coding: utf-8 -*-
"""転送(RS5 で消す): 認識ワーカーの本体は src/pipeline/transcribe/worker.py に移した(役割で組み直す RS2-9)。

古いコードのまま動いている入口(編集の serve が認識ワーカーをこの旧い場所のパスで起動する)が、ワーカーを起動し直しても動くようにするための入口。
src を sys.path に入れて新しい場所のスクリプトを __main__ として動かす(引数 --probe もそのまま)。やり取り(op の名前・イベント)は同じ。
"""
import os
import runpy
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.dirname(HERE)
if SRC not in sys.path:
    sys.path.insert(0, SRC)
TARGET = os.path.join(SRC, "pipeline", "transcribe", "worker.py")

if __name__ == "__main__":
    runpy.run_path(TARGET, run_name="__main__")
