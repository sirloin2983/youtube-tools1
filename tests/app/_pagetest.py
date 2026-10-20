# -*- coding: utf-8 -*-
"""入口(src/app/server.py)を一時のデータで立てて GET で画面の配り方を確かめるテストの共通の土台(test_cases_page・test_check_page)。

使い方: `class XTest(PageServerTest): TMP_PREFIX = "ytt-x-page-"` として self.req(path, headers) を呼ぶ。
クラスごとに一時のフォルダ・環境変数(YTT_RUNTIME_DIR)・Supervisor・ポート・サーバーを独立に作る。
準備の途中で失敗しても、そこまでに作った物(サーバー・環境変数・一時のフォルダ)は addClassCleanup で必ず戻す。"""
import http.client
import os
os.environ.setdefault("YTT_DATA_DIR", "inplace")   # テストは作業データを本物の置き場所に書かない(ytt.datadir)
import shutil
import sys
import tempfile
import threading
import unittest
from unittest import mock

TESTS = os.path.dirname(os.path.abspath(__file__))   # tests/app
SRC = os.path.join(os.path.dirname(os.path.dirname(TESTS)), "src")
sys.path.insert(0, os.path.join(SRC, "app"))
sys.path.insert(0, os.path.join(os.path.dirname(SRC), "tests", "app"))
if SRC not in sys.path:
    sys.path.append(SRC)
from app import server as L  # noqa: E402
from test_launch import free_ports  # noqa: E402


class PageServerTest(unittest.TestCase):
    TMP_PREFIX = "ytt-page-"

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix=cls.TMP_PREFIX)
        cls.addClassCleanup(shutil.rmtree, cls.tmp, ignore_errors=True)
        cls.env = mock.patch.dict(os.environ, {"YTT_RUNTIME_DIR": os.path.join(cls.tmp, ".runtime")})
        cls.env.start()
        cls.addClassCleanup(cls.env.stop)
        cls.sup = L.Supervisor(cls.tmp, ready_timeout=5, stop_timeout=5, poll=0.5, log=lambda m: None,
                               ports=dict(zip(L.TOOL_IDS, free_ports(3))), mounts=())
        cls.addClassCleanup(cls.sup.close)
        cls.srv, cls.port = L.make_server(0, cls.sup)
        cls.addClassCleanup(cls.srv.server_close)
        cls.sup.attach(cls.srv)
        cls.th = threading.Thread(target=cls.srv.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)   # 止めるのを待たない
        cls.th.start()
        cls.addClassCleanup(cls.srv.shutdown)   # 戻す順は後に足した物から = shutdown → server_close → sup.close → env.stop → 一時のフォルダ
        cls.host = "127.0.0.1:%d" % cls.port

    def req(self, path, headers=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=30)
        h = {"Host": self.host}
        h.update(headers or {})
        conn.request("GET", path, headers=h)
        r = conn.getresponse()
        body = r.read()
        conn.close()
        return r, body
