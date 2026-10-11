"""リポジトリの中のフォルダの並び(2026-10-07 に整理。段0 2026-09-30 の改名は `docs/design/phase0-restructure.md`)。

    <リポジトリ直下>/            start.bat・push.bat・README.txt・AGENTS.md・setup/・plan/・docs/・dev/(ユーザーと AI が触る)
      src/                       動くコード = ツール(home・studio・editor・cut2resolve・recorder)・共通部品(ytt・ui-kit)・役割の層(pipeline・human・manage・eval・app)
      friend-apps/               友人用の Windows アプリ(holo-colors・request-sender。C#)

フォルダ名と識別子を分ける: キーはツールの ID(作業データのフォルダ名・.runtime の ID・URL の /studio/ など。互換のため変えない)、
値はフォルダ名(2026-09-30 に app → home・clip-studio → studio・transcribe-tool → editor に変えた)。
フォルダ名を知っている場所はここを読む(次にフォルダを変えるとき、直す場所を1つにするため)。

「root」の意味: ツールの親のフォルダ(= `src/`。テストが一時フォルダにツールと共通のコードを平らに写したときはその一時フォルダ)。
入口の server.py の ROOT・datadir・txindex・各テストの REPO はこの意味で使う(src_root)。
dev/・setup/・friend-apps/ のようにリポジトリ直下にあるものを探すときだけ repo_root を使う。
各ツールが共通部品を探す `_load_core()`(「ツールのフォルダの1つ上」)は ytt を読む前なので、ここを使わない。
"""
import os

SRC_DIR = "src"                     # 動くコードの置き場所(リポジトリ直下からの相対)
FRIEND_APPS_DIR = "friend-apps"     # 友人用の Windows アプリの置き場所(同上)
TOOL_DIRS = {"app": "home", "studio": "studio", "transcribe": "editor", "cut2resolve": "cut2resolve"}   # src/ の中のフォルダ名
RECORDER_DIR = "recorder"           # src/ の中(録画の部品の作業データ inplace の data/・AGENTS.md・README.txt のフォルダ。コードは RECORDER_SCRIPT)
RECORDER_SCRIPT = os.path.join("pipeline", "ingest", "recorder.py")   # src からの相対(録画の部品。入口と別のプロセス。パスで起動する)
UI_KIT_DIR = "ui-kit"               # src/ の中(共通の見た目の正本)
PACK_CORE = os.path.join("pipeline", "pack", "cut2resolve_core.py")   # src/ の中(cut2resolve の版 VERSION の正。RS1-2 で cut2resolve から移した)
HOLO_COLORS_DIR = os.path.join(FRIEND_APPS_DIR, "holo-colors")          # リポジトリ直下からの相対
REQUEST_SENDER_DIR = os.path.join(FRIEND_APPS_DIR, "request-sender")    # 同上
# src/ の中の共通のコード(ツールのフォルダではない物)。役割で組み直す計画(plan/role-restructure.md)の層のパッケージと、
# (旧い名前の転送 ytt_core は RS5-G で消した)。ツールを一時フォルダに写すテストは、ツールと一緒にこれを全部写す(copy_shared_code)
SHARED_CODE_DIRS = ("ytt", "pipeline", "flow", "human", "manage", "eval", "app")   # flow = ② 管理(RS6 a-0)


def src_root():
    """ツールと共通のコードの親のフォルダ(この ytt の1つ上 = <リポジトリ直下>/src)"""
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


def copy_shared_code(dst, ignore=None, root=None):
    """共通のコード(SHARED_CODE_DIRS)を dst の直下に写す(ツールを一時フォルダに写すテスト用。本物と同じ並びにする)。
    root の既定は src_root()。ignore は shutil.copytree の ignore"""
    import shutil
    for d in SHARED_CODE_DIRS:
        shutil.copytree(os.path.join(root or src_root(), d), os.path.join(dst, d), ignore=ignore)
