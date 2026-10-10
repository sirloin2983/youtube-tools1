# -*- coding: utf-8 -*-
"""human/proof/doc_jobs の、serve が登録する口(set_hooks・check_hooks。役割で組み直す RS2-8d)のテスト。

    py -3.10 -m unittest src/human/proof/tests/test_doc_jobs.py -v

doc_jobs は editor の部品を裸の名前(import ed_store など)で読むので、src と src/editor を sys.path に足す。編集の serve は読まない
(serve の登録で口が埋まり、評価用の作り直しの差し替えが本体に届くことは src/editor/tests/test_evalbatch.py・test_names.py が確かめる)。
"""
import os
os.environ.setdefault("YTT_DATA_DIR", "inplace")   # 作業データ(AppData など)に触らない
import subprocess
import sys
import unittest

SRC = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))   # tests -> proof -> human -> src
EDITOR = os.path.join(SRC, "editor")
for _p in (EDITOR, SRC):
    if _p not in sys.path:
        sys.path.insert(0, _p)
from human.proof import doc_jobs  # noqa: E402


class TestHooks(unittest.TestCase):
    def setUp(self):
        self.saved = dict(doc_jobs._hooks)
        doc_jobs._hooks.clear()

    def tearDown(self):
        doc_jobs._hooks.clear()
        doc_jobs._hooks.update(self.saved)

    def test_unregistered_hook_raises(self):
        with self.assertRaises(RuntimeError) as cm:
            doc_jobs._hook("redo_skip")
        self.assertIn("redo_skip", str(cm.exception))
        self.assertIn("serve.py", str(cm.exception))

    def test_check_hooks_names_missing_keys(self):
        doc_jobs.set_hooks(redo_skip=lambda job: False)
        with self.assertRaises(RuntimeError) as cm:
            doc_jobs.check_hooks()
        msg = str(cm.exception)
        for k in ("redo_fill", "norm_after"):
            self.assertIn(k, msg)
        self.assertNotIn("redo_skip", msg)
        doc_jobs.check_hooks(("redo_skip",))   # 登録した鍵だけなら通る

    def test_set_hooks_rejects_unknown_and_non_callable(self):
        with self.assertRaises(TypeError):
            doc_jobs.set_hooks(not_a_hook=lambda: None)
        with self.assertRaises(TypeError):
            doc_jobs.set_hooks(redo_skip=True)
        self.assertEqual(doc_jobs._hooks, {})   # 断ったときは何も入れない

    def test_hook_is_looked_up_at_call_time(self):
        calls = []
        doc_jobs.set_hooks(norm_after=lambda job, spec, tid: calls.append(("a", tid)))
        doc_jobs._hook("norm_after")({}, {}, "t1")
        doc_jobs.set_hooks(norm_after=lambda job, spec, tid: calls.append(("b", tid)))   # 登録し直すと次の呼び出しから新しい方
        doc_jobs._hook("norm_after")({}, {}, "t2")
        self.assertEqual(calls, [("a", "t1"), ("b", "t2")])
        doc_jobs.set_hooks(redo_skip=lambda j: False, redo_fill=lambda j, s, f: None)
        doc_jobs.check_hooks()

    def test_eval_dir_hooks_are_gone(self):
        """評価用のフォルダの判定は口でなく ytt/settings を直に読む(RS3-1。口は redo_skip・redo_fill・norm_after の 3 本)"""
        self.assertEqual(doc_jobs._HOOK_KEYS, ("redo_skip", "redo_fill", "norm_after"))
        with self.assertRaises(TypeError):
            doc_jobs.set_hooks(in_eval_dir=lambda path: False)

    def test_does_not_import_manage_or_eval_parts(self):
        """評価用のフォルダ(manage の ed_relink)と評価用の作り直し(eval の ed_evalbatch)はモジュールとして持たない(口を通す)"""
        for name in ("ed_relink", "ed_evalbatch", "ed_state"):
            self.assertNotIn(name, vars(doc_jobs), name)


class TestImportWithoutServe(unittest.TestCase):
    def test_import_without_serve(self):
        """doc_jobs は編集の serve を読まずに import できる(口は空のまま = 使う前に serve が登録する)"""
        code = ("import os, sys; os.environ.setdefault('YTT_DATA_DIR', 'inplace'); sys.path[:0] = [%r, %r]; "
                "from human.proof import doc_jobs; import ed_jobs; "
                "ok = 'serve' not in sys.modules and doc_jobs._hooks == {} and ed_jobs.public_job is doc_jobs.public_job; "
                "print(sorted(m for m in sys.modules if m == 'serve')); sys.exit(0 if ok else 1)") % (SRC, EDITOR)
        p = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=120)
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)


if __name__ == "__main__":
    unittest.main()
