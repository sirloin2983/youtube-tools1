"""書き出し済みのマークの「セリフ」(文字起こしツールで作った文字起こし)を、元の配信の時刻にして返す(統合計画の段階4)。

文字起こしツールのデータは**読むだけ**(書き換えない)。紐づけと時刻の合わせ方は ytt_core/txindex.py(入口の案件の画面と共通)。
GET /api/transcripts?id=<動画ID> → {"marks": {マークID: {...}}}。書き出し済みで mp4 のパスを持つマークだけ。
"""
import os

import common
from ytt_core import txindex

MAX_LINES = 3000   # 1本の切り抜きで返す行の上限(ショートなら数十行)


def tx_folder():
    return txindex.folder(os.path.dirname(common.CODE_DIR))


def for_video(video, folder=None):
    """video: STORE.get の公開用の動画(marks に path を持つ)。-> {"marks": {...}, "linked": 件数}"""
    docs = None
    out = {}
    vid = video.get("id") or ""
    for m in video.get("marks") or []:
        path = m.get("path") if isinstance(m.get("path"), str) else ""
        if m.get("status") != "exported" or not path:
            continue
        if docs is None:
            docs = txindex.load(folder or tx_folder())
        doc, n, _ = txindex.pick(docs, vid, m.get("id"), path)
        if not doc:
            continue
        off, basis = txindex.offset(doc, vid, path, m.get("start"))
        out[m["id"]] = dict(txindex.summary(doc), others=n - 1, offset=round(off, 3), offsetFrom=basis,
                            lines=txindex.lines(doc, off, MAX_LINES), truncated=doc["count"] > MAX_LINES)
    return {"marks": out, "linked": len(out)}
