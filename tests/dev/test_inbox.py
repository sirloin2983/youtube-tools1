"""dev/inbox_send.py と dev/inbox_hook.py(作業中のセッションの受け箱。11-07)。一時フォルダだけ"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

DEV = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "dev")
ID = "local_11111111-2222-3333-4444-555555555555"


class InboxTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.env = dict(os.environ, YTT_INBOX_DIR=self.tmp, CLAUDE_CODE_HOST_SESSION_ID=ID, PYTHONIOENCODING="utf-8")

    def run_py(self, name, *args, stdin="{}"):
        return subprocess.run([sys.executable, os.path.join(DEV, name)] + list(args), input=stdin.encode("utf-8"), capture_output=True,
                              env=self.env, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0), timeout=30)

    def test_send_then_hook_delivers_once_and_keeps_copy(self):
        self.assertEqual(self.run_py("inbox_hook.py").stdout, b"")   # 受け箱が無い = 何も出さない
        self.assertEqual(self.run_py("inbox_send.py", ID, "区間は 3 本に").returncode, 0)
        self.assertEqual(self.run_py("inbox_send.py", "bad", "x").returncode, 1)   # 宛先の形が違えば断る
        out = json.loads(self.run_py("inbox_hook.py").stdout.decode("utf-8"))["hookSpecificOutput"]
        self.assertEqual(out["hookEventName"], "PostToolUse")
        self.assertIn("区間は 3 本に", out["additionalContext"])
        self.assertIn("ユーザー本人の入力ではありません", out["additionalContext"])
        self.assertEqual(self.run_py("inbox_hook.py").stdout, b"")   # 渡した分は受け箱から消える
        with open(os.path.join(self.tmp, "done", ID + ".jsonl"), encoding="utf-8") as f:
            self.assertIn("区間は 3 本に", f.read())   # 消す前に控えへ

    def test_off_switch(self):
        self.run_py("inbox_send.py", ID, "a")
        open(os.path.join(self.tmp, "OFF"), "w").close()
        self.assertEqual(self.run_py("inbox_hook.py").stdout, b"")   # 止めるスイッチ = 何もしない(受け箱は残る)
        self.assertTrue(os.path.isfile(os.path.join(self.tmp, ID + ".jsonl")))
        self.assertEqual(self.run_py("inbox_send.py", ID, "b").returncode, 1)


if __name__ == "__main__":
    unittest.main()
