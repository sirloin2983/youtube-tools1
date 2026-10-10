#!/usr/bin/env python3
"""校正画面のキー操作の通し確認(Playwright + 疑似モード): 集中モード・表示設定・左手だけのキー操作(Shift+キー)・タグ・自動再生・進み具合の帯・用語挿入・
続きから・履歴・保存の競合・数千行での速さ。

    python3 src/editor/tests/e2e_proofread_keys.py [スクリーンショットの保存先フォルダ]
"""
import json
import os
os.environ.setdefault("YTT_DATA_DIR", "inplace")   # テストは作業データを本物の置き場所(AppData など)に書かない(ytt_core.datadir)
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import types
import urllib.request

from playwright.sync_api import sync_playwright

TESTS = os.path.dirname(os.path.abspath(__file__))
HERE = os.path.dirname(TESTS)   # ツール(editor/)のフォルダ
os.environ.setdefault("YTT_CORE_DIR", os.path.dirname(HERE))   # 一時フォルダに写した serve.py が共通部品 ytt_core(リポジトリ直下)を見つけられるように
SHOTS = next((a for a in sys.argv[1:] if not a.startswith("--")), None)
BIG = 4000
QS = "?nofs=1" if "--nofs" in sys.argv else ""


def call(port, method, path, body=None):
    req = urllib.request.Request("http://127.0.0.1:%d%s" % (port, path), method=method,
                                 data=None if body is None else json.dumps(body).encode(), headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read())


def wait_settings(port, want, timeout=5.0):
    """サーバーの設定が want(鍵 → 値)になるまで待つ -> なったか(画面の設定の保存は 0.6 秒まとめてから)"""
    end = time.time() + timeout
    while True:
        got = call(port, "GET", "/api/settings")
        if all(got.get(k) == v for k, v in want.items()):
            return True
        if time.time() > end:
            return False
        time.sleep(0.1)


def main():
    tmp = tempfile.mkdtemp()
    for n in ("serve.py", "index.html", "app.js", "cut.js", "pack-tab.js", "ui-kit.js", "hololive-roster.json") + tuple(n for n in sorted(os.listdir(HERE)) if (n.startswith("ed_") and n.endswith(".py")) or (n.startswith("app-") and n.endswith(".js"))):   # 段10 で serve.py・app.js から分けた部品(pipeline_io・resolve_export は RS3-E5b で層へ移った = YTT_CORE_DIR の src から読む)
        shutil.copy(os.path.join(HERE, n), tmp)
    wav = os.path.join(tmp, "sample.wav")
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi", "-i", "sine=frequency=440:duration=24", wav], check=True)
    with open(os.path.join(tmp, "settings.json"), "w", encoding="utf-8") as f:
        json.dump({"glossary": "ホロライブ\nトワ", "model": "small", "language": "ja"}, f)
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    env = dict(os.environ, YTT_RUNTIME_DIR=os.path.join(tmp, ".runtime"), TRANSCRIBE_BACKEND="fake", TRANSCRIBE_FAKE_DELAY="0.01")
    proc = subprocess.Popen([sys.executable, os.path.join(tmp, "serve.py"), str(port), "--no-open"], cwd=tmp, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    errors, ok = [], True

    def check(cond, msg):
        nonlocal ok
        print(("OK   " if cond else "FAIL ") + msg)
        ok = ok and bool(cond)

    try:
        for _ in range(100):
            try:
                call(port, "GET", "/api/ping")
                break
            except Exception:
                time.sleep(0.1)

        def make():
            j = call(port, "POST", "/api/transcribe", {"sourcePath": wav, "model": "small", "language": "ja", "glossary": "ホロライブ\nトワ", "autoGloss": False})
            for _ in range(200):
                jobs = call(port, "GET", "/api/jobs")["jobs"]
                job = next(x for x in jobs if x["id"] == j["id"])
                if job["state"] in ("done", "error"):
                    return job["tid"]
                time.sleep(0.1)

        tid = make()
        d = call(port, "GET", "/api/transcript?id=" + tid)
        # 校正の流れ用: 2行目を要確認に、1行目を校正済みに
        d["segments"][1]["flag"] = "認識が不確か"
        d["segments"][0]["proofed"] = True
        SPK = [{"id": "S1", "name": "トワ", "color": "#2f62d6"}]
        call(port, "PUT", "/api/transcript?id=" + tid, {"title": d["title"], "speakers": SPK, "segments": d["segments"]})
        n = len(d["segments"])
        # 数千行の文字起こし(別の文書)
        tid2 = make()
        d2 = call(port, "GET", "/api/transcript?id=" + tid2)
        big = [{"id": "b%d" % i, "start": i * 2.0, "end": i * 2.0 + 1.8, "text": "これは%d行目のテスト文です。トワ様のホロライブの話をしています" % i, "speaker": "",
                "flag": "認識が不確か" if i % 50 == 7 else "", **({"proofed": True} if i % 3 == 0 else {})} for i in range(BIG)]
        call(port, "PUT", "/api/transcript?id=" + tid2, {"title": "大きい文書", "speakers": [], "segments": big})

        with sync_playwright() as pw:
            b = pw.chromium.launch()
            ctx = b.new_context(viewport={"width": 1500, "height": 1000}, permissions=[])
            pg = ctx.new_page()
            pg.add_init_script("document.addEventListener('DOMContentLoaded', () => { const st = document.createElement('style'); st.textContent = '[data-side-pane][hidden]{display:block !important}'; document.head.appendChild(st); })")   # v0.9.9: メニューのタブで隠れるカードも操作できるように(タブ自体は e2e_ui_v098.py で確認)
            pg.on("pageerror", lambda e: errors.append(str(e)))
            pg.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
            pg.goto("http://localhost:%d/%s" % (port, QS))
            pg.wait_for_selector("#txList .txi")
            cx = types.SimpleNamespace(**locals())   # 場面の関数(下の _scene_*)へ渡す値。場面で作って、あとの場面で使う値は場面が cx に戻す
            _scene_opt_checks(cx)
            _scene_keys(cx)
            _scene_keymap(cx)
            _scene_tags_autoplay(cx)
            _scene_view(cx)
            _scene_history_conflict(cx)
            _scene_big_doc(cx)
            b.close()
        errors = [e for e in errors if "409" not in e]   # 競合の試験で、わざと409を起こしている
        check(not errors, "画面のエラーなし " + ("" if not errors else str(errors[:3])))
    finally:
        proc.terminate()
        proc.wait(timeout=10)
        shutil.rmtree(tmp, ignore_errors=True)
    print("ALL PASSED" if ok else "SOME FAILED")
    sys.exit(0 if ok else 1)


def _scene_opt_checks(cx):
    """設定のチェックは、変えたらすぐ保存する(表 SET_CHECKS のうち画面に残ったもの = 書き出しの 2 つ。保管の 2 つは 0.68.0 で消した)。
    0.66.0: 認識の設定の自動の後処理・声の検出・字幕の向きと最大文字数の欄は設定の画面へ(欄の無い鍵は保存した設定 S.settings から要求に付く)"""
    check, pg, port = cx.check, cx.pg, cx.port
    check(pg.locator("#optAutoContext, #optVad, #optAutoFill, #optSubOrient").count() == 0 and pg.locator("#recogDetails a[href$='settings#sec-editor']").count() == 1,
          "認識の設定に自動の後処理・声の検出・字幕の向きの欄は無く、設定の画面へのリンクがある")
    shown = pg.evaluate("SET_CHECKS.filter(([k, id]) => document.querySelector('#' + id)).map(([k, id]) => id)")
    check(set(shown) == {"exSpk", "exTs"}, "画面に残るチェックは書き出しの 2 つ: %s" % shown)
    before = pg.evaluate("Object.fromEntries(SET_CHECKS.filter(([k, id]) => document.querySelector('#' + id)).map(([k, id]) => [id, document.querySelector('#' + id).checked]))")
    # 表のチェックを 1 つずつ変え、その場で設定(S.settings)に入るか = 変えたら保存する待ち受けが漏れていないか
    missed = pg.evaluate("""SET_CHECKS.filter(([k, id]) => document.querySelector('#' + id)).filter(([k, id]) => { const c = document.querySelector('#' + id); c.checked = !c.checked;
      c.dispatchEvent(new Event('change', { bubbles: true })); return S.settings[k] !== c.checked; }).map(([k, id]) => id)""")
    check(not missed, "設定のチェック(%d 個)はどれも、変えたらすぐ設定に入る: 漏れ %s" % (len(before), missed))
    want = pg.evaluate("""b => { SET_CHECKS.filter(([k, id]) => document.querySelector('#' + id)).forEach(([k, id]) => { const c = document.querySelector('#' + id);
      if (c.checked !== b[id]){ c.checked = b[id]; c.dispatchEvent(new Event('change', { bubbles: true })); } });
      return Object.fromEntries(SET_CHECKS.filter(([k, id]) => document.querySelector('#' + id)).map(([k, id]) => [k, document.querySelector('#' + id).checked])); }""", before)
    check(wait_settings(port, want), "元に戻すと、サーバーの設定も元の値になる")
    # 欄の無い鍵(自動の後処理)は、保存した設定が文字起こしの要求に付く(checksOf は欄が無ければ S.settings を読む)
    check(pg.evaluate("checksOf(OPT_CHECKS).autoContext === false && checksOf(OPT_CHECKS).autoDict === true"), "欄の無い鍵は既定の扱い(autoContext オフ・autoDict オン)で要求に付く")
    pg.evaluate("S.settings.autoContext = true; putSettingsNow()")
    check(wait_settings(port, {"autoContext": True}) and pg.evaluate("checksOf(OPT_CHECKS).autoContext === true"), "保存した設定を変えると要求にも付く(autoContext)")
    pg.evaluate("S.settings.autoContext = false; putSettingsNow()")
    check(wait_settings(port, {"autoContext": False}), "戻す")


def _scene_keys(cx):
    """小さい文書を開く・行の移動と再生のキー(↓↑・Shift+↓↑・F・W/S/A/D・Q/E・Space・B・Tab)"""
    check, n, pg = cx.check, cx.n, cx.pg
    # ---- 小さい文書 ----
    items = pg.locator("#txList .txi")
    idx = [i for i in range(items.count()) if "大きい文書" not in items.nth(i).inner_text()][0]
    items.nth(idx).locator(".t").click()
    pg.wait_for_selector("#segs .seg")
    check(pg.locator("#segs .seg").count() == n, "小さい文書を開いた")
    check("未校正 %d行" % (n - 1) in pg.inner_text("#sessStat"), "未校正の残りが出る: " + pg.inner_text("#sessStat"))
    # キー操作(キー単体。入力欄の外で使う。段2: 行の移動は S/W → ↓/↑、未校正への移動は D/A → Shift+↓/↑ に変えた)
    active_body = "document.activeElement === document.body"
    navi = lambda: pg.evaluate("[...document.querySelectorAll('#segs .seg')].findIndex(r => r.classList.contains('nav'))")
    pg.locator("#segs textarea").nth(0).focus()
    pg.keyboard.press("Escape")
    check(pg.evaluate(active_body) and navi() == 0, "Esc で入力欄から抜けても、選んでいる行(枠)は残る")
    pg.keyboard.press("ArrowDown")
    check(navi() == 1 and pg.evaluate(active_body), "↓ で次の行(入力欄には入らない)")
    pg.keyboard.press("ArrowUp")
    check(navi() == 0, "↑ で前の行")
    pg.keyboard.press("Shift+ArrowDown")
    check(navi() == 1, "Shift+↓ で次の未校正へ(1行目は校正済みなのでとばす)")
    pg.keyboard.press("f")
    check(navi() == 4, "F で次の要確認へ(2行目 → 5行目)")
    pg.keyboard.press("f")
    check(navi() == 4 and "要確認" in pg.inner_text("#toast"), "F: これより後に要確認が無ければ移動せず、案内が出る")
    pg.keyboard.press("Shift+ArrowUp")
    check(navi() == 3, "Shift+↑ で前の未校正へ")
    # 左手の操作(段2 でやめたが 2026-09-27 に戻した。↓/↑ と両方使える)
    pg.keyboard.press("w"); check(navi() == 2, "W で前の行")
    pg.keyboard.press("s"); check(navi() == 3, "S で次の行")
    pg.keyboard.press("a"); na = navi(); check(0 < na < 3, "A で前の未校正へ: %d" % na)
    pg.keyboard.press("d")
    nd = navi(); check(nd > na, "D で次の未校正へ: %d" % nd)
    while navi() != 3:
        pg.keyboard.press("s" if navi() < 3 else "w")
    pg.evaluate("document.querySelector('#player').pause(); document.querySelector('#player').currentTime = 5")
    pg.keyboard.press("e"); check(abs(pg.evaluate("document.querySelector('#player').currentTime") - 8) < 0.3, "E で3秒進む")
    pg.keyboard.press("q"); check(abs(pg.evaluate("document.querySelector('#player').currentTime") - 5) < 0.3, "Q で3秒戻る")
    # Space は1回押すと1回だけ再生/停止が切り替わる(以前は共通の再生キーと古い処理の両方が動いて「再生 → すぐ停止」になっていた)
    pg.keyboard.press("Space")
    pg.wait_for_timeout(300)
    check(not pg.evaluate("document.querySelector('#player').paused"), "Space 1回で再生になる(すぐ止まらない)")
    pg.keyboard.press("Space")
    check(pg.evaluate("document.querySelector('#player').paused"), "もう一度 Space で止まる")
    pg.keyboard.down("Space"); pg.keyboard.down("Space"); pg.keyboard.down("Space"); pg.keyboard.up("Space")   # 押しっぱなし(2回目以降は repeat)
    pg.wait_for_timeout(200)
    check(not pg.evaluate("document.querySelector('#player').paused"), "Space の押しっぱなしで再生・停止を繰り返さない(1回分だけ)")
    pg.keyboard.press("k")
    pg.keyboard.press("b"); check(pg.is_checked("#autoNext"), "B で「移動したら自動で再生」をオン")
    pg.keyboard.press("b"); check(not pg.is_checked("#autoNext"), "もう一度 B でオフ")
    pg.keyboard.press("Tab")
    check(pg.evaluate("document.activeElement === document.querySelectorAll('#segs textarea')[3]"), "Tab で選んだ行の入力欄へ")
    pg.keyboard.press("Tab")
    check(pg.evaluate(active_body) and navi() == 3, "入力中の Tab で入力欄から抜ける")
    cx.navi = navi


def _scene_keymap(cx):
    """キー配置(? の一覧): 変える・断る・外す・保存・標準に戻す・派生キー・ツールチップとキーの説明"""
    check, navi, pg, port = cx.check, cx.navi, cx.pg, cx.port
    # キー配置(? の一覧。2026-09-27。段6 から部品 UIKit.keymap。2026-10-04 から変える場所は ? の一覧だけ・⚙ にはそこを開くボタンだけ): 割り当てを変える・使えないキーは断る・重なりは外す・開き直しても残る・標準に戻す
    KB = "#keysList .ui-km-key[data-km=%s]"
    def km_text(action_id):
        return pg.inner_text(KB % action_id).replace("\n", "").replace(" ", "")
    def km_set(action_id, key):
        pg.click("#btnKeys")
        pg.wait_for_selector(KB % action_id, state="visible")
        pg.click(KB % action_id)
        check(pg.inner_text(KB % action_id) == "キーを押す…", "キー配置: ボタンを押すと「キーを押す…」になる(%s)" % action_id)
        pg.keyboard.press(key)
        note = pg.inner_text("#keysList .ui-km-note")
        if pg.evaluate("UIKit.keymap.capturing()"):   # 断られた = 待つのを続けている → Esc で取り消し(Esc で引き出しは閉じない)
            pg.keyboard.press("Escape")
            check(pg.evaluate("document.querySelector('#keys').open"), "キーを待っている間の Esc は取り消しだけ(一覧は閉じない)")
        txt = km_text(action_id)
        pg.click("#keys .ui-dlg-head button")   # 一覧を閉じる(Esc を2回続けると2回目は Chrome が閉じないので、閉じるボタンで)
        pg.wait_for_function("!document.querySelector('#keys').open", timeout=3000)
        km_set.note = note
        return txt
    check(km_set("rowNext", "y") == "Y", "キー配置: 「次の行」を Y に変えられる")
    pg.keyboard.press("y"); check(navi() == 4, "Y で次の行へ(変えた割り当てが効く)")
    pg.keyboard.press("s"); check(navi() == 4, "もとの S はもう効かない")
    pg.keyboard.press("ArrowUp"); check(navi() == 3, "↑ ↓ は固定なのでそのまま使える")
    check(km_set("playPause", "s") == "Space", "再生のキーに S(2 カット の分割)は割り当てられない(元のまま)")
    check("分割" in km_set.note, "断った理由が一覧の中に出る: " + km_set.note)
    check(km_set("replay", "h") != "H" and "2 カット" in km_set.note, "1 文字起こし のキーに H(2 カット の「始まり〜終わりを削る」)は割り当てられない(UI の見直し 2 周目): " + km_set.note)
    check(km_set("replay", "y") == "Y", "すでに使っているキーを選ぶと、こちらに割り当てられる")
    check("外しました" in km_set.note, "前の操作から外したことが一覧の中に出る: " + km_set.note)
    import time as _t; _t.sleep(1.0)
    saved = call(port, "GET", "/api/settings").get("keymap") or {}
    check(saved.get("replay") == "y" and saved.get("rowNext") == "", "キー配置はサーバーの設定に保存される: %s" % {k: saved.get(k) for k in ("replay", "rowNext")})
    check(km_set("playPause", "p") == "P", "共通の再生キー(再生・停止)も変えられる")
    pg.evaluate("document.querySelector('#player').pause()")
    pg.keyboard.press("p"); pg.wait_for_timeout(300)
    check(not pg.evaluate("document.querySelector('#player').paused"), "P で再生になる")
    pg.keyboard.press("k")
    pg.click("#btnKeys"); pg.wait_for_selector("#keysList [data-km-reset]", state="visible")
    pg.click("#keysList [data-km-reset]")
    check(km_text("rowNext") == "S" and km_text("playPause") == "Space", "「すべて標準に戻す」で元の配置に戻る")
    pg.keyboard.press("Escape")
    _t.sleep(1.0)
    pg.keyboard.press("s"); check(navi() == 4, "標準に戻したあとは S で次の行")
    pg.keyboard.press("w")
    # 段3 3-2(監査 03): 派生キー(1秒戻る/進むのキー + Shift = 5秒)と、2 カット の Shift+, / Shift+.(< >)は、ほかの操作に登録できない
    check(km_set("rowNext", "Shift+ArrowLeft") == "S" and "5 秒" in km_set.note, "3-2: 「次の行」に Shift+← は断られて元のまま: " + km_set.note)
    check(km_set("rowNext", "Shift+KeyY") == "Shift+Y", "3-2: 「次の行」を Shift+Y にできる")
    check(km_set("seekBack", "KeyY") == "Y" and km_text("rowNext") == "未設定" and "外しました" in km_set.note,
          "3-2: 「1秒戻る」を Y にすると、Shift+Y を持つ「次の行」から外れる(未設定): " + km_set.note)
    pg.evaluate("document.querySelector('#player').pause(); document.querySelector('#player').currentTime = 8")
    pg.wait_for_function("document.querySelector('#player').currentTime >= 7.9")
    pg.keyboard.press("Shift+KeyY")
    pg.wait_for_function("document.querySelector('#player').currentTime <= 3.5", timeout=4000)
    check(navi() == 3, "3-2: Shift+Y で5秒戻る(「1秒戻る」+ Shift。行は動かない)")
    check(km_set("playPause", "Shift+Comma") == "Space" and "10コマ" in km_set.note, "3-2: 再生のキーに < (Shift+,)は断られる: " + km_set.note)
    # 段3 3-3(監査 16): ツールチップ・知らせ・キー帯・説明はキー配置から。未設定のキーはどこにも出ない
    row_title = lambda sel: pg.evaluate("document.querySelectorAll('#segs %s')[3].title" % sel)   # noqa: E731
    check("(X)" in row_title("button[data-act=tag][data-t=unclear]") and "(N)" in row_title("button[data-act=adda]") and "Z でも" in row_title("button[data-act=del]"),
          "3-3: 標準の配置では行の title に (X)・(N)・Z でも")
    check(km_set("tagUnclear", "KeyY") == "Y", "3-3: 「聞き取れない」を Y に")
    check("(Y)" in row_title("button[data-act=tag][data-t=unclear]"), "3-3: 行の「聞き取れない」の title が (Y): " + row_title("button[data-act=tag][data-t=unclear]"))
    check(km_set("tagUnclear", "Delete") == "未設定" and "(" not in row_title("button[data-act=tag][data-t=unclear]"), "3-3: 未設定にすると「(キー)」ごと出さない: " + row_title("button[data-act=tag][data-t=unclear]"))
    check(km_set("del", "Delete") == "未設定" and "でも消せます" not in row_title("button[data-act=del]") and km_set("insert", "Delete") == "未設定" and "(" not in row_title("button[data-act=adda]"),
          "3-3: 削除・行の追加を未設定にすると、行の title にキーが出ない: %s / %s" % (row_title("button[data-act=del]"), row_title("button[data-act=adda]")))
    check(km_set("menu", "KeyM") == "M" and pg.get_attribute("#btnMenu", "title").endswith("(M)") and pg.get_attribute("[data-strip=menu]", "title").endswith("(M)"),
          "3-3: メニューのキーを M にすると、メニューのボタンの title が (M): " + pg.get_attribute("#btnMenu", "title"))
    check(km_set("frameFwd", "KeyU") == "U" and km_text("frameFwd") == "U" and "?" in pg.evaluate("document.querySelector('#cutKeysText').textContent"),
          "3-3: 「1コマ進む」を U にすると、一覧も U。2 カット の下の行は「すべてのキー: ?」だけ(長い説明はやめた。UI の見直し S17): " + pg.evaluate("document.querySelector('#cutKeysText').textContent"))
    check(km_set("playPause", "KeyP") == "P" and pg.get_attribute("#cutPlay", "title") == "再生・停止(P)", "3-3: カットの再生ボタンの title も再生のキーから: " + pg.get_attribute("#cutPlay", "title"))
    check(km_set("markIn", "Delete") == "未設定" and pg.evaluate("document.querySelector('#cutIOLabel').textContent") == "印の間を削る", "3-3: 始まりの印を外すと「I〜O を削る」は「印の間を削る」: " + pg.evaluate("document.querySelector('#cutIOLabel').textContent"))
    check(km_set("proof", "Delete") == "未設定" and "Shift+Space" not in pg.evaluate("document.querySelector('#accCard').textContent") and "Shift+Space" not in (pg.get_attribute("#autoNextLbl", "title") or ""),
          "3-3: 校正済みのキーを外すと、精度の説明・自動で再生の説明に Shift+Space が出ない")
    pg.click("#btnKeys"); pg.wait_for_selector("#keysList [data-km-reset]", state="visible")
    pg.click("#keysList [data-km-reset]")
    check(km_text("rowNext") == "S" and km_text("seekBack") == "←", "3-2: すべて標準に戻す")
    pg.keyboard.press("Escape")
    pg.wait_for_function("!document.querySelector('.ui-drawer:not([hidden])')", timeout=3000)
    _t.sleep(1.0)


def _scene_tags_autoplay(cx):
    """タグと話者・入力中の Shift+文字・Shift+Space で校正済み・自動再生(Alt+Enter)"""
    check, d, navi, pg = cx.check, cx.d, cx.navi, cx.pg
    # タグ(聞き取れない・声が重なる・BGM)と話者
    pg.keyboard.press("x")
    check(pg.locator("#segs .seg").nth(3).evaluate("e => e.classList.contains('tagged')"), "X で「聞き取れない」")
    pg.keyboard.press("x")
    check(not pg.locator("#segs .seg").nth(3).evaluate("e => e.classList.contains('tagged')"), "もう一度で外れる")
    pg.keyboard.press("c")
    pg.keyboard.press("1")
    check(pg.locator("#segs .spk").nth(3).input_value() == "S1", "1 で話者を割り当て")
    # 入力欄の中では、Shift+文字は普通に入力できる(操作キーは働かない。F は今も1文字の操作キー)
    pg.keyboard.press("t")
    check(pg.evaluate("document.activeElement === document.querySelectorAll('#segs textarea')[3]"), "T で行の文字を直す(入力欄へ)")
    before = pg.locator("#segs textarea").nth(3).input_value()
    pg.keyboard.press("Shift+F")
    check(pg.locator("#segs textarea").nth(3).input_value() == before + "F" and navi() == 3, "入力中の Shift+F は、大文字の F が入るだけ")
    pg.keyboard.press("Backspace")
    pg.keyboard.press("Escape")
    # Shift+Space だけは例外(Space 単体は再生・停止のため): 校正済みにして次へ(自動再生あり)。
    # 「移動したら自動で再生」は ⚙ 設定の引き出しの中(B キーでも切り替わる)
    pg.keyboard.press("ArrowUp")
    pg.click("[data-ui-settings]")
    pg.wait_for_selector("#autoNext", state="visible")
    pg.check("#autoNext")
    pg.keyboard.press("Escape")
    check(pg.is_checked("#autoNext"), "設定の引き出しで「移動したら自動で再生」をオンにできる")
    pg.keyboard.press("Shift+Space")
    check(navi() == 3 and pg.locator("#segs .seg").nth(2).evaluate("e => e.classList.contains('proofed')"), "Shift+Space で校正済みにして次の行へ")
    pg.wait_for_function("document.querySelector('#player').currentTime >= %s - 0.05" % d["segments"][3]["start"], timeout=5000)
    check(True, "次の行が自動で再生される")
    pg.keyboard.press("Shift+Space")
    pg.click("[data-ui-settings]")
    pg.uncheck("#autoNext")
    pg.keyboard.press("Escape")
    check(not pg.is_checked("#autoNext"), "設定の引き出しでオフに戻せる")
    # 自動再生
    pg.click("[data-ui-settings]"); pg.check("#autoNext"); pg.keyboard.press("Escape")
    pg.locator("#segs textarea").nth(1).focus()
    pg.keyboard.press("Alt+Enter")
    pg.wait_for_function("document.querySelector('#player').currentTime >= %s - 0.05" % d["segments"][2]["start"], timeout=5000)
    check(pg.evaluate("document.activeElement === document.querySelectorAll('#segs textarea')[2]"), "Alt+Enter で次の行へ移動し、自動再生の位置に飛ぶ")
    check(pg.locator("#segs .seg.proofed").count() == 4, "Alt+Enter でも校正済みになる(入力中)")
    check("今回 +3行" in pg.inner_text("#sessStat"), "今回の校正数が増える: " + pg.inner_text("#sessStat"))
    pg.click("[data-ui-settings]"); pg.uncheck("#autoNext"); pg.keyboard.press("Escape")


def _scene_view(cx):
    """再生速度と → キー・用語の挿入・進み具合の帯・表示設定・続きから・キーの一覧"""
    check, n, pg, port = cx.check, cx.n, cx.pg, cx.port
    # 再生速度・共通の再生キー(← → 1秒)
    pg.keyboard.press("Escape")
    pg.select_option("#rate", "1.5")
    check(pg.evaluate("document.querySelector('#player').playbackRate") == 1.5, "再生速度が変わる")
    pg.select_option("#rate", "1")
    pg.evaluate("document.querySelector('#player').currentTime = 10")
    pg.wait_for_function("document.querySelector('#player').currentTime >= 9.9")   # シーク待ち(すぐにキーを送ると、シーク前の位置に+1秒してしまうことがある)
    pg.locator("#player").focus()
    pg.wait_for_timeout(100)   # フォーカスが落ち着いてから押す(PC の負荷でのタイミング依存を減らす)
    pg.keyboard.press("ArrowRight")
    pg.wait_for_function("document.querySelector('#player').currentTime >= 10.7", timeout=4000)
    check(pg.evaluate("document.querySelector('#player').currentTime") <= 11.3, "→ で1秒進む(共通の再生キー)")
    # 用語の挿入
    check(pg.locator("#terms .chip").count() == 2, "用語のボタンが出る(用語集の2語)")
    ta = pg.locator("#segs textarea").nth(3)
    ta.fill("これは")
    ta.focus()
    pg.keyboard.press("End")
    pg.click("#terms .chip[data-t=トワ]")
    check(ta.input_value() == "これはトワ", "用語をカーソル位置に挿入: " + ta.input_value())
    check(pg.evaluate("document.activeElement === document.querySelectorAll('#segs textarea')[3]"), "挿入後も入力欄にフォーカスが残る")
    # 進み具合の帯
    box = pg.locator("#strip").bounding_box()
    pg.mouse.click(box["x"] + box["width"] * 0.9, box["y"] + 5)
    check(pg.evaluate("[...document.querySelectorAll('#segs .seg')].findIndex(r => r.classList.contains('nav'))") == n - 1, "帯をクリックすると、その位置の行へ移動")
    has_ink = pg.evaluate("""() => { const c = document.querySelector('#strip'), x = c.getContext('2d'); const d = x.getImageData(0, 0, c.width, c.height).data; let n = 0; for (let i = 3; i < d.length; i += 4) if (d[i] > 0) n++; return n; }""")
    check(has_ink > 100, "帯に色が描かれている")
    # 表示設定(v6: ヘッダーの ⚙ から開く設定の引き出し。UIKit.settings)
    pg.click("[data-ui-settings]")
    pg.wait_for_selector("#vFs", state="visible")
    pg.select_option("#vFs", "20")
    check(pg.evaluate("getComputedStyle(document.querySelector('#segs textarea')).fontSize") == "20px", "文字の大きさ: 特大")
    theme_sel = "#uiSettingsDrawer .ui-settings-row:has-text('テーマ') select"
    pg.select_option(theme_sel, "dark")
    check(pg.evaluate("document.documentElement.dataset.theme") == "dark", "画面の色(全体の節): 暗い")
    pg.check("#vDense")
    check(pg.evaluate("document.documentElement.classList.contains('dense')"), "行の間隔を詰める")
    pg.select_option("#vVid", "a")
    check(pg.evaluate("document.querySelector('#player').getBoundingClientRect().height") < 70, "音声だけ聞く: 映像が小さくなる")
    pg.mouse.click(5, 500)
    check(pg.evaluate("document.querySelector('#uiSettingsDrawer').hidden") is True, "外(幕)をクリックすると設定の引き出しが閉じる")
    if pg.is_hidden("#menuPanel"):   # 1600px 未満の画面では、文書を開いた時点でメニューは自動で閉じている(2026-09-27)ので、先に開く
        pg.click("#btnMenu")
    pg.click("#btnMenu")
    check(pg.is_hidden("#menuPanel") and pg.is_visible("#player"), "メニューを閉じる: 左のメニューだけ隠れる(映像は残る)")
    pg.keyboard.press("Escape")
    pg.keyboard.press("g")
    check(pg.is_visible("#menuPanel"), "G でメニューを開く")
    pg.wait_for_function("document.querySelector('#saveState').textContent.includes('保存しました')", timeout=8000)   # 再読み込みの前に、保存を待つ
    pg.goto("http://localhost:%d/%s" % (port, QS))
    pg.wait_for_selector("#txList .txi")
    check(pg.is_visible("#menuPanel") and pg.evaluate("document.documentElement.dataset.theme") == "dark" and pg.evaluate("getComputedStyle(document.documentElement).getPropertyValue('--fs').trim()") == "20px", "表示の設定(文字・色・メニューの開閉)が残る")
    # 続きから
    items = pg.locator("#txList .txi")
    idx = [i for i in range(items.count()) if "大きい文書" not in items.nth(i).inner_text()][0]
    items.nth(idx).locator(".t").click()
    pg.wait_for_selector("#segs .seg")
    pg.wait_for_function("document.querySelector('#toast').textContent.includes('前回の続き')", timeout=5000)
    check(True, "開き直すと「前回の続き」へ移動する")
    pg.click("#btnMenu")
    if SHOTS:
        os.makedirs(SHOTS, exist_ok=True)
        pg.screenshot(path=os.path.join(SHOTS, "v071_focus_dark.png"))
    pg.click("#btnMenu")
    # キー一覧
    pg.click("#btnKeys")
    check(pg.is_visible("#keys") and "Shift+Space" in pg.inner_text("#keys") or "校正済みにして次へ" in pg.inner_text("#keys"), "操作キーの一覧が開く")
    pg.keyboard.press("Escape")
    check(pg.is_hidden("#keys"), "Esc で閉じる")


def _scene_history_conflict(cx):
    """タグと話者の保存・以前の版・保存の競合・校正の手間・履歴から戻す"""
    SPK, check, pg, port, tid, tmp = cx.SPK, cx.check, cx.pg, cx.port, cx.tid, cx.tmp
    # ---- 履歴と競合 ----
    pg.locator("#segs textarea").nth(4).fill("履歴用の編集")
    pg.wait_for_function("document.querySelector('#saveState').textContent.includes('保存しました')", timeout=8000)
    sv = call(port, "GET", "/api/transcript?id=" + tid)["segments"][3]
    check(sv.get("tags") == ["overlap"] and sv.get("speaker") == "S1", "タグと話者がサーバーに保存された: %s" % ({k: sv.get(k) for k in ("tags", "speaker")},))
    # 保管(dataset/)は 0.68.0 で消した(カードも自動の保管も無い)
    check(pg.locator("#arcCard, #arcStat, #arcNow").count() == 0, "保管のカード・状況は無い")
    if pg.is_visible("#menuScrim"):
        pg.click("#menuScrim")   # B-7: 1600px 未満ではメニューを重ねて開くので、閉じてから本文を操作する
    pg.click("#btnSpk")   # v0.15.0: 「道具 ▾」→「以前の版に戻す」(自動バックアップ。旧「履歴」)
    pg.click("[data-jump=hiDetails]")
    pg.wait_for_function("document.querySelectorAll('#hiList [data-act=hirest]').length >= 1", timeout=8000)
    check(True, "以前の版(自動バックアップ)の一覧が出る(件数: %d)" % pg.locator("#hiList [data-act=hirest]").count())
    # 別の場所(API)が先に更新 → 画面側の保存は競合になる
    cur = call(port, "GET", "/api/transcript?id=" + tid)
    cur["segments"][5]["text"] = "別のタブで直した"
    call(port, "PUT", "/api/transcript?id=" + tid, {"title": cur["title"], "speakers": SPK, "segments": cur["segments"]})
    pg.locator("#segs textarea").nth(0).fill("画面で直した")
    pg.wait_for_function("!document.querySelector('#conflictBar').hidden", timeout=8000)
    check("競合" in pg.inner_text("#saveState"), "競合の案内が出て、自動保存が止まる")
    check(call(port, "GET", "/api/transcript?id=" + tid)["segments"][5]["text"] == "別のタブで直した", "サーバー側の内容は上書きされていない")
    pg.click("#cfReload")
    pg.wait_for_function("document.querySelector('#conflictBar').hidden")
    check(pg.locator("#segs textarea").nth(5).input_value() == "別のタブで直した", "読み込み直すと、先に保存された内容になる")
    pg.locator("#segs textarea").nth(0).fill("読み込み直してから直した")
    pg.wait_for_function("document.querySelector('#saveState').textContent.includes('保存しました')", timeout=8000)
    check(call(port, "GET", "/api/transcript?id=" + tid)["segments"][0]["text"] == "読み込み直してから直した", "読み込み直したあとは通常どおり保存できる")
    # ---- 記録の土台(マスタープラン Q2): 校正した時刻・校正の手間 ----
    cur = call(port, "GET", "/api/transcript?id=" + tid)
    pf = [g for g in cur["segments"] if g.get("proofed")]
    check(len(pf) >= 4 and all(isinstance(g.get("proofedAt"), int) and g["proofedAt"] > 1.7e12 for g in pf),
          "画面で校正済みにした行に、校正した時刻 proofedAt(ミリ秒)が付く: %s" % [g.get("proofedAt") for g in pf][:6])
    check((cur.get("effort") or {}).get("proofedRows", 0) >= 3, "校正済みにした行の数を、保存のときにサーバーが数える: %s" % (cur.get("effort"),))
    ua = cur["updatedAt"]
    pg.evaluate("effortTick(60000); effortFlush()")   # 30 秒刻みの数えを2回分進めて、送る(離れたとき・文書を切り替えるときと同じ関数)
    for _ in range(50):
        ef = call(port, "GET", "/api/transcript?id=" + tid).get("effort") or {}
        if ef.get("activeSec", 0) >= 60:
            break
        time.sleep(0.1)
    cur = call(port, "GET", "/api/transcript?id=" + tid)
    check(cur["effort"]["activeSec"] >= 60 and cur["effort"]["sessions"] >= 1 and cur["updatedAt"] == ua,
          "校正の手間(操作していた秒・回数)が文書の effort に足され、updatedAt は変わらない: %s" % (cur["effort"],))
    pg.locator("#segs textarea").nth(0).fill("手間を送ったあとに直した")
    pg.wait_for_function("document.querySelector('#saveState').textContent.includes('保存しました')", timeout=8000)
    check(pg.is_hidden("#conflictBar") and call(port, "GET", "/api/transcript?id=" + tid)["segments"][0]["text"] == "手間を送ったあとに直した",
          "手間を送っても、開いている画面の次の保存は競合(409)にならない")
    # 履歴から戻す
    hs = call(port, "GET", "/api/history?id=" + tid)["items"]
    pg.click("#hiRefresh")
    pg.wait_for_function("document.querySelectorAll('#hiList [data-act=hirest]').length == %d" % len(hs))
    last = pg.locator("#hiList [data-act=hirest]").last
    last.click()
    last.click()
    pg.wait_for_function("document.querySelector('#toast').textContent.includes('戻しました')", timeout=8000)
    check(len(call(port, "GET", "/api/history?id=" + tid)["items"]) == len(hs) + 1, "戻すと、戻す前の状態も履歴に残る")


def _scene_big_doc(cx):
    """数千行: 開く速さ・入力の反応・Alt+Enter・絞り込み・文字サイズ・Shift+↓・Z と Ctrl+Z"""
    check, pg = cx.check, cx.pg
    # ---- 数千行 ----
    if "menu-closed" in (pg.get_attribute(".app", "class") or ""):
        pg.click("#btnMenu")   # B-7: 重ねて開くメニューは、上で閉じたので開き直す
    items = pg.locator("#txList .txi")
    idx = [i for i in range(items.count()) if "大きい文書" in items.nth(i).inner_text()][0]
    t0 = time.time()
    items.nth(idx).locator(".t").click()
    pg.wait_for_function("document.querySelectorAll('#segs .seg').length === %d" % BIG, timeout=60000)
    t_open = time.time() - t0
    check(t_open < 4.0, "%d行を開くまで %.2f 秒" % (BIG, t_open))
    # 入力の引っかかり(1文字入力 → 反映までの時間)
    pg.locator("#segs textarea").nth(2000).scroll_into_view_if_needed()
    ms = pg.evaluate("""async () => {
              const ta = document.querySelectorAll('#segs textarea')[2000]; ta.focus(); const out = [];
              for (let i = 0; i < 20; i++){ const t = performance.now(); ta.value += 'あ'; ta.dispatchEvent(new Event('input', { bubbles: true })); await new Promise(r => requestAnimationFrame(() => r())); out.push(performance.now() - t); }
              out.sort((a, b) => a - b); return out[Math.floor(out.length * 0.9)]; }""")
    check(ms < 60, "%d行での入力の反応(90%%点) %.1f ms" % (BIG, ms))
    t0 = time.time()
    pg.keyboard.press("Escape")
    pg.locator("#segs textarea").nth(2000).focus()
    pg.keyboard.press("Alt+Enter")
    pg.wait_for_function("document.activeElement === document.querySelectorAll('#segs textarea')[2001]")
    t_proof = time.time() - t0
    check(t_proof < 0.5, "%d行での Alt+Enter(入力中)→ 次の行 %.3f 秒" % (BIG, t_proof))
    t0 = time.time()
    pg.select_option("#flagKind", "unproofed")
    t_f = time.time() - t0
    check(t_f < 2.0, "絞り込み(未校正)にかかる時間 %.2f 秒" % t_f)
    pg.select_option("#flagKind", "")
    t0 = time.time()
    pg.select_option("#vFs", "17") if pg.is_visible("#vFs") else pg.evaluate("document.querySelector('#vFs').value='17'; document.querySelector('#vFs').dispatchEvent(new Event('change'))")
    pg.wait_for_timeout(600)
    check(time.time() - t0 < 3.0, "文字サイズ変更の再計算 %.2f 秒" % (time.time() - t0))
    pg.keyboard.press("Escape")
    pg.keyboard.press("Shift+ArrowDown")
    check(pg.evaluate("(() => { const i = [...document.querySelectorAll('#segs .seg')].findIndex(r => r.classList.contains('nav')); return i > 2001; })()"), "大きい文書でも Shift+↓ で次の未校正へ")
    pg.keyboard.press("z")
    check(pg.locator("#segs .seg").count() == BIG, "Z を1回押しただけでは消えない(v0.9.8: 2回押し)")
    pg.keyboard.press("z")
    check(pg.locator("#segs .seg").count() == BIG - 1, "Z をもう一度で行を削除")
    pg.keyboard.press("Control+z")
    check(pg.locator("#segs .seg").count() == BIG, "Ctrl+Z で削除を元に戻せる")
    if SHOTS:
        pg.screenshot(path=os.path.join(SHOTS, "v071_big.png"))


if __name__ == "__main__":
    main()
