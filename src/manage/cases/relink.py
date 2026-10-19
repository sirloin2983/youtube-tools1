# -*- coding: utf-8 -*-
"""④ 文書と動画の紐づけ: 動画を選び直す(付け替え)・まとめて付け替える・「参照…」・素材を 30fps にそろえる

- 評価用のフォルダの整理(名前をそろえる・仮置き・外からの取り込み)は manage/keep/evalfolders.py(付け替えの書き込み _relink_write をここから読む = ④ → ③ の下向き)
- 評価用のフォルダの判定(eval_dirs・in_eval_dir・eval_name_guard)は ytt/settings、別のドライブへの移動は ytt/fsio(RS3-1)
名前は serve.py からも見える(serve.py の名前の受付 _ED_MODULES がこの部品へ転送する。テストの S.名前 = … もここに入る)。
ほかの部品の名前は `モジュール.名前` の形で呼ぶたびに読む(差し替えが効くように。from … import はしない)。編集の画面の部品(状態・ジョブ・文書の保存)は読まない。
"""
import os
import re
import time

from ytt import errors as _errors, fsio as _fsio, normalize as _vnorm, schemas as _yschemas  # noqa: E402
from flow import jobs as _heavy, normalize as _flownorm  # noqa: E402
from ytt import settings as _settings  # noqa: E402   評価用のフォルダの判定 in_eval_dir・eval_name_guard(RS3-1 に ed_relink から ytt/settings へ)
from ytt import tools as _tools, workdata as _workdata  # noqa: E402   (置き場所と版の今の値・動画と音声の小道具)
from ytt import txbase as _txbase  # noqa: E402   ロガー log・環境変数のスイッチ env_off・ジョブの注意 add_warning(RS3-E7 まで ed_state の別名で読んでいた)
from human.proof import store as _store  # noqa: E402   文書の読み書き・保存のロック・控え・要約(呼ぶたびに _store.名前 で読む)

# ---------- 動画を選び直す(付け替え。全体の計画の段2 B-4・監査 19) ----------
# 動画を移した・改名した文書の sourcePath を、行・校正・話者・カットを残したまま新しいパスに直す。
# 選べる場所は「このパソコンのドライブならどこでも」(ユーザー決定)。ネットワーク上・ツールの作業データの中・リンクの先がそれらになるものは断る。
# URL の引数では付け替えない(POST + 合言葉 + Origin 検査だけ)。候補の自動の推測はしない
RELINK_KEEP = 10          # 文書に残す付け替えの記録(relinks)の数
RELINK_TOL_SEC = 1.0      # 動画全体の文書: 長さの差がこれ(か 0.5%)以下なら同じ動画とみなす
RELINK_TOL_RATIO = 0.005
RELINK_RANGE_TOL = 0.5    # 範囲の文書: 新しい動画の長さ ≥ 範囲の終わり − これ


def relink_path(raw):
    """付け替え先のパスの検査。ネットワーク上のパスは、ファイルに触る前に断る(存在を確かめるだけで資格情報を送るため)。
    ジャンクション・リンクを解いた先でも、もう一度 ネットワーク・「:」(NTFS の代替ストリーム)・拡張子・作業データの中 を確かめる。-> 実体のパス"""
    s = str(raw or "").strip().strip('"').strip()
    if not s or len(s) > 1000 or any(ch in s for ch in "\x00\r\n"):
        raise _errors.ApiError("bad_path", "パスを入れてください", 400)
    if _fsio.is_network_path(s):
        raise _errors.ApiError("network_path", "ネットワーク上のファイルは選べません(このパソコンにコピーしてから選んでください)", 400)
    if not os.path.isabs(s):
        raise _errors.ApiError("bad_path", "ドライブから始まるパス(例: D:\\動画\\配信.mp4)を入れてください", 400)
    p = os.path.abspath(s)
    for resolved in (False, True):
        if resolved:   # 1回目の検査を通ってから(ネットワーク上のパスには触らない)リンクを解く
            try:
                p = os.path.realpath(p)
            except (OSError, ValueError):
                raise _errors.ApiError("no_file", "ファイルが見つかりません(パスを確認してください)", 400)
        if _fsio.is_network_path(p) or _fsio.is_remote_drive(p):
            raise _errors.ApiError("network_path", "ネットワーク上のファイルは選べません(このパソコンにコピーしてから選んでください)", 400)
        if ":" in os.path.splitdrive(p)[1]:
            raise _errors.ApiError("bad_path", "パスに「:」が入っています(ファイルそのもののパスを入れてください)", 400)
        if os.path.splitext(p)[1].lower() not in _tools.MEDIA_TYPES:
            raise _errors.ApiError("bad_ext", "動画・音声ファイルではないようです(対応: %s)" % " ".join(sorted(_tools.MEDIA_TYPES)), 400)
        if _fsio.is_inside(p, _workdata.DATA_DIR):   # このツールの作業データ(文書・設定・保管)。スタジオの既定の書き出し先(作業データの studio\exports)は選べる
            raise _errors.ApiError("bad_path", "このツールの作業データの中のファイルは選べません", 400)
    if not os.path.isfile(p):
        raise _errors.ApiError("no_file", "ファイルが見つかりません(パスを確認してください)", 400)
    return p


def _relink_ref(doc):
    """比べる長さ。-> (長さ秒 または None, 動画全体の文書か)。動画全体の文書は記録した長さ、範囲の文書は範囲の終わり(無ければ最後の行の終わり)"""
    dur, end = _yschemas.num_or(doc.get("duration")), _yschemas.num_or(doc.get("end"))
    if doc.get("whole") is not False and dur and dur > 0:
        return dur, True
    if end and end > 0:
        return end, False
    ends = [_yschemas.num_or(s.get("end"), 0.0) or 0.0 for s in doc.get("segments") or [] if isinstance(s, dict)]
    return (max(ends), False) if ends and max(ends) > 0 else (None, False)


def relink_check(obj):
    """POST /api/relink/check {"id", "path"}: 付け替える前の確認(書き込まない)。
    -> {path, name, durationSec, fps, hasVideo, docDuration, diffSec, mismatch, sameAsNow, usedBy: [{id, title}], rowsAfterEnd, warnings}。
    fps・長さはカットのタブと同じ測り方(flow.pack.media_plan。音声だけのファイルは ffmpeg の長さ)"""
    from flow import pack as flowpack   # 呼ぶときに読む(RS6 a-5a に pipeline/pack/resolve_export から)
    tid = str(obj.get("id") or "")
    doc = _store.read_transcript(tid)
    p = relink_path(obj.get("path"))
    _settings.eval_name_guard(p, doc.get("evalSet") is True, "付け替えてください")   # 評価用のフォルダの設定が消えているときは、評価用のフォルダへの付け替えを止める
    dur, has_v, has_a = _tools.probe_media(p)
    if not (has_v or has_a):
        raise _errors.ApiError("bad_media", "動画・音声として読めませんでした(壊れているか、対応していない形式です)", 400)
    fps, warnings = None, []
    if has_v:
        try:
            dr = flowpack.media_plan(doc, p)
            fps, dur = dr["fps"], dr["durationSec"]
        except _errors.ResolveExportError as e:
            warnings.append("fps を調べられませんでした(%s)。カットのタブで使えない可能性があります" % str(e)[:200])
    else:
        warnings.append("映像の無いファイル(音声だけ)です。文字の直しはできますが、カットとパックには使えません")
    if not dur or dur <= 0:
        raise _errors.ApiError("bad_media", "動画の長さを読めませんでした(壊れているか、対応していない形式です)", 400)
    ref, whole = _relink_ref(doc)
    diff = round(dur - ref, 2) if ref else None
    if ref is None:
        mismatch = False
        warnings.append("この文書には元の長さの記録が無いため、長さを比べられません")
    elif whole:
        mismatch = abs(dur - ref) > max(RELINK_TOL_SEC, RELINK_TOL_RATIO * ref)
    else:
        mismatch = dur < ref - RELINK_RANGE_TOL
    if mismatch:
        warnings.append("長さが元の動画と違います(元 %s・選んだ動画 %s)。別の動画の可能性があります" % (_yschemas.fmt_hms(ref), _yschemas.fmt_hms(dur)))
    after = sum(1 for s in doc.get("segments") or [] if isinstance(s, dict) and (_yschemas.num_or(s.get("start"), 0.0) or 0.0) >= dur)
    if after:
        warnings.append("選んだ動画の終わりより後ろに %d 行あります(その行は再生できません)" % after)
    key = os.path.normcase(p)
    used = []
    for other, sm, sp in _store.summaries():
        if other != tid and sp and not _fsio.is_network_path(sp) and _fsio.norm_path(sp) == key:
            used.append({"id": other, "title": str(sm.get("title") or "")[:120]})
            if len(used) >= 10:
                break
    cur = str(doc.get("sourcePath") or "")
    same = bool(cur) and not _fsio.is_network_path(cur) and _fsio.norm_path(cur) == key
    return {"path": p, "name": os.path.basename(p), "durationSec": round(dur, 3), "fps": fps, "hasVideo": bool(has_v),
            "docDuration": round(ref, 3) if ref else None, "diffSec": diff, "mismatch": mismatch, "sameAsNow": same,
            "usedBy": used, "rowsAfterEnd": after, "warnings": warnings}


def _doc_busy(tid):
    """その文書を読み書きするジョブ(話者判別・再認識・声を覚える・比較・この文書に入れる文字起こし)が動いているか"""
    return _heavy.doc_busy(tid)   # ② の読み口(表 _jobs と錠を読まない = 設計原則のレビューの指摘 5)


def relink_doc(obj):
    """POST /api/relink {"id", "path", "baseUpdatedAt", "acceptDiff", "normalize"?}: 文書の動画を付け替える。
    動画が 30fps でなければ、付け替えたあと裏のジョブで <名前>_30fps.mp4 を作って付け替え直す(応答の normalizing = ジョブの id・
    normNote = 作れない理由。"normalize": false なら作らない = まとめて付け替える。評価用は作らない)。
    書き換えるのは sourcePath・sourceName・updatedAt と記録 relinks だけ(行・校正・話者・original・clip・start/end・カットは変えない。
    カットは秒で持っているので、fps が違っても読み込むときに合わせ直る)。書く前に履歴を残す。
    409: 先に更新された(conflict)・ジョブの最中(busy)・長さが違うのに acceptDiff が無い(duration_mismatch)"""
    tid = str(obj.get("id") or "")
    base = obj.get("baseUpdatedAt")
    if _yschemas.plain_int(base) is None:
        raise _errors.ApiError("bad_request", "baseUpdatedAt(読み込んだときの更新日時)を付けてください", 400)
    chk = relink_check(obj)   # 動画を調べるのは時間がかかるので、ロックの外で
    if chk["sameAsNow"]:
        raise _errors.ApiError("same_path", "今と同じ動画です(付け替える必要はありません)", 400)
    with _store.saving():
        doc = _store.read_transcript(tid)
        if doc.get("updatedAt") and base != doc.get("updatedAt"):
            raise _errors.ApiError("conflict", "別の場所で先に更新されています。読み込み直してから、もう一度選んでください", 409)
        if _doc_busy(tid):
            raise _errors.ApiError("busy", "この文書は、いま別の処理(文字起こし・話者判別・再認識など)の最中です。終わってから付け替えてください", 409)
        if chk["mismatch"] and obj.get("acceptDiff") is not True:
            raise _errors.ApiError("duration_mismatch", "長さが元の動画と違います。別の動画でないか確かめてから付け替えてください", 409, {"check": chk})
        now = _relink_write(tid, doc, chk["path"], chk["diffSec"])
    _txbase.log.info("動画を付け替え: %s → %s", tid, chk["name"])
    norm_job, note = None, ""
    if obj.get("normalize") is not False:   # 30fps でなければ裏で作り直して付け替える(Q1)。まとめて付け替えるは false = 作り直さない
        try:
            norm_job, note = norm_start(tid, chk["path"], doc)
        except Exception as e:   # 付け替えは済んでいるので、作り直しを始められなくても成功で返す
            _txbase.log.warning("30fps の作り直しを始められませんでした: %s %s", tid, e)
            norm_job, note = None, "30fps にそろえるのを始められませんでした。元の動画のまま使えます"
    return {"ok": True, "updatedAt": now, "sourcePath": chk["path"], "sourceName": chk["name"], "warnings": chk["warnings"],
            "normalizing": norm_job, "normNote": note}


def _relink_write(tid, doc, path, diff, why=None, bump=True):
    """付け替えの書き込み(store.saving() の中で呼ぶ)。履歴を残し、sourcePath・sourceName・updatedAt・relinks を直す。
    評価用のフォルダの中へ付け替えたら評価用の印も付ける(ユーザー決定: フォルダの中は外せない)。-> 新しい updatedAt
    bump=False: updatedAt を変えない(30fps の写しへの自動の付け替え = 中身は同じ動画。開いている画面の次の保存を 409 にしないため。
    保存 save_transcript は sourcePath を画面から受け取らないので、画面の古い版で上書きされても付け替えは消えない)"""
    _store.backup_doc(tid, "relink")   # 直前の状態を履歴へ(履歴の「以前の版に戻す」で元のパスへ戻せる)。カット(edit.json)は書き換えないので写さない(opt-human 2a-4)
    now = max(_yschemas.now_ms(), int(doc.get("updatedAt") or 0) + 1) if bump or not doc.get("updatedAt") else int(doc["updatedAt"])
    prev = [r for r in doc.get("relinks") or [] if isinstance(r, dict)]
    rec = {"from": str(doc.get("sourcePath") or ""), "at": max(now, _yschemas.now_ms()), "diffSec": diff}
    if why:
        rec["why"] = why
    doc["relinks"] = (prev + [rec])[-RELINK_KEEP:]
    doc.update({"sourcePath": path, "sourceName": os.path.basename(path), "updatedAt": now})
    if _settings.in_eval_dir(path):
        doc["evalSet"] = True
    _store.apply_edit_cuts(tid, doc)
    _store.commit(tid, doc, why="relink")
    return now


# ---------- 素材を 30fps にそろえる(マスタープラン Q1。ユーザー決定) ----------
# 計画と作り直しは ② flow/normalize の 1 つの段(OPT-M2 5b-1)。ここ(④)に残るのは文書の付け替え norm_swap と、付け替えのあとの作り直しの始め方 norm_start だけ。
# 動画を選び直したとき、動画が 30fps(H.264・yuv420p・AAC)でなければ、元の動画の隣に <名前>_30fps.mp4 を作り、文書をそれに付け替える(元は消さない)。
# 文字起こしのあとの 30fps は ② の実行の段(file)が先にそろえるので、文字起こしの続きの口 norm_after は無い(OPT-M2 5b-2)。
# - 選び直し: 付け替えはすぐに済ませ、作り直しは裏のジョブ(kind "normalize")→ できたら付け替える(付け替えの要求を待たせない。
#   失敗しても付け替えは済んでいる)。まとめて付け替える(文書の動画を移したとき)は作り直さない(normalize: false)
# - 評価用(evalSet・評価用のフォルダの中)は作り直さない(パックを作らない・評価用のフォルダの整理が動画の数を数えるため)
# - ジョブはすでに SLOTS(ytt.jobs)を持っている(ytt/jobs の work_one)。この中で取り直さない(上限 1 だと自分を待って止まる)
# - 付け替えは updatedAt を変えない(_relink_write の bump=False。開いている画面の次の保存を 409 にしない)
NORM_WHY = "normalize30"                  # 付け替えの記録 relinks[].why


def norm_swap(tid, src, dst):
    """作り直した写しへ文書を付け替える(文書の動画が src のままのときだけ)。-> None(付け替えた)か 付け替えなかった理由"""
    with _store.saving():
        try:
            doc = _store.read_transcript(tid)
        except _errors.ApiError:
            return "文書が見つからないため、付け替えませんでした(%s は残っています)" % os.path.basename(dst)
        cur = str(doc.get("sourcePath") or "")
        if not cur or _fsio.norm_path(cur) != _fsio.norm_path(src):
            return "作り直しの間に文書の動画が変わったため、付け替えませんでした(%s は残っています)" % os.path.basename(dst)
        info = _vnorm.probe(dst) or {}
        ref = _yschemas.num_or(doc.get("duration"))
        diff = round(info["duration"] - ref, 2) if info.get("duration") is not None and ref else None
        _relink_write(tid, doc, dst, diff, why=NORM_WHY, bump=False)
    _txbase.log.info("30fps の写しへ付け替え: %s → %s", tid, os.path.basename(dst))
    return None


def norm_start(tid, path, doc):
    """動画を選び直したあと: 30fps でなければ裏のジョブで作り直して付け替える。
    -> (始めたジョブの id か None, 知らせ(作らない理由。無ければ ""))。評価用・30fps なら (None, "")"""
    if doc.get("evalSet") is True or _settings.in_eval_dir(path):
        return None, ""
    plan = _flownorm.plan(path)
    if not plan:
        return None, ""
    if plan.get("note"):
        return None, plan["note"]
    title = str(doc.get("title") or os.path.basename(path))[:120]
    try:
        job = _heavy.add_job({"tid": tid, "title": title, "plan": plan}, "normalize")
    except _errors.ApiError as e:
        return None, "30fps にそろえるのを始められませんでした(%s)。元の動画のまま使えます" % e.message
    return job["id"], ""


# ---------- まとめて付け替える・「参照…」(ユーザー決定: 参照の窓 + 履歴からまとめて) ----------
# 付け替えそのものは1件ずつ /api/relink(控え・長さの確認・競合の確認を同じにするため)。ここは候補を集めるだけで、書き込まない。
# 「候補の自動の推測はしない」(段2 B-4)を、ユーザーが選んだフォルダの中の「同じファイル名」に限って緩めた。候補を選んでも、
# 長さを確かめて画面で選んだものだけを付け替える(長さが違うものは既定で選ばない)
FIND_BUDGET_SEC = 8.0     # フォルダを探す時間の上限(ドライブ全体を選ばれても固まらない)
FIND_MAX_ENTRIES = 50000  # 見るファイルとフォルダの数の上限
FIND_MAX_DEPTH = 6        # 選んだフォルダから下へ何段まで
FIND_PER_DOC = 5          # 1文書あたりの候補の数
_FIND_SKIP = {"$recycle.bin", "system volume information", "windows", "program files", "program files (x86)", "programdata", "appdata"}


def relink_missing():
    """POST /api/relink/missing: 元の動画が見つからない文書(パスの記録があるものだけ)。
    -> {items: [{id, title, sourcePath, sourceName, updatedAt}], skipped}。ネットワーク上のパスは調べない(skipped に数える)"""
    items, skipped, dirs = [], 0, {}
    for tid, sm, sp in _store.summaries():
        if not sp:
            continue
        if _fsio.is_network_path(sp) or not os.path.isabs(sp):
            skipped += 1
            continue
        folder = os.path.dirname(sp)
        try:
            if folder not in dirs:
                dirs[folder] = os.path.isdir(folder)
            ok = dirs[folder] and os.path.isfile(sp)
        except (OSError, ValueError):
            ok = False
        if not ok:
            items.append({"id": tid, "title": str(sm.get("title") or "")[:200], "sourcePath": sp,
                          "sourceName": str(sm.get("sourceName") or os.path.basename(sp))[:260], "updatedAt": sm.get("updatedAt") or 0})
    items.sort(key=lambda x: -(x["updatedAt"] or 0))
    return {"items": items, "skipped": skipped}


def relink_folder(raw):
    """探すフォルダの検査(relink_path と同じ考え: ネットワークはフォルダに触る前に断る → リンクを解いてもう一度)。-> 実体のパス"""
    s = str(raw or "").strip().strip('"').strip()
    if not s or len(s) > 1000 or any(ch in s for ch in "\x00\r\n"):
        raise _errors.ApiError("bad_path", "フォルダのパスを入れてください", 400)
    net = _errors.ApiError("network_path", "ネットワーク上のフォルダは選べません", 400)
    if _fsio.is_network_path(s):
        raise net
    if not os.path.isabs(s):
        raise _errors.ApiError("bad_path", "ドライブから始まるパス(例: D:\\動画)を入れてください", 400)
    p = os.path.abspath(s)
    if _fsio.is_remote_drive(p):
        raise net
    try:
        p = os.path.realpath(p)
    except (OSError, ValueError):
        raise _errors.ApiError("no_dir", "フォルダが見つかりません", 400)
    if _fsio.is_network_path(p) or _fsio.is_remote_drive(p):
        raise net
    if ":" in os.path.splitdrive(p)[1]:
        raise _errors.ApiError("bad_path", "パスに「:」が入っています", 400)
    if not os.path.isdir(p):
        raise _errors.ApiError("no_dir", "フォルダが見つかりません(パスを確認してください)", 400)
    if _fsio.is_inside(p, _workdata.DATA_DIR):
        raise _errors.ApiError("bad_path", "このツールの作業データの中は探せません", 400)
    return p


def relink_find(obj):
    """POST /api/relink/find {"folder", "ids"}: 選んだフォルダ(とその下)から、各文書の元の動画と同じファイル名(大文字小文字は区別しない)の動画を探す。
    -> {folder, candidates: {id: [path, …]}, scanned, truncated}。時間・数・深さに上限があり、超えたら truncated"""
    root = relink_folder(obj.get("folder"))
    want = {}
    for tid in [str(x) for x in (obj.get("ids") or [])][:500]:
        if not _yschemas.TID_RE.match(tid):
            continue
        sm = _store.transcript_summary(tid)
        name = re.split(r"[\\/]", str((sm or {}).get("_sourcePath") or ""))[-1] or str((sm or {}).get("sourceName") or "")
        if name and os.path.splitext(name)[1].lower() in _tools.MEDIA_TYPES:
            want.setdefault(os.path.normcase(name), []).append(tid)
    found = {k: [] for k in want}
    t0, seen, truncated = time.monotonic(), 0, False
    base_depth = root.rstrip("\\/").count(os.sep)
    for cur, dnames, fnames in os.walk(root):   # リンクは辿らない(followlinks=False)
        seen += len(dnames) + len(fnames)
        if seen > FIND_MAX_ENTRIES or time.monotonic() - t0 > FIND_BUDGET_SEC:
            truncated = True
            break
        for fn in fnames:
            k = os.path.normcase(fn)
            if k in found and len(found[k]) < FIND_PER_DOC:
                found[k].append(os.path.join(cur, fn))
        if cur.rstrip("\\/").count(os.sep) - base_depth >= FIND_MAX_DEPTH:
            if dnames:
                truncated = True
            dnames[:] = []
        else:
            dnames[:] = sorted(d for d in dnames if not d.startswith(".") and d.lower() not in _FIND_SKIP
                               and not _fsio.is_inside(os.path.join(cur, d), _workdata.DATA_DIR))
    cands = {tid: found[k] for k, tids in want.items() for tid in tids if found[k]}
    return {"folder": root, "candidates": cands, "scanned": seen, "truncated": truncated}


def pick_path(obj):
    """POST /api/pick {"kind": "file"|"dir", "hint"}: PC の標準の窓で動画かフォルダを選ぶ(ytt/pick.py)。
    -> {path}(やめたら "")。選んだ動画の検査は、そのあとの /api/relink/check と /api/relink/find が行う"""
    from ytt import pick as _pick
    kind = "dir" if obj.get("kind") == "dir" else "file"
    try:
        p = _pick.pick(kind, "動画のあるフォルダを選ぶ" if kind == "dir" else "動画を選ぶ", obj.get("hint") or "", _tools.MEDIA_TYPES)
    except _pick.PickBusy as e:
        raise _errors.ApiError("pick_busy", str(e), 409)
    except _pick.PickError as e:
        raise _errors.ApiError("pick_unavailable", "%s。パスを貼り付けてください" % e, 400)
    return {"path": p}
