# -*- coding: utf-8 -*-
"""友人の受信箱の正(F2-2。notes:plan/f1-friend-requirements.md の A-1・A-12・5 章・6 章)。

受信箱の記録は 1 つの JSON(<作業データ>/app/friendapp/inbox.json)だけ。画面は毎回ここを読む(Dropbox の一覧・② の記録から組み立て直さない)。
1 行 = 1 依頼 = 1 配信(A-4)。行の状態:
    sent     送った(② の待ち)
    making   作っている(② が実行中。進み具合は記録に写さず、画面に出すときに ② の状態を重ねる)
    arrived  届いた(パックがある。まだ決めていない物が残る)
    failed   失敗(理由・[もう一度送る]・[消す]。3 日で自動で片付く = 5-7)
    done     決めた(全部のパックを決めた = 画面に出さない。3 日で記録から消す)
パックの決め方(5-2〜5-6): keep = [受け取る](受け取るの保存先へ移す)/ reject = [要らない](ごみ箱へ)。どちらも送り返しの
<outbox>/<依頼 id>__<パック名>.verdict.json を書く(F2-3 の同期が Dropbox の /送り返し/ へ上げる。形はユーザーの PC の
src/human/friend/returns.py の parse_verdict と同じ)。届いてから 3 日決めなければ自動で reject(by auto = 学習で外れの印にしない)。
全部決めた行の案件フォルダ(切り抜き・作業用)はごみ箱へ(6 章)。ごみ箱(<一時保管>/ごみ箱/<日付>/)は 3 日で消す。
組(5-8): 届け方の n 本ごと(依頼の deliverBatch。初めは 5 = A-9)にまとめる。まとめ動画は玄関の engine が作ってから set_preview で入れる。

ファイルと時計は引数で受ける(テストは一時フォルダ)。標準ライブラリと ytt だけを読む。
"""
import datetime
import json
import os
import re
import shutil
import threading
import time
import uuid

from ytt import fsio

V = 1
DAY = 86400
KEEP_DAYS = 3                       # 物の終わりの日数(6 章の原則 = src/manage/keep/cleanup.py の 3 日)
STATES = ("sent", "making", "arrived", "failed", "done")
VERDICTS = ("keep", "reject")       # 「動画にした」はやめた(5-2)
VERDICT_SUFFIX = ".verdict.json"
TRASH_NAME = "ごみ箱"
ROW_ID_RE = re.compile(r"^[0-9A-Za-z_-]{1,64}$")   # 依頼 id(flow/deliver.request_id の形。送り返しの名前にも入る)
BAD_NAME = re.compile(r'[\\/:*?"<>|\x00-\x1f]')
NAME_MAX = 100                      # 送り返しの名前に入れるパック名の長さ(送るアプリの LocalPacks.PackNameMax と同じ)
PACK_SUFFIX = "_pack"


def pack_name(d):
    """パックのフォルダの名前(送り返しの名前に入れる形。使えない文字は _・長さは NAME_MAX まで)"""
    n = BAD_NAME.sub("_", os.path.basename(str(d or "").rstrip("\\/"))).strip()
    return n[:NAME_MAX].strip()


def pack_title(name):
    return name[:-len(PACK_SUFFIX)] if name.endswith(PACK_SUFFIX) and len(name) > len(PACK_SUFFIX) else name


def verdict_doc(verdict, request_id, name, title, at_ms, origin="request", by=None):
    d = {"v": 1, "verdict": verdict, "requestId": request_id, "zip": name, "title": title, "origin": origin, "at": int(at_ms)}
    if by == "auto":
        d["by"] = "auto"
    return d


def unique_dest(folder, name):
    """folder/name が既にあれば末尾に -xxxx を足した名前"""
    dest = os.path.join(folder, name)
    while os.path.exists(dest):
        dest = os.path.join(folder, "%s-%s" % (name, uuid.uuid4().hex[:4]))
    return dest


def case_of(result_path):
    """結果の束 <案件>/作業用/runs/<id>.json -> 案件のフォルダか None"""
    if not isinstance(result_path, str) or not result_path:
        return None
    runs = os.path.dirname(os.path.abspath(result_path))
    work = os.path.dirname(runs)
    if os.path.basename(runs) != "runs" or not work:
        return None
    return os.path.dirname(work)


class Inbox:
    """受信箱の記録の持ち主(玄関に 1 つ)。
    path = inbox.json・outbox = 送り返しのフォルダ・save_dir() = 受け取るの保存先・case_root() = 一時保管(ごみ箱はその下)"""

    def __init__(self, path, outbox, save_dir, case_root, clock=time.time, log=None):
        self.path, self.outbox = path, outbox
        self.save_dir, self.case_root = save_dir, case_root
        self.clock, self.log = clock, log or (lambda msg: None)
        self.lock = threading.RLock()
        self.rows = self._load()

    # ------------------------------------------------------------ 記録
    def _load(self):
        d = fsio.read_json_or(self.path, None, kind=dict)
        rows = d.get("rows") if isinstance(d, dict) and d.get("v") == V else None
        return [r for r in rows if isinstance(r, dict) and ROW_ID_RE.match(str(r.get("id") or "")) and r.get("state") in STATES] if isinstance(rows, list) else []

    def _save(self):
        fsio.write_json(self.path, {"v": V, "rows": self.rows}, indent=None)

    def _now_ms(self):
        return int(self.clock() * 1000)

    def row(self, rid):
        with self.lock:
            return next((r for r in self.rows if r["id"] == rid), None)

    def by_run(self, run_id):
        with self.lock:
            return next((r for r in self.rows if r.get("runId") == run_id), None)

    # ------------------------------------------------------------ 送る
    def add(self, rid, form, source, run_id=None):
        """送った行を足す(新しい物を先頭)。form = 送った欄(もう一度送るときに使う)・source = {url, videoId, title, channel}"""
        if not ROW_ID_RE.match(rid or ""):
            raise ValueError("依頼の id の形が違います")
        now = self._now_ms()
        r = {"id": rid, "kind": "url", "origin": "request", "state": "sent", "form": form, "source": source, "runId": run_id,
             "createdAt": now, "updatedAt": now, "packs": [], "groups": [], "error": "", "note": ""}
        with self.lock:
            self.rows.insert(0, r)
            self._save()
        return r

    def resent(self, rid, run_id):
        """失敗した行をもう一度送った(同じ行を「送った」に戻す)"""
        with self.lock:
            r = self.row(rid)
            if r is None:
                raise KeyError(rid)
            r.update(state="sent", runId=run_id, error="", note="", failedAt=None, updatedAt=self._now_ms())
            self._save()
            return r

    def making(self, run_id):
        """② が実行を始めた(画面の「作っている」)"""
        with self.lock:
            r = self.by_run(run_id)
            if r is not None and r["state"] == "sent":
                r["state"], r["updatedAt"] = "making", self._now_ms()
                self._save()

    def finished(self, run_id, state, error, packs, batch, case=None, note=""):
        """② の実行が終わった。packs = [{"dir", "seconds"}](作ったパック)・batch = 組の本数・case = 案件のフォルダ。
        パックがあれば「届いた」(組に分ける)・無ければ「失敗」(理由)。-> 行か None(玄関の依頼でない実行)"""
        with self.lock:
            r = self.by_run(run_id)
            if r is None:
                return None
            now = self._now_ms()
            r["case"] = case if isinstance(case, str) else r.get("case")
            items = []
            for p in packs:
                d = p.get("dir")
                if not isinstance(d, str) or not os.path.isdir(d):
                    continue
                name = pack_name(d)
                items.append({"name": name, "dir": d, "title": pack_title(name), "seconds": p.get("seconds"), "verdict": None, "at": None, "by": None})
            if items:
                n = batch if isinstance(batch, int) and 1 <= batch <= 10 else 5
                r["packs"] = items
                r["groups"] = [{"n": i // n + 1, "names": [x["name"] for x in items[i:i + n]], "preview": None}
                               for i in range(0, len(items), n)]
                r.update(state="arrived", arrivedAt=now, error="", note=note or "")
            else:
                r.update(state="failed", failedAt=now,
                         error=error or ("止めました" if state == "cancelled" else "切り抜く所が見つからず、パックができませんでした"))
            r["updatedAt"] = now
            self._save()
            return r

    def set_preview(self, rid, n, path):
        with self.lock:
            r = self.row(rid)
            g = next((g for g in (r or {}).get("groups") or [] if g["n"] == n), None)
            if g is not None:
                g["preview"] = path
                self._save()

    # ------------------------------------------------------------ 決める
    def decide(self, rid, names, verdict, by=None):
        """パック(names。空なら行の決めていない物全部)を keep / reject に決める -> {"done": [名前], "errors": [{"name", "message"}], "row"}。
        keep = 保存先へ移す・reject = ごみ箱へ。どちらも送り返しの .verdict.json を書く。移せなかった物は決めない(理由を返す = 一覧から外さない)"""
        if verdict not in VERDICTS:
            raise ValueError("決め方は keep か reject です")
        with self.lock:
            r = self.row(rid)
            if r is None or r["state"] != "arrived":
                raise KeyError(rid)
            want = set(names or [])
            done, errors = [], []
            for p in r["packs"]:
                if p["verdict"] or (want and p["name"] not in want):
                    continue
                try:
                    self._place(p, verdict)
                    self._write_verdict(r, p, verdict, by)
                except OSError as e:
                    errors.append({"name": p["name"], "message": self._move_failed(verdict, e)})
                    continue
                p.update(verdict=verdict, at=self._now_ms(), by=by)
                done.append(p["name"])
            if r["packs"] and all(p["verdict"] for p in r["packs"]):
                self._close_row(r)
            r["updatedAt"] = self._now_ms()
            self._save()
            return {"done": done, "errors": errors, "row": r}

    @staticmethod
    def _move_failed(verdict, e):
        what = "受け取るの保存先へ移せませんでした" if verdict == "keep" else "ごみ箱へ移せませんでした"
        return "%s(%s)。フォルダを開いているソフトを閉じてから、もう一度押してください" % (what, e.__class__.__name__)

    def _place(self, p, verdict):
        src = p["dir"]
        if not os.path.isdir(src):
            raise FileNotFoundError(src)
        if verdict == "keep":
            folder = self.save_dir()
            os.makedirs(folder, exist_ok=True)
            dest = unique_dest(folder, os.path.basename(src))
            shutil.move(src, dest)
            p["savedTo"] = dest
        else:
            self._to_trash(src)

    def _write_verdict(self, r, p, verdict, by):
        os.makedirs(self.outbox, exist_ok=True)
        path = os.path.join(self.outbox, "%s__%s%s" % (r["id"], p["name"], VERDICT_SUFFIX))
        fsio.write_json(path, verdict_doc(verdict, r["id"], p["name"], p["title"], self._now_ms(), r.get("origin") or "request", by), indent=None)

    def trash_dir(self):
        return os.path.join(self.case_root(), TRASH_NAME)

    def _to_trash(self, path):
        day = datetime.datetime.fromtimestamp(self.clock()).strftime("%Y%m%d")
        folder = os.path.join(self.trash_dir(), day)
        os.makedirs(folder, exist_ok=True)
        shutil.move(path, unique_dest(folder, os.path.basename(path.rstrip("\\/"))))

    def _close_row(self, r):
        """全部決めた行: まとめ動画を消し、案件フォルダ(一時保管の中だけ)をごみ箱へ・行は done(3 日で消える)"""
        for g in r.get("groups") or []:
            if g.get("preview"):
                fsio.unlink_quiet(g["preview"])
        self._trash_case(r)
        r["state"], r["doneAt"] = "done", self._now_ms()

    def _trash_case(self, r):
        case = r.get("case")
        root = self.case_root()
        if case and root and os.path.isdir(case) and fsio.is_inside(case, root, strict=True) and not fsio.is_inside(case, self.trash_dir()):
            try:
                self._to_trash(case)
            except OSError as e:
                self.log("案件フォルダをごみ箱へ移せませんでした: %s" % e.__class__.__name__)

    def remove(self, rid):
        """失敗の行を消す([消す])"""
        with self.lock:
            r = self.row(rid)
            if r is None or r["state"] != "failed":
                raise KeyError(rid)
            self._trash_case(r)
            self.rows.remove(r)
            self._save()

    # ------------------------------------------------------------ 3 日の片付け(5-6・5-7・6 章)
    def left_days(self, r):
        """自動で片付くまでの日数(届いた行・失敗の行)か None"""
        at = r.get("arrivedAt") if r["state"] == "arrived" else r.get("failedAt") if r["state"] == "failed" else None
        if not at:
            return None
        return max(0, KEEP_DAYS - int((self._now_ms() - at) // (DAY * 1000)))

    def sweep(self):
        """届いて 3 日決めていない物を自動で要らない・失敗と決めた行を 3 日で消す・ごみ箱の 3 日より前の日を消す -> 自動で要らないにした本数"""
        n = 0
        limit = KEEP_DAYS * DAY * 1000
        with self.lock:
            now = self._now_ms()
            for r in list(self.rows):
                if r["state"] == "arrived" and now - (r.get("arrivedAt") or now) >= limit:
                    n += len(self.decide(r["id"], [], "reject", by="auto")["done"])
                elif r["state"] == "failed" and now - (r.get("failedAt") or now) >= limit:
                    self.remove(r["id"])
                elif r["state"] == "done" and now - (r.get("doneAt") or now) >= limit:
                    self.rows.remove(r)
            self._save()
        self._purge_trash()
        return n

    def _purge_trash(self):
        t = self.trash_dir()
        if not os.path.isdir(t):
            return
        cut = datetime.datetime.fromtimestamp(self.clock() - KEEP_DAYS * DAY).strftime("%Y%m%d")
        for name in os.listdir(t):
            if re.fullmatch(r"\d{8}", name) and name < cut:
                shutil.rmtree(os.path.join(t, name), ignore_errors=True)

    # ------------------------------------------------------------ 画面へ
    def view(self, status_of=None):
        """画面に出す行(done は出さない)。status_of(run_id) = ② の実行の状態(作っている行の進み具合)か None"""
        with self.lock:
            out = []
            for r in self.rows:
                if r["state"] == "done":
                    continue
                v = json.loads(json.dumps(r))
                v["left"] = self.left_days(r)
                v["undecided"] = sum(1 for p in r["packs"] if not p["verdict"])
                for p in v["packs"]:
                    p.pop("dir", None)   # 画面に絶対パスを出さない(開くのは玄関の口から)
                if r["state"] in ("sent", "making") and status_of and r.get("runId"):
                    v["run"] = status_of(r["runId"])
                out.append(v)
            return out
