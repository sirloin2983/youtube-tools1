"""重い処理の同時実行数の上限(統合計画の段階4)。

入口(start.bat)の中では3つのツールが1つのプロセスで動くので、ここの SLOTS をみんなで使う:
  スタジオの解析・書き出し、文字起こし(認識は別プロセスのワーカーだが、ジョブの順番はここで待つ)、cut2resolve のパック作成。
上限を超えた処理は、先に来た順に待つ(待っている間も取り消せる)。ツールを単独で起動したときは、そのツールの中だけの上限になる。
上限は環境変数 YTT_MAX_HEAVY_JOBS(1〜8。既定 2)。

用途つきの枠(線 D の M6。2026-10-07): 上限とは別に、決まった用途(tool の名前)だけが使える枠 RESERVED を持つ。
今は「ライブの書き出し(tool "live")に 1 つ」だけ。使うのは呼ぶ側が acquire(…, reserved=True) を渡したとき = **録画中だけ**
(src/flow/live_export.py。録画が終わったら普通の枠で順番を待つ)。文字起こし 2 本で上限が埋まっていても、配信中のライブの書き出しは待たされない。
普通の枠が空いていれば、先に来た順のまま普通の枠を使う(用途つきの枠は、普通の枠が埋まっているときだけ・同じ用途の中では先に来た順)。
値は仮(U4 = 本物の 3 時間の配信の値が出たら決め直す。plan/line-d-auto-pack.md の M6)。snapshot の active の行には、用途つきの枠なら extra: true が付く

ここは ① 道具の部品も使う物だけ(枠・中止の例外・中止の確かめ・① の関数への手渡し Ctl)。ジョブの表・待機列・種類の登録・ワーカーの繰り返し・取り消しの受付は ② の src/flow/jobs.py(RS6 a-2。2026-10-10 に移した)。

使い方:
    with jobs.SLOTS.slot("transcribe", "配信タイトル", cancelled=lambda: job["cancel"], on_wait=lambda: ...) as ok:
        if ok:
            ...重い処理...
        # ok が False = 待っている間に取り消された
"""
import contextlib
import itertools
import os
import threading
import time

from . import errors

DEFAULT_LIMIT = 2
MAX_LIMIT = 8
WAIT_MESSAGE = "他のツールの処理が終わるのを待っています"
RESERVED = {"live": 1}   # 用途つきの枠(M6。仮の値): 録画中のライブの書き出しに、上限とは別に 1 つ


def limit_from_env(env=None):
    env = os.environ if env is None else env
    try:
        n = int(str(env.get("YTT_MAX_HEAVY_JOBS") or DEFAULT_LIMIT).strip())
    except ValueError:
        return DEFAULT_LIMIT
    return min(MAX_LIMIT, max(1, n))


class HeavySlots:
    def __init__(self, limit=None, reserved=None):
        """reserved: 用途つきの枠 {tool: 数}(None = RESERVED。{} = 持たない)"""
        self.limit = limit or limit_from_env()
        src = RESERVED if reserved is None else reserved
        self.reserved = {str(k): min(MAX_LIMIT, max(0, int(v))) for k, v in src.items()}
        self._cv = threading.Condition()
        self._seq = itertools.count(1)
        self._active = {}    # token -> {"tool", "label", "since", "extra"(用途つきの枠)}
        self._waiting = []   # [token](先に来た順)
        self._info = {}      # token -> {"tool", "label", "since", "reserved"(用途つきの枠を使ってよい)}(待っている間)

    def _grant(self, token, info):
        """-> "normal"(上限の中の枠)・"extra"(用途つきの枠)・None(まだ待つ)。呼ぶのは self._cv を持っている間"""
        normal = sum(1 for a in self._active.values() if not a.get("extra"))
        if self._waiting[0] == token and normal < self.limit:
            return "normal"
        if info.get("reserved"):
            tool = info["tool"]
            used = sum(1 for a in self._active.values() if a.get("extra") and a["tool"] == tool)
            first = next((t for t in self._waiting if self._info.get(t, {}).get("reserved") and self._info[t]["tool"] == tool), None)
            if used < self.reserved.get(tool, 0) and first == token:   # 同じ用途の中では先に来た順
                return "extra"
        return None

    def acquire(self, tool, label="", cancelled=None, on_wait=None, poll=0.5, reserved=False):
        """空くまで待って番号(token)を返す。待っている間に cancelled() が真になれば None。
        on_wait: 待ち始めたときに1回だけ呼ぶ(画面に「待っています」を出す用)。
        reserved: True なら、普通の枠が埋まっているとき tool の用途つきの枠(RESERVED)も使う(M6。ライブの書き出しの録画中だけ)"""
        cancelled = cancelled or (lambda: False)
        token = next(self._seq)
        info = {"tool": str(tool), "label": str(label)[:80], "since": time.time(),
                "reserved": bool(reserved) and self.reserved.get(str(tool), 0) > 0}
        waited = False
        with self._cv:
            self._waiting.append(token)
            self._info[token] = info
            try:
                while True:
                    kind = self._grant(token, info)
                    if kind:
                        break
                    if cancelled():
                        return None
                    if not waited:
                        waited = True
                        if on_wait:
                            try:
                                on_wait()
                            except Exception:
                                pass
                    self._cv.wait(poll)
                self._active[token] = {"tool": info["tool"], "label": info["label"], "since": time.time(), "extra": kind == "extra"}
                return token
            finally:
                self._waiting.remove(token)
                self._info.pop(token, None)
                self._cv.notify_all()

    def release(self, token):
        if token is None:
            return
        with self._cv:
            self._active.pop(token, None)
            self._cv.notify_all()

    @contextlib.contextmanager
    def slot(self, tool, label="", cancelled=None, on_wait=None, poll=0.5, reserved=False):
        token = self.acquire(tool, label, cancelled, on_wait, poll, reserved)
        try:
            yield token is not None
        finally:
            self.release(token)

    def snapshot(self):
        """{"limit", "active": [{"tool", "label", "seconds", "extra"?}], "waiting": [...]}(入口の画面用。extra: true = 用途つきの枠を使っている)"""
        now = time.time()
        with self._cv:
            act = [dict(tool=i["tool"], label=i["label"], seconds=int(now - i["since"]), **({"extra": True} if i.get("extra") else {}))
                   for i in self._active.values()]
            wait = [dict(tool=self._info[t]["tool"], label=self._info[t]["label"], seconds=int(now - self._info[t]["since"]))
                    for t in self._waiting if t in self._info]
        return {"limit": self.limit, "active": act, "waiting": wait}


SLOTS = HeavySlots()   # プロセスに1つ(入口の中では3ツールで共有)


Cancelled = errors.Cancelled   # lint: keep 別名(RS3-4)= 中止の例外(正は ytt/errors。スタジオの procs.run_capture と同じクラス。差し替えない)


def check_cancel(job):
    """取り消されていれば Cancelled を上げる(ジョブの本体の区切りごとの確かめ。① の認識・判別・後処理が使う)"""
    if job.get("cancel"):
        raise Cancelled()


class Ctl:
    """① の関数への手渡し(OPT2 の J0。docs/design/opt2-jobs-plan.md の 2): 進み具合の報告・取り消し・途中の覚え書き・小さな合図。
    器(② のジョブの表)が 1 ジョブに 1 つ作って ① の fn(spec, ctl) に渡す。CLI は None か Ctl()(報告も取り消しもしない)。
    子プロセスはここに持たない(ytt/tools.run_progress(cancelled=ctl.is_cancelled) の見張りが止める)。枠 SLOTS は器が取る(① は知らない)。
    exc: check() が上げる例外の型(既定は ytt/errors の Cancelled。パックは cut2resolve_core の Cancelled = CLI の扱いを保つ)"""

    def __init__(self, on_progress=None, cancel_event=None, on_note=None, exc=None):
        self._on = on_progress
        self._on_note = on_note
        self.cancel_event = cancel_event or threading.Event()
        self.exc = exc or Cancelled
        self.flags = set()

    @property
    def cancelled(self):
        return self.cancel_event.is_set()

    def is_cancelled(self):
        """cancelled の関数の形(run_progress(cancelled=…)・SLOTS.slot(cancelled=…) にそのまま渡す)"""
        return self.cancel_event.is_set()

    def cancel(self):
        self.cancel_event.set()

    def check(self):
        """区切りごとの確かめ: 取り消されていれば self.exc を上げる"""
        if self.cancel_event.is_set():
            raise self.exc()

    def report(self, frac=None, message=None):
        """進み具合(0〜1 か None)と人が読む段階の文。報告の失敗で処理を止めない"""
        if self._on:
            try:
                self._on(frac, message)
            except Exception:   # noqa: BLE001  (報告の失敗で処理を止めない)
                pass

    def note(self, key, value):
        """器に見せる途中の値(解析のチャットの状態など)。失敗で処理を止めない"""
        if self._on_note:
            try:
                self._on_note(key, value)
            except Exception:   # noqa: BLE001  (覚え書きの失敗で処理を止めない)
                pass

    def flag(self, name):
        """器から ① への小さな合図が立っているか(解析の「チャット待ちだけ打ち切る」skipChat など)"""
        return name in self.flags

    def raise_flag(self, name):
        self.flags.add(name)

    def span(self, lo, hi):
        """子の Ctl: report(frac) を lo〜hi に写す(取り消し・覚え書き・合図は親と共有)"""
        def on(frac, message):
            self.report(None if frac is None else lo + (hi - lo) * max(0.0, min(1.0, frac)), message)
        child = Ctl(on, self.cancel_event, self._on_note, self.exc)
        child.flags = self.flags
        return child

    def timer(self, dur):
        """run_progress の on_time(秒) 用: 秒 / dur を report する関数(dur が 0 以下なら何もしない)"""
        def on_time(sec):
            if dur and dur > 0:
                self.report(max(0.0, min(1.0, sec / dur)))
        return on_time
