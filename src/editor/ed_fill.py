# -*- coding: utf-8 -*-
"""「編集」のサーバーの部品: 認識のあとの後処理(10-08 の実験ループの A・C・D。plan/line-b-transcription.md の「10-08 の実験ループ」。編集 0.60.0)。

ねらい: whisper の結果のうち「機械どうしを突き合わせれば直せる」所だけを自動で直して、校正を短くする(ユーザー 10-08「精度が上がるなら自動で書き換えてよい」)。
  A fill_apply   文字の少ない行(FILL_MIN_SEC 秒以上で、記号を除き同じ字の繰り返しを 1 字に縮めた文字数が FILL_MAX_CPS 字/秒 未満、または繰り返しで縮む行
                 = 声が重なって片方しか書けていない所)の窓(前後 FILL_PAD 秒)を SenseVoice(tx_engines.SenseVoice。CPU・1 窓 0.1 秒)で読み、
                 字数が FILL_RATIO 倍以上なら置き換える。確かめ済み 22 本で CER 13.0 → 11.8%・重なり区間の抜け 109 → 51 字
  B fill_strip_names  行の頭の「名前:」(whisper が字幕の学習データの形を出す)を外す。名前が名簿・用語集・文脈の語に当たるか、かな・カタカナだけの短い語のとき。
                 設定 stripNames(既定オン・autoFill とは別のスイッチ)。印 FILL_SPK_FLAG・行の fill = {"from": 元の文字, "by": "name"}(0.67.0)
  C fill_clean_tail   前の行の末尾だけをもう一度出した行(窓の境目の重複)を捨てる(run_job)
    fill_clean_turns  定型の幻覚(FILL_STOCK)で、声の区間(話者判別の turns)と FILL_MIN_VOICE も重ならない行を捨てる(apply_diarization = 判別のあとだけ。
                 判別を回さない文書では捨てない)。22 本で 13.0 → 12.8%
  D fill_agree   SenseVoice の全体の読みに名簿の呼び名(FILL_AGREE_MIN 字以上・common は除く)がそのまま出ていて、同じ時間の行にその呼び名が無く、
                 同じ長さで 1 字だけ違う並び(かなの違いは数えない)があれば、その呼び名に直す。無条件の 1 字違い直しは誤爆した(11.3〜13.7%)ので
                 別のエンジンの一致を条件にする。名前の再現 +4
決まり:
  - 設定 autoFill(「認識の設定」。既定オン。文字起こしの指定 validate_job)。評価用の文書には当てない(autoDict と同じ = 定点の正解が 2 つのエンジンに寄らない)
  - 置き換えた・直した行には印(FILL_FLAG / FILL_NAME_FLAG)と元の文字(行の fill = {"from": 元の文字, "by": "sense-voice"})を残す = 画面の「別の読み」の札で戻せる。
    whisper の生の結果は <id>.asr.json にそのまま残る(後から「後処理あり/なし」を同じ文書で測り直せる)
  - SenseVoice が使えない(sherpa-onnx が無い・取得できない)ときは文字起こしを失敗にせず、警告を出して whisper の結果のまま
  - 置き換えた・捨てた数は記録に残す(recognition.runs[].fill・diarization.fillDropped)
名前は fill_ / FILL_ / _fill_ で始める(serve.py の _ED_MODULES の最後。ほかの部品と重ならないように)。ほかの部品は ed_xxx.名前 の形で呼ぶたびに読む。
"""
import os
import re
import unicodedata

import ed_speakers  # noqa: E402,F401
from pipeline.transcribe import worker_client  # noqa: E402   wav を読まずに渡す形 read_wav_f32(RS2-6)・モデルの読み込み load_model・filter_kwargs(RS2-8a)
from ytt import jobs as _heavy  # noqa: E402   取り消し Cancelled(RS2-8a。持ち主から直に読む)
import ed_state  # noqa: E402,F401
from pipeline.transcribe import roster as _roster  # noqa: E402,F401
from pipeline.transcribe import tx_engines  # noqa: E402,F401   名前だけ(ネイティブの部品は読み込まない)

FILL_ENGINE, FILL_MODEL = "sense-voice", "sense-voice-small"   # 2 つ目の読み(tx_engines.SenseVoice)
FILL_LANGS = ("ja", "en", "zh", "ko")   # SenseVoice に言語として渡せるもの(それ以外は auto)
FILL_MIN_SEC = 2.0       # A: この秒以上の行だけ
FILL_MAX_CPS = 1.5       # A: 縮めた文字数がこの字/秒 未満なら「文字が少ない」
FILL_RUNNY = 0.6         # A: 同じ字の繰り返しを縮めて文字数がこの割合以下になる行(「うわああああ」。4 字以上)も対象
FILL_PAD = 0.5           # A: 窓の前後の余白(秒)
FILL_RATIO = 3.0         # A: 別の読みの字数が元の何倍以上なら置き換えるか
FILL_MAX_ROWS = 60       # A: 1 回の文字起こしで読む窓の上限(長い文書で遅くならないように)
FILL_FLAG = "別の読みで埋めた(元の文字は「別の読み」の札)"
FILL_NAME_FLAG = "名簿の呼び名に直した(別のエンジンも同じ呼び名)"
FILL_STOCK = ("ご視聴ありがとうございました", "チャンネル登録", "ありがとうございました", "おやすみなさい", "字幕", "最後まで", "ご視聴")   # C: 定型の幻覚(10-08 に測った文)
FILL_MIN_VOICE = 0.3     # C: 行の長さのうち声の区間と重なる割合がこれ未満なら幻覚
FILL_DUP_MIN = 6         # C: 前の行の末尾の重複とみなす最小の文字数
FILL_AGREE_MIN = 3       # D: 呼び名の最小の文字数
FILL_AGREE_SLACK = 0.5   # D: 行と 2 つ目のエンジンの行の時間の重なりの余裕(秒)
FILL_AGREE_MAX_SEC = 1800   # D: 全体を読むのはこの秒までの文書(CPU で音声の約 2% の時間)
_FILL_REP3 = re.compile(r"(.)\1{2,}")
FILL_SPK_BY = "name"       # B: 行の fill の by(話者名を外した)
FILL_SPK_NOTE = "話者名を外した"   # 範囲・全体の再認識・疑わしい所の認識し直しの印(元の文字は残さない)
FILL_SPK_FLAG = FILL_SPK_NOTE + "(元の文字は「別の読み」の札)"
FILL_SPK_KANA_MAX = 8      # B: 名簿に無い名前は、かな・カタカナだけのこの字数まで
_FILL_SPK_RE = re.compile(r"^\s*([^\s:：「」『』()（）\[\]【】]{1,16})\s*[:：]\s*(\S.*)$", re.S)
_FILL_SPK_KANA = re.compile(r"^[ぁ-ゖァ-ヺー・]{1,%d}$" % FILL_SPK_KANA_MAX)
_FILL_SPK_HONOR = re.compile(r"(さん|ちゃん|くん|君|様|さま|先輩|せんぱい)$")


# ---------- 文字の数え方 ----------
def fill_norm(text):
    """比べる用の文字: NFKC → 文字と数字だけ(記号・空白を除く)"""
    return "".join(ch for ch in unicodedata.normalize("NFKC", str(text or "")) if unicodedata.category(ch)[0] in "LN")


def fill_chars(text):
    """A の文字数: 同じ字が 3 回以上続く所は 1 字に縮めて数える(「うわああああ」= 2 字)"""
    return len(_FILL_REP3.sub(r"\1", fill_norm(text)))


def fill_sparse_row(row):
    """A の対象の行か: FILL_MIN_SEC 秒以上で、縮めた文字数が FILL_MAX_CPS 字/秒 未満、または同じ字の繰り返しで縮む行(FILL_RUNNY)"""
    try:
        dur = float(row["end"]) - float(row["start"])
    except (KeyError, TypeError, ValueError):
        return False
    if dur < FILL_MIN_SEC:
        return False
    raw = fill_norm(row.get("text"))
    n = fill_chars(row.get("text"))
    runny = len(raw) >= 4 and n <= FILL_RUNNY * len(raw)
    return runny or n / max(dur, 0.01) < FILL_MAX_CPS


def _fill_overlap(a0, a1, b0, b1):
    return max(0.0, min(a1, b1) - max(a0, b0))


# ---------- A: 文字の少ない行の窓を別の読みで埋める ----------
def fill_apply(rows, read, total):
    """rows(expand_segments の行。wav の秒)のうち対象の行(fill_sparse_row)の窓を read(s0, e0) -> [{start, end, text}](wav の秒)で読み、
    別の読み(行の半分以上が元の行の時間に入るもの)の字数が元の FILL_RATIO 倍以上なら置き換える。
    -> (新しい行の一覧(時刻の順), {"windows": 読んだ窓, "rows": 置き換えた行, "added": 足した行})。置き換えた行は fill = {"from": 元の文字, "by": FILL_ENGINE}"""
    out, stats = list(rows), {"windows": 0, "rows": 0, "added": 0}
    targets = [r for r in rows if r.get("text") and fill_sparse_row(r)][:FILL_MAX_ROWS]
    for r in targets:
        s0 = max(0.0, float(r["start"]) - FILL_PAD)
        e0 = float(r["end"]) + FILL_PAD
        if total:
            e0 = min(float(total), e0)
        if e0 - s0 < 0.5:
            continue
        stats["windows"] += 1
        cand = [c for c in read(s0, e0) if str(c.get("text") or "").strip()
                and _fill_overlap(c["start"], c["end"], r["start"], r["end"]) >= 0.5 * max(0.01, c["end"] - c["start"])]
        n = fill_chars(r["text"])
        nc = sum(fill_chars(c["text"]) for c in cand)
        if not cand or nc < max(n + 1, FILL_RATIO * n):
            continue
        new = [{"start": round(float(c["start"]), 3), "end": round(float(c["end"]), 3), "text": str(c["text"]).strip(), "words": [],
                "avg_logprob": None, "no_speech_prob": None, "compression_ratio": None, "fill": {"from": r["text"], "by": FILL_ENGINE}} for c in cand]
        out = [x for x in out if x is not r] + new
        stats["rows"] += 1
        stats["added"] += len(new)
    out.sort(key=lambda x: (x["start"], x["end"]))
    return out, stats


# ---------- C: 余分の掃除 ----------
def fill_clean_tail(rows):
    """前の行の末尾だけをもう一度出した行(FILL_DUP_MIN 字以上・前の行より短い・前の行の末尾と同じ)を捨てる -> (行, 捨てた数)"""
    out, prev, n = [], "", 0
    for r in rows:
        t = fill_norm(r.get("text"))
        if t and len(t) >= FILL_DUP_MIN and len(t) < len(prev) and prev.endswith(t):
            n += 1
            continue
        out.append(r)
        prev = t
    return out, n


def fill_stock(text):
    """定型の幻覚の文か(FILL_STOCK のどれかを含む)"""
    n = fill_norm(text)
    return bool(n) and any(fill_norm(x) in n for x in FILL_STOCK)


def fill_voice_frac(g, spans):
    """行 g の長さのうち、声の区間 spans [(始め, 終わり)] と重なる割合"""
    a, b = float(g["start"]), float(g["end"])
    if b <= a:
        return 1.0 if any(x <= a <= y for x, y in spans) else 0.0
    return sum(_fill_overlap(a, b, x, y) for x, y in spans) / (b - a)


def fill_clean_turns(doc, turns, offset):
    """判別のあと: 定型の幻覚の行で、声の区間(turns = [(始め, 終わり, 話者)]。wav の秒 + offset = 文書の秒)と FILL_MIN_VOICE も重ならないものを捨てる。
    autoFill で作った文書(params.autoFill)だけ・評価用は除く・校正済み・人や辞書が直した行(機械の出力 original と違う)・メモや下書き・カット済・字幕に出さない行は捨てない。
    -> 捨てた数(doc["segments"] を書き換える。original はそのまま)"""
    if not (doc.get("params") if isinstance(doc.get("params"), dict) else {}).get("autoFill") or doc.get("evalSet") is True:
        return 0
    spans = [(float(a) + offset, float(b) + offset) for a, b, *_rest in turns if float(b) > float(a)]
    if not spans or not isinstance(doc.get("original"), list):
        return 0
    machine = {(round(float(o["start"]), 2), round(float(o["end"]), 2)): o.get("text") for o in doc["original"] if isinstance(o, dict)}
    keep, n = [], 0
    for g in doc.get("segments") or []:
        if (isinstance(g, dict) and fill_stock(g.get("text")) and g.get("proofed") is not True and not g.get("tags") and not g.get("noSub")
                and not g.get("draft") and g.get("cutState") != "cut"
                and machine.get((round(float(g["start"]), 2), round(float(g["end"]), 2))) == g.get("text")
                and fill_voice_frac(g, spans) < FILL_MIN_VOICE):
            n += 1
            continue
        keep.append(g)
    if n:
        doc["segments"] = keep
    return n


# ---------- B: 行の頭の話者名を外す(0.67.0。10-09 ユーザー報告「『Aさん:発言』のような形になってる」) ----------
def fill_spk_key(s):
    """話者名を比べる用: NFKC・前後の空白を除く"""
    return unicodedata.normalize("NFKC", str(s or "")).strip()


def fill_spk_names(spec):
    """外してよい名前: 名簿の名前と呼び名(common も含む = 直後に「:」が来るときだけ使う)・用語集・配信ごとの文脈の語(友人が指定した名前もここに入る)"""
    names = set()
    try:
        r = _roster.load(ed_state.ROSTER)
        for name, m in (r.get("members") or {}).items():
            m = m if isinstance(m, dict) else {}
            names.update(fill_spk_key(a) for a in [name] + list(m.get("aliases") or []))
    except (OSError, ValueError, TypeError, KeyError, AttributeError) as e:
        ed_state.log.warning("名簿を読めないので、話者名は名簿なしで判断します: %s", e)
    for t in list(spec.get("glossary") or []) + list((spec.get("context") or {}).get("terms") or []):
        names.add(fill_spk_key(t))
    names.discard("")
    return names


def fill_spk_split(text, names):
    """行の頭の「名前:」か「名前：」を分ける -> (本文, 外した頭) か (text, None)。
    外すのは、名前が names に当たる(敬称を除いても)か、かな・カタカナだけの FILL_SPK_KANA_MAX 字以下で、直後に本文(文字か数字)が続くときだけ"""
    m = _FILL_SPK_RE.match(str(text or ""))
    if not m:
        return text, None
    name, body = m.group(1), m.group(2).strip()
    key = fill_spk_key(name)
    known = key in names or _FILL_SPK_HONOR.sub("", key) in names
    if not fill_norm(body) or not (known or _FILL_SPK_KANA.match(key)):
        return text, None
    return body, str(text)[:len(str(text)) - len(m.group(2))]


def _fill_spk_words(words, head):
    """頭の単語(3 つ組 [始め, 終わり, 文字])のうち、外した頭の字だけでできたものを除く。境目が単語の途中なら単語はそのまま"""
    def chars(w):
        return fill_norm(w[2] if isinstance(w, (list, tuple)) and len(w) > 2 else "")
    want, acc, k = fill_norm(head), "", 0
    while k < len(words) and acc != want:
        acc += chars(words[k])
        if not want.startswith(acc):
            return words
        k += 1
    while k < len(words) and not chars(words[k]):   # 名前のあとの「:」だけの単語
        k += 1
    return words[k:] if acc == want and k < len(words) else words


def fill_strip_names(spec, rows):
    """run_job の行(expand_segments のあと・C と A の前)の頭の話者名を外す(設定 stripNames。評価用は validate_job が外す)。
    whisper が字幕の学習データの「名前:」の形を出す(ヒントが無くても)。外した行は fill = {"from": 元の文字, "by": FILL_SPK_BY}(画面の「別の読み」の札で戻せる)。
    whisper の生の結果 <id>.asr.json はそのまま -> (行, 外した数)"""
    if not spec.get("stripNames"):
        return rows, 0
    names, n = fill_spk_names(spec), 0
    for r in rows:
        body, head = fill_spk_split(r.get("text"), names)
        if head is None:
            continue
        if not isinstance(r.get("fill"), dict):
            r["fill"] = {"from": r["text"], "by": FILL_SPK_BY}
        r["text"] = body
        for k in ("_words", "words"):
            if isinstance(r.get(k), list) and r[k]:
                r[k] = _fill_spk_words(r[k], head)
        n += 1
    return rows, n


# ---------- D: 別のエンジンも同じ呼び名なら 1 字違いを直す ----------
def fill_aliases(r=None):
    """名簿の呼び名(名前 + aliases。common = 普通の言葉と重なる語は除く・FILL_AGREE_MIN 字以上)。r = 名簿(無ければ読む)"""
    r = _roster.load(ed_state.ROSTER) if r is None else r
    out = set()
    for name, m in (r.get("members") or {}).items():
        m = m if isinstance(m, dict) else {}
        common = set(m.get("common") or [])
        for a in [name] + list(m.get("aliases") or []):
            if isinstance(a, str) and len(a) >= FILL_AGREE_MIN and a not in common:
                out.add(a)
    return out


def fill_kana(t):
    """かなの違いを数えないための形(カタカナ → ひらがな)"""
    return "".join(_roster._hira(c) for c in str(t or ""))


def fill_agree(segs, others, aliases):
    """others(2 つ目のエンジンの行 [{start, end, text}]。文書の秒)に呼び名がそのまま出ていて、同じ時間(FILL_AGREE_SLACK)の行(校正済みでない)にその呼び名が無く、
    同じ長さで 1 字だけ違う並びがあれば、その呼び名に直す。直した行は fill(元の文字。A で埋めた行はそのまま)と FILL_NAME_FLAG。-> 直した数"""
    n = 0
    al = sorted(aliases, key=len, reverse=True)
    for o in others:
        ot = str(o.get("text") or "")
        hits = [a for a in al if a in ot]
        if not hits:
            continue
        for g in segs:
            if g.get("proofed") is True or g["end"] <= o["start"] - FILL_AGREE_SLACK or g["start"] >= o["end"] + FILL_AGREE_SLACK:
                continue
            t = str(g.get("text") or "")
            for a in hits:
                if a in t or fill_kana(a) in fill_kana(t):
                    continue
                size, na = len(a), fill_kana(a)
                for i in range(0, len(t) - size + 1):
                    if sum(1 for x, y in zip(fill_kana(t[i:i + size]), na) if x != y) == 1:
                        g.setdefault("fill", {"from": t, "by": FILL_ENGINE})
                        t = t[:i] + a + t[i + size:]
                        g["text"] = t
                        if FILL_NAME_FLAG not in str(g.get("flag") or ""):
                            g["flag"] = "、".join(x for x in (FILL_NAME_FLAG, str(g.get("flag") or "")) if x)[:100]
                        n += 1
                        break
    return n


# ---------- run_job から呼ぶ入口 ----------
def fill_reader(job, spec, wav):
    """窓を読む関数 read(s0, e0) -> [{start, end, text}](wav の秒)。疑似(TRANSCRIBE_BACKEND=fake)は環境変数 TRANSCRIBE_FAKE_FILL の文字を窓いっぱいの 1 行に(空 = 行なし)。
    本物は SenseVoice を認識ワーカーに読み込み(主のモデルは手放さない = tx_engines.Engine.light)、窓のサンプルの範囲だけを渡す"""
    if ed_state.backend_name() == "fake":
        text = os.environ.get("TRANSCRIBE_FAKE_FILL", "")
        return lambda s0, e0: [{"start": s0, "end": e0, "text": text}] if text else []
    if not ed_speakers.has_sherpa():
        raise ed_state.ApiError("no_sherpa", "別の読み(SenseVoice)の部品 sherpa-onnx が入っていません(setup\\install-diarize.bat を実行してください)", 400)
    phase = job.get("phase")
    model, _dev = worker_client.load_model(FILL_MODEL, job, "cpu", engine=FILL_ENGINE)
    job["phase"] = phase
    audio = worker_client.read_wav_f32(wav)
    lang = spec.get("language") if spec.get("language") in FILL_LANGS else "auto"
    kw = worker_client.filter_kwargs(model, {"language": lang})

    def read(s0, e0):
        chunk = audio[int(s0 * 16000):int(e0 * 16000)]
        if len(chunk) < 1600:
            return []
        segs, _info = model.transcribe(chunk, **kw)
        return [{"start": float(s.start) + s0, "end": float(s.end) + s0, "text": str(s.text or "").strip()} for s in segs]
    return read


def fill_after_rows(job, spec, rows, wav, total):
    """run_job の行(expand_segments のあと)に C(末尾の重複)と A(別の読みで埋める)を当てる。
    -> (行, 記録 {engine, windows, rows, added, dup, agree} か None(設定オフ), 窓を読む関数 か None(読めない = 警告を job に足して whisper のまま))"""
    if not spec.get("autoFill"):
        return rows, None, None
    rows, dup = fill_clean_tail(rows)
    rec = {"engine": FILL_ENGINE, "windows": 0, "rows": 0, "added": 0, "dup": dup, "agree": 0}
    phase = job.get("phase")
    try:
        read = fill_reader(job, spec, wav)
        job["phase"] = "文字の少ない行を別の読みで埋め中"
        rows, st = fill_apply(rows, read, total)
    except _heavy.Cancelled:
        raise
    except (ed_state.ApiError, tx_engines.EngineError) as e:
        job["phase"] = phase
        ed_state.add_warning(job, "別の読みで埋められませんでした(whisper の結果のまま): " + str(getattr(e, "message", e))[:200])
        return rows, rec, None
    job["phase"] = phase
    rec.update(st)
    return rows, rec, read


def fill_agree_doc(job, segs, read, total, spec):
    """D を文書の行に当てる: SenseVoice で全体を読み(FILL_AGREE_MAX_SEC まで)、名簿の呼び名(fill_aliases)で fill_agree。-> 直した数(名簿が無い・読めなければ 0)"""
    try:
        aliases = fill_aliases()
    except (OSError, ValueError, TypeError, KeyError) as e:
        ed_state.log.warning("名簿を読めないので呼び名の直しはしません: %s", e)
        return 0
    if not aliases or not segs or not total or float(total) > FILL_AGREE_MAX_SEC:
        return 0
    phase = job.get("phase")
    try:
        job["phase"] = "別のエンジンで名簿の呼び名を確かめ中"
        rows = read(0.0, float(total))
    except _heavy.Cancelled:
        raise
    except (ed_state.ApiError, tx_engines.EngineError) as e:
        ed_state.add_warning(job, "別のエンジンで名簿の呼び名を確かめられませんでした: " + str(getattr(e, "message", e))[:200])
        return 0
    finally:
        job["phase"] = phase
    shift = float(spec.get("start") or 0.0)
    return fill_agree(segs, [{"start": r["start"] + shift, "end": r["end"] + shift, "text": r["text"]} for r in rows], aliases)
