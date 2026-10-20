# -*- coding: utf-8 -*-
"""画面のエラー 1 件の「決まった項目を決まった長さで切る」規則の 1 か所(入口 manage/ops/clientlog と友人のアプリ friendapp/server が呼ぶ)。
画面から来た値は文字列・整数として扱うだけ(解釈しない)。項目の足し方・必須の検査・書く場所は呼ぶ側。
"""

TEXT = {"message": 500, "source": 300, "stack": 2000, "page": 300}   # 文字列の項目 -> 長さの上限(この順で並べる)


def pick(body, text=TEXT, line_max=None):
    """body の text の項目(空でない文字列だけ・長さで切る)と、line・col(整数。bool は除く。line_max があれば 0 < 値 < line_max だけ)-> dict"""
    out = {k: v[:n] for k, n in text.items() for v in (body.get(k),) if isinstance(v, str) and v}
    for k in ("line", "col"):
        v = body.get(k)
        if isinstance(v, int) and not isinstance(v, bool) and (line_max is None or 0 < v < line_max):
            out[k] = v
    return out
