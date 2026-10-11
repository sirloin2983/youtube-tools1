# -*- coding: utf-8 -*-
"""RS8 の ② の口 S2: スタジオの解析(an)・書き出し(ex)・配信の検索(se)が掲示板(flow/board.py)に載る。  py -3.10 -m unittest src/studio/tests/test_board_s2.py
状態が変わったら、その id がその state で載る。取り消し・やり直しは掲示板の id で。"""
import os
os.environ.setdefault("YTT_DATA_DIR", "inplace")   # 作業データは読み書きしない
os.environ["STUDIO_FAKE"] = "1"
import sys
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))   # ツールのフォルダ(studio/)
import startup  # noqa: E402  (src を sys.path に足し、スタジオのフォルダを ytt/studio_env に知らせる)
import serve  # noqa: E402
from flow import batch as batch_mod, board as B  # noqa: E402
from human.find import rank  # noqa: E402
from pipeline.export import exporter  # noqa: E402


class Store:
    def has(self, vid):
        return True

    def ensure(self, src, title, channel):
        return {"title": title, "channel": channel}


def state_of(b, jid):
    j = b.get(jid)
    return j and j["state"]


class TestAnalyze(unittest.TestCase):
    def new(self):
        bt, b = batch_mod.Batch(Store()), B.Board()
        bt.attach_board(b)
        bt.start = lambda: None   # 糸は起こさない
        it = bt._new_item({"kind": "youtube", "videoId": "abcdefghijk", "name": "abcdefghijk"}, {}, "配信A", "ch")
        bt.items.append(it)
        return bt, b, it

    def test_states_on_board(self):
        bt, b, it = self.new()
        b.refresh()
        j = b.get("an:" + it["qid"])
        self.assertEqual((j["kind"], j["state"], j["canCancel"], j["title"]), ("analyze", "queued", True, "配信A"))
        it["status"] = "running"
        b.refresh()
        self.assertEqual(state_of(b, "an:" + it["qid"]), "running")
        bt._finish(it, "error", "だめ")
        b.refresh()
        j = b.get("an:" + it["qid"])
        self.assertEqual((j["state"], j["error"]["text"], j["canRetry"]), ("error", "だめ", True))

    def test_cancel_and_retry_by_board_id(self):
        bt, b, it = self.new()
        j = b.cancel("an:" + it["qid"])
        self.assertEqual(j["state"], "skipped")
        new = b.retry("an:" + it["qid"])
        self.assertEqual((new["state"], new["id"] != "an:" + it["qid"]), ("queued", True))
        with self.assertRaises(B.NotFound):
            b.cancel("an:nai")


class TestExport(unittest.TestCase):
    def setUp(self):
        self.addCleanup(exporter._jobs.clear)
        exporter._jobs.clear()
        self.b = B.Board()
        self.b.register("ex", source=exporter.board_jobs, cancel=exporter.board_cancel)

    def job(self, state="running"):
        j = {"id": "e1", "videoId": "abcdefghijk", "state": state, "cancel": False, "proc": None, "created": time.time(),
             "items": [{"id": "m1", "status": "running", "progress": 0.5, "path": None, "error": None}]}
        exporter._jobs["e1"] = j
        return j

    def test_states_on_board(self):
        j = self.job()
        self.b.refresh()
        self.assertEqual((state_of(self.b, "ex:e1"), self.b.get("ex:e1")["canCancel"], self.b.get("ex:e1")["progress"]), ("running", True, 0.5))
        j["state"] = "done"
        j["items"][0].update(status="done", progress=1.0, path=os.path.abspath("x.mp4"))
        self.b.refresh()
        self.assertEqual((state_of(self.b, "ex:e1"), "path" in self.b.get("ex:e1")["target"]), ("done", True))

    def test_cancel_by_board_id(self):
        j = self.job()
        self.b.cancel("ex:e1")
        self.assertTrue(j["cancel"])
        j["state"] = "cancelled"
        with self.assertRaises(B.Refused):
            self.b.cancel("ex:e1")


class TestSearch(unittest.TestCase):
    def setUp(self):
        self.addCleanup(rank._jobs.clear)
        rank._jobs.clear()

    def test_states_cancel_retry(self):
        b = B.Board()
        rank.attach_board(b)
        spec = {"agencies": []}
        rank._jobs["s1"] = {"id": "s1", "state": "running", "phase": "開始", "progress": 0.2, "cancel": False, "error": "", "result": None, "created": 1, "spec": spec}
        b.refresh()
        self.assertEqual((state_of(b, "se:s1"), b.get("se:s1")["canCancel"]), ("running", True))
        b.cancel("se:s1")
        self.assertTrue(rank._jobs["s1"]["cancel"])
        rank._jobs["s1"]["state"] = "cancelled"
        calls = []
        orig = rank._start_search
        rank._start_search = lambda s: calls.append(s) or {"id": "s2", "state": "running", "phase": "開始", "progress": 0.0, "cancel": False, "error": "", "created": 2}
        self.addCleanup(setattr, rank, "_start_search", orig)
        new = b.retry("se:s1")
        self.assertEqual((new["id"], new["state"], calls), ("se:s2", "running", [spec]))


class TestWiring(unittest.TestCase):
    def test_serve_attach_board(self):
        serve.init()
        b = B.Board()
        serve.attach_board(b)
        self.assertEqual(b.snapshot()["jobs"], [])


if __name__ == "__main__":
    unittest.main()
