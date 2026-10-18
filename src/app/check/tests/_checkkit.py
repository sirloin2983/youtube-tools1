"""src/app/check/tests の共通の下ごしらえ(2026-10-18 テストの見直し)。test_ で始めない(流す対象ではない)。

各テストの頭にあった「src を sys.path へ・YTT_DATA_DIR の既定・JSON を書く write・一時フォルダ・Ctx」を 1 か所に置く。
使い方(テストの頭):
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import _checkkit as kit  # noqa: E402
"""
import os
import sys

os.environ.setdefault("YTT_DATA_DIR", "inplace")   # テストは作業データを本物の置き場所に書かない(ytt.datadir)
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))   # tests -> check -> app -> src
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from ytt import testkit  # noqa: E402
from human.check import apply  # noqa: E402

write = testkit.write_json   # write(path, obj): 親のフォルダも作って JSON を書く
tempdir = testkit.tempdir    # tempdir(case, prefix): case の間だけある一時フォルダ


class Ctx(apply.Context):
    pass
