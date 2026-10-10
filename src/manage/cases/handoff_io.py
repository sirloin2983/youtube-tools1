# -*- coding: utf-8 -*-
"""③ 受け渡し: 切り抜きスタジオ(と旧クリップマーカー)のマークを読む・元の配信の情報(clip/v1)・受け渡しの JSON と SRT を動画の隣に保存
(docs/spec/pipeline.md の 2・4・6。段10 で editor/serve.py から分けた ed_misc。役割で組み直す RS3-E7(2026-10-10)に manage/cases/handoff_io.py へ移した。
旧い名前 ed_misc は転送だけの殻 = RS5 で消す)。

- フォルダの一括読み込みと文字起こし済みの範囲(transcribed_ranges)は human/proof/batch.py(進行度 progress は編集 0.69.0 で消した)
- .runtime の置き場所 runtime_path_dir は app(editor/ed_state.py)
- 名前 handoff_io はスタジオの handoff(配信 → 編集の受け渡しの書き手)と重ねないため
名前は serve.py からも見える(serve.py の名前の受付 _ED_MODULES がこの部品へ転送する。テストの S.名前 = … もここに入る)。
ほかの部品の名前は `モジュール.名前` の形で呼ぶたびに読む(差し替えが効くように。from … import はしない)。
"""
import functools
import json
import os

from ytt import errors as _errors, fsio as _fsio, schemas as _yschemas  # noqa: E402
from ytt import tools as _tools, workdata as _workdata  # noqa: E402   (置き場所と版の今の値・動画と音声の小道具。RS3-0A に ed_state・ed_store から移した)
from pipeline.pack import resolve_export  # noqa: E402   (受け渡しの JSON と SRT の組み立て build_*。RS3-E5b に pipeline_io から pipeline/pack へ)
from ytt import txbase as _txbase  # noqa: E402   ロガー log(RS3-E7 まで ed_state の別名で読んでいた)
from human.proof import store as _store  # noqa: E402   文書の読み・編集の内容(呼ぶたびに _store.名前 で読む)
from human.proof import batch as _batch  # noqa: E402   文字起こし済みの範囲 transcribed_ranges(フォルダの一括と同じ 1 か所)
from . import pipeline_io  # noqa: E402   (受け渡しの読み・保存。RS3-E5b に editor から manage/cases へ)


# ---------- clip-marker との連携 ----------
OTHER_JSON_MAX = 64 * 1024 * 1024   # 他のツールが書く JSON(スタジオの data.json・旧マーカー・波形の記録)を読む上限(これより大きいものは読めない扱い)
# 他のツール(スタジオ・旧マーカー)が書くファイルを読む。BOM 付きでも読む。読めなければ None(ytt.fsio.read_json_or。名前はテストが呼ぶので残す)
_read_json_file = functools.partial(_fsio.read_json_or, default=None, max_bytes=OTHER_JSON_MAX)  # lint: keep 写しではなく別名(上限つき。名前はテストが呼ぶ)


def studio_out_dir(data_path):
    """スタジオの書き出し先。明示設定がなければ、スタジオと同じ exports を使う。"""
    for name in ("settings.json", "config.json"):
        s = _read_json_file(os.path.join(os.path.dirname(data_path), name))
        if isinstance(s, dict):
            v = s.get("outDir")
            if not v and isinstance(s.get("settings"), dict):
                v = s["settings"].get("outDir")
            if isinstance(v, str) and v.strip():
                p = v.strip()
                if not os.path.isabs(p):
                    p = os.path.join(os.path.dirname(data_path), p)
                return os.path.abspath(p)
    return os.path.abspath(os.path.join(os.path.dirname(data_path), "exports"))


def _covered(ranges, path, start, end):
    """path の [start,end] が、すでにある文字起こしに含まれているか(全体を処理したものは常に含む。部分は9割以上重なれば含む)。"""
    k = _fsio.norm_path(path)
    length = max(0.0001, end - start)
    for r in ranges:
        if r["path"] != k:
            continue
        if r["whole"]:
            return r["tid"]
        ov = min(r["end"] if r["end"] is not None else end, end) - max(r["start"], start)
        if ov > 0 and ov / length >= 0.9:
            return r["tid"]
    return ""


def read_marker():
    """切り抜きスタジオ(優先)と、旧クリップマーカーのマークを読む。どちらも読むだけで、書き換えない。"""
    videos, srcs, seen = [], [], set()
    out_dir = ""
    for kind, path in (("studio", _workdata.STUDIO_DATA), ("marker", _workdata.MARKER_DATA)):
        if not os.path.isfile(path):
            continue
        d = _read_json_file(path)
        if d is None:
            continue
        vs = marker_videos(d)
        srcs.append({"kind": kind, "path": path, "videos": len(vs)})
        if kind == "studio":
            out_dir = studio_out_dir(path)
        for v in vs:
            if v["videoId"] in seen:
                continue
            if kind == "studio" and out_dir:   # 書き出し済みの mp4(書き出し先からの相対パス)が実在すれば、その絶対パスを付ける
                base = os.path.realpath(out_dir)
                for c in v["clips"]:
                    if c["file"] and not os.path.isabs(c["file"]):
                        fp = os.path.realpath(os.path.join(base, c["file"]))
                        if os.path.commonpath([base, fp]) == base and os.path.isfile(fp):
                            c["fileAbs"] = fp
            seen.add(v["videoId"])
            videos.append({**v, "from": kind})
    ranges = _batch.transcribed_ranges()   # 文字起こし済みの範囲(② のフォルダの一括と同じ 1 か所。S.transcribed_ranges の差し替えが届く)
    for v in videos:   # すでに文字起こし済みのポイントに印を付ける(書き出し済みの mp4、または元の動画パス+同じ範囲)
        for c in v["clips"]:
            if c.get("fileAbs"):
                c["doneTid"] = _covered(ranges, c["fileAbs"], 0.0, 10 ** 9) or ""
            elif v.get("sourcePath"):
                c["doneTid"] = _covered(ranges, v["sourcePath"], c["start"], c["end"])
            else:
                c["doneTid"] = ""
    return {"found": bool(srcs), "videos": videos, "sources": srcs, "outDir": out_dir}


def marker_videos(d):
    """マークの一覧を取り出す。切り抜きスタジオ/旧クリップマーカーのどちらの形でも読めるようにゆるく解釈する
    (videos は {ID: 動画} でも [動画, ...] でもよい。マークは clips / marks / points のどれか)。"""
    out = []
    vids = d.get("videos") if isinstance(d, dict) else None
    if isinstance(vids, list):
        vids = {str((v or {}).get("videoId") or (v or {}).get("id") or i): v for i, v in enumerate(vids) if isinstance(v, dict)}
    if not isinstance(vids, dict):
        return out
    for vid, v in list(vids.items())[:500]:
        if not isinstance(v, dict) or v.get("demo"):
            continue
        raw = next((v[k] for k in ("clips", "marks", "points") if isinstance(v.get(k), list)), [])
        clips = []
        for c in raw[:500]:
            if not isinstance(c, dict):
                continue
            a, b = _yschemas.num_or(c.get("start")), _yschemas.num_or(c.get("end"))
            if a is None or b is None or b <= a:
                continue
            clips.append({"id": str(c.get("id", ""))[:40], "start": a, "end": b, "title": str(c.get("title") or c.get("label") or "")[:120],
                          "status": str(c.get("status") or "")[:12], "rating": int(_yschemas.num_or(c.get("rating"), 0) or 0), "file": str(c.get("file") or "")[:500],
                          "src": str(c.get("src") or "")[:8], "score": _yschemas.num_or(c.get("score"))})
        if clips:
            out.append({"videoId": str(vid)[:20], "title": str(v.get("title", ""))[:120], "local": v.get("local") is True or str(v.get("kind", "")) in ("local", "file"),
                        "fileName": str(v.get("fileName", ""))[:200], "sourcePath": str(v.get("sourcePath") or v.get("path") or "")[:500], "clips": clips})
    return out


# ---------- 受け渡しの API(docs/spec/pipeline.md の 2・4・6) ----------
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


def transcript_v1(tid):
    return resolve_export.build_transcript_v1(_store.read_transcript(tid), _workdata.SERVER_VERSION)


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
        obj = resolve_export.build_transcript_v1(doc, _workdata.SERVER_VERSION)
        count, schema = len(obj["segments"]), pm.TRANSCRIPT_SCHEMA
        if not count:
            raise _errors.ApiError("empty", "書き出す行がありません(文字のある行がありません)", 400)
        data = (json.dumps(obj, ensure_ascii=False, indent=1) + "\n").encode("utf-8")
    elif fmt == "cut-plan-v1":
        obj = resolve_export.build_cut_plan_v1(doc, _workdata.SERVER_VERSION)
        ed, _broken = _store.read_edit(tid)
        if ed:   # 「編集」のカットがあれば、残す区間はそのとおり(行の区間ではなく)
            obj["segments"] = [{"id": "segment-%03d" % i, "start": a, "end": b, "status": "adopted", "label": ""}
                               for i, (a, b) in enumerate(_store.edit_keeps_sec(ed), 1)]
        count, schema = len(obj["segments"]), pm.CUT_PLAN_SCHEMA
        if not count:
            raise _errors.ApiError("empty", "残す区間がありません(すべての行が「カット済」か、文字のある行がありません)", 400)
        data = (json.dumps(obj, ensure_ascii=False, indent=1) + "\n").encode("utf-8")
    else:
        try:
            wrap = max(0, min(200, int(req.get("wrap") or 0)))
        except (TypeError, ValueError):
            wrap = 0
        text, count = resolve_export.build_srt(doc, wrap, req.get("speakerNames") is True)
        schema = None   # SRT は中身で「前にこのツールが書いたか」を判断できないので、同名があれば常に別名にする
        if not count:
            raise _errors.ApiError("empty", "書き出す行がありません(文字のある行がありません)", 400)
        data = text.encode("utf-8")   # BOM なし(docs/spec/pipeline.md の 1)
    try:
        path, overwritten = pm.save_beside(src, suffix, data, schema)
    except pm.PipelineError as e:
        raise _pipeline_error(e)
    _txbase.log.info("動画の隣に保存: %s %s(%s)", fmt, os.path.basename(path), "上書き" if overwritten else "新規")
    return {"path": path, "name": os.path.basename(path), "overwritten": overwritten, "format": fmt, "count": count}
