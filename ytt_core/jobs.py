"""重い処理の同時実行数の上限(統合計画の段階4)。

入口(start-all.bat)の中では3つのツールが1つのプロセスで動くので、ここの SLOTS をみんなで使う:
  スタジオの解析・書き出し、文字起こし(認識は別プロセスのワーカーだが、ジョブの順番はここで待つ)、cut2resolve のパック作成。
上限を超えた処理は、先に来た順に待つ(待っている間も取り消せる)。ツールを単独で起動したときは、そのツールの中だけの上限になる。
上限は環境変数 YTT_MAX_HEAVY_JOBS(1〜8。既定 2)。

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

DEFAULT_LIMIT = 2
MAX_LIMIT = 8
WAIT_MESSAGE = "他のツールの処理が終わるのを待っています"


def limit_from_env(env=None):
    env = os.environ if env is None else env
    try:
        n = int(str(env.get("YTT_MAX_HEAVY_JOBS") or DEFAULT_LIMIT).strip())
    except ValueError:
        return DEFAULT_LIMIT
    return min(MAX_LIMIT, max(1, n))


class HeavySlots:
    def __init__(self, limit=None):
        self.limit = limit or limit_from_env()
        self._cv = threading.Condition()
        self._seq = itertools.count(1)
        self._active = {}    # token -> {"tool", "label", "since"}
        self._waiting = []   # [token](先に来た順)
        self._info = {}      # token -> {"tool", "label", "since"}(待っている間)

    def acquire(self, tool, label="", cancelled=None, on_wait=None, poll=0.5):
        """空くまで待って番号(token)を返す。待っている間に cancelled() が真になれば None。
        on_wait: 待ち始めたときに1回だけ呼ぶ(画面に「待っています」を出す用)"""
        cancelled = cancelled or (lambda: False)
        token = next(self._seq)
        info = {"tool": str(tool), "label": str(label)[:80], "since": time.time()}
        waited = False
        with self._cv:
            self._waiting.append(token)
            self._info[token] = info
            try:
                while not (self._waiting[0] == token and len(self._active) < self.limit):
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
                self._active[token] = dict(info, since=time.time())
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
    def slot(self, tool, label="", cancelled=None, on_wait=None, poll=0.5):
        token = self.acquire(tool, label, cancelled, on_wait, poll)
        try:
            yield token is not None
        finally:
            self.release(token)

    def snapshot(self):
        """{"limit", "active": [{"tool", "label", "seconds"}], "waiting": [...]}(入口の画面用)"""
        now = time.time()
        with self._cv:
            act = [dict(tool=i["tool"], label=i["label"], seconds=int(now - i["since"])) for i in self._active.values()]
            wait = [dict(tool=self._info[t]["tool"], label=self._info[t]["label"], seconds=int(now - self._info[t]["since"]))
                    for t in self._waiting if t in self._info]
        return {"limit": self.limit, "active": act, "waiting": wait}


SLOTS = HeavySlots()   # プロセスに1つ(入口の中では3ツールで共有)
