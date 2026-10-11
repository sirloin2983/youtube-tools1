"""ジョブの表・待機列・種類の登録・ワーカーの繰り返し・取り消しの受付(② 管理。役割で組み直す RS6 a-2。2026-10-10 に ytt/jobs から移した)。

重い処理の枠(HeavySlots・SLOTS・WAIT_MESSAGE)・中止の例外 Cancelled・中止の確かめ check_cancel は ① の部品も使うので ytt/jobs に残る(ここは ytt.jobs を読む)。
SLOTS を差し替えるテストは ytt.jobs.SLOTS を差し替える(ここは呼ぶたびに _slots.SLOTS を読む)。
"""
import contextlib
import itertools
import json
import logging
import os
import queue
import tempfile
import threading
import time
import uuid

from ytt import errors, fsio, tools
from ytt import jobs as _slots

# ---------- ジョブの表・待機列・ワーカーの繰り返し・取り消し・登録の口(RS2-1b で編集の ed_jobs から ytt/jobs へ・RS6 a-2 で ytt から flow へ) ----------
# 1 つのプロセスに 1 つの表(今は編集のジョブだけが使う)。種類(kind)ごとの本体・優先度・同時に入れない組・文書の id を持つか・やり直せるかは
# register で登録する(登録するのは app = 編集の serve.py。下の層は自分で登録しない)。編集だけの値(記録の書き先・起動中の印・一時フォルダ・待機の上限・
# やり直せない理由)は configure で渡す(ytt は編集の部品を読まない)。状態(state)・段階(phase)の文字は画面(編集の app-jobs.js)が読むので変えない。
# 編集の部品・テストは今までどおり ed_jobs.名前 / S.名前 で読み書きできる(ed_jobs の転送 _MOVED と serve の名前の受付)。
_jobs = {}
_order = []
_jobs_lock = threading.Lock()
_queue = queue.PriorityQueue()   # (優先度, 通し番号, jid)。話者判別は文字起こしの待機列を追い越せるよう優先度を分ける(実行中のジョブを中断はしない。次の空きで割り込む)
_seq_counter = itertools.count()
JOB_RUNNERS = {}     # 種類 → 本体 run(job)
JOB_PRIORITY = {}    # 種類 → 優先度(登録しない種類は 1。数値が小さいほど先に実行)
EXCLUSIVE = {}       # 種類 → 同じ文書に同時に入れない種類(入口の検査 validate_* と add_job の両方がこの表を使う)
RETRY_KINDS = ()     # [やり直す] で同じ指定のまま入れ直せる種類
TID_KINDS = set()    # job["tid"] に spec["tid"](文書の id)を入れる種類
ACTIVE_STATES = ("queued", "loading", "extracting", "running")
INTERNAL_MSG = "処理が途中で止まりました"   # 想定外の失敗の決まった文(例外の名前・原文は errorDetail へ。画面は「詳しく」に畳む。UI の見直し M9)
_conf = {"tool": "jobs", "log": logging.getLogger("ytt.jobs"), "tmp_dir": tempfile.gettempdir, "max_queue": lambda: 200,
         "mark": lambda info: None, "after": lambda: None, "idle": lambda: None, "no_retry": lambda: ()}


def configure(**kw):
    """使う側の値を渡す(app が読み込みのときに 1 回)。tool = SLOTS の名前・log = 記録の logger・tmp_dir() = 一時の wav の置き場所・
    max_queue() = 待機できる最大件数・mark(info | None) = 起動中の印(ジョブの開始と終わり)・after() = ジョブの終わりごと・
    idle() = 待機列が 60 秒空いたとき・no_retry() = 同じ指定ではまた失敗する理由の code の並び。呼ぶたびに読む物は関数で渡す"""
    bad = set(kw) - set(_conf)
    if bad:
        raise TypeError("知らない設定: %s" % ", ".join(sorted(bad)))
    _conf.update(kw)


def tool_slot(label, cancelled=None):
    """SLOTS の札を configure の tool(使う側のツールの名前)で取る(with で使う)。ツールの ID を知らない下の層の部品が、
    ジョブの外の重い処理(たたき台の無音の検出など)の順番を待つため(RS3-E5a。human/proof/store の「行から」)"""
    return _slots.SLOTS.slot(_conf["tool"], label, cancelled=cancelled)


def register(kind, run, priority=1, exclusive=(), has_tid=False, retry=False):
    """ジョブの種類を登録する(app が読み込みのときに)。run(job) = 本体(テストの差し替えが効くよう、呼ぶたびに読む lambda を渡す)。
    priority = 待機列の優先度・exclusive = 同じ文書に同時に入れない種類・has_tid = job["tid"] に文書の id を入れる・retry = [やり直す] で入れ直せる"""
    global RETRY_KINDS
    JOB_RUNNERS[kind] = run
    JOB_PRIORITY[kind] = priority
    if exclusive:
        EXCLUSIVE[kind] = tuple(exclusive)
    if has_tid:
        TID_KINDS.add(kind)
    if retry and kind not in RETRY_KINDS:
        RETRY_KINDS += (kind,)


def set_cancelled(job, phase="中止しました"):
    job["state"], job["phase"] = "cancelled", phase


def set_internal_error(job, e):
    """想定外の失敗を job に入れる: 本文は決まった文、原文(例外の名前と文)は errorDetail(画面に直接出さない)。"""
    job["state"], job["error"], job["phase"] = "error", INTERNAL_MSG, "失敗"
    job["errorDetail"], job["internal"] = "%s: %s" % (e.__class__.__name__, str(e)[:200]), True


@contextlib.contextmanager
def job_errors(job, wav=None, cancelled="中止しました", log=None):
    """ジョブの本体の失敗を job の状態にする(取り消し = cancelled・ApiError = その理由・想定外 = 内部エラー。ワーカーは止めない)。
    wav = 終わったら消す一時ファイル。log = 想定外の失敗を記録に残すときの文"""
    try:
        yield
    except errors.Cancelled:
        set_cancelled(job, cancelled)
    except errors.ApiError as e:
        job["state"], job["error"], job["phase"] = "error", e.message, "失敗"
        job["errorCode"] = e.code
        if e.extra.get("detail"):
            job["errorDetail"] = str(e.extra["detail"])[:300]   # 内部の名前・原文は「詳しく」の中だけ(UI の見直し S12)
    except Exception as e:
        if log:
            _conf["log"].exception(log)
        set_internal_error(job, e)
    finally:
        if wav:
            fsio.unlink_quiet(wav)


@contextlib.contextmanager
def job_temp_wav(job, cancelled="中止しました", log=None):
    """ジョブの本体を job_errors で囲み、一時の wav のパス(tmp_dir()/<ジョブの id>.wav。フォルダは作ってから)を渡す。終わったら wav を消す"""
    tmp = _conf["tmp_dir"]()
    wav = os.path.join(tmp, job["id"] + ".wav")
    with job_errors(job, wav, cancelled, log):
        os.makedirs(tmp, exist_ok=True)
        yield wav


def job_done(job, tid, phase="完了"):
    job["tid"], job["progress"], job["state"], job["phase"] = tid, 1.0, "done", phase


def job_title(prefix, doc):
    """文書へのジョブの題名(処理状況の一覧): 「話者判別: 」などの頭 + 文書の題名(100 字まで。無ければ「無題」)"""
    return prefix + (str(doc.get("title") or "") or "無題")[:100]


def _busy_locked(tid, kinds):
    """_jobs_lock を持った中で: その文書に kinds の種類のジョブが待っている・動いているか"""
    return any(j.get("kind") in kinds and j["spec"].get("tid") == tid and j["state"] in ACTIVE_STATES for j in _jobs.values())


def tid_busy(tid, kinds):
    """その文書に、kinds の種類のジョブが待っている・動いているか(同じ文書に同時に入れない組み合わせ = EXCLUSIVE。add_job も同じロックの中で確かめ直す)"""
    with _jobs_lock:
        return _busy_locked(tid, kinds)


def can_retry(j):
    return j["state"] == "error" and j["kind"] in RETRY_KINDS and j.get("errorCode") not in _conf["no_retry"]()


def retry_job(jid):
    """失敗した処理を、同じ指定でもう一度待機列に入れる(画面の [やり直す]。UI の見直し M9)-> 新しい job"""
    with _jobs_lock:
        j = _jobs.get(str(jid or ""))
        if not j:
            raise errors.ApiError("not_found", "その処理は見つかりません。画面を読み込み直してください", 404)
        if not can_retry(j):
            raise errors.ApiError("bad_state", "この処理は、同じ指定ではやり直せません(失敗した文字起こしのうち、指定を変えなくてよいものだけ)", 409)
        kind, spec = j["kind"], j["spec"]
        try:
            spec = json.loads(json.dumps(spec, ensure_ascii=False))   # 前の job と指定を共有しない
        except (TypeError, ValueError):
            spec = dict(spec)
    return add_job(spec, kind)


def add_job(spec, kind="transcribe"):
    with _jobs_lock:
        waiting = sum(1 for j in _jobs.values() if j["state"] in ACTIVE_STATES)
        cap = _conf["max_queue"]()
        if waiting >= cap:
            raise errors.ApiError("busy", "待機中のジョブが多すぎます(最大%d件)" % cap, 429)
        excl = EXCLUSIVE.get(kind)
        if excl and spec.get("tid") and _busy_locked(spec["tid"], excl):
            # validate_* でも確かめているが、確認と登録の間に同じ要求が割り込めたので、登録と同じロックの中でもう一度確かめる
            raise errors.ApiError("busy", "この文字起こしは、すでに別の処理(話者判別・再認識・比較)の最中です", 409)
        jid = uuid.uuid4().hex[:12]
        job = {"id": jid, "title": spec["title"], "state": "queued", "phase": "順番待ち", "progress": 0.0, "tid": spec["tid"] if kind in TID_KINDS else None, "error": None,
               "segments": 0, "speakers": 0, "unsure": 0, "kind": kind, "device": "", "createdAt": int(time.time() * 1000), "cancel": False, "proc": None, "spec": spec}
        _jobs[jid] = job
        _order.append(jid)
        while len(_order) > 100:
            old = _order.pop(0)
            if _jobs.get(old, {}).get("state") not in ACTIVE_STATES:
                _jobs.pop(old, None)
            else:
                _order.insert(0, old)
                break
        _queue.put((JOB_PRIORITY.get(kind, 1), next(_seq_counter), jid))
    return job


def worker():
    """ジョブを 1 本ずつ動かすスレッドの本体(app が起動する)。待機列が 60 秒空いたら idle()(長く使っていないモデルを手放す など)"""
    while True:
        try:
            _priority, _seq, jid = _queue.get(timeout=60)
        except queue.Empty:
            _conf["idle"]()
            continue
        work_one(jid)


def work_one(jid):
    job = _jobs.get(jid)
    log = _conf["log"]
    try:
        if job and job["state"] == "queued" and not job["cancel"]:
            sp = job.get("spec") or {}
            job["startedAt"] = int(time.time() * 1000)
            info = {"id": job["id"], "kind": job.get("kind", "transcribe"), "model": sp.get("model", ""), "title": str(sp.get("title", ""))[:60], "at": int(time.time())}
            _conf["mark"](info)
            t0 = time.time()
            # 重い処理の同時実行数の上限(入口の中では他のツールの解析・書き出しと順番を待つ。上の SLOTS)
            with _slots.SLOTS.slot(_conf["tool"], info["title"], cancelled=lambda: job["cancel"],
                            on_wait=lambda: job.update(phase=_slots.WAIT_MESSAGE)) as ok:
                if not ok:
                    set_cancelled(job)
                    return
                log.info("ジョブ開始 %s %s モデル=%s(メモリ %s)", info["kind"], info["id"], info["model"], tools.memory_label())
                JOB_RUNNERS[info["kind"]](job)
            log.info("ジョブ終了 %s %s 状態=%s %.0f秒(メモリ %s)%s", info["kind"], info["id"], job["state"], time.time() - t0, tools.memory_label(), (" エラー: " + str(job.get("error"))) if job.get("error") else "")
        elif job and job["state"] == "queued":
            set_cancelled(job)
    except Exception as e:   # 想定外でもワーカーを止めない(止まると、以後のジョブが動かないまま待機列に残る)
        log.exception("ワーカーで例外")
        if job:
            set_internal_error(job, e)
    finally:
        if job and job["state"] not in ACTIVE_STATES:
            job.setdefault("finishedAt", int(time.time() * 1000))
        _conf["after"]()
        _conf["mark"](None)


def cancel_job(jid):
    job = _jobs.get(str(jid))
    if not job:
        raise errors.ApiError("not_found", "ジョブが見つかりません", 404)
    job["cancel"] = True
    if job["state"] == "queued":
        set_cancelled(job)
        job.setdefault("finishedAt", int(time.time() * 1000))
    p = job.get("proc")
    if p and p.poll() is None:
        try:
            p.terminate()
        except OSError:
            pass


# ---------- ② のジョブの掲示板に見せる(RS8 の ② の口 S2。flow/board.py。器の本体と今の API(/api/jobs など)は変えない) ----------
# 掲示板の kind の語彙(board.KINDS)に載せる写し: 文字起こし・話者(声を覚えるも)・それ以外の作り直し(再認識・疑わしい所・比較・30fps・字幕・サムネ)。仮の分け方
BOARD_KIND = {"transcribe": "transcribe", "diarize": "diarize", "voice-learn": "diarize"}
BOARD_STATE = {"queued": "queued", "loading": "running", "extracting": "running", "running": "running", "done": "done", "error": "error", "cancelled": "cancelled"}


def board_job(j):
    """編集のジョブ 1 つ -> 掲示板の Job(id = "tx:<ジョブの id>")。表の中身は読むだけ"""
    state = BOARD_STATE.get(j["state"], "running")
    active = state in ("queued", "running")
    err = None
    if j.get("error"):
        err = {"code": j.get("errorCode"), "text": str(j["error"]), "detail": j.get("errorDetail") or None}
    return {"id": "tx:" + j["id"], "kind": BOARD_KIND.get(j.get("kind"), "rerun"), "target": {"docId": j["tid"]} if j.get("tid") else {},
            "title": j.get("title") or "", "state": state, "phase": j.get("phase") or "", "progress": j.get("progress"),
            "waiting": state == "queued" or j.get("phase") == _slots.WAIT_MESSAGE, "createdAt": j.get("createdAt"),
            "startedAt": j.get("startedAt"), "finishedAt": j.get("finishedAt"), "error": err,
            "canCancel": active, "canRetry": can_retry(j)}


def board_jobs():
    """表の今のジョブ(入れた順)を掲示板の Job に(引く形の source)"""
    with _jobs_lock:
        return [board_job(_jobs[i]) for i in _order if i in _jobs]


def board_cancel(jid):
    """掲示板の cancel(器の中の id)。無い id は LookupError"""
    try:
        cancel_job(jid)
    except errors.ApiError as e:
        raise LookupError(e.message)


def board_retry(jid):
    """掲示板の retry。-> 入れ直した新しい Job。できなければ ValueError・無ければ LookupError"""
    try:
        return board_job(retry_job(jid))
    except errors.ApiError as e:
        if e.status == 404:
            raise LookupError(e.message)
        raise ValueError(e.message)


def attach_board(board):
    """掲示板(flow/board.Board)に頭 tx で載せる(app が 1 回)。やり直し(retry)は RETRY_KINDS の失敗だけ(can_retry)"""
    board.register("tx", source=board_jobs, cancel=board_cancel, retry=board_retry)
