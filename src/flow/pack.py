"""② パックの口(RS6 a-5a)。人とデータの層(③・④)が Resolve のパックの部品(① pipeline/pack/resolve_export)を直に読まずに済む動詞。

- `cut_draft(doc, rows, row_edge)` : カットのたたき台。② が足すこと = 版(workdata)・無音の検出(ffmpeg)の順番待ち(SLOTS。待つのは DRAFT_SLOT_WAIT 秒まで)
- `cut_preview(doc, keeps, wrap)` : カットのとおりに作ったときのパックの見積もり。② が足すこと = 版
- `handoff_files(doc, fmt)` : 受け渡しの JSON の中身。② が足すこと = 版・形式の見分け
- `media_plan(doc, path)` : 別の動画に付け替えるときの fps と長さ。② が足すこと = 版・「行から」を計算しない指定(rows=False)
- `instructions(folder)` : 前回のパックの Resolve での手順。② が足すこと = 無いときは None でなく空の文字
置き場所・版は `ytt.workdata` の今の値を呼ぶたびに読む。重い処理の札の名前は `flow.jobs` の configure(tool=)(編集の serve が入れる)。
"""
import time

from pipeline.pack import resolve_export
from ytt import workdata

from . import jobs

DRAFT_SLOT_WAIT = 10.0   # 「行から」の行の端の無音を調べる順番(SLOTS)を待つ上限(秒)。過ぎたら無音を調べずに決まった余白で広げる


def _draft_slot(label):
    deadline = time.monotonic() + DRAFT_SLOT_WAIT
    return jobs.tool_slot(label, cancelled=lambda: time.monotonic() > deadline)


def cut_draft(doc, rows=True, row_edge=None):
    """カットのたたき台と動画の fps・長さ(① resolve_export.edit_draft)。② が足すこと: 版・無音の検出の順番待ち(DRAFT_SLOT_WAIT 秒)。
    -> {"fps", "durationSec", "keepsSec", "base", "warnings", "skipped"?}。動画が読めなければ ytt.errors.ResolveExportError"""
    return resolve_export.edit_draft(doc, workdata.SERVER_VERSION, rows=rows, row_edge=row_edge, heavy=_draft_slot)


def cut_preview(doc, keeps, wrap=None):
    """カットのとおりに作ったときのパックの見積もり(① resolve_export.edit_preview)。② が足すこと: 版。ファイルは作らない"""
    return resolve_export.edit_preview(doc, keeps, workdata.SERVER_VERSION, wrap)


def handoff_files(doc, fmt):
    """受け渡しの中身 -> (obj, 行の数)。transcript-v1 は dict(segments を持つ)。
    ② が足すこと: 版・形式の検査(知らない形式は ValueError)"""
    if fmt == "transcript-v1":
        obj = resolve_export.build_transcript_v1(doc, workdata.SERVER_VERSION)
        return obj, len(obj["segments"])
    raise ValueError("知らない形式です: %r" % (fmt,))


def media_plan(doc, path):
    """文書の動画を path に替えたときの {"fps": [n, d], "durationSec"}(カットのタブと同じ測り方。① resolve_export.edit_draft)。
    ② が足すこと: 版・「行から」を計算しない(rows=False)。読めなければ ytt.errors.ResolveExportError"""
    dr = resolve_export.edit_draft(dict(doc, sourcePath=path), workdata.SERVER_VERSION, rows=False)
    return {"fps": dr["fps"], "durationSec": dr["durationSec"]}


def instructions(folder):
    """前回のパックの Resolve での手順(パックの Lua から作り直す。① resolve_export.pack_instructions)。② が足すこと: 作れなければ None でなく空の文字"""
    return resolve_export.pack_instructions(folder) or ""


