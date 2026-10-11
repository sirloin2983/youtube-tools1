# -*- coding: utf-8 -*-
"""② 管理の層 flow: パックのジョブの器(OPT2 後半 J3・J6。2026-10-11)。cut2resolve/serve.py の Job・AppState のジョブの部分を移した。
J6 で ② の 1 つの器 `flow/jobs.Table`(頭 pk)の上の薄い殻にした。

同時に 1 本だけ(画面の二度押しで並ばない = Table の admit)・履歴は 20・糸 1 本・build は必ず SLOTS を待つ / plan は heavy() が真のときだけ待つ・
Task(= ytt/jobs.Ctl の子)を Table が作って fn(task) を呼ぶ。変換のコードは書かない(fn は呼ぶ側 = serve が渡す ① の呼び出し)。
応答の形(public)と掲示板の頭 pk の形は移す前と同じ。docs/design/opt2-jobs-plan.md の J3・J6。
"""
import time
import traceback

from pipeline.pack import cut2resolve_core as C
from ytt import jobs as _heavy
from ytt.errors import ApiError

from .jobs import Table

KEEP_JOBS = 20
BOARD_STATE = {"running": "running", "done": "done", "error": "error", "cancelled": "cancelled"}
BUSY_MSG = "前の処理が終わっていません(「取り消す」で止められます)"


class Job:
    """Table の記録 1 つの見え方(serve と画面が読む今の形: id・kind・state・progress・message・result・error・task・public())。
    記録を読むだけ(動いている間の値もそのまま見える)。待ち(queued)は画面には「実行中」で見せる(移す前は受けたときから running)"""

    def __init__(self, rec):
        self.rec = rec

    id = property(lambda self: self.rec["id"])
    kind = property(lambda self: self.rec["kind"])
    state = property(lambda self: "running" if self.rec["state"] == "queued" else self.rec["state"])
    progress = property(lambda self: self.rec["progress"])
    message = property(lambda self: self.rec["phase"])
    result = property(lambda self: self.rec["result"])
    error = property(lambda self: self.rec["error"])
    task = property(lambda self: self.rec["ctl"])
    started = property(lambda self: self.rec["createdAt"] / 1000.0)
    finished = property(lambda self: self.rec["finishedAt"] / 1000.0 if self.rec["finishedAt"] else None)

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


def _admit(active, spec, kind):
    if active:
        raise ApiError("busy", BUSY_MSG, 409, {"job": Job(active[0]).public()})


def _on_progress(rec, frac, message):
    if frac is not None:
        rec["progress"] = round(float(frac), 4)
    if message:
        rec["phase"] = message
        rec["progress"] = None if frac is None else rec["progress"]


class PackJobs:
    """1 つのサーバーのパックのジョブ(テストで複数のサーバーを作ってもぶつからないよう、グローバルではなく持ち主に持たせる)。
    tool_id: SLOTS の待ち行列に出す名前。log: 想定外のエラーを記録する関数(msg)。log_path: 画面の文に出す記録の場所"""

    def __init__(self, tool_id, log=None, log_path=""):
        self.tool_id = tool_id
        self.log = log or (lambda msg: None)
        self.log_path = log_path
        self.table = Table("pk", tool_id, run=lambda rec, task: rec["fn"](task), kinds=("plan", "build"), admit=_admit, keep=KEEP_JOBS,
                           slot=self._slot, make_ctl=lambda on_progress, on_note: C.Task(on_progress), on_progress=_on_progress,
                           fail=self._fail, cancelled_exc=(C.Cancelled,), phases={"cancelled": "取り消しました"},
                           board_job=lambda rec: board_job(Job(rec)),
                           messages={"missing": "その処理は見つかりません(サーバーを起動し直した可能性があります)"})

    def start_job(self, kind, fn, heavy=None):
        """heavy: 引数なしで呼べる関数。真を返すなら、その処理は他のツールの重い処理と順番を待つ(build は常に待つ。試算は無音の検出が要るときだけ)"""
        return Job(self.table.add({}, kind, extra={"fn": fn, "heavy": heavy, "phase": ""}))

    @staticmethod
    def _slot(rec):
        # パックの作成(粗編集・動画のコピー)と、無音の検出が要る試算(動画の音声を全部読む)は重いので、他のツールの重い処理と順番を待つ(ytt.jobs)
        if rec["kind"] == "build":
            return "パックの作成"
        heavy = rec.get("heavy")
        return "試算(無音の検出)" if heavy is not None and heavy() else None

    def _fail(self, rec, e):
        if isinstance(e, C.OutputExists):
            return {"code": "exists", "message": str(e), "files": [p.name for p in e.existing]}
        if isinstance(e, (C.ToolError, ApiError)):
            return {"code": getattr(e, "code", "tool"), "message": getattr(e, "message", None) or str(e)}
        self.log("error: job %s: %s" % (rec["kind"], traceback.format_exc()))   # 想定外でもサーバーは落とさない(詳細は記録)
        return {"code": "internal", "message": "内部エラー: %s %s(%s に記録しました)" % (e.__class__.__name__, str(e)[:200], self.log_path)}

    def job(self, jid):
        return Job(self.table.get(jid))

    def running_now(self):
        """動いているジョブ(無ければ None)。入口の「すべて終了」の確認と後始末用"""
        act = self.table.active()
        return Job(act[0]) if act else None

    def board_jobs(self):
        """入れた順のジョブを掲示板の Job に(引く形の source)"""
        return self.table.board_jobs()

    def board_cancel(self, jid):
        """掲示板の cancel(器の中の id)。無い id は LookupError"""
        self.table.board_cancel(jid)
