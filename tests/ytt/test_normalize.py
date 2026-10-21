# -*- coding: utf-8 -*-
"""ytt.normalize(素材を 30fps にそろえる。Q1)のテスト。  py -3.12 -m unittest tests/ytt/test_normalize.py -v
ffmpeg・ffprobe で数秒の合成動画を作って確かめる(無い環境ではスキップ)。
正しく動く道と、見本で作れる入力の決まり(60・29.97fps・H.265・10 bit・yuv444p・音声だけ opus・音声なし・30fps のまま)は、
② の段の通し tests/flow/test_normalize30.py の test_job_through。
ここは通しでは起こせない物だけ: 見本で作れない入力の決まり(可変 fps・端数の平均・映像なし・調べられない)・出来上がりから読めない画質の引数・
取り消し・失敗・検証で落ちる・ffprobe が無い・古い ffmpeg・GPU から CPU へ。"""
import os
os.environ.setdefault("YTT_DATA_DIR", "inplace")   # 作業データは読み書きしないが、ほかのテストとそろえる
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

REPO = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "src")
sys.path.insert(0, REPO)
from ytt import normalize, tools  # noqa: E402

FF = tools.find_tool("ffmpeg", "YTT_FFMPEG")
FP = tools.find_tool("ffprobe", "YTT_FFPROBE")


def no_gpu(case):
    """作り直しのテストを GPU の有無で変えない(NVIDIA の PC でも libx264 の道を確かめる)。GPU の道は TestFastPaths で別に"""
    p = mock.patch.dict(os.environ, {normalize.GPU_ENV: "0"})
    p.start()
    case.addCleanup(p.stop)


def make(path, rate, sec, audio=True, size="64x64", pix="yuv420p", vcodec="libx264", src="testsrc"):
    cmd = [FF, "-hide_banner", "-loglevel", "error", "-nostdin", "-y", "-f", "lavfi", "-i", "%s=size=%s:rate=%s:duration=%s" % (src, size, rate, sec)]
    if audio:
        cmd += ["-f", "lavfi", "-i", "sine=frequency=440:duration=%s" % sec, "-c:a", "aac", "-shortest"]
    cmd += ["-c:v", vcodec, "-preset", "veryfast", "-pix_fmt", pix, path]
    subprocess.run(cmd, check=True, stdin=subprocess.DEVNULL)
    return path


def info(**kw):
    """needs_normalize の規則だけを確かめる用の probe の結果"""
    d = {"has_video": True, "has_audio": True, "vcodec": "h264", "bit_depth": 8, "pix_fmt": "yuv420p",
         "r_frame_rate": "30/1", "avg_fps": 30.0, "acodec": "aac"}
    d.update(kw)
    return d


class TestRules(unittest.TestCase):
    def test_ok_as_is(self):
        self.assertEqual(normalize.needs_normalize(info(avg_fps=29.995))[0], False)        # 長さの端数で平均が少しずれるのは許す

    def test_needs(self):
        cases = {"vfr": info(avg_fps=29.5), "novideo": info(has_video=False)}
        for name, i in cases.items():
            with self.subTest(name):
                need, why = normalize.needs_normalize(i)
                self.assertTrue(need)
                self.assertTrue(why)
        self.assertEqual(normalize.needs_normalize(None), (True, ["ffprobe で調べられませんでした"]))

    def test_encode_args(self):
        """スタジオの書き出しと同じ画質の設定(crf 18)+ 30fps の固定。既に -vf があればつなぐ"""
        a = normalize.ENC_ARGS
        for pair in (["-vf", "fps=30"], ["-fps_mode", "cfr"], ["-c:v", "libx264"], ["-preset", "veryfast"], ["-crf", "18"],
                     ["-pix_fmt", "yuv420p"], ["-c:a", "aac"], ["-movflags", "+faststart"]):
            i = a.index(pair[0])
            self.assertEqual(a[i:i + 2], pair)
        self.assertNotIn("-r", a)
        self.assertEqual(normalize.ENC_FAST_ARGS[normalize.ENC_FAST_ARGS.index("-preset") + 1], "ultrafast")
        self.assertEqual(normalize.ENC_FAST_ARGS[normalize.ENC_FAST_ARGS.index("-crf") + 1], "18")
        self.assertEqual(normalize.fps_filter("scale=-2:720"), "scale=-2:720,fps=30")
        self.assertNotIn("-vf", normalize.encode_args(in_graph=True))

    def test_legacy_rules(self):
        """古い ffmpeg への備え: -fps_mode → -vsync の読み替えと、エラーの文の見分け"""
        a = normalize.legacy_args(normalize.ENC_ARGS)
        self.assertEqual(a[a.index("-vsync"):a.index("-vsync") + 2], ["-vsync", "cfr"])
        self.assertNotIn("-fps_mode", a)
        self.assertIn("-fps_mode", normalize.ENC_ARGS)   # 元のリストは変えない
        self.assertTrue(normalize.is_fps_mode_error("Unrecognized option 'fps_mode'.\nError splitting the argument list: Option not found"))
        self.assertTrue(normalize.is_fps_mode_error("Option fps_mode not found."))
        self.assertFalse(normalize.is_fps_mode_error("Unrecognized option 'no_such_option_xyz'."))
        self.assertFalse(normalize.is_fps_mode_error("Invalid data found when processing input"))

    def test_probe_without_ffprobe(self):
        with mock.patch.object(tools, "find_tool", return_value=None):
            self.assertIsNone(normalize.probe("x.mp4"))
            with self.assertRaises(normalize.NormalizeError):
                normalize.normalize("x.mp4", "y.mp4", ffmpeg="ffmpeg")

    def test_run_with_legacy(self):
        """古い ffmpeg のやり直し(公開の形): -fps_mode を知らないときだけ、書きかけを消して -vsync で1回だけ"""
        old = (1, ["Unrecognized option 'fps_mode'.", "Error splitting the argument list: Option not found"], None)
        calls = []

        def run(answers):
            def f(args):
                calls.append(list(args))
                return answers[len(calls) - 1]
            return f
        tmp = os.path.join(tempfile.mkdtemp(), "part.mp4")
        self.addCleanup(shutil.rmtree, os.path.dirname(tmp), True)
        with open(tmp, "wb") as f:
            f.write(b"x")
        self.assertEqual(normalize.run_with_legacy(run([old, (0, [], None)]), normalize.ENC_ARGS, tmp), (0, [], None))
        self.assertEqual(len(calls), 2)
        self.assertIn("-vsync", calls[1])
        self.assertNotIn("-fps_mode", calls[1])
        self.assertFalse(os.path.exists(tmp))                      # やり直しの前に書きかけを消す
        for first, kw in ((old, {"cancelled": lambda: True}),       # 取り消した・止めた・ほかのエラー・成功はやり直さない
                          ((1, ["fps_mode"], "cancel"), {}), ((1, ["Invalid data"], None), {}), ((0, [], None), {})):
            calls.clear()
            self.assertEqual(normalize.run_with_legacy(run([first]), normalize.ENC_ARGS, **kw), first)
            self.assertEqual(len(calls), 1)

    def test_verify(self):
        """作り直した動画の確かめ: 30/1 と長さ(文は呼ぶ側が what・ref・got で選ぶ。dur=None は長さを見ない)"""
        good = {"r_frame_rate": "30/1", "avg_fps": 30.0, "duration": 10.0}
        with mock.patch.object(normalize, "probe", return_value=good):
            self.assertEqual(normalize.verify("x.mp4", 10.3), good)
            self.assertEqual(normalize.verify("x.mp4", None), good)
            with self.assertRaises(normalize.NormalizeError) as cm:
                normalize.verify("x.mp4", 11.0)
            self.assertEqual(str(cm.exception), "作り直した動画の長さが元と違います(元 11.00 秒 / 作り直し 10.00 秒)")

            class Other(ValueError):
                pass
            with self.assertRaises(Other) as cm:
                normalize.verify("x.mp4", 10.3, 0.2, what="作り直した本番版", ref="区間", got="動画", error=Other)
            self.assertEqual(str(cm.exception), "作り直した本番版の長さが区間と違います(区間 10.30 秒 / 動画 10.00 秒)")
        with mock.patch.object(normalize, "probe", return_value=dict(good, duration=None)):
            with self.assertRaises(normalize.NormalizeError) as cm:
                normalize.verify("x.mp4", 10.0)
            self.assertIn("作り直し 不明 秒", str(cm.exception))
        for info, shown in ((None, "読めません"), (dict(good, r_frame_rate="60/1", avg_fps=60.0), "60/1")):
            with mock.patch.object(normalize, "probe", return_value=info):
                with self.assertRaises(normalize.NormalizeError) as cm:
                    normalize.verify("x.mp4", None)
                self.assertEqual(str(cm.exception), "作り直した動画が 30fps になっていません(%s)" % shown)


@unittest.skipUnless(FF and FP, "ffmpeg・ffprobe が無い環境ではスキップ")
class TestNormalize(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.src = tempfile.mkdtemp()
        cls.v60 = make(os.path.join(cls.src, "v60.mp4"), 60, 2, audio=False)          # 60fps・2 秒・yuv420p の H.264
        cls.long = make(os.path.join(cls.src, "long.mp4"), 60, 30, size="320x240", src="testsrc2")   # 取り消し用(作り直しに少しかかる)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.src, ignore_errors=True)

    def setUp(self):
        no_gpu(self)
        self.tmp = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def leftovers(self):
        return [n for n in os.listdir(self.tmp) if normalize.PART in n]

    def test_probe_missing_file(self):
        self.assertIsNone(normalize.probe(os.path.join(self.tmp, "無い.mp4")))

    def test_cancel_leaves_nothing(self):
        flag = []
        dst = os.path.join(self.tmp, "c.mp4")
        with self.assertRaises(normalize.Cancelled):
            normalize.normalize(self.long, dst, cancelled=lambda: bool(flag), on_progress=lambda p: flag.append(p))
        self.assertFalse(os.path.exists(dst))
        self.assertEqual(self.leftovers(), [])

    def test_ffmpeg_failure_leaves_nothing(self):
        dst = os.path.join(self.tmp, "f.mp4")
        with mock.patch.object(normalize, "encode_args", return_value=["-no_such_option_xyz", "1"]):
            with self.assertRaises(normalize.NormalizeError) as cm:
                normalize.normalize(self.v60, dst)
        self.assertNotIsInstance(cm.exception, normalize.Cancelled)
        self.assertFalse(os.path.exists(dst))
        self.assertEqual(self.leftovers(), [])

    def test_verify_failure_leaves_nothing(self):
        """作り直しは終わったが検証(長さ)で落ちたとき: 一時ファイルを消し、dst は作らない"""
        dst = os.path.join(self.tmp, "v.mp4")
        with mock.patch.object(normalize, "DURATION_TOL", -1):
            with self.assertRaises(normalize.NormalizeError) as cm:
                normalize.normalize(self.v60, dst)
        self.assertIn("長さ", str(cm.exception))
        self.assertFalse(os.path.exists(dst))
        self.assertEqual(self.leftovers(), [])


class OldFfmpeg:
    """ffmpeg 5.1 より古い ffmpeg のふり(normalize の popen に渡す): -fps_mode を知らずに失敗し、-vsync は分かる。
    -vsync の呼び出しは、本物の ffmpeg(7 以降は -vsync が無い)に -fps_mode へ読み替えて渡す。vsync_ok=False なら -vsync でも失敗する"""
    MSG = "Unrecognized option '%s'.\nError splitting the argument list: Option not found\n"

    def __init__(self, vsync_ok=True):
        self.calls, self.vsync_ok = [], vsync_ok

    def fail(self, opt, kw):
        code = "import sys; sys.stdout.write(%r); sys.exit(8)" % (self.MSG % opt)
        return subprocess.Popen([sys.executable, "-c", code], **kw)

    def __call__(self, cmd, **kw):
        self.calls.append(list(cmd))
        if "-fps_mode" in cmd:
            return self.fail("fps_mode", kw)
        if not self.vsync_ok:
            return self.fail("vsync", kw)
        return subprocess.Popen(["-fps_mode" if a == "-vsync" else a for a in cmd], **kw)


@unittest.skipUnless(FF and FP, "ffmpeg・ffprobe が無い環境ではスキップ")
class TestOldFfmpeg(unittest.TestCase):
    """-fps_mode を知らない古い ffmpeg: -vsync cfr に替えて1回だけやり直す(Q1 の 4。友人の PC の ffmpeg が古いとき)"""
    @classmethod
    def setUpClass(cls):
        cls.src = tempfile.mkdtemp()
        cls.v60 = make(os.path.join(cls.src, "v60.mp4"), 60, 2)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.src, ignore_errors=True)

    def setUp(self):
        no_gpu(self)
        self.tmp = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_retry_with_vsync(self):
        fake = OldFfmpeg()
        dst = os.path.join(self.tmp, "old.mp4")
        out = normalize.normalize(self.v60, dst, popen=fake)
        self.assertEqual(len(fake.calls), 2)
        self.assertIn("-fps_mode", fake.calls[0])
        self.assertNotIn("-fps_mode", fake.calls[1])
        i = fake.calls[1].index("-vsync")
        self.assertEqual(fake.calls[1][i + 1], "cfr")
        self.assertEqual(out["r_frame_rate"], "30/1")
        self.assertEqual(sorted(os.listdir(self.tmp)), ["old.mp4"])   # 1回目の書きかけは残らない

    def test_retry_only_once(self):
        fake = OldFfmpeg(vsync_ok=False)
        dst = os.path.join(self.tmp, "old.mp4")
        with self.assertRaises(normalize.NormalizeError) as cm:
            normalize.normalize(self.v60, dst, popen=fake)
        self.assertEqual(len(fake.calls), 2)
        self.assertIn("vsync", str(cm.exception))
        self.assertEqual(os.listdir(self.tmp), [])


class TestFastRules(unittest.TestCase):
    """速くする 2 つの決まり:映像が条件どおりなら音声だけ・GPU の作り方の引数と使えるかの確かめ"""
    def test_video_ok(self):
        """映像をコピーしてよいか(音声だけ違う・60fps の道は通し)"""
        for bad in (info(vcodec="hevc"), info(bit_depth=10), info(pix_fmt="yuv444p"), info(avg_fps=29.5), info(has_video=False), None):
            self.assertFalse(normalize.video_ok(bad))

    def test_gpu_args_keep_the_rules(self):
        for codec, looks in normalize.GPU_ENCODERS:
            self.assertEqual(set(looks), {"main", "preview"})
            a = normalize.encode_args(codec=codec)
            for pair in (["-vf", "fps=30"], ["-fps_mode", "cfr"], ["-c:v", codec], ["-pix_fmt", "yuv420p"], ["-c:a", "aac"], ["-movflags", "+faststart"]):
                i = a.index(pair[0])
                self.assertEqual(a[i:i + 2], pair)
            self.assertNotIn("-crf", a)
        self.assertEqual(normalize.ENC_ARGS[normalize.ENC_ARGS.index("-c:v") + 1], "libx264")

    def test_gpu_encoder_order_and_switch(self):
        """GPU_ENCODERS の順で最初に使える物・スイッチで使わない・どれも使えなければ libx264 だけ"""
        with mock.patch.dict(os.environ, {normalize.GPU_ENV: "0"}):
            self.assertIsNone(normalize.gpu_encoder("ffmpeg", runner=lambda c: 0))
            self.assertEqual([c for c, _a in normalize.encode_tries("ffmpeg", runner=lambda c: 0)], ["libx264"])
        with mock.patch.dict(os.environ, {normalize.GPU_ENV: ""}):
            amd = lambda c: 0 if "h264_amf" in c else 1   # noqa: E731
            self.assertEqual(normalize.gpu_encoder("ffmpeg", runner=amd), "h264_amf")
            self.assertEqual([c for c, _a in normalize.encode_tries("ffmpeg", runner=amd)], ["h264_amf", "libx264"])
            self.assertIsNone(normalize.gpu_encoder("ffmpeg", runner=lambda c: 1))
            self.assertIsNone(normalize.gpu_encoder(None))

    def test_preview_look_and_prev_switch(self):
        """確認用の動画も GPU → libx264(crf は PREVIEW_CRF)。前の設定に戻すスイッチで本番の GPU は前の値・確認用の動画は libx264 だけ"""
        amd = lambda c: 0 if "h264_amf" in c else 1   # noqa: E731
        with mock.patch.dict(os.environ, {normalize.GPU_ENV: "", normalize.PREV_ENV: ""}):
            pv = normalize.video_tries("ffmpeg", "preview", "veryfast", runner=amd)
            self.assertEqual([c for c, _a in pv], ["h264_amf", "libx264"])
            self.assertEqual(pv[1][1][pv[1][1].index("-crf") + 1], normalize.PREVIEW_CRF)
            self.assertEqual(normalize.enc_set(), normalize.ENC_SET)
        with mock.patch.dict(os.environ, {normalize.GPU_ENV: "", normalize.PREV_ENV: "1"}):
            self.assertEqual([c for c, _a in normalize.video_tries("ffmpeg", "preview", runner=amd)], ["libx264"])
            self.assertEqual(normalize.video_args("h264_amf")[2:], normalize.PREV_MAIN["h264_amf"])
            self.assertEqual(normalize.enc_set(), "prev")


@unittest.skipUnless(FF and FP, "ffmpeg・ffprobe が無い環境ではスキップ")
class TestFastPaths(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.src = tempfile.mkdtemp()
        cls.v60 = make(os.path.join(cls.src, "v60.mp4"), 60, 2)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.src, ignore_errors=True)

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def test_gpu_first_then_cpu(self):
        """GPU が使えると見たら(確かめを差し替えて全部使えると見せる = 最初の h264_nvenc から)。GPU で作れなければ(NVIDIA の無い PC では必ず)libx264 で 1 回だけやり直す"""
        calls = []

        def popen(cmd, **kw):
            calls.append(list(cmd))
            return subprocess.Popen(cmd, **kw)
        with mock.patch.dict(os.environ, {normalize.GPU_ENV: ""}):
            out = normalize.normalize(self.v60, os.path.join(self.tmp, "g.mp4"), popen=popen, gpu_runner=lambda c: 0)
        self.assertEqual(calls[0][calls[0].index("-c:v") + 1], "h264_nvenc")
        self.assertEqual(normalize.probe(out["path"])["r_frame_rate"], "30/1")
        if out["how"] == "CPU(libx264)":   # この PC に NVIDIA の GPU が無い
            self.assertEqual(len(calls), 2)
            self.assertEqual(calls[1][calls[1].index("-c:v") + 1], "libx264")
            self.assertTrue(out["failed"][0].startswith("GPU(h264_nvenc)"))
        else:
            self.assertEqual((out["how"], len(calls)), ("GPU(h264_nvenc)", 1))
        self.assertEqual([n for n in os.listdir(self.tmp) if normalize.PART in n], [])


if __name__ == "__main__":
    unittest.main()
