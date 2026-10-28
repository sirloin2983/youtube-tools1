"""書き出しの編集用素材まわりの取り残し(10-29 の見直し 4・8・17)のテスト。偽の ffmpeg 呼び出しで足りる(動画は作らない)。

    py -3.12 -m unittest tests/pipeline/export/test_exporter_edit.py
"""
import os
os.environ.setdefault("YTT_DATA_DIR", "inplace")   # テストは作業データを本物の置き場所に書かない(ytt.datadir)
import json
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

    def test_copy_edit_media_writes_sidecar_for_same_range(self):
        # 編集用素材 = 本体の写し(EDIT_FROM_MAIN・上乗せ 0): 作業用/<base>_edit.partial.mp4 に同じ中身・.edit.json は selectionIn 0・範囲は clipRange
        d = tempfile.mkdtemp()
        main = os.path.join(d, "01_a.partial.mp4")
        with open(main, "wb") as f:
            f.write(b"x" * 100)
        it = {"start": 7.0, "end": 12.0, "clipRange": (0.0, 22.0), "path": main, "method": "encode", "encoder": "h264_nvenc", "srcLen": 30.0}
        spec = {"outDir": d, "folder": "f"}
        with mock.patch.object(exporter._media, "media_info", return_value=(22.0, True, True, "")):
            rel = exporter.copy_edit_media(spec, it, "01_a")
        edit = os.path.join(d, "作業用", "01_a_edit.partial.mp4")
        self.assertEqual((rel, it["editPath"], os.path.getsize(edit)), ("f/作業用/01_a_edit.partial.mp4", edit, 100))
        with open(os.path.join(d, "作業用", "01_a.edit.json"), encoding="utf-8") as f:
            side = json.load(f)
        self.assertEqual((side["media"], side["selectionIn"], side["handleBefore"], side["handleAfter"], side["sourceStart"], side["sourceEnd"]),
                         ("01_a_edit.mp4", 0.0, 0.0, 0.0, 0.0, 22.0))
        self.assertEqual((it["editRange"], it["editEncoder"], it["editFrom"]), ((0.0, 22.0), "h264_nvenc", "copy"))
        self.assertGreaterEqual(it["secs"]["editCopy"], 0)

    def test_encode_falls_back_from_gpu_decode_to_cpu_decode(self):
        # 読み込みを GPU にした回(入力側の引数つき)が失敗したら、同じ作り方を読み込み CPU で(hwdecError に理由・hwdec は付かない)。入力側の引数は build の 2 つ目で受ける
        it, seen = {}, []
        tries = [("h264_nvenc", ["-hwaccel", "cuda"], ["-c:v", "h264_nvenc"]), ("h264_nvenc", ["-c:v", "h264_nvenc"]), ("libx264", ["-c:v", "libx264"])]

        def build(enc, pre=()):
            seen.append(list(pre))
            return ["ff"] + list(pre) + ["-i", "in"] + enc

        def pump(ctl, cmd, it_, dur, span):
            if "-hwaccel" in cmd:
                raise exporter.ExportError("Device creation failed")
            return []
        ctl = mock.Mock(cancelled=False)
        with mock.patch.object(exporter, "_pump", side_effect=pump), mock.patch.object(exporter, "verify_output"), \
                mock.patch.object(exporter, "log_export"):
            exporter._encode(ctl, {}, it, build, [("a.partial.mp4", 5.0)], "t", tries=tries)
        self.assertEqual(seen, [["-hwaccel", "cuda"], []])
        self.assertEqual((it["encoder"], it.get("hwdec"), it["hwdecError"][:30]), ("h264_nvenc", None, "h264_nvenc+cuda: Device creati"))
        self.assertNotIn("gpuError", it)


if __name__ == "__main__":
    unittest.main()
