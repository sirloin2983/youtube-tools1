# -*- coding: utf-8 -*-
"""友人の玄関のライブ係(notes:docs/design/friend-history.md の 7 章、docs/spec/friend.md の 2-15)。

友人の PC の ② のライブ係 = flow/livesession.LiveSession を継いだ FriendLive。入口 app を読まずに作る:
  設定に関わらずオン(always_on)・どの封筒も依頼の決まりで(request_all = 検出・自動の採用・パックまで)・スタジオなしの採用(LocalMarks = 親の既定)・
  届けない(deliver_for なし = 親の既定)・6 時間の見回りなし(親の既定)・自動の採用の上限は束の adopt.top(bundle_top)・空き容量の下限(machine の diskMinGB)。
  ② の待ち行列(engine.FriendQueue)の set_live_hook で封筒 kind live を回し、書き出した切り抜きは同じ待ち行列へ(runner)。

違うところ(友人の PC だけ):
  - 依頼と録画の結びつきは受信箱の側(② flow/live_rules.RequestBook。ユーザーの PC の入口と 1 つ・友人の PC は届けない)
  - 録画の置き場所は一時保管の中(<作業>/ライブの録画)。本番版への作り直し(P4)はしない(A-14)
  - [すべて止めて終了]・exe の「止める」 は録画中でも録画の部品まで止める(親の close は録画中なら残す)。止めても録画の記録は「録画中」のまま =
    次に開いたとき録画の部品が起動して(見回り)、同じ録画を新しいセッションで続ける(pipeline/ingest/rec_core の load)
  - 配信後のアーカイブからの追加(M7)の解析は、② の道具のスタジオなしの台帳(flow/studiobook.LocalStudio)へ(studio_call の 3 つの口だけを写す)
  - 録画中に依頼の設定(1 時間の枠・長さ・配信後の追加)を差し替えられる(change_request。C-2-11)
  - 録画の片付けはユーザーの PC と同じ決まり(10-24。flow/live_retire.fate): アーカイブ化を確かめたら消す・非公開・見られないと分かるか
    終わって 24 時間たってもアーカイブにならなければ 1 本につないで名前に「非公開」(録画元の keep)・それまでは消さない(配信後の追加が済んでから)
受信箱の行と録画を結ぶ見回り(行の状態・組)は engine が持つ(on_tick)。録画が終わっても検出がまだ採用しうる間は行を閉じさせない(detect_hold)・
閉じたときの診断の材料(live_facts)はここが集める。
"""
import os
import time

from flow import live_export as _lx, live_retire as _retire, livesession as _ls
from pipeline.ingest import rec_core as _rec_core
from ytt import layout, tools

from flow.live_rules import RequestBook
from .live import REC_FOLDER, REQUESTS_NAME, STORE_DIR, settings_label

CLEAN_EVERY = 600.0                 # 録画の片付けを見る間隔(秒)
KEEP_RETRY = 6 * 3600.0             # 1 本につなげなかった録画(keepError)をやり直す間隔(秒。10 分ごとだと長い録画を何度も写して重い。10-25)
RECORDER_WAIT = 20.0                # 送ったとき、録画の部品が起動するまで待つ秒
REC_PORT_ENV = "YTT_FRIEND_REC_PORT"   # 録画の部品の番号(exe が選ぶ。無ければ 8730)
DETECT_HOLD_EXTRA = 900.0           # 録画が終わってから自動の採用を待つ上限 = 依頼の待ち(分)+ この秒(帳簿を締める遅れと採用の見回りの分)


def recorders(env=None):
    """録画元の一覧: 手元の 1 つ。番号は exe がその都度空いている物を選んで YTT_FRIEND_REC_PORT で渡す(C-1-3。ユーザーの入口の
    8730 と取り合わない = C-0)。無い・読めなければ空 = 決まりの 8730(開発の PC)"""
    env = os.environ if env is None else env
    raw = (env.get(REC_PORT_ENV) or "").strip()
    port = int(raw) if raw.isdigit() and 1024 <= int(raw) <= 65535 else 0
    return [dict(_ls.LOCAL, url="http://127.0.0.1:%d" % port)] if port else []


class FriendLive(_ls.LiveSession):
    """友人の PC のライブ係(上の説明)。places = friendapp/places.setup の値・queue() -> ② の待ち行列(engine.FriendQueue)。
    disk_min_gb = 空き容量の下限(GB。None = 見ない)。on_tick() = 見回りのたびに呼ぶ(engine が受信箱の行を進める)"""

    def __init__(self, places, queue, log=None, spawn=True, disk_min_gb=None, clock=time.time):
        self.places = places
        self.queue_fn = queue
        self.on_tick = None
        self.clock = clock
        self._clean_at = 0.0
        self._keep_tried = {}   # 録画の id -> 1 本につなぐのを最後に頼んだ時刻(keepError のやり直しの間隔)
        store = os.path.join(places["data"], STORE_DIR)
        super().__init__(layout.src_root(), os.path.join(places["data"], "app", "logs"),
                         requests=RequestBook(os.path.join(store, REQUESTS_NAME), clock=clock, log=log, deliver=False), cfg=self.live_cfg, log=log, spawn=spawn,
                         store_dir=store, out_dir=lambda: self.places["cases"], runner=self.queue_fn)
        self.always_on = self.request_all = True   # 設定に関わらずオン・どの封筒も依頼の決まり
        self.disk_min_gb = disk_min_gb
        self.auto_max = self.bundle_top

    # ------------------------------------------------------------ 設定(友人の PC は固定)
    def rec_folder(self):
        return os.path.join(self.places["cases"], REC_FOLDER)

    def live_cfg(self):
        """ライブの設定(ホームの設定 live の代わり)。検出・採用は依頼の設定で動く(結びつきのある録画だけ)・
        配信後の追加は依頼の afterStream で(autoAfterStream は依頼でない録画の物 = 使わない)・書き出したあとはパックまで"""
        return {"enabled": True, "folder": self.rec_folder(), "recorders": recorders(), "quality": _ls.DEFAULT_QUALITY,
                "autoAfterStream": False, "auto": {"after": "auto"}}

    def _request_label(self, item):
        """依頼を録画に結びつけたときの記録の 1 行(ライブの 6 つの設定)"""
        return settings_label(item["settings"])

    # ------------------------------------------------------------ スタジオの口(配信後の追加 M7 の解析だけ。② の道具の LocalStudio へ)
    def _studio(self):
        q = self.queue_fn()
        return getattr(getattr(q, "tools", None), "studio", None) if q is not None else None

    def studio_call(self, method, path, body=None):
        """live_archive が呼ぶスタジオの 4 つの口を、② の道具のスタジオなしの台帳へ写す -> (HTTP の番号, JSON)。ほかは (None, {"message"})"""
        st = self._studio()
        if st is None:
            return None, {"message": "解析の部品がまだ準備できていません"}
        try:
            if method == "GET" and path.startswith("/api/video?id="):
                return st.video(path[len("/api/video?id="):])
            if method == "POST" and path == "/api/queue/add":
                items = (body or {}).get("items") or []
                return 200, st.analyze_add(items[0] if items else {}, (body or {}).get("settings"))
            if method == "GET" and path == "/api/queue":
                return 200, {"items": st.analyze_items()}
        except Exception as e:   # noqa: BLE001  (道具の断り = 理由の文を返す。配信後の追加の記録に出る)
            return 400, {"message": str(e)[:200]}
        return None, {"message": "切り抜きスタジオがありません"}

    def studio_queue(self):
        st = self._studio()
        batch = getattr(st, "batch", None)
        return batch.snapshot() if batch is not None else None

    # ------------------------------------------------------------ 録画の部品
    def wait_recorder(self, timeout=RECORDER_WAIT):
        """送ったとき: 手元の録画の部品が応答するまで待つ(動いていなければ見回りを起こして起動してもらう)-> 応答したか"""
        local = next((r for r in self.recorders() if _ls.is_local_url(r.get("url") or "")), None)
        if local is None:
            return False
        end = time.time() + timeout
        while True:
            if self.ping(local, 1.0):
                return True
            if time.time() >= end or self._halt.is_set():
                return False
            if self._thread is None:   # 見回りの糸が無い(テスト・起動の途中): ここで 1 回見回る = 起動する
                self.tick()
            else:
                self.wake.set()
            time.sleep(0.5)

    def _stop_recorder(self):
        """終了: 録画中でも、この玄関が起こした録画の部品は孫ごと止める(録画の記録は「録画中」のまま = 次に開いたとき同じ録画の続きから)。
        起こしていない部品が録画中なら止められない(記録に出す)"""
        got = super()._stop_recorder()
        own = self._own_proc()
        if got == "kept" and own is not None:
            tools.kill_tree(own, wait=5.0)
            self.log("録画中の録画の部品を止めました(次に開いたとき、配信中なら同じ録画の続きから録ります)")
            return "killed"
        if got == "kept":
            self.log("この玄関が起こしていない録画の部品が録画中なので、止められませんでした")
        return got

    def recordings(self, rc_id):
        """録画元の録画の一覧 -> {録画の id: 生の行(active を足す)} か None(つながらない = 分からない)"""
        rc = self.find(rc_id)
        rows = _lx.rec_list(self.call, rc) if rc is not None else None
        if rows is None:
            return None
        return {r["id"]: dict(r, active=r.get("active") is True or r.get("state") in _rec_core.ACTIVE) for r in rows}

    def active_count(self):
        """録画中の本数(exe の閉じるときの確認とアイコンの文に出す。録画元の一覧を数秒覚えて読む)"""
        try:
            return sum(1 for r in self.recent() if r.get("active") is True)
        except Exception:   # noqa: BLE001  (数えられなければ 0)
            return 0

    def stop_recording(self, rc_id, rec):
        """受信箱の [録画を止める]: 録画元の録画を止める(録画を閉じる = そのあとの書き出し・パックは続く)。だめなら LiveError"""
        rc = self._ids(rc_id, rec)
        code, d = self.call(rc, "POST", "/live/%s/stop" % rec, {}, timeout=_ls.STOP_TIMEOUT)
        self._recent = None
        if code == 200:
            self.log("ライブ: 録画を止めました %s" % rec)
            return True
        if code is None:
            raise self._down(rc)
        raise _lx.LiveError("録画を止められませんでした(%s)" % (((d or {}).get("message") if isinstance(d, dict) else "") or "HTTP %s" % code), 409)

    def restart_recording(self, rc_id, rec, whole=False):
        """止まった録画のやり直し(玄関の更新の見回りが呼ぶ)-> "reconnect"・"restarted"・"inactive"・"respawn"・""(できなかった)。
        ふだんは録画元にその録画の子(取得・ffmpeg)だけを止めてもらう(POST /live/<id>/reconnect = 同じ録画の新しいセッション)。
        whole か録画元が返事をしないときは、この玄関が起こした録画の部品を PID で止める(見回りが起こし直し、録画中の録画を続きから録る)"""
        rc = self._ids(rc_id, rec)
        code = None
        if not whole:
            code, d = self.call(rc, "POST", "/live/%s/reconnect" % rec, {}, timeout=10.0)
            self._recent = None
            if code == 200:
                return str((d or {}).get("did") or "") if isinstance(d, dict) else ""
        own = self._own_proc()
        if (code is not None and not whole) or own is None:
            return ""
        tools.kill_tree(own, wait=5.0)
        self._recent = None
        self.wake.set()
        self.log("ライブ: 録画 %s が止まったので、録画の部品を起こし直します(録画中の録画は続きから)" % rec)
        return "respawn"

    def change_request(self, rc_id, rec, rid, settings):
        """録画中の依頼の設定を差し替える(C-2-11。1 時間の枠・長さ(固定の秒 / 自動 = 場面ごと)・配信後の追加)。
        結びつき(requests.json)を書き換え、検出のワーカーへの config.json もすぐ書く = これから確定・採用・切り出す物から効く
        (枠と長さはワーカーが読み直したとき・配信後の追加は配信が終わったときに読む。もう切った物は作り直さない)。
        -> 差し替えた結びつきの項目。録画がその依頼に結びついていなければ LiveError(409)"""
        item = self.requests.get(rc_id, rec)
        if item is None or item.get("rid") != rid:
            raise _lx.LiveError("この録画の依頼が見つかりません(録画が終わって片付けたかもしれません)", 409)
        got = self.requests.update(rc_id, rec, settings)
        if got is None:
            raise _lx.LiveError("この録画の依頼が見つかりません(録画が終わって片付けたかもしれません)", 409)
        self.log("ライブ: 依頼 %s の設定を録画の途中で変えました(%s)" % (rid, settings_label(got["settings"])))
        try:
            self.detector.write_config()
        except Exception as e:   # noqa: BLE001  (書けなくても次の見回りが書く)
            self.log("ライブ: 検出の設定を書けませんでした(次の見回りで書きます): %s" % e.__class__.__name__)
        return got

    def busy_recording(self, rc_id, rec):
        """その録画の書き出し・まとめて実行への受け渡しが途中か"""
        ex = self._exporter
        if ex is None:
            return False
        with ex.lock:
            return any(j.get("recorder") == rc_id and j.get("recording") == rec and (j.get("state") in _lx.ACTIVE or j.get("handoffWait"))
                       for j in ex.jobs)

    def after_hold(self, rc_id, raw):
        """配信後の追加(M7)をまだ待つ理由か ""(待たない)。raw = 録画元の一覧の生の行"""
        try:
            return self.archiver.after_stream_hold(rc_id, raw) or ""
        except Exception:   # noqa: BLE001  (分からなければ待たない)
            return ""

    def detect_hold(self, rc_id, raw, now=None):
        """録画が終わったあと、配信中の検出がまだ自動で採用しうる間の理由か ""(待たない)。raw = 録画元の一覧の生の行。
        待つのは、依頼の録画でワーカーが動いていて、帳簿を締める前か、締めたあと採用待ちの枠の候補が残る間だけ。
        録画の終わりから 依頼の待ち(分)+ DETECT_HOLD_EXTRA 秒を過ぎたら待たない(止まったワーカー・採用されない候補で行を閉じそびれない)"""
        try:
            return self._detect_hold(rc_id, raw, self.clock() if now is None else now)
        except Exception:   # noqa: BLE001  (分からなければ待たない)
            return ""

    def _detect_hold(self, rc_id, raw, now):
        rec = str((raw or {}).get("id") or "")
        req = self.requests.get(rc_id, rec)
        det = self.detector
        if req is None or not det.enabled() or not det.running():
            return ""
        ended = _lx.iso_epoch(raw.get("endedAt")) or _lx.iso_epoch(raw.get("lastPdt"))
        if ended is None or now - ended > req["settings"]["waitMin"] * 60 + DETECT_HOLD_EXTRA:
            return ""
        doc, peaks, _pending = det.view(rc_id, rec)
        if doc is None or not doc.get("ended"):
            return "配信中の検出が録画の終わりまで測り終えるのを待っています"
        if det.auto_count(rc_id, rec) >= det.auto_max(rc_id, rec):
            return ""
        given = {x.get("id") for x in det.given_up(rc_id, rec)}
        left = [p for p in peaks if p.get("state") == "frame" and not p.get("provisional") and p.get("id") not in given]
        return "配信中の候補 %d 件の自動の採用を待っています" % len(left) if left else ""

    def adopt_hint(self, rc_id, rec, now=None):
        """録画中の行に添える、切り抜く前の候補の知らせ(「候補 2 件・約 4 分後に切り抜きます」)か ""。
        届いた物が無いまま「録画中」だけが続き、候補があるのに切り抜く前に取り消された(10-21 の友人の 13 分の録画)"""
        try:
            w = self.detector.adopt_waiting(rc_id, rec) if self.detector.enabled() else None
        except Exception:   # noqa: BLE001  (分からなければ出さない)
            return ""
        if not w:
            return ""
        if w.get("capped") is not None:   # 上限に届いたあと「録画中」だけが続いた(10-21 の友人の 41 分の録画。残りの候補 11 件)
            return "自動で切り抜くのは %d 本まで(届きました)" % w["capped"]
        due = w.get("dueAt")
        if due is None:
            return "候補 %d 件" % w["count"]
        left = due - (self.clock() if now is None else now)
        return "候補 %d 件・%s切り抜きます" % (w["count"], "まもなく" if left <= 30 else "約 %d 分後に" % max(1, int(round(left / 60.0))))

    def live_facts(self, rc_id, rec, raw=None):
        """ライブの行を閉じたときの診断の材料(friendapp/diag の kind live。engine が伏せてから書く)。
        配信の記録(flow/live_report の build = 録画の長さ・候補と採用の数・遅れ・チャット・書き出しの数)から題と URL を除き、
        検出の記録(peaks.json)の測った秒・チャットの状態と理由・しきい値・音だけの候補、ワーカーの心拍、自動の採用を諦めた候補、
        書き出しの失敗の文、配信後の追加(archive.json の afterStream)、依頼の設定を足す。読めない欄は None"""
        raw = raw or {}
        row = {"recorder": rc_id, "id": rec, "active": raw.get("active") is True or raw.get("state") in _rec_core.ACTIVE,
               "endedAt": _lx.iso_epoch(raw.get("endedAt")), "firstPdt": _lx.iso_epoch(raw.get("firstPdt")), "lastPdt": _lx.iso_epoch(raw.get("lastPdt"))}
        out = {}
        try:
            rep = self.reporter.build(row, {}, self.clock(), True)
            info = rep.get("info") or {}
            first, last = row["firstPdt"], row["lastPdt"]
            out.update(recording={"sec": round(last - first, 1) if first is not None and last is not None and last >= first else None,
                                  "hours": info.get("hours"), "firstPdt": info.get("firstPdt"), "lastPdt": info.get("lastPdt"), "endedAt": info.get("endedAt"),
                                  "state": raw.get("state"), "message": raw.get("message"),
                                  "blocked": raw.get("message") in (_rec_core.BLOCKED, _rec_core.BLOCKED_ENDED)},   # bot と判定されて止めた(行の理由 liveBlocked)
                       samples=rep.get("samples"), detect=rep.get("detect"), tx=rep.get("tx"), exports=rep.get("exports"), disk=rep.get("disk"))
        except Exception as e:   # noqa: BLE001  (材料の一部が読めなくても残りは書く)
            out["reportError"] = e.__class__.__name__
        det = self.detector
        doc, peaks, _pending = det.view(rc_id, rec)
        if doc is not None:
            scores = [p.get("score") for p in peaks if isinstance(p.get("score"), (int, float))]
            out["peaksDoc"] = {k: doc.get(k) for k in ("measuredSec", "scoredSec", "ended", "chat", "message", "lag", "gaps", "lateFrom", "perHour",
                                                         "thr", "audioOnly", "lengthFrom", "shape", "moodShifts", "behindSec", "lateChat", "chatInfo")}
            out["peaksDoc"].update(skipped=len(doc.get("skipped") or []), peaks=len(peaks), maxScore=max(scores) if scores else None,
                                   audioOnlyPeaks=sum(1 for p in peaks if p.get("audioOnly")),
                                   provisional=sum(1 for p in peaks if p.get("provisional")), expired=sum(1 for p in peaks if p.get("expired")))
        else:
            out["peaksDoc"] = None
        hb = det.heartbeat() or {}
        out["worker"] = {"enabled": det.enabled(), "running": det.running(hb), "restarts": det.restarts, "lastExit": det.last_exit,
                         "chatRestarts": hb.get("chatRestarts"), "memMB": hb.get("memMB"), "behindSec": hb.get("behindSec"),
                         "message": hb.get("message") or "", "error": hb.get("error") or "", "at": hb.get("at")}
        out["givenUp"] = [{"start": x.get("start"), "end": x.get("end"), "message": x.get("message"), "at": x.get("at")}
                          for x in det.given_up(rc_id, rec)][-10:]
        try:
            out["exportFailures"] = [f.get("text") for f in self.exporter.failures() if f.get("recorder") == rc_id and f.get("recording") == rec][:10]
        except Exception as e:   # noqa: BLE001
            out["exportFailures"] = None
            out["exportError"] = e.__class__.__name__
        try:
            with self.archiver.lock:
                a = dict((self.archiver.info.get(self.archiver.key(rc_id, rec)) or {}).get("afterStream") or {})
            out["afterStream"] = {k: a.get(k) for k in ("state", "label", "message", "mode", "n", "at", "picked", "skipped")} if a else None
            if a:
                out["afterStream"]["jobs"] = len(a.get("jobs") or [])
        except Exception as e:   # noqa: BLE001
            out["afterStream"] = None
            out["afterStreamError"] = e.__class__.__name__
        req = self.requests.get(rc_id, rec)
        out["settings"] = dict(req["settings"]) if req else None
        out["autoMax"] = det.auto_max(rc_id, rec)
        return out

    # ------------------------------------------------------------ 見回り
    def _app_watch(self):
        return [("友人の受信箱の行の見回りでエラー", self._rows_tick), ("録画の片付けでエラー", self.clean_recordings)]

    def _rows_tick(self):
        fn = self.on_tick
        return fn() if fn is not None else None

    def clean_recordings(self, force=False):
        """終わった録画を片付ける(配信後の追加を待つ録画・書き出しの途中の録画は残す。決まりは flow/live_retire.fate):
        アーカイブ化を確かめたら消す・非公開・見られないと分かるか終わって 24 時間たてば 1 本につないで残す・ほかは待つ -> 消した(残した)録画の id"""
        now = self.clock()
        if not force and now - self._clean_at < CLEAN_EVERY:
            return []
        self._clean_at = now
        out = []
        for rc in self.recorders():
            rows = _lx.rec_list(self.call, rc)
            for r in rows or []:
                rec = r["id"]
                if r.get("active") is True or r.get("state") in _rec_core.ACTIVE or r.get("keeping"):
                    continue
                ended = _lx.iso_epoch(r.get("endedAt")) or _lx.iso_epoch(r.get("lastPdt"))
                if ended is None or self.busy_recording(rc["id"], rec) or self.after_hold(rc["id"], r):
                    continue
                if r.get("keepError") and now - self._keep_tried.get(rec, 0.0) < KEEP_RETRY:
                    continue
                fate = "private" if r.get("keepError") else _retire.fate(self.archiver.archived(rc["id"], r), self.archiver.unavailable(rc["id"], r),
                                                                         _retire.overdue(r, now))
                if fate == "delete":
                    code, _d = self.call(rc, "POST", "/live/%s/delete" % rec, {}, timeout=30.0)
                    if code == 200:
                        out.append(rec)
                        self.log("ライブ: アーカイブになった録画を消しました %s" % rec)
                elif fate == "private":
                    self._keep_tried[rec] = now
                    code, d = self.call(rc, "POST", "/live/%s/keep" % rec, {"name": _retire.private_name(r)}, timeout=30.0)
                    if code == 200 and isinstance(d, dict) and d.get("started"):
                        out.append(rec)
                        self.log("ライブ: 非公開・見られない配信の録画を 1 本につないで残します %s%s" % (rec, "(前は「%s」でつなげなかった)" % r["keepError"] if r.get("keepError") else ""))
        return out
