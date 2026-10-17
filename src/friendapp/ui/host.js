/* 窓と画面の境目(F3-1。notes:plan/f1-friend-requirements.md の C-1・説明は friend-apps/launcher/README.txt)。
   FriendApp.exe(WebView2)の窓の中なら window.chrome.webview で exe と話す。窓の外(WebView2 の無い PC の Edge の窓・開発の PC)は代わりの動き。
   合言葉は exe が要求ごとに足すので、ここでも画面のほかの所でも扱わない(UIKit.http で呼ぶだけ)。 */
(function () {
  'use strict';
  var wv = window.chrome && window.chrome.webview ? window.chrome.webview : null;
  var seq = 0, waiting = {};

  if (wv) {
    wv.addEventListener('message', function (ev) {
      var m = ev.data;
      if (!m || m.type !== 'files' || !waiting[m.id]) return;
      var cb = waiting[m.id];
      delete waiting[m.id];
      if (m.status === 200 && m.body) cb(null, m.body);
      else cb({ status: m.status || 0, message: (m.body && m.body.message) || '動画ファイルを受け付けられませんでした' }, m.body || null);
    });
  }

  window.FriendHost = {
    /* exe の窓の中か */
    isApp: !!wv,

    /* [すべて止めて終了]: exe が作業中・預かりを見て確認する([裏で続ける] / [止めて閉じる])。窓の外は確認なしで止める */
    quit: function () {
      if (wv) { wv.postMessage({ type: 'quit' }); return Promise.resolve(true); }
      return UIKit.http('api/shutdown', { body: {} }).then(function () { return true; });
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
