"""src/eval/tools/_evalcommon.py(測る道具の共通の部品)の、引数・保存・音声の出どころ・JSON の読み込みのテスト。リポジトリ直下で:

    py -3.10 -m unittest src/eval/tools/tests/test_evalcommon.py

作業データは一時フォルダに作る(本物の作業データは読まない・書かない)。
"""
import argparse
import contextlib
import io
import json
import os
import sys
import tempfile
import unittest

os.environ.setdefault("YTT_DATA_DIR", "inplace")
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # src/eval/tools (道具の置き場所)
REPO = os.path.dirname(os.path.dirname(HERE))   # src(ツールと共通部品 ytt の置き場所)
sys.path.insert(0, REPO)
from eval.tools import _evalcommon as C  # noqa: E402


def put(path, data, mode="wb"):
    with open(path, mode) as f:
        f.write(data)


class FakeServe:
    """audio_span が使う editor の部品(num)だけを持つ偽の serve"""

    @staticmethod
    def num(x, default=None):
        return float(x) if isinstance(x, (int, float)) and not isinstance(x, bool) else default


class TestArgs(unittest.TestCase):
    def test_add_period_args(self):
        p = argparse.ArgumentParser()
        C.add_period_args(p, "since の説明")
        a = p.parse_args(["--since", "2026-10-01", "--json", "--data-dir", "x"])
        self.assertEqual((a.since, a.until, a.json, a.data_dir), ("2026-10-01", None, True, "x"))
        self.assertEqual(p.parse_args([]).json, False)

    def test_split_ids(self):
        self.assertEqual(C.split_ids("a, b ,,c"), ["a", "b", "c"])
        self.assertIsNone(C.split_ids(None))
        self.assertIsNone(C.split_ids(""))
        self.assertEqual(C.split_ids(","), [])

    def test_label_name(self):
        self.assertEqual(C.label_name("cloud openai/gpt 4o"), "cloud_openai_gpt_4o")
        self.assertEqual(len(C.label_name("a" * 100)), 40)
        self.assertEqual(len(C.label_name("a" * 100, None)), 100)


class TestSave(unittest.TestCase):
    def test_save_and_report(self):
        with tempfile.TemporaryDirectory() as root:
            path = C.save({"a": "あ"}, root, "demo", "_x")
            self.assertEqual(os.path.dirname(path), os.path.join(root, "evals", "demo"))
            self.assertTrue(path.endswith("_x.json"))
            with open(path, "rb") as f:
                raw = f.read()
            self.assertEqual(json.loads(raw.decode("utf-8")), {"a": "あ"})
            self.assertFalse(raw.startswith(b"\xef\xbb\xbf"))   # BOM なし
            self.assertEqual([n for n in os.listdir(os.path.dirname(path)) if n.startswith(".tmp")], [])   # 書きかけを残さない
            out = os.path.join(root, "sub", "o.json")
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                C.report_saved({"b": 1}, True, root, "demo", out=out)
                C.report_saved({"b": 1}, False, root, "demo")
            self.assertEqual(buf.getvalue(), "\n" + C.SAVED_MARK + os.path.abspath(out) + "\n")   # 入口の accuracy.py が読む「保存: <パス>」の形
            with open(out, encoding="utf-8") as f:
                self.assertEqual(json.load(f), {"b": 1})
            self.assertEqual(os.listdir(os.path.join(root, "evals", "demo")), [os.path.basename(path)])   # enabled=False は書かない


class TestReadJson(unittest.TestCase):
    def test_limit_and_bom_and_broken(self):
        with tempfile.TemporaryDirectory() as d:
            ok, big, bad = (os.path.join(d, n) for n in ("ok.json", "big.json", "bad.json"))
            put(ok, b"\xef\xbb\xbf" + json.dumps({"a": 1}).encode())
            put(big, json.dumps({"a": "x" * 100}).encode())
            put(bad, b"{broken")
            self.assertEqual(C.read_json(ok), {"a": 1})
            self.assertEqual(C.read_json(ok, None, 100), {"a": 1})
            self.assertEqual(C.read_json(big, "既定", 50), "既定")   # limit を超えたら既定値
            self.assertEqual(C.read_json(big, None, C.DOC_BYTES)["a"], "x" * 100)
            self.assertEqual(C.read_json(bad, {}), {})
            self.assertEqual(C.read_json(os.path.join(d, "none.json"), 5), 5)
            self.assertEqual(C.read_json(ok, {}, kind=list), {})


class TestAudioSpan(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.data = self.tmp.name
        self.full = os.path.join(self.data, "dataset", "docs", "d1", "full.flac")
        os.makedirs(os.path.dirname(self.full))
        put(self.full, b"x")
        self.video = os.path.join(self.data, "v.mp4")
        put(self.video, b"x")

    def tearDown(self):
        self.tmp.cleanup()

    def test_video_first_then_stored_audio(self):
        doc = {"id": "d1", "sourcePath": self.video, "start": 10, "end": 50}
        spec, offset, where = C.audio_span(FakeServe, doc, self.data, boost=True)
        self.assertEqual((spec, offset, where), ({"sourcePath": self.video, "start": 10.0, "end": 50.0, "boost": True}, 10.0, "動画"))
        doc["sourcePath"] = os.path.join(self.data, "無い.mp4")   # 動画が無ければ保管の音声(範囲の先頭 = 0 秒・行の時刻の基準は start のまま)
        spec, offset, where = C.audio_span(FakeServe, doc, self.data, boost=False)
        self.assertEqual((spec, offset, where), ({"sourcePath": self.full, "start": 0.0, "end": None, "boost": False}, 10.0, "保管の音声"))

    def test_boost_none_has_no_key_and_doc_id(self):
        spec, _o, _w = C.audio_span(FakeServe, {"sourcePath": self.video}, self.data, doc_id="d1")
        self.assertNotIn("boost", spec)
        self.assertEqual((spec["start"], spec["end"]), (0.0, None))

    def test_network_path_is_not_touched(self):
        # ネットワーク上の動画は存在を確かめない(資格情報を送らない)。保管の音声があればそちら・無ければ RuntimeError
        for src in ("\\\\server\\share\\v.mp4", "//server/share/v.mp4"):
            spec, _o, where = C.audio_span(FakeServe, {"id": "d1", "sourcePath": src}, self.data)
            self.assertEqual((spec["sourcePath"], where), (self.full, "保管の音声"))
        os.unlink(self.full)
        with self.assertRaises(RuntimeError):
            C.audio_span(FakeServe, {"id": "d1", "sourcePath": "\\\\server\\share\\v.mp4"}, self.data)

    def test_fake_job_is_new_each_time(self):
        a, b = C.fake_job(), C.fake_job()
        self.assertIsNot(a, b)
        self.assertEqual((a["cancel"], a["proc"], a["progress"]), (False, None, 0.0))


if __name__ == "__main__":
    unittest.main()
