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

F2-3(Dropbox の同期 = friendapp/sync.py が呼ぶ):
- 処理する PC(A-2): 行の pc = "this"(この PC の ②)/ "user"(ユーザーの PC に頼んだ)/ "auto"(ユーザーの PC が自分の配信から自動で届けた = 依頼なし)。
  ユーザーの PC に頼んだ行は remote.state = pending(まだ上げていない)→ uploaded(Dropbox の直下に置いた・受付待ち)→ accepted(直下から消えた =
  受け付けられた。行は「作っている」)→ done(/出力/ から届いた)。LOCAL_AFTER 秒受付が読まなければ [この PC でやり直す](to_local)
- Dropbox のパック(/出力/ の zip。まだ手元に無い): パックの remote = {zip, size, rev, hash, meta}・dir は受け取るまで None。[受け取る] は want = keep に
  するだけ(同期が取って展開してから remote_kept で決める)・[要らない] は取らずに決める。組の remote = {group, preview, previewSize, cleaned}。
  組の全部を決めたら同期が/出力/ の zip・まとめ動画・.group.json・.meta.json を消す(cleanup_queue → remote_cleaned)。名前は全部 Dropbox の名前(パスにしない)

F2-6(送る欄を広げる): 行の kind = "url" / "file"(動画ファイル。form.file = {path, name, size, copy}。path・copy は画面に出さない)/ "live"(ライブ)。
- この PC のライブの行: 送った → recording(録画中。live = {recorder, recording, endedAt, finished, phase, done, errors, lastError})→ 届いた / 失敗 → 決めた。
  切り抜きごとの実行(封筒の requestId = 行の id)が終わるたびに live_clip でパックを足し、届け方の n 本ごとに組にする(録画が終わって作る物が無くなったら残りを
  1 組に = live_update。配信後の追加(M7)の分は別の組「配信後」)。録画中でも組になった物は決められる(組になる前の物は出さない・決めない)
- 動画ファイルのこの PC の行: 送った(写している = runId なし)→ set_run(② に積んだ)→ URL の行と同じ

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
STATES = ("sent", "making", "recording", "arrived", "failed", "done")   # recording = この PC のライブの行(録画中・残りを作っている。F2-6)
KINDS = ("url", "file", "live")     # 送った物(F2-6)。自動で届いた行は "remote"
PHASES = ("live", "archive")        # ライブの切り抜きの段(配信中 / 配信後の追加 M7)。組は段ごと
LIVE_STALE = KEEP_DAYS * DAY + 12 * 3600   # 録画の行がこれより長く終わらない(録画元が見つからないなど)= 残りを組にして閉じる
LIVE_DONE_MAX = 500                 # ライブの行が覚える済んだ切り抜きの実行の id の数
VERDICTS = ("keep", "reject")       # 「動画にした」はやめた(5-2)
VERDICT_SUFFIX = ".verdict.json"
TRASH_NAME = "ごみ箱"
ROW_ID_RE = re.compile(r"^[0-9A-Za-z_-]{1,64}$")   # 依頼 id(flow/deliver.request_id の形。送り返しの名前にも入る)
BAD_NAME = re.compile(r'[\\/:*?"<>|\x00-\x1f]')
NAME_MAX = 100                      # 送り返しの名前に入れるパック名の長さ(送るアプリの LocalPacks.PackNameMax と同じ)
PACK_SUFFIX = "_pack"
PCS = ("this", "user")              # 処理する PC(A-2)。行の pc にはほかに "auto"(依頼なし)
LOCAL_AFTER = 3600                  # ユーザーの PC の受付がこの秒数読まなければ [この PC でやり直す](A-2 の仮 = 1 時間)
REMOTE_FAILS_MAX = 20


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
    def add(self, rid, form, source, run_id=None, pc="this", kind="url"):
        """送った行を足す(新しい物を先頭)。form = 送った欄(もう一度送るときに使う)・source = {url, videoId, title, channel}。
        pc = "user" なら ユーザーの PC に頼む行(同期が Dropbox の直下へ上げる)。kind = url / file / live(F2-6)"""
        if not ROW_ID_RE.match(rid or ""):
            raise ValueError("依頼の id の形が違います")
        now = self._now_ms()
        r = {"id": rid, "kind": kind if kind in KINDS else "url", "origin": "request", "state": "sent", "form": form, "source": source, "runId": run_id,
             "createdAt": now, "updatedAt": now, "packs": [], "groups": [], "error": "", "note": "", "pc": "user" if pc == "user" else "this"}
        if r["pc"] == "user":
            r["remote"] = {"state": "pending", "uploadedAt": None}
        with self.lock:
            self.rows.insert(0, r)
            self._save()
        return r

    def drop(self, rid):
        """送れなかった行を消す(② が断った・録画を始められなかった)"""
        with self.lock:
            r = self.row(rid)
            if r is not None:
                self.rows.remove(r)
                self._save()

    def set_run(self, rid, run_id, copy=None):
        """動画ファイルの行: 写し終えて ② に積む(積む前に呼ぶ = 実行が終わったときに行が見つかる)。copy = 一時保管の写しのパス"""
        with self.lock:
            r = self.row(rid)
            if r is None:
                raise KeyError(rid)
            r.update(runId=run_id, updatedAt=self._now_ms())
            if copy and isinstance((r.get("form") or {}).get("file"), dict):
                r["form"]["file"]["copy"] = copy
            self._save()
            return r

    def fail(self, rid, text):
        """送った・作っている行を失敗にする(写せなかった・Dropbox へ上げる動画が無い など。理由は画面にそのまま)"""
        with self.lock:
            r = self.row(rid)
            if r is None or r["state"] not in ("sent", "making", "recording"):
                return None
            now = self._now_ms()
            r.update(state="failed", failedAt=now, error=str(text or "失敗しました")[:500], updatedAt=now)
            self._save()
            return r

    # ------------------------------------------------------------ この PC のライブの行(F2-6。engine が呼ぶ)
    def live_started(self, rid, recorder, recording, existing=False):
        """録画を始めた(依頼に結びつけた)-> 行は「録画中」"""
        with self.lock:
            r = self.row(rid)
            if r is None:
                raise KeyError(rid)
            now = self._now_ms()
            r.update(state="recording", runId=None, error="", updatedAt=now, failedAt=None)
            r["live"] = {"recorder": recorder, "recording": recording, "existing": bool(existing), "startedAt": now, "endedAt": None,
                         "finished": None, "phase": "recording", "done": [], "errors": 0, "lastError": ""}
            self._save()
            return r

    def live_rows(self):
        """見回る行(この PC のライブの行で、まだ閉じていない物か組になる前のパックがある物)の写し"""
        with self.lock:
            out = []
            for r in self.rows:
                lv = r.get("live")
                if r.get("kind") != "live" or r.get("pc") == "user" or not isinstance(lv, dict) or r["state"] == "failed":
                    continue
                if r["state"] == "recording" or self._ungrouped(r):
                    out.append(json.loads(json.dumps(r)))
            return out

    @staticmethod
    def _ungrouped(r):
        grouped = {n for g in r.get("groups") or [] for n in g["names"]}
        return [p for p in r["packs"] if p["name"] not in grouped]

    def _live_group(self, r, force):
        """組になる前のパックを届け方の n 本ごとに組へ(段ごと)。force = 残りも 1 組に -> 足した組の n のリスト"""
        batch = (r.get("form") or {}).get("deliverBatch")
        n = batch if isinstance(batch, int) and not isinstance(batch, bool) and 1 <= batch <= 10 else 5
        pend = self._ungrouped(r)
        made = []
        last = max([g["n"] for g in r.get("groups") or []] + [0])
        for phase in PHASES:
            ps = [p for p in pend if (p.get("phase") or "live") == phase]
            while len(ps) >= n or (force and ps):
                take, ps = ps[:n], ps[n:]
                last += 1
                r["groups"].append({"n": last, "names": [p["name"] for p in take], "preview": None, "label": "配信後" if phase == "archive" else ""})
                made.append(last)
        return made

    def live_clip(self, rid, run_id, state, error, packs, phase="live", case=None):
        """ライブの切り抜き 1 本の実行が終わった(封筒の requestId = 行の id)。packs = [{"dir", "seconds"}]。
        -> (行の写し, 足した組の n のリスト) か (None, [])(ライブの行でない・同じ実行をもう入れた)"""
        with self.lock:
            r = self.row(rid)
            lv = (r or {}).get("live")
            if r is None or r.get("kind") != "live" or not isinstance(lv, dict) or run_id in (lv.get("done") or []):
                return None, []
            now = self._now_ms()
            lv["done"] = ((lv.get("done") or []) + [run_id])[-LIVE_DONE_MAX:]
            if isinstance(case, str) and case and case not in (r.get("cases") or []):
                r["cases"] = (r.get("cases") or []) + [case]
            names = {p["name"] for p in r["packs"]}
            added = 0
            for p in packs:
                d = p.get("dir")
                if not isinstance(d, str) or not os.path.isdir(d):
                    continue
                base = pack_name(d)
                name, i = base, 2
                while name in names:
                    name, i = "%s-%d" % (base[:NAME_MAX - 4], i), i + 1
                names.add(name)
                r["packs"].append({"name": name, "dir": d, "title": pack_title(base), "seconds": p.get("seconds"), "verdict": None, "at": None, "by": None,
                                   "phase": phase if phase in PHASES else "live"})
                added += 1
            if not added and state in ("error", "cancelled"):
                lv["errors"] = int(lv.get("errors") or 0) + 1
                lv["lastError"] = str(error or "止めました")[:300]
            made = self._live_group(r, False)
            if added and r["state"] in ("arrived", "done"):   # 閉じたあとに届いた(配信後の追加の遅れ)= もう一度「届いた」
                r.update(state="arrived", arrivedAt=now, doneAt=None)
            r["updatedAt"] = now
            self._save()
            return json.loads(json.dumps(r)), made

    def live_update(self, rid, recording, busy, waiting=""):
        """見回り: recording = 録画中か・busy = 書き出し・作っている切り抜きがあるか・waiting = 配信後の追加を待つ理由("" = 待たない)。
        録画が終わって作る物が無ければ残りを組に・配信後の追加も待たなければ行を閉じる(パックがあれば「届いた」・全部決めていれば「決めた」・無ければ「失敗」)。
        -> 足した組の n のリスト"""
        with self.lock:
            r = self.row(rid)
            lv = (r or {}).get("live")
            if r is None or not isinstance(lv, dict):
                return []
            now = self._now_ms()
            before = json.dumps([r["state"], lv, r.get("groups")])
            if not recording and not lv.get("endedAt"):
                lv["endedAt"] = now
            made = self._live_group(r, True) if not recording and not busy else []
            lv["phase"] = "recording" if recording else "making" if busy else "after" if waiting else "done"
            if not recording and not busy and not waiting and not lv.get("finished"):
                lv["finished"] = now
                if r["state"] == "recording":
                    self._live_close(r, now)
            if json.dumps([r["state"], lv, r.get("groups")]) != before:
                r["updatedAt"] = now
                self._save()
            return made

    def _live_close(self, r, now):
        lv = r["live"]
        if not r["packs"]:
            r.update(state="failed", failedAt=now, error=lv.get("lastError") or "録画から切り抜く所が見つからず、パックができませんでした")
        elif all(p["verdict"] for p in r["packs"]):
            self._close_row(r)
        else:
            r.update(state="arrived", arrivedAt=now)

    def resent(self, rid, run_id):
        """失敗した行をもう一度送った(同じ行を「送った」に戻す。ユーザーの PC の行は依頼を上げ直す)"""
        with self.lock:
            r = self.row(rid)
            if r is None:
                raise KeyError(rid)
            r.update(state="sent", runId=run_id, error="", note="", failedAt=None, updatedAt=self._now_ms())
            if r.get("pc") == "user":
                r["remote"] = {"state": "pending", "uploadedAt": None}
            self._save()
            return r

    # ------------------------------------------------------------ ユーザーの PC に頼んだ行(A-2。同期が呼ぶ)
    def remote_rows(self, state):
        """ユーザーの PC に頼んだ行のうち remote.state が state の物(写し)"""
        with self.lock:
            return [json.loads(json.dumps(r)) for r in self.rows
                    if r.get("pc") == "user" and r["state"] in ("sent", "making") and (r.get("remote") or {}).get("state") == state]

    def remote_mark(self, rid, state):
        """uploaded(直下に置いた)・accepted(直下から消えた = 受け付けられた。行は「作っている」)"""
        with self.lock:
            r = self.row(rid)
            if r is None or r.get("pc") != "user" or r["state"] not in ("sent", "making"):
                return None
            now = self._now_ms()
            rem = r.setdefault("remote", {})
            rem["state"] = state
            if state == "uploaded":
                rem["uploadedAt"] = now
            elif state == "accepted":
                rem["acceptedAt"] = now
                r["state"] = "making"
            r["updatedAt"] = now
            self._save()
            return r

    def waited(self, r):
        """ユーザーの PC の受付を待っている秒数(上げる前は送った時刻から)か None(待っていない)"""
        rem = r.get("remote") or {}
        if r.get("pc") != "user" or r["state"] != "sent" or rem.get("state") not in ("pending", "uploaded"):
            return None
        return max(0, (self._now_ms() - (rem.get("uploadedAt") or r["createdAt"])) // 1000)

    def to_local(self, rid, run_id):
        """[この PC でやり直す]: ユーザーの PC に頼んだ行を、この PC の ② の行に変える(同期が直下の依頼を消したあと)"""
        with self.lock:
            r = self.row(rid)
            if r is None:
                raise KeyError(rid)
            r.update(pc="this", remote=None, runId=run_id, state="sent", error="", updatedAt=self._now_ms())
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
                if path is None and g.get("remote"):
                    g["remote"]["preview"] = None   # Dropbox にまとめ動画が無かった = もう取りに行かない
                self._save()

    # ------------------------------------------------------------ Dropbox の /出力/ から届いた物(同期が呼ぶ)
    def known_remote(self):
        """行に入れた Dropbox の名前(zip・組の一覧・まとめ動画・印・失敗の知らせ)の集まり(同じ物を 2 回取り込まない)"""
        out = set()
        with self.lock:
            for r in self.rows:
                for p in r["packs"]:
                    rem = p.get("remote") or {}
                    out.update(x for x in (rem.get("zip"), rem.get("meta")) if x)
                for g in r.get("groups") or []:
                    rem = g.get("remote") or {}
                    out.update(x for x in (rem.get("group"), rem.get("previewName")) if x)
                out.update(r.get("remoteFails") or [])
        return out

    def _remote_row(self, rid, origin, title, now):
        r = {"id": rid, "kind": "remote", "origin": "auto" if origin == "auto" else "request", "state": "arrived", "form": None,
             "source": {"url": "", "videoId": "", "title": title, "channel": ""}, "runId": None, "createdAt": now, "updatedAt": now,
             "packs": [], "groups": [], "error": "", "note": "", "pc": "auto" if origin == "auto" else "user"}
        self.rows.insert(0, r)
        return r

    def import_remote(self, rid, origin, title, specs):
        """/出力/ の組・1 本を行に入れる(依頼 id の行があればその行・無ければ新しい行 = origin auto なら札「依頼なし」)。
        specs = [{"group": 名前か None, "preview": 名前か None, "previewSize", "packs": [{"zip", "title", "seconds", "size", "rev", "hash", "meta"}]}]"""
        if not ROW_ID_RE.match(rid or ""):
            raise ValueError("依頼の id の形が違います")
        with self.lock:
            now = self._now_ms()
            r = self.row(rid) or self._remote_row(rid, origin, title, now)
            names = {p["name"] for p in r["packs"]}
            n = max([g["n"] for g in r.get("groups") or []] + [0])
            for spec in specs:
                got = []
                for it in spec["packs"]:
                    base = pack_name(str(it.get("title") or "pack") + PACK_SUFFIX) or "pack"
                    name, i = base, 2
                    while name in names:
                        name, i = "%s-%d" % (base[:NAME_MAX - 4], i), i + 1
                    names.add(name)
                    r["packs"].append({"name": name, "dir": None, "title": str(it.get("title") or pack_title(name)), "seconds": it.get("seconds"),
                                       "verdict": None, "at": None, "by": None, "want": None, "error": "",
                                       "remote": {k: it.get(k) for k in ("zip", "size", "rev", "hash", "meta")}})
                    got.append(name)
                if got:
                    n += 1
                    r["groups"].append({"n": n, "names": got, "preview": None,
                                        "remote": {"group": spec.get("group"), "previewName": spec.get("preview"), "preview": spec.get("preview"),
                                                   "previewSize": spec.get("previewSize"), "cleaned": False}})
            r.update(state="arrived", arrivedAt=now, error="", updatedAt=now)   # 新しく届いた物にも 3 日(仮 = 行の残りも延びる)
            if r.get("remote"):
                r["remote"]["state"] = "done"
            self._save()
            return r

    def remote_failure(self, rid, title, text, fail_name):
        """/出力/ の .失敗.txt(ユーザーの PC で失敗した)。依頼の行は「失敗」に・無ければ失敗の行を足す・届いた行には知らせだけ"""
        if not ROW_ID_RE.match(rid or ""):
            raise ValueError("依頼の id の形が違います")
        with self.lock:
            now = self._now_ms()
            r = self.row(rid)
            if r is None:
                r = self._remote_row(rid, "request", title, now)
                r.update(state="failed", failedAt=now, error=text)
            elif r["state"] in ("sent", "making", "failed"):
                r.update(state="failed", failedAt=now, error=text)
            elif r["state"] == "arrived":
                r["note"] = text[:500]
            r["remoteFails"] = ((r.get("remoteFails") or []) + [fail_name])[-REMOTE_FAILS_MAX:]
            r["updatedAt"] = now
            self._save()
            return r

    def remote_fail_cleared(self, rid, fail_name):
        """失敗の知らせを Dropbox から消した(覚えておく必要が無くなった)"""
        with self.lock:
            r = self.row(rid)
            if r is not None and fail_name in (r.get("remoteFails") or []):
                r["remoteFails"].remove(fail_name)
                self._save()

    def preview_queue(self):
        """取ってくるまとめ動画 -> [(依頼 id, 組の n, Dropbox の名前, 大きさ)]"""
        with self.lock:
            return [(r["id"], g["n"], g["remote"]["preview"], g["remote"].get("previewSize")) for r in self.rows if r["state"] == "arrived"
                    for g in r.get("groups") or [] if g.get("remote") and g["remote"].get("preview") and not g.get("preview")
                    and not g["remote"].get("cleaned")]

    def receive_queue(self):
        """[受け取る] を押した Dropbox のパック -> [(依頼 id, パック名, remote の写し)]"""
        with self.lock:
            return [(r["id"], p["name"], dict(p["remote"])) for r in self.rows if r["state"] == "arrived"
                    for p in r["packs"] if p.get("remote") and p.get("want") == "keep" and not p["verdict"]]

    def _pack(self, rid, name):
        r = self.row(rid)
        return r, next((p for p in (r or {}).get("packs") or [] if p["name"] == name), None)

    def remote_kept(self, rid, name, saved_to):
        """Dropbox のパックを取って保存先へ展開し終えた -> 受け取ったに決める(送り返しの .verdict.json)"""
        with self.lock:
            r, p = self._pack(rid, name)
            if p is None or p["verdict"]:
                return None
            p.update(savedTo=saved_to, want=None, error="")
            try:
                self._write_verdict(r, p, "keep", None)
            except OSError as e:
                self.log("採否を書けませんでした: %s" % e.__class__.__name__)
            p.update(verdict="keep", at=self._now_ms(), by=None)
            if all(x["verdict"] for x in r["packs"]):
                self._close_row(r)
            r["updatedAt"] = self._now_ms()
            self._save()
            return r

    def remote_keep_failed(self, rid, name, message):
        with self.lock:
            r, p = self._pack(rid, name)
            if p is not None and not p["verdict"]:
                p.update(want=None, error=message)
                r["updatedAt"] = self._now_ms()
                self._save()

    def cleanup_queue(self):
        """全部決めた Dropbox の組 -> [(依頼 id, 組の n, [/出力/ の名前])](zip・印・まとめ動画・組の一覧。消すのは同期)"""
        out = []
        with self.lock:
            for r in self.rows:
                by = {p["name"]: p for p in r["packs"]}
                for g in r.get("groups") or []:
                    rem = g.get("remote")
                    if not rem or rem.get("cleaned"):
                        continue
                    ps = [by[n] for n in g["names"] if n in by]
                    if ps and all(p["verdict"] for p in ps):
                        names = [x for p in ps for x in ((p.get("remote") or {}).get("zip"), (p.get("remote") or {}).get("meta")) if x]
                        out.append((r["id"], g["n"], names + [x for x in (rem.get("previewName"), rem.get("group")) if x]))
        return out

    def remote_cleaned(self, rid, n):
        with self.lock:
            r = self.row(rid)
            g = next((g for g in (r or {}).get("groups") or [] if g["n"] == n), None)
            if g is not None and g.get("remote"):
                g["remote"]["cleaned"] = True
                self._save()

    def _remote_left(self, r):
        return any(g.get("remote") and not g["remote"].get("cleaned") for g in r.get("groups") or [])

    # ------------------------------------------------------------ 決める
    def decide(self, rid, names, verdict, by=None):
        """パック(names。空なら行の決めていない物全部)を keep / reject に決める -> {"done": [名前], "pending": [名前], "errors": [{"name", "message"}], "row"}。
        keep = 保存先へ移す・reject = ごみ箱へ。どちらも送り返しの .verdict.json を書く。移せなかった物は決めない(理由を返す = 一覧から外さない)。
        Dropbox のパック(まだ手元に無い): keep は「受け取っています」にするだけ(pending。同期が取って展開してから決める)・reject は取らずに決める。
        3 日の自動(by auto)は、受け取っている途中の物を要らないにしない"""
        if verdict not in VERDICTS:
            raise ValueError("決め方は keep か reject です")
        with self.lock:
            r = self.row(rid)
            if r is None or r["state"] not in ("arrived", "recording"):   # 録画中のライブの行も、組になった物は決められる(F2-6)
                raise KeyError(rid)
            want = set(names or [])
            done, pending, errors = [], [], []
            hidden = {p["name"] for p in self._ungrouped(r)}   # 組になる前のパック(画面に出していない)は決めない
            for p in r["packs"]:
                if p["verdict"] or p["name"] in hidden or (want and p["name"] not in want) or (by == "auto" and p.get("want") == "keep"):
                    continue
                remote = bool(p.get("remote")) and not p.get("dir")
                if remote and verdict == "keep":
                    p.update(want="keep", error="")
                    pending.append(p["name"])
                    continue
                try:
                    if not remote:
                        self._place(p, verdict)
                    self._write_verdict(r, p, verdict, by)
                except OSError as e:
                    errors.append({"name": p["name"], "message": self._move_failed(verdict, e)})
                    continue
                p.update(verdict=verdict, at=self._now_ms(), by=by, want=None)
                done.append(p["name"])
            if r["state"] == "arrived" and r["packs"] and all(p["verdict"] for p in r["packs"]):   # 録画中の行は録画が終わってから閉じる
                self._close_row(r)
            r["updatedAt"] = self._now_ms()
            self._save()
            return {"done": done, "pending": pending, "errors": errors, "row": r}

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
        zip_name = (p.get("remote") or {}).get("zip") or p["name"]   # Dropbox のパックは出力の zip の名前
        fsio.write_json(path, verdict_doc(verdict, r["id"], zip_name, p["title"], self._now_ms(), r.get("origin") or "request", by), indent=None)

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
        root = self.case_root()
        for case in dict.fromkeys([r.get("case")] + list(r.get("cases") or [])):   # ライブの行は切り抜きごとの案件(F2-6)
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
                if r["state"] == "recording" and now - ((r.get("live") or {}).get("endedAt") or r["createdAt"]) >= LIVE_STALE * 1000:
                    self._live_group(r, True)   # 録画元が見つからないまま終わらない行(F2-6)= 残りを組にして閉じる
                    r.setdefault("live", {})["finished"] = now
                    self._live_close(r, now)
                elif r["state"] == "arrived" and now - (r.get("arrivedAt") or now) >= limit:
                    n += len(self.decide(r["id"], [], "reject", by="auto")["done"])
                elif r["state"] == "failed" and now - (r.get("failedAt") or now) >= limit:
                    self.remove(r["id"])
                elif r["state"] == "done" and now - (r.get("doneAt") or now) >= limit and not self._remote_left(r):
                    self.rows.remove(r)   # Dropbox にまだ消せていない物がある行は残す(消し終えるまで同じ物を取り込み直さない)
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
                hidden = {p["name"] for p in self._ungrouped(r)}
                v["undecided"] = sum(1 for p in r["packs"] if not p["verdict"] and p["name"] not in hidden)
                v["waitingPacks"] = len(hidden)   # 組になる前のパック(ライブ。画面に「あと m 本で 1 組」)
                f = v.get("form") or {}
                if isinstance(f.get("file"), dict):   # 動画ファイルのパスは画面に出さない(名前と大きさだけ)
                    f["file"] = {k: f["file"].get(k) for k in ("name", "size")}
                lv = v.pop("live", None)
                if isinstance(lv, dict):
                    v["live"] = {"phase": lv.get("phase") or "recording", "ended": bool(lv.get("endedAt")), "errors": lv.get("errors") or 0}
                v.pop("cases", None)
                for p in v["packs"]:
                    p.pop("dir", None)   # 画面に絶対パスを出さない(開くのは玄関の口から)
                    p.pop("savedTo", None)
                    p["remote"] = bool(p.get("remote"))
                for g in v.get("groups") or []:
                    g["remote"] = bool(g.get("remote"))
                    g["preview"] = bool(g.get("preview"))
                v.pop("remoteFails", None)
                v.setdefault("pc", "this")
                w = self.waited(r)
                if w is not None:
                    v["waitHours"], v["canLocal"] = int(w // 3600), w >= LOCAL_AFTER
                if r["state"] in ("sent", "making") and status_of and r.get("runId"):
                    v["run"] = status_of(r["runId"])
                out.append(v)
            return out
