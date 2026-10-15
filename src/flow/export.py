"""② 書き出しの器(OPT2 の J2・J6。notes:docs/design/opt2-jobs-plan.md): ① の書き出し(pipeline/export/exporter.run)を 1 本ずつ動かすジョブの表。
J6 で ② の 1 つの器 `flow/jobs.Table`(頭 ex)の上の薄い殻にした。

- 同時に 1 本(動いている間の start は 409 busy = Table の admit)・履歴は 20 件(動いている物は消さない)・プロセスに 1 つ(`default()`)
- 1 ジョブに 1 つの `ytt/jobs.Ctl`(Table が作る)を ① に渡す(取り消しは ctl.cancel。子プロセスは ① の run_progress の見張りが止める)
- 重い処理の枠(`SLOTS.slot("studio", …)`)は Table が取る。待っている間は waiting が真
- 登録は出力先の変更(`studio_env.set_out_dir`)と同じロック `_out_lock` の下(出力先が書き出しの途中で変わらない)
- `public(jid)` は今の GET /api/export の形(id・state・outDir・folder・waiting・items・combined)
- 掲示板(頭 ex)の引く形・取り消し。登録は `attach_board(board)`(呼び手のスタジオの serve)
変換のコードは書かない(書き出しの中身・結果の形は ①)。実行中のまま終わったときの後始末(`_settle`)だけ持つ。
"""
import threading

from pipeline.export import exporter as _exporter
from ytt import studio_env as _env
from ytt.errors import ApiError

from .jobs import Table

KEEP = 20   # 終わったジョブを覚えておく数(画面の進み具合の問い合わせ用。メモリだけ)
BUSY_MSG = "別の書き出しが実行中です。完了または中止してから始めてください"


def build_spec(book, req):
    """書き出しの指定(束)を台帳から組む -> spec。book = 配信の台帳(スタジオの Store でも スタジオなしの StudioBook でも同じ。internal(id) を持つ)。
    配信が無ければ 404。マーク・音量・高さ・ファイルの検査と組み立ては ① pipeline/export/exporter.spec_from_video(台帳を知らない)"""
    v = book.internal(req.get("id"))
    if not v:
        raise ApiError("not_found", "配信が見つかりません", 404)
    return _exporter.spec_from_video(v, req)


def _admit(active, spec, kind):
    if active:
        raise ApiError("busy", BUSY_MSG, 409)


class ExportJobs:
    def __init__(self, keep=KEEP):
        self.table = Table("ex", "studio", run=self._run, kinds=("export",), admit=_admit, keep=keep,
                           title=lambda spec, kind: "書き出し %d 本" % len(spec["clips"]),
                           slot=lambda rec: "書き出し %d 本" % len(rec["res"]["items"]), on_finish=self._settle,
                           board_job=self._board_job,
                           messages={"missing": "その書き出しは見つかりません(ツールを起動し直すと、前の書き出しの記録は消えます)"})

    # ---------- 受付 ----------
    def start(self, spec, on_done=None):
        """書き出しを始める -> ジョブの記録(id・res・ctl…)。動いている書き出しがあれば ApiError busy(409)"""
        with _env._out_lock:   # 出力先の変更と同時に走らない(set_out_dir と同じ順でロックを取る)
            return self.table.add(spec, prepare=lambda: {"videoId": spec["videoId"], "outDir": _env.get_out_dir(),
                                                          "res": _exporter.new_result(spec), "onDone": on_done})

    @staticmethod
    def _run(rec, ctl):
        _exporter.run(rec["spec"], rec["res"], ctl, rec.get("onDone"))

    @staticmethod
    def _settle(rec):
        """Table が終わりの状態を入れたあと: ① の結果(res)がまだ「実行中」なら終わりの状態を付け(中止を伝えていれば中止、そうでなければ失敗)、
        記録の state を res の state にそろえる。想定外の例外でもジョブを「実行中」のまま残さない(残ると次の書き出し・出力先の変更・動画の削除が 409 になる)"""
        res = rec["res"]
        if res["state"] == "running":
            stop = rec["ctl"].cancelled
            for it in res["items"] + ([res["combined"]] if res.get("combined") else []):
                if it.get("status") in ("queued", "running"):
                    it["status"] = "cancelled" if stop else "error"
                    if not stop and not it.get("error"):
                        it["error"] = "内部エラーで止まりました(詳細は studio-errors.log)"
            res["state"] = "cancelled" if stop else "error"
        rec["state"] = res["state"] if res["state"] in ("done", "error", "cancelled") else "error"

    # ---------- 読み・取り消し ----------
    def get(self, jid):
        return self.table.get(jid)

    @staticmethod
    def public_of(rec):
        """GET /api/export の中身(今の形のまま: id・state・outDir・folder・waiting・items・combined)"""
        p = _exporter.result_public(rec["res"])
        return {"id": rec["id"], "state": p["state"], "outDir": rec.get("outDir") or _env.get_out_dir(), "folder": p["folder"],
                "waiting": bool(rec.get("waiting")),   # 他のツールの重い処理が終わるのを待っている(ytt.jobs)
                "items": p["items"], "combined": p["combined"]}

    def public(self, jid):
        return self.public_of(self.get(jid))

    def cancel(self, jid):
        self.table.cancel(jid)

    def cancel_all(self):
        """終了の流れ用(スタジオの serve.shutdown_jobs・studiobook.close): 実行中の書き出しに中止を伝える(待たない)。
        子プロセスは procs.stop_children がまとめて止める。中止したジョブの記録の一覧を返す(終了のためであることは interrupted に残す)"""
        return self.table.cancel_all()

    def is_busy(self):
        return self.table.busy()

    def is_busy_for(self, video_id):
        return self.table.busy(lambda r: r.get("videoId") == video_id)

    def clear(self):
        """テスト用: 覚えている記録を消す(動いている物には中止を伝える)"""
        self.table.clear(finished_only=False)

    # ---------- 掲示板(RS8 の ② の口 S2。flow/board.py の Job の形の辞書) ----------
    @staticmethod
    def _board_job(rec):
        res = rec["res"]
        items = res["items"]
        state = res["state"] if res["state"] in ("running", "done", "error", "cancelled") else "error"
        paths = [it["path"] for it in items if it.get("status") == "done" and it.get("path")]
        nd = sum(1 for it in items if it.get("status") == "done")
        err = next((it["error"] for it in items if it.get("status") == "error" and it.get("error")), None)
        active = state == "running"
        return {"id": "ex:" + rec["id"], "kind": "export", "target": {"videoId": rec.get("videoId"), "path": paths[0] if paths else None},
                "title": "書き出し %d 本" % len(items), "state": state,
                "phase": "順番待ち" if active and rec.get("waiting") else "%d/%d 本" % (nd, len(items)), "waiting": bool(rec.get("waiting")),
                "progress": 1.0 if state == "done" else (sum(float(it.get("progress") or 0) for it in items) / len(items) if items else None),
                "createdAt": rec["createdAt"], "finishedAt": rec.get("finishedAt"),
                "error": {"code": None, "text": str(err), "detail": None} if state == "error" else None,
                "canCancel": active and not rec["ctl"].cancelled, "canRetry": False}

    def board_jobs(self):
        """掲示板の引く形: 書き出しのジョブ(入れた順)-> [Job の辞書]"""
        return self.table.board_jobs()

    def board_cancel(self, jid):
        """掲示板の取り消し: cancel と同じ。無い id は LookupError・実行中でなければ ValueError"""
        self.table.board_cancel(jid)

    def attach_board(self, board):
        """書き出し(頭 ex)を掲示板に載せる(引く形・取り消し)"""
        self.table.attach_board(board)


_default = None
_default_lock = threading.Lock()


def default():
    """プロセスに 1 つの書き出しの器(スタジオの serve とスタジオなしの台帳 flow/studiobook が同じ物を使う = 同時 1 本がプロセスで効く)"""
    global _default
    with _default_lock:
        if _default is None:
            _default = ExportJobs()
        return _default
