#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""パックのテストの道具(見本の動画・EDL の読み方・採用区間からのパック)と、通しでは起こせない物の単体
(何時間もの切り抜きの時間切れ・書きかけの付け替えの失敗・無料版の Resolve で読めない形式)。
時刻・カットリスト・EDL・字幕の付け直しなどの正しく動く道は test_pack の TestPackRun(本物の ffmpeg の通し)。 python test_cut2resolve.py"""
import re
import shutil
import subprocess
import sys
import unittest
from pathlib import Path

TESTS = Path(__file__).resolve().parent
sys.path.insert(0, str(TESTS.parents[2]))   # src(パックの部品は pipeline.pack)
from pipeline.pack import cut2resolve_core as C  # noqa: E402
from pipeline.pack import pack  # noqa: E402
from pipeline.pack import srt2resolve as S  # noqa: E402
from ytt.tests import testkit  # noqa: E402

HAVE_FFMPEG = bool(shutil.which("ffmpeg") and shutil.which("ffprobe"))
FPS30 = (30, 1)


def selection_pack(video, selection, out_dir, sub=None, handles=None, copy_video=False, force=False):
    """採用区間 JSON(youtube-tools-cut-plan/v1)+ 動画 + 任意の字幕から、パックを作る(base "plan"・EDL・カット後の SRT・
    cut-plan.json・友人へ.txt)。最短の長さで区間を捨てない・余白つき素材は入れない。-> (計画, 結果)"""
    req = pack.Request(video=Path(video), sub=Path(sub) if sub else None, plan=Path(selection), base="plan", handles=handles,
                       min_len=0.0, edit_media=False)
    plan = pack.plan_cut(req)
    return plan, pack.build_pack(plan, Path(out_dir), copy_video=copy_video, force=force)


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


class TestLongClipTimeouts(unittest.TestCase):
    """友人の依頼の区間は長さの上限なし(C-2-7・C-5-5)= 3 時間の切り抜きでも ffmpeg を決まった秒数で切らない(3 時間の動画は通しで作れない)"""

    def test_span_timeout(self):
        self.assertEqual(C.span_timeout(3600, 600, 1.0), 3600)          # 短い切り抜きは決まった値
        self.assertEqual(C.span_timeout(7200, 3 * 3600, 3.0), 32400)     # 長いものは長さに合わせて延ばす
        for unknown in (None, 0, -5, float("nan"), "x"):
            self.assertEqual(C.span_timeout(7200, unknown, 3.0), 7200, unknown)

    def test_preview_timeout_follows_length(self):
        from unittest import mock
        from pipeline.pack import preview as PV
        d = Path(testkit.tempdir(self))
        video = d / "clip.mp4"
        video.write_bytes(b"\0")
        got = []
        with mock.patch.object(PV.normalize, "probe", return_value={"has_audio": True, "duration": 3 * 3600.0}), \
                mock.patch.object(PV, "_run_ffmpeg", side_effect=lambda args, timeout, check: (got.append(timeout), (1, "x"))[1]):
            self.assertFalse(PV.make_preview(str(video), str(d / "p.mp4"), ffmpeg="ffmpeg"))
        self.assertEqual(got, [3 * 3600 * PV.PREVIEW_PER_SEC])
        with mock.patch.object(PV.normalize, "probe", return_value={"has_audio": False, "duration": 60.0}), \
                mock.patch.object(PV, "_run_ffmpeg", side_effect=lambda args, timeout, check: (got.append(timeout), (1, "x"))[1]):
            PV.make_preview(str(video), str(d / "p.mp4"), ffmpeg="ffmpeg")
        self.assertEqual(got[-1], PV.PREVIEW_TIMEOUT)


class TestParseCutList(unittest.TestCase):
    def test_negative_time_is_refused(self):
        """先頭の「-」は区切りではなく負の時刻の打ち間違い(「-1 5」を 1〜5 秒と黙って読まない)。範囲の区切りの「-」は今まで通り"""
        self.assertEqual(C.parse_cut_list("1-5\n2 - 6\n3 7"), [(1.0, 5.0), (2.0, 6.0), (3.0, 7.0)])
        for bad in ("-1 5", "－1 5", "1 5\n-2 8"):
            with self.assertRaises(C.ToolError):
                C.parse_cut_list(bad)


class TestStagedWrite(unittest.TestCase):
    """一時ファイルに書いて付け替える処理(srt2resolve.staged)。途中の失敗を差し込む(付け替えのやり直しは ytt/fsio.py の replace_retry で、そのテストは test_ytt_core)"""

    def setUp(self):
        self.dir = Path(testkit.tempdir(self))

    def test_staged_replaces_on_success_and_cleans_on_failure(self):
        dst = self.dir / "out.bin"
        dst.write_bytes(b"old")
        with S.staged(dst) as tmp:
            self.assertEqual(Path(tmp).parent, self.dir)
            self.assertTrue(Path(tmp).name.startswith(".tmp-"))
            Path(tmp).write_bytes(b"new")
            self.assertEqual(dst.read_bytes(), b"old")   # 書き終えるまで元は壊さない
        self.assertEqual(dst.read_bytes(), b"new")
        self.assertEqual([p.name for p in self.dir.iterdir()], ["out.bin"])   # 一時ファイルは残らない
        with self.assertRaises(RuntimeError):
            with S.staged(dst, ".mp4") as tmp:
                Path(tmp).write_bytes(b"half")
                raise RuntimeError("途中で失敗")
        self.assertEqual(dst.read_bytes(), b"new")   # 失敗したら元のまま・書きかけを残さない
        self.assertEqual([p.name for p in self.dir.iterdir()], ["out.bin"])
        S.write_text_atomic(self.dir / "w.bin", "x")
        self.assertEqual(sorted(p.name for p in self.dir.iterdir()), ["out.bin", "w.bin"])


class TestCodecWarnings(unittest.TestCase):
    """無料版の Resolve で読めないことがある形式の注意(srt2resolve.codec_warnings。試算・パックの warnings に出る)。
    av1・hevc の見本を作れる符号器は PC ごとに違うので、通しの見本には入れない"""

    def test_codec_and_bit_depth(self):
        for codec in ("vp9", "av1", "hevc", "h265"):
            w = S.codec_warnings(codec, "yuv420p")
            self.assertEqual(len(w), 1, codec)
            self.assertIn("無料版", w[0])
        self.assertIn("vp9", S.codec_warnings("vp9", "yuv420p")[0])
        self.assertIn("H.265", S.codec_warnings("hevc", "yuv420p")[0])
        for pf in ("yuv420p10le", "yuv422p10be", "p010le"):
            w = S.codec_warnings("mpeg4", pf)
            self.assertEqual(len(w), 1, pf)
            self.assertIn("10bit", w[0])
        self.assertIn("yuv420p10le", S.codec_warnings("h264", "yuv420p10le")[0])   # H.264 は形式を出す
        for codec in ("h264", "hevc", "av1"):
            self.assertEqual(len(S.codec_warnings(codec, "yuv420p10le")), 1, codec)   # 二重には出ない
        for codec, pf in (("h264", "yuv420p"), ("mpeg4", "yuv420p"), ("h264", ""), ("prores", "yuv422p10le"), ("dnxhd", "yuv422p10le"),
                          ("cfhd", "yuv422p10le")):
            self.assertEqual(S.codec_warnings(codec, pf), [], (codec, pf))


if __name__ == "__main__":
    unittest.main(verbosity=2)
