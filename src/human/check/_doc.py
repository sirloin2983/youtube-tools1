"""「確かめる」の文書の行を直す 1 つの口(読み・時刻・声のカードの反映と Z が使う。opt-human 6-1)。

edit_row(tid, row_id, fn, why): 保存の錠 → この文書を書き換えるジョブの最中なら断る → 文書を読み直す → 評価用なら断る → 行を探す →
  fn(doc, seg) -> (変えたか, 戻り値) → 変えたときだけ updatedAt を進めて、履歴(10 分に 1 つ。編集の画面の保存と同じ)→ store.commit(why)。
  断るときの理由は 4 つの種類で同じ: 503 unavailable(文字起こしの置き場所が決まっていない)・409 busy・409 no_doc・409 eval・409 no_row。
反映と Z の共通の形もここ: edit_fields(前の値 → 直す → 後の値)・revert_fields(答えたあとのままのときだけ戻す)・row_target・doc_id(カードの行・文書)・choice(答えの検査)。
印(行の flag)の割る・つなぐは ytt/schemas の flag_parts・join_flags を直に使う。
③ の層: 文書は human/proof の store と layers、ジョブの最中かは ② flow/jobs の読み口だけを読む。
"""
import time

from ytt import errors as _errors, schemas as _yschemas, workdata as _workdata
from flow import jobs as _heavy
from human.proof import store as _store
from . import apply as _apply   # 同じ human/check の兄弟

# この文書を書き換えないジョブ(2 つ目のエンジン・30fps の作り直し)と、確かめるが自分で足す声の覚え直しは「最中」に数えない。
# ほかの種類(文字起こし・話者判別・再認識・疑わしい所・これから足す種類)の最中は、答えが結果で消えるので断る
NOT_BUSY_KINDS = ("alt", "normalize", "voice-learn")


def busy(tid):
    return _heavy.doc_busy(tid, NOT_BUSY_KINDS)


def _bump(doc):
    doc["updatedAt"] = max(int(time.time() * 1000), int(_yschemas.num_or(doc.get("updatedAt"), 0) or 0) + 1)


def edit_row(tid, row_id, fn, why):
    """行を 1 つ直す(説明は先頭)。-> fn の戻り値。断るときは apply.Refused"""
    if not _workdata.TX_DIR:   # 編集の作業データの置き場所が決まっていない(編集を取り込んでいない入口)
        raise _apply.Refused("文字起こしの置き場所がまだ決まっていません", 503, "unavailable")
    with _store._save_lock:
        if busy(tid):
            raise _apply.Refused("この文字起こしは処理中です(話者判別・再認識などが終わってからにしてください)", 409, "busy")
        try:
            doc = _store.read_transcript(tid)
        except _errors.ApiError as e:
            raise _apply.Refused("文字起こしを読めません: " + str(e.message or e), 409, "no_doc")
        if doc.get("evalSet") is True:
            raise _apply.Refused("評価用の文字起こしは確かめるでは直しません(評価ドリルで確かめてください)", 409, "eval")
        seg = next((g for g in doc.get("segments") or () if isinstance(g, dict) and str(g.get("id")) == str(row_id)), None)
        if seg is None:
            raise _apply.Refused("その行はもうありません(行が消えたか分け直されています)", 409, "no_row")
        changed, out = fn(doc, seg)
        if changed:
            _bump(doc)
            _store.snapshot(tid, False)   # 履歴が残せなくても続ける(編集の画面の保存と同じ)
            _store.commit(tid, doc, why=why)
        return out


def edit_fields(tid, row_id, why, state, change):
    """反映の共通: before = state(g) → change(doc, g, before)。change が None を返したら書かない(-> None)・
    ほかの値を返したら書いて -> (before, state(g), change の戻り値)。断るときは change の中で Refused"""
    def fn(doc, g):
        before = state(g)
        extra = change(doc, g, before)
        return (False, None) if extra is None else (True, (before, state(g), extra))
    return edit_row(tid, row_id, fn, why)


def revert_fields(tid, row_id, why, state, was, still, put, changed_msg):
    """Z の共通: 行の今 now = state(g) が答える前(was(now))で答えたあとの形でない(not still(now))= もう戻っている -> False(書かない)。
    答えたあとの形でなければ Refused(changed_msg, 409, changed)。答えたあとのままなら put(doc, g) で戻して -> True"""
    def fn(doc, g):
        now = state(g)
        if was(now) and not still(now):
            return False, False   # もう戻っている(やりかけの Z のやり直し)
        if not still(now):
            raise _apply.Refused(changed_msg, 409, "changed")
        put(doc, g)
        return True, True
    return edit_row(tid, row_id, fn, why)


def doc_id(card, msg):
    """カードの target.docId(形が違えば Refused(msg, 400, bad_request))"""
    tid = (card.get("target") or {}).get("docId")
    if not isinstance(tid, str) or not _yschemas.TID_RE.match(tid):
        raise _apply.Refused(msg, 400, "bad_request")
    return tid


def row_target(card, msg="カードの行を特定できません", row_re=None):
    """カードの target -> (docId, row)。row_re を渡すと行の id の形も見る。違えば Refused(msg, 400, bad_request)"""
    t = card.get("target") or {}
    tid, rid = t.get("docId"), t.get("row")
    if (not isinstance(tid, str) or not _yschemas.TID_RE.match(tid) or not isinstance(rid, str) or not rid
            or (row_re is not None and not row_re.match(rid))):
        raise _apply.Refused(msg, 400, "bad_request")
    return tid, rid


def choice(choices, label="答え(choice)", only=False):
    """答え {choice} の検査を作る(only = choice のほかの欄を許さない)。-> check(answer) -> {choice}。違えば ValueError(400)"""
    def check(ans):
        c = ans.get("choice") if isinstance(ans, dict) else None
        if c not in choices or (only and set(ans) != {"choice"}):
            raise ValueError("%sは %s のどれかです" % (label, "・".join(choices)))
        return {"choice": c}
    return check
