#!/usr/bin/env python3
"""Lua のファイルを lupa の LuaJIT で流す(Lua の実行環境が無い PC で、test_pack の Lua の通しに使う。開発用の依存 = setup/requirements-dev.txt)。
    py -3.12 run_lua.py <file.lua>
print は Lua の C の print なので、そのまま標準出力へ出る。Lua の失敗は標準エラーに出して終了コード 1"""
import sys


def engine():
    """LuaJIT(Resolve と同じ)。無ければ lupa の既定の Lua"""
    try:
        from lupa import luajit21 as lupa
    except ImportError:
        import lupa
    return lupa


def main():
    lupa = engine()
    rt = lupa.LuaRuntime()
    try:
        rt.globals().dofile(sys.argv[1])
    except lupa.LuaError as e:
        sys.stdout.flush()
        sys.stderr.write(str(e) + "\n")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
