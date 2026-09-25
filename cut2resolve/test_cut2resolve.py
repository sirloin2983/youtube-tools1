#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""cut2resolve のテスト。 python test_cut2resolve.py  (ffmpeg が無ければ通しテストは自動スキップ)"""
import json
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
from fractions import Fraction
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import cut2resolve as FULL  # noqa: E402
import cut2resolve_core as C  # noqa: E402
import auto_cut as AC  # noqa: E402
import srt2resolve as S  # noqa: E402

HAVE_FFMPEG = bool(shutil.which("ffmpeg") and shutil.which("ffprobe"))
FPS30 = (30, 1)


def make_video(path, dur=10, fps="30", size="640x360", audio="tone"):
    """audio: 'tone'=ずっと音 / 'gaps'=音(2秒)・無音(2秒)・音(2秒)…を dur 秒ぶん / None=音声なし"""
    cmd = ["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", f"testsrc=size={size}:rate={fps}:duration={dur}"]
    if audio == "tone":
        cmd += ["-f", "lavfi", "-i", f"sine=frequency=440:duration={dur}"]
    elif audio == "gaps":
        # 0-2s 音 / 2-4s 無音 / 4-6s 音 / 6-8s 無音 / 8-10s 音
        expr = "if(lt(mod(t\\,4)\\,2)\\,0.5*sin(2*PI*440*t)\\,0)"
        cmd += ["-f", "lavfi", "-i", f"aevalsrc={expr}:s=44100:d={dur}"]
    cmd += ["-pix_fmt", "yuv420p", "-c:v", "libx264"]
    if audio:
        cmd += ["-c:a", "aac", "-shortest"]
    subprocess.run(cmd + [str(path)], check=True)


def parse_edl(text):
    """独立した簡易パーサ: 仕様の書式どおりか検証しつつ [(番号, リール, トラック, src_in, src_out, rec_in, rec_out, comments)] を返す"""
    events, cur = [], None
    for line in re.split(r"\r?\n", text):  # ファイルを read_text すると改行が \n に変換されるため両対応
        m = re.fullmatch(r"(\d{3,})  (\S{1,8}) +(V|AA/V) +C {8}"
                         r"(\d\d:\d\d:\d\d:\d\d) (\d\d:\d\d:\d\d:\d\d) (\d\d:\d\d:\d\d:\d\d) (\d\d:\d\d:\d\d:\d\d)", line)
        if m:
            cur = list(m.groups()) + [[]]
            events.append(cur)
        elif line.startswith("* ") and cur:
            cur[-1].append(line[2:])
    return events


def tc2f(tc, nominal):
    h, m, s, f = (int(x) for x in tc.split(":"))
    return ((h * 60 + m) * 60 + s) * nominal + f


class TestTimeAndLists(unittest.TestCase):
    def test_parse_time(self):
        self.assertEqual(C.parse_time("12.5"), 12.5)
        self.assertEqual(C.parse_time("1:02.5"), 62.5)
        self.assertEqual(C.parse_time("0:01:02,5"), 62.5)
        self.assertEqual(C.parse_time("00:00:01"), 1)
        for bad in ("", "abc", "-1", "1:2:3:4", "inf", "nan", "1..2"):
            with self.assertRaises(C.ToolError, msg=bad):
                C.parse_time(bad)

    def test_parse_cut_list(self):
        t = "\ufeff# 例\n0:05 0:20.5\n1:02 - 1:30   # コメント\n\n2:00〜2:10\n3:00 → 3:05\n4:00 --> 4:02\n"
        self.assertEqual(C.parse_cut_list(t), [(5, 20.5), (62, 90), (120, 130), (180, 185), (240, 242)])

    def test_parse_cut_list_errors_have_line_numbers(self):
        with self.assertRaises(C.ToolError) as cm:
            C.parse_cut_list("0:05 0:10\n0:20\n")
        self.assertIn("2行目", str(cm.exception))
        with self.assertRaises(C.ToolError) as cm:
            C.parse_cut_list("0:10 0:05\n")
        self.assertIn("1行目", str(cm.exception))

    def test_parse_index_list(self):
        self.assertEqual(C.parse_index_list("3,5-7"), {3, 5, 6, 7})
        self.assertEqual(C.parse_index_list(" 2 4 "), {2, 4})
        for bad in ("a", "0", "5-3"):
            with self.assertRaises(C.ToolError, msg=bad):
                C.parse_index_list(bad)

    def test_timecode(self):
        self.assertEqual(C.frames_to_tc(0, 30), "00:00:00:00")
        self.assertEqual(C.frames_to_tc(100, 24), "00:00:04:04")
        self.assertEqual(C.frames_to_tc(3600 * 30, 30), "01:00:00:00")
        self.assertEqual(C.tc_to_frames("01:00:00:00", 30), 108000)
        for f in (0, 1, 29, 30, 1799, 1800, 107999, 108000, 123457):
            self.assertEqual(C.tc_to_frames(C.frames_to_tc(f, 30), 30), f)
        self.assertEqual(C.nominal_rate((30000, 1001)), 30)
        self.assertEqual(C.nominal_rate((24000, 1001)), 24)
        with self.assertRaises(C.ToolError):
            C.tc_to_frames("01:00:00;00", 30)  # ドロップフレームは未対応と明示
        with self.assertRaises(C.ToolError):
            C.tc_to_frames("00:00:00:30", 30)  # フレーム部が範囲外


class TestRanges(unittest.TestCase):
    def test_normalize(self):
        self.assertEqual(C.normalize([(10, 20), (15, 30), (30, 40), (50, 50), (-5, 3), (90, 200)], 100),
                         [(0, 3), (10, 40), (90, 100)])

    def test_subtract(self):
        self.assertEqual(C.subtract([(0, 100)], [(10, 20), (50, 60)]), [(0, 10), (20, 50), (60, 100)])
        self.assertEqual(C.subtract([(0, 100)], [(0, 100)]), [])
        self.assertEqual(C.subtract([(0, 100)], [(-10, 5), (95, 200)]), [(5, 95)])
        self.assertEqual(C.subtract([(10, 20), (30, 40)], [(15, 35)]), [(10, 15), (35, 40)])
        self.assertEqual(C.subtract([(0, 10)], []), [(0, 10)])

    def test_merge_and_short(self):
        self.assertEqual(C.merge_close([(0, 10), (12, 20), (40, 50)], 2), [(0, 20), (40, 50)])
        self.assertEqual(C.merge_close([(0, 10), (10, 20)], 0), [(0, 20)])
        self.assertEqual(C.drop_short([(0, 3), (5, 20)], 6), [(5, 20)])

    def test_cut_list_to_keeps_clips_and_warns(self):
        keeps, w = C.cut_list_to_keeps([(1, 2), (9, 20), (50, 60)], FPS30, 300)  # 10秒の動画
        self.assertEqual(keeps, [(30, 60), (270, 300)])
        self.assertTrue(w)


class TestEdl(unittest.TestCase):
    def test_structure_and_arithmetic(self):
        keeps = [(30, 90), (150, 155), (300, 600)]
        text = C.build_edl("my clip", "a.mp4", keeps, FPS30, True, rec_start="01:00:00:00")
        self.assertTrue(text.startswith("TITLE: my clip\r\nFCM: NON-DROP FRAME\r\n"))
        ev = parse_edl(text)
        self.assertEqual(len(ev), 3)
        rec = 108000
        for (num, reel, track, si, so, ri, ro, com), (s, e) in zip(ev, keeps):
            self.assertEqual(track, "AA/V")
            self.assertEqual(tc2f(si, 30), s)
            self.assertEqual(tc2f(so, 30), e)
            self.assertEqual(tc2f(ri, 30), rec)  # 記録側は隙間なく連続
            self.assertEqual(tc2f(ro, 30) - tc2f(ri, 30), e - s)  # 長さが一致
            self.assertIn("FROM CLIP NAME: a.mp4", com)
            rec += e - s
        self.assertEqual([e[0] for e in ev], ["001", "002", "003"])

    def test_video_only_and_reel_and_src_start(self):
        text = C.build_edl("t", "b.mov", [(0, 30)], FPS30, False, reel="日本語 x-1", src_start="01:00:00:00")
        ev = parse_edl(text)
        self.assertEqual(ev[0][2], "V")
        self.assertEqual(ev[0][1], "X1")  # 英数字だけを残して大文字に
        self.assertEqual(ev[0][3], "01:00:00:00")
        self.assertEqual(C.build_edl("t", "b.mov", [(0, 30)], FPS30, False, reel="日本語").count("AX"), 1)

    def test_2997_counts_as_30(self):
        text = C.build_edl("t", "c.mp4", [(0, 1800)], (30000, 1001), True)
        ev = parse_edl(text)
        self.assertEqual(ev[0][4], "00:01:00:00")  # 1800フレーム = 呼び名どおり 1分0フレーム

    def test_title_newline_removed(self):
        self.assertEqual(C.build_edl("a\nb", "c.mp4", [(0, 5)], FPS30, True).split("\r\n")[0], "TITLE: a b")


class TestRemap(unittest.TestCase):
    keeps = [(30, 90), (150, 240)]  # 元の 1-3秒 / 5-8秒。カット後は 0-2秒 / 2-5秒

    def test_inside_first_and_second(self):
        out, gone = C.remap_cues([(1000, 2000, "A"), (5500, 7000, "B")], self.keeps, FPS30)
        self.assertEqual(out, [(0, 30, "A"), (60 + 15, 60 + 60, "B")])
        self.assertEqual(gone, 0)

    def test_fully_cut_is_counted(self):
        out, gone = C.remap_cues([(3500, 4500, "cut")], self.keeps, FPS30)
        self.assertEqual((out, gone), ([], 1))

    def test_cue_across_cut_is_split(self):
        out, gone = C.remap_cues([(2000, 6000, "X")], self.keeps, FPS30)  # 2-6秒: 1つ目の後半 + 2つ目の前半
        self.assertEqual(out, [(30, 60, "X"), (60, 60 + 30, "X")])
        self.assertEqual(gone, 0)

    def test_tiny_clipped_piece_is_dropped_but_tiny_whole_cue_kept(self):
        # 2.95-3.4 秒の字幕 → 1つ目の区間に入るのは 2.95-3.0(1.5フレーム)だけ = 断片が短いので捨てる
        out, gone = C.remap_cues([(2950, 3400, "T")], self.keeps, FPS30)
        self.assertEqual((out, gone), ([], 1))
        out, gone = C.remap_cues([(1000, 1100, "short")], self.keeps, FPS30)  # 切られていない短い字幕は残す
        self.assertEqual(len(out), 1)

    def test_sorted_output_and_srt_roundtrip(self):
        out, _ = C.remap_cues([(5500, 6000, "later"), (1000, 1500, "first")], self.keeps, FPS30)
        self.assertEqual([c[2] for c in out], ["first", "later"])
        srt = S.build_srt(out, FPS30)
        self.assertEqual([c[2] for c in S.parse_subs(srt)], ["first", "later"])


class TestSrcStart(unittest.TestCase):
    def test_override_wins_and_no_probe(self):
        self.assertEqual(C.resolve_src_start(Path("nope.mp4"), "01:02:03:04"), ("01:02:03:04", "指定", []))

    def test_drop_frame_notation_is_converted_with_warning(self):
        from unittest import mock
        with mock.patch.object(C, "read_start_tc", return_value="01:00:00;00"):
            tc, desc, warns = C.resolve_src_start(Path("x.mov"))
        self.assertEqual(tc, "01:00:00:00")
        self.assertEqual(len(warns), 1)


class TestInputs(unittest.TestCase):
    def test_classify(self):
        v, s, c = C.classify_inputs([Path("cuts.txt"), Path("a.mp4"), Path("b.srt")], need_cuts=True)
        self.assertEqual((v.name, s.name, c.name), ("a.mp4", "b.srt", "cuts.txt"))

    def test_classify_errors(self):
        with self.assertRaises(C.ToolError):
            C.classify_inputs([Path("a.mp4"), Path("b.srt")], need_cuts=True)  # カットリスト無し
        with self.assertRaises(C.ToolError):
            C.classify_inputs([Path("a.mp4"), Path("b.mp4")], need_cuts=False)  # 動画が2つ
        with self.assertRaises(C.ToolError):
            C.classify_inputs([Path("a.mp4"), Path("b.srt"), Path("c.srt")], need_cuts=False)

    def test_name_warning(self):
        self.assertEqual(C.name_warnings(Path("clip.mp4")), [])
        self.assertEqual(len(C.name_warnings(Path("さくらみこ.mp4"))), 1)


class TestOutputSafety(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_existing_output_requires_force_and_force_preserves_input_guard(self):
        output = self.dir / "result.edl"
        source = self.dir / "source.mp4"
        output.write_text("old", encoding="utf-8")
        source.write_text("source", encoding="utf-8")
        with self.assertRaisesRegex(C.ToolError, "--force"):
            C.validate_output_paths([output])
        C.validate_output_paths([output], force=True)
        with self.assertRaisesRegex(C.ToolError, "入力ファイル"):
            C.validate_output_paths([source], force=True, protected=(source,))
        self.assertEqual(output.read_text(encoding="utf-8"), "old")

    def test_auto_cut_plan_keeps_handles_and_records_recoverable_gaps(self):
        meta = {"fps": FPS30, "total": 1800}
        selected = [{"id": "a", "label": "first", "start_seconds": 20, "end_seconds": 30},
                    {"id": "b", "label": "second", "start_seconds": 35, "end_seconds": 40}]
        plan = AC.build_plan(selected, meta, handle_seconds=10)
        self.assertEqual(plan["keep_frames"], [[300, 1500]])  # handles overlap; union, not duplicate clips
        self.assertEqual(plan["removed_frames"], [[0, 300], [1500, 1800]])
        self.assertEqual(plan["selected_segments"][0]["selected_frames"], [600, 900])
        for invalid in (-1, float("inf"), float("nan")):
            with self.assertRaises(C.ToolError):
                AC.build_plan(selected, meta, invalid)

    def test_auto_cut_selection_json_uses_adopted_segments_only(self):
        p = self.dir / "selection.json"
        p.write_text('{"schema":"youtube-tools-cut-plan/v1","segments":['
                     '{"id":"keep","start":1.0,"end":2.0,"status":"adopted"},'
                     '{"id":"skip","start":3.0,"end":4.0,"status":"rejected"}]}', encoding="utf-8")
        self.assertEqual([x["id"] for x in AC.read_selection(p)], ["keep"])

    def test_auto_cut_fcpxml_contains_trimmed_source_clips_and_titles(self):
        meta = {"fps": FPS30, "total": 120, "w": 640, "h": 360, "audio": None}
        xml = AC.build_cut_fcpxml(self.dir / "source.mp4", meta, [(0, 30), (60, 90)],
                                  [(0, 30, "one"), (30, 60, "two")])
        root = ET.fromstring(xml.split("\n", 2)[2])
        clips = root.findall(".//spine/asset-clip")
        self.assertEqual(len(clips), 2)
        self.assertEqual([x.get("start") for x in clips], ["0s", "2s"])
        self.assertEqual([x.find("title/text/text-style").text for x in clips], ["one", "two"])

    def test_auto_cut_package_contains_recovery_files_and_protects_existing_outputs(self):
        video = self.dir / "source.mp4"
        video.write_bytes(b"fake media for package-only test")
        out = self.dir / "package"
        meta = {"fps": FPS30, "total": 300, "w": 640, "h": 360, "audio": None}
        plan = AC.build_plan([{"id": "m1", "label": "moment", "start_seconds": 3, "end_seconds": 5}],
                             meta, 1)
        files = AC.write_package(video, out, meta, plan, [(30, 90, "字幕")], "00:00:00:00")
        self.assertEqual(len(files), 5)
        saved = json.loads((out / "cut-plan.json").read_text(encoding="utf-8"))
        self.assertEqual(saved["removed_frames"], [[0, 60], [180, 300]])
        with self.assertRaisesRegex(C.ToolError, "--force"):
            AC.write_package(video, out, meta, plan, [(30, 90, "字幕")], "00:00:00:00")
        AC.write_package(video, out, meta, plan, [(30, 90, "字幕")], "00:00:00:00", force=True)


@unittest.skipUnless(HAVE_FFMPEG, "ffmpeg が無いためスキップ")
class TestWithFfmpeg(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def _srt(self, text="1\n00:00:01,000 --> 00:00:02,000\nあ\n\n2\n00:00:05,000 --> 00:00:06,000\nい\n\n"
                        "3\n00:00:09,000 --> 00:00:09,800\nう\n"):
        p = self.dir / "subs.srt"
        p.write_text(text, encoding="utf-8")
        return p

    def test_detect_silence(self):
        v = self.dir / "g.mp4"
        make_video(v, 10, audio="gaps")
        meta = S.probe(v)
        sil = C.detect_silence(v, meta["fps"], meta["total"], -35, 0.6, 0.15)
        # 無音は 2-4s と 6-8s。前後 0.15s を残すので 2.15-3.85 / 6.15-7.85 付近(±3フレーム)
        self.assertEqual(len(sil), 2, sil)
        for (s, e), (es, ee) in zip(sil, [(64, 116), (184, 236)]):
            self.assertLessEqual(abs(s - es), 3)
            self.assertLessEqual(abs(e - ee), 3)

    def test_silence_on_video_without_audio_is_an_error(self):
        v = self.dir / "na.mp4"
        make_video(v, 3, audio=None)
        meta = S.probe(v)
        with self.assertRaises(C.ToolError):
            C.detect_silence(v, meta["fps"], meta["total"])

    def test_render_length_and_audio(self):
        v = self.dir / "r.mp4"
        make_video(v, 10)
        out = self.dir / "cut.mp4"
        keeps = [(30, 90), (150, 240), (270, 300)]  # 2+3+1 = 6秒
        C.render_rough_cut(v, keeps, FPS30, True, out)
        m = S.probe(out)
        self.assertLessEqual(abs(m["total"] - 180), 2)
        self.assertIsNotNone(m["audio"])

    def test_render_video_only(self):
        v = self.dir / "rv.mp4"
        make_video(v, 5, audio=None)
        out = self.dir / "cutv.mp4"
        C.render_rough_cut(v, [(0, 30), (60, 90)], FPS30, False, out)
        self.assertLessEqual(abs(S.probe(out)["total"] - 60), 2)
        self.assertIsNone(S.probe(out)["audio"])

    def test_cutlist_cli_end_to_end(self):
        # 旧シンプル版(cut2resolve_simple.py、2026-09-26 に廃止)の確認を、フル版の同じ使い方(動画・字幕・カットリスト)に移したもの
        v = self.dir / "clip.mp4"
        make_video(v, 10)
        cuts = self.dir / "cuts.txt"
        cuts.write_text("0:00 0:03\n5 8  # 後半\n", encoding="utf-8")
        rc = FULL.main([str(v), str(self._srt()), str(cuts)])
        self.assertEqual(rc, 0)
        out = self.dir / "clip_pack"
        ev = parse_edl((out / "clip.edl").read_text(encoding="utf-8"))
        self.assertEqual([(e[3], e[4]) for e in ev], [("00:00:00:00", "00:00:03:00"), ("00:00:05:00", "00:00:08:00")])
        self.assertEqual([(e[5], e[6]) for e in ev], [("01:00:00:00", "01:00:03:00"), ("01:00:03:00", "01:00:06:00")])
        cues = S.parse_subs((out / "clip_cut.srt").read_text(encoding="utf-8"))
        # あ(1-2s)は残る / い(5-6s)はカット後 3-4s / う(9-9.8s)は消える
        self.assertEqual([(c[0], c[1], c[2]) for c in cues], [(1000, 2000, "あ"), (3000, 4000, "い")])
        self.assertTrue((out / "友人へ.txt").read_text(encoding="utf-8-sig").startswith("DaVinci Resolve"))
        raw = (out / "clip.edl").read_bytes()
        self.assertIn(b"\r\n", raw)  # EDL は CRLF で書く
        self.assertFalse(raw.startswith(b"\xef\xbb\xbf"))  # BOM なし
        original_edl = raw
        args = [str(v), str(self._srt()), str(cuts)]
        self.assertEqual(FULL.main(args), 1)  # 既存出力は既定で保護
        self.assertEqual((out / "clip.edl").read_bytes(), original_edl)
        self.assertEqual(FULL.main(args + ["--force"]), 0)

    def test_cutlist_cli_without_subtitles_and_errors(self):
        v = self.dir / "n.mp4"
        make_video(v, 5)
        cuts = self.dir / "c.txt"
        cuts.write_text("1 2\n", encoding="utf-8")
        self.assertEqual(FULL.main([str(v), str(cuts)]), 0)
        self.assertFalse((self.dir / "n_pack" / "n_cut.srt").exists())
        self.assertIn("字幕は付いていません", (self.dir / "n_pack" / "友人へ.txt").read_text(encoding="utf-8-sig"))
        bad = self.dir / "bad.txt"
        bad.write_text("100 200\n", encoding="utf-8")  # 動画(5秒)の範囲外
        self.assertEqual(FULL.main([str(v), str(bad), "-o", str(self.dir / "bad_out")]), 1)

    def test_full_cli_silence_render_pack(self):
        v = self.dir / "g.mp4"
        make_video(v, 10, audio="gaps")
        rc = FULL.main([str(v), str(self._srt()), "--silence", "--render", "--copy-video"])
        self.assertEqual(rc, 0)
        out = self.dir / "g_pack"
        for name in ("g.edl", "g_cut.srt", "g_roughcut.mp4", "友人へ.txt", "g.mp4"):
            self.assertTrue((out / name).exists(), name)
        ev = parse_edl((out / "g.edl").read_text(encoding="utf-8"))
        self.assertEqual(len(ev), 3)  # 音のある 3 か所
        rec_total = tc2f(ev[-1][6], 30) - tc2f(ev[0][5], 30)
        self.assertLessEqual(abs(S.probe(out / "g_roughcut.mp4")["total"] - rec_total), 3)  # 粗編集の長さ = EDL の長さ
        cues = S.parse_subs((out / "g_cut.srt").read_text(encoding="utf-8"))
        self.assertEqual([c[2] for c in cues], ["あ", "い", "う"])  # 字幕は全て音のある区間に入っている

    def test_full_cli_textplus_pack_60fps_to_30fps_target(self):
        # v0.4.0: 60fps 横の動画を再圧縮せず media/ に入れ、置き先(既定 30fps・1080x1920)を計画に書く。CLI の経路の確認
        v = self.dir / "t60.mp4"
        make_video(v, 10, fps="60")
        rc = FULL.main([str(v), str(self._srt()), "--textplus"])
        self.assertEqual(rc, 0)
        out = self.dir / "t60_pack"
        for name in ("create_resolve_textplus_project.lua", "textplus-import.json", "cut-plan.json", "友人へ.txt"):
            self.assertTrue((out / name).exists(), name)
        self.assertEqual((out / "media" / "t60.mp4").read_bytes(), v.read_bytes())  # 再圧縮しない(中身が同じ)
        plan = json.loads((out / "textplus-import.json").read_text(encoding="utf-8"))
        self.assertEqual(plan["target"], {"fps": 30, "width": 1080, "height": 1920})
        self.assertEqual(plan["mediaFps"], 60)
        self.assertEqual(len(plan["captions"]), 3)
        self.assertNotIn(str(self.dir), json.dumps(plan, ensure_ascii=False))  # 計画にローカルの絶対パスを入れない
        lua = (out / "create_resolve_textplus_project.lua").read_text(encoding="utf-8")
        for bad in ("CreateProject", "SetSetting", "LoadProject"):  # プロジェクトを作らない・設定を変えない
            self.assertNotIn(bad, lua)

    def test_full_cli_textplus_target_options_and_errors(self):
        v = self.dir / "t.mp4"
        make_video(v, 4)
        subs = self._srt("1\n00:00:01,000 --> 00:00:02,000\nあ\n")
        self.assertEqual(FULL.main([str(v), str(subs), "--textplus", "--textplus-fps", "60",
                                    "--textplus-size", "1920x1080"]), 0)
        plan = json.loads((self.dir / "t_pack" / "textplus-import.json").read_text(encoding="utf-8"))
        self.assertEqual(plan["target"], {"fps": 60, "width": 1920, "height": 1080})
        for bad in (["--textplus-fps", "29"], ["--textplus-size", "1080"], ["--textplus-size", "1081x1920"]):
            self.assertEqual(FULL.main([str(v), str(subs), "--textplus", "--force", "-o", str(self.dir / "x")] + bad), 1, bad)
            self.assertFalse((self.dir / "x").exists(), bad)  # 不正な指定ではファイルを作らない

    def test_full_cli_dry_run_and_options(self):
        v = self.dir / "d.mp4"
        make_video(v, 10)
        subs = self._srt()
        self.assertEqual(FULL.main([str(v), str(subs), "--drop-lines", "2", "--dry-run"]), 0)
        self.assertFalse((self.dir / "d_pack").exists())  # dry-run はファイルを作らない
        self.assertEqual(FULL.main([str(v), str(subs), "--drop-lines", "2"]), 0)
        ev = parse_edl((self.dir / "d_pack" / "d.edl").read_text(encoding="utf-8"))
        self.assertEqual(len(ev), 2)  # 5-6秒の字幕の時間帯が抜ける
        self.assertEqual((ev[0][4], ev[1][3]), ("00:00:05:00", "00:00:06:00"))
        drop = self.dir / "drop.txt"
        drop.write_text("0 1\n9 10\n", encoding="utf-8")
        self.assertEqual(FULL.main([str(v), "--drop", str(drop), "-o", str(self.dir / "o2")]), 0)
        ev = parse_edl((self.dir / "o2" / "d.edl").read_text(encoding="utf-8"))
        self.assertEqual((ev[0][3], ev[0][4]), ("00:00:01:00", "00:00:09:00"))
        self.assertEqual(FULL.main([str(v), str(subs), "--drop-lines", "2"]), 1)
        self.assertEqual(FULL.main([str(v), str(subs), "--drop-lines", "2", "--force"]), 0)

    def test_srt2resolve_output_overwrite_requires_force(self):
        v = self.dir / "subvideo.mp4"
        make_video(v, 10)
        subs = self._srt()
        args = [str(v), str(subs)]
        self.assertEqual(S.main(args), 0)
        out = self.dir / "subvideo_resolve"
        xml = (out / "subvideo.fcpxml").read_bytes()
        self.assertEqual(S.main(args), 1)
        self.assertEqual((out / "subvideo.fcpxml").read_bytes(), xml)
        self.assertEqual(S.main(args + ["--force"]), 0)

    def test_embedded_start_timecode_is_used_in_edl(self):
        # Resolve は動画に埋め込まれた開始タイムコードをクリップの Start TC にする。EDL の元動画側の時刻が
        # その範囲に入らないと「timecode extents do not match」で結び付かない(実機で報告のあったエラー)
        v = self.dir / "tc.mov"
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "testsrc=size=640x360:rate=30:duration=6",
                        "-f", "lavfi", "-i", "sine=duration=6", "-c:v", "libx264", "-pix_fmt", "yuv420p",
                        "-c:a", "aac", "-shortest", "-timecode", "10:00:00:00", str(v)], check=True)
        self.assertEqual(C.read_start_tc(v), "10:00:00:00")
        cuts = self.dir / "cuts.txt"
        cuts.write_text("1 2\n3 5\n", encoding="utf-8")
        self.assertEqual(FULL.main([str(v), str(cuts)]), 0)
        ev = parse_edl((self.dir / "tc_pack" / "tc.edl").read_text(encoding="utf-8"))
        self.assertEqual([(e[3], e[4]) for e in ev], [("10:00:01:00", "10:00:02:00"), ("10:00:03:00", "10:00:05:00")])
        self.assertEqual(ev[0][5], "01:00:00:00")  # 記録側は元の開始タイムコードに影響されない
        self.assertIn("10:00:00:00", (self.dir / "tc_pack" / "友人へ.txt").read_text(encoding="utf-8-sig"))
        # 明示指定が優先
        self.assertEqual(FULL.main([str(v), str(cuts), "--src-start-tc", "00:00:00:00", "-o", str(self.dir / "o")]), 0)
        ev = parse_edl((self.dir / "o" / "tc.edl").read_text(encoding="utf-8"))
        self.assertEqual(ev[0][3], "00:00:01:00")

    def test_no_embedded_timecode_defaults_to_zero(self):
        v = self.dir / "plain.mp4"
        make_video(v, 4)
        self.assertIsNone(C.read_start_tc(v))
        self.assertEqual(C.resolve_src_start(v)[0], "00:00:00:00")

    def test_full_cli_errors(self):
        v = self.dir / "e.mp4"
        make_video(v, 4)
        self.assertEqual(FULL.main([str(v), "--drop-lines", "1"]), 1)  # 字幕が無い
        drop = self.dir / "all.txt"
        drop.write_text("0 10\n", encoding="utf-8")
        self.assertEqual(FULL.main([str(v), "--drop", str(drop)]), 1)  # 全部削ると残らない
        cuts = self.dir / "cuts.txt"
        cuts.write_text("0 1\n", encoding="utf-8")
        self.assertEqual(FULL.main([str(v), str(cuts), "--keep", str(cuts)]), 1)  # 二重指定

    def test_frame_exactness_at_2997(self):
        v = self.dir / "f.mp4"
        make_video(v, 6, fps="30000/1001")
        cuts = self.dir / "cuts.txt"
        cuts.write_text("1 2\n3 4\n", encoding="utf-8")
        self.assertEqual(FULL.main([str(v), str(cuts), "--render"]), 0)
        out = self.dir / "f_pack"
        ev = parse_edl((out / "f.edl").read_text(encoding="utf-8"))
        n = sum(tc2f(e[4], 30) - tc2f(e[3], 30) for e in ev)
        self.assertLessEqual(abs(S.probe(out / "f_roughcut.mp4")["total"] - n), 2)
        self.assertEqual(S.probe(out / "f_roughcut.mp4")["fps"], (30000, 1001))


def load_tests(loader, tests, pattern):
    """python -m unittest test_cut2resolve で、追加のテスト(test_pack: 見直しで直した所・pack、test_serve: 画面のサーバー)も走らせる。
    discover(pattern あり)のときは各ファイルが自分で読まれるので足さない(二重に走らないように)"""
    if pattern is None:
        import importlib.util
        for name in ("test_pack", "test_serve"):
            if importlib.util.find_spec(name) is not None:
                tests.addTests(loader.loadTestsFromName(name))
    return tests


if __name__ == "__main__":
    unittest.main(verbosity=2)
