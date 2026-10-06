"""リポジトリの中のフォルダの並び(2026-10-07 に整理。段0 2026-09-30 の改名は `docs/design/phase0-restructure.md`)。

    <リポジトリ直下>/            start.bat・push.bat・README.txt・AGENTS.md・setup/・plan/・docs/・dev/(ユーザーと AI が触る)
      src/                       動くコード = ツール(home・studio・editor・cut2resolve・recorder)と共通部品(ytt_core・ui-kit)
      friend-apps/               友人用の Windows アプリ(holo-colors・request-sender。C#)

フォルダ名と識別子を分ける: キーはツールの ID(作業データのフォルダ名・.runtime の ID・URL の /studio/ など。互換のため変えない)、
値はフォルダ名(2026-09-30 に app → home・clip-studio → studio・transcribe-tool → editor に変えた)。
フォルダ名を知っている場所はここを読む(次にフォルダを変えるとき、直す場所を1つにするため)。

「root」の意味: ツールの親のフォルダ(= `src/`。テストが一時フォルダにツールと ytt_core を平らに写したときはその一時フォルダ)。
入口の launch.py の ROOT・datadir・txindex・各テストの REPO はこの意味で使う(src_root)。
dev/・setup/・friend-apps/ のようにリポジトリ直下にあるものを探すときだけ repo_root を使う。
各ツールが ytt_core を探す `_load_core()`(「ツールのフォルダの1つ上」)は ytt_core を読む前なので、ここを使わない。
"""
import os

SRC_DIR = "src"                     # 動くコードの置き場所(リポジトリ直下からの相対)
FRIEND_APPS_DIR = "friend-apps"     # 友人用の Windows アプリの置き場所(同上)
TOOL_DIRS = {"app": "home", "studio": "studio", "transcribe": "editor", "cut2resolve": "cut2resolve"}   # src/ の中のフォルダ名
RECORDER_DIR = "recorder"           # src/ の中(録画の部品。入口と別のプロセス)
UI_KIT_DIR = "ui-kit"               # src/ の中(共通の見た目の正本)
HOLO_COLORS_DIR = os.path.join(FRIEND_APPS_DIR, "holo-colors")          # リポジトリ直下からの相対
REQUEST_SENDER_DIR = os.path.join(FRIEND_APPS_DIR, "request-sender")    # 同上


def src_root():
    """ツールと ytt_core の親のフォルダ(この ytt_core の1つ上 = <リポジトリ直下>/src)"""
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def repo_root(root=None):
    """リポジトリ直下(src の1つ上)。root を渡したら、それを src_root とみなしてその1つ上"""
    return os.path.dirname(os.path.abspath(root)) if root else os.path.dirname(src_root())


def tool_dir(tool, root=None):
    """ツールのフォルダ(<root>/<フォルダ名>。root の既定は src_root)。tool はツールの ID("app"・"studio"・"transcribe"・"cut2resolve")"""
    return os.path.join(root or src_root(), TOOL_DIRS[tool])


def holo_colors_dir(repo=None):
    """ホロカラーのフォルダ(members.json の場所)。repo の既定は repo_root()"""
    return os.path.join(repo or repo_root(), HOLO_COLORS_DIR)
