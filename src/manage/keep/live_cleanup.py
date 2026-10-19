# -*- coding: utf-8 -*-
"""録画を自動で消す(線 D。notes:plan/line-d-live-clipping.md の 0-9 の最後。ユーザー決定。決定 3-73)の入口の側。
設定 live.autoDelete(既定オン。src/app/prefs.py)。オフなら何も消さない。リアルタイム切り抜きがオフ(live.enabled)のときも何もしない。

消すのは ごみ箱へ(録画の部品 src/pipeline/ingest/rec_core.py の delete が <置き場所>/ごみ箱/<日付>/録画/<録画の id> へ改名し、manifest.jsonl に元の場所。
録画の部品が 3 日(ytt/trashbin.KEEP_DAYS)より古い日付のフォルダを消す = その間は戻せる)。それでも戻すのは手間なので、条件は厳しめにする(迷ったら消さない・分からなければ消さない):
  1. アーカイブ化した録画(すぐ。src/flow/live_archive.py の Archiver が1本終えるたびに check を呼ぶ・見回りでも)
     - 録画元の一覧(GET /live/list)で、その録画が終わっている(active でない)
     - その録画の書き出しのジョブ(src/flow/live_export.py)が1つ以上あり、マークごとの最新のジョブが全部 done
       (録画に無い区間のマークは、アーカイブから書き出して done になっている)
     - 書き出しの途中・アーカイブからの書き出しの途中や待ち・失敗・取り消しのマークが1つも無い
     - その録画に「採用」のまま書き出していないマークが無い(親のマークの置き場 marks.adopted = スタジオか、スタジオなしは案件の 採用.json・マークの正本。
       置き場を持たない親だけスタジオの GET /studio/api/video に聞く。確かめられなければ消さない)
     - アーカイブ化を確かめた(archived = live_archive の Archiver.archived。消す直前に yt-dlp で確かめ直す: was_live・限定でない・
       アーカイブが録画の終わりまである)
     → 録画元の POST /live/<録画>/delete → その録画のジョブに recordingDeleted(時刻)を残す(スタジオの画面が「録画は消しました」と出す)
     (消してよいかの判断と、消したことを ② の記録に記すのは ② の口 src/flow/live_retire.py の Retire。OPT2 の 7x-1)。マークの正本は残す
  2. マークが1つも無い録画(試しに始めて止めた・見ただけ)
     - 録画が終わって no_mark_sec(24 時間)たった・入口の書き出しのジョブもマークの正本(live/marks)も無い
     - スタジオにマークが1つも無い(GET /studio/api/video?id=<録画>。スタジオに登録が無い録画も「マークなし」。つながらない・答えが読めなければ消さない)
     → スタジオの一覧の行を先に消す(POST /studio/api/video/delete {ifNoMarks: true} = 調べてから消すまでの間にマークが付いたら 409 で消さない)
     → 録画を消す(使用中で消せなければ、次の見回りでまた消す。スタジオの行はもう無いので 2 の条件のまま)
  3. 1 を満たさない録画(ユーザー決定「終わって 3 日で消す」= decisions 3-15 (fc)): 消せない理由が「書き出していないマークがある」
     「アーカイブ化をまだ確かめられていない」だけ(live_retire.stale_ok)の録画は、終わって STALE_SEC(3 日)たったら消す。
     スタジオに「採用のまま書き出していないマーク」がある・スタジオに確かめられないときは消さない。
     消す 1 日前(WARN_SEC)から「調子」に予告(live_failures.delete_notice)。ほかの理由(書き出しの途中など)は消さずに知らせる(keep_failure)
録画中・配信待ち・つなぎ直し中の録画は消さない(録画元も 409 で断る)。録画元につながらない・一覧を読めないときは何もしない。
配信後の全自動(線 D の M7。設定 live.autoAfterStream)がオンで、その録画の自動の切り抜きがまだ済んでいない間も消さない(hold。src/flow/live_archive.py の after_stream_hold)。
消したことは入口の記録(log)に1行ずつ残す。録画を消す API(録画元の …/delete)は入口のこの処理だけが呼ぶ(画面からの中継 /live/r/… は通さない)。
ここ(④)が持つのは 見回り(tick・check)・期限(24 時間・3 日・予告と知らせ)・録画元へ delete を送る・記録の 1 行。
書き出しのジョブ・マークの正本・検出の記録は直に読み書きせず、② の Retire(verdict・has_marks の読み口と recording_deleted の書き口)を通す。
"""
import threading
import time
import urllib.parse

from ytt import schemas, trashbin
from flow import live_failures   # 残っている録画の知らせの文。D-14
from flow import live_export as LX
from flow import live_retire   # 録画を消してよいかの判断と、消したことを記す ② の口(OPT2 の 7x-1)

NO_MARK_SEC = 24 * 3600.0      # マークの無い録画を消すまで(録画が終わってから)
INTERVAL = 600.0               # 見回り(入口の録画の見回り src/app/live.py の tick から)で調べる間隔
STALE_SEC = float(trashbin.KEEP_SEC)   # D-14: 終わってからこれだけたっても消せない録画を「調子」に知らせる。理由が live_retire.stale_ok だけなら、このとき消す(ユーザー決定)
WARN_SEC = 2 * 86400.0         # stale_ok の理由の録画を消す 1 日前から「調子」に予告する
DELETE_TIMEOUT = 60.0          # 録画元が消し終えるまで(大きな録画は数秒かかる)
REC_ACTIVE = ("waiting", "recording", "reconnecting")   # src/pipeline/ingest/rec_core.py の ACTIVE と同じ


class Cleaner:
    def __init__(self, live, enabled=None, studio=None, log=None, no_mark_sec=NO_MARK_SEC, interval=INTERVAL, clock=time.time, hold=None,
                 archived=None):
        """live: src/app/live.py の Live(録画元の一覧と要求。書き出しのジョブ・マーク・検出の記録は ② の口 live_retire.Retire(live) を通して読み書きする)。
        enabled(): 消してよいか(リアルタイム切り抜きがオンで、設定 live.autoDelete がオン)。
        studio(method, path, body) -> (HTTP の番号 か None(つながらない), JSON): 取り込んだスタジオの API(Live.studio_call)。
        hold(録画元の id, 録画元の一覧の 1 行) -> 消すのを待つ理由(空 = 待たない。M7 の配信後の全自動がまだ)。
        archived(録画元の id, 録画元の一覧の 1 行) -> アーカイブ化を確かめたか("" = 確かめた / 理由。live_archive の Archiver.archived。
        無ければ確かめられない = 終わって 3 日の期限まで消さない)。
        時間(no_mark_sec・interval)はテストで縮める"""
        self.live = live
        self.enabled = enabled or (lambda: False)
        self.hold = hold or (lambda rc_id, r: "")
        self.archived = archived or (lambda rc_id, r: live_retire.NOT_ARCHIVED)
        self.studio = studio or (lambda method, path, body=None: (None, {}))
        self.log = log or (lambda m: None)
        self.retire = live_retire.Retire(live, studio_marks=lambda rec: self._studio_marks(rec)[0])   # 親がマークの置き場を持たなければスタジオに聞く
        self.no_mark_sec, self.interval, self.clock = no_mark_sec, interval, clock
        self.lock = threading.Lock()
        self._last = 0.0
        self._said = {}   # 録画 -> 前に記録した「消せなかった」理由(見回りのたびに同じ行を書かない)
        self._kept = {}   # 録画 -> {"why", "endedAt", "title"}: 終わっているのに消せない録画と理由(D-14 の知らせ。見回りで更新)

    # --- 入口から ---
    def tick(self, force=False):
        """見回り(interval ごと。force なら今すぐ)。-> {"deleted": [録画の id]}"""
        out = {"deleted": []}
        if not self.enabled():
            return out
        now = self.clock()
        if not force and now - self._last < self.interval:
            return out
        self._last = now
        with self.lock:
            for rc in self.live.recorders():
                for r in LX.rec_list(self.live.call, rc) or []:   # つながらない・読めない録画元は何もしない
                    if self._consider(rc, r, now):
                        out["deleted"].append(r["id"])
        return out

    def check(self, rc_id, rec):
        """1本だけ確かめる(アーカイブからの書き出しが済んだとき・配信後の全自動が済んだとき。src/flow/live_archive.py の Archiver の after から)。-> 消したら True"""
        if not self.enabled() or not schemas.ids_ok(rc_id, rec):   # 録画元・録画の id の形(文字列でなければ False)
            return False
        rc = self.live.find(rc_id)
        if rc is None:
            return False
        with self.lock:
            r = next((x for x in LX.rec_list(self.live.call, rc) or [] if x.get("id") == rec), None)
            return bool(r) and self._consider(rc, r, self.clock())

    # --- 録画1本 ---
    def _consider(self, rc, r, now):
        """録画1本を消すか決めて、消す。-> 消したら True"""
        rec = r["id"]
        if r.get("active") or r.get("state") in REC_ACTIVE:   # 録画中・配信待ち・つなぎ直し中
            self._kept.pop(rec, None)
            return False
        try:
            why = self.hold(rc["id"], r)
        except Exception:   # 確かめられなければ消さない
            why = "配信後の自動の切り抜きの状態を確かめられない"
        if why:
            self._say(rec, "録画はまだ消しません(%s)" % why)
            return self._keep(r, why)
        v = self.retire.verdict(rc["id"], rec, stale=self._stale(r, now), archived=lambda: self.archived(rc["id"], r))   # 消してよいか(② の判断)
        if v.jobs:
            if v.why:
                return self._keep(r, v.why)
            if v.archived:
                return self._delete_recorded(rc, rec, "書き出し済みで、アーカイブ化を確かめた")
            # 終わって 3 日たっても書き出せない・アーカイブ化を確かめられない: 採用のまま書き出していないマークが無ければ消す
            return self._delete_recorded(rc, rec, "終わって %d 日たった" % int(STALE_SEC // 86400))
        return self._consider_no_jobs(rc, r, rec, now)

    def _stale(self, r, now):
        ended = LX.iso_epoch(r.get("endedAt")) or LX.iso_epoch(r.get("lastPdt"))
        return isinstance(ended, (int, float)) and now - ended >= STALE_SEC

    def _delete_recorded(self, rc, rec, why):
        """録画を消し(ごみ箱へ)、② の記録に消したことを記す(ジョブの recordingDeleted・検出の記録。マークの正本は残す)-> 消したら True"""
        if not self._delete(rc, rec, why):
            return False
        self._kept.pop(rec, None)
        res = self.retire.recording_deleted(rc["id"], rec)
        if res == "dropped":
            self.log("リアルタイム切り抜き: 録画のマークの正本を消しました %s" % rec)
        elif res == "unsettled":
            self._say(rec, "マークの正本は案件にまだ写っていないので残します")
        elif res.startswith("error: "):
            self._say(rec, "マークの正本を消せませんでした(%s)" % res[len("error: "):])
        return True

    def _consider_no_jobs(self, rc, r, rec, now):
        """マークが1つも無い録画(書き出しのジョブが無い)を消すか決めて、消す -> 消したら True"""
        ended = LX.iso_epoch(r.get("endedAt"))
        if ended is None or now - ended < self.no_mark_sec:
            return False
        if self.retire.has_marks(rc["id"], rec) is not False:   # マークの正本(P2 の形)に残っている・読めない
            return False
        marks, registered = self._studio_marks(rec)
        if marks is None:
            return self._keep(r, "スタジオに確かめられない")
        if marks:
            return self._keep(r, "スタジオにマークがあるが書き出していない")
        if registered:
            code, d = self.studio("POST", "/api/video/delete", {"id": rec, "ifNoMarks": True})
            if code != 200 and not (code == 404 and isinstance(d, dict) and d.get("error") == "not_found"):
                self._say(rec, "スタジオの行を消せなかったので、録画も消しません(%s)" % ((d or {}).get("message") if isinstance(d, dict) else code))
                return False
            self.log("リアルタイム切り抜き: マークの無い録画のスタジオの行を消しました %s" % rec)
        return self._delete_recorded(rc, rec, "マークが無いまま %d 時間たった" % int(self.no_mark_sec // 3600))

    def _keep(self, r, why):
        """終わっているのに消せない録画を覚える(D-14 の知らせ)。-> False(消していない)"""
        ended = LX.iso_epoch(r.get("endedAt")) or LX.iso_epoch(r.get("lastPdt"))
        self._kept[r["id"]] = {"why": why, "endedAt": ended, "title": str(r.get("title") or "")[:80]}
        return False

    def kept_failures(self, now=None):
        """D-14: 終わって STALE_SEC より長く消せないままの録画 -> 「調子」の失敗の一覧の形(kind keep。文は live_failures.keep_failure)"""
        now = self.clock() if now is None else now
        out = []
        for rec, k in sorted(self._kept.items()):
            ended = k.get("endedAt")
            if isinstance(ended, (int, float)) and live_retire.stale_ok(k.get("why")) and WARN_SEC <= now - ended:   # 消す予告(消すのは STALE_SEC。消せなければ次の見回り)
                out.append(live_failures.delete_notice(rec, max(0, int((ended + STALE_SEC - now) // 3600)), title=k.get("title") or "", at=LX.epoch_iso(ended)))
                continue
            if not isinstance(ended, (int, float)) or now - ended < STALE_SEC:
                continue
            out.append(live_failures.keep_failure(rec, int((now - ended) // 86400), k.get("why") or "", title=k.get("title") or "",
                                                 at=LX.epoch_iso(ended)))
        return out

    def _studio_marks(self, rec):
        """スタジオのその録画のマーク -> (マークの list か None(つながらない・読めない), スタジオに登録があるか)。登録が無ければ ([], False)"""
        try:
            code, d = self.studio("GET", "/api/video?id=" + urllib.parse.quote(rec), None)
        except Exception:
            return None, False
        if code == 404 and isinstance(d, dict) and d.get("error") == "not_found":
            return [], False
        v = d.get("video") if code == 200 and isinstance(d, dict) else None
        if not isinstance(v, dict) or v.get("id") != rec or not isinstance(v.get("marks"), list):
            return None, False
        return v["marks"], True

    def _delete(self, rc, rec, why):
        code, d = self.live.call(rc, "POST", "/live/%s/delete" % rec, {}, timeout=DELETE_TIMEOUT)
        if code == 200 and isinstance(d, dict) and d.get("ok"):
            self._said.pop(rec, None)
            self.log("リアルタイム切り抜き: 録画をごみ箱へ移しました %s(%s。録画元「%s」。%d 日で消えます)" % (rec, why, rc.get("name") or rc.get("id"), trashbin.KEEP_DAYS))
            return True
        if code is None:
            return False
        msg = (d or {}).get("message") if isinstance(d, dict) else ""
        self._say(rec, "録画を消せませんでした(HTTP %s: %s)" % (code, msg or "理由は分かりません"))
        return False

    def _say(self, rec, msg):
        if self._said.get(rec) != msg:
            self._said[rec] = msg
            self.log("リアルタイム切り抜き: %s %s" % (rec, msg))
