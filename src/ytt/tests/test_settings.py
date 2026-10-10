"""ytt_core.settings(設定ファイルの共通部品。S4)のテスト。リポジトリ直下で:
    python -m unittest src/ytt/tests/test_settings.py
"""
import json
import os
import sys
import tempfile
import threading
import unittest
os.environ.setdefault("YTT_DATA_DIR", "inplace")   # 作業データを本物の置き場所に書かない(ytt/datadir。編集の設定の節は workdata を一時フォルダに差し替える)

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.dirname(os.path.dirname(HERE))
if SRC not in sys.path:
    sys.path.insert(0, SRC)
from ytt_core import settings as S  # noqa: E402


class TestSettingsFile(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="ytt-settings-")
        self.path = os.path.join(self.tmp, "sub", "settings.json")

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def raw(self):
        with open(self.path, "rb") as f:
            return f.read()

    def test_missing_is_empty_not_broken(self):
        sf = S.SettingsFile(self.path)
        self.assertEqual(sf.load(), ({}, False))
        self.assertEqual(sf.read(), {})
        d = sf.read(); d["x"] = 1
        self.assertEqual(sf.read(), {}, "read は毎回新しい dict")

    def test_set_section_writes_atomically_and_makes_folder(self):
        sf = S.SettingsFile(self.path)
        self.assertEqual(sf.set_section("review", {"volume": 70}), {"volume": 70})
        self.assertEqual(json.loads(self.raw().decode("utf-8")), {"review": {"volume": 70}})
        self.assertFalse(any(n.startswith(".") or n.endswith(".tmp") for n in os.listdir(os.path.dirname(self.path))), "一時ファイルを残さない")
        self.assertNotIn(b"\xef\xbb\xbf", self.raw()[:3], "BOM を書かない")
        sf.set_section("analyze", {"count": 8})
        self.assertEqual(sf.read(), {"review": {"volume": 70}, "analyze": {"count": 8}}, "別の節は消えない")

    def test_section_name_and_value_checks(self):
        sf = S.SettingsFile(self.path)
        for bad in ("", "1abc", "a" * 33, "a b", None, 3):
            with self.assertRaises(S.SettingsError, msg=repr(bad)):
                sf.set_section(bad, {})
        with self.assertRaises(S.SettingsError):
            sf.set_section("review", [1])
        self.assertTrue(S.section_name_ok("review-2_x"))

    def test_broken_file_reads_as_empty_and_is_retired_on_save(self):
        os.makedirs(os.path.dirname(self.path))
        with open(self.path, "wb") as f:
            f.write(b"{not json")
        sf = S.SettingsFile(self.path)
        self.assertEqual(sf.load(), ({}, True))
        sf.set_section("review", {"a": 1})
        names = sorted(os.listdir(os.path.dirname(self.path)))
        self.assertEqual(len(names), 2, names)
        self.assertTrue(any(".broken-" in n for n in names), "壊れたファイルは消さずに退避する: %s" % names)
        with open(os.path.join(os.path.dirname(self.path), [n for n in names if ".broken-" in n][0]), "rb") as f:
            self.assertEqual(f.read(), b"{not json")
        self.assertEqual(sf.read(), {"review": {"a": 1}})
        # 辞書でない JSON・BOM つきの辞書
        with open(self.path, "wb") as f:
            f.write(b"[1, 2]")
        self.assertEqual(sf.load(), ({}, True))
        with open(self.path, "wb") as f:
            f.write(b"\xef\xbb\xbf" + json.dumps({"k": "v"}).encode("utf-8"))
        self.assertEqual(sf.load(), ({"k": "v"}, False), "BOM があっても読む")

    def test_too_big_is_refused_without_touching_file(self):
        sf = S.SettingsFile(self.path, max_bytes=200)
        sf.set_section("a", {"x": 1})
        before = self.raw()
        with self.assertRaises(S.SettingsTooLarge):
            sf.set_section("b", {"y": "z" * 300})
        self.assertEqual(self.raw(), before)
        self.assertTrue(issubclass(S.SettingsTooLarge, S.SettingsError))
        # 読むときも上限: 大きいファイルは「壊れている」扱い
        with open(self.path, "wb") as f:
            f.write(json.dumps({"big": "z" * 300}).encode("utf-8"))
        self.assertEqual(sf.load(), ({}, True))

    def test_patch_section_uses_cleaner_and_keeps_other_keys(self):
        sf = S.SettingsFile(self.path)
        sf.set_section("autorun", {"top": 3, "mode": "full"})

        def cleaner(v, cur):
            out = dict(cur)
            if "top" in v:
                if not isinstance(v["top"], int) or not 1 <= v["top"] <= 20:
                    raise ValueError("採用数は 1〜20")
                out["top"] = v["top"]
            return out
        self.assertEqual(sf.patch_section("autorun", {"top": 5}, cleaner), {"top": 5, "mode": "full"})
        with self.assertRaises(ValueError):
            sf.patch_section("autorun", {"top": 99}, cleaner)
        self.assertEqual(sf.read()["autorun"], {"top": 5, "mode": "full"}, "検査に落ちたら書かない")
        with self.assertRaises(S.SettingsError):
            sf.patch_section("autorun", "x", cleaner)
        # current で「今の値」を決め直せる(保存してある値を検査し直して使うとき)
        self.assertEqual(sf.patch_section("autorun", {}, cleaner, current=lambda d: {"top": 1}), {"top": 1})

    def test_update_keys_and_merge_top(self):
        sf = S.SettingsFile(self.path)
        allow = {"packFps": lambda v: v in ("30", "60"), "packBackup": lambda v: isinstance(v, bool)}
        self.assertEqual(sf.update_keys({"packFps": "60"}, allow), {"packFps": "60"})
        for bad in ({}, {"packFps": "24"}, {"nope": 1}, "x"):
            with self.assertRaises(S.SettingsError, msg=repr(bad)):
                sf.update_keys(bad, allow)
        sf.merge_top({"glossary": "みこ", "old": None, "packFps": "30"}, skip=allow)
        self.assertEqual(sf.read(), {"packFps": "60", "glossary": "みこ"}, "skip の鍵は merge_top では変わらない・None は消す")
        sf.merge_top({"glossary": None})
        self.assertEqual(sf.read(), {"packFps": "60"})
        with self.assertRaises(S.SettingsError):
            sf.merge_top({"": 1})
        with self.assertRaises(S.SettingsError):
            sf.merge_top({"k" * 61: 1})
        with self.assertRaises(S.SettingsError):
            sf.merge_top({"k%d" % i: i for i in range(201)})

    def test_external_lock_and_threads(self):
        lock = threading.RLock()
        sf = S.SettingsFile(self.path, lock=lock)
        self.assertIs(sf.lock, lock)
        errs = []

        def worker(i):
            try:
                for j in range(20):
                    sf.set_section("s%d" % i, {"j": j})
            except Exception as e:   # noqa: BLE001
                errs.append(e)
        ts = [threading.Thread(target=worker, args=(i,)) for i in range(4)]
        for t in ts:
            t.start()
        for t in ts:
            t.join()
        self.assertEqual(errs, [])
        d = sf.read()
        self.assertEqual(sorted(d), ["s0", "s1", "s2", "s3"])
        self.assertTrue(all(v == {"j": 19} for v in d.values()), d)

    def test_custom_writer_and_indent(self):
        seen = []

        def writer(path, data):
            seen.append((path, data))
            with open(path, "wb") as f:
                f.write(data)
        sf = S.SettingsFile(self.path, writer=writer, indent=None)
        sf.set_section("a", {"x": 1})
        self.assertEqual(len(seen), 1)
        self.assertEqual(seen[0][1], b'{"a": {"x": 1}}', "indent=None は 1 行")


class TestEditorSettings(unittest.TestCase):
    """編集の設定の読み書き(RS3-1 に editor/ed_learn.py から移した)。置き場所は ytt/workdata.SETTINGS を呼ぶたびに読む・serve なしで動く"""

    def setUp(self):
        from unittest import mock
        from ytt import settings, workdata
        self.st, self.wd = settings, workdata
        self.tmp = tempfile.mkdtemp(prefix="ytt-edsettings-")
        self.path = os.path.join(self.tmp, "settings.json")
        p = mock.patch.object(workdata, "SETTINGS", self.path)
        p.start()
        self.addCleanup(p.stop)
        keys = dict(settings.SETTINGS_PATCH_KEYS)
        self.addCleanup(lambda: (settings.SETTINGS_PATCH_KEYS.clear(), settings.SETTINGS_PATCH_KEYS.update(keys)))

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_follows_workdata_and_patch_keys(self):
        from ytt import errors
        self.assertEqual(self.st.load_settings(), {})
        self.assertEqual(self.st.patch_settings({"values": {"packFps": "30"}}), {"ok": True, "values": {"packFps": "30"}})
        with self.assertRaises(errors.ApiError) as cm:
            self.st.patch_settings({"values": {"packFps": "31"}})
        self.assertEqual(cm.exception.status, 400)
        self.st.merge_settings({"patch": {"glossary": "みこ", "packFps": "60"}})   # 検査のある鍵は merge では変えない
        self.assertEqual(self.st.load_settings(), {"packFps": "30", "glossary": "みこ"})
        self.st.replace_settings({"other": 1, "packFps": "24"})                   # 丸ごとでも検査のある鍵はサーバーの値
        self.assertEqual(self.st.load_settings(), {"other": 1, "packFps": "30"})
        with open(self.path, encoding="utf-8") as f:
            self.assertEqual(json.load(f), {"other": 1, "packFps": "30"})

    def test_register_patch_key(self):
        from ytt import errors
        with self.assertRaises(errors.ApiError):
            self.st.patch_settings({"values": {"zzKey": 1}})   # 登録していない鍵は直せない
        self.st.register_patch_key("zzKey", lambda v: v == 1)
        self.assertEqual(self.st.patch_settings({"values": {"zzKey": 1}})["values"], {"zzKey": 1})
        with self.assertRaises(ValueError):
            self.st.register_patch_key("", lambda v: True)

    def test_eval_dirs(self):
        """評価用のフォルダの判定(RS3-1 に editor/ed_relink から)。設定 evalDirs を読む・あるフォルダだけ・作業データの中は使わない"""
        from unittest import mock
        from ytt import errors
        ev = os.path.join(self.tmp, "評価用データ")
        os.makedirs(ev)
        self.assertTrue(self.st._eval_dirs_ok([ev]))
        for bad in ("x", ["relative"], ["\\\\server\\share"], [ev] * 11):
            self.assertFalse(self.st._eval_dirs_ok(bad), bad)
        self.assertTrue(self.st.SETTINGS_PATCH_KEYS["evalDirs"]([ev]))
        self.assertEqual(self.st.eval_dirs(), [])
        with self.assertRaises(errors.ApiError) as cm:   # 設定が無いのに「評価用」のフォルダの動画 = 止める
            self.st.eval_name_guard(os.path.join(ev, "a.mp4"))
        self.assertEqual(cm.exception.code, "eval_dir_unset")
        self.st.eval_name_guard(os.path.join(ev, "a.mp4"), is_eval=True)   # 評価用として始めるなら通す
        self.st.patch_settings({"values": {"evalDirs": [ev, os.path.join(self.tmp, "無い")]}})
        with mock.patch.object(self.wd, "DATA_DIR", os.path.join(self.tmp, "data")):
            self.assertEqual(self.st.eval_dirs(), [os.path.abspath(ev)])   # 無いフォルダは除く
            self.assertTrue(self.st.in_eval_dir(os.path.join(ev, "a.mp4")))
            self.assertFalse(self.st.in_eval_dir(ev + "x" + os.sep + "a.mp4"))   # 名前が前で一致するだけの隣のフォルダは外
            self.assertFalse(self.st.in_eval_dir("relative.mp4"))
            self.st.eval_name_guard(os.path.join(ev, "a.mp4"))   # 設定があれば何もしない
        with mock.patch.object(self.wd, "DATA_DIR", ev):
            self.assertEqual(self.st.eval_dirs(), [])   # 作業データと重なるフォルダは使わない

    def test_too_big_is_413(self):
        from ytt import errors
        with self.assertRaises(errors.ApiError) as cm:
            self.st.merge_settings({"patch": {"big": "x" * (self.st.SETTINGS_MAX + 10)}})
        self.assertEqual(cm.exception.status, 413)


if __name__ == "__main__":
    unittest.main()
