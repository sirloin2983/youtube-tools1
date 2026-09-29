"""リポジトリの中のフォルダの並び(段0 2026-09-30。`docs/plan/phase0-restructure.md`)。

フォルダ名と識別子を分ける: キーはツールの ID(作業データのフォルダ名・.runtime の ID・URL の /studio/ など。互換のため変えない)、
値はリポジトリの中のフォルダ名(2026-09-30 に app → home・clip-studio → studio・transcribe-tool → editor に変えた)。
フォルダ名を知っている場所はここを読む(次にフォルダを変える = パッケージ化のとき、直す場所を1つにするため)。
各ツールが ytt_core を探す `_load_core()`(「ツールのフォルダの1つ上 = リポジトリ直下」)は ytt_core を読む前なので、ここを使わない。
"""
import os

TOOL_DIRS = {"app": "home", "studio": "studio", "transcribe": "editor", "cut2resolve": "cut2resolve"}
HOLO_COLORS_DIR = "holo-colors"


def repo_root():
    """リポジトリ直下(この ytt_core の1つ上)"""
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def tool_dir(tool, root=None):
    """ツールのフォルダ(<リポジトリ直下>/<フォルダ名>)。tool はツールの ID("app"・"studio"・"transcribe"・"cut2resolve")"""
    return os.path.join(root or repo_root(), TOOL_DIRS[tool])
