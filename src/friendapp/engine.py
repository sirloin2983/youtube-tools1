# -*- coding: utf-8 -*-
"""友人の玄関の ② の組み立て(F2-1・F2-2。Fable と相談した案 3 = CLI(app/cli.py の run_local)と同じ部品を糸つきで持つ)。

- FriendQueue = ② の待ち行列 flow/runqueue.Queue + 道具 flow/tools.LocalTools(配信の段はスタジオなしの台帳 flow/studiobook.LocalStudio)。
  ③ human・入口の 3 ツールの取り込みは読まない。待ちの記録は ② のまま(<作業データ>/app/logs。閉じても次に開いたとき続きから = 4-6)
- 実行が終わったら(Queue の finished_hook): 送り返しの zip(flow/outbox。依頼の実行だけ)→ 受信箱の行を「届いた / 失敗」に → 組のまとめ動画を裏で作る(5-8)
- 区間だけの依頼の最後の段「解析(あとで)」は友人の PC では飛ばす(友人の区間と自動の候補を比べる材料はユーザーの PC の物。仮・AI)
- 話者分離(束の transcribe.diarize)は LocalTools に無いので、送る側(api)で人数を束に入れない(コラボの名前は hints.people の色だけ。仮・AI)
"""
import os
import shutil
import threading

from flow import learning as _learning, outbox as _outbox, runqueue as _runqueue, studiobook as _studiobook, tools as _tools, wire as _wire
from pipeline.pack import preview as _preview
from pipeline.transcribe import worker_client as _worker_client
from ytt import workdata as _workdata

from . import inbox as _inbox

PREVIEW_DIR = "previews"


class FriendQueue(_runqueue.Queue):
    """玄関の ② の待ち行列(hook は CLI の CliRunner と同じ物 + 区間だけの依頼の後の解析を飛ばす)"""

    def __init__(self, studio_book, log_dir, log=None):
        self.learning_reader = _learning.Learning(_learning.learning_dir())   # 学習の束だけ(③ の読み込みは渡さない)
        _wire.install(tool="friendapp", tmp_dir=lambda: _workdata.TMP_DIR, dict_learned=self.learning_reader.dict_learned)
        tools = _tools.LocalTools(learning=self.learning_reader, studio=_studiobook.LocalStudio(studio_book))
        super().__init__(None, poll=0.5, log=log, tools=tools, log_dir=log_dir)
        self.learning = self.learning_reader

    def _studio_video(self, vid):
        return self.tools.studio_video(vid)

    def _accept(self, run, convert=False):
        super()._accept(run, convert)
        run.steps = [s for s in run.steps if s["key"] != "deliver"]   # 友人の PC の ② は届ける段を持たない(4-7。パックは受信箱に並ぶ)

    def _step_analyze_later(self, run, st, v):
        st["state"], st["detail"] = "skip", "友人の PC では解析しません(区間だけを切りました)"
        return None

    def close(self):
        super().close()
        studio = getattr(self.tools, "studio", None)
        if studio is not None:
            studio.close()   # 解析・書き出しの糸と子プロセス(ffmpeg・yt-dlp)を残さない
        _worker_client.WORKER.close()   # 認識ワーカー(別プロセス)を残さない


class Engine:
    """玄関の ② と受信箱を結ぶ係(玄関に 1 つ)"""

    def __init__(self, places, inbox, log=None, queue_factory=FriendQueue):
        self.places, self.inbox = places, inbox
        self.log = log or (lambda msg: None)
        self.app_dir = os.path.join(places["data"], "app")
        self.queue = queue_factory(places["studio"], os.path.join(self.app_dir, "logs"), log=self.log)
        self.queue.set_finished_hook(self.after_run)
        self._previews = []
        self._pv_lock = threading.Condition()
        self._pv_thread = threading.Thread(target=self._preview_loop, name="friend-preview", daemon=True)
        self._pv_thread.start()
        self.reconcile()

    # ------------------------------------------------------------ ② の状態
    def run_status(self, run_id):
        """1 本の実行の状態({state, stateLabel, step, steps, message})か None(② の待ちに無い)"""
        st = self.queue.status()
        return next((r for r in st["runs"] if r["id"] == run_id), None)

    def status_map(self):
        st = self.queue.status()
        return {r["id"]: r for r in st["runs"]}, st

    def reconcile(self):
        """起動したとき: 送った・作っている行のうち ② の待ちにも記録にも無い物を失敗にする(終了の途中で失われた。[もう一度送る] で送り直せる)。
        記録(終わった実行)にあれば、その結果で行を進める"""
        live, _ = self.status_map()
        past = {r.get("id"): r for r in (self.queue.history(200).get("runs") or [])}
        for r in self.inbox.view():
            if r["state"] not in ("sent", "making") or r.get("runId") in live or r.get("pc") == "user":   # ユーザーの PC に頼んだ行は同期が見る
                continue
            rec = past.get(r.get("runId"))
            if rec:
                packs = [p for p in (rec.get("packs") or []) if isinstance(p, str)]
                self.inbox.finished(r["runId"], rec.get("state"), rec.get("error") or "", [{"dir": p} for p in packs],
                                    (r.get("form") or {}).get("deliverBatch"), case=_case_from(rec.get("resultPath")))
            else:
                self.inbox.finished(r["runId"], "error", "前回アプリを閉じたときに依頼が途中で失われました。[もう一度送る] で送り直してください", [], None)

    # ------------------------------------------------------------ 終わった実行
    def after_run(self, run):
        row = self.inbox.by_run(run.id)
        if row is None:
            return
        if run.result_path:
            try:
                path = _outbox.build(run.result_path, self.app_dir, request_id=row["id"], log_path=os.path.join(self.app_dir, "logs", "friendapp.log"))
                if path:
                    self.log("送り返しの zip を作りました: %s" % os.path.basename(path))
            except Exception as e:   # 送り返しが作れなくても受信箱には届ける
                self.log("送り返しの zip を作れませんでした: %s" % e.__class__.__name__)
        dirs = [d for d in run.all_packs() if os.path.isdir(d)] if run.state == "done" else []
        try:
            secs = _preview.clip_seconds(dirs) if dirs else []
        except Exception:   # 長さが分からなくても届ける
            secs = [None] * len(dirs)
        error = run.error if run.state == "error" else ""
        got = self.inbox.finished(run.id, run.state, error, [{"dir": d, "seconds": s} for d, s in zip(dirs, secs)],
                                  (row.get("form") or {}).get("deliverBatch"), case=_case_from(run.result_path))
        if got and got["state"] == "arrived":
            with self._pv_lock:
                self._previews.append(got["id"])
                self._pv_lock.notify()

    def _preview_loop(self):
        while True:
            with self._pv_lock:
                while not self._previews:
                    self._pv_lock.wait()
                rid = self._previews.pop(0)
            if rid is None:
                return
            try:
                self.make_previews(rid)
            except Exception as e:   # まとめ動画が無くても 1 本ずつは見られる
                self.log("まとめ動画を作れませんでした: %s" % e.__class__.__name__)

    def make_previews(self, rid):
        """届いた行の組ごとのまとめ動画(札 = パックの題。① pipeline/pack/preview)を <玄関>/previews/<依頼 id>-<n>.mp4 に"""
        r = self.inbox.row(rid)
        if r is None:
            return
        folder = os.path.join(self.places["friend"], PREVIEW_DIR)
        os.makedirs(folder, exist_ok=True)
        by_name = {p["name"]: p for p in r["packs"]}
        for g in r["groups"]:
            if g.get("preview") and os.path.isfile(g["preview"]):
                continue
            dirs = [by_name[n]["dir"] for n in g["names"] if n in by_name and by_name[n].get("dir") and os.path.isdir(by_name[n]["dir"])]
            tmp = _preview.batch_preview(dirs, log=self.log) if dirs else None
            if not tmp:
                continue
            dest = os.path.join(folder, "%s-%d.mp4" % (rid, g["n"]))
            shutil.move(tmp, dest)
            self.inbox.set_preview(rid, g["n"], dest)

    def reload_learning(self):
        """学習の束を取り直したとき(F2-3 の同期): machine の learningDir の束を、② の読み手に入れ直す(同じ物を道具と辞書の版が使う)"""
        lr = getattr(self.queue, "learning_reader", None)
        if lr is None:
            return
        new = _learning.Learning(_learning.learning_dir())
        lr.ld, lr.pack = new.ld, new.pack

    def close(self):
        self.queue.close()
        with self._pv_lock:
            self._previews.append(None)
            self._pv_lock.notify()


def _case_from(result_path):
    return _inbox.case_of(result_path)
