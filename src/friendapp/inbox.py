# -*- coding: utf-8 -*-
"""友人の受信箱の正(notes:plan/f1-friend-requirements.md の C-3、notes:docs/design/friend-history.md の 7 章)。

受信箱の記録は 1 つの JSON(<作業データ>/app/friendapp/inbox.json)だけ。画面は毎回ここを読む(Dropbox の一覧・② の記録から組み立て直さない)。
1 行 = 1 依頼 = 1 配信(A-4)。行の状態:
    sent     送った(② の待ち)
    making   作っている(② が実行中。進み具合は記録に写さず、画面に出すときに ② の状態を重ねる)
    arrived  届いた(パックがある。まだ決めていない物が残る)
    failed   失敗(理由・[もう一度送る]・[消す]。3 日で自動で片付く = 5-7)
    done     決めた(全部のパックを決めた = 画面に出さない。3 日で記録から消す)
パックの決め方(decide): keep = [受け取る](受け取るの保存先へ移す)/ skip = [見送る](アプリのごみ箱へ。3 日は戻せる)/
bad = 届かなくてよかった(理由つき)。どれも送り返しの <outbox>/<依頼 id>__<パック名>~<at>.verdict.json(判断の記録 v 2)を書く
(同期が Dropbox の /送り返し/ へ上げる。形はユーザーの PC の src/human/friend/returns.py が読む)。届いてから 3 日決めなければ自動で見送る
(by auto = 学習で外れの印にしない)。全部決めた行の案件フォルダ(切り抜き・作業用)はごみ箱へ(6 章)。ごみ箱(<一時保管>/ごみ箱/<日付>/)は 3 日で消す。
パックは 1 本ずつ届き、1 本ずつ決める(C-3-1)。行の groups は 1 本ずつの枠 {n, names: [パック名], preview}(確認用の動画は玄関の engine が
作ってから set_preview で入れる。Dropbox から来た物は remote = {previewName, preview, previewSize, cleaned})。

Dropbox の同期(friendapp/sync.py が呼ぶ):
- 処理する PC(A-2): 行の pc = "this"(この PC の ②)/ "user"(ユーザーの PC に頼んだ)/ "auto"(ユーザーの PC が自分の配信から自動で届けた = 依頼なし)。
  ユーザーの PC に頼んだ行は remote.state = pending(まだ上げていない)→ uploaded(Dropbox の直下に置いた・受付待ち)→ accepted(直下から消えた =
  受け付けられた。行は「作っている」)→ done(/出力/ から届いた)。LOCAL_AFTER 秒受付が読まなければ [この PC でやり直す](to_local)
- Dropbox のパック(/出力/ の zip。まだ手元に無い): パックの remote = {zip, size, rev, hash, meta}・dir は受け取るまで None。[受け取る] は want = keep に
  するだけ(同期が取って展開してから remote_kept で決める)・[見送る] は取らずに決める。
  決めたら同期が /出力/ の zip・確認用の動画・.meta.json を消す(cleanup_queue → remote_cleaned)。名前は全部 Dropbox の名前(パスにしない)

送る物: 行の kind = "url" / "file"(動画ファイル。form.file = {path, name, size, copy}。path・copy は画面に出さない)/ "live"(ライブ)。
- この PC のライブの行: 送った → recording(録画中。live = {recorder, recording, endedAt, finished, phase, done, errors, lastError, cause})→ 届いた / 失敗 → 決めた。
  失敗(パックが無いまま閉じた)の理由は engine.live_cause が原因ごとに分けて渡す(cause = その種類)。閉じたあとにパックが届けば失敗の行も「届いた」に戻す。
  切り抜きごとの実行(封筒の requestId = 行の id)が終わるたびに live_clip でパックを足し、1 本ずつの枠に入れる(録画が終わって作る物が無くなったら残りも
  = live_update。配信後の追加(M7)の分は札「配信後」)。録画中でも枠に入った物は決められる(入る前の物は出さない・決めない)
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

from flow import retention   # 物の終わりの日数
from ytt import fsio, trashbin

from . import progress as _progress

V = 1
DAY = 86400
KEEP_DAYS = retention.KEEP_DAYS      # 物の終わりの日数(6 章の原則。ユーザーのツールと同じ flow/retention の 1 か所)
STATES = ("waiting", "sent", "making", "recording", "arrived", "failed", "done")   # recording = この PC のライブの行(録画中・残りを作っている)・waiting = アーカイブ待ち(F3-3)
KINDS = ("url", "file", "live")     # 送った物。自動で届いた行は "remote"
PHASES = ("live", "archive")        # ライブの切り抜きの段(配信中 / 配信後の追加 M7)。組は段ごと
LIVE_STALE = KEEP_DAYS * DAY + 12 * 3600   # 録画の行がこれより長く終わらない(録画元が見つからないなど)= 残りを組にして閉じる
LIVE_DONE_MAX = 500                 # ライブの行が覚える済んだ切り抜きの実行の id の数
VERDICTS = ("keep", "skip", "bad")  # 受け取る / 見送る / 届かなくてよかった(C-3-4)
JUDGE = {"keep": "good", "skip": "unknown", "bad": "bad"}   # 送り返しの判断の記録 v 2 の言葉(notes:docs/spec/friend.md の 12-2)
REASONS = ("boring", "cut")         # 届かなくてよかったの理由: つまらない(場面の選び方)/ 切り方が変(区間の決め方)
CLIP_RANGE_RE = re.compile(r"(\d{2,})h(\d{2})m(\d{2})s-(\d{2,})h(\d{2})m(\d{2})s")   # 書き出しの名前の <始まり>-<終わり>(ytt/names)
TITLE_CUT = 40                      # 保存先のフォルダの名前に入れる配信の題の長さ(C-3-8)
VERDICT_SUFFIX = ".verdict.json"
TRASH_NAME = trashbin.TRASH_DIR
TRASH_KIND = "受信箱"   # ごみ箱の日付のフォルダの中の種類(受け取らなかった物・片付けた案件のフォルダ)
ROW_ID_RE = re.compile(r"^[0-9A-Za-z_-]{1,64}$")   # 依頼 id(flow/deliver.request_id の形。送り返しの名前にも入る)
BAD_NAME = re.compile(r'[\\/:*?"<>|\x00-\x1f]')
NAME_MAX = 100                      # 送り返しの名前に入れるパック名の長さ
PACK_SUFFIX = "_pack"
PCS = ("this", "user")              # 処理する PC(A-2)。行の pc にはほかに "auto"(依頼なし)
LOCAL_AFTER = 3600                  # ユーザーの PC の受付がこの秒数読まなければ [この PC でやり直す](A-2 の仮 = 1 時間)
REMOTE_FAILS_MAX = 20
RETRY_MAX = 3                       # 直る見込みのある失敗の自動のやり直しの回数(C-2-16。api が数える)
STATS_KEEP = 5                      # 段ごとにかかった秒を覚える数(残り時間の見積もり = progress.eta)


def pack_name(d):
    """パックのフォルダの名前(送り返しの名前に入れる形。使えない文字は _・長さは NAME_MAX まで)"""
    n = BAD_NAME.sub("_", os.path.basename(str(d or "").rstrip("\\/"))).strip()
    return n[:NAME_MAX].strip()


def pack_title(name):
    return name[:-len(PACK_SUFFIX)] if name.endswith(PACK_SUFFIX) and len(name) > len(PACK_SUFFIX) else name


def unique_dest(folder, name):
    """folder/name が既にあれば末尾に -xxxx を足した名前"""
    dest = os.path.join(folder, name)
    while os.path.exists(fsio.long_path(dest)):
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
        self.stats = {}                 # 段ごとにかかった秒 {段の名前: [秒, …]}(F3-3。新しい順・STATS_KEEP まで)
        self.nums = {}                  # 配信ごとの通し番号の最後 {配信の鍵: n}(C-3-2。見送って消えた番号も使い回さない)
        self.notice = None              # 3 日の自動の片付けの知らせ {n, at}(画面に 1 行。見たら消す)
        self.stream_info = lambda vid: None   # 配信の一覧の 1 件(題・配信者・始まった時刻。玄関が streams.lookup を入れる)
        self.on_fail = None             # fail で行を失敗にしたとき on_fail(行の写し)(② の前の失敗の診断。玄関が friendapp/diag を入れる)
        self.rows = self._load()

    # ------------------------------------------------------------ 記録
    def _load(self):
        d = fsio.read_json_or(self.path, None, kind=dict)
        rows = d.get("rows") if isinstance(d, dict) and d.get("v") == V else None
        st = d.get("stats") if isinstance(d, dict) else None
        if isinstance(st, dict):
            self.stats = {k: [x for x in v if isinstance(x, (int, float)) and x >= 0][:STATS_KEEP] for k, v in st.items() if isinstance(k, str) and isinstance(v, list)}
        nums = d.get("nums") if isinstance(d, dict) else None
        if isinstance(nums, dict):
            self.nums = {k: v for k, v in nums.items() if isinstance(k, str) and isinstance(v, int) and not isinstance(v, bool) and v >= 0}
        if isinstance(d, dict) and isinstance(d.get("notice"), dict):
            self.notice = d["notice"]
        out = [r for r in rows if isinstance(r, dict) and ROW_ID_RE.match(str(r.get("id") or "")) and r.get("state") in STATES] if isinstance(rows, list) else []
        for r in out:   # 番号の無いパックに番号
            for p in r.get("packs") or []:
                if not p.get("num"):
                    self._number(r, p)
        return out

    def _save(self):
        fsio.write_json(self.path, {"v": V, "rows": self.rows, "stats": self.stats, "nums": self.nums, "notice": self.notice}, indent=None)

    def _number(self, r, p):
        """届いたパックに配信ごとの通し番号を振る(C-3-2。2 回目の依頼は続きから)と届いた時刻(3 日を数える)"""
        key = _stream_key(r, p)
        n = self.nums.get(key, 0) + 1
        self.nums[key] = n
        p.update(num=n, key=key)
        p.setdefault("arrivedAt", r.get("arrivedAt") or self._now_ms())

    # ------------------------------------------------------------ 段ごとの秒(残り時間の見積もり。F3-3)
    def record_stage(self, label, seconds):
        if not isinstance(label, str) or not label or not isinstance(seconds, (int, float)) or seconds < 0:
            return
        with self.lock:
            self.stats = dict(self.stats)
            self.stats[label] = ([round(float(seconds), 1)] + list(self.stats.get(label) or []))[:STATS_KEEP]
            self._save()

    def stage_stats(self):
        with self.lock:
            return json.loads(json.dumps(self.stats))

    def _now_ms(self):
        return int(self.clock() * 1000)

    def row(self, rid):
        with self.lock:
            return next((r for r in self.rows if r["id"] == rid), None)

    def by_run(self, run_id):
        with self.lock:
            return next((r for r in self.rows if r.get("runId") == run_id), None)

    # ------------------------------------------------------------ 送る
    def add(self, rid, form, source, run_id=None, pc="this", kind="url", state="sent"):
        """送った行を足す(新しい物を先頭)。form = 送った欄(もう一度送るときに使う)・source = {url, videoId, title, channel}。
        pc = "user" なら ユーザーの PC に頼む行(同期が Dropbox の直下へ上げる)。kind = url / file / live。
        state = "waiting" ならアーカイブ待ち(F3-3。api.tick がアーカイブが出たのを見て作り始める = 依頼もそのときに上げる)"""
        if not ROW_ID_RE.match(rid or ""):
            raise ValueError("依頼の id の形が違います")
        now = self._now_ms()
        r = {"id": rid, "kind": kind if kind in KINDS else "url", "origin": "request", "state": "waiting" if state == "waiting" else "sent", "form": form,
             "source": source, "runId": run_id, "createdAt": now, "updatedAt": now, "packs": [], "groups": [], "error": "", "note": "",
             "pc": "user" if pc == "user" else "this"}
        if r["pc"] == "user" and r["state"] != "waiting":
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
            if r is None or r["state"] not in ("waiting", "sent", "making", "recording"):
                return None
            now = self._now_ms()
            r.update(state="failed", failedAt=now, error=str(text or "失敗しました")[:500], updatedAt=now)
            self._failed_code(r)
            self._save()
            if self.on_fail is not None:
                try:
                    self.on_fail(json.loads(json.dumps(r)))
                except Exception:   # noqa: BLE001  (診断で受信箱を止めない)
                    pass
            return r

    @staticmethod
    def _failed_code(r):
        """失敗の種類を数える(自動のやり直しが残っている間は数えない = 「同じ失敗が 2 回目」は友人が送り直してまた落ちたとき。C-2-16)"""
        cls = _progress.classify(r.get("error") or "", r.get("kind") or "url")
        if cls["retry"] and (r.get("autoRetries") or 0) < cls.get("retryMax", RETRY_MAX):
            return
        r["failCodes"] = ((r.get("failCodes") or []) + [cls["code"]])[-10:]

    # ------------------------------------------------------------ アーカイブ待ち・取り消す・知らせた(F3-3)
    def waiting_rows(self):
        with self.lock:
            return [json.loads(json.dumps(r)) for r in self.rows if r["state"] == "waiting"]

    def wait_checked(self, rid):
        with self.lock:
            r = self.row(rid)
            if r is not None and r["state"] == "waiting":
                r["checkedAt"] = self._now_ms()
                self._save()

    def wait_failed(self, rid, text):
        return self.fail(rid, text)

    def wait_done(self, rid):
        """アーカイブが出た: 普通の URL の依頼の行に(作り始めるのは呼ぶ側)"""
        with self.lock:
            r = self.row(rid)
            if r is None or r["state"] != "waiting":
                return None
            r.update(state="sent", kind="url", waited=True, updatedAt=self._now_ms())
            if isinstance(r.get("form"), dict):
                r["form"]["kind"] = "url"
            self._save()
            return r

    def to_remote(self, rid):
        """アーカイブ待ちだった依頼の行を、同期が上げる依頼にする(remote pending)"""
        with self.lock:
            r = self.row(rid)
            if r is not None:
                r.update(pc="user", remote={"state": "pending", "uploadedAt": None}, updatedAt=self._now_ms())
                self._save()
            return r

    def cancelled(self, rid, drop=False):
        """[取り消す]: 届いた物が無ければ(か drop)行を消す。あれば送った物の一覧から外し、届いた物は受け取るに残す -> 行か None"""
        with self.lock:
            r = self.row(rid)
            if r is None:
                return None
            if drop or not r["packs"]:
                self.rows.remove(r)
                self._save()
                return None
            now = self._now_ms()
            r.update(cancelled=True, updatedAt=now)
            if r["state"] in ("sent", "making", "recording"):
                r.update(state="arrived", arrivedAt=r.get("arrivedAt") or now)
                if isinstance(r.get("live"), dict):
                    r["live"].update(phase="done", finished=r["live"].get("finished") or now, endedAt=r["live"].get("endedAt") or now)
            self._save()
            return r

    def reported(self, rid):
        with self.lock:
            r = self.row(rid)
            if r is None:
                raise KeyError(rid)
            r["reportedAt"] = self._now_ms()
            self._save()
            return r

    # ------------------------------------------------------------ この PC のライブの行(engine が呼ぶ)
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

    def set_live_form(self, rid, live):
        """録画中に変えたライブの設定(C-2-11)を行の送った欄 form.live に -> 行"""
        with self.lock:
            r = self.row(rid)
            if r is None:
                raise KeyError(rid)
            r["form"] = dict(r.get("form") or {}, live=dict(live))
            r["updatedAt"] = self._now_ms()
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
        """枠に入る前のパックを 1 本ずつの枠へ(段ごと。C-3-1)-> 足した枠の n のリスト"""
        n = 1
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
                if not isinstance(d, str) or not os.path.isdir(fsio.long_path(d)):
                    continue
                base =pack_name(d)
                name, i = base, 2
                while name in names:
                    name, i = "%s-%d" % (base[:NAME_MAX - 4], i), i + 1
                names.add(name)
                r["packs"].append({"name": name, "dir": d, "title": pack_title(base), "seconds": p.get("seconds"), "verdict": None, "at": None, "by": None,
                                   "phase": phase if phase in PHASES else "live", "arrivedAt": now})
                self._number(r, r["packs"][-1])
                added += 1
            if not added and state in ("error", "cancelled"):
                lv["errors"] = int(lv.get("errors") or 0) + 1
                lv["lastError"] = str(error or "止めました")[:300]
            made = self._live_group(r, False)
            if added and r["state"] in ("arrived", "done", "failed"):   # 閉じたあとに届いた(採用の遅れ・配信後の追加)= もう一度「届いた」
                r.update(state="arrived", arrivedAt=now, doneAt=None, failedAt=None, error="")
            r["updatedAt"] = now
            self._save()
            return json.loads(json.dumps(r)), made

    def live_update(self, rid, recording, busy, waiting="", why=None):
        """見回り: recording = 録画中か・busy = 書き出し・作っている切り抜きがあるか・waiting = 検出の採用・配信後の追加を待つ理由("" = 待たない)。
        録画が終わって作る物が無ければ残りを組に・どれも待たなければ行を閉じる(パックがあれば「届いた」・全部決めていれば「決めた」・無ければ「失敗」)。
        why = パックが無いまま閉じるときの理由 {"code", "text"}(engine.live_cause。live.cause に残す)。-> 足した組の n のリスト"""
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
                    self._live_close(r, now, why)
            if json.dumps([r["state"], lv, r.get("groups")]) != before:
                r["updatedAt"] = now
                self._save()
            return made

    def _live_close(self, r, now, why=None):
        lv = r["live"]
        if not r["packs"]:
            why = why if isinstance(why, dict) else {}
            lv["cause"] = why.get("code") or ("error" if lv.get("lastError") else "none")
            r.update(state="failed", failedAt=now,
                     error=str(why.get("text") or lv.get("lastError") or "録画から切り抜く所が見つからず、パックができませんでした")[:500])
            self._failed_code(r)
        elif all(p["verdict"] for p in r["packs"]):
            self._close_row(r)
        else:
            r.update(state="arrived", arrivedAt=now)

    def resent(self, rid, run_id, auto=False):
        """失敗した行をもう一度送った(同じ行を「送った」に戻す。ユーザーの PC の行は依頼を上げ直す)。
        auto = 自動のやり直し(回数を数える)/ 友人が押した = 数え直す(C-2-16)"""
        with self.lock:
            r = self.row(rid)
            if r is None:
                raise KeyError(rid)
            r.update(state="sent", runId=run_id, error="", note="", failedAt=None, updatedAt=self._now_ms(),
                     autoRetries=(r.get("autoRetries") or 0) + 1 if auto else 0, reportedAt=None if not auto else r.get("reportedAt"))
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

    def finished(self, run_id, state, error, packs, case=None, note=""):
        """② の実行が終わった。packs = [{"dir", "seconds"}](作ったパック)・case = 案件のフォルダ。
        パックがあれば「届いた」(1 本ずつの枠に)・無ければ「失敗」(理由)。-> 行か None(玄関の依頼でない実行)"""
        with self.lock:
            r = self.by_run(run_id)
            if r is None:
                return None
            now = self._now_ms()
            r["case"] = case if isinstance(case, str) else r.get("case")
            items = []
            for p in packs:
                d = p.get("dir")
                if not isinstance(d, str) or not os.path.isdir(fsio.long_path(d)):
                    continue
                name = pack_name(d)
                items.append({"name": name, "dir": d, "title": pack_title(name), "seconds": p.get("seconds"), "verdict": None, "at": None, "by": None,
                              "arrivedAt": now})
            if items:
                for it in items:
                    self._number(r, it)
                r["packs"] = items
                r["groups"] = [{"n": i + 1, "names": [x["name"]], "preview": None} for i, x in enumerate(items)]   # 1 本ずつ(C-3-1)
                r.update(state="arrived", arrivedAt=now, error="", note=note or "")
            elif r.get("cancelled") or (state == "cancelled" and not r["packs"]):   # [取り消す] で止めた = 行ごと消す(C-2-14)
                self.rows.remove(r)
                self._save()
                return None
            else:
                r.update(state="failed", failedAt=now,
                         error=error or ("止めました" if state == "cancelled" else "切り抜く所が見つからず、パックができませんでした"))
                self._failed_code(r)
            r["updatedAt"] = now
            self._save()
            return r

    def set_preview(self, rid, n, path):
        """枠 n の確認用の動画(そのパックの確認用の動画 = p.preview にも)"""
        with self.lock:
            r = self.row(rid)
            g = next((g for g in (r or {}).get("groups") or [] if g["n"] == n), None)
            if g is not None:
                g["preview"] = path
                if len(g.get("names") or []) == 1:
                    _r, p = self._pack(rid, g["names"][0])
                    if p is not None and not (p["verdict"] == "keep" or p.get("by") == "auto"):
                        p["preview"] = path
                if path is None and g.get("remote"):
                    g["remote"]["preview"] = None   # Dropbox に確認用の動画が無かった = もう取りに行かない
                self._save()

    # ------------------------------------------------------------ Dropbox の /出力/ から届いた物(同期が呼ぶ)
    def known_remote(self):
        """行に入れた Dropbox の名前(zip・確認用の動画・印・失敗の知らせ)の集まり(同じ物を 2 回取り込まない)"""
        out = set()
        with self.lock:
            for r in self.rows:
                for p in r["packs"]:
                    rem = p.get("remote") or {}
                    out.update(x for x in (rem.get("zip"), rem.get("meta")) if x)
                for g in r.get("groups") or []:
                    rem = g.get("remote") or {}
                    out.update(x for x in (rem.get("previewName"),) if x)
                out.update(r.get("remoteFails") or [])
        return out

    def _remote_row(self, rid, origin, title, now):
        r = {"id": rid, "kind": "remote", "origin": "auto" if origin == "auto" else "request", "state": "arrived", "form": None,
             "source": {"url": "", "videoId": "", "title": title, "channel": ""}, "runId": None, "createdAt": now, "updatedAt": now,
             "packs": [], "groups": [], "error": "", "note": "", "pc": "auto" if origin == "auto" else "user"}
        self.rows.insert(0, r)
        return r

    def import_remote(self, rid, origin, title, specs):
        """/出力/ のパックを行に入れる(依頼 id の行があればその行・無ければ新しい行 = origin auto なら札「依頼なし」)。
        specs = [{"preview": 名前か None, "previewSize", "packs": [{"zip", "title", "seconds", "size", "rev", "hash", "meta"}]}](ふつうは 1 本ずつ)"""
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
                    info = it.get("info") if isinstance(it.get("info"), dict) else {}
                    r["packs"].append({"name": name, "dir": None, "title": str(it.get("title") or pack_title(name)),
                                       "seconds": it.get("seconds") if it.get("seconds") is not None else info.get("seconds"),
                                       "verdict": None, "at": None, "by": None, "want": None, "error": "", "arrivedAt": now,
                                       "info": {k: info[k] for k in ("videoId", "markId", "streamTitle", "streamer") if info.get(k)},
                                       "remote": {k: it.get(k) for k in ("zip", "size", "rev", "hash", "meta")}})
                    self._number(r, r["packs"][-1])
                    got.append(name)
                if got:
                    n += 1
                    r["groups"].append({"n": n, "names": got, "preview": None,
                                        "remote": {"previewName": spec.get("preview"), "preview": spec.get("preview"),
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
        """取ってくる確認用の動画 -> [(依頼 id, 枠の n, Dropbox の名前, 大きさ)]"""
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
                self._record(r, p, "good")
            except OSError as e:
                self.log("判断の記録を書けませんでした: %s" % e.__class__.__name__)
            p.update(verdict="keep", at=self._now_ms(), by=None)
            self._drop_preview(p)
            self._maybe_close(r)
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
        """決めた Dropbox の枠 -> [(依頼 id, 枠の n, [/出力/ の名前])](zip・印・確認用の動画。消すのは同期)"""
        out = []
        with self.lock:
            for r in self.rows:
                by = {p["name"]: p for p in r["packs"]}
                for g in r.get("groups") or []:
                    rem = g.get("remote")
                    if not rem or rem.get("cleaned"):
                        continue
                    ps = [by[n] for n in g["names"] if n in by]
                    now = self._now_ms()
                    # 受け取った・3 日の自動は今すぐ・見送った / 届かなくてよかったは戻せる 3 日を待ってから(C-3-6)
                    if ps and all(p["verdict"] and (p["verdict"] == "keep" or p.get("by") == "auto" or now - (p.get("at") or 0) >= KEEP_DAYS * DAY * 1000)
                                  for p in ps):
                        names = [x for p in ps for x in ((p.get("remote") or {}).get("zip"), (p.get("remote") or {}).get("meta")) if x]
                        out.append((r["id"], g["n"], names + [x for x in (rem.get("previewName"),) if x]))
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

    # ------------------------------------------------------------ 決める(C-3-4〜C-3-8)
    def decide(self, rid, names, verdict, by=None, reason=None):
        """パック(names。空なら行の決めていない物全部)を決める -> {"done": [名前], "pending": [名前], "errors": [{"name", "message"}], "row"}。
        keep = [受け取る](保存先の <配信の日付>_<配信者>_<題>\\#番号 へ移す)/ skip = [見送る](アプリのごみ箱へ。3 日は戻せる)/
        bad = 届かなくてよかった(reason boring・cut。見送ると同じに片付ける)。どれも送り返しへ判断の記録(v 2)を書く。
        Dropbox のパック(まだ手元に無い): keep は「受け取っています」にするだけ(同期が取って展開してから決める)・skip と bad は取らずに決める。
        3 日の自動(by auto)は見送る(理由なし)で、ごみ箱を経ずにすぐ消す。受け取っている途中の物は自動で見送らない"""
        if verdict not in VERDICTS:
            raise ValueError("決め方は keep・skip・bad です")
        if verdict == "bad" and reason not in REASONS:
            raise ValueError("届かなくてよかった理由は boring か cut です")
        with self.lock:
            r = self.row(rid)
            if r is None or r["state"] not in ("arrived", "recording", "done"):
                raise KeyError(rid)
            want = set(names or [])
            done, pending, errors = [], [], []
            for p in r["packs"]:
                if p["verdict"] or (want and p["name"] not in want) or (by == "auto" and p.get("want") == "keep"):
                    continue
                remote = bool(p.get("remote")) and not p.get("dir")
                if remote and verdict == "keep":
                    p.update(want="keep", error="")
                    pending.append(p["name"])
                    continue
                try:
                    if not remote:
                        self._place(r, p, verdict, by)
                except OSError as e:
                    errors.append({"name": p["name"], "message": self._move_failed(verdict, e)})
                    continue
                try:
                    self._record(r, p, JUDGE[verdict], reason=reason if verdict == "bad" else None, by=by)
                except OSError as e:
                    # 移したあとに記録が書けない: 移した物を元へ戻して「決めていない」のまま(もう一度押せば決まる)。
                    # 戻せない(3 日の自動ですぐ消した・戻す移動も失敗)ときは、記録なしで決めたことにする(ごみ箱の物は 3 日は [戻す] が効く)
                    self.log("判断の記録を書けませんでした: %s" % e.__class__.__name__)
                    if not remote and self._unplace(p):
                        errors.append({"name": p["name"], "message": self._move_failed(verdict, e)})
                        continue
                p.update(verdict=verdict, reason=reason if verdict == "bad" else None, at=self._now_ms(), by=by, want=None)
                if verdict == "keep" or by == "auto":
                    self._drop_preview(p)
                done.append(p["name"])
            self._maybe_close(r)
            r["updatedAt"] = self._now_ms()
            self._save()
            return {"done": done, "pending": pending, "errors": errors, "row": r}

    def undo(self, rid, names):
        """[戻す](C-3-6): 見送った・届かなくてよかったの物を 3 日の間は決める前に戻す(ごみ箱から元の場所へ・取り消しの記録)-> {"done", "errors"}"""
        with self.lock:
            r = self.row(rid)
            if r is None:
                raise KeyError(rid)
            want = set(names or [])
            done, errors = [], []
            now = self._now_ms()
            for p in r["packs"]:
                if p["name"] not in want or p["verdict"] not in ("skip", "bad") or p.get("by") == "auto" or now - (p.get("at") or 0) >= KEEP_DAYS * DAY * 1000:
                    continue
                try:
                    if p.get("trash"):
                        if not os.path.isdir(fsio.long_path(p["trash"])):
                            raise FileNotFoundError(p["trash"])
                        os.makedirs(fsio.long_path(os.path.dirname(p["dir"])), exist_ok=True)
                        back = p["dir"] if not os.path.exists(fsio.long_path(p["dir"])) else unique_dest(os.path.dirname(p["dir"]), os.path.basename(p["dir"]))
                        shutil.move(fsio.long_path(p["trash"]), fsio.long_path(back))
                        p["dir"] = back
                    self._record(r, p, "retract", of=p.get("verdictId"))
                except OSError as e:
                    errors.append({"name": p["name"], "message": "戻せませんでした(%s)" % e.__class__.__name__})
                    continue
                p.update(verdict=None, reason=None, at=None, by=None, trash=None, arrivedAt=now)   # 戻した物にも 3 日
                done.append(p["name"])
            if done and r["state"] == "done":
                r.update(state="arrived", doneAt=None, arrivedAt=now)
            r["updatedAt"] = now
            self._save()
            return {"done": done, "errors": errors}

    @staticmethod
    def _move_failed(verdict, e):
        what = "保存先へ移せませんでした" if verdict == "keep" else "片付けられませんでした"
        return "%s(%s)。フォルダを開いているソフトを閉じてから、もう一度押してください" % (what, e.__class__.__name__)

    def _place(self, r, p, verdict, by):
        src = p["dir"]
        if not os.path.isdir(fsio.long_path(src)):
            raise FileNotFoundError(src)
        if verdict == "keep":
            folder, name = self.keep_dest(r, p)
            os.makedirs(fsio.long_path(folder), exist_ok=True)
            dest = unique_dest(folder, name)
            shutil.move(fsio.long_path(src), fsio.long_path(dest))
            p["savedTo"] = dest
        elif by == "auto":   # 3 日決めなかった物 = ごみ箱を経ずにすぐ消す(C-3-7)
            shutil.rmtree(fsio.long_path(src))
        else:
            p["trash"] = self._to_trash(src)

    def _unplace(self, p):
        """_place で移した物を元の場所(p["dir"])へ戻す -> 戻せたか(すぐ消した物・元の場所がふさがっている・移せないは False)"""
        moved = p.get("savedTo") or p.get("trash")
        if not moved or os.path.exists(fsio.long_path(p["dir"])):
            return False
        try:
            shutil.move(fsio.long_path(moved), fsio.long_path(p["dir"]))
        except OSError as e:
            self.log("移した物を元へ戻せませんでした: %s" % e.__class__.__name__)
            return False
        p.update(savedTo=None, trash=None)
        return True

    def keep_dest(self, r, p):
        """受け取った物の置き場所(C-3-8)-> (<保存先>\\<配信の日付>_<配信者名>_<配信タイトル 40 文字>, "#番号")"""
        info = self.stream_of(r, p)
        day = datetime.datetime.fromtimestamp((info["startAt"] or p.get("arrivedAt") or r["createdAt"]) / 1000.0).strftime("%Y-%m-%d")
        parts = [day] + [x for x in (info["streamer"], info["title"][:TITLE_CUT]) if x]
        folder = BAD_NAME.sub("_", "_".join(parts)).strip(" .") or day
        return os.path.join(self.save_dir(), folder), "#%d" % (p.get("num") or 0)

    def saved_dir(self, rid, name):
        """受け取った物のフォルダ(手元にあれば)か None([フォルダを開く])"""
        with self.lock:
            _r, p = self._pack(rid, name)
            d = (p or {}).get("savedTo")
            return d if d and os.path.isdir(fsio.long_path(d)) else None

    def keep_place(self, rid, name):
        """Dropbox のパックを受け取る置き場所(同期が使う)-> (配信のフォルダ, "#番号") か None"""
        with self.lock:
            r, p = self._pack(rid, name)
            return self.keep_dest(r, p) if p is not None else None

    def _record(self, r, p, judge, reason=None, by=None, of=None):
        """送り返しの判断の記録(notes:docs/spec/friend.md の 12-2 の v 2)。名前 = <依頼 id>__<パック名>~<at 13 桁>.verdict.json"""
        os.makedirs(self.outbox, exist_ok=True)
        at = self._now_ms()
        while os.path.exists(os.path.join(self.outbox, "%s__%s~%013d%s" % (r["id"], p["name"], at, VERDICT_SUFFIX))):
            at += 1
        info = p.get("info") or {}
        doc = {"v": 2, "id": uuid.uuid4().hex[:16], "judge": judge, "zip": (p.get("remote") or {}).get("zip") or p["name"],
               "origin": r.get("origin") or "request", "at": at}
        vid = info.get("videoId") or (r.get("source") or {}).get("videoId")
        if vid:
            doc["videoId"] = vid
        if info.get("markId"):
            doc["markId"] = info["markId"]
        if judge == "bad":
            doc["reason"] = reason
        if judge == "retract":
            doc["of"] = of or ""
        if by == "auto":
            doc["by"] = "auto"
        fsio.write_json(os.path.join(self.outbox, "%s__%s~%013d%s" % (r["id"], p["name"], at, VERDICT_SUFFIX)), doc, indent=None)
        if judge != "retract":
            p["verdictId"] = doc["id"]

    def _drop_preview(self, p):
        if p.get("preview"):
            fsio.unlink_quiet(p["preview"])
            p["preview"] = None

    def _maybe_close(self, r):
        """全部決めた行は done(案件のフォルダは最後に決めてから 3 日で片付ける = sweep。2 回目の依頼で失敗しないよう、決めた時には動かさない = C-3-7)"""
        if r["state"] == "arrived" and r["packs"] and all(p["verdict"] for p in r["packs"]):
            r["state"], r["doneAt"] = "done", self._now_ms()

    def trash_dir(self):
        return os.path.join(self.case_root(), TRASH_NAME)

    def _to_trash(self, path):
        """一時保管の ごみ箱\\<日付>\\受信箱\\ へ移す(ytt/trashbin の 1 か所。元の場所は manifest に)-> 移した先。移せなければ OSError"""
        res = trashbin.to_trash(self.trash_dir(), [path], TRASH_KIND, clock=self.clock)
        if not res["moved"]:
            raise OSError(res["failed"][0][1] if res["failed"] else "移す物がありません")
        return res["moved"][0][1]

    def _close_row(self, r):
        """録画の行を閉じる(全部決めていれば _maybe_close が done に)"""
        r["state"] = "arrived" if r["state"] == "recording" else r["state"]   # 録画の行を閉じるとき(全部決めていれば _maybe_close が done に)
        self._maybe_close(r)

    def _trash_case(self, r):
        root = self.case_root()
        for case in dict.fromkeys([r.get("case")] + list(r.get("cases") or [])):   # ライブの行は切り抜きごとの案件
            if case and root and os.path.isdir(fsio.long_path(case)) and fsio.is_inside(case, root, strict=True) and not fsio.is_inside(case, self.trash_dir()):
                try:
                    self._to_trash(case)
                except OSError as e:
                    self.log("案件フォルダをごみ箱へ移せませんでした: %s" % e.__class__.__name__)

    def remove(self, rid):
        """失敗の行を消す([取り消す]・3 日の片付け)。届いた物の無い案件のフォルダもごみ箱へ"""
        with self.lock:
            r = self.row(rid)
            if r is None or r["state"] != "failed":
                raise KeyError(rid)
            if not r["packs"]:
                self._trash_case(r)
            self.rows.remove(r)
            self._save()

    # ------------------------------------------------------------ 3 日の片付け(C-3-7)
    def left_days(self, r):
        """自動で片付くまでの日数(届いた行・失敗の行)か None"""
        at = r.get("arrivedAt") if r["state"] == "arrived" else r.get("failedAt") if r["state"] == "failed" else None
        if not at:
            return None
        return max(0, KEEP_DAYS - int((self._now_ms() - at) // (DAY * 1000)))

    def sweep(self):
        """3 日決めなかった物を自動で見送る(すぐ消す)・決めて 3 日の行の案件のフォルダを片付ける・失敗の行を 3 日で消す・ごみ箱の 3 日より前を消す
        -> 自動で見送った本数(画面に「3 日たった n 本を片付けました」を 1 行 = notice)"""
        n = 0
        limit = KEEP_DAYS * DAY * 1000
        with self.lock:
            now = self._now_ms()
            for r in list(self.rows):
                if r["state"] == "recording" and now - ((r.get("live") or {}).get("endedAt") or r["createdAt"]) >= LIVE_STALE * 1000:
                    self._live_group(r, True)   # 録画元が見つからないまま終わらない行= 残りを組にして閉じる
                    r.setdefault("live", {})["finished"] = now
                    self._live_close(r, now)
                if r["state"] in ("arrived", "recording"):
                    old = [p["name"] for p in r["packs"] if not p["verdict"] and now - (p.get("arrivedAt") or r.get("arrivedAt") or now) >= limit]
                    if old:
                        n += len(self.decide(r["id"], old, "skip", by="auto")["done"])
                    for p in r["packs"]:   # 見送って 3 日たった物の確認用の動画
                        if p["verdict"] in ("skip", "bad") and p.get("preview") and now - (p.get("at") or now) >= limit:
                            self._drop_preview(p)
                elif r["state"] == "failed" and now - (r.get("failedAt") or now) >= limit:
                    self.remove(r["id"])
                elif r["state"] == "done" and now - (r.get("doneAt") or now) >= limit and not self._remote_left(r):
                    for p in r["packs"]:
                        self._drop_preview(p)
                    self._trash_case(r)
                    self.rows.remove(r)   # Dropbox にまだ消せていない物がある行は残す(消し終えるまで同じ物を取り込み直さない)
            if n:
                self.notice = {"n": (self.notice or {}).get("n", 0) + n, "at": now}
            self._save()
        self._purge_trash()
        return n

    def notice_seen(self):
        with self.lock:
            if self.notice:
                self.notice = None
                self._save()

    def _purge_trash(self):
        trashbin.purge(self.trash_dir(), KEEP_DAYS, self.clock())

    # ------------------------------------------------------------ 画面へ
    def view(self, status_of=None):
        """送った物の行(done は出さない)。status_of(run_id) = ② の実行の状態(作っている行の進み具合)か None"""
        with self.lock:
            out = []
            for r in self.rows:
                if r["state"] == "done":
                    continue
                v = json.loads(json.dumps(r))
                v["left"] = self.left_days(r)
                v["undecided"] = sum(1 for p in r["packs"] if not p["verdict"])
                f = v.get("form") or {}
                if isinstance(f.get("file"), dict):   # 動画ファイルのパスは画面に出さない(名前と大きさだけ)
                    f["file"] = {k: f["file"].get(k) for k in ("name", "size")}
                lv = v.pop("live", None)
                if isinstance(lv, dict):
                    v["live"] = {"phase": lv.get("phase") or "recording", "ended": bool(lv.get("endedAt")), "errors": lv.get("errors") or 0}
                v.pop("cases", None)
                for p in v["packs"]:
                    for k in ("dir", "savedTo", "trash", "preview"):   # 画面に絶対パスを出さない(開くのは玄関の口から)
                        p.pop(k, None)
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

    def stream_of(self, r, p):
        """パックの配信 -> {"key", "videoId", "title", "streamer", "startAt"}(届いた meta → 行の欄 → 一覧の写しの順)"""
        info = p.get("info") or {}
        src = r.get("source") or {}
        form = r.get("form") or {}
        vid = info.get("videoId") or src.get("videoId") or ""
        seen = self.stream_info(vid) if vid else None
        seen = seen or {}
        title = info.get("streamTitle") or src.get("title") or seen.get("title") or src.get("fileName") or ""
        if r.get("kind") == "file":
            title = form.get("title") or title
        return {"key": p.get("key") or _stream_key(r, p), "videoId": vid, "title": str(title)[:200],
                "streamer": str(info.get("streamer") or form.get("streamer") or seen.get("streamer") or src.get("channel") or "")[:60],
                "startAt": seen.get("startAt")}

    def receive_view(self):
        """受け取る画面(C-3): 配信ごとの段(最後に届いた時刻の新しい順・段の中は番号順)・見送った物(3 日の間)・まだ決めていない本数"""
        with self.lock:
            now = self._now_ms()
            secs, skipped, total = {}, [], 0
            for r in self.rows:
                making = r["state"] in ("waiting", "sent", "making", "recording") and not r.get("cancelled")
                f = r.get("form") or {}
                expect = (len(f.get("ranges") or []) or f.get("top")) if r.get("kind") in ("url", "remote") else None
                for p in r["packs"]:
                    info = self.stream_of(r, p)
                    s = secs.get(info["key"])
                    if s is None:
                        s = secs[info["key"]] = {"key": info["key"], "videoId": info["videoId"], "title": info["title"], "streamer": info["streamer"],
                                                 "auto": False, "making": False, "expect": 0, "arrived": 0, "lastAt": 0, "items": [], "rows": set()}
                    s["arrived"] += 1
                    s["lastAt"] = max(s["lastAt"], p.get("arrivedAt") or r.get("arrivedAt") or 0)
                    s["auto"] = s["auto"] or r.get("origin") == "auto"
                    if r["id"] not in s["rows"]:
                        s["rows"].add(r["id"])
                        s["making"] = s["making"] or making
                        s["expect"] += expect if isinstance(expect, int) and making else 0
                    it = self._item(r, p, info)
                    if not p["verdict"]:   # 受け取っている途中(Dropbox から取っている)の物も並べる(札「受け取っています」)
                        s["items"].append(it)
                        total += 0 if p.get("want") == "keep" else 1
                    elif p["verdict"] in ("skip", "bad") and p.get("by") != "auto" and now - (p.get("at") or 0) < KEEP_DAYS * DAY * 1000:
                        it["left"] = max(0, KEEP_DAYS - int((now - p["at"]) // (DAY * 1000)))
                        skipped.append(it)
            out = []
            for s in secs.values():
                s.pop("rows")
                s["items"].sort(key=lambda x: x["num"] or 0)
                if s["items"]:
                    out.append(s)
            out.sort(key=lambda s: -s["lastAt"])
            skipped.sort(key=lambda x: -(x.get("at") or 0))
            return {"sections": out, "skipped": skipped, "undecided": total, "notice": dict(self.notice) if self.notice else None}

    @staticmethod
    def _clip_label(p):
        """カードの下の文字: 切り抜きの名前が <番号>_<始まり>-<終わり>(書き出しの名前)なら「配信の 1:56 あたり」・違えば題のまま。
        名前の区間は見どころ(マーク)の区間で、届く動画は編集のための前後の余白(LD-2f)込み = 区間の長さを出すと動画の長さと 2 通りに見えるので、始まりだけ"""
        m = CLIP_RANGE_RE.search(str(p.get("title") or p.get("name") or ""))
        if not m:
            return p["title"]
        a = int(m.group(1)) * 3600 + int(m.group(2)) * 60 + int(m.group(3))
        return "配信の %s あたり" % _hms(a)

    @staticmethod
    def _item(r, p, info):
        num = p.get("num") or 0
        title = "%s|%s #%d" % (info["streamer"], info["title"], num) if info["streamer"] else "%s #%d" % (info["title"] or p["title"], num)
        return {"id": r["id"], "name": p["name"], "num": num, "title": title, "clip": Inbox._clip_label(p), "seconds": p.get("seconds"),
                "preview": bool(p.get("preview")), "remote": bool(p.get("remote")), "want": p.get("want"), "error": p.get("error") or "",
                "verdict": p["verdict"], "reason": p.get("reason"), "at": p.get("at"), "arrivedAt": p.get("arrivedAt"),
                "videoId": info["videoId"], "auto": r.get("origin") == "auto"}

    def pack_preview(self, rid, name):
        """1 本の確認用の動画のパス(手元にあれば)か None"""
        with self.lock:
            r, p = self._pack(rid, name)
            if p is None:
                return None
            if p.get("preview"):
                return p["preview"]
            g = next((g for g in r.get("groups") or [] if g.get("names") == [name] and g.get("preview")), None)
            return g["preview"] if g else None


def _hms(sec):
    h, m, s = sec // 3600, sec % 3600 // 60, sec % 60
    return "%d:%02d:%02d" % (h, m, s) if h else "%d:%02d" % (m, s)


def _stream_key(r, p):
    """配信ごとの通し番号の鍵(C-3-2): 配信の id > 動画ファイルの題 > 依頼の行"""
    vid = (p.get("info") or {}).get("videoId") or (r.get("source") or {}).get("videoId")
    if vid:
        return "v:" + vid
    if r.get("kind") == "file":
        return "f:" + str((r.get("form") or {}).get("title") or (r.get("source") or {}).get("fileName") or r["id"])[:120]
    return "r:" + r["id"]
