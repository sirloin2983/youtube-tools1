import json
import os
import tempfile
import unittest
import zipfile

import resolve_export


class ResolveExportTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.source = os.path.join(self.tmp.name, "clip.mp4")
        self.edit = os.path.join(self.tmp.name, "clip_edit.mp4")
        with open(self.source, "wb") as f:
            f.write(b"exact")
        with open(self.edit, "wb") as f:
            f.write(b"handled-media")
        with open(os.path.join(self.tmp.name, "clip.edit.json"), "w", encoding="utf-8") as f:
            json.dump({"schema": "clip-studio/edit-media/v1", "media": "clip_edit.mp4", "selectionIn": 10,
                       "handleBefore": 10, "handleAfter": 10}, f)

    def tearDown(self):
        self.tmp.cleanup()

    def doc(self):
        return {"title": "テスト", "sourcePath": self.source, "whole": True, "duration": 8,
                "segments": [{"id": "s1", "start": 0, "end": 2, "text": "残す"},
                             {"id": "s2", "start": 2, "end": 4, "text": "切る", "cutState": "cut"},
                             {"id": "s3", "start": 4, "end": 8, "text": "もう一度残す"}]}

    def test_plan_uses_handle_media_and_keeps_recoverable_source_offsets(self):
        plan = resolve_export.build_plan(self.doc(), "30")
        self.assertTrue(plan["media"]["hasEditHandles"])
        self.assertEqual(plan["media"]["selectionInSeconds"], 10)
        self.assertEqual([(c["sourceStartFrame"], c["sourceEndFrame"]) for c in plan["cuts"]], [(300, 360), (420, 540)])
        self.assertEqual([c["startFrame"] for c in plan["captions"]], [0, 60])

    def test_package_contains_portable_recovery_files_and_textplus_importer(self):
        path, temp_dir, plan = resolve_export.create_package(self.doc(), "30")
        try:
            with zipfile.ZipFile(path) as z:
                names = set(z.namelist())
                self.assertTrue({"cut-plan.json", "timeline.fcpxml", "subtitles.srt", "create_resolve_project.py",
                                 "install_resolve_script.py", "Resolveに登録.bat", "はじめに.txt", "media/clip_edit.mp4"} <= names)
                script = z.read("create_resolve_project.py").decode("utf-8")
                self.assertIn('InsertFusionTitleIntoTimeline("Text+")', script)
                self.assertIn('CreateEmptyTimeline("SOURCE_WITH_HANDLES")', script)
                self.assertIn("Transcribe Resolve Import.py", z.read("install_resolve_script.py").decode("utf-8"))
                xml = z.read("timeline.fcpxml").decode("utf-8")
                self.assertIn("asset-clip", xml)
                self.assertNotIn(os.path.dirname(self.source), xml)
                self.assertEqual(len(plan["cuts"]), 2)
        finally:
            import shutil
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_old_clip_falls_back_without_claiming_handles(self):
        os.unlink(os.path.join(self.tmp.name, "clip.edit.json"))
        plan = resolve_export.build_plan(self.doc(), "24")
        self.assertFalse(plan["media"]["hasEditHandles"])
        self.assertEqual(plan["media"]["file"], "media/clip.mp4")

    def test_range_doc_uses_range_length_not_whole_file(self):
        """範囲指定の文書(1時間の動画の 100〜160 秒)で、素材の長さがファイル全体(3600秒)を基準にならないこと。
        以前は SOURCE_WITH_HANDLES の終わりが 3710 秒(ファイルより長い)になっていた。"""
        os.unlink(os.path.join(self.tmp.name, "clip.edit.json"))
        doc = {"title": "範囲", "sourcePath": self.source, "whole": False, "start": 100.0, "end": 160.0, "duration": 3600.0,
               "segments": [{"id": "s1", "start": 101, "end": 110, "text": "a"}]}
        plan = resolve_export.build_plan(doc, "30")
        self.assertEqual(plan["sourceTimeline"], {"startFrame": 90 * 30, "endFrame": 170 * 30})
        # 範囲がファイルの終わり近くなら、後ろの余白はファイルの終わりまで
        doc.update({"start": 3500.0, "end": 3595.0, "segments": [{"id": "s1", "start": 3501, "end": 3510, "text": "a"}]})
        plan = resolve_export.build_plan(doc, "30")
        self.assertEqual(plan["sourceTimeline"]["endFrame"], 3600 * 30)
        self.assertAlmostEqual(plan["media"]["handleAfterSeconds"], 5.0)

    def test_kept_spans_is_the_single_rule(self):
        """残す区間の規則: カット済・文字が空の行は除き、重なる・接する行はまとめる。すき間は残さない。"""
        segs = [{"id": "a", "start": 0, "end": 2, "text": "残す"}, {"id": "b", "start": 2, "end": 3, "text": "続き"},
                {"id": "c", "start": 3, "end": 4, "text": "切る", "cutState": "cut"}, {"id": "d", "start": 4.5, "end": 5, "text": "  "},
                {"id": "e", "start": 6, "end": 7, "text": "後"}, {"id": "f", "start": 6.5, "end": 8, "text": "重なる"}]
        spans = resolve_export.kept_spans(segs)
        self.assertEqual([(s["start"], s["end"], [g["id"] for g in s["segments"]]) for s in spans],
                         [(0.0, 3.0, ["a", "b"]), (6.0, 8.0, ["e", "f"])])
        self.assertFalse(resolve_export.is_kept({"text": "x", "cutState": "cut"}))
        self.assertTrue(resolve_export.is_kept({"text": "x", "cutState": "keep"}))

    def test_srt_text_format(self):
        self.assertEqual(resolve_export.srt_text([(0, 1.5, "一"), (3661.0005, 3662, "二\n行")]),
                         "1\n00:00:00,000 --> 00:00:01,500\n一\n\n2\n01:01:01,001 --> 01:01:02,000\n二\n行\n")
        self.assertEqual(resolve_export.srt_time(-1), "00:00:00,000")


if __name__ == "__main__":
    unittest.main()
