"""作業データのバックアップ(home/backup.py)の単体テスト。一時フォルダだけを使う。

実行(リポジトリ直下から): python -m unittest home/tests/test_backup.py -v
"""
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
        # 写さないもの
        put(os.path.join(self.src, "studio", "cache", "chat", "big.json"), "x" * 100)
        put(os.path.join(self.src, "studio", "studio.log"), "log")
        put(os.path.join(self.src, "transcribe", "models", "diar", "m.onnx"), "model")
        put(os.path.join(self.src, "transcribe", "bin", "w.exe"), "exe")
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
                                        "transcribe/transcripts/.hist/a/1.json", "transcribe/transcripts/a.json", "transcribe/voices/voxceleb.json"])
        self.assertEqual((r["copied"], r["same"], r["errors"]), (6, 0, []))
        self.assertEqual(read(os.path.join(self.dst, backup.DEST_NAME, "transcribe", "transcripts", "a.json")), "文書 1")

    def test_second_run_copies_only_changes_and_keeps_one_previous(self):
        backup.run_once(self.src, self.dst)
        r = backup.run_once(self.src, self.dst)
        self.assertEqual((r["copied"], r["same"]), (0, 6))
        put(os.path.join(self.src, "studio", "data.json"), '{"v": 2, "more": true}')
        r = backup.run_once(self.src, self.dst)
        self.assertEqual((r["copied"], r["same"]), (1, 5))
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
        self.assertEqual((r["copied"], b.state), (6, "idle"))
        s = b.snapshot()
        self.assertEqual((s["lastOk"], s["copied"], s["stateLabel"], s["folder"]), (1000000000, 6, "動いています", self.dst))
        self.assertTrue(any("6 個を写しました" in m for m in logs))
        now[0] += 3600
        self.assertIsNone(b.tick())               # まだ時間が来ていない
        b.run_now()
        self.assertEqual(b.tick()["copied"], 0)   # 「今すぐ」は時間によらない
        now[0] += 24 * 3600
        self.assertEqual(b.tick()["same"], 6)
        # 起動し直しても、最後に写した時刻を覚えている
        b2, _ = self.make(lambda: now[0] + 60)
        self.assertIsNone(b2.tick())
        self.assertEqual(json.loads(read(b.state_path))["copied"], 0)
        # 写す先を変えたら、時間によらず写す
        other = os.path.join(self.tmp, "別の先")
        self.prefs.patch("backup", {"folder": other})
        self.assertEqual(b2.tick()["copied"], 6)

    def test_tick_reports_bad_place_and_inplace(self):
        b, _ = self.make(lambda: 5.0)
        self.prefs.patch("backup", {"enabled": True, "folder": os.path.join(self.src, "x")})
        self.assertIsNone(b.tick())
        self.assertEqual(b.state, "error")
        self.assertIn("作業データの中", b.snapshot()["message"])
        b.source = None   # YTT_DATA_DIR=inplace(テスト・以前の形)では写さない
        b.tick()
        self.assertEqual(b.state, "off")

    def test_prefs_shape(self):
        p = prefs_mod.Prefs(os.path.join(self.tmp, "p.json"), fsio.atomic_write)
        self.assertEqual(p.get(["backup"])["backup"], {"enabled": False, "folder": "", "everyHours": 24})
        for bad in ({"enabled": True}, {"folder": "\\\\srv\\share"}, {"folder": "rel"}, {"everyHours": 0}, {"everyHours": 1.5}, {"everyHours": True}):
            with self.assertRaises(prefs_mod.PrefsError, msg=bad):
                p.patch("backup", bad)
        self.assertEqual(p.patch("backup", {"enabled": True, "folder": self.dst, "everyHours": 6, "x": 1}),
                         {"enabled": True, "folder": self.dst, "everyHours": 6})
        self.assertEqual(p.get(["intake"])["intake"]["enabled"], False)   # ほかの節はそのまま


if __name__ == "__main__":
    unittest.main()
