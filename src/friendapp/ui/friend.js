/* 友人のアプリの共通の部分(F3)。口は friendapp/server.py の説明。外から来た文字(題・名前・理由)は textContent でだけ入れる。
   ここ = [送る] / [受け取る] の切り替え・3 秒おきの問い合わせ(送った物の行・受け取る物)を各部品へ配る(FR.on)・上の帯・止めて終了。
   ⚙ は settings.js(F3-5)・窓との境目は host.js(F3-1。FriendHost)・初回の準備は setup.html(済むまで玄関がそちらへ送る)。
   部品: send-list.js(配信の一覧)・send-form.js(送る欄)・sent.js(送った物)・receive.js(受け取る) */
(function () {
  'use strict';
  var $ = function (id) { return document.getElementById(id); };
  var POLL = 3000, POLL_AWAY = 10000;
  var subs = [], timer = 0, listTimer = 0, view = 'send', undecided = 0;
  var st = { partsWhy: '', hasKey: true, inbox: null, receive: null, form: null };

  function el(tag, attrs, kids) {
    var e = document.createElement(tag);
    Object.keys(attrs || {}).forEach(function (k) {
      if (k === 'text') e.textContent = attrs[k];
      else if (k === 'cls') e.className = attrs[k];
      else if (k === 'on') Object.keys(attrs.on).forEach(function (ev) { e.addEventListener(ev, attrs.on[ev]); });
      else if (attrs[k] === true) e.setAttribute(k, '');
      else if (attrs[k] !== false && attrs[k] != null) e.setAttribute(k, attrs[k]);
    });
    (kids || []).forEach(function (c) { if (c != null) e.appendChild(typeof c === 'string' ? document.createTextNode(c) : c); });
    return e;
  }
  function api(path, body) { return UIKit.http('api/friend/' + path, body === undefined ? {} : { body: body }); }
  function sizeText(n) { return n == null ? '不明' : n >= 1e9 ? (n / 1e9).toFixed(1) + ' GB' : Math.max(1, Math.round(n / 1e6)) + ' MB'; }
  function fail(what, e) { UIKit.toast(what + ': ' + e.message, { kind: 'err', detail: e.detail, ms: 6000 }); }
  function dur(sec) {
    if (sec == null) return '';
    sec = Math.round(sec);
    var h = Math.floor(sec / 3600), m = Math.floor(sec % 3600 / 60), s = sec % 60, p = function (n) { return (n < 10 ? '0' : '') + n; };
    return (h ? h + ':' + p(m) : String(m)) + ':' + p(s);
  }
  function token() { var m = document.querySelector('meta[name="ytt-token"]'); return m ? m.content : ''; }
  /* 文字を打つ場所か(Ctrl+V・Esc・Space の扱いを変える) */
  function typing(t) {
    t = t || document.activeElement;
    if (!t || !t.tagName) return false;
    return /^(INPUT|TEXTAREA|SELECT)$/.test(t.tagName) || t.isContentEditable || t.getAttribute('role') === 'spinbutton';
  }

  /* ---------------------------------------------------------------- [送る] / [受け取る](C-2-1) */
  function show(v) {
    view = v === 'receive' ? 'receive' : 'send';
    $('viewSend').hidden = view !== 'send';
    $('viewReceive').hidden = view !== 'receive';
    $('tabSend').setAttribute('aria-pressed', view === 'send' ? 'true' : 'false');
    $('tabReceive').setAttribute('aria-pressed', view === 'receive' ? 'true' : 'false');
    if (location.hash !== '#' + view) history.replaceState(null, '', '#' + view);
    emit('view', view);
    if (view === 'send') pollList();
  }
  function pollList() {   /* 一覧は送る画面を出している間だけ問い合わせる(玄関の中の写しを読むだけ = 軽い) */
    clearTimeout(listTimer);
    if (view !== 'send' || !window.FRList) return;
    FRList.load().catch(function () { /* 玄関とつながらない = 上の帯が知らせる */ }).then(function () {
      listTimer = setTimeout(pollList, UIKit.life.isAway() ? POLL_AWAY : POLL);
    });
  }
  function setCount(n) {   /* ●n = まだ決めていない本数(C-3-9)。窓のタイトルにも(窓はタイトルを写す = F3-A) */
    undecided = n;
    $('tabN').hidden = !n;
    $('tabN').textContent = n ? String(n) : '';
    $('tabReceive').setAttribute('aria-label', n ? '受け取る(まだ決めていない ' + n + ' 本)' : '受け取る');
    document.title = n ? '切り抜き(' + n + ')' : '切り抜き';
  }

  /* ---------------------------------------------------------------- 配る */
  function on(fn) { subs.push(fn); }
  function emit(what, data) { subs.forEach(function (fn) { try { fn(what, data); } catch (e) { if (window.console) console.error(e); } }); }

  function banner(j) {
    var sy = j.sync || {};
    st.hasKey = sy.key !== false;
    st.partsWhy = j.partsWhy || '';   /* 部品を取っている間・足りない間は [送る](この PC)を止める(C-5-1) */
    $('noKey').hidden = !sy.message;
    $('noKey').textContent = sy.message || '';
    $('updated').hidden = !sy.updated || st.updatedSeen === sy.updated;
    $('updatedText').textContent = sy.updated ? '新しい版 ' + sy.updated + ' を入れました(次に開いたときから)' : '';
    var p = j.prep || {};
    $('prep').hidden = p.state === 'ready';
    $('prep').textContent = p.message || '';
    $('prep').classList.toggle('err', p.state === 'error');
    var old = (j.rollback ? j.rollback + '。' : '') + (j.notice ? '前の部品 ' + j.notice.freedGB + ' GB を片付けました' : '');
    var cl = st.receive && st.receive.notice;
    $('cleaned').hidden = !(old || cl);
    $('cleanedText').textContent = old || (cl ? '3 日たった ' + cl.n + ' 本を片付けました' : '');
    $('cleaned').setAttribute('data-what', old ? 'old' : 'cleaned');
  }
  function refresh() {
    clearTimeout(timer);
    return Promise.all([api('inbox'), api('receive')]).then(function (got) {
      var j = got[0];
      $('errbar').hidden = true;
      st.inbox = j; st.receive = got[1]; st.form = j.form;
      $('btnSaved').title = '受け取った物の保存先を開きます: ' + (j.saveDir || '');
      banner(j);
      setCount(got[1].undecided || 0);
      emit('data', { inbox: j, receive: got[1] });
    }, function (e) {
      $('errbar').hidden = false;
      $('errbar').textContent = 'アプリとつながりません。アプリを開き直してください';
      if (window.console) console.warn(e.message);
    }).then(function () { timer = setTimeout(refresh, UIKit.life.isAway() ? POLL_AWAY : POLL); });
  }

  function drawerOpen() { var d = $('settingsDrawer'); return !!d && !d.hidden; }   /* ⚙ が開いている(Esc とキーは ⚙ へ) */
  window.FR = { $: $, el: el, api: api, fail: fail, sizeText: sizeText, dur: dur, token: token, typing: typing, on: on, refresh: refresh, show: show, drawerOpen: drawerOpen,
    get state() { return st; }, get view() { return view; } };
  window.FriendApp = { show: show, count: function () { return undecided; } };   /* 窓(F3-A)から呼ぶ口(仮 = decisions 3-83 (f3b-e)) */

  document.addEventListener('DOMContentLoaded', function () {
    var v = document.querySelector('meta[name="ytt-version"]');
    $('ver').textContent = v ? 'v' + v.content : '';
    $('tabSend').addEventListener('click', function () { show('send'); });
    $('tabReceive').addEventListener('click', function () { show('receive'); });
    window.addEventListener('hashchange', function () { show(location.hash.slice(1)); });
    $('btnSaved').addEventListener('click', function () { api('open', { what: 'saved' }).catch(function (e) { fail('開けませんでした', e); }); });
    $('btnQuit').addEventListener('click', function () {
      if (window.FriendHost && FriendHost.isApp) { FriendHost.quit(); return; }   /* exe の窓 = exe が作業中・預かりを見て確認する(F3-1) */
      api('../shutdown', {}).then(function () {
        clearTimeout(timer); clearTimeout(listTimer);
        document.querySelector('.fr-main').textContent = '';
        document.querySelector('.fr-main').appendChild(el('p', { cls: 'fr-bye', text: '止めて終了しました。この窓は閉じてかまいません(次に開くと、作っていた物の続きから始めます)' }));
      }, function (e) { fail('終了できませんでした', e); });
    });
    $('cleanedOk').addEventListener('click', function () {
      var what = $('cleaned').getAttribute('data-what');
      api('notice-seen', what === 'cleaned' ? { what: 'cleaned' } : {}).then(function () { $('cleaned').hidden = true; if (st.receive) st.receive.notice = null; });
    });
    $('updatedOk').addEventListener('click', function () { st.updatedSeen = ((st.inbox || {}).sync || {}).updated; $('updated').hidden = true; });
    UIKit.life.onReturn(function () { refresh(); pollList(); });
    show(location.hash.slice(1));
    refresh();
  });
})();
