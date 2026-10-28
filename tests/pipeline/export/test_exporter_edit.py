"""書き出しの編集用素材まわりの取り残し(10-29 の見直し 4・8・17)のテスト。偽の ffmpeg 呼び出しで足りる(動画は作らない)。

    py -3.12 -m unittest tests/pipeline/export/test_exporter_edit.py
"""
import os
os.environ.setdefault("YTT_DATA_DIR", "inplace")   # テストは作業データを本物の置き場所に書かない(ytt.datadir)
import sys
import tempfile
import unittest
from unittest import mock

SRC = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))), "src")
sys.path.insert(0, SRC)
from pipeline.export import exporter  # noqa: E402


class EditMediaLeftovers(unittest.TestCase):
    def test_encode_sets_expect_sec_from_first_output(self):
        # _encode の間 it に path はまだ無い: 点検の長さの期待は outs[0](本体)から入れる
        it = {}
        with mock.patch.object(exporter, "_pump", return_value=[]), mock.patch.object(exporter, "verify_output"):
            exporter._encode(None, {}, it, lambda enc: ["ff"], [("a.partial.mp4", 12.5), ("b.partial.mp4", 12.5)], "t", tries=[("cpu", [])])
        self.assertEqual(it["expectSec"], 12.5)

    def test_edit_media_does_not_ask_for_another_edit_or_share_secs(self):
        # 方法 2 で本体ができたあと(editMade 無し): 編集用素材の作り直しに keepRaw・editMade を渡さない(_edit_edit の書きかけを作らない)。
        # 段ごとの秒は本体の辞書に足さない
        it = {"start": 10.0, "end": 20.0, "keepRaw": 0.0, "editMade": None, "secs": {"encode": 3.0}}
        seen = {}
        d = tempfile.mkdtemp()

        def runner(ctl, spec, edit_it, base):
            seen.update(keepRaw=edit_it.get("keepRaw", "none"), editMade=edit_it.get("editMade", "none"))
            exporter._secs(edit_it, "encode", 9.0)
            path = os.path.join(spec["outDir"], base + ".partial.mp4")
            open(path, "wb").close()
            return spec["folder"] + "/" + os.path.basename(path)

        spec = {"outDir": d, "folder": "f"}
        with mock.patch.object(exporter._media, "media_info", return_value=(10.0, None, None, "")):
            exporter.export_edit_media(None, spec, it, "01_a", runner)
        self.assertEqual((seen["keepRaw"], seen["editMade"]), ("none", "none"))
        self.assertEqual(it["secs"], {"encode": 3.0})


if __name__ == "__main__":
    unittest.main()
