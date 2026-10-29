# -*- coding: utf-8 -*-
"""録画の片付けの ② の口(OPT2 の 7x-1。plan/opt-manage.md の 7e・7f): 「この録画を消してよいか(理由)」の読み口と、
「録画を消したことを記す」の書き口。書き出しのジョブ(live_export の Exporter)・
マークの正本(MarkStore)・配信中の検出の記録(live_detect の Detector)の持ち主の側に置く。

使うのは ④ の録画の片付け(src/manage/keep/live_cleanup.py の Cleaner)。④ は見回り(tick・check)・期限(3 日・24 時間・予告と知らせ)・
録画元へ delete を送る・記録の 1 行だけを持ち、② の記録を直に書かない。
親(host)は flow/livesession.py の LiveSession(exporter・marks・detector)。marks と detector は呼ぶときに読む(差し替えが効く)。

消してよい条件(決定 3-73): マークが全部書き出し済み(録画に無い区間はアーカイブから)で、アーカイブ化を確かめたこと。アーカイブ化の確かめは src/flow/live_archive.py の Archiver.archived(④ が verdict に関数で渡す)。
終わって 3 日たっても書き出していないマークは、アーカイブ化を確かめれば消してよい(アーカイブから書き出せる)。アーカイブ化を確かめられない録画は消さない(10-24 ユーザー決定。
前の「確かめられないまま 3 日で消す」はやめた)。非公開・見られない配信と分かった録画と、終わって 24 時間たってもアーカイブにならない録画は、消さずに 1 本につないで名前に「非公開」
(fate・overdue・private_name。録画の部品の keep。10-24 夜のユーザーの答え「未公開と分かった段階で行えばいい。24 時間でアーカイブ化されない場合は未公開扱いしていい」)。
消すのは ごみ箱へ(録画の部品の delete が ごみ箱/<日付>/録画/ へ改名する。3 日で消える)。マークの正本は消さない(あとでアーカイブから書き出すときに URL・題を読む)。
10-29 から(スイッチ flow/retention.LIVE_FAST_RETIRE): アーカイブ化を確かめた録画は、マークの書き出しが済んでいなくてもすぐ消す(書き出していないマークはアーカイブから書き出す)。
待つのは書き出しの途中(録画を読んでいる)・アーカイブからの書き出しの途中や待ちだけ。ごみ箱に入れた録画は 24 時間で消える(録画の部品。retention.LIVE_TRASH_SEC)。
"""
import collections
import re
import time

from . import live_export as LX
from . import retention

NOT_EXPORTED = "書き出していないマークがある"   # 消せない理由のうち、終わって 3 日たったらアーカイブ化を確かめて消す理由(失敗・取り消し・アーカイブから書き出せない)
NOT_ARCHIVED = "アーカイブ化をまだ確かめられていない"   # live_archive.NOT_ARCHIVED と同じ頭(後ろに理由が付く)。この理由の録画は消さない
STUDIO_UNKNOWN = "スタジオに確かめられない"
PRIVATE_MARK = "非公開"   # 非公開・見られない配信の録画を残す名前の終わり(日付_配信者_題_非公開)
ARCHIVE_WAIT_SEC = 24 * 3600.0   # 終わってこれだけたってもアーカイブにならない録画は非公開と同じ扱い(1 本につないで残す)
PROCESS_WAIT_SEC = 7 * 24 * 3600.0   # 見られるアーカイブが YouTube の処理済みの版に置き換わるのを待つ上限(10-30。過ぎたら非公開と同じ扱い)
NOT_PROCESSED = "YouTube の処理済みの版にまだ置き換わっていない"   # live_archive.NOT_PROCESSED と同じ文
_NAME_BAD = re.compile(r'[\\/:*?"<>|\x00-\x1f]+')

# 録画を消してよいかの答え: jobs = 書き出しのジョブがあるか(無ければ ④ はマークの無い録画の道へ)・why = 消せない理由(空 = 消してよい)・
# archived = アーカイブ化を確かめた(why が空なら必ず真)
Verdict = collections.namedtuple("Verdict", "jobs why archived")


def fate(archived_why, unavailable, late, process_late=False):
    """終わった録画をどうするか(両方の PC で同じ。10-24): archived_why = Archiver.archived の答え("" = アーカイブ化を確かめた)・
    unavailable = Archiver.unavailable の答え(非公開・見られないと分かった種類。分からなければ "")・late = overdue(終わって 24 時間たった)。
    process_late = overdue(r, now, PROCESS_WAIT_SEC)。アーカイブは見られて処理済みの版を待つ間(NOT_PROCESSED)は late でなくこちらで決める(10-30)。
    -> "delete"(消す = アーカイブがはっきり見られるときだけ)・"private"(消さずに 1 本につないで名前に「非公開」。分かったらすぐ)・""(まだ待つ)"""
    if archived_why == "":
        return "delete"
    if NOT_PROCESSED in (archived_why or ""):
        late = process_late
    if unavailable or late:
        return "private"
    return ""


def overdue(r, now, sec=ARCHIVE_WAIT_SEC):
    """録画が終わって sec(既定 ARCHIVE_WAIT_SEC = 24 時間)たったか(終わりの時刻が分からなければ False = 待つ)。r = 録画元の一覧の 1 行"""
    ended = LX.iso_epoch(r.get("endedAt")) or LX.iso_epoch(r.get("lastPdt"))
    return isinstance(ended, (int, float)) and now - ended >= sec


def private_name(r):
    """非公開の録画を残す名前(拡張子なし): 日付_配信者_題_非公開。r = 録画元の一覧の 1 行。分からない所は飛ばす"""
    t = LX.iso_epoch(r.get("streamStart")) or LX.iso_epoch(r.get("firstPdt")) or LX.iso_epoch(r.get("created")) or LX.iso_epoch(r.get("endedAt"))
    parts = [time.strftime("%Y-%m-%d", time.localtime(t)) if t else "", r.get("channel"), r.get("title")]
    parts = [_NAME_BAD.sub("_", p).strip(" ._") for p in parts if isinstance(p, str)]
    return "_".join([p[:60] for p in parts if p] + [PRIVATE_MARK])


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
        無ければ確かめられない = 消さない。期限を過ぎて書き出していないマークがあるだけなら、アーカイブ化を確かめて消す(アーカイブから書き出せる)"""
        js = self._jobs(rc_id, rec)
        if not js:
            return Verdict(False, "", False)
        last = LX.latest_per_mark(js)
        fast = retention.LIVE_FAST_RETIRE   # 10-29: アーカイブ化を確かめたら、書き出していないマークがあってもすぐ(書き出しの途中だけ待つ)
        why = exported_why(js)
        if why and not (why == NOT_EXPORTED and (stale or fast)):
            return Verdict(True, why, False)
        why = "" if fast else adopted_why(last, self._adopted(rc_id, rec))
        if why:
            return Verdict(True, why, False)
        try:
            why = archived() if archived is not None else NOT_ARCHIVED
        except Exception:   # noqa: BLE001  (確かめられなければ消さない)
            why = NOT_ARCHIVED
        return Verdict(True, why, not why)

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
