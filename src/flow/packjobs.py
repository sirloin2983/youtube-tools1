# -*- coding: utf-8 -*-
"""② 管理の層 flow: パックのジョブの器(OPT2 後半 J3。2026-10-11)。cut2resolve/serve.py の Job・AppState のジョブの部分を移した。

同時に 1 本だけ(画面の二度押しで並ばない)・履歴は 20・糸 1 本・build は必ず SLOTS を待つ / plan は heavy() が真のときだけ待つ・
Task(= ytt/jobs.Ctl の子)を作って fn(task) を呼ぶ。変換のコードは書かない(fn は呼ぶ側 = serve が渡す ① の呼び出し)。
応答の形(public)と掲示板の頭 pk の形は移す前と同じ。docs/design/opt2-jobs-plan.md の J3。
"""
import secrets
import threading
import time
import traceback
from collections import OrderedDict

from pipeline.pack import cut2resolve_core as C
from ytt import jobs as _heavy
from ytt.errors import ApiError

KEEP_JOBS = 20
BOARD_STATE = {"running": "running", "done": "done", "error": "error", "cancelled": "cancelled"}


class Job:
    def __init__(self, kind):
        self.id = secrets.token_hex(6)
        self.kind = kind
        self.state = "running"
        self.progress = None
        self.message = ""
        self.result = None
        self.error = None
        self.started = time.time()
        self.finished = None
        self.task = C.Task(self._on_progress)

    def _on_progress(self, frac, message):
        if frac is not None:
            self.progress = round(float(frac), 4)
        if message:
            self.message = message
            self.progress = None if frac is None else self.progress

    def public(self):
        d = {"id": self.id, "kind": self.kind, "state": self.state, "progress": self.progress, "message": self.message,
             "elapsed": round((self.finished or time.time()) - self.started, 1)}
        if self.result is not None:
            d["result"] = self.result
        if self.error is not None:
            d["error"] = self.error
        return d


def board_job(job):
    """パックのジョブ 1 つ -> 掲示板の Job(id = "pk:<ジョブの id>"。kind pack。試算も同じ kind で題だけ違う)。読むだけ"""
    state = BOARD_STATE.get(job.state, "running")
    err = None
    if job.error:
        err = {"code": job.error.get("code"), "text": job.error.get("message") or "", "detail": None}
    res = job.result if isinstance(job.result, dict) else {}
    target = {"path": str(res["outDir"])} if res.get("outDir") else {}
    return {"id": "pk:" + job.id, "kind": "pack", "target": target, "title": "パックの作成" if job.kind == "build" else "試算",
            "state": state, "phase": job.message or "", "progress": job.progress, "waiting": job.message == _heavy.WAIT_MESSAGE and state == "running",
            "createdAt": int(job.started * 1000), "startedAt": int(job.started * 1000),
            "finishedAt": int(job.finished * 1000) if job.finished else None, "error": err, "canCancel": state == "running", "canRetry": False}


class PackJobs:
    """1 つのサーバーのパックのジョブ(テストで複数のサーバーを作ってもぶつからないよう、グローバルではなく持ち主に持たせる)。
    tool_id: SLOTS の待ち行列に出す名前。log: 想定外のエラーを記録する関数(msg)。log_path: 画面の文に出す記録の場所"""

    def __init__(self, tool_id, log=None, log_path=""):
        self.tool_id = tool_id
        self.log = log or (lambda msg: None)
        self.log_path = log_path
        self.lock = threading.Lock()
        self.jobs = OrderedDict()
        self.running = None

    def start_job(self, kind, fn, heavy=None):
        """heavy: 引数なしで呼べる関数。真を返すなら、その処理は他のツールの重い処理と順番を待つ(build は常に待つ。試算は無音の検出が要るときだけ)"""
        with self.lock:
            if self.running is not None and self.running.state == "running":
                raise ApiError("busy", "前の処理が終わっていません(「取り消す」で止められます)", 409,
                               {"job": self.running.public()})
            job = Job(kind)
            self.running = job
            self.jobs[job.id] = job
            while len(self.jobs) > KEEP_JOBS:
                self.jobs.popitem(last=False)
        th = threading.Thread(target=self._run, args=(job, fn, heavy), daemon=True, name="job-" + kind)
        th.start()
        return job

    def _run(self, job, fn, heavy=None):
        try:
            # パックの作成(粗編集・動画のコピー)と、無音の検出が要る試算(動画の音声を全部読む)は重いので、他のツールの重い処理と順番を待つ(ytt.jobs)
            if job.kind == "build" or (heavy is not None and heavy()):
                with _heavy.SLOTS.slot(self.tool_id, "パックの作成" if job.kind == "build" else "試算(無音の検出)", cancelled=lambda: job.task.cancelled,
                                       on_wait=lambda: setattr(job, "message", _heavy.WAIT_MESSAGE)) as ok:
                    if not ok:
                        raise C.Cancelled()
                    job.message = ""
                    job.result = fn(job.task)
            else:
                job.result = fn(job.task)
            job.state = "done"
        except C.Cancelled:
            job.state = "cancelled"
            job.message = "取り消しました"
        except C.OutputExists as e:
            job.state = "error"
            job.error = {"code": "exists", "message": str(e), "files": [p.name for p in e.existing]}
        except (C.ToolError, ApiError) as e:
            job.state = "error"
            job.error = {"code": getattr(e, "code", "tool"), "message": getattr(e, "message", None) or str(e)}
        except Exception as e:   # 想定外でもサーバーは落とさない(詳細は記録)
            self.log("error: job %s: %s" % (job.kind, traceback.format_exc()))
            job.state = "error"
            job.error = {"code": "internal", "message": "内部エラー: %s %s(%s に記録しました)" % (e.__class__.__name__, str(e)[:200], self.log_path)}
        finally:
            job.finished = time.time()

    def job(self, jid):
        with self.lock:
            j = self.jobs.get(str(jid or ""))
        if j is None:
            raise ApiError("not_found", "その処理は見つかりません(サーバーを起動し直した可能性があります)", 404)
        return j

    def running_now(self):
        """動いているジョブ(無ければ None)。入口の「すべて終了」の確認と後始末用"""
        job = self.running
        return job if job is not None and job.state == "running" else None

    def board_jobs(self):
        """入れた順のジョブを掲示板の Job に(引く形の source)"""
        with self.lock:
            jobs = list(self.jobs.values())
        return [board_job(j) for j in jobs]

    def board_cancel(self, jid):
        """掲示板の cancel(器の中の id)。無い id は LookupError"""
        try:
            job = self.job(jid)
        except ApiError as e:
            raise LookupError(e.message)
        if job.state == "running":
            job.task.cancel()
