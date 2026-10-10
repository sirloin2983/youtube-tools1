#!/usr/bin/env python3
"""校正画面の通し確認(Playwright + 疑似モード)。校正済みボタン・絞り込み・精度カード(設定の比較 A/B・修正データの書き出しは 0.68.0 で消した)。

    python3 src/editor/tests/e2e_proofread_accuracy.py [スクリーンショットの保存先フォルダ]
"""
import json
import os
import re
os.environ.setdefault("YTT_DATA_DIR", "inplace")   # テストは作業データを本物の置き場所(AppData など)に書かない(ytt_core.datadir)
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request

from playwright.sync_api import sync_playwright

TESTS = os.path.dirname(os.path.abspath(__file__))
HERE = os.path.dirname(TESTS)   # ツール(editor/)のフォルダ
os.environ.setdefault("YTT_CORE_DIR", os.path.dirname(HERE))   # 一時フォルダに写した serve.py が共通部品 ytt_core(リポジトリ直下)を見つけられるように


def app_version():
    """画面の版(app.js の APP_VERSION)。版を上げるたびにテストを書き換えなくて済むように、固定の文字列ではなくここから読む"""
    with open(os.path.join(HERE, "app.js"), encoding="utf-8") as f:
        m = re.search(r"const APP_VERSION = '([^']+)'", f.read())
    assert m, "app.js に APP_VERSION が見つからない"
    return "v" + m.group(1)


SHOTS = sys.argv[1] if len(sys.argv) > 1 else None


def call(port, method, path, body=None):
    req = urllib.request.Request("http://127.0.0.1:%d%s" % (port, path), method=method,
                                 data=None if body is None else json.dumps(body).encode(), headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())


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
        j = call(port, "POST", "/api/transcribe", {"sourcePath": wav, "model": "small", "language": "ja", "glossary": "ホロライブ\nトワ", "autoGloss": False})
        for _ in range(200):
            jobs = call(port, "GET", "/api/jobs")["jobs"]
            if jobs and jobs[0]["state"] in ("done", "error"):
                break
            time.sleep(0.1)
        tid = jobs[0]["tid"]
        with sync_playwright() as pw:
            b = pw.chromium.launch()
            pg = b.new_page(viewport={"width": 1920, "height": 1000})
            pg.add_init_script("document.addEventListener('DOMContentLoaded', () => { const st = document.createElement('style'); st.textContent = '[data-side-pane][hidden]{display:block !important}'; document.head.appendChild(st); })")   # v0.9.9: メニューのタブで隠れるカードも操作できるように(タブ自体は e2e_ui_v098.py で確認)
            pg.on("pageerror", lambda e: errors.append(str(e)))
            pg.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
            pg.goto("http://localhost:%d/" % port)
            pg.wait_for_selector("#txList .txi")
            check(pg.inner_text("#ver") == app_version(), "版が app.js の APP_VERSION(%s)と同じ: %s" % (app_version(), pg.inner_text("#ver")))
            check(pg.is_hidden("#errBar"), "版の不一致の赤い帯が出ていない")
            check("校正済みの行がまだありません" in pg.inner_text("#accOut"), "精度カード: 校正済みなしの案内")
            pg.click("#txList .txi .t")
            pg.wait_for_selector("#segs .seg")
            n = pg.locator("#segs .seg").count()
            # 校正済みの数は題名の行の札(#pillProof)の 1 か所(映像の下の「校正済み n/m行」は二重だったのでやめた。UI の見直し S6)
            pf = lambda: pg.evaluate("new Promise(r => requestAnimationFrame(() => requestAnimationFrame(() => r(document.querySelector('#pillProof').textContent))))")   # noqa: E731
            check(n >= 4 and pf() == "校正 0 / %d行" % n, "校正 0 / %d行の表示" % n)
            # 1行目を直して、Alt+Enter で校正済みにして次の行へ進む
            ta = pg.locator("#segs .seg textarea").nth(0)
            ta.fill("トワ様のテスト")
            ta.press("Alt+Enter")
            check(pg.locator("#segs .seg.proofed").count() == 1, "Alt+Enter で1行目が校正済み")
            check(pg.evaluate("document.activeElement === document.querySelectorAll('#segs textarea')[1]"), "次の行の入力欄へ移動")
            pg.locator("#segs .seg textarea").nth(1).press("Alt+Enter")
            # ボタンでも切り替え(3行目)
            pg.locator("#segs .seg [data-act=proof]").nth(2).click()
            check(pf() == "校正 3 / %d行" % n, "3行を校正済み(ボタンと Alt+Enter)")
            pg.locator("#segs .seg [data-act=proof]").nth(2).click()
            check(pf() == "校正 2 / %d行" % n, "もう一度押すと解除")
            pg.locator("#segs .seg [data-act=proof]").nth(2).click()
            if SHOTS:
                os.makedirs(SHOTS, exist_ok=True)
                pg.locator("#editor").screenshot(path=os.path.join(SHOTS, "ui_rows.png"))
            # 絞り込み
            pg.select_option("#flagKind", "proofed")
            check(pg.locator("#segs .seg:not([hidden])").count() == 3, "校正済みの行だけ表示: 3行")
            pg.select_option("#flagKind", "unproofed")
            check(pg.locator("#segs .seg:not([hidden])").count() == n - 3, "未校正の行だけ表示")
            pg.select_option("#flagKind", "")
            # 保存(自動保存 700ms)して、サーバー側にも残っている
            pg.wait_for_function("document.querySelector('#saveState').textContent.includes('保存しました')", timeout=8000)
            d = call(port, "GET", "/api/transcript?id=" + tid)
            check([bool(g.get("proofed")) for g in d["segments"][:4]] == [True, True, True, False], "サーバーに proofed が保存された")
            # 精度カード(自動更新は4秒後。ボタンで即更新)
            pg.click("#accRefresh")
            pg.wait_for_function("document.querySelector('#accOut').textContent.includes('内訳')", timeout=8000)
            txt = pg.inner_text("#accOut")
            check("CER" in txt and "置換" in txt, "精度カードに CER と内訳が出る")
            check("small / 用語集あり" in txt, "設定別の表が出る")
            # 選択行を校正済みに / 全行(2度押し)
            pg.locator("#segs .seg .sel").nth(3).evaluate("e => e.click()")   # 固定表示の帯の下に隠れることがあるので、直接押す
            pg.click("#moreTools summary")
            pg.click("#btnProofSel")
            check(pf() == "校正 4 / %d行" % n, "選択行を校正済みに")
            pg.click("#btnProofAll")   # 元に戻せる操作なので確認なし(気が利く画面へ 段1。以前は2度押し)
            check(pf() == "校正 %d / %d行" % (n, n), "全行を校正済みに")
            check(pg.locator(".ui-toast .ui-toast-act", has_text="2 カットへ").count() >= 1, "全部済んだら知らせに [2 カットへ](UI の見直し M7。元に戻すは Ctrl+Z)")
            check(pg.inner_text("#btnProofAll") == "校正済みを全解除", "ボタンが全解除に変わる")
            pg.keyboard.press("Control+z")   # 入力欄にフォーカスがなければ元に戻す
            pg.click("#btnUndo")
            check(pf().startswith("校正 ") and pf() != "校正 %d / %d行" % (n, n), "元に戻せる")
            # 一括置換で聞かずに書き換えた行は校正済みが外れる
            before = pg.locator("#segs .seg.proofed").count()
            if not pg.evaluate("document.querySelector('#fixDetails').open"):   # v0.15.0: 置換は「文字をまとめて直す」のカード
                pg.evaluate("document.querySelector('#fixDetails').open = true")   # 段3: 4枚のカードは「…」から開く(閉じている間は隠れている)
                pg.wait_for_selector("#fixDetails:not([hidden])")
            pg.fill("#repFrom", "テスト文")
            pg.fill("#repTo", "テスト文!")
            pg.click("#repGo")
            after = pg.locator("#segs .seg.proofed").count()
            check(after < before, "一括置換で変わった行は校正済みが外れる(%d → %d)" % (before, after))
            # 単語の途中には当てない置換(|語|)・単語の時刻の設定
            check(pg.evaluate("S.settings.wordSplit !== false && !document.querySelector('#optWordSplit')"), "単語の時刻の設定が既定でオン(欄は設定の画面。0.66.0)")
            # ホロライブの名簿(用語集へ追加・効く長さの表示)
            check(pg.locator("#rosterGroups .rg").count() >= 15, "名簿の所属が並ぶ")
            pg.evaluate("document.querySelectorAll('#optGloss')[0].value='' ; document.querySelector('#rosterGroups .rg[value=gen3]').checked=true; document.querySelector('#rosterGroups .rg[value=gen5]').checked=true; document.querySelector('#rosterAdd').click()")
            g = pg.evaluate("document.querySelector('#optGloss').value").split("\n")
            check(g[:2] == ["兎田ぺこら", "不知火フレア"] and len(g) == 8, "選んだ所属の名前が用語集に入る(%d語)" % len(g))
            check("先頭" not in pg.evaluate("document.querySelector('#glossFit').textContent") and "8語" in pg.evaluate("document.querySelector('#glossFit').textContent"), "8語は全部ヒントに入る表示")
            pg.evaluate("document.querySelector('#rosterGroups .rg[value=gen3]').checked=true; document.querySelector('#rosterAdd').click()")
            check(len(pg.evaluate("document.querySelector('#optGloss').value").split("\n")) == 8, "同じ所属を足しても重複しない")
            pg.evaluate("['gen0','gen1','gamers','gen2','gen4','holox','regloss','flowglow','en_advent','en_justice','id1','id2','id3'].forEach(v => document.querySelector('#rosterGroups .rg[value='+v+']').checked=true); document.querySelector('#rosterAdd').click()")
            check("後ろの語は効きません" in pg.evaluate("document.querySelector('#glossFit').textContent"), "長すぎると、効く語数の警告が出る")
            pg.evaluate("document.querySelector('#optGloss').value=''; document.querySelector('#optGloss').dispatchEvent(new Event('input'))")
            # 辞書 |語| は単語の途中に当てない(画面側の一括適用)
            ta = pg.locator("#segs .seg textarea").nth(0)
            ta.fill("トルコとトル様")
            pg.evaluate("document.querySelector('#repDict').value='|トル|=>ポル'")
            pg.click("#repDictGo")
            check(pg.locator("#segs .seg textarea").nth(0).input_value() == "トルコとポル様", "辞書 |語| は単語の途中に当てない(画面側)")
            pg.evaluate("document.querySelector('#repDict').value='トル=>ポル'")
            ta.fill("トルコとトル様"); pg.click("#repDictGo")
            check(pg.locator("#segs .seg textarea").nth(0).input_value() == "ポルコとポル様", "縦棒なしは従来どおり全部置換")
            # 学習候補は語の全体(カタカナの並び)になり、辞書に登録すると |語| の形になる
            t1 = pg.locator("#segs .seg textarea").nth(1)
            orig1 = t1.input_value()
            t1.fill(orig1.replace("テスト", "テスタ"))
            pg.evaluate("document.querySelector('#repDict').value=''")
            pg.wait_for_function("document.body.innerText.includes('保存しました')", timeout=15000)
            pg.select_option("#lnMin", "1")   # v0.9.9: 候補の回数の既定が「2回以上」になったので、1回の修正も出す
            pg.click("#lnRefresh")
            pg.wait_for_function("[...document.querySelectorAll('#lnList .ln .lw')].some(x => x.value === 'テスト')", timeout=10000)
            pg.evaluate("[...document.querySelectorAll('#lnList .ln')].find(r => r.querySelector('.lw').value === 'テスト').querySelector('[data-act=lnadd]').click()")
            pg.wait_for_function("document.querySelector('#repDict').value.includes('|テスト|=>テスタ')", timeout=10000)
            check(True, "学習候補「テスト→テスタ」(語の全体)を登録すると |テスト|=>テスタ になる")
            check(pg.locator("#lnExport").count() == 0, "修正データの書き出しのボタンは無い(0.68.0 で消した)")
            if SHOTS:
                os.makedirs(SHOTS, exist_ok=True)
                pg.screenshot(path=os.path.join(SHOTS, "ui_editor.png"), full_page=False)
                pg.locator("#accCard").scroll_into_view_if_needed()
                pg.locator("#accCard").screenshot(path=os.path.join(SHOTS, "ui_acc.png"))
            b.close()
        check(not errors, "画面のエラーなし " + ("" if not errors else str(errors[:3])))
    finally:
        proc.terminate()
        proc.wait(timeout=10)
        shutil.rmtree(tmp, ignore_errors=True)
    print("ALL PASSED" if ok else "SOME FAILED")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
