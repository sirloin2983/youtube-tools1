# -*- coding: utf-8 -*-
"""録画を自動で消す(線 D の P4。plan/line-d-live-clipping.md の 0-9 の最後。2026-10-05 ユーザー決定)の入口の側。
設定 live.autoDelete(既定オン。src/home/prefs.py)。オフなら何も消さない。リアルタイム切り抜きがオフ(live.enabled)のときも何もしない。

消すのは戻せないので、条件は厳しめにする(迷ったら消さない・分からなければ消さない):
  1. 本番版への入れ替えが全部済んだ録画(すぐ。src/home/live_archive.py の Archiver が1本終えるたびに check を呼ぶ・見回りでも)
     - 録画元の一覧(GET /live/list)で、その録画が終わっている(active でない)
     - その録画の書き出しのジョブ(src/home/live_export.py)が1つ以上あり、マークごとの最新のジョブが全部 done で archive.state も done
       (= 本番版に作り直す対象(P4 の決め方)が全部入れ替え済み。欠けで書き出せなかったマークも、本番版で作り直して done になっている)
     - 書き出しの途中・本番版への作り直しの途中(待ちを含む)・失敗・取り消しのマークが1つも無い
     - スタジオのその録画に「採用」のまま書き出していないマークが無い(GET /studio/api/video。スタジオが答えなければ消さない)
     → 録画元の POST /live/<録画>/delete → その録画のジョブに recordingDeleted(時刻)を残す(スタジオの画面が「録画は消しました」と出す)
  2. マークが1つも無い録画(試しに始めて止めた・見ただけ)
     - 録画が終わって no_mark_sec(24 時間)たった・入口の書き出しのジョブもマークの正本(live/marks)も無い
     - スタジオにマークが1つも無い(GET /studio/api/video?id=<録画>。スタジオに登録が無い録画も「マークなし」。つながらない・答えが読めなければ消さない)
     → スタジオの一覧の行を先に消す(POST /studio/api/video/delete {ifNoMarks: true} = 調べてから消すまでの間にマークが付いたら 409 で消さない)
     → 録画を消す(使用中で消せなければ、次の見回りでまた消す。スタジオの行はもう無いので 2 の条件のまま)
  3. 退避した速報版(<配信のフォルダ>\\作業用\\速報版\\…。ジョブの archive.keep): 入れ替え(archive.at)から keep_sec(7 日)たったら消す。
     消すのはジョブが自分で退避したパスだけ(書き出し先の中・作業用\\速報版\\ の直下・.mp4・リンクでない普通のファイル)→ archive.keepDeleted
録画中・配信待ち・つなぎ直し中の録画は消さない(録画元も 409 で断る)。録画元につながらない・一覧を読めないときは何もしない。
配信後の全自動(線 D の M7。設定 live.autoAfterStream)がオンで、その録画の自動の切り抜きがまだ済んでいない間も消さない(hold。src/home/live_archive.py の after_stream_hold)。
消したことは入口の記録(log)に1行ずつ残す。録画を消す API(録画元の …/delete)は入口のこの処理だけが呼ぶ(画面からの中継 /live/r/… は通さない)。
"""
import os
import threading
import time
import urllib.parse

from ytt_core import schemas
import live_archive as LA
import live_export as LX

NO_MARK_SEC = 24 * 3600.0      # マークの無い録画を消すまで(録画が終わってから)
KEEP_SEC = 7 * 86400.0         # 退避した速報版を消すまで(入れ替えてから)
INTERVAL = 600.0               # 見回り(入口の録画の見回り src/home/live.py の tick から)で調べる間隔
DELETE_TIMEOUT = 60.0          # 録画元が消し終えるまで(大きな録画は数秒かかる)
REC_ACTIVE = ("waiting", "recording", "reconnecting")   # src/recorder/rec_core.py の ACTIVE と同じ


class Cleaner:
    def __init__(self, live, enabled=None, studio=None, log=None, no_mark_sec=NO_MARK_SEC, keep_sec=KEEP_SEC, interval=INTERVAL, clock=time.time, hold=None):
        """live: src/home/live.py の Live(録画元の一覧と要求・書き出しのジョブ exporter)。
        enabled(): 消してよいか(リアルタイム切り抜きがオンで、設定 live.autoDelete がオン)。
        studio(method, path, body) -> (HTTP の番号 か None(つながらない), JSON): 取り込んだスタジオの API(Live.studio_call)。
        hold(録画元の id, 録画元の一覧の 1 行) -> 消すのを待つ理由(空 = 待たない。M7 の配信後の全自動がまだ)。
        時間(no_mark_sec・keep_sec・interval)はテストで縮める"""
        self.live = live
        self.enabled = enabled or (lambda: False)
        self.hold = hold or (lambda rc_id, r: "")
        self.studio = studio or (lambda method, path, body=None: (None, {}))
        self.log = log or (lambda m: None)
        self.no_mark_sec, self.keep_sec, self.interval, self.clock = no_mark_sec, keep_sec, interval, clock
        self.lock = threading.Lock()
        self._last = 0.0
        self._said = {}   # 録画 -> 前に記録した「消せなかった」理由(見回りのたびに同じ行を書かない)

    # --- 入口から ---
    def tick(self, force=False):
        """見回り(interval ごと。force なら今すぐ)。-> {"deleted": [録画の id], "keeps": 消した速報版の数}"""
        out = {"deleted": [], "keeps": 0}
        if not self.enabled():
            return out
        now = self.clock()
        if not force and now - self._last < self.interval:
            return out
        self._last = now
        with self.lock:
            out["keeps"] = self._clean_keeps(now)
            for rc in self.live.recorders():
                for r in LX.rec_list(self.live.call, rc) or []:   # つながらない・読めない録画元は何もしない
                    if self._consider(rc, r, now):
                        out["deleted"].append(r["id"])
        return out

    def check(self, rc_id, rec):
        """1本だけ確かめる(本番版への作り直しが1本終わったとき。src/home/live_archive.py の Archiver の after から)。-> 消したら True"""
        if not self.enabled() or not LX.ID_RE.match(rc_id or "") or not LX.REC_RE.match(rec or ""):
            return False
        rc = self.live.find(rc_id)
        if rc is None:
            return False
        with self.lock:
            r = next((x for x in LX.rec_list(self.live.call, rc) or [] if x.get("id") == rec), None)
            return bool(r) and self._consider(rc, r, self.clock())

    # --- 録画1本 ---
    def _jobs(self, rc_id, rec):
        ex = self.live.exporter
        with ex.lock:
            return [j for j in ex.jobs if j.get("recorder") == rc_id and j.get("recording") == rec]

    def _consider(self, rc, r, now):
        """録画1本を消すか決めて、消す。-> 消したら True"""
        rec = r["id"]
        if r.get("active") or r.get("state") in REC_ACTIVE:   # 録画中・配信待ち・つなぎ直し中
            return False
        try:
            why = self.hold(rc["id"], r)
        except Exception:   # 確かめられなければ消さない
            why = "配信後の自動の切り抜きの状態を確かめられない"
        if why:
            self._say(rec, "録画はまだ消しません(%s)" % why)
            return False
        js = self._jobs(rc["id"], rec)
        if js:
            why = self._replaced_why(js, rec)
            if why:
                return False
            if self._delete(rc, rec, "本番版に入れ替え済み"):
                stamp = LX.now_iso()
                ex = self.live.exporter
                with ex.lock:
                    for j in js:
                        j["recordingDeleted"] = stamp
                ex._save()
                return True
            return False
        # マークが1つも無い録画
        ended = LX.iso_epoch(r.get("endedAt"))
        if ended is None or now - ended < self.no_mark_sec:
            return False
        try:
            if (self.live.exporter.marks.load(rc["id"], rec).get("marks") or []):   # マークの正本(P2 の形)に残っている
                return False
        except LX.LiveError:
            return False
        marks, registered = self._studio_marks(rec)
        if marks is None or marks:
            return False
        if registered:
            code, d = self.studio("POST", "/api/video/delete", {"id": rec, "ifNoMarks": True})
            if code != 200 and not (code == 404 and isinstance(d, dict) and d.get("error") == "not_found"):
                self._say(rec, "スタジオの行を消せなかったので、録画も消しません(%s)" % ((d or {}).get("message") if isinstance(d, dict) else code))
                return False
            self.log("リアルタイム切り抜き: マークの無い録画のスタジオの行を消しました %s" % rec)
        return self._delete(rc, rec, "マークが無いまま %d 時間たった" % int(self.no_mark_sec // 3600))

    def _replaced_why(self, js, rec):
        """入れ替えが全部済んだ録画か。済んでいれば ""、まだなら理由(消さない)"""
        if any(j.get("recordingDeleted") for j in js):   # 前に消した(一覧にまだあるのは、録画元が古い一覧を返したとき)
            return "前に消しました"
        for j in js:
            if j.get("state") in LX.ACTIVE:
                return "書き出しの途中"
            if (j.get("archive") or {}).get("state") in LX.ARCHIVE_ACTIVE:
                return "本番版への作り直しの途中"
        last = LX.latest_per_mark(js)
        if not last or not all(j.get("state") == "done" and (j.get("archive") or {}).get("state") == "done" for j in last):
            return "本番版になっていないマークがある"
        marks, _registered = self._studio_marks(rec)
        if marks is None:
            return "スタジオに確かめられない"
        done = {(j.get("studio") or {}).get("mark"): j.get("studio") or {} for j in last}
        near = lambda a, b: isinstance(a, (int, float)) and isinstance(b, (int, float)) and abs(a - b) < 0.05   # noqa: E731
        for m in marks:   # 採用のまま書き出していない(新しいマーク・区間を直して採用に戻ったマーク)= これから録画から書き出すかもしれない
            if isinstance(m, dict) and m.get("status") == "adopted":
                s = done.get(m.get("id"))
                if s is None or not (near(m.get("start"), s.get("start")) and near(m.get("end"), s.get("end"))):
                    return "採用のまま書き出していないマークがある"
        return ""

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
            self.log("リアルタイム切り抜き: 録画を消しました %s(%s。録画元「%s」)" % (rec, why, rc.get("name") or rc.get("id")))
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

    # --- 退避した速報版 ---
    def _clean_keeps(self, now):
        """入れ替えから keep_sec たった、退避した速報版を消す。-> 消した数"""
        ex = self.live.exporter
        try:
            root = ex.out_dir()
        except Exception:
            return 0
        with ex.lock:
            cand = [j for j in ex.jobs if isinstance(j.get("archive"), dict) and j["archive"].get("state") == "done"
                    and isinstance(j["archive"].get("keep"), str) and j["archive"]["keep"] and not j["archive"].get("keepDeleted")]
        n = 0
        for j in cand:
            a = j["archive"]
            at = LX.iso_epoch(a.get("at"))
            if at is None or now - at < self.keep_sec:
                continue
            p = a["keep"]
            if not self._keep_ok(p, root):
                self._say(j["id"], "退避した速報版の場所が思っていた所ではないので消しません: %s" % p)
                continue
            try:
                os.unlink(p)
            except FileNotFoundError:
                pass   # 手で消した: 消したことにする
            except OSError as e:
                self._say(j["id"], "退避した速報版を消せませんでした(%s): %s" % (e.strerror or e.__class__.__name__, p))
                continue
            try:
                os.rmdir(os.path.dirname(p))   # 空になった 速報版 のフォルダ(中身があれば消えない)
            except OSError:
                pass
            with ex.lock:
                j["archive"] = dict(a, keepDeleted=LX.now_iso())
            n += 1
            self.log("リアルタイム切り抜き: 退避した速報版を消しました(入れ替えから %d 日)%s" % (int(self.keep_sec // 86400), p))
        if n:
            ex._save()
        return n

    @staticmethod
    def _keep_ok(p, root):
        """消してよい退避先か: 絶対パス・.mp4・書き出し先の中・…\\作業用\\速報版\\<名前> の形・リンクでない普通のファイル(無ければ消したことにする)"""
        if not isinstance(p, str) or not os.path.isabs(p) or not p.lower().endswith(".mp4") or not root:
            return False
        d = os.path.dirname(p)
        if os.path.basename(d) != LA.SPEED_DIR or os.path.basename(os.path.dirname(d)) != schemas.WORK_DIR:
            return False
        if not LA.inside(p, root):
            return False
        if os.path.lexists(p) and (os.path.islink(p) or not os.path.isfile(p)):
            return False
        return True
