"""切り抜き 1 本の素性(.clip.json = youtube-tools-clip/v1)の組み立てと書き込み(pipeline/export/manifest.py)のテスト。
RS3-5(2026-10-10)で studio/tests/test_handoff.py から移した。  実行(リポジトリ直下): py -3.10 -m unittest src/pipeline/export/tests/test_manifest.py"""
import json
import os
os.environ.setdefault("YTT_DATA_DIR", "inplace")   # テストは作業データを本物の置き場所(AppData など)に書かない(ytt.datadir)
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch

SRC = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))   # tests → export → pipeline → src
sys.path.insert(0, SRC)
from pipeline.export import manifest  # noqa: E402
from ytt import schemas, studio_env  # noqa: E402


class TestClipManifest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        studio_env.set_home(self.tmp)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_manifest_path_replaces_extension(self):
        # 途中のファイルは 作業用\ に書く(2026-09-27。出力先の直下はパックと元動画だけ)
        W = schemas.WORK_DIR
        self.assertEqual(manifest.manifest_path(os.path.join("x", "動画_0012.mp4")), os.path.abspath(os.path.join("x", W, "動画_0012.clip.json")))
        self.assertEqual(manifest.manifest_path("a.b.webm"), os.path.abspath(os.path.join(W, "a.b.clip.json")))

    def test_youtube_manifest_shape(self):
        media = os.path.join(self.tmp, "01_clip.mp4")
        with patch.dict(manifest.TOOL, {"name": "clip-studio", "version": "0.1.8"}):
            path = manifest.write_clip_manifest(media, duration=45.2345, source={"kind": "youtube", "videoId": "abcdefghijk", "title": "配信 <b>", "path": "/secret"},
                                               rng=(1234.5, 1279.7), mark={"id": "m12", "label": "見どころ", "status": "exported", "src": "manual"},
                                               export={"mode": "precise", "volume": 75})
        self.assertEqual(path, os.path.join(self.tmp, schemas.WORK_DIR, "01_clip.clip.json"))
        with open(path, "rb") as f:
            raw = f.read()
        self.assertFalse(raw.startswith(b"\xef\xbb\xbf"))   # BOM なし
        d = json.loads(raw.decode("utf-8"))
        self.assertEqual(d["schema"], "youtube-tools-clip/v1")
        self.assertEqual(d["tool"], {"name": "clip-studio", "version": "0.1.8"})
        self.assertRegex(d["createdAt"], r"[+-]\d\d:\d\d$")
        self.assertEqual(d["media"], {"path": os.path.abspath(media), "name": "01_clip.mp4", "durationSec": 45.234})
        self.assertEqual(d["source"], {"kind": "youtube", "videoId": "abcdefghijk", "url": "https://www.youtube.com/watch?v=abcdefghijk",
                                       "title": "配信 <b>", "path": None})   # youtube のときは元のパスを入れない
        self.assertEqual(d["range"], {"start": 1234.5, "end": 1279.7})
        self.assertEqual(d["mark"], {"id": "m12", "label": "見どころ", "status": "exported", "src": "manual"})
        self.assertEqual(d["export"], {"mode": "precise", "volume": 75})
        self.assertEqual(sorted(os.listdir(self.tmp)), [schemas.WORK_DIR])                                 # 動画のフォルダの直下には置かない
        self.assertEqual(sorted(os.listdir(os.path.join(self.tmp, schemas.WORK_DIR))), ["01_clip.clip.json"])   # 一時ファイルが残らない

    def test_file_manifest_has_source_path_and_no_url(self):
        d = manifest.clip_manifest(os.path.join(self.tmp, "a.mp4"), None, {"kind": "file", "videoId": "f0123456789", "title": "t", "path": "C:\\v\\元.mp4"},
                                  (0, 5), {"id": "m1", "src": "weird"}, {"mode": "fast"})
        self.assertEqual(d["source"]["path"], "C:\\v\\元.mp4")
        self.assertIsNone(d["source"]["url"])
        self.assertIsNone(d["media"]["durationSec"])
        self.assertEqual(d["mark"]["src"], "manual")   # 知らない値は manual に丸める

    def test_manifest_never_contains_api_key(self):
        with patch.dict(os.environ, {"YOUTUBE_API_KEY": "AIzaSyDUMMYKEYDUMMYKEY12345"}):
            d = manifest.clip_manifest("a.mp4", 1, {"kind": "youtube", "videoId": "abcdefghijk"}, (0, 1), {}, {"mode": "precise"})
        self.assertNotIn("AIza", json.dumps(d))


if __name__ == "__main__":
    unittest.main(verbosity=1)
