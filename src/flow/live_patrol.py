"""ライブの見回りの糸の骨組み(OPT2。live_export.Exporter・live_archive.Archiver・live_tx.LiveTx が継ぐ)と中止の例外 1 組。

糸は `_step()` を回す(真 = 仕事をした = すぐ次へ / 偽 = wake か poll 秒まで待つ。例外は LOOP_ERROR で記録して止めない)。
`close()` = 入口の終了: `_halt` を立てて起こし、`_on_close()` のあと JOIN 秒まで待つ(0 = 待たない)。
`Cancelled` = ジョブの取り消し(ytt/errors と同じクラス)・`Halted` = 入口の終了(ジョブは待ちに戻して次の起動でやり直す)。
"""
import threading

from ytt import errors

Cancelled = errors.Cancelled   # lint: keep 別名 = 中止の例外の正は ytt/errors


class Halted(Exception):
    """入口の終了(ジョブは「待ち」に戻して、次の起動でやり直す)"""


class Patrol:
    NAME, LOOP_ERROR, JOIN, poll = "live", "%r", 15, 30.0   # 糸の名前・見回りの例外の文・close で待つ秒・仕事が無いときに待つ秒

    def __init__(self):
        self.wake, self._halt, self._start_lock, self.thread = threading.Event(), threading.Event(), threading.Lock(), None

    def start(self):
        with self._start_lock:
            if self.thread is None or not self.thread.is_alive():
                self._halt.clear()
                self.thread = threading.Thread(target=self._loop, daemon=True, name=self.NAME)
                self.thread.start()

    def close(self):
        self._halt.set()
        self.wake.set()
        self._on_close()
        if self.thread is not None and self.JOIN:
            self.thread.join(self.JOIN)

    def _on_close(self):   # 子プロセスを止めるなど(継ぐ側が決める)
        pass

    def _loop(self):
        while not self._halt.is_set():
            try:
                if self._step():
                    continue
            except Exception as e:   # 見回りは止めない
                self.log(self.LOOP_ERROR % (e,))
            self.wake.wait(self.poll)
            self.wake.clear()

    def _job_cancelled(self, job):   # ジョブの取り消しが頼まれているか(継ぐ側が決める)
        return False

    def _check(self, job, stopped=False):
        """区切りごとの確かめ: 入口の終了なら Halted・取り消し(stopped = 子を止めた・枠を取れなかったあと = 必ず上げる)なら Cancelled"""
        if self._halt.is_set():
            raise Halted()
        if stopped or self._job_cancelled(job):
            raise Cancelled()

    def _stopper(self, job):
        """外のプログラム・待ちに渡す「止めるか」(入口の終了か取り消し)"""
        return lambda: self._halt.is_set() or self._job_cancelled(job)
