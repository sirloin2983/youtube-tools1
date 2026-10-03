"""作業データのバックアップ(home/backup.py)の単体テスト。一時フォルダだけを使う。

実行(リポジトリ直下から): python -m unittest home/tests/test_backup.py -v
"""
import contextlib
import io
import json
import os
import shutil
import sys
import tempfile
import unittest

os.environ.setdefault("YTT_DATA_DIR", "inplace")
HOME = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
ROOT = os.path.dirname(HOME)
for p in (HOME, ROOT):
    if p not in sys.path:
        sys.path.insert(0, p)

import backup  # noqa: E402
import prefs as prefs_mod  # noqa: E402
from ytt_core import fsio  # noqa: E402


def put(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


def read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


class BackupTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="ytt-backup-")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.src = os.path.join(self.tmp, "data")
        self.dst = os.path.join(self.tmp, "外付け", "backup")
        put(os.path.join(self.src, "transcribe", "transcripts", "a.json"), "文書 1")
        put(os.path.join(self.src, "transcribe", "transcripts", ".hist", "a", "1.json"), "履歴")
        put(os.path.join(self.src, "transcribe", "voices", "voxceleb.json"), "{}")
        put(os.path.join(self.src, "studio", "data.json"), '{"v": 1}')
        put(os.path.join(self.src, "studio", "config.json"), "{}")
        put(os.path.join(self.src, "cut2resolve", "packs", "p.json"), "{}")
        # 写す(作り直しに Visual Studio が要る whisper.cpp と、作り直せない評価用の音声)
        put(os.path.join(self.src, "transcribe", "bin", "whisper.cpp-v1-vulkan", "whisper-cli.exe"), "exe")
        put(os.path.join(self.src, "transcribe", "bin", "whisper.cpp-v1-vulkan", "build", "bin", "x.dll"), "dll")
        put(os.path.join(self.src, "transcribe", "eval-audio", "a.flac"), "flac")
        # 写さないもの
        put(os.path.join(self.src, "studio", "cache", "chat", "big.json"), "x" * 100)
        put(os.path.join(self.src, "studio", "studio.log"), "log")
        put(os.path.join(self.src, "transcribe", "models", "diar", "m.onnx"), "model")
        put(os.path.join(self.src, "transcribe", "bin", "w.exe"), "exe")
        put(os.path.join(self.src, "transcribe", "bin", "llama.cpp-b1", "llama-server.exe"), "exe")
        put(os.path.join(self.src, "studio", "bin", "other.exe"), "exe")   # transcribe 以外の bin は今までどおり写さない
        put(os.path.join(self.src, "app", "logs", "launcher.log"), "log")
        put(os.path.join(self.src, "app", "browser-profile", "x"), "p")
        put(os.path.join(self.src, "cut2resolve", "work", "uploads", "u.mp4"), "v")
        put(os.path.join(self.src, "studio", "data.json.part-123"), "half")

    def files(self):
        out = []
        for d, _, names in os.walk(self.dst):
            out += [os.path.relpath(os.path.join(d, n), os.path.join(self.dst, backup.DEST_NAME)).replace("\\", "/") for n in names]
        return sorted(out)

    def test_copies_what_cannot_be_remade_and_skips_the_rest(self):
        r = backup.run_once(self.src, self.dst)
        self.assertEqual(self.files(), ["cut2resolve/packs/p.json", "studio/config.json", "studio/data.json",
                                        "transcribe/bin/whisper.cpp-v1-vulkan/build/bin/x.dll", "transcribe/bin/whisper.cpp-v1-vulkan/whisper-cli.exe",
                                        "transcribe/eval-audio/a.flac",
                                        "transcribe/transcripts/.hist/a/1.json", "transcribe/transcripts/a.json", "transcribe/voices/voxceleb.json"])
        self.assertEqual((r["copied"], r["same"], r["errors"]), (9, 0, []))
        self.assertEqual(read(os.path.join(self.dst, backup.DEST_NAME, "transcribe", "transcripts", "a.json")), "文書 1")

    def test_second_run_copies_only_changes_and_keeps_one_previous(self):
        backup.run_once(self.src, self.dst)
        r = backup.run_once(self.src, self.dst)
        self.assertEqual((r["copied"], r["same"]), (0, 9))
        put(os.path.join(self.src, "studio", "data.json"), '{"v": 2, "more": true}')
        r = backup.run_once(self.src, self.dst)
        self.assertEqual((r["copied"], r["same"]), (1, 8))
        d = os.path.join(self.dst, backup.DEST_NAME, "studio")
        self.assertEqual((read(os.path.join(d, "data.json")), read(os.path.join(d, "data.json.prev"))), ('{"v": 2, "more": true}', '{"v": 1}'))
        # 同じ日の2回目の上書きでは、1つ前(その日の最初の形)を残したまま
        put(os.path.join(self.src, "studio", "data.json"), "")
        backup.run_once(self.src, self.dst)
        self.assertEqual((read(os.path.join(d, "data.json")), read(os.path.join(d, "data.json.prev"))), ("", '{"v": 1}'))
        # 日が変わったら、1つ前を入れ替える
        put(os.path.join(self.src, "studio", "data.json"), '{"v": 3}')
        backup.run_once(self.src, self.dst, day="2099-01-01")
        self.assertEqual((read(os.path.join(d, "data.json")), read(os.path.join(d, "data.json.prev"))), ('{"v": 3}', ""))

    def test_never_deletes_in_destination(self):
        backup.run_once(self.src, self.dst)
        os.remove(os.path.join(self.src, "transcribe", "transcripts", "a.json"))
        backup.run_once(self.src, self.dst)
        self.assertIn("transcribe/transcripts/a.json", self.files())

    def test_refuses_bad_places(self):
        for folder in ("", "relative", os.path.join(self.src, "studio"), self.src):
            with self.assertRaises(ValueError, msg=folder):
                backup.run_once(self.src, folder)
        with self.assertRaises(ValueError):
            backup.run_once(os.path.join(self.tmp, "無い"), self.dst)
        if os.name == "nt":
            free = [c for c in "QWXYZ" if not os.path.exists(c + ":\\")]
            if free:
                with self.assertRaisesRegex(ValueError, "ドライブ"):
                    backup.run_once(self.src, free[0] + ":\\backup")

    def test_does_not_follow_symlinks(self):
        outside = os.path.join(self.tmp, "outside")
        put(os.path.join(outside, "secret.txt"), "s")
        try:
            os.symlink(outside, os.path.join(self.src, "studio", "link"), target_is_directory=True)
        except (OSError, NotImplementedError):
            self.skipTest("シンボリックリンクを作れない")
        backup.run_once(self.src, self.dst)
        self.assertFalse(any("secret" in f for f in self.files()))

    def make(self, clock):
        self.prefs = prefs_mod.Prefs(os.path.join(self.tmp, "app", "prefs.json"), fsio.atomic_write)
        logs = []
        return backup.Backup(self.prefs, self.src, os.path.join(self.tmp, "app"), log=logs.append, clock=clock), logs

    def test_tick_runs_when_due_and_remembers(self):
        now = [1000000.0]
        b, logs = self.make(lambda: now[0])
        self.assertIsNone(b.tick())
        self.assertEqual((b.state, b.snapshot()["enabled"]), ("off", False))
        self.prefs.patch("backup", {"enabled": True, "folder": self.dst, "everyHours": 24})
        r = b.tick()
        self.assertEqual((r["copied"], b.state), (9, "idle"))
        s = b.snapshot()
        self.assertEqual((s["lastOk"], s["copied"], s["stateLabel"], s["folder"]), (1000000000, 9, "動いています", self.dst))
        self.assertTrue(any("9 個を写しました" in m for m in logs))
        now[0] += 3600
        self.assertIsNone(b.tick())               # まだ時間が来ていない
        b.run_now()
        self.assertEqual(b.tick()["copied"], 0)   # 「今すぐ」は時間によらない
        now[0] += 24 * 3600
        self.assertEqual(b.tick()["same"], 9)
        # 起動し直しても、最後に写した時刻を覚えている
        b2, _ = self.make(lambda: now[0] + 60)
        self.assertIsNone(b2.tick())
        self.assertEqual(json.loads(read(b.state_path))["copied"], 0)
        # 写す先を変えたら、時間によらず写す
        other = os.path.join(self.tmp, "別の先")
        self.prefs.patch("backup", {"folder": other})
        self.assertEqual(b2.tick()["copied"], 9)

    def test_tick_reports_bad_place_and_inplace(self):
        b, _ = self.make(lambda: 5.0)
        self.prefs.patch("backup", {"enabled": True, "folder": os.path.join(self.src, "x")})
        self.assertIsNone(b.tick())
        self.assertEqual(b.state, "error")
        self.assertIn("作業データの中", b.snapshot()["message"])
        b.source = None   # YTT_DATA_DIR=inplace(テスト・以前の形)では写さない
        b.tick()
        self.assertEqual(b.state, "off")

    def quiet_setup(self, t0):
        """作業データの更新時刻をテストの時計(t0)のずっと前にそろえて、Backup を作る"""
        self.prefs = prefs_mod.Prefs(os.path.join(self.tmp, "app", "prefs.json"), fsio.atomic_write)
        self.now = [t0]
        b = backup.Backup(self.prefs, self.src, os.path.join(self.tmp, "app"), clock=lambda: self.now[0])
        self.prefs.patch("backup", {"enabled": True, "folder": self.dst, "everyHours": 24})
        for d, _, names in os.walk(self.src):
            for n in names:
                os.utime(os.path.join(d, n), (t0 - 10000, t0 - 10000))
        return b

    def test_tick_copies_changes_after_quiet_period(self):
        """変わったら、間隔(24 時間)を待たず、最後の変更から 120 秒たったら写す。保存が続いている間は待つ"""
        now = [2000000000.0]
        b = self.quiet_setup(now[0])
        now = self.now
        a_json = os.path.join(self.src, "transcribe", "transcripts", "a.json")

        def touch(path, text, at):
            put(path, text)
            os.utime(path, (at, at))

        self.assertEqual(b.tick()["copied"], 9)
        now[0] += 60
        self.assertIsNone(b.tick())                       # 変わっていない
        touch(a_json, "校正 2", now[0] - 30)              # 30 秒前に保存
        self.assertIsNone(b.tick())                       # まだ静かになっていない(保存が続くかもしれない)
        now[0] += 60
        touch(a_json, "校正 3", now[0] - 10)              # また保存 → 待ち直し
        self.assertIsNone(b.tick())
        now[0] += backup.QUIET
        r = b.tick()                                      # 最後の保存から 120 秒以上 → 間隔(24 時間)の前でも写す
        self.assertEqual((r["copied"], r["same"]), (1, 8))
        self.assertEqual(read(os.path.join(self.dst, backup.DEST_NAME, "transcribe", "transcripts", "a.json")), "校正 3")
        self.assertIsNone(b.tick())                       # 写したあとは、また変わるまで写さない
        # 写すたびに書き換わる記録・対象外のファイルの更新では写さない
        now[0] += 10
        touch(os.path.join(self.src, "app", "backup-state.json"), "{}", now[0] - 1)
        touch(os.path.join(self.src, "studio", "studio.log"), "log 2", now[0] - 1)
        touch(os.path.join(self.src, "studio", "cache", "chat", "big.json"), "y", now[0] - 1)
        now[0] += 1000
        self.assertIsNone(b.tick())
        # 起動し直しても(記録から)変わったかを判断できる
        touch(a_json, "校正 4", now[0] - 500)
        b2 = backup.Backup(self.prefs, self.src, os.path.join(self.tmp, "app"), clock=lambda: now[0])
        self.assertEqual(b2.tick()["copied"], 2)   # 校正 + 先ほど書き換えた記録(対象なので写る。変わった判定には使わない)

    def test_changed_files_that_failed_are_retried(self):
        b = self.quiet_setup(2000000000.0)
        now = self.now
        old = backup.copy_one

        def broken(src, dst, day):
            if os.path.basename(src) == "a.json":
                raise PermissionError(13, "使用中")
            return old(src, dst, day)

        backup.copy_one = broken
        self.addCleanup(setattr, backup, "copy_one", old)
        r = b.tick()
        self.assertEqual(len(r["errors"]), 1)
        now[0] += 200
        backup.copy_one = old                             # 使用中でなくなった
        r = b.tick()                                      # 古い更新時刻のままでも、写せなかった分は静かになってからもう一度
        self.assertEqual((r["copied"], r["errors"]), (1, []))

    def test_whisper_bin_only_and_eval_audio(self):
        names = [rel.replace("\\", "/") for rel, _, _ in backup.plan(self.src)]
        self.assertIn("transcribe/bin/whisper.cpp-v1-vulkan/whisper-cli.exe", names)
        self.assertIn("transcribe/bin/whisper.cpp-v1-vulkan/build/bin/x.dll", names)
        self.assertIn("transcribe/eval-audio/a.flac", names)
        self.assertFalse([n for n in names if n.startswith("transcribe/bin/") and "whisper.cpp-" not in n])
        self.assertFalse([n for n in names if "/models/" in n or n.startswith("studio/bin/")])

    def test_restore_roundtrip(self):
        backup.run_once(self.src, self.dst)
        put(os.path.join(self.src, "studio", "data.json"), '{"v": 22}')
        backup.run_once(self.src, self.dst)               # .prev ができる
        want = {rel: read(os.path.join(self.src, rel)) for rel, _, _ in backup.plan(self.src)}
        shutil.rmtree(self.src)
        self.assertEqual(backup.restore_once(self.dst, self.src, dry_run=True)["copied"], len(want))
        self.assertFalse(os.path.exists(self.src))        # dry_run は書かない
        r = backup.restore_once(self.dst, self.src)
        self.assertEqual((r["copied"], r["same"], r["newer"], r["errors"]), (len(want), 0, 0, []))
        got = {rel: read(os.path.join(self.src, rel)) for rel, _, _ in backup.plan(self.src)}
        self.assertEqual(got, want)
        self.assertEqual(got[os.path.join("studio", "data.json")], '{"v": 22}')
        self.assertFalse(any(f.endswith(".prev") for _, _, fs in os.walk(self.src) for f in fs))   # .prev は戻さない
        r = backup.restore_once(self.dst, self.src)       # 2回目は何もしない
        self.assertEqual((r["copied"], r["same"]), (0, len(want)))

    def test_restore_does_not_overwrite_newer(self):
        backup.run_once(self.src, self.dst)
        a = os.path.join(self.src, "transcribe", "transcripts", "a.json")
        put(a, "バックアップのあとで直した")
        os.utime(a, (4000000000, 4000000000))             # こちらのほうが新しい → 上書きしない
        d = os.path.join(self.src, "studio", "data.json")
        put(d, "古い")
        os.utime(d, (1, 1))                               # こちらが古い → バックアップで上書き
        r = backup.restore_once(self.dst, self.src)
        self.assertEqual((r["copied"], r["newer"]), (1, 1))
        self.assertEqual(read(a), "バックアップのあとで直した")
        self.assertEqual(read(d), '{"v": 1}')
        put(os.path.join(self.src, "extra.json"), "x")    # バックアップに無いファイルは消さない
        backup.restore_once(self.dst, self.src)
        self.assertTrue(os.path.exists(os.path.join(self.src, "extra.json")))

    def test_restore_refuses_bad_places_and_symlinks(self):
        backup.run_once(self.src, self.dst)
        for folder, target in (("relative", self.src), (os.path.join(self.tmp, "無い"), self.src), (self.dst, ""),
                               (self.dst, os.path.join(self.dst, backup.DEST_NAME, "studio")), (self.dst, self.dst)):
            with self.assertRaises(ValueError, msg=(folder, target)):
                backup.restore_once(folder, target)
        outside = os.path.join(self.tmp, "outside")
        put(os.path.join(outside, "secret.txt"), "s")
        try:
            os.symlink(outside, os.path.join(self.dst, backup.DEST_NAME, "studio", "link"), target_is_directory=True)
        except (OSError, NotImplementedError):
            self.skipTest("シンボリックリンクを作れない")
        tgt = os.path.join(self.tmp, "restored")
        backup.restore_once(self.dst, tgt)
        self.assertFalse(os.path.exists(os.path.join(tgt, "studio", "link")))

    def test_restore_cli(self):
        backup.run_once(self.src, self.dst)
        out = contextlib.redirect_stdout(io.StringIO())
        out.__enter__()
        self.addCleanup(out.__exit__, None, None, None)
        tgt = os.path.join(self.tmp, "restored")
        self.assertEqual(backup.main(["--restore", self.dst, "--target", tgt, "--yes"]), 0)
        self.assertEqual(read(os.path.join(tgt, "studio", "data.json")), '{"v": 1}')
        self.assertEqual(backup.main(["--restore", self.dst, "--target", tgt, "--yes"]), 0)   # 写すものなし
        self.assertEqual(backup.main(["--restore", os.path.join(self.tmp, "無い"), "--target", tgt, "--yes"]), 2)

    def test_prefs_shape(self):
        p = prefs_mod.Prefs(os.path.join(self.tmp, "p.json"), fsio.atomic_write)
        self.assertEqual(p.get(["backup"])["backup"], {"enabled": False, "folder": "", "everyHours": 1})
        for bad in ({"enabled": True}, {"folder": "\\\\srv\\share"}, {"folder": "rel"}, {"everyHours": 0}, {"everyHours": 1.5}, {"everyHours": True}):
            with self.assertRaises(prefs_mod.PrefsError, msg=bad):
                p.patch("backup", bad)
        self.assertEqual(p.patch("backup", {"enabled": True, "folder": self.dst, "everyHours": 6, "x": 1}),
                         {"enabled": True, "folder": self.dst, "everyHours": 6})
        self.assertEqual(p.get(["intake"])["intake"]["enabled"], False)   # ほかの節はそのまま


if __name__ == "__main__":
    unittest.main()
