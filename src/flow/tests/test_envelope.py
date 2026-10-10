# -*- coding: utf-8 -*-
"""flow/envelope.py(依頼の封筒。RS7-1 S3)のテスト。  py -3.10 -m unittest src/flow/tests/test_envelope.py -v"""
import os
os.environ.setdefault("YTT_DATA_DIR", "inplace")
import sys
import unittest

SRC = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, SRC)
from flow import envelope as E  # noqa: E402


class TestCheck(unittest.TestCase):
    def test_minimal_forms_get_defaults(self):
        got = E.check({"id": "a1", "kind": "docs", "input": {"docId": "d1"}}, now=12.5)
        self.assertEqual(got, {"id": "a1", "kind": "docs", "input": {"title": "", "docId": "d1"}, "requestId": None,
                               "deliver": {"dir": None, "batch": None, "pool": None}, "note": "", "createdAt": 12500,
                               "specVersion": E.SPEC_VERSION, "legacy": {"mode": None, "onFail": None, "streamer": None}})
        url = E.check({"id": "a", "kind": "url", "input": {"url": "https://youtu.be/abcdefghijk", "marks": ["m1", "m1"]}})
        self.assertEqual((url["input"]["videoId"], url["input"]["marks"]), ("abcdefghijk", ["m1"]))
        f = E.check({"id": "a", "kind": "file", "input": {"path": "C:/x.mp4", "title": "題"},
                     "deliver": {"dir": "D:/out", "batch": 3, "pool": {"key": "k", "meta": {"phase": "live", "x": 1}}}, "note": "メモ"})
        self.assertEqual(f["deliver"], {"dir": "D:/out", "batch": 3, "pool": {"key": "k", "rid": "", "title": "", "meta": {"phase": "live"}}})

    def test_live_input(self):
        url = "https://www.youtube.com/watch?v=" + VID
        got = E.check({"id": "L1", "kind": "live", "input": {"url": url, "title": "配信", "recorder": "rec1"}})
        self.assertEqual(got["input"], {"title": "配信", "videoId": VID, "url": url, "recorder": "rec1"})
        self.assertEqual(E.check({"id": "L1", "kind": "live", "input": {"videoId": VID}})["input"], {"title": "", "videoId": VID, "recorder": None})
        for inp, why in (({"videoId": VID, "marks": []}, "封筒.input.marks"), ({"url": "https://example.com/"}, "YouTube"), ({}, "videoId"),
                         ({"videoId": VID, "recorder": ""}, "recorder")):
            with self.assertRaises(ValueError, msg=inp) as cm:
                E.check({"id": "L1", "kind": "live", "input": inp})
            self.assertIn(why, str(cm.exception))

    def test_refusals_say_why(self):
        ok = {"id": "a", "kind": "docs", "input": {"docId": "d1"}}
        bad = [
            (dict(ok, extra=1), "知らない項目です: 封筒.extra"),
            (dict(ok, specVersion=2), "知らない束の版"),
            (dict(ok, specVersion=True), "知らない束の版"),
            (dict(ok, kind="nai"), "封筒.kind"),
            (dict(ok, id="../x"), "封筒.id"),
            (dict(ok, input={"docId": "d1", "path": "x"}), "封筒.input.path"),
            (dict(ok, input={}), "docId"),
            (dict(ok, deliver={"batch": 11}), "封筒.deliver.batch"),
            (dict(ok, deliver={"pool": {"x": 1}}), "封筒.deliver.pool"),
            (dict(ok, deliver={"where": 1}), "封筒.deliver.where"),
            (dict(ok, legacy={"onFail": "x"}), "封筒.legacy.onFail"),
            (dict(ok, createdAt=-1), "createdAt"),
            (dict(ok, requestId=""), "requestId"),
            ({"id": "a", "kind": "url", "input": {"url": "https://example.com/"}}, "YouTube"),
            ({"id": "a", "kind": "url", "input": {"videoId": VID, "duration": -3}}, "duration"),
            ({"id": "a", "kind": "url", "input": {"videoId": VID, "fresh": {"title": "t", "x": 1}}}, "fresh.x"),
            ({"id": "a", "kind": "file", "input": {"title": "t"}}, "path"),
            ("abc", "封筒"),
        ]
        for env, why in bad:
            with self.assertRaises(ValueError, msg=env) as cm:
                E.check(env)
            self.assertIn(why, str(cm.exception), env)


VID = "abcdefghijk"


if __name__ == "__main__":
    unittest.main()
