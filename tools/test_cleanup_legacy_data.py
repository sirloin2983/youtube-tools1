#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tools/cleanup_legacy_data.py(以前の場所に残った作業データの片付け)のテスト。本物の AppData・ごみ箱は使わない。
実行(リポジトリ直下): python -m unittest tools/test_cleanup_legacy_data.py"""
import ast
import json
import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

os.environ.setdefault("YTT_DATA_DIR", "inplace")   # テストは作業データを本物の置き場所(AppData など)に書かない(ytt_core.datadir)
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
import cleanup_legacy_data as CL  # noqa: E402


def data_items_of(serve_path):
    """serve.py の DATA_ITEMS(import せずに読む)"""
    with open(serve_path, encoding="utf-8") as f:
        tree = ast.parse(f.read())
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and any(getattr(t, "id", None) == "DATA_ITEMS" for t in node.targets):
            return tuple(ast.literal_eval(node.value))
    return None


class TestCleanup(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.root = os.path.join(self.tmp, "repo")
        self.data = os.path.join(self.tmp, "data")
        self.env = {"YTT_DATA_DIR": self.data}
        self.trash = os.path.join(self.tmp, "trash")
        self.w(os.path.join(self.root, "clip-studio", "serve.py"), "code")             # コードは触らない
        self.w(os.path.join(self.root, "clip-studio", "data.json"), "{}")
        self.w(os.path.join(self.root, "clip-studio", "cache", "chat", "a.json"), "x" * 1000)
        self.w(os.path.join(self.root, "clip-studio", "studio.log"), "log")
        self.w(os.path.join(self.root, "transcribe-tool", "transcripts", "a.json"), "{}")
        self.w(os.path.join(self.root, "transcribe-tool", "serve.log"), "log")
        self.w(os.path.join(self.root, "app", "logs", "launcher.log"), "log")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    @staticmethod
    def w(path, text):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)

    def migrate(self, tool, folder, items):
        """移し済みの状態(新しい場所に同じ名前・.migrated.json)を作る"""
        for n in items:
            src, dst = os.path.join(self.root, folder, n), os.path.join(self.data, tool, n)
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            shutil.copytree(src, dst) if os.path.isdir(src) else shutil.copy(src, dst)
        os.makedirs(os.path.join(self.data, tool), exist_ok=True)
        with open(os.path.join(self.data, tool, ".migrated.json"), "w", encoding="utf-8") as f:
            json.dump({"from": os.path.join(self.root, folder), "items": list(items)}, f)

    def run_main(self, *args, answer="y"):
        with mock.patch.object(CL, "running_tools", return_value=[]):
            return CL.main(list(args), root=self.root, env=self.env, ask=lambda _: answer, trash_dir=self.trash)

    def test_lists_match_each_serve(self):
        """片付ける一覧は、各ツールの serve.py の DATA_ITEMS(写したもの)と同じ"""
        for tool, folder, data_items, _ in CL.TOOLS:
            if data_items:
                self.assertEqual(data_items_of(os.path.join(ROOT, folder, "serve.py")), data_items, tool)

    def test_logs_need_the_new_folder_in_use(self):
        """ログなどの一時的なものも、新しい場所がまだ無ければ(移す前の版で動いている)消さない"""
        self.assertFalse([i for i in CL.plan(self.root, self.env) if i["ok"]])

    def test_nothing_without_marker(self):
        items = CL.plan(self.root, self.env)
        self.assertTrue(items and not any(i["ok"] for i in items))
        self.assertIn(".migrated.json", items[0]["reason"])
        self.assertEqual(self.run_main(), 0)
        self.assertTrue(os.path.isfile(os.path.join(self.root, "clip-studio", "data.json")))

    def test_moves_migrated_data_and_logs_to_trash(self):
        self.migrate("studio", "clip-studio", ["data.json", "cache"])
        self.migrate("transcribe", "transcribe-tool", ["transcripts"])
        os.makedirs(os.path.join(self.data, "app", "logs"))   # 入口は .migrated.json を作らない(記録だけなので)
        self.assertEqual(self.run_main(), 0)
        for rel in ("clip-studio/data.json", "clip-studio/cache", "clip-studio/studio.log", "transcribe-tool/transcripts",
                    "transcribe-tool/serve.log", "app/logs"):
            self.assertFalse(os.path.lexists(os.path.join(self.root, rel)), rel)
        self.assertTrue(os.path.isfile(os.path.join(self.root, "clip-studio", "serve.py")))            # コードは残る
        self.assertTrue(os.path.isfile(os.path.join(self.trash, "cache", "chat", "a.json")))          # ごみ箱にある
        self.assertTrue(os.path.isfile(os.path.join(self.data, "studio", "data.json")))               # 新しい場所は触らない

    def test_keeps_items_not_in_marker_or_missing_in_new(self):
        self.migrate("studio", "clip-studio", ["data.json"])
        os.remove(os.path.join(self.data, "studio", "data.json"))                                      # 新しい場所に無い
        items = {i["name"]: i for i in CL.plan(self.root, self.env) if i["tool"] == "studio"}
        self.assertFalse(items["data.json"]["ok"])
        self.assertIn("同じ名前が無い", items["data.json"]["reason"])
        self.assertFalse(items["cache"]["ok"])                                                         # 写した一覧に無い
        self.assertTrue(items["studio.log"]["ok"])                                                     # ログは消してよい

    def test_marker_from_another_folder(self):
        self.migrate("studio", "clip-studio", ["data.json"])
        with open(os.path.join(self.data, "studio", ".migrated.json"), "w", encoding="utf-8") as f:
            json.dump({"from": os.path.join(self.tmp, "other", "clip-studio"), "items": ["data.json"]}, f)
        self.assertFalse(any(i["ok"] for i in CL.plan(self.root, self.env) if i["tool"] == "studio"))

    def test_dry_run_and_decline(self):
        self.migrate("studio", "clip-studio", ["data.json"])
        self.assertEqual(self.run_main("--dry-run"), 0)
        self.assertEqual(self.run_main(answer="n"), 1)
        self.assertTrue(os.path.isfile(os.path.join(self.root, "clip-studio", "data.json")))

    def test_running_tools_stop_everything(self):
        self.migrate("studio", "clip-studio", ["data.json"])
        with mock.patch.object(CL, "running_tools", return_value=["studio"]):
            self.assertEqual(CL.main([], root=self.root, env=self.env, ask=lambda _: "y", trash_dir=self.trash), 2)
        self.assertTrue(os.path.isfile(os.path.join(self.root, "clip-studio", "data.json")))

    def test_inplace_never_deletes(self):
        self.migrate("studio", "clip-studio", ["data.json"])
        self.assertFalse(any(i["ok"] for i in CL.plan(self.root, {"YTT_DATA_DIR": "inplace"})))


if __name__ == "__main__":
    unittest.main()
