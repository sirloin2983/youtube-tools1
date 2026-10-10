# -*- coding: utf-8 -*-
"""① 自動の流れの層 pipeline/transcribe: 置換辞書(「誤=>正」を 1 行に 1 つ書いた文字列)の当て方(`apply_replacements`)。純粋な関数だけ(ファイル・設定を読まない)。
読み方(`parse_replacements`・`wb_split`・`_bounded`)は RS6 a-1(2026-10-10)に `ytt/dictfmt.py` へ移した(③ 人・④ データが ① を読まずに読めるように。ここでは再公開しない)。

役割で組み直す RS3-E5c(2026-10-10)に編集の ed_learn(段10 で editor/serve.py から分けた部品)から移した(中身は同じ)。
文字起こしのジョブ(human/proof/doc_jobs)・再認識(human/proof/rerun)・学習(human/proof/learn)・精度の用語(eval/drill/metrics)が `replace.名前` で呼ぶたびに読む。
旧い名前 ed_learn.名前・S.名前 は editor/ed_learn.py(転送だけの殻。RS5 で消す)と serve の受付がここへ回す。
"""
from ytt import dictfmt as _dictfmt  # noqa: E402   辞書の読み方(wb_split・_bounded。RS6 a-1 に ここから ytt へ)


def apply_replacements(text, pairs):
    n = 0
    for w, r in pairs:
        core, wb = _dictfmt.wb_split(w)
        if not core or core not in text:
            continue
        if not wb:
            n += text.count(core)
            text = text.replace(core, r)
            continue
        out, i, k = [], 0, text.find(core)
        while k >= 0:
            if _dictfmt._bounded(text, k, core):
                out.append(text[i:k]); out.append(r); i = k + len(core); n += 1
                k = text.find(core, i)
            else:
                k = text.find(core, k + 1)
        out.append(text[i:]); text = "".join(out)
    return text, n
