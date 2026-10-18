"""YTT_DATA_DIR=inplace のとき、作業データ(ログ・起動中の印・書き出し先)が src の中にできないことを見張る。リポジトリ直下で:

    py -3.12 -m unittest dev/tests/test_no_src_workdata.py

2026-10-16 の RV C5: inplace の作業データは <リポジトリ直下>/.data/<ツールID>/ に置く決めなのに、編集の .running.json・スタジオの exports/export-log.txt・
cut2resolve の work/serve.log が、各モジュールの「既定 = ツールのフォルダ」の置き場所のまま src の中にできていた(.gitignore で無視されて気づきにくい)。
1. 置き場所の既定が .data の下になること(重くしない: 子プロセスで読み込むだけ)
2. src の下に作業データの名前のファイルが無いこと(unittest を流したあとの残りの見張り。.gitignore の外の物は git が見るのでここは無視されている名前だけ)
"""
import json
import os
import subprocess
import sys
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SRC = os.path.join(REPO, "src")
DATA = os.path.normcase(os.path.join(REPO, ".data"))
# 作業データの名前(ツールのコードはこの名前のファイルを持たない)
WORKDATA_NAMES = {".running.json", "export-log.txt", "export-log.old.txt", "serve.log", "serve.old.log", "studio.log", "studio.old.log", "serve.crash.log", "worker.log"}
WORKDATA_DIRS = {"exports", "logs", "work"}

PROBE = r"""
import json, os, sys
sys.path.insert(0, os.path.join(%r, "src"))
sys.path.insert(0, os.path.join(%r, "src", "cut2resolve"))
from ytt import studio_env, workdata, layout
workdata.set_root(layout.tool_dir("transcribe"))
import serve
print(json.dumps({"studio": studio_env.home(), "editor": workdata.DATA_DIR, "c2r": serve.WORK_DIR}))
""" % (REPO, REPO)


class TestNoSrcWorkdata(unittest.TestCase):
    def test_inplace_defaults_are_under_dot_data(self):
        env = dict(os.environ, YTT_DATA_DIR="inplace")
        for k in ("STUDIO_HOME", "TRANSCRIBE_DATA_DIR"):
            env.pop(k, None)
        r = subprocess.run([sys.executable, "-c", PROBE], env=env, capture_output=True, text=True, encoding="utf-8", cwd=REPO,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        self.assertEqual(r.returncode, 0, r.stderr[-800:])
        got = json.loads(r.stdout.strip().splitlines()[-1])
        for k, v in got.items():
            self.assertTrue(os.path.normcase(os.path.abspath(v)).startswith(DATA + os.sep), "%s の既定が .data の下でない: %s" % (k, v))

    def test_no_workdata_files_under_src(self):
        found = []
        for d, dirs, files in os.walk(SRC):
            dirs[:] = [x for x in dirs if x not in ("__pycache__", "node_modules", ".venv", "tests")]
            rel = os.path.relpath(d, SRC)
            if rel.count(os.sep) == 1 and os.path.basename(d) in WORKDATA_DIRS:   # src/<ツール>/exports など
                found.append(rel)
            found.extend(os.path.join(rel, f) for f in files if f in WORKDATA_NAMES)
        self.assertEqual(found, [], "src の下に作業データができている(inplace は .data の下に置く): %s" % found)


if __name__ == "__main__":
    unittest.main()
