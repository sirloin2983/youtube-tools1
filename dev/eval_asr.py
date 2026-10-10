# -*- coding: utf-8 -*-
"""転送(RS5 で消す): 測る道具の本体は src/eval/tools/eval_asr.py に移した(役割で組み直す RS4-4。旧い場所は起動用の転送だけ)。

古い入口の夜の自動測定(accuracy.py が dev/eval_asr.py を子プロセスで起こす)と、旧いコマンド(py -3.10 dev/eval_asr.py …)を動かし続けるための入口。
新しい場所のスクリプトを __main__ として動かす(引数・標準出力・終了コードはそのまま)。新しいコマンドは py -3.10 src/eval/tools/eval_asr.py …
"""
import os
import runpy

HERE = os.path.dirname(os.path.abspath(__file__))
TARGET = os.path.join(os.path.dirname(HERE), "src", "eval", "tools", "eval_asr.py")

if __name__ == "__main__":
    runpy.run_path(TARGET, run_name="__main__")
