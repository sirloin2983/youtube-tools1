# -*- coding: utf-8 -*-
"""① 自動の流れの層 pipeline/transcribe: 確度「高」の学習済み置換を機械の出力に当てる(`auto_learned_replace`)。純粋な関数だけ(ファイル・設定を読まない)。
役割で組み直す RS6 a-3(2026-10-10)に human/proof/learn から移した(① の clipjob が ③ を読まずに当てるため)。規則を作って選ぶ(学習の統計・確度)のは ③ の learn のまま =
呼ぶ側が選び方 find(learn.find_suggestions の only_high)を渡す。
置換辞書の読み方(`parse_replacements`・`wb_split`・`_bounded`。RS6 a-1)と当て方(`apply_replacements`。RS6 a-3)は `ytt/dictfmt.py`
(③ 人の再認識の反映・④⑤ も ① を読まずに使う。ここでは再公開しない)。

役割で組み直す RS3-E5c(2026-10-10)に置換辞書の部品をここへ移した。旧い名前 S.名前 は serve の受付がここへ回す。
"""


from ytt import dictfmt as _dictfmt


def fixed_finder(pairs):
    """確度「高」と決まった置換の組 [(誤, 正)] だけで選ぶ find(text)(auto_learned_replace に渡す形)。組が無ければ None。
    確度「高」は文脈に依らない(そのまま残した例が無い・3 回以上・2 件以上の文書・却下 0)ので、③ が計算した組だけを受ければ
    ③ の learn.find_suggestions(only_high=True)と同じ選び方になる(長い誤りを優先・重なる所は出さない・位置の順)。友人の PC は文書なしでこれを使う"""
    pairs = [(str(w), str(r)) for w, r in pairs if w]
    if not pairs:
        return None

    def find(text):
        cands = [(k, w, r) for w, r in pairs if w in text for k in _dictfmt.spans(text, w, r)]
        cands.sort(key=lambda c: (-len(c[1]), c[0]))
        used, out = [], []
        for k, w, r in cands:
            if any(k < b and a < k + len(w) for a, b in used):
                continue
            used.append((k, k + len(w)))
            out.append({"i": k, "wrong": w, "right": r})
        out.sort(key=lambda c: c["i"])
        return out
    return find


def pick_glossary(user_terms, ranked, limit=150):
    """③ が順位つけた語 ranked(多い順・重複なし)から、ヒント全体が limit 文字に収まる範囲で最大 20 語 -> 足す語の一覧(③ learn.auto_glossary の選び方と同じ)"""
    have = list(user_terms)
    out = []
    for r in ranked:
        if r in have or r in out:
            continue
        if len("、".join(have + out + [r])) > limit:
            continue
        out.append(r)
        if len(out) >= 20:
            break
    return out


def auto_learned_replace(text, find):
    """確度が「高」の学習済み置換だけを当てる -> (新しい文章, 置換した数)。find(text) -> [{"i", "wrong", "right"}](位置の順・重ならない。
    ③ の learn.find_suggestions(text, 規則, 記録, only_high=True)を呼ぶ側が包んで渡す)"""
    sugs = find(text)
    for sg in reversed(sugs):
        text = text[:sg["i"]] + sg["right"] + text[sg["i"] + len(sg["wrong"]):]
    return text, len(sugs)
