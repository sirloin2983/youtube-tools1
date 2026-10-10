# -*- coding: utf-8 -*-
"""① 自動の流れの層 pipeline/transcribe: 置換辞書(「誤=>正」を 1 行に 1 つ書いた文字列)の読み方と当て方。純粋な関数だけ(ファイル・設定を読まない)。

役割で組み直す RS3-E5c(2026-10-10)に編集の ed_learn(段10 で editor/serve.py から分けた部品)から移した(中身は同じ)。
文字起こしのジョブ(human/proof/doc_jobs)・再認識(human/proof/rerun)・学習(human/proof/learn)・精度の用語(eval/drill/metrics)が `replace.名前` で呼ぶたびに読む。
旧い名前 ed_learn.名前・S.名前 は editor/ed_learn.py(転送だけの殻。RS5 で消す)と serve の受付がここへ回す。
"""
from . import txbase as _txbase  # noqa: E402   文字の種類 char_class(RS2-4b に ed_learn の _cc を移した)


def parse_replacements(text):
    """「誤=>正」を1行に1つ書いた文字列 → [(誤, 正)](長い誤りから先に置換する)。"""
    pairs = []
    for line in str(text or "").splitlines():
        k = line.find("=>")
        if k > 0 and line[:k].strip():
            pairs.append((line[:k].strip(), line[k + 2:].strip()))
    return sorted(pairs[:500], key=lambda p: -len(p[0]))


def _bounded(text, k, w):
    """text の位置 k にある w が、同じ種類の文字の並び(カタカナ・漢字・英数字)の途中で切れていないか。
    例: 「トル」は「トルコ」の中では×、「トル様」の中なら○(ひらがな・記号との境目は切れ目とみなす)。"""
    c = _txbase.char_class(w[0])
    if c and k > 0 and _txbase.char_class(text[k - 1]) == c:
        return False
    c = _txbase.char_class(w[-1])
    if c and k + len(w) < len(text) and _txbase.char_class(text[k + len(w)]) == c:
        return False
    return True


def wb_split(w):
    """置換辞書の「誤」が |語| の形なら、(語, True)。単語の途中には当てない指定。それ以外は (w, False)。"""
    if len(w) >= 3 and w[0] == "|" and w[-1] == "|":
        return w[1:-1], True
    return w, False


def apply_replacements(text, pairs):
    n = 0
    for w, r in pairs:
        core, wb = wb_split(w)
        if not core or core not in text:
            continue
        if not wb:
            n += text.count(core)
            text = text.replace(core, r)
            continue
        out, i, k = [], 0, text.find(core)
        while k >= 0:
            if _bounded(text, k, core):
                out.append(text[i:k]); out.append(r); i = k + len(core); n += 1
                k = text.find(core, i)
            else:
                k = text.find(core, k + 1)
        out.append(text[i:]); text = "".join(out)
    return text, n
