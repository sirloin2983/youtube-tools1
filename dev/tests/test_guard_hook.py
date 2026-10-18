"""dev/guard_hook.py(PreToolUse のフックの守り)のテスト。よくある命令を並べて、通す / 断るを確かめる。一時フォルダだけを使う"""
import json
import os
import subprocess
import sys
import tempfile
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(REPO, "dev"))
import guard_hook  # noqa: E402

NO_WINDOW = 0x08000000 if os.name == "nt" else 0


def touch(path, text=""):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as f:
        f.write(text)


class GuardTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = self.tmp.name.replace("\\", "/")
        self.main = root + "/repo"                     # main の作業フォルダ(.git がフォルダ・dev/land.py)
        os.makedirs(self.main + "/.git")
        touch(self.main + "/dev/land.py")
        touch(self.main + "/dev/code_map.py")
        touch(self.main + "/codemap/dev.md")
        self.wt = self.main + "/.claude/worktrees/x"   # worktree(.git がファイル)
        touch(self.wt + "/.git", "gitdir: ../../../.git/worktrees/x\n")
        touch(self.wt + "/dev/land.py")
        self.vault = root + "/vault"                   # 保管庫(.git がフォルダ・dev/land.py なし)
        os.makedirs(self.vault + "/.git")
        os.makedirs(self.vault + "/plan/data/tasks")
        os.environ.pop(guard_hook.MAIN_COMMIT_ENV, None)
        self.saved_dd = os.environ.pop("YTT_DATA_DIR", None)

    def tearDown(self):
        if self.saved_dd is not None:
            os.environ["YTT_DATA_DIR"] = self.saved_dd
        self.tmp.cleanup()

    def why(self, cmd, tool="Bash", cwd=None):
        return guard_hook.check_command(cmd, tool, cwd or self.wt)[0]

    def assertBlocked(self, kind, cmds, tool="Bash", cwd=None):
        for c in cmds:
            with self.subTest(cmd=c):
                self.assertEqual(self.why(c, tool, cwd), kind)

    def assertPass(self, cmds, tool="Bash", cwd=None):
        for c in cmds:
            with self.subTest(cmd=c):
                self.assertIsNone(self.why(c, tool, cwd))

    # 1. 名前でまとめて止める
    def test_kill_by_name(self):
        self.assertBlocked("kill", [
            "taskkill /IM python.exe /F", "taskkill /F /T /im node.exe", "taskkill.exe /F /IM py.exe",
            'taskkill /FI "IMAGENAME eq python.exe" /F', "pkill -f server.py", "killall python",
            'wmic process where "name=\'python.exe\'" delete', "cd /tmp && taskkill /IM x.exe",
        ])
        self.assertBlocked("kill", [
            "Stop-Process -Name python", "Stop-Process -Name python -Force", "spps -n node",
            "Get-Process python | Stop-Process", "Get-Process -Name py* | Stop-Process -Force",
            "Get-Process | Where-Object { $_.Name -eq 'python' } | Stop-Process", "kill -Name python",
        ], tool="PowerShell")

    def test_kill_by_pid_passes(self):
        self.assertPass(["taskkill /PID 1234 /T /F", "kill 1234", "kill -9 1234", "ps aux | grep python",
                         "tasklist /FI \"IMAGENAME eq python.exe\"", 'echo "taskkill /IM x.exe"'])
        self.assertPass(["Stop-Process -Id 1234 -Force", "Stop-Process 1234", "Get-Process -Id 1234 | Stop-Process",
                         "kill 1234", "Get-Process python | Select-Object Id,StartTime",
                         'Write-Output "Stop-Process -Name python"'], tool="PowerShell")

    # 2. sed -i
    def test_sed(self):
        self.assertBlocked("sed", ["sed -i 's/a/b/' f.py", "sed -i.bak -e s/a/b/ f", "sed -Ei 's/a/b/' f",
                                   "sed --in-place 's/a/b/' f", "cat f | sed -i s/a/b/ g"])
        self.assertPass(["sed -n '1,20p' f.py", "sed 's/ -i//' f.py > out.txt", "sed -E 's/x/y/' f", "grep -i sed f"])

    # 3. git add -A など
    def test_git_add_all(self):
        self.assertBlocked("add", ["git add -A", "git add .", "git add --all", "git add -- .", "git add :/",
                                   "git -C C:/x add -A", "git commit -a -m wip", "git commit -am 'wip'",
                                   "git add . && git commit -m x", "git commit --all -m x"])
        self.assertPass(["git add dev/guard_hook.py dev/tests/test_guard_hook.py", "git add -p f.py",
                         "git commit -m 'git add -A は使わない'", "git commit --amend --no-edit",
                         'git commit -m "x -a y"', "git status", "git diff --cached --stat", "git log -1"])

    # 4. main の作業フォルダでのコミット
    def test_commit_in_main(self):
        self.assertBlocked("main", ["git commit -m x"], cwd=self.main)
        self.assertBlocked("main", ["git -C %s commit -m x" % self.main, 'cd "%s" && git commit -m x' % self.main,
                                    "git -C ../../.. commit -m x"], cwd=self.wt)
        self.assertBlocked("main", ["Set-Location %s; git commit -m x" % self.main.replace("/", "\\")],
                           tool="PowerShell")

    def test_commit_elsewhere_passes(self):
        self.assertPass(["git commit -m x", "git -C %s commit -m x" % self.vault], cwd=self.wt)
        self.assertPass(["git commit -m x"], cwd=self.vault)
        self.assertPass(["git -C %s commit -m x" % self.wt, "git status", "git merge x", "py -3.12 dev/land.py"],
                        cwd=self.main)

    def test_main_commit_escape(self):
        self.assertPass(["YTT_MAIN_COMMIT=1 git commit -m x"], cwd=self.main)
        self.assertPass(["$env:YTT_MAIN_COMMIT=1; git commit -m x", "$env:YTT_MAIN_COMMIT='1'; git commit -m x"],
                        tool="PowerShell", cwd=self.main)
        os.environ[guard_hook.MAIN_COMMIT_ENV] = "1"
        try:
            self.assertPass(["git commit -m x"], cwd=self.main)
        finally:
            del os.environ[guard_hook.MAIN_COMMIT_ENV]
        # 抜け道でも add -A は断る
        self.assertBlocked("add", ["YTT_MAIN_COMMIT=1 git commit -am x"], cwd=self.main)

    # 5. 生成物
    def test_generated_shell_writes(self):
        dj = self.vault + "/plan/data.js"
        self.assertBlocked("data.js", ["echo x > %s" % dj, "echo x >> '%s'" % dj, "cat a | tee %s" % dj,
                                       "cp /tmp/a.js %s" % dj, "cd %s/plan && echo x > data.js" % self.vault])
        self.assertBlocked("data.js", ['Set-Content -Path "%s" -Value x' % dj, "'x' | Out-File %s" % dj,
                                       "Copy-Item a.js -Destination %s" % dj], tool="PowerShell")
        self.assertBlocked("codemap", ["echo x > %s/codemap/dev.md" % self.main])
        self.assertBlocked("prov", ["echo x > %s/plan/仮決めの一覧.md" % self.vault])
        self.assertPass(["cat %s" % dj, "sed -n 1,5p %s" % dj, "py -3.12 dev/plan_data.py build",
                         "py -3.12 dev/code_map.py", "cp %s /tmp/backup.js" % dj, "echo x > %s/plan/notes.md" % self.vault,
                         "echo x > %s/plan/data/tasks/a.json" % self.vault, "echo x 2>&1 > out.txt"])

    def test_generated_edit_tools(self):
        dj = self.vault + "/plan/data.js"
        for tool in ("Edit", "Write", "MultiEdit"):
            with self.subTest(tool=tool):
                why, _ = guard_hook.decide({"tool_name": tool, "tool_input": {"file_path": dj}, "cwd": self.wt})
                self.assertIn("plan_data.py build", why)
        why, _ = guard_hook.decide({"tool_name": "Write", "tool_input": {"file_path": self.main + "/codemap/dev.md"}})
        self.assertIn("code_map.py", why)
        for p in (self.vault + "/plan/data/tasks/a.json", self.main + "/dev/x.py", "C:/elsewhere/data.js"):
            with self.subTest(path=p):
                self.assertEqual(guard_hook.decide({"tool_name": "Edit", "tool_input": {"file_path": p}}), (None, None))

    # 足す物: テストの起動の知らせ
    def test_test_run_warning(self):
        warn = lambda c, t="Bash": guard_hook.check_command(c, t, self.wt)[1]  # noqa: E731
        self.assertTrue(warn("py -3.12 -m unittest dev/tests/test_land.py"))
        self.assertTrue(warn("python -m pytest -q"))
        self.assertIsNone(warn("YTT_DATA_DIR=inplace py -3.12 -m unittest x"))
        self.assertIsNone(warn("$env:YTT_DATA_DIR='inplace'; py -3.12 -m unittest x", "PowerShell"))
        self.assertIsNone(warn("py -3.12 dev/run_unit.py --only dev"))
        self.assertIsNone(warn("py -3.12 -c 'import unittest'"))

    # 語に分ける
    def test_heredoc_and_herestring_are_data(self):
        self.assertPass(["cat > notes.md <<'EOF'\ngit add -A\ntaskkill /IM python.exe\nEOF\necho ok"])
        self.assertBlocked("add", ["cat > n.md <<EOF\nhello\nEOF\ngit add -A"])
        self.assertPass(["git commit -F - <<'EOF'\nsed -i は使わない\nEOF"])
        self.assertPass(["git commit -m @'\ngit add -A をやめた\n'@"], tool="PowerShell")

    def test_other_tools_pass(self):
        self.assertEqual(guard_hook.decide({"tool_name": "Read", "tool_input": {"file_path": "x"}}), (None, None))
        self.assertEqual(guard_hook.decide({}), (None, None))

    # フックとして(別のプロセス)
    def run_hook(self, payload):
        p = subprocess.run([sys.executable, os.path.join(REPO, "dev", "guard_hook.py")], input=payload,
                           capture_output=True, timeout=30, creationflags=NO_WINDOW)
        return p.returncode, p.stdout.decode("utf-8")

    def test_hook_process_deny_json(self):
        data = {"tool_name": "Bash", "tool_input": {"command": "taskkill /IM python.exe /F"}, "cwd": self.wt}
        code, out = self.run_hook(json.dumps(data).encode("utf-8"))
        self.assertEqual(code, 0)
        res = json.loads(out)["hookSpecificOutput"]
        self.assertEqual(res["permissionDecision"], "deny")
        self.assertIn("PID", res["permissionDecisionReason"])

    def test_hook_process_passes_and_fails_open(self):
        ok = {"tool_name": "Bash", "tool_input": {"command": "git status"}, "cwd": self.wt}
        for payload in (json.dumps(ok).encode("utf-8"), b"", b"{not json", b"\xff\xfe", b'{"tool_name": 3}'):
            with self.subTest(payload=payload):
                self.assertEqual(self.run_hook(payload), (0, ""))

    def test_install(self):
        path = self.tmp.name + "/s/.claude/settings.json"
        touch(path, '{"permissions": {"additionalDirectories": ["D:/x"]}}')
        self.assertTrue(guard_hook.install(path))
        self.assertFalse(guard_hook.install(path))
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        self.assertEqual(data["permissions"]["additionalDirectories"], ["D:/x"])
        hooks = data["hooks"]["PreToolUse"]
        self.assertEqual(len(hooks), 1)
        self.assertIn("|| true", hooks[0]["hooks"][0]["command"])
        self.assertIn("Bash", hooks[0]["matcher"])


if __name__ == "__main__":
    unittest.main()
