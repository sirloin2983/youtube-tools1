# -*- coding: utf-8 -*-
"""友人の玄関の ② の組み立て(F2-1・F2-2。Fable と相談した案 3 = CLI(app/cli.py の run_local)と同じ部品を糸つきで持つ)。

- FriendQueue = ② の待ち行列 flow/runqueue.Queue + 道具 flow/tools.LocalTools(配信の段はスタジオなしの台帳 flow/studiobook.LocalStudio)。
  ③ human・入口の 3 ツールの取り込みは読まない。待ちの記録は ② のまま(<作業データ>/app/logs。閉じても次に開いたとき続きから = 4-6)
- 実行が終わったら(Queue の finished_hook): 送り返しの zip(flow/outbox。依頼の実行だけ)→ 受信箱の行を「届いた / 失敗」に → 組のまとめ動画を裏で作る(5-8)
- 区間だけの依頼の最後の段「解析(あとで)」は友人の PC では飛ばす(友人の区間と自動の候補を比べる材料はユーザーの PC の物。仮・AI)
- 話者分離(束の transcribe.diarize)は LocalTools に無いので、送る側(api)で人数を束に入れない(コラボの名前は hints.people の色だけ。仮・AI)
- ライブ(F2-6): ② のライブ係 friendapp/live.FriendLive を持ち、待ち行列の set_live_hook で封筒 kind live を回す(長さは受信箱の行の送った欄 =
  束の analyze に入れない。lengthMode auto = 場面ごとの形・fixed = 固定の秒。C-2-11)。切り抜きごとの実行(requestId = 行の id)が終わったら行にパックを足し(live_clip)、ライブ係の見回りのたびに
  録画が終わったか・作っている物が残っているかを見て行を進める(live_tick)
"""
import os
import shutil
import threading
import time

from flow import learning as _learning, livesession as _livesession, outbox as _outbox, runqueue as _runqueue, studiobook as _studiobook, \
    tools as _tools, wire as _wire
from pipeline.pack import preview as _preview
from pipeline.transcribe import worker_client as _worker_client
from ytt import docloc as _docloc, fsio as _fsio, workdata as _workdata

from . import inbox as _inbox, progress as _progress

PREVIEW_DIR = "previews"
_CLIP_PREVIEW = getattr(_preview, "clip_preview", None)   # 1 本の確認用の動画(札なし。F3-6 で ① に入る。無ければ札つきのまとめ動画の形で 1 本)


ENGINE_OF_DEVICE = {"vulkan": "A", "cuda": "C"}   # 文字起こしのエンジン A = whisper.cpp の Vulkan・C = CUDA(⚙ と同じ名前)


def _hms(ms):
    return time.strftime("%H:%M:%S", time.localtime(ms / 1000.0))


def stage_lines(run):
    """1 本の実行の段ごとの始めと終わりの時刻・かかった秒を 1 段 1 行で(友人のログ friendapp.log 用。10-18 友人の PC が遅い原因を後から追うため)。
    段の時刻は ② の steps[].startedAt・finishedAt(ミリ秒)。始まらなかった段は書かない"""
    who = getattr(run, "request_id", None) or run.id
    out = []
    for s in getattr(run, "steps", None) or []:
        a, b = s.get("startedAt"), s.get("finishedAt")
        if not isinstance(a, int) or isinstance(a, bool):
            continue
        b = b if isinstance(b, int) and not isinstance(b, bool) else a
        out.append("段 依頼=%s %s(%s) 始め=%s 終わり=%s %.1f 秒 %s %s" % (
            who, s.get("key"), _progress.FRIEND_OF.get(s.get("key")) or "-", _hms(a), _hms(b), max(0, b - a) / 1000.0,
            s.get("state") or "", str(s.get("detail") or "")[:60].replace("\n", " ")))
    return out


def transcribe_line(who, rec):
    """文書の認識の記録(recognition.runs の 1 件)-> 文字起こしの 1 行: エンジン(A/C)・実際に使った装置・モデル・音声の長さ・かかった秒・実時間比。
    装置 = whisper.cpp が出した「using … backend」と GPU 名(ggml_vulkan / CUDA の行)。CPU に落ちたら CPU と書く。記録に装置が無ければ「記録なし」"""
    dev = str(rec.get("device") or "")
    eng = ENGINE_OF_DEVICE.get(dev) or ("CPU" if dev == "cpu" else "?")
    backend, gpu = str(rec.get("backend") or ""), str(rec.get("gpu") or "")
    if dev == "cpu":
        where = "CPU(GPU は使っていません)"
    elif backend or gpu:
        where = "%s GPU=%s" % (backend or "?", gpu or "?")
    else:
        where = "記録なし(GPU の行を拾えていません。CPU に落ちた疑い)" if dev in ENGINE_OF_DEVICE else "記録なし"
    audio, wall = rec.get("audioSec"), rec.get("wallSec")
    ok = isinstance(audio, (int, float)) and isinstance(wall, (int, float)) and audio > 0
    return "文字起こし 依頼=%s エンジン=%s(%s %s) 装置=%s モデル=%s 音声=%s 秒 かかった=%s 秒 実時間比=%s" % (
        who, eng, rec.get("engine") or "?", rec.get("engineVersion") or "", where, rec.get("model") or "?",
        "%.1f" % audio if isinstance(audio, (int, float)) else "?", "%.1f" % wall if isinstance(wall, (int, float)) else "?",
        "%.2f" % (wall / audio) if ok else "?")


def transcribe_lines(run, read_doc=None):
    """この実行が文字起こしした文書ごとの transcribe_line(段の始まりより後の認識の記録だけ = 飛ばした既存の文書は書かない)"""
    who = getattr(run, "request_id", None) or run.id
    read_doc = read_doc or _read_doc
    t0 = next((s.get("startedAt") for s in getattr(run, "steps", None) or [] if s.get("key") == "transcribe" and isinstance(s.get("startedAt"), int)), None)
    out = []
    for tid in getattr(run, "docs", None) or []:
        d = read_doc(tid)
        runs = ((d or {}).get("recognition") or {}).get("runs") if isinstance(d, dict) else None
        rec = runs[-1] if isinstance(runs, list) and runs and isinstance(runs[-1], dict) else None
        if rec is None or (t0 is not None and isinstance(rec.get("at"), (int, float)) and rec["at"] < t0):
            continue
        out.append(transcribe_line(who, rec))
    return out


def _read_doc(tid):
    try:
        return _fsio.read_json_or(_docloc.doc_file(str(tid), ".json"), None, kind=dict)
    except Exception:
        return None


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

    def _shape_steps(self, run):   # _accept と起動し直しの復元の両方から呼ばれる(復元した実行が届ける段を持ち越さない)
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

    def __init__(self, places, inbox, log=None, queue_factory=FriendQueue, live_factory=None):
        """live_factory(places, queue_fn, log) -> ライブ係(friendapp/live.FriendLive)か None(ライブなし = テスト)。玄関は本物を渡し、見回りの糸を起こす"""
        self.places, self.inbox = places, inbox
        self.log = log or (lambda msg: None)
        self.app_dir = os.path.join(places["data"], "app")
        self.queue = queue_factory(places["studio"], os.path.join(self.app_dir, "logs"), log=self.log)
        self.queue.set_finished_hook(self.after_run)
        self.live = live_factory(places, lambda: self.queue, self.log) if live_factory is not None else None
        if self.live is not None:
            self.queue.set_live_hook(self.live_submit)
            self.live.on_tick = self.live_tick
        self._previews = []
        self._pv_lock = threading.Condition()
        self._mk_lock = threading.Lock()
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
            if not r.get("runId"):   # ② に積む前に閉じた(動画を写している途中・録画を始める途中。F2-6)
                self.inbox.fail(r["id"], "前回アプリを閉じたときに依頼が途中で止まりました。[もう一度送る] で送り直してください")
            elif rec:
                packs = [p for p in (rec.get("packs") or []) if isinstance(p, str)]
                self.inbox.finished(r["runId"], rec.get("state"), rec.get("error") or "", [{"dir": p} for p in packs],
                                    (r.get("form") or {}).get("deliverBatch"), case=_case_from(rec.get("resultPath")))
            else:
                self.inbox.finished(r["runId"], "error", "前回アプリを閉じたときに依頼が途中で失われました。[もう一度送る] で送り直してください", [], None)

    # ------------------------------------------------------------ 終わった実行
    def transcribe_progress(self):
        """いま動いている文字起こしのジョブの進み("42%")か None。ツールの transcribe_start は ② の段の中で同じ糸が終わらせるので、
        段の detail は動かない。玄関の画面がここから読む(「1/3」のまま止まって見えないように)"""
        try:
            jobs = self.queue.tools.jobs()
        except Exception:
            return None
        run = [j for j in jobs if isinstance(j, dict) and j.get("kind") == "transcribe" and j.get("state") == "running"]
        if not run:
            return None
        p = run[-1].get("progress")
        return "%d%%" % round(float(p) * 100) if isinstance(p, (int, float)) and not isinstance(p, bool) else None

    def log_run(self, run):
        """終わった実行の記録を friendapp.log へ(段ごと 1 行 + 文字起こし 1 行 + 実行の終わり 1 行)。書けなくても実行は止めない"""
        try:
            for line in stage_lines(run) + transcribe_lines(run):
                self.log(line)
            self.log("実行の終わり 依頼=%s 状態=%s" % (getattr(run, "request_id", None) or run.id, run.state) + (" 理由=%s" % str(run.error)[:200].replace("\n", " ") if run.state == "error" else ""))
        except Exception as e:
            self.log("実行の記録を書けませんでした: %s" % e.__class__.__name__)

    def after_run(self, run):
        self.log_run(run)
        row = self.inbox.by_run(run.id)
        clip = False
        if row is None and getattr(run, "request_id", None):   # ライブの切り抜き 1 本の実行(封筒の requestId = 受信箱の行の id。F2-6)
            row = self.inbox.row(run.request_id)
            clip = row is not None and row.get("kind") == "live"
        if row is None or (row.get("runId") != run.id and not clip):
            return
        if run.result_path:
            try:
                path = _outbox.build(run.result_path, self.app_dir, request_id=row["id"], log_path=os.path.join(self.app_dir, "logs", "friendapp.log"))
                if path:
                    self.log("送り返しの zip を作りました: %s" % os.path.basename(path))
            except Exception as e:   # 送り返しが作れなくても受信箱には届ける
                self.log("送り返しの zip を作れませんでした: %s" % e.__class__.__name__)
        dirs = [d for d in run.all_packs() if os.path.isdir(_fsio.long_path(d))] if run.state == "done" else []
        try:
            secs = _preview.clip_seconds(dirs) if dirs else []
        except Exception:   # 長さが分からなくても届ける
            secs = [None] * len(dirs)
        error = run.error if run.state == "error" else ""
        packs = [{"dir": d, "seconds": s} for d, s in zip(dirs, secs)]
        if clip:
            meta = ((getattr(run, "pool", None) or {}).get("meta") or {})
            _got, made = self.inbox.live_clip(row["id"], run.id, run.state, error, packs, meta.get("phase") or "live", case=_case_from(run.result_path))
            if made:
                self._want_previews(row["id"])
            return
        got = self.inbox.finished(run.id, run.state, error, packs, (row.get("form") or {}).get("deliverBatch"), case=_case_from(run.result_path))
        if got and got["state"] == "arrived":
            self._want_previews(got["id"])

    def _want_previews(self, rid):
        with self._pv_lock:
            if rid not in self._previews:
                self._previews.append(rid)
            self._pv_lock.notify()

    # ------------------------------------------------------------ ライブ(F2-6)
    def live_submit(self, env, bundle):
        """② の待ち行列の live の hook: 封筒 kind live + 束 -> ライブ係の submit(依頼の結びつきの欄 ctx は封筒 + 束から。長さは受信箱の行の送った欄 =
        束の analyze に入れない(入口 app の submit_request と同じ決まり))。録画の部品が起動するまで少し待つ"""
        ctx = _livesession.bundle_ctx(env, bundle, _livesession.stream_url(env))
        row = self.inbox.row(env.get("requestId") or "")
        s = ((row or {}).get("form") or {}).get("live")
        if isinstance(s, dict) and isinstance(s.get("length"), int):
            ctx["settings"] = dict(ctx["settings"], length=s["length"])
        if isinstance(s, dict) and s.get("lengthMode") == "auto":   # 長さ「自動(場面ごと)」(C-2-11。length は場面が取れないときの長さ)
            ctx["settings"] = dict(ctx["settings"], lengthMode="auto")
        ctx["deliverDir"] = ""   # 友人の PC は届けない(4-7。パックは受信箱に並ぶ)
        self.live.wait_recorder()
        return self.live.submit(env, bundle, ctx=ctx)

    def live_tick(self):
        """ライブ係の見回りのたび: この PC のライブの行ごとに、録画が終わったか・書き出しと切り抜きの実行が残っているか・配信後の追加を待つかを見て
        行を進める(組・届いた・失敗)。録画元につながらないときはその行を飛ばす(分からないまま閉じない)"""
        rows = self.inbox.live_rows()
        if not rows or self.live is None:
            return
        runs = self.queue.status().get("runs") or []
        lists = {}
        for r in rows:
            lv = r["live"]
            rc, rec = lv.get("recorder"), lv.get("recording")
            if rc not in lists:
                lists[rc] = self.live.recordings(rc)
            recs = lists[rc]
            if recs is None:
                continue
            raw = recs.get(rec)
            recording = bool(raw and raw.get("active"))
            busy = self.live.busy_recording(rc, rec) or any(x.get("requestId") == r["id"] and x.get("state") in ("queued", "running") for x in runs)
            waiting = self.live.after_hold(rc, raw) if raw is not None and not recording and not busy else ""
            if self.inbox.live_update(r["id"], recording, busy, waiting):
                self._want_previews(r["id"])

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
        """届いた行のパック 1 本ずつの確認用の動画(480p・字幕なし。① pipeline/pack/preview の clip_preview = F3-6。C-3-3)を
        <玄関>/previews/<依頼 id>-<n>.mp4 に(n = 1 本ずつの組の番号)。1 つずつ(裏の糸と呼んだ側が同じ物を二重に作らない)"""
        with self._mk_lock:
            self._make_previews(rid)

    def _make_previews(self, rid):
        r = self.inbox.row(rid)
        if r is None:
            return
        folder = os.path.join(self.places["friend"], PREVIEW_DIR)
        os.makedirs(folder, exist_ok=True)
        by_name = {p["name"]: p for p in r["packs"]}
        for g in r["groups"]:
            if g.get("preview") and os.path.isfile(g["preview"]):
                continue
            dirs = [by_name[n]["dir"] for n in g["names"] if n in by_name and by_name[n].get("dir") and os.path.isdir(_fsio.long_path(by_name[n]["dir"]))
                    and not by_name[n].get("verdict")]
            if len(dirs) == 1 and _CLIP_PREVIEW is not None:
                tmp = _CLIP_PREVIEW(dirs[0], log=self.log)
            else:
                tmp = _preview.batch_preview(dirs, log=self.log) if dirs else None
            if not tmp:
                continue
            dest = os.path.join(folder, "%s-%d.mp4" % (rid, g["n"]))
            shutil.move(_fsio.long_path(tmp), _fsio.long_path(dest))
            self.inbox.set_preview(rid, g["n"], dest)

    def reload_learning(self):
        """学習の束を取り直したとき(F2-3 の同期): machine の learningDir の束を、② の読み手に入れ直す(同じ物を道具と辞書の版が使う)"""
        lr = getattr(self.queue, "learning_reader", None)
        if lr is None:
            return
        new = _learning.Learning(_learning.learning_dir())
        lr.ld, lr.pack = new.ld, new.pack

    def close(self):
        if self.live is not None:   # 録画中でも録画の部品まで止める(次に開いたとき同じ録画の続きから。friendapp/live.py)
            try:
                self.live.close()
            except Exception as e:   # 後始末の途中の不具合で ② を残さない
                self.log("ライブ係を止める途中でエラー: %s" % e.__class__.__name__)
        self.queue.close()
        with self._pv_lock:
            self._previews.append(None)
            self._pv_lock.notify()


def _case_from(result_path):
    return _inbox.case_of(result_path)
