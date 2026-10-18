# -*- coding: utf-8 -*-
"""flow/livehost(ライブの親の口。役割で組み直す RS7-2 G0)のテスト。  py -3.12 -m unittest src/flow/tests/test_livehost.py -v

- ライブ係 LiveSession(flow/livesession.py。入口の Live はそれを継ぐ)が口 LiveHost の名前を全部持ち、メソッドは口の引数を受けられる
- 子 4 つは LiveSession を親に持つ
- close の順: 終わりの印 → 検出 → 配信中の文字起こし → 作り直し → 書き出し → 録画の部品
"""
import os
os.environ.setdefault("YTT_DATA_DIR", "inplace")   # 作業データは読み書きしない(一時フォルダだけ)
import shutil
import sys
import unittest

SRC = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))   # tests -> flow -> src
sys.path.insert(0, SRC)
from ytt import testkit  # noqa: E402
from flow import livehost as H, livesession as LS  # noqa: E402


def host_names():
    """LiveHost に並べた属性とメソッドの名前"""
    own = vars(H.LiveHost)
    return set(own.get("__annotations__", {})) | {k for k, v in own.items() if callable(v) and not (k.startswith("__") and k.endswith("__"))}


class LiveTest(unittest.TestCase):
    """ライブ係(LiveSession)"""

    def setUp(self):
        self.tmp = testkit.tempdir(self, "ytt-livehost-live-")
        self.logs = []
        self.live = LS.LiveSession(self.tmp, os.path.join(self.tmp, "logs"), cfg=lambda: {}, log=self.logs.append, spawn=False,
                                   store_dir=os.path.join(self.tmp, "live"), out_dir=lambda: os.path.join(self.tmp, "out"))

    def tearDown(self):
        self.live.detector.stop()
        shutil.rmtree(self.tmp, ignore_errors=True)


    def test_close_order(self):
        """入口の終了: 終わりの印 → 検出 → 配信中の文字起こし → 作り直し → 書き出し → 録画の部品"""
        lv, calls = self.live, []

        class Closer:
            def __init__(self, name):
                self.name = name

            def close(self):
                calls.append(self.name)

        lv.detector.stop = lambda: calls.append(("detector", lv._halt.is_set(), lv.wake.is_set()))
        lv.livetx.close = lambda: calls.append("livetx")
        lv._archiver, lv._exporter = Closer("archiver"), Closer("exporter")
        lv.stop_recorder = lambda: calls.append("recorder")
        lv.close()
        self.assertEqual(calls, [("detector", True, True), "livetx", "archiver", "exporter", "recorder"])

    def test_close_order_unused_parts(self):
        """作り直し・書き出しを使っていなければ作らずに飛ばす。録画の部品を止める途中の不具合で終了を止めない"""
        lv, calls = self.live, []
        lv.detector.stop = lambda: calls.append("detector")
        lv.livetx.close = lambda: calls.append("livetx")

        def boom():
            calls.append("recorder")
            raise RuntimeError("止められない")
        lv.stop_recorder = boom
        lv.close()
        self.assertEqual(calls, ["detector", "livetx", "recorder"])
        self.assertIsNone(lv._exporter)
        self.assertIsNone(lv._archiver)
        self.assertTrue(any("録画の部品を止める途中でエラー" in m for m in self.logs), self.logs)


if __name__ == "__main__":
    unittest.main()
