# -*- coding: utf-8 -*-
"""人の操作のテストが共有する、一時の作業データの準備(S4)。

テストの名前ではない(unittest は読まない)。tests/human を sys.path に入れて `from _workdata import temporary_workdata` で使う。
一時フォルダを作り、作業データ(workdata)の六つの置き場所を一時フォルダの下へ向け、transcripts を作る。
六つの値の保存・復元は addCleanup で登録するので、準備の途中で例外が出ても、テストの本体が落ちても戻ってから消す。
"""
import os
import shutil
import tempfile

from ytt import workdata

_NAMES = ("DATA_DIR", "TX_DIR", "TMP_DIR", "SETTINGS", "FEEDBACK")


def temporary_workdata(testcase, prefix):
    """一時フォルダを作って返す。作業データは <一時>/data、文書は <一時>/data/transcripts(作成済み)"""
    tmp = tempfile.mkdtemp(prefix=prefix)
    testcase.addCleanup(shutil.rmtree, tmp, True)
    saved = {n: getattr(workdata, n) for n in _NAMES}
    testcase.addCleanup(lambda: [setattr(workdata, n, v) for n, v in saved.items()])
    workdata.set_data_dir(os.path.join(tmp, "data"))
    os.makedirs(workdata.TX_DIR)
    return tmp
