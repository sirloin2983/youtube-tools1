# -*- coding: utf-8 -*-
"""① 文字起こしの行の後処理: 要確認の印(make_flags)・認識の出力を整える流れ(expand_segments = 行を単語の時刻で分ける split_segment・
長さで切る clip_rows・同じ文字の行をまとめる merge_repeats・終わりを早める trim_ends・続いている行をつなぐ join_rows・句読点の除去 strip_punct)・
自信の度合い(machine_conf)・後処理の記録(post_record)・行の単語(row_words)。
split_segment・strip_punct・SPARSE_FLAG・text_chars・SPLIT_*・_squash の本体は RS6 a-3(2026-10-10)から ytt/txtext.py(③ も読む語彙)。ここに別名は残さない。

役割で組み直す RS2-4b(2026-10-10)に編集の ed_jobs から移した(中身は同じ)。標準ライブラリ・ytt・同じパッケージの兄弟(txbase・tx_engines・roster)だけを読む
= 編集のサーバー(serve)なしで ① から読める(post_record の編集の版だけは ytt/workdata の SERVER_VERSION = app が入れた値)。
差し替えられる値(END_TRIM・JOIN_GAP)と、それを読む expand_segments・join_rows・post_record は同じこのモジュールにある。
テストの S.END_TRIM = …・mock.patch.object(ed_jobs, "expand_segments", …) は serve の名前の受付と ed_jobs の転送(ytt/modfwd)でここに届くので、
読む側は呼ぶたびに postproc.名前(ed_jobs)か ed_jobs.名前(ほかの編集の部品)で読む(from … import で読み直さない)。
"""
import functools
import math
import re
import unicodedata

from ytt import workdata as _workdata
from . import roster as _roster, tx_engines
from ytt import txbase as _txbase
from ytt import txtext as _txtext   # 行を分ける split_segment・句読点の除去 strip_punct・印の文 SPARSE_FLAG・文字数 text_chars(RS6 a-3 にここから ytt へ)


LATIN_MIN_LETTERS = 4   # 英字がこの数以上で、文字全体の LATIN_RATIO 以上を占め、
LATIN_RATIO = 0.3       # かつ「英字が LATIN_LONG 文字以上」か「英字の語が2つ以上」の行、
LATIN_LONG = 6          # または、英字と空白が LATIN_RUN 文字以上続く行を「英語の幻覚かも」とする(初期値。実データで調整する)
LATIN_RUN = 8
_LATIN_RUN_RE = re.compile(r"[A-Za-z][A-Za-z' ]{%d,}" % (LATIN_RUN - 1))


def latin_suspect(text, terms=()):
    """日本語の音声なのに英字が目立つ行か(英語のでたらめな文の幻覚に多い)。用語集にある英字の語(Apex など)は数えない。
    Apex・GG のような短い英単語が1つだけ混じる行は対象外(要確認だらけになるのを避ける)。"""
    t = str(text or "")
    for w in _latin_terms(tuple(terms)):
        t = t.replace(w, "")
    t = re.sub(r"(?i)w{2,}|\b(?:lol|lmao|gg|wp|ok)\b", "", t)   # 笑いの「wwww」や定番の略語は数えない
    letters = len(re.findall(r"[A-Za-z]", t))
    if letters < LATIN_MIN_LETTERS:
        return False
    body = len(re.sub(r"[\W_]+", "", t))   # 記号・空白を除いた文字数(日本語も数える)
    if body and letters / body >= LATIN_RATIO and (letters >= LATIN_LONG or len(re.findall(r"[A-Za-z']+", t)) >= 2):
        return True
    return bool(_LATIN_RUN_RE.search(t))


@functools.lru_cache(maxsize=32)
def _latin_terms(terms):
    """ヒントの語のうち英字を含む語(長い順)。行ごとに並べ直さない(同じヒントの語の組なら覚えた並び)"""
    return tuple(sorted({x for x in terms if x and re.search(r"[A-Za-z]", x)}, key=len, reverse=True))


SPARSE_MIN_SEC = 4.0    # 「長い区間に文字が少ない」行(docs/design/edit-tool-design.md の 12 ③-1): この長さより長くて
                        # (ちょうど 4.0 秒は含めない。疑似の文字起こしの行(4.0 秒に「テスト文N」)を対象にしないため。本物の行への影響は境目だけ)
SPARSE_MAX_CPS = 1.5    # 記号・空白を除いた文字数が 1 秒あたりこれ未満
# 印の文 SPARSE_FLAG と文字数 text_chars は RS6 a-3 に ytt/txtext.py へ下ろした(③ の再認識・疑わしい所の選び方も読む)


def sparse_row(start, end, text):
    """長い区間に文字が少ない行か(③-1)。取りこぼしを減らすために VAD を甘くしている(vadMode weak)ので、BGM やゲーム音が声として通り、
    Whisper が長い塊に単語1つを出したり、途中を飛ばしたりする(区間ごとの抜け)。その形をつかまえる"""
    try:
        dur = float(end) - float(start)
    except (TypeError, ValueError):
        return False
    return dur > SPARSE_MIN_SEC and _txtext.text_chars(text) < SPARSE_MAX_CPS * dur


def _letters(text):
    """比べる用: NFKC・小文字・文字と数字だけ"""
    return "".join(ch for ch in unicodedata.normalize("NFKC", str(text or "")).lower() if unicodedata.category(ch)[0] in "LN")


def stock_phrase(text):
    """よくある誤認識の文か(時間は見ない): 以前からの HALLUC が含まれる・行のほとんどが HALLUC_LINE の文・音楽の表記だけ(♪・(音楽))"""
    t = str(text or "")
    if any(h in t for h in _txbase.HALLUC):
        return True
    if t.strip() and _txbase.MUSIC_ONLY.match(t) and ("♪" in t or "♫" in t or "♬" in t or "(" in t or "（" in t or "[" in t or "【" in t or "［" in t):
        return True
    n = _letters(t)
    return any(k in n and len(n) - len(k) <= _txbase.HALLUC_LINE_REST for k in _halluc_keys(tuple(_txbase.HALLUC_LINE)))


@functools.lru_cache(maxsize=4)
def _halluc_keys(lines):
    """HALLUC_LINE の文の比べる形(_letters)。行ごとに作り直さない(表を差し替えれば作り直す = 表そのものが鍵)"""
    return tuple(k for k in (_letters(h) for h in lines) if k)


def repeats_in_line(text):
    """行の中で同じ語(2〜10 文字)が REP_MIN 回以上続くか(「ぱんぱんぱんぱんぱん…」。1 文字の繰り返し = 笑い・叫びは除く)"""
    k = _letters(text)
    m = _txbase.REP_RE.search(k)
    while m:
        if len(set(m.group(1))) > 1:
            return True
        m = _txbase.REP_RE.search(k, m.start() + 1)
    return False


def make_flags(seg, prev_texts, lang=None, terms=()):
    """Whisper は BGM・無音・歌で幻覚(でたらめな文)を出しやすいので、要確認の印を付ける。
    lang が "ja" のときは、英字が目立つ行も対象にする(terms = 認識のヒントに渡した語(prompt_terms)。その中の英字の語は数えない)。
    長い区間に文字が少ない行(抜けの可能性。sparse_row)にも付ける(2026-09-26 ③-1)。
    S-3(2026-09-29): よくある誤認識の文を増やした(stock_phrase)・行の中の繰り返し(repeats_in_line)・近くの行に同じ文が3回・
    短い区間でヒントの語だけが出た行(LEAK_FLAG。roster.leak_only)"""
    why = []
    lp, ns, cr = seg.get("avg_logprob"), seg.get("no_speech_prob"), seg.get("compression_ratio")
    if lp is not None and lp < -1.0:
        why.append("自信が低い")
    if ns is not None and ns > 0.6:
        why.append("音声でない可能性(BGMなど)")
    text = seg["text"]
    if (cr is not None and cr > 2.4) or repeats_in_line(text) or seg.get("_rep"):   # _rep = 同じ文字の行をまとめた・縮めた(merge_repeats)
        why.append("繰り返しの可能性")
    dur = seg["end"] - seg["start"]
    if stock_phrase(text) and dur < 8:
        why.append("よくある誤認識の文")
    key = _letters(text)
    if text and (prev_texts[-2:] == [text, text] or (len(key) >= 4 and sum(1 for p in prev_texts[-5:] if _letters(p) == key) >= 2)):
        why.append("同じ文の繰り返し")   # 続けて3回、または近く(前の5行)に同じ文が2回あって3回目
    if terms and (("用語" in text and ":" in unicodedata.normalize("NFKC", text)) or (dur <= _txbase.LEAK_MAX_SEC and _roster.leak_only(text, terms))):
        why.append(_txbase.LEAK_FLAG)
    if lang == "ja" and latin_suspect(text, terms):
        why.append("英字が多い(英語の幻覚の可能性)")
    if sparse_row(seg.get("start"), seg.get("end"), text):
        why.append(_txtext.SPARSE_FLAG)
    return "、".join(why)


# 行を単語の時刻で分ける split_segment(と SPLIT_GAP・SPLIT_SEC・SPLIT_CHARS・SPLIT_SLACK・_cut_words)・句読点の除去 strip_punct(STRIP_PUNCT_CHARS)・空白を詰める _squash は RS6 a-3(2026-10-10)に ytt/txtext.py へ下ろした(③ が ① を読まずに使えるように。ここは _txtext.名前 で呼ぶたびに読む)


def expand_segments(gen, spec, dur=None, join=True):
    """認識の出力を、split_segment で整えながら流す(wordSplit が無効なら、そのまま)。
    句読点の除去(stripPunct、既定オン)は、単語分割が句読点を判断材料に使い終えたあとの、最後の1回だけにかける
    (分割の精度には影響させず、かつ text と original の両方に必ず同じ結果が入るよう、ここ1か所にまとめる)。
    2026-10-04: 分けたあとに、音声の長さ dur(秒。行と同じ基準)で切る(clip_rows)・同じ文字だけの行が続いたら1行にまとめる(merge_repeats)。
    whisper.cpp の続いている行の終わりを END_TRIM 秒早める(trim_ends。0.57.1 から既定 0 = かけない)。
    2026-10-07(0.57.1。行の時刻の原則 docs/spec/row-timing-policy.md の ①): 最後に、続いている行(すき間 JOIN_GAP 以下)の終わりを次の行の始まりへ延ばす(join_rows。全エンジン)。
    join=False は時刻を使わない呼び出し(疑わしい所の認識し直し・2つ目のエンジンの候補)。
    0.65.0(2026-10-09)で、行の終わりを音の谷へ寄せる pull_ends(引数 levels・TRANSCRIBE_PULL_ENDS)を消した(既定オフのままだった)"""
    strip = spec.get("stripPunct", True)
    mc = spec.get("splitChars") or _txtext.SPLIT_CHARS
    rows = (p for s in gen for p in (_txtext.split_segment(s, mc) if spec.get("wordSplit") else [s]))
    if dur:
        rows = clip_rows(rows, dur)
    rows = merge_repeats(rows)
    if spec.get("engine") == tx_engines.WhisperCpp.id and END_TRIM > 0:
        rows = trim_ends(rows, END_TRIM)
    if join and JOIN_GAP > 0:
        rows = join_rows(rows, JOIN_GAP)
    for p in rows:
        yield {**p, "text": _txtext.strip_punct(p["text"])} if strip and p.get("text") else p


# ---------- 行の後処理(2026-10-04。ユーザーの報告「行の終わりに次の行の頭の言葉が入る」「動画の長さより後ろに行がある」「ああああ…の行が大量」) ----------
# 測った結果と理由は README の「次の版の変更」と editor/AGENTS.md の「行の後処理」
REP_ROWS = 3          # 同じ1文字だけの行(「ああああ」)がこの数以上続いたら1行にまとめる(本当に叫んでいることもあるので消さない。印「繰り返しの可能性」)
REP_ROW_GAP = 1.0     # まとめる行の間のすき間の上限(秒)
REP_CHAR_KEEP = 10    # 1行の中の同じ文字の続きは、ここまでに縮める(「あああ…」×40 → 10 文字)
# 行の終わりを音の谷へ寄せる pull_ends(0.51.0)は 2026-10-05 に既定でやめ、0.65.0(2026-10-09)で部品ごと消した(早めすぎて言葉の終わりが切れた。履歴 c2dde44 以前)
# whisper.cpp の続いている行の終わりを早める秒(2026-10-05 ユーザーの目安 0.1 秒)。2026-10-07(0.57.1)に既定でやめた(0): 行の時刻の原則の ①
# 「言葉の末を切らない」に反する(人は字幕の終わりを機械より平均 0.15 秒後ろへ直していた。10-05 の目安は「この行だけ再生」で聞くための値)。
# TRANSCRIBE_END_TRIM=0.1 で戻せる(測り直すとき用。plan/line-b-row-timing.md の 7-1)
END_TRIM = tx_engines.env_num("TRANSCRIBE_END_TRIM", 0.0, lo=0.0, hi=0.5, cast=float)
# 続いている行の終わりを次の行の始まりへ延ばす、すき間の上限(秒。2026-10-07 = 0.57.1。原則の ①: 字幕が一瞬消えてまた出るのをやめ、言葉の末を切らない。
# 確かめ済み 22 本の試算で ①末 34% → 20%・②次 6% → 10%。plan/line-b-row-timing.md の 7-2)。TRANSCRIBE_JOIN_GAP=0 でやめる
JOIN_GAP = tx_engines.env_num("TRANSCRIBE_JOIN_GAP", 0.5, lo=0.0, hi=2.0, cast=float)
TRIM_GAP = 0.3        # trim_ends: 次の行の始まりとのすき間がこの秒以下の行(続いている行)だけ、終わりを早める(0.64.0 までの名前は PULL_GAP)
TRIM_MIN = 0.3        # trim_ends: 早めたあとの行の長さの下限(秒。0.64.0 までの名前は PULL_MIN)
_SAME_CHAR_RUN = re.compile(r"(.)\1{%d,}" % REP_CHAR_KEEP)


def _clip_words(p, lo, hi):
    """行の単語("_words" か "words")の時刻を [lo, hi] の中に収める(単語は捨てない = 行の文字と単語の並びは合ったまま)"""
    key = "_words" if p.get("_words") is not None else "words"
    ws = p.get(key)
    if not ws:
        return p
    out = []
    for a, b, t in ws:
        a2 = min(hi, max(lo, a))
        out.append((a2, min(hi, max(a2, b)), t))
    return {**p, key: out}


def clip_rows(rows, dur):
    """音声の長さ dur より後ろの行を捨て、終わりを dur で切る。whisper.cpp は最後の 30 秒の窓の残り(無音で埋めた所)に、
    音声の長さを越える時刻の行を出すことがある(40.7 秒の音声に 56 秒までの「ああああ」18 行。2026-10-04)"""
    for p in rows:
        if p["start"] >= dur:
            continue
        if p["end"] > dur:
            p = _clip_words({**p, "end": dur}, p["start"], dur)
        yield p


def _one_char(text):
    """行の文字(句読点・空白を除く)が同じ1文字の2つ以上の続きなら、その文字。そうでなければ None"""
    k = _letters(text)
    return k[0] if len(k) >= 2 and k == k[0] * len(k) else None


def merge_repeats(rows):
    """同じ1文字だけの行(「ああ」「ああああああ」)が REP_ROWS 行以上続いたら(すき間 REP_ROW_GAP 秒以下)、1行にまとめる(始まり = 最初・終わり = 最後・
    単語はつなぐ・"_rep" = まとめた行の数 → make_flags が「繰り返しの可能性」)。どの行も、同じ文字の続きは REP_CHAR_KEEP 文字までに縮める。
    「早く!早く!…」のように意味のある語の繰り返しの行は、本当に言っていることが多いのでまとめない(印は従来どおり)"""
    buf = []

    def flush():
        if len(buf) >= REP_ROWS:
            words = [w for p in buf for w in (p.get("_words") if p.get("_words") is not None else p.get("words") or [])]
            m = {**buf[0], "end": max(p["end"] for p in buf), "text": "".join(p["text"] for p in buf), "_rep": len(buf)}
            m.pop("words", None)
            m["_words"] = words
            out = [m]
        else:
            out = list(buf)
        buf.clear()
        return [_squash_row(p) for p in out]

    for p in rows:
        c = _one_char(p.get("text"))
        if buf and (c is None or c != _one_char(buf[-1].get("text")) or p["start"] - buf[-1]["end"] > REP_ROW_GAP):
            yield from flush()
        if c is None:
            yield _squash_row(p)
        else:
            buf.append(p)
    yield from flush()


def _squash_row(p):
    """行の中の同じ文字の続きを REP_CHAR_KEEP 文字までに縮める(縮めたら "_rep")"""
    t = p.get("text") or ""
    s = _SAME_CHAR_RUN.sub(lambda m: m.group(1) * REP_CHAR_KEEP, t)
    if s == t:
        return p
    return {**p, "text": s, "_rep": p.get("_rep") or 1}


def _with_next(rows, fix):
    """流れの行の各行に fix(行, 次の行) をかけて流す(次の行を1つ先に読む。最後の行はそのまま)"""
    prev = None
    for p in rows:
        if prev is not None:
            yield fix(prev, p)
        prev = p
    if prev is not None:
        yield prev


def trim_ends(rows, sec):
    """whisper.cpp の行のうち、次の行とのすき間が TRIM_GAP 秒以下の行の終わりを sec 秒だけ早める(行の長さは TRIM_MIN 秒を残す。次の行の始まり・文字は変えない)。
    2026-10-05 ユーザーの目安「前回の作業の前の状態から行末を 0.1 秒早く終わらせる程度」。音の谷へ寄せる pull_ends は早めすぎた(0.65.0 で消した)。
    2026-10-07(0.57.1)から既定ではかけない(END_TRIM = 0。原則の ① に反するため)"""
    def fix(prev, p):
        if p["start"] - prev["end"] <= TRIM_GAP:
            new = round(max(prev["start"] + TRIM_MIN, prev["end"] - sec), 3)
            if new < prev["end"] - 0.005:
                return _clip_words({**prev, "end": new}, prev["start"], new)
        return prev
    return _with_next(rows, fix)


def join_rows(rows, gap=None):
    """続いている行の前の行の終わりを、次の行の始まりへ延ばす(2026-10-07 = 0.57.1。行の時刻の原則 ① 言葉の末を切らない > ② > ③。plan/line-b-row-timing.md の 7-2)。
    0 < 次の始まり − 前の終わり ≤ gap(既定 JOIN_GAP)のときだけ。縮めない・重なり(次の始まりが前の終わりより前)は触らない・最後の行はそのまま・
    文字と単語は変えない(延ばした所は単語の無いすき間)。gap が 0 以下なら何もしない。流れ(生成器)で受けて流す(次の行を1つ先に読む)"""
    gap = JOIN_GAP if gap is None else gap
    return _with_next(rows, lambda prev, p: {**prev, "end": p["start"]} if gap > 0 and 0 < p["start"] - prev["end"] <= gap + 1e-9 else prev)


CONF_KEYS = ("avg_logprob", "no_speech_prob", "compression_ratio")   # 機械の出力 original の各行に残す、認識の自信の度合い(文字起こしの改善の計画 段0-1)


def machine_conf(s):
    """認識の1行の自信の度合い {avg_logprob, no_speech_prob, compression_ratio}(分かるものだけ。小数4桁)。
    original に残して、どの値のときに誤りが多いか(怪しい所だけ別の方法で聞き直す判断の材料)を測れるようにする"""
    out = {}
    for k in CONF_KEYS:
        v = s.get(k)
        if isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v):
            out[k] = round(float(v), 4)
    return out


def post_record():
    """recognition.runs[].post: この認識の行の後処理の設定(0.57.1 から。測る道具 src/eval/tools/eval_timing.py が「版ごと」に分ける。無い記録は 0.57.0 まで)。
    version = 編集の版・endTrim = END_TRIM(whisper.cpp の続いている行の終わりを早める秒)・joinGap = JOIN_GAP(続いている行をつなぐすき間)。
    0.64.0 までは pullEnds(音の谷へ寄せるか)・retime(1 秒丸めの配り直しのモデル | False)も書いた(0.65.0 で部品ごと消した。古い記録の鍵は読むだけ)。
    同じく runs[].retimed(配り直しの数)も 0.65.0 から書かない"""
    return {"version": str(_workdata.SERVER_VERSION or ""), "endTrim": END_TRIM, "joinGap": JOIN_GAP}


def row_words(p, shift=0.0):
    """expand_segments が出した行の単語(split_segment の "_words" か、分けなかった行の "words")→ [[開始, 終了, 文字]](絶対の秒)"""
    return [[round(a + shift, 3), round(b + shift, 3), t] for a, b, t in (p.get("_words") or p.get("words") or [])]
