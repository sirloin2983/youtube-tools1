"""src/friendapp/oldcopy.py のテスト。リポジトリ直下で: py -3.10 -m unittest src/friendapp/tests/test_oldcopy.py"""
import hashlib
import json
import os
import shutil
import sys
import tempfile
import unittest

os.environ.setdefault("YTT_DATA_DIR", "inplace")
SRC = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if SRC not in sys.path:
    sys.path.insert(0, SRC)
from friendapp import oldcopy  # noqa: E402


def _sha(data):
    return hashlib.sha256(data).hexdigest()


def _file_sha(path):
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


class OldCopyTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="oldcopy-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
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
        with open(self.fetch, "w", encoding="utf-8") as f:
            json.dump({"version": "t", "items": rows}, f)

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

    def test_nested_root_does_nothing(self):
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


if __name__ == "__main__":
    unittest.main()
