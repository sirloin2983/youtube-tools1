"""計画のデータ plan/data/ をテストの一時フォルダに置く道具(tests/dev/test_plan_data.py・test_plan_artifact.py が使う)。"""
import json
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(REPO, "dev"))
import plan_data  # noqa: E402


def lay(plan_dir, plan):
    """window.PLAN と同じ形の dict を plan/data/ の 1 件 1 ファイルに置く(summary.md・main.json は残りの欄)"""
    plan = json.loads(json.dumps(plan))
    dd = plan_data.data_dir(plan_dir)

    def put(kind, it, order):
        plan_data.write_atomic(os.path.join(dd, kind, plan_data.file_name(kind, it)), plan_data.dumps(dict(it, order=order)))

    for kind in ("recent", "tasks", "history"):
        for i, it in enumerate(plan.pop(kind, []), 1):
            put(kind, it, i * 10)
    ut = plan.setdefault("userTasks", {})
    for lst in plan_data.USER_LISTS:
        for i, it in enumerate(ut.pop(lst, []), 1):
            put("user", dict(it, list=lst), i * 10)
    for i, it in enumerate(ut.pop("provisional", []), 1):
        put("provisional", it, i * 10)
    plan_data.write_atomic(os.path.join(dd, "summary.md"), plan.pop("summary", "") + "\n")
    plan_data.write_atomic(os.path.join(dd, "main.json"), json.dumps(plan, ensure_ascii=False, indent=2) + "\n")
