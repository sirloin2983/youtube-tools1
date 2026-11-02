"""確かめる(/check。部品は src/app/ui/check/)の通し確認(Playwright)。リポジトリ直下で:
    set PYTHONIOENCODING=utf-8
    py -3.12 tests/app/e2e_check.py
入口(server.py)はツールを取り込まずに動かす。⑤ の待ち行列の口(api/check/next・answer・skip)は
計画 資料の git:before-1028-cleanup:docs/design/v1-check-build.md 2-3 の形の偽物(Playwright の route)で答える。動画は ffmpeg で作った webm を transcribe/media の偽物で返す。
見るもの: 開く(帯 = 今日 n 件・この確認で決まる物・このあと・最初のカード)・URL の c / kind を口へ渡す / A で答える → 送った中身・すぐ次へ /
Z で 1 つ前に戻す(undo の id・カードが戻る・今日の数)/ N で飛ばす(skip を送る・Z では戻らない)/ 答えのボタン = キーと同じ道 /
誰の声のカード = 再生が終わるまで Enter は効かない・動画のある文書は映像つき・切り出した音は音だけ・自動で再生して区間で止まる・登録簿の人・混ざり・G(ゲーム音・BGM が大きい)/ 答えに 404 gone(戻さず次へ)/
時刻のカード = 波形の帯・単語の時刻の候補・H と ← で端を動かして答える / 自動カット(cut)の 3 つの問い /
(読みのカード read と「この行は声ですか?」speech は 10-31 に消した = 文字起こしを Haas に替えるため)/
種類の切り替え(残りの枚数・覚える・URL の kind が先)/ 評価のレーン(lane=eval・まとめて文字起こし・区間カード)/ 10 件答えても止めない(答えた数・目標は端に)/
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


def make_wav(path, sec=3):
    """切り出した行の音の形(16kHz・モノラル・16bit。human/proof/voiceclips と同じ)"""
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi", "-i", "sine=frequency=300:sample_rate=16000:duration=%s" % sec,
                    "-ac", "1", "-c:a", "pcm_s16le", path], check=True, timeout=60, creationflags=tools.no_window_flags())
    with open(path, "rb") as f:
        return f.read()


def card(i, kind, **extra):
    c = {"id": "%s:e2e:%02d" % (kind, i), "kind": kind, "source": extra.pop("source", "auto"), "case": {"id": "v1", "title": "【雑談】テストの配信"},
         "target": {"docId": "a0000000000a", "row": "r%d" % i}, "media": {}, "text": "行 %d の字幕" % i, "note": ""}
    c.update(extra)
    return c


MEMBERS = {"groups": [{"label": "3期生", "names": ["兎田ぺこら", "宝鐘マリン"]}, {"label": "0期生", "names": ["さくらみこ"]}],
           "members": {"兎田ぺこら": {"yomi": "うさだぺこら", "en": "Usada Pekora", "calls": ["ぺこら先輩"], "hex": "#68C1FF"},
                       "宝鐘マリン": {"yomi": "ほうしょうまりん", "en": "Houshou Marine", "calls": ["船長", "せんちょう"], "hex": "#C83F3F"},
                       "さくらみこ": {"yomi": "", "en": "Sakura Miko", "calls": ["みこち"], "hex": "#FF8FDF"}}}


class FakeQueue:
    """⑤ の待ち行列の偽物(計画 2-3 の形)。答え・戻す・飛ばすを覚え、next は答えていない・飛ばしていない・skip に無い物を前から返す"""

    def __init__(self, cards):
        self.cards = cards
        self.answers = []      # [{id, body}]
        self.undone = []
        self.skipped = []
        self.unknowns = []     # [分からない] [{id, body}](undo の id で戻る)
        self.symrules = {"proposals": [], "rules": [], "unsure": []}   # 記号の決まりの欄の返事(11-02)
        self.sym_posts = []    # 記号の決まりの案への答え
        self.next_q = []       # 受けた next の引数
        self.fail_next = 0     # 次の n 回の next を 500 に
        self.fail_answer = 0
        self.gone = set()      # 答えると 404 gone を返すカードの id(一度答えたあとは一覧にも出さない = 一覧のあとで確かめる物でなくなった)
        self.gone_hit = set()
        self.failed = 0       # counts.failed(前に答えたのに反映できなかった数)
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
            if u.path.endswith("/api/check/symbolrules"):   # 記号の決まりの欄(11-02)
                if req.method == "POST":
                    self.sym_posts.append(json.loads(req.post_data or "{}"))
                    self.symrules["proposals"] = []
                    return route.fulfill(status=200, content_type="application/json", body='{"ok": true}')
                return route.fulfill(status=200, content_type="application/json", body=json.dumps(self.symrules, ensure_ascii=False))
            if u.path.endswith("/api/check/members"):   # 話者カードの「ほかのメンバーを足す」の探し方の表(11-02)
                return route.fulfill(status=200, content_type="application/json", body=json.dumps(MEMBERS, ensure_ascii=False))
            if u.path.endswith("/api/check/next"):
                self.next_q.append(q)
                if self.fail_next:
                    self.fail_next -= 1
                    return route.fulfill(status=500, content_type="application/json", body=json.dumps({"error": "boom", "message": "待ち行列を作れませんでした(テスト)"}))
                done = ({a["body"]["card"] for a in self.live_answers()} | set(self.skipped) | self.gone_hit |
                        {u["body"]["card"] for u in self.unknowns if u["id"] not in self.undone})
                skip = set((q.get("skip") or [""])[0].split(",")) if q.get("skip") else set()
                n = int((q.get("n") or ["10"])[0])
                every = [c for c in self.cards if c["id"] not in done and c["id"] not in skip]
                kind = (q.get("kind") or [""])[0]
                rest = [c for c in every if not kind or c["kind"] == kind or (kind == "voice" and c["kind"] == "speaker")]   # 本物と同じく 話者 = 誰の声 + コラボの話者(11-02)
                per = {k: len([c for c in self.cards if c["kind"] == k and c["id"] not in done]) for k in ("value", "voice", "time", "cut")}   # 本物と同じく skip は数から外さない
                values = len([a for a in self.live_answers() if a["body"]["card"].startswith("value:")])
                body = {"rev": len(self.answers), "cards": rest[:n], "total": len(rest),
                        "counts": {"today": len(self.live_answers()), "perKind": per, "failed": self.failed},
                        "goal": {"kind": "value", "id": "marks", "label": "採用の記録 配信 10 本", "left": max(0, 2 - values), "target": 10, "unit": "本",
                                 "opens": "C1 盛り上がりの重み(I-4a)", "now": 8 + values, "reached": False},
                        "goals": {"value": {"kind": "value", "id": "marks", "label": "採用の記録 配信 10 本", "left": max(0, 2 - values), "target": 10, "unit": "本",
                                            "opens": "C1 盛り上がりの重み(I-4a)", "now": 8 + values, "reached": False},
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
            if u.path.endswith("/api/check/unknown"):
                uid = "unk%03d" % (len(self.unknowns) + 1)
                self.unknowns.append({"id": uid, "body": body})
                return route.fulfill(status=200, content_type="application/json",
                                     body=json.dumps({"ok": True, "answer": uid, "card": body.get("card"), "flushed": [], "next": None}))
            if u.path.endswith("/api/check/answer"):
                if "undo" in body:
                    self.undone.append(body["undo"])
                    return route.fulfill(status=200, content_type="application/json", body=json.dumps({"ok": True, "answer": body["undo"], "card": "", "reverted": {}}))
                if self.fail_answer:
                    self.fail_answer -= 1
                    return route.fulfill(status=500, content_type="application/json", body=json.dumps({"error": "boom", "message": "記録に失敗しました(テスト)"}))
                if body.get("card") in self.gone:
                    self.gone_hit.add(body["card"])
                    return route.fulfill(status=404, content_type="application/json", body=json.dumps({"error": "gone", "message": "そのカードはもう確かめる物ではありません(テスト)"}))
                aid = "ans%03d" % (len(self.answers) + 1)
                self.answers.append({"id": aid, "body": body})
                return route.fulfill(status=200, content_type="application/json",
                                     body=json.dumps({"ok": True, "answer": aid, "card": body.get("card"), "applied": {}, "held": False, "flushed": [], "next": None}))
        return route.fulfill(status=404, body="")


def state(pg):
    return pg.evaluate("CheckShell.state()")


LOADED_JS = "document.getElementById('chkEmpty').hidden || !document.querySelector('#chkEmpty .chk-loading')"


SHELL_BTN = {"n": "#chkSkip", "w": "#chkUnknown", "r": "[data-chk-replay]"}   # 共通の枠のボタン(11-02 にキーを消した)
KEPT_KEYS = {"z", "Space"}   # 11-02 ユーザー「キー操作は大幅に消す」のあとに残したキー


def press(pg, key):
    """カードの名前 key のボタンを押す(無ければ何もしない = 効かないキーと同じ)。残したキー(Z・Space)と、入力欄の中の Enter・Esc はキーで押す。
    送った要求(答え・戻す・後で)を偽の待ち行列が受け、カードの読み込み(先読みの api/check/next)が済むまで待つ。
    同期版の route は Playwright を呼んでいる間しか動かない(time.sleep では届かない)ので wait_for_timeout と evaluate で待つ"""
    typing = pg.evaluate("(() => { const a = document.activeElement; return !!a && /^(INPUT|TEXTAREA|SELECT)$/.test(a.tagName); })()")
    if key == "1" and not typing and state(pg)["kind"] in ("voice", "speaker"):   # 話者カード = 最初の人を選んで決める(数字のキーは無い)
        for k in ("N0", "Enter"):
            pg.evaluate("(() => { const b = document.querySelector(\"#chkBody [data-chk-k='%s']\"); if (b && !b.disabled) b.click(); })()" % k)
    elif key in KEPT_KEYS or (typing and key in ("Enter", "Escape")):
        pg.keyboard.press(key)
    else:
        sel = SHELL_BTN.get(key) or "#chkBody [data-chk-k='%s']" % (key if len(key) > 1 else key.upper())
        pg.evaluate("(() => { const b = document.querySelector(%s); if (b && !b.disabled) b.click(); })()" % json.dumps(sel))
    pg.wait_for_timeout(40)
    wait_js(pg, LOADED_JS, 5000)


def answer_key(pg):
    """今のカードに答えるキー: 価値の候補(cand)= A・自動の切り抜き = 点の 4(10-29 点だけで答える)・ほか = 1"""
    if state(pg)["kind"] != "value":
        return "1"
    return "a" if pg.evaluate("!!document.querySelector(\"#chkBody [data-chk-k='A']\")") else "4"


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
    press(pg, "4")
    check(state(pg)["cur"] == "value:e2e:02", "点の 4 で答えるとすぐ次へ: %s" % state(pg)["cur"])
    check(wait_js(pg, "CheckShell.state().hist === 1") and len(fq.answers) == 1, "答えを 1 件送った")
    a = fq.answers[0]["body"]
    check(a["card"] == "value:e2e:01" and a["answer"] == {"choice": "good", "score": 4} and isinstance(a["ms"], int) and "value:e2e:02" in a["skip"],
          "送った中身(card・answer・ms・待っている id): %s" % a)
    check(pg.text_content("#chkToday") == "1", "帯: 今日 1 件")
    check(pg.text_content("#chkSkip").strip() == "後で" and "もう出さない" in pg.text_content("#chkUnknown"), "共通の枠の言葉(後で・分からない(もう出さない)): %r" % pg.text_content("#chkSkip"))
    check(pg.evaluate("!!document.querySelector('#chkBody .chk-rows + #chkFoot')"), "共通の枠は答えのすぐ下(カードの中)")
    press(pg, "n")
    check(state(pg)["cur"] == "value:e2e:03" and wait_js(pg, "true") and fq.skipped == ["value:e2e:02"], "[後で](skip を送る): %s" % fq.skipped)
    press(pg, "z")
    check(wait_js(pg, "CheckShell.state().cur === 'value:e2e:01'"), "Z で最後に答えたカードへ戻る(飛ばしたカードは戻さない): %s" % state(pg))
    check(fq.undone == ["ans001"] and pg.text_content("#chkToday") == "0", "undo に答えの id を送り、今日の数も戻る: %s" % fq.undone)
    check(state(pg)["queue"][:1] == ["value:e2e:03"], "戻る前のカードは次に回る: %s" % state(pg)["queue"][:3])
    pg.click("#chkBody [data-chk-k='2']")   # 点の 2 = 悪い = 理由の札の段へ(まだ答えない)
    check(state(pg)["cur"] == "value:e2e:01" and wait_js(pg, "!!document.querySelector(\"#chkBody [data-chk-k='Enter']\")"), "点の 2(悪い)は理由の札を出すだけ: %s" % state(pg)["cur"])
    pg.click("#chkBody [data-chk-k='1']")
    check(wait_js(pg, "CheckShell.state().cur === 'value:e2e:03'") and wait_js(pg, "CheckShell.state().hist === 1"), "答えのボタン = キーと同じ道")
    check(fq.answers[-1]["body"]["answer"] == {"choice": "bad", "reason": "boring", "score": 2}, "悪い + 理由の札 + 点の答え: %s" % fq.answers[-1]["body"]["answer"])
    check(not pg.is_disabled("#chkUndo"), "答えたあとは戻せる")
    # 点だけで答える(10-29 ユーザー): ボタンは 1〜5 だけ・3 = 不明・押し続け(repeat)では次のカードに答えない(0.99.338 の守り)
    keys = "[...document.querySelectorAll('#chkBody [data-chk-k]')].map(b => b.dataset.chkK).join()"
    check(pg.evaluate(keys) == "1,2,3,4,5", "ボタンは 1〜5 だけ(良い・悪い・不明のボタンは無い): %s" % pg.evaluate(keys))
    bar = pg.text_content(".ui-keybar") or ""
    check("1 つ前に戻す" in bar and "分からない" not in bar and "面白" not in bar, "下の帯は残したキー(Space・Z)だけ: %r" % bar)
    n0 = len(fq.answers)
    press(pg, "3")
    check(wait_js(pg, "CheckShell.state().cur !== 'value:e2e:03'") and fq.answers[-1]["body"]["answer"] == {"choice": "unknown", "score": 3},
          "点の 3 = 不明として記録: %s" % fq.answers[-1]["body"]["answer"])
    cur = state(pg)["cur"]
    pg.evaluate("document.dispatchEvent(new KeyboardEvent('keydown', {key: '5', repeat: true, bubbles: true}))")
    pg.wait_for_timeout(300)
    check(state(pg)["cur"] == cur and len(fq.answers) == n0 + 1, "数字のキーでは答えない(11-02 にキーを消した): %s" % state(pg)["cur"])
    press(pg, "z")
    wait_js(pg, "CheckShell.state().cur === 'value:e2e:03'")


def _scene_kinds(cx):
    pg, check, fq = cx.pg, cx.check, cx.fq
    pg.goto(cx.base + "check")
    check(wait_js(pg, "CheckShell.state().cur === 'value:e2e:03'"), "開き直すと、答えた・飛ばしたカードの次から: %s" % state(pg))
    press(pg, "4")
    check(wait_js(pg, "CheckShell.state().kind === 'voice'") and fq.answers[-1]["body"]["card"] == "value:e2e:03", "点の 4 で答えると次は誰の声のカード: %s" % state(pg))
    check(wait_js(pg, "!!document.querySelector('#chkBody video')"), "誰の声のカードは動画を出す")
    check(pg.evaluate("document.querySelector('#chkBody video').volume") == 0.5, "音量の既定は半分")
    pg.evaluate("document.querySelector('#chkBody video').volume = 0.3")
    check(wait_js(pg, "JSON.parse(localStorage.getItem('check.volume') || '{}').volume === 0.3"), "変えた音量を覚える(次のカードで使う)")
    check(pg.query_selector("#chkBody [data-chk-k='NONE']") is not None and "予想どおり" not in pg.text_content("#chkBody"), "話者カード: 予想どおりは無い(11-02)")
    check(wait_js(pg, "(() => { const v = document.querySelector('#chkBody video'); return v && !v.paused && v.currentTime > 0.4; })()", 10000), "出したら自動で再生(区間の頭から)")
    check(wait_js(pg, "(() => { const v = document.querySelector('#chkBody video'); return v && v.paused && v.currentTime >= 1.6 && v.currentTime < 2.3; })()", 10000),
          "区間の末 + pad で止まる: %s" % pg.evaluate("document.querySelector('#chkBody video').currentTime"))
    stopped = "(() => { const v = document.querySelector('#chkBody video'); return v && v.paused && v.currentTime >= 1.6; })()"
    replayed = "(() => { const v = document.querySelector('#chkBody video'); return v && !v.paused && v.currentTime < 1.2; })()"
    press(pg, "r")
    check(wait_js(pg, replayed, 5000) and state(pg)["kind"] == "voice", "終わった後の [もう一度聞く] = 区間の頭から流し直す(答えない)")
    check(wait_js(pg, stopped, 10000), "流し直しも区間の末で止まる")
    pg.click("[data-chk-replay]")
    check(wait_js(pg, replayed, 5000), "[もう一度聞く] のボタンも頭から")
    check(wait_js(pg, stopped, 10000), "ボタンの流し直しも末で止まる")
    pg.evaluate("document.activeElement && document.activeElement.blur()")
    press(pg, "Space")   # 10-25 ユーザー: 区間の頭へ戻して末で止めるのは最初の自動再生と もう一度聞く だけ
    check(wait_js(pg, "(() => { const v = document.querySelector('#chkBody video'); return v && !v.paused && v.currentTime > 2.3; })()", 5000),
          "末で止まった後の Space = 今の位置から止めずに流す(行の後ろも聞ける): %s" % pg.evaluate("document.querySelector('#chkBody video').currentTime"))
    t_pause = pg.evaluate("(() => { const v = document.querySelector('#chkBody video'); v.pause(); return v.currentTime; })()")   # 区間(末 1.7 秒)の後ろで一時停止
    pg.wait_for_timeout(200)
    pg.evaluate("document.querySelector('#chkBody video').play()")   # 動画の再生ボタン
    pg.wait_for_timeout(300)
    t_play = pg.evaluate("document.querySelector('#chkBody video').currentTime")
    check(t_play >= t_pause and not pg.evaluate("document.querySelector('#chkBody video').paused"),
          "区間の後ろで止めて再生ボタン = その位置から流す(区間の頭へ戻さない・止めない): %s → %s" % (t_pause, t_play))   # シークはこの試しの動画の配り方(Range なし)では 0 秒へ戻るので見ない
    pg.evaluate("document.querySelector('#chkBody video').pause()")
    press(pg, "N1")
    press(pg, "Enter")
    check(wait_js(pg, "CheckShell.state().kind === 'time'") and fq.answers[-1]["body"]["answer"] == {"names": ["配信者 B"]}, "名前を選んで決める = {names}: %s" % fq.answers[-1:])
    n_before = len(fq.answers)
    check(wait_js(pg, "(() => { const v = document.querySelector('#chkBody video'); return !v || v.volume === 0.3; })()"), "次のカードも覚えた音量")
    check(wait_js(pg, "!!document.querySelector('#chkBody canvas[data-chk-wave]')") and wait_js(pg, "!document.querySelector('[data-chk-wavemsg]').textContent"),
          "時刻のカードに波形の帯(peaks を読めた)")
    check(cx.retime_hits and cx.retime_hits[0] == {"id": "a0000000000c", "rows": ["r6"]}, "単語の印は POST transcribe/api/retime {id, rows:[行]}: %s" % cx.retime_hits[:1])
    check(cx.peaks_hits and "id=a0000000000c" in cx.peaks_hits[0], "波形は transcribe/api/peaks?id=<文書 id>: %s" % cx.peaks_hits[:1])
    check("B1 行の時刻" in pg.text_content("#chkGoal") and "目標に届きました" in pg.text_content("#chkGoal"), "帯はカードの種類の目標(goals): %r" % pg.text_content("#chkGoal"))
    check(wait_js(pg, "!!document.querySelector('[data-chk-tguide]').textContent"), "単語の時刻の候補(api/retime)を点線の参考の印と文で出す: %r" % pg.text_content("[data-chk-tguide]"))
    tv = "document.querySelector('#chkBody video')"   # 時刻のカード = 窓(0.5〜2.5 秒)の中だけ流す(波形と再生位置を合わせたまま)
    check(wait_js(pg, "(() => { const v = %s; return v && v.paused && v.currentTime >= 2.3; })()" % tv, 10000), "時刻: 自動再生は窓の末で止まる")
    pg.evaluate("document.activeElement && document.activeElement.blur()")
    press(pg, "Space")
    check(wait_js(pg, "(() => { const v = %s; return v && !v.paused && v.currentTime < 1.2; })()" % tv, 5000),
          "時刻: 末で止まった後の Space は窓の頭から(窓の外へ出さない): %s" % pg.evaluate("%s.currentTime" % tv))
    check(wait_js(pg, "(() => { const v = %s; return v && v.paused && v.currentTime >= 2.3 && v.currentTime < 2.8; })()" % tv, 10000),
          "時刻: 自分で流しても窓の末で止まる: %s" % pg.evaluate("%s.currentTime" % tv))
    check(pg.is_hidden("[data-chk-nudge]") and "ちょうどいい" in pg.text_content("[data-chk-tstate]"), "印を選ぶ前は動かすボタンを出さない")
    press(pg, "h")
    check(pg.get_attribute("#chkBody .chk-marks [data-chk-k='H']", "aria-pressed") == "true" and pg.is_visible("[data-chk-nudge]"), "[頭がずれている] は段 3 の印(押した状態)・動かすボタンが出る")
    for _ in range(3):
        press(pg, "M1")
    check("頭がずれている" in pg.text_content("[data-chk-tstate]") and "−0.10 秒" in pg.text_content("[data-chk-tstate]"), "頭を選び [−1] 3 回 = 0.10 秒前へ: %r" % pg.text_content("[data-chk-tstate]"))
    check(pg.text_content("#chkBody .chk-acts [data-chk-k='Enter']").strip() == "この時刻で答える", "動かすと答えのボタンは「この時刻で答える」")
    check(state(pg)["kind"] == "time" and len(fq.answers) == n_before, "動かしただけでは答えない")
    press(pg, "t")   # 読みを直す(10-26)
    check(pg.is_visible("#chkBody [data-chk-retext] input") and pg.evaluate("document.activeElement.id === 'chkTimeText'"), "[読みを直す] で欄が開き、そこに入る")
    pg.fill("#chkTimeText", "直した読み")
    press(pg, "Enter")
    check(state(pg)["kind"] == "time" and len(fq.answers) == n_before and "直した読み" in (pg.text_content("[data-chk-newtext]") or ""),
          "欄の Enter は文字を決めるだけ(答えない)")
    press(pg, "Enter")
    check(wait_js(pg, "CheckShell.state().kind === 'value'") and fq.answers[-1]["body"]["answer"] == {"choice": "head", "dStart": -0.1, "dEnd": 0, "text": "直した読み"},
          "[この時刻で答える] で答える(動かした量と直した文字つき): %s" % fq.answers[-1]["body"]["answer"])


def _scene_summary_and_end(cx):
    pg, check = cx.pg, cx.check
    pg.goto(cx.base + "check?c=v1&back=cases")
    check(wait_js(pg, "!!CheckShell.state().cur"), "開き直すと続きから")
    for _ in range(10):
        press(pg, answer_key(pg))
    check(wait_js(pg, "!!CheckShell.state().cur") and pg.locator("#chkSum").count() == 0, "10 件答えても止めずに次のカード: %s" % state(pg))
    check("10 件答えました" in pg.text_content("#chkAnswered") and "この確認で決まる物" in pg.text_content("#chkGoal"),
          "答えた数と目標は端に出したまま: %r %r" % (pg.text_content("#chkAnswered"), pg.text_content("#chkGoal")))
    for _ in range(40):
        if not state(pg)["cur"]:
            break
        press(pg, answer_key(pg))
    check(wait_js(pg, "CheckShell.state().empty"), "全部答えたら空の状態: %s" % state(pg))
    check("今日の分は終わりです" in pg.text_content("#chkEmpty") and pg.get_attribute("#chkEmpty a.btn.primary", "href") == "cases?c=v1",
          "空の状態の文と 案件へ戻る(back=cases)")
    press(pg, "z")
    check(wait_js(pg, "!!CheckShell.state().cur && !CheckShell.state().empty"), "空の状態からも Z で 1 つ前に戻る")


def _scene_failures(cx):
    pg, check, fq = cx.pg, cx.check, cx.fq
    fq.fail_answer = 1
    cur = state(pg)["cur"]
    press(pg, answer_key(pg))
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
    """話者カード(誰の声・11-02): 予想を初めから選ばない・予想どおりのボタンは無い・選ぶまで決めるは押せない・名前を選んで決める = {names}・
    名前を選んでいる間は声なしは押せない・Z で戻す・声なし = {choice: other}"""
    pg, check = cx.pg, cx.check
    vid = {"url": "transcribe/media?id=a0000000000b", "start": 0.5, "end": 1.5, "pad": 0.2}
    fv = FakeQueue([card(30, "voice", source="diar", media=vid, guess={"id": "name:みこ", "name": "みこ"}, note="below_match",
                         options=[{"id": "S1", "name": "ぺこら", "voice": True}, {"id": "name:みこ", "name": "みこ", "voice": True},
                                  {"id": "other", "name": "その他"}, {"id": "mixed", "name": "混ざり"}])])
    _swap_queue(cx, fv)
    enter, none = "#chkBody [data-chk-k='Enter']", "#chkBody [data-chk-k='NONE']"
    try:
        pg.goto(cx.base + "check?kind=voice")
        check(wait_js(pg, "CheckShell.state().cur === 'voice:e2e:30'"), "話者のカードを開く: %s" % state(pg))
        names = pg.evaluate("[...document.querySelectorAll('#chkBody .chk-spk-name')].map(b => [b.textContent.trim(), b.getAttribute('aria-pressed')])")
        check(names[:2] == [["ぺこら", "false"], ["みこ", "false"]] and [n for n, _p in names[2:]] == ["誰か分からないメンバー", "メンバー以外の人", "ゲームの声"],
              "出るはずの人の名前のボタン(予想を選んでおかない)+ 札 3 つ: %s" % names)
        check("予想どおり" not in (pg.text_content("#chkBody") or "") and pg.is_disabled(enter) and not pg.is_disabled(none), "予想どおりは無い・選ぶまで決めるは押せない")
        press(pg, "N1")
        check(pg.is_disabled(none) and "みこ" in pg.text_content(enter), "名前を選んでいる間は声なしは押せない・決めるに選んだ人")
        press(pg, "Enter")
        check(wait_js(pg, "CheckShell.state().empty") and fv.answers[-1]["body"]["answer"] == {"names": ["みこ"]}, "決める = {names}: %s" % fv.answers[-1:])
        press(pg, "z")
        check(wait_js(pg, "CheckShell.state().cur === 'voice:e2e:30'"), "Z で戻す")
        press(pg, "NONE")
        check(wait_js(pg, "CheckShell.state().empty") and fv.answers[-1]["body"]["answer"] == {"choice": "other"}, "声なし = {choice: other}: %s" % fv.answers[-1:])
    finally:
        _restore_queue(cx)


def _scene_rate_kept(cx):
    """再生速度をカードをまたいで覚える(10-29 ユーザー「毎回変えるのめんどくさい」): 変えた速さで次のカードも・開き直しても・K(止める)は覚えた速さへ"""
    pg, check = cx.pg, cx.check
    vid = {"url": "transcribe/media?id=a0000000000b", "start": 0.5, "end": 1.5, "pad": 0.2}
    fr = FakeQueue([card(i, "value", media=vid, options=["good", "bad"], reasons=[{"id": "boring", "text": "場面がつまらない"}]) for i in (70, 71, 72)])
    _swap_queue(cx, fr)
    rate = "(() => { const v = document.querySelector('#chkBody video'); return v ? [v.playbackRate, v.defaultPlaybackRate] : null; })()"
    try:
        pg.evaluate("localStorage.removeItem('check.rate')")
        pg.goto(cx.base + "check?kind=value")
        check(wait_js(pg, "CheckShell.state().cur === 'value:e2e:70' && !!document.querySelector('#chkBody video')"), "動画のある価値のカード: %s" % state(pg))
        check(pg.evaluate(rate) == [1, 1], "覚えた速さが無ければ 1 倍: %s" % pg.evaluate(rate))
        pg.evaluate("document.querySelector('#chkBody video').playbackRate = 1.5")   # 動画の速さのメニューで変えたのと同じ
        check(wait_js(pg, "localStorage.getItem('check.rate') === '1.5'"), "変えた速さを覚える: %s" % pg.evaluate("localStorage.getItem('check.rate')"))
        press(pg, "4")
        check(wait_js(pg, "CheckShell.state().cur === 'value:e2e:71' && !!document.querySelector('#chkBody video')") and pg.evaluate(rate) == [1.5, 1.5],
              "次のカードも最初から 1.5 倍: %s" % pg.evaluate(rate))
        pg.goto(cx.base + "check?kind=value")
        check(wait_js(pg, "!!document.querySelector('#chkBody video')") and pg.evaluate(rate) == [1.5, 1.5], "開き直しても 1.5 倍: %s" % pg.evaluate(rate))
        # 速さの選び方(10-29 ユーザー「4 倍まで刻んで出して」): 再生の横の「速さ」で 1〜4 倍・声の高さを保つ・覚えた速さは段にそろえる
        opts = pg.evaluate("[...document.querySelectorAll('#chkBody [data-chk-rate] option')].map(o => +o.value)")
        check(opts == [1, 1.25, 1.5, 1.75, 2, 2.5, 3, 3.5, 4] and pg.input_value("#chkBody [data-chk-rate]") == "1.5", "速さの段は 4 倍まで・今の 1.5 倍を指す: %s" % opts)
        pg.select_option("#chkBody [data-chk-rate]", "4")
        check(pg.evaluate(rate) == [4, 4] and pg.evaluate("localStorage.getItem('check.rate')") == "4", "4 倍を選ぶと 4 倍で覚える: %s" % pg.evaluate(rate))
        check(pg.evaluate("document.querySelector('#chkBody video').preservesPitch") is True, "速くしても声の高さを保つ(preservesPitch)")
        check(pg.evaluate("document.activeElement === document.body || !document.activeElement.matches('select')"), "選んだあとのキーはカードへ(速さの欄から外す)")
        pg.evaluate("document.querySelector('#chkBody video').playbackRate = 2.7")   # 段に無い速さ(動画のメニューなど)= 一番近い段で覚える
        check(wait_js(pg, "localStorage.getItem('check.rate') === '2.5'") and pg.input_value("#chkBody [data-chk-rate]") == "2.5", "段に無い速さは一番近い段で覚える")
    finally:
        pg.evaluate("localStorage.removeItem('check.rate')")
        _restore_queue(cx)


def _scene_voice_bgm_and_gone(cx):
    """話者カード: BGM が大きい・声色が違う の印(段 3)を入れて決める = {names, bgm, alt}・次のカードでは切れている。答えに 404 gone が返ったカードは戻さず次へ・もう出ない"""
    pg, check = cx.pg, cx.check
    opts = [{"id": "S1", "name": "ぺこら"}, {"id": "other", "name": "その他"}, {"id": "mixed", "name": "混ざり"}]
    fv = FakeQueue([card(i, "voice", source="solo", options=opts, cast=["ぺこら"]) for i in (40, 41, 42)])
    fv.gone.add("voice:e2e:41")
    _swap_queue(cx, fv)
    try:
        pg.goto(cx.base + "check?kind=voice")
        check(wait_js(pg, "CheckShell.state().cur === 'voice:e2e:40'"), "話者のカード(ソロ)を開く: %s" % state(pg))
        press(pg, "BGM")
        press(pg, "ALT")
        check(pg.get_attribute("#chkBody [data-chk-k='BGM']", "aria-pressed") == "true" and pg.get_attribute("#chkBody [data-chk-k='ALT']", "aria-pressed") == "true",
              "BGM が大きい・声色が違う は段 3 の印(押した状態)")
        press(pg, "1")
        check(wait_js(pg, "CheckShell.state().cur === 'voice:e2e:41'") and fv.answers[-1]["body"]["answer"] == {"names": ["ぺこら"], "bgm": True, "alt": True},
              "印のあと名前で決める = {names, bgm, alt}: %s" % fv.answers[-1:])
        check(pg.get_attribute("#chkBody [data-chk-k='BGM']", "aria-pressed") == "false", "次のカードでは印は切れている")
        press(pg, "1")
        check(wait_js(pg, "[...document.querySelectorAll('.ui-toast')].some(t => t.textContent.includes('次へ進みます'))"), "gone: 次へ進む知らせ")
        check(wait_js(pg, "CheckShell.state().cur === 'voice:e2e:42'"), "gone: 戻さずに次のカード: %s" % state(pg))
        press(pg, "1")
        check(wait_js(pg, "CheckShell.state().empty") and "voice:e2e:41" not in [a["body"]["card"] for a in fv.answers], "gone のカードはもう出ない: %s" % state(pg))
    finally:
        _restore_queue(cx)


def _scene_unknown(cx):
    """[分からない](W・ボタン): unknown の口へ送り、もう出ない・今日の数に入れない・Z で戻すとまた出る(undo に分からないの id)"""
    pg, check = cx.pg, cx.check
    fv = FakeQueue([card(i, "value", score=50) for i in (60, 61, 62)])
    _swap_queue(cx, fv)
    try:
        pg.goto(cx.base + "check?kind=value")
        check(wait_js(pg, "CheckShell.state().cur === 'value:e2e:60'"), "分からない: カードを開く: %s" % state(pg))
        check(pg.is_visible("#chkUnknown") and pg.text_content("#chkUnknown").strip() == "分からない(もう出さない)", "[分からない(もう出さない)] のボタン")
        check(wait_js(pg, "document.body.textContent.includes('分からない')"), "キーの表示に 分からない")
        press(pg, "w")
        check(wait_js(pg, "CheckShell.state().cur === 'value:e2e:61'") and [u["body"]["card"] for u in fv.unknowns] == ["value:e2e:60"] and not fv.answers,
              "W = unknown の口へ送る(答えではない): %s" % fv.unknowns)
        check(state(pg)["today"] == 0 and pg.text_content("#chkToday") == "0", "今日の数に入れない")
        press(pg, "z")
        check(wait_js(pg, "CheckShell.state().cur === 'value:e2e:60'") and fv.undone == ["unk001"], "Z で戻すとまた出る(undo に分からないの id): %s" % fv.undone)
        check(state(pg)["today"] == 0, "戻しても今日の数は 0 のまま")
        pg.click("#chkUnknown")
        check(wait_js(pg, "CheckShell.state().cur === 'value:e2e:61'") and len(fv.unknowns) == 2, "ボタンでも同じ")
        pg.goto(cx.base + "check?kind=value")
        check(wait_js(pg, "CheckShell.state().cur === 'value:e2e:61'"), "開き直しても 分からない のカードは出ない: %s" % state(pg))
    finally:
        _restore_queue(cx)


def _scene_voice_pick(cx):
    """話者カード: [ほかのメンバーを足す] = 探す欄(ひらがな・ローマ字・呼び名)と期ごとの名前の札。押した人は名前のボタンの最後に「足した」で加わり選ばれる・
    何人でも足せる・探す欄の Enter = 1 人に絞れたら足す・名簿に無い名前も足せる・[閉じる] で畳む"""
    pg, check = cx.pg, cx.check
    opts = [{"id": "S1", "name": "ぺこら"}, {"id": "other", "name": "その他"}, {"id": "mixed", "name": "混ざり"}]
    fv = FakeQueue([card(i, "voice", source="solo", options=opts, cast=["ぺこら"]) for i in (70, 71)])
    _swap_queue(cx, fv)
    find = "#chkBody [data-chk-find]"
    added = "[...document.querySelectorAll('#chkBody .chk-spk-name')].filter(b => b.querySelector('.chk-spk-added')).map(b => [b.firstChild.textContent, b.getAttribute('aria-pressed')])"
    try:
        pg.goto(cx.base + "check?kind=voice")
        check(wait_js(pg, "CheckShell.state().cur === 'voice:e2e:70'"), "話者のカード(足す)を開く: %s" % state(pg))
        check(pg.query_selector(find) is None, "ふだんは「ほかのメンバーを足す」のボタンだけ")
        press(pg, "OPEN")
        check(wait_js(pg, "!!document.querySelector('#chkBody [data-chk-find]') && document.querySelectorAll('#chkBody .chk-spk-group').length === 2")
              and pg.evaluate("document.activeElement && document.activeElement.matches('[data-chk-find]')"), "開くと探す欄(入っている)と期ごとの札")
        check(pg.evaluate("getComputedStyle(document.querySelector('#chkBody .chk-spk-chip .chk-spk-dot')).backgroundColor") != "rgba(0, 0, 0, 0)", "札にメンバーの色を小さく添える")
        pg.keyboard.type("せんちょう")
        check(wait_js(pg, "[...document.querySelectorAll('#chkBody [data-chk-found] .chk-spk-chip')].map(b => b.dataset.chkAdd).join() === '宝鐘マリン'"), "呼び名の読み(せんちょう)で絞れる")
        press(pg, "Enter")
        check(wait_js(pg, "JSON.stringify(%s) === JSON.stringify([['宝鐘マリン', 'true']])" % added), "探す欄の Enter = 1 人に絞れたら足して選ぶ: %s" % pg.evaluate(added))
        pg.fill(find, "pekora")
        pg.click("#chkBody [data-chk-found] [data-chk-add='兎田ぺこら']")
        check(wait_js(pg, "%s.length === 2" % added), "ローマ字でも探せる・何人でも続けて足せる: %s" % pg.evaluate(added))
        pg.fill(find, "Guest m1")
        pg.click("#chkBody [data-chk-found] [data-chk-add='Guest m1']")
        press(pg, "CLOSE")
        check(pg.query_selector(find) is None and pg.evaluate("%s.length" % added) == 3, "名簿に無い名前も足せる・[閉じる] で畳む")
        press(pg, "Enter")
        check(wait_js(pg, "CheckShell.state().cur === 'voice:e2e:71'") and fv.answers[-1]["body"]["answer"] == {"names": ["宝鐘マリン", "兎田ぺこら", "Guest m1"]},
              "足した人で決める: %s" % fv.answers[-1:])
    finally:
        _restore_queue(cx)


def _scene_voice_others(cx):
    """話者カード: 札(誰か分からないメンバー・メンバー以外の人・ゲームの声)は人と同じく選ぶ・2 人以上も選べる"""
    pg, check = cx.pg, cx.check
    opts = [{"id": "S1", "name": "ぺこら"}, {"id": "other", "name": "その他"}, {"id": "mixed", "name": "混ざり"}]
    fv = FakeQueue([card(i, "voice", source="solo", options=opts, cast=["ぺこら"]) for i in (60, 61)])
    _swap_queue(cx, fv)
    try:
        pg.goto(cx.base + "check?kind=voice")
        check(wait_js(pg, "CheckShell.state().cur === 'voice:e2e:60'"), "話者のカード(札)を開く: %s" % state(pg))
        press(pg, "NS0")
        press(pg, "Enter")
        check(wait_js(pg, "CheckShell.state().cur === 'voice:e2e:61'") and fv.answers[-1]["body"]["answer"] == {"names": ["誰か分からないメンバー"]},
              "札だけで決める: %s" % fv.answers[-1:])
        press(pg, "N0")
        press(pg, "NS2")
        press(pg, "Enter")
        check(wait_js(pg, "CheckShell.state().empty") and fv.answers[-1]["body"]["answer"] == {"names": ["ぺこら", "ゲームの声"]}, "2 人以上も選べる: %s" % fv.answers[-1:])
    finally:
        _restore_queue(cx)


def _scene_voice_video_or_clip(cx):
    """誰の声(ソロ)のカード: 元の動画がある文書は映像つき(transcribe/media の <video> に映像の大きさがある)・切り出した行の音(api/check/voiceclip)は
    音だけ(映像の大きさ 0)で流れる(10-25: 0.99.207 から動画のある文書も音だけになっていた)。どちらの形を出すかは app/check/voice_solo(単体で確かめる)"""
    pg, check = cx.pg, cx.check
    opts = [{"id": "S1", "name": "ぺこら"}, {"id": "other", "name": "その他"}, {"id": "mixed", "name": "混ざり"}]
    fv = FakeQueue([card(50, "voice", source="solo", options=opts, media={"url": "transcribe/media?id=a0000000000b", "start": 0.5, "end": 1.5, "pad": 0.2}),
                    card(51, "voice", source="solo", options=opts, media={"url": "api/check/voiceclip?doc=a0000000000b&row=r51", "start": 1.0, "end": 2.0, "pad": 0.2})])
    clip_re = re.compile(r".*/api/check/voiceclip.*")
    _swap_queue(cx, fv)
    cx.ctx.route(clip_re, lambda route: route.fulfill(status=200, body=cx.wav, headers={"Content-Type": "audio/wav", "Accept-Ranges": "none"}))
    size = "(() => { const v = document.querySelector('#chkBody video'); return v && v.readyState >= 1 ? [v.videoWidth, v.videoHeight] : null; })()"
    try:
        pg.goto(cx.base + "check?kind=voice")
        check(wait_js(pg, "CheckShell.state().cur === 'voice:e2e:50'"), "声のカード(ソロ・動画あり)を開く: %s" % state(pg))
        check(wait_js(pg, "(() => { const v = document.querySelector('#chkBody video'); return !!v && v.videoWidth > 0; })()", 10000),
              "元の動画がある文書は映像つきで流れる: %s" % pg.evaluate(size))
        press(pg, "1")
        check(wait_js(pg, "CheckShell.state().cur === 'voice:e2e:51'"), "次のカード(切り出した音): %s" % state(pg))
        check(wait_js(pg, "(() => { const v = document.querySelector('#chkBody video'); return !!v && v.readyState >= 1 && v.src.includes('api/check/voiceclip'); })()", 10000)
              and pg.evaluate("document.querySelector('#chkBody video').videoWidth") == 0, "切り出した音は音だけで流れる: %s" % pg.evaluate(size))
        press(pg, "1")
        check(wait_js(pg, "CheckShell.state().empty"), "全部答えた")
    finally:
        cx.ctx.unroute(clip_re)
        _restore_queue(cx)


def _scene_speaker(cx):
    """話者カード(10 秒の区間。画面は speaker.js = ソロの 10 秒 speaker:solo。11-02 まではコラボの 10 秒 speaker:collab も): 出る人の全員が名前のボタン・予想なし・選ばずに決めるは押せない・何人でも選んで決める = {names}・
    ほかのメンバーを足す・メンバー以外の人の札は その他の人 の名前で送る(前の答えと同じ)・声なし。YTT_E2E_SHOT があれば、そのパスにカードの写真を撮る"""
    pg, check = cx.pg, cx.check
    def sc(i, people):
        return card(i, "speaker", source="solo", target={"videoId": "AAAAAAAAAAA", "solo": "c1r%02d" % i, "piece": [0.0, 1.0], "docId": None, "row": None},
                    media={"url": "api/check/voicesolo?key=c1r%02d" % i, "start": 0.0, "end": 1.0, "pad": 0.0, "padEnd": 0.0}, text="",
                    people=people, cast=people, otherPerson="その他の人", case={"id": "AAAAAAAAAAA", "title": "ド珍検証会(ド珍組)"})
    four = ["さくらみこ", "白上フブキ", "大神ミオ", "大空スバル"]
    fs = FakeQueue([sc(i, four) for i in (90, 91, 92, 93)])
    clip_re = re.compile(r".*/api/check/voicesolo.*")
    _swap_queue(cx, fs)
    cx.ctx.route(clip_re, lambda route: route.fulfill(status=200, body=cx.wav, headers={"Content-Type": "audio/wav", "Accept-Ranges": "none"}))
    names = "[...document.querySelectorAll('#chkBody .chk-spk-names .chk-spk-name')].map(b => [b.firstChild.textContent, b.getAttribute('aria-pressed')])"
    try:
        pg.goto(cx.base + "check?kind=voice")
        check(wait_js(pg, "CheckShell.state().cur === 'speaker:e2e:90'") and fs.next_q[-1].get("kind") == ["voice"],
              "コラボの区間も「話者」(kind=voice)で出る: %s" % state(pg))
        got = pg.evaluate(names)
        check([n for n, _p in got][:4] == four and all(p_ == "false" for _n, p_ in got), "出る人の全員が名前のボタン(並びはカードのまま): %s" % got)
        check("予想" not in (pg.text_content("#chkBody") or "") and pg.is_disabled("#chkBody [data-chk-k='Enter']"), "予想なし・選ばずに決めるは押せない")
        press(pg, "N1")
        press(pg, "N3")
        shot = os.environ.get("YTT_E2E_SHOT")
        if shot:
            pg.screenshot(path=shot, full_page=True)
        press(pg, "Enter")
        check(wait_js(pg, "CheckShell.state().cur === 'speaker:e2e:91'") and fs.answers[-1]["body"]["answer"] == {"names": ["白上フブキ", "大空スバル"]},
              "決める = 選んだ人を全員 {names}: %s" % fs.answers[-1:])
        press(pg, "OPEN")
        wait_js(pg, "!!document.querySelector('#chkBody [data-chk-add=\"兎田ぺこら\"]')")
        pg.click("#chkBody [data-chk-add='兎田ぺこら']")
        check(wait_js(pg, "[...document.querySelectorAll('#chkBody .chk-spk-name')].some(b => b.textContent.includes('兎田ぺこら') && b.getAttribute('aria-pressed') === 'true')"),
              "ほかのメンバーを足すと名前のボタンに足して選んだ状態: %s" % pg.evaluate(names))
        pg.click("#chkBody [data-chk-k='Enter']")   # 探す欄にいるので決めるはボタンで
        check(wait_js(pg, "CheckShell.state().cur === 'speaker:e2e:92'") and fs.answers[-1]["body"]["answer"] == {"names": ["兎田ぺこら"]}, "足した人で答える: %s" % fs.answers[-1:])
        press(pg, "N0")
        press(pg, "NS1")
        press(pg, "Enter")
        check(wait_js(pg, "CheckShell.state().cur === 'speaker:e2e:93'") and fs.answers[-1]["body"]["answer"] == {"names": ["さくらみこ", "その他の人"]},
              "メンバー以外の人 = その他の人 の名前で送る(前の答えと同じ): %s" % fs.answers[-1:])
        press(pg, "NONE")
        check(wait_js(pg, "CheckShell.state().empty") and fs.answers[-1]["body"]["answer"] == {"choice": "other"}, "声なし: %s" % fs.answers[-1:])
    finally:
        cx.ctx.unroute(clip_re)
        _restore_queue(cx)


def _scene_symbol(cx):
    """記号のカード(11-02 の案 1): 1 か所 = 1 枚・文脈に色・消した後の文・名前と全角 / 半角・場面・消してよい / 残す / 迷う。
    種類で記号を選ぶと上に記号の決まりの欄(決まりの案を 認める / 認めない・迷うの一覧の もう一度答える = その答えの Z)"""
    pg, check = cx.pg, cx.check
    def sym(i):
        return card(i, "symbol", source="asr", text="・", media=None, target={"symbol": "u30fb", "docId": "a0000000000a", "row": None, "seg": 0, "at": 3, "scene": ["kana", "kana"]},
                    context={"left": "うん", "right": "そう", "removed": "うんそう", "title": "テストの配信"}, name="中黒(全角)", scene="かなとかなの間", sceneCount=5)
    fy = FakeQueue([sym(i) for i in (95, 96)])
    fy.symrules = {"proposals": [{"ch": "・", "left": "kana", "right": "kana", "label": "かなとかなの間", "action": "remove", "n": 3, "ok": 3, "keep": 0, "unsure": 0,
                                  "text": "かなとかなの間の「・」は消す"}], "rules": [],
                   "unsure": [{"answer": "ans009", "card": "symbol:e2e:90", "ch": "・", "label": "かなとかなの間", "text": "うん[・]そう", "at": 1}]}
    _swap_queue(cx, fy)
    try:
        pg.goto(cx.base + "check?kind=symbol")
        check(wait_js(pg, "CheckShell.state().cur === 'symbol:e2e:95'"), "記号のカードを開く: %s" % state(pg))
        body = pg.text_content("#chkBody") or ""
        check("中黒(全角)" in body and "消した後: うんそう" in body and "かなとかなの間" in body and pg.text_content("#chkBody mark") == "・",
              "名前と全角 / 半角・消した後の文・場面・文脈の記号に色: %r" % body[:160])
        check(wait_js(pg, "!document.querySelector('#chkSymHead').hidden && document.querySelector('#chkSymHead').textContent.includes('かなとかなの間の「・」は消す')"),
              "記号を選ぶと上に記号の決まりの欄(案)")
        pg.click("#chkSymHead [data-chk-sym-ok='1']")
        check(wait_for(lambda: fy.sym_posts == [{"ch": "・", "left": "kana", "right": "kana", "action": "remove", "approve": True}]), "認める = POST symbolrules: %s" % fy.sym_posts)
        press(pg, "U")
        check(wait_js(pg, "CheckShell.state().cur === 'symbol:e2e:96'") and fy.answers[-1]["body"]["answer"] == {"choice": "unsure"}, "迷う = {choice: unsure}: %s" % fy.answers[-1:])
        pg.click("#chkSymHead summary")
        pg.click("#chkSymHead [data-chk-sym-redo='ans009']")
        check(wait_for(lambda: "ans009" in fy.undone), "迷うの一覧の もう一度答える = その答えの Z: %s" % fy.undone)
        press(pg, "A")
        check(wait_for(lambda: fy.answers[-1]["body"]["answer"] == {"choice": "ok"}), "消してよい = {choice: ok}: %s" % fy.answers[-1:])
    finally:
        _restore_queue(cx)


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
        check(pg.evaluate("(() => { const d = document.querySelector('#chkBody .chk-dock'); return !!d && getComputedStyle(d).position === 'sticky' && !!d.querySelector('.chk-acts [data-chk-k=Enter]') && !!d.querySelector('#chkFoot'); })()"),
              "区間: 段 2 と共通の枠は画面の下に留める(.chk-dock = sticky)")
        press(pg, "Enter")
        check(wait_js(pg, "CheckShell.state().cur === 'section:e2e:72'") and fe.answers[-1]["body"]["answer"] == {}, "何も変えず Enter = {}: %s" % fe.answers[-1:])
        # 2 枚目: 直す
        pg.fill("#chkBody li[data-sec-row=r1] [data-sec-text]", "直した字幕")
        check("直して答える" in pg.text_content(enter), "直すとボタンが 直して答える に変わる: %r" % pg.text_content(enter))
        pg.select_option("#chkBody li[data-sec-row=r1] [data-sec-spk]", "みこ")
        pg.check("#chkBody li[data-sec-row=r2] [data-sec-drop]")
        pg.evaluate("document.activeElement && document.activeElement.blur()")
        pg.click("#chkBody [data-sec-addrow]")
        check(pg.evaluate("document.querySelectorAll('#chkBody li[data-sec-add]').length") == 1, "[行を足す] で足す行の欄が増える")
        check(pg.evaluate("document.activeElement.matches('[data-sec-add] [data-sec-text]')"), "足す行の文字の欄に入る")
        pg.fill("#chkBody li[data-sec-add] [data-sec-a]", "7")
        pg.fill("#chkBody li[data-sec-add] [data-sec-b]", "9.5")
        pg.fill("#chkBody li[data-sec-add] [data-sec-text]", "足した言葉")
        check("同時に話していたら" in pg.text_content(body) and pg.evaluate("document.querySelectorAll('#chkBody li[data-sec-row=r1] [data-sec-memo]').length") == 3,
              "案内の 1 行と、行ごとのメモ 3 つ(重なり・BGM 大・聞き取れない)")
        pg.select_option("#chkBody li[data-sec-add] [data-sec-spk]", "__game__")   # 話者の「ゲームの音」
        pg.check("#chkBody li[data-sec-add] [data-sec-memo=overlap]")
        pg.focus("#chkBody li[data-sec-add] [data-sec-text]")
        press(pg, "Enter")
        check(state(pg)["cur"] == "section:e2e:72", "入力中の Enter では答えない")
        pg.click(enter)
        check(wait_js(pg, "CheckShell.state().empty"), "[直して答える] で答える: %s" % state(pg))
        want = {"rows": [{"id": "r1", "text": "直した字幕", "speaker": "みこ"}, {"id": "r2", "drop": True}], "add": [{"start": 7, "end": 9.5, "text": "足した言葉", "game": True, "tags": ["overlap"]}]}
        check(fe.answers[-1]["body"]["answer"] == want, "直した答えの中身: %s" % fe.answers[-1]["body"]["answer"])
        pg.click("#chkEvalHead [data-chk-eb=stop]")
        check(wait_for(lambda: hits["stop"] == [{}]), "止める = POST eval-batch/stop {}: %s" % hits["stop"])
    finally:
        _restore_queue(cx, eval_routes)


def _scene_kind_pick(cx):
    """種類の切り替え: 残りの枚数(0 は薄い)・押すと口へ kind を渡してその種類だけ・押した後のキーはカードへ・次に開いても同じ種類・URL の kind が先"""
    pg, check = cx.pg, cx.check
    gap = card(83, "cut", source="gap", target={"cut": [1.0, 2.5], "docId": "a0000000000e"},
               media={"url": "transcribe/media?id=a0000000000e", "start": 0.0, "end": 4.0, "pad": 0.0}, text="", note="自動カットのテスト")
    fk = FakeQueue([card(81, "value", options=["good", "bad"]), card(82, "value", options=["good", "bad"]), gap])
    _swap_queue(cx, fk)
    pills = "[...document.querySelectorAll('#chkKinds [data-chk-kind]')].map(b => [b.dataset.chkKind, b.querySelector('.chk-kn').textContent, b.getAttribute('aria-pressed'), b.classList.contains('chk-k0')])"
    try:
        pg.goto(cx.base + "check")
        check(wait_js(pg, "CheckShell.state().cur === 'value:e2e:81'"), "全部の種類で開く: %s" % state(pg))
        got = pg.evaluate(pills)
        check(got == [["", "3", "true", False], ["voice", "0", "false", True], ["time", "0", "false", True],   # voice = 話者(誰の声 + コラボの話者。11-02)
                      ["value", "2", "false", False], ["cut", "1", "false", False], ["symbol", "0", "false", True]],   # symbol = 記号のカード(11-01)
              "切り替え: 全部が選ばれ、残りの枚数・0 の種類は薄い(読み・声かどうかは無い): %s" % got)
        pg.click("#chkKinds [data-chk-kind=cut]")
        check(wait_js(pg, "CheckShell.state().cur === 'cut:e2e:83'") and fk.next_q[-1].get("kind") == ["cut"], "カットを押すと kind=cut で読み直す: %s" % fk.next_q[-1:])
        check(pg.evaluate("document.activeElement === document.body") and "kind=cut" in pg.url, "押した後は切り替えから外れる・URL もカット: %s" % pg.url)
        press(pg, "a")
        check(wait_for(lambda: fk.answers and fk.answers[-1]["body"]["card"] == "cut:e2e:83"), "押した後のキーはカードの答え: %s" % fk.answers[-1:])
        check(wait_js(pg, "CheckShell.state().empty"), "カットが尽きたら空の状態: %s" % state(pg))
        pg.goto(cx.base + "check")
        check(wait_js(pg, "CheckShell.state().want.kind === 'cut'") and pg.get_attribute("#chkKinds [data-chk-kind=cut]", "aria-pressed") == "true",
              "次に開いてもカットのまま(覚えている): %s" % state(pg)["want"])
        pg.goto(cx.base + "check?kind=value")
        check(wait_js(pg, "CheckShell.state().cur === 'value:e2e:81'") and fk.next_q[-1].get("kind") == ["value"], "URL の kind が覚えた種類より先: %s" % state(pg))
        pg.click("#chkKinds [data-chk-kind='']")
        check(wait_js(pg, "CheckShell.state().cur === 'value:e2e:81'") and "kind" not in fk.next_q[-1], "全部に戻す: %s" % fk.next_q[-1:])
        pg.goto(cx.base + "check")
        check(wait_js(pg, "CheckShell.state().want.kind === ''"), "全部も覚える")
    finally:
        _restore_queue(cx)


def wait_for(fn, timeout=8):
    return testkit.wait_for(fn, timeout, 0.1)


def fixture_cards():
    vid = {"url": "transcribe/media?id=a0000000000b", "start": 0.5, "end": 1.5, "pad": 0.2}
    cards = [card(i, "value", options=["good", "bad"], reasons=[{"id": "boring", "text": "場面がつまらない"}, {"id": "long", "text": "長すぎる"}],
                  score=82.4 if i == 1 else None) for i in (1, 2, 3)]   # 自動の切り抜き = 送った後の品質の確認(良い / 悪い + 理由の札)
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
    wav = make_wav(os.path.join(tmp, "clip.wav"))
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
                pg.on("pageerror", lambda e: errors.append(str(e) + " @ " + (getattr(e, "stack", "") or "")[:400]))
                pg.on("response", lambda r: bad_status.append("%s %s" % (r.status, r.url)) if r.status >= 400 else None)
                cx = types.SimpleNamespace(pg=pg, check=check, fq=fq, base="http://127.0.0.1:%d/" % port, peaks_hits=peaks_hits, retime_hits=retime_hits, ctx=ctx, wav=wav)
                _scene_open(cx)
                _scene_answer_undo_skip(cx)
                _scene_kinds(cx)
                _scene_summary_and_end(cx)
                _scene_failures(cx)
                _scene_voice(cx)
                _scene_voice_bgm_and_gone(cx)
                _scene_rate_kept(cx)
                _scene_voice_pick(cx)
                _scene_unknown(cx)
                _scene_voice_video_or_clip(cx)
                _scene_voice_others(cx)
                _scene_cut(cx)
                _scene_kind_pick(cx)
                _scene_speaker(cx)
                _scene_symbol(cx)
                _scene_eval_lane(cx)
                check(all("lane" not in q for q in fq.next_q), "普段のレーンは lane=eval を渡さない")
                _scene_real_api(cx)
                unexpected = [s for s in bad_status if not s.startswith("500 ") and not (s.startswith("404 ") and "/api/check/answer" in s)]
                check(not unexpected, "4xx/5xx が出ない(試しに起こした 500・答えの 404 gone を除く): %s" % unexpected[:5])
                errs = [e for e in errors if "500" not in e and "Internal Server Error" not in e and "status of 404" not in e]
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
