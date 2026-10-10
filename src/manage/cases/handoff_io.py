# -*- coding: utf-8 -*-
"""「編集」のサーバーの部品: clip-marker との連携・進行度・フォルダの一括読み込み・受け渡しの API(段10 で editor/serve.py から分けた。git の履歴(679ff01 以前)の docs/plan/phase10-code-split.md)。
設定の比較(A/B。run_abtest・/api/abtest・/api/evals)は 0.68.0(2026-10-10。ユーザー決定「使っていない」)で消した(戻すときは git の履歴)。

名前は serve.py からも見える(serve.py が受け付けて、この部品へ転送する。テストの S.名前 = … もここに入る)。
ほかの部品の名前は `ed_xxx.名前` の形で呼ぶたびに読む(差し替えが効くように。from … import はしない)。
"""
import functools
import json
import os

from ytt import fsio as _fsio, runtime as _runtime, schemas as _yschemas  # noqa: E402
import ed_jobs  # noqa: E402,F401
from manage.cases import pipeline_io  # noqa: E402   (受け渡しの読み・保存・.runtime。RS3-E5b に editor から manage/cases へ。RS3-0A まで ed_state.pio() の遅延ロード)
from pipeline.pack import resolve_export  # noqa: E402   (受け渡しの JSON と SRT の組み立て build_*。RS3-E5b に pipeline_io から pipeline/pack へ)
import ed_state  # noqa: E402,F401
from ytt import tools as _tools, workdata as _workdata  # noqa: E402   (置き場所と版の今の値・動画と音声の小道具。RS3-0A に ed_state・ed_store から移した)
import ed_store  # noqa: E402,F401
# ---------- clip-marker との連携 ----------
OTHER_JSON_MAX = 64 * 1024 * 1024   # 他のツールが書く JSON(スタジオの data.json・旧マーカー・波形の記録)を読む上限(これより大きいものは読めない扱い)
# 他のツール(スタジオ・旧マーカー)が書くファイルを読む。BOM 付きでも読む。読めなければ None(ytt_core.fsio.read_json_or。名前はテストが呼ぶので残す)
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


def transcribed_ranges():
    """全文字起こしの (元ファイル・範囲・全体か・id) の一覧。フォルダ一覧・マーカーのポイントで「文字起こし済み」を判定するのに使う。"""
    out = []
    for tid, sm, sp in ed_store.summaries():   # 一覧(list_transcripts)は動画・パックの有無も調べるので、ここでは要約だけを読む(キャッシュが効く)
        if not sp:
            continue
        a, b = ed_state.num(sm.get("start"), 0.0) or 0.0, ed_state.num(sm.get("end"))
        out.append({"path": ed_state.norm_path(sp), "start": a, "end": b, "whole": sm["_whole"], "tid": tid})
    return out


def _covered(ranges, path, start, end):
    """path の [start,end] が、すでにある文字起こしに含まれているか(全体を処理したものは常に含む。部分は9割以上重なれば含む)。"""
    k = ed_state.norm_path(path)
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
    ranges = transcribed_ranges()
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
            a, b = ed_state.num(c.get("start")), ed_state.num(c.get("end"))
            if a is None or b is None or b <= a:
                continue
            clips.append({"id": str(c.get("id", ""))[:40], "start": a, "end": b, "title": str(c.get("title") or c.get("label") or "")[:120],
                          "status": str(c.get("status") or "")[:12], "rating": int(ed_state.num(c.get("rating"), 0) or 0), "file": str(c.get("file") or "")[:500],
                          "src": str(c.get("src") or "")[:8], "score": ed_state.num(c.get("score"))})
        if clips:
            out.append({"videoId": str(vid)[:20], "title": str(v.get("title", ""))[:120], "local": v.get("local") is True or str(v.get("kind", "")) in ("local", "file"),
                        "fileName": str(v.get("fileName", ""))[:200], "sourcePath": str(v.get("sourcePath") or v.get("path") or "")[:500], "clips": clips})
    return out


# ---------- 進行度(校正済みの量) ----------
def progress_stats():
    """校正済みの量。学習用(評価用でない文書)と評価用を分けて数える。「聞き取れない」の印がある行は、どちらも数えない。
    文書は読み直さない(ed_store の要約のキャッシュの _prog を足し合わせる = 一覧と同じ 1 回の読み込み)"""
    tot = {"proofedSec": 0.0, "proofedLines": 0, "docs": 0, "docsProofed": 0, "totalSec": 0.0, "totalLines": 0,
           "evalDocs": 0, "evalDocsDone": 0, "evalProofedSec": 0.0, "evalProofedLines": 0, "evalPendingLines": 0}
    for _tid, sm, _sp in ed_store.summaries():
        r = sm.get("_prog")
        if r is None:
            continue
        if r["eval"]:
            tot["evalDocs"] += 1
            tot["evalDocsDone"] += 1 if r["lines"] and not r["pend"] else 0
            tot["evalProofedSec"] += r["sec"]
            tot["evalProofedLines"] += r["lines"]
            tot["evalPendingLines"] += r["pend"]
            continue
        tot["docs"] += 1
        tot["docsProofed"] += 1 if r["lines"] else 0
        tot["proofedSec"] += r["sec"]
        tot["proofedLines"] += r["lines"]
        tot["totalSec"] += r["totalSec"]
        tot["totalLines"] += r["totalLines"]
    for k in ("proofedSec", "totalSec", "evalProofedSec"):
        tot[k] = round(tot[k], 1)
    return tot


# ---------- フォルダの一括読み込み ----------
MAX_SCAN_FILES = 500


def scan_folder(path, recursive=False):
    """フォルダの中の動画・音声を一覧にする。文字起こし済み(全体を処理したもの)・待機中かも返す。"""
    p = os.path.abspath(str(path or "").strip().strip('"'))
    if not os.path.isdir(p):
        raise ed_state.ApiError("no_dir", "フォルダが見つかりません(パスを確認してください)", 400)
    found, trunc = [], False
    base_depth = p.rstrip(os.sep).count(os.sep)
    try:
        for root, dirs, files in os.walk(p):
            depth = root.rstrip(os.sep).count(os.sep) - base_depth
            # 途中のファイルの 作業用\(編集用素材 _edit.mp4 など)は拾わない(2026-09-27)
            dirs[:] = sorted(d for d in dirs if not d.startswith(".") and d != _yschemas.WORK_DIR) if recursive and depth < 3 else []
            for name in sorted(files):
                if name.startswith(".") or os.path.splitext(name)[1].lower() not in _tools.MEDIA_TYPES:
                    continue
                if len(found) >= MAX_SCAN_FILES:
                    trunc = True
                    break
                fp = os.path.join(root, name)
                try:
                    size = os.path.getsize(fp)
                except OSError:
                    continue
                found.append({"path": fp, "name": name, "rel": os.path.relpath(fp, p), "size": size})
            if trunc:
                break
    except OSError as e:
        raise ed_state.ApiError("scan_failed", "フォルダを読めませんでした: %s" % e.__class__.__name__, 400)
    for f, st in zip(found, scan_common([f["path"] for f in found])):   # 文字起こし済み・待機中の判定は scan_common の 1 か所
        f["doneTid"], f["queued"] = st["doneTid"], st["queued"]
    return {"dir": p, "files": found, "truncated": trunc}


def _done_and_active():
    """({正規化したパス: 全体を文字起こし済みの id}, {待機中・処理中の文字起こしのパス})。"""
    done = {r["path"]: r["tid"] for r in transcribed_ranges() if r["whole"]}
    with ed_jobs._jobs_lock:
        active = {ed_state.norm_path(j["spec"].get("sourcePath", "")) for j in ed_jobs._jobs.values()
                  if j.get("kind") == "transcribe" and j["state"] in ed_jobs.ACTIVE_STATES and j["spec"].get("sourcePath")}
    return done, active


def add_batch(req):
    """複数のファイルを、それぞれ別の文字起こしとして待機列に入れる(設定は共通)。同じファイルが2回あっても1回だけ入れる。"""
    paths = list({ed_state.norm_path(str(x)): str(x) for x in (req.get("paths") or []) if isinstance(x, str) and x.strip()}.values())[:MAX_SCAN_FILES]
    if not paths:
        raise ed_state.ApiError("empty", "対象のファイルがありません", 400)
    skip_done = req.get("skipDone") is not False
    info = {ed_state.norm_path(f["path"]): f for f in scan_common(paths)} if skip_done else {}
    added, skipped = [], []
    for fp in paths:
        k = ed_state.norm_path(fp)
        f = info.get(k)
        if f and (f["doneTid"] or f["queued"]):
            skipped.append({"path": fp, "reason": "文字起こし済み" if f["doneTid"] else "すでに待機中"})
            continue
        try:
            spec = ed_jobs.validate_job({**req, "sourcePath": fp, "title": "", "start": 0, "end": None})
            added.append(ed_jobs.public_job(ed_jobs.add_job(spec)))
        except ed_state.ApiError as e:
            skipped.append({"path": fp, "reason": e.message})
            if e.code == "busy":
                break
    return {"added": added, "skipped": skipped}


def scan_common(paths):
    """パスの一覧について、scan_folder と同じ形(doneTid / queued)を返す。
    以前はフォルダごとに scan_folder(=全文書の読み直し)を呼んでいて、サブフォルダが多いと遅く、500件を超えるフォルダでは判定が漏れた。"""
    done, active = _done_and_active()
    out = []
    for p in paths:
        k = ed_state.norm_path(p)
        out.append({"path": p, "doneTid": done.get(k, ""), "queued": k in active})
    return out


# ---------- 受け渡しの API(docs/spec/pipeline.md の 2・4・6) ----------
def _pipeline_error(e):
    return ed_state.ApiError(e.code, e.message, e.status)


def clip_info(path):
    """GET /api/clip-info?path=。path は動画のパスか、.clip.json のパス(画面の ?clip= 用)。
    戻り値 {"clip": clip/v1 または null, "clipPath", "mediaPath", "warning"}。clip が使えないときは clip=null と理由(warning)。
    path が空・動画でも .clip.json でもないときだけ 400(画面が ?media= で開いたときに、例外にせず表示だけ省けるように)。"""
    pm = pipeline_io
    p = str(path or "").strip().strip('"')
    if not p or "\x00" in p:
        raise ed_state.ApiError("bad_request", "path(動画のパス)を指定してください", 400)
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
        raise ed_state.ApiError("bad_ext", "動画・音声ファイルか .clip.json のパスを指定してください", 400)
    if not os.path.isfile(p):
        out["warning"] = "動画が見つかりません(パスを確認してください)"
        return out
    clip, warn, cp = pm.find_clip(p)   # ここでは長さの照合はしない(ffmpeg を呼ばず、すぐ返す)
    out.update({"clip": clip, "clipPath": cp if clip else None, "mediaPath": p, "warning": warn})
    return out


def transcript_v1(tid):
    return resolve_export.build_transcript_v1(ed_store.read_transcript(tid), _workdata.SERVER_VERSION)


def export_file(req):
    """POST /api/export-file {"id", "format": transcript-v1|srt|cut-plan-v1, "baseUpdatedAt"?, "wrap"?, "speakerNames"?}
    → 動画の隣に保存して {"path", "name", "overwritten", "format", "count"}。保存済みの内容を書き出す(画面は先に保存してから呼ぶ)。
    baseUpdatedAt を付けると、保存済みの版と違うとき 409(画面の表示と違う内容を書き出さないため)。"""
    pm = pipeline_io
    tid = str(req.get("id") or "")
    fmt = req.get("format")
    if fmt not in pm.EXPORT_FORMATS:
        raise ed_state.ApiError("bad_format", "format は transcript-v1 / srt / cut-plan-v1 のどれかにしてください", 400)
    doc = ed_store.read_transcript(tid)
    b = req.get("baseUpdatedAt")
    if b is not None and doc.get("updatedAt") and b != doc.get("updatedAt"):
        raise ed_state.ApiError("conflict", "保存されていない変更があるか、別の場所で更新されています。保存してから、もう一度書き出してください", 409)
    src = str(doc.get("sourcePath") or "")
    if not src:
        raise ed_state.ApiError("no_media", "この文字起こしには元の動画のパスがありません(動画の隣には保存できません。ダウンロードを使ってください)", 400)
    if not os.path.isfile(src):
        raise ed_state.ApiError("no_media", "元の動画が見つかりません(移動・削除した可能性があります): %s" % src, 400)
    suffix = pm.EXPORT_FORMATS[fmt]
    if fmt == "transcript-v1":
        obj = resolve_export.build_transcript_v1(doc, _workdata.SERVER_VERSION)
        count, schema = len(obj["segments"]), pm.TRANSCRIPT_SCHEMA
        if not count:
            raise ed_state.ApiError("empty", "書き出す行がありません(文字のある行がありません)", 400)
        data = (json.dumps(obj, ensure_ascii=False, indent=1) + "\n").encode("utf-8")
    elif fmt == "cut-plan-v1":
        obj = resolve_export.build_cut_plan_v1(doc, _workdata.SERVER_VERSION)
        ed, _broken = ed_store.read_edit(tid)
        if ed:   # 「編集」のカットがあれば、残す区間はそのとおり(行の区間ではなく)
            obj["segments"] = [{"id": "segment-%03d" % i, "start": a, "end": b, "status": "adopted", "label": ""}
                               for i, (a, b) in enumerate(ed_store.edit_keeps_sec(ed), 1)]
        count, schema = len(obj["segments"]), pm.CUT_PLAN_SCHEMA
        if not count:
            raise ed_state.ApiError("empty", "残す区間がありません(すべての行が「カット済」か、文字のある行がありません)", 400)
        data = (json.dumps(obj, ensure_ascii=False, indent=1) + "\n").encode("utf-8")
    else:
        try:
            wrap = max(0, min(200, int(req.get("wrap") or 0)))
        except (TypeError, ValueError):
            wrap = 0
        text, count = resolve_export.build_srt(doc, wrap, req.get("speakerNames") is True)
        schema = None   # SRT は中身で「前にこのツールが書いたか」を判断できないので、同名があれば常に別名にする
        if not count:
            raise ed_state.ApiError("empty", "書き出す行がありません(文字のある行がありません)", 400)
        data = text.encode("utf-8")   # BOM なし(docs/spec/pipeline.md の 1)
    try:
        path, overwritten = pm.save_beside(src, suffix, data, schema)
    except pm.PipelineError as e:
        raise _pipeline_error(e)
    ed_state.log.info("動画の隣に保存: %s %s(%s)", fmt, os.path.basename(path), "上書き" if overwritten else "新規")
    return {"path": path, "name": os.path.basename(path), "overwritten": overwritten, "format": fmt, "count": count}


def runtime_path_dir():
    """<editor の1つ上>/.runtime(環境変数 YTT_RUNTIME_DIR が優先)。pipeline_io.runtime_dir と同じ規則。"""
    return _runtime.runtime_dir(_workdata.ROOT)
