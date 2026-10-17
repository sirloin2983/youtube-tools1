#!/usr/bin/env python3
"""友人の受信箱の通し確認(Playwright の chromium・headless)。玄関(friendapp.server の FriendApp + Server)を
このプロセスの中で一時フォルダに起こし、画面(/friend/)を実際に操作する。リポジトリ直下で:

    set PYTHONIOENCODING=utf-8
    py -3.10 src/friendapp/tests/e2e_friend_inbox.py

流れ 1: URL を貼る → 題が出る → 区間を 1 つ(数字だけで打つ・Enter で次の欄)→ [送る] → 送った物 → 届く(●3)→ [受け取る] の段 → 再生画面で
        [受け取る](保存先 = <日付>_<配信者>_<題> の中の #1)→ 自動で次 → [見送る] → 知らせの [戻す] → 一覧でチェック 2 本 → まとめて見送る → 判断の記録 v2
流れ 2: 失敗(上の段 = 友人の言葉)→ [もう一度送る] → 届く・Esc で送る欄を閉じる

外に作用する口は偽物に替える(本物のネット・Dropbox・エクスプローラー・Edge・ファイルを選ぶ窓は出さない):
  ② = FakeEngine(送った依頼を少し後に「作っている」→ 一時フォルダにパックのフォルダを 3 本作って inbox.finished。fail_next 回は「止まった」で終わる)
  oEmbed(api.fetch)・配信中かの問い合わせ(api.probe)・ファイルを選ぶ(app.pick_file)・フォルダを開く(app.open_folder)
  Dropbox の同期(app.sync)は鍵を置かない = 何もしない(裏の糸は起こさない。loop も起こさない)・窓(app.open_window)は開かない
作業データは一時フォルダ(places を組み立て直す = places.setup() を通さない)。待ちは固定の sleep でなく「表示されるまで待つ」。
"""
import json
import os
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
            self.inbox.finished(rid, "error", "この動画は非公開です(テストの偽物)", [], 5)
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
                expect(pg.locator("#formEmpty")).to_be_visible(timeout=WAIT)

                # 流れ 1: URL を貼る → 区間を 1 つ → 送る → 送った物 → 届く(●3)
                pg.fill("#url", URL_A)
                pg.press("#url", "Enter")
                expect(pg.locator("#headTitle")).to_have_text(TITLE_A, timeout=WAIT)
                expect(pg.locator("#btnSend")).to_be_enabled(timeout=WAIT)
                ok &= check(True, "URL を貼ると送る欄に題が出て [送る] が押せる")
                pg.locator(".fr-range .ui-time").nth(0).click()
                pg.keyboard.type("01230")
                pg.keyboard.press("Enter")   # 次の欄へ
                pg.keyboard.type("01500")
                expect(pg.locator(".fr-range-said").first).to_contain_text("12分30秒 〜 15分00秒(2分30秒)", timeout=WAIT)
                ok &= check(pg.locator("#topLine").is_hidden(), "区間を入れると読み取った結果が出て、本数の欄が消える")
                pg.click("#btnSend")
                expect(pg.locator("#formEmpty")).to_be_visible(timeout=WAIT)
                row = pg.locator(".fr-sent-row", has_text=TITLE_A).first
                expect(row).to_be_visible(timeout=WAIT)
                ok &= check(True, "[送る] の後、送る欄が閉じて「送った物」に行が出る")
                sent = app.inbox.rows[0]["form"]
                ok &= check([list(x) for x in sent["ranges"]] == [[750.0, 900.0]] and sent["top"] is None, "区間が依頼に入る(C-0 の「区間が捨てられる」の直し)")
                expect(pg.locator(".fr-sent-row", has_text=TITLE_A)).to_have_count(0, timeout=WAIT * 2)
                expect(pg.locator("#tabN")).to_have_text(str(PACKS), timeout=WAIT)
                ok &= check(True, "届くと送った物から消え、[受け取る] に ●%d" % PACKS)

                # 受け取る: 配信の段 → 再生画面 → [受け取る](保存先の形)→ 自動で次 → [見送る] → [戻す] → まとめて見送る
                pg.click("#tabReceive")
                sec = pg.locator(".fr-rsec", has_text=TITLE_A).first
                expect(sec.locator(".fr-rcard")).to_have_count(PACKS, timeout=WAIT)
                ok &= check(True, "配信の段に %d 本" % PACKS)
                sec.locator(".fr-rcard-btn").first.click()
                expect(pg.locator("#playerTitle")).to_contain_text("#1", timeout=WAIT)
                pg.click("#btnKeep")
                expect(pg.locator("#playerTitle")).to_contain_text("#2", timeout=WAIT)
                folders = os.listdir(save) if os.path.isdir(save) else []
                ok &= check(len(folders) == 1 and TITLE_A in folders[0] and os.path.isdir(os.path.join(save, folders[0], "#1")),
                            "[受け取る] で保存先の <日付>_<配信者>_<題> の中の #1 に入り、自動で #2 へ: %s" % folders)
                pg.click("#btnSkip")
                expect(pg.locator("#playerTitle")).to_contain_text("#3", timeout=WAIT)
                pg.locator("#toast").get_by_role("button", name="戻す").click()
                expect(pg.locator("#playerList .fr-rcard")).to_have_count(2, timeout=WAIT)
                ok &= check(True, "[見送る] で #3 へ・知らせの [戻す] で #2 が戻る")
                pg.keyboard.press("Escape")
                expect(pg.locator("#rcvList")).to_be_visible(timeout=WAIT)
                for cb in sec.locator(".fr-pick").all():
                    cb.check()
                expect(pg.locator("#bulkBar")).to_be_visible(timeout=WAIT)
                pg.click("#bulkSkip")
                expect(pg.locator(".fr-rsec", has_text=TITLE_A)).to_have_count(0, timeout=WAIT)
                expect(pg.locator("#rcvSkipList li")).to_have_count(2, timeout=WAIT)
                ok &= check(pg.locator("#tabN").is_hidden(), "まとめて見送ると段が消え、見送った物に 2 本・●が消える")

                judges = []
                for n in sorted(os.listdir(places["outbox"])):
                    if n.endswith(".verdict.json"):
                        with open(os.path.join(places["outbox"], n), encoding="utf-8") as f:
                            d = json.load(f)
                        judges.append(d["judge"] if d.get("v") == 2 else "v1")
                ok &= check(sorted(judges) == ["good", "retract", "unknown", "unknown", "unknown"], "判断の記録 v2(受け取る 1・見送る 3・戻す 1): %s" % judges)

                # 流れ 2: 失敗(2 段)→ [もう一度送る] → 届く・Esc で送る欄を閉じる
                app.engine.queue.fail_next = 1
                pg.click("#tabSend")
                pg.fill("#url", URL_B)
                pg.press("#url", "Enter")
                expect(pg.locator("#headTitle")).to_have_text(TITLE_B, timeout=WAIT)
                expect(pg.locator("#btnSend")).to_be_enabled(timeout=WAIT)
                pg.click("#btnSend")
                row = pg.locator(".fr-sent-row", has_text=TITLE_B).first
                expect(row.locator(".fr-fail-top")).to_be_visible(timeout=WAIT * 2)
                ok &= check("見られません" in row.locator(".fr-fail-top").text_content(), "失敗は友人の言葉で次にすることを 1 つ(上の段)")
                row.get_by_role("button", name="もう一度送る").click()
                expect(pg.locator("#tabN")).to_have_text(str(PACKS), timeout=WAIT * 2)
                ok &= check(True, "[もう一度送る] で届いた")
                pg.fill("#url", URL_A)
                pg.press("#url", "Enter")
                expect(pg.locator("#formStream")).to_be_visible(timeout=WAIT)
                pg.locator("#headTitle").click()
                pg.keyboard.press("Escape")
                expect(pg.locator("#formEmpty")).to_be_visible(timeout=WAIT)
                ok &= check(True, "Esc で送る欄を閉じる")

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
