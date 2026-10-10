#!/usr/bin/env python3
"""ytt/workdata.py(編集の作業データの置き場所と版の今の値)と ytt/studiodata.py(スタジオの data.json の読み口)のテスト(役割で組み直す RS3-0A)。

    python -m unittest src/ytt/tests/test_workdata.py

編集の serve の名前の受付(S.TX_DIR = … が workdata へ届く)は src/editor/tests/test_names.py が確かめる。ここは serve なしで読めて、
set_root・set_data_dir が以前の ed_state(読み込みのとき)・serve.set_data_dir と同じパスを作ることと、studiodata が置き場所を呼ぶたびに読むことだけ。
"""
import json
import os
os.environ.setdefault("YTT_DATA_DIR", "inplace")   # 作業データは読み書きしないが、ほかのテストとそろえる
import shutil
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))   # src
from ytt import layout, studiodata, workdata  # noqa: E402

NAMES = ("ROOT", "DATA_DIR", "TX_DIR", "TMP_DIR", "DATASET_DIR", "EVAL_BASE", "SETTINGS", "FEEDBACK", "MARKER_DATA", "STUDIO_DATA", "SERVER_VERSION")


class _Saved(unittest.TestCase):
    """workdata の値を試験の前に控え、後で戻す(編集のテストと同じプロセスで流しても壊さない)"""

    def setUp(self):
        saved = {n: getattr(workdata, n) for n in NAMES}
        self.addCleanup(lambda: [setattr(workdata, n, v) for n, v in saved.items()])


class TestWorkdata(_Saved):
    def test_set_root_defaults(self):
        root = os.path.join("x", "src", "editor")
        env = {k: v for k, v in os.environ.items() if k not in ("TRANSCRIBE_DATA_DIR", "TRANSCRIBE_MARKER_DATA", "TRANSCRIBE_STUDIO_DATA")}
        with mock.patch.dict(os.environ, env, clear=True):
            workdata.set_root(root)
        self.assertEqual(workdata.ROOT, root)
        self.assertEqual(workdata.DATA_DIR, root)   # 読み込みの直後はこのフォルダ(テスト用。起動したら serve が切り替える)
        self.assertEqual(workdata.TX_DIR, os.path.join(root, "transcripts"))
        self.assertEqual(workdata.TMP_DIR, os.path.join(root, "transcripts", ".tmp"))
        self.assertEqual(workdata.MARKER_DATA, os.path.join("x", "src", "clip-marker", "data.json"))
        self.assertEqual(workdata.STUDIO_DATA, os.path.join(layout.tool_dir("studio", os.path.join("x", "src")), "data.json"))

    def test_set_root_reads_env(self):
        with mock.patch.dict(os.environ, {"TRANSCRIBE_DATA_DIR": os.path.join("d", "data"), "TRANSCRIBE_MARKER_DATA": "m.json",
                                          "TRANSCRIBE_STUDIO_DATA": "s.json"}):
            workdata.set_root(os.path.join("x", "editor"))
        self.assertEqual((workdata.DATA_DIR, workdata.MARKER_DATA, workdata.STUDIO_DATA), (os.path.join("d", "data"), "m.json", "s.json"))

    def test_set_data_dir_paths(self):
        d = os.path.join("e", "data")
        workdata.set_data_dir(d)
        want = {"DATA_DIR": d, "TX_DIR": os.path.join(d, "transcripts"), "TMP_DIR": os.path.join(d, "transcripts", ".tmp"),
                "DATASET_DIR": os.path.join(d, "dataset"), "EVAL_BASE": os.path.join(d, "eval-baselines.json"),
                "SETTINGS": os.path.join(d, "settings.json"), "FEEDBACK": os.path.join(d, "learn-feedback.json")}
        self.assertEqual({k: getattr(workdata, k) for k in want}, want)


class TestStudiodata(_Saved):
    def test_reads_place_each_time(self):
        tmp = tempfile.mkdtemp(prefix="rs3-studio-")
        self.addCleanup(shutil.rmtree, tmp, True)
        a, b = os.path.join(tmp, "a.json"), os.path.join(tmp, "b.json")
        with open(a, "w", encoding="utf-8") as f:
            json.dump({"videos": {"v1": {"channel": "Ch1", "title": "T1"}, "v2": {"channel": "Ch2", "title": "T2"}},
                       "groups": {"g": {"members": ["v1", "v2"]}}}, f, ensure_ascii=False)
        workdata.STUDIO_DATA = a
        self.assertEqual(studiodata.studio_videos()["v1"], {"channel": "Ch1", "title": "T1"})
        self.assertEqual(studiodata.studio_stream("v1"), {"channel": "Ch1", "title": "T1", "collab": [{"channel": "Ch2", "title": "T2", "videoId": "v2"}]})
        self.assertIsNone(studiodata.studio_stream("none"))
        workdata.STUDIO_DATA = b   # 無いファイル = 空(呼ぶたびに今の場所を読む)
        self.assertEqual(studiodata.studio_videos(), {})


if __name__ == "__main__":
    unittest.main()
