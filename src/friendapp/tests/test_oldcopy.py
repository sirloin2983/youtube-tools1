"""src/friendapp/oldcopy.py のテスト。リポジトリ直下で: py -3.12 -m unittest src/friendapp/tests/test_oldcopy.py"""
import hashlib
import json
import os
import shutil
import subprocess
import sys
import unittest

os.environ.setdefault("YTT_DATA_DIR", "inplace")
SRC = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if SRC not in sys.path:
    sys.path.insert(0, SRC)
from ytt import testkit  # noqa: E402
from friendapp import oldcopy  # noqa: E402


def _sha(data):
    return hashlib.sha256(data).hexdigest()


def _file_sha(path):
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


class OldCopyTest(unittest.TestCase):
    def setUp(self):
        self.tmp = testkit.tempdir(self, "oldcopy-")
        self.old = os.path.join(self.tmp, "old")
        self.new = os.path.join(self.tmp, "new")
        self.catalog = os.path.join(self.tmp, "state", "catalog.json")
        self.fetch = os.path.join(self.tmp, "fetch.json")
        os.makedirs(self.old)
        os.makedirs(self.new)

    def put(self, root, rel, data):
        path = os.path.join(root, *rel.split("/"))
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as f:
            f.write(data)
        return path

    def row(self, dest, file_, data, **extra):
        r = {"name": file_, "file": file_, "url": "https://example.invalid/" + file_, "size": len(data),
             "sha256": _sha(data), "base": "data", "dest": dest, "unzip": None}
        r.update(extra)
        return r

    def write_fetch(self, rows):
        testkit.write_json(self.fetch, {"version": "t", "items": rows})

    def migrate(self, **kw):
        return oldcopy.migrate(self.fetch, self.old, self.new, self.catalog, **kw)

    def test_copies_matching_and_deletes_old(self):
        data = b"model-bytes" * 100
        self.put(self.old, "transcribe/models/a.bin", data)
        self.write_fetch([self.row("transcribe/models", "a.bin", data)])
        r = self.migrate()
        self.assertEqual(r["copied"], 1)
        self.assertEqual(r["deleted"], 1)
        self.assertEqual(r["freed"], len(data))
        self.assertEqual(r["skipped"], [])
        new_path = os.path.join(self.new, "transcribe", "models", "a.bin")
        self.assertEqual(_file_sha(new_path), _sha(data))
        self.assertFalse(os.path.exists(os.path.join(self.old, "transcribe", "models", "a.bin")))

    def test_empty_folders_removed_root_kept(self):
        data = b"x" * 10
        self.put(self.old, "deep/er/x.bin", data)
        self.write_fetch([self.row("deep/er", "x.bin", data)])
        self.migrate()
        self.assertTrue(os.path.isdir(self.old))
        self.assertEqual(os.listdir(self.old), [])

    def test_hash_mismatch_keeps_old_and_skips(self):
        data = b"real-data"
        old_path = self.put(self.old, "m/a.bin", data)
        row = self.row("m", "a.bin", data)
        row["sha256"] = _sha(b"something else")
        self.write_fetch([row])
        r = self.migrate()
        self.assertEqual(r["copied"], 0)
        self.assertEqual(r["deleted"], 0)
        self.assertEqual(r["skipped"], [{"name": "a.bin", "reason": "hash-mismatch"}])
        self.assertTrue(os.path.exists(old_path))
        self.assertFalse(os.path.exists(os.path.join(self.new, "m", "a.bin")))

    def test_size_mismatch_not_planned(self):
        data = b"abc"
        old_path = self.put(self.old, "m/a.bin", data)
        row = self.row("m", "a.bin", data, size=999)
        self.write_fetch([row])
        r = self.migrate()
        self.assertEqual(r["copied"], 0)
        self.assertEqual(r["skipped"], [])
        self.assertTrue(os.path.exists(old_path))

    def test_unlisted_file_kept(self):
        data = b"listed"
        self.put(self.old, "m/a.bin", data)
        case_path = self.put(self.old, "case/project.json", b"{}")
        self.write_fetch([self.row("m", "a.bin", data)])
        self.migrate()
        self.assertTrue(os.path.exists(case_path))

    def test_unzip_and_app_rows_ignored(self):
        data = b"zipped"
        old_path = self.put(self.old, "m/z.zip", data)
        app_path = self.put(self.old, "m/app.bin", data)
        rows = [self.row("m", "z.zip", data, unzip="zip"), self.row("m", "app.bin", data, base="app")]
        self.write_fetch(rows)
        r = self.migrate()
        self.assertEqual(r["copied"], 0)
        self.assertTrue(os.path.exists(old_path))
        self.assertTrue(os.path.exists(app_path))

    def test_bad_rows_dropped(self):
        data = b"d"
        good = self.row("transcribe/models", "ok.bin", data)
        bad_dests = ["/abs/x", "C:x/y", "../x", "a/../b", "", "a//b", "a\\b", "a/./b"]
        rows = [good] + [self.row(d, "bad.bin", data) for d in bad_dests]
        rows.append(self.row("m", "x/y.bin", data))
        rows.append(self.row("m", "bad_sha.bin", data, sha256="zz"))
        rows.append(self.row("m", "bad_base.bin", data, base="other"))
        self.write_fetch(rows)
        items = oldcopy.load_items(self.fetch)
        self.assertEqual([i["name"] for i in items], ["ok.bin"])

    def test_bad_fetch_json_gives_nothing(self):
        with open(self.fetch, "w", encoding="utf-8") as f:
            f.write("{ not json")
        self.assertEqual(oldcopy.load_items(self.fetch), [])
        r = self.migrate()
        self.assertEqual((r["copied"], r["deleted"], r["skipped"]), (0, 0, []))

    def test_second_run_does_nothing(self):
        data = b"again"
        self.put(self.old, "m/a.bin", data)
        self.write_fetch([self.row("m", "a.bin", data)])
        self.migrate()
        r = self.migrate()
        self.assertEqual((r["copied"], r["deleted"], r["skipped"]), (0, 0, []))

    def test_broken_copy_leaves_no_part_file(self):
        data = b"will break"
        old_path = self.put(self.old, "m/a.bin", data)
        self.write_fetch([self.row("m", "a.bin", data)])

        def hasher(path):
            if path.endswith(".part"):
                return "0" * 64
            return _file_sha(path)

        r = self.migrate(hasher=hasher)
        self.assertEqual(r["copied"], 0)
        self.assertEqual(r["skipped"], [{"name": "a.bin", "reason": "copy-mismatch"}])
        self.assertTrue(os.path.exists(old_path))
        self.assertFalse(os.path.exists(os.path.join(self.new, "m", "a.bin")))
        self.assertFalse(os.path.exists(os.path.join(self.new, "m", "a.bin.part")))

    def test_cancel_stops_midway(self):
        a, b = b"first-file", b"second-file"
        a_old = self.put(self.old, "m/a.bin", a)
        b_old = self.put(self.old, "m/b.bin", b)
        self.write_fetch([self.row("m", "a.bin", a), self.row("m", "b.bin", b)])
        calls = []

        def cancelled():
            calls.append(1)
            return len(calls) > 1

        r = self.migrate(cancelled=cancelled)
        self.assertEqual(r["copied"], 1)
        self.assertEqual(r["deleted"], 1)
        self.assertFalse(os.path.exists(a_old))
        self.assertTrue(os.path.exists(b_old))
        self.assertFalse(os.path.exists(os.path.join(self.new, "m", "b.bin")))

    def test_notice_shown_once(self):
        data = b"notice-data" * 5
        self.put(self.old, "m/a.bin", data)
        self.write_fetch([self.row("m", "a.bin", data)])
        self.assertIsNone(oldcopy.notice(self.catalog))
        self.migrate()
        self.assertEqual(oldcopy.notice(self.catalog), {"bytes": len(data)})
        oldcopy.mark_notice_shown(self.catalog)
        self.assertIsNone(oldcopy.notice(self.catalog))
        self.migrate()
        self.assertIsNone(oldcopy.notice(self.catalog))

    def test_same_root_does_nothing(self):
        data = b"same"
        old_path = self.put(self.old, "m/a.bin", data)
        self.write_fetch([self.row("m", "a.bin", data)])
        r = oldcopy.migrate(self.fetch, self.old, self.old, self.catalog)
        self.assertEqual((r["copied"], r["deleted"], r["skipped"]), (0, 0, []))
        self.assertTrue(os.path.exists(old_path))
        self.assertFalse(os.path.exists(self.catalog))
        # ---- test_nested_root_does_nothing
        data = b"nested"
        old_path = self.put(self.old, "m/a.bin", data)
        inner = os.path.join(self.old, "sub")
        os.makedirs(inner)
        self.write_fetch([self.row("m", "a.bin", data)])
        r = oldcopy.migrate(self.fetch, self.old, inner, self.catalog)
        self.assertEqual((r["copied"], r["deleted"]), (0, 0))
        self.assertTrue(os.path.exists(old_path))
        self.assertFalse(os.path.exists(self.catalog))

    def test_size_null_uses_max_bytes(self):
        ok = b"0123456789" * 5          # 50 バイト
        rows = [
            self.row("m", "ok.bin", ok, size=None, maxBytes=100),
            self.row("m", "too_big.bin", ok, size=None, maxBytes=10),
            self.row("m", "no_limit.bin", ok, size=None),
            self.row("m", "empty.bin", b"", size=None, maxBytes=100),
        ]
        for r in rows:
            self.put(self.old, "m/" + r["file"], ok if r["file"] != "empty.bin" else b"")
        self.write_fetch(rows)
        r = self.migrate()
        self.assertEqual(r["copied"], 1)
        self.assertTrue(os.path.exists(os.path.join(self.old, "m", "too_big.bin")))
        self.assertTrue(os.path.exists(os.path.join(self.old, "m", "no_limit.bin")))
        self.assertTrue(os.path.exists(os.path.join(self.old, "m", "empty.bin")))
        self.assertFalse(os.path.exists(os.path.join(self.old, "m", "ok.bin")))

    def test_existing_new_file_not_touched(self):
        data = b"old-side"
        old_path = self.put(self.old, "m/a.bin", data)
        new_path = self.put(self.new, "m/a.bin", b"new-side-already")
        self.write_fetch([self.row("m", "a.bin", data)])
        r = self.migrate()
        self.assertEqual(r["copied"], 0)
        self.assertTrue(os.path.exists(old_path))
        with open(new_path, "rb") as f:
            self.assertEqual(f.read(), b"new-side-already")

    def test_plan_shape(self):
        data = b"planned"
        old_path = self.put(self.old, "m/a.bin", data)
        items = [{"name": "a.bin", "file": "a.bin", "dest": "m", "size": len(data), "maxBytes": None, "sha256": _sha(data)}]
        got = oldcopy.plan(items, self.old, self.new)
        self.assertEqual(got, [{"name": "a.bin", "old": old_path,
                                "new": os.path.join(self.new, "m", "a.bin"),
                                "size": len(data), "sha256": _sha(data)}])
        self.assertEqual(oldcopy.plan(items, self.old, self.old), [])


    def test_pending_clean_skip_only_catalog_files(self):
        data = b"model-bytes" * 10
        old_path = self.put(self.old, "m/a.bin", data)
        other = self.put(self.old, "cases/mine.txt", b"case")
        self.write_fetch([self.row("m", "a.bin", data)])
        self.migrate(remove_old=False)
        self.assertTrue(os.path.isfile(old_path))
        self.assertEqual(oldcopy.pending(self.catalog, self.old), {"bytes": len(data), "count": 1, "asked": False})
        oldcopy.skip(self.catalog)
        self.assertTrue(oldcopy.pending(self.catalog, self.old)["asked"])
        got = oldcopy.clean(self.catalog, self.old)
        self.assertEqual(got, {"deleted": 1, "freed": len(data)})
        self.assertFalse(os.path.exists(old_path))
        self.assertTrue(os.path.isfile(other))
        self.assertEqual(oldcopy.pending(self.catalog, self.old)["count"], 0)

    def test_pending_without_catalog_and_changed_old(self):
        self.assertEqual(oldcopy.pending(self.catalog, self.old), {"bytes": 0, "count": 0, "asked": False})
        oldcopy.skip(self.catalog)   # 目録が無ければ何もしない
        self.assertFalse(os.path.exists(self.catalog))
        data = b"abc" * 50
        old_path = self.put(self.old, "m/a.bin", data)
        self.write_fetch([self.row("m", "a.bin", data)])
        self.migrate(remove_old=False)
        with open(old_path, "ab") as f:
            f.write(b"x")
        self.assertEqual(oldcopy.pending(self.catalog, self.old)["bytes"], 0)
        self.assertEqual(oldcopy.clean(self.catalog, self.old)["deleted"], 0)
        self.assertTrue(os.path.isfile(old_path))


class HomeCleanTest(unittest.TestCase):
    """アプリのフォルダ(home の直下)に残った前のアプリの物の片付け。一覧の名前だけ消す。"""
    KEEP = ("config.json", "keys.json", "FriendApp.exe", "app-0.1.0/app.dll", "python/python.exe", "src/a.py",
            "tools/ffmpeg.exe", "data/x.txt", "作業/a.txt", "fetch.json", "members.json", "FriendApp-はじめに.txt")
    OLD = ("RequestSender.exe", "README.txt", "guide.html", "friend-defaults.json",
           "settings.json", "update.cmd", "new/a.bin", "update-download/b.zip")

    def setUp(self):
        self.tmp = testkit.tempdir(self, "homeclean-")
        self.home = os.path.join(self.tmp, "FriendApp")
        self.catalog = os.path.join(self.tmp, "state", "catalog.json")
        for rel in self.KEEP + self.OLD:
            path = os.path.join(self.home, *rel.split("/"))
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "wb") as f:
                f.write(b"0123456789")   # 10 バイトずつ
        # 家の外の同名の物は触らない
        with open(os.path.join(self.tmp, "RequestSender.exe"), "wb") as f:
            f.write(b"outside")

    def exists(self, rel):
        return os.path.exists(os.path.join(self.home, *rel.split("/")))

    def test_only_listed_names_removed(self):
        self.assertEqual(oldcopy.home_pending(self.home), {"bytes": 80, "count": 8})
        got = oldcopy.clean_home(self.home)
        self.assertEqual(got, {"deleted": 8, "freed": 80, "skipped": []})
        for rel in self.OLD:
            self.assertFalse(self.exists(rel), rel)
        for rel in self.KEEP:
            self.assertTrue(self.exists(rel), rel)
        self.assertTrue(os.path.isfile(os.path.join(self.tmp, "RequestSender.exe")))   # 外へ出ない
        self.assertEqual(oldcopy.home_pending(self.home), {"bytes": 0, "count": 0})

    def test_locked_file_is_skipped_and_rest_goes_on(self):
        def remove(path):
            if os.path.basename(path) in ("RequestSender.exe", "a.bin"):
                raise PermissionError(13, "使用中")
            os.remove(path)
        logs = []
        got = oldcopy.clean_home(self.home, log=logs.append, remove=remove)
        self.assertEqual(got, {"deleted": 6, "freed": 60, "skipped": ["RequestSender.exe", "new"]})
        self.assertTrue(self.exists("RequestSender.exe"))
        self.assertTrue(self.exists("new/a.bin"))                  # フォルダの中に残った物があるので new は残す
        self.assertFalse(self.exists("README.txt"))
        self.assertFalse(self.exists("update-download"))
        self.assertTrue(any("消せないので飛ばす: RequestSender.exe" in m for m in logs))

    def test_link_is_not_followed(self):
        target = os.path.join(self.tmp, "target")
        os.makedirs(target)
        with open(os.path.join(target, "keep.txt"), "wb") as f:
            f.write(b"keep")
        link = os.path.join(self.home, "update-download")
        shutil.rmtree(link)
        try:
            os.symlink(target, link, target_is_directory=True)
        except (OSError, NotImplementedError):
            # 権限が無い Windows では接合点(junction・管理者権限が要らない)で同じ形を作る。黒い窓は出さない
            flags = 0x08000000 if os.name == "nt" else 0   # CREATE_NO_WINDOW
            r = subprocess.run(["cmd", "/c", "mklink", "/J", link, target], capture_output=True, creationflags=flags)
            if r.returncode != 0:
                self.skipTest("リンクも接合点も作れない")
        got = oldcopy.clean_home(self.home)
        self.assertEqual(got["deleted"], 7)                                  # リンク以外の一覧の物は消す
        self.assertEqual(got["skipped"], [])                                 # リンクは一覧から外すだけ(飛ばしの記録にもしない)
        self.assertTrue(os.path.isfile(os.path.join(target, "keep.txt")))   # 辿らない
        self.assertTrue(oldcopy._is_link(link))                             # 残っている(リンクとして)

    def test_missing_home_does_nothing(self):
        self.assertEqual(oldcopy.home_pending(os.path.join(self.tmp, "none")), {"bytes": 0, "count": 0})
        self.assertEqual(oldcopy.clean_home(os.path.join(self.tmp, "none")), {"deleted": 0, "freed": 0, "skipped": []})

    def test_mark_asked_without_catalog(self):
        self.assertFalse(os.path.exists(self.catalog))
        oldcopy.mark_asked(self.catalog)
        self.assertTrue(oldcopy.pending(self.catalog, None)["asked"])


if __name__ == "__main__":
    unittest.main()
