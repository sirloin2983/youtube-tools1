/* 初回の準備だけの画面(F3-5。notes:plan/f1-friend-requirements.md の C-5-1・C-1-2)。
   GET api/friend/setup を 1 秒おきに見て、棒 1 本と「あと約 n 分」を出す。済んだら /friend/ へ移る。
   前のアプリの片付けは 1 回だけ聞く([片付ける] [あとで])。部品の名前と詳しい文は「詳しく」の中だけ。 */
(function () {
  'use strict';
  var $ = function (id) { return document.getElementById(id); };
  var timer = 0, leaving = false, detailText = '', shownItems = null;
  var TITLES = { copying: '前のアプリの部品を写しています', fetching: '準備しています', placing: '部品を置いています', checking: '部品を確かめています',
                 cuda: '文字起こしの部品を取り直しています', done: '準備ができました', failed: '準備が止まりました', 'need-space': '空きが足りません' };

  function api(path, body) { return UIKit.http('api/friend/' + path, body === undefined ? {} : { body: body }); }

  function sizeText(n) {
    if (n == null) return '';
    return n >= 1e9 ? (n / 1e9).toFixed(1) + 'GB' : Math.max(1, Math.round(n / 1e6)) + 'MB';
  }

  function leftText(sec) {
    if (sec == null || !isFinite(sec)) return '残り時間を見積もっています';
    if (sec < 60) return 'あと 1 分ほど';
    return 'あと約 ' + Math.ceil(sec / 60) + ' 分';
  }

  function li(item) {
    var e = document.createElement('li');
    e.className = 'fs-item fs-' + (item.state || 'wait');
    var mark = { done: '済み', ok: '済み', fail: 'だめ', failed: 'だめ', running: '今', wait: '' }[item.state] || '';
    var m = document.createElement('span');
    m.className = 'fs-mark';
    m.textContent = mark;
    var l = document.createElement('span');
    l.textContent = item.label + (item.text ? ' — ' + item.text : '');
    e.appendChild(m);
    e.appendChild(l);
    return e;
  }

  function show(s, done) {
    s = s || {};
    var st = s.state || 'fetching';
    $('fsTitle').textContent = TITLES[st] || '準備しています';
    var failed = st === 'failed' || st === 'need-space';
    $('fsLead').textContent = s.message || (st === 'done' ? '送る画面へ移ります。' : '文字起こしなどに使う部品をそろえています(約 11GB)。');
    $('fsLead').hidden = failed;
    var pct = Math.max(0, Math.min(100, Math.round(+s.percent || (st === 'done' ? 100 : 0))));
    $('fsBar').firstElementChild.style.width = pct + '%';
    $('fsBar').setAttribute('aria-valuenow', String(pct));
    $('fsBar').hidden = failed;
    $('fsLeft').textContent = st === 'done' ? '' : [pct + '%', leftText(s.remainSec),
      s.totalBytes ? sizeText(s.doneBytes) + ' / ' + sizeText(s.totalBytes) : ''].filter(Boolean).join('・');
    $('fsLeft').hidden = failed || st === 'done';
    $('fsFail').hidden = !failed;
    var failText = failed ? (s.error && st === 'need-space' ? s.error : (s.message || 'ネットを確かめて [もう一度] を押してください(取れた分は残り、続きから取ります)')) : '';
    $('fsFailText').textContent = failText;
    $('btnRetry').hidden = st === 'need-space' && !s.canRetry;
    var old = s.oldApp || {};
    $('fsOld').hidden = !old.ask;
    $('fsOldText').textContent = old.ask ? '前のアプリを片付けます(約 ' + sizeText(old.bytes) + ' 空きます)。部品はこのアプリへ写して同じだと確かめてあります。' : '';
    var items = s.detail || [];
    var itemsKey = JSON.stringify(items);
    if (itemsKey !== shownItems) {   /* 1 秒ごとの問い合わせで変わった時だけ一覧を作り直す */
      shownItems = itemsKey;
      $('fsItems').textContent = '';
      items.forEach(function (it) { $('fsItems').appendChild(li(it)); });
    }
    $('fsErr').hidden = !s.error || s.error === failText;
    $('fsErr').textContent = s.error || '';
    detailText = items.map(function (it) { return it.label + ': ' + (it.state || '') + (it.text ? ' ' + it.text : ''); }).concat(s.error ? [s.error] : []).join('\n');
    $('btnCopy').hidden = !failed;
    if (failed && !$('fsMore').open && s.error) $('fsMore').open = true;
    if (done && !old.ask) go();
  }

  function go() {
    if (leaving) return;
    leaving = true;
    clearTimeout(timer);
    location.replace('./');
  }

  function poll() {
    clearTimeout(timer);
    api('setup').then(function (j) {
      show(j.setup, j.done);
    }, function () {
      $('fsLeft').textContent = '少し待っています…';
    }).then(function () { if (!leaving) timer = setTimeout(poll, 1000); });
  }

  function act(what, btn) {
    if (btn) btn.disabled = true;
    return api('setup/' + what, {}).then(function (j) { show(j.setup, j.done); }, function (e) {
      UIKit.toast((e && e.message) || 'できませんでした', { ms: 4000 });
    }).then(function () { if (btn) btn.disabled = false; });
  }

  document.addEventListener('DOMContentLoaded', function () {
    $('btnRetry').addEventListener('click', function () { act('start', $('btnRetry')); });
    $('btnCleanOld').addEventListener('click', function () { act('clean-old', $('btnCleanOld')); });
    $('btnSkipOld').addEventListener('click', function () { act('skip-old', $('btnSkipOld')); });
    $('btnQuit').addEventListener('click', function () { FriendHost.quit(); });
    $('btnCopy').addEventListener('click', function () {
      if (navigator.clipboard) navigator.clipboard.writeText(detailText).then(function () { UIKit.toast('コピーしました', { ms: 2000 }); });
    });
    poll();
  });
})();
