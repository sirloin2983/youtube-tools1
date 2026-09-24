/* ui-kit v1 — テーマ切り替えと、ツール間のリンク。<head> の中で CSS より先に同期読み込みする(画面のちらつき防止)。
   正本はリポジトリ直下の ui-kit/ui-kit.js。各ツールへは tools/sync_ui_kit.py で写す(手で直接直さない)。
   window.UIKit.theme  : get() 保存した選択('system'|'light'|'dark') / resolved() 実際の見た目 / set(p) / toggle() / onChange(fn)
   window.UIKit.tools  : 既定のポートとツール名。render(el, {current, ports}) で「他のツール」メニューを作る */
(function () {
  'use strict';
  var KEY = 'ytt:theme';
  var root = document.documentElement;
  var mq = window.matchMedia ? window.matchMedia('(prefers-color-scheme: dark)') : null;
  var subs = [];

  function pref() {
    try { var v = localStorage.getItem(KEY); return v === 'light' || v === 'dark' ? v : 'system'; } catch (e) { return 'system'; }
  }
  function resolve(p) { return p === 'system' ? (mq && mq.matches ? 'dark' : 'light') : p; }
  function syncButtons() {
    var t = root.getAttribute('data-theme') === 'dark' ? 'dark' : 'light', p = pref();
    var btns = document.querySelectorAll('[data-theme-toggle]');
    for (var i = 0; i < btns.length; i++) {
      btns[i].setAttribute('aria-pressed', String(t === 'dark'));
      btns[i].setAttribute('aria-label', t === 'dark' ? 'ライト表示に切り替え' : 'ダーク表示に切り替え');
      btns[i].title = (t === 'dark' ? 'ライト表示に切り替え' : 'ダーク表示に切り替え') + '(いま: ' + (p === 'system' ? 'OSの設定に合わせる' : t === 'dark' ? 'ダーク' : 'ライト') + ')';
    }
  }
  function paint(p) {
    var t = resolve(p);
    root.setAttribute('data-theme', t);
    root.setAttribute('data-theme-pref', p);
    syncButtons();
    for (var j = 0; j < subs.length; j++) { try { subs[j](t, p); } catch (e) { /* 購読側の失敗は無視 */ } }
  }
  function set(p) {
    if (p !== 'light' && p !== 'dark') p = 'system';
    try { if (p === 'system') localStorage.removeItem(KEY); else localStorage.setItem(KEY, p); } catch (e) { /* 保存できなくても見た目は変える */ }
    paint(p);
  }
  var theme = {
    get: pref,
    resolved: function () { return resolve(pref()); },
    set: set,
    toggle: function () { set(resolve(pref()) === 'dark' ? 'light' : 'dark'); },
    onChange: function (fn) { if (typeof fn === 'function') subs.push(fn); }
  };
  paint(pref());
  if (mq) {
    var onSys = function () { if (pref() === 'system') paint('system'); };
    if (mq.addEventListener) mq.addEventListener('change', onSys); else if (mq.addListener) mq.addListener(onSys);
  }
  /* 別のタブで切り替えたら、このタブも合わせる */
  window.addEventListener('storage', function (e) { if (e.key === KEY) paint(pref()); });
  document.addEventListener('click', function (e) {
    var b = e.target && e.target.closest ? e.target.closest('[data-theme-toggle]') : null;
    if (b) { e.preventDefault(); theme.toggle(); }
  });
  /* ボタンは <head> の実行時にはまだ無いので、読み込み後に表示だけ合わせる(data-theme は変えない: 画面側が独自に決めた値を消さないため) */
  document.addEventListener('DOMContentLoaded', syncButtons);
  /* 「他のツール」などの <details class="ui-menu"> を、外側のクリックと Esc で閉じる */
  document.addEventListener('click', function (e) {
    var open = document.querySelectorAll('details.ui-menu[open]');
    for (var i = 0; i < open.length; i++) if (!open[i].contains(e.target)) open[i].removeAttribute('open');
  });
  document.addEventListener('keydown', function (e) {
    if (e.key !== 'Escape') return;
    var open = document.querySelectorAll('details.ui-menu[open]');
    for (var i = 0; i < open.length; i++) open[i].removeAttribute('open');
  });

  /* ---- ツール間のリンク ---- */
  var TOOLS = [
    { id: 'studio', name: '切り抜きスタジオ', sub: '配信を探す・切り抜く区間を選ぶ', port: 8800, mark: 'studio' },
    { id: 'transcribe', name: '文字起こしツール', sub: '字幕を作る・校正する', port: 8775, mark: 'transcribe' },
    { id: 'cut2resolve', name: 'cut2resolve', sub: 'カットと字幕を Resolve へ渡す', port: 8810, mark: 'cut2resolve' }
  ];
  function esc(s) { return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) { return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]; }); }
  var tools = {
    list: TOOLS,
    /* ports: {studio: 8801, ...}(サーバーが知っている実際のポート。無ければ既定) */
    url: function (id, ports, path) {
      var t = null;
      for (var i = 0; i < TOOLS.length; i++) if (TOOLS[i].id === id) t = TOOLS[i];
      if (!t) return '';
      var port = (ports && +ports[id]) || t.port;
      return 'http://localhost:' + port + (path || '/');
    },
    render: function (el, opt) {
      if (!el) return;
      opt = opt || {};
      var html = '';
      for (var i = 0; i < TOOLS.length; i++) {
        var t = TOOLS[i], cur = t.id === opt.current;
        html += '<a href="' + esc(cur ? '/' : tools.url(t.id, opt.ports)) + '"' + (cur ? ' aria-current="page"' : ' target="_blank" rel="noopener"') + '>' +
          '<span class="ui-brand-mark" data-tool="' + t.mark + '" aria-hidden="true"></span><span><b>' + esc(t.name) + '</b><small>' + esc(t.sub) + (cur ? '(いま開いている画面)' : '') + '</small></span></a>';
      }
      el.innerHTML = html;
    }
  };
  theme.syncButtons = syncButtons;
  window.UIKit = { version: 1, theme: theme, tools: tools };
})();
