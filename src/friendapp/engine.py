# -*- coding: utf-8 -*-
"""友人の玄関の ② の組み立て(flow の部品を糸つきで持つ)。

- FriendQueue = ② の待ち行列 flow/runqueue.Queue + 道具 flow/tools.LocalTools(配信の段はスタジオなしの台帳 flow/studiobook.LocalStudio)。
  ③ human・入口の 3 ツールの取り込みは読まない。待ちの記録は ② のまま(<作業データ>/app/logs。閉じても次に開いたとき続きから = 4-6)
- 実行が終わったら(Queue の finished_hook): 送り返しの zip(flow/outbox。依頼の実行だけ)→ 受信箱の行を「届いた / 失敗」に → パック 1 本ずつの確認用の動画を裏で作る
- 区間だけの依頼の最後の段「解析(あとで)」は友人の PC では飛ばす(友人の区間と自動の候補を比べる材料はユーザーの PC の物。仮・AI)
- 話者分離(束の transcribe.diarize)は LocalTools に無いので、送る側(api)で人数を束に入れない(コラボの名前は hints.people の色だけ。仮・AI)
- ライブ: ② のライブ係 friendapp/live.FriendLive を持ち、待ち行列の set_live_hook で封筒 kind live を回す(長さは受信箱の行の送った欄 =
  束の analyze に入れない。lengthMode auto = 場面ごとの形・fixed = 固定の秒。C-2-11)。切り抜きごとの実行(requestId = 行の id)が終わったら行にパックを足し(live_clip)、ライブ係の見回りのたびに
  録画が終わったか・作っている物が残っているか・検出がまだ採用しうるかを見て行を進める(live_tick)。行を閉じたら診断 kind live(friendapp/diag)。
  パックが無いまま閉じた理由は原因ごと(live_cause = 候補なし・チャットなし・検出が動かない・採用の失敗・書き出しの失敗 など)
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
BLOCKED_NOTICE = 180   # 録画元が YouTube に断られ続けてこの秒たったら友人の行に出す(録画元の記録の blockedAt。pipeline/ingest/rec_core)
BLOCKED_WARN = "YouTube に断られて録画できていません(⚙ で YouTube にログインするか、しばらく待ってください)"
LOST_NOTICE = 180      # 録画の部品が答えないままこの秒たったら友人の行に出す(10-23 の見回り: 前は行が録画中のまま何も出なかった)
LOST_WARN = "録画の部品が応答していません。続くときはアプリを起動し直してください(録れた分は残ります)"


ENGINE_OF_DEVICE = {"vulkan": "A", "cuda": "C"}   # 文字起こしのエンジン A = whisper.cpp の Vulkan・C = CUDA(⚙ と同じ名前)


def _hms(ms):
    return time.strftime("%H:%M:%S", time.localtime(ms / 1000.0))


def stage_lines(run):
    """1 本の実行の段ごとの始めと終わりの時刻・かかった秒を 1 段 1 行で(友人のログ friendapp.log 用。友人の PC が遅い原因を後から追うため)。
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
    return [transcribe_line(who, rec) for rec in transcribe_records(run, read_doc)]


def transcribe_records(run, read_doc=None):
    """この実行が文字起こしした文書ごとの認識の記録(recognition.runs の最後。段の始まりより後の物だけ)。ログの行と診断(friendapp/diag)が読む。
    流れ作業(書き出しの段の最中に先に頼んだ分。段の印 early)は書き出しの段の始まりから数える(文字起こしの段の始まりより前に済んでいる。
    この PC の道具は頼んだ糸の中で文字起こしを終えるので、印 earlyAt は 1 本目が済んだあと)"""
    read_doc = read_doc or _read_doc
    steps = {s.get("key"): s for s in getattr(run, "steps", None) or []}
    tx = steps.get("transcribe") or {}
    starts = [tx.get("startedAt")] + ([(steps.get("export") or {}).get("startedAt"), tx.get("earlyAt")] if tx.get("early") else [])
    t0 = min([t for t in starts if isinstance(t, int) and not isinstance(t, bool)], default=None)
    out = []
    for tid in getattr(run, "docs", None) or []:
        d = read_doc(tid)
        runs = ((d or {}).get("recognition") or {}).get("runs") if isinstance(d, dict) else None
        rec = runs[-1] if isinstance(runs, list) and runs and isinstance(runs[-1], dict) else None
        if rec is None or (t0 is not None and isinstance(rec.get("at"), (int, float)) and rec["at"] < t0):
            continue
        out.append(rec)
    return out


def export_records(run, read_doc=None):
    """この実行の文書ごとの書き出しの記録(文書の clip.export の作り方・元の形・段ごとの秒・GPU で作れなかった理由)。診断が読む"""
    read_doc = read_doc or _read_doc
    out = []
    for tid in getattr(run, "docs", None) or []:
        ex = (((read_doc(tid) or {}).get("clip") or {}).get("export")) or {}
        got = {k: ex[k] for k in ("encoder", "input", "secs", "gpuError") if ex.get(k) is not None} if isinstance(ex, dict) else {}
        if got:
            out.append(got)
    return out


def _read_doc(tid):
    try:
        return _fsio.read_json_or(_docloc.doc_file(str(tid), ".json"), None, kind=dict)
    except Exception:
        return None


class FriendQueue(_runqueue.Queue):
    """玄関の ② の待ち行列(区間だけの依頼の後の解析を飛ばす)"""

    def __init__(self, studio_book, log_dir, log=None):
        self.learning_reader = _learning.Learning(_learning.learning_dir())   # 学習の束だけ(③ の読み込みは渡さない)
        _wire.install(tool="friendapp", tmp_dir=lambda: _workdata.TMP_DIR, dict_learned=self.learning_reader.dict_learned)
        tools = _tools.LocalTools(learning=self.learning_reader, studio=_studiobook.LocalStudio(studio_book))
        super().__init__(None, poll=0.5, log=log, tools=tools, log_dir=log_dir)
        self.learning = self.learning_reader

    def _studio_video(self, vid):
        return self.tools.studio_video(vid)

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
        self.diag = None   # 診断の係(friendapp/diag.Diag。玄関が起こしたあとに入れる。テストは None)
        self.app_dir = os.path.join(places["data"], "app")
        self.queue = queue_factory(places["studio"], os.path.join(self.app_dir, "logs"), log=self.log)
        self.queue.set_finished_hook(self.after_run)
        self.live = live_factory(places, lambda: self.queue, self.log) if live_factory is not None else None
        if self.live is not None:
            self.queue.set_live_hook(self.live_submit)
            self.live.on_tick = self.live_tick
        self._previews = []
        self._rec_lost = {}   # 録画元 id -> 答えなくなった時刻(秒。LOST_NOTICE)
        self._pv_lock = threading.Condition()
        self._mk_lock = threading.Lock()
        self._pv_thread = threading.Thread(target=self._preview_loop, name="friend-preview", daemon=True)
        self._pv_thread.start()
        self.reconcile()

    # ------------------------------------------------------------ ② の状態
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
            if not r.get("runId"):   # ② に積む前に閉じた(動画を写している途中・録画を始める途中)
                self.inbox.fail(r["id"], "前回アプリを閉じたときに依頼が途中で止まりました。[もう一度送る] で送り直してください")
            elif rec:
                packs = [p for p in (rec.get("packs") or []) if isinstance(p, str)]
                self.inbox.finished(r["runId"], rec.get("state"), rec.get("error") or "", [{"dir": p} for p in packs],
                                    case=_case_from(rec.get("resultPath")))
            else:
                self.inbox.finished(r["runId"], "error", "前回アプリを閉じたときに依頼が途中で失われました。[もう一度送る] で送り直してください", [])

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
        if row is None and getattr(run, "request_id", None):   # ライブの切り抜き 1 本の実行(封筒の requestId = 受信箱の行の id)
            row = self.inbox.row(run.request_id)
            clip = row is not None and row.get("kind") == "live"
        if row is None or (row.get("runId") != run.id and not clip):
            return
        if self.diag is not None:   # 依頼 1 件ごとの診断(段ごとの秒・道具の終了コード。friendapp/diag)
            try:
                self.diag.run(run, row, transcribe_records(run), exports=export_records(run))
            except Exception as e:   # noqa: BLE001  (診断で届けるのを止めない)
                self.log("診断を書けませんでした: %s" % e.__class__.__name__)
        if run.result_path:
            try:
                path = _outbox.build(run.result_path, self.app_dir, request_id=row["id"], log_path=os.path.join(self.app_dir, "logs", "friendapp.log"))
                if path:
                    self.log("送り返しの zip を作りました: %s" % os.path.basename(path))
            except Exception as e:   # 送り返しが作れなくても受信箱には届ける
                self.log("送り返しの zip を作れませんでした: %s" % e.__class__.__name__)
        dirs = [d for d in run.all_packs() if os.path.isdir(_fsio.long_path(d))] if run.state == "done" else []
        try:
            secs = [_preview.pack_seconds(d) for d in dirs]
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
        try:
            got = self.inbox.finished(run.id, run.state, error, packs, case=_case_from(run.result_path))
        except Exception as e:   # noqa: BLE001  (行を「作っている」のまま残さない。fail が診断にも書く)
            self.log("届いた物を受信箱に入れられませんでした: %s %s" % (e.__class__.__name__, str(e)[:160]))
            self.inbox.fail(row["id"], "できた物を受信箱に入れられませんでした(%s %s)。アプリを開き直してください" % (e.__class__.__name__, str(e)[:80]))
            return
        if got and got["state"] == "arrived":
            self._want_previews(got["id"])

    def _want_previews(self, rid):
        with self._pv_lock:
            if rid not in self._previews:
                self._previews.append(rid)
            self._pv_lock.notify()

    # ------------------------------------------------------------ ライブ
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
        try:
            self.live.wait_recorder()
            return self.live.submit(env, bundle, ctx=ctx)
        except Exception as e:   # 受付の失敗(配信中でない・録画を始められない・空き容量など)も診断へ。断りはそのまま呼んだ側へ
            self._diag("live", rid=env.get("requestId"), summary="ライブの受付に失敗しました: %s" % (str(e).splitlines()[0][:200] if str(e) else e.__class__.__name__),
                       detail="%s: %s" % (e.__class__.__name__, str(e)[:2000]), stage="submit", outcome={"state": "refused", "error": e.__class__.__name__})
            raise

    def _diag(self, kind, **kw):
        """診断を 1 つ書く(診断の係が無い = テスト・書けない = 何もしない)"""
        if self.diag is None:
            return None
        try:
            return self.diag.write(kind, **kw)
        except Exception as e:   # noqa: BLE001  (診断で玄関を止めない)
            self.log("診断を書けませんでした: %s" % e.__class__.__name__)
            return None

    def live_tick(self):
        """ライブ係の見回りのたび: この PC のライブの行ごとに、録画が終わったか・書き出しと切り抜きの実行が残っているか・
        検出がまだ採用しうるか(detect_hold)・配信後の追加を待つかを見て行を進める(組・届いた・失敗)。録画元につながらないときはその行を飛ばす
        (分からないまま閉じない)。行を閉じるときは、パックが無ければ原因ごとの理由(live_cause)を渡し、成功・失敗とも診断(kind live)を書く"""
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
            if recs is None:   # 録画元が答えない = 分からないので閉じない。長く続けば知らせる
                self._live_lost(r["id"], rc)
                continue
            self._rec_lost.pop(rc, None)
            raw = recs.get(rec)
            recording = bool(raw and raw.get("active"))
            busy = self.live.busy_recording(rc, rec) or any(x.get("requestId") == r["id"] and x.get("state") in ("queued", "running") for x in runs)
            waiting = ""
            if raw is not None and not recording and not busy:
                hold = getattr(self.live, "detect_hold", None)
                waiting = self.live.after_hold(rc, raw) or (hold(rc, raw) if hold is not None else "")
            closing = r["state"] == "recording" and not recording and not busy and not waiting and not lv.get("finished")
            facts = self._live_facts(rc, rec, raw) if closing else None
            if not closing and not recording and lv.get("phase") == "recording":   # 録画が終わったが行はまだ閉じない(書き出し・配信後の追加の待ち):
                self._live_ended(r, rc, rec, raw, waiting)                         # 途中の診断を 1 回(閉じる前にアプリを閉じても材料が残る)
            why = live_cause(facts, lv.get("lastError")) if closing and not r["packs"] else None
            warn = self._live_blocked(r["id"], raw) if recording else ""
            hint = getattr(self.live, "adopt_hint", lambda _rc, _rec: "")(rc, rec) if recording and not warn else ""
            if self.inbox.live_update(r["id"], recording, busy, waiting, why=why, warn=warn, hint=hint):
                self._want_previews(r["id"])
            if closing:
                self._live_closed(r["id"], facts, why)

    def _masked(self, x):
        """診断に載せる前の伏せ字(診断の口の mask_tree。無ければそのまま)"""
        mask = getattr(self.diag, "mask_tree", None)
        return mask(x) if mask else x

    def _live_ended(self, r, rc, rec, raw, waiting):
        """録画が終わった見回り(行の phase が録画中から変わる 1 回): 診断 kind live・stage ended(閉じたときの close と同じ材料)。
        診断は行を閉じたときにしか書いていなかったので、配信後のアーカイブ待ち(afterStream)が長い・閉じる前にアプリを閉じると、作る人に何も届かなかった"""
        if self.diag is None:
            return
        facts = self._live_facts(rc, rec, raw)
        lv = r.get("live") or {}
        outcome = {"state": r.get("state"), "packs": len(r.get("packs") or []), "clipRuns": len(lv.get("done") or []), "errors": lv.get("errors") or 0,
                   "lastError": lv.get("lastError") or "", "waiting": waiting or ""}
        self._diag("live", rid=r["id"], summary="ライブ: 録画が終わりました(パック %d 本・%s)" % (outcome["packs"], waiting or "残りを作っています"),
                   stage="ended", outcome=self._masked(outcome), live=self._masked(facts or {}))

    def _live_lost(self, rid, rc):
        """録画元 rc が答えない見回り: LOST_NOTICE 秒続いたら行に LOST_WARN・診断(kind live・stage lost)を 1 回。答えたら次の見回りで消える"""
        since = self._rec_lost.setdefault(rc, time.time())
        if time.time() - since < LOST_NOTICE:
            return
        if self.inbox.live_warn(rid, LOST_WARN) and self.diag is not None:
            self.diag.once("lost-" + rid, 6 * 3600, "live", rid=rid, summary=LOST_WARN, stage="lost", live={"recorder": rc, "sinceSec": int(time.time() - since)})

    def _live_blocked(self, rid, raw):
        """録画元が YouTube に断られ続けて BLOCKED_NOTICE 秒たった -> 行に出す知らせ(無ければ "")。初めて出すとき診断(kind live・stage blocked)を 1 回"""
        at = (raw or {}).get("blockedAt")
        if not at or time.time() * 1000 - at < BLOCKED_NOTICE * 1000:
            return ""
        if self.diag is not None:
            self.diag.once("blocked-" + rid, 6 * 3600, "live", rid=rid, summary=BLOCKED_WARN, stage="blocked",
                           live={"blockedAt": at, "state": raw.get("state"), "message": raw.get("message"), "segments": raw.get("segments")})
        return BLOCKED_WARN

    def _live_facts(self, rc, rec, raw):
        fn = getattr(self.live, "live_facts", None)
        if fn is None:
            return {}
        try:
            return fn(rc, rec, raw)
        except Exception as e:   # noqa: BLE001  (材料が読めなくても行は閉じる)
            self.log("ライブの診断の材料を読めませんでした: %s" % e.__class__.__name__)
            return {"factsError": e.__class__.__name__}

    def live_row(self, rid):
        """ライブの行の録画の、録画元の今の行(生の行)か None(つながらない・無い)"""
        lv = (self.inbox.row(rid) or {}).get("live") or {}
        try:
            return (self.live.recordings(lv.get("recorder")) or {}).get(lv.get("recording")) if self.live is not None else None
        except Exception:   # noqa: BLE001
            return None

    def live_cancelled(self, rid, before=None):
        """録画中のライブを友人が [取り消す] で止めた(行は消えることがある = 消す前に): 閉じたときと同じ診断(パック 0 本で取り消したときの原因を残す)。
        before = 止める前に読んだ録画の行(止めた直後は録画元の一覧が読めず、友人の診断の録画の長さが空だった。10-21 の 2 本)"""
        lv = (self.inbox.row(rid) or {}).get("live") or {}
        rc, rec = lv.get("recorder"), lv.get("recording")
        raw = self.live_row(rid) or before   # 録画元の今の状態(録画の長さ・取れなかった理由の材料。どちらも無ければ無しで書く)
        self._live_closed(rid, self._live_facts(rc, rec, raw), {"code": "cancelled", "text": "録画中に [取り消す] で止めました"})

    def _live_closed(self, rid, facts, why):
        """ライブの行を閉じた: friendapp.log に 1 行・診断(kind live。成功・失敗とも。秘密は diag が伏せる)"""
        r = self.inbox.row(rid) or {}
        lv = r.get("live") or {}
        packs = len(r.get("packs") or [])
        summary = "ライブ %s: パック %d 本" % (r.get("state") or "?", packs) + (" / %s" % (why or {}).get("text") if why else "")
        self.log("ライブの行を閉じました 依頼=%s 状態=%s パック=%d 理由=%s" % (rid, r.get("state"), packs, (why or {}).get("code") or "-"))
        if self.diag is None:
            return
        outcome = {"state": r.get("state"), "packs": packs, "groups": len(r.get("groups") or []), "cause": lv.get("cause"),
                   "lastError": lv.get("lastError") or "", "errors": lv.get("errors") or 0, "clipRuns": len(lv.get("done") or []),
                   "phase": lv.get("phase"), "startedAt": lv.get("startedAt"), "endedAt": lv.get("endedAt"), "finished": lv.get("finished")}
        code = (why or {}).get("code") or ""
        self._diag("live", rid=rid, summary=summary, detail=(why or {}).get("text") or "", code=code if code.startswith("live") else None,
                   stage="close", outcome=self._masked(outcome), live=self._masked(facts or {}))

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
            except Exception as e:   # 確認用の動画が無くても受け取る・見送るは決められる
                self.log("確認用の動画を作れませんでした: %s" % e.__class__.__name__)

    def make_previews(self, rid):
        """届いた行のパック 1 本ずつの確認用の動画(480p・字幕なし。① pipeline/pack/preview の clip_preview。C-3-3)を
        <玄関>/previews/<依頼 id>-<n>.mp4 に(n = 受信箱の 1 本ずつの枠の番号)。1 つずつ(裏の糸と呼んだ側が同じ物を二重に作らない)"""
        with self._mk_lock:
            self._make_previews(rid)

    def _make_previews(self, rid):
        t0, made, err = time.time(), [0, 0], ""   # made = [作れた本数, 作れなかった本数]
        try:
            self._make_previews_of(rid, made)
        except Exception as e:
            err = "%s %s" % (e.__class__.__name__, str(e)[:300])
            raise
        finally:
            if self.diag is not None and (made[0] or made[1] or err):   # 確認用の動画づくりの秒(友人の PC で見られなかった・遅い)
                bad = bool(err) or (made[1] and not made[0])
                self.diag.write("error" if bad else "preview", rid=rid, summary=err or "確認用の動画 %d 本・作れなかった %d 本 %.1f 秒" % (
                    made[0], made[1], time.time() - t0), stage="preview", sec=round(time.time() - t0, 1), count=made[0], missed=made[1],
                    tools=self.diag.tools_since(int(t0 * 1000) - 1000))

    def _make_previews_of(self, rid, made):
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
            tmp = _preview.clip_preview(dirs[0], log=self.log) if dirs else None
            if not tmp:
                made[1] += 1 if dirs else 0
                continue
            dest = os.path.join(folder, "%s-%d.mp4" % (rid, g["n"]))
            shutil.move(_fsio.long_path(tmp), _fsio.long_path(dest))
            self.inbox.set_preview(rid, g["n"], dest)
            made[0] += 1

    def reload_learning(self):
        """学習の束を取り直したとき(同期): machine の learningDir の束を、② の読み手に入れ直す(同じ物を道具と辞書の版が使う)"""
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


def _minutes(sec):
    return "%d 分" % max(1, int(round(sec / 60.0))) if isinstance(sec, (int, float)) and not isinstance(sec, bool) and sec > 0 else "? 分"


def live_cause(facts, last_error=""):
    """ライブの行がパックの無いまま閉じるときの理由 {"code", "text"}。facts = FriendLive.live_facts の形(読めない欄は無くてよい)。
    当てる順: 切り抜きの実行の失敗(lastError)→ 書き出しの失敗 → 自動の採用を諦めた → 検出が測っていない → 候補はあったが採用されない →
    チャットが取れず音だけで候補 0 → 候補 0。文の頭の印(progress.LIVE_MARKS)で友人の言葉が決まる。配信後の追加が無い・失敗した理由は後ろに添える"""
    f = facts if isinstance(facts, dict) else {}
    pd = f.get("peaksDoc") if isinstance(f.get("peaksDoc"), dict) else None
    det = f.get("detect") if isinstance(f.get("detect"), dict) else {}
    wk = f.get("worker") if isinstance(f.get("worker"), dict) else {}
    rec = f.get("recording") if isinstance(f.get("recording"), dict) else {}
    after = f.get("afterStream") if isinstance(f.get("afterStream"), dict) else {}
    tail = ""
    if after.get("state") in ("none", "error"):
        tail = "(配信後の追加: %s)" % (str(after.get("message") or after.get("label") or after.get("state"))[:200])
    if last_error:
        return {"code": "error", "text": str(last_error)[:300] + tail}

    def say(code, text):
        return {"code": code, "text": "%s %s、パックができませんでした%s" % (_progress.LIVE_MARKS[code], text, tail)}
    mins = _minutes(rec.get("sec"))
    if rec.get("blocked"):   # 録画元が bot と判定されて止めた(10-23: 前は「検出が動かない・起動し直して」と誤って出ていた)
        return say("liveBlocked", "YouTube に bot と判定されて録画できず(録れた長さ %s)" % mins)
    ex = [x for x in f.get("exportFailures") or [] if x]
    if ex:
        return say("liveExport", "切り抜く所を録画から書き出せず(%s)" % str(ex[0])[:200])
    gu = [x for x in f.get("givenUp") or [] if isinstance(x, dict)]
    if gu:
        return say("liveAdopt", "切り抜く所を自動で採用できず(%s)" % str(gu[-1].get("message") or "")[:200])
    if pd is None or not pd.get("measuredSec"):
        why = wk.get("error") or wk.get("message") or ("ワーカーが動いていません" if not wk.get("running") else "")
        return say("liveNoDetect", "録画 %s の盛り上がりを測った記録が無く(%s)" % (mins, str(why)[:200] or "理由が分かりません"))
    cands = int(det.get("frame") or 0) + int(det.get("bench") or 0) + int(det.get("adopted") or 0)
    if cands:
        return say("liveLate", "候補 %d 件が切り抜きに回らないまま終わり" % cands)
    if pd.get("chat") in ("none", "restarting", "off"):
        return say("liveNoChat", "チャットを読み取れず(%s)、音だけで録画 %s を測っても候補が 0 件で" % (str(pd.get("message") or pd.get("chat"))[:200], mins))
    return say("liveNone", "録画 %s(測った %s)に盛り上がった所(候補)が 0 件で" % (mins, _minutes(pd.get("measuredSec"))))
