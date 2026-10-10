# -*- coding: utf-8 -*-
"""③ 文書と動画の紐づけ: 動画を選び直す(付け替え)・まとめて付け替える・「参照…」・素材を 30fps にそろえる
(段10 で editor/serve.py から分けた ed_relink。役割で組み直す RS3-E7(2026-10-10)に manage/cases/relink.py へ移した。旧い名前 ed_relink は転送だけの殻 = RS5 で消す)。

- 評価用のフォルダの整理(名前をそろえる・仮置き・外からの取り込み)は eval/drill/folders.py(付け替えの書き込み _relink_write をここから読む = ④ → ③ の下向き)
- 評価用のフォルダの判定(eval_dirs・in_eval_dir・eval_name_guard)は ytt/settings、別のドライブへの移動は ytt/fsio(RS3-1)
名前は serve.py からも見える(serve.py の名前の受付 _ED_MODULES がこの部品へ転送する。テストの S.名前 = … もここに入る)。
ほかの部品の名前は `モジュール.名前` の形で呼ぶたびに読む(差し替えが効くように。from … import はしない)。編集の ed_state・ed_jobs・ed_store は読まない(app と転送の殻)。
"""
import os
import re
import shutil
import tempfile
import time

from ytt import errors as _errors, fsio as _fsio, jobs as _heavy, normalize as _vnorm, schemas as _yschemas  # noqa: E402
from ytt import settings as _settings  # noqa: E402   評価用のフォルダの判定 in_eval_dir・eval_name_guard(RS3-1 に ed_relink から ytt/settings へ)
from ytt import tools as _tools, workdata as _workdata  # noqa: E402   (置き場所と版の今の値・動画と音声の小道具。RS3-0A に ed_state・ed_store から移した)
from ytt import txbase as _txbase  # noqa: E402   ロガー log・環境変数のスイッチ env_off・ジョブの注意 add_warning(RS3-E7 まで ed_state の別名で読んでいた)
from human.proof import store as _store  # noqa: E402   文書の読み書き・保存のロック・控え・要約(呼ぶたびに _store.名前 で読む)

# ---------- 動画を選び直す(付け替え。全体の計画の段2 B-4・監査 19。git の履歴(679ff01 以前)の docs/plan/phase2-data-safety.md の 1) ----------
# 動画を移した・改名した文書の sourcePath を、行・校正・話者・カットを残したまま新しいパスに直す。
# 選べる場所は「このパソコンのドライブならどこでも」(ユーザー決定 2026-09-29)。ネットワーク上・ツールの作業データの中・リンクの先がそれらになるものは断る。
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
    fps・長さはカットのタブと同じ測り方(resolve_export.edit_draft。音声だけのファイルは ffmpeg の長さ)"""
    from pipeline.pack import resolve_export   # 呼ぶときに読む(RS3-E5b に editor から pipeline/pack へ)
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
            dr = resolve_export.edit_draft(dict(doc, sourcePath=p), _workdata.SERVER_VERSION, rows=False)
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
    with _heavy._jobs_lock:
        return any(j["state"] in _heavy.ACTIVE_STATES and (j.get("tid") == tid or (j.get("spec") or {}).get("tid") == tid
                                                    or (j.get("spec") or {}).get("intoDoc") == tid) for j in _heavy._jobs.values())


def relink_doc(obj):
    """POST /api/relink {"id", "path", "baseUpdatedAt", "acceptDiff", "normalize"?}: 文書の動画を付け替える。
    動画が 30fps でなければ、付け替えたあと裏のジョブで <名前>_30fps.mp4 を作って付け替え直す(応答の normalizing = ジョブの id・
    normNote = 作れない理由。"normalize": false なら作らない = まとめて付け替える。評価用は作らない)。
    書き換えるのは sourcePath・sourceName・updatedAt と記録 relinks だけ(行・校正・話者・original・clip・start/end・カットは変えない。
    カットは秒で持っているので、fps が違っても読み込むときに合わせ直る)。書く前に .bak/<id>.pre-relink.json・履歴・.bak/<id>.edit.pre-relink.json を残す。
    409: 先に更新された(conflict)・ジョブの最中(busy)・長さが違うのに acceptDiff が無い(duration_mismatch)"""
    tid = str(obj.get("id") or "")
    base = obj.get("baseUpdatedAt")
    if _yschemas.plain_int(base) is None:
        raise _errors.ApiError("bad_request", "baseUpdatedAt(読み込んだときの更新日時)を付けてください", 400)
    chk = relink_check(obj)   # 動画を調べるのは時間がかかるので、ロックの外で
    if chk["sameAsNow"]:
        raise _errors.ApiError("same_path", "今と同じ動画です(付け替える必要はありません)", 400)
    with _store._save_lock:
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
    """付け替えの書き込み(_save_lock の中で呼ぶ)。控え .bak/<id>.pre-relink.json・履歴を残し、sourcePath・sourceName・updatedAt・relinks を直す。
    評価用のフォルダの中へ付け替えたら評価用の印も付ける(ユーザー決定 2026-10-01: フォルダの中は外せない)。-> 新しい updatedAt
    bump=False: updatedAt を変えない(30fps の写しへの自動の付け替え = 中身は同じ動画。開いている画面の次の保存を 409 にしないため。
    保存 save_transcript は sourcePath を画面から受け取らないので、画面の古い版で上書きされても付け替えは消えない)"""
    _store.backup_doc(tid, "relink")   # 直前の状態を1世代だけ(話者判別の pre-diarize と同じ)・「以前の版に戻す」で元のパスへ戻せる
    if os.path.isfile(_store.edit_path(tid)):
        shutil.copy2(_store.edit_path(tid), os.path.join(_workdata.TX_DIR, ".bak", tid + ".edit.pre-relink.json"))
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
    _store.write_doc(tid, doc)
    return now


# ---------- 素材を 30fps にそろえる(マスタープラン Q1。2026-10-04 ユーザー決定) ----------
# 「編集」の単体の文字起こし(動画のパスを指定)と動画を選び直したとき、動画が 30fps(H.264・yuv420p・AAC)でなければ、
# 元の動画の隣に <名前>_30fps.mp4 を作り、文書をそれに付け替える(元は消さない。作り直しは ytt/normalize.py)。
# - 順番: 文字起こしは元の動画のまま(時刻は秒なので同じ)→ 同じジョブの続きで作り直す → できたら付け替える。
#   作り直しに失敗・取り消し・隣に書けないときは、文書は元の動画のまま・ジョブの知らせ(normNote)に理由(文字起こしの結果は失わない)
# - 選び直し: 付け替えはすぐに済ませ、作り直しは裏のジョブ(kind "normalize")→ できたら付け替える(付け替えの要求を待たせない。
#   失敗しても付け替えは済んでいる)。まとめて付け替える(以前の文書の動画を移したとき)は作り直さない(normalize: false)
# - 評価用(evalSet・評価用のフォルダの中)は作り直さない(パックを作らない・評価用のフォルダの整理が動画の数を数えるため)
# - ジョブはすでに SLOTS(ytt.jobs)を持っている(ytt/jobs の work_one)。この中で取り直さない(上限 1 だと自分を待って止まる)
# - 付け替えは updatedAt を変えない(_relink_write の bump=False。開いている画面の次の保存を 409 にしない)
NORM_SUFFIX = "_30fps"
NORM_PHASE = "動画の 1 秒のコマ数を 30 にそろえています(30fps)…"   # 言葉の説明つき(2 周目 S10)   # 画面は「30fps にそろえています… n%」(ジョブの progress)
NORM_MIN_FREE = 1024 ** 3                 # 作り直しの前に、元の動画の大きさ + これだけの空きを求める
NORM_WHY = "normalize30"                  # 付け替えの記録 relinks[].why


def norm_enabled():
    """TRANSCRIBE_NORMALIZE=off で作り直さない(どの fps でも動くので、困ったときの逃げ道)"""
    return not _txbase.env_off("TRANSCRIBE_NORMALIZE")


def norm_name(src):
    """隣に作る名前 <名前>_30fps.mp4"""
    d, n = os.path.split(os.path.abspath(src))
    return os.path.join(d, os.path.splitext(n)[0] + NORM_SUFFIX + ".mp4")


def norm_usable(path, info_src):
    """すでにある写しをそのまま使えるか(30fps でそろっていて、長さが元と同じ)"""
    info = _vnorm.probe(path)
    if not info or _vnorm.needs_normalize(info)[0]:
        return False
    a, b = info.get("duration"), (info_src or {}).get("duration")
    return a is not None and (b is None or abs(a - b) <= max(_vnorm.DURATION_TOL, RELINK_TOL_RATIO * b))


def norm_plan(src):
    """作り直しの予定。-> None(作り直さない)か {"src", "dst", "reuse", "why": [理由], "note"?: 作れない理由(作らずに知らせる)}"""
    if not norm_enabled() or not src:
        return None
    src = os.path.abspath(src)
    ext = os.path.splitext(src)[1].lower()
    if _tools.MEDIA_TYPES.get(ext, "").startswith("audio/"):   # 音声だけのファイル(カバー画像を映像と数えない)
        return None
    if _fsio.is_network_path(src) or _fsio.is_remote_drive(src):
        return {"src": src, "dst": None, "reuse": False, "why": [], "note": "ネットワーク上の動画は 30fps にそろえません(元の動画のまま使います)"}
    info = _vnorm.probe(src)
    if info is None:
        return {"src": src, "dst": None, "reuse": False, "why": [],
                "note": "動画を調べられなかったため、30fps にそろえませんでした(ffprobe が見つからないか、読めないファイルです)"}
    if not info.get("has_video"):
        return None
    need, why = _vnorm.needs_normalize(info)
    if not need:
        return None
    base = norm_name(src)
    for p in [base] + [base[:-4] + "_%d.mp4" % i for i in range(2, 10)]:
        # 同じ名前があって使えるならそれを使う。使えない(別の動画・30fps でない)なら上書きせずに次の名前へ
        if os.path.normcase(p) == os.path.normcase(src):
            continue
        if not os.path.exists(p):
            return {"src": src, "dst": p, "reuse": False, "why": why}
        if os.path.isfile(p) and norm_usable(p, info):
            return {"src": src, "dst": p, "reuse": True, "why": why}
    return {"src": src, "dst": None, "reuse": False, "why": why,
            "note": "隣に 30fps の動画を作る名前が空いていないため、元の動画のまま使います(%s)" % os.path.basename(base)}


def _norm_room(src, dst):
    """隣に書けるか・空きが足りるか。-> None(書ける)か 書けない理由"""
    d = os.path.dirname(dst)
    try:
        os.makedirs(d, exist_ok=True)
        fd, test_path = tempfile.mkstemp(prefix=".ytt-write-test-", dir=d)
        os.close(fd)
        os.unlink(test_path)
    except OSError:
        return "動画のフォルダに書き込めないため(読み取り専用など)、30fps にそろえられませんでした。文書は元の動画のままです"
    try:
        need = os.path.getsize(src) + NORM_MIN_FREE
        free = shutil.disk_usage(d).free
    except OSError:
        return None
    if free < need:
        return "ディスクの空きが足りないため(%.1f GB 必要)、30fps にそろえられませんでした。文書は元の動画のままです" % (need / 1024 ** 3)
    return None


def norm_swap(tid, src, dst):
    """作り直した写しへ文書を付け替える(文書の動画が src のままのときだけ)。-> None(付け替えた)か 付け替えなかった理由"""
    with _store._save_lock:
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


def norm_run(job, tid, plan):
    """作り直して付け替える(ジョブの中で。SLOTS はジョブが持っている)。-> (付け替えたか, 知らせの文)。
    job の state・phase・progress を「30fps にそろえています… n%」にする"""
    src, dst = plan["src"], plan.get("dst")
    if plan.get("note") or not dst:
        return False, plan.get("note") or ""
    if not plan.get("reuse"):
        room = _norm_room(src, dst)
        if room:
            return False, room
        job["state"], job["phase"], job["progress"], job["device"] = "running", NORM_PHASE, 0.0, ""
        try:
            _vnorm.normalize(src, dst, cancelled=lambda: bool(job.get("cancel")),
                            on_progress=lambda p: job.__setitem__("progress", round(float(p), 3)))
        except _vnorm.Cancelled:
            return False, "30fps にそろえるのを取り消しました。文書は元の動画のままです"
        except (_vnorm.NormalizeError, OSError) as e:
            _txbase.log.warning("30fps の作り直しに失敗: %s %s", tid, e)
            return False, "30fps にそろえられませんでした(%s)。文書は元の動画のままです" % str(e)[:200]
    why = norm_swap(tid, src, dst)
    if why:
        return False, why
    if plan.get("reuse"):
        return True, "30fps の動画 %s があったので、それに付け替えました" % os.path.basename(dst)
    return True, "30fps にそろえた動画 %s を作って付け替えました(元の動画はそのまま残っています)" % os.path.basename(dst)


def norm_after_transcribe(job, spec, tid):
    """文字起こしのジョブの続き(human/proof/doc_jobs.run_job が文書を書いたあとで、serve が登録した口 norm_after から呼ぶ)。評価用は作り直さない。
    知らせは job["normNote"](付け替えなかったときは job["warnings"] にも)"""
    if spec.get("evalSet") or _settings.in_eval_dir(spec.get("sourcePath")):
        return
    try:
        plan = norm_plan(spec.get("sourcePath"))
    except Exception as e:   # 調べる所の想定外でも、文字起こしの結果は残す
        _txbase.log.warning("30fps の確認に失敗: %s %s", tid, e)
        return
    if not plan:
        return
    job["tid"] = tid   # 作り直しの間は、この文書の付け替えを止める(_doc_busy)
    try:
        ok, note = norm_run(job, tid, plan)
    except Exception as e:
        _txbase.log.exception("30fps の作り直しで例外")
        ok, note = False, "30fps にそろえられませんでした(内部エラー: %s)。文書は元の動画のままです" % e.__class__.__name__
    _norm_note(job, ok, note)


def _norm_note(job, ok, note):
    if not note:
        return
    job["normNote"], job["normOk"] = note, bool(ok)
    if not ok:
        _txbase.add_warning(job, note)


def norm_start(tid, path, doc):
    """動画を選び直したあと: 30fps でなければ裏のジョブで作り直して付け替える。
    -> (始めたジョブの id か None, 知らせ(作らない理由。無ければ ""))。評価用・30fps なら (None, "")"""
    if doc.get("evalSet") is True or _settings.in_eval_dir(path):
        return None, ""
    plan = norm_plan(path)
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


def run_normalize(job):
    """ジョブ kind "normalize"(選び直しのあとの作り直し。SLOTS は work_one が持っている)"""
    spec = job["spec"]
    try:
        ok, note = norm_run(job, spec["tid"], spec["plan"])
        _norm_note(job, ok, note)
        job["progress"], job["state"], job["phase"] = 1.0, "done", "完了" if ok else "元の動画のまま"
    except Exception as e:
        _heavy.set_internal_error(job, e)

# ---------- まとめて付け替える・「参照…」(2026-10-01。ユーザー決定: 参照の窓 + 履歴からまとめて) ----------
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
