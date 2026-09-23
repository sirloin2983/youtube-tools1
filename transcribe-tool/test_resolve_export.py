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


if __name__ == "__main__":
    unittest.main()
