"""重い処理の同時実行数の上限(統合計画の段階4)。

入口(start.bat)の中では3つのツールが1つのプロセスで動くので、ここの SLOTS をみんなで使う:
  スタジオの解析・書き出し、文字起こし(認識は別プロセスのワーカーだが、ジョブの順番はここで待つ)、cut2resolve のパック作成。
上限を超えた処理は、先に来た順に待つ(待っている間も取り消せる)。ツールを単独で起動したときは、そのツールの中だけの上限になる。
上限は環境変数 YTT_MAX_HEAVY_JOBS(1〜8。既定 2)。

用途つきの枠(線 D の M6。2026-10-07): 上限とは別に、決まった用途(tool の名前)だけが使える枠 RESERVED を持つ。
今は「ライブの書き出し(tool "live")に 1 つ」だけ。使うのは呼ぶ側が acquire(…, reserved=True) を渡したとき = **録画中だけ**
(src/home/live_export.py。録画が終わったら普通の枠で順番を待つ)。文字起こし 2 本で上限が埋まっていても、配信中のライブの書き出しは待たされない。
普通の枠が空いていれば、先に来た順のまま普通の枠を使う(用途つきの枠は、普通の枠が埋まっているときだけ・同じ用途の中では先に来た順)。
値は仮(U4 = 本物の 3 時間の配信の値が出たら決め直す。plan/line-d-auto-pack.md の M6)。snapshot の active の行には、用途つきの枠なら extra: true が付く

使い方:
    with jobs.SLOTS.slot("transcribe", "配信タイトル", cancelled=lambda: job["cancel"], on_wait=lambda: ...) as ok:
        if ok:
            ...重い処理...
        # ok が False = 待っている間に取り消された
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

from . import errors, fsio, tools

DEFAULT_LIMIT = 2
MAX_LIMIT = 8
WAIT_MESSAGE = "他のツールの処理が終わるのを待っています"
RESERVED = {"live": 1}   # 用途つきの枠(M6。仮の値): 録画中のライブの書き出しに、上限とは別に 1 つ


def limit_from_env(env=None):
    env = os.environ if env is None else env
    try:
        n = int(str(env.get("YTT_MAX_HEAVY_JOBS") or DEFAULT_LIMIT).strip())
    except ValueError:
        return DEFAULT_LIMIT
    return min(MAX_LIMIT, max(1, n))


class HeavySlots:
    def __init__(self, limit=None, reserved=None):
        """reserved: 用途つきの枠 {tool: 数}(None = RESERVED。{} = 持たない)"""
        self.limit = limit or limit_from_env()
        src = RESERVED if reserved is None else reserved
        self.reserved = {str(k): min(MAX_LIMIT, max(0, int(v))) for k, v in src.items()}
        self._cv = threading.Condition()
        self._seq = itertools.count(1)
        self._active = {}    # token -> {"tool", "label", "since", "extra"(用途つきの枠)}
        self._waiting = []   # [token](先に来た順)
        self._info = {}      # token -> {"tool", "label", "since", "reserved"(用途つきの枠を使ってよい)}(待っている間)

    def _grant(self, token, info):
        """-> "normal"(上限の中の枠)・"extra"(用途つきの枠)・None(まだ待つ)。呼ぶのは self._cv を持っている間"""
        normal = sum(1 for a in self._active.values() if not a.get("extra"))
        if self._waiting[0] == token and normal < self.limit:
            return "normal"
        if info.get("reserved"):
            tool = info["tool"]
            used = sum(1 for a in self._active.values() if a.get("extra") and a["tool"] == tool)
            first = next((t for t in self._waiting if self._info.get(t, {}).get("reserved") and self._info[t]["tool"] == tool), None)
            if used < self.reserved.get(tool, 0) and first == token:   # 同じ用途の中では先に来た順
                return "extra"
        return None

    def acquire(self, tool, label="", cancelled=None, on_wait=None, poll=0.5, reserved=False):
        """空くまで待って番号(token)を返す。待っている間に cancelled() が真になれば None。
        on_wait: 待ち始めたときに1回だけ呼ぶ(画面に「待っています」を出す用)。
        reserved: True なら、普通の枠が埋まっているとき tool の用途つきの枠(RESERVED)も使う(M6。ライブの書き出しの録画中だけ)"""
        cancelled = cancelled or (lambda: False)
        token = next(self._seq)
        info = {"tool": str(tool), "label": str(label)[:80], "since": time.time(),
                "reserved": bool(reserved) and self.reserved.get(str(tool), 0) > 0}
        waited = False
        with self._cv:
            self._waiting.append(token)
            self._info[token] = info
            try:
                while True:
                    kind = self._grant(token, info)
                    if kind:
                        break
                    if cancelled():
                        return None
                    if not waited:
                        waited = True
                        if on_wait:
                            try:
                                on_wait()
                            except Exception:
                                pass
                    self._cv.wait(poll)
                self._active[token] = {"tool": info["tool"], "label": info["label"], "since": time.time(), "extra": kind == "extra"}
                return token
            finally:
                self._waiting.remove(token)
                self._info.pop(token, None)
                self._cv.notify_all()

    def release(self, token):
        if token is None:
            return
        with self._cv:
            self._active.pop(token, None)
            self._cv.notify_all()

    @contextlib.contextmanager
    def slot(self, tool, label="", cancelled=None, on_wait=None, poll=0.5, reserved=False):
        token = self.acquire(tool, label, cancelled, on_wait, poll, reserved)
        try:
            yield token is not None
        finally:
            self.release(token)

    def snapshot(self):
        """{"limit", "active": [{"tool", "label", "seconds", "extra"?}], "waiting": [...]}(入口の画面用。extra: true = 用途つきの枠を使っている)"""
        now = time.time()
        with self._cv:
            act = [dict(tool=i["tool"], label=i["label"], seconds=int(now - i["since"]), **({"extra": True} if i.get("extra") else {}))
                   for i in self._active.values()]
            wait = [dict(tool=self._info[t]["tool"], label=self._info[t]["label"], seconds=int(now - self._info[t]["since"]))
                    for t in self._waiting if t in self._info]
        return {"limit": self.limit, "active": act, "waiting": wait}


SLOTS = HeavySlots()   # プロセスに1つ(入口の中では3ツールで共有)


# ---------- ジョブの表・待機列・ワーカーの繰り返し・取り消し・登録の口(役割で組み直す RS2-1b。2026-10-10 に編集の ed_jobs から移した) ----------
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


class Cancelled(Exception):
    pass


def check_cancel(job):
    """取り消されていれば Cancelled を上げる(ジョブの本体の区切りごとの確かめ)"""
    if job.get("cancel"):
        raise Cancelled()


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
    except Cancelled:
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
            info = {"id": job["id"], "kind": job.get("kind", "transcribe"), "model": sp.get("model", ""), "title": str(sp.get("title", ""))[:60], "at": int(time.time())}
            _conf["mark"](info)
            t0 = time.time()
            # 重い処理の同時実行数の上限(入口の中では他のツールの解析・書き出しと順番を待つ。上の SLOTS)
            with SLOTS.slot(_conf["tool"], info["title"], cancelled=lambda: job["cancel"],
                            on_wait=lambda: job.update(phase=WAIT_MESSAGE)) as ok:
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
        _conf["after"]()
        _conf["mark"](None)


def cancel_job(jid):
    job = _jobs.get(str(jid))
    if not job:
        raise errors.ApiError("not_found", "ジョブが見つかりません", 404)
    job["cancel"] = True
    if job["state"] == "queued":
        set_cancelled(job)
    p = job.get("proc")
    if p and p.poll() is None:
        try:
            p.terminate()
        except OSError:
            pass
