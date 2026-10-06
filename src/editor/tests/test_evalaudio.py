#!/usr/bin/env python3
"""評価用の音声(ed_evalaudio.py。マスタープラン Q0)のテスト。評価用のフォルダの中の動画から 16kHz・モノラルの flac を作業データに作る。

    python -m unittest src/editor/tests/test_metrics.py   # test_metrics がこのファイルのテストも読み込む
    python -m unittest src/editor/tests/test_evalaudio.py # これだけ
ffmpeg が必要(2 秒の小さな動画を lavfi で作る)。
"""
import json
import os
os.environ.setdefault("YTT_DATA_DIR", "inplace")   # テストは作業データを本物の置き場所に書かない(ytt_core.datadir)
import re
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock

TESTS = os.path.dirname(os.path.abspath(__file__))
HERE = os.path.dirname(TESTS)
os.environ.setdefault("YTT_CORE_DIR", os.path.dirname(HERE))
sys.path.insert(0, HERE)
sys.path.insert(0, TESTS)
import serve as S  # noqa: E402
import ed_evalaudio as EA  # noqa: E402

FFMPEG = shutil.which("ffmpeg")


def make_video(path, seconds=2, freq=440):
    subprocess.run([FFMPEG, "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi", "-i", "testsrc=size=64x64:rate=10:duration=%s" % seconds,
                    "-f", "lavfi", "-i", "sine=frequency=%d:duration=%s" % (freq, seconds), "-c:v", "mpeg4", "-c:a", "aac", "-shortest", path],
                   check=True, stdin=subprocess.DEVNULL)


@unittest.skipUnless(FFMPEG, "ffmpeg が必要")
class TestEvalAudio(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()    # 作業データの代わり(設定・eval-audio/)
        self.ev = tempfile.mkdtemp()     # 評価用のフォルダ(動画)
        self.saved = (S.TX_DIR, S.TMP_DIR, S.SETTINGS)
        S.TX_DIR, S.TMP_DIR, S.SETTINGS = os.path.join(self.tmp, "transcripts"), os.path.join(self.tmp, ".tmp"), os.path.join(self.tmp, "settings.json")
        self.mem = os.path.join(self.ev, "1_JP", "評価用データ01_ときのそら")
        os.makedirs(self.mem)
        self.set_dirs([self.ev])

    def tearDown(self):
        S.TX_DIR, S.TMP_DIR, S.SETTINGS = self.saved
        shutil.rmtree(self.tmp, ignore_errors=True)
        shutil.rmtree(self.ev, ignore_errors=True)

    def set_dirs(self, dirs):
        with open(S.SETTINGS, "w", encoding="utf-8") as f:
            json.dump({"evalDirs": dirs} if dirs is not None else {}, f, ensure_ascii=False)

    def video(self, name="配信 切り抜き#1.mp4", **kw):
        p = os.path.join(self.mem, name)
        make_video(p, **kw)
        return p

    def flac_path(self, item):
        return os.path.join(EA.audio_dir(), item["flac"])

    def test_names(self):
        k = EA.path_key(r"E:\Video\評価用データ\a.mp4")
        self.assertRegex(k, r"^[0-9a-f]{12}$")
        self.assertEqual(k, EA.path_key("e:/video/評価用データ/A.MP4"))   # 大文字小文字・区切りは同じ
        self.assertNotEqual(k, EA.path_key(r"E:\Video\評価用データ\b.mp4"))
        self.assertEqual(EA.flac_name(r"E:\x\配信:切り抜き?.mp4"), "%s_配信_切り抜き_.flac" % EA.path_key(r"E:\x\配信:切り抜き?.mp4"))
        self.assertTrue(len(EA.safe_stem("あ" * 200)) <= 60)

    def test_makes_flac_16k_mono_and_does_not_remake(self):
        src = self.video()
        r = EA.run_pass("test")
        self.assertEqual((r["made"], r["failed"], r["found"], r["deferred"]), (1, 0, 1, None), r)
        idx = EA.read_index()
        (key, it), = idx["items"].items()
        self.assertEqual(key, EA.path_key(src))
        self.assertEqual((it["src"], it["size"]), (src, os.path.getsize(src)))
        fp = self.flac_path(it)
        self.assertTrue(os.path.isfile(fp) and fp.endswith(".flac") and it["flac"].startswith(key + "_"))
        self.assertAlmostEqual(it["durationSec"], 2.0, delta=0.3)
        info = subprocess.run([FFMPEG, "-hide_banner", "-i", fp], stdin=subprocess.DEVNULL, capture_output=True, text=True, encoding="utf-8", errors="replace").stderr
        self.assertRegex(info, r"flac, 16000 Hz, mono")
        self.assertEqual([n for n in os.listdir(EA.audio_dir()) if n.endswith(".part")], [])   # 書きかけは残さない
        before = os.path.getmtime(fp)
        time.sleep(0.05)
        r2 = EA.run_pass("test")   # 元が変わっていない: 作り直さない
        self.assertEqual((r2["made"], r2["pending"]), (0, 0), r2)
        self.assertEqual(os.path.getmtime(fp), before)
        s = EA.status()
        self.assertEqual((s["enabled"], s["total"], s["made"], s["remaining"], s["gone"], s["failed"], s["lastError"]), (True, 1, 1, 0, 0, 0, None))
        self.assertEqual(s["bytes"], os.path.getsize(fp))
        self.assertAlmostEqual(s["seconds"], 2.0, delta=0.3)

    def test_remakes_when_source_changes(self):
        src = self.video(seconds=2)
        EA.run_pass("test")
        it = next(iter(EA.read_index()["items"].values()))
        make_video(src, seconds=4, freq=880)   # 同じパスで中身が変わった(大きさ・更新時刻が変わる)
        r = EA.run_pass("test")
        self.assertEqual(r["made"], 1, r)
        items = EA.read_index()["items"]
        self.assertEqual(len(items), 1)
        new = next(iter(items.values()))
        self.assertEqual(new["flac"], it["flac"])
        self.assertAlmostEqual(new["durationSec"], 4.0, delta=0.3)

    def test_gone_source_keeps_flac(self):
        src = self.video()
        EA.run_pass("test")
        os.remove(src)
        r = EA.run_pass("test")
        self.assertEqual((r["made"], r["found"]), (0, 0))
        it = next(iter(EA.read_index()["items"].values()))
        self.assertTrue(it["gone"])
        self.assertTrue(os.path.isfile(self.flac_path(it)))   # 消さない
        s = EA.status()
        self.assertEqual((s["made"], s["gone"], s["total"]), (1, 1, 0))
        # 元が戻れば gone の印は外れる
        make_video(src)
        EA.run_pass("test")
        self.assertNotIn("gone", next(iter(EA.read_index()["items"].values())))

    def test_renamed_source_adopts_flac(self):
        """評価用の整理で動画の名前が変わっても(大きさ・更新時刻は同じ)、作り直さずに flac を引き継ぐ"""
        src = self.video("元の名前.mp4")
        EA.run_pass("test")
        old = next(iter(EA.read_index()["items"].values()))
        new = os.path.join(self.mem, "評価用データ01_ときのそら_01_未.mp4")
        os.rename(src, new)
        r = EA.run_pass("test")
        self.assertEqual((r["made"], r["adopted"]), (0, 1), r)
        items = EA.read_index()["items"]
        self.assertEqual(list(items), [EA.path_key(new)])
        it = items[EA.path_key(new)]
        self.assertEqual((it["src"], it["flac"]), (new, old["flac"]))
        self.assertNotIn("gone", it)
        self.assertEqual(len([n for n in os.listdir(EA.audio_dir()) if n.endswith(".flac")]), 1)

    def test_no_eval_dirs_does_nothing(self):
        self.video()
        for dirs in (None, []):
            self.set_dirs(dirs)
            self.assertEqual(EA.run_pass("test"), {"skipped": "no_eval_dirs"})
            self.assertFalse(os.path.exists(EA.audio_dir()))   # フォルダも作らない
        self.assertFalse(EA.status()["enabled"])
        # 評価用のフォルダが空のとき(あるが動画が無い)は、見つけた 0 本で終わる
        self.set_dirs([self.ev])
        shutil.rmtree(os.path.join(self.ev, "1_JP"))
        r = EA.run_pass("test")
        self.assertEqual((r["found"], r["made"]), (0, 0))

    def test_drive_missing_does_not_mark_gone(self):
        """評価用のフォルダが見えない間(外付けのドライブを外した)は、何も gone にしない"""
        self.video()
        EA.run_pass("test")
        self.set_dirs([os.path.join(self.ev, "無いフォルダ")])
        self.assertEqual(EA.run_pass("test"), {"skipped": "no_eval_dirs"})
        self.assertNotIn("gone", next(iter(EA.read_index()["items"].values())))

    def test_defers_while_jobs_run(self):
        self.video()
        with S._jobs_lock:
            S._jobs["evalaudio1"] = {"id": "evalaudio1", "state": "queued", "kind": "transcribe", "spec": {}}
        try:
            r = EA.run_pass("test")
        finally:
            with S._jobs_lock:
                S._jobs.pop("evalaudio1")
        self.assertEqual(r["made"], 0)
        self.assertTrue(r["deferred"])
        self.assertEqual(EA.status()["remaining"], 1)
        self.assertEqual(EA.run_pass("test")["made"], 1)   # ジョブが終われば作る

    def test_failure_is_recorded_and_given_up(self):
        bad = os.path.join(self.mem, "壊れた.mp4")
        with open(bad, "wb") as f:
            f.write(os.urandom(4096))
        for n in range(EA.MAX_FAILS + 1):
            r = EA.run_pass("test")
            self.assertEqual((r["made"], r["failed"]), (0, 1 if n < EA.MAX_FAILS else 0), (n, r))
        it = next(iter(EA.read_index()["items"].values()))
        self.assertEqual((it["flac"], it["fails"]), (None, EA.MAX_FAILS))
        s = EA.status()
        self.assertEqual((s["made"], s["failed"]), (0, 1))
        self.assertEqual(s["lastError"]["src"], "壊れた.mp4")
        self.assertEqual([n for n in os.listdir(EA.audio_dir()) if n.endswith((".part", ".flac"))], [])

    def test_ffmpeg_flags_and_command(self):
        """ffmpeg は 16kHz・モノラル・flac で、Windows では「通常より下」の優先度・黒い画面なし"""
        self.video()
        real = subprocess.run
        seen = []

        def spy(cmd, *a, **k):
            seen.append((cmd, k.get("creationflags")))
            return real(cmd, *a, **k)
        with mock.patch.object(EA.subprocess, "run", spy):
            EA.run_pass("test")
        cmd, flags = seen[0]
        for tok in ("-vn", "-ac", "1", "-ar", "16000", "-c:a", "flac"):
            self.assertIn(tok, cmd)
        self.assertTrue(cmd[-1].endswith(".part"))
        if os.name == "nt":
            self.assertTrue(flags & subprocess.BELOW_NORMAL_PRIORITY_CLASS and flags & subprocess.CREATE_NO_WINDOW)

    def test_pass_is_exclusive(self):
        self.video()
        self.assertTrue(EA._pass_lock.acquire(blocking=False))
        try:
            self.assertEqual(EA.run_pass("test"), {"skipped": "running"})
            self.assertTrue(EA.status()["running"])
        finally:
            EA._pass_lock.release()
        # 別のプロセスが印を持っているとき
        os.makedirs(EA.audio_dir())
        with EA._file_lock(os.path.join(EA.audio_dir(), ".lock")) as got:
            self.assertTrue(got)
            with EA._file_lock(os.path.join(EA.audio_dir(), ".lock")) as got2:
                self.assertFalse(got2)
        self.assertEqual(EA.run_pass("test")["made"], 1)

    def test_background_can_be_disabled(self):
        with mock.patch.dict(os.environ, {"TRANSCRIBE_EVAL_AUDIO": "off"}):
            self.assertIsNone(EA.start_background(0.01, 0.01))


if __name__ == "__main__":
    unittest.main()
