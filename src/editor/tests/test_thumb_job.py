#!/usr/bin/env python3
"""サムネの案のジョブ(提案 P5。editor/ed_thumb.py → thumb_ideas.py)のテスト。

    py -3.10 -m unittest src/editor/tests/test_metrics.py   # test_metrics がこのファイルのテストも読み込む

- 指定(thumb_spec): 切り取りの値・同じ文書で作っている最中は 409・文書が無い・動画が無い
- ジョブ(本物の ffmpeg で 4 秒の動画を描く): 作業用/<名前>_thumb-ideas.png と .json・案は 6 つ・切り取りの指定・文書は書き換えない(updatedAt も)・thumb_info と画像のパス
- 設定 thumbCrop(api/settings/patch の検査)
"""
import json
import os
os.environ.setdefault("YTT_DATA_DIR", "inplace")   # テストは作業データを本物の置き場所に書かない(ytt.datadir)
import shutil
import subprocess
import sys
import tempfile
import unittest

TESTS = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(TESTS))
sys.path.insert(0, TESTS)
from test_backend import S, TID, StoreDir  # noqa: F401,E402  (S = serve)
from human.proof import doc_jobs  # noqa: E402
from ytt import jobs  # noqa: E402
import ed_state  # noqa: E402
import ed_thumb  # noqa: E402

HAVE_FF = bool(shutil.which("ffmpeg"))


def _drop_jobs(match):
    """このテストのジョブを表と待機列から外す(ほかのテストの run_job に拾われないように)"""
    with jobs._jobs_lock:
        for k in [k for k, j in jobs._jobs.items() if match(j)]:
            jobs._jobs.pop(k, None)
        keep = []
        while True:
            try:
                it = jobs._queue.get_nowait()
            except Exception:
                break
            if it[2] in jobs._jobs:
                keep.append(it)
        for it in keep:
            jobs._queue.put(it)


@unittest.skipUnless(HAVE_FF, "ffmpeg が必要")
class TestThumbJob(StoreDir):
    @classmethod
    def setUpClass(cls):
        cls.src_dir = tempfile.mkdtemp()
        cls.video = os.path.join(cls.src_dir, "切り抜き.mp4")
        subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin", "-y", "-f", "lavfi", "-i", "testsrc=size=320x180:rate=30:duration=4",
                        "-f", "lavfi", "-i", "sine=frequency=440:duration=4", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", cls.video],
                       check=True, timeout=120)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.src_dir, ignore_errors=True)

    def setUp(self):
        super().setUp()
        self.put_doc({"id": TID, "title": "サムネの試し", "sourcePath": self.video, "updatedAt": 123, "segments": [
            {"id": "s1", "start": 0.2, "end": 1.8, "text": "えっ待って!?"}, {"id": "s2", "start": 2.0, "end": 3.8, "text": "なんでそうなるの"}]})

    def tearDown(self):
        _drop_jobs(lambda j: (j.get("spec") or {}).get("sourcePath") == self.video)
        shutil.rmtree(os.path.join(self.src_dir, "作業用"), ignore_errors=True)
        super().tearDown()

    def test_job_writes_png_and_json_without_touching_doc(self):
        spec = S.thumb_spec(TID, {"crop": "center"})
        self.assertEqual((spec["crop"], spec["sourcePath"]), ("center", self.video))
        job = jobs.add_job(spec, "thumb")
        self.assertEqual(job["tid"], TID)
        doc_jobs.run_job(job)
        self.assertEqual(job["state"], "done", job.get("error"))
        png, js = ed_thumb.thumb_paths(self.video)
        self.assertEqual(os.path.dirname(png), os.path.join(self.src_dir, "作業用"))
        self.assertTrue(os.path.isfile(png) and os.path.getsize(png) > 1000 and os.path.isfile(js))
        info = S.thumb_info(TID)
        self.assertTrue(info["ok"])
        self.assertEqual((len(info["cards"]), info["crops"], info["file"]), (6, ["center"], "切り抜き_thumb-ideas.png"))
        self.assertEqual(S.thumb_image_path(TID), png)
        with open(S.tx_path(TID), encoding="utf-8") as f:
            self.assertEqual(json.load(f)["updatedAt"], 123)   # 文書は読むだけ

    def test_info_before_and_refusals(self):
        self.assertEqual(S.thumb_info(TID)["ok"], False)
        with self.assertRaises(ed_state.ApiError) as cm:
            S.thumb_image_path(TID)
        self.assertEqual(cm.exception.status, 404)
        with self.assertRaises(ed_state.ApiError) as cm:
            S.thumb_spec(TID, {"crop": "zoom"})
        self.assertEqual(cm.exception.status, 400)
        jobs.add_job(S.thumb_spec(TID, {}), "thumb")   # 待っている間にもう一度 → 409
        with self.assertRaises(ed_state.ApiError) as cm:
            S.thumb_spec(TID, {})
        self.assertEqual(cm.exception.status, 409)
        with self.assertRaises(ed_state.ApiError):
            S.thumb_spec("0123456789ab", {})   # 文書が無い

    def test_missing_video(self):
        self.put_doc({"id": TID, "title": "x", "sourcePath": os.path.join(self.src_dir, "無い.mp4"), "segments": []})
        with self.assertRaises(ed_state.ApiError):
            S.thumb_spec(TID, {})

    def test_settings_patch_thumb_crop(self):
        self.assertTrue(S.patch_settings({"values": {"thumbCrop": "right"}})["ok"])
        self.assertEqual(S.load_settings()["thumbCrop"], "right")
        with self.assertRaises(ed_state.ApiError):
            S.patch_settings({"values": {"thumbCrop": "zoom"}})


if __name__ == "__main__":
    unittest.main()
