#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""cut2resolve のコマンドの旧い場所の起動用(転送。役割で組み直す RS1-2。2026-10-09。RS5 で消す)。

本体は src/pipeline/pack/cut2resolve.py に移した。cut2resolve.bat が "%~dp0cut2resolve.py" を動かすので、ここから本体を動かす。
モジュールとしては読まない(入口の取り込みが部品の名前を調べるだけ。中身は import しない)。
"""
import os
import runpy
import sys

if __name__ == "__main__":
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))   # src
    runpy.run_module("pipeline.pack.cut2resolve", run_name="__main__", alter_sys=True)
