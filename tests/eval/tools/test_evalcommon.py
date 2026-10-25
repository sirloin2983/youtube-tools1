"""src/eval/tools/_evalcommon.py(測る道具の共通の部品)の、引数・保存・音声の出どころのテスト。リポジトリ直下で:

    py -3.12 -m unittest tests/eval/tools/test_evalcommon.py

作業データは一時フォルダに作る(本物の作業データは読まない・書かない)。
"""
import argparse
import contextlib
import datetime
import io
import json
import os
import sys
import types
import unittest
from unittest import mock

os.environ.setdefault("YTT_DATA_DIR", "inplace")
HERE = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))), "src", "eval", "tools")   # src/eval/tools (道具の置き場所)
REPO = os.path.dirname(os.path.dirname(HERE))   # src(ツールと共通部品 ytt の置き場所)
sys.path.insert(0, REPO)
from eval.tools import _evalcommon as C  # noqa: E402
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))   # tests/(testkit)
import testkit  # noqa: E402


def put(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(data)


def printed(fn, *a, **kw):
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        fn(*a, **kw)
    return out.getvalue()


class Ticking(datetime.datetime):
    """呼ぶたびに 1 秒進む now(保存の名前は秒まで。待たずに別の名前にする)"""
    t = datetime.datetime(2026, 10, 1, 12, 0, 0)

    @classmethod
    def now(cls, tz=None):
        cls.t += datetime.timedelta(seconds=1)
        return cls.t


def ticking(case):
    """case の間、_evalcommon の保存の時刻を Ticking にする"""
    p = mock.patch.object(C, "datetime", types.SimpleNamespace(datetime=Ticking, timedelta=datetime.timedelta))
    p.start()
    case.addCleanup(p.stop)


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
        root = testkit.tempdir(self)
        path = C.save({"a": "あ"}, root, "demo", "_x")
        self.assertEqual(os.path.dirname(path), os.path.join(root, "evals", "demo"))
        self.assertTrue(path.endswith("_x.json"))
        with open(path, "rb") as f:
            raw = f.read()
        self.assertEqual(json.loads(raw.decode("utf-8")), {"a": "あ"})
        self.assertFalse(raw.startswith(b"\xef\xbb\xbf"))   # BOM なし
        self.assertEqual([n for n in os.listdir(os.path.dirname(path)) if n.startswith(".tmp")], [])   # 書きかけを残さない
        text = printed(lambda: (C.report_saved({"b": 1}, True, root, "demo", "_y"), C.report_saved({"b": 2}, False, root, "demo", "_y")))
        saved = [n for n in os.listdir(os.path.join(root, "evals", "demo")) if n.endswith("_y.json")]
        self.assertEqual(len(saved), 1)                                                 # enabled=False は書かない
        self.assertEqual(text, "\n" + C.SAVED_MARK + os.path.join(root, "evals", "demo", saved[0]) + "\n")   # 入口の accuracy.py が読む「保存: <パス>」の形


class TestSaveUnchanged(unittest.TestCase):
    """前の結果と中身(時刻・git・かかった秒を除く)が同じなら書かずに「変わらず: <前のファイル>」(夜の測定が毎晩同じ結果を貯めない)"""

    def setUp(self):
        self.root = testkit.tempdir(self)
        ticking(self)   # 保存のたびに時刻が 1 秒進む = 書くなら別の名前になる

    def res(self, v=1, at=1, git="aaa"):
        return {"meta": {"at": at, "git": git, "n": [{"sec": 1.5, "x": v}]}, "v": v}

    def test_same_content_is_not_written(self):
        root = self.root
        p1 = C.save(self.res(), root, "demo")
        self.assertEqual(C.save(self.res(at=2, git="bbb"), root, "demo"), p1)   # at・git・sec だけ違う = 同じ
        self.assertEqual(len(os.listdir(os.path.dirname(p1))), 1)
        self.assertEqual(printed(C.report_saved, self.res(at=3), True, root, "demo"), "\n" + C.SAME_MARK + p1 + "\n")
        p2 = C.save(self.res(v=2), root, "demo")                                  # 中身が違えば書く
        self.assertNotEqual(p2, p1)
        self.assertEqual(len(os.listdir(os.path.dirname(p1))), 2)
        self.assertIsNone(C.previous_same(self.res(v=1), root, "demo"))           # 比べるのは最新(p2)だけ

    def test_suffix_and_marks(self):
        root = self.root
        a = C.save(self.res(), root, "demo", "_x")
        self.assertIsNone(C.previous_same(self.res(), root, "demo", "-run"))       # 別の suffix は別の系列
        self.assertEqual(C.previous_same(self.res(), root, "demo", "_x"), a)
        m1 = C.save(self.res(), root, "marks")
        self.assertEqual(C.save(self.res(), root, "marks"), m1)                     # marks も同じ決まり
        self.assertIn(C.SAME_MARK, printed(C.report_saved, self.res(), True, root, "marks"))

    def test_unreadable_previous_gets_a_new_file(self):
        d = os.path.join(self.root, "evals", "demo")
        put(os.path.join(d, "20260101-000000.json"), "{壊れている".encode("utf-8"))
        self.assertTrue(C.save(self.res(), self.root, "demo").endswith(".json"))
        self.assertEqual(len(os.listdir(d)), 2)


class TestAudioSpan(unittest.TestCase):
    def setUp(self):
        self.data = testkit.tempdir(self)
        self.full = os.path.join(self.data, "dataset", "docs", "d1", "full.flac")
        put(self.full, b"x")
        self.video = os.path.join(self.data, "v.mp4")
        put(self.video, b"x")

    def test_video_first_then_stored_audio(self):
        doc = {"id": "d1", "sourcePath": self.video, "start": 10, "end": 50}
        spec, offset, where = C.audio_span(doc, self.data, boost=True)
        self.assertEqual((spec, offset, where), ({"sourcePath": self.video, "start": 10.0, "end": 50.0, "boost": True}, 10.0, "動画"))
        doc["sourcePath"] = os.path.join(self.data, "無い.mp4")   # 動画が無ければ保管の音声(範囲の先頭 = 0 秒・行の時刻の基準は start のまま)
        spec, offset, where = C.audio_span(doc, self.data, boost=False)
        self.assertEqual((spec, offset, where), ({"sourcePath": self.full, "start": 0.0, "end": None, "boost": False}, 10.0, "保管の音声"))

    def test_boost_none_has_no_key_and_doc_id(self):
        spec, _o, _w = C.audio_span({"sourcePath": self.video}, self.data, doc_id="d1")
        self.assertNotIn("boost", spec)
        self.assertEqual((spec["start"], spec["end"]), (0.0, None))

    def test_network_path_is_not_touched(self):
        # ネットワーク上の動画は存在を確かめない(資格情報を送らない)。保管の音声があればそちら・無ければ RuntimeError
        for src in ("\\\\server\\share\\v.mp4", "//server/share/v.mp4"):
            spec, _o, where = C.audio_span({"id": "d1", "sourcePath": src}, self.data)
            self.assertEqual((spec["sourcePath"], where), (self.full, "保管の音声"))
        os.unlink(self.full)
        with self.assertRaises(RuntimeError):
            C.audio_span({"id": "d1", "sourcePath": "\\\\server\\share\\v.mp4"}, self.data)

    def test_fake_job_is_new_each_time(self):
        a, b = C.fake_job(), C.fake_job()
        self.assertIsNot(a, b)
        self.assertEqual((a["cancel"], a["proc"], a["progress"]), (False, None, 0.0))


class TestReadAnswersWithRetext(unittest.TestCase):
    def test_time_text_overrides_older_read(self):
        """時刻のカードの「読みを直す」の文字は、同じ行の読みの答えより新しければ「打った文字」として読む(10-26)"""
        def row(kind, at, rid, ans):
            return {"id": "a%d" % at, "kind": kind, "source": "alt" if kind == "read" else "row", "at": at,
                    "target": {"docId": "d1", "row": rid}, "answer": ans}
        rows = [row("read", 1, "s1", {"choice": "2"}), row("time", 2, "s1", {"choice": "ok", "text": "直した"}),
                row("time", 3, "s2", {"choice": "ok", "text": "古い"}), row("read", 4, "s2", {"choice": "1"}),
                row("time", 5, "s3", {"choice": "ok", "text": "読みの答えなし"})]
        st = types.SimpleNamespace(effective=lambda: rows)
        with mock.patch("human.check.answerlog.state", lambda app_dir: st):
            got = C.read_answers("x", "read", "alt", {"1": 1, "2": 1, "other": 1})
        self.assertEqual(got[("d1", "s1")]["answer"], {"choice": "other", "text": "直した"})   # 新しい方 = 時刻のカードの文字
        self.assertEqual(got[("d1", "s2")]["answer"], {"choice": "1"})                        # 読みの答えが新しい
        self.assertNotIn(("d1", "s3"), got)                                                    # 読みの答えの無い行は出どころが分からない


if __name__ == "__main__":
    unittest.main()
