# -*- coding: utf-8 -*-
"""リアルタイム切り抜き(線 D の P2: マークと書き出し。docs/plan/live-clipping-plan.md の 0・5・6)の入口の側の中身。
画面と API は home/live.py(設定 live.enabled がオンのときだけ)。ここは「マークの正本」と「書き出しのジョブ」。

マーク(MarkStore):
  録画1本(録画元 + 録画の id)ごとに、入口の作業データの live/marks/<録画元>__<録画の id>.json に置く(マークの正本)。
  押すたびに、一時ファイルに書いて fsync してから置き換える(ytt_core.fsio.atomic_write(fsync_required=True))。
  時刻は絶対時刻(UTC。hls.js の playingDate = 録画元の受信時刻 PDT)で持つ。
  計画の 5 は「追記専用の JSONL」だが、ラベルの変更・終了の後付け・削除があるので、全体を原子的に置き換える形にした(壊れるのは「前の版のまま」だけ)。
  バックアップは作業データのバックアップ(home/backup.py。変わってから QUIET 秒で写す)に乗る。

書き出しのジョブ(Exporter。計画の 6。1本ずつ順に):
  1. 録画待ち … マークの終わりの時刻まで録画が届くのを待つ(録画元の /live/<録画>/segments の lastPdt。届く前に録画が終われば、録れた所までで切る)
  2. 取得     … 区間にかかるセグメント(4 秒ごとの .ts)だけを録画元から取る。録画元は 主 → 予備(同じ配信を録っている別の録画元。2台のとき)の順。
                 区間に欠け(繋ぎ直しの間など)があれば書き出さずに「要差し替え」(P4 のアーカイブで作り直す)
  3. 作り直し … セッションごとにつないで(TS はそのままつなげる)、正確な区間に切って ytt_core.normalize と同じ設定で 30fps に(SLOTS を通す)
  4. 検証     … ffprobe で 30/1・長さ(区間 ±0.5 秒)を確かめてから本当の名前へ
  5. 完了     … スタジオの書き出しと同じ置き場所(スタジオの書き出し先\<配信の名前>\)・名前の規則・作業用\<名前>.clip.json。
                 文字起こしへ(任意)は入口の「まとめて実行」の文字起こしだけの形(autorun.start_file。mode file)に入れる
  ジョブは live/exports.json に残す。入口を起動し直したら、途中だったジョブは「録画待ち」からやり直す(冪等: 書きかけは消し、名前は仕上げるときに決める)。

.clip.json の source(pipeline.md の 2.1 に足す値): kind "live"。range は「録画の最初のセグメントの受信時刻」からの秒、
絶対時刻と録画の素性は source.live に入れる(P4 でアーカイブの時刻へ置き換えるため)。videoId は YouTube の動画の id(分かるとき)。
url は入れない(range がアーカイブの秒ではないので、YouTube の位置へのリンクにしない)。
"""
import datetime
import glob
import json
import os
import re
import secrets
import shutil
import subprocess
import threading
import time
import urllib.parse

from ytt_core import fsio, jobs, normalize, schemas, tools

VERSION = "0.1.0"
TOOL = {"name": "ytt-live", "version": VERSION}
MARKS_SCHEMA = "ytt-live-marks/v1"
JOBS_SCHEMA = "ytt-live-exports/v1"
ID_RE = re.compile(r"^[a-z][a-z0-9-]{0,15}\Z")                       # 録画元の id(home/live.py の RELAY_RE と同じ)
REC_RE = re.compile(r"^\d{8}-\d{6}(?:-[A-Za-z0-9_-]{1,24})?\Z")      # 録画の id(recorder/rec_core.py の REC_ID_RE と同じ)
MARK_RE = re.compile(r"^lm-[0-9a-f]{8,16}\Z")
JOB_RE = re.compile(r"^lx-[0-9a-f]{8,16}\Z")
SEG_URI_RE = re.compile(r"^session_\d{3,6}/seg_\d{6,9}\.ts\Z")
YT_ID_RE = re.compile(r"^[A-Za-z0-9_-]{11}\Z")
MAX_MARKS = 300            # 録画1本のマークの数
MAX_MARK_SEC = 3600        # 1つのマークの長さ(スタジオの MAX_MARK_SEC と同じ)
LABEL_MAX = 80
TITLE_MAX = 200
KEEP_JOBS = 200            # 終わったジョブを残す数
LEN_TOL = 0.2              # 書き出した長さと区間の差の上限(30fps の1コマ + 音声の端)。normalize の DURATION_TOL(0.5)より厳しく
READY_PAD = 1.0            # 終わりの時刻よりこの秒数先まで録れたら「届いた」(受信時刻の揺れの分)
POLL = 2.0                 # 録画待ちの見回りの間隔(秒)
DOWN_SEC = 60.0            # 録画元にこの秒数つながらなければ、予備を探して、無ければ失敗
FETCH_TIMEOUT = 30.0
STATES = ("wait", "fetch", "encode", "done", "error", "cancelled")
ACTIVE = ("wait", "fetch", "encode")
STATE_LABELS = {"wait": "録画待ち", "fetch": "取得中", "encode": "作り直し中", "done": "済み", "error": "失敗", "cancelled": "取り消し"}
# スタジオの書き出しと同じ名前の規則(studio/exporter.py。ツールをまたいで import しないので同じ値を持つ)
MAX_PATH_UNITS = 240
SUFFIX_ROOM = 36
BASE_ROOM = 26
PARTIAL = ".partial"
WIN_RESERVED = {"CON", "PRN", "AUX", "NUL", "CONIN$", "CONOUT$"} | {"COM%s" % d for d in "123456789¹²³"} | {"LPT%s" % d for d in "123456789¹²³"}


class LiveError(ValueError):
    """画面に出せる理由(code は HTTP の番号)"""
    def __init__(self, message, code=400):
        super().__init__(message)
        self.code = code


class Cancelled(Exception):
    pass


class Halted(Exception):
    """入口の終了(ジョブは「録画待ち」に戻して、次の起動でやり直す)"""


# ---------- 時刻 ----------
def iso_epoch(s):
    """UTC の時刻の文字列("…Z"・ミリ秒あり/なし・+00:00)→ epoch 秒。読めなければ None"""
    if not isinstance(s, str) or len(s) > 40:
        return None
    t = s.strip().replace("+00:00", "Z")
    for fmt in ("%Y-%m-%dT%H:%M:%S.%fZ", "%Y-%m-%dT%H:%M:%SZ"):
        try:
            return datetime.datetime.strptime(t, fmt).replace(tzinfo=datetime.timezone.utc).timestamp()
        except ValueError:
            continue
    return None


def epoch_iso(e):
    return datetime.datetime.fromtimestamp(e, datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def now_iso():
    return epoch_iso(time.time())


# ---------- 名前(スタジオの書き出しと同じ規則) ----------
def compact_ts(t):
    s = int(max(0, t))
    return "%02dh%02dm%02ds" % (s // 3600, s % 3600 // 60, s % 60)


def safe_name(s, n):
    s = re.sub(r'[\\/:*?"<>|%\x00-\x1f]+', "_", str(s or ""))
    return s[:n].strip(" ._")


def path_units(s):
    return len(str(s).encode("utf-16-le", "surrogatepass")) // 2


def trim_units(s, n):
    s = str(s)
    while s and path_units(s) > n:
        s = s[:-1]
    return s.rstrip(" ._")


def is_reserved(name):
    return name.split(".", 1)[0].rstrip(" ").upper() in WIN_RESERVED


def _read_owner(path):
    for m in (os.path.join(path, schemas.WORK_DIR, ".studio-id"), os.path.join(path, ".studio-id")):
        try:
            with open(m, encoding="utf-8") as f:
                return f.read().strip()
        except OSError:
            continue
    return None


def _write_owner(path, owner):
    os.makedirs(os.path.join(path, schemas.WORK_DIR), exist_ok=True)
    with open(os.path.join(path, schemas.WORK_DIR, ".studio-id"), "w", encoding="utf-8") as f:
        f.write(owner)


def pick_folder(root, title, owner):
    """<書き出し先>/<配信の名前>/(スタジオの pick_folder と同じ: 作業用/.studio-id に持ち主を書き、同じ名前の別の配信とは混ぜない)"""
    room = MAX_PATH_UNITS - path_units(root) - 1 - 3 - 1 - BASE_ROOM - SUFFIX_ROOM
    name = trim_units(safe_name(title, 60), max(8, min(60, room))) or safe_name(owner, 60) or "live"
    if is_reserved(name):
        name = "_" + name
    for i in range(1, 100):
        cand = name if i == 1 else "%s_%d" % (name, i)
        path = os.path.join(root, cand)
        if not os.path.exists(path):
            os.makedirs(path)
            _write_owner(path, owner)
            return path
        if os.path.isdir(path):
            got = _read_owner(path)
            if got == owner:
                return path
            if got is None:
                _write_owner(path, owner)
                return path
    raise LiveError("保存先のフォルダを作れませんでした")


def unique_base(base, folder):
    """フォルダ(と 作業用/)で使われていない名前(スタジオの unique_base と同じ。<名前>_edit も空いていること)"""
    def used(name):
        return any(glob.glob(glob.escape(os.path.join(d, n)) + ".*")
                   for d in (folder, os.path.join(folder, schemas.WORK_DIR)) for n in (name, name + "_edit"))
    name, i = base, 2
    while used(name):
        name = "%s_%d" % (base, i)
        i += 1
    return name


def video_id_of(url, rec_id=""):
    """YouTube の動画の id(11 文字)。分からなければ ""(録画の id の後ろ = recorder の new_rec_id が URL から取った物も見る)"""
    try:
        u = urllib.parse.urlsplit(url or "")
        q = urllib.parse.parse_qs(u.query)
        v = (q.get("v") or [""])[0]
        if not v and (u.hostname == "youtu.be" or u.path.startswith("/live/")):
            v = u.path.rstrip("/").rsplit("/", 1)[-1]
    except ValueError:
        v = ""
    if YT_ID_RE.match(v or ""):
        return v
    tail = (rec_id or "").split("-", 2)[2:] if rec_id else []
    return tail[0] if tail and YT_ID_RE.match(tail[0]) else ""


# ---------- マーク(正本) ----------
def _text(v, n):
    return re.sub(r"[\x00-\x1f\x7f]", " ", v if isinstance(v, str) else "").strip()[:n]


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
            if isinstance(body.get("url"), str) and not d.get("url"):
                d["url"] = _text(body["url"], 500)
            if isinstance(body.get("title"), str) and body["title"].strip():
                d["title"] = _text(body["title"], TITLE_MAX)
            marks = d["marks"]
            if op == "add":
                if len(marks) >= MAX_MARKS:
                    raise LiveError("1本の録画に付けられるマークは %d 個までです" % MAX_MARKS, 409)
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
            try:
                self._save(d)
            except OSError as e:
                raise LiveError("マークを保存できませんでした: %s" % (e.strerror or e.__class__.__name__), 500)
            return m, marks

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
    def __init__(self, live, folder, out_dir, runner=None, log=None, slots=None, poll=POLL, down_sec=DOWN_SEC, ffmpeg=None, ffprobe=None):
        """live: home/live.py の Live(録画元の一覧と要求)。folder: 入口の作業データの live\\。out_dir(): 書き出し先(スタジオの書き出し先)。
        runner(): まとめて実行(home/autorun.py の AutoRunner。文字起こしへ渡す)か None"""
        self.live, self.folder, self.out_dir, self.runner = live, folder, out_dir, runner
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
                j.update(state="wait", progress=0, message="入口を起動し直したので、やり直します")
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
        with self.lock:
            out = [dict((k, v) for k, v in j.items() if k != "cancel") for j in self.jobs
                   if (rc is None or j["recorder"] == rc) and (rec is None or j["recording"] == rec)]
        for j in out:
            j["stateLabel"] = STATE_LABELS.get(j["state"], j["state"])
            if j.get("runId") and j["runId"] in tx:
                j["tx"] = tx[j["runId"]]
        return list(reversed(out))

    def _tx_states(self):
        """文字起こしへ渡したジョブの、まとめて実行の状態(runId -> {state, label})"""
        try:
            r = self.runner() if self.runner else None
            runs = r.snapshot().get("runs") if r is not None else []
        except Exception:
            return {}
        return {x.get("id"): {"state": x.get("state"), "label": x.get("stateLabel"), "message": x.get("error") or x.get("message") or ""}
                for x in runs or [] if isinstance(x, dict)}

    def add(self, rc, rec, mid, transcribe=True):
        if self.live.find(rc) is None:
            raise LiveError("その録画元はありません", 404)
        m = self.marks.get(rc, rec, mid)
        if not m.get("end"):
            raise LiveError("終了をマークしてから書き出してください")
        with self.lock:
            if any(j for j in self.jobs if j["markId"] == mid and j["recording"] == rec and j["state"] in ACTIVE):
                raise LiveError("このマークは書き出しの途中です", 409)
            if sum(1 for j in self.jobs if j["state"] in ACTIVE) >= 50:
                raise LiveError("書き出しの順番待ちが多すぎます(50 本まで)", 409)
            job = {"id": "lx-" + secrets.token_hex(5), "recorder": rc, "recording": rec, "markId": mid, "n": m.get("n") or 0,
                   "label": m.get("label") or "", "start": m["start"], "end": m["end"], "transcribe": bool(transcribe),
                   "state": "wait", "message": "録画が届くのを待っています", "error": "", "needsArchive": False, "progress": 0,
                   "source": "", "path": "", "manifest": "", "runId": "", "warning": "", "attempts": 0,
                   "created": now_iso(), "updated": now_iso()}
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
        with self.lock:
            return any(j["state"] in ACTIVE for j in self.jobs)

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
                job = self._next_ready()
                if job is not None:
                    self._process(job)
                    continue
            except Exception as e:   # 見回りは止めない
                self.log("リアルタイム切り抜き: 書き出しの見回りでエラー: %r" % (e,))
            self.wake.wait(self.poll)
            self.wake.clear()

    def _next_ready(self):
        """録画待ちのジョブを順に見て、録画が届いた最初の1本を返す(録画元への問い合わせは、同じ録画は1回だけ)"""
        with self.lock:
            waiting = [j for j in self.jobs if j["state"] == "wait"]
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
                c2, lst = self.live.call(other, "GET", "/live/list", timeout=5.0)
                for r in (lst or {}).get("recordings") or [] if c2 == 200 and isinstance(lst, dict) else []:
                    if r.get("url") == url and REC_RE.match(str(r.get("id") or "")):
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
        self._set(job, state="fetch", message="録画元からセグメントを取っています", error="", progress=0, attempts=(job.get("attempts") or 0) + 1)
        tmp = None
        try:
            got, why = None, []
            for rc, rec, d in self._sources(job, a, b):
                self._cancelled(job)
                name = (rc or {}).get("name") or "?"
                if d.get("gaps"):
                    g = d["gaps"][0]
                    why.append("「%s」の録画は %s〜%s の %.0f 秒が欠けています" % (name, g["from"][11:19], g["to"][11:19], g["sec"]))
                    continue
                segs = d.get("segments") or []
                if not segs or not all(SEG_URI_RE.match(str(s.get("uri") or "")) for s in segs):
                    why.append("「%s」に区間のセグメントがありません" % name)
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
                          error=("区間に録画の欠けがあるので書き出せません(要差し替え。アーカイブで作り直す P4 で救えます)。" if gap else
                                 "録画を取れませんでした。") + " / ".join(why or ["録画元につながりません"]))
                return
            rc, rec, d, segs, files = got
            self._set(job, source=rc["id"], message="取得しました(%d 個)。作り直しの順番を待っています" % len(segs))
            with self.slots.slot("live", "リアルタイム切り抜き %s" % (job.get("label") or job["id"]),
                                 cancelled=lambda: bool(job.get("cancel")) or self._halt.is_set(),
                                 on_wait=lambda: self._set(job, message="ほかの重い処理が終わるのを待っています")) as ok:
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
            self._set(job, state="wait", message="入口を終えたので、次の起動でやり直します", progress=0)
        except LiveError as e:
            self._set(job, state="error", error=str(e), message="")
        except normalize.NormalizeError as e:
            self._set(job, state="error", error=str(e), message="")
        except OSError as e:
            self._set(job, state="error", error="書けませんでした: %s" % (e.strerror or e.__class__.__name__), message="")
        except Exception as e:
            self.log("リアルタイム切り抜き: 書き出しでエラー %r" % (e,))
            self._set(job, state="error", error="内部エラー: %s" % e.__class__.__name__, message="")
        finally:
            if tmp:
                _unlink(tmp)
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
        title = self._title(job, d)
        root = self.out_dir()
        if not root or not os.path.isabs(root):
            raise LiveError("書き出し先が決まっていません(スタジオの ③ 書き出しの「保存先」を確かめてください)")
        os.makedirs(root, exist_ok=True)
        owner = video_id_of(d.get("url"), rec) or "live-" + rec
        folder = pick_folder(root, title, owner)
        head = "%02d_%s-%s" % (job.get("n") or 0, compact_ts(a - self._base(d, a)), compact_ts(b - self._base(d, a)))
        room = MAX_PATH_UNITS - SUFFIX_ROOM - 3 - 1 - path_units(os.path.join(folder, head))
        label = trim_units(safe_name(job.get("label"), 30), max(0, room))
        base = unique_base(head + ("_" + label if label else ""), folder)
        tmp = os.path.join(folder, base + PARTIAL + ".mp4")
        flags = 0
        if os.name == "nt":
            flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) | getattr(subprocess, "BELOW_NORMAL_PRIORITY_CLASS", 0)   # 録画は「通常より上」・書き出しは「通常より下」
        # -ss は入力の前(作り直しなので位置はコマ単位で正確)。長さは出力の -t で決める(入力の -t だけだと、fps フィルタが最後のコマを
        # 増やして映像が約 0.5 秒長くなる。2026-10-04 に確かめた)。入力の -t は読む量を抑えるだけ(少し長めに)
        head_args = [ff, "-hide_banner", "-nostdin", "-y", "-v", "error", "-ss", "%.3f" % ss, "-t", "%.3f" % (dur + 1.0)] + src + \
                    ["-t", "%.3f" % dur, "-map", "0:v:0", "-map", "0:a:0?", "-sn", "-dn"]
        enc = normalize.encode_args()
        code, tail, why = self._run(job, head_args + enc + ["-progress", "pipe:1", "-nostats", tmp], dur, flags)
        if code != 0 and why is None and normalize.is_fps_mode_error("\n".join(tail)):   # ffmpeg 5.1 より古い
            _unlink(tmp)
            code, tail, why = self._run(job, head_args + normalize.legacy_args(enc) + ["-progress", "pipe:1", "-nostats", tmp], dur, flags)
        if why == "cancel":
            _unlink(tmp)
            self._cancelled(job)
            raise Cancelled()
        if code != 0:
            _unlink(tmp)
            raise LiveError("作り直しに失敗しました: %s" % (" / ".join(tail[-3:]) or "終了コード %s" % code))
        info = normalize.probe(tmp, self.ffprobe)
        if not normalize.is_30fps(info):
            _unlink(tmp)
            raise LiveError("作り直した動画が 30fps になっていません(%s)" % ((info or {}).get("r_frame_rate") or "読めません"))
        if info.get("duration") is None or abs(info["duration"] - dur) > LEN_TOL:
            _unlink(tmp)
            raise LiveError("作り直した動画の長さが区間と違います(区間 %.2f 秒 / 動画 %s 秒)"
                            % (dur, "不明" if info.get("duration") is None else "%.2f" % info["duration"]))
        final = os.path.join(folder, base + ".mp4")
        fsio.replace_retry(tmp, final)
        return dict(info, path=final, title=title), None

    def _run(self, job, cmd, dur, flags):
        """ffmpeg を1回動かす(取り消し・入口の終了で止める)。-> (終了コード, エラーの行, None|"cancel")"""
        tail, state = [], {"why": None}
        try:
            proc = subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, creationflags=flags)
        except OSError as e:
            raise LiveError("ffmpeg を起動できませんでした: %s" % e)
        done = threading.Event()

        def watchdog():
            while not done.wait(0.3):
                if job.get("cancel") or self._halt.is_set():
                    state["why"] = "cancel"
                    try:
                        proc.kill()
                    except OSError:
                        pass
                    return
        threading.Thread(target=watchdog, daemon=True).start()
        try:
            for raw in proc.stdout:
                line = raw.decode("utf-8", "replace").strip()
                m = re.match(r"^out_time_(?:us|ms)=(\d+)$", line)
                if m:
                    if dur > 0:
                        job["progress"] = round(0.2 + 0.8 * min(0.99, int(m.group(1)) / 1e6 / dur), 3)
                    continue
                if line and "=" not in line[:20]:
                    tail = (tail + [line])[-20:]
            proc.wait()
        finally:
            done.set()
            if proc.poll() is None:
                proc.kill()
            proc.stdout.close()
        return proc.returncode, tail, state["why"]

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

    def _finish(self, job, rc, rec, d, out, a, b):
        base = self._base(d, a)
        media = out["path"]
        vid = video_id_of(d.get("url"), rec)
        clip = schemas.build_clip(media, out.get("duration"), {"kind": "youtube", "videoId": vid, "title": out["title"]},
                                  (a - base, b - base), {"id": job["markId"], "label": job.get("label") or "", "status": "exported", "src": "manual"},
                                  {"mode": "precise", "volume": 100, "fps": "30/1", "from": "live-recording"}, TOOL)
        clip["source"] = {"kind": "live", "videoId": vid, "url": None, "title": out["title"], "path": None,
                          "live": {"url": d.get("url") or "", "recorder": rc["id"], "recording": rec, "base": epoch_iso(base),
                                   "start": epoch_iso(a), "end": epoch_iso(b), "markId": job["markId"]}}
        warn = [job["warning"]] if job.get("warning") else []
        manifest = ""
        try:
            manifest = schemas.clip_path_for(media)
            os.makedirs(os.path.dirname(manifest), exist_ok=True)
            fsio.write_json(manifest, clip)
        except OSError as e:
            manifest = ""
            warn.append("切り抜きの情報ファイル(.clip.json)を保存できませんでした(動画はそのまま使えます): %s" % (e.strerror or e.__class__.__name__))
        run_id = ""
        if job.get("transcribe"):
            try:
                r = self.runner() if self.runner else None
                if r is None:
                    raise ValueError("まとめて実行が使えません")
                run_id = (r.start_file(media, title=os.path.splitext(os.path.basename(media))[0], flow="check") or {}).get("id") or ""
            except Exception as e:
                warn.append("文字起こしへ渡せませんでした: %s" % str(e)[:160])
        self._set(job, state="done", progress=1.0, path=media, manifest=manifest, runId=run_id, warning=" / ".join(warn),
                  message="書き出しました" + ("。文字起こしの順番に入れました(ホームの「まとめて実行」)" if run_id else ""))
        self.log("リアルタイム切り抜き: 書き出しました %s" % media)


def _unlink(p):
    try:
        os.unlink(p)
    except OSError:
        pass
