"""「編集」のサムネの案(提案 P5 の S。plan/thumb-ideas.md の 7・8)。作る本体は thumb_ideas.py(コマンドとしても使える独立の部品)。

- ジョブ kind `thumb`(`POST /api/thumb-ideas {id, crop?}` → `thumb_spec` → `run_thumb`)。切り抜きの動画と文書の行から 6 案を 1 枚の PNG に。
  文書は読むだけ(書き換えない・updatedAt も動かさない)ので、編集を止めるジョブ(LOCK_KINDS)にしない。同じ文書で 1 つだけ(ed_jobs.EXCLUSIVE)
- 置き場所: 動画のフォルダの 作業用/<名前>_thumb-ideas.png と同じ名前の .json(ytt_core.schemas.work_dir。パックのフォルダには入れない =
  友人へ届ける zip に混ざらないように)。作り直すと上書き
- 切り取り crop: alt(中央と右下を交互。既定)/ center / right。画面が選んだ値は編集の設定 thumbCrop(ed_learn.SETTINGS_PATCH_KEYS)に覚える
- 結果は `GET /api/thumb-ideas?id=`(thumb_info = 有無・作った時刻・案ごとの型と文字)・画像は `GET /api/thumb-ideas/image?id=`(パスは文書の動画から作る = 画面から受け取らない)
- 名前は serve.py が部品から集めるので `thumb_`・`THUMB_` で始める(ほかの部品と重ねない)
"""
import os
import time

import ed_jobs
import ed_state
import ed_store
from ytt_core import fsio as _fsio, schemas as _yschemas

THUMB_CROPS = ("alt", "center", "right")
THUMB_SUFFIX = "_thumb-ideas"
THUMB_MAX_JSON = 1024 * 1024


def thumb_paths(src):
    """動画のパス -> (png, json)(作業用 のフォルダ。無ければ作るのは書くとき)"""
    base = os.path.join(_yschemas.work_dir(src), os.path.splitext(os.path.basename(src))[0] + THUMB_SUFFIX)
    return base + ".png", base + ".json"


def _thumb_doc_src(tid):
    """文書と動画のパス(動画が無ければ ApiError)"""
    doc = ed_store.read_transcript(str(tid or ""))
    return doc, ed_state.check_source(doc.get("sourcePath"))


def thumb_spec(tid, req=None):
    """サムネの案のジョブの指定。断る: 文書が無い・動画が無い・音声だけ・同じ文書で作っている最中・crop の値が違う"""
    req = req or {}
    tid = str(tid or "")
    doc, src = _thumb_doc_src(tid)
    if _fsio.is_network_path(src):   # パックと同じ(ネットワーク上のファイルには触らない = 資格情報を送らない)。音声だけのファイルは作るときに thumb_ideas.probe が断る
        raise ed_state.ApiError("network_path", "ネットワーク上の動画では、サムネの案は作れません(このパソコンにコピーして開いてください)", 400)
    crop = req.get("crop", "alt")
    if crop not in THUMB_CROPS:
        raise ed_state.ApiError("bad_request", "切り取りの指定が正しくありません", 400)
    if ed_jobs.tid_busy(tid, ("thumb",)):
        raise ed_state.ApiError("busy", "この文書のサムネの案は、いま作っている最中です", 409)
    return {"tid": tid, "sourcePath": src, "crop": crop, "title": "サムネの案: " + (str(doc.get("title") or "") or "無題")[:100]}


def run_thumb(job):
    """6 案を描いて 1 枚にする(thumb_ideas.make)。作業データの文書は読むだけ"""
    import thumb_ideas   # 呼ばれたときに読む(サーバーの起動を重くしない)
    spec = job["spec"]
    tid = spec["tid"]
    with ed_jobs.job_errors(job, log="サムネの案で例外"):
        job["state"], job["phase"] = "running", "サムネの案を作っています"
        doc = ed_store.read_transcript(tid)
        png, _js = thumb_paths(spec["sourcePath"])
        try:
            thumb_ideas.make(spec["sourcePath"], doc, None, png, spec["crop"])
        except thumb_ideas.ThumbError as e:
            raise ed_state.ApiError("thumb_failed", "サムネの案を作れませんでした: " + e.message, 400, {"detail": e.detail}) from None
        ed_jobs.check_cancel(job)
        job["progress"] = 1.0
        ed_jobs.job_done(job, tid, "完了")


def thumb_info(tid):
    """GET /api/thumb-ideas?id= -> {"ok", "at"(作った時刻 ms | None), "crop", "cards": [{n, layout, label, at, from, crop, top, lines, word}], "file"(png の名前)}"""
    _doc, src = _thumb_doc_src(tid)
    png, js = thumb_paths(src)
    if not os.path.isfile(png):
        return {"ok": False, "at": None, "cards": [], "file": ""}
    rec = _fsio.read_json_or(js, {}, max_bytes=THUMB_MAX_JSON) or {}
    cards = rec.get("cards") if isinstance(rec.get("cards"), list) else []
    crops = sorted({str(c.get("crop") or "") for c in cards if isinstance(c, dict)})
    return {"ok": True, "at": int(os.path.getmtime(png) * 1000), "cards": cards[:6], "crops": crops, "file": os.path.basename(png),
            "folder": os.path.dirname(png), "now": int(time.time() * 1000)}


def thumb_image_path(tid):
    """画像を返すときのパス(無ければ ApiError 404)。パスは文書の動画から作る"""
    _doc, src = _thumb_doc_src(tid)
    png, _js = thumb_paths(src)
    if not os.path.isfile(png):
        raise ed_state.ApiError("not_found", "サムネの案はまだありません", 404)
    return png
