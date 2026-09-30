/* ui-kit v9 — テーマ切り替えと、ツール間のリンク。<head> の中で CSS より先に同期読み込みする(画面のちらつき防止)。
   画面の全面見直し(.design/ui-overhaul/)の段階1。ES5 のまま(var・function。アロー関数・テンプレート文字列は使わない): <head> で同期に読み込むため。
   正本はリポジトリ直下の ui-kit/ui-kit.js。各ツールへは dev/sync_ui_kit.py で写す(手で直接直さない)。
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
   v4: 文字起こしツールと cut2resolve を「編集」に統合(docs/design/edit-tool-design.md)。transcribe の表示名を「編集」に、cut2resolve は hidden
   v5: 配信者の名前(字幕の色)の欄 <input data-ui-streamer>(UIKit.streamer。候補と色の見本。docs/archive/followup-2026-09-27.md の 4)、
       入口へ戻るリンク(data-ui-portal)は、入口がほかの窓・タブで開いていれば新しく開かずにそちらを前に出す(UIKit.portal。入口が二つにならないように。2026-09-27)
       (一覧には残す = 編集が UIKit.tools.base('cut2resolve') でパックの API を呼ぶ。「他のツール」のメニューには出さない)
   v6(2026-09-27・画面の全面見直し 段階1): 既定のテーマを明るいに、新しい部品(すべて README.md の「v6」に使い方):
       UIKit.appnav(ホーム/スタジオ/編集の切り替え)・UIKit.drawer(右から出る引き出し)・UIKit.dialog(確認・警告)・
       details.ui-pop(ポップオーバー。ui-menu と同じ閉じ方)・UIKit.toast(通知。重ねて最大3つ)・UIKit.keybar(下の細い帯)・
       UIKit.settings.mount(設定の引き出し)・UIKit.keys(共通の再生キー)・UIKit.icon(SVG の線のアイコン)
   v7(2026-09-29・気が利く画面へ 段1。.design/ux-consistency/): UIKit.toast の ms: 0 = 消えない(以前は 0 が既定の秒数に戻っていた)・
       action: {label, fn}(ボタン1つ)・閉じるボタン・戻り値 {close}。UIKit.confirmTwice(btn, run, text)(二度押しの確認を1つに)。
       UIKit.prefs(ホームの設定 api/ytt/prefs: get(sections)・patch(section, value)(節ごと・まとめて送る)・remember(kind, key, name)・
       available()。保存に失敗したら知らせと [もう一度])。
       UIKit.autorun(まとめて実行の部品: panel(el, {kind, modes}) = 要約1行と「設定を変える」・start(path, body, estBody) = 見積もり → 始める → 終わったら知らせ・
       stepLabel / runLabel = 状態の言葉)。
       UIKit.packLoud(パックの音量: LUFS でそろえる か % で決める。値は編集の設定 packLoudness・packVolume の1か所。mount(select) で選択の欄と % の欄にする・get()・set(values))
   v8(2026-09-29・気が利く画面へ 段6): UIKit.keymap(キーの一覧 = キー配置の設定。README.md の「v8」)
   v9(2026-09-30・全体の計画 段2 監査 11): UIKit.settings.status(state, message, retry, label)(設定の保存・読み込みの失敗を ⚙ の印と引き出しの先頭に)・statusOf() */
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

  /* ポップオーバーを開いたら、画面の外にはみ出さないよう置き場所を直す(A-1: 右端の「…」の選択肢が画面の外に出ていた)。
     data-align の指定のまま置いてみて、はみ出す側だけ反対にそろえる。下にはみ出して上に余裕があれば上に開く */
  function fitPop(d) {
    var body = d.querySelector(':scope > .ui-pop-body, :scope > .ui-menu-pop'); if (!body) return;
    body.style.left = body.style.right = body.style.top = body.style.bottom = body.style.maxHeight = body.style.overflowY = '';
    var r = body.getBoundingClientRect(), vw = document.documentElement.clientWidth || window.innerWidth, vh = window.innerHeight, m = 8;
    if (r.right > vw - m) { body.style.left = 'auto'; body.style.right = '0'; r = body.getBoundingClientRect(); }
    if (r.left < m) { body.style.right = 'auto'; body.style.left = '0'; r = body.getBoundingClientRect(); }
    if (r.right > vw - m) { var p = d.getBoundingClientRect(); body.style.left = Math.round(m - p.left) + 'px'; body.style.right = 'auto'; }   /* どちらにそろえても入らない狭い画面: 画面の左端から */
    if (r.bottom > vh - m) {
      var top = d.getBoundingClientRect().top;
      if (top - r.height - 6 >= m) { body.style.top = 'auto'; body.style.bottom = 'calc(100% + 6px)'; }
      else { body.style.maxHeight = Math.max(120, vh - r.top - m) + 'px'; body.style.overflowY = 'auto'; }
    }
  }
  /* open が付いた直後(描く前)に直す。toggle イベントは後から届くので、1コマだけ画面の外に出て見えることがあった */
  if (window.MutationObserver) new MutationObserver(function (recs) {
    for (var i = 0; i < recs.length; i++) {
      var d = recs[i].target;
      if (d.open && d.matches && d.matches('details.ui-pop, details.ui-menu')) fitPop(d);
    }
  }).observe(document.documentElement, { subtree: true, attributes: true, attributeFilter: ['open'] });

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
      if (typeof loudRefresh === 'function') loudRefresh();   /* v7: パックの音量の欄(編集の場所が分かってから出す) */
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
  /* v7(気が利く画面へ 段5): 配信者の名前を自動で入れる(覚えた名前 → チャンネル名から。決める順は入口の api/ytt/streamer-guess の1か所)・
     札「自動(チャンネル名から)」「前回」・手で直したら文書・配信・チャンネルに覚える(空 = 「色なし」を覚える)・見つからない名前は始める前に聞く */
  function streamerBadge(input, text) {
    var b = input.__badge;
    if (!b) {
      b = document.createElement('span'); b.className = 'pill info ui-streamer-badge'; b.hidden = true;
      var after = input.nextElementSibling && input.nextElementSibling.nextElementSibling ? input.nextElementSibling.nextElementSibling : input;
      after.insertAdjacentElement('afterend', b); input.__badge = b;
    }
    b.textContent = text || ''; b.hidden = !text;
  }
  function streamerRemember(ctx, name) {
    if (!ctx || !prefs.available()) return;
    var noop = function () {};
    if (ctx.docId) prefs.remember('docs', ctx.docId, name).catch(noop);
    if (ctx.videoId) prefs.remember('videos', ctx.videoId, name).catch(noop);
    if (ctx.channel) prefs.remember('channels', ctx.channel, name).catch(noop);
  }
  var streamer = {
    attach: attachStreamer,
    set: function (input, value) { if (!input) return; input.value = value || ''; attachStreamer(input); input.__uiStreamer(true); if (input.__badge) streamerBadge(input, ''); },
    value: function (input) { return input ? input.value.trim() : ''; },
    /* ctx = {docId?, videoId?, channel?}(この欄が何の配信者か)。手で直していなければ、覚えた名前か チャンネル名から入れて札を付ける */
    autoFill: function (input, ctx) {
      if (!input) return Promise.resolve(null);
      attachStreamer(input);
      var key = JSON.stringify(ctx || {});
      if (input.__ctxKey === key && input.__touched) return Promise.resolve(null);   // 同じ相手の欄を手で直したあとは入れ直さない
      input.__ctx = ctx || {}; input.__ctxKey = key; input.__touched = false;
      if (!input.__autoBound) {
        input.__autoBound = true;
        /* 打ち始めたら、あとから届いた自動の名前で上書きしない(問い合わせの途中に打つと、打った名前が消えていた) */
        input.addEventListener('input', function () { input.__touched = true; });
        input.addEventListener('change', function () { input.__touched = true; streamerBadge(input, ''); streamerRemember(input.__ctx, input.value.trim()); });
      }
      if (!token()) return Promise.resolve(null);
      var my = input.__autoSeq = (input.__autoSeq || 0) + 1;
      return yttPost('streamer-guess', input.__ctx).then(function (j) {
        if (my !== input.__autoSeq || input.__touched) return j;
        input.value = j.name || ''; input.__uiStreamer(true);
        streamerBadge(input, j.name ? (j.source === 'auto' ? '自動(チャンネル名から)' : '前回') : (j.source ? '前回: 色なし' : ''));
        return j;
      }, function () { return null; });
    },
    /* 始める前: 欄の名前がメンバーに見つからなければ「色なしで進める」か聞く(S-20。以前は始めたあとでエラー)。-> Promise<名前 | ''(色なし)| null(やめる)> */
    check: function (input) {
      var v = input ? input.value.trim() : '';
      if (!v || !token()) return Promise.resolve(v);
      /* 欄の data-color は照らし合わせの途中(打った直後・描き直した直後)に消えているので、ここで照らし合わせ直す */
      return yttPost('streamer-colors', { q: v }).then(function (j) {
        if (j.match) return v;
        return dialogConfirm({ title: '配信者がメンバーに見つかりません', ok: '色なしで進める',
          body: '「' + v + '」は色の一覧にありません。色なし(黒い文字)で進めますか?(ホロカラーのマイカラーに足すと、その色にできます)' })
          .then(function (ok) { return ok ? '' : null; });
      }, function () { return v; });   // 照らし合わせられないときは、サーバーが始める前に断る
    }
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
  /* v7: ms: 0 = 閉じるまで出す。action: {label, fn} = ボタン1つ(押すと閉じてから fn)。閉じるボタン(×)はいつも。-> {close, el} */
  function toastFn(message, opt) {
    opt = opt || {};
    var kind = opt.kind || '', isErr = kind === 'err';
    var ms = opt.ms === 0 ? 0 : (+opt.ms > 0 ? +opt.ms : (isErr ? 8000 : 2500));
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
    var act = opt.action && opt.action.label && typeof opt.action.fn === 'function' ? opt.action : null;
    if (act) {
      var ab = document.createElement('button');
      ab.type = 'button'; ab.className = 'ui-toast-act'; ab.textContent = String(act.label);
      ab.addEventListener('click', function (e) { e.stopPropagation(); remove(); act.fn(); });
      item.appendChild(ab);
    }
    var xb = document.createElement('button');
    xb.type = 'button'; xb.className = 'ui-toast-x'; xb.setAttribute('aria-label', '知らせを閉じる'); xb.textContent = '×';
    xb.addEventListener('click', function (e) { e.stopPropagation(); remove(); });
    item.appendChild(xb);
    function remove() { clearTimeout(timer); if (item.parentNode) item.parentNode.removeChild(item); }
    var timer = ms > 0 ? setTimeout(remove, ms) : 0;
    item.addEventListener('click', function (e) {
      if (e.target && e.target.closest && e.target.closest('details')) return;   // 「詳しく」の開閉では閉じない
      if (act || ms === 0) return;   // ボタンのある知らせ・消えない知らせは、本文を押しても閉じない(× か ボタンで)
      remove();
    });
    box.appendChild(item);
    return { close: remove, el: item };
  }

  /* ---- confirmTwice(二度押しの確認。v7)---- 1回目でボタンの文字を text に変え、3秒以内のもう1回で run。実行したらすぐ元に戻す
     (以前の3つの実装(スタジオ・コラボ・編集)をまとめた。編集の版は実行後も「確認済み」のままで、続けて押すと同じ操作がもう一度走っていた) */
  function confirmTwice(btn, run, text) {
    if (!btn) return;
    if (btn.getAttribute('data-armed')) {
      clearTimeout(+btn.getAttribute('data-arm-t') || 0);
      btn.removeAttribute('data-armed'); btn.innerHTML = btn.getAttribute('data-label') || ''; btn.classList.remove('armed');
      run(); return;
    }
    btn.setAttribute('data-label', btn.innerHTML); btn.setAttribute('data-armed', '1');
    btn.textContent = text || 'もう一度押すと実行します'; btn.classList.add('armed');
    btn.setAttribute('data-arm-t', String(setTimeout(function () {
      if (btn.isConnected && btn.getAttribute('data-armed')) { btn.removeAttribute('data-armed'); btn.innerHTML = btn.getAttribute('data-label') || ''; btn.classList.remove('armed'); }
    }, 3000)));
  }

  /* ---- prefs(ホームの設定。v7)---- api/ytt/prefs(home/prefs.py)。ホームから開いていない(合言葉なし)ときは available() が false。
     patch は同じ節をまとめて 400ms 後に送る(続けて変えても1回)。失敗したら知らせと [もう一度](以前は空の catch で黙って捨てていた) */
  var prefsPending = {}, prefsTimer = {};
  function prefsFail(section, err) {
    toastFn('設定を保存できませんでした: ' + (err && err.message ? err.message : ''), { kind: 'err', ms: 0,
      action: { label: 'もう一度', fn: function () { prefsFlush(section); } } });
  }
  function prefsFlush(section, value) {
    var v = value || prefsPending[section];
    delete prefsPending[section]; clearTimeout(prefsTimer[section]);
    if (!v) return Promise.resolve(null);
    return yttPost('prefs', { op: 'patch', section: section, value: v }).then(function (j) { return j.value; }, function (e) {
      prefsPending[section] = Object.assign({}, v, prefsPending[section] || {});   /* 失敗した値は残す([もう一度]・次の patch と一緒に送る) */
      prefsFail(section, e);
      throw e;
    });
  }
  var prefs = {
    available: function () { return !!token(); },
    get: function (sections) { return yttPost('prefs', { op: 'get', sections: sections || null }).then(function (j) { return j.prefs || {}; }); },
    patch: function (section, value) {
      prefsPending[section] = Object.assign(prefsPending[section] || {}, value || {});
      clearTimeout(prefsTimer[section]);
      return new Promise(function (resolve, reject) {
        prefsTimer[section] = setTimeout(function () { prefsFlush(section).then(resolve, reject); }, 400);
      });
    },
    flush: function (section) { return prefsFlush(section); },
    remember: function (kind, key, name) {
      return yttPost('prefs', { op: 'remember', kind: kind, key: key, name: name }).then(function (j) { return j.streamer; }, function (e) { prefsFail('streamer', e); throw e; });
    }
  };

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
  /* v9(2026-09-30・全体の計画 段2 監査 11): 設定の保存・読み込みの失敗を出す。UIKit.settings.status(state, message, retry, label)
     state = 'err' のとき、⚙ ボタン([data-ui-settings])に赤い印と title、設定の引き出しの先頭に「message [label(既定: もう一度)]」。
     それ以外('' / null)で消す。retry は押したときに呼ぶ関数(無ければボタンを出さない)。文書の保存の表示とは別の場所 */
  var setStatus = { state: '', message: '', retry: null, label: '' }, setStatusEl = null;
  function paintSettingsStatus() {
    var err = setStatus.state === 'err';
    var btns = document.querySelectorAll('[data-ui-settings]');
    for (var i = 0; i < btns.length; i++) {
      var b = btns[i];
      if (b.__uiSetLabel === undefined) b.__uiSetLabel = b.getAttribute('aria-label');
      if (b.__uiSetTitle === undefined) b.__uiSetTitle = b.getAttribute('title');
      if (err) {
        b.setAttribute('data-ui-status', 'err');
        b.setAttribute('title', setStatus.message);
        b.setAttribute('aria-label', (b.__uiSetLabel || '設定') + '(' + setStatus.message + ')');
      } else {
        b.removeAttribute('data-ui-status');
        if (b.__uiSetTitle === null) b.removeAttribute('title'); else b.setAttribute('title', b.__uiSetTitle);
        if (b.__uiSetLabel === null) b.removeAttribute('aria-label'); else b.setAttribute('aria-label', b.__uiSetLabel);
      }
    }
    if (!setStatusEl) return;
    setStatusEl.hidden = !err;
    setStatusEl.textContent = '';
    if (!err) return;
    var t = document.createElement('span'); t.textContent = setStatus.message; setStatusEl.appendChild(t);
    if (typeof setStatus.retry === 'function') {
      var rb = document.createElement('button'); rb.type = 'button'; rb.className = 'btn small'; rb.textContent = setStatus.label || 'もう一度';
      var fn = setStatus.retry;
      rb.addEventListener('click', function () { rb.disabled = true; try { var r = fn(); if (r && typeof r.then === 'function') r.then(function () { rb.disabled = false; }, function () { rb.disabled = false; }); else rb.disabled = false; } catch (e) { rb.disabled = false; } });
      setStatusEl.appendChild(rb);
    }
  }
  function settingsStatus(state, message, retry, label) {
    setStatus = { state: state === 'err' ? 'err' : '', message: String(message || ''), retry: retry || null, label: label || '' };
    paintSettingsStatus();
  }
  function settingsMount(opts) {
    opts = opts || {};
    var el = buildSettingsDrawer(), body = el.querySelector('#uiSettingsBody');
    body.innerHTML = '';
    if (!setStatusEl) { setStatusEl = document.createElement('div'); setStatusEl.className = 'notice err ui-settings-status'; setStatusEl.setAttribute('role', 'alert'); setStatusEl.hidden = true; }
    body.appendChild(setStatusEl);
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
    paintSettingsStatus();
    return el;
  }
  var settings = { mount: settingsMount, status: settingsStatus, statusOf: function () { return { state: setStatus.state, message: setStatus.message }; } };

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
    return '<div class="ui-krow"><span class="ui-kkeys">' + kbds + '</span><span class="ui-klabel">' + esc(label) + '</span></div>';   /* キー → 説明(各ツールの一覧と同じ順) */
  }
  /* キーの組み合わせの表記(割り当ての保存形式)。'j'・'Shift+j'・'Space'・'Shift+Space'・'ArrowLeft'・','。
     1文字の記号は Shift で文字そのものが変わる('?' など)ので Shift を付けない。英字・Space・名前のあるキー(矢印など)だけ Shift を付ける */
  var KEY_TEXT = { ArrowLeft: '←', ArrowRight: '→', ArrowUp: '↑', ArrowDown: '↓', Space: 'Space', Enter: 'Enter', Tab: 'Tab', Escape: 'Esc', Delete: 'Del', Backspace: 'BS' };
  function comboOf(e) {
    var k = e.key;
    if (!k || k === 'Shift' || k === 'Control' || k === 'Alt' || k === 'Meta' || k === 'Dead' || k === 'Process' || k === 'Unidentified') return '';
    var base, shiftable;
    if (k === ' ' || k === 'Spacebar') { base = 'Space'; shiftable = true; }
    else if (k.length === 1) { base = k.toLowerCase(); shiftable = /[a-z]/i.test(k); }
    else { base = k; shiftable = true; }
    return (e.shiftKey && shiftable ? 'Shift+' : '') + base;
  }
  function keyText(combo) {
    if (!combo) return '未設定';
    return String(combo).split('+').map(function (p) { return KEY_TEXT[p] || (p.length === 1 ? p.toUpperCase() : p); }).join('+');
  }
  /* 共通の再生キーの操作(id → 既定のキー・説明)。画面が keymap を渡せば割り当てを変えられる(編集)。渡さなければ既定のまま(スタジオ) */
  var PLAYBACK_ACTIONS = [
    ['playPause', 'Space', '再生・停止'], ['back1', 'j', '1秒戻る'], ['stop', 'k', '止める'], ['play', 'l', '再生(もう一度で 1.5 → 2 倍)'],
    ['seekBack', 'ArrowLeft', '1秒戻る(Shift で5秒)'], ['seekFwd', 'ArrowRight', '1秒進む(Shift で5秒)'],
    ['frameBack', ',', '1コマ戻る'], ['frameFwd', '.', '1コマ進む'], ['markIn', 'i', '始まりの印'], ['markOut', 'o', '終わりの印']
  ];
  function playbackMap(km) {
    var out = {};
    for (var i = 0; i < PLAYBACK_ACTIONS.length; i++) {
      var id = PLAYBACK_ACTIONS[i][0];
      out[id] = km && typeof km[id] === 'string' ? km[id] : PLAYBACK_ACTIONS[i][1];
    }
    return out;
  }
  function keysHelpHtml(km) {
    var html = '<section class="ui-kgroup"><h3 class="section-title">共通の再生キー</h3>';
    if (!km) {
      var rows = [
        ['Space', '再生・停止'], ['J', '1秒戻る'], ['K', '止める'], ['L', '再生(もう一度で 1.5 → 2 倍)'],
        ['← / →', '1秒(Shift で5秒)'], [', / .', '1コマ(コマ送り)'], ['I / O', '始まり/終わりの印']
      ];
      for (var i = 0; i < rows.length; i++) html += kbdRow(rows[i][0], rows[i][1]);
      return html + '</section>';
    }
    var m = playbackMap(km);
    for (var j = 0; j < PLAYBACK_ACTIONS.length; j++) html += kbdRow(keyText(m[PLAYBACK_ACTIONS[j][0]]), PLAYBACK_ACTIONS[j][2]);
    return html + '</section>';
  }
  /* K・L で戻す速さは、画面の速さの設定(defaultPlaybackRate。編集の「速さ」など)。無ければ 1 倍 */
  function baseRate(media) { var r = +media.defaultPlaybackRate; return r > 0 ? r : 1; }
  /* play() の約束(Promise)の失敗は無視する: 再生の直後に止めると「play() request was interrupted」で失敗するが、止めたかっただけなので問題ない */
  function playQuiet(media) { var p = media.play(); if (p && typeof p.catch === 'function') p.catch(function () { /* 無視 */ }); }
  /* 押しっぱなし(自動の繰り返し)で続けて働いてよい操作 */
  var PLAYBACK_REPEAT = { back1: 1, seekBack: 1, seekFwd: 1, frameBack: 1, frameFwd: 1 };
  function keysPlayback(opts) {
    opts = opts || {};
    return function (e) {
      if (opts.enabled && !opts.enabled()) return false;
      if (e.isComposing || e.keyCode === 229) return false;   // 日本語の変換中は受け取らない(段6)
      if (isTyping(e.target)) return false;
      if (e.ctrlKey || e.altKey || e.metaKey) return false;
      /* media・fps・keymap は関数でもよい(毎回そのとき呼ぶ: 動画の差し替え・読み込み後に決まる fps・設定の変更に対応) */
      var media = typeof opts.media === 'function' ? opts.media() : opts.media;
      var fps = typeof opts.fps === 'function' ? opts.fps() : opts.fps;
      fps = fps > 0 ? fps : 30;
      var km = playbackMap(typeof opts.keymap === 'function' ? opts.keymap() : opts.keymap);
      var combo = comboOf(e); if (!combo) return false;
      var action = null, big = false;
      for (var id in km) if (km[id] && km[id] === combo) { action = id; break; }
      /* ← → に当たる操作は Shift つきで5秒(割り当てたキー + Shift。決まりは derivedKeys の1か所 = キー配置の重なりの検査と同じ) */
      if (!action) { var dv = derivedKeys(km); if (dv[combo]) { action = dv[combo]; big = true; } }
      if (!action) return false;
      if (action === 'playPause' && isSpaceControlTarget(e.target) && (combo === 'Space' || combo === 'Enter')) return false;   // ボタン・チェックなどは Space の既定の動きに任せる
      e.preventDefault();
      if (e.repeat && !PLAYBACK_REPEAT[action]) return true;   // 押しっぱなしで再生・停止などを繰り返さない(ページのスクロールも止める)
      function seek(delta) { if (media) { try { media.currentTime = Math.max(0, (media.currentTime || 0) + delta); } catch (er) { /* まだ読み込めていない */ } } }
      if (action === 'playPause') { if (media) { try { if (media.paused) playQuiet(media); else media.pause(); } catch (er) { /* 無視 */ } } }
      else if (action === 'back1') seek(-1);
      else if (action === 'stop') { if (media) { try { media.pause(); media.playbackRate = baseRate(media); } catch (er) { /* 無視 */ } } }
      else if (action === 'play') {
        if (media) {
          try { if (media.paused) { media.playbackRate = baseRate(media); playQuiet(media); } else media.playbackRate = media.playbackRate >= 1.5 ? 2 : 1.5; } catch (er) { /* 無視 */ }
        }
      }
      else if (action === 'seekBack') seek(big ? -5 : -1);
      else if (action === 'seekFwd') seek(big ? 5 : 1);
      else if (action === 'frameBack' || action === 'frameFwd') {
        var dir = action === 'frameBack' ? -1 : 1, done = false;
        if (typeof opts.onFrame === 'function') done = opts.onFrame(dir) === true;
        if (!done) seek(dir * (1 / fps));
      }
      else if (action === 'markIn') { if (typeof opts.onIn === 'function') opts.onIn(); }
      else if (action === 'markOut') { if (typeof opts.onOut === 'function') opts.onOut(); }
      var name = keyText(combo);
      if (typeof opts.onKey === 'function') opts.onKey(name, action);   // どの操作か(キーの名前は割り当てで変わるので、画面は操作で判断する)
      keybar.flash(name);
      return true;
    };
  }
  /* 派生キー: 共通の再生キーの割り当て(km。足りない所は既定)から、「← → に当たるキー + Shift」(5秒)→ 操作の id。{ 'Shift+ArrowLeft': 'seekBack', … }
     keysPlayback(押したとき)と keymap(登録のときの重なりの検査)が同じこれを使う(段3 3-2 監査 03。派生を増やすときはここだけ) */
  function derivedKeys(km) {
    var m = playbackMap(km), out = {};
    ['seekBack', 'seekFwd'].forEach(function (id) { var d = kmDerived(m[id]); if (d && !out[d]) out[d] = id; });
    return out;
  }
  var keysApi = { isTyping: isTyping, helpHtml: keysHelpHtml, playback: keysPlayback, comboOf: comboOf, keyText: keyText, PLAYBACK_ACTIONS: PLAYBACK_ACTIONS, playbackMap: playbackMap, derived: derivedKeys };

  /* ==== v8(気が利く画面へ 段6): keymap = キーの一覧がそのままキー配置の設定(編集・スタジオで同じ部品。使い方は README.md の「v8」) ====
     ? の一覧と ⚙ の「キー配置」は同じ部品を出す(場所が 2 つでも中身は 1 つ)。キーのボタンを押す → その場で次のキーを待つ
     (Esc = 取り消しだけ・一覧は閉じない / Delete = 外す)。重なったら一覧の中に「「X」から外しました [戻す]」(一覧はモーダルの上なので、知らせは一覧の中に出す)。
     共通の再生キー(PLAYBACK_ACTIONS)はホームの設定 keymap.playback に 1 つ(どのツールで変えても同じ)。ツールのキーは各ツールが保存する。
     重なりの検査はここ 1 か所: 変えられないキー(全ツール)・共通の再生キー・ツールのキー・派生キー(← → に当たるキー + Shift = 5 秒。GPT-03) */
  var PB_IDS = {};
  for (var pbi = 0; pbi < PLAYBACK_ACTIONS.length; pbi++) PB_IDS[PLAYBACK_ACTIONS[pbi][0]] = PLAYBACK_ACTIONS[pbi];
  /* 共通の再生キーにできないキー(どれかのツールで固定の意味がある。再生のキーはどのタブ・ツールでも先に働くので、ツールごとには決められない) */
  var PB_BLOCKED = { ArrowUp: '編集: 前の行', ArrowDown: '編集: 次の行', 'Shift+ArrowUp': '編集: 前の未校正', 'Shift+ArrowDown': '編集: 次の未校正',
    Tab: '入力欄の出入り', 'Shift+Tab': 'フォーカスの移動', Escape: '取り消し・閉じる', Enter: 'ボタンを押す', '?': 'キーの一覧',
    s: '編集 2 カット: 分割', x: '編集 2 カット: I〜O を削る', q: '編集 2 カット: 始まりの端', w: '編集 2 カット: 終わりの端',
    '[': '編集 2 カット: 前の区間', ']': '編集 2 カット: 次の区間', Delete: '編集 2 カット: 削る/戻す', Backspace: '編集 2 カット: 削る/戻す',
    '+': '編集 2 カット: 拡大', '=': '編集 2 カット: 拡大', '-': '編集 2 カット: 縮小', Home: '編集 2 カット: 先頭へ', End: '編集 2 カット: 末尾へ',
    '<': '編集 2 カット: 選んだ端を10コマ戻す(Shift+,)', '>': '編集 2 カット: 選んだ端を10コマ進める(Shift+.)' };   // Shift+, / Shift+. は e.key が < > になる(段3 3-2)
  for (var dgi = 0; dgi <= 9; dgi++) PB_BLOCKED[String(dgi)] = '編集: 話者の番号';
  var KM_COMBO_RE = /^(?:Shift\+)?(?:[^\x00-\x1f\x7f]|[A-Z][A-Za-z0-9]{1,20})$/;   /* home/prefs.py の COMBO_RE と同じ */
  /* ← → に当たるキー + Shift(5 秒)。1文字の記号は Shift で文字そのものが変わるので派生しない(comboOf と同じ決まり) */
  function kmDerived(combo) {
    if (!combo || combo.indexOf('Shift+') === 0) return '';
    if (combo.length === 1 && !/[a-z]/.test(combo)) return '';
    return 'Shift+' + combo;
  }
  /* キーの表記 → <kbd>。'Shift+j' → Shift + J・'+' はそのまま 1 つ */
  function kmKbd(combo) {
    var parts = combo.indexOf('Shift+') === 0 && combo.length > 6 ? ['Shift', combo.slice(6)] : [combo];
    return parts.map(function (p) { return '<kbd class="ui-kbd">' + esc(KEY_TEXT[p] || (p.length === 1 ? p.toUpperCase() : p)) + '</kbd>'; }).join('+');
  }
  /* 一覧に出すだけの表記(変えられないキー・固定の別の手段)。'Ctrl+Shift+Z'・'1…9'・'Shift+↓' など */
  function kmKbdText(text) {
    var t = String(text);
    var parts = t === '+' ? ['+'] : t.split('+');
    return parts.map(function (p) { return '<kbd class="ui-kbd">' + esc(p) + '</kbd>'; }).join('+');
  }
  var kmCap = null, kmEscAt = 0;   /* キーを待っている { km(内部), id, el }(画面に 1 つ)・Esc で取り消した時刻(同じ Esc で一覧が閉じないように) */
  function kmCreate(o) {
    o = o || {};
    var acts = o.actions || [], byId = {}, groups = o.groups || [], fixed = o.fixed || [];
    for (var i = 0; i < acts.length; i++) byId[acts[i].id] = acts[i];
    var self = { tool: {}, pb: {}, prefsPb: null, eff: {}, used: {}, lost: {}, derived: {}, mounts: [], note: null, lastId: null };
    function labelOf(id) { return PB_IDS[id] ? PB_IDS[id][2] : (byId[id] ? byId[id].label : id); }
    function defOf(id) { return PB_IDS[id] ? PB_IDS[id][1] : (byId[id] ? byId[id].def : ''); }
    function toolRefuse(combo) { return typeof o.refuse === 'function' ? (o.refuse(combo) || '') : ''; }
    /* 保存した値 → 今効く割り当て。重なり・使えないキーは外し、理由を lost に残す(一覧のその行に出す)。再生のキーが先(先に処理されるため) */
    function compute() {
      var eff = {}, used = {}, lost = {}, derived = {}, i, id, k, why;
      for (i = 0; i < PLAYBACK_ACTIONS.length; i++) {
        id = PLAYBACK_ACTIONS[i][0]; k = typeof self.pb[id] === 'string' ? self.pb[id] : PLAYBACK_ACTIONS[i][1];
        why = !k ? '' : !KM_COMBO_RE.test(k) ? '形が正しくない' : PB_BLOCKED[k] ? '「' + PB_BLOCKED[k] + '」に使う' : toolRefuse(k) ? '「' + toolRefuse(k) + '」に使う'
          : used[k] ? '「' + labelOf(used[k]) + '」と重なる' : '';
        if (why) { lost[id] = { key: k, why: why }; k = ''; }
        if (k) used[k] = id;
        eff[id] = k;
      }
      var dvk = derivedKeys(eff);   // 外れた(eff が '')再生のキーからは派生しない
      for (k in dvk) if (eff[dvk[k]] && !used[k]) derived[k] = dvk[k];
      for (i = 0; i < acts.length; i++) {
        id = acts[i].id; k = typeof self.tool[id] === 'string' ? self.tool[id].slice(0, 24) : acts[i].def;
        why = !k ? '' : !KM_COMBO_RE.test(k) ? '形が正しくない' : toolRefuse(k) ? '「' + toolRefuse(k) + '」に使う'
          : used[k] ? (PB_IDS[used[k]] ? '共通の再生キー「' + labelOf(used[k]) + '」に使われている' : '「' + labelOf(used[k]) + '」と重なる')
          : derived[k] ? '共通の再生キー「' + labelOf(derived[k]) + '」の Shift つき(5秒)に使われている' : '';
        if (why) { lost[id] = { key: k, why: why }; k = ''; }
        if (k) used[k] = id;
        eff[id] = k;
      }
      self.eff = eff; self.used = used; self.lost = lost; self.derived = derived;
    }
    /* 割り当てられない理由('' = 割り当てられる)。ほかの操作と重なるだけなら割り当てられる(そちらを外して [戻す] を出す) */
    function refusal(id, combo) {
      var K = keyText(combo), r, d;
      if (!KM_COMBO_RE.test(combo)) return K + ' は割り当てられません';
      if (PB_IDS[id]) {
        if ((r = PB_BLOCKED[combo] || toolRefuse(combo))) return K + ' は「' + r + '」に使っているので、共通の再生キーには割り当てられません';
        if ((id === 'seekBack' || id === 'seekFwd') && (d = kmDerived(combo)) && (r = PB_BLOCKED[d] || toolRefuse(d)))
          return K + ' に Shift を足した ' + keyText(d) + '(5秒)が「' + r + '」と重なるので割り当てられません';
        return '';
      }
      if ((r = toolRefuse(combo))) return K + ' は「' + r + '」に使っているので割り当てられません';
      if (self.derived[combo]) return K + ' は共通の再生キー「' + labelOf(self.derived[combo]) + '」に Shift を足した 5 秒の移動に使っているので割り当てられません';
      return '';
    }
    function fullPb(pb) {
      var out = {};
      for (var i = 0; i < PLAYBACK_ACTIONS.length; i++) { var id = PLAYBACK_ACTIONS[i][0]; out[id] = typeof pb[id] === 'string' ? pb[id] : PLAYBACK_ACTIONS[i][1]; }
      return out;
    }
    function fullTool(tool) {
      var out = {};
      for (var i = 0; i < acts.length; i++) { var id = acts[i].id; out[id] = typeof tool[id] === 'string' ? tool[id] : acts[i].def; }
      return out;
    }
    function copy(x) { var out = {}; for (var k in x) if (Object.prototype.hasOwnProperty.call(x, k)) out[k] = x[k]; return out; }
    function savePb() {
      var full = fullPb(self.pb);
      if (prefs.available()) { self.prefsPb = full; prefs.patch('keymap', { playback: full }).catch(function () { /* 失敗の知らせは prefs が出す */ }); }
      else if (o.fallbackPlayback && typeof o.fallbackPlayback.save === 'function') o.fallbackPlayback.save(full);
    }
    function commit(tool, pb, before, msg, kind) {
      var toolChanged = JSON.stringify(tool) !== JSON.stringify(self.tool), pbChanged = JSON.stringify(pb) !== JSON.stringify(self.pb);
      self.tool = tool; self.pb = pb; compute();
      if (toolChanged && typeof o.save === 'function') o.save(fullTool(self.tool));
      if (pbChanged) savePb();
      self.note = msg ? { text: msg, kind: kind || '', undo: before } : null;
      paint(); changed();
    }
    function snapshot() { return { tool: copy(self.tool), pb: copy(self.pb) }; }
    function set(id, combo, msg) {
      if (!PB_IDS[id] && !byId[id]) return false;
      combo = combo || '';
      if (combo) { var why = refusal(id, combo); if (why) { say(why, 'warn'); return false; } }
      var before = snapshot(), tool = copy(self.tool), pb = copy(self.pb), taken = [], takenD = [], k;
      if (combo) {
        for (k in self.eff) if (k !== id && self.eff[k] === combo) {
          if (PB_IDS[k]) { pb[k] = ''; taken.push('「' + labelOf(k) + '」(共通の再生キー。スタジオ・編集とも)'); } else { tool[k] = ''; taken.push('「' + labelOf(k) + '」'); }
        }
        var d = (id === 'seekBack' || id === 'seekFwd') ? kmDerived(combo) : '';
        if (d) for (k in self.eff) if (byId[k] && self.eff[k] === d) { tool[k] = ''; takenD.push('「' + labelOf(k) + '」'); }   // Shift つき(5 秒)に使うキーを持っていた操作
      }
      (PB_IDS[id] ? pb : tool)[id] = combo;
      self.lastId = id;
      var lostMsg = [taken.length ? taken.join('・') + 'から ' + keyText(combo) + ' を外しました' : '',
        takenD.length ? takenD.join('・') + 'から ' + keyText(d) + '(' + keyText(combo) + ' + Shift = 5秒に使う)を外しました' : ''].filter(Boolean).join('。');
      commit(tool, pb, before, msg || (lostMsg ? lostMsg + '(未設定になりました)'
        : combo ? '「' + labelOf(id) + '」を ' + keyText(combo) + ' にしました' : '「' + labelOf(id) + '」のキーを外しました'), lostMsg ? 'warn' : '');
      return true;
    }
    function undo() {
      var n = self.note; if (!n || !n.undo) return;
      commit(n.undo.tool, n.undo.pb, null, 'もとに戻しました', '');
    }
    function say(text, kind, keepCap) {
      if (!keepCap && kmCap && kmCap.km === self) kmCap = null;
      self.note = { text: text, kind: kind || '', undo: null, capWarn: !!keepCap };   // 待っている間の注意は、案内の代わりに出す(待つのは続ける)
      paint();
    }
    function changed() { if (typeof o.onChange === 'function') { try { o.onChange(); } catch (e) { report(e && e.message ? e.message : String(e), { where: 'keymap.onChange' }, 'report'); } } }
    function anyCustom() {
      for (var id in self.eff) if ((self.eff[id] || '') !== (defOf(id) || '')) return true;
      return false;
    }
    function rowHtml(id, label, alt, extra) {
      var k = self.eff[id], cap = kmCap && kmCap.km === self && kmCap.id === id, def = defOf(id), lost = self.lost[id];
      var btn = '<button type="button" class="ui-km-key' + (k ? '' : ' none') + (cap ? ' cap' : '') + '" data-km="' + esc(id) + '" aria-label="' +
        esc(label + ' のキー: ' + (k ? keyText(k) : '未設定') + '(押して変える)') + '"' + (cap ? ' aria-pressed="true"' : '') + '>' +
        (cap ? 'キーを押す…' : k ? kmKbd(k) : '未設定') + '</button>';
      var alts = alt ? '<span class="muted">/</span>' + kmKbdText(alt) : '';
      var std = (k || '') !== (def || '') ? '<button type="button" class="btn small ghost ui-km-def" data-km-def="' + esc(id) + '" title="' + esc('標準の ' + (def ? keyText(def) : '未設定') + ' に戻す') +
        '" aria-label="' + esc(label + ' を標準の ' + (def ? keyText(def) : '未設定') + ' に戻す') + '">標準</button>' : '';
      return '<div class="ui-krow ui-km-row" data-km-row="' + esc(id) + '"><span class="ui-kkeys">' + btn + alts + '</span><span class="ui-klabel">' + esc(label) +
        (lost ? '<small class="ui-km-lost">' + esc(keyText(lost.key) + ' は' + lost.why + 'ので外れています') + '</small>' : '') + '</span>' + (extra || '') + std + '</div>';
    }
    function fixedRow(r) {
      var keys = String(r[0]).split(' / ').map(kmKbdText).join('<span class="muted">/</span>'), why = r[2] || o.fixedWhy || '';
      return '<div class="ui-krow ui-km-fixed"><span class="ui-kkeys">' + keys + '</span><span class="ui-klabel">' + esc(r[1]) + '</span>' +
        (why ? '<span class="ui-km-lock" role="img" aria-label="' + esc('変えられません: ' + why) + '" title="' + esc('変えられません: ' + why) + '">' + icon('lock', { size: 13 }) + '</span>' : '') + '</div>';
    }
    function section(title, note, body) {
      return body ? '<section class="ui-kgroup"><h3 class="section-title">' + esc(title) + (note ? ' <span class="hint">' + esc(note) + '</span>' : '') + '</h3>' + body + '</section>' : '';
    }
    function bodyHtml() {
      var extra = typeof o.extra === 'function' ? o.extra : function () { return ''; }, html = o.intro ? '<p class="hint ui-km-intro">' + esc(o.intro) + '</p>' : '', rows = '', i, j;
      html += '<div class="ui-kgrid ui-km-grid">';
      for (i = 0; i < PLAYBACK_ACTIONS.length; i++) rows += rowHtml(PLAYBACK_ACTIONS[i][0], PLAYBACK_ACTIONS[i][2], null, extra(PLAYBACK_ACTIONS[i][0]));
      html += section('共通の再生キー', o.playbackNote || '(スタジオ・編集で同じ)', rows);
      for (i = 0; i < groups.length; i++) {
        rows = '';
        for (j = 0; j < acts.length; j++) if (acts[j].group === groups[i][0]) rows += rowHtml(acts[j].id, acts[j].label, acts[j].alt, extra(acts[j].id));
        for (j = 0; j < fixed.length; j++) if (fixed[j].group === groups[i][0]) rows += fixed[j].rows.map(function (r) { return fixedRow([r[0], r[1], r[2] || fixed[j].why]); }).join('');
        html += section(groups[i][1], '', rows);
      }
      for (j = 0; j < fixed.length; j++) if (!fixed[j].group) html += section(fixed[j].title, fixed[j].note || '', fixed[j].rows.map(function (r) { return fixedRow([r[0], r[1], r[2] || fixed[j].why]); }).join(''));
      html += '</div><div class="ui-km-foot"><button type="button" class="btn small" data-km-reset' + (anyCustom() ? '' : ' disabled title="すべて標準のままです"') + '>すべて標準に戻す</button>' +
        (o.footNote ? '<span class="hint">' + esc(o.footNote) + '</span>' : '') + '</div>';
      return html;
    }
    function noteHtml() {
      var n = self.note, cap = kmCap && kmCap.km === self ? kmCap : null;
      if (cap && !(n && n.capWarn)) return esc('「' + labelOf(cap.id) + '」に割り当てるキーを押してください(Esc で取り消し・Delete で外す)');
      if (!n) return '';
      return esc(n.text) + (n.undo ? ' <button type="button" class="btn small" data-km-undo>戻す</button>' : '');
    }
    function paint() {
      for (var i = 0; i < self.mounts.length; i++) {
        var el = self.mounts[i], a = document.activeElement, had = !!(a && el.contains(a));
        var fid = had ? (a.getAttribute('data-km') || a.getAttribute('data-km-def') || self.lastId) : null;
        var note = el.querySelector('.ui-km-note'), body = el.querySelector('.ui-km-body');
        var n = self.note, cap = kmCap && kmCap.km === self;
        note.className = 'ui-km-note' + (n && n.kind && !(cap && !n.capWarn) ? ' ' + n.kind : '') + (cap ? ' cap' : '');
        note.innerHTML = noteHtml();
        body.innerHTML = bodyHtml();
        if (had && !el.contains(document.activeElement)) {
          var f = (fid && el.querySelector('[data-km="' + fid + '"]')) || el.querySelector('[data-km]');
          if (f) f.focus({ preventScroll: true });
        }
      }
    }
    function startCap(id, el) {
      kmCap = { km: self, id: id, el: el }; self.note = null;
      paint();
      var b = el.querySelector('[data-km="' + id + '"]'); if (b) b.focus({ preventScroll: true });
    }
    function stopCap() { if (kmCap && kmCap.km === self) { kmCap = null; paint(); } }
    function mount(el) {
      if (!el || el.__km) return;
      el.__km = true;
      el.classList.add('ui-km');
      el.innerHTML = '<p class="ui-km-note" role="status" aria-live="polite"></p><div class="ui-km-body"></div>';
      self.mounts.push(el);
      el.addEventListener('click', function (e) {
        var t = e.target && e.target.closest ? e.target.closest('[data-km],[data-km-def],[data-km-undo],[data-km-reset]') : null;
        if (!t || !el.contains(t) || t.disabled) return;
        if (t.hasAttribute('data-km')) startCap(t.getAttribute('data-km'), el);
        else if (t.hasAttribute('data-km-def')) { var id = t.getAttribute('data-km-def'); kmCap = null; set(id, defOf(id), '「' + labelOf(id) + '」を標準の ' + (defOf(id) ? keyText(defOf(id)) : '未設定') + ' に戻しました'); }
        else if (t.hasAttribute('data-km-undo')) undo();
        else if (t.hasAttribute('data-km-reset')) { kmCap = null; commit({}, {}, snapshot(), 'すべて標準に戻しました', ''); }
      });
      el.addEventListener('focusout', function () {   /* 別の所を押したら取り消し(キーを押したときは下の keydown が先に受ける) */
        if (!kmCap || kmCap.km !== self) return;
        setTimeout(function () { var a = document.activeElement; if (kmCap && kmCap.km === self && !(a && a.classList && a.classList.contains('cap'))) stopCap(); }, 0);
      });
      paint();
    }
    /* 共通の再生キーの読み込み: ホームの設定(入口の中)。初回は、ツールに保存していた再生キー(編集の settings.keymap)をホームの設定へ移す */
    function syncPb() {
      var fb = o.fallbackPlayback && typeof o.fallbackPlayback.load === 'function' ? (o.fallbackPlayback.load() || {}) : {};
      if (!prefs.available() || self.prefsPb === null) { self.pb = copy(fb); return; }
      var empty = true, custom = false, k;
      for (k in self.prefsPb) { empty = false; break; }
      for (k in PB_IDS) if (typeof fb[k] === 'string' && fb[k] !== PB_IDS[k][1]) custom = true;
      if (empty && custom) { var pb = {}; for (k in PB_IDS) if (typeof fb[k] === 'string') pb[k] = fb[k]; self.pb = pb; savePb(); return; }
      self.pb = copy(self.prefsPb);
    }
    function loadPrefs() {
      if (!prefs.available()) return;
      prefs.get(['keymap']).then(function (p) {
        var pb = p && p.keymap && p.keymap.playback;
        self.prefsPb = pb && typeof pb === 'object' ? pb : {};
        var was = JSON.stringify(self.eff);
        syncPb(); compute();
        if (JSON.stringify(self.eff) !== was) { paint(); changed(); }
      }, function () { /* 読めなければ今の割り当てのまま */ });
    }
    function reload() {
      self.tool = typeof o.load === 'function' ? copy(o.load() || {}) : {};
      syncPb(); compute(); paint(); changed();
    }
    self.tool = typeof o.load === 'function' ? copy(o.load() || {}) : {};
    syncPb(); compute(); loadPrefs();
    life.onReturn(loadPrefs);   /* 別の窓(スタジオ・編集)で変えた共通の再生キーを、戻ったときに読み直す */
    var api = {
      /* 今効く割り当て { 操作の id: キー }(共通の再生キーを含む。UIKit.keys.playback の keymap にそのまま渡せる) */
      map: function () { return self.eff; },
      key: function (id) { return self.eff[id] || ''; },
      text: function (id) { return self.eff[id] ? keyText(self.eff[id]) : ''; },
      /* キー(comboOf の表記)→ このツールの操作の id か null */
      actionOf: function (combo) { if (!combo) return null; var id = self.used[combo]; return id && byId[id] ? id : null; },
      mount: mount, reload: reload, refusal: refusal,
      set: function (id, combo) { return set(id, combo); },
      /* ツールのキーをまとめて(スタジオのプリセット)。[戻す] つき */
      setMany: function (map, msg) { kmCap = null; commit(copy(map || {}), copy(self.pb), snapshot(), msg || 'キー配置を変えました', ''); },
      clearNote: function () { if (kmCap && kmCap.km === self) kmCap = null; self.note = null; paint(); },
      capturing: function () { return !!(kmCap && kmCap.km === self); }
    };
    self.api = api; self.say = say; self.set = set; self.refusal = refusal;
    return api;
  }
  /* キーを待っている間は、どのキーも「割り当てるキー」として受け取る(捕捉の段階で受けて、ほかの処理 = 一覧・引き出しの Esc・再生のキーなどに渡さない) */
  window.addEventListener('keydown', function (e) {
    var c = kmCap; if (!c) return;
    if (e.isComposing || e.keyCode === 229) return;   // 日本語の変換中は受け取らない
    e.preventDefault(); e.stopImmediatePropagation();
    if (e.repeat) return;
    var km = c.km;
    if (e.key === 'Escape') { kmCap = null; kmEscAt = Date.now(); km.say('取り消しました(キーは変わっていません)', ''); return; }
    if (e.key === 'Delete' || e.key === 'Backspace') { kmCap = null; km.set(c.id, ''); return; }
    if (e.ctrlKey || e.metaKey || e.altKey) {
      if (e.key !== 'Control' && e.key !== 'Alt' && e.key !== 'Meta') { km.say('Ctrl・Alt つきのキーは割り当てられません(ブラウザ・タブの切り替えと重なるため)。別のキーを押してください', 'warn', true); }
      return;
    }
    var combo = comboOf(e); if (!combo) return;   // Shift だけを押した段階は、次のキーを待つ
    var why = km.refusal(c.id, combo);
    if (why) { km.say(why + '。別のキーを押すか、Esc で取り消してください', 'warn', true); return; }
    kmCap = null; km.set(c.id, combo);
  }, true);
  document.addEventListener('cancel', function (e) { if (kmCap || Date.now() - kmEscAt < 400) e.preventDefault(); }, true);   // キーを待っている間の Esc で一覧(dialog)を閉じない
  var keymapApi = { create: kmCreate, capturing: function () { return !!kmCap; }, BLOCKED: PB_BLOCKED };

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
    lock: '<rect x="5" y="11" width="14" height="9" rx="2"/><path d="M8 11V8a4 4 0 0 1 8 0v3"/>',
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

  /* ---- packLoud(パックの音量のそろえ方。v7・2026-09-29)---- 値は編集の設定 packLoudness の1か所(パックのタブ・まとめて実行のパックと同じ)。
     どの画面のまとめて実行の欄からも同じ値を読み書きする: 読む = 編集の api/settings、直す = api/settings/patch(送ったキーだけ。
     編集の画面の丸ごとの保存では、この値はサーバーのものが残る)。編集が同じ入口に取り込まれていないとき(paths に無い)は欄を隠す */
  var LOUD_OPTS = [[-14, '-14 LUFS(YouTube と同じくらい・おすすめ)'], [-11, '-11 LUFS(大きめ)'], [-16, '-16 LUFS(少し小さめ)'], [-18, '-18 LUFS(小さめ)'], [0, '音量を % で決める']];
  var loudGet = null;
  function txApiUrl(p) { var b = tools.paths && tools.paths.transcribe; return b ? b + p : ''; }
  function loudNorm(raw) {
    if (raw === undefined || raw === null || raw === '') return 0;   // 既定はそろえない = 音量 30%(2026-10-01)
    var v = +raw;
    return v === 0 ? 0 : (v === -11 || v === -14 || v === -16 || v === -18) ? v : -14;
  }
  function volNorm(raw) { var v = Math.round(+raw); return v >= 1 && v <= 200 ? v : 30; }
  /* 値 {loud: LUFS か 0(= % で決める), vol: %(元 = 100)} を、画面のすべての欄に反映して知らせる */
  function loudPaint(st) {
    var els = document.querySelectorAll('select[data-ui-packloud]');
    for (var i = 0; i < els.length; i++) {
      if (document.activeElement !== els[i]) els[i].value = String(st.loud);
      var vi = els[i].parentNode && els[i].parentNode.querySelector('input[data-ui-packvol]');
      if (vi) { if (document.activeElement !== vi) vi.value = String(st.vol); vi.parentNode.hidden = st.loud !== 0; }   /* vi の親 = % の欄(span.ui-packvol) */
    }
    try { document.dispatchEvent(new CustomEvent('ui-packloud', { detail: st })); } catch (e) { /* 古いブラウザ: 知らせないだけ */ }
  }
  var loudMounted = [];
  function loudWrap(sel) { return sel.closest ? (sel.closest('label') || sel) : sel; }
  function loudRefresh() {
    loudMounted = loudMounted.filter(function (sel) { return sel.isConnected; });
    if (!loudMounted.length) return;
    var ok = !!(txApiUrl('api/settings') && token());
    for (var i = 0; i < loudMounted.length; i++) loudWrap(loudMounted[i]).hidden = !ok;
    if (ok) packLoud.get().then(function (st) { loudPaint(st); }, function () { for (var j = 0; j < loudMounted.length; j++) loudWrap(loudMounted[j]).hidden = true; });
  }
  var packLoud = {
    norm: loudNorm,
    get: function () {
      var u = txApiUrl('api/settings');
      if (!u || !window.fetch) return Promise.reject(new Error('編集が動いていません'));
      if (!loudGet) {
        loudGet = fetch(u, { cache: 'no-store', credentials: 'same-origin' }).then(function (r) { return r.json(); })
          .then(function (j) { return { loud: loudNorm(j.packLoudness), vol: volNorm(j.packVolume) }; });
        loudGet.then(function () { setTimeout(function () { loudGet = null; }, 3000); }, function () { loudGet = null; });   /* 続けて読むときは1回に */
      }
      return loudGet;
    },
    /* values: {packLoudness?, packVolume?}(送った方だけ直す) */
    set: function (values) {
      var u = txApiUrl('api/settings/patch'), tk = token(), v = {};
      if ('packLoudness' in values) v.packLoudness = loudNorm(values.packLoudness);
      if ('packVolume' in values) v.packVolume = volNorm(values.packVolume);
      if (!u || !window.fetch) return Promise.reject(new Error('編集が動いていません'));
      return fetch(u, { method: 'POST', cache: 'no-store', credentials: 'same-origin',
        headers: { 'Content-Type': 'application/json', 'X-YTT-Token': tk }, body: JSON.stringify({ values: v }) })
        .then(function (r) { return r.json().catch(function () { return {}; }).then(function (j) { if (!r.ok) throw new Error(j.message || ('HTTP ' + r.status)); }); })
        .then(function () { loudGet = null; return packLoud.get(); })
        .then(function (st) { loudPaint(st); return st; }, function (e) {
          toastFn('パックの音量を保存できませんでした: ' + e.message, { kind: 'err', ms: 0, action: { label: 'もう一度', fn: function () { packLoud.set(values); } } });
          throw e;
        });
    },
    /* <select data-ui-packloud> を選択の欄にする(選択肢と「%」の欄を入れ・今の値を読み・変えたら保存)。使えなければ、欄を包む label ごと隠す */
    mount: function (sel) {
      if (!sel || sel.getAttribute('data-ui-packloud-on')) return;
      sel.setAttribute('data-ui-packloud', ''); sel.setAttribute('data-ui-packloud-on', '1');
      sel.title = sel.title || 'パックに入れる動画の音量(パックのタブと同じ設定)。LUFS = 聞こえ方の大きさ(数字が小さいほど小さい音)。% = 元の音量を 100 としたときの大きさ';
      sel.innerHTML = '';
      for (var i = 0; i < LOUD_OPTS.length; i++) { var o = document.createElement('option'); o.value = String(LOUD_OPTS[i][0]); o.textContent = LOUD_OPTS[i][1]; sel.appendChild(o); }
      var box = document.createElement('span'); box.className = 'ui-packvol'; box.hidden = true;
      var vi = document.createElement('input'); vi.type = 'number'; vi.min = '1'; vi.max = '200'; vi.step = '5'; vi.style.width = '4.5em';
      vi.setAttribute('data-ui-packvol', ''); vi.setAttribute('aria-label', '音量(%。元の音量 = 100)'); vi.title = '元の音量を 100 としたときの大きさ(%)。小さくするなら 100 より下';
      box.appendChild(vi); box.appendChild(document.createTextNode('%'));
      sel.parentNode.insertBefore(box, sel.nextSibling);
      sel.addEventListener('change', function () { box.hidden = sel.value !== '0'; packLoud.set({ packLoudness: sel.value }).catch(function () {}); });
      vi.addEventListener('change', function () { packLoud.set({ packVolume: vi.value }).catch(function () {}); });
      loudMounted.push(sel);
      loudRefresh();   /* 編集の場所がまだ分からなければ隠しておき、setPaths のときに出す */
    }
  };

  /* ---- autorun(まとめて実行の部品。v7・気が利く画面へ 段4)----
     どの入口(ホームの案件・紐づかない文書・スタジオ ①/③・編集の題名の行・履歴)でも、同じ設定の要約1行 +「設定を変える」+ 始める前の見積もり +
     終わったときの知らせ(ボタンつき)。値は1か所: まとめて実行の形・採用数・カットの方法・上書き・失敗したとき = ホームの設定 autorun(UIKit.prefs)、
     パックの出力(fps・縦横・話者の色・予備・音量)= 編集の設定(3 パック のタブと同じ。送ったキーだけ直す api/settings/patch)。
     状態の言葉もここ(サーバーの stateLabel が正。無いときの予備) */
  var AR_STEP = { wait: '待ち', run: '実行中', done: '済み', skip: '飛ばした', warn: '一部失敗', error: '失敗' };
  var AR_RUN = { queued: '待ち', running: '実行中', done: '済み', error: '失敗', cancelled: '中止', nothing: 'やることがありませんでした' };
  var AR_MODES = { adopted: '採用後を全部', transcribe: '文字起こしまで', full: '解析から全部' };
  var AR_CUT = { rows: '行から', none: 'カットしない', silence: '無音で削る' };
  var arSeq = 0, arPanels = [], arWatched = {}, arTimer = 0, arState = null;
  function arHomeApi(path, body) {
    var init = { cache: 'no-store', credentials: 'same-origin', method: body === undefined ? 'GET' : 'POST' };
    if (body !== undefined) { init.headers = { 'Content-Type': 'application/json', 'X-YTT-Token': token() }; init.body = JSON.stringify(body); }
    return fetch(new URL('../' + path, location.href).href, init).then(function (r) {
      return r.json().catch(function () { return {}; }).then(function (j) { if (!r.ok) { var e = new Error(j.message || ('HTTP ' + r.status)); e.code = j.error; throw e; } return j; });
    });
  }
  function arLoad() {
    var pr = prefs.available() ? prefs.get(['autorun']).then(function (p) { return p.autorun || {}; }, function () { return {}; }) : Promise.resolve({});
    var u = txApiUrl('api/settings');
    var tx = u ? fetch(u, { cache: 'no-store', credentials: 'same-origin' }).then(function (r) { return r.json(); }).catch(function () { return {}; }) : Promise.resolve({});
    return Promise.all([pr, tx]).then(function (x) {
      var a = x[0], t = x[1] || {};
      arState = { mode: a.mode || null, top: +a.top || 3, cut: AR_CUT[a.cut] ? a.cut : 'rows', overwrite: a.overwrite === true, onFail: a.onFail === 'stop' ? 'stop' : 'next',
                  fps: String(t.packFps || '30'), size: t.packSize === '1920x1080' ? '1920x1080' : '1080x1920', spk: t.speakerColors !== false, backup: t.packBackup === true,
                  loud: loudNorm(t.packLoudness), vol: volNorm(t.packVolume), pack: !!u };
      return arState;
    });
  }
  function arSummary(st, kind) {
    if (!st) return '';
    var bits = [];
    if (kind === 'video' && st.mode) bits.push(AR_MODES[st.mode]);
    if (kind === 'new' || (kind === 'video' && st.mode === 'full')) bits.push('採用 ' + st.top);
    bits.push(AR_CUT[st.cut]);
    if (st.pack) {
      bits.push(st.fps + 'fps ' + (st.size === '1920x1080' ? '横' : '縦'));
      bits.push(st.spk ? '話者の色あり' : '話者の色なし');
      bits.push(st.loud ? '音量 ' + st.loud + ' LUFS' : '音量 ' + st.vol + '%');
      if (st.backup) bits.push('予備あり');
    }
    bits.push(st.overwrite ? 'パックがあれば作り直す' : 'パックがあれば飛ばす');
    bits.push(st.onFail === 'stop' ? '失敗したら止める' : '失敗したら次へ');
    return bits.join(' ・ ');
  }
  function arRepaint() {
    arPanels = arPanels.filter(function (p) { return p.el.isConnected; });
    for (var i = 0; i < arPanels.length; i++) arPanels[i].paint();
  }
  function arSave(where, values) {
    var done = where === 'prefs' ? prefs.patch('autorun', values)   /* ホームの設定(失敗は UIKit.prefs が知らせる) */
      : fetch(txApiUrl('api/settings/patch'), { method: 'POST', cache: 'no-store', credentials: 'same-origin',
          headers: { 'Content-Type': 'application/json', 'X-YTT-Token': token() }, body: JSON.stringify({ values: values }) })
        .then(function (r) { if (!r.ok) return r.json().catch(function () { return {}; }).then(function (j) { throw new Error(j.message || ('HTTP ' + r.status)); }); });
    return done.then(function () { return arLoad(); }).then(function () { arRepaint(); try { document.dispatchEvent(new CustomEvent('ui-autorun-settings', { detail: arState })); } catch (e) {} },
      function (e) { if (where !== 'prefs') toastFn('パックの設定を保存できませんでした: ' + e.message, { kind: 'err', ms: 0 }); });
  }
  function arEl(tag, attrs, text) {
    var el = document.createElement(tag);
    for (var k in attrs) if (Object.prototype.hasOwnProperty.call(attrs, k)) el.setAttribute(k, attrs[k]);
    if (text != null) el.textContent = text;
    return el;
  }
  function arSelect(opts, value) {
    var s = arEl('select');
    for (var i = 0; i < opts.length; i++) { var o = arEl('option', { value: opts[i][0] }, opts[i][1]); s.appendChild(o); }
    s.value = String(value);
    return s;
  }
  function arField(label, control, hint) {
    var f = arEl('label', { 'class': 'ui-ar-f' });
    f.appendChild(arEl('span', { 'class': 'ui-ar-l' }, label));
    f.appendChild(control);
    if (hint) f.appendChild(arEl('span', { 'class': 'ui-ar-h' }, hint));
    return f;
  }
  /* 設定の欄(ポップオーバーの中身)。値を変えたらすぐ保存(どこで変えても全部の入口の既定) */
  function arForm(kind, opts) {
    var st = arState, box = arEl('div', { 'class': 'ui-ar-form' });
    if (kind === 'video' && opts.modes) {
      var m = arSelect(opts.modes.map(function (k) { return [k, AR_MODES[k]]; }), st.mode || opts.modes[0]);
      m.addEventListener('change', function () { arSave('prefs', { mode: m.value }); });
      box.appendChild(arField('形', m));
    }
    if (kind === 'new' || (kind === 'video' && (!opts.modes || opts.modes.indexOf('full') >= 0))) {
      var t = arEl('input', { type: 'number', min: '1', max: '20', step: '1' }); t.value = String(st.top); t.style.width = '5em';
      t.addEventListener('change', function () { var n = Math.round(+t.value); if (n >= 1 && n <= 20) arSave('prefs', { top: n }); });
      box.appendChild(arField('採用する数(解析から全部)', t));
    }
    var c = arSelect([['rows', '行から(文字起こしの行を残す)'], ['none', 'カットしない(動画全体)'], ['silence', '無音で削る']], st.cut);
    c.addEventListener('change', function () { arSave('prefs', { cut: c.value }); });
    box.appendChild(arField('カットの方法', c, 'カットを決めてある文書は、そのカットのとおり。細かい値は「編集」の 2 カット で'));
    if (st.pack) {
      var fps = arSelect([['30', '30 fps'], ['60', '60 fps'], ['24', '24 fps'], ['25', '25 fps'], ['50', '50 fps']], st.fps);
      fps.addEventListener('change', function () { arSave('tx', { packFps: fps.value }); });
      var size = arSelect([['1080x1920', '縦 1080×1920'], ['1920x1080', '横 1920×1080']], st.size);
      size.addEventListener('change', function () { arSave('tx', { packSize: size.value }); });
      box.appendChild(arField('パックの置き先', fps));
      box.appendChild(arField('画面の大きさ', size));
      var loud = arEl('select');
      var lf = arField('パックの音量', loud); box.appendChild(lf);
      packLoud.mount(loud);
      var spk = arEl('input', { type: 'checkbox' }); spk.checked = st.spk;
      spk.addEventListener('change', function () { arSave('tx', { speakerColors: spk.checked }); });
      var sl = arEl('label', { 'class': 'ui-ar-c' }); sl.appendChild(spk); sl.appendChild(document.createTextNode('話者の名前がメンバーと合えば、その話者の字幕をその色に'));
      box.appendChild(sl);
      var bk = arEl('input', { type: 'checkbox' }); bk.checked = st.backup;
      bk.addEventListener('change', function () { arSave('tx', { packBackup: bk.checked }); });
      var bl = arEl('label', { 'class': 'ui-ar-c' }); bl.appendChild(bk); bl.appendChild(document.createTextNode('予備も入れる(EDL・SRT)'));
      box.appendChild(bl);
    } else {
      box.appendChild(arEl('p', { 'class': 'ui-ar-h' }, 'パックの出力(fps・縦横・話者の色・音量)は、「編集」が動いていると ここでも変えられます'));
    }
    var ow = arEl('input', { type: 'checkbox' }); ow.checked = st.overwrite;
    ow.addEventListener('change', function () { arSave('prefs', { overwrite: ow.checked }); });
    var ol = arEl('label', { 'class': 'ui-ar-c' }); ol.appendChild(ow); ol.appendChild(document.createTextNode('パックがあれば作り直す(上書き)'));
    box.appendChild(ol);
    var of = arSelect([['next', '残りを続ける'], ['stop', 'そこで止める']], st.onFail);
    of.addEventListener('change', function () { arSave('prefs', { onFail: of.value }); });
    box.appendChild(arField('1本が失敗したとき', of));
    return box;
  }
  function arEstimateText(e) {
    if (!e || !e.steps) return '';
    return e.steps.map(function (s) { return s.label + ' ' + (s.count == null ? 'あとで決まる' : s.count + ' 本'); }).join(' → ');
  }
  function arDocHref(run) {
    var b = tools.paths && tools.paths.transcribe;
    if (!b) return '';
    var id = run.docId || (run.docs && run.docs[0]);   /* 文書の実行はその文書・配信の実行は最初に文字起こし・パックした文書 */
    return id ? b + '?doc=' + encodeURIComponent(id) + '#tx' : b + '#tx';
  }
  function arOpen(href) { if (href) location.href = href; }   /* 同じ窓で移る(窓・画面を増やさない。S-15) */
  function arFinished(run, again) {
    var title = run.title ? '「' + run.title + '」' : '';
    if (run.state === 'cancelled') return;
    if (run.state === 'error') {
      toastFn(title + 'のまとめて実行が止まりました: ' + (run.error || ''), { kind: 'err', ms: 0,
        action: again ? { label: 'やり直す', fn: again } : null });
      return;
    }
    if (run.nothing) { toastFn(title + (title ? ': ' : '') + (run.message || AR_RUN.nothing), { kind: 'info', ms: 8000 }); return; }
    var pk = null, warn = false;
    for (var i = 0; i < (run.steps || []).length; i++) { if (run.steps[i].key === 'pack') pk = run.steps[i]; if (run.steps[i].state === 'warn') warn = true; }
    var msg = title + 'のまとめて実行が終わりました' + (pk && pk.detail ? '(' + pk.detail.split('。')[0] + ')' : '') + (warn ? '。一部失敗しました(詳しくは進み具合の欄)' : '');
    var href = arDocHref(run);
    toastFn(msg, { kind: warn ? 'info' : 'ok', ms: 0, action: href ? { label: '校正を始める', fn: function () { arOpen(href); } } : null });
  }
  function arPoll() {
    arTimer = 0;
    var ids = Object.keys(arWatched);
    if (!ids.length) return;
    arHomeApi('api/autorun').then(function (j) {
      var runs = j.runs || [];
      for (var i = 0; i < ids.length; i++) {
        var r = null;
        for (var k = 0; k < runs.length; k++) if (runs[k].id === ids[i]) r = runs[k];
        if (!r) { delete arWatched[ids[i]]; continue; }
        if (r.state !== 'queued' && r.state !== 'running') { var again = arWatched[ids[i]]; delete arWatched[ids[i]]; arFinished(r, again); }
      }
    }).catch(function () {}).then(function () { if (Object.keys(arWatched).length) arTimer = setTimeout(arPoll, 2500); });
  }
  var autorun = {
    STEP: AR_STEP, RUN: AR_RUN, MODES: AR_MODES, CUT: AR_CUT,
    stepLabel: function (s) { return (s && s.stateLabel) || AR_STEP[s && s.state] || (s && s.state) || ''; },
    runLabel: function (r) { return (r && r.stateLabel) || AR_RUN[r && r.nothing && r.state === 'done' ? 'nothing' : r && r.state] || (r && r.state) || ''; },
    load: arLoad,
    state: function () { return arState; },
    summary: arSummary,
    /* el に「要約1行 +『設定を変える』」を描く。opts: {kind: 'video'|'docs'|'new', modes: ['adopted', …](形を選ばせるとき)} */
    panel: function (el, opts) {
      if (!el) return null;
      opts = opts || {};
      var kind = opts.kind || 'video', id = 'ui-ar-' + (++arSeq);
      el.classList.add('ui-autorun');
      el.innerHTML = '';
      var sum = arEl('span', { 'class': 'ui-ar-sum', id: id + '-sum' });
      var det = arEl('details', { 'class': 'ui-pop ui-ar-pop' });
      var s = arEl('summary', { 'class': 'btn small ghost', 'aria-describedby': id + '-sum' }, '設定を変える');
      var body = arEl('div', { 'class': 'ui-pop-body ui-ar-body', 'data-align': opts.align || 'left' });
      det.appendChild(s); det.appendChild(body);
      el.appendChild(sum); el.appendChild(det);
      var p = { el: el, paint: function () { sum.textContent = arState ? arSummary(arState, kind) : '…'; } };
      det.addEventListener('toggle', function () {
        if (!det.open) return;
        body.textContent = '読み込んでいます…';
        arLoad().then(function () { body.innerHTML = ''; body.appendChild(arForm(kind, opts)); p.paint(); });
      });
      arPanels.push(p);
      if (arState) p.paint(); else arLoad().then(arRepaint, function () {});
      return p;
    },
    /* 始める: 見積もり(estBody があれば)→ やることが 0 なら始めない → path に POST → 終わるまで見て知らせる。-> Promise<応答 | null> */
    start: function (path, body, estBody) {
      var est = estBody ? arHomeApi('api/autorun/estimate', estBody).catch(function () { return null; }) : Promise.resolve(null);
      return est.then(function (e) {
        if (e && e.nothing) { toastFn('やることがありません: ' + (e.reason || ''), { kind: 'info', ms: 8000 }); return null; }
        return arHomeApi(path, body).then(function (j) {
          var runs = j.run ? [j.run] : (j.runs || []);
          for (var i = 0; i < runs.length; i++) arWatched[runs[i].id] = (function () { var b = body; return function () { autorun.start(path, b, estBody); }; })();
          if (runs.length && !arTimer) arTimer = setTimeout(arPoll, 2500);
          var what = runs.length === 1 ? '「' + runs[0].modeLabel + '」' : runs.length + ' 本のまとめて実行';
          toastFn(what + 'を始めました' + (e ? '(' + arEstimateText(e) + ')' : ''), { kind: 'ok', ms: 6000 });
          if (j.skipped && j.skipped.length) toastFn(j.skipped.length + ' 本は始めませんでした: ' + j.skipped[0].reason, { kind: 'info', ms: 8000 });
          return j;
        });
      });
    },
    watch: function (runId, again) { arWatched[runId] = again || null; if (!arTimer) arTimer = setTimeout(arPoll, 2500); },
    estimateText: arEstimateText
  };

  window.UIKit = { version: 8, theme: theme, tools: tools, life: life, report: function (message, info) { return report(message, info, 'report'); }, win: win, fmt: fmt, esc: esc,
                   portal: portal, streamer: streamer, appnav: appnav, drawer: drawer, dialog: dialogApi, toast: toastFn, keybar: keybar, settings: settings, keys: keysApi, keymap: keymapApi, icon: icon,
                   confirmTwice: confirmTwice, prefs: prefs, packLoud: packLoud, autorun: autorun };
})();
