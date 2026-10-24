/* 操作の記録と画面の要約を玄関へ送る(形の正は notes:plan/友人の不具合の自動対応-1025.md。玄関は friendapp/report.py・oplog.py)。
   画面には何も出さない・送れなくても画面は止めない(捨てる)。まとめて FLUSH ミリ秒ごとに POST api/friend/ops {ops, screen?}。
   書く物: nav(画面の名前の移り変わり)・click(ボタンの id か data 属性。画面の文は書かない)・setting(入力の変更。選ぶ物の値だけ・文の欄は長さ len だけ・
   鍵やログインの欄は値なし)・error(赤い知らせの文・押したあと 10 秒返事が無い口)。依頼の送信と取り消しは玄関が書く。
   画面の要約(画面の名前・出ている文を切った物・小窓・押せないボタンと理由)は変わったときだけ添える(状態の書き出しの screen) */
(function () {
  'use strict';
  var FLUSH = 3000, MAX_BUF = 200, BATCH = 100, NO_REPLY = 10000, CLICK_LINK = 1500;
  var TEXTS = 80, TEXT = 120;
  var SAFE = /^[0-9A-Za-z_.:\-]{1,40}$/;
  var SECRET = /key|token|pass|cookie|secret|login|logout|auth/i;
  var SKIP_API = /pick-file|pick-folder|api\/friend\/ops|client-log/;
  var buf = [], lastName = '', lastScreen = '', lastClick = null, before = new WeakMap(), timer = 0;

  function now() { return Date.now(); }
  function push(kind, target, detail) {
    if (!target) return;
    buf.push({ at: now(), kind: kind, target: String(target).slice(0, 100), detail: detail || {} });
    if (buf.length > MAX_BUF) buf.splice(0, buf.length - MAX_BUF);
  }
  /* ボタンの名前 = #id か [data-x=v](値が記号の形のときだけ)か、id のある親 + 要素の種類と最初の class */
  function targetOf(el) {
    if (!el || !el.tagName) return '';
    if (el.id) return '#' + el.id;
    for (var i = 0; i < el.attributes.length; i++) {
      var a = el.attributes[i];
      if (a.name.indexOf('data-') === 0 && SAFE.test(a.value)) return '[' + a.name + '=' + a.value + ']';
    }
    var p = el.parentElement, tag = el.tagName.toLowerCase(), cls = (el.classList && el.classList[0]) || '';
    while (p && !p.id) p = p.parentElement;
    return (p ? '#' + p.id + '>' : '') + tag + (cls ? '.' + cls : '');
  }
  function visible(el) { return !!el && !el.hidden && !(el.closest && el.closest('[hidden]')) && el.getClientRects().length > 0; }
  function screenName() {
    if (document.querySelector('.fs-brand') && !document.getElementById('viewSend')) return 'setup';
    var v = (location.hash || '').slice(1) === 'receive' ? 'receive' : 'send';
    var d = document.getElementById('settingsDrawer');
    if (d && !d.hidden) v += '/settings';
    var dlg = Array.prototype.filter.call(document.querySelectorAll('dialog[open],[role="dialog"],[role="alertdialog"]'), visible)[0];
    if (dlg) v += '/dialog' + (dlg.id ? ':' + dlg.id : '');
    return v;
  }
  function screen() {
    var main = document.querySelector('.fr-main') || document.body, seen = {}, texts = [];
    String(main.innerText || '').split('\n').forEach(function (t) {
      t = t.trim();
      if (t && !seen[t] && texts.length < TEXTS) { seen[t] = 1; texts.push(t.slice(0, TEXT)); }
    });
    var dialogs = [];
    Array.prototype.forEach.call(document.querySelectorAll('dialog[open],[role="dialog"],[role="alertdialog"],.ui-toast-msg'), function (d) {
      if (visible(d) && dialogs.length < 10) dialogs.push(String(d.innerText || '').trim().slice(0, 200));
    });
    var disabled = [];
    Array.prototype.forEach.call(document.querySelectorAll('button[disabled],button[aria-disabled="true"]'), function (b) {
      if (visible(b) && disabled.length < 40) disabled.push({ id: targetOf(b), why: String(b.title || b.getAttribute('aria-description') || '').slice(0, TEXT) });
    });
    return { name: screenName(), texts: texts, dialogs: dialogs, disabled: disabled };
  }
  function checkNav() {
    var n = screenName();
    if (n !== lastName) { push('nav', n, lastName ? { from: lastName } : {}); lastName = n; }
  }
  function flush(keepalive) {
    clearTimeout(timer);
    timer = setTimeout(function () { flush(false); }, FLUSH);
    if (!send) return;
    checkNav();
    var body = {}, sc;
    try { sc = screen(); } catch (e) { sc = null; }
    var key = sc ? JSON.stringify(sc) : '';
    if (sc && key !== lastScreen) { body.screen = sc; lastScreen = key; }
    if (!buf.length && !body.screen) return;
    body.ops = buf.splice(0, BATCH);
    send.call(UIKit, 'api/friend/ops', { body: body, keepalive: !!keepalive, timeout: 8000 }).catch(function () { /* 送れなければ捨てる */ });
  }

  /* 押した物 */
  document.addEventListener('click', function (e) {
    var el = e.target && e.target.closest ? e.target.closest('button,a,[role="button"],[role="tab"],summary,input[type="checkbox"],input[type="radio"]') : null;
    if (!el) return;
    var t = targetOf(el);
    lastClick = { target: t, at: now() };
    push('click', t, { view: screenName() });
    setTimeout(checkNav, 300);
  }, true);
  /* 入力の変更: 前の値は入ったときに覚える。文の欄は長さだけ・鍵の欄は値なし */
  function valueOf(el) {
    var type = (el.type || '').toLowerCase();
    if (type === 'checkbox') return { v: !!el.checked };
    if (type === 'radio') return { v: SAFE.test(el.value) ? el.value : null };
    if (el.tagName === 'SELECT') return { v: SAFE.test(el.value) ? el.value : null };
    if (type === 'range' || type === 'number') { var n = Number(el.value); return { v: isFinite(n) ? n : null }; }
    return { len: String(el.value || '').length };
  }
  document.addEventListener('focusin', function (e) {
    var el = e.target;
    if (el && /^(INPUT|SELECT|TEXTAREA)$/.test(el.tagName)) before.set(el, valueOf(el));
  }, true);
  document.addEventListener('change', function (e) {
    var el = e.target;
    if (!el || !/^(INPUT|SELECT|TEXTAREA)$/.test(el.tagName)) return;
    var t = targetOf(el), cur = valueOf(el), prev = before.get(el) || {}, d = { view: screenName() };
    if (SECRET.test(t) || (el.type || '').toLowerCase() === 'password') d.secret = true;
    else if ('len' in cur) d.len = cur.len;
    else { d.before = 'v' in prev ? prev.v : null; d.after = cur.v; }
    before.set(el, cur);
    push('setting', t, d);
  }, true);
  window.addEventListener('hashchange', function () { setTimeout(checkNav, 0); });
  window.addEventListener('pagehide', function () { flush(true); });

  /* 赤い知らせ・押したあと返事の無い口(UIKit を包む。画面の動きは変えない) */
  var send = null;
  function wrap() {
    if (!window.UIKit || send) return;
    send = UIKit.http;
    UIKit.http = function (url, opt) {
      var p = send.apply(UIKit, arguments);
      var post = opt && opt.body !== undefined;
      if (post && lastClick && now() - lastClick.at <= CLICK_LINK && !SKIP_API.test(String(url))) {
        var who = lastClick.target, api = String(url).split('?')[0].replace(/^.*api\//, 'api/').slice(0, 80), done = false;
        var tm = setTimeout(function () { if (!done) push('error', who, { noResponseSec: NO_REPLY / 1000, api: api }); }, NO_REPLY);
        p.then(function () { done = true; clearTimeout(tm); }, function () { done = true; clearTimeout(tm); });
      }
      return p;
    };
    var toast = UIKit.toast;
    if (typeof toast === 'function') {
      UIKit.toast = function (msg, opt) {
        if (opt && opt.kind === 'err') push('error', screenName(), { message: String(msg || '').slice(0, 200) });
        return toast.apply(UIKit, arguments);
      };
    }
  }
  wrap();
  document.addEventListener('DOMContentLoaded', function () { wrap(); checkNav(); timer = setTimeout(function () { flush(false); }, FLUSH); });
})();
