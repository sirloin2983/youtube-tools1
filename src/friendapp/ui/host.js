/* 窓と画面の境目(F3-1。notes:plan/done/f1-friend-requirements.md の C-1、資料の git:before-1028-cleanup:docs/design/friend-history.md の 7 章)。
   FriendApp.exe(WebView2)の窓の中なら window.chrome.webview で exe と話す。窓の外(WebView2 の無い PC の Edge の窓・開発の PC)は代わりの動き。
   合言葉は exe が要求ごとに足すので、ここでも画面のほかの所でも扱わない(UIKit.http で呼ぶだけ)。 */
(function () {
  'use strict';
  var wv = window.chrome && window.chrome.webview ? window.chrome.webview : null;
  var seq = 0, waiting = {}, loginCb = null;

  if (wv) {
    wv.addEventListener('message', function (ev) {
      var m = ev.data;
      if (m && m.type === 'ytlogin' && loginCb) { var lc = loginCb; loginCb = null; lc(!!m.ok, m.message || ''); return; }
      if (!m || m.type !== 'files' || !waiting[m.id]) return;
      var cb = waiting[m.id];
      delete waiting[m.id];
      if (m.status === 200 && m.body) cb(null, m.body);
      else cb({ status: m.status || 0, message: (m.body && m.body.message) || '動画ファイルを受け付けられませんでした' }, m.body || null);
    });
  }

  /* 配色(F3-B の配色 A〜D の切り替え・明るい / 暗い)を exe へ: 窓のタイトルの帯と閉じるときの確認の窓の色を画面に合わせる。
     ui-kit の変数(--header-bg・--ink・--panel・--line-2・--accent・--accent-ink)を色に直して送る。変数の名前を変えずに
     値だけ切り替える形なら、画面のほかの所は何もしなくてよい(<html> と <body> の属性・暗い表示の切り替えを見て送り直す) */
  var lastTheme = '';
  function rgb(varName) {
    var probe = document.createElement('i');
    probe.style.cssText = 'position:absolute;width:0;height:0;visibility:hidden;color:var(' + varName + ')';
    (document.body || document.documentElement).appendChild(probe);
    var m = /rgba?\((\d+),\s*(\d+),\s*(\d+)/.exec(getComputedStyle(probe).color || '');
    probe.remove();
    return m ? [+m[1], +m[2], +m[3]] : null;
  }
  function sendTheme() {
    if (!wv) return;
    var t = { type: 'theme', caption: rgb('--header-bg'), text: rgb('--ink'), panel: rgb('--panel'), line: rgb('--line-2'),
              accent: rgb('--accent'), accentInk: rgb('--accent-ink') };
    if (!t.caption || !t.text) return;
    var key = JSON.stringify(t);
    if (key === lastTheme) return;
    lastTheme = key;
    wv.postMessage(t);
  }
  var themeTimer = 0;
  function themeSoon() { clearTimeout(themeTimer); themeTimer = setTimeout(sendTheme, 50); }
  if (wv) {
    document.addEventListener('DOMContentLoaded', function () {
      sendTheme();
      var mo = new MutationObserver(themeSoon);
      mo.observe(document.documentElement, { attributes: true, attributeFilter: ['class', 'style', 'data-theme', 'data-scheme', 'data-palette'] });
      if (document.body) mo.observe(document.body, { attributes: true, attributeFilter: ['class', 'style', 'data-theme', 'data-scheme', 'data-palette'] });
      if (window.matchMedia) {
        var mq = window.matchMedia('(prefers-color-scheme: dark)');
        if (mq.addEventListener) mq.addEventListener('change', themeSoon);
      }
    });
  }

  window.FriendHost = {
    /* 配色を変えたあとに呼ぶと、すぐ exe の窓の色も合わせる(属性を変える形なら呼ばなくても送られる) */
    themeChanged: themeSoon,

    /* exe の窓の中か */
    isApp: !!wv,

    /* [すべて止めて終了]: exe が作業中・預かりを見て確認する([裏で続ける] / [止めて閉じる])。窓の外は確認なしで止める */
    quit: function () {
      if (wv) { wv.postMessage({ type: 'quit' }); return Promise.resolve(true); }
      return UIKit.http('api/shutdown', { body: {} }).then(function () { return true; });
    },

    /* ⚙ の [YouTube にログイン]: exe がログインの小窓を開き(friend-apps/launcher/src/YtLogin.cs)、閉じたら cb(ok, message)。
       窓の外では開けない(cb(false, 理由))。cookie は exe と Python の間だけ(画面には来ない) */
    youtubeLogin: function (cb) {
      if (!wv) { cb(false, 'アプリの窓の中でだけログインできます'); return; }
      loginCb = cb;
      wv.postMessage({ type: 'ytlogin' });
    },

    /* 落とした動画ファイル(DataTransfer.files)を送る係へ。exe が本物のパスを読んで POST /api/friend/files {paths} を送り、答えを cb(err, json) へ。
       画面からパスは送らない(パスを打たせない決まり)。窓の外ではパスが読めないので断る */
    sendFiles: function (files, cb) {
      if (!wv || !wv.postMessageWithAdditionalObjects) {
        cb({ status: 0, message: 'この窓では動画ファイルを落とせません。[ファイルを選ぶ] から選んでください' }, null);
        return;
      }
      var id = ++seq;
      waiting[id] = cb;
      wv.postMessageWithAdditionalObjects({ type: 'files', id: id }, files);
    }
  };
})();
