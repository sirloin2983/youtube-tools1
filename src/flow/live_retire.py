# -*- coding: utf-8 -*-
"""録画の片付けの ② の口(OPT2 の 7x-1。plan/opt-manage.md の 7e・7f): 「この録画を消してよいか(理由)」の読み口と、
「録画を消したことを記す」の書き口。書き出しのジョブ(live_export の Exporter)・
マークの正本(MarkStore)・配信中の検出の記録(live_detect の Detector)の持ち主の側に置く。

使うのは ④ の録画の片付け(src/manage/keep/live_cleanup.py の Cleaner)。④ は見回り(tick・check)・期限(3 日・24 時間・予告と知らせ)・
録画元へ delete を送る・記録の 1 行だけを持ち、② の記録を直に書かない。
親(host)は flow/livesession.py の LiveSession(exporter・marks・detector)。marks と detector は呼ぶときに読む(use_headless の差し替えが効く)。

消してよい条件(決定 3-73): マークが全部書き出し済み(録画に無い区間はアーカイブから)で、アーカイブ化を確かめたこと。アーカイブ化の確かめは src/flow/live_archive.py の Archiver.archived(④ が verdict に関数で渡す)。
消すのは ごみ箱へ(録画の部品の delete が ごみ箱/<日付>/録画/ へ改名する。3 日で消える)。マークの正本は消さない(あとでアーカイブから書き出すときに URL・題を読む)。
"""
import collections

from . import live_export as LX

NOT_EXPORTED = "書き出していないマークがある"   # 消せない理由のうち、④ が期限(終わって 3 日)で消す理由(失敗・取り消し・アーカイブから書き出せない)
NOT_ARCHIVED = "アーカイブ化をまだ確かめられていない"   # 同じく期限で消す理由(live_archive.NOT_ARCHIVED と同じ頭。後ろに理由が付く)
STUDIO_UNKNOWN = "スタジオに確かめられない"

# 録画を消してよいかの答え: jobs = 書き出しのジョブがあるか(無ければ ④ はマークの無い録画の道へ)・why = 消せない理由(空 = 消してよい)・
# archived = アーカイブ化を確かめて消してよい(偽で why が空 = 終わって 3 日の期限で消してよい)
Verdict = collections.namedtuple("Verdict", "jobs why archived")


def stale_ok(why):
    """終わって 3 日の期限を過ぎたら、この理由だけなら消してよいか(書き出していない・アーカイブ化を確かめられない)"""
    return isinstance(why, str) and (why == NOT_EXPORTED or why.startswith(NOT_ARCHIVED))


def near(a, b):
    """スタジオのマークと書き出したときの区間が同じか(秒の数で、差が 0.05 秒未満)"""
    return isinstance(a, (int, float)) and isinstance(b, (int, float)) and abs(a - b) < 0.05


def exported_why(js):
    """録画のマークが全部書き出し済みか(採用の側・アーカイブ化は見ない)。済んでいれば ""、まだなら理由"""
    if any(j.get("recordingDeleted") for j in js):   # 前に消した(一覧にまだあるのは、録画元が古い一覧を返したとき)
        return "前に消しました"
    for j in js:
        if (j.get("archive") or {}).get("state") in LX.ARCHIVE_ACTIVE or (j.get("state") == "wait" and j.get("from") == "archive"):
            return "アーカイブからの書き出しの途中・待ち"
        if j.get("state") in LX.ACTIVE:
            return "書き出しの途中"
    last = LX.latest_per_mark(js)
    if not last or not all(j.get("state") == "done" for j in last):
        return NOT_EXPORTED
    return ""


def adopted_why(last, marks):
    """採用の側で消せない理由(採用のまま書き出していないマーク・確かめられない)。無ければ ""。
    last: マークごとの最新のジョブ。marks: 録画の採用のマーク(秒)か None(読めない)"""
    if marks is None:
        return STUDIO_UNKNOWN
    done = {(j.get("studio") or {}).get("mark"): j.get("studio") or {} for j in last}
    for m in marks:   # 採用のまま書き出していない(新しいマーク・区間を直して採用に戻ったマーク)= これから録画から書き出すかもしれない
        if isinstance(m, dict) and m.get("status") == "adopted":
            s = done.get(m.get("id"))
            if s is None or not (near(m.get("start"), s.get("start")) and near(m.get("end"), s.get("end"))):
                return "採用のまま書き出していないマークがある"
    return ""


class Retire:
    def __init__(self, host, studio_marks=None):
        """host: 親(exporter・marks・detector を持つ)。studio_marks(録画) -> 採用のマークの list か None:
        親がマークの置き場(marks.adopted)を持たないときに聞く先(④ の Cleaner がスタジオに聞く。既定は None = 確かめられない)"""
        self.host = host
        self.studio_marks = studio_marks or (lambda rec: None)

    @property
    def _ex(self):
        return self.host.exporter

    def _jobs(self, rc_id, rec):
        ex = self._ex
        with ex.lock:
            return [j for j in ex.jobs if j.get("recorder") == rc_id and j.get("recording") == rec]

    def _adopted(self, rc_id, rec):
        """録画の採用のマーク(秒)。マークの置き場(親の marks.adopted = スタジオか、スタジオなしは案件の 採用.json・マークの正本。RS8 B3-5 の G3)から。
        親が置き場を持たなければ studio_marks に聞く。読めなければ None"""
        book = getattr(self.host, "marks", None)
        if book is None or not hasattr(book, "adopted"):
            try:
                return self.studio_marks(rec)
            except Exception:   # noqa: BLE001  (確かめられなければ消さない)
                return None
        try:
            return book.adopted(rc_id, rec)
        except Exception:   # noqa: BLE001  (確かめられなければ消さない)
            return None

    # --- 読み口 ---
    def verdict(self, rc_id, rec, stale=False, archived=None):
        """この録画を消してよいか -> Verdict。stale: 録画が終わって ④ の期限(3 日)を過ぎたか。
        archived() -> アーカイブ化を確かめたか("" = 確かめた / 理由。live_archive.Archiver.archived。ほかの条件を満たしたときだけ呼ぶ = yt-dlp を むだに呼ばない)。
        無ければ確かめられない。期限を過ぎて理由が stale_ok だけなら、採用のまま書き出していないマークが無ければ消してよい(archived は False)"""
        js = self._jobs(rc_id, rec)
        if not js:
            return Verdict(False, "", False)
        last = LX.latest_per_mark(js)
        why = exported_why(js)
        if not why:
            why = adopted_why(last, self._adopted(rc_id, rec))
            if why:
                return Verdict(True, why, False)
            try:
                why = archived() if archived is not None else NOT_ARCHIVED
            except Exception:   # noqa: BLE001  (確かめられなければ期限まで消さない)
                why = NOT_ARCHIVED
            if not why:
                return Verdict(True, "", True)
        if stale_ok(why) and stale:
            return Verdict(True, adopted_why(last, self._adopted(rc_id, rec)), False)
        return Verdict(True, why, False)

    def has_marks(self, rc_id, rec):
        """マークの正本(P2 の形)にマークが残っているか。読めなければ None(④ は消さない)"""
        try:
            return bool(self._ex.marks.load(rc_id, rec).get("marks") or [])
        except LX.LiveError:
            return None

    # --- 書き口 ---
    def recording_deleted(self, rc_id, rec, replaced=False):
        """録画を消したことを記す(④ が録画元の delete を済ませたあと): その録画のジョブに recordingDeleted(スタジオの画面が「録画は消しました」と出す)・
        配信中の検出の記録(live/excite/<録画元>/<録画>。線 D の L2)を消す・replaced なら マークの正本(live/marks)も消す。
        マークの正本は案件に写したあとだけ(RS8 B3-5。決定 3-37 の (r8j)): スタジオなしの採用の印(LocalMarks)が残っていれば、全部が案件の 採用.json に
        写っているときだけ。スタジオの採用(StudioMarks)の正本は書き出しのジョブの入力の写しなので消してよい。終わって 3 日の録画の正本は残す
        (あとでアーカイブから作り直すときに URL・題を読む)。
        -> マークの正本の後始末: "" = しない・"dropped" = 消した・"gone" = もう無い・"unsettled" = 案件にまだ写っていないので残す・"error: …" = 消せない"""
        det = getattr(self.host, "detector", None)
        if det is not None:
            det.forget(rc_id, rec)
        ex = self._ex
        stamp = LX.now_iso()
        with ex.lock:
            js = [j for j in ex.jobs if j.get("recorder") == rc_id and j.get("recording") == rec]
            for j in js:
                j["recordingDeleted"] = stamp
        if js:
            ex._save()
        if not replaced:
            return ""
        ms = ex.marks
        try:
            with ms.lock:
                if not ms.settled(rc_id, rec):
                    return "unsettled"
                return "dropped" if ms.drop(rc_id, rec) else "gone"
        except (OSError, LX.LiveError) as e:
            return "error: %s" % e
