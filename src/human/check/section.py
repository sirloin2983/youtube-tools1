"""「確かめる」の評価のレーンの区間カードの反映(C-EVAL (2)。決定 3-47「確かめると評価をまとめる」・3-49 Q2。設計の相談は Fable)。

評価用の文書を頭から区間に分け(区切りは入口 src/app/check/eval_sources.py)、1 枚ずつ「区間を聞いて、持ち主の行を合っている / 直す / 足す」で答える。
正解づくりなので、答えた持ち主の行は校正済み(proofed)にする。全部の行がどこかの区間で 1 回ずつ答えられるので、残りを黙って校正済みにはしない
(⑤ eval/drill の「全部聞いた」が残りの行を校正済みにする道 = 混ざる道 1 を通らない)。
  - カードの target = {docId, from, to(秒。区間), rows(持ち主の行の id), updatedAt(カードを組んだときの文書), last(最後の区間か), index}
  - 答え = {rows: [{id, text?, speaker?, drop?}], add: [{start, end, text, speaker?}]}。rows に無い持ち主の行 = そのまま(合っている)。
    speaker は名前(1〜30 字。メンバーのフォルダの名前を画面が選ばせる・打ってもよい)。ここでは形だけ確かめる(一覧との照合は画面の手伝い)
  - 機械の予想・覚えた声の候補は使わない。学習の記録・声の覚え直しはしない(評価用から学ばせない)
  - 最後の区間を答えたら evalReviewed = {at, rows, durationSec, via: "card", sections}。at は行の proofedAt と別の値にする
    (⑤ drill_unreviewed が「proofedAt == evalReviewed.at の行」の校正済みを外すため、区間の答えまで外さない)
  - 断る: 評価用でない(409 not_eval)・処理中(409 busy)・カードを組んだあとに文書が変わった(409 changed = 画面は読み込み直す)・行が消えた(409 changed)
Z = 答える前の行と話者の表に戻す(持ち主の行・足した行が答えのあとのままのときだけ。もう戻っていれば何もしない)。最後の区間なら via card の evalReviewed も外す。
③ の層: 文書は human/proof の store、ジョブの最中かは human/check/_doc(② flow/jobs の読み口)だけを読む。入口が import すると register される。
"""
import copy
import os
import re

from ytt import errors as _errors, schemas as _yschemas, settings as _settings, textutil as _textutil, workdata as _workdata
from human.proof import speakers as _speakers, store as _store
from . import _doc, apply   # 同じ human/check の兄弟

NAME_MAX = 30
MAX_ROWS = 200          # 1 枚で直す・足す行の上限(20〜40 秒の区間には十分)
MAX_ANSWER_BYTES = 64 * 1024
_CTRL_RE = re.compile(r"[\x00-\x1f\x7f]")
ADDED_PREFIX = "c"      # 足した行の id の頭(Z で探す。sanitize が付ける s<番号> と重ならない)


def _name(v):
    n = str(v).strip() if isinstance(v, str) else None
    if not n or len(n) > NAME_MAX or _CTRL_RE.search(n):
        raise ValueError("話者の名前は 1〜%d 文字で送ってください" % NAME_MAX)
    if _speakers.is_generic_speaker_name(n):
        raise ValueError("「%s」は仮の名前です(人の名前を選ぶか打ってください)" % n)
    return n


def _text(v):
    if not isinstance(v, str) or len(v) > 2000 or _CTRL_RE.search(v.replace("\n", "")):
        raise ValueError("行の文字の形が正しくありません")
    return v.strip()


def _num(v, what):
    if isinstance(v, bool) or not isinstance(v, (int, float)) or v != v or not 0 <= v < 1e7:
        raise ValueError("%s は 0 以上の数にしてください" % what)
    return round(float(v), 3)


def _check(answer):
    """答えを検査して整える -> {rows: [...], add: [...]}。違えば ValueError(400)"""
    if not isinstance(answer, dict) or set(answer) - {"rows", "add"}:
        raise ValueError("答えは {rows, add} の形で送ってください")
    rows, add = answer.get("rows") or [], answer.get("add") or []
    if not isinstance(rows, list) or not isinstance(add, list) or len(rows) + len(add) > MAX_ROWS:
        raise ValueError("直す行・足す行は合わせて %d 行までです" % MAX_ROWS)
    out_rows, seen = [], set()
    for r in rows:
        if not isinstance(r, dict) or set(r) - {"id", "text", "speaker", "drop"} or not isinstance(r.get("id"), str) \
                or not re.match(r"^[A-Za-z0-9_-]{1,16}\Z", r["id"]) or r["id"] in seen:
            raise ValueError("直す行の形が正しくありません")
        seen.add(r["id"])
        one = {"id": r["id"]}
        if r.get("drop") is True:
            one["drop"] = True
        else:
            if "text" in r:
                one["text"] = _text(r["text"])
            if "speaker" in r:
                one["speaker"] = _name(r["speaker"])
        out_rows.append(one)
    out_add = []
    for r in add:
        if not isinstance(r, dict) or set(r) - {"start", "end", "text", "speaker"}:
            raise ValueError("足す行の形が正しくありません")
        a, b, t = _num(r.get("start"), "start"), _num(r.get("end"), "end"), _text(r.get("text"))
        if b <= a or not t:
            raise ValueError("足す行は 終わり > 始まり で、文字を入れてください")
        one = {"start": a, "end": b, "text": t}
        if "speaker" in r:
            one["speaker"] = _name(r["speaker"])
        out_add.append(one)
    return {"rows": out_rows, "add": out_add}


def _target(card):
    t = card.get("target") or {}
    tid = str(t.get("docId") or "")
    rows = t.get("rows")
    if not _yschemas.TID_RE.match(tid) or not isinstance(rows, list) or not all(isinstance(x, str) for x in rows):
        raise apply.Refused("カードの対象(文書・区間)が正しくありません", 400, "bad_request")
    a, b = _yschemas.num(t.get("from")), _yschemas.num(t.get("to"))
    if a is None or b is None or b <= a:
        raise apply.Refused("カードの区間が正しくありません", 400, "bad_request")
    return tid, a, b, list(rows), t.get("updatedAt"), t.get("last") is True, t.get("index")


def _speaker_id(doc, name, added):
    """名前 -> 文書の話者の id(同じ人 = person_key が同じ。いなければ足して added に入れる)"""
    sps = doc.setdefault("speakers", [])
    want = _textutil.person_key(name)
    for s in sps:
        if isinstance(s, dict) and not _yschemas.other_speaker(s) and _textutil.person_key(s.get("name")) == want:
            return str(s["id"])
    named = [s for s in sps if isinstance(s, dict) and not _yschemas.other_speaker(s)]
    if len(named) >= _speakers.MAX_SPEAKERS:
        raise apply.Refused("この文書の話者は %d 人までです(編集の画面で使わない話者を消してください)" % _speakers.MAX_SPEAKERS, 409, "too_many")
    ids = {str(s.get("id")) for s in sps if isinstance(s, dict)}
    n = len(named) + 1
    while "S%d" % n in ids:
        n += 1
    sid = "S%d" % n
    from . import voice as _voice   # 色の並びは声のカードと同じ(画面の addSpeaker と同じ)
    new = {"id": sid, "name": name, "color": _voice.SPK_COLORS[(n - 1) % len(_voice.SPK_COLORS)]}
    k = next((i for i, s in enumerate(sps) if _yschemas.other_speaker(s)), None)   # 組み込みの「ゲーム音声など」はいつも最後
    sps.insert(k, new) if k is not None else sps.append(new)
    added.append(sid)
    return sid


def _state(g):
    """戻すときに比べる行の欄"""
    return {"text": str(g.get("text") or ""), "speaker": g.get("speaker") or "", "proofed": g.get("proofed") is True}


def _write(tid, base, segs, speakers, why, reviewed=None):
    """行と話者の表を差し替えて保存する(保存の錠を持って呼ぶ)-> 書いた文書。reviewed = evalReviewed に入れる値(None = base のまま・False = 外す)"""
    doc = _store.sanitize_transcript({"title": base.get("title", ""), "speakers": speakers, "segments": segs}, base)
    if reviewed is False:
        doc.pop("evalReviewed", None)
    elif isinstance(reviewed, dict):
        rv = dict(reviewed, at=int(doc["updatedAt"]) + 1)   # 行の proofedAt(sanitize の「今」= updatedAt)と別の値(説明は先頭)
        doc["evalReviewed"] = rv
        doc["updatedAt"] = rv["at"]
    _store.snapshot(tid, False)
    _store.commit(tid, doc, why=why)
    return doc


def _open(tid):
    """保存の錠の中で文書を読む(評価用でない・処理中は断る)"""
    if not _workdata.TX_DIR:   # 編集の作業データの置き場所が決まっていない(編集を取り込んでいない入口)
        raise apply.Refused("文字起こしの置き場所がまだ決まっていません", 503, "unavailable")
    if _doc.busy(tid):
        raise apply.Refused("この文字起こしは処理中です(評価用の一括の作り直し・話者判別などが終わってからにしてください)", 409, "busy")
    try:
        doc = _store.read_transcript(tid)
    except _errors.ApiError as e:
        raise apply.Refused("文字起こしを読めません: " + str(e.message or e), 409, "no_doc")
    if doc.get("evalSet") is not True:
        raise apply.Refused("評価用の文字起こしではありません(普段のカードで確かめてください)", 409, "not_eval")
    return doc


def _apply_section(ctx, card, answer):
    """答えを実物へ。-> applied {docId, from, to, index, before, after, added, addedSpeakers, reviewed, updatedAt}"""
    tid, a, b, owned, stamp, last, index = _target(card)
    with _store._save_lock:
        base = _open(tid)
        if stamp is not None and base.get("updatedAt") != stamp:
            raise apply.Refused("カードを用意したあとに文書が変わりました(読み込み直してください)", 409, "changed")
        segs = [dict(g) for g in base.get("segments") or () if isinstance(g, dict)]
        by_id = {str(g.get("id")): g for g in segs}
        if any(r not in by_id for r in owned):
            raise apply.Refused("区間の行が変わっています(読み込み直してください)", 409, "changed")
        speakers = copy.deepcopy(base.get("speakers") or [])
        doc_sp = {"speakers": speakers}
        added_sp, before, dropped = [], {}, []
        edits = {r["id"]: r for r in answer["rows"]}
        if set(edits) - set(owned):
            raise apply.Refused("区間の持ち主でない行は直せません", 400, "bad_request")
        for rid in owned:
            g = by_id[rid]
            before[rid] = copy.deepcopy(g)
            e = edits.get(rid) or {}
            if e.get("drop"):
                dropped.append(rid)
                continue
            if "text" in e:
                g["text"] = e["text"]
            if "speaker" in e:
                g["speaker"] = _speaker_id(doc_sp, e["speaker"], added_sp)
            if str(g.get("text") or "").strip():
                g["proofed"] = True   # 正解づくり: 区間を聞いて答えた持ち主の行(文字のある行だけ。drill_reviewed と同じ)
        segs = [g for g in segs if str(g.get("id")) not in dropped]
        added = []
        for i, r in enumerate(answer["add"]):
            s0, e0 = max(a, r["start"]), min(b, r["end"])   # 区間の中に切り詰める(境目をまたぐと次の区間が持ち主になり二度答える)
            if e0 - s0 < 0.1:
                raise apply.Refused("足す行が区間の外です", 400, "bad_request")
            rid = "%s%x%d" % (ADDED_PREFIX, _yschemas.now_ms() % 0xFFFFFF, i)
            g = {"id": rid, "start": s0, "end": e0, "text": r["text"], "speaker": "", "proofed": True}
            if "speaker" in r:
                g["speaker"] = _speaker_id(doc_sp, r["speaker"], added_sp)
            segs.append(g)
            added.append(rid)
        segs.sort(key=lambda g: (_yschemas.num_or(g.get("start"), 0.0) or 0.0, _yschemas.num_or(g.get("end"), 0.0) or 0.0))
        reviewed = None
        if last:
            texts = [g for g in segs if str(g.get("text") or "").strip()]
            reviewed = {"rows": len(texts), "durationSec": round(_store.doc_length(dict(base, segments=segs)), 1), "via": "card",
                        "sections": (index + 1) if isinstance(index, int) else None}
        doc = _write(tid, base, segs, speakers, "check:section", reviewed)
        now = {str(g.get("id")): g for g in doc.get("segments") or () if isinstance(g, dict)}
        after = {rid: _state(now[rid]) for rid in [r for r in owned if r not in dropped] + added if rid in now}
        return {"docId": tid, "from": a, "to": b, "index": index, "before": before, "dropped": dropped, "after": after, "added": added,
                "addedSpeakers": added_sp, "reviewed": bool(last), "updatedAt": doc.get("updatedAt"),
                "changed": sum(1 for r in answer["rows"]) + len(added)}


def _revert_section(ctx, row):
    """Z。答える前の行と話者の表に戻す(説明は先頭)。-> {docId, from, to, reverted}"""
    ap = row.get("applied") or {}
    tid = str(ap.get("docId") or "")
    if not _yschemas.TID_RE.match(tid) or not isinstance(ap.get("before"), dict) or not isinstance(ap.get("after"), dict):
        raise apply.Refused("この答えは戻せません(記録の形が違います)", 409, "cannot_undo")
    before, after = ap["before"], ap["after"]
    added = [x for x in ap.get("added") or () if isinstance(x, str)]
    with _store._save_lock:
        base = _open(tid)
        segs = [dict(g) for g in base.get("segments") or () if isinstance(g, dict)]
        by_id = {str(g.get("id")): g for g in segs}
        restored = all(rid in by_id and _state(by_id[rid]) == _state(g) for rid, g in before.items()) and not any(x in by_id for x in added)
        if restored:
            return {"docId": tid, "from": ap.get("from"), "to": ap.get("to"), "reverted": False}   # もう戻っている(やりかけの Z のやり直し)
        if any(rid not in by_id or _state(by_id[rid]) != st for rid, st in after.items()):
            raise apply.Refused("この区間の行はあとで直されています(編集の画面で直してください)", 409, "changed")
        segs = [g for g in segs if str(g.get("id")) not in added and str(g.get("id")) not in before]
        segs += [copy.deepcopy(g) for g in before.values()]
        segs.sort(key=lambda g: (_yschemas.num_or(g.get("start"), 0.0) or 0.0, _yschemas.num_or(g.get("end"), 0.0) or 0.0))
        speakers = copy.deepcopy(base.get("speakers") or [])
        used = {g.get("speaker") for g in segs}
        speakers = [s for s in speakers if not (isinstance(s, dict) and s.get("id") in (ap.get("addedSpeakers") or ()) and s.get("id") not in used)]
        rv = base.get("evalReviewed")
        reviewed = False if ap.get("reviewed") and isinstance(rv, dict) and rv.get("via") == "card" else None
        _write(tid, base, segs, speakers, "check:section", reviewed)
    return {"docId": tid, "from": ap.get("from"), "to": ap.get("to"), "reverted": True}


SETTING = "checkSectionCardsOn"   # 編集の設定の鍵(既定オン)。既定オフのころの鍵 checkSectionCards は読まない = 前に保存されたオフは既定オンに読み替える


def enabled():
    """区間カードのスイッチ(既定オン = ユーザー決定 3-63 (ce1) B)。編集の設定 checkSectionCardsOn(設定の画面の「編集」)を
    明示でオフにしたときだけ出さない。環境変数 YTT_CHECK_SECTION が on 系なら出す・off 系(0・off・false・no)なら出さない(テスト・試し)"""
    v = str(os.environ.get(SWITCH_ENV) or "").strip().lower()
    if v in ("1", "on", "true", "yes"):
        return True
    if v in ("0", "off", "false", "no"):
        return False
    try:
        return _settings.load_settings().get(SETTING) is not False
    except Exception:
        return True


SWITCH_ENV = "YTT_CHECK_SECTION"
apply.register("section", "eval", _apply_section, revert=_revert_section, check=_check, max_bytes=MAX_ANSWER_BYTES)
