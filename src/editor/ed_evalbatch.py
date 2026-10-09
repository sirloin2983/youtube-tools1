# -*- coding: utf-8 -*-
"""「編集」のサーバーの部品: 評価用の動画を、手が空いたとき少しずつまとめて文字起こしする(マスタープラン Q4(b)。git の履歴(679ff01 以前)の docs/plan/q3-q4-design.md)。

評価用のフォルダ(設定 evalDirs)の「評価用_仮置き」と、名前が「…_NN_未文字起こし」の動画のうち、文字のある文書がまだ無い・動いていないものを、
**待っているジョブが 2 件までになるよう少しずつ**文字起こしの待機列に入れる(一度に全部を入れるフォルダ一括と違い、ユーザーの操作が割り込める)。
  - 始めるのはボタンだけ(API の start)。止めるまで続く(止める = stop。残りがなくなったら自分で止まる)。夜間の自動開始はしない
  - 起動し直しても、状態 `eval-batch.json`(作業データ)の enabled が真なら続ける
  - 評価用の印(evalSet: True)を明示し、ヒント(用語集・文脈・置換辞書・学習した置換)は `validate_job` の評価用の規則で付かない。
    処理方式・モデル・言語などは編集の設定(settings.json)のまま
  - ユーザーのジョブ(自分が入れたもの以外)が動いている・待っている間と、評価用のフォルダの整理の間は、自分の分を増やさない
  - 失敗したら 2 回までやり直し、それでもだめなら飛ばす(同じ動画を延々と入れ直さない)。取り消されたら飛ばす
  - ほかのプロセス(単独で動かした編集と入口)とは `eval-batch.lock`(ed_evalaudio の `_file_lock`)で重ならない
  - 話者の自動判別(v0.50.0): 文字起こしが終わると、その続きで判別のジョブが足される(ed_speakers.autodiar_after_transcribe。自分の印つき)。
    もう文字起こし済みで話者の無い評価用の文書(判別したことが無い = diar.json が無い)にも、見回りのたびに 1 本ずつ判別のジョブを足す(後追い)。
    文書ごとに 1 回だけ(状態の diar に記録)・直近に人が直した文書(ed_drill.DRILL_RECENT_SEC)は後回し・待ちの数は文字起こしと合わせて EB_MAX_WAIT まで
  - 未確認の評価用の作り直し(2026-10-04 ユーザー承認。whisper.cpp の時刻の 1 秒丸め・繰り返しを v0.51.0 で直す前に文字起こしした分):
    `POST api/eval-batch/redo {dryRun}`(eval_batch_redo)。「手つかず」(eb_redo_why が None)の評価用の文書を状態の redo.queue に入れ、
    見回り(_eb_redo_pass)が待ちの数の中で少しずつ、同じ文書 id のまま今の編集の設定で文字起こしし直す(spec の evalRedo・intoDoc。
    ed_jobs.run_job が始める直前(eb_redo_skip_at_start)と書く直前(eb_redo_fill)にもう一度確かめ、手が入っていたら書かずに飛ばす)。
    前の状態は履歴(hist_snapshot)に・前の機械の出力は recognition.runs の kind "evalRedo" に残す。話者は消して、評価用の自動の判別をもう一度かける
  - 1 本ずつの作り直し(2026-10-05 ユーザー要望): `POST api/eval-batch/redo-one {id, baseUpdatedAt, force?}`(eval_batch_redo_one)。
    開いている評価用の動画だけを、見回りを通さずすぐ待機列へ。人が手を入れた文書は force のときだけ(押したあとに直されたら書かない)

名前は serve.py からも見える(serve.py が部品の名前を集めるので、**ほかの部品と重ならないよう eb_ / EB_ / eval_batch_ を付ける**)。
ほかの部品は `ed_xxx.名前` で呼ぶたびに読む。
"""
import json
import os
import re
import threading

from ytt import fsio as _fsio  # noqa: E402
import ed_drill  # noqa: E402,F401
import ed_evalaudio  # noqa: E402,F401
import ed_jobs  # noqa: E402,F401
import ed_learn  # noqa: E402,F401
import ed_relink  # noqa: E402,F401
import ed_speakers  # noqa: E402,F401
import ed_state  # noqa: E402,F401
import ed_store  # noqa: E402,F401

EB_SCHEMA = "ytt-eval-batch/v1"
EB_FILE = "eval-batch.json"
EB_LOCK = "eval-batch.lock"
EB_MAX_WAIT = 2                  # 自分のジョブで、待っている・動いているものの上限(これを超えて入れない)
EB_FIRST_DELAY_SEC = 60          # 起動してから最初に見るまで(起動直後は文字起こしの準備・整理が重なるので待つ)
EB_INTERVAL_SEC = 30             # 見回る間隔(1 本の文字起こしは数分かかる。待ちが 1 件に減ったら補う)
EB_MAX_FAILS = 2                 # 同じ動画で失敗したら、あきらめる回数
EB_MAX_TRIES = 3                 # 同じ動画を入れる回数の上限(文字が 0 行のまま「文字のある文書」にならない動画を入れ直し続けない)
EB_DIAR_PER_TICK = 1             # 話者の判別の後追いを 1 回の見回りで入れる本数(文字起こしの待ちを埋めつくさない)
EB_STATE_MAX_BYTES = 8 * 1024 * 1024
EB_REDO_TIME_TOL = 0.005         # 作り直しの「手つかず」の判定: 行の時刻が機械の出力とこれ以内なら同じ(どちらも 0.01 秒に丸めてある)
EB_REDO_MAX_ITEMS = 5000
# 作り直さない理由(eb_redo_why)。EB_REDO_TOUCHED = 人が手を入れた(画面の「手を入れた n 本は残します」に数える)
EB_REDO_LABELS = {"proofed": "校正済みの行がある", "tags": "音のメモを付けた", "noOriginal": "比べる機械の出力が無い", "rows": "行を足した・消した・分けた",
                  "text": "文字を直した", "time": "時刻を直した", "speaker": "人が話者を選んだ・名前を変えた", "noSub": "字幕に出さない行がある",
                  "reviewed": "確かめ済み", "notTranscribed": "文字起こし前", "recent": "直近 10 分に開いた・直した", "busy": "処理中",
                  "noMedia": "動画が見つからない", "queued": "もう作り直し待ち", "changed": "作り直しの間に直された", "moved": "動画が変わった",
                  "not_found": "文書が無い", "broken": "文書を読めない", "stopped": "止めた",
                  "pressedChanged": "押したあとに直されたため"}   # 1 本ずつの作り直し(eval_batch_redo_one)で、押したあとに文書が変わった
EB_REDO_TOUCHED = ("proofed", "tags", "noSub", "noOriginal", "rows", "text", "time", "speaker")
EB_REDO_MACHINE_BY = ("threshold", "elimination", "context")   # diar.json の voices の by のうち、機械が名前を付けたもの(request = 依頼の名前は人の入力)
EB_UNTRANSCRIBED_RE = re.compile(r"_\d{2,4}_未文字起こし$")   # 評価用の整理の名前の規則(ed_relink._eval_name_re と同じ形)
_eb_state_lock = threading.RLock()   # 状態ファイルの読み書き・ジョブを足す瞬間(start / stop / 見回りが重ならない)
_eb_pass_lock = threading.Lock()     # 見回りは同時に1つ
_eb_one_lock = threading.Lock()      # 1 本ずつの作り直し: 確かめてからジョブを足すまで(同じ文書を2回押しても 1 本だけ)
_eb_wake = threading.Event()
_eb_halt = threading.Event()
_eb_threads = []


# ---------------------------------------------------------------- 置き場所・状態

def eb_path():
    """作業データの eval-batch.json(テストは設定の置き場所の隣)"""
    return os.path.join(os.path.dirname(ed_state.SETTINGS), EB_FILE)


def eb_lock_path():
    return os.path.join(os.path.dirname(ed_state.SETTINGS), EB_LOCK)


def eb_key(path):
    return ed_state.norm_path(str(path))


def _eb_empty():
    return {"schema": EB_SCHEMA, "enabled": False, "startedAt": None, "stoppedAt": None, "finishedAt": None, "enqueued": 0,
            "remaining": None, "deferred": None, "lastError": None, "lastAddedAt": None, "items": {}, "updatedAt": 0,
            "diar": {}, "diarRemaining": None,   # diar[文書の id] = {at, via, job?, state?, error?, skipped?}(話者の判別を試した = もう入れない。v0.50.0)
            # 作り直し待ち(eval_batch_redo)。queue = まだ入れていない文書の id(順番どおり)・items[id] = {at, job?, state?, skipped?, error?}
            "redo": {"queue": [], "items": {}, "requestedAt": None, "enqueued": 0}}


def eb_read():
    try:
        d = _fsio.read_json_file(eb_path(), EB_STATE_MAX_BYTES)
    except (OSError, UnicodeError, ValueError):
        return _eb_empty()
    if not isinstance(d, dict):
        return _eb_empty()
    out = _eb_empty()
    for k in out:
        if k in d and k not in ("schema", "items", "diar", "redo"):
            out[k] = d[k]
    if isinstance(d.get("items"), dict):
        out["items"] = {k: v for k, v in d["items"].items() if isinstance(v, dict)}
    if isinstance(d.get("diar"), dict):
        out["diar"] = {k: v for k, v in d["diar"].items() if isinstance(v, dict) and ed_state.TID_RE.match(str(k))}
    rd = d.get("redo") if isinstance(d.get("redo"), dict) else {}
    q = [t for t in rd.get("queue") or [] if isinstance(t, str) and ed_state.TID_RE.match(t)]
    out["redo"] = {"queue": list(dict.fromkeys(q))[:EB_REDO_MAX_ITEMS],
                   "items": {k: v for k, v in (rd.get("items") if isinstance(rd.get("items"), dict) else {}).items() if isinstance(v, dict) and ed_state.TID_RE.match(str(k))},
                   "requestedAt": rd.get("requestedAt"), "enqueued": int(rd.get("enqueued") or 0) if isinstance(rd.get("enqueued"), int) else 0}
    out["enabled"] = d.get("enabled") is True
    return out


def _eb_write(st):
    st["schema"] = EB_SCHEMA
    st["updatedAt"] = ed_state.now_ms()
    ed_state.atomic_write(eb_path(), json.dumps(st, ensure_ascii=False, indent=1).encode("utf-8"))


def _eb_jobs():
    """ジョブの表のコピー(表のロックは持ち続けない。add_job が同じロックを取る)"""
    with ed_jobs._jobs_lock:
        return list(ed_jobs._jobs.values())


def _eb_mine(j):
    return bool((j.get("spec") or {}).get("evalBatch"))


def _eb_auto_diar(j):
    """評価用の文書の自動の話者判別のジョブ(まとめての文字起こしが入れたものも、手で始めた評価用の文字起こしの続きも)"""
    sp = j.get("spec") or {}
    return j.get("kind") == "diarize" and bool(sp.get("auto")) and bool(sp.get("autoEval"))


# ---------------------------------------------------------------- 状態(GET /api/eval-batch)

def eval_batch_status():
    """-> {enabled, running(見回りのスレッドが動いている), enqueued(始めてから入れた本数), remaining(まだ入れていない本数。最後に調べたとき),
    active(自分のジョブで待っている・動いている件数), done, failed, finished(残りがなくなって止まった), startedAt, stoppedAt, finishedAt,
    deferred(増やさなかった理由), lastError}。ファイルは探さない(状態を読むだけ)"""
    st = eb_read()
    items = list(st["items"].values())
    jobs = _eb_jobs()
    mine = [j for j in jobs if _eb_mine(j) and j.get("state") in ed_jobs.ACTIVE_STATES]
    diar_active = sum(1 for j in jobs if _eb_auto_diar(j) and j.get("state") in ed_jobs.ACTIVE_STATES)
    diar_left = int(st.get("diarRemaining") or 0) if st["enabled"] else 0
    rd = st["redo"]
    redo_active = sum(1 for j in mine if (j.get("spec") or {}).get("evalRedo"))
    ritems = list(rd["items"].values())
    return {"redoWaiting": (len(rd["queue"]) if st["enabled"] else 0) + redo_active, "redoActive": redo_active,   # 未確認の評価用の作り直し
            "redoDone": sum(1 for i in ritems if i.get("state") == "done" and not i.get("skipped")),
            "redoSkipped": sum(1 for i in ritems if i.get("skipped")), "redoFailed": sum(1 for i in ritems if i.get("error") and not i.get("skipped")),
            "diarWaiting": diar_active + diar_left, "diarActive": diar_active, "diarTried": len(st.get("diar") or {}),   # 話者の判別 待ち(v0.50.0)
            "enabled": st["enabled"], "running": any(t.is_alive() for t in _eb_threads), "enqueued": int(st.get("enqueued") or 0),
            "remaining": st.get("remaining"), "active": len(mine), "done": sum(1 for i in items if i.get("done")),
            "failed": sum(1 for i in items if not i.get("done") and int(i.get("fails") or 0) >= EB_MAX_FAILS),
            "finished": bool(st.get("finishedAt")) and not st["enabled"], "startedAt": st.get("startedAt"), "stoppedAt": st.get("stoppedAt"),
            "finishedAt": st.get("finishedAt"), "deferred": st.get("deferred") if st["enabled"] else None, "lastError": st.get("lastError"),
            "titles": [str(j.get("title") or "")[:60] for j in mine]}


# ---------------------------------------------------------------- 始める・止める

def eb_require_ready():
    """まとめての文字起こしを動かせるか(評価用のフォルダが見えている・ffmpeg がある)。だめなら ApiError"""
    if not ed_relink.eval_dirs():
        raise ed_state.ApiError("no_eval_dirs", "評価用のフォルダが設定されていないか、見つかりません(⚙ の『評価用のフォルダ』を確かめてください)", 400)
    if not ed_state.find_ffmpeg():
        raise ed_state.ApiError("no_ffmpeg", "ffmpeg が見つかりません(README の準備手順を確認してください)", 400)


def eval_batch_start(req=None):
    """POST /api/eval-batch/start。評価用のフォルダが見えていて ffmpeg があれば enabled にして、見回りのスレッドを起こす(すぐに1回見回る)。
    もう enabled なら何も変えない(入れた数を数え直さない)。止めたあとの再開は、入れた数・失敗の記録を数え直す(失敗した動画もやり直す)"""
    eb_require_ready()
    with _eb_state_lock:
        st = eb_read()
        if not st["enabled"]:
            st = dict(_eb_empty(), enabled=True, startedAt=ed_state.now_ms())
            _eb_write(st)
            ed_state.log.info("評価用のまとめての文字起こしを始めました")
    eb_start_background()
    _eb_wake.set()
    return eval_batch_status()


def eval_batch_stop(req=None):
    """POST /api/eval-batch/stop。新しく入れるのをやめ、まだ始まっていない(待っている)自分のジョブを取り消す。
    動いている 1 本は(途中までの時間を捨てないよう)そのまま最後まで動かす"""
    with _eb_state_lock:
        st = eb_read()
        now = ed_state.now_ms()
        q = st["redo"]["queue"]
        if st["enabled"] or q:
            for tid in q:   # 作り直しの待ちも止める(もう一度作り直すときは、ボタンでもう一度数え直す)
                st["redo"]["items"][tid] = {"at": now, "skipped": "stopped"}
            st["redo"]["queue"] = []
            if st["enabled"]:
                st["enabled"], st["stoppedAt"], st["deferred"] = False, now, None
                ed_state.log.info("評価用のまとめての文字起こしを止めました")
            _eb_write(st)
    for j in _eb_jobs():   # enabled を外したあとなので、見回りがこの先で足すことはない
        if _eb_mine(j) and j.get("state") == "queued":
            j["evalBatchStop"] = True   # 自分で取り消したもの(ユーザーの取り消しと区別する)
            try:
                ed_jobs.cancel_job(j["id"])
            except ed_state.ApiError:
                pass
    return eval_batch_status()


# ---------------------------------------------------------------- 入れる動画を決める

def eb_scan():
    """評価用のフォルダの下の「評価用_仮置き」と「…_NN_未文字起こし」の動画 [パス](並びは名前順)"""
    out, seen = [], set()
    for root in ed_relink.eval_dirs():
        stg = os.path.join(root, ed_relink.EVAL_STAGING)
        for folder, names in sorted(ed_relink._eval_videos(root, skip_staging=False).items()):
            staged = _fsio.is_inside(folder, stg)
            for n in sorted(names):
                if not (staged or EB_UNTRANSCRIBED_RE.search(os.path.splitext(n)[0])):
                    continue
                p = os.path.join(folder, n)
                k = eb_key(p)
                if k not in seen:
                    seen.add(k)
                    out.append(p)
    return out


def eb_candidates(items, busy_paths=()):
    """入れる動画 [(パス, 入れ先の文書の id または None)]。除くもの = 文字のある文書がある・待っている/動いている(busy_paths)・
    済んだ・あきらめた(失敗 EB_MAX_FAILS 回・入れた回数 EB_MAX_TRIES 回)。
    文字の無い文書(「文字起こしせずに開いた」動画)だけがあるときは、その文書へ入れる(intoDoc。文書が2つにならない)"""
    paths = eb_scan()
    want = {eb_key(p) for p in paths}
    docs = {}
    for _tid, sm, sp in ed_store.summaries():
        if sp and eb_key(sp) in want:
            docs.setdefault(eb_key(sp), []).append(sm)
    out = []
    for p in paths:
        k = eb_key(p)
        it = items.get(k) or {}
        if k in busy_paths or it.get("done") or int(it.get("fails") or 0) >= EB_MAX_FAILS or int(it.get("tries") or 0) >= EB_MAX_TRIES:
            continue
        sms = docs.get(k, [])
        if any(s.get("rows") for s in sms):
            continue
        out.append((p, sorted(s["id"] for s in sms)[0] if sms else None))
    return out


def eb_diar_candidates(tried, busy=(), now=None):
    """話者の判別の後追いをする評価用の文書 -> ([文書の id](古く直した順), 直近に直したので後回しにした本数)。
    対象 = 評価用・文字のある行がある・確かめ済みでない・文字のある行に話者が 1 つも無い(人が付けたものを置き換えない)・
    判別したことが無い(diar.json が無い)・試していない(tried)・ジョブの最中でない(busy)・動画がある(ネットワーク上は調べずに除く)"""
    now = now or ed_state.now_ms()
    ready, recent = [], 0
    for tid, sm in ed_drill.drill_docs():
        if not sm.get("eval") or sm.get("reviewed") or not sm.get("rows") or sm.get("spkRows") or tid in tried or tid in busy:
            continue
        if os.path.exists(ed_speakers.diar_path(tid)):
            continue
        last = max(sm.get("updatedAt") or 0, sm.get("lastAt") or 0)
        if now - last < ed_drill.DRILL_RECENT_SEC * 1000:   # 編集の画面で開いているかもしれない(判別は編集を止める)
            recent += 1
            continue
        if not ed_drill._media_ok(sm.get("sourcePath")):
            continue
        ready.append((last, tid))
    return [t for _a, t in sorted(ready)], recent


def _eb_diar_pass(room, log):
    """後追いの判別を room 本まで(1 回の見回りで EB_DIAR_PER_TICK 本まで)入れる。-> (入れた本数, 残りの本数 or None = 調べなかった)"""
    if room <= 0 or not ed_speakers.autodiar_enabled() or not ed_speakers.autodiar_ready():
        return 0, None
    with _eb_state_lock:
        tried = set(eb_read().get("diar") or {})
    ready, recent = eb_diar_candidates(tried, ed_drill._busy_tids())
    added = 0
    for tid in list(ready):
        if added >= min(room, EB_DIAR_PER_TICK):
            break
        with _eb_state_lock:
            st = eb_read()
            if not st["enabled"]:
                return added, None
            rec = {"at": ed_state.now_ms(), "via": "backlog"}
            try:
                r = ed_speakers.autodiar_enqueue(tid, batch=True)
            except ed_state.ApiError as e:
                if e.code == "busy":   # 待機列がいっぱい・処理が重なった: 次の見回りで(試したことにしない)
                    break
                rec["error"] = e.message[:300]
                r = {}
            if r.get("job"):
                rec["job"] = r["job"]["id"]
                if r.get("name"):
                    rec["name"] = r["name"]
                added += 1
                log("話者の判別を入れました %s" % tid)
            elif r.get("skipped"):
                rec["skipped"] = r["skipped"]
            st.setdefault("diar", {})[tid] = rec
            ready.remove(tid)
            _eb_write(st)
    return added, len(ready) + recent


def eb_request(path, into):
    """validate_job に渡す要求: 編集の設定そのまま + 動画全体 + 評価用の印。ヒントは評価用の規則(validate_job の ev)で外れる"""
    req = dict(ed_learn.load_settings(), sourcePath=path, title="", start=0, end=None, evalSet=True)
    req.pop("intoDoc", None)
    if into:
        req["intoDoc"] = into
    return req


# ---------------------------------------------------------------- 見回る

def _eb_absorb(st, mine):
    """自分のジョブの結果を状態に写す(済んだ・失敗・取り消された)。同じジョブは1回だけ数える"""
    now = ed_state.now_ms()
    for j in mine:
        if j.get("kind") == "diarize":   # 話者の判別(文字起こしの続き・後追い): 結果を写し、試した文書として覚える(もう入れない)
            tid = str((j.get("spec") or {}).get("tid") or "")
            if tid and j.get("state") not in ed_jobs.ACTIVE_STATES:
                d = st.setdefault("diar", {}).setdefault(tid, {"at": now, "job": j.get("id"), "via": "transcribe"})
                if d.get("job") == j.get("id") and not d.get("state"):
                    d["state"] = j.get("state")
                    if j.get("error"):
                        d["error"] = str(j["error"])[:300]
            continue
        if (j.get("spec") or {}).get("evalRedo"):   # 作り直し: 結果は redo.items へ(動画の items には数えない = 新しい文字起こしの候補・失敗の数に混ぜない)
            tid = str((j.get("spec") or {}).get("tid") or "")
            rec = st["redo"]["items"].get(tid)
            if tid and j.get("state") not in ed_jobs.ACTIVE_STATES and isinstance(rec, dict) and rec.get("job") == j.get("id") and not rec.get("state"):
                rec["state"] = j.get("state")
                if j.get("redoSkipped"):
                    rec["skipped"] = j["redoSkipped"]
                if j.get("state") == "error":
                    rec["error"] = str(j.get("error") or "")[:300]
                    st["lastError"] = {"at": now, "src": os.path.basename(str(j["spec"].get("sourcePath") or "")), "message": rec["error"]}
            continue
        sp = (j.get("spec") or {}).get("sourcePath")
        if not sp or j.get("state") in ed_jobs.ACTIVE_STATES:
            continue
        it = st["items"].setdefault(eb_key(sp), {"src": sp, "tries": 0, "fails": 0, "failJobs": [], "done": False})
        if j.get("state") == "done":
            it["done"] = True
        elif j.get("id") not in it["failJobs"] and not j.get("evalBatchStop"):
            it["failJobs"] = (it["failJobs"] + [j.get("id")])[-10:]
            if j.get("state") == "error":
                it["fails"] = int(it.get("fails") or 0) + 1
                it["error"] = str(j.get("error") or "")[:300]
                st["lastError"] = {"at": now, "src": os.path.basename(sp), "message": it["error"]}
            else:   # 取り消された(ユーザーが): もう入れない
                it["fails"] = EB_MAX_FAILS
                it["error"] = "取り消されました"


def eb_tick(why="tick", log=None):
    """1回見回る。-> {added, remaining, deferred(増やさなかった理由)} か {skipped: 理由}。
    ユーザーのジョブが動いている・待っているときは増やさない。自分のジョブが EB_MAX_WAIT 件に満たなければ、その分だけ入れる"""
    log = log or (lambda m: ed_state.log.info("評価用のまとめての文字起こし: %s", m))
    if not eb_read()["enabled"]:
        return {"skipped": "stopped"}
    if not _eb_pass_lock.acquire(blocking=False):
        return {"skipped": "running"}
    try:
        with ed_evalaudio._file_lock(eb_lock_path()) as got:
            if not got:
                return {"skipped": "running"}
            return _eb_tick_locked(why, log)
    finally:
        _eb_pass_lock.release()


def _eb_tick_locked(why, log):
    jobs = _eb_jobs()
    active = [j for j in jobs if j.get("state") in ed_jobs.ACTIVE_STATES]
    mine_active = [j for j in active if _eb_mine(j)]
    others = [j for j in active if not _eb_mine(j)]
    busy_paths = {eb_key(sp) for sp in ((j.get("spec") or {}).get("sourcePath") for j in active) if sp}
    with _eb_state_lock:
        st = eb_read()
        if not st["enabled"]:
            return {"skipped": "stopped"}
        before = json.dumps(st, sort_keys=True)
        _eb_absorb(st, [j for j in jobs if _eb_mine(j)])
        if not ed_relink.eval_dirs():   # ドライブを外している間: 何もしない(終わったことにも、止めたことにもしない)
            st["deferred"] = "評価用のフォルダが見つかりません(ドライブを確かめてください)"
            res = {"skipped": "no_eval_dirs"}
        elif others:
            st["deferred"] = "ほかのジョブが動いています(終わるまで待ちます)"
            res = {"added": 0, "remaining": st.get("remaining"), "deferred": st["deferred"]}
        elif ed_relink._evalorg_lock.locked():
            st["deferred"] = "評価用のフォルダを整理中です"
            res = {"added": 0, "remaining": st.get("remaining"), "deferred": st["deferred"]}
        else:
            st["deferred"], res = None, None
        items_snapshot = json.loads(json.dumps(st["items"]))
        if json.dumps(st, sort_keys=True) != before:
            _eb_write(st)
    if res is not None:
        return res
    room = EB_MAX_WAIT - len(mine_active)
    diar_added, diar_left = _eb_diar_pass(room, log)   # 文字起こし済みで話者の無い評価用の文書の判別(後追い。v0.50.0)
    room -= diar_added
    if diar_left is not None:
        with _eb_state_lock:
            st = eb_read()
            if st["enabled"] and st.get("diarRemaining") != diar_left:
                st["diarRemaining"] = diar_left
                _eb_write(st)
    redo_added, redo_left = _eb_redo_pass(room, log)   # 未確認の評価用の作り直し(新しい動画の文字起こしより先に)
    room -= redo_added
    if room <= 0:   # 待ちが上限まで入っている: 動画を探さない(終わったら次の見回りで補う)
        return {"added": 0, "diarAdded": diar_added, "redoAdded": redo_added, "remaining": eb_read().get("remaining"), "deferred": None}
    cands = eb_candidates(items_snapshot, busy_paths)   # フォルダを歩く・文書の要約を読む(時間がかかるので、状態のロックの外で)
    added, rest = 0, list(cands)
    while rest and added < room:
        path, into = rest[0]
        try:
            spec = ed_jobs.validate_job(eb_request(path, into))
            err = None
        except ed_state.ApiError as e:   # 6 時間を超える・動画が壊れている・文書が変わった など。この動画は飛ばして次へ
            spec, err = None, e
        with _eb_state_lock:
            st = eb_read()
            if not st["enabled"]:   # 調べている間に止められた
                return {"added": added, "remaining": len(rest), "deferred": None}
            it = st["items"].setdefault(eb_key(path), {"src": path, "tries": 0, "fails": 0, "failJobs": [], "done": False})
            if err is not None:
                it["fails"], it["error"] = EB_MAX_FAILS, err.message[:300]
                st["lastError"] = {"at": ed_state.now_ms(), "src": os.path.basename(path), "message": err.message[:300]}
                log("飛ばします %s: %s" % (os.path.basename(path), err.message))
                rest.pop(0)
                _eb_write(st)
                continue
            spec["evalBatch"] = True   # 自分が入れたジョブの印(ユーザーのジョブと区別する)
            try:
                ed_jobs.add_job(spec)
            except ed_state.ApiError as e:   # 待機列がいっぱい(busy): 次の見回りで
                st["deferred"] = e.message
                _eb_write(st)
                return {"added": added, "remaining": len(rest), "deferred": e.message}
            it["tries"] = int(it.get("tries") or 0) + 1
            st["enqueued"] = int(st.get("enqueued") or 0) + 1
            st["lastAddedAt"] = ed_state.now_ms()
            rest.pop(0)
            added += 1
            _eb_write(st)
        log("入れました %s" % os.path.basename(path))
    with _eb_state_lock:
        st = eb_read()
        if not st["enabled"]:
            return {"added": added, "remaining": len(rest), "deferred": None}
        st["remaining"] = len(rest)
        if not rest and len(mine_active) + added + diar_added + redo_added == 0 and not diar_left and not redo_left and not st["redo"]["queue"]:
            # 残り(文字起こし・話者の判別・作り直し)がなく、動いているものもない: 終わり
            st["enabled"], st["finishedAt"] = False, ed_state.now_ms()
            log("終わりました(入れた %d 本・済 %d 本・飛ばした %d 本)" % (
                st["enqueued"], sum(1 for i in st["items"].values() if i.get("done")),
                sum(1 for i in st["items"].values() if not i.get("done") and int(i.get("fails") or 0) >= EB_MAX_FAILS)))
        _eb_write(st)
    return {"added": added, "diarAdded": diar_added, "redoAdded": redo_added, "remaining": len(rest), "deferred": None}


# ---------------------------------------------------------------- 未確認の評価用の作り直し(2026-10-04 ユーザー承認)

def _eb_speaker_why(tid, doc, segs):
    """話者が機械の付けたものだけか。-> None か "speaker"。
    話者が全部空 = 手つかず。話者があるなら、diar.json の最新が自動の判別(latest.auto)で、行ごとの話者がその割り当てのまま・
    使っている話者の名前が仮の名前(話者n)か、機械(覚えた声・消去法・動画の手がかり)が付けた名前のときだけ手つかず。
    人が始めた判別・「全行をこの人に」(single)・依頼の名前は、迷うので手を入れた側(作り直さない)"""
    used = {str(g.get("speaker")) for g in segs if g.get("speaker")}
    d = ed_speakers.read_diar(tid)
    latest = d.get("latest") if d else None
    if not used:
        # 全部空: 判別していない = 手つかず。ただし今の機械の出力より後の判別が今の行に話者を付けていたのに全部空 = 人が外した(手を入れた側)
        runs = [r for r in ((doc.get("recognition") or {}).get("runs") or []) if isinstance(r, dict) and not r.get("kind")] if isinstance(doc.get("recognition"), dict) else []
        made = ed_state.num(runs[0].get("at"), 0) or 0 if runs else 0
        if isinstance(latest, dict) and (ed_state.num(latest.get("at"), 0) or 0) > made:
            ids = {str(g.get("id")) for g in segs}
            rows = latest.get("rows") if isinstance(latest.get("rows"), dict) else {}
            if any(isinstance(r, dict) and r.get("speaker") and k in ids for k, r in rows.items()):
                return "speaker"
        return None
    if not isinstance(latest, dict) or not latest.get("auto") or (latest.get("engine") or {}).get("name") == "single":
        return "speaker"
    rows = latest.get("rows") if isinstance(latest.get("rows"), dict) else {}
    for g in segs:
        r = rows.get(str(g.get("id")))
        if str(g.get("speaker") or "") != str((r or {}).get("speaker") or ""):
            return "speaker"
    voices = (latest.get("voices") or {}).get("speakers") if isinstance(latest.get("voices"), dict) else None
    voices = voices if isinstance(voices, dict) else {}
    names = {str(s.get("id")): str(s.get("name") or "") for s in doc.get("speakers") or [] if isinstance(s, dict)}
    for sid in used:
        if sid not in names:
            return "speaker"
        nm = names[sid]
        if ed_speakers.DEFAULT_SPK_NAME.match(nm):
            continue
        v = voices.get(sid) if isinstance(voices.get(sid), dict) else {}
        if v.get("decided") == nm and v.get("by") in EB_REDO_MACHINE_BY:
            continue
        return "speaker"
    return None


def eb_redo_why(tid, doc, busy=(), now=None, media=True, recent=True):
    """作り直してよい(「手つかず」)なら None、そうでなければ理由(EB_REDO_LABELS のキー。評価用でなければ "notEval")。
    手つかず = 評価用・確かめ済み(evalReviewed)でない・文字起こし済み(model がある)・校正済みの行と音のメモが無い・
    segments と original が同じ(行の数・各行の start/end が EB_REDO_TIME_TOL 以内・文字が同じ)・話者は機械が付けたものだけ(_eb_speaker_why)・
    直近 ed_drill.DRILL_RECENT_SEC に更新・操作していない(updatedAt と effort.lastAt。recent=False で見ない = 1 本ずつの作り直しは開いている人が押す)・
    ジョブの最中でない(busy)・動画がある(media)。迷うものは手を入れた側に倒す(作り直さない)"""
    if not isinstance(doc, dict) or doc.get("evalSet") is not True:
        return "notEval"
    if isinstance(doc.get("evalReviewed"), dict):
        return "reviewed"
    segs = [g for g in doc.get("segments") or [] if isinstance(g, dict)]
    if not doc.get("model"):
        return "notTranscribed" if not segs else "noOriginal"
    if any(g.get("proofed") is True for g in segs):
        return "proofed"
    if any(g.get("tags") for g in segs):
        return "tags"
    if any(g.get("noSub") is True for g in segs):   # 字幕に出さない印は人が付けたもの(機械は付けない。2026-10-05)
        return "noSub"
    orig = doc.get("original")
    if not isinstance(orig, list) or not all(isinstance(o, dict) for o in orig):
        return "noOriginal"
    if len(orig) != len(segs):
        return "rows"
    if any(str(g.get("text") or "") != str(o.get("text") or "") for g, o in zip(segs, orig)):
        return "text"
    for g, o in zip(segs, orig):
        try:
            if abs(float(g["start"]) - float(o["start"])) > EB_REDO_TIME_TOL or abs(float(g["end"]) - float(o["end"])) > EB_REDO_TIME_TOL:
                return "time"
        except (KeyError, TypeError, ValueError):
            return "time"
    why = _eb_speaker_why(tid, doc, segs)
    if why:
        return why
    now = now or ed_state.now_ms()
    eff = doc.get("effort") if isinstance(doc.get("effort"), dict) else {}
    last = max(ed_state.num(doc.get("updatedAt"), 0) or 0, ed_state.num(eff.get("lastAt"), 0) or 0)
    if recent and now - last < ed_drill.DRILL_RECENT_SEC * 1000:
        return "recent"
    if tid in busy:
        return "busy"
    if media and not ed_drill._media_ok(doc.get("sourcePath")):
        return "noMedia"
    return None


def eb_redo_scan(busy=None, queued=(), now=None):
    """評価用の文書を全部見て -> ([作り直す文書の id](短い順), {理由: 本数})。評価用でない文書は数えない"""
    busy = ed_drill._busy_tids() if busy is None else busy
    now = now or ed_state.now_ms()
    out, reasons = [], {}
    for tid, sm, _sp in ed_store.summaries():
        if not sm.get("evalSet"):   # 要約(キャッシュ)で評価用でないものを先に除く(全部の文書を読み直さない)
            continue
        try:
            doc = ed_store.read_transcript(tid)
        except ed_state.ApiError as e:
            reasons[e.code] = reasons.get(e.code, 0) + 1
            continue
        why = "queued" if tid in queued else eb_redo_why(tid, doc, busy, now)
        if why == "notEval":
            continue
        if why:
            reasons[why] = reasons.get(why, 0) + 1
        else:
            out.append((float(sm.get("durationSec") or 0), tid))
    return [t for _d, t in sorted(out)], reasons


def eval_batch_redo(req=None):
    """POST /api/eval-batch/redo {dryRun}。dryRun(既定。押し間違いで作り直さない)= 数えるだけ:
    {targets, touched(人が手を入れたので残す本数), reasons{理由: 本数}, labels{理由: 説明}, touchedKeys, queued(もう待っている本数)}。
    dryRun が false なら対象を状態の redo.queue に足し、まとめての文字起こしを動かす(止まっていれば始める = start と同じ。見回りが少しずつ入れる)"""
    req = req if isinstance(req, dict) else {}
    dry = req.get("dryRun") is not False
    with _eb_state_lock:
        st = eb_read()
    queued = set(st["redo"]["queue"]) if st["enabled"] else set()
    targets, reasons = eb_redo_scan(ed_drill._busy_tids(), queued)
    res = {"dryRun": dry, "targets": len(targets), "touched": sum(reasons.get(k, 0) for k in EB_REDO_TOUCHED), "reasons": reasons,
           "labels": {k: EB_REDO_LABELS.get(k, k) for k in reasons}, "touchedKeys": list(EB_REDO_TOUCHED), "queued": len(queued), "added": 0}
    if dry:
        return res
    if targets:
        eb_require_ready()
        with _eb_state_lock:
            st = eb_read()
            if not st["enabled"]:   # 止まっていれば始める(start と同じ。入れた数・失敗の記録は数え直す)
                st = dict(_eb_empty(), enabled=True, startedAt=ed_state.now_ms())
                ed_state.log.info("評価用のまとめての文字起こしを始めました(作り直し)")
            q = st["redo"]["queue"]
            new = [t for t in targets if t not in q][:max(0, EB_REDO_MAX_ITEMS - len(q))]
            q.extend(new)
            for t in new:
                st["redo"]["items"].pop(t, None)   # 前の回の結果は消す(今回の結果を写す)
            st["redo"]["requestedAt"] = ed_state.now_ms()
            _eb_write(st)
        res["added"] = len(new)
        ed_state.log.info("評価用の作り直しを待ちに入れました: %d 本(残した %d 本)", len(new), res["touched"])
        eb_start_background()
        _eb_wake.set()
    res["status"] = eval_batch_status()
    return res


def eb_redo_spec(tid, doc):
    """作り直しの文字起こしの spec: 編集の設定そのまま + 評価用(ヒントなし)+ 文書の範囲(動画全体の文書は全体)。
    同じ文書へ入れる(intoDoc)・spec の tid = その文書(処理中の文書として、ドリル・付け替え・作り直しの判定が避ける)"""
    req = eb_request(str(doc.get("sourcePath") or ""), None)
    if not doc.get("whole"):
        req.update(start=ed_state.num(doc.get("start"), 0.0) or 0.0, end=ed_state.num(doc.get("end")))
    spec = ed_jobs.validate_job(req)
    spec.update(intoDoc=tid, tid=tid, evalSet=True, evalBatch=True, evalRedo={"queuedAt": ed_state.now_ms()},
                title=(str(doc.get("title") or "") or spec["title"])[:120])
    return spec


def _eb_redo_pass(room, log):
    """作り直し待ちを room 本まで入れる。入れる直前にもう一度「手つかず」を確かめ、手が入っていれば飛ばす(待ちから外して記録)。
    -> (入れた本数, 残りの本数)"""
    added = 0
    while added < room:
        with _eb_state_lock:
            st = eb_read()
            q = st["redo"]["queue"]
            if not st["enabled"] or not q:
                return added, len(q)
            tid = q[0]
            rec = {"at": ed_state.now_ms()}
            try:
                doc = ed_store.read_transcript(tid)
                why = eb_redo_why(tid, doc, ed_drill._busy_tids())
            except ed_state.ApiError as e:
                doc, why = None, e.code
            spec = None
            if not why:
                try:
                    spec = eb_redo_spec(tid, doc)
                except ed_state.ApiError as e:   # 動画が壊れている・6 時間を超える など: この文書は飛ばす
                    rec["error"] = e.message[:300]
                    st["lastError"] = {"at": rec["at"], "src": os.path.basename(str(doc.get("sourcePath") or "")), "message": rec["error"]}
            if spec is not None:
                try:
                    job = ed_jobs.add_job(spec)
                except ed_state.ApiError as e:   # 待機列がいっぱい(busy): 次の見回りで(待ちに残す)
                    st["deferred"] = e.message
                    _eb_write(st)
                    return added, len(q)
                rec["job"] = job["id"]
                st["redo"]["enqueued"] = int(st["redo"].get("enqueued") or 0) + 1
                added += 1
            elif why:
                rec["skipped"] = why
            q.pop(0)
            st["redo"]["items"][tid] = rec
            if len(st["redo"]["items"]) > EB_REDO_MAX_ITEMS:   # 古い記録から捨てる
                for k in sorted(st["redo"]["items"], key=lambda k: st["redo"]["items"][k].get("at") or 0)[:len(st["redo"]["items"]) - EB_REDO_MAX_ITEMS]:
                    st["redo"]["items"].pop(k, None)
            _eb_write(st)
        log("作り直しを入れました %s" % tid if spec is not None else "作り直しを飛ばしました %s: %s" % (tid, rec.get("skipped") or rec.get("error")))
    with _eb_state_lock:
        return added, len(eb_read()["redo"]["queue"])


# ---------------------------------------------------------------- 1 本ずつの作り直し(2026-10-05 ユーザー要望)
# 評価ドリルで校正しながら、文字起こしの後処理の調整(行の終わりなど)の効き目を 1 本ずつ確かめるため、開いている評価用の動画だけを今の設定で作り直す。
# まとめての文字起こしの見回り・待ちの数(EB_MAX_WAIT)を通さず、ユーザーが押したジョブとしてすぐ待機列へ(まとめての文字起こしが止まっていても動く)。
# spec に evalBatch の印は付けない(ユーザーのジョブ = まとめての文字起こしはこの間増やさない・止めるで取り消されない)。evalRedo の one・force・base が印

def _eb_touched_rows(doc, why):
    """人が手を入れた行の数(作り直しで置き換わる直し。画面の確認に出す): 校正済み・音のメモ・機械の出力(original)に同じ文字・時刻の行が無い・
    (理由が話者のとき)話者が付いている行"""
    orig = doc.get("original") if isinstance(doc.get("original"), list) else []
    keys = set()
    for o in orig:
        if isinstance(o, dict):
            try:
                keys.add((str(o.get("text") or ""), round(float(o["start"]), 2), round(float(o["end"]), 2)))
            except (KeyError, TypeError, ValueError):
                pass
    n = 0
    for g in doc.get("segments") or []:
        if not isinstance(g, dict):
            continue
        try:
            k = (str(g.get("text") or ""), round(float(g["start"]), 2), round(float(g["end"]), 2))
        except (KeyError, TypeError, ValueError):
            k = None
        if g.get("proofed") is True or g.get("tags") or g.get("noSub") is True or k not in keys or (why == "speaker" and g.get("speaker")):
            n += 1
    return n


def eval_batch_redo_one(req=None):
    """POST /api/eval-batch/redo-one {id, baseUpdatedAt, force?}。開いている評価用の動画 1 本を、今の編集の設定ですぐ作り直す(待機列へ)。
    断る: 評価用でない 400 not_eval・確かめ済み 400 reviewed・文字起こし前 400 not_transcribed・baseUpdatedAt が無い 400 / 違う 409 conflict・
    ジョブの最中 409 busy・動画が無い 400 no_file。人が手を入れた文書(eb_redo_why が EB_REDO_TOUCHED)は force: true のときだけ
    (無ければ 409 touched と {why, label, rows(直した行の数), total(行の数)} = 画面の確認に使う)。直近に開いた・直した(recent)は見ない。
    -> {"ok", "job"(public_job), "forced"}。書く前の確かめ直しは eb_redo_skip_at_start・eb_redo_fill(force なら「押したときの updatedAt のまま」だけ)"""
    req = req if isinstance(req, dict) else {}
    tid = str(req.get("id") or "")
    force = req.get("force") is True
    with _eb_one_lock:
        doc = ed_store.read_transcript(tid)
        if doc.get("evalSet") is not True:
            raise ed_state.ApiError("not_eval", "評価用の文字起こしではありません(1 本ずつの作り直しは評価用の動画だけです)", 400)
        if isinstance(doc.get("evalReviewed"), dict):
            raise ed_state.ApiError("reviewed", "確かめ済みの動画は作り直せません。先に確かめ済みを取り消してください", 400)
        if not doc.get("model"):
            raise ed_state.ApiError("not_transcribed", "まだ文字起こししていません(作り直しは文字起こし済みの動画だけです)", 400)
        b = req.get("baseUpdatedAt")
        if ed_state.plain_int(b) is None:
            raise ed_state.ApiError("bad_request", "baseUpdatedAt(読み込んだときの版)を付けてください", 400)
        if b != doc.get("updatedAt"):
            raise ed_state.ApiError("conflict", "この文字起こしは別の所(別の画面・再認識・話者判別など)で先に変わりました。読み込み直してから、もう一度押してください", 409)
        if tid in ed_drill._busy_tids():
            raise ed_state.ApiError("busy", "この文字起こしは処理中です(話者判別などが終わってから、もう一度押してください)", 409)
        if not ed_drill._media_ok(doc.get("sourcePath")):
            raise ed_state.ApiError("no_file", "動画が見つかりません(動画を選び直してから、もう一度押してください)", 400)
        why = eb_redo_why(tid, doc, media=False, recent=False)
        if why and why not in EB_REDO_TOUCHED:
            raise ed_state.ApiError(why, "作り直せません(%s)" % EB_REDO_LABELS.get(why, why), 400)
        if why and not force:
            raise ed_state.ApiError("touched", "この動画は人が手を入れています(%s)。作り直すと置き換わります" % EB_REDO_LABELS.get(why, why), 409,
                                    {"why": why, "label": EB_REDO_LABELS.get(why, why), "rows": _eb_touched_rows(doc, why),
                                     "total": sum(1 for g in doc.get("segments") or [] if isinstance(g, dict) and str(g.get("text") or "").strip())})
        if not ed_state.find_ffmpeg():
            raise ed_state.ApiError("no_ffmpeg", "ffmpeg が見つかりません(README の準備手順を確認してください)", 400)
        spec = eb_redo_spec(tid, doc)
        spec.pop("evalBatch", None)
        spec["evalRedo"] = {"queuedAt": ed_state.now_ms(), "one": True, "force": force, "base": doc.get("updatedAt"), "why": why}
        job = ed_jobs.add_job(spec)
    ed_state.log.info("評価用の動画 1 本を作り直します%s: %s", "(手を入れた分を置き換える: %s)" % why if why else "", tid)
    return {"ok": True, "job": ed_jobs.public_job(job), "forced": bool(why)}


def _eb_one_why(tid, doc, red, busy=(), media=True):
    """1 本ずつの作り直しのジョブ(evalRedo.one)の確かめ直し: 押したときの updatedAt(base)から変わっていない(変わっていれば pressedChanged)。
    force でなければ、さらに今の「手つかず」の決まり(直近に開いた・直した は見ない)"""
    if doc.get("updatedAt") != red.get("base"):
        return "pressedChanged"
    if red.get("force"):
        return None
    return eb_redo_why(tid, doc, busy, media=media, recent=False)


def _eb_redo_skipped(job, why):
    job["redoSkipped"] = why
    ed_jobs.job_done(job, job["spec"].get("tid"), "作り直しませんでした(%s)" % EB_REDO_LABELS.get(why, why))


def eb_redo_skip_at_start(job):
    """作り直しのジョブ(spec の evalRedo)が動き出すとき(ed_jobs.run_job の最初)にもう一度「手つかず」を確かめる。
    手が入っていたら「完了(作り直しませんでした)」にして True。手つかずなら、書く直前の比べのために今の updatedAt を覚えて False。
    1 本ずつの作り直し(evalRedo.one)は押したときの updatedAt(base)のまま比べる(_eb_one_why)"""
    spec = job["spec"]
    tid = str(spec.get("tid") or "")
    red = spec.get("evalRedo") if isinstance(spec.get("evalRedo"), dict) else {}
    with ed_jobs._jobs_lock:
        busy = {str((j.get("spec") or {}).get("tid") or j.get("tid") or "") for j in ed_jobs._jobs.values()
                if j is not job and j.get("state") in ed_jobs.ACTIVE_STATES}
    try:
        doc = ed_store.read_transcript(tid)
        why = _eb_one_why(tid, doc, red, busy) if red.get("one") else eb_redo_why(tid, doc, busy)
    except ed_state.ApiError as e:
        doc, why = None, e.code
    if why:
        _eb_redo_skipped(job, why)
        ed_state.log.info("評価用の作り直しを飛ばしました(%s): %s", why, tid)
        return True
    if not red.get("one"):
        spec["evalRedo"] = dict(red, base=doc.get("updatedAt"))
    return False


def eb_redo_fill(job, spec, fields):
    """作り直しの結果を同じ文書に書く(ed_jobs.run_job が fill_doc の代わりに呼ぶ。保存のロックの中)。-> 文書の id か None(書かなかった)。
    書く直前にもう一度確かめる: 動画が同じ・始めたときから更新されていない(updatedAt)・まだ手つかず(認識の間に開いた = effort.lastAt も含む)。
    前の状態は履歴に(以前の版に戻すで戻せる)・前の機械の出力は recognition.runs の kind "evalRedo"(replaced = 前の original・replacedRun = 前の最初の認識の記録)。
    新しい最初の認識の記録を runs の先頭に(kind の無い記録 = 今の original を作った認識。D1-b・測る道具が読む)。
    話者・判別の印(diarization)・確かめ済みの印は消す(話者は run_job の続きの自動の判別がもう一度付ける)。id・題名・作った日・clip・評価用の印・校正の手間・編集の内容はそのまま"""
    tid = str(spec.get("tid") or spec.get("intoDoc") or "")
    red = spec.get("evalRedo") if isinstance(spec.get("evalRedo"), dict) else {}
    base = red.get("base")
    with ed_store._save_lock:
        try:
            doc = ed_store.read_transcript(tid)
        except ed_state.ApiError as e:
            _eb_redo_skipped(job, e.code)
            return None
        if ed_state.norm_path(str(doc.get("sourcePath") or "")) != ed_state.norm_path(spec["sourcePath"]):
            why = "moved"
        elif red.get("one"):   # 1 本ずつの作り直し: 押したときのまま(force なら手を入れた分も置き換える)
            why = _eb_one_why(tid, doc, red, media=False)
        elif base is not None and doc.get("updatedAt") != base:
            why = "changed"
        else:
            why = eb_redo_why(tid, doc, media=False)
        if why:
            _eb_redo_skipped(job, why)
            ed_state.log.info("評価用の作り直しを書きませんでした(%s): %s", why, tid)
            return None
        ed_store.snapshot(tid)   # 作り直す前を「以前の版に戻す」に残す
        old_rec = doc.get("recognition") if isinstance(doc.get("recognition"), dict) else {}
        old_first = [r for r in old_rec.get("runs") or [] if isinstance(r, dict) and not r.get("kind")]
        a = float(spec.get("start") or 0)
        b = ed_state.num(spec.get("end")) or ed_state.num(spec.get("duration")) or max([ed_state.num(o.get("end"), 0.0) or 0.0 for o in doc.get("original") or []] + [a + 0.01])
        ed_jobs.record_rerun(doc, spec, "evalRedo", [[a, max(b, a + 0.01)]], [dict(o) for o in doc.get("original") or [] if isinstance(o, dict)])
        runs = doc["recognition"]["runs"]
        if old_first and runs and runs[-1].get("kind") == "evalRedo":
            runs[-1]["replacedRun"] = old_first[0]
        doc.update(fields)
        doc["recognition"] = dict(old_rec, runs=list(fields["recognition"]["runs"]) + [r for r in runs if r.get("kind")])
        for k in ("diarization", "evalReviewed", "resplit"):
            doc.pop(k, None)
        doc["evalSet"] = True
        ed_store.apply_edit_cuts(tid, doc)
        ed_store.write_doc(tid, doc)
    ed_state.log.info("評価用の文書を作り直しました: %s(%d 行)", tid, len(fields.get("segments") or []))
    return tid


# ---------------------------------------------------------------- 裏のスレッド

def eb_start_background(first_delay=EB_FIRST_DELAY_SEC, interval=EB_INTERVAL_SEC):
    """見回りの裏のスレッド(serve.py の prepare から1回。start でも確かめる)。enabled でなければ何もしない(30 秒ごとに状態を読むだけ)。
    start が起こすとすぐに見回る。環境変数 TRANSCRIBE_EVAL_BATCH=off で始めない"""
    if ed_state.env_off("TRANSCRIBE_EVAL_BATCH") or any(t.is_alive() for t in _eb_threads):
        return None
    _eb_halt.clear()

    def loop():
        delay = first_delay
        while not _eb_halt.is_set():
            _eb_wake.wait(delay)
            if _eb_halt.is_set():
                break
            _eb_wake.clear()
            try:
                if eb_read()["enabled"]:
                    eb_tick("background")
            except Exception:
                ed_state.log.exception("評価用のまとめての文字起こしの見回りに失敗")
            delay = interval

    t = threading.Thread(target=loop, daemon=True, name="eval-batch")
    _eb_threads[:] = [t]
    t.start()
    return t


def eb_shutdown():
    """裏のスレッドを止める(テスト用)"""
    _eb_halt.set()
    _eb_wake.set()
    for t in list(_eb_threads):
        t.join(5)
    _eb_threads.clear()
    _eb_wake.clear()
