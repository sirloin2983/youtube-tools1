# -*- coding: utf-8 -*-
"""pipeline/spec.py(① に渡す指定の束の形・既定値・検査。RS1-6)のテスト。  py -3.12 -m unittest tests/flow/test_spec.py -v
- 検査(clean_ranges・clean_weights・top_arg・marks_arg・row_edge_ok)は autorun の同じ名前と同じ物
- merge = 既定値に変えたい所だけ重ねる(知らない節・鍵は ValueError)・validate = 型と範囲(理由つきの ValueError)
"""
import os
os.environ.setdefault("YTT_DATA_DIR", "inplace")   # 作業データは読み書きしないが、ほかのテストとそろえる
import copy
import sys
import unittest
from unittest import mock

SRC = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "src")   # tests -> pipeline -> src
sys.path.insert(0, SRC)
from flow import spec  # noqa: E402


class TestMoved(unittest.TestCase):
    def test_constants(self):
        self.assertEqual((spec.RANGE_MAX, spec.PAD_MAX, spec.MAX_MARKS, spec.DEFAULT_TOP), (10, 3600, 50, 3))
        self.assertFalse(hasattr(spec, "RANGE_MAX_SEC"), "区間 1 つの長さは上限なし(C-2-7・C-5-5)")
        self.assertEqual(spec.CUTS, ("none", "silence"))
        self.assertEqual(spec.LIVE_AUTO_CUT, "none")
        self.assertEqual(spec.WEIGHT_KEYS, ("wAudio", "wChat", "wComments"))
        self.assertEqual((spec.TX_ENGINES, spec.TX_MODELS, spec.TX_DEVICES), (("whisper.cpp",), ("large-v3",), ("vulkan", "cuda")))   # cuda は F1 F0-2
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
        for bad in ("x", [[1]], [[2, 1]], [[0, 360001]], [[-1, 5]], [["1", 2]], [[True, 2]], [[i, i + 1] for i in range(11)]):
            with self.assertRaises(ValueError, msg=bad):
                spec.clean_ranges(bad)
        with self.assertRaises(ValueError) as cm:
            spec.clean_ranges([[5, 1]])
        self.assertEqual(str(cm.exception), "区間の指定が正しくありません")
        self.assertEqual(spec.clean_ranges([[0, 3600]]), [(0.0, 3600.0)])
        self.assertEqual(spec.clean_ranges([[0, 3601], [600, 600 + 3 * 3600]]), [(0.0, 3601.0), (600.0, 11400.0)])   # 長さの上限なし(3 時間も通る)
        self.assertEqual(spec.clean_ranges([[0, 360000]]), [(0.0, 360000.0)])   # 時刻の上限(100 時間)いっぱいまで
        self.assertEqual(len(spec.clean_ranges([[i, i + 1] for i in range(10)])), 10)
        with self.assertRaises(ValueError):
            spec.clean_ranges([[0.01, 0.04]])   # 丸めたあと長さ 0(opt-human 9b-2)

    def test_check_ranges(self):
        """理由つきの検査(opt-human 9b-2。友人の受付 intake.parse_ranges が呼ぶ): 形の違う区間だけ断り、ほかは進める"""
        self.assertEqual(spec.check_range((10, 20)), ((10.0, 20.0), ""))
        for r, why in (((5, 5), "終了が開始より前"), ((0.01, 0.04), "短すぎます"), (("1", 2), "形が正しくありません"),
                       ((True, 2), "形が正しくありません"), ((0, 360001), "形が正しくありません"), (None, "形が正しくありません"), ((1,), "形が正しくありません")):
            got, msg = spec.check_range(r)
            self.assertIsNone(got, r)
            self.assertIn(why, msg, r)
        self.assertEqual(spec.check_ranges(None), ([], []))
        self.assertEqual(spec.check_ranges("x"), ([], ["区間の形が正しくありません"]))
        ok, bad = spec.check_ranges([(10, 20), (9, 3), (10, 20.04)] + [(i * 100, i * 100 + 5) for i in range(1, 12)])
        self.assertEqual((len(ok), ok[0], len(bad)), (spec.RANGE_MAX, (10.0, 20.0), 1 + 2))   # 同じ区間(丸めたあと)は 1 つ・上限を超えた 2 つは理由つき
        self.assertTrue(any("個までです" in b for b in bad))

    def test_check_weights(self):
        self.assertEqual(spec.check_weights({"wAudio": 1, "wChat": 0.25, "wComments": 3}), ({"wAudio": 1.0, "wChat": 0.2, "wComments": 3.0}, ""))
        for bad in (None, {"wAudio": 4, "wChat": 1, "wComments": 1}, {"wAudio": True, "wChat": 1, "wComments": 1}, {"wAudio": 1, "wChat": 1},
                    {"wAudio": float("inf"), "wChat": 1, "wComments": 1}):
            got, why = spec.check_weights(bad)
            self.assertIsNone(got, bad)
            self.assertTrue(why, bad)

    def test_clean_weights(self):
        self.assertEqual(spec.clean_weights({"wAudio": 1, "wChat": 0.25, "wComments": 3}), {"wAudio": 1.0, "wChat": 0.2, "wComments": 3.0})
        for bad in (None, {"wAudio": 4, "wChat": 1, "wComments": 1}, {"wAudio": True, "wChat": 1, "wComments": 1}, {"wAudio": 1, "wChat": 1},
                    {"wAudio": -0.1, "wChat": 1, "wComments": 1}):
            self.assertIsNone(spec.clean_weights(bad), bad)

    def test_top_arg(self):
        self.assertEqual(spec.top_arg(None), 3)
        self.assertEqual(spec.top_arg(""), 3)
        self.assertEqual((spec.top_arg(1), spec.top_arg(30), spec.top_arg(99)), (1, 30, 99))   # 上限なし(10-20)
        for bad in (0, True, 2.0, "3", [1]):
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


class TestMerge(unittest.TestCase):

    def test_known_defaults(self):
        d = spec.merge(None)
        self.assertEqual((d["export"]["volume"], d["export"]["loudness"]), (75, -14))
        self.assertEqual((d["pack"]["size"], d["pack"]["volume"], d["pack"]["loudness"]), ("1080x1920", 30, 0))
        self.assertEqual((d["pack"]["speakerColors"], d["pack"]["cut"]), (True, "none"))
        self.assertNotIn("backup", d["pack"])   # パックの予備は束に無い(決定 3-34)
        self.assertEqual(d["adopt"]["top"], spec.DEFAULT_TOP)
        self.assertEqual((d["analyze"]["wAudio"], d["analyze"]["wChat"], d["analyze"]["wComments"]), (1.0, 1.0, 0.7))

    def test_renamed_pinned_reads_as_requested(self):
        """RV A2: 旧い鍵 run.pinned は run.requested として読む(待ちの記録・録画の束を書き換えない)。両方あれば今の名前"""
        self.assertEqual(spec.merge({"run": {"pinned": ["cut"]}})["run"]["requested"], ["cut"])
        self.assertNotIn("pinned", spec.merge({"run": {"pinned": ["cut"]}})["run"])
        self.assertEqual(spec.merge({"run": {"pinned": ["cut"], "requested": ["weights"]}})["run"]["requested"], ["weights"])
        for bad in ({"run": {"upto": "export"}}, {"run": {"onFail": "x"}}, {"hints": {"streamer": 1}}, {"hints": {"streamer": "x" * 121}}):
            with self.assertRaises(ValueError, msg=bad):
                spec.validate(spec.merge(bad))

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
        def no_run(b):
            del b["run"]

        def no_size(b):
            del b["pack"]["size"]

        def pack_extra(b):
            b["pack"]["extra"] = 1
        for name, spoil in (("section", no_run), ("key", no_size), ("pack extra", pack_extra), ("top extra", lambda b: b.update(extra={}))):
            b = spec.merge(None)
            spoil(b)
            with self.assertRaises(ValueError, msg=name):
                spec.validate(b)
        with self.assertRaises(ValueError):
            spec.validate([])

    def test_messages_name_the_item(self):
        self.assertIn("adopt.top", self.bad("adopt", top=0))
        self.assertIn("transcribe.engine", self.bad("transcribe", engine="whisperx"))

    def test_hints(self):
        spec.validate(spec.merge({"hints": {"ranges": [[0, 10], (20, 30.5)], "people": [{"name": "A", "color": "#ff6699"}, {"name": "B"}]}}))
        spec.validate(spec.merge({"hints": {"people": {"count": 3}}}))
        for bad in ("x", [[2, 1]], [[0, 360001]], [[i, i + 1] for i in range(11)], None):
            self.bad("hints", ranges=bad)
        for bad in ("x", {"count": 0}, {"count": 11}, {"count": 2, "x": 1}, [{"name": ""}], [{"color": "#ffffff"}], [{"name": "A", "color": "red"}], [{"name": "A", "x": 1}], ["A"]):
            self.bad("hints", people=bad)

    def test_analyze(self):
        spec.validate(spec.merge({"analyze": {"wAudio": 3, "wChat": 0, "count": 30, "length": 10, "preRatio": 0.9, "lag": 0, "sensitivity": "low"}}))
        for kw in ({"wAudio": 3.1}, {"wChat": -1}, {"wComments": True}, {"wAudio": "1"}, {"sensitivity": "mid"}, {"count": 0}, {"count": 31}, {"count": 8.0},
                   {"length": 9}, {"length": 301}, {"preRatio": 0.2}, {"headSec": 601}, {"lag": 31}, {"lagAuto": 1}, {"chatTimeout": 0}, {"useChat": None}):
            self.bad("analyze", **kw)

    def test_adopt_export(self):
        spec.validate(spec.merge({"adopt": {"top": 30, "perHour": 30, "waitMin": 60}, "export": {"loudness": None, "volume": 200}}))
        spec.validate(spec.merge({"adopt": {"sens": "high", "afterStream": False}}))
        self.assertEqual((spec.DEFAULTS["adopt"]["sens"], spec.DEFAULTS["adopt"]["afterStream"]), ("normal", True))
        for kw in ({"sens": "mid"}, {"sens": None}, {"afterStream": 1}, {"afterStream": "yes"}):
            self.bad("adopt", **kw)
        for kw in ({"top": None}, {"top": 0}, {"top": True}, {"top": 2.0}, {"pad": -1}, {"perHour": 0}, {"waitMin": 61}):
            self.bad("adopt", **kw)
        for kw in ({"loudness": -12}, {"loudness": 0}, {"loudness": True}, {"volume": 0}, {"volume": 201}):
            self.bad("export", **kw)
        spec.validate(spec.merge({"export": {"loudness": -18}}))

    def test_transcribe(self):
        spec.validate(spec.merge({"transcribe": {"engine": "whisper.cpp", "model": "large-v3", "language": "auto", "quality": "fast", "device": "vulkan",
                                                 "vadMode": "off", "boost": True, "diarize": 10}}))
        # 旧い値は断らずに読み替える(エンジン → whisper.cpp・機器 → vulkan・large-v3 でないモデルの名前 → large-v3)・使わない項目 redoLarge・autoRedo は捨てる
        for eng, model, dev in (("faster-whisper", "small", "auto"), ("qwen3-asr", "qwen3-asr-0.6b", "cpu"), ("llama.cpp", "large-v3-turbo", "cuda"),
                                ("faster-whisper", "kotoba-tech/kotoba-whisper-v2.0-faster", "cpu")):
            b = spec.validate(spec.merge({"transcribe": {"engine": eng, "model": model, "device": dev}, "post": {"redoLarge": False, "autoRedo": True}}))
            self.assertEqual((b["transcribe"]["engine"], b["transcribe"]["model"], b["transcribe"]["device"]), ("whisper.cpp", "large-v3", "vulkan"))
            self.assertNotIn("redoLarge", b["post"])
            self.assertNotIn("autoRedo", b["post"])
        self.assertEqual(spec.read_legacy_tx("language", "auto"), "auto")   # transcribe の 3 つの項目だけ
        # F1 F0-2: cuda = whisper.cpp の CUDA 版(エンジンは同じ whisper.cpp)。旧いエンジンと組の cuda だけ旧い意味(faster-whisper の CUDA)で vulkan に読む
        b = spec.validate(spec.merge({"transcribe": {"device": "cuda"}}))
        self.assertEqual((b["transcribe"]["engine"], b["transcribe"]["device"]), ("whisper.cpp", "cuda"))
        self.assertEqual(spec.read_legacy_tx("device", "cuda"), "cuda")
        b = spec.validate(spec.merge({"transcribe": {"engine": "faster-whisper", "device": "cuda"}}))
        self.assertEqual((b["transcribe"]["engine"], b["transcribe"]["device"]), ("whisper.cpp", "vulkan"))
        for kw in ({"engine": "x"}, {"engine": None}, {"model": ""}, {"model": "a b"}, {"model": 3}, {"language": "fr"}, {"quality": "normal"},
                   {"device": "gpu"}, {"vadMode": "strong"}, {"boost": "yes"}, {"diarize": 0}, {"diarize": 11}, {"diarize": True}):
            self.bad("transcribe", **kw)

    def test_post(self):
        spec.validate(spec.merge({"post": {"orientation": "horizontal", "maxChars": {"horizontal": 40}, "splitChars": 8, "autoLlm": False,
                                           "learning": {"version": "abc"}}}))
        for kw in ({"orientation": "square"}, {"maxChars": {"vertical": 3, "horizontal": 28}}, {"maxChars": {"vertical": 16}}, {"splitChars": 7},
                   {"splitChars": 81}, {"autoFill": 1}, {"learning": {"version": None}}, {"learning": {"dir": "D:/x"}}, {"learning": {"version": "x" * 81}}):
            self.bad("post", **kw)

    def test_hint_readers(self):
        b = spec.merge({"hints": {"ranges": [[10, 20], [500, 520]], "people": [{"name": " A ", "color": "#ff6699"}, {"name": "B"}]}})
        self.assertEqual(spec.hint_ranges(b), [[8.0, 22.0], [498.0, 522.0]])
        self.assertEqual(spec.hint_ranges(b, 100), [[8.0, 22.0]])   # 動画の外は落とす
        self.assertEqual(spec.hint_ranges(b, 100, pad=0), [[10.0, 20.0]])
        self.assertEqual(spec.hint_ranges(spec.merge(None)), [])
        self.assertEqual(spec.hint_people(b), {"people": [{"name": "A", "color": "#ff6699"}, {"name": "B", "color": None}], "count": 2})
        self.assertEqual(spec.hint_people(spec.merge({"hints": {"people": {"count": 3}}})), {"people": [], "count": 3})
        self.assertEqual(spec.hint_people(spec.merge(None)), {"people": [], "count": None})
        self.bad("hints", people=[{"name": "A"}, {"name": "A"}])
        self.bad("hints", people=[{"name": str(i)} for i in range(11)])

    def test_learning_version(self):
        self.assertNotIn("learningVersion", spec.tx_opts(spec.merge(None)))   # 既定は書かない = 要求も鍵も今と同じ
        o = spec.tx_opts(spec.merge({"post": {"learning": {"version": "v2"}}}))
        self.assertEqual(o["learningVersion"], "v2")

    def test_old_pack_backup_and_render_are_dropped(self):
        """古い束・待ちの記録・録画の束の pack.backup(パックの予備。決定 3-34)・pack.render(粗編集の動画。10-24)は断らずに黙って捨てる"""
        for v in (True, False, 1):
            b = spec.validate(spec.merge({"pack": {"backup": v, "render": v, "speakerColors": False}}))
            self.assertNotIn("backup", b["pack"])
            self.assertNotIn("render", b["pack"])
            self.assertIs(b["pack"]["speakerColors"], False)
        base = spec.validate(spec.merge(None))
        self.assertNotIn("render", spec.validate(spec.merge_onto(base, {"pack": {"backup": True, "render": True}}))["pack"])

    def test_pack(self):
        spec.validate(spec.merge({"pack": {"size": "1920x1080", "loudness": -16, "volume": 100, "rowEdge": {"after": 1.0},
                                           "cut": "silence", "videoTracks": 5, "wrapChars": {"vertical": 2, "horizontal": 40},
                                           "cutSilence": {"noise": -90, "min": 0.05, "pad": 10}}}))
        spec.validate(spec.merge({"pack": {"cut": "rows"}}))   # 行から(ホームの設定 autorun.cut の選択肢)も束で表せる
        for kw in ({"size": "1280x720"}, {"loudness": -12}, {"loudness": None}, {"volume": 0}, {"speakerColors": None},
                   {"rowEdge": {"after": 3}}, {"rowEdge": None}, {"cut": "words"}, {"cut": ""}, {"videoTracks": 0}, {"videoTracks": 6},
                   {"wrapChars": {"vertical": 41, "horizontal": 14}}, {"cutSilence": {"noise": 1, "min": 0.6, "pad": 0.15}},
                   {"cutSilence": {"noise": -35, "min": 0.01, "pad": 0.15}}, {"cutSilence": {"noise": -35, "min": 0.6}}):
            self.bad("pack", **kw)

    def test_run(self):
        spec.validate(spec.merge({"run": {"from": "export", "force": True}}))
        for kw in ({"from": "deliver"}, {"from": ""}, {"force": "no"}):
            self.bad("run", **kw)
        for step in spec.RUN_FROM:
            spec.validate(spec.merge({"run": {"from": step}}))


class TestBodies(unittest.TestCase):
    """束 → 各ツールの API の本文。画面の設定 → 束は tests/app/test_autorun.py の TestSpecFromSettings"""

    def test_key_ok(self):
        self.assertTrue(spec.key_ok("pack", "wrapChars", {"vertical": 9}))   # 辞書は既定に重ねてから見る
        self.assertTrue(spec.key_ok("pack", "wrapChars", {"vertical": 0}))   # 0 = 改行しない
        for sec, k, v in (("pack", "wrapChars", {"vertical": 41}), ("pack", "nai", 1), ("nai", "x", 1), ("analyze", "count", 5.0),
                          ("transcribe", "model", "../x"), ("pack", "rowEdge", {"on": "yes"})):
            self.assertFalse(spec.key_ok(sec, k, v), (sec, k, v))
        self.assertTrue(spec.key_ok("analyze", "count", 5))

    def test_export_body(self):
        b = spec.merge({"export": {"volume": 60, "loudness": None}})
        self.assertEqual(spec.export_body(b, "v", ("m1",))["margin"], spec.MARGIN_DEFAULT)   # 余白(LD-2f)の既定
        b = spec.merge({"export": {"volume": 60, "loudness": None, "margin": 0}})
        self.assertEqual(spec.export_body(b, "v", ("m1",))["margin"], 10.0)   # 10-29 から余白は固定(束の 0 も 10 秒 = ytt/marks.CLIP_MARGIN_SEC)
        self.assertEqual([spec.export_margin(x) for x in ({"export": {"volume": 60, "margin": 25}}, {"export": {"volume": 60}}, None)], [10.0, 10.0, 10.0])
        with mock.patch.object(spec._marks, "CLIP_MARGIN_FIXED", False):   # スイッチ: 前の形 = 束の export.margin(値の境は tests/ytt/test_marks.py の clip_margin)
            self.assertEqual(spec.export_body(b, "v", ("m1",)), {"id": "v", "markIds": ["m1"], "precision": "accurate", "maxHeight": 0, "volume": 60, "loudness": None})
            self.assertEqual([spec.export_margin(x) for x in ({"export": {"margin": 25}}, {"export": {"volume": 60}}, None)], [25.0, 0.0, 0.0])   # 余白を足す前の束・束なし = 0

    def test_tx_opts(self):
        o = spec.tx_opts(spec.merge(None))
        self.assertEqual(set(o), set(spec.TX_TRANSCRIBE_KEYS + spec.TX_POST_KEYS))
        self.assertEqual((o["model"], o["device"], o["quality"], o["autoLearned"]), ("large-v3", "vulkan", "best", False))   # 既定
        self.assertNotIn("engine", o)   # エンジンは機器(vulkan)から決まる = 書かない
        self.assertNotIn("engine", spec.tx_opts(spec.merge({"transcribe": {"engine": "faster-whisper", "device": "cpu"}})))   # 旧い値も GPU に読む
        self.assertNotIn("glossary", o)   # 用語集は書かない(編集の受付が自分の設定から読む。RS7-1 S4)
        self.assertNotIn("redoLarge", o)   # 使わない項目
        self.assertNotIn("people", spec.tx_opts(spec.merge({"hints": {"people": [{"name": "A"}]}})))   # 1 人は今と同じ本文
        self.assertEqual(spec.tx_opts(spec.merge({"hints": {"people": [{"name": "A"}, {"name": "B"}]}}))["people"], ["A", "B"])   # 2 人以上 = 行ごとの声の名前
        for dev in ("vulkan", "cuda", "cpu", "auto", None):
            self.assertEqual(spec.implied_engine(dev), "whisper.cpp")
        o = spec.tx_opts(spec.merge({"transcribe": {"device": "cuda"}}))   # F1 F0-2: 機器 cuda は本文に残り、エンジンは書かない(受付が whisper.cpp に決める)
        self.assertEqual((o["device"], "engine" in o), ("cuda", False))

    def test_pack_output(self):
        row_edge, out, cs = spec.pack_output(spec.merge(None))
        self.assertIs(row_edge, True)
        self.assertEqual(out, {"textplusWrap": 8, "textplusSize": "1080x1920", "textplusFps": "30", "speakerColors": True, "loudness": -14.0})   # そろえない(0)でも目標へ
        self.assertEqual(cs, {"noise": -35.0, "min": 0.6, "pad": 0.15})
        b = spec.merge({"pack": {"size": "1920x1080", "loudness": -14, "backup": True, "render": True, "videoTracks": 3, "speakerColors": False}})
        _re, out, _cs = spec.pack_output(b)   # 古い束の pack.backup・render: true は読み捨てる(要求に書かない = 決定 3-34・10-24)
        self.assertEqual(out, {"textplusWrap": 14, "textplusSize": "1920x1080", "textplusFps": "30", "speakerColors": False,
                               "loudness": -14, "videoTracks": 3})


class TestPadRange(unittest.TestCase):
    def test_pad_range(self):
        """友人の区間の前後の余白(既定 2 秒): 0 より前・動画の長さより後には出さない。区間の長さの上限は無い = 余白はそのまま"""
        self.assertEqual(spec.pad_range(100, 190), [98.0, 192.0])
        self.assertEqual(spec.pad_range(1, 30, 31.0), [0.0, 31.0])
        self.assertEqual(spec.pad_range(0, 3600), [0.0, 3602.0])
        self.assertEqual(spec.pad_range(10, 3609), [8.0, 3611.0])


if __name__ == "__main__":
    unittest.main()
