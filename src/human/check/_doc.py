"""「確かめる」の文書の行を直す 1 つの口(読み・時刻・声のカードの反映と Z が使う。opt-human 6-1)。

edit_row(tid, row_id, fn, why): 保存の錠 → この文書を書き換えるジョブの最中なら断る → 文書を読み直す → 評価用なら断る → 行を探す →
  fn(doc, seg) -> (変えたか, 戻り値) → 変えたときだけ updatedAt を進めて、履歴(10 分に 1 つ。編集の画面の保存と同じ)→ store.commit(why)。
  断るときの理由は 4 つの種類で同じ: 503 unavailable(文字起こしの置き場所が決まっていない)・409 busy・409 no_doc・409 eval・409 no_row。
  O1 の控え(overrides.save_after)は呼ばない(作り直しの引き継ぎは文書から取り出す = 控えが古くても失われない。6d-2)。
印(行の flag)の「、」で割る・つなぐもここ(human/proof/layers.join_flags と同じ決まり = 同じ印は 1 つ・空は捨てる・100 字まで)。
③ の層: 文書は human/proof の store と layers、ジョブの最中かは ② flow/jobs の読み口だけを読む。
"""
import time

from ytt import errors as _errors, schemas as _yschemas, workdata as _workdata
from flow import jobs as _heavy
from human.proof import layers as _layers, store as _store
from . import apply as _apply   # 同じ human/check の兄弟

# この文書を書き換えないジョブ(2 つ目のエンジン・サムネの案・30fps の作り直し)と、確かめるが自分で足す声の覚え直しは「最中」に数えない。
# ほかの種類(文字起こし・話者判別・再認識・疑わしい所・これから足す種類)の最中は、答えが結果で消えるので断る
NOT_BUSY_KINDS = ("alt", "thumb", "normalize", "voice-learn")


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


def flag_parts(flag):
    """行の印を「、」で割る(空は捨てる)"""
    return [x for x in str(flag or "").split("、") if x]


def join_flags(parts):
    return _layers.join_flags(*parts)
