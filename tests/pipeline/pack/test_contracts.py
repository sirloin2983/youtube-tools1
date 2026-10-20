# -*- coding: utf-8 -*-
"""別のプログラムが読む形の見本(src/ytt/tests/fixtures/contracts/ の clip/v1.json・transcript/v1.json)。書く側が書いた形は見本と同じ鍵・
読む側(文字起こしの受付が読む .clip.json・cut2resolve が読む .transcript.json)は見本を読める。  py -3.12 -m unittest src/pipeline/pack/tests/test_contracts.py"""
import json
import os
import sys
import tempfile
import unittest

SRC = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))   # tests -> pack -> pipeline -> src
sys.path.insert(0, SRC)
from pipeline.pack import cut2resolve_core as C, resolve_export as RE  # noqa: E402
from ytt import schemas  # noqa: E402

FIX = os.path.join(SRC, "ytt", "tests", "fixtures", "contracts")


def sample(name):
    with open(os.path.join(FIX, name, "v1.json"), encoding="utf-8") as f:
        return json.load(f)


class TestClipAndTranscript(unittest.TestCase):
    def test_written_shape_and_read_back(self):
        want_clip, want_tr = sample("clip"), sample("transcript")
        clip = schemas.build_clip(want_clip["media"]["path"], 20.0, want_clip["source"], (5.0, 25.0), want_clip["mark"], want_clip["export"], want_clip["tool"])
        self.assertEqual({k: set(v) if isinstance(v, dict) else None for k, v in clip.items()},
                         {k: set(v) if isinstance(v, dict) else None for k, v in want_clip.items()})
        got, warn = schemas.validate_clip(want_clip)   # 文字起こしの受付が読む
        self.assertEqual((warn, got["range"], schemas.clip_offset(got)), (None, {"start": 5.0, "end": 25.0}, 5.0))
        doc = {"sourcePath": want_tr["media"]["path"], "duration": 20.0, "clip": got, "title": "通し", "language": "ja",
               "speakers": [{"id": "s1", "name": "兎田ぺこら"}],
               "segments": [dict(g, speaker="s1" if g["speaker"] == 0 else None, cutState="cut" if g["cut"] else "", proofed=g["proofed"])
                            for g in want_tr["segments"]]}
        tr = RE.build_transcript_v1(doc, "0.2.0")
        self.assertEqual(set(tr), set(want_tr))
        self.assertEqual([set(g) for g in tr["segments"]], [set(g) for g in want_tr["segments"]])
        self.assertEqual((tr["clip"]["range"], [g["cut"] for g in tr["segments"]]), (want_clip["range"], [False, True, False]))
        with tempfile.TemporaryDirectory() as d:
            for name, obj in (("written", tr), ("sample", want_tr)):   # cut2resolve が読む(書いた物も見本も)
                p = os.path.join(d, name + ".transcript.json")
                with open(p, "w", encoding="utf-8") as f:
                    json.dump(obj, f, ensure_ascii=False)
                got_tr = C.read_transcript(p)
                self.assertEqual((got_tr["bad"], got_tr["speakerOrder"]), (0, ["兎田ぺこら"]), name)
                self.assertEqual(C.transcript_kept_spans(got_tr["rows"]), [(0.5, 4.0), (12.5, 18.0)], name)   # カット済の行・すき間は残さない


if __name__ == "__main__":
    unittest.main()
