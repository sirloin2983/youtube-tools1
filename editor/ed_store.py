# -*- coding: utf-8 -*-
"""「編集」のサーバーの部品: 文字起こしの保存・履歴(自動スナップショット)・編集の内容(残す区間)(段10 で editor/serve.py から分けた。docs/plan/phase10-code-split.md)。

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
import ed_misc  # noqa: E402,F401
import ed_relink  # noqa: E402,F401
import ed_state  # noqa: E402,F401
# ---------- 文字起こしの保存 ----------
def tx_path(tid):
    return os.path.join(ed_state.TX_DIR, tid + ".json")


def sanitize_transcript(obj, base=None):
    """クライアントから来た編集内容を検査して、保存できる形にする。"""
    speakers, seen = [], set()
    for s in (obj.get("speakers") or [])[:20]:
        if not isinstance(s, dict):
            continue
        sid = re.sub(r"[^\w-]", "", str(s.get("id", "")))[:12]
        if not sid or sid in seen:
            continue
        seen.add(sid)
        one = {"id": sid, "name": str(s.get("name", ""))[:30] or sid, "color": re.sub(r"[^#\w]", "", str(s.get("color", "")))[:9]}
        if re.match(r"^#[0-9A-Fa-f]{6}$", str(s.get("outline", ""))):   # 字幕のふちの色(友人用簡易版。無ければ今までどおり)
            one["outline"] = s["outline"]
        speakers.append(one)
    segs, ids = [], set()
    now = int(time.time() * 1000)
    base_at = {}   # 保存済みの校正済みの行 id -> 校正した時刻(以前の文書で時刻が無ければ None = 分からないまま。今の時刻を作らない)
    for g in (base or {}).get("segments") or []:
        if isinstance(g, dict) and g.get("proofed") is True and isinstance(g.get("id"), str):
            at = g.get("proofedAt")
            base_at[g["id"]] = at if isinstance(at, int) and not isinstance(at, bool) and at > 0 else None
    for i, sg in enumerate(obj.get("segments") or []):
        if i >= ed_state.MAX_SEGMENTS:
            raise ed_state.ApiError("too_many", "行数が多すぎます", 400)
        if not isinstance(sg, dict):
            continue
        a, b = ed_state.num(sg.get("start")), ed_state.num(sg.get("end"))
        if a is None or b is None or a < 0 or b < a:
            continue
        sid = re.sub(r"[^\w-]", "", str(sg.get("id", "")))[:16] or "s%d" % (i + 1)
        while sid in ids:
            sid += "x"
        ids.add(sid)
        sp = str(sg.get("speaker", ""))
        one = {"id": sid, "start": round(a, 2), "end": round(b, 2), "text": str(sg.get("text", ""))[:ed_state.MAX_TEXT],
               "speaker": sp if sp in seen else "", "flag": str(sg.get("flag", ""))[:100]}
        tg = [t for t in ed_state.TAGS if isinstance(sg.get("tags"), list) and t in sg["tags"]]   # 音の状態のメモ(聞き取れない・声が重なる・BGMが大きい)
        if tg:
            one["tags"] = tg
        if sg.get("proofed") is True:   # 校正済み(人が聞いて、この行の文字が正しいと確認した印)。学習・精度測定の正解データに使う
            one["proofed"] = True
            # 初めて校正済みにした時刻(ミリ秒。マスタープラン Q2 = 時期で分けて測る)。保存済みの同じ id の行から引き継ぎ(画面の値は使わない)、
            # 保存済みで校正済みでなかった行は今。外した行は残さない(次に校正済みにした時刻から数え直す)。
            # この項目より前に校正済みだった行は時刻を作らない(分からないまま。時期で分けるときは「時刻なし = この版より前」)
            at = base_at[sid] if sid in base_at else now
            if at is not None:
                one["proofedAt"] = at
        if sg.get("cutState") == "cut":
            one["cutState"] = "cut"
        segs.append(one)
    out = dict(base or {})
    if "evalSet" in obj:   # 評価用の印(キーが来たときだけ変える。古い画面から保存しても外れないように)
        if obj.get("evalSet") is True:
            out["evalSet"] = True
        else:
            out.pop("evalSet", None)
    if ed_relink.in_eval_dir(out.get("sourcePath")):   # 評価用のフォルダの動画は外せない(2026-10-01 ユーザー決定)
        out["evalSet"] = True
    out.update({"title": str(obj.get("title", out.get("title", "")))[:120], "speakers": speakers, "segments": segs,
                "updatedAt": now})
    return out


_summary_cache = {}   # tid -> ((更新日時ns, 大きさ), 要約)。一覧・文字起こし済みの判定のたびに、全部の文書を JSON として読み直さないため


def transcript_summary(tid):
    """文書1件の要約(一覧の1行 + 元ファイル・範囲)。ファイルの更新日時と大きさが同じなら、前に読んだ結果を使う。読めなければ None。"""
    try:
        st = os.stat(tx_path(tid))
        key = (st.st_mtime_ns, st.st_size)
        hit = _summary_cache.get(tid)
        if hit and hit[0] == key:
            return hit[1]
        with open(tx_path(tid), "r", encoding="utf-8") as f:
            d = json.load(f)
    except (OSError, ValueError):
        return None
    if not isinstance(d, dict):
        return None
    segs = [s for s in (d.get("segments") or []) if isinstance(s, dict)]
    text_rows = sum(1 for s in segs if str(s.get("text") or "").strip())
    proofed = sum(1 for s in segs if s.get("proofed") is True and str(s.get("text") or "").strip())
    a = ed_state.num(d.get("start"), 0.0) or 0.0
    b = ed_state.num(d.get("end"))
    dur = ed_state.num(d.get("duration"))
    if b is not None and b > a:
        length = b - a
    elif dur is not None and dur > a:
        length = dur - a
    else:   # 古い文書・長さの記録が無い文書は、最後の行の終わりまで
        length = max([ed_state.num(s.get("end"), 0.0) or 0.0 for s in segs] or [0.0]) - a
    clip = d.get("clip") if isinstance(d.get("clip"), dict) else None
    src = clip.get("source") if clip and isinstance(clip.get("source"), dict) else {}
    rng = clip.get("range") if clip and isinstance(clip.get("range"), dict) else {}
    mk = clip.get("mark") if clip and isinstance(clip.get("mark"), dict) else {}
    sm = {"id": tid, "title": d.get("title", ""), "sourceName": d.get("sourceName", ""), "start": d.get("start", 0),
          "end": d.get("end"), "model": d.get("model", ""), "segments": len(d.get("segments") or []),
          "createdAt": d.get("createdAt", 0), "updatedAt": d.get("updatedAt", 0), "evalSet": d.get("evalSet") is True,
          "hasClip": clip is not None,
          # v0.15.0: 履歴の一覧で見分け・絞り込みに使う(校正の進み具合・長さ・元の配信)
          "rows": text_rows, "proofed": proofed, "cut": sum(1 for s in segs if s.get("cutState") == "cut"),
          "flagged": sum(1 for s in segs if str(s.get("flag") or "").strip()), "durationSec": round(max(0.0, length), 1),
          "videoId": str(src.get("videoId") or "")[:40] if clip else "", "clipTitle": str(src.get("title") or "")[:200] if clip else "",
          "clipStart": ed_state.num(rng.get("start")), "clipEnd": ed_state.num(rng.get("end")), "markLabel": str(mk.get("label") or "")[:80],
          "_sourcePath": d.get("sourcePath") or "", "_whole": bool(d.get("whole")),
          "_aliases": [r["from"] for r in d.get("relinks") or [] if isinstance(r, dict) and r.get("why") == "normalize30" and isinstance(r.get("from"), str) and r["from"]][-5:]}   # 30fps の写しへ付け替える前のパス(Q1)
    _summary_cache[tid] = (key, sm)
    return sm


def _tids():
    return [n[:-5] for n in (os.listdir(ed_state.TX_DIR) if os.path.isdir(ed_state.TX_DIR) else []) if n.endswith(".json") and ed_state.TID_RE.match(n[:-5])]


_studio_cache = {"key": None, "path": None, "videos": {}, "groups": []}   # スタジオの data.json から読んだ {videoId: {"channel", "title"}} と
                                                                        # コラボのまとまり [[videoId, …]](更新日時と大きさでキャッシュ)
_studio_lock = threading.Lock()


def _studio_load():
    """切り抜きスタジオの data.json(読むだけ。置き場所は studio_data_path() と同じ規則 = 入口の案件の画面・ytt_core.txindex と同じ)。
    -> ({videoId: {"channel", "title"}}, コラボのまとまり [[videoId, …]])。一覧のたびに大きな data.json を読み直さないよう、
    ファイルの更新日時と大きさが同じなら前の結果を使う。"""
    path = ed_state.STUDIO_DATA
    try:
        st = os.stat(path)
        key = (st.st_mtime_ns, st.st_size)
    except (OSError, ValueError):
        return {}, []
    with _studio_lock:
        if _studio_cache["key"] == key and _studio_cache["path"] == path:
            return _studio_cache["videos"], _studio_cache["groups"]
    d = ed_misc._read_json_file(path)
    out, groups = {}, []
    vids = d.get("videos") if isinstance(d, dict) else None
    if isinstance(vids, dict):
        for vid, v in list(vids.items())[:5000]:
            if isinstance(v, dict):
                out[str(vid)[:40]] = {"channel": str(v.get("channel") or "")[:100], "title": str(v.get("title") or "")[:200]}
    gs = d.get("groups") if isinstance(d, dict) else None
    for g in (list(gs.values())[:2000] if isinstance(gs, dict) else []):
        ms = g.get("members") if isinstance(g, dict) else None
        if isinstance(ms, list):
            groups.append([str(m)[:40] for m in ms[:50] if isinstance(m, str)])
    with _studio_lock:
        _studio_cache.update({"key": key, "path": path, "videos": out, "groups": groups})
    return out, groups


def studio_videos():
    """-> {videoId: {"channel", "title"}}(履歴の一覧の配信者・配信の題名)"""
    return _studio_load()[0]


def studio_stream(video_id):
    """配信 -> {"channel", "title", "collab": [{"videoId", "channel", "title"}]}(コラボ = スタジオで同じまとまりにした他の配信)。無ければ None"""
    vids, groups = _studio_load()
    vid = str(video_id or "")[:40]
    if vid not in vids:
        return None
    collab, seen = [], {vid}
    for g in groups:
        if vid in g:
            for m in g:
                if m not in seen and len(collab) < 12:
                    seen.add(m)
                    collab.append(dict(vids.get(m) or {"channel": "", "title": ""}, videoId=m))
    return dict(vids[vid], collab=collab)


PACK_CHECK_BUDGET = 2.0   # 秒。一覧1回でパック・動画の有無を調べる時間の上限(外付けの取り外し・つながらないネットワークドライブで一覧が止まらないように)


def pack_info(media_path):
    """動画の隣の <名前>_pack(cut2resolve の既定の出力先)。規則は ytt_core/txindex.pack_info の1か所(入口の案件の画面と同じ判定)。
    -> {"textplus": bool, "updatedAt": ms} か None(一覧の API にフォルダのパスは出さない)"""
    from ytt_core import txindex as _txi   # 一覧を作るときだけ使う(読み込みを軽く)
    p = _txi.pack_info(media_path)
    return {"textplus": p["textplus"], "updatedAt": p["updatedAt"]} if p else None


def _files_state(items):
    """一覧の各文書の、元の動画の有無(mediaOk)とパック(pack)。フォルダごとに1回だけ存在を確かめ、全体で PACK_CHECK_BUDGET 秒まで。
    ネットワーク上のパス(\\\\サーバー\\…)は調べない(一覧を開くだけでそのサーバーへ資格情報を送らないため。clip_info と同じ考え)。
    調べなかった・調べきれなかったものは mediaOk = None(不明)。"""
    t0 = time.monotonic()
    dirs = {}
    for it in items:
        sp = it.pop("_sp", "")
        it["mediaOk"], it["pack"] = None, None
        if not sp or not os.path.isabs(sp) or _fsio.is_network_path(sp):
            if not sp:
                it["mediaOk"] = False
            continue
        if time.monotonic() - t0 > PACK_CHECK_BUDGET:
            continue
        folder = os.path.dirname(sp)
        if folder not in dirs:
            try:
                dirs[folder] = os.path.isdir(folder)
            except (OSError, ValueError):
                dirs[folder] = False
        if not dirs[folder]:
            it["mediaOk"] = False
            continue
        try:
            it["mediaOk"] = os.path.isfile(sp)
        except (OSError, ValueError):
            it["mediaOk"] = False
        it["pack"] = pack_info(sp)


def list_transcripts():
    """GET /api/transcripts の items。作った日が新しい順(画面で並べ替える)。
    v0.15.0: 校正の進み具合(rows・proofed・cut・flagged)・長さ(durationSec)・元の配信(videoId・clipTitle・clipStart/End・markLabel)・
    配信者(channel。スタジオの data.json から)・元の動画の有無(mediaOk)・パック(pack)も返す。"""
    items, seen = [], set()
    for tid in _tids():
        seen.add(tid)
        sm = transcript_summary(tid)
        if sm:
            it = dict({k: v for k, v in sm.items() if not k.startswith("_")}, _sp=sm["_sourcePath"])
            it.update(edit_summary(tid))   # 「編集」: カットの有無・rev・パックを作った rev(履歴の「パック済み」「作り直しが要る」)
            it["packStale"] = pack_stale(it)
            it.pop("_packDocAt", None)
            items.append(it)
    for cache in (_summary_cache, _edit_cache):   # 消した文書の分は捨てる
        for k in [k for k in cache if k not in seen]:
            cache.pop(k, None)
    studio = studio_videos()
    for it in items:
        sv = studio.get(it["videoId"]) if it["videoId"] else None
        it["channel"] = sv["channel"] if sv else ""
        if sv and sv["title"]:
            it["streamTitle"] = sv["title"]   # スタジオで題名を直していれば、そちらを見出しに使う
    _files_state(items)
    items.sort(key=lambda x: x["createdAt"], reverse=True)
    return items


def read_transcript(tid):
    if not ed_state.TID_RE.match(tid or "") or not os.path.isfile(tx_path(tid)):
        raise ed_state.ApiError("not_found", "文字起こしが見つかりません", 404)
    try:
        with open(tx_path(tid), "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        raise ed_state.ApiError("broken", "文字起こしファイルを読み込めません", 500)


# ---------- 履歴(自動スナップショット)と保存の競合検出 ----------
HIST_INTERVAL = 600     # 秒。保存のたびではなく、前回の履歴からこれだけ経っていたら1つ残す
HIST_KEEP = 30          # 1本あたりの保持数(古いものから消す)
_save_lock = threading.Lock()


def _hist_dir(tid):
    return os.path.join(ed_state.TX_DIR, ".hist", tid)


def hist_stamps(tid):
    d = _hist_dir(tid)
    out = []
    if os.path.isdir(d):
        for n in os.listdir(d):
            if n.endswith(".json") and n[:-5].isdigit():
                out.append(int(n[:-5]))
    return sorted(out)


def hist_snapshot(tid, force=False):
    """いまの保存内容を履歴へ1つ残す。直近の履歴が新しければ(force でなければ)何もしない。"""
    src = tx_path(tid)
    if not os.path.isfile(src):
        return None
    stamps = hist_stamps(tid)
    now = int(time.time() * 1000)
    if not force and stamps and now - stamps[-1] < HIST_INTERVAL * 1000:
        return None
    d = _hist_dir(tid)
    os.makedirs(d, exist_ok=True)
    ts = now if not stamps or now > stamps[-1] else stamps[-1] + 1
    shutil.copy2(src, os.path.join(d, "%d.json" % ts))
    stamps.append(ts)
    for old in stamps[:-HIST_KEEP]:
        try:
            os.unlink(os.path.join(d, "%d.json" % old))
        except OSError:
            pass
    return ts


def list_history(tid):
    read_transcript(tid)
    items = []
    for ts in reversed(hist_stamps(tid)):
        try:
            with open(os.path.join(_hist_dir(tid), "%d.json" % ts), "r", encoding="utf-8") as f:
                d = json.load(f)
        except (OSError, ValueError):
            continue
        segs = d.get("segments") or []
        items.append({"ts": ts, "segments": len(segs), "proofed": sum(1 for s in segs if s.get("proofed") is True),
                      "chars": sum(len(s.get("text", "")) for s in segs)})
    return items


def save_transcript(tid, obj):
    """編集内容の保存。baseUpdatedAt が付いていて、保存済みの版とずれていれば 409(別のタブ・再認識などで先に更新されている)。"""
    with _save_lock:
        base = read_transcript(tid)
        b = obj.get("baseUpdatedAt")
        if b is not None and not obj.get("force") and base.get("updatedAt") and b != base.get("updatedAt"):
            raise ed_state.ApiError("conflict", "別の場所で先に更新されています(別のタブ、再認識、話者分離など)。読み込み直すか、この内容で上書きするか選んでください", 409)
        doc = sanitize_transcript(obj, base)
        effort_rows(base, doc)   # 校正済みにした行・外した行の数(校正の手間。Q2)
        apply_edit_cuts(tid, doc)   # 編集の内容があれば、行の「カット済」はそちらから決める(画面の古い印で上書きしない)
        try:
            hist_snapshot(tid)
        except OSError:
            pass    # 履歴が残せなくても保存は止めない
        ed_state.atomic_write(tx_path(tid), json.dumps(doc, ensure_ascii=False, indent=1).encode("utf-8"))
        return doc


def restore_history(tid, ts):
    with _save_lock:
        read_transcript(tid)
        if not isinstance(ts, int) or ts not in hist_stamps(tid):
            raise ed_state.ApiError("not_found", "その履歴は見つかりません", 404)
        p = os.path.join(_hist_dir(tid), "%d.json" % ts)
        try:
            with open(p, "r", encoding="utf-8") as f:
                old = json.load(f)
            hist_snapshot(tid, force=True)      # 戻す前の状態も残す(戻したことを取り消せるように)
            old["updatedAt"] = int(time.time() * 1000)
            cur = read_transcript(tid)
            if isinstance(cur.get("effort"), dict):   # 校正の手間の累計は戻さない(戻すのは文字と行。マスタープラン Q2)
                old["effort"] = cur["effort"]
            else:
                old.pop("effort", None)
            if ed_relink.in_eval_dir(old.get("sourcePath")):   # 評価用のフォルダの動画は、印の無い版へ戻しても評価用のまま
                old["evalSet"] = True
            apply_edit_cuts(tid, old)   # 戻すのは文字と行。カットは今の編集の内容のまま
            ed_state.atomic_write(tx_path(tid), json.dumps(old, ensure_ascii=False, indent=1).encode("utf-8"))
        except (OSError, ValueError):
            raise ed_state.ApiError("broken", "履歴を読み込めません", 500)
        return old


# ---------- 校正の手間(マスタープラン Q2。文書ごとの累計 effort = {"activeSec", "cutSec", "sessions", "proofedRows", "unproofedRows", "lastAt"}) ----------
# 時間(activeSec = 1 文字起こし のタブで操作していた秒・cutSec = 2 カット / 3 パック・sessions = 開いて作業した回数)は画面が POST /api/effort で送る。
# 行(proofedRows = 校正済みにした行・unproofedRows = 外した行)は保存のときにサーバーが数える(簡易版を含め、どの画面から保存しても同じ数え方)。
# どれも文書の updatedAt を動かさない(記録のために画面の保存の競合 baseUpdatedAt / 409 を起こさない)
MAX_EFFORT_SEC = 3600   # 1回に足せる秒の上限(画面は 30 秒刻みで数え、5 分たまったとき・離れたとき・文書を切り替えるときに送る)
EFFORT_KEYS = ("activeSec", "cutSec", "sessions", "proofedRows", "unproofedRows")


def _plain_int(v):
    return v if isinstance(v, int) and not isinstance(v, bool) else None


def _effort_of(doc):
    ef = doc.get("effort") if isinstance(doc.get("effort"), dict) else {}
    out = {k: max(0, _plain_int(ef.get(k)) or 0) for k in EFFORT_KEYS}
    if _plain_int(ef.get("lastAt")):
        out["lastAt"] = ef["lastAt"]
    return out


def effort_rows(base, doc):
    """保存で校正済みにした行・外した行(保存済みの文書 base と、これから書く doc の同じ id の行を比べる)を doc の effort に足す"""
    before = {g.get("id") for g in (base or {}).get("segments") or [] if isinstance(g, dict) and g.get("proofed") is True}
    after = {g["id"]: g.get("proofed") is True for g in doc.get("segments") or []}
    on = sum(1 for i, p in after.items() if p and i not in before)
    off = sum(1 for i in before if i in after and not after[i])
    if on or off:
        ef = _effort_of(doc)
        ef["proofedRows"] += on
        ef["unproofedRows"] += off
        ef["lastAt"] = doc.get("updatedAt") or int(time.time() * 1000)
        doc["effort"] = ef


def add_effort(obj):
    """POST /api/effort {"id", "activeSec", "cutSec"?, "newSession"?} -> {"effort": 累計}。文書の effort の時間と回数に足す。
    **文書の updatedAt は変えない**。保存と同じロックの中で読み直して足す"""
    tid = str(obj.get("id") or "")
    sec, cut = _plain_int(obj.get("activeSec", 0)), _plain_int(obj.get("cutSec", 0))
    if sec is None or cut is None or not 0 <= sec <= MAX_EFFORT_SEC or not 0 <= cut <= MAX_EFFORT_SEC:
        raise ed_state.ApiError("bad_request", "activeSec・cutSec は 0〜%d 秒の整数にしてください" % MAX_EFFORT_SEC, 400)
    with _save_lock:
        doc = read_transcript(tid)
        ef = _effort_of(doc)
        if not sec and not cut:
            return {"effort": ef}
        ef["activeSec"] += sec
        ef["cutSec"] += cut
        ef["sessions"] += 1 if obj.get("newSession") is True else 0
        ef["lastAt"] = int(time.time() * 1000)
        doc["effort"] = ef
        ed_state.atomic_write(tx_path(tid), json.dumps(doc, ensure_ascii=False, indent=1).encode("utf-8"))
        return {"effort": ef}


# ---------- 編集の内容(残す区間。「編集」ツールのカットの正。docs/design/edit-tool-design.md の 4・5) ----------
# 文書 transcripts/<id>.json の隣の <id>.edit.json。校正の保存(文書の baseUpdatedAt)と、タイムラインの細かい保存(rev)を別にするため別のファイル。
# 行の「カット済」(cutState)は、編集の内容があるときは常にそこから決める(文書のどの書き込みでも apply_edit_cuts を通す)。
EDIT_SCHEMA = "youtube-tools-edit/v1"
MAX_EDIT_BYTES = 1024 * 1024
MAX_CLIPS = 5000
MAX_MEDIA_SEC = 24 * 3600
EDIT_ORIGINS = ("rows", "silence", "list", "plan", "manual", "all", "whole")   # whole = 「カットしない(動画全体)」を選んだ(気が利く画面へ 段3)
CUT_TOLERANCE_FRAMES = 0.75   # 行の時間のうち、残す区間に入るのがこれ未満(フレーム)なら「カット済」。区間の端はフレームに、行の時刻は 0.01 秒に丸めてあるため
_edit_cache = {}   # tid -> ((更新日時ns, 大きさ), 一覧用の要約)


def edit_path(tid):
    return os.path.join(ed_state.TX_DIR, tid + ".edit.json")


def _real(x):
    """JSON の数(真偽値・文字列・NaN は数として扱わない)。-> float か None"""
    if isinstance(x, bool) or not isinstance(x, (int, float)):
        return None
    x = float(x)
    return x if math.isfinite(x) else None


def _fps_pair(v):
    if not isinstance(v, list) or len(v) != 2 or any(isinstance(x, bool) or not isinstance(x, int) for x in v):
        return None
    n, d = v
    if not (1 <= n <= 1000000 and 1 <= d <= 1000000 and 1 <= n / d <= 300):
        return None
    return [n, d]


def sanitize_edit(obj):
    """画面から来た編集の内容を検査して、保存できる形にする(知らない項目は捨てる。rev・packRev はサーバーが付ける)。
    v1: 動画は文書の動画1本だけ(sources は1つ・clips の src は 0)。区間は元の動画の秒で、時刻の順・重ならない。区間が0個も受け付ける(全部削った状態)"""
    if not isinstance(obj, dict):
        raise ed_state.ApiError("bad_edit", "編集の内容の形が正しくありません", 400)
    srcs = obj.get("sources")
    if not isinstance(srcs, list) or len(srcs) != 1 or not isinstance(srcs[0], dict):
        raise ed_state.ApiError("bad_edit", "動画(sources)は1つだけにしてください(複数の切り抜きをつなぐのは、まだ使えません)", 400)
    fps, dur = _fps_pair(srcs[0].get("fps")), _real(srcs[0].get("duration"))
    if fps is None or dur is None or not 0 < dur <= MAX_MEDIA_SEC:
        raise ed_state.ApiError("bad_edit", "動画の fps・長さが正しくありません", 400)
    clips = obj.get("clips")
    if not isinstance(clips, list) or len(clips) > MAX_CLIPS:
        raise ed_state.ApiError("bad_edit", "区間(clips)は %d 個までです" % MAX_CLIPS, 400)
    limit = dur + fps[1] / fps[0] + 1e-6   # 長さ + 1フレームまで(フレームの境目に丸めた分)
    out, prev = [], 0.0
    for c in clips:
        if not isinstance(c, dict):
            raise ed_state.ApiError("bad_edit", "区間の形が正しくありません", 400)
        src = c.get("src", 0)
        if isinstance(src, bool) or src != 0:
            raise ed_state.ApiError("bad_edit", "区間の動画(src)は 0 だけにしてください(複数の切り抜きをつなぐのは、まだ使えません)", 400)
        a, b = _real(c.get("in")), _real(c.get("out"))
        if a is None or b is None or not 0 <= a < b <= limit:
            raise ed_state.ApiError("bad_edit", "区間の時刻が正しくありません(0 ≤ 始まり < 終わり ≤ 動画の長さ)", 400)
        if a < prev - 1e-6:
            raise ed_state.ApiError("bad_edit", "区間は時刻の順に、重ならないように並べてください", 400)
        ra, rb = round(a, 3), round(b, 3)
        if rb <= ra:
            raise ed_state.ApiError("bad_edit", "区間が短すぎます", 400)
        out.append({"src": 0, "in": ra, "out": rb})
        prev = b
    return {"sources": [{"fps": fps, "duration": round(dur, 3)}], "clips": out,
            "origin": obj.get("origin") if obj.get("origin") in EDIT_ORIGINS else "manual"}


DRAFT_ORIGINS = ("rows", "all", "whole", "silence", "list", "plan")   # 機械が作るたたき台(manual は人の操作なので入れない)


def sanitize_draft(v):
    """初めてのたたき台の記録 draft(マスタープラン Q2。人の最終 = 保存したカット・パックの cutPlan と並べて、たたき台の規則を直すため)を確かめる。
    {"origin": たたき台の種類, "settings": {名前: 数・真偽・短い文字}(行から = 行の端の設定 rowEdge・無音 = しきい値など), "keepsSec": [[開始, 終了], …], "at"}。
    記録のための値なので、正しくなければ None(= 保存しない。カットの保存は止めない)"""
    if not isinstance(v, dict) or v.get("origin") not in DRAFT_ORIGINS:
        return None
    keeps = v.get("keepsSec")
    if not isinstance(keeps, list) or len(keeps) > MAX_CLIPS:
        return None
    out_k, prev = [], 0.0
    for x in keeps:
        a, b = (_real(x[0]), _real(x[1])) if isinstance(x, list) and len(x) == 2 else (None, None)
        if a is None or b is None or not 0 <= a < b <= MAX_MEDIA_SEC or a < prev - 1e-6:
            return None
        out_k.append([round(a, 3), round(b, 3)])
        prev = b
    st = v.get("settings") if isinstance(v.get("settings"), dict) else {}
    settings = {}
    for k, x in list(st.items())[:20]:
        if not isinstance(k, str) or not re.fullmatch(r"[A-Za-z][\w]{0,29}", k, re.A):
            continue
        if isinstance(x, bool) or (isinstance(x, str) and len(x) <= 100 and not any(ord(ch) < 32 for ch in x)):
            settings[k] = x
        elif _real(x) is not None:
            settings[k] = round(_real(x), 4)
    at = v.get("at")
    return {"origin": v["origin"], "settings": settings, "keepsSec": out_k,
            "at": at if isinstance(at, int) and not isinstance(at, bool) and at > 0 else int(time.time() * 1000)}


def read_edit(tid):
    """保存済みの編集の内容。-> (中身 または None, 壊れているか)。形が正しくないもの(手で書き換えた・書きかけ)は壊れている扱い"""
    try:
        with open(edit_path(tid), "rb") as f:
            raw = f.read(MAX_EDIT_BYTES + 1)
    except FileNotFoundError:
        return None, False
    except OSError:
        return None, True
    try:
        d = json.loads(raw.decode("utf-8-sig"), parse_constant=ed_state._reject_json_constant) if len(raw) <= MAX_EDIT_BYTES else None
        if not isinstance(d, dict) or d.get("schema") != EDIT_SCHEMA or isinstance(d.get("rev"), bool) or not isinstance(d.get("rev"), int):
            return None, True
        out = sanitize_edit(d)
    except (UnicodeDecodeError, ValueError, ed_state.ApiError):
        return None, True
    pr = d.get("packRev")
    out.update({"schema": EDIT_SCHEMA, "rev": max(0, d["rev"]), "updatedAt": d.get("updatedAt") if isinstance(d.get("updatedAt"), int) else 0,
                "packRev": pr if isinstance(pr, int) and not isinstance(pr, bool) and pr >= 0 else 0})
    if isinstance(d.get("pack"), dict):
        out["pack"] = d["pack"]
    draft = sanitize_draft(d.get("draft"))   # 初めてのたたき台の記録(Q2。以前の edit.json には無い)
    if draft:
        out["draft"] = draft
    return out, False


def edit_cut_flags(segs, edit):
    """編集の内容から、各行が「カット済」か。-> [bool](segs と同じ順)。
    行の時間が全部、削る区間に入っていれば(残す区間に入るのが CUT_TOLERANCE_FRAMES 未満なら)カット済。
    ごく短い行(2 × 許す幅 以下)は、行の真ん中が残す区間に入っているかで決める。画面の cut.js も同じ規則"""
    clips = edit["clips"]
    fps = edit["sources"][0]["fps"]
    tol = CUT_TOLERANCE_FRAMES * fps[1] / fps[0]
    starts = [c["in"] for c in clips]
    out = []
    for s in segs:
        a, b = ed_state.num(s.get("start"), 0.0), ed_state.num(s.get("end"), 0.0)
        i = max(0, bisect.bisect_right(starts, a) - 1)
        if b - a <= 2 * tol:
            mid = (a + b) / 2
            j = bisect.bisect_right(starts, mid) - 1
            out.append(not (j >= 0 and clips[j]["in"] <= mid < clips[j]["out"]))
            continue
        kept = 0.0
        while i < len(clips) and clips[i]["in"] < b:
            kept += max(0.0, min(b, clips[i]["out"]) - max(a, clips[i]["in"]))
            i += 1
        out.append(kept < tol)
    return out


def apply_edit_cuts(tid, doc, edit=None):
    """編集の内容があれば、文書の行の cutState をそれに合わせる(文書の書き込みは全部ここを通す)。
    -> 変わった行の数。編集の内容が無い・壊れているときは None(行の cutState はそのまま = 以前の使い方)"""
    if edit is None:
        edit, _broken = read_edit(tid)
        if not edit:
            return None
    segs = [s for s in (doc.get("segments") or []) if isinstance(s, dict)]
    changed = 0
    for s, cut in zip(segs, edit_cut_flags(segs, edit)):
        if cut != (s.get("cutState") == "cut"):
            changed += 1
        if cut:
            s["cutState"] = "cut"
        else:
            s.pop("cutState", None)
    return changed


DRAFT_SLOT_WAIT = 10.0   # 「行から」の行の端の無音を調べる順番(SLOTS)を待つ上限(秒)。過ぎたら無音を調べずに決まった余白で広げる


def _draft_slot(label):
    deadline = time.monotonic() + DRAFT_SLOT_WAIT
    return _heavy.SLOTS.slot(ed_state.TOOL_ID, label, cancelled=lambda: time.monotonic() > deadline)


def edit_draft(tid, rows=False):
    """GET /api/edit/draft?id=&rows=1 : 動画の fps・長さと、たたき台「行から」(残す行が無ければ全部残す)。計算は cut2resolve の pack.py(resolve_export.edit_draft)。
    「行から」を計算するのは、カットが無い(壊れている)文書か rows=1(「行から」のボタン)のときだけ(行の端の無音を調べるのは重いので、開くたびにしない)。
    行の端を広げるかは設定の rowEdge(docs/design/edit-tool-design.md の 12 ⑥)。無音の検出は SLOTS を通す(DRAFT_SLOT_WAIT 秒待っても空かなければ決まった余白)。
    カット・パックに使えないとき(動画が無い・ネットワーク上・音声だけ)は {"unavailable": {"code", "message"}}。
    ネットワーク上の動画は調べない(カット・パックに使えない理由を画面に出す。一覧・clip-info と同じく、開くだけで資格情報を送らない)。
    隣の .cut-plan.json(スタジオなどの残す区間の指定)があるかも返す(たたき台「スタジオ」)"""
    import resolve_export
    doc = read_transcript(tid)
    src = str(doc.get("sourcePath") or "")

    def unavailable(code, message):   # 使えない理由は 200 で返す(画面が毎回エラーとして記録しないように。文書が無いときだけ 404)
        return {"unavailable": {"code": code, "message": message}}
    if not src:
        return unavailable("no_source", "この文書には動画のパスがありません")
    if _fsio.is_network_path(src):
        return unavailable("network_path", "ネットワーク上の動画は、カットとパックに使えません(このパソコンにコピーして開いてください)")
    if not os.path.isfile(src):
        return unavailable("source_missing", "元の動画が見つかりません(移動・削除した可能性があります)")
    try:
        need = bool(rows) or not read_edit(tid)[0]
        out = resolve_export.edit_draft(doc, ed_state.SERVER_VERSION, rows=need, row_edge=ed_learn.load_settings().get("rowEdge"), heavy=_draft_slot)
    except resolve_export.ResolveExportError as e:
        msg = str(e)
        if "動画ストリーム" in msg:
            return unavailable("no_video", "映像の無いファイル(音声だけ)は、カットとパックに使えません")
        return unavailable("draft_failed", msg)
    out["planBeside"] = _yschemas.find_sidecar(src, ".cut-plan.json") or ""   # 作業用\ → 以前の置き方(動画の隣)
    return out


def edit_keeps_sec(edit):
    """編集の内容の残す区間(秒)。接している区間(分割しただけ)は1つにまとめる(パックと同じ)"""
    out = []
    for c in edit["clips"]:
        if out and c["in"] <= out[-1][1] + 1e-9:
            out[-1][1] = max(out[-1][1], c["out"])
        else:
            out.append([c["in"], c["out"]])
    return out


def keeps_arg(v):
    """画面から来た残す区間 [[開始, 終了], ...](秒)の検査(cut2resolve の keeps_from_spec と同じ決まり)"""
    if not isinstance(v, list) or not 1 <= len(v) <= MAX_CLIPS:
        raise ed_state.ApiError("bad_keeps", "残す区間は 1〜%d 個にしてください" % MAX_CLIPS, 400)
    out, prev = [], 0.0
    for x in v:
        a, b = (_real(x[0]), _real(x[1])) if isinstance(x, list) and len(x) == 2 else (None, None)
        if a is None or b is None or not 0 <= a < b <= MAX_MEDIA_SEC or a < prev:
            raise ed_state.ApiError("bad_keeps", "残す区間は時刻の順に、重ならないように [開始, 終了] で指定してください", 400)
        out.append([a, b])
        prev = b
    return out


def edit_preview(obj):
    """POST /api/edit/preview {"id", "keeps"}: カットのとおりに作ったときのパックの見積もり(区間の数・カット後の長さ・Text+ 字幕の数・注意)。ファイルは作らない"""
    import resolve_export
    doc = read_transcript(str(obj.get("id") or ""))
    keeps = keeps_arg(obj.get("keeps"))
    src = str(doc.get("sourcePath") or "")
    if not src or _fsio.is_network_path(src) or not os.path.isfile(src):
        raise ed_state.ApiError("no_media", "元の動画が見つかりません", 400)
    try:
        return resolve_export.edit_preview(doc, keeps, ed_state.SERVER_VERSION, wrap_arg(obj.get("wrap")))
    except resolve_export.ResolveExportError as e:
        raise ed_state.ApiError("preview_failed", str(e), 400)


def wrap_arg(v, size=None):
    """Text+ 字幕の1段の文字数(0〜40)。無ければ設定の subtitle.wrapChars(size が横 1920x1080 なら横、それ以外は縦)"""
    if isinstance(v, (int, float)) and not isinstance(v, bool) and 0 <= v <= 40:
        return int(v)
    sub = ed_jobs.subtitle_settings()
    return sub["wrapChars"]["horizontal" if str(size or "") == "1920x1080" else "vertical"]


PACK_README_NAMES = ("友人へ.txt", "予備_EDLで開く手順.txt")   # 2026-09-27 より前のパック(今は手順書のファイルを入れない)


def pack_readme(tid):
    """GET /api/edit/pack-readme?id=: 前回のパックの Resolve での手順。記録したフォルダが cut2resolve のパック
    (cut2resolve のパックを作った記録があるか、以前のパックなら中に cut-plan.json。ytt_core.txindex.is_pack_dir)のときだけ読む。
    今のパックは手順書のファイルが無いので、パックの Lua から作り直す(resolve_export.pack_instructions)。以前のパックはファイルを読む"""
    from ytt_core import txindex as _txi
    read_transcript(tid)
    d, _ = read_edit(tid)
    pk = (d or {}).get("pack") or {}
    folder = pk.get("dir") if isinstance(pk.get("dir"), str) else ""
    if not folder or _fsio.is_network_path(folder) or not _txi.is_pack_dir(folder):
        raise ed_state.ApiError("not_found", "前回のパックのフォルダが見つかりません(移動・削除した可能性があります)", 404)
    import resolve_export
    text = resolve_export.pack_instructions(folder)
    if text:
        return {"name": "", "text": text}
    for n in PACK_README_NAMES:
        try:
            with open(os.path.join(folder, n), "rb") as f:
                return {"name": n, "text": f.read(256 * 1024).decode("utf-8-sig", "replace")}
        except OSError:
            continue
    raise ed_state.ApiError("not_found", "パックの中に Resolve での手順を作る材料(.lua)がありません", 404)


def get_edit(tid):
    """GET /api/edit?id= -> {"edit": 中身 | null, "rev", "broken"}(無ければ null と rev 0)"""
    doc = read_transcript(tid)
    d, broken = read_edit(tid)
    pk = (d or {}).get("pack") or {}
    stale = pack_stale({"packRev": d["packRev"] if d else 0, "editRev": d["rev"] if d else 0, "updatedAt": doc.get("updatedAt") or 0,
                        "_packDocAt": pk.get("docUpdatedAt") if isinstance(pk.get("docUpdatedAt"), int) else 0})
    return {"edit": d, "rev": d["rev"] if d else 0, "broken": broken, "packStale": stale}


def save_edit(tid, obj):
    """PUT /api/edit?id= {"edit", "baseRev", "draft"?} -> {"rev", "cutRows", "updatedAt"}。baseRev が保存済みの rev と違えば 409(別のタブ・窓で先に保存された)。
    draft = 画面がそのカットを始めたたき台(sanitize_draft)。保存済みの edit.json に draft が無いときだけ一度だけ書く(上書きしない。Q2)。
    文書の行の cutState も同じロックの中で合わせる(画面から2回に分けて送らない)。文書の updatedAt は変えない
    (cutState は編集の内容から決まる値なので、校正の保存の競合の検出(baseUpdatedAt)に巻き込まない)"""
    base = obj.get("baseRev")
    if isinstance(base, bool) or not isinstance(base, int) or base < 0:
        raise ed_state.ApiError("bad_request", "baseRev(読み込んだときの rev)を付けてください", 400)
    clean = sanitize_edit(obj.get("edit"))
    with _save_lock:
        doc = read_transcript(tid)
        cur, broken = read_edit(tid)
        rev = cur["rev"] if cur else 0
        if base != rev:
            raise ed_state.ApiError("conflict", "別のタブか窓で、先にカットが保存されています。読み直すか、こちらの内容で上書きするか選んでください", 409, {"rev": rev})
        if broken:   # 壊れたファイルは上書きする前に1つだけ残す(調べられるように)
            try:
                shutil.copy2(edit_path(tid), os.path.join(ed_state.TX_DIR, tid + ".edit.broken.json"))
            except OSError:
                pass
        now = int(time.time() * 1000)
        d = dict(clean, schema=EDIT_SCHEMA, rev=rev + 1, updatedAt=now, packRev=cur["packRev"] if cur else 0)
        if cur and cur.get("pack"):
            d["pack"] = cur["pack"]
        if cur and cur.get("draft"):
            d["draft"] = cur["draft"]
        elif not cur:   # 初めての保存(壊れていたファイルの上書きを含む)のときだけ。以前の版で作った edit.json には後から足さない(始めたたき台が分からないため)
            draft = sanitize_draft(obj.get("draft"))
            if draft:
                d["draft"] = draft
        body = json.dumps(d, ensure_ascii=False, indent=1).encode("utf-8")
        if len(body) > MAX_EDIT_BYTES:
            raise ed_state.ApiError("too_big", "区間が多すぎて保存できません", 413)
        ed_state.atomic_write(edit_path(tid), body)   # 先に編集の内容(文書の書き込みが失敗しても、次の保存で cutState は合う)
        if apply_edit_cuts(tid, doc, d):
            ed_state.atomic_write(tx_path(tid), json.dumps(doc, ensure_ascii=False, indent=1).encode("utf-8"))
        cut_rows = [s.get("id") for s in doc.get("segments") or [] if isinstance(s, dict) and s.get("cutState") == "cut"]
        return {"rev": d["rev"], "cutRows": cut_rows, "updatedAt": now}


PACK_OUTPUT_LOUDNESS = (0, -11, -14, -16, -18)


def _pack_text(v, limit):
    """出力の設定の文字列: 長さの上限以内・制御文字なし(改行・タブ・NUL などを含めば None)"""
    if not isinstance(v, str) or len(v) > limit or any(ord(ch) < 32 or ord(ch) == 127 for ch in v):
        return None
    return v


def sanitize_pack_output(o):
    """POST /api/edit/pack の output(作ったときの出力の設定)を確かめる。決まった鍵だけ残し(余計な鍵は黙って捨てる)、
    必須の鍵が1つでも正しくなければ、あるいは任意の鍵が入っていて正しくなければ None(= 記録には output を入れない。
    古い画面・まとめて実行 home/autorun.py は output を送らないので、エラーにはしない)。bool は int でもあるので先に isinstance(bool) で見る"""
    if not isinstance(o, dict):
        return None
    out = {}
    fps = o.get("fps")
    if not isinstance(fps, str) or not re.fullmatch(r"\d{1,3}", fps, re.A):
        return None
    out["fps"] = fps
    if o.get("size") not in ("1080x1920", "1920x1080"):
        return None
    out["size"] = o["size"]
    wrap = o.get("wrap")
    if isinstance(wrap, bool) or not isinstance(wrap, int) or not 0 <= wrap <= 40:
        return None
    out["wrap"] = wrap
    for k in ("textplus", "backup", "render", "speakerColors"):
        if not isinstance(o.get(k), bool):
            return None
        out[k] = o[k]
    if "streamer" in o:
        st = _pack_text(o["streamer"], 200)
        if st is None:
            return None
        out["streamer"] = st
    if "loudness" in o:
        v = o["loudness"]
        if isinstance(v, bool) or not isinstance(v, (int, float)) or v not in PACK_OUTPUT_LOUDNESS:
            return None
        out["loudness"] = v
    if "volume" in o:
        v = o["volume"]
        if isinstance(v, bool) or not isinstance(v, int) or not 1 <= v <= 200:
            return None
        out["volume"] = v
    if "advanced" in o:
        adv = o["advanced"]
        if not isinstance(adv, dict):
            return None
        a = {}
        for k in ("srcStartTc", "recStart", "reel"):
            if k in adv:
                t = _pack_text(adv[k], 40)
                if t is None:
                    return None
                a[k] = t
        out["advanced"] = a
    return out


def record_pack(obj):
    """POST /api/edit/pack {"id", "rev", "docUpdatedAt", "dir", "files"}: 画面がパックを作り終えたときに呼ぶ(rev は増やさない)。
    packRev = そのパックを作った編集の rev。rev ≠ packRev か、文書の updatedAt が docUpdatedAt より新しければ「作り直し」"""
    tid = str(obj.get("id") or "")
    rev, dua = obj.get("rev"), obj.get("docUpdatedAt")
    if isinstance(rev, bool) or not isinstance(rev, int) or rev < 1 or isinstance(dua, bool) or not isinstance(dua, int) or dua < 0:
        raise ed_state.ApiError("bad_request", "rev・docUpdatedAt が正しくありません", 400)
    out_dir = obj.get("dir")
    if not isinstance(out_dir, str) or not out_dir or len(out_dir) > 1000 or any(ch in out_dir for ch in "\x00\r\n") or not os.path.isabs(out_dir):
        raise ed_state.ApiError("bad_request", "パックのフォルダ(dir)が正しくありません", 400)
    files = [os.path.basename(str(x))[:200] for x in (obj.get("files") or []) if isinstance(x, str)][:40] if isinstance(obj.get("files"), list) else []
    output = sanitize_pack_output(obj.get("output"))
    with _save_lock:
        read_transcript(tid)
        cur, _broken = read_edit(tid)
        if not cur:
            raise ed_state.ApiError("no_edit", "カットがまだ保存されていません", 409)
        if rev > cur["rev"]:
            raise ed_state.ApiError("bad_request", "rev が保存済みのカットより新しくなっています", 400)
        now = int(time.time() * 1000)
        pk = {"rev": rev, "at": now, "docUpdatedAt": dua, "dir": out_dir, "files": files}
        if output is not None:
            pk["output"] = output
        d = dict(cur, packRev=rev, pack=pk)
        ed_state.atomic_write(edit_path(tid), json.dumps(d, ensure_ascii=False, indent=1).encode("utf-8"))
        return {"ok": True, "packRev": rev, "at": now}


def edit_summary(tid):
    """一覧の各文書の編集・パックの状態(ファイルの更新日時と大きさが同じなら前の結果)。"""
    try:
        st = os.stat(edit_path(tid))
    except OSError:
        _edit_cache.pop(tid, None)
        return {"hasEdit": False, "editRev": 0, "packRev": 0, "_packDocAt": 0, "packAt": 0}
    key = (st.st_mtime_ns, st.st_size)
    hit = _edit_cache.get(tid)
    if hit and hit[0] == key:
        return hit[1]
    d, _broken = read_edit(tid)
    pk = (d or {}).get("pack") or {}
    sm = {"hasEdit": bool(d), "editRev": d["rev"] if d else 0, "packRev": d["packRev"] if d else 0,
          "_packDocAt": pk.get("docUpdatedAt") if isinstance(pk.get("docUpdatedAt"), int) else 0,
          "packAt": pk.get("at") if isinstance(pk.get("at"), int) else 0}
    _edit_cache[tid] = (key, sm)
    return sm


def pack_stale(item):
    """パックを作ったあとにカットか文字が変わったか(一覧と画面の「作り直し」の知らせ。規則はここ1か所)"""
    return bool(item.get("packRev")) and (item.get("editRev") != item.get("packRev") or (item.get("updatedAt") or 0) > (item.get("_packDocAt") or 0))


def doc_has_rows(doc):
    return any(isinstance(s, dict) and str(s.get("text") or "").strip() for s in doc.get("segments") or [])


def fill_doc(spec, fields):
    """文字起こしの結果を、文字起こしの無い文書(intoDoc)に入れる。id・題名・作った日・clip・編集の内容はそのまま。
    -> 入れた文書の id。その間に文書が消えた・行が入った・動画が変わったときは None(呼び出し側が新しい文書にする。結果は捨てない)"""
    tid = spec["intoDoc"]
    with _save_lock:
        try:
            doc = read_transcript(tid)
        except ed_state.ApiError:
            doc = None
        same = doc is not None and os.path.normcase(os.path.abspath(str(doc.get("sourcePath") or ""))) == os.path.normcase(spec["sourcePath"])
        if not same or doc_has_rows(doc):
            spec.setdefault("warnings", []).append("文字起こしを入れる文書が変わっていたため、新しい文字起こしとして保存しました")
            return None
        doc.update(fields)
        if spec.get("clip") and not doc.get("clip"):
            doc["clip"] = spec["clip"]
        if spec.get("evalSet"):
            doc["evalSet"] = True   # 評価用として文字起こしした(外すのは画面の「評価用にする」)
        apply_edit_cuts(tid, doc)   # 先にカットを決めてあれば、行の「カット済」もそれに合わせる
        ed_state.atomic_write(tx_path(tid), json.dumps(doc, ensure_ascii=False, indent=1).encode("utf-8"))
        return tid


def probe_media(path):
    """ffmpeg -i で長さと、映像・音声の有無を調べる。-> (長さ秒 または None, 映像あり, 音声あり)。
    カバー画像(音声ファイルに付いた attached pic)は映像に数えない"""
    ff = ed_state.find_ffmpeg()
    if not ff:
        raise ed_state.ApiError("no_ffmpeg", "ffmpeg が見つかりません(README の準備手順を確認してください)", 400)
    try:
        p = subprocess.run([ff, "-hide_banner", "-nostdin", "-i", path], stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                           stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace", timeout=30)
    except (OSError, subprocess.SubprocessError):
        return None, False, False
    out = p.stdout or ""
    m = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", out)
    dur = int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3)) if m else None
    streams = [l for l in out.splitlines() if re.match(r"\s*Stream #\d+:\d+", l)]
    has_v = any(": Video:" in l and "attached pic" not in l for l in streams)
    has_a = any(": Audio:" in l for l in streams)
    return dur, has_v, has_a


_open_lock = threading.Lock()


def find_doc_for_media(path):
    """その動画の文書(行のある文書・更新が新しいものを先に)。-> {"id", "rows"} か None。パスを比べるだけで、ファイルには触らない"""
    p = str(path or "").strip().strip('"')
    if not p or "\x00" in p:
        return None
    key = os.path.normcase(os.path.abspath(p))
    best = None
    for tid in _tids():
        sm = transcript_summary(tid)
        if not sm or not any(p and os.path.normcase(os.path.abspath(p)) == key for p in [sm["_sourcePath"]] + list(sm.get("_aliases") or ())):
            continue
        rank = (sm["rows"] > 0, sm.get("updatedAt") or 0)
        if best is None or rank > best[0]:
            best = (rank, {"id": tid, "rows": sm["rows"]})
    return best[1] if best else None


def open_video(req):
    """POST /api/open-video {"path", "title"?} -> {"id", "created", "warnings"}。「文字起こしせずに開く」: 動画のパスだけで文書を作る。
    同じ動画の文書があればそれを返す(行のある文書・新しいものを先に)。隣の .clip.json があれば文書の clip に入れる(スタジオの切り抜きと紐づく)。
    文書にした動画は /media で配るので、動画・音声の拡張子で、ffmpeg で映像か音声が読めるものだけ受け付ける"""
    src = ed_state.check_source(req.get("path"))
    with _open_lock:   # 同じ動画を続けて2回開いても、文書を2つ作らない
        hit = find_doc_for_media(src)
        if hit:
            return {"id": hit["id"], "created": False, "warnings": []}
        dur, has_v, has_a = probe_media(src)
        if not (has_v or has_a):
            raise ed_state.ApiError("bad_media", "動画・音声として読めませんでした(壊れているか、対応していない形式です)", 400)
        pm = ed_state.pio(required=False)
        clip, warn, _cp = pm.find_clip(src, dur) if pm else (None, None, None)
        tid = uuid.uuid4().hex[:12]
        now = int(time.time() * 1000)
        doc = {"schema": "transcribe/v1", "id": tid, "title": str(req.get("title") or "").strip()[:120] or os.path.splitext(os.path.basename(src))[0][:120],
               "sourcePath": src, "sourceName": os.path.basename(src), "start": 0, "end": round(dur, 2) if dur else None, "whole": True,
               "duration": dur, "model": "", "language": "", "params": {}, "speakers": [], "segments": [], "original": [],
               "createdAt": now, "updatedAt": now}
        if clip:
            doc["clip"] = clip
        with _save_lock:
            ed_state.atomic_write(tx_path(tid), json.dumps(doc, ensure_ascii=False, indent=1).encode("utf-8"))
    ed_state.log.info("文字起こしせずに開く: %s", os.path.basename(src))
    return {"id": tid, "created": True, "warnings": [warn] if warn else []}
