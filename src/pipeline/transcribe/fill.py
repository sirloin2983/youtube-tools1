# -*- coding: utf-8 -*-
"""「編集」のサーバーの部品: 認識のあとの後処理(A・C・D。notes:plan/line-b-transcription.md の「10-08 の実験ループ」)。

ねらい: whisper の結果のうち「機械どうしを突き合わせれば直せる」所だけを自動で直して、校正を短くする(ユーザー決定「精度が上がるなら自動で書き換えてよい」)。
  A fill_apply   文字の少ない行(FILL_MIN_SEC 秒以上で、記号を除き同じ字の繰り返しを 1 字に縮めた文字数が FILL_MAX_CPS 字/秒 未満、または繰り返しで縮む行
                 = 声が重なって片方しか書けていない所)の窓(前後 FILL_PAD 秒)を SenseVoice(tx_engines.SenseVoice。CPU・1 窓 0.1 秒)で読み、
                 字数が FILL_RATIO 倍以上なら置き換える。確かめ済み 22 本で CER 13.0 → 11.8%・重なり区間の抜け 109 → 51 字。
                 置き換えた行の頭・尻が前後の行と同じ字(窓の余白で入った隣の言葉)は落とす(FILL_TRIM_EDGE・印 fill.trim。10-26)
  B fill_strip_names  行の頭の「名前:」(whisper が字幕の学習データの形を出す)を外す。名前が名簿・用語集・文脈の語に当たるか、かな・カタカナだけの短い語のとき。
                 設定 stripNames(既定オン・autoFill とは別のスイッチ)。印 FILL_SPK_FLAG・行の fill = {"from": 元の文字, "by": "name"}
  C fill_clean_tail   前の行の末尾だけをもう一度出した行(窓の境目の重複)を捨てる(run_job)
    fill_clean_turns  定型の幻覚(FILL_STOCK)で、声の区間(話者判別の turns)と FILL_MIN_VOICE も重ならない行を捨てる(apply_diarization = 判別のあとだけ。
                 判別を回さない文書では捨てない)。22 本で 13.0 → 12.8%
  D fill_agree   SenseVoice の全体の読みに名簿の呼び名(FILL_AGREE_MIN 字以上・common は除く)がそのまま出ていて、同じ時間の行にその呼び名が無く、
                 同じ長さで 1 字だけ違う並び(かなの違いは数えない)があれば、その呼び名に直す。無条件の 1 字違い直しは誤爆した(11.3〜13.7%)ので
                 別のエンジンの一致を条件にする。名前の再現 +4。違う 1 字が っ などの小さい字(呼び名の別の書き方)・置き換えると同じ字が
                 並ぶ物は直さない(FILL_AGREE_SMALL_SKIP。「みこっち」→「みこちち」が確かめるで 3 件。10-26)
決まり:
  - 設定 autoFill(「認識の設定」。既定オン。文字起こしの指定 validate_job)。評価用の文書には当てない(autoDict と同じ = 定点の正解が 2 つのエンジンに寄らない)
  - 置き換えた・直した行には印(FILL_FLAG / FILL_NAME_FLAG)と元の文字(行の fill = {"from": 元の文字, "by": "sense-voice"})を残す = 画面の「別の読み」の札で戻せる。
    whisper の生の結果は <id>.asr.json にそのまま残る(後から「後処理あり/なし」を同じ文書で測り直せる)
  - SenseVoice が使えない(sherpa-onnx が無い・取得できない)ときは文字起こしを失敗にせず、警告を出して whisper の結果のまま
  - 置き換えた・捨てた数は記録に残す(recognition.runs[].fill・diarization.fillDropped)
名前は fill_ / FILL_ / _fill_ で始める(serve.py の _ED_MODULES。ほかの部品と重ならないように)。

S.fill_* は serve の名前の受付で読める。
  fill_drop_silent  声を分けて(separate.py の Spleeter)声と 1 割も重ならない行を捨てる(A → C のあと。束 transcribe.dropSilent・既定オフ。印 fill.dropped)
  fill_snap_ends    同じ区間で行の終わりを区間の終わりへ ±0.3 秒寄せる(束 transcribe.endSnap・既定オフ。印 fill.endSnap)
標準ライブラリ・ytt・同じパッケージの兄弟(backend・diarize・roster・separate・tx_engines・txbase・worker_client)だけを読む。名簿のファイルの場所は呼ぶたびに
roster.ROSTER から、話者判別の部品の有無は diarize.has_sherpa から、疑似の窓の読みは backend の口 fill_reader から(app の ed_state を読まない)。ネイティブの部品は読み込まない。
"""
import re
import unicodedata

from ytt import errors as _errors, jobs as _heavy   # 取り消し Cancelled(RS2-8a。持ち主から直に読む)
from . import backend as _backend, diarize, postproc as _postproc, roster as _roster, separate, tx_engines, worker_client  # postproc = 単語の時刻を行の中へ _clip_words(endSnap)・ separate = 分けた声の区間(dropSilent)・ diarize = 話者判別の部品の有無 has_sherpa(RS2-9。呼ぶたびに diarize.名前 で読む)・ wav を読まずに渡す形 read_wav_f32(RS2-6)・モデルの読み込み load_model・filter_kwargs(RS2-8a)
from ytt import txbase as _txbase

FILL_ENGINE, FILL_MODEL = "sense-voice", "sense-voice-small"   # 2 つ目の読み(tx_engines.SenseVoice)
FILL_LANGS = ("ja", "en", "zh", "ko")   # SenseVoice に言語として渡せるもの(それ以外は auto)
FILL_MIN_SEC = 2.0       # A: この秒以上の行だけ
FILL_MAX_CPS = 1.5       # A: 縮めた文字数がこの字/秒 未満なら「文字が少ない」
FILL_RUNNY = 0.6         # A: 同じ字の繰り返しを縮めて文字数がこの割合以下になる行(「うわああああ」。4 字以上)も対象
FILL_PAD = 0.5           # A: 窓の前後の余白(秒)
FILL_RATIO = 3.0         # A: 別の読みの字数が元の何倍以上なら置き換えるか
FILL_MAX_ROWS = 60       # A: 1 回の文字起こしで読む窓の上限(長い文書で遅くならないように)
FILL_TRIM_EDGE = True    # A: 置き換えた行の頭が前の行の末尾と・尻が次の行の頭と FILL_TRIM_MIN 字以上同じなら、その字を落とす(窓の余白で隣の言葉が入る。
                         # 確かめるの答え「どちらも違う」に次の行の頭が入った行。置き換えた 150 行の 15%。印 fill.trim。False で前の形。10-26)
FILL_SKIP_LATIN = True   # A: 文書の言語が ja のとき、別の読みが英字ばかり(字の半分以上)なら置き換えない(歌・ゲームの音で SenseVoice が英語を書く。
                         # 字幕を仮の正解にした比べで、英字の置き換え 9 窓は字幕に近くならなかった。False で前の形。10-26)
FILL_TRIM_MIN = 2        # A: 落とす重なりの最小の字数(比べるのは fill_norm の文字)
FILL_A_FIRST = True      # A を C より先に(False = 0.99.99 までの C → A。記録の fill.order)
FILL_FLAG = "別の読みで埋めた(元の文字は「別の読み」の札)"
FILL_NAME_FLAG = "名簿の呼び名に直した(別のエンジンも同じ呼び名)"
FILL_STOCK = ("ご視聴ありがとうございました", "チャンネル登録", "ありがとうございました", "おやすみなさい", "字幕", "最後まで", "ご視聴")   # C: 定型の幻覚
FILL_MIN_VOICE = 0.3     # C: 行の長さのうち声の区間と重なる割合がこれ未満なら幻覚
FILL_STOCK_READ = True   # C: 判別が無くても、定型の文だけの行を別の読みで読み直し、読めなければ捨てる(fill_clean_read。記録 fill.stockRead。10-23)
FILL_STOCK_GAP = 0.3     # C: 定型の文が分かれた行をつなぐすき間(秒)
FILL_STOCK_ROWS = 4      # C: つなぐ行の数の上限
FILL_SILENT_VOICE = 0.1  # 声の無い行: 分けた声の区間と重なる割合がこれ未満の行を捨てる(dropSilent。3 割では本当の声を捨てた)
FILL_SNAP_END = 0.3      # 行の終わりを分けた声の区間の終わりへ寄せる幅(秒。endSnap。row-start-study の物差しで ±0.2〜0.3 が良かった)
FILL_DUP_MIN = 6       # C: 前の行の末尾の重複とみなす最小の文字数
FILL_AGREE_MIN = 3       # D: 呼び名の最小の文字数
FILL_AGREE_SLACK = 0.5   # D: 行と 2 つ目のエンジンの行の時間の重なりの余裕(秒)
FILL_AGREE_MAX_SEC = 1800   # D: 全体を読むのはこの秒までの文書(CPU で音声の約 2% の時間)
_FILL_REP3 = re.compile(r"(.)\1{2,}")
FILL_SPK_BY = "name"       # B: 行の fill の by(話者名を外した)
FILL_SPK_NOTE = "話者名を外した"   # 範囲・全体の再認識の印(元の文字は残さない)
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
    """A の対象の行か: FILL_MIN_SEC 秒以上で、縮めた文字数が FILL_MAX_CPS 字/秒 未満、または同じ字の繰り返しで縮む行(FILL_RUNNY)・繰り返しをまとめた行(_rep)"""
    try:
        dur = float(row["end"]) - float(row["start"])
    except (KeyError, TypeError, ValueError):
        return False
    if dur < FILL_MIN_SEC:
        return False
    raw = fill_norm(row.get("text"))
    n = fill_chars(row.get("text"))
    runny = len(raw) >= 4 and n <= FILL_RUNNY * len(raw) or bool(row.get("_rep"))   # 繰り返しをまとめた・縮めた行(postproc.merge_repeats。「どう」×150 の幻)も
    return runny or n / max(dur, 0.01) < FILL_MAX_CPS


def _fill_overlap(a0, a1, b0, b1):
    return max(0.0, min(a1, b1) - max(a0, b0))


# ---------- A: 文字の少ない行の窓を別の読みで埋める ----------
def _fill_edge(a, b):
    """a の末尾と b の頭が同じ最長の字数(fill_norm の文字。FILL_TRIM_MIN 未満は 0)"""
    for k in range(min(len(a), len(b)), FILL_TRIM_MIN - 1, -1):
        if a[-k:] == b[:k]:
            return k
    return 0


def _fill_cut(text, k, head):
    """text の頭(head)か尻から、fill_norm の文字で k 字ぶんを落とす(間の記号・空白も一緒に)"""
    if k <= 0:
        return text
    t = text if head else text[::-1]
    n = 0
    for i, ch in enumerate(t):
        if fill_norm(ch):
            n += 1
            if n == k:
                rest = t[i + 1:]
                return (rest if head else rest[::-1]).strip()
    return ""


def fill_trim_edges(new, prev, nxt):
    """A で置き換えた行 new(時刻の順)の頭が前の行 prev の末尾と・尻が次の行 nxt の頭と同じ字(窓の余白で入った隣の言葉)を落とす。
    落とした字数を最初と最後の行の fill.trim {head, tail} に残す。空になった行は捨てる -> 行"""
    if not new:
        return new
    h = _fill_edge(fill_norm(prev.get("text")), fill_norm(new[0]["text"])) if prev else 0
    t = _fill_edge(fill_norm(new[-1]["text"]), fill_norm(nxt.get("text"))) if nxt else 0
    h = h if 2 * h <= len(fill_norm(new[0]["text"])) else 0     # 行の半分を超える重なりは落とさない(同じ言葉の繰り返し = 隣の言葉ではない。答えで残した行)
    t = t if 2 * t <= len(fill_norm(new[-1]["text"])) else 0
    if h:
        new[0]["text"] = _fill_cut(new[0]["text"], h, True)
        new[0]["fill"]["trim"] = dict(new[0]["fill"].get("trim") or {}, head=h)
    if t and new[-1]["text"]:
        new[-1]["text"] = _fill_cut(new[-1]["text"], t, False)
        new[-1]["fill"]["trim"] = dict(new[-1]["fill"].get("trim") or {}, tail=t)
    return [x for x in new if fill_norm(x["text"])]


def _fill_latin(text):
    """字(文字の種類 L)の半分以上が英字か"""
    letters = [c for c in fill_norm(text) if unicodedata.category(c)[0] == "L"]
    return bool(letters) and 2 * sum(1 for c in letters if c.isascii()) >= len(letters)


def fill_apply(rows, read, total, lang=None):
    """rows(expand_segments の行。wav の秒)のうち対象の行(fill_sparse_row)の窓を read(s0, e0) -> [{start, end, text}](wav の秒)で読み、
    別の読み(行の半分以上が元の行の時間に入るもの)の字数が元の FILL_RATIO 倍以上なら置き換える。
    lang = 文書の言語(ja なら英字ばかりの読みは置き換えない = FILL_SKIP_LATIN)。
    -> (新しい行の一覧(時刻の順), {"windows": 読んだ窓, "rows": 置き換えた行, "added": 足した行(, "latin": 英字なので置き換えなかった窓)})。置き換えた行は fill = {"from": 元の文字, "by": FILL_ENGINE}"""
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
        if FILL_SKIP_LATIN and lang == "ja" and _fill_latin("".join(str(c["text"]) for c in cand)) and not _fill_latin(r["text"]):
            stats["latin"] = stats.get("latin", 0) + 1   # 日本語の文書で英語の読み = 置き換えない(記録の fill.latin)
            continue
        new = [{"start": round(float(c["start"]), 3), "end": round(float(c["end"]), 3), "text": str(c["text"]).strip(), "words": [],
                "avg_logprob": None, "no_speech_prob": None, "compression_ratio": None, "fill": {"from": r["text"], "by": FILL_ENGINE}} for c in cand]
        if FILL_TRIM_EDGE:
            rest = [x for x in out if x is not r]
            prev = max((x for x in rest if float(x["end"]) <= float(r["start"]) + FILL_PAD), key=lambda x: float(x["end"]), default=None)
            nxt = min((x for x in rest if float(x["start"]) >= float(r["end"]) - FILL_PAD), key=lambda x: float(x["start"]), default=None)
            new = fill_trim_edges(new, prev, nxt)   # 置き換えるかは落とす前の字数で決める(落とすと短い行は置き換えなくなり、答えで当たっていた物まで落ちた)
            if not new:
                continue
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


def _fill_stock_only(text):
    """文字が定型の文だけか(FILL_STOCK を取り除くと 1 字以下しか残らない)"""
    n = fill_norm(text)
    if not fill_stock(n):
        return False
    for x in sorted(FILL_STOCK, key=len, reverse=True):
        n = n.replace(fill_norm(x), "")
    return len(n) <= 1


def fill_clean_read(rows, read):
    """判別が無くても: 続いた行(すき間 FILL_STOCK_GAP 秒まで・FILL_STOCK_ROWS 行まで)をつないだ文字が定型の文だけで、
    その窓(前後 FILL_PAD 秒)を別の読み read で読んでも定型の文が出ない所は、幻覚として捨てる
    (正弦波だけの音で whisper が 30 秒に「ご視聴ありがとうございました」と書き、単語の間で「ご / 視聴 / ありがとうございました」の 3 行に分かれた)。
    別の読みで埋めた行(fill)は見ない。-> (行, 捨てた行 [{start, end, text}])"""
    if not FILL_STOCK_READ or read is None:
        return rows, []
    drop, i = set(), 0
    while i < len(rows):
        best = None
        for j in range(i, min(len(rows), i + FILL_STOCK_ROWS)):
            if (j > i and float(rows[j]["start"]) - float(rows[j - 1]["end"]) > FILL_STOCK_GAP or isinstance(rows[j].get("fill"), dict)
                    or not fill_norm(rows[j].get("text"))):   # 文字の無い行(♪ だけ。字幕に出さない印は postproc.note_nosub)はつながない
                break
            if _fill_stock_only("".join(str(r.get("text") or "") for r in rows[i:j + 1])):
                best = j
        if best is None:
            i += 1
            continue
        s0, e0 = max(0.0, float(rows[i]["start"]) - FILL_PAD), float(rows[best]["end"]) + FILL_PAD
        if not fill_stock("".join(str(c.get("text") or "") for c in read(s0, e0))):
            drop.update(range(i, best + 1))
        i = best + 1
    gone = [{"start": round(float(rows[k]["start"]), 2), "end": round(float(rows[k]["end"]), 2), "text": str(rows[k].get("text") or "")[:200]} for k in sorted(drop)]
    return [r for k, r in enumerate(rows) if k not in drop], gone


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
    spans = [(float(a) + offset, float(b) + offset) for a, b, *_rest in turns if float(b) > float(a)]   # 空 = 判別は通ったが声が 1 つも無い(BGM だけの切り抜き)= 定型の文は全部声の外
    if not isinstance(doc.get("original"), list):
        return 0
    machine = {(round(float(o["start"]), 2), round(float(o["end"]), 2)): o.get("text") for o in doc["original"] if isinstance(o, dict)}
    keep, n = [], 0
    for g in doc.get("segments") or []:
        if (isinstance(g, dict) and fill_stock(g.get("text")) and g.get("proofed") is not True and not g.get("tags") and not g.get("noSub")
                and g.get("cutState") != "cut"
                and machine.get((round(float(g["start"]), 2), round(float(g["end"]), 2))) == g.get("text")
                and fill_voice_frac(g, spans) < FILL_MIN_VOICE):
            n += 1
            continue
        keep.append(g)
    if n:
        doc["segments"] = keep
    return n


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


# ---------- D: 別のエンジンも同じ呼び名なら 1 字違いを直す ----------
def fill_aliases(r=None):
    """名簿の呼び名(名前 + aliases。common = 普通の言葉と重なる語は除く・FILL_AGREE_MIN 字以上)。r = 名簿(無ければ読む)"""
    r = _roster.load(_roster.ROSTER) if r is None else r
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


FILL_AGREE_SMALL_SKIP = True   # D: 違う 1 字が小さい字・伸ばし(「みこっち」の っ)か、置き換えると同じ字が並ぶ(みこち + ち)なら直さない
                               # (確かめるの答えで「みこちち」が 3 件。10-26。False で前の形)
_FILL_SMALL = set("っッゃゅょャュョぁぃぅぇぉァィゥェォゎヮー〜")


def _fill_agree_variant(t, i, a):
    """D: t[i:i+len(a)] を呼び名 a に置き換えると誤る形か(違う 1 字が小さい字・伸ばし = 呼び名の別の書き方 / 置き換えた後ろに a の最後の字が続く = 二重)"""
    w = t[i:i + len(a)]
    diff = [(x, y) for x, y in zip(fill_kana(w), fill_kana(a)) if x != y]
    if diff and diff[0][0] in _FILL_SMALL and diff[0][1] not in _FILL_SMALL:   # っ ↔ ち(書き方の違い)。ょ ↔ ゃ は聞き違いなので直す
        return True
    return t[i + len(a):i + len(a) + 1] == a[-1:] or (i > 0 and t[i - 1] == a[:1])


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
                    if FILL_AGREE_SMALL_SKIP and _fill_agree_variant(t, i, a):
                        continue
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
    """窓を読む関数 read(s0, e0) -> [{start, end, text}](wav の秒)。本物と疑似は backend の口 fill_reader(RS5-D。
    疑似 = eval/fake/fake_asr は環境変数 TRANSCRIBE_FAKE_FILL の文字を窓いっぱいの 1 行に(空 = 行なし))"""
    return _backend.select().fill_reader(job, spec, wav, _fill_reader_real)


def _fill_reader_real(job, spec, wav):
    """本物の窓を読む関数: SenseVoice を認識ワーカーに読み込み(主のモデルは手放さない = tx_engines.Engine.light)、窓のサンプルの範囲だけを渡す"""
    if not diarize.has_sherpa():   # 話者判別の部品 sherpa-onnx の有無(呼ぶたびに読む。ネイティブの部品はここでは読み込まない)
        raise _errors.ApiError("no_sherpa", "別の読み(SenseVoice)の部品 sherpa-onnx が入っていません(setup\\install-diarize.bat を実行してください)", 400)
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
    """run_job の行(expand_segments のあと)に A(別の読みで埋める)と C(末尾の重複)を当てる。
    順は FILL_A_FIRST(既定 A → C。C が A の対象の「うわああああ」の次の「ああああ」の行を先に捨てて埋められなかった = 確かめ済み 23 本の組 B で
    C → A 15.23% → A → C 12.45%・組 A は全部同じ。notes:plan/accuracy-review-1022.md)。A が読めなくても C は当てる。dup は A の後の行で数える。
    -> (行, 記録 {engine, windows, rows, added, dup, agree, order} か None(設定オフ), 窓を読む関数 か None(読めない = 警告を job に足して whisper のまま))"""
    if not spec.get("autoFill"):
        return rows, None, None
    order = "AC" if FILL_A_FIRST else "CA"
    rec = {"engine": FILL_ENGINE, "windows": 0, "rows": 0, "added": 0, "dup": 0, "agree": 0, "order": order}
    if order == "CA":
        rows, rec["dup"] = fill_clean_tail(rows)
    phase = job.get("phase")
    read = None
    try:
        read = fill_reader(job, spec, wav)
        job["phase"] = "文字の少ない行を別の読みで埋め中"
        rows, st = fill_apply(rows, read, total, spec.get("language"))
        rec.update(st)
    except _heavy.Cancelled:
        raise
    except (_errors.ApiError, tx_engines.EngineError) as e:
        read = None
        _txbase.add_warning(job, "別の読みで埋められませんでした(whisper の結果のまま): " + str(getattr(e, "message", e))[:200])
    job["phase"] = phase
    if order == "AC":
        rows, rec["dup"] = fill_clean_tail(rows)
    if read is not None:   # 定型の文だけの行を読み直して、読めなければ捨てる(判別の無い文書でも。fill_clean_read)
        try:
            rows, gone = fill_clean_read(rows, read)
        except _heavy.Cancelled:
            raise
        except (_errors.ApiError, tx_engines.EngineError) as e:
            gone = []
            _txbase.add_warning(job, "定型の文を別の読みで確かめられませんでした: " + str(getattr(e, "message", e))[:200])
        if gone:
            rec["stockRead"] = {"n": len(gone), "rows": gone[:50]}
    if spec.get("dropSilent") or spec.get("endSnap"):
        rows = fill_drop_silent(job, rows, wav, rec, drop=bool(spec.get("dropSilent")), snap=bool(spec.get("endSnap")))
    return rows, rec, read


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
    組 A 10.35 → 9.89%・組 B 12.45 → 11.70%・抜け・時刻は両方の組で同じ = notes:plan/voice-separation-1022.md の 2)。
    捨てた行は rec["dropped"] = {n, db, rows(最初の 200)} に残す。分けられない(型が無い・落ちた)・区間が無ければ警告して捨てない。
    snap(束 transcribe.endSnap・既定オフ)なら残した行の終わりを分けた声の区間の終わりへ寄せる(fill_snap_ends)"""
    phase = job.get("phase")
    job["phase"] = "声を分けて声の無い行を探し中"
    try:
        spans = separate.voice_spans(job, wav)
    except _heavy.Cancelled:
        raise
    except (_errors.ApiError, tx_engines.EngineError, OSError, MemoryError, RuntimeError) as e:
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


def fill_agree_doc(job, segs, read, total, spec):
    """D を文書の行に当てる: SenseVoice で全体を読み(FILL_AGREE_MAX_SEC まで)、名簿の呼び名(fill_aliases)で fill_agree。-> 直した数(名簿が無い・読めなければ 0)"""
    try:
        aliases = fill_aliases()
    except (OSError, ValueError, TypeError, KeyError) as e:
        _txbase.log.warning("名簿を読めないので呼び名の直しはしません: %s", e)
        return 0
    if not aliases or not segs or not total or float(total) > FILL_AGREE_MAX_SEC:
        return 0
    phase = job.get("phase")
    try:
        job["phase"] = "別のエンジンで名簿の呼び名を確かめ中"
        rows = read(0.0, float(total))
    except _heavy.Cancelled:
        raise
    except (_errors.ApiError, tx_engines.EngineError) as e:
        _txbase.add_warning(job, "別のエンジンで名簿の呼び名を確かめられませんでした: " + str(getattr(e, "message", e))[:200])
        return 0
    finally:
        job["phase"] = phase
    shift = float(spec.get("start") or 0.0)
    return fill_agree(segs, [{"start": r["start"] + shift, "end": r["end"] + shift, "text": r["text"]} for r in rows], aliases)
