# -*- coding: utf-8 -*-
"""② フォルダの一括読み込み: フォルダの中の動画・音声の一覧と、選んだファイルをそれぞれ別の文字起こしとして待機列に入れる・文字起こし済みの範囲
(段10 で editor/serve.py から分けた ed_misc の一部。役割で組み直す RS3-E7(2026-10-10)に human/proof/batch.py へ切り出した)。

- transcribed_ranges(全文字起こしの元ファイルと範囲)は ③ のマーカーの読み(manage/cases/handoff_io.read_marker)も呼ぶ(③ → ② の下向き)
名前は serve.py からも見える(serve.py の名前の受付 _ED_MODULES がこの部品へ転送する。テストの S.名前 = … もここに入る)。
ほかの部品の名前は `モジュール.名前` の形で呼ぶたびに読む(差し替えが効くように。from … import はしない)。
"""
import os

from ytt import errors as _errors, fsio as _fsio, schemas as _yschemas, tools as _tools  # noqa: E402
from flow import jobs as _heavy  # noqa: E402
from . import store as _store  # noqa: E402   文書の要約(summaries。呼ぶたびに _store.名前 で読む)
from . import doc_jobs  # noqa: E402   文字起こしの受付 validate_job・画面に返すジョブの形 public_job(呼ぶたびに doc_jobs.名前 で読む)


# ---------- 文字起こし済みの範囲(フォルダ一覧・マーカーのポイントの「文字起こし済み」の判定の 1 か所) ----------
def transcribed_ranges():
    """全文字起こしの (元ファイル・範囲・全体か・id) の一覧。フォルダ一覧・マーカーのポイントで「文字起こし済み」を判定するのに使う。"""
    out = []
    for tid, sm, sp in _store.summaries():   # 一覧(list_transcripts)は動画・パックの有無も調べるので、ここでは要約だけを読む(キャッシュが効く)
        if not sp:
            continue
        a, b = _yschemas.num_or(sm.get("start"), 0.0) or 0.0, _yschemas.num_or(sm.get("end"))
        out.append({"path": _fsio.norm_path(sp), "start": a, "end": b, "whole": sm["_whole"], "tid": tid})
    return out


# ---------- フォルダの一括読み込み ----------
MAX_SCAN_FILES = 500


def scan_folder(path, recursive=False):
    """フォルダの中の動画・音声を一覧にする。文字起こし済み(全体を処理したもの)・待機中かも返す。"""
    p = os.path.abspath(str(path or "").strip().strip('"'))
    if not os.path.isdir(p):
        raise _errors.ApiError("no_dir", "フォルダが見つかりません(パスを確認してください)", 400)
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
        raise _errors.ApiError("scan_failed", "フォルダを読めませんでした: %s" % e.__class__.__name__, 400)
    for f, st in zip(found, scan_common([f["path"] for f in found])):   # 文字起こし済み・待機中の判定は scan_common の 1 か所
        f["doneTid"], f["queued"] = st["doneTid"], st["queued"]
    return {"dir": p, "files": found, "truncated": trunc}


def _done_and_active():
    """({正規化したパス: 全体を文字起こし済みの id}, {待機中・処理中の文字起こしのパス})。"""
    done = {r["path"]: r["tid"] for r in transcribed_ranges() if r["whole"]}
    with _heavy._jobs_lock:
        active = {_fsio.norm_path(j["spec"].get("sourcePath", "")) for j in _heavy._jobs.values()
                  if j.get("kind") == "transcribe" and j["state"] in _heavy.ACTIVE_STATES and j["spec"].get("sourcePath")}
    return done, active


def add_batch(req):
    """複数のファイルを、それぞれ別の文字起こしとして待機列に入れる(設定は共通)。同じファイルが2回あっても1回だけ入れる。"""
    paths = list({_fsio.norm_path(str(x)): str(x) for x in (req.get("paths") or []) if isinstance(x, str) and x.strip()}.values())[:MAX_SCAN_FILES]
    if not paths:
        raise _errors.ApiError("empty", "対象のファイルがありません", 400)
    skip_done = req.get("skipDone") is not False
    info = {_fsio.norm_path(f["path"]): f for f in scan_common(paths)} if skip_done else {}
    added, skipped = [], []
    for fp in paths:
        k = _fsio.norm_path(fp)
        f = info.get(k)
        if f and (f["doneTid"] or f["queued"]):
            skipped.append({"path": fp, "reason": "文字起こし済み" if f["doneTid"] else "すでに待機中"})
            continue
        try:
            spec = doc_jobs.validate_job({**req, "sourcePath": fp, "title": "", "start": 0, "end": None})
            added.append(doc_jobs.public_job(_heavy.add_job(spec)))
        except _errors.ApiError as e:
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
        k = _fsio.norm_path(p)
        out.append({"path": p, "doneTid": done.get(k, ""), "queued": k in active})
    return out
