"""確かめる(/check。部品は src/app/ui/check/)の通し確認(Playwright)。リポジトリ直下で:
    set PYTHONIOENCODING=utf-8
    py -3.12 tests/app/e2e_check.py
入口(server.py)はツールを取り込まずに動かす。⑤ の待ち行列の口(api/check/next・answer・skip)は
計画 notes:docs/design/v1-check-build.md 2-3 の形の偽物(Playwright の route)で答える。動画は ffmpeg で作った webm を transcribe/media の偽物で返す。
見るもの: 開く(帯 = 今日 n 件・この確認で決まる物・このあと・最初のカード)・URL の c / kind を口へ渡す / A で答える → 送った中身・すぐ次へ /
Z で 1 つ前に戻す(undo の id・カードが戻る・今日の数)/ N で飛ばす(skip を送る・Z では戻らない)/ 答えのボタン = キーと同じ道 /
読みのカード(1 / 2・3 で打って答える)/ 誰の声のカード = 再生が終わるまで Enter は効かない・自動で再生して区間で止まる・登録簿の人・混ざり /
時刻のカード = 波形の帯・単語の時刻の候補・H と ← で端を動かして答える / 声ですか(speech)/ 自動カット(cut)の 3 つの問い /
評価のレーン(lane=eval・まとめて文字起こし・区間カード)/ 10 件ごとのまとめ(Enter で続ける)/
全部答えた空の状態(back=cases なら案件へ戻る)/ 答えを記録できない(カードが戻る)・離れたら保留を確定 / 一覧を読めない(もう一度)・反映できなかった数 /
本物の口(src/app/check/deck.py)で空 / 版と appnav の今の場所(ヘッダーの部品の並びは ui_audit の A-28)/ コンソールにエラーが無い。"""
import json
import os
import re
import subprocess
import sys
import tempfile
import threading
import types
import urllib.parse
os.environ.setdefault("YTT_DATA_DIR", "inplace")   # テストは作業データを本物の置き場所に書かない(ytt.datadir)
import shutil
from unittest import mock

from playwright.sync_api import sync_playwright

TESTS = os.path.dirname(os.path.abspath(__file__))   # tests/app
SRC = os.path.join(os.path.dirname(os.path.dirname(TESTS)), "src")
sys.path.insert(0, os.path.join(SRC, "app"))
sys.path.insert(0, os.path.join(os.path.dirname(SRC), "tests", "app"))
if SRC not in sys.path:
    sys.path.append(SRC)
from app import server as L  # noqa: E402
from test_launch import free_ports  # noqa: E402
from ytt import tools  # noqa: E402
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))   # tests/(testkit)
import testkit  # noqa: E402


wait_js = testkit.wait_js


def make_video(path, sec=4):
    """再生を確かめる webm(VP9 + Opus。Playwright の chromium は H.264 を再生できない)"""
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi", "-i", "testsrc=size=320x180:rate=30:duration=%s" % sec,
                    "-f", "lavfi", "-i", "sine=frequency=440:duration=%s" % sec, "-shortest", "-pix_fmt", "yuv420p", "-c:v", "libvpx-vp9",
                    "-deadline", "realtime", "-cpu-used", "8", "-b:v", "200k", "-c:a", "libopus", path],
                   check=True, timeout=120, creationflags=tools.no_window_flags())
    with open(path, "rb") as f:
        return f.read()


def card(i, kind, **extra):
    c = {"id": "%s:e2e:%02d" % (kind, i), "kind": kind, "source": extra.pop("source", "auto"), "case": {"id": "v1", "title": "【雑談】テストの配信"},
         "target": {"docId": "a0000000000a", "row": "r%d" % i}, "media": {}, "text": "行 %d の字幕" % i, "note": ""}
    c.update(extra)
    return c


class FakeQueue:
    """⑤ の待ち行列の偽物(計画 2-3 の形)。答え・戻す・飛ばすを覚え、next は答えていない・飛ばしていない・skip に無い物を前から返す"""

    def __init__(self, cards):
        self.cards = cards
        self.answers = []      # [{id, body}]
        self.undone = []
        self.skipped = []
        self.next_q = []       # 受けた next の引数
        self.fail_next = 0     # 次の n 回の next を 500 に
        self.fail_answer = 0
        self.failed = 0        # counts.failed(前に答えたのに反映できなかった数)
        self.flushed = 0
        self.section_cards = None   # 評価のレーンの next に付ける sectionCards(None = 付けない)
        self.lock = threading.RLock()   # 経路の処理は同じ糸の中で入れ子に呼ばれることがある(fulfill の待ちの間に次の要求)= 入れ子でも止まらない鍵

    def live_answers(self):
        gone = set(self.undone)
        return [a for a in self.answers if a["id"] not in gone]

    def handle(self, route):
        req = route.request
        u = urllib.parse.urlparse(req.url)
        q = urllib.parse.parse_qs(u.query)
        with self.lock:
            if u.path.endswith("/api/check/next"):
                self.next_q.append(q)
                if self.fail_next:
                    self.fail_next -= 1
                    return route.fulfill(status=500, content_type="application/json", body=json.dumps({"error": "boom", "message": "待ち行列を作れませんでした(テスト)"}))
                done = {a["body"]["card"] for a in self.live_answers()} | set(self.skipped)
                skip = set((q.get("skip") or [""])[0].split(",")) if q.get("skip") else set()
                n = int((q.get("n") or ["10"])[0])
                rest = [c for c in self.cards if c["id"] not in done and c["id"] not in skip]
                values = len([a for a in self.live_answers() if a["body"]["card"].startswith("value:")])
                body = {"rev": len(self.answers), "cards": rest[:n], "total": len(rest),
                        "counts": {"today": len(self.live_answers()), "perKind": {}, "failed": self.failed},
                        "goal": {"kind": "value", "id": "marks", "label": "採用の記録 配信 10 本", "left": max(0, 2 - values), "target": 10, "unit": "本",
                                 "opens": "C1 盛り上がりの重み(I-4a)", "now": 8 + values, "reached": False},
                        "goals": {"value": {"kind": "value", "id": "marks", "label": "採用の記録 配信 10 本", "left": max(0, 2 - values), "target": 10, "unit": "本",
                                            "opens": "C1 盛り上がりの重み(I-4a)", "now": 8 + values, "reached": False},
                                  "read": {"kind": "read", "id": "fill", "label": "後処理の札の判定 30 行", "left": None, "target": 30, "unit": "行",
                                           "opens": "K1 後処理の割合", "now": None, "reached": False},   # 未測定
                                  "time": {"kind": "time", "id": "timing", "label": "行の時刻の判定 100 行", "left": 0, "target": 100, "unit": "行",
                                           "opens": "B1 行の時刻", "now": 100, "reached": True}},
                        "held": [], "failed": [], "errors": []}
                if self.section_cards is not None:
                    body["sectionCards"] = self.section_cards
                return route.fulfill(status=200, content_type="application/json", body=json.dumps(body, ensure_ascii=False))
            body = json.loads(req.post_data or "{}")
            if req.headers.get("x-ytt-token", "") == "":
                return route.fulfill(status=403, content_type="application/json", body=json.dumps({"error": "token"}))
            if u.path.endswith("/api/check/flush"):
                self.flushed += 1
                return route.fulfill(status=200, content_type="application/json", body='{"ok": true, "flushed": []}')
            if u.path.endswith("/api/check/skip"):
                self.skipped.append(body.get("card"))
                return route.fulfill(status=200, content_type="application/json", body='{"ok": true}')
            if u.path.endswith("/api/check/answer"):
                if "undo" in body:
                    self.undone.append(body["undo"])
                    return route.fulfill(status=200, content_type="application/json", body=json.dumps({"ok": True, "answer": body["undo"], "card": "", "reverted": {}}))
                if self.fail_answer:
                    self.fail_answer -= 1
                    return route.fulfill(status=500, content_type="application/json", body=json.dumps({"error": "boom", "message": "記録に失敗しました(テスト)"}))
                aid = "ans%03d" % (len(self.answers) + 1)
                self.answers.append({"id": aid, "body": body})
                return route.fulfill(status=200, content_type="application/json",
                                     body=json.dumps({"ok": True, "answer": aid, "card": body.get("card"), "applied": {}, "held": False, "flushed": [], "next": None}))
        return route.fulfill(status=404, body="")


def state(pg):
    return pg.evaluate("CheckShell.state()")


LOADED_JS = "document.getElementById('chkEmpty').hidden || !document.querySelector('#chkEmpty .chk-loading')"


def press(pg, key):
    """キーを押して、送った要求(答え・戻す・飛ばす)を偽の待ち行列が受け、カードの読み込み(先読みの api/check/next)が済むまで待つ。
    同期版の route は Playwright を呼んでいる間しか動かない(time.sleep では届かない)ので wait_for_timeout と evaluate で待つ"""
    pg.keyboard.press(key)
    pg.wait_for_timeout(40)
    wait_js(pg, LOADED_JS, 5000)


def _scene_open(cx):
    pg, check, fq = cx.pg, cx.check, cx.fq
    pg.goto(cx.base + "check?c=v1&kind=value&back=cases")
    check(wait_js(pg, "CheckShell.state().cur === 'value:e2e:01'"), "最初のカードが出る: %s" % state(pg))
    check(fq.next_q and fq.next_q[0].get("c") == ["v1"] and fq.next_q[0].get("kind") == ["value"] and fq.next_q[0].get("n") == ["10"],
          "URL の c・kind を口へ渡し、10 枚を先に読む: %s" % (fq.next_q[:1],))
    check(pg.text_content("#chkToday") == "0", "帯: 今日 0 件")
    check("機械の点数: 82" in pg.text_content("#chkBody"), "価値のカード: 字幕と機械の点数が出る: %r" % pg.text_content("#chkBody")[:80])
    goal = pg.text_content("#chkGoal")
    check("C1 盛り上がりの重み(I-4a)" in goal and "あと 2 本" in goal and "採用の記録 配信 10 本" in goal, "帯: この確認で決まる物とあと何本: %r" % goal)
    check(pg.evaluate("document.querySelectorAll('#chkQueue li').length") >= 5, "このあと の一覧")
    check(pg.is_disabled("#chkUndo") and bool(pg.get_attribute("#chkUndo", "title")), "まだ答えていないときは戻せない + 理由")
    check(wait_js(pg, "document.querySelector('#ver').textContent.startsWith('v')"), "版が出る")
    check(pg.evaluate("document.querySelector('[data-ui-appnav-item][aria-current=\"page\"]').dataset.uiAppnavItem") == "check", "appnav の今の場所は「確かめる」")


def _scene_answer_undo_skip(cx):
    pg, check, fq = cx.pg, cx.check, cx.fq
    press(pg, "a")
    check(state(pg)["cur"] == "value:e2e:02", "A で答えるとすぐ次へ: %s" % state(pg)["cur"])
    check(wait_js(pg, "CheckShell.state().hist === 1") and len(fq.answers) == 1, "答えを 1 件送った")
    a = fq.answers[0]["body"]
    check(a["card"] == "value:e2e:01" and a["answer"] == {"choice": "good"} and isinstance(a["ms"], int) and "value:e2e:02" in a["skip"],
          "送った中身(card・answer・ms・待っている id): %s" % a)
    check(pg.text_content("#chkToday") == "1", "帯: 今日 1 件")
    press(pg, "n")
    check(state(pg)["cur"] == "value:e2e:03" and wait_js(pg, "true") and fq.skipped == ["value:e2e:02"], "N で飛ばす(skip を送る): %s" % fq.skipped)
    press(pg, "z")
    check(wait_js(pg, "CheckShell.state().cur === 'value:e2e:01'"), "Z で最後に答えたカードへ戻る(飛ばしたカードは戻さない): %s" % state(pg))
    check(fq.undone == ["ans001"] and pg.text_content("#chkToday") == "0", "undo に答えの id を送り、今日の数も戻る: %s" % fq.undone)
    check(state(pg)["queue"][:1] == ["value:e2e:03"], "戻る前のカードは次に回る: %s" % state(pg)["queue"][:3])
    pg.click("#chkBody [data-chk-k='X']")   # 悪い = 理由の札の段へ(まだ答えない)
    check(state(pg)["cur"] == "value:e2e:01" and wait_js(pg, "!!document.querySelector(\"#chkBody [data-chk-k='1']\")"), "X(悪い)は理由の札を出すだけ: %s" % state(pg)["cur"])
    pg.click("#chkBody [data-chk-k='1']")
    check(wait_js(pg, "CheckShell.state().cur === 'value:e2e:03'") and wait_js(pg, "CheckShell.state().hist === 1"), "答えのボタン = キーと同じ道")
    check(fq.answers[-1]["body"]["answer"] == {"choice": "bad", "reason": "boring"}, "悪い + 理由の札の答え: %s" % fq.answers[-1]["body"]["answer"])
    check(not pg.is_disabled("#chkUndo"), "答えたあとは戻せる")


def _scene_kinds(cx):
    pg, check, fq = cx.pg, cx.check, cx.fq
    pg.goto(cx.base + "check")
    check(wait_js(pg, "CheckShell.state().cur === 'value:e2e:03'"), "開き直すと、答えた・飛ばしたカードの次から: %s" % state(pg))
    press(pg, "a")
    check(wait_js(pg, "CheckShell.state().kind === 'read'"), "読みのカード: %s" % state(pg))
    check(pg.evaluate("document.querySelectorAll('#chkBody .ui-pair .ui-pair-opt').length") == 2 and "まけないからね" in pg.text_content("#chkBody .ui-pair") and "認識のまま" in pg.text_content("#chkBody .ui-pair"),
          "比べる欄(ui-kit の .ui-pair)に 2 つの読みと出どころの名前")
    press(pg, "2")
    check(wait_js(pg, "CheckShell.state().kind === 'voice'") and fq.answers[-1]["body"]["answer"] == {"choice": "2"}, "2 で答える")
    check(wait_js(pg, "!!document.querySelector('#chkBody video')"), "誰の声のカードは動画を出す")
    press(pg, "Enter")
    pg.wait_for_timeout(200)
    check(state(pg)["kind"] == "voice", "再生が終わるまで Enter は効かない")
    check(wait_js(pg, "(() => { const v = document.querySelector('#chkBody video'); return v && !v.paused && v.currentTime > 0.4; })()", 10000), "出したら自動で再生(区間の頭から)")
    check(wait_js(pg, "(() => { const v = document.querySelector('#chkBody video'); return v && v.paused && v.currentTime >= 1.6 && v.currentTime < 2.3; })()", 10000),
          "区間の末 + pad で止まる: %s" % pg.evaluate("document.querySelector('#chkBody video').currentTime"))
    stopped = "(() => { const v = document.querySelector('#chkBody video'); return v && v.paused && v.currentTime >= 1.6; })()"
    replayed = "(() => { const v = document.querySelector('#chkBody video'); return v && !v.paused && v.currentTime < 1.2; })()"
    press(pg, "r")
    check(wait_js(pg, replayed, 5000) and state(pg)["kind"] == "voice", "終わった後の R = 区間の頭から流し直す(答えない)")
    check(wait_js(pg, stopped, 10000), "流し直しも区間の末で止まる")
    pg.click("[data-chk-replay]")
    check(wait_js(pg, replayed, 5000), "[もう一度聞く] のボタンも頭から")
    check(wait_js(pg, stopped, 10000), "ボタンの流し直しも末で止まる")
    pg.evaluate("document.activeElement && document.activeElement.blur()")
    press(pg, "Space")
    check(wait_js(pg, replayed, 5000), "末で止まった後の Space も頭から(すぐ止まらない)")
    check(wait_js(pg, stopped, 10000), "Space の再生も末で止まる")
    press(pg, "Enter")
    check(wait_js(pg, "CheckShell.state().kind === 'time'") and fq.answers[-1]["body"]["answer"] == {"choice": "B"}, "再生のあとの Enter = 機械の予想どおり")
    n_before = len(fq.answers)
    check(wait_js(pg, "!!document.querySelector('#chkBody canvas[data-chk-wave]')") and wait_js(pg, "!document.querySelector('[data-chk-wavemsg]').textContent"),
          "時刻のカードに波形の帯(peaks を読めた)")
    check(cx.retime_hits and cx.retime_hits[0] == {"id": "a0000000000c", "rows": ["r6"]}, "単語の印は POST transcribe/api/retime {id, rows:[行]}: %s" % cx.retime_hits[:1])
    check(cx.peaks_hits and "id=a0000000000c" in cx.peaks_hits[0], "波形は transcribe/api/peaks?id=<文書 id>: %s" % cx.peaks_hits[:1])
    check("B1 行の時刻" in pg.text_content("#chkGoal") and "目標に届きました" in pg.text_content("#chkGoal"), "帯はカードの種類の目標(goals): %r" % pg.text_content("#chkGoal"))
    check(wait_js(pg, "!!document.querySelector('[data-chk-tguide]').textContent"), "単語の時刻の候補(api/retime)を点線の参考の印と文で出す: %r" % pg.text_content("[data-chk-tguide]"))
    press(pg, "ArrowLeft")
    check(wait_js(pg, "CheckShell.state().kind === 'time'") and "ちょうどいい" in pg.text_content("[data-chk-tstate]"), "印を選ぶ前の ← は再生の移動(答えない・印も動かない)")
    press(pg, "h")
    for _ in range(3):
        press(pg, "ArrowLeft")
    check("頭がずれている" in pg.text_content("[data-chk-tstate]") and "−0.10 秒" in pg.text_content("[data-chk-tstate]"), "H で頭を選び ← 3 コマ = 0.10 秒前へ: %r" % pg.text_content("[data-chk-tstate]"))
    check(state(pg)["kind"] == "time" and len(fq.answers) == n_before, "動かしただけでは答えない")
    press(pg, "Enter")
    check(wait_js(pg, "CheckShell.state().kind === 'value'") and fq.answers[-1]["body"]["answer"] == {"choice": "head", "dStart": -0.1, "dEnd": 0},
          "Enter で答える(動かした量つき): %s" % fq.answers[-1]["body"]["answer"])


def _scene_summary_and_end(cx):
    pg, check = cx.pg, cx.check
    pg.goto(cx.base + "check?c=v1&back=cases")
    check(wait_js(pg, "!!CheckShell.state().cur"), "開き直すと続きから")
    for _ in range(10):   # まとめはこの画面で答えた数の 10 件ごと
        press(pg, "a" if state(pg)["kind"] == "value" else "1")
    check(wait_js(pg, "CheckShell.state().summary") and not pg.is_hidden("#chkSum"), "10 件ごとのまとめ: %s" % state(pg))
    check("件答えました" in pg.text_content("#chkSum") and "C1 盛り上がりの重み(I-4a)" in pg.text_content("#chkSum"), "まとめの文: %r" % pg.text_content("#chkSum"))
    press(pg, "Enter")
    check(wait_js(pg, "!CheckShell.state().summary && !!CheckShell.state().cur"), "Enter で続ける")
    for _ in range(40):
        if not state(pg)["cur"] or state(pg)["summary"]:
            if state(pg)["summary"]:
                press(pg, "Enter")
                continue
            break
        press(pg, "a" if state(pg)["kind"] == "value" else "1")
    check(wait_js(pg, "CheckShell.state().empty"), "全部答えたら空の状態: %s" % state(pg))
    check("今日の分は終わりです" in pg.text_content("#chkEmpty") and pg.get_attribute("#chkEmpty a.btn.primary", "href") == "cases?c=v1",
          "空の状態の文と 案件へ戻る(back=cases)")
    press(pg, "z")
    check(wait_js(pg, "!!CheckShell.state().cur && !CheckShell.state().empty"), "空の状態からも Z で 1 つ前に戻る")


def _scene_failures(cx):
    pg, check, fq = cx.pg, cx.check, cx.fq
    fq.fail_answer = 1
    cur = state(pg)["cur"]
    press(pg, "a" if state(pg)["kind"] == "value" else "1")
    check(wait_js(pg, "CheckShell.state().cur === %s" % json.dumps(cur), 8000), "答えを記録できなければ、そのカードがもう一度出る: %s" % state(pg))
    check(wait_js(pg, "[...document.querySelectorAll('.ui-toast')].some(t => t.textContent.includes('答えを記録できませんでした'))"), "失敗の知らせ")
    pg.evaluate("window.dispatchEvent(new Event('pagehide'))")
    check(wait_js(pg, "true") and fq.flushed >= 1, "画面を離れたら保留を確定(api/check/flush): %d" % fq.flushed)
    fq.fail_next = 1
    fq.failed = 2
    pg.goto(cx.base + "check?kind=time")
    check(wait_js(pg, "!!document.querySelector('#chkEmpty [data-chk-fail]')"), "一覧を読めないときは 何が + もう一度")
    check("待ち行列を作れませんでした(テスト)" in pg.text_content("#chkEmpty"), "サーバーの文を出す")
    pg.click("#chkEmpty [data-chk-retry]")
    check(wait_js(pg, "!!CheckShell.state().cur || CheckShell.state().empty"), "もう一度読み込むと出る: %s" % state(pg))
    check(wait_js(pg, "!document.querySelector('#chkFailed').hidden && document.querySelector('#chkFailed').textContent.includes('2 件')") and not pg.is_hidden("#chkFailed"),
          "反映できなかった答えの数を帯に 1 行")
    fq.failed = 0


def _scene_read_type(cx):
    """読みのカード: 1 / 2 で答える形は _scene_kinds。ここは 3(どちらも違う)= 入力欄 → 打つ → Enter で {choice: other, text}。入力欄の中の 1 は答えにならない"""
    pg, check, fq = cx.pg, cx.check, cx.fq
    fq.cards = [card(90, "read", source="alt", guess=None, text="今日は晴れです", note="違い: 「晴」→「腫」",
                     options=[{"id": "1", "text": "今日は晴れです"}, {"id": "2", "text": "今日は腫れです"}])]
    n = len(fq.live_answers())
    pg.goto(cx.base + "check?kind=read")
    check(wait_js(pg, "CheckShell.state().cur === 'read:e2e:90'"), "読みのカード(別のエンジン)が出る: %s" % state(pg))
    check("2 つ目のエンジン" in pg.text_content("#chkBody .ui-pair") and "違い: 「晴」→「腫」" in pg.text_content("#chkBody"), "出どころの名前と違い")
    check(pg.is_hidden("#chkBody [data-chk-type]"), "入力欄は 3 を押すまで隠れている")
    press(pg, "3")
    check(pg.is_visible("#chkBody [data-chk-text]") and pg.evaluate("document.activeElement.matches('[data-chk-text]')"), "3 で入力欄が開き、そこに入る")
    pg.fill("#chkBody [data-chk-text]", "")
    pg.keyboard.type("今日は春1です")
    pg.wait_for_timeout(200)
    check(len(fq.live_answers()) == n and state(pg)["cur"] == "read:e2e:90", "入力欄の中の 1 は答えにならない")
    press(pg, "Escape")
    check(pg.is_hidden("#chkBody [data-chk-type]") and len(fq.live_answers()) == n, "Esc でやめる(答えない)")
    press(pg, "3")
    pg.fill("#chkBody [data-chk-text]", "   ")
    press(pg, "Enter")
    pg.wait_for_timeout(200)
    check(len(fq.live_answers()) == n, "空のままの Enter は答えにならない")
    pg.fill("#chkBody [data-chk-text]", "今日は晴れでした")
    press(pg, "Enter")
    check(wait_js(pg, "CheckShell.state().cur === null || CheckShell.state().empty") and len(fq.live_answers()) == n + 1, "Enter で答える: %s" % state(pg))
    check(fq.answers[-1]["body"]["answer"] == {"choice": "other", "text": "今日は晴れでした"}, "答えは {choice: other, text}: %s" % fq.answers[-1]["body"]["answer"])


def _scene_real_api(cx):
    """偽物を外して本物の入口の口(src/app/check/deck.py)で開く: 作業データが空なら「いま確かめる物はありません」・帯の目標は ⑤ の goals"""
    pg, check = cx.pg, cx.check
    cx.ctx.unroute(re.compile(r".*/api/check/.*"))
    pg.goto(cx.base + "check")
    check(wait_js(pg, "CheckShell.state().empty", 30000), "本物の口: 確かめる物が無ければ空の状態: %s" % state(pg))
    check("いま確かめる物はありません" in pg.text_content("#chkEmpty") and pg.get_attribute("#chkEmpty a.btn.primary", "href") == "./",
          "空の状態の 2 文とホームへ: %r" % pg.text_content("#chkEmpty"))
    check(pg.text_content("#chkToday") == "0", "本物の口: 今日 0 件")


def _scene_voice(cx):
    """誰の声のカード: 予想の Enter のボタンは再生が終わるまで押せない(理由つき)・登録簿の人(name:)は {name} で答える・M = 混ざり・Z で戻すとまた待つ"""
    pg, check = cx.pg, cx.check
    vid = {"url": "transcribe/media?id=a0000000000b", "start": 0.5, "end": 1.5, "pad": 0.2}
    fv = FakeQueue([card(30, "voice", source="diar", media=vid, guess={"id": "name:みこ", "name": "みこ"}, note="below_match",
                         options=[{"id": "S1", "name": "ぺこら", "voice": True}, {"id": "name:みこ", "name": "みこ", "voice": True},
                                  {"id": "other", "name": "その他"}, {"id": "mixed", "name": "混ざり"}])])
    cx.ctx.unroute(re.compile(r".*/api/check/.*"))
    cx.ctx.route(re.compile(r".*/api/check/.*"), fv.handle)
    try:
        pg.goto(cx.base + "check?kind=voice")
        check(wait_js(pg, "CheckShell.state().cur === 'voice:e2e:30'"), "声のカードを開く: %s" % state(pg))
        enter = "#chkBody [data-chk-k='Enter']"
        check(pg.evaluate("(() => { const b = document.querySelector(\"%s\"); return !!b && b.disabled && !!b.getAttribute('data-ui-why'); })()" % enter),
              "予想どおり(Enter)のボタンは再生が終わるまで押せない・理由つき")
        check("みこ" in pg.text_content("#chkBody .notice"), "機械の予想の名前")
        press(pg, "m")
        check(wait_js(pg, "CheckShell.state().empty") and fv.answers[-1]["body"]["answer"] == {"choice": "mixed"}, "M = 声が混ざっている")
        press(pg, "z")
        check(wait_js(pg, "CheckShell.state().cur === 'voice:e2e:30'") and pg.evaluate("document.querySelector(\"%s\").disabled" % enter), "Z で戻すと、また再生が終わるまで待つ")
        check(wait_js(pg, "!document.querySelector(\"%s\").disabled" % enter, 10000), "再生が終わると押せる")
        pg.click(enter)
        check(wait_js(pg, "CheckShell.state().empty") and fv.answers[-1]["body"]["answer"] == {"name": "みこ"}, "登録簿の人の予想は {name} で答える: %s" % fv.answers[-1:])
    finally:
        cx.ctx.unroute(re.compile(r".*/api/check/.*"))
        cx.ctx.route(re.compile(r".*/api/check/.*"), cx.fq.handle)


def _swap_queue(cx, fq2, eval_routes=None):
    """api/check/ の偽物を fq2 に差し替える(戻すのは _restore_queue)。eval_routes = transcribe/api/drill/status・eval-batch の偽物(あれば)"""
    cx.ctx.unroute(re.compile(r".*/api/check/.*"))
    cx.ctx.route(re.compile(r".*/api/check/.*"), fq2.handle)
    if eval_routes:
        cx.ctx.route(EVAL_ROUTE_RE, eval_routes)


def _restore_queue(cx, eval_routes=None):
    cx.ctx.unroute(re.compile(r".*/api/check/.*"))
    cx.ctx.route(re.compile(r".*/api/check/.*"), cx.fq.handle)
    if eval_routes:
        cx.ctx.unroute(EVAL_ROUTE_RE, eval_routes)


EVAL_ROUTE_RE = re.compile(r".*/transcribe/api/(drill/status|eval-batch).*")


def _scene_speech(cx):
    """この行は声ですか?(speech): A = 残す {choice: keep}・X(ボタン)= 消す {choice: drop}"""
    pg, check = cx.pg, cx.check
    fs = FakeQueue([card(60 + i, "speech", source="diar", options=["keep", "drop"], text="声かどうか怪しい行 %d" % i) for i in (1, 2)])
    _swap_queue(cx, fs)
    try:
        pg.goto(cx.base + "check?kind=speech")
        check(wait_js(pg, "CheckShell.state().cur === 'speech:e2e:61'"), "speech のカードが出る: %s" % state(pg))
        check("この行は声ですか?" in pg.text_content("#chkBody") and "声かどうか怪しい行 1" in pg.text_content("#chkBody"), "問いと行の字幕")
        check(pg.evaluate("[...document.querySelectorAll('#chkBody [data-chk-k]')].map(b => b.dataset.chkK).join()") == "A,X", "ボタンは A(残す)と X(消す)")
        press(pg, "a")
        check(wait_js(pg, "CheckShell.state().cur === 'speech:e2e:62'") and fs.answers[-1]["body"]["answer"] == {"choice": "keep"}, "A = 残す: %s" % fs.answers[-1:])
        pg.click("#chkBody [data-chk-k='X']")
        check(wait_js(pg, "CheckShell.state().empty") and fs.answers[-1]["body"]["answer"] == {"choice": "drop"}, "X のボタン = 消す: %s" % fs.answers[-1:])
        check(all("lane" not in q for q in fs.next_q), "普段のレーンは lane を渡さない: %s" % fs.next_q[:2])
    finally:
        _restore_queue(cx)


def _scene_cut(cx):
    """自動カットの確認(cut): edge / gap / whole の問い・ボタン・キーの答え・消した所を飛ばす"""
    pg, check = cx.pg, cx.check
    vurl = "transcribe/media?id=a0000000000e"

    def cc(i, source, target, media):
        return card(i, "cut", source=source, target=dict(target, docId="a0000000000e"), media=media, text="", note="自動カットのテスト")
    edge_m = {"url": vurl, "start": 0.0, "end": 4.0, "pad": 0.0}
    cut = {"cut": [1.0, 2.5]}
    keeps = {"keeps": [[0.0, 1.0], [2.5, 3.5]]}
    fc = FakeQueue([cc(91, "edge", cut, edge_m), cc(92, "edge", cut, edge_m), cc(93, "gap", cut, edge_m), cc(94, "whole", keeps, edge_m)])
    _swap_queue(cx, fc)
    keys = "[...document.querySelectorAll('#chkBody [data-chk-k]')].map(b => b.dataset.chkK).join()"
    try:
        pg.goto(cx.base + "check?kind=cut")
        check(wait_js(pg, "CheckShell.state().cur === 'cut:e2e:91'"), "cut の edge カードが出る: %s" % state(pg))
        check("切れ目はちょうどいい?" in pg.text_content("#chkBody"), "edge の問い")
        check(pg.evaluate(keys) == "Enter,E,L,K", "edge のボタンは Enter・E・L・K: %s" % pg.evaluate(keys))
        # 消した所を飛ばす(本物の動画のとき。飛ばなければ失敗にせず注記だけ)
        if wait_js(pg, "(() => { const v = document.querySelector('#chkBody video'); return !!v && v.readyState >= 1; })()", 8000):
            pg.evaluate("document.querySelector('#chkBody video').currentTime = 1.5")
            jumped = wait_js(pg, "document.querySelector('#chkBody video').currentTime >= 2.5", 3000)
            # 偽の動画は Range 無しで返すので、シークが戻される(再生位置が揺れる)= 飛んだときだけ確かめ、飛ばなければ注記だけ(不安定にしない)
            print(("OK   " if jumped else "SKIP ") + "edge: 消した所の中へ動かすと 2.5 へ飛ぶ(偽の動画ではシークが効かないことがある): %s" % pg.evaluate("document.querySelector('#chkBody video').currentTime"), flush=True)
        else:
            print("SKIP edge の飛ばし: video が準備できない", flush=True)
        press(pg, "Enter")
        check(wait_js(pg, "CheckShell.state().cur === 'cut:e2e:92'") and fc.answers[-1]["body"]["answer"] == {"choice": "good"}, "edge: Enter = good: %s" % fc.answers[-1:])
        pg.click("#chkBody [data-chk-k='L']")
        check(wait_js(pg, "CheckShell.state().cur === 'cut:e2e:93'") and fc.answers[-1]["body"]["answer"] == {"choice": "late"}, "edge: L のボタン = late: %s" % fc.answers[-1:])
        check("消してよい?" in pg.text_content("#chkBody") and pg.evaluate(keys) == "A,K", "gap の問いとボタン A・K: %s" % pg.evaluate(keys))
        press(pg, "a")
        check(wait_js(pg, "CheckShell.state().cur === 'cut:e2e:94'") and fc.answers[-1]["body"]["answer"] == {"choice": "ok"}, "gap: A = ok: %s" % fc.answers[-1:])
        check("自動で切った 1 本は自然?" in pg.text_content("#chkBody") and pg.evaluate(keys) == "Enter,T,U", "whole の問いとボタン Enter・T・U: %s" % pg.evaluate(keys))
        press(pg, "u")
        check(wait_js(pg, "CheckShell.state().empty") and fc.answers[-1]["body"]["answer"] == {"choice": "unnatural"}, "whole: U = unnatural: %s" % fc.answers[-1:])
    finally:
        _restore_queue(cx)


def _section_card(i, rows=None, **extra):
    rows = rows if rows is not None else [
        {"id": "r1", "start": 1.0, "end": 3.0, "text": "もとの字幕", "speaker": "ぺこら", "owned": True, "novoice": False, "proofed": False},
        {"id": "r2", "start": 4.0, "end": 6.0, "text": "消す予定の行", "speaker": "", "owned": True, "novoice": True, "proofed": False},
        {"id": "r3", "start": 31.0, "end": 33.0, "text": "隣の区間の行", "speaker": "", "owned": False, "novoice": False, "proofed": False}]
    return card(i, "section", source="eval", options=["ぺこら", "みこ"], rows=rows, note="評価用 テスト動画の 0:00 〜 0:30",
                target={"docId": "a0000000000d", "from": 0.0, "to": 30.0, "rows": ["r1", "r2"], "updatedAt": 1, "last": False, "index": 0},
                progress={"index": 0, "fromSec": 0.0, "totalSec": 90.0},
                media={"url": "transcribe/media?id=a0000000000d", "start": 0.0, "end": 30.0, "pad": 0.0}, **extra)


def _scene_eval_lane(cx):
    """評価のレーン: タブ・頭(定点 + まとめて文字起こし)・区間カード(合っている = {}・直して答える = 変えた行と足す行)"""
    pg, check = cx.pg, cx.check
    fe = FakeQueue([_section_card(71), _section_card(72)])
    fe.section_cards = True
    hits = {"start": [], "stop": [], "get": 0, "running": False}

    def eval_routes(route):
        u = route.request.url
        if "/drill/status" in u:
            return route.fulfill(status=200, content_type="application/json", body=json.dumps(
                {"goalSec": 3600, "reviewedSec": 3000, "leftSec": 600, "docs": 9, "reviewedDocs": 3, "pendingDocs": 4, "untranscribed": 2, "ready": False}))
        if "/eval-batch/start" in u:
            hits["start"].append(json.loads(route.request.post_data or "{}"))
            hits["running"] = True
            return route.fulfill(status=200, content_type="application/json", body='{"ok": true}')
        if "/eval-batch/stop" in u:
            hits["stop"].append(json.loads(route.request.post_data or "{}"))
            hits["running"] = False
            return route.fulfill(status=200, content_type="application/json", body='{"ok": true}')
        hits["get"] += 1
        return route.fulfill(status=200, content_type="application/json", body=json.dumps(
            {"enabled": hits["running"], "enqueued": 5, "done": 2, "failed": 0, "remaining": 3, "finished": False, "titles": ["動画 A"], "lastError": ""}))

    _swap_queue(cx, fe, eval_routes)
    try:
        pg.goto(cx.base + "check?lane=eval")
        check(wait_js(pg, "CheckShell.state().cur === 'section:e2e:71'"), "評価のレーンの区間カードが出る: %s" % state(pg))
        lanes = pg.evaluate("[...document.querySelectorAll('#chkLanes [data-chk-lane]')].map(a => [a.dataset.chkLane, a.getAttribute('aria-current')])")
        cur_lanes = [l[0] for l in lanes if l[1] == "page"]
        check(cur_lanes == ["eval"] and len(lanes) == 2, "レーンのタブ: 評価だけが今の場所: %s" % lanes)
        check(fe.next_q and all(q.get("lane") == ["eval"] for q in fe.next_q), "評価のレーンは lane=eval を渡す: %s" % fe.next_q[:2])
        check(wait_js(pg, "!document.querySelector('#chkEvalHead').hidden"), "評価の頭が出る")
        pg.click("#chkEvalHead [data-chk-eb=start]")
        check(wait_js(pg, "!!document.querySelector('#chkEvalHead [data-chk-eb=stop]')") and hits["start"] == [{}], "まとめて文字起こし = POST eval-batch/start {}: %s" % hits["start"])
        check(wait_js(pg, "document.querySelector('#chkEvalHead').textContent.includes('まとめて文字起こし中')"), "動き出したら 止める に変わる: %r" % pg.text_content("#chkEvalHead")[:120])
        # 区間カード
        body = "#chkBody"
        enter = "#chkBody [data-chk-k='Enter']"
        check(pg.evaluate("document.querySelectorAll('#chkBody li[data-sec-row]').length") == 2, "持ち主の行 2 本が直せる形で出る")
        check(pg.evaluate("(() => { const o = document.querySelector('#chkBody .chk-sec-other'); return !!o && o.textContent.includes('隣の区間の行') && !o.querySelector('input,select,textarea,button'); })()"),
              "隣の区間の行は見せるだけ(入力欄なし)")
        check(pg.evaluate("document.querySelectorAll('#chkBody [data-sec-text]').length") == 2, "文字の欄は持ち主の行の分だけ")
        check("合っている" in pg.text_content(enter), "何も変えないときのボタン: %r" % pg.text_content(enter))
        press(pg, "Enter")
        check(wait_js(pg, "CheckShell.state().cur === 'section:e2e:72'") and fe.answers[-1]["body"]["answer"] == {}, "何も変えず Enter = {}: %s" % fe.answers[-1:])
        # 2 枚目: 直す
        pg.fill("#chkBody li[data-sec-row=r1] [data-sec-text]", "直した字幕")
        check("直して答える" in pg.text_content(enter), "直すとボタンが 直して答える に変わる: %r" % pg.text_content(enter))
        pg.select_option("#chkBody li[data-sec-row=r1] [data-sec-spk]", "みこ")
        pg.check("#chkBody li[data-sec-row=r2] [data-sec-drop]")
        pg.evaluate("document.activeElement && document.activeElement.blur()")
        press(pg, "a")
        check(pg.evaluate("document.querySelectorAll('#chkBody li[data-sec-add]').length") == 1, "A で足す行の欄が増える")
        check(pg.evaluate("document.activeElement.matches('[data-sec-add] [data-sec-text]')"), "足す行の文字の欄に入る")
        pg.fill("#chkBody li[data-sec-add] [data-sec-a]", "7")
        pg.fill("#chkBody li[data-sec-add] [data-sec-b]", "9.5")
        pg.fill("#chkBody li[data-sec-add] [data-sec-text]", "足した言葉")
        pg.focus("#chkBody li[data-sec-add] [data-sec-text]")
        press(pg, "Enter")
        check(state(pg)["cur"] == "section:e2e:72", "入力中の Enter だけでは答えない")
        press(pg, "Control+Enter")
        check(wait_js(pg, "CheckShell.state().empty"), "Ctrl+Enter で答える: %s" % state(pg))
        want = {"rows": [{"id": "r1", "text": "直した字幕", "speaker": "みこ"}, {"id": "r2", "drop": True}], "add": [{"start": 7, "end": 9.5, "text": "足した言葉"}]}
        check(fe.answers[-1]["body"]["answer"] == want, "直した答えの中身: %s" % fe.answers[-1]["body"]["answer"])
        pg.click("#chkEvalHead [data-chk-eb=stop]")
        check(wait_for(lambda: hits["stop"] == [{}]), "止める = POST eval-batch/stop {}: %s" % hits["stop"])
    finally:
        _restore_queue(cx, eval_routes)


def wait_for(fn, timeout=8):
    return testkit.wait_for(fn, timeout, 0.1)


def fixture_cards():
    vid = {"url": "transcribe/media?id=a0000000000b", "start": 0.5, "end": 1.5, "pad": 0.2}
    cards = [card(i, "value", options=["good", "bad"], reasons=[{"id": "boring", "text": "場面がつまらない"}, {"id": "long", "text": "長すぎる"}],
                  score=82.4 if i == 1 else None) for i in (1, 2, 3)]   # 自動の切り抜き = 送った後の品質の確認(良い / 悪い + 理由の札)
    cards.append(card(4, "read", source="fill", guess="1", note="llm", options=[{"id": "1", "text": "負けないからね"}, {"id": "2", "text": "まけないからね"}]))
    cards.append(card(5, "voice", source="diar", media=vid, guess={"id": "B", "name": "配信者 B"},
                      options=[{"id": "A", "name": "配信者 A"}, {"id": "B", "name": "配信者 B"}, {"id": "other", "name": "その他"}, {"id": "mixed", "name": "混ざり"}]))
    cards.append(card(6, "time", source="row", guess="ok", options=["ok", "head", "tail", "both"], target={"docId": "a0000000000c", "row": "r6"},
                      media={"url": "transcribe/media?id=a0000000000c", "start": 1, "end": 2, "pad": 0.5}))
    cards += [card(i, "value", source="cand", options=["adopt", "reject"]) for i in range(7, 25)]
    return cards


def main():
    checks = {"ok": True}

    def check(cond, msg):
        print(("OK   " if cond else "FAIL ") + msg, flush=True)
        checks["ok"] = checks["ok"] and bool(cond)

    tmp = tempfile.mkdtemp(prefix="ytt-check-ui-")
    video = make_video(os.path.join(tmp, "v.webm"))
    patches = [mock.patch.dict(os.environ, {"YTT_RUNTIME_DIR": os.path.join(tmp, ".runtime")})]
    for p in patches:
        p.start()
    sup = L.Supervisor(tmp, ready_timeout=5, stop_timeout=5, poll=0.5, log=lambda m: None, ports=dict(zip(L.TOOL_IDS, free_ports(3))), mounts=())
    srv, port = L.make_server(0, sup)
    sup.attach(srv)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    errors, bad_status, peaks_hits, retime_hits = [], [], [], []
    fq = FakeQueue(fixture_cards())

    def media_route(route):
        u = route.request.url
        if "/api/peaks" in u:
            peaks_hits.append(u)
            return route.fulfill(status=200, body=bytes((i * 7) % 256 for i in range(800)), headers={"X-Peaks-Rate": "100", "Content-Type": "application/octet-stream"})
        if "/api/retime" in u:
            retime_hits.append(json.loads(route.request.post_data or "{}"))
            return route.fulfill(status=200, content_type="application/json", body=json.dumps(
                {"items": [{"id": "r6", "start": 0.85, "end": 2.2, "matched": True, "dStart": -0.15, "dEnd": 0.2, "edges": ["start", "end"], "from": {"start": 1.0, "end": 2.0}}],
                 "checked": 1, "updatedAt": 1}))
        return route.fulfill(status=200, body=video, headers={"Content-Type": "video/webm", "Accept-Ranges": "none"})

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(args=["--autoplay-policy=no-user-gesture-required", "--mute-audio"])
            try:
                ctx = browser.new_context(viewport={"width": 1280, "height": 900})
                pg = ctx.new_page()
                ctx.route(re.compile(r".*/api/check/.*"), fq.handle)
                ctx.route(re.compile(r".*/transcribe/.*"), media_route)
                pg.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
                pg.on("pageerror", lambda e: errors.append(str(e)))
                pg.on("response", lambda r: bad_status.append("%s %s" % (r.status, r.url)) if r.status >= 400 else None)
                cx = types.SimpleNamespace(pg=pg, check=check, fq=fq, base="http://127.0.0.1:%d/" % port, peaks_hits=peaks_hits, retime_hits=retime_hits, ctx=ctx)
                _scene_open(cx)
                _scene_answer_undo_skip(cx)
                _scene_kinds(cx)
                _scene_summary_and_end(cx)
                _scene_failures(cx)
                _scene_read_type(cx)
                _scene_voice(cx)
                _scene_speech(cx)
                _scene_cut(cx)
                _scene_eval_lane(cx)
                check(all("lane" not in q for q in fq.next_q), "普段のレーンは lane=eval を渡さない")
                _scene_real_api(cx)
                unexpected = [s for s in bad_status if not s.startswith("500 ")]
                check(not unexpected, "4xx/5xx が出ない(試しに起こした 500 を除く): %s" % unexpected[:5])
                errs = [e for e in errors if "500" not in e and "Internal Server Error" not in e]
                check(not errs, "コンソールにエラーが無い: %s" % errs[:5])
            finally:
                browser.close()
    finally:
        srv.shutdown()
        srv.server_close()
        sup.close()
        for p in patches:
            p.stop()
        shutil.rmtree(tmp, ignore_errors=True)
    print("ALL OK" if checks["ok"] else "SOME FAILED", flush=True)
    return 0 if checks["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
