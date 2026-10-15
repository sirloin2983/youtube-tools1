# -*- coding: utf-8 -*-
"""③ 人の操作の層 human/proof: 元の配信の YouTube の字幕の候補の、比べ方の部品だけ(読むだけ・通信しない)。

YouTube の字幕の候補(取得・ジョブ・API・画面の欄・設定 autoYtcap・編集の提案の yt)は消した(OPT-H1。決定 notes:plan/decisions.md の 3-47 Q10)。
ここに残るのは ⑤ が読む部品だけ = 「確かめる」の読みのカード read:yt(src/eval/check/read_sources.py の YTCAP_SCHEMA・ytcap_diffs)と
測る道具 src/eval/tools/eval_alt.py の --source yt(ytcap_doc_range・ytcap_doc_rows・ytcap_diffs・ytcap_valid_cache ほか。serve の名前 S.名前 で読む)。
⑤ の呼び手を消したら、このファイルごと消す(OPT-E1)。

名前は serve.py からも見える(serve.py の _ED_MODULES。ほかの部品と重ならないよう、名前は ytcap_ / YTCAP_ / _ytcap_ で始める)。
"""
import re

from ytt import errors as _errors, schemas as _yschemas  # noqa: E402
from ytt import txbase as _txbase  # noqa: E402   1 行の文字数の上限
from . import alt  # noqa: E402   比べ方 alt_diffs・alt_fold(呼ぶたびに alt.名前 で読む)

YTCAP_SCHEMA = "youtube-tools-ytcap/v1"            # 文書の隣の <id>.ytcap.json(文書の範囲に切り出した字幕。形は alt.json に合わせる。もう書かない)
YTCAP_VIDEO_SCHEMA = "youtube-tools-ytcap-video/v1"   # 作業データの ytcaps/<videoId>.json(配信 1 本ぶんの字幕。もう書かない)
YTCAP_VID_RE = re.compile(r"^[\w-]{11}\Z", re.ASCII)   # 配信の ID(ytt/yturl の VID_RE と同じ。ASCII のみ・末尾の改行も不可)
YTCAP_MAX_CACHE_BYTES = 48 * 1024 * 1024
# 言いよどみ(フィラー)だけの違い。YouTube の自動字幕は「え、」「あの、」「おお。」まで書き、主のエンジン(Whisper)と人の最終は落とすことが多い
# (2026-10-05 に本物の 8 本で、yt の候補の外れの多くがこれだった)。句読点で区切って足した所が、比べる文字(alt_fold のあと = ひらがな・伸ばしなし)でこれだけなら出さない
_YTCAP_SEP_RE = re.compile(r"[、。,.?？!！]")
YTCAP_FILLER_RE = re.compile(r"^(?:えっと|あのう|あの|ええ|ああ|おお|うう|うん|まあ|ほう|ふん|はあ|うわ|わあ|へえ|ほお|[えあおうんま]っ?)+\Z")


# ---------- 文書 → 配信の ID と範囲 ----------
def ytcap_doc_range(doc):
    """文書の元の配信と、文書の範囲を配信の時刻に直したもの → {videoId, offset, a, b, docStart, docEnd}。
    文書の行の時刻 t(切り抜きの動画の先頭 = 0 秒)は、配信では offset + t(offset = clip の export.actualStart → range.start。ytt.schemas.clip_offset)。
    使えない(clip が無い・壊れている・YouTube の配信でない・ID の形が違う)ときは ApiError no_clip"""
    clip = doc.get("clip") if isinstance(doc, dict) else None
    if not isinstance(clip, dict):
        raise _errors.ApiError("no_clip", "元の配信が分からない文書です(スタジオで書き出した切り抜きだけ、YouTube の字幕と比べられます)", 400)
    c, why = _yschemas.validate_clip(clip)
    if c is None:
        raise _errors.ApiError("no_clip", "元の配信の情報が読めません。スタジオで書き出し直すと直ります", 400, {"detail": ".clip.json: %s" % why})   # 内部の名前は detail
    src = c.get("source") if isinstance(c.get("source"), dict) else {}
    if src.get("kind") != "youtube":
        raise _errors.ApiError("no_clip", "元の動画が YouTube の配信ではありません(手元のファイル・リアルタイム切り抜きは、YouTube の字幕と時刻が合いません)", 400)
    vid = str(src.get("videoId") or "")
    if not YTCAP_VID_RE.match(vid):
        raise _errors.ApiError("no_clip", "元の配信の ID の形が正しくありません", 400)
    off = float(_yschemas.clip_offset(c))
    ds = max(0.0, _yschemas.num_or(doc.get("start"), 0.0) or 0.0)
    de = _yschemas.num_or(doc.get("end"))
    if de is None:   # 文書が動画の最後まで: 切り抜きの長さ(元の配信の範囲)
        de = float(c["range"]["end"]) - off
        md = _yschemas.num_or((c.get("media") or {}).get("durationSec")) if isinstance(c.get("media"), dict) else None
        if de <= ds and md:
            de = md
    if de <= ds:
        raise _errors.ApiError("no_clip", "元の配信の範囲が正しくありません", 400)
    return {"videoId": vid, "offset": round(off, 3), "a": round(off + ds, 3), "b": round(off + de, 3), "docStart": round(ds, 3), "docEnd": round(de, 3)}


def ytcap_valid_cache(d, vid=None):
    """配信ごとの字幕の記録として使える形か(測る道具 src/eval/tools/eval_alt.py が読む)"""
    return (isinstance(d, dict) and d.get("schema") == YTCAP_VIDEO_SCHEMA and d.get("kind") in ("manual", "auto", "none")
            and isinstance(d.get("cues"), list) and isinstance(d.get("at"), (int, float)) and (vid is None or d.get("videoId") == vid))


# ---------- 文書の範囲に切り出す(純粋な関数) ----------
def ytcap_cut(cues, a, b, offset):
    """字幕(配信の時刻)から [a, b) 秒の所を切り出し、文書の時刻(配信の時刻 − offset)の行 [{start, end, text}] にする。
    言葉は文字ごとに時刻を割り振り(言葉の長さを字数で等分)、真ん中の時刻が範囲の中の文字だけを残す。1 つの字幕 = 1 行"""
    a_ms, b_ms = a * 1000.0, b * 1000.0
    rows = []
    for cue in cues or []:
        if not isinstance(cue, list) or not cue:
            continue
        try:
            if cue[-1][1] <= a_ms or cue[0][0] >= b_ms:
                continue
        except (TypeError, IndexError):
            continue
        txt, t_first, t_last = [], None, None
        for w in cue:
            if not (isinstance(w, list) and len(w) == 3 and isinstance(w[2], str)):
                continue
            t, e, s = float(w[0]), float(w[1]), w[2]
            n = len(s)
            if not n:
                continue
            step = max(0.0, e - t) / n
            for i, ch in enumerate(s):
                c0 = t + i * step
                if a_ms <= c0 + step / 2 < b_ms:
                    txt.append(ch)
                    t_first = c0 if t_first is None else t_first
                    t_last = c0 + step
        text = "".join(txt).strip()
        if text and t_first is not None:
            rows.append({"start": round(t_first / 1000.0 - offset, 2), "end": round(max(t_last, t_first + 1) / 1000.0 - offset, 2), "text": text[:_txbase.MAX_TEXT]})
    rows.sort(key=lambda r: r["start"])
    return rows


def ytcap_doc_rows(doc, cache):
    """文書と配信の字幕の記録 → (文書の時刻の行, 範囲 ytcap_doc_range)。測る道具が使う(読むだけ)"""
    rng = ytcap_doc_range(doc)
    return ytcap_cut(cache.get("cues") or [], rng["a"], rng["b"], rng["offset"]), rng


def ytcap_filler_only(wrong, right):
    """YouTube の字幕が、句読点で区切った言いよどみを足しただけの候補か(例: 「よ」→「よ。あの」・「て」→「て。え」)。
    句読点の無い 1 文字の足し(「す」→「ます」・「なで」→「なんで」)は本当の直しのことがあるので、言いよどみにしない"""
    if right.startswith(wrong):
        extra = right[len(wrong):]
    elif right.endswith(wrong):
        extra = right[:len(right) - len(wrong)]
    else:
        return False
    return bool(_YTCAP_SEP_RE.search(extra)) and bool(YTCAP_FILLER_RE.match(alt.alt_fold(extra)))


def ytcap_diffs(rows, yt_rows):
    """今の行と YouTube の字幕の食い違い → (候補 [{… tier: "yt"}], 数えた理由)。比べ方は alt.alt_diffs そのまま(二重に書かない)。
    加えて、切り抜きの頭と終わりの食い違い(最初の行の頭・最後の行の終わりにかかる候補)は出さない(clipEdge。字幕の時刻で切るので、境目の言葉がずれる)。
    言いよどみだけを足す・消す候補も出さない(filler。YTCAP_FILLER_RE)"""
    items, stats = alt.alt_diffs(rows, yt_rows)
    stats = dict(stats, clipEdge=0, filler=0)
    texts = [g for g in rows or [] if isinstance(g, dict) and str(g.get("text") or "").strip() and _yschemas.num_or(g.get("start")) is not None]
    if not texts:
        return [], stats
    first = min(texts, key=lambda g: _yschemas.num_or(g.get("start")))
    last = max(texts, key=lambda g: (_yschemas.num_or(g.get("end"), 0.0) or 0.0, _yschemas.num_or(g.get("start"))))
    out = []
    for x in items:
        if first.get("id") == x["seg"] and not alt.alt_fold(str(first["text"])[:x["i"]]):
            stats["clipEdge"] += 1
            continue
        if last.get("id") == x["seg"] and not alt.alt_fold(str(last["text"])[x["i"] + len(x["wrong"]):]):
            stats["clipEdge"] += 1
            continue
        if ytcap_filler_only(x["wrong"], x["right"]):
            stats["filler"] += 1
            continue
        out.append(dict(x, tier="yt"))
    return out, stats
