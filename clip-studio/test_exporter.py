"""書き出しの音量調整(exporter.apply_volume / build_spec の volume 検証)のテスト。
実際に ffmpeg を1回動かして確認する(合成した2秒の無音動画を使う。数秒で終わる)。

    python3 test_exporter.py
"""
import hashlib
import os
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import common
import exporter


def _make_clip(path, sec=2.0):
    """テスト用の短い合成動画(映像+無音の音声)を作る。ffmpeg が無ければテストをスキップする。"""
    ff = common.find_tool("ffmpeg")
    if not ff:
        return False
    cmd = [ff, "-hide_banner", "-nostdin", "-y", "-f", "lavfi", "-i", "testsrc=size=64x64:rate=10:duration=%.1f" % sec,
           "-f", "lavfi", "-i", "anullsrc=r=44100:cl=mono", "-t", "%.1f" % sec, "-c:v", "libx264", "-preset", "veryfast",
           "-c:a", "aac", path]
    r = subprocess.run(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    return r.returncode == 0 and os.path.isfile(path)


@unittest.skipUnless(common.find_tool("ffmpeg"), "ffmpeg が無い環境ではスキップ")
class TestApplyVolume(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.clip = os.path.join(self.tmp, "01_clip.mp4")
        if not _make_clip(self.clip):
            self.skipTest("テスト用動画を作れなかった(ffmpeg のビルドを確認してください)")

    def _job_it(self):
        return {"cancel": False, "proc": None}, {"start": 0.0, "end": 2.0, "progress": 0.0}

    def test_volume_100_is_a_noop(self):
        """既定の100(調整なし)では、ffmpeg を呼び直さずファイルはそのまま(バイト列が変わらない)。"""
        with open(self.clip, "rb") as f:
            before = hashlib.sha1(f.read()).hexdigest()
        job, it = self._job_it()
        exporter.apply_volume(job, {"outDir": self.tmp, "volume": 100}, it, os.path.basename(self.clip))
        with open(self.clip, "rb") as f:
            after = hashlib.sha1(f.read()).hexdigest()
        self.assertEqual(before, after)
        self.assertFalse(os.path.exists(self.clip + ".vol.mp4"))

    def test_volume_75_reencodes_audio_and_keeps_length(self):
        """既定値75では実際に ffmpeg が動き、映像は無劣化(長さが変わらない)のまま音量だけ変わる。"""
        job, it = self._job_it()
        exporter.apply_volume(job, {"outDir": self.tmp, "volume": 75}, it, os.path.basename(self.clip))
        dur, has_v, has_a, _ = common.media_info(self.clip)
        self.assertTrue(has_v)
        self.assertTrue(has_a)
        self.assertAlmostEqual(dur, 2.0, delta=0.3)
        self.assertFalse(os.path.exists(self.clip + ".vol.mp4"))   # 一時ファイルは置き換え後に残らない

    def _fake_store(self):
        clip = self.clip

        class FakeStore:
            def internal(self, vid):
                return {"id": vid, "marks": [{"id": "m1", "start": 1.0, "end": 2.0, "label": ""}], "kind": "file", "path": clip, "title": "t", "fileName": ""}
        return FakeStore()

    def test_volume_out_of_range_rejected_by_build_spec(self):
        """build_spec は 1〜200 の範囲外を bad_request で断る(ffmpeg は呼ばない)。"""
        store = self._fake_store()
        for bad in (0, 201, -5, "abc"):
            with self.assertRaises(common.ApiError):
                exporter.build_spec(store, {"id": "v1", "markIds": ["m1"], "volume": bad})

    def test_volume_missing_defaults_to_75(self):
        spec = exporter.build_spec(self._fake_store(), {"id": "v1", "markIds": ["m1"]})
        self.assertEqual(spec["volume"], exporter.DEFAULT_EXPORT_VOLUME)


class TestExportCompletion(unittest.TestCase):
    def test_callback_receives_the_exported_range(self):
        with tempfile.TemporaryDirectory() as tmp:
            spec = {"videoId": "abcdefghijk", "mode": "file"}
            item = {"id": "m1", "start": 10.0, "end": 15.0, "label": "", "status": "queued"}
            job = {"items": [item], "cancel": False}
            done = Mock(return_value=False)   # マークが変更されていても、出力ファイル自体は成功
            with patch.object(common, "get_out_dir", return_value=tmp), \
                    patch.object(exporter, "pick_folder", return_value=("video", tmp)), \
                    patch.object(exporter, "run_ffmpeg", return_value="video/clip.mp4"), \
                    patch.object(exporter, "apply_volume"):
                exporter.run_job(job, spec, done)
            done.assert_called_once_with("abcdefghijk", "m1", "video/clip.mp4", 10.0, 15.0)
            self.assertEqual((job["state"], item["status"], item["file"]), ("done", "done", "video/clip.mp4"))


if __name__ == "__main__":
    unittest.main(verbosity=1)
