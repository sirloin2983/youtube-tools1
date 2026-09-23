"""保存・書き出しの障害回復。実データやネットワークは使用しない。"""
import os
import tempfile
import unittest
from unittest.mock import Mock, patch

import common
import exporter


def locked():
    error = PermissionError(13, "in use", "clip.mp4")
    error.winerror = 32
    return error


class TestAtomicWrite(unittest.TestCase):
    def test_transient_windows_lock_is_retried(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "data.json")
            common.atomic_write(path, b"old")
            replace = os.replace
            calls = []

            def flaky(src, dst):
                calls.append(dst)
                if len(calls) < 3:
                    raise locked()
                replace(src, dst)

            with patch.object(common.os, "replace", side_effect=flaky), patch.object(common.time, "sleep"):
                common.atomic_write(path, b"new")
            with open(path, "rb") as f:
                self.assertEqual(f.read(), b"new")
            self.assertEqual(len(calls), 3)
            self.assertEqual(os.listdir(tmp), ["data.json"])

    def test_permanent_lock_preserves_original_and_cleans_temporary_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "data.json")
            common.atomic_write(path, b"original")
            with patch.object(common.os, "replace", side_effect=locked()) as replace, patch.object(common.time, "sleep"):
                with self.assertRaises(PermissionError):
                    common.atomic_write(path, b"changed")
                self.assertEqual(replace.call_count, 4)
            with open(path, "rb") as f:
                self.assertEqual(f.read(), b"original")
            self.assertEqual(os.listdir(tmp), ["data.json"])

    def test_non_windows_permission_error_is_not_retried(self):
        with patch.object(common.os, "replace", side_effect=PermissionError()) as replace:
            with self.assertRaises(PermissionError):
                common.replace_file("source", "target")
            self.assertEqual(replace.call_count, 1)

    def test_cleanup_failure_does_not_hide_original_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            original = PermissionError("replace failed")
            with patch.object(common.os, "replace", side_effect=original), \
                    patch.object(common.os, "unlink", side_effect=OSError("cleanup failed")):
                with self.assertRaises(PermissionError) as raised:
                    common.atomic_write(os.path.join(tmp, "data.json"), b"data")
            self.assertIs(raised.exception, original)


class TestExportRecovery(unittest.TestCase):
    def run_export(self, callback=None, name_error=None, volume_error=None):
        spec = {"videoId": "abcdefghijk", "mode": "file"}
        item = {"id": "m1", "start": 0, "end": 5, "label": "", "status": "queued"}
        job = {"items": [item], "cancel": False}
        with tempfile.TemporaryDirectory() as tmp, \
                patch.object(common, "get_out_dir", return_value=tmp), \
                patch.object(common, "log_failure") as log, \
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
        with tempfile.TemporaryDirectory() as tmp, patch.object(common, "get_out_dir", return_value=tmp):
            folder, path = exporter.pick_folder({"title": "CON.txt", "videoId": "abcdefghijk"})
            self.assertEqual(folder, "_CON.txt")
            self.assertTrue(os.path.isdir(path))


if __name__ == "__main__":
    unittest.main()
