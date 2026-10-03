# -*- coding: utf-8 -*-
"""「編集」のサーバーの部品: 動画を選び直す(付け替え)・まとめて付け替える・評価用のフォルダ(段10 で editor/serve.py から分けた。docs/plan/phase10-code-split.md)。

名前は serve.py からも見える(serve.py が受け付けて、この部品へ転送する。テストの S.名前 = … もここに入る)。
ほかの部品の名前は `ed_xxx.名前` の形で呼ぶたびに読む(差し替えが効くように。from … import はしない)。
"""
import array
import bisect
import difflib
import faulthandler
import gc
import hashlib
import itertools
import json
import logging
import logging.handlers
import math
import os
import queue
import re
import shutil
import socket
import subprocess
import sys
import tarfile
import threading
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
import uuid
import wave

from ytt_core import datadir as _datadir, fsio as _fsio, httpsec, layout as _layout, jobs as _heavy, runtime as _runtime, schemas as _yschemas, tools as _tools  # noqa: E402,F401
import roster as _roster  # noqa: E402,F401
import ed_jobs  # noqa: E402,F401
import ed_learn  # noqa: E402,F401
import ed_state  # noqa: E402,F401
import ed_store  # noqa: E402,F401
# ---------- 動画を選び直す(付け替え。全体の計画の段2 B-4・監査 19。docs/plan/phase2-data-safety.md の 1) ----------
# 動画を移した・改名した文書の sourcePath を、行・校正・話者・カットを残したまま新しいパスに直す。
# 選べる場所は「このパソコンのドライブならどこでも」(ユーザー決定 2026-09-29)。ネットワーク上・ツールの作業データの中・リンクの先がそれらになるものは断る。
# URL の引数では付け替えない(POST + 合言葉 + Origin 検査だけ)。候補の自動の推測はしない
RELINK_KEEP = 10          # 文書に残す付け替えの記録(relinks)の数
RELINK_TOL_SEC = 1.0      # 動画全体の文書: 長さの差がこれ(か 0.5%)以下なら同じ動画とみなす
RELINK_TOL_RATIO = 0.005
RELINK_RANGE_TOL = 0.5    # 範囲の文書: 新しい動画の長さ ≥ 範囲の終わり − これ


def _remote_drive(p):
    """Windows のネットワークドライブ(net use で割り当てた Z: など)か。ドライブの種類を聞くだけで、ファイルには触らない"""
    if os.name != "nt":
        return False
    drive = os.path.splitdrive(p)[0]
    if len(drive) != 2 or drive[1] != ":":
        return False
    try:
        import ctypes
        return ctypes.windll.kernel32.GetDriveTypeW(drive + "\\") == 4   # DRIVE_REMOTE
    except (AttributeError, OSError, ValueError):
        return False


def _inside(p, folder):
    try:
        a, b = os.path.normcase(os.path.realpath(p)), os.path.normcase(os.path.realpath(folder))
    except (OSError, ValueError):
        return False
    return a == b or a.startswith(b.rstrip("\\/") + os.sep)


def relink_path(raw):
    """付け替え先のパスの検査。ネットワーク上のパスは、ファイルに触る前に断る(存在を確かめるだけで資格情報を送るため)。
    ジャンクション・リンクを解いた先でも、もう一度 ネットワーク・「:」(NTFS の代替ストリーム)・拡張子・作業データの中 を確かめる。-> 実体のパス"""
    s = str(raw or "").strip().strip('"').strip()
    if not s or len(s) > 1000 or any(ch in s for ch in "\x00\r\n"):
        raise ed_state.ApiError("bad_path", "パスを入れてください", 400)
    if _fsio.is_network_path(s):
        raise ed_state.ApiError("network_path", "ネットワーク上のファイルは選べません(このパソコンにコピーしてから選んでください)", 400)
    if not os.path.isabs(s):
        raise ed_state.ApiError("bad_path", "ドライブから始まるパス(例: D:\\動画\\配信.mp4)を入れてください", 400)
    p = os.path.abspath(s)
    for resolved in (False, True):
        if resolved:   # 1回目の検査を通ってから(ネットワーク上のパスには触らない)リンクを解く
            try:
                p = os.path.realpath(p)
            except (OSError, ValueError):
                raise ed_state.ApiError("no_file", "ファイルが見つかりません(パスを確認してください)", 400)
        if _fsio.is_network_path(p) or _remote_drive(p):
            raise ed_state.ApiError("network_path", "ネットワーク上のファイルは選べません(このパソコンにコピーしてから選んでください)", 400)
        if ":" in os.path.splitdrive(p)[1]:
            raise ed_state.ApiError("bad_path", "パスに「:」が入っています(ファイルそのもののパスを入れてください)", 400)
        if os.path.splitext(p)[1].lower() not in ed_state.MEDIA_TYPES:
            raise ed_state.ApiError("bad_ext", "動画・音声ファイルではないようです(対応: %s)" % " ".join(sorted(ed_state.MEDIA_TYPES)), 400)
        if _inside(p, ed_state.DATA_DIR):   # このツールの作業データ(文書・設定・保管)。スタジオの既定の書き出し先(作業データの studio\exports)は選べる
            raise ed_state.ApiError("bad_path", "このツールの作業データの中のファイルは選べません", 400)
    if not os.path.isfile(p):
        raise ed_state.ApiError("no_file", "ファイルが見つかりません(パスを確認してください)", 400)
    return p


def _relink_ref(doc):
    """比べる長さ。-> (長さ秒 または None, 動画全体の文書か)。動画全体の文書は記録した長さ、範囲の文書は範囲の終わり(無ければ最後の行の終わり)"""
    dur, end = ed_state.num(doc.get("duration")), ed_state.num(doc.get("end"))
    if doc.get("whole") is not False and dur and dur > 0:
        return dur, True
    if end and end > 0:
        return end, False
    ends = [ed_state.num(s.get("end"), 0.0) or 0.0 for s in doc.get("segments") or [] if isinstance(s, dict)]
    return (max(ends), False) if ends and max(ends) > 0 else (None, False)


def relink_check(obj):
    """POST /api/relink/check {"id", "path"}: 付け替える前の確認(書き込まない)。
    -> {path, name, durationSec, fps, hasVideo, docDuration, diffSec, mismatch, sameAsNow, usedBy: [{id, title}], rowsAfterEnd, warnings}。
    fps・長さはカットのタブと同じ測り方(resolve_export.edit_draft。音声だけのファイルは ffmpeg の長さ)"""
    import resolve_export
    tid = str(obj.get("id") or "")
    doc = ed_store.read_transcript(tid)
    p = relink_path(obj.get("path"))
    eval_name_guard(p, doc.get("evalSet") is True, "付け替えてください")   # 評価用のフォルダの設定が消えているときは、評価用のフォルダへの付け替えを止める
    dur, has_v, has_a = ed_store.probe_media(p)
    if not (has_v or has_a):
        raise ed_state.ApiError("bad_media", "動画・音声として読めませんでした(壊れているか、対応していない形式です)", 400)
    fps, warnings = None, []
    if has_v:
        try:
            dr = resolve_export.edit_draft(dict(doc, sourcePath=p), ed_state.SERVER_VERSION, rows=False)
            fps, dur = dr["fps"], dr["durationSec"]
        except resolve_export.ResolveExportError as e:
            warnings.append("fps を調べられませんでした(%s)。カットのタブで使えない可能性があります" % str(e)[:200])
    else:
        warnings.append("映像の無いファイル(音声だけ)です。文字の直しはできますが、カットとパックには使えません")
    if not dur or dur <= 0:
        raise ed_state.ApiError("bad_media", "動画の長さを読めませんでした(壊れているか、対応していない形式です)", 400)
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
        warnings.append("長さが元の動画と違います(元 %s・選んだ動画 %s)。別の動画の可能性があります" % (ed_state.fmt_hms(ref), ed_state.fmt_hms(dur)))
    after = sum(1 for s in doc.get("segments") or [] if isinstance(s, dict) and (ed_state.num(s.get("start"), 0.0) or 0.0) >= dur)
    if after:
        warnings.append("選んだ動画の終わりより後ろに %d 行あります(その行は再生できません)" % after)
    key = os.path.normcase(p)
    used = []
    for other in ed_store._tids():
        if other == tid:
            continue
        sm = ed_store.transcript_summary(other)
        if sm and sm["_sourcePath"] and not _fsio.is_network_path(sm["_sourcePath"]) \
                and os.path.normcase(os.path.abspath(sm["_sourcePath"])) == key:
            used.append({"id": other, "title": str(sm.get("title") or "")[:120]})
            if len(used) >= 10:
                break
    cur = str(doc.get("sourcePath") or "")
    same = bool(cur) and not _fsio.is_network_path(cur) and os.path.normcase(os.path.abspath(cur)) == key
    return {"path": p, "name": os.path.basename(p), "durationSec": round(dur, 3), "fps": fps, "hasVideo": bool(has_v),
            "docDuration": round(ref, 3) if ref else None, "diffSec": diff, "mismatch": mismatch, "sameAsNow": same,
            "usedBy": used, "rowsAfterEnd": after, "warnings": warnings}


def _doc_busy(tid):
    """その文書を読み書きするジョブ(話者判別・再認識・声を覚える・比較・この文書に入れる文字起こし)が動いているか"""
    with ed_jobs._jobs_lock:
        return any(j["state"] in ed_jobs.ACTIVE_STATES and (j.get("tid") == tid or (j.get("spec") or {}).get("tid") == tid
                                                    or (j.get("spec") or {}).get("intoDoc") == tid) for j in ed_jobs._jobs.values())


def relink_doc(obj):
    """POST /api/relink {"id", "path", "baseUpdatedAt", "acceptDiff"}: 文書の動画を付け替える。
    書き換えるのは sourcePath・sourceName・updatedAt と記録 relinks だけ(行・校正・話者・original・clip・start/end・カットは変えない。
    カットは秒で持っているので、fps が違っても読み込むときに合わせ直る)。書く前に .bak/<id>.pre-relink.json・履歴・.bak/<id>.edit.pre-relink.json を残す。
    409: 先に更新された(conflict)・ジョブの最中(busy)・長さが違うのに acceptDiff が無い(duration_mismatch)"""
    tid = str(obj.get("id") or "")
    base = obj.get("baseUpdatedAt")
    if isinstance(base, bool) or not isinstance(base, int):
        raise ed_state.ApiError("bad_request", "baseUpdatedAt(読み込んだときの更新日時)を付けてください", 400)
    chk = relink_check(obj)   # 動画を調べるのは時間がかかるので、ロックの外で
    if chk["sameAsNow"]:
        raise ed_state.ApiError("same_path", "今と同じ動画です(付け替える必要はありません)", 400)
    with ed_store._save_lock:
        doc = ed_store.read_transcript(tid)
        if doc.get("updatedAt") and base != doc.get("updatedAt"):
            raise ed_state.ApiError("conflict", "別の場所で先に更新されています。読み込み直してから、もう一度選んでください", 409)
        if _doc_busy(tid):
            raise ed_state.ApiError("busy", "この文書は、いま別の処理(文字起こし・話者判別・再認識など)の最中です。終わってから付け替えてください", 409)
        if chk["mismatch"] and obj.get("acceptDiff") is not True:
            raise ed_state.ApiError("duration_mismatch", "長さが元の動画と違います。別の動画でないか確かめてから付け替えてください", 409, {"check": chk})
        now = _relink_write(tid, doc, chk["path"], chk["diffSec"])
    ed_state.log.info("動画を付け替え: %s → %s", tid, chk["name"])
    return {"ok": True, "updatedAt": now, "sourcePath": chk["path"], "sourceName": chk["name"], "warnings": chk["warnings"]}


def _relink_write(tid, doc, path, diff, why=None):
    """付け替えの書き込み(_save_lock の中で呼ぶ)。控え .bak/<id>.pre-relink.json・履歴を残し、sourcePath・sourceName・updatedAt・relinks を直す。
    評価用のフォルダの中へ付け替えたら評価用の印も付ける(ユーザー決定 2026-10-01: フォルダの中は外せない)。-> 新しい updatedAt"""
    bak = os.path.join(ed_state.TX_DIR, ".bak")
    os.makedirs(bak, exist_ok=True)
    shutil.copy2(ed_store.tx_path(tid), os.path.join(bak, tid + ".pre-relink.json"))   # 直前の状態を1世代だけ(話者判別の pre-diarize と同じ)
    if os.path.isfile(ed_store.edit_path(tid)):
        shutil.copy2(ed_store.edit_path(tid), os.path.join(bak, tid + ".edit.pre-relink.json"))
    try:
        ed_store.hist_snapshot(tid, force=True)   # 「以前の版に戻す」で元のパスへ戻せる
    except OSError:
        pass
    now = max(int(time.time() * 1000), int(doc.get("updatedAt") or 0) + 1)
    prev = [r for r in doc.get("relinks") or [] if isinstance(r, dict)]
    rec = {"from": str(doc.get("sourcePath") or ""), "at": now, "diffSec": diff}
    if why:
        rec["why"] = why
    doc["relinks"] = (prev + [rec])[-RELINK_KEEP:]
    doc.update({"sourcePath": path, "sourceName": os.path.basename(path), "updatedAt": now})
    if in_eval_dir(path):
        doc["evalSet"] = True
    ed_store.apply_edit_cuts(tid, doc)
    ed_state.atomic_write(ed_store.tx_path(tid), json.dumps(doc, ensure_ascii=False, indent=1).encode("utf-8"))
    return now


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
    for tid in ed_store._tids():
        sm = ed_store.transcript_summary(tid)
        sp = str((sm or {}).get("_sourcePath") or "")
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
        raise ed_state.ApiError("bad_path", "フォルダのパスを入れてください", 400)
    net = ed_state.ApiError("network_path", "ネットワーク上のフォルダは選べません", 400)
    if _fsio.is_network_path(s):
        raise net
    if not os.path.isabs(s):
        raise ed_state.ApiError("bad_path", "ドライブから始まるパス(例: D:\\動画)を入れてください", 400)
    p = os.path.abspath(s)
    if _remote_drive(p):
        raise net
    try:
        p = os.path.realpath(p)
    except (OSError, ValueError):
        raise ed_state.ApiError("no_dir", "フォルダが見つかりません", 400)
    if _fsio.is_network_path(p) or _remote_drive(p):
        raise net
    if ":" in os.path.splitdrive(p)[1]:
        raise ed_state.ApiError("bad_path", "パスに「:」が入っています", 400)
    if not os.path.isdir(p):
        raise ed_state.ApiError("no_dir", "フォルダが見つかりません(パスを確認してください)", 400)
    if _inside(p, ed_state.DATA_DIR):
        raise ed_state.ApiError("bad_path", "このツールの作業データの中は探せません", 400)
    return p


def relink_find(obj):
    """POST /api/relink/find {"folder", "ids"}: 選んだフォルダ(とその下)から、各文書の元の動画と同じファイル名(大文字小文字は区別しない)の動画を探す。
    -> {folder, candidates: {id: [path, …]}, scanned, truncated}。時間・数・深さに上限があり、超えたら truncated"""
    root = relink_folder(obj.get("folder"))
    want = {}
    for tid in [str(x) for x in (obj.get("ids") or [])][:500]:
        if not ed_state.TID_RE.match(tid):
            continue
        sm = ed_store.transcript_summary(tid)
        name = re.split(r"[\\/]", str((sm or {}).get("_sourcePath") or ""))[-1] or str((sm or {}).get("sourceName") or "")
        if name and os.path.splitext(name)[1].lower() in ed_state.MEDIA_TYPES:
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
                               and not _inside(os.path.join(cur, d), ed_state.DATA_DIR))
    cands = {tid: found[k] for k, tids in want.items() for tid in tids if found[k]}
    return {"folder": root, "candidates": cands, "scanned": seen, "truncated": truncated}


def pick_path(obj):
    """POST /api/pick {"kind": "file"|"dir", "hint"}: PC の標準の窓で動画かフォルダを選ぶ(ytt_core/pick.py)。
    -> {path}(やめたら "")。選んだ動画の検査は、そのあとの /api/relink/check と /api/relink/find が行う"""
    from ytt_core import pick as _pick
    kind = "dir" if obj.get("kind") == "dir" else "file"
    try:
        p = _pick.pick(kind, "動画のあるフォルダを選ぶ" if kind == "dir" else "動画を選ぶ", obj.get("hint") or "", ed_state.MEDIA_TYPES)
    except _pick.PickBusy as e:
        raise ed_state.ApiError("pick_busy", str(e), 409)
    except _pick.PickError as e:
        raise ed_state.ApiError("pick_unavailable", "%s。パスを貼り付けてください" % e, 400)
    return {"path": p}


# ---------- 評価用のフォルダ(2026-10-01 ユーザー決定。docs/design/eval-folder.md) ----------
# 設定 evalDirs のフォルダ(の下)にある動画は、精度を測るためだけのデータ。文字起こしを始めたとき・保存・付け替え・履歴から戻したときに
# 評価用の印(evalSet)を付け、画面からは外せない。「整理」は動画の名前を「フォルダ名_番号_状態」にそろえ、文書を付け替える
# (入口の起動時に1回 + 画面のボタン)。状態 = 済(文字のある行がすべて校正済み)・未・未文字起こし
EVAL_DIRS_MAX = 10
EVAL_STATES = ("済", "未", "未文字起こし")
EVAL_WALK_DEPTH = 4         # 評価用のフォルダから下へ何段まで(評価用データ\1_JP\01_0期生\評価用データ01_ときのそら = 3段)
EVAL_WALK_MAX = 20000       # 見るファイルとフォルダの数の上限
EVAL_SIDECARS = (".clip.json", ".edit.json", ".transcript.json", ".cut-plan.json", ".srt", "_edit.mp4")   # 動画と同じ名前で持つ途中のファイル(home/cleanup.py と同じ)
# 仮置き(2026-10-01 ユーザー決定): 評価用のフォルダの直下の「評価用_仮置き」で作業し、全行に話者が付いて全行が校正済みになったら、
# 話した時間が最も長いメンバーのフォルダ(名前が「…数字_メンバー名」のフォルダ)へ「フォルダ名_番号_済」で移す。仮置きの中は名前を変えない
EVAL_STAGING = "評価用_仮置き"
_EVAL_MEMBER_RE = re.compile(r"^.*?\d+_(.+)$")
_evalorg_lock = threading.Lock()
_evalorg_last = {}


def _eval_dirs_ok(v):
    return (isinstance(v, list) and len(v) <= EVAL_DIRS_MAX
            and all(isinstance(p, str) and 3 <= len(p) <= 1000 and os.path.isabs(p) and not _fsio.is_network_path(p)
                    and not any(ch in p for ch in "\x00\r\n") and ":" not in os.path.splitdrive(p)[1] for p in v))


def eval_dirs():
    """設定の評価用のフォルダ(あるものだけ)。ネットワーク上・作業データの中は使わない"""
    v = ed_learn.load_settings().get("evalDirs")
    if not _eval_dirs_ok(v):
        return []
    out = []
    for p in v:
        p = os.path.abspath(p)
        try:
            if not _remote_drive(p) and os.path.isdir(p) and not _inside(p, ed_state.DATA_DIR) and not _inside(ed_state.DATA_DIR, p):
                out.append(p)
        except (OSError, ValueError):
            pass
    return out


def in_eval_dir(path, dirs=None):
    """動画のパスが評価用のフォルダの中か(パスを比べるだけ。ネットワーク上のパスには触らない)"""
    s = str(path or "")
    if not s or _fsio.is_network_path(s) or not os.path.isabs(s):
        return False
    return any(_inside(s, d) for d in (eval_dirs() if dirs is None else dirs))


EVAL_NAME_WORD = "評価用"


def eval_name_guard(path, is_eval=False, todo="文字起こししてください"):
    """設定 evalDirs が空(未設定・消えた)なのに、動画のパスのフォルダ名のどこかに「評価用」が入っているときは止めて案内する
    (設定が消えたまま文字起こしすると、評価用の動画が学習用の文書に混ざる。master-plan Q0)。設定があれば今までどおり(何もしない)。
    is_eval: 評価用として始める(画面のチェック・評価用の文書)なら混ざらないので通す。パスの文字を調べるだけでファイルには触らない"""
    if is_eval:
        return
    v = ed_learn.load_settings().get("evalDirs")
    if _eval_dirs_ok(v) and v:
        return
    if any(EVAL_NAME_WORD in part for part in re.split(r"[\\/]+", os.path.dirname(str(path or "")))):
        raise ed_state.ApiError("eval_dir_unset", "評価用のフォルダの中の動画のようです。⚙ の『評価用のフォルダ』を設定してから%s(設定が無いと学習用に混ざります)" % todo, 400)


def _eval_name_re(prefix):
    return re.compile(r"^%s_(\d{2,4})_(%s)$" % (re.escape(prefix), "|".join(sorted(EVAL_STATES, key=len, reverse=True))))


def _eval_state(sms):
    """文書の要約の一覧 → 状態。行のある文書が無ければ「未文字起こし」、どれもすべての行が校正済みなら「済」"""
    rows = [s for s in sms if s.get("rows")]
    if not rows:
        return "未文字起こし"
    return "済" if all(s["proofed"] >= s["rows"] for s in rows) else "未"


def _eval_videos(root, skip_staging=True):
    """評価用のフォルダの下の動画 {フォルダ: [ファイル名]}(作業用/ と _edit の動画は除く。仮置きは skip_staging で除く)"""
    out, seen = {}, 0
    for cur, dirs, files in os.walk(root):
        depth = os.path.relpath(cur, root).count(os.sep) + (0 if cur == root else 1)
        dirs[:] = [d for d in dirs if d != _yschemas.WORK_DIR and not d.startswith(".") and depth < EVAL_WALK_DEPTH
                   and not (skip_staging and cur == root and d == EVAL_STAGING)]
        seen += len(dirs) + len(files)
        if seen > EVAL_WALK_MAX:
            break
        vids = [f for f in files if os.path.splitext(f)[1].lower() in ed_state.MEDIA_TYPES and not os.path.splitext(f)[0].endswith("_edit")]
        if vids:
            out[cur] = vids
    return out


def _path_busy(path):
    key = os.path.normcase(path)
    with ed_jobs._jobs_lock:
        return any(j["state"] in ed_jobs.ACTIVE_STATES and os.path.normcase(str((j.get("spec") or {}).get("sourcePath") or "")) == key for j in ed_jobs._jobs.values())


def _same_drive(a, b):
    return os.path.splitdrive(os.path.abspath(a))[0].lower() == os.path.splitdrive(os.path.abspath(b))[0].lower()


def _move(a, b):
    """ファイルを移す。同じドライブなら名前を変えるだけ。別のドライブ(C: → E: など。評価用のフォルダへ取り込むとき)は
    コピー(.part)→ 大きさを確かめる → 名前を付ける → 元を消す。元を消せなければ(開いているなど)コピーを消して OSError(元のまま)"""
    try:
        os.rename(a, b)
        return
    except OSError as e:
        if _same_drive(a, b) or os.path.exists(b):
            raise
        first = e
    part = b + ".part"
    try:
        shutil.copy2(a, part)
        if os.path.getsize(part) != os.path.getsize(a):
            raise OSError("コピーの大きさが合いません: %s" % os.path.basename(a))
        os.rename(part, b)
        try:
            os.remove(a)
        except OSError:
            os.remove(b)
            raise
    except BaseException:
        if os.path.exists(part):
            try:
                os.remove(part)
            except OSError:
                pass
        raise
    ed_state.log.info("別のドライブへ移した: %s → %s(最初の名前の変更: %s)", a, b, first)


def _rename_sidecars(old, new):
    """動画の途中のファイル(作業用/ と、以前の置き方の動画の隣)も動画に合わせて名前を変える・移す(仮置きから移すときは別のフォルダへ)。
    中身は書き換えない。-> [(古い, 新しい)]"""
    done = []
    ostem, nstem = os.path.splitext(os.path.basename(old))[0], os.path.splitext(os.path.basename(new))[0]
    for src, dst in ((_yschemas.work_dir(old), _yschemas.work_dir(new)), (os.path.dirname(old), os.path.dirname(new))):
        for suf in EVAL_SIDECARS:
            a, b = os.path.join(src, ostem + suf), os.path.join(dst, nstem + suf)
            if os.path.isfile(a) and not os.path.exists(b):
                os.makedirs(dst, exist_ok=True)
                _move(a, b)
                done.append((a, b))
    return done


def _norm_member(name):
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", str(name or ""))).lower()


def _eval_members(root):
    """評価用のフォルダの下のメンバーのフォルダ {正規化した名前: フォルダ}(「…数字_名前」の形。仮置き・作業用は除く)"""
    out, seen = {}, 0
    for cur, dirs, _files in os.walk(root):
        depth = os.path.relpath(cur, root).count(os.sep) + (0 if cur == root else 1)
        dirs[:] = [d for d in dirs if d != _yschemas.WORK_DIR and not d.startswith(".") and depth < EVAL_WALK_DEPTH
                   and not (cur == root and d == EVAL_STAGING)]
        seen += len(dirs)
        if seen > EVAL_WALK_MAX:
            break
        for d in dirs:
            m = _EVAL_MEMBER_RE.match(d)
            if m:
                out.setdefault(_norm_member(m.group(1)), os.path.join(cur, d))
    return out


def _eval_ready(doc):
    """仮置きから移せるか。-> (話者の名前ごとの秒 [(名前, 秒)] 長い順, 理由 または None)。
    条件 = 文字のある行が1つ以上・すべて校正済み・すべて話者付き(仮の名前でもよい。ユーザー決定)"""
    names = {s.get("id"): str(s.get("name") or "") for s in doc.get("speakers") or [] if isinstance(s, dict)}
    rows = [g for g in doc.get("segments") or [] if isinstance(g, dict) and str(g.get("text") or "").strip()]
    if not rows:
        return [], "まだ文字起こしされていません"
    if not all(g.get("proofed") is True for g in rows):
        return [], "校正していない行があります"
    if not all(g.get("speaker") in names for g in rows):
        return [], "話者が付いていない行があります"
    secs = {}
    for g in rows:
        nm = names[g["speaker"]]
        secs[nm] = secs.get(nm, 0.0) + max(0.0, (ed_state.num(g.get("end"), 0.0) or 0.0) - (ed_state.num(g.get("start"), 0.0) or 0.0))
    return sorted(secs.items(), key=lambda kv: -kv[1]), None


def _eval_next_name(folder, ext, state):
    """メンバーのフォルダで次に空いている番号の名前「フォルダ名_番号_状態.拡張子」"""
    prefix = os.path.basename(folder)
    rx = _eval_name_re(prefix)
    used = set()
    for f in os.listdir(folder) if os.path.isdir(folder) else []:
        m = rx.match(os.path.splitext(f)[0])
        if m:
            used.add(int(m.group(1)))
    n = 1
    while n in used:
        n += 1
    return os.path.join(folder, "%s_%02d_%s%s" % (prefix, n, state, ext))


def _eval_settle_one(path, tids, members):
    """仮置きの動画1本を、条件を満たせばメンバーのフォルダへ移す。-> ({from, to, docs, member} または None, 理由 または None)"""
    if not tids:
        return None, "まだ文字起こしされていません"
    if _path_busy(path) or any(_doc_busy(t) for t in tids):
        return None, "文字起こしなどの処理の最中です"
    best = None
    for tid in tids:
        secs, why = _eval_ready(ed_store.read_transcript(tid))
        if why:
            return None, why
        for nm, sec in secs:   # 長い順。メンバーのフォルダと同じ名前の最初の人
            if _norm_member(nm) in members:
                if best is None or sec > best[1]:
                    best = (nm, sec)
                break
    if best is None:
        return None, "移す先が決まりません(メンバーのフォルダと同じ名前の話者がいません)"
    new = _eval_next_name(members[_norm_member(best[0])], os.path.splitext(path)[1], "済")
    rec = _eval_rename(path, new, tids, "evalSettle")
    rec["member"] = best[0]
    return rec, None


def _eval_copy_index(dirs):
    """仮置きのコピーの付け替え先の候補: 評価用のフォルダの外の動画を指す、行のある文書 {正規化したファイル名: [要約]}(2026-10-02 ユーザー決定)"""
    idx = {}
    for tid in ed_store._tids():
        sm = ed_store.transcript_summary(tid)
        sp = str((sm or {}).get("_sourcePath") or "")
        if not sp or not sm.get("rows") or _fsio.is_network_path(sp) or not os.path.isabs(sp) or in_eval_dir(sp, dirs):
            continue
        idx.setdefault(os.path.normcase(os.path.basename(sp)), []).append(sm)
    return idx


def _eval_adopt_copy(path, copies):
    """仮置きの動画(文書の無いコピー)に、同じ名前で同じ大きさの元の動画を指す文書がちょうど1つあれば、その文書をこの動画へ付け替える。
    元の動画が無い(大きさを比べられない)・候補が2つ以上・処理中なら付け替えない。-> (付け替えた文書の id または None, 理由 または None)"""
    size = os.path.getsize(path)
    hits = []
    for sm in copies.get(os.path.normcase(os.path.basename(path)), []):
        try:
            if os.path.getsize(sm["_sourcePath"]) == size:
                hits.append(sm)
        except OSError:
            continue   # 元の動画が無い・読めない: 中身が同じか分からないので候補にしない
    if not hits:
        return None, None
    if len(hits) > 1:
        return None, "同じ名前・同じ大きさの動画を指す文書が %d つあり、どれを付け替えるか決められません(「動画を選び直す」で選んでください)" % len(hits)
    tid = hits[0]["id"]
    if _doc_busy(tid):
        return None, "文書が処理の最中です"
    with ed_store._save_lock:
        doc = ed_store.read_transcript(tid)
        if os.path.normcase(os.path.abspath(str(doc.get("sourcePath") or ""))) != os.path.normcase(os.path.abspath(hits[0]["_sourcePath"])):
            return None, None   # 調べている間に付け替えられた
        _relink_write(tid, doc, path, 0.0, "evalStagingCopy")
    ed_state.log.info("評価用の仮置き: コピー %s に文書 %s を付け替えた(元 %s)", os.path.basename(path), tid, hits[0]["_sourcePath"])
    return tid, None


def _eval_staging_pass(dirs, by_path, res):
    """仮置きの動画のうち、移せるものを移す(eval_organize と eval_settle から。_evalorg_lock の中で呼ぶ)"""
    for root in dirs:
        stg = os.path.join(root, EVAL_STAGING)
        if not os.path.isdir(stg):
            continue
        members, copies = None, None
        for folder, files in sorted(_eval_videos(stg, False).items()):
            for f in sorted(files):
                old = os.path.join(folder, f)
                key = os.path.normcase(old)
                if key not in by_path and res.get("_only"):
                    continue
                sms = by_path.get(key, [])
                if not sms and not res.get("_only"):   # 文書の無いコピー: 同じ名前・同じ大きさの動画を指す文書が1つだけなら、それをこのコピーへ付け替える
                    if copies is None:
                        copies = _eval_copy_index(dirs)
                    try:
                        tid, why = _eval_adopt_copy(old, copies)
                    except (OSError, ed_state.ApiError) as e:
                        tid, why = None, "文書を付け替えられませんでした: %s" % (getattr(e, "message", None) or e)
                    if tid:
                        res.setdefault("adopted", []).append({"path": old, "id": tid})
                        sm = ed_store.transcript_summary(tid)
                        sms = [sm] if sm else []
                    elif why:
                        res["staged"].append({"path": old, "reason": why})
                        continue
                res["marked"] += _eval_mark_docs([x["id"] for x in sms if not x.get("evalSet")])
                if members is None:
                    members = _eval_members(root)
                try:
                    rec, why = _eval_settle_one(old, [x["id"] for x in sms if x.get("rows")], members)
                except (OSError, ed_state.ApiError) as e:
                    rec, why = None, "移せませんでした(動画を開いているかもしれません): %s" % (getattr(e, "message", None) or e)
                if rec:
                    res["moved"].append(rec)
                else:
                    res["staged"].append({"path": old, "reason": why})


def _eval_outside_docs(dirs, only=None):
    """評価用の印があるのに、動画が評価用のフォルダの外にある文書 {動画のパス(正規化): (動画のパス, [要約])}。
    同じ動画を使う文書は印の無いものも入れる(断るかを決めるため)。only: この文書の動画だけ"""
    by_path, marked = {}, set()
    for tid in ed_store._tids():
        sm = ed_store.transcript_summary(tid)
        sp = str((sm or {}).get("_sourcePath") or "")
        if not sp or _fsio.is_network_path(sp) or not os.path.isabs(sp) or in_eval_dir(sp, dirs) or _inside(sp, ed_state.DATA_DIR):
            continue
        key = os.path.normcase(os.path.abspath(sp))
        by_path.setdefault(key, (sp, []))[1].append(sm)
        if sm.get("evalSet") and (only is None or sm["id"] == only):
            marked.add(key)
    return {k: v for k, v in by_path.items() if k in marked}


def _eval_free_name(folder, name):
    """folder の中で使われていない名前(同じ名前があれば「名前 (2).拡張子」…)"""
    stem, ext = os.path.splitext(name)
    p, n = os.path.join(folder, name), 2
    while os.path.exists(p):
        p, n = os.path.join(folder, "%s (%d)%s" % (stem, n, ext)), n + 1
    return p


def _eval_intake_one(path, sms, root):
    """評価用にした文書の動画1本を、評価用のフォルダへ取り込む(2026-10-04 ユーザー決定)。すべての行が校正済み・話者付きで
    メンバーのフォルダが決まれば そのフォルダの「フォルダ名_番号_済」、それ以外は仮置き(名前はそのまま。そろったら仮置きから移る)。
    -> ({from, to, docs, member, staged} または None, 理由 または None)"""
    if not os.path.isfile(path):
        return None, "動画が見つかりません"
    if any(not s.get("evalSet") for s in sms):
        return None, "評価用でない文書もこの動画を使っています(その文書にも「評価用」の印を付けるか、動画を選び直してください)"
    tids = [s["id"] for s in sms]
    if _path_busy(path) or any(_doc_busy(t) for t in tids):
        return None, "文字起こしなどの処理の最中です"
    members, best, why = _eval_members(root), None, None
    rowed = [s["id"] for s in sms if s.get("rows")]
    if not rowed:
        why = "まだ文字起こしされていません"
    for tid in rowed:
        secs, why = _eval_ready(ed_store.read_transcript(tid))
        if why:
            break
        for nm, sec in secs:   # 長い順。メンバーのフォルダと同じ名前の最初の人
            if _norm_member(nm) in members:
                if best is None or sec > best[1]:
                    best = (nm, sec)
                break
    if not why and best is None:
        why = "メンバーのフォルダと同じ名前の話者がいません"
    if why:
        stg = os.path.join(root, EVAL_STAGING)
        os.makedirs(stg, exist_ok=True)
        new = _eval_free_name(stg, os.path.basename(path))
    else:
        new = _eval_next_name(members[_norm_member(best[0])], os.path.splitext(path)[1], "済")
    rec = _eval_rename(path, new, tids, "evalIntake")
    rec["member"] = None if why else best[0]
    rec["staged"] = why   # 仮置きへ置いた理由(メンバーのフォルダへ移したときは None)
    return rec, None


def _eval_intake_pass(dirs, res, only=None):
    """評価用の印がある文書の動画が評価用のフォルダの外にあれば、最初の評価用のフォルダへ取り込む(_evalorg_lock の中で呼ぶ)"""
    for _key, (path, sms) in sorted(_eval_outside_docs(dirs, only).items()):
        try:
            rec, why = _eval_intake_one(path, sms, dirs[0])
        except (OSError, ed_state.ApiError) as e:
            rec, why = None, "移せませんでした(動画を開いているかもしれません): %s" % (getattr(e, "message", None) or e)
        if rec:
            res.setdefault("intaken", []).append(rec)
        else:
            res["skipped"].append({"path": path, "reason": "評価用のフォルダへ移せませんでした: " + why})


def eval_organize(trigger="button"):
    """POST /api/eval-folders/organize: 評価用のフォルダの動画の名前をそろえて、文書を付け替える。
    番号は動画のフォルダの中で、すでに付いた番号はそのまま・無いものは古い順に空いている番号。
    動画を使うジョブが動いている・文書が処理中・同じ名前のファイルがある・名前を変えられない(開いている)ものは飛ばす。
    -> {at, trigger, dirs, videos, renamed: [{from, to, docs}], marked, skipped: [{path, reason}]}"""
    if not _evalorg_lock.acquire(blocking=False):
        raise ed_state.ApiError("busy", "評価用のフォルダの整理は、いま動いています", 409)
    try:
        dirs = eval_dirs()
        res = {"at": int(time.time() * 1000), "trigger": trigger, "dirs": len(dirs), "videos": 0, "renamed": [], "marked": 0, "skipped": [],
               "moved": [], "staged": [], "intaken": []}
        if not dirs:
            return res
        _eval_intake_pass(dirs, res)   # 評価用にした文書の動画を外から取り込む(仮置きか、そろっていればメンバーのフォルダへ)
        _eval_staging_pass(dirs, _eval_docs_by_path(dirs), res)
        by_path = _eval_docs_by_path(dirs)   # 仮置きから移した分を入れて数え直す
        for root in dirs:
            for folder, files in sorted(_eval_videos(root).items()):
                prefix = os.path.basename(folder)
                rx = _eval_name_re(prefix)
                used, todo = set(), []
                for f in files:
                    m = rx.match(os.path.splitext(f)[0])
                    if m and int(m.group(1)) not in used:
                        used.add(int(m.group(1)))
                        todo.append((f, int(m.group(1))))
                    else:
                        todo.append((f, None))

                def mtime(f):
                    try:
                        return os.path.getmtime(os.path.join(folder, f))
                    except OSError:
                        return 0
                nxt = 1
                for f, n in sorted(todo, key=lambda t: (t[1] is None, t[1] or 0, mtime(t[0]), t[0])):
                    res["videos"] += 1
                    old = os.path.join(folder, f)
                    sms = by_path.get(os.path.normcase(old), [])
                    if n is None:
                        while nxt in used:
                            nxt += 1
                        n = nxt
                        used.add(n)
                    new = os.path.join(folder, "%s_%02d_%s%s" % (prefix, n, _eval_state(sms), os.path.splitext(f)[1]))
                    try:
                        res["marked"] += _eval_mark_docs([s["id"] for s in sms if not s.get("evalSet")])
                        if new == old:
                            continue
                        if os.path.exists(new) and os.path.normcase(new) != os.path.normcase(old):
                            res["skipped"].append({"path": old, "reason": "同じ名前のファイルがあります: " + os.path.basename(new)})
                            continue
                        if _path_busy(old) or any(_doc_busy(s["id"]) for s in sms):
                            res["skipped"].append({"path": old, "reason": "文字起こしなどの処理の最中です(終わってから整理してください)"})
                            continue
                        res["renamed"].append(_eval_rename(old, new, [s["id"] for s in sms]))
                    except (OSError, ed_state.ApiError) as e:
                        res["skipped"].append({"path": old, "reason": "名前を変えられませんでした(動画を開いているかもしれません): %s" % (getattr(e, "message", None) or e)})
        ed_state.log.info("評価用のフォルダを整理(%s): 動画 %d・名前を変えた %d・外から取り込んだ %d・仮置きから移した %d・評価用にした %d・飛ばした %d",
                 trigger, res["videos"], len(res["renamed"]), len(res["intaken"]), len(res["moved"]), res["marked"], len(res["skipped"]))
        _evalorg_last.clear()
        _evalorg_last.update(res)
        return res
    finally:
        _evalorg_lock.release()


def _eval_docs_by_path(dirs):
    """評価用のフォルダの中の動画 → その動画を使う文書の要約の一覧"""
    by_path = {}
    for tid in ed_store._tids():
        sm = ed_store.transcript_summary(tid)
        sp = str((sm or {}).get("_sourcePath") or "")
        if sp and in_eval_dir(sp, dirs):
            by_path.setdefault(os.path.normcase(os.path.abspath(sp)), []).append(sm)
    return by_path


def eval_settle(obj):
    """POST /api/eval-folders/settle {"id"}: 画面がほかの文書へ移ったときに、前の文書の動画が仮置きにあって条件を満たせば移す。
    -> {moved: {from, to, docs, member} | None, reason}(仮置きでない・整理が動いているときは moved なし)"""
    tid = str(obj.get("id") or "")
    doc = ed_store.read_transcript(tid)
    dirs = eval_dirs()
    sp = str(doc.get("sourcePath") or "")
    if dirs and sp and doc.get("evalSet") is True and not in_eval_dir(sp, dirs) and _eval_outside_docs(dirs, tid):
        # 評価用にした文書の動画が外にある: 評価用のフォルダへ取り込む(別のドライブへのコピーは時間がかかるので裏で。結果はログと整理の記録)
        if not _evalorg_lock.acquire(blocking=False):
            return {"moved": None, "reason": "整理が動いています"}

        def run():
            try:
                res = {"at": int(time.time() * 1000), "trigger": "settle", "skipped": [], "intaken": []}
                _eval_intake_pass(dirs, res, only=tid)
                for r in res["intaken"]:
                    ed_state.log.info("評価用のフォルダへ取り込んだ: %s → %s", r["from"], r["to"])
                for r in res["skipped"]:
                    ed_state.log.warning("%s: %s", r["path"], r["reason"])
                _evalorg_last.clear()
                _evalorg_last.update(res)
            except Exception:
                ed_state.log.exception("評価用のフォルダへの取り込みに失敗")
            finally:
                _evalorg_lock.release()
        threading.Thread(target=run, daemon=True, name="eval-intake").start()
        return {"moved": None, "reason": None, "intake": True}
    if not sp or not any(_inside(sp, os.path.join(r, EVAL_STAGING)) for r in dirs):
        return {"moved": None, "reason": None}
    if not _evalorg_lock.acquire(blocking=False):
        return {"moved": None, "reason": "整理が動いています"}
    try:
        key = os.path.normcase(os.path.abspath(sp))
        res = {"marked": 0, "moved": [], "staged": [], "_only": True}
        _eval_staging_pass(dirs, {k: v for k, v in _eval_docs_by_path(dirs).items() if k == key}, res)
        moved = res["moved"][0] if res["moved"] else None
        reason = res["staged"][0]["reason"] if res["staged"] else None
        if moved:
            ed_state.log.info("評価用の仮置きから移した: %s → %s", os.path.basename(moved["from"]), moved["to"])
        return {"moved": moved, "reason": reason}
    finally:
        _evalorg_lock.release()


def _eval_mark_docs(tids):
    """評価用のフォルダの中の動画なのに印の無い文書に、評価用の印を付ける(行・時刻は変えない)。-> 付けた数"""
    n = 0
    for tid in tids:
        with ed_store._save_lock:
            doc = ed_store.read_transcript(tid)
            if doc.get("evalSet") is True or not in_eval_dir(doc.get("sourcePath")):
                continue
            try:
                ed_store.hist_snapshot(tid, force=True)
            except OSError:
                pass
            doc["evalSet"] = True
            doc["updatedAt"] = max(int(time.time() * 1000), int(doc.get("updatedAt") or 0) + 1)
            ed_state.atomic_write(ed_store.tx_path(tid), json.dumps(doc, ensure_ascii=False, indent=1).encode("utf-8"))
            n += 1
    return n


def _eval_rename(old, new, tids, why="evalOrganize"):
    """動画と途中のファイルの名前を変えて(仮置きから移すとき・外から取り込むときは別のフォルダ・別のドライブへ)、その動画を使う文書を付け替える。
    付け替えに失敗したら名前を元に戻す"""
    _move(old, new)
    side, done = [], []
    try:
        side = _rename_sidecars(old, new)
        for tid in tids:
            with ed_store._save_lock:
                doc = ed_store.read_transcript(tid)
                if os.path.normcase(os.path.abspath(str(doc.get("sourcePath") or ""))) != os.path.normcase(old):
                    continue
                _relink_write(tid, doc, new, 0.0, why)
                done.append(tid)
    except BaseException:
        for tid in done:   # 付け替えた文書も元の名前へ(控えと履歴は残る)
            try:
                with ed_store._save_lock:
                    _relink_write(tid, ed_store.read_transcript(tid), old, 0.0, why + "Undo")
            except (OSError, ed_state.ApiError):
                ed_state.log.exception("評価用の整理: 文書を元の名前へ戻せませんでした %s", tid)
        for a, b in reversed(side):
            try:
                _move(b, a)
            except OSError:
                pass
        try:
            _move(new, old)
        except OSError:
            ed_state.log.exception("評価用の整理: 名前を戻せませんでした %s", new)
        raise
    ed_state.log.info("評価用の整理: %s → %s(文書 %d)", os.path.basename(old), os.path.basename(new), len(done))
    return {"from": old, "to": new, "docs": done}


def eval_folders_info():
    """GET /api/eval-folders: 設定の値・使えるフォルダ・最後の整理の結果"""
    v = ed_learn.load_settings().get("evalDirs")
    return {"dirs": v if _eval_dirs_ok(v) else [], "active": eval_dirs(), "running": _evalorg_lock.locked(), "last": dict(_evalorg_last) or None}


def _evalorg_startup():
    try:
        if eval_dirs():
            eval_organize("startup")
    except Exception:
        ed_state.log.exception("評価用のフォルダの整理(起動時)に失敗")
