"""友人のアプリの e2e(e2e_friend_send.py・e2e_friend_receive.py)の共通部品。玄関(friendapp.server の FriendApp + Server)を
このプロセスの中で一時フォルダに起こし、外に作用する口は全部偽物に替える:
  ② = FakeEngine(待ち行列 FakeQueue はテストが手で進める = 固定の sleep をしない・録画の部品 FakeLive)
  oEmbed(api.fetch)・配信中かの問い合わせ(api.probe)・配信の一覧(streams.view)・ファイルを選ぶ窓・フォルダを選ぶ窓・フォルダを開く(open_folder)・
  API キーの確かめ(settings.probe)。Dropbox の同期(app.sync)は鍵を置かない = 何もしない(裏の糸は起こさない)・窓(open_window)は開かない
音は出さない(chromium は --mute-audio)。作業データは一時フォルダ(places を組み立て直す)。
"""
import copy
import os
import subprocess
import sys
import tempfile
import threading
import time

os.environ.setdefault("YTT_DATA_DIR", "inplace")   # テストは作業データを本物の置き場所(AppData など)に書かない(ytt.datadir)

SRC = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)
from friendapp import server as S  # noqa: E402

CHANNEL = "テストちゃんねる"
WAIT = 20000        # 画面の待ち(ms)。固定の sleep はしない
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def check(cond, msg):
    print(("OK   " if cond else "FAIL ") + msg, flush=True)
    return bool(cond)


def wait_until(fn, sec=15.0, what="条件"):
    """fn() が真になるまで待つ(0.05 秒おきに見るだけ。固定の待ちではない)"""
    end = time.time() + sec
    while time.time() < end:
        v = fn()
        if v:
            return v
        time.sleep(0.05)
    raise AssertionError("待ちきれませんでした: " + what)


class FakeQueue:
    """② の待ち行列の偽物。submit は「順番待ち」で止まり、テストが start(rid) → finish(rid, packs) / fail(rid, text) で進める。
    kind live の依頼は録画の部品の結びつき({recorder, recording})を返す"""

    def __init__(self, inbox, cases):
        self.inbox, self.cases = inbox, cases
        self.runs = {}
        self.order = []
        self.lock = threading.Lock()

    def status(self):
        with self.lock:
            runs = [dict(r) for r in self.runs.values()]
        return {"idle": not runs, "runs": runs, "blocked": None}

    def submit(self, env, spec=None):
        rid = env["id"]
        with self.lock:
            self.runs[rid] = {"id": rid, "state": "queued", "stateLabel": "順番を待っています", "message": "", "steps": []}
            self.order.append(rid)
        if env.get("kind") == "live":
            return {"id": rid, "recorder": "rec-%s" % rid[-6:], "recording": "recording-%s" % rid[-6:], "existing": False}
        return {"id": rid, "state": "queued", "message": "順番を待っています", "steps": []}

    def latest(self):
        with self.lock:
            return self.order[-1] if self.order else None

    def start(self, rid, key="export"):
        """順番が来て作り始めた(段 = key。export なら友人の言葉で「切り抜き」)"""
        with self.lock:
            self.runs[rid].update(state="running", stateLabel="実行中", steps=[{"key": key, "state": "run", "detail": ""}])

    def finish(self, rid, packs=3, seconds=40.0):
        d = os.path.join(self.cases, rid)
        out = []
        for i in range(packs):
            p = os.path.join(d, "見どころ%d_pack" % (i + 1))
            os.makedirs(p, exist_ok=True)
            with open(os.path.join(p, "clip.mp4"), "wb") as f:
                f.write(b"\0" * 1024)
            out.append({"dir": p, "seconds": seconds + i})
        self.inbox.finished(rid, "done", "", out, case=d)
        with self.lock:
            self.runs.pop(rid, None)

    def fail(self, rid, text):
        self.inbox.finished(rid, "error", text, [])
        with self.lock:
            self.runs.pop(rid, None)

    def cancel(self, run_id):
        with self.lock:
            self.runs.pop(run_id, None)
        return {"id": run_id, "state": "cancelled"}

    def history(self, limit=None):
        return {"runs": []}

    def close(self):
        pass


class FakeLive:
    """録画の部品の偽物(録画は始めない・止める口は覚えるだけ)"""

    def __init__(self):
        self.stopped = []
        self.changed = []

    def active_count(self):
        return 0

    def stop_recording(self, recorder, recording):
        self.stopped.append((recorder, recording))

    def change_request(self, recorder, recording, rid, settings):
        self.changed.append((rid, settings))

    def start(self):
        pass

    def close(self):
        pass


class FakeEngine:
    """② の偽物(make_engine に渡す)。queue・live・_previews・status_map・close を持つ(dev/friend_demo.py の StubEngine と同じ形)"""

    def __init__(self, inbox, cases):
        self.queue = FakeQueue(inbox, cases)
        self.live = FakeLive()
        self._previews = []

    def status_map(self):
        st = self.queue.status()
        return {r["id"]: r for r in st["runs"]}, st

    def make_previews(self, rid):
        pass

    def close(self):
        pass


def make_places(tmp):
    home = os.path.join(tmp, "home")
    data = os.path.join(tmp, "data")
    save = os.path.join(tmp, "受け取ったパック")
    places = {"home": home, "data": data, "friend": os.path.join(data, "app", "friendapp"), "outbox": os.path.join(data, "app", "outbox"),
              "cases": os.path.join(tmp, "作業"), "save": lambda: save}
    for k in ("home", "friend", "outbox", "cases"):
        os.makedirs(places[k], exist_ok=True)
    return places, save


def make_mp4(path, sec=3):
    """確認用の動画の代わりの短い mp4(音なし)。ffmpeg が使えなければ False(確認用の動画なしの形だけ確かめる)。
    chromium(Playwright)は H.264 を再生できないので VP9 で(入れ物は mp4)"""
    ff = None
    try:
        from ytt import tools
        ff = tools.find_tool("ffmpeg")
    except Exception:  # noqa: BLE001
        ff = None
    if not ff:
        return False
    cmd = [ff, "-y", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc=size=160x90:rate=10:duration=%s" % sec, "-c:v", "libvpx-vp9",
           "-b:v", "50k", "-an", "-f", "mp4", path]
    try:
        subprocess.run(cmd, check=True, timeout=60, creationflags=NO_WINDOW, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception:  # noqa: BLE001
        return False
    return os.path.isfile(path) and os.path.getsize(path) > 0


class Rig:
    """一時フォルダに玄関を起こす。使い方: with Rig(prefix) as rig: rig.app / rig.base / rig.places / rig.save / rig.opened"""

    def __init__(self, prefix, oembed=None, probe=None):
        self.prefix, self.oembed, self.probe = prefix, oembed, probe
        self.srv = None

    def __enter__(self):
        self.tmp = tempfile.mkdtemp(prefix=self.prefix)
        self.places, self.save = make_places(self.tmp)
        app = S.FriendApp(self.places, make_engine=lambda pl, ib, log: FakeEngine(ib, pl["cases"]))
        app.prepare()                                        # 偽の ② を起こす
        app.api.fetch = self.oembed or (lambda vid: {"title": vid, "channel": CHANNEL})
        app.api.probe = self.probe or (lambda url: {"status": "was_live", "title": "", "channel": "", "message": ""})
        app.pick_file = lambda: None                         # ファイルを選ぶ窓は出さない
        app.pick_folder = lambda what: None                  # ⚙ のフォルダを選ぶ窓も出さない
        app.settings.probe = lambda key: (200, "{}")         # API キーの確かめでネットへ出ない
        self.opened = []
        app.open_folder = self.opened.append                 # エクスプローラーを開かない(画面を取らない)
        self.sections = []
        real = app.streams.view
        app.streams.view = lambda: dict(real(), updatedAt=int(time.time() * 1000), busy=False, first=False, error=None,
                                        sections=copy.deepcopy(self.sections))   # 配信の一覧は偽物(本物のネットに出ない)
        self.srv = S.Server(("127.0.0.1", 0), app)
        app.server = self.srv
        port = self.srv.server_address[1]
        threading.Thread(target=self.srv.serve_forever, kwargs={"poll_interval": 0.1}, daemon=True).start()
        self.app = app
        self.base = "http://localhost:%d/friend/" % port
        self.queue = app.engine.queue
        self.live = app.engine.live
        return self

    def __exit__(self, *exc):
        import shutil
        if self.srv is not None:
            self.srv.shutdown()
            self.srv.server_close()
        shutil.rmtree(self.tmp, ignore_errors=True)
        return False
