# -*- coding: utf-8 -*-
"""flow/envelope.py(依頼の封筒。RS7-1 S3)のテスト。  py -3.12 -m unittest src/flow/tests/test_envelope.py -v"""
import os
os.environ.setdefault("YTT_DATA_DIR", "inplace")
import sys
import unittest

SRC = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, SRC)
from flow import envelope as E  # noqa: E402

V = {"specVersion": 2}


def env(**kw):
    return dict(V, **kw)


class TestCheck(unittest.TestCase):
    def test_minimal_forms_get_defaults(self):
        got = E.check(env(id="a1", kind="docs", input={"docId": "d1"}), now=12.5)
        self.assertEqual(got, {"id": "a1", "kind": "docs", "input": {"title": "", "docId": "d1"}, "requestId": None,
                               "deliver": {"dir": None, "pool": None, "origin": None, "tag": None}, "createdAt": 12500, "specVersion": 2})
        url = E.check(env(id="a", kind="url", input={"url": "https://youtu.be/abcdefghijk", "marks": ["m1", "m1"]}))
        self.assertEqual((url["input"]["videoId"], url["input"]["marks"]), ("abcdefghijk", ["m1"]))
        f = E.check(env(id="a", kind="file", input={"path": "C:/x.mp4", "title": "題"},
                        deliver={"dir": "D:/out", "pool": {"key": "k", "meta": {"phase": "live", "x": 1}}}))
        self.assertEqual(f["deliver"], {"dir": "D:/out", "pool": {"key": "k", "rid": "", "title": "", "meta": {"phase": "live"}}, "origin": None, "tag": None})

    def test_dropped_keys_are_read_and_discarded(self):
        """前に書いていた note・deliver.batch は断らずに読んで捨てる(出力に入れない。保存済みの待ちの列・録画の束のため)"""
        got = E.check(env(id="a", kind="docs", input={"docId": "d1"}, note="メモ", deliver={"dir": "D:/out", "batch": 3}), now=1)
        self.assertNotIn("note", got)
        self.assertEqual(got["deliver"], {"dir": "D:/out", "pool": None, "origin": None, "tag": None})
        got = E.check(env(id="a", kind="docs", input={"docId": "d1"}, note=None, deliver={"batch": None}), now=1)
        self.assertNotIn("note", got)
        self.assertNotIn("batch", got["deliver"])

    def test_deliver_origin(self):
        """D-SEND: 届けるときの出どころ(request・auto・manual。無ければ None = 自動で決める)。ほかは理由つきの ValueError"""
        base = env(id="a", kind="docs", input={"docId": "d1"})
        for o in E.DELIVER_ORIGINS:
            self.assertEqual(E.check(dict(base, deliver={"dir": "D:/out", "origin": o}))["deliver"]["origin"], o)
        self.assertEqual(E.check(dict(base, deliver={"dir": "D:/out"}))["deliver"]["origin"], None)
        for bad in ("Auto", "", 1, True, ["auto"]):
            with self.assertRaises(ValueError, msg=bad) as cm:
                E.check(dict(base, deliver={"dir": "D:/out", "origin": bad}))
            self.assertIn("封筒.deliver.origin", str(cm.exception))
        from flow import sendpolicy
        self.assertEqual(E.DELIVER_ORIGINS, sendpolicy.ORIGINS, "sendpolicy と同じ並び")

    def test_live_input(self):
        url = "https://www.youtube.com/watch?v=" + VID
        got = E.check(env(id="L1", kind="live", input={"url": url, "title": "配信", "recorder": "rec1"}))
        self.assertEqual(got["input"], {"title": "配信", "videoId": VID, "url": url, "recorder": "rec1"})
        self.assertEqual(E.check(env(id="L1", kind="live", input={"videoId": VID}))["input"], {"title": "", "videoId": VID, "recorder": None})
        for inp, why in (({"videoId": VID, "marks": []}, "封筒.input.marks"), ({"url": "https://example.com/"}, "YouTube"), ({}, "videoId"),
                         ({"videoId": VID, "recorder": ""}, "recorder")):
            with self.assertRaises(ValueError, msg=inp) as cm:
                E.check(env(id="L1", kind="live", input=inp))
            self.assertIn(why, str(cm.exception))

    def test_file_normalize(self):
        got = E.check(env(id="a", kind="file", input={"path": "C:/x.mp4", "normalize": True}, deliver={"origin": "auto", "tag": "20261016-010203-abcdef"}), now=1)
        self.assertEqual((got["input"]["normalize"], got["deliver"]["tag"]), (True, "20261016-010203-abcdef"))
        self.assertIs(E.check(env(id="a", kind="file", input={"path": "C:/x.mp4"}))["input"]["normalize"], False)
        with self.assertRaises(ValueError) as cm:
            E.check(env(id="a", kind="file", input={"path": "C:/x.mp4", "normalize": 1}))
        self.assertIn("normalize", str(cm.exception))

    def test_refusals_say_why(self):
        ok = env(id="a", kind="docs", input={"docId": "d1"})
        bad = [
            (dict(ok, extra=1), "知らない項目です: 封筒.extra"),
            (dict(ok, specVersion=3), "知らない束の版"),
            (dict(ok, specVersion=1), "知らない束の版"),
            (dict(ok, legacy={"mode": "doc"}), "知らない項目です: 封筒.legacy"),
            (dict(ok, specVersion=True), "知らない束の版"),
            (dict(ok, specVersion=None), "知らない束の版"),
            (dict(ok, kind="nai"), "封筒.kind"),
            (dict(ok, id="../x"), "封筒.id"),
            (dict(ok, input={"docId": "d1", "path": "x"}), "封筒.input.path"),
            (dict(ok, input={}), "docId"),
            (dict(ok, deliver={"pool": {"x": 1}}), "封筒.deliver.pool"),
            (dict(ok, deliver={"where": 1}), "封筒.deliver.where"),
            (dict(ok, createdAt=-1), "createdAt"),
            (dict(ok, requestId=""), "requestId"),
            (env(id="a", kind="url", input={"url": "https://example.com/"}), "YouTube"),
            (env(id="a", kind="url", input={"videoId": VID, "duration": -3}), "duration"),
            (env(id="a", kind="url", input={"videoId": VID, "fresh": {"title": "t", "x": 1}}), "fresh.x"),
            (env(id="a", kind="file", input={"title": "t"}), "path"),
            ("abc", "封筒"),
        ]
        for e, why in bad:
            with self.assertRaises(ValueError, msg=e) as cm:
                E.check(e)
            self.assertIn(why, str(cm.exception), e)

    def test_missing_version_is_current(self):
        self.assertEqual(E.check({"id": "a", "kind": "docs", "input": {"docId": "d1"}}, now=1)["specVersion"], E.SPEC_VERSION)

    def test_read_copies_bundle(self):
        spec = {"run": {"upto": "transcribe"}}
        got, out = E.read(env(id="a", kind="docs", input={"docId": "d1"}), spec, now=1)
        self.assertEqual(out, spec)
        self.assertIsNot(out, spec)
        self.assertEqual(E.read(env(id="a", kind="docs", input={"docId": "d1"}), now=1)[1], {})


VID = "abcdefghijk"


if __name__ == "__main__":
    unittest.main()
