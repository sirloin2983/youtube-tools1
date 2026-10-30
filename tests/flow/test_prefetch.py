# -*- coding: utf-8 -*-
"""解析の先回り(flow/runqueue.Queue._prefetch_next。資料の git:before-1028-cleanup:plan/解析の先回り-設計.md)のテスト。
糸は回さず、待ちの列に実行を置いて、先回りの判定・B の番の解析の段・中止を直に呼ぶ。  py -3.12 -m unittest tests/flow/test_prefetch.py -v
"""
import os
os.environ.setdefault("YTT_DATA_DIR", "inplace")   # 作業データは読み書きしない(記録は一時フォルダ)
import sys
import unittest
from unittest import mock

SRC = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "src")
sys.path.insert(0, SRC)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))   # tests/(testkit)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import testkit  # noqa: E402
import _runfields as RF  # noqa: E402
from flow import runqueue as Q, run as R, tools as T  # noqa: E402

A, B = "aaaaaaaaaaa", "bbbbbbbbbbb"


class Tools(T.HttpTools):
    """スタジオの配信(解析の有無)・解析の順番(qid ごとの状態)を覚える道具"""

    def __init__(self):
        super().__init__(None)
        self.analysis = {}     # 配信 -> analysis(無ければ未解析)
        self.added, self.cancelled = [], []
        self.status = {}       # qid -> 状態

    def video(self, vid):
        v = {"kind": "youtube", "title": vid}
        if vid in self.analysis:
            v["analysis"] = self.analysis[vid]
        return 200, {"video": v}

    def analyze_add(self, item, settings):
        qid = "q%d" % (len(self.added) + 1)
        self.added.append((item["videoId"], qid))
        self.status[qid] = "running"
        return {"added": [{"qid": qid}]}

    def analyze_items(self):
        return [{"qid": q, "videoId": v, "status": self.status[q], "marks": 3} for v, q in self.added if q in self.status]

    def analyze_cancel(self, qid):
        self.cancelled.append(qid)
        self.status[qid] = "cancelled"


class PrefetchTest(unittest.TestCase):
    def setUp(self):
        tmp = testkit.tempdir(self)
        os.makedirs(os.path.join(tmp, "logs"))
        self.tools = Tools()
        self.q = Q.Queue(None, env={"YTT_MACHINE_FILE": os.path.join(tmp, "nai.json")}, poll=0.01, tools=self.tools, log_dir=os.path.join(tmp, "logs"))
        self.addCleanup(self.q.close)
        self.a = RF.run_of(A, "今の配信", "full", 1)
        self.a.state = "running"
        self.b = RF.run_of(B, "次の配信", "full", 1)
        self.q.runs.extend([self.a, self.b])

    def test_asks_next_analysis_once(self):
        """今の実行 A が文字起こしの段に入るとき、次の B の解析を B の配信で頼む(1 回だけ)"""
        pre = self.q._prefetch_next(self.a)
        self.assertEqual(self.tools.added, [(B, "q1")])
        self.assertEqual(pre["qid"], "q1")
        self.assertIs(self.b.prefetch, pre)
        self.assertIsNone(self.q._prefetch_next(self.a))   # もう頼んだ
        self.assertEqual(len(self.tools.added), 1)

    def test_does_not_ask(self):
        """同じ配信・解析済み・空き容量の下限・解析の段の無い実行では頼まない"""
        with mock.patch.object(self.q, "disk_check", lambda: {"freeGB": 1, "minGB": 10}):
            self.assertIsNone(self.q._prefetch_next(self.a))
        self.tools.analysis[B] = {"at": 1}   # 解析済み(重みの指定も無い)= skip
        with mock.patch.object(R, "redo_reason", lambda *a: None):
            self.assertIsNone(self.q._prefetch_next(self.a))
        same = RF.run_of(A, "同じ配信", "full", 1)
        self.q.runs[1:] = [same]
        self.assertIsNone(self.q._prefetch_next(self.a))
        doc = RF.run_of(None, "文書", R.DOC_MODE, None, doc_id="d1")
        self.q.runs[1:] = [doc]
        self.assertIsNone(self.q._prefetch_next(self.a))
        self.assertEqual(self.tools.added, [])

    def test_b_waits_prefetched_analysis(self):
        """B の番: 先回りの解析がまだ動いていれば、頼み直さずにそれを待つ(印 prefetched)"""
        self.q._prefetch_next(self.a)
        self.tools.status["q1"] = "done"
        st = self.b.step("analyze")
        self.q._step_analyze(self.b, st, {"kind": "youtube"})
        self.assertEqual(len(self.tools.added), 1)
        self.assertTrue(st["prefetched"])
        self.assertIn("解析しました", st["detail"])
        self.assertIsNone(self.b.prefetch)

    def test_b_skips_when_already_done(self):
        """B の番に解析が済んでいれば飛ばして、先回りだったと書く"""
        self.q._prefetch_next(self.a)
        st = self.b.step("analyze")
        with mock.patch.object(R, "redo_reason", lambda *a: None):
            self.q._step_analyze(self.b, st, {"kind": "youtube", "analysis": {"at": 1}})
        self.assertEqual((st["state"], st["prefetched"]), ("skip", True))
        self.assertIn("先に始めました", st["detail"])

    def test_b_asks_again_when_prefetch_failed(self):
        """先回りが失敗・消えていたら、B の番で今の形に頼み直す(B を失敗にしない)"""
        self.q._prefetch_next(self.a)
        self.tools.status["q1"] = "error"
        st = self.b.step("analyze")
        orig = self.tools.analyze_add

        def add(item, settings):
            got = orig(item, settings)
            self.tools.status[got["added"][0]["qid"]] = "done"
            return got
        self.tools.analyze_add = add
        self.q._step_analyze(self.b, st, {"kind": "youtube"})
        self.assertEqual([q for _v, q in self.tools.added], ["q1", "q2"])
        self.assertNotIn("prefetched", st)

    def test_cancel_queued_b_cancels_prefetch(self):
        self.q._prefetch_next(self.a)
        self.q.cancel(self.b.id)
        self.assertEqual(self.tools.cancelled, ["q1"])
        self.assertIsNone(self.b.prefetch)


if __name__ == "__main__":
    unittest.main()
