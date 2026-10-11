#!/usr/bin/env python3
"""案件の画面(/cases)の「カット・パック」パネル(src/app/ui/cases/panels/cut.js。RS8 C2c)の通し確認(Playwright)。リポジトリ直下で:
    set PYTHONIOENCODING=utf-8
    py -3.10 src/app/tests/e2e_cases_cut.py
入口を編集と cut2resolve を取り込んだ形で動かし(編集の e2e と同じ Server。疑似の文字起こし)、/cases?d=<文書 id>#cut を開く(仮の案件 orphan に入る)。
旧 e2e_edit_cut(カットのタブ)と e2e_edit_pack(パック)の要点だけを 1 本に: 行からのたたき台・波形・区間の選択と削る / 戻す / 元に戻す・自動保存・
殻のキー(Alt+1/2)とパネルのキーの両立・下の帯・字幕の一覧の「残す / カット」・カットしない・パックの設定(大きさ・音量・行の後の余白)が編集の設定に残る・
「予備」の欄が無い(決定 3-34)・パックを作る(区間 = カットのとおり・EDL を入れない)・別の切り抜きを選んでも未保存のカットが残る・コンソールにエラーが無い。
RS8 C4 で足した場面: パックの記録と「作り直しが要る」の理由・同じ場所は確認なしで作り直す・別の場所は 3 択・zip でダウンロード(旧 e2e_ui_mounted)/
カット・パックで行を分けてすぐ校正へ(閉じる側の保存を待つ)/ キーボードだけで区間と端を選んで 1 コマ動かす・2 つの窓の 409 と読み直す・文書の競合の案内(旧 e2e_edit_cut)。"""
import json
import os
import shutil
import sys
import time
import types
import zipfile

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
            _scene_pack_stale(cx)   # 以下 2 つは旧 e2e_ui_mounted(RS8 C4 で消した)から
            _scene_zip(cx)
            _scene_switch(cx)
            _scene_rows_to_proof(cx)
            _scene_edge_keys(cx)   # 以下 2 つは旧 e2e_edit_cut から
            _scene_two_windows(cx)

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


LUA = "create_resolve_textplus_project.lua"


def _pack_done(pg, dir_part=None):
    """パックを作り終える(ジョブが消えてボタンが戻る)まで待つ"""
    cond = "!document.querySelector('#pkBuild').disabled && document.querySelector('#pkJob').hidden && !document.querySelector('dialog.ui-dialog[open]')"
    if dir_part:
        cond += " && document.querySelector('#pkLastDir').textContent.indexOf(%s) >= 0" % json.dumps(dir_part)
    return wait_js(pg, cond, 120000)


def _scene_pack_stale(cx):
    """パックの記録(packRev・作ったときの設定)・カットを変えると「作り直しが要る」と理由・同じ場所は確認なしで作り直す・
    前のパックがある別の場所は 3 択(やめる・別の場所を選ぶ・上書きして作り直す)・字幕を直すと理由「字幕が変わった」(旧 e2e_ui_mounted の 3c)"""
    check, pg, srv, tid, v1 = cx.check, cx.pg, cx.srv, cx.tid, cx.v1
    r = srv.get("/api/edit?id=" + tid)
    e = dict(r["edit"], packStale=r.get("packStale"))
    out = (e.get("pack") or {}).get("output") or {}
    check(e.get("packRev") == e.get("rev") and r.get("packStale") is False and str(out.get("fps")) == str(FPS) and bool(out.get("size")), "パックの記録: packRev = rev・作ったときの設定(fps %s・大きさ %s): %s" % (out.get("fps"), out.get("size"), {k: e.get(k) for k in ("rev", "packRev", "packStale")}))
    check(pg.inner_text("#pkLastPill") == "前回のパック", "前回のパックの札")
    packdir = os.path.splitext(v1)[0] + "_pack"
    mt = os.path.getmtime(os.path.join(packdir, LUA))
    pg.click("#tlVideo .tt-k[data-i='1']")
    pg.keyboard.press("Delete")
    check(cx.wait_saved(4) and wait_js(pg, "document.querySelector('#pkLastPill').textContent === '作り直しが要る'", 30000), "カットを変えると「作り直しが要る」")
    check("カットが変わった" in pg.inner_text("#pkLastWhen") and pg.inner_text("#pkBuild") == "パックを作り直す(上書き)", "理由(カットが変わった)とボタン: %s" % pg.inner_text("#pkLastWhen"))
    pg.click("#pkBuild")
    check(_pack_done(pg) and wait_js(pg, "document.querySelector('#pkLastPill').textContent === '前回のパック'", 10000), "同じ場所へは確認なしで作り直す")
    check(os.path.getmtime(os.path.join(packdir, LUA)) > mt and len(read_pack_plan(os.path.join(packdir, LUA)).get("cuts", [])) == 4, "今のカット(4 区間)で作り直した")
    pg.focus("#tlScroll")
    pg.keyboard.press("Control+z")
    check(cx.wait_saved(5), "Ctrl+Z で 5 区間に戻す(あとの場面の前提)")
    packdir2 = packdir + "_別の場所"
    shutil.copytree(packdir, packdir2)
    pg.evaluate("document.querySelector('#pkMore').open = true")
    pg.fill("#pkDir", packdir2)
    check(wait_js(pg, "document.querySelector('#pkBuild').textContent === 'パックを作る'", 5000), "出力先を変えるとボタンは「パックを作る」")
    pg.click("#pkBuild")
    check(wait_js(pg, "!!document.querySelector('dialog.ui-dialog[open]')", 20000), "前のパックがある別の場所 = 上書きの確認")
    check(LUA in pg.inner_text("dialog.ui-dialog[open] .ui-dlg-body") and pg.evaluate("[...document.querySelectorAll('dialog.ui-dialog[open] .ui-dlg-actions button')].map(b => b.textContent).join('|')") == "やめる|別の場所を選ぶ|上書きして作り直す"
          and pg.evaluate("document.activeElement.textContent") == "やめる", "3 択・最初のフォーカスは「やめる」")
    pg.click("dialog.ui-dialog[open] .ui-dlg-actions button:has-text('やめる')")
    check(_pack_done(pg) and packdir2 not in pg.inner_text("#pkLastDir"), "「やめる」なら作らない")
    pg.click("#pkBuild")
    wait_js(pg, "!!document.querySelector('dialog.ui-dialog[open]')", 20000)
    pg.click("dialog.ui-dialog[open] .ui-dlg-actions button:has-text('上書きして作り直す')")
    check(_pack_done(pg, packdir2), "「上書きして作り直す」で別の場所に作る")
    cx.errors[:] = [x for x in cx.errors if "409" not in x]   # 前のパックがあるときの 409 はブラウザがエラーとして記録する(想定どおり)
    pg.fill("#pkDir", "")
    pg.evaluate("document.activeElement && document.activeElement.blur()")
    # パックのあとに字幕を直す → 理由「字幕が変わった」
    pg.keyboard.press("Alt+1")
    check(wait_js(pg, "CasesShell.state().tab === 'proof' && EditHost.active && !!document.querySelector('#csPane #segs .seg')", 30000), "校正へ")
    pg.locator("#segs textarea").nth(0).fill("直した行1(パックのあと)")
    pg.keyboard.press("Escape")
    pg.keyboard.press("Alt+2")
    check(wait_js(pg, "CasesShell.state().tab === 'cut' && ((document.querySelector('#pkLastWhen') || {}).textContent || '').indexOf('字幕が変わった') >= 0", 30000),
          "カット・パックへ戻ると理由「字幕が変わった」: %s" % pg.inner_text("#pkLastWhen"))
    cx.packdir2 = packdir2


def _scene_zip(cx):
    """「zip でダウンロード」= 同じ Text+ パック(動画は直下・Lua・EDL なし・区間はパックと同じ)と知らせ(旧 e2e_ui_mounted の 3d)"""
    check, pg, srv = cx.check, cx.pg, cx.srv
    pg.evaluate("document.querySelector('#pkMore').open = true")
    with pg.expect_download(timeout=60000) as dl:
        pg.click("#pkZip")
    zpath = os.path.join(srv.tmp, "dl-resolve.zip")
    dl.value.save_as(zpath)
    with zipfile.ZipFile(zpath) as z:
        names = z.namelist()
        lua = next((n for n in names if n.endswith("/" + LUA)), None)
        if lua:
            with open(os.path.join(srv.tmp, "zip-" + LUA), "wb") as f:
                f.write(z.read(lua))
    check(lua and any(n.split("/", 1)[-1] == os.path.basename(cx.v1) for n in names) and not any(n.endswith((".edl", ".srt")) or "/media/" in n for n in names),
          "zip に Lua と動画(直下)・EDL・SRT なし: %s" % names[:5])
    if lua:
        cuts = read_pack_plan(os.path.join(srv.tmp, "zip-" + LUA)).get("cuts")
        check(cuts == read_pack_plan(os.path.join(cx.packdir2, LUA)).get("cuts"), "zip の区間はパックと同じ(カットのとおり)")
    check(wait_js(pg, "[...document.querySelectorAll('.ui-toast')].some(e => e.textContent.indexOf('パック(zip)を作成しました') >= 0)", 10000), "作成できたことを知らせる")
    pg.evaluate("document.querySelector('#pkMore').open = false")


def _scene_edge_keys(cx):
    """キーボードだけで区間と端を選び([ ] と Q / W)、. / , で 1 コマずつ動かす = 保存は 1 コマ(1/30 秒)の丸め(旧 e2e_edit_cut の B-10)"""
    check, pg = cx.check, cx.pg
    pg.keyboard.press("Alt+2")
    check(wait_js(pg, "CasesShell.state().tab === 'cut' && document.querySelectorAll('#tlVideo .tt-k').length >= 2", 30000), "カット・パックへ")
    pg.evaluate("(() => { const v = document.querySelector('#cutPlayer'); v.pause(); v.currentTime = 0; })()")
    wait_js(pg, "document.querySelector('#cutPlayer').currentTime < 0.01", 5000)
    pg.focus("#tlScroll")
    pg.keyboard.press("BracketRight")
    pg.keyboard.press("BracketRight")
    check(wait_js(pg, "!!document.querySelector('#tlVideo .tt-k[data-i=\"1\"].sel')", 3000), "] を 2 回で 2 つ目の区間")
    pg.keyboard.press("BracketLeft")
    check(wait_js(pg, "!!document.querySelector('#tlVideo .tt-k[data-i=\"0\"].sel')", 3000), "[ で前の区間")
    pg.keyboard.press("BracketRight")
    before = cx.server_clips()[1]
    pg.keyboard.press("w")
    check(wait_js(pg, "!!document.querySelector('#tlVideo .tt-k[data-i=\"1\"] .tt-h.out.on')", 3000), "W で終わりの端を選ぶ")
    check(wait_js(pg, "['.', ','].every(k => !!document.querySelector('.ui-keybar [data-k=\"' + k + '\"]'))", 3000), "下の帯が端の場面(, .)になる")

    def moved(want):
        end = time.time() + 15
        while time.time() < end:
            if abs(cx.server_clips()[1][1] - want) < 0.002:
                return True
            time.sleep(0.1)
        return False
    pg.keyboard.press("Period")
    check(moved(round(round(before[1] * FPS + 1) / FPS, 3)), ". で 1 コマ後ろ(保存は 1/30 秒の丸め): %s → %s" % (before, cx.server_clips()[1]))
    pg.keyboard.press("Comma")
    check(moved(before[1]) and cx.server_clips()[1][0] == before[0], ", で戻す: %s" % (cx.server_clips()[1],))
    pg.keyboard.press("q")
    check(wait_js(pg, "!!document.querySelector('#tlVideo .tt-k[data-i=\"1\"] .tt-h.in.on')", 3000), "Q で始まりの端を選ぶ")
    pg.keyboard.press("Escape")


def _scene_two_windows(cx):
    """2 つの窓で同じカットを直す → 後の窓は 409 の案内と「読み直す」/ 文書の競合はカットのパネルにも出て、行のつまみを出さない(旧 e2e_edit_cut の 595-637)"""
    check, pg, srv, tid = cx.check, cx.pg, cx.srv, cx.tid
    n = pg.evaluate("document.querySelectorAll('#tlVideo .tt-k').length")
    pg2 = cx.ctx.new_page()
    pg2.on("pageerror", lambda e: cx.errors.append(str(e)))
    pg2.goto(cx.base + "cases?d=%s#cut" % tid)
    check(wait_js(pg2, "document.querySelectorAll('#tlVideo .tt-k').length === %d && document.querySelector('#cutPlayer').readyState >= 1" % n, 40000), "2 つ目の窓で同じ切り抜きのカットを開く")
    pg2.evaluate("document.querySelector('#cutPlayer').currentTime = 12.0")
    wait_js(pg2, "Math.abs(document.querySelector('#cutPlayer').currentTime - 12.0) < 0.01", 5000)
    pg2.focus("#tlScroll")
    pg2.keyboard.press("s")
    check(wait_js(pg2, "document.querySelector('#cutSaveSt').textContent === 'カットを保存しました'", 10000), "2 つ目の窓で分けて保存")
    n2 = pg2.evaluate("document.querySelectorAll('#tlVideo .tt-k').length")
    pg.bring_to_front()
    pg.evaluate("document.querySelector('#cutPlayer').currentTime = 13.0")
    wait_js(pg, "Math.abs(document.querySelector('#cutPlayer').currentTime - 13.0) < 0.01", 5000)
    pg.focus("#tlScroll")
    pg.keyboard.press("s")
    check(wait_js(pg, "!document.querySelector('#cutConflict').hidden", 10000) and "競合" in pg.inner_text("#cutSaveSt"), "先に保存されていると 409 = 黙って上書きせず案内")
    pg.click("#cutReload")
    check(wait_js(pg, "document.querySelector('#cutConflict').hidden && document.querySelectorAll('#tlVideo .tt-k').length === %d" % n2, 10000), "「読み直す」で先に保存された内容になる")
    pg2.close()
    # 文書(字幕の行)の競合
    d = srv.get("/api/transcript?id=" + tid)
    srv.call("PUT", "/api/transcript?id=" + tid, {"title": d["title"], "speakers": d.get("speakers", []), "segments": d["segments"], "baseUpdatedAt": d["updatedAt"]})   # 別の所で先に保存した
    pg.click("#cutZoomFit")
    pg.click("#tlSubs .tt-s[data-i='1']")
    wait_js(pg, "!!document.querySelector('#tlSubs .tt-s[data-i=\"1\"].sel')", 3000)
    pg.keyboard.press("w")
    pg.keyboard.press("Period")   # 行の時刻を直す → 文書の保存 → 409
    check(wait_js(pg, "!document.querySelector('#cutDocConflict').hidden", 10000) and pg.locator("#tlSubs .tt-rh").count() == 0, "文書の競合の案内がカットのパネルに出て、行のつまみは消える")
    pg.click("#cutDocConflictGo")
    check(wait_js(pg, "document.querySelector('#cutDocConflict').hidden", 10000), "案内のボタンで保存済みの文字起こしを読み直す")
    cx.errors[:] = [x for x in cx.errors if "409" not in x]   # わざと起こした 409


def _scene_rows_to_proof(cx):
    """カット・パックのパネルで行を分けて、すぐ校正へ(RS8 C4: 閉じる側の文書の保存を、開く校正が待ってから読む)= 校正の行が新しい・409 にならない"""
    check, pg, srv, tid = cx.check, cx.pg, cx.srv, cx.tid
    n = len(srv.get("/api/transcript?id=" + tid)["segments"])
    pg.click("#tlSubs .tt-s[data-i='3']")   # 行 4(11.0〜14.5 秒)を選ぶ
    pg.evaluate("(() => { const v = document.querySelector('#cutPlayer'); v.pause(); v.currentTime = 12.6; })()")
    check(wait_js(pg, "!!document.querySelector('#cutStatus [data-act=rowsplit]') && !document.querySelector('#cutStatus [data-act=rowsplit]').disabled", 5000), "行を選ぶと「再生位置でこの行を分ける」が押せる")
    pg.click("#cutStatus [data-act=rowsplit]")
    check(wait_js(pg, "!!document.querySelector('#cutSplitDlg[open]')", 5000), "文字のどこで分けるかの確認が開く")
    pg.keyboard.press("Enter")
    check(wait_js(pg, "document.querySelectorAll('#tlSubs .tt-s').length === %d" % (n + 1), 5000), "字幕の段が %d 行に" % (n + 1))
    pg.keyboard.press("Alt+1")   # 文書の保存のまとめを待たずに校正へ
    check(wait_js(pg, "CasesShell.state().tab === 'proof' && typeof EditHost === 'object' && EditHost.active && S.docId === '%s' && S.doc.segments.length === %d" % (tid, n + 1), 30000),
          "校正の行は分けたあとの %d 行: %s" % (n + 1, pg.evaluate("typeof S === 'object' && S.doc ? S.doc.segments.length : null")))
    check(len(srv.get("/api/transcript?id=" + tid)["segments"]) == n + 1, "分けた行は閉じる前に保存された")
    time.sleep(0.5)
    check(pg.evaluate("document.querySelector('#conflictBar').hidden"), "保存の競合(409)の案内が出ない")
    # 区間(edit.json)が決まっている文書で、校正の行の「カット」を押すと、印だけ変えて黙って消える代わりにカット・パックのタブへ案内する(RS8 C4)
    check(srv.get("/api/edit?id=" + tid).get("edit") is not None, "(前提)カットの区間が保存されている")
    i = pg.evaluate("S.doc.segments.findIndex(g => g.cutState !== 'cut' && String(g.text || '').trim())")
    before = srv.get("/api/transcript?id=" + tid)["segments"][i].get("cutState")
    pg.evaluate("i => document.querySelector('#segs .seg[data-i=\"' + i + '\"]').scrollIntoView({block: 'center'})", i)
    pg.click("#segs .seg[data-i='%d'] [data-act=cut]" % i)
    check(wait_js(pg, "[...document.querySelectorAll('.ui-toast')].some(t => /カット・パック」のタブで変えます/.test(t.textContent))", 5000), "区間があるときは校正で印を変えずにカット・パックへ案内する")
    time.sleep(1.2)
    check(pg.evaluate("i => S.doc.segments[i].cutState !== 'cut'", i) and srv.get("/api/transcript?id=" + tid)["segments"][i].get("cutState") == before,
          "画面の印もサーバーの印も変わらない(黙って消える印を付けない)")


if __name__ == "__main__":
    sys.exit(main())
