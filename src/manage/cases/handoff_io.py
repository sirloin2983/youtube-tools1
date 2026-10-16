# -*- coding: utf-8 -*-
"""④ 受け渡し: 元の配信の情報(clip/v1)・受け渡しの JSON と SRT を動画の隣に保存
(notes:docs/spec/pipeline.md の 2・4・6。段10 で editor/serve.py から分けた ed_misc。役割で組み直す RS3-E7(2026-10-10)に manage/cases/handoff_io.py へ移した。
旧い名前 ed_misc は転送だけの殻 = RS5 で消す)。

- .runtime の置き場所 runtime_path_dir は app(editor/ed_state.py)
- 名前 handoff_io はスタジオの handoff(配信 → 編集の受け渡しの書き手)と重ねないため
名前は serve.py からも見える(serve.py の名前の受付 _ED_MODULES がこの部品へ転送する。テストの S.名前 = … もここに入る)。
ほかの部品の名前は `モジュール.名前` の形で呼ぶたびに読む(差し替えが効くように。from … import はしない)。
"""
import functools
import json
import os

from ytt import errors as _errors, fsio as _fsio  # noqa: E402
from ytt import studiodata as _studiodata, tools as _tools  # noqa: E402   (スタジオの data.json の読み口・動画と音声の小道具。RS3-0A に移した)
from flow import pack as _flowpack  # noqa: E402   (受け渡しの JSON と SRT の組み立て。RS6 a-5a に pipeline/pack/resolve_export から。呼ぶたびに _flowpack.名前 で読む)
from ytt import txbase as _txbase  # noqa: E402   ロガー log(RS3-E7 まで ed_state の別名で読んでいた)
from human.proof import store as _store  # noqa: E402   文書の読み・編集の内容(呼ぶたびに _store.名前 で読む)
from . import pipeline_io  # noqa: E402   (受け渡しの読み・保存。RS3-E5b に editor から manage/cases へ)


# ---------- 他のツールが書く JSON の読み ----------
# 他のツール(スタジオなど)が書くファイルを読む。BOM 付きでも読む。読めなければ None(ytt.fsio.read_json_or。名前はテストが呼ぶので残す)
_read_json_file = functools.partial(_fsio.read_json_or, default=None, max_bytes=_studiodata.STUDIO_JSON_MAX)  # lint: keep 写しではなく別名(上限つき。名前はテストが呼ぶ)


# ---------- 受け渡しの API(notes:docs/spec/pipeline.md の 2・4・6) ----------
def _pipeline_error(e):
    return _errors.ApiError(e.code, e.message, e.status)


def clip_info(path):
    """GET /api/clip-info?path=。path は動画のパスか、.clip.json のパス(画面の ?clip= 用)。
    戻り値 {"clip": clip/v1 または null, "clipPath", "mediaPath", "warning"}。clip が使えないときは clip=null と理由(warning)。
    path が空・動画でも .clip.json でもないときだけ 400(画面が ?media= で開いたときに、例外にせず表示だけ省けるように)。"""
    pm = pipeline_io
    p = str(path or "").strip().strip('"')
    if not p or "\x00" in p:
        raise _errors.ApiError("bad_request", "path(動画のパス)を指定してください", 400)
    out = {"clip": None, "clipPath": None, "mediaPath": None, "warning": None}
    if pm.is_network_path(p):
        # 画面は URL の ?media= を受けて自動でこれを呼ぶ(他のサイトのリンクでも開ける)。ネットワークのパスを調べると
        # Windows がそのサーバーへ資格情報を送るので、ここでは調べない(文字起こしの開始ボタンでは従来どおり使える)
        out["warning"] = "ネットワーク上のパスは、元の配信の情報を自動では調べません"
        return out
    p = os.path.abspath(p)
    if p.lower().endswith(pm.CLIP_SUFFIX):
        if not os.path.isfile(p):
            out["warning"] = ".clip.json が見つかりません"
            return out
        clip, warn = pm.load_clip_file(p)
        out.update({"clip": clip, "clipPath": p if clip else None, "warning": warn})
        if clip:
            out["mediaPath"] = pm.resolve_clip_media(p, clip, _tools.MEDIA_TYPES)
            if not out["mediaPath"]:
                out["warning"] = ".clip.json が指す動画が見つかりません(同じフォルダにも見当たりません)"
        return out
    if os.path.splitext(p)[1].lower() not in _tools.MEDIA_TYPES:
        raise _errors.ApiError("bad_ext", "動画・音声ファイルか .clip.json のパスを指定してください", 400)
    if not os.path.isfile(p):
        out["warning"] = "動画が見つかりません(パスを確認してください)"
        return out
    clip, warn, cp = pm.find_clip(p)   # ここでは長さの照合はしない(ffmpeg を呼ばず、すぐ返す)
    out.update({"clip": clip, "clipPath": cp if clip else None, "mediaPath": p, "warning": warn})
    return out


def export_file(req):
    """POST /api/export-file {"id", "format": transcript-v1|srt|cut-plan-v1, "baseUpdatedAt"?, "wrap"?, "speakerNames"?}
    → 動画の隣に保存して {"path", "name", "overwritten", "format", "count"}。保存済みの内容を書き出す(画面は先に保存してから呼ぶ)。
    baseUpdatedAt を付けると、保存済みの版と違うとき 409(画面の表示と違う内容を書き出さないため)。"""
    pm = pipeline_io
    tid = str(req.get("id") or "")
    fmt = req.get("format")
    if fmt not in pm.EXPORT_FORMATS:
        raise _errors.ApiError("bad_format", "format は transcript-v1 / srt / cut-plan-v1 のどれかにしてください", 400)
    doc = _store.read_transcript(tid)
    b = req.get("baseUpdatedAt")
    if b is not None and doc.get("updatedAt") and b != doc.get("updatedAt"):
        raise _errors.ApiError("conflict", "保存されていない変更があるか、別の場所で更新されています。保存してから、もう一度書き出してください", 409)
    src = str(doc.get("sourcePath") or "")
    if not src:
        raise _errors.ApiError("no_media", "この文字起こしには元の動画のパスがありません(動画の隣には保存できません。ダウンロードを使ってください)", 400)
    if not os.path.isfile(src):
        raise _errors.ApiError("no_media", "元の動画が見つかりません(移動・削除した可能性があります): %s" % src, 400)
    suffix = pm.EXPORT_FORMATS[fmt]
    if fmt == "transcript-v1":
        obj, count = _flowpack.handoff_files(doc, fmt)
        schema = pm.TRANSCRIPT_SCHEMA
        if not count:
            raise _errors.ApiError("empty", "書き出す行がありません(文字のある行がありません)", 400)
        data = (json.dumps(obj, ensure_ascii=False, indent=1) + "\n").encode("utf-8")
    elif fmt == "cut-plan-v1":
        ed, _broken = _store.read_edit(tid)
        # 「編集」のカットがあれば、残す区間はそのとおり(行の区間ではなく)
        obj, count = _flowpack.handoff_files(doc, fmt, keeps=_store.edit_keeps_sec(ed) if ed else None)
        schema = pm.CUT_PLAN_SCHEMA
        if not count:
            raise _errors.ApiError("empty", "残す区間がありません(すべての行が「カット済」か、文字のある行がありません)", 400)
        data = (json.dumps(obj, ensure_ascii=False, indent=1) + "\n").encode("utf-8")
    else:
        try:
            wrap = max(0, min(200, int(req.get("wrap") or 0)))
        except (TypeError, ValueError):
            wrap = 0
        text, count = _flowpack.handoff_files(doc, fmt, wrap, req.get("speakerNames") is True)
        schema = None   # SRT は中身で「前にこのツールが書いたか」を判断できないので、同名があれば常に別名にする
        if not count:
            raise _errors.ApiError("empty", "書き出す行がありません(文字のある行がありません)", 400)
        data = text.encode("utf-8")   # BOM なし(notes:docs/spec/pipeline.md の 1)
    try:
        path, overwritten = pm.save_beside(src, suffix, data, schema)
    except pm.PipelineError as e:
        raise _pipeline_error(e)
    _txbase.log.info("動画の隣に保存: %s %s(%s)", fmt, os.path.basename(path), "上書き" if overwritten else "新規")
    return {"path": path, "name": os.path.basename(path), "overwritten": overwritten, "format": fmt, "count": count}
