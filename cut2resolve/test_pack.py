#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""cut2resolve の見直し(2026-09)で直した所・足した所のテスト。
python -m unittest test_cut2resolve で一緒に走る(test_cut2resolve の load_tests)。単独なら python -m unittest test_pack"""
import json
import os
import subprocess
import sys
import tempfile
import threading
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).parent))
import auto_cut as AC  # noqa: E402
import cut2resolve as FULL  # noqa: E402
import cut2resolve_core as C  # noqa: E402
import pack  # noqa: E402
import resolve_textplus as RTP  # noqa: E402
import srt2resolve as S  # noqa: E402
from test_cut2resolve import FPS30, HAVE_FFMPEG, make_video, parse_edl, tc2f  # noqa: E402


def write(path, text, enc="utf-8"):
    Path(path).write_text(text, encoding=enc)
    return Path(path)


def transcript_doc(rows, media=None):
    return {"schema": "youtube-tools-transcript/v1", "tool": {"name": "transcribe-tool", "version": "0.10.0"},
            "media": media or {}, "segments": [dict(id="s%d" % i, start=a, end=b, text=t, cut=c)
                                              for i, (a, b, t, c) in enumerate(rows, 1)]}


class TestResolveTextPlusScript(unittest.TestCase):
    def test_captions_are_placed_on_v2_at_timeline_start_offset(self):
        plan = {"title": "test", "fps": "30/1", "nominalFps": 30,
                "media": {"file": "media/test.mov", "name": "test.mov", "width": 1080, "height": 1920},
                "cuts": [{"sourceStartFrame": 0, "sourceEndFrame": 120}],
                "captions": [{"startFrame": 27, "endFrame": 93, "text": "日本語字幕"}],
                "sourceTimeline": {"startFrame": 0, "endFrame": 120}}
        script = RTP.importer_script(plan)
        self.assertIn('recordFrame = baseFrame + cap.startFrame', script)
        self.assertIn('trackIndex=2, recordFrame=recordFrame', script)
        self.assertIn('endFrame=duration', script)
        self.assertNotIn('InsertFusionTitleIntoTimeline', script.split('local added, failed = 0, 0')[1])
        self.assertIn('ImportFolderFromFile(DATA.template.absolutePath)', script)
        self.assertIn('SetInput("Font", "Noto Sans JP")', script)
        self.assertIn('SetInput("Style", "Medium")', script)
        self.assertIn('日本語字幕', script)

    def test_template_is_bundled(self):
        import zipfile
        template = Path(RTP.__file__).with_name(RTP.TEMPLATE_NAME)
        with zipfile.ZipFile(template) as archive:
            self.assertIn('project.xml', archive.namelist())
        install = RTP.installer_script('test.mov')
        self.assertIn('textplus-template.drb', install)
        self.assertIn('__C2R_TEMPLATE_PATH__', install)

    def test_generated_pack_contains_template_and_v2_script(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            plan = mock.Mock()
            plan.video = Path('test.mov')
            plan.req.name = 'test'
            plan.meta = {'fps': (30, 1), 'w': 1080, 'h': 1920, 'total': 120}
            plan.cues_out = [(27, 93, '日本語字幕')]
            plan.keeps = [(0, 120)]
            paths = pack.pack_paths(plan.video, output, True, textplus=True)
            files = RTP.write_files(paths, plan, output)
            self.assertEqual(paths['textplus_template'].read_bytes(),
                             Path(RTP.__file__).with_name(RTP.TEMPLATE_NAME).read_bytes())
            self.assertIn('trackIndex=2', files['textplus_script'].read_text(encoding='utf-8'))


class TestParsingFixes(unittest.TestCase):
    def test_minutes_seconds_over_59_is_rejected(self):
        with self.assertRaises(C.ToolError):
            C.parse_time("1:75")
        with self.assertRaises(C.ToolError):
            C.parse_time("0:60:00")
        self.assertEqual(C.parse_time("75"), 75)       # 先頭の欄は 60 以上でもよい(秒だけ・分だけ)
        self.assertEqual(C.parse_time("90:00"), 5400)

    def test_fullwidth_digits_and_colon(self):
        self.assertEqual(C.parse_time("１：０２．５"), 62.5)
        self.assertEqual(C.parse_cut_list("１：００〜１：３０\n"), [(60, 90)])

    def test_csv_lines(self):
        t = "start,end\n5,20\n0:05, 0:20\n1,5 3,5\n1,2,見どころ\n7\t9\n"
        self.assertEqual(C.parse_cut_list(t), [(5, 20), (5, 20), (1.5, 3.5), (1, 2), (7, 9)])

    def test_bad_time_error_has_line_number(self):
        with self.assertRaises(C.ToolError) as cm:
            C.parse_cut_list("0:01 0:02\n0:05 abc\n")
        self.assertIn("2行目", str(cm.exception))

    def test_zero_length_after_rounding_warns(self):
        keeps, w = C.cut_list_to_keeps([(1.0, 1.01), (2, 3)], FPS30, 300)
        self.assertEqual(keeps, [(60, 90)])
        self.assertTrue(any("0 になる" in x for x in w))

    def test_fmt_sec_rounds_before_splitting(self):
        self.assertEqual(C.fmt_sec(59.996), "1:00.00")
        self.assertEqual(C.fmt_sec(3599.999), "1:00:00.00")
        self.assertEqual(C.fmt_sec(5.2), "0:05.20")

    def test_edl_clip_name_newline_is_removed(self):
        text = C.build_edl("t", "a\nb.mp4", [(0, 5)], FPS30, True)
        self.assertIn("* FROM CLIP NAME: a b.mp4", text)
        self.assertEqual(len(parse_edl(text)), 1)

    def test_check_timecodes(self):
        C.check_timecodes(FPS30, "01:00:00:00", "10:00:00:29")
        with self.assertRaisesRegex(C.ToolError, "--src-start-tc"):
            C.check_timecodes(FPS30, "01:00:00:00", "00:00:00:30")
        with self.assertRaisesRegex(C.ToolError, "--rec-start"):
            C.check_timecodes((25, 1), "1:00:00", "00:00:00:00")

    def test_src_start_override_drop_frame_is_converted(self):
        tc, desc, warns = C.resolve_src_start(Path("x.mp4"), "01:00:00;00")
        self.assertEqual((tc, desc, len(warns)), ("01:00:00:00", "指定", 1))
        self.assertEqual(C.resolve_src_start(Path("x.mp4"), None, {"start_tc": None})[0], "00:00:00:00")
        self.assertEqual(C.resolve_src_start(Path("x.mp4"), None, {"start_tc": "02:00:00:00"})[0], "02:00:00:00")


class TestOutputGuard(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_output_exists_lists_files(self):
        a = write(self.dir / "a.edl", "x")
        with self.assertRaises(C.OutputExists) as cm:
            C.validate_output_paths([a, self.dir / "b.srt"])
        self.assertEqual(cm.exception.existing, [a])
        self.assertIsInstance(cm.exception, C.ToolError)   # CLI は従来どおり ToolError として表示する

    def test_same_path_variants(self):
        a = write(self.dir / "a.srt", "x")
        self.assertTrue(S.same_path(a, self.dir / "." / "a.srt"))
        self.assertFalse(S.same_path(a, None))
        with self.assertRaisesRegex(C.ToolError, "入力ファイル"):
            C.validate_output_paths([self.dir / "sub" / ".." / "a.srt"], force=True, protected=(a,))

    def test_atomic_write_leaves_no_temp(self):
        p = self.dir / "x.txt"
        S.write_text_atomic(p, "あ\nい\n", encoding="utf-8-sig", newline="\r\n")
        self.assertEqual(p.read_bytes(), "\ufeffあ\r\nい\r\n".encode("utf-8"))
        self.assertEqual(sorted(x.name for x in self.dir.iterdir()), ["x.txt"])

    def test_auto_cut_package_protects_subtitle_input_even_with_force(self):
        video = write(self.dir / "v.mp4", "fake")
        out = self.dir / "pack"
        out.mkdir()
        sub = write(out / "v_cut.srt", "1\n00:00:01,000 --> 00:00:02,000\nx\n")
        meta = {"fps": FPS30, "total": 300, "w": 640, "h": 360, "audio": None}
        plan = AC.build_plan([{"id": "a", "label": "", "start_seconds": 1, "end_seconds": 2}], meta, 0)
        with self.assertRaisesRegex(C.ToolError, "入力ファイル"):
            AC.write_package(video, out, meta, plan, [(0, 30, "x")], "00:00:00:00", force=True, protected=(sub,))
        self.assertIn("x", sub.read_text(encoding="utf-8"))


class TestFcpxml(unittest.TestCase):
    meta = {"fps": FPS30, "total": 300, "w": 640, "h": 360, "audio": None}

    def _root(self, xml):
        return ET.fromstring(xml.split("\n", 2)[2])

    def test_title_offsets_are_in_parent_clip_time(self):
        # 2つ目のクリップは元動画の 5秒(150f)から。字幕はカット後の 2.5秒(75f) = 2つ目のクリップの 0.5秒後
        xml = AC.build_cut_fcpxml(Path("/tmp/src.mp4"), self.meta, [(0, 60), (150, 240)], [(75, 105, "B")])
        root = self._root(xml)
        clips = root.findall(".//spine/asset-clip")
        self.assertEqual(clips[1].get("start"), "5s")
        title = clips[1].find("title")
        self.assertEqual(title.get("offset"), "11/2s")   # 150 + 15 フレーム = 5.5秒(親の start 基準)
        self.assertIsNone(clips[0].find("title"))

    def test_text_style_ids_are_unique(self):
        xml = AC.build_cut_fcpxml(Path("/tmp/src.mp4"), self.meta, [(0, 60), (150, 240)],
                                  [(0, 30, "a"), (60, 90, "b"), (100, 120, "c")])
        ids = [e.get("id") for e in self._root(xml).iter("text-style-def")]
        self.assertEqual(len(ids), 3)
        self.assertEqual(len(set(ids)), 3)

    def test_start_timecode_is_applied(self):
        t0 = 108000   # 01:00:00:00 @30
        xml = AC.build_cut_fcpxml(Path("/tmp/src.mp4"), self.meta, [(30, 60)], [(0, 10, "a")], t0)
        root = self._root(xml)
        self.assertEqual(root.find(".//asset").get("start"), "3600s")
        clip = root.find(".//spine/asset-clip")
        self.assertEqual(clip.get("start"), "3601s")
        self.assertEqual(clip.find("title").get("offset"), "3601s")
        xml2, _ = S.build_fcpxml(Path("/tmp/src.mp4"), self.meta, [(30, 60, "x")], "n", "Yu Gothic", 40, True, t0)
        r2 = self._root(xml2)
        self.assertEqual(r2.find(".//asset").get("start"), "3600s")
        self.assertEqual(r2.find(".//spine/asset-clip").get("start"), "3600s")
        self.assertEqual(r2.find(".//title").get("offset"), "3601s")

    def test_start_tc_frames(self):
        self.assertEqual(S.start_tc_frames(None, FPS30), (0, []))
        self.assertEqual(S.start_tc_frames("01:00:00;00", (30000, 1001))[0], 108000)
        self.assertEqual(len(S.start_tc_frames("01:00:00;00", (30000, 1001))[1]), 1)


class TestCutPlanDocs(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def _plan(self, extra=None, segs=None):
        d = {"schema": "youtube-tools-cut-plan/v1",
             "segments": segs or [{"id": "a", "start": 1.0, "end": 2.0}, {"id": "b", "start": 3.0, "end": 4.0, "status": "rejected"}]}
        d.update(extra or {})
        return write(self.dir / "plan.json", json.dumps(d))

    def test_default_handles_by_source(self):
        self.assertEqual(AC.default_handles(AC.read_cut_plan(self._plan())), 10.0)
        self.assertEqual(AC.default_handles(AC.read_cut_plan(self._plan({"tool": {"name": "clip-studio"}}))), 10.0)
        self.assertEqual(AC.default_handles(AC.read_cut_plan(self._plan({"tool": {"name": "transcribe-tool"}}))), 0.0)
        segs = [{"id": "x", "start": 1.0, "end": 2.0, "lines": ["s1", "s2"]}]
        self.assertEqual(AC.default_handles(AC.read_cut_plan(self._plan(segs=segs))), 0.0)
        self.assertEqual(AC.default_handles(AC.read_cut_plan(self._plan({"segmentsIncludeHandles": True}))), 0.0)

    def test_unsupported_version_and_bom(self):
        p = write(self.dir / "v2.json", json.dumps({"schema": "youtube-tools-cut-plan/v2", "segments": []}))
        with self.assertRaisesRegex(C.ToolError, "未対応の版"):
            AC.read_cut_plan(p)
        p = self.dir / "bom.json"
        p.write_bytes(b"\xef\xbb\xbf" + json.dumps({"schema": "youtube-tools-cut-plan/v1", "segments": [{"start": 0, "end": 1}]}).encode())
        self.assertEqual(len(AC.read_selection(p)), 1)
        p = write(self.dir / "nan.json", '{"schema":"youtube-tools-cut-plan/v1","segments":[{"start":NaN,"end":1}]}')
        with self.assertRaises(C.ToolError):
            AC.read_cut_plan(p)

    def test_old_detailed_doc_is_readable(self):
        p = write(self.dir / "cut-plan.json", json.dumps({"schema": "youtube-tools-cut-plan/v1", "frame_rate": "30/1",
                                                         "keep_frames": [[30, 60], [90, 150]]}))
        doc = AC.read_cut_plan(p)
        self.assertEqual([(s["start_seconds"], s["end_seconds"]) for s in doc["segments"]], [(1, 2), (3, 5)])
        self.assertEqual(AC.default_handles(doc), 0.0)

    def test_package_plan_round_trips(self):
        """書いた cut-plan.json を読み直すと、同じ残す区間になる(以前は segments が無く読み直せなかった)"""
        video = write(self.dir / "v.mp4", "fake")
        meta = {"fps": (30000, 1001), "total": 900, "w": 640, "h": 360, "audio": (2, 48000)}
        plan = AC.build_plan([{"id": "a", "label": "", "start_seconds": 3.3, "end_seconds": 7.7},
                              {"id": "b", "label": "", "start_seconds": 20, "end_seconds": 25}], meta, 1.5)
        AC.write_package(video, self.dir / "out", meta, plan, None, "00:00:00:00")
        saved = json.loads((self.dir / "out" / "cut-plan.json").read_text(encoding="utf-8"))
        for k in ("schema", "tool", "createdAt", "media", "segments"):
            self.assertIn(k, saved)
        self.assertEqual(saved["media"]["name"], "v.mp4")
        doc = AC.read_cut_plan(self.dir / "out" / "cut-plan.json")
        again = AC.build_plan(doc["segments"], meta, AC.default_handles(doc))
        self.assertEqual(again["keep_frames"], plan["keep_frames"])


class TestTranscript(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_read_and_rules(self):
        rows = [(3.0, 4.0, "c", False), (0.5, 1.5, "a", False), (1.5, 2.0, "b", False),
                (2.2, 2.8, "えー", True), (5.0, 4.0, "bad", False), (6.0, 7.0, "", False), (3.5, 5.0, "重なるカット", True)]
        p = write(self.dir / "t.transcript.json", json.dumps(transcript_doc(rows), ensure_ascii=False))
        tr = C.read_transcript(p)
        self.assertEqual(tr["bad"], 1)
        self.assertEqual([r["text"] for r in tr["rows"]][:3], ["a", "b", "えー"])
        self.assertEqual(C.transcript_kept_spans(tr["rows"]), [(0.5, 2.0), (3.0, 4.0)])   # 接する行はまとめ、空の行は残さない
        self.assertEqual(C.transcript_cut_spans(tr["rows"]), [(2.2, 2.8), (3.5, 5.0)])
        self.assertEqual([c[2] for c in C.transcript_cues(tr["rows"])], ["a", "b", "c"])

    def test_schema_errors(self):
        p = write(self.dir / "x.json", json.dumps({"schema": "youtube-tools-transcript/v9", "segments": []}))
        with self.assertRaisesRegex(C.ToolError, "未対応の版"):
            C.read_transcript(p)
        p = write(self.dir / "y.json", json.dumps({"schema": "youtube-tools-cut-plan/v1", "segments": []}))
        with self.assertRaisesRegex(C.ToolError, "ではありません"):
            C.read_transcript(p)
        p = write(self.dir / "z.json", "{broken")
        with self.assertRaisesRegex(C.ToolError, "JSON"):
            C.read_transcript(p)

    def test_resolve_media_path_fallback_to_same_folder(self):
        v = write(self.dir / "clip.mp4", "fake")
        j = self.dir / "clip.transcript.json"
        self.assertEqual(C.resolve_media_path({"path": str(v)}, j), str(v))
        self.assertEqual(C.resolve_media_path({"path": r"C:\gone\clip.mp4"}, j), str(v))   # Windows のパスでも名前だけ使う
        self.assertEqual(C.resolve_media_path({"path": "/nope/x.mp4", "name": "../clip.mp4"}, j), str(v))
        self.assertIsNone(C.resolve_media_path({"path": r"\\server\share\clip2.mp4"}, j))
        self.assertIsNone(C.resolve_media_path(None, j))


@unittest.skipUnless(HAVE_FFMPEG, "ffmpeg が無いためスキップ")
class TestPackWithFfmpeg(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmpc = tempfile.TemporaryDirectory()
        cls.gaps = Path(cls.tmpc.name) / "gaps.mp4"
        make_video(cls.gaps, 10, audio="gaps")   # 音 0-2 / 無音 2-4 / 音 4-6 / 無音 6-8 / 音 8-10

    @classmethod
    def tearDownClass(cls):
        cls.tmpc.cleanup()

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.video = self.dir / "clip.mp4"
        self.video.write_bytes(self.gaps.read_bytes())

    def tearDown(self):
        self.tmp.cleanup()

    def _tr(self, rows, name="clip.transcript.json"):
        return write(self.dir / name, json.dumps(transcript_doc(rows, {"path": str(self.video), "name": "clip.mp4"}),
                                                 ensure_ascii=False))

    def test_transcript_cut_rows_are_removed_and_subtitles_come_from_kept_rows(self):
        tr = self._tr([(0.5, 1.5, "こんにちは", False), (4.0, 5.0, "カットして", True), (8.5, 9.5, "またね", False)])
        plan = pack.plan_cut(pack.Request(video=self.video, transcript=tr))
        self.assertEqual(plan.keeps, [(0, 120), (150, 300)])
        self.assertEqual(plan.sub_source, "transcript")
        self.assertEqual([c[2] for c in plan.cues_out], ["こんにちは", "またね"])
        self.assertEqual(plan.cues_out[1][:2], (225, 255))   # 8.5 秒 → カット後 7.5 秒
        plan2 = pack.plan_cut(pack.Request(video=self.video, transcript=tr, drop_cut_rows=False))
        self.assertEqual(plan2.keeps, [(0, 300)])

    def test_keep_rows_base_removes_gaps_between_rows(self):
        tr = self._tr([(0.5, 1.5, "a", False), (1.5, 2.0, "b", False), (8.5, 9.5, "c", False)])
        plan = pack.plan_cut(pack.Request(video=self.video, transcript=tr, base="rows"))
        self.assertEqual(plan.keeps, [(15, 60), (255, 285)])
        self.assertEqual(plan.handles, 0.0)
        plan = pack.plan_cut(pack.Request(video=self.video, transcript=tr, base="rows", handles=0.5))
        self.assertEqual(plan.keeps, [(0, 75), (240, 300)])

    def test_transcribe_tool_cut_plan_defaults_to_no_handles(self):
        p = write(self.dir / "clip.cut-plan.json", json.dumps({
            "schema": "youtube-tools-cut-plan/v1", "tool": {"name": "transcribe-tool", "version": "0.10.0"},
            "segments": [{"id": "segment-001", "start": 1.0, "end": 2.0, "status": "adopted", "lines": ["s1"]},
                         {"id": "segment-002", "start": 5.0, "end": 6.0, "status": "adopted", "lines": ["s3"]}]}))
        plan = pack.plan_cut(pack.Request(video=self.video, plan=p, base="plan"))
        self.assertEqual(plan.keeps, [(30, 60), (150, 180)])   # 10秒の余白で全部つながらない
        plan = pack.plan_cut(pack.Request(video=self.video, plan=p, base="plan", handles=10))
        self.assertEqual(plan.keeps, [(0, 300)])

    def test_srt_wins_over_transcript_with_note(self):
        tr = self._tr([(0.5, 1.5, "文字起こし", False)])
        srt = write(self.dir / "s.srt", "1\n00:00:00,500 --> 00:00:01,500\nSRT の字幕\n")
        plan = pack.plan_cut(pack.Request(video=self.video, transcript=tr, sub=srt))
        self.assertEqual(plan.sub_source, "srt")
        self.assertTrue(any("SRT のほう" in w for w in plan.warnings))

    def test_silence_with_cache_and_task_progress(self):
        seen = []
        task = C.Task(lambda f, m: seen.append((f, m)))
        cache = pack.Cache()
        req = pack.Request(video=self.video, silence=True)
        p1 = pack.plan_cut(req, task=task, cache=cache)
        self.assertEqual(len(p1.keeps), 3)
        self.assertTrue(any(isinstance(f, float) for f, _ in seen), seen)   # 進み具合(0〜1)が来る
        self.assertTrue(cache.silence_cached(self.video, p1.meta["fps"], p1.meta["total"], -35.0, 0.6, 0.15))
        with mock.patch.object(C, "detect_silence", side_effect=AssertionError("キャッシュを使うはず")):
            p2 = pack.plan_cut(req, cache=cache)
        self.assertEqual(p2.keeps, p1.keeps)

    def test_invalid_timecode_fails_before_rendering(self):
        cuts = write(self.dir / "cuts.txt", "1 2\n")
        rc = FULL.main([str(self.video), str(cuts), "--render", "--src-start-tc", "00:00:00:45"])
        self.assertEqual(rc, 1)
        self.assertFalse((self.dir / "clip_pack").exists())   # 以前は粗編集の mp4 だけ書き出してから失敗していた

    def test_full_cli_with_transcript_json_and_fcpxml(self):
        tr = self._tr([(0.5, 1.5, "こんにちは", False), (4.0, 5.0, "カット", True), (8.5, 9.5, "またね", False)])
        self.assertEqual(FULL.main([str(self.video), str(tr), "--fcpxml"]), 0)   # .json は順不同で schema から判別
        out = self.dir / "clip_pack"
        names = sorted(p.name for p in out.iterdir())
        self.assertEqual(names, ["clip.edl", "clip_cut.fcpxml", "clip_cut.srt", "cut-plan.json", "友人へ.txt"])
        ev = parse_edl((out / "clip.edl").read_text(encoding="utf-8"))
        self.assertEqual([(e[3], e[4]) for e in ev], [("00:00:00:00", "00:00:04:00"), ("00:00:05:00", "00:00:10:00")])
        readme = (out / "友人へ.txt").read_text(encoding="utf-8-sig")
        self.assertIn("cut-plan.json", readme)
        self.assertIn("clip_cut.fcpxml", readme)
        doc = AC.read_cut_plan(out / "cut-plan.json")   # 読み直せる
        self.assertEqual(len(doc["segments"]), 2)
        bad = write(self.dir / "other.json", '{"schema":"something/v1"}')
        self.assertEqual(FULL.main([str(self.video), str(bad), "-o", str(self.dir / "o")]), 1)

    def test_full_cli_plan_and_list_are_exclusive(self):
        cuts = write(self.dir / "cuts.txt", "1 2\n")
        p = write(self.dir / "p.json", json.dumps({"schema": "youtube-tools-cut-plan/v1", "segments": [{"start": 1, "end": 2}]}))
        self.assertEqual(FULL.main([str(self.video), str(cuts), str(p), "--dry-run"]), 1)
        self.assertEqual(FULL.main([str(self.video), "--keep-rows", "--dry-run"]), 1)   # 文字起こしが無い
        self.assertEqual(FULL.main([str(self.video), str(p), "--dry-run"]), 0)

    def test_build_pack_stale_files_warning_and_force(self):
        plan = pack.plan_cut(pack.Request(video=self.video, silence=True))
        r1 = pack.build_pack(plan, render=True)
        self.assertEqual([k for k, _ in r1["files"]], ["edl", "readme", "plan", "roughcut"])
        with self.assertRaises(C.OutputExists) as cm:
            pack.build_pack(plan)
        self.assertEqual(sorted(p.name for p in cm.exception.existing), ["clip.edl", "cut-plan.json", "友人へ.txt"])
        r2 = pack.build_pack(plan, force=True)
        self.assertTrue(any("clip_roughcut.mp4" in w for w in r2["warnings"]))
        self.assertIn("DaVinci Resolve", r2["readme"])
        leftovers = [p.name for p in r2["out_dir"].iterdir() if p.name.startswith(".")]
        self.assertEqual(leftovers, [])

    def test_cancel_during_copy_leaves_nothing(self):
        plan = pack.plan_cut(pack.Request(video=self.video))
        task = C.Task()
        task._on = lambda f, m: task.cancel() if isinstance(f, float) else None
        out = self.dir / "o"
        with self.assertRaises(C.Cancelled):
            pack.build_pack(plan, out, copy_video=True, task=task)
        self.assertEqual(list(out.iterdir()), [])   # 途中の一時ファイルも、半端なパックも残さない

    def test_cancel_during_render_kills_ffmpeg_and_cleans_up(self):
        long_v = self.dir / "long.mp4"
        make_video(long_v, 20, size="960x540")
        task = C.Task()
        task._on = lambda f, m: task.cancel() if isinstance(f, float) and f > 0 else None
        out = self.dir / "r"
        out.mkdir()
        with self.assertRaises(C.Cancelled):
            C.render_rough_cut(long_v, [(0, 1200)], FPS30, True, out / "x.mp4", 18, task)
        self.assertEqual(list(out.iterdir()), [])

    def test_render_failure_leaves_no_partial_file(self):
        noa = self.dir / "noaudio.mp4"
        make_video(noa, 2, audio=None)
        out = self.dir / "f"
        out.mkdir()
        with self.assertRaises(C.ToolError):
            C.render_rough_cut(noa, [(0, 30)], FPS30, True, out / "x.mp4")   # 音声が無いのに音声ありで書き出す → ffmpeg が失敗
        self.assertEqual(list(out.iterdir()), [])

    def test_relative_path_starting_with_dash(self):
        """「-」で始まるファイル名を ffprobe / ffmpeg にオプションと取り違えさせない"""
        odd = self.dir / "-i.mp4"
        odd.write_bytes(self.video.read_bytes())
        cwd = os.getcwd()
        os.chdir(self.dir)
        try:
            meta = S.probe(Path("-i.mp4"))
            self.assertEqual(meta["total"], 300)
            self.assertEqual(len(C.detect_silence(Path("-i.mp4"), meta["fps"], meta["total"])), 2)
        finally:
            os.chdir(cwd)

    def test_srt2resolve_uses_embedded_start_timecode(self):
        v = self.dir / "tc.mov"
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "testsrc=size=320x180:rate=30:duration=3",
                        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-timecode", "01:00:00:00", str(v)], check=True)
        srt = write(self.dir / "tc.srt", "1\n00:00:01,000 --> 00:00:02,000\nx\n")
        self.assertEqual(S.main([str(v), str(srt)]), 0)
        root = ET.fromstring((self.dir / "tc_resolve" / "tc.fcpxml").read_text(encoding="utf-8").split("\n", 2)[2])
        self.assertEqual(root.find(".//asset").get("start"), "3600s")
        self.assertEqual(root.find(".//title").get("offset"), "3601s")
        self.assertEqual(S.main([str(v), str(srt), "--src-start-tc", "00:00:00:00", "-o", str(self.dir / "z")]), 0)
        root = ET.fromstring((self.dir / "z" / "tc.fcpxml").read_text(encoding="utf-8").split("\n", 2)[2])
        self.assertEqual(root.find(".//asset").get("start"), "0s")

    def test_summary_shape(self):
        tr = self._tr([(0.5, 1.5, "a", False), (4.0, 5.0, "cut", True)])
        s = pack.summary(pack.plan_cut(pack.Request(video=self.video, transcript=tr, silence=True)))
        self.assertEqual(s["fps"], [30, 1])
        self.assertEqual(s["total"], 300)
        self.assertIn("silence", s["drops"])
        self.assertIn("cutRows", s["drops"])
        self.assertEqual(s["subtitles"]["source"], "transcript")
        self.assertEqual(len(s["transcriptRows"]), 2)
        self.assertAlmostEqual(s["keptSec"] + s["removedSec"], 10.0, places=3)
        json.dumps(s)   # そのまま JSON にできる


if __name__ == "__main__":
    unittest.main(verbosity=2)
