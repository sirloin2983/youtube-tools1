"""テストの共通の下ごしらえ(2026-10-18 テストの見直し TESTREV。notes:plan/test-review.md の 6)。

各層の tests/ が同じ物を写して持っていた「一時フォルダ・JSON の読み書き・偽の HTTP サーバー・作業データの切り離し」を 1 か所に置く。
テストからだけ使う(本体のコードは import しない)。ytt は一番下の層なので、どの層のテストからも読める。

    from ytt import testkit
    class T(testkit.TempCase):            # self.tmp(一時フォルダ・後で消す)・self.path(...)・self.write_json / read_json
        def test_x(self):
            p = self.write_json("a/b.json", {"k": 1})
            url, seen = testkit.serve(self, Handler)   # 偽のサーバー(127.0.0.1・空きの番号・後で止める)

テストの決まり(消音・外への口は偽物・YTT_DATA_DIR)は notes:docs/spec/code.md の 5〜7。
"""
import contextlib
import http.server
import json
import os
import shutil
import tempfile
import threading
import unittest


def write_json(path, obj):
    """path へ JSON を書く(親のフォルダも作る)。path を返す。"""
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False)
    return path


def read_json(path, default=None):
    """path の JSON を読む。無ければ default。"""
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return default


def write_text(path, text):
    """path へ文字を書く(親のフォルダも作る・UTF-8・改行はそのまま)。path を返す。"""
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as f:
        f.write(text)
    return path


def tempdir(case, prefix="ytt-test-"):
    """case(TestCase)の間だけある一時フォルダを作って返す(終わりに消す)。"""
    d = tempfile.mkdtemp(prefix=prefix)
    case.addCleanup(shutil.rmtree, d, ignore_errors=True)
    return d


@contextlib.contextmanager
def env(**values):
    """環境変数をこの中だけ変える(None は消す)。"""
    old = {k: os.environ.get(k) for k in values}
    try:
        for k, v in values.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = str(v)
        yield
    finally:
        for k, v in old.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


def data_dir(case, prefix="ytt-data-"):
    """作業データの置き場所(YTT_DATA_DIR)を一時フォルダに切り離す。case の間だけ。フォルダを返す。"""
    d = tempdir(case, prefix)
    cm = env(YTT_DATA_DIR=d)
    cm.__enter__()
    case.addCleanup(cm.__exit__, None, None, None)
    return d


def serve(case, handler, server_cls=http.server.ThreadingHTTPServer):
    """偽の HTTP サーバーを 127.0.0.1 の空いた番号で起こす(case の終わりに止める)。(url, server) を返す。"""
    srv = server_cls(("127.0.0.1", 0), handler)
    srv.daemon_threads = True
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    case.addCleanup(srv.server_close)
    case.addCleanup(srv.shutdown)
    return "http://127.0.0.1:%d" % srv.server_address[1], srv


class TempCase(unittest.TestCase):
    """setUp で一時フォルダ self.tmp を作る(終わりに消す)TestCase。TMP_PREFIX で名前の頭を変えられる。"""
    TMP_PREFIX = "ytt-test-"

    def setUp(self):
        super().setUp()
        self.tmp = tempdir(self, self.TMP_PREFIX)

    def path(self, *parts):
        """self.tmp の下のパス"""
        return os.path.join(self.tmp, *parts)

    def write_json(self, rel, obj):
        return write_json(self.path(*rel.split("/")), obj)

    def read_json(self, rel, default=None):
        return read_json(self.path(*rel.split("/")), default)

    def write_text(self, rel, text):
        return write_text(self.path(*rel.split("/")), text)
