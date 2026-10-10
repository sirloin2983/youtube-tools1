# -*- coding: utf-8 -*-
"""文字起こしの文字の語彙(標準ライブラリと ytt/txbase だけの純粋な関数と決まった値)。役割で組み直す RS6 a-3(2026-10-10)に
pipeline/transcribe の postproc(行を分ける・句読点・要確認の印の文)と roster(用語の区切り)から下ろした
= ③ 人の校正(長い行の分け直し・再認識の反映)が ① を読まずに使える。① の postproc もここを読む(同じ物を 2 つ持たない)。

- 要確認の印「長い区間に文字が少ない」の文 SPARSE_FLAG と、記号・空白を除いた文字数 text_chars
- 行を単語の時刻で整えて分ける split_segment(決まりの値 SPLIT_GAP・SPLIT_SEC・SPLIT_CHARS・SPLIT_SLACK)と、空白を詰めて比べる _squash
- テロップ用の句読点の除去 strip_punct(STRIP_PUNCT_CHARS)
- 用語集の欄の区切り split_terms
名前は編集の serve の名前の受付(_ED_MODULES)に並ぶ = S.strip_punct などで読める。受付に並ぶほかの部品と同じ名前を作らない。
"""
import re
import unicodedata

from ytt import txbase as _txbase

SPARSE_FLAG = "長い区間に文字が少ない(抜けの可能性)"   # 要確認の印(① の postproc.make_flags が付け、③ の再認識・疑わしい所の選び方が読む)


def text_chars(text):
    """記号・空白を除いた文字数(文字と数字だけ。かな・漢字・英数字)"""
    return sum(1 for ch in str(text or "") if unicodedata.category(ch)[0] in "LN")


SPLIT_GAP, SPLIT_SEC, SPLIT_CHARS = 1.0, 8.0, 24   # 単語の間がこの秒数以上あいたら行を分ける / 1行の最大の長さ(秒・文字。文字は設定の subtitle.splitChars(既定 24 = 0.59.6。0.59.5 は 40)。
# 0.59.5(2026-10-08)までは字幕の最大文字数(縦 16)で分けていたが、区切りを意識した校正(確かめ済み 22 本)で 16 文字の内側の切れ目は 73% が戻され、
# whisper の行をそのまま残す方が人の分け方に近かった(的中 68% → 74〜76%・①頭 19% → 14%・①末 25% → 20%。plan/line-b-row-split.md の 8)。字幕の長さはパックの折り返しで別に扱う。
# 0.59.6(2026-10-08): 友人「字幕が長すぎる(縦 8 字で 5 段)」→ ユーザー「3 段(24 字)以上はやめてほしい・とりあえず 24 で」。24 で分けても境目の的中 74%・①末 20% は 40 と同じ(plan/line-b-transcription.md の「長い行だけ分けると」))
SPLIT_SLACK = 2          # 最大文字数を 2 文字まで超えるのは許す(無理に分けて変な所で切らない。docs/design/edit-tool-design.md の 12 ②)


STRIP_PUNCT_CHARS = "、。？！?!"   # ショート動画のテロップでは句読点が浮きやすいので、既定で取り除く対象(全角の読点・句点・疑問符・感嘆符と、その半角形)
_strip_punct_re = re.compile("[%s]" % re.escape(STRIP_PUNCT_CHARS))


def strip_punct(text):
    """テロップ表示用に、句読点(、。？！ と半角の ?!)を取り除く。"""
    return _strip_punct_re.sub("", text)


def _squash(text):
    """空白を詰めた文字(単語の並びと行の文字が同じかを比べる)"""
    return re.sub(r"\s+", "", str(text or ""))


def _cut_words(ws, max_chars=SPLIT_CHARS):
    """単語の並び ws=[(開始,終了,文字)] を、長すぎる間は「間が大きい・句読点のあと・真ん中に近い」所で分けていく。
    文字数は max_chars + SPLIT_SLACK まで許す。同じ種類の文字(カタカナ・漢字・英数字)の並びの途中では、なるべく切らない(12 ②)"""
    dur = ws[-1][1] - ws[0][0]
    chars = sum(len(t.strip()) for _a, _b, t in ws)
    if len(ws) < 2 or (dur <= SPLIT_SEC and chars <= max_chars + SPLIT_SLACK):
        return [ws]
    best, bi = None, 1
    for i in range(1, len(ws)):
        gap = max(0.0, ws[i][0] - ws[i - 1][1])
        prev_t, next_t = ws[i - 1][2].rstrip(), ws[i][2].lstrip()
        tail = prev_t[-1:]
        punct = 1.0 if tail in "。！？!?" else (0.4 if tail in "、,，" else 0.0)
        balance = 1.0 - abs((ws[i - 1][1] - ws[0][0]) / dur - 0.5) if dur > 0 else 0.5
        same = 1.0 if prev_t and next_t and _txbase.char_class(prev_t[-1]) and _txbase.char_class(prev_t[-1]) == _txbase.char_class(next_t[0]) else 0.0   # 語の途中
        score = gap * 2 + punct + balance * 0.5 - same
        if best is None or score > best:
            best, bi = score, i
    return _cut_words(ws[:bi], max_chars) + _cut_words(ws[bi:], max_chars)


def split_segment(s, max_chars=SPLIT_CHARS):
    """認識した1行 s を、単語の時刻で整える。①行の始まり・終わりを最初・最後の単語にそろえる(声のない所まで伸びた行を直す)
    ②単語の間が1秒以上あいた所で分ける ③長すぎる行(8秒・max_chars 文字 + 2 超)は区切りのよい所で分ける。
    単語の並びが行の文章と合わないとき、単語の時刻が無いときは、何もせずそのまま返す。
    分けた行には、その行の単語を "_words" に付ける(文書の words.json に保存する用。行のデータには入れない)"""
    words = s.get("words") or []
    if not words:
        return [s]
    ws = [(a, b, t) for a, b, t in words if b >= a]
    if not ws or _squash("".join(t for _a, _b, t in ws)) != _squash(s.get("text", "")):
        return [s]
    groups, cur = [], [ws[0]]
    for w in ws[1:]:
        if w[0] - cur[-1][1] >= SPLIT_GAP:
            groups.append(cur)
            cur = []
        cur.append(w)
    groups.append(cur)
    parts = [p for g in groups for p in _cut_words(g, max_chars)]
    out = []
    for p in parts:
        text = "".join(t for _a, _b, t in p).strip()
        if text:
            out.append({**{k: v for k, v in s.items() if k != "words"}, "start": p[0][0], "end": max(p[-1][1], p[0][0]), "text": text, "_words": p})
    return out or [s]


def split_terms(text):
    """「、」「,」・改行で区切った語の並び(用語集の欄など)。RS2-8a に編集の ed_jobs から pipeline/transcribe/roster へ、RS6 a-3 にここへ"""
    return [t.strip() for t in re.split(r"[\r\n,、]+", str(text or "")) if t.strip()]
