# -*- coding: utf-8 -*-
"""① 自動の流れの層 pipeline/transcribe: 確度「高」の学習済み置換を機械の出力に当てる(`auto_learned_replace`)。純粋な関数だけ(ファイル・設定を読まない)。
役割で組み直す RS6 a-3(2026-10-10)に human/proof/learn から移した(① の clipjob が ③ を読まずに当てるため)。規則を作って選ぶ(学習の統計・確度)のは ③ の learn のまま =
呼ぶ側が選び方 find(learn.find_suggestions の only_high)を渡す。
置換辞書の読み方(`parse_replacements`・`wb_split`・`_bounded`。RS6 a-1)と当て方(`apply_replacements`。RS6 a-3)は `ytt/dictfmt.py`
(③ 人の再認識の反映・④⑤ も ① を読まずに使う。ここでは再公開しない)。

役割で組み直す RS3-E5c(2026-10-10)に編集の ed_learn(段10 で editor/serve.py から分けた部品)から置換辞書の部品をここへ移した。旧い名前 S.名前 は serve の受付がここへ回す。
"""


def auto_learned_replace(text, find):
    """確度が「高」の学習済み置換だけを当てる -> (新しい文章, 置換した数)。find(text) -> [{"i", "wrong", "right"}](位置の順・重ならない。
    ③ の learn.find_suggestions(text, 規則, 記録, only_high=True)を呼ぶ側が包んで渡す)"""
    sugs = find(text)
    for sg in reversed(sugs):
        text = text[:sg["i"]] + sg["right"] + text[sg["i"] + len(sg["wrong"]):]
    return text, len(sugs)
