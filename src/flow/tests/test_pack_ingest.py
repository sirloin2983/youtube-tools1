# -*- coding: utf-8 -*-
"""② flow/pack.py・flow/ingest.py の動詞の最小の検査(RS6 a-5a)。  py -3.10 -m unittest src/flow/tests/test_pack_ingest.py -v
- pack: 形式の見分け・カットの区間の差し替え・版の付与・手順の None → 空の文字・たたき台の順番待ち(重い処理の札)を resolve_export に渡す
- ingest: 文字だけの入力の見分け・ライブの録画・不正な入力
- ytt に下ろした check_live・prune_cache の動き
"""
import os
os.environ.setdefault("YTT_DATA_DIR", "inplace")
import sys
import tempfile
import time
import unittest
from unittest import mock

SRC = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))   # tests -> flow -> src
sys.path.insert(0, SRC)
from flow import ingest, pack  # noqa: E402
from ytt import errors, fsio, workdata, yturl  # noqa: E402

DOC = {"sourcePath": "C:\\x\\clip.mp4", "title": "t", "duration": 10.0,
       "segments": [{"id": "a", "start": 0, "end": 2, "text": "残す"}, {"id": "b", "start": 2, "end": 4, "text": "切る", "cutState": "cut"}]}


class TestPack(unittest.TestCase):
    def test_handoff_formats(self):
        obj, n = pack.handoff_files(DOC, "transcript-v1")
        self.assertEqual((n, len(obj["segments"])), (len(obj["segments"]), n))
        cp, n = pack.handoff_files(DOC, "cut-plan-v1")
        self.assertEqual(n, len(cp["segments"]))
        text, n = pack.handoff_files(DOC, "srt", 0, False)
        self.assertIsInstance(text, str)
        self.assertGreaterEqual(n, 1)
        with self.assertRaises(ValueError):
            pack.handoff_files(DOC, "nope")

    def test_cut_plan_keeps_override(self):
        cp, n = pack.handoff_files(DOC, "cut-plan-v1", keeps=[[0.5, 1.5], [3.0, 4.0]])
        self.assertEqual(n, 2)
        self.assertEqual([(s["id"], s["start"], s["end"], s["status"]) for s in cp["segments"]],
                         [("segment-001", 0.5, 1.5, "adopted"), ("segment-002", 3.0, 4.0, "adopted")])

    def test_version_is_passed_each_call(self):
        with mock.patch.object(pack.resolve_export, "edit_preview", return_value={"ok": 1}) as m:
            self.assertEqual(pack.cut_preview(DOC, [[0, 1]], 12), {"ok": 1})
            m.assert_called_once_with(DOC, [[0, 1]], workdata.SERVER_VERSION, 12)
        with mock.patch.object(pack.resolve_export, "edit_draft", return_value={"fps": [30, 1], "durationSec": 5.0, "keepsSec": []}) as m:
            self.assertEqual(pack.media_plan(DOC, "D:\\y.mp4"), {"fps": [30, 1], "durationSec": 5.0})
            args, kw = m.call_args
            self.assertEqual(args[0]["sourcePath"], "D:\\y.mp4")
            self.assertIs(kw["rows"], False)

    def test_cut_draft_uses_tool_slot(self):
        seen = {}

        def fake(doc, version, rows=True, row_edge=None, heavy=None):
            seen.update(version=version, rows=rows, row_edge=row_edge, heavy=heavy)
            return {}
        with mock.patch.object(pack.resolve_export, "edit_draft", fake):
            pack.cut_draft(DOC, rows=True, row_edge={"x": 1})
        self.assertEqual((seen["version"], seen["rows"], seen["row_edge"]), (workdata.SERVER_VERSION, True, {"x": 1}))
        with mock.patch.object(pack.jobs, "tool_slot", return_value="slot") as ts:
            self.assertEqual(seen["heavy"]("ラベル"), "slot")
            self.assertEqual(ts.call_args[0], ("ラベル",))
            self.assertFalse(ts.call_args[1]["cancelled"]())   # 待つ上限の前

    def test_instructions_none_to_empty(self):
        with mock.patch.object(pack.resolve_export, "pack_instructions", return_value=None):
            self.assertEqual(pack.instructions("x"), "")
        with mock.patch.object(pack.resolve_export, "pack_instructions", return_value="手順"):
            self.assertEqual(pack.instructions("x"), "手順")


class TestIngest(unittest.TestCase):
    def test_probe_youtube_text(self):
        r = ingest.probe("https://youtu.be/U972n0ncl4k")
        self.assertEqual((r["kind"], r["id"]), ("youtube", "U972n0ncl4k"))
        self.assertNotIn("live", r)

    def test_probe_file_path(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "a.mp4")
            open(p, "wb").close()
            r = ingest.probe(p)
        self.assertEqual((r["kind"], r["title"]), ("file", "a.mp4"))
        self.assertTrue(r["id"].startswith("f"))

    def test_probe_live(self):
        live = {"kind": "live", "recorder": "rec1", "recording": "20261005-185300", "url": "https://youtu.be/U972n0ncl4k"}
        r = ingest.probe(live)
        self.assertEqual((r["kind"], r["id"]), ("live", "20261005-185300"))
        self.assertEqual(r["live"]["videoId"], "U972n0ncl4k")

    def test_probe_bad(self):
        for bad in ("not a url", {"kind": "file", "path": "Z:\\no\\such.mp4"}, 5, {"kind": "live"}):
            with self.assertRaises(errors.ApiError):
                ingest.probe(bad)


class TestLowered(unittest.TestCase):
    def test_check_live_in_yturl(self):
        self.assertEqual(yturl.check_live({"recorder": "rec1", "recording": "20261005-185300", "url": "https://www.youtube.com/@x/live"})["videoId"], "")
        with self.assertRaises(errors.ApiError):
            yturl.check_live({"recorder": "rec1", "recording": "bad", "url": "https://youtu.be/U972n0ncl4k"})

    def test_prune_cache(self):
        with tempfile.TemporaryDirectory() as d:
            for i in range(5):
                p = os.path.join(d, "%d.json" % i)
                open(p, "w").close()
                os.utime(p, (time.time() - 100 + i, time.time() - 100 + i))
            fsio.prune_cache(d, "*.json", 2)
            self.assertEqual(sorted(os.listdir(d)), ["3.json", "4.json"])
            fsio.prune_cache(os.path.join(d, "none"), "*.json", 2)   # 無いフォルダは黙って諦める


if __name__ == "__main__":
    unittest.main()
