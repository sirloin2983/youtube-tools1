# -*- coding: utf-8 -*-
"""③ 3 択の口(RS8 O2-4。決定 3-37・notes:plan/rs8-cases-ui.md の決めたこと 3 の案 A): 機械の結果が変わって人の直しと食い違う行(印 layers.MACH_CHANGED)を
前の機械・今の機械・人の直しで並べて返し、[自分の直しのまま] / [今の機械にする] を選ぶ。

- 層が正(TRANSCRIBE_LAYERS=primary)のときだけ動く(shadow・off では印は組み立てに出ない = 一覧は空・選ぶ口は 409 not_primary)
- 選んだ結果は人の層を直して store.commit(hum=…) で書く(写しは組み立て直した文書)。既定は自分の直しのまま(選ばなければ印が残るだけ)
- 画面は新しい画面の行の札(app/ui/cases/panels/machpick.js)。API は編集のサーバー src/editor/serve.py の GET /api/mach-changes・POST /api/mach-changes/pick
"""
from ytt import errors as _errors, schemas as _yschemas, txbase as _txbase  # noqa: E402
from . import layers as _layers  # noqa: E402
from . import store  # noqa: E402   文書の読み書き・保存の錠 saving・層の読み read_layers(呼ぶたびに store.名前 で読む)

PICKS = ("mine", "machine")   # mine = 自分の直しのまま・machine = 今の機械にする


def _primary():
    return _txbase.layers_mode() == _txbase.LAYERS_PRIMARY


def changes(tid, row=None):
    """GET /api/mach-changes?id=&row= -> {"layers": モード, "updatedAt", "rows": [{"id", "human", "before", "now"}…]}(layers.mach_changes。読むだけ。
    開くので写しが古ければ組み立て直す = store.read_transcript)。層が正でなければ rows は空"""
    doc = store.read_transcript(str(tid or ""))
    mode = _txbase.layers_mode()
    if mode != _txbase.LAYERS_PRIMARY:
        return {"layers": mode, "updatedAt": doc.get("updatedAt"), "rows": []}
    mach, hum = store.read_layers(doc.get("id") or tid)
    rows = _layers.mach_changes(mach, hum, row or None) if mach is not None and hum is not None else []
    return {"layers": mode, "updatedAt": doc.get("updatedAt"), "rows": rows}


def pick(obj):
    """POST /api/mach-changes/pick {"id", "row", "pick": "mine" | "machine", "baseUpdatedAt"?} -> {"ok", "row", "pick", "updatedAt"}。
    baseUpdatedAt が保存済みの版と違えば 409 conflict(画面の保存と同じ)・層が正でなければ 409 not_primary・印の付いた行で無ければ 404 not_changed。
    書く前の文書を必ず履歴に残す(store.snapshot(force=True)。「以前の版に戻す」で戻せる。P-PRIMARY = 1f-3)"""
    tid = str(obj.get("id") or "")
    rid, choice = str(obj.get("row") or ""), obj.get("pick")
    if choice not in PICKS or not rid:
        raise _errors.ApiError("bad_request", "row と pick(mine か machine)を付けてください", 400)
    if not _primary():
        raise _errors.ApiError("not_primary", "機械の層と人の層が正のとき(TRANSCRIBE_LAYERS=primary)だけ選べます", 409)
    with store.saving():
        doc = store.read_transcript(tid)
        b = obj.get("baseUpdatedAt")
        if b is not None and doc.get("updatedAt") and b != doc.get("updatedAt"):
            raise _errors.ApiError("conflict", "別の場所で先に更新されています。読み込み直してから選んでください", 409)
        mach, hum = store.read_layers(tid)
        if mach is None or hum is None or not _layers.mach_changes(mach, hum, rid):
            raise _errors.ApiError("not_changed", "その行に「機械の結果が変わりました」の印はありません", 404)
        new_hum = _layers.pick(mach, hum, rid, choice)
        store.snapshot(tid, True)   # 今の機械にするは人の直しを丸ごと外すので、前の履歴からの時間に関わらず必ず残す(1f-3)
        doc["updatedAt"] = _yschemas.now_ms()
        out = store.commit(tid, doc, why="mach_pick", hum=new_hum)
    _txbase.log.info("3 択 %s row=%s pick=%s", tid, rid, choice)
    return {"ok": True, "row": rid, "pick": choice, "updatedAt": out.get("updatedAt")}
