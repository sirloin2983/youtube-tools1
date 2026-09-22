"""② 解析キュー(バッチ): 最大10本(待ち+実行中)。1つのワーカースレッドが古い順に1本ずつ analyze.run_analyze で解析する。

- 終わったら候補を「自動マーク」に変換して store に保存(その動画の既存の自動マークは置き換え、手動マークは残す)。series はメモリに保持。
- 失敗・中止は次の item へ続行。終わった item の履歴は新しい順に最大30件。
"""
import threading
import time
import uuid

import analyze
import common
from common import ApiError

MAX_ACTIVE = 10
MAX_HISTORY = 30
FINISHED = ("done", "error", "cancelled", "skipped")
RETRYABLE = ("error", "cancelled", "skipped")


def _now_ms():
    return int(time.time() * 1000)


class Batch:
    def __init__(self, store):
        self.store = store
        self.cv = threading.Condition()
        self.items = []      # 作成順(待ち・実行中・履歴)
        self.running = None  # 実行中の qid
        self._fseq = 0
        self._thread = None

    def start(self):
        """ワーカーを1つだけ起動する(何度呼んでも、同時に呼んでも、1つしか作らない)。"""
        with self.cv:
            if self._thread is None:
                self._thread = threading.Thread(target=self._loop, daemon=True, name="batch-worker")
                self._thread.start()

    # ---- 状態 ----
    def _active(self):
        return [i for i in self.items if i["status"] in ("waiting", "running")]

    def is_busy(self):
        with self.cv:
            return bool(self._active())

    def _find(self, qid):
        it = next((i for i in self.items if i["qid"] == str(qid or "")), None)
        if not it:
            raise ApiError("not_found", "キューにありません", 404)
        return it

    def _finish(self, it, status, error="", phase=None):
        self._fseq += 1
        it["status"], it["error"], it["fseq"], it["finishedAt"] = status, error, self._fseq, _now_ms()
        if status in ("skipped", "cancelled"):
            analyze.cancel_prefetch(it["videoId"])   # 先読み中なら止める
        it["phase"] = phase or {"done": "完了", "error": "失敗", "cancelled": "中止しました", "skipped": "取り除きました"}[status]
        it["progress"] = 1.0 if status == "done" else it["progress"]
        fin = sorted((i for i in self.items if i["status"] in FINISHED), key=lambda i: i["fseq"])
        for old in fin[:-MAX_HISTORY]:
            self.items.remove(old)

    def _public(self, it):
        job = it.get("job")
        chat = analyze.chat_public(job["chat"]) if job else it.get("chatSnap")
        d = {"qid": it["qid"], "videoId": it["videoId"], "kind": it["kind"], "title": it["title"], "channel": it["channel"], "status": it["status"],
             "phase": job["phase"] if job and it["status"] == "running" else it["phase"], "progress": round(job["progress"], 3) if job and it["status"] == "running" else it["progress"],
             "error": it["error"], "chat": chat, "marks": it["marks"], "finishedAt": it["finishedAt"]}
        return d

    def snapshot(self):
        with self.cv:
            run = [i for i in self.items if i["status"] == "running"]
            wait = [i for i in self.items if i["status"] == "waiting"]
            fin = sorted((i for i in self.items if i["status"] in FINISHED), key=lambda i: -i["fseq"])
            return {"items": [self._public(i) for i in run + wait + fin], "running": self.running, "max": MAX_ACTIVE}

    # ---- 追加 ----
    def _new_item(self, src, settings, title, channel):
        return {"qid": uuid.uuid4().hex[:8], "videoId": src["videoId"], "kind": src["kind"], "title": title, "channel": channel, "status": "waiting", "phase": "順番待ち",
                "progress": 0.0, "error": "", "src": src, "settings": settings, "job": None, "chatSnap": None, "marks": 0, "finishedAt": None, "fseq": 0}

    def add(self, items, settings):
        if not isinstance(items, list) or not items:
            raise ApiError("bad_request", "解析する動画を指定してください", 400)
        if not common.fake() and not common.find_tool("ffmpeg"):
            raise ApiError("no_ffmpeg", "ffmpeg が見つかりません(README の準備手順を確認してください)", 400)
        settings = analyze.validate_settings(settings)
        added, rejected = [], []
        with self.cv:
            for raw in items[:100]:
                label = (str(raw.get("path") if raw.get("kind") == "file" else (raw.get("url") or raw.get("videoId")) or "")[:200]) if isinstance(raw, dict) else ""
                try:
                    src = analyze.validate_source(raw)
                    if src["kind"] == "youtube" and not common.fake() and not common.find_tool("yt-dlp"):
                        raise ApiError("no_ytdlp", "yt-dlp が見つかりません(README の準備手順を確認してください)", 400)
                except ApiError as e:
                    rejected.append({"input": label, "reason": e.message})
                    continue
                if src["kind"] == "file":
                    label = src["name"]
                act = self._active()
                if len(act) >= MAX_ACTIVE:
                    rejected.append({"input": label, "reason": "一度に入れられるのは10本までです"})
                    continue
                if any(i["videoId"] == src["videoId"] for i in act):
                    rejected.append({"input": label, "reason": "すでにキューにあります"})
                    continue
                title, channel = str(raw.get("title") or "")[:120], str(raw.get("channel") or "")[:100]
                try:
                    v = self.store.ensure(src, title, channel)
                except ApiError as e:
                    rejected.append({"input": label, "reason": e.message})
                    continue
                it = self._new_item(src, settings, v["title"], v["channel"])
                self.items.append(it)
                added.append({"qid": it["qid"], "videoId": it["videoId"]})
            if added:
                self.cv.notify_all()
        if added:
            self.start()
            self._kick_prefetch()
        for i in items[100:]:
            rejected.append({"input": "", "reason": "一度に指定できる数を超えています"})
        return {"added": added, "rejected": rejected}

    # ---- 操作 ----
    def cancel(self, qid):
        with self.cv:
            it = self._find(qid)
            if it["status"] == "waiting":
                self._finish(it, "skipped")
            elif it["status"] == "running" and it.get("job"):
                analyze.cancel_job(it["job"])
        return True

    def skipchat(self, qid):
        with self.cv:
            it = self._find(qid)
            job = it.get("job") if it["status"] == "running" else None
        if job:
            analyze.skip_chat(job)
        return True

    def retry(self, qid):
        with self.cv:
            it = self._find(qid)
            if it["status"] not in RETRYABLE:
                raise ApiError("bad_state", "やり直せるのは、失敗・中止・取り除いた配信だけです", 409)
            act = self._active()
            if len(act) >= MAX_ACTIVE:
                raise ApiError("full", "一度に入れられるのは10本までです", 409)
            if any(i["videoId"] == it["videoId"] for i in act):
                raise ApiError("duplicate", "すでにキューにあります", 409)
            self.store.ensure(it["src"], it["title"], it["channel"])
            new = self._new_item(it["src"], it["settings"], it["title"], it["channel"])
            self.items.remove(it)
            self.items.append(new)
            self.cv.notify_all()
        self.start()
        return new["qid"]

    def cancel_video(self, vid, wait=20.0):
        """動画の削除前: その動画の待ち item は取り除き(skipped)、実行中の解析は中止して終わるのを待つ。
        戻り値: 実行中の解析が止まったか(待ちきれなければ False)。"""
        with self.cv:
            for it in list(self.items):
                if it["videoId"] == vid and it["status"] == "waiting":
                    self._finish(it, "skipped", "動画が削除されました", "取り除きました")
            run = next((i for i in self.items if i["videoId"] == vid and i["status"] == "running"), None)
            if run is None:
                return True
            if run.get("job"):
                analyze.cancel_job(run["job"])
            return self.cv.wait_for(lambda: run["status"] != "running", wait)

    def clear(self):
        with self.cv:
            n = len(self.items)
            self.items = [i for i in self.items if i["status"] not in FINISHED]
            return n - len(self.items)

    def _kick_prefetch(self):
        """解析が走っているあいだ、待ちの配信のうち先頭から順にチャットを先読みする(同時に1本)。取れたら次を先読みする。"""
        with self.cv:
            if not any(i["status"] == "running" for i in self.items):
                return
            for i in self.items:
                if i["status"] != "waiting" or i["src"]["kind"] != "youtube" or not i["settings"].get("useChat"):
                    continue
                r = analyze.prefetch_chat(i["videoId"], i["settings"]["chatTimeout"] * 60, self._kick_prefetch)
                if r != "skip":
                    break

    # ---- ワーカー ----
    def _loop(self):
        while True:
            with self.cv:
                while True:
                    it = next((i for i in self.items if i["status"] == "waiting"), None)
                    if it:
                        break
                    self.cv.wait()
                if not self.store.has(it["videoId"]):   # 待っている間に動画が消された
                    self._finish(it, "skipped", "動画が削除されました", "取り除きました")
                    continue
                it["status"], it["phase"] = "running", "開始"
                job = analyze.new_job(analyze.make_spec(it["src"], it["settings"]))
                it["job"] = job
                self.running = it["qid"]
            self._kick_prefetch()
            try:
                analyze.run_analyze(job)
            except BaseException as e:   # 想定外でも次の item へ続ける
                job["state"], job["error"] = "error", "内部エラー: %s %s" % (e.__class__.__name__, str(e)[:200])
            self._complete(it, job)

    def _complete(self, it, job):
        n, err, status = 0, "", job["state"]
        try:
            if status == "done" and job.get("result"):
                n = self._apply(it, job)
                if n is None:
                    status, err = "error", "解析中に動画が削除されました"
            elif status == "done":
                status, err = "error", "解析結果がありません"
            elif status == "error":
                err = job.get("error") or "解析に失敗しました"
            elif status != "cancelled":
                status, err = "error", "解析が途中で止まりました"
        except Exception as e:
            status, err = "error", "結果の保存に失敗しました: %s" % e.__class__.__name__
        with self.cv:
            it["marks"] = n or 0
            it["chatSnap"] = analyze.chat_public(job.get("chat"))
            it["job"] = None
            self.running = None
            if it in self.items:
                self._finish(it, status, err)
            self.cv.notify_all()

    def _apply(self, it, job):
        res = job["result"]
        a = {"at": _now_ms(), "signals": res["signals"], "counts": res["counts"], "warnings": res["warnings"], "spec": res["spec"], "type": res.get("type")}
        cands = [{"start": c["start"], "end": c["end"], "peak": c["peak"], "score": c["score"], "parts": c["parts"], "reasons": c["reasons"]} for c in res["candidates"]]
        return self.store.replace_auto(it["videoId"], cands, a, res["source"].get("duration"), res["series"])
