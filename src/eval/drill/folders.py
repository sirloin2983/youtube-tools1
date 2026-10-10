# -*- coding: utf-8 -*-
"""④ 評価用のフォルダの整理: 動画の名前を「フォルダ名_番号_状態」にそろえる・仮置きからメンバーのフォルダへ移す・評価用にした文書の動画を外から取り込む
(docs/spec/eval-folder.md。段10 で editor/serve.py から分けた ed_relink の後半。役割で組み直す RS3-E7(2026-10-10)に eval/drill/folders.py へ切り出した)。

- 文書を付け替える書き込みは ③ の manage/cases/relink(_relink_write・_doc_busy。④ → ③ の下向き = 呼ぶたびに _relink.名前 で読む = S._relink_write = … が届く)
- 評価用のフォルダの判定(eval_dirs・in_eval_dir)は ytt/settings、別のドライブへの移動 move_file は ytt/fsio(RS3-1)
- 起動の 5 秒後に 1 回の整理(_evalorg_startup)は serve.prepare が裏のスレッドで呼ぶ
名前は serve.py からも見える(serve.py の名前の受付 _ED_MODULES がこの部品へ転送する。テストの S.名前 = … もここに入る)。
ほかの部品の名前は `モジュール.名前` の形で呼ぶたびに読む(差し替えが効くように。from … import はしない)。
"""
import os
import re
import threading
import unicodedata

from ytt import errors as _errors, fsio as _fsio, schemas as _yschemas  # noqa: E402
from flow import jobs as _heavy  # noqa: E402
from ytt import settings as _settings  # noqa: E402   評価用のフォルダの判定と設定の読み load_settings(RS3-1 に ed_relink・ed_learn から ytt/settings へ)
from ytt import tools as _tools, workdata as _workdata  # noqa: E402   (置き場所の今の値・動画と音声の拡張子)
from ytt import txbase as _txbase  # noqa: E402   ロガー log(RS3-E7 まで ed_state の別名で読んでいた)
from human.proof import store as _store  # noqa: E402   文書の読み書き・保存のロック・履歴・要約(呼ぶたびに _store.名前 で読む)
from manage.cases import relink as _relink  # noqa: E402   付け替えの書き込み _relink_write・文書が処理中か _doc_busy(呼ぶたびに _relink.名前 で読む)


# ---------- 評価用のフォルダ(2026-10-01 ユーザー決定。docs/spec/eval-folder.md) ----------
# 設定 evalDirs のフォルダ(の下)にある動画は、精度を測るためだけのデータ。文字起こしを始めたとき・保存・付け替え・履歴から戻したときに
# 評価用の印(evalSet)を付け、画面からは外せない。「整理」は動画の名前を「フォルダ名_番号_状態」にそろえ、文書を付け替える
# (入口の起動時に1回 + 画面のボタン)。状態 = 済(文字のある行がすべて校正済み)・未・未文字起こし
# 判定(eval_dirs・in_eval_dir・eval_name_guard・設定の形 _eval_dirs_ok)は ytt/settings、別のドライブへ移す move_file・same_drive は ytt/fsio
# (RS3-1 に移した。_settings.名前・_fsio.名前 で呼ぶたびに読む = S.in_eval_dir = …・patch.object(fsio, "same_drive") が届く)
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


def _eval_name_re(prefix):
    return re.compile(r"^%s_(\d{2,4})_(%s)$" % (re.escape(prefix), "|".join(sorted(EVAL_STATES, key=len, reverse=True))))


def _eval_state(sms):
    """文書の要約の一覧 → 状態。行のある文書が無ければ「未文字起こし」、どれもすべての行が校正済みなら「済」"""
    rows = [s for s in sms if s.get("rows")]
    if not rows:
        return "未文字起こし"
    return "済" if all(s["proofed"] >= s["rows"] for s in rows) else "未"


def _eval_walk(root, skip_staging=True, count_files=True):
    """評価用のフォルダの下を EVAL_WALK_DEPTH 段まで歩く -> (フォルダ, 下のフォルダ, ファイル) の並び。作業用/・「.」で始まるフォルダと、
    skip_staging なら直下の仮置きには入らない。見たフォルダ(count_files ならファイルも)の数が EVAL_WALK_MAX を超えたらやめる"""
    seen = 0
    for cur, dirs, files in os.walk(root):
        depth = os.path.relpath(cur, root).count(os.sep) + (0 if cur == root else 1)
        dirs[:] = [d for d in dirs if d != _yschemas.WORK_DIR and not d.startswith(".") and depth < EVAL_WALK_DEPTH
                   and not (skip_staging and cur == root and d == EVAL_STAGING)]
        seen += len(dirs) + (len(files) if count_files else 0)
        if seen > EVAL_WALK_MAX:
            return
        yield cur, dirs, files


def _eval_videos(root, skip_staging=True):
    """評価用のフォルダの下の動画 {フォルダ: [ファイル名]}(作業用/ と _edit の動画は除く。仮置きは skip_staging で除く)"""
    out = {}
    for cur, _dirs, files in _eval_walk(root, skip_staging):
        vids = [f for f in files if os.path.splitext(f)[1].lower() in _tools.MEDIA_TYPES and not os.path.splitext(f)[0].endswith("_edit")]
        if vids:
            out[cur] = vids
    return out


def _path_busy(path):
    key = os.path.normcase(path)
    with _heavy._jobs_lock:
        return any(j["state"] in _heavy.ACTIVE_STATES and os.path.normcase(str((j.get("spec") or {}).get("sourcePath") or "")) == key for j in _heavy._jobs.values())


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
                _fsio.move_file(a, b, log=_txbase.log)
                done.append((a, b))
    return done


def _norm_member(name):
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", str(name or ""))).lower()


def _eval_members(root):
    """評価用のフォルダの下のメンバーのフォルダ {正規化した名前: フォルダ}(「…数字_名前」の形。仮置き・作業用は除く)"""
    out = {}
    for cur, dirs, _files in _eval_walk(root, True, False):
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
        secs[nm] = secs.get(nm, 0.0) + max(0.0, (_yschemas.num_or(g.get("end"), 0.0) or 0.0) - (_yschemas.num_or(g.get("start"), 0.0) or 0.0))
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


def _eval_best_member(tids, members):
    """文書たちの話者のうち、メンバーのフォルダと同じ名前で話した秒がいちばん長い人 -> ((名前, 秒) か None, 移せない理由(_eval_ready) か None)"""
    best = None
    for tid in tids:
        secs, why = _eval_ready(_store.read_transcript(tid))
        if why:
            return None, why
        for nm, sec in secs:   # 長い順。メンバーのフォルダと同じ名前の最初の人
            if _norm_member(nm) in members:
                if best is None or sec > best[1]:
                    best = (nm, sec)
                break
    return best, None


def _eval_settle_one(path, tids, members):
    """仮置きの動画1本を、条件を満たせばメンバーのフォルダへ移す。-> ({from, to, docs, member} または None, 理由 または None)"""
    if not tids:
        return None, "まだ文字起こしされていません"
    if _path_busy(path) or any(_relink._doc_busy(t) for t in tids):
        return None, "文字起こしなどの処理の最中です"
    best, why = _eval_best_member(tids, members)
    if why:
        return None, why
    if best is None:
        return None, "移す先が決まりません(メンバーのフォルダと同じ名前の話者がいません)"
    new = _eval_next_name(members[_norm_member(best[0])], os.path.splitext(path)[1], "済")
    rec = _eval_rename(path, new, tids, "evalSettle")
    rec["member"] = best[0]
    return rec, None


def _eval_copy_index(dirs):
    """仮置きのコピーの付け替え先の候補: 評価用のフォルダの外の動画を指す、行のある文書 {正規化したファイル名: [要約]}(2026-10-02 ユーザー決定)"""
    idx = {}
    for _tid, sm, sp in _store.summaries():
        if not sp or not sm.get("rows") or _fsio.is_network_path(sp) or not os.path.isabs(sp) or _settings.in_eval_dir(sp, dirs):
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
    if _relink._doc_busy(tid):
        return None, "文書が処理の最中です"
    with _store._save_lock:
        doc = _store.read_transcript(tid)
        if _fsio.norm_path(str(doc.get("sourcePath") or "")) != _fsio.norm_path(hits[0]["_sourcePath"]):
            return None, None   # 調べている間に付け替えられた
        _relink._relink_write(tid, doc, path, 0.0, "evalStagingCopy")
    _txbase.log.info("評価用の仮置き: コピー %s に文書 %s を付け替えた(元 %s)", os.path.basename(path), tid, hits[0]["_sourcePath"])
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
                    except (OSError, _errors.ApiError) as e:
                        tid, why = None, "文書を付け替えられませんでした: %s" % (getattr(e, "message", None) or e)
                    if tid:
                        res.setdefault("adopted", []).append({"path": old, "id": tid})
                        sm = _store.transcript_summary(tid)
                        sms = [sm] if sm else []
                    elif why:
                        res["staged"].append({"path": old, "reason": why})
                        continue
                res["marked"] += _eval_mark_docs([x["id"] for x in sms if not x.get("evalSet")])
                if members is None:
                    members = _eval_members(root)
                try:
                    rec, why = _eval_settle_one(old, [x["id"] for x in sms if x.get("rows")], members)
                except (OSError, _errors.ApiError) as e:
                    rec, why = None, "移せませんでした(動画を開いているかもしれません): %s" % (getattr(e, "message", None) or e)
                if rec:
                    res["moved"].append(rec)
                else:
                    res["staged"].append({"path": old, "reason": why})


def _eval_outside_docs(dirs, only=None):
    """評価用の印があるのに、動画が評価用のフォルダの外にある文書 {動画のパス(正規化): (動画のパス, [要約])}。
    同じ動画を使う文書は印の無いものも入れる(断るかを決めるため)。only: この文書の動画だけ"""
    by_path, marked = {}, set()
    for _tid, sm, sp in _store.summaries():
        if not sp or _fsio.is_network_path(sp) or not os.path.isabs(sp) or _settings.in_eval_dir(sp, dirs) or _fsio.is_inside(sp, _workdata.DATA_DIR):
            continue
        key = _fsio.norm_path(sp)
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
    if _path_busy(path) or any(_relink._doc_busy(t) for t in tids):
        return None, "文字起こしなどの処理の最中です"
    members = _eval_members(root)
    rowed = [s["id"] for s in sms if s.get("rows")]
    best, why = _eval_best_member(rowed, members) if rowed else (None, "まだ文字起こしされていません")
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
        except (OSError, _errors.ApiError) as e:
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
        raise _errors.ApiError("busy", "評価用のフォルダの整理は、いま動いています", 409)
    try:
        dirs = _settings.eval_dirs()
        res = {"at": _yschemas.now_ms(), "trigger": trigger, "dirs": len(dirs), "videos": 0, "renamed": [], "marked": 0, "skipped": [],
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
                        if _path_busy(old) or any(_relink._doc_busy(s["id"]) for s in sms):
                            res["skipped"].append({"path": old, "reason": "文字起こしなどの処理の最中です(終わってから整理してください)"})
                            continue
                        res["renamed"].append(_eval_rename(old, new, [s["id"] for s in sms]))
                    except (OSError, _errors.ApiError) as e:
                        res["skipped"].append({"path": old, "reason": "名前を変えられませんでした(動画を開いているかもしれません): %s" % (getattr(e, "message", None) or e)})
        _txbase.log.info("評価用のフォルダを整理(%s): 動画 %d・名前を変えた %d・外から取り込んだ %d・仮置きから移した %d・評価用にした %d・飛ばした %d",
                 trigger, res["videos"], len(res["renamed"]), len(res["intaken"]), len(res["moved"]), res["marked"], len(res["skipped"]))
        _evalorg_last.clear()
        _evalorg_last.update(res)
        return res
    finally:
        _evalorg_lock.release()


def _eval_docs_by_path(dirs):
    """評価用のフォルダの中の動画 → その動画を使う文書の要約の一覧"""
    by_path = {}
    for _tid, sm, sp in _store.summaries():
        if sp and _settings.in_eval_dir(sp, dirs):
            by_path.setdefault(_fsio.norm_path(sp), []).append(sm)
    return by_path


def eval_settle(obj):
    """POST /api/eval-folders/settle {"id"}: 画面がほかの文書へ移ったときに、前の文書の動画が仮置きにあって条件を満たせば移す。
    -> {moved: {from, to, docs, member} | None, reason}(仮置きでない・整理が動いているときは moved なし)"""
    tid = str(obj.get("id") or "")
    doc = _store.read_transcript(tid)
    dirs = _settings.eval_dirs()
    sp = str(doc.get("sourcePath") or "")
    if dirs and sp and doc.get("evalSet") is True and not _settings.in_eval_dir(sp, dirs) and _eval_outside_docs(dirs, tid):
        # 評価用にした文書の動画が外にある: 評価用のフォルダへ取り込む(別のドライブへのコピーは時間がかかるので裏で。結果はログと整理の記録)
        if not _evalorg_lock.acquire(blocking=False):
            return {"moved": None, "reason": "整理が動いています"}

        def run():
            try:
                res = {"at": _yschemas.now_ms(), "trigger": "settle", "skipped": [], "intaken": []}
                _eval_intake_pass(dirs, res, only=tid)
                for r in res["intaken"]:
                    _txbase.log.info("評価用のフォルダへ取り込んだ: %s → %s", r["from"], r["to"])
                for r in res["skipped"]:
                    _txbase.log.warning("%s: %s", r["path"], r["reason"])
                _evalorg_last.clear()
                _evalorg_last.update(res)
            except Exception:
                _txbase.log.exception("評価用のフォルダへの取り込みに失敗")
            finally:
                _evalorg_lock.release()
        threading.Thread(target=run, daemon=True, name="eval-intake").start()
        return {"moved": None, "reason": None, "intake": True}
    if not sp or not any(_fsio.is_inside(sp, os.path.join(r, EVAL_STAGING)) for r in dirs):
        return {"moved": None, "reason": None}
    if not _evalorg_lock.acquire(blocking=False):
        return {"moved": None, "reason": "整理が動いています"}
    try:
        key = _fsio.norm_path(sp)
        res = {"marked": 0, "moved": [], "staged": [], "_only": True}
        _eval_staging_pass(dirs, {k: v for k, v in _eval_docs_by_path(dirs).items() if k == key}, res)
        moved = res["moved"][0] if res["moved"] else None
        reason = res["staged"][0]["reason"] if res["staged"] else None
        if moved:
            _txbase.log.info("評価用の仮置きから移した: %s → %s", os.path.basename(moved["from"]), moved["to"])
        return {"moved": moved, "reason": reason}
    finally:
        _evalorg_lock.release()


def _eval_mark_docs(tids):
    """評価用のフォルダの中の動画なのに印の無い文書に、評価用の印を付ける(行・時刻は変えない)。-> 付けた数"""
    n = 0
    for tid in tids:
        with _store._save_lock:
            doc = _store.read_transcript(tid)
            if doc.get("evalSet") is True or not _settings.in_eval_dir(doc.get("sourcePath")):
                continue
            _store.snapshot(tid)
            doc["evalSet"] = True
            doc["updatedAt"] = max(_yschemas.now_ms(), int(doc.get("updatedAt") or 0) + 1)
            _store.write_doc(tid, doc)
            n += 1
    return n


def _eval_rename(old, new, tids, why="evalOrganize"):
    """動画と途中のファイルの名前を変えて(仮置きから移すとき・外から取り込むときは別のフォルダ・別のドライブへ)、その動画を使う文書を付け替える。
    付け替えに失敗したら名前を元に戻す"""
    _fsio.move_file(old, new, log=_txbase.log)
    side, done = [], []
    try:
        side = _rename_sidecars(old, new)
        for tid in tids:
            with _store._save_lock:
                doc = _store.read_transcript(tid)
                if _fsio.norm_path(str(doc.get("sourcePath") or "")) != os.path.normcase(old):
                    continue
                _relink._relink_write(tid, doc, new, 0.0, why)
                done.append(tid)
    except BaseException:
        for tid in done:   # 付け替えた文書も元の名前へ(控えと履歴は残る)
            try:
                with _store._save_lock:
                    _relink._relink_write(tid, _store.read_transcript(tid), old, 0.0, why + "Undo")
            except (OSError, _errors.ApiError):
                _txbase.log.exception("評価用の整理: 文書を元の名前へ戻せませんでした %s", tid)
        for a, b in reversed(side):
            try:
                _fsio.move_file(b, a, log=_txbase.log)
            except OSError:
                pass
        try:
            _fsio.move_file(new, old, log=_txbase.log)
        except OSError:
            _txbase.log.exception("評価用の整理: 名前を戻せませんでした %s", new)
        raise
    _txbase.log.info("評価用の整理: %s → %s(文書 %d)", os.path.basename(old), os.path.basename(new), len(done))
    return {"from": old, "to": new, "docs": done}


def eval_folders_info():
    """GET /api/eval-folders: 設定の値・使えるフォルダ・最後の整理の結果"""
    v = _settings.load_settings().get("evalDirs")
    return {"dirs": v if _settings._eval_dirs_ok(v) else [], "active": _settings.eval_dirs(), "running": _evalorg_lock.locked(), "last": dict(_evalorg_last) or None}


def _evalorg_startup():
    try:
        if _settings.eval_dirs():
            eval_organize("startup")
    except Exception:
        _txbase.log.exception("評価用のフォルダの整理(起動時)に失敗")
