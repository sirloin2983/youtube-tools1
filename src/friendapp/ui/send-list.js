/* 送る画面の配信の一覧(F3-2。notes:plan/f1-friend-requirements.md の C-2-2〜C-2-5)。
   口は friendapp/server.py の GET api/friend/streams(friendapp/streams.py の view + 送った物の印)。
   描くだけ: カードを押したら FRList.onPick(item)。外から来た文字(題・名前)は textContent でだけ入れる。
   増えてもスクロールの位置を動かさない(一番上に見えているカードを描き直しの前後で同じ高さに置く)・選んだ配信は選んだまま */
(function () {
  'use strict';
  var $ = function (id) { return document.getElementById(id); };
  var STATE = { live: ['fr-badge-live', 'ライブ'], upcoming: ['fr-badge-plan', '予定'], justEnded: ['fr-badge-ended', '終わったばかり'],
    checking: ['fr-badge-check', '確かめ中'] };
  var SENT = { sent: '送った', queued: '順番待ち', waiting: 'アーカイブ待ち', reserved: '予約', making: '作っている', recording: '録画中', arrived: '届いた', failed: '失敗' };
  var my = { key: '', view: null, selected: '', onPick: null, items: {} };

  function el(tag, cls, text) {
    var e = document.createElement(tag);
    if (cls) e.className = cls;
    if (text != null) e.textContent = text;
    return e;
  }
  function pad(n) { return (n < 10 ? '0' : '') + n; }
  function hm(ms) { var d = new Date(ms); return d.getHours() + ':' + pad(d.getMinutes()); }
  function dayDiff(ms) {   /* 今日 = 0・明日 = 1・昨日 = -1(現地の日付で) */
    var a = new Date(ms), b = new Date();
    a.setHours(0, 0, 0, 0); b.setHours(0, 0, 0, 0);
    return Math.round((a - b) / 86400000);
  }
  function dur(sec) {
    if (sec == null) return '';
    sec = Math.round(sec);
    var h = Math.floor(sec / 3600), m = Math.floor(sec % 3600 / 60), s = sec % 60;
    return (h ? h + ':' + pad(m) : String(m)) + ':' + pad(s);
  }
  /* 時刻の文字: ライブ「12:00〜 配信中」/ 予定「18:00 から」(明日なら「明日 18:00 から」)/ ほか「21:00〜」(一昨日より前は日付も) */
  function when(it) {
    if (!it.startAt) return '';
    var d = dayDiff(it.startAt), t = hm(it.startAt);
    if (it.state === 'live') return t + '〜 配信中';
    if (it.state === 'upcoming') return (d === 1 ? '明日 ' : d > 1 ? (new Date(it.startAt).getMonth() + 1) + '/' + new Date(it.startAt).getDate() + ' ' : '') + t + ' から';
    if (d < -1) return (new Date(it.startAt).getMonth() + 1) + '/' + new Date(it.startAt).getDate() + ' ' + t + '〜';
    return t + '〜';
  }
  function card(it) {
    var b = el('button', 'fr-card');
    b.type = 'button';
    b.setAttribute('data-vid', it.videoId);
    b.setAttribute('aria-pressed', it.videoId === my.selected ? 'true' : 'false');
    var th = el('span', 'fr-thumb');
    var img = el('img');
    img.alt = ''; img.loading = 'lazy'; img.decoding = 'async';
    if (it.thumb) img.src = it.thumb;
    th.appendChild(img);
    var st = STATE[it.state];
    if (st) th.appendChild(el('span', 'fr-badge ' + st[0], st[1]));
    if (it.sent && SENT[it.sent.state]) th.appendChild(el('span', 'fr-badge fr-badge-sent' + (it.sent.state === 'failed' ? ' bad' : ''), SENT[it.sent.state]));
    if ((it.state === 'ended' || it.state === 'justEnded') && it.duration) th.appendChild(el('span', 'fr-dur', dur(it.duration)));
    b.appendChild(th);
    var body = el('span', 'fr-card-body');
    body.appendChild(el('span', 'fr-card-title', it.title || '(題を確かめています)'));
    var who = el('span', 'fr-card-who');
    var dot = el('span', 'fr-dot');
    if (it.hex) dot.style.background = it.hex;
    dot.setAttribute('aria-hidden', 'true');
    who.appendChild(dot);
    who.appendChild(document.createTextNode(it.streamer || ''));
    body.appendChild(who);
    body.appendChild(el('span', 'fr-card-when' + (it.state === 'live' ? ' live' : ''), when(it)));
    b.appendChild(body);
    b.title = (it.title || '') + (it.streamer ? '\n' + it.streamer : '');
    b.addEventListener('click', function () { pick(it.videoId); });
    return b;
  }
  function pick(vid) {
    my.selected = vid;
    mark();
    if (my.onPick && my.items[vid]) my.onPick(my.items[vid]);
  }
  function mark() {
    Array.prototype.forEach.call($('streamsList').querySelectorAll('.fr-card'), function (c) {
      c.setAttribute('aria-pressed', c.getAttribute('data-vid') === my.selected ? 'true' : 'false');
    });
  }
  /* 一番上に見えているカード(と見出しの下からのずれ)= 描き直したあと同じ所に戻す */
  function anchor() {
    var box = $('streamsScroll'), top = box.getBoundingClientRect().top, cards = box.querySelectorAll('.fr-card');
    for (var i = 0; i < cards.length; i++) {
      var r = cards[i].getBoundingClientRect();
      if (r.bottom > top) return { vid: cards[i].getAttribute('data-vid'), off: r.top - top };
    }
    return null;
  }
  function restore(a) {
    if (!a) return;
    var box = $('streamsScroll'), c = box.querySelector('.fr-card[data-vid="' + a.vid + '"]');
    if (c) box.scrollTop += (c.getBoundingClientRect().top - box.getBoundingClientRect().top) - a.off;
  }
  function render(v) {
    var list = $('streamsList'), keep = $('streamsScroll').scrollTop > 0 ? anchor() : null;
    list.textContent = '';
    my.items = {};
    (v.sections || []).forEach(function (s) {
      var sec = el('section', 'fr-sec');
      sec.setAttribute('aria-label', s.label);
      var h = el('h3', 'fr-sec-h');
      h.appendChild(document.createTextNode(s.label));
      h.appendChild(el('span', 'fr-sec-n', s.count + ' 件'));
      sec.appendChild(h);
      var grid = el('div', 'fr-cards');
      s.items.forEach(function (it) { my.items[it.videoId] = it; grid.appendChild(card(it)); });
      sec.appendChild(grid);
      list.appendChild(sec);
    });
    restore(keep);
  }
  function bar(v) {
    var b = $('btnStreamsRefresh');
    /* 取りに行っている間も、前に取れた時刻を出したまま(C-2-5「14:05 に更新」)。初めての 1 回だけ「取っています…」 */
    b.textContent = v.updatedAt ? hm(v.updatedAt) + ' に更新' + (v.busy ? '(確かめています)' : '') : v.busy ? '取っています…' : '更新';
    b.disabled = !!v.busy;
    b.title = v.busy ? '新しい一覧を確かめています' : '押すと、新しい一覧を取りに行きます';
    var err = v.error && !v.first ? v.error.message : '';
    $('streamsErr').hidden = !err;
    $('streamsErrText').textContent = err;
    var none = !(v.sections || []).length;
    var empty = $('streamsEmpty');
    empty.hidden = !none;
    empty.textContent = '';
    if (!none) return;
    if (v.first && v.error) {
      empty.appendChild(el('p', '', v.error.message));
      var again = el('button', 'btn', 'もう一度');
      again.type = 'button';
      again.addEventListener('click', refresh);
      empty.appendChild(again);
    } else {
      empty.appendChild(el('p', '', v.busy || v.first ? '配信の一覧を取っています…' : '今日と昨日の配信はまだありません。'));
      empty.appendChild(el('p', 'hint', '見たい配信の URL を右の欄に貼っても送れます。'));
    }
  }
  function refresh() {
    $('btnStreamsRefresh').disabled = true;
    return UIKit.http('api/friend/streams/refresh', { body: {} }).then(function (j) {
      if (!j.ok && j.waitSec) UIKit.toast('YouTube に断られたので、' + Math.ceil(j.waitSec / 60) + ' 分ほど待ってから取りに行きます', { ms: 5000 });
      return load();
    }, function (e) { UIKit.toast('更新できませんでした: ' + e.message, { kind: 'err' }); $('btnStreamsRefresh').disabled = false; });
  }
  function load() {
    return UIKit.http('api/friend/streams').then(function (v) {
      my.view = v;
      bar(v);
      var key = JSON.stringify(v.sections || []);
      if (key !== my.key) { my.key = key; render(v); }
      return v;
    });
  }
  document.addEventListener('DOMContentLoaded', function () {
    $('btnStreamsRefresh').addEventListener('click', refresh);
    $('btnStreamsRetry').addEventListener('click', refresh);
  });
  window.FRList = {
    load: load,
    refresh: refresh,
    item: function (vid) { return my.items[vid] || null; },
    select: function (vid) { my.selected = vid || ''; mark(); var c = vid && $('streamsList').querySelector('.fr-card[data-vid="' + vid + '"]'); if (c && c.scrollIntoView) c.scrollIntoView({ block: 'nearest' }); },
    selected: function () { return my.selected; },
    set onPick(fn) { my.onPick = fn; },
    get onPick() { return my.onPick; }
  };
})();
