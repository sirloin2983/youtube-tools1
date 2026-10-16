# -*- coding: utf-8 -*-
"""友人の受信箱(src/friendapp)を見本のデータで動かす(画面の見直し・ui_audit・手での確認用)。本物の作業データ・② には触らない。

    py -3.10 dev/friend_demo.py [--port 8760] [--dir <作業フォルダ>]

一時フォルダ(--dir を指定すればそこ)をアプリのフォルダにし、受信箱に 送った・作っている・届いた(1 組 / 2 組)・失敗 の行と、
ユーザーの PC が自動で届けた組(依頼なし)・ユーザーの PC に頼んだ行(受付待ち・作っている)を置く(F2-3。Dropbox の同期の糸は起こさない)。
F2-6: ライブの行(録画中・1 組届いて 2 本が組になるのを待っている)と動画ファイルの行(届いた)。配信の題と「配信中か」は見本の値を返す(ネットへ出ない):
LIVE_URL を貼るとライブの 6 つの設定が出る。[動画ファイルを選ぶ] は本物の窓を開かず、見本の動画を選んだことにする。
② は疑似(StubEngine: 送った物を待ちに積むだけで処理しない)。Ctrl+C で終わる(一時フォルダは消す。--dir を指定したときは残す)。
"""
import argparse
import os
import shutil
import sys
import tempfile
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(os.path.dirname(HERE), "src")
sys.path.insert(0, SRC)

TITLES = ["【雑談】朝活 120 回目!", "【APEX】ランクでダイヤ目指す", "【歌枠】リクエストいっぱい歌う", "【コラボ】4人で協力プレイ!"]
LIVE_VID = "demolive001"
LIVE_URL = "https://www.youtube.com/watch?v=" + LIVE_VID   # 貼ると「配信中」(ui_audit の friend-live)


def demo_fetch(vid):
    """oEmbed の代わり(見本の題。ネットへ出ない)"""
    return {"title": "【歌枠】ライブの見本" if vid == LIVE_VID else "見本の配信", "channel": "星見ルナ Ch."}


def demo_probe(url):
    """配信中かの代わり(LIVE_VID だけ配信中)"""
    return {"status": "is_live" if LIVE_VID in url else "was_live", "title": "", "channel": "", "message": ""}


class StubQueue:
    def __init__(self):
        self.runs = []

    def status(self):
        return {"idle": not any(r["state"] in ("queued", "running") for r in self.runs), "runs": list(self.runs), "blocked": None}

    def submit(self, env, spec=None):
        r = {"id": env["id"], "state": "queued", "message": "順番を待っています", "steps": []}
        self.runs.append(r)
        return r

    def cancel(self, run_id):
        for r in self.runs:
            if r["id"] == run_id:
                r["state"] = "cancelled"
        return {"ok": True}

    def history(self, limit=None):
        return {"runs": []}

    def close(self):
        pass


class StubEngine:
    def __init__(self, places, inbox, log=None):
        self.queue = StubQueue()
        self._previews = []
        self.queue.runs.append({"id": "demorun0002", "state": "running", "stateLabel": "実行中", "message": "",
                                "steps": [{"key": "export", "label": "書き出し", "state": "done"},
                                          {"key": "transcribe", "label": "文字起こし", "state": "run", "detail": "42%"}]})

    def status_map(self):
        st = self.queue.status()
        return {r["id"]: r for r in st["runs"]}, st

    def close(self):
        pass


def seed(app, home):
    ib = app.inbox
    now = time.time()
    case_root = app.places["cases"]

    def packs(rid, n):
        out = []
        for i in range(n):
            d = os.path.join(case_root, rid, "【見本】%s %d_pack" % (rid[-4:], i + 1))
            os.makedirs(d, exist_ok=True)
            with open(os.path.join(d, "clip.mp4"), "wb") as f:
                f.write(b"\0" * 1024)
            out.append({"dir": d, "seconds": 60.0 + i * 15})
        return out

    form = {"url": "https://www.youtube.com/watch?v=demo0000001", "videoId": "demo0000001", "ranges": [], "top": 5, "streamer": "星見ルナ",
            "people": [], "videoTracks": 1, "deliverBatch": 5, "useWeights": False, "weights": None, "title": "", "channel": ""}
    rows = [("20261016-090000-aaaa01", TITLES[0], "demorun0001", "arrived", 3), ("20261016-091000-aaaa02", TITLES[1], "demorun0003", "arrived", 7),
            ("20261016-092000-aaaa03", TITLES[2], "demorun0004", "failed", 0), ("20261016-093000-aaaa04", TITLES[3], "demorun0002", "sent", 0),
            ("20261016-094000-aaaa05", "【雑談】夜ふかし", "demorun0005", "sent", 0)]
    for rid, title, run_id, st, n in rows:
        ib.add(rid, dict(form, title=title), {"url": form["url"], "videoId": form["videoId"], "title": title, "channel": "星見ルナ Ch."}, run_id=run_id)
        if st == "arrived":
            ib.finished(run_id, "done", "", packs(rid, n), 5, case=os.path.join(case_root, rid))
        elif st == "failed":
            ib.finished(run_id, "error", "配信を取ってこられませんでした(配信が非公開か、まだ公開されていません)。少し待ってから [もう一度送る] を押してください", [], 5)
    app.engine.queue.runs.append({"id": "demorun0005", "state": "queued", "message": "順番を待っています", "steps": []})
    # F2-3: ユーザーの PC が自動で届けた組(札「依頼なし」・Dropbox のパック = まだ手元に無い)と、ユーザーの PC に頼んだ行(受付待ち 2 時間・作っている)
    rid = "20261016-095000-bbbb01"
    ib.import_remote(rid, "auto", "【自動】朝活の見どころ", [{"group": rid + "__朝活 1-3.group.json", "preview": None, "previewSize": None, "packs": [
        {"zip": "%s__見どころ %d.zip" % (rid, i), "title": "見どころ %d" % i, "seconds": 40.0 + i, "size": 1024, "rev": "r%d" % i, "hash": None, "meta": None}
        for i in (1, 2, 3)]}])
    for rid, title, accepted in (("20261016-085000-cccc01", "【歌枠】ユーザーの PC に頼んだ", False), ("20261016-086000-cccc02", "【雑談】ユーザーの PC で作っている", True)):
        ib.add(rid, dict(form, title=title), {"url": form["url"], "videoId": form["videoId"], "title": title, "channel": "星見ルナ Ch."}, pc="user")
        ib.remote_mark(rid, "uploaded")
        if accepted:
            ib.remote_mark(rid, "accepted")
        else:
            with ib.lock:
                ib.row(rid)["remote"]["uploadedAt"] = int((now - 2 * 3600) * 1000)   # 2 時間待っている = [この PC でやり直す]
                ib._save()
    # F2-6: ライブの行(録画中。5 本の 1 組が届き、2 本が組になるのを待っている)と動画ファイルの行(届いた)
    live_form = dict(form, url=LIVE_URL, videoId=LIVE_VID, kind="live", top=10,
                     live={"sens": "low", "perHour": 8, "length": 120, "waitMin": 10, "pad": 5.0, "afterStream": True})
    rid = "20261016-096000-dddd01"
    ib.add(rid, live_form, {"url": LIVE_URL, "videoId": LIVE_VID, "title": "【歌枠】ライブの見本", "channel": "星見ルナ Ch."}, kind="live")
    ib.live_started(rid, "local", "20261016-200000-" + LIVE_VID)
    for i, p in enumerate(packs(rid, 7)):
        ib.live_clip(rid, "demolive%02d" % i, "done", "", [p], "live", case=os.path.join(case_root, rid))
    rid = "20261016-097000-eeee01"
    clip = os.path.join(home, "user", "Videos", "【星見ルナ】歌ってみた切り抜き.mp4")
    ib.add(rid, dict(form, kind="file", file={"path": clip, "name": os.path.basename(clip), "size": 1300000000}, title="【星見ルナ】歌ってみた切り抜き"),
           {"url": "", "videoId": "", "title": "【星見ルナ】歌ってみた切り抜き", "channel": "", "fileName": os.path.basename(clip), "fileSize": 1300000000},
           kind="file")
    ib.set_run(rid, "demorun0006")
    ib.finished("demorun0006", "done", "", packs(rid, 1), 5, case=os.path.join(case_root, rid))


def demo_file(home):
    """[動画ファイルを選ぶ] の代わり(本物の窓を開かない): 見本の動画を作って、そのパスを返す"""
    p = os.path.join(home, "user", "Videos", "【星見ルナ】歌ってみた切り抜き.mp4")
    os.makedirs(os.path.dirname(p), exist_ok=True)
    if not os.path.isfile(p):
        with open(p, "wb") as f:
            f.write(b"\0" * 4096)
    return p


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8760)
    ap.add_argument("--dir")
    a = ap.parse_args(argv)
    tmp_root = tempfile.gettempdir()
    for n in os.listdir(tmp_root):   # 前の見本の残り(ui_audit が止めると finally を通らない)を消す
        p = os.path.join(tmp_root, n)
        if n.startswith("friend-demo-") and os.path.isdir(p) and time.time() - os.path.getmtime(p) > 600:
            shutil.rmtree(p, ignore_errors=True)
    home = os.path.abspath(a.dir) if a.dir else tempfile.mkdtemp(prefix="friend-demo-")
    os.makedirs(home, exist_ok=True)
    os.environ.update(YTT_FRIEND_HOME=home, YTT_DATA_DIR=os.path.join(home, "data"), LOCALAPPDATA=os.path.join(home, "localappdata"),
                      USERPROFILE=os.path.join(home, "user"), TRANSCRIBE_BACKEND="fake", STUDIO_FAKE="1")
    from friendapp import places as P, server as S
    key = os.path.join(home, "config.json")
    if not os.path.exists(key):   # 見本の鍵(形だけ。同期の糸は起こさない = Dropbox へつながない。あれば触らない)
        with open(key, "w", encoding="utf-8") as f:
            f.write('{"appKey": "demo", "refreshToken": "demo"}')
    pl = P.setup()
    pl["save"] = lambda: S.save_dir(pl["friend"])
    app = S.FriendApp(pl, log=lambda m: print(m, flush=True), make_engine=StubEngine)
    app.engine = StubEngine(pl, app.inbox)
    app.prep = {"state": "ready", "message": ""}
    app.api.fetch, app.api.probe = demo_fetch, demo_probe   # ネットへ出ない(F2-6)
    app.pick_file = lambda: demo_file(home)                  # 本物のファイルを選ぶ窓を開かない
    if not app.inbox.rows:
        seed(app, home)
    srv = S.Server(("127.0.0.1", a.port), app)
    app.server = srv
    print("見本の受信箱: http://localhost:%d/friend/(%s)" % (a.port, home), flush=True)
    try:
        srv.serve_forever(poll_interval=0.5)
    except KeyboardInterrupt:
        pass
    finally:
        srv.server_close()
        if not a.dir:
            shutil.rmtree(home, ignore_errors=True)
    return 0


if __name__ == "__main__":
    threading.current_thread().name = "friend-demo"
    sys.exit(main())
