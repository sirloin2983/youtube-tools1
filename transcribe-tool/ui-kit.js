/* このファイルは ui-kit/ から tools/sync_ui_kit.py で写したもの。直すときは ui-kit/ の正本を直して写し直す */
/* ui-kit v6 — テーマ切り替えと、ツール間のリンク。<head> の中で CSS より先に同期読み込みする(画面のちらつき防止)。
   画面の全面見直し(.design/ui-overhaul/)の段階1。ES5 のまま(var・function。アロー関数・テンプレート文字列は使わない): <head> で同期に読み込むため。
   正本はリポジトリ直下の ui-kit/ui-kit.js。各ツールへは tools/sync_ui_kit.py で写す(手で直接直さない)。
   window.UIKit.theme  : get() 保存した選択('system'|'light'|'dark'。**v6: 保存が無いときは既定で 'light'**。以前は OS の設定(system)に従っていた) / resolved() 実際の見た目 / set(p) / toggle() / onChange(fn)
   window.UIKit.tools  : 既定のポートとツール名。render(el, {current, ports}) で「他のツール」メニューを作る。
                         setPaths(/api/siblings の paths) で、入口の統合サーバーに取り込まれたツールの場所(/studio/ など)を覚える
   window.UIKit.life   : onLeave(fn(reason)) / onReturn(fn(reason)) / isAway()。画面を離れた・戻ったの合図(段階7-2)。
                         離れた = タブの切り替え('hidden')・別の窓へ移った('blur')・閉じる直前('pagehide')。戻った = 'visible' | 'focus' | 'pageshow'
   window.UIKit.report : report(message, info) 画面のエラーを入口のログ(app\logs\client-errors.jsonl)へ送る(段階7-0)。
                         捕まえられなかったエラー(error・unhandledrejection)は自動で送る。入口の外(合言葉なし)では送らない
   window.UIKit.win    : isApp() 窓(Edge のアプリモード)で開いているか / open(url) 入口に頼んで開く(段階7-3)。
                         窓の中の「新しいタブで開く」リンクは自動で: このパソコンの画面 → 同じ形の窓、外のサイト → いつものブラウザ
   v3: 入口・案件へ戻るリンク(ヘッダーの <a data-ui-home>・<a data-ui-cases> と「他のツール」メニューの先頭)、
       window.UIKit.fmt : ago(ms) 相対の日時(「3日前」)/ date(ms) 日付と時刻 / dur(秒) 長さ(1:23:45)、window.UIKit.esc(s)
   v4: 文字起こしツールと cut2resolve を「編集」に統合(docs/edit-tool-design.md)。transcribe の表示名を「編集」に、cut2resolve は hidden
   v5: 配信者の名前(字幕の色)の欄 <input data-ui-streamer>(UIKit.streamer。候補と色の見本。docs/followup-2026-09-27.md の 4)、
       入口へ戻るリンク(data-ui-portal)は、入口がほかの窓・タブで開いていれば新しく開かずにそちらを前に出す(UIKit.portal。入口が二つにならないように。2026-09-27)
       (一覧には残す = 編集が UIKit.tools.base('cut2resolve') でパックの API を呼ぶ。「他のツール」のメニューには出さない)
   v6(2026-09-27・画面の全面見直し 段階1): 既定のテーマを明るいに、新しい部品(すべて README.md の「v6」に使い方):
       UIKit.appnav(ホーム/スタジオ/編集の切り替え)・UIKit.drawer(右から出る引き出し)・UIKit.dialog(確認・警告)・
       details.ui-pop(ポップオーバー。ui-menu と同じ閉じ方)・UIKit.toast(通知。重ねて最大3つ)・UIKit.keybar(下の細い帯)・
       UIKit.settings.mount(設定の引き出し)・UIKit.keys(共通の再生キー)・UIKit.icon(SVG の線のアイコン) */
(function () {
  'use strict';
  var KEY = 'ytt:theme';
  var root = document.documentElement;
  var mq = window.matchMedia ? window.matchMedia('(prefers-color-scheme: dark)') : null;
  var subs = [];

  /* v6: 保存が無いときの既定は明るい(以前は 'system' = OS の設定)。'system'(OSに合わせる)は選んだときだけ明示的に保存する */
  function pref() {
    try { var v = localStorage.getItem(KEY); return v === 'light' || v === 'dark' || v === 'system' ? v : 'light'; } catch (e) { return 'light'; }
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
    if (p !== 'light' && p !== 'dark' && p !== 'system') p = 'light';
    try { localStorage.setItem(KEY, p); } catch (e) { /* 保存できなくても見た目は変える */ }   /* v6: 'system' も明示的に保存する(absent は明るい) */
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
  /* 「他のツール」などの <details class="ui-menu"> と、v6 の <details class="ui-pop">(ポップオーバー)を、外側のクリックと Esc で閉じる */
  var POP_SEL = 'details.ui-menu[open], details.ui-pop[open]';
  document.addEventListener('click', function (e) {
    var open = document.querySelectorAll(POP_SEL);
    for (var i = 0; i < open.length; i++) if (!open[i].contains(e.target)) open[i].removeAttribute('open');
  });
  document.addEventListener('keydown', function (e) {
    if (e.key !== 'Escape') return;
    var open = document.querySelectorAll(POP_SEL);
    for (var i = 0; i < open.length; i++) {
      var d = open[i], s = d.querySelector('summary');
      d.removeAttribute('open');
      if (s && s.focus) s.focus({ preventScroll: true });   /* v6: Esc では summary へフォーカスを戻す */
    }
  });

  /* ---- ツール間のリンク ---- */
  var TOOLS = [
    { id: 'studio', name: '切り抜きスタジオ', sub: '配信を探す・切り抜く区間を選ぶ', port: 8800, mark: 'studio' },
    { id: 'transcribe', name: '編集', sub: 'カット・字幕・Resolve へのパック', port: 8775, mark: 'transcribe' },
    { id: 'cut2resolve', name: 'cut2resolve', sub: '「編集」がパックを作るのに使う部品', port: 8810, mark: 'cut2resolve', hidden: true }
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
      /* v6: ツールの場所が分かったら、先に描いた appnav のリンクを描き直す(appnav は DOMContentLoaded で1回描くが、場所は /api/siblings・/api/status の答えで後から来る) */
      if (document.readyState !== 'loading') renderAppNav();
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
    /* 入口に取り込まれているか(入口が画面に合言葉 ytt-token を入れる)。取り込まれていれば入口は同じアドレスの / */
    mounted: function () { return !!document.querySelector('meta[name="ytt-token"]'); },
    render: function (el, opt) {
      if (!el) return;
      opt = opt || {};
      var html = '';
      if (tools.mounted()) {   // 入口・案件へ戻る(ツールを開いたタブから、迷わず戻れるように)
        html += '<a href="/" data-ui-portal><span class="ui-brand-mark" data-tool="portal" aria-hidden="true"></span><span><b>入口</b><small>ツールの状態・起動と終了</small></span></a>' +
          '<a href="/cases.html"><span class="ui-brand-mark" data-tool="portal" aria-hidden="true"></span><span><b>案件の一覧</b><small>配信ごとの切り抜き・文字起こし・パック</small></span></a>' +
          '<div class="ui-menu-sep" role="separator"></div>';
      }
      for (var i = 0; i < TOOLS.length; i++) {
        var t = TOOLS[i], cur = t.id === opt.current;
        if (t.hidden && !cur) continue;   // 部品(cut2resolve)はメニューに出さない
        html += '<a href="' + esc(cur ? tools.base(t.id) : tools.url(t.id, opt.ports)) + '"' + (cur ? ' aria-current="page"' : ' target="_blank" rel="noopener"') + '>' +
          '<span class="ui-brand-mark" data-tool="' + t.mark + '" aria-hidden="true"></span><span><b>' + esc(t.name) + '</b><small>' + esc(t.sub) + (cur ? '(いま開いている画面)' : '') + '</small></span></a>';
      }
      el.innerHTML = html;
    }
  };
  theme.syncButtons = syncButtons;

  /* ---- 入口・案件へ戻るリンク(v3)---- ヘッダーに <a data-ui-home hidden> / <a data-ui-cases hidden> を置くと、入口に取り込まれているときだけ出す */
  document.addEventListener('DOMContentLoaded', function () {
    if (!tools.mounted()) return;
    var home = document.querySelectorAll('[data-ui-home]'), cases = document.querySelectorAll('[data-ui-cases]');
    for (var i = 0; i < home.length; i++) { home[i].setAttribute('href', '/'); home[i].setAttribute('data-ui-portal', ''); home[i].hidden = false; }
    for (var j = 0; j < cases.length; j++) { cases[j].setAttribute('href', '/cases.html'); cases[j].hidden = false; }
  });

  /* ---- 表示の書式(v3)---- 一覧で「いつのものか」をすぐ分かるように */
  function pad2(n) { return (n < 10 ? '0' : '') + n; }
  var fmt = {
    date: function (ms) {
      if (!ms) return '';
      var d = new Date(ms), now = new Date();
      return (d.getFullYear() !== now.getFullYear() ? d.getFullYear() + '/' : '') + (d.getMonth() + 1) + '/' + d.getDate() + ' ' + pad2(d.getHours()) + ':' + pad2(d.getMinutes());
    },
    ago: function (ms) {
      if (!ms) return '';
      var sec = (Date.now() - ms) / 1000;
      if (sec < 60) return 'たった今';
      if (sec < 3600) return Math.floor(sec / 60) + '分前';
      var d = new Date(ms), now = new Date();
      var days = Math.round((new Date(now.getFullYear(), now.getMonth(), now.getDate()) - new Date(d.getFullYear(), d.getMonth(), d.getDate())) / 86400000);
      if (days <= 0) return '今日 ' + pad2(d.getHours()) + ':' + pad2(d.getMinutes());
      if (days === 1) return '昨日 ' + pad2(d.getHours()) + ':' + pad2(d.getMinutes());
      if (days < 7) return days + '日前';
      return fmt.date(ms).split(' ')[0];
    },
    dur: function (sec) {
      sec = Math.max(0, Math.round(+sec || 0));
      var h = Math.floor(sec / 3600), m = Math.floor(sec % 3600 / 60), s2 = sec % 60;
      return (h ? h + ':' + pad2(m) : m) + ':' + pad2(s2);
    }
  };

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

  /* ---- 入口へ戻る(v5)---- bat で開いた入口の窓があるのに、ツールの窓の「入口」で同じ窓を入口へ移すと、入口が二つになっていた(2026-09-27)。
     入口の画面(portal.js が UIKit.portal.listen())が BroadcastChannel で答えたら、移らずに入口(サーバー)に「入口の窓を前に出して」と頼む
     (api/ytt/focus-portal。Windows の窓を題名で探す)。前に出せなかったら知らせるだけ(ツールの画面はそのまま)。
     答えが無ければ今までどおり、その場で入口へ移る。同じパソコン・同じブラウザのプロファイルの中だけで届く(外には出ない) */
  var PORTAL_CH = 'ytt-portal';
  function portalOpen(ms) {
    return new Promise(function (resolve) {
      if (!window.BroadcastChannel) return resolve(false);
      var ch, done = false, id = String(Math.random()).slice(2);
      function end(v) { if (done) return; done = true; try { ch.close(); } catch (e) { /* 閉じ済み */ } resolve(v); }
      try { ch = new BroadcastChannel(PORTAL_CH); } catch (e) { return resolve(false); }
      ch.onmessage = function (e) { var d = e.data || {}; if (d.type === 'here' && d.re === id) end(true); };
      ch.postMessage({ type: 'ping', id: id });
      setTimeout(function () { end(false); }, ms || 400);
    });
  }
  function note(message) { toastFn(message, { kind: 'info', ms: 5000 }); }   /* v6: UIKit.toast(下で定義)を使う(ツールごとの知らせの部品に頼らない) */
  var portal = {
    /* 入口の画面が呼ぶ: ほかの窓の「入口」リンクに「ここにある」と答える */
    listen: function () {
      if (!window.BroadcastChannel) return;
      try {
        var ch = new BroadcastChannel(PORTAL_CH);
        ch.onmessage = function (e) { var d = e.data || {}; if (d.type === 'ping' && d.id) ch.postMessage({ type: 'here', re: d.id }); };
      } catch (e) { /* 使えないブラウザ: 答えない(リンクは今までどおり移る) */ }
    },
    isOpen: portalOpen,
    /* 入口へ: 開いていれば前に出す(-> 'focused' | 'elsewhere')、無ければ href へ移る(-> 'moved') */
    go: function (href) {
      return portalOpen(400).then(function (open) {
        if (!open || !token()) { location.href = href || '/'; return 'moved'; }
        return yttPost('focus-portal', {}).then(function (r) { return r && r.focused ? 'focused' : 'elsewhere'; }, function () { return 'elsewhere'; })
          .then(function (how) {
            if (how === 'elsewhere') note('入口はほかの窓(タブ)で開いています。タスクバーから切り替えてください');
            return how;
          });
      });
    }
  };
  document.addEventListener('click', function (e) {
    if (e.button !== 0 || e.defaultPrevented || e.ctrlKey || e.shiftKey || e.metaKey || e.altKey) return;
    var a = e.target && e.target.closest ? e.target.closest('a[data-ui-portal]') : null;
    if (!a || !token()) return;
    e.preventDefault();
    portal.go(a.href);
  });

  /* ---- 配信者の名前(字幕の色)の欄(v5)---- <input data-ui-streamer> に、名前の候補(datalist)・色の見本・合う人の表示を付ける。
     名前 → メンバーカラーの照らし合わせは入口(api/ytt/streamer-colors → ytt_core/colors.py)の1か所。欄の値は名前のまま送り、
     使う側(cut2resolve・まとめて実行)も同じ規則で照らし合わせる(画面に規則を書かない)。入口の外では使えないと知らせる。
     値を画面から入れ直したら UIKit.streamer.set(input, 名前)。合う人が決まるたびに input に 'ui-streamer' イベント(detail: 人 | null) */
  var streamerList = null;
  function streamerItems() {
    if (!streamerList) streamerList = yttPost('streamer-colors', { q: '', all: true }).then(function (j) { return j.items || []; }, function () { streamerList = null; return []; });
    return streamerList;
  }
  function attachStreamer(input) {
    if (!input || input.__uiStreamer) return;
    var id = 'ui-streamer-list';
    if (!document.getElementById(id)) {
      var dl = document.createElement('datalist');
      dl.id = id;
      document.body.appendChild(dl);
      if (token()) streamerItems().then(function (items) {
        dl.innerHTML = items.map(function (e) { return '<option value="' + esc(e.name) + '">' + esc((e.group || '') + ' ' + e.hex) + '</option>'; }).join('');
      });
    }
    input.setAttribute('list', id);
    input.setAttribute('autocomplete', 'off');
    input.maxLength = 60;
    var sw = document.createElement('span'), hint = document.createElement('small');
    sw.className = 'ui-streamer-sw'; sw.hidden = true; sw.setAttribute('aria-hidden', 'true');
    hint.className = 'ui-streamer-hint'; hint.setAttribute('aria-live', 'polite');
    input.insertAdjacentElement('afterend', sw);
    sw.insertAdjacentElement('afterend', hint);
    var timer = 0, seq = 0, last = null;
    function tell(who) { try { input.dispatchEvent(new CustomEvent('ui-streamer', { detail: who })); } catch (e) { /* 古いブラウザ */ } }
    /* 同じ名前ではもう一度照らし合わせない(force を除く)。欄から離れた(change)ときに説明の文が変わると、隣のボタンが押している途中で
       ずれてクリックが成立しなかった(2026-09-27)。同じ理由で、照らし合わせの途中は説明の文を変えない */
    function show(force) {
      var q = input.value.trim();
      if (!force && q === last) return;
      last = q;
      var my = ++seq;
      input.removeAttribute('data-color'); sw.hidden = true; sw.style.background = '';
      if (!q) { hint.textContent = '空なら黒い文字'; tell(null); return; }
      if (!token()) { hint.textContent = '入口から開くと使えます'; tell(null); return; }
      yttPost('streamer-colors', { q: q }).then(function (j) {
        if (my !== seq) return;
        if (j.match) {
          sw.hidden = false; sw.style.background = j.match.hex;
          hint.textContent = j.match.name + ' の色 ' + j.match.hex + '(文字をこの色に)';
          input.setAttribute('data-color', j.match.hex);
          tell(j.match);
        } else {
          hint.textContent = j.candidates && j.candidates.length ? '1人に決まりません。候補: ' + j.candidates.slice(0, 5).map(function (e) { return e.name; }).join('・')
            : '見つかりません(ホロカラーのマイカラーに足すと使えます)';
          tell(null);
        }
      }, function () { if (my === seq) { hint.textContent = '色の一覧を読めません'; tell(null); } });
    }
    input.__uiStreamer = show;
    input.addEventListener('input', function () { clearTimeout(timer); timer = setTimeout(function () { show(false); }, 200); });
    input.addEventListener('change', function () { clearTimeout(timer); show(false); });
    show(true);
  }
  var streamer = {
    attach: attachStreamer,
    set: function (input, value) { if (!input) return; input.value = value || ''; attachStreamer(input); input.__uiStreamer(true); },
    value: function (input) { return input ? input.value.trim() : ''; }
  };
  document.addEventListener('DOMContentLoaded', function () {
    var list = document.querySelectorAll('input[data-ui-streamer]');
    for (var i = 0; i < list.length; i++) attachStreamer(list[i]);
  });

  /* ==== v6(2026-09-27・画面の全面見直し 段階1): 共通の部品。使い方は README.md の「v6」 ==== */

  /* ---- appnav(ホーム/スタジオ/編集の切り替え。ヘッダーの左) ---- <nav data-ui-appnav="studio|transcribe|portal"> に中身を作る */
  var APPNAV_ITEMS = [{ id: 'portal', label: 'ホーム' }, { id: 'studio', label: 'スタジオ' }, { id: 'transcribe', label: '編集' }];
  var appnavSuffix = {}, appnavVersion = '';
  function appnavHref(id) { return id === 'portal' ? '/' : (tools.mounted() ? tools.base(id) : tools.url(id)); }
  function renderAppNav() {
    var navs = document.querySelectorAll('[data-ui-appnav]');
    for (var n = 0; n < navs.length; n++) {
      var nav = navs[n], current = nav.getAttribute('data-ui-appnav') || '', html = '';
      for (var i = 0; i < APPNAV_ITEMS.length; i++) {
        var it = APPNAV_ITEMS[i];
        if (it.id === 'portal' && !tools.mounted()) continue;   // 単体で開いたとき(入口の外)はホームを出さない
        var base = appnavHref(it.id), href = base + (appnavSuffix[it.id] || '');
        html += '<a href="' + esc(href) + '" data-ui-appnav-item="' + it.id + '" data-ui-appnav-base="' + esc(base) + '"' +
          (it.id === current ? ' aria-current="page"' : '') + (it.id === 'portal' ? ' data-ui-portal' : '') + '>' + esc(it.label) + '</a>';
      }
      nav.innerHTML = html;
      if (appnavVersion) { var cur = nav.querySelector('[aria-current="page"]'); if (cur) cur.title = appnavVersion; }   /* 描き直しても版の title を保つ */
    }
  }
  document.addEventListener('DOMContentLoaded', renderAppNav);
  var APPNAV_SUFFIX_RE = /^[?#]/;
  var appnav = {
    /* 画面が開いている動画を引き継ぐ('?media=…' のように ? か # で始まる文字列だけ受け付ける) */
    setLink: function (id, suffix) {
      if (typeof suffix !== 'string' || !APPNAV_SUFFIX_RE.test(suffix)) return;
      appnavSuffix[id] = suffix;
      var els = document.querySelectorAll('[data-ui-appnav-item="' + id + '"]');
      for (var i = 0; i < els.length; i++) els[i].setAttribute('href', (els[i].getAttribute('data-ui-appnav-base') || appnavHref(id)) + suffix);
    },
    /* 今の場所の項目の title に版を出す */
    setVersion: function (text) {
      appnavVersion = String(text || '');
      var navs = document.querySelectorAll('[data-ui-appnav]');
      for (var n = 0; n < navs.length; n++) { var cur = navs[n].querySelector('[aria-current="page"]'); if (cur) cur.title = text; }
    }
  };

  /* ---- drawer(右から出る引き出し。設定・書き出し・パックの詳しい設定など) ----
     UIKit.drawer.open(el, {modal:true|false, opener}) / close(el) / isOpen(el)。
     modal: 裏に幕・裏を inert(body の直接の子。引き出し自身・幕・トースト・キーの帯は除く)にしてフォーカスを閉じ込める(inert が Tab を外へ出さない)。
     docked(modal:false): 幕なし・裏も操作できる */
  function drawerKeepEls(el, scrim) {
    var keep = [el], toastEl = document.getElementById('toast'), kbEl = document.querySelector('.ui-keybar');
    if (scrim) keep.push(scrim);
    if (toastEl) keep.push(toastEl);
    if (kbEl) keep.push(kbEl);
    return keep;
  }
  function drawerInert(keep, on) {
    /* 引き出しから body までの道すじの各段で、道すじ以外の兄弟を inert にする(引き出しが body の直接の子でなくても、裏の全部を止める)。
       保つ要素(幕・トースト・キーの帯)を含む兄弟は inert にしない */
    var body = document.body; if (!body) return;
    var node = keep[0];
    while (node && node !== body && node.parentNode) {
      var sibs = node.parentNode.children;
      for (var i = 0; i < sibs.length; i++) {
        var k = sibs[i], keepThis = k === node;
        for (var j = 1; !keepThis && j < keep.length; j++) if (keep[j] && k.contains(keep[j])) keepThis = true;
        if (!keepThis) k.inert = on;
      }
      node = node.parentNode;
    }
  }
  function drawerFocusables(el) {
    return el.querySelectorAll('a[href],button:not([disabled]),input:not([disabled]),select:not([disabled]),textarea:not([disabled]),[tabindex]:not([tabindex="-1"])');
  }
  function fireDrawerEvent(el, open) { try { document.dispatchEvent(new CustomEvent('ui-drawer', { detail: { open: open, el: el } })); } catch (e) { /* 古いブラウザ */ } }
  var drawer = {
    isOpen: function (el) { return !!(el && !el.hidden); },
    open: function (el, opt) {
      if (!el || !el.hidden) return;
      opt = opt || {};
      var modal = opt.modal !== false;
      el.__uiOpener = opt.opener || document.activeElement;
      el.__uiModal = modal;
      el.hidden = false;
      el.setAttribute('role', 'dialog');
      el.setAttribute('aria-hidden', 'false');
      if (modal) el.setAttribute('aria-modal', 'true'); else el.removeAttribute('aria-modal');
      if (modal) {
        var scrim = document.createElement('div');
        scrim.className = 'ui-drawer-scrim';
        scrim.addEventListener('click', function () { drawer.close(el); });
        (el.parentNode || document.body).insertBefore(scrim, el);
        el.__uiScrim = scrim;
        drawerInert(drawerKeepEls(el, scrim), true);
      }
      requestAnimationFrame(function () { el.classList.add('in'); });
      if (opt.focus !== false) setTimeout(function () {   /* focus:false: 自動で開くとき(スタジオの書き出しの欄)はフォーカスを動かさない */
        if (el.contains(document.activeElement)) return;
        var list = drawerFocusables(el);
        if (list.length && list[0].focus) list[0].focus({ preventScroll: true });
      }, 30);
      fireDrawerEvent(el, true);
    },
    close: function (el) {
      if (!el || el.hidden) return;
      el.classList.remove('in'); el.hidden = true; el.setAttribute('aria-hidden', 'true');
      if (el.__uiScrim) {
        drawerInert(drawerKeepEls(el, el.__uiScrim), false);
        if (el.__uiScrim.parentNode) el.__uiScrim.parentNode.removeChild(el.__uiScrim);
        el.__uiScrim = null;
      }
      var opener = el.__uiOpener; el.__uiOpener = null;
      if (opener && opener.isConnected && opener.focus) opener.focus({ preventScroll: true });
      fireDrawerEvent(el, false);
    }
  };
  /* modal の引き出しの中で Tab を回す(最後 → 先頭、Shift+Tab で先頭 → 最後)。inert だけではブラウザのアドレス欄へ抜けるため */
  document.addEventListener('keydown', function (e) {
    if (e.key !== 'Tab' || document.querySelector('dialog[open]')) return;
    var open = document.querySelectorAll('.ui-drawer:not([hidden])'), el = null;
    for (var i = open.length - 1; i >= 0; i--) if (open[i].__uiModal) { el = open[i]; break; }
    if (!el) return;
    var list = [], all = drawerFocusables(el);
    for (var j = 0; j < all.length; j++) if (all[j].offsetParent !== null || all[j] === document.activeElement) list.push(all[j]);
    if (!list.length) return;
    var first = list[0], last = list[list.length - 1], a = document.activeElement;
    if (!el.contains(a)) { e.preventDefault(); first.focus(); }
    else if (e.shiftKey && a === first) { e.preventDefault(); last.focus(); }
    else if (!e.shiftKey && a === last) { e.preventDefault(); first.focus(); }
  });
  /* Esc: 開いている引き出しのうち、modal か(フォーカスが中にある docked)を閉じる(いちばん後ろ = 手前のものから)。
     引き出しの上に確認ダイアログ(<dialog>)が開いているときは、ダイアログだけが Esc を受け取る(ブラウザの標準の動きに任せる) */
  document.addEventListener('keydown', function (e) {
    if (e.key !== 'Escape') return;
    if (document.querySelector('dialog[open]')) return;
    var open = document.querySelectorAll('.ui-drawer:not([hidden])');
    for (var i = open.length - 1; i >= 0; i--) {
      var el = open[i];
      if (el.__uiModal || el.contains(document.activeElement)) { e.preventDefault(); drawer.close(el); break; }
    }
  });

  /* ---- dialog(確認・警告) ---- <dialog class="ui-dialog"> + showModal(フォーカスの閉じ込め・Esc はブラウザに任せる)。本文は textContent で入れる(XSS を作らない) */
  function buildDialogShell() {
    var dlg = document.createElement('dialog'); dlg.className = 'ui-dialog';
    var head = document.createElement('div'); head.className = 'ui-dlg-head';
    var h2 = document.createElement('h2'); head.appendChild(h2);
    var body = document.createElement('div'); body.className = 'ui-dlg-body';
    var actions = document.createElement('div'); actions.className = 'ui-dlg-actions';
    dlg.appendChild(head); dlg.appendChild(body); dlg.appendChild(actions);
    (document.body || document.documentElement).appendChild(dlg);
    return { dlg: dlg, h2: h2, body: body, actions: actions };
  }
  function dialogConfirm(opts) {
    opts = opts || {};
    return new Promise(function (resolve) {
      var parts = buildDialogShell(), opener = document.activeElement, done = false;
      parts.h2.textContent = opts.title || '確認';
      parts.body.textContent = opts.body || '';
      var cancelBtn = document.createElement('button');
      cancelBtn.type = 'button'; cancelBtn.className = 'btn ghost'; cancelBtn.textContent = opts.cancel || 'キャンセル';
      var okBtn = document.createElement('button');
      okBtn.type = 'button'; okBtn.className = 'btn ' + (opts.danger ? 'danger solid' : 'primary'); okBtn.textContent = opts.ok || 'OK';
      parts.actions.appendChild(cancelBtn); parts.actions.appendChild(okBtn);
      function finish(v) { if (done) return; done = true; resolve(v); parts.dlg.close(); }
      cancelBtn.addEventListener('click', function () { finish(false); });
      okBtn.addEventListener('click', function () { finish(true); });
      parts.dlg.addEventListener('close', function () {
        if (!done) { done = true; resolve(false); }
        if (parts.dlg.parentNode) parts.dlg.parentNode.removeChild(parts.dlg);
        if (opener && opener.isConnected && opener.focus) opener.focus({ preventScroll: true });
      });
      parts.dlg.showModal();
      (opts.danger ? cancelBtn : okBtn).focus({ preventScroll: true });   /* 消す・戻せない操作(danger)は、既定のフォーカスを安全な方(キャンセル)に */
    });
  }
  function dialogAlert(opts) {
    opts = opts || {};
    return new Promise(function (resolve) {
      var parts = buildDialogShell(), opener = document.activeElement, done = false;
      parts.h2.textContent = opts.title || 'お知らせ';
      parts.body.textContent = opts.body || '';
      var okBtn = document.createElement('button');
      okBtn.type = 'button'; okBtn.className = 'btn primary'; okBtn.textContent = opts.ok || 'OK';
      parts.actions.appendChild(okBtn);
      function finish() { if (done) return; done = true; resolve(undefined); parts.dlg.close(); }
      okBtn.addEventListener('click', finish);
      parts.dlg.addEventListener('close', function () {
        if (!done) { done = true; resolve(undefined); }
        if (parts.dlg.parentNode) parts.dlg.parentNode.removeChild(parts.dlg);
        if (opener && opener.isConnected && opener.focus) opener.focus({ preventScroll: true });
      });
      parts.dlg.showModal();
      okBtn.focus({ preventScroll: true });
    });
  }
  var dialogApi = { confirm: dialogConfirm, alert: dialogAlert };

  /* ---- toast(通知。重ねて最大3つ) ---- <div class="ui-toasts" id="toast" aria-live="polite">。既存の単発の #toast(class=toast)があれば入れ物として作り直す */
  var toastBox = null;
  function ensureToastBox() {
    if (toastBox && toastBox.isConnected) return toastBox;
    var el = document.getElementById('toast');
    if (el) { el.innerHTML = ''; el.hidden = false; el.removeAttribute('role'); }
    else { el = document.createElement('div'); el.id = 'toast'; (document.body || document.documentElement).appendChild(el); }
    el.className = 'ui-toasts';
    el.setAttribute('aria-live', 'polite');
    toastBox = el;
    return el;
  }
  function toastFn(message, opt) {
    opt = opt || {};
    var kind = opt.kind || '', isErr = kind === 'err';
    var ms = opt.ms || (isErr ? 8000 : 2500);
    var box = ensureToastBox();
    while (box.children.length >= 3) box.removeChild(box.firstChild);   // 最大3つ(古いものから消す)
    var item = document.createElement('div');
    item.className = 'ui-toast' + (kind ? ' ' + kind : '');
    item.setAttribute('role', isErr ? 'alert' : 'status');
    var msgEl = document.createElement('div'); msgEl.className = 'ui-toast-msg'; msgEl.textContent = message == null ? '' : String(message);
    item.appendChild(msgEl);
    if (opt.detail) {
      var det = document.createElement('details'); det.className = 'ui-toast-detail';
      var sum = document.createElement('summary'); sum.textContent = '詳しく'; det.appendChild(sum);
      var pre = document.createElement('div'); pre.textContent = String(opt.detail); det.appendChild(pre);
      item.appendChild(det);
    }
    function remove() { clearTimeout(timer); if (item.parentNode) item.parentNode.removeChild(item); }
    var timer = setTimeout(remove, ms);
    item.addEventListener('click', function (e) {
      if (e.target && e.target.closest && e.target.closest('details')) return;   // 「詳しく」の開閉では閉じない
      remove();
    });
    box.appendChild(item);
  }

  /* ---- keybar(画面の下の細い帯。いま使えるキー) ---- 既定は表示。設定「キーの帯を出す」(localStorage 'ytt:keybar' === '0' で消す) */
  var keybarEl = null, keybarItems = [];
  function keybarWanted() { try { return localStorage.getItem('ytt:keybar') !== '0'; } catch (e) { return true; } }
  function ensureKeybarEl() {
    if (keybarEl && keybarEl.isConnected) return keybarEl;
    keybarEl = document.createElement('div');
    keybarEl.className = 'ui-keybar'; keybarEl.setAttribute('aria-hidden', 'true'); keybarEl.hidden = true;
    (document.body || document.documentElement).appendChild(keybarEl);
    return keybarEl;
  }
  function keybarPaint() {
    var el = ensureKeybarEl(), html = '';
    for (var i = 0; i < keybarItems.length; i++) {
      var it = keybarItems[i] || {};
      html += '<span class="ui-keybar-item" data-k="' + esc(it.k || '') + '"><kbd class="ui-kbd">' + esc(it.k || '') + '</kbd>' + esc(it.l || '') + '</span>';
    }
    el.innerHTML = html;
    var show = keybarItems.length > 0 && keybarWanted();
    el.hidden = !show;
    if (show) root.setAttribute('data-keybar', ''); else root.removeAttribute('data-keybar');
  }
  var keybar = {
    set: function (items) { keybarItems = items || []; keybarPaint(); },
    flash: function (k) {
      var el = ensureKeybarEl(), items = el.querySelectorAll('.ui-keybar-item');
      for (var i = 0; i < items.length; i++) if (items[i].getAttribute('data-k') === k) (function (node) {
        node.classList.add('flash');
        setTimeout(function () { node.classList.remove('flash'); }, 220);
      })(items[i]);
    },
    clear: function () { keybarItems = []; keybarPaint(); }
  };

  /* ---- 文字の大きさ(localStorage 'ytt:fs'。'lg' で html[data-fs=lg]。ui-kit.css がトークンを少し大きくする) ---- */
  var fsControls = [], keybarControls = [];
  function fsPref() { try { return localStorage.getItem('ytt:fs') === 'lg' ? 'lg' : 'md'; } catch (e) { return 'md'; } }
  function applyFontSize() { if (fsPref() === 'lg') root.setAttribute('data-fs', 'lg'); else root.removeAttribute('data-fs'); }
  applyFontSize();
  /* 全体の設定(テーマ・文字の大きさ・キーの帯)は、どのツールで変えても他のタブ・他のツールに効く(storage イベント。テーマは既存の paint() と同じ仕組み) */
  window.addEventListener('storage', function (e) {
    if (e.key === 'ytt:fs') {
      applyFontSize();
      var fv = fsPref();
      for (var i = 0; i < fsControls.length; i++) fsControls[i].value = fv;
    } else if (e.key === 'ytt:keybar') {
      keybarPaint();
      var kv = keybarWanted();
      for (var j = 0; j < keybarControls.length; j++) keybarControls[j].checked = kv;
    }
  });

  /* ---- settings(⚙ の引き出し) ---- UIKit.settings.mount({tool: 要素 | null, title, version}) */
  var settingsDrawerEl = null, generalSectionEl = null;
  function addOpt(sel, value, label) { var o = document.createElement('option'); o.value = value; o.textContent = label; sel.appendChild(o); }
  function buildGeneralSection() {
    /* settings.mount() が2回以上呼ばれても(ツールが呼び直したときも)、控え・リスナーを増やさない: 一度作った節を使い回す(appendChild で移す) */
    if (generalSectionEl) return generalSectionEl;
    var sec = document.createElement('section'); sec.className = 'ui-settings-sec';
    var h3 = document.createElement('h3'); h3.textContent = '全体'; sec.appendChild(h3);

    var themeRow = document.createElement('div'); themeRow.className = 'ui-settings-row';
    var themeLabel = document.createElement('span'); themeLabel.textContent = 'テーマ';
    var themeSel = document.createElement('select');
    addOpt(themeSel, 'light', '明るい'); addOpt(themeSel, 'dark', '暗い'); addOpt(themeSel, 'system', 'OSに合わせる');
    themeSel.value = theme.get();
    themeSel.addEventListener('change', function () { theme.set(themeSel.value); });
    theme.onChange(function (t, p) { themeSel.value = p; });
    themeRow.appendChild(themeLabel); themeRow.appendChild(themeSel);

    var fsRow = document.createElement('div'); fsRow.className = 'ui-settings-row';
    var fsLabel = document.createElement('span'); fsLabel.textContent = '文字の大きさ';
    var fsSel = document.createElement('select');
    addOpt(fsSel, 'md', '標準'); addOpt(fsSel, 'lg', '大きい');
    fsSel.value = fsPref();
    fsSel.addEventListener('change', function () {
      try { localStorage.setItem('ytt:fs', fsSel.value); } catch (e) { /* 保存できなくても見た目は変える */ }
      applyFontSize();
    });
    fsControls.push(fsSel);
    fsRow.appendChild(fsLabel); fsRow.appendChild(fsSel);

    var kbRow = document.createElement('div'); kbRow.className = 'ui-settings-row';
    var kbLabel = document.createElement('label'); kbLabel.className = 'lag';
    var kbCheck = document.createElement('input'); kbCheck.type = 'checkbox'; kbCheck.checked = keybarWanted();
    kbCheck.addEventListener('change', function () {
      try { localStorage.setItem('ytt:keybar', kbCheck.checked ? '1' : '0'); } catch (e) { /* 保存できなくても見た目は変える */ }
      keybarPaint();
    });
    keybarControls.push(kbCheck);
    kbLabel.appendChild(kbCheck); kbLabel.appendChild(document.createTextNode('キーの帯を出す'));
    kbRow.appendChild(kbLabel);

    sec.appendChild(themeRow); sec.appendChild(fsRow); sec.appendChild(kbRow);
    generalSectionEl = sec;
    return sec;
  }
  function buildSettingsDrawer() {
    if (settingsDrawerEl && settingsDrawerEl.isConnected) return settingsDrawerEl;
    var el = document.createElement('aside');
    el.className = 'ui-drawer'; el.id = 'uiSettingsDrawer'; el.hidden = true;
    el.setAttribute('aria-hidden', 'true'); el.setAttribute('aria-labelledby', 'uiSettingsTitle');
    var head = document.createElement('div'); head.className = 'ui-drawer-head';
    var h2 = document.createElement('h2'); h2.className = 'ui-drawer-title'; h2.id = 'uiSettingsTitle'; h2.textContent = '設定';
    var ver = document.createElement('span'); ver.className = 'ui-ver'; ver.id = 'uiSettingsVer'; ver.hidden = true;
    var closeBtn = document.createElement('button');
    closeBtn.type = 'button'; closeBtn.className = 'btn ghost icon small'; closeBtn.setAttribute('aria-label', '閉じる'); closeBtn.innerHTML = icon('close');
    closeBtn.addEventListener('click', function () { drawer.close(el); });
    head.appendChild(h2); head.appendChild(ver); head.appendChild(closeBtn);
    var body = document.createElement('div'); body.className = 'ui-drawer-body'; body.id = 'uiSettingsBody';
    el.appendChild(head); el.appendChild(body);
    (document.body || document.documentElement).appendChild(el);
    settingsDrawerEl = el;
    return el;
  }
  function settingsMount(opts) {
    opts = opts || {};
    var el = buildSettingsDrawer(), body = el.querySelector('#uiSettingsBody');
    body.innerHTML = '';
    if (opts.tool) { opts.tool.classList.add('ui-settings-sec'); body.appendChild(opts.tool); }
    body.appendChild(buildGeneralSection());
    if (opts.title) el.querySelector('#uiSettingsTitle').textContent = opts.title;
    var verEl = el.querySelector('#uiSettingsVer');
    if (opts.version) { verEl.textContent = opts.version; verEl.hidden = false; } else verEl.hidden = true;
    var btns = document.querySelectorAll('[data-ui-settings]');
    for (var i = 0; i < btns.length; i++) {
      if (btns[i].__uiSettingsWired) continue;
      btns[i].__uiSettingsWired = true;
      (function (btn) { btn.addEventListener('click', function () { if (drawer.isOpen(el)) drawer.close(el); else drawer.open(el, { modal: true, opener: btn }); }); })(btns[i]);
    }
    return el;
  }
  var settings = { mount: settingsMount };

  /* ---- keys(共通の再生キー) ---- isTyping/helpHtml/playback(NOT auto-installed。画面が自分のキー処理の前に呼び、true なら自分の処理をしない) */
  /* 文字を打てる input だけ「入力中」とみなす(checkbox・radio・button・submit・color・file などは単体キーを邪魔しない) */
  var TYPING_INPUT_TYPES = { text: 1, search: 1, number: 1, email: 1, url: 1, password: 1, tel: 1, date: 1, time: 1, 'datetime-local': 1, month: 1, week: 1, range: 1 };
  function isTyping(t) {
    if (!t) return false;
    var tag = (t.tagName || '').toLowerCase();
    if (tag === 'textarea' || tag === 'select') return true;
    if (t.isContentEditable) return true;
    if (tag === 'input') return !!TYPING_INPUT_TYPES[String(t.type || 'text').toLowerCase()];
    return false;
  }
  /* Space はこれらの上ではブラウザの既定の動き(ボタンを押す・チェックを切り替えるなど)に任せる */
  function isSpaceControlTarget(t) {
    if (!t) return false;
    var tag = (t.tagName || '').toLowerCase();
    if (tag === 'button' || tag === 'summary') return true;
    if (tag === 'a' && t.hasAttribute('href')) return true;
    if (t.getAttribute && t.getAttribute('role') === 'button') return true;
    if (tag === 'input') { var ty = String(t.type || '').toLowerCase(); return ty === 'checkbox' || ty === 'radio'; }
    return false;
  }
  function kbdRow(keyStr, label) {
    var parts = String(keyStr).split(' / '), kbds = '';
    for (var i = 0; i < parts.length; i++) { if (i) kbds += '<span class="muted">/</span>'; kbds += '<kbd class="ui-kbd">' + esc(parts[i]) + '</kbd>'; }
    return '<div class="ui-krow"><span class="ui-klabel">' + esc(label) + '</span><span class="ui-kkeys">' + kbds + '</span></div>';
  }
  function keysHelpHtml() {
    var rows = [
      ['Space', '再生・停止'], ['J', '1秒戻る'], ['K', '止める'], ['L', '再生(もう一度で 1.5 → 2 倍)'],
      ['← / →', '1秒(Shift で5秒)'], [', / .', '1コマ(コマ送り)'], ['I / O', '始まり/終わりの印']
    ];
    var html = '<section class="ui-kgroup"><h3 class="section-title">共通の再生キー</h3>';
    for (var i = 0; i < rows.length; i++) html += kbdRow(rows[i][0], rows[i][1]);
    return html + '</section>';
  }
  /* K・L で戻す速さは、画面の速さの設定(defaultPlaybackRate。編集の「速さ」など)。無ければ 1 倍 */
  function baseRate(media) { var r = +media.defaultPlaybackRate; return r > 0 ? r : 1; }
  function keysPlayback(opts) {
    opts = opts || {};
    return function (e) {
      if (opts.enabled && !opts.enabled()) return false;
      if (isTyping(e.target)) return false;
      if (e.ctrlKey || e.altKey || e.metaKey) return false;
      /* media・fps は関数でもよい(毎回そのとき呼ぶ: 動画の差し替え・読み込み後に決まる fps に対応) */
      var media = typeof opts.media === 'function' ? opts.media() : opts.media;
      var fps = typeof opts.fps === 'function' ? opts.fps() : opts.fps;
      fps = fps > 0 ? fps : 30;
      var key = e.key, shift = e.shiftKey, name = null;
      if (shift && key !== 'ArrowLeft' && key !== 'ArrowRight') return false;   // Shift が要るのは矢印だけ
      function seek(delta) { if (media) { try { media.currentTime = Math.max(0, (media.currentTime || 0) + delta); } catch (er) { /* まだ読み込めていない */ } } }
      if (key === ' ' || key === 'Spacebar') {
        if (isSpaceControlTarget(e.target)) return false;   // ボタン・チェックなどは Space の既定の動きに任せる
        if (media) { try { if (media.paused) media.play(); else media.pause(); } catch (er) { /* 無視 */ } }
        name = 'Space';
      } else if (key === 'j' || key === 'J') { seek(-1); name = 'J'; }
      else if (key === 'k' || key === 'K') { if (media) { try { media.pause(); media.playbackRate = baseRate(media); } catch (er) { /* 無視 */ } } name = 'K'; }
      else if (key === 'l' || key === 'L') {
        if (media) {
          try { if (media.paused) { media.playbackRate = baseRate(media); media.play(); } else media.playbackRate = media.playbackRate >= 1.5 ? 2 : 1.5; } catch (er) { /* 無視 */ }
        }
        name = 'L';
      } else if (key === 'ArrowLeft') { seek(shift ? -5 : -1); name = shift ? 'Shift+←' : '←'; }
      else if (key === 'ArrowRight') { seek(shift ? 5 : 1); name = shift ? 'Shift+→' : '→'; }
      else if (key === ',' || key === '.') {
        var dir = key === ',' ? -1 : 1, done = false;
        if (typeof opts.onFrame === 'function') done = opts.onFrame(dir) === true;
        if (!done) seek(dir * (1 / fps));
        name = key;
      } else if (key === 'i' || key === 'I') { if (typeof opts.onIn === 'function') opts.onIn(); name = 'I'; }
      else if (key === 'o' || key === 'O') { if (typeof opts.onOut === 'function') opts.onOut(); name = 'O'; }
      else return false;
      e.preventDefault();
      if (typeof opts.onKey === 'function') opts.onKey(name);
      keybar.flash(name);
      return true;
    };
  }
  var keysApi = { isTyping: isTyping, helpHtml: keysHelpHtml, playback: keysPlayback };

  /* ---- icon(SVG の線のアイコン。24x24・stroke currentColor・stroke-width 2・角丸) ---- UIKit.icon(name, opts) は文字列を返す。
     <span class="ui-icon" data-icon="play"></span> は読み込み後に中身が入る(UIKit.icon.fill(root)) */
  var ICONS = {
    play: '<path d="M7 4.5v15l13-7.5z"/>',
    pause: '<path d="M8 5v14M16 5v14"/>',
    back: '<path d="M11 5 4 12l7 7M4 12h16"/>',
    forward: '<path d="M13 5l7 7-7 7M20 12H4"/>',
    'frame-prev': '<path d="M11 6 5 12l6 6M19 5v14"/>',
    'frame-next': '<path d="M13 6l6 6-6 6M5 5v14"/>',
    scissors: '<circle cx="6" cy="6" r="3"/><circle cx="6" cy="18" r="3"/><path d="M20 4 8.1 15.9M8.1 8.1 20 20"/>',
    split: '<path d="M12 3v6M12 15v6M5 21l7-7 7 7M5 3l7 7 7-7"/>',
    merge: '<path d="M12 21v-6M12 9V3M5 3l7 7 7-7M5 21l7-7 7 7"/>',
    trash: '<path d="M4 7h16M9 7V4h6v3M6 7l1 13h10l1-13M10 11v6M14 11v6"/>',
    plus: '<path d="M12 5v14M5 12h14"/>',
    minus: '<path d="M5 12h14"/>',
    more: '<circle cx="5" cy="12" r="1.6"/><circle cx="12" cy="12" r="1.6"/><circle cx="19" cy="12" r="1.6"/>',
    gear: '<circle cx="12" cy="12" r="3.2"/><path d="M12 3v2.2M12 18.8V21M4.2 7l1.9 1.1M17.9 15.9l1.9 1.1M3 12h2.2M18.8 12H21M4.2 17l1.9-1.1M17.9 8.1l1.9-1.1M7 4.2l1.1 1.9M15.9 17.9l1.1 1.9"/>',
    menu: '<path d="M4 6h16M4 12h16M4 18h16"/>',
    close: '<path d="M6 6l12 12M18 6 6 18"/>',
    'chevron-down': '<path d="m6 9 6 6 6-6"/>',
    'chevron-right': '<path d="m9 6 6 6-6 6"/>',
    'chevron-left': '<path d="m15 6-6 6 6 6"/>',
    folder: '<path d="M4 7a1 1 0 0 1 1-1h4.5l1.5 2H19a1 1 0 0 1 1 1v9a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1z"/>',
    download: '<path d="M12 4v11m0 0-4-4m4 4 4-4M5 19h14"/>',
    undo: '<path d="M9 8 4 12l5 4M4 12h9a6 6 0 1 1 0 12h-1"/>',
    redo: '<path d="M15 8l5 4-5 4M20 12H11a6 6 0 1 0 0 12h1"/>',
    check: '<path d="m5 13 4 4 10-10"/>',
    alert: '<path d="M12 3 2 20h20zM12 10v4"/><circle cx="12" cy="17" r=".2"/>',
    info: '<circle cx="12" cy="12" r="9"/><path d="M12 8h.01M11 11h1v6h1"/>',
    search: '<circle cx="11" cy="11" r="7"/><path d="m21 21-4.3-4.3"/>',
    home: '<path d="M4 11 12 4l8 7M6 10v9h12v-9"/>',
    film: '<rect x="3.5" y="4.5" width="17" height="15" rx="1.5"/><path d="M8 4.5v15M16 4.5v15M3.5 9h4.5M3.5 15h4.5M16 9h4.5M16 15h4.5"/>',
    text: '<path d="M5 6h14M12 6v13M9 19h6"/>',
    mic: '<rect x="9" y="3" width="6" height="11" rx="3"/><path d="M5 11a7 7 0 0 0 14 0M12 18v3"/>',
    flag: '<path d="M6 3v18M6 4h11l-2.5 3.5L17 11H6"/>',
    keyboard: '<rect x="3" y="6" width="18" height="12" rx="1.5"/><path d="M7 10h.01M11 10h.01M15 10h.01M17 10h.01M7 14h10"/>',
    'zoom-in': '<circle cx="11" cy="11" r="7"/><path d="M11 8v6M8 11h6M21 21l-4.3-4.3"/>',
    'zoom-out': '<circle cx="11" cy="11" r="7"/><path d="M8 11h6M21 21l-4.3-4.3"/>',
    refresh: '<path d="M20 11a8 8 0 0 0-14.9-4M4 13a8 8 0 0 0 14.9 4M4 4v5h5M20 20v-5h-5"/>',
    external: '<path d="M9 6H6a1 1 0 0 0-1 1v11a1 1 0 0 0 1 1h11a1 1 0 0 0 1-1v-3M14 4h6v6M10 14 20 4"/>',
    copy: '<rect x="8" y="8" width="12" height="12" rx="1.5"/><path d="M5.5 16H5a1 1 0 0 1-1-1V5a1 1 0 0 1 1-1h10a1 1 0 0 1 1 1v.5"/>',
    sun: '<circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/>',
    moon: '<path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8z"/>',
    'mark-in': '<path d="M8 4v16M8 4l8 4v8l-8 4"/>',
    'mark-out': '<path d="M16 4v16M16 4l-8 4v8l8 4"/>',
    clock: '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l4 2"/>',
    list: '<path d="M9 6h11M9 12h11M9 18h11M4.5 6h.01M4.5 12h.01M4.5 18h.01"/>',
    layers: '<path d="m12 3 9 5-9 5-9-5z"/><path d="m3 14 9 5 9-5M3 8l9 5 9-5"/>',
    wave: '<path d="M2 12h2l1.5-6 3 12 3-16 3 16 3-10 1.5 4H22"/>',
    user: '<circle cx="12" cy="8" r="3.5"/><path d="M4.5 20a7.5 7.5 0 0 1 15 0"/>'
  };
  function icon(name, opts) {
    opts = opts || {};
    var size = opts.size || 24;
    return '<svg viewBox="0 0 24 24" width="' + size + '" height="' + size + '" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" focusable="false">' +
      (Object.prototype.hasOwnProperty.call(ICONS, name) ? ICONS[name] : '') + '</svg>';
  }
  icon.fill = function (scopeEl) {
    var scope = scopeEl || document;
    var els = scope.querySelectorAll('[data-icon]');
    for (var i = 0; i < els.length; i++) {
      var name = els[i].getAttribute('data-icon');
      if (Object.prototype.hasOwnProperty.call(ICONS, name)) els[i].innerHTML = icon(name);
    }
  };
  document.addEventListener('DOMContentLoaded', function () { icon.fill(document); });

  window.UIKit = { version: 6, theme: theme, tools: tools, life: life, report: function (message, info) { return report(message, info, 'report'); }, win: win, fmt: fmt, esc: esc,
                   portal: portal, streamer: streamer, appnav: appnav, drawer: drawer, dialog: dialogApi, toast: toastFn, keybar: keybar, settings: settings, keys: keysApi, icon: icon };
})();
