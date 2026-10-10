# -*- coding: utf-8 -*-
"""転送(RS5 で消す): 配信中の候補の文字起こしの子プロセスの本体は src/pipeline/transcribe/live_tx_worker.py に移した(役割で組み直す RS3-1)。

古いコードのまま動いている入口(旧い live_tx が候補 1 本ごとに起動する)が、この旧い場所のパスで子プロセスを起動し直しても動くようにするための入口。
src を sys.path に入れて新しい場所のスクリプトを __main__ として動かす(引数もそのまま)。やり取り(引数・出力・ファイル)は同じ。
"""
import os
import runpy
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.dirname(HERE)
if SRC not in sys.path:
    sys.path.insert(0, SRC)
TARGET = os.path.join(SRC, "pipeline", "transcribe", "live_tx_worker.py")

if __name__ == "__main__":
    runpy.run_path(TARGET, run_name="__main__")
