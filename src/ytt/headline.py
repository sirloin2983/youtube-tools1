# -*- coding: utf-8 -*-
"""切り抜きの見出しと「選んだ理由」を規則で作る(人の作業なしの候補の新機能 C・10-23)。LLM は使わない。
見出し = 盛り上がりの山の近くの、感情の強い行(！？・伸ばし棒・笑い・同じ字の繰り返し・感情の言葉。サムネの案 thumb_ideas と同じ点数 excite_score)を「…」で。
理由 = 候補の理由(盛り上がりの reasons。音量が急上昇・チャットが急増 など)+ 見出しの行の手がかり(山の何秒前か・叫び・笑い)。
届ける情報(.meta.json の headline・headlineWhy)と友人の受け取りの画面に「機械の見出し」として出す(flow/run・flow/deliver・friendapp)。
文字起こしの行の言葉そのままで、要約・言い換えはしない(誤った見出しを作らない)。スイッチ HEADLINE
"""
import re
import unicodedata

HEADLINE = True          # False = 見出しを作らない(前のまま)
HEAD_MAX = 24            # 見出しの文字の最大(超えたら … で切る)
HEAD_MIN = 5             # これより短い行(相づち・「なんで」だけ)は見出しにしない
PEAK_NEAR = 8.0          # 山の前後この秒の行に点を足す
# ひらがなで始まる言葉は、前がひらがななら語の途中(「において」の「おい」・「好きなんです」の「なんで」)なので当てない。「おい」は後ろがひらがなでも当てない(「おいしい」)
WORD_RE = re.compile(r"(?:(?<![ぁ-ん])(?:なんで|うそ|やば|待って|まって|ちょ|えぇ+|えっ|は[?？]|ん[?？]|あれ|おい(?![ぁ-ん])|うわ+|ぎゃ+)|嘘|誰|最高|無理|好き)")
_LAUGH = re.compile(r"笑|[wｗ]{2,}|草|あはは|ははは|ふふふ")
_SHOUT = re.compile(r"[!！]|ー{2,}|～|うわ|ぎゃ|えっ|やば|ヤバ|マジ|まじ|嘘")
_FILLER = re.compile(r"ちょ(?:っと|うど)|好き")     # 感情の言葉の規則(WORD_RE)に当たるが、見出しではふだんの言葉(「ちょっと」「ちょうど」)
_HESITATE = re.compile(r"(?:\.\.\.|…)")          # 言いよどみ・聞き取れない所(「えーっと...えーっと」)


def excite_score(text):
    """行の感情の強さ(！？・伸ばし棒・笑い・同じ字の繰り返し・感情の言葉)"""
    t = str(text or "")
    s = 2 * len(re.findall(r"[!！?？]", t)) + len(re.findall(r"ー{2,}|～", t)) + 2 * len(re.findall(r"笑|[wｗ]{2,}|草", t))
    s += 2 * len(re.findall(r"(.)\1{2,}", t)) + 3 * len(WORD_RE.findall(t))
    return s


def clean(text):
    """見出し・キャッチにする文字(空白と記号の続きを詰める)"""
    t = unicodedata.normalize("NFKC", str(text or "")).strip()
    t = re.sub(r"\s+", "", t)
    return re.sub(r"([!?。、…])\1+", r"\1", t)


def headline(rows, peak=None, span=None, reasons=None):
    """文字起こしの行(start・end・text・cut / noSub)-> {"text": 見出し, "why": 理由, "by": "rule", "at": 行の秒} か None(作れない・スイッチがオフ)。
    peak = 山の時刻(行と同じ時刻の物差し。無ければ None)・span = (始まり, 終わり)= この中の行だけ(余白つきの切り抜きのマークの区間)・
    reasons = 候補の理由の文の一覧(盛り上がりの reasons。依頼の区間なら無い)"""
    if not HEADLINE:
        return None
    best = None
    for r in rows or []:
        if not isinstance(r, dict) or r.get("cut") or r.get("noSub"):
            continue
        t = clean(r.get("text"))
        try:
            a, b = float(r.get("start")), float(r.get("end"))
        except (TypeError, ValueError):
            continue
        if len(t) < HEAD_MIN or (span and (b <= span[0] or a >= span[1])):
            continue
        near = peak is not None and a - PEAK_NEAR <= peak <= b + PEAK_NEAR
        score = excite_score(t) - 3 * len(_FILLER.findall(t)) - 2 * max(0, len(_HESITATE.findall(t)) - 1)
        score += (3 if near else 0) + min(len(t), 16) / 8.0   # 同じ点なら長めの行(意味が分かる)
        if best is None or score > best[0]:
            best = (score, t, a, near)
    if best is None:
        return None
    score, t, a, near = best
    text = "「%s」" % (t if len(t) <= HEAD_MAX else t[:HEAD_MAX - 1] + "…")
    hints = [str(x) for x in reasons or [] if str(x).strip()][:3]
    if near and peak is not None:
        hints.append("山の近くの行" if abs(peak - a) < 1.0 else "山の %d 秒%sの行" % (round(abs(peak - a)), "前" if a < peak else "後"))
    if _LAUGH.search(t):
        hints.append("笑い")
    elif _SHOUT.search(t):
        hints.append("叫び・驚き")
    if not reasons and score < 3:
        hints.append("目立つ行が無いので長めの行")
    return {"text": text, "why": "・".join(dict.fromkeys(hints)) or "文字起こしの行から", "by": "rule", "at": round(a, 2)}
