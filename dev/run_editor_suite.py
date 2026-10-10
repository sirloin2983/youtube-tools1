#!/usr/bin/env python3
"""「編集」まわりのテストをまとめて流し、結果の1行ずつを出す(段10 のコードの整理で、分ける前と後の結果を比べるため)。

    python dev/run_editor_suite.py [--only 名前の一部] [--out 結果.json]

リポジトリ直下から流す。各テストは別のプロセス(AGENTS.md の決まりどおりのコマンド)。
e2e は PYTHONIOENCODING=utf-8、src/home/tests/test_mount.py は付けない(付けると子プロセスの出力の読み取りが落ちる。以前からの件)。
"""
import argparse
import json
import os
import re
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PY = sys.executable
UNIT = [
    ("editor 単体", [PY, "-m", "unittest", "src/editor/tests/test_metrics.py", "src/editor/tests/test_resolve_export.py", "src/editor/tests/test_roster.py"], False),
    ("home test_mount", [PY, "-m", "unittest", "src/home/tests/test_mount.py"], False),
    ("契約テスト", [PY, "-m", "unittest", "dev/tests/test_resolve_pack_contract.py"], False),
    ("eval_asr", [PY, "-m", "unittest", "src/eval/tools/tests/test_eval_asr.py"], False),
    ("eval_alt", [PY, "-m", "unittest", "src/eval/tools/tests/test_eval_alt.py"], False),   # 候補の当たり率(alt・YouTube の字幕 yt)
    ("ui-kit の写し", [PY, "-m", "unittest", "dev/tests/test_ui_kit_sync.py"], False),
]
def find_node():
    """node(PATH に無ければ Playwright に入っている node.exe)。無ければ None"""
    import shutil
    n = shutil.which("node")
    if n:
        return n
    try:
        import playwright
        p = os.path.join(os.path.dirname(playwright.__file__), "driver", "node.exe" if os.name == "nt" else "node")
        return p if os.path.isfile(p) else None
    except ImportError:
        return None


NODE = find_node()
if NODE:
    UNIT.append(("node 保存と切り替え", [NODE, "--test", "src/editor/tests/test_document_save.cjs"], False))
E2E = ["e2e_proofread_accuracy", "e2e_proofread_keys", "e2e_folder_marker_range", "e2e_eval_set", "e2e_row_editing", "e2e_ui_handoff",
       "e2e_edit_tabs", "e2e_edit_cut", "e2e_edit_voices", "e2e_edit_pack", "e2e_ui_mounted", "e2e_drill", "e2e_alt", "e2e_fill", "e2e_follow_scroll"]   # 一式の正は dev/run_e2e.py(test_run_e2e が一致を確かめる)
SUITE = UNIT + [(n, [PY, "src/editor/tests/%s.py" % n], True) for n in E2E] + [("通し確認 e2e_pipeline", [PY, "dev/tests/e2e_pipeline.py"], True)]


def summary(out):
    """出力から件数の行を拾う(unittest の Ran/OK/FAILED、e2e の OK/FAIL の数)"""
    ran = re.findall(r"Ran (\d+) tests?", out)
    res = re.findall(r"^(OK.*|FAILED.*)$", out, re.M)
    oks, fails = len(re.findall(r"^\s*OK\s", out, re.M)), len(re.findall(r"^\s*(FAIL|NG)\s", out, re.M))
    if ran:
        return "Ran %s %s" % (ran[-1], res[-1] if res else "")
    nt = re.findall(r"(?:ℹ|#) (tests|pass|fail) (\d+)", out)   # node --test の件数
    if nt:
        return " ".join("%s %s" % kv for kv in nt[-3:])
    return "OK %d / FAIL %d" % (oks, fails)


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default="")
    ap.add_argument("--out", default="")
    a = ap.parse_args()
    rows = []
    for name, cmd, utf8 in SUITE:
        if a.only and a.only not in name:
            continue
        env = dict(os.environ)
        if utf8:
            env["PYTHONIOENCODING"] = "utf-8"
        else:
            env.pop("PYTHONIOENCODING", None)
        t0 = time.time()
        try:
            p = subprocess.run(cmd, cwd=ROOT, env=env, capture_output=True, timeout=1800)
            out = (p.stdout + p.stderr).decode("utf-8", "replace")
            code = p.returncode
        except subprocess.TimeoutExpired:
            out, code = "timeout", -1
        row = {"name": name, "exit": code, "sec": round(time.time() - t0), "summary": summary(out)}
        rows.append(row)
        print("%-28s exit %-3s %5ds  %s" % (name, code, row["sec"], row["summary"]), flush=True)
        if code != 0:
            print("    ↳ " + "\n    ↳ ".join([l for l in out.splitlines() if re.search(r"FAIL|NG |Error|Traceback", l)][:6]), flush=True)
    if a.out:
        with open(a.out, "w", encoding="utf-8") as f:
            json.dump(rows, f, ensure_ascii=False, indent=1)
    sys.exit(0 if all(r["exit"] == 0 for r in rows) else 1)


if __name__ == "__main__":
    main()
