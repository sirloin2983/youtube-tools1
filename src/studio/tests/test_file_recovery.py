"""保存・書き出しの障害回復。実データやネットワークは使用しない。"""
import os
os.environ.setdefault("YTT_DATA_DIR", "inplace")   # テストは作業データを本物の置き場所(AppData など)に書かない(ytt.datadir)
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))   # ツールのフォルダ(studio/。exporter が裸の名前で handoff を読む)
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))   # src
from pipeline.export import exporter  # noqa: E402
from ytt import studio_env  # noqa: E402


def locked():
    error = PermissionError(13, "in use", "clip.mp4")
    error.winerror = 32
    return error


class TestExportRecovery(unittest.TestCase):
    def run_export(self, callback=None, name_error=None, volume_error=None):
        spec = {"videoId": "abcdefghijk", "mode": "file"}
        item = {"id": "m1", "start": 0, "end": 5, "label": "", "status": "queued"}
        job = {"items": [item], "cancel": False}
        with tempfile.TemporaryDirectory() as tmp, \
                patch.object(studio_env, "get_out_dir", return_value=tmp), \
                patch.object(studio_env, "log_failure") as log, \
                patch.object(exporter, "pick_folder", return_value=("video", tmp)), \
                patch.object(exporter, "unique_base", side_effect=name_error, return_value="clip"), \
                patch.object(exporter, "run_ffmpeg", return_value="video/clip.mp4"), \
                patch.object(exporter, "apply_volume", side_effect=volume_error):
            exporter.run_job(job, spec, callback)
        return job, item, log

    def test_mark_save_failure_is_visible_without_reexporting_successful_file(self):
        job, item, log = self.run_export(Mock(side_effect=OSError("disk full")))
        self.assertEqual(job["state"], "done")
        self.assertEqual(item["file"], "video/clip.mp4")
        self.assertIn("記録に失敗", item["warning"])
        log.assert_called_once()

    def test_filename_failure_does_not_leave_job_running_forever(self):
        job, item, log = self.run_export(name_error=OSError("drive disconnected"))
        self.assertEqual(job["state"], "error")
        self.assertEqual(item["status"], "error")
        log.assert_called_once()

    def test_permission_error_names_the_file_and_does_not_mark_exported(self):
        callback = Mock()
        job, item, log = self.run_export(callback, volume_error=locked())
        self.assertEqual(job["state"], "error")
        self.assertIn("clip.mp4", item["error"])
        callback.assert_not_called()
        log.assert_called_once()

    def test_windows_reserved_basename_with_extension_is_safe(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(studio_env, "get_out_dir", return_value=tmp):
            folder, path = exporter.pick_folder({"title": "CON.txt", "videoId": "abcdefghijk"})
            self.assertEqual(folder, "_CON.txt")
            self.assertTrue(os.path.isdir(path))


if __name__ == "__main__":
    unittest.main()
