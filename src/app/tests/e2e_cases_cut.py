#!/usr/bin/env python3
"""案件の画面(/cases)の「カット・パック」パネル(src/app/ui/cases/panels/cut.js。RS8 C2c)の通し確認(Playwright)。リポジトリ直下で:
    set PYTHONIOENCODING=utf-8
    py -3.10 src/app/tests/e2e_cases_cut.py
入口を編集と cut2resolve を取り込んだ形で動かし(編集の e2e と同じ Server。疑似の文字起こし)、/cases?d=<文書 id>#cut を開く(仮の案件 orphan に入る)。
旧 e2e_edit_cut(カットのタブ)と e2e_edit_pack(パック)の要点だけを 1 本に: 行からのたたき台・波形・区間の選択と削る / 戻す / 元に戻す・自動保存・
殻のキー(Alt+1/2)とパネルのキーの両立・下の帯・字幕の一覧の「残す / カット」・カットしない・パックの設定(大きさ・音量・行の後の余白)が編集の設定に残る・
「予備」の欄が無い(決定 3-34)・パックを作る(区間 = カットのとおり・EDL を入れない)・別の切り抜きを選んでも未保存のカットが残る・コンソールにエラーが無い。"""
import os
import shutil
import sys
import time
import types

from playwright.sync_api import sync_playwright

TESTS = os.path.dirname(os.path.abspath(__file__))   # src/app/tests
SRC = os.path.dirname(os.path.dirname(TESTS))
sys.path.insert(0, os.path.join(SRC, "editor", "tests"))
from e2e_edit_common import Checks, Server, make_video, read_pack_plan, wait_js  # noqa: E402

FPS = 30
ROWS = [(0.5, 3.2), (4.0, 6.5), (7.0, 9.8), (11.0, 14.5), (15.2, 19.0)]


def main():
    check = Checks()
    srv = Server(mounted=True)
    errors = []
    try:
        shutil.copytree(os.path.join(SRC, "ui-kit"), os.path.join(srv.tmp, "ui-kit"))   # 入口は共通の見た目を src/ui-kit から直に配る(一時フォルダには写っていない)
        v1 = make_video(os.path.join(srv.media, "カットの確認.webm"), sec=20, fps=FPS, beeps=ROWS)
        tid = srv.transcribe(v1, "カットの確認")
        doc = srv.get("/api/transcript?id=" + tid)
        segs = [{"id": "r%d" % (i + 1), "start": a, "end": b, "text": "行%d" % (i + 1)} for i, (a, b) in enumerate(ROWS)]
        srv.call("PUT", "/api/transcript?id=" + tid, {"title": doc["title"], "speakers": [], "segments": segs})
        v2 = make_video(os.path.join(srv.media, "もう1本.webm"), sec=10, fps=FPS)
        tid2 = srv.transcribe(v2, "もう1本")

        with sync_playwright() as pw:
            b = pw.chromium.launch()
            ctx = b.new_context(viewport={"width": 1440, "height": 950})
            pg = ctx.new_page()
            pg.on("pageerror", lambda e: errors.append(str(e)))
            pg.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
            base = "http://localhost:%d/" % srv.port
            pg.goto(base + "cases?d=%s#cut" % tid)
            wait_js(pg, "document.querySelectorAll('#tlVideo .tt-k').length === 5", 40000)

            def server_clips(i=None):
                e = srv.get("/api/edit?id=" + (i or tid))["edit"]
                return None if e is None else [(c["in"], c["out"]) for c in e["clips"]]

            def wait_saved(n):
                end = time.time() + 15
                while time.time() < end:
                    got = server_clips()
                    if got is not None and len(got) == n:
                        return True
                    time.sleep(0.1)
                return False

            cx = types.SimpleNamespace(**locals())
            _scene_open(cx)
            _scene_edit_keys(cx)
            _scene_rows_whole(cx)
            _scene_pack_settings(cx)
            _scene_build(cx)
            _scene_switch(cx)

            check(not errors, "画面のエラー・コンソールのエラーが無い: %s" % errors[:5])
            b.close()
    finally:
        srv.stop()
    print("ALL PASSED" if check.ok else "SOME FAILED")
    return 0 if check.ok else 1


def _scene_open(cx):
    """開く: 行からのたたき台 5 区間・開いただけでは保存しない・波形・予備の欄が無い・殻のキーと下の帯"""
    check, pg, srv, tid = cx.check, cx.pg, cx.srv, cx.tid
    shell = pg.evaluate("CasesShell.state()")
    check(shell["tab"] == "cut" and shell["panel"] == "cut" and shell["docId"] == tid, "#cut で、この切り抜きのカット・パックのパネル: %s" % shell)
    check("文字起こしの行から作ったたたき台" in pg.inner_text("#cutStatus") and "残す 5区間" in pg.inner_text("#cutStatus"), "行からのたたき台(5 区間): " + pg.inner_text("#cutStatus"))
    check(cx.server_clips() is None, "開いただけでは保存しない")
    wait_js(pg, """(() => { const c = document.querySelector('#tlWave'), sc = document.querySelector('#tlScroll');
      const pps = sc.scrollWidth / 20, x = Math.round((1.0 * pps - sc.scrollLeft) * (window.devicePixelRatio || 1));
      const d = c.getContext('2d').getImageData(x, 0, 1, c.height).data; let n = 0; for (let i = 3; i < d.length; i += 4) if (d[i] > 0) n++; return n > 10; })()""", 20000)
    check(True, "音の波形が出る(編集の /api/peaks)")
    check(pg.evaluate("!document.querySelector('#pkBackup')"), "パックに「予備」の欄が無い(決定 3-34)")
    check("3 パック" not in pg.inner_text("#csPane"), "画面に古い言い方「3 パック」が残っていない")
    check(pg.evaluate("document.querySelector('#cutPlayer').src.indexOf('/transcribe/media?id=') > 0"), "動画は編集の /transcribe/media から")
    check(wait_js(pg, "['Alt+1', 'Alt+2', 'Shift+N'].every(k => !!document.querySelector('.ui-keybar [data-k=\"' + k + '\"]')) && !!document.querySelector('.ui-keybar [data-k=\"Del\"]')", 5000),
          "下の帯は 殻のキー(Alt+1・Alt+2・Shift+N)とカットのキー(Del など)")
    check(pg.evaluate("document.querySelectorAll('[data-cs-stub]').length") == 0, "空のパネルの案内は出ていない")


def _scene_edit_keys(cx):
    """区間を選んで Del(保存)→ Ctrl+Z(戻る)・S の分割・[ ] で区間を選ぶ。Alt+1 / Alt+2 の殻のキーはそのまま効く"""
    check, pg, srv, tid = cx.check, cx.pg, cx.srv, cx.tid
    pg.click("#tlVideo .tt-k[data-i='1']")
    check(pg.evaluate("document.querySelector('#tlVideo .tt-k.sel') && document.querySelector('#tlVideo .tt-k.sel').dataset.i") == "1", "区間を押すと選べる")
    pg.keyboard.press("Delete")
    check(wait_js(pg, "document.querySelectorAll('#tlVideo .tt-k').length === 4", 5000), "Del で 1 区間を削る(4 区間)")
    check(cx.wait_saved(4), "自動保存されて、サーバーの区間が 4 つ: %s" % cx.server_clips())
    check(wait_js(pg, "document.querySelector('#cutSaveSt').textContent === 'カットを保存しました'", 10000), "保存の状態の表示(パネルの中)")
    pg.keyboard.press("Control+z")
    check(wait_js(pg, "document.querySelectorAll('#tlVideo .tt-k').length === 5", 5000), "Ctrl+Z で戻る(5 区間)")
    check(cx.wait_saved(5), "戻したカットも保存される")
    pg.keyboard.press("BracketRight")
    check(pg.evaluate("document.querySelector('#tlVideo .tt-k.sel') !== null"), "] で区間を選ぶ(パネルのキー)")
    pg.evaluate("document.activeElement && document.activeElement.blur()")
    pg.evaluate("(() => { const v = document.querySelector('#cutPlayer'); v.pause(); v.currentTime = 1.5; })()")
    pg.keyboard.press("s")
    check(wait_js(pg, "document.querySelectorAll('#tlVideo .tt-k').length === 6", 5000), "S で再生位置(1.5 秒)の区間を分割(6 区間)")
    pg.keyboard.press("Control+z")
    wait_js(pg, "document.querySelectorAll('#tlVideo .tt-k').length === 5", 5000)
    pg.keyboard.press("Alt+1")
    check(wait_js(pg, "CasesShell.state().tab === 'proof'", 5000), "Alt+1 は殻が取って校正のタブへ(カットのキーに食われない)")
    pg.keyboard.press("Alt+2")
    check(wait_js(pg, "CasesShell.state().tab === 'cut' && document.querySelectorAll('#tlVideo .tt-k').length === 5", 20000), "Alt+2 でカットのタブへ戻ると、保存したカットで開き直す")
    check(pg.evaluate("document.querySelectorAll('#csPane #tabCut').length") == 1, "タブを開き直しても、パネルは 1 つだけ")


def _scene_rows_whole(cx):
    """字幕の一覧の「カット」→ その行の時間が削る区間に・「カットしない」で動画全体 1 区間・「行から」で戻す"""
    check, pg, tid = cx.check, cx.pg, cx.tid
    wait_js(pg, "document.querySelectorAll('#cutSubs .tt-csub').length === 5", 10000)
    pg.click("#cutSubs .tt-csub[data-i='2'] [data-act='cutrow']")
    check(wait_js(pg, "document.querySelectorAll('#tlVideo .tt-k').length === 4 && document.querySelector('#cutSubs .tt-csub[data-i=\"2\"]').classList.contains('cut')", 5000),
          "字幕の一覧の「カット」で、その行が削る区間になる(4 区間・行は「カット済」)")
    pg.click("#cutSubs .tt-csub[data-i='2'] [data-act='keeprow']")
    check(wait_js(pg, "document.querySelectorAll('#tlVideo .tt-k').length === 5", 5000), "「残す」で戻る")
    pg.click("#cutNone")
    if pg.is_visible(".ui-dialog, dialog[open]"):
        pg.click("dialog[open] .btn.primary")
    check(wait_js(pg, "document.querySelectorAll('#tlVideo .tt-k').length === 1", 5000), "「カットしない」で動画全体の 1 区間")
    pg.keyboard.press("Control+z")
    check(wait_js(pg, "document.querySelectorAll('#tlVideo .tt-k').length === 5", 5000), "Ctrl+Z で 5 区間に戻る")
    check(cx.wait_saved(5), "保存済みのカットは 5 区間")


def _scene_pack_settings(cx):
    """パックの設定(パネルの中。古い画面は ⚙ の引き出し): 大きさ・音量(%)・行の後の余白が編集の設定に残る"""
    check, pg, srv = cx.check, cx.pg, cx.srv
    check("30fps" in pg.inner_text("#pkSummaryText"), "前回の設定の要約(30fps): " + pg.inner_text("#pkSummaryText"))
    pg.click("#pkSettingsBtn")
    check(wait_js(pg, "document.activeElement && document.activeElement.closest('#edSetPack') !== null", 5000), "「設定を変える」でパネルの中の「パックの設定」へ移る")
    pg.click("#pkSize [data-v='1920x1080']")
    pg.select_option("#pkLoud", "0")
    wait_js(pg, "!document.querySelector('#pkVolBox').hidden", 5000)
    pg.fill("#pkVol", "70")
    pg.press("#pkVol", "Tab")
    pg.fill("#pkPadAfter", "0.5")
    pg.press("#pkPadAfter", "Tab")
    end = time.time() + 10
    while time.time() < end:
        st = srv.get("/api/settings")
        if st.get("packSize") == "1920x1080" and st.get("packVolume") == 70 and (st.get("rowEdge") or {}).get("padAfter") == 0.5:
            break
        time.sleep(0.2)
    check(st.get("packSize") == "1920x1080" and st.get("packVolume") == 70 and (st.get("rowEdge") or {}).get("padAfter") == 0.5,
          "編集の設定に残る(大きさ・音量 70%%・行の後の余白 0.5): %s" % {k: st.get(k) for k in ("packSize", "packVolume", "rowEdge")})
    check(wait_js(pg, "document.querySelector('#pkSummaryText').textContent.indexOf('音量 70%') >= 0 && document.querySelector('#pkSummaryText').textContent.indexOf('行の後の余白 0.5秒') >= 0", 5000),
          "要約に音量と余白: " + pg.inner_text("#pkSummaryText"))
    pg.click("#pkSize [data-v='1080x1920']")
    pg.fill("#pkPadAfter", "0.2")
    pg.press("#pkPadAfter", "Tab")
    end = time.time() + 10
    while time.time() < end and (srv.get("/api/settings").get("rowEdge") or {}).get("padAfter") != 0.2:
        time.sleep(0.2)
    check(srv.get("/api/settings").get("packSize") == "1080x1920", "縦に戻した")


def _scene_build(cx):
    """パックを作る: 見積もり(区間 5・字幕 5)→ 作る → 前回のパック・パックの区間 = カットのとおり・EDL(予備)を入れない"""
    check, pg, srv, v1 = cx.check, cx.pg, cx.srv, cx.v1
    wait_js(pg, "document.querySelector('#pkCount').textContent === '5' && document.querySelector('#pkCaps').textContent === '5'", 40000)
    check(True, "これから作るパックの見積もり(5 区間・字幕 5)")
    check(wait_js(pg, "!document.querySelector('#pkBuild').disabled", 10000), "cut2resolve が使えて「パックを作る」が押せる: " + pg.inner_text("#pkOff"))
    pg.click("#pkBuild")
    wait_js(pg, "(!document.querySelector('#pkLast').hidden || !document.querySelector('#pkErr').hidden) && document.querySelector('#pkJob').hidden && !document.querySelector('#pkBuild').disabled", 120000)
    check(pg.is_hidden("#pkErr"), "パックができる(エラーが出ない): " + pg.inner_text("#pkErr"))
    packdir = os.path.splitext(v1)[0] + "_pack"
    names = sorted(os.path.relpath(os.path.join(r, n), packdir).replace(os.sep, "/") for r, _, ns in os.walk(packdir) for n in ns)
    check(not [n for n in names if n.lower().endswith((".edl", ".srt"))] and any(n.endswith(".lua") for n in names), "EDL・SRT(予備)は入らず Text+ のスクリプトが入る: %s" % names)
    ip = read_pack_plan(os.path.join(packdir, "create_resolve_textplus_project.lua"))
    got = [(c["sourceStartFrame"], c["sourceEndFrame"]) for c in ip.get("cuts", [])]
    want = [(round(a * FPS), round(b * FPS)) for a, b in ROWS]
    check(len(got) == 5 and all(abs(g[0] - w[0]) <= 15 and abs(g[1] - w[1]) <= 15 for g, w in zip(got, want)), "パックの区間 = カットのタブの区間(行から広げた 5 区間): %s" % got)
    check(len(ip.get("captions", [])) == 5, "字幕 5 件")
    check(wait_js(pg, "!document.querySelector('#pkLast').hidden && document.querySelector('#pkLastDir').textContent.indexOf('_pack') > 0", 5000), "前回のパックの欄が出る: " + pg.inner_text("#pkLastDir"))
    e = srv.get("/api/edit?id=" + cx.tid)["edit"]
    check(e and e.get("pack") and (e["pack"].get("output") or {}).get("backup") in (False, None), "パックの記録の output.backup は偽: %s" % (e and e.get("pack", {}).get("output")))
    check(wait_js(pg, "document.querySelector('#csRail [data-cs-key=\"d:%s\"] .pill').textContent === 'パック済み'" % cx.tid, 20000), "左の一覧の札が「パック済み」に変わる")


def _scene_switch(cx):
    """未保存のカットを持ったまま別の切り抜きを選んでも保存される・別の切り抜きのカットが開く"""
    check, pg, srv, tid, tid2 = cx.check, cx.pg, cx.srv, cx.tid, cx.tid2
    pg.click("#tlVideo .tt-k[data-i='0']")
    pg.keyboard.press("Delete")
    wait_js(pg, "document.querySelectorAll('#tlVideo .tt-k').length === 4", 5000)
    pg.click("#csRail [data-cs-key='d:%s']" % tid2)   # 保存の 0.8 秒を待たずに切り替える
    check(wait_js(pg, "CasesShell.state().docId === '%s' && CasesShell.state().tab === 'cut'" % tid2, 10000), "別の切り抜きを選ぶと、カットのタブのまま")
    check(wait_js(pg, "document.querySelectorAll('#tlVideo .tt-k').length >= 1 && document.querySelectorAll('#csPane #tabCut').length === 1", 40000), "もう 1 本のカットが開く")
    check(cx.wait_saved(4), "切り替える前の未保存のカットが保存された: %s" % cx.server_clips())
    pg.click("#csRail [data-cs-key='d:%s']" % tid)
    check(wait_js(pg, "document.querySelectorAll('#tlVideo .tt-k').length === 4", 40000), "戻ると、保存したカット(4 区間)で開く")


if __name__ == "__main__":
    sys.exit(main())
