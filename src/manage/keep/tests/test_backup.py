"""作業データのバックアップ(src/manage/keep/backup.py。設定は入口の Prefs を借りる。prefs の節の検査は src/app/tests/test_backup_prefs.py)の単体テスト。一時フォルダだけを使う。

実行(リポジトリ直下から): python -m unittest src/manage/keep/tests/test_backup.py -v
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
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))   # tests -> keep -> manage -> src
HOME = os.path.join(ROOT, "app")   # 設定 prefs(入口 = app)を借りる
for p in (HOME, ROOT):
    if p not in sys.path:
        sys.path.insert(0, p)

from manage.keep import backup  # noqa: E402
from app import prefs as prefs_mod  # noqa: E402
from ytt import fsio  # noqa: E402


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
        # 写す(作り直しに Visual Studio が要る whisper.cpp)
        put(os.path.join(self.src, "transcribe", "bin", "whisper.cpp-v1-vulkan", "whisper-cli.exe"), "exe")
        put(os.path.join(self.src, "transcribe", "bin", "whisper.cpp-v1-vulkan", "build", "bin", "x.dll"), "dll")
        # 写さないもの
        put(os.path.join(self.src, "transcribe", "eval-audio", "a.flac"), "flac")   # 評価用の音声は元の配信から作り直せる(2026-10-15 に外した)
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
                                        "transcribe/transcripts/.hist/a/1.json", "transcribe/transcripts/a.json", "transcribe/voices/voxceleb.json"])
        self.assertEqual((r["copied"], r["same"], r["errors"]), (8, 0, []))
        self.assertEqual(read(os.path.join(self.dst, backup.DEST_NAME, "transcribe", "transcripts", "a.json")), "文書 1")

    def test_second_run_copies_only_changes_and_keeps_one_previous(self):
        backup.run_once(self.src, self.dst)
        r = backup.run_once(self.src, self.dst)
        self.assertEqual((r["copied"], r["same"]), (0, 8))
        put(os.path.join(self.src, "studio", "data.json"), '{"v": 2, "more": true}')
        r = backup.run_once(self.src, self.dst)
        self.assertEqual((r["copied"], r["same"]), (1, 7))
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

    def test_refuses_overlap_through_junction(self):
        """写す先が、見かけは外でもジャンクション越しに作業データの中なら断る(リンクを解いたパスでも比べる。fsio.is_inside。2026-10-09)。
        見かけで重なる指定は今までどおり断る・重ならない指定は通る"""
        try:
            import _winapi
            link = os.path.join(self.tmp, "見かけは外")
            _winapi.CreateJunction(os.path.join(self.src, "studio"), link)
        except (ImportError, AttributeError, OSError):
            self.skipTest("ジャンクションを作れない")
        self.addCleanup(lambda: os.path.isdir(link) and os.rmdir(link))
        with self.assertRaisesRegex(ValueError, "作業データの中"):
            backup.run_once(self.src, link)
        self.assertFalse(os.path.exists(os.path.join(self.src, "studio", backup.DEST_NAME)))
        self.assertTrue(backup._overlaps(os.path.join(self.src, "x"), self.src))
        self.assertFalse(backup._overlaps(self.src + "2", self.src))   # 名前の頭だけ同じ別のフォルダは重ならない
        self.assertEqual(backup.run_once(self.src, self.dst)["copied"], 8)

    def test_state_file_roundtrip_and_broken(self):
        """最後に写した記録(backup-state.json): 1 行の JSON で原子的に書く・壊れた・大きすぎる・dict でない記録は「記録なし」"""
        b, _ = self.make(lambda: 5.0)
        b.last = {"ok": 5.0, "folder": "D:/バックアップ"}
        b._save_state()
        self.assertEqual(read(b.state_path), '{"ok": 5.0, "folder": "D:/バックアップ"}')
        self.assertEqual(sorted(os.listdir(os.path.dirname(b.state_path))), [backup.STATE_FILE])   # 一時ファイルを残さない
        self.assertEqual(b._load_state(), b.last)
        for bad in ("{壊れた", "[1]", '{"x": "%s"}' % ("y" * backup.STATE_MAX)):
            put(b.state_path, bad)
            self.assertEqual(b._load_state(), {}, bad[:20])

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
        self.assertEqual((r["copied"], b.state), (8, "idle"))
        s = b.snapshot()
        self.assertEqual((s["lastOk"], s["copied"], s["stateLabel"], s["folder"]), (1000000000, 8, "動いています", self.dst))
        self.assertTrue(any("8 個を写しました" in m for m in logs))
        now[0] += 3600
        self.assertIsNone(b.tick())               # まだ時間が来ていない
        b.run_now()
        self.assertEqual(b.tick()["copied"], 0)   # 「今すぐ」は時間によらない
        now[0] += 24 * 3600
        self.assertEqual(b.tick()["same"], 8)
        # 起動し直しても、最後に写した時刻を覚えている
        b2, _ = self.make(lambda: now[0] + 60)
        self.assertIsNone(b2.tick())
        self.assertEqual(json.loads(read(b.state_path))["copied"], 0)
        # 写す先を変えたら、時間によらず写す
        other = os.path.join(self.tmp, "別の先")
        self.prefs.patch("backup", {"folder": other})
        self.assertEqual(b2.tick()["copied"], 8)

    def test_tick_reports_bad_place_and_inplace(self):
        b, _ = self.make(lambda: 5.0)
        self.prefs.patch("backup", {"enabled": True, "folder": os.path.join(self.src, "x")})
        self.assertIsNone(b.tick())
        self.assertEqual(b.state, "error")
        self.assertIn("作業データの中", b.snapshot()["message"])
        b.source = None   # YTT_DATA_DIR=inplace(テスト・以前の形)では写さない
        b.tick()
        self.assertEqual(b.state, "off")

    def test_cfg_falls_back_to_given_defaults(self):
        """設定が読めないときの既定は入口が渡す(backup は prefs を読み込まない。RS3-0B)"""
        class Broken:
            def get(self, sections):
                raise OSError("読めない")
        d = prefs_mod.DEFAULTS["backup"]
        b = backup.Backup(Broken(), self.src, os.path.join(self.tmp, "app"), defaults=d)
        self.assertEqual(b._cfg(), d)
        self.assertIsNot(b._cfg(), d)    # 呼ぶ側が書き換えても既定は変わらない
        self.assertEqual(backup.Backup(Broken(), self.src, os.path.join(self.tmp, "app"))._cfg(), {})   # 渡さなければ空 = オフ扱い

    def timed(self, t0):
        """テストの時計(t0 から)で Backup を作り、24 時間ごとでオンにする"""
        self.prefs = prefs_mod.Prefs(os.path.join(self.tmp, "app", "prefs.json"), fsio.atomic_write)
        self.now = [t0]
        b = backup.Backup(self.prefs, self.src, os.path.join(self.tmp, "app"), clock=lambda: self.now[0])
        self.prefs.patch("backup", {"enabled": True, "folder": self.dst, "everyHours": 24})
        return b

    def test_changes_wait_for_the_interval(self):
        """変わっても間隔(24 時間)までは写さない(10-14 に「変わったらすぐ写す」をやめた)。「今すぐ」は写す"""
        b = self.timed(2000000000.0)
        self.assertEqual(b.tick()["copied"], 8)
        self.now[0] += 600
        put(os.path.join(self.src, "transcribe", "transcripts", "a.json"), "校正 2 長くした")
        self.assertIsNone(b.tick())
        b.run_now()
        self.assertEqual(b.tick()["copied"], 1)

    def test_copy_failure_is_partial_and_retried_after_retry_sec(self):
        """写せないファイルがあれば完全に写せたにしない(ok を進めない)。RETRY_SEC のあとでもう一度"""
        b = self.timed(2000000000.0)
        old = backup.copy_one

        def broken(src, dst, day):
            if os.path.basename(src) == "a.json":
                raise PermissionError(13, "使用中")
            return old(src, dst, day)

        backup.copy_one = broken
        self.addCleanup(setattr, backup, "copy_one", old)
        r = b.tick()
        self.assertEqual((len(r["errors"]), r["complete"], b.last["ok"], b.last["partial"]), (1, False, None, True))
        self.assertIn("写せなかったファイルが 1 個", b.message)
        self.assertTrue(b.snapshot()["partial"])
        self.now[0] += 600
        self.assertIsNone(b.tick())                       # すぐには歩き直さない
        backup.copy_one = old                             # 使用中でなくなった
        self.now[0] += backup.RETRY_SEC
        r = b.tick()
        self.assertEqual((r["copied"], r["errors"], r["complete"], b.last["ok"], b.last["partial"]), (1, [], True, self.now[0], False))

    def test_unreadable_folder_is_not_success_and_is_retried(self):
        """読めないフォルダがあっても読める物は写し、完全に写せたにしない(部品 M3)。読めるようになったら、古い更新時刻の物も写す"""
        b = self.timed(2000000000.0)
        studio = os.path.join(self.src, "studio")
        for d, _, ns in os.walk(studio):
            for n in ns:
                os.utime(os.path.join(d, n), (1000, 1000))   # 更新時刻がずっと前でも
        real = os.scandir

        def scandir(path):
            if os.path.normcase(os.path.abspath(path)) == os.path.normcase(studio):
                raise PermissionError(13, "アクセスが拒否されました")
            return real(path)

        backup.os.scandir = scandir
        self.addCleanup(setattr, backup.os, "scandir", real)
        r = b.tick()
        self.assertEqual((r["complete"], r["scanFailed"], r["errors"]), (False, 1, []))
        self.assertIn("読めないフォルダ: studio", r["scanErrors"][0])
        self.assertEqual(r["copied"], 6)                  # 読める物は写した(studio の 2 つ以外)
        self.assertIsNone(b.last["ok"])
        self.assertIn("読めなかったフォルダ・ファイルが 1 個", b.message)
        backup.os.scandir = real
        self.now[0] += backup.RETRY_SEC
        r = b.tick()
        self.assertEqual((r["copied"], r["complete"]), (2, True))
        self.assertTrue(os.path.isfile(os.path.join(self.dst, backup.DEST_NAME, "studio", "data.json")))

    def test_skips_analytics_build_cache_and_tmp(self):
        put(os.path.join(self.src, "analytics", "state.json"), "{}")
        put(os.path.join(self.src, "app", "friend-build-cache", "python.zip"), "zip")
        put(os.path.join(self.src, "transcribe", "transcripts", ".tmp", "x.json"), "{}")
        put(os.path.join(self.src, "studio", "analytics", "keep.json"), "{}")   # 直下でなければ名前で除かない
        names = [rel.replace("\\", "/") for rel, _, _ in backup.plan(self.src)]
        self.assertFalse([n for n in names if n.startswith("analytics/") or "friend-build-cache" in n or "/.tmp/" in n])
        self.assertIn("studio/analytics/keep.json", names)

    def test_names_come_from_their_owners(self):
        """写しの名前は持ち主(② placement・ytt names・docloc)から読む(名前を変えたときに写し漏れが黙って起きない)"""
        from flow import placement
        from ytt import docloc, names
        self.assertEqual(backup.REQUEST_DIR, placement.REQUEST_DIR)
        self.assertEqual(backup.CASE_STUDIO_ID, names.OWNER_FILE)
        self.assertEqual(set(backup.CASE_SUBDIRS), {placement.RUNS_DIR.lower(), docloc.HIST_DIR.lower(), docloc.BAK_DIR.lower()})

    def make_media(self):
        """評価用データと、その隣の 学習用データ(作業データの外)"""
        base = os.path.join(self.tmp, "素材")
        ev, lr = os.path.join(base, "評価用データ"), os.path.join(base, backup.LEARN_NAME)
        put(os.path.join(ev, "配信A", "a.mp4"), "video-a")
        put(os.path.join(ev, "配信A", "作業用", "a.clip.json"), "{}")
        put(os.path.join(ev, "配信A", "cache", "x.bin"), "c")       # キャッシュは写さない
        put(os.path.join(lr, "b.mp4"), "video-b")
        put(os.path.join(lr, "b.mp4.part-1"), "half")
        return ev, lr

    def test_media_dirs_are_copied_and_restored_to_the_same_place(self):
        ev, lr = self.make_media()
        r = backup.run_once(self.src, self.dst, media_dirs=[ev, lr])
        self.assertEqual((r["copied"], r["complete"], r["errors"], r["scanErrors"]), (8 + 3, True, [], []))
        media = [f for f in self.files() if f.startswith(backup.MEDIA_DIR + "/")]
        rel_ev = backup.media_rel(ev).replace("\\", "/")
        self.assertIn(rel_ev + "/配信A/a.mp4", media)
        self.assertIn(rel_ev + "/配信A/作業用/a.clip.json", media)
        self.assertEqual(len(media), 3)
        self.assertEqual(backup.run_once(self.src, self.dst, media_dirs=[ev, lr])["copied"], 0)   # 動画は変わらないので 2 回目は写さない
        # 写し戻し: 元の場所へ。既にあるファイルは上書きしない・作業データの根へは media を戻さない
        os.remove(os.path.join(ev, "配信A", "a.mp4"))
        put(os.path.join(lr, "b.mp4"), "直した")
        os.utime(os.path.join(lr, "b.mp4"), (1, 1))
        tgt = os.path.join(self.tmp, "restored")
        r = backup.restore_once(self.dst, tgt)
        self.assertEqual((r["mediaCopied"], r["mediaKept"], r["mediaSame"]), (1, 1, 1))
        self.assertEqual(read(os.path.join(ev, "配信A", "a.mp4")), "video-a")
        self.assertEqual(read(os.path.join(lr, "b.mp4")), "直した")
        self.assertFalse(os.path.exists(os.path.join(tgt, backup.MEDIA_DIR)))
        self.assertEqual(backup.restore_once(self.dst, tgt, media=False)["mediaCopied"], 0)

    def test_media_dir_inside_data_or_dest_is_ignored(self):
        r = backup.run_once(self.src, self.dst, media_dirs=[os.path.join(self.src, "studio"), self.dst, "相対"])
        self.assertFalse([f for f in self.files() if f.startswith(backup.MEDIA_DIR + "/")])
        self.assertTrue(r["complete"])

    def test_default_media_dirs_follow_eval_dirs_and_switch(self):
        ev, lr = self.make_media()
        old = backup.settings.eval_dirs
        backup.settings.eval_dirs = lambda: [ev]
        self.addCleanup(setattr, backup.settings, "eval_dirs", old)
        self.assertEqual(backup.default_media_dirs(), [os.path.abspath(ev), os.path.abspath(lr)])
        backup.COPY_MEDIA = False
        self.addCleanup(setattr, backup, "COPY_MEDIA", True)
        self.assertEqual(backup.default_media_dirs(), [])

    def test_restore_skips_what_backup_would_not_copy(self):
        """以前の決まりで写った物(app/intake の動画・analytics・ログ)は写し戻さない(6c-1)"""
        backup.run_once(self.src, self.dst)
        d = os.path.join(self.dst, backup.DEST_NAME)
        put(os.path.join(d, "app", "intake", "2026-10-04", "x.mp4"), "video")
        put(os.path.join(d, "analytics", "state.json"), "{}")
        put(os.path.join(d, "app", "logs", "launcher.log"), "log")
        tgt = os.path.join(self.tmp, "restored")
        r = backup.restore_once(self.dst, tgt)
        self.assertEqual((r["copied"], r["errors"]), (8, []))
        for p in (("app", "intake"), ("analytics",), ("app", "logs")):
            self.assertFalse(os.path.exists(os.path.join(tgt, *p)), p)

    def test_whisper_bin_only_and_no_eval_audio(self):
        names = [rel.replace("\\", "/") for rel, _, _ in backup.plan(self.src)]
        self.assertIn("transcribe/bin/whisper.cpp-v1-vulkan/whisper-cli.exe", names)
        self.assertIn("transcribe/bin/whisper.cpp-v1-vulkan/build/bin/x.dll", names)
        self.assertNotIn("transcribe/eval-audio/a.flac", names)
        self.assertFalse([n for n in names if n.startswith("transcribe/bin/") and "whisper.cpp-" not in n])
        self.assertFalse([n for n in names if "/models/" in n or n.startswith("studio/bin/")])

    def make_cases(self):
        out = os.path.join(self.tmp, "出力")   # 作業データの根の外
        w = os.path.join(out, "題名A", "作業用")
        put(os.path.join(w, "a.clip.json"), "{}")
        put(os.path.join(w, "a.edit.json"), "{}")
        put(os.path.join(w, "a.tx.key.json"), "{}")
        put(os.path.join(w, ".studio-id"), "id1")
        put(os.path.join(w, "runs", "r1.json"), "{}")
        put(os.path.join(w, ".hist", "0123456789ab", "1700000000000.json"), "{}")   # 文書の履歴(RS8 B2-0)
        put(os.path.join(w, ".bak", "0123456789ab.pre-fill.json"), "{}")            # 機械の書き換え前の控え
        put(os.path.join(w, ".hist", "0123456789ab", "deep", "x.json"), "{}")       # .hist/<tid> の下には入らない
        put(os.path.join(w, ".bak", "sub", "x.json"), "{}")                         # .bak の下には入らない
        put(os.path.join(w, "a.wav"), "audio")                    # json 以外は写さない
        put(os.path.join(w, "tmp", "x.json"), "{}")               # runs・.hist・.bak 以外の下は入らない
        put(os.path.join(w, "速報版", "x.json"), "{}")
        put(os.path.join(w, ".tmp", "x.json"), "{}")
        put(os.path.join(w, ".resume", "x.json"), "{}")
        put(os.path.join(w, "runs", "r1.json.part-1"), "{}")       # 途中のファイルは写さない
        put(os.path.join(out, "題名A", "a.mp4"), "video")
        put(os.path.join(out, "題名A", "a_edit.mp4"), "video")
        put(os.path.join(out, "題名A", "a_pack", "p.json"), "{}")
        put(os.path.join(out, "top.json"), "{}")
        return out

    def test_cases_work_dir_outside_data_root_is_copied(self):
        out = self.make_cases()
        r = backup.run_once(self.src, self.dst, out_dir=out)
        cases = [f for f in self.files() if f.startswith("cases/")]
        self.assertEqual(cases, ["cases/題名A/作業用/.bak/0123456789ab.pre-fill.json", "cases/題名A/作業用/.hist/0123456789ab/1700000000000.json",
                                 "cases/題名A/作業用/.studio-id", "cases/題名A/作業用/a.clip.json", "cases/題名A/作業用/a.edit.json",
                                 "cases/題名A/作業用/a.tx.key.json", "cases/題名A/作業用/runs/r1.json"])
        self.assertEqual((r["copied"], r["errors"]), (8 + 7, []))
        self.assertEqual(backup.run_once(self.src, self.dst, out_dir=out)["copied"], 0)
        self.assertEqual(backup.run_once(self.src, self.dst, out_dir=os.path.join(self.tmp, "無い"))["errors"], [])   # 無い outDir は何もしない
        self.assertEqual(backup.run_once(self.src, self.dst)["copied"], 0)

    def test_request_cases_are_copied_and_intake_videos_are_not(self):
        """依頼/<日付>_<題>_<id6>/作業用 の json は案件として写す。app/intake の動画は写さない(RS8 B3-7。(r8h))"""
        out = os.path.join(self.tmp, "出力")
        put(os.path.join(out, "依頼", "2026-10-11_題_abc123", "作業用", "case.json"), "{}")
        put(os.path.join(out, "依頼", "2026-10-11_題_abc123", "v.mp4"), "video")
        put(os.path.join(self.src, "app", "intake", "2026-10-11", "x.mp4"), "video")
        put(os.path.join(self.src, "app", "intake", "2026-10-11", "20261011-101500-abc123", "y.mp4"), "video")
        r = backup.run_once(self.src, self.dst, out_dir=out)
        self.assertEqual(r["errors"], [])
        files = self.files()
        self.assertIn("cases/依頼/2026-10-11_題_abc123/作業用/case.json", files)
        self.assertEqual([f for f in files if f.endswith(".mp4")], [])


    def test_restore_cases_to_out_dir(self):
        out = self.make_cases()
        backup.run_once(self.src, self.dst, out_dir=out)
        new_out = os.path.join(self.tmp, "新しい出力")
        tgt = os.path.join(self.tmp, "restored")
        r = backup.restore_once(self.dst, tgt, dry_run=True, out_dir=new_out)
        self.assertEqual((r["casesCopied"], r["casesKept"], r["outDir"]), (7, 0, os.path.abspath(new_out)))
        self.assertFalse(os.path.exists(new_out))                 # dry_run は書かない
        r = backup.restore_once(self.dst, tgt, out_dir=new_out)
        self.assertEqual((r["casesCopied"], r["errors"]), (7, []))
        got = sorted(rel.replace("\\", "/") for rel, _, _ in backup.plan_cases(new_out))
        self.assertEqual(got, sorted(rel.replace("\\", "/") for rel, _, _ in backup.plan_cases(out)))
        self.assertFalse(os.path.exists(os.path.join(tgt, backup.CASES_DIR)))   # 作業データの根へは cases を戻さない
        # 既にあるファイルは、中身が違っても(バックアップのほうが新しくても)上書きしない
        e = os.path.join(new_out, "題名A", "作業用", "a.edit.json")
        put(e, "人が直した")
        os.utime(e, (1, 1))
        r = backup.restore_once(self.dst, tgt, out_dir=new_out)
        self.assertEqual((r["casesCopied"], r["casesKept"], r["casesSame"]), (0, 1, 6))
        self.assertEqual(read(e), "人が直した")

    def test_restore_without_out_dir_skips_cases(self):
        out = self.make_cases()
        backup.run_once(self.src, self.dst, out_dir=out)
        tgt = os.path.join(self.tmp, "restored")
        r = backup.restore_once(self.dst, tgt)
        self.assertEqual((r["casesCopied"], r["casesSkipped"], r["outDir"]), (0, 7, None))
        self.assertFalse(os.path.exists(os.path.join(tgt, backup.CASES_DIR)))
        with self.assertRaises(ValueError):
            backup.restore_once(self.dst, tgt, out_dir="相対")
        with self.assertRaises(ValueError):                       # バックアップの中は断る
            backup.restore_once(self.dst, tgt, out_dir=os.path.join(self.dst, backup.DEST_NAME, "cases"))

    def test_restore_cli_cases(self):
        out = self.make_cases()
        backup.run_once(self.src, self.dst, out_dir=out)
        buf = io.StringIO()
        tgt = os.path.join(self.tmp, "restored")
        new_out = os.path.join(self.tmp, "新しい出力")
        with contextlib.redirect_stdout(buf):
            self.assertEqual(backup.main(["--restore", self.dst, "--target", tgt, "--out-dir", new_out, "--yes"]), 0)
        self.assertTrue(os.path.isfile(os.path.join(new_out, "題名A", "作業用", ".hist", "0123456789ab", "1700000000000.json")))
        # 既定の案件の根 = 写し戻した先(無ければバックアップ)のスタジオの設定の outDir
        put(os.path.join(self.src, "studio", "settings.json"), json.dumps({"outDir": os.path.join(self.tmp, "設定の出力")}))
        backup.run_once(self.src, self.dst, out_dir=out)
        tgt2 = os.path.join(self.tmp, "restored2")
        with contextlib.redirect_stdout(buf):
            self.assertEqual(backup.main(["--restore", self.dst, "--target", tgt2, "--yes"]), 0)
        self.assertTrue(os.path.isfile(os.path.join(self.tmp, "設定の出力", "題名A", "作業用", "a.edit.json")))
        with contextlib.redirect_stdout(buf):                      # --out-dir の指定が正しくなければ断る
            self.assertEqual(backup.main(["--restore", self.dst, "--target", tgt2, "--out-dir", "相対", "--yes"]), 2)

    def test_backup_passes_out_dir_by_value_or_function(self):
        out = self.make_cases()
        b, _ = self.make(lambda: 1000.0)
        self.assertIsNone(b._out_dir())
        b.out_dir = lambda: out
        self.assertEqual(b._out_dir(), out)
        b.out_dir = "相対"
        self.assertIsNone(b._out_dir())

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


if __name__ == "__main__":
    unittest.main()
