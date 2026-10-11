# -*- coding: utf-8 -*-
"""録画を自動で消す(線 D の P4。plan/line-d-live-clipping.md の 0-9 の最後。2026-10-05 ユーザー決定)の入口の側。
設定 live.autoDelete(既定オン。src/home/prefs.py)。オフなら何も消さない。リアルタイム切り抜きがオフ(live.enabled)のときも何もしない。

消すのは戻せないので、条件は厳しめにする(迷ったら消さない・分からなければ消さない):
  1. 本番版への入れ替えが全部済んだ録画(すぐ。src/flow/live_archive.py の Archiver が1本終えるたびに check を呼ぶ・見回りでも)
     - 録画元の一覧(GET /live/list)で、その録画が終わっている(active でない)
     - その録画の書き出しのジョブ(src/flow/live_export.py)が1つ以上あり、マークごとの最新のジョブが全部 done で archive.state も done
       (= 本番版に作り直す対象(P4 の決め方)が全部入れ替え済み。欠けで書き出せなかったマークも、本番版で作り直して done になっている)
     - 書き出しの途中・本番版への作り直しの途中(待ちを含む)・失敗・取り消しのマークが1つも無い
     - スタジオのその録画に「採用」のまま書き出していないマークが無い(GET /studio/api/video。スタジオが答えなければ消さない)
     → 録画元の POST /live/<録画>/delete → その録画のジョブに recordingDeleted(時刻)を残す(スタジオの画面が「録画は消しました」と出す)
     → マークの正本(live/marks/<録画元>__<録画>.json)も消す。ただし スタジオなしの採用の印が案件の 採用.json に写ったあとだけ(RS8 B3-5。(r8j))
  2. マークが1つも無い録画(試しに始めて止めた・見ただけ)
     - 録画が終わって no_mark_sec(24 時間)たった・入口の書き出しのジョブもマークの正本(live/marks)も無い
     - スタジオにマークが1つも無い(GET /studio/api/video?id=<録画>。スタジオに登録が無い録画も「マークなし」。つながらない・答えが読めなければ消さない)
     → スタジオの一覧の行を先に消す(POST /studio/api/video/delete {ifNoMarks: true} = 調べてから消すまでの間にマークが付いたら 409 で消さない)
     → 録画を消す(使用中で消せなければ、次の見回りでまた消す。スタジオの行はもう無いので 2 の条件のまま)
  3. 退避した速報版(<配信のフォルダ>/作業用/速報版/…。ジョブの archive.keep): 入れ替え(archive.at)から keep_sec(3 日)たったら消す。
     消すのはジョブが自分で退避したパスだけ(書き出し先の中・作業用/速報版/ の直下・.mp4・リンクでない普通のファイル)→ archive.keepDeleted
  4. 本番版に置き換わらない録画(10-09 ユーザー決定「終わって 3 日で消す」= decisions 3-15 (fc) の変更): 消せない理由が「本番版になっていないマークがある」だけの録画は、
     終わって STALE_SEC(3 日)たったら消す。スタジオに「採用のまま書き出していないマーク」がある・スタジオに確かめられないときは消さない。
     消す 1 日前(WARN_SEC)から「調子」に予告(live_failures.delete_notice)。ほかの理由(書き出しの途中・作り直しの途中など)は今までどおり消さずに知らせる(keep_failure)
録画中・配信待ち・つなぎ直し中の録画は消さない(録画元も 409 で断る)。録画元につながらない・一覧を読めないときは何もしない。
配信後の全自動(線 D の M7。設定 live.autoAfterStream)がオンで、その録画の自動の切り抜きがまだ済んでいない間も消さない(hold。src/flow/live_archive.py の after_stream_hold)。
消したことは入口の記録(log)に1行ずつ残す。録画を消す API(録画元の …/delete)は入口のこの処理だけが呼ぶ(画面からの中継 /live/r/… は通さない)。
"""
import os
import threading
import time
import urllib.parse

from ytt import schemas
from flow import live_failures   # 残っている録画の知らせの文。D-14
from flow import live_export as LX
from flow import live_archive as LA

NO_MARK_SEC = 24 * 3600.0      # マークの無い録画を消すまで(録画が終わってから)
KEEP_SEC = 3 * 86400.0         # 退避した速報版を消すまで(入れ替えてから。ただの控えは早めに消す = docs/spec/data-location.md の保存の方針)
INTERVAL = 600.0               # 見回り(入口の録画の見回り src/home/live.py の tick から)で調べる間隔
STALE_SEC = 3 * 86400.0        # D-14: 終わってからこれだけたっても消せない録画を「調子」に知らせる。理由が NOT_REPLACED だけなら、このとき消す(10-09 ユーザー決定)
WARN_SEC = 2 * 86400.0         # NOT_REPLACED の録画を消す 1 日前から「調子」に予告する
NOT_REPLACED = "本番版になっていないマークがある"   # 消せない理由のうち、3 日で消す理由(_replaced_why が返す文)
DELETE_TIMEOUT = 60.0          # 録画元が消し終えるまで(大きな録画は数秒かかる)
REC_ACTIVE = ("waiting", "recording", "reconnecting")   # src/pipeline/ingest/rec_core.py の ACTIVE と同じ


def _near(a, b):
    """スタジオのマークと書き出したときの区間が同じか(秒の数で、差が 0.05 秒未満)"""
    return isinstance(a, (int, float)) and isinstance(b, (int, float)) and abs(a - b) < 0.05


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
        self._kept = {}   # 録画 -> {"why", "endedAt", "title"}: 終わっているのに消せない録画と理由(D-14 の知らせ。見回りで更新)

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
        """1本だけ確かめる(本番版への作り直しが1本終わったとき。src/flow/live_archive.py の Archiver の after から)。-> 消したら True"""
        if not self.enabled() or not schemas.ids_ok(rc_id, rec):   # 録画元・録画の id の形(文字列でなければ False)
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
            self._kept.pop(rec, None)
            return False
        try:
            why = self.hold(rc["id"], r)
        except Exception:   # 確かめられなければ消さない
            why = "配信後の自動の切り抜きの状態を確かめられない"
        if why:
            self._say(rec, "録画はまだ消しません(%s)" % why)
            return self._keep(r, why)
        js = self._jobs(rc["id"], rec)
        if js:
            why = self._replaced_why(js, rec)
            if why == NOT_REPLACED and self._stale(r, now):   # 終わって 3 日たっても本番版にならない: 採用のまま書き出していないマークが無ければ消す
                why = self._studio_why(LX.latest_per_mark(js), rec) or ""
                if not why:
                    return self._delete_with_jobs(rc, rec, js, "終わって %d 日たっても本番版にならない" % int(STALE_SEC // 86400))
            if why:
                return self._keep(r, why)
            if not self._delete_with_jobs(rc, rec, js, "本番版に入れ替え済み"):
                return False
            self._drop_marks(rc["id"], rec)
            return True
        return self._consider_no_jobs(rc, r, rec, now)

    def _drop_marks(self, rc_id, rec):
        """本番版に入れ替え済みで録画を消したあと、その録画のマークの正本(live/marks)も消す。ただし案件に写したあとだけ(RS8 B3-5。決定 3-37 の (r8j)):
        スタジオなしの採用の印(LocalMarks)が残っていれば、全部が案件の 採用.json に写っているときだけ(写っていなければ残して記録に 1 行)。
        スタジオの採用(StudioMarks)の正本は書き出しのジョブの入力の写しなので消してよい。終わって 3 日の録画(本番版にならない)の正本は残す
        (あとでアーカイブから作り直すときに URL・題を読む)"""
        ms = self.live.exporter.marks
        try:
            with ms.lock:
                if not ms.settled(rc_id, rec):
                    self._say(rec, "マークの正本は案件にまだ写っていないので残します")
                    return False
                if ms.drop(rc_id, rec):
                    self.log("リアルタイム切り抜き: 録画のマークの正本を消しました %s" % rec)
                return True
        except (OSError, LX.LiveError) as e:
            self._say(rec, "マークの正本を消せませんでした(%s)" % e)
            return False

    def _stale(self, r, now):
        ended = LX.iso_epoch(r.get("endedAt")) or LX.iso_epoch(r.get("lastPdt"))
        return isinstance(ended, (int, float)) and now - ended >= STALE_SEC

    def _delete_with_jobs(self, rc, rec, js, why):
        """書き出しのジョブのある録画を消し、ジョブに recordingDeleted を残す -> 消したら True"""
        if not self._delete(rc, rec, why):
            return False
        self._kept.pop(rec, None)
        stamp = LX.now_iso()
        ex = self.live.exporter
        with ex.lock:
            for j in js:
                j["recordingDeleted"] = stamp
        ex._save()
        return True

    def _consider_no_jobs(self, rc, r, rec, now):
        """マークが1つも無い録画(書き出しのジョブが無い)を消すか決めて、消す -> 消したら True"""
        ended = LX.iso_epoch(r.get("endedAt"))
        if ended is None or now - ended < self.no_mark_sec:
            return False
        try:
            if (self.live.exporter.marks.load(rc["id"], rec).get("marks") or []):   # マークの正本(P2 の形)に残っている
                return False
        except LX.LiveError:
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
        if self._delete(rc, rec, "マークが無いまま %d 時間たった" % int(self.no_mark_sec // 3600)):
            self._kept.pop(rec, None)
            return True
        return False

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
            if isinstance(ended, (int, float)) and k.get("why") == NOT_REPLACED and WARN_SEC <= now - ended:   # 消す予告(消すのは STALE_SEC。消せなければ次の見回り)
                out.append(live_failures.delete_notice(rec, max(0, int((ended + STALE_SEC - now) // 3600)), title=k.get("title") or "", at=LX.epoch_iso(ended)))
                continue
            if not isinstance(ended, (int, float)) or now - ended < STALE_SEC:
                continue
            out.append(live_failures.keep_failure(rec, int((now - ended) // 86400), k.get("why") or "", title=k.get("title") or "",
                                                 at=LX.epoch_iso(ended)))
        return out

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
            return NOT_REPLACED
        return self._studio_why(last, rec)

    def _adopted_marks(self, rc_id, rec):
        """録画の採用のマーク(秒)。マークの置き場(親の marks.adopted = スタジオか、スタジオなしは案件の 採用.json・マークの正本。RS8 B3-5 の G3)から。
        親が置き場を持たなければスタジオに聞く。読めなければ None"""
        book = getattr(self.live, "marks", None)
        if book is None or not hasattr(book, "adopted"):
            return self._studio_marks(rec)[0]
        try:
            return book.adopted(rc_id, rec)
        except Exception:   # noqa: BLE001  (確かめられなければ消さない)
            return None

    def _studio_why(self, last, rec):
        """採用の側で消せない理由(採用のまま書き出していないマーク・確かめられない)。無ければ """""
        marks = self._adopted_marks((last[0] if last else {}).get("recorder"), rec)
        if marks is None:
            return "スタジオに確かめられない"
        done = {(j.get("studio") or {}).get("mark"): j.get("studio") or {} for j in last}
        for m in marks:   # 採用のまま書き出していない(新しいマーク・区間を直して採用に戻ったマーク)= これから録画から書き出すかもしれない
            if isinstance(m, dict) and m.get("status") == "adopted":
                s = done.get(m.get("id"))
                if s is None or not (_near(m.get("start"), s.get("start")) and _near(m.get("end"), s.get("end"))):
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
            if getattr(self.live, "detector", None) is not None:   # 配信中の検出の記録(live/excite/<録画元>/<録画>。線 D の L2)も消す
                self.live.detector.forget(rc.get("id"), rec)
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
