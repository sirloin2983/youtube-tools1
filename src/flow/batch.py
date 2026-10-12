"""解析キュー(バッチ): 最大10本(待ち+実行中)。1つの糸が古い順に1本ずつ analyze.run(spec, ctl) で解析する(OPT2 の J1)。
J6 で ② の 1 つの器 `flow/jobs.Table`(頭 an)の上に載せた: 積む・糸・枠・状態・取り消し・やり直し・履歴・掲示板は Table、
受け入れの検査(形・ffmpeg・yt-dlp・いっぱい・同じ配信)・store.ensure・チャットの先読み・結果を store へ入れる段取りはここ。

- 終わったら候補を「自動マーク」に変換して store に保存(その動画の既存の自動マークは置き換え、手動マークは残す)。series はメモリに保持。
- 失敗・中止は次の item へ続行。終わった item の履歴は新しい順に最大30件。
- 応答(/api/queue の items)の形は今のまま: qid・videoId・kind(src の kind)・title・channel・status(waiting・running・done・error・cancelled・skipped)・phase・progress・error・chat・marks・finishedAt
"""
from ytt import schemas, studio_env as _env

from pipeline.analyze import fetch   # 解析の材料の取得と先読み(OPT2)
from pipeline.analyze import analyze   # 解析(隣のパッケージ。RS3-5 でスタジオから pipeline へ)
from ytt.errors import ApiError

from .jobs import Table

MAX_ACTIVE = 10
MAX_HISTORY = 30
FINISHED = ("done", "error", "cancelled", "skipped")
BOARD_STATE = {"waiting": "queued", "running": "running", "done": "done", "error": "error", "cancelled": "cancelled", "skipped": "skipped"}   # item の status -> 掲示板の state
RETRYABLE = ("error", "cancelled", "skipped")
FULL_MSG = "一度に入れられるのは%d本までです" % MAX_ACTIVE
DUP_MSG = "すでに解析の順番待ちにあります"
PHASES = {"done": "完了", "error": "失敗", "cancelled": "中止しました", "skipped": "取り除きました"}


def _vid(rec):
    return rec["spec"]["src"]["videoId"]


def _admit(active, spec, kind):
    """待ち + 実行中に入れられないとき ApiError(いっぱい・同じ配信がもうある。409)"""
    if len(active) >= MAX_ACTIVE:
        raise ApiError("full", FULL_MSG, 409)
    if any(_vid(r) == spec["src"]["videoId"] for r in active):
        raise ApiError("duplicate", DUP_MSG, 409)


class Batch:
    def __init__(self, store):
        self.store = store
        self.table = Table("an", "studio", run=self._run, kinds=("analyze",), admit=_admit, keep=MAX_HISTORY,
                           slot=lambda rec: rec["title"] or _vid(rec), before=self._before, on_start=lambda rec: self._kick_prefetch(),
                           on_finish=self._on_finish, phases=PHASES, drop_state="skipped", interrupt_phase="中断しました(終了)",
                           retryable=RETRYABLE, board_job=self._board_job,
                           messages={"missing": "解析の順番待ちにありません", "closing": "終了しているところです。起動し直してから入れてください",
                                     "no_retry": "やり直せるのは、失敗・中止・取り除いた配信だけです"})

    def start(self):
        """糸を1つだけ起動する(何度呼んでも、同時に呼んでも、1つしか作らない)。"""
        self.table.start()

    # ---- 状態 ----
    def is_busy(self):
        return self.table.busy()

    def running_now(self):
        return self.table.busy(lambda r: r["state"] == "running")

    @staticmethod
    def _public(rec):
        chat = analyze.chat_public(rec["notes"].get("chat")) if rec["state"] == "running" else rec.get("chatSnap")
        return {"qid": rec["id"], "videoId": _vid(rec), "kind": rec["spec"]["src"]["kind"], "title": rec["title"], "channel": rec["channel"],
                "status": "waiting" if rec["state"] == "queued" else rec["state"], "phase": rec["phase"], "progress": round(rec["progress"] or 0.0, 3),
                "error": rec["error"] or "", "chat": chat, "marks": rec["marks"], "finishedAt": rec["finishedAt"]}

    def snapshot(self):
        recs = self.table.list()
        run = [r for r in recs if r["state"] == "running"]
        wait = [r for r in recs if r["state"] == "queued"]
        fin = sorted((r for r in recs if r["state"] in FINISHED), key=lambda r: -r["fseq"])
        return {"items": [self._public(r) for r in run + wait + fin], "running": run[0]["id"] if run else None, "max": MAX_ACTIVE}

    # ---- 追加 ----
    def add(self, items, settings):
        if not isinstance(items, list) or not items:
            raise ApiError("bad_request", "解析する配信を指定してください", 400)
        if not _env.fake() and not _env.find_tool("ffmpeg"):
            raise ApiError("no_ffmpeg", "ffmpeg が見つかりません(README の準備手順を確認してください)", 400)
        settings = analyze.validate_settings(settings)
        if self.table.closing:
            raise ApiError("closing", self.table.messages["closing"], 503)
        added, rejected = [], []
        for raw in items[:100]:
            label = (str(raw.get("path") if raw.get("kind") == "file" else (raw.get("url") or raw.get("videoId")) or "")[:200]) if isinstance(raw, dict) else ""
            try:
                src = analyze.validate_source(raw)
                if src["kind"] == "youtube" and not _env.fake() and not _env.find_tool("yt-dlp"):
                    raise ApiError("no_ytdlp", "yt-dlp が見つかりません(README の準備手順を確認してください)", 400)
            except ApiError as e:
                rejected.append({"input": label, "reason": e.message})
                continue
            if src["kind"] == "file":
                label = src["name"]
            title, channel = str(raw.get("title") or "")[:120], str(raw.get("channel") or "")[:100]

            def prepare(src=src, title=title, channel=channel):
                v = self.store.ensure(src, title, channel)   # 受け入れの検査のあと・同じロックの中(入れられない配信は store に足さない)
                return {"title": v["title"], "channel": v["channel"], "marks": 0, "chatSnap": None}
            try:
                rec = self.table.add({"src": src, "settings": settings}, prepare=prepare)
            except ApiError as e:
                rejected.append({"input": label, "reason": e.message})
                continue
            added.append({"qid": rec["id"], "videoId": src["videoId"]})
        if added:
            self._kick_prefetch()
        for i in items[100:]:
            rejected.append({"input": "", "reason": "一度に指定できる数を超えています"})
        return {"added": added, "rejected": rejected}

    # ---- 操作 ----
    def cancel(self, qid):
        self.table.cancel(qid)
        return True

    def skipchat(self, qid):
        with self.table.cv:
            rec = self.table.get(qid)
            ctl = rec["ctl"] if rec["state"] == "running" else None
            c = rec["notes"].get("chat")
        if ctl and c and c["state"] == "running":
            ctl.raise_flag("skipChat")   # チャット待ちだけ打ち切る(音声などの解析は続ける)
        return True

    def retry(self, qid):
        def prepare(old):
            self.store.ensure(old["spec"]["src"], old["title"], old["channel"])
            return {"channel": old["channel"], "marks": 0, "chatSnap": None}
        return self.table.retry(qid, prepare)["id"]

    def cancel_video(self, vid, wait=20.0):
        """動画の削除前: その動画の待ち item は取り除き(skipped)、実行中の解析は中止して終わるのを待つ。
        戻り値: 実行中の解析が止まったか(待ちきれなければ False)。"""
        t = self.table
        with t.cv:
            for rec in t.list():
                if _vid(rec) == vid and rec["state"] == "queued":
                    t.finish(rec, "skipped", "動画が削除されました", "取り除きました")
            run = next((r for r in t.list() if _vid(r) == vid and r["state"] == "running"), None)
            if run is None:
                return True
            run["ctl"].cancel()
            return t.wait(lambda: run["state"] != "running", wait)

    def shutdown(self, reason="終了のため中断しました"):
        """終了の流れ用(serve.shutdown_jobs): 待ちの配信を「中止」にして取り除き、実行中の解析に中止を伝える(待たない)。
        子プロセスは procs.stop_children がまとめて止める。中断した配信の名前の一覧を返す"""
        return [r["title"] or _vid(r) for r in self.table.shutdown(reason)]

    def clear(self):
        return self.table.clear()

    def _kick_prefetch(self):
        """解析が走っているあいだ、待ちの配信のうち先頭から順にチャットを先読みする(同時に1本)。取れたら次を先読みする。"""
        recs = self.table.list()
        if not any(r["state"] == "running" for r in recs):
            return
        for r in recs:
            src, settings = r["spec"]["src"], r["spec"]["settings"]
            if r["state"] != "queued" or src["kind"] != "youtube" or not settings.get("useChat"):
                continue
            if fetch.prefetch_chat(src["videoId"], settings["chatTimeout"] * 60, self._kick_prefetch) != "skip":
                break

    # ---- 掲示板(RS8 の ② の口 S2。flow/board.py。頭 an・id = an:<qid>。今の API は変えない: 状態を写して見せるだけ) ----
    def attach_board(self, board):
        """解析のキューを掲示板に載せる(引く形・頭 an。取り消し・やり直しも掲示板の id で)。スタジオの serve が init で 1 回呼ぶ"""
        board.register("an", source=self.board_jobs, cancel=self.board_cancel, retry=self.board_retry)

    def _board_job(self, rec):
        """記録 -> 掲示板の Job(Table の cv を持って呼ぶ)。案件の根は掲示板の case_hook が target から引く"""
        p = self._public(rec)
        state = BOARD_STATE.get(p["status"], "error")
        src = rec["spec"]["src"]
        target = {"videoId": p["videoId"]}
        if src.get("kind") == "file":
            target["path"] = src.get("path")
        return {"id": "an:" + p["qid"], "kind": "analyze", "target": target, "title": p["title"] or p["videoId"], "state": state,
                "phase": p["phase"], "progress": p["progress"], "finishedAt": p["finishedAt"],
                "error": {"code": None, "text": p["error"] or "解析に失敗しました", "detail": None} if state == "error" else None,
                "canCancel": state in ("queued", "running"), "canRetry": p["status"] in RETRYABLE}

    def board_jobs(self):
        """掲示板の引く形: 今のキュー(作成順)-> [Job]"""
        return self.table.board_jobs()

    def board_cancel(self, qid):
        """掲示板の取り消し: cancel と同じ(待ちは取り除く・実行中は中止を伝える)。無い id は LookupError"""
        try:
            self.cancel(qid)
        except ApiError as e:
            raise LookupError(e.message)

    def board_retry(self, qid):
        """掲示板のやり直し: retry と同じ(新しい qid で入れ直す)-> 新しい item の Job。無い id は LookupError・入れられないは ValueError"""
        try:
            new = self.retry(qid)
        except ApiError as e:
            raise (LookupError if e.status == 404 else ValueError)(e.message)
        with self.table.cv:
            return self._board_job(self.table.get(new))

    # ---- 糸の中身(Table が呼ぶ) ----
    def _before(self, rec):
        """動かす直前(Table の cv の中): 待っている間に動画が消されていれば取り除く"""
        if not self.store.has(_vid(rec)):
            return "skipped", "動画が削除されました", "取り除きました"
        rec["phase"], rec["progress"] = "開始", 0.0
        return None

    def _run(self, rec, ctl):
        """解析して結果を store へ入れる(失敗は ApiError = その文が error になる)"""
        result = analyze.run(analyze.make_spec(rec["spec"]["src"], rec["spec"]["settings"]), ctl)
        if not result:
            raise ApiError("no_result", "解析結果がありません")
        try:
            n = self._apply(rec, result)
        except Exception as e:   # noqa: BLE001
            raise ApiError("save", "結果の保存に失敗しました: %s" % e.__class__.__name__)
        if n is None:
            raise ApiError("deleted", "解析中に動画が削除されました")
        rec["marks"] = n or 0

    @staticmethod
    def _on_finish(rec):
        """終わりの状態を入れた直後(Table の cv の中)"""
        if rec["state"] in ("skipped", "cancelled"):
            fetch.cancel_prefetch(_vid(rec))   # 先読み中なら止める
        if rec["state"] == "done":
            rec["progress"] = 1.0
        if rec["startedAt"]:
            rec["chatSnap"] = analyze.chat_public(rec["notes"].get("chat"))
        if rec["state"] == "error" and not rec["error"]:
            rec["error"] = "解析に失敗しました"

    def _apply(self, rec, res):
        a = {"at": schemas.now_ms(), "signals": res["signals"], "counts": res["counts"], "warnings": res["warnings"], "spec": res["spec"], "type": res.get("type")}
        cands = [{"start": c["start"], "end": c["end"], "peak": c["peak"], "score": c["score"], "parts": c["parts"], "reasons": c["reasons"]} for c in res["candidates"]]
        return self.store.replace_auto(_vid(rec), cands, a, res["source"].get("duration"), res["series"])
