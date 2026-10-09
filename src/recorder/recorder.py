# -*- coding: utf-8 -*-
"""転送(RS5 で消す): 録画の部品の本体は src/pipeline/ingest/recorder.py に移した(役割で組み直す RS1-3)。

古いコードのまま動いている入口が、旧い場所のこのファイルで録画の部品を起動しても動くようにするための入口。
src を sys.path に入れて新しい場所のスクリプトを __main__ として動かす(引数はそのまま)。版(VERSION)はここに持たない。
"""
import os
import runpy
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.dirname(HERE)
if SRC not in sys.path:
    sys.path.insert(0, SRC)
TARGET = os.path.join(SRC, "pipeline", "ingest", "recorder.py")

if __name__ == "__main__":
    runpy.run_path(TARGET, run_name="__main__")
