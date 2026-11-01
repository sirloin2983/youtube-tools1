# -*- coding: utf-8 -*-
"""「編集」のサーバーの部品: 認識のあとの後処理(行の頭の話者名を外す B・声の無い行を捨てる dropSilent・行の終わりを寄せる endSnap)。

11-01 に主の文字起こしを whisper から Haas(speech.cpp)に替え、2 つ目の読み(SenseVoice)で埋める A・末尾の重複と定型の幻覚を捨てる C・
名簿の呼び名の 1 字違いを直す D を消した(ユーザーの決め 10-31 (1)・保管庫 plan/Haas に替える時の変更の一覧.md の段 7)。前の文書に残っている
印(FILL_FLAG・FILL_NAME_FLAG)と元の文字(行の fill = {"from", "by"})は、画面の「別の読み」の札で戻せるようにそのまま読む。
  B fill_strip_names  行の頭の「名前:」(whisper が字幕の学習データの形を出す)を外す。名前が名簿・用語集・文脈の語に当たるか、かな・カタカナだけの短い語のとき。
                 設定 stripNames(既定オン)。印 FILL_SPK_FLAG・行の fill = {"from": 元の文字, "by": "name"}
  fill_drop_silent  声を分けて(separate.py の Spleeter)声と 1 割も重ならない行を捨てる(束 transcribe.dropSilent。印 fill.dropped)
  fill_snap_ends    同じ区間で行の終わりを区間の終わりへ ±0.3 秒寄せる(束 transcribe.endSnap・既定オフ。印 fill.endSnap)
名前は fill_ / FILL_ / _fill_ で始める(serve.py の _ED_MODULES。ほかの部品と重ならないように)。
標準ライブラリ・ytt・同じパッケージの兄弟(roster・separate・tx_engines・txbase)だけを読む。名簿のファイルの場所は呼ぶたびに roster.ROSTER から。
"""
import re
import unicodedata

from ytt import errors as _errors, jobs as _heavy   # 取り消し Cancelled(RS2-8a。持ち主から直に読む)
from . import postproc as _postproc, roster as _roster, separate, tx_engines  # postproc = 単語の時刻を行の中へ _clip_words(endSnap)・ separate = 分けた声の区間(dropSilent)
from ytt import txbase as _txbase

FILL_FLAG = "別の読みで埋めた(元の文字は「別の読み」の札)"
FILL_NAME_FLAG = "名簿の呼び名に直した(別のエンジンも同じ呼び名)"
FILL_SILENT_VOICE = 0.1  # 声の無い行: 分けた声の区間と重なる割合がこれ未満の行を捨てる(dropSilent。3 割では本当の声を捨てた)
FILL_SNAP_END = 0.3      # 行の終わりを分けた声の区間の終わりへ寄せる幅(秒。endSnap。row-start-study の物差しで ±0.2〜0.3 が良かった)
FILL_SPK_BY = "name"       # B: 行の fill の by(話者名を外した)
FILL_SPK_NOTE = "話者名を外した"   # 範囲・全体の再認識の印(元の文字は残さない)
FILL_SPK_FLAG = FILL_SPK_NOTE + "(元の文字は「別の読み」の札)"
FILL_SPK_KANA_MAX = 8      # B: 名簿に無い名前は、かな・カタカナだけのこの字数まで
_FILL_SPK_RE = re.compile(r"^\s*([^\s:：「」『』()（）\[\]【】]{1,16})\s*[:：]\s*(\S.*)$", re.S)
_FILL_SPK_KANA = re.compile(r"^[ぁ-ゖァ-ヺー・]{1,%d}$" % FILL_SPK_KANA_MAX)
_FILL_SPK_HONOR = re.compile(r"(さん|ちゃん|くん|君|様|さま|先輩|せんぱい)$")


def fill_norm(text):
    """比べる用の文字: NFKC → 文字と数字だけ(記号・空白を除く)"""
    return "".join(ch for ch in unicodedata.normalize("NFKC", str(text or "")) if unicodedata.category(ch)[0] in "LN")


def _fill_overlap(a0, a1, b0, b1):
    return max(0.0, min(a1, b1) - max(a0, b0))


def fill_voice_frac(g, spans):
    """行 g の長さのうち、声の区間 spans [(始め, 終わり)] と重なる割合"""
    a, b = float(g["start"]), float(g["end"])
    if b <= a:
        return 1.0 if any(x <= a <= y for x, y in spans) else 0.0
    return sum(_fill_overlap(a, b, x, y) for x, y in spans) / (b - a)


def fill_after_rows(job, spec, rows, wav, total):
    """run_job の行(expand_segments のあと)に、声の無い行を捨てる(dropSilent)・行の終わりを寄せる(endSnap)を当てる(全エンジン)。
    -> (行, 記録 {"dropped"?, "endSnap"?} か None(どちらもオフ), None)。3 つ目は前の 2 つ目の読み(A・D)の窓の読み手の場所で、今は常に None"""
    if not (spec.get("dropSilent") or spec.get("endSnap")):
        return rows, None, None
    rec = {}
    return fill_drop_silent(job, rows, wav, rec, drop=bool(spec.get("dropSilent")), snap=bool(spec.get("endSnap"))), rec, None

# ---------- B: 行の頭の話者名を外す(「Aさん:発言」のような形を直す) ----------
def fill_spk_key(s):
    """話者名を比べる用: NFKC・前後の空白を除く"""
    return unicodedata.normalize("NFKC", str(s or "")).strip()

def fill_spk_names(spec):
    """外してよい名前: 名簿の名前と呼び名(common も含む = 直後に「:」が来るときだけ使う)・用語集・配信ごとの文脈の語(友人が指定した名前もここに入る)"""
    names = set()
    try:
        r = _roster.load(_roster.ROSTER)
        for name, m in (r.get("members") or {}).items():
            m = m if isinstance(m, dict) else {}
            names.update(fill_spk_key(a) for a in [name] + list(m.get("aliases") or []))
    except (OSError, ValueError, TypeError, KeyError, AttributeError) as e:
        _txbase.log.warning("名簿を読めないので、話者名は名簿なしで判断します: %s", e)
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

def fill_head_stripper(spec):
    """範囲・全体の再認識で、行の頭の「名前:」を外す決まり(B)。recognize.finish_range_lines が使う
    (同じ ① の recognize が直に呼ぶ)。-> None(設定 stripNames が明示のオフ・評価用)か、split(文字) -> (本文, 外したときの印 FILL_SPK_NOTE か None)"""
    if spec.get("stripNames", True) is False or spec.get("evalSet"):
        return None
    names = fill_spk_names(spec)

    def split(text):
        text, head = fill_spk_split(text, names)
        return text, (FILL_SPK_NOTE if head else None)
    return split

def fill_snap_ends(rows, spans, rec, reach=FILL_SNAP_END):
    """行の終わりを、reach 秒以内でいちばん近い分けた声の区間の終わりへ寄せる(始まり + 0.1 秒より後・次の行の始まりを越えない)。
    動かした行は rec["endSnap"] = {n, rows(最初の 200 = 始まり・元の終わり・新しい終わり)}"""
    ends, moved = sorted(b for _a, b in spans), []
    for k, g in enumerate(rows):
        e, s = float(g["end"]), float(g["start"])
        cap = float(rows[k + 1]["start"]) if k + 1 < len(rows) else float("inf")
        c = [t for t in ends if abs(t - e) <= reach and s + 0.1 < t <= max(cap, e)]
        t = min(c, key=lambda t: abs(t - e)) if c else e
        if abs(t - e) > 1e-6:
            moved.append({"start": round(s, 2), "from": round(e, 2), "to": round(t, 2)})
            g["end"] = t
            if t < e:   # 縮めたら単語の時刻も行の中へ(残すと記録に行の終わりの後の単語が残る)
                rows[k] = _postproc._clip_words(g, s, t)
    rec["endSnap"] = {"n": len(moved), "rows": moved[:200]}
    return rows

def fill_drop_silent(job, rows, wav, rec, drop=True, snap=False):
    """分けた声(separate.voice_spans)と FILL_SILENT_VOICE も重ならない行を捨てる(束 transcribe.dropSilent・既定オフ。確かめ済み 23 本で
    組 A 10.35 → 9.89%・組 B 12.45 → 11.70%・抜け・時刻は両方の組で同じ = 資料の git:before-1028-cleanup:plan/voice-separation-1022.md の 2)。
    捨てた行は rec["dropped"] = {n, db, rows(最初の 200)} に残す。分けられない(型が無い・落ちた)・区間が無ければ警告して捨てない。
    snap(束 transcribe.endSnap・既定オフ)なら残した行の終わりを分けた声の区間の終わりへ寄せる(fill_snap_ends)"""
    phase = job.get("phase")
    job["phase"] = "声を分けて声の無い行を探し中"
    try:
        spans = separate.voice_spans(job, wav)
    except _heavy.Cancelled:
        raise
    except (_errors.ApiError, tx_engines.EngineError, separate.worker_client.WorkerError, OSError, MemoryError, RuntimeError) as e:   # WorkerError = ワーカーの中で型が無い・落ちた(文字起こしは止めない)
        _txbase.add_warning(job, "声を分けられなかったので声の無い行は捨てていません: " + str(getattr(e, "message", e))[:200])
        return rows
    finally:
        job["phase"] = phase
    if not spans:   # 区間が 0 = 捨てない(かけたことは記録に残す)
        _txbase.add_warning(job, "分けた声に区間が無かったので、声の無い行は捨てていません")
        if drop:
            rec["dropped"] = {"n": 0, "db": -separate.SEP_DB, "rows": [], "why": "no-voice"}
        return rows
    keep, out = [], []
    for g in rows:
        (out if drop and fill_voice_frac(g, spans) < FILL_SILENT_VOICE else keep).append(g)
    if drop:
        rec["dropped"] = {"n": len(out), "db": -separate.SEP_DB,
                          "rows": [{"start": round(float(g["start"]), 2), "end": round(float(g["end"]), 2), "text": str(g.get("text") or "")[:200]} for g in out[:200]]}
    return fill_snap_ends(keep, spans, rec) if snap else keep
