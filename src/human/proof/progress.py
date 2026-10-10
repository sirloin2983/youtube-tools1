# -*- coding: utf-8 -*-
"""② 進行度(校正済みの量。GET /api/progress)。段10 で editor/serve.py から分けた ed_misc の一部。役割で組み直す RS3-E7(2026-10-10)に
human/proof/progress.py へ切り出した(一時の置き場所。進行度は次の段 D2 で消す予定 = このファイルごと消す)。

名前は serve.py からも見える(serve.py の名前の受付 _ED_MODULES がこの部品へ転送する)。
"""
from . import store as _store  # noqa: E402   文書の要約のキャッシュの _prog(呼ぶたびに _store.名前 で読む)


def progress_stats():
    """校正済みの量。学習用(評価用でない文書)と評価用を分けて数える。「聞き取れない」の印がある行は、どちらも数えない。
    文書は読み直さない(store の要約のキャッシュの _prog を足し合わせる = 一覧と同じ 1 回の読み込み)"""
    tot = {"proofedSec": 0.0, "proofedLines": 0, "docs": 0, "docsProofed": 0, "totalSec": 0.0, "totalLines": 0,
           "evalDocs": 0, "evalDocsDone": 0, "evalProofedSec": 0.0, "evalProofedLines": 0, "evalPendingLines": 0}
    for _tid, sm, _sp in _store.summaries():
        r = sm.get("_prog")
        if r is None:
            continue
        if r["eval"]:
            tot["evalDocs"] += 1
            tot["evalDocsDone"] += 1 if r["lines"] and not r["pend"] else 0
            tot["evalProofedSec"] += r["sec"]
            tot["evalProofedLines"] += r["lines"]
            tot["evalPendingLines"] += r["pend"]
            continue
        tot["docs"] += 1
        tot["docsProofed"] += 1 if r["lines"] else 0
        tot["proofedSec"] += r["sec"]
        tot["proofedLines"] += r["lines"]
        tot["totalSec"] += r["totalSec"]
        tot["totalLines"] += r["totalLines"]
    for k in ("proofedSec", "totalSec", "evalProofedSec"):
        tot[k] = round(tot[k], 1)
    return tot
