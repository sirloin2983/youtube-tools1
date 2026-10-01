#!/usr/bin/env python3
"""「編集」まわりのテストをまとめて流し、結果の1行ずつを出す(段10 のコードの整理で、分ける前と後の結果を比べるため)。

    python dev/run_editor_suite.py [--only 名前の一部] [--out 結果.json]

リポジトリ直下から流す。各テストは別のプロセス(AGENTS.md の決まりどおりのコマンド)。
e2e は PYTHONIOENCODING=utf-8、home/tests/test_mount.py は付けない(付けると子プロセスの出力の読み取りが落ちる。以前からの件)。
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
    ("editor 単体", [PY, "-m", "unittest", "editor/tests/test_metrics.py", "editor/tests/test_resolve_export.py", "editor/tests/test_roster.py"], False),
    ("home test_mount", [PY, "-m", "unittest", "home/tests/test_mount.py"], False),
    ("契約テスト", [PY, "-m", "unittest", "dev/tests/test_resolve_pack_contract.py"], False),
    ("eval_asr", [PY, "-m", "unittest", "dev/tests/test_eval_asr.py"], False),
    ("ui-kit の写し", [PY, "-m", "unittest", "dev/tests/test_ui_kit_sync.py"], False),
]
E2E = ["e2e_proofread_accuracy", "e2e_proofread_keys", "e2e_folder_marker_range", "e2e_eval_set", "e2e_row_editing", "e2e_ui_handoff",
       "e2e_edit_tabs", "e2e_edit_cut", "e2e_edit_voices", "e2e_edit_pack", "e2e_ui_mounted"]
SUITE = UNIT + [(n, [PY, "editor/tests/%s.py" % n], True) for n in E2E] + [("通し確認 e2e_pipeline", [PY, "dev/tests/e2e_pipeline.py"], True)]


def summary(out):
    """出力から件数の行を拾う(unittest の Ran/OK/FAILED、e2e の OK/FAIL の数)"""
    ran = re.findall(r"Ran (\d+) tests?", out)
    res = re.findall(r"^(OK.*|FAILED.*)$", out, re.M)
    oks, fails = len(re.findall(r"^\s*OK\s", out, re.M)), len(re.findall(r"^\s*(FAIL|NG)\s", out, re.M))
    if ran:
        return "Ran %s %s" % (ran[-1], res[-1] if res else "")
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
