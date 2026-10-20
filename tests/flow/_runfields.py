# -*- coding: utf-8 -*-
"""テストが共有する部品: Run の欄の形(Run(video_id, title, mode, top, 欄...))から Run を作る(Run を作るのは封筒 + 束だけ = RV A2)。

テストの名前ではない(unittest は読まない)。flow の tests と入口 app のテストが `import _runfields as RF` で使う(app のテストは sys.path に tests/flow を足す)。
欄 → 封筒 + 束の差分は本物の flow/order.py(画面・友人の受付と同じ変換)、mode → run.from・run.upto は flow/run.py の MODE_RUN。
"""
import os
import sys

TESTS = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(os.path.dirname(os.path.dirname(TESTS)), "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)
from flow import order as O, run as R, spec as SP  # noqa: E402

# mode → (封筒の kind, run.from, run.upto)。export = 書き出しから全部(mode full + run.from export。マークの行の「この後を」の形。テストの呼び名)
SHAPES = dict(R.MODE_RUN, export=("url", "export", "pack"))
RENAME = {"overwrite": "repack", "deliver_origin": "origin", "deliver_tag": "tag", "source_path": "path"}


def run_of(video_id, title, mode, top=None, base=None, **kw):
    """Run(video_id, title, mode, top, **欄) の形から作る実行の Run(base = 土台の束。None = 既定)。
    依頼の形(request・request_auto)は依頼の id が要る(無ければ "r-test")"""
    kind, frm, upto = SHAPES[mode]
    o = {RENAME.get(k, k): v for k, v in kw.items()}
    if kind == "url":
        o["video_id"] = video_id
        if top is not None:
            o["top"] = top
        if mode == "request_auto":
            o.setdefault("request_id", "r-test")
    if isinstance(o.get("marks"), tuple):
        o["marks"] = list(o["marks"])
    env, diff = O.order(kind, title=title, from_=frm, upto=upto, **o)
    run = R.Run.from_envelope(env, SP.merge_onto(SP.validate(SP.merge(base)), diff))
    run.diff = diff
    return run


def respec(run, spec):
    """run.spec = 束(欄から写した差分が重なる): 束 spec(変えたい所だけ)にこの Run の差分を重ね直して置く。段の並びは作ったときのまま"""
    run.spec = SP.validate(SP.merge_onto(SP.validate(SP.merge(spec)), run.diff or {}))
    return run
