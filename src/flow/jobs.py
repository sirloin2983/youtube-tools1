"""ジョブの表・待機列・種類の登録・ワーカーの繰り返し・取り消しの受付(② 管理。役割で組み直す RS6 a-2。2026-10-10 に ytt/jobs から移した)。

重い処理の枠(HeavySlots・SLOTS・WAIT_MESSAGE)・中止の例外 Cancelled・中止の確かめ check_cancel は ① の部品も使うので ytt/jobs に残る(ここは ytt.jobs を読む)。
SLOTS を差し替えるテストは ytt.jobs.SLOTS を差し替える(ここは呼ぶたびに _slots.SLOTS を読む)。
"""
import contextlib
import json
import logging
import os
import tempfile
import threading
import time
import uuid

from ytt import errors, fsio, tools
from ytt import jobs as _slots

# ---------- ジョブの表・待機列・ワーカーの繰り返し・取り消し・登録の口(RS2-1b で編集の ed_jobs から ytt/jobs へ・RS6 a-2 で ytt から flow へ) ----------
# 1 つのプロセスに 1 つの表 = 下の Table の既定インスタンス TX_TABLE(OPT2 後半 J8。ファイルの末尾で作る。_jobs・_jobs_lock はその表と錠の別名)。
# 種類(kind)ごとの本体・優先度・同時に入れない組・文書の id を持つか・やり直せるかは register で登録する(登録するのは app = 編集の serve.py。下の層は自分で登録しない)。
# 編集だけの値(記録の書き先・起動中の印・一時フォルダ・待機の上限・やり直せない理由)は configure で渡す(ytt は編集の部品を読まない)。
# 状態(state)・段階(phase)の文字は画面(編集の app-jobs.js)が読むので変えない(loading・extracting は走らせる本体が入れる)。
# 編集の部品・テストは今までどおり ed_jobs.名前 / S.名前 で読み書きできる(ed_jobs の転送 _MOVED と serve の名前の受付)。
JOB_RUNNERS = {}     # 種類 → 本体 run(job)
JOB_PRIORITY = {}    # 種類 → 優先度(登録しない種類は 1。数値が小さいほど先に実行。話者判別は文字起こしの待機列を追い越す = 実行中は中断せず次の空きで割り込む)
EXCLUSIVE = {}       # 種類 → 同じ文書に同時に入れない種類(入口の検査 validate_* と add_job の両方がこの表を使う)
RETRY_KINDS = ()     # [やり直す] で同じ指定のまま入れ直せる種類
TID_KINDS = set()    # job["tid"] に spec["tid"](文書の id)を入れる種類
ACTIVE_STATES = ("queued", "loading", "extracting", "running")   # Table の active_states(解析などの TABLE_ACTIVE より loading・extracting が多い)
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
    if "tool" in kw:
        TX_TABLE.tool = kw["tool"]


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


def _admit(active, spec, kind):
    """Table の受け入れの検査(add と同じロックの中): 待っている・動いている数の上限と、同じ文書に同時に入れない種類"""
    cap = _conf["max_queue"]()
    if len(active) >= cap:
        raise errors.ApiError("busy", "待機中のジョブが多すぎます(最大%d件)" % cap, 429)
    excl = EXCLUSIVE.get(kind)
    if excl and spec.get("tid") and _busy_locked(spec["tid"], excl):
        # validate_* でも確かめているが、確認と登録の間に同じ要求が割り込めたので、登録と同じロックの中でもう一度確かめる
        raise errors.ApiError("busy", "この文字起こしは、すでに別の処理(話者判別・再認識・比較)の最中です", 409)


def add_job(spec, kind="transcribe"):
    return TX_TABLE.add(spec, kind, title=spec["title"], extra={
        "progress": 0.0, "tid": spec["tid"] if kind in TID_KINDS else None, "segments": 0, "speakers": 0, "unsure": 0,
        "device": "", "cancel": False, "proc": None})


def worker():
    """ジョブを 1 本ずつ動かす糸の本体(app が別スレッドで起こす。戻らない)。待機列が 60 秒空いたら idle()(長く使っていないモデルを手放す など)"""
    TX_TABLE.lane()


def work_one(jid):
    """待っているジョブ 1 つをこの糸で動かす(糸の中身と同じ。テスト・同期の呼び出し用)"""
    TX_TABLE.run_one(jid)


def cancel_job(jid):
    with _jobs_lock:
        job = TX_TABLE.find(jid)
        if job is None:
            raise errors.ApiError("not_found", "ジョブが見つかりません", 404)
        job["cancel"] = True
        TX_TABLE.cancel(jid)   # ctl に伝え、待ちなら「中止しました」で終える
    p = job.get("proc")
    if p and p.poll() is None:
        try:
            p.terminate()
        except OSError:
            pass


def _tx_start(job):
    sp = job.get("spec") or {}
    _conf["mark"]({"id": job["id"], "kind": job.get("kind", "transcribe"), "model": sp.get("model", ""), "title": str(sp.get("title", ""))[:60], "at": int(time.time())})


def _tx_run(job, ctl):
    log, kind, sp = _conf["log"], job.get("kind", "transcribe"), job.get("spec") or {}
    t0 = time.time()
    log.info("ジョブ開始 %s %s モデル=%s(メモリ %s)", kind, job["id"], sp.get("model", ""), tools.memory_label())
    JOB_RUNNERS[kind](job)
    log.info("ジョブ終了 %s %s 状態=%s %.0f秒(メモリ %s)%s", kind, job["id"], job["state"], time.time() - t0, tools.memory_label(), (" エラー: " + str(job.get("error"))) if job.get("error") else "")


def _tx_fail(job, e):
    _conf["log"].exception("ワーカーで例外")   # 想定外でもワーカーは止めない(止まると、以後のジョブが動かないまま待機列に残る)
    set_internal_error(job, e)
    return INTERNAL_MSG


def _tx_after(job):
    _conf["after"]()
    _conf["mark"](None)


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
        return [board_job(j) for j in _jobs.values()]


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


# ---------- ② の 1 つの器 Table(OPT2 後半 J6。notes:docs/design/opt2-jobs-plan.md の 3) ----------
# 解析 an(flow/batch.Batch)・書き出し ex(flow/export.ExportJobs)・パック pk(flow/packjobs.PackJobs)が同じコードの上に乗る。
# 積む・lanes 本の糸で古い順に動かす・重い処理の枠 SLOTS・状態・取り消し・やり直し・履歴 keep・busy・掲示板への写しはここ 1 か所。
# 種類ごとの違い(受け入れの規則 admit・kind・title・本体 run・掲示板の形 board_job など)は引数。① の中身は書かない(run は呼び手が渡す)。
# 記録(rec)は辞書: id・kind・spec・title・state(queued・running・done・error・cancelled・skipped)・phase・progress・error・result・ctl(ytt/jobs.Ctl)・
# notes(ctl.note の覚え書き)・waiting(枠を待っている)・createdAt・startedAt・finishedAt(ミリ秒)・fseq(終わった順)・interrupted + 呼び手の extra。
# 編集の tx(上のモジュール関数)も J8 で、ファイルの末尾の既定インスタンス TX_TABLE に載せた(積む・糸・取り消し・履歴は Table。優先度・active_states・run_state などは引数)。
TABLE_ACTIVE = ("queued", "running")
TABLE_FINAL = ("done", "error", "cancelled", "skipped")


def _now_ms():
    return int(time.time() * 1000)


def _default_progress(rec, frac, message):
    if frac is not None:
        rec["progress"] = frac
    if message is not None:
        rec["phase"] = message


def _default_fail(rec, e):
    if isinstance(e, errors.ApiError):
        return e.message
    return "内部エラー: %s %s" % (e.__class__.__name__, str(e)[:200])


class Table:
    """種類ごとに 1 インスタンスのジョブの器(② 管理)。
    prefix: 掲示板の頭(an・ex・pk)。tool: SLOTS の名前。kinds: 受ける種類(先頭が既定)。
    run(rec, ctl) -> 結果: 本体(① の呼び出し)。取り消しは cancelled_exc の例外か ctl を見て返す。想定外の例外は fail(rec, e) の値を error にする。
    admit(active, spec, kind): 入れられないとき ApiError を上げる(cv を持って呼ぶ)。title(spec, kind) -> 題。keep: 覚えておく終わった記録の数。
    lanes: 糸の数。slot(rec) -> SLOTS の札の文字(None なら枠を取らない)。make_ctl(on_progress, on_note) -> Ctl。on_progress(rec, frac, message)。
    before(rec): 動かす直前(cv の中)。(state, error, phase) を返せば動かさずに終える。on_start(rec): 動き出した直後(cv の外)。
    on_finish(rec): 終わりの状態を入れた直後(cv の中)。phases: 終わりの状態 -> phase の文(無ければ今のまま)。
    drop_state: 待ちの記録を取り消したときの状態。interrupt_phase: 終了の流れで止めたときの phase。retryable: やり直せる状態。
    board_job(rec) -> 掲示板の Job の辞書。log(text): 想定外の失敗の記録。
    (J8)active_states: 待ち・動いている状態(既定 queued・running。編集は loading・extracting も)。priority(rec): 小さいほど先に動かす(同じなら入れた順)。
    run_state: 糸が動かし始めるときに入れる状態(None なら変えない = 走らせる本体が自分で入れる。編集)。autostart: add・retry で糸を起こすか(False なら lane() を呼ぶ側が起こす)。
    after(rec): 1 つ動かし終えるごと(cv の外)。idle_after 秒 待ちが無ければ on_idle()。kinds が空なら種類は縛らない"""

    def __init__(self, prefix, tool, *, run, kinds=("job",), admit=None, title=None, keep=30, lanes=1, slot=None, make_ctl=None,
                 on_progress=None, fail=None, cancelled_exc=(errors.Cancelled,), before=None, on_start=None, on_finish=None,
                 phases=None, drop_state="cancelled", interrupt_phase=None, retryable=(), board_job=None, log=None,
                 messages=None, active_states=TABLE_ACTIVE, priority=None, run_state="running", autostart=True, after=None,
                 idle_after=None, on_idle=None):
        self.prefix, self.tool, self.kinds = prefix, tool, tuple(kinds)
        self.active_states, self.priority, self.run_state, self.autostart = tuple(active_states), priority, run_state, autostart
        self.after, self.idle_after, self.on_idle = after, idle_after, on_idle
        self.run, self.admit, self.title_of = run, admit, title
        self.keep, self.lanes = keep, max(1, int(lanes))
        self.slot_of, self.make_ctl = slot, make_ctl or (lambda on_progress, on_note: _slots.Ctl(on_progress=on_progress, on_note=on_note))
        self.on_progress = on_progress or _default_progress
        self.fail, self.cancelled_exc = fail or _default_fail, tuple(cancelled_exc)
        self.before, self.on_start, self.on_finish = before, on_start, on_finish
        self.phases, self.drop_state, self.interrupt_phase = dict(phases or {}), drop_state, interrupt_phase
        self.retryable, self.board_job = tuple(retryable), board_job
        self.log = log or (lambda text: None)
        self.messages = {"missing": "その処理は見つかりません", "closing": "終了しているところです。起動し直してから入れてください",
                         "no_retry": "この処理はやり直せません"}
        self.messages.update(messages or {})
        self.cv = threading.Condition(threading.RLock())   # 呼び手の印(before・on_finish)の中から表を読み直せるよう RLock
        self.jobs = {}   # id -> 記録(入れた順。やり直しは末尾へ)
        self.closing = False
        self._fseq = 0
        self._threads = []

    # ---- 糸 ----
    def start(self):
        """糸を lanes 本だけ起こす(何度呼んでも増えない)。add・retry が呼ぶ(テストは差し替えて糸を起こさないこともできる)"""
        with self.cv:
            while len(self._threads) < self.lanes:
                th = threading.Thread(target=self.lane, daemon=True, name="%s-lane%d" % (self.prefix, len(self._threads)))
                self._threads.append(th)
                th.start()

    def lane(self):
        """糸の本体(戻らない)。autostart が False の器は、呼ぶ側が自分のスレッドで呼ぶ"""
        while True:
            with self.cv:
                rec = self._next_locked()
                if rec is not None:
                    self._begin(rec)
            if rec is None:
                if self.on_idle:
                    try:
                        self.on_idle()
                    except Exception as e:   # noqa: BLE001  (手放しの失敗で糸を止めない)
                        self.log("idle で例外: %s" % e)
                continue
            self.work(rec)

    _lane = lane

    def _begin(self, rec):
        """動かし始める印(cv の中)"""
        if self.run_state:
            rec["state"] = self.run_state
        rec["startedAt"] = _now_ms()

    def queue_order(self):
        """待ちの記録を動かす順に(priority の小さい順・同じなら入れた順)"""
        with self.cv:
            queued = [r for r in self.jobs.values() if r["state"] == "queued"]
            return sorted(queued, key=self.priority) if self.priority else queued

    def _next_locked(self):
        """次に動かす記録(cv の中)。idle_after 秒 待っても無ければ None"""
        while True:
            order = [] if self.closing else self.queue_order()
            if not order:
                if self.idle_after:
                    if not self.cv.wait(self.idle_after):
                        return None
                else:
                    self.cv.wait()
                continue
            rec = order[0]
            stop = self.before(rec) if self.before else None
            if not stop:
                return rec
            self.finish(rec, *stop)

    def run_one(self, jid):
        """待ちの記録 1 つを、糸を通さずこの呼び出しの中で動かす(糸の中身と同じ。テスト・同期の呼び出し)-> 動かしたか"""
        with self.cv:
            rec = self.find(jid)
            if rec is None or rec["state"] != "queued":
                return False
            stop = self.before(rec) if self.before else None
            if stop:
                self.finish(rec, *stop)
                return False
            self._begin(rec)
        self.work(rec)
        return True

    def work(self, rec):
        """1 つの記録を動かす(糸の中身): 枠を待つ → run(rec, ctl) → 終わりの状態。想定外の失敗でも「実行中」のまま残さない"""
        ctl = self._ctl(rec)
        state, err, result = "done", None, None
        try:
            if self.on_start:
                self.on_start(rec)
            label = self.slot_of(rec) if self.slot_of else None
            if label is None:
                result = self.run(rec, ctl)
            else:
                prev = rec.get("phase", "")
                with _slots.SLOTS.slot(self.tool, label, cancelled=ctl.is_cancelled,
                                       on_wait=lambda: rec.update(waiting=True, phase=_slots.WAIT_MESSAGE)) as ok:
                    if rec.get("waiting"):
                        rec.update(waiting=False, phase=prev)
                    if ok:
                        result = self.run(rec, ctl)
                    else:
                        state = "cancelled"
        except self.cancelled_exc:
            state = "cancelled"
        except Exception as e:   # noqa: BLE001  (想定外でも糸を止めない = 次の記録へ続ける)
            state = "error"
            try:
                err = self.fail(rec, e)
            except Exception:   # noqa: BLE001
                err = _default_fail(rec, e)
        try:
            self.finish(rec, state, err, result=result)
        finally:
            if self.after:
                try:
                    self.after(rec)
                except Exception as e:   # noqa: BLE001  (後始末の失敗で糸を止めない)
                    self.log("after で例外: %s" % e)

    # ---- 記録 ----
    def _new(self, spec, kind, title, extra):
        rec = {"id": uuid.uuid4().hex[:12], "kind": kind, "spec": spec, "title": title, "state": "queued", "phase": "順番待ち",
               "progress": None, "error": None, "result": None, "notes": {}, "waiting": False, "createdAt": _now_ms(),
               "startedAt": None, "finishedAt": None, "fseq": 0, "interrupted": False}
        rec.update(extra or {})
        self._ctl(rec)
        return rec

    def _ctl(self, rec):
        """記録の Ctl(無ければ作る = 呼び手が辞書を直に表へ入れた記録も扱える)"""
        ctl = rec.get("ctl")
        if ctl is None:
            ctl = rec["ctl"] = self.make_ctl(lambda frac, msg: self.on_progress(rec, frac, msg), rec.setdefault("notes", {}).__setitem__)
            if hasattr(ctl, "bind"):
                ctl.bind(rec)
        return ctl

    def _put(self, rec):
        self.jobs[rec["id"]] = rec
        self._trim()
        self.cv.notify_all()

    def active(self):
        with self.cv:
            return [r for r in self.jobs.values() if r["state"] in self.active_states]

    def add(self, spec, kind=None, *, title=None, extra=None, prepare=None):
        """記録を積む -> 記録。入れられなければ admit の ApiError・終了のあとは closing(503)。
        prepare() は受け入れの検査のあと(同じロックの中)に呼ぶ。返した辞書は extra に足す(ApiError を上げれば入れない)"""
        kind = kind or (self.kinds[0] if self.kinds else None)
        if self.kinds and kind not in self.kinds:
            raise ValueError("知らない種類です: %r" % (kind,))
        with self.cv:
            if self.closing:
                raise errors.ApiError("closing", self.messages["closing"], 503)
            if self.admit:
                self.admit(self.active(), spec, kind)
            extra = dict(extra or {})
            if prepare:
                extra.update(prepare() or {})
            if title is None:
                title = self.title_of(spec, kind) if self.title_of else ""
            rec = self._new(spec, kind, title, extra)
            self._put(rec)
        if self.autostart:
            self.start()
        return rec

    def find(self, jid):
        return self.jobs.get(str(jid or ""))

    def get(self, jid):
        rec = self.find(jid)
        if rec is None:
            raise errors.ApiError("not_found", self.messages["missing"], 404)
        return rec

    def list(self):
        with self.cv:
            return list(self.jobs.values())

    def finish(self, rec, state, error=None, phase=None, result=None):
        """終わりの状態を入れる(糸・取り消し・終了の流れ・呼び手の印から)。もう終わっている記録は変えない"""
        with self.cv:
            if rec["state"] in TABLE_FINAL:
                if not rec.get("fseq"):   # 走らせる本体が自分で終わりの状態を入れた記録(編集)にも、終わった順と時刻を付ける
                    self._fseq += 1
                    rec["fseq"] = self._fseq
                    if rec.get("finishedAt") is None:
                        rec["finishedAt"] = _now_ms()
                    self._trim()
                    self.cv.notify_all()
                return
            if state == "cancelled" and rec.get("interrupted"):
                error = error or rec.get("interruptReason")
                phase = phase or self.interrupt_phase
            self._fseq += 1
            rec.update(state=state, error=error, waiting=False, fseq=self._fseq, finishedAt=_now_ms())
            rec["phase"] = phase or self.phases.get(state) or rec.get("phase", "")
            if result is not None:
                rec["result"] = result
            if self.on_finish:
                self.on_finish(rec)
            self._trim()
            self.cv.notify_all()

    def _trim(self):
        fin = sorted((r for r in self.jobs.values() if r["state"] in TABLE_FINAL), key=lambda r: r.get("fseq", 0))
        for old in fin[:max(0, len(fin) - self.keep)]:
            self.jobs.pop(old["id"], None)

    # ---- 操作 ----
    def cancel(self, jid):
        """取り消し: 待ちは drop_state で終える・実行中は ctl に中止を伝える(終わりは糸が入れる)・終わった物は何もしない -> 記録"""
        with self.cv:
            rec = self.get(jid)
            if rec["state"] in self.active_states:
                self._ctl(rec).cancel()
            if rec["state"] == "queued":
                self.finish(rec, self.drop_state)
        return rec

    def retry(self, jid, prepare=None):
        """やり直し: 同じ指定で新しい記録を末尾に入れる(前の記録は消す)-> 新しい記録。retryable の外は bad_state(409)・入れられなければ admit の ApiError"""
        with self.cv:
            if self.closing:   # add と同じく、終了のあとは新しい待ちの記録を作らない(待ち列が動かないまま残るのを防ぐ)
                raise errors.ApiError("closing", self.messages["closing"], 503)
            old = self.get(jid)
            if old["state"] not in self.retryable:
                raise errors.ApiError("bad_state", self.messages["no_retry"], 409)
            if self.admit:
                self.admit(self.active(), old["spec"], old["kind"])
            extra = dict(prepare(old) or {}) if prepare else {}
            rec = self._new(dict(old["spec"]), old["kind"], old["title"], extra)
            self.jobs.pop(old["id"], None)
            self._put(rec)
        if self.autostart:
            self.start()
        return rec

    def cancel_all(self, reason=None):
        """終了の流れ: 待ちは中止で終え、実行中は中止を伝える(待たない)。どちらも interrupted の印。-> 止めた記録の一覧"""
        with self.cv:
            recs = [r for r in self.jobs.values() if r["state"] in self.active_states]
            for r in recs:
                r["interrupted"] = True
                if reason:
                    r["interruptReason"] = reason
                self._ctl(r).cancel()
                if r["state"] == "queued":
                    self.finish(r, "cancelled")
            self.cv.notify_all()
        return recs

    def shutdown(self, reason=None):
        """cancel_all に加えて、これより後は新しく入れない・待ちを始めない"""
        with self.cv:
            self.closing = True
            return self.cancel_all(reason)

    def busy(self, pred=None):
        with self.cv:
            return any(r["state"] in self.active_states and (pred is None or pred(r)) for r in self.jobs.values())

    def wait(self, pred, timeout=None):
        with self.cv:
            return self.cv.wait_for(pred, timeout)

    def clear(self, finished_only=True):
        """終わった記録を消す -> 消した数。finished_only=False なら全部(動いている物には中止を伝える。テスト用)"""
        with self.cv:
            gone = [r for r in self.jobs.values() if not finished_only or r["state"] in TABLE_FINAL]
            for r in gone:
                self.jobs.pop(r["id"], None)
                if r["state"] in self.active_states:
                    self._ctl(r).cancel()
            return len(gone)

    # ---- 掲示板(flow/board.py。頭 prefix・器の中の id) ----
    def board_jobs(self):
        """掲示板の引く形: 記録(入れた順)-> [Job]"""
        with self.cv:
            return [self.board_job(r) for r in self.jobs.values()]

    def board_cancel(self, jid):
        """掲示板の取り消し。無い id は LookupError・終わっていれば ValueError"""
        rec = self.find(jid)
        if rec is None:
            raise LookupError(self.messages["missing"])
        if rec["state"] not in self.active_states:
            raise ValueError("その処理は終わっています")
        self.cancel(jid)

    def board_retry(self, jid, prepare=None):
        """掲示板のやり直し -> 新しい記録の Job。無い id は LookupError・やり直せなければ ValueError"""
        try:
            rec = self.retry(jid, prepare)
        except errors.ApiError as e:
            raise (LookupError if e.status == 404 else ValueError)(e.message)
        with self.cv:
            return self.board_job(rec)

    def attach_board(self, board, retry=None):
        """掲示板に頭 prefix で載せる(引く形・取り消し。retryable があればやり直しも。retry で差し替えられる)"""
        if retry is None and self.retryable:
            retry = self.board_retry
        board.register(self.prefix, source=self.board_jobs, cancel=self.board_cancel, retry=retry)


# ---------- 編集のジョブ(tx)の既定インスタンス(OPT2 後半 J8) ----------
# 上の Table に載せた 1 つの表。種類の本体は JOB_RUNNERS(register)から呼ぶたびに引く。走らせる本体(① の呼び出し)は job の辞書を直に書く(state の loading・extracting・done・error も本体が入れる)。
# 記録は今までの job の辞書に ctl・notes などを足した形(public_job が写す欄だけ画面へ出るので /api/jobs の応答は変わらない)。
# 糸は app が worker() を別スレッドで呼んで起こす(autostart=False = 入れただけでは動かない。テストは work_one で 1 つずつ動かす)。


class _FlagCtl(_slots.Ctl):
    """編集のジョブの Ctl: 記録の "cancel"(走らせる本体が job["cancel"] で直に見る旗)も取り消しとして見る"""
    job = None

    def bind(self, rec):
        self.job = rec

    @property
    def cancelled(self):
        return self.cancel_event.is_set() or bool(self.job and self.job.get("cancel"))

    def is_cancelled(self):
        return self.cancelled

    def check(self):
        if self.cancelled:
            raise self.exc()


TX_TABLE = Table("tx", "jobs", run=_tx_run, kinds=(), admit=_admit, keep=100, lanes=1, slot=lambda rec: str((rec.get("spec") or {}).get("title", ""))[:60],
                 make_ctl=lambda on_progress, on_note: _FlagCtl(on_progress=on_progress, on_note=on_note), fail=_tx_fail, cancelled_exc=(),
                 before=lambda rec: ("cancelled", None, "中止しました") if rec.get("cancel") else None, on_start=_tx_start, after=_tx_after,
                 phases={"cancelled": "中止しました"}, board_job=lambda rec: board_job(rec), run_state=None, autostart=False,
                 active_states=ACTIVE_STATES, priority=lambda rec: JOB_PRIORITY.get(rec.get("kind"), 1), idle_after=60,
                 on_idle=lambda: _conf["idle"](), messages={"missing": "ジョブが見つかりません"})
_jobs = TX_TABLE.jobs       # 表(辞書。入れた順)。呼び手・テストは中身を直に読み書きする(辞書そのものは差し替えない)
_jobs_lock = TX_TABLE.cv    # 表の錠
