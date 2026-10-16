# -*- coding: utf-8 -*-
"""友人の玄関のライブ係(F2-6。notes:plan/f1-friend-requirements.md の A-5・A-13・A-14、docs/spec/friend.md の 2-15)。

友人の PC の ② のライブ係 = flow/livesession.LiveSession を継いだ FriendLive。入口 app の src/app/live.py の use_headless と同じ形を、app を読まずに作る:
  設定に関わらずオン(always_on)・どの封筒も依頼の決まりで(request_all = 検出・自動の採用・パックまで)・スタジオなしの採用(LocalMarks = 親の既定)・
  届けない(deliver_for なし = 親の既定)・6 時間の見回りなし(親の既定)・自動の採用の上限は束の adopt.top(bundle_top)・空き容量の下限(machine の diskMinGB)。
  ② の待ち行列(engine.FriendQueue)の set_live_hook で封筒 kind live を回し、書き出した切り抜きは同じ待ち行列へ(runner)。

違うところ(友人の PC だけ):
  - 依頼と録画の結びつきは受信箱の側(friendapp/live.RequestBook。③ human の live_requests は読まない)
  - 録画の置き場所は一時保管の中(<作業>/ライブの録画)。本番版への作り直し(P4)はしない(A-14 で廃止)
  - [すべて止めて終了]・起動役の [止める] は録画中でも録画の部品まで止める(親の close は録画中なら残す)。止めても録画の記録は「録画中」のまま =
    次に開いたとき録画の部品が起動して(見回り)、同じ録画を新しいセッションで続ける(pipeline/ingest/rec_core の load)
  - 配信後のアーカイブからの追加(M7)の解析は、② の道具のスタジオなしの台帳(flow/studiobook.LocalStudio)へ(studio_call の 3 つの口だけを写す)
  - 録画は終わって 3 日で消す(配信後の追加が済んでから。6 章の「確かめられないまま 3 日で消す」。アーカイブ化で消すのは線 D の LD-1)
受信箱の行と録画を結ぶ見回り(行の状態・組)は engine が持つ(on_tick)。
"""
import os
import time

from flow import live_export as _lx, livesession as _ls
from pipeline.ingest import rec_core as _rec_core
from ytt import layout, tools

from .live import REC_FOLDER, REQUESTS_NAME, STORE_DIR, RequestBook, settings_label

REC_KEEP_DAYS = 3                   # 終わった録画を消すまでの日数(配信後の追加が済んでから)
CLEAN_EVERY = 600.0                 # 録画の片付けを見る間隔(秒)
RECORDER_WAIT = 20.0                # 送ったとき、録画の部品が起動するまで待つ秒


class FriendLive(_ls.LiveSession):
    """友人の PC のライブ係(上の説明)。places = friendapp/places.setup の値・queue() -> ② の待ち行列(engine.FriendQueue)。
    disk_min_gb = 空き容量の下限(GB。None = 見ない)。on_tick() = 見回りのたびに呼ぶ(engine が受信箱の行を進める)"""

    def __init__(self, places, queue, log=None, spawn=True, disk_min_gb=None, clock=time.time):
        self.places = places
        self.queue_fn = queue
        self.on_tick = None
        self.clock = clock
        self._clean_at = 0.0
        store = os.path.join(places["data"], STORE_DIR)
        super().__init__(layout.src_root(), os.path.join(places["data"], "app", "logs"),
                         requests=RequestBook(os.path.join(store, REQUESTS_NAME), clock=clock, log=log), cfg=self.live_cfg, log=log, spawn=spawn,
                         store_dir=store, out_dir=lambda: self.places["cases"], runner=self.queue_fn)
        self.always_on = self.request_all = True   # 入口 app の use_headless と同じ値(設定に関わらずオン・どの封筒も依頼の決まり)
        self.disk_min_gb = disk_min_gb
        self.auto_max = self.bundle_top

    # ------------------------------------------------------------ 設定(友人の PC は固定)
    def rec_folder(self):
        return os.path.join(self.places["cases"], REC_FOLDER)

    def live_cfg(self):
        """ライブの設定(ホームの設定 live の代わり)。検出・採用は依頼の設定で動く(結びつきのある録画だけ)・P4 の作り直しはしない(A-14)・
        配信後の追加は依頼の afterStream で(autoAfterStream は依頼でない録画の物 = 使わない)・書き出したあとはパックまで"""
        return {"enabled": True, "folder": self.rec_folder(), "recorders": [], "quality": _ls.DEFAULT_QUALITY,
                "autoArchive": False, "autoAfterStream": False, "autoDelete": False, "auto": {"after": "auto"}}

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
        """録画中の本数(起動役の状態の窓の × が録画中だけ最小化になる。録画元の一覧を数秒覚えて読む)"""
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

    # ------------------------------------------------------------ 見回り
    def _app_watch(self):
        return [("友人の受信箱の行の見回りでエラー", self._rows_tick), ("録画の片付けでエラー", self.clean_recordings)]

    def _rows_tick(self):
        fn = self.on_tick
        return fn() if fn is not None else None

    def clean_recordings(self, force=False):
        """終わって REC_KEEP_DAYS 日たった録画を消す(配信後の追加を待つ録画・書き出しの途中の録画は残す)-> 消した録画の id"""
        now = self.clock()
        if not force and now - self._clean_at < CLEAN_EVERY:
            return []
        self._clean_at = now
        out = []
        for rc in self.recorders():
            rows = _lx.rec_list(self.call, rc)
            for r in rows or []:
                rec = r["id"]
                if r.get("active") is True or r.get("state") in _rec_core.ACTIVE:
                    continue
                ended = _lx.iso_epoch(r.get("endedAt")) or _lx.iso_epoch(r.get("lastPdt"))
                if ended is None or now - ended < REC_KEEP_DAYS * 86400 or self.busy_recording(rc["id"], rec) or self.after_hold(rc["id"], r):
                    continue
                code, _d = self.call(rc, "POST", "/live/%s/delete" % rec, {}, timeout=30.0)
                if code == 200:
                    out.append(rec)
                    self.log("ライブ: 終わって %d 日たった録画を消しました %s" % (REC_KEEP_DAYS, rec))
        return out
