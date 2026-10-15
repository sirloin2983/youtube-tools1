# -*- coding: utf-8 -*-
"""③ 文字起こし済みの範囲 transcribed_ranges(全文書の元ファイル・範囲・全体か・id)。

呼び手は ④ のマーカーの読み(manage/cases/handoff_io.read_marker。④ → ③ の向き)と編集の画面の GET /api/transcribed-ranges(スタジオのマークの「文字起こし済み」)だけ。
**read_marker と一緒に OPT-M1 で消す**(決定 3-48 の Q7)。汎用のフォルダの一括(scan_folder・add_batch・/api/scan-folder・/api/transcribe-batch)は
決定 3-47 の Q5 で消した(評価用の専用の一括 ⑤ eval/drill/evalbatch は残る)。
名前は serve.py からも見える(serve.py の名前の受付 _ED_MODULES がこの部品へ転送する。テストの S.名前 = … もここに入る)。
ほかの部品の名前は `モジュール.名前` の形で呼ぶたびに読む(差し替えが効くように。from … import はしない)。
"""
from ytt import fsio as _fsio, schemas as _yschemas  # noqa: E402
from . import store as _store  # noqa: E402   文書の要約(summaries。呼ぶたびに _store.名前 で読む)


def transcribed_ranges():
    """全文字起こしの (元ファイル・範囲・全体か・id) の一覧。マーカーのポイントで「文字起こし済み」を判定するのに使う(OPT-M1 で read_marker と一緒に消す)。"""
    out = []
    for tid, sm, sp in _store.summaries():   # 一覧(list_transcripts)は動画・パックも調べるので、ここでは要約だけを読む(キャッシュが効く)
        if not sp:
            continue
        a, b = _yschemas.num_or(sm.get("start"), 0.0) or 0.0, _yschemas.num_or(sm.get("end"))
        out.append({"path": _fsio.norm_path(sp), "start": a, "end": b, "whole": sm["_whole"], "tid": tid})
    return out
