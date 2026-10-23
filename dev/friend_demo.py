# -*- coding: utf-8 -*-
"""友人の受信箱(src/friendapp)を見本のデータで動かす(画面の見直し・ui_audit・手での確認用)。本物の作業データ・② には触らない。

    py -3.12 dev/friend_demo.py [--port 8760] [--dir <作業フォルダ>]

一時フォルダ(--dir を指定すればそこ)をアプリのフォルダにし、受信箱に 送った・作っている・届いた(3 本 / 7 本)・失敗 の行と、
ユーザーの PC が自動で届けた 3 本(依頼なし)・ユーザーの PC に頼んだ行(受付待ち・作っている)を置く(Dropbox の同期の糸は起こさない)。
ライブの行(録画中・7 本届いた)と動画ファイルの行(届いた)。配信の題と「配信中か」は見本の値を返す(ネットへ出ない):
LIVE_URL を貼るとライブの 6 つの設定が出る。[動画ファイルを選ぶ] は本物の窓を開かず、見本の動画を選んだことにする。
② は疑似(StubEngine: 送った物を待ちに積むだけで処理しない)。Ctrl+C で終わる(一時フォルダは消す。--dir を指定したときは残す)。
⚙ の [選ぶ] は本物の窓を開かず見本のフォルダを選んだことにする・API キーの確かめはネットへ出ない(どのキーも「使えます」)。
--missing を付けると、初回の取得の部品が足りない形(見本の fetch.json)で起こす(ui_audit の friend-setup)。[始める] はネットへ出ず、少しずつ進んだことにする。
--update を付けると、今の版より 1 つ新しい版が入っている形(<home>/app-<版>/)で起こす = 帯に「新しい版 n があります [更新する]」(ui_audit の friend-update)。
[更新する] を押しても exe の無い見本は開き直しの案内だけ。
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


DEMO_PEOPLE = (("兎田ぺこら", "#65BAEA"), ("宝鐘マリン", "#B3223B"), ("白上フブキ", "#2CC7E4"), ("さくらみこ", "#FF4C8F"), ("星街すいせい", "#0F77E7"),
               ("戌神ころね", "#E0A800"), ("大空スバル", "#E1E11A"), ("猫又おかゆ", "#B28DF1"))
DEMO_STREAMS = (   # (状態, 始まりの「今から何分」, 長さの分, 題)。ui_audit が見る一覧(F3-2)
    ("live", -95, None, "【マイクラ】新しい拠点を作る!"), ("live", -20, None, "【雑談】寝る前にちょっとだけ"),
    ("upcoming", 40, None, "【歌枠】リクエスト歌枠"), ("upcoming", 300, None, "【APEX】ランク"),
    ("justEnded", -200, 150, "【朝活】おはよう!"), ("checking", -60, None, "【ゲーム】新作を遊ぶ"),
    ("ended", -320, 180, "【コラボ】4人で協力プレイ!"), ("ended", -500, 95, "【歌ってみた】の裏話"),
    ("ended", -24 * 60 - 120, 240, "【耐久】クリアするまで終われない"), ("ended", -24 * 60 - 400, 120, "【雑談】昨日の振り返り"),
    ("ended", -36 * 60, 13 * 60, "【24時間】長時間配信"))


def demo_thumb(hex_color):
    """見本のサムネ(色だけの SVG。ネットへ出ない・CSP の data: で読める)"""
    import urllib.parse
    svg = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 16 9"><defs><linearGradient id="g" x2="1" y2="1">'
           '<stop offset="0" stop-color="%s"/><stop offset="1" stop-color="#1b2030"/></linearGradient></defs><rect width="16" height="9" fill="url(#g)"/></svg>'
           % hex_color)
    return "data:image/svg+xml," + urllib.parse.quote(svg)


class DemoStreams:
    """配信の一覧の代わり(F3-2。ネットへ出ない。時刻は起動した時刻から作る)"""

    def __init__(self, clock=time.time):
        now = clock()
        self.at = int(now * 1000)
        items = []
        for i, (st, start, length, title) in enumerate(DEMO_STREAMS):
            who, hexc = DEMO_PEOPLE[i % len(DEMO_PEOPLE)]
            vid = "demo%07d" % (i + 1)
            s = int((now + start * 60) * 1000)
            items.append({"videoId": vid, "url": "https://www.youtube.com/watch?v=" + vid, "title": title, "channelId": "UCdemo%018d" % i,
                          "streamer": who, "hex": hexc, "thumb": demo_thumb(hexc), "state": st, "startAt": s,
                          "endAt": s + length * 60000 if length else None, "duration": length * 60 if length and st == "ended" else None})
        today = time.mktime(time.localtime(now)[:3] + (0, 0, 0, 0, 0, -1)) * 1000
        live = sorted([x for x in items if x["state"] in ("live", "upcoming")], key=lambda x: (x["state"] != "live", x["startAt"]))
        rest = sorted([x for x in items if x["state"] not in ("live", "upcoming")], key=lambda x: -x["startAt"])
        secs = [("live", "ライブ中・これから", live), ("today", "今日", [x for x in rest if x["startAt"] >= today]),
                ("yesterday", "昨日", [x for x in rest if x["startAt"] < today])]
        self.sections = [{"key": k, "label": lb, "count": len(xs), "items": xs} for k, lb, xs in secs if xs]

    def view(self):
        import json
        return {"updatedAt": self.at, "busy": False, "first": False, "error": None, "sections": json.loads(json.dumps(self.sections))}

    def refresh(self):
        self.at = int(time.time() * 1000)
        return {"ok": True}

    def lookup(self, vid):
        return next((dict(x) for s in self.sections for x in s["items"] if x["videoId"] == vid), None)

    def start(self):
        pass

    def stop(self):
        pass


DEMO_OVERLAP = "前に届けた切り抜きと区間が 8 割重なっています(20261015-210000-aaaa00__01_00h12m03s-00h14m10s・10-15 に届けた)"


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
            out.append(dict({"dir": d, "seconds": 60.0 + i * 15}, **({"info": {"overlapNote": DEMO_OVERLAP}} if i == 1 else {})))   # かぶり(新機能 E)の見本
        return out

    form = {"url": "https://www.youtube.com/watch?v=demo0000001", "videoId": "demo0000001", "ranges": [], "top": 5, "streamer": "星見ルナ",
            "people": [], "videoTracks": 1, "title": "", "channel": ""}
    rows = [("20261016-090000-aaaa01", TITLES[0], "demorun0001", "arrived", 3), ("20261016-091000-aaaa02", TITLES[1], "demorun0003", "arrived", 7),
            ("20261016-092000-aaaa03", TITLES[2], "demorun0004", "failed", 0), ("20261016-093000-aaaa04", TITLES[3], "demorun0002", "sent", 0),
            ("20261016-094000-aaaa05", "【雑談】夜ふかし", "demorun0005", "sent", 0)]
    for rid, title, run_id, st, n in rows:
        ib.add(rid, dict(form, title=title), {"url": form["url"], "videoId": form["videoId"], "title": title, "channel": "星見ルナ Ch."}, run_id=run_id)
        if st == "arrived":
            ib.finished(run_id, "done", "", packs(rid, n), case=os.path.join(case_root, rid))
        elif st == "failed":
            ib.finished(run_id, "error", "配信を取ってこられませんでした(配信が非公開か、まだ公開されていません)。少し待ってから [もう一度送る] を押してください", [])
    app.engine.queue.runs.append({"id": "demorun0005", "state": "queued", "message": "順番を待っています", "steps": []})
    # ユーザーの PC が自動で届けた 3 本(札「依頼なし」・Dropbox のパック = まだ手元に無い。1 本ずつ届く)と、ユーザーの PC に頼んだ行(受付待ち 2 時間・作っている)
    rid = "20261016-095000-bbbb01"
    for i in (1, 2, 3):
        ib.import_remote(rid, "auto", "【自動】朝活の見どころ", [{"preview": None, "previewSize": None, "packs": [
            {"zip": "%s__見どころ %d.zip" % (rid, i), "title": "見どころ %d" % i, "seconds": 40.0 + i, "size": 1024, "rev": "r%d" % i, "hash": None,
             "meta": "%s__見どころ %d.meta.json" % (rid, i)}]}])
    for rid, title, accepted in (("20261016-085000-cccc01", "【歌枠】ユーザーの PC に頼んだ", False), ("20261016-086000-cccc02", "【雑談】ユーザーの PC で作っている", True)):
        ib.add(rid, dict(form, title=title), {"url": form["url"], "videoId": form["videoId"], "title": title, "channel": "星見ルナ Ch."}, pc="user")
        ib.remote_mark(rid, "uploaded")
        if accepted:
            ib.remote_mark(rid, "accepted")
        else:
            with ib.lock:
                ib.row(rid)["remote"]["uploadedAt"] = int((now - 2 * 3600) * 1000)   # 2 時間待っている = [この PC でやり直す]
                ib._save()
    # ライブの行(録画中。7 本届いた)と動画ファイルの行(届いた)
    live_form = dict(form, url=LIVE_URL, videoId=LIVE_VID, kind="live", top=10,
                     live={"sens": "low", "perHour": 8, "length": 120, "waitMin": 10, "pad": 5.0, "afterStream": True})
    rid = "20261016-096000-dddd01"
    ib.add(rid, live_form, {"url": LIVE_URL, "videoId": LIVE_VID, "title": "【歌枠】ライブの見本", "channel": "星見ルナ Ch."}, kind="live")
    ib.live_started(rid, "local", "20261016-200000-" + LIVE_VID)
    for i, p in enumerate(packs(rid, 7)):
        ib.live_clip(rid, "demolive%02d" % i, "done", "", [p], "live", case=os.path.join(case_root, rid))
    ib.live_update(rid, True, False, hint="候補 2 件・約 4 分後に切り抜きます")   # 切り抜く前の候補の知らせ(live.hint)
    # アーカイブ待ちの行(終わったばかりの配信を送った)
    ib.add("20261016-098000-ffff01", dict(form, url="https://www.youtube.com/watch?v=demo0000005", videoId="demo0000005", kind="wait", title="【朝活】おはよう!"),
           {"url": "https://www.youtube.com/watch?v=demo0000005", "videoId": "demo0000005", "title": "【朝活】おはよう!", "channel": ""}, state="waiting")
    rid = "20261016-097000-eeee01"
    clip = os.path.join(home, "user", "Videos", "【星見ルナ】歌ってみた切り抜き.mp4")
    ib.add(rid, dict(form, kind="file", file={"path": clip, "name": os.path.basename(clip), "size": 1300000000}, title="【星見ルナ】歌ってみた切り抜き"),
           {"url": "", "videoId": "", "title": "【星見ルナ】歌ってみた切り抜き", "channel": "", "fileName": os.path.basename(clip), "fileSize": 1300000000},
           kind="file")
    ib.set_run(rid, "demorun0006")
    ib.finished("demorun0006", "done", "", packs(rid, 1), case=os.path.join(case_root, rid))


DEMO_FETCH = (("whisper.cpp/large-v3", "ggml-large-v3.bin", 3095033483, None, "data", "transcribe/models/whispercpp"),
              ("llama.cpp/b6000", "llama-bin-win-vulkan-x64.zip", 31457280, "zip", "data", "transcribe/bin/llama.cpp"),
              ("llm/qwen3-8b", "Qwen3-8B-Q4_K_M.gguf", 5027783488, None, "data", "transcribe/models/llm"),
              ("sensevoice/small", "sensevoice-small.tar.bz2", 241172480, "tar.bz2", "data", "transcribe/models/sensevoice"),
              ("ffmpeg", "ffmpeg-9.0.2-essentials_build.zip", 104857600, "zip", "app", "tools/ffmpeg"),
              ("yt-dlp", "yt-dlp.exe", 18874368, None, "app", "tools/yt-dlp"),
              ("deno", "deno-x86_64-pc-windows-msvc.zip", 47185920, "zip", "app", "tools/deno"))


def write_demo_fetch(home):
    """見本の fetch.json(大きさは本物に近い・取得先は見本 = 取らない)"""
    import json
    items = []
    for name, file, size, unzip, base, dest in DEMO_FETCH:
        it = {"name": name, "file": file, "url": "https://example.invalid/" + file, "size": size, "sha256": "0" * 64, "base": base, "dest": dest,
              "unzip": unzip}
        if unzip == "tar.bz2":
            it.update(top="sensevoice-small", parts=["model.onnx", "tokens.txt"])
        items.append(it)
    with open(os.path.join(home, "fetch.json"), "w", encoding="utf-8") as f:
        json.dump({"schema": "youtube-tools-friend-fetch/v1", "version": "demo", "items": items}, f, ensure_ascii=False)


class DemoDownloader:
    """[始める] の代わり(ネットへ出ない): 少しずつ進んだことにして、最後は中身が違うので取れなかったことにする"""

    def get(self, url, part, expect, progress, cancelled):
        from friendapp import setup as _setup
        for i in range(1, 21):
            if cancelled():
                raise _setup.Cancelled()
            progress(expect * i // 20)
            time.sleep(0.3)
        raise _setup.FetchError("見本なので取りません")


def demo_file(home):
    """[動画ファイルを選ぶ] の代わり(本物の窓を開かない): 見本の動画を作って、そのパスを返す"""
    p = os.path.join(home, "user", "Videos", "【星見ルナ】歌ってみた切り抜き.mp4")
    os.makedirs(os.path.dirname(p), exist_ok=True)
    if not os.path.isfile(p):
        with open(p, "wb") as f:
            f.write(b"\0" * 4096)
    return p


def write_demo_update(home):
    """--update: 今の版より 1 つ新しい版を <home>/app-<版>/ に入れた形にする(server.update_version が見る 2 つのファイルだけ。中身は空)。-> 版"""
    from ytt import version as V
    a, b, c = (int(x) for x in V.VERSION.split(".")[:3])
    ver = "%d.%d.%d" % (a, b, c + 1)
    for rel in (("src", "friendapp", "server.py"), ("python", "python.exe")):
        p = os.path.join(home, "app-" + ver, *rel)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        open(p, "ab").close()
    return ver


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8760)
    ap.add_argument("--dir")
    ap.add_argument("--missing", action="store_true", help="初回の取得の部品が足りない形で起こす")
    ap.add_argument("--update", action="store_true", help="新しい版が入っている形で起こす(帯の [更新する])")
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
    if a.missing:
        write_demo_fetch(home)
    if a.update:
        write_demo_update(home)
    key = os.path.join(home, "config.json")
    if not os.path.exists(key):   # 見本の鍵(形だけ。同期の糸は起こさない = Dropbox へつながない。あれば触らない)
        with open(key, "w", encoding="utf-8") as f:
            f.write('{"appKey": "demo", "refreshToken": "demo"}')
    pl = P.setup()
    pl["save"] = lambda: S.save_dir(pl["friend"])
    app = S.FriendApp(pl, log=lambda m: print(m, flush=True), make_engine=StubEngine)
    app.engine = StubEngine(pl, app.inbox)
    app.prep = {"state": "ready", "message": ""}
    app.api.fetch, app.api.probe = demo_fetch, demo_probe   # ネットへ出ない
    app.pick_file = lambda: demo_file(home)                  # 本物のファイルを選ぶ窓を開かない
    app.open_folder = lambda d: None                         # [保存先を開く] でエクスプローラーを開かない(画面を取らない)
    picked = os.path.join(home, "user", "見本のフォルダ")
    app.pick_folder = lambda what: picked                    # ⚙ の [選ぶ] で本物の窓を開かない
    app.settings.probe = lambda key: (200, "{}")             # API キーの確かめでネットへ出ない
    app.setup.downloader = DemoDownloader()                  # [始める] でネットへ出ない
    app.setup.disk_usage = lambda path: shutil.disk_usage(home)._replace(free=200 * 1024 ** 3)   # 見本は空きが足りる形
    app.setup.run = lambda cmd, timeout: (0, "demo 1.0", None)   # 道具の確かめで本物の道具を動かさない
    app.setup.whisper = lambda device, data_root, wav: None
    app.setup.set_device = lambda d: None
    app.setup.env = {}
    app.setup.log = lambda m: None                           # 準備の流れのログは出さない(ui_audit は起動の 1 行のあと標準出力を読まない = 詰まる)
    app.setup.start()                                        # 見本は古い部品を写さない。fetch.json が無ければすぐ済み・--missing は準備だけの画面
    app.streams = DemoStreams()                              # 配信の一覧(F3-2)はネットへ出ない
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
