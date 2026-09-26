/* ui-kit v2 — テーマ切り替えと、ツール間のリンク。<head> の中で CSS より先に同期読み込みする(画面のちらつき防止)。
   正本はリポジトリ直下の ui-kit/ui-kit.js。各ツールへは tools/sync_ui_kit.py で写す(手で直接直さない)。
   window.UIKit.theme  : get() 保存した選択('system'|'light'|'dark') / resolved() 実際の見た目 / set(p) / toggle() / onChange(fn)
   window.UIKit.tools  : 既定のポートとツール名。render(el, {current, ports}) で「他のツール」メニューを作る。
                         setPaths(/api/siblings の paths) で、入口の統合サーバーに取り込まれたツールの場所(/studio/ など)を覚える
   window.UIKit.life   : onLeave(fn(reason)) / onReturn(fn(reason)) / isAway()。画面を離れた・戻ったの合図(段階7-2)。
                         離れた = タブの切り替え('hidden')・別の窓へ移った('blur')・閉じる直前('pagehide')。戻った = 'visible' | 'focus' | 'pageshow'
   window.UIKit.report : report(message, info) 画面のエラーを入口のログ(app\logs\client-errors.jsonl)へ送る(段階7-0)。
                         捕まえられなかったエラー(error・unhandledrejection)は自動で送る。入口の外(合言葉なし)では送らない
   window.UIKit.win    : isApp() 窓(Edge のアプリモード)で開いているか / open(url) 入口に頼んで開く(段階7-3)。
                         窓の中の「新しいタブで開く」リンクは自動で: このパソコンの画面 → 同じ形の窓、外のサイト → いつものブラウザ */
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
  var PATH_RE = /^\/(?:[a-z0-9][a-z0-9-]{0,31}\/)?$/;
  var tools = {
    list: TOOLS,
    /* 統合サーバーに取り込まれたツールの場所 {studio: '/studio/'}(/api/siblings の paths。無ければ各ツールのポートの直下) */
    paths: {},
    setPaths: function (p) {
      var out = {};
      if (p && typeof p === 'object') for (var k in p) if (Object.prototype.hasOwnProperty.call(p, k) && typeof p[k] === 'string' && PATH_RE.test(p[k])) out[k] = p[k];
      tools.paths = out;
    },
    base: function (id) { return tools.paths[id] || '/'; },
    /* ports: {studio: 8801, ...}(サーバーが知っている実際のポート。無ければ既定)。path は画面の中の場所('/?media=...' など) */
    url: function (id, ports, path) {
      var t = null;
      for (var i = 0; i < TOOLS.length; i++) if (TOOLS[i].id === id) t = TOOLS[i];
      if (!t) return '';
      var port = (ports && +ports[id]) || t.port;
      var rest = path || '/';
      if (rest.charAt(0) === '/') rest = rest.slice(1);
      return 'http://localhost:' + port + tools.base(id) + rest;
    },
    render: function (el, opt) {
      if (!el) return;
      opt = opt || {};
      var html = '';
      for (var i = 0; i < TOOLS.length; i++) {
        var t = TOOLS[i], cur = t.id === opt.current;
        html += '<a href="' + esc(cur ? tools.base(t.id) : tools.url(t.id, opt.ports)) + '"' + (cur ? ' aria-current="page"' : ' target="_blank" rel="noopener"') + '>' +
          '<span class="ui-brand-mark" data-tool="' + t.mark + '" aria-hidden="true"></span><span><b>' + esc(t.name) + '</b><small>' + esc(t.sub) + (cur ? '(いま開いている画面)' : '') + '</small></span></a>';
      }
      el.innerHTML = html;
    }
  };
  theme.syncButtons = syncButtons;

  /* ---- 入口の共通の API(api/ytt/…)---- 画面の場所からの相対パス(入口の画面 → /api/ytt/…、取り込んだツール → /studio/api/ytt/… など。
     どちらも入口が受け持つ)。合言葉はサーバーが </head> の直前に入れるので、このファイルの実行時ではなく送るときに読む */
  function token() { var m = document.querySelector('meta[name="ytt-token"]'); return m ? m.content : ''; }
  function yttPost(name, obj, keepalive) {
    var tk = token();
    if (!tk || !window.fetch) return Promise.reject(new Error('入口の外では使えません'));
    return fetch('api/ytt/' + name, { method: 'POST', cache: 'no-store', credentials: 'same-origin', keepalive: !!keepalive,
      headers: { 'Content-Type': 'application/json', 'X-YTT-Token': tk }, body: JSON.stringify(obj) })
      .then(function (r) { return r.json().catch(function () { return {}; }).then(function (j) { if (!r.ok) throw new Error(j.message || ('HTTP ' + r.status)); return j; }); });
  }

  /* ---- 画面のエラーを入口のログへ(段階7-0)---- 同じエラーは1回、1回の表示で20件まで(画面の不具合でログを埋めない。サーバー側にも上限) */
  var sentN = 0, seen = {};
  function clip(v, n) { v = v == null ? '' : String(v); return v.length > n ? v.slice(0, n) : v; }
  function report(message, info, kind) {
    try {
      info = info || {};
      message = clip(message, 500);
      if (!message || !token()) return false;
      var key = (kind || 'report') + '|' + message + '|' + (info.source || '') + '|' + (info.line || 0);
      if (seen[key] || sentN >= 20) return false;
      seen[key] = 1; sentN++;
      yttPost('client-log', { kind: kind || 'report', message: message, source: clip(info.source, 300), line: +info.line || 0, col: +info.col || 0,
        stack: clip(info.stack, 1500), page: clip(location.pathname, 200) }, true).catch(function () { /* 送れなくても画面は止めない */ });
      return true;
    } catch (e) { return false; }
  }
  window.addEventListener('error', function (e) {
    if (!e || !e.message) return;
    if (!e.filename && /^Script error\.?$/.test(e.message)) return;   // 別のサイトのスクリプト(YouTube のプレイヤー)の、中身の見えないエラー
    report(e.message, { source: e.filename, line: e.lineno, col: e.colno, stack: e.error && e.error.stack }, 'error');
  });
  window.addEventListener('unhandledrejection', function (e) {
    var r = e ? e.reason : null;
    report(r && r.message ? r.message : String(r), { stack: r && r.stack }, 'rejection');
  });

  /* ---- 画面を離れた・戻った(段階7-2)----
     タブの切り替え(visibilitychange)だけだと、窓を並べて使うときに「隣の窓をクリックした」を取りこぼす(画面は見えたまま)。
     別の窓へ移った(blur)・閉じる直前(pagehide)も「離れた」にする。ただし埋め込みの YouTube(iframe)をクリックしても窓の blur が来るので、
     少し待って、フォーカスがまだこの画面の中(document.hasFocus() か、フォーカスが iframe)なら離れたことにしない */
  var leaveFns = [], returnFns = [], away = false, awayBy = '', blurTimer = null;
  function fire(list, reason) {
    for (var i = 0; i < list.length; i++) { try { list[i](reason); } catch (e) { report(e && e.message ? e.message : String(e), { stack: e && e.stack }, 'error'); } }
  }
  function focusInside() {
    try { if (document.hasFocus()) return true; } catch (e) { /* 古いブラウザ */ }
    var a = document.activeElement;
    return !!(a && a.tagName === 'IFRAME');
  }
  function leave(reason) {
    /* 離れたのは1回だけ知らせる。ただし「隣の窓へ('blur')」のあとにタブを切り替えた・最小化した('hidden')ときは、もう一度知らせる
       ('blur' では再生の停止・重い処理をしない決まりなので、見えなくなった時点でそれをさせる)。閉じる直前('pagehide')はいつでも知らせる */
    if (away && !(reason === 'pagehide' || (reason === 'hidden' && awayBy === 'blur'))) return;
    away = true;
    awayBy = reason;
    fire(leaveFns, reason);
  }
  function back(reason) {
    if (!away) return;
    away = false;
    fire(returnFns, reason);
  }
  document.addEventListener('visibilitychange', function () { if (document.hidden) leave('hidden'); else back('visible'); });
  window.addEventListener('pagehide', function () { leave('pagehide'); });
  window.addEventListener('pageshow', function (e) { if (e && e.persisted) back('pageshow'); });
  window.addEventListener('blur', function () {
    clearTimeout(blurTimer);
    blurTimer = setTimeout(function () { if (!document.hidden && !focusInside()) leave('blur'); }, 150);
  });
  window.addEventListener('focus', function () { clearTimeout(blurTimer); if (!document.hidden) back('focus'); });
  var life = {
    onLeave: function (fn) { if (typeof fn === 'function') leaveFns.push(fn); },
    onReturn: function (fn) { if (typeof fn === 'function') returnFns.push(fn); },
    isAway: function () { return away; }
  };

  /* ---- 窓(Edge のアプリモード)で開いているときのリンク(段階7-3)----
     アプリモードの窓の中で「新しいタブで開く」と、タブのある普通の窓(専用のプロファイル)になってしまう。入口に頼んで開き直す:
     このパソコンの画面(localhost)→ 同じ形の窓、外のサイト(YouTube など)→ いつものブラウザ(ログインしている方)。
     アプリモードかどうかは display-mode(Edge のアプリの窓は standalone)で見る。ブラウザのタブで開いているときは何もしない */
  function isApp() { try { return !!(window.matchMedia && window.matchMedia('(display-mode: standalone)').matches); } catch (e) { return false; } }
  function isLocal(u) { return u.hostname === location.hostname || u.hostname === 'localhost' || u.hostname === '127.0.0.1'; }
  function openVia(href) {
    var u;
    try { u = new URL(href, location.href); } catch (e) { return Promise.reject(e); }
    return yttPost(isLocal(u) ? 'open-window' : 'open-external', { url: u.href });
  }
  function onLink(e) {
    if (e.defaultPrevented || !isApp() || !token()) return;
    var a = e.target && e.target.closest ? e.target.closest('a[href]') : null;
    if (!a || a.hasAttribute('download')) return;
    var mod = e.ctrlKey || e.shiftKey || e.metaKey || e.button === 1;
    if (a.target !== '_blank' && !mod) return;
    var u;
    try { u = new URL(a.href, location.href); } catch (x) { return; }
    if (u.protocol !== 'http:' && u.protocol !== 'https:') return;
    e.preventDefault();
    openVia(u.href).catch(function (err) {
      report('窓で開けませんでした: ' + (err && err.message), { source: u.origin + u.pathname }, 'report');
      window.open(u.href, '_blank', 'noopener');   // 入口に頼めないときは、ブラウザに任せる(タブのある窓になる)
    });
  }
  document.addEventListener('click', function (e) { if (e.button === 0) onLink(e); });
  document.addEventListener('auxclick', function (e) { if (e.button === 1) onLink(e); });
  var win = { isApp: isApp, open: openVia };

  window.UIKit = { version: 2, theme: theme, tools: tools, life: life, report: function (message, info) { return report(message, info, 'report'); }, win: win };
})();
