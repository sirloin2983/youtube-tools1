# -*- coding: utf-8 -*-
"""② flow/pack.py・flow/ingest.py の動詞。  py -3.12 -m unittest tests/flow/test_pack_ingest.py -v
- 受け渡しの通し(transcript-v1・SRT の中身と書式。字幕に出さない行・カット済の行・時と改行のある行を混ぜた文書)
- 入力の見分けの通し(YouTube の URL・ファイル・ライブの録画・不正な入力)
- 通しでは見えない物: 版を一時の文字起こしに渡す・重い処理の札(順番待ち)・古いキャッシュの片付け(更新日時の並び)
"""
import os
os.environ.setdefault("YTT_DATA_DIR", "inplace")
import sys
import tempfile
import time
import unittest
from unittest import mock

SRC = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "src")   # tests -> flow -> src
sys.path.insert(0, SRC)
from flow import ingest, pack  # noqa: E402
from ytt import errors, fsio, workdata  # noqa: E402

DOC = {"sourcePath": "C:\\x\\clip.mp4", "title": "t", "duration": 3700.0,
       "speakers": [{"id": "S1", "name": "ぺこら"}, {"id": "other", "name": "ゲーム音声など", "builtin": "other"}],
       "segments": [{"id": "d", "start": 3661.0005, "end": 3662, "text": "二\n行"},
                    {"id": "a", "start": 0, "end": 1.5, "text": "一", "speaker": "S1"},
                    {"id": "b", "start": 1.5, "end": 4, "text": "NPC", "speaker": "other", "noSub": True},
                    {"id": "c", "start": 2, "end": 4, "text": "切る", "cutState": "cut"},
                    {"id": "e", "start": 5, "end": 6, "text": "   "}]}


class TestPack(unittest.TestCase):
    def test_handoff_run(self):
        """受け渡しの中身: 行は時刻順・文字の無い行は入れない・字幕に出さない行は印を載せる・区間には数える"""
        obj, n = pack.handoff_files(DOC, "transcript-v1")
        self.assertEqual(n, 4)
        self.assertEqual([(g["id"], g.get("noSub"), g["cut"], g["speaker"]) for g in obj["segments"]],
                         [("a", None, False, 0), ("b", True, False, 1), ("c", None, True, None), ("d", None, False, None)])
        self.assertEqual(([s["name"] for s in obj["speakers"]], obj["tool"]["version"]), (["ぺこら", "ゲーム音声など"], workdata.SERVER_VERSION))
        for fmt in ("nope", "srt", "cut-plan-v1"):   # 字幕の書き出し(srt)・残す区間の保存(cut-plan-v1)は 10-24 に無くした
            with self.assertRaises(ValueError):
                pack.handoff_files(DOC, fmt)
        with tempfile.TemporaryDirectory() as d:                                       # 前回のパックの手順: 作れなければ空の文字
            self.assertEqual(pack.instructions(os.path.join(d, "none")), "")
            with open(os.path.join(d, "create_resolve_textplus_project.lua"), "w", encoding="utf-8") as f:
                f.write("-- 壊れた")
            self.assertEqual(pack.instructions(d), "")

    def test_version_is_passed_each_call(self):
        """版は一時の文字起こしに書くだけで戻り値に出ないので、呼ぶ引数で確かめる。media_plan は「行から」を計算しない"""
        with mock.patch.object(pack.resolve_export, "edit_preview", return_value={"ok": 1}) as m:
            self.assertEqual(pack.cut_preview(DOC, [[0, 1]], 12), {"ok": 1})
            m.assert_called_once_with(DOC, [[0, 1]], workdata.SERVER_VERSION, 12)
        with mock.patch.object(pack.resolve_export, "edit_draft", return_value={"fps": [30, 1], "durationSec": 5.0, "keepsSec": []}) as m:
            self.assertEqual(pack.media_plan(DOC, "D:\\y.mp4"), {"fps": [30, 1], "durationSec": 5.0})
            args, kw = m.call_args
            self.assertEqual(args[0]["sourcePath"], "D:\\y.mp4")
            self.assertIs(kw["rows"], False)

    def test_cut_draft_uses_tool_slot(self):
        """たたき台の重い処理は順番待ちの札を通す(ほかの重い処理と並ぶ状態は通しでは作れない)"""
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


class TestIngest(unittest.TestCase):
    def test_probe_run(self):
        """入力の見分け: YouTube の URL(配信中ではない)・ファイル・ライブの録画(配信の URL から動画の id。チャンネルの /live なら空)・不正な入力"""
        r = ingest.probe("https://youtu.be/U972n0ncl4k")
        self.assertEqual((r["kind"], r["id"]), ("youtube", "U972n0ncl4k"))
        self.assertNotIn("live", r)
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "a.mp4")
            open(p, "wb").close()
            r = ingest.probe(p)
        self.assertEqual((r["kind"], r["title"]), ("file", "a.mp4"))
        self.assertTrue(r["id"].startswith("f"))
        live = {"kind": "live", "recorder": "rec1", "recording": "20261005-185300", "url": "https://youtu.be/U972n0ncl4k"}
        r = ingest.probe(live)
        self.assertEqual((r["kind"], r["id"], r["live"]["videoId"]), ("live", "20261005-185300", "U972n0ncl4k"))
        self.assertEqual(ingest.probe(dict(live, url="https://www.youtube.com/@x/live"))["live"]["videoId"], "")
        for bad in ("not a url", {"kind": "file", "path": "Z:\\no\\such.mp4"}, 5, {"kind": "live"}, dict(live, recording="bad")):
            with self.subTest(bad=bad), self.assertRaises(errors.ApiError):
                ingest.probe(bad)


class TestLowered(unittest.TestCase):
    def test_prune_cache(self):
        """古い順に消して新しい n 個を残す(更新日時の並びは時間を待たないと来ないので、日時を書き換えて作る)"""
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
