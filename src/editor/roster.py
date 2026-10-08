"""名簿(hololive-roster.json)と、配信ごとの文脈(文字起こしの改善の計画 段1。plan/line-b-transcription.md(付録))。

- 名簿の members: 配信で実際に呼ばれる形(aliases)・普通の言葉と重なる呼び名(common)・誤りやすい形(misrecognitions。学習用の文書の修正から)
- 配信ごとの文脈: 配信のチャンネル名・コラボ相手のチャンネル名・話者の名前・題名から「その配信に出る人」を決め、その人の名前と呼び名だけを
  認識のヒント(initial_prompt・hotwords)に渡す。入る長さに限りがある(先頭 150 字)ので、出る人に絞る。**題名の文字列そのものは渡さない**
- プロンプトの漏れ出し(S-3): 声の無い所で、ヒントに渡した語だけが字幕に出ることがある。行が渡した語だけでできているかを調べる
サーバー側で使う(numpy などのネイティブの部品は読まない)。
"""
import json
import os
import re
import threading
import unicodedata

PROMPT_LIMIT = 150      # initial_prompt に入れる語の長さ(「用語: 」を除く。以前からの上限。画面の GLOSS_PROMPT と同じ)
HOT_LIMIT = 300         # hotwords の長さ
MAX_MEMBERS = 6         # 文脈に入れる人数の上限(1人 = 名前 + 呼び名 3 つ で 15〜20 字)
ALIASES_PER = 3
DETECT_MIN = 3          # 題名・チャンネル名から呼び名で判定するときの最短の長さ(「ルイ」「トワ」のような短い形は別の語に紛れる)
SOURCES = ("channel", "collab", "speaker", "title")   # 出る人を決めた材料(先の方が強い)
_SEP = re.compile(r"[\s・･\-‐_＿.,、。'\"/|｜!！?？#＃【】\[\]()（）「」『』<>〈〉★☆♪~〜]+")
_cache = {}
_lock = threading.Lock()


def fold(s):
    """照らし合わせ用: NFKC・小文字・カタカナ → ひらがな・空白と区切りを除く"""
    t = unicodedata.normalize("NFKC", str(s or "")).lower()
    t = "".join(chr(ord(c) - 0x60) if "ァ" <= c <= "ヶ" else c for c in t)
    return _SEP.sub("", t)


def _strs(v, n=40, size=40):
    return [str(x).strip()[:size] for x in (v if isinstance(v, list) else [])[:n] if str(x).strip()]


def load(path):
    """-> {"groups": [{"id", "label", "names"}], "members": {名前: {"name", "aliases", "common", "misrecognitions"}}, "people": [人の名前]}。
    読めない・形が違うときは空。ファイルが変わったときだけ読み直す"""
    try:
        st = os.stat(path)
        key = (st.st_mtime_ns, st.st_size)
    except OSError:
        return {"groups": [], "members": {}, "people": []}
    with _lock:
        hit = _cache.get(path)
        if hit and hit[0] == key:
            return hit[1]
    try:
        with open(path, "rb") as f:
            d = json.loads(f.read().decode("utf-8-sig"))
    except (OSError, ValueError):
        d = {}
    d = d if isinstance(d, dict) else {}
    groups, people, members = [], [], {}
    for g in d.get("groups") or []:
        if not isinstance(g, dict):
            continue
        names = _strs(g.get("names"), 100, 60)
        if names and g.get("id") and g.get("label"):
            groups.append({"id": str(g["id"])[:40], "label": str(g["label"])[:80], "names": names})
            if g["id"] != "units":   # グループ名・番組名は人ではない
                people += [n for n in names if n not in people]
    for m in d.get("members") or []:
        if not isinstance(m, dict) or not str(m.get("name") or "").strip():
            continue
        name = str(m["name"]).strip()[:60]
        aliases = _strs(m.get("aliases"))
        mis = [{"wrong": str(x.get("wrong")).strip()[:40], "right": str(x.get("right")).strip()[:40]}
               for x in (m.get("misrecognitions") or [])[:40] if isinstance(x, dict) and str(x.get("wrong") or "").strip() and str(x.get("right") or "").strip()]
        members[name] = {"name": name, "aliases": aliases, "common": [c for c in _strs(m.get("common")) if c in aliases], "misrecognitions": mis}
        if name not in people:
            people.append(name)
    out = {"groups": groups, "members": members, "people": people}
    with _lock:
        _cache[path] = (key, out)
    return out


def _keys(r, strict):
    """[(照らし合わせる形, 名前)](長い形から)。strict = 題名・チャンネル名から探すとき(普通の言葉と重なる呼び名・短い呼び名は使わない)"""
    out = []
    for n in r["people"]:
        out.append((fold(n), n))
        m = r["members"].get(n)
        for a in (m["aliases"] if m else []):
            if strict and (a in m["common"] or len(fold(a)) < DETECT_MIN):
                continue
            out.append((fold(a), n))
    return sorted([k for k in out if k[0]], key=lambda k: -len(k[0]))


def find_in_text(text, r):
    """題名・チャンネル名に出る人(出てくる順)。正式な名前か、普通の言葉と重ならない 3 文字以上の呼び名で探す"""
    t = fold(text)
    if not t:
        return []
    hits = []
    for k, n in _keys(r, True):
        i = t.find(k)
        if i >= 0 and all(n != h[1] for h in hits):
            hits.append((i, n))
    return [n for _i, n in sorted(hits)]


def match_name(name, r):
    """話者の名前(人が付けた名前)-> 名簿の人。正式な名前か呼び名とちょうど同じときだけ(「話者1」は None)"""
    q = fold(name)
    if not q:
        return None
    for k, n in _keys(r, False):
        if k == q:
            return n
    return None


def build_context(r, channel="", collab=(), speakers=(), titles=(), limit=MAX_MEMBERS):
    """-> {"members": [{"name", "from": [材料]}]}。材料の順(チャンネル → コラボ相手 → 話者 → 題名)に並べ、limit 人まで"""
    found = {}

    def add(n, src):
        if n:
            found.setdefault(n, [])
            if src not in found[n]:
                found[n].append(src)

    for n in find_in_text(channel, r):
        add(n, "channel")
    for c in collab or ():
        for n in find_in_text(c, r):
            add(n, "collab")
    for s in speakers or ():
        add(match_name(s, r), "speaker")
    for t in titles or ():
        for n in find_in_text(t, r):
            add(n, "title")
    ranked = sorted(found.items(), key=lambda kv: min(SOURCES.index(s) for s in kv[1]))   # sorted は安定: 同じ強さなら見つけた順
    return {"members": [{"name": n, "from": src} for n, src in ranked[:limit]]}


def member_terms(names, r):
    """出る人 -> ヒントの語(1人ずつ 名前 + 呼び名 3 つ)"""
    out = []
    for n in names:
        m = r["members"].get(n)
        for t in [n] + (m["aliases"][:ALIASES_PER] if m else []):
            if t not in out:
                out.append(t)
    return out


def fit(terms, limit=PROMPT_LIMIT, sep=1):
    """先頭から、区切り(sep 字。「、」なら 1)でつないで limit 字に収まるだけ(語の途中で切らない。画面の glossFit と同じ数え方)"""
    out, n = [], 0
    for t in terms:
        t = str(t).strip()
        if not t or t in out:
            continue
        add = (sep if out else 0) + len(t)
        if n + add > limit:
            break
        out.append(t)
        n += add
    return out


def leak_only(text, terms):
    """行の文字が、ヒントに渡した語(と「用語」)だけでできているか(プロンプトの漏れ出しの疑い。S-3)"""
    t = "".join(ch for ch in fold(text) if unicodedata.category(ch)[0] in "LN")
    keys = {k for k in ("".join(ch for ch in fold(x) if unicodedata.category(ch)[0] in "LN") for x in list(terms or ()) + ["用語"]) if k}
    if not t or not terms:
        return False
    ok = [True] + [False] * len(t)
    lens = sorted({len(k) for k in keys})
    for i in range(1, len(t) + 1):
        ok[i] = any(L <= i and ok[i - L] and t[i - L:i] in keys for L in lens)
    return ok[len(t)]



# ---------------------------------------------------------------- 呼び名の表記ゆれ(2026-10-08。plan/line-b-transcription.md の「10-08 の実験ループ」B)
# whisper は呼び名の長音を「ー」で書く(はあちゃま → はーちゃま・ラミィ → ラミー)ことと、音の同じ漢字を当てる(フブキ → 吹雪・こより → 子寄り)ことがある。
# 名簿の呼び名から「whisper が書きそうな別の綴り → 名簿の綴り」の表を作り、置換辞書と同じ所で当てる(評価用の文書には当てない = autoDict が外れる)。
# 確かめ済み 22 本で名前の再現率 28 → 40/53・余分は増えず、普段の文書 1045 行で変わる行は 0(普通の言葉は壊さない)。無条件の 1 字違いの直しは誤爆するので入れない
KANJI_VARIANTS = {   # 名簿の名前 → [(whisper が当てた漢字, 名簿の綴り)]。測定で見つかったものだけ(増やすときは普段の文書で壊す例が無いか数える)
    "白上フブキ": [("吹雪", "フブキ")], "大空スバル": [("昴", "スバル")], "博衣こより": [("子寄り", "こより"), ("小寄り", "こより")],
}
_VOWEL_ROWS = {"あ": "あかさたなはまやらわがざだばぱゃ", "い": "いきしちにひみりぎじぢびぴ", "う": "うくすつぬふむゆるぐずづぶぷゅ",
               "え": "えけせてねへめれげぜでべぺ", "お": "おこそとのほもよろごぞどぼぽょ"}
_SMALL_VOWELS = {"ぁ": "あ", "ぃ": "い", "ぅ": "う", "ぇ": "え", "ぉ": "お"}
VARIANT_MIN = 3   # これより短い綴りは普通の言葉に紛れるので表に入れない


def _hira(c):
    return chr(ord(c) - 0x60) if "ァ" <= c <= "ヶ" else c


def _kata(c):
    return chr(ord(c) + 0x60) if "ぁ" <= c <= "ゖ" else c


def alias_variants(alias):
    """呼び名 → whisper が書きそうな別の綴り(母音の長音 ↔ ー。ひらがな・カタカナの両方の形)。元の綴りは入れない"""
    outs = set()
    for form in {alias, "".join(_kata(c) for c in alias), "".join(_hira(c) for c in alias)}:
        chars = list(form)
        for i in range(1, len(chars)):
            c, prev = chars[i], chars[i - 1]
            hc, hp = _hira(c), _hira(prev)
            vowel = _SMALL_VOWELS.get(hc, hc)
            if vowel in _VOWEL_ROWS and hp in _VOWEL_ROWS[vowel]:   # 母音の長音 → ー
                v = chars[:]
                v[i] = "ー"
                outs.add("".join(v))
            if c == "ー":                                              # ー → 母音
                for vow, row in _VOWEL_ROWS.items():
                    if hp in row:
                        v = chars[:]
                        v[i] = vow if "ぁ" <= prev <= "ゖ" else _kata(vow)
                        outs.add("".join(v))
    outs.discard(alias)
    return sorted(v for v in outs if len(v) >= VARIANT_MIN)


def variant_pairs(r):
    """名簿 r(load の結果)→ 置換の組 [(別の綴り, 名簿の綴り)](長い綴りから先。置換辞書 parse_replacements と同じ形)。
    名簿の全員の名前と呼び名(common = 普通の言葉と重なる語は入れない)+ KANJI_VARIANTS"""
    pairs, seen = [], set()
    members = r.get("members") or {}
    for name, m in members.items():
        for src, dst in KANJI_VARIANTS.get(name, []):
            if src not in seen:
                seen.add(src)
                pairs.append((src, dst))
        common = set(m.get("common") or [])
        for alias in [name] + list(m.get("aliases") or []):
            if alias in common:
                continue
            for v in alias_variants(alias):
                if v not in seen and v not in members and not any(v == a for mm in members.values() for a in mm.get("aliases") or []):
                    seen.add(v)
                    pairs.append((v, alias))
    return sorted(pairs, key=lambda p: (-len(p[0]), p[0]))
