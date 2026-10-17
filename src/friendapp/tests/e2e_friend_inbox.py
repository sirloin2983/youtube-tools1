#!/usr/bin/env python3
"""友人の受信箱の通し確認(Playwright の chromium・headless)。玄関(friendapp.server の FriendApp + Server)を
このプロセスの中で一時フォルダに起こし、画面(/friend/)を実際に操作する。リポジトリ直下で:

    set PYTHONIOENCODING=utf-8
    py -3.10 src/friendapp/tests/e2e_friend_inbox.py

流れ 1: URL を貼る → 題が出る → [送る] → 行が「送った」→「作っている」→「届いた」→ 行を開く → 1 本 [受け取る](保存先 = 一時フォルダ)
        → 残りを [要らない](確認 → ごみ箱 = 一時フォルダ)→ 行が消える → 送り返し(outbox)に .verdict.json が 1 本ずつ
流れ 2: 失敗の行の [もう一度送る] → 届いた

外に作用する口は偽物に替える(本物のネット・Dropbox・エクスプローラー・Edge・ファイルを選ぶ窓は出さない):
  ② = FakeEngine(送った依頼を少し後に「作っている」→ 一時フォルダにパックのフォルダを 3 本作って inbox.finished。fail_next 回は「止まった」で終わる)
  oEmbed(api.fetch)・配信中かの問い合わせ(api.probe)・ファイルを選ぶ(app.pick_file)・フォルダを開く(app.open_folder)
  Dropbox の同期(app.sync)は鍵を置かない = 何もしない(裏の糸は起こさない。loop も起こさない)・窓(app.open_window)は開かない
作業データは一時フォルダ(places を組み立て直す = places.setup() を通さない)。待ちは固定の sleep でなく「表示されるまで待つ」。
"""
import json
import os
import re
import shutil
import sys
import tempfile
import threading
import time

os.environ.setdefault("YTT_DATA_DIR", "inplace")   # テストは作業データを本物の置き場所(AppData など)に書かない(ytt.datadir)
from playwright.sync_api import expect, sync_playwright  # noqa: E402

SRC = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if SRC not in sys.path:
    sys.path.insert(0, SRC)
from friendapp import server as S  # noqa: E402

URL_A = "https://www.youtube.com/watch?v=e2eFriend01"
URL_B = "https://www.youtube.com/watch?v=e2eFriend02"
TITLE_A, TITLE_B = "テストの配信 1", "テストの配信 2"
CHANNEL = "テストちゃんねる"
QUEUED_SEC = 2.5    # 「送った」のまま待つ秒(偽の ②)
WORK_SEC = 2.0      # 「作っている」の秒
PACKS = 3           # 届く本数
WAIT = 20000        # 画面の待ち(ms)。固定の sleep はしない


def check(cond, msg):
    print(("OK   " if cond else "FAIL ") + msg, flush=True)
    return bool(cond)


class FakeQueue:
    """② の待ち行列の偽物。submit は「送った」(待ち)→「作っている」→ 一時フォルダのパックで inbox.finished(届いた)。
    fail_next 回は「止まった」(パックなし = 失敗の行)で終わる"""

    def __init__(self, inbox, cases):
        self.inbox, self.cases = inbox, cases
        self.runs = {}
        self.fail_next = 0
        self.lock = threading.Lock()

    def status(self):
        with self.lock:
            runs = [dict(r) for r in self.runs.values()]
        return {"idle": not runs, "runs": runs, "blocked": None}

    def submit(self, env, spec=None):
        rid = env["id"]
        with self.lock:
            fail = self.fail_next > 0
            if fail:
                self.fail_next -= 1
            self.runs[rid] = {"id": rid, "state": "queued", "stateLabel": "順番を待っています", "message": "", "steps": []}
        threading.Thread(target=self._run, args=(rid, fail), daemon=True).start()
        return {"id": rid, "state": "queued", "message": "順番を待っています", "steps": []}

    def _run(self, rid, fail):
        time.sleep(QUEUED_SEC)
        with self.lock:
            self.runs[rid].update(state="running", stateLabel="実行中")
        time.sleep(WORK_SEC)
        if fail:
            self.inbox.finished(rid, "error", "配信を取ってこられませんでした(テストの偽物)", [], 5)
        else:
            d = os.path.join(self.cases, rid)
            packs = []
            for i in range(PACKS):
                p = os.path.join(d, "見どころ%d_pack" % (i + 1))
                os.makedirs(p, exist_ok=True)
                with open(os.path.join(p, "clip.mp4"), "wb") as f:
                    f.write(b"\0" * 1024)
                packs.append({"dir": p, "seconds": 40.0 + i})
            self.inbox.finished(rid, "done", "", packs, 5, case=d)
        with self.lock:
            self.runs.pop(rid, None)

    def cancel(self, run_id):
        return {"id": run_id, "state": "cancelled"}

    def history(self, limit=None):
        return {"runs": []}

    def close(self):
        pass


class FakeEngine:
    """② の偽物(make_engine に渡す)。queue・_previews・status_map・close を持つ(dev/friend_demo.py の StubEngine と同じ形)"""

    def __init__(self, inbox, cases):
        self.queue = FakeQueue(inbox, cases)
        self._previews = []

    def status_map(self):
        st = self.queue.status()
        return {r["id"]: r for r in st["runs"]}, st

    def close(self):
        pass


def fake_oembed(vid):
    """oEmbed の代わり(ネットへ出ない)"""
    return {"title": TITLE_B if vid.endswith("02") else TITLE_A, "channel": CHANNEL}


def fake_probe(url):
    """配信中かの代わり(ネットへ出ない。普通の動画として送る)"""
    return {"status": "was_live", "title": "", "channel": "", "message": ""}


def make_places(tmp):
    home = os.path.join(tmp, "home")
    data = os.path.join(tmp, "data")
    save = os.path.join(tmp, "受け取ったパック")
    places = {"home": home, "data": data, "friend": os.path.join(data, "app", "friendapp"), "outbox": os.path.join(data, "app", "outbox"),
              "cases": os.path.join(tmp, "作業"), "save": lambda: save}
    for k in ("home", "friend", "outbox", "cases"):
        os.makedirs(places[k], exist_ok=True)
    return places, save


def pack_row(pg, title):
    return pg.locator(".fr-row", has_text=title).first


def pack_item(pg, title):
    return pg.locator(".fr-item", has_text=title).first


def pill_text(row):
    return row.locator(".pill").first.text_content().strip()


def main():
    tmp = tempfile.mkdtemp(prefix="ytt-friend-inbox-e2e-")
    ok = True
    srv = None
    try:
        places, save = make_places(tmp)
        app = S.FriendApp(places, make_engine=lambda pl, ib, log: FakeEngine(ib, pl["cases"]))
        app.prepare()                                        # 偽の ② を起こす(古い部品の写しは無い = old_root なし)
        app.api.fetch, app.api.probe = fake_oembed, fake_probe
        app.pick_file = lambda: None                         # ファイルを選ぶ窓は出さない
        app.pick_folder = lambda what: None                  # ⚙ のフォルダを選ぶ窓も出さない(F2-5)
        app.settings.probe = lambda key: (200, "{}")         # API キーの確かめでネットへ出ない(F2-5)
        opened = []
        app.open_folder = opened.append                       # エクスプローラーを開かない(画面を取らない)
        srv = S.Server(("127.0.0.1", 0), app)
        app.server = srv
        port = srv.server_address[1]
        threading.Thread(target=srv.serve_forever, kwargs={"poll_interval": 0.1}, daemon=True).start()
        base = "http://localhost:%d/friend/" % port

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            try:
                pg = browser.new_page(viewport={"width": 1000, "height": 800})
                errors = []
                pg.on("pageerror", lambda e: errors.append(str(e)))
                pg.goto(base)
                expect(pg.locator("#btnSend")).to_be_visible(timeout=WAIT)
                ok &= check(pg.locator("#btnSend").is_disabled(), "URL が無いうちは [送る] が押せない")

                # 流れ 1: 送る
                pg.fill("#url", URL_A)
                expect(pg.locator("#peek")).to_contain_text(TITLE_A, timeout=WAIT)
                expect(pg.locator("#btnSend")).to_be_enabled(timeout=WAIT)
                ok &= check(CHANNEL in pg.locator("#peek").text_content(), "貼った URL の題とチャンネル名が出る")
                pg.click("#btnSend")
                pg.click("#tabReceive")   # 届いた物は [受け取る] の画面(F3)
                row = pack_row(pg, TITLE_A)
                expect(row).to_be_visible(timeout=WAIT)
                expect(row.locator(".pill").first).to_have_text("送った", timeout=WAIT)
                ok &= check(True, "[送る] の後、行が「送った」")
                expect(row.locator(".pill").first).to_have_text("作っている", timeout=WAIT)
                ok &= check(True, "行が「作っている」になる")
                expect(row.locator(".pill").first).to_have_text("届いた", timeout=WAIT)
                ok &= check(True, "行が「届いた」になる")

                item = pack_item(pg, TITLE_A)
                row.get_by_role("button", name="開く").click()
                expect(item.locator("li.fr-pack")).to_have_count(PACKS, timeout=WAIT)
                ok &= check(True, "行を開くと %d 本のパックが並ぶ" % PACKS)
                item.locator("li.fr-pack").nth(0).get_by_role("button", name="受け取る").click()
                expect(item.locator("li.fr-pack").nth(0)).to_contain_text("受け取った", timeout=WAIT)
                ok &= check(os.path.isdir(os.path.join(save, "見どころ1_pack")), "[受け取る] で 1 本目が保存先へ移った")
                # 残り 2 本を [要らない](確認の窓 → ごみ箱へ)
                for cb in item.locator("input[type=checkbox]:not([disabled])").all():
                    cb.check()
                item.get_by_role("button", name=re.compile("選んだ 2 本を要らない")).click()
                dlg = pg.locator("dialog[open]")
                expect(dlg).to_be_visible(timeout=WAIT)
                dlg.get_by_role("button", name="要らない").click()
                expect(pg.locator(".fr-row", has_text=TITLE_A)).to_have_count(0, timeout=WAIT)
                ok &= check(True, "残りを要らないにすると、行が消える")

                verdicts = []
                for n in sorted(os.listdir(places["outbox"])):
                    if n.endswith(".verdict.json"):
                        with open(os.path.join(places["outbox"], n), encoding="utf-8") as f:
                            verdicts.append(json.load(f)["verdict"])
                ok &= check(sorted(verdicts) == ["keep", "reject", "reject"], "outbox に .verdict.json が 1 本ずつ(受け取る 1・要らない 2)")
                saved = sorted(os.listdir(save)) if os.path.isdir(save) else []
                ok &= check(saved == ["見どころ1_pack"], "保存先には受け取った 1 本だけ(要らない 2 本は保存先に入らない)")

                # 流れ 2: 失敗 → [もう一度送る]
                app.engine.queue.fail_next = 1
                pg.click("#tabSend")
                pg.fill("#url", URL_B)
                expect(pg.locator("#peek")).to_contain_text(TITLE_B, timeout=WAIT)
                expect(pg.locator("#btnSend")).to_be_enabled(timeout=WAIT)
                pg.click("#btnSend")
                pg.click("#tabReceive")
                row = pack_row(pg, TITLE_B)
                expect(row.locator(".pill").first).to_have_text("失敗", timeout=WAIT * 2)
                ok &= check(True, "止まった依頼の行が「失敗」(理由つき)")
                row.get_by_role("button", name="もう一度送る").click()
                expect(pack_row(pg, TITLE_B).locator(".pill").first).to_have_text("届いた", timeout=WAIT * 2)
                ok &= check(True, "[もう一度送る] で届いた")

                ok &= check(not errors, "画面にエラー(pageerror)が出ていない%s" % ("" if not errors else ": " + errors[0][:120]))
            finally:
                browser.close()
    finally:
        if srv is not None:
            srv.shutdown()
            srv.server_close()
        shutil.rmtree(tmp, ignore_errors=True)
    print("OK" if ok else "FAIL", flush=True)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
