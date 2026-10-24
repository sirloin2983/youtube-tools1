# -*- coding: utf-8 -*-
"""③ 人の層: 友人の zip を配る待ちの列と、3 時間ごとの配る回(ユーザーの PC。友人の zip はまとめて配る決め・10-25 ユーザーの OK。
notes:plan/友人の不具合の自動対応-1025.md の「まとめて配る」)。

- 列(<app>\\friend-publish\\queue.json): `py -3.12 dev/build_friend_zip.py --queue --note "<直した一言>"` が積む(add)。何本積んでも配るのは 1 回。
  入口が起動し直しても消えない
- 配る回(tick。受付の見回りが毎回呼ぶ): 3 時間ごとの区切り(0・3・6・9・12・15・18・21 時 = SLOT_HOURS)を越えて最初の見回りで、列に積まれていれば
  main の今の版を 1 回だけ配る(`build_friend_zip.py --publish --from-queue` を窓なしで起こす。配る前の検査は道具が 1 回)。
  入口が落ちていて区切りを逃したら、次に起きた時に 1 回だけ。ライブ中かどうかは見ない(配ってよい)。何も無ければ何もしない
- 失敗: 配る道具が知らせの一覧(human/friend/upwatch の alerts.jsonl)へ書く。道具が途中で消えた(起こした PID が無いのに列が残る)ときはここで書く。
  列はそのまま残り、次の回にまた配る
- 配れたら: 道具が積んだ一言を latest.json と台帳の changes(この版で直したこと)に入れて、その分を列から外す(take)
- すぐ配る例外(種類 4 と、種類 2 の録画そのものが動かない直し)は `--publish --important --fix-kind 4|2`。列に積んだ物も一緒に乗る
- スイッチ: 環境変数 YTT_FRIEND_PUBLISH_QUEUE=0 で配る回を起こさない(積むのは続く)。リポジトリが無い PC(友人の PC)でも起こさない
標準ライブラリと ytt だけ。
"""
import datetime
import os
import subprocess
import time

from ytt import fsio, procs, tools
from . import upwatch as _upwatch

DIR = "friend-publish"
QUEUE_NAME, STATE_NAME, LOCK_NAME = "queue.json", "state.json", "queue.lock"
SLOT_HOURS = 3
RUN_MAX_SEC = 2 * 3600              # 配る道具(検査つき)がこれより長ければ、起こした PID を止める
SWITCH_ENV = "YTT_FRIEND_PUBLISH_QUEUE"
NOTE_MAX = 200
_running = {}                       # 起こした配る道具(pid → Popen)


def _dir(app_dir):
    return os.path.join(app_dir, DIR)


def _locked(app_dir, fn):
    lock = None
    for _ in range(50):
        lock = fsio.try_lock(os.path.join(_dir(app_dir), LOCK_NAME))
        if lock is not None:
            break
        time.sleep(0.1)
    try:
        return fn()
    finally:
        fsio.unlock(lock)


def items(app_dir):
    """積まれている物 [{at, note, version, by}](古い順)"""
    d = fsio.read_json_or(os.path.join(_dir(app_dir), QUEUE_NAME), None) or {}
    return [x for x in d.get("items") or [] if isinstance(x, dict)]


def _write(app_dir, rows):
    fsio.write_json(os.path.join(_dir(app_dir), QUEUE_NAME), {"v": 1, "items": rows})


def add(app_dir, note, version, by="", now=None):
    """列に 1 つ積む -> 積んだ物"""
    row = {"at": int((time.time() if now is None else now) * 1000), "note": str(note or "").strip()[:NOTE_MAX], "version": str(version or ""), "by": str(by or "")[:60]}
    os.makedirs(_dir(app_dir), exist_ok=True)
    _locked(app_dir, lambda: _write(app_dir, items(app_dir) + [row]))
    return row


def take(app_dir, until_ms):
    """配れた: until_ms までに積んだ物を列から外す -> 外した物"""
    def fn():
        rows = items(app_dir)
        _write(app_dir, [x for x in rows if (x.get("at") or 0) > until_ms])
        return [x for x in rows if (x.get("at") or 0) <= until_ms]
    return _locked(app_dir, fn)


def changes(rows):
    """この版で直したこと(積んだ一言の一覧。同じ一言は 1 つ・空は除く)"""
    return list(dict.fromkeys(x.get("note") for x in rows if x.get("note")))


def slot_of(t):
    """3 時間ごとの区切りの名前(ローカルの時刻 t 秒)"""
    d = datetime.datetime.fromtimestamp(t)
    return "%s-%02d" % (d.strftime("%Y%m%d"), d.hour // SLOT_HOURS * SLOT_HOURS)


def _alive(pid):
    p = _running.get(pid)
    if p is not None:
        if p.poll() is None:
            return True
        _running.pop(pid, None)
        return False
    return procs.pid_alive(pid)


def _spawn(cmd, cwd, out):
    with open(out, "ab") as f:
        return subprocess.Popen(cmd, cwd=cwd, stdin=subprocess.DEVNULL, stdout=f, stderr=subprocess.STDOUT,
                                creationflags=tools.no_window_flags(new_group=True, priority="low"))


def tick(app_dir, repo, clock=None, log=None, spawn=None):
    """見回りの 1 回: 区切りを越えて最初なら、列に積まれていれば配る道具を 1 回起こす -> 起こした {pid, started, slot} か None。
    失敗しても見回りは止めない(ログに 1 行)"""
    clock, log = clock or time.time, log or (lambda m: None)
    try:
        return _tick(app_dir, repo, clock, log, spawn)
    except Exception as e:   # noqa: BLE001  (配る回が壊れても依頼の受付は止めない)
        log("まとめて配る回でエラー: %s %s" % (e.__class__.__name__, str(e)[:200]))
        return None


def _tick(app_dir, repo, clock, log, spawn):
    sp = os.path.join(_dir(app_dir), STATE_NAME)
    st = fsio.read_json_or(sp, None) or {}
    now = clock()
    run = st.get("run")
    if run:
        if _alive(run.get("pid")):
            if now - (run.get("started") or now) <= RUN_MAX_SEC:
                return None
            if run["pid"] in _running:   # 自分が起こした物だけ止める(入口が起こし直した後の PID は止めずに記録だけ)
                tools.kill_tree(_running.pop(run["pid"]))
            log("友人の zip を配る道具を %d 分で打ち切りました(PID %s)" % (RUN_MAX_SEC // 60, run["pid"]))
        if any((x.get("at") or 0) <= run["started"] * 1000 for x in items(app_dir)):   # 終わったのに列が残る = 配れなかった
            _upwatch.add_alert(app_dir, "warn", "publish:%d" % run["started"], "まとめて配る回(%s)で友人の zip を配れませんでした。列は残しました(次の回にまた配ります)。記録: %s"
                               % (run.get("slot"), run.get("log")), now=now)
        st["run"] = None
        os.makedirs(_dir(app_dir), exist_ok=True)
        fsio.write_json(sp, st)
    slot = slot_of(now)
    first = "slot" not in st   # 初めての見回り = 区切りを越えたとは言えない(次の区切りから)
    if st.get("slot") == slot:
        return None
    st["slot"] = slot
    if first:
        os.makedirs(_dir(app_dir), exist_ok=True)
        fsio.write_json(sp, st)
        return None
    os.makedirs(_dir(app_dir), exist_ok=True)
    fsio.write_json(sp, st)
    if not items(app_dir) or os.environ.get(SWITCH_ENV, "1") == "0" or not repo:
        return None
    out = os.path.join(_dir(app_dir), "publish-%s.log" % slot)
    cmd = [tools.python_exe(), os.path.join(repo, "dev", "build_friend_zip.py"), "--publish", "--from-queue"]
    try:
        proc = (spawn or _spawn)(cmd, repo, out)
    except (OSError, subprocess.SubprocessError) as e:
        _upwatch.add_alert(app_dir, "warn", "publish-spawn:%s" % slot, "まとめて配る回(%s)で配る道具を起こせませんでした: %s" % (slot, str(e)[:200]), now=now)
        return None
    _running[proc.pid] = proc
    st["run"] = {"pid": proc.pid, "started": now, "slot": slot, "log": out}
    fsio.write_json(sp, st)
    log("まとめて配る回(%s): 列の %d 件で友人の zip を配ります(PID %d)" % (slot, len(items(app_dir)), proc.pid))
    return st["run"]
