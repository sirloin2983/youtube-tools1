#!/usr/bin/env python3
"""1 文字起こし: 再生に合わせて行を追いかけても、窓(映像の列・メニュー・題名の行)は動かさず、行の一覧の列の中だけを動かす(v0.56.1。2026-10-06 ユーザーの指摘)。
2列の幅で、長い一覧の文書を開き、再生位置を一覧の下の方の行へ進めて、窓の scrollY が 0 のまま・一覧(.tx-list)の scrollTop だけが増えることを確かめる。
1列の幅(狭い窓)では今までどおり窓が動く(一覧は自分でスクロールしない)。"""
import os
os.environ.setdefault("YTT_DATA_DIR", "inplace")
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from e2e_edit_common import Checks, Server, make_video, open_doc, wait_js  # noqa: E402
from playwright.sync_api import sync_playwright  # noqa: E402


def main():
    ck = Checks()
    srv = Server()
    try:
        vid = make_video(os.path.join(srv.media, "long.webm"), sec=150)
        srv.transcribe(vid, title="追いかけ")
        with sync_playwright() as p:
            br = p.chromium.launch()
            pg = br.new_page(viewport={"width": 1500, "height": 800})
            errs = []
            pg.on("pageerror", lambda e: errs.append(str(e)))
            pg.goto(srv.base)
            open_doc(pg, "追いかけ")
            wait_js(pg, "document.querySelectorAll('#segs .seg').length > 20")
            pg.evaluate("document.querySelector('#follow').checked = true")
            st = pg.evaluate("(() => { const b = document.querySelector('.tx-list'), cs = getComputedStyle(b); return {ov: cs.overflowY, pos: cs.position, sh: b.scrollHeight, ch: b.clientHeight}; })()")
            ck(st["ov"] in ("auto", "scroll") and st["pos"] == "sticky" and st["sh"] > st["ch"], "2列では行の一覧が自分でスクロールする箱: %s" % st)
            n = pg.evaluate("document.querySelectorAll('#segs .seg').length")
            # 再生位置を下の方の行へ(timeupdate で今の行が変わり、追いかける)
            for frac in (0.5, 0.9):
                pg.evaluate("(f => { const s = [...document.querySelectorAll('#segs .seg')]; const v = document.querySelector('#player'); "
                            "const i = Math.floor(s.length * f); v.currentTime = Number(s[i].dataset.start || 0) || (v.duration * f); v.dispatchEvent(new Event('timeupdate')); })(%s)" % frac)
                pg.wait_for_timeout(900)
            r = pg.evaluate("({y: window.scrollY, ly: document.querySelector('.tx-list').scrollTop, cur: (() => { const c = document.querySelector('#segs .seg.cur'); if (!c) return null; const a = c.getBoundingClientRect(), b = document.querySelector('.tx-list').getBoundingClientRect(); return {top: a.top, bottom: a.bottom, bt: b.top, bb: Math.min(b.bottom, innerHeight)}; })()})")
            ck(r["y"] == 0, "再生で行を追いかけても窓は動かない(scrollY %s)" % r["y"])
            ck(r["ly"] > 0, "一覧の列の中だけが動く(scrollTop %s・行 %d)" % (r["ly"], n))
            c = r["cur"]
            ck(c is not None and c["top"] >= c["bt"] and c["bottom"] <= c["bb"], "今の行は一覧の見える所にある: %s" % c)
            # 行の移動のキー(S)でも窓は動かない
            pg.evaluate("document.activeElement && document.activeElement.blur()")
            for _ in range(5):
                pg.keyboard.press("s")
            pg.wait_for_timeout(500)
            ck(pg.evaluate("window.scrollY") == 0, "キーで行を移っても窓は動かない")
            # 1列の幅では、今までどおり窓が動く
            pg.set_viewport_size({"width": 700, "height": 800})
            pg.wait_for_timeout(400)
            ov = pg.evaluate("getComputedStyle(document.querySelector('.tx-list')).overflowY")
            ck(ov == "visible", "1列では一覧は自分でスクロールしない(窓が動く): %s" % ov)
            ck(not errs, "画面のエラーなし: %s" % errs)
            br.close()
    finally:
        srv.stop()
    print("ALL PASSED" if ck.ok else "SOME FAILED")
    sys.exit(0 if ck.ok else 1)


if __name__ == "__main__":
    main()
