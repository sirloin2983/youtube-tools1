# -*- coding: utf-8 -*-
"""旧パスの起動用の転送。入口の本体は src/app/server.py(RS7-2 G5b で移した)。手打ちの `py -3.10 src/home/launch.py ...` を動かし続けるためだけにある。
start.bat・再起動(manage/ops/restart)・テストは新しい場所を直に呼ぶ。import はできない(`from app import server` を使う)"""
import os
import runpy
import sys

if __name__ == "__main__":
    _script = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "app", "server.py")
    sys.argv[0] = _script
    runpy.run_path(_script, run_name="__main__")
