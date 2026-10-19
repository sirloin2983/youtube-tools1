"""置換辞書の読み方と当て方(語彙。標準ライブラリと ytt.txbase だけの純粋な関数)。③ 人の再認識の反映・① の clipjob の両方が読む。

「誤=>正」を 1 行に 1 つ書いた文字列を読む `parse_replacements`・「|語|」(単語の途中には当てない指定)を割る `wb_split`・
語が同じ種類の文字の並びの途中で切れていないかを見る `_bounded`・組 [(誤, 正)] を文に当てる `apply_replacements`。
"""
from ytt import txbase as _txbase

# 人が登録する置換辞書(設定の replacements)を当てるか(ユーザー「使い始める時にしっかり置換規則を再定義する」= decisions 3-48 Q10)。
# 今はオフ: 登録があっても文字起こし・再認識の結果に当てない(② flow/tx.dict_pairs が組に入れない)・学習の束にも入れない(④ keep/learnpack)。
# 名簿の呼び名の表記ゆれの表(roster.variant_pairs)はこれと別で、今までどおり当てる。読み方(parse_replacements など)と設定の欄は残す
USER_DICT = False


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


def spans(text, w, r):
    """text の中で w がある位置(r の一部になっている箇所・単語の途中は除く)。学習した置換の選び方(③ learn)と確度「高」だけを当てる側(① replace)の共通の数え方"""
    rs = []
    if r:
        k = text.find(r)
        while k >= 0:
            rs.append((k, k + len(r)))
            k = text.find(r, k + 1)
    out, k = [], text.find(w)
    while k >= 0:
        if not any(a <= k and k + len(w) <= b for a, b in rs) and _bounded(text, k, w):   # 単語の途中には当てない(トル→ポル が「トルコ」に当たらない)
            out.append(k)
        k = text.find(w, k + 1)
    return out


def wb_split(w):
    """置換辞書の「誤」が |語| の形なら、(語, True)。単語の途中には当てない指定。それ以外は (w, False)。"""
    if len(w) >= 3 and w[0] == "|" and w[-1] == "|":
        return w[1:-1], True
    return w, False


def apply_replacements(text, pairs):
    """置換辞書の組 [(誤, 正)] を順に当てる -> (新しい文章, 置き換えた数)。|語| の形は単語の途中には当てない(_bounded)"""
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
