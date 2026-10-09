# -*- coding: utf-8 -*-
"""リアルタイム切り抜き(線 D の P2: マークと書き出し。plan/line-d-live-clipping.md の 0・5・6)の入口の側の中身。
画面と API は src/home/live.py(設定 live.enabled がオンのときだけ)。ここは「マークの正本」と「書き出しのジョブ」。

マーク(MarkStore):
  録画1本(録画元 + 録画の id)ごとに、入口の作業データの live/marks/<録画元>__<録画の id>.json に置く(マークの正本)。
  押すたびに、一時ファイルに書いて fsync してから置き換える(ytt_core.fsio.atomic_write(fsync_required=True))。
  時刻は絶対時刻(UTC。hls.js の playingDate = 録画元の受信時刻 PDT)で持つ。
  計画の 5 は「追記専用の JSONL」だが、ラベルの変更・終了の後付け・削除があるので、全体を原子的に置き換える形にした(壊れるのは「前の版のまま」だけ)。
  P3(スタジオに統合。計画の 0-8)からは、スタジオのマーク(録画の頭からの秒)を書き出すときに入口が絶対時刻へ直して入れる(upsert。id は
  lm- + sha1(スタジオのマークの id) の頭 12 桁)。ジョブには studio {video, mark, start, end} を残す(スタジオの画面がどのマークの書き出しか分かる)。
  バックアップは作業データのバックアップ(src/home/backup.py。変わってから QUIET 秒で写す)に乗る。

書き出しのジョブ(Exporter。計画の 6。1本ずつ順に):
  1. 録画待ち … マークの終わりの時刻まで録画が届くのを待つ(録画元の /live/<録画>/segments の lastPdt。届く前に録画が終われば、録れた所までで切る)
  2. 取得     … 区間にかかるセグメント(4 秒ごとの .ts)だけを録画元から取る。録画元は 主 → 予備(同じ配信を録っている別の録画元。2台のとき)の順。
                 区間に欠け(繋ぎ直しの間など)があれば書き出さずに「要差し替え」(P4 のアーカイブで作り直す)
  3. 作り直し … セッションごとにつないで(TS はそのままつなげる)、正確な区間に切って ytt_core.normalize と同じ設定で 30fps に(SLOTS を通す)
  3b. 音量    … スタジオの書き出しと同じ扱い(audio()。既定はスタジオの「書き出しの設定」= 音量 75% か、ラウドネスをそろえる -14 LUFS など)。
                 ラウドネスは作り直した動画で測って(loudnorm)から、音声だけ作り直して(映像は無劣化)ゲインをかける(ytt_core.loudness)
  4. 検証     … ffprobe で 30/1・長さ(区間 ±0.5 秒)を確かめてから本当の名前へ
  5. 完了     … スタジオの書き出しと同じ置き場所(スタジオの書き出し先/<配信の名前>/)・名前の規則・作業用/<名前>.clip.json。
                 書き出したあと(ジョブの after。スタジオの LIVE の帯の「書き出したあと」)は入口の「まとめて実行」の動画ファイルの形(autorun.start_file。
                 check = 文字起こしまで(mode file)・auto = 文字起こし → パック(mode file_auto)・none = 渡さない)。streamer(配信者の名前)があれば
                 照らし合わせて渡す(字幕の色。合わなければ色なしで進めて、ジョブの warning に出す)
  ジョブは live/exports.json に残す。入口を起動し直したら、途中だったジョブは「録画待ち」からやり直す(冪等: 書きかけは消し、名前は仕上げるときに決める)。
  P4(アーカイブで本番版に作り直す。src/home/live_archive.py)はジョブに archive を足す(ここは起動し直したときに途中の段を「待ち」に戻すのと、
  作り直しの途中のマークを書き出し直させない busy・欠けのマークの名前を決める target・recBase(録画の頭の時刻)を受け持つ)。

採用の出どころ origin(線 D の M1。入口 0.39.0): manual(人がマークした)・auto(配信中の検出が自動で採用。M11)・archive(配信後のアーカイブの解析で自動で採用。M7)。
ジョブ・.clip.json の source.live.origin と mark.src(auto・archive は "auto")・live/live_feedback.jsonl(採用の記録。feedback.jsonl とは別 = 計画の 0-8)に残す。
自動の採用は「良い」に数えない(live_feedback の human が false・verdict が null。スタジオの adopt_top と同じ決まり)。
書き出しが済んだら、スタジオのマーク(ジョブの studio)を入口が自分で「書き出し済み」にする(POST /studio/api/live/exported。画面を閉じていても。M1)。
書き出したあとの自動の流れの設定(ホームの設定 live.auto の cut・engine・model。M2)はジョブを作るときに auto に覚え、まとめて実行へ渡す。
失敗の文は src/home/live_failures.py の failure_of だけが作る(M3)。snapshot はジョブに failure を足し、帯が今までどおり出す欄(error・warning)にも同じ文を入れる。

ディスクの見張り(線 D の M4。入口 0.40.0): 書き出し先(パックも切り抜きの隣 <名前>_pack に作る)と live/work(取ったセグメント・アーカイブの丸ごとの音)の
空きを DISK_POLL(1 分)ごとに調べる(disk)。DISK_WARN(20 GB)未満で注意(「調子」)、DISK_LOW(5 GB)未満で**新しい書き出しと文字起こしを「空き待ち」**にする
(録画待ちのジョブは録画元に問い合わせずに待ち、書き出しが済んだジョブはまとめて実行へ渡すのを待つ = handoffWait "disk")。空けば続ける。
止めずに待つのは、書き込みの途中で失敗して書きかけが壊れるより戻しやすいため(計画の 5 の 3)。録画の部品は録画先を 1 GB で止め・20 GB で注意する(別)。
用途つきの枠(M6): 書き出す録画がまだ録画中なら、重い処理の順番(ytt_core.jobs.SLOTS)の用途つきの枠も使う(acquire(reserved=True))。
本番版を待ってから渡す(M7): holdFor "archive" のジョブ(配信後の全自動。src/home/live_archive.py)は、書き出したあと まとめて実行へすぐ渡さず
handoffWait "archive" で待ち、アーカイブで本番版に入れ替えてから(できなければ速報版のまま)Archiver が release_hold で渡す(パックが本番版になる)。

.clip.json の source(pipeline.md の 2.1 に足す値): kind "live"。range は「録画の最初のセグメントの受信時刻」からの秒、
絶対時刻と録画の素性は source.live に入れる(P4 でアーカイブの時刻へ置き換えるため)。videoId は YouTube の動画の id(分かるとき)。
url は入れない(range がアーカイブの秒ではないので、YouTube の位置へのリンクにしない)。
"""
import hashlib
import json
import math
import os
import re
import secrets
import shutil
import threading
import time
import urllib.parse

from ytt import colors, fsio, jobs, loudness, names, normalize, recproto, schemas, tools
import live_failures  # noqa: E402  (失敗の文は 1 か所。M3)

VERSION = "0.1.0"
TOOL = {"name": "ytt-live", "version": VERSION}
MARKS_SCHEMA = "ytt-live-marks/v1"
JOBS_SCHEMA = "ytt-live-exports/v1"
# 録画元との約束(id の形・時刻の書き方・動画の id)は ytt_core/recproto.py の 1 か所(録画の部品・配信中の検出のワーカーと同じ物。2026-10-09 見直し T8)
ID_RE = recproto.RECORDER_ID_RE   # 録画元の id
REC_RE = recproto.REC_ID_RE       # 録画の id
MARK_RE = re.compile(r"^lm-[0-9a-f]{8,16}\Z")
JOB_RE = re.compile(r"^lx-[0-9a-f]{8,16}\Z")
SEG_URI_RE = recproto.SEG_URI_RE
YT_ID_RE = recproto.YT_VID_RE
STUDIO_ID_RE = re.compile(r"^[\w-]{1,40}\Z", re.ASCII)              # スタジオの配信・マークの id(P3。POST /live/api/export の studio)
MAX_MARKS = 300            # 録画1本のマークの数
MAX_MARK_SEC = 3600        # 1つのマークの長さ(スタジオの MAX_MARK_SEC と同じ)
LABEL_MAX = 80
AFTERS = ("none", "check", "auto")   # 書き出したあと: 何もしない / 文字起こしまで(まとめて実行の ② 軽く確認)/ 全自動(文字起こし → パック。① 全自動)
ORIGINS = ("manual", "auto", "archive")   # 採用の出どころ(M1): 人 / 配信中の検出(M11)/ 配信後のアーカイブの解析(M7)
AUTO_KEYS = ("cut", "engine", "model")    # ジョブに覚える書き出したあとの設定(ホームの設定 live.auto。M2)
FEEDBACK = "live_feedback.jsonl"          # 採用の記録(入口の作業データの live\。feedback.jsonl とは別 = 計画の 0-8)
FEEDBACK_MAX_BYTES = 4 * 1024 * 1024      # これを超えたら .1 に回す
TITLE_MAX = 200
KEEP_JOBS = 200            # 終わったジョブを残す数
LEN_TOL = 0.2              # 書き出した長さと区間の差の上限(30fps の1コマ + 音声の端)。normalize の DURATION_TOL(0.5)より厳しく
READY_PAD = 1.0            # 終わりの時刻よりこの秒数先まで録れたら「届いた」(受信時刻の揺れの分)
POLL = 2.0                 # 録画待ちの見回りの間隔(秒)
DOWN_SEC = 60.0            # 録画元にこの秒数つながらなければ、予備を探して、無ければ失敗
FETCH_TIMEOUT = 30.0
ACTIVE = ("wait", "fetch", "encode")
STATE_LABELS = {"wait": "録画待ち", "fetch": "取得中", "encode": "作り直し中", "done": "済み", "error": "失敗", "cancelled": "取り消し"}
GB = 1024 ** 3
DISK_WARN = 20 * GB        # 空きがこれ未満で注意(M4。録画の部品の 20 GB と同じ)
DISK_LOW = 5 * GB          # 空きがこれ未満で、新しい書き出し・文字起こしを「空き待ち」にする(M4。録画の部品は 1 GB で録画を止める)
DISK_POLL = 60.0           # 空きを調べ直す間隔(秒)
HOLDS = ("archive",)       # まとめて実行へ渡すのを待つ理由(holdFor。M7: 本番版にしてから)
ARCHIVE_RUN = ("probe", "align", "fetch", "verify")   # 本番版への作り直し(src/home/live_archive.py の RUN と同じ)の動いている段
ARCHIVE_ACTIVE = ("wait",) + ARCHIVE_RUN


class LiveError(ValueError):
    """画面に出せる理由(code は HTTP の番号)"""
    def __init__(self, message, code=400):
        super().__init__(message)
        self.code = code


class Cancelled(Exception):
    pass


class Halted(Exception):
    """入口の終了(ジョブは「録画待ち」に戻して、次の起動でやり直す)"""


# ---------- 時刻・名前(ytt_core の 1 か所。テストと live_archive・live_cleanup などがここの名前で読む) ----------
iso_epoch, epoch_iso, now_iso, video_id_of = recproto.iso_epoch, recproto.epoch_iso, recproto.now_iso, recproto.video_id_of
compact_ts, safe_name, unique_base = names.compact_ts, names.safe_name, names.unique_base   # スタジオの書き出しと同じ規則(ytt_core/names.py)


def pick_folder(root, title, owner):
    """<書き出し先>/<配信の名前>/(スタジオの pick_folder と同じ ytt_core.names.pick_folder: 作業用/.studio-id に持ち主を書き、
    同じ名前の別の配信とは混ぜない)。題が空なら持ち主の名前か live"""
    got = names.pick_folder(root, title, owner, safe_name(owner, 60) or "live")
    if got is None:
        raise LiveError("保存先のフォルダを作れませんでした")
    return got[1]


def rec_list(call, rc, timeout=5.0):
    """録画元の録画の一覧(GET /live/list の recordings のうち、id の形が正しい辞書だけ)。つながらない・読めなければ None。
    call = src/home/live.py の Live.call(テストは差し替える)"""
    code, d = call(rc, "GET", "/live/list", timeout=timeout)
    if code != 200 or not isinstance(d, dict):
        return None
    return [r for r in d.get("recordings") or [] if isinstance(r, dict) and REC_RE.match(str(r.get("id") or ""))]


def latest_per_mark(js):
    """マークごとの最新のジョブ(作った時刻の新しいもの)。本番版への作り直しの対象(live_archive)と、録画を消すか(live_cleanup)で同じ決め方"""
    last = {}
    for j in js:
        p = last.get(j.get("markId"))
        if p is None or str(j.get("created") or "") >= str(p.get("created") or ""):
            last[j.get("markId")] = j
    return list(last.values())


# ---------- マーク(正本) ----------
def _text(v, n):
    return re.sub(r"[\x00-\x1f\x7f]", " ", v if isinstance(v, str) else "").strip()[:n]


def check_after(body, default="check"):
    """POST /live/api/export・adopt の after("none"|"check"|"auto")。無ければ以前の transcribe(真偽)から: false → none・true → check。
    どちらも無ければ default(ホームの設定 live.auto.after。M2)"""
    a = body.get("after") if isinstance(body, dict) else None
    if a is None:
        t = body.get("transcribe") if isinstance(body, dict) else None
        return "none" if t is False else "check" if t is True else (default if default in AFTERS else "check")
    if a not in AFTERS:
        raise LiveError("書き出したあと(after)は none・check・auto のどれかにしてください")
    return a


def check_origin(v):
    """採用の出どころ(M1)。無い = manual"""
    if v is None:
        return "manual"
    if v not in ORIGINS:
        raise LiveError("origin は manual・auto・archive のどれかにしてください")
    return v


def clean_auto(cfg):
    """ホームの設定 live.auto(src/home/prefs.py が検査済み)-> ジョブに覚える {cut, engine, model}(空の値は入れない)"""
    cfg = cfg if isinstance(cfg, dict) else {}
    return {k: cfg[k] for k in AUTO_KEYS if isinstance(cfg.get(k), str) and cfg[k]}


def check_streamer(v):
    """POST /live/api/export の streamer(配信者の名前。字幕の色)。無い・空 = ""。長すぎる・制御文字・文字列でない → LiveError"""
    if v is None:
        return ""
    if not isinstance(v, str) or any(ord(c) < 32 or ord(c) == 127 for c in v):
        raise LiveError("配信者の名前が正しくありません")
    v = v.strip()
    if len(v) > colors.NAME_MAX:
        raise LiveError("配信者の名前が長すぎます(%d 文字まで)" % colors.NAME_MAX)
    return v


def deliver_pool(job, req):
    """ライブの切り抜きを n 本の組で届けるときの溜めの指定(src/pipeline/run.py の Run.pool)。溜めは 依頼(自分の配信の自動で届ける分は録画)× 段
    (配信中の live = 自動の採用・人のマーク / 配信後の追加 archive)ごと。10-09 ユーザー決定 = decisions 3-20"""
    phase = "archive" if job.get("origin") == "archive" else "live"
    who = "auto" if req.get("autoDeliver") is True else str(req.get("rid") or "")
    rec = "%s/%s" % (job.get("recorder") or "", job.get("recording") or "")
    title = job.get("title") if isinstance(job.get("title"), str) and job.get("title") else job.get("recording") or "live"
    return {"key": "%s|%s|%s" % (phase, who, rec), "rid": str(req.get("rid") or ""), "title": (title + (" 配信後" if phase == "archive" else ""))[:100],
            "meta": {"recorder": job.get("recorder") or "", "recording": job.get("recording") or "", "phase": phase}}


def job_after(job):
    """ジョブの書き出したあと(この版より前のジョブは transcribe から)"""
    a = job.get("after")
    return a if a in AFTERS else ("check" if job.get("transcribe") else "none")


def studio_mark_id(mark):
    """スタジオのマークの id → マークの正本の id(同じスタジオのマークは何度書き出しても同じ正本の1件)"""
    return "lm-" + hashlib.sha1(mark.encode("utf-8")).hexdigest()[:12]


def check_studio(s):
    """POST /live/api/export の studio {video, mark, n, label, start, end} を検査する(start・end は録画の頭からの秒)。-> 整えた辞書"""
    if not isinstance(s, dict):
        raise LiveError("studio の形が正しくありません")
    for k in ("video", "mark"):
        if not isinstance(s.get(k), str) or not STUDIO_ID_RE.match(s[k]):
            raise LiveError("studio.%s の形が正しくありません" % k)
    sec = {}
    for k in ("start", "end"):
        v = s.get(k)
        if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v):
            raise LiveError("studio.%s は秒(数)で指定してください" % k)
        sec[k] = round(float(v), 3)
    if not 0 <= sec["start"] < sec["end"]:
        raise LiveError("区間は 0 ≤ 開始 < 終了 にしてください")
    if sec["end"] - sec["start"] > MAX_MARK_SEC:
        raise LiveError("1つのマークは %d 分までです" % (MAX_MARK_SEC // 60))
    n = s.get("n", 0)
    if isinstance(n, bool) or not isinstance(n, int) or not 0 <= n <= 99999:
        raise LiveError("studio.n の形が正しくありません")
    return {"video": s["video"], "mark": s["mark"], "n": n, "label": _text(s.get("label"), LABEL_MAX), "start": sec["start"], "end": sec["end"]}


class MarkStore:
    """録画1本ごとのマーク。値の変更はロックの中で読み → 変える → fsync して置き換える"""

    def __init__(self, folder):
        self.folder = folder
        self.lock = threading.RLock()

    def path(self, rc, rec):
        if not ID_RE.match(rc or "") or not REC_RE.match(rec or ""):
            raise LiveError("録画元か録画の指定が正しくありません")
        return os.path.join(self.folder, "%s__%s.json" % (rc, rec))

    def load(self, rc, rec):
        p = self.path(rc, rec)
        try:
            d = fsio.read_json_file(p, 4 * 1024 * 1024)
        except FileNotFoundError:
            d = None
        except (OSError, ValueError) as e:
            raise LiveError("マークのファイルを読めません(%s)" % (e.__class__.__name__ if isinstance(e, OSError) else str(e)[:80]), 500)
        if not isinstance(d, dict) or d.get("schema") != MARKS_SCHEMA:
            d = {"schema": MARKS_SCHEMA, "recorder": rc, "recording": rec, "url": "", "title": "", "marks": []}
        d["marks"] = [m for m in d.get("marks") or [] if isinstance(m, dict) and MARK_RE.match(str(m.get("id") or ""))]
        return d

    def _save(self, d):
        d["updated"] = now_iso()
        fsio.atomic_write(self.path(d["recorder"], d["recording"]),
                          json.dumps(d, ensure_ascii=False, indent=1).encode("utf-8"), fsync_required=True)

    def get(self, rc, rec, mid):
        m = next((x for x in self.load(rc, rec)["marks"] if x["id"] == mid), None)
        if m is None:
            raise LiveError("そのマークはありません", 404)
        return m

    def apply(self, rc, rec, body):
        """{op: add|update|delete, …} -> (変えたマーク(delete は None), 全部のマーク)"""
        op = body.get("op")
        with self.lock:
            d = self.load(rc, rec)
            self._touch(d, body.get("url"), body.get("title"))
            marks = d["marks"]
            if op == "add":
                self._room(marks)
                m = {"id": "lm-" + secrets.token_hex(5), "n": max([x.get("n") or 0 for x in marks] + [0]) + 1,
                     "start": None, "end": None, "label": "", "created": now_iso()}
                self._set(m, body, new=True)
                marks.append(m)
            elif op in ("update", "delete"):
                m = next((x for x in marks if x["id"] == body.get("id")), None)
                if m is None:
                    raise LiveError("そのマークはありません", 404)
                if op == "delete":
                    marks.remove(m)
                    m = None
                else:
                    self._set(m, body)
            else:
                raise LiveError("op は add・update・delete のどれかです")
            if m is not None:
                m["updated"] = now_iso()
            self._save_or_raise(d)
            return m, marks

    def upsert(self, rc, rec, mid, n, start, end, label="", url=None, title=None):
        """スタジオのマーク(P3)を正本に入れる: id(lm-…)が無ければ足す・あれば開始・終了・ラベル・番号を変える。
        start・end は絶対時刻の文字列(UTC)。-> 入れたマーク"""
        if not MARK_RE.match(mid or ""):
            raise LiveError("マークの指定が正しくありません")
        with self.lock:
            d = self.load(rc, rec)
            self._touch(d, url, title)
            m = next((x for x in d["marks"] if x["id"] == mid), None)
            if m is None:
                self._room(d["marks"])
                m = {"id": mid, "n": n, "start": None, "end": None, "label": "", "created": now_iso(), "src": "studio"}
                self._set(m, {"start": start, "end": end, "label": label}, new=True)
                d["marks"].append(m)
            else:
                self._set(m, {"start": start, "end": end, "label": label})
                m["n"] = n
            m["updated"] = now_iso()
            self._save_or_raise(d)
            return dict(m)

    @staticmethod
    def _touch(d, url, title):
        """録画の記録に配信の URL(まだ無いときだけ)と題名(空でなければ)を入れる(apply と upsert の共通)"""
        if isinstance(url, str) and not d.get("url"):
            d["url"] = _text(url, 500)
        if isinstance(title, str) and title.strip():
            d["title"] = _text(title, TITLE_MAX)

    @staticmethod
    def _room(marks):
        """マークを 1 つ足せるか(上限 MAX_MARKS。超えるなら 409 の LiveError)"""
        if len(marks) >= MAX_MARKS:
            raise LiveError("1本の録画に付けられるマークは %d 個までです" % MAX_MARKS, 409)

    def _save_or_raise(self, d):
        """保存する。書けなければ 500 の LiveError(画面に出す文)"""
        try:
            self._save(d)
        except OSError as e:
            raise LiveError("マークを保存できませんでした: %s" % tools.why(e), 500)

    @staticmethod
    def _set(m, body, new=False):
        start, end = m.get("start"), m.get("end")
        if "start" in body or new:
            if iso_epoch(body.get("start")) is None:
                raise LiveError("開始の時刻が正しくありません(再生している所の時刻が取れていないかもしれません)")
            start = epoch_iso(iso_epoch(body["start"]))
        if "end" in body:
            if body["end"] is None:
                end = None
            elif iso_epoch(body["end"]) is None:
                raise LiveError("終了の時刻が正しくありません")
            else:
                end = epoch_iso(iso_epoch(body["end"]))
        if end is not None:
            a, b = iso_epoch(start), iso_epoch(end)
            if b - a < 0.5:
                raise LiveError("終了は開始より後にしてください(0.5 秒以上)")
            if b - a > MAX_MARK_SEC:
                raise LiveError("1つのマークは %d 分までです" % (MAX_MARK_SEC // 60))
        if "label" in body:
            m["label"] = _text(body.get("label"), LABEL_MAX)
        m["start"], m["end"] = start, end


# ---------- 書き出しのジョブ ----------
class Exporter:
    def __init__(self, live, folder, out_dir, runner=None, log=None, slots=None, poll=POLL, down_sec=DOWN_SEC, ffmpeg=None, ffprobe=None, audio=None,
                 runs_log=None, disk_usage=None, disk_poll=DISK_POLL):
        """live: src/home/live.py の Live(録画元の一覧と要求)。folder: 入口の作業データの live\\。out_dir(): 書き出し先(スタジオの書き出し先)。
        runner(): まとめて実行(src/home/autorun.py の AutoRunner。文字起こしへ渡す)か None。
        audio(): 書き出しの音量 {"volume": 1〜200(%), "loudness": LUFS か None}(src/home/live.py の studio_audio)。None なら音量を変えない。
        runs_log: まとめて実行の記録 autorun-runs.jsonl(失敗の集約。M3)。
        disk_usage(path) -> (空きのバイト数, 全体のバイト数)(M4。既定 shutil.disk_usage。テストは偽の小さな空きにする)・disk_poll: 調べ直す間隔(秒)"""
        self.live, self.folder, self.out_dir, self.runner, self.audio = live, folder, out_dir, runner, audio
        self.disk_usage = disk_usage or _disk_usage
        self.disk_poll = disk_poll
        self._disk = None          # 前に調べた結果(disk)
        self._disk_at = 0.0
        self._disk_said = "ok"     # 前に記録(log)した状態(変わったときだけ書く)
        self._disk_lock = threading.Lock()
        self.runs = live_failures.Reader(runs_log)
        self.fb_lock = threading.Lock()
        self.log = log or (lambda m: None)
        self.slots = slots or jobs.SLOTS
        self.poll, self.down_sec = poll, down_sec
        self.ffmpeg, self.ffprobe = ffmpeg, ffprobe
        self.marks = MarkStore(os.path.join(folder, "marks"))
        self.work = os.path.join(folder, "work")       # 取ったセグメントの一時の置き場所(作業データのバックアップは work を写さない)
        self.jobs_path = os.path.join(folder, "exports.json")
        self.lock = threading.RLock()
        self.wake = threading.Event()
        self._halt = threading.Event()
        self._thread = None
        self.jobs = []
        self._load()

    # --- 記録 ---
    def _load(self):
        try:
            d = fsio.read_json_file(self.jobs_path, 8 * 1024 * 1024)
        except (OSError, ValueError):
            d = None
        jobs_ = d.get("jobs") if isinstance(d, dict) and d.get("schema") == JOBS_SCHEMA else []
        for j in jobs_ if isinstance(jobs_, list) else []:
            if not isinstance(j, dict) or not JOB_RE.match(str(j.get("id") or "")):
                continue
            if j.get("state") in ("fetch", "encode"):   # 入口が途中で終わった: 録画待ちからやり直す
                j.update(state="wait", progress=0, message="ホームを起動し直したので、やり直します")
            j.pop("diskWait", None)
            arc = j.get("archive")
            if isinstance(arc, dict) and arc.get("state") in ARCHIVE_RUN:   # 本番版への作り直し(P4。src/home/live_archive.py)の途中: 順番待ちに戻す
                j["archive"] = dict(arc, state="wait", label="待ち", progress=0, message="ホームを起動し直したので、続きから作り直します")
            j.pop("cancel", None)
            self.jobs.append(j)
        shutil.rmtree(self.work, ignore_errors=True)   # 前回の取りかけ

    def _save(self):
        with self.lock:
            data = json.dumps({"schema": JOBS_SCHEMA, "jobs": [{k: v for k, v in j.items() if k != "cancel"} for j in self.jobs]},
                              ensure_ascii=False, indent=1).encode("utf-8")
        try:
            fsio.atomic_write(self.jobs_path, data)
        except OSError as e:
            self.log("リアルタイム切り抜き: 書き出しの記録を書けませんでした: %s" % e)

    def _set(self, job, **kw):
        with self.lock:
            job.update(kw)
            job["updated"] = now_iso()
        self._save()

    def _trim(self):
        done = [j for j in self.jobs if j["state"] not in ACTIVE]
        for j in done[:max(0, len(done) - KEEP_JOBS)]:
            self.jobs.remove(j)

    # --- 画面から ---
    def snapshot(self, rc=None, rec=None):
        tx = self._tx_states()
        try:
            runs = self.runs.runs()
        except Exception:   # 記録を読めなくても一覧は出す
            runs = {}
        with self.lock:
            out = [dict((k, v) for k, v in j.items() if k != "cancel") for j in self.jobs
                   if (rc is None or j["recorder"] == rc) and (rec is None or j["recording"] == rec)]
        for j in out:
            j["stateLabel"] = STATE_LABELS.get(j["state"], j["state"])
            if j.get("runId") and j["runId"] in tx:
                j["tx"] = tx[j["runId"]]
            f = live_failures.failure_of(j, runs.get(j.get("runId")) if j.get("runId") else None)
            if f is not None:   # 失敗の文(M3)。帯は今までどおり error(書き出しの失敗)・warning(それ以外)を出すので、同じ文を入れる
                j["failure"] = f
                if f["kind"] == "export":
                    j["error"] = f["text"]
                else:
                    parts = [p for p in str(j.get("warning") or "").split(" / ") if p]
                    j["warning"] = " / ".join(parts + [f["text"]] if f["text"] not in parts else parts)
        return list(reversed(out))

    def failures(self, now=None):
        """失敗の一覧(新しい順。「調子」に出す。M3)。文は snapshot と同じ(live_failures.failure_of)"""
        with self.lock:
            jobs_ = [dict(j) for j in self.jobs]
        try:
            runs = self.runs.runs()
        except Exception:
            runs = {}
        return live_failures.collect(jobs_, runs, now=time.time() if now is None else now)

    def feedback(self, row):
        """採用の記録を live_feedback.jsonl に 1 行(M1。feedback.jsonl とは別)。書けなくても採用は止めない"""
        path = os.path.join(self.folder, FEEDBACK)
        line = json.dumps(dict({"v": 1, "at": now_iso()}, **row), ensure_ascii=False) + "\n"
        with self.fb_lock:
            try:
                fsio.append_line(path, line, FEEDBACK_MAX_BYTES)   # 記録のファイルに 1 行ずつ書く形は 1 か所(ytt/fsio)
            except OSError as e:
                self.log("リアルタイム切り抜き: 採用の記録を書けませんでした: %s" % tools.why(e))

    def _tx_states(self):
        """文字起こしへ渡したジョブの、まとめて実行の状態(runId -> {state, label})"""
        try:
            r = self.runner() if self.runner else None
            runs = r.snapshot().get("runs") if r is not None else []
        except Exception:
            return {}
        return {x.get("id"): {"state": x.get("state"), "label": x.get("stateLabel"), "message": x.get("error") or x.get("message") or "",
                              "steps": [{"key": s.get("key"), "label": s.get("label"), "state": s.get("state"), "stateLabel": s.get("stateLabel")}
                                        for s in x.get("steps") or [] if isinstance(s, dict)]}
                for x in runs or [] if isinstance(x, dict)}

    def busy(self, rec, mid):
        """書き出しの途中か、本番版への作り直し(P4)の順番待ち・途中(入れ替える相手のファイルを、書き出し直しで変えない)"""
        with self.lock:
            return any(j for j in self.jobs if j["markId"] == mid and j["recording"] == rec and
                       (j["state"] in ACTIVE or (j.get("archive") or {}).get("state") in ARCHIVE_ACTIVE))

    def _busy_error(self, rec, mid):
        """busy のときに断る文(本番版への作り直しの途中なら、そう言う)"""
        with self.lock:
            arch = any(j for j in self.jobs if j["markId"] == mid and j["recording"] == rec and (j.get("archive") or {}).get("state") in ARCHIVE_ACTIVE)
        return LiveError("このマークは本番版に作り直しています(終わってから書き出し直せます)" if arch else "このマークは書き出しの途中です", 409)

    def add_studio(self, rc, rec, studio, first, transcribe=True, url=None, title=None, after=None, streamer="", origin="manual", auto=None, hold=None, score=None,
                   request=None):
        """スタジオのマーク(P3)から書き出す。studio: 検査済みの {video, mark, n, label, start, end}(秒 = 録画の最初のセグメントの受信時刻から)。
        first: その受信時刻(epoch 秒。録画元の status の firstPdt = _base と同じ基準)。マークの正本の id は lm- + sha1(スタジオのマークの id) の頭 12 桁。
        after・streamer・origin・auto・hold・score: add と同じ"""
        if self.live.find(rc) is None:
            raise LiveError("その録画元はありません", 404)
        mid = studio_mark_id(studio["mark"])
        with self.lock:   # 書き出しの途中のマークは、正本を書き換える前に断る(途中のジョブの区間と正本が食い違わないように)
            if self.busy(rec, mid):
                raise self._busy_error(rec, mid)
            self.marks.upsert(rc, rec, mid, studio["n"], epoch_iso(first + studio["start"]), epoch_iso(first + studio["end"]),
                              studio["label"], url=url, title=title)
            return self.add(rc, rec, mid, transcribe,
                            studio={k: studio[k] for k in ("video", "mark", "start", "end")}, after=after, streamer=streamer, origin=origin, auto=auto,
                            hold=hold, score=score, request=request)

    def add(self, rc, rec, mid, transcribe=True, studio=None, after=None, streamer="", origin="manual", auto=None, hold=None, score=None, request=None):
        """studio: スタジオのマークから頼まれたとき {video, mark, start, end}(ジョブに残す = スタジオの画面がどのマークの書き出しか分かる)。
        after: 書き出したあと(AFTERS。None = transcribe から)。streamer: 検査済みの配信者の名前(""= 決まっていない)。どちらもジョブに残して _finish が使う。
        origin: 採用の出どころ(ORIGINS。M1)。auto: 書き出したあとの設定 {cut, engine, model}(clean_auto 済み。M2)。
        hold: "archive" = 書き出したあと、本番版に入れ替えてから まとめて実行へ渡す(HOLDS。M7 の配信後の全自動。入口の中からだけ。API からは渡せない)。
        score: 候補の点数(配信中の検出・アーカイブの解析。任意)。ジョブに残し、.clip.json の source.live.score へ(M9 の確認の一覧が出す)。
        request: 友人のライブ配信の依頼(live_requests.Store の項目。2-15)。ジョブに {rid, deliverDir, speakers, videoTracks, cut} を残し、_handoff が まとめて実行へ渡す"""
        after = after if after in AFTERS else ("check" if transcribe else "none")
        origin = origin if origin in ORIGINS else "manual"
        if self.live.find(rc) is None:
            raise LiveError("その録画元はありません", 404)
        m = self.marks.get(rc, rec, mid)
        if not m.get("end"):
            raise LiveError("終了をマークしてから書き出してください")
        with self.lock:
            if self.busy(rec, mid):
                raise self._busy_error(rec, mid)
            if sum(1 for j in self.jobs if j["state"] in ACTIVE) >= 50:
                raise LiveError("書き出しの順番待ちが多すぎます(50 本まで)", 409)
            job = {"id": "lx-" + secrets.token_hex(5), "recorder": rc, "recording": rec, "markId": mid, "n": m.get("n") or 0,
                   "label": m.get("label") or "", "start": m["start"], "end": m["end"], "transcribe": after != "none",
                   "after": after, "streamer": streamer or "", "origin": origin, "auto": clean_auto(auto),
                   "state": "wait", "message": "録画が届くのを待っています", "error": "", "needsArchive": False, "progress": 0,
                   "source": "", "path": "", "manifest": "", "runId": "", "warning": "", "attempts": 0,
                   "created": now_iso(), "updated": now_iso()}
            if studio is not None:
                job["studio"] = dict(studio)
            if hold in HOLDS:
                job["holdFor"] = hold
            if isinstance(score, (int, float)) and not isinstance(score, bool):
                job["score"] = round(float(score), 2)   # 候補の点数(自動の採用。.clip.json の source.live.score へ)
            if isinstance(request, dict) and request.get("rid"):
                job["request"] = {k: request.get(k) for k in ("rid", "deliverDir", "speakers", "videoTracks", "cut")}   # 友人の依頼(2-15)
                if isinstance(request.get("deliverBatch"), int) and not isinstance(request.get("deliverBatch"), bool):   # 届け方(2.9.0 のアプリ)
                    job["request"]["deliverBatch"] = request["deliverBatch"]
                if request.get("autoDeliver") is True:   # 自分の配信の自動の切り抜きを確認なしで届ける(live.autoDeliver)= 友人の依頼と分ける印
                    job["request"]["autoDeliver"] = True
            self.jobs.append(job)
            self._trim()
        self._save()
        self.start()
        self.wake.set()
        return dict(job, stateLabel=STATE_LABELS["wait"])

    def cancel(self, jid):
        with self.lock:
            job = next((j for j in self.jobs if j["id"] == jid), None)
            if job is None:
                raise LiveError("その書き出しはありません", 404)
            if job["state"] not in ACTIVE:
                return dict(job)
            job["cancel"] = True
            if job["state"] == "wait":
                job.update(state="cancelled", message="取り消しました")
        self._save()
        self.wake.set()
        return dict((k, v) for k, v in job.items() if k != "cancel")

    def pending(self):
        """書き出しの途中・順番待ちか、空きを待ってまとめて実行へ渡すもの(M4)がある(入口を起動し直したら見回りを動かす)"""
        with self.lock:
            return any(j["state"] in ACTIVE or (j["state"] == "done" and j.get("handoffWait") == "disk") for j in self.jobs)

    # --- ディスクの見張り(M4) ---
    def disk_paths(self):
        """見張る場所 [(名前, パス)]: 書き出し先(パックも切り抜きの隣に作る)・live/work(取ったセグメント・アーカイブの丸ごとの音)"""
        out = []
        try:
            root = self.out_dir()
        except Exception:
            root = None
        if isinstance(root, str) and root and os.path.isabs(root):
            out.append(("書き出し先・パック", root))
        out.append(("作業用(live\\work)", self.work))
        return out

    def disk(self, force=False):
        """空き容量 -> {"state": ok|warn|low, "rows": [{label, path, drive, freeBytes, totalBytes, state}], "message", "checkedAt", "lowBytes", "warnBytes"}。
        DISK_POLL 秒は前の結果を返す(force で今すぐ)。同じドライブは 1 行にまとめる。調べられない場所は行に出さない(待ちにしない)"""
        now = time.time()
        with self._disk_lock:
            if not force and self._disk is not None and now - self._disk_at < self.disk_poll:
                return self._disk
        rows, by_drive = [], {}
        for label, path in self.disk_paths():
            probe = path
            while probe and not os.path.exists(probe):   # まだ無いフォルダは、ある所まで上へ(src/home/health.py の disk_free と同じ)
                parent = os.path.dirname(probe)
                if parent == probe:
                    break
                probe = parent
            try:
                free, total = self.disk_usage(probe)
                free, total = int(free), int(total)
            except (OSError, ValueError, TypeError):
                continue
            drive = os.path.splitdrive(os.path.abspath(probe))[0].upper() or os.path.abspath(probe)
            if drive in by_drive:
                by_drive[drive]["label"] += "・" + label
                continue
            row = {"label": label, "path": path, "drive": drive, "freeBytes": free, "totalBytes": total,
                   "state": "low" if free < DISK_LOW else "warn" if free < DISK_WARN else "ok"}
            by_drive[drive] = row
            rows.append(row)
        low = [r for r in rows if r["state"] == "low"]
        warn = [r for r in rows if r["state"] == "warn"]
        state = "low" if low else "warn" if warn else "ok"
        where = lambda rs: "・".join("%s(%s)の空き %.1f GB" % (r["label"], r["drive"], r["freeBytes"] / GB) for r in rs)   # noqa: E731
        msg = ("空き容量が少ないので、新しい書き出し・文字起こしを止めて待っています(%s。%d GB 以上空くと続けます)" % (where(low), DISK_LOW // GB) if low else
               "空き容量が %d GB を切りました(%s)。片付けを考えてください" % (DISK_WARN // GB, where(warn)) if warn else "")
        res = {"state": state, "rows": rows, "message": msg, "checkedAt": now_iso(), "lowBytes": DISK_LOW, "warnBytes": DISK_WARN}
        with self._disk_lock:
            self._disk, self._disk_at = res, now
            said, self._disk_said = self._disk_said, state
        if said != state:   # 変わったときだけ記録する
            self.log("リアルタイム切り抜き: " + (msg or "空き容量が戻ったので、書き出し・文字起こしを続けます"))
        return res

    def _disk_low(self):
        """空きが DISK_LOW 未満か(調べる所の不具合では止めない = False)"""
        try:
            return self.disk()["state"] == "low"
        except Exception:
            return False

    # --- 動かす ---
    def start(self):
        with self.lock:
            if self._thread is None or not self._thread.is_alive():
                self._halt.clear()
                self._thread = threading.Thread(target=self._loop, daemon=True, name="live-export")
                self._thread.start()

    def close(self):
        self._halt.set()
        self.wake.set()
        t = self._thread
        if t is not None:
            t.join(15)

    def _loop(self):
        while not self._halt.is_set():
            try:
                self._retry_handoffs()   # 空きを待っていた まとめて実行への受け渡し(M4)
                job = self._next_ready()
                if job is not None:
                    self._process(job)
                    continue
            except Exception as e:   # 見回りは止めない
                self.log("リアルタイム切り抜き: 書き出しの見回りでエラー: %r" % (e,))
            self.wake.wait(self.poll)
            self.wake.clear()

    def _next_ready(self):
        """録画待ちのジョブを順に見て、録画が届いた最初の1本を返す(録画元への問い合わせは、同じ録画は1回だけ)。
        空きが少ない(M4)ときは、どれも始めずに「空き待ち」の文を出す(録画元にも問い合わせない)"""
        with self.lock:
            waiting = [j for j in self.jobs if j["state"] == "wait" and not j.get("cancel")]
        if not waiting:
            return None
        dk = self.disk() if self._disk_low() else None
        for job in waiting:
            if dk is not None:
                job.update(message=dk["message"], diskWait=True)   # 数分ごとには変わらないが、記録のファイルには書かない(空けば消える)
            elif job.pop("diskWait", None):
                job["message"] = "空きが戻ったので、続けます"
        if dk is not None:
            return None
        seen = {}
        for job in waiting:
            if self._halt.is_set() or job.get("cancel"):
                continue
            key = (job["recorder"], job["recording"])
            a, b = iso_epoch(job["start"]), iso_epoch(job["end"])
            if key not in seen:
                seen[key] = self._query(job["recorder"], job["recording"], a, b)
            code, d = seen[key]
            if code is None:   # つながらない
                since = job.get("downSince") or time.time()
                if not job.get("downSince"):
                    job["downSince"] = since
                rc = self.live.find(job["recorder"]) or {"name": job["recorder"]}
                if time.time() - since > self.down_sec:
                    if self._backup_for(job, a, b):
                        return job
                    self._set(job, state="error", error="録画元「%s」に %d 秒つながりませんでした(録画の部品が止まっているかもしれません。予備の録画元もありません)"
                              % (rc.get("name"), int(self.down_sec)), message="")
                elif job.get("message", "").find("つながりません") < 0:
                    self._set(job, message="録画元「%s」につながりません。待っています…" % rc.get("name"))
                continue
            job.pop("downSince", None)
            if code == 404:
                self._set(job, state="error", error="録画が見つかりません(録画元で消されたか、置き場所を変えたかもしれません)", message="")
                continue
            if code != 200 or not isinstance(d, dict):
                self._set(job, state="error", error="録画元から思わぬ応答がありました(HTTP %s)" % code, message="")
                continue
            last = iso_epoch(d.get("lastPdt"))
            if last is not None and last >= b + READY_PAD:
                return job
            if not d.get("active"):   # 録画が終わった: 録れた所までで切る
                if last is not None and last - a >= 1.0:
                    job["end"] = epoch_iso(last)
                    job["warning"] = "録画が区間の終わりまで届かなかったので、録画の終わり(%s)までで切りました" % job["end"][11:19]
                    return job
                self._set(job, state="error", error="録画が区間まで届きませんでした(録画は「%s」です)" % (d.get("state") or "?"), message="")
                continue
            left = b + READY_PAD - (last if last is not None else a)
            msg = "録画が届くのを待っています(あと約 %d 秒)" % max(1, int(left + 0.999))
            if job.get("message") != msg:
                job["message"] = msg   # 数秒ごとに変わるので記録のファイルには書かない
        return None

    def _query(self, rc_id, rec, a, b):
        rc = self.live.find(rc_id)
        if rc is None:
            return 404, None
        return self.live.call(rc, "GET", "/live/%s/segments?%s" % (rec, urllib.parse.urlencode({"start": epoch_iso(a), "end": epoch_iso(b)})),
                              timeout=10.0)

    def _sources(self, job, a, b):
        """取得の順番: 主(マークを付けた録画)→ 予備(ほかの録画元で、同じ配信の URL を録っている録画)。-> [(rc, rec, 区間の答え)]"""
        out = []
        code, d = self._query(job["recorder"], job["recording"], a, b)
        rc = self.live.find(job["recorder"])
        url = ""
        if code == 200 and isinstance(d, dict):
            out.append((rc, job["recording"], d))
            url = d.get("url") or ""
        if not url:
            try:
                url = self.marks.load(job["recorder"], job["recording"]).get("url") or ""
            except LiveError:
                url = ""
        if url:
            for other in self.live.recorders():
                if other.get("id") == job["recorder"]:
                    continue
                for r in rec_list(self.live.call, other) or []:
                    if r.get("url") == url:
                        c3, d3 = self._query(other["id"], r["id"], a, b)
                        if c3 == 200 and isinstance(d3, dict):
                            out.append((other, r["id"], d3))
        return out

    def _backup_for(self, job, a, b):
        """主がつながらない: 予備の録画元に、区間まで録れた録画があれば True(取得は _process が順に試す)"""
        for rc, rec, d in self._sources(job, a, b):
            last = iso_epoch(d.get("lastPdt"))
            if rc and rc.get("id") != job["recorder"] and last is not None and last >= b + READY_PAD and not d.get("gaps"):
                return True
        return False

    # --- 1本を書き出す ---
    def _cancelled(self, job):
        if self._halt.is_set():
            raise Halted()
        if job.get("cancel"):
            raise Cancelled()

    def _process(self, job):
        a, b = iso_epoch(job["start"]), iso_epoch(job["end"])
        wdir = os.path.join(self.work, job["id"])
        self._set(job, state="fetch", message="録画元から録画のデータを取っています", error="", progress=0, attempts=(job.get("attempts") or 0) + 1)
        tmp = None
        try:
            got, why = None, []
            for rc, rec, d in self._sources(job, a, b):
                self._cancelled(job)
                if not job.get("recBase") and iso_epoch(d.get("firstPdt")) is not None:   # 録画の頭の時刻(P4 で欠けのマークをアーカイブから作るときの名前・range に使う)
                    job["recBase"] = epoch_iso(iso_epoch(d["firstPdt"]))
                name = (rc or {}).get("name") or "?"
                if d.get("gaps"):
                    g = d["gaps"][0]
                    why.append("「%s」の録画は %s〜%s の %.0f 秒が欠けています" % (name, g["from"][11:19], g["to"][11:19], g["sec"]))
                    continue
                segs = d.get("segments") or []
                if not segs or not all(SEG_URI_RE.match(str(s.get("uri") or "")) for s in segs):
                    why.append("「%s」に区間の録画のデータがありません" % name)
                    continue
                try:
                    files = self._fetch(job, rc, rec, segs, wdir)
                except OSError as e:
                    why.append("「%s」から取れませんでした(%s)" % (name, e))
                    continue
                got = (rc, rec, d, segs, files)
                break
            if got is None:
                gap = any("欠けて" in w for w in why)
                self._set(job, state="error", needsArchive=gap, message="",
                          error=("区間に録画の欠けがあるので書き出せません(要差し替え。録画が終わってから、アーカイブで作り直すと書き出せます)。" if gap else
                                 "録画を取れませんでした。") + " / ".join(why or ["録画元につながりません"]))
                return
            rc, rec, d, segs, files = got
            self._set(job, source=rc["id"], message="取得しました(%d 個)。作り直しの順番を待っています" % len(segs))
            with self.slots.slot("live", "リアルタイム切り抜き %s" % (job.get("label") or job["id"]),
                                 cancelled=lambda: bool(job.get("cancel")) or self._halt.is_set(),
                                 on_wait=lambda: self._set(job, message="ほかの重い処理が終わるのを待っています"),
                                 reserved=bool(d.get("active"))) as ok:   # 録画中は用途つきの枠も使う(M6。文字起こしで上限が埋まっていても待たない)
                self._cancelled(job)
                if not ok:
                    raise Cancelled()
                self._set(job, state="encode", message="30fps に作り直しています")
                out, tmp = self._encode(job, rc, rec, d, segs, files, a, b, wdir)
            tmp = None
            self._finish(job, rc, rec, d, out, a, b)
        except Cancelled:
            self._set(job, state="cancelled", message="取り消しました", progress=0)
        except Halted:
            self._set(job, state="wait", message="ホームを終えたので、次の起動でやり直します", progress=0)
        except (LiveError, normalize.NormalizeError) as e:
            self._set(job, state="error", error=str(e), message="")
        except OSError as e:
            self._set(job, state="error", error="書けませんでした: %s" % tools.why(e), message="")
        except Exception as e:
            self.log("リアルタイム切り抜き: 書き出しでエラー %r" % (e,))
            self._set(job, state="error", error="内部エラー: %s" % e.__class__.__name__, message="")
        finally:
            if tmp:
                fsio.unlink_quiet(tmp)
            shutil.rmtree(wdir, ignore_errors=True)
            job.pop("cancel", None)

    def _fetch(self, job, rc, rec, segs, wdir):
        """セグメントをセッションごとに1つの .ts へつなぐ(同じセッションの TS は時刻が続いているので、そのままつなげる)。-> [(ファイル, セッション)]"""
        os.makedirs(wdir, exist_ok=True)
        files, cur, f = [], None, None
        try:
            for i, s in enumerate(segs):
                self._cancelled(job)
                if s["session"] != cur:
                    if f:
                        f.close()
                    cur = s["session"]
                    path = os.path.join(wdir, "part_%02d.ts" % len(files))
                    files.append((path, cur))
                    f = open(path, "wb")
                conn, r = self.live.request(rc, "GET", "/live/%s/%s" % (rec, s["uri"]), timeout=FETCH_TIMEOUT)
                try:
                    if r.status != 200:
                        raise OSError("HTTP %s" % r.status)
                    while True:
                        chunk = r.read(256 * 1024)
                        if not chunk:
                            break
                        f.write(chunk)
                finally:
                    conn.close()
                job["progress"] = round((i + 1) / len(segs) * 0.2, 3)   # 取得は全体の 2 割として見せる
        finally:
            if f:
                f.close()
        return files

    def _encode(self, job, rc, rec, d, segs, files, a, b, wdir):
        ff = self.ffmpeg or tools.find_tool("ffmpeg", "YTT_FFMPEG")
        if not ff:
            raise LiveError("ffmpeg が見つかりません")
        first = iso_epoch(segs[0]["pdt"])
        ss, dur = max(0.0, a - first), b - a
        if len(files) == 1:
            src = ["-i", files[0][0]]
        else:   # 繋ぎ直しをまたぐ(欠けは無い): セッションごとのファイルを concat でつなぐ(時刻はファイルの長さで続ける)
            lst = os.path.join(wdir, "parts.txt")
            with open(lst, "w", encoding="utf-8") as f:
                for p, _ in files:
                    f.write("file '%s'\n" % p.replace("\\", "/").replace("'", "'\\''"))
            src = ["-f", "concat", "-safe", "0", "-i", lst]
        folder, base, title = self.target(job, d, rec, a, b)
        tmp = names.partial_path(folder, base)
        flags = tools.no_window_flags(priority="low")   # 書き出しは「通常より下」(録画は「通常より上」)
        # -ss は入力の前(作り直しなので位置はコマ単位で正確)。長さは出力の -t で決める(入力の -t だけだと、fps フィルタが最後のコマを
        # 増やして映像が約 0.5 秒長くなる。2026-10-04 に確かめた)。入力の -t は読む量を抑えるだけ(少し長めに)
        head_args = [ff, "-hide_banner", "-nostdin", "-y", "-v", "error", "-ss", "%.3f" % ss, "-t", "%.3f" % (dur + 1.0)] + src + \
                    ["-t", "%.3f" % dur, "-map", "0:v:0", "-map", "0:a:0?", "-sn", "-dn"]
        enc = normalize.encode_args()
        code, tail, why = self._run(job, head_args + enc + ["-progress", "pipe:1", "-nostats", tmp], dur, flags)
        if code != 0 and why is None and normalize.is_fps_mode_error("\n".join(tail)):   # ffmpeg 5.1 より古い
            fsio.unlink_quiet(tmp)
            code, tail, why = self._run(job, head_args + normalize.legacy_args(enc) + ["-progress", "pipe:1", "-nostats", tmp], dur, flags)
        if why == "cancel":
            fsio.unlink_quiet(tmp)
            self._cancelled(job)
            raise Cancelled()
        if code != 0:
            fsio.unlink_quiet(tmp)
            raise LiveError("作り直しに失敗しました: %s" % (" / ".join(tail[-3:]) or "終了コード %s" % code))
        try:
            audio = self._adjust_audio(job, ff, tmp, dur, flags)
        except BaseException:   # 取り消し・入口の終了・失敗: 書きかけは残さない
            fsio.unlink_quiet(tmp)
            raise
        info = normalize.probe(tmp, self.ffprobe)
        if not normalize.is_30fps(info):
            fsio.unlink_quiet(tmp)
            raise LiveError("作り直した動画が 30fps になっていません(%s)" % ((info or {}).get("r_frame_rate") or "読めません"))
        if info.get("duration") is None or abs(info["duration"] - dur) > LEN_TOL:
            fsio.unlink_quiet(tmp)
            raise LiveError("作り直した動画の長さが区間と違います(区間 %.2f 秒 / 動画 %s 秒)"
                            % (dur, "不明" if info.get("duration") is None else "%.2f" % info["duration"]))
        final = os.path.join(folder, base + ".mp4")
        fsio.replace_retry(tmp, final)
        return dict(info, path=final, title=title, audio=audio), None

    def target(self, job, d, rec, a, b):
        """書き出す場所と名前(スタジオの書き出しと同じ規則)。-> (配信のフォルダ, 名前(拡張子なし), 題)。
        アーカイブで新しく作る(P4。src/home/live_archive.py の欠けのマーク)も同じ規則で決める"""
        title = self._title(job, d)
        root = self.out_dir()
        if not root or not os.path.isabs(root):
            raise LiveError("書き出し先が決まっていません(スタジオの ③ 書き出しの「保存先」を確かめてください)")
        os.makedirs(root, exist_ok=True)
        owner = video_id_of(d.get("url"), rec) or "live-" + rec
        folder = pick_folder(root, title, owner)
        base = self._base(d, a)
        return folder, names.clip_base(folder, job.get("n") or 0, a - base, b - base, job.get("label"), unique=unique_base), title

    def _audio_cfg(self):
        """-> (音量(%。100 = 変えない), ラウドネスの目標 LUFS か None)。形が正しくなければ「変えない」"""
        try:
            a = self.audio() if self.audio else None
        except Exception:
            a = None
        a = a if isinstance(a, dict) else {}
        try:
            loud = loudness.check_target(a.get("loudness"))
        except ValueError:
            loud = None
        try:
            vol = loudness.check_volume(a.get("volume")) or 100
        except ValueError:
            vol = 100
        return vol, loud

    def _adjust_audio(self, job, ff, path, dur, flags):
        """作り直した動画の音量を、スタジオの書き出しと同じ設定にそろえる(音声だけ作り直し。映像は -c:v copy で無劣化)。
        ラウドネスのとき: 測って(loudnorm)・上げ下げの量は ytt_core.loudness.gain(音が割れない・上げすぎない範囲)。
        -> .clip.json の export に足す項目({"loudness": {...}} か {"volume": %}。スタジオの _clip_export_info と同じ形)"""
        vol, loud = self._audio_cfg()
        if not loud and vol == 100:
            return {"volume": 100}
        info = normalize.probe(path, self.ffprobe)
        if info is not None and not info.get("has_audio"):   # 音声の無い録画: 何もしない
            return {"loudness": {"target": loud, "skipped": "音声がありません"}} if loud else {"volume": vol}
        if loud:
            self._set(job, message="音量(%g LUFS)をそろえています" % loud)
            cmd = [ff, "-hide_banner", "-nostdin", "-i", path, "-vn", "-af", "loudnorm=print_format=json", "-f", "null", "-",
                   "-progress", "pipe:1", "-nostats"]
            code, tail, why = self._run(job, cmd, dur, flags)
            if why == "cancel":
                self._cancelled(job)
                raise Cancelled()
            i, tp = loudness.parse(" ".join(tail)) if code == 0 else (None, None)
            if i is None:   # 無音・測れない: 音量は変えない(スタジオと同じ)
                return {"loudness": {"target": loud, "skipped": "音声が無いか、無音のため測れませんでした"}}
            g = loudness.gain(loud, i, tp)
            res = {"loudness": loudness.result(loud, i, g)}
            if abs(g) < loudness.MIN_GAIN_DB:
                return res
            af, what = "volume=%.2fdB" % g, "ラウドネス調整"
        else:
            res, af, what = {"volume": vol}, "volume=%.3f" % (vol / 100.0), "音量調整"
        self._set(job, message="音量を調整しています")
        out = path + ".vol.mp4"
        cmd = [ff, "-hide_banner", "-nostdin", "-y", "-v", "error", "-i", path, "-map", "0:v:0", "-map", "0:a:0?", "-sn", "-dn",
               "-c:v", "copy", "-af", af, "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", "-progress", "pipe:1", "-nostats", out]
        code, tail, why = self._run(job, cmd, dur, flags)
        if why == "cancel" or code != 0:
            fsio.unlink_quiet(out)
            if why == "cancel":
                self._cancelled(job)
                raise Cancelled()
            raise LiveError("%sに失敗しました: %s" % (what, " / ".join(tail[-3:]) or "終了コード %s" % code))
        fsio.replace_retry(out, path)
        return res

    def _run(self, job, cmd, dur, flags):
        """ffmpeg を1回動かす(取り消し・入口の終了で止める)。-> (終了コード, エラーの行, None|"cancel")。
        中身は ytt_core.tools.run_progress(-progress の進み具合を job["progress"] の 0.2〜1.0 に写す)"""
        def on_time(sec):
            if dur > 0:
                job["progress"] = round(0.2 + 0.8 * min(0.99, sec / dur), 3)
        try:
            return tools.run_progress(cmd, flags=flags, cancelled=lambda: job.get("cancel") or self._halt.is_set(), on_time=on_time)
        except OSError as e:
            raise LiveError("ffmpeg を起動できませんでした: %s" % e)

    @staticmethod
    def _base(d, a):
        """range の 0 秒 = 録画の最初のセグメントの受信時刻(配信の開始時刻はまだ取らない。計画の 3 の 3 番目)"""
        f = iso_epoch(d.get("firstPdt"))
        return f if f is not None and f <= a else a

    def _title(self, job, d):
        try:
            mk = self.marks.load(job["recorder"], job["recording"])
        except LiveError:
            mk = {}
        return (d.get("title") or mk.get("title") or "").strip() or video_id_of(d.get("url"), job["recording"]) or job["recording"]

    def _finish(self, job, rc, rec, d, out, a, b, archive=None, message="書き出しました"):
        """archive: アーカイブから新しく作った(P4。src/home/live_archive.py の欠けのマーク)ときの source.live.archive {videoId, start, end, offset, residual, at}"""
        base = self._base(d, a)
        media = out["path"]
        vid = video_id_of(d.get("url"), rec)
        origin = job.get("origin") if job.get("origin") in ORIGINS else "manual"
        clip = schemas.build_clip(media, out.get("duration"), {"kind": "youtube", "videoId": vid, "title": out["title"]},
                                  (a - base, b - base), {"id": job["markId"], "label": job.get("label") or "", "status": "exported",
                                                         "src": "manual" if origin == "manual" else "auto"},   # 自動の採用(auto・archive)は機械が選んだ区間
                                  dict({"mode": "precise", "fps": "30/1", "from": "youtube-archive" if archive else "live-recording"},
                                       **(out.get("audio") or {"volume": 100})), TOOL)   # 音量は実際にかけた値(スタジオの _clip_export_info と同じ形)
        clip["source"] = {"kind": "live", "videoId": vid, "url": None, "title": out["title"], "path": None,
                          "live": {"url": d.get("url") or "", "recorder": rc["id"], "recording": rec, "base": epoch_iso(base),
                                   "start": epoch_iso(a), "end": epoch_iso(b), "markId": job["markId"], "origin": origin}}
        if isinstance(job.get("score"), (int, float)):
            clip["source"]["live"]["score"] = job["score"]   # 候補の点数(M9 の確認の一覧が出す)
        req = job.get("request") if isinstance(job.get("request"), dict) else {}
        if req.get("rid"):   # 友人の依頼・自動で届ける切り抜き(届けるのは まとめて実行)。見ていない切り抜きの片付け(cases.expire_unseen)はこれがあれば片付けない
            clip["source"]["live"]["deliver"] = {"rid": str(req["rid"])[:40], "auto": req.get("autoDeliver") is True}
        if isinstance(job.get("studio"), dict):   # スタジオのマークから(P3): スタジオの配信(= 録画の id)とマークの id も残す
            clip["source"]["live"]["studio"] = {"video": job["studio"].get("video"), "mark": job["studio"].get("mark")}
        if archive:
            clip["source"]["live"]["archive"] = dict(archive)
        warn = [job["warning"]] if job.get("warning") else []
        manifest = ""
        try:
            manifest = schemas.clip_path_for(media)
            os.makedirs(os.path.dirname(manifest), exist_ok=True)
            fsio.write_json(manifest, clip)
        except OSError as e:
            manifest = ""
            warn.append("切り抜きの情報ファイル(.clip.json)を保存できませんでした(動画はそのまま使えます): %s" % tools.why(e))
        run_id, handoff, wait = "", "", ""
        after = job_after(job)
        if after != "none":   # 書き出したあと: まとめて実行の動画ファイルの形へ(check = 文字起こしまで・auto = 文字起こし → パック)
            if job.get("holdFor") == "archive" and not archive:   # 本番版に入れ替えてから渡す(M7。アーカイブから作った本番版はすぐ渡す)
                wait = "archive"
            elif self._disk_low():   # 空きが少ない(M4): 空くまで渡さない
                wait = "disk"
            else:
                run_id, handoff, more = self._handoff(job, media, after)
                warn += more
        marked = self._studio_exported(job, media, bool(archive))
        if marked:
            warn.append(marked)
        self._set(job, state="done", progress=1.0, path=media, manifest=manifest, runId=run_id, warning=" / ".join(warn), recBase=epoch_iso(base),
                  handoffError=handoff, handoffWait=wait, message=message + self._after_note(after, run_id, wait))
        self.log("リアルタイム切り抜き: 書き出しました %s" % media)
        if handoff:
            self.log("リアルタイム切り抜き: " + live_failures.failure_of(dict(job, path=media, handoffError=handoff))["text"])

    @staticmethod
    def _after_note(after, run_id, wait):
        """書き出したあとの文(メッセージの後ろに付ける)"""
        what = "文字起こし → パック" if after == "auto" else "文字起こし"
        if run_id:
            return "。%sの順番に入れました(ホームの「まとめて実行」)" % what
        if wait == "archive":
            return "。アーカイブで本番版に入れ替えてから、%sへ渡します" % what
        if wait == "disk":
            return "。空き容量が少ないので、空くまで%sへ渡すのを待っています" % what
        return ""

    def _handoff(self, job, media, after):
        """まとめて実行へ渡す(動画ファイルの形 start_file)。-> (run の id, 渡せなかった理由(handoffError), 警告の文のリスト)"""
        warn, run_id, handoff = [], "", ""
        who = None
        if job.get("streamer"):   # 配信者の名前(字幕の色)。照らし合わせられなければ色なしで進める(書き出しは止めない)
            try:
                who = colors.resolve(job["streamer"])[0]
            except ValueError as e:
                warn.append("配信者「%s」が色の一覧と合わないので、字幕の色なしで進めます(%s)" % (job["streamer"][:60], str(e)[:120]))
        auto = job.get("auto") if isinstance(job.get("auto"), dict) else {}
        kw = {k: auto[k] for k in AUTO_KEYS if auto.get(k)}   # 書き出したあとの設定(live.auto の cut・engine・model。M2)。無ければ今までどおり
        try:
            r = self.runner() if self.runner else None
            if r is None:
                raise ValueError("まとめて実行が使えません")
            req = job.get("request") if isinstance(job.get("request"), dict) and job["request"].get("rid") else None
            if req:   # 友人のライブ配信の依頼の録画(2-15): 依頼 id・届け先・配信者の設定を渡す = パックを 1 本ずつ友人へ届ける
                kw.update(request_id=req["rid"], deliver_dir=req.get("deliverDir") or None, speakers=req.get("speakers"), video_tracks=req.get("videoTracks"),
                          deliver_batch=req.get("deliverBatch"), pool=deliver_pool(job, req))   # 届け方は依頼の指定(無ければホームの設定)・n 本の組は録画をまたいで溜める
                if req.get("cut"):
                    kw["cut"] = req["cut"]
            run_id = (r.start_file(media, title=os.path.splitext(os.path.basename(media))[0], streamer=who, flow=after, **kw) or {}).get("id") or ""
        except Exception as e:   # 失敗の集約(M3)は handoffError から文を作る(warning に重ねない)
            handoff = ("パックへ" if after == "auto" else "文字起こしへ") + "渡せませんでした: %s" % str(e)[:160]
        return run_id, handoff, warn

    def _hand_over(self, job, note=""):
        """待っていた まとめて実行への受け渡しを今する(M4 の空き待ち・M7 の本番版待ち)。空きが少なければ「空き待ち」に。-> run の id か "\""""
        after = job_after(job)
        media = job.get("path") or ""
        if after == "none" or not media or not os.path.isfile(media):
            self._set(job, handoffWait="", handoffError="" if after == "none" else
                      ("パックへ" if after == "auto" else "文字起こしへ") + "渡せませんでした: 書き出した動画が見つかりません(動かしたか消したかもしれません)")
            return ""
        notes = [x for x in str(job.get("warning") or "").split(" / ") if x]
        if note and note not in notes:
            notes.append(note)
        if self._disk_low():
            self._set(job, handoffWait="disk", warning=" / ".join(notes), message="書き出しました" + self._after_note(after, "", "disk"))
            return ""
        run_id, handoff, more = self._handoff(job, media, after)
        self._set(job, handoffWait="", runId=run_id, handoffError=handoff, warning=" / ".join(notes + more),
                  message="書き出しました" + self._after_note(after, run_id, ""))
        if run_id:
            self.log("リアルタイム切り抜き: まとめて実行へ渡しました %s" % media)
        elif handoff:
            self.log("リアルタイム切り抜き: " + live_failures.failure_of(dict(job, handoffError=handoff))["text"])
        return run_id

    def release_hold(self, job, note=""):
        """本番版への作り直しを待っていた書き出し(handoffWait "archive"。M7)を まとめて実行へ渡す(src/home/live_archive.py から。
        入れ替えが済んだとき・作り直せなかったとき(note に理由 = 速報版のまま渡す))。-> run の id か ""(渡さなかった・空き待ち)"""
        with self.lock:
            if job.get("state") != "done" or job.get("handoffWait") != "archive":
                return ""
        return self._hand_over(job, note)

    def _retry_handoffs(self):
        """空きを待っていた受け渡し(handoffWait "disk")を、空きが戻ったら渡す(M4)"""
        with self.lock:
            todo = [j for j in self.jobs if j.get("state") == "done" and j.get("handoffWait") == "disk"]
        if not todo or self._disk_low():
            return 0
        for j in todo:
            self._hand_over(j)
        return len(todo)

    def _studio_exported(self, job, media, archived=False):
        """スタジオのマーク(ジョブの studio)を「書き出し済み」にする(M1: 画面を閉じていても。画面も同じ API を呼ぶ = 何度呼んでも同じ)。
        -> 警告の文(できなかったとき)か ""。スタジオが動いていない・入口のサーバーが無い(テスト)ときは黙って飛ばす(画面が開いたときに突き合わせる)"""
        st = job.get("studio") if isinstance(job.get("studio"), dict) else None
        call = getattr(self.live, "studio_call", None)
        if not st or not st.get("video") or not st.get("mark") or call is None:
            return ""
        body = {"id": st["video"], "markId": st["mark"], "path": media}
        if archived:
            body["archived"] = True
        try:
            code, d = call("POST", "/api/live/exported", body)
        except Exception as e:
            return "スタジオのマークを「書き出し済み」にできませんでした(%s)" % e.__class__.__name__
        if code is None or code == 200:
            return ""
        return "スタジオのマークを「書き出し済み」にできませんでした: %s" % str((d or {}).get("message") or "HTTP %s" % code)[:160]


def _disk_usage(path):
    """(空き, 全体) のバイト数(Exporter.disk の既定)"""
    u = shutil.disk_usage(path)
    return u.free, u.total
