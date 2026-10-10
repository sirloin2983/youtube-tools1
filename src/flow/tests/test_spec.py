# -*- coding: utf-8 -*-
"""pipeline/spec.py(① に渡す指定の束の形・既定値・検査。RS1-6)のテスト。  py -3.10 -m unittest src/flow/tests/test_spec.py -v
- autorun.py から移した検査(clean_ranges・clean_weights・top_arg・marks_arg・row_edge_ok)は動きを変えていない(autorun の同じ名前も同じ物)
- merge = 既定値に変えたい所だけ重ねる(知らない節・鍵は ValueError)・validate = 型と範囲(理由つきの ValueError)
"""
import os
os.environ.setdefault("YTT_DATA_DIR", "inplace")   # 作業データは読み書きしないが、ほかのテストとそろえる
import copy
import sys
import unittest

SRC = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))   # tests -> pipeline -> src
sys.path.insert(0, SRC)
from flow import spec  # noqa: E402


class TestMoved(unittest.TestCase):
    def test_constants(self):
        self.assertEqual((spec.RANGE_MAX, spec.RANGE_MAX_SEC, spec.MAX_MARKS, spec.DEFAULT_TOP), (10, 3600, 50, 3))
        self.assertEqual(spec.CUTS, ("none", "silence"))
        self.assertEqual(spec.LIVE_AUTO_CUT, "none")
        self.assertEqual(spec.WEIGHT_KEYS, ("wAudio", "wChat", "wComments"))
        self.assertEqual(spec.TX_ENGINES, ("faster-whisper", "whisper.cpp", "qwen3-asr", "llama.cpp"))
        self.assertTrue(spec.TX_MODEL_RE.match("large-v3"))
        self.assertTrue(spec.TX_MODEL_RE.match("a" * 60))
        for bad in ("", "-x", "a" * 61, "a b", "../x", "x\n"):
            self.assertIsNone(spec.TX_MODEL_RE.match(bad), bad)

    def test_num_ok(self):
        for ok in (0, 1, -3.5, 9999999):
            self.assertTrue(spec.num_ok(ok), ok)
        for bad in (True, None, "1", float("nan"), float("inf"), 1e7, -1e7, 10 ** 400):
            self.assertFalse(spec.num_ok(bad), bad)

    def test_clean_ranges(self):
        self.assertEqual(spec.clean_ranges(None), [])
        self.assertEqual(spec.clean_ranges([]), [])
        self.assertEqual(spec.clean_ranges([[1, 2.26], (3, 4)]), [(1.0, 2.3), (3.0, 4.0)])
        for bad in ("x", [[1]], [[2, 1]], [[0, 3601]], [[-1, 5]], [["1", 2]], [[True, 2]], [[i, i + 1] for i in range(11)]):
            with self.assertRaises(ValueError, msg=bad):
                spec.clean_ranges(bad)
        with self.assertRaises(ValueError) as cm:
            spec.clean_ranges([[5, 1]])
        self.assertEqual(str(cm.exception), "区間の指定が正しくありません")
        self.assertEqual(spec.clean_ranges([[0, 3600]]), [(0.0, 3600.0)])
        self.assertEqual(len(spec.clean_ranges([[i, i + 1] for i in range(10)])), 10)

    def test_clean_weights(self):
        self.assertEqual(spec.clean_weights({"wAudio": 1, "wChat": 0.25, "wComments": 3}), {"wAudio": 1.0, "wChat": 0.2, "wComments": 3.0})
        self.assertIsNone(spec.clean_weights(None))
        self.assertIsNone(spec.clean_weights({"wAudio": 4, "wChat": 1, "wComments": 1}))
        self.assertIsNone(spec.clean_weights({"wAudio": True, "wChat": 1, "wComments": 1}))
        self.assertIsNone(spec.clean_weights({"wAudio": 1, "wChat": 1}))
        self.assertIsNone(spec.clean_weights({"wAudio": -0.1, "wChat": 1, "wComments": 1}))

    def test_top_arg(self):
        self.assertEqual(spec.top_arg(None), 3)
        self.assertEqual(spec.top_arg(""), 3)
        self.assertEqual((spec.top_arg(1), spec.top_arg(30)), (1, 30))
        for bad in (0, 31, True, 2.0, "3", [1]):
            with self.assertRaises(ValueError, msg=bad):
                spec.top_arg(bad)

    def test_marks_arg(self):
        self.assertIsNone(spec.marks_arg(None))
        self.assertIsNone(spec.marks_arg([]))
        self.assertEqual(spec.marks_arg(["m1", "m2", "m1"]), ("m1", "m2"))   # 重ならない組・順番はそのまま
        for bad in ("m1", [1], ["../x"], ["m" * 41], [""], ["m%d" % i for i in range(spec.MAX_MARKS + 1)]):
            with self.assertRaises(ValueError, msg=bad):
                spec.marks_arg(bad)
        self.assertEqual(len(spec.marks_arg(["m%d" % i for i in range(spec.MAX_MARKS)])), spec.MAX_MARKS)

    def test_row_edge_ok(self):
        for ok in (True, False, {}, {"on": False}, {"after": 0.5, "before": 2}, {"after": "", "before": None}):
            self.assertTrue(spec.row_edge_ok(ok), ok)
        for bad in (None, 1, "x", {"on": 1}, {"after": 2.1}, {"before": -0.1}, {"after": True}, {"after": "1"}):
            self.assertFalse(spec.row_edge_ok(bad), bad)

    def test_autorun_still_exposes_the_names(self):
        """autorun は同じ名前で読み直している(test_autorun.py・ほかの使い手がそのまま動く)"""
        sys.path.insert(0, os.path.join(SRC, "home"))
        import autorun as A   # noqa: E402
        for name in ("RANGE_MAX", "RANGE_MAX_SEC", "CUTS", "TX_ENGINES", "TX_MODEL_RE", "WEIGHT_KEYS", "MAX_MARKS", "DEFAULT_TOP", "LIVE_AUTO_CUT",
                     "clean_ranges", "clean_weights"):
            self.assertIs(getattr(A, name), getattr(spec, name), name)
        self.assertIs(A._top_arg, spec.top_arg)
        self.assertIs(A._row_edge_ok, spec.row_edge_ok)
        self.assertIs(A._num, spec.num_ok)
        self.assertEqual(A.AutoRunner._marks_arg(["a", "a"]), ("a",))
        with self.assertRaises(ValueError):
            A.AutoRunner._marks_arg("a")


class TestMerge(unittest.TestCase):
    def test_defaults_are_valid_and_complete(self):
        self.assertEqual(spec.validate(spec.merge(None)), spec.DEFAULTS)
        self.assertEqual(spec.merge({}), spec.DEFAULTS)
        self.assertEqual(tuple(spec.DEFAULTS), spec.SECTIONS)
        self.assertEqual(set(spec.SCHEMA), set(spec.SECTIONS))
        for sec in spec.SECTIONS:   # 検査の表と既定値の鍵は同じ(片方だけ増やした食い違いを落とす)
            self.assertEqual(set(spec.SCHEMA[sec]), set(spec.DEFAULTS[sec]), sec)

    def test_known_defaults(self):
        d = spec.merge(None)
        self.assertEqual((d["export"]["volume"], d["export"]["loudness"]), (75, -14))
        self.assertEqual((d["pack"]["size"], d["pack"]["volume"], d["pack"]["loudness"]), ("1080x1920", 30, 0))
        self.assertEqual((d["pack"]["backup"], d["pack"]["speakerColors"], d["pack"]["cut"]), (False, True, "none"))
        self.assertEqual(d["adopt"]["top"], spec.DEFAULT_TOP)
        self.assertEqual((d["analyze"]["wAudio"], d["analyze"]["wChat"], d["analyze"]["wComments"]), (1.0, 1.0, 0.7))

    def test_fixed_items_are_not_keys(self):
        for k in spec.FIXED:
            for sec in spec.SECTIONS:
                self.assertNotIn(k, spec.DEFAULTS[sec], "%s.%s" % (sec, k))
        self.assertEqual((spec.FIXED["fps"], spec.FIXED["on_fail"], spec.FIXED["upto"]), (30, "next", "pack"))

    def test_overlay(self):
        b = spec.merge({"adopt": {"top": 5}, "pack": {"cutSilence": {"min": 1.0}, "cut": "silence"}, "hints": {"ranges": [[1, 9]]}})
        self.assertEqual(b["adopt"]["top"], 5)
        self.assertEqual(b["adopt"]["pad"], spec.DEFAULTS["adopt"]["pad"])   # 渡さなかった所は既定のまま
        self.assertEqual(b["pack"]["cutSilence"], {"noise": -35.0, "min": 1.0, "pad": 0.15})   # 辞書は鍵ごとに重なる
        self.assertEqual(b["hints"]["ranges"], [[1, 9]])
        spec.validate(b)

    def test_does_not_touch_defaults_or_input(self):
        before = copy.deepcopy(spec.DEFAULTS)
        given = {"hints": {"ranges": [[1, 9]], "people": [{"name": "A"}]}, "pack": {"wrapChars": {"vertical": 9}}}
        keep = copy.deepcopy(given)
        b = spec.merge(given)
        b["hints"]["ranges"].append([20, 30])
        b["hints"]["people"][0]["name"] = "B"
        b["pack"]["wrapChars"]["horizontal"] = 3
        b["post"]["maxChars"]["vertical"] = 1
        self.assertEqual(spec.DEFAULTS, before)
        self.assertEqual(given, keep)

    def test_unknown_section_or_key(self):
        for bad in ({"nope": {}}, {"adopt": {"tpo": 3}}, {"pack": {"cutSilence": {"nois": 1}}}):
            with self.assertRaises(ValueError, msg=bad) as cm:
                spec.merge(bad)
            self.assertIn("知らない", str(cm.exception))
        for bad in ([], "x", {"adopt": 3}, {"pack": {"cutSilence": 3}}):
            with self.assertRaises(ValueError, msg=bad):
                spec.merge(bad)


class TestValidate(unittest.TestCase):
    def bad(self, sec, **kw):
        b = spec.merge(None)
        b[sec].update(kw)
        with self.assertRaises(ValueError, msg=(sec, kw)) as cm:
            spec.validate(b)
        return str(cm.exception)

    def test_shape(self):
        with self.assertRaises(ValueError):
            spec.validate([])
        b = spec.merge(None)
        del b["run"]
        with self.assertRaises(ValueError):
            spec.validate(b)
        b = spec.merge(None)
        del b["pack"]["size"]
        with self.assertRaises(ValueError):
            spec.validate(b)
        b = spec.merge(None)
        b["pack"]["extra"] = 1
        with self.assertRaises(ValueError):
            spec.validate(b)
        b = spec.merge(None)
        b["extra"] = {}
        with self.assertRaises(ValueError):
            spec.validate(b)

    def test_messages_name_the_item(self):
        self.assertIn("adopt.top", self.bad("adopt", top=0))
        self.assertIn("transcribe.engine", self.bad("transcribe", engine="whisperx"))

    def test_hints(self):
        spec.validate(spec.merge({"hints": {"ranges": [[0, 10], (20, 30.5)], "people": [{"name": "A", "color": "#ff6699"}, {"name": "B"}]}}))
        spec.validate(spec.merge({"hints": {"people": {"count": 3}}}))
        for bad in ("x", [[2, 1]], [[0, 3601]], [[i, i + 1] for i in range(11)], None):
            self.bad("hints", ranges=bad)
        for bad in ("x", {"count": 0}, {"count": 11}, {"count": 2, "x": 1}, [{"name": ""}], [{"color": "#ffffff"}], [{"name": "A", "color": "red"}], [{"name": "A", "x": 1}], ["A"]):
            self.bad("hints", people=bad)

    def test_analyze(self):
        spec.validate(spec.merge({"analyze": {"wAudio": 3, "wChat": 0, "count": 30, "length": 10, "preRatio": 0.9, "lag": 0, "sensitivity": "low"}}))
        for kw in ({"wAudio": 3.1}, {"wChat": -1}, {"wComments": True}, {"wAudio": "1"}, {"sensitivity": "mid"}, {"count": 0}, {"count": 31}, {"count": 8.0},
                   {"length": 9}, {"length": 121}, {"preRatio": 0.2}, {"headSec": 601}, {"lag": 31}, {"lagAuto": 1}, {"chatTimeout": 0}, {"useChat": None}):
            self.bad("analyze", **kw)

    def test_adopt_export(self):
        spec.validate(spec.merge({"adopt": {"top": 30, "perHour": 30, "waitMin": 60}, "export": {"loudness": None, "volume": 200}}))
        for kw in ({"top": None}, {"top": 31}, {"top": True}, {"top": 2.0}, {"pad": -1}, {"perHour": 0}, {"waitMin": 61}):
            self.bad("adopt", **kw)
        for kw in ({"loudness": -12}, {"loudness": 0}, {"loudness": True}, {"volume": 0}, {"volume": 201}):
            self.bad("export", **kw)
        spec.validate(spec.merge({"export": {"loudness": -18}}))

    def test_transcribe(self):
        spec.validate(spec.merge({"transcribe": {"engine": "whisper.cpp", "model": "large-v3-turbo", "language": "auto", "quality": "fast", "device": "vulkan",
                                                 "vadMode": "off", "boost": True, "diarize": 10}}))
        for kw in ({"engine": "x"}, {"engine": None}, {"model": ""}, {"model": "a b"}, {"model": 3}, {"language": "fr"}, {"quality": "normal"},
                   {"device": "gpu"}, {"vadMode": "strong"}, {"boost": "yes"}, {"diarize": 0}, {"diarize": 11}, {"diarize": True}):
            self.bad("transcribe", **kw)

    def test_post(self):
        spec.validate(spec.merge({"post": {"orientation": "horizontal", "maxChars": {"horizontal": 40}, "splitChars": 8, "autoLlm": False,
                                           "learning": {"dir": "D:/x", "version": "abc"}}}))
        for kw in ({"orientation": "square"}, {"maxChars": {"vertical": 3, "horizontal": 28}}, {"maxChars": {"vertical": 16}}, {"splitChars": 7},
                   {"splitChars": 81}, {"autoFill": 1}, {"learning": {"dir": 3, "version": None}}, {"learning": {"dir": None}}):
            self.bad("post", **kw)

    def test_pack(self):
        spec.validate(spec.merge({"pack": {"size": "1920x1080", "loudness": -16, "volume": 100, "backup": True, "render": True, "rowEdge": {"after": 1.0},
                                           "cut": "silence", "videoTracks": 5, "wrapChars": {"vertical": 2, "horizontal": 40},
                                           "cutSilence": {"noise": -90, "min": 0.05, "pad": 10}}}))
        spec.validate(spec.merge({"pack": {"cut": "rows"}}))   # 行から(ホームの設定 autorun.cut の選択肢)も束で表せる
        for kw in ({"size": "1280x720"}, {"loudness": -12}, {"loudness": None}, {"volume": 0}, {"backup": 1}, {"speakerColors": None},
                   {"rowEdge": {"after": 3}}, {"rowEdge": None}, {"cut": "words"}, {"cut": ""}, {"videoTracks": 0}, {"videoTracks": 6},
                   {"wrapChars": {"vertical": 1, "horizontal": 14}}, {"cutSilence": {"noise": 1, "min": 0.6, "pad": 0.15}},
                   {"cutSilence": {"noise": -35, "min": 0.01, "pad": 0.15}}, {"cutSilence": {"noise": -35, "min": 0.6}}):
            self.bad("pack", **kw)

    def test_run(self):
        spec.validate(spec.merge({"run": {"from": "export", "force": True}}))
        for kw in ({"from": "deliver"}, {"from": ""}, {"force": "no"}):
            self.bad("run", **kw)
        for step in spec.RUN_FROM:
            spec.validate(spec.merge({"run": {"from": step}}))


if __name__ == "__main__":
    unittest.main()
