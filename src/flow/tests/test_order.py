# -*- coding: utf-8 -*-
"""flow/order.py(欄 → 封筒 + 束の差分。RV A1)のテスト。  py -3.12 -m unittest src/flow/tests/test_order.py -v"""
import os
os.environ.setdefault("YTT_DATA_DIR", "inplace")
import sys
import unittest

SRC = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, SRC)
from flow import envelope as E, order as O, run as R, spec as SP  # noqa: E402

VID = "abcdefghijk"


class TestOrder(unittest.TestCase):
    def test_envelope_is_v2_and_checked(self):
        env, diff = O.order("url", video_id=VID, title="題" * 200, fresh={"title": "t", "channel": "c"}, eid="0123456789", created=12.5)
        self.assertEqual(env, E.check(env))
        self.assertEqual((env["specVersion"], env["id"], env["createdAt"], len(env["input"]["title"])), (2, "0123456789", 12500, E.TITLE_MAX))
        self.assertNotIn("legacy", env)
        self.assertEqual(diff, {"run": {"upto": "pack"}})
        self.assertRegex(O.order("docs", doc_id="d1")[0]["id"], r"^[0-9a-f]{10}$")
        for kind, kw, why in (("url", {"video_id": "../x"}, "videoId"), ("docs", {}, "docId"), ("file", {}, "path"), ("nai", {}, "kind"),
                              ("url", {"video_id": VID, "marks": "m1"}, "マーク")):
            with self.assertRaises(ValueError, msg=kind) as cm:
                O.order(kind, **kw)
            self.assertIn(why, str(cm.exception))

    def test_fields_to_diff(self):
        """Run の欄から写した差分(_asked_spec)と同じ表。合わない欄は黙って土台のまま"""
        env, diff = O.order("url", video_id=VID, from_="export", upto="transcribe", on_fail="stop", top=4, ranges=[(1, 2)],
                            weights={"wAudio": 1.5, "wChat": 0.5, "wComments": 2.0}, cut="silence", video_tracks=2,
                            speakers={"count": 2, "names": ["A", " A", "B" * 50], "styles": {"A": {"color": "112233"}}},
                            engine="faster-whisper", model="large-v3", force=True, repack=True, streamer="",
                            request_id="r1", deliver_dir="D:/out", origin="auto", tag="20261016-010203-abcdef", marks=("m1",))
        self.assertEqual(diff, {"adopt": {"top": 4}, "hints": {"ranges": [[1, 2]], "people": [{"name": "A", "color": "#112233"}, {"name": "B" * 40}],
                                                               "streamer": ""},
                                "analyze": {"wAudio": 1.5, "wChat": 0.5, "wComments": 2.0}, "pack": {"cut": "silence", "videoTracks": 2},
                                "transcribe": {"diarize": 2, "model": "large-v3"},
                                "run": {"force": True, "repack": True, "requested": ["weights", "cut", "videoTracks", "model"], "from": "export",
                                        "upto": "transcribe", "onFail": "stop"}})
        self.assertEqual(env["deliver"], {"dir": "D:/out", "pool": None, "origin": "auto", "tag": "20261016-010203-abcdef"})
        self.assertEqual(env["input"]["marks"], ["m1"])
        _env, bad = O.order("url", video_id=VID, top=99, cut="rows", video_tracks=9, weights={"wAudio": 9}, speakers={"count": 0})
        self.assertEqual(bad, {"run": {"upto": "pack"}}, "合わない欄は写さない")
        env, diff = O.order("live", url="https://www.youtube.com/watch?v=" + VID, cut="none")
        self.assertEqual((env["input"]["videoId"], diff), (VID, {"pack": {"cut": "none"}, "run": {"requested": ["cut"]}}), "ライブは段の並びを持たない")

    def test_same_run_as_old_fields(self):
        """欄から作った Run は、Run(欄) と同じ形(派生の mode = 記録の mode)・段の並び(固定の見本と比べる)"""
        base = SP.validate(SP.merge(None))
        m = "C:/x/a.mp4"
        cases = [("full", dict(kind="url", video_id=VID), ["analyze", "adopt", "export", "transcribe", "pack"]),
                 ("full", dict(kind="url", video_id=VID, deliver_dir="D:/o"), ["analyze", "adopt", "export", "transcribe", "pack", "deliver"]),
                 ("full", dict(kind="url", video_id=VID, from_="export"), ["export", "transcribe", "pack"]),   # 書き出しから全部(10-19。依頼の id があれば request_auto)
                 ("full", dict(kind="url", video_id=VID, from_="export", marks=["m1"], origin="auto", deliver_dir="D:/o"), ["export", "transcribe", "pack", "deliver"]),
                 ("request_auto", dict(kind="url", video_id=VID, from_="export", request_id="r1", marks=["m1"]), ["export", "transcribe", "pack", "deliver"]),
                 ("request_auto", dict(kind="url", video_id=VID, request_id="r1", ranges=[(1, 5)], top=1),
                  ["adopt", "export", "transcribe", "pack", "deliver", "analyze_later"]),
                 ("request_auto", dict(kind="url", video_id=VID, request_id="r1", deliver_dir="D:/o", cut="none", repack=True,
                                       speakers={"count": 2, "names": ["A"]}),
                  ["analyze", "adopt", "export", "transcribe", "diarize", "pack", "deliver"]),
                 ("doc", dict(kind="docs", doc_id="d1"), ["transcribe", "pack"]),
                 ("file", dict(kind="file", path=m, normalize=True, upto="transcribe"), ["normalize", "transcribe"]),
                 ("file_auto", dict(kind="file", path=m, engine="whisper.cpp", upto="pack"), ["transcribe", "pack", "deliver"])]
        for mode, okw, steps in cases:
            kind = okw.pop("kind")
            env, diff = O.order(kind, **okw)
            new = R.Run.from_envelope(env, SP.merge_onto(base, diff))
            self.assertEqual((new.mode, [s["key"] for s in new.steps]), (mode, steps), mode)
        for kw in (dict(from_="export", marks=["m1"]), dict(request_id="r1")):   # 文字起こしまで(transcribe)・② 軽く確認(request)の形は 10-19 に消した = 断る
            env, diff = O.order("url", video_id=VID, upto="transcribe", **kw)
            with self.assertRaises(ValueError, msg=kw):
                R.Run.from_envelope(env, SP.merge_onto(base, diff))


class TestMergeOnto(unittest.TestCase):
    def test_base_kept_and_marks_added(self):
        """土台(画面の設定・録画の束)に差分を重ねる。依頼が決めた印は足し合わせ・force・repack はどちらかが真なら真"""
        base = SP.validate(SP.merge({"export": {"loudness": -16}, "run": {"requested": ["engine"], "force": True}, "transcribe": {"engine": "whisper.cpp"}}))
        got = SP.validate(SP.merge_onto(base, {"pack": {"cut": "none"}, "run": {"requested": ["cut"], "upto": "transcribe", "pinned": ["model"]}}))
        self.assertEqual((got["export"]["loudness"], got["pack"]["cut"], got["run"]["requested"], got["run"]["force"], got["run"]["upto"]),
                         (-16, "none", ["engine", "cut"], True, "transcribe"))
        self.assertEqual(SP.merge_onto(base, None), base)
        with self.assertRaises(ValueError):
            SP.merge_onto(base, {"nai": {}})


if __name__ == "__main__":
    unittest.main()
