"""YouTube Studio 投稿時刻(Chrome 拡張)の通しの確認。

本物の Studio の代わりに、同じ URL(https://studio.youtube.com/...)に見せかけた偽のページ(Playwright の route で差し替え)に
拡張を読み込ませ、fetch/XHR の包み・行への書き足し・shadow DOM の中の行・行の使い回し(Polymer の真似)を確かめる。
Studio の本物の作り(内部 API の鍵の名前・行の class)が変わったことは分からない(それは手で。README の「動かないとき」)。

ブラウザ: 拡張を --load-extension で入れられるものが要る。本物の Chrome は 137 以降この引数を受け付けない(拡張は入らない)ので、
Edge(Windows に最初から入っている)→ Playwright の chromium(headless → 窓あり)の順に試す。
必要: playwright。1 本ずつ・PYTHONIOENCODING=utf-8 で:
  py -3.10 chrome-ext/yt-studio-time/tests/e2e_fake_studio.py
"""
import json
import os
import sys
import tempfile
import time

from playwright.sync_api import sync_playwright

HERE = os.path.dirname(os.path.abspath(__file__))
EXT = os.path.dirname(HERE)                       # manifest.json のあるフォルダ
T1, T2, T3, T4 = 1759640580, 1759600000, 1759700000, 1759800000   # 公開・アップロードの秒(画面にはローカル時刻で出る)
EDGE = [p for p in (r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe", r"C:\Program Files\Microsoft\Edge\Application\msedge.exe")
        if os.path.exists(p)]

VIDEOS_P1 = {"videos": [
    {"videoId": "AAAAAAAAAAA", "title": "1", "timePublishedSeconds": str(T1), "timeCreatedSeconds": str(T2)},
    {"videoId": "BBBBBBBBBBB", "title": "2", "timeCreatedSeconds": str(T2)},                                   # 非公開: アップロードの時刻だけ
    {"videoId": "CCCCCCCCCCC", "title": "3", "timePublishedSeconds": T3, "timeCreatedSeconds": T3 - 60},     # 数でも読む
]}
VIDEOS_P2 = {"videos": [{"videoId": "DDDDDDDDDDD", "title": "4", "timePublishedSeconds": str(T4), "timeCreatedSeconds": str(T4 - 100)}]}

PAGE = """<!doctype html><html><head><meta charset="utf-8"><title>fake studio</title></head><body>
<div id="list"></div>
<script>
function row(id, date, label) {
  const r = document.createElement('ytcp-video-row');
  r.innerHTML = '<div class="tablecell-video"><a id="video-title" href="/video/' + id + '/edit">title ' + id + '</a></div>'
    + '<div class="tablecell-date style-scope ytcp-video-row"><div class="date-text">' + date + '</div><div class="date-sub-text">' + label + '</div></div>';
  return r;
}
window.__steps = [];
fetch('/youtubei/v1/creator/list_creator_videos?alt=json', {method: 'POST', body: '{}'}).then(r => r.json()).then(d => {
  const list = document.getElementById('list');
  list.appendChild(row('AAAAAAAAAAA', '2026/10/05', '公開日'));
  list.appendChild(row('BBBBBBBBBBB', '2026/10/05', 'アップロード日'));
  list.appendChild(row('ZZZZZZZZZZZ', '2026/10/04', '公開日'));
  const host = document.createElement('ytcp-video-section-content');
  list.appendChild(host);
  host.attachShadow({mode: 'open'}).appendChild(row('CCCCCCCCCCC', '2026/10/06', '公開日'));
  window.__steps.push('p1');
});
window.page2 = function () {
  const x = new XMLHttpRequest();
  x.open('POST', '/youtubei/v1/creator/list_creator_videos?alt=json');
  x.responseType = 'json';
  x.onload = function () {
    const first = document.querySelector('ytcp-video-row');
    first.querySelector('a').setAttribute('href', '/video/DDDDDDDDDDD/edit');
    first.querySelector('.date-text').textContent = '2026/10/07';
    window.__steps.push('p2');
  };
  x.send('{"page":2}');
};
</script></body></html>"""

COLLECT = """(() => {
  const out = {};
  const q = (root) => root.querySelectorAll('ytcp-video-row').forEach(r => {
    const a = r.querySelector('a');
    const ss = r.querySelectorAll('.ytt-pub-time');
    const s = ss[0];
    out[a.getAttribute('href')] = s ? {text: s.textContent, title: s.title, key: s.dataset.key, parent: s.parentElement.className, count: ss.length,
                                       line: s.parentElement.textContent} : null;
  });
  q(document);
  document.querySelectorAll('ytcp-video-section-content').forEach(h => q(h.shadowRoot));
  return out;
})()"""


def hm(sec):
    return time.strftime("%H:%M", time.localtime(sec))


def full(sec):
    return time.strftime("%Y/%m/%d %H:%M:%S", time.localtime(sec))


def handle(route, request):
    if "/youtubei/v1/creator/list_creator_videos" in request.url:
        body = VIDEOS_P2 if '"page":2' in (request.post_data or "") else VIDEOS_P1
        route.fulfill(status=200, content_type="application/json", body=json.dumps(body))
    else:
        route.fulfill(status=200, content_type="text/html; charset=utf-8", body=PAGE)


def wait(page, js, cond, timeout=10):
    """js の値が cond(値) を満たすまで待って値を返す(CSP のある画面に合わせて evaluate で待つ)"""
    end = time.time() + timeout
    v = None
    while time.time() < end:
        v = page.evaluate(js)
        if cond(v):
            return v
        time.sleep(0.1)
    raise AssertionError("timeout: " + js[:80] + " / last=" + json.dumps(v, ensure_ascii=False)[:300])


def run(p, launch):
    """launch(launch_persistent_context の引数)で拡張を入れて確かめる。拡張が入らなければ (None, logs)"""
    logs = []
    with tempfile.TemporaryDirectory() as ud:
        ctx = p.chromium.launch_persistent_context(ud, args=["--disable-extensions-except=" + EXT, "--load-extension=" + EXT], **launch)
        try:
            ctx.route("https://studio.youtube.com/**", handle)
            page = ctx.new_page()
            page.on("console", lambda m: logs.append(m.text))
            page.on("pageerror", lambda e: logs.append("pageerror: " + str(e)))
            page.add_init_script("try { localStorage.setItem('yttStudioTimeDebug', '1'); } catch (e) {}")
            page.goto("https://studio.youtube.com/channel/UCxxxx/videos/short")
            wait(page, "window.__steps.includes('p1')", bool)
            try:
                wait(page, "!!window.__yttStudioTime", bool, timeout=3)
            except AssertionError:
                return None, logs
            # 1 ページ目: 公開日 → 公開の時刻 / アップロード日 → アップロードの時刻 / 応答に無い行は何も出ない / shadow DOM の中の行にも出る
            out = wait(page, COLLECT, lambda o: all(o.get(k) for k in ("/video/AAAAAAAAAAA/edit", "/video/BBBBBBBBBBB/edit", "/video/CCCCCCCCCCC/edit")))
            a, b, c, z = out["/video/AAAAAAAAAAA/edit"], out["/video/BBBBBBBBBBB/edit"], out["/video/CCCCCCCCCCC/edit"], out.get("/video/ZZZZZZZZZZZ/edit", "missing")
            assert a["text"] == hm(T1) and a["key"] == "AAAAAAAAAAA:%d" % T1 and a["parent"] == "date-text" and a["count"] == 1, a
            assert a["title"] == "公開 %s / アップロード %s" % (full(T1), full(T2)), a["title"]
            assert a["line"] == "2026/10/05" + hm(T1), a["line"]           # 日付の文字の直後(余白は CSS)
            assert b["text"] == hm(T2) and b["key"] == "BBBBBBBBBBB:%d" % T2 and b["title"] == "アップロード " + full(T2), b
            assert c["text"] == hm(T3) and c["parent"] == "date-text" and c["count"] == 1, c
            assert z is None, z
            # 2 ページ目(XHR)で 1 行目が使い回される: id と日付が変わる → 時刻も変わる(古い span が残らない)
            page.evaluate("window.page2()")
            wait(page, "window.__steps.includes('p2')", bool)
            out = wait(page, COLLECT, lambda o: (o.get("/video/DDDDDDDDDDD/edit") or {}).get("key") == "DDDDDDDDDDD:%d" % T4)
            d = out["/video/DDDDDDDDDDD/edit"]
            assert d["text"] == hm(T4) and d["count"] == 1 and d["line"] == "2026/10/07" + hm(T4), d
            assert "/video/AAAAAAAAAAA/edit" not in out, list(out)
            # 控えには 4 本(応答 2 回分)
            assert page.evaluate("__yttStudioTime.times.size") == 4
            return out, logs
        finally:
            ctx.close()


def main():
    cands = [("Edge headless", {"executable_path": e, "headless": True}) for e in EDGE[:1]]
    cands += [("Playwright の chromium headless", {"channel": "chromium", "headless": True}), ("Playwright の chromium 窓あり", {"headless": False})]
    with sync_playwright() as p:
        for name, launch in cands:
            try:
                out, logs = run(p, launch)
            except Exception as e:                       # 起動できない(この PC では channel="chromium" が spawn UNKNOWN)
                print("%s: 起動できない -> %s" % (name, str(e).splitlines()[0][:120]))
                continue
            if out is None:
                print("%s: 拡張が入らなかった(次を試す)" % name)
                continue
            ext_logs = [l for l in logs if "[ytt-pub-time]" in l]
            print("console(拡張の記録 %d 行):" % len(ext_logs), *ext_logs[-6:], sep="\n  ")
            bad = [l for l in logs if "pageerror" in l or "行の処理に失敗" in l]
            assert not bad, bad
            print("OK (%s): 行 4 + 使い回し 1 / fetch と XHR の両方から控えた / shadow DOM の行にも出た" % name)
            return 0
    print("NG: どのブラウザでも拡張が入らなかった")
    return 1


if __name__ == "__main__":
    sys.exit(main())
